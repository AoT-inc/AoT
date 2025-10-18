# coding=utf-8
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# 작성일: 2025-10-05
"""
AoT Input: ChirpStack v4 REST API + JMESPath

- Polls ChirpStack (v4) REST API for device events (e.g., kind='up').
- Evaluates user-provided JMESPath per channel against each event JSON.
- Writes measurements to InfluxDB using AoT's existing pipeline.

References
- ChirpStack v4 breaking changes: https://www.chirpstack.io/docs/v4-breaking-changes.html
- Python client (optional): https://github.com/chirpstack/chirpstack-rest-api
- JMESPath: https://jmespath.org/
"""

import datetime
import json
from typing import Any, Dict, List, Optional

import requests

from aot.config import AOT_DB_PATH
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Conversion, Input, InputChannel
from aot.databases.utils import session_scope
from aot.inputs.base_input import AbstractInput
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_measurement


# ----------------------------- AoT metadata -----------------------------

def constraints_pass_positive_value(mod_input, value):
    """Dummy constraint example kept for parity with other modules."""
    errors = []
    ok = True
    if value <= 0:
        ok = False
        errors.append("Must be a positive value")
    if value > 100:
        ok = False
        errors.append("Number of measurements cannot exceed 100")
    return ok, errors, mod_input


measurements_dict = {}
channels_dict = {0: {}}

INPUT_INFORMATION = {
    'input_name_unique': 'CHIRPSTACK_REST_JMESPATH',
    'input_manufacturer': 'ChirpStack',
    'input_name': 'ChirpStack: REST API (Payload JMESPath Expression)',
    'input_name_short': 'ChirpStack REST',
    'input_library': 'chirpstack-rest-api, requests, jmespath',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': (
        'ChirpStack v4 REST API를 주기적으로 호출하여 디바이스 이벤트를 가져오고, '
        '각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. '
        '예시(https://jmespath.org): object.battery_V, object.battery_pct, '
        'max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.'
    ),

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'options_enabled': [
        'measurements_select',
        'period',         # polling cycle (seconds)
        'start_offset',
        'pre_output'
    ],

    # Dependencies (install if missing). You asked to include the example with paho + jmespath.
    'dependencies_module': [
        ('pip-pypi', 'requests', 'requests==2.31.0'),
        ('pip-pypi', 'paho-mqtt', 'paho-mqtt==1.5.1'),  # not required by this module, included per request/example
        ('pip-pypi', 'jmespath', 'jmespath==0.10.0'),
    ],

    # Module options visible in the UI
    'custom_options': [
        {
            'id': 'api_base_url',
            'type': 'text',
            'default_value': 'http://localhost:8090',  # ChirpStack REST base
            'required': True,
            'name': 'API Base URL',
            'phrase': 'ChirpStack REST API의 기본 주소 (예: http://localhost:8080) (일반적으로 REST 프록시는 8090 포트)'
        },
        {
            'id': 'api_token',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'API Token',
            'phrase': 'ChirpStack REST API 접근을 위한 Bearer 토큰 (관리 콘솔에서 발급)'
        },
        {
            'id': 'tenant_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Tenant ID',
            'phrase': '선택 사항: 특정 테넌트에 속한 디바이스만 조회할 때 사용'
        },
        {
            'id': 'application_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Application ID',
            'phrase': '선택 사항: 특정 애플리케이션에 속한 디바이스만 조회할 때 사용'
        },
        {
            'id': 'device_euis',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'Device EUIs (comma-separated)',
            'phrase': '선택 사항: 조회할 디바이스 EUI를 콤마(,)로 구분해 입력. 비우면 애플리케이션의 모든 디바이스 대상'
        },
        {
            'id': 'page_limit',
            'type': 'text',
            'default_value': 50,
            'required': False,
            'name': 'Page size / limit',
            'phrase': '한 번의 REST API 호출에서 가져올 이벤트 개수(페이지 크기)'
        },
        {
            'id': 'event_kind',
            'type': 'text',
            'default_value': 'up',
            'required': False,
            'name': 'Event kind',
            'phrase': '가져올 이벤트의 종류 (예: up, join, status)'
        },
        {
            'id': 'fallback_raw_url_template',
            'type': 'text',
            'default_value': '/api/devices/{dev_eui}/events?limit={limit}&kind={kind}&after={after}',
            'required': False,
            'name': 'Fallback URL template',
            'phrase': '공식 파이썬 클라이언트를 사용할 수 없을 때 REST 요청에 사용할 URL 템플릿 (API Base URL 뒤에 연결됨). {dev_eui}, {limit}, {kind}, {after}가 자동 치환됨'
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
            'phrase': 'Evaluated against the full event JSON'
        }
    ]
}


# ----------------------------- Module class -----------------------------

