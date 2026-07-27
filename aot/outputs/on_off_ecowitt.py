# coding=utf-8
#
# on_off_ecowitt.py - Minimal On/Off over Ecowitt Local HTTP IoT API
# (GPIO-style layout: single class with __init__, initialize, output_switch, is_on, is_setup, stop_output)
#
import requests
import time
from flask_babel import lazy_gettext

from aot.utils.influx import add_measurements_influxdb

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

# Measurements
measurements_dict = {
    0: {
        'measurement': 'duration_time',
        'unit': 's'
    },
    1: {
        'measurement': 'water_flow_velocity',
        'unit': 'l_min'
    }
}

channels_dict = {
    0: {
        'types': ['on_off'],
        'measurements': [0, 1]
    }
}

# Output information (kept small)
OUTPUT_INFORMATION = {
    'output_name_unique': 'ecowitt_output',
    'output_name': "{}: Ecowitt Local HTTP".format(lazy_gettext('On/Off')),
    'output_library': 'requests',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'message': lazy_gettext('Enter the Ecowitt hub IP, sub-device ID, and model (WFC01/02=1, WFC02 new firmware=3, AC1100=2) to control On/Off via the local HTTP API.'),

    'options_enabled': [
        'button_on'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'requests', 'requests==2.31.0'),
    ],

    'interfaces': ['IP'],

    # Device options kept minimal (GPIO-like)
    'custom_options': [
        {
            'id': 'ecowitt_device_ip',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'Ecowitt Device IP',
            'phrase': 'Local IP address of the Ecowitt hub (e.g., 192.168.1.100)'
        },
        {
            'id': 'ecowitt_device_id',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'Ecowitt Sub-device ID',
            'phrase': 'ID of WFC01/WFC02/AC1100 (e.g., 11044)'
        },
        {
            'id': 'ecowitt_model',
            'type': 'select',
            'default_value': 3,
            'options_select': [
                (1, 'WFC01'),
                (3, 'WFC02'),
                (2, 'AC1100')
            ],
            'name': 'Ecowitt Device Model',
            'phrase': lazy_gettext('1=WFC01/most WFC02, 3=some WFC02 (new firmware), 2=AC1100')
        },
        {
            'id': 'valve_open_percent',
            'type': 'integer',
            'default_value': 100,
            'name': 'Valve Open %',
            'phrase': 'When turning on, open valve to this percent (0-100)'
        },
        {
            'id': 'state_query_period',
            'type': 'integer',
            'default_value': 60,
            'name': "State Query Period (Seconds)",
            'phrase': 'How often to query the state of the output'
        }
    ],

    'custom_channel_options': [
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': 'Set the state when AoT starts'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': 'Set the state when AoT shuts down'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': 'Whether to trigger functions when the output switches at startup'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Control Ecowitt weather station devices via local HTTP API.

    @phase active
    @stability stable
    @dependency AbstractOutput
    """

    # ==== 1) Construction (GPIO-style) ====
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        # Ensure options always exists
        self.options = {}

        # Runtime state
        self.output_setup = False
        self.running = False
        self.last_state = None  # cached bool
        self.query_timer = 0
        self.state_query_period = None
        # Reachability, recorded by _read_status() (the only place that actually
        # talks to the device on a regular basis). None = never attempted yet,
        # so a freshly started output is not reported as failed before its first
        # read. See comm_is_fault() below.
        self._comm_ok = None

        # Populate internal/output option stores; do not assign return (None)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], output)

        # Load channel options (GPIO parity)
        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    # ==== 2) Initialization (GPIO-style) ====
    def initialize(self):
        """Configure Ecowitt device connection and apply startup state."""
        self.setup_output_variables(OUTPUT_INFORMATION)

        # Refresh option stores from DB/UI
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)
        self.logger.debug(f"Post-setup options snapshot: output.options={getattr(self.output, 'options', None)!r}, options_json={getattr(self.output, 'options_json', None)!r}")

        # Prefer attributes populated by setup_custom_options; fall back to _opt
        # Use explicit None check to avoid empty strings (valid default) being ignored by 'or'
        ip = getattr(self, 'ecowitt_device_ip', None)
        if ip is None: ip = self._opt('ecowitt_device_ip')

        dev_id = getattr(self, 'ecowitt_device_id', None)
        if dev_id is None: dev_id = self._opt('ecowitt_device_id')

        model = getattr(self, 'ecowitt_model', None)
        if model is None: model = self._opt('ecowitt_model')

        if isinstance(ip, str):
            ip = ip.strip()
        try:
            if isinstance(dev_id, str):
                dev_id = dev_id.strip()
                if dev_id.isdigit():
                    dev_id = int(dev_id)
            elif isinstance(dev_id, (float, int)):
                dev_id = int(dev_id)
        except Exception:
            dev_id = None
        try:
            if isinstance(model, str):
                model = int(model.strip())
            elif isinstance(model, (float, int)):
                model = int(model)
        except Exception:
            model = None

        self.ip = ip
        self.dev_id = dev_id
        self.model = model

        try:
            self.state_query_period = int(self._opt('state_query_period') or 0)
        except Exception:
            self.state_query_period = 0

        self.logger.debug(
            f"Attr-sourced before parse -> ip={getattr(self, 'ecowitt_device_ip', None)!r}, id={getattr(self, 'ecowitt_device_id', None)!r}, model={getattr(self, 'ecowitt_model', None)!r}")
        self.logger.debug(
            f"Ecowitt config parsed -> ip={self.ip!r}, id={self.dev_id!r}, model={self.model!r}, state_query_period={self.state_query_period!r}")

        if not (self.ip and self.dev_id is not None and self.model is not None):
            missing = []
            if not self.ip: missing.append('ip')
            if self.dev_id is None: missing.append('id')
            if self.model is None: missing.append('model')
            self.logger.error(
                f"Ecowitt device configuration incomplete (missing: {', '.join(missing)}). "
                f"Parsed values: ip={self.ip!r} (missing/empty), id={self.dev_id!r}, model={self.model!r}")
            self.logger.debug(f"Raw options dict: {self.options!r}; output.options: {getattr(self.output, 'options', None)!r}")
            self.output_setup = False
            return

        self.logger.info(f"Ecowitt device configured: ip={self.ip}, id={self.dev_id}, model={self.model}")

        # Mark ready (no threads, keep it simple)
        self.output_setup = True
        self.running = True

        # Immediate first state query to warm the cache
        try:
            self._do_state_query()
        except Exception:
            pass

        # Apply startup state (same pattern as GPIO)
        try:
            if self.options_channels['state_startup'][0] == 1:
                self.output_switch('on', output_channel=0)
            elif self.options_channels['state_startup'][0] == 0:
                self.output_switch('off', output_channel=0)
            if self.options_channels['trigger_functions_startup'][0]:
                try:
                    self.check_triggers(self.unique_id, output_channel=0)
                except Exception as err:
                    self.logger.error(
                        "Could not check Trigger for channel 0 of output {}: {}".format(
                            self.unique_id, err))
            # Start background state query loop (runs after first initialize and then every period)
            if self.state_query_period and self.state_query_period > 0:
                from threading import Thread
                t = Thread(target=self._state_query_loop)
                t.daemon = True
                t.start()
        except Exception as except_msg:
            self.logger.exception(
                "Output was unable to be setup with startup actions: {err}".format(err=except_msg))
            
    def _do_state_query(self):
        if not self.is_setup():
            self.logger.error(f"Cannot query Output {self.unique_id}: Output not set up.")
            return None
        try:
            status = self._read_status()
            state = self._status_to_bool(status)
            if state is not None:
                self.last_state = state
                # Reflect state to server/UI state cache
                try:
                    self.output_states[0] = 1.0 if state else 0.0
                except Exception:
                    pass
            # Parse flow velocity from response and write to measurements
            flow_v = None
            if isinstance(status, dict):
                # Per Ecowitt Local API, the canonical key is 'flow_velocity' (l_min).
                for k in ('flow_velocity', 'wfc02_flow_velocity', 'velocity', 'flow'):
                    if k in status:
                        try:
                            v = status.get(k)
                            if isinstance(v, str):
                                v = v.strip()
                            flow_v = float(v)
                        except Exception:
                            flow_v = None
                        break
            if flow_v is not None:
                try:
                    # Write only the flow velocity measurement (index 1) to InfluxDB in l_min
                    measure_dict = {
                        1: {
                            'measurement': 'water_flow_velocity',
                            'unit': 'l_min',
                            'value': flow_v
                        }
                    }
                    add_measurements_influxdb(self.unique_id, measure_dict)
                except Exception as e:
                    self.logger.error(f"Error writing flow velocity measurement: {e}")
            return bool(self.last_state) if self.last_state is not None else None
        except Exception as e:
            self.logger.error(f"State query error: {e}")
            return bool(self.last_state) if self.last_state is not None else None

    def _state_query_loop(self):
        while self.running:
            now = time.time()
            if self.state_query_period and now >= self.query_timer:
                self._do_state_query()
                self.query_timer = now + int(self.state_query_period)
            time.sleep(1)
    # ==== 3) Public API (GPIO parity) ====
    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        """Send on/off command to the Ecowitt device with lazy initialization."""
        # Lazy initialize if not yet set up
        if not self.is_setup():
            self.logger.debug("Output not set up on first call to output_switch; attempting initialize().")
            try:
                self.initialize()
            except Exception as e:
                self.logger.exception(f"initialize() raised during lazy init: {e}")
        if not self.is_setup():
            self.logger.error(f"Cannot manipulate Output {self.unique_id}: Output not set up.")
            # (code, msg) tuple, not a bare string: base_output._switch_failed()
            # only recognises a non-zero tuple code as failure, so 'failure' was
            # being reported to the UI as a successful switch.
            return 1, f"Cannot manipulate Output {self.unique_id}: Output not set up."
        try:
            if state == 'on':
                try:
                    # Prefer attribute populated by setup_custom_options, then _opt, then provided amount, then 100
                    pos_raw = getattr(self, 'valve_open_percent', None)
                    if pos_raw in (None, ''):
                        pos_raw = self._opt('valve_open_percent')
                    if pos_raw in (None, '') and amount is not None:
                        pos_raw = amount
                    if isinstance(pos_raw, str):
                        pos = int(float(pos_raw.strip()))
                    elif isinstance(pos_raw, (float, int)):
                        pos = int(pos_raw)
                    else:
                        pos = 100
                except Exception:
                    pos = 100
                pos = max(0, min(100, pos))
                self.logger.debug(f"Applying ON with valve_open_percent={pos}")
                ok = self._apply(True, position=pos)
            elif state == 'off':
                ok = self._apply(False)
            else:
                ok = False
            if ok:
                return 'success'
            self.logger.warning(f'Failed to set state {state} on channel {output_channel}')
            return 1, f"Failed to set state {state} on channel {output_channel}"
        except Exception as e:
            msg = f"State change error: {e}"
            self.logger.exception(msg)
            return 1, msg

    def is_on(self, output_channel=0):
        if not self.is_setup():
            self.logger.debug("Output not set up on first call to is_on; attempting initialize().")
            try:
                self.initialize()
            except Exception as e:
                self.logger.exception(f"initialize() raised during lazy init: {e}")
        if not self.is_setup():
            return False
        try:
            status = self._read_status()
            state = self._status_to_bool(status)
            if state is not None:
                self.last_state = state
                return bool(state)
            # Fallback to cached
            return bool(self.last_state) if self.last_state is not None else False
        except Exception as e:
            self.logger.error(f"Status check error: {e}")
            return bool(self.last_state) if self.last_state is not None else False

    def is_setup(self):
        return self.output_setup

    # ------------------------------------------------------------------ #
    # Shared communication-status contract (AbstractBaseController.comm_*)
    #
    # This driver already re-queried the device (_read_status, called from
    # is_on) and even retried failed commands, but none of that reached the UI:
    # a device that had stopped answering kept showing its last cached state.
    # ------------------------------------------------------------------ #
    def comm_capable(self):
        """True: the device is re-queried over HTTP (_read_status)."""
        return True

    def comm_is_fault(self, output_channel=0):
        # None = no read attempted yet (this driver initialises lazily), so fall
        # back to whether setup succeeded rather than claiming a failure we have
        # not actually observed.
        if self._comm_ok is None:
            return not self.output_setup
        return not self._comm_ok

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            if self.options_channels['state_shutdown'][0] == 1:
                self.output_switch('on', output_channel=0)
            elif self.options_channels['state_shutdown'][0] == 0:
                self.output_switch('off', output_channel=0)
        self.running = False

    # ==== 4) Minimal helpers (private) ====
    def _opt(self, key):
        # Ensure self.options always exists
        if not hasattr(self, 'options') or self.options is None:
            self.options = {}
        """Read from multiple option sources with minor alias support, similar to on_off_gpio pin handling."""
        aliases = {
            'ecowitt_device_ip': ['ecowitt_device_ip', 'device_ip', 'ecowitt_ip', 'hub_ip', 'ip'],
            'ecowitt_device_id': ['ecowitt_device_id', 'device_id', 'subdevice_id', 'ecowitt_id', 'id'],
            'ecowitt_model': ['ecowitt_model', 'device_model', 'model']
        }
        alias_keys = aliases.get(key, [key])

        # Check self.options dictionary first
        if isinstance(self.options, dict):
            for k in alias_keys:
                if k in self.options and self.options[k] not in (None, ''):
                    v = self.options[k]
                    if isinstance(v, (list, tuple)) and len(v) > 0:
                        return v[0]
                    return v

        # Check self.output.options dict
        if hasattr(self.output, 'options') and isinstance(self.output.options, dict):
            for k in alias_keys:
                if k in self.output.options and self.output.options[k] not in (None, ''):
                    v = self.output.options[k]
                    if isinstance(v, (list, tuple)) and len(v) > 0:
                        return v[0]
                    return v

        # Check self.output.options_json list/dict
        if hasattr(self.output, 'options_json'):
            opt_json = self.output.options_json
            if isinstance(opt_json, dict):
                for k in alias_keys:
                    if k in opt_json and opt_json[k] not in (None, ''):
                        v = opt_json[k]
                        if isinstance(v, (list, tuple)) and len(v) > 0:
                            return v[0]
                        return v
            elif isinstance(opt_json, (list, tuple)):
                for item in opt_json:
                    if not isinstance(item, dict):
                        continue
                    for k in alias_keys:
                        # Match by id, key, or name
                        if (item.get('id') == k or item.get('key') == k or item.get('name') == k) and item.get('value') not in (None, ''):
                            v = item.get('value')
                            if isinstance(v, (list, tuple)) and len(v) > 0:
                                return v[0]
                            return v

        # Check options_channels dict for the key
        if isinstance(self.options_channels, dict):
            if key in self.options_channels:
                v = self.options_channels[key]
                if isinstance(v, (list, tuple)) and len(v) > 0:
                    return v[0]
                return v

        return None

    def _status_to_bool(self, status_obj):
        """Convert Ecowitt read_device response (cmd object) to boolean."""
        if not isinstance(status_obj, dict):
            return None
        # Model-aware but forgiving
        v = None
        # WFC02 new FW
        if 'wfc02_status' in status_obj:
            v = status_obj.get('wfc02_status')
        # Legacy WFC01/WFC02
        if v is None and 'water_status' in status_obj:
            v = status_obj.get('water_status')
        # Running fallback
        if v is None and 'water_running' in status_obj:
            v = status_obj.get('water_running')
        # AC1100
        if v is None and 'ac_status' in status_obj:
            v = status_obj.get('ac_status')
        if v is None and 'ac_running' in status_obj:
            v = status_obj.get('ac_running')

        if v is None:
            return None
        try:
            if isinstance(v, str):
                v = v.strip().lower()
                if v in ('1', 'true', 'on'): return True
                if v in ('0', 'false', 'off'): return False
                if v.isdigit(): return int(v) == 1
                return None
            if isinstance(v, (int, float)):
                return int(v) == 1
        except Exception:
            return None
        return None

    def _apply(self, turn_on: bool, position: int = 100) -> bool:
        """Send quick_run/quick_stop; then verify with retries via read_device."""
        url = f'http://{self.ip}/parse_quick_cmd_iot'
        headers = {'Content-Type': 'application/json'}
        mid = int(self.model)
        did = int(self.dev_id)

        if turn_on:
            sent = False
            if mid == 3:
                # Attempt 1: try position (newer WFC02 FW supports it, undocumented)
                payload_try1 = {
                    "command": [{
                        "cmd": "quick_run",
                        "always_on": 1,
                        "val_type": 0,
                        "val": 0,
                        "position": int(position),
                        "id": did,
                        "model": mid
                    }]}
                # Attempt 2: spec-compatible fallback (no position)
                payload_try2 = {
                    "command": [{
                        "cmd": "quick_run",
                        "on_type": 0,
                        "off_type": 0,
                        "always_on": 1,
                        "on_time": 0,
                        "off_time": 0,
                        "val_type": 0,
                        "val": 0,
                        "id": did,
                        "model": mid
                    }]}
                # Send try1; on non-200 or error, fall back to try2
                try:
                    r = requests.post(url, json=payload_try1, headers=headers, timeout=5)
                except Exception as e:
                    self.logger.error(f'Error sending command (try1): {e}')
                    r = None
                if not r or r.status_code != 200:
                    try:
                        r = requests.post(url, json=payload_try2, headers=headers, timeout=5)
                    except Exception as e:
                        self.logger.error(f'Error sending command (try2): {e}')
                        return False
                if r.status_code != 200:
                    body = ''
                    try:
                        body = r.text[:200]
                    except Exception:
                        pass
                    self.logger.error(f'Ecowitt command failed: {r.status_code}, body={body}')
                    return False
                # After sending, verify below (common path)
                sent = True
            else:
                payload = {
                    "command": [{
                        "cmd": "quick_run",
                        "on_type": 0,
                        "off_type": 0,
                        "always_on": 1,
                        "on_time": 0,
                        "off_time": 0,
                        "val_type": 0,
                        "val": 0,
                        "id": did,
                        "model": mid
                    }]}
                try:
                    r = requests.post(url, json=payload, headers=headers, timeout=5)
                except Exception as e:
                    self.logger.error(f'Error sending command: {e}')
                    return False
                if r.status_code != 200:
                    body = ''
                    try:
                        body = r.text[:200]
                    except Exception:
                        pass
                    self.logger.error(f'Ecowitt command failed: {r.status_code}, body={body}')
                    return False
                sent = True
        else:
            payload = {"command": [{"cmd": "quick_stop", "id": did, "model": mid}]}
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=5)
            except Exception as e:
                self.logger.error(f'Error sending command: {e}')
                return False
            if r.status_code != 200:
                body = ''
                try:
                    body = r.text[:200]
                except Exception:
                    pass
                self.logger.error(f'Ecowitt command failed: {r.status_code}, body={body}')
                return False

        # Verify with limited retries (2s interval, up to ~6s total)
        desired = True if turn_on else False
        actual = None
        for _ in range(3):
            status = self._read_status()
            actual = self._status_to_bool(status)
            if actual is not None and actual == desired:
                break
            time.sleep(2)
        if actual is None:
            self.logger.warning('Unable to determine state after command')
            return False
        self.last_state = actual
        try:
            self.output_states[0] = 1.0 if actual else 0.0
        except Exception:
            pass
        return actual is True if turn_on else actual is False

    def _read_status(self):
        url = f'http://{self.ip}/parse_quick_cmd_iot'
        headers = {'Content-Type': 'application/json'}
        payload = {"command": [{"cmd": "read_device", "id": int(self.dev_id), "model": int(self.model)}]}
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=5)
            if r.status_code != 200:
                self._comm_ok = False
                return {}
            j = r.json()
            self._comm_ok = True
            return (j or {}).get('command', [{}])[0]
        except Exception as e:
            self.logger.error(f'Read status error: {e}')
            self._comm_ok = False
            return {}