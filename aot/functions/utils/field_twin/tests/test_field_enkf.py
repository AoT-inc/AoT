# coding=utf-8
"""노지 EnKF — 쌍둥이 실험(합성 진실)으로 동기화·파라미터 추정·계단·입력 누락을 본다."""
import numpy as np
import pytest

from aot.functions.utils.field_twin.enkf import FieldEnKF
from aot.functions.utils.field_twin.model import FieldBucketModel
from aot.functions.utils.field_twin.params import FieldPrior, SensorSpec, TEXTURES

# 비 사건: 마른 뒤 큰 비 몇 번(김제 08~10 월과 비슷한 간격)
RAIN = {3: 25.0, 4: 10.0, 18: 40.0, 19: 30.0, 40: 15.0, 52: 20.0}
TRUE_A, TRUE_B = 1.2, -4.0


def _truth(n_days=60, k_bottom=1.0, seed=0):
    """실트질양토·배수 1.5 일 진실을 굴려 2층 센서 관측(잡음 0.8 %p)을 만든다."""
    m = FieldBucketModel(crop='perilla')
    x = m.init_state(prior=FieldPrior(texture='silt_loam', theta0=[0.30, 0.32, 0.33]))
    x[m.idx['tau_drain_d']] = 1.5
    x[m.idx['k_bottom']] = k_bottom
    x[m.idx['kcb_scale']] = 0.8
    rng = np.random.default_rng(seed)
    s = SensorSpec('s', layer=1, a=TRUE_A, b=TRUE_B)
    W, Y = [], []
    for d in range(n_days):
        w = {'rain_mm': RAIN.get(d, 0.0), 'et0_mm': 4.5 - 2.0 * d / n_days, 't_mean': 25.0,
             'dap': 20 + d}
        x = m.step(x, {}, w)
        W.append(w)
        Y.append(float(m.observe(x, s)) + rng.normal(0, 0.8))
    return m, x, W, Y


def _filter(m, seed=1, known_cal=False, **kw):
    if known_cal:
        s = SensorSpec('s', layer=1, a=TRUE_A, b=TRUE_B, r_sd=1.0, estimate_cal=False)
    else:
        s = SensorSpec('s', layer=1, a=1.3, b=0.0, r_sd=1.0)
    return FieldEnKF(m, [s], n_members=96, seed=seed,
                     prior=FieldPrior(texture='loam', theta0=[0.25, 0.25, 0.25]), **kw)


def _run(f, W, Y, start=0, hook=None):
    err = []
    for d, (w, y) in enumerate(zip(W, Y)):
        f.forecast({'irr_mm': float('nan')}, w)
        if d >= start:
            err.append(float(np.median(f.predict_obs(f.sensors[0]))) - y)
        if hook:
            hook(d, f)
        f.update({'s': y})
    return np.array(err)


def test_twin_experiment_tracks_and_learns_soil():
    """보정을 알면(현장 시료) θfc 를 진실 ±0.02 로 찾는다 — 사전(양토 0.25)에서 0.29 로."""
    fc_true = TEXTURES['silt_loam'].theta_fc
    for seed in (0, 1):
        m, _, W, Y = _truth(seed=seed)
        f = _filter(FieldBucketModel(crop='perilla'), seed=seed + 1, known_cal=True)
        err = _run(f, W, Y, start=10)
        assert np.sqrt(np.mean(err ** 2)) < 2.0
        assert abs(f.mean()['theta_fc'] - fc_true) < 0.02
        assert not any(i.shift for i in f.log)


def test_without_calibration_only_the_reading_at_field_capacity_is_identified():
    """보정 a·b 를 함께 추정하면 θfc 자체는 b 와 섞인다. 식별되는 것은 '포장용수량에서
    센서가 읽는 값' a·100·θfc + b 다(계획서 §9.5 — 토성 숫자에는 현장 시료가 필요)."""
    y_fc_true = TRUE_A * 100 * TEXTURES['silt_loam'].theta_fc + TRUE_B
    for seed in (0, 1):
        m, _, W, Y = _truth(seed=seed)
        f = _filter(FieldBucketModel(crop='perilla'), seed=seed + 1)
        err = _run(f, W, Y, start=10)
        assert np.sqrt(np.mean(err ** 2)) < 2.0
        mm = f.mean()
        y_fc = mm['cal_a:s'] * 100 * mm['theta_fc'] + mm['cal_b:s']
        assert abs(y_fc - y_fc_true) < 4.0


