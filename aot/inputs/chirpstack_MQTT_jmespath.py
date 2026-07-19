# coding=utf-8
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# Created: 2025-10-05
"""
AoT Input: ChirpStack v4 MQTT + JMESPath

- Subscribes to the `application/+/device/+/event/up` topic on the MQTT broker (ChirpStack v4 Gateway to MQTT).
- Applies per-channel JMESPath expressions to received JSON events to extract/store measurements.
- Uses AoT's common pipeline as-is for InfluxDB storage.

Notes
- ChirpStack v4 broker topic: application/<applicationId>/device/<devEui>/event/up
- JMESPath: https://jmespath.org/
- v4 Breaking changes: https://www.chirpstack.io/docs/v4-breaking-changes.html
"""

import datetime
import json
import ssl
import threading

from flask_babel import lazy_gettext

from typing import TYPE_CHECKING, Any, Dict, List, Optional
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
    'input_name_unique': 'chirpstack_mqtt_jmespath',
    'input_manufacturer': 'ChirpStack',
    'input_name': 'ChirpStack: MQTT (Payload JMESPath Expression)',
    'input_name_short': 'ChirpStack MQTT',
    'input_library': 'paho-mqtt, jmespath',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext(
        'Subscribes to the ChirpStack v4 MQTT broker topic (application/+/device/+/event/up) to receive events, '
        'and applies per-channel JMESPath expressions to each event JSON to store measurements. '
        'Examples (https://jmespath.org): object.battery_V, object.battery_pct, '
        'max_by(rxInfo,&rssi).rssi, max_by(rxInfo,&snr).snr, deviceInfo.devEui.'
    ),

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'options_enabled': [
        'measurements_select',
        'period',      # listener-based, so period isn't used for polling, but is
                        # kept for consistency with other sensors' global settings
        'pre_output'   # listener-based, so start_offset is not used
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
            'name': lazy_gettext('MQTT Host'),
            'phrase': lazy_gettext('MQTT broker hostname or IP address (e.g. localhost)')
        },
        {
            'id': 'mqtt_port',
            'type': 'text',
            'default_value': 1883,
            'required': True,
            'name': lazy_gettext('MQTT Port'),
            'phrase': lazy_gettext('MQTT broker port (default 1883, 8883 recommended for TLS)')
        },
        {
            'id': 'mqtt_username',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Username'),
            'phrase': lazy_gettext('Optional: broker authentication username')
        },
        {
            'id': 'mqtt_password',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Password'),
            'phrase': lazy_gettext('Optional: broker authentication password')
        },
        {
            'id': 'mqtt_tls_enable',
            'type': 'bool',
            'default_value': False,
            'required': False,
                       'name': lazy_gettext('Enable TLS'),
            'phrase': lazy_gettext('Whether to use a TLS (SSL) connection (default off)')
        },
        {
            'id': 'mqtt_ca_cert',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('CA Certificate Path'),
            'phrase': lazy_gettext('Optional: path to the CA certificate when using TLS')
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
            'name': lazy_gettext('Keepalive (sec)'),
            'phrase': lazy_gettext('MQTT keepalive in seconds (default 60 sec)')
        },
        {
            'id': 'mqtt_topics',
            'type': 'text',
            'default_value': 'application/+/device/+/event/up',
            'required': True,
            'name': lazy_gettext('Subscribe Topics'),
            'phrase': lazy_gettext('Comma-separated subscription topics (e.g. application/+/device/+/event/up)')
        },
        {
            'id': 'mqtt_qos',
            'type': 'text',
            'default_value': 0,
            'required': False,
            'name': lazy_gettext('QoS'),
            'phrase': lazy_gettext('MQTT QoS level (0, 1, 2)')
        },
        {
            'id': 'device_euis',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Device EUIs (comma-separated)'),
            'phrase': lazy_gettext('Optional: process only specific devices. Enter EUIs separated by commas')
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
            'name': lazy_gettext('JMESPath Expression'),
            'phrase': lazy_gettext('Evaluated against the entire received event (JSON)')
        }
    ]
}


# ----------------------------- Module class -----------------------------

