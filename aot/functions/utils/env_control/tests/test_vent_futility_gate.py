# coding=utf-8
"""
test_vent_futility_gate.py — 환기 무익 게이트 (사용자 옵션 vent_futility_gate).

환기는 실내를 **실외 쪽으로**밖에 못 민다. 목표가 실외의 반대편에 있으면 아무리
열어도 목표에 가까워지지 않는다 — 야간 제습이 대표적이다(실외 노점이 더 높으면
창을 열수록 더 습해진다). 기존 G_MIN_EFFECT 게이트는 '구동력 크기'만 보므로
방향이 반대인 대형 천창을 못 걸러냈다(2026-08-06 aot-005: 밤새 근거코드가 전부
PRIMARY, 창이 40~70% 열린 채 유지).

데드존 연속화(같은 날 수정)로 평형 유지가 강해진 만큼 이 게이트가 더 필요해졌다.
게이트가 없으면 무익한 개도가 '흔들리지 않고 그대로' 밤새 유지된다.
"""

from aot.functions.utils.env_control.coordinator import (
    REASON_NO_GRADIENT,
    REASON_PRIMARY,
    VENTILATING_KINDS,
    CoordinatorState,
    _outdoor_reachable,
    coordinate,
)
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import TargetVar

from .conftest import make_ctx, make_heater_profile, make_opening_profile

# 실측 야간 조건 (2026-08-06 04시 aot-005 고추 육묘장)
NIGHT = dict(T_int=22.8, RH_int=86.0, T_ext=21.0, RH_ext=95.0)   # 실내 0.39 / 실외 0.12
VPD_TARGET = 0.46      # 목표는 실내보다 위 → 제습(=VPD 상승) 필요
VPD_TOL = 0.1


def _vent(actuator_id='v1'):
    p = make_opening_profile(actuator_id)
    p.effect_model = build_effect_model('opening', {})   # 유도 VPD effect 포함
    return p


def _cycle(profile, state, gate, target_vpd=VPD_TARGET, **env):
    """단일 사이클 실행 → ActuatorCommand."""
    conds = dict(NIGHT)
    conds.update(env)
    vpd_int = compute_vpd(conds['T_int'], conds['RH_int'])
    target = {'vpd': TargetVar(value=target_vpd, tolerance=VPD_TOL,
                               priority=1.2, unit='kPa')}
    ctx = make_ctx(VPD_int=vpd_int, **conds)
    report, _ = assess(target,
                       dict(ctx['internal'], VPD=vpd_int), ctx['external'],
                       cycle_sec=600.0, now_ts=ctx['now_ts'])
    report.context['vent_futility_gate'] = gate
    cmds, state = coordinate(report, [profile], state)
    return cmds[profile.actuator_id], state, report


def _state(start=55.0, aid='v1'):
    st = CoordinatorState()
    st.integral[aid] = start
    st.prev_commands[aid] = start
    return st