def test_ensemble_spread_gives_reasonable_coverage():
    m, _, W, Y = _truth(seed=3)
    f = _filter(FieldBucketModel(crop='perilla'), seed=4)
    inside = []
    for d, (w, y) in enumerate(zip(W, Y)):
        f.forecast({}, w)
        lo, hi = np.quantile(f.predict_obs(f.sensors[0]), [0.1, 0.9])
        if d >= 10:
            inside.append(lo <= y <= hi)
        f.update({'s': y})
    assert 0.5 <= np.mean(inside) <= 1.0


def test_sensor_step_without_rain_is_absorbed_by_calibration():
    """비 없는 날 관측이 −10 %p 계단으로 떨어지면 b 를 다시 열어 흡수하고 곧 다시 맞춘다."""
    m, _, W, Y = _truth()
    Y2 = [y - (10.0 if d >= 30 else 0.0) for d, y in enumerate(Y)]
    f = _filter(FieldBucketModel(crop='perilla'))
    b_before = {}
    err = _run(f, W, Y2, hook=lambda d, f: b_before.setdefault(d, f.mean()['cal_b:s']))
    shifts = [i for i in f.log if i.shift]
    assert len(shifts) >= 1
    assert np.sqrt(np.mean(err[34:40] ** 2)) < 2.5
    # 계단의 대부분(10 중 6 이상)이 토양 물이 아니라 보정 b 로 갔다
    assert b_before[30] - b_before[33] > 6.0


def test_reopen_calibration_widens_only_the_offset_spread():
    m = FieldBucketModel(crop='perilla')
    f = _filter(m)
    ib = f.names.index('cal_b:s')
    j = f.names.index('theta_fc')
    sd_b, sd_fc = f.X[:, ib].std(), f.X[:, j].std()
    f.X[:, ib] = f.X[:, ib].mean()
    f.reopen_calibration('s', b_only=True)
    assert f.X[:, ib].std() > 2.0 and f.X[:, j].std() == pytest.approx(sd_fc)


def test_unexplained_wetting_opens_the_water_state():
    """관측소가 놓친 비: 입력에 비가 없는데 관측이 크게 오르면 보정이 아니라 수분을 연다."""
    m, _, W, Y = _truth()
    W2 = [dict(w, rain_mm=0.0) if d in (18, 19) else w for d, w in enumerate(W)]
    f = _filter(FieldBucketModel(crop='perilla'), shift_gate_sigma=3.0)
    _run(f, W2, Y)
    assert any(i.wetting for i in f.log)
    assert not any(i.shift for i in f.log if i.innovation > 0)


def test_run_ahead_leaves_the_filter_untouched():
    m, _, W, Y = _truth(n_days=10)
    f = _filter(FieldBucketModel(crop='perilla'))
    _run(f, W, Y)
    X0 = f.X.copy()
    traj = f.run_ahead([{'rain_mm': 0.0, 'et0_mm': 5.0, 'dap': 30 + k} for k in range(7)])
    assert traj.shape == (f.n_members, 7, f.model.n)
    assert np.array_equal(f.X, X0)
    r = f.model.risks(traj, dap0=30)
    assert np.all((r['p_water_short'] >= 0) & (r['p_water_short'] <= 1))


def test_quantiles_are_ordered():
    m, _, W, Y = _truth(n_days=5)
    f = _filter(FieldBucketModel(crop='perilla'))
    _run(f, W, Y)
    q = f.quantiles('theta2')
    assert q[0] <= q[1] <= q[2]
    q = f.obs_quantiles('s')
    assert q[0] <= q[1] <= q[2]
