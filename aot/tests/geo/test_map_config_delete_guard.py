# coding=utf-8
"""Regression tests for the shared-map guard in delete_map_config.

Background (2026-08-03 incident, aot-004): deleting one duplicate output wiped
the shared design map '임실군' -- 62 shapes plus the GeoMap row itself.

Why it happened: a device's `map_config_id` does not mean "this device owns
that map". The device settings page deliberately offers every non-device-owned
map (the user's design maps) so a device can be placed on the shared site map,
and picking one stores that uuid in `map_config_id`. The delete paths
(output/input/controller) then passed it straight to delete_map_config, which
deleted `geo_shape WHERE geo_id=<uuid>` and the GeoMap row with no ownership
check at all.

This is a different code path from the save_overlays empty-payload guard added
in e064f28 (see test_geo_overlays_guard.py) -- that guard sits on the overlay
save API and never sees these deletes.

These tests pin the guard:
  - shared/design map (is_device_owned=False)   -> BLOCKED
  - device-owned but another device references  -> BLOCKED
  - device-owned and unreferenced               -> deleted (normal case)
  - unknown uuid / empty uuid                   -> no-op, no crash

Plus the clone_map_config `type` carry-over, whose absence made every shape in
a cloned map invisible to get_overlays().

All DB/Flask dependencies are mocked; no real database is touched.
"""
import types
import unittest.mock as mock

import pytest

import aot.aot_flask.utils.utils_map_config as mod


class _DeleteTracker:
    """Chainable stand-in for SQLAlchemy Query recording delete()/first()."""

    def __init__(self, store, label, first_result=None):
        self.store = store
        self.label = label
        self.first_result = first_result

    def filter_by(self, **kwargs):
        return self

    def delete(self):
        self.store.append(self.label)
        return 1

    def first(self):
        return self.first_result


def _map(is_device_owned=True, category='device', name='m'):
    return types.SimpleNamespace(
        unique_id='map-uuid', name=name,
        category=category, is_device_owned=is_device_owned)


@pytest.fixture
def env(monkeypatch):
    """Wire GeoMap/GeoShape/current_app to trackers. Returns a control object."""
    deletes = []
    state = types.SimpleNamespace(map_row=_map(), deletes=deletes)

    monkeypatch.setattr(mod, 'GeoMap', types.SimpleNamespace(
        query=_DeleteTracker(deletes, 'geo_map', first_result=None)), raising=False)
    monkeypatch.setattr(mod, 'GeoShape', types.SimpleNamespace(
        query=_DeleteTracker(deletes, 'geo_shape')), raising=False)
    monkeypatch.setattr(mod, 'current_app', types.SimpleNamespace(
        logger=mock.Mock()), raising=False)

    def _set_map(row):
        state.map_row = row
        mod.GeoMap.query = _DeleteTracker(deletes, 'geo_map', first_result=row)

    state.set_map = _set_map
    _set_map(state.map_row)
    return state


def test_shared_design_map_is_not_deleted(env, monkeypatch):
    """The 2026-08-03 regression: a design map must survive device deletion."""
    env.set_map(_map(is_device_owned=False, category='design', name='임실군'))
    monkeypatch.setattr(mod, '_map_still_referenced', lambda uuid: None)

    mod.delete_map_config('map-uuid')

    assert env.deletes == [], "shared design map must never be deleted"


def test_device_owned_map_still_referenced_is_not_deleted(env, monkeypatch):
    env.set_map(_map(is_device_owned=True, category='device'))
    monkeypatch.setattr(mod, '_map_still_referenced', lambda uuid: ('Output', 'v01'))

    mod.delete_map_config('map-uuid')

    assert env.deletes == [], "a map another device still points at must survive"


def test_device_owned_unreferenced_map_is_deleted(env, monkeypatch):
    env.set_map(_map(is_device_owned=True, category='device'))
    monkeypatch.setattr(mod, '_map_still_referenced', lambda uuid: None)

    mod.delete_map_config('map-uuid')

    assert set(env.deletes) == {'geo_shape', 'geo_map'}


def test_category_design_with_owned_flag_is_not_deleted(env, monkeypatch):
    """Both conditions are required, not just is_device_owned."""
    env.set_map(_map(is_device_owned=True, category='design'))
    monkeypatch.setattr(mod, '_map_still_referenced', lambda uuid: None)

    mod.delete_map_config('map-uuid')

    assert env.deletes == []


def test_missing_and_empty_uuid_are_noops(env, monkeypatch):
    monkeypatch.setattr(mod, '_map_still_referenced', lambda uuid: None)

    mod.delete_map_config('')
    mod.delete_map_config(None)

    env.set_map(None)
    mod.delete_map_config('gone-uuid')

    assert env.deletes == []


def test_clone_carries_shape_type(monkeypatch):
    """Cloned shapes kept the column default 'feature', so get_overlays --
    which filters on type -- returned nothing for the copied map.

    Also pins that device-bound shapes are NOT copied: a cloned map belongs to
    a different device, so carrying the source device's marker over would put
    that device on two maps at once (2026-08-04)."""
    source_map = types.SimpleNamespace(
        unique_id='src', name='src', latitude=1, longitude=2, zoom=18,
        provider=None, style_url=None, api_key=None, use_satellite=False,
        providers=None, map_locked=False)
    overlays = [
        types.SimpleNamespace(id=1, parent_id=None, type='zone', device_id=None,
                              channel_id=None, layer_group='g', sort_order=3,
                              meta_json={'a': 1}, feature={'properties': {}}),
        types.SimpleNamespace(id=2, parent_id=None, type='facility',
                              device_id='dev', channel_id='ch',
                              layer_group=None, sort_order=0, meta_json=None,
                              feature={'properties': {}}),
    ]
    added = []

    def _fake_geo_map(**kw):
        return types.SimpleNamespace(unique_id='cloned', **kw)
    _fake_geo_map.query = _DeleteTracker([], 'geo_map', first_result=source_map)

    monkeypatch.setattr(mod, 'GeoMap', _fake_geo_map, raising=False)
    monkeypatch.setattr(mod, 'GeoShape', lambda **kw: kw, raising=False)
    mod.GeoShape.query = types.SimpleNamespace(
        filter_by=lambda **kw: types.SimpleNamespace(all=lambda: overlays))
    monkeypatch.setattr(mod, 'db', types.SimpleNamespace(
        session=types.SimpleNamespace(add=added.append, flush=lambda: None)),
        raising=False)
    monkeypatch.setattr(mod, 'current_app', types.SimpleNamespace(
        logger=mock.Mock()), raising=False)

    mod.clone_map_config('src', 'new device')

    shape_rows = [a for a in added if isinstance(a, dict)]
    # device_id 를 가진 'facility' 는 복제 대상이 아니다 — 장치 배치는 안 따라간다.
    assert [r['type'] for r in shape_rows] == ['zone']
    assert shape_rows[0]['layer_group'] == 'g'
    assert shape_rows[0]['sort_order'] == 3
    assert shape_rows[0]['meta_json'] == {'a': 1}
    assert 'device_id' not in shape_rows[0]
