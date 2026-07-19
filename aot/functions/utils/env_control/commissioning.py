# coding=utf-8
"""
env_control/commissioning.py — 사용자 트리거 장치 점검 엔진.

흐름:
  1. start_check(facility_uuid, actuator_ids)  → check_id 반환
  2. 매 cycle: tick(check_id, sensor_snapshot)  → 내부 상태 갱신
  3. get_result(check_id)                        → CheckResult (판정 대기 상태)
  4. submit_verdict(check_id, actuator_id, verdict, note)  → 설정 반영 지시

테스트 시퀀스 (kind 별):
  - heater / cooler : 0→pct_test→0, hold_s 유지, T 응답 관찰
  - opening / exhaust_fan / intake_fan : 0→80%→0, T + RH 응답
  - fogger : 0→100%→0, RH 응답
  - co2_injector : 0→50%→0, CO2 응답
  - circulation_fan : 0→100%→0, T 분산 (공간 균등화 지표 없으므로 노이즈 레벨만)
  - shade / curtain : 0→100%→0, RH 응답 (미미), 주로 dispatch 성공 여부

판정 종류 (verdict):
  - 'ok'          : 정상
  - 'sensor'      : 센서 오염 / 위치 오류
  - 'device'      : 장치 성능 저하 / 불량
  - 'external'    : 외부 교란 (바람, 강우 등)
  - 'skip'        : 이번 점검 건너뜀

판정 → 설정 반영:
  - ok      : calibration 신뢰 데이터로 등록 (K_actual 기준값 보정)
  - sensor  : 해당 센서 trust 0 강제 + hygiene 블랙리스트 플래그
  - device  : 해당 actuator K_upper_bound 하향 (실측 응답 기준) + 알람 플래그
  - external: 해당 시간대 hygiene 오염 마크
  - skip    : 무시
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── kind 별 테스트 파라미터 ─────────────────────────────────────────────────────

_KIND_TEST = {
    'heater':          {'pct': 60, 'hold_s': 180, 'vars': ['T'],       'expect_dir': {'T': +1}},
    'cooler':          {'pct': 60, 'hold_s': 180, 'vars': ['T'],       'expect_dir': {'T': -1}},
    'opening':         {'pct': 80, 'hold_s': 120, 'vars': ['T', 'RH'], 'expect_dir': None},
    'exhaust_fan':     {'pct': 80, 'hold_s': 120, 'vars': ['T', 'RH'], 'expect_dir': None},
    'intake_fan':      {'pct': 80, 'hold_s': 120, 'vars': ['T', 'RH'], 'expect_dir': None},
    'fogger':          {'pct':100, 'hold_s':  90, 'vars': ['RH'],      'expect_dir': {'RH': +1}},
    'co2_injector':    {'pct': 50, 'hold_s': 120, 'vars': ['CO2'],     'expect_dir': {'CO2': +1}},
    'shade':           {'pct':100, 'hold_s':  60, 'vars': ['T'],       'expect_dir': {'T': -1}},
    'curtain':         {'pct':100, 'hold_s':  60, 'vars': ['T'],       'expect_dir': {'T': -1}},
    'circulation_fan': {'pct':100, 'hold_s':  60, 'vars': ['T'],       'expect_dir': None},
}
_DEFAULT_TEST = {'pct': 50, 'hold_s': 120, 'vars': ['T'], 'expect_dir': None}

# 응답 임계값 (이 이상 변해야 "응답 있음")
_RESPONSE_THRESHOLD = {
    'T':   0.3,   # °C
    'RH':  2.0,   # %
    'CO2': 30.0,  # ppm
}

# 점검 전체 타임아웃
_CHECK_TIMEOUT_S = 600


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class ActuatorTestSpec:
    actuator_id: str
    kind: str
    name: str
    pct: float
    hold_s: float
    observe_vars: List[str]
    expect_dir: Optional[Dict[str, int]]   # +1 or -1, None = 방향 무관


@dataclass
class ActuatorTestResult:
    actuator_id: str
    kind: str
    name: str
    # 측정값
    baseline: Dict[str, float] = field(default_factory=dict)
    response: Dict[str, float] = field(default_factory=dict)   # 최대 변화량
    response_lag_s: Optional[float] = None
    noise_level: Dict[str, float] = field(default_factory=dict)
    dispatch_ok: bool = True
    # 분석
    responded: bool = False
    direction_match: Optional[bool] = None   # None = 방향 무관
    expected_response: Dict[str, float] = field(default_factory=dict)
    status: str = 'pending'   # pending / ok / warn / fail
    # 인간 판정
    verdict: Optional[str] = None   # ok / sensor / device / external / skip
    verdict_note: str = ''
    verdict_ts: Optional[float] = None
    # 설정 반영 결과
    applied_settings: List[str] = field(default_factory=list)


@dataclass
class CommissioningCheck:
    check_id: str
    facility_uuid: str
    started_ts: float
    specs: List[ActuatorTestSpec]
    results: Dict[str, ActuatorTestResult] = field(default_factory=dict)
    current_idx: int = 0       # 현재 테스트 중인 actuator 인덱스
    phase: str = 'baseline'    # baseline / active / recovery / done
    phase_started_ts: float = 0.0
    baseline_buf: Dict[str, deque] = field(default_factory=dict)
    active_buf: Dict[str, deque] = field(default_factory=dict)
    overall_status: str = 'running'   # running / awaiting_verdict / completed / error
    error_msg: str = ''

    def current_spec(self) -> Optional[ActuatorTestSpec]:
        if self.current_idx < len(self.specs):
            return self.specs[self.current_idx]
        return None

    def all_verdicts_submitted(self) -> bool:
        return all(
            r.verdict is not None
            for r in self.results.values()
        )


# ── 전역 저장소 (메모리, 프로세스 재시작 시 초기화) ──────────────────────────

_checks: Dict[str, CommissioningCheck] = {}


# ── 공개 API ──────────────────────────────────────────────────────────────────

def start_check(
    facility_uuid: str,
    actuator_list: List[Dict],   # [{'actuator_id', 'kind', 'name'}, ...]
) -> str:
    """점검을 시작하고 check_id 를 반환한다."""
    check_id = str(uuid.uuid4())[:8]
    specs = []
    for act in actuator_list:
        kind  = act.get('kind', '')
        tp    = _KIND_TEST.get(kind, _DEFAULT_TEST)
        specs.append(ActuatorTestSpec(
            actuator_id  = act['actuator_id'],
            kind         = kind,
            name         = act.get('name', act['actuator_id']),
            pct          = tp['pct'],
            hold_s       = tp['hold_s'],
            observe_vars = tp['vars'],
            expect_dir   = tp.get('expect_dir'),
        ))

    now = time.time()
    check = CommissioningCheck(
        check_id      = check_id,
        facility_uuid = facility_uuid,
        started_ts    = now,
        specs         = specs,
        phase         = 'baseline',
        phase_started_ts = now,
        baseline_buf  = {v: deque(maxlen=10) for v in ('T', 'RH', 'CO2')},
        active_buf    = {v: deque(maxlen=30) for v in ('T', 'RH', 'CO2')},
    )
    _checks[check_id] = check
    return check_id


def tick(
    check_id: str,
    sensor: Dict[str, float],    # {'T': ..., 'RH': ..., 'CO2': ...}
    dispatch_result: Optional[Dict[str, bool]] = None,  # {actuator_id: ok}
) -> Optional[Dict]:
    """매 사이클 호출. 현재 단계를 진행하고 액추에이터 명령 지시를 반환한다.

    Returns:
        {'set': {actuator_id: pct}} or {'off': [actuator_id]} or None (대기)
    """
    check = _checks.get(check_id)
    if not check or check.overall_status not in ('running',):
        return None

    now = time.time()
    if now - check.started_ts > _CHECK_TIMEOUT_S:
        check.overall_status = 'error'
        check.error_msg = 'timeout'
        return None

    spec = check.current_spec()
    if spec is None:
        _finalize(check)
        return None

    # dispatch 결과 기록
    if dispatch_result and spec.actuator_id in dispatch_result:
        result = check.results.get(spec.actuator_id)
        if result:
            result.dispatch_ok = dispatch_result[spec.actuator_id]

    elapsed = now - check.phase_started_ts

    if check.phase == 'baseline':
        _record_sensor(check.baseline_buf, sensor)
        if elapsed >= 30.0:   # 30초 baseline 수집
            _start_active(check, spec, now)
            return {'set': {spec.actuator_id: spec.pct}}

    elif check.phase == 'active':
        _record_sensor(check.active_buf, sensor)
        if elapsed >= spec.hold_s:
            _evaluate(check, spec)
            _start_recovery(check, spec, now)
            return {'off': [spec.actuator_id]}

    elif check.phase == 'recovery':
        if elapsed >= 30.0:   # 30초 회복 대기
            _next_actuator(check, now)

    return None


def get_result(check_id: str) -> Optional[Dict]:
    """현재 점검 상태 + 결과를 직렬화해 반환한다."""
    check = _checks.get(check_id)
    if not check:
        return None
    return _serialize(check)


def submit_verdict(
    check_id: str,
    actuator_id: str,
    verdict: str,
    note: str = '',
) -> Tuple[bool, str, List[Dict]]:
    """인간 판정을 기록하고 설정 반영 지시 목록을 반환한다.

    Returns:
        (ok: bool, message: str, actions: List[Dict])
    """
    check = _checks.get(check_id)
    if not check:
        return False, 'check_id not found', []

    result = check.results.get(actuator_id)
    if not result:
        return False, 'actuator result not found', []

    if verdict not in ('ok', 'sensor', 'device', 'external', 'skip'):
        return False, f'invalid verdict: {verdict}', []

    result.verdict      = verdict
    result.verdict_note = note
    result.verdict_ts   = time.time()

    actions = _compute_actions(result)
    result.applied_settings = [a['description'] for a in actions]

    if check.all_verdicts_submitted():
        check.overall_status = 'completed'

    return True, 'ok', actions


def list_checks(facility_uuid: str) -> List[Dict]:
    """시설의 점검 이력 목록 (최근 10개)."""
    items = [
        _serialize(c) for c in _checks.values()
        if c.facility_uuid == facility_uuid
    ]
    items.sort(key=lambda x: x['started_ts'], reverse=True)
    return items[:10]


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _record_sensor(buf: Dict[str, deque], sensor: Dict):
    for v in ('T', 'RH', 'CO2'):
        val = sensor.get(v)
        if val is not None:
            buf[v].append(float(val))


def _mean(q: deque) -> Optional[float]:
    if not q:
        return None
    return sum(q) / len(q)


def _noise(q: deque) -> float:
    if len(q) < 2:
        return 0.0
    m = sum(q) / len(q)
    return (sum((x - m) ** 2 for x in q) / len(q)) ** 0.5


def _start_active(check: CommissioningCheck, spec: ActuatorTestSpec, now: float):
    baseline = {}
    for v in spec.observe_vars:
        m = _mean(check.baseline_buf[v])
        if m is not None:
            baseline[v] = m

    result = ActuatorTestResult(
        actuator_id = spec.actuator_id,
        kind        = spec.kind,
        name        = spec.name,
        baseline    = baseline,
        noise_level = {v: _noise(check.baseline_buf[v]) for v in spec.observe_vars},
        status      = 'running',
    )
    check.results[spec.actuator_id] = result
    for v in ('T', 'RH', 'CO2'):
        check.active_buf[v].clear()

    check.phase            = 'active'
    check.phase_started_ts = now


def _start_recovery(check: CommissioningCheck, spec: ActuatorTestSpec, now: float):
    check.phase            = 'recovery'
    check.phase_started_ts = now


def _next_actuator(check: CommissioningCheck, now: float):
    check.current_idx += 1
    if check.current_idx >= len(check.specs):
        _finalize(check)
    else:
        for v in ('T', 'RH', 'CO2'):
            check.baseline_buf[v].clear()
            check.active_buf[v].clear()
        check.phase            = 'baseline'
        check.phase_started_ts = now


def _evaluate(check: CommissioningCheck, spec: ActuatorTestSpec):
    result = check.results.get(spec.actuator_id)
    if not result:
        return

    for v in spec.observe_vars:
        base = result.baseline.get(v)
        active_vals = list(check.active_buf.get(v, []))
        if base is None or not active_vals:
            result.response[v] = 0.0
            continue

        peak = max(active_vals, key=lambda x: abs(x - base))
        delta = peak - base
        result.response[v] = delta

        # 응답 지연 추정: 처음 threshold 초과 시점
        thresh = _RESPONSE_THRESHOLD.get(v, 0.5)
        for i, val in enumerate(active_vals):
            if abs(val - base) >= thresh:
                result.response_lag_s = i * 60.0   # cycle_sec ≈ 60s
                break

    # 응답 여부 판단
    responded = False
    for v in spec.observe_vars:
        delta = abs(result.response.get(v, 0.0))
        if delta >= _RESPONSE_THRESHOLD.get(v, 0.5):
            responded = True
            break
    result.responded = responded

    # 방향 일치 여부
    if spec.expect_dir:
        matches = []
        for v, expected_sign in spec.expect_dir.items():
            actual = result.response.get(v, 0.0)
            if abs(actual) >= _RESPONSE_THRESHOLD.get(v, 0.5):
                matches.append((actual > 0) == (expected_sign > 0))
        result.direction_match = all(matches) if matches else None

    # 기대 응답 산출 (kind별 K_default × pct)
    _K_EXPECT = {
        'heater':   {'T': 0.08},
        'cooler':   {'T': -0.08},
        'fogger':   {'RH': 0.5},
        'co2_injector': {'CO2': 2.0},
        'opening':  {'T': -0.05, 'RH': 0.02},
        'exhaust_fan': {'T': -0.04, 'RH': -0.01},
    }
    k_ref = _K_EXPECT.get(spec.kind, {})
    for v, k in k_ref.items():
        result.expected_response[v] = k * spec.pct

    # 자동 상태 판단 (인간 판정 전 힌트)
    if not result.dispatch_ok:
        result.status = 'fail'
    elif not responded:
        result.status = 'warn'
    elif result.direction_match is False:
        result.status = 'warn'
    else:
        result.status = 'ok'


def _finalize(check: CommissioningCheck):
    if check.overall_status == 'running':
        check.overall_status = 'awaiting_verdict'


def _compute_actions(result: ActuatorTestResult) -> List[Dict]:
    """판정에 따른 설정 반영 지시 목록."""
    actions = []
    v = result.verdict

    if v == 'ok':
        # 실측 응답을 신뢰 캘리브레이션 데이터로 등록
        for var, delta in result.response.items():
            baseline_v = result.baseline.get(var)
            if baseline_v is not None and abs(delta) > 0:
                actions.append({
                    'type': 'calibration_anchor',
                    'actuator_id': result.actuator_id,
                    'var': var,
                    'k_measured': delta,
                    'description': f'[{result.name}] {var} 응답 {delta:+.3f} — 캘리브레이션 기준값 등록',
                })

    elif v == 'sensor':
        actions.append({
            'type': 'sensor_trust_zero',
            'actuator_id': result.actuator_id,
            'description': f'[{result.name}] 센서 신뢰도 0으로 설정 — 센서 점검 필요',
        })
        actions.append({
            'type': 'hygiene_blacklist',
            'actuator_id': result.actuator_id,
            'description': f'[{result.name}] 점검 기간 데이터 hygiene 제외',
        })

    elif v == 'device':
        # 실측 응답 기준으로 K_upper_bound 하향
        for var, delta in result.response.items():
            expected = result.expected_response.get(var)
            if expected and abs(delta) > 0 and abs(expected) > 0:
                ratio = abs(delta) / abs(expected)
                actions.append({
                    'type': 'k_upper_bound_adjust',
                    'actuator_id': result.actuator_id,
                    'var': var,
                    'ratio': round(ratio, 3),
                    'description': f'[{result.name}] 효과계수 상한 {ratio*100:.0f}%로 조정 — 장치 점검 권고',
                })
        actions.append({
            'type': 'alarm',
            'actuator_id': result.actuator_id,
            'description': f'[{result.name}] 장치 성능 저하 알람 등록',
        })

    elif v == 'external':
        actions.append({
            'type': 'hygiene_blacklist',
            'actuator_id': result.actuator_id,
            'description': f'[{result.name}] 점검 기간 외부 교란으로 hygiene 제외',
        })

    return actions


def _serialize(check: CommissioningCheck) -> Dict:
    results_list = []
    for spec in check.specs:
        r = check.results.get(spec.actuator_id)
        if r:
            results_list.append({
                'actuator_id':       r.actuator_id,
                'kind':              r.kind,
                'name':              r.name,
                'baseline':          r.baseline,
                'response':          r.response,
                'response_lag_s':    r.response_lag_s,
                'noise_level':       r.noise_level,
                'expected_response': r.expected_response,
                'responded':         r.responded,
                'direction_match':   r.direction_match,
                'dispatch_ok':       r.dispatch_ok,
                'status':            r.status,
                'verdict':           r.verdict,
                'verdict_note':      r.verdict_note,
                'applied_settings':  r.applied_settings,
            })
        else:
            results_list.append({
                'actuator_id': spec.actuator_id,
                'kind':        spec.kind,
                'name':        spec.name,
                'status':      'pending',
                'verdict':     None,
            })

    current_spec = check.current_spec()
    return {
        'check_id':       check.check_id,
        'facility_uuid':  check.facility_uuid,
        'started_ts':     check.started_ts,
        'overall_status': check.overall_status,
        'phase':          check.phase,
        'current_actuator': current_spec.actuator_id if current_spec else None,
        'progress': {
            'done':  check.current_idx,
            'total': len(check.specs),
        },
        'results':        results_list,
        'error_msg':      check.error_msg,
    }
