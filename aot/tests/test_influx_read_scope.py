# coding=utf-8
"""Influx 읽기 오버헤드 (MCP 구역 요약 지연, 2026-11-07).

1. `influx_scope` — 도구 호출 하나 동안 `Misc` 읽기를 한 번만. 블록이 끝나면 캐시도 없다.
2. `_time_value_rows` — 두 칸만 변환하는 읽기가 `influxdb_client` 의 전체 파싱과 **같은 값·같은 형**을 낸다.
   (값이 같아야 하는 최적화라, 기존 파서를 정답으로 두고 비교한다.)
"""
import io
from unittest import mock

import pytest
from influxdb_client.client.flux_csv_parser import (FluxCsvParser,
                                                    FluxQueryException,
                                                    FluxSerializationMode)

from aot.utils import influx as I

CSV = (
    '#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,dateTime:RFC3339,double,string,string,string,string\r\n'
    '#group,false,false,true,true,false,false,true,true,true,true\r\n'
    '#default,_result,,,,,,,,,\r\n'
    ',result,table,_start,_stop,_time,_value,_field,_measurement,device_id,channel\r\n'
    ',,0,2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,2026-11-01T00:00:05.123456789Z,21.5,value,C,d1,0\r\n'
    ',,0,2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,2026-11-01T00:10:05Z,22,value,C,d1,0\r\n'
    ',,1,2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,2026-11-01T00:00:07Z,-3.25e-2,value,C,d1,1\r\n'
    '\r\n'
    '#datatype,string,long,dateTime:RFC3339,dateTime:RFC3339,dateTime:RFC3339,long,string,string,string\r\n'
    '#group,false,false,true,true,false,false,true,true,true\r\n'
    '#default,_result,,,,,7,,,\r\n'
    ',result,table,_start,_stop,_time,_value,_field,_measurement,device_id\r\n'
    ',,0,2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,2026-11-01T01:00:00Z,5,value,s,d2\r\n'
    ',,0,2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,2026-11-01T02:00:00Z,,value,s,d2\r\n'
    '\r\n'
)


def _reference(text):
    parser = FluxCsvParser(response=io.BytesIO(text.encode()),
                           serialization_mode=FluxSerializationMode.tables)
    with parser:
        for _ in parser._parse_flux_response():
            pass
    return [(r.values['_time'], r.values['_value'])
            for t in parser.tables for r in t.records]


def _lean(text):
    import codecs
    import csv
    return I._time_value_rows(csv.reader(codecs.iterdecode(io.BytesIO(text.encode()), 'utf-8')))


def test_lean_parse_matches_full_parse_values_and_types():
    ref, got = _reference(CSV), _lean(CSV)
    assert got == ref and len(got) == 5
    for (rt, rv), (gt, gv) in zip(ref, got):
        assert type(rt) is type(gt) and repr(rt) == repr(gt)
        assert type(rv) is type(gv)
    assert got[-1][1] == 7          # 빈 칸은 `#default` 를 따른다 (기존 파서와 같다)


def test_lean_parse_empty_result_is_empty_list_not_none():
    assert _lean('') == []


def test_lean_parse_raises_on_error_response():
    err = ('#datatype,string,string\r\n#group,true,true\r\n#default,,\r\n'
           ',error,reference\r\n,failed to create physical plan,897\r\n')
    with pytest.raises(FluxQueryException):
        _reference(err)
    with pytest.raises(ValueError):
        _lean(err)


class _Client:
    """`InfluxDBClient` 대역 — `query_csv` 만 안다."""
    seen = []

    def __init__(self, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query_api(self):
        outer = self

        class Q:
            def query_csv(self, query):
                _Client.seen.append(query)
                import codecs
                import csv
                return csv.reader(codecs.iterdecode(io.BytesIO(CSV.encode()), 'utf-8'))
        return Q()


class _Misc:
    measurement_db_name = 'influxdb'
    measurement_db_host = 'localhost'
    measurement_db_port = 8086
    measurement_db_version = '2'
    measurement_db_password = 'tok'
    measurement_db_dbname = 'b'
    measurement_db_user = 'u'
    measurement_db_retention_policy = 'rp'


def test_read_influxdb_list_returns_epoch_or_datetime_like_before():
    with mock.patch.object(I, '_misc_settings', return_value=_Misc()), \
            mock.patch.object(I, 'InfluxDBClient', _Client):
        dts = I.read_influxdb_list('d1', 'C', 0, measure='t', duration_sec=60, datetime_obj=True)
        eps = I.read_influxdb_list('d1', 'C', 0, measure='t', duration_sec=60)
    ref = _reference(CSV)
    assert dts == ref
    assert eps == [(t.timestamp(), v) for t, v in ref]


def test_read_influxdb_list_returns_none_when_not_influx_or_query_fails():
    m = _Misc()
    m.measurement_db_name = 'other'
    with mock.patch.object(I, '_misc_settings', return_value=m):
        assert I.read_influxdb_list('d1', 'C', 0, duration_sec=60) is None
    m = _Misc()
    m.measurement_db_version = '9'
    with mock.patch.object(I, '_misc_settings', return_value=m):
        assert I.read_influxdb_list('d1', 'C', 0, duration_sec=60) is None

    class Boom(_Client):
        def query_api(self):
            raise RuntimeError('down')
    with mock.patch.object(I, '_misc_settings', return_value=_Misc()), \
            mock.patch.object(I, 'InfluxDBClient', Boom):
        assert I.read_influxdb_list('d1', 'C', 0, duration_sec=60) is None


def test_lean_query_text_is_the_same_as_query_flux():
    """서버로 가는 질의문은 바뀌지 않는다 — 파싱 범위만 달라졌다."""
    _Client.seen.clear()
    with mock.patch.object(I, '_misc_settings', return_value=_Misc()), \
            mock.patch.object(I, 'InfluxDBClient', _Client):
        I.read_influxdb_list('d1', 'C', 0, measure='t', duration_sec=60)
        lean = _Client.seen[-1]
        built = I._flux_query_and_conn(_Misc(), 'C', 'd1', measure='t', channel=0, past_sec=60)
    assert lean == built[2]
    assert 'range(start: -60s)' in lean


def test_influx_scope_reads_misc_once_and_forgets_after():
    row = _Misc()
    with mock.patch.object(I, 'db_retrieve_table_daemon', return_value=row) as rd:
        I._misc_settings()
        I._misc_settings()
        assert rd.call_count == 2                   # 블록 밖: 호출마다 읽는다
        rd.reset_mock()
        with I.influx_scope():
            assert I._misc_settings() is row
            assert I._misc_settings() is row
            with I.influx_scope():                  # 중첩은 바깥 캐시를 쓴다
                I._misc_settings()
        assert rd.call_count == 1
        I._misc_settings()
        assert rd.call_count == 2                   # 블록이 끝나면 캐시도 사라진다


def test_influx_scope_does_not_cache_failed_read():
    with mock.patch.object(I, 'db_retrieve_table_daemon', side_effect=[None, _Misc()]) as rd:
        with I.influx_scope():
            assert I._misc_settings() is None
            assert I._misc_settings() is not None
        assert rd.call_count == 2
