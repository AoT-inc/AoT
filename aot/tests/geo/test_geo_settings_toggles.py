# coding=utf-8
"""geo 설정 모달 — 한 번 켠 토글을 끌 수 있다 / 표시가 모델 기본값과 같다.

배경(2026-09-27 실측): 모달이 폼을 `.serialize()` 로 보내 꺼진 체크박스는
요청에서 빠졌고, 서버는 받은 키만 저장하므로 digital_zoom·smooth_zoom·
tile_fade_animation·prefer_canvas 는 한 번 켜면 끌 수 없었다. 또
maplibre_local_serving 은 미설정 = 로컬(layout.html)인데 모달이 꺼짐으로
보여, 아무것도 안 건드리고 저장해도 false(CDN)가 기록됐다.
"""
import os
import re
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

BOOL_FIELDS = ('digital_zoom', 'smooth_zoom', 'tile_fade_animation',
               'prefer_canvas')


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


class TestServerSavesOnlyReceivedKeys(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        GeoSetting.query.delete()
        db.session.add(GeoSetting(digital_zoom=True, smooth_zoom=True,
                                  tile_fade_animation=True,
                                  prefer_canvas=True))
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()

    def tearDown(self):
        db.session.rollback()
        GeoSetting.query.delete()
        db.session.commit()
        utils_geo.invalidate_geo_config_cache()
        self.ctx.pop()

    def _post(self, data):
        from aot.aot_flask import routes_geo_map as r
        view = r.api_geo_settings
        while hasattr(view, '__wrapped__'):
            view = view.__wrapped__
        with self.app.test_request_context('/api/geo/settings',
                                           method='POST', data=data):
            with mock.patch.object(r.utils_general, 'user_has_permission',
                                   return_value=True):
                return view()

    def test_explicit_false_turns_toggles_off(self):
        # 모달이 이제 보내는 모양 — 꺼진 체크박스도 'false' 로 온다.
        self.assertTrue(self._post({f: 'false' for f in BOOL_FIELDS})
                        .get_json()['ok'])
        row = GeoSetting.query.populate_existing().first()
        for f in BOOL_FIELDS:
            self.assertIs(getattr(row, f), False, f)

    def test_absent_key_is_left_alone(self):
        self._post({'digital_zoom': 'false'})
        row = GeoSetting.query.populate_existing().first()
        self.assertIs(row.digital_zoom, False)
        for f in ('smooth_zoom', 'tile_fade_animation', 'prefer_canvas'):
            self.assertIs(getattr(row, f), True, f)


class TestModalSendsEveryToggle(unittest.TestCase):
    def setUp(self):
        self.src = open(MODAL, encoding='utf-8').read()

    def test_checkboxes_are_sent_explicitly(self):
        # serialize 에서 체크박스를 빼고, 이름 있는 체크박스는 전부 true/false 로.
        self.assertIn(".not(':checkbox')", self.src)
        self.assertIn(":checkbox[name]", self.src)
        self.assertIn("(this.checked ? 'true' : 'false')", self.src)
        for f in BOOL_FIELDS:
            self.assertRegex(self.src, r'name="%s" type="checkbox"' % f)

    def test_displayed_defaults_match_model(self):
        # 값이 NULL 일 때 모달이 보이는 값 = GeoSetting 의 column default.
        cols = GeoSetting.__table__.c
        for f in BOOL_FIELDS:
            m = re.search(r"_bool\(state\.%s, (true|false)\)" % f, self.src)
            self.assertIsNotNone(m, f)
            self.assertEqual(m.group(1) == 'true', cols[f].default.arg, f)

    def test_maplibre_unset_shows_local(self):
        # layout.html 은 명시적 false 일 때만 CDN — 미설정은 로컬(켜짐)이다.
        self.assertRegex(
            self.src,
            r"_bool\(state\.providers && "
            r"state\.providers\.maplibre_local_serving, true\)")
        layout = open(os.path.join(ROOT, 'aot', 'aot_flask', 'templates',
                                   'layout.html'), encoding='utf-8').read()
        self.assertIn("get('maplibre_local_serving') == false", layout)


if __name__ == '__main__':
    unittest.main()
