# coding=utf-8
#
# remote_output_on_off.py - Output for controlling a remote AoT On/Off Output
#
import json
import time
from threading import Thread
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import random

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
    'output_name_unique': 'ecowitt_output',
    'output_name': "ecowitt Output: On/Off",
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_library': 'requests',
    'output_types': ['on_off'],

    'message': 'Ecowitt 장치 IP, 서브디바이스 ID, 모델을 입력해 주세요. WFC01과 WFC02는 모델 1을 사용하고, AC1100은 모델 2를 사용합니다. 저장하면 HTTP IoT API를 통해 로컬 제어가 가능해집니다.',

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'requests', 'requests==2.31.0'),
    ],

    'interfaces': ['API'],

    'custom_options_message': 'Ecowitt 장치 IP, 서브디바이스 ID, 모델을 입력하세요. WFC01과 WFC02는 모델 1을 사용하고, AC1100은 모델 2를 사용합니다. 저장하면 HTTP IoT API를 통해 로컬 제어를 사용할 수 있습니다.',

    'custom_options': [
        {
            'id': 'ecowitt_device_ip',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'Ecowitt Device IP',
            'phrase': 'Local IP address of the Ecowitt hub (e.g., 192.168.4.1)'
        },
        {
            'id': 'state_query_period',
            'type': 'integer',
            'default_value': 120,
            'name': "State Query Period (Seconds)",
            'phrase': '출력 상태를 조회하는 주기(초)'
        },
        {
            'id': 'ecowitt_device_id',
            'type': 'select_custom_choices',
            'default_value': '',
            'custom_choices': [],
            'required': True,
            'name': 'Ecowitt Sub-device ID',
            'phrase': '제어할 WFC01 또는 AC1100의 ID(예: 4371)'
        },
        {
            'id': 'ecowitt_model',
            'type': 'select',
            'default_value': 1,
            'options_select': [
                (1, 'WFC01 / WFC02'),
                (2, 'AC1100')
            ],
            'name': 'Ecowitt Device Model',
            'phrase': 'Model number for Ecowitt device: 1=WFC01 or WFC02, 2=AC1100'
        }
    ],

    'custom_channel_options': [
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': -1,
            'options_select': [(-1, '무동작'), (0, '꺼짐'), (1, '켜짐')],
            'name': lazy_gettext('시작 시 상태'),
            'phrase': 'AoT가 시작될 때 설정할 상태'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': -1,
            'options_select': [(-1, '무동작'), (0, '꺼짐'), (1, '켜짐')],
            'name': lazy_gettext('종료 시 상태'),
            'phrase': 'AoT가 종료될 때 설정할 상태'
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('강제 명령'),
            'phrase': '현재 상태와 상관없이 명령을 항상 전송합니다.'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('시작 시 함수 트리거'),
            'phrase': '시작할 때 출력 상태 변경 시 함수 실행 여부'
        },
        {
            'id': 'confirmation_reads',
            'type': 'integer',
            'default_value': 2,
            'name': '상태 확인 횟수',
            'phrase': '상태 변화 확정 전에 연속으로 동일한 값을 읽는 횟수'
        },
        {
            'id': 'failsafe_timeout',
            'type': 'integer',
            'default_value': 30,
            'name': '펄세이프 타임아웃(초)',
            'phrase': '상태 불명 지속 시 안전한 상태로 전환하기 전까지 대기 시간(초)'
        },
        {
            'id': 'degraded_threshold',
            'type': 'integer',
            'default_value': 5,
            'name': '감소 모드 임계',
            'phrase': '연속 실패 횟수 초과 시 degraded mode로 진입하는 기준'
        }
    ]
}

def normalize_status(raw_status, model, previous_state):
    try:
        if model == 1:  # valve (water_status) covers WFC01 and WFC02
            val = raw_status.get('water_status')
        elif model == 2:  # relay (ac_status)
            val = raw_status.get('ac_status')
        else:
            return previous_state

        if isinstance(val, str):
            low = val.strip().lower()
            if low in ('1', 'true', 'on'):
                val_int = 1
            elif low in ('0', 'false', 'off'):
                val_int = 0
            elif low.isdigit():
                val_int = int(low)
            else:
                return previous_state
        elif isinstance(val, int):
            val_int = val
        else:
            return previous_state

        return True if val_int == 1 else False
    except Exception:
        return previous_state

