# coding=utf-8
"""forecast_series.read() 와 GET /api/twin/forecast_series — 트윈·화면·AI 가 같은 모양으로 읽는 예보 시계열."""
import base64
import os
import tempfile
import unittest
from unittest import mock

from flask import Flask

from aot.space import forecast_series as fs

H = 3600.0
T0 = 1_800_000_000.0 - (1_800_000_000.0 % H)
API = 'application/vnd.aot.v1+json'


def _series(n=5, rain=None, anchor=T0, fetched=None):
    rows = []
    for i in range(n):
        ep = anchor + i * H
        rows.append((ep, {'epoch': ep, 'TMP': 20.0 + i, 'REH': 80, 'WSD': 2.0, 'VEC': 350, 'RN1': (rain or {}).get(i, 0.0),
                          'POP': 50 + i, 'CLD': 100, 'SOL': 10.0 * i}))
    return {'rows': rows, 'input_id': 'in-1', 'source': 'OM hourly', 'model': 'open_meteo',
            'fetched_epoch': fetched if fetched is not None else anchor + 600.0,
            'meta': {'grid_latitude': 32.75, 'grid_longitude': 130.69, 'elevation': 4.0}}


def patched(series, daily=None, fallback=None):
    """대지 예보 계열의 재료를 바꿔 끼운다 — 지정 목록·시간열 파일·일별 사다리·폴백 레이어. 계열 캐시는 비운다."""
    import contextlib
    fs.clear_cache()
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(fs, 'designated_ids', return_value=['in-1'] if (series or daily) else []))
    stack.enter_context(mock.patch.object(fs, '_load', return_value=(series, None if series else 'stale_or_missing')))
    stack.enter_context(mock.patch.object(fs, '_load_daily', return_value=daily))
    stack.enter_context(mock.patch.object(fs, '_site_tz_name', return_value='UTC'))
    stack.enter_context(mock.patch.object(fs, '_site_point', return_value=(32.7, 130.7)))
    stack.enter_context(mock.patch.object(fs, '_fallback_cells', return_value=fallback or (None, None, None)))
    stack.callback(fs.clear_cache)
    return stack


class TestSeriesCache(unittest.TestCase):
    """계열 캐시 10분 — 페이지를 열 때마다 일별 사다리가 Influx 를 40번 읽던 비용(0.7~1.1초)을 없앤다."""

    def test_ttl_is_ten_minutes(self):
        self.assertEqual(fs.SERIES_TTL_S, 600.0)

    def test_second_call_inside_the_window_does_not_reload(self):
        with patched(_series()):
            fs.site_series('site-1', T0 + 10, fallback=False)
            fs.site_series('site-1', T0 + 599, fallback=False)            # 같은 10분 칸
            self.assertEqual(fs._load.call_count, 1)
            fs.site_series('site-1', T0 + 601, fallback=False)            # 다음 10분 칸
            self.assertEqual(fs._load.call_count, 2)

    def test_clear_cache_forces_a_reload(self):
        with patched(_series()):
            fs.site_series('site-1', T0 + 10, fallback=False)
            fs.clear_cache()                                            # 예보 출처 지정이 바뀔 때
            fs.site_series('site-1', T0 + 20, fallback=False)
            self.assertEqual(fs._load.call_count, 2)


class TestPrewarm(unittest.TestCase):
    """서버 시작·10분마다 지정 대지의 계열을 미리 만들어 첫 페이지 로드가 계산을 기다리지 않게 한다."""

    def test_designated_series_is_shared_across_coordinates_and_fallback(self):
        with patched(_series()):
            fs.site_series('site-1', T0 + 10, fallback=False)             # 미리 채움(좌표 없음)
            fs.site_series('site-1', T0 + 20, 35.8, 126.9)                # 지도(좌표 있음, 폴백 기본)
            fs.site_series('site-1', T0 + 30, 35.9, 126.7, fallback=False)
            self.assertEqual(fs._load.call_count, 1)

    def test_undesignated_site_is_not_aliased(self):
        with patched(None, fallback=([{'time': T0, 'end': T0 + H}], {'name': 'layer'}, H)):
            fs.designated_ids.return_value = []
            a = fs.site_series('site-1', T0 + 10, 35.8, 126.9)
            b = fs.site_series('site-1', T0 + 20, 36.5, 127.5)
            self.assertIsNot(a, b)                                        # 폴백 계열은 좌표마다 다르다

    def test_prewarm_builds_every_designated_site_and_survives_a_failure(self):
        rows = [('site-a',), ('site-b',), ('site-c',)]
        q = mock.MagicMock()
        q.query.with_entities.return_value.filter.return_value.distinct.return_value.all.return_value = rows
        calls = []

        def fake(site, now, **kw):
            calls.append((site, kw.get('fallback')))
            if site == 'site-b':
                raise RuntimeError('boom')
        with mock.patch('aot.databases.models.GeoBinding', q), mock.patch.object(fs, 'site_series', side_effect=fake):
            n = fs.prewarm(now=T0)
        self.assertEqual(n, 2)
        self.assertEqual([c[0] for c in calls], ['site-a', 'site-b', 'site-c'])
        self.assertTrue(all(c[1] is False for c in calls))


