# coding=utf-8
"""`POST /api/consult/parcel`(상담용 읽기 전용 필지 조회)의 계약.

고정하는 것:

1. 응답 모양 — 성공 `{ok, feature, pnu, area_m2, centroid:[lon,lat], address_normalized}`,
   실패 `{ok:false, error:<invalid_address|not_found|vworld_unavailable>}`.
2. 입력 검증과 오류 코드 구분(못 찾음 ≠ VWorld 장애).
3. 인증(없으면 401)·권한(view_settings)·**읽기 전용 키도 열린다**(`_READONLY_POST_PATHS`),
   그 밖의 POST 는 읽기 전용 키에서 여전히 막힌다.
4. **CSRF 토큰 없이 API 키로 POST 가 통과한다**(CSRF 를 켠 앱에서). 같은 앱의 면제 밖 POST 는
   막힌다 — 시험이 CSRF 를 실제로 켜 두었다는 대조군.
5. **DB 에 아무것도 쓰지 않는다** — 실행 전후 행 수, 세션 flush 훅, 핸들러 정적 검사.
   이 전제가 CSRF 면제와 읽기 전용 키 예외의 유일한 근거다(`test_data_batch_readonly.py` 와 같은 구조).

외부 API 는 부르지 않는다 — `requests.get` 을 URL 별 가짜로 바꾼다. 임시 sqlite 만 쓴다.
"""
import ast
import base64
import json
import os
import tempfile
import unittest
from unittest import mock

import requests

from aot.aot_flask.api import consult

_CONSULT_SRC = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'api', 'consult.py')
_APP_SRC = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'app.py')
_API_INIT_SRC = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'api', '__init__.py')

PATH = '/api/consult/parcel'
HDR = {'Accept': 'application/vnd.aot.v1+json'}

# 서울 근처 0.001° x 0.001° 정사각형 필지(좌표 닫힘). 위도 37.5 에서 약 88 m x 111 m.
_LNG0, _LAT0, _D = 126.9, 37.5, 0.001
RING = [[_LNG0, _LAT0], [_LNG0 + _D, _LAT0], [_LNG0 + _D, _LAT0 + _D], [_LNG0, _LAT0 + _D], [_LNG0, _LAT0]]
PNU = '1168010100008080000'


class _Resp(object):
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError('not json')
        return self._payload


class FakeVWorld(object):
    """`requests.get` 대체 — URL 로 단계를 가려 VWorld 응답 모양을 흉내 낸다. 호출 수를 센다."""

    def __init__(self, mode='ok'):
        self.mode, self.calls = mode, []

    def __call__(self, url, params=None, **kw):
        self.calls.append(url)
        if self.mode == 'down':
            raise requests.ConnectionError('boom')
        if self.mode == 'html':                     # 점검 페이지 같은 JSON 아닌 응답
            return _Resp('<html>maintenance</html>', 503)
        if self.mode == 'error_status':             # 키·도메인 오류
            return _Resp({'response': {'status': 'ERROR', 'error': {'code': 'INVALID_KEY'}}})
        if self.mode == 'not_found':
            return _Resp({'response': {'status': 'NOT_FOUND'}})
        if self.mode in ('polygon_down', 'polygon_empty') and not ('/req/address' in url and 'getcoord' in url):
            # 지오코딩은 정상, 그 뒤(역지오코딩·Data API)만: 전부 죽음 / 정상이지만 필지 없음
            if self.mode == 'polygon_down':
                raise requests.Timeout('slow')
            return _Resp({'response': {'status': 'NOT_FOUND'}})
        if '/req/address' in url and 'getcoord' in url:
            return _Resp({'response': {'status': 'OK', 'result': {'point': {'x': str(_LNG0), 'y': str(_LAT0)}}}})
        if '/req/address' in url and 'getAddress' in url:
            return _Resp({'response': {'status': 'OK', 'result': [{
                'text': '서울특별시 강남구 역삼동 808',
                'structure': {'level4LC': '1168010100', 'detail': '808'}}]}})
        if '/req/data' in url:
            return _Resp({'response': {'status': 'OK', 'result': {'featureCollection': {'features': [{
                'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [RING]},
                'properties': {'addr': '서울특별시 강남구 역삼동 808', 'pnu': PNU}}]}}}})
        return _Resp({'response': {'status': 'NOT_FOUND'}})


