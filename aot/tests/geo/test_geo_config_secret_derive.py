# coding=utf-8
"""get_geo_config — 활성 레이어 목록은 한 번만 계산하고, 키 없는 판은 비밀 포함 판에서 파생한다.

배경(2026-11-10 실측): (locale, with_secrets) 두 벌이 `get_active_geo_layers` 를 각각 돌려
대시보드 콜드 로드에 InputModule 을 90번 만들었다. 파생해도 키는 키 없는 판에 남으면 안 된다
(2026-09-08 사고: 모든 페이지 HTML 에 지도 키 평문).
"""
import json
import unittest
from unittest import mock

from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.databases.models import GeoSetting
from aot.tests.geo.test_geo_settings_theme_unset import _make_app

KEY = 'SECRET-KEY-0123456789'


def _layers():
    return [
        {'id': 'base1', 'type': 'vector', 'role': 'base', 'api_key': KEY,
         'url': 'https://t.example/{z}/{x}/{y}?key=' + KEY, 'options': {'style': 'x?key=' + KEY}},
        {'id': 'base2', 'type': 'vector', 'role': 'base', 'api_key': KEY,
         'url': 'https://t.example/b2?key=' + KEY, 'options': {'k': KEY}},
        {'id': 'ov1', 'type': 'xyz', 'role': 'overlay', 'api_key': KEY,
         'url': 'https://o.example/{z}/{x}/{y}?appid=' + KEY, 'options': {'appid': KEY}},
    ]


def _fake_layers(k=None, layer_ids=None):
    return _layers()


class TestSecretDerive(unittest.TestCase):
    def setUp(self):
        from aot.utils import water_terrain
        water_terrain.wait_idle()          # 앞 시험이 남긴 배경 선계산이 get_geo_config 를 부르지 않게
        # 이 시험이 부르는 invalidate 도 DEM 배경 작업을 예약한다. 그 작업은 다른 스레드에서
        # get_geo_config 를 부르고(전역으로 바꿔 둔 get_active_geo_layers 를 같이 센다) 판이
        # 바뀌었다고 보면 캐시를 다시 비운다 — 앞 시험이 남긴 DEM 상태에 따라 예약 여부가 갈려
        # 병렬 CI 배치에 따라서만 2 != 1 로 깨졌다. 여기서 재는 것은 캐시 파생이므로 막는다.
        patcher = mock.patch.object(water_terrain, 'on_geo_config_changed',
                                    return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        GeoSetting.query.delete()
        db.session.add(GeoSetting(theme_config='{}', keys=json.dumps({'maptiler': KEY})))
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()

    def tearDown(self):
        db.session.rollback()
        GeoSetting.query.delete()
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()
        self.ctx.pop()

    def _get(self, with_secrets):
        with self.app.test_request_context('/'):
            return utils_geo.get_geo_config(with_secrets=with_secrets)

    def test_layers_computed_once_for_both_variants_in_either_order(self):
        for order in ((False, True), (True, False)):
            utils_geo.invalidate_geo_config_cache()
            with mock.patch.object(utils_geo, 'get_active_geo_layers',
                                   side_effect=_fake_layers) as m:
                for ws in order:
                    self._get(ws)
                self.assertEqual(m.call_count, 1, order)

    def test_public_variant_never_carries_the_key(self):
        with mock.patch.object(utils_geo, 'get_active_geo_layers', side_effect=_fake_layers):
            secret = self._get(True)
            public = self._get(False)
        self.assertIn(KEY, json.dumps(secret))                 # 서버 안 호출자는 키를 받는다
        self.assertEqual(public['keys'], {})
        by_id = {lay['id']: lay for lay in public['layers']}
        # 첫 벡터 베이스 하나만 키가 남는 기존 계약 — 나머지 어디에도 없어야 한다.
        for lid in ('base2', 'ov1'):
            self.assertNotIn(KEY, json.dumps(by_id[lid]))
        self.assertEqual(by_id['ov1']['url'], '/api/geo/tile/ov1/{z}/{x}/{y}')
        rest = dict(public)
        rest['layers'] = [lay for lay in public['layers'] if lay['id'] != 'base1']
        self.assertNotIn(KEY, json.dumps(rest))

    def test_secret_variant_is_not_changed_by_deriving_public(self):
        with mock.patch.object(utils_geo, 'get_active_geo_layers', side_effect=_fake_layers):
            secret = self._get(True)
            self._get(False)
            again = self._get(True)
        self.assertIs(secret, again)
        by_id = {lay['id']: lay for lay in secret['layers']}
        self.assertEqual(by_id['ov1']['api_key'], KEY)
        self.assertIn(KEY, by_id['ov1']['url'])
        self.assertEqual(secret['keys'], {'maptiler': KEY})

    def test_module_cache_is_created_outside_the_layer_loop(self):
        import inspect
        src = inspect.getsource(utils_geo.get_active_geo_layers)
        self.assertEqual(src.count('_module_cache = {}'), 1)
        self.assertLess(src.index('_module_cache = {}'),
                        src.index('for layer in active_layers:\n        layer_def'))


if __name__ == '__main__':
    unittest.main()
