# coding=utf-8
# 2025-10-06
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# on_off_chirpstack.py - Output for controlling a device via ChirpStack gRPC (Enqueue)
#
import base64
import importlib
import json
import subprocess
import sys
import threading
from urllib.parse import urlparse

import requests

try:
    import grpc  # type: ignore[import-not-found]
except ModuleNotFoundError:
    grpc = None

try:
    from chirpstack_api import api as cs_api  # type: ignore[import-not-found]
except ModuleNotFoundError:
    cs_api = None

try:
    import paho.mqtt.client as mqtt  # type: ignore[import-not-found]
except ModuleNotFoundError:
    mqtt = None

_GRPC_INSTALL_LOCK = threading.Lock()
_GRPC_INSTALL_ATTEMPTED = False

# Site-wide downlink pacing is shared with the LoRaWAN class scheduler via
# aot.utils.lorawan_pacing so that valve-control downlinks AND scheduler CFG
# downlinks are paced together on the one half-duplex gateway. See that module.
from aot.utils.lorawan_pacing import MAX_PACE_WAIT_S
from aot.utils.lorawan_pacing import MIN_GLOBAL_DOWNLINK_INTERVAL_S
from aot.utils.lorawan_pacing import pace_send

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

# Known FPorts used by the device sketch (align with valve-control_v1.2.ino)
FPORT_STATUS   = 12  # open/close completion: [0xB0, vid, state]
FPORT_ERROR    = 13  # warn/error: [0xEE, code, detail?]
FPORT_CTRL_ACK = 11  # control ACK: [0xA0, vid, cmd, sec, ok]
FPORT_HB       = 225 # heartbeat/extended telemetry
FPORT_CFG      = 14  # mode/period config (ACK: 0xD1,mode,period)
FPORT_CTRL     = 15  # control open/close/stop

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

