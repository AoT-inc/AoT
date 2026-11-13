# coding=utf-8
"""p7_05: 레거시 마커 백필 + 가드 (장치 위치 L4 / C-4 선행)."""
import importlib.util
import os
import unittest

import sqlalchemy as sa

_P = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'alembic_db',
                  'alembic', 'versions',
                  'p7_05_backfill_legacy_markers_20261105.py')
_spec = importlib.util.spec_from_file_location('p7_05', _P)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _db():
    e = sa.create_engine('sqlite://')
    c = e.connect()
    c.execute(sa.text(
        'CREATE TABLE geo_shape (unique_id TEXT, type TEXT, device_id TEXT, '
        'channel_id TEXT)'))
    c.execute(sa.text(
        'CREATE TABLE geo_binding (unique_id TEXT, spatial_kind TEXT, '
        'spatial_id TEXT, role TEXT, device_kind TEXT, device_id TEXT, '
        'channel_id TEXT, valid_from DATETIME, valid_to DATETIME, '
        'created_at DATETIME)'))
    for t in ('input', 'output', 'custom_controller', 'function', 'pid',
              'trigger', 'conditional'):
        c.execute(sa.text('CREATE TABLE "%s" (unique_id TEXT)' % t))
    c.execute(sa.text("INSERT INTO input VALUES ('dev-in')"))
    c.execute(sa.text("INSERT INTO output VALUES ('dev-out')"))
    return c


def _shape(c, sid, typ, dev, ch=None):
    c.execute(sa.text('INSERT INTO geo_shape VALUES (:a,:b,:c,:d)'),
              dict(a=sid, b=typ, c=dev, d=ch))


class Backfill(unittest.TestCase):
    def test_creates_marker_and_area(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'dev-in')
        _shape(c, 's2', 'device', 'dev-out', '1')
        st = m.backfill_legacy_markers(c)
        self.assertEqual(2, st['created'])
        rows = c.execute(sa.text(
            'SELECT spatial_id, role, device_kind, channel_id FROM geo_binding '
            'ORDER BY spatial_id')).fetchall()
        self.assertEqual([('s1', 'marker', 'input', '0'),
                          ('s2', 'area', 'output', '1')], [tuple(r) for r in rows])

    def test_idempotent(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'dev-in')
        m.backfill_legacy_markers(c)
        st = m.backfill_legacy_markers(c)
        self.assertEqual((0, 1), (st['created'], st['present']))

    def test_dead_ref_and_other_holder_skipped_not_blocking(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'ghost')
        _shape(c, 's2', 'aot_device', 'dev-in')
        c.execute(sa.text(
            "INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id, role,"
            " device_kind, device_id, channel_id) VALUES "
            "('b','shape','s2','marker','output','dev-out','0')"))
        st = m.backfill_legacy_markers(c)
        self.assertEqual(0, st['created'])
        self.assertEqual([('s1', 'ghost')], st['dead'])
        self.assertEqual([('s2', 'dev-in', 'dev-out')], st['slot_taken'])
        self.assertEqual([], st['failed'])

    def test_unmapped_type_reported(self):
        c = _db()
        _shape(c, 's1', 'polygon', 'dev-in')
        st = m.backfill_legacy_markers(c)
        self.assertEqual(1, len(st['unmapped_type']))

    def test_insert_failure_is_blocking(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'dev-in')
        c.execute(sa.text(
            'CREATE TRIGGER deny BEFORE INSERT ON geo_binding BEGIN '
            "SELECT RAISE(ABORT,'no'); END"))
        st = m.backfill_legacy_markers(c)
        self.assertEqual(1, len(st['failed']))

    def test_no_binding_table_is_noop(self):
        e = sa.create_engine('sqlite://')
        c = e.connect()
        c.execute(sa.text('CREATE TABLE geo_shape (unique_id TEXT)'))
        self.assertEqual(0, m.backfill_legacy_markers(c)['created'])


if __name__ == '__main__':
    unittest.main()
