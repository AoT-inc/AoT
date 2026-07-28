# coding=utf-8
#
# on_off_modbus.py - Output for switching coils on a Modbus TCP device (PLC)
#
"""
AoT Output: Modbus TCP coil (PLC)

Design notes (.local/plans/plc_modbus_integration_plan.md section 3):
  - Every command writes the coil and re-reads it inside the same lock hold, so
    the confirmation is not a separate round trip that another thread can slip a
    write into. That readback is handed to confirm_command(), which is exactly
    the pattern on_off_kasa_plugs.py already uses on this same base class — no
    new state machine is introduced here.
  - begin_command() is called AFTER the dispatch attempt with dispatched_ok, not
    before it. Calling it first would paint an optimistic ON that survives a
    failed write (a phantom ON in the UI).
  - self._shared_link makes comm_is_fault() report the whole PLC as faulted when
    the link dies, even with no command in flight. Without it, a PLC that goes
    down quietly leaves no trace in the UI until someone presses a button.
  - Nothing here blocks daemon startup: the initial state probe runs in a
    background thread, because is_on() is polled serially across all channels by
    the output page and initialize() runs inside the daemon's sequential
    activation.

A readback only proves the PLC's coil register changed. It does not prove the
relay actually moved or that the wiring is intact — that needs a separate
feedback contact read back as an Input.
"""
import json
import threading

from flask_babel import lazy_gettext

from aot.databases.models import DeviceMeasurements, OutputChannel
from aot.devices.modbus_client import ModbusLinkError, get_link
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

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
    'output_name_unique': 'MODBUS_TCP_COIL',
    'output_name': "{}: Modbus TCP Coil (PLC)".format(lazy_gettext('On/Off')),
    'output_manufacturer': 'Modbus',
    'output_library': 'pymodbus',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    # write -> readback happens inside the dispatch, so a command is confirmed
    # (or failed) by the time output_switch() returns. This window only has to
    # cover the transport, not a device that reports back later.
    'command_timeout_default_s': 5,

    'message': lazy_gettext(
        'Switch coils on a Modbus TCP device (PLC, relay board, gateway). Each channel is one '
        'coil address. After every command the coil is read back to confirm it actually changed, '
        'and a mismatch is reported as a failure. Inputs and Outputs pointing at the same host '
        'and port share one connection automatically. '
        'Note that a readback confirms the PLC register, not that the relay or wiring moved. '
        'Modbus has no authentication or encryption — keep the device on an isolated network.'
    ),

    'dependencies_module': [
        ('pip-pypi', 'pymodbus', 'pymodbus==3.14.0')
    ],

    'execute_at_modification': None,  # set below

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['IP'],

    'custom_options': [
        {
            'id': 'num_channels',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Number of Channels'),
            'phrase': lazy_gettext(
                'Number of coils to control. Save to add or remove channel rows.')
        },
        {
            'id': 'plc_host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Host'),
            'phrase': lazy_gettext(
                'IP address or hostname of the Modbus TCP device')
        },
        {
            'id': 'plc_port',
            'type': 'integer',
            'default_value': 502,
            'required': True,
            'name': lazy_gettext('Port'),
            'phrase': lazy_gettext(
                'TCP port of the Modbus TCP device (standard: 502)')
        },
        {
            'id': 'unit_id',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Unit ID'),
            'phrase': lazy_gettext(
                'Modbus unit/slave ID of the device. Usually 1 for a device addressed '
                'directly, or the slave address behind a serial gateway')
        },
        {
            'id': 'timeout_s',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'name': lazy_gettext('Timeout (seconds)'),
            'phrase': lazy_gettext(
                'How long to wait for a response. One request takes at most '
                'timeout x (retries + 1), and a command sends two requests')
        },
        {
            'id': 'retries',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Retries'),
            'phrase': lazy_gettext(
                'Retries per request before it is treated as failed. Keep this low: a high '
                'value multiplies how long an unreachable device blocks a command')
        }
    ],

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Channel Name'),
            'phrase': lazy_gettext(
                'A friendly name shown in the UI for this channel.')
        },
        {
            'id': 'coil_address',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Coil Address'),
            'phrase': lazy_gettext(
                'Zero-based coil address to switch. Vendor documentation often lists '
                'one-based addresses (e.g. 00001 for coil 0), so verify against the '
                'register map')
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
                'Set the channel state when AoT starts. "Do Nothing" leaves the coil as the '
                'PLC has it and simply reads it back')
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
            'phrase': lazy_gettext(
                'Set the channel state when AoT shuts down')
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
            'name': "{} ({})".format(lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': lazy_gettext(
                'The current draw of the device being controlled')
        }
    ]
}


