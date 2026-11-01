# coding=utf-8
"""시설 트윈 모델·필터·동기화 시험. 참값은 같은 모델에 다른 파라미터를 준 '쌍둥이 실험'이다 —
구조 오차가 있는 독립 참값 검증은 plans/twin_fac/validate_plant.py (sim/plant.py)."""
import math

import numpy as np
import pytest

from aot.functions.utils.env_control.greybox import model as gb
from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.facility_twin import FacilityConfig, FacilityTwinModel, FacilityUKF
from aot.functions.utils.facility_twin.model import I_AH, I_LLK, I_LSOL, I_LTR, I_LUA, I_LVENT, I_T, I_TM
from aot.functions.utils.facility_twin.sync import assimilate

GP = GreyboxParams(UA_eff=3000.0, tau_T=700.0, m_vent_coef=20.0, volume_m3=1100.0, alpha_sol=150.0,
                   Q_heat=30000.0, k_transp=2e-3)
EXT = {"T_ext": 8.0, "RH_ext": 70.0, "CO2_ext": 420.0, "solar": 300.0, "wind": 1.5}
CM = {"heat": 0.0, "cool": 0.0, "vent": 30.0, "fog": 0.0, "co2_inj": 0.0, "shade": 100.0, "curtain": 100.0}


def test_reduces_to_greybox_without_extras():
    """누기 0 · 열질량 결합 0 · 배율 1 이면 그레이박스 `step` 과 같은 식이다(원칙 3: 모델은 한 벌).
    (결합이 있으면 Tm 이 T 를 따라오지 못하는 동안 다르다 — 그게 Tm 을 넣은 이유다.)"""
    m = FacilityTwinModel(GP, FacilityConfig(leak_ach=0.0, mass_coupling_ratio=0.0))
    z = m.init_state(22.0, 65.0, 450.0)
    for _ in range(10):
        z = m.propagate(z, EXT, CM, 60.0)
    T, RH, C = 22.0, 65.0, 450.0
    for _ in range(10):
        T, RH, C = gb.step(T, RH, C, EXT, CM, GP, 60.0)
    o = m.observe(z)
    assert o[0] == pytest.approx(T, abs=0.02)
    assert o[1] == pytest.approx(RH, abs=0.3)
    assert o[2] == pytest.approx(C, abs=1.0)


def test_thermal_mass_pulls_air_toward_itself():
    m = FacilityTwinModel(GP)
    cold = m.init_state(15.0, 60.0, 420.0, Tm=15.0)
    warm = m.init_state(15.0, 60.0, 420.0, Tm=25.0)
    e = dict(EXT, solar=0.0, T_ext=15.0)
    c = dict(CM, vent=0.0)
    a = m.propagate(cold, e, c, 600.0)
    b = m.propagate(warm, e, c, 600.0)
    assert b[I_T] > a[I_T] + 0.2          # 따뜻한 열질량이 공기를 데운다
    assert b[I_TM] < warm[I_TM]           # 그 몫만큼 열질량은 식는다


def test_slow_parameters_move_the_right_way():
    m = FacilityTwinModel(GP)
    base = m.init_state(20.0, 60.0, 420.0)
    e = dict(EXT, T_ext=0.0, solar=0.0)
    hi = base.copy(); hi[I_LUA] = math.log(2.0)
    assert m.propagate(hi, e, CM, 300.0)[I_T] < m.propagate(base, e, CM, 300.0)[I_T]       # 열손실 배율↑ → 더 식음
    leaky = base.copy(); leaky[I_LLK] = math.log(3.0)
    assert m.propagate(leaky, e, CM, 300.0)[I_T] < m.propagate(base, e, CM, 300.0)[I_T]
    sun = dict(EXT, solar=700.0)
    more = base.copy(); more[I_LSOL] = math.log(2.0)
    assert m.propagate(more, sun, CM, 300.0)[I_T] > m.propagate(base, sun, CM, 300.0)[I_T]
    ve = base.copy(); ve[I_LVENT] = math.log(2.0)
    assert m.propagate(ve, e, CM, 300.0)[I_T] < m.propagate(base, e, CM, 300.0)[I_T]
    tr = base.copy(); tr[I_LTR] = math.log(5.0)
    assert m.propagate(tr, sun, dict(CM, vent=0.0), 600.0)[I_AH] > m.propagate(base, sun, dict(CM, vent=0.0), 600.0)[I_AH]


def test_propagate_does_not_mutate_input_and_stays_physical():
    m = FacilityTwinModel(GP)
    z = m.init_state(20.0, 95.0, 420.0)
    z0 = z.copy()
    for _ in range(50):
        z = m.propagate(z, dict(EXT, T_ext=-5.0, RH_ext=100.0), dict(CM, vent=100.0), 300.0)
    assert np.allclose(m.init_state(20.0, 95.0, 420.0), z0)
    o = m.observe(z)
    assert -15 <= o[0] <= 55 and 0 <= o[1] <= 100 and 250 <= o[2] <= 5000


