# coding=utf-8
#
# on_off_mqtt.py - Output for publishing on or off via MQTT
#
from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.outputs.mqtt_publisher import PersistentMqttPublisher
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
    'output_name_unique': 'MQTT_PAHO',
    'output_name': "{}: MQTT Publish".format(lazy_gettext('On/Off')),
    'output_manufacturer': 'AoT',
    'output_library': 'paho-mqtt',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'url_additional': 'http://www.eclipse.org/paho/',

    'message': 'Publish "on" or "off" (or any other strings of your choosing) to an MQTT server.',

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1')
    ],

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['IP'],

    'custom_channel_options': [
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
            'id': 'topic',
            'type': 'text',
            'default_value': 'paho/test/single',
            'required': True,
            'name': 'Topic',
            'phrase': 'The topic to publish with'
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
            'id': 'payload_on',
            'type': 'text',
            'default_value': 'on',
            'required': True,
            'name': lazy_gettext('On Payload'),
            'phrase': 'The payload to send when turned on'
        },
        {
            'id': 'payload_off',
            'type': 'text',
            'default_value': 'off',
            'required': True,
            'name': lazy_gettext('Off Payload'),
            'phrase': 'The payload to send when turned off'
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
            'phrase': 'Set the state when AoT starts'
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
            'phrase': 'Set the state when AoT shuts down'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': 'Whether to trigger functions when the output switches at startup'
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
            'id': 'mqtt_use_tls',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Use TLS',
            'phrase': 'Encrypt the connection with TLS (broker port is usually 8883). '
                      'Required when the broker is reachable over the internet.'
        },
        {
            'id': 'mqtt_tls_ca_cert',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('TLS CA Certificate'),
            'phrase': 'Path to the CA certificate file that signed the broker certificate. '
                      'Leave blank to use the system CA store (for brokers with a '
                      'publicly-trusted certificate, e.g. Let\'s Encrypt).'
        },
        {
            'id': 'mqtt_use_websockets',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Use Websockets',
            'phrase': 'Use websockets to connect to the server.'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Publish on/off payloads to an MQTT broker topic via paho-mqtt.

    @phase active
    @stability stable
    @dependency AbstractOutput, paho-mqtt
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.publisher = None

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        """Import paho MQTT client and apply the configured startup state."""

        self.setup_output_variables(OUTPUT_INFORMATION)

        self._start_publisher()
        self.output_setup = True

        if self.options_channels['state_startup'][0] == 1:
            self.output_switch('on')
        elif self.options_channels['state_startup'][0] == 0:
            self.output_switch('off')

        if (self.options_channels['state_startup'][0] in [0, 1] and
                self.options_channels['trigger_functions_startup'][0]):
            try:
                self.check_triggers(self.unique_id, output_channel=0)
            except Exception as err:
                self.logger.error(
                    f"Could not check Trigger for channel 0 of output {self.unique_id}: {err}")

    def _auth_dict(self):
        if self.options_channels['login'][0]:
            pwd = self.options_channels['password'][0] or None
            return {"username": self.options_channels['username'][0], "password": pwd}
        return None

    def _start_publisher(self):
        """Bring up the persistent publish client.

        publish.single() 을 쓰지 않는 이유는 mqtt_publisher.py 의 설명 참고 —
        요약하면 자체 타임아웃이 없어 브로커가 CONNACK 를 주지 않는 오설정에서
        출력 컨트롤러 스레드가 영구 블로킹된다."""
        self.publisher = PersistentMqttPublisher(
            self.logger,
            self.options_channels['hostname'][0],
            self.options_channels['port'][0],
            self.options_channels['clientid'][0],
            keepalive=self.options_channels['keepalive'][0],
            auth=self._auth_dict(),
            tls=self._tls_dict(),
            transport='websockets' if self.options_channels['mqtt_use_websockets'][0] else 'tcp')
        self.publisher.start()

    def _tls_dict(self):
        """TLS settings for paho's publish helper, or None for a plaintext connection.

        ca_certs=None makes paho fall back to the system CA store, which is what
        a publicly-trusted broker certificate needs. A private/self-signed broker
        needs its CA file given explicitly."""
        if not self.options_channels.get('mqtt_use_tls', {}).get(0):
            return None
        return {"ca_certs": self.options_channels.get('mqtt_tls_ca_cert', {}).get(0) or None}

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        """Publish the on or off payload to the configured MQTT topic."""
        try:
            if state == 'on':
                payload = self.options_channels['payload_on'][0]
                new_state = True
            elif state == 'off':
                payload = self.options_channels['payload_off'][0]
                new_state = False
            else:
                return

            if self.publisher is None:
                self.logger.error("Publisher not set up; cannot publish")
                return

            # 발행이 실패하면 상태를 바꾸지 않는다 — 명령이 나가지 않았는데
            # 켜진 것으로 표시되면 그 자체가 위험이다.
            if self.publisher.publish(self.options_channels['topic'][0], payload):
                self.output_states[output_channel] = new_state
        except Exception as e:
            self.logger.error("State change error: {}".format(e))

    def is_on(self, output_channel=0):
        if self.is_setup():
            if output_channel is not None and output_channel in self.output_states:
                return self.output_states[output_channel]
            else:
                return self.output_states

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            if self.options_channels['state_shutdown'][0] == 1:
                self.output_switch('on')
            elif self.options_channels['state_shutdown'][0] == 0:
                self.output_switch('off')
        if self.publisher is not None:
            self.publisher.stop()
            self.publisher = None
        self.running = False
