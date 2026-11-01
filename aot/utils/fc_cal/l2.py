# coding=utf-8
"""L2 보정 곡선 쓰기 — `fc_hourly_cal`·`fc_daily_cal` (버킷 `aot_calc`, 설계 §1·§4.4, D5).

L0 발표본(`fc_hourly`·`fc_daily`)과 **같은 모양**이다 — 태그 `var`·`lead_h`/`lead_d` 에 `cal_rev` 가 더해지고 타임스탬프는
대상 시각이다. 보정을 **쓰는** (변수, 리드대)의 점만 쓴다(그 밖은 L0 가 곧 값이다). 위젯·직접 조회가 같은 계층을 읽게
하려는 사본이다 — 트윈·지도·AI 는 `forecast_series` 가 같은 계수로 읽을 때 즉시 계산하므로 이 곡선이 늦어도 값은 같다
(`apply.Calibrator` 한 곳). 계수와 L0 가 있으면 언제든 다시 만들 수 있고, 같은 대상 시각의 점은 덮어쓴다.

데몬 예약 작업이 매시간 부른다(`job`) — 새 발표본이 들어왔거나 쓰는 판이 바뀐 대지만 쓴다(프로세스 메모리의 '이미 씀' 표).
"""
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import store
from .apply import Calibrator, models_of
from .common import DAY_S, HOUR_S, KIND_D, KIND_H, Ctx, band_of

logger = logging.getLogger('aot.fc_cal')

M_HOURLY_CAL, M_DAILY_CAL = 'fc_hourly_cal', 'fc_daily_cal'
HOURLY_MAX_AGE_S = 7200.0                                   # `forecast_series.L0_HOURLY_MAX_AGE_S` 와 같다
DAILY_MAX_AGE_S = 36 * 3600.0

_HOURLY_ORDER = ('T', 'RH', 'WS', 'SOL', 'RAIN')            # 기온을 먼저 — 습도가 보정한 기온을 쓴다
_DAILY_ORDER = ('TMAX', 'TMIN', 'RAIN')

_done: Dict[Tuple, int] = {}                                # (대지, 종류, 입력, 발표 기준) → 쓴 판


def hourly_points(input_id, base, series: Dict[str, Dict[float, float]], cal: Calibrator):
    """한 시간별 발표본 → 보정 점 목록. `series` = `{var: {대상 정시: 값}}`(L0 읽기 모양)."""
    from aot.utils.fc_store import Pt
    out = []
    t_series = series.get('T') or {}
    t_cal: Dict[float, float] = {}
    for var in _HOURLY_ORDER:
        if not cal.uses(KIND_H, var):
            continue
        for t, v in sorted((series.get(var) or {}).items()):
            lead = int(round((t - base) / HOUR_S))
            if (KIND_H, var, band_of(KIND_H, lead)) not in cal.models:
                continue
            aux = tc = None
            if var == 'RH':
                aux, tc = (t_series.get(t), t_series.get(t)), t_cal.get(t)
            elif var == 'RAIN':
                pop = (series.get('POP') or {}).get(t)
                aux = None if pop is None else max(0.0, min(1.0, pop / 100.0))
            nv = cal.value(KIND_H, var, t, lead, v, aux, tc)
            if var == 'T':
                t_cal[t] = nv
            if var in ('RH', 'WS'):
                nv = max(0.0, nv)
            out.append(Pt(M_HOURLY_CAL, input_id, None, float(t), float(nv),
                          {'var': var, 'lead_h': str(lead), 'cal_rev': str(cal.rev)}))
    return out


