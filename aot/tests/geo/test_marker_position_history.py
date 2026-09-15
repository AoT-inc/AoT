# coding=utf-8
"""마커 좌표 기간 기록 — 어느 경로로 바꿔도 이력이 끊기지 않는다.

좌표를 바꾸는 경로는 다섯 곳이다(설정 폼 좌표 이동·지도 편집기 저장·장치
교체·장치 삭제·도형 삭제). 그중 여럿이 ORM 이 아니라 대량 `Query.update()/
delete()` 라서, 경로마다 기록을 부르게 하면 새 경로 하나가 빠질 때 조용히
이력이 끊긴다. 여기서는 **모양별로** 한 번씩 고정한다: ORM 삽입·수정·삭제,
대량 수정·삭제, 그리고 리스너가 생기기 전부터 있던 마커의 첫 변경.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding, device_placement
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import GeoMarkerPosition, GeoShape, Input

MAP = 'map-pos-0001'


def _point(lng, lat):
    return {'type': 'Feature', 'properties': {},
            'geometry': {'type': 'Point', 'coordinates': [lng, lat]}}


class _Base(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _marker(self, lng=127.0, lat=35.0):
        shape = GeoShape(geo_id=MAP, type='aot_device', feature=_point(lng, lat))
        db.session.add(shape)
        db.session.commit()
        return shape.unique_id

    def _rows(self, uid):
        return (GeoMarkerPosition.query.filter_by(shape_uuid=uid)
                .order_by(GeoMarkerPosition.id).all())


class TestMarkerPositionHistory(_Base):

    def test_a_new_marker_opens_a_period(self):
        uid = self._marker()
        rows = self._rows(uid)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].lng, rows[0].lat), (127.0, 35.0))
        self.assertIsNotNone(rows[0].valid_from)
        self.assertIsNone(rows[0].valid_to)

    def test_moving_closes_the_old_period_and_opens_a_new_one(self):
        """좌표 이동 경로(`move_device_markers`)는 feature 를 통째로 새로 대입한다."""
        uid = self._marker()
        shape = GeoShape.query.filter_by(unique_id=uid).first()
        shape.feature = _point(127.5, 35.5)
        db.session.commit()

        old, new = self._rows(uid)
        self.assertEqual(old.ended_reason, 'moved')
        self.assertIsNotNone(old.valid_to)
        self.assertEqual((new.lng, new.lat), (127.5, 35.5))
        self.assertIsNone(new.valid_to)
        self.assertEqual(old.valid_to, new.valid_from)

    def test_touching_only_properties_adds_nothing(self):
        """장치 교체는 properties.unique_id 만 고친다 — 좌표가 그대로면 기간도 그대로다."""
        uid = self._marker()
        shape = GeoShape.query.filter_by(unique_id=uid).first()
        feat = _point(127.0, 35.0)
        feat['properties'] = {'unique_id': 'new-device'}
        shape.feature = feat
        db.session.commit()
        self.assertEqual(len(self._rows(uid)), 1)

    def test_orm_delete_closes_the_period_and_keeps_the_row(self):
        uid = self._marker()
        shape = GeoShape.query.filter_by(unique_id=uid).first()
        db.session.delete(shape)
        db.session.commit()

        rows = self._rows(uid)
        self.assertEqual(len(rows), 1, '도형이 지워지면서 위치 기록도 사라졌다')
        self.assertEqual(rows[0].ended_reason, 'removed')
        self.assertIsNotNone(rows[0].valid_to)

    def test_bulk_delete_closes_the_period(self):
        """`delete_shape`·지도 편집기 저장은 대량 `Query.delete()` 다."""
        uid = self._marker()
        GeoShape.query.filter_by(unique_id=uid).delete(synchronize_session=False)
        db.session.commit()
        self.assertEqual([r.ended_reason for r in self._rows(uid)], ['removed'])

    def test_bulk_update_of_the_geometry_moves_the_period(self):
        uid = self._marker()
        GeoShape.query.filter(GeoShape.unique_id == uid).update(
            {'feature': _point(128.0, 36.0)}, synchronize_session=False)
        db.session.commit()
        old, new = self._rows(uid)
        self.assertEqual(old.ended_reason, 'moved')
        self.assertEqual((new.lng, new.lat), (128.0, 36.0))

    def test_the_first_change_of_an_untracked_marker_keeps_its_old_position(self):
        """리스너 이전부터 있던 마커는 행이 없다. 처음 바뀌는 순간 옛 좌표를
        '처음부터' 인 닫힌 기간으로 먼저 남겨야, 백필 없이도 과거를 잃지 않는다."""
        uid = self._marker(127.0, 35.0)
        db.session.execute(GeoMarkerPosition.__table__.delete())
        db.session.commit()

        shape = GeoShape.query.filter_by(unique_id=uid).first()
        shape.feature = _point(127.9, 35.9)
        db.session.commit()

        old, new = self._rows(uid)
        self.assertIsNone(old.valid_from, '기록 이전 좌표는 처음부터로 남아야 한다')
        self.assertEqual((old.lng, old.lat), (127.0, 35.0))
        self.assertEqual(old.ended_reason, 'moved')
        self.assertEqual((new.lng, new.lat), (127.9, 35.9))

    def test_an_untracked_marker_deleted_in_bulk_is_still_recorded(self):
        uid = self._marker(127.0, 35.0)
        db.session.execute(GeoMarkerPosition.__table__.delete())
        db.session.commit()

        GeoShape.query.filter_by(unique_id=uid).delete(synchronize_session=False)
        db.session.commit()

        rows = self._rows(uid)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].valid_from)
        self.assertEqual(rows[0].ended_reason, 'removed')

    def test_zone_polygons_are_not_recorded(self):
        zone = GeoShape(geo_id=MAP, type='zone', feature={
            'type': 'Feature', 'properties': {},
            'geometry': {'type': 'Polygon', 'coordinates': [
                [[127, 35], [128, 35], [128, 36], [127, 35]]]}})
        db.session.add(zone)
        db.session.commit()
        self.assertEqual(GeoMarkerPosition.query.count(), 0)

    def test_a_rolled_back_move_leaves_no_trace(self):
        uid = self._marker()
        shape = GeoShape.query.filter_by(unique_id=uid).first()
        shape.feature = _point(129.0, 37.0)
        db.session.flush()
        db.session.rollback()
        rows = self._rows(uid)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].valid_to)


class TestMarkerPositionThroughPlacementGateway(_Base):
    """실제 좌표 이동 문(`device_placement.move_device_markers`)도 같은 기록을 남긴다."""

    def test_move_device_markers_records_the_move(self):
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        Input(unique_id='pos-dev-0001', name='온도계').save()
        uid = self._marker(127.0, 35.0)
        device_binding.bind('shape', uid, 'marker', 'input', 'pos-dev-0001',
                            commit=True)

        moved = device_placement.move_device_markers(
            'pos-dev-0001', 35.25, 127.25, commit=True)

        self.assertEqual(moved, 1)
        old, new = self._rows(uid)
        self.assertEqual(old.ended_reason, 'moved')
        self.assertEqual((new.lng, new.lat), (127.25, 35.25))


if __name__ == '__main__':
    unittest.main()