_STATE = {}


def _build(rate_limit=None):
    """CSRF 를 켠 앱 + 상담 네임스페이스 + 스코프 가드. 전역 api_blueprint 는 등록하지 않는다
    (다른 시험의 네임스페이스와 충돌 — test_twin_read_api.py 와 같은 이유)."""
    from flask import Blueprint, Flask
    from flask_babel import Babel
    from flask_restx import Api

    import aot.databases.models  # noqa: F401 — 모델 등록
    from aot.aot_flask.api import api as global_api
    from aot.aot_flask.app import (extension_limiter, extension_login_manager,
                                   register_api_key_scope_guard)
    from aot.aot_flask.api.measurement import ns_measurement      # 다른 POST 경로(가드 확인용)
    from aot.aot_flask.extensions import csrf, db
    from aot.databases.models import GeoLayer, Misc, Role, User

    tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(tmp.name, 't.db'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='x', TESTING=True)
    # WTF_CSRF_ENABLED 를 건드리지 않는다 — 기본값 True. 이 시험의 요점이다.
    db.init_app(app)
    csrf.init_app(app)
    bp = Blueprint('api_consult_test', __name__, url_prefix='/api')
    api = Api(bp, default_mediatype='application/vnd.aot.v1+json')
    for media, fn in global_api.representations.items():
        api.representations[media] = fn
    api.add_namespace(consult.ns_consult)
    api.add_namespace(ns_measurement)
    csrf.exempt(bp)                                  # 실제 앱은 extension_csrf 가 api_blueprint 를 면제한다

    @app.route('/protected', methods=['POST'])       # 면제 밖 대조군
    def protected():
        return 'ok'

    Babel(app)
    app.register_blueprint(bp)
    register_api_key_scope_guard(app)
    extension_login_manager(app)                 # 실제 키 로더·401 처리기
    if rate_limit:
        # 실제 extension_limiter — 상담 경로의 키 함수·한도·429 처리기가 여기서 배선된다.
        with mock.patch.dict(os.environ, {consult.PARCEL_RATE_LIMIT_ENV: rate_limit}):
            extension_limiter(app)

    keys = {}
    with app.app_context():
        db.create_all()
        db.session.add(Misc())
        admin = Role(name='Admin', edit_settings=True, view_settings=True)
        nobody = Role(name='Nobody', view_settings=False)
        db.session.add_all([admin, nobody])
        db.session.commit()
        for name, role, scope in (('full', admin, 'full'), ('full2', admin, 'full'), ('ro', admin, 'readonly'),
                                  ('noperm', nobody, 'full')):
            u = User(name='u_' + name, email=name + '@example.com', role_id=role.id)
            u.set_password('correct horse battery staple')
            db.session.add(u)
            db.session.flush()
            keys[name] = base64.b64encode(u.issue_api_key(name, scope)).decode()
        db.session.add(GeoLayer(name='vworld', type='gis_vworld', is_activated=True,
                                options=json.dumps({'api_key': 'TEST-KEY', 'vworld_domain': 'example.test'})))
        db.session.commit()
    return dict(app=app, tmp=tmp, keys=keys, client=app.test_client())


def setUpModule():
    _STATE.update(_build())


def tearDownModule():
    _STATE['tmp'].cleanup()


