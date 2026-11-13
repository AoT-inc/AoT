# coding=utf-8
"""디지털트윈(실험) 대지·구획 설정 — 저장·상속·제안·판정 (배포 제안 개정 2 §2·§4·§5, S3).

정본은 `twin_config` 표(`aot/databases/models/twin_config.py`). 이 모듈이 그 표를 읽고 쓰는 유일한 곳이다.

- **상속**: 대지 → 구획. 구획 행에 키가 없으면 대지 값을 쓰고, 있으면 덮어쓴다(null = "여기서는 없음").
  서비스(`aot.twin.discovery`)는 `overrides()` 가 돌려주는 사전을 그대로 받는다(모양은 S2 덮어쓰기 JSON 과 같다).
- **제안**: 예보 입력(채널 메타 `forecast_lead_d` 를 밝힌 입력 — 제공자 이름을 보지 않는다), 대지 비·기온(대지에
  기상대로 *지정된* 장치의 채널), 구획 관측 센서(구획 안이나 30 m 안 마커의 토양 채널). **제안은 저장하지 않는다** —
  사용자가 '적용' 할 때만 설정이 된다(사용자 지침 2026-10-19 "사용자가 모든 걸 정한다").
- **출처 표시**: 실측·미러·가상·미확인. 사람이 정한다. 동기화·검증에는 실측만 쓴다(`aot.twin.engine`).
  입력 모듈이 `INPUT_INFORMATION['provenance']` 를 밝혔으면 그것을 제안값으로, 아니면 '미확인'.

지역·제공자 이름은 이 모듈에 없다. 순수 함수(`merge`·`effective`·`validate_config`·`distance_m`·`verdict`)는
DB 없이 시험한다.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from aot.utils.timekit import naive_utc, utc_now

logger = logging.getLogger(__name__)

PROVENANCES = ('measured', 'mirror', 'virtual', 'unknown')
#: 대지에서 고르는 출처(구획이 물려받는다) · 구획에서 고르는 관측.
SITE_INPUTS = ('rain', 't_air', 'et0')
PLOT_INPUTS = ('theta', 'soil_t')
INPUT_KEYS = SITE_INPUTS + PLOT_INPUTS
RAIN_AGGS = ('hourly_mean_sum', 'daily_sum', 'daily_last')
#: 센서 없는 구획: predict = 관측 없이 모델만(참고용, 기본) · off = 계산하지 않음. 모델 쪽 이름과 같다.
SENSORLESS_MODES = ('predict', 'off')
#: 관측 센서 제안 반경 — 구획 경계에서 이만큼 안의 마커까지 본다.
SENSOR_RADIUS_M = 30.0
#: 제안 표에 싣는 후보 수 상한(입력마다).
MAX_SUGGESTIONS = 5
#: 구획 안·반경 안·구역 대표 센서가 모두 없을 때 가장 가까운 센서까지 보는 한계(구획 경계에서, m).
SENSOR_FALLBACK_M = 2000.0
#: 대지 기상대(비·기온)를 못 찾을 때 같은 지도에서 가장 가까운 기상 채널까지 보는 한계(대지 중심에서, m).
WEATHER_FALLBACK_M = 20000.0
#: 이 거리(km) 안에 켜진 예보 입력이 없으면 대지에 새로 만들기를 권한다.
FORECAST_NEAR_KM = 10.0


class TwinConfigError(ValueError):
    """저장하려는 설정이 계약에 맞지 않는다(화면이 그대로 보여 준다)."""


def ui_enabled(misc=None) -> bool:
    """트윈 화면·읽기 API 게이트: 설정 > 일반 플래그 AND 안 잠김(`twin_gate.twin_enabled`, S1 정본).

    옛 개발 설정(`AOT_TWIN_ENABLED`·`Misc.twin_mode`)은 수신 API 와 함께 걷어 냈다(계획서 §9.19).
    `misc` 는 예전 호출 모양을 받으려고 남긴 인자다(쓰지 않는다).
    """
    try:
        from aot.utils import twin_gate
        return bool(twin_gate.twin_enabled())
    except Exception:
        logger.exception('트윈 게이트 판정 실패 — 꺼진 것으로 본다')
        return False


# ── 순수 함수 ─────────────────────────────────────────────────────────────────

def merge(a: Mapping, b: Mapping) -> Dict:
    """사전끼리는 안으로 들어가 합치고, 그 밖(null 포함)은 b 가 이긴다 — discovery._merge 와 같은 규칙."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def effective(site_cfg: Mapping, plot_cfg: Mapping) -> Dict[str, Dict]:
    """입력·예보마다 {value, origin} — origin 은 'plot'·'site'·None(아무도 안 고름).

    화면이 "대지에서 물려받음" 과 "이 구획에서 덮어씀" 을 나눠 보이는 데 쓴다.
    """
    s_in = (site_cfg or {}).get('inputs') or {}
    p_in = (plot_cfg or {}).get('inputs') or {}
    out: Dict[str, Dict] = {}
    for k in INPUT_KEYS:
        if k in p_in:
            out[k] = {'value': p_in[k], 'origin': 'plot'}
        elif k in s_in:
            out[k] = {'value': s_in[k], 'origin': 'site'}
        else:
            out[k] = {'value': None, 'origin': None}
    if 'forecast' in (plot_cfg or {}):
        out['forecast'] = {'value': plot_cfg['forecast'], 'origin': 'plot'}
    elif 'forecast' in (site_cfg or {}):
        out['forecast'] = {'value': site_cfg['forecast'], 'origin': 'site'}
    else:
        out['forecast'] = {'value': None, 'origin': None}
    return out


def _series(d, key: str) -> Optional[Dict]:
    if d is None:
        return None
    if not isinstance(d, Mapping):
        raise TwinConfigError('%s: 객체여야 한다' % key)
    uid = str(d.get('unique_id') or '').strip()
    if not uid:
        raise TwinConfigError('%s: 장치(unique_id)가 없다' % key)
    try:
        ch = int(d.get('channel', 0))
    except (TypeError, ValueError):
        raise TwinConfigError('%s: 채널은 정수' % key)
    prov = str(d.get('provenance') or 'unknown')
    if prov not in PROVENANCES:
        raise TwinConfigError('%s: 출처 표시는 %s 중 하나' % (key, '·'.join(PROVENANCES)))
    out = {'unique_id': uid, 'unit': str(d.get('unit') or ''), 'channel': ch, 'provenance': prov}
    if not out['unit']:
        raise TwinConfigError('%s: 단위가 없다' % key)
    return out


def validate_config(cfg: Mapping, scope: str) -> Dict:
    """저장 전 검사·정리. 모르는 키는 버리지 않고 거부한다(조용히 사라지면 사용자가 모른다)."""
    if scope == 'facility':                                  # 시설은 칸이 다르다 — 규칙은 시설 모듈에
        from aot.utils.twin_facility_config import validate_config as _validate_facility
        return _validate_facility(cfg)
    if cfg is None:
        return {}
    if not isinstance(cfg, Mapping):
        raise TwinConfigError('설정은 객체여야 한다')
    unknown = set(cfg) - {'inputs', 'options', 'forecast', 'effects'}
    if unknown:
        raise TwinConfigError('모르는 항목: %s' % ', '.join(sorted(unknown)))
    out: Dict = {}
    if 'inputs' in cfg:
        ins = cfg.get('inputs') or {}
        if not isinstance(ins, Mapping):
            raise TwinConfigError('inputs 는 객체여야 한다')
        bad = set(ins) - set(INPUT_KEYS)
        if bad:
            raise TwinConfigError('모르는 입력: %s' % ', '.join(sorted(bad)))
        out['inputs'] = {k: _series(v, k) for k, v in ins.items()}
    if 'options' in cfg:
        opts = cfg.get('options') or {}
        if not isinstance(opts, Mapping):
            raise TwinConfigError('options 는 객체여야 한다')
        rain = opts.get('rain')
        if rain is not None:
            if not isinstance(rain, Mapping):
                raise TwinConfigError('options.rain 은 객체여야 한다')
            if 'agg' in rain and rain['agg'] not in RAIN_AGGS:
                raise TwinConfigError('비 묶는 법은 %s 중 하나' % '·'.join(RAIN_AGGS))
            if 'scale' in rain:
                try:
                    sc = float(rain['scale'])
                except (TypeError, ValueError):
                    raise TwinConfigError('비 배율은 수')
                if not (0 < sc <= 100):
                    raise TwinConfigError('비 배율은 0 보다 크고 100 이하')
        sl = opts.get('sensorless')
        if sl is not None and sl not in SENSORLESS_MODES:
            raise TwinConfigError('센서 없는 구획은 %s 중 하나' % '·'.join(SENSORLESS_MODES))
        sp = opts.get('spinup_from')
        if sp is not None and sp != '':
            try:
                datetime.strptime(str(sp), '%Y-%m-%d')
            except ValueError:
                raise TwinConfigError('동화 시작일은 YYYY-MM-DD')
        json.dumps(opts)                                     # 저장 가능한 값인지
        out['options'] = dict(opts)
    if cfg.get('effects') is not None:
        if scope != 'site':
            raise TwinConfigError('장치 역할은 대지에서 정한다')
        from aot.utils.twin_effects_link import validate_overrides
        eff = validate_overrides(cfg['effects'], 'field')
        if eff:
            out['effects'] = eff
    if 'forecast' in cfg and scope == 'plot':
        raise TwinConfigError('예보 출처는 대지에서 정한다(기상원·예보 출처 지정) — 구획마다 다르게 두지 않는다')
    if 'forecast' in cfg:
        fc = cfg.get('forecast')
        if fc is None:
            out['forecast'] = None
        else:
            if not isinstance(fc, Mapping) or not str(fc.get('input') or '').strip():
                raise TwinConfigError('예보는 {"input": 입력 id} 이거나 null')
            f2 = {'input': str(fc['input']).strip()}
            if 'max_age_h' in fc:
                try:
                    f2['max_age_h'] = float(fc['max_age_h'])
                except (TypeError, ValueError):
                    raise TwinConfigError('예보 max_age_h 는 수')
            out['forecast'] = f2
    return out


