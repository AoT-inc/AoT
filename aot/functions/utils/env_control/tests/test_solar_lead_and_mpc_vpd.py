# coding=utf-8
"""일사 선행 예측(그림자) · MPC 의 VPD 항과 온·습도 범위 벌점(결정 D3)."""
import math

import pytest

from aot.functions.utils.env_control.solar_lead import G_PRIOR, SolarLead
from aot.functions.utils.env_control.greybox import mpc
from aot.functions.utils.env_control.greybox.params import GreyboxParams


# ── 일사 선행 예측 ───────────────────────────────────────────────────────────

def _drive(sl, gain, n=600, dt=600.0, lag_steps=2):
    """일사 계단이 lag 뒤 온도에 gain 으로 나타나는 합성 기록(+ 일사와 무관한 흔들림)."""
    S_hist, T = [], 20.0
    rep = None
    for i in range(n):
        S = 600.0 if (i // 9) % 2 else 200.0           # 90분마다 구름
        S_hist.append(S)
        noise = 0.3 * math.sin(i * 1.7)                 # 일사와 무관한 변동
        if len(S_hist) > lag_steps:
            T = 20.0 + gain * (S_hist[-1 - lag_steps] - 400.0) + noise
        rep = sl.step(i * dt, S, T, dt)
    return rep


def test_it_learns_the_gain_and_beats_no_change():
    rep = _drive(SolarLead(), gain=0.004)
    assert rep['g_per_100W'] > 0.2
    assert rep['skill'] is not None and rep['skill'] > 0.2


def test_no_relation_means_no_skill():
    rep = _drive(SolarLead(), gain=0.0)
    assert rep['skill'] is not None and rep['skill'] <= 0.0


def test_unknown_solar_does_nothing():
    sl = SolarLead()
    assert sl.step(0.0, None, 20.0, 600.0) is None
    assert sl.S_f is None


def test_night_is_not_scored():
    sl = SolarLead()
    for i in range(200):
        sl.step(i * 600.0, 0.0, 15.0 + 0.1 * (i % 3), 600.0)
    assert sl.n == 0


def test_prior_before_learning():
    assert SolarLead().g == pytest.approx(G_PRIOR)


# ── MPC: VPD 항과 범위 벌점 ─────────────────────────────────────────────────

P = GreyboxParams(volume_m3=1000.0, UA_eff=300.0, tau_T=4000.0, m_vent_coef=3.0,
                  Q_heat=20000.0, Q_cool=0.0, alpha_sol=0.0, k_transp=2e-4,
                  k_photo=0.0, Q_plant_base=0.0)


class _Prof:
    def __init__(self, kind):
        self.kind = kind


def _opt(targets, soft=None, T=22.0, RH=90.0, ext=None, kinds=('heater', 'opening')):
    ext = ext or {'T_ext': 12.0, 'RH_ext': 80.0, 'CO2_ext': 400.0, 'solar': 0.0, 'wind': 1.0}
    return mpc.optimize_channels(
        state=(T, RH, 400.0), targets=targets,
        profiles=[_Prof(k) for k in kinds], ext_seq=[ext] * 10,
        params=P, prev_channel_cmds={}, cycle_sec=600.0, soft_bounds=soft)


def test_vpd_target_alone_is_now_something_to_do():
    """VPD 방식에서도 MPC 가 목표를 받는다(예전엔 noop)."""
    r = _opt({'vpd': (0.8, 0.1, 1.2)})
    assert r.method != 'noop' and r.end_state is not None
    T, RH, _ = r.end_state
    assert mpc._vpd(T, RH) > mpc._vpd(22.0, 90.0), '습한 밤에 VPD 를 올린다'


def test_temperature_bound_keeps_vpd_from_using_extreme_heat():
    """난방만 있는 시설: 범위 벌점이 없으면 VPD 를 난방으로 밀어 온도가 치솟는다 —
    있으면 범위 근처에서 멈춘다."""
    free = _opt({'vpd': (1.5, 0.1, 1.2)}, kinds=('heater',))
    bound = _opt({'vpd': (1.5, 0.1, 1.2)}, soft={'temperature': (18.0, 26.0)},
                 kinds=('heater',))
    assert free.end_state[0] > 27.0
    assert bound.end_state[0] < free.end_state[0] - 1.0
    assert bound.end_state[0] <= 27.0


def test_mpc_may_choose_ventilation_over_heat_for_vpd():
    """습한 밤·건조한 외기: VPD 를 올리는 데 환기를 섞어 쓸 수 있다(난방만 고집하지 않는다)."""
    r = _opt({'vpd': (1.5, 0.1, 1.2)}, soft={'temperature': (18.0, 26.0)})
    assert r.channel_cmds['vent'] > 0.0


# ── C 단계: 에너지 단가 · 난방/냉방 동시 · 마모 ───────────────────────────────

HOT = {'T_ext': 22.0, 'RH_ext': 50.0, 'CO2_ext': 400.0, 'solar': 600.0, 'wind': 1.0}
P2 = GreyboxParams(volume_m3=1000.0, UA_eff=300.0, tau_T=4000.0, m_vent_coef=2.0,
                   Q_heat=20000.0, Q_cool=20000.0, alpha_sol=40.0, k_transp=0.0,
                   k_photo=0.0, Q_plant_base=0.0)


def _cool(kw=None, prev=None, move=None, T=30.0):
    return mpc.optimize_channels(
        state=(T, 60.0, 400.0), targets={'temperature': (24.0, 1.0, 1.2)},
        profiles=[_Prof('cooler'), _Prof('opening'), _Prof('heater')], ext_seq=[HOT] * 10,
        params=P2, prev_channel_cmds=prev or {}, cycle_sec=600.0,
        channel_kw=kw, prev_move=move)


def test_expensive_cooling_yields_to_cheap_ventilation():
    """실외가 더 시원하면, 냉방이 비쌀수록 환기를 더 쓰고 냉방을 덜 쓴다."""
    cheap = _cool(kw={'cool': 0.1, 'vent': 0.1, 'heat': 5.0})
    dear = _cool(kw={'cool': 20.0, 'vent': 0.1, 'heat': 5.0})
    assert dear.channel_cmds['cool'] < cheap.channel_cmds['cool']


def test_heating_and_cooling_are_not_used_together():
    r = _cool(kw={'cool': 2.5, 'vent': 0.1, 'heat': 5.0}, T=24.0)
    assert min(r.channel_cmds['heat'], r.channel_cmds['cool']) < 5.0


def test_reversal_is_penalised():
    """창을 방금 열었으면(직전 움직임 +), 조금 닫고 싶어도 되돌리기를 망설인다."""
    base = dict(state=(24.6, 60.0, 400.0), targets={'temperature': (24.0, 1.0, 1.2)},
                profiles=[_Prof('opening')], ext_seq=[dict(HOT, solar=0.0, T_ext=23.0)] * 10,
                params=P2, prev_channel_cmds={'vent': 60.0}, cycle_sec=600.0)
    free = mpc.optimize_channels(**base)
    held = mpc.optimize_channels(**base, prev_move={'vent': -30.0})   # 방금 닫고 있었다
    again = mpc.optimize_channels(**base, prev_move={'vent': +30.0})  # 방금 열고 있었다
    assert free.channel_cmds['vent'] >= 0.0
    # 방금 연 창을 반대로(닫는 쪽) 움직이는 양은 방금 닫던 경우보다 작다
    assert (60.0 - again.channel_cmds['vent']) <= (60.0 - held.channel_cmds['vent']) + 1e-6


def test_actuator_kw_prefers_electric_draw():
    from aot.functions.utils.env_control.energy import actuator_kw, electric_kw
    assert electric_kw(10.0, 220.0) == pytest.approx(2.2)
    assert actuator_kw('heater', {'elec_kw': 0.4, 'rated_kW_thermal': 20.0}) == 0.4
    assert actuator_kw('heater', {'rated_kW_thermal': 20.0}) == 20.0
    assert actuator_kw('heater', {}) == 5.0
