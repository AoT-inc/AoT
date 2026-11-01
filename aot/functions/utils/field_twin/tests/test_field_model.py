# coding=utf-8
"""노지 물 수지 모델 — 보존, 극한, 계약 인터페이스."""
import math

import numpy as np
import pytest

from aot.functions.utils.field_twin.model import FieldBucketModel, PARAM_NAMES, STATE_NAMES
from aot.functions.utils.field_twin.params import (CROPS, FieldPrior, SensorSpec, TEXTURES,
                                                    nearest_texture)


def _model(**kw):
    return FieldBucketModel(crop=kw.pop('crop', 'perilla'), **kw)


def _x(m, theta=(0.25, 0.25, 0.25), **params):
    x = m.init_state(prior=FieldPrior(texture='loam', theta0=list(theta)))
    for k, v in params.items():
        x[m.idx[k]] = v
    return x


def _balance(m, x0, x1, f):
    ds = float(np.sum(m.storage_mm(x1) - m.storage_mm(x0)))
    flows = float(np.sum(f['rain'] + f['irr'] - f['runoff'] - f['evap'] - f['transp'] - f['drain']))
    return ds, flows


def test_interface_matches_contract():
    """계약 §10.7: kind·state_names·param_names·dt_nominal_s 와 step/observe/derived/risks."""
    m = _model()
    assert m.kind == 'field'
    assert tuple(m.state_names) == STATE_NAMES and tuple(m.param_names) == PARAM_NAMES
    assert m.dt_nominal_s == 86400.0
    x = m.init_state()
    assert x.shape == (len(STATE_NAMES) + len(PARAM_NAMES),)
    for fn in ('step', 'observe', 'derived', 'risks', 'init_state'):
        assert callable(getattr(m, fn))


@pytest.mark.parametrize('rain,irr,et0,dt', [
    (0.0, 0.0, 5.0, 86400.0), (30.0, 0.0, 4.0, 86400.0), (120.0, 0.0, 2.0, 86400.0),
    (0.0, 15.0, 6.0, 86400.0), (8.0, 0.0, 0.2, 3600.0),
])
def test_water_is_conserved(rain, irr, et0, dt):
    """저수량 변화 = 비 + 관수 − 유출 − 증발 − 증산 − 심부 배수 (1e-9 mm)."""
    m = _model()
    x0 = _x(m, (0.18, 0.30, 0.40))
    x1, f = m.step_fluxes(x0, {'irr_mm': irr}, {'rain_mm': rain, 'et0_mm': et0, 'dap': 40}, dt)
    ds, flows = _balance(m, x0, x1, f)
    assert ds == pytest.approx(flows, abs=1e-9)


def test_ensemble_step_equals_member_steps():
    """앙상블 (N, n) 을 한 번에 굴린 결과가 멤버마다 굴린 것과 같다."""
    m = _model()
    X = m.init_state(prior=FieldPrior(texture='loam'), n=8, rng=np.random.default_rng(1))
    w = {'rain_mm': 12.0, 'et0_mm': 4.0, 't_mean': 24.0, 'dap': 30}
    Y = m.step(X, {}, w)
    for i in range(8):
        assert np.allclose(Y[i], m.step(X[i], {}, w))


def test_free_drainage_stops_at_field_capacity():
    """증발산이 없으면 포장용수량 위 물만 빠지고 그 아래로는 내려가지 않는다."""
    m = _model(crop='bare')
    x = _x(m, (0.40, 0.40, 0.40), tau_drain_d=1.0, k_bottom=1.0)
    fc = x[m.idx['theta_fc']]
    for _ in range(30):
        x = m.step(x, {}, {'rain_mm': 0.0, 'et0_mm': 0.0})
    for k in (1, 2, 3):
        assert x[m.idx['theta%d' % k]] == pytest.approx(fc, abs=0.01)
        assert x[m.idx['theta%d' % k]] >= fc - 1e-9


def test_blocked_bottom_keeps_profile_wet():
    """k_bottom = 0 (경반층·높은 지하수위)이면 심부 배수가 없고 아래층부터 찬다."""
    m = _model(crop='bare')
    x = _x(m, (0.25, 0.25, 0.25), k_bottom=0.0, tau_drain_d=0.5)
    x, f = m.step_fluxes(x, {}, {'rain_mm': 80.0, 'et0_mm': 0.0})
    for _ in range(10):
        x, f2 = m.step_fluxes(x, {}, {'rain_mm': 0.0, 'et0_mm': 0.0})
        assert float(f2['drain']) == 0.0
    assert x[m.idx['theta3']] > x[m.idx['theta_fc']] + 0.05


def test_small_rain_on_dry_soil_wets_the_top_first():
    """마른 땅에 온 작은 비는 1층을 먼저 적시고 2층에는 거의 닿지 않는다(김제 10-13)."""
    m = _model(crop='bare')
    x0 = _x(m, (0.10, 0.12, 0.15))
    x1 = m.step(x0, {}, {'rain_mm': 15.0, 'et0_mm': 0.0})
    d1 = x1[m.idx['theta1']] - x0[m.idx['theta1']]
    d2 = x1[m.idx['theta2']] - x0[m.idx['theta2']]
    assert d1 > 0.10 and d2 < 0.01


