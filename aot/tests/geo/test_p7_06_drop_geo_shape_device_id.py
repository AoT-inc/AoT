# coding=utf-8
"""p7_06: geo_shape.device_id 삭제 + 가드 + 마커 유일성 트리거 (장치 위치 L4 / C-4)."""
import importlib.util
import os
import unittest

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_P = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'alembic_db',
                  'alembic', 'versions', 'p7_06_drop_geo_shape_device_id_20261105.py')
_spec = importlib.util.spec_from_file_location('p7_06', _P)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _db():
    e = sa.create_engine('sqlite://')
    c = e.connect()
    c.execute(sa.text(
        'CREATE TABLE geo_shape (id INTEGER PRIMARY KEY, unique_id TEXT, '
        'geo_id TEXT, type TEXT, device_id TEXT, channel_id TEXT)'))
    c.execute(sa.text('CREATE INDEX ix_geo_shape_device_id ON geo_shape (device_id)'))
    c.execute(sa.text(
        'CREATE UNIQUE INDEX geo_itg_i2_marker_unique ON geo_shape '
        "(geo_id, device_id, COALESCE(channel_id,'0')) "
        "WHERE device_id IS NOT NULL AND type='aot_device'"))
    c.execute(sa.text(
        'CREATE TABLE geo_binding (unique_id TEXT, spatial_kind TEXT, '
        'spatial_id TEXT, role TEXT, device_kind TEXT, device_id TEXT, '
        'channel_id TEXT, valid_from DATETIME, valid_to DATETIME, '
        'ended_reason TEXT)'))
    for t in m.DEVICE_TABLES:
        c.execute(sa.text('CREATE TABLE "%s" (unique_id TEXT)' % t))
    c.execute(sa.text("INSERT INTO output VALUES ('dev-1')"))
    return c


def _shape(c, uid, typ, dev=None, geo='m1', ch=None):
    if 'device_id' in _cols(c):
        c.execute(sa.text(
            'INSERT INTO geo_shape (unique_id, geo_id, type, device_id, channel_id) '
            'VALUES (:u,:g,:t,:d,:c)'), dict(u=uid, g=geo, t=typ, d=dev, c=ch))
    else:
        c.execute(sa.text(
            'INSERT INTO geo_shape (unique_id, geo_id, type, channel_id) '
            'VALUES (:u,:g,:t,:c)'), dict(u=uid, g=geo, t=typ, c=ch))


def _bind(c, sid, role='marker', dev='dev-1', ch='0'):
    c.execute(sa.text(
        "INSERT INTO geo_binding (unique_id, spatial_kind, spatial_id, role, "
        "device_kind, device_id, channel_id, valid_from) VALUES "
        "(:b,'shape',:s,:r,'output',:d,:c,'2026-11-05 00:00:00')"),
        dict(b='b-' + sid, s=sid, r=role, d=dev, c=ch))


def _upgrade(c):
    ctx = MigrationContext.configure(c)
    with Operations.context(ctx):
        m.op = Operations(ctx)
        m.upgrade()


def _cols(c):
    return {x['name'] for x in sa.inspect(c).get_columns('geo_shape')}


class DropColumn(unittest.TestCase):
    def test_drops_column_and_indexes_when_everything_is_bound(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'dev-1')
        _bind(c, 's1')
        _upgrade(c)
        self.assertNotIn('device_id', _cols(c))
        names = {r[0] for r in c.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='index'"))}
        self.assertNotIn('ix_geo_shape_device_id', names)
        self.assertNotIn('geo_itg_i2_marker_unique', names)

    def test_dead_reference_and_other_holder_do_not_block(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'ghost')          # 죽은 참조
        _shape(c, 's2', 'aot_device', 'dev-1')          # 자리에 다른 장치
        _bind(c, 's2', dev='dev-other')
        _shape(c, 's3', 'zone', 'dev-1')                # 장치를 매다는 type 아님
        _upgrade(c)
        self.assertNotIn('device_id', _cols(c))

    def test_guard_blocks_when_a_live_link_would_be_lost(self):
        c = _db()
        _shape(c, 's1', 'aot_device', 'dev-1')          # 바인딩 없음
        with self.assertRaises(RuntimeError):
            _upgrade(c)
        self.assertIn('device_id', _cols(c))            # 아무것도 지우지 않았다

    def test_idempotent_when_column_already_gone(self):
        c = _db()
        _upgrade(c)
        _upgrade(c)


class MarkerUniqueness(unittest.TestCase):
    def _after(self):
        c = _db()
        _upgrade(c)
        return c

    def test_second_marker_for_same_device_channel_map_is_blocked(self):
        c = self._after()
        _shape(c, 'a', 'aot_device', geo='m1')
        _shape(c, 'b', 'aot_device', geo='m1')
        _bind(c, 'a')
        with self.assertRaises(sa.exc.IntegrityError):
            _bind(c, 'b')

    def test_other_channel_other_map_and_areas_are_allowed(self):
        c = self._after()
        _shape(c, 'a', 'aot_device', geo='m1')
        _shape(c, 'b', 'aot_device', geo='m1')
        _shape(c, 'c', 'aot_device', geo='m2')
        _shape(c, 'z1', 'device', geo='m1')
        _shape(c, 'z2', 'device', geo='m1')
        _bind(c, 'a')
        _bind(c, 'b', ch='1')                           # 다른 채널
        _bind(c, 'c')                                   # 다른 지도
        _bind(c, 'z1', role='area')
        _bind(c, 'z2', role='area')                     # 구역은 여러 개 정당

    def test_ending_the_old_marker_frees_the_slot(self):
        c = self._after()
        _shape(c, 'a', 'aot_device')
        _shape(c, 'b', 'aot_device')
        _bind(c, 'a')
        c.execute(sa.text(
            "UPDATE geo_binding SET valid_to='2026-11-06 00:00:00', "
            "ended_reason='replaced' WHERE spatial_id='a'"))
        _bind(c, 'b')


if __name__ == '__main__':
    unittest.main()