def distance_m(polygon_geojson: Mapping, lng: float, lat: float) -> Optional[float]:
    """점과 폴리곤의 거리(m). 안이면 0. 구획 크기(수백 m)에서는 등장방형 근사로 충분하다."""
    from shapely.geometry import Point, shape as shapely_shape
    from shapely.ops import transform
    try:
        poly = shapely_shape(polygon_geojson)
    except Exception:
        return None
    if poly.is_empty:
        return None
    c = poly.representative_point()
    lat0 = math.radians(c.y)
    kx, ky = 111320.0 * math.cos(lat0), 110540.0

    def proj(x, y, z=None):
        return ((x - c.x) * kx, (y - c.y) * ky)

    try:
        pm = transform(proj, poly)
        pt = Point(*proj(lng, lat))
        return 0.0 if pm.contains(pt) else float(pm.distance(pt))
    except Exception:
        return None


def channel_kinds(measurement: str, unit: str, name: str = '', medium: str = '') -> List[str]:
    """채널 하나가 어느 트윈 입력이 될 수 있나(후보 거르기용, 좁게). 결정은 사용자가 한다."""
    from aot.space.weather_state import classify_field_measurement
    m = (measurement or '').lower()
    u = (unit or '').lower()
    hay = (m + ' ' + (name or '')).lower()
    out: List[str] = []
    if medium == 'soil':
        if m in ('volumetric_water_content', 'soil_moisture', 'moisture') or (
                m not in ('temperature', 'soil_temperature', 'electrical_conductivity', 'soil_ec')
                and u in ('percent', '%', 'm3_m3', 'cm3_cm3')):
            out.append('theta')
        if m in ('temperature', 'soil_temperature'):
            out.append('soil_t')
        return out
    kind = classify_field_measurement(measurement, unit, name)
    if kind == 'precip':
        out.append('rain')
    if kind == 'temp':
        out.append('t_air')
    if 'evapotranspiration' in hay or m in ('et0', 'eto', 'reference_et'):
        out.append('et0')
    return out


def sensorless_mode(site_cfg: Mapping, plot_cfg: Mapping) -> str:
    """센서 없는 구획을 어떻게 하나 — 구획 값이 대지 값을 덮고, 없으면 'predict'(관측 없이 모델만)."""
    for cfg in (plot_cfg, site_cfg):
        v = ((cfg or {}).get('options') or {}).get('sensorless')
        if v in SENSORLESS_MODES:
            return v
    return 'predict'


# @manual geo/map-widget#twin-tab
def verdict(site_enabled: bool, site_cfg: Mapping, plots: Sequence[Mapping],
            excluded: Optional[Mapping] = None) -> Dict[str, object]:
    """대지 한 곳의 판정 — 제안 표·트윈 탭의 한 줄. plots 는 [{included, effective, sensorless?}].

    code: off · no_plots · no_rain · rain_not_observation · no_sensor · sensorless · partial · ready. 막힌 이유를 차례로 하나만 말한다.
    `excluded` = 대지 칸 중 관측이 아니라 동기화에서 빠지는 것 `{칸: 이유}`, 구획의 `excluded` 도 같다(토양수분이 그러면 센서 없는 구획으로 센다).
    `sensorless` = 센서가 있는 구획이 하나도 없지만 센서 없는 구획을 관측 없이 예측만 하는 중(참고용).
    """
    inc = [p for p in plots if p.get('included', True)]
    ready = 0
    unverified = 0
    free = 0
    for p in inc:
        th = ((p.get('effective') or {}).get('theta') or {}).get('value')
        if th and not (p.get('excluded') or {}).get('theta'):
            ready += 1                           # 위치(도형 상속)로 정해진 센서는 출처 표시 없이 그대로 쓴다
        elif p.get('sensorless', 'predict') != 'off':
            free += 1
    rain = ((site_cfg or {}).get('inputs') or {}).get('rain')
    fc = (site_cfg or {}).get('forecast')
    if not site_enabled:
        code = 'off'
    elif not inc:
        code = 'no_plots'
    elif not rain:
        code = 'no_rain'
    elif (excluded or {}).get('rain'):
        code = 'rain_not_observation'
    elif not ready and not free:
        code = 'no_sensor'
    elif not ready:
        code = 'sensorless'
    elif ready < len(inc):
        code = 'partial'
    else:
        code = 'ready'
    return {'code': code, 'plots': len(inc), 'ready': ready, 'unverified': unverified,
            'sensorless': free, 'forecast': bool(fc)}


# @manual geo/map-widget#twin-tab
def diagnose_plot(site_enabled: bool, entry: Mapping, n_sensor_suggestions: Optional[int] = None) -> str:
    """구획 하나가 왜 지금 그렇게 도는지(또는 못 도는지) 코드 하나 — 화면이 원인과 할 일을 같이 적는다.

    entry 는 `_plot_entry` 의 결과(+ `sensorless` 방식). `n_sensor_suggestions` 는 구획 센서 제안 수
    (모르면 None — 제안이 있는지 말하지 않는다). 차례대로 첫 번째만:
    excluded · site_off · no_planted · no_rain · rain_not_observation · sensor_not_observation(예보·모델값·시뮬레이터라
    동기화에서 빠짐) · synced · suggest_sensor ·
    sensorless(관측 없이 예측만, 참고용) · sensorless_off(센서 없어서 계산 안 함).
    """
    if not entry.get('included', True):
        return 'excluded'
    if not site_enabled:
        return 'site_off'
    if not entry.get('started_on'):
        return 'no_planted'
    eff = entry.get('effective') or {}
    if not (eff.get('rain') or {}).get('value'):
        return 'no_rain'
    exc = entry.get('excluded') or {}
    if exc.get('rain'):
        return 'rain_not_observation'
    th = (eff.get('theta') or {}).get('value')
    if th:
        return 'sensor_not_observation' if exc.get('theta') else 'synced'
    if n_sensor_suggestions:
        return 'suggest_sensor'
    return 'sensorless_off' if entry.get('sensorless') == 'off' else 'sensorless'


# ── DB ──────────────────────────────────────────────────────────────────────────

def _model():
    from aot.databases.models import TwinConfig
    return TwinConfig


def get_row(scope: str, target_id: str):
    return _model().query.filter_by(scope=scope, target_id=str(target_id)).first()


def read(scope: str, target_id: str) -> Tuple[Optional[bool], Dict]:
    """한 행 읽기. 대지의 `forecast` 는 표가 아니라 **대지 예보 출처 지정**(`geo_binding`)에서 온다 — 기상원 지정
    화면·지도 날씨·AI 와 같은 저장소다(`site_forecast_choice`)."""
    row = get_row(scope, target_id)
    enabled, cfg = (None, {}) if row is None else (row.enabled, row.config_dict())
    if scope == 'site':
        cfg = {k: v for k, v in cfg.items() if k != 'forecast'}
        choice = site_forecast_choice(target_id)
        if choice:
            cfg['forecast'] = {'input': choice}
    return enabled, cfg


def site_forecast_choice(site_id: str) -> Optional[str]:
    """대지 예보 출처 지정 중 트윈 탭 예보 칸에 보일 입력 — 첫 일별 입력(트윈 일 격자의 주 출처), 없으면 첫 지정."""
    try:
        from aot.space import forecast_series as fs
        ids = fs.designated_ids(site_id)
        _hourly, daily = fs.split_kinds(ids)
        return daily[0][0] if daily else (ids[0] if ids else None)
    except Exception:
        logger.exception('트윈: 대지 %s 예보 출처 읽기 실패', site_id)
        return None


def set_site_forecast_choice(site_id: str, input_id: Optional[str]) -> None:
    """트윈 탭 예보 칸 저장 → 대지 예보 출처 지정. 고른 입력이 같은 종류(시간별·일별)의 지정을 대신하고, 다른 종류
    지정은 그대로 둔다(예: 시간별 입력 + 트윈이 고른 일별 입력). None 이면 일별 지정만 뺀다."""
    from aot.space import device_binding, forecast_series as fs
    ids = fs.designated_ids(site_id)
    if input_id and input_id in ids:
        return                    # 이미 지정돼 있다 — 순서(시간별 → 일별)를 흔들지 않는다(예전 화면이 칸을 그대로 되보낼 때)
    hourly, daily = fs.split_kinds(ids)
    daily_ids = [d for d, _drv in daily]
    if input_id:
        new_hourly, new_daily = fs.split_kinds([input_id])
        same = daily_ids if new_daily else hourly
        want = [input_id] + [d for d in ids if d != input_id and d not in same]
    else:
        want = [d for d in ids if d not in daily_ids]
    if want != device_binding.site_forecast_ids(site_id):
        device_binding.set_site_forecast(site_id, want)


