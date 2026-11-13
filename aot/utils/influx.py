# coding=utf-8
import contextlib
import contextvars
import datetime
import logging
import threading
import time

import requests
from influxdb_client import InfluxDBClient, Point

from aot.utils import influx_layers
from aot.config import INFLUXDB_PORT, resolve_measurement_db_host
from aot.databases.models import (Conversion, DeviceMeasurements, Misc,
                                     Output)
from aot.aot_client import DaemonControl
from aot.utils.database import (db_retrieve_table_daemon,
                                disabled_measurement_channels)
from aot.utils.system_pi import return_measurement_info

logger = logging.getLogger("aot.influx")

# Maximum lookback range when no time bounds are specified.
# Covers the full retention period without an unbounded scan.
INFLUX_FULL_HISTORY_RANGE = '-99999d'


# 도구 호출 하나 동안만 사는 설정 캐시(`influx_scope`). 프로세스 캐시가 아니다.
_SCOPE_MISC = contextvars.ContextVar('_influx_scope_misc', default=None)


@contextlib.contextmanager
def influx_scope():
    """이 블록 안의 측정 DB 설정(`Misc`) 읽기를 한 번만 한다 (읽기 전용 일괄 조회용).

    `read_influxdb_list` 한 번이 `Misc` 를 3번 읽는다(질의 만들기·`query_string`·결과 해석).
    구역 요약처럼 채널마다 수백 번 묻는 읽기 도구는 그만큼 SQLite 를 다시 읽는다
    (2026-11-07 실측: 204회 질의에서 읽기 약 600회). 블록이 끝나면 캐시도 사라지므로
    다른 호출·프로세스·데몬과 어긋나지 않는다. 블록 안에서 측정 DB 설정을 바꾸지 말 것.
    중첩하면 바깥 캐시를 그대로 쓴다. 다른 스레드는 이 캐시를 보지 못한다(읽기만 다시 한다).
    """
    if _SCOPE_MISC.get() is not None:
        yield
        return
    token = _SCOPE_MISC.set({})
    try:
        yield
    finally:
        _SCOPE_MISC.reset(token)


def _misc_settings():
    """측정 DB 설정 행. `influx_scope` 안이면 첫 읽기를 재사용한다(실패한 읽기는 담지 않는다)."""
    scoped = _SCOPE_MISC.get()
    if scoped is None:
        return db_retrieve_table_daemon(Misc, entry='first')
    if 'misc' not in scoped:
        row = db_retrieve_table_daemon(Misc, entry='first')
        if row is None:
            return row
        scoped['misc'] = row
    return scoped['misc']


