# coding=utf-8
"""구획의 과거 출처 조합 — `plot_sources`.

구획은 센서 값을 갖지 않고, 조회할 때 구획 위치 × 기간 × 데이터 ID 를
조합한다. 여기서 지키는 것은 넷이다.

1. **떼어낸 센서도 그 기간에는 출처다.** 마커가 지워지고 장치·측정 정의가
   지워져도, 좌표 기간·바인딩 이력·제거 표시된 정의로 그 기간의 값을 부른다.
2. **"물리 센서 A → API 센서 → 물리 센서 B" 흐름이 한 기간에 모두 걸린다.**
   구역 후보가 가까운 순 세 개인 이유다.
3. **날짜마다 가장 좁은 출처를 쓴다.** 구획 안에 새 센서가 생겨도 그 전 기간은
   구역 센서가 채운다(`choose`).
4. **구역 후보는 가까운 순 최대 셋이다.** 전부 쓰면 한 구역의 구획들이 서로 같은
   문서가 된다.
"""
import unittest
from datetime import datetime

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding, plot_sources
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import (
    DeviceMeasurements, GeoBinding, GeoMarkerPosition, GeoShape, Input)

MAP = 'map-src-0001'
T_BEGIN = datetime(2026, 7, 1)
T0 = datetime(2026, 8, 1)
T1 = datetime(2026, 8, 20)
T2 = datetime(2026, 9, 1)
T3 = datetime(2026, 9, 10)


def _polygon(lng0, lat0, lng1, lat1):
    return {'type': 'Polygon', 'coordinates': [[
        [lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]]}


def _point(lng, lat):
    return {'type': 'Feature', 'properties': {},
            'geometry': {'type': 'Point', 'coordinates': [lng, lat]}}


class _Plot(object):
    geo_id = MAP
    facility_uuid = None
    bay_id = None
    unique_id = 'plot-src-0001'
    feature = {'type': 'Feature', 'properties': {},
               'geometry': _polygon(127.000, 35.000, 127.004, 35.004)}

    def has_own_geometry(self):
        return True


class _Base(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        device_binding.reset_fallback_log()
        zone = GeoShape(geo_id=MAP, type='zone', feature={
            'type': 'Feature', 'properties': {'name': '3-2'},
            'geometry': _polygon(126.99, 34.99, 127.03, 35.03)})
        db.session.add(zone)
        db.session.commit()
        self.zone_uuid = zone.unique_id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ── 준비 ──────────────────────────────────────────────────────────
    def _sensor(self, uid):
        Input(unique_id=uid, name=uid).save()
        DeviceMeasurements(device_id=uid, channel=0,
                           measurement='temperature', unit='C').save()
        return uid

    def _place(self, device_id, lng, lat, since=T_BEGIN):
        """마커를 찍고 바인딩한 뒤, 둘 다 `since` 부터였던 것으로 되돌린다."""
        shape = GeoShape(geo_id=MAP, type='aot_device', feature=_point(lng, lat))
        db.session.add(shape)
        db.session.commit()
        device_binding.bind('shape', shape.unique_id, 'marker', 'input',
                            device_id, commit=True)
        self._set_open_since(shape.unique_id, since)
        return shape.unique_id

    def _set_open_since(self, shape_uuid, since):
        for row in GeoMarkerPosition.query.filter_by(
                shape_uuid=shape_uuid, valid_to=None).all():
            row.valid_from = since
        for row in GeoBinding.query.filter_by(
                spatial_id=shape_uuid, valid_to=None).all():
            row.valid_from = since
        db.session.commit()

    def _set_closed_at(self, shape_uuid, when):
        """방금 닫힌 좌표·바인딩 기간을 `when` 에 닫힌 것으로 되돌린다."""
        rows = (GeoMarkerPosition.query.filter_by(shape_uuid=shape_uuid)
                .filter(GeoMarkerPosition.valid_to.isnot(None))
                .order_by(GeoMarkerPosition.id.desc()).all())
        if rows:
            rows[0].valid_to = when
        for row in GeoBinding.query.filter_by(spatial_id=shape_uuid).filter(
                GeoBinding.valid_to.isnot(None)).all():
            row.valid_to = when
        db.session.commit()

    def _remove(self, shape_uuid, when):
        shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
        db.session.delete(shape)
        db.session.commit()
        self._set_closed_at(shape_uuid, when)

    def _resolve(self, start=T0, end=T3):
        return plot_sources.resolve(_Plot(), start, end)

    @staticmethod
    def _by_device(sources):
        return {(s['device_id'], s['tier']): s for s in sources}


class TestReplacementFlow(_Base):
    """물리 센서 A 를 떼고, API 센서가 공백을 메우고, 물리 센서 B 를 단다."""

    def setUp(self):
        super().setUp()
        self._sensor('phys-a')
        self._sensor('api-w')
        self._sensor('phys-b')
        self.a = self._place('phys-a', 127.001, 35.001)
        self._remove(self.a, T1)
        self._place('api-w', 127.015, 35.015)
        self._place('phys-b', 127.001, 35.001, since=T2)

    def test_the_removed_sensor_is_still_a_source_for_its_period(self):
        src = self._by_device(self._resolve()['indoor'])
        self.assertIn(('phys-a', 'plot'), src, '떼어낸 센서가 과거 기간에서 사라졌다')
        self.assertEqual(src[('phys-a', 'plot')]['periods'], [(T0, T1)])

    def test_the_new_sensor_starts_when_it_was_installed(self):
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('phys-b', 'plot')]['periods'], [(T2, T3)])

    def test_the_api_sensor_covers_the_whole_period_as_the_zone_fallback(self):
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('api-w', 'zone')]['periods'], [(T0, T3)])
        self.assertEqual(src[('api-w', 'zone')]['rank'], 0)

    def test_a_deleted_device_still_has_its_channel_definition(self):
        """장치를 지우면 측정 정의는 제거 표시만 남는다 — 그걸로 과거 값을 부른다."""
        Input.query.filter_by(unique_id='phys-a').first().delete()
        for dm in DeviceMeasurements.query.filter_by(device_id='phys-a').all():
            dm.delete()
        sources = self._resolve()['indoor']
        pairs = plot_sources.channels_for(sources, {'temperature'})
        devices = {src['device_id'] for src, _dm in pairs}
        self.assertIn('phys-a', devices)


