# coding=utf-8
"""대지의 예보 계열 하나 — 디지털트윈·지도 날씨(슬라이더 독·연출)·AI 예보가 같은 출처를 읽는다.

**출처(저장소 하나).** 대지에 **지정한** 예보 입력이다 — `geo_binding` 의 ``role='forecast'`` 행
(`device_binding.site_forecast_ids`, 기상원 지정 화면과 트윈 탭 예보 칸이 같은 행을 쓴다). 지정 순서가 우선순위.
2단계(10-23)에서 기상대 역할로 지정한 예보 시각 입력(``data_time='forecast'``)도 호환으로 인정한다.

**이어 붙이기.** 지정 목록에서 시간별 입력(시간열 파일, ``forecast_file_path``) 하나와 일별 입력(채널 메타
``forecast_lead_d``·``daily_stat``) 하나를 고른다. 시각 t 의 값은 시간별 지평 안이면 시간 칸, 그 뒤면 **t 가 속한 날**
(대지 시간대)의 일 행이다(`segments_of`). 일 값 규칙은 트윈 사다리와 같은 함수(`aot.twin.forecast.ladder_with_times`).
일별 입력이 없으면 시간 칸이 하루를 다 덮는 날만 일 합·최고/최저로 접는다.

**폴백도 하나.** 지정이 없으면 지도에 등록된 gis-input 예보 레이어(사용자가 고른 것)를 대지 대표점에서 표본한다
(``source_basis='map_layer'``). 지정이 있으면 폴백을 섞지 않는다 — 지정 계열 밖은 "범위 밖"이다.

시간 칸의 시각 기준은 파일의 ``lead_definition`` 과 같다 — 행의 ``epoch`` 는 정시 라벨이다.
- 순간 값(기온·바람): 앞뒤 정시 행의 직선 보간(풍향은 원형). 이웃 행이 하나라도 없으면 값 없음.
- 칸 값(강수·구름): t 를 **포함하는 칸**, 곧 ``ceil(t)`` 정시 행(그 정시까지 직전 1시간 값). 강수 RN1 은 1시간 합 mm → mm/h.
값이 없으면 쓰지 않는다(0 으로 채우지 않는다). 공통 코드는 제공자·지역 이름을 보지 않는다.
"""
import logging
import math
import os
import time

logger = logging.getLogger(__name__)

HOUR_S = 3600.0

# 파일 키 → 표준 키(`weather_state.ITEM_UNITS`). kind: instant | cell | bearing
_MAP = (
    ('TMP', 'temp', 'instant'),
    ('WSD', 'wind_speed', 'instant'),
    ('VEC', 'wind_dir', 'bearing'),
    ('RN1', 'precip', 'cell'),
    ('CLD', 'cloud', 'cell'),
)


def rows_of(data):
    """파일 내용 → 시각순 ``[(epoch, 행)]``. 행에 epoch 가 없으면 건너뛴다."""
    out = []
    for row in ((data or {}).get('forecasts') or {}).values():
        if not isinstance(row, dict):
            continue
        ep = row.get('epoch')
        if isinstance(ep, bool) or not isinstance(ep, (int, float)):
            continue
        out.append((float(ep), row))
    out.sort(key=lambda r: r[0])
    return out


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def span_of(rows):
    """읽을 수 있는 시각 범위 ``(start, end)`` — 첫 칸의 시작부터 마지막 정시까지. 비면 None."""
    if not rows:
        return None
    return rows[0][0] - HOUR_S, rows[-1][0]


def values_at(rows, t):
    """시각 t(epoch 초)의 표준 값 ``{key: 값}``. 범위 밖이거나 값이 없으면 {}.

    ``rows`` 는 ``rows_of`` 결과. 순간 값은 보간, 칸 값은 ``ceil(t)`` 정시 행."""
    if not rows:
        return {}
    start, end = span_of(rows)
    if t < start or t > end:
        return {}
    by_ep = {ep: row for ep, row in rows}
    cell_ep = math.ceil(t / HOUR_S) * HOUR_S
    lo = math.floor(t / HOUR_S) * HOUR_S
    out = {}
    for fkey, key, kind in _MAP:
        if kind == 'cell':
            v = _num((by_ep.get(cell_ep) or {}).get(fkey))
            if v is not None:
                out[key] = max(0.0, v) if key == 'precip' else v
            continue
        a = _num((by_ep.get(lo) or {}).get(fkey))
        b = _num((by_ep.get(lo + HOUR_S) or {}).get(fkey))
        if lo == t:
            v = a
        elif a is None or b is None:
            v = None
        else:
            w = (t - lo) / HOUR_S
            if kind == 'bearing':
                d = ((b - a + 540.0) % 360.0) - 180.0
                v = (a + d * w) % 360.0
            else:
                v = a + (b - a) * w
        if v is not None:
            out[key] = v
    return out


def designated_ids(site_uuid):
    """대지의 예보 출처로 지정한 입력 id — 지정 순서가 우선순위.

    정본은 `geo_binding` 의 ``role='forecast'`` 행(`device_binding.site_forecast_ids`) — 기상원 지정 화면과 트윈 탭이
    같은 행을 읽고 쓴다. 2단계(10-23)에서 기상대(station) 역할로 지정한 예보 시각 입력도 뒤에 붙인다(호환)."""
    if not site_uuid:
        return []
    out = []
    try:
        from aot.space import device_binding, device_membership
        from aot.utils.inputs import forecast_time_input_drivers, input_driver_of
        out = list(device_binding.site_forecast_ids(site_uuid))
        future = forecast_time_input_drivers()
        for dev_id in device_membership.bound_weather_device_ids(site_uuid):
            if dev_id not in out and input_driver_of(dev_id) in future:
                out.append(dev_id)
    except Exception:                                       # noqa: BLE001
        logger.debug('[forecast_series] 예보 출처 지정 읽기 실패: %s', site_uuid, exc_info=True)
    return out


def split_kinds(ids):
    """지정 id → (시간별, 일별) 입력 id 목록(순서 유지). 일별 = 채널 메타가 리드(일)를 밝힌 입력, 시간별 = 나머지
    예보 시각 입력(시간열 파일). 예보가 아닌 입력은 버린다."""
    from aot.utils.inputs import daily_forecast_drivers, forecast_time_input_drivers, input_driver_of
    future, daily = forecast_time_input_drivers(), daily_forecast_drivers()
    hourly_ids, daily_ids = [], []
    for dev_id in ids:
        drv = input_driver_of(dev_id)
        if drv in daily:
            daily_ids.append((dev_id, drv))
        elif drv in future:
            hourly_ids.append(dev_id)
    return hourly_ids, daily_ids


#: 시간별·일별 계열을 L0(`fc_hourly`·`fc_daily`, Influx)에서 먼저 읽는다. 못 읽거나 낡았으면 지금 길(시간열 파일·
#: 일별 채널 사다리)로 물러난다. 끄려면 False 또는 `misc.data_layers.read_l0 == false`.
L0_READ = os.environ.get('AOT_FC_L0_READ', '1') != '0'
#: L0 발표본을 쓰는 최대 나이. 시간열 파일의 기준과 같다(`FACILITY_FILE_MAX_AGE_S`).
L0_HOURLY_MAX_AGE_S = 7200.0

# 파일 키 ← L0 중립 변수 이름 (open_meteo_hourly_forecast._L0_VARS 의 거꾸로).
_L0_FILE_KEYS = {'T': 'TMP', 'RH': 'REH', 'WS': 'WSD', 'WD': 'VEC', 'RAIN': 'RN1',
                 'SOL': 'SOL', 'CLD': 'CLD', 'POP': 'POP'}