def _flux_str(value):
    """Escape a string value for safe interpolation into a Flux filter expression."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def _as_influx_number(value):
    """정수로 들어온 측정값을 float 으로 맞춘다.

    **InfluxDB 의 필드 타입은 시리즈 단위로 한 번 정해지면 바뀌지 않는다.**
    influxdb-client 는 파이썬 타입을 그대로 라인 프로토콜에 싣기 때문에, 같은
    시리즈에 한 번이라도 `10`(int) 이 들어가면 `10i` 로 기록되고, 이미 float 로
    만들어진 시리즈라면 그 점은 422 로 거부된다 — 게다가 write_api 가 비동기
    배치라 호출자는 성공으로 알고 지나간다. 실측(2026-09-21):

        field type conflict: input field "value" on measurement "s"
        is type integer, already exists as type float dropped=1

    원인은 `base_output._record_on_duration` 이 `abs(output_last_duration) -
    remaining_time` 을 그대로 넘기는 것인데, `output_last_duration` 은 호출자가
    준 amount 이고 파이썬 출력의 `control.output_on(..., amount=10)` 처럼 정수
    리터럴이 흔하다. 그 결과 10분마다 한 점씩 개방 시간 기록이 조용히 사라져
    그래프에서는 "밸브가 열린 적 없는" 것으로 보였다.

    호출자마다 float() 를 흩뿌리는 대신 유일한 쓰기 길목인 여기서 맞춘다.
    bool 은 int 의 하위형이라 함께 걸리며, 문자열·None 은 손대지 않는다 —
    숫자가 아닌 필드를 숫자로 바꾸는 것은 이 함수의 일이 아니다.
    """
    if isinstance(value, bool) or isinstance(value, int):
        return float(value)
    return value


#
# Influxdb using Flux (influxdb versions 1.8+ and 2.x)
#

def write_influxdb_value(unique_id, unit, value, measure=None, channel=None, timestamp=None, extra_tags=None):
    """Write a value into an InfluxDB database using the flux client.

    @phase active
    @stability stable
    @dependency InfluxDBClient, Point, db_retrieve_table_daemon
    """
    settings = db_retrieve_table_daemon(Misc, entry='first')
    influx_host = resolve_measurement_db_host(settings.measurement_db_host)
    influx_port = INFLUXDB_PORT or settings.measurement_db_port

    influxdb_url = f'http://{influx_host}:{influx_port}'

    if settings.measurement_db_version == '1':
        client = InfluxDBClient(
            url=influxdb_url,
            token=f'{settings.measurement_db_user}:{settings.measurement_db_password}',
            org='aot',
            timeout=5000)
        bucket = f'{settings.measurement_db_dbname}/{settings.measurement_db_retention_policy}'
    elif settings.measurement_db_version == '2':
        client = InfluxDBClient(
            url=influxdb_url,
            token=settings.measurement_db_password,
            org='aot',
            timeout=5000)
        bucket = settings.measurement_db_dbname
    else:
        logger.error(f"Unknown Influxdb version: {settings.measurement_db_version}")
        return

    with client.write_api(success_callback=write_success, error_callback=write_fail) as write_api:
        point = Point(unit).tag("device_id", unique_id)

        if measure:
            point = point.tag("measure", measure)
        if channel is not None:
            point = point.tag("channel", channel)
        if extra_tags and isinstance(extra_tags, dict):
            for tag_key, tag_val in extra_tags.items():
                point = point.tag(tag_key, tag_val)
        if timestamp:
            point = point.time(timestamp)

        point = point.field("value", _as_influx_number(value))

        try:
            write_api.write(bucket=bucket, record=point)
            return 0
        except Exception as except_msg:
            logger.warning(f"InfluxDB write failed for {unique_id}, retrying in 5s: {except_msg}")
            time.sleep(5)
            try:
                write_api.write(bucket=bucket, record=point)
                return 0
            except Exception as retry_msg:
                logger.error(
                    f"InfluxDB write retry failed for {unique_id}: {retry_msg}")
                return 1


def add_measurements_influxdb_flux(unique_id, measurements, use_same_timestamp=True, block=False):
    """
    Parse measurement data into list to be input into influxdb (flux edition, using influxdb_client)
    :param unique_id: Unique ID of device
    :param measurements: dict of measurements
    :param use_same_timestamp: Allow influxdb to create the timestamp upon storage
    :return:
    """
    settings = db_retrieve_table_daemon(Misc, entry='first')
    influx_host = resolve_measurement_db_host(settings.measurement_db_host)
    influx_port = INFLUXDB_PORT or settings.measurement_db_port

    influxdb_url = f'http://{influx_host}:{influx_port}'

    if settings.measurement_db_version == '1':
        client = InfluxDBClient(
            url=influxdb_url,
            token=f'{settings.measurement_db_user}:{settings.measurement_db_password}',
            org='aot',
            timeout=5000)
        bucket = f'{settings.measurement_db_dbname}/{settings.measurement_db_retention_policy}'
    elif settings.measurement_db_version == '2':
        client = InfluxDBClient(
            url=influxdb_url,
            token=settings.measurement_db_password,
            org='aot',
            timeout=5000)
        bucket = settings.measurement_db_dbname
    else:
        logger.error(f"Unknown Influxdb version: {settings.measurement_db_version}")
        return

    # 마지막 관문: '활성화할 측정값 선택'에서 꺼 둔 채널은 저장하지 않는다.
    # 입력 모듈이 100종이 넘고 그중 푸시형(MQTT/HTTP)은 value_set() 을 거치지
    # 않고 이 함수로 바로 들어오므로, 모듈마다 검사를 심는 대신 저장 직전
    # 한 곳에서 막는다. 여기까지 오는 경로가 곧 저장되는 경로다.
    disabled_channels = disabled_measurement_channels(unique_id)

    with client.write_api(success_callback=write_success, error_callback=write_fail) as write_api:
        for each_channel, each_measurement in measurements.items():
            if each_channel in disabled_channels:
                continue  # measurement disabled by the user

            if 'value' not in each_measurement or each_measurement['value'] is None:
                continue  # skip to next measurement to add

            if use_same_timestamp:
                # influxdb will create the timestamp when the data is stored
                timestamp = None
            else:
                # Use timestamp stored with each measurement
                timestamp = each_measurement['timestamp_utc']

            point = Point(each_measurement['unit']).tag("device_id", unique_id)

            if each_measurement['measurement']:
                point = point.tag("measure", each_measurement['measurement'])
            if each_channel is not None:
                point = point.tag("channel", each_channel)
            if timestamp:
                point = point.time(timestamp)

            # 단건 경로와 같은 이유로 정수를 float 으로 맞춘다
            # (_as_influx_number 참조). 이쪽은 Input 일괄 기록 경로라, 정수만
            # 돌려주는 센서 하나가 시리즈 타입을 integer 로 굳혀 버리면 이후의
            # 실수 값이 전부 422 로 거부된다.
            point = point.field(
                "value", _as_influx_number(each_measurement['value']))
            write_api.write(bucket=bucket, record=point)


def write_influxdb_points(points, batch_size=2000, layer=None):
    """여러 점을 한 연결·동기 쓰기로 넣는다. 쓴 점 수를 돌려주고, 실패하면 예외를 올린다.

    `write_influxdb_value` 는 점마다 클라이언트를 새로 열고 비동기 배치라 실패를 삼킨다.
    트윈 발행(시설 한 건 약 4.7 천 점)은 그 경로로는 느리고, 트윈 서비스는 쓴 수를 정확히
    알아야 한다(내장 통로 `aot.twin.sources.embedded.EmbeddedSink`). 점은 `measurement`·`device_id`·
    `channel`·`timestamp`(epoch 초)·`value`·`tags` 속성을 가진 객체다(`aot.twin.types.Point`).

    `layer` 를 주면 측정 이름이 정하는 계층 대신 그 계층의 버킷에 쓴다(고정한 시나리오의 `aot_hist` 사본).
    """
    from influxdb_client.client.write_api import SYNCHRONOUS
    from influxdb_client.domain.write_precision import WritePrecision

    params = _influx_connection_params()
    if params is None:
        raise RuntimeError('measurement DB 설정을 읽지 못했다')
    url, token, bucket, _ver = params
    # 측정 이름으로 계층 버킷을 고른다(influx_layers). 한 버킷 모드면 전부 `bucket` 이다.
    by_bucket = {}
    for p in points:
        rec = Point(p.measurement).tag("device_id", p.device_id)
        if p.channel is not None:                # fc_* 는 channel 대신 var·lead 태그를 쓴다
            rec = rec.tag("channel", int(p.channel))
        for k, v in (p.tags or {}).items():
            rec = rec.tag(k, v)
        rec = rec.field("value", float(p.value)).time(int(round(float(p.timestamp) * 1000)),
                                                      WritePrecision.MS)
        by_bucket.setdefault(_layer_write_bucket(p.measurement, bucket, layer), []).append(rec)
    total = sum(len(v) for v in by_bucket.values())
    if not total:
        return 0
    with InfluxDBClient(url=url, token=token, org='aot', timeout=30000) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        for target, records in by_bucket.items():
            for i in range(0, len(records), batch_size):
                chunk = records[i:i + batch_size]
                try:
                    write_api.write(bucket=target, record=chunk, write_precision=WritePrecision.MS)
                except Exception:
                    if target == bucket:
                        raise
                    # 계층 버킷이 사라졌거나 쓸 수 없다 — 해석을 다시 하고 한 버킷으로 돌려 쓴다.
                    logger.warning("계층 버킷 %s 쓰기 실패 — %s 로 돌려 쓴다", target, bucket,
                                   exc_info=True)
                    influx_layers.invalidate()
                    write_api.write(bucket=bucket, record=chunk, write_precision=WritePrecision.MS)
    return total


def _layer_write_bucket(measurement, legacy_bucket, layer=None):
    """계층 해석이 실패해도 쓰기는 멈추지 않는다 — 한 버킷으로 돌아간다."""
    try:
        if layer is not None:
            return influx_layers.layout().buckets[layer]
        return influx_layers.write_bucket(measurement)
    except Exception:                                           # noqa: BLE001
        logger.debug("계층 버킷 해석 실패 — %s", legacy_bucket, exc_info=True)
        return legacy_bucket


def _layer_read_buckets(measurement, legacy_bucket):
    try:
        return influx_layers.read_buckets(measurement)
    except Exception:                                           # noqa: BLE001
        logger.debug("계층 버킷 해석 실패 — %s", legacy_bucket, exc_info=True)
        return [legacy_bucket]


def read_twin_series(device_id, measurement, channel, start_epoch, end_epoch, lead=None, tag_filters=None):
    """`env_twin*` 한 계열을 [start, end] 로 읽는다 → [(epoch 초, 값)] 시각순.

    `read_influxdb_list` 는 "지금부터 과거" 만 읽어 미래 시각인 예측 곡선이 빠지고, 측정 API 는
    단위표에 없는 `env_twin*` 를 422 로 막는다. 트윈 읽기 API(`/api/twin/series`) 가 쓴다.
    lead: `*_lead` 측정의 `lead_h`/`lead_d` 태그 값(그 선행 시간만).
    tag_filters: 그 밖의 태그 조건 — 시나리오 곡선(`env_twin_scn*`)의 `{'scenario': id}`.
    """
    params = _influx_connection_params()
    if params is None:
        return []
    url, token, bucket, _ver = params

    def iso(t):
        return datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%SZ')

    tail = (f' |> filter(fn: (r) => r["_measurement"] == "{_flux_str(measurement)}")'
            f' |> filter(fn: (r) => r["device_id"] == "{_flux_str(device_id)}")'
            f' |> filter(fn: (r) => r["channel"] == "{_flux_str(int(channel))}")'
            f' |> filter(fn: (r) => r["_field"] == "value")')
    if lead is not None:
        key = 'lead_h' if measurement == 'env_twin_lead' else 'lead_d'
        tail += f' |> filter(fn: (r) => r["{key}"] == "{_flux_str(lead)}")'
    for k, v in (tag_filters or {}).items():
        tail += f' |> filter(fn: (r) => r["{_flux_str(k)}"] == "{_flux_str(v)}")'
    merged = {}
    with InfluxDBClient(url=url, token=token, org='aot', timeout=30000) as client:
        # 우선순위 순: 같은 시각에 값이 두 버킷에 있으면 앞 버킷(새 계층)이 이긴다.
        for target in _layer_read_buckets(measurement, bucket):
            q = (f'from(bucket: "{_flux_str(target)}") |> range(start: {iso(start_epoch)}, '
                 f'stop: {iso(float(end_epoch) + 1)})' + tail)
            try:
                tables = client.query_api().query(q)
            except Exception:
                if target == bucket:
                    raise
                logger.warning("계층 버킷 %s 읽기 실패 — 건너뜀", target, exc_info=True)
                continue
            for t in tables:
                for r in t.records:
                    merged.setdefault(r.get_time().timestamp(), r.get_value())
    return sorted(merged.items())


def read_twin_many(measurement, device_ids, channels, start_epoch, end_epoch, tag_filters=None):
    """`env_twin*` 여러 대상·채널을 한 번에 읽는다 → {(device_id, channel): [(epoch 초, 값)]}.

    지도 예측 제공자(`/api/twin/plots`)가 구획마다 따로 왕복하지 않게 한다. `*_lead` 는 받지
    않는다(선행 태그를 섞으면 같은 시각에 값이 여럿이다).
    """
    if not device_ids or not channels:
        return {}
    params = _influx_connection_params()
    if params is None:
        return {}
    url, token, bucket, _ver = params

    def iso(t):
        return datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%SZ')

    ids = ', '.join('"%s"' % _flux_str(d) for d in device_ids)
    chs = ', '.join('"%s"' % _flux_str(int(c)) for c in channels)
    tail = (f' |> filter(fn: (r) => r["_measurement"] == "{_flux_str(measurement)}")'
            f' |> filter(fn: (r) => contains(value: r["device_id"], set: [{ids}]))'
            f' |> filter(fn: (r) => contains(value: r["channel"], set: [{chs}]))'
            f' |> filter(fn: (r) => r["_field"] == "value")')
    for k, v in (tag_filters or {}).items():
        tail += f' |> filter(fn: (r) => r["{_flux_str(k)}"] == "{_flux_str(v)}")'
    out = {}
    with InfluxDBClient(url=url, token=token, org='aot', timeout=30000) as client:
        for target in _layer_read_buckets(measurement, bucket):
            q = (f'from(bucket: "{_flux_str(target)}") |> range(start: {iso(start_epoch)}, '
                 f'stop: {iso(float(end_epoch) + 1)})' + tail)
            try:
                tables = client.query_api().query(q)
            except Exception:
                if target == bucket:
                    raise
                logger.warning("계층 버킷 %s 읽기 실패 — 건너뜀", target, exc_info=True)
                continue
            for t in tables:
                for r in t.records:
                    key = (r.values.get('device_id'), int(r.values.get('channel')))
                    out.setdefault(key, {}).setdefault(r.get_time().timestamp(), r.get_value())
    return {k: sorted(v.items()) for k, v in out.items()}


_FLUX_INTERNAL_KEYS = frozenset(('result', 'table', '_start', '_stop', '_time', '_value', '_field',
                                 '_measurement', 'device_id'))


def read_layer_points(measurement, device_id, tag_filters, start_epoch, end_epoch):
    """태그로 고른 한 대상의 점을 [start, end] 로 읽는다 → [(epoch 초, 값, {태그})] 시각순.

    `fc_*` 처럼 `channel` 대신 `var`·`lead_*` 태그를 쓰는 계층 측정용이다. `device_id=None` 이면 대상을 가리지 않고 결과 태그에 `device_id` 를 싣는다. 계층 버킷과 `aot_db` 를
    우선순위 순으로 읽어 병합한다(같은 시각·같은 태그면 앞 버킷이 이긴다). 태그 값은 문자열이다.
    """
    params = _influx_connection_params()
    if params is None:
        return []
    url, token, bucket, _ver = params

    def iso(t):
        return datetime.datetime.fromtimestamp(float(t), datetime.timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%SZ')

    tail = f' |> filter(fn: (r) => r["_measurement"] == "{_flux_str(measurement)}")'
    if device_id is not None:         # None 이면 모든 대상 — 결과 태그의 `device_id` 로 가른다(물 결과 컨텍스트)
        tail += f' |> filter(fn: (r) => r["device_id"] == "{_flux_str(device_id)}")'
    tail += ' |> filter(fn: (r) => r["_field"] == "value")'
    for k, v in (tag_filters or {}).items():
        tail += f' |> filter(fn: (r) => r["{_flux_str(k)}"] == "{_flux_str(v)}")'
    merged = {}
    with InfluxDBClient(url=url, token=token, org='aot', timeout=30000) as client:
        for target in _layer_read_buckets(measurement, bucket):
            q = (f'from(bucket: "{_flux_str(target)}") |> range(start: {iso(start_epoch)}, '
                 f'stop: {iso(float(end_epoch) + 1)})' + tail)
            try:
                tables = client.query_api().query(q)
            except Exception:
                if target == bucket:
                    raise
                logger.warning("계층 버킷 %s 읽기 실패 — 건너뜀", target, exc_info=True)
                continue
            for tb in tables:
                for r in tb.records:
                    tags = {k: v for k, v in r.values.items() if k not in _FLUX_INTERNAL_KEYS}
                    if device_id is None:                # 모든 대상을 읽을 때만 대상을 태그로 돌려준다
                        tags['device_id'] = r.values.get('device_id')
                    ts = r.get_time().timestamp()
                    merged.setdefault((ts, tuple(sorted(tags.items()))), (r.get_value(), tags))
    return sorted(((ts, v, tags) for (ts, _k), (v, tags) in merged.items()), key=lambda x: x[0])


def write_fail(point_data, written_data, err):
    # WARNING 승격: InfluxDB 기록 실패는 측정값 유실이므로 INFO 이상에서도 확인 가능해야 함.
    logger.warning(f"InfluxDB write failed: {err}")


def write_success(point_data, written_data):
    # 성공 콜백: 정상 상태이므로 로그 없음.
    # 매 write_api 호출마다 발동 → DEBUG 로도 기록하지 않아야 로그 폭증이 없다.
    pass


def add_measurements_influxdb(unique_id, measurements, use_same_timestamp=True, block=False):
    """Parse measurement data and write to InfluxDB (threaded for non-blocking operation).

    @phase active
    @stability stable
    @dependency add_measurements_influxdb_flux
    """
    if block:
        add_measurements_influxdb_flux(unique_id, measurements, use_same_timestamp)
    else:
        write_db = threading.Thread(
            target=add_measurements_influxdb_flux,
            args=(unique_id, measurements, use_same_timestamp,))
        write_db.start()


def _flux_query_and_conn(settings, unit, unique_id,
                         value=None, measure=None, channel=None, ts_str=None,
                         start_str=None, end_str=None, min_value=None, max_value=None,
                         past_sec=None, group_sec=None, limit=None, group_fn=None,
                         group_fns=None):
    """(url, token, flux 질의문). 측정 DB 버전을 모르면 None. `query_flux` 와 읽기 전용 경로가 공유한다."""
    influx_host = resolve_measurement_db_host(settings.measurement_db_host)
    influx_port = INFLUXDB_PORT or settings.measurement_db_port

    influxdb_url = f'http://{influx_host}:{influx_port}'

    if settings.measurement_db_version == '1':
        token = f'{settings.measurement_db_user}:{settings.measurement_db_password}'
        bucket = f'{settings.measurement_db_dbname}/{settings.measurement_db_retention_policy}'
    elif settings.measurement_db_version == '2':
        token = settings.measurement_db_password
        bucket = settings.measurement_db_dbname
    else:
        logger.error(f"Unknown Influxdb version: {settings.measurement_db_version}")
        return None

    query = f'from(bucket: "{bucket}")'

    if past_sec:
        query += f' |> range(start: -{int(past_sec)}s)'
    elif start_str and end_str:
        query += f' |> range(start: {start_str}, stop: {end_str})'
    elif start_str:
        query += f' |> range(start: {start_str})'
    elif end_str:
        query += f' |> range(stop: {end_str})'
    else:
        query += f' |> range(start: {INFLUX_FULL_HISTORY_RANGE})'

    if min_value:
        query += f' |> filter(fn: (r) => r._value > {min_value})'
    if max_value:
        query += f' |> filter(fn: (r) => r._value < {max_value})'

    query += f' |> filter(fn: (r) => r["_measurement"] == "{_flux_str(unit)}")'
    query += f' |> filter(fn: (r) => r["device_id"] == "{_flux_str(unique_id)}")'

    if channel is not None:
        query += f' |> filter(fn: (r) => r["channel"] == "{_flux_str(channel)}")'
    if measure:
        query += f' |> filter(fn: (r) => r["measure"] == "{_flux_str(measure)}")'
    if ts_str:
        query += f' |> filter(fn: (r) => r._time == {ts_str})'

    # group_fns: 같은 필터·같은 창으로 **여러 통계를 한 번에**(왕복 1회). 통계마다
    # 질의를 따로 보내던 자리(일지 min/max/mean, GDD max/min)가 채널 수 × 통계
    # 수만큼 왕복했다. 각 레코드에 `_stat` 열(통계 이름)을 달아 합쳐 돌려준다.
    # 기본(None)은 기존 동작 그대로이며, 둘 이상일 때만 이 경로를 탄다.
    # 이 경로는 `limit`·`value`(LAST 등)를 쓰지 않는다 — 넘겨도 무시된다.
    # 긴 기간(작기 전체 GDD)에는 쓰지 말 것: 맥미니 실측(26-11-10)에서 union 으로
    # 묶은 질의가 저장소 쪽 집계 최적화를 잃어 0.8→3.8초로 느려졌다(7일 창은 이득).
    _multi = [f for f in (group_fns or ())
              if f in ('max', 'min', 'mean', 'median', 'sum')]
    if group_sec and len(_multi) >= 2:
        _multi = list(dict.fromkeys(_multi))
        stmts = [f'data = {query}']
        for f in _multi:
            stmts.append(
                f'{f}_s = data |> aggregateWindow(every: {group_sec}s, fn: {f})'
                f' |> filter(fn: (r) => exists r._value)'
                f' |> set(key: "_stat", value: "{f}")')
        stmts.append('union(tables: [' + ', '.join(f'{f}_s' for f in _multi) + '])')
        return influxdb_url, token, '\n'.join(stmts)

    if group_sec:
        # group_fn: 창마다 어떤 통계를 낼지. 기본(None)은 기존 동작 그대로 —
        # 그래프가 쓰는 평균이다. 'max'/'min' 은 일별 최고·최저가 필요한 자리
        # (GDD = (Tmax+Tmin)/2)에서 쓴다. 여기서 만들지 않으면 그 자리가 Flux
        # 쿼리를 한 벌 더 짜게 되고, 버킷·필터 규약이 두 곳으로 갈린다.
        # 'sum' 은 **길이의 합**이 필요한 자리다(장치가 하루에 몇 초 돌았나 —
        # `runtime.get_daily_operational_seconds`). 평균으로 내면 "한 번 켤 때
        # 평균 몇 초" 가 되어 전혀 다른 값이다.
        _fn = group_fn if group_fn in ('max', 'min', 'mean', 'median',
                                       'sum') else None
        if _fn:
            query += f' |> aggregateWindow(every: {group_sec}s, fn: {_fn})'
        elif settings.measurement_db_version == '1':
            # TODO: Change median to mean when issue is fixed
            # Bug in influxdb/Flux v1.8.10 due to mean
            # Error: panic: runtime error: invalid memory address or nil pointer dereference
            # https://github.com/influxdata/influxdb/issues/21649
            # https://github.com/influxdata/influxdb/pull/23520
            query += f' |> aggregateWindow(every: {group_sec}s, fn: median)'
        elif settings.measurement_db_version == '2':
            query += f' |> aggregateWindow(every: {group_sec}s, fn: mean)'
        # aggregateWindow fills empty buckets with null; remove them before returning
        # so callers never receive null values that JS would convert to 0 (false spikes).
        query += ' |> filter(fn: (r) => exists r._value)'

    if limit:
        query += f' |> limit(n:{limit})'

    if value:
        if value == "LAST":
            query += ' |> last()'
        elif value == "FIRST":
            query += ' |> first()'
        elif value == "MAX":
            query += ' |> max()'
        elif value == "MIN":
            query += ' |> min()'
        elif value == "COUNT":
            query += ' |> count()'
        elif value == "SUM":
            if settings.measurement_db_version == '1':
                # TODO: Change when issue is fixed
                # Bug in influxdb/Flux v1.8.10 due to mean
                # Error: panic: runtime error: invalid memory address or nil pointer dereference
                # https://github.com/influxdata/influxdb/issues/21649
                # https://github.com/influxdata/influxdb/pull/23520
                logger.error("SUM cannot be used with influxdb 1.8.10 without causing an error. "
                             "Returning all measurements for period to manually sum.")
            elif settings.measurement_db_version == '2':
                query += ' |> sum(column: "_value")'
        elif value == "MEAN":
            if settings.measurement_db_version == '1':
                # TODO: Change median to mean when issue is fixed
                # Bug in influxdb/Flux v1.8.10 due to mean
                # Error: panic: runtime error: invalid memory address or nil pointer dereference
                # https://github.com/influxdata/influxdb/issues/21649
                # https://github.com/influxdata/influxdb/pull/23520
                query += ' |> median()'
            elif settings.measurement_db_version == '2':
                query += ' |> mean()'

    return influxdb_url, token, query


def query_flux(unit, unique_id,
               value=None, measure=None, channel=None, ts_str=None,
               start_str=None, end_str=None, min_value=None, max_value=None, past_sec=None, group_sec=None,
               limit=None, group_fn=None, group_fns=None):
    """Generate influxdb query string (flux edition, using influxdb_client)."""
    settings = _misc_settings()
    built = _flux_query_and_conn(
        settings, unit, unique_id,
        value=value, measure=measure, channel=channel, ts_str=ts_str,
        start_str=start_str, end_str=end_str, min_value=min_value, max_value=max_value,
        past_sec=past_sec, group_sec=group_sec, limit=limit, group_fn=group_fn,
        group_fns=group_fns)
    if built is None:
        return None
    influxdb_url, token, query = built

    logger.debug(f"query_flux() query: '{query}'")

    try:
        with InfluxDBClient(url=influxdb_url, token=token, org='aot', timeout=60000) as client:
            tables = client.query_api().query(query)
        return tables
    except Exception as err:
        logger.error(f"query_flux() InfluxDB query failed: {err}")
        return None


def _csv_converter(data_type, default):
    """`FluxCsvParser._to_value` 와 같은 변환 — 칸 하나용 함수. 빈 칸은 `#default` 를 따른다."""
    from influxdb_client.client.util.date_utils import get_date_helper
    if data_type in ('dateTime:RFC3339', 'dateTime:RFC3339Nano'):
        conv = get_date_helper().parse_date
    elif data_type == 'double':
        conv = float
    elif data_type in ('long', 'unsignedLong', 'duration'):
        conv = int
    elif data_type == 'boolean':
        conv = lambda v: v == 'true'                       # noqa: E731
    elif data_type == 'string':
        conv = lambda v: v                                 # noqa: E731
    else:
        # base64Binary 등 이 경로가 받을 일 없는 형: 기존 파서에 맡기도록 알린다.
        raise ValueError(f'unsupported flux datatype {data_type!r}')
    if default not in ('', None):
        _fallback = conv(default)
    else:
        _fallback = None

    def convert(v):
        return conv(v) if v != '' else _fallback
    return convert


def _time_value_rows(csv_rows):
    """주석 달린 Flux CSV → [(`_time`, `_value`), ...]. 표 순서·행 순서 그대로.

    `influxdb_client` 의 `query()` 는 행마다 열 전부(_start·_stop·태그 포함, 시각 3개)를
    변환해 객체를 만든다 — 구역 요약 한 번에 32만 행, 파이썬 쪽 변환이 호출 시간의 약 40%
    였다(2026-11-07 실측). 이 읽기는 두 칸만 쓰므로 그 두 칸만 같은 규칙으로 변환한다.
    오류 응답(`error,reference`)·열 누락은 예외 → 호출부가 기존처럼 None 으로 접는다.
    """
    out = []
    types = defaults = None
    conv_t = conv_v = None
    ti = vi = -1
    header_next = False
    for csv in csv_rows:
        if not csv:
            continue
        if len(csv) > 2 and csv[1] == 'error' and csv[2] == 'reference':
            raise ValueError('flux error response')
        tok = csv[0]
        if tok == '#datatype':
            types, defaults, header_next = csv, None, True
        elif tok == '#group':
            continue
        elif tok == '#default':
            defaults = csv
        elif header_next:
            # 열 이름 행. 열 번호는 csv 배열 그대로(0번 칸은 주석 표지).
            header_next = False
            ti = csv.index('_time')
            vi = csv.index('_value')
            d = defaults or []
            conv_t = _csv_converter(types[ti], d[ti] if ti < len(d) else '')
            conv_v = _csv_converter(types[vi], d[vi] if vi < len(d) else '')
        else:
            out.append((conv_t(csv[ti]), conv_v(csv[vi])))
    return out


def query_time_values(unit, unique_id, measure=None, channel=None,
                      start_str=None, end_str=None, past_sec=None):
    """`query_string(...)` 결과에서 (`_time`, `_value`) 만 뽑은 목록. 실패면 None.

    질의문은 `query_flux` 와 같다(같은 함수가 만든다) — 서버가 하는 일도, 값도 같고
    파이썬 쪽 변환 범위만 두 칸으로 줄었다. 측정 DB 가 influxdb 가 아니면 None.
    """
    settings = _misc_settings()
    if settings.measurement_db_name != "influxdb":
        return None
    built = _flux_query_and_conn(
        settings, unit, unique_id, measure=measure, channel=channel,
        start_str=start_str, end_str=end_str, past_sec=past_sec)
    if built is None:
        return None
    url, token, query = built
    try:
        with InfluxDBClient(url=url, token=token, org='aot', timeout=60000) as client:
            return _time_value_rows(client.query_api().query_csv(query))
    except Exception as err:
        logger.error(f"query_time_values() InfluxDB query failed: {err}")
        return None


def _influx_connection_params():
    """(url, token, bucket, version) for the configured measurement DB.

    query_flux() builds these inline; the bulk helper below needs the same
    values, so the resolution lives here rather than being copied a third time.
    Returns None when the version is unknown (same failure mode as query_flux).
    """
    settings = _misc_settings()
    host = resolve_measurement_db_host(settings.measurement_db_host)
    port = INFLUXDB_PORT or settings.measurement_db_port
    url = f'http://{host}:{port}'

    if settings.measurement_db_version == '1':
        token = f'{settings.measurement_db_user}:{settings.measurement_db_password}'
        bucket = f'{settings.measurement_db_dbname}/{settings.measurement_db_retention_policy}'
    elif settings.measurement_db_version == '2':
        token = settings.measurement_db_password
        bucket = settings.measurement_db_dbname
    else:
        logger.error(f"Unknown Influxdb version: {settings.measurement_db_version}")
        return None
    return url, token, bucket, settings.measurement_db_version


def query_last_values_bulk(specs, past_sec=600):
    """Last value for MANY series in a single Flux query.

    query_flux(value='LAST') issues one HTTP query per measurement. A map widget
    with 15 inputs asked for 107 of them per refresh — measured at ~840-970ms
    even with an 8-thread pool, and the cost scaled linearly with the item count
    (each query ~60-70ms of round trip). One query filtered by the union of
    device_ids collapses that into a single round trip.

    Args
    ----
    specs : iterable of (unit, device_id, channel, measure)
        `unit` is the Influx `_measurement`; `channel`/`measure` are tags and may
        be None (they are optional at write time — see write_influxdb_value).
    past_sec : lookback window, matching the per-item `period` of /last.

    Returns
    -------
    dict keyed by (unit, device_id, channel_str, measure) → [epoch_seconds, value].
    `channel_str` is str(channel) or '' — Influx tags are strings, so callers
    must look up with the same normalisation (see _bulk_key).
    Returns {} on any failure so callers can fall back to the per-item path.

    A caller that must tell "the query failed" from "the query ran and that
    series simply has no point in the window" cannot do it here — both are {}.
    Use query_last_values_bulk_status() for that.
    """
    values, _ok = query_last_values_bulk_status(specs, past_sec=past_sec)
    return values


def query_last_values_bulk_status(specs, past_sec=600):
    """query_last_values_bulk + whether the query actually ran → (values, ok).

    An empty result is ambiguous: the query may have failed, or it may have run
    and found nothing (a fresh install with no measurements yet — every series
    misses). A caller that falls back to the per-item path on a miss needs the
    difference. Treating "ran, found nothing" as a miss puts it right back on
    the N-queries path it was trying to leave, and that is the exact case where
    N is largest, so the fallback is at its most expensive when it buys nothing.

    `ok` is True when the Flux query returned and parsed. With ok=True the
    absence of a key means that series has no point inside `past_sec` — an
    answer, not a failure.
    """
    specs = [s for s in specs if s and s[0] and s[1]]
    if not specs:
        return {}, True

    conn = _influx_connection_params()
    if not conn:
        return {}, False
    url, token, bucket, _version = conn

    units = sorted({str(s[0]) for s in specs})
    devices = sorted({str(s[1]) for s in specs})
    _set = lambda vals: '[' + ', '.join(f'"{_flux_str(v)}"' for v in vals) + ']'

    query = (
        f'from(bucket: "{bucket}")'
        f' |> range(start: -{int(past_sec)}s)'
        f' |> filter(fn: (r) => contains(value: r["_measurement"], set: {_set(units)}))'
        f' |> filter(fn: (r) => contains(value: r["device_id"], set: {_set(devices)}))'
        ' |> last()'
    )
    logger.debug(f"query_last_values_bulk() {len(specs)} specs, query: '{query}'")

    try:
        with InfluxDBClient(url=url, token=token, org='aot', timeout=60000) as client:
            tables = client.query_api().query(query)
    except Exception as err:
        logger.error(f"query_last_values_bulk() InfluxDB query failed: {err}")
        return {}, False

    out = {}
    try:
        for table in tables:
            for row in table.records:
                v = row.values
                if '_value' not in v or '_time' not in v:
                    continue
                key = (v.get('_measurement'), v.get('device_id'),
                       '' if v.get('channel') is None else str(v.get('channel')),
                       v.get('measure'))
                out[key] = [v['_time'].timestamp(), v['_value']]
    except Exception as err:
        logger.error(f"query_last_values_bulk() result parse failed: {err}")
        return {}, False
    return out, True


def bulk_key(unit, device_id, channel, measure):
    """Key normalisation shared by producer and consumer of query_last_values_bulk."""
    return (str(unit) if unit is not None else None,
            str(device_id) if device_id is not None else None,
            '' if channel is None else str(channel),
            measure if measure else None)


def query_string(unit, unique_id,
                 value=None, measure=None, channel=None, ts_str=None,
                 start_str=None, end_str=None, min_value=None, max_value=None,
                 past_sec=None, group_sec=None, limit=None, group_fn=None,
                 group_fns=None):
    """Generate influxdb query string."""
    ret_value = None
    settings = _misc_settings()

    if settings.measurement_db_name == "influxdb":
        ret_value = query_flux(
            unit, unique_id,
            value=value, measure=measure, channel=channel, ts_str=ts_str,
            start_str=start_str, end_str=end_str, min_value=min_value, max_value=max_value,
            past_sec=past_sec, group_sec=group_sec, limit=limit,
            group_fn=group_fn, group_fns=group_fns)

    return ret_value


def get_last_measurement(device_id, measurement_id, max_age=None):
    """Query the most recent measurement for a device and measurement ID.

    @phase active
    @stability stable
    @dependency DeviceMeasurements, Conversion, read_influxdb_single
    """
    device_measurement = db_retrieve_table_daemon(
        DeviceMeasurements).filter(
        DeviceMeasurements.unique_id == measurement_id).first()
    if device_measurement:
        conversion = db_retrieve_table_daemon(
            Conversion, unique_id=device_measurement.conversion_id)
    else:
        conversion = None
    channel, unit, measurement = return_measurement_info(
        device_measurement, conversion)

    last_measurement = read_influxdb_single(
        device_id,
        unit,
        channel,
        measure=measurement,
        duration_sec=max_age,
        value='LAST')

    return last_measurement


def read_influxdb_single(unique_id, unit, channel,
                         measure=None,
                         duration_sec=None,
                         start_str=None,
                         end_str=None,
                         value='LAST',
                         datetime_obj=False):
    """Query InfluxDB for a single entry/value.

    @phase active
    @stability stable
    @dependency query_string, db_retrieve_table_daemon
    """
    try:
        data = query_string(
            unit,
            unique_id,
            measure=measure,
            channel=channel,
            value=value,
            start_str=start_str,
            end_str=end_str,
            past_sec=duration_sec)

        if data:
            try:
                settings = _misc_settings()
                if settings.measurement_db_name == 'influxdb':
                    for table in data:
                        for row in table.records:
                            if datetime_obj:
                                last_time = row.values['_time']
                            else:
                                last_time = row.values['_time'].timestamp()
                            return [last_time, row.values['_value']]
            except Exception:
                logger.exception("Error parsing the last influx measurement")
    except requests.exceptions.ConnectionError:
        logger.debug("Failed to establish a new influxdb connection. Ensure influxdb is running.")

    return [None, None]


def get_past_measurements(device_id, measurement_id, max_age=None):
    device_measurement = db_retrieve_table_daemon(
        DeviceMeasurements).filter(
        DeviceMeasurements.unique_id == measurement_id).first()
    if device_measurement:
        conversion = db_retrieve_table_daemon(
            Conversion, unique_id=device_measurement.conversion_id)
    else:
        conversion = None
    channel, unit, measurement = return_measurement_info(
        device_measurement, conversion)

    past_measurements = read_influxdb_list(
        device_id,
        unit,
        channel,
        measure=measurement,
        duration_sec=max_age)

    return past_measurements


def read_influxdb_list(unique_id, unit, channel,
                       measure=None,
                       duration_sec=None,
                       start_str=None,
                       end_str=None,
                       datetime_obj=False):
    """
    Query Influxdb for a list of entries

    example:
        read_influxdb_list('00000001', 'C', duration_sec=0)

    :return: list of time and value
    :rtype: list

    :param unique_id: What unique_id tag to query in the Influxdb
        database (eg. '00000001')
    :type unique_id: str
    :param unit: What unit to query in the Influxdb
        database (eg. 'C', 's')
    :type unit: str
    :param measure: What measurement to query in the Influxdb
        database (eg. 'temperature', 'duration_time')
    :type measure: str or None
    :param channel: Channel
    :type channel: int or None
    :param duration_sec: How many seconds to look for a past measurement
    :type duration_sec: int or None
    :param start_str: Start time, in influxdb format
    :type start_str: str
    :param end_str: End time, in influxdb format
    :type end_str: str
    :param datetime_obj: return a datetime object as a time
    :type datetime_obj: bool
    """
    try:
        # 두 칸만 변환하는 읽기(`query_time_values`) — 결과 값은 `query_string` 경로와 같다.
        data = query_time_values(
            unit, unique_id,
            measure=measure,
            channel=channel,
            start_str=start_str,
            end_str=end_str,
            past_sec=duration_sec)

        if data is not None:
            if datetime_obj:
                return data
            return [(t.timestamp(), v) for t, v in data]
    except:
        logger.debug("Could not read form influxdb.")


def output_sec_on(output_id, past_seconds, output_channel=0):
    """Return the number of seconds a output has been ON in the past number of seconds."""
    # Get the number of seconds ON stored in the database
    if not output_id:
        return None

    output = db_retrieve_table_daemon(Output, unique_id=output_id)
    if output is None:
        logger.error("output_sec_on: 출력 %s 조회 실패", output_id)
        return None

    # Get the number of seconds not stored in the database (if currently on)
    output_time_on = 0
    try:
        control = DaemonControl()
        if control.output_state(output_id, output_channel=output_channel) == 'on':
            output_time_on = control.output_sec_currently_on(
                output_id, output_channel=output_channel)
    except Exception:
        logger.exception("output_sec_on()")

    data = query_string(
        's', output.unique_id,
        measure='duration_time',
        channel=output_channel,
        value='SUM',
        past_sec=past_seconds)

    sec_recorded_on = 0
    if data:
        settings = db_retrieve_table_daemon(Misc, entry='first')
        if settings.measurement_db_name == 'influxdb':
            if settings.measurement_db_version == '1':
                # TODO: remove when influxdb 1.8.10 issue is fixed
                for table in data:
                    for row in table.records:
                        sec_recorded_on += row.values['_value']
            elif settings.measurement_db_version == '2':
                # 표(시리즈)마다 **더한다.** 데몬은 켜짐 시간에 누가 켰는지
                # (source_type·source_id)를 태그로 붙이므로, 사람·함수·AI 가 번갈아
                # 켠 출력은 SUM 이 시리즈 수만큼의 표로 나온다. 예전에는 마지막 표
                # 값으로 덮어써서 가동 시간·에너지 사용량이 크게 적게 나왔다
                # (2026-09-18 E2E: 1 시간 켜짐이 0.0 시간으로 보고됨).
                for table in data:
                    for row in table.records:
                        sec_recorded_on += row.values['_value']

    sec_currently_on = 0
    if output_time_on:
        sec_currently_on = min(output_time_on, past_seconds)

    return sec_recorded_on + sec_currently_on


def average_past_seconds(unique_id, unit, channel, past_seconds, measure=None):
    """Return measurement average for the past x seconds."""
    data = query_string(
        unit, unique_id,
        measure=measure,
        channel=channel,
        value='MEAN',
        past_sec=past_seconds)

    if data:
        settings = db_retrieve_table_daemon(Misc, entry='first')
        if settings.measurement_db_name == 'influxdb':
            for table in data:
                for row in table.records:
                    return row.values['_value']


def average_start_end_seconds(unique_id, unit, channel, str_start, str_end, measure=None):
    """Return measurement average for a period of time."""
    data = query_string(
        unit, unique_id,
        measure=measure,
        channel=channel,
        value='MEAN',
        start_str=str_start,
        end_str=str_end)

    if data:
        settings = db_retrieve_table_daemon(Misc, entry='first')
        if settings.measurement_db_name == 'influxdb':
            for table in data:
                for row in table.records:
                    return row.values['_value']


def sum_past_seconds(unique_id, unit, channel, past_seconds, measure=None):
    """Return measurement sum for the past x seconds."""
    data = query_string(
        unit, unique_id,
        measure=measure,
        channel=channel,
        value='SUM',
        past_sec=past_seconds)

    if data:
        total_seconds = 0
        settings = db_retrieve_table_daemon(Misc, entry='first')
        if settings.measurement_db_name == 'influxdb':
            if settings.measurement_db_version == '1':
                # TODO: remove when influxdb 1.8.10 issue is fixed
                for table in data:
                    for row in table.records:
                        total_seconds += row.values['_value']
                return total_seconds
            elif settings.measurement_db_version == '2':
                # 시리즈(태그 조합)마다 표가 따로 온다 — 덮어쓰지 않고 더한다
                # (output_sec_on 참고).
                for table in data:
                    for row in table.records:
                        total_seconds += row.values['_value']
        return total_seconds


def influx_time_str_to_milliseconds(timestamp):
    """Converts InfluxDB time string with "Z" from nanoseconds to milliseconds and removes the Z."""
    if type(timestamp) == datetime:
        start_date_time = timestamp.split('Z')[0].split('.')[0]
        start_milliseconds = timestamp.split('Z')[0].split('.')[1][:3]
    elif type(timestamp) == str:
        start_date_time = timestamp.split('Z')[0].split('.')[0]
        start_milliseconds = timestamp.split('Z')[0].split('.')[1][:3]
    else:
        return
    return '{}.{}'.format(start_date_time, start_milliseconds)


def valid_date_str(date_str):
    try:
        datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
    except ValueError:
        logger.exception(1)
        return False
    return True


def influx_to_list(data):
    """[(ts, value), ...] — 시간순 정렬 보장.

    같은 device_id/measure 라도 일부 쓰기에만 source_id/source_type 같은
    extra_tags 가 붙어 있으면(예: Function 이 제어를 넘겨받은 구간), Flux 는
    태그 집합이 다른 레코드를 별도 테이블로 쪼갠다 — 값은 하나의 논리적
    시계열인데 물리적으로는 여러 테이블에 나뉘어 온다는 뜻이다. 테이블을
    순서대로 이어 붙이면 뒤 테이블이 앞 테이블보다 과거일 때 배열 끝이
    시간 역행한다. 차트는 x 값이 오름차순이라고 가정하고 구간을 찾으므로,
    이 역행 구간 때문에 실제로는 존재하는 최신 데이터를 "범위 밖"으로 오판해
    그래프에서 통째로 사라진다(1일 확대 시 사용량이 안 보이던 문제가
    이것이었다). 반환 전에 정렬해 이 가정을 지켜준다.
    """
    list_data = []
    for table in data:
        for row in table.records:
            val = row.values.get('_value')
            if val is None:
                continue
            list_data.append((row.values['_time'].timestamp(), val))
    list_data.sort(key=lambda point: point[0])
    return list_data


def influxdb_get_count_points(data):
    """전체 개수 — 태그 집합이 갈라져 여러 테이블로 와도 합산한다(위 참조)."""
    total = 0
    found = False
    for table in data:
        for record in table.records:
            total += record.values['_value']
            found = True
    return total if found else None


def influxdb_get_first_point(data):
    """가장 이른 시각 — 여러 테이블 중 최솟값(위 참조, 테이블 순서는 신뢰 불가)."""
    earliest = None
    for table in data:
        for record in table.records:
            ts = record.values['_time']
            if earliest is None or ts < earliest:
                earliest = ts
    return earliest


#
# DEPRECATED
# TODO: Remove
#

def read_last_influxdb(unique_id, unit, channel, measure=None, duration_sec=None):
    """
    DEPRECATED: use read_influxdb_single()
    """
    last_measurement = read_influxdb_single(
        unique_id, unit, channel,
        measure=measure, duration_sec=duration_sec, value='LAST')
    return last_measurement


def read_past_influxdb(unique_id, unit, channel, past_seconds, measure=None):
    """
    DEPRECATED: use read_influxdb_list()
    """
    last_measurement = read_influxdb_list(
        unique_id, unit, channel,
        measure=measure, duration_sec=past_seconds)
    return last_measurement