class TestZoneCandidates(_Base):

    def test_only_the_three_nearest_zone_sensors_are_candidates(self):
        for i, lng in enumerate((127.006, 127.010, 127.016, 127.024)):
            uid = self._sensor('zone-%d' % i)
            self._place(uid, lng, 35.002)
        zone = [s for s in self._resolve()['indoor'] if s['tier'] == 'zone']
        self.assertEqual([s['device_id'] for s in zone],
                         ['zone-0', 'zone-1', 'zone-2'])
        self.assertEqual([s['rank'] for s in zone], [0, 1, 2])

    def test_a_sensor_outside_the_zone_is_not_a_source(self):
        self._place(self._sensor('far'), 127.50, 35.50)
        self.assertEqual(self._resolve()['indoor'], [])


class TestPositionHistoryDecidesTheTier(_Base):

    def test_a_sensor_moved_out_of_the_plot_changes_tier_on_that_day(self):
        uid = self._place(self._sensor('mover'), 127.001, 35.001)
        shape = GeoShape.query.filter_by(unique_id=uid).first()
        shape.feature = _point(127.015, 35.015)
        db.session.commit()
        old, new = (GeoMarkerPosition.query.filter_by(shape_uuid=uid)
                    .order_by(GeoMarkerPosition.id).all())
        old.valid_to = T1
        new.valid_from = T1
        db.session.commit()

        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('mover', 'plot')]['periods'], [(T0, T1)])
        self.assertEqual(src[('mover', 'zone')]['periods'], [(T1, T3)])

    def test_a_marker_recorded_before_the_listener_counts_from_the_beginning(self):
        uid = self._place(self._sensor('old-timer'), 127.002, 35.002)
        GeoMarkerPosition.query.filter_by(shape_uuid=uid).delete()
        db.session.commit()
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('old-timer', 'plot')]['periods'], [(T0, T3)])

    def test_a_legacy_marker_without_any_binding_is_read_as_always_there(self):
        self._sensor('legacy-dev')
        shape = GeoShape(geo_id=MAP, type='aot_device', device_id='legacy-dev',
                         feature=_point(127.002, 35.002))
        db.session.add(shape)
        db.session.commit()
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('legacy-dev', 'plot')]['periods'], [(T0, T3)])


