# coding=utf-8
"""device_location.locate — 우선순위·폴백·일괄 조회 (읽기 전용 리졸버)."""
import unittest
from datetime import timedelta

from flask import Flask
from sqlalchemy import event

from aot.aot_flask.extensions import db
from aot.space import device_location as L
from aot.aot_flask.geo.device_placement import MARKER_TYPE
from aot.databases.models import (GeoBinding, GeoFacility, GeoMap, GeoShape,
                                  Input, Output)
from aot.utils.timekit import utc_now

MAP = 'map-1'
DEV = 'dev-0001'


def _poly(lat0, lng0, lat1, lng1):
    ring = [[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]
    return {'type': 'Feature', 'geometry': {'type': 'Polygon',
                                            'coordinates': [ring]},
            'properties': {}}


def _pt(lat, lng):
    return {'type': 'Feature', 'geometry': {'type': 'Point',
                                            'coordinates': [lng, lat]},
            'properties': {}}


def _named(feature, name):
    feature['properties'] = {'name': name}
    return feature


def _shape(uid, typ, feature, geo_id=MAP, **kw):
    s = GeoShape(unique_id=uid, geo_id=geo_id, type=typ, feature=feature, **kw)
    s.save()
    return s


def _bind(kind, sid, role, dev=DEV, ch='0', frm=None, to=None, dkind='output'):
    GeoBinding(spatial_kind=kind, spatial_id=sid, role=role, device_kind=dkind,
               device_id=dev, channel_id=ch,
               valid_from=frm or (utc_now() - timedelta(days=10)),
               valid_to=to).save()


class _Base(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id=MAP, name='지도').save()
        # 대지(서울 tz) ⊃ 구역 ⊃ 점들. 대지 중심은 (37.05, 127.05).
        _shape('site-1', 'site', _named(_poly(37.0, 127.0, 37.1, 127.1), '대지'),
               timezone='Asia/Seoul')
        _shape('zone-1', 'zone', _named(_poly(37.0, 127.0, 37.04, 127.04), '구역'))
        Output(unique_id=DEV, name='출력').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestPriority(_Base):

    def test_marker_only(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        p = L.locate('output', DEV)
        self.assertEqual(p.source, 'marker')
        self.assertEqual(p.point, (37.01, 127.01))
        self.assertEqual(p.basis, 'device')
        self.assertEqual(p.slot, L.SlotRef('shape', 'mk-1', 'marker', '0'))
        self.assertEqual([c.kind for c in p.chain], ['site', 'zone'])
        self.assertEqual(p.chain[1].name, '구역')
        self.assertEqual(p.tz, 'Asia/Seoul')      # 대지에서 상속
        self.assertEqual(p.precision, 'point')

    def test_area_only_uses_center(self):
        _shape('ar-1', 'device', _poly(37.0, 127.0, 37.02, 127.02))
        _bind('shape', 'ar-1', 'area')
        p = L.locate('output', DEV)
        self.assertEqual(p.source, 'area')
        self.assertAlmostEqual(p.point[0], 37.008, places=2)

    def test_marker_beats_area(self):
        _shape('ar-1', 'device', _poly(37.0, 127.0, 37.02, 127.02))
        _shape('mk-1', MARKER_TYPE, _pt(37.03, 127.03))
        _bind('shape', 'ar-1', 'area')
        _bind('shape', 'mk-1', 'marker')
        p = L.locate('output', DEV)
        self.assertEqual((p.source, p.point), ('marker', (37.03, 127.03)))

    def test_latest_valid_from_wins_in_same_rank(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _shape('mk-2', MARKER_TYPE, _pt(37.02, 127.02))
        _bind('shape', 'mk-1', 'marker', ch='1', frm=utc_now() - timedelta(days=5))
        _bind('shape', 'mk-2', 'marker', ch='2', frm=utc_now() - timedelta(days=1))
        self.assertEqual(L.locate('output', DEV).point, (37.02, 127.02))

    def _facility(self, tz=None):
        _shape('fs-1', 'facility', _named(_poly(37.06, 127.06, 37.08, 127.08), '온실'))
        GeoFacility(unique_id='fac-1', shape_uuid='fs-1', geo_id=MAP, name='온실A',
                    timezone=tz).save()

    def test_fitting_beats_area(self):
        self._facility()
        _shape('ar-1', 'device', _poly(37.0, 127.0, 37.02, 127.02))
        _bind('shape', 'ar-1', 'area')
        _bind('fitting', 'fac-1:F1', 'actuator')
        p = L.locate('output', DEV)
        self.assertEqual(p.source, 'fitting')
        self.assertAlmostEqual(p.point[0], 37.07, delta=0.01)
        self.assertEqual(p.chain[-1].kind, 'facility')
        self.assertEqual(p.slot.spatial_kind, 'fitting')
        self.assertEqual(p.precision, 'facility')   # 시설 중심이다
        self.assertEqual([c.kind for c in p.chain], ['site', 'facility'])

    def test_role_only_uses_facility_center(self):
        self._facility(tz='Asia/Tokyo')
        _bind('sensor_role', 'fac-1', 'indoor_temp', dkind='input')
        Input(unique_id=DEV + 'i', name='센서', device='X').save()
        GeoBinding.query.update({'device_id': DEV + 'i'})
        db.session.commit()
        p = L.locate('input', DEV + 'i')
        self.assertEqual(p.source, 'facility')
        self.assertAlmostEqual(p.point[1], 127.07, delta=0.01)
        self.assertEqual(p.tz, 'Asia/Tokyo')      # 시설 tz, 대지 tz 보다 안쪽

    def test_weather_role_uses_facility_center(self):
        self._facility()
        _bind('weather', 'fac-1', 'forecast_temperature', dkind='input',
              dev=DEV)
        Input(unique_id='w-1', name='예보', device='X').save()
        GeoBinding.query.update({'device_id': 'w-1'})
        db.session.commit()
        p = L.locate('input', 'w-1')
        self.assertEqual((p.source, p.precision), ('facility', 'facility'))

    def test_fitting_bay_id_sets_chain_bay(self):
        self._facility()
        f = GeoFacility.query.filter_by(unique_id='fac-1').one()
        f.fittings = [{'id': 'F1', 'kind': 'window', 'bay_id': 'B2'}]
        f.bays = [{'id': 'B2', 'name': '2동'}]
        db.session.commit()
        _bind('fitting', 'fac-1:F1', 'actuator')
        p = L.locate('output', DEV)
        self.assertEqual(p.chain[-1], L.PlaceRef('bay', 'fac-1:B2', '2동'))

    def test_fitting_without_bay_id_has_no_bay(self):
        self._facility()
        _bind('fitting', 'fac-1:F1', 'actuator')
        self.assertNotIn('bay', [c.kind for c in L.locate('output', DEV).chain])

    def test_fitting_tz_facility_before_site(self):
        self._facility(tz='Asia/Tokyo')
        _bind('fitting', 'fac-1:F1', 'actuator')
        self.assertEqual(L.locate('output', DEV).tz, 'Asia/Tokyo')

    def test_marker_in_facility_tz_parents_before_facility(self):
        self._facility(tz='Asia/Tokyo')
        _shape('mk-1', MARKER_TYPE, _pt(37.07, 127.07))
        _bind('shape', 'mk-1', 'marker')
        p = L.locate('output', DEV)
        self.assertEqual([c.kind for c in p.chain], ['site', 'facility'])
        self.assertEqual(p.tz, 'Asia/Seoul')   # 도형 앵커: 부모 체인 > 시설

    def test_channel_unresolvable_anchor_falls_back_to_device_level(self):
        _shape('mk-0', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-0', 'marker', ch='0')
        _bind('shape', 'ghost-shape', 'marker', ch='2')   # 도형이 없다
        p = L.locate('output', DEV, channel_id='2')
        self.assertEqual((p.source, p.point), ('marker', (37.01, 127.01)))

    def test_channel_specific_wins_then_device_level(self):
        _shape('mk-0', MARKER_TYPE, _pt(37.01, 127.01))
        _shape('mk-2', MARKER_TYPE, _pt(37.03, 127.03))
        _bind('shape', 'mk-0', 'marker', ch='0')
        _bind('shape', 'mk-2', 'marker', ch='2', frm=utc_now() - timedelta(days=20))
        self.assertEqual(L.locate('output', DEV, channel_id='2').point,
                         (37.03, 127.03))
        self.assertEqual(L.locate('output', DEV, channel_id='7').point,
                         (37.01, 127.01))       # 장치 단위 폴백

    def test_marker_tz_from_zone_overrides_site(self):
        GeoShape.query.filter_by(unique_id='zone-1').update(
            {'timezone': 'America/New_York'})
        db.session.commit()
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        self.assertEqual(L.locate('output', DEV).tz, 'America/New_York')


class TestTime(_Base):

    def test_past_at_sees_ended_binding_and_now_does_not(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        t0 = utc_now()
        _bind('shape', 'mk-1', 'marker', frm=t0 - timedelta(days=10),
              to=t0 - timedelta(days=2))
        past = L.locate('output', DEV, at=t0 - timedelta(days=5))
        self.assertEqual(past.source, 'marker')
        now = L.locate('output', DEV)
        self.assertEqual(now.source, 'site')     # 끝난 연결은 되살아나지 않는다
        self.assertEqual(L.locate('output', DEV, at=t0 - timedelta(days=1)).source,
                         'site')

    def test_boundaries_valid_from_inclusive_valid_to_exclusive(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        f = utc_now().replace(microsecond=0) - timedelta(days=10)
        to = f + timedelta(days=4)
        _bind('shape', 'mk-1', 'marker', frm=f, to=to)
        self.assertEqual(L.locate('output', DEV, at=f).source, 'marker')
        self.assertEqual(L.locate('output', DEV, at=to).source, 'site')
        self.assertEqual(L.locate('output', DEV,
                                  at=to - timedelta(seconds=1)).source, 'marker')
        self.assertEqual(L.locate('output', DEV,
                                  at=f - timedelta(seconds=1)).source, 'site')

    def test_aware_at_is_normalised(self):
        from datetime import timezone
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        f = utc_now().replace(microsecond=0) - timedelta(days=10)
        _bind('shape', 'mk-1', 'marker', frm=f, to=f + timedelta(days=4))
        kst = timezone(timedelta(hours=9))
        inside = (f + timedelta(days=1)).astimezone(kst)
        outside = (f + timedelta(days=4)).astimezone(kst)
        self.assertEqual(L.locate('output', DEV, at=inside).source, 'marker')
        self.assertEqual(L.locate('output', DEV, at=outside).source, 'site')

    def test_locate_many_at(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        t0 = utc_now()
        _bind('shape', 'mk-1', 'marker', frm=t0 - timedelta(days=10),
              to=t0 - timedelta(days=2))
        k = ('output', DEV)
        self.assertEqual(L.locate_many([k], at=t0 - timedelta(days=5))[k].source,
                         'marker')
        self.assertEqual(L.locate_many([k])[k].source, 'site')


class TestFallbacks(_Base):

    def test_site_fallback_when_single_site(self):
        p = L.locate('output', DEV)
        self.assertEqual((p.source, p.basis), ('site', 'site'))
        self.assertAlmostEqual(p.point[0], 37.05, delta=0.02)
        self.assertEqual(p.tz, 'Asia/Seoul')
        self.assertEqual([c.kind for c in p.chain], ['site'])

    def test_none_when_no_single_site(self):
        _shape('site-2', 'site', _poly(38.0, 128.0, 38.1, 128.1))
        p = L.locate('output', DEV)
        self.assertEqual(p, L.Placement(None, (), None, 'none', None, 'none'))

    def test_unknown_device_is_none(self):
        self.assertIsNone(L.locate('output', 'no-such'))

    def test_locate_many_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            L.locate_many([('output', DEV), ('aot_device', DEV)])

    def test_unknown_kind_raises(self):
        for alias in ('aot_device', 'custom_controller', 'generic_function'):
            with self.assertRaises(ValueError):
                L.locate(alias, DEV)


class TestNoAppContext(unittest.TestCase):
    """데몬: 앱 컨텍스트 없이 분리 세션으로 읽는다."""

    def test_locate_without_app_context(self):
        import contextlib
        import os
        import tempfile
        from unittest import mock

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        d = tempfile.mkdtemp()
        path = os.path.join(d, 't.db')
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + path
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        with app.app_context():
            db.create_all()
            GeoMap(unique_id=MAP, name='지도').save()
            _shape('site-1', 'site', _poly(37.0, 127.0, 37.1, 127.1),
                   timezone='Asia/Seoul')
            _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
            Output(unique_id=DEV, name='출력').save()
            _bind('shape', 'mk-1', 'marker')
            db.session.remove()
            db.engine.dispose()
        engine = create_engine('sqlite:///' + path)

        @contextlib.contextmanager
        def scope(_path):
            s = sessionmaker(bind=engine)()
            try:
                yield s
            finally:
                s.close()

        with mock.patch('aot.utils.database.session_scope', scope):
            p = L.locate('output', DEV)
        self.assertEqual((p.source, p.point, p.tz),
                         ('marker', (37.01, 127.01), 'Asia/Seoul'))
        engine.dispose()


class TestBatch(_Base):

    def _count(self, n):
        for i in range(n):
            Output(unique_id='b-%d' % i, name='o%d' % i).save()
            _shape('bm-%d' % i, MARKER_TYPE, _pt(37.01 + i * 1e-4, 127.01))
            _bind('shape', 'bm-%d' % i, 'marker', dev='b-%d' % i)
        db.session.commit()
        stmts = []

        def on(conn, cur, stmt, *a):
            stmts.append(stmt)
        event.listen(db.engine, 'before_cursor_execute', on)
        try:
            res = L.locate_many([('output', 'b-%d' % i) for i in range(n)])
        finally:
            event.remove(db.engine, 'before_cursor_execute', on)
        return res, len(stmts)

    def test_query_count_does_not_grow_with_devices(self):
        res, q = self._count(3)
        self.assertEqual(len(res), 3)
        db.session.expunge_all()
        # 같은 DB 에 더 늘려서 다시 — 상수여야 한다.
        for i in range(3, 40):
            Output(unique_id='b-%d' % i, name='o%d' % i).save()
            _shape('bm-%d' % i, MARKER_TYPE, _pt(37.01 + i * 1e-4, 127.01))
            _bind('shape', 'bm-%d' % i, 'marker', dev='b-%d' % i)
        db.session.commit()
        stmts = []

        def on(conn, cur, stmt, *a):
            stmts.append(stmt)
        event.listen(db.engine, 'before_cursor_execute', on)
        try:
            res2 = L.locate_many([('output', 'b-%d' % i) for i in range(40)]
                                 + [('output', 'ghost')])
        finally:
            event.remove(db.engine, 'before_cursor_execute', on)
        self.assertEqual(len(res2), 41)
        self.assertIsNone(res2[('output', 'ghost')])
        self.assertTrue(all(res2[('output', 'b-%d' % i)].source == 'marker'
                            for i in range(40)))
        self.assertLessEqual(len(stmts), 20, [x.split(' FROM ')[-1][:60] for x in stmts[:40]])
        self.assertLessEqual(len(stmts), q + 4)


if __name__ == '__main__':
    unittest.main()