# L0 일별 변수 ← 이 모듈의 일 행 변수 이름 (`_DAILY_VARS` 의 묶음 이름 대신 중립 이름).
_L0_DAILY_KEYS = {'RAIN': 'precip_mm', 'ET0': 'et0_mm', 'TMAX': 'temp_max_c', 'TMIN': 'temp_min_c',
                  'POP': 'pop_pct'}


def _l0_enabled():
    if not L0_READ:
        return False
    try:
        from aot.utils.influx_layers import _settings_config
        return _settings_config().get('read_l0') is not False
    except Exception:                                       # noqa: BLE001
        return True


def _l0_hourly(dev_id, now):
    """L0 의 가장 최근 시간별 발표본 → `_load` 와 같은 모양. 없거나 낡았거나 듬성하면 None(파일로 물러난다).

    저사양 `thin` 발표본은 3시간 간격이라 칸을 못 닫는다 — 앞 49 시간이 모두 있을 때만 쓴다."""
    from aot.utils import fc_store
    got = fc_store.latest_hourly_issue(dev_id, now, L0_HOURLY_MAX_AGE_S)
    if not got:
        return None
    base = got['base']
    t_series = got['series'].get('T') or {}
    if any((base + k * HOUR_S) not in t_series for k in range(0, 49)):
        return None
    age = now - got['fetched']
    if age > L0_HOURLY_MAX_AGE_S or age < -600.0:
        return None
    rows = {}
    for var, by_t in got['series'].items():
        fkey = _L0_FILE_KEYS.get(var)
        if not fkey:
            continue
        for ts, v in by_t.items():
            rows.setdefault(ts, {'epoch': ts})[fkey] = v
    out = sorted(((float(ep), row) for ep, row in rows.items()), key=lambda r: r[0])
    return {'rows': out, 'fetched_epoch': got['fetched'], 'issued_epoch': got['base'],
            'meta': {k: v for k, v in got['meta'].items()}, 'layer': 'L0'}


def _load(site_uuid, now=None):
    """시간별 구간 (series, reason). 못 읽으면 series 는 None, reason: no_site | none_designated | stale_or_missing."""
    if not site_uuid:
        return None, 'no_site'
    designated = False
    try:
        from aot.functions.utils.env_control.forecast_feedforward import load_fresh_facility_forecast
        from aot.inputs.open_meteo_hourly_forecast import forecast_file_path
        hourly_ids, _daily = split_kinds(designated_ids(site_uuid))
        for dev_id in hourly_ids:
            designated = True
            if _l0_enabled():
                try:
                    l0 = _l0_hourly(dev_id, now if now is not None else time.time())
                except Exception:                           # noqa: BLE001
                    logger.debug('[forecast_series] L0 시간별 읽기 실패 — 파일로: %s', dev_id, exc_info=True)
                    l0 = None
                if l0:
                    l0.update({'input_id': dev_id, 'source': _input_name(dev_id), 'model': 'open_meteo'})
                    return l0, None
            try:
                path = forecast_file_path(dev_id)
            except ValueError:
                continue
            data = load_fresh_facility_forecast(path, now)
            rows = rows_of(data)
            if not rows:
                continue
            return {'rows': rows, 'input_id': dev_id, 'source': _input_name(dev_id), 'layer': 'file',
                    'issued_epoch': data.get('issued_epoch'),
                    'fetched_epoch': data.get('fetched_epoch'), 'model': data.get('source'),
                    'meta': {k: data.get(k) for k in ('grid_latitude', 'grid_longitude', 'elevation')}}, None
    except Exception:                                       # noqa: BLE001
        logger.debug('[forecast_series] 예보 출처 읽기 실패: %s', site_uuid, exc_info=True)
    return None, ('stale_or_missing' if designated else 'none_designated')


def forecast_candidates(site_uuid):
    """대지 예보 출처로 고를 수 있는 입력 — 값이 미래 시각인 입력(``data_time='forecast'``) 전부, 가까운 순.

    ``[{'device_id', 'name', 'kind': 'hourly'|'daily', 'active', 'distance_km', 'selected', 'order'}]``.
    제공자 이름을 보지 않는다 — 같은 표식을 단 새 입력 모듈은 코드 변경 없이 후보가 된다."""
    from aot.databases.models import Input
    from aot.utils.inputs import daily_forecast_drivers, forecast_time_input_drivers
    future = forecast_time_input_drivers()
    if not future:
        return []
    daily = daily_forecast_drivers()
    chosen = designated_ids(site_uuid)
    lat, lon = _site_point(site_uuid)
    out = []
    rows = Input.query.filter(Input.device.in_(list(future))).all()
    # 입력 위치는 장치 컬럼이 아니라 리졸버(일괄)로 — 위치의 정본은 한 곳.
    from aot.space.device_location import locate_many
    located = locate_many([('input', r.unique_id) for r in rows])
    for r in rows:
        d = None
        pl = located.get(('input', r.unique_id))
        # 대지 폴백(basis='site')은 "이 입력이 여기 있다" 가 아니다 — 거리에서 뺀다.
        rpt = pl.point if pl is not None and pl.basis == 'device' else None
        if lat is not None and lon is not None and rpt is not None:
            rlat, rlon = rpt
            p1, p2 = math.radians(lat), math.radians(rlat)
            a = (math.sin((p2 - p1) / 2) ** 2
                 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(rlon - lon) / 2) ** 2)
            d = round(2 * 6371.0 * math.asin(math.sqrt(min(1.0, a))), 1)
        out.append({'device_id': r.unique_id, 'name': r.name or r.unique_id,
                    'kind': 'daily' if r.device in daily else 'hourly', 'active': bool(r.is_activated),
                    'distance_km': d, 'selected': r.unique_id in chosen,
                    'order': chosen.index(r.unique_id) if r.unique_id in chosen else None})
    out.sort(key=lambda x: (not x['selected'], x['order'] if x['order'] is not None else 0, not x['active'],
                            x['distance_km'] is None, x['distance_km'] or 0.0, x['name']))
    return out


def site_forecast_block(site_uuid, now=None):
    """화면(기상원 지정·트윈 탭)이 함께 쓰는 대지 예보 출처 묶음 — 같은 저장(`geo_binding` role forecast)·같은 후보.

    ``{'selected': [id…], 'candidates': forecast_candidates(), 'segments': [{kind, name, end}], 'days': 트윈이 쓸 앞날
    일 수, 'daily_from': 'daily_input'|'hourly_sum'|None}``. 시간별만 지정한 대지는 시간 칸이 하루를 다 덮는 날만
    일 값이 되므로 ``days`` 가 작다 — 화면이 그대로 알린다."""
    ser = site_series(site_uuid, now, fallback=False) if site_uuid else None
    daily = (ser or {}).get('daily') or {}
    return {'selected': designated_ids(site_uuid), 'candidates': forecast_candidates(site_uuid),
            'segments': [{'kind': s['kind'], 'end': s['end'], 'name': (s.get('source') or {}).get('name')}
                         for s in (segments_of(ser) if ser and ser.get('basis') == 'designated' else [])],
            'days': len(daily.get('days') or {}) if ser and ser.get('basis') == 'designated' else 0,
            'daily_from': daily.get('from'),
            'calibrated': bool(ser and (ser.get('cal') or {}).get('applied')),
            'cal_rev': int((ser or {}).get('cal', {}).get('rev') or 0) if ser and (ser.get('cal') or {}).get('applied') else 0}


