# coding=utf-8
"""geo 설정 모달 — 색을 건드리지 않은 저장이 검정을 굳히지 않는다 / 설정 캐시가 DB 변경을 따라간다.

배경(2026-09-25 실측): 색 입력(<input type=color>)은 비울 수 없어 미설정 색이
#000000 으로 보이고, 위·경도만 바꿔 저장해도 폼 전체가 직렬화돼
theme_config 에 검정 일곱 개가 굳었다. 또 DB 를 직접 되돌려도
window.AOT_GEO_CONFIG 는 웹 프로세스를 재시작할 때까지 옛 값이었다.
"""
import json
import os
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.databases.models import GeoSetting

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
MODAL = os.path.join(ROOT, 'aot', 'aot_flask', 'templates', 'modals',
                     'geo_settings_modal.html')


def _make_app():
    from aot.config import AOT_DB_PATH
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 't'
    db.init_app(app)
    from flask_babel import Babel
    Babel(app)
    return app


class _Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        GeoSetting.query.delete()
        db.session.add(GeoSetting(theme_config='{}'))
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()

    def tearDown(self):
        db.session.rollback()
        GeoSetting.query.delete()
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()
        self.ctx.pop()


class TestSaveWithoutColours(_Base):
    def test_saving_only_lat_lng_leaves_colours_unset(self):
        from aot.aot_flask import routes_geo_map as r
        view = r.api_geo_settings
        while hasattr(view, '__wrapped__'):
            view = view.__wrapped__
        with self.app.test_request_context(
                '/api/geo/settings', method='POST',
                data={'default_lat': '35.1', 'default_lng': '127.2',
                      'default_zoom': '14'}):
            with mock.patch.object(r.utils_general, 'user_has_permission',
                                   return_value=True):
                resp = view()
        self.assertTrue(resp.get_json()['ok'])
        row = GeoSetting.query.populate_existing().first()
        self.assertEqual(row.default_lat, 35.1)
        theme = json.loads(row.theme_config or '{}')
        for key in ('site', 'zone', 'facility', 'equipment', 'device',
                    'panel_bg'):
            self.assertNotIn(key, theme)

    def test_modal_does_not_send_untouched_colours(self):
        src = open(MODAL, encoding='utf-8').read()
        # 미설정 색은 표시만 하고 직렬화에서 뺀다.
        self.assertIn(".not('.aot-geo-theme-color[data-unset]')", src)
        self.assertIn("attr('data-unset', '1')", src)
        self.assertIn("removeAttr('data-unset')", src)


class TestConfigCacheFollowsDb(_Base):
    def _theme(self):
        with self.app.test_request_context('/'):
            return utils_geo.get_geo_config().get('theme_config') or {}

    def test_direct_db_change_is_visible_without_invalidate(self):
        GeoSetting.query.first().theme_config = json.dumps({'zone': '#000000'})
        db.session.commit()
        self.assertEqual(self._theme().get('zone'), '#000000')

        # 앱 밖에서 DB 를 직접 되돌린 것과 같다 — invalidate 는 불리지 않는다.
        db.session.execute(db.text("UPDATE geo_setting SET theme_config='{}'"))
        db.session.commit()
        self.assertEqual(self._theme(), {})


if __name__ == '__main__':
    unittest.main()
