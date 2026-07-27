# coding=utf-8
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# Created: 2025-11-03
"""
AoT Input: RAK3172 Valve Controller — Heartbeat Decoder (ChirpStack MQTT)

Subscribes to the RAK3172 valve controller's HB uplink on the ChirpStack v4 MQTT
broker, decodes the heartbeat payload directly, and stores it as measurements.

Subscription topic: application/<appId>/device/<devEui>/event/up

Extracted measurements (channel mapping)
  0: battery_V         Battery voltage (V). Excluded as null when INA219 is absent
  1: node_class        Policy expected class (1=A, 2=B, 3=C)  -> lorawan_mode_manager input_node_class
  2: node_class_actual Actually applied class (1=A, 2=B, 3=C) -> for Class B beacon lock detection
  3: node_hb_min       Current HB period (min)                -> lorawan_mode_manager input_node_hb
  4: uptime_sec        Uptime (sec)
  5: valve_states      3-valve state bitfield (bit1:0=V1, 3:2=V2, 5:4=V3; 0=idle,1=open,2=close)
  6: rssi              Received signal strength (dBm)         -> lorawan_mode_manager input_rssi
  7: snr               Signal-to-noise ratio (dB)             -> lorawan_mode_manager input_snr
  8: class_mismatch    Expected/actual class mismatch flag (0=match, 1=mismatch)
"""

import datetime
import json
import ssl
import threading
import time
from typing import Any, Dict, List, Optional

from flask_babel import lazy_gettext

from aot.config import AOT_DB_PATH
from aot.databases.models import Input, InputChannel
from aot.databases.utils import session_scope
from aot.inputs.base_input import AbstractInput
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.utils import random_alphanumeric

# ----------------------------- AoT metadata -----------------------------

measurements_dict = {
    0: {'measurement': 'electrical_potential', 'unit': 'V',   'name': lazy_gettext('Battery Voltage')},
    1: {'measurement': 'unitless',             'unit': 'none','name': lazy_gettext('End Node Class (Expected)')},
    2: {'measurement': 'unitless',             'unit': 'none','name': lazy_gettext('End Node Class (Actual)')},
    3: {'measurement': 'duration_time',        'unit': 'min', 'name': lazy_gettext('HB Period (min)')},
    4: {'measurement': 'duration_time',        'unit': 's',   'name': lazy_gettext('Uptime (sec)')},
    5: {'measurement': 'unitless',             'unit': 'none','name': lazy_gettext('Valve State Bitfield')},
    6: {'measurement': 'rssi',                 'unit': 'dBm', 'name': 'RSSI'},
    7: {'measurement': 'snr',                  'unit': 'dB',  'name': 'SNR'},
    8: {'measurement': 'unitless',             'unit': 'none','name': lazy_gettext('Class Mismatch Flag')},
    9: {'measurement': 'current',              'unit': 'mA',  'name': lazy_gettext('Battery Current (mA)')},
    10: {'measurement': 'power',               'unit': 'mW',  'name': lazy_gettext('Power (mW)')},
}
channels_dict = {i: {} for i in measurements_dict}

