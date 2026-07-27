# coding=utf-8
"""
Shared command-confirmation / latency state machine for outputs.

Historically an output's state flipped the instant a command was *issued* — true
only for synchronous transports (local GPIO/relays). As AoT gained WiFi/MQTT/API
and LoRaWAN outputs, "command sent" stopped meaning "device switched": the ACK
can lag from sub-second to 10s+, and one-way transmitters never confirm at all.

This mixin centralises the confirmation lifecycle so each output no longer hand
-rolls it (as on_off_chirpstack.py used to). An output opts in by:
  - returning True from confirmation_capable()  (it has a device-feedback path)
  - calling begin_command(...) right after it dispatches a command
  - calling confirm_command(...) from its transport when the device reports back
  - implementing _resend_command(...) if it wants in-window retransmission

Two clocks are kept deliberately separate:
  1) optimistic display window  -> anchored at dispatch (command_timeout_s long)
  2) actual runtime clock       -> anchored at the device response (ACK), so the
     dispatch->ACK latency never inflates the reported on-duration.

Synchronous outputs never call begin_command and are completely unaffected
(confirmation_capable() stays False, is_pending() stays False, no timers arm).
"""
import threading
from datetime import timedelta

from aot.utils.time_utils import utc_now

# System default optimistic window (seconds) applied to a confirmation-capable
# output when the user leaves 'command_timeout_s' unset. Wired/synchronous
# outputs use 0 (immediate) and never reach this path.
DEFAULT_COMMAND_TIMEOUT_S = 8.0

# Lower bound for a single retransmission interval, so a small timeout does not
# spin the resend timer too tightly.
_MIN_RESEND_INTERVAL_S = 2.0


