# coding=utf-8
"""Bus-shared paired actuator — several actuators behind one Open/Close relay pair.

``actuator_paired`` assumes every actuator owns its Open and Close relays. A
common greenhouse side-vent panel is wired the other way round: one Open relay
and one Close relay form a *shared bus*, and a per-window *selector* relay
decides which motor that bus is currently connected to. A 6-channel relay board
then drives four windows (CH1 open bus, CH2 close bus, CH3–CH6 selectors)
instead of the three a dedicated-pair layout allows.

One Output = one actuator, exactly like ``actuator_paired`` — the environment
coordinator keys a control profile by Output id, so folding several windows into
one multi-channel Output would leave all but one of them outside automatic
control. Instances that name the same Open/Close pair discover each other
through a process-wide bus registry and are scheduled against one another.

Switching discipline
--------------------
Selector contacts must never make or break while the bus is energized, or they
arc. Every stage therefore runs:

    selector ON -> confirm -> bus ON -> travel -> bus OFF -> confirm -> selector OFF

Both confirmations go through the transport-agnostic ``output_state()``, which
returns ``'on' | 'off' | 'pending' | 'fault'``. A local GPIO relay confirms on
the first poll; a LoRaWAN relay confirms when its uplink ACK arrives (see
``aot/outputs/confirmable_output.py``). No transport-specific logic lives here.

Parallel driving and staging
----------------------------
When the bus can carry several motors at once (``allow_parallel_same_direction``),
actuators energizing the same relay run together. Different targets mean
different run times, and a selector cannot be dropped mid-travel, so a batch is
split into *stages*: the bus runs for the shortest outstanding time, goes off,
finished selectors are released, and the bus restarts for the remainder. Every
contact change still happens with the bus de-energized.

Targets at a physical end stop (0% or 100%) are exempt: with ``end_stop_overrun``
enabled the limit switch absorbs the extra seconds, so those actuators take the
group's longest run time and merge into a single stage. An emergency close of
every window is therefore one bus run, not one per window.
"""
import time

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.outputs.paired_actuator_common import ACTUATOR_KIND_OPTIONS
# The bus scheduler MUST come from a normally-imported module: output modules
# are loaded per-Output via load_module_from_file(), so anything declared here
# would be private to each window instead of shared across the bus.
from aot.outputs.paired_actuator_bus_scheduler import (
    _Bus, get_bus, drop_member)  # noqa: F401
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb

# Position deltas below this (percent) are treated as "already there".
POSITION_EPSILON = 0.5
# Poll period while waiting for a relay to confirm its new state.
CONFIRM_POLL_SEC = 0.2

measurements_dict = {0: {'measurement': 'duty_cycle', 'unit': 'percent'}}
channels_dict = {0: {'types': ['value'], 'measurements': [0]}}



