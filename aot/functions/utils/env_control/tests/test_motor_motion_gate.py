"""측창·천창(opening) 모터 수명 보호 — 이동 게이트 검증.

PI 제어기가 매 주기 미세하게 흔들리는 목표값을 내도 모터가 매번 구동되지 않아야 한다.
HelpersMixin._motor_motion_gate (순수 로직) 과 _dispatch (통합 경로) 를 검증한다.
"""
import types

from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)


class _FakeConstraints:
    def __init__(self, min_dwell_sec=30.0, move_step_pct=5.0):
        self.min_dwell_sec = min_dwell_sec
        self.move_step_pct = move_step_pct


class _FakeProfile:
    def __init__(self, kind='opening', min_dwell_sec=30.0, move_step_pct=5.0):
        self.kind = kind
        self.cmd_constraints = _FakeConstraints(min_dwell_sec, move_step_pct)


class _RecordingAdapter:
    """send() 호출(=실제 모터 명령)을 기록하는 가짜 어댑터."""
    def __init__(self):
        self.sends = []

    def send(self, control, actuator_id, val, ch, cycle_sec):
        self.sends.append(val)


def _make_gate_host():
    """_motor_motion_gate 만 쓰는 최소 호스트."""
    host = types.SimpleNamespace()
    host._motor_motion_gate = HelpersMixin._motor_motion_gate.__get__(host)
    return host


# ── 순수 게이트 로직 ────────────────────────────────────────────────────────

def test_gate_first_move_quantizes():
    g = _make_gate_host()
    send, move = g._motor_motion_gate(23.0, None, age=0.0, min_dwell=180.0, step=5.0)
    assert move is True
    assert send == 25.0  # 5% 격자 스냅


def test_gate_suppresses_sub_step_wiggle():
    g = _make_gate_host()
    # 직전 송신 25%, 목표가 23~27% 로 흔들려도 같은 스텝 → 이동 금지
    for tgt in (23.0, 24.0, 26.0, 27.0, 25.4):
        send, move = g._motor_motion_gate(tgt, 25.0, age=9999.0, min_dwell=180.0, step=5.0)
        assert move is False, f"{tgt} 에서 불필요 이동 발생"
        assert send == 25.0


def test_gate_allows_full_step_after_dwell():
    g = _make_gate_host()
    # 한 스텝 이상 차이 + 최소 간격 경과 → 이동 허용
    send, move = g._motor_motion_gate(31.0, 25.0, age=200.0, min_dwell=180.0, step=5.0)
    assert move is True
    assert send == 30.0


def test_gate_blocks_move_within_min_dwell():
    g = _make_gate_host()
    # 한 스텝 차이지만 최소 간격 미경과 + 급변 아님 → 억제
    send, move = g._motor_motion_gate(31.0, 25.0, age=60.0, min_dwell=180.0, step=5.0)
    assert move is False
    assert send == 25.0


def test_gate_blocks_large_deviation_within_min_dwell():
    """순수 게이트 로직엔 더 이상 급변 크기 기반 우회가 없다 — 긴급 여부는 호출자
    (_dispatch)가 min_dwell 자체를 emergency_period_sec 으로 낮춰 표현한다."""
    g = _make_gate_host()
    send, move = g._motor_motion_gate(70.0, 25.0, age=5.0, min_dwell=180.0, step=5.0)
    assert move is False
    assert send == 25.0


def test_gate_custom_step_granularity():
    g = _make_gate_host()
    # step=10 격자: 23% → 20%, 23~24% 흔들림은 같은 스텝(20) → 이동 금지
    send, move = g._motor_motion_gate(23.0, None, age=0.0, min_dwell=180.0, step=10.0)
    assert move is True and send == 20.0
    send, move = g._motor_motion_gate(24.0, 20.0, age=9999.0, min_dwell=180.0, step=10.0)
    assert move is False and send == 20.0


# ── _dispatch 통합: 흔들리는 목표 시퀀스에서 송신 횟수 급감 ──────────────────

class _DispatchHost(HelpersMixin):
    def __init__(self, adapter, move_step_pct=5.0):
        self.control = object()
        self._channel_map = {'win1': 0}
        self._by_id = {'win1': _FakeProfile(
            'opening', min_dwell_sec=30.0, move_step_pct=move_step_pct)}
        self._adapter_by_id = {'win1': adapter}
        self._dispatch_sent = {}
        self.debug_logging = False

        class _L:
            def warning(self, *a, **k):
                pass

            def debug(self, *a, **k):
                pass
        self.logger = _L()


def test_dispatch_motor_suppresses_per_cycle_micro_moves(monkeypatch):
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)

    # 시간을 수동 전진시켜 최소 이동 간격 효과를 끈다(즉 게이트의 양자화/히스테리시스만 평가).
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    # PI 정상상태 흔들림을 모사: 25% 부근에서 ±2% 진동.
    # 사이클 간격 50초(누적 500초 < watchdog 600초) → 강제 재확인을 배제하고
    # 게이트의 양자화/히스테리시스에 의한 미세이동 억제만 격리 평가한다.
    targets = [25.3, 24.1, 26.4, 23.8, 25.9, 24.6, 26.1, 25.0, 23.2, 26.8]
    for tgt in targets:
        clock['t'] += 50.0
        host._dispatch({'win1': {'value': tgt}})

    # 모든 목표가 5% 격자상 25%로 스냅 → 첫 1회만 송신, 이후 미세 진동은 전부 억제
    assert adapter.sends == [25.0], f"micro-move 억제 실패: {adapter.sends}"


