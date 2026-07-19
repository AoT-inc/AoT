# coding=utf-8
"""
env_control/cumulative_tracker.py — DLI·GDD 일별 누적 추적 (P5-5).

매 사이클마다 호출되어 DLI(일적산광량)·GDD(누적온도)를 적산하고,
부채 발생 시 보상 제안을 생성한다.

보상은 Phase 1: 제안만(suggest-only) — 실제 목표 조정은 _cycle_mixin이 적용 여부 결정.

참조: docs/env_control_enhancement_design.md §3.20
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────────────────

# µmol/m²/s × s → mol/m²  변환 계수 (1 µmol = 1e-6 mol)
_PPFD_S_TO_MOL = 1.0 / 1_000_000.0

# ── 광 단위 → PPFD(µmol/m²/s) 환산 ────────────────────────────────────────────
# DLI 는 PPFD 통적이 필요하다. 시스템의 internal['light'] 는 관례상 W/m²(일사량)이며
# (facility_sensors: _UNIT_BY_KEY['light']='W/m²', 실내 광센서 부재 시 실외 solar_wm2 보충).
# 환산은 시스템 단위 정의(config_devices_units.UNIT_CONVERSIONS)를 그대로 사용한다 —
# 별도 계수를 두지 않고 시스템 변환표를 단일 출처로 삼는다(W_m2→umol_m2_s ×4.57 등).

# PPFD 의 시스템 단위 키
_PPFD_UNIT_KEY = 'umol_m2_s'

# 입력 단위 문자열 → config_devices_units 단위 키 정규화
_LIGHT_UNIT_ALIASES = {
    'umol_m2_s': 'umol_m2_s', 'umol': 'umol_m2_s', 'umol/m2/s': 'umol_m2_s',
    'µmol/m²/s': 'umol_m2_s', 'ppfd': 'umol_m2_s', 'par': 'umol_m2_s',
    'w_m2': 'W_m2', 'w/m^2': 'W_m2', 'w/m²': 'W_m2', 'w/m2': 'W_m2', 'wm2': 'W_m2',
    'solar': 'W_m2', 'solar_wm2': 'W_m2', 'irradiance': 'W_m2', 'radiation': 'W_m2', 'light': 'W_m2',
    'lux': 'lux', 'lx': 'lux', 'klux': 'klux', 'full': 'full',
    'j_cm2': 'J_cm2', 'j/cm²': 'J_cm2', 'j/cm2': 'J_cm2',
}
# 단위 미상 시 기본 가정: 시스템 관례(W/m²).
_LIGHT_DEFAULT_UNIT_KEY = 'W_m2'


def _normalize_light_unit(unit: Optional[str]) -> str:
    if not unit:
        return _LIGHT_DEFAULT_UNIT_KEY
    return _LIGHT_UNIT_ALIASES.get(unit.strip().lower(), _LIGHT_DEFAULT_UNIT_KEY)


def _apply_eq(eqn: str, x: float) -> float:
    """config 의 변환식('x * 4.57' 등)을 적용. 신뢰된 상수식만 평가."""
    return float(eval(eqn, {'__builtins__': {}}, {'x': float(x)}))


def _convert_via_system(value: float, from_key: str, to_key: str) -> Optional[float]:
    """config_devices_units.UNIT_CONVERSIONS 그래프를 BFS 로 따라가 단위 변환.

    변환 경로가 없으면 None. 시스템 변환표를 단일 출처로 사용한다.
    """
    if from_key == to_key:
        return value
    try:
        from aot.config_devices_units import UNIT_CONVERSIONS
    except Exception:
        return None
    # 인접 리스트: from -> [(to, eqn)]
    adj = {}
    for f, t, eqn in UNIT_CONVERSIONS:
        adj.setdefault(f, []).append((t, eqn))
    # BFS (값을 들고 전파)
    from collections import deque
    q = deque([(from_key, value)])
    seen = {from_key}
    while q:
        node, val = q.popleft()
        for nxt, eqn in adj.get(node, []):
            if nxt in seen:
                continue
            try:
                nval = _apply_eq(eqn, val)
            except Exception:
                continue
            if nxt == to_key:
                return nval
            seen.add(nxt)
            q.append((nxt, nval))
    return None


def light_to_ppfd(value: Optional[float], unit: Optional[str] = None) -> Optional[float]:
    """광 측정값을 PPFD(µmol/m²/s)로 환산 — 시스템 단위 변환표(UNIT_CONVERSIONS) 사용.

    단위 미상/미매핑이면 시스템 관례(W/m²)로 가정. 변환 경로가 없으면 원값 반환.
    이미 PPFD(umol_m2_s/ppfd)면 그대로 통과.
    """
    if value is None:
        return None
    from_key = _normalize_light_unit(unit)
    converted = _convert_via_system(value, from_key, _PPFD_UNIT_KEY)
    return converted if converted is not None else value


def local_today(tz=None) -> date:
    """tz 기준 오늘 날짜. tz 미지정 시 UTC(하위 호환)."""
    if tz is None:
        return datetime.now(timezone.utc).date()
    try:
        return datetime.now(timezone.utc).astimezone(tz).date()
    except Exception:
        return datetime.now(timezone.utc).date()

# 보상 한계: 정상 목표의 ±15%
_COMPENSATION_RATIO = 0.15

# 보상 분산 기간 (day)
_COMPENSATION_SPREAD_DAYS = 3


# ─────────────────────────────────────────────────────────────────────────────
# 인-메모리 누적 상태 (사이클 간 보존, DB는 일 단위 마감 시 저장)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DailyAccumulator:
    """하루치 누적 상태 (시설 로컬 자정 기준 초기화).

    day_local 은 시설 타임존 기준 날짜다. tz 미지정 환경(테스트 등)에서는 UTC 날짜로
    초기화되며, accumulate_cycle 에 tz 를 넘기면 로컬 자정 경계로 롤오버한다.
    """
    day_local: date  = field(default_factory=lambda: datetime.now(timezone.utc).date())
    dli:       float = 0.0    # mol/m²
    gdd:       float = 0.0    # °C·day (사이클 단위 누적)
    vpd_h:     float = 0.0    # kPa·h
    co2_kh:    float = 0.0    # ppm·h / 1000


# ─────────────────────────────────────────────────────────────────────────────
# 보상 제안
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CompensationSuggestion:
    """보상 제안 (Phase 1: suggest-only)."""
    metric:       str    # 'dli' | 'gdd'
    direction:    str    # 'increase' | 'decrease'
    debt:         float  # 부채량 (metric 단위)
    daily_delta:  float  # 일당 보상량 (metric 단위, spread 적용)
    authority:    str    # 'ACTIVE' | 'PASSIVE' | 'unattainable'
    message:      str    # 사람이 읽는 메시지


# ─────────────────────────────────────────────────────────────────────────────
# 누적 계산 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def accumulate_cycle(
    acc: DailyAccumulator,
    light_value: Optional[float],
    T_mean: float,
    VPD: float,
    CO2: float,
    cycle_sec: float,
    T_base: float = 10.0,
    light_unit: Optional[str] = None,
    tz=None,
) -> bool:
    """한 사이클분 메트릭을 누적한다. (로컬)날짜가 바뀌면 True 반환(일 마감 신호).

    light_value 는 센서 원단위 광측정값이며 light_unit 으로 PPFD 환산된다.
    tz 가 주어지면 시설 로컬 자정 기준으로 날짜 경계를 판단한다(미지정 시 UTC).
    """
    now_date = local_today(tz)
    rolled   = now_date != acc.day_local

    if rolled:
        # 날짜 바뀜 — 현재 값은 호출자가 DB 저장 후 초기화
        return True

    h = cycle_sec / 3600.0

    # DLI: 광측정값을 PPFD(µmol/m²/s)로 환산 후 × cycle_sec(s) × 1e-6 → mol/m²
    light_ppfd = light_to_ppfd(light_value, light_unit)
    if light_ppfd is not None and light_ppfd > 0:
        acc.dli   += light_ppfd * _PPFD_S_TO_MOL * cycle_sec

    # GDD: max(0, T_mean - T_base) × (cycle_sec / 86400)
    acc.gdd   += max(0.0, T_mean - T_base) * (cycle_sec / 86400.0)

    # VPD·h
    acc.vpd_h += max(0.0, VPD) * h

    # CO2·h / 1000
    acc.co2_kh += max(0.0, CO2) / 1000.0 * h

    return False


# ─────────────────────────────────────────────────────────────────────────────
# 보상 제안 생성
# ─────────────────────────────────────────────────────────────────────────────

def generate_suggestions(
    debt_dli: float,
    debt_gdd: float,
    authority: Dict[str, str],
    dli_target: Optional[float] = None,
    gdd_target: Optional[float] = None,
) -> List[CompensationSuggestion]:
    """부채 기반 보상 제안을 생성한다 (suggest-only).

    보상량은 _COMPENSATION_SPREAD_DAYS 일에 걸쳐 분산.
    NATURAL 권한 변수는 'unattainable' 권고.
    """
    from .authority import LEVEL_ACTIVE, LEVEL_PASSIVE, LEVEL_NATURAL

    suggestions: List[CompensationSuggestion] = []

    # DLI 부채
    if dli_target and abs(debt_dli) > dli_target * 0.05:
        direction = 'increase' if debt_dli > 0 else 'decrease'
        daily_delta = abs(debt_dli) / _COMPENSATION_SPREAD_DAYS
        cap = (dli_target * _COMPENSATION_RATIO) if dli_target else daily_delta

        light_auth = authority.get('Light_up', LEVEL_NATURAL)
        if light_auth == LEVEL_ACTIVE:
            auth_label = LEVEL_ACTIVE
            msg = (f'DLI 부채 {debt_dli:.2f} mol/m²: 보광등 강도/시간을 '
                   f'{daily_delta:.2f} mol/m²/day씩 {_COMPENSATION_SPREAD_DAYS}일 보상 권장')
        elif light_auth == LEVEL_PASSIVE:
            auth_label = LEVEL_PASSIVE
            daily_delta = min(daily_delta, cap)
            msg = (f'DLI 부채 {debt_dli:.2f} mol/m²: 차광 축소 또는 환기 최소화로 '
                   f'부분 보상 가능 (max {cap:.2f} mol/m²/day)')
        else:
            auth_label = 'unattainable'
            msg = (f'DLI 부채 {debt_dli:.2f} mol/m²: 보광 액추에이터 미보유 — '
                   f'목표 완화 또는 사이클 연장 권고')

        suggestions.append(CompensationSuggestion(
            metric='dli', direction=direction, debt=debt_dli,
            daily_delta=daily_delta, authority=auth_label, message=msg,
        ))

    # GDD 부채
    if gdd_target and abs(debt_gdd) > gdd_target * 0.02:
        direction = 'increase' if debt_gdd > 0 else 'decrease'
        daily_delta = abs(debt_gdd) / _COMPENSATION_SPREAD_DAYS

        t_up_auth   = authority.get('T_up',   LEVEL_NATURAL)
        t_down_auth = authority.get('T_down',  LEVEL_NATURAL)

        if debt_gdd > 0:  # GDD 부족 → T 상향
            if t_up_auth == LEVEL_ACTIVE:
                auth_label = LEVEL_ACTIVE
                msg = (f'GDD 부채 {debt_gdd:.2f}°C·day: 야간 T 목표를 '
                       f'+{daily_delta:.2f}°C·day/일 씩 {_COMPENSATION_SPREAD_DAYS}일 보상')
            elif t_up_auth == LEVEL_PASSIVE:
                auth_label = LEVEL_PASSIVE
                msg = (f'GDD 부채 {debt_gdd:.2f}°C·day: 보온커튼 사전 폐쇄로 부분 보상')
            else:
                auth_label = 'unattainable'
                msg = f'GDD 부채 {debt_gdd:.2f}°C·day: 난방 미보유 — 사이클 연장 권고'
        else:  # GDD 과잉 → T 하향
            if t_down_auth in (LEVEL_ACTIVE, LEVEL_PASSIVE):
                auth_label = t_down_auth
                msg = (f'GDD 과잉 {-debt_gdd:.2f}°C·day: 냉방·환기 증가 또는 '
                       f'차광 증대 권장')
            else:
                auth_label = 'unattainable'
                msg = f'GDD 과잉 {-debt_gdd:.2f}°C·day: 냉방 미보유 — 야간 환기 강화'

        suggestions.append(CompensationSuggestion(
            metric='gdd', direction=direction, debt=debt_gdd,
            daily_delta=daily_delta, authority=auth_label, message=msg,
        ))

    return suggestions


# ─────────────────────────────────────────────────────────────────────────────
# DB 영속화 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def save_daily_state(
    function_id: str,
    acc: DailyAccumulator,
    dli_target: Optional[float],
    gdd_target: Optional[float],
    suggestions: List[CompensationSuggestion],
) -> None:
    """누적 상태를 FunctionCumulativeState DB에 upsert한다."""
    try:
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        from aot.databases.models.function_cumulative import FunctionCumulativeState

        now_ts = time.time()
        debt_dli = (dli_target - acc.dli) if dli_target is not None else 0.0
        debt_gdd = (gdd_target - acc.gdd) if gdd_target is not None else 0.0

        comp_entries = [
            {'metric': s.metric, 'authority': s.authority, 'message': s.message,
             'ts': now_ts}
            for s in suggestions
        ]

        with session_scope(AOT_DB_PATH) as sess:
            row = sess.query(FunctionCumulativeState).filter_by(
                function_id=function_id, date=acc.day_local).first()
            if row is None:
                row = FunctionCumulativeState(
                    function_id=function_id, date=acc.day_local)
                sess.add(row)

            row.dli_actual  = acc.dli
            row.gdd_actual  = acc.gdd
            row.vpd_hours   = acc.vpd_h
            row.co2_hours   = acc.co2_kh
            row.dli_target  = dli_target
            row.gdd_target  = gdd_target
            row.debt_dli    = debt_dli
            row.debt_gdd    = debt_gdd
            row.updated_at  = now_ts
            if comp_entries:
                row.append_compensation(comp_entries[0])
            sess.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            'cumulative_tracker: DB 저장 실패 — %s', exc)


def load_recent_state(
    function_id: str,
    days: int = 7,
) -> List[dict]:
    """최근 N일 누적 상태를 리스트로 반환한다 (MCP 도구 지원용)."""
    try:
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        from aot.databases.models.function_cumulative import FunctionCumulativeState

        with session_scope(AOT_DB_PATH) as sess:
            rows = (sess.query(FunctionCumulativeState)
                    .filter_by(function_id=function_id)
                    .order_by(FunctionCumulativeState.date.desc())
                    .limit(days)
                    .all())
            result = [
                {
                    'date':        str(r.date),
                    'dli_actual':  r.dli_actual,
                    'dli_target':  r.dli_target,
                    'gdd_actual':  r.gdd_actual,
                    'gdd_target':  r.gdd_target,
                    'debt_dli':    r.debt_dli,
                    'debt_gdd':    r.debt_gdd,
                    'vpd_hours':   r.vpd_hours,
                    'co2_hours':   r.co2_hours,
                }
                for r in rows
            ]
            sess.expunge_all()
            return result
    except Exception:
        return []