def _twin_truth(hours, rng, theta=(1.4, 1.0, 1.0, 1.0, 1.0), dt=300.0):
    """쌍둥이 실험: 같은 모델에 다른 UA 를 주고 되먹임 비슷한 명령으로 돌린 참값 + 잡음 섞은 측정."""
    m = FacilityTwinModel(GP)
    z = m.init_state(18.0, 70.0, 420.0)
    z[I_LUA] = math.log(theta[0])
    t0 = 1.7e9
    obs = {"T": ([], []), "RH": ([], []), "CO2": ([], [])}
    ext = {k: ([], []) for k in ("T_ext", "RH_ext", "solar", "wind")}
    cmd = {"vent": ([], []), "heat": ([], [])}
    for i in range(int(hours * 3600 / dt)):
        t = t0 + i * dt
        hr = (t / 3600.0) % 24
        e = {"T_ext": 8.0 + 6.0 * math.sin((hr - 9) / 24 * 2 * math.pi), "RH_ext": 70.0,
             "solar": max(0.0, 600.0 * math.sin((hr - 6) / 12 * math.pi)), "wind": 1.5, "CO2_ext": 420.0}
        c = dict(CM, vent=float(np.clip((z[I_T] - 22.0) * 15.0, 0, 100)), heat=float(np.clip((14.0 - z[I_T]) * 30.0, 0, 100)))
        for k in ext:
            ext[k][0].append(t); ext[k][1].append(e[k])
        for k in cmd:
            cmd[k][0].append(t); cmd[k][1].append(c[k])
        z = m.propagate(z, e, c, dt)
        o = m.observe(z)
        for k, v, sd in (("T", o[0], 0.1), ("RH", o[1], 1.0), ("CO2", o[2], 10.0)):
            obs[k][0].append(t + dt); obs[k][1].append(v + rng.normal(0, sd))
    return t0, t0 + hours * 3600, obs, ext, cmd


def test_ukf_learns_envelope_loss_and_predicts():
    rng = np.random.default_rng(3)
    t0, t1, obs, ext, cmd = _twin_truth(30, rng, theta=(1.5, 1, 1, 1, 1))
    m = FacilityTwinModel(GP)                        # 사전값은 UA 가 1.0 배 — 참값은 1.5 배
    ukf = FacilityUKF(m, obs_sd={"T": 0.15, "RH": 1.5, "CO2": 15.0})
    res = assimilate(m, ukf, t0, t1, obs, ext, cmd, dt_s=300.0, lead_s=(3600.0,), lead_skip_s=8 * 3600.0)
    assert res is not None and res.n_obs > 300
    assert res.rmse_1step("T") < 0.5
    assert math.exp(ukf.z[I_LUA]) > 1.2             # 사전(1.0)보다 참값(1.5) 쪽으로 학습
    assert res.n_lead(3600.0, "T", "actual") >= 6
    assert res.rmse_lead(3600.0, "T", "actual") < 1.0
    assert res.rmse_lead(3600.0, "RH", "actual") < 7.0


def test_outlier_is_gated_but_persistent_shift_is_accepted():
    m = FacilityTwinModel(GP)
    ukf = FacilityUKF(m, gate_max_run=3)
    ukf.init(20.0, 60.0, 420.0)
    for _ in range(20):
        ukf.predict(120.0, EXT, CM)
        ukf.update({"T": 20.0, "RH": 60.0, "CO2": 420.0})
    z_before = ukf.z.copy()
    ukf.predict(120.0, EXT, CM)
    out = ukf.update({"T": 45.0})                    # 한 번 튀는 값 — 버린다
    assert out.get("gated") == 1.0 and abs(ukf.z[I_T] - z_before[I_T]) < 1.0
    for _ in range(8):                               # 계속 45 면 센서가 맞다고 받아들인다(문이 열린 채 등)
        ukf.predict(120.0, EXT, CM)
        ukf.update({"T": 45.0})
    assert ukf.z[I_T] > 30.0


def test_sample_first_member_is_the_mean_and_covariance_is_psd():
    m = FacilityTwinModel(GP)
    ukf = FacilityUKF(m)
    ukf.init(20.0, 60.0, 420.0)
    for _ in range(5):
        ukf.predict(120.0, EXT, CM)
        ukf.update({"T": 19.0, "RH": 62.0, "CO2": 430.0})
    s = ukf.sample(6, np.random.default_rng(1))
    assert np.allclose(s[0], ukf.z)
    assert np.linalg.eigvalsh((ukf.P + ukf.P.T) / 2).min() > -1e-8


def test_assimilate_needs_observations():
    m = FacilityTwinModel(GP)
    assert assimilate(m, FacilityUKF(m), 0.0, 3600.0, {}, {}, {}) is None


def test_vent_scale_can_go_below_one_third():
    """그레이박스 환기 계수는 독립 참값보다 3 배쯤 크게 나온다 — 옛 한계(1/3)에 붙으면 습도·고온 선행이 무너졌다."""
    from aot.functions.utils.facility_twin.model import LN_BOUND
    m = FacilityTwinModel(GP)
    ukf = FacilityUKF(m)
    ukf.init(20.0, 60.0, 420.0)
    ukf.z[I_LVENT] = math.log(0.2)
    assert ukf._clip(ukf.z)[I_LVENT] == pytest.approx(math.log(0.2))
    ukf.z[I_LVENT] = -10.0
    assert ukf._clip(ukf.z)[I_LVENT] == pytest.approx(-LN_BOUND)
