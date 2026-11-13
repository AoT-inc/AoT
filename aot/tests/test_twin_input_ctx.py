# coding=utf-8
"""HTTP 요청 문맥 없이(트윈 서비스·데몬처럼 앱 문맥만 있는 곳) 입력 모듈 정보를 읽는다.

예전에는 로캘 선택기가 `request.accept_languages` 를 읽다 `Working outside of request context` 로 터져
`parse_input_information` 이 실패했고, 그러자 `exclusions` 가 빈 사전을 돌려 관측이 아닌 입력(예보·모델값)이
동기화에 그대로 들어갔다. 다른 시험은 `parse_input_information` 을 가짜로 바꿔 이 경로를 가렸다 — 여기서는
진짜 입력 모듈과 진짜 로캘 선택기(`extension_babel`)를 쓴다.
"""
import unittest

from flask import Flask

from aot.aot_flask.app import extension_babel
from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoMap, GeoShape, Input, Misc
from aot.utils import twin_config as TC


def _ser(uid, unit, ch=0):
    return {'unique_id': uid, 'unit': unit, 'channel': ch, 'provenance': 'unknown'}


class NoRequestContextTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        extension_babel(self.app)                       # 앱이 쓰는 로캘 선택기 그대로
        self.ctx = self.app.app_context()               # 요청 문맥은 없다
        self.ctx.push()
        db.create_all()
        db.session.add(Misc())
        GeoMap(unique_id='m1', name='지도', category='design').save()
        ring = [[126.88, 35.86], [126.88, 35.87], [126.89, 35.87], [126.89, 35.86], [126.88, 35.86]]
        GeoShape(unique_id='site-1', geo_id='m1', type='site', feature={
            'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]},
            'properties': {'name': 'A 포장'}}).save()
        db.session.add(Input(unique_id='wx-model', device='OPEN_METEO_FORECAST', name='격자 날씨'))
        db.session.add(DeviceMeasurements(device_id='wx-model', channel=0, measurement='precipitation',
                                          unit='mm', name='강수'))
        db.session.commit()
        TC._info_cache.update(fn=None, at=0.0, val=None)

    def tearDown(self):
        TC._info_cache.update(fn=None, at=0.0, val=None)
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_locale_outside_a_request_is_the_default_not_an_error(self):
        from flask_babel import get_locale
        self.assertIsNotNone(get_locale())

    def test_locale_inside_a_request_still_follows_accept_language(self):
        from flask_babel import get_locale
        with self.app.test_request_context('/', headers={'Accept-Language': 'ko'}):
            self.assertEqual(str(get_locale()), 'ko')

    def test_input_info_and_channels_read_without_a_request(self):
        info = TC._input_info()
        self.assertEqual(info['OPEN_METEO_FORECAST']['data_origin'], 'model')
        self.assertEqual([c['unique_id'] for c in TC.channels(['wx-model'])], ['wx-model'])

    def test_resolved_overrides_drops_a_model_input_without_a_request(self):
        TC.save('site', 'site-1', True, {'inputs': {'rain': _ser('wx-model', 'mm')}}, set_enabled=True)
        s = TC.resolved_overrides()['sites']['site-1']
        self.assertNotIn('rain', s['inputs'])                   # 모델값은 웹 화면처럼 빠진다
        self.assertEqual(s['excluded']['rain']['reason'], 'model')


if __name__ == '__main__':
    unittest.main()