def test_unknown_irrigation_is_left_out():
    """관수 NaN(모름)은 0 과 같다 — 계약 §10.7, 메타가 irrigation_known=0 을 남긴다."""
    m = _model()
    x = _x(m)
    w = {'rain_mm': 3.0, 'et0_mm': 4.0, 'dap': 20}
    assert np.allclose(m.step(x, {'irr_mm': float('nan')}, w), m.step(x, {}, w))
    assert np.allclose(m.step(x, {'irr_mm': None}, w), m.step(x, {'irr_mm': 0.0}, w))


def test_soil_never_dries_past_physical_limits():
    """긴 가뭄: 1층은 기건(0.5 θwp) 아래로, 뿌리층은 위조점 아래로 마르지 않는다."""
    m = _model()
    x = _x(m)
    wp = x[m.idx['theta_wp']]
    for d in range(120):
        x = m.step(x, {}, {'rain_mm': 0.0, 'et0_mm': 7.0, 'dap': 50})
    assert x[m.idx['theta1']] >= 0.5 * wp - 1e-9
    assert x[m.idx['theta2']] >= wp - 1e-9 and x[m.idx['theta3']] >= wp - 1e-9
    assert float(m.derived(x, dap=50)['Ks']) < 0.05


def test_ks_is_one_at_field_capacity_and_falls_after_raw():
    m = _model()
    x = _x(m)
    fc = x[m.idx['theta_fc']]
    for k in (1, 2, 3):
        x[m.idx['theta%d' % k]] = fc
    d = m.derived(x, dap=60)
    assert float(d['Ks']) == 1.0 and float(d['Dr_mm']) == 0.0
    wp = x[m.idx['theta_wp']]
    for k in (1, 2, 3):
        x[m.idx['theta%d' % k]] = wp + 0.2 * (fc - wp)
    d = m.derived(x, dap=60)
    assert float(d['Dr_mm']) > float(d['RAW_mm']) and float(d['Ks']) < 1.0


def test_transpiration_follows_the_crop_curve():
    """같은 물·같은 ET0 에서 중기(Kcb 1.05) 증산이 초기(0.15)보다 훨씬 크다."""
    m = _model()
    x = _x(m)
    w = {'rain_mm': 0.0, 'et0_mm': 5.0}
    _, f_ini = m.step_fluxes(x, {}, dict(w, dap=5))
    _, f_mid = m.step_fluxes(x, {}, dict(w, dap=60))
    assert float(f_mid['transp']) > 4 * float(f_ini['transp'])
    # kcb_scale 이 증산을 비례로 줄인다
    x2 = x.copy()
    x2[m.idx['kcb_scale']] = 0.5
    _, f_half = m.step_fluxes(x2, {}, dict(w, dap=60))
    assert float(f_half['transp']) == pytest.approx(0.5 * float(f_mid['transp']), rel=0.05)


def test_kcb_curve_stages():
    c = CROPS['perilla']
    l1, l2, l3, l4 = c.stage_days
    assert c.kcb(0) == c.kcb_ini
    assert c.kcb(l1 + l2 / 2) == pytest.approx((c.kcb_ini + c.kcb_mid) / 2)
    assert c.kcb(l1 + l2 + 1) == c.kcb_mid
    assert c.kcb(l1 + l2 + l3 + l4 + 10) == c.kcb_end


def test_observe_is_linear_calibration_of_one_layer():
    m = _model()
    x = _x(m, (0.10, 0.30, 0.20))
    s = SensorSpec('s', layer=1, a=1.2, b=-5.0)
    assert float(m.observe(x, s)) == pytest.approx(1.2 * 30.0 - 5.0)
    assert SensorSpec.layer_for_depth(5) == 0
    assert SensorSpec.layer_for_depth(15) == 1
    assert SensorSpec.layer_for_depth(90) == 2


def test_risks_probabilities():
    """앙상블 궤적에서 물 부족 확률이 마를수록 커진다."""
    m = _model()
    X = m.init_state(prior=FieldPrior(texture='loam'), n=32, rng=np.random.default_rng(0))
    traj = []
    for d in range(20):
        X = m.step(X, {}, {'rain_mm': 0.0, 'et0_mm': 6.0, 'dap': 50 + d})
        traj.append(X.copy())
    r = m.risks(np.stack(traj, axis=1), dap0=50)
    p = r['p_water_short']
    assert p.shape == (20,) and np.all((0 <= p) & (p <= 1))
    assert p[-1] > p[0] and p[-1] == 1.0
    assert np.all(r['p_water_short_severe'] <= p)


def test_nearest_texture():
    t = TEXTURES['silt_loam']
    assert nearest_texture(t.theta_fc, t.tau_drain_d)[0] == 'silt_loam'
    assert nearest_texture(0.12, 0.3)[0] == 'sand'


def test_clip_restores_parameter_order():
    m = _model()
    x = _x(m)
    x[m.idx['theta_fc']] = 0.05
    x[m.idx['theta_wp']] = 0.25
    x[m.idx['theta_sat']] = 0.70
    y = m.clip(x)
    assert y[m.idx['theta_wp']] + 0.02 <= y[m.idx['theta_fc']] + 1e-12
    assert y[m.idx['theta_fc']] <= y[m.idx['theta_sat']] - 0.02 + 1e-12
    assert math.isclose(y[m.idx['theta_sat']], 0.60)
