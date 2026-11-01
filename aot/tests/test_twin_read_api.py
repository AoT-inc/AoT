# coding=utf-8
"""트윈 읽기 API(`/api/twin/series`·`/api/twin/plots`)와 걷어 낸 수신 API 의 흔적(실험, 비공개).

- 읽기: 게이트(설정 > 일반 플래그 — `twin_gate.twin_enabled`), 측정 이름 검사, 구획 묶음.
- 걷어 낸 것(2026-10-24, 계획서 §9.19): `POST /api/twin/ingest` 는 없다. 옛 키 범위 'twin_ingest' 로 발급된
  행이 남아 있어도 읽기 전용으로 보고(`RETIRED_READONLY_SCOPES`) 어느 POST 도 못 한다.
- 검증 규칙의 단위 시험은 `aot/twin/tests/test_contract_check.py` 로 옮겼다.

Influx 는 건드리지 않는다(읽기 함수를 바꿔 끼운다). 임시 sqlite 만 쓴다.
"""
import base64
import os
import tempfile
import time
import unittest
from unittest import mock

from aot.twin import output as O
from aot.twin.types import Status, TargetKind, TwinOutput

PLOT = '53bdbec9-3507-4944-a7c2-778758196d8a'
COORD = 'c00rd000-0000-4000-8000-000000000001'


def _field_output(t0, status=Status.OK, n=8):
    days = [t0 + k * 86400.0 for k in range(n)]
    q = {'theta_root': {'p10': [20.0 + k for k in range(n)], 'p50': [22.0 + k for k in range(n)],
                        'p90': [24.0 + k for k in range(n)]},
         'Ks': {'p10': [0.8] * n, 'p50': [0.9] * n, 'p90': [1.0] * n}}
    out = TwinOutput(kind=TargetKind.FIELD, target_id=PLOT, t0=t0,
                     grids={'daily': days}, quantiles={'daily': q},
                     events={'daily': {'water_deficit': [0.1] * n}})
    out.meta = {'status': int(status), 'valid_until': t0 + (36 * 3600.0 if status < 2 else 0.0),
                'horizon_d': n - 1, 'ensemble_size': 64, 'stale_s': 0.0, 'model_rev': 1,
                'rain_src': 2}
    if status >= 2:
        out.grids, out.quantiles, out.events = {}, {}, {}
    return out


def _body(points, with_pubs=True):
    b = {'source': 'aot_twin', 'points': [
        {'m': p.measurement, 'id': p.device_id, 'ch': p.channel, 'ts': p.timestamp, 'v': p.value,
         'tags': dict(p.tags)} for p in points]}
    if with_pubs:
        b['pubs'] = O.publications(points)
    return b