class ConfirmableOutputMixin:
    """Generic pending/confirm/timeout machinery for latency-aware outputs."""

    # ------------------------------------------------------------------ #
    # State init (called from AbstractOutput.__init__)
    # ------------------------------------------------------------------ #
    def _confirm_init(self):
        # ch -> {'seq','intent','prev','deadline','resends','dispatched_at'}
        self._cmd_pending = {}
        # ch -> {'state': bool, 'ts': datetime, 'source': str}
        self._cmd_confirmed = {}
        # ch -> datetime the last unconfirmed command gave up (fault marker)
        self._cmd_fault_at = {}
        # ch -> duration seconds whose auto-off is deferred until the device
        # confirms ON (guarantees >= N seconds of confirmed-on runtime).
        self._cmd_duration = {}
        # True once ANY device confirmation has ever been seen for this output.
        self._confirm_seen = False
        # Channels currently deemed offline (a command gave up unconfirmed and the
        # device has not reported back since). Commands to an offline channel are
        # single-shot probes — no retransmission storm, no fail-safe off — while
        # still going out once so a recovered device can re-confirm.
        self._offline = set()
        # ch -> monotonic command sequence (stale-timer guard)
        self._cmd_seq = {}
        self._confirm_lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Hooks — modules may override
    # ------------------------------------------------------------------ #
    def confirmation_capable(self):
        """True if this output has a device-feedback channel (ACK/echo/re-query).

        When False, begin_command() still shows an optimistic window but never
        faults or reverts (there is nothing that could confirm), matching a
        fire-and-forget transmitter.
        """
        return False

    def supports_device_duration(self):
        """True if the device runs a timed action itself (the duration is carried
        in the command payload), making the on-time immune to link latency.

        Preferred over server-side timing when available: output_on_off passes
        the duration straight to the device and arms NO server auto-off. Default
        False -> the server owns the timing (confirm-anchored when capable).
        """
        return False

    def command_timeout_s(self, output_channel=0):
        """User-configured optimistic/confirmation window in seconds.

        Read from the common 'command_timeout_s' custom option. 0/unset => the
        output is treated as immediate (no pending window). A confirmation
        -capable output with the option unset falls back to the system default.
        """
        raw = None
        try:
            raw = self.get_custom_option('command_timeout_s')
        except Exception:
            raw = None
        # Legacy alias: chirpstack shipped 'ack_timeout_s' before unification.
        if raw in (None, ''):
            try:
                raw = self.get_custom_option('ack_timeout_s')
            except Exception:
                raw = None
        if raw in (None, ''):
            # Unset. A non-capable output (no feedback channel — e.g. an MQTT
            # output with no status topic) stays at 0 (immediate, no phantom
            # pending window). A capable output falls back to the module's
            # declared default (matches the form pre-fill), then the system default.
            if not self.confirmation_capable():
                return 0.0
            try:
                mod_default = (self.OUTPUT_INFORMATION or {}).get('command_timeout_default_s')
            except Exception:
                mod_default = None
            if mod_default not in (None, ''):
                try:
                    return max(0.0, float(mod_default))
                except Exception:
                    pass
            return DEFAULT_COMMAND_TIMEOUT_S
        try:
            val = float(raw)
        except Exception:
            return DEFAULT_COMMAND_TIMEOUT_S if self.confirmation_capable() else 0.0
        return max(0.0, val)

    def _resend_command(self, output_channel, intent_state):
        """Optional in-window retransmission of the same command (idempotent).

        Default: no retransmission. Modules with a lossy link (e.g. LoRaWAN)
        override to re-dispatch, returning truthy on a successful enqueue.
        """
        return False

    def _notify_command_fault(self, output_channel, intent_state):
        """Surface a command that gave up unconfirmed.

        Default: log at ERROR (always persisted). The state is also exposed via
        output_state() -> 'fault' for widgets to render. A pushed system-wide
        toast is layered on in the widget-unification phase.
        """
        try:
            self.logger.error(
                f"[confirm] Output {self.unique_id} CH{output_channel} command "
                f"'{intent_state}' was not confirmed by the device within the "
                f"timeout; reverting to the prior state.")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Core machinery
    # ------------------------------------------------------------------ #
    def begin_command(self, output_channel, intent_state, prev_state, dispatched_ok=True):
        """Record intent and arm the optimistic window after a dispatch.

        :param intent_state: 'on' or 'off'
        :param prev_state: bool state before this command (for revert on fault)
        :param dispatched_ok: whether the transport accepted the command. If
            False, nothing is armed and no optimistic flip happens — the caller
            must keep the prior state (no phantom 'on' on a failed send).
        """
        if not dispatched_ok:
            return

        want_on = (intent_state == 'on')
        with self._confirm_lock:
            # A new command clears any stale fault marker for this channel.
            self._cmd_fault_at.pop(output_channel, None)

            # Optimistic display state reflects the click immediately.
            self.output_states[output_channel] = want_on

            timeout = self.command_timeout_s(output_channel)
            if timeout <= 0:
                # Immediate/synchronous: no window, state is already authoritative.
                self._cmd_pending.pop(output_channel, None)
                return

            seq = self._cmd_seq.get(output_channel, 0) + 1
            self._cmd_seq[output_channel] = seq
            now = utc_now()
            # A channel already known-offline sends this command as a single-shot
            # probe (no retransmission, no fail-safe off) — just enough to detect
            # recovery without flooding an unreachable device every cycle.
            probe = output_channel in self._offline
            self._cmd_pending[output_channel] = {
                'seq': seq,
                'intent': intent_state,
                'prev': bool(prev_state),
                'deadline': now.timestamp() + timeout,
                'resends': 0,
                'dispatched_at': now,
                'probe': probe,
            }

        # Arm resend + expiry timer outside the lock. A capable, online channel
        # retransmits on the tick interval; a probe (offline) or a fire-and-forget
        # output ticks once at the deadline (no resend).
        if self.confirmation_capable() and not probe:
            interval = max(_MIN_RESEND_INTERVAL_S, timeout / 3.0)
        else:
            interval = timeout
        self._arm_confirm_timer(output_channel, seq, interval)

    def _arm_confirm_timer(self, output_channel, seq, interval):
        # Cap the delay to the remaining time-to-deadline so expiry (fault/revert)
        # is never late even when the resend interval exceeds a short timeout.
        try:
            with self._confirm_lock:
                p = self._cmd_pending.get(output_channel)
                if not p or p.get('seq') != seq:
                    return
                remaining = p.get('deadline', 0) - utc_now().timestamp()
            delay = interval if remaining > interval else max(0.0, remaining)
            t = threading.Timer(
                max(0.2, delay),
                self._confirm_tick, args=(output_channel, seq, interval))
            t.daemon = True
            t.start()
        except Exception:
            pass

    def _confirm_tick(self, output_channel, seq, interval):
        """Timer callback: resend until confirmed, fault/settle at the deadline."""
        with self._confirm_lock:
            p = self._cmd_pending.get(output_channel)
            # Confirmed (pending cleared) or superseded by a newer command.
            if not p or p.get('seq') != seq:
                return
            now_ts = utc_now().timestamp()
            expired = now_ts >= p.get('deadline', 0)
            capable = self.confirmation_capable()

            if expired:
                intent = p.get('intent')
                prev = p.get('prev', False)
                self._cmd_pending.pop(output_channel, None)
                had_duration = self._cmd_duration.pop(output_channel, None) is not None
                was_probe = bool(p.get('probe'))
                if capable:
                    # Never confirmed within the window -> treat as command loss.
                    # Revert the optimistic state and mark a fault. The transport
                    # listener stays live: a late confirm_command() can still flip
                    # this back to on and re-anchor the runtime clock.
                    self.output_states[output_channel] = bool(prev)
                    self._cmd_fault_at[output_channel] = utc_now()
                    # Mark the channel offline so subsequent commands go out as
                    # single-shot probes instead of retransmitting to a dead link.
                    self._offline.add(output_channel)
                    fault_intent = intent
                else:
                    # Fire-and-forget: nothing can confirm; keep optimistic state.
                    fault_intent = None
                # Notify outside the lock.
                if fault_intent is not None:
                    threading.Thread(
                        target=self._notify_command_fault,
                        args=(output_channel, fault_intent),
                        daemon=True).start()
                # Fail-safe: a timed ON that was never confirmed may still have
                # physically taken effect (ACK lost, not the command), and its
                # auto-off was deferred to a confirm that never came. Send OFF so
                # nothing is left running unattended (e.g. a valve stuck open).
                # Skip it for a probe: the device was already known offline, so the
                # ON almost certainly never landed and an OFF would just be more
                # wasted traffic to a dead link.
                if capable and had_duration and intent == 'on' and not was_probe:
                    threading.Thread(
                        target=self._failsafe_off,
                        args=(output_channel,),
                        daemon=True).start()
                return

            # Not expired and capable, non-probe -> resend the same command.
            do_resend = capable and not p.get('probe')
            if do_resend:
                p['resends'] += 1
                intent = p.get('intent')

        # Resend + re-arm outside the lock.
        if do_resend:
            try:
                self._resend_command(output_channel, intent)
            except Exception:
                pass
            self._arm_confirm_timer(output_channel, seq, interval)

    def defer_duration_to_confirm(self, output_channel, amount):
        """Arm a timed ON's auto-off relative to the device-confirmed ON.

        Called by output_on_off for a confirmation-capable output receiving an
        ON with a duration. Guarantees >= N seconds of *confirmed* on-time:
          - async confirmer (still pending after dispatch, e.g. LoRaWAN): defer;
            confirm_command() arms output_on_until at confirm_time + N.
          - synchronous confirmer (already confirmed during dispatch, e.g. an
            HTTP POST / RPC that returns applied): arm now (= confirm time).
        """
        try:
            amt = abs(float(amount))
            if self.is_pending(output_channel):
                # Confirmation still outstanding — arm at confirm time. Prevent the
                # controller loop from firing a premature off meanwhile.
                self._cmd_duration[output_channel] = amt
                self.output_on_until[output_channel] = None
            else:
                # Already confirmed synchronously during dispatch — arm from now.
                now = utc_now()
                self._cmd_duration.pop(output_channel, None)
                self.output_on_until[output_channel] = now + timedelta(seconds=amt)
                self.output_last_duration[output_channel] = amt
                self.output_on_duration[output_channel] = True
                self.output_off_triggered[output_channel] = False
                self.output_session_start[output_channel] = now
                self.output_session_max[output_channel] = amt
        except Exception:
            pass

    def confirm_command(self, output_channel, actual_state, source='device'):
        """Record an authoritative device report and resolve any pending command.

        Safe to call at any time, including AFTER the window elapsed (a late ACK):
        it clears the fault, sets the confirmed state, and re-anchors the runtime
        clock (output_started_at / time_turned_on) to this moment.
        """
        want_on = bool(actual_state)
        with self._confirm_lock:
            self._confirm_seen = True
            self._cmd_confirmed[output_channel] = {
                'state': want_on,
                'ts': utc_now(),
                'source': source,
            }
            self._cmd_pending.pop(output_channel, None)
            self._cmd_fault_at.pop(output_channel, None)
            # Device reported back -> it is online again; resume normal (retrying)
            # command delivery.
            self._offline.discard(output_channel)
            self.output_states[output_channel] = want_on
            duration = self._cmd_duration.pop(output_channel, None) if want_on else None
            if not want_on:
                # An OFF confirmation cancels any deferred duration.
                self._cmd_duration.pop(output_channel, None)

        # Anchor the *actual runtime clock* to the response, not the dispatch.
        try:
            if want_on:
                now = utc_now()
                self.output_time_turned_on[output_channel] = now
                # Allow the (previously deferred) start marker to be written now.
                if hasattr(self, '_started_at_written'):
                    self._started_at_written[output_channel] = False
                self._ensure_started_marked(output_channel)
                # Arm the deferred auto-off from the confirmed-on moment so the
                # runtime is >= N seconds (the output controller loop turns it
                # off once output_on_until passes).
                if duration is not None:
                    self.output_on_until[output_channel] = now + timedelta(seconds=duration)
                    self.output_last_duration[output_channel] = duration
                    self.output_on_duration[output_channel] = True
                    self.output_off_triggered[output_channel] = False
                    self.output_session_start[output_channel] = now
                    self.output_session_max[output_channel] = duration
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # State resolution helpers (used by the module's is_on / base output_state)
    # ------------------------------------------------------------------ #
    def _failsafe_off(self, output_channel):
        """Best-effort OFF after a timed ON gave up unconfirmed (see _confirm_tick).
        Routes through output_switch so the OFF itself is retried/confirmed."""
        try:
            self.output_switch('off', output_channel=output_channel)
            self.logger.warning(
                f"[confirm] Output {self.unique_id} CH{output_channel} fail-safe "
                f"OFF sent after an unconfirmed timed ON.")
        except Exception:
            pass

    def pending_intent(self, output_channel=0):
        """Intended state ('on'/'off') of the in-flight command, or None."""
        try:
            p = self._cmd_pending.get(output_channel)
            return p.get('intent') if p else None
        except Exception:
            return None

    def is_pending(self, output_channel=0):
        try:
            p = self._cmd_pending.get(output_channel)
            if not p:
                return False
            return utc_now().timestamp() < p.get('deadline', 0)
        except Exception:
            return False

    def is_offline(self, output_channel=0):
        """True if this channel is currently treated as offline (a command gave
        up unconfirmed and the device has not reported back since). Commands to it
        go out as single-shot probes."""
        try:
            return output_channel in self._offline
        except Exception:
            return False

    def is_fault(self, output_channel=0):
        # Fault persists until the next command (begin_command) or a device
        # report (confirm_command) clears it — NOT on a timer. A device that
        # never confirms (e.g. an offline LoRaWAN valve driven by a sequence)
        # must keep reading 'fault', never silently revert to a stale optimistic
        # on/off that misrepresents an offline device as working.
        try:
            if self.is_pending(output_channel):
                return False
            return output_channel in self._cmd_fault_at
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # AbstractBaseController.comm_* interface (protocol-agnostic status)
    # ------------------------------------------------------------------ #
    def comm_capable(self):
        """Delegates to confirmation_capable(); also True if a shared link
        object (see comm_is_fault) is attached, even without command-level
        confirmation wired up."""
        if self.confirmation_capable():
            return True
        return getattr(self, '_shared_link', None) is not None

    def comm_is_pending(self, output_channel=0):
        return self.is_pending(output_channel)

    def comm_is_fault(self, output_channel=0):
        """OR-composition of three independent axes:
          - offline axis: the channel is known offline and has NOT reported back
            since. Deliberately outranks a command in flight: issuing a command
            to a device already known to be dead must not make it look healthy
            again for the length of the confirmation window. _offline is only
            cleared by confirm_command(), i.e. by the device actually answering,
            so this reads as "offline until online is confirmed".
          - command axis: the last dispatched command was never confirmed (is_fault)
          - link axis: a persistent shared connection (e.g. one PLC/gateway backing
            several channels) is currently known down, even with no command in
            flight — see aot/outputs/base_output.py for why this must be
            reachable from output_state() and io_link_health_infra_plan.md 2.2
            for why it is a separate axis from is_fault().

        A driver opts into the link axis by setting self._shared_link to an
        object exposing is_healthy() -> bool (e.g. a shared Modbus/TCP client
        keyed by host:port, so all channels on that link report the same fault).
        """
        if self.is_offline(output_channel):
            return True
        if self.is_fault(output_channel):
            return True
        link = getattr(self, '_shared_link', None)
        if link is not None:
            try:
                return not link.is_healthy()
            except Exception:
                return False
        return False

    def resolve_is_on(self, output_channel, optimistic):
        """Resolve the boolean on-state for a confirmation-aware output.

        - within the optimistic window: report the intended state (responsive UI)
        - otherwise, once the device has ever confirmed: trust the confirmed state
        - else: fall back to the caller's optimistic value
        """
        try:
            p = self._cmd_pending.get(output_channel)
            if p and utc_now().timestamp() < p.get('deadline', 0):
                return p.get('intent') == 'on'
            c = self._cmd_confirmed.get(output_channel)
            if c is not None:
                return bool(c.get('state'))
            return bool(optimistic)
        except Exception:
            return bool(optimistic)

    def confirmation_deferred_start(self, output_channel=0):
        """True if the runtime start-marker should be deferred to confirm time.

        Used by _ensure_started_marked to skip writing output_started_at at
        dispatch for a confirmation-capable output that has not yet confirmed
        the current ON — the mark is written from confirm_command() instead.
        """
        try:
            if not self.confirmation_capable():
                return False
            c = self._cmd_confirmed.get(output_channel)
            # If already confirmed on, do not defer (let the normal mark proceed).
            if c is not None and c.get('state'):
                return False
            return True
        except Exception:
            return False
