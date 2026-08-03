# coding=utf-8
"""Regression tests for the empty-payload wipe guard in GeoOverlayManager.save_overlays.

Background (2026-06-21 incident, aot-004): a full-sync save fired with an empty
feature list and deleted an entire design layer. save_overlays uses delta-sync
("rows missing from the payload are deleted"), so features=[] meant "delete all".
Only 'aot_device' was guarded; zone/site/facility/infra_blob/equipment were not.

These tests pin the generalized guard:
  - empty payload that would delete existing rows  -> BLOCKED (no delete)
  - same, but allow_empty=True                     -> proceeds (intentional clear)
  - partial payload (some features present)         -> normal delta delete, NOT blocked
  - empty payload but device-scoped (device_id set) -> targeted clear allowed
  - equipment empty payload with existing rows      -> BLOCKED

All DB/Flask dependencies are mocked; no real database is touched.
"""
import types
import unittest.mock as mock

import pytest

from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
import aot.aot_flask.geo.geo_overlays as mod


def _row(rid, node_id=None, rtype='zone'):
    return types.SimpleNamespace(
        id=rid,
        type=rtype,
        feature={'type': 'Feature',
                 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
                 'properties': {'node_id': node_id or f'n{rid}'}},
        device_id=None, channel_id=None, parent_id=None,
        unique_id=f'u{rid}', updated_at=None,
    )


class _FakeQuery:
    """Chainable stand-in for SQLAlchemy Query. Tracks whether delete() ran."""
    def __init__(self, rows):
        self._rows = list(rows)
        self.delete_called = False

    def filter_by(self, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def all(self):
        return self._rows

    def count(self):
        return len(self._rows)

    def delete(self, **kw):
        self.delete_called = True
        return len(self._rows)


@pytest.fixture
def patched(monkeypatch):
    """Patch module globals: GeoShape, db, current_app. Returns a handle dict."""
    fake_query = _FakeQuery([])

    fake_geoshape = mock.MagicMock(name='GeoShape')
    # GeoShape.query returns our fake; GeoShape() returns a fresh dummy row.
    type(fake_geoshape).query = mock.PropertyMock(return_value=fake_query)
    fake_geoshape.side_effect = lambda *a, **k: types.SimpleNamespace(**k)

    fake_db = mock.MagicMock(name='db')
    fake_app = mock.MagicMock(name='current_app')

    monkeypatch.setattr(mod, 'GeoShape', fake_geoshape)
    monkeypatch.setattr(mod, 'db', fake_db)
    monkeypatch.setattr(mod, 'current_app', fake_app)

    return {'query': fake_query, 'GeoShape': fake_geoshape, 'db': fake_db, 'app': fake_app}


def _set_rows(patched, rows):
    patched['query']._rows = list(rows)


# ─── Main delta-sync path ────────────────────────────────────────────────────

def test_empty_payload_with_existing_rows_is_blocked(patched):
    _set_rows(patched, [_row(1), _row(2)])
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'zone', 'features': []})
    assert err is None
    assert result['stats'].get('skipped') == 'empty_wipe_blocked'
    assert result['stats'].get('would_delete') == 2
    assert patched['query'].delete_called is False
    patched['db'].session.commit.assert_not_called()


def test_empty_payload_with_allow_empty_proceeds(patched):
    _set_rows(patched, [_row(1), _row(2)])
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'zone', 'features': [], 'allow_empty': True})
    assert err is None
    assert 'skipped' not in result['stats']
    assert result['stats']['deleted'] == 2
    assert patched['query'].delete_called is True
    patched['db'].session.commit.assert_called()


def test_partial_payload_is_not_blocked(patched, monkeypatch):
    # Skip shapely validation so the test stays DB/geo-lib independent.
    monkeypatch.setattr(GeoOverlayManager, '_validate_geometry_rules',
                        staticmethod(lambda f, t: (True, None)))
    monkeypatch.setattr(GeoOverlayManager, '_sync_device_properties',
                        staticmethod(lambda f: None))
    _set_rows(patched, [_row(1, node_id='keep'), _row(2, node_id='drop')])
    keep_feat = {'type': 'Feature',
                 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
                 'properties': {'node_id': 'keep', 'db_id': 1}}
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'zone', 'features': [keep_feat]})
    assert err is None
    assert result['stats'].get('skipped') is None
    # [I9] Row 2 (absent from payload) SURVIVES — save_overlays is
    # upsert-only now. Omission-as-deletion was the top producer of the
    # 2026-08-03 corruption (a client that lost db_id wiped and re-created
    # whole zones, severing every device membership). Deletions must go
    # through /overlays/delta deletes[] or features=[]+allow_empty.
    assert result['stats']['deleted'] == 0
    assert patched['query'].delete_called is False


def test_empty_device_scoped_requires_allow_empty(patched):
    # [I9] 장치 스코프라도 빈 페이로드 삭제는 allow_empty 명시가 필수.
    _set_rows(patched, [_row(1)])
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'zone', 'features': [], 'device_id': 'dev-1'})
    assert err is None
    assert result['stats'].get('skipped') == 'empty_wipe_blocked'
    assert patched['query'].delete_called is False


def test_empty_device_scoped_with_allow_empty_clears(patched):
    _set_rows(patched, [_row(1)])
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'zone', 'features': [],
         'device_id': 'dev-1', 'allow_empty': True})
    assert err is None
    assert result['stats'].get('skipped') is None
    assert patched['query'].delete_called is True


# ─── Equipment bulk-bundle path ──────────────────────────────────────────────

def test_equipment_empty_payload_with_existing_is_blocked(patched):
    _set_rows(patched, [_row(1, rtype='equipment_collection')])
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'equipment', 'features': []})
    assert err is None
    assert result['stats'].get('skipped') == 'empty_wipe_blocked'
    assert patched['query'].delete_called is False


def test_equipment_empty_payload_no_existing_is_noop_ok(patched):
    _set_rows(patched, [])  # nothing to wipe -> allowed to proceed
    result, err = GeoOverlayManager.save_overlays(
        {'map_uuid': 'm1', 'type': 'equipment', 'features': []})
    assert err is None
    assert result['stats'].get('skipped') is None
