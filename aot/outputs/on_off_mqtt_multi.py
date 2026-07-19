# coding=utf-8
#
# on_off_mqtt_multi.py - Output for publishing on/off via MQTT to multiple channels
#                       with separate control/status topics and per-channel status payload matching.
#
import json
import threading

from flask_babel import lazy_gettext

from aot.databases.models import DeviceMeasurements, OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.constraints_pass import constraints_pass_positive_or_zero_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.utils import random_alphanumeric

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
    'output_name_unique': 'MQTT_PAHO_MULTI',
    'output_name': "{}: MQTT Publish Multi".format(lazy_gettext('On/Off')),
    'output_manufacturer': 'AoT',
    'output_library': 'paho-mqtt',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'url_additional': 'http://www.eclipse.org/paho/',

    'message': (
        'Publish "on"/"off" payloads to a control topic for multiple channels, '
        'and subscribe to a status topic to reflect each channel\'s actual operating state. '
        'All channels share the same broker connection and the two topics. '
        'Each channel sends its own control payload and matches its own status payload values. '
        'Increase the channel count and save to add channels.'
    ),

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1')
    ],

    'execute_at_modification': None,  # set below

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['IP'],

    # ── Common (device-level) settings ──────────────────────────────────────
    'custom_options': [
        {
            'id': 'num_channels',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Number of Channels'),
            'phrase': 'Number of channels. Save to add or remove channel rows.'
        },
        {
            'id': 'hostname',
            'type': 'text',
            'default_value': 'localhost',
            'required': True,
            'name': lazy_gettext('Hostname'),
            'phrase': 'The hostname of the MQTT server'
        },
        {
            'id': 'port',
            'type': 'integer',
            'default_value': 1883,
            'required': True,
            'name': lazy_gettext('Port'),
            'phrase': 'The port of the MQTT server'
        },
        {
            'id': 'topic_control',
            'type': 'text',
            'default_value': 'paho/test/control',
            'required': True,
            'name': lazy_gettext('Control Topic'),
            'phrase': 'The MQTT topic used to publish on/off commands (control direction).'
        },
        {
            'id': 'topic_status',
            'type': 'text',
            'default_value': 'paho/test/status',
            'required': False,
            'name': lazy_gettext('Status Topic'),
            'phrase': 'The MQTT topic to subscribe to for confirming each channel\'s operating state. '
                      'Leave blank to disable status feedback.'
        },
        {
            'id': 'keepalive',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_gettext('Keep Alive'),
            'phrase': 'The keepalive timeout value for the client. Set to 0 to disable.'
        },
        {
            'id': 'clientid',
            'type': 'text',
            'default_value': 'client_{}'.format(random_alphanumeric(8)),
            'required': True,
            'name': 'Client ID',
            'phrase': 'Unique client ID for connecting to the MQTT server'
        },
        {
            'id': 'login',
            'type': 'bool',
            'default_value': False,
            'name': 'Use Login',
            'phrase': 'Send login credentials'
        },
        {
            'id': 'username',
            'type': 'text',
            'default_value': 'user',
            'required': False,
            'name': lazy_gettext('Username'),
            'phrase': 'Username for connecting to the server'
        },
        {
            'id': 'password',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Password'),
            'phrase': 'Password for connecting to the server. Leave blank to disable.'
        },
        {
            'id': 'mqtt_use_websockets',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Use Websockets',
            'phrase': 'Use websockets to connect to the server.'
        }
    ],

    # ── Per-channel settings ───────────────────────────────────────────────
    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Channel Name'),
            'phrase': 'A friendly name shown in the UI for this channel.'
        },
        {
            'id': 'payload_on',
            'type': 'text',
            'default_value': 'on',
            'required': True,
            'name': lazy_gettext('On Payload (Control)'),
            'phrase': 'The payload published to the Control Topic to turn this channel ON.'
        },
        {
            'id': 'payload_off',
            'type': 'text',
            'default_value': 'off',
            'required': True,
            'name': lazy_gettext('Off Payload (Control)'),
            'phrase': 'The payload published to the Control Topic to turn this channel OFF.'
        },
        {
            'id': 'payload_status_on',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('On Payload (Status)'),
            'phrase': 'When this exact value is received on the Status Topic, the channel is marked ON. '
                      'Leave blank to disable ON detection for this channel.'
        },
        {
            'id': 'payload_status_off',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Off Payload (Status)'),
            'phrase': 'When this exact value is received on the Status Topic, the channel is marked OFF. '
                      'Leave blank to disable OFF detection for this channel.'
        },
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': 'Set the channel state when AoT starts'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': 'Set the channel state when AoT shuts down'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': 'Whether to trigger functions when the channel switches at startup'
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Force Command'),
            'phrase': 'Always send the command if instructed, regardless of the current state'
        },
        {
            'id': 'amps',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': 'The current draw of the device being controlled'
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

    # measurements_dict is template-only ({0: duration_time/s}). Without this
    # sync, runtime channels 1..N have no DeviceMeasurements row and the UI
    # cannot display per-channel duration_time even though InfluxDB writes
    # succeed. Mirror OutputChannel changes with DeviceMeasurements changes.
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
                'payload_on': 'on',
                'payload_off': 'off',
                'payload_status_on': '',
                'payload_status_off': '',
                'state_startup': 0,
                'state_shutdown': 0,
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
    """Publish on/off payloads to a control topic and reflect channel states from a status topic.

    All channels share the same broker connection and the two topics. Each channel has its own
    control payloads (publish) and status payloads (matched on subscribe).

    @phase active
    @stability stable
    @dependency AbstractOutput, paho-mqtt
    """

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.publish = None
        self.status_client = None
        self._status_lock = threading.Lock()

        # device-level (set via setup_custom_options)
        self.num_channels = None
        self.hostname = None
        self.port = None
        self.topic_control = None
        self.topic_status = None
        self.keepalive = None
        self.clientid = None
        self.login = None
        self.username = None
        self.password = None
        self.mqtt_use_websockets = None

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        import paho.mqtt.publish as publish

        self.publish = publish

        self.setup_output_variables(OUTPUT_INFORMATION)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)

        # Register all runtime channels in base class dicts (channels_dict only defines ch0)
        for ch in self.options_channels.get('payload_on', {}):
            if ch not in self.output_states:
                self.output_states[ch] = None
                self.output_off_triggered[ch] = False
                self.output_time_turned_on[ch] = None
                self.output_on_duration[ch] = False
                self.output_last_duration[ch] = 0
                self.output_off_until[ch] = 0
                self._started_at_written[ch] = False
                # output_on_until intentionally omitted: loop checks `ch in output_on_until`
                # first; None would cause TypeError on `None < datetime` comparison

        self.output_setup = True

        for ch in self.options_channels.get('payload_on', {}):
            state_startup = self.options_channels['state_startup'].get(ch, -1)
            if state_startup == 1:
                self.output_switch('on', output_channel=ch)
            elif state_startup == 0:
                self.output_switch('off', output_channel=ch)

            if state_startup in [0, 1] and self.options_channels['trigger_functions_startup'].get(ch):
                try:
                    self.check_triggers(self.unique_id, output_channel=ch)
                except Exception as err:
                    self.logger.error(
                        f"Could not check Trigger for channel {ch} of output {self.unique_id}: {err}")

        # Subscribe to status topic (if configured)
        if self.topic_status:
            self._start_status_subscriber()

    def _start_status_subscriber(self):
        """Connect a paho-mqtt Client and subscribe to the status topic."""
        try:
            import paho.mqtt.client as mqtt_client

            transport = 'websockets' if self.mqtt_use_websockets else 'tcp'
            sub_client_id = "{}_sub_{}".format(self.clientid or 'aot', random_alphanumeric(4))

            self.status_client = mqtt_client.Client(
                client_id=sub_client_id, transport=transport)

            if self.login:
                pwd = self.password if self.password else None
                self.status_client.username_pw_set(self.username, pwd)

            self.status_client.on_connect = self._on_status_connect
            self.status_client.on_message = self._on_status_message
            self.status_client.on_disconnect = self._on_status_disconnect

            self.status_client.connect(self.hostname, self.port, self.keepalive or 60)
            self.status_client.loop_start()
            self.logger.info(
                "Status subscriber started for topic '{}'".format(self.topic_status))
        except Exception as err:
            self.logger.error("Failed to start status subscriber: {}".format(err))
            self.status_client = None

    def _on_status_connect(self, client, userdata, flags, rc):
        if rc == 0:
            try:
                client.subscribe(self.topic_status)
                self.logger.info("Subscribed to status topic: {}".format(self.topic_status))
            except Exception as err:
                self.logger.error("Subscribe failed: {}".format(err))
        else:
            self.logger.error("Status subscriber connect failed (rc={})".format(rc))

    def _on_status_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning("Status subscriber unexpectedly disconnected (rc={})".format(rc))

    def _on_status_message(self, client, userdata, msg):
        """Update channel states based on the received status payload."""
        try:
            payload = msg.payload.decode('utf-8', errors='replace').strip()
        except Exception:
            return

        with self._status_lock:
            for ch in self.options_channels.get('payload_on', {}):
                on_val = self.options_channels.get('payload_status_on', {}).get(ch, '')
                off_val = self.options_channels.get('payload_status_off', {}).get(ch, '')

                if on_val and payload == on_val:
                    if self.output_states.get(ch) is not True:
                        self.output_states[ch] = True
                        self.logger.debug(
                            "Channel {} marked ON via status payload '{}'".format(ch, payload))
                elif off_val and payload == off_val:
                    if self.output_states.get(ch) is not False:
                        self.output_states[ch] = False
                        self.logger.debug(
                            "Channel {} marked OFF via status payload '{}'".format(ch, payload))

    def _auth_dict(self):
        if self.login:
            pwd = self.password if self.password else None
            return {"username": self.username, "password": pwd}
        return None

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        """Publish the on or off payload to the control topic for the given channel."""
        try:
            transport = 'websockets' if self.mqtt_use_websockets else 'tcp'

            if state == 'on':
                self.publish.single(
                    self.topic_control,
                    self.options_channels['payload_on'][output_channel],
                    hostname=self.hostname,
                    port=self.port,
                    client_id=self.clientid,
                    keepalive=self.keepalive,
                    auth=self._auth_dict(),
                    transport=transport)
                self.output_states[output_channel] = True
            elif state == 'off':
                self.publish.single(
                    self.topic_control,
                    payload=self.options_channels['payload_off'][output_channel],
                    hostname=self.hostname,
                    port=self.port,
                    client_id=self.clientid,
                    keepalive=self.keepalive,
                    auth=self._auth_dict(),
                    transport=transport)
                self.output_states[output_channel] = False
        except Exception as e:
            self.logger.error("State change error on channel {}: {}".format(output_channel, e))

    def is_on(self, output_channel=0):
        if self.is_setup():
            state = self.output_states.get(output_channel)
            return bool(state) if state is not None else False
        return False

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            for ch in self.options_channels.get('payload_on', {}):
                state_shutdown = self.options_channels['state_shutdown'].get(ch, -1)
                if state_shutdown == 1:
                    self.output_switch('on', output_channel=ch)
                elif state_shutdown == 0:
                    self.output_switch('off', output_channel=ch)

            # Stop status subscriber
            if self.status_client is not None:
                try:
                    self.status_client.loop_stop()
                    self.status_client.disconnect()
                except Exception as err:
                    self.logger.warning("Status subscriber stop error: {}".format(err))
                self.status_client = None

        self.running = False
