# coding=utf-8
"""보정 입력 읽기 — 대지의 예보 출처(L0)와 위치로 정해진 현장 관측 (설계 §4.1).

**관측은 위치가 정한다.** 대지의 기상 관측 = 도형 상속이 이미 정한 기상원(`device_membership.weather_device_ids` —
지정한 기상원 → 대지 안 기상 장치)의 채널이다. 새 설정 칸은 없다. 센서의 출처 표시(실측·미러·가상·미확인)로 거르지
않는다 — 개발서버의 미러 센서는 현장 실측의 사본이라 똑같이 쓴다. 자동으로 빼는 것은 입력 모듈이 스스로 관측이
아니라고 밝힌 것(`data_origin: model`·`data_time: forecast` — 예보·재분석·시뮬레이터 입력)뿐이다.
대지 트윈 설정(`twin_config`)에 사용자가 직접 고른 기온·비 채널이 있으면 그것이 상속을 덮어쓴다.

`Sources` 는 러너가 부르는 읽기 틈새다. 시험은 같은 모양의 가짜를 넣는다(`aot/tests/test_fc_cal_runner.py`).
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger('aot.fc_cal')

#: 관측 변수 열쇠 — 예보 변수 T·TMAX·TMIN 은 'T', RH 는 'RH', …
OBS_KEY = {'T': 'T', 'TMAX': 'T', 'TMIN': 'T', 'RH': 'RH', 'WS': 'WS', 'SOL': 'SOL', 'RAIN': 'RAIN'}
_ISO = '%Y-%m-%dT%H:%M:%S.%fZ'
_RH_UNITS = ('%', 'percent', 'pct')
_SOL_SCALE = {'w_m2': 1.0, 'w/m2': 1.0, 'wm-2': 1.0, 'w/m²': 1.0, 'w_m^2': 1.0, 'kw_m2': 1000.0, 'kw/m2': 1000.0}
_RH_NAMES = ('humidity', 'relative_humidity')
_SOL_NAMES = ('radiation', 'solar_radiation', 'shortwave_radiation', 'irradiance', 'ghi', 'solar')


def classify_obs(measurement, unit='', name='', medium='air') -> Optional[str]:
    """현장 장치 채널 하나 → 보정 관측 변수('T'·'RH'·'WS'·'SOL'·'RAIN') 또는 None. 좁게 고른다."""
    from aot.space.weather_state import classify_field_measurement
    if medium == 'soil':
        return None
    m = (measurement or '').lower()
    u = (unit or '').strip().lower()
    n = (name or '').lower()
    kind = classify_field_measurement(measurement, unit, name)
    if kind == 'temp':
        return 'T'
    if kind == 'precip':
        return 'RAIN'
    if kind == 'wind_speed':
        return 'WS'
    if (m in _RH_NAMES or any(k in n for k in ('습도', 'humidity'))) and u in _RH_UNITS \
            and 'soil' not in n and '토양' not in n and 'leaf' not in n:
        return 'RH'
    if (m in _SOL_NAMES or any(k in n for k in ('일사', 'solar radiation', 'irradiance'))) and u in _SOL_SCALE:
        return 'SOL'
    return None


def standardize(key, value, unit, name='', driver=None):
    """측정값 → 보정 표준 단위(T °C · RH % · WS m/s · SOL W/m² · RAIN mm/h). 모르면 None."""
    from aot.space.weather_state import to_standard
    if value is None:
        return None
    u = (unit or '').strip().lower()
    if key == 'T':
        return to_standard('temp', value, unit)
    if key == 'WS':
        return to_standard('wind_speed', value, unit)
    if key == 'RAIN':
        return to_standard('precip', value, unit, name, driver)
    if key == 'RH':
        return float(value) if u in _RH_UNITS else None
    if key == 'SOL':
        s = _SOL_SCALE.get(u)
        return None if s is None else float(value) * s
    return None


def _iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime(_ISO)


class InfluxSources:
    """실제 읽기 — Flask 앱 컨텍스트 안에서 쓴다."""

    # ── 대지 ──────────────────────────────────────────────────────────────

    def sites(self) -> List[str]:
        from aot.databases.models import GeoShape
        return [s.unique_id for s in GeoShape.query.filter_by(type='site').all()]

    def has_forecast(self, site_id) -> bool:
        """대지에 예보 출처가 지정돼 있나(점검할 거리가 있나) — 싸게 판정한다."""
        from aot.space import forecast_series as fs
        return bool(fs.designated_ids(site_id))

    def site_tz(self, site_id) -> str:
        from aot.space import forecast_series as fs
        return fs._site_tz_name(site_id)

    def site_info(self, site_id) -> dict:
        """대지의 보정 맥락: 시간대·위치·예보 출처 입력(시간별·일별 각 하나)·관측 채널표."""
        from aot.space import forecast_series as fs
        from aot.databases.models import GeoShape
        ids = fs.designated_ids(site_id)
        hourly_ids, daily = fs.split_kinds(ids)
        lat, lon = fs._site_point(site_id)
        shape = GeoShape.query.filter_by(unique_id=site_id).first()
        obs, src = self._observation_specs(site_id)
        return {'site_id': site_id, 'name': getattr(shape, 'name', None) or site_id,
                'tz': fs._site_tz_name(site_id), 'lat': lat, 'lon': lon,
                'hourly_input': hourly_ids[0] if hourly_ids else None,
                'daily_input': daily[0][0] if daily else None,
                'obs': obs, 'obs_source': src}

    def _observation_specs(self, site_id) -> Tuple[Dict[str, dict], str]:
        from aot.space import device_membership
        from aot.space.weather_state import _effective_unit
        from aot.databases.models import DeviceMeasurements
        from aot.utils.inputs import forecast_time_input_drivers, input_driver_of, model_input_drivers
        skip = set(forecast_time_input_drivers()) | set(model_input_drivers())
        devs, src = device_membership.weather_device_ids(site_id)
        out: Dict[str, dict] = {}
        for dev in devs or []:
            driver = input_driver_of(dev)
            if driver in skip:
                continue                        # 예보·재분석 입력은 관측이 아니다(모듈이 스스로 밝힌다)
            rows = DeviceMeasurements.query.filter(DeviceMeasurements.device_id == dev).order_by(
                DeviceMeasurements.id).all()
            for r in rows:
                meas, unit = _effective_unit(r)
                key = classify_obs(meas, unit, r.name, device_membership.channel_medium(r))
                if key and key not in out and standardize(key, 1.0, unit, r.name, driver) is not None:
                    out[key] = self._spec(r, key, driver)         # 표준 단위로 못 바꾸는 채널(단위 없음 등)은 건너뛴다
        for key, spec in self._twin_overrides(site_id).items():
            if spec['driver'] not in skip:          # 사용자가 골랐어도 모듈이 관측이 아니라고 밝힌 입력은 관측으로 안 쓴다
                out[key] = spec
        return out, src

    @staticmethod
    def _spec(row, key, driver):
        from aot.space.weather_state import _effective_unit
        from aot.databases.models import Conversion
        from aot.utils.system_pi import return_measurement_info
        conv = Conversion.query.filter_by(unique_id=row.conversion_id).first() if row.conversion_id else None
        channel, unit, measurement = return_measurement_info(row, conv)
        _m, std_unit = _effective_unit(row)
        return {'key': key, 'device_id': row.device_id, 'channel': channel, 'unit': unit,
                'measure': measurement, 'std_unit': std_unit or unit, 'name': row.name or '', 'driver': driver}

    def _twin_overrides(self, site_id) -> Dict[str, dict]:
        """사용자가 트윈 설정에서 직접 고른 기온·비 채널은 상속을 덮어쓴다."""
        out: Dict[str, dict] = {}
        try:
            from aot.databases.models import DeviceMeasurements
            from aot.utils import twin_config as TC
            from aot.utils.inputs import input_driver_of
            _en, cfg = TC.read('site', site_id)
            for tkey, key in (('t_air', 'T'), ('rain', 'RAIN')):
                ser = (cfg.get('inputs') or {}).get(tkey)
                if not ser:
                    continue
                row = DeviceMeasurements.query.filter_by(device_id=ser['unique_id'], channel=ser['channel']).first()
                if row is not None:
                    out[key] = self._spec(row, key, input_driver_of(ser['unique_id']))
        except Exception:                                   # noqa: BLE001
            logger.debug('[fc_cal] 트윈 설정 관측 읽기 실패: %s', site_id, exc_info=True)
        return out

    # ── 값 ────────────────────────────────────────────────────────────────

    def fc_hourly(self, input_id, var, t0, t1) -> List[Tuple[float, int, float]]:
        from aot.utils import fc_store, influx
        rows = influx.read_layer_points(fc_store.M_HOURLY, input_id, {'var': var}, t0, t1)
        return [(ts, int(tags['lead_h']), v) for ts, v, tags in rows if tags.get('lead_h') is not None]

    def fc_daily(self, input_id, var, t0, t1) -> List[Tuple[float, int, float]]:
        from aot.utils import fc_store, influx
        rows = influx.read_layer_points(fc_store.M_DAILY, input_id, {'var': var}, t0, t1)
        return [(ts, int(tags['lead_d']), v) for ts, v, tags in rows if tags.get('lead_d') is not None]

    def obs_hourly(self, spec, t0, t1, fn='mean') -> Dict[float, float]:
        """관측 채널의 시간 값 → {창 끝 정시 epoch: 표준 단위 값}. 창 = 직전 1시간. 기록이 없는 시간은 빠진다."""
        from aot.utils import influx
        tables = influx.query_flux(spec['unit'], spec['device_id'], measure=spec.get('measure'),
                                   channel=spec['channel'], start_str=_iso(t0), end_str=_iso(t1),
                                   group_sec=3600, group_fn=fn)
        out: Dict[float, float] = {}
        for tb in tables or []:
            for rec in tb.records:
                v = standardize(spec['key'], rec.get_value(), spec['std_unit'], spec.get('name', ''),
                                spec.get('driver'))
                if v is not None:
                    out[rec.get_time().timestamp()] = float(v)
        return out