class InputModule(AbstractInput):
    """Fetches ChirpStack events through REST and extracts values via JMESPath."""

    def _coerce_int(self, value, default: int) -> int:
        """Safely parse integers from AoT option values (which may arrive as str)."""
        try:
            if value is None:
                return default
            if isinstance(value, int):
                return value
            s = str(value).strip()
            if s == "":
                return default
            return int(float(s))  # accept "50", "50.0"
        except Exception:
            return default

    def __init__(self, input_dev, testing: bool = False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.log_level_debug = None
        self.jmespath = None

        # Options
        self.api_base_url: str = 'http://localhost:8080'
        self.api_token: str = ''
        self.tenant_id: str = ''
        self.application_id: str = ''
        self.device_euis: List[str] = []
        self.page_limit: int = 50
        self.event_kind: str = 'up'
        self.fallback_raw_url_template: str = '/api/devices/{dev_eui}/events?limit={limit}&kind={kind}&after={after}'

        # Runtime
        self.interface = None
        self.period = None
        self.latest_datetime: Optional[datetime.datetime] = None
        self.options_channels: Dict[str, Dict[int, Any]] = {}

        # Client (optional)
        self._cs_client = None
        self._cs_api = None  # lazily set when client exists

        # Incoming event timestamp format (RFC3339 with ns).
        self.timestamp_format = '%Y-%m-%dT%H:%M:%S.%f%z'

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    # --------------- Initialization helpers ---------------

    def initialize(self):
        import jmespath

        self.jmespath = jmespath

        self.log_level_debug = self.input_dev.log_level_debug
        self.interface = self.input_dev.interface
        self.period = self.input_dev.period
        self.latest_datetime = self.input_dev.datetime

        # Coerce option types that may come as strings from UI
        self.page_limit = self._coerce_int(getattr(self, 'page_limit', 50), 50)
        if not getattr(self, 'event_kind', None):
            self.event_kind = 'up'

        # Channels
        input_channels = db_retrieve_table_daemon(InputChannel).filter(
            InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        # Normalize device_euis option
        try:
            euis_raw = getattr(self, 'device_euis', '')
            self.device_euis = [x.strip() for x in euis_raw.split(',') if x.strip()]
        except Exception:
            self.device_euis = []

        # Try to initialize official REST client
        self._init_cs_client()

    def _init_cs_client(self):
        """
        Initialize chirpstack-rest-api client if available.
        """
        try:
            import chirpstack_rest_api as cs_api
            from chirpstack_rest_api import ApiClient, Configuration

            cfg = Configuration(host=self.api_base_url)
            cfg.access_token = self.api_token

            self._cs_client = ApiClient(cfg)

            # Client APIs vary by version; try a few known names.
            candidates = [
                ('EventsApi', 'list_device_events'),
                ('EventServiceApi', 'list_device_events'),
                ('DeviceApi', 'list_events'),
            ]
            for api_name, method_name in candidates:
                api_cls = getattr(cs_api, api_name, None)
                if api_cls is None:
                    continue
                api_instance = api_cls(self._cs_client)
                if hasattr(api_instance, method_name):
                    self._cs_api = (api_instance, method_name)
                    self.logger.info(f"Using ChirpStack REST client: {api_name}.{method_name}()")
                    return

            # No recognizable API/method; fall back to raw requests.
            self.logger.warning("ChirpStack REST client present but Events API not recognized; using requests fallback.")
            self._cs_client = None
            self._cs_api = None

        except Exception as e:
            self.logger.info(f"chirpstack-rest-api not available or failed to init ({e}); using requests fallback.")
            self._cs_client = None
            self._cs_api = None

    # --------------- REST helpers ---------------

    def _parse_cs_time(self, value: Optional[str]) -> Optional[datetime.datetime]:
        """Parse RFC3339 time string into naive UTC."""
        if not value:
            return None
        ts = value.replace('Z', '+00:00')
        # Trim fractional seconds to microseconds if longer
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
        try:
            dt = datetime.datetime.strptime(ts, self.timestamp_format)
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except Exception:
            return None

    def _iso_after(self) -> str:
        """Return ISO string for 'after' cursor based on latest_datetime."""
        if self.latest_datetime:
            return self.latest_datetime.replace(tzinfo=datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        # If first run and no stored timestamp, go back one period to avoid flooding
        dt = datetime.datetime.utcnow() - datetime.timedelta(seconds=int(self.period or 60))
        return dt.replace(tzinfo=datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def _list_devices(self) -> List[str]:
        """
        Return a list of device EUIs to poll.
        If device_euis is set, return as-is; otherwise try to list devices for the application.
        """
        if self.device_euis:
            return self.device_euis

        # Try listing devices via REST (requests path)
        if not self.application_id:
            return []

        try:
            # Common REST path in v4:
            #   GET /api/applications/{applicationId}/devices?limit=100
            url = f"{self.api_base_url}/api/applications/{self.application_id}/devices?limit=100"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = []
            if isinstance(data, dict):
                items = data.get('result') or data.get('devices') or data.get('items') or []
            elif isinstance(data, list):
                items = data
            euis = []
            for it in items:
                dev_eui = it.get('devEui') or it.get('dev_eui') or it.get('dev_eui_hex')
                if dev_eui:
                    euis.append(dev_eui)
            return euis
        except Exception as e:
            self.logger.warning(f"Could not list devices via REST: {e}")
            return []

    def _fetch_events_requests(self, dev_eui: str) -> List[Dict[str, Any]]:
        """Fallback raw-requests fetch for device events.
        Many v4 installs expose the REST proxy on :8090 and different paths.
        We try a few known templates and auto-switch 8080→8090 on 404.
        """
        after = self._iso_after()
        limit = self._coerce_int(self.page_limit, 50)

        # Candidate URL templates (format with dev_eui, limit, kind, after)
        candidates = []
        # 1) User-provided template first
        if self.fallback_raw_url_template:
            candidates.append(self.fallback_raw_url_template)
        # 2) Common v4 REST proxy routes
        candidates.extend([
            '/api/devices/{dev_eui}/events?limit={limit}&kind={kind}&after={after}',
            '/api/events?device_dev_eui={dev_eui}&limit={limit}&kind={kind}&after={after}',
            '/api/devices/{dev_eui}/events?limit={limit}&after={after}&kind={kind}',
        ])

        # Base URLs to try (original, then 8080→8090 fallback)
        base_urls = [self.api_base_url]
        if ':8080' in self.api_base_url:
            base_urls.append(self.api_base_url.replace(':8080', ':8090'))

        headers = self._headers()
        last_error = None

        for base in base_urls:
            for tmpl in candidates:
                try:
                    url = f"{base}{tmpl.format(dev_eui=dev_eui, limit=limit, kind=self.event_kind or 'up', after=after)}"
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code == 404:
                        # try next candidate
                        last_error = f"404 Not Found: {url}"
                        continue
                    r.raise_for_status()
                    data = r.json()
                    if isinstance(data, dict):
                        items = data.get('result') or data.get('events') or data.get('items') or []
                    else:
                        items = data
                    if not isinstance(items, list):
                        items = []
                    if items:
                        return items
                    # Even if empty list, accept as success and return
                    return items
                except Exception as e:
                    last_error = str(e)
                    continue

        self.logger.error(f"REST fetch (requests) failed for {dev_eui}: {last_error}")
        return []

    def _fetch_events_client(self, dev_eui: str) -> List[Dict[str, Any]]:
        """Use chirpstack-rest-api client if available."""
        if not self._cs_api:
            return []
        api, method_name = self._cs_api
        try:
            method = getattr(api, method_name)
        except Exception:
            return []

        after = self._iso_after()
        try:
            # Generic signature; may vary by client version.
            limit = self._coerce_int(self.page_limit, 50)
            resp = method(device_dev_eui=dev_eui, kind=self.event_kind or 'up', limit=limit, after=after)
            if hasattr(resp, 'to_dict'):
                resp = resp.to_dict()
            if isinstance(resp, dict):
                items = resp.get('result') or resp.get('events') or resp.get('items') or []
            else:
                items = resp
            if not isinstance(items, list):
                items = []
            return items
        except Exception as e:
            self.logger.warning(f"REST fetch (client) failed for {dev_eui}: {e}")
            return []

    # --------------- AoT entrypoints ---------------

    def get_new_data(self, _past_seconds: int):
        """
        Poll devices and process new events since the last timestamp.
        """
        try:
            import jmespath  # ensure available for channel eval
        except Exception as e:
            self.logger.error(f"jmespath not available: {e}")
            return

        devices = self._list_devices()
        if not devices:
            self.logger.info("No device EUIs to poll (set device_euis or application_id).")
            return

        all_events: List[Dict[str, Any]] = []
        for dev_eui in devices:
            items = self._fetch_events_client(dev_eui) if self._cs_api else self._fetch_events_requests(dev_eui)
            if not items:
                continue
            # Ensure chronological order (oldest first) by 'time'
            try:
                items.sort(key=lambda x: x.get('time', ''))
            except Exception:
                pass
            all_events.extend(items)

        for event in all_events:
            measurements = {}

            # Timestamp
            dt_utc = self._parse_cs_time(event.get('time')) or datetime.datetime.utcnow()
            if (not self.latest_datetime) or (self.latest_datetime < dt_utc):
                self.latest_datetime = dt_utc

            # Evaluate each channel
            for channel in self.channels_measurement:
                jexpr = self.options_channels['jmespath_expression'][channel]
                try:
                    compiled = self.jmespath.compile(jexpr)
                    value = compiled.search(event)
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
                self.logger.debug("No measurements extracted for this event.")

        # Persist latest timestamp for next poll
        if self.running and self.latest_datetime:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_input = new_session.query(Input).filter(Input.unique_id == self.unique_id).first()
                if not mod_input.datetime or mod_input.datetime < self.latest_datetime:
                    mod_input.datetime = self.latest_datetime
                    new_session.commit()

    def get_measurement(self):
        """Scheduler tick: poll the REST API."""
        # First run: if no stored timestamp, pull up to one `period` in the past.
        if self.input_dev and not self.input_dev.datetime and not self.latest_datetime:
            self.latest_datetime = datetime.datetime.utcnow() - datetime.timedelta(seconds=int(self.period or 60))

        try:
            self.get_new_data(self.period)
        except Exception:
            self.logger.exception("Polling ChirpStack REST API")
        return {}
