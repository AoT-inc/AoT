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


# ─────────────────────────────────────────────────────────────────────────────
# 안전 게이트의 강제 명령은 억제를 지나지 않는다
# ─────────────────────────────────────────────────────────────────────────────
# 위 억제(모터 모션 게이트·데드밴드)는 **모터 수명**을 위한 것이고, 안전
# 게이트는 그보다 위다. 순서가 뒤집히면 마지막 방어선이 수명 보호에 막힌다.
#
# 실측(2026-09-07 쿠마모토): 강우 게이트가 2시간 31분 동안 32회 발동해 측창에
# 0% 를 강제했는데, 직전 전송값도 0 이라 히스테리시스에 걸려 **한 번도
# 전달되지 않았다.** 그동안 버스 스케줄러는 재큐해 둔 옛 목표(69.8%)를 향해
# 창을 5%p 씩 열어 올렸고(최대 65%), 게이트가 풀리자 곧바로 69.8% 로 돌아갔다.
#
# ⚠ `emergency=True` 만으로는 부족하다 — 그것은 최소 이동 간격을
#   `emergency_period_sec` 으로 낮출 뿐, 값이 같으면 여전히 막는다. 위 사건이
#   정확히 그 경우였다(게이트 명령도 0, 직전 전송값도 0).

from aot.functions.utils.env_control import (          # noqa: E402
    REASON_SAFETY_PRE_GATE, REASON_SAFETY_POST_GATE, REASON_PRIMARY,
)


def _clocked(monkeypatch, start=1000.0):
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as mod
    monkeypatch.setattr(mod.time, 'sleep', lambda *_: None)
    clock = {'t': start}
    monkeypatch.setattr(mod.time, 'time', lambda: clock['t'])
    return clock


def test_safety_gate_command_is_resent_even_when_the_value_did_not_change(monkeypatch):
    """같은 값이어도 매번 보낸다 — 그것이 확인 사살이다.

    코디네이터가 믿는 '직전에 0 을 보냈다' 와 실제 개도는 갈라질 수 있다
    (출력층이 재큐된 옛 목표로 창을 열고 있었다). 값이 같다는 이유로 재전송을
    억제하면 그 갈라짐을 바로잡을 기회가 영영 없다.
    """
    clock = _clocked(monkeypatch)
    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    host._dispatch({'win1': {'value': 0.0, 'reason': REASON_SAFETY_PRE_GATE}},
                   emergency=True)
    first = len(adapter.sends)
    assert first == 1

    # 시간을 거의 진전시키지 않는다 — 최소 이동 간격·데드밴드가 가장 강하게
    # 막는 조건에서도 안전 명령은 통과해야 한다.
    for _ in range(4):
        clock['t'] += 1.0
        host._dispatch({'win1': {'value': 0.0, 'reason': REASON_SAFETY_PRE_GATE}},
                       emergency=True)

    assert len(adapter.sends) == first + 4, (
        '안전 게이트 명령이 억제됐습니다 — 강우 중 창이 열린 채로 남습니다. '
        '보낸 횟수: %d' % len(adapter.sends))
    assert all(value == 0.0 for value in adapter.sends)


def test_post_gate_correction_is_also_exempt(monkeypatch):
    """후게이트 보정도 안전 조치다 — 같은 규칙을 받는다."""
    clock = _clocked(monkeypatch)
    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    host._dispatch({'win1': {'value': 0.0, 'reason': REASON_SAFETY_POST_GATE}})
    clock['t'] += 1.0
    host._dispatch({'win1': {'value': 0.0, 'reason': REASON_SAFETY_POST_GATE}})

    assert len(adapter.sends) == 2


def test_normal_command_is_still_suppressed(monkeypatch):
    """일반 제어는 그대로 억제된다 — 면제를 넓히면 모터 수명이 사라진다."""
    clock = _clocked(monkeypatch)
    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter)

    host._dispatch({'win1': {'value': 25.0, 'reason': REASON_PRIMARY}})
    sent_after_first = len(adapter.sends)

    for _ in range(4):
        clock['t'] += 1.0
        host._dispatch({'win1': {'value': 25.0, 'reason': REASON_PRIMARY}})

    assert len(adapter.sends) == sent_after_first, (
        '일반 명령까지 억제가 풀렸습니다 — 창이 매 사이클 떨게 됩니다')


def test_safety_value_is_still_snapped_to_the_motor_grid(monkeypatch):
    """억제만 건너뛴다 — 격자는 지킨다.

    모터는 격자 값을 기대하고, 이후 비교도 그 위에서 이뤄져야 한다.
    """
    _clocked(monkeypatch)
    adapter = _RecordingAdapter()
    host = _DispatchHost(adapter, move_step_pct=5.0)

    host._dispatch({'win1': {'value': 63.2, 'reason': REASON_SAFETY_PRE_GATE}},
                   emergency=True)

    assert adapter.sends[-1] == 65.0