# ─────────────────────────────────────────────────────────────────────────────
# Output module
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_INFORMATION = {
    'output_name_unique': 'actuator_paired_bus',
    'output_name': "{}: Actuator Paired (Shared Bus)".format(lazy_gettext('Value')),
    'output_manufacturer': 'AoT',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['value'],

    'message': lazy_gettext(
        'Time-based opening control (0–100%) for a vent, curtain or valve whose Open and '
        'Close relays are SHARED with other actuators, each picked by its own selector '
        'relay — so a 6-channel relay board drives four windows. Add one of these outputs '
        'per actuator, give them the same Open/Close channels, and they schedule against '
        'each other automatically. Selector contacts are only ever switched while the '
        'shared bus is de-energized. Use "Actuator Paired" instead when the actuator has '
        'its own dedicated Open/Close relays.'),

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
            'id': 'selector_output_id',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output: Selector'),
            'phrase': lazy_gettext(
                'on/off Output channel that connects the shared bus to THIS actuator. It is '
                'switched on before the bus starts and off after the bus stops, never under '
                'load. Leave empty only if this actuator has the bus to itself.'),
        },
        {
            'id': 'output_open_id',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output: Open (shared bus)'),
            'phrase': lazy_gettext(
                'on/off Output channel connected to the OPEN relay. Every actuator naming '
                'the same Open and Close channels shares one bus and is scheduled against '
                'the others.'),
        },
        {
            'id': 'output_close_id',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output: Close (shared bus)'),
            'phrase': lazy_gettext(
                'on/off Output channel connected to the CLOSE relay. Every actuator naming '
                'the same Open and Close channels shares one bus and is scheduled against '
                'the others.'),
        },
        {
            'id': 'travel_time_open_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Travel Time Open (s)'),
            'phrase': lazy_gettext(
                'Seconds to travel from fully closed (0%) to fully open (100%). If unset, the '
                'close travel time is used as a fallback. Use the Calibration buttons below '
                'to measure automatically.'),
        },
        {
            'id': 'travel_time_close_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Travel Time Close (s)'),
            'phrase': lazy_gettext(
                'Seconds to travel from fully open (100%) to fully closed (0%). If unset, the '
                'open travel time is used as a fallback.'),
        },
        {
            'id': 'end_stop_overrun',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Limit Switch Fitted'),
            'phrase': lazy_gettext(
                # Wording note: keep '%' away from a following space+letter such as
                # "0% or" — Babel reads "% o" as a python-format conversion, flags the
                # message python-format, and then rejects every translation that has no
                # matching placeholder ("placeholders are incompatible" at compile time).
                'Enable when this actuator has limit switches at both ends. An end-stop '
                'target (0%, 100%) may then be driven longer than its calculated travel '
                'time, letting several actuators reach their end stop in a single bus run '
                '— an emergency close of every window finishes in one run instead of one '
                'per window. Disable when there is no limit switch, or the motor would '
                'stall.'),
        },
        {
            'id': 'allow_parallel_same_direction',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Allow Parallel Driving'),
            'phrase': lazy_gettext(
                'Let this actuator move at the same time as others on the same bus, when they '
                'are driving the same relay. Enable only if the bus and its supply can carry '
                'all of those motors at once. Opposite directions are never run together '
                'regardless of this setting. If any actuator on a bus disables this, the whole '
                'bus moves one actuator at a time.'),
        },
        {
            'id': 'batch_window_sec',
            'type': 'float',
            'default_value': 2.0,
            'required': False,
            'name': lazy_gettext('Batch Window (s)'),
            'phrase': lazy_gettext(
                'Commands arriving within this window are planned together, so a control '
                'cycle that targets every actuator on the bus becomes one batch instead of a '
                'queue of separate moves.'),
        },
        {
            'id': 'selector_settle_sec',
            'type': 'float',
            'default_value': 0.5,
            'required': False,
            'name': lazy_gettext('Selector Settle Time (s)'),
            'phrase': lazy_gettext(
                'Dwell between a selector relay changing and the shared bus being energized '
                '(and again after the bus stops, before the selector is released), so the '
                'contacts never switch under load.'),
        },
        {
            'id': 'confirm_timeout_sec',
            'type': 'float',
            'default_value': 15.0,
            'required': False,
            'name': lazy_gettext('Relay Confirm Timeout (s)'),
            'phrase': lazy_gettext(
                'How long to wait for a selector or bus relay to report its new state before '
                'giving up on this actuator. Wired relays confirm immediately; radio-linked '
                'relays confirm when the device acknowledges. The bus is never energized '
                'against an unconfirmed selector.'),
        },
        {
            'id': 'reverse_pause_sec',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Reverse Pause (s)'),
            'phrase': lazy_gettext(
                'Dwell inserted when the shared bus changes direction (open↔close) to protect '
                'the motors. Both bus relays stay off for this long before the new direction '
                'starts.'),
        },
        {
            'id': 'startup_force_off',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Force Relays Off At Startup'),
            'phrase': lazy_gettext(
                'After the daemon starts, switch off any selector or bus relay still reporting '
                'on — a restart during travel would otherwise leave a motor running. Only '
                'relays actually reporting on are commanded, so toggle-protocol outputs are '
                'not phantom-activated.'),
        },
        {
            'id': 'effective_start_pct',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Open Start Position (%)'),
            'phrase': lazy_gettext(
                'Reference only (informational). Motor position (%) at which the mechanism '
                'visually begins to open. The command value is used as the motor position '
                'directly and is NOT rescaled by this field.'),
        },
        {
            'id': 'effective_end_pct',
            'type': 'float',
            'default_value': 100.0,
            'required': False,
            'name': lazy_gettext('Full Open Position (%)'),
            'phrase': lazy_gettext(
                # See the Babel wording note on 'Limit Switch Fitted': "0% always" would
                # read as the "% a" conversion, so phrase it "0% moves … regardless".
                'Reference only (informational). Motor position (%) regarded as fully open. '
                'The command value is NOT capped by this field. A command of 0% moves to the '
                'physical end stop regardless (emergency fully-closed).'),
        },
        {
            'id': 'move_step_pct',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Min Move Step (%)'),
            'phrase': lazy_gettext(
                'Motor lifespan protection for automatic environment control. The motor moves '
                'only when the target differs from the last sent position by at least this '
                'much, and commands snap to this grid (e.g. 5% → 0, 5, 10 …). Set to 0 to '
                'disable — every minor fluctuation then drives the motor.'),
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
                'Last manually commanded target position. -1 means not set. Saved on each '
                'manual set command so the target survives daemon restarts.'),
        },
        {
            'id': 'min_command_interval_sec',
            'type': 'float',
            'default_value': 1.0,
            'required': False,
            'name': lazy_gettext('Min Command Interval (s)'),
            'phrase': lazy_gettext(
                'Reject any new target arriving within this many seconds of the previous one. '
                'Prevents queued-up motor whiplash from rapid button presses. Stop is always '
                'accepted regardless of this interval.'),
        },
        {
            'id': 'invert_direction',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Invert Direction'),
            'phrase': lazy_gettext(
                'Swap the Open and Close relays in software. Enable when 0% physically deploys '
                'the actuator and 100% pulls it back. An inverted actuator is never driven in '
                'parallel with a non-inverted one, because they energize opposite relays.'),
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
                'Engages this actuator\'s selector and drives it in the selected direction. '
                'Refused while the shared bus is busy. Click Stop when done.'),
        },
        {
            'id': 'calib_stop',
            'type': 'button',
            'name': lazy_gettext('■ Stop & Save'),
            'phrase': lazy_gettext(
                'Stops the bus, releases the selector and saves the elapsed time to Travel '
                'Time Open or Travel Time Close.'),
        },
    ],
}