class TestUnrecordedPastPlacement(_Base):
    """좌표 기록이 생기기 전에 지워진 마커 — 그 장치의 다음 자리로 읽는다.

    실측(2026-09-15): 온습도 센서 셋의 마커가 9/12 에 지워지고 9/13 에 다시
    찍혔다. 옛 마커 좌표는 기록 이전에 사라져, 그대로 두면 8/8~9/12 가 조회에서
    통째로 빠진다.
    """

    def _pre_listener_marker(self, device_id, lng, lat, since, until):
        """리스너 이전에 쓰이다 지워진 마커를 흉내 낸다 — 좌표 기록 없이 사라진다."""
        shape = GeoShape(geo_id=MAP, type='aot_device', feature=_point(lng, lat))
        db.session.add(shape)
        db.session.commit()
        uid = shape.unique_id
        device_binding.bind('shape', uid, 'marker', 'input', device_id,
                            commit=True)
        pos = GeoMarkerPosition.__table__
        db.session.execute(pos.delete().where(pos.c.shape_uuid == uid))
        shapes = GeoShape.__table__
        db.session.execute(shapes.delete().where(shapes.c.unique_id == uid))
        db.session.commit()
        for row in GeoBinding.query.filter_by(spatial_id=uid).all():
            row.valid_from, row.valid_to = since, until
            row.ended_reason = row.ended_reason or 'unbound'
        db.session.commit()

    def test_the_lost_period_is_read_at_the_next_known_position(self):
        self._sensor('re-placed')
        self._pre_listener_marker('re-placed', 127.020, 35.020, T_BEGIN, T1)
        self._place('re-placed', 127.001, 35.001, since=T2)
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('re-placed', 'plot')]['periods'],
                         [(T0, T1), (T2, T3)])
        self.assertNotIn(('re-placed', 'zone'), src,
                         '모르는 옛 좌표를 지어내 다른 층으로 넣었다')

    def test_a_recorded_removal_is_not_guessed(self):
        """좌표 기록이 남은 제거는 추측하지 않는다 — 기록이 정본이다."""
        self._sensor('moved-in')
        first = self._place('moved-in', 127.015, 35.015)
        self._remove(first, T1)
        self._place('moved-in', 127.001, 35.001, since=T2)
        src = self._by_device(self._resolve()['indoor'])
        self.assertEqual(src[('moved-in', 'zone')]['periods'], [(T0, T1)])
        self.assertEqual(src[('moved-in', 'plot')]['periods'], [(T2, T3)])


class TestBindingsThatPredateTheHistory(_Base):
    """바인딩 표를 처음 채운 백필 행의 시작 시각은 설치일이 아니다.

    실측(2026-09-15): 모든 마커 바인딩이 8/8 04:29:17 에 시작해, 6/15 에 심은
    구획의 GDD 가 8/7 까지를 통째로 잃었다(92일 중 35일).
    """

    def test_the_earliest_binding_is_read_as_always_there(self):
        early = datetime(2026, 6, 15)
        uid = self._place(self._sensor('backfilled'), 127.002, 35.002,
                          since=datetime(2026, 8, 8))
        # 백필 행이 가리키는 마커는 좌표 기록 이전부터 있던 마커다.
        GeoMarkerPosition.query.filter_by(shape_uuid=uid).delete()
        db.session.commit()
        self._place(self._sensor('installed-later'), 127.003, 35.003,
                    since=datetime(2026, 9, 1))
        src = self._by_device(self._resolve(start=early)['indoor'])
        self.assertEqual(src[('backfilled', 'plot')]['periods'], [(early, T3)])
        self.assertEqual(src[('installed-later', 'plot')]['periods'],
                         [(datetime(2026, 9, 1), T3)],
                         '나중에 단 센서까지 처음부터로 읽으면 안 된다')