def _row_counts():
    from sqlalchemy import text
    from aot.aot_flask.extensions import db
    with _STATE['app'].app_context():
        names = [r[0] for r in db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
        return {n: db.session.execute(text('SELECT COUNT(*) FROM "{}"'.format(n))).scalar() for n in names}


class ConsultParcelApiTest(unittest.TestCase):

    def setUp(self):
        self.client = _STATE['client']
        self.keys = _STATE['keys']

    def post(self, body, key='full', raw=None):
        headers = dict(HDR)
        if key:
            headers['X-API-KEY'] = self.keys[key]
        if raw is not None:
            return self.client.post(PATH, data=raw, headers=headers, content_type='application/json')
        return self.client.post(PATH, json=body, headers=headers)

    # --- 성공 ----------------------------------------------------------------------------------

    def test_success_shape(self):
        fake = FakeVWorld()
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            r = self.post({'address': '  서울특별시   강남구 역삼동 808 '})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual(set(body), {'ok', 'feature', 'pnu', 'area_m2', 'centroid', 'address_normalized'})
        self.assertIs(body['ok'], True)
        self.assertEqual(body['pnu'], PNU)
        self.assertEqual(body['address_normalized'], '서울특별시 강남구 역삼동 808')
        self.assertEqual(body['feature']['type'], 'Feature')
        self.assertEqual(body['feature']['geometry'], {'type': 'Polygon', 'coordinates': [RING]})
        # 위도 37.5 에서 0.001° x 0.001° ≈ 87.9 m x 111.3 m
        self.assertAlmostEqual(body['area_m2'], 0.001 * 111320 * 0.001 * 111320 * 0.79335, delta=30)
        lon, lat = body['centroid']
        self.assertAlmostEqual(lon, _LNG0 + _D / 2, places=6)
        self.assertAlmostEqual(lat, _LAT0 + _D / 2, places=6)
        # 주소는 공백이 정리돼 VWorld 에 나간다(키는 서버가 등록된 입력에서 읽는다 — 요청에 없다)
        self.assertTrue(any('TEST-KEY' in u for u in fake.calls))
        self.assertNotIn('TEST-KEY', r.get_data(as_text=True))

    # --- 오류 코드 -----------------------------------------------------------------------------

    def test_not_found(self):
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld('not_found')):
            r = self.post({'address': '없는 주소 99999'})
        self.assertEqual((r.status_code, r.get_json()), (404, {'ok': False, 'error': 'not_found'}))

    def test_vworld_down_is_unavailable_not_not_found(self):
        for mode in ('down', 'html', 'error_status'):
            with self.subTest(mode=mode), mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld(mode)):
                r = self.post({'address': '서울특별시 강남구 역삼동 808'})
                self.assertEqual((r.status_code, r.get_json()), (503, {'ok': False, 'error': 'vworld_unavailable'}))

    def test_partial_failure_with_a_real_answer_is_not_found(self):
        """일부 호출만 실패하고 VWorld 가 한 번이라도 '없음' 이라 답했으면 장애가 아니라 못 찾음."""
        base = FakeVWorld('not_found')

        def flaky(url, params=None, **kw):
            if 'getcoord' in url and 'type=PARCEL' in url:
                return base(url, params, **kw)
            raise requests.Timeout('slow')
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', flaky):
            r = self.post({'address': '어딘가 1'})
        self.assertEqual((r.status_code, r.get_json()['error']), (404, 'not_found'))

    def test_vworld_key_missing_is_unavailable(self):
        fake = FakeVWorld()
        with mock.patch('aot.aot_flask.routes_geo_map._get_vworld_credentials', return_value=('', '')), \
                mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertEqual((r.status_code, r.get_json()), (503, {'ok': False, 'error': 'vworld_unavailable'}))
        self.assertEqual(fake.calls, [])

    def test_polygon_stage_all_failed_is_unavailable(self):
        """지오코딩은 됐는데 그 뒤 호출이 전부 실패하면 못 찾음이 아니라 장애."""
        fake = FakeVWorld('polygon_down')
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertEqual((r.status_code, r.get_json()), (503, {'ok': False, 'error': 'vworld_unavailable'}))
        self.assertGreater(len(fake.calls), 1)

    def test_polygon_stage_answered_empty_is_not_found(self):
        """같은 지점에서 VWorld 가 정상적으로 '없음' 이라 답하면 장애가 아니다."""
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld('polygon_empty')):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertEqual((r.status_code, r.get_json()), (404, {'ok': False, 'error': 'not_found'}))

    def test_logs_never_carry_the_vworld_key(self):
        """requests 예외 메시지에는 key= 가 든 URL 이 실린다 — 로그에는 예외 종류만 남는다."""
        leak = requests.ConnectionError('HTTPSConnectionPool: /req/address?key=TEST-KEY&domain=example.test')
        with self.assertLogs('aot.aot_flask.api.consult', level='DEBUG') as logs, \
                mock.patch('aot.inputs_gis.gis_vworld.InputModule.parcel_from_address', side_effect=leak):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertEqual((r.status_code, r.get_json()['error']), (503, 'vworld_unavailable'))
        text = '\n'.join(logs.output)
        self.assertIn('ConnectionError', text)
        self.assertNotIn('TEST-KEY', text)
        self.assertNotIn('Traceback', text)
        with self.assertLogs('aot.aot_flask.api.consult', level='DEBUG') as logs, \
                mock.patch('aot.aot_flask.routes_geo_map._get_vworld_credentials', side_effect=leak):
            self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertNotIn('TEST-KEY', '\n'.join(logs.output))

    def test_invalid_address(self):
        fake = FakeVWorld()
        cases = [{}, {'address': ''}, {'address': '   '}, {'address': 'a'}, {'address': 123},
                 {'address': None}, {'address': ['서울']}, {'address': 'x' * (consult.ADDRESS_MAX_LEN + 1)},
                 {'address': '서울\x00시'}, {'address': '서울\n시 강남'}, ['서울'], 'str']
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            for body in cases:
                with self.subTest(body=repr(body)[:40]):
                    r = self.post(body)
                    self.assertEqual((r.status_code, r.get_json()), (400, {'ok': False, 'error': 'invalid_address'}))
            r = self.post(None, raw='{not json')
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.get_json()['error'], 'invalid_address')
        self.assertEqual(fake.calls, [], '잘못된 입력은 외부 호출 전에 거절한다')

    def test_address_length_boundary(self):
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld()):
            self.assertEqual(self.post({'address': '가' * consult.ADDRESS_MAX_LEN}).status_code, 200)
            self.assertEqual(self.post({'address': '가' * (consult.ADDRESS_MAX_LEN + 1)}).status_code, 400)

    # --- 인증·권한·키 범위 ---------------------------------------------------------------------

    def test_no_credentials_is_401(self):
        fake = FakeVWorld()
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'}, key=None)
        self.assertEqual((r.status_code, r.get_json()), (401, {'ok': False, 'error': 'unauthorized'}))
        self.assertEqual(fake.calls, [])

    def test_wrong_key_is_401(self):
        r = self.client.post(PATH, json={'address': '서울 강남'}, headers=dict(HDR, **{'X-API-KEY': 'AAAA'}))
        self.assertEqual((r.status_code, r.get_json()), (401, {'ok': False, 'error': 'unauthorized'}))

    def test_role_without_view_settings_is_403(self):
        fake = FakeVWorld()
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', fake):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'}, key='noperm')
        self.assertEqual((r.status_code, r.get_json()), (403, {'ok': False, 'error': 'forbidden'}))
        self.assertEqual(fake.calls, [])

    def test_readonly_key_is_allowed(self):
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld()):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'}, key='ro')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()['ok'])

    def test_readonly_key_is_still_blocked_elsewhere(self):
        """예외가 이 경로 하나에만 열렸다는 대조군."""
        r = self.client.post('/api/measurements/create/x/C/0/1.0', json={},
                             headers=dict(HDR, **{'X-API-KEY': self.keys['ro']}))
        self.assertEqual(r.status_code, 403)
        self.assertIn('read-only', r.get_data(as_text=True))
        r = self.client.post(PATH + '/extra', json={}, headers=dict(HDR, **{'X-API-KEY': self.keys['ro']}))
        self.assertEqual(r.status_code, 403)

    # --- CSRF ----------------------------------------------------------------------------------

    def test_csrf_is_on_and_the_api_key_post_passes_without_a_token(self):
        # 대조군: 같은 앱에서 면제 밖 POST 는 토큰이 없어 막힌다 → CSRF 가 실제로 켜져 있다.
        control = self.client.post('/protected', headers={'X-API-KEY': self.keys['full']})
        self.assertEqual(control.status_code, 400)
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld()):
            r = self.post({'address': '서울특별시 강남구 역삼동 808'})
        self.assertEqual(r.status_code, 200)

    # --- 쓰기 없음 -----------------------------------------------------------------------------

    def test_no_db_writes(self):
        from aot.aot_flask.extensions import db
        from sqlalchemy import event
        flushed = []

        def _spy(session, ctx, instances):
            flushed.append((list(session.new), list(session.dirty), list(session.deleted)))
        before = _row_counts()
        with _STATE['app'].app_context():
            event.listen(db.session, 'before_flush', _spy)
        try:
            for mode in ('ok', 'not_found', 'down'):
                with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld(mode)):
                    self.post({'address': '서울특별시 강남구 역삼동 808'})
            self.post({'address': ''})
        finally:
            with _STATE['app'].app_context():
                event.remove(db.session, 'before_flush', _spy)
        self.assertEqual(_row_counts(), before)
        self.assertEqual(flushed, [])


