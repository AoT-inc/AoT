# coding=utf-8
"""측정 정의는 지우지 않고 '제거됨' 으로 표시한다.

떼어낸 센서의 과거 값은 Influx 에 장치 id·채널 태그로 남는다. 정의 행을
지우면 그 값을 어떤 채널·단위로 불러야 하는지가 사라져, 구획이 "그 기간 그
자리의 센서" 값을 다시 적용할 수 없다. 여기서 지키는 것은 셋이다.

1. 어느 경로로 지워도(ORM 삭제·CRUDMixin.delete) 행은 남고 표시만 된다.
2. 표시된 행은 평소 조회에서 보이지 않는다 — 조회 파일이 64곳이라 한 곳이라도
   빠지면 떼어낸 센서가 목록·계산에 되살아난다.
3. 과거 조회만 `include_removed_measurements` 로 연다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements
from aot.databases.models.measurement import INCLUDE_REMOVED_MEASUREMENTS

DEV = 'retire-device-0001'


class TestMeasurementRetire(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        self.ch0 = DeviceMeasurements(device_id=DEV, channel=0,
                                      measurement='temperature', unit='C').save()
        self.ch1 = DeviceMeasurements(device_id=DEV, channel=1,
                                      measurement='humidity', unit='percent').save()
        self.ch1_uid = self.ch1.unique_id

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _visible_channels(self):
        return sorted(m.channel for m in DeviceMeasurements.query.filter_by(
            device_id=DEV).all())

    def _all_rows(self):
        return DeviceMeasurements.query.execution_options(
            **{INCLUDE_REMOVED_MEASUREMENTS: True}).filter_by(device_id=DEV).all()

    def test_orm_delete_keeps_the_row_and_marks_it(self):
        db.session.delete(self.ch1)
        db.session.commit()

        self.assertEqual(self._visible_channels(), [0])
        rows = {m.unique_id: m for m in self._all_rows()}
        self.assertIn(self.ch1_uid, rows, '행이 실제로 지워졌다')
        self.assertIsNotNone(rows[self.ch1_uid].removed_at)

    def test_crud_mixin_delete_takes_the_same_path(self):
        self.ch1.delete()
        self.assertEqual(self._visible_channels(), [0])
        self.assertEqual(len(self._all_rows()), 2)

    def test_column_only_and_count_queries_hide_removed_rows(self):
        """조회 파일 대부분이 `with_entities`·`count` 를 쓴다 — 거기서 새면
        떼어낸 채널이 개수 판정에 되살아난다."""
        self.ch1.delete()
        chans = DeviceMeasurements.query.with_entities(
            DeviceMeasurements.channel).filter(
                DeviceMeasurements.device_id == DEV).all()
        self.assertEqual([c[0] for c in chans], [0])
        self.assertEqual(DeviceMeasurements.query.filter_by(
            device_id=DEV).count(), 1)
        self.assertIsNone(DeviceMeasurements.query.filter_by(
            unique_id=self.ch1_uid).first())

    def test_the_same_channel_can_be_added_again(self):
        """채널을 줄였다가 다시 늘리는 설정 변경이 막히면 안 된다."""
        self.ch1.delete()
        DeviceMeasurements(device_id=DEV, channel=1,
                           measurement='humidity', unit='percent').save()
        self.assertEqual(self._visible_channels(), [0, 1])
        self.assertEqual(len(self._all_rows()), 3)

    def test_a_removed_row_is_deleted_again_without_moving_its_mark(self):
        """이미 표시된 행을 다시 지워도 처음 제거 시각을 덮지 않는다."""
        self.ch1.delete()
        first = self._removed_at(self.ch1_uid)
        row = next(m for m in self._all_rows() if m.unique_id == self.ch1_uid)
        db.session.delete(row)
        db.session.commit()
        self.assertEqual(self._removed_at(self.ch1_uid), first)

    def _removed_at(self, uid):
        return next(m.removed_at for m in self._all_rows() if m.unique_id == uid)


if __name__ == '__main__':
    unittest.main()
