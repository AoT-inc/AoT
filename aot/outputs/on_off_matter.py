# coding=utf-8
#
# on_off_matter.py - Output for switching OnOff endpoints of a Matter device
#
"""
AoT Output: Matter On/Off

One Output per Matter node; one channel per OnOff endpoint. Created from the
node's own description when the device is shared to AoT (Settings > Matter);
see docs/design/matter-controller.md §5-3.

Commands go through the shared Matter server client
(aot/devices/matter_client.py) as device_command On/Off. The server's
subscription then reports the OnOff attribute, which is what confirms the
command (ConfirmableOutputMixin.confirm_command) — the same "dispatch, then
let the device's own report decide" pattern the Modbus readback uses, only
the report arrives as an event instead of a read.

Runtime contract (plc-modbus-integration.md §3):
  - initialize() never connects or waits (C2);
  - is_on() reads the client's cache only (C4);
  - one command is bounded by COMMAND_TIMEOUT_S, under the 8s Pyro budget (C3);
  - failures return (1, message) (C5).
Startup states are applied from a worker thread once the first snapshot
arrives: subscriber callbacks run on the client's reader thread, which must
not wait on its own reply.
"""
import threading

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.lazy_text import lazy_format

# Under the 8s Pyro budget of output_switch() (C3). Thread devices behind a
# border router usually answer in well under a second; a sleepy one may not.
COMMAND_TIMEOUT_S = 5.0

ON_OFF_CLUSTER = 6
ON_OFF_ATTRIBUTE = 0

measurements_dict = {
    0: {
        'measurement': 'duration_time',
        'unit': 's'
    }
}

channels_dict = {
    0: {
        'types': ['on_off'],
        'measurements': [0]
    }
}

OUTPUT_INFORMATION = {
    'output_name_unique': 'MATTER_ON_OFF',
    'output_name': lazy_format("{}: Matter", lazy_gettext('On/Off')),
    'output_manufacturer': 'Matter',
    'output_library': 'websockets',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    # The device's own OnOff report confirms a command. It normally lands
    # within a second; this is how long to wait before calling it unconfirmed.
    'command_timeout_default_s': 5,

    'message': lazy_gettext(
        'Switch the On/Off endpoints of a Matter device on the AoT Matter fabric (plugs, '
        'relays, lights). Created automatically when a device is shared to AoT from '
        'Settings > Matter; each channel is one endpoint. A command counts as done when '
        'the device itself reports the new state.'
    ),

    'dependencies_module': [
        ('pip-pypi', 'websockets', 'websockets==16.0')
    ],

    'options_enabled': [
        'button_on',
        'button_send_duration'
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
            'phrase': lazy_gettext('Matter endpoint number of this switch on the device')
        },
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': -1,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': lazy_gettext(
                'Set the channel state when AoT starts. "Do Nothing" leaves the device as it is')
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': -1,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': lazy_gettext('Set the channel state when AoT shuts down')
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': lazy_gettext(
                'Whether to trigger functions when the channel switches at startup')
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Force Command'),
            'phrase': lazy_gettext(
                'Always send the command if instructed, regardless of the current state')
        },
        {
            'id': 'amps',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'name': lazy_format("{} ({})", lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': lazy_gettext('The current draw of the device being controlled')
        }
    ]
}


def execute_at_creation(error, new_output, dict_outputs=None):
    """Only Settings > Matter creates this (bound to a node); refuse elsewhere."""
    from aot.devices.matter_onboarding import refuse_outside_settings
    return refuse_outside_settings(error, new_output, dict_outputs)


OUTPUT_INFORMATION['execute_at_creation'] = execute_at_creation


class _NodeLink:
    """The `_shared_link` contract ConfirmableOutputMixin.comm_is_fault() reads:
    the server connection plus the node's availability as the server sees it."""

    def __init__(self, client, node_id):
        self.client = client
        self.node_id = node_id

    def is_healthy(self):
        if not self.client.is_connected():
            return False
        node = self.client.get_node(self.node_id)
        return bool(node and node.get('available'))


