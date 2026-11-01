# coding=utf-8
import threading

from aot.twin import bench
from aot.twin.expiry import is_expired, valid_until_for
from aot.twin.queue import Job, ServerQueues
from aot.twin.types import Status


def test_valid_until_rules():
    assert valid_until_for(1000, 3600, Status.OK) == 1000 + 7200
    assert valid_until_for(1000, 3600, Status.DEGRADED) == 1000 + 7200
    assert valid_until_for(1000, 3600, Status.UNSYNCED) == 1000          # 즉시 만료 (§7-3)
    assert valid_until_for(1000, 3600, Status.NOT_TWINNABLE) == 1000
    assert valid_until_for(1000, 3600, Status.OK, "field_daily") == 1000 + 36 * 3600


def test_expired_semantics():
    assert not is_expired(100.0, 100.0)
    assert is_expired(100.0, 100.1)
    assert is_expired(None, 0)                                           # 모르면 만료


def J(sid, t, at=0.0):
    return Job(sid, (sid, "facility", t), at)


def test_coalesce_same_target():
    q = ServerQueues()
    q.put(J("a", "t1", 1.0))
    q.put(J("a", "t1", 2.0))
    assert q.pending("a") == 1 and q.coalesced == 1
    assert q.get(0).enqueued_at == 2.0


def test_drop_oldest_when_full():
    q = ServerQueues(max_per_server=2)
    for t in ("t1", "t2", "t3"):
        q.put(J("a", t))
    assert q.pending("a") == 2 and q.dropped == 1
    assert q.get(0).target_key[2] == "t2"


def test_round_robin_and_one_in_flight_per_server():
    q = ServerQueues()
    for t in ("a1", "a2", "a3"):
        q.put(J("A", t))
    q.put(J("B", "b1"))
    j1 = q.get(0)
    j2 = q.get(0)
    assert {j1.server_id, j2.server_id} == {"A", "B"}                    # 느린 A 가 B 를 막지 않는다
    assert q.get(0) is None                                              # 둘 다 진행 중 → A 는 한 번에 하나
    q.done(j1)
    q.done(j2)
    assert q.get(0).server_id == "A"


def test_get_blocks_then_wakes():
    q = ServerQueues()
    got = []
    th = threading.Thread(target=lambda: got.append(q.get(timeout=2)))
    th.start()
    q.put(J("A", "x"))
    th.join(3)
    assert got and got[0].server_id == "A"


def test_close_wakes_waiters():
    q = ServerQueues()
    got = []
    th = threading.Thread(target=lambda: got.append(q.get(timeout=5)))
    th.start()
    q.close()
    th.join(2)
    assert got == [None]


def test_bench_tiers():
    assert bench.decide(0.001).tier == "full" and bench.decide(0.001).ensemble_size == 50
    c = bench.decide(10.0, period_s=3600)                                # 예산 900 s → 90 멤버 → full(50)
    assert c.tier == "full"
    c = bench.decide(300.0, period_s=3600)                               # 예산 900 s → 3 멤버: 결정론
    assert (c.tier, c.ensemble_size, c.horizon_frac) == ("deterministic", 1, 1.0)
    c = bench.decide(2000.0, period_s=3600)                              # 1 멤버도 안 들어감 → 경량
    assert c.tier == "light" and c.horizon_frac == 0.5 and c.period_s > 3600


def test_bench_scales_with_targets():
    assert bench.decide(10.0, n_targets=1).tier == "full"
    assert bench.decide(10.0, n_targets=20).ensemble_size < 50           # 대상이 많으면 앙상블이 줄어든다


def test_bench_forced():
    assert bench.forced("light").horizon_frac == 0.5
    assert bench.forced("nope") is None
