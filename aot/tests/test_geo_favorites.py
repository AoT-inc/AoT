# coding=utf-8
"""지도 즐겨찾기 — 담기·중복·한도·지우기, 마이그레이션, 시트가 쓰는 길(JS)과 서버 계약이 맞는지."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


class FavoritesService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(cls._tmp.name, 'fav.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoFavorite
        GeoFavorite.query.delete()
        db.session.commit()
        from aot.aot_flask.geo import geo_favorites
        self.F = geo_favorites

    def test_add_list_remove_keeps_the_order_they_were_saved(self):
        a, made_a = self.F.add('  창고  ', 36.1, 127.1, '창고길 1', created_by='kim')
        b, made_b = self.F.add('', 36.2, 127.2, '밭길 2')
        self.assertTrue(made_a and made_b)
        self.assertEqual(['창고', '밭길 2'], [f['name'] for f in self.F.listing()])   # 이름이 없으면 주소
        self.assertEqual('kim', a.created_by)
        self.F.remove(a.id)
        self.assertEqual(['밭길 2'], [f['name'] for f in self.F.listing()])

    def test_same_spot_is_not_added_twice_and_keeps_the_first_name(self):
        first, _ = self.F.add('우리 집', 36.123456, 127.123456)
        again, made = self.F.add('다른 이름', 36.123458, 127.123454)         # 약 1m 안
        self.assertFalse(made)
        self.assertEqual(first.id, again.id)
        self.assertEqual('우리 집', again.name)
        _, made_far = self.F.add('멀리', 36.1236, 127.1236)
        self.assertTrue(made_far)

    def test_name_falls_back_to_coordinates_and_is_trimmed(self):
        row, _ = self.F.add('', 10, 20)
        self.assertEqual('10.00000, 20.00000', row.name)
        long_row, _ = self.F.add('x' * 200, 11, 21, 'y' * 500)
        self.assertEqual(self.F.NAME_MAX, len(long_row.name))
        self.assertEqual(self.F.ADDRESS_MAX, len(long_row.address))

    def test_bad_input_and_limit(self):
        for lat, lng in (('x', 1), (91, 1), (1, 181), (float('nan'), 1), (None, None)):
            with self.assertRaises(self.F.FavoriteError) as cm:
                self.F.add('a', lat, lng)
            self.assertEqual('bad_coordinates', cm.exception.code)
        for i in range(self.F.MAX_FAVORITES):
            self.F.add('f%d' % i, 30 + i * 0.001, 120)
        with self.assertRaises(self.F.FavoriteError) as cm:
            self.F.add('over', 50, 50)
        self.assertEqual(('limit', 409), (cm.exception.code, cm.exception.status))
        with self.assertRaises(self.F.FavoriteError) as cm:
            self.F.remove(999999)
        self.assertEqual(404, cm.exception.status)


class FavoritesEditing(FavoritesService):
    """이름·순서·공유 — 개인용은 담은 사람 눈에만 보이고 그 사람만 고친다."""

    def test_rename_trims_and_refuses_empty(self):
        row, _ = self.F.add('a', 36, 127, created_by='kim')
        self.assertEqual('새 이름', self.F.update(row.id, 'lee', name='  새 이름 ').name)   # 공유된 것은 누구나
        with self.assertRaises(self.F.FavoriteError) as cm:
            self.F.update(row.id, 'lee', name='   ')
        self.assertEqual('bad_name', cm.exception.code)

    def test_private_favorites_are_visible_and_editable_only_to_the_owner(self):
        mine, _ = self.F.add('내 비밀', 36, 127, created_by='kim', shared=False)
        pub, _ = self.F.add('공유', 37, 127, created_by='kim')
        self.assertEqual(['내 비밀', '공유'], [f['name'] for f in self.F.listing('kim')])
        self.assertEqual(['공유'], [f['name'] for f in self.F.listing('lee')])
        self.assertEqual(['공유'], [f['name'] for f in self.F.search('', user=None)])    # AI(MCP)는 개인용을 못 본다
        for fn in (lambda: self.F.update(mine.id, 'lee', name='x'), lambda: self.F.remove(mine.id, 'lee'),
                   lambda: self.F.move(mine.id, 'lee', 'up')):
            with self.assertRaises(self.F.FavoriteError) as cm:
                fn()
            self.assertEqual(404, cm.exception.status)                                  # 있는지조차 알리지 않는다
        with self.assertRaises(self.F.FavoriteError) as cm:
            self.F.update(pub.id, 'lee', shared=False)                                  # 공유 여부는 담은 사람만
        self.assertEqual(403, cm.exception.status)
        self.assertFalse(self.F.update(pub.id, 'kim', shared=False).shared)
        self.assertTrue(self.F.to_dict(pub, 'kim')['mine'])
        self.assertFalse(self.F.to_dict(pub, 'lee')['mine'])

    def test_private_one_does_not_block_someone_else_saving_the_same_spot(self):
        self.F.add('개인', 36, 127, created_by='kim', shared=False)
        _, made = self.F.add('내 것', 36, 127, created_by='lee')
        self.assertTrue(made)

    def test_move_swaps_neighbours_in_the_visible_list(self):
        a, _ = self.F.add('A', 1, 1)
        b, _ = self.F.add('B', 2, 2)
        c, _ = self.F.add('C', 3, 3)
        self.F.move(c.id, None, 'up')
        self.assertEqual(['A', 'C', 'B'], [f['name'] for f in self.F.listing()])
        self.F.move(a.id, None, 'up')                                                   # 맨 위는 그대로
        self.assertEqual(['A', 'C', 'B'], [f['name'] for f in self.F.listing()])
        self.F.move(a.id, None, 'down')
        self.assertEqual(['C', 'A', 'B'], [f['name'] for f in self.F.listing()])
        with self.assertRaises(self.F.FavoriteError):
            self.F.move(a.id, None, 'sideways')

    def test_search_filters_name_and_address(self):
        self.F.add('Barn', 1, 1, 'Rice Road')
        self.F.add('Shed', 2, 2, 'Barn Lane')
        self.F.add('Pond', 3, 3)
        self.assertEqual(['Barn', 'Shed'], [f['name'] for f in self.F.search('barn')])
        self.assertEqual(3, len(self.F.search('')))
        self.assertEqual(1, len(self.F.search('', limit=1)))


class FavoritesWiring(unittest.TestCase):

    def test_migration_creates_and_drops_the_table_and_is_in_the_chain(self):
        path = _ROOT / 'alembic_db' / 'alembic' / 'versions' / 'p7_03_geo_favorite_20261104.py'
        spec = importlib.util.spec_from_file_location('p7_03', str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual('p7_02_drop_irrigation_design_20261102', mod.down_revision)
        # p7_04(L3-C) 가 뒤에 붙었으므로 head 가 아니라 자기 revision 만 확인한다.
        self.assertEqual('p7_03_geo_favorite_20261104', mod.revision)
        src = path.read_text(encoding='utf-8')
        self.assertIn("'geo_favorite'", src)
        self.assertIn('drop_table', src)

    def test_write_routes_need_edit_settings_and_reading_only_login(self):
        import inspect
        from aot.aot_flask.api import geo
        guard = inspect.getsource(geo._fav_write_guard)
        self.assertIn("user_has_permission('edit_settings')", guard)
        for fn in (geo.GeoFavorites.post, geo.GeoFavoriteItem.patch, geo.GeoFavoriteItem.delete, geo.GeoFavoriteMove.post):
            self.assertIn('_fav_write_guard()', inspect.getsource(fn))
        self.assertNotIn('_fav_write_guard', inspect.getsource(geo.GeoFavorites.get))
        self.assertNotIn('_fav_write_guard', inspect.getsource(geo.GeoAround.get))

    def test_find_favorites_returns_only_shared_places_without_owner_info(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from aot.aot_flask.geo import geo_favorites as F
        rows = [{'name': 'Barn', 'address': 'Rd', 'lat': 1.0, 'lng': 2.0, 'created_by': 'kim', 'shared': True}]
        from unittest import mock
        with mock.patch.object(F, 'search', return_value=rows) as m:
            out = S.find_favorites(query='barn', limit='5')
        m.assert_called_once_with('barn', limit=5, user=None)
        self.assertEqual({'status': 'ok', 'count': 1,
                          'favorites': [{'name': 'Barn', 'address': 'Rd', 'lat': 1.0, 'lng': 2.0}]}, out)

    def test_find_favorites_is_a_read_only_domain_op(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain.registry_data import OPS
        self.assertIn('find_favorites', R.DOMAIN_ONLY_TOOLS)
        op = next(o for o in OPS if (o.tool, o.op) == ('find', 'favorites'))
        self.assertEqual(('read', {'none': 'find_favorites'}), (op.effect, op.inner))
        self.assertNotIn('find_favorites', R.approval_required_tools())


if __name__ == '__main__':
    unittest.main()