class TestPrewarmWindow(unittest.TestCase):
    def test_works_once_per_cache_window(self):
        app = mock.MagicMock()
        fs._PREWARMED_BUCKET = None
        with mock.patch.object(fs, 'prewarm', return_value=2) as pw:
            self.assertEqual(fs.prewarm_if_new_window(app, now=T0 + 10), 2)
            self.assertIsNone(fs.prewarm_if_new_window(app, now=T0 + 599))      # 같은 10분 칸 — 건너뜀
            self.assertEqual(fs.prewarm_if_new_window(app, now=T0 + 601), 2)    # 다음 칸
            self.assertEqual(pw.call_count, 2)
        fs._PREWARMED_BUCKET = None


class TestRead(unittest.TestCase):
    def _read(self, series, *a, **k):
        with patched(series):
            return fs.read('site-1', *a, **k)

    def test_cells_start_at_the_hour_and_cell_values_come_from_the_end_row(self):
        out = self._read(_series(rain={1: 4.0, 2: 5.2}), now=T0 + 600)
        r0, r1 = out['rows'][0], out['rows'][1]
        self.assertEqual((r0['time'], r0['end']), (T0, T0 + H))
        self.assertEqual(r0['precip_mm_h'], 4.0)              # 파일의 T0+1h 행(= T0~T0+1h 칸)
        self.assertEqual(r1['precip_mm_h'], 5.2)
        self.assertEqual(r0['temp_c'], 20.0)                  # 순간 값은 time 정시
        self.assertEqual(r0['solar_w_m2'], 10.0)              # 칸 평균은 end 행의 값
        self.assertEqual(r0['pop_pct'], 51)
        self.assertEqual(len(out['rows']), 4)                 # 마지막 정시는 칸을 닫을 행이 없다

    def test_missing_values_are_omitted_not_zero(self):
        s = _series()
        s['rows'][1][1].pop('RN1')
        s['rows'][2][1]['TMP'] = None
        out = self._read(s, now=T0)
        self.assertNotIn('precip_mm_h', out['rows'][0])
        self.assertNotIn('temp_c', out['rows'][2])

    def test_response_tells_resolution_horizon_and_whether_the_request_is_covered(self):
        out = self._read(_series(), T0, T0 + 100 * H, now=T0)
        self.assertTrue(out['available'])
        self.assertEqual(out['resolution'], {'step_s': 3600, 'kind': 'hourly'})
        self.assertEqual((out['coverage']['start'], out['horizon']), (T0, T0 + 4 * H))
        self.assertFalse(out['covers_request'])               # 요청이 지평 너머 — 거짓으로 덮었다고 하지 않는다
        self.assertEqual(out['fetched_at'], T0 + 600.0)
        self.assertEqual(out['source']['name'], 'OM hourly')
        self.assertEqual(out['variables']['precip_mm_h']['kind'], 'cell')
        self.assertEqual(out['variables']['temp_c']['kind'], 'instant')
        self.assertIn('nothing is filled in', out['note'])
        self.assertEqual(self._read(_series(), T0, T0 + 3 * H, now=T0)['covers_request'], True)

    def test_window_keeps_only_overlapping_cells(self):
        out = self._read(_series(8), T0 + 2 * H, T0 + 4 * H, now=T0)
        self.assertEqual([r['time'] for r in out['rows']], [T0 + 2 * H, T0 + 3 * H])

    def test_default_window_starts_at_the_current_hour(self):
        out = self._read(_series(8), now=T0 + 3 * H + 900)
        self.assertEqual(out['rows'][0]['time'], T0 + 3 * H)

    def test_variable_subset_and_unknown_name(self):
        out = self._read(_series(), variables=['precip_mm_h'], now=T0)
        self.assertEqual(set(out['rows'][0]) - {'time', 'end', 'calibrated'}, {'precip_mm_h'})
        self.assertEqual(list(out['variables']), ['precip_mm_h'])
        with self.assertRaises(ValueError):
            self._read(_series(), variables=['nope'], now=T0)

    def test_unavailable_gives_a_reason(self):
        out = self._read(None, now=T0)
        self.assertFalse(out['available'])
        self.assertEqual(out['reason'], 'none_designated')
        self.assertIn('designated', out['reason_text'])


