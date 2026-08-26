# coding=utf-8
import datetime
import json
import time

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
        {'json_name': 'tempf',        'label': lazy_gettext('Outdoor Temperature')},
        {'json_name': 'humidity',     'label': lazy_gettext('Outdoor Humidity')},
        {'json_name': 'baromabsin',   'label': lazy_gettext('Absolute Pressure')},
        {'json_name': 'baromrelin',   'label': lazy_gettext('Relative Pressure')},
        {'json_name': 'windspeedmph', 'label': lazy_gettext('Wind Speed')},
        {'json_name': 'winddir',      'label': lazy_gettext('Wind Direction')},
        {'json_name': 'solarradiation','label': lazy_gettext('Solar Radiation')},
        {'json_name': 'uv',           'label': lazy_gettext('UV Index')},
        {'json_name': 'rainratein',   'label': lazy_gettext('Precipitation')},
    ],
    'temp_humi_sensor': [
        {'json_name': 'tempf',      'label': lazy_gettext('Temperature')},
        {'json_name': 'humidity',   'label': lazy_gettext('Humidity')},
    ],
    'temp_sensor': [
        {'json_name': 'tempf',      'label': lazy_gettext('Temperature')},
    ],
    'soil_moisture_sensor': [
        {'json_name': 'soilmoisture', 'label': lazy_gettext('Soil Moisture')},
        {'json_name': 'soilbatt',     'label': lazy_gettext('Soil Battery')},
    ],
    'leaf_sensor': [
        {'json_name': 'leafwetness', 'label': lazy_gettext('Leaf Wetness')},
    ],
    'distance_sensor': [
        {'json_name': 'lightningdist', 'label': lazy_gettext('Lightning Distance')},
        {'json_name': 'lightningtime', 'label': lazy_gettext('Lightning Time')},
        {'json_name': 'lightningpower','label': lazy_gettext('Lightning Energy')},
    ],
    'air_quality_sensor': [
        {'json_name': 'pm25',       'label': lazy_gettext('PM2.5 Concentration')},
        {'json_name': 'pm10',       'label': lazy_gettext('PM10 Concentration')},
        {'json_name': 'co2',        'label': lazy_gettext('CO2 Concentration')},
        {'json_name': 'co2_24h',    'label': lazy_gettext('24-hour CO2 Average')},
    ],
    # add other device types as needed
}

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'ecowitt_MQTT',
    'input_manufacturer': 'Ecowitt',
    'input_name': 'Ecowitt MQTT (JSON payload)',
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
        'Subscribes to channels automatically generated based on the selected Ecowitt device type, '
        'extracts values from the URL-encoded or JSON payload sent over the MQTT topic using each '
        'channel\'s JMESPATH expression, and stores them in the database. '
        'Per-channel measurement units and conversion settings can be specified via custom options.'
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
            'name': lazy_gettext('Ecowitt Device'),
            'options_select': [
                ('weather_station', lazy_gettext('Weather Station')),
                ('temp_humi_sensor', lazy_gettext('Temperature/Humidity Sensor')),
                ('temp_sensor', lazy_gettext('Temperature Sensor')),
                ('soil_moisture_sensor', lazy_gettext('Soil Moisture Sensor')),
                ('leaf_sensor', lazy_gettext('Leaf Sensor')),
                ('distance_sensor', lazy_gettext('Distance Sensor')),
                ('air_quality_sensor', lazy_gettext('Air Quality Sensor')),
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

def ecowitt_measurement_options(device):
    """선택한 기기 종류가 내보내는 (json_name, 라벨) 목록.

    예전에는 `current_app.input_dev` 에서 기기를 꺼내려 했는데 Flask 에 그런
    속성이 없다 — 부르는 순간 AttributeError 였고, 실제로 부르는 곳도 없었다.
    기기 종류는 호출자가 넘긴다.
    """
    return [(cfg['json_name'], cfg['label'])
            for cfg in DEVICE_CHANNELS.get(device, [])]


class InputModule(AbstractInput):
    """Sensor driver for Ecowitt devices via MQTT JSON payload.

    Reads variable measurements (temperature, humidity, pressure, wind, rain, etc.) from Ecowitt sensors via MQTT broker.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.log_level_debug = None
        self.client = None
        self.jmespath = None
        self.options_channels = None
        # 'custom_options' 의 ecowitt_device 가 setup_custom_options 로 여기 실린다.
        self.ecowitt_device = None
        # 선택한 기기 종류가 내보내는 json 키 집합 (initialize 에서 한 번 계산).
        self._allowed_json_names = None

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

        # Communication status (comm_* contract) — see comm_is_fault() below.
        self._comm_connected = False
        self._comm_last_ts = None

        if not testing:
            # Load custom options (including ecowitt_device)
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.initialize()
            self.listener()

    def initialize(self):
        import paho.mqtt.client as mqtt
        import jmespath

        self.jmespath = jmespath
        self.log_level_debug = self.input_dev.log_level_debug

        # ── 기기 종류 → 읽을 json 키 ────────────────────────────────────────
        # 예전에는 `self.input_dev.option_get('ecowitt_device')` 로 읽고
        # `add_channel`/`delete_channel` 로 채널을 만들려 했는데 **그 셋 다
        # 이 코드베이스에 존재하지 않는 함수**다. `__init__` 이 initialize() 를
        # 부르므로 이 모듈은 여태 **생성 자체가 불가능**했다(AttributeError).
        # 옵션은 `setup_custom_options` 가 같은 이름의 속성으로 실어 준다.
        device = self.ecowitt_device or ''
        allowed = {cfg['json_name'] for cfg in DEVICE_CHANNELS.get(device, [])}
        self._allowed_json_names = allowed or None

        input_channels = db_retrieve_table_daemon(
            InputChannel).filter(InputChannel.input_id == self.input_dev.unique_id).all()

        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        # ⚠ 거르는 것은 **말하고** 거른다. 선택한 기기 종류에 없는 키를 조용히
        # 버리면 "채널을 만들었는데 값이 안 들어온다" 가 되고, 그때 원인이
        # 어디인지 알 방법이 없다. 판정은 매 메시지가 아니라 여기서 한 번만
        # 한다(초당 여러 번 오는 경로라 메시지마다 찍으면 로그를 덮는다).
        # ERROR 로 남긴다 — 입력 로거는 log_level_debug 가 꺼져 있으면 ERROR 라
        # warning/info 는 기본 설치에서 아무 데도 안 남는다.
        if allowed:
            names = self.options_channels.get('json_name', {}) or {}
            dropped = sorted({str(v) for v in names.values()
                              if v and str(v) not in allowed})
            if dropped:
                self.logger.error(
                    "기기 종류 '%s' 에 없는 채널은 읽지 않습니다: %s. "
                    "기기 종류를 바꾸거나 해당 채널을 지우세요.",
                    device, ', '.join(dropped))

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
        self._comm_connected = (rc == 0)
        self.logger.debug(f"Connected: {rc}")
        self.subscribe()

    def on_disconnect(self, client, userdata, rc):
        self._comm_connected = False
        self.logger.debug(f"Disconnected: {rc}")

    # ------------------------------------------------------------------ #
    # Communication status (AbstractBaseController.comm_*, consumed through
    # InputController.comm_*). Broker-connection state, not "a message arrived
    # recently": these topics carry whatever the publisher decides to send, so
    # a quiet publisher is not a broken link. comm_last_success() still exposes
    # the last message for callers that want their own freshness policy.
    # ------------------------------------------------------------------ #
    def comm_capable(self):
        return True

    def comm_last_success(self):
        return self._comm_last_ts

    def comm_is_fault(self, channel=None):
        return not self._comm_connected

    def comm_is_pending(self, channel=None):
        return False

    def on_subscribe(self, client, obj, mid, granted_qos):
        self.logger.debug("Subscribed to mqtt topic: {}, {}, {}".format(
            self.mqtt_channel, mid, granted_qos))

    def on_log(self, mqttc, obj, level, string):
        self.logger.info("Log: {}".format(string))

    def on_message(self, client, userdata, msg):
        # Any delivered message proves the broker link is alive, recorded before
        # decoding so an undecodable payload still counts as proof of life.
        self._comm_last_ts = time.time()

        # Unified parsing for both JSON and URL-encoded form payloads
        from urllib.parse import parse_qsl, unquote_plus

        try:
            payload = msg.payload.decode(errors='ignore').strip()
        except Exception as exc:
            self.logger.error("Payload could not be decoded: {}".format(exc))
            return
        self.logger.debug("Received message: topic: {}, payload: {}".format(
            msg.topic, payload))

        try:
            if payload.startswith('{') and payload.endswith('}'):
                json_values = json.loads(payload)
            else:
                # URL-encoded key=value&... format
                items = parse_qsl(payload, keep_blank_values=True)
                json_values = {key: unquote_plus(value) for key, value in items}
        except Exception as err:
            self.logger.error("Error parsing payload '{}': {}".format(payload, err))
            return

        allowed = self._allowed_json_names

        datetime_utc = datetime.datetime.utcnow()
        measurement = {}
        for each_channel in self.channels_measurement:
            json_name = self.options_channels['json_name'][each_channel]
            # 선택한 기기 종류에 없는 키는 읽지 않는다. 무엇이 걸러지는지는
            # initialize() 가 이미 한 번 말했다 — 여기서 또 찍으면 로그를 덮는다.
            if allowed is not None and json_name not in allowed:
                continue

            try:
                jmesexpression = self.jmespath.compile(json_name)
                result = jmesexpression.search(json_values)
            except Exception as err:
                self.logger.error("Error in JSON '{}' finding '{}': {}".format(
                    json_values, json_name, err))
                continue

            # ⚠ **0 을 버리지 말 것.** 예전에는 `value == 0` 이면 건너뛰었는데,
            # 이 기기가 내보내는 값의 상당수는 0 이 정상이다 — 밤의 일사·UV,
            # 비가 안 올 때의 강우량, 무풍일 때의 풍속. 그것을 버리면 "값이
            # 가끔 안 들어온다" 가 되고, 더 나쁘게는 **평균과 적산이 0 을 빼고
            # 계산돼** 조용히 부풀려진다. 걸러야 할 것은 0 이 아니라 '없음' 이다.
            if result is None or (isinstance(result, str) and not result.strip()):
                self.logger.debug("Value for {} not found or empty; skipping.".format(json_name))
                continue
            try:
                value = float(result)
            except (TypeError, ValueError):
                self.logger.debug("Non-numeric value for {}: {}; skipping.".format(
                    json_name, result))
                continue

            self.logger.debug("Found key: {}, value: {}".format(json_name, value))
            measurement[each_channel] = {}
            measurement[each_channel]['measurement'] = self.channels_measurement[each_channel].measurement
            measurement[each_channel]['unit'] = self.channels_measurement[each_channel].unit
            measurement[each_channel]['value'] = value
            measurement[each_channel]['timestamp_utc'] = datetime_utc
            measurement = self.check_conversion(each_channel, measurement)

        message, measurement = run_input_actions(self.unique_id, "", measurement, self.log_level_debug)

        self.logger.debug("Adding measurement to influxdb: {}".format(measurement))
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
        self._comm_connected = False
        self.client.loop_stop()
        self.client.disconnect()

    # `reinitialize()` 를 되살리지 말 것 — 유일한 호출자가 존재하지 않는
    # `input_dev.on_option_change(...)` 였다(레포에 그런 함수가 없다). 기기
    # 종류를 바꾸면 Input 저장이 컨트롤러를 재시작하고, 그 과정에서 __init__ →
    # initialize() 가 다시 도므로 따로 손댈 필요가 없다.