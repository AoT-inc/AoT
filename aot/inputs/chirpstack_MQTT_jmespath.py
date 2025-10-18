# coding=utf-8
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# 작성일: 2025-10-05
"""
AoT Input: ChirpStack v4 MQTT + JMESPath

- MQTT 브로커(ChirpStack v4 Gateway to MQTT)에서 `application/+/device/+/event/up` 토픽을 구독합니다.
- 수신한 JSON 이벤트에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 추출/저장합니다.
- InfluxDB 저장은 AoT의 공용 파이프라인을 그대로 사용합니다.

참고
- ChirpStack v4 브로커 토픽: application/<applicationId>/device/<devEui>/event/up
- JMESPath: https://jmespath.org/
- v4 Breaking changes: https://www.chirpstack.io/docs/v4-breaking-changes.html
"""

import datetime
import json
import ssl
import threading
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

from aot.config import AOT_DB_PATH
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Conversion, Input, InputChannel
from aot.databases.utils import session_scope
from aot.inputs.base_input import AbstractInput
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_measurement
from aot.utils.utils import random_alphanumeric

# ----------------------------- AoT metadata -----------------------------

measurements_dict = {}
channels_dict = {0: {}}

INPUT_INFORMATION = {
    'input_name_unique': 'CHIRPSTACK_MQTT_JMESPATH',
    'input_manufacturer': 'ChirpStack',
    'input_name': 'ChirpStack: MQTT (Payload JMESPath Expression)',
    'input_name_short': 'ChirpStack MQTT',
    'input_library': 'paho-mqtt, jmespath',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': (
        'ChirpStack v4 MQTT 브로커의 토픽(application/+/device/+/event/up)을 구독하여 이벤트를 수신하고, '
        '각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. '
        '예시(https://jmespath.org): object.battery_V, object.battery_pct, '
        'max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.'
    ),

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'options_enabled': [
        'measurements_select',
        'pre_output'   # listener 기반이므로 period/start_offset은 사용하지 않음
    ],

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1'),
        ('pip-pypi', 'jmespath', 'jmespath==0.10.0'),
    ],

    # Module options
    'custom_options': [
        {
            'id': 'mqtt_host',
            'type': 'text',
            'default_value': 'localhost',
            'required': True,
            'name': 'MQTT Host',
            'phrase': 'MQTT 브로커 호스트명 또는 IP 주소 (예: localhost)'
        },
        {
            'id': 'mqtt_port',
            'type': 'text',
            'default_value': 1883,
            'required': True,
            'name': 'MQTT Port',
            'phrase': 'MQTT 브로커 포트 (기본 1883, TLS는 8883 권장)'
        },
        {
            'id': 'mqtt_username',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'MQTT Username',
            'phrase': '선택 사항: 브로커 인증 사용자 이름'
        },
        {
            'id': 'mqtt_password',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'MQTT Password',
            'phrase': '선택 사항: 브로커 인증 비밀번호'
        },
        {
            'id': 'mqtt_tls_enable',
            'type': 'bool',
            'default_value': False,
            'required': False,
                       'name': 'Enable TLS',
            'phrase': 'TLS(SSL) 연결 사용 여부 (기본 꺼짐)'
        },
        {
            'id': 'mqtt_ca_cert',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'CA Certificate Path',
            'phrase': '선택 사항: TLS 사용 시 CA 인증서 경로'
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
            'id': 'mqtt_keepalive',
            'type': 'text',
            'default_value': 60,
            'required': False,
            'name': 'Keepalive (sec)',
            'phrase': 'MQTT Keepalive 초 (기본 60초)'
        },
        {
            'id': 'mqtt_topics',
            'type': 'text',
            'default_value': 'application/+/device/+/event/up',
            'required': True,
            'name': 'Subscribe Topics',
            'phrase': '콤마(,)로 구분된 구독 토픽들 (예: application/+/device/+/event/up)'
        },
        {
            'id': 'mqtt_qos',
            'type': 'text',
            'default_value': 0,
            'required': False,
            'name': 'QoS',
            'phrase': 'MQTT QoS 레벨 (0, 1, 2)'
        },
        {
            'id': 'device_euis',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Device EUIs (comma-separated)',
            'phrase': '선택 사항: 특정 디바이스만 처리. EUI를 콤마(,)로 구분해 입력'
        },
    ],

    # Per-channel options
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
            'id': 'jmespath_expression',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'JMESPath Expression',
            'phrase': '수신 이벤트 전체(JSON)에 대해 평가합니다'
        }
    ]
}