def save(scope: str, target_id: str, enabled=None, config: Optional[Mapping] = None,
         *, set_enabled: bool = False, replace: bool = True):
    """한 행 쓰기. `replace` 면 config 를 통째로, 아니면 키 단위로 합친다(빈 칸 채우기 등)."""
    from aot.aot_flask.extensions import db
    if scope not in ('site', 'plot', 'facility'):
        raise TwinConfigError('scope 는 site·plot·facility')
    target_id = str(target_id or '').strip()
    if not target_id or len(target_id) > 80:
        raise TwinConfigError('대상 id 가 없다')
    clean = validate_config(config, scope) if config is not None else None
    if clean is not None and scope == 'site' and 'forecast' in clean:
        # 예보 칸은 이 표에 두지 않는다 — 대지 예보 출처 지정(기상원 지정 화면과 같은 행)에 쓴다
        fc = clean.pop('forecast')
        set_site_forecast_choice(target_id, (fc or {}).get('input'))
    M = _model()
    row = get_row(scope, target_id)
    if row is None:
        row = M(scope=scope, target_id=target_id)
        db.session.add(row)
    if set_enabled:
        row.enabled = None if enabled is None else bool(enabled)
    if clean is not None:
        merged = clean if replace else merge(row.config_dict(), clean)
        if scope == 'site':
            merged = {k: v for k, v in merged.items() if k != 'forecast'}
        row.set_config(merged)
    else:
        row.updated_at = naive_utc(utc_now())
    db.session.commit()
    return row


def overrides() -> Dict[str, Dict]:
    """서비스가 읽는 모양 `{"sites": {id: {...}}, "plots": {id: {...}}, "facilities": {id: {...}}}`
    (S2 덮어쓰기 JSON 과 같다. 시설은 상속 없이 자기 행만)."""
    out: Dict[str, Dict] = {'sites': {}, 'plots': {}, 'facilities': {}}
    table = {'site': 'sites', 'plot': 'plots', 'facility': 'facilities'}
    for r in _model().query.all():
        d = r.config_dict()
        if r.enabled is not None:
            d['enabled'] = bool(r.enabled)
        out[table.get(r.scope, 'plots')][r.target_id] = d
    return out


# ── 카탈로그(서비스와 같은 정본) ─────────────────────────────────────────────────

def catalog_sites():
    """켜고 끌 수 있는 대지와 그 안의 재배 중 노지 구획 — 서비스(`DbCatalog`)와 같은 목록.
    시설만 있는 대지는 노지 설정 대상이 아니다(시설은 `twin_facility_config` 가 따로 본다)."""
    from aot.twin.discovery import DbCatalog
    return [s for s in DbCatalog(None)._sites() if s.plots]


def _plot_rows(ids: Iterable[str]) -> Dict[str, object]:
    from aot.databases.models import GeoPlot
    ids = list(ids)
    if not ids:
        return {}
    return {p.unique_id: p for p in GeoPlot.query.filter(GeoPlot.unique_id.in_(ids)).all()}


def site_of_plot(plot_id: str, sites=None):
    for s in (sites if sites is not None else catalog_sites()):
        for p in s.plots:
            if p.unique_id == plot_id:
                return s
    return None


# ── 채널 목록·제안 ──────────────────────────────────────────────────────────────

_INFO_TTL_S = 300.0
_info_cache: Dict[str, object] = {'fn': None, 'at': 0.0, 'val': None}


def _input_info():
    """입력 모듈 정보(`parse_input_information`) — 모듈 파일을 전부 읽어 한 번에 0.2 초라, 한 화면(대지 + 구획 여럿의
    제안)에서 열네 번 부르면 3 초가 걸렸다. 모듈은 실행 중에 바뀌지 않으니 5 분 캐시한다(함수가 바뀌면 — 시험의
    patch — 다시 읽는다)."""
    import time as _time
    from aot.utils.inputs import parse_input_information
    now = _time.time()
    c = _info_cache
    if c['fn'] is parse_input_information and c['val'] is not None and now - float(c['at']) < _INFO_TTL_S:
        return c['val']
    val = parse_input_information()
    c.update(fn=parse_input_information, at=now, val=val)
    return val


def _device_names(ids: Iterable[str]) -> Dict[str, Tuple[str, str]]:
    """장치 id → (이름, 모듈 이름). 입력·함수만 본다(트윈 출처가 될 측정을 내는 쪽)."""
    from aot.databases.models import CustomController, Input
    ids = set(ids)
    out: Dict[str, Tuple[str, str]] = {}
    if not ids:
        return out
    for r in Input.query.filter(Input.unique_id.in_(ids)).all():
        out[r.unique_id] = (r.name or r.unique_id, r.device or '')
    for r in CustomController.query.filter(CustomController.unique_id.in_(ids)).all():
        out.setdefault(r.unique_id, (r.name or r.unique_id, r.device or ''))
    return out


def provenance_hint(module: str, info=None) -> str:
    """입력 모듈이 스스로 밝힌 출처 표시(`INPUT_INFORMATION['provenance']`), 없으면 미확인."""
    info = info if info is not None else _input_info()
    p = str(((info or {}).get(module) or {}).get('provenance') or 'unknown')
    return p if p in PROVENANCES else 'unknown'


def exclusions(inputs: Optional[Mapping]) -> Dict[str, Dict[str, object]]:
    """계열 모음 `{논리 이름: {unique_id, channel, ...}}` 중 **관측이 아닌** 것 → `{논리 이름: {reason, name, unique_id}}`.

    판정은 `aot.twin.obs_basis.non_observation_reason` 하나(입력 모듈이 밝힌 성질만 — 예보·모델값·시뮬레이터).
    설정을 읽지 않고 장치 정보만 본다. 못 읽으면 빈 사전 — 기존 입력을 이유 없이 빼지 않는다."""
    from aot.twin.obs_basis import non_observation_reason
    ser = {k: v for k, v in (inputs or {}).items() if isinstance(v, Mapping) and v.get('unique_id')}
    if not ser:
        return {}
    try:
        names = _device_names({v['unique_id'] for v in ser.values()})
        info = _input_info()
    except Exception:
        logger.exception('트윈: 관측 여부 판정용 장치 정보 읽기 실패')
        return {}
    out: Dict[str, Dict[str, object]] = {}
    for k, v in ser.items():
        nm = names.get(v['unique_id'])
        reason = non_observation_reason(nm[1], info, v.get('channel')) if nm else None
        if reason:
            out[k] = {'reason': reason, 'name': nm[0], 'unique_id': v['unique_id']}
    return out


def _drop_non_observations(cfg: Optional[Mapping], plot: bool = False) -> Dict:
    """설정 한 장의 `inputs` 에서 관측이 아닌 계열을 빼고 `excluded` 로 이유를 남긴 사본. 구획은 null 로 비워(대지 값으로
    되돌아가지 않게) 둔다. 빠진 것이 없으면 그대로."""
    cfg = dict(cfg or {})
    exc = exclusions(cfg.get('inputs'))
    if not exc:
        return cfg
    ins = dict(cfg['inputs'])
    for k in exc:
        if plot:
            ins[k] = None
        else:
            del ins[k]
    return dict(cfg, inputs=ins, excluded=dict(cfg.get('excluded') or {}, **exc))


def _conversions(rows) -> Dict[str, object]:
    """채널에 걸린 단위 변환 `{conversion_id: Conversion}` — 저장 단위를 알려면 필요하다."""
    ids = {r.conversion_id for r in rows if getattr(r, 'conversion_id', None)}
    if not ids:
        return {}
    from aot.databases.models import Conversion
    return {c.unique_id: c for c in Conversion.query.filter(Conversion.unique_id.in_(ids)).all()}


def stored_unit(dm, conversions: Optional[Mapping] = None) -> str:
    """측정 채널의 **저장 단위** — 변환이 걸린 채널(예: 미러 온도 F→C)은 변환 뒤 단위로 저장된다.
    계열을 읽는 쪽(`SeriesRef.unit`)은 저장 단위로 찾으므로, 제안·검증은 원 단위(`dm.unit`)가 아니라 이것을 쓴다."""
    from aot.utils.system_pi import return_measurement_info
    conv = (conversions or {}).get(getattr(dm, 'conversion_id', None))
    return return_measurement_info(dm, conv)[1] or dm.unit or ''