class TestOutdoorHistory(_Base):

    def test_a_replaced_weather_station_keeps_its_period(self):
        self._sensor('station-1')
        self._sensor('station-2')
        first = device_binding.bind('weather', self.zone_uuid, 'station',
                                    'input', 'station-1', commit=True)
        device_binding.unbind(first.unique_id, 'unbound', commit=True)
        device_binding.bind('weather', self.zone_uuid, 'station', 'input',
                            'station-2', commit=True)
        rows = (GeoBinding.query.filter_by(spatial_id=self.zone_uuid)
                .order_by(GeoBinding.id).all())
        rows[0].valid_from, rows[0].valid_to = T_BEGIN, T1
        rows[1].valid_from = T1
        db.session.commit()

        out = {s['device_id']: s for s in self._resolve()['outdoor']}
        self.assertEqual(out['station-1']['periods'], [(T0, T1)])
        self.assertEqual(out['station-2']['periods'], [(T1, T3)])
        self.assertEqual(out['station-1']['scope'], 'outdoor')


class TestChoose(unittest.TestCase):

    @staticmethod
    def _c(dev, tier, rank=0, data=True):
        return {'device_id': dev, 'tier': tier, 'rank': rank, 'data': data}

    def _pick(self, cands):
        return [c['device_id'] for c in
                plot_sources.choose(cands, lambda c: c['data'])]

    def test_the_plot_sensor_wins_on_a_day_it_has_data(self):
        self.assertEqual(self._pick([self._c('zone-a', 'zone'),
                                     self._c('plot-b', 'plot')]), ['plot-b'])

    def test_the_zone_fills_a_day_before_the_plot_sensor_existed(self):
        """구획 안에 새 센서가 생긴 날 이전 — 그 센서는 그날 값이 없다."""
        self.assertEqual(self._pick([self._c('plot-new', 'plot', data=False),
                                     self._c('zone-old', 'zone')]), ['zone-old'])

    def test_only_the_nearest_zone_candidate_with_data_is_used(self):
        self.assertEqual(self._pick([self._c('far', 'zone', rank=2),
                                     self._c('near', 'zone', rank=0, data=False),
                                     self._c('mid', 'zone', rank=1)]), ['mid'])

    def test_every_sensor_in_the_plot_is_kept(self):
        """서로 다른 실제 설치를 하나로 접지 않는다."""
        self.assertEqual(sorted(self._pick([self._c('p1', 'plot'),
                                            self._c('p2', 'plot')])),
                         ['p1', 'p2'])

    def test_a_day_without_any_data_keeps_the_narrowest_empty_source(self):
        self.assertEqual(self._pick([self._c('zone-a', 'zone', data=False),
                                     self._c('plot-b', 'plot', data=False)]),
                         ['plot-b'])

    def test_pick_rows_leaves_outdoor_and_untiered_rows_alone(self):
        rows = [{'device_id': 'w', 'measurement': 'temperature',
                 'scope': 'outdoor', 'tier': 'weather', 'samples': 3},
                {'device_id': 'z', 'measurement': 'temperature',
                 'scope': 'indoor', 'samples': 3},
                {'device_id': 'p', 'measurement': 'temperature',
                 'scope': 'indoor', 'tier': 'plot', 'rank': 0, 'samples': 0},
                {'device_id': 'q', 'measurement': 'temperature',
                 'scope': 'indoor', 'tier': 'zone', 'rank': 0, 'samples': 5}]
        kept = {r['device_id'] for r in plot_sources.pick_rows(rows)}
        self.assertEqual(kept, {'w', 'z', 'q'})


if __name__ == '__main__':
    unittest.main()
