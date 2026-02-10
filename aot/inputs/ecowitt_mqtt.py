# coding=utf-8
import datetime
import json

from flask_babel import lazy_gettext
from aot.utils.actions import run_input_actions
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Conversion
from aot.databases.models import InputChannel
from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_measurement
from aot.utils.utils import random_alphanumeric

# Measurements
measurements_dict = {}

# Channels

channels_dict = {
    0: {}
}

# Device to channels mapping for Ecowitt devices
DEVICE_CHANNELS = {
    'weather_station': [
        {'json_name': 'tempf',        'label': '야외 온도'},
        {'json_name': 'humidity',     'label': '야외 습도'},
        {'json_name': 'baromabsin',   'label': '절대 기압'},
        {'json_name': 'baromrelin',   'label': '상대 기압'},
        {'json_name': 'windspeedmph', 'label': '풍속'},
        {'json_name': 'winddir',      'label': '풍향'},
        {'json_name': 'solarradiation','label': '일사량'},
        {'json_name': 'uv',           'label': 'UV 지수'},
        {'json_name': 'rainratein',   'label': '강수량'},
    ],
    'temp_humi_sensor': [
        {'json_name': 'tempf',      'label': '온도'},
        {'json_name': 'humidity',   'label': '습도'},
    ],
    'temp_sensor': [
        {'json_name': 'tempf',      'label': '온도'},
    ],
    'soil_moisture_sensor': [
        {'json_name': 'soilmoisture', 'label': '토양 수분'},
        {'json_name': 'soilbatt',     'label': '토양 배터리'},
    ],
    'leaf_sensor': [
        {'json_name': 'leafwetness', 'label': '잎 습윤도'},
    ],
    'distance_sensor': [
        {'json_name': 'lightningdist', 'label': '번개 거리'},
        {'json_name': 'lightningtime', 'label': '번개 발생 시간'},
        {'json_name': 'lightningpower','label': '번개 에너지'},
    ],
    'air_quality_sensor': [
        {'json_name': 'pm25',       'label': 'PM2.5 농도'},
        {'json_name': 'pm10',       'label': 'PM10 농도'},
        {'json_name': 'co2',        'label': 'CO2 농도'},
        {'json_name': 'co2_24h',    'label': '24시간 CO2 평균'},
    ],
    # add other device types as needed
}

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'ecowitt_MQTT',
    'input_manufacturer': 'Ecowitt',
    'input_name': 'Ecowitt MQTT\(JSON payload)',
    'input_name_short': 'Ecowitt MQTT JSON',
    'input_library': 'paho-mqtt, jmespath',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'options_enabled': [
        'measurements_select',
        'period'
    ],

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'message': lazy_gettext(
        '선택된 Ecowitt 장치 유형에 따라 자동 생성된 채널을 구독하고, '
        'MQTT 토픽으로 전송되는 URL 인코딩 또는 JSON 페이로드에서 각 채널의 JMESPATH 표현식으로 '
        '값을 추출하여 데이터베이스에 저장합니다. '
        '채널별 측정 단위와 변환 설정을 사용자 정의 옵션으로 지정할 수 있습니다.'
    ),

    'interfaces': ['AoT'],

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1'),
        ('pip-pypi', 'jmespath', 'jmespath==0.10.0')
    ],

    'custom_options': [
        {
            'id': 'ecowitt_device',
            'type': 'select',
            'required': True,
            'default_value': 'weather_station',
            'name': 'Ecowitt 장치',
            'options_select': [
                ('weather_station', '기상대'),
                ('temp_humi_sensor', '온습도 센서'),
                ('temp_sensor', '온도 센서'),
                ('soil_moisture_sensor', '토양 수분 센서'),
                ('leaf_sensor', '잎 센서'),
                ('distance_sensor', '거리 측정기'),
                ('air_quality_sensor', '공기질 측정기'),
            ]
        },
        {
            'id': 'mqtt_hostname',
            'type': 'text',
            'default_value': 'localhost',
            'required': True,
            'name': TRANSLATIONS["host"]["title"],
            'phrase': TRANSLATIONS["host"]["phrase"]
        },
        {
            'id': 'mqtt_port',
            'type': 'integer',
            'default_value': 1883,
            'required': True,
            'name': TRANSLATIONS["port"]["title"],
            'phrase': TRANSLATIONS["port"]["phrase"]
        },
        {
            'id': 'mqtt_channel',
            'type': 'text',
            'default_value': 'gw',
            'required': True,
            'name': 'Topic',
            'phrase': 'The topic to subscribe to'
        },
        {
            'id': 'mqtt_keepalive',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Keep Alive'),
            'phrase': 'Maximum amount of time between received signals. Set to 0 to disable.'
        },
        {
            'id': 'mqtt_clientid',
            'type': 'text',
            'default_value': 'client_{}'.format(random_alphanumeric(8)),
            'required': True,
            'name': 'Client ID',
            'phrase': 'Unique client ID for connecting to the server'
        },
        {
            'id': 'mqtt_login',
            'type': 'bool',
            'default_value': False,
            'name': 'Use Login',
            'phrase': 'Send login credentials'
        },
        {
            'id': 'mqtt_use_tls',
            'type': 'bool',
            'default_value': False,
            'name': 'Use TLS',
            'phrase': 'Send login credentials using TLS'
        },
        {
            'id': 'mqtt_username',
            'type': 'text',
            'default_value': 'user',
            'required': False,
            'name': lazy_gettext('Username'),
            'phrase': lazy_gettext('Username for connecting to the server')
        },
        {
            'id': 'mqtt_password',
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

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': TRANSLATIONS['name']['title'],
            'phrase': TRANSLATIONS['name']['phrase']
        },
        {
            'id': 'json_name',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'JMESPATH Expression',
            'phrase': 'JMESPATH expression to find value in JSON response'
        }
    ]
}