def execute_at_modification(
        messages,
        mod_output,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """Add or remove OutputChannel records when num_channels changes."""
    from aot.aot_flask.extensions import db

    messages["page_refresh"] = True

    try:
        num_channels = int(custom_options_dict_postsave.get('num_channels', 1))
        if num_channels < 1:
            num_channels = 1
    except (TypeError, ValueError):
        num_channels = 1

    current_channels = OutputChannel.query.filter(
        OutputChannel.output_id == mod_output.unique_id
    ).order_by(OutputChannel.channel).all()
    current_count = len(current_channels)

    # channels_dict/measurements_dict are templates describing channel 0 only.
    # Runtime channels 1..N need their own DeviceMeasurements row or the UI has
    # nowhere to show per-channel duration_time even though InfluxDB accepts the
    # writes (same reasoning as on_off_mqtt_multi.py).
    measure_template = measurements_dict.get(0, {})

    if num_channels < current_count:
        for ch in current_channels[num_channels:]:
            dm = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == mod_output.unique_id,
                DeviceMeasurements.channel == ch.channel
            ).first()
            if dm and ch.channel != 0:
                db.session.delete(dm)
            db.session.delete(ch)

    elif num_channels > current_count:
        for i in range(current_count, num_channels):
            new_ch = OutputChannel()
            new_ch.output_id = mod_output.unique_id
            new_ch.channel = i
            new_ch.custom_options = json.dumps({
                'name': '',
                'coil_address': i,
                'state_startup': -1,
                'state_shutdown': -1,
                'trigger_functions_startup': False,
                'command_force': False,
                'amps': 0.0
            })
            db.session.add(new_ch)

            if i != 0:
                existing_dm = DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == mod_output.unique_id,
                    DeviceMeasurements.channel == i
                ).first()
                if not existing_dm:
                    new_dm = DeviceMeasurements()
                    new_dm.device_id = mod_output.unique_id
                    new_dm.measurement = measure_template.get('measurement', 'duration_time')
                    new_dm.unit = measure_template.get('unit', 's')
                    new_dm.channel = i
                    new_dm.is_enabled = True
                    db.session.add(new_dm)

    mod_output.size_y = num_channels + 1

    return (
        messages,
        mod_output,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave
    )


OUTPUT_INFORMATION['execute_at_modification'] = execute_at_modification


