# coding=utf-8
"""L0 예보 발표본 저장 — 시간별 `fc_hourly`, 일별 `fc_daily` (예보·트윈 데이터 관리 D2).

설계: AoT_dev/plans/2026-10-25_twin_data_management_design.md §1·§3. 버킷은 `aot_fc`
(`aot.utils.influx_layers` 가 고른다. 한 버킷 모드면 `aot_db`).

## 모양 (제공자 중립)

| 측정 | 태그 | 타임스탬프 | 값 |
|---|---|---|---|
| `fc_hourly` | `device_id`(예보 입력 uuid), `var`, `lead_h` 0…48 | **대상 정시** | 제공자 행 그대로 |
| `fc_daily`  | `device_id`, `var`, `lead_d` 0…7 | **대상일 00:00 UTC** | 일 합·최고·최저 그대로 |
| `fc_hourly_meta` / `fc_daily_meta` | `device_id`, `model` | **받은 시각(epoch)** | 채널: 0 점 수, 1 격자 위도, 2 격자 경도, 3 고도, 4 발표 기준 시각 / 일별은 4 = UTC 오프셋 |

- 변수 `var`: 시간별 T·RH·WS·WD·RAIN·SOL·CLD·POP, 일별 RAIN·ET0·TMAX·TMIN·POP.
- **발표 시각은 태그로 달지 않는다.** 대상 시각 − 리드 = 발표 기준 시각이다(`env_twin_lead` 와 같은 방식).
  그래서 계열 수가 발행 수와 무관하게 고정이다(입력당 시간별 8 × 49, 일별 5 × 8).
  시간별은 받은 시각을 **정시로 내려** 발표 기준으로 삼는다(30분 주기로 두 번 받으면 나중 것이 이긴다).
  정확한 수신 시각은 `*_meta` 에 있다. 일별은 받은 시각의 **현지 날짜**가 기준이다.
- L0 는 **고치지 않는다.** 제공자 행의 값을 그대로 쓰고, 리드 정의(보간·칸 끝 정시)는 L1 이 읽을 때 적용한다.
  값이 없으면 쓰지 않는다(0 으로 채우지 않는다).
- 쓰기는 `write_influxdb_points`(한 연결·동기)를 쓴다. 실패는 예외로 올라가고, 부르는 쪽(드라이버)이
  채널 기록을 막지 않도록 삼킨다.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, Mapping, Optional

logger = logging.getLogger("aot.fc_store")

M_HOURLY, M_HOURLY_META = 'fc_hourly', 'fc_hourly_meta'
M_DAILY, M_DAILY_META = 'fc_daily', 'fc_daily_meta'

HOURLY_VARS = ('T', 'RH', 'WS', 'WD', 'RAIN', 'SOL', 'CLD', 'POP')
DAILY_VARS = ('RAIN', 'ET0', 'TMAX', 'TMIN', 'POP')
HOURLY_LEADS_FULL = tuple(range(0, 49))
# 저사양: 앞 24 시간은 매시간, 그 뒤는 3시간 간격(27, 30, … 48).
HOURLY_LEADS_THIN = tuple(range(0, 25)) + tuple(range(27, 49, 3))
DAILY_LEADS = tuple(range(0, 8))

META_POINTS, META_LAT, META_LON, META_ELEV, META_BASE = 0, 1, 2, 3, 4


@dataclass
class Pt:
    """`write_influxdb_points` 가 받는 점 — `aot.twin.types.Point` 와 같은 속성. `channel` 은 없을 수 있다."""
    measurement: str
    device_id: str
    channel: Optional[int]
    timestamp: float
    value: float
    tags: Mapping[str, str] = field(default_factory=dict)


def _finite(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float('inf'), float('-inf')))


def issue_hour(fetched_epoch):
    """받은 시각 → 발표 기준 정시(UTC epoch)."""
    return int(fetched_epoch // 3600) * 3600


def hourly_points(device_id, fetched_epoch, series, leads=HOURLY_LEADS_FULL):
    """시간별 발표본 → 점 목록.

    series : {var: {대상 정시 epoch: 값}} — 제공자 행을 중립 변수 이름으로 옮긴 것.
    leads  : 남길 리드(시간). 기본 0…48.
    """
    if not device_id:
        return []
    base = issue_hour(fetched_epoch)
    out = []
    for var in HOURLY_VARS:
        rows = series.get(var) or {}
        for lead in leads:
            v = rows.get(base + lead * 3600)
            if not _finite(v):
                continue
            out.append(Pt(M_HOURLY, device_id, None, base + lead * 3600, float(v),
                          {'var': var, 'lead_h': str(lead)}))
    return out


def _meta_points(measurement, device_id, fetched_epoch, n, lat, lon, elev, base, model):
    tags = {'model': str(model or 'best_match')}
    pairs = ((META_POINTS, n), (META_LAT, lat), (META_LON, lon), (META_ELEV, elev), (META_BASE, base))
    return [Pt(measurement, device_id, ch, float(fetched_epoch), float(v), tags)
            for ch, v in pairs if _finite(v)]


def hourly_meta_points(device_id, fetched_epoch, n_points, lat=None, lon=None, elev=None, model=None):
    return _meta_points(M_HOURLY_META, device_id, fetched_epoch, n_points, lat, lon, elev,
                        issue_hour(fetched_epoch), model)


def _day_epoch(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def local_day(fetched_epoch, utc_offset_s):
    return (datetime.fromtimestamp(fetched_epoch, timezone.utc) + timedelta(seconds=utc_offset_s)).date()


def daily_points(device_id, fetched_epoch, utc_offset_s, values):
    """일별 발표본 → 점 목록.

    values : {(var, 리드 일): 값}. 타임스탬프 = 발표일(받은 시각의 현지 날짜) + 리드 의 00:00 UTC.
    """
    if not device_id:
        return []
    today = local_day(fetched_epoch, utc_offset_s)
    out = []
    for (var, lead), v in sorted(values.items()):
        if var not in DAILY_VARS or lead not in DAILY_LEADS or not _finite(v):
            continue
        out.append(Pt(M_DAILY, device_id, None, _day_epoch(today + timedelta(days=lead)), float(v),
                      {'var': var, 'lead_d': str(lead)}))
    return out


def daily_meta_points(device_id, fetched_epoch, utc_offset_s, n_points, lat=None, lon=None, elev=None,
                      model=None):
    return _meta_points(M_DAILY_META, device_id, fetched_epoch, n_points, lat, lon, elev,
                        utc_offset_s, model)


def _write(points):
    if not points:
        return 0
    from aot.utils import influx
    return int(influx.write_influxdb_points(points))


def store_hourly(device_id, fetched_epoch, series, leads=HOURLY_LEADS_FULL, lat=None, lon=None,
                 elev=None, model=None):
    """시간별 한 발표본을 쓴다 → 쓴 점 수. 점이 하나도 없으면 머리말도 쓰지 않는다."""
    pts = hourly_points(device_id, fetched_epoch, series, leads)
    if not pts:
        return 0
    n = len(pts)
    return _write(pts + hourly_meta_points(device_id, fetched_epoch, n, lat, lon, elev, model))


def store_daily(device_id, fetched_epoch, utc_offset_s, values, lat=None, lon=None, elev=None,
                model=None):
    pts = daily_points(device_id, fetched_epoch, utc_offset_s, values)
    if not pts:
        return 0
    n = len(pts)
    return _write(pts + daily_meta_points(device_id, fetched_epoch, utc_offset_s, n, lat, lon, elev,
                                          model))


# ── 읽기 ────────────────────────────────────────────────────────────────────

def read_hourly_leads(device_id, var, start_epoch, end_epoch, lead_h):
    """한 변수·한 리드의 대상 시각별 값 → [(대상 정시 epoch, 값)] (평가용: 같은 리드로 관측과 짝짓는다)."""
    from aot.utils import influx
    rows = influx.read_layer_points(M_HOURLY, device_id, {'var': var, 'lead_h': str(int(lead_h))},
                                    start_epoch, end_epoch)
    return [(ts, v) for ts, v, _tags in rows]


def read_hourly_issue(device_id, fetched_epoch_or_base, vars_: Optional[Iterable[str]] = None):
    """한 발표본 전체 → {var: {lead_h: 값}}. 발표 기준 정시 = 대상 시각 − 리드 가 같은 점만 모은다."""
    from aot.utils import influx
    base = issue_hour(fetched_epoch_or_base)
    want = set(vars_ or HOURLY_VARS)
    out: Dict[str, Dict[int, float]] = {}
    for ts, v, tags in influx.read_layer_points(M_HOURLY, device_id, {}, base, base + 48 * 3600):
        var = tags.get('var')
        if var not in want:
            continue
        try:
            lead = int(tags.get('lead_h'))
        except (TypeError, ValueError):
            continue
        if int(ts) - lead * 3600 == base:
            out.setdefault(var, {})[lead] = v
    return out


def latest_meta(measurement, device_id, now_epoch, max_age_s):
    """가장 최근 머리말 → {'fetched': 받은 시각, 채널: 값…}. `max_age_s` 안에 없으면 None."""
    from aot.utils import influx
    rows = influx.read_layer_points(measurement, device_id, {}, now_epoch - max_age_s, now_epoch + 60)
    if not rows:
        return None
    fetched = max(ts for ts, _v, _t in rows)
    out = {'fetched': fetched}
    for ts, v, tags in rows:
        if ts == fetched:
            try:
                out[int(tags.get('channel'))] = v
            except (TypeError, ValueError):
                continue
    return out


def latest_hourly_issue(device_id, now_epoch, max_age_s, lat_tolerance=None):
    """가장 최근 시간별 발표본 → `{'fetched', 'base', 'series': {var: {대상 정시: 값}}, 'meta': {...}}` 또는 None.

    `max_age_s` 보다 오래됐거나 점이 없으면 None — 부르는 쪽이 파일 사본으로 물러난다."""
    meta = latest_meta(M_HOURLY_META, device_id, now_epoch, max_age_s)
    if not meta:
        return None
    base = issue_hour(meta['fetched'])
    issue = read_hourly_issue(device_id, base)
    if not issue:
        return None
    series = {var: {base + lead * 3600: v for lead, v in by.items()} for var, by in issue.items()}
    return {'fetched': meta['fetched'], 'base': base, 'series': series,
            'meta': {'grid_latitude': meta.get(META_LAT), 'grid_longitude': meta.get(META_LON),
                     'elevation': meta.get(META_ELEV)}}


def latest_daily_days(device_id, now_epoch, max_age_s, from_day_epoch):
    """대상일 ≥ `from_day_epoch`(UTC 자정 epoch)인 일별 값 중 **가장 최근 발표본이 이기게** 모은다.

    → `{'fetched': 가장 최근 받은 시각, 'days': {일 번호(= 대상일 epoch ÷ 86400): {var: 값}}}` 또는 None.
    같은 대상일에 여러 발표가 있으면 리드(`lead_d`)가 가장 작은 것 = 가장 늦은 발표다."""
    from aot.utils import influx
    meta = latest_meta(M_DAILY_META, device_id, now_epoch, max_age_s)
    if not meta:
        return None
    rows = influx.read_layer_points(M_DAILY, device_id, {}, from_day_epoch, from_day_epoch + 9 * 86400)
    best: Dict[tuple, tuple] = {}
    for ts, v, tags in rows:
        var = tags.get('var')
        try:
            lead = int(tags.get('lead_d'))
        except (TypeError, ValueError):
            continue
        if var not in DAILY_VARS:
            continue
        key = (int(ts), var)
        if key not in best or lead < best[key][0]:
            best[key] = (lead, v)
    if not best:
        return None
    days: Dict[int, Dict[str, float]] = {}
    for (ts, var), (_lead, v) in best.items():
        days.setdefault(ts // 86400, {})[var] = v
    return {'fetched': meta['fetched'], 'days': days}


def read_daily_leads(device_id, var, start_epoch, end_epoch, lead_d):
    from aot.utils import influx
    rows = influx.read_layer_points(M_DAILY, device_id, {'var': var, 'lead_d': str(int(lead_d))},
                                    start_epoch, end_epoch)
    return [(ts, v) for ts, v, _tags in rows]


def read_daily_issue(device_id, issue_day: date):
    """한 발표일의 일별 예보 전체 → {var: {lead_d: 값}} (발표일 = 받은 시각의 현지 날짜)."""
    from aot.utils import influx
    base = _day_epoch(issue_day)
    out: Dict[str, Dict[int, float]] = {}
    for ts, v, tags in influx.read_layer_points(M_DAILY, device_id, {}, base, base + 7 * 86400):
        var = tags.get('var')
        if var not in DAILY_VARS:
            continue
        try:
            lead = int(tags.get('lead_d'))
        except (TypeError, ValueError):
            continue
        if int(ts) - lead * 86400 == base:
            out.setdefault(var, {})[lead] = v
    return out
