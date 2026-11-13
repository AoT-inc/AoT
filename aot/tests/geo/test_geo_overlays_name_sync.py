# coding=utf-8
"""지도 저장의 이름 역동기화(`_sync_device_properties`)는 마커(점)에만 적용된다.

장치에 묶인 담당 구역(폴리곤)은 제 이름이 있다. 예전에는 지도를 저장할 때마다 구역 이름이
출력·채널 이름을 덮어 써서, E2E 시드의 팬 출력 'E2E State Fan' 이 'E2E Fan Area' 가 됐다.
"""
import types

import pytest

import aot.aot_flask.geo.geo_overlays as mod
from aot.aot_flask.geo.geo_overlays import GeoOverlayManager


class _Query:
    def __init__(self, row):
        self.row = row

    def filter_by(self, **kw):
        return self

    def first(self):
        return self.row


@pytest.fixture
def rows(monkeypatch):
    channel = types.SimpleNamespace(name='E2E State Fan', custom_options=None)
    output = types.SimpleNamespace(name='E2E State Fan', custom_options=None)
    monkeypatch.setattr(mod, 'OutputChannel', types.SimpleNamespace(query=_Query(channel)))
    model = types.SimpleNamespace(query=_Query(output))
    monkeypatch.setattr(mod, 'models_for', lambda *a, **k: {'output': model})
    monkeypatch.setattr(mod, 'current_app', types.SimpleNamespace(
        logger=types.SimpleNamespace(error=lambda *a, **k: None)))
    return channel, output


def _feature(geometry):
    return {'type': 'Feature', 'geometry': geometry,
            'properties': {'aot_type': 'output', 'device_type': 'output',
                           'device_id': 'fan-1', 'channel_id': '0', 'name': 'E2E Fan Area'}}


def test_a_device_area_polygon_does_not_rename_the_device(rows):
    channel, output = rows
    ring = [[0, 0], [0, 1], [1, 1], [0, 0]]
    GeoOverlayManager._sync_device_properties(_feature({'type': 'Polygon', 'coordinates': [ring]}))
    assert channel.name == 'E2E State Fan'
    assert output.name == 'E2E State Fan'


def test_a_line_bound_to_a_device_does_not_rename_it(rows):
    channel, output = rows
    GeoOverlayManager._sync_device_properties(
        _feature({'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}))
    assert (channel.name, output.name) == ('E2E State Fan', 'E2E State Fan')


def test_renaming_a_marker_still_renames_the_device(rows):
    channel, output = rows
    GeoOverlayManager._sync_device_properties(_feature({'type': 'Point', 'coordinates': [0, 0]}))
    assert channel.name == 'E2E Fan Area'
    assert output.name == 'E2E Fan Area'