class ConsultParcelRateLimitTest(unittest.TestCase):
    """실제 `extension_limiter` 로 만든 앱 — 키 함수·한도·429 처리기가 배선된 그대로를 본다."""

    @classmethod
    def setUpClass(cls):
        cls.state = _build(rate_limit='2/minute')

    @classmethod
    def tearDownClass(cls):
        cls.state['tmp'].cleanup()

    def _call(self, key_name):
        hdr = dict(HDR, **{'X-API-KEY': self.state['keys'][key_name]})
        with mock.patch('aot.inputs_gis.gis_vworld.requests.get', FakeVWorld()):
            return self.state['app'].test_client().post(PATH, json={'address': '서울 강남 808'}, headers=hdr)

    def test_limit_is_counted_per_api_key_and_returns_the_error_shape(self):
        codes = [self._call('full').status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])
        r = self._call('full')
        self.assertEqual(r.status_code, 429)
        body = r.get_json()
        self.assertEqual((body['ok'], body['error']), (False, 'rate_limited'))
        # 같은 IP(테스트 클라이언트)·같은 사용자 계정 군이어도 다른 키는 자기 몫을 따로 쓴다.
        self.assertEqual([self._call('full2').status_code for _ in range(3)], [200, 200, 429])
        # 읽기 전용 키도 키 ID 로 따로 센다.
        self.assertEqual(self._call('ro').status_code, 200)

    def test_rate_limit_key_is_the_key_id_not_the_secret(self):
        from flask import Flask
        from aot.databases.models.user_api_key import UserAPIKey
        app = self.state['app']
        with app.test_request_context(PATH, method='POST',
                                      headers={'X-API-KEY': self.state['keys']['full']}):
            key = consult.rate_limit_key()
            row = UserAPIKey.query.filter_by(name='full').one()
            self.assertEqual(key, 'consult-apikey:{}'.format(row.unique_id))
            self.assertNotIn(self.state['keys']['full'], key)
        with app.test_request_context(PATH, method='POST', environ_base={'REMOTE_ADDR': '10.1.2.3'}):
            self.assertTrue(consult.rate_limit_key().startswith('consult-'))

    def test_limit_value_is_configurable_with_a_safe_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(consult.PARCEL_RATE_LIMIT_ENV, None)
            self.assertEqual(consult.parcel_rate_limit(), '30/minute')
        with mock.patch.dict(os.environ, {consult.PARCEL_RATE_LIMIT_ENV: '120/minute'}):
            self.assertEqual(consult.parcel_rate_limit(), '120/minute')
        with mock.patch.dict(os.environ, {consult.PARCEL_RATE_LIMIT_ENV: 'lots'}):
            self.assertEqual(consult.parcel_rate_limit(), '30/minute')