def channels(device_ids: Optional[Iterable[str]] = None) -> List[Dict[str, object]]:
    """고를 수 있는 채널 전부(또는 주어진 장치만) — 트윈 입력 후보 종류(`kinds`)를 붙여서."""
    from aot.space.device_membership import channel_medium
    from aot.databases.models import DeviceMeasurements
    q = DeviceMeasurements.query
    if device_ids is not None:
        ids = [str(d).split('::')[0] for d in device_ids if d]
        if not ids:
            return []
        q = q.filter(DeviceMeasurements.device_id.in_(ids))
    rows = q.all()
    names = _device_names({r.device_id for r in rows})
    info = _input_info()
    convs = _conversions(rows)
    out = []
    for r in rows:
        if r.device_id not in names:
            continue
        dname, module = names[r.device_id]
        medium = channel_medium(r)
        unit = stored_unit(r, convs)
        out.append({
            'unique_id': r.device_id, 'device_name': dname, 'channel': int(r.channel or 0),
            'name': r.name or '', 'measurement': r.measurement or '', 'unit': unit,
            'enabled': bool(getattr(r, 'is_enabled', True)), 'medium': medium,
            # 예보 채널(모듈이 forecast_lead_d 를 밝힌 채널)은 관측 출처 후보가 아니다 — 예보 입력으로 고른다
            'kinds': [] if _is_forecast_channel(info, module, r.channel) else
                     channel_kinds(r.measurement or '', unit, r.name or '', medium),
            'provenance_hint': provenance_hint(module, info)})
    out.sort(key=lambda c: (c['device_name'], c['channel']))
    return out


def _is_forecast_channel(info, module: str, channel) -> bool:
    md = ((info or {}).get(module) or {}).get('measurements_dict') or {}
    meta = md.get(channel) if isinstance(md, Mapping) else None
    if meta is None and isinstance(md, Mapping):
        meta = md.get(str(channel))
    return isinstance(meta, Mapping) and meta.get('forecast_lead_d') is not None


