# coding=utf-8
# 2025-10-06
# on_off_chirpstack.py - Output for controlling a device via ChirpStack gRPC (Enqueue)
#
import json

import grpc
from chirpstack_api import api as cs_api

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
    'output_library': 'requests',
    'output_types': ['on_off'],

    'message': "ChirpStack gRPC Enqueue를 사용해 온/오프 다운링크 명령을 전송합니다.",

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [],

    'interfaces': ['API'],

    'custom_options_message': 'ChirpStack 서버 주소, API 키, DevEUI, FPort, 페이로드(ON/OFF)를 입력하세요. 페이로드 형식은 Hex 또는 JSON을 선택할 수 있습니다.',

    'custom_options': [
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': False,
            'name': 'ChirpStack gRPC 서버',
            'phrase': '호스트:포트 형식 (예: 127.0.0.1:8080) 또는 http(s)://호스트:포트'
        },
        {
            'id': 'cs_api_token',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'API Key',
            'phrase': 'JWT 토큰 값을 입력하세요 (Bearer 제외)'
        },
        {
            'id': 'dev_eui',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'DevEUI',
            'phrase': '16자리 16진수 DevEUI (구분자 허용)'
        },
        {
            'id': 'f_port',
            'type': 'integer',
            'default_value': 15,
            'required': False,
            'name': 'FPort',
            'phrase': '명령을 수신할 LoRaWAN FPort'
        },
        {
            'id': 'confirmed',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': 'Confirmed',
            'phrase': '확인형(Confirmed)으로 명령 전송'
        },
        {
            'id': 'payload_format',
            'type': 'select',
            'default_value': 'hex',
            'options_select': [
                ('hex', 'Hex 바이트'),
                ('json', 'JSON 객체(UTF-8 인코딩)')
            ],
            'name': 'Payload Format',
            'phrase': '페이로드 인코딩 형식을 선택하세요'
        },
        {
            'id': 'on_payload',
            'type': 'text',
            'default_value': '000000',
            'required': False,
            'name': 'On Payload',
            'phrase': '예: 010110 (Hex) 또는 JSON 문자열'
        },
        {
            'id': 'off_payload',
            'type': 'text',
            'default_value': '000000',
            'required': False,
            'name': 'off Payload',
            'phrase': '예: 010210 (Hex) 또는 JSON 문자열'
        },
        {
            'id': 'confirm_grace_s',
            'type': 'integer',
            'default_value': 90,
            'required': False,
            'name': '확인 유예(초)',
            'phrase': '업링크 지연 허용시간'
        },
        {
            'id': 'confirm_hard_timeout_s',
            'type': 'integer',
            'default_value': 600,
            'required': False,
            'name': '확정 타임아웃(초)',
            'phrase': '이 시간이 지나도 미확인 시 경고/재조치'
        },
        {
            'id': 'auto_reassert_off',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': '하드 타임아웃 시 OFF 재전송',
            'phrase': 'duration 종료 또는 타임아웃 시 OFF를 다시 보냄'
        }
    ],

    'custom_channel_options': [
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (-1, '아무 동작 안 함'),
                (0, '끄기(OFF)'),
                (1, '켜기(ON)')
            ],
            'name': '시작 시 상태',
            'phrase': 'AoT가 시작될 때 적용할 상태'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (-1, '아무 동작 안 함'),
                (0, '끄기(OFF)'),
                (1, '켜기(ON)')
            ],
            'name': '종료 시 상태',
            'phrase': 'AoT가 종료될 때 적용할 상태'
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': 'Force Command',
            'phrase': '현재 상태와 무관하게 명령을 항상 전송'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': '시작 시 트리거 실행',
            'phrase': '시작 시 출력이 전환되면 트리거 기능 실행'
        }
    ]
}


