# coding=utf-8
#
# value_matter_covering.py - Position output for Matter window coverings
#
"""
AoT Output: Matter window covering (curtain, shade, blind, motorised vent)

One Output per covering endpoint, always on channel 0: the environment
coordinator syncs a position actuator's last position from channel 0 only.
Created from the node's own description when the device is shared to AoT
(Settings > Matter); docs/design/matter-controller.md §12.

Units. AoT position actuators use 100 = open / retracted, 0 = closed /
deployed (env_coordinator, actuator_paired). Matter lift is the other way
round: 0 % = fully open, 100 % (10000 in 100ths) = fully closed. This module
converts both ways; nothing above it sees Matter's convention.

Commands (a `value` output, `self_positioning`):
  value N      -> GoToLiftPercentage(liftPercent100thsValue = (100-N)*100)
                  on a position-aware covering; otherwise N >= 50 opens
                  (UpOrOpen) and N < 50 closes (DownOrClose)
  off          -> StopMotion (as the value widget and actuator_paired mean it)
`self_positioning` makes the coordinator send 0 % as a value command, not as
off, so "close" never turns into "stop" (dispatch_adapters.select_adapter).

The device moves itself and reports CurrentPositionLiftPercent100ths while
travelling; that report is the state. When it stops, the position is
written to channel 0's `last_position_pct` (what the coordinator reads after
a restart or a manual move) and recorded to InfluxDB.

A failed command returns (1, message), which base_output's value path
reports as a failure (command audit and triggers still run).

`on` without an amount: base_output passes 0 for a missing amount, so it
reaches this module as value 0 (close). Callers that mean "open" send 100.
"""
import copy
import threading
import time

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.devices.matter_output import MatterOutputMixin
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.lazy_text import lazy_format

COMMAND_TIMEOUT_S = 5.0          # under the 8 s Pyro budget (C3)
WINDOW_COVERING = 0x0102
CURRENT_LIFT_100THS = 14
TARGET_LIFT_100THS = 11
OPERATIONAL_STATUS = 10
LIFT_STATUS_MASK = 0b1100        # OperationalStatus bits 2-3: lift; 0 = stopped
# While travelling, persist the position at most this often (stops always).
PERSIST_EVERY_S = 10.0

measurements_dict = {
    0: {
        'measurement': 'duty_cycle',
        'unit': 'percent'
    }
}

channels_dict = {
    0: {
        'types': ['value'],
        'measurements': [0]
    }
}

OUTPUT_INFORMATION = {
    'output_name_unique': 'MATTER_COVERING',
    'output_name': lazy_format("{}: Matter", lazy_gettext('Curtain / Shade')),
    'output_manufacturer': 'Matter',
    'output_library': 'websockets',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['value'],
    # The device positions itself: 0 % is a position, off is Stop.
    'self_positioning': True,

    'message': lazy_gettext(
        'Move a Matter curtain, shade, blind or motorised vent on the AoT Matter fabric to a '
        'position. 100 is fully open (retracted) and 0 fully closed (deployed), as for other '
        'AoT position actuators. Off stops the motor. The device reports its own position, '
        'which is shown here and used by the environment coordinator.'
    ),

    'dependencies_module': [
        ('pip-pypi', 'websockets', 'websockets==16.0')
    ],

    'options_enabled': [
        'button_send_value'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['IP'],

    'custom_options': [
        {
            'id': 'node_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Node ID'),
            'phrase': lazy_gettext(
                'Node ID on the AoT Matter fabric. Inherited from the Matter device')
        },
    ],

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Name'),
            'phrase': lazy_gettext('A name for this channel')
        },
        {
            'id': 'endpoint',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Endpoint'),
            'phrase': lazy_gettext('Matter endpoint number of this covering on the device')
        },
    ]
}


def execute_at_creation(error, new_output, dict_outputs=None):
    """Only Settings > Matter creates this (bound to a node); refuse elsewhere."""
    from aot.devices.matter_onboarding import refuse_outside_settings
    return refuse_outside_settings(error, new_output, dict_outputs)


OUTPUT_INFORMATION['execute_at_creation'] = execute_at_creation


def aot_to_matter_100ths(pct):
    """AoT 100 = open -> Matter 0 = open, in 100ths."""
    pct = float(pct)
    if pct != pct or pct in (float('inf'), float('-inf')):
        raise ValueError(f"Invalid position: {pct}")
    pct = max(0.0, min(100.0, pct))
    return int(round((100.0 - pct) * 100))


def matter_100ths_to_aot(value):
    return round(100.0 - max(0, min(10000, int(value))) / 100.0, 1)