def _collect_ids(obj, out: set) -> set:
    """설정·상속·제안 묶음 안의 장치·입력 id 전부."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k in ('unique_id', 'input') and isinstance(v, str):
                out.add(v)
            else:
                _collect_ids(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_ids(v, out)
    return out


def with_names(view: Dict) -> Dict:
    """화면이 id 대신 장치 이름을 보이도록 `names` {id: 이름} 를 붙인다."""
    ids = _collect_ids({k: view.get(k) for k in ('config', 'site_config', 'effective', 'used', 'plots', 'suggestions')}, set())
    view['names'] = {k: v[0] for k, v in _device_names(ids).items()}
    return view


def _as_series(c: Mapping) -> Dict[str, object]:
    return {'unique_id': c['unique_id'], 'unit': c['unit'], 'channel': c['channel'],
            'provenance': c.get('provenance_hint') or 'unknown'}


def forecast_inputs(lat: Optional[float] = None, lng: Optional[float] = None) -> List[Dict[str, object]]:
    """예보 입력 후보 — 채널 메타에 `forecast_lead_d` 를 밝힌 입력 모듈의 입력. 가까운 순(좌표가 있으면).

    어느 제공자인지는 보지 않는다. 같은 메타를 밝힌 새 입력 모듈은 코드 변경 없이 후보가 된다.
    """
    from aot.databases.models import Input
    from aot.utils.timekit import resolve_coords
    info = _input_info()
    mods = {k for k, v in (info or {}).items()
            if any(isinstance(m, Mapping) and m.get('forecast_lead_d') is not None
                   for m in ((v or {}).get('measurements_dict') or {}).values())}
    if not mods:
        return []
    out = []
    for r in Input.query.filter(Input.device.in_(mods)).all():
        d = None
        # 좌표는 배치에서 푼다(L4 S3c) — 장치 행에 위치 컬럼이 없다. 마커가 있으면
        # 그 지점, 없으면 대지/농장 상속(또는 없음).
        rlat, rlng, _src = resolve_coords(r)
        if lat is not None and lng is not None and rlat is not None and rlng is not None:
            d = _haversine_km(lat, lng, rlat, rlng)
        out.append({'input': r.unique_id, 'name': r.name or r.unique_id, 'module': r.device,
                    'active': bool(r.is_activated), 'distance_km': None if d is None else round(d, 1)})
    out.sort(key=lambda x: (not x['active'], x['distance_km'] is None, x['distance_km'] or 0.0, x['name']))
    return out


def _forecast_modules(info=None) -> Dict[str, int]:
    """예보 채널(`forecast_lead_d`)을 밝힌 입력 모듈 → 가장 먼 리드(일)."""
    info = info if info is not None else _input_info()
    out: Dict[str, int] = {}
    for k, v in (info or {}).items():
        leads = [m.get('forecast_lead_d') for m in ((v or {}).get('measurements_dict') or {}).values()
                 if isinstance(m, Mapping) and m.get('forecast_lead_d') is not None]
        if leads:
            out[k] = max(int(x) for x in leads)
    return out


def forecast_module(info=None) -> Optional[str]:
    """새 예보 입력을 만들 때 쓸 모듈 — 채널 메타로만 고른다(제공자 이름은 보지 않는다): 가장 먼 리드, 같으면 이름순."""
    mods = _forecast_modules(info)
    if not mods:
        return None
    return sorted(mods, key=lambda m: (-mods[m], m))[0]


def forecast_module_label(module: str, info=None) -> str:
    info = info if info is not None else _input_info()
    v = (info or {}).get(module) or {}
    return str(v.get('input_name_short') or v.get('input_name') or module)


def create_forecast_input(lat: float, lng: float, name: str = '', activate: bool = True,
                          map_uuid: str = None) -> str:
    """좌표에 예보 입력을 만든다 — 지도·설정 화면에서 입력을 추가하는 것과 같은 결과(기본값·채널·활성화).

    좌표는 **배치(마커)로 둔다** — 장치는 더 이상 위치 컬럼을 들지 않는다(L4 S3c).
    `map_uuid` 를 주면 그 지도에 마커를 놓아 바인딩을 만든다(수동으로 지도에 찍는
    것과 같은 경로). 지도를 모르면 배치 없이 만들고(리졸버가 대지/농장으로 상속),
    사람이 나중에 설정 화면의 지도에서 찍는다.

    모듈은 `forecast_module()` 이 채널 메타로 고른다. 반환: 새 입력의 unique_id. 못 만들면 TwinConfigError.
    """
    from aot.aot_flask.extensions import db
    from aot.aot_flask.utils.utils_general import controller_activate_deactivate, custom_options_return_json
    from aot.aot_flask.utils.utils_input import check_input_channels_exist
    from aot.databases import set_uuid
    from aot.databases.models import Input

    info = _input_info()
    mod = forecast_module(info)
    if not mod:
        raise TwinConfigError('예보를 내는 입력 모듈이 없다')
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise TwinConfigError('좌표를 알 수 없다')
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise TwinConfigError('좌표가 범위를 벗어났다')
    spec = info[mod]
    new = Input()
    new.device = mod
    if spec.get('interfaces'):
        new.interface = spec['interfaces'][0]
    new.name = (name or forecast_module_label(mod, info))[:64]
    max_pos = db.session.query(db.func.max(Input.position_y)).scalar()
    new.position_y = (max_pos or 0) + 1
    if spec.get('period'):
        new.period = spec['period']
    errs, opts = custom_options_return_json([], info, device=mod, use_defaults=True)
    if errs:
        raise TwinConfigError('입력 기본값을 만들지 못했다: %s' % errs[0])
    new.custom_options = opts
    new.unique_id = set_uuid()
    new.save()
    # 좌표는 마커 배치로 둔다 — 장치 행에 위치 컬럼이 없다(L4 S3c). 지도를 알면
    # 지금 놓고, 모르면 사람이 설정 화면 지도에서 찍는다(그때까지 대지/농장 상속).
    if map_uuid:
        try:
            from aot.aot_flask.geo.device_placement import place_device
            if place_device(new.unique_id, map_uuid, lat, lng,
                            device_type='input', name=new.name, commit=True) is None:
                logger.warning('트윈: 예보 입력 %s 를 지도 %s 에 배치하지 못했다',
                               new.unique_id, map_uuid)
        except Exception as exc:
            logger.warning('트윈: 예보 입력 %s 마커 배치 실패: %s', new.unique_id, exc)
    msgs = check_input_channels_exist(info, mod, new.unique_id,
                                      {'success': [], 'info': [], 'warning': [], 'error': []})
    if msgs.get('error'):
        raise TwinConfigError('입력 채널을 만들지 못했다: %s' % msgs['error'][0])
    if activate:
        res = controller_activate_deactivate({'success': [], 'info': [], 'warning': [], 'error': []},
                                             'activate', 'Input', new.unique_id, flash_message=False)
        if res.get('error'):
            logger.warning('트윈: 새 예보 입력 %s 를 켜지 못했다: %s', new.unique_id, res['error'][0])
    return new.unique_id


def ensure_site_forecast(site_id: str, sites=None) -> Optional[str]:
    """대지에 가까운 켜진 예보 입력이 없으면 만들고, 대지 설정의 예보 칸이 비어 있으면 그 입력으로 채운다.

    이미 예보를 정해 뒀거나 가까운 것이 있으면 아무것도 안 한다. 반환: 새로 만든 입력 id 또는 None.
    좌표는 대지의 구획 중심 — 사용자가 입력 설정에서 고칠 수 있다.
    """
    sites = sites if sites is not None else catalog_sites()
    site = next((s for s in sites if s.site_id == site_id), None)
    if site is None:
        return None
    _, cfg = read('site', site_id)
    if cfg.get('forecast'):
        return None
    sug = site_suggestions(site)
    create = sug.get('forecast_create')
    if not create:
        # 가까운 것이 이미 있다 — 칸이 비어 있으면 가장 앞 제안으로 채운다(빈 칸만)
        if sug.get('forecast'):
            save('site', site_id, config={'forecast': {'input': sug['forecast'][0]['input']}},
                 replace=False)
        return None
    uid = create_forecast_input(create['lat'], create['lng'],
                                '%s · %s' % ((site.name or 'Site'), create['label']),
                                map_uuid=_site_map_id(site_id))
    save('site', site_id, config={'forecast': {'input': uid, 'max_age_h': 36}}, replace=False)
    return uid


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, a)))


def _site_center(site):
    pts = [(p.lat, p.lon) for p in site.plots if p.lat is not None and p.lon is not None]
    if not pts:
        return None, None
    return sum(a for a, _ in pts) / len(pts), sum(b for _, b in pts) / len(pts)


def _site_map_id(sid: str) -> Optional[str]:
    """대지 id → 지도 id. `map:<지도>` 는 대지 도형이 없는 지도 전체, 아니면 대지 도형의 지도."""
    if sid.startswith('map:'):
        return sid[4:]
    try:
        from aot.databases.models import GeoShape
        row = GeoShape.query.filter_by(unique_id=sid).first()
        return row.geo_id if row is not None else None
    except Exception:
        return None


def _nearest_channels(geo_id, lat, lng, limit_m: float, max_devices: int = 25, weather_only: bool = False):
    """같은 지도의 장치 마커 중 (lat, lng) 에서 가까운 순으로 `[(거리 m, 채널 dict)]`.

    `weather_only` 면 기상 측정값(강수·일사 등, 지도의 기상원 추론과 같은 기준)을 내는 장치만 — 온실 안
    온습도계 같은 실내 센서를 기상대로 제안하지 않기 위해서다."""
    from aot.space.device_membership import load_markers
    if not geo_id or lat is None or lng is None:
        return []
    best: Dict[str, float] = {}
    for dev, (mlng, mlat) in load_markers(geo_id):
        base = str(dev).split('::')[0]
        d = _haversine_km(lat, lng, mlat, mlng) * 1000.0
        if d <= limit_m and d < best.get(base, 1e18):
            best[base] = d
    if not best:
        return []
    ids = sorted(best, key=lambda k: best[k])[:max_devices]
    rows = channels(ids)
    if weather_only:
        from aot.space.device_membership import WEATHER_MARKER_MEASUREMENTS
        wx = {c['unique_id'] for c in rows if c['measurement'] in WEATHER_MARKER_MEASUREMENTS}
        rows = [c for c in rows if c['unique_id'] in wx]
    out = []
    for c in rows:
        out.append((best[c['unique_id']], c))
    out.sort(key=lambda x: (x[0], x[1]['device_name'], x[1]['channel']))
    return out


def _other_site_sources(site, sites) -> Dict[str, List[Dict]]:
    """같은 지도의 **다른 대지에서 사용자가 이미 고른** 비·기온·ET0 — 같은 기상대를 다시 찾지 않게 한다.

    이름·지역을 보지 않는다(사용자가 고른 것만 옮긴다). 비는 묶는 법(`options.rain`)도 함께 싣는다 —
    같은 채널이면 같은 기록 방식이다. 켜진 대지의 것을 먼저, 그다음 이름순.
    """
    out: Dict[str, List[Dict]] = {k: [] for k in SITE_INPUTS}
    map_id = _site_map_id(site.site_id)
    if not map_id:
        return out
    seen = set()
    for other in sorted(sites or [], key=lambda x: (not (read('site', x.site_id)[0]), x.name or '')):
        if other.site_id == site.site_id or _site_map_id(other.site_id) != map_id:
            continue
        _en, cfg = read('site', other.site_id)
        for k in SITE_INPUTS:
            ser = ((cfg.get('inputs') or {}).get(k))
            if not ser or (k, ser['unique_id'], ser['channel']) in seen:
                continue
            seen.add((k, ser['unique_id'], ser['channel']))
            c = next((x for x in channels([ser['unique_id']]) if x['channel'] == ser['channel']), None)
            row = dict(ser, label=_label(c) if c else '%s · CH%s' % (ser['unique_id'][:8], ser['channel']),
                       why='other_site', from_site=other.name or other.site_id)
            if k == 'rain' and (cfg.get('options') or {}).get('rain'):
                row['rain_options'] = dict(cfg['options']['rain'])
            out[k].append(row)
    return out


def _site_weather(site) -> Tuple[Dict[str, List[Dict]], set]:
    """대지 기상대 채널 후보(비·기온·ET0) — 도형 상속 순서: 지정된 기상대 → 대지 안 기상 장치 → 같은 지도의 가장 가까운 기상 채널.
    (후보 표, 대지 안 장치 id 집합)."""
    out: Dict[str, List[Dict]] = {k: [] for k in SITE_INPUTS}
    sid = site.site_id
    lat, lng = _site_center(site)
    inside: set = set()

    def add(k, c, why, d=None):
        if k in out and len(out[k]) < MAX_SUGGESTIONS:
            row = dict(_as_series(c), label=_label(c), why=why)
            if d is not None:
                row['distance_m'] = round(d, 1)
            out[k].append(row)

    if not sid.startswith('map:'):
        try:
            from aot.space.device_membership import device_ids_in_area, weather_device_ids
            ids, src = weather_device_ids(sid)
            why = 'weather_bound' if src == 'bound' else 'weather_inferred'
            for c in channels(ids):
                for k in c['kinds']:
                    add(k, c, why)
            inside = set(device_ids_in_area(sid) or [])
        except Exception:
            logger.exception('트윈 제안: 기상대 채널 읽기 실패 %s', sid)
    missing = [k for k in SITE_INPUTS if not out[k]]
    if missing:
        try:
            for d, c in _nearest_channels(_site_map_id(sid), lat, lng, WEATHER_FALLBACK_M, weather_only=True):
                for k in c['kinds']:
                    if k in missing:
                        add(k, c, 'weather_nearest', d)
        except Exception:
            logger.exception('트윈 제안: 가까운 기상 채널 찾기 실패 %s', sid)

    return out, inside


def site_suggestions(site, sites=None) -> Dict[str, List[Dict]]:
    """대지 출처 제안.

    비·기온·ET0 = 기상대 채널 — ① 대지에 **지정된** 기상대(`weather_bound`), ② 없으면 대지 안 장치 중
    기상 측정값이 있는 것(`weather_inferred`, 지도가 쓰는 규칙과 같다), ③ 그래도 없으면 같은 지도에서 가장
    가까운 기상 채널(`weather_nearest`, 거리 표시). 앞 단계에서 찾은 종류는 뒤 단계로 내려가지 않는다.
    `sites` 를 주면 같은 지도의 다른 대지에서 사용자가 이미 고른 출처(`other_site`)를 맨 앞에 둔다.
    예보 = 예보 입력 — 대지 안에 둔 것이 먼저(`forecast_inside`), 그다음 가까운 순(`forecast_meta`).
    가까운(켜진) 예보 입력이 없으면 `forecast_create` 로 새로 만들 수 있다고 알린다.
    """
    out, inside = _site_weather(site)
    sid = site.site_id
    lat, lng = _site_center(site)

    if sites:
        try:
            for k, rows in _other_site_sources(site, sites).items():
                if rows:
                    mine = {(r['unique_id'], r['channel']) for r in rows}
                    out[k] = rows + [r for r in out[k] if (r['unique_id'], r['channel']) not in mine]
        except Exception:
            logger.exception('트윈 제안: 다른 대지의 출처 읽기 실패 %s', sid)

    fc = forecast_inputs(lat, lng)
    for f in fc:
        f['inside'] = f['input'] in inside
    fc.sort(key=lambda f: (not f['inside'], not f['active'], f['distance_km'] is None,
                           f['distance_km'] or 0.0, f['name']))
    out['forecast'] = [{'input': f['input'], 'label': f['name'], 'distance_km': f['distance_km'],
                        'active': f['active'], 'why': 'forecast_inside' if f['inside'] else 'forecast_meta'}
                       for f in fc[:MAX_SUGGESTIONS]]
    near = any(f['active'] and (f['inside'] or (f['distance_km'] is not None and f['distance_km'] <= FORECAST_NEAR_KM))
               for f in fc)
    mod = forecast_module()
    if not near and mod and lat is not None:
        out['forecast_create'] = {'module': mod, 'lat': round(lat, 5), 'lng': round(lng, 5),
                                  'label': forecast_module_label(mod)}
    return out


def _label(c: Mapping) -> str:
    nm = c.get('name') or c.get('measurement') or ''
    return '%s · CH%s %s (%s)' % (c.get('device_name', ''), c.get('channel', 0), nm, c.get('unit', ''))


def plot_suggestions(plot_id: str, radius_m: float = SENSOR_RADIUS_M,
                     markers: Optional[Dict[str, list]] = None) -> Dict[str, List[Dict]]:
    """구획 관측 센서 제안 — 지도가 구획 센서를 찾는 순서(`sensors_for_plot`)를 따른다.

    ① 구획 안(`inside`)·경계에서 `radius_m` 안(`near`) 마커의 토양 채널, 가까운 순.
    ② 없으면 구획이 속한 대지·구역의 센서(`zone`, 구역 대표값) — 가까운 순.
    ③ 그래도 없으면 같은 지도에서 가장 가까운 토양 채널(`nearest`, 거리 표시, `SENSOR_FALLBACK_M` 까지).
    입력 종류마다 앞 단계에서 찾았으면 뒤 단계는 보지 않는다. 제안일 뿐 — 쓰려면 사용자가 적용한다.

    `markers` 는 지도 id → `load_markers` 결과 캐시(여러 구획을 연달아 볼 때 마커 조회를 한 번만)."""
    from aot.space.device_membership import load_markers
    from aot.space.plot_geometry import geometry_of
    out: Dict[str, List[Dict]] = {k: [] for k in PLOT_INPUTS}
    pl = _plot_rows([plot_id]).get(plot_id)
    if pl is None:
        return out
    geom = geometry_of(pl) or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return out
    if markers is None:
        markers = {}
    if pl.geo_id not in markers:
        markers[pl.geo_id] = load_markers(pl.geo_id)
    near: Dict[str, Tuple[float, Optional[int]]] = {}
    for dev, (lng, lat) in markers[pl.geo_id]:
        d = distance_m(geom, lng, lat)
        if d is None or d > SENSOR_FALLBACK_M:
            continue
        base, _, ch = str(dev).partition('::')
        key = base + ('::' + ch if ch else '')
        if key not in near or d < near[key][0]:
            near[key] = (d, int(ch) if ch.isdigit() else None)
    if not near:
        return out
    zone_ids: set = set()
    try:
        from aot.space.plot_context import sensors_for_plot
        zone_ids = set(sensors_for_plot(pl, markers=markers[pl.geo_id]).get('from_zone') or [])
    except Exception:
        logger.exception('트윈 제안: 구역 센서 찾기 실패 %s', plot_id)
    by_dev: Dict[str, List] = {}
    for key, (d, ch) in sorted(near.items(), key=lambda kv: kv[1][0])[:40]:
        by_dev.setdefault(key.split('::')[0], []).append((d, ch))
    cands = []
    for c in channels(by_dev):
        for d, ch in by_dev[c['unique_id']]:
            if ch is not None and ch != c['channel']:
                continue
            tier = 1 if d <= radius_m else (2 if c['unique_id'] in zone_ids else 3)
            cands.append((tier, d, c))
    cands.sort(key=lambda x: (x[0], x[1], x[2]['device_name'], x[2]['channel']))
    why_of = {1: None, 2: 'zone', 3: 'nearest'}
    chosen_tier: Dict[str, int] = {}
    seen = set()
    for tier, d, c in cands:
        for k in c['kinds']:
            if k not in out or (k, c['unique_id'], c['channel']) in seen or len(out[k]) >= MAX_SUGGESTIONS:
                continue
            if chosen_tier.setdefault(k, tier) != tier:
                continue                                      # 앞 단계에서 찾은 종류는 뒤 단계를 안 본다
            seen.add((k, c['unique_id'], c['channel']))
            why = why_of[tier] or ('inside' if d == 0 else 'near')
            out[k].append(dict(_as_series(c), label=_label(c), distance_m=round(d, 1), why=why))
    return out


# ── 도형 상속 — 저장된 선택이 없을 때 '쓰는 값' ────────────────────────────────────
#
# 비·기온·ET0 는 대지 기상대, 토양수분·지온은 구획 안/가까운/구역 센서를 도형 상속(`device_membership`)이 이미
# 정한다. 트윈은 그 결과를 실행 때 그대로 쓰고, 저장된 선택(`twin_config` 행의 inputs)은 덮어쓰기일 뿐이다.
# 상속값은 저장하지 않는다 — 상속이 바뀌면 따라간다. 키가 있으면(null 포함) 덮어쓰기라 상속하지 않는다.

#: 구획 센서 중 상속으로 '쓰는 값'이 되는 단계. 먼 센서(`nearest`)는 구획을 대표하지 못할 수 있어 덮어쓰기로만 고른다.
PLOT_INHERIT_WHY = ('inside', 'near', 'zone')


def site_inherited(site) -> Dict[str, Dict]:
    """대지가 도형으로 물려받는 비·기온·ET0 — 종류마다 첫 후보(지정 기상대 → 대지 안 기상 장치 → 가까운 기상 채널)."""
    cands, _inside = _site_weather(site)
    return {k: rows[0] for k, rows in cands.items() if rows}


def plot_inherited(sug: Optional[Mapping]) -> Dict[str, Dict]:
    """구획이 도형으로 물려받는 토양수분·지온 — `plot_suggestions` 결과에서 상속 단계의 첫 후보.
    지온은 토양수분과 같은 장치일 때만(다른 센서의 지온을 섞지 않는다)."""
    out: Dict[str, Dict] = {}
    for k in PLOT_INPUTS:
        for r in (sug or {}).get(k) or []:
            if r.get('why') in PLOT_INHERIT_WHY:
                out[k] = r
                break
    th, st = out.get('theta'), out.get('soil_t')
    if st is not None and (th is None or th['unique_id'] != st['unique_id']):
        del out['soil_t']
    return out


def _plain(r: Mapping) -> Dict[str, object]:
    """상속 후보 → 설정에 들어가는 계열 모양(화면용 label·why 는 뺀다)."""
    return {'unique_id': r['unique_id'], 'unit': r['unit'], 'channel': r['channel'],
            'provenance': r.get('provenance') or 'unknown'}


def resolved_overrides(sites=None) -> Dict[str, Dict]:
    """`overrides()` 에 상속값을 채운 것 — 서비스(discovery)가 읽는다. 켜진 대지의 비·기온·ET0 와 그 구획의
    토양수분·지온 중 저장된 선택(키)이 없는 것만 채운다. 저장하지 않는다."""
    ov = overrides()
    sites = sites if sites is not None else catalog_sites()
    mcache: Dict[str, list] = {}
    for s in sites:
        scfg = ov['sites'].get(s.site_id) or {}
        if not scfg.get('enabled'):
            continue
        ins = dict(scfg.get('inputs') or {})
        try:
            for k, r in site_inherited(s).items():
                ins.setdefault(k, _plain(r))
        except Exception:
            logger.exception('트윈 상속: 대지 %s 기상대 읽기 실패', s.site_id)
        sopts = dict(scfg.get('options') or {})
        if 'effects' not in sopts:                          # 노지 출력 명단 — 머리말 effects_* 의 재료(저장하지 않는다)
            try:
                from aot.utils.twin_effects_link import field_effects_options
                roster = field_effects_options(s.site_id, scfg, [p.unique_id for p in s.plots])
                if roster:
                    sopts['effects'] = roster
            except Exception:
                logger.exception('트윈 상속: 대지 %s 노지 출력 명단 읽기 실패', s.site_id)
        ov['sites'][s.site_id] = dict(scfg, inputs=ins, options=sopts) if sopts else dict(scfg, inputs=ins)
        for p in s.plots:
            pcfg = ov['plots'].get(p.unique_id) or {}
            pins = dict(pcfg.get('inputs') or {})
            if pcfg.get('enabled') is False or 'theta' in pins:
                continue
            try:
                inh = plot_inherited(plot_suggestions(p.unique_id, markers=mcache))
            except Exception:
                logger.exception('트윈 상속: 구획 %s 센서 읽기 실패', p.unique_id)
                continue
            for k, r in inh.items():
                pins.setdefault(k, _plain(r))
            if pins:
                ov['plots'][p.unique_id] = dict(pcfg, inputs=pins)
    # 시설 — 켜진 시설은 손배선이 없으면 위치로 읽은 장치를 효과 채널에 자동 연결한다(대지에 구획이 없어도).
    from aot.utils.twin_effects_link import inherit_facility
    for fid, fcfg in list(ov['facilities'].items()):
        if fcfg.get('enabled') is True:
            ov['facilities'][fid] = inherit_facility(fid, fcfg)
    return drop_non_observations(ov)


def drop_non_observations(ov: Dict[str, Dict]) -> Dict[str, Dict]:
    """서비스가 읽는 덮어쓰기에서 **관측이 아닌 입력**(예보·모델값·시뮬레이터)을 뺀다 — 동기화는 관측으로만 맞춘다.
    대지·구획·시설의 `inputs` 에서 빼고 이유는 `excluded` 에 남겨 계획(`discovery.build_plan`)이 결과 한 줄로 읽게 한다.
    장치 상태(`controls`)는 보지 않는다. 지역·제공자 이름은 보지 않는다."""
    for scope, plot in (('sites', False), ('plots', True), ('facilities', False)):
        for tid, cfg in list((ov.get(scope) or {}).items()):
            if (cfg or {}).get('inputs'):
                ov[scope][tid] = _drop_non_observations(cfg, plot)
    return ov


# ── 일치도(최근 발행 머리말) ──────────────────────────────────────────────────────

def agreement(plot_ids: Sequence[str], now: Optional[float] = None) -> Dict[str, Dict]:
    """구획마다 최근 발행의 일치도 — {t0, status, sync_rmse_theta_1d, coverage_80, rain_fc_days, usable, reason}.

    Influx 를 못 읽으면 빈 사전(화면은 '—'). 값은 참고용이다.
    """
    import time as _time
    if not plot_ids:
        return {}
    now = _time.time() if now is None else now
    try:
        from aot.twin import output as O
        from aot.utils import twin_read
        from aot.utils.influx import read_twin_many
        rows = read_twin_many(O.M_FLD_META, list(plot_ids), twin_read.META_CHANNELS,
                              now - 7 * 86400.0, now + 600.0)
    except Exception:
        logger.exception('트윈 일치도 읽기 실패')
        return {}
    out = {}
    for pid in plot_ids:
        meta = twin_read.latest_meta(rows, pid)
        ok, why = twin_read.usable(meta, now)
        rec = {'usable': ok, 'reason': why}
        if meta:
            for k in ('t0', 'status', 'sync_rmse_theta_1d', 'coverage_80', 'rain_fc_days', 'valid_until', 'obs_n'):
                if k in meta:
                    rec[k] = meta[k]
        out[pid] = rec
    return out


# ── 화면용 묶음 ─────────────────────────────────────────────────────────────────

def _with_inherited(cfg: Mapping, inh: Mapping[str, Mapping]) -> Dict:
    """저장된 설정에 상속값을 '쓰는 값'으로 채운 사본 — 키가 있으면(null 포함) 덮어쓰기라 채우지 않는다."""
    ins = dict((cfg or {}).get('inputs') or {})
    for k, r in inh.items():
        ins.setdefault(k, _plain(r))
    return dict(cfg or {}, inputs=ins)


def _inh_entry(r: Mapping) -> Dict[str, object]:
    return {'value': _plain(r), 'origin': 'inherited', 'label': r.get('label'),
            'why': r.get('why'), 'distance_m': r.get('distance_m')}


def _used(cfg: Mapping, inh: Mapping[str, Mapping], keys: Sequence[str],
          fallback: Optional[Mapping[str, Mapping]] = None) -> Dict[str, Dict]:
    """키마다 {value, origin('own'·'inherited'·'none'), label, why, distance_m, fallback} — 화면이 '트윈이 지금 쓰는 것'
    한 줄로 읽는다. `fallback` = 덮어쓴 값을 걷었을 때 쓰게 될 상속 항목(없으면 None). 덮어쓴 값의 라벨은 화면이
    장치 이름(`names`)으로 만든다."""
    ins = (cfg or {}).get('inputs') or {}
    fb_src = inh if fallback is None else fallback
    out: Dict[str, Dict] = {}
    for k in keys:
        fb = _inh_entry(fb_src[k]) if k in fb_src else None
        if k in ins:
            out[k] = {'value': ins[k], 'origin': 'own' if ins[k] else 'none', 'fallback': fb}
        elif k in inh:
            out[k] = dict(_inh_entry(inh[k]), fallback=None)
        else:
            out[k] = {'value': None, 'origin': 'none', 'fallback': None}
    # 관측이 아닌 계열(예보·모델값·시뮬레이터)은 동기화에서 빠진다 — 화면이 그 줄을 읽도록 이유를 붙인다
    vals = {k: e['value'] for k, e in out.items() if e.get('value')}
    vals.update({k + '#fb': e['fallback']['value'] for k, e in out.items()
                 if e.get('fallback') and e['fallback'].get('value')})
    exc = exclusions(vals)
    for k, e in out.items():
        if k in exc:
            e['excluded'] = exc[k]['reason']
        if (k + '#fb') in exc:
            e['fallback']['excluded'] = exc[k + '#fb']['reason']
    return out


def _plot_entry(p, site_cfg: Mapping, prow, inh: Optional[Mapping[str, Mapping]] = None,
                site_excluded: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    enabled = prow[0] if prow else None
    pcfg = prow[1] if prow else {}
    raw = inh or {}
    inh = {} if 'theta' in ((pcfg or {}).get('inputs') or {}) else raw   # 토양수분을 직접 정했으면 상속하지 않는다(지온 짝 맞추기도)
    used = _used(pcfg, inh, PLOT_INPUTS, raw)
    own = (pcfg or {}).get('inputs') or {}
    exc = dict({k: r for k, r in (site_excluded or {}).items() if k not in own}, **_excluded_of(used))   # 대지 칸은 구획이 안 덮었을 때
    return {'plot_id': p.unique_id, 'name': p.name or p.subject, 'started_on': p.started_on,
            'enabled': enabled, 'included': enabled is not False,
            'config': pcfg, 'effective': effective(site_cfg, _with_inherited(pcfg, inh)),
            'used': used, 'excluded': exc,
            'sensorless': sensorless_mode(site_cfg, pcfg)}


def _excluded_of(used: Mapping[str, Mapping]) -> Dict[str, str]:
    """`_used` 결과에서 관측이 아니라 동기화에서 빠지는 칸 → 이유."""
    return {k: e['excluded'] for k, e in used.items() if e.get('excluded')}


# @manual geo/map-widget#twin-tab
def site_view(site_id: str, sites=None, with_suggestions: bool = True) -> Optional[Dict[str, object]]:
    """대지 트윈 탭 한 장: 설정(덮어쓰기)·쓰는 값(상속 반영)·구획 목록·판정·일치도.

    `used` = 트윈이 지금 쓰는 비·기온·ET0 — 저장된 선택이 있으면 'own', 없으면 도형 상속 'inherited'(기상대 지정 →
    대지 안 → 가까운 기상 채널). 구획의 `used` 도 같다(구획 안/가까운/구역 센서). 판정·진단은 쓰는 값으로 낸다."""
    sites = sites if sites is not None else catalog_sites()
    site = next((s for s in sites if s.site_id == site_id), None)
    enabled, cfg = read('site', site_id)
    inh_site: Dict[str, Dict] = {}
    if site is not None and with_suggestions:
        try:
            inh_site = site_inherited(site)
        except Exception:
            logger.exception('트윈 상속: 대지 %s 기상대 읽기 실패', site_id)
    used_cfg = _with_inherited(cfg, inh_site)
    used_site = _used(cfg, inh_site, SITE_INPUTS)
    site_exc = _excluded_of(used_site)
    rows = {r.target_id: (r.enabled, r.config_dict())
            for r in _model().query.filter(_model().scope == 'plot').all()}
    mcache: Dict[str, list] = {}
    plots = []
    sugg_of: Dict[str, Dict] = {}
    for p in (site.plots if site else []):
        prow = rows.get(p.unique_id)
        sug: Dict[str, List[Dict]] = {}
        inh: Dict[str, Dict] = {}
        if with_suggestions and (prow is None or prow[0] is not False) and \
                'theta' not in ((prow[1] if prow else {}).get('inputs') or {}):
            try:
                sug = plot_suggestions(p.unique_id, markers=mcache)
                inh = plot_inherited(sug)
            except Exception:
                logger.exception('트윈 제안: 구획 센서 %s', p.unique_id)
        sugg_of[p.unique_id] = sug
        plots.append(_plot_entry(p, used_cfg, prow, inh, site_exc))
    agr = agreement([p['plot_id'] for p in plots if p['included']])
    for p in plots:
        p['agreement'] = agr.get(p['plot_id'])
        sug = sugg_of.get(p['plot_id']) or {}
        n_sug = None
        if with_suggestions and p['included'] and not (p['effective'].get('theta') or {}).get('value'):
            n_sug = len(sug.get('theta') or [])        # 상속 단계 밖(먼 센서)만 남은 경우 — 덮어쓰기로 고르라고 알린다
        p['diagnosis'] = diagnose_plot(bool(enabled), p, n_sug)
    out = {'site_id': site_id, 'name': site.name if site else '', 'timezone': site.timezone if site else '',
           'known': site is not None, 'enabled': bool(enabled), 'config': cfg, 'plots': plots,
           'used': used_site,
           'verdict': verdict(bool(enabled), used_cfg, plots, site_exc)}
    if with_suggestions and site is not None:
        out['suggestions'] = site_suggestions(site, sites)
    out['forecast_source'] = _forecast_block(site_id)
    if site is not None:
        try:
            from aot.utils.twin_effects_link import site_effects
            out['effects'] = site_effects(site, cfg)
        except Exception:
            logger.exception('트윈 효과: 대지 %s 장치 읽기 실패', site_id)
    return out


def _forecast_block(site_id: str) -> Dict[str, object]:
    """대지 예보 출처(기상원 지정 화면과 같은 목록·같은 저장) — 트윈 탭 예보 칸이 쓴다."""
    try:
        from aot.space import forecast_series
        return forecast_series.site_forecast_block(site_id)
    except Exception:
        logger.exception('트윈: 대지 %s 예보 출처 묶음 실패', site_id)
        return {'selected': [], 'candidates': [], 'segments': [], 'days': 0, 'daily_from': None}


# @manual geo/map-widget#twin-tab
def plot_view(plot_id: str, sites=None) -> Dict[str, object]:
    """구획 트윈 탭 한 장. 트윈 대상이 아닌 구획(시설·끝난 작기·안 심음)은 `eligible: False`.
    `used` = 이 구획이 지금 쓰는 값(덮어쓴 것 'own' / 대지·도형에서 물려받은 것 'inherited')."""
    sites = sites if sites is not None else catalog_sites()
    site = site_of_plot(plot_id, sites)
    p_en, p_cfg = read('plot', plot_id)
    if site is None:
        return {'plot_id': plot_id, 'eligible': False, 'enabled': p_en, 'config': p_cfg}
    s_en, s_cfg = read('site', site.site_id)
    p = next(x for x in site.plots if x.unique_id == plot_id)
    sug = plot_suggestions(plot_id)
    inh = plot_inherited(sug)
    try:
        inh_site = site_inherited(site)
    except Exception:
        logger.exception('트윈 상속: 대지 %s 기상대 읽기 실패', site.site_id)
        inh_site = {}
    used_site = _with_inherited(s_cfg, inh_site)
    entry = _plot_entry(p, used_site, (p_en, p_cfg), inh)
    # 이 구획이 쓰는 비·기온·ET0 까지 — 구획 값(덮어쓰기 'own') → 대지 값('site') → 도형 상속('inherited')
    used = dict(entry['used'])
    base = _used(s_cfg, inh_site, SITE_INPUTS)
    for k in SITE_INPUTS:
        b0 = dict(base[k], fallback=None)
        if b0['origin'] == 'own':
            b0['origin'] = 'site'
        if k in (p_cfg.get('inputs') or {}):
            v = p_cfg['inputs'][k]
            used[k] = {'value': v, 'origin': 'own' if v else 'none', 'fallback': b0}
        else:
            used[k] = b0
    entry['excluded'] = _excluded_of(used)
    entry.update({'eligible': True, 'site_id': site.site_id, 'site_name': site.name,
                  'site_enabled': bool(s_en), 'site_config': used_site, 'used': used,
                  'site_forecast_source': _forecast_block(site.site_id),
                  'suggestions': sug,
                  'agreement': agreement([plot_id]).get(plot_id),
                  'diagnosis': diagnose_plot(bool(s_en), entry,
                                             None if entry['effective'].get('theta', {}).get('value')
                                             else len(sug.get('theta') or []))})
    return entry


_DIAG_TTL_S = 60.0
_diag_cache: Dict[str, object] = {'at': 0.0, 'val': {}}


def plot_diagnoses(plot_ids: Iterable[str], now: Optional[float] = None) -> Dict[str, str]:
    """구획마다 `diagnose_plot` 코드(제안 수는 보지 않는다) — 지도가 '왜 못 칠하나' 를 적는 데 쓴다.
    대지 목록 조립이 무거워 1 분 캐시한다."""
    import time as _time
    now = _time.time() if now is None else now
    if now - float(_diag_cache['at']) > _DIAG_TTL_S:
        val: Dict[str, str] = {}
        rows = {(r.scope, r.target_id): (r.enabled, r.config_dict()) for r in _model().query.all()}
        for s in catalog_sites():
            en, cfg = rows.get(('site', s.site_id), (None, {}))
            sx = {k: e['reason'] for k, e in exclusions({'rain': (cfg.get('inputs') or {}).get('rain')}).items()}
            for p in s.plots:
                val[p.unique_id] = diagnose_plot(bool(en), _plot_entry(p, cfg, rows.get(('plot', p.unique_id)),
                                                                      site_excluded=sx))
        _diag_cache.update(at=now, val=val)
    return {pid: _diag_cache['val'][pid] for pid in plot_ids if pid in _diag_cache['val']}


def overview(sites=None) -> List[Dict[str, object]]:
    """설정 그룹의 제안 결과 표 — 대지마다 켜짐·출처(설정/제안)·센서·판정."""
    sites = sites if sites is not None else catalog_sites()
    rows = {(r.scope, r.target_id): (r.enabled, r.config_dict()) for r in _model().query.all()}
    chosen = set()
    fc_of = {s.site_id: site_forecast_choice(s.site_id) for s in sites}
    chosen.update(c for c in fc_of.values() if c)
    for (scope, _tid), (_en, cfg) in rows.items():
        if scope == 'site':
            chosen.add(str((((cfg.get('inputs') or {}).get('rain')) or {}).get('unique_id') or ''))
    names = _device_names(c for c in chosen if c)
    mcache: Dict[str, list] = {}
    out = []
    for s in sites:
        enabled, cfg = rows.get(('site', s.site_id), (None, {}))
        cfg = {k: v for k, v in cfg.items() if k != 'forecast'}
        if fc_of.get(s.site_id):
            cfg['forecast'] = {'input': fc_of[s.site_id]}
        rain = (cfg.get('inputs') or {}).get('rain')
        sx = {k: e['reason'] for k, e in exclusions({'rain': rain}).items()}
        plots = [_plot_entry(p, cfg, rows.get(('plot', p.unique_id)), site_excluded=sx) for p in s.plots]
        sug = site_suggestions(s, sites)
        sensor_sug = 0
        for p in plots:
            if not (p['effective'].get('theta') or {}).get('value'):
                try:
                    if plot_suggestions(p['plot_id'], markers=mcache).get('theta'):
                        sensor_sug += 1
                except Exception:
                    logger.exception('트윈 제안: 구획 센서 %s', p['plot_id'])
        fc = (cfg.get('forecast') or {}).get('input')
        out.append({
            'site_id': s.site_id, 'name': s.name, 'outside': s.site_id.startswith('map:'),
            'enabled': bool(enabled), 'plots': len(plots),
            'rain': _series_label(rain, names), 'rain_suggested': (sug.get('rain') or [{}])[0].get('label'),
            'forecast': (names.get(fc) or (fc,))[0] if fc else None,
            'forecast_suggested': (sug.get('forecast') or [{}])[0].get('label'),
            'sensor_suggested_plots': sensor_sug,
            'verdict': verdict(bool(enabled), cfg, plots, sx)})
    out.sort(key=lambda r: (not r['enabled'], r['name'] or r['site_id']))
    return out


def _series_label(s, names=None) -> Optional[str]:
    if not s:
        return None
    uid = str(s.get('unique_id', ''))
    dev = ((names or {}).get(uid) or (uid[:8],))[0]
    return '%s · CH%s' % (dev, s.get('channel', 0))


def enable_all(apply_suggestions: bool = False, sites=None, auto_forecast: bool = False) -> Dict[str, int]:
    """모든 대지를 켠다. `apply_suggestions` 면 **비어 있는 칸만** 첫 제안으로 채운다(이미 고른 것은 그대로).

    `auto_forecast` 면 가까운 예보 입력이 없는 대지마다 예보 입력을 새로 만든다(`ensure_site_forecast`).
    """
    sites = sites if sites is not None else catalog_sites()
    mcache: Dict[str, list] = {}
    n_on = n_filled = n_created = 0
    for s in sites:
        save('site', s.site_id, True, None, set_enabled=True)
        n_on += 1
        if not apply_suggestions:
            continue
        if auto_forecast:
            try:
                if ensure_site_forecast(s.site_id, sites):
                    n_created += 1
            except Exception:
                logger.exception('트윈: 대지 %s 예보 입력 만들기 실패', s.site_id)
        _, cfg = read('site', s.site_id)
        sug = site_suggestions(s, sites)
        patch: Dict = {}
        ins = dict(cfg.get('inputs') or {})
        for k in SITE_INPUTS:
            c = next((x for x in (sug.get(k) or []) if x.get('unit')), None)   # 단위 없는 채널은 저장 검사를 못 넘는다
            if k not in ins and c:
                ins[k] = {x: c[x] for x in ('unique_id', 'unit', 'channel', 'provenance')}
                n_filled += 1
                if k == 'rain' and c.get('rain_options') and not (cfg.get('options') or {}).get('rain'):
                    patch['options'] = merge(cfg.get('options') or {}, {'rain': c['rain_options']})
        if ins != (cfg.get('inputs') or {}):
            patch['inputs'] = ins
        if 'forecast' not in cfg and sug.get('forecast'):
            patch['forecast'] = {'input': sug['forecast'][0]['input']}
            n_filled += 1
        if patch:
            save('site', s.site_id, config=patch, replace=False)
        for p in s.plots:
            _, pcfg = read('plot', p.unique_id)
            pins = dict(pcfg.get('inputs') or {})
            ps = plot_suggestions(p.unique_id, markers=mcache)
            changed = False
            for k in PLOT_INPUTS:
                c = next((x for x in (ps.get(k) or []) if x.get('unit')), None)
                if k not in pins and c:
                    pins[k] = {x: c[x] for x in ('unique_id', 'unit', 'channel', 'provenance')}
                    n_filled += 1
                    changed = True
            if changed:
                save('plot', p.unique_id, config={'inputs': pins}, replace=False)
    return {'sites': n_on, 'filled': n_filled, 'forecast_created': n_created}