class HelpersTest(unittest.TestCase):

    def test_normalize_address(self):
        self.assertEqual(consult.normalize_address('  서울  강남   808 '), '서울 강남 808')
        for bad in (None, 5, '', ' ', 'a', '서울\x01', 'x' * 201):
            self.assertIsNone(consult.normalize_address(bad))

    def test_centroid_of_l_shape_is_area_weighted(self):
        # L 자: 아래 2x1 + 위 1x1 (단위 0.001°). 단순 평균(꼭짓점)이 아니라 면적 가중이어야 한다.
        d = 0.001
        ring = [[0, 37], [2 * d, 37], [2 * d, 37 + d], [d, 37 + d], [d, 37 + 2 * d], [0, 37 + 2 * d], [0, 37]]
        lon, lat = consult.centroid_lonlat({'type': 'Polygon', 'coordinates': [ring]})
        # 아래 2x1 의 무게중심 (1.0, 0.5), 위 1x1 의 무게중심 (0.5, 1.5) → 면적 가중 (2.5/3, 2.5/3)
        self.assertAlmostEqual(lon / d, 2.5 / 3, places=3)
        self.assertAlmostEqual((lat - 37) / d, 2.5 / 3, places=3)

    def test_centroid_and_area_for_multipolygon_and_garbage(self):
        d = 0.001
        sq = lambda x0: [[x0, 37], [x0 + d, 37], [x0 + d, 37 + d], [x0, 37 + d], [x0, 37]]  # noqa: E731
        lon, lat = consult.centroid_lonlat({'type': 'MultiPolygon', 'coordinates': [[sq(0)], [sq(2 * d)]]})
        self.assertAlmostEqual(lon, 1.5 * d, places=7)
        for bad in (None, {}, {'type': 'Point', 'coordinates': [1, 2]}, {'type': 'Polygon', 'coordinates': []}):
            self.assertIsNone(consult.centroid_lonlat(bad))


