# coding=utf-8
"""지도 API 쓰기 경로의 결함 회귀 — 권한·스코프·오류 코드·채널·카메라.

배경(2026-09-27 매뉴얼 조사 중 실측):

1. `/api/geo/device/location` POST, `/api/geo/parcel/save_as_site`,
   `/api/geo/import/gg_parks` 는 `@login_required` 만 있었다. 형제 쓰기
   (`/overlays`·`/binding`·`/designs`·`site_order`)는 `edit_settings` 와 지도
   스코프를 묻는다 — 로그인만 하면 Guest 도 장치 좌표를 옮기고 남의 지도에
   대지를 만들 수 있었다.
2. `restore-original` 의 `abort(400)`(추적 컬럼 없음)이 바깥
   `except Exception` 에 잡혀 500 으로 나갔다.
3. `_binding_args` 가 `device_id` 의 `<uuid>::<channel>` 접미사를 떼기만 하고
   버려, 매뉴얼이 약속한 "접미사가 channel_id 가 된다" 가 거짓이었다.
4. `GET /api/geo/designs` 가 center 를 리스트로만 읽어 `{lat, lng}` 로 저장된
   지도가 전부 서울 기본값으로 나갔다.
"""
import json
import unittest
from unittest import mock

from flask import Flask
from werkzeug.exceptions import HTTPException

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, Input


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


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


def _status(result):
    """view 반환값(응답 객체·튜플·dict) → 상태 코드."""
    if isinstance(result, tuple):
        return result[1]
    code = getattr(result, 'status_code', None)
    return code if code is not None else 200


class _Base(unittest.TestCase):
    MAP = 'gwg-map-1'
    DEV = 'gwg-input-1'

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self._clean()
        db.session.add(GeoMap(unique_id=self.MAP, name='M', category='design'))
        db.session.add(Input(unique_id=self.DEV, name='S1',
                             latitude=1.0, longitude=2.0))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self._clean()
        self.ctx.pop()

    def _clean(self):
        GeoShape.query.filter(GeoShape.geo_id.like('gwg-%')).delete(
            synchronize_session=False)
        GeoMap.query.filter(GeoMap.unique_id.like('gwg-%')).delete(
            synchronize_session=False)
        Input.query.filter(Input.unique_id.like('gwg-%')).delete(
            synchronize_session=False)
        db.session.commit()

    def _perm(self, allowed):
        from aot.aot_flask.utils import utils_general
        return mock.patch.object(utils_general, 'user_has_permission',
                                 return_value=allowed)


# --------------------------------------------------------------- 1. /device/location

class TestDeviceLocationGate(_Base):
    def _post(self, body):
        from aot.aot_flask.api.geo import GeoDeviceLocation
        view = _unwrap(GeoDeviceLocation.post)
        with self.app.test_request_context(
                '/api/geo/device/location', method='POST', json=body):
            return view(GeoDeviceLocation())

    def _lat(self):
        return Input.query.populate_existing().filter_by(
            unique_id=self.DEV).first().latitude

    def test_without_edit_settings_is_403_and_nothing_moves(self):
        with self._perm(False):
            with self.assertRaises(HTTPException) as cm:
                self._post({'unique_id': self.DEV, 'type': 'input',
                            'lat': 9.0, 'lng': 9.0})
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self._lat(), 1.0)

    def test_device_outside_scope_is_403_and_nothing_moves(self):
        from aot.aot_flask.access import scope
        with self._perm(True), \
                mock.patch.object(scope, 'can_operate_device',
                                  return_value=False) as dev_gate:
            result = self._post({'unique_id': self.DEV, 'type': 'input',
                                 'lat': 9.0, 'lng': 9.0})
        self.assertEqual(_status(result), 403)
        dev_gate.assert_called_with(self.DEV)
        self.assertEqual(self._lat(), 1.0)

    def test_map_outside_scope_is_403_and_no_marker(self):
        from aot.aot_flask.access import scope
        with self._perm(True), \
                mock.patch.object(scope, 'can_operate_device',
                                  return_value=True), \
                mock.patch.object(scope, 'can_operate',
                                  return_value=False) as map_gate, \
                mock.patch('aot.aot_flask.geo.device_placement.place_device'
                           ) as place:
            result = self._post({'unique_id': self.DEV, 'type': 'input',
                                 'lat': 9.0, 'lng': 9.0,
                                 'map_uuid': self.MAP})
        self.assertEqual(_status(result), 403)
        map_gate.assert_called_with('geo_map', self.MAP)
        place.assert_not_called()
        self.assertEqual(self._lat(), 1.0)

    def test_allowed_saves(self):
        from aot.aot_flask.access import scope
        with self._perm(True), \
                mock.patch.object(scope, 'can_operate_device',
                                  return_value=True), \
                mock.patch('aot.aot_client.DaemonControl'):
            result = self._post({'unique_id': self.DEV, 'type': 'input',
                                 'lat': 9.0, 'lng': 8.0})
        self.assertEqual(_status(result), 200)
        self.assertTrue(result['ok'])
        self.assertEqual(self._lat(), 9.0)


# --------------------------------------------------------------- 1. parcel / gg_parks

