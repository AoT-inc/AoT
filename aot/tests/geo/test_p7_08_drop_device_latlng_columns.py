# coding=utf-8
"""p7_08: 장치 latitude/longitude 삭제 (장치 위치 L4 S3c).

백필/승격 없음 — 컬럼은 리졸버가 읽지 않는 유령이라 지워도 해석이 안 바뀐다.
값이 남아 있던 행은 로그만 남기고 차단하지 않는다.
"""
import importlib.util
import os
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_P = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'alembic_db',
                  'alembic', 'versions', 'p7_08_drop_device_latlng_columns_20261106.py')
_spec = importlib.util.spec_from_file_location('p7_08', _P)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _db():
    e = sa.create_engine('sqlite://')
    c = e.connect()
    for t in m.DEVICE_TABLES:
        c.execute(sa.text(
            'CREATE TABLE "%s" (unique_id TEXT, latitude REAL, longitude REAL, '
            'name TEXT)' % t))
    return c


def _dev(c, table, uid, lat=None, lng=None):
    c.execute(sa.text(
        'INSERT INTO "%s" (unique_id, latitude, longitude) VALUES (:u,:la,:ln)' % table),
        dict(u=uid, la=lat, ln=lng))


def _upgrade(c):
    ctx = MigrationContext.configure(c)
    with Operations.context(ctx):
        m.op = Operations(ctx)
        m.upgrade()


def _cols(c, table):
    return {x['name'] for x in sa.inspect(c).get_columns(table)}


class DropLatLngColumns(unittest.TestCase):
    def test_drops_latlng_from_all_device_tables(self):
        c = _db()
        _dev(c, 'input', 'd1', lat=35.86, lng=126.88)     # 값이 있어도 백필 없이 지운다
        _upgrade(c)
        for t in m.DEVICE_TABLES:
            cols = _cols(c, t)
            self.assertNotIn('latitude', cols)
            self.assertNotIn('longitude', cols)

    def test_counts_rows_with_coords_without_blocking(self):
        c = _db()
        _dev(c, 'input', 'd1', lat=35.86, lng=126.88)
        _dev(c, 'output', 'o1', lat=36.0, lng=127.0)
        _dev(c, 'input', 'd2')                             # 좌표 없음
        self.assertEqual(m._count_rows_with_coords(c), 2)
        _upgrade(c)                                        # 차단하지 않는다
        self.assertNotIn('latitude', _cols(c, 'input'))

    def test_idempotent_when_columns_already_gone(self):
        c = _db()
        _upgrade(c)
        _upgrade(c)   # 두 번째도 조용히 지나간다


class Downgrade(unittest.TestCase):
    def test_downgrade_readds_columns(self):
        c = _db()
        _dev(c, 'input', 'd1', lat=35.86, lng=126.88)
        _upgrade(c)
        ctx = MigrationContext.configure(c)
        with Operations.context(ctx):
            m.op = Operations(ctx)
            m.downgrade()
        for t in m.DEVICE_TABLES:
            cols = _cols(c, t)
            self.assertIn('latitude', cols)
            self.assertIn('longitude', cols)


if __name__ == '__main__':
    unittest.main()
