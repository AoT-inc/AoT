# coding=utf-8
"""Regression tests: ephemeral sprinkler dot markers must never be persisted.

Background (2026-09-03 incident, 나주 map): geo/design's sprinkler generator
creates two layers per emitter — a `sprinkler_coverage` circle (the canonical,
persisted emitter; see aot-geo-stats.js and plot_journal._EMITTER_SUB_TYPE)
and a `sprinkler` dot marker meant to be a client-side-only visual decoration.
The dot marker was, in practice, saved to the DB anyway. Because the client's
load path (`_loadAllFeatures`) refuses to load these Point markers back, a
session could never see its own previously-saved dots to delete them, and
both save paths (`save_overlays`'s full-replace bulk-bundle, and
`save_delta`'s additive merge) only ever act on what the client currently
knows about. Every "regenerate sprinklers" cycle therefore piled a fresh
batch of dots on top of invisible leftovers — one emitter ended up with 8
duplicate dot markers, some still carrying a stale flow value from before a
spec change (850 -> 70 L/h).

The fix filters `sub_type == 'sprinkler'` Point features out at the actual
persistence boundary (GeoOverlayManager), so it holds regardless of which
client code path (or a future one) tries to save them. These tests pin that
boundary directly, with no real database — matching the mocking style of
test_geo_overlays_guard.py.
"""
import types
import unittest.mock as mock

import pytest

import aot.aot_flask.geo.geo_overlays as mod
from aot.aot_flask.geo.geo_overlays import (
    GeoOverlayManager, _is_ephemeral_sprinkler_marker)


def _sprinkler_marker(node_id='spr-1', flow=70, lng=126.7, lat=34.8):
    return {'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lng, lat]},
            'properties': {'node_id': node_id, 'aot_type': 'equipment',
                            'sub_type': 'sprinkler', 'flow': flow,
                            'parent_node_id': 'pipe-1', 'zone_id': 'zone-1'}}


def _sprinkler_coverage(node_id='cov-1', flow=70):
    return {'type': 'Feature',
            'geometry': {'type': 'Polygon',
                         'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
            'properties': {'node_id': node_id, 'aot_type': 'equipment',
                            'sub_type': 'sprinkler_coverage', 'flow': flow,
                            'is_circle': True}}


def _pipe(node_id='pipe-1'):
    return {'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [0, 1]]},
            'properties': {'node_id': node_id, 'aot_type': 'equipment',
                            'sub_type': 'pipe_branch'}}


# ─── Pure predicate ──────────────────────────────────────────────────────────

def test_is_ephemeral_sprinkler_marker_matches_only_the_dot():
    assert _is_ephemeral_sprinkler_marker(_sprinkler_marker()) is True
    assert _is_ephemeral_sprinkler_marker(_sprinkler_coverage()) is False
    assert _is_ephemeral_sprinkler_marker(_pipe()) is False
    assert _is_ephemeral_sprinkler_marker({}) is False
    assert _is_ephemeral_sprinkler_marker(None) is False


# ─── save_overlays: bulk equipment bundle path ──────────────────────────────

class _FakeQuery:
    """Chainable stand-in for SQLAlchemy Query (mirrors test_geo_overlays_guard)."""
    def __init__(self, rows):
        self._rows = list(rows)
        self.delete_called = False

    def filter_by(self, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)

    def delete(self, **kw):
        self.delete_called = True
        return len(self._rows)


@pytest.fixture
def patched(monkeypatch):
    fake_query = _FakeQuery([])

    fake_geoshape = mock.MagicMock(name='GeoShape')
    type(fake_geoshape).query = mock.PropertyMock(return_value=fake_query)
    fake_geoshape.side_effect = lambda *a, **k: types.SimpleNamespace(**k)

    fake_db = mock.MagicMock(name='db')
    fake_app = mock.MagicMock(name='current_app')

    monkeypatch.setattr(mod, 'GeoShape', fake_geoshape)
    monkeypatch.setattr(mod, 'db', fake_db)
    monkeypatch.setattr(mod, 'current_app', fake_app)

    return {'query': fake_query, 'GeoShape': fake_geoshape, 'db': fake_db}


def test_save_overlays_equipment_drops_sprinkler_dot_keeps_the_rest(patched):
    payload = {'map_uuid': 'm1', 'type': 'equipment',
               'features': [_sprinkler_marker(), _pipe(), _sprinkler_coverage()]}
    result, err = GeoOverlayManager.save_overlays(payload)
    assert err is None
    assert result['ok'] is True
    assert result['count'] == 2  # sprinkler dot excluded, pipe + coverage kept

    added = patched['db'].session.add.call_args[0][0]
    saved_subtypes = sorted(f['properties']['sub_type'] for f in added.feature['features'])
    assert saved_subtypes == ['pipe_branch', 'sprinkler_coverage']


def test_save_overlays_equipment_all_sprinkler_dots_treated_as_empty(patched):
    # No real equipment existed before, so an all-dots payload is a true no-op,
    # not a wipe of real data.
    payload = {'map_uuid': 'm1', 'type': 'equipment',
               'features': [_sprinkler_marker('a'), _sprinkler_marker('b')]}
    result, err = GeoOverlayManager.save_overlays(payload)
    assert err is None
    assert result['stats'].get('skipped') is None
    assert result['count'] == 0


def test_save_overlays_equipment_all_sprinkler_dots_blocked_when_real_rows_exist(patched):
    # Existing real equipment rows must not be wiped just because this
    # particular save happened to carry only stale dot markers.
    patched['query']._rows = [types.SimpleNamespace(id=1, type='equipment_collection')]
    payload = {'map_uuid': 'm1', 'type': 'equipment',
               'features': [_sprinkler_marker()]}
    result, err = GeoOverlayManager.save_overlays(payload)
    assert err is None
    assert result['stats'].get('skipped') == 'empty_wipe_blocked'
    assert patched['query'].delete_called is False


# ─── save_delta: additive merge into the equipment_collection bundle ────────

def test_save_delta_upsert_drops_sprinkler_dot_keeps_the_rest(patched, monkeypatch):
    monkeypatch.setattr(mod, 'flag_modified', mock.MagicMock())
    payload = {'map_uuid': 'm1',
               'upserts': [_sprinkler_marker(), _pipe()]}
    result, err = GeoOverlayManager.save_delta(payload)
    assert err is None

    added = patched['db'].session.add.call_args[0][0]
    saved_subtypes = [f['properties']['sub_type'] for f in added.feature['features']]
    assert saved_subtypes == ['pipe_branch']


def test_save_delta_upsert_only_sprinkler_dots_creates_no_bundle(patched, monkeypatch):
    monkeypatch.setattr(mod, 'flag_modified', mock.MagicMock())
    payload = {'map_uuid': 'm1', 'upserts': [_sprinkler_marker()]}
    result, err = GeoOverlayManager.save_delta(payload)
    assert err is None
    patched['db'].session.add.assert_not_called()
