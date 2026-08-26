# coding=utf-8
"""습도가 이미 넘쳤으면 습윤형 분무를 쓰지 않는다 (2026-08-25).

## 무엇이 문제였나

결합 drive 는 각 축을 자기 허용오차로 정규화해 겨루게 한다. 그래서 "이미
한참 벗어난 축을 더 나빠지게 하면 안 된다" 는 개념이 없다 — 26.5% 초과나
5.1% 초과나 방향만 같으면 유효도로만 겨룬다.

실측(2026-08-25 イチゴ, 목표 온도 22 °C · 습도 62.5%):

    온도  편차 +1.4 °C   e=+0.233  g=0.285  w=0.1425   ← 냉각 방향
    습도  편차 +26.5 %   e=−0.883  g=0.014  w=0.0072   ← 가습 방향(반대)
                                      e_norm = +0.180 → 분무 20% 켜짐

방향 신호는 습도가 4배 강한데 **가중치가 20배**라 온도가 이긴다. 분무기의
습도 효과가 물리적으로 작기 때문이고(RH 89% 에서 ΔRH 0.43%), 그 작음이 곧
"습도는 어차피 못 건드리니 온도나 잡자" 로 읽힌 것이다.

얻는 것은 1.71 °C 냉각인데 대가는 포화에 가까운 공기에서 잎이 젖고 마를 틈이
없는 것이다 — 잿빛곰팡이가 오는 조건이라 그 거래는 성립하지 않는다.

## 왜 drive 가 아니라 게이트인가

결합 drive 에 "초과 축 페널티" 를 넣는 일반해도 있지만 **모든 액추에이터의
거동을 바꾼다.** 여기서 막고 싶은 것은 한 종류(습윤형 분무기)의 한 상황이고,
이유도 습도 숫자가 아니라 **젖은 잎**이다 — 일소 잠금과 같은 성격이라 같은
자리에 같은 모양으로 둔다.

## ⚠ 판정 시점

`_check_hard_constraints`(정적 `humid_max`)가 아니라 **`assess` 뒤**에서
판정해야 한다. 유효 목표는 프로그램·VPD 분해를 거쳐 `assess` 가 정하므로,
함수 옵션의 `target_humidity` 로 판정하면 실제로 쓰인 목표와 어긋난다 —
실측에서 설정은 65.0 인데 유효 목표는 62.5 였다.
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    apply_threshold_and_gate_overrides, apply_wetting_fog_humidity_ceiling,
    latch_threshold, RH_HYST_PCT,
)
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _fogger(aid='fog_01', wetting=True):
    return ActuatorProfile(
        actuator_id=aid,
        kind='fogger',
        capabilities=['humidify', 'cooling_passive'],
        cost_fn=lambda env, pct: 5.0,
        response_sec=60.0,
        safe_default=0.0,
        capacity_meta={'nozzle': {'wetting': wetting}},
        cmd_constraints=CmdConstraints(max_on_sec=30.0, min_off_sec=180.0),
    )


def _opening(aid='vent_01'):
    return ActuatorProfile(
        actuator_id=aid,
        kind='opening',
        capabilities=['ventilation', 'cooling_passive'],
        cost_fn=lambda env, pct: 5.0,
        response_sec=60.0,
        safe_default=0.0,
    )


class TestCeilingBlocksWettingFog:

    def test_습도가_넘치면_분무를_0으로_끊는다(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 20.0, 'reason': 1}}
        apply_wetting_fog_humidity_ceiling(
            {'_fog_humidity_block': True}, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 0.0
        assert cmds[fog.actuator_id]['reason'] == 'fog_humidity_ceiling', (
            '왜 안 켜졌는지 근거가 남아야 한다')

    def test_표식이_없으면_손대지_않는다(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 20.0, 'reason': 1}}
        apply_wetting_fog_humidity_ceiling({}, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 20.0

    def test_이미_0이면_근거를_덮어쓰지_않는다(self):
        """다른 이유로 0 인 명령의 근거를 이 게이트가 가로채면 안 된다."""
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 0.0, 'reason': 'nursery_fog_derate'}}
        apply_wetting_fog_humidity_ceiling(
            {'_fog_humidity_block': True}, [fog], cmds)
        assert cmds[fog.actuator_id]['reason'] == 'nursery_fog_derate'


class TestScopeIsWettingFoggersOnly:

    def test_고압_미세포그는_대상이_아니다(self):
        """잎을 적시지 않는 포그는 VPD 제어의 정당한 수단이다."""
        fog = _fogger('fog_hp', wetting=False)
        cmds = {fog.actuator_id: {'value': 20.0, 'reason': 1}}
        apply_wetting_fog_humidity_ceiling(
            {'_fog_humidity_block': True}, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 20.0

    def test_개구부는_대상이_아니다(self):
        """습도가 넘칠 때 창은 오히려 더 열려야 한다."""
        vent = _opening()
        cmds = {vent.actuator_id: {'value': 25.0, 'reason': 1}}
        apply_wetting_fog_humidity_ceiling(
            {'_fog_humidity_block': True}, [vent], cmds)
        assert cmds[vent.actuator_id]['value'] == 25.0


class TestHysteresis:
    """경계에서 켜졌다 꺼졌다 하지 않아야 한다."""

    CEIL = 67.5          # 목표 62.5 + 허용 5.0

    def test_넘으면_잠기고_히스테리시스만큼_내려가야_풀린다(self):
        st = False
        st = latch_threshold(70.0, self.CEIL, RH_HYST_PCT, st, 'max')
        assert st is True
        st = latch_threshold(66.5, self.CEIL, RH_HYST_PCT, st, 'max')
        assert st is True, '해제 문턱(%.1f) 위에서는 유지돼야 한다' % (
            self.CEIL - RH_HYST_PCT)
        st = latch_threshold(64.0, self.CEIL, RH_HYST_PCT, st, 'max')
        assert st is False

    def test_범위_안에서는_처음부터_잠기지_않는다(self):
        assert latch_threshold(63.0, self.CEIL, RH_HYST_PCT, False, 'max') is False


class TestOrdering:
    """순서가 곧 우선순위다 — 헬퍼 한 함수가 그것을 보장한다."""

    def test_일사_감쇠보다_뒤에_온다(self):
        """감쇠는 비율, 상한은 0 으로 끊는 더 강한 규칙이다."""
        import inspect
        src = inspect.getsource(apply_threshold_and_gate_overrides)
        assert (src.index('apply_nursery_fog_derate')
                < src.index('apply_wetting_fog_humidity_ceiling'))

    def test_안전_프리게이트보다_앞에_온다(self):
        """게이트(partial_overrides)는 여전히 최우선이어야 한다."""
        import inspect
        src = inspect.getsource(apply_threshold_and_gate_overrides)
        assert (src.index('apply_wetting_fog_humidity_ceiling')
                < src.index('if partial_overrides:'))


def test_판정은_assess_뒤에서_유효_목표로_한다():
    """정적 `target_humidity` 로 판정하면 실제 쓰인 목표와 어긋난다.

    실측: 함수 옵션은 65.0 인데 `assess` 가 정한 유효 목표는 62.5 였다.
    `_check_hard_constraints` 는 `assess` 보다 앞이라 그 값을 볼 수 없다.
    """
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
    src = inspect.getsource(_cycle_mixin.CycleMixin)
    i_assess = src.index('situation, self._trend_state = assess(')
    i_block = src.index("internal['_fog_humidity_block'] = True")
    assert i_assess < i_block, '판정이 assess 앞으로 올라갔다 — 유효 목표를 못 본다'
    assert 'self.target_humidity' not in src[i_assess:i_block], (
        '정적 설정값으로 판정하고 있다')


class TestVpdDirectControlModeStripsHumidityKey:
    """VPD 직접 제어 중에는 'humidity' 가 없다 — 폴백이 없으면 게이트가 죽는다.

    2026-08-25 실사고: VPD 목표(프로그램)+측정이 둘 다 있으면
    `situation._decompose_vpd` 가 'humidity'/'temperature' 를 제어목표에서
    빼고 `_humidity_constraint`/`_temperature_constraint` 로 이름만 바꾼다
    (TargetVar 는 그대로 — 값을 지우는 게 아니라 **어디서 찾는지**가 바뀐다).

    게이트 코드가 'humidity' 만 보면 VPD 모드가 걸린 뒤로 조용히
    "목표 없음"으로 빠져 **한 번도 서지 않는다.** 실측: 습도 91%(허용오차
    포함 상한 88.42% 초과)에서 분무 67% 가 그대로 디스패치됐다.
    """

    def test_situation_target에서_humidity가_사라진다(self):
        """이 사실 자체를 고정한다 — situation.py 가 계약을 바꾸면 여기서 안다."""
        from aot.functions.utils.env_control.situation import assess
        from aot.functions.utils.env_control.goal import build_env_target

        env_target = build_env_target(
            T_target=23.4, T_tol=1.0, T_pri=0.5,
            RH_target=83.42, RH_tol=5.0, RH_pri=0.5,
            CO2_target=1000.0, CO2_tol=100.0, CO2_pri=0.8,
            VPD_target=0.4772, VPD_tol=0.1, VPD_pri=1.2)
        internal = {'T': 22.6, 'RH': 91.0, 'VPD': 0.225, 'CO2': None}
        external = {'T_ext': 31.22, 'RH_ext': 58.0, 'wind': 0.5}

        situation, _ = assess(
            env_target=env_target, internal=internal, external=external,
            cycle_sec=600.0, now_ts=0, last_ext_ts=None, last_int_ts=None,
            trend_state=None, authority=None, light_sat=None)

        assert 'humidity' not in situation.target, (
            'situation.py 계약이 바뀌었다 — 이 테스트와 _cycle_mixin 의 '
            '폴백 조회를 함께 재검토할 것')
        rh_tv = situation.target.get('_humidity_constraint')
        assert rh_tv is not None
        assert rh_tv.value == pytest.approx(83.42)
        assert rh_tv.tolerance == pytest.approx(5.0)

    def test_run_cycle이_두_키_모두를_조회한다(self):
        """실제 판정 코드가 폴백을 쓰는지 소스로 고정한다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
        src = inspect.getsource(_cycle_mixin.CycleMixin._run_cycle)
        i = src.index("_rh_tv = ")
        window = src[i:i + 200]
        assert "get('humidity')" in window and "get('_humidity_constraint')" in window, (
            "'humidity' 만 보면 VPD 직접 제어 중에는 게이트가 영원히 안 선다")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
