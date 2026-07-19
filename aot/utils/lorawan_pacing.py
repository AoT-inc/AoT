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

Usage (sleep OUTSIDE any lock the caller may hold):

    from aot.utils.lorawan_pacing import claim_send_slot
    from time import sleep
    wait = claim_send_slot()
    if wait > 0:
        sleep(wait)
    # ... perform the actual enqueue ...
"""

import threading
from time import time

# Minimum gap between ANY two downlinks site-wide. ~1.5 s leaves the half-duplex
# gateway idle windows to receive device ACK uplinks between transmissions.
MIN_GLOBAL_DOWNLINK_INTERVAL_S = 1.5
# Cap how long a single send may block waiting for its slot, so an extreme burst
# degrades to "sent a bit early" rather than blocking a caller unboundedly.
MAX_PACE_WAIT_S = 30.0

_PACE_LOCK = threading.Lock()
_NEXT_SLOT = [0.0]  # mutable holder: earliest epoch the next downlink may go out


def claim_send_slot(min_interval=MIN_GLOBAL_DOWNLINK_INTERVAL_S,
                    max_wait=MAX_PACE_WAIT_S):
    """Reserve the next global send slot and return seconds to sleep before sending.

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
        _NEXT_SLOT[0] = slot + mi
    return max(0.0, min(slot - now, max_wait))