INPUT_INFORMATION = {
    'input_name_unique': 'chirpstack_rak3172_valve_hb',
    'input_manufacturer': 'RAKwireless',
    'input_name': 'RAK3172 Valve Controller: Heartbeat (ChirpStack MQTT)',
    'input_name_short': 'RAK3172 HB',
    'input_library': 'paho-mqtt',
    'measurements_name': 'Battery, LoRa Class, HB Period, Valve States, RSSI, SNR',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext(
        'Directly decodes the RAK3172 valve controller\'s heartbeat (FPort 225) payload from the '
        'ChirpStack v4 MQTT broker and stores battery voltage, node class, HB period, valve states, '
        'and RSSI/SNR. This input is used as the measurement source for lorawan_mode_manager\'s '
        'input_node_class / input_node_hb / input_vbat / input_rssi / input_snr.'
    ),

    'options_enabled': [
        'measurements_select',
        'pre_output'
    ],

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1'),
    ],

    'custom_options': [
        {
            'id': 'mqtt_host',
            'type': 'text',
            'default_value': 'localhost',
            'required': True,
            'name': lazy_gettext('MQTT Host'),
            'phrase': lazy_gettext('ChirpStack MQTT broker hostname or IP address')
        },
        {
            'id': 'mqtt_port',
            'type': 'integer',
            'default_value': 1883,
            'required': True,
            'name': lazy_gettext('MQTT Port'),
            'phrase': lazy_gettext('MQTT port (default 1883)')
        },
        {
            'id': 'mqtt_username',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Username'),
            'phrase': lazy_gettext('Broker authentication username (leave empty if none)')
        },
        {
            'id': 'mqtt_password',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Password'),
            'phrase': lazy_gettext('Broker authentication password')
        },
        {
            'id': 'mqtt_tls_enable',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable TLS'),
            'phrase': lazy_gettext('Whether to use a TLS (SSL) connection')
        },
        {
            'id': 'mqtt_ca_cert',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('CA Certificate Path'),
            'phrase': lazy_gettext('Path to the CA certificate file when using TLS')
        },
        {
            'id': 'mqtt_clientid',
            'type': 'text',
            'default_value': 'aot_rak3172hb_{}'.format(random_alphanumeric(6)),
            'required': True,
            'name': lazy_gettext('Client ID'),
            'phrase': lazy_gettext('Unique MQTT client ID')
        },
        {
            'id': 'app_id',
            'type': 'text',
            'default_value': '+',
            'required': False,
            'name': lazy_gettext('Application ID (MQTT Topic)'),
            'phrase': lazy_gettext('Enter an ID to subscribe to a specific app only. Leave empty to use "+" (all).')
        },
        {
            'id': 'device_eui',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Device EUI Filter'),
            'phrase': lazy_gettext('Process only specific devices. Leave empty to receive all (multiple can be specified, comma-separated).')
        },
        {
            'id': 'decode_base_frame',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': lazy_gettext('Decode Base HB Frame'),
            'phrase': lazy_gettext('Decode the 0xA5 base frame (battery + class) on FPort 225.')
        },
        {
            'id': 'decode_ext_frame',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': lazy_gettext('Decode Ext HB Frame'),
            'phrase': lazy_gettext('Decode the 0xA6 ext frame (HB period, actual class, valve states, etc.) on FPort 225.')
        },
    ]
}

# ----------------------------- Decoding constants -----------------------------

FPORT_HB = 225
SIG_HB = 0xA5
SIG_HB_EXT = 0xA6
BATTERY_MV_INVALID = 0xFFFF   # Sentinel: INA219 absent/failed
CURRENT_MA_INVALID  = 0x7FFF   # Sentinel: INA219 absent/failed (signed 16-bit)


def _cls_code_to_node_class(code: int) -> Optional[int]:
    """Convert firmware cls_code (0=A,1=B,2=C) to the lorawan_mode_manager convention (1=A,2=B,3=C)."""
    return {0: 1, 1: 2, 2: 3}.get(code)