def clear_cache():
    _SERIES_CACHE.clear()


DAY_S = 86400.0
#: 일별 입력 값을 쓰는 최대 나이 — 트윈 사다리 기본값(`aot.twin.forecast.DEFAULT_MAX_AGE_H`)과 같다.
DAILY_MAX_AGE_H = 36.0
#: 일별 묶음 → 응답 변수 이름. 강수확률(pop)은 트윈 모델 입력이 아니라 사다리 밖에서 따로 묶는다.
_DAILY_VARS = (('rain', 'precip_mm'), ('et0', 'et0_mm'), ('t_max', 'temp_max_c'),
               ('t_min', 'temp_min_c'), ('pop', 'pop_pct'))


def _site_tz_name(site_uuid):
    try:
        from aot.databases.models import GeoShape
        from aot.utils.timekit import resolve_tz
        shape = GeoShape.query.filter_by(unique_id=site_uuid).first()
        tz, _src = resolve_tz(shape)
        return getattr(tz, 'zone', None) or str(tz)
    except Exception:                                       # noqa: BLE001
        return 'UTC'


def _tz_offset_s(tz_name, at):
    from datetime import datetime, timezone
    from aot.utils.timekit import tz_of
    try:
        off = datetime.fromtimestamp(float(at), timezone.utc).astimezone(tz_of(tz_name)).utcoffset()
        return off.total_seconds() if off is not None else 0.0
    except Exception:                                       # noqa: BLE001
        return 0.0


def _daily_channels(input_id, mdict):
    """일별 입력의 채널 메타 — 트윈 discovery(`DbCatalog.forecast_channels`)와 같은 모양."""
    from aot.databases.models import DeviceMeasurements
    rows = DeviceMeasurements.query.filter_by(device_id=input_id).all()
    out = []
    for r in rows:
        meta = mdict.get(r.channel) or mdict.get(str(r.channel)) or {}
        out.append({'channel': r.channel, 'measurement': r.measurement or meta.get('measurement'),
                    'unit': r.unit or meta.get('unit'), 'enabled': bool(r.is_enabled),
                    'lead_d': meta.get('forecast_lead_d'), 'daily_stat': meta.get('daily_stat')})
    return out


class _InfluxSource:
    """트윈 사다리(`aot.twin.forecast.ladder_with_times`)에 넘길 읽기 — 내장 통로와 같은 Influx 읽기."""

    def read_series(self, ref, window_s, now):
        from aot.twin.sources.embedded import EmbeddedSource
        return EmbeddedSource('', []).read_series(ref, window_s, now)


def _load_daily(site_uuid, now, tz_name, source=None):
    """일별 구간 — 지정 목록의 첫 일별 입력에서 날짜별 값을 만든다. 없거나 비면 None.

    ``{'input_id', 'source', 'fetched_epoch', 'days': {일 번호: {변수: 값}}, 'tz': 이름}`` (일 번호 = 대지 현지 날짜)."""
    from aot.twin import forecast as FC
    from aot.twin.types import Provenance, SeriesRef
    _hourly, daily_ids = split_kinds(designated_ids(site_uuid))
    if not daily_ids:
        return None
    from aot.utils.inputs import daily_forecast_drivers
    mdicts = daily_forecast_drivers()
    src = source or _InfluxSource()
    tz = _tz_offset_s(tz_name, now)
    today = int(math.floor((now + tz) / DAY_S))
    max_age_s = DAILY_MAX_AGE_H * 3600.0
    if _l0_enabled():
        from aot.utils import fc_store
        for input_id, _drv in daily_ids:
            try:
                got = fc_store.latest_daily_days(input_id, now, max_age_s, today * DAY_S)
            except Exception:                               # noqa: BLE001
                logger.debug('[forecast_series] L0 일별 읽기 실패 — 채널로: %s', input_id, exc_info=True)
                continue
            if not got:
                continue
            days = {}
            for d, by_var in got['days'].items():
                if d < today:
                    continue
                for var, v in by_var.items():
                    key = _L0_DAILY_KEYS.get(var)
                    if key:
                        days.setdefault(d, {})[key] = max(0.0, v) if key in ('precip_mm', 'et0_mm') else v
            if days:
                return {'input_id': input_id, 'source': _input_name(input_id), 'fetched_epoch': got['fetched'],
                        'days': days, 'tz': tz_name, 'tz_offset_s': tz, 'layer': 'L0'}
    for input_id, drv in daily_ids:
        try:
            chans = _daily_channels(input_id, mdicts.get(drv) or {})
            cfg, _notes = FC.ladder_from_channels(input_id, chans)
            groups = FC.parse({'forecast': cfg}) if cfg else {}
            pop = {int(c['lead_d']): (int(c['channel']), str(c.get('unit') or 'percent')) for c in chans
                   if c.get('lead_d') is not None and c.get('enabled', True)
                   and str(c.get('measurement')) == 'precipitation' and str(c.get('daily_stat')) == 'max'}
            if pop:
                groups['pop'] = FC.Group('pop', {k: SeriesRef(input_id, unit, ch, Provenance.MIRROR)
                                                 for k, (ch, unit) in pop.items()})
            days, fetched = {}, None
            for gname, var in _DAILY_VARS:
                if gname not in groups:
                    continue
                for d, (t, v) in FC.ladder_with_times(groups[gname], src, now, tz, max_age_s).items():
                    if d < today:
                        continue
                    days.setdefault(d, {})[var] = max(0.0, v) if var in ('precip_mm', 'et0_mm') else v
                    fetched = t if fetched is None or t > fetched else fetched
            if days:
                return {'input_id': input_id, 'source': _input_name(input_id), 'fetched_epoch': fetched,
                        'days': days, 'tz': tz_name, 'tz_offset_s': tz}
        except Exception:                                   # noqa: BLE001
            logger.debug('[forecast_series] 일별 예보 읽기 실패: %s', input_id, exc_info=True)
    return None


def _day_bounds(day, tz):
    return day * DAY_S - tz, (day + 1) * DAY_S - tz


def _date_text(day):
    from datetime import date, timedelta
    return (date(1970, 1, 1) + timedelta(days=int(day))).isoformat()


def load_for_site(site_uuid, now=None):
    """대지에 지정된 예보 입력 중 신선한 첫 파일 → ``{'rows', 'source', 'input_id', 'fetched_epoch', 'model', 'meta'}``
    또는 None. 지정 순서가 우선순위다."""
    return _load(site_uuid, now)[0]


def _input_name(input_id):
    try:
        from aot.databases.models import Input
        row = Input.query.filter_by(unique_id=input_id).first()
        return row.name if row is not None and row.name else input_id
    except Exception:                                       # noqa: BLE001
        return input_id


def site_of_place(kind, ident):
    """AI 가 푼 장소(도형 종류·uuid) → 그 장소가 속한 대지 uuid, 모르면 None.

    장치·농장 기본값처럼 도형이 없는 장소는 대지를 모른다 → 지정 출처가 없는 것으로 본다."""
    if not ident or kind in ('device', 'farm'):
        return None
    if kind == 'site':
        return ident
    try:
        from aot.space.site_parent import parent_site_for_shape
        parent = parent_site_for_shape(ident)
        return parent['uuid'] if parent else None
    except Exception:                                       # noqa: BLE001
        logger.debug('[forecast_series] 상위 대지 찾기 실패: %s', ident, exc_info=True)
        return None


