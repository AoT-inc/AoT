# coding=utf-8
#
# value_mqtt.py - Output for publishing a value via MQTT
#
import copy

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.outputs.mqtt_publisher import PersistentMqttPublisher
from aot.utils.constraints_pass import constraints_pass_positive_or_zero_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.utils import random_alphanumeric

measurements_dict = {
    0: {
        'measurement': 'unitless',
        'unit': 'none'
    }
}

channels_dict = {
    0: {
        'types': ['value'],
        'measurements': [0]
    }
}

OUTPUT_INFORMATION = {
    'output_name_unique': 'MQTT_PAHO_VALUE',
    'output_name': "{}: MQTT Publish".format(lazy_gettext('Value')),
    'output_library': 'paho-mqtt',
    'output_manufacturer': 'AoT',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['value'],

    'url_additional': 'http://www.eclipse.org/paho/',

    'message': 'Publish a value to an MQTT server.',

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1')
    ],

    'options_enabled': [
        'button_send_value'
    ],

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
            'id': 'off_value',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Off Value'),
            'phrase': 'The value to send when an Off command is given'
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
            'phrase': 'Password for connecting to the server.'
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
    """Publish arbitrary values to an MQTT broker via the paho-mqtt library.

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

        self.setup_output_variables(OUTPUT_INFORMATION)

        self._start_publisher()
        self.output_setup = True

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
        measure_dict = copy.deepcopy(measurements_dict)

        try:
            if state == 'on' and amount is not None:
                value = amount
                new_state = amount
            elif state == 'off':
                value = self.options_channels['off_value'][0]
                new_state = False
            else:
                return

            if self.publisher is None:
                self.logger.error("Publisher not set up; cannot publish")
                return

            # 발행에 실패했으면 상태도 측정값도 남기지 않는다 — 나가지 않은
            # 명령을 기록하면 이후 판단이 전부 어긋난다.
            if not self.publisher.publish(self.options_channels['topic'][0], value):
                return

            self.output_states[output_channel] = new_state
            measure_dict[0]['value'] = value
        except Exception as e:
            self.logger.error("State change error: {}".format(e))
            return

        add_measurements_influxdb(self.unique_id, measure_dict)

    def stop_output(self):
        """Called when Output is stopped.

        이 드라이버는 종료 상태를 발행하지 않는다(원래 동작). 다만 지속 연결
        발행기는 정리해야 백그라운드 네트워크 스레드가 남지 않는다."""
        if self.publisher is not None:
            self.publisher.stop()
            self.publisher = None
        self.running = False

    def is_on(self, output_channel=0):
        if self.is_setup():
            if output_channel is not None and output_channel in self.output_states:
                return self.output_states[output_channel]
            else:
                return self.output_states

    def is_setup(self):
        return self.output_setup
