# -*- coding: utf-8 -*-
"""켜짐 시간 합계가 **시리즈마다 나뉜 표를 모두 더하는지**의 회귀 가드.

배경 — 2026-09-18 E2E(에너지 사용량). 데몬은 켜짐 시간(`duration_time`)에 누가
켰는지(source_type·source_id)를 태그로 붙인다. InfluxDB v2 의 SUM 은 태그
조합(시리즈)마다 표를 따로 돌려주는데, 합계 함수들이 v2 에서 **마지막 표 값으로
덮어써** 사람·함수·AI 가 번갈아 켠 출력의 가동 시간·에너지가 크게 적게 나왔다
(1 시간 켜짐 → 0.0 시간).
"""
import os
import sys
from types import SimpleNamespace

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))


def _tables(*sums):
    """SUM 결과 — 시리즈마다 표 하나, 표마다 행 하나."""
    return [SimpleNamespace(records=[SimpleNamespace(values={'_value': v})])
            for v in sums]


def _settings(version):
    return SimpleNamespace(measurement_db_name='influxdb',
                           measurement_db_version=version)


def test_output_sec_on_adds_every_series(monkeypatch):
    from aot.utils import influx

    monkeypatch.setattr(influx, 'db_retrieve_table_daemon',
                        lambda table, **kw: (_settings('2') if kw.get('entry')
                                             else SimpleNamespace(unique_id='o1')))
    monkeypatch.setattr(influx, 'query_string',
                        lambda *a, **kw: _tables(3600.0, 4.25))

    class _Daemon:
        def output_state(self, *a, **kw):
            return 'off'
    monkeypatch.setattr(influx, 'DaemonControl', _Daemon)

    assert influx.output_sec_on('o1', 86400) == 3604.25


def test_sum_past_seconds_adds_every_series(monkeypatch):
    from aot.utils import influx

    monkeypatch.setattr(influx, 'db_retrieve_table_daemon',
                        lambda table, **kw: _settings('2'))
    monkeypatch.setattr(influx, 'query_string',
                        lambda *a, **kw: _tables(10.0, 20.0, 30.0))

    assert influx.sum_past_seconds('o1', 's', 0, 3600) == 60.0


def test_operational_seconds_adds_every_series(monkeypatch):
    from aot.utils import runtime

    monkeypatch.setattr(runtime, 'query_string',
                        lambda *a, **kw: _tables(100.0, 50.0))

    class _Daemon:
        def output_state(self, *a, **kw):
            return 'off'
    monkeypatch.setattr(runtime, 'DaemonControl', _Daemon)

    assert runtime.get_operational_seconds('o1', 86400) == 150.0