class OutputModule(AbstractOutput):
    """An output support class that operates an output."""
    def _get_opt(self, key):
        if hasattr(self.output, 'get_option'):
            try:
                return self.output.get_option(key)
            except Exception:
                pass
        opts = getattr(self.output, 'options', None)
        if isinstance(opts, dict):
            return opts.get(key)
        if hasattr(self, 'get_option'):
            try:
                return self.get_option(key)
            except Exception:
                pass
        return None

    def _set_opt(self, key, value):
        if hasattr(self, 'set_option'):
            try:
                self.set_option(key, value)
                return
            except Exception:
                pass
        if hasattr(self.output, 'set_option'):
            try:
                self.output.set_option(key, value)
                return
            except Exception:
                pass
        opts = getattr(self.output, 'options', None)
        if isinstance(opts, dict):
            opts[key] = value
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.state_query_period = None

        self.ecowitt_device_ip = None
        self.ecowitt_device_id = None
        self.ecowitt_model = None

        self.api_output = None
        self.query_timer = 0

        self.setup_custom_options(
            OUTPUT_INFORMATION['custom_options'], output)

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)

        # load Ecowitt local API configuration
        self.ecowitt_device_ip = self._get_opt('ecowitt_device_ip')
        self.ecowitt_device_id = self._get_opt('ecowitt_device_id')
        self.ecowitt_model = self._get_opt('ecowitt_model')
        # Normalize model for WFC02 to model 1 API semantics (WFC01 and WFC02 share model 1)
        # Since option list now combines WFC01 and WFC02 as model 1, no remapping needed here.

        if not self.ecowitt_device_id and self.ecowitt_device_ip:
            candidates = [d for d in self.discover_subdevices() if d.get('model') == int(self.ecowitt_model)]
            if len(candidates) == 1:
                candidate = candidates[0]
                self.ecowitt_device_id = candidate['id']
                self._set_opt('ecowitt_device_id', candidate['id'])
                self.logger.info(f"Auto-selected Ecowitt sub-device ID: {candidate['id']}")
            elif len(candidates) > 1:
                choice_list = [(str(d['id']), f"model {d['model']} id {d['id']}") for d in candidates]
                # Try to set custom option choices if possible, else fallback
                try:
                    self.set_custom_option('ecowitt_device_id', 'custom_choices', choice_list)
                except Exception:
                    self.output.options['ecowitt_device_id_choices'] = choice_list
                    self.logger.info(f"Multiple Ecowitt sub-devices found, choices: {choice_list}")

        if not self.ecowitt_device_ip or not self.ecowitt_device_id or not self.ecowitt_model:
            self.logger.error('Ecowitt device configuration incomplete')
            self.output_setup = False
        else:
            self.output_setup = True

        try:
            if self.output_setup:
                # Set up thread to query output states
                query_states = Thread(target=self.remote_state_query)
                query_states.daemon = True
                query_states.start()

                for channel in channels_dict:
                    if self.options_channels['state_startup'][channel] == 1:
                        self.output_switch("on", output_channel=channel)
                    elif self.options_channels['state_startup'][channel] == 0:
                        self.output_switch("off", output_channel=channel)
                    else:
                        continue

                    startup = 'ON' if self.options_channels['state_startup'][channel] else 'OFF'
                    self.logger.info(f"Output setup and turned {startup}")

                    if self.options_channels['trigger_functions_startup'][channel]:
                        try:
                            self.check_triggers(self.unique_id, output_channel=channel)
                        except Exception as err:
                            self.logger.error(
                                f"Could not check Trigger for channel {channel} of output {self.unique_id}: {err}")
        except Exception as except_msg:
            self.logger.exception(
                "Output was unable to be setup: {err}".format(err=except_msg))

    def get_ecowitt_device_status_for_discovery(self, max_retries=2):
        import requests
        url = f'http://{self.ecowitt_device_ip}/parse_quick_cmd_iot'
        headers = {'Content-Type': 'application/json'}
        payload = {"command":[{"cmd":"read_quick"}]}
        backoff = 1
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=3)
            except Exception as e:
                self.logger.warning(f'Discovery attempt {attempt} error: {e}')
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return {}
            if response.status_code != 200:
                self.logger.warning(f'Discovery attempt {attempt}: status {response.status_code}')
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return {}
            try:
                return response.json()
            except Exception:
                self.logger.warning('Failed to parse discovery response JSON')
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return {}
        return {}

    def discover_subdevices(self):
        raw = self.get_ecowitt_device_status_for_discovery()
        devices = []
        if not raw or 'command' not in raw:
            return devices
        for entry in raw['command']:
            try:
                model = entry.get('model')
                dev_id = entry.get('id')
                if model is None or dev_id is None:
                    continue
                devices.append({'model': int(model), 'id': int(dev_id), 'raw': entry})
            except Exception:
                continue
        return devices

    def remote_state_query(self):
        consecutive_failures = 0
        while self.running:
            status = self.get_ecowitt_device_status()
            prev = self.output_states.get(0, None)
            new_state = normalize_status(status, int(self.ecowitt_model), prev)
            if new_state is None:
                consecutive_failures += 1
                self.logger.debug(f'State normalization failed ({consecutive_failures} consecutive)')
            else:
                consecutive_failures = 0
                self.output_states[0] = new_state
            if consecutive_failures >= 5:
                self.logger.error('Too many consecutive status failures, entering degraded mode')
                time.sleep(10)
            else:
                time.sleep(2)

    def get_ecowitt_device_status(self, max_retries=3):
        import requests
        url = f'http://{self.ecowitt_device_ip}/parse_quick_cmd_iot'
        headers = {'Content-Type': 'application/json'}
        payload = {"command":[{"cmd":"read_device","id":int(self.ecowitt_device_id),"model":int(self.ecowitt_model)}]}
        backoff = 1
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=5)
            except Exception as e:
                self.logger.warning(f'Attempt {attempt}: error contacting Ecowitt device: {e}')
                if attempt < max_retries:
                    time.sleep(backoff + random.random() * 0.5)
                    backoff *= 2
                    continue
                return {}
            if response.status_code != 200:
                self.logger.warning(f'Attempt {attempt}: Ecowitt API returned status {response.status_code}')
                if attempt < max_retries:
                    time.sleep(backoff + random.random() * 0.5)
                    backoff *= 2
                    continue
                return {}
            try:
                resp = response.json()
            except Exception:
                self.logger.warning(f'Attempt {attempt}: failed to parse JSON from Ecowitt response')
                if attempt < max_retries:
                    time.sleep(backoff + random.random() * 0.5)
                    backoff *= 2
                    continue
                return {}
            return resp.get('command', [{}])[0]
        return {}

    def send_remote_output(self, channel, state):
        import requests
        url = f'http://{self.ecowitt_device_ip}/parse_quick_cmd_iot'
        headers = {'Content-Type': 'application/json'}
        payload = {"command":[{"cmd":"quick_run","on_type":0,"off_type":0,"always_on":1,"on_time":0,"off_time":0,"val_type":0,"val":0,"id":int(self.ecowitt_device_id),"model":int(self.ecowitt_model)}]} if state else {"command":[{"cmd":"quick_stop","id":int(self.ecowitt_device_id),"model":int(self.ecowitt_model)}]}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=5)
        except Exception as e:
            self.logger.error(f'Error sending command to Ecowitt device: {e}')
            return False
        if response.status_code != 200:
            self.logger.error(f'Ecowitt command failed with status {response.status_code}')
            return False
        try:
            _ = response.json()
        except Exception:
            self.logger.warning('Failed to parse Ecowitt command response')
        status = self.get_ecowitt_device_status()
        prev = self.output_states.get(channel, None)
        actual = normalize_status(status, int(self.ecowitt_model), prev)
        desired = True if state else False
        if actual is None:
            self.logger.warning('Unable to determine actual state after command')
            return False
        if actual == desired:
            self.output_states[channel] = actual
            return True
        self.logger.warning(f'State mismatch after command. Desired={desired}, Actual={actual}')
        return False

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        success = False
        if state == 'on':
            success = self.send_remote_output(output_channel, True)
        elif state == 'off':
            success = self.send_remote_output(output_channel, False)
        msg = 'success' if success else 'failure'
        if not success:
            self.logger.warning(f'Failed to set state {state} on channel {output_channel}')
        return msg

    def is_on(self, output_channel=0):
        if self.output_setup:
            try:
                return self.output_states[output_channel]
            except Exception as e:
                self.logger.error("Status check error: {}".format(e))

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.output_setup:
            for channel in channels_dict:
                if self.options_channels['state_shutdown'][channel] == 1:
                    self.output_switch('on', output_channel=channel)
                elif self.options_channels['state_shutdown'][channel] == 0:
                    self.output_switch('off', output_channel=channel)
        self.running = False