_SQUARE = {'type': 'Feature', 'properties': {},
           'geometry': {'type': 'Polygon',
                        'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]}}


class TestParcelSaveAsSiteGate(_Base):
    def _post(self, body):
        from aot.aot_flask import routes_geo_map as r
        view = _unwrap(r.api_geo_parcel_save_as_site)
        with self.app.test_request_context(
                '/api/geo/parcel/save_as_site', method='POST', json=body):
            return view()

    def _sites(self):
        return GeoShape.query.filter_by(geo_id=self.MAP).count()

    def test_without_edit_settings_is_403(self):
        with self._perm(False):
            result = self._post({'feature': json.loads(json.dumps(_SQUARE)),
                                 'name': 'P', 'map_uuid': self.MAP})
        self.assertEqual(_status(result), 403)
        self.assertEqual(self._sites(), 0)

    def test_map_outside_scope_is_403(self):
        from aot.aot_flask import routes_geo_map as r
        with self._perm(True), \
                mock.patch.object(r.scope, 'can_operate',
                                  return_value=False) as gate:
            result = self._post({'feature': json.loads(json.dumps(_SQUARE)),
                                 'name': 'P', 'map_uuid': self.MAP})
        self.assertEqual(_status(result), 403)
        gate.assert_called_with('geo_map', self.MAP)
        self.assertEqual(self._sites(), 0)

    def test_allowed_creates_site(self):
        with self._perm(True):
            result = self._post({'feature': json.loads(json.dumps(_SQUARE)),
                                 'name': 'P', 'map_uuid': self.MAP})
        self.assertEqual(_status(result), 200)
        self.assertEqual(
            GeoShape.query.filter_by(geo_id=self.MAP, type='site').count(), 1)


class TestGgParksImportGate(_Base):
    def _post(self, body):
        from aot.aot_flask import routes_geo_map as r
        view = _unwrap(r.api_geo_import_gg_parks)
        with self.app.test_request_context(
                '/api/geo/import/gg_parks', method='POST', json=body):
            return view()

    def _importer(self):
        return mock.patch(
            'aot.aot_flask.geo.importers.gg_public_park_importer.'
            'GgPublicParkImporter')

    def test_without_edit_settings_is_403(self):
        with self._perm(False), self._importer() as imp:
            result = self._post({'map_uuid': self.MAP})
        self.assertEqual(_status(result), 403)
        imp.assert_not_called()

    def test_map_outside_scope_is_403(self):
        from aot.aot_flask import routes_geo_map as r
        with self._perm(True), self._importer() as imp, \
                mock.patch.object(r.scope, 'can_operate',
                                  return_value=False) as gate:
            result = self._post({'map_uuid': self.MAP})
        self.assertEqual(_status(result), 403)
        gate.assert_called_with('geo_map', self.MAP)
        imp.assert_not_called()


# --------------------------------------------------------------- 2. restore-original

class TestRestoreOriginalKeeps400(_Base):
    def test_missing_tracking_columns_is_400_not_500(self):
        from aot.aot_flask.api.geo import GeoMapRestoreOriginal
        from aot.aot_flask.access import scope
        view = _unwrap(GeoMapRestoreOriginal.post)
        with self.app.test_request_context(
                '/api/geo/maps/%s/restore-original' % self.MAP,
                method='POST'):
            with self._perm(True), \
                    mock.patch.object(scope, 'can_operate',
                                      return_value=True), \
                    mock.patch.object(db.session, 'execute',
                                      side_effect=Exception('no column')):
                with self.assertRaises(HTTPException) as cm:
                    view(GeoMapRestoreOriginal(), self.MAP)
        self.assertEqual(cm.exception.code, 400)


# --------------------------------------------------------------- 3. binding channel

class TestBindingArgsChannelSuffix(unittest.TestCase):
    def _args(self, data):
        from aot.aot_flask.api import geo as api_geo
        from aot.aot_flask.geo import device_binding
        app = Flask(__name__)
        with app.app_context(), \
                mock.patch.object(device_binding, 'resolve_device_kind',
                                  return_value='input'):
            return api_geo._binding_args(dict(
                {'spatial_kind': 'sensor_role', 'spatial_id': 'x',
                 'role': 'sensor'}, **data))

    def test_suffix_becomes_channel(self):
        a = self._args({'device_id': 'dev-1::3'})
        self.assertEqual(a['device_id'], 'dev-1')
        self.assertEqual(a['channel_id'], '3')

    def test_explicit_channel_wins_over_suffix(self):
        a = self._args({'device_id': 'dev-1::3', 'channel_id': '5'})
        self.assertEqual(a['device_id'], 'dev-1')
        self.assertEqual(a['channel_id'], '5')

    def test_no_suffix_defaults_to_zero(self):
        a = self._args({'device_id': 'dev-1'})
        self.assertEqual(a['channel_id'], '0')


# --------------------------------------------------------------- 4. designs center

class TestDesignsListCenter(_Base):
    def test_dict_and_list_centres_are_both_read(self):
        from aot.aot_flask.api.geo import GeoDesigns
        m = GeoMap.query.filter_by(unique_id=self.MAP).first()
        m.state_json = json.dumps({'center': {'lat': 35.85, 'lng': 126.86},
                                   'zoom': 16})
        db.session.add(GeoMap(unique_id='gwg-map-2', name='L',
                              category='design',
                              state_json=json.dumps(
                                  {'center': [36.1, 127.2], 'zoom': 14})))
        db.session.commit()
        view = _unwrap(GeoDesigns.get)
        with self.app.test_request_context('/api/geo/designs'):
            rows = {r['unique_id']: r for r in view(GeoDesigns())}
        self.assertEqual((rows[self.MAP]['latitude'],
                          rows[self.MAP]['longitude'],
                          rows[self.MAP]['zoom']), (35.85, 126.86, 16))
        self.assertEqual((rows['gwg-map-2']['latitude'],
                          rows['gwg-map-2']['longitude']), (36.1, 127.2))


if __name__ == '__main__':
    unittest.main()