# ----------------------------- Module class -----------------------------

class InputModule(AbstractInput):
    """Subscribe to ChirpStack MQTT and extract values via JMESPath."""

    def __init__(self, input_dev, testing: bool = False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.jmespath = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self._mqtt_thread: Optional[threading.Thread] = None

        # Options
        self.mqtt_host: str = 'localhost'
        self.mqtt_port: int = 1883
        self.mqtt_username: str = ''
        self.mqtt_password: str = ''
        self.mqtt_tls_enable: bool = False
        self.mqtt_ca_cert: str = ''
        self.mqtt_client_id: str = ''
        self.mqtt_keepalive: int = 60
        self.mqtt_topics: str = 'application/+/device/+/event/up'
        self.mqtt_qos: int = 0
        self.device_euis: List[str] = []

        # Runtime
        self.log_level_debug = None
        self.interface = None
        self.period = None
        self.latest_datetime: Optional[datetime.datetime] = None
        self.options_channels: Dict[str, Dict[int, Any]] = {}

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    # --------------- Initialization helpers ---------------

    def _coerce_int(self, value, default: int) -> int:
        try:
            if value is None:
                return default
            if isinstance(value, int):
                return value
            s = str(value).strip()
            if s == '':
                return default
            return int(float(s))
        except Exception:
            return default

    def initialize(self):
        import jmespath
        self.jmespath = jmespath

        self.log_level_debug = self.input_dev.log_level_debug
        self.interface = self.input_dev.interface
        self.period = self.input_dev.period
        self.latest_datetime = self.input_dev.datetime

        # Normalize ints
        self.mqtt_port = self._coerce_int(getattr(self, 'mqtt_port', 1883), 1883)
        self.mqtt_keepalive = self._coerce_int(getattr(self, 'mqtt_keepalive', 60), 60)
        self.mqtt_qos = max(0, min(2, self._coerce_int(getattr(self, 'mqtt_qos', 0), 0)))

        # Channel options
        input_channels = db_retrieve_table_daemon(InputChannel).filter(
            InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        # Device filters
        try:
            euis_raw = getattr(self, 'device_euis', '')
            self.device_euis = [x.strip() for x in euis_raw.split(',') if x.strip()]
        except Exception:
            self.device_euis = []

        # MQTT client
        cid = self.mqtt_client_id or f"AoT-{self.unique_id}"
        self.mqtt_client = mqtt.Client(client_id=cid, clean_session=True)

        if self.mqtt_username or self.mqtt_password:
            self.mqtt_client.username_pw_set(self.mqtt_username or None, self.mqtt_password or None)

        if self.mqtt_tls_enable:
            ctx = ssl.create_default_context(cafile=self.mqtt_ca_cert or None)
            self.mqtt_client.tls_set_context(ctx)

        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        # Start background network loop
        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()

    # --------------- MQTT callbacks ---------------

    def _mqtt_loop(self):
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.mqtt_keepalive)
            self.mqtt_client.loop_forever()
        except Exception as e:
            self.logger.error(f"MQTT loop error: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            try:
                topics = [t.strip() for t in (self.mqtt_topics or '').split(',') if t.strip()]
                for t in topics:
                    client.subscribe(t, qos=self.mqtt_qos)
                    self.logger.info(f"Subscribed to: {t} (QoS={self.mqtt_qos})")
            except Exception as e:
                self.logger.error(f"Subscribe error: {e}")
        else:
            self.logger.error(f"MQTT connect failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.logger.warning(f"MQTT disconnected: rc={rc}")

    def _parse_time(self, iso: Optional[str]) -> datetime.datetime:
        if not iso:
            return datetime.datetime.utcnow()
        try:
            # RFC3339 ns → us로 절삭 후 파싱
            ts = iso.replace('Z', '+00:00')
            if '.' in ts:
                head, tail = ts.split('.', 1)
                if '+' in tail or '-' in tail:
                    if '+' in tail:
                        frac, tz = tail.split('+', 1)
                        sign = '+' + tz
                    else:
                        frac, tz = tail.split('-', 1)
                        sign = '-' + tz
                else:
                    frac, sign = tail, ''
                frac = (frac + '000000')[:6]
                ts = f"{head}.{frac}{sign}" if sign else f"{head}.{frac}+00:00"
            dt = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f%z')
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except Exception:
            return datetime.datetime.utcnow()

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8', errors='replace')
            data = json.loads(payload)
        except Exception as e:
            self.logger.error(f"Invalid JSON on {msg.topic}: {e}")
            return

        # 디바이스 필터(EUI)
        dev_eui = None
        try:
            dev_eui = data.get('deviceInfo', {}).get('devEui')
        except Exception:
            pass
        if self.device_euis and dev_eui and (dev_eui not in self.device_euis):
            return

        # 타임스탬프
        dt_utc = self._parse_time(data.get('time'))
        if (not self.latest_datetime) or (self.latest_datetime < dt_utc):
            self.latest_datetime = dt_utc

        # 채널별 JMESPath 평가
        measurements = {}
        for channel in self.channels_measurement:
            jexpr = self.options_channels['jmespath_expression'][channel]
            try:
                compiled = self.jmespath.compile(jexpr)
                value = compiled.search(data)
                self.logger.debug(f"Expression: {jexpr}, value: {value}")
            except Exception as err:
                self.logger.error(f"Error evaluating '{jexpr}': {err}")
                continue

            if value is None:
                continue

            measurements[channel] = {}
            measurements[channel]['measurement'] = self.channels_measurement[channel].measurement
            measurements[channel]['unit'] = self.channels_measurement[channel].unit
            measurements[channel]['timestamp_utc'] = dt_utc

            try:
                measurements[channel]['value'] = float(value)
            except Exception:
                self.logger.error(f"Value doesn't represent float: {value}")
                continue

            # Optional conversion
            if self.channels_conversion[channel]:
                conversion = db_retrieve_table_daemon(
                    Conversion, unique_id=self.channels_measurement[channel].conversion_id)
                if conversion:
                    meas = parse_measurement(
                        self.channels_conversion[channel],
                        self.channels_measurement[channel],
                        measurements,
                        channel,
                        measurements[channel],
                        timestamp=dt_utc
                    )
                    measurements[channel]['measurement'] = meas[channel]['measurement']
                    measurements[channel]['unit'] = meas[channel]['unit']
                    measurements[channel]['value'] = float(meas[channel]['value'])

        if measurements:
            message, measurements = run_input_actions(self.unique_id, "", measurements, self.log_level_debug)
            self.logger.debug(f"Adding measurements to influxdb: {measurements}")
            add_measurements_influxdb(
                self.unique_id, measurements,
                use_same_timestamp=INPUT_INFORMATION['measurements_use_same_timestamp'])
        else:
            self.logger.debug("No measurements extracted for this message.")

        # 최신 타임스탬프 저장
        if self.running and self.latest_datetime:
            try:
                with session_scope(AOT_DB_PATH) as new_session:
                    mod_input = new_session.query(Input).filter(Input.unique_id == self.unique_id).first()
                    if not mod_input.datetime or mod_input.datetime < self.latest_datetime:
                        mod_input.datetime = self.latest_datetime
                        new_session.commit()
            except Exception as e:
                self.logger.warning(f"Could not persist latest timestamp: {e}")

    # --------------- AoT entrypoints ---------------

    def listener(self):
        """AoT가 백그라운드로 실행하는 리스너 진입점.
        MQTT 루프는 `initialize()`에서 별도 스레드로 이미 시작합니다.
        여기서는 True만 반환하여 컨트롤러가 listener 모드를 인지하도록 합니다.
        """
        return True

    def get_measurement(self):
        """폴링은 사용하지 않습니다 (MQTT 수신 방식)."""
        return {}