# Output information
OUTPUT_INFORMATION = {
    'output_name_unique': 'chirpstack_downlink',
    'output_name': "On/Off: ChirpStack gRPC",
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_library': 'requests, paho-mqtt, grpcio (optional)',
    'output_types': ['on_off'],

    # Expected LoRaWAN round-trip; pre-fills the common "Command Timeout" field.
    #
    # 8 s holds exactly two dispatches once retransmission is floored at the
    # pacing interval (send at t=0, one resend at t=4, each answered by the
    # device's status uplink ~1.7 s later). Widening it would only buy a third
    # attempt, and on a site that is already downlink-saturated more attempts
    # per command is the wrong direction — raising rx2_dr (SF12 -> SF9) is what
    # buys the airtime back. See resend_interval_floor_s() below.
    'command_timeout_default_s': 8,

    'message': (
        "Sends on/off downlink commands via ChirpStack REST/gRPC API. "
        "Attempts gRPC first; falls back to REST (/api/devices/<devEui>/queue) if grpcio/chirpstack-api is not installed or unreachable."
    ),

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'paho', 'paho-mqtt==1.5.1'),
    ],

    'interfaces': ['API'],

    'custom_options_message': 'Enter the ChirpStack server address, API key, DevEUI, FPort, and ON/OFF payload. Payload format can be Hex or JSON.',

    'custom_options': [
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': False,
            'name': 'ChirpStack gRPC Server',
            'phrase': 'Host:port format (e.g., 127.0.0.1:8080) or http(s)://host:port'
        },
        {
            'id': 'cs_api_token',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'API Key',
            'phrase': 'Enter the JWT token value (without Bearer prefix)'
        },
        {
            'id': 'dev_eui',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'DevEUI',
            'phrase': '16-digit hexadecimal DevEUI (separators allowed)'
        },
        {
            'id': 'f_port',
            'type': 'integer',
            'default_value': 15,
            'required': False,
            'name': 'FPort',
            'phrase': lazy_gettext('LoRaWAN FPort on which the command is received')
        },
        {
            'id': 'confirmed',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Confirmed',
            'phrase': 'Send command as confirmed (await acknowledgment)'
        },
        {
            'id': 'payload_format',
            'type': 'select',
            'default_value': 'hex',
            'options_select': [
                ('hex', 'Hex Bytes'),
                ('json', 'JSON Object (UTF-8 encoded)')
            ],
            'name': 'Payload Format',
            'phrase': 'Select the payload encoding format'
        },
        {
            'id': 'on_payload',
            'type': 'text',
            'default_value': '000000',
            'required': False,
            'name': 'On Payload',
            'phrase': 'e.g., 010110 (Hex) or JSON string'
        },
        {
            'id': 'off_payload',
            'type': 'text',
            'default_value': '000000',
            'required': False,
            'name': 'Off Payload',
            'phrase': 'e.g., 010210 (Hex) or JSON string'
        },
        # NOTE: ACK Timeout / Max Retries are unified into the common
        # "Command Timeout (seconds)" field injected for all on/off outputs
        # (see aot/utils/outputs.py). The base state machine derives the resend
        # interval/attempts from that timeout. command_timeout_default_s (below)
        # pre-fills it to the expected LoRaWAN latency.
        {
            'id': 'debug_logging',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Enable Debug Logging',
            'phrase': 'Log connection/enqueue/confirmation notices (INFO/WARNING) for this '
                      'device. Errors are always logged. Leave off in production.'
        }
    ],

    'custom_channel_options': [
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': 'Startup State',
            'phrase': 'State to apply when AoT starts'
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
            'name': 'Shutdown State',
            'phrase': 'State to apply when AoT shuts down'
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': 'Force Command',
            'phrase': 'Always send command regardless of current state'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': 'Trigger Functions at Startup',
            'phrase': 'Execute trigger function when output switches at startup'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Control LoRaWAN devices via ChirpStack gRPC/REST downlink enqueue.

    @phase active
    @stability stable
    @dependency AbstractOutput, requests
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        # Populate attributes (AoT convention) and also keep JSON copy
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], output)
        self.options = self.setup_custom_options_json(OUTPUT_INFORMATION['custom_options'], output) or {}

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

        # Runtime state
        self.output_states = {ch: False for ch in channels_dict.keys()}
        self.output_setup = False
        self.running = False
        self.last_downlinks = []   # list of dicts {ts,state,fport,confirmed,bytes}
        self.grpc_available = False

        # Pending/confirm/retry/timeout is owned by ConfirmableOutputMixin
        # (base). This module only supplies the transport: _dispatch via
        # _enqueue, and device reports via ingest_uplink -> confirm_command.
        # MQTT uplink listener runtime
        self.mqtt_client = None
        self._mqtt_thread = None
        self._mqtt_stop = None

    def _log_info(self, msg):
        """INFO logging gated by the per-device 'Enable Debug Logging' option --
        without this, per-uplink/per-resend notices flood the system log for
        every device on every command/confirmation."""
        if getattr(self, 'debug_logging', False):
            try:
                self.logger.info(msg)
            except Exception:
                pass

    def _log_warning(self, msg):
        """WARNING logging gated the same way as _log_info (see above)."""
        if getattr(self, 'debug_logging', False):
            try:
                self.logger.warning(msg)
            except Exception:
                pass

    def _ensure_grpc_client(self) -> bool:
        global grpc, cs_api, _GRPC_INSTALL_ATTEMPTED
        if grpc and cs_api:
            return True

        if _GRPC_INSTALL_ATTEMPTED:
            return False

        with _GRPC_INSTALL_LOCK:
            if grpc and cs_api:
                return True
            if _GRPC_INSTALL_ATTEMPTED:
                return False
            _GRPC_INSTALL_ATTEMPTED = True
            self._log_info("Installing grpcio/chirpstack-api into AoT environment (once)...")
            try:
                subprocess.check_call([
                    sys.executable, '-m', 'pip', 'install',
                    'grpcio>=1.62.0', 'chirpstack-api>=4.4.0'
                ])
            except Exception as err:
                self._log_warning(f"Automatic gRPC client install failed: {err}")
                _GRPC_INSTALL_ATTEMPTED = False
                return False

            try:
                importlib.invalidate_caches()
                import grpc as _grpc  # type: ignore
                from chirpstack_api import api as _cs_api  # type: ignore
                grpc = _grpc
                cs_api = _cs_api
                self._log_info("gRPC client libraries installed successfully.")
                return True
            except Exception as err:
                self._log_warning(f"gRPC client import failed after install: {err}")
                _GRPC_INSTALL_ATTEMPTED = False
                return False

    def initialize(self):
        """Establish gRPC/REST client and apply startup state for each channel."""
        self.setup_output_variables(OUTPUT_INFORMATION)

        if not (grpc and cs_api):
            self._ensure_grpc_client()

        self.grpc_available = bool(grpc and cs_api)
        if not self.grpc_available:
            try:
                missing = []
                if grpc is None:
                    missing.append('grpcio')
                if cs_api is None:
                    missing.append('chirpstack-api')
                if missing:
                    self._log_warning(
                        f"gRPC client dependencies missing ({', '.join(missing)}); "
                        f"REST fallback will be used.")
            except Exception:
                pass

        # Defensive: some AoT versions populate options in different attributes
        if not hasattr(self, 'options') or self.options is None:
            self.options = getattr(self, 'options_custom', {}) or {}

        raw_server = self._opt('cs_server', None)
        raw_token = self._opt('cs_api_token', None)
        raw_dev = self._opt('dev_eui', None)
        raw_fport = self._opt('f_port', None)

        # Determine minimal required fields for activation (token + dev_eui only)
        missing = []
        if not raw_token:
            missing.append('cs_api_token')
        if not raw_dev:
            missing.append('dev_eui')
        self.output_setup = (len(missing) == 0)
        if not self.output_setup:
            return

        # Activate immediately without waiting for any response
        self.running = True

        # Start the uplink listener so device ACK/status frames close the loop
        # (corrects optimistic state and clears pending confirm checks).
        try:
            self._start_uplink_listener()
        except Exception as err:
            self._log_warning(f"Uplink listener not started: {err}")

        # Execute Startup State best-effort
        try:
            for channel in channels_dict:
                startup = self.options_channels['state_startup'][channel]
                if channel not in self.output_states:
                    self.output_states[channel] = False
                if startup == 1:
                    self.output_switch('on', output_channel=channel)
                    self.output_states[channel] = True
                elif startup == 0:
                    self.output_switch('off', output_channel=channel)
                    self.output_states[channel] = False
                else:
                    continue
                if self.options_channels['trigger_functions_startup'][channel]:
                    try:
                        self.check_triggers(self.unique_id, output_channel=channel)
                    except Exception:
                        pass
        except Exception:
            pass

    def _normalize_server(self):
        srv = (self._opt('cs_server', '') or '').strip()
        if '://' in srv:
            srv = srv.split('://', 1)[1]
        srv = srv.split('/', 1)[0]
        return srv

    def _normalize_token(self):
        tok = (self._opt('cs_api_token', '') or '').strip()
        if tok.lower().startswith('bearer '):
            tok = tok[7:].strip()
        return tok

    def _normalize_deveui(self):
        dev = (self._opt('dev_eui', '') or '').strip()
        dev = ''.join(ch for ch in dev if ch.isalnum())
        return dev.lower()

    def _my_vid(self):
        """The valve id (vid) this output controls, parsed from the ON payload.

        One physical controller (one DevEUI) drives multiple valves; each valve
        is a separate output whose payload's first field carries the vid. Used to
        filter inbound ACK/status uplinks so one valve's frame never flips a
        sibling valve's state. Returns None if the vid cannot be determined.
          - legacy 3-byte: [vid, cmd, sec]            -> vid = b[0]
          - compact 2-byte: [hdr, sec], vid in hdr    -> vid = (b[0] >> 4) & 0x03
        """
        try:
            b = self._payload_bytes('on') or self._payload_bytes('off')
            if not b:
                return None
            if len(b) >= 3:
                return b[0] & 0xFF
            if len(b) == 2:
                return (b[0] >> 4) & 0x03
        except Exception:
            pass
        return None

    def _my_board_ch(self):
        """The (board, ch) this output controls on a RAK3172-C-E relay
        controller, parsed from the ON payload's 4-byte format
        [board, ch, cmd, dur_sec]. One DevEUI can drive up to 64 relay
        channels across 4 boards; each channel is a separate output. Used to
        filter inbound 0xC0 relay-status uplinks so one channel's frame never
        flips a sibling channel's state. Returns (None, None) if the payload
        isn't in this 4-byte board/channel format.
        """
        try:
            b = self._payload_bytes('on') or self._payload_bytes('off')
            if b and len(b) >= 4:
                return b[0] & 0xFF, b[1] & 0xFF
        except Exception:
            pass
        return None, None

    def _opt(self, key, default=None):
        """Resolve option from multiple known containers, preferring non-empty values.
        Order: direct attribute -> self.options -> options_custom -> custom_options -> output.custom_options_json -> output.custom_options
        """
        # 1) Direct attribute (remote_output_on_off.py pattern)
        try:
            if hasattr(self, key):
                val = getattr(self, key)
                if val not in [None, '']:
                    return val
        except Exception:
            pass
        # 2) Dicts in priority order
        containers = []
        try:
            containers.append(self.options)
        except Exception:
            pass
        try:
            containers.append(getattr(self, 'options_custom', {}))
        except Exception:
            pass
        try:
            containers.append(getattr(self, 'custom_options', {}))
        except Exception:
            pass
        try:
            out = getattr(self, 'output', None)
            if out is not None:
                containers.append(getattr(out, 'custom_options_json', {}))
                containers.append(getattr(out, 'custom_options', {}))
        except Exception:
            pass
        for src in containers:
            if isinstance(src, dict) and key in src and src[key] not in [None, '']:
                return src[key]
        return default





    def _record_enqueue(self, state, f_port, confirmed, payload_bytes):
        try:
            from time import time
            self.last_downlinks.append({
                'ts': time(),
                'state': state,
                'fport': f_port,
                'confirmed': bool(confirmed),
                'len': len(payload_bytes or b''),
            })
            # keep only the last 50 records
            if len(self.last_downlinks) > 50:
                self.last_downlinks = self.last_downlinks[-50:]
        except Exception:
            pass

    def _payload_bytes(self, which):
        fmt = (self._opt('payload_format', 'hex') or 'hex').strip().lower()
        raw = (self._opt(f'{which}_payload', '') or '').strip()
        if fmt == 'json':
            try:
                obj = json.loads(raw)
            except Exception:
                obj = raw  # treat as plain string
            s = json.dumps(obj, separators=(',', ':'))
            b = s.encode('utf-8')
            return b
        # default hex
        try:
            b = bytes.fromhex(raw)
        except Exception:
            b = b''
        return b

    def _to_bytes(self, data):
        """Accept bytes/bytearray/str(hex)/str(utf-8 json) and return bytes."""
        if data is None:
            return b''
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, str):
            s = data.strip()
            # try hex first
            try:
                return bytes.fromhex(s)
            except Exception:
                return s.encode('utf-8', errors='replace')
        # fallback
        try:
            return bytes(data)
        except Exception:
            return b''

    # --- ConfirmableOutputMixin hooks (base owns the pending/timeout machine) ---
    def confirmation_capable(self):
        """LoRaWAN devices report actual state via uplink (FP11/FP12), so the
        base state machine treats them as confirmation-capable: it retransmits
        within the window and faults+reverts if the device never confirms."""
        return True

    def resend_interval_floor_s(self):
        """A resend cannot go out faster than the site-wide pacing lets it.

        Every downlink from this module claims a slot from the one global
        limiter, so scheduling retransmissions closer together than that
        interval only queues them up: the timer fires, the send blocks on the
        pacing, and the command's own deadline passes while it waits.
        """
        return MIN_GLOBAL_DOWNLINK_INTERVAL_S

    def _resend_command(self, output_channel, intent_state):
        """In-window retransmission. ChirpStack v4 does NOT auto-retransmit
        unacked downlinks and the RF link drops frames, so the base timer
        resends the SAME command (idempotent for valves) until ingest_uplink()
        confirms. Interval/attempts are derived from the command timeout."""
        try:
            ok = bool(self._enqueue(intent_state))
            self._log_info(
                f"[AoT] resend ch={output_channel} state={intent_state} "
                f"({'ok' if ok else 'enqueue_failed'})")
            return ok
        except Exception:
            return False

    def _mqtt_settings(self):
        """Resolve (host, port) for the ChirpStack MQTT broker.

        Source of truth is the global ChirpStack connection stored in Misc
        (chirpstack_mqtt_host / chirpstack_mqtt_port) — the same broker the
        registered ChirpStack MQTT inputs use. Falls back to deriving the host
        from cs_server (gRPC) on port 1883 so no extra per-output config is
        required.
        """
        host, port = '', 1883
        try:
            from aot.databases.models import Misc
            m = db_retrieve_table_daemon(Misc, entry='first')
            if m is not None:
                host = (m.chirpstack_mqtt_host or '').strip()
                try:
                    port = int(m.chirpstack_mqtt_port or 1883)
                except Exception:
                    port = 1883
        except Exception:
            pass
        if not host:
            # Derive from the gRPC server host as a last resort
            host = (self._normalize_server() or '').split(':', 1)[0] or 'localhost'
        return host, port

    def _start_uplink_listener(self):
        """Subscribe to this device's ChirpStack v4 uplink events over MQTT and
        feed each frame to ingest_uplink() for closed-loop confirmation."""
        if mqtt is None:
            self._log_warning("paho-mqtt not available; uplink confirmation disabled.")
            return

        dev_eui = self._normalize_deveui()
        if not dev_eui:
            return

        host, port = self._mqtt_settings()
        self._mqtt_stop = threading.Event()
        # ChirpStack v4 topic: application/<appId>/device/<devEui>/event/up
        self._uplink_topic = f"application/+/device/{dev_eui}/event/up"

        cid = f"AoT-out-{getattr(self, 'unique_id', dev_eui)}"
        self.mqtt_client = mqtt.Client(client_id=cid, clean_session=True)
        self.mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        self._mqtt_host, self._mqtt_port = host, port
        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()
        self._log_info(
            f"Uplink listener started: {host}:{port} topic={self._uplink_topic}")

    def _mqtt_loop(self):
        if not self.mqtt_client:
            return
        backoff = 1
        while not (self._mqtt_stop and self._mqtt_stop.is_set()):
            try:
                self.mqtt_client.connect(self._mqtt_host, self._mqtt_port, keepalive=60)
                self.mqtt_client.loop_forever()
                backoff = 1
            except Exception as e:
                try:
                    self.logger.error(f"Uplink MQTT loop error: {e}")
                except Exception:
                    pass
                if self._mqtt_stop and self._mqtt_stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 60)
            else:
                if self._mqtt_stop and self._mqtt_stop.is_set():
                    break
                if self._mqtt_stop and self._mqtt_stop.wait(1):
                    break

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            try:
                client.subscribe(self._uplink_topic, qos=0)
                self._log_info(f"Subscribed to uplink: {self._uplink_topic}")
            except Exception as e:
                try:
                    self.logger.error(f"Uplink subscribe error: {e}")
                except Exception:
                    pass
        else:
            try:
                self.logger.error(f"Uplink MQTT connect failed: rc={rc}")
            except Exception:
                pass

    def _on_disconnect(self, client, userdata, rc):
        if not (self._mqtt_stop and self._mqtt_stop.is_set()):
            self._log_warning(f"Uplink MQTT disconnected: rc={rc}")

    def _on_message(self, client, userdata, msg):
        """Decode a ChirpStack v4 uplink event and feed it to ingest_uplink().

        Event JSON carries: deviceInfo.devEui, fPort (int), data (base64 of the
        raw frmPayload).
        """
        try:
            data = json.loads(msg.payload.decode('utf-8', errors='replace'))
        except Exception:
            return

        # Defensive device filter (topic already targets our devEui)
        try:
            ev_eui = (data.get('deviceInfo', {}) or {}).get('devEui')
            if ev_eui and self._normalize_deveui() and \
                    ev_eui.lower() != self._normalize_deveui():
                return
        except Exception:
            pass

        f_port = data.get('fPort')
        b64 = data.get('data')
        if f_port is None or not b64:
            return
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return
        self.ingest_uplink(f_port, raw)

    def ingest_uplink(self, f_port, data):
        """Ingest an uplink event (called by AoT when a device uplink is received).
        Updates cached state and clears pending checks when appropriate.
        """
        try:
            b = self._to_bytes(data)
            if not isinstance(f_port, int):
                try:
                    f_port = int(f_port)
                except Exception:
                    return

            # 1) Config ACK: [0xD1, mode, period]
            if f_port == FPORT_CFG and len(b) >= 3 and b[0] == 0xD1:
                mode = b[1]
                period = b[2]
                setattr(self, 'cfg_mode', mode)
                setattr(self, 'cfg_period_min', period)
                try:
                    self.logger.debug(f"[AoT] CFG-ACK mode={mode} period_min={period}")
                except Exception:
                    pass
                return

            # vid this output controls; frames for other valves on the same
            # controller (same DevEUI) must NOT touch this output's state.
            my_vid = self._my_vid()

            # 1.5) Valve completion/status on FPORT_STATUS: [0xB0, vid, state]
            if f_port == FPORT_STATUS and len(b) >= 3 and b[0] == 0xB0:
                frame_vid = b[1] & 0xFF
                if my_vid is not None and frame_vid != my_vid:
                    return  # belongs to a sibling valve
                st = b[2] & 0xFF
                ch = 0
                if st == 1:  # open_done
                    self.confirm_command(ch, True, 'status')
                    self._log_info(f"[AoT] device confirmed OPEN (status, vid={frame_vid})")
                elif st == 2:  # close_done
                    self.confirm_command(ch, False, 'status')
                    self._log_info(f"[AoT] device confirmed CLOSE (status, vid={frame_vid})")
                return

            # 1.55) Relay status on FPORT_STATUS (RAK3172-C-E board/relay
            # controller, e.g. a pump output): [0xC0, board, state_hi, state_lo,
            # ack_hi, ack_lo] (6 bytes). `state` is the full 16-bit ON/OFF
            # bitmask of every channel on that board; `ack` is a bitmask of the
            # channel(s) this particular update pertains to (just touched by a
            # command or an expired pulse timer) -- distinct from the 3-byte
            # [0xB0, vid, state] valve-controller status frame handled above.
            if f_port == FPORT_STATUS and len(b) >= 6 and b[0] == 0xC0:
                frame_board = b[1] & 0xFF
                my_board, my_ch = self._my_board_ch()
                if my_board is None or my_ch is None or frame_board != my_board:
                    return  # belongs to a different board/output
                ack = ((b[4] & 0xFF) << 8) | (b[5] & 0xFF)
                if not (ack & (1 << my_ch)):
                    return  # this update doesn't concern my channel
                state = ((b[2] & 0xFF) << 8) | (b[3] & 0xFF)
                is_on = bool(state & (1 << my_ch))
                self.confirm_command(0, is_on, 'relay_status')
                self._log_info(
                    f"[AoT] device confirmed {'ON' if is_on else 'OFF'} "
                    f"(relay_status, board={frame_board} ch={my_ch})")
                return

            # 1.6) Control ACK on FPORT_CTRL_ACK: [0xA0, vid, cmd, sec, ok]
            if f_port == FPORT_CTRL_ACK and len(b) >= 5 and b[0] == 0xA0:
                frame_vid = b[1] & 0xFF
                if my_vid is not None and frame_vid != my_vid:
                    return  # belongs to a sibling valve
                ok = (b[4] == 1)
                ch = 0
                if ok:
                    # Heuristic: if cmd indicates ON(OPEN) mark on, if STOP/CLOSE mark off
                    cmd = b[2] & 0xFF
                    if cmd == 1:  # OPEN
                        self.confirm_command(ch, True, 'ctrl_ack')
                    elif cmd in (0, 2, 3):  # STOP/CLOSE/ALL_OFF
                        self.confirm_command(ch, False, 'ctrl_ack')
                    self._log_info(f"[AoT] device ACK received (ctrl_ack, vid={frame_vid})")
                return

            # 2) Control status/done on control port
            #    Heuristic: 2nd byte is state code (0=STOP/OFF, 1=OPEN/ON, 2=CLOSE)
            #    No vid in this frame — skip for multi-valve controllers (vid known)
            #    since authoritative state arrives on FPORT_CTRL_ACK/STATUS instead.
            if f_port == FPORT_CTRL and len(b) >= 2:
                if my_vid is not None:
                    return
                state_code = b[1]
                ch = 0
                if state_code == 1:
                    self.confirm_command(ch, True, 'ctrl_status')
                    self._log_info("[AoT] device confirmed ON (ctrl_status, ch=0)")
                elif state_code in (0, 2):
                    self.confirm_command(ch, False, 'ctrl_status')
                    self._log_info("[AoT] device confirmed OFF (ctrl_status, ch=0)")
                return

            # 3) Heartbeat/status (optional): hook here if your heartbeat embeds valve state
            if f_port == FPORT_HB and len(b) > 0:
                return
        except Exception:
            pass

    def _enqueue_raw(self, f_port, confirmed, payload_bytes):
        token = self._normalize_token()
        dev_eui = self._normalize_deveui()
        f_port_int = int(f_port) if f_port is not None else 0
        if not token or not dev_eui or f_port_int <= 0 or not payload_bytes:
            return False

        self._record_enqueue('raw', f_port_int, bool(confirmed), payload_bytes)

        # Site-wide pacing: wait for the next global send slot so the half-duplex
        # gateway is never flooded and device ACK uplinks have airtime. Shared by
        # ALL chirpstack_downlink outputs (control + retries). The wait happens
        # OUTSIDE any lock so a slow send never stalls the site. A False here
        # means the backlog is deeper than MAX_PACE_WAIT_S: fail the command
        # rather than add to the flood.
        if not pace_send():
            self._log_error(
                "Downlink dropped: site-wide pacing backlog exceeded "
                f"{MAX_PACE_WAIT_S:.0f}s")
            return False
        return self._send_downlink(f_port_int, confirmed, payload_bytes, token, dev_eui)

    def _send_downlink(self, f_port_int, confirmed, payload_bytes, token, dev_eui):
        """Perform the actual gRPC/REST enqueue. Globally paced by _enqueue_raw."""
        if self.grpc_available:
            try:
                channel = grpc.insecure_channel(self._normalize_server())
                client = cs_api.DeviceServiceStub(channel)
                md = [("authorization", f"Bearer {token}")]
                req = cs_api.EnqueueDeviceQueueItemRequest()
                req.queue_item.dev_eui = dev_eui
                req.queue_item.f_port = f_port_int
                req.queue_item.confirmed = bool(confirmed)
                req.queue_item.data = bytes(payload_bytes)
                client.Enqueue(req, metadata=md)
                return True
            except Exception as err:
                self._log_warning(f"gRPC enqueue failed ({err}); attempting REST fallback.")

        server_opt = (self._opt('cs_server', '') or '').strip()
        parsed = urlparse(server_opt if '://' in server_opt else f"http://{server_opt}")
        scheme = parsed.scheme or 'http'
        netloc = parsed.netloc or parsed.path  # path holds host if no scheme supplied
        base_path = parsed.path if parsed.netloc else ''
        base_url = f"{scheme}://{netloc}".rstrip('/')
        api_root = base_path.rstrip('/')
        if api_root == '/api':
            api_root = ''

        queue_path = f"/api/devices/{dev_eui}/queue"
        if api_root:
            queue_urls = [f"{base_url}{api_root}{queue_path}", f"{base_url}{queue_path}"]
        else:
            queue_urls = [f"{base_url}{queue_path}"]

        # Common ChirpStack installs expose REST proxy on :8090 (when gRPC is :8080).
        if ':8080' in base_url:
            alt_base = base_url.replace(':8080', ':8090')
            if api_root:
                queue_urls.append(f"{alt_base}{api_root}{queue_path}")
            queue_urls.append(f"{alt_base}{queue_path}")

        payload_b64 = base64.b64encode(bytes(payload_bytes)).decode('ascii')
        body = {
            "deviceQueueItem": {
                "confirmed": bool(confirmed),
                "data": payload_b64,
                "devEui": dev_eui,
                "fPort": f_port_int
            }
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        last_err = None
        for url in queue_urls:
            try:
                response = requests.post(url, json=body, timeout=15, headers=headers)
                response.raise_for_status()
                return True
            except requests.HTTPError as http_err:
                last_err = http_err
                if http_err.response is not None and http_err.response.status_code == 404:
                    continue  # try next candidate (likely wrong port/path)
                break
            except Exception as err:
                last_err = err
                break

        try:
            self.logger.error(f"REST enqueue failed: {last_err}")
        except Exception:
            pass
        return False

    def _enqueue(self, desired_state):
        server = self._normalize_server()
        token = self._normalize_token()
        dev_eui = self._normalize_deveui()
        f_port_raw = self._opt('f_port', None)
        f_port = int(f_port_raw) if f_port_raw not in [None, ''] else 0
        confirmed = bool(self._opt('confirmed', False))
        payload = self._payload_bytes('on' if desired_state == 'on' else 'off')
        if not server or not token or not dev_eui or f_port <= 0 or not payload:
            return False
        return self._enqueue_raw(f_port, confirmed, payload)

    def set_mode_period(self, mode: int, period_min: int, confirmed: bool = False):
        """Enqueue CFG command (0xD0, mode, period) on FPORT_CFG.
        Returns True on success, False otherwise.
        """
        try:
            m = int(mode) & 0xFF
            p = int(period_min) & 0xFF
            payload = bytes([0xD0, m, p])
            return self._enqueue_raw(FPORT_CFG, bool(confirmed), payload)
        except Exception:
            return False

    def enqueue_hex(self, f_port: int, hex: str, confirmed: bool = False):
        """Enqueue an arbitrary hex payload to the given FPort.
        Example: enqueue_hex(14, 'D0 01 0F', False)
        """
        try:
            s = ''.join(ch for ch in (hex or '') if ch not in [' ', '\n', '\t', '\r'])
            payload = bytes.fromhex(s)
        except Exception:
            payload = b''
        return self._enqueue_raw(int(f_port), bool(confirmed), payload)

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        """Enqueue an on/off downlink command and hand off to the base state
        machine (pending window, retransmission, timeout fault/revert, and
        confirmation via ingest_uplink -> confirm_command)."""
        try:
            # ensure key exists
            if output_channel not in self.output_states:
                self.output_states[output_channel] = False

            prev_state = self.output_states.get(output_channel, False)

            ok = False
            if state in ('on', 'off'):
                ok = bool(self._enqueue(state))
                # begin_command sets the optimistic state and arms the window
                # only when the dispatch actually succeeded (no phantom 'on').
                self.begin_command(output_channel, state, prev_state, dispatched_ok=ok)
            if not ok:
                self._log_warning(
                    f"[AoT] enqueue failed ch={output_channel} state={state}; "
                    f"not arming pending/intent (no command was actually sent)")
            msg = 'success' if ok else 'enqueue_failed'
        except Exception as e:
            msg = f'State change error: {e}'
        return msg

    # is_pending() is provided by ConfirmableOutputMixin.

    def is_on(self, output_channel=0):
        if not self.is_setup():
            return None
        # Base resolves: intended state during the pending window, then the
        # device-confirmed state once reported, else the optimistic value.
        return self.resolve_is_on(
            output_channel, self.output_states.get(output_channel, False))

    def is_setup(self):
        if getattr(self, 'output_setup', False):
            return True
        # Fallback: treat token+dev presence as setup
        return bool(self._opt('cs_api_token', None) and self._opt('dev_eui', None))

    # Convenience alias for AoT event bus
    on_device_uplink = ingest_uplink

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            for channel in channels_dict:
                if self.options_channels['state_shutdown'][channel] == 1:
                    self.output_switch('on', output_channel=channel)
                elif self.options_channels['state_shutdown'][channel] == 0:
                    self.output_switch('off', output_channel=channel)
        self.running = False

        # Tear down the uplink listener
        try:
            if self._mqtt_stop:
                self._mqtt_stop.set()
            if self.mqtt_client:
                try:
                    self.mqtt_client.disconnect()
                except Exception:
                    pass
            if self._mqtt_thread and self._mqtt_thread.is_alive():
                self._mqtt_thread.join(timeout=5)
        except Exception:
            pass
        finally:
            self.mqtt_client = None
            self._mqtt_thread = None
            self._mqtt_stop = None
