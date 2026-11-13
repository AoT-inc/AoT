# coding=utf-8
"""장치 위치 소비자 전환(L1b) — 마커만/구역만/레거시만/없음 → 폴백 basis.

timekit · device_membership · get_device_location · resolve_location_coords ·
forecast 후보 · 공간 트리가 전부 `device_location.locate` 한 곳을 읽는지 본다.
"""
import unittest
from datetime import datetime, timezone

import pytz
from sqlalchemy import event

from aot.aot_flask.extensions import db
from aot.space import device_membership as DM
from aot.aot_flask.geo.device_placement import MARKER_TYPE
from aot.databases.models import GeoMap, GeoShape, Input, Output
from aot.tests.geo.test_device_location import (DEV, MAP, _Base, _bind, _named,
                                                _poly, _pt, _shape)
from aot.utils import timekit as tk


def _out():
    return Output.query.filter_by(unique_id=DEV).first()


class TestTimekit(_Base):

    def setUp(self):
        super().setUp()
        self._orig = (tk._db_row, tk._system_coords, tk._system_tz_name)
        tk._db_row = lambda *a, **k: None
        tk._system_coords = lambda: (None, None)
        tk._system_tz_name = lambda: 'America/New_York'

    def tearDown(self):
        tk._db_row, tk._system_coords, tk._system_tz_name = self._orig
        super().tearDown()

    def test_marker_gives_device_basis(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        c = tk.resolve_coords(_out())
        self.assertEqual(tuple(c), (37.01, 127.01, tk.SOURCE_INHERITED))
        self.assertEqual(c.basis, 'device')

    def test_zone_only(self):
        _bind('shape', 'zone-1', 'area')
        c = tk.resolve_coords(_out())
        self.assertEqual(c.basis, 'device')
        self.assertAlmostEqual(c[0], 37.02, places=2)

    def test_legacy_column_coords_are_ignored(self):
        o = _out()
        o.latitude, o.longitude = 35.5, 129.5
        db.session.commit()
        c = tk.resolve_coords(o)
        self.assertEqual(c.basis, 'site')

    def test_unplaced_falls_back_to_site_basis(self):
        c = tk.resolve_coords(_out())
        self.assertEqual(c.basis, 'site')
        self.assertAlmostEqual(c[0], 37.05, delta=0.02)

    def test_nothing_anywhere_is_farm_fallback(self):
        GeoShape.query.delete()
        db.session.commit()
        c = tk.resolve_coords(_out())
        self.assertEqual((c[0], c[2], c.basis), (None, tk.SOURCE_UTC, 'none'))

    def test_row_tz_attrs_are_ignored_placement_wins(self):
        o = _out()
        o.timezone, o.tz_source = 'Asia/Kolkata', 'explicit'   # 컬럼은 폐지 — 속성이 있어도 무시
        tz, src = tk._device_tz(o)
        self.assertEqual((tz.zone, src), ('Asia/Seoul', tk.SOURCE_INHERITED))

    def test_tz_inherited_from_other_timezone_site_and_dst_boundary(self):
        GeoShape.query.filter_by(unique_id='site-1').first().timezone = 'America/New_York'
        db.session.commit()
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        tz, src = tk._device_tz(_out())
        self.assertEqual((tz.zone, src), ('America/New_York', tk.SOURCE_INHERITED))
        before = datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)   # EST 01:59
        after = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)     # EDT 03:00
        self.assertEqual(before.astimezone(tz).isoformat(), '2026-03-08T01:59:00-05:00')
        self.assertEqual(after.astimezone(tz).isoformat(), '2026-03-08T03:00:00-04:00')

    def test_no_placement_and_no_site_has_no_device_tz(self):
        GeoShape.query.delete()
        db.session.commit()
        self.assertIsNone(tk._device_tz(_out()))


