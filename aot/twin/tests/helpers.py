# coding=utf-8
import time

from aot.twin.types import Provenance, SeriesRef, TargetKind, TargetSpec

M = Provenance.MEASURED


def facility_spec(server_id="dev", provenance=M, with_ext=True, **opts):
    opts.setdefault("model", "dummy_facility")    # 뼈대 배관 시험 — 진짜 시설 모델은 test_facility_greybox
    inputs = {"T_int": SeriesRef("sens-in", "C", 0, provenance),
              "RH_int": SeriesRef("sens-in", "percent", 1, provenance)}
    if with_ext:
        inputs["T_ext"] = SeriesRef("sens-out", "C", 0, provenance)
        inputs["RH_ext"] = SeriesRef("sens-out", "percent", 1, provenance)
    return TargetSpec(server_id, TargetKind.FACILITY, "coord-1", facility="a3d725da",
                      inputs=inputs, options=opts)


def field_spec(server_id="dev", provenance=M, **opts):
    opts.setdefault("model", "dummy_field")       # 뼈대 배관 시험 — 진짜 노지 모델은 test_field_bucket
    return TargetSpec(server_id, TargetKind.FIELD, "plot-53bdbec9", facility="",
                      inputs={"theta": SeriesRef("soil-3", "percent", 2, provenance)}, options=opts)


def seed_facility(fake, t_in=22.0, rh_in=70.0, t_out=10.0, rh_out=50.0, now=None):
    fake.seed_recent("sens-in", "C", 0, t_in, now)
    fake.seed_recent("sens-in", "percent", 1, rh_in, now)
    fake.seed_recent("sens-out", "C", 0, t_out, now)
    fake.seed_recent("sens-out", "percent", 1, rh_out, now)


class MemSource:
    """메모리 소스 — 서버 없이 엔진만 시험."""
    server_id = "mem"

    def __init__(self, data, targets=()):
        self.data, self._t = data, list(targets)

    def ping(self):
        return True

    def list_targets(self):
        return self._t

    def read_series(self, ref, window_s, now):
        from aot.twin.types import Series
        rows = self.data.get((ref.unique_id, ref.unit, ref.channel), [])
        s = Series()
        for t, v in rows:
            if now - window_s <= t <= now + 1:
                s.times.append(t)
                s.values.append(v)
        return s


def recent(value, now=None, n=6, step=60.0):
    now = time.time() if now is None else now
    return [(now - (n - 1 - i) * step - 5, value) for i in range(n)]