class OutputModule(AbstractOutput):
    """One actuator on a shared Open/Close bus, positioned by travel time."""

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.options_channels = {}
        self._bus = None
        self._position_pct = 0.0
        self._motion = None
        self._last_command_ts = 0.0
        self._calib_start_ts = 0.0
        self._calib_drive_ref = None
        self._user_target_pct = None
        self._system_target_pct = None
        self._last_target_pct = None
        self._last_target_source = None

        if testing:
            return

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(
                OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels) or {}

        self._position_pct = self.float_option('last_position_pct', 0.0)
        saved_target = self.float_option('last_target_pct', -1.0)
        self._user_target_pct = saved_target if saved_target >= 0.0 else None
        # Source is unknown after a restart — the value was restored, not issued.
        self._last_target_pct = self._user_target_pct

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        # Reflect the restored position immediately, before any command arrives.
        self.output_states[0] = self._position_pct if self._position_pct > 0 else False
        self.output_setup = True

        self._bus = get_bus(self.bus_key())
        self._bus.attach(self)

        self.logger.info(
            "actuator_paired_bus ready — kind=%s selector=%s bus=%s pos=%.1f%%",
            self.opt('actuator_kind') or '?',
            self.ref_key(self.selector_ref()) or '(none)',
            self.bus_key() or '(none)',
            self._position_pct)

    # ── public API ───────────────────────────────────────────────────────────
    def output_switch(self, state, output_type=None, amount=None, output_channel=0,
                      additional_options=None):
        if self._bus is None:
            self.logger.warning("Command ignored — output is not attached to a bus yet")
            return

        if state == 'off':
            # Stop: halt this actuator where it is. Always accepted — Stop bypasses
            # the rate limit.
            self._last_command_ts = time.time()
            self._bus.request_stop(self)
            return

        interval = max(self.float_option('min_command_interval_sec', 1.0), 0.0)
        if interval > 0:
            elapsed = time.time() - self._last_command_ts
            if elapsed < interval:
                self.logger.info(
                    "Command rejected (rate limit) — %.2fs since last, need %.2fs",
                    elapsed, interval)
                return
        self._last_command_ts = time.time()

        target = max(0.0, min(100.0, float(amount or 0.0)))

        source = (additional_options or {}).get('source', 'system')
        if source == 'manual':
            self._user_target_pct = target
        else:
            self._system_target_pct = target
        self._last_target_pct = target
        self._last_target_source = source
        try:
            self.save_option('last_target_pct', round(target, 1))
        except Exception as err:
            self.logger.warning("save last_target_pct failed: %s", err)

        self._bus.submit(self, target)

    def is_on(self, output_channel=0):
        if not self.is_setup():
            return None
        if output_channel is None or output_channel not in self.output_states:
            return self.output_states
        if self._motion is not None:
            live = self.live_position()
            return live if live > 0 else False
        return self.output_states[output_channel]

    def is_setup(self):
        return self.output_setup

    def output_target_pct(self, output_channel=0):
        """Return (last_target_pct, last_target_source) — the last specified target."""
        return self._last_target_pct, self._last_target_source

    def stop_output(self):
        if self._bus is not None:
            try:
                drop_member(self)
            except Exception:
                self.logger.exception("Failed to detach from bus")
            self._bus = None
        self.running = False

    # ── planning / motion (called by the bus worker) ─────────────────────────
    def plan_move(self, target):
        raw_open, raw_close = self.raw_bus_refs()
        if not self.ref_key(raw_open) and not self.ref_key(raw_close):
            self.logger.warning("No Open/Close bus configured — ignoring target")
            return None

        current = self.live_position()
        delta = target - current
        if abs(delta) < POSITION_EPSILON:
            return None

        direction = 'open' if delta > 0 else 'close'
        open_ref, close_ref = self.bus_refs()
        drive_ref = open_ref if delta > 0 else close_ref
        if not self.ref_key(drive_ref):
            self.logger.warning("No %s relay configured — ignoring target", direction)
            return None

        travel = self.travel_time(direction)
        selector_ref = self.selector_ref()

        return {
            'member': self,
            'target': target,
            'start_pos': current,
            'direction': direction,
            'travel': travel,
            'run_sec': (abs(delta) / 100.0) * travel,
            'eff_sec': (abs(delta) / 100.0) * travel,
            'driven': 0.0,
            'stage_start': None,
            'selector_ref': selector_ref,
            'drive_ref': drive_ref,
            # Grouping is by the relay actually energized, not the logical direction:
            # an inverted actuator's "open" drives the physical close relay and must
            # never share a stage with a non-inverted actuator's "open".
            'drive_key': self.ref_key(drive_ref),
            'is_end_stop': target <= 0.0 or target >= 100.0,
            'end_overrun': self.bool_option('end_stop_overrun', True),
        }

    def begin_motion(self, item):
        self._motion = item

    def in_motion(self):
        return self._motion is not None

    def live_position(self):
        item = self._motion
        if item is None:
            return self._position_pct
        driven = item['driven']
        if item['stage_start'] is not None:
            driven += max(time.time() - item['stage_start'], 0.0)
        # Only an end-stop target may be driven past its calculated travel time.
        if not (item['is_end_stop'] and item['end_overrun']):
            driven = min(driven, item['run_sec'])
        moved = (driven / item['travel']) * 100.0
        sign = 1.0 if item['direction'] == 'open' else -1.0
        return max(0.0, min(100.0, item['start_pos'] + sign * moved))

    def finish_motion(self, position):
        self._motion = None
        self._position_pct = position
        self.output_states[0] = position if position > 0 else False
        try:
            measurement = dict(measurements_dict[0])
            measurement['value'] = position
            add_measurements_influxdb(self.unique_id, {0: measurement})
        except Exception as err:
            self.logger.warning("measurement write failed: %s", err)
        try:
            self.save_option('last_position_pct', round(position, 1))
        except Exception as err:
            self.logger.warning("save last_position_pct failed: %s", err)

    def output_label(self):
        try:
            return '{} ({})'.format(self.output.name, self.unique_id[:8])
        except Exception:
            return str(self.unique_id)

    # ── relay helpers (called by the bus worker) ─────────────────────────────
    def wait_confirm(self, refs, want_on):
        """Poll refs until each reports the wanted state. True when all confirmed.

        Transport-agnostic: output_state() is 'on'/'off' immediately for a wired
        relay, and only after the device acknowledges for a radio-linked one.
        """
        timeout = max(self.float_option('confirm_timeout_sec', 15.0), 0.0)
        pending = {}
        for ref in refs:
            key = self.ref_key(ref)
            if key:
                pending[key] = ref
        if not pending:
            return True
        if timeout <= 0:
            return True

        try:
            from aot.aot_client import DaemonControl
            control = DaemonControl()
        except Exception as err:
            self.logger.warning("Cannot reach daemon to confirm relays: %s", err)
            return True

        deadline = time.time() + timeout
        while pending and time.time() < deadline:
            for key, ref in list(pending.items()):
                output_id, channel_number = self.parse_ref(ref)
                if not output_id:
                    pending.pop(key, None)
                    continue
                try:
                    state = control.output_state(output_id, channel_number)
                except Exception as err:
                    self.logger.debug("output_state(%s) failed: %s", key, err)
                    continue
                if state == 'fault':
                    self.logger.error("Relay %s reports fault", key)
                    return False
                if state in (None, 'pending'):
                    continue
                if _state_is_on(state) == bool(want_on):
                    pending.pop(key, None)
            if pending:
                time.sleep(CONFIRM_POLL_SEC)

        for key in pending:
            self.logger.error("Relay %s did not confirm %s within %.1fs",
                              key, 'on' if want_on else 'off', timeout)
        return not pending

    def relay_reports_on(self, ref):
        output_id, channel_number = self.parse_ref(ref)
        if not output_id:
            return False
        from aot.aot_client import DaemonControl
        return _state_is_on(DaemonControl().output_state(output_id, channel_number))

    def relay_on(self, ref, duration=0.0):
        output_id, channel_number = self.parse_ref(ref)
        if not output_id:
            self.logger.warning("relay_on aborted — could not resolve ref %r", ref)
            return
        self.logger.info("relay_on  %s:%s dur=%.2f", output_id, channel_number, duration)
        try:
            from aot.aot_client import DaemonControl
            control = DaemonControl()
            if duration > 0:
                control.output_on(output_id, output_type='sec',
                                  amount=duration, output_channel=channel_number)
            else:
                control.output_on(output_id, output_channel=channel_number)
        except Exception as err:
            self.logger.warning("relay_on %r failed: %s", ref, err)

    def relay_off(self, ref):
        output_id, channel_number = self.parse_ref(ref)
        if not output_id:
            self.logger.warning("relay_off aborted — could not resolve ref %r", ref)
            return
        self.logger.info("relay_off %s:%s", output_id, channel_number)
        try:
            from aot.aot_client import DaemonControl
            DaemonControl().output_off(output_id, output_channel=channel_number)
        except Exception as err:
            self.logger.warning("relay_off %r failed: %s", ref, err)

    def parse_ref(self, ref):
        """Resolve an output reference to (output_id, channel_number).

        select_channel is parsed by the framework into {'device_id', 'channel_id'},
        where channel_id is the OutputChannel unique_id. Legacy string forms
        ('output_id' and 'output_id,channel_uid') are also accepted.
        """
        if not ref:
            return '', 0

        output_id = ''
        channel_uid = ''
        if isinstance(ref, dict):
            output_id = ref.get('device_id') or ''
            channel_uid = ref.get('channel_id') or ''
        elif isinstance(ref, str):
            if ',' in ref:
                output_id, channel_uid = ref.split(',', 1)
            else:
                output_id = ref
        else:
            return '', 0

        if not output_id:
            return '', 0
        if not channel_uid:
            return output_id, 0
        try:
            channel = db_retrieve_table_daemon(OutputChannel, unique_id=channel_uid)
            return output_id, (channel.channel if channel else 0)
        except Exception as err:
            self.logger.warning("parse_ref lookup failed for %s: %s", channel_uid, err)
            return output_id, 0

    def ref_key(self, ref):
        output_id, channel_number = self.parse_ref(ref)
        return '{}:{}'.format(output_id, channel_number) if output_id else ''

    # ── calibration ──────────────────────────────────────────────────────────
    def calib_run(self, args_dict=None):
        if self._bus is None:
            return "Output is not attached to a bus yet."
        if not self._bus.acquire_for_calibration(self):
            return "The shared bus is busy. Try again once it stops."

        direction = self.opt('calib_direction') or 'open'
        try:
            selector_ref = self.selector_ref()
            if selector_ref:
                self.relay_on(selector_ref)
                if not self.wait_confirm([selector_ref], want_on=True):
                    self.relay_off(selector_ref)
                    self._bus.release_calibration(self)
                    return "Selector relay did not confirm — calibration aborted."
                settle = max(self.float_option('selector_settle_sec', 0.5), 0.0)
                if settle > 0:
                    time.sleep(settle)

            open_ref, close_ref = self.bus_refs()
            drive_ref = open_ref if direction == 'open' else close_ref
            if not self.ref_key(drive_ref):
                if selector_ref:
                    self.relay_off(selector_ref)
                self._bus.release_calibration(self)
                return "No {} relay is configured.".format(direction)

            self._calib_drive_ref = drive_ref
            self._calib_start_ts = time.time()
            self.relay_on(drive_ref)
            self._bus.note_drive_ref(self.ref_key(drive_ref))
        except Exception as err:
            self._bus.release_calibration(self)
            self.logger.exception("Calibration start failed")
            return "Calibration could not start: {}".format(err)

        self.logger.info("Calibration started — direction=%s", direction)
        return "Running. Click '■ Stop & Save' when fully {}.".format(direction)

    def calib_stop(self, args_dict=None):
        if self._calib_drive_ref is None:
            return "No calibration is running."

        direction = self.opt('calib_direction') or 'open'
        elapsed = round(time.time() - self._calib_start_ts, 1)

        try:
            # Stop the bus and wait for it to actually open before releasing the
            # selector, so the selector never breaks under load.
            self.relay_off(self._calib_drive_ref)
            self.wait_confirm([self._calib_drive_ref], want_on=False)
            settle = max(self.float_option('selector_settle_sec', 0.5), 0.0)
            if settle > 0:
                time.sleep(settle)
            selector_ref = self.selector_ref()
            if selector_ref:
                self.relay_off(selector_ref)
        finally:
            self._calib_drive_ref = None
            if self._bus is not None:
                self._bus.release_calibration(self)

        field = 'travel_time_open_sec' if direction == 'open' else 'travel_time_close_sec'
        try:
            self.save_option(field, elapsed)
        except Exception as err:
            self.logger.warning("calib_stop save failed: %s", err)
            return "Stopped after {:.1f}s but failed to save: {}".format(elapsed, err)

        # The actuator now sits at a known end stop — record it so the first real
        # move is measured from the truth rather than a stale estimate.
        self.finish_motion(100.0 if direction == 'open' else 0.0)

        self.logger.info("Calibration done — %.1fs saved as %s", elapsed, field)
        return ("Travel Time {} saved as {:.1f} s. Calibrate the other direction "
                "separately if needed. Reload page to confirm.".format(
                    'Open' if direction == 'open' else 'Close', elapsed))

    # ── options ──────────────────────────────────────────────────────────────
    def selector_ref(self):
        ref = self.opt('selector_output_id')
        return ref if self.ref_key(ref) else None

    def raw_bus_refs(self):
        """(open_ref, close_ref) exactly as configured, without invert_direction."""
        return self.opt('output_open_id'), self.opt('output_close_id')

    def bus_refs(self):
        """(open_ref, close_ref) with invert_direction applied."""
        open_ref, close_ref = self.raw_bus_refs()
        if self.bool_option('invert_direction', False):
            return close_ref, open_ref
        return open_ref, close_ref

    def bus_key(self):
        """Identify the physical bus this actuator is wired to.

        Built from the uninverted pair so two actuators sharing the same hardware
        contend with each other even when only one of them is inverted.
        """
        open_ref, close_ref = self.raw_bus_refs()
        return '|'.join(sorted([self.ref_key(open_ref), self.ref_key(close_ref)]))

    def travel_time(self, direction):
        """Travel time (s) for a direction, falling back to the other, then 60 s."""
        open_sec = max(self.float_option('travel_time_open_sec', 0.0), 0.0)
        close_sec = max(self.float_option('travel_time_close_sec', 0.0), 0.0)
        if direction == 'open':
            return max(open_sec or close_sec or 60.0, 1.0)
        return max(close_sec or open_sec or 60.0, 1.0)

    def startup_force_off_enabled(self):
        return self.bool_option('startup_force_off', True)

    def save_option(self, key, value):
        """Persist a channel option AND refresh the in-memory copy.

        set_custom_channel_option() only writes the database; self.options_channels
        was built once at construction. Without this refresh a freshly calibrated
        travel time stays invisible to the running module, which then falls back to
        the 60 s default and drives the motor for the wrong duration until the
        output happens to be reloaded.
        """
        self.set_custom_channel_option(0, key, value)
        try:
            slot = self.options_channels.get(key)
            if slot is None:
                self.options_channels[key] = {0: value}
            else:
                slot[0] = value
        except Exception as err:
            self.logger.warning("in-memory refresh of '%s' failed: %s", key, err)

    def opt(self, key):
        values = self.options_channels.get(key)
        if not values:
            return None
        try:
            return values.get(0)
        except AttributeError:
            try:
                return values[0]
            except (IndexError, KeyError, TypeError):
                return None

    def float_option(self, key, default):
        value = self.opt(key)
        if value in (None, ''):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def bool_option(self, key, default):
        value = self.opt(key)
        return default if value is None else bool(value)


def _state_is_on(state):
    """Interpret an output_state() result as a boolean on/off."""
    if state is None or state in ('pending', 'fault'):
        return False
    if isinstance(state, str):
        if state == 'on':
            return True
        if state == 'off':
            return False
        try:
            return float(state) > 0
        except (TypeError, ValueError):
            return False
    try:
        return float(state) > 0
    except (TypeError, ValueError):
        return bool(state)
