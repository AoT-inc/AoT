# coding=utf-8
"""노지 참값(`sim/field_plant.py`)과 버킷 모델의 물 수지 — 설계서 §8-4(E3).

시설의 `twin_effects/tests/test_step_response.py` 와 같은 형식이다: 같은 사건을 독립 참값과 모델에 주고 변화의 **방향과 크기**를 견준다.
참값은 12층 이상·Darcy 흐름이라 버킷과 구조가 다르다. 기준 크기비는 측정으로 정한 느슨한 범위이고, 같은 저자의 물리라 현실 검증이 아니다.

닫히는 식: 공급(비 + 관수) = Δ저장 + 증발 + 증산 + 배수 + 유출.
"""
import ast
import inspect

import numpy as np
import pytest

from aot.functions.utils.field_twin import FieldBucketModel, FieldPrior
from aot.functions.utils.field_twin.sim import field_plant as P

SEEDS = range(6)


def _days(seed, n=40):
    rng = np.random.default_rng(seed)
    return [(float(rng.choice([0.0, 0.0, 0.0, 8.0, 30.0])), float(rng.choice([0.0, 0.0, 12.0, 25.0])),
             float(rng.uniform(0.5, 6.0))) for _ in range(n)]


def _bucket_run(days, theta0=0.27):
    model = FieldBucketModel()
    x = model.init_state(prior=FieldPrior(texture="loam", theta0=[theta0] * 3))
    start = float(model.storage_mm(x))
    tot = {k: 0.0 for k in ("rain", "irr", "runoff", "evap", "transp", "drain")}
    for i, (rain, irr, et0) in enumerate(days):
        x, flux = model.step_fluxes(x, {"irr_mm": irr}, {"rain_mm": rain, "et0_mm": et0, "t_mean": 20.0, "dap": i + 30})
        for k in tot:
            tot[k] += float(flux[k])
    return model, x, start, tot


def test_plant_does_not_import_the_bucket_model():
    tree = ast.parse(inspect.getsource(P))
    names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("model" in n or "params" in n or "field_twin" in n for n in names), names


def test_plant_is_structurally_different():
    with pytest.raises(ValueError):
        P.FieldPlant(n_layers=3)
    assert len(P.FieldPlant().dz) >= 10


@pytest.mark.parametrize("seed", SEEDS)
def test_plant_water_balance_closes(seed):
    plant = P.FieldPlant()
    plant.run(_days(seed))
    led = plant.ledger
    assert led["irr"] > 0 and led["transp"] > 0 and led["drain"] > 0
    assert abs(plant.check_balance()) < 1e-6


@pytest.mark.parametrize("seed", SEEDS)
def test_bucket_water_balance_closes_with_irrigation(seed):
    days = _days(seed)
    model, x, start, tot = _bucket_run(days)
    assert tot["irr"] == pytest.approx(sum(d[1] for d in days))
    closed = tot["rain"] + tot["irr"] - (float(model.storage_mm(x)) - start) - tot["evap"] - tot["transp"] \
        - tot["drain"] - tot["runoff"]
    assert abs(closed) < 1e-6


def test_unknown_irrigation_enters_nothing_but_does_not_break_the_balance():
    model = FieldBucketModel()
    x = model.init_state(prior=FieldPrior(texture="loam", theta0=[0.27] * 3))
    _x, flux = model.step_fluxes(x, {"irr_mm": float("nan")}, {"rain_mm": 0.0, "et0_mm": 3.0, "dap": 30})
    assert float(flux["irr"]) == 0.0


def _delta_plant(irr, et0=4.0):
    dry, wet = P.FieldPlant(), P.FieldPlant()
    for _ in range(6):
        dry.step_day(0.0, 0.0, et0)
        wet.step_day(0.0, 0.0, et0)
    dry.step_day(0.0, 0.0, et0)
    wet.step_day(0.0, irr, et0)
    return (wet.theta_at(0.0, 0.3) - dry.theta_at(0.0, 0.3), wet.storage_mm() - dry.storage_mm(), wet.ledger["runoff"])


def _delta_bucket(irr, et0=4.0):
    model = FieldBucketModel()
    x = model.init_state(prior=FieldPrior(texture="loam", theta0=[0.28] * 3))
    w = {"rain_mm": 0.0, "et0_mm": et0, "t_mean": 20.0, "dap": 40}
    for _ in range(6):
        x = model.step(x, {"irr_mm": 0.0}, w)
    a = model.step(x, {"irr_mm": 0.0}, w)
    b = model.step(x, {"irr_mm": irr}, w)
    theta = lambda s: (0.1 * s[model.idx["theta1"]] + 0.2 * s[model.idx["theta2"]]) / 0.3
    return float(theta(b) - theta(a)), float(model.storage_mm(b) - model.storage_mm(a))


# (깊이 mm, Δθ 크기비 범위) — 비 = 버킷 / 참값. 측정(2026-11-01)으로 정한 느슨한 값. 시설의 계단 시험과 같은 0.5~2.
@pytest.mark.parametrize("irr,band", [(10.0, (0.5, 2.0)), (20.0, (0.5, 2.0)), (40.0, (0.5, 2.0))])
def test_irrigation_response_sign_and_size(irr, band):
    dp, sp, _run = _delta_plant(irr)
    db, sb = _delta_bucket(irr)
    assert dp > 0 and db > 0                                      # 부호 일치(필수)
    assert band[0] <= db / dp <= band[1], (irr, db, dp)
    assert 0.5 <= sb / sp <= 2.0, (irr, sb, sp)


def test_depth_from_litres_and_area_is_a_unit_identity():
    """1 L 를 1 m² 에 고르게 주면 1 mm 다 — `water_day` 의 mm 이 참값·모델 입력과 같은 단위다."""
    from aot.functions.utils.water_net import result as R
    row = R.run_row("v1", 0.0, 3600.0, 60.0, 3600.0, 0.5, area_m2=900.0)
    assert row["litres"] == 1800.0 and row["mm"] == 2.0
