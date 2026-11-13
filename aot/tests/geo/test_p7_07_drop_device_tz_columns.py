# coding=utf-8
"""p7_07: 장치 timezone/tz_source 삭제 + explicit → 자리 도형 승격 가드 (장치 위치 L4 S3b)."""
import importlib.util
import os
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_P = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'alembic_db',
                  'alembic', 'versions', 'p7_07_drop_device_tz_columns_20261105.py')
_spec = importlib.util.spec_from_file_location('p7_07', _P)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _db():
    e = sa.create_engine('sqlite://')
    c = e.connect()
    c.execute(sa.text(
        'CREATE TABLE geo_shape (id INTEGER PRIMARY KEY, unique_id TEXT, '
        'timezone TEXT, tz_source TEXT)'))
    c.execute(sa.text(
        'CREATE TABLE geo_binding (unique_id TEXT, spatial_kind TEXT, '
        'spatial_id TEXT, role TEXT, device_kind TEXT, device_id TEXT, '
        'channel_id TEXT, valid_from DATETIME, valid_to DATETIME)'))
    for t in m.DEVICE_TABLES:
        c.execute(sa.text(
            'CREATE TABLE "%s" (unique_id TEXT, latitude REAL, longitude REAL, '
            'timezone TEXT, tz_source TEXT)' % t))
    return c


def _shape(c, uid, tz=None, src=None):
    c.execute(sa.text(
        'INSERT INTO geo_shape (unique_id, timezone, tz_source) VALUES (:u,:t,:s)'),
        dict(u=uid, t=tz, s=src))


def _bind(c, sid, dev, role='marker'):
    c.execute(sa.text(
        "INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id, role, "
        "device_kind, device_id, channel_id, valid_from) VALUES "
        "(:b,'shape',:s,:r,'output',:d,'0','2026-11-05 00:00:00')"),
        dict(b='b-' + sid + '-' + dev, s=sid, r=role, d=dev))


def _dev(c, table, uid, tz=None, src=None, lat=1.0, lng=2.0):
    c.execute(sa.text(
        'INSERT INTO "%s" (unique_id, latitude, longitude, timezone, tz_source) '
        'VALUES (:u,:la,:ln,:t,:s)' % table),
        dict(u=uid, la=lat, ln=lng, t=tz, s=src))


def _upgrade(c):
    ctx = MigrationContext.configure(c)
    with Operations.context(ctx):
        m.op = Operations(ctx)
        m.upgrade()


def _cols(c, table):
    return {x['name'] for x in sa.inspect(c).get_columns(table)}


def _shape_tz(c, uid):
    return c.execute(sa.text(
        'SELECT timezone, tz_source FROM geo_shape WHERE unique_id=:u'),
        dict(u=uid)).first()


class DropTzColumns(unittest.TestCase):
    def test_drops_tz_columns_keeps_latlng(self):
        c = _db()
        _dev(c, 'input', 'd1', tz='Asia/Seoul', src='coords')
        _upgrade(c)
        for t in m.DEVICE_TABLES:
            cols = _cols(c, t)
            self.assertNotIn('timezone', cols)
            self.assertNotIn('tz_source', cols)
            self.assertIn('latitude', cols)
            self.assertIn('longitude', cols)

    def test_idempotent_when_columns_already_gone(self):
        c = _db()
        _upgrade(c)
        _upgrade(c)   # 두 번째도 조용히 지나간다


class ExplicitPromotion(unittest.TestCase):
    def test_placed_explicit_is_promoted_to_marker_shape(self):
        c = _db()
        _shape(c, 's1')                                   # 자리 도형, tz 없음
        _bind(c, 's1', 'd1')
        _dev(c, 'output', 'd1', tz='Asia/Tokyo', src='explicit')
        _upgrade(c)
        self.assertEqual(_shape_tz(c, 's1'), ('Asia/Tokyo', 'explicit'))

    def test_marker_preferred_over_area_when_both_bound(self):
        c = _db()
        _shape(c, 'area1')
        _shape(c, 'mk1')
        _bind(c, 'area1', 'd1', role='area')
        _bind(c, 'mk1', 'd1', role='marker')
        _dev(c, 'output', 'd1', tz='Asia/Tokyo', src='explicit')
        _upgrade(c)
        self.assertEqual(_shape_tz(c, 'mk1'), ('Asia/Tokyo', 'explicit'))
        self.assertEqual(_shape_tz(c, 'area1'), (None, None))  # 안 건드림

    def test_shape_already_explicit_is_not_overwritten(self):
        c = _db()
        _shape(c, 's1', tz='Europe/Paris', src='explicit')  # 사람이 도형에 정함
        _bind(c, 's1', 'd1')
        _dev(c, 'output', 'd1', tz='Asia/Tokyo', src='explicit')
        _upgrade(c)
        self.assertEqual(_shape_tz(c, 's1'), ('Europe/Paris', 'explicit'))

    def test_non_explicit_is_not_promoted(self):
        c = _db()
        _shape(c, 's1')
        _bind(c, 's1', 'd1')
        _dev(c, 'output', 'd1', tz='Asia/Seoul', src='coords')
        _upgrade(c)
        self.assertEqual(_shape_tz(c, 's1'), (None, None))

    def test_placeless_explicit_aborts_and_drops_nothing(self):
        c = _db()
        _dev(c, 'output', 'd1', tz='Asia/Tokyo', src='explicit')  # 바인딩 없음
        with self.assertRaises(RuntimeError):
            _upgrade(c)
        self.assertIn('tz_source', _cols(c, 'output'))            # 아무것도 안 지움

    def test_ended_binding_does_not_count_as_a_place(self):
        c = _db()
        _shape(c, 's1')
        _bind(c, 's1', 'd1')
        c.execute(sa.text("UPDATE geo_binding SET valid_to='2026-11-06 00:00:00'"))
        _dev(c, 'output', 'd1', tz='Asia/Tokyo', src='explicit')
        with self.assertRaises(RuntimeError):            # 끝난 바인딩은 자리가 아니다
            _upgrade(c)


class Downgrade(unittest.TestCase):
    def test_downgrade_readds_columns(self):
        c = _db()
        _dev(c, 'input', 'd1', tz='Asia/Seoul', src='coords')
        _upgrade(c)
        ctx = MigrationContext.configure(c)
        with Operations.context(ctx):
            m.op = Operations(ctx)
            m.downgrade()
        for t in m.DEVICE_TABLES:
            cols = _cols(c, t)
            self.assertIn('timezone', cols)
            self.assertIn('tz_source', cols)


if __name__ == '__main__':
    unittest.main()
