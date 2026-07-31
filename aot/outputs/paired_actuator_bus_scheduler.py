# coding=utf-8
"""Shared bus scheduler for ``actuator_paired_bus`` outputs.

This lives in its own module for one specific reason: AoT loads output modules
with ``load_module_from_file()``, which builds a FRESH module object per Output
and never registers it in ``sys.modules``. Module-level state declared inside
``actuator_paired_bus.py`` is therefore private to each Output, not shared.

Four windows on one relay pair each got their own registry that way, so each one
drove the shared bus on its own schedule — four overlapping ON commands, and the
first actuator to finish switched the bus off underneath the other three. The
relay leases were per-copy too, so nothing serialized.

Because this module is reached through the normal import system, every copy of
``actuator_paired_bus`` resolves to this single instance, and the registry, the
bus workers and the relay leases really are process-wide.
"""
import logging
import threading
import time

# Stage boundaries closer together than this (seconds) are merged.
STAGE_EPSILON = 0.05
# Granularity of the interruptible travel wait.
TRAVEL_SLICE_SEC = 0.2
# Delay before the startup relay sweep, so peer outputs finish setting up first.
STARTUP_SWEEP_DELAY_SEC = 5.0

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Bus registry — instances sharing an Open/Close pair share one scheduler
# ─────────────────────────────────────────────────────────────────────────────
_BUS_REGISTRY = {}
_BUS_REGISTRY_LOCK = threading.RLock()

# Process-wide relay leases. A bus is identified by its Open/Close pair, so two
# buses that overlap only partially — actuator A wired to CH1/CH2, actuator B to
# CH1/CH7 — would otherwise get separate workers and could energize CH1 at the
# same time. Every batch leases each relay key it may touch, so any overlap
# serializes regardless of how the pairs were configured.
_RELAY_LEASES = {}
_RELAY_CONDITION = threading.Condition()
# Upper bound on how long a batch waits for relays another batch is using. Long
# enough to outlast a full travel, short enough that a leaked lease surfaces.
RELAY_LEASE_TIMEOUT_SEC = 600.0


def _acquire_relays(relay_keys, owner, timeout=RELAY_LEASE_TIMEOUT_SEC):
    """Lease every relay key for `owner`. All-or-nothing; False on timeout."""
    if not relay_keys:
        return True
    deadline = time.time() + timeout
    with _RELAY_CONDITION:
        while True:
            busy = [key for key in relay_keys
                    if _RELAY_LEASES.get(key, owner) is not owner]
            if not busy:
                for key in relay_keys:
                    _RELAY_LEASES[key] = owner
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.error("Relay lease timed out waiting for %s", sorted(busy))
                return False
            _RELAY_CONDITION.wait(timeout=min(remaining, 1.0))


def _release_relays(relay_keys, owner):
    if not relay_keys:
        return
    with _RELAY_CONDITION:
        for key in relay_keys:
            if _RELAY_LEASES.get(key) is owner:
                _RELAY_LEASES.pop(key, None)
        _RELAY_CONDITION.notify_all()


def get_bus(bus_key):
    with _BUS_REGISTRY_LOCK:
        bus = _BUS_REGISTRY.get(bus_key)
        if bus is None:
            bus = _Bus(bus_key)
            _BUS_REGISTRY[bus_key] = bus
        return bus


def drop_member(member):
    """Detach a member from its bus, discarding the bus once it is empty."""
    with _BUS_REGISTRY_LOCK:
        for key, bus in list(_BUS_REGISTRY.items()):
            if bus.detach(member):
                if bus.is_empty():
                    bus.shutdown()
                    _BUS_REGISTRY.pop(key, None)


