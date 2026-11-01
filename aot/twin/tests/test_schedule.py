# coding=utf-8
"""정기 실행(벽시계) — 예약 시각 계산과 노드 루프(재시도·따라잡기). 가짜 시계, 실제 대기 없음."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from aot.twin import schedule as sch, settings as S
from aot.twin.node import JobReport, TwinNode

KST = ZoneInfo("Asia/Seoul")


def _t(y, mo, d, h, mi, tz=KST):
    return dt.datetime(y, mo, d, h, mi, tzinfo=tz).timestamp()


class TestNextRun:
    RA = sch.parse_run_at(["18:10", "06:10"])

    def test_sorted_and_dedup(self):
        assert sch.parse_run_at(["18:10", "06:10", "6:10"]) == ((6, 10), (18, 10))

    @pytest.mark.parametrize("bad", ["24:00", "6", "06:60", "abc", ""])
    def test_bad_run_at(self, bad):
        with pytest.raises(ValueError):
            sch.parse_run_at([bad])

    def test_before_first_same_day(self):
        assert sch.next_run(_t(2026, 10, 22, 5, 0), self.RA, "Asia/Seoul") == _t(2026, 10, 22, 6, 10)

    def test_between(self):
        assert sch.next_run(_t(2026, 10, 22, 12, 0), self.RA, "Asia/Seoul") == _t(2026, 10, 22, 18, 10)

    def test_after_last_goes_tomorrow(self):
        assert sch.next_run(_t(2026, 10, 22, 19, 0), self.RA, "Asia/Seoul") == _t(2026, 10, 23, 6, 10)

    def test_exactly_on_time_is_strictly_after(self):
        assert sch.next_run(_t(2026, 10, 22, 6, 10), self.RA, "Asia/Seoul") == _t(2026, 10, 22, 18, 10)

    def test_timezone_matters(self):
        now = _t(2026, 10, 22, 5, 0)                       # KST 05:00 = UTC 20:00 (전날)
        assert sch.next_run(now, ((6, 10),), "UTC") == _t(2026, 10, 22, 6, 10, ZoneInfo("UTC"))

    def test_dst_zone_ok(self):
        ny = ZoneInfo("America/New_York")
        now = _t(2026, 3, 8, 1, 0, ny)                     # 일광절약 시작일
        assert sch.next_run(now, ((6, 10),), "America/New_York") == _t(2026, 3, 8, 6, 10, ny)


class TestSettings:
    def test_parse_and_defaults(self):
        ns = S.from_dict({"schedule": {"run_at": ["06:10", "18:10"], "timezone": "Asia/Seoul"}})
        assert ns.schedule.run_at == ["06:10", "18:10"] and ns.schedule.run_on_start and ns.schedule.max_retries == 4
        assert S.from_dict({}).schedule.run_at == []       # 없으면 예전 주기 방식

    @pytest.mark.parametrize("bad", [{"run_at": ["25:00"]}, {"run_at": ["06:10"], "timezone": "Mars/Base"},
                                     {"run_at": ["06:10"], "retry_s": 5}, {"run_at": [f"0{i}:00" for i in range(7)]}])
    def test_invalid(self, bad):
        with pytest.raises(S.SettingsError):
            S.from_dict({"schedule": bad})


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _node(clock, outcomes, **sc):
    """run_once 가 outcomes 를 차례로 돌려주는 노드. 대기는 시계를 점프시킨다."""
    ns = S.NodeSettings(enabled=True, force_tier="light", schedule=S.Schedule(
        run_at=["06:10", "18:10"], timezone="Asia/Seoul", **sc))
    node = TwinNode(ns, channels={}, clock=clock)
    node.calls = []

    def run_once():
        node.calls.append(clock.t)
        return outcomes.pop(0)
    node.run_once = run_once
    node.startup_bench = lambda: None

    def wait(sec):                                         # 기다리는 만큼 시계를 앞으로
        clock.t += sec
        return False
    node._stop.wait = wait
    return node


OK = [JobReport("s", ("s", "field", "p"), None)]
BAD = [JobReport("s", ("s", "field", "p"), None, error="OSError: down")]


def test_cycle_ok_rules():
    assert TwinNode.cycle_ok(OK)
    assert not TwinNode.cycle_ok([])                       # 서버가 안 닿아 한 건도 못 돌았다
    assert not TwinNode.cycle_ok(BAD)
    assert not TwinNode.cycle_ok([JobReport("s", ("s", "f", "p"), None, rejected=3)])


def test_runs_on_start_then_at_scheduled_times():
    clock = _Clock(_t(2026, 10, 22, 5, 0))
    node = _node(clock, [OK, OK, OK])
    assert node.serve_scheduled(max_cycles=3) == 3
    assert node.calls == [_t(2026, 10, 22, 5, 0), _t(2026, 10, 22, 6, 10), _t(2026, 10, 22, 18, 10)]


def test_run_on_start_false_waits_for_first_slot():
    clock = _Clock(_t(2026, 10, 22, 5, 0))
    node = _node(clock, [OK], run_on_start=False)
    node.serve_scheduled(max_cycles=1)
    assert node.calls == [_t(2026, 10, 22, 6, 10)]


def test_retry_then_recover():
    clock = _Clock(_t(2026, 10, 22, 7, 0))
    node = _node(clock, [BAD, BAD, OK, OK], retry_s=900, max_retries=4)
    node.serve_scheduled(max_cycles=4)
    t0 = _t(2026, 10, 22, 7, 0)
    assert node.calls[:3] == [t0, t0 + 900, t0 + 1800]     # 15 분 간격 재시도
    assert node.calls[3] == _t(2026, 10, 22, 18, 10)       # 성공한 뒤는 다음 예약 시각


def test_gives_up_until_next_slot_after_max_retries():
    clock = _Clock(_t(2026, 10, 22, 7, 0))
    node = _node(clock, [BAD] * 3 + [OK], retry_s=900, max_retries=2)
    node.serve_scheduled(max_cycles=4)
    assert node.calls[3] == _t(2026, 10, 22, 18, 10)       # 시작 + 재시도 2 + 포기 → 다음 슬롯


def test_retry_never_overshoots_next_slot():
    clock = _Clock(_t(2026, 10, 22, 18, 0))
    node = _node(clock, [BAD, OK], retry_s=3600, max_retries=4)
    node.serve_scheduled(max_cycles=2)
    assert node.calls[1] == _t(2026, 10, 22, 18, 10)       # 한 시간 뒤가 아니라 10 분 뒤 예약 시각


def test_exception_in_cycle_is_contained():
    clock = _Clock(_t(2026, 10, 22, 7, 0))
    node = _node(clock, [], retry_s=900)
    outcomes = iter([RuntimeError("boom"), OK])

    def run_once():
        node.calls.append(clock.t)
        v = next(outcomes)
        if isinstance(v, Exception):
            raise v
        return v
    node.run_once = run_once
    assert node.serve_scheduled(max_cycles=2) == 2