class OutputModule(AbstractOutput):
    """Switch Matter OnOff endpoints; the device's own report confirms.

    @phase experimental
    @stability experimental
    @dependency AbstractOutput, matter_client
    """

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.node_id = None
        self.client = None
        self._sub_handle = None
        self._channel_by_path = {}
        self._startup_applied = False
        self._startup_lock = threading.Lock()
        self._was_available = False

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        from aot.devices import matter_clusters
        from aot.devices.matter_client import get_client

        self.setup_output_variables(OUTPUT_INFORMATION)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)

        if not self.node_id:
            # Normal for a moment while Settings > Matter creates the device:
            # output_add() loads the Output before the blueprint writes node_id,
            # and utils_matter reloads it right after. Anything longer means
            # the Output was made outside that path.
            self.logger.info("Node ID not set yet; waiting for it to be configured")
            return

        # channels_dict only declares channel 0; register the runtime channels.
        for ch in self.options_channels.get('endpoint', {}):
            if ch not in self.output_states:
                self.output_states[ch] = None
                self.output_off_triggered[ch] = False
                self.output_time_turned_on[ch] = None
                self.output_on_duration[ch] = False
                self.output_last_duration[ch] = 0
                self.output_off_until[ch] = 0
                self._started_at_written[ch] = False
                # output_on_until stays unset (see on_off_modbus.py).

        self._channel_by_path = {}
        for ch, endpoint in self.options_channels.get('endpoint', {}).items():
            path = matter_clusters.attribute_path(endpoint, ON_OFF_CLUSTER, ON_OFF_ATTRIBUTE)
            self._channel_by_path.setdefault(path, []).append(ch)

        self.client = get_client()
        self._shared_link = _NodeLink(self.client, self.node_id)
        if self._sub_handle is None:
            self._sub_handle = self.client.subscribe(self._on_event, node_id=self.node_id)
        self.client.ensure_started()      # non-blocking

        # Set up now; a channel whose state is not known yet reports None from
        # is_on() (shown as unknown), never a fabricated OFF.
        self.output_setup = True
        node = self.client.get_node(self.node_id) if self.client.is_connected() else None
        self._was_available = bool(node and node.get('available'))
        if self._was_available:
            self._seed_from_cache('initialize')

    # ------------------------------------------------------------------ #

    def _on_event(self, event, data):
        """Runs on the client's reader thread — no commands from here."""
        if event == 'attribute_updated':
            try:
                path, value = data[1], data[2]
            except (TypeError, IndexError):
                return
            for ch in self._channel_by_path.get(path, ()):
                self.note_device_alive(ch)
                self.confirm_command(ch, bool(value), 'matter-report')
        elif event == 'connected':
            self._seed_from_cache(event)
        elif event in ('node_updated', 'node_added'):
            # node_updated also fires for interview refreshes, with a cache that
            # may predate a command's report. Re-seed only when the node comes
            # back online; otherwise reports and invoke results are the source.
            available = bool(isinstance(data, dict) and data.get('available'))
            if available and not self._was_available:
                self._seed_from_cache(event)
            self._was_available = available

    def _seed_from_cache(self, source):
        node = self.client.get_node(self.node_id)
        if not node or not node.get('available'):
            return
        for path, channels in self._channel_by_path.items():
            value = self.client.get_attribute(self.node_id, path)
            if value is None:
                continue
            for ch in channels:
                # A command in flight is settled by its own invoke result and
                # report. Confirming it here from a value cached before the
                # command would cancel it (and drop a timed ON's auto-off).
                if self.is_pending(ch):
                    continue
                self.confirm_command(ch, bool(value), f'matter-{source}')
        with self._startup_lock:
            if self._startup_applied:
                return
            self._startup_applied = True
        threading.Thread(target=self._apply_startup_states, daemon=True,
                         name=f'matter-startup-{self.unique_id[:8]}').start()

    def _apply_startup_states(self):
        for ch in self.options_channels.get('endpoint', {}):
            state_startup = self.options_channels['state_startup'].get(ch, -1)
            if state_startup == 1:
                self.output_switch('on', output_channel=ch)
            elif state_startup == 0:
                self.output_switch('off', output_channel=ch)

            if (state_startup in [0, 1] and
                    self.options_channels['trigger_functions_startup'].get(ch)):
                try:
                    self.check_triggers(self.unique_id, output_channel=ch)
                except Exception as err:
                    self.logger.error(
                        f"Could not check Trigger for channel {ch} of output "
                        f"{self.unique_id}: {err}")

    # ------------------------------------------------------------------ #

    def confirmation_capable(self):
        """True: the device's OnOff attribute report is device feedback."""
        return True

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        from aot.devices.matter_client import MatterError

        if self.client is None:
            return 1, "Output not set up"
        endpoint = self.options_channels.get('endpoint', {}).get(output_channel)
        if endpoint is None:
            return 1, f"Channel {output_channel} has no Matter endpoint"

        prev_state = bool(self.output_states.get(output_channel) or False)
        command = 'On' if state == 'on' else 'Off'
        try:
            self.client.send_command('device_command', {
                'node_id': int(self.node_id),
                'endpoint_id': int(endpoint),
                'cluster_id': ON_OFF_CLUSTER,
                'command_name': command,
                'payload': {},
            }, timeout=COMMAND_TIMEOUT_S)
        except MatterError as err:
            # No optimistic flip for a command that did not go through.
            self.begin_command(output_channel, state, prev_state, dispatched_ok=False)
            msg = f"Matter command failed on channel {output_channel}: {err}"
            self.logger.error(msg)
            return 1, msg
        except Exception as err:
            self.begin_command(output_channel, state, prev_state, dispatched_ok=False)
            msg = f"Error switching channel {output_channel}: {err}"
            self.logger.exception(msg)
            return 1, msg

        # The invoke succeeded: the device itself executed On/Off, which is
        # device feedback in its own right. Confirm now rather than waiting
        # for the OnOff report, because (a) a command matching the current
        # state produces no report at all (subscriptions report changes), so
        # waiting would turn every repeated OFF from a PID into a fault, and
        # (b) the report can be handled on the reader thread before this line
        # runs, and a pending window opened after it would never close. A
        # later report that disagrees still corrects the state.
        self.begin_command(output_channel, state, prev_state, dispatched_ok=True)
        self.confirm_command(output_channel, state == 'on', 'matter-invoke')
        return 0, ""

    def is_on(self, output_channel=0):
        if not self.is_setup():
            return None
        state = self.output_states.get(output_channel)
        if state is None and self._cmd_confirmed.get(output_channel) is None:
            return None
        return self.resolve_is_on(output_channel, bool(state))

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup() and self.client is not None and self.client.is_connected():
            for ch in self.options_channels.get('endpoint', {}):
                state_shutdown = self.options_channels['state_shutdown'].get(ch, -1)
                if state_shutdown == 1:
                    self.output_switch('on', output_channel=ch)
                elif state_shutdown == 0:
                    self.output_switch('off', output_channel=ch)
        if self.client is not None and self._sub_handle is not None:
            self.client.unsubscribe(self._sub_handle)
            self._sub_handle = None
        self.running = False
