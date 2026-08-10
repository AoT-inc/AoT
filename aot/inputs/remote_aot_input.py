# coding=utf-8
"""원격 AoT 서버의 측정값을 수집하는 Input.

원격 AoT 를 "장치"로 다루는 두 방향 중 **수집** 쪽. 제어는 이미
`aot/outputs/remote_output_on_off.py`·`remote_output_pwm.py` 가 하고 있었지만,
반대 방향(다른 AoT 의 센서값을 이쪽으로 끌어오기)은 드라이버가 하나도 없었다.

**수집 경로 — `/data_batch` 우선, `/past` 폴백.**
채널마다 요청을 하나씩 보내면 원격 채널 20개짜리 연결이 주기마다 20 요청이 된다.
`POST /data_batch` 는 최대 300건을 한 번에 처리하므로 채널 수와 무관하게 1요청이다
(대시보드가 같은 이유로 쓰던 엔드포인트 — `routes_general.py` 의 주석 참조).
다만 이 엔드포인트는 `/api/` 밖의 내부 경로라 버전 계약이 없으므로, 없는
서버에서는 채널당 `GET /past/...` 로 자동 폴백한다.

**측정 식별은 `measurement_id` 로 한다 — unit/channel 이 아니라.**
`/api/measurements/past/<uuid>/<unit>/<channel>/…` 도 있지만 그 경로는 원시
unit·channel 을 받으므로, 원격 채널에 변환(Conversion)이 걸려 있으면 **변환 전
값**이 넘어온다. 반면 `/data_batch` 와 `/past` 는 둘 다 `async_data()` 를 타면서
원격이 변환을 적용한 뒤의 값을 준다. 단위 어휘를 로컬에서 다시 해석할 필요가
없어지는 것도 같은 이유다.

**디스커버리에서 `DeviceMeasurements.device_type` 을 믿지 않는다.** 컬럼은
있지만 코드베이스 어디에서도 값을 넣지 않아 항상 NULL 이다(로컬 라이브 DB 184행
전수 확인, 2026-08-10). 종류 판정은 `remote_aot_client.discover_measurements()` 가
device_id 를 실제 장치 목록에 대조해서 한다.

**보안**: API 키는 그 사용자의 전 권한을 그대로 넘긴다. 수집 전용 연결이라면
`view_settings` 만 가진 계정의 키를 쓸 것. TLS 검증 기본값은 켬이다. 자세한
배경은 `aot/utils/remote_aot_client.py` 헤더.

@phase active
@stability experimental
@dependency AbstractInput, RemoteAoTClient, requests
"""
import datetime

from flask_babel import lazy_gettext

from aot.config import AOT_DB_PATH
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Conversion
from aot.databases.models import Input
from aot.databases.models import InputChannel
from aot.databases.utils import session_scope
from aot.inputs.base_input import AbstractInput
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_measurement
from aot.utils.remote_aot_client import (
    RemoteAoTClient, RemoteAoTError, discover_measurements, parse_channel_value)

# Measurements
measurements_dict = {}

# Channels
channels_dict = {
    0: {}
}

INPUT_INFORMATION = {
    'input_name_unique': 'REMOTE_AOT',
    'input_manufacturer': 'AoT',
    'input_name': "{} AoT: {}".format(
        lazy_gettext('Remote'), lazy_gettext('Measurements')),
    'input_name_short': 'Remote AoT',
    'input_library': 'requests',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext(
        'Collect measurements from another AoT server over the network using its API. '
        'Enter the host and API key, set the number of measurements, and save — the '
        'Remote Measurement dropdown is then filled with the channels available on that '
        'server. Pick one per channel and set its Measurement Unit to match the unit '
        'shown in the dropdown. Values arrive with the remote timestamp, and any '
        'conversion configured on the remote channel is already applied.'),

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'options_enabled': [
        'measurements_select',
        'period',
        'start_offset',
        'pre_output'
    ],

    'dependencies_module': [
        ('pip-pypi', 'requests', 'requests==2.33.0'),
    ],

    'custom_options_message': lazy_gettext(
        'SECURITY: an AoT API key carries every permission of the user it belongs to. '
        'For a collect-only connection, create a user on the remote server whose role '
        'has only "View Settings" and use that user\'s key — a key from an admin account '
        'would also grant control of that server\'s devices. Keep TLS verification '
        'enabled unless you understand the risk.'),

    'custom_options': [
        {
            'id': 'host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Remote AoT Host'),
            'phrase': lazy_gettext('The host or IP address of the remote AoT (a port may be included, e.g. 192.168.0.9:8084)')
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Remote AoT API Key'),
            'phrase': lazy_gettext('The API key of the remote AoT, exactly as shown on that server')
        },
        {
            'id': 'scheme',
            'type': 'select',
            'default_value': 'https',
            'options_select': [
                ('https', 'HTTPS'),
                ('http', 'HTTP')
            ],
            'name': lazy_gettext('Protocol'),
            'phrase': lazy_gettext('Use HTTPS unless the remote AoT is only reachable over plain HTTP on a trusted network')
        },
        {
            'id': 'verify_tls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Verify TLS Certificate'),
            'phrase': lazy_gettext('Verify the remote server certificate. Turn this off only for a self-signed certificate on a trusted network — while off, the API key can be read by a man in the middle')
        },
        {
            'id': 'request_timeout',
            'type': 'integer',
            'default_value': 30,
            'name': lazy_gettext('Request Timeout (Seconds)'),
            'phrase': lazy_gettext('HTTP read timeout. Raise it if the remote server is slow to answer a large batch')
        },
        {
            'id': 'first_run_hours',
            'type': 'integer',
            'default_value': 24,
            'name': lazy_gettext('Initial Backfill (Hours)'),
            'phrase': lazy_gettext('How far back to collect on the first run. Later runs only fetch what has arrived since the last collection')
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
            'id': 'remote_measurement',
            'type': 'select_custom_choices',
            'default_value': '',
            'name': lazy_gettext('Remote Measurement'),
            'phrase': lazy_gettext('The measurement on the remote AoT to collect into this channel')
        }
    ]
}