class TestMembership(_Base):

    def test_marker_zone_and_maps(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        self.assertEqual(DM.zone_for_device(DEV, MAP).unique_id, 'zone-1')
        self.assertIsNone(DM.zone_for_device(DEV, 'other-map'))
        self.assertEqual(DM.maps_for_device(DEV), [MAP])
        self.assertEqual(DM.map_for_device(DEV), MAP)

    def test_zone_only_binding(self):
        _bind('shape', 'zone-1', 'area')
        self.assertEqual(DM.zone_for_device(DEV, MAP).unique_id, 'zone-1')

    def test_unplaced_device_has_no_zone_or_map(self):
        # 대지 폴백(basis='site')은 "배치됨" 이 아니다.
        self.assertIsNone(DM.zone_for_device(DEV, MAP))
        self.assertEqual(DM.maps_for_device(DEV), [])
        self.assertIsNone(DM.map_for_device(DEV))

    def test_second_map_marker_is_kept_after_primary(self):
        GeoMap(unique_id='map-2', name='둘째').save()
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _shape('mk-2', MARKER_TYPE, _pt(1, 1), geo_id='map-2')
        _bind('shape', 'mk-1', 'marker', ch='0')
        _bind('shape', 'mk-2', 'marker', ch='1')
        self.assertEqual(sorted(DM.maps_for_device(DEV)), sorted([MAP, 'map-2']))


class TestTools(_Base):

    def _loc(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        return S.get_device_location(device_id=DEV)

    def test_location_basis_device_site_none(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        r = self._loc()
        self.assertEqual((r['lat'], r['lng'], r['location_basis']), (37.01, 127.01, 'device'))

        from aot.databases.models import GeoBinding
        GeoBinding.query.delete()
        GeoShape.query.filter_by(unique_id='mk-1').delete()
        db.session.commit()
        r = self._loc()
        self.assertEqual(r['location_basis'], 'site')
        self.assertAlmostEqual(r['lat'], 37.05, delta=0.02)

        GeoShape.query.delete()
        db.session.commit()
        r = self._loc()
        self.assertEqual((r['lat'], r['lng'], r['location_basis']), (None, None, 'none'))

    def test_resolve_location_coords_uses_resolver(self):
        from aot.utils.device_tz import resolve_location_coords
        _shape('mk-old', MARKER_TYPE, _pt(37.03, 127.03))
        _bind('shape', 'mk-old', 'marker')
        self.assertEqual(tuple(resolve_location_coords(DEV)), (37.03, 127.03))

    def test_forecast_candidates_distance_from_placement(self):
        from aot.space import forecast_series as FS
        from aot.utils import inputs as I
        orig = (I.forecast_time_input_drivers, I.daily_forecast_drivers)
        I.forecast_time_input_drivers = lambda: {'OPEN_METEO_FORECAST'}
        I.daily_forecast_drivers = lambda: set()
        try:
            Input(unique_id='fc-1', name='예보', device='OPEN_METEO_FORECAST',
                  is_activated=True).save()
            _shape('mk-1', MARKER_TYPE, _pt(37.06, 127.05))
            _bind('shape', 'mk-1', 'marker', dev='fc-1', dkind='input')
            out = FS.forecast_candidates('site-1')
        finally:
            I.forecast_time_input_drivers, I.daily_forecast_drivers = orig
        self.assertEqual(len(out), 1)
        self.assertIsNotNone(out[0]['distance_km'])
        self.assertLess(out[0]['distance_km'], 5)


def _flatten(nodes):
    for n in nodes or []:
        yield n
        for c in _flatten(n.get('children')):
            yield c


class TestSpatialTree(_Base):

    def _tree_device_ids(self):
        import aot.ai.services.ai_context_service as ACS
        ACS._SPATIAL_CACHE = None
        tree = ACS.AIContextService.get_spatial_hierarchy(tier='standard')
        return {n.get('device_id') for n in _flatten(tree) if n.get('device_id')}

    def test_marker_binding_only(self):
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        self.assertIn(DEV, self._tree_device_ids())

    def test_zone_area_binding_only(self):
        _shape('ar-1', 'device', _poly(37.0, 127.0, 37.02, 127.02))
        _bind('shape', 'ar-1', 'area')
        self.assertIn(DEV, self._tree_device_ids())

    def test_no_placement_has_no_device_node(self):
        self.assertNotIn(DEV, self._tree_device_ids())


class TestResolvePoint(_Base):

    def test_device_marker_then_site_fallback_then_none(self):
        from aot.utils.geo_distance import resolve_point
        _shape('mk-1', MARKER_TYPE, _pt(37.01, 127.01))
        _bind('shape', 'mk-1', 'marker')
        p = resolve_point(DEV)
        self.assertEqual((p['lat'], p['lng'], p['target_type']), (37.01, 127.01, 'output'))

        from aot.databases.models import GeoBinding
        GeoBinding.query.delete()
        GeoShape.query.filter_by(unique_id='mk-1').delete()
        db.session.commit()
        p = resolve_point(DEV)            # 장치 자리는 없고 대지 폴백만
        self.assertAlmostEqual(p['lat'], 37.05, delta=0.02)

        GeoShape.query.delete()
        db.session.commit()
        self.assertIsNone(resolve_point(DEV))

    def test_shape_target_wins_over_device_step(self):
        from aot.utils.geo_distance import resolve_point
        p = resolve_point('zone-1')
        self.assertEqual(p['target_type'], 'zone')


class TestSpatialTreeQueries(_Base):

    def test_devices_for_shapes_is_constant_queries(self):
        from aot.space.device_binding import devices_for_shapes
        counts = []
        for n in (2, 12):
            shapes = []
            for i in range(n):
                shapes.append(_shape('m%d-%d' % (n, i), MARKER_TYPE, _pt(37.01, 127.01)))
                _bind('shape', 'm%d-%d' % (n, i), 'marker', dev='d%d-%d' % (n, i))
            shapes = GeoShape.query.filter(GeoShape.unique_id.like('m%d-%%' % n)).all()
            for sh in shapes:
                sh.unique_id, sh.type          # 속성 로드 — 질의 수에서 제외
            q = []

            def on(conn, cur, stmt, params, ctx, many):
                q.append(stmt)
            event.listen(db.engine, 'before_cursor_execute', on)
            try:
                got = devices_for_shapes(shapes)
            finally:
                event.remove(db.engine, 'before_cursor_execute', on)
            self.assertEqual(len(got), n)
            counts.append(len(q))
        self.assertEqual(counts[0], counts[1])      # N+1 없음

    def test_locate_many_is_constant_queries(self):
        from aot.space.device_location import locate_many
        res = []
        for n in (2, 10):
            pairs = []
            for i in range(n):
                uid = 'o%d-%d' % (n, i)
                Output(unique_id=uid, name=uid).save()
                _shape('mk%s' % uid, MARKER_TYPE, _pt(37.01, 127.01))
                _bind('shape', 'mk%s' % uid, 'marker', dev=uid)
                pairs.append(('output', uid))
            q = []

            def on(conn, cur, stmt, params, ctx, many):
                q.append(stmt)
            event.listen(db.engine, 'before_cursor_execute', on)
            try:
                locate_many(pairs)
            finally:
                event.remove(db.engine, 'before_cursor_execute', on)
            res.append(len(q))
        self.assertEqual(res[0], res[1])


if __name__ == '__main__':
    unittest.main()