def decode_hb_base(data_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Decode base HB frame.
      5B: [0xA5, flags_hi, flags_lo, bat_mv_hi, bat_mv_lo]
      7B: above + [cur_hi, cur_lo]  (firmware v26.07+, signed int16 mA)

    flags16: bit0=initial, bit1=boot_done, bits5:4=class_id(1=A,2=B,3=C)
    """
    if len(data_bytes) < 5 or data_bytes[0] != SIG_HB:
        return None
    flags16 = (data_bytes[1] << 8) | data_bytes[2]
    bat_mv = (data_bytes[3] << 8) | data_bytes[4]
    class_id = (flags16 >> 4) & 0x03  # 1=A, 2=B, 3=C (already 1-based)

    result: Dict[str, Any] = {
        'initial': bool(flags16 & 0x01),
        'boot_done': bool(flags16 & 0x02),
        'node_class': class_id if 1 <= class_id <= 3 else None,
    }
    bat_v = None
    if bat_mv == BATTERY_MV_INVALID:
        result['battery_V'] = None
    else:
        bat_v = round(bat_mv / 1000.0, 3)
        result['battery_V'] = bat_v

    # 7-byte extension: current_mA (signed int16 BE)
    if len(data_bytes) >= 7:
        cur_raw = (data_bytes[5] << 8) | data_bytes[6]
        if cur_raw >= 0x8000:
            cur_raw -= 0x10000
        if cur_raw != CURRENT_MA_INVALID:
            result['current_mA'] = cur_raw
            if bat_v is not None:
                result['power_mW'] = round(bat_v * cur_raw, 1)

    return result


def decode_hb_ext(data_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Decode ext HB frame (17 bytes):
    [0xA6, up_s*4(LE), flags, last_err, w_iw*2, w_ir*2, w_g*2,
     cls_expected, cls_actual, hb_min, valves]
    """
    if len(data_bytes) < 17 or data_bytes[0] != SIG_HB_EXT:
        return None

    up_sec = (data_bytes[1]
               | (data_bytes[2] << 8)
               | (data_bytes[3] << 16)
               | (data_bytes[4] << 24))
    flags_b = data_bytes[5]
    last_err = data_bytes[6]
    warn_i2c_w = (data_bytes[7] << 8) | data_bytes[8]
    warn_i2c_r = (data_bytes[9] << 8) | data_bytes[10]
    warn_gpio = (data_bytes[11] << 8) | data_bytes[12]
    cls_expected = data_bytes[13]  # 0=A,1=B,2=C
    cls_actual = data_bytes[14]    # 0=A,1=B,2=C (actual LoRa stack value)
    hb_min = data_bytes[15]
    valves = data_bytes[16]

    return {
        'uptime_sec': up_sec,
        'initial': bool(flags_b & 0x01),
        'boot_done': bool(flags_b & 0x02),
        'last_error': last_err,
        'warn_i2c_write': warn_i2c_w,
        'warn_i2c_read': warn_i2c_r,
        'warn_gpio': warn_gpio,
        # lorawan_mode_manager mapping targets
        'node_class': _cls_code_to_node_class(cls_expected),    # policy expected class
        'node_class_actual': _cls_code_to_node_class(cls_actual), # actually applied class
        'class_mismatch': int(cls_expected != cls_actual),
        'node_hb_min': hb_min if hb_min > 0 else None,
        # valve state bitfield
        'valve_states': valves & 0x3F,  # bit5:0 only (GPS bits excluded)
        'gps_present': bool((valves >> 6) & 0x01),
        'gps_power_on': bool((valves >> 7) & 0x01),
    }


# ----------------------------- InputModule -----------------------------

class InputModule(AbstractInput):
    """
    RAK3172 Valve Controller Heartbeat Decoder via ChirpStack MQTT.

    @phase active
    @stability experimental
    @dependency AbstractInput, paho-mqtt
    """

    def __init__(self, input_dev, testing: bool = False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.mqtt_client = None
        self._mqtt_thread: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None

        # Option defaults
        self.mqtt_host: str = 'localhost'
        self.mqtt_port: int = 1883
        self.mqtt_username: str = ''
        self.mqtt_password: str = ''
        self.mqtt_tls_enable: bool = False
        self.mqtt_ca_cert: str = ''
        self.mqtt_clientid: str = ''
        self.app_id: str = '+'
        self.device_eui: str = ''
        self.decode_base_frame: bool = True
        self.decode_ext_frame: bool = True

        self._allowed_euis: List[str] = []
        self.latest_datetime: Optional[datetime.datetime] = None

        # Communication status (AbstractBaseController.comm_*, consumed through
        # InputController.comm_*). Two independent levels are tracked, because
        # they answer different questions:
        #   _comm_connected  — is the MQTT broker link up (transport level)
        #   _comm_last_ts    — when did THIS LoRaWAN node last send a heartbeat
        # The second is the meaningful one for a field device: the broker can be
        # perfectly reachable while the node itself is dead. FPort 225 heartbeats
        # arrive on a known period (decoded as node_hb_min), so their absence is
        # a positive offline signal rather than mere silence.
        self._comm_connected = False
        self._comm_last_ts: Optional[float] = None
        self._comm_hb_period_min: Optional[float] = None
        self._comm_ref_ts = time.time()

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    # --------------- Initialization ---------------

    def initialize(self):
        import paho.mqtt.client as mqtt

        self._stop_event = threading.Event()
        self.latest_datetime = self.input_dev.datetime

        # Correct port/flag types
        try:
            self.mqtt_port = int(self.mqtt_port)
        except Exception:
            self.mqtt_port = 1883

        # Parse DevEUI filter (lowercase, strip separators)
        raw_euis = str(getattr(self, 'device_eui', '') or '')
        self._allowed_euis = [
            ''.join(e.strip().lower().replace(':', '').replace('-', ''))
            for e in raw_euis.split(',') if e.strip()
        ]

        # Build the MQTT subscription topic
        app_id = str(getattr(self, 'app_id', '+') or '+').strip() or '+'
        self._subscribe_topic = f"application/{app_id}/device/+/event/up"

        # paho client
        cid = getattr(self, 'mqtt_clientid', '') or f"AoT-RAK3172HB-{self.unique_id}"
        self.mqtt_client = mqtt.Client(client_id=cid, clean_session=True)
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)

        if self.mqtt_username or self.mqtt_password:
            self.mqtt_client.username_pw_set(
                self.mqtt_username or None, self.mqtt_password or None)

        if bool(getattr(self, 'mqtt_tls_enable', False)):
            try:
                ca = getattr(self, 'mqtt_ca_cert', '') or None
                ctx = ssl.create_default_context(cafile=ca)
                self.mqtt_client.tls_set_context(ctx)
            except Exception as e:
                self.logger.error(f"TLS setup failed: {e}")

        self.mqtt_client.on_connect    = self._on_connect
        self.mqtt_client.on_message    = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()
        self.logger.info(
            f"RAK3172 HB decoder started: {self.mqtt_host}:{self.mqtt_port} "
            f"topic={self._subscribe_topic} filter_euis={self._allowed_euis or 'ALL'}"
        )

    # --------------- MQTT network loop ---------------

    def _mqtt_loop(self):
        if not self.mqtt_client:
            return
        backoff = 1
        while not (self._stop_event and self._stop_event.is_set()):
            try:
                self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
                self.mqtt_client.loop_forever()
                backoff = 1
            except Exception as e:
                self.logger.error(f"MQTT loop error: {e}")
                if self._stop_event and self._stop_event.wait(backoff):
                    break
                backoff = min(backoff * 2, 60)
            else:
                if self._stop_event and (self._stop_event.is_set() or self._stop_event.wait(1)):
                    break

    def _on_connect(self, client, userdata, flags, rc):
        self._comm_connected = (rc == 0)
        if rc == 0:
            client.subscribe(self._subscribe_topic, qos=0)
            self.logger.info(f"MQTT connected, subscribed: {self._subscribe_topic}")
        else:
            self.logger.error(f"MQTT connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._comm_connected = False
        if self._stop_event and self._stop_event.is_set():
            self.logger.debug(f"MQTT shutdown: rc={rc}")
        else:
            self.logger.warning(f"MQTT disconnected (awaiting reconnect): rc={rc}")

    # --------------- Communication status (comm_* contract) ---------------

    # How many missed heartbeats before the node is declared offline. 3 gives
    # the node a couple of chances to be heard (a single lost uplink is normal
    # on LoRaWAN) without dragging the detection out for too long.
    COMM_MISSED_HB_LIMIT = 3
    # Used only until a heartbeat has actually told us the node's period.
    COMM_FALLBACK_HB_MIN = 15.0

    def comm_capable(self) -> bool:
        """True: this node announces itself on a fixed heartbeat (FPort 225), so
        both its presence and its absence are observable."""
        return True

    def comm_last_success(self) -> Optional[float]:
        return self._comm_last_ts

    def comm_is_fault(self, channel=None) -> bool:
        # Transport level first — with the broker link down we are not receiving
        # anything at all, so no heartbeat-age reasoning would be meaningful.
        if not self._comm_connected:
            return True
        period_min = self._comm_hb_period_min or self.COMM_FALLBACK_HB_MIN
        deadline = period_min * 60.0 * self.COMM_MISSED_HB_LIMIT
        if self._comm_last_ts is None:
            # Connected but nothing heard yet. Measure the grace window from
            # controller start, not from a last-success time that doesn't exist
            # — otherwise every node reads as offline right after a restart.
            return (time.time() - self._comm_ref_ts) > deadline
        return (time.time() - self._comm_last_ts) > deadline

    def comm_is_pending(self, channel=None) -> bool:
        return False

    # --------------- Message handling ---------------

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode('utf-8', errors='replace'))
        except Exception as e:
            self.logger.debug(f"JSON parsing failed: {e}")
            return

        # DevEUI filter
        try:
            dev_eui = (data.get('deviceInfo', {}) or {}).get('devEui', '') or ''
            dev_eui_norm = dev_eui.lower().replace(':', '').replace('-', '')
        except Exception:
            dev_eui_norm = ''

        if self._allowed_euis and dev_eui_norm and dev_eui_norm not in self._allowed_euis:
            return

        # Check FPort
        try:
            fport = int(data.get('fPort') or data.get('fport') or 0)
        except Exception:
            fport = 0
        if fport != FPORT_HB:
            return

        # Base64 decode
        try:
            import base64
            raw_b64 = data.get('data', '')
            if not raw_b64:
                return
            payload_bytes = base64.b64decode(raw_b64)
        except Exception as e:
            self.logger.debug(f"payload decode failed: {e}")
            return

        # Timestamp
        dt_utc = self._parse_time(data.get('time'))

        # RSSI/SNR (select the strongest signal from the rxInfo array)
        rssi_val: Optional[float] = None
        snr_val: Optional[float] = None
        try:
            rx_list = data.get('rxInfo') or []
            if rx_list:
                best = max(rx_list, key=lambda r: r.get('rssi', -999) if isinstance(r, dict) else -999)
                if isinstance(best, dict):
                    if best.get('rssi') is not None:
                        rssi_val = float(best['rssi'])
                    if best.get('snr') is not None:
                        snr_val = float(best['snr'])
        except Exception:
            pass

        # Decode payload
        decoded: Optional[Dict[str, Any]] = None
        sig = payload_bytes[0] if payload_bytes else 0

        if sig == SIG_HB and bool(getattr(self, 'decode_base_frame', True)):
            decoded = decode_hb_base(payload_bytes)
        elif sig == SIG_HB_EXT and bool(getattr(self, 'decode_ext_frame', True)):
            decoded = decode_hb_ext(payload_bytes)

        if not decoded:
            self.logger.debug(
                f"decode skipped: sig=0x{sig:02X} len={len(payload_bytes)} "
                f"fport={fport} eui={dev_eui_norm}"
            )
            return

        # Build measurements (channel indices match measurements_dict)
        measurements: Dict[int, Dict] = {}

        def _add(ch: int, value: Optional[float]):
            if value is None:
                return
            m = measurements_dict.get(ch, {})
            measurements[ch] = {
                'measurement': m.get('measurement', 'unitless'),
                'unit': m.get('unit', 'none'),
                'value': float(value),
                'timestamp_utc': dt_utc,
            }

        # A decoded heartbeat from an allowed DevEUI is proof this node is alive.
        # Recorded after all the filters above so another node's traffic (or an
        # undecodable frame) never counts as this input's liveness.
        self._comm_last_ts = time.time()
        try:
            hb_min = decoded.get('node_hb_min')
            if hb_min:
                # The node reports its own heartbeat period, so the staleness
                # deadline adapts to however this node is configured instead of
                # relying on a guessed constant.
                self._comm_hb_period_min = float(hb_min)
        except (TypeError, ValueError):
            pass

        _add(0, decoded.get('battery_V'))
        _add(1, decoded.get('node_class'))
        _add(2, decoded.get('node_class_actual'))
        _add(3, decoded.get('node_hb_min'))
        _add(4, decoded.get('uptime_sec'))
        _add(5, decoded.get('valve_states'))
        _add(6, rssi_val)
        _add(7, snr_val)
        _add(8, decoded.get('class_mismatch'))
        _add(9, decoded.get('current_mA'))
        _add(10, decoded.get('power_mW'))

        # class_mismatch warning log
        if decoded.get('class_mismatch'):
            self.logger.warning(
                f"[{dev_eui_norm}] Class mismatch: "
                f"expected={decoded.get('node_class')} actual={decoded.get('node_class_actual')} "
                f"(possible Class B beacon lock failure)"
            )

        if not measurements:
            return

        try:
            _, measurements = run_input_actions(
                self.unique_id, "", measurements, self.input_dev.log_level_debug)
        except Exception:
            pass

        add_measurements_influxdb(
            self.unique_id, measurements,
            use_same_timestamp=False)

        self.logger.debug(
            f"[{dev_eui_norm}] HB stored sig=0x{sig:02X} "
            f"channels={list(measurements.keys())}"
        )

        # Update latest timestamp in DB
        if self.running and dt_utc:
            try:
                with session_scope(AOT_DB_PATH) as sess:
                    mod = sess.query(Input).filter(
                        Input.unique_id == self.unique_id).first()
                    if mod and (not mod.datetime or mod.datetime < dt_utc):
                        mod.datetime = dt_utc
                        sess.commit()
            except Exception as e:
                self.logger.debug(f"Timestamp save failed: {e}")

    # --------------- Utilities ---------------

    @staticmethod
    def _parse_time(iso: Optional[str]) -> datetime.datetime:
        if not iso:
            return datetime.datetime.utcnow()
        try:
            ts = iso.replace('Z', '+00:00')
            if '.' in ts:
                head, tail = ts.split('.', 1)
                sign = ''
                frac = tail
                for sep in ('+', '-'):
                    if sep in tail:
                        idx = tail.rfind(sep)
                        frac, sign = tail[:idx], sep + tail[idx+1:]
                        break
                frac = (frac + '000000')[:6]
                ts = f"{head}.{frac}{sign}" if sign else f"{head}.{frac}+00:00"
            dt = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f%z')
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except Exception:
            return datetime.datetime.utcnow()

    # --------------- AoT entry points ---------------

    def stop_input(self):
        super().stop_input()
        self._comm_connected = False
        if self._stop_event:
            self._stop_event.set()
        if self.mqtt_client:
            try:
                self.mqtt_client.disconnect()
            except Exception:
                pass
        if self._mqtt_thread and self._mqtt_thread.is_alive():
            self._mqtt_thread.join(timeout=5)
        self.mqtt_client = None
        self._stop_event = None

    def listener(self) -> bool:
        """The MQTT loop is already started in a separate thread in initialize()."""
        return True

    def get_measurement(self):
        """Polling is not used because this is an MQTT push approach."""
        return {}