def daily_points(input_id, issue_day, days: Dict[int, Dict[str, float]], cal: Calibrator):
    """일별 발표본 → 보정 점 목록. `days` = `{일 번호: {var: 값}}`, `issue_day` = 발표일 번호(대지 현지 날짜)."""
    from aot.utils.fc_store import Pt
    out = []
    for d, row in sorted(days.items()):
        lead = int(d) - int(issue_day)
        t = float(d) * DAY_S
        pop = row.get('POP')
        for var in _DAILY_ORDER:
            v = row.get(var)
            if v is None or (KIND_D, var, band_of(KIND_D, lead)) not in cal.models:
                continue
            aux = None if var != 'RAIN' or pop is None else max(0.0, min(1.0, pop / 100.0))
            nv = cal.value(KIND_D, var, t, lead, v, aux)
            out.append(Pt(M_DAILY_CAL, input_id, None, t, float(nv),
                          {'var': var, 'lead_d': str(lead), 'cal_rev': str(cal.rev)}))
    return out


def refresh_site(site_id, io, now=None, writer: Optional[Callable] = None, force=False) -> int:
    """대지 하나의 L2 곡선을 최신 발표본으로 쓴다 → 쓴 점 수. 보정을 쓰지 않으면 0."""
    now = time.time() if now is None else float(now)
    mode = store.site_mode(site_id)
    row = store.site_row(site_id)
    rev = int(row.active_rev or 0) if row is not None else 0
    if mode == 'off' or not rev:
        return 0
    models = models_of(store.entries_of_rev(site_id, rev))
    if not models:
        return 0
    info = io.site_info(site_id)
    cal = Calibrator(models, Ctx(info['tz'], info['lat'], info['lon']), rev)
    from aot.utils import fc_store
    pts: List = []
    keys = []
    if info.get('hourly_input') and cal.variables(KIND_H):
        got = fc_store.latest_hourly_issue(info['hourly_input'], now, HOURLY_MAX_AGE_S)
        if got:
            key = (site_id, 'h', info['hourly_input'], got['base'], rev)
            if force or _done.get(key) != rev:
                pts += hourly_points(info['hourly_input'], got['base'], got['series'], cal)
                keys.append(key)
    if info.get('daily_input') and cal.variables(KIND_D):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        try:
            off = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(info['tz'] or 'UTC')).utcoffset()
            off_s = off.total_seconds() if off is not None else 0.0
        except Exception:                                   # noqa: BLE001
            off_s = 0.0
        today = int((now + off_s) // DAY_S)
        got = fc_store.latest_daily_days(info['daily_input'], now, DAILY_MAX_AGE_S, today * DAY_S)
        if got:
            issue_day = int((got['fetched'] + off_s) // DAY_S)
            key = (site_id, 'd', info['daily_input'], issue_day, rev)
            if force or _done.get(key) != rev:
                pts += daily_points(info['daily_input'], issue_day, got['days'], cal)
                keys.append(key)
    if not pts:
        for k in keys:
            _done[k] = rev
        return 0
    try:
        if writer is None:
            from aot.utils import influx
            writer = influx.write_influxdb_points
        n = int(writer(pts))
    except Exception:                                       # noqa: BLE001 — 곡선 쓰기 실패가 값을 막지 않는다
        logger.warning('[fc_cal] L2 곡선 쓰기 실패 — 다음 시간에 다시 (%s)', site_id, exc_info=True)
        return 0
    for k in keys:
        _done[k] = rev
    if len(_done) > 512:
        _done.clear()
    return n


def refresh_all(io=None, now=None, writer=None) -> Dict[str, int]:
    """보정을 쓰는 모든 대지의 L2 곡선을 갱신한다 → `{대지: 쓴 점 수}`. 앱 컨텍스트 안에서 부른다."""
    from .sources import InfluxSources
    io = io or InfluxSources()
    out = {}
    for sid in io.sites():
        try:
            if not io.has_forecast(sid):
                continue
            n = refresh_site(sid, io, now=now, writer=writer)
            if n:
                out[sid] = n
        except Exception:                                   # noqa: BLE001
            logger.exception('[fc_cal] L2 곡선 갱신 실패: %s', sid)
    return out