class _Bus:
    """Serializes access to one shared Open/Close relay pair.

    Owns a single worker thread. Every actuator wired to this pair submits its
    target here; the worker plans them into stages and drives the bus. Nothing
    else may energize the pair while a batch runs.
    """

    def __init__(self, key):
        self.key = key
        self.logger = logging.getLogger('{}.bus'.format(__name__))

        self._members = {}          # output unique_id -> OutputModule
        self._requests = {}         # output unique_id -> target percent
        self._stops = set()
        self._req_lock = threading.RLock()
        self._wake = threading.Event()
        self._interrupt = False

        self._engaged = {}          # output unique_id -> member (selector on)
        self._last_ref_key = None   # relay energized most recently
        self._active_drive_ref = None

        self._state_lock = threading.RLock()
        self._batch_running = False
        self._calib_holder = None

        self._thread = None
        self._stopping = False
        self._swept = False

    # ── membership ───────────────────────────────────────────────────────────
    def attach(self, member):
        with self._req_lock:
            self._members[member.unique_id] = member
        self._ensure_thread()

    def detach(self, member):
        with self._req_lock:
            if member.unique_id not in self._members:
                return False
            self._members.pop(member.unique_id, None)
            self._requests.pop(member.unique_id, None)
            self._stops.discard(member.unique_id)
        self._engaged.pop(member.unique_id, None)
        return True

    def is_empty(self):
        with self._req_lock:
            return not self._members

    def shutdown(self):
        self._stopping = True
        self._interrupt = True
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=5.0)
            except Exception:
                pass
        self._release_bus()

    def _ensure_thread(self):
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(
                target=self._worker_loop,
                name='paired-bus-{}'.format(self.key[:24]),
                daemon=True)
            self._thread.start()

    # ── submission ───────────────────────────────────────────────────────────
    def submit(self, member, target):
        with self._req_lock:
            self._stops.discard(member.unique_id)
            self._requests[member.unique_id] = target
        # Re-plan: a running batch ends its current stage early so this actuator
        # does not wait out someone else's full travel.
        self._interrupt = True
        self._wake.set()

    def request_stop(self, member):
        with self._req_lock:
            self._requests.pop(member.unique_id, None)
            self._stops.add(member.unique_id)
        self._interrupt = True
        self._wake.set()

    # ── calibration exclusivity ──────────────────────────────────────────────
    def acquire_for_calibration(self, member):
        with self._state_lock:
            if self._batch_running or self._calib_holder is not None:
                return False
            self._calib_holder = member.unique_id
            return True

    def release_calibration(self, member):
        with self._state_lock:
            if self._calib_holder == member.unique_id:
                self._calib_holder = None

    def note_drive_ref(self, ref_key):
        """Record the relay a calibration run energized, for reverse-pause tracking."""
        self._last_ref_key = ref_key

    # ── worker ───────────────────────────────────────────────────────────────
    def _worker_loop(self):
        while not self._stopping:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            if self._stopping:
                break

            if not self._swept:
                self._swept = True
                try:
                    self._startup_sweep()
                except Exception:
                    self.logger.exception("Startup relay sweep failed")

            if not self._has_work():
                continue

            # Collect everything landing inside the batch window so one control
            # cycle targeting every actuator plans as a single bus batch.
            window = self._agg_float('batch_window_sec', 2.0, aggregate=max)
            if window > 0:
                time.sleep(window)

            with self._state_lock:
                if self._calib_holder is not None:
                    continue
                self._batch_running = True
            try:
                self._interrupt = False
                self._run_batch()
            except Exception:
                self.logger.exception("Bus %s batch failed — releasing bus", self.key)
                self._emergency_release()
            finally:
                with self._state_lock:
                    self._batch_running = False

    def _has_work(self):
        with self._req_lock:
            return bool(self._requests) or bool(self._stops)

    def _run_batch(self):
        with self._req_lock:
            stops = set(self._stops)
            self._stops.clear()
            requests = dict(self._requests)
            self._requests.clear()
            members = dict(self._members)

        for unique_id in stops:
            requests.pop(unique_id, None)
            member = members.get(unique_id)
            if member is not None:
                member.finish_motion(member.live_position())

        moves = []
        for unique_id in sorted(requests):
            member = members.get(unique_id)
            if member is None:
                continue
            move = member.plan_move(requests[unique_id])
            if move is None:
                # Nothing to do — still publish so the card shows the resolved position.
                member.finish_motion(member.live_position())
            else:
                moves.append(move)

        if not moves:
            self._release_selectors(list(self._engaged.values()))
            return

        groups = {}
        for move in moves:
            groups.setdefault(move['drive_key'], []).append(move)

        # Closing moves first: an actuator told to shut is the safety-relevant one
        # and must not queue behind an opening batch.
        ordered = sorted(groups.values(),
                         key=lambda items: 0 if items[0]['direction'] == 'close' else 1)

        # Lease every relay this batch may touch. Groups then run strictly one
        # after another on this thread — open and close are never energized at the
        # same moment — and no other bus sharing any of these relays can start.
        relay_keys = self._relay_keys_for(moves)
        if not _acquire_relays(relay_keys, self):
            self.logger.error("Bus %s could not lease its relays — deferring batch", self.key)
            self._requeue(moves)
            return

        try:
            for index, items in enumerate(ordered):
                if self._stopping:
                    self._requeue([m for group in ordered[index:] for m in group])
                    return
                self._run_group(items)
                if self._interrupt:
                    self._requeue([m for group in ordered[index + 1:] for m in group])
                    return
        finally:
            _release_relays(relay_keys, self)

    @staticmethod
    def _relay_keys_for(moves):
        """Every relay key a batch may energize: both bus relays plus selectors."""
        keys = set()
        for move in moves:
            member = move['member']
            open_ref, close_ref = member.raw_bus_refs()
            for ref in (open_ref, close_ref, move['selector_ref']):
                key = member.ref_key(ref)
                if key:
                    keys.add(key)
        return keys

    def _run_group(self, items):
        if not self._allow_parallel(items) and len(items) > 1:
            for position, item in enumerate(items):
                self._run_group([item])
                if self._interrupt or self._stopping:
                    self._requeue(items[position + 1:])
                    return
            return

        longest = max(item['run_sec'] for item in items)
        for item in items:
            # A limit switch absorbs the overrun, so end-stop targets can share the
            # group's longest stage instead of forcing a stage of their own.
            if item['is_end_stop'] and item['end_overrun']:
                item['eff_sec'] = longest
            item['member'].begin_motion(item)

        thresholds = sorted({round(item['eff_sec'], 3) for item in items})
        previous = 0.0
        try:
            for threshold in thresholds:
                stage_sec = threshold - previous
                previous = threshold
                if stage_sec <= STAGE_EPSILON:
                    continue

                active = [item for item in items
                          if item['eff_sec'] >= threshold - STAGE_EPSILON
                          and item['member'].in_motion()]
                if not active:
                    continue

                self._run_stage(active, stage_sec)
                if self._interrupt or self._stopping:
                    break

                done = [item for item in active
                        if item['eff_sec'] <= threshold + STAGE_EPSILON]
                self._release_selectors([item['member'] for item in done])
        finally:
            self._release_selectors([item['member'] for item in items])
            unfinished = []
            for item in items:
                member = item['member']
                if not member.in_motion():
                    continue
                complete = item['driven'] >= item['run_sec'] - STAGE_EPSILON
                member.finish_motion(
                    item['target'] if complete else member.live_position())
                if not complete:
                    unfinished.append(item)
            if unfinished and not self._stopping:
                self._requeue(unfinished)

    def _run_stage(self, items, stage_sec):
        """Run one bus stage: engage selectors, drive the bus, stop, settle."""
        settle = self._agg_float('selector_settle_sec', 0.5, aggregate=max, items=items)

        to_engage = [item for item in items
                     if item['selector_ref'] and item['member'].unique_id not in self._engaged]
        if to_engage:
            for item in to_engage:
                item['member'].relay_on(item['selector_ref'])
            for item in to_engage:
                member = item['member']
                if member.wait_confirm([item['selector_ref']], want_on=True):
                    self._engaged[member.unique_id] = member
                else:
                    # Never energize the bus against an unconfirmed selector: the
                    # wrong actuator could be connected, or none at all.
                    self.logger.error(
                        "Selector for %s did not confirm — dropped from this batch",
                        member.output_label())
                    member.relay_off(item['selector_ref'])
                    member.finish_motion(member.live_position())
            items = [item for item in items if item['member'].in_motion()]
            if not items:
                return
            if settle > 0:
                time.sleep(settle)

        driver = items[0]['member']
        drive_ref = items[0]['drive_ref']
        drive_key = items[0]['drive_key']

        # Hardware interlock check. Everything above only guarantees that THIS
        # module never energizes both directions at once; a manual toggle on the
        # output page, a Trigger, or a relay that came up on after a power cut can
        # still have left the opposite direction live. Read it back and clear it
        # before applying power, rather than trusting our own bookkeeping.
        open_ref, close_ref = driver.bus_refs()
        opposite_ref = close_ref if driver.ref_key(open_ref) == drive_key else open_ref
        if driver.ref_key(opposite_ref):
            try:
                if driver.relay_reports_on(opposite_ref):
                    self.logger.error(
                        "Bus %s: opposite relay %s is ON before driving %s — "
                        "switching it off first", self.key,
                        driver.ref_key(opposite_ref), drive_key)
                    driver.relay_off(opposite_ref)
                    if not driver.wait_confirm([opposite_ref], want_on=False):
                        self.logger.error(
                            "Bus %s: opposite relay would not switch off — refusing to drive",
                            self.key)
                        self._interrupt = True
                        return
                    # Force the dwell below: the motors were just under power.
                    self._last_ref_key = driver.ref_key(opposite_ref)
            except Exception as err:
                self.logger.warning(
                    "Bus %s: could not read back the opposite relay (%s) — "
                    "proceeding on the reverse-pause dwell alone", self.key, err)

        if self._last_ref_key and self._last_ref_key != drive_key:
            pause = self._agg_float('reverse_pause_sec', 5.0, aggregate=max, items=items)
            if pause > 0:
                self.logger.info("Bus %s reverse pause %.2fs", self.key, pause)
                time.sleep(pause)

        # The duration is a crash backstop only: the output controller switches the
        # bus off on its own if this thread dies mid-travel. Confirmation-capable
        # outputs anchor it at their ACK, so it never expires early.
        backstop = stage_sec + max(2.0, stage_sec * 0.1)
        driver.relay_on(drive_ref, duration=backstop)
        self._active_drive_ref = drive_ref
        if not driver.wait_confirm([drive_ref], want_on=True):
            self.logger.error("Bus %s relay did not confirm on — aborting stage", self.key)
            driver.relay_off(drive_ref)
            self._active_drive_ref = None
            self._interrupt = True
            return
        self._last_ref_key = drive_key

        started = time.time()
        for item in items:
            item['stage_start'] = started
        elapsed = self._sleep_interruptible(stage_sec)
        for item in items:
            item['driven'] += elapsed
            item['stage_start'] = None

        driver.relay_off(drive_ref)
        # Wait for the bus to actually open before any selector moves — on a radio
        # link the off command is in flight for seconds, and releasing a selector
        # against a still-live bus is exactly the load switching this design avoids.
        if not driver.wait_confirm([drive_ref], want_on=False):
            self.logger.error(
                "Bus %s relay did not confirm off — holding selectors engaged and stopping",
                self.key)
            self._interrupt = True
            return
        self._active_drive_ref = None
        if settle > 0:
            time.sleep(settle)

    def _sleep_interruptible(self, seconds):
        """Sleep up to `seconds`, returning early on interrupt. Returns elapsed."""
        started = time.time()
        while True:
            elapsed = time.time() - started
            if elapsed >= seconds or self._interrupt or self._stopping:
                return min(elapsed, seconds)
            time.sleep(min(TRAVEL_SLICE_SEC, seconds - elapsed))

    def _requeue(self, items):
        """Return unfinished targets to the pending map so the next batch resumes them."""
        with self._req_lock:
            for item in items:
                unique_id = item['member'].unique_id
                if unique_id in self._requests or unique_id in self._stops:
                    continue  # a newer command already supersedes this one
                self._requests[unique_id] = item['target']
        self._wake.set()

    def _release_selectors(self, members):
        for member in members:
            if member.unique_id not in self._engaged:
                continue
            selector_ref = member.selector_ref()
            if selector_ref:
                member.relay_off(selector_ref)
            self._engaged.pop(member.unique_id, None)

    def _release_bus(self):
        if self._active_drive_ref is not None:
            with self._req_lock:
                members = list(self._members.values())
            if members:
                members[0].relay_off(self._active_drive_ref)
            self._active_drive_ref = None
        self._release_selectors(list(self._engaged.values()))

    def _emergency_release(self):
        if self._active_drive_ref is not None:
            with self._req_lock:
                members = list(self._members.values())
            if members:
                members[0].relay_off(self._active_drive_ref)
            self._active_drive_ref = None
        with self._req_lock:
            members = list(self._members.values())
        for member in members:
            if member.in_motion():
                member.finish_motion(member.live_position())
        self._release_selectors(list(self._engaged.values()))

    def _startup_sweep(self):
        """Switch off bus and selector relays left on by a restart during travel."""
        with self._req_lock:
            members = list(self._members.values())
        if not members:
            return
        if not any(member.startup_force_off_enabled() for member in members):
            return

        time.sleep(STARTUP_SWEEP_DELAY_SEC)

        driver = members[0]
        seen = set()
        for member in members:
            refs = [member.selector_ref()]
            open_ref, close_ref = member.raw_bus_refs()
            refs.extend([open_ref, close_ref])
            for ref in refs:
                key = member.ref_key(ref)
                if not key or key in seen:
                    continue
                seen.add(key)
                try:
                    # Only command relays actually reporting on — a redundant off
                    # would activate a toggle-protocol relay rather than leave it be.
                    if driver.relay_reports_on(ref):
                        self.logger.warning(
                            "Startup sweep: %s was still on — switching off", key)
                        driver.relay_off(ref)
                except Exception as err:
                    self.logger.warning("Startup sweep failed for %s: %s", key, err)

    # ── aggregated member settings ───────────────────────────────────────────
    def _members_for(self, items=None):
        if items:
            return [item['member'] for item in items]
        with self._req_lock:
            return list(self._members.values())

    def _agg_float(self, option, default, aggregate=max, items=None):
        values = []
        for member in self._members_for(items):
            try:
                values.append(member.float_option(option, default))
            except Exception:
                continue
        return aggregate(values) if values else default

    def _allow_parallel(self, items):
        # Every participant must permit it — the most conservative wins.
        members = self._members_for(items)
        if not members:
            return False
        return all(member.bool_option('allow_parallel_same_direction', True)
                   for member in members)
