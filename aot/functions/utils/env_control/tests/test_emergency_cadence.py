"""긴급 판정이 개구부 구동 주기를 지우지 않는다 (2026-09-26).

실측(김제 육묘장3, 로컬 개발서버 09-25~26 리플레이 1,425사이클): 사이클 **전부**
가 긴급이었다 — 육묘 분무 잠금(분무기 하나만 0 강제)으로 654회, 크기만 큰 VPD
편차(허용 0.1 kPa × 3)로 771회. 그래서 구동 프로파일 '표준'(180초)이 한 번도
적용되지 않았고 측창이 64초 간격으로 움직였다.

두 규칙을 고정한다.
  1. 안전 게이트는 사이클 긴급 사유가 아니다 — 강제 명령은 `_dispatch` 가 장치별로
     즉시 보낸다(`safety_forced`). 강제받지 않은 개구부는 정상 주기를 지킨다.
  2. 편차는 **벌어지는 중** 일 때만 긴급이다 — 멀리 떨어진 채 머무는 것은 아니다.
"""
import types

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.utils.env_control import (
    REASON_PRIMARY, REASON_SAFETY_PRE_GATE,
)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_EXT_EXP, GATE_BIT_FOG_SUNBURN, GATE_BIT_WIND,
)
from aot.functions.utils.env_control.safety_gates import GateResult
from aot.functions.utils.env_control.types import TargetVar

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod


class _Host(CycleMixin):
    """_classify_emergency 에 필요한 것만 가진 호스트."""

    def __init__(self):
        self._force_immediate = False
        self.emergency_deviation_mult = 3.0
        self.emergency_rate_c_per_10min = 2.0


def _situation(vpd_dev, tol=0.1, T_trend=0.0):
    return types.SimpleNamespace(
        deviation_native={'vpd': vpd_dev},
        target={'vpd': TargetVar(value=1.28, tolerance=tol, priority=1.2)},
        context={'T_trend': T_trend})


def _clock(monkeypatch, start=1_000_000.0):
    t = {'now': start}
    monkeypatch.setattr(cycle_mod.time, 'time', lambda: t['now'])
    return t


_CALM = GateResult(triggered=False)


# ── 1. 안전 게이트 ─────────────────────────────────────────────────────────

def test_육묘_분무_잠금은_사이클_긴급이_아니다(monkeypatch):
    """분무기 하나를 0 으로 잡는 국소 잠금이 측창 구동 주기를 풀면 안 된다."""
    _clock(monkeypatch)
    fog_lock = GateResult(partial=True, gate_mask=GATE_BIT_FOG_SUNBURN,
                          forced_commands={'fog1': {'value': 0.0,
                                                    'reason': REASON_SAFETY_PRE_GATE}})
    assert _Host()._classify_emergency(fog_lock, _situation(0.0)) == (False, '')


def test_분무_잠금과_기상값_끊김이_겹쳐도_긴급이_아니다(monkeypatch):
    _clock(monkeypatch)
    both = GateResult(partial=True, gate_mask=GATE_BIT_FOG_SUNBURN | GATE_BIT_EXT_EXP,
                      forced_commands={'fog1': {'value': 0.0}}, vent_open_ceiling=True)
    assert _Host()._classify_emergency(both, _situation(0.0)) == (False, '')


def test_풍상측_강제_폐쇄도_사이클_긴급이_아니다(monkeypatch):
    """풍하측 창은 코디네이터가 정상 운용한다 — 그 창의 구동 주기까지 풀 이유가 없다.
    풍상측 폐쇄 자체는 `_dispatch` 가 장치별로 즉시 보낸다(아래 테스트)."""
    _clock(monkeypatch)
    windward = GateResult(partial=True, gate_mask=GATE_BIT_WIND,
                          forced_commands={'v1': {'value': 0.0}})
    assert _Host()._classify_emergency(windward, _situation(0.0)) == (False, '')