# ──────────────────────────────────────────────────────────────────────────
# 저장 시 디스커버리
#
# 원격 채널 목록은 접속정보를 받기 전에는 알 수 없다. 그래서 저장 훅에서 원격을
# 조회해 각 채널의 `remote_measurement_choices` 를 채운다. 이 훅은 Flask 요청
# 컨텍스트에서 돌기 때문에(utils_input.py) 데몬 재시작 없이 반영되고,
# custom_options 가 바뀌면 utils_input 이 page_refresh 를 세우므로 사용자가
# 수동으로 새로고침할 필요도 없다 — 기존 remote_output 계열이 안내문에서
# "저장 후 페이지를 새로고침하라"고 요구하던 왕복을 여기서는 없앤다.
# ──────────────────────────────────────────────────────────────────────────
def execute_at_modification(
        messages,
        mod_input,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """Refresh the per-channel Remote Measurement dropdown from the remote host."""
    client = RemoteAoTClient.from_options(custom_options_dict_postsave)

    if not client.configured:
        messages["info"].append(
            "Remote AoT: enter the host and API key, then save again to list the "
            "measurements available on that server.")
        return (messages, mod_input,
                custom_options_dict_postsave, custom_options_channels_dict_postsave)

    try:
        choices = discover_measurements(client)
    except RemoteAoTError as err:
        # 실패해도 기존 선택지는 지우지 않는다 — 원격이 잠깐 죽었다고 이미 고른
        # 채널의 드롭다운이 빈 목록이 되면, 저장 한 번에 배선이 통째로 풀린다.
        messages["error"].append(
            "Remote AoT: could not read the measurement list from {host} ({err})".format(
                host=client.host, err=err))
        return (messages, mod_input,
                custom_options_dict_postsave, custom_options_channels_dict_postsave)

    for channel in custom_options_channels_dict_postsave:
        custom_options_channels_dict_postsave[channel]['remote_measurement_choices'] = choices

    if choices:
        messages["info"].append(
            "Remote AoT: {n} measurement(s) available on {host}.".format(
                n=len(choices), host=client.host))
    else:
        messages["warning"].append(
            "Remote AoT: connected to {host} but it reported no measurements. If that "
            "server does have Inputs, the API key's user may lack 'View Settings'.".format(
                host=client.host))

    return (messages, mod_input,
            custom_options_dict_postsave, custom_options_channels_dict_postsave)


INPUT_INFORMATION['execute_at_modification'] = execute_at_modification


class InputModule(AbstractInput):
    """Collect measurements from another AoT server via its REST API."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.host = None
        self.api_key = None
        self.scheme = 'https'
        self.verify_tls = True
        self.request_timeout = 30
        self.first_run_hours = 24

        self.client = None
        self.options_channels = {}
        self.latest_datetime = None
        # initialize() 에서도 채우지만 __init__ 에도 둔다 — initialize() 가
        # 접속정보 미설정으로 일찍 빠져나오는 경로가 있어서, 이 속성이 없으면
        # 뒤이은 코드가 AttributeError 로 죽는다.
        self.log_level_debug = False

        # 채널별 마지막 수집 시각(메모리). 재시작 직후에는 비어 있어 그 주기에는
        # 창 전체를 다시 쓴다 — InfluxDB 는 같은 타임스탬프를 덮어쓰므로
        # 중복 데이터가 생기지 않고, 대신 주기가 다른 채널(예: 10초짜리와 10분
        # 짜리가 한 연결에 섞인 경우)에서 느린 채널의 값이 빠지는 일이 없다.
        # 전역 watermark 하나로 걸러내면 정확히 그 값들이 사라진다.
        self._channel_watermark = {}

        self._warned_unit_mismatch = set()
        self._warned_no_channels = False
        self._batch_supported = True

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        self.log_level_debug = self.input_dev.log_level_debug
        self.period = self.input_dev.period
        self.latest_datetime = self.input_dev.datetime

        input_channels = db_retrieve_table_daemon(
            InputChannel).filter(
            InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        if not self.host or not self.api_key:
            self.logger.error(
                "Remote AoT host and API key must both be set before this Input "
                "can collect anything")
            return

        self.client = RemoteAoTClient(
            host=self.host,
            api_key=self.api_key,
            scheme=self.scheme,
            verify_tls=self.verify_tls,
            request_timeout=self.request_timeout,
            logger_=self.logger)

    # ── 채널 해석 ─────────────────────────────────────────────────────────
    def _selected_channels(self):
        """설정된 채널을 [(channel, device_id, measurement_id, measure_type)] 로."""
        selected = []
        for channel in self.channels_measurement:
            if not self.is_enabled(channel):
                continue
            raw = self.options_channels.get('remote_measurement', {}).get(channel)
            parsed = parse_channel_value(raw)
            if not parsed:
                continue
            device_id, measurement_id, measure_type = parsed
            selected.append((channel, device_id, measurement_id, measure_type))
        return selected

    def _window_seconds(self):
        """이번에 몇 초 전까지 거슬러 올라가 가져올지 결정한다."""
        first_run_seconds = max(1, int(self.first_run_hours or 24)) * 3600

        if not self.latest_datetime:
            return first_run_seconds

        elapsed = (datetime.datetime.utcnow() - self.latest_datetime).total_seconds()
        if elapsed <= 0:
            # 원격 시계가 앞서 있으면 elapsed 가 음수가 된다. 한 주기치만 본다.
            return max(1, int(self.period or 60))

        # 한 주기를 겹쳐서 가져온다. 경계에 딱 걸린 값이 양쪽 창에서 모두 빠지는
        # 것을 막기 위한 여유이고, 겹친 부분은 watermark 로 걸러진다.
        window = int(elapsed) + max(1, int(self.period or 60))
        return min(window, first_run_seconds)

    # ── 수집 ──────────────────────────────────────────────────────────────
    def _fetch(self, selected, past_seconds):
        """채널별 [[ts, value], ...] 리스트를 selected 와 같은 순서로 돌려준다."""
        if self._batch_supported:
            items = [{
                'kind': 'past',
                'unique_id': device_id,
                'measure_type': measure_type,
                'measurement_id': measurement_id,
                'period': str(past_seconds),
            } for _, device_id, measurement_id, measure_type in selected]
            try:
                return self.client.data_batch(items)
            except RemoteAoTError as err:
                # 배치가 없는(구버전) 원격일 수 있다. 한 번 실패하면 이후로는
                # 채널별 조회만 쓴다 — 주기마다 없는 엔드포인트를 두드리며
                # 실패 로그를 쌓지 않기 위해서다.
                self.logger.info(
                    "Remote AoT: /data_batch unavailable (%s); falling back to "
                    "per-channel requests", err)
                self._batch_supported = False

        results = []
        for _, device_id, measurement_id, measure_type in selected:
            try:
                results.append(self.client.past_data(
                    device_id, measure_type, measurement_id, past_seconds))
            except RemoteAoTError as err:
                self.logger.error(
                    "Remote AoT: failed to read %s (%s)", measurement_id, err)
                results.append(None)
        return results

    def _check_unit(self, channel, remote_choice_label):
        """로컬 채널의 단위가 원격과 다르면 한 번만 경고한다.

        값 자체는 그대로 저장한다 — 사용자가 일부러 다른 단위로 기록하려는
        경우까지 막을 근거는 없다. 다만 조용히 두면 °C 를 %로 저장해 놓고
        몇 주 뒤에 발견하게 된다.
        """
        if channel in self._warned_unit_mismatch or not remote_choice_label:
            return
        local_unit = self.channels_measurement[channel].unit
        if not local_unit or '({})'.format(local_unit) in remote_choice_label:
            return
        self._warned_unit_mismatch.add(channel)
        self.logger.warning(
            "Channel %s stores unit '%s' but the selected remote measurement is "
            "'%s'. Values are stored as-is — set the channel's Measurement Unit to "
            "match unless the difference is intentional.",
            channel, local_unit, remote_choice_label)

    def _label_for(self, channel):
        choices = self.options_channels.get(
            'remote_measurement_choices', {}).get(channel) or []
        selected = self.options_channels.get('remote_measurement', {}).get(channel)
        for entry in choices:
            try:
                if entry[0] == selected:
                    return entry[1]
            except (IndexError, TypeError):
                continue
        return ''

    def get_measurement(self):
        """Collect everything that has arrived on the remote since the last run."""
        if not self.client:
            return

        selected = self._selected_channels()
        if not selected:
            # 주기마다 조용히 아무것도 안 하는 상태가 되면 사용자는 "수집이 안
            # 된다"만 보고 이유를 못 찾는다. 다만 매 주기 찍으면 로그가 차므로
            # 한 번만 남긴다(설정이 채워지면 다시 켜진다).
            if not self._warned_no_channels:
                self._warned_no_channels = True
                self.logger.error(
                    "No Remote Measurement is selected on any channel, so nothing "
                    "will be collected. Open this Input's settings, save once to "
                    "populate the Remote Measurement dropdowns, then pick one per "
                    "channel.")
            return {}
        self._warned_no_channels = False

        past_seconds = self._window_seconds()
        self.logger.debug("Collecting the past %s seconds for %s channel(s)",
                          past_seconds, len(selected))

        results = self._fetch(selected, past_seconds)

        newest_overall = self.latest_datetime
        for index, (channel, _device_id, _measurement_id, _measure_type) in enumerate(selected):
            points = results[index] if index < len(results) else None
            if not points:
                continue

            self._check_unit(channel, self._label_for(channel))

            watermark = self._channel_watermark.get(channel)
            newest_for_channel = watermark

            for point in points:
                if not self.running:
                    break
                try:
                    timestamp, value = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    self.logger.debug("Discarding malformed point: %s", point)
                    continue

                # 이미 가져온 구간은 건너뛴다. 겹침은 창 계산에서 일부러 만든
                # 것이라 정상이며, 여기서 걸러야 같은 값으로 Input Action 이
                # 두 번 돌지 않는다.
                if watermark is not None and timestamp <= watermark:
                    continue

                datetime_utc = datetime.datetime.utcfromtimestamp(timestamp)
                self._store_point(channel, value, datetime_utc)

                if newest_for_channel is None or timestamp > newest_for_channel:
                    newest_for_channel = timestamp
                if newest_overall is None or datetime_utc > newest_overall:
                    newest_overall = datetime_utc

            if newest_for_channel is not None:
                self._channel_watermark[channel] = newest_for_channel

        self._save_latest_datetime(newest_overall)
        return {}

    def _store_point(self, channel, value, datetime_utc):
        """한 포인트를 변환·액션을 거쳐 InfluxDB 에 기록한다."""
        measurements = {channel: {
            'measurement': self.channels_measurement[channel].measurement,
            'unit': self.channels_measurement[channel].unit,
            'value': value,
            'timestamp_utc': datetime_utc,
        }}

        # 로컬 채널에도 변환이 걸려 있으면 적용한다. 원격의 변환은 이미 값에
        # 반영돼 있으므로, 여기 걸린 것은 그 위에 얹는 로컬 변환이다.
        if self.channels_conversion.get(channel):
            conversion = db_retrieve_table_daemon(
                Conversion,
                unique_id=self.channels_measurement[channel].conversion_id)
            if conversion:
                try:
                    converted = parse_measurement(
                        self.channels_conversion[channel],
                        self.channels_measurement[channel],
                        measurements,
                        channel,
                        measurements[channel],
                        timestamp=datetime_utc)
                    measurements[channel]['measurement'] = converted[channel]['measurement']
                    measurements[channel]['unit'] = converted[channel]['unit']
                    measurements[channel]['value'] = float(converted[channel]['value'])
                except Exception:
                    self.logger.exception(
                        "Conversion failed for channel %s; storing the raw value",
                        channel)

        try:
            _message, measurements = run_input_actions(
                self.unique_id, "", measurements, self.log_level_debug)
        except Exception:
            self.logger.exception("Input actions failed; storing the value anyway")

        add_measurements_influxdb(
            self.unique_id, measurements,
            use_same_timestamp=INPUT_INFORMATION['measurements_use_same_timestamp'])

    def _save_latest_datetime(self, newest):
        """다음 창 계산의 기준이 되도록 최신 수집 시각을 저장한다."""
        if not newest or not self.running:
            return
        if self.latest_datetime and newest <= self.latest_datetime:
            return
        self.latest_datetime = newest
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_input = new_session.query(Input).filter(
                    Input.unique_id == self.unique_id).first()
                if mod_input and (not mod_input.datetime or mod_input.datetime < newest):
                    mod_input.datetime = newest
                    new_session.commit()
        except Exception:
            self.logger.exception("Could not store the latest collection time")
