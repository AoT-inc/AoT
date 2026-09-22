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
