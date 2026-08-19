# coding=utf-8
import copy
import threading
import time

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb

# Canonical definitions live in paired_actuator_common so actuator_paired_bus
# shares them. Re-exported here because existing importers reference them via
# this module.
from aot.outputs.paired_actuator_common import (  # noqa: F401
    ACTUATOR_KIND_OPTIONS,
    KIND_TO_PROFILE_KIND,
)

measurements_dict = {0: {'measurement': 'duty_cycle', 'unit': 'percent'}}
channels_dict = {0: {'types': ['value'], 'measurements': [0]}}

OUTPUT_INFORMATION = {
    'output_name_unique': 'actuator_paired',
    'output_name': "{}: Actuator Paired".format(lazy_gettext('Value')),
    'output_manufacturer': 'AoT',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['value'],

    'message': lazy_gettext(
        'Time-based opening control (0–100%) for vents, curtains, and ball valves. '
        'Connects an Open relay and a Close relay to a single percentage command.'
    ),

    'options_enabled': ['button_send_value'],

    'custom_channel_options': [
        {
            'id': 'actuator_kind',
            'type': 'select',
            'default_value': 'side_vent',
            'required': True,
            'options_select': ACTUATOR_KIND_OPTIONS,
            'name': lazy_gettext('Actuator Kind'),
            'phrase': lazy_gettext('Type of actuator being controlled.'),
        },
        {
            'id': 'output_open_id',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output: Open'),
            'phrase': lazy_gettext('on/off Output channel connected to the OPEN relay.'),
        },
        {
            'id': 'output_close_id',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output: Close'),
            'phrase': lazy_gettext('on/off Output channel connected to the CLOSE relay.'),
        },
        {
            'id': 'travel_time_open_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Travel Time Open (s)'),
            'phrase': lazy_gettext(
                'Seconds to travel from fully closed (0%) to fully open (100%). '
                'If unset, the close travel time is used as a fallback. '
                'Use the Calibration buttons below to measure automatically.'),
        },
        {
            'id': 'travel_time_close_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Travel Time Close (s)'),
            'phrase': lazy_gettext(
                'Seconds to travel from fully open (100%) to fully closed (0%). '
                'If unset, the open travel time is used as a fallback.'),
        },
        {
            'id': 'effective_start_pct',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Open Start Position (%)'),
            'phrase': lazy_gettext(
                'Reference only (informational). Motor position (%) at which the '
                'mechanism visually begins to open. The command value is used as the '
                'motor position directly and is NOT rescaled by this field — '
                'a command of 22% maps directly to motor position 22.'),
        },
        {
            'id': 'effective_end_pct',
            'type': 'float',
            'default_value': 100.0,
            'required': False,
            'name': lazy_gettext('Full Open Position (%)'),
            'phrase': lazy_gettext(
                'Reference only (informational). Motor position (%) regarded as fully '
                'open. The command value is used as the motor position directly and is '
                'NOT capped by this field. A command of 0% always moves to the physical '
                'end-stop (emergency fully-closed).'),
        },
        {
            'id': 'move_step_pct',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Min Move Step (%)'),
            'phrase': lazy_gettext(
                'Motor lifespan protection for automatic environment control. The motor '
                'moves only when the target differs from the last sent position by at least '
                'this much, and commands snap to this grid (e.g. 5% → 0, 5, 10 …). This absorbs '
                'the small per-cycle fluctuations of the PI controller so the motor is not '
                'driven every cycle. Set to 0 to disable — every minor fluctuation then drives '
                'the motor (legacy behavior).'),
        },
        {
            'id': 'last_position_pct',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Last Position (%)'),
            'phrase': lazy_gettext(
                'Last known position. Updated automatically on each move so the value '
                'survives daemon restarts. Edit manually only if you know the actual position.'),
        },
        {
            'id': 'last_target_pct',
            'type': 'float',
            'default_value': -1.0,
            'required': False,
            'name': lazy_gettext('Last Target (%)'),
            'phrase': lazy_gettext(
                'Last manually commanded target position. -1 means not set. '
                'Saved on each manual set command so the target survives daemon restarts.'),
        },
        {
            'id': 'min_command_interval_sec',
            'type': 'float',
            'default_value': 1.0,
            'required': False,
            'name': lazy_gettext('Min Command Interval (s)'),
            'phrase': lazy_gettext(
                'Reject any new Open/Close command that arrives within this many seconds of the '
                'previous one. Prevents queued-up motor whiplash from rapid button presses. '
                'Stop is always accepted regardless of this interval.'),
        },
        {
            'id': 'reverse_pause_sec',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Reverse Pause (s)'),
            'phrase': lazy_gettext(
                'Dwell time inserted when reversing direction (open↔close) to protect the motor. '
                'Both relays stay OFF for this many seconds before the new direction starts.'),
        },
        {
            'id': 'invert_direction',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Invert Direction'),
            'phrase': lazy_gettext(
                'Swap Open and Close relays in software. '
                'Enable when 0% physically deploys the actuator and 100% pulls it back '
                '(e.g. thermal curtain wired with Close = deploy).'),
        },
        {
            'id': 'calib_direction',
            'type': 'select',
            'default_value': 'open',
            'required': False,
            'options_select': [('open', lazy_gettext('Open')), ('close', lazy_gettext('Close'))],
            'name': lazy_gettext('Calibration Direction'),
            'phrase': lazy_gettext(
                'Click Start → actuator moves → click Stop when fully open or closed → '
                'elapsed time is saved to Travel Time Open or Travel Time Close.'),
        },
    ],
    'custom_commands': [
        {
            'id': 'calib_run',
            'type': 'button',
            'name': lazy_gettext('▶ Start Calibration'),
            'phrase': lazy_gettext(
                'Drives the actuator in the selected direction. Click Stop when done.'),
        },
        {
            'id': 'calib_stop',
            'type': 'button',
            'name': lazy_gettext('■ Stop & Save'),
            'phrase': lazy_gettext(
                'Stops the actuator and saves elapsed time to Travel Time Open or Travel Time Close.'),
        },
    ],
}