def test_dispatch_motor_moves_on_real_demand_shift(monkeypatch):
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    # 실제 수요가 단계적으로 상승(온도 상승 → 측창 점진 개방), 사이클마다 300초 경과
    targets = [10.0, 22.0, 41.0, 59.0, 78.0]
    for tgt in targets:
        clock['t'] += 300.0
        host._dispatch({'win1': {'value': tgt}})

    # 실수요 변화는 격자에 맞춰 전부 반영되어야 한다
    assert adapter.sends == [10.0, 20.0, 40.0, 60.0, 80.0], adapter.sends


def test_dispatch_motor_step_zero_disables_gate(monkeypatch):
    """move_step_pct=0 → 게이트 비활성. 1% 이상 미세 변동도 그대로 송신(기존 deadband 동작)."""
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter, move_step_pct=0.0)

    # 25% 부근 ±2% 진동 — deadband(1%) 만 적용되므로 1% 이상 변동마다 송신(양자화 없음)
    targets = [25.3, 24.1, 26.4, 23.8]
    for tgt in targets:
        clock['t'] += 50.0
        host._dispatch({'win1': {'value': tgt}})

    # 격자 스냅 없이 원래 값들이 그대로 송신된다 (미세 진동도 작동)
    assert adapter.sends == [25.3, 24.1, 26.4, 23.8], adapter.sends


# ── 구동주기(actuation_profile) / 긴급(emergency) 통합 검증 ──────────────────
#
# _DispatchHost 는 actuation_profile/actuation_period_sec/emergency_period_sec
# 을 설정하지 않으면 _actuation_params() 의 getattr 기본값(표준 180s / 긴급 60s)을
# 그대로 쓴다 — 표준값이 곧 기존 _MOTOR_MIN_MOVE_SEC(180)과 같아, 아래 케이스들은
# 별도 설정 없이도 기존 회귀 테스트들과 동일한 기본 동작 위에서 검증된다.

def test_dispatch_emergency_bypasses_normal_period_partway_through_dwell(monkeypatch):
    """표준(180s) 구동주기 중간(90s 경과) 시점 — 정상 사이클은 이동 억제,
    긴급(emergency=True, 60s 하한)은 이동 허용. 안전게이트 강제명령 지연 버그 회귀 방지."""
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    host._dispatch({'win1': {'value': 25.0}})   # 최초 이동
    assert adapter.sends == [25.0]

    clock['t'] += 90.0   # 표준주기(180s) 미경과, 긴급주기(60s) 는 경과
    host._dispatch({'win1': {'value': 0.0}})    # 정상 사이클 — 억제되어야 함
    assert adapter.sends == [25.0], "정상 사이클은 90s 시점에 이동하면 안 됨"

    host._dispatch({'win1': {'value': 0.0}}, emergency=True)  # 안전게이트 강제명령 경로
    assert adapter.sends == [25.0, 0.0], (
        "긴급 사이클은 정상 구동주기를 우회해 즉시 반영돼야 함(강우·돌풍 등)")


def test_dispatch_gentle_period_survives_default_watchdog(monkeypatch):
    """구동주기(custom, 900s)가 기본 워치독(600s)보다 길면 워치독도 함께 늘어나,
    600s 강제 재확인이 900s 미만인 구동주기를 무력화하지 않아야 한다."""
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)
    host.actuation_profile = 'custom'
    host.actuation_period_sec = 900.0

    host._dispatch({'win1': {'value': 25.0}})   # 최초 이동
    clock['t'] += 650.0   # 옛 고정 워치독(600s) 은 지났지만 구동주기(900s) 는 아직
    host._dispatch({'win1': {'value': 0.0}})
    assert adapter.sends == [25.0], (
        "900s 구동주기 설정에서 650s 시점에 강제 이동이 발생하면 워치독 정합 버그")


def test_dispatch_watchdog_reconfirm_does_not_reset_dwell_clock(monkeypatch):
    """값이 같은 워치독 재확인 전송은 '실제 이동' 시각을 갱신하면 안 된다.
    갱신되면 그 다음의 진짜 수요 변화가 불필요하게 다시 최소 간격만큼 지연된다."""
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': 1000.0}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])

    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)   # 표준 프로파일: 정상주기 180s

    host._dispatch({'win1': {'value': 25.0}})    # t=1000, 실제 이동
    assert adapter.sends == [25.0]

    clock['t'] += 600.0   # 워치독(600s) 도달, 목표값 변화 없음 → 재확인 전송(이동 아님)
    host._dispatch({'win1': {'value': 25.0}})
    assert adapter.sends == [25.0, 25.0], "워치독 재확인 전송 누락"

    clock['t'] += 100.0   # 재확인 후 100s(= 최초 이동 후 총 700s) 뒤 실제 수요 변화
    host._dispatch({'win1': {'value': 0.0}})
    assert adapter.sends == [25.0, 25.0, 0.0], (
        "워치독 재확인이 dwell 시계를 리셋해 실제 이동(정상주기 180s 는 이미 충족)을 "
        "억제하면 버그")