_APP = {}


def setUpModule():
    import flask_login
    from flask import Blueprint
    from flask_babel import Babel
    from flask_restx import Api
    from aot.aot_flask.api import api as global_api
    from aot.aot_flask.api.twin import ns_twin
    from aot.aot_flask.extensions import csrf, db
    from aot.databases.models import GeoMap, GeoShape, Misc, Role, User

    tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(tmp.name, 't.db'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='x', WTF_CSRF_ENABLED=False, TESTING=True)
    db.init_app(app)
    csrf.init_app(app)
    bp = Blueprint('api_twin_fs_test', __name__, url_prefix='/api')
    api = Api(bp, default_mediatype=API)
    for media, fn in global_api.representations.items():
        api.representations[media] = fn
    api.add_namespace(ns_twin)
    csrf.exempt(bp)
    Babel(app)
    app.register_blueprint(bp)
    lm = flask_login.LoginManager()
    lm.init_app(app)

    @lm.request_loader
    def _load(req):
        try:
            return User.find_by_api_key(base64.b64decode(req.headers.get('X-API-KEY')))
        except Exception:
            return None

    with app.app_context():
        db.create_all()
        db.session.add(Misc())
        viewer = Role(name='Viewer', edit_settings=False, view_settings=True)
        nobody = Role(name='Nobody', edit_settings=False, view_settings=False)
        db.session.add_all([viewer, nobody])
        db.session.commit()
        keys = {}
        for name, role in (('viewer', viewer), ('nobody', nobody)):
            u = User(name='u_' + name, email=name + '@example.com', role_id=role.id)
            u.set_password('correct horse battery staple')
            db.session.add(u)
            db.session.flush()
            keys[name] = base64.b64encode(u.issue_api_key(name, 'full')).decode()
        db.session.add(GeoMap(unique_id='m1', name='M'))
        for uid, typ in (('site-1', 'site'), ('zone-1', 'zone')):
            db.session.add(GeoShape(unique_id=uid, geo_id='m1', type=typ,
                                    feature={'type': 'Feature', 'properties': {'name': uid},
                                             'geometry': {'type': 'Point', 'coordinates': [130.7, 32.7]}}))
        db.session.commit()
    _APP.update(app=app, tmp=tmp, keys=keys, client=app.test_client())


def tearDownModule():
    _APP['tmp'].cleanup()


class TestRest(unittest.TestCase):
    URL = '/api/twin/forecast_series'

    def setUp(self):
        self.c = _APP['client']
        p = mock.patch('aot.utils.twin_gate.twin_enabled', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def _h(self, who='viewer'):
        return {'X-API-KEY': _APP['keys'][who], 'Accept': API}

    def _get(self, qs='site=site-1', who='viewer', series='default'):
        s = _series() if series == 'default' else series
        with patched(s):
            return self.c.get(self.URL + '?' + qs, headers=self._h(who))

    def test_returns_the_series(self):
        r = self._get('site=site-1&variables=precip_mm_h,temp_c')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        j = r.get_json()
        self.assertTrue(j['available'])
        self.assertEqual(j['resolution']['step_s'], 3600)
        self.assertIn('horizon', j)
        self.assertEqual(set(j['variables']), {'precip_mm_h', 'temp_c'})

    def test_unavailable_is_200_with_a_reason(self):
        r = self._get(series=None)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()['available'])
        self.assertEqual(r.get_json()['reason'], 'none_designated')

    def test_flag_off_is_404(self):
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False), \
                mock.patch.dict(os.environ, {'AOT_TWIN_ENABLED': ''}):
            self.assertEqual(self._get().status_code, 404)

    def test_needs_view_settings(self):
        self.assertEqual(self._get(who='nobody').status_code, 403)

    def test_validation(self):
        self.assertEqual(self._get('').status_code, 422)                              # site 없음
        self.assertEqual(self._get('site=missing').status_code, 404)
        self.assertEqual(self._get('site=zone-1').status_code, 404)                   # 대지가 아님
        self.assertEqual(self._get('site=site-1&variables=nope').status_code, 422)
        self.assertEqual(self._get('site=site-1&start=abc').status_code, 422)
        self.assertEqual(self._get('site=site-1&start=10&end=5').status_code, 422)