# --- Dynamic measurement options for measurements_select ---
def get_ecowitt_measurement_options():
    """
    Return list of (json_name, label) tuples for measurements based on selected Ecowitt device.
    """
    from flask import current_app
    # current input_dev context may provide selected device
    input_dev = current_app.input_dev  # adjust as per framework context
    device = input_dev.option_get('ecowitt_device')
    return [(cfg['json_name'], cfg['label']) for cfg in DEVICE_CHANNELS.get(device, [])]


class InputModule(AbstractInput):
    """A sensor support class that retrieves stored data from MQTT."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.log_level_debug = None
        self.client = None
        self.jmespath = None
        self.options_channels = None

        self.mqtt_hostname = None
        self.mqtt_port = None
        self.mqtt_channel = None
        self.mqtt_keepalive = None
        self.mqtt_clientid = None
        self.mqtt_login = None
        self.mqtt_use_tls = None
        self.mqtt_username = None
        self.mqtt_password = None
        self.mqtt_use_websockets = None

        if not testing:
            # Load custom options (including ecowitt_device)
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            # Immediately initialize channels based on selected device
            self.initialize()
            # Start listener after initialization
            self.listener()
            # Reinitialize channels on device change
            input_dev.on_option_change('ecowitt_device', self.reinitialize)
            self.logger.debug("Bound Ecowitt 장치 change listener")

    def initialize(self):
        import paho.mqtt.client as mqtt
        import jmespath

        self.jmespath = jmespath
        self.log_level_debug = self.input_dev.log_level_debug

        # --- Per-device channel creation ---
        device = self.input_dev.option_get('ecowitt_device')
        # delete existing channels
        existing = db_retrieve_table_daemon(
            InputChannel).filter(InputChannel.input_id == self.input_dev.unique_id).all()
        for ch in existing:
            self.delete_channel(ch.unique_id)
        # add channels defined for this device
        for cfg in DEVICE_CHANNELS.get(device, []):
            self.add_channel(
                name=cfg['label'],
                json_name=cfg['json_name']
            )
        # refresh channel list
        input_channels = db_retrieve_table_daemon(
            InputChannel).filter(InputChannel.input_id == self.input_dev.unique_id).all()

        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        self.client = mqtt.Client(
            self.mqtt_clientid,
            transport='websockets' if self.mqtt_use_websockets else 'tcp')
        self.logger.debug("Client created with ID {}".format(self.mqtt_clientid))
        if self.mqtt_login:
            if not self.mqtt_password:
                self.mqtt_password = None
            self.logger.debug("Sending username and password credentials")
            self.client.username_pw_set(self.mqtt_username, self.mqtt_password)
        if self.mqtt_use_tls:
            self.client.tls_set()

    def listener(self):
        self.callbacks_connect()
        self.connect()
        self.client.loop_start()

    def callbacks_connect(self):
        """Connect the callback functions."""
        try:
            self.logger.debug("Connecting MQTT callback functions")
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_message = self.on_message
            self.client.on_subscribe = self.on_subscribe
            self.logger.debug("MQTT callback functions connected")
        except:
            self.logger.error("Unable to connect mqtt callback functions")

    def connect(self):
        """Set up the connection to the MQTT Server."""
        try:
            self.client.connect(
                self.mqtt_hostname,
                port=self.mqtt_port,
                keepalive=self.mqtt_keepalive)
            self.logger.info("Connected to {} as {}".format(
                self.mqtt_hostname, self.mqtt_clientid))
        except:
            self.logger.error("Could not connect to mqtt host: {}:{}".format(
                self.mqtt_hostname, self.mqtt_port))

    def subscribe(self):
        """Subscribe to the proper MQTT channel to listen to."""
        try:
            self.logger.debug("Subscribing to MQTT topic '{}'".format(
                self.mqtt_channel))
            self.client.subscribe(self.mqtt_channel)
        except:
            self.logger.error("Could not subscribe to MQTT channel '{}'".format(
                self.mqtt_channel))

    def on_connect(self, client, obj, flags, rc):
        self.logger.debug(f"Connected: {rc}")
        self.subscribe()

    def on_disconnect(self, client, userdata, rc):
        self.logger.debug(f"Disconnected: {rc}")

    def on_subscribe(self, client, obj, mid, granted_qos):
        self.logger.debug("Subscribed to mqtt topic: {}, {}, {}".format(
            self.mqtt_channel, mid, granted_qos))

    def on_log(self, mqttc, obj, level, string):
        self.logger.info("Log: {}".format(string))

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode()
            # self.logger.debug(
            #     "Received message: topic: {}, payload: {}".format(
            #         msg.topic, payload))
        except Exception as exc:
            # self.logger.error(
            #     "Payload could not be decoded: {}".format(exc))
            return

        # Unified parsing for both JSON and URL-encoded form payloads
        from urllib.parse import parse_qsl, unquote_plus

        # Determine payload format: JSON or URL form
        raw = msg.payload.decode(errors='ignore')
        payload = raw.strip()
        try:
            if payload.startswith('{') and payload.endswith('}'):
                # JSON format
                json_values = json.loads(payload)
            else:
                # URL-encoded key=value&... format
                items = parse_qsl(payload, keep_blank_values=True)
                json_values = {key: unquote_plus(value) for key, value in items}
        except Exception as err:
            # self.logger.error(
            #     f"Error parsing payload '{payload}': {err}")
            return

        # --- call_back filter logic ---
        device_filter = self.input_dev.option_get('call_back') or ''
        allowed = [cfg['json_name'] for cfg in DEVICE_CHANNELS.get(device_filter, [])] if device_filter else None

        datetime_utc = datetime.datetime.utcnow()
        measurement = {}
        for each_channel in self.channels_measurement:
            json_name = self.options_channels['json_name'][each_channel]
            # apply call_back filter
            if allowed is not None and json_name not in allowed:
                continue
            # self.logger.debug("Searching JSON for {}".format(json_name))

            try:
                jmesexpression = self.jmespath.compile(json_name)
                value = float(jmesexpression.search(json_values))
                # Validate the value
                # if value is None or isinstance(value, str) or value == 0:
                #     self.logger.warning(f"Ignored invalid value for {json_name}: {value}")
                #     continue
                if value is None or isinstance(value, str) or value == 0:
                    continue
                # self.logger.debug(
                #     "Found key: {}, value: {}".format(json_name, value))
                measurement[each_channel] = {}
                measurement[each_channel]['measurement'] = self.channels_measurement[each_channel].measurement
                measurement[each_channel]['unit'] = self.channels_measurement[each_channel].unit
                measurement[each_channel]['value'] = value
                measurement[each_channel]['timestamp_utc'] = datetime_utc
                measurement = self.check_conversion(each_channel, measurement)
            except Exception as err:
                # self.logger.error(
                #     "Error in JSON '{}' finding '{}': {}".format(
                #         json_values, json_name, err))
                pass

        message, measurement = run_input_actions(self.unique_id, "", measurement, self.log_level_debug)

        # self.logger.debug(f"Adding measurement to influxdb: {measurement}")
        add_measurements_influxdb(
            self.unique_id,
            measurement,
            use_same_timestamp=INPUT_INFORMATION['measurements_use_same_timestamp'])

    def check_conversion(self, channel, measurement):
        # Convert value/unit is conversion_id present and valid
        try:
            if self.channels_conversion[channel]:
                conversion = db_retrieve_table_daemon(
                    Conversion,
                    unique_id=self.channels_measurement[channel].conversion_id)
                if conversion:
                    meas = parse_measurement(
                        self.channels_conversion[channel],
                        self.channels_measurement[channel],
                        measurement,
                        channel,
                        measurement[channel],
                        timestamp=measurement[channel]['timestamp_utc'])

                    measurement[channel]['measurement'] = meas[channel]['measurement']
                    measurement[channel]['unit'] = meas[channel]['unit']
                    measurement[channel]['value'] = meas[channel]['value']
        except:
            self.logger.exception("Checking conversion")
        
        return measurement

    def stop_input(self):
        """Called when Input is deactivated."""
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()

    def reinitialize(self, *args, **kwargs):
        """Recreate channels and options on device change."""
        # Stop any running listener
        try:
            self.stop_input()
        except Exception:
            pass
        # Re-run initialization
        self.initialize()
        # Restart listener if needed
        try:
            self.listener()
        except Exception:
            pass