class OutputModule(AbstractOutput):
    """Switch coils on a Modbus TCP device, confirming each command by readback.

    @phase active
    @stability experimental
    @dependency AbstractOutput, ModbusTCPLink
    """

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.num_channels = None
        self.plc_host = None
        self.plc_port = None
        self.unit_id = None
        self.timeout_s = None
        self.retries = None

        self.link = None
        self._startup_thread = None

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)

        if not self.plc_host:
            self.logger.error("Host must be set")
            return

        # channels_dict only declares channel 0; register the runtime channels.
        for ch in self.options_channels.get('coil_address', {}):
            if ch not in self.output_states:
                self.output_states[ch] = None
                self.output_off_triggered[ch] = False
                self.output_time_turned_on[ch] = None
                self.output_on_duration[ch] = False
                self.output_last_duration[ch] = 0
                self.output_off_until[ch] = 0
                self._started_at_written[ch] = False
                # output_on_until is deliberately left unset: the loop tests
                # `ch in output_on_until` first, and None would blow up the
                # `None < datetime` comparison.

        # get_link() registers the connection without opening a socket, so this
        # is safe inside the daemon's sequential Output activation.
        self.link = get_link(
            self.plc_host,
            port=int(self.plc_port),
            timeout_s=float(self.timeout_s),
            retries=int(self.retries))

        # The link axis of comm_is_fault(): when this PLC is down, every channel
        # on it reports faulted even with no command in flight.
        self._shared_link = self.link

        # is_setup() stays False until the probe finishes, so is_on() returns
        # None and the UI shows "unknown" rather than a fabricated OFF.
        if self._startup_thread is None or not self._startup_thread.is_alive():
            self._startup_thread = threading.Thread(
                target=self._startup_probe, daemon=True)
            self._startup_thread.start()

    def _startup_probe(self):
        """Read every coil once, then apply startup states.

        Runs off the activation path on purpose. Reading here rather than inside
        is_on() matters: the output page polls is_on() serially for every
        channel, so a network read there would freeze the whole page for
        timeout x channels whenever the PLC is unreachable.
        """
        try:
            for ch, address in self.options_channels.get('coil_address', {}).items():
                try:
                    actual = self.link.read_coils(
                        int(address), count=1, device_id=int(self.unit_id))[0]
                except ModbusLinkError as err:
                    # Leave the state unknown and let comm_is_fault() report the
                    # link. The next command retries the connection.
                    self.logger.error(f"Startup probe failed on channel {ch}: {err}")
                    continue
                self.confirm_command(ch, bool(actual), 'startup-probe')
                self.logger.debug(f"Startup probe: channel {ch} coil {address} = {actual}")
        finally:
            # Set up either way: a PLC that is down at boot must still become
            # controllable once it comes back, and comm_is_fault() already tells
            # the UI that the link is bad.
            self.output_setup = True

        for ch in self.options_channels.get('coil_address', {}):
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

    def confirmation_capable(self):
        """Always true: the coil readback after every write is device feedback."""
        return True

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        """Write the coil, read it back in the same lock hold, and confirm."""
        if self.link is None:
            return 1, "Output not set up"

        address = self.options_channels.get('coil_address', {}).get(output_channel)
        if address is None:
            return 1, f"Channel {output_channel} has no coil address"

        want_on = (state == 'on')
        prev_state = bool(self.output_states.get(output_channel) or False)

        try:
            actual = self.link.write_coil_and_read_back(
                int(address), want_on, device_id=int(self.unit_id))
        except ModbusLinkError as err:
            # dispatched_ok=False keeps prev_state — no optimistic flip on a
            # command that never reached the PLC.
            self.begin_command(output_channel, state, prev_state, dispatched_ok=False)
            msg = f"PLC communication failed on channel {output_channel}: {err}"
            self.logger.error(msg)
            return 1, msg
        except Exception as err:
            self.begin_command(output_channel, state, prev_state, dispatched_ok=False)
            msg = f"Error switching channel {output_channel}: {err}"
            self.logger.exception(msg)
            return 1, msg

        self.begin_command(output_channel, state, prev_state, dispatched_ok=True)
        self.confirm_command(output_channel, bool(actual), 'modbus-readback')

        if bool(actual) != want_on:
            # The write was acknowledged but the coil did not take the value —
            # a PLC program overriding the coil, or a wrong address.
            msg = (f"Coil mismatch on channel {output_channel}: "
                   f"requested {state}, read back {'on' if actual else 'off'}")
            self.logger.error(msg)
            return 1, msg

        return 0, ""

    def is_on(self, output_channel=0):
        if self.is_setup():
            return self.resolve_is_on(
                output_channel, bool(self.output_states.get(output_channel) or False))

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            for ch in self.options_channels.get('coil_address', {}):
                state_shutdown = self.options_channels['state_shutdown'].get(ch, -1)
                if state_shutdown == 1:
                    self.output_switch('on', output_channel=ch)
                elif state_shutdown == 0:
                    self.output_switch('off', output_channel=ch)
        self.running = False