class InputModule(AbstractInput):
    """
    Subscribes to ChirpStack v4 MQTT broker and extracts values via JMESPath expressions.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing: bool = False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.jmespath = None
        self.mqtt_client: Optional["mqtt.Client"] = None
        self._mqtt_thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._compiled_expressions: Dict[int, Optional[Any]] = {}

        # Options
        self.mqtt_host: str = 'localhost'
        self.mqtt_port: int = 1883
        self.mqtt_username: str = ''
        self.mqtt_password: str = ''
        self.mqtt_tls_enable: bool = False
        self.mqtt_ca_cert: str = ''
        self.mqtt_clientid: str = ''
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

    def _coerce_bool(self, value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        try:
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}
        except Exception:
            return default

    def initialize(self):
        import jmespath
        import paho.mqtt.client as mqtt

        self.jmespath = jmespath
        self._stop_event = threading.Event()

        self.log_level_debug = self.input_dev.log_level_debug
        self.interface = self.input_dev.interface
        self.period = self.input_dev.period
        self.latest_datetime = self.input_dev.datetime

        # Normalize option types
        self.mqtt_port = self._coerce_int(getattr(self, 'mqtt_port', 1883), 1883)
        self.mqtt_keepalive = self._coerce_int(getattr(self, 'mqtt_keepalive', 60), 60)
        self.mqtt_qos = max(0, min(2, self._coerce_int(getattr(self, 'mqtt_qos', 0), 0)))
        self.mqtt_tls_enable = self._coerce_bool(getattr(self, 'mqtt_tls_enable', False), False)

        # Channel options
        input_channels = db_retrieve_table_daemon(InputChannel).filter(
            InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        self._compiled_expressions = {}
        channel_exprs = self.options_channels.get('jmespath_expression', {})
        for channel_id, expression in channel_exprs.items():
            if not expression:
                self._compiled_expressions[channel_id] = None
                continue
            try:
                self._compiled_expressions[channel_id] = self.jmespath.compile(expression)
            except Exception as err:
                self.logger.error(f"Invalid JMESPath expression for channel {channel_id}: {expression} ({err})")
                self._compiled_expressions[channel_id] = None

        # Device filters
        try:
            euis_raw = getattr(self, 'device_euis', '')
            self.device_euis = [x.strip() for x in euis_raw.split(',') if x.strip()]
        except Exception:
            self.device_euis = []

        # MQTT client
        cid = getattr(self, 'mqtt_clientid', '') or f"AoT-{self.unique_id}"
        self.mqtt_client = mqtt.Client(client_id=cid, clean_session=True)
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

        if self.mqtt_username or self.mqtt_password:
            self.mqtt_client.username_pw_set(self.mqtt_username or None, self.mqtt_password or None)

        if self.mqtt_tls_enable:
            try:
                ctx = ssl.create_default_context(cafile=self.mqtt_ca_cert or None)
                self.mqtt_client.tls_set_context(ctx)
            except Exception as err:
                self.logger.error(f"Failed to configure TLS context: {err}")

        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        # Start background network loop
        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()

    # --------------- MQTT callbacks ---------------

    def _mqtt_loop(self):
        if not self.mqtt_client:
            return

        backoff = 1
        while not (self._stop_event and self._stop_event.is_set()):
            try:
                self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.mqtt_keepalive)
                self.mqtt_client.loop_forever()
                backoff = 1
            except Exception as e:
                self.logger.error(f"MQTT loop error: {e}")
                if self._stop_event and self._stop_event.wait(backoff):
                    break
                backoff = min(backoff * 2, 60)
            else:
                if self._stop_event and self._stop_event.is_set():
                    break
                if self._stop_event and self._stop_event.wait(1):
                    break

        self.logger.debug("MQTT networking thread exiting")

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
        if self._stop_event and self._stop_event.is_set():
            self.logger.debug(f"MQTT disconnected (shutdown): rc={rc}")
        else:
            self.logger.warning(f"MQTT disconnected: rc={rc}")

    def _parse_time(self, iso: Optional[str]) -> datetime.datetime:
        if not iso:
            return datetime.datetime.utcnow()
        try:
            # Truncate RFC3339 ns -> us, then parse
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

        # Device filter (EUI)
        dev_eui = None
        try:
            dev_eui = data.get('deviceInfo', {}).get('devEui')
        except Exception:
            pass
        if self.device_euis and dev_eui and (dev_eui not in self.device_euis):
            return

        # Timestamp
        dt_utc = self._parse_time(data.get('time'))
        if (not self.latest_datetime) or (self.latest_datetime < dt_utc):
            self.latest_datetime = dt_utc

        # Per-channel JMESPath evaluation
        expr_map = self.options_channels.get('jmespath_expression', {})
        measurements = {}
        for channel in self.channels_measurement:
            jexpr = expr_map.get(channel, '')
            compiled = self._compiled_expressions.get(channel)
            if not compiled:
                if jexpr:
                    self.logger.debug(f"Skipping channel {channel}; expression pre-compilation failed for '{jexpr}'")
                continue
            try:
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

        # Store latest timestamp
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

    def stop_input(self):
        super().stop_input()

        if self._stop_event:
            self._stop_event.set()

        if self.mqtt_client:
            try:
                self.mqtt_client.disconnect()
            except Exception as err:
                self.logger.debug(f"MQTT disconnect raised: {err}")

        if self._mqtt_thread and self._mqtt_thread.is_alive():
            self._mqtt_thread.join(timeout=5)
            self._mqtt_thread = None

        self.mqtt_client = None
        self._stop_event = None

    def listener(self):
        """Listener entry point that AoT runs in the background.
        The MQTT loop is already started in a separate thread in `initialize()`.
        Here we simply return True so the controller recognizes listener mode.
        """
        return True

    def get_measurement(self):
        """Polling is not used (MQTT receive approach)."""
        return {}