class OutputModule(AbstractOutput):
    """An output support class that operates an output."""
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
        self.pending = {}          # ch -> {'state': 'on'|'off', 'deadline': ts, 'hard': ts}
        self.last_downlinks = []   # list of dicts {ts,state,fport,confirmed,bytes}

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)

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

    def _schedule_checks(self, ch, state, duration_s=None):
        """Schedule soft/hard confirm checks around the expected STOP time.
        - Soft check: grace window expiry (info-level log only)
        - Hard check: final timeout — optional OFF reassert
        """
        from threading import Timer
        from time import time
        try:
            grace = int(self._opt('confirm_grace_s', 90) or 90)
            hard  = int(self._opt('confirm_hard_timeout_s', 600) or 600)
        except Exception:
            grace, hard = 90, 600

        now = time()
        if duration_s and duration_s > 0:
            hard_deadline = now + float(duration_s) + grace
        else:
            hard_deadline = now + hard

        self.pending[ch] = {'state': state, 'deadline': now + grace, 'hard': hard_deadline}

        def _soft_check():
            p = self.pending.get(ch)
            if not p or p.get('state') != state:
                return
            try:
                self.logger.info(f"[AoT] Pending confirm (soft) ch={ch} state={state}")
            except Exception:
                pass

        def _hard_check():
            p = self.pending.get(ch)
            if not p or p.get('state') != state:
                return
            try:
                self.logger.warning(f"[AoT] Hard timeout waiting confirm ch={ch} state={state}")
            except Exception:
                pass
            if state == 'on' and bool(self._opt('auto_reassert_off', False)):
                try:
                    self._enqueue('off')
                    self.output_states[ch] = False
                    try:
                        self.logger.warning(f"[AoT] Reasserted OFF due to hard-timeout ch={ch}")
                    except Exception:
                        pass
                except Exception:
                    pass
            self.pending.pop(ch, None)

        Timer(grace, _soft_check).start()
        Timer(max(0.1, hard_deadline - now), _hard_check).start()

    def _clear_pending(self, ch):
        try:
            if ch in self.pending:
                self.pending.pop(ch, None)
        except Exception:
            pass

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
                    self.logger.info(f"[AoT] CFG-ACK mode={mode} period_min={period}")
                except Exception:
                    pass
                return

            # 1.5) Valve completion/status on FPORT_STATUS: [0xB0, vid, state]
            if f_port == FPORT_STATUS and len(b) >= 3 and b[0] == 0xB0:
                st = b[2] & 0xFF
                ch = 0
                if st == 1:  # open_done
                    self.output_states[ch] = True
                    self._clear_pending(ch)
                    try:
                        self.logger.info("[AoT] VALVE status -> OPEN_DONE (cleared pending)")
                    except Exception:
                        pass
                elif st == 2:  # close_done
                    self.output_states[ch] = False
                    self._clear_pending(ch)
                    try:
                        self.logger.info("[AoT] VALVE status -> CLOSE_DONE (cleared pending)")
                    except Exception:
                        pass
                return

            # 1.6) Control ACK on FPORT_CTRL_ACK: [0xA0, vid, cmd, sec, ok]
            if f_port == FPORT_CTRL_ACK and len(b) >= 5 and b[0] == 0xA0:
                ok = (b[4] == 1)
                ch = 0
                if ok:
                    # Heuristic: if cmd indicates ON(OPEN) mark on, if STOP/CLOSE mark off
                    cmd = b[2] & 0xFF
                    if cmd == 1:  # OPEN
                        self.output_states[ch] = True
                    elif cmd in (0, 2, 3):  # STOP/CLOSE/ALL_OFF
                        self.output_states[ch] = False
                    self._clear_pending(ch)
                    try:
                        self.logger.info("[AoT] CTRL-ACK ok -> cleared pending")
                    except Exception:
                        pass
                return

            # 2) Control status/done on control port
            #    Heuristic: 2nd byte is state code (0=STOP/OFF, 1=OPEN/ON, 2=CLOSE)
            if f_port == FPORT_CTRL and len(b) >= 2:
                state_code = b[1]
                ch = 0
                if state_code == 1:
                    self.output_states[ch] = True
                    self._clear_pending(ch)
                    try:
                        self.logger.info("[AoT] CTRL status -> ON (cleared pending)")
                    except Exception:
                        pass
                elif state_code in (0, 2):
                    self.output_states[ch] = False
                    self._clear_pending(ch)
                    try:
                        self.logger.info("[AoT] CTRL status -> OFF (cleared pending)")
                    except Exception:
                        pass
                return

            # 3) Heartbeat/status (optional): hook here if your heartbeat embeds valve state
            if f_port == FPORT_HB and len(b) > 0:
                return
        except Exception:
            pass

    def _enqueue_raw(self, f_port, confirmed, payload_bytes):
        server = self._normalize_server()
        token = self._normalize_token()
        dev_eui = self._normalize_deveui()
        if not server or not token or not dev_eui or int(f_port) <= 0 or not payload_bytes:
            return False
        channel = grpc.insecure_channel(server)
        client = cs_api.DeviceServiceStub(channel)
        md = [("authorization", f"Bearer {token}")]
        self._record_enqueue('raw', int(f_port), bool(confirmed), payload_bytes)
        req = cs_api.EnqueueDeviceQueueItemRequest()
        req.queue_item.dev_eui   = dev_eui
        req.queue_item.f_port    = int(f_port)
        req.queue_item.confirmed = bool(confirmed)
        req.queue_item.data      = bytes(payload_bytes)
        client.Enqueue(req, metadata=md)
        return True

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
        try:
            # ensure key exists
            if output_channel not in self.output_states:
                self.output_states[output_channel] = False

            # Extract duration seconds if provided (None if not numeric)
            dur_s = None
            try:
                if output_type in [None, 'sec'] and amount not in [None, '']:
                    dur_s = float(amount)
            except Exception:
                dur_s = None

            ok = False
            if state == 'on':
                ok = bool(self._enqueue('on'))
                self.output_states[output_channel] = True if ok else self.output_states.get(output_channel, False)
                self._schedule_checks(output_channel, 'on', duration_s=dur_s)
            elif state == 'off':
                ok = bool(self._enqueue('off'))
                self.output_states[output_channel] = False if ok else self.output_states.get(output_channel, False)
                self._schedule_checks(output_channel, 'off', duration_s=None)
            msg = 'success' if ok else 'enqueue_failed'
        except Exception as e:
            msg = f'State change error: {e}'
        return msg

    def is_on(self, output_channel=0):
        if not self.is_setup():
            return None
        # return cached state; default to False if channel not present
        try:
            val = self.output_states.get(output_channel, False)
            return bool(val)
        except Exception:
            return False

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