def test_강제_명령은_긴급_없이도_구동_주기_안에서_즉시_나간다(monkeypatch):
    """사이클 긴급을 없애도 안전 명령이 늦지 않는다는 근거 — 장치별 면제."""
    import aot.functions.custom_functions.env_coordinator_impl._helpers_mixin as hm
    t = {'now': 5000.0}
    monkeypatch.setattr(hm.time, 'time', lambda: t['now'])
    monkeypatch.setattr(hm.time, 'sleep', lambda *_: None)

    sends = []

    class _Adapter:
        def send(self, control, actuator_id, val, ch, cycle_sec):
            sends.append(val)

    class _Host2(HelpersMixin):
        def __init__(self):
            self.control = object()
            self._channel_map = {'win1': 0}
            self._by_id = {'win1': types.SimpleNamespace(
                kind='opening', cmd_constraints=types.SimpleNamespace(
                    min_dwell_sec=30.0, move_step_pct=5.0))}
            self._adapter_by_id = {'win1': _Adapter()}
            self._dispatch_sent = {}
            self.actuation_profile = 'standard'
            self.logger = types.SimpleNamespace(warning=lambda *a, **k: None,
                                                debug=lambda *a, **k: None)

    host = _Host2()
    host._dispatch({'win1': {'value': 80.0, 'reason': REASON_PRIMARY}})
    t['now'] += 10.0     # 표준 구동 주기(180초)의 한참 안쪽
    host._dispatch({'win1': {'value': 0.0, 'reason': REASON_SAFETY_PRE_GATE}},
                   emergency=False)
    assert sends == [80.0, 0.0], sends


# ── 2. 편차 ────────────────────────────────────────────────────────────────

def test_멀리_떨어진_채_머무는_편차는_긴급이_아니다(monkeypatch):
    """습한 밤·환기로 못 닿는 목표 — 창은 이미 할 수 있는 만큼 가 있다."""
    t = _clock(monkeypatch)
    host = _Host()
    results = []
    for _ in range(30):                       # 60초 주기로 30분, 편차 −0.9 고정
        results.append(host._classify_emergency(_CALM, _situation(-0.9)))
        t['now'] += 60.0
    assert all(r == (False, '') for r in results), results


def test_벌어지는_중인_큰_편차는_긴급이다(monkeypatch):
    t = _clock(monkeypatch)
    host = _Host()
    dev = -0.20
    hits = []
    for _ in range(20):                       # 10분에 0.2 kPa 씩 더 벌어진다
        hits.append(host._classify_emergency(_CALM, _situation(dev)))
        t['now'] += 60.0
        dev -= 0.02
    assert hits[-1] == (True, 'deviation:vpd'), hits[-5:]
    # 허용치×배수(0.3) 전에는 걸리지 않는다
    assert hits[0] == (False, '')


def test_비교할_과거가_없으면_편차_긴급을_걸지_않는다(monkeypatch):
    """재시작 직후 — 벌어지는 중인지 모른다. 급변은 변화율 판정이 따로 잡는다."""
    _clock(monkeypatch)
    assert _Host()._classify_emergency(_CALM, _situation(-2.0)) == (False, '')


def test_600초_주기의_직전_사이클이_비교_대상이_된다(monkeypatch):
    """영양처럼 주기가 창(10분)과 같으면 직전 사이클과 비교한다(지터 590초 포함)."""
    t = _clock(monkeypatch)
    host = _Host()
    assert host._classify_emergency(_CALM, _situation(-0.3))[0] is False
    t['now'] += 590.0
    assert host._classify_emergency(_CALM, _situation(-0.5)) == (True, 'deviation:vpd')


def test_변화율과_설정_변경은_그대로_긴급이다(monkeypatch):
    _clock(monkeypatch)
    host = _Host()
    assert host._classify_emergency(_CALM, _situation(0.0, T_trend=0.3)) == (True, 'T_rate')
    host._force_immediate = True
    assert host._classify_emergency(_CALM, _situation(0.0)) == (True, 'setpoint_change')
    assert host._force_immediate is False