def _dew_point_c(t, rh):
    if t is None or rh is None or rh <= 0:
        return None
    a, b = 17.62, 243.12
    g = math.log(rh / 100.0) + a * t / (b + t)
    return b * g / (a - g)


def _vpd_kpa(t, rh):
    if t is None or rh is None:
        return None
    svp = 0.6108 * math.exp(17.27 * t / (t + 237.3))
    return svp * (1.0 - rh / 100.0)


def ai_hourly_rows(rows, tz_name):
    """`read()` 의 시간 칸 → AI 예보(`get_weather_forecast`)의 시간별 행. 시각은 칸 시작의 지역시각 ``YYYY-MM-DDTHH:MM``.

    Open-Meteo 직접 조회 행(`openmeteo_client.cells_to_interval_start`)과 같은 기준이다 — 순간 값은 그 시각, 칸 값
    (강수·확률·일사·구름)은 그 칸 ``[time, end)`` 의 값. 강수는 칸 합(mm, 칸 길이 × mm/h). 값이 없는 키는 넣지 않는다."""
    from datetime import datetime
    from aot.utils.timekit import tz_of
    tz = tz_of(tz_name)
    out = []
    for c in rows:
        r = {'time': datetime.fromtimestamp(c['time'], tz).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M')}
        t, rh = c.get('temp_c'), c.get('rh_pct')
        for key, v in (('temperature_2m (°C)', t), ('relative_humidity_2m (%)', rh),
                       ('dew_point_2m (°C)', _dew_point_c(t, rh)),
                       ('vapour_pressure_deficit (kPa)', _vpd_kpa(t, rh)),
                       ('wind_speed (m/s)', c.get('wind_ms'))):
            if v is not None:
                r[key] = round(v, 2)
        hours = (c['end'] - c['time']) / HOUR_S
        if c.get('precip_mm_h') is not None:
            r['precipitation (mm)'] = round(c['precip_mm_h'] * hours, 3)
        for key, var in (('precipitation_probability (%)', 'pop_pct'), ('shortwave_radiation (W/m²)', 'solar_w_m2'),
                         ('cloud_cover (%)', 'cloud_pct')):
            if c.get(var) is not None:
                r[key] = c[var]
        out.append(r)
    return out


#: 일 행 변수 → AI 일별 행 키(Open-Meteo 직접 조회의 daily 행과 같은 이름)
_AI_DAILY_KEYS = (('temp_max_c', 'temperature_2m_max (°C)'), ('temp_min_c', 'temperature_2m_min (°C)'),
                  ('precip_mm', 'precipitation_sum (mm)'), ('pop_pct', 'precipitation_probability_max (%)'),
                  ('et0_mm', 'et0_fao_evapotranspiration (mm)'))


def ai_daily_rows(daily):
    """`read()` 의 일 행 → AI 일별 행 ``{'date', <Open-Meteo daily 키>…}``."""
    out = []
    for d in daily:
        r = {'date': d['date']}
        for var, key in _AI_DAILY_KEYS:
            if d.get(var) is not None:
                r[key] = d[var]
        out.append(r)
    return out


#: read() 가 내는 변수 — 이름: (파일 키, 단위, 종류, 뜻). cell = 칸 값, instant = 순간 값.
VARIABLES = {
    'temp_c': ('TMP', '°C', 'instant', 'air temperature at `time`'),
    'rh_pct': ('REH', '%', 'instant', 'relative humidity at `time`'),
    'wind_ms': ('WSD', 'm/s', 'instant', 'wind speed at `time`'),
    'wind_dir_deg': ('VEC', '°', 'instant', 'wind direction (bearing, from) at `time`'),
    'precip_mm_h': ('RN1', 'mm/h', 'cell', 'precipitation over [time, end): the 1 h sum, so mm and mm/h are the same number'),
    'solar_w_m2': ('SOL', 'W/m²', 'cell', 'shortwave radiation, mean over [time, end)'),
    'cloud_pct': ('CLD', '%', 'cell', 'cloud cover over [time, end)'),
    'pop_pct': ('POP', '%', 'cell', 'probability of precipitation over [time, end)'),
}
STEP_S = 3600


#: 일별 행 변수 — 이름: (단위, 뜻). 행은 대지 현지 하루 ``[time, end)``.
DAILY_VARIABLES = {
    'precip_mm': ('mm', 'precipitation sum over the local day [time, end)'),
    'temp_max_c': ('°C', 'daily maximum air temperature'),
    'temp_min_c': ('°C', 'daily minimum air temperature'),
    'et0_mm': ('mm', 'reference evapotranspiration (FAO-56) over the day'),
    'pop_pct': ('%', 'highest probability of precipitation in the day'),
}

#: gis-input 표준 키 → 응답 변수(폴백 표본용)
_GIS_VARS = (('temp', 'temp_c'), ('wind_speed', 'wind_ms'), ('wind_dir', 'wind_dir_deg'),
             ('precip', 'precip_mm_h'), ('cloud', 'cloud_pct'))

#: 공통 계열 캐시 — 슬라이더가 칸마다, 페이지가 열릴 때마다 부른다. 캐시가 비면 일별 사다리가 Influx 를
#: 40번 읽어 0.7~1.1초 걸린다(2026-10-25 개발서버 실측). 예보 입력은 시간 단위로 갱신되므로 10분은 안전하다.
#: 대지의 예보 출처 지정이 바뀌면 `clear_cache()` 가 바로 비운다.
SERIES_TTL_S = 600.0
_SERIES_CACHE = {}


def _file_cells(series):
    """시간열 파일 → 한 시간 칸 행 ``{time, end, 변수…}`` (칸 값은 칸의 끝 정시 행에서). 값 없는 변수는 뺀다."""
    by_ep = {ep: row for ep, row in series['rows']}
    out = []
    for ep, frow in series['rows']:
        nxt = by_ep.get(ep + HOUR_S)
        if nxt is None:
            continue                              # 마지막 정시는 칸을 닫을 다음 행이 없다
        r = {'time': ep, 'end': ep + HOUR_S}
        for name, (fkey, _unit, kind, _meaning) in VARIABLES.items():
            v = _num((frow if kind == 'instant' else nxt).get(fkey))
            if v is not None:
                r[name] = max(0.0, v) if name == 'precip_mm_h' else v
        out.append(r)
    return out


def _site_point(site_uuid):
    try:
        from aot.databases.models import GeoShape
        from aot.utils.timekit import resolve_coords
        shape = GeoShape.query.filter_by(unique_id=site_uuid).first()
        if shape is None:
            return None, None
        lat, lon, _src = resolve_coords(shape)
        return lat, lon
    except Exception:                                       # noqa: BLE001
        return None, None


def _fallback_cells(lat, lon, now):
    """지정이 없을 때의 폴백 — 지도에 등록된 gis-input 예보 레이어(사용자가 고른 것, 레이어 순서)를 그 레이어의 칸
    간격으로 표본한다. 슬라이더가 같은 레이어를 같은 함수(`weather_state.collect_gis_at`)로 읽는다.
    반환 (칸 목록, 출처, 칸 길이 s) 또는 (None, None, None)."""
    if lat is None or lon is None:
        return None, None, None
    from aot.space import weather_state as ws
    rng = (ws.collect_timeline(None, now) or {}).get('forecast')
    if not rng:
        return None, None, None
    step = max(HOUR_S, rng['step_ms'] / 1000.0)
    end = rng['end_ms'] / 1000.0
    t = math.floor(now / step) * step
    cells, used = [], []
    while t < end:
        cands = ws.collect_gis_at(lat, lon, t, 'forecast', now)
        r = {'time': t, 'end': t + step}
        for key, var in _GIS_VARS:
            c = (cands.get(key) or [None])[0]
            if c is not None and c.get('value') is not None:
                r[var] = max(0.0, c['value']) if var == 'precip_mm_h' else c['value']
                if c.get('src_id') and c['src_id'] not in used:
                    used.append(c['src_id'])
        if len(r) > 2:
            cells.append(r)
        t += step
    if not cells:
        return None, None, None
    names = []
    try:
        from aot.databases.models import GeoLayer
        for uid in used:
            row = GeoLayer.query.filter_by(unique_id=uid).first()
            names.append(row.name if row is not None and row.name else uid)
    except Exception:                                       # noqa: BLE001
        names = list(used)
    return cells, {'name': ', '.join(names) or 'map layer', 'layer_ids': used, 'model': None}, step


def _fold_daily(cells, tz):
    """칸 행 → 하루가 **다 덮인** 날만 일 값 ``{일 번호: {precip_mm, temp_max_c, temp_min_c, pop_pct}}``.
    일별 입력이 없을 때 트윈·AI 일 행이 같은 계열에서 나오게 한다(모자란 날은 만들지 않는다)."""
    by_day = {}
    for c in cells:
        d = int(math.floor((c['time'] + tz) / DAY_S))
        by_day.setdefault(d, []).append(c)
    out = {}
    for d, cs in by_day.items():
        lo, hi = _day_bounds(d, tz)
        cs.sort(key=lambda c: c['time'])
        if cs[0]['time'] > lo or cs[-1]['end'] < hi or any(b['time'] != a['end'] for a, b in zip(cs, cs[1:])):
            continue
        row = {}
        rain = [c.get('precip_mm_h') for c in cs]
        if all(v is not None for v in rain):
            row['precip_mm'] = round(sum(v * (c['end'] - c['time']) / HOUR_S for v, c in zip(rain, cs)), 3)
        temps = [c['temp_c'] for c in cs if c.get('temp_c') is not None]
        if len(temps) == len(cs):
            row['temp_max_c'], row['temp_min_c'] = max(temps), min(temps)
        pops = [c['pop_pct'] for c in cs if c.get('pop_pct') is not None]
        if pops:
            row['pop_pct'] = max(pops)
        if row:
            out[d] = row
    return out


CAL_CHOICES = ('auto', 'raw', 'corrected')


def site_series(site_uuid, now=None, lat=None, lon=None, fallback=True, calibration='auto'):
    """대지의 예보 계열 하나 — 트윈·지도 날씨·AI 가 모두 이 결과만 쓴다.

    ``calibration``: ``auto``(쓰는 판에서 채택한 보정을 적용 — 기본, 소비자 모두 이것) | ``raw``(L0 원본) |
    ``corrected``(계수가 있는 보정을 채택 여부와 무관하게 적용 — 미리 보기). 보정은 칸·일 행마다 바뀐 변수의 원본을
    ``raw`` 에 두고, ``cal`` 에 판 번호·방식·보정한 변수를 싣는다(`_calibrated`).
    """
    if calibration not in CAL_CHOICES:
        raise ValueError('unknown calibration: %s' % calibration)
    ser = _series_raw(site_uuid, now, lat, lon, fallback)
    if calibration == 'raw' or ser['basis'] != 'designated':
        return ser
    return _calibrated(ser, site_uuid, now, 'all' if calibration == 'corrected' else 'used')


def _series_raw(site_uuid, now=None, lat=None, lon=None, fallback=True):
    """보정 전(L0 원본) 대지 예보 계열 — 공통 캐시. 설명은 `site_series`.

    - ``basis``: ``designated``(대지에 지정한 예보 입력) | ``map_layer``(지정 없음 → 지도 gis-input 레이어 폴백) | ``none``.
    - ``hourly``: ``{'cells', 'source', 'step_s', 'fetched', 'grid', 'end'}`` — 가까운 날(지정 시간별 입력 또는 폴백 레이어).
    - ``daily``: ``{'days': {일 번호: 값}, 'source', 'from', 'fetched'}`` — 지정 일별 입력, 없으면 시간 칸을 하루 단위로 접은 것.
    - ``tz``·``tz_offset_s``: 일 번호의 기준(대지 시간대).

    지정이 있으면 폴백을 섞지 않는다 — 지정 계열의 범위 밖은 "범위 밖"이다.
    """
    import time as _time
    now = _time.time() if now is None else float(now)
    bucket = int(now // SERIES_TTL_S)
    key = (site_uuid, bucket, None if lat is None else round(lat, 2),
           None if lon is None else round(lon, 2), bool(fallback))
    hit = _SERIES_CACHE.get(key)
    if hit is None:
        hit = _SERIES_CACHE.get((site_uuid, bucket, '*'))     # 지정 예보 계열은 좌표·폴백과 무관하다
    if hit is not None:
        return hit
    tz_name = _site_tz_name(site_uuid) if site_uuid else 'UTC'
    tz = _tz_offset_s(tz_name, now)
    out = {'site': site_uuid, 'basis': 'none', 'reason': None, 'hourly': None, 'daily': None,
           'tz': tz_name, 'tz_offset_s': tz}
    ids = designated_ids(site_uuid) if site_uuid else []
    if ids:
        out['basis'] = 'designated'
        series, reason = _load(site_uuid, now)
        if series:
            cells = _file_cells(series)
            if cells:
                out['hourly'] = {'cells': cells, 'step_s': HOUR_S, 'end': cells[-1]['end'],
                                 'source': {'name': series['source'], 'input_id': series['input_id'],
                                            'model': series.get('model')},
                                 'fetched': series.get('fetched_epoch'), 'grid': dict(series.get('meta') or {}),
                                 'layer': series.get('layer'), 'issued': series.get('issued_epoch')}
        daily = _load_daily(site_uuid, now, tz_name)
        if daily:
            out['daily'] = {'days': daily['days'], 'from': 'daily_input', 'fetched': daily['fetched_epoch'],
                            'layer': daily.get('layer') or 'channel',
                            'source': {'name': daily['source'], 'input_id': daily['input_id'], 'model': None}}
        if not out['hourly'] and not out['daily']:
            out['reason'] = 'stale_or_missing'
    elif fallback:
        if lat is None or lon is None:
            lat, lon = _site_point(site_uuid) if site_uuid else (None, None)
        cells, src, step = _fallback_cells(lat, lon, now)
        if cells:
            out['basis'] = 'map_layer'
            out['hourly'] = {'cells': cells, 'step_s': step, 'end': cells[-1]['end'], 'source': src,
                             'fetched': None, 'grid': {}}
        else:
            out['reason'] = 'none_designated' if site_uuid else 'no_site'
    else:
        out['reason'] = 'none_designated' if site_uuid else 'no_site'
    if out['hourly'] and not out['daily']:
        days = _fold_daily(out['hourly']['cells'], tz)
        if days:
            out['daily'] = {'days': days, 'from': 'hourly_sum', 'fetched': out['hourly']['fetched'],
                            'source': dict(out['hourly']['source'])}
    if out['daily']:
        today = int(math.floor((now + tz) / DAY_S))
        out['daily']['days'] = {d: v for d, v in out['daily']['days'].items() if d >= today}
        if not out['daily']['days']:
            out['daily'] = None
    if len(_SERIES_CACHE) > 256:
        _SERIES_CACHE.clear()
    _SERIES_CACHE[key] = out
    if out['basis'] == 'designated':
        # 지정이 있으면 결과가 좌표·폴백 여부에 달려 있지 않다 — 지도(좌표 있음)·AI·트윈(좌표 없음)이
        # 같은 항목을 쓰게 한 별칭 키. 지정이 바뀌면 clear_cache() 가 함께 비운다.
        _SERIES_CACHE[(site_uuid, bucket, '*')] = out
    return out


def _cal_state(site_uuid):
    """대지의 보정 방식·쓰는 판 ``(mode, active_rev)``. 읽지 못하면 ``('auto', 0)``(= 원본)."""
    try:
        from aot.utils.fc_cal import store
        row = store.site_row(site_uuid)
        if row is None:
            return 'auto', 0
        return (row.mode if row.mode in ('auto', 'on', 'off') else 'auto'), int(row.active_rev or 0)
    except Exception:                                       # noqa: BLE001
        logger.debug('[forecast_series] 보정 상태 읽기 실패: %s', site_uuid, exc_info=True)
        return 'auto', 0


def _cal_off(ser, mode, rev=0, scope='used'):
    return dict(ser, cal={'applied': False, 'rev': 0, 'mode': mode, 'scope': scope, 'variables': [],
                          'hourly': False, 'daily': False})


def _calibrated(ser, site_uuid, now, scope):
    """원본 계열 → 쓰는 판의 보정을 적용한 계열(없으면 원본에 ``cal`` 만 단 것). 결과도 공통 캐시에 둔다.

    칸·일 행에서 값이 바뀐 변수는 원본을 ``raw`` 에 둔다. ``cal`` = ``{applied, rev, mode, scope, variables, hourly, daily}``.
    ``applied`` 가 거짓이면 쓰는 보정이 하나도 없다는 뜻(``rev`` 는 0 = 원본). 시간별은 발표 기준 시각(``issued``)을 모르면
    리드를 알 수 없어 건너뛴다. 일 행은 일별 입력이면 일별 보정을, 시간열을 접은 날이면 보정한 시간열에서 다시 접는다."""
    import time as _time
    now = _time.time() if now is None else float(now)
    mode, rev = _cal_state(site_uuid)
    key = ('cal', site_uuid, int(now // SERIES_TTL_S), scope, mode, rev)
    hit = _SERIES_CACHE.get(key)
    if hit is not None:
        return hit
    out = None
    if mode != 'off' and rev:
        try:
            out = _apply_calibration(ser, site_uuid, scope, mode, rev)
        except Exception:                                   # noqa: BLE001 — 보정이 실패해도 원본은 준다
            logger.warning('[forecast_series] 보정 적용 실패 — 원본: %s', site_uuid, exc_info=True)
    if out is None:
        out = _cal_off(ser, mode, scope=scope)
    if len(_SERIES_CACHE) > 256:
        _SERIES_CACHE.clear()
    _SERIES_CACHE[key] = out
    return out


def _apply_calibration(ser, site_uuid, scope, mode, rev):
    from aot.utils.fc_cal import apply as CA
    from aot.utils.fc_cal import store
    from aot.utils.fc_cal.common import Ctx
    models = CA.models_of(store.entries_of_rev(site_uuid, rev), scope)
    if not models:
        return None
    lat, lon = _site_point(site_uuid)
    cal = CA.Calibrator(models, Ctx(ser.get('tz'), lat, lon), rev)
    tz = ser.get('tz_offset_s') or 0.0
    out = dict(ser)
    h, d = ser.get('hourly'), ser.get('daily')
    h_done = d_done = False
    h_changed = set()
    if h and h.get('issued') is not None:
        cells, h_changed = cal.hourly_cells(h['cells'], float(h['issued']))
        out['hourly'] = dict(h, cells=cells)
        h_done = True
    if d:
        if d.get('from') == 'daily_input' and d.get('fetched') is not None:
            issue_day = int(math.floor((float(d['fetched']) + tz) / DAY_S))
            days, raws, _chg = cal.daily_days(d['days'], issue_day)
            out['daily'] = dict(d, days=days, raw=raws)
            d_done = True
        elif d.get('from') == 'hourly_sum' and h_done and h_changed:
            folded = _fold_daily(out['hourly']['cells'], tz)
            days, raws = {}, {}
            for day, row in d['days'].items():
                new = dict(row, **{k: v for k, v in (folded.get(day) or {}).items() if k in row})
                days[day] = new
                diff = {k: row[k] for k in row if k in new and abs(new[k] - row[k]) > 1e-9}
                if diff:
                    raws[day] = diff
            out['daily'] = dict(d, days=days, raw=raws)
            d_done = True
    if not (h_done or d_done):
        return None
    variables = [v for v in cal.variables() if (h_done and v in ('T', 'RH', 'WS', 'SOL', 'RAIN'))
                 or (d_done and v in ('TMAX', 'TMIN', 'RAIN'))]
    if not variables:
        return None
    out['cal'] = {'applied': True, 'rev': rev, 'mode': mode, 'scope': scope, 'variables': variables,
                  'hourly': h_done, 'daily': d_done}
    return out


def prewarm(now=None):
    """예보 출처를 지정한 모든 대지의 계열을 미리 만들어 캐시에 둔다. 만든 대지 수를 돌려준다.

    페이지를 처음 열 때 일별 사다리가 Influx 를 40번 읽는 0.7~1.1초(2026-10-25 실측)를 사용자가 겪지 않게
    한다. 앱 컨텍스트 안에서 불러야 한다."""
    import time as _time
    from aot.databases.models import GeoBinding
    now = _time.time() if now is None else float(now)
    sites = [r[0] for r in GeoBinding.query.with_entities(GeoBinding.spatial_id).filter(
        GeoBinding.spatial_kind == 'weather', GeoBinding.role == 'forecast',
        GeoBinding.valid_to.is_(None)).distinct().all() if r[0]]
    n = 0
    for site in sites:
        try:
            site_series(site, now, fallback=False)
            n += 1
        except Exception as e:                                   # noqa: BLE001 — 한 대지의 실패가 나머지를 막지 않게
            logger.warning('forecast_series prewarm failed for %s: %s', site, e)
    return n


_PREWARMED_BUCKET = None


def prewarm_if_new_window(app, now=None):
    """이 프로세스에서 이번 캐시 칸을 아직 채우지 않았다면 채운다. 채운 대지 수를, 건너뛰면 None 을 돌려준다.

    스레드를 따로 두지 않는 호출자(주기적으로 깨는 트윈 서비스 루프)용 — 자주 불러도 칸당 한 번만 일한다."""
    import time as _time
    global _PREWARMED_BUCKET
    now = _time.time() if now is None else float(now)
    bucket = int(now // SERIES_TTL_S)
    if bucket == _PREWARMED_BUCKET:
        return None
    _PREWARMED_BUCKET = bucket
    t0 = _time.time()
    with app.app_context():
        n = prewarm(now)
    logger.info('forecast_series prewarm: %d site(s) in %.2fs', n, _time.time() - t0)
    return n


def start_prewarm(app):
    """웹 진입점에서만 부른다 — 서버가 뜰 때 한 번, 이후 캐시 칸(`SERIES_TTL_S`)이 바뀔 때마다 다시 채운다.

    데몬도 create_app() 을 쓰므로 create_app 안에 두지 않는다(`warm_start_mcp_servers` 와 같은 이유).
    워커마다 캐시가 따로라 워커마다 한 스레드가 돈다. 데몬 스레드라 부팅을 막지 않는다."""
    import threading
    import time as _time

    def _loop():
        _time.sleep(3.0)                                         # 부팅·마이그레이션 직후의 몰림을 피한다
        while True:
            try:
                t0 = _time.time()
                with app.app_context():
                    n = prewarm()
                logger.info('forecast_series prewarm: %d site(s) in %.2fs', n, _time.time() - t0)
            except Exception as e:                               # noqa: BLE001
                logger.warning('forecast_series prewarm pass failed: %s', e)
            now = _time.time()
            # 다음 칸이 시작된 직후에 채운다 — 사용자가 새 칸의 첫 요청을 맞기 전에.
            _time.sleep(max(30.0, (int(now // SERIES_TTL_S) + 1) * SERIES_TTL_S - now + 2.0))

    threading.Thread(target=_loop, name='forecast-series-prewarm', daemon=True).start()


def segments_of(ser):
    """계열의 구간 — ``[{'kind': 'hourly'|'daily', 'start', 'end', 'source'}]`` (시각순).

    t 의 값: 시간별 구간 안이면 시간 칸, 그 뒤면 **t 가 속한 날**의 일 행. 일별 구간은 시간별 지평 다음 칸부터
    연속한 날까지다(빠진 날이 있으면 거기서 끝난다)."""
    out = []
    h, d = ser.get('hourly'), ser.get('daily')
    tz = ser.get('tz_offset_s') or 0.0
    h_end = None
    if h:
        h_end = h['end']
        out.append({'kind': 'hourly', 'start': h['cells'][0]['time'], 'end': h_end, 'source': h['source'],
                    'step_s': h['step_s']})
    if d:
        days = d['days']
        if h_end is None:
            first = min(days)
            lo = _day_bounds(first, tz)[0]
        else:
            first = int(math.floor((h_end + tz) / DAY_S))     # 지평 바로 뒤 시각이 속한 날(자정이면 다음 날)
            lo = h_end
        if first in days:
            last = first
            while last + 1 in days:
                last += 1
            out.append({'kind': 'daily', 'start': lo, 'end': _day_bounds(last, tz)[1], 'source': d['source'],
                        'from': d['from']})
    return out


def coverage_end(ser):
    segs = segments_of(ser)
    return max(s['end'] for s in segs) if segs else None


def daily_row(ser, day):
    """일 번호 → 응답 일 행 ``{date, time, end, 변수…}`` 또는 None."""
    d = (ser.get('daily') or {}).get('days', {}).get(day)
    if d is None:
        return None
    lo, hi = _day_bounds(day, ser.get('tz_offset_s') or 0.0)
    return dict({'date': _date_text(day), 'time': lo, 'end': hi}, **d)


def at_time(ser, t):
    """계열에서 시각 t 의 값 — ``{'segment': 'hourly'|'daily'|None, 'values'|'daily', 'source'}``.

    시간 칸: 순간 값은 앞뒤 칸 시작 사이 직선 보간(풍향 원형), 칸 값은 t 를 포함하는 칸. 일별: t 가 속한 날의 행.
    범위 밖이면 segment None."""
    for seg in segments_of(ser):
        if not (seg['start'] <= t <= seg['end']):
            continue
        if seg['kind'] == 'hourly':
            cells = ser['hourly']['cells']
            vals = _cells_value(cells, t)
            if vals:
                return {'segment': 'hourly', 'values': vals, 'source': seg['source']}
        else:
            tz = ser.get('tz_offset_s') or 0.0
            row = daily_row(ser, int(math.floor((t + tz) / DAY_S)))
            if row:
                return {'segment': 'daily', 'daily': row, 'source': seg['source']}
    return {'segment': None, 'source': None}


def _cells_value(cells, t):
    import bisect
    times = [c['time'] for c in cells]
    i = bisect.bisect_right(times, t) - 1
    if i < 0:
        return {}
    a = cells[i]
    if t > a['end']:
        return {}
    b = cells[i + 1] if i + 1 < len(cells) and cells[i + 1]['time'] == a['end'] else None
    out = {}
    for name, (_f, _u, kind, _m) in VARIABLES.items():
        va = a.get(name)
        if va is None:
            continue
        if kind == 'cell' or t == a['time']:
            if kind == 'cell' and t >= a['end']:
                continue
            out[name] = va
            continue
        vb = b.get(name) if b else None
        if vb is None:
            continue
        w = (t - a['time']) / (b['time'] - a['time'])
        if name == 'wind_dir_deg':
            d = ((vb - va + 540.0) % 360.0) - 180.0
            out[name] = (va + d * w) % 360.0
        else:
            out[name] = va + (vb - va) * w
    return out


BASIS_TEXT = {
    'designated': 'forecast input(s) designated for this site',
    'map_layer': 'no forecast input is designated for this site — map weather layer (gis-input) used as the common fallback',
    'none': 'no forecast source: nothing designated for this site and no map weather layer gives a forecast',
}


def source_info(ser):
    """응답·화면에 싣는 출처 묶음 — ``{'basis', 'basis_text', 'segments': [{kind, start, end, name}]}``."""
    cal = ser.get('cal') or {}
    return {'basis': ser['basis'], 'basis_text': BASIS_TEXT.get(ser['basis'], ser['basis']),
            'calibrated': bool(cal.get('applied')), 'cal_rev': int(cal.get('rev') or 0) if cal.get('applied') else 0,
            'segments': [{'kind': s['kind'], 'start': s['start'], 'end': s['end'],
                          'name': (s.get('source') or {}).get('name'),
                          'input_id': (s.get('source') or {}).get('input_id')} for s in segments_of(ser)]}


LAYER_CHOICES = ('auto', 'raw', 'corrected')


def read(site_uuid, t0=None, t1=None, variables=None, now=None, lat=None, lon=None, layer='auto'):
    """대지의 예보 계열 — 트윈·화면·AI 가 같은 모양으로 읽는다. ``available`` 이 false 면 ``reason`` 이 이유.

    ``rows``: 가까운 날의 시간 칸 ``[time, end)`` (epoch 초). **칸 값**(강수·일사·구름·확률)은 그 칸의 값, **순간 값**
    (기온·습도·풍속·풍향)은 ``time`` 정시 값. 값이 없는 변수는 키를 뺀다(0 으로 채우지 않는다). ``[t0, t1)`` 과 겹치는
    칸만 싣는다(기본: 지금부터).
    ``daily``: 대지 현지 하루 행(지정 일별 입력, 없으면 시간 칸을 하루 단위로 접은 것 — ``daily_from``).
    ``segments``: 이어 붙인 순서 — 시간별 지평(``horizon``) 다음은 일별 행. ``source_basis``: designated | map_layer | none.
    잘못된 ``variables`` 이름은 ValueError.

    ``layer``: ``auto``(쓰는 판에서 채택한 보정본, 없으면 원본 — 소비자 모두 이것) | ``raw``(L0 원본) | ``corrected``(계수가
    있는 보정을 채택 여부와 무관하게 적용, 없으면 원본).
    **보정 계약(그래프·AI·화면이 읽는다)**: 응답 ``calibrated``(쓰는 보정이 있나)·``cal_rev``(판 번호, 0 = 원본)·
    ``calibration``(``{rev, mode, variables, hourly, daily}``). 시간 칸·일 행마다 ``calibrated``(그 행의 값이 바뀌었나)와,
    바뀌었으면 ``raw``(**바뀐 변수만**의 보정 전 값 — 없는 변수는 값이 원본과 같다). 행의 변수 값은 항상 쓰는 값이다.
    ``data_layer`` 는 시간별·일별 계열을 어디서 읽었는지(L0 | file | channel | hourly_sum).
    """
    import time as _time
    now = _time.time() if now is None else float(now)
    if layer not in LAYER_CHOICES:
        raise ValueError('unknown layer: %s' % layer)
    names = list(VARIABLES) if not variables else [v for v in variables]
    bad = [v for v in names if v not in VARIABLES]
    if bad:
        raise ValueError('unknown variable(s): %s' % ', '.join(bad))
    ser = site_series(site_uuid, now, lat, lon,
                      calibration={'auto': 'auto', 'raw': 'raw', 'corrected': 'corrected'}[layer])
    base = {'site': site_uuid, 'now': now, 'source_basis': ser['basis'],
            'source_basis_text': BASIS_TEXT.get(ser['basis'], ser['basis'])}
    h, d = ser.get('hourly'), ser.get('daily')
    if not h and not d:
        reason = ser.get('reason') or 'none_designated'
        return dict(base, available=False, reason=reason,
                    reason_text={'no_site': 'no site given',
                                 'none_designated': 'no forecast input is designated for this site and no map weather layer gives a forecast',
                                 'stale_or_missing': 'the designated forecast input has no fresh data (old or no file)'
                                 }.get(reason, reason))
    lo = None if t0 is None else float(t0)
    hi = None if t1 is None else float(t1)
    if lo is None:
        lo = math.floor(now / HOUR_S) * HOUR_S
    rows = []
    for c in (h['cells'] if h else []):
        if c['end'] <= lo or (hi is not None and c['time'] >= hi):
            continue
        row = {k: v for k, v in c.items() if k in ('time', 'end') or k in names}
        raw = {k: v for k, v in (c.get('raw') or {}).items() if k in names}
        row['calibrated'] = bool(raw)
        if raw:
            row['raw'] = raw
        rows.append(row)
    daily = []
    for day in sorted((d or {}).get('days', {})):
        r = daily_row(ser, day)
        if r['end'] <= lo or (hi is not None and r['time'] >= hi):
            continue
        raw = (d.get('raw') or {}).get(day)
        r['calibrated'] = bool(raw)
        if raw:
            r['raw'] = dict(raw)
        daily.append(r)
    cal = ser.get('cal') or {}
    cal_on = bool(cal.get('applied'))
    segs = segments_of(ser)
    cov_start = segs[0]['start'] if segs else None
    cov_end = max(s['end'] for s in segs) if segs else None
    hsrc = (h or {}).get('source') or (d or {}).get('source') or {}
    fetched = (h or {}).get('fetched') or (d or {}).get('fetched')
    step = (h or {}).get('step_s') or STEP_S
    return dict(
        base, available=True,
        source={'name': hsrc.get('name'), 'input_id': hsrc.get('input_id'), 'model': hsrc.get('model')},
        fetched_at=float(fetched) if fetched is not None else None,
        issued_epoch=(h or {}).get('issued'),
        calibrated=cal_on, cal_rev=int(cal.get('rev') or 0) if cal_on else 0, layer=layer,
        calibration={'rev': int(cal.get('rev') or 0) if cal_on else 0, 'mode': cal.get('mode'),
                     'variables': list(cal.get('variables') or []), 'hourly': bool(cal.get('hourly')),
                     'daily': bool(cal.get('daily'))},
        data_layer={'hourly': (h or {}).get('layer'), 'daily': (d or {}).get('layer') or (d or {}).get('from')},
        horizon=(h['end'] if h else None),
        resolution={'step_s': step, 'kind': 'hourly' if step == STEP_S else 'step'},
        coverage={'start': cov_start, 'end': cov_end},
        segments=[{'kind': s['kind'], 'start': s['start'], 'end': s['end'],
                   'source': {'name': (s.get('source') or {}).get('name'),
                              'input_id': (s.get('source') or {}).get('input_id')}} for s in segs],
        requested={'t0': None if t0 is None else float(t0), 't1': None if t1 is None else float(t1)},
        covers_request=(t1 is None or (cov_end is not None and float(t1) <= cov_end))
                       and (t0 is None or (cov_start is not None and float(t0) >= cov_start)),
        variables={n: {'unit': VARIABLES[n][1], 'kind': VARIABLES[n][2], 'meaning': VARIABLES[n][3]} for n in names},
        daily_variables={n: {'unit': u, 'meaning': m} for n, (u, m) in DAILY_VARIABLES.items()},
        daily_from=(d or {}).get('from'),
        timezone=ser.get('tz'),
        grid=dict((h or {}).get('grid') or {}),
        note=('Near days are hourly cells [time, end) in `rows`; after `horizon` the series continues as local-day rows in '
              '`daily` (see `segments`). Beyond `coverage.end` this source gives nothing and nothing is filled in; '
              'a missing variable is simply absent.'),
        rows=rows, daily=daily)


#: 지도 독(weather_state 표준 키) ← 시간 칸 변수
_STATE_KEYS = (('temp_c', 'temp'), ('wind_ms', 'wind_speed'), ('wind_dir_deg', 'wind_dir'),
               ('precip_mm_h', 'precip'), ('cloud_pct', 'cloud'))


def state_at(site_uuid, t, now=None, lat=None, lon=None):
    """슬라이더 forecast 모드 — 시각 t 의 값을 공통 계열에서. ``basis`` 가 ``designated`` 가 아니면 None
    (지정이 없으면 슬라이더는 같은 폴백 레이어를 `collect_gis_at` 로 직접 읽는다 — 같은 레이어·같은 함수).

    반환 ``{'basis', 'segment', 'candidates', 'daily', 'source', 'info'}``. segment None = 지정 계열의 범위 밖."""
    ser = site_series(site_uuid, now, lat, lon, fallback=False)
    if ser['basis'] != 'designated':
        return None
    got = at_time(ser, t)
    out = {'basis': ser['basis'], 'segment': got['segment'], 'candidates': {}, 'daily': got.get('daily'),
           'source': got.get('source'), 'info': source_info(ser)}
    if got['segment'] == 'hourly':
        from aot.space.weather_state import _cand
        src_id = (got['source'] or {}).get('input_id')
        for var, key in _STATE_KEYS:
            v = got['values'].get(var)
            if v is None:
                continue
            c = _cand(key, v, 'field', t, src_id)
            if c:
                out['candidates'][key] = [c]
    return out


def candidates(site_uuid, t, now=None):
    """슬라이더 forecast 모드용 시간 칸 후보 ``{key: [후보]}`` — 지정 계열의 시간별 구간만. 그 밖은 {}."""
    got = state_at(site_uuid, t, now)
    return (got or {}).get('candidates') or {}


def timeline_range(site_uuid, now):
    """슬라이더가 지정 계열로 받을 수 있는 예보 구간 ``{'start','end','step_s'}`` 또는 None(지정 없음·빈 계열)."""
    ser = site_series(site_uuid, now, fallback=False)
    if ser['basis'] != 'designated':
        return None
    segs = segments_of(ser)
    if not segs:
        return None
    s, e = max(segs[0]['start'], now), max(x['end'] for x in segs)
    step = segs[0].get('step_s') or HOUR_S
    return {'start': s, 'end': e, 'step_s': step} if e > s else None
