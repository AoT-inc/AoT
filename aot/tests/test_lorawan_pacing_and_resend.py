# coding=utf-8
"""LoRaWAN downlink pacing and confirm-retry timing.

Covers the two fixes for the koat site's downlink saturation:

2. The confirm retry interval is floored at the pacing interval, so a
   retransmission is no longer scheduled sooner than the link can carry it.
3. Once the pacing backlog is deeper than MAX_PACE_WAIT_S the downlink is
   dropped. It used to be sent anyway after a capped sleep, which turned the
   rate limiter into a thundering herd at exactly the congestion it exists to
   prevent.
"""
import threading
import time

import pytest

from aot.utils import lorawan_pacing
from aot.utils.lorawan_pacing import claim_send_slot, pace_send


@pytest.fixture(autouse=True)
def reset_pacing():
    """The limiter is module-global; each test starts from an idle site."""
    lorawan_pacing._NEXT_SLOT[0] = 0.0
    yield
    lorawan_pacing._NEXT_SLOT[0] = 0.0


# --- slot claiming ------------------------------------------------------------

def test_first_send_on_an_idle_site_waits_for_nothing():
    assert claim_send_slot(min_interval=4.0) == 0.0


def test_each_claim_pushes_the_next_one_out_by_the_interval():
    assert claim_send_slot(min_interval=4.0) == 0.0
    assert claim_send_slot(min_interval=4.0) == pytest.approx(4.0, abs=0.05)
    assert claim_send_slot(min_interval=4.0) == pytest.approx(8.0, abs=0.05)


def test_a_backlog_deeper_than_the_cap_is_refused():
    for _ in range(8):                       # 8 x 4 s = 32 s > 30 s cap
        claim_send_slot(min_interval=4.0, max_wait=30.0)
    assert claim_send_slot(min_interval=4.0, max_wait=30.0) is None


def test_a_refused_claim_does_not_consume_a_slot():
    """The regression: a refused send must not push the queue out further."""
    for _ in range(8):
        claim_send_slot(min_interval=4.0, max_wait=30.0)
    before = lorawan_pacing._NEXT_SLOT[0]
    assert claim_send_slot(min_interval=4.0, max_wait=30.0) is None
    assert lorawan_pacing._NEXT_SLOT[0] == before


def test_the_queue_drains_and_accepts_sends_again():
    for _ in range(8):
        claim_send_slot(min_interval=4.0, max_wait=30.0)
    assert claim_send_slot(min_interval=4.0, max_wait=30.0) is None
    lorawan_pacing._NEXT_SLOT[0] = time.time() + 1.0     # queue mostly drained
    assert claim_send_slot(min_interval=4.0, max_wait=30.0) == pytest.approx(1.0, abs=0.05)


def test_claims_are_serialized_under_concurrency():
    """Two threads must never be handed the same slot."""
    waits = []
    guard = threading.Lock()

    def claim():
        w = claim_send_slot(min_interval=4.0, max_wait=300.0)
        with guard:
            waits.append(w)

    threads = [threading.Thread(target=claim) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(waits) == 20
    assert None not in waits
    assert sorted(round(w, 2) for w in waits) == [
        pytest.approx(i * 4.0, abs=0.1) for i in range(20)]


# --- pace_send ----------------------------------------------------------------

def test_pace_send_allows_an_immediate_send():
    started = time.monotonic()
    assert pace_send(min_interval=4.0) is True
    assert time.monotonic() - started < 0.5


def test_pace_send_sleeps_until_the_slot():
    assert pace_send(min_interval=0.3) is True
    started = time.monotonic()
    assert pace_send(min_interval=0.3) is True
    assert time.monotonic() - started == pytest.approx(0.3, abs=0.2)


def test_pace_send_refuses_instead_of_sending_late():
    """Was: sleep(30) then transmit anyway — every backlogged sender at once."""
    for _ in range(8):
        claim_send_slot(min_interval=4.0, max_wait=30.0)
    started = time.monotonic()
    assert pace_send(min_interval=4.0, max_wait=30.0) is False
    assert time.monotonic() - started < 0.5, "a refused send must not sleep"


# --- resend interval floor ----------------------------------------------------

def test_chirpstack_floors_resends_at_the_pacing_interval():
    from aot.outputs.on_off_chirpstack import OutputModule
    floor = OutputModule.resend_interval_floor_s(object())
    assert floor == lorawan_pacing.MIN_GLOBAL_DOWNLINK_INTERVAL_S


def test_default_floor_is_unchanged_for_ordinary_outputs():
    """Only rate-limited links pay the higher floor."""
    from aot.outputs.confirmable_output import (
        ConfirmableOutputMixin, _MIN_RESEND_INTERVAL_S)
    assert ConfirmableOutputMixin.resend_interval_floor_s(object()) == _MIN_RESEND_INTERVAL_S


ACK_LATENCY_S = 1.7   # device status uplink after dispatch, measured on site


def simulate_dispatches(timeout, floor, pacing=None):
    """When each attempt of one command actually reaches the air.

    begin_command() ticks a resend timer every max(floor, timeout/3), but a
    dispatch only leaves at its pacing slot — that gap between "scheduled" and
    "actually sent" is what the retuning is about, so the test has to model it.

    `pacing` 을 비우면 **현재 사이트 간격**을 쓴다. 여기에 숫자를 박아 두면
    RX2 데이터레이트를 바꿔 간격이 달라져도 테스트는 옛 전제로 계속 통과하거나
    (더 나쁘게) 엉뚱한 이유로 실패한다 — 실제로 SF12→SF10 전환 때 그랬다.
    옛 동작을 재현하는 테스트만 그 시절 값을 명시한다.
    """
    if pacing is None:
        from aot.utils.lorawan_pacing import MIN_GLOBAL_DOWNLINK_INTERVAL_S
        pacing = MIN_GLOBAL_DOWNLINK_INTERVAL_S
    interval = max(floor, timeout / 3.0)
    next_slot = 0.0
    dispatches = []
    scheduled = 0.0
    while scheduled < timeout or not dispatches:
        actual = max(scheduled, next_slot)
        dispatches.append(actual)
        next_slot = actual + pacing
        scheduled += interval
    return dispatches


def test_every_chirpstack_attempt_is_dispatched_before_its_deadline():
    """No attempt may reach the air at/after the fault that discards it."""
    from aot.outputs.on_off_chirpstack import OUTPUT_INFORMATION, OutputModule

    timeout = float(OUTPUT_INFORMATION['command_timeout_default_s'])
    floor = OutputModule.resend_interval_floor_s(object())
    dispatches = simulate_dispatches(timeout, floor)

    assert len(dispatches) >= 2, "no retransmission fits in the window"
    assert max(dispatches) + ACK_LATENCY_S <= timeout, (
        f"attempt at t={max(dispatches):.2f}s cannot be answered before the "
        f"{timeout}s deadline; dispatches={dispatches}")


def test_the_old_resend_floor_wasted_an_attempt():
    """Guards the fix: at the previous 2 s floor the last resend hit the air
    exactly as the command was faulted — 1.32 s of SF12 airtime spent on a
    command already given up on, taking a slot another device needed."""
    dispatches = simulate_dispatches(timeout=8.0, floor=2.0, pacing=4.0)
    assert max(dispatches) + ACK_LATENCY_S > 8.0
    assert len(dispatches) == 3


def test_the_new_floor_drops_that_wasted_attempt():
    dispatches = simulate_dispatches(timeout=8.0, floor=4.0, pacing=4.0)
    assert len(dispatches) == 2, "one dispatch per command should have gone away"
    assert max(dispatches) + ACK_LATENCY_S <= 8.0
