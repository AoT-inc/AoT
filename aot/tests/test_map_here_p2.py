# coding=utf-8
"""지도 현재 위치 P2 — 화면이 보고한 위치를 서버가 이름·거리로 풀어 get_screen 에 싣는다.

좌표는 응답에 없어야 하고, 오차 규칙(edge·<=오차·coarse)을 지키며, 켜진 기기·10분 안일 때만 읽힌다.
"""
import json
import time as _t
import types
import unittest
import uuid
from datetime import date
from unittest import mock

LAT, LNG = 36.002, 127.002          # 3-1 과 감자밭 한가운데 근처
_M_LNG = 111320 * 0.80902           # 위도 36° 에서 경도 1도(m)


def sq(x0, y0, x1, y1):
    return {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def dev(name, dlat_m, dlng_m, base=(LAT, LNG)):
    # 위치는 행 컬럼이 아니라 리졸버가 낸다 — 시험은 locate_many 를 _placed 로 대신한다.
    return types.SimpleNamespace(
        name=name, unique_id='u-' + name,
        latitude=base[0] + dlat_m / 111320.0, longitude=base[1] + dlng_m / _M_LNG)


def _placed(devs):
    """dev() 행들의 위치를 locate_many 가 낸 것처럼 돌려주는 대역."""
    def fake(pairs, **_kw):
        by_id = {row.unique_id: row for row, _t, _l in devs}
        return {(k, d): types.SimpleNamespace(
                    point=(by_id[d].latitude, by_id[d].longitude), basis='device')
                for k, d in pairs if d in by_id}
    return fake


class HereTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Dashboard, GeoMap, GeoPlot, GeoShape, Widget
        from aot.space import shape_index
        self.tag = 'zz_here_' + uuid.uuid4().hex[:6]
        dash = Dashboard(name=self.tag)
        db.session.add(dash)
        db.session.commit()
        self.dash_id = dash.unique_id
        shape_index.invalidate()
        mid = str(uuid.uuid4())

        def shape(kind, name, geom):
            return GeoShape(geo_id=mid, type=kind, unique_id=str(uuid.uuid4()),
                            feature={'type': 'Feature', 'geometry': geom, 'properties': {'name': name}})
        db.session.add_all([
            GeoMap(unique_id=mid, name=self.tag + '지도', category='design'),
            shape('site', '3포장', sq(126.99, 35.99, 127.03, 36.02)),
            shape('zone', '3-1', sq(127.00, 36.00, 127.01, 36.01)),
            shape('zone', '3-2', sq(127.01, 36.00, 127.02, 36.01))])
        db.session.add(GeoPlot(geo_id=mid, kind='vegetation', subject='고추', name='고추밭',
                               started_on=date(2020, 1, 1),
                               feature={'type': 'Feature', 'properties': {},
                                        'geometry': sq(127.000, 36.000, 127.005, 36.005)}))
        w = Widget(name='지도', graph_type='AoT_map', tab_id=self.dash_id,
                   custom_options=json.dumps({'map_uuid': mid}))
        db.session.add(w)
        db.session.commit()
        self.mid, self.widget = mid, w.unique_id
        self._devs = mock.patch('aot.utils.geo_distance._named_devices', return_value=[])
        self._devs.start()

    def tearDown(self):
        self._devs.stop()
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoMap, GeoPlot, GeoShape, Widget, Dashboard
        db.session.rollback()
        for model in (GeoShape, GeoPlot):
            model.query.filter(model.geo_id == self.mid).delete(synchronize_session=False)
        GeoMap.query.filter(GeoMap.unique_id == self.mid).delete(synchronize_session=False)
        Widget.query.filter(Widget.tab_id == self.dash_id).delete(synchronize_session=False)
        Dashboard.query.filter(Dashboard.unique_id == self.dash_id).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()

    def _around(self, lat=LAT, lng=LNG, acc=10):
        from aot.utils import geo_distance
        return geo_distance.around_point(lat, lng, acc, map_uuid=self.mid)

    # ── around_point ────────────────────────────────────────────────────────
    def test_inside_names_the_chain_and_the_plot(self):
        r = self._around(acc=10)
        self.assertEqual(['3포장 > 3-1', '고추밭'], r['inside'])
        self.assertEqual([], r['edge'])
        self.assertEqual(10, r['accuracy_m'])
        self.assertNotIn('coarse', r)

    def test_a_boundary_within_the_accuracy_is_edge_not_inside(self):
        # 3-1 과 3-2 의 경계(경도 127.01)에서 약 4.5 m 안쪽, 오차 12 m.
        r = self._around(lng=127.01 - 5.0 / _M_LNG, acc=12)
        self.assertEqual(['3-1', '3-2'], sorted(r['edge']))
        self.assertEqual(['3포장'], r['inside'])            # 대지 경계는 멀다
        self.assertNotIn('3-1', ' '.join(r['inside']))

    def test_above_50m_it_does_not_claim_membership(self):
        r = self._around(acc=60)
        self.assertTrue(r['coarse'])
        self.assertEqual([], r['inside'])
        self.assertEqual([], r['edge'])

    def test_exactly_50m_is_still_usable(self):
        self.assertNotIn('coarse', self._around(acc=50))

    def test_near_devices_use_a_bound_when_within_the_accuracy(self):
        devs = [(dev('밸브1', 18, 0), 'output', 'x'), (dev('토양센서2', 4, 3), 'input', 'y'),
                (dev('먼장치', 500, 0), 'input', 'z')]
        with mock.patch('aot.utils.geo_distance._named_devices', return_value=devs), \
             mock.patch('aot.space.device_location.locate_many', _placed(devs)):
            r = self._around(acc=12)
        self.assertEqual([{'name': '토양센서2', 'm': '<=12'}, {'name': '밸브1', 'm': 18}], r['near'])

    def test_lists_are_capped_and_the_basis_is_attached(self):
        devs = [(dev('d%d' % i, 10 + i, 0), 'input', 'x') for i in range(8)]
        with mock.patch('aot.utils.geo_distance._named_devices', return_value=devs), \
             mock.patch('aot.space.device_location.locate_many', _placed(devs)):
            r = self._around(acc=5)
        self.assertEqual(3, len(r['near']))
        self.assertIn("Don't pick one", r['basis'])

    def test_the_result_carries_no_coordinates(self):
        devs = [(dev('밸브1', 18, 0), 'output', 'x')]
        with mock.patch('aot.utils.geo_distance._named_devices', return_value=devs), \
             mock.patch('aot.space.device_location.locate_many', _placed(devs)):
            blob = json.dumps(self._around(acc=12), ensure_ascii=False)
        for needle in ('36.00', '127.00', 'lat', 'lng'):
            self.assertNotIn(needle, blob)

    # ── get_screen 의 here ──────────────────────────────────────────────────
    def _live(self, here, allowed=True, client_age=0, key='here'):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        state = {'path': '/dashboard/' + self.dash_id, 'visible_widgets': [self.widget]}
        if here is not None:
            state[key] = here
        now = _t.time()
        row = {'client_state': json.dumps(state), 'client_at': now - client_age,
               'page_kind': 'dashboard', 'page_ref': self.dash_id, 'ai_allowed': 1 if allowed else 0}
        return S._screen_live_state(row, now)

    def _here(self, **kw):
        h = {'widget_id': self.widget, 'lat': LAT, 'lng': LNG, 'acc': 10, 'age_s': 8}
        h.update(kw)
        return h

    def test_screen_response_has_here_without_coordinates(self):
        live = self._live(self._here())
        h = live['here']
        self.assertEqual(['3포장 > 3-1', '고추밭'], h['inside'])
        self.assertEqual(8, h['age_s'])
        blob = json.dumps(h, ensure_ascii=False)
        for needle in ('36.00', '127.00', '"lat"', '"lng"', 'widget_id'):
            self.assertNotIn(needle, blob)

    def test_chosen_spot_carries_its_source_and_the_screen_resolved_address(self):
        """지도 중심·눌러 고른 자리: 어떻게 골랐는지와 화면이 푼 주소 한 줄. 좌표는 여전히 없다."""
        for src in ('center', 'pick', 'search', 'favorite'):
            h = self._live(self._here(acc=1, src=src, addr='  1 Main St, Somewhere  '))['here']
            self.assertEqual(src, h['source'])
            self.assertEqual('1 Main St, Somewhere', h['address'])
            self.assertEqual(['3포장 > 3-1', '고추밭'], h['inside'])
            blob = json.dumps(h, ensure_ascii=False)
            for needle in ('36.00', '127.00', '"lat"', '"lng"'):
                self.assertNotIn(needle, blob)

    def test_device_position_never_carries_an_address_or_a_source(self):
        """기기 위치(gps)는 주소를 싣지 않는다 — 화면이 보내도 무시한다. 알 수 없는 출처도 gps 로 본다."""
        for extra in ({}, {'src': 'gps', 'addr': 'X Street'}, {'src': 'bogus', 'addr': 'X Street'}):
            h = self._live(self._here(**extra))['here']
            self.assertNotIn('source', h)
            self.assertNotIn('address', h)

    def test_long_address_is_trimmed(self):
        h = self._live(self._here(acc=1, src='pick', addr='a' * 500))['here']
        self.assertEqual(160, len(h['address']))

    def test_no_here_when_the_screen_did_not_report_one(self):
        self.assertNotIn('here', self._live(None) or {})

    def test_no_here_when_ai_control_is_off_on_that_device(self):
        self.assertNotIn('here', self._live(self._here(), allowed=False) or {})

    def test_expired_here_is_ignored(self):
        self.assertNotIn('here', self._live(self._here(age_s=601)) or {})
        self.assertIn('here', self._live(self._here(age_s=590)))

    def test_age_grows_with_the_time_since_the_report(self):
        h = self._live(self._here(age_s=5), client_age=12)['here']
        self.assertGreaterEqual(h['age_s'], 17)

    def test_malformed_here_is_dropped_not_fatal(self):
        for bad in ({'lat': 'x', 'lng': 1, 'acc': 3}, {'lat': 95, 'lng': 0, 'acc': 3},
                    {'lat': 0, 'lng': 0, 'acc': 0}, 'text', []):
            self.assertNotIn('here', self._live(bad) or {})

    def test_added_state_stays_small_and_cheap(self):
        """client_state 는 8,000자에서 잘린다 — here 가 그 몫을 거의 먹지 않아야 한다."""
        raw = json.dumps({'here': self._here()}, ensure_ascii=False)
        self.assertLess(len(raw), 150)
        t0 = _t.perf_counter()
        for _ in range(20):
            self._around()
        per_call_ms = (_t.perf_counter() - t0) / 20 * 1000
        print('\n[here] around_point 평균 %.1f ms (작은 지도)' % per_call_ms)
        self.assertLess(per_call_ms, 200)

    def test_a_large_map_stays_fast(self):
        """도형 150개·구획 60개. 대부분 멀리(좌표 상자로 거른다) / 전부 겹쳐 있는 최악 둘 다 잰다."""
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoPlot, GeoShape
        for far in (True, False):
            rows = []
            for i in range(150):
                x0 = 126.0 + (i % 15) * 0.01 if far else 127.0005 + i * 1e-7
                y0 = 35.0 + (i // 15) * 0.01 if far else 36.0005 + i * 1e-7
                rows.append(GeoShape(
                    geo_id=self.mid, type='zone', unique_id=str(uuid.uuid4()),
                    feature={'type': 'Feature', 'properties': {'name': 'z%d' % i},
                             'geometry': sq(x0, y0, x0 + 0.004, y0 + 0.004)}))
            for i in range(60):
                x0 = 126.0 + (i % 10) * 0.01 if far else 127.0005 + i * 1e-7
                y0 = 35.5 + (i // 10) * 0.01 if far else 36.0005 + i * 1e-7
                rows.append(GeoPlot(geo_id=self.mid, kind='vegetation', subject='p%d' % i, name='p%d' % i,
                                    started_on=date(2020, 1, 1),
                                    feature={'type': 'Feature', 'properties': {},
                                             'geometry': sq(x0, y0, x0 + 0.002, y0 + 0.002)}))
            db.session.add_all(rows)
            db.session.commit()
            t0 = _t.perf_counter()
            r = self._around()
            ms = (_t.perf_counter() - t0) * 1000
            print('\n[here] 큰 지도(%s) around_point %.0f ms' % ('대부분 멀리' if far else '전부 겹침', ms))
            self.assertLessEqual(len(r['inside']), 3)
            self.assertLess(ms, 1500)
            for o in rows:
                db.session.delete(o)
            db.session.commit()


if __name__ == '__main__':
    unittest.main()
