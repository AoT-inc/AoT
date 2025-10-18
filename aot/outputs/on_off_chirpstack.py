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

    def _enqueue(self, desired_state):
        server = self._normalize_server()
        token = self._normalize_token()
        dev_eui = self._normalize_deveui()
        f_port_raw = self._opt('f_port', None)
        f_port = int(f_port_raw) if f_port_raw not in [None, ''] else 0
        confirmed = bool(self._opt('confirmed', False))
        payload = self._payload_bytes('on' if desired_state == 'on' else 'off')

        if not server or not token or not dev_eui or f_port <= 0 or not payload:
            return

        channel = grpc.insecure_channel(server)
        client = cs_api.DeviceServiceStub(channel)
        md = [("authorization", f"Bearer {token}")]

        req = cs_api.EnqueueDeviceQueueItemRequest()
        req.queue_item.dev_eui = dev_eui
        req.queue_item.f_port = f_port
        req.queue_item.confirmed = confirmed
        req.queue_item.data = payload
        resp = client.Enqueue(req, metadata=md)

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        try:
            # ensure key exists
            if output_channel not in self.output_states:
                self.output_states[output_channel] = False
            if state == 'on':
                self._enqueue('on')
                self.output_states[output_channel] = True
            elif state == 'off':
                self._enqueue('off')
                self.output_states[output_channel] = False
            msg = 'success'
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

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            for channel in channels_dict:
                if self.options_channels['state_shutdown'][channel] == 1:
                    self.output_switch('on', output_channel=channel)
                elif self.options_channels['state_shutdown'][channel] == 0:
                    self.output_switch('off', output_channel=channel)
        self.running = False