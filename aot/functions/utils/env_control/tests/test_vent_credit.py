# coding=utf-8
"""실외가 **대신 해 주는 몫**만큼 냉난방의 짐을 던다 (2026-08-26).

## `vent_first` 는 이분법이었다

파킹 판정은 "환기로 **전부** 되는가" 하나만 묻는다. 그래서 상태가 둘뿐이었다 —
전부 되면 냉난방을 재우고, 아니면 냉난방이 **전체 편차**를 자기 혼자 메울
값으로 계산한다. 흔한 것은 그 중간인데 그 중간을 표현할 수단이 없었다.

실측(쿠마모토 イチゴ, 2026-08-26 19:47):

    실내 VPD 0.67   목표 1.0   실외 0.897
    실외가 메울 수 있는 몫 = (0.897 − 0.67) / (1.0 − 0.67) = 69%

실외가 목표까지의 69% 를 공짜로 해 주는데 난방기는 그것을 **모른 채** 편차
−0.33 전부를 자기 몫으로 계산해 46.5% 로 돌고 있었다. 창은 열려 있고 난방기는
과다 가동 — **열을 버리며 데운다.** 사용자가 본 그 모양이다.

## 창을 잠그는 것(`hvac_interlock`)은 답이 아니다

잠그면 그 69% 를 통째로 버리고 난방 부하가 3배가 된다. 열 손실은 막지만 더
많은 에너지를 쓴다. 판단 기준은 스위치가 아니라 **내외 환경 차이**여야 한다.
실외가 못 도우면 크레딧이 0 이라, 잠금 없이도 겨울에는 저절로 예전 동작이 된다.

## ⚠ 도메인 간 부하분담을 되살리는 것이 아니다

2026-08-25 사고는 액추에이터가 **주장한 효과**(모델 출력)를 도메인 너머로
넘기다 부호가 뒤집혀 반대편을 켰다. 여기서 넘기는 것은 모델 출력이 아니라
**실외 측정값**이다 — 어떤 장치의 주장도 아닌 독립적인 물리 상한이고, 한
장치가 고장 나도 값이 바뀌지 않는다. 그 사고의 성립 조건이 여기엔 없다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    VENT_FIRST_PATIENCE_S, CoordinatorState, _ventilation_credit, coordinate,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context=None, target=None):
        self.target = target or _TARGET
        self.deviation_native = deviation
        self.context = context or {'cycle_sec': 600.0}


# 실측 그대로 — 목표 VPD 1.0(허용 0.1), 실내 0.67 → 편차 −0.33.
_TARGET = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
_DEV    = {'vpd': -0.33}


def _vent(aid='vent'):
    return ActuatorProfile(
        actuator_id=aid, kind='opening',
        effect_model={'vpd': _effect('↑', 0.3)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _heater(aid='heater'):
    return ActuatorProfile(
        actuator_id=aid, kind='heater',
        effect_model={'vpd': _effect('↑', 0.4)},
        cost_fn=lambda env, pct: 9.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _ctx(vpd_ext, **kw):
    """실외 VPD 를 T/RH 로 되돌려 넣는다(`_outdoor_reachable` 이 그렇게 읽는다)."""
    import math
    T = 30.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T,
           'RH_ext': (1.0 - vpd_ext / svp) * 100.0,
           'vent_first': True, 'vent_futility_gate': False}
    ctx.update(kw)
    return ctx


class TestTheCreditItself:

    def test_it_measures_the_share_the_outdoor_can_take(self):
        """실측 재현 — 0.897 은 0.67 에서 0.227 만큼 데려다 준다."""
        c = _ventilation_credit(_Situation(_DEV), _ctx(0.897), [_vent()], set())
        assert c['vpd'] == pytest.approx(0.227, abs=0.005)

    def test_it_never_exceeds_the_need(self):
        """넘기면 보정된 편차의 **부호가 뒤집혀** 냉난방이 반대로 돈다 —
        2026-08-25 사고와 같은 모양이다."""
        c = _ventilation_credit(_Situation(_DEV), _ctx(5.0), [_vent()], set())
        assert c['vpd'] == pytest.approx(0.33)

    def test_the_wrong_direction_earns_nothing(self):
        """실외가 더 습하면(VPD 더 낮으면) 열수록 목표에서 멀어진다."""
        c = _ventilation_credit(_Situation(_DEV), _ctx(0.3), [_vent()], set())
        assert 'vpd' not in c

    def test_inside_the_tolerance_there_is_nothing_to_share(self):
        c = _ventilation_credit(_Situation({'vpd': -0.01}), _ctx(0.897),
                                [_vent()], set())
        assert c == {}


class TestItNeedsWindowsThatCanActuallyOpen:
    """창이 못 열리면 실외는 아무것도 못 해 준다.

    그때 크레딧을 주면 **냉난방이 있지도 않은 도움을 믿고 물러난다** —
    비 오는 날 난방이 모자라는 모양이 된다.
    """

    def test_no_vents_no_credit(self):
        assert _ventilation_credit(_Situation(_DEV), _ctx(0.897), [], set()) == {}

    def test_parked_vents_earn_nothing(self):
        """무익 판정·냉난방 연동 잠금으로 파킹된 창은 도움이 아니다."""
        v = _vent()
        c = _ventilation_credit(_Situation(_DEV), _ctx(0.897), [v],
                                {v.actuator_id})
        assert c == {}

    def test_a_made_up_outdoor_reading_earns_nothing(self):
        """실외 캐시조차 없어 지어낸 값은 근거가 아니다."""
        ctx = _ctx(0.897, external={'_ext_synthetic': True})
        assert _ventilation_credit(_Situation(_DEV), ctx, [_vent()], set()) == {}


class TestEndToEnd:
    """coordinate() 를 통과시켜 난방기 명령이 실제로 줄어드는지 본다."""

    def _heater_pct(self, vpd_ext, vent_first=True, cycles=1):
        vent, heater = _vent(), _heater()
        ctx = _ctx(vpd_ext)
        ctx['vent_first'] = vent_first
        st = CoordinatorState()
        st.prev_commands = {'vent': 20.0, 'heater': 46.5}
        st.integral      = {'vent': 20.0, 'heater': 46.5}
        pct = None
        for _ in range(cycles):
            cmds, st = coordinate(_Situation(_DEV, ctx), [vent, heater], st,
                                  unique_id='t')
            pct = cmds['heater'].control_value()
        return pct, cmds['vent'].control_value()

    def test_the_heater_carries_less_when_the_outdoor_helps(self):
        helped, _ = self._heater_pct(0.897)
        alone, _  = self._heater_pct(0.897, vent_first=False)
        assert helped < alone, (
            '실외가 69%%를 메우는데 난방기가 그대로다 (%.1f vs %.1f)'
            % (helped, alone))

    def test_the_windows_still_open(self):
        """냉난방의 짐을 더는 것이지 환기를 멈추는 게 아니다.

        ⚠ 크레딧을 환기 자신에게도 적용하면 자기가 할 일을 자기 편차에서 빼
          창이 열리지 않는다 — 그러면 아무도 일하지 않는다.
        """
        _, vent = self._heater_pct(0.897)
        assert vent > 20.0

    def test_a_cold_outdoor_changes_nothing(self):
        """실외가 못 도우면 크레딧 0 — 잠금 없이도 예전 동작이 된다."""
        helped, _ = self._heater_pct(0.3)
        alone, _  = self._heater_pct(0.3, vent_first=False)
        assert helped == pytest.approx(alone)

    def test_it_is_off_unless_vent_first_is_on(self):
        """업그레이드로 조용히 달라지는 설치가 없어야 한다."""
        on, _  = self._heater_pct(0.897)
        off, _ = self._heater_pct(0.897, vent_first=False)
        assert on != off


class TestPatienceCoversPartialRelianceToo:
    """부분 의지도 **실패하면 넘긴다.**

    크레딧만 주고 인내를 안 세면, 실외가 0.227 을 해 준다고 믿은 채 목표에
    영영 못 닿아도 난방기는 계속 나머지만 맡는다 — `vent_first` 의 원래 결함
    ("여력만 묻고 결과를 안 묻는다")이 그대로 되살아난다.
    """

    def _run(self, cycles):
        vent, heater = _vent(), _heater()
        ctx = _ctx(0.897)
        st = CoordinatorState()
        st.prev_commands = {'vent': 20.0, 'heater': 46.5}
        st.integral      = {'vent': 20.0, 'heater': 46.5}
        for _ in range(cycles):
            cmds, st = coordinate(_Situation(_DEV, ctx), [vent, heater], st,
                                  unique_id='t')
        return cmds['heater'].control_value(), st

    def test_partial_reliance_accumulates_patience(self):
        _pct, st = self._run(2)
        assert st.vent_first_held_s == pytest.approx(1200.0)

    def test_after_the_patience_the_heater_owns_it_all(self):
        n = int(VENT_FIRST_PATIENCE_S // 600) + 1
        late, _  = self._run(n)
        early, _ = self._run(1)
        assert late > early, (
            '%.0f초를 못 맞췄는데도 난방기가 아직 일부만 맡는다' % (n * 600))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