class ReadOnlyWiringTest(unittest.TestCase):
    """쓰기 없음과 면제·예외 배선을 정적으로 고정한다(`test_data_batch_readonly.py` 방식)."""

    _WRITE_CALLS = ('commit', 'add', 'add_all', 'delete', 'merge', 'flush', 'execute', 'save', 'bulk_save_objects',
                    'update', 'rollback', 'bulk_insert_mappings', 'bulk_update_mappings')

    def test_handler_functions_do_not_write(self):
        with open(os.path.abspath(_CONSULT_SRC), encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        names = {f.name for f in funcs}
        self.assertTrue({'post', 'lookup_parcel', 'centroid_lonlat', 'normalize_address'} <= names)
        hits = ["{}:{} → .{}()".format(f.name, s.lineno, s.func.attr)
                for f in funcs for s in ast.walk(f)
                if isinstance(s, ast.Call) and isinstance(s.func, ast.Attribute) and s.func.attr in self._WRITE_CALLS]
        self.assertFalse(hits, "/api/consult/parcel 이 상태를 바꾸고 있습니다: {}\n"
                               "이 경로의 읽기 전용 키 예외(app._READONLY_POST_PATHS)는 '아무것도 쓰지 않는다' 를 "
                               "근거로 합니다. 쓰기가 필요하면 예외를 먼저 걷어내십시오.".format(hits))

    def test_module_does_not_touch_the_db(self):
        with open(os.path.abspath(_CONSULT_SRC), encoding='utf-8') as fh:
            src = fh.read()
        for banned in ('db.session', 'from aot.aot_flask.extensions import db', '.query.'):
            self.assertNotIn(banned, src)

    def test_scope_guard_allows_the_path(self):
        from aot.aot_flask.app import _READONLY_POST_PATHS
        self.assertIn(PATH, _READONLY_POST_PATHS)

    def test_route_lives_under_the_csrf_exempt_api_blueprint(self):
        from aot.aot_flask.api import api, api_blueprint
        self.assertIs(api.blueprint, api_blueprint)
        self.assertIs(consult.ns_consult.apis[0], api)
        with open(os.path.abspath(_APP_SRC), encoding='utf-8') as fh:
            app_src = fh.read()
        self.assertIn('csrf.exempt(api_blueprint)', app_src)
        self.assertIn('limit_consult_parcel(limiter, app)', app_src)   # 실제 배선은 RateLimitTest 가 실행으로 확인
        with open(os.path.abspath(_API_INIT_SRC), encoding='utf-8') as fh:
            self.assertIn('import aot.aot_flask.api.consult', fh.read())

    def test_route_url_is_the_documented_one(self):
        self.assertEqual([url for _, urls, *_ in consult.ns_consult.resources for url in urls], ['/parcel'])
        self.assertEqual(consult.ns_consult.path, '/consult')


if __name__ == '__main__':
    unittest.main()
