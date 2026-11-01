# coding=utf-8
import time

import pytest

from aot.twin import bench, engine, models
from aot.twin.types import Provenance, Status
from .helpers import MemSource, facility_spec, field_spec, recent

FULL = bench.Capability("full", 20, 1.0, 3600.0, 0.0)
DET = bench.Capability("deterministic", 1, 1.0, 3600.0, 0.0)
LIGHT = bench.Capability("light", 1, 0.5, 7200.0, 0.0)


def _src(now, t_in=22.0, rh_in=70.0, with_ext=True):
    d = {("sens-in", "C", 0): recent(t_in, now), ("sens-in", "percent", 1): recent(rh_in, now)}
    if with_ext:
        d[("sens-out", "C", 0)] = recent(10.0, now)
        d[("sens-out", "percent", 1)] = recent(50.0, now)
    return MemSource(d)


def _run(spec, src, cap, now):
    return engine.run_target(spec, src, models.get(spec.kind.value, spec.options.get("model")), cap, now)


def test_facility_ok_full_ensemble():
    now = time.time()
    r = _run(facility_spec(), _src(now), FULL, now)
    assert r.status == Status.OK
    o = r.output
    assert len(o.grids["fast"]) == 289 and o.meta["ensemble_size"] == 20
    assert o.meta["valid_until"] == o.t0 + 7200 and o.meta["horizon_h"] == 48
    T = o.quantiles["fast"]["T"]
    assert all(a <= b <= c for a, b, c in zip(T["p10"], T["p50"], T["p90"]))
    assert T["p90"][0] > T["p10"][0]                                   # 앙상블이 있어 띠에 폭이 있다
    # 외기 10 °C 쪽으로 끌려간다(자리표시자 물리)
    assert T["p50"][-1] < T["p50"][0]
    assert o.t0 % 60 == 0 and o.t0 <= now


def test_deterministic_has_only_p50():
    now = time.time()
    o = _run(facility_spec(), _src(now), DET, now).output
    assert set(o.quantiles["fast"]["T"]) == {"p50"} and o.meta["ensemble_size"] == 1


def test_light_halves_horizon():
    now = time.time()
    o = _run(facility_spec(), _src(now), LIGHT, now).output
    assert len(o.grids["fast"]) == 145 and o.meta["horizon_h"] == 24


def test_reproducible_given_same_t0():
    now = time.time()
    a = _run(facility_spec(), _src(now), FULL, now).output
    b = _run(facility_spec(), _src(now), FULL, now).output
    assert a.quantiles["fast"]["T"]["p10"] == b.quantiles["fast"]["T"]["p10"]


def test_provenance_label_is_not_a_gate():
    """출처 표시(실측·미러·가상·미확인)는 판정에 쓰지 않는다 — 위치로 정해진 입력은 미러여도 그대로 동기화한다(2026-10-26)."""
    now = time.time()
    for prov in (Provenance.UNKNOWN, Provenance.MIRROR, Provenance.VIRTUAL):
        r = _run(facility_spec(provenance=prov), _src(now), FULL, now)
        assert r.status == Status.OK and r.output.grids


def test_missing_required_is_unsynced():
    now = time.time()
    src = MemSource({("sens-in", "C", 0): recent(22.0, now)})       # RH_int 없음
    r = _run(facility_spec(), src, FULL, now)
    assert r.status == Status.UNSYNCED and not r.output.grids


def test_stale_obs_is_unsynced():
    now = time.time()
    src = _src(now - 3 * 3600)
    r = engine.run_target(facility_spec(obs_window_s=6 * 3600), src, models.get("facility", "dummy_facility"), FULL, now)
    assert r.status == Status.UNSYNCED and "낡" in r.reason


def test_missing_optional_input_degrades():
    now = time.time()
    r = _run(facility_spec(), _src(now, with_ext=False), FULL, now)
    assert r.status == Status.DEGRADED and "보조 입력" in r.reason


def test_unwired_required_is_not_twinnable():
    now = time.time()
    spec = facility_spec()
    del spec.inputs["RH_int"]
    assert _run(spec, _src(now), FULL, now).status == Status.NOT_TWINNABLE


def test_read_failure_is_missing_not_crash():
    now = time.time()

    class Boom(MemSource):
        def read_series(self, *a):
            raise RuntimeError("down")

    r = _run(facility_spec(), Boom({}), FULL, now)
    assert r.status == Status.UNSYNCED


def test_model_exception_is_error_without_curves():
    now = time.time()

    class Bad(models.dummy.DummyFacilityModel):
        def step(self, *a, **k):
            raise ZeroDivisionError

    r = engine.run_target(facility_spec(), _src(now), Bad(), FULL, now)
    assert r.status == Status.ERROR and not r.output.grids


def test_frost_event_probability():
    now = time.time()
    src = _src(now, t_in=6.0)                                       # 실내 6 °C, 외기 10 °C 대신 -5 °C
    src.data[("sens-out", "C", 0)] = recent(-5.0, now)
    o = _run(facility_spec(T_low=5.0), src, FULL, now).output
    fr = o.events["fast"]["frost"]
    assert fr[-1] > 0.9 and 0.0 <= min(fr)


def test_field_kind_picks_field_model():
    now = time.time()
    src = MemSource({("soil-3", "percent", 2): recent(35.0, now)})
    r = _run(field_spec(), src, FULL, now)
    assert r.status == Status.OK
    o = r.output
    assert len(o.grids["daily"]) == 15 and o.meta["horizon_d"] == 14
    assert o.meta["valid_until"] == o.t0 + 36 * 3600
    th = o.quantiles["daily"]["theta_root"]["p50"]
    assert th[-1] < th[0]                                           # 마른다
    assert "water_deficit" in o.events["daily"]
