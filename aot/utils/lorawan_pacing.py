# coding=utf-8
"""Site-wide LoRaWAN downlink pacing (single shared rate limiter).

A site typically has ONE LoRaWAN gateway, which is half-duplex: while it is
transmitting a downlink it cannot hear device uplinks. If many downlinks are
enqueued at once — valve control from the on/off output, CFG/class changes from
the LoRaWAN class scheduler, plus retries — ChirpStack hands them to the gateway
back-to-back, the gateway floods the air, and the device ACK uplinks (FP11/FP12)
that the retry logic depends on get lost, triggering MORE retries
(self-reinforcing congestion).

Every downlink path shares the ONE limiter in this module so the whole site is
paced together (not just per module). Outputs and functions run in the same AoT
daemon process, so these module-level globals are genuinely shared.

Usage — call pace_send() and drop the downlink if it returns False (never call
it while holding a lock: it sleeps):

    from aot.utils.lorawan_pacing import pace_send
    if not pace_send():
        return False  # backlog too deep; sending now would defeat the pacing
    # ... perform the actual enqueue ...
"""

import threading
from time import sleep, time

# Minimum gap between ANY two downlinks site-wide, sized so the half-duplex
# gateway is actually IDLE when the device's ACK comes back.
#
# The original 1.5 s assumed a short downlink. It is not: a Class C downlink goes
# out in RX2, and with the KR920 default rx2_dr=0 (SF12) a ~16 B frame occupies
# ~1.32 s of gateway TX time — during which the concentrator cannot receive on
# ANY of its channels. Measured on site (2026-07-27), the device's FP11 ctrl_ack
# lands ~1.7 s after dispatch, i.e. squarely inside the NEXT transmission when
# the gap is 1.5 s: the ACK was being lost structurally, not by chance. Busy
# minutes showed 23-26 downlinks/min => 50-57 % of the minute deaf, and each lost
# ACK triggered a retry, which produced yet another 1.32 s of deafness.
#
# 4.0 s => ~1.32 s TX + ~2.7 s listening per slot (33 % TX duty), so both the
# ctrl_ack (~1.7 s) and a valve's completion status land in a quiet window.
#
# This constant is tied to the RX2 data rate. If rx2_dr is raised (SF12 -> SF9 is
# ~165 ms, SF7 ~51 ms), the airtime collapses and this can come back down toward
# the original 1.5 s.
MIN_GLOBAL_DOWNLINK_INTERVAL_S = 4.0
# Cap how long a single send may block waiting for its slot. Past this the
# downlink is DROPPED, not sent late.
#
# It used to be sent late: the cap clamped the returned sleep but the slot had
# already been reserved, so once the backlog passed ~7 deep every caller slept
# 30 s and then transmitted at once — the pacing silently inverted into a
# thundering herd at exactly the congestion it exists to prevent. A valve
# command that has been queued 30 s is stale anyway, so failing it visibly beats
# flooding the air with it.
MAX_PACE_WAIT_S = 30.0

_PACE_LOCK = threading.Lock()
_NEXT_SLOT = [0.0]  # mutable holder: earliest epoch the next downlink may go out


def claim_send_slot(min_interval=MIN_GLOBAL_DOWNLINK_INTERVAL_S,
                    max_wait=MAX_PACE_WAIT_S):
    """Reserve the next global send slot and return seconds to sleep before sending.

    Returns None if the backlog is already deeper than max_wait, in which case
    NO slot is reserved and the caller must drop the downlink — reserving one
    anyway would push the queue out further for everybody behind it.

    The lock is held only to claim a monotonically increasing slot (fast); the
    caller does the sleeping outside the lock, so a slow or failing send never
    stalls the rest of the site.
    """
    try:
        mi = float(min_interval)
    except Exception:
        mi = MIN_GLOBAL_DOWNLINK_INTERVAL_S
    if mi < 0:
        mi = 0.0
    with _PACE_LOCK:
        now = time()
        slot = now if now >= _NEXT_SLOT[0] else _NEXT_SLOT[0]
        if slot - now > max_wait:
            return None
        _NEXT_SLOT[0] = slot + mi
    return max(0.0, slot - now)


def pace_send(min_interval=MIN_GLOBAL_DOWNLINK_INTERVAL_S,
              max_wait=MAX_PACE_WAIT_S):
    """Wait for this downlink's slot. False means drop it instead of sending.

    Every downlink path goes through here so the drop decision lives in one
    place: callers that merely swallowed an exception and transmitted anyway
    were how the pacing got bypassed before.
    """
    wait = claim_send_slot(min_interval=min_interval, max_wait=max_wait)
    if wait is None:
        return False
    if wait > 0:
        sleep(wait)
    return True