class TestGateFires:
    def test_parks_when_outdoor_is_on_the_wrong_side(self):
        """실외 VPD 가 목표 반대쪽이면 무익 판정 → 닫는 방향."""
        cmd, _st, _r = _cycle(_vent(), _state(), gate=True)
        assert cmd.reason == REASON_NO_GRADIENT
        assert cmd.aperture < 55.0, '무익 판정인데 개도가 안 줄었다'

    def test_converges_to_closed_without_chatter(self):
        """여러 사이클에 걸쳐 safe_default(닫힘)로 수렴하고 다시 열리지 않는다."""
        p, st = _vent(), _state()
        traj = []
        for _ in range(20):
            cmd, st, _r = _cycle(p, st, gate=True)
            st.prev_commands['v1'] = cmd.aperture
            traj.append(cmd.aperture)
        assert traj[-1] == 0.0, f'닫힘으로 수렴 실패: {traj[-5:]}'
        # 단조 감소 — 파킹 도중 다시 열리는 채터링이 없어야 한다
        assert all(b <= a + 1e-9 for a, b in zip(traj, traj[1:])), \
            f'파킹 중 재개방(채터링): {traj}'

    def test_option_off_keeps_previous_behaviour(self):
        """옵션을 끄면 같은 조건에서 게이트가 발동하지 않는다."""
        cmd, _st, _r = _cycle(_vent(), _state(), gate=False)
        assert cmd.reason == REASON_PRIMARY
        assert cmd.aperture > 40.0, '게이트 OFF 인데 파킹됐다'

    def test_gate_is_why_the_vent_does_not_stay_half_open(self):
        """게이트가 없으면 무익한 개도가 그대로 유지된다 — 게이트의 존재 이유.

        데드존 연속화 이후 평형 유지가 강해져, 게이트 없이는 밤새 반쯤 열린
        상태가 흔들림 없이 고정된다. 두 경로의 차이를 한 테스트에 고정한다.
        """
        p_off, st_off = _vent('off'), _state(aid='off')
        p_on, st_on = _vent('on'), _state(aid='on')
        for _ in range(10):
            c_off, st_off, _ = _cycle(p_off, st_off, gate=False)
            st_off.prev_commands['off'] = c_off.aperture
            c_on, st_on, _ = _cycle(p_on, st_on, gate=True)
            st_on.prev_commands['on'] = c_on.aperture
        assert c_off.aperture > 40.0, '게이트 OFF 인데 저절로 닫혔다'
        assert c_on.aperture < 5.0, '게이트 ON 인데 안 닫혔다'


class TestGateDoesNotFire:
    def test_outdoor_on_the_target_side_keeps_controlling(self):
        """실외가 목표 쪽(더 건조)이면 환기가 유효 → 게이트 미발동."""
        cmd, _st, _r = _cycle(_vent(), _state(), gate=True,
                              T_ext=18.0, RH_ext=60.0)   # 실외 VPD 0.83 > 목표
        assert cmd.reason == REASON_PRIMARY
        assert cmd.aperture > 40.0

    def test_neutral_deviation_holds_instead_of_parking(self):
        """편차가 데드존 안(중립)이면 게이트가 개입하지 않는다.

        지금 열려 있는 덕분에 목표를 맞추고 있는 경우까지 닫아 버리면 진동이
        생긴다. 판단 근거가 될 만큼 벗어난 변수가 없으면 평상시 hold 가 맞다.
        """
        vpd_now = compute_vpd(NIGHT['T_int'], NIGHT['RH_int'])
        cmd, _st, _r = _cycle(_vent(), _state(), gate=True, target_vpd=vpd_now)
        assert cmd.reason == REASON_PRIMARY
        assert cmd.aperture == 55.0, '중립인데 평형 개도가 흔들렸다'

    def test_unknown_variable_is_not_judged(self):
        """실외 대응값을 모르는 변수로는 무익 판정을 하지 않는다(보수적 미발동).

        assess() 가 T_ext/RH_ext 에 기본값을 채우므로 실서비스에서 결측은
        드물지만, 새 제어변수가 추가됐을 때 '모르니까 닫는다'가 되면 안 된다.
        """
        assert _outdoor_reachable('temperature', {'T_ext': 21.0}) == 21.0
        assert _outdoor_reachable('vpd', {'T_ext': 21.0, 'RH_ext': 95.0}) is not None
        assert _outdoor_reachable('vpd', {'T_ext': None, 'RH_ext': 95.0}) is None
        assert _outdoor_reachable('soil_moisture', {'T_ext': 21.0}) is None

    def test_scope_is_air_exchanging_kinds_only(self):
        """게이트 대상은 외기와 공기를 바꾸는 종류뿐이다.

        히터·커튼·분무기는 실외 상태와 무관하게 자기 효과를 내므로 '실외 도달성'
        논리가 성립하지 않는다. 대상 목록에 이런 종류가 섞이면 안 된다.
        """
        assert VENTILATING_KINDS == {'opening', 'exhaust_fan', 'intake_fan'}
        assert make_heater_profile('h1').kind not in VENTILATING_KINDS
        # 순환팬은 실내 공기만 섞으므로 대상 아님
        assert 'circulation_fan' not in VENTILATING_KINDS