class OutputModule(AbstractOutput):
    """Time-based opening control for vents, curtains, and ball valves."""

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(
                OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

        try:
            self._position_pct = float(self._opt('last_position_pct') or 0.0)
        except (TypeError, ValueError):
            self._position_pct = 0.0
        self._last_direction = 'idle'
        self._last_direction_change_ts = 0.0
        self._calib_start_ts = 0.0
        self._watchdog_timer = None
        self._last_command_ts = 0.0
        # In-flight motion record so we can compute true position if stopped mid-travel.
        self._motion_start_ts = 0.0
        self._motion_start_pos = 0.0
        self._motion_target = 0.0
        self._motion_dir = 'idle'
        self._motion_run_sec = 0.0
        # Last target value per command source — used by the UI to distinguish
        # user-driven vs system-driven decisions.
        # _user_target_pct is also persisted to the DB (last_target_pct) so it is
        # restored after a daemon restart.
        # -1.0 is the "unset" sentinel.
        try:
            _saved = float(self._opt('last_target_pct') or -1.0)
            self._user_target_pct = _saved if _saved >= 0.0 else None
        except (TypeError, ValueError):
            self._user_target_pct = None
        self._system_target_pct = None   # Last value decided by automation (PID/Trigger, etc.)
        # Last specified target (source-agnostic) — for text/slider display.
        # Tracks the most recent target regardless of whether the user or system issued it.
        # Right after a restart, restore from the DB (last_target_pct) but leave the source unknown (None).
        self._last_target_pct = self._user_target_pct
        self._last_target_source = None

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        # Restore output_states from DB-saved position so the runtime API reflects the
        # correct state immediately after daemon restart, before any new command arrives.
        # setup_output_variables() sets output_states[0]=None; we overwrite it here.
        self.output_states[0] = self._position_pct if self._position_pct > 0 else False
        self.output_setup = True
        self.logger.info(
            "actuator_paired ready — kind=%s open=%s close=%s pos=%.1f%% target=%s",
            self._opt('actuator_kind') or '?',
            self._opt('output_open_id') or '(none)',
            self._opt('output_close_id') or '(none)',
            self._position_pct,
            f"{self._user_target_pct:.1f}%" if self._user_target_pct is not None else "none")

    # ── public ──────────────────────────────────────────────────────────────
    def output_switch(self, state, output_type=None, amount=None, output_channel=0,
                      additional_options=None):
        if state == 'off':
            # Stop: immediately halt whichever relay is running; recompute actual position
            # based on elapsed travel. Always accepted — Stop bypasses rate limit.
            self._cancel_watchdog()
            self._relay_off(self._opt('output_open_id'))
            self._relay_off(self._opt('output_close_id'))
            self._position_pct = self._compute_current_position()
            self._motion_dir = 'idle'
            self._last_direction = 'idle'
            self._last_direction_change_ts = time.time()
            self._last_command_ts = time.time()
            # Publish the actual position (numeric) so the UI displays it.
            # Use False only when fully closed so output_state returns 'off'.
            self.output_states[output_channel] = (
                self._position_pct if self._position_pct > 0 else False)
            measure = copy.deepcopy(measurements_dict)
            measure[0]['value'] = self._position_pct
            add_measurements_influxdb(self.unique_id, measure)
            self._save_position(self._position_pct)
            return

        # Rate-limit Open/Close: reject commands arriving within min_command_interval_sec
        min_interval = max(float(self._opt('min_command_interval_sec') or 0.0), 0.0)
        if min_interval > 0:
            elapsed = time.time() - self._last_command_ts
            if elapsed < min_interval:
                self.logger.info(
                    "Command rejected (rate limit) — %.2fs since last, need %.2fs",
                    elapsed, min_interval)
                return
        self._last_command_ts = time.time()

        # If a motion is already in progress, fold its real-time progress into _position_pct
        # before computing the next move so the delta is accurate.
        if self._motion_dir != 'idle':
            self._position_pct = self._compute_current_position()

        target = float(amount or 0.0)
        target = max(0.0, min(100.0, target))

        # Record the target value per source + track the last specified target (source-agnostic).
        source = (additional_options or {}).get('source', 'system')
        if source == 'manual':
            self._user_target_pct = target
        else:
            self._system_target_pct = target
        # Last specified target — always updated to the latest value regardless of
        # whether the user or system issued it.
        # The text/slider display this value (and its source). Also persisted to the
        # DB for restoration after a restart.
        self._last_target_pct = target
        self._last_target_source = source
        try:
            self._save_option('last_target_pct', round(target, 1))
        except Exception as e:
            self.logger.warning("save last_target_pct failed: %s", e)

        moved = self._drive(target)
        if not moved:
            # _drive returned False because |target - current position| < 0.5.
            # Two sub-cases share this branch and must be handled differently:
            #   (a) motor was idle, already at target → nothing to do.
            #   (b) motor was running and the new target ≈ current live
            #       position → user pressed "stop here". The old code ignored
            #       this and let the motor run on to its ORIGINAL target.
            # Detect (b) via _motion_dir and treat it as a Stop-in-place:
            # cancel watchdog and OFF only the running relay (safe direction).
            if self._motion_dir != 'idle':
                self.logger.info(
                    "Stop-in-place: target %.1f%% ≈ current %.1f%%",
                    target, self._position_pct)
                self._cancel_watchdog()
                running = self._running_relay_id()
                if running:
                    self._relay_off(running)
                self._motion_dir = 'idle'
                self._last_direction = 'idle'
                self._last_direction_change_ts = time.time()
                self._save_position(self._position_pct)
            self.output_states[output_channel] = (
                self._position_pct if self._position_pct > 0 else False)
            measure = copy.deepcopy(measurements_dict)
            measure[0]['value'] = self._position_pct
            add_measurements_influxdb(self.unique_id, measure)
            return

        # Publish the target as the state (numeric for Active, False for fully-closed).
        self.output_states[output_channel] = target if target > 0 else False
        measure = copy.deepcopy(measurements_dict)
        measure[0]['value'] = target
        add_measurements_influxdb(self.unique_id, measure)
        # _position_pct will be set to target by _motion_complete (natural finish) or
        # recomputed from elapsed time if interrupted by Stop / next command.

    def is_on(self, output_channel=0):
        if self.is_setup():
            if output_channel is not None and output_channel in self.output_states:
                # While moving, report the live elapsed-based position so the UI
                # shows progressing % instead of the static target.
                if self._motion_dir != 'idle':
                    live = self._compute_current_position()
                    return live if live > 0 else False
                return self.output_states[output_channel]
            return self.output_states

    def is_setup(self):
        return self.output_setup

    def output_target_pct(self, output_channel=0):
        """Return (last_target_pct, last_target_source) — the last specified target.

        Returns the most recent target and its source
        ('manual' | 'system' | None), regardless of whether the user or system issued it.
        The UI displays this value as text and on the slider thumb.
        """
        return self._last_target_pct, self._last_target_source

    def _running_relay_id(self):
        """Return the relay reference for the direction currently driving, or None.

        Toggle-style protocols flip a relay's state on every command, so a
        redundant OFF sent to an already-off relay activates it. Stop must only
        target the relay we know is running — never blast both directions.
        """
        if self._motion_dir == 'open':
            return self._opt('output_open_id')
        if self._motion_dir == 'close':
            return self._opt('output_close_id')
        # Fall back to _last_direction when motion has just finished but we
        # still need to ensure the relay we last activated is off.
        if self._last_direction == 'open':
            return self._opt('output_open_id')
        if self._last_direction == 'close':
            return self._opt('output_close_id')
        return None

    def stop_output(self):
        self._cancel_watchdog()
        # Only OFF the running direction. The opposite direction must NEVER be
        # touched on stop — under a toggle protocol a redundant OFF on an
        # already-off relay activates it, energizing both directions of an
        # H-bridge motor driver simultaneously (motor damage / short circuit).
        running = self._running_relay_id()
        if running:
            self._relay_off(running)
        self.running = False

    # ── drive ────────────────────────────────────────────────────────────────
    def _get_travel_time(self, direction: str) -> float:
        """Return travel time (s) for the given direction.

        If only one direction is calibrated the other uses it as a fallback.
        Default when neither is set: 60 s.
        """
        t_open  = max(float(self._opt('travel_time_open_sec')  or 0.0), 0.0)
        t_close = max(float(self._opt('travel_time_close_sec') or 0.0), 0.0)
        if direction == 'open':
            return max(t_open or t_close or 60.0, 1.0)
        return max(t_close or t_open or 60.0, 1.0)

    def _apply_effective_range(self, target_pct: float) -> float:
        """Command value IS the motor position (0–100%). Identity, clamped.

        UI consistency decision (user): unify both target and current position to
        'motor coordinates'. A command of 22% is exactly motor position 22%, and
        since the UI's target/current share the same coordinate they match.
        The opening start point (e.g. 10%) is perceived visually by the user, so the
        system does not auto-correct it (no opening-area to motor linear mapping).

        0% always drives to the physical endpoint (fully closed) — preserves the
        user's emergency operation.

        NOTE: the effective_start_pct / effective_end_pct channel options no longer
        transform the motor command (kept only as reference metadata). The former
        linear mapping was removed because it made the target (opening area) and the
        current value (motor) different coordinates, causing confusion such as
        'I set 22% but it only moves 33%'.
        """
        return max(0.0, min(100.0, target_pct))

    def _drive(self, target_pct: float):
        # Command value is the motor position directly (0–100%, clamped).
        target_pct = self._apply_effective_range(target_pct)

        delta = target_pct - self._position_pct
        if abs(delta) < 0.5:
            return False

        _open_id  = self._opt('output_open_id')  or ''
        _close_id = self._opt('output_close_id') or ''
        # invert_direction: swap relay wiring in software
        _invert = bool(self._opt('invert_direction') or False)
        open_id  = _close_id if _invert else _open_id
        close_id = _open_id  if _invert else _close_id

        new_dir  = 'open' if delta > 0 else 'close'
        travel   = self._get_travel_time(new_dir)
        rev_pause = max(float(self._opt('reverse_pause_sec') or 0.0), 0.0)

        primary_id  = open_id  if new_dir == 'open' else close_id
        opposite_id = close_id if new_dir == 'open' else open_id

        # Only touch the opposite relay when actually reversing direction.
        # Some underlying outputs use a toggle protocol where
        # a redundant OFF on an already-off relay can flip it ON.
        if self._last_direction not in ('idle', new_dir):
            self._relay_off(opposite_id)
            # rev_pause is the dwell BETWEEN turning off the running motor and
            # energizing the opposite direction — protects the H-bridge and
            # lets the motor coast to a stop. The previous "waited = since
            # direction change" subtraction is wrong: _last_direction_change_ts
            # is set when the previous motor STARTED, so for a long-running
            # close→open reverse the subtraction made pause = 0 (no dwell at
            # all). Use the full configured pause every time we actually
            # reverse direction.
            if rev_pause > 0:
                self.logger.info(
                    "Reverse pause %.2fs (%s → %s)",
                    rev_pause, self._last_direction, new_dir)
                time.sleep(rev_pause)

        run_sec = (abs(delta) / 100.0) * travel
        start_pos = self._position_pct

        self._relay_on(primary_id, duration=run_sec)

        self._last_direction = new_dir
        self._last_direction_change_ts = time.time()
        # Record motion state for elapsed-based position recovery on Stop.
        self._motion_dir = new_dir
        self._motion_start_ts = time.time()
        self._motion_start_pos = start_pos
        self._motion_target = target_pct
        self._motion_run_sec = run_sec
        self._arm_watchdog(run_sec)
        return True

    def _compute_current_position(self) -> float:
        """Estimate actual actuator position based on elapsed motion time."""
        if self._motion_dir == 'idle' or self._motion_run_sec <= 0:
            return self._position_pct
        travel = self._get_travel_time(self._motion_dir)
        elapsed = max(time.time() - self._motion_start_ts, 0.0)
        # If we have already exceeded the planned run, motion is complete.
        if elapsed >= self._motion_run_sec:
            return self._motion_target
        moved_pct = (elapsed / travel) * 100.0
        sign = 1.0 if self._motion_dir == 'open' else -1.0
        actual = self._motion_start_pos + sign * moved_pct
        return max(0.0, min(100.0, actual))

    def _arm_watchdog(self, run_sec: float):
        self._cancel_watchdog()
        # Safety margin: stop slightly after the expected run time in case the
        # relay's own duration timer was missed (e.g. daemon restart, network blip).
        timeout = max(run_sec + 1.0, 1.5)
        t = threading.Timer(timeout, self._watchdog_fire)
        t.daemon = True
        self._watchdog_timer = t
        t.start()

    def _cancel_watchdog(self):
        t = self._watchdog_timer
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
            self._watchdog_timer = None

    def _watchdog_fire(self):
        """Travel timer expired — motion is finished. Force relays off, finalize state."""
        self.logger.info("Travel time elapsed — motion complete, forcing Stop")
        # Same safety rule as stop_output: only OFF the relay that is running.
        # Touching the opposite (idle) relay can phantom-activate it under
        # toggle protocols and energize both motor directions.
        running = self._running_relay_id()
        if running:
            self._relay_off(running)
        # Snap to target since motion ran the full expected time.
        target = self._motion_target
        self._position_pct = target
        self._motion_dir = 'idle'
        self._last_direction = 'idle'
        self._last_direction_change_ts = time.time()
        self._watchdog_timer = None
        # Update card state + persist so UI reflects completion immediately on next poll.
        try:
            self.output_states[0] = target if target > 0 else False
            measure = copy.deepcopy(measurements_dict)
            measure[0]['value'] = target
            add_measurements_influxdb(self.unique_id, measure)
            self._save_position(target)
        except Exception as e:
            self.logger.warning("watchdog state update failed: %s", e)

    # ── relay helpers ────────────────────────────────────────────────────────
    def _parse_ref(self, ref):
        """Resolve an output reference to (output_id, channel_number).

        The select_channel form type is parsed by the framework into a dict
        {'device_id': ..., 'channel_id': ...} where channel_id is the
        OutputChannel.unique_id. We look up the channel number from the DB.

        Legacy string formats are also accepted **here**:
          - 'output_id'              → (output_id, 0)
          - 'output_id,channel_uid'  → (output_id, looked_up_channel_number)

        ⚠ 저장된 값이 그 형식이어야 한다는 뜻은 아니다. `select_channel` 옵션은
        프레임워크가 **읽을 때** dict 로 파싱하는데, 저장된 값이 출력 UUID 하나뿐
        이면 `{'device_id': None, 'channel_id': None}` 이 되어 여기 오기도 전에
        비어 버린다. 그러면 명령은 성공으로 돌아오는데 릴레이는 돌지 않는다
        (2026-08-19 실측). 저장 형식은 `'출력UUID,채널UUID'` 다.
        """
        if not ref:
            return '', 0

        out_id = ''
        chan_uid = ''

        if isinstance(ref, dict):
            out_id = ref.get('device_id') or ''
            chan_uid = ref.get('channel_id') or ''
        elif isinstance(ref, str):
            if ',' in ref:
                parts = ref.split(',', 1)
                out_id = parts[0]
                chan_uid = parts[1] if len(parts) > 1 else ''
            else:
                out_id = ref
        else:
            return '', 0

        if not out_id:
            return '', 0
        if not chan_uid:
            return out_id, 0
        try:
            ch = db_retrieve_table_daemon(OutputChannel, unique_id=chan_uid)
            ch_num = ch.channel if ch else 0
            self.logger.debug("_parse_ref ref=%r -> out_id=%s ch_uid=%s ch=%s",
                              ref, out_id, chan_uid, ch_num)
            return out_id, ch_num
        except Exception as e:
            self.logger.warning("_parse_ref lookup failed for %s: %s", chan_uid, e)
            return out_id, 0

    def _relay_on(self, output_id, duration: float = 0.0):
        if not output_id:
            return
        out_id, ch_num = self._parse_ref(output_id)
        if not out_id:
            self.logger.warning("relay_on aborted — could not resolve ref %r", output_id)
            return
        self.logger.info("relay_on  ref=%r -> out_id=%s ch=%s dur=%.2f",
                         output_id, out_id, ch_num, duration)
        try:
            from aot.aot_client import DaemonControl
            ctrl = DaemonControl()
            if duration > 0:
                ctrl.output_on(out_id, output_type='sec',
                               amount=duration, output_channel=ch_num)
            else:
                ctrl.output_on(out_id, output_channel=ch_num)
        except Exception as e:
            self.logger.warning("relay_on %s failed: %s", output_id, e)

    def _relay_off(self, output_id):
        if not output_id:
            return
        out_id, ch_num = self._parse_ref(output_id)
        if not out_id:
            self.logger.warning("relay_off aborted — could not resolve ref %r", output_id)
            return
        self.logger.info("relay_off ref=%r -> out_id=%s ch=%s", output_id, out_id, ch_num)
        try:
            from aot.aot_client import DaemonControl
            DaemonControl().output_off(out_id, output_channel=ch_num)
        except Exception as e:
            self.logger.warning("relay_off %s failed: %s", output_id, e)

    # ── calibration ──────────────────────────────────────────────────────────
    def calib_run(self, args_dict=None):
        direction = self._opt('calib_direction') or 'open'
        open_id  = self._opt('output_open_id')  or ''
        close_id = self._opt('output_close_id') or ''
        self._calib_start_ts = time.time()
        if direction == 'open':
            self._relay_off(close_id)
            time.sleep(0.05)
            self._relay_on(open_id)
        else:
            self._relay_off(open_id)
            time.sleep(0.05)
            self._relay_on(close_id)
        self.logger.info("Calibration started — direction=%s", direction)
        return "Running. Click '■ Stop & Save' when fully {}.".format(direction)

    def calib_stop(self, args_dict=None):
        # Calibration only drives one direction (calib_direction). Only OFF
        # that one — opposite was never turned on, so touching it would risk
        # phantom-activating it under toggle protocols.
        direction = self._opt('calib_direction') or 'open'
        calib_id = (self._opt('output_open_id')
                    if direction == 'open'
                    else self._opt('output_close_id'))
        if calib_id:
            self._relay_off(calib_id)
        elapsed = round(time.time() - self._calib_start_ts, 1)
        # Save to the direction-specific field; also update the common fallback
        # field so the output works immediately even if only one direction has
        # been calibrated.
        dir_field = 'travel_time_open_sec' if direction == 'open' else 'travel_time_close_sec'
        try:
            self._save_option(dir_field, elapsed)
        except Exception as e:
            self.logger.warning("calib_stop save failed: %s", e)
            return "Stopped after {:.1f}s but failed to save: {}".format(elapsed, e)
        self.logger.info("Calibration done — %.1fs saved as %s", elapsed, dir_field)
        dir_label = 'Open' if direction == 'open' else 'Close'
        return (
            "Travel Time {} saved as {:.1f} s. "
            "Calibrate the other direction separately if needed. "
            "Reload page to confirm.".format(dir_label, elapsed)
        )

    # ── util ─────────────────────────────────────────────────────────────────
    def _opt(self, key):
        vals = self.options_channels.get(key, [None])
        return vals[0] if vals else None

    def _save_option(self, key, value):
        """Persist a channel option AND refresh the in-memory copy.

        set_custom_channel_option() only writes the database, while
        options_channels was built once in __init__. Without this refresh a
        freshly calibrated travel time stayed invisible to the running module:
        _get_travel_time() kept reading 0, fell back to its 60 s default, and the
        next move drove the motor for that duration instead of the measured one —
        into the end stop. It only looked correct because saving the output form
        reloads the module, which is what the calibration message's "Reload page"
        hint was really working around.
        """
        self.set_custom_channel_option(0, key, value)
        try:
            slot = self.options_channels.get(key)
            if slot is None:
                self.options_channels[key] = {0: value}
            else:
                slot[0] = value
        except Exception as e:
            self.logger.warning("in-memory refresh of '%s' failed: %s", key, e)

    def _save_position(self, position_pct: float):
        # Persist last known position to channel custom_options so it survives daemon restarts.
        try:
            value = round(float(position_pct), 1)
            self._save_option('last_position_pct', value)
        except Exception as e:
            self.logger.warning("save_position failed: %s", e)