def _now_t0():
    now = time.time()
    return now, float(int(now) // 3600 * 3600)


_APP = {}


def setUpModule():
    from flask import Flask
    import flask_login
    from flask_babel import Babel

    from aot.aot_flask.extensions import db, csrf
    import aot.databases.models  # noqa: F401 — 모델 등록
    from aot.databases.models import CustomController, GeoPlot, Misc, Role, User
    from flask import Blueprint
    from flask_restx import Api
    from aot.aot_flask.api import api as global_api
    from aot.aot_flask.api.measurement import ns_measurement   # 다른 POST 경로(가드 확인용)
    from aot.aot_flask.api.twin import ns_twin
    from aot.aot_flask.app import (extension_csrf, register_api_key_scope_guard)  # noqa: F401

    tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(tmp.name, 't.db'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY='x',
                      WTF_CSRF_ENABLED=False, TESTING=True)
    db.init_app(app)
    csrf.init_app(app)
    # 전역 api_blueprint 를 등록하지 않는다 — flask-restx Api 가 이 앱에 묶이면 뒤에 import 되는
    # 다른 시험의 네임스페이스가 이미 요청을 받은 이 앱에 경로를 달려다 실패한다.
    api_blueprint = Blueprint('api_twin_test', __name__, url_prefix='/api')
    api = Api(api_blueprint, default_mediatype='application/vnd.aot.v1+json')
    for media, fn in global_api.representations.items():
        api.representations[media] = fn
    api.add_namespace(ns_twin)
    api.add_namespace(ns_measurement)
    csrf.exempt(api_blueprint)
    Babel(app)
    app.register_blueprint(api_blueprint)
    register_api_key_scope_guard(app)
    lm = flask_login.LoginManager()
    lm.init_app(app)

    @lm.request_loader
    def _load(req):                         # app.load_user_from_request 의 X-API-KEY 경로와 같다
        try:
            return User.find_by_api_key(base64.b64decode(req.headers.get('X-API-KEY')))
        except Exception:
            return None

    with app.app_context():
        db.create_all()
        db.session.add(Misc())
        admin = Role(name='Admin', edit_controllers=True, view_settings=True)
        viewer = Role(name='Viewer', edit_controllers=False, view_settings=True)
        db.session.add_all([admin, viewer])
        db.session.commit()
        keys = {}
        for name, role, scope in (('admin', admin, 'full'), ('node', admin, 'twin_ingest'),
                                  ('ro', admin, 'readonly'), ('viewer', viewer, 'full')):
            u = User(name='u_' + name, email=name + '@example.com', role_id=role.id)
            u.set_password('correct horse battery staple')
            db.session.add(u)
            db.session.flush()
            keys[name] = base64.b64encode(u.issue_api_key(name, scope)).decode()
            if scope == 'twin_ingest':
                # 발급은 모르는 범위를 읽기 전용으로 좁힌다 — 옛 서버에 남은 행을 흉내 내려고 값을 직접 되돌린다
                from aot.databases.models.user_api_key import UserAPIKey
                UserAPIKey.query.filter_by(user_id=u.id).one().scope = 'twin_ingest'
        db.session.add(CustomController(unique_id=COORD, device='env_coordinator', name='c'))
        import datetime
        db.session.add(GeoPlot(unique_id=PLOT, geo_id='a19a5594-e689-4aac-bacb-c94b020ccd67',
                               name='들깨 1구', subject='들깨', kind='vegetation',
                               started_on=datetime.date(2026, 8, 14)))
        db.session.commit()
    _APP.update(app=app, tmp=tmp, keys=keys, client=app.test_client())


def tearDownModule():
    _APP['tmp'].cleanup()


class TwinReadApiTest(unittest.TestCase):

    def setUp(self):
        self.client = _APP['client']
        self.keys = _APP['keys']
        g = mock.patch('aot.utils.twin_gate.twin_enabled', return_value=True)
        g.start()
        self.addCleanup(g.stop)

    def _post(self, key, body, path):
        return self.client.post(path, json=body, headers={
            'X-API-KEY': key, 'Accept': 'application/vnd.aot.v1+json'})

    def test_ingest_route_is_gone(self):
        now, t0 = _now_t0()
        body = _body(O.flatten(_field_output(t0)))
        with mock.patch('aot.utils.influx.write_influxdb_points') as w:
            for who in ('admin', 'node'):
                r = self._post(self.keys[who], body, '/api/twin/ingest')
                self.assertIn(r.status_code, (403, 404, 405), (who, r.status_code))
            w.assert_not_called()
        self.assertEqual(self._post(self.keys['admin'], body, '/api/twin/ingest').status_code, 404)

    def test_legacy_twin_key_is_read_only_everywhere(self):
        """옛 'twin_ingest' 범위 행은 전체 권한으로 넓어지지 않는다 — 어느 POST 도 요청 가드가 막는다."""
        from aot.databases.models.user_api_key import UserAPIKey
        with _APP['app'].app_context():
            row = UserAPIKey.query.filter_by(scope='twin_ingest').one()
            self.assertTrue(row.is_readonly)
            self.assertFalse(hasattr(row, 'allows_post'))
        r = self._post(self.keys['node'], {}, '/api/measurements/create/x/C/0/1.0')
        self.assertEqual(r.status_code, 403)
        self.assertIn('read-only', r.get_data(as_text=True))
        r = self._post(self.keys['node'], {}, '/api/twin/ingest')
        self.assertEqual(r.status_code, 403)

    def test_issuing_an_unknown_scope_narrows_to_read_only(self):
        from aot.databases.models import User
        from aot.databases.models.user_api_key import UserAPIKey
        with _APP['app'].app_context():
            u = User.query.filter_by(name='u_admin').one()
            u.issue_api_key('again', 'twin_ingest')
            from aot.aot_flask.extensions import db
            db.session.commit()
            self.assertEqual(UserAPIKey.query.filter_by(name='again').one().scope, 'readonly')

    def test_series_read_window_and_gate(self):
        rows = [(1.0, 20.0), (2.0, 21.0)]
        with mock.patch('aot.utils.influx.read_twin_series', return_value=rows) as rd:
            r = self.client.get('/api/twin/series/{}/env_twin_field/1?start=0&end=86400'.format(PLOT),
                                headers={'X-API-KEY': self.keys['node'],
                                         'Accept': 'application/vnd.aot.v1+json'})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            body = r.get_json()
            self.assertEqual(body['measurements'], [{'time': 1.0, 'value': 20.0}, {'time': 2.0, 'value': 21.0}])
            self.assertEqual((body['scenario'], body['post']), ('baseline', False))
            self.assertEqual({'calibrated', 'cal_rev', 'fc_issue_epoch', 'origin'} - set(body), set())   # 계보 칸이 늘 있다
            rd.assert_called_once_with(PLOT, 'env_twin_field', 1, 0.0, 86400.0, lead=None)
        hdr = {'X-API-KEY': self.keys['node'], 'Accept': 'application/vnd.aot.v1+json'}
        self.assertEqual(self.client.get('/api/twin/series/x/temperature/0', headers=hdr).status_code, 422)
        self.assertEqual(self.client.get('/api/twin/series/x/env_twin/0?start=0&end=99999999',
                                         headers=hdr).status_code, 422)
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False), \
                mock.patch.dict(os.environ, {'AOT_TWIN_ENABLED': '1'}):     # 옛 개발 설정은 더 이상 열지 않는다
            self.assertEqual(self.client.get('/api/twin/series/x/env_twin/0', headers=hdr).status_code, 404)

    def test_plots_bundle_route(self):
        from aot.utils import twin_read as R
        now, t0 = _now_t0()
        pts = O.flatten(_field_output(t0))
        rows = {}
        for p in pts:
            if p.measurement in ('env_twin_field', 'env_twin_field_meta') and not p.tags.get('lead_d'):
                rows.setdefault((p.measurement, p.device_id, p.channel), []).append((p.timestamp, p.value))

        def fake(meas, ids, chans, lo, hi):
            return {(d, c): v for (m, d, c), v in rows.items() if m == meas and d in ids and c in chans}
        hdr = {'X-API-KEY': self.keys['node'], 'Accept': 'application/vnd.aot.v1+json'}
        with mock.patch('aot.utils.influx.read_twin_many', side_effect=fake):
            r = self.client.get('/api/twin/plots?plots={},nope'.format(PLOT), headers=hdr)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual([p['plot_uuid'] for p in body['plots']], [PLOT])    # 없는 구획은 빠진다
        rec = body['plots'][0]
        self.assertTrue(rec['usable'], rec['reason'])
        self.assertEqual(rec['days'][0], t0)
        self.assertEqual(rec['theta_root_p50'][0], 22.0)
        self.assertEqual(set(R.CURVE_CHANNELS) - set(rec), set())
        self.assertEqual(self.client.get('/api/twin/plots?measure=facility', headers=hdr).status_code, 422)
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False):
            self.assertEqual(self.client.get('/api/twin/plots', headers=hdr).status_code, 404)


    def test_chart_plot_route(self):
        """구획 그래프 묶음 — 게이트(404)·권한·범위 자르기·대상 아닌 구획(404)·읽기 실패(503)."""
        hdr = {'X-API-KEY': self.keys['viewer'], 'Accept': 'application/vnd.aot.v1+json'}
        url = '/api/twin/chart/plot/' + PLOT
        with mock.patch('aot.utils.twin_chart.plot_chart', return_value={'plot_id': PLOT, 'days': []}) as pc:
            r = self.client.get(url + '?back=999&ahead=0', headers=hdr)
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual(r.get_json()['plot_id'], PLOT)
            self.assertEqual(pc.call_args[0][0], PLOT)
            self.assertEqual(pc.call_args[0][2:], (999, 0))     # 자르기는 조립기(MAX_BACK_D·최소 +1일)가 한다
            self.assertEqual(self.client.get(url + '?back=x', headers=hdr).status_code, 422)
        with mock.patch('aot.utils.twin_chart.plot_chart', return_value=None):
            self.assertEqual(self.client.get(url, headers=hdr).status_code, 404)
        with mock.patch('aot.utils.twin_chart.plot_chart', side_effect=RuntimeError('influx down')):
            self.assertEqual(self.client.get(url, headers=hdr).status_code, 503)
        with mock.patch('aot.utils.twin_gate.twin_enabled', return_value=False):
            self.assertEqual(self.client.get(url, headers=hdr).status_code, 404)
        with mock.patch('aot.utils.twin_chart.plot_chart') as pc:
            self.assertEqual(self.client.get(url, headers={'Accept': 'application/vnd.aot.v1+json'}).status_code, 401)
            pc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