class OutputModule(MatterOutputMixin, AbstractOutput):
    """Matter WindowCovering lift as an AoT position (value) output.

    @phase experimental
    @stability experimental
    @dependency AbstractOutput, matter_client, matter_output
    """

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)
        self._matter_init()
        self._last_persist = {}       # channel -> (monotonic time, pct)
        self._persist_lock = threading.Lock()
        self._last_target = {}        # channel -> (pct, source) of our last command

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)
        if not self.node_id:
            self.logger.info("Node ID not set yet; waiting for it to be configured")
            return
        self._matter_setup(OUTPUT_INFORMATION)

    # -- state -------------------------------------------------------------

    def state_paths(self, endpoint):
        from aot.devices.matter_clusters import attribute_path
        return [attribute_path(endpoint, WINDOW_COVERING, CURRENT_LIFT_100THS),
                attribute_path(endpoint, WINDOW_COVERING, OPERATIONAL_STATUS)]

    def _state_from_cache(self, channel, endpoint):
        current = self._attr(endpoint, WINDOW_COVERING, CURRENT_LIFT_100THS)
        return None if current is None else matter_100ths_to_aot(current)

    def _moving(self, endpoint):
        status = self._attr(endpoint, WINDOW_COVERING, OPERATIONAL_STATUS)
        return isinstance(status, int) and bool(status & LIFT_STATUS_MASK)

    def _set_state(self, channel, value, source):
        super()._set_state(channel, value, source)
        endpoint = self._endpoint(channel)
        moving = endpoint is not None and self._moving(endpoint)
        last = self._last_persist.get(channel)
        now = time.monotonic()
        if last is not None and abs(last[1] - value) < 0.5:
            return
        if moving and last is not None and now - last[0] < PERSIST_EVERY_S:
            return
        self._last_persist[channel] = (now, value)
        # Reports arrive on the Matter client's reader thread; a DB write
        # there would hold up every Matter reply in this process.
        threading.Thread(target=self._persist, args=(channel, value), daemon=True,
                         name=f'matter-cover-persist-{self.unique_id[:8]}').start()

    def _persist(self, channel, pct):
        """Write where the coordinator and a restarted daemon look, and record.

        One worker thread per persist, serialised here; a write that is no
        longer the latest position is dropped, so a slow moving-write cannot
        land after the stop-write and leave a stale position behind."""
        with self._persist_lock:
            latest = self._last_persist.get(channel)
            if latest is not None and latest[1] != pct:
                return
            self._persist_now(channel, pct)

    def _persist_now(self, channel, pct):
        if channel == 0:
            value = round(float(pct), 1)
            try:
                saved = self.set_custom_channel_option(0, 'last_position_pct', value)
            except Exception:
                self.logger.exception("Saving last_position_pct failed")
                saved = None
            # The setter swallows its own errors and returns the value only on
            # success. On failure forget the persist, so the next report (or
            # the stop report) tries again instead of leaving a stale position
            # the coordinator would resync to every cycle.
            if saved != value:
                self.logger.warning("Saving last_position_pct failed; will retry")
                self._last_persist.pop(channel, None)
        try:
            measure = {channel: copy.deepcopy(measurements_dict[0])}
            measure[channel]['value'] = float(pct)
            add_measurements_influxdb(self.unique_id, measure)
        except Exception:
            self.logger.exception("Recording position failed")

    # -- commands ----------------------------------------------------------

    def _position_aware(self, endpoint):
        from aot.devices.matter_clusters import covering_position_aware
        node = self.client.get_node(self.node_id) or {}
        return covering_position_aware(node.get('attributes') or {}, endpoint)

    def output_switch(self, state, output_type=None, amount=None, output_channel=0,
                      additional_options=None, **kwargs):
        """Returns (1, message) on failure (see module docstring)."""
        from aot.devices.matter_client import MatterError

        if self.client is None:
            return 1, "Output not set up"
        endpoint = self._endpoint(output_channel)
        if endpoint is None:
            return 1, f"Channel {output_channel} has no Matter endpoint"

        try:
            if state == 'off':
                self._send(endpoint, WINDOW_COVERING, 'StopMotion', {}, COMMAND_TIMEOUT_S)
            else:
                pct = 100.0 if amount is None else float(amount)
                if pct != pct or pct in (float('inf'), float('-inf')):
                    return 1, f"Invalid position: {amount}"
                source = (additional_options or {}).get('source', 'system')
                if self._position_aware(endpoint):
                    self._send(endpoint, WINDOW_COVERING, 'GoToLiftPercentage',
                               {'liftPercent100thsValue': aot_to_matter_100ths(pct)},
                               COMMAND_TIMEOUT_S)
                elif pct >= 50:
                    self._send(endpoint, WINDOW_COVERING, 'UpOrOpen', {}, COMMAND_TIMEOUT_S)
                else:
                    self._send(endpoint, WINDOW_COVERING, 'DownOrClose', {}, COMMAND_TIMEOUT_S)
                self._last_target[output_channel] = (pct, source)
        except MatterError as err:
            msg = f"Matter command failed on channel {output_channel}: {err}"
            self.logger.error(msg)
            return 1, msg
        except (TypeError, ValueError) as err:
            return 1, f"Invalid position: {amount} ({err})"
        return 0, ""

    def is_on(self, output_channel=0):
        """The position (AoT %), False when fully closed, None if unknown —
        the convention value outputs use (actuator_paired)."""
        if not self.is_setup():
            return None
        pct = self.output_states.get(output_channel)
        if pct is None:
            return None
        return pct if pct > 0 else False

    def output_target_pct(self, output_channel=0):
        """Where the device is heading, for the value widget."""
        endpoint = self._endpoint(output_channel)
        if self.client is None or endpoint is None:
            return None
        target = self._attr(endpoint, WINDOW_COVERING, TARGET_LIFT_100THS)
        if target is None:
            return None
        pct = matter_100ths_to_aot(target)
        # Who asked for it: ours if it is the target we last sent (with the
        # source the caller gave — the value widget says 'manual'), otherwise
        # someone else moved it (another app, a wall switch, the device).
        sent = self._last_target.get(output_channel)
        if sent is not None and abs(sent[0] - pct) < 0.5:
            return pct, sent[1]
        return pct, 'system'

    def stop_output(self):
        self._matter_teardown()
        self.running = False
