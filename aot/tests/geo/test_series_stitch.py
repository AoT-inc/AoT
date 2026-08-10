# coding=utf-8
"""장치 교체를 관통하는 시계열 접합 — `utils_series_stitch`.

InfluxDB 는 값을 장치 uuid 로 태깅하므로 장치를 갈면 그래프가 그 시점에서
끊긴다. 사람이 보고 싶은 것은 "이 센서의 값"이 아니라 **"이 자리의 값"** 이다.
과거 데이터를 새 uuid 로 다시 쓰는 방법은 되돌릴 수 없고 "그때 실제로 측정한
기계"라는 사실을 지우므로 쓰지 않는다 — 조회 시점에 이어 붙인다.

여기서 지키는 것은 넷이다.

1. **접합할 이력이 없으면 접합하지 않는다.** 빈 목록을 돌려주고 호출자가 기존
   단일 장치 경로를 그대로 타게 한다 — 같은 결과를 두 코드 경로로 만들지 않는다.
2. **대응 측정값을 못 찾은 구간을 조용히 빼지 않는다.** 말없이 건너뛰면
   그래프가 "그 기간에는 아무 일도 없었다"고 거짓말한다.
3. **자리 선택이 재현된다.** 한 장치가 여러 자리를 맡는 것은 정상이라
   (위치 마커 + 담당 구역) 아무거나 집으면 실행마다 다른 자리를 기준으로
   접합될 수 있다.
4. **그룹핑 간격은 전체 범위 기준이다.** 구간마다 따로 계산하면 짧은 구간이
   촘촘해지고 긴 구간이 성글어져, 사람이 그 계단을 데이터의 변화로 읽는다.

InfluxDB 는 이 테스트에 없다. 값 자체가 아니라 **어느 장치에게 어떤 간격으로
물었는가**가 여기서 지킬 계약이므로 조회를 대역으로 잡고 그 인자를 본다.
"""
import datetime
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding as B
from aot.aot_flask.utils import utils_series_stitch as S
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import DeviceMeasurements, GeoShape, Input


ZONE = 'zone-uuid-0001'
OLD = 'sensor-old-0001'
NEW = 'sensor-new-0002'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class _Base(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()
        B.reset_fallback_log()

        Input(unique_id=OLD, name='옛 온습도계').save()
        Input(unique_id=NEW, name='새 온습도계').save()
        GeoShape(unique_id=ZONE, geo_id='map-1', type='device',
                 feature={'type': 'Feature', 'properties': {}}).save()

        self.m_old = self._measurement(OLD, 0, 'temperature', 'C')
        self.m_new = self._measurement(NEW, 0, 'temperature', 'C')

        # 조회 대역 — 어느 장치에게 어떤 인자로 물었는지 기록한다.
        self.queries = []
        self._orig_seg = S._segment_series

        def fake(segment, start, end, group_sec):
            self.queries.append({'device_id': segment['device_id'],
                                 'measurement_id': segment['measurement_id'],
                                 'group_sec': group_sec})
            return [(1000.0 + len(self.queries), 1.0)]

        S._segment_series = fake

    def tearDown(self):
        S._segment_series = self._orig_seg
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _measurement(self, device_id, channel, measurement, unit):
        m = DeviceMeasurements(device_id=device_id, channel=channel,
                               measurement=measurement, unit=unit)
        m.save()
        return m.unique_id

    def _range(self):
        end = datetime.datetime.utcnow()
        return end - datetime.timedelta(days=7), end

    def _swap(self):
        """옛 장치 → 새 장치 교체 이력을 만든다."""
        B.bind('shape', ZONE, 'area', 'input', OLD, commit=True)
        B.rebind('shape', ZONE, 'area', 'input', NEW, commit=True)


class TestSegments(_Base):

    def test_a_single_segment_is_not_stitched(self):
        """접합할 것이 없으면 빈 목록 — 호출자가 기존 경로를 탄다."""
        B.bind('shape', ZONE, 'area', 'input', NEW, commit=True)
        self.assertEqual(S.slot_segments(NEW, self.m_new), [])

    def test_a_device_with_no_binding_is_not_stitched(self):
        self.assertEqual(S.slot_segments(NEW, self.m_new), [])

    def test_a_swap_produces_two_segments_in_time_order(self):
        self._swap()
        segs = S.slot_segments(NEW, self.m_new)
        self.assertEqual([s['device_id'] for s in segs], [OLD, NEW])
        self.assertIsNotNone(segs[0]['valid_to'])
        self.assertIsNone(segs[1]['valid_to'])

    def test_the_matching_measurement_of_the_old_device_is_found(self):
        """같은 자리를 맡은 온습도계 둘은 모델이 달라도 온도는 온도다."""
        self._swap()
        segs = S.slot_segments(NEW, self.m_new)
        self.assertEqual(segs[0]['measurement_id'], self.m_old)
        self.assertTrue(segs[0]['has_data'])

    def test_a_segment_without_a_counterpart_is_reported_not_dropped(self):
        """조용히 빼면 그래프가 '그 기간엔 아무 일도 없었다'고 거짓말한다."""
        DeviceMeasurements.query.filter(
            DeviceMeasurements.unique_id == self.m_old).delete()
        db.session.commit()
        self._swap()

        segs = S.slot_segments(NEW, self.m_new)
        self.assertEqual(len(segs), 2)
        self.assertFalse(segs[0]['has_data'])
        self.assertIsNone(segs[0]['measurement_id'])

    def test_the_channel_decides_between_several_candidates(self):
        """채널 번호는 최초 배정 후 재배정하지 않는 불변값이라, 다채널 장치에서
        어느 구멍이었나를 말해주는 유일한 단서다."""
        m_old_ch1 = self._measurement(OLD, 1, 'temperature', 'C')
        m_new_ch1 = self._measurement(NEW, 1, 'temperature', 'C')
        self._swap()

        segs = S.slot_segments(NEW, m_new_ch1)
        self.assertEqual(segs[0]['measurement_id'], m_old_ch1)

    def test_a_measurement_pinned_on_the_binding_wins(self):
        other = self._measurement(OLD, 3, 'humidity', 'percent')
        B.bind('shape', ZONE, 'area', 'input', OLD, measurement_id=other,
               commit=True)
        B.rebind('shape', ZONE, 'area', 'input', NEW, commit=True)

        segs = S.slot_segments(NEW, self.m_new)
        self.assertEqual(segs[0]['measurement_id'], other)


class TestSlotChoiceIsReproducible(_Base):
    """한 장치가 여러 자리를 맡는 것은 정상이다(위치 마커 + 담당 구역)."""

    def test_the_area_slot_wins_over_the_marker(self):
        marker = 'marker-uuid-0001'
        GeoShape(unique_id=marker, geo_id='map-1', type='aot_device',
                 feature={'type': 'Feature', 'properties': {}}).save()
        self._swap()
        B.bind('shape', marker, 'marker', 'input', NEW, commit=True)

        self.assertEqual(S._slot_of(NEW), ('shape', ZONE, 'area'))

    def test_a_marker_only_device_still_resolves(self):
        marker = 'marker-uuid-0002'
        GeoShape(unique_id=marker, geo_id='map-1', type='aot_device',
                 feature={'type': 'Feature', 'properties': {}}).save()
        B.bind('shape', marker, 'marker', 'input', NEW, commit=True)

        self.assertEqual(S._slot_of(NEW), ('shape', marker, 'marker'))


class TestStitchedSeries(_Base):

    def test_every_segment_is_asked_of_its_own_device(self):
        self._swap()
        start, end = self._range()

        points, segs = S.stitched_series(NEW, self.m_new, start, end)

        self.assertEqual([q['device_id'] for q in self.queries], [OLD, NEW])
        self.assertEqual(len(segs), 2)
        self.assertEqual(len(points), 2)

    def test_the_grouping_interval_is_the_same_for_every_segment(self):
        """구간마다 따로 계산하면 점 밀도가 교체 시점마다 튀고, 사람은 그 계단을
        데이터의 변화로 읽는다."""
        self._swap()
        start, end = self._range()

        S.stitched_series(NEW, self.m_new, start, end)

        intervals = {q['group_sec'] for q in self.queries}
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals.pop(), int((end - start).total_seconds() / 700))

    def test_points_come_back_in_time_order(self):
        self._swap()
        start, end = self._range()
        points, _ = S.stitched_series(NEW, self.m_new, start, end)
        self.assertEqual(points, sorted(points, key=lambda p: p[0]))

    def test_a_segment_without_a_counterpart_is_never_queried(self):
        DeviceMeasurements.query.filter(
            DeviceMeasurements.unique_id == self.m_old).delete()
        db.session.commit()
        self._swap()
        start, end = self._range()

        _points, segs = S.stitched_series(NEW, self.m_new, start, end)

        self.assertEqual([q['device_id'] for q in self.queries], [NEW])
        self.assertEqual(segs[0]['points'], 0)
        self.assertFalse(segs[0]['has_data'])

    def test_nothing_to_stitch_returns_none_so_the_caller_falls_back(self):
        B.bind('shape', ZONE, 'area', 'input', NEW, commit=True)
        start, end = self._range()

        points, segs = S.stitched_series(NEW, self.m_new, start, end)

        self.assertIsNone(points)
        self.assertEqual(segs, [])
        self.assertEqual(self.queries, [])


class TestHardwareEvents(_Base):
    """그래프 마커 — 교체를 말해주는 두 출처를 한 줄에 모은다.

    하나만 보면 절반을 놓친다: 같은 모델로 갈아끼운 교체는 uuid 가 그대로라
    바인딩에 흔적이 없고(그쪽 기록은 maintenance 노트뿐), 다른 장치로 옮긴
    교체는 노트에 없다.
    """

    def _note(self, device_id, name, body, when):
        from aot.databases.models import Notes
        n = Notes(name=name, note=body, target_id=device_id,
                  target_type='input', category='maintenance', date_time=when)
        n.save()
        return n

    def test_nothing_happened_means_no_markers(self):
        B.bind('shape', ZONE, 'area', 'input', NEW, commit=True)
        self.assertEqual(S.hardware_events(NEW, self.m_new), [])

    def test_a_rebind_becomes_a_marker(self):
        self._swap()
        events = S.hardware_events(NEW, self.m_new)
        self.assertEqual([e['kind'] for e in events], ['rebind'])
        self.assertEqual(events[0]['label'], '새 온습도계')

    def test_the_first_segment_is_not_a_replacement(self):
        """처음 설치한 것을 '교체'로 찍으면 모든 장치에 가짜 교체가 하나씩 생긴다."""
        self._swap()
        events = S.hardware_events(NEW, self.m_new)
        self.assertEqual(len(events), 1)

    def test_a_maintenance_note_becomes_a_marker(self):
        """접속정보만 갈아끼운 교체는 바인딩에 흔적이 없다 — 이 노트가 유일한
        기록이고, 없으면 그래프의 단차를 설명할 방법이 사라진다."""
        B.bind('shape', ZONE, 'area', 'input', NEW, commit=True)
        self._note(NEW, '교체: 새 온습도계', 'DevEUI: aaaa → bbbb',
                   datetime.datetime(2026, 8, 1, 9, 0, 0))

        events = S.hardware_events(NEW, self.m_new)
        self.assertEqual([e['kind'] for e in events], ['swap'])
        self.assertIn('bbbb', events[0]['text'])

    def test_notes_of_earlier_devices_are_included(self):
        """교체 전 장치에 남은 갱신도 이 그래프가 설명해야 할 사건이다."""
        self._swap()
        self._note(OLD, '교체: 옛 온습도계', 'DevEUI 교체',
                   datetime.datetime(2026, 7, 1, 9, 0, 0))

        events = S.hardware_events(NEW, self.m_new)
        self.assertEqual(sorted(e['kind'] for e in events), ['rebind', 'swap'])

    def test_events_come_back_in_time_order(self):
        self._swap()
        self._note(OLD, 'a', '', datetime.datetime(2026, 7, 1))
        self._note(NEW, 'b', '', datetime.datetime(2020, 1, 1))

        events = S.hardware_events(NEW, self.m_new)
        self.assertEqual([e['time'] for e in events],
                         sorted(e['time'] for e in events))

    def test_other_note_categories_are_not_markers(self):
        """일반 노트까지 찍으면 이 줄은 곧 배경 소음이 되고 아무도 안 본다."""
        from aot.databases.models import Notes
        B.bind('shape', ZONE, 'area', 'input', NEW, commit=True)
        Notes(name='관찰', note='잎이 노랗다', target_id=NEW,
              target_type='input', category='observation',
              date_time=datetime.datetime(2026, 8, 1)).save()

        self.assertEqual(S.hardware_events(NEW, self.m_new), [])


class TestPayload(_Base):

    def test_segments_serialise_for_the_chart(self):
        self._swap()
        start, end = self._range()
        _points, segs = S.stitched_series(NEW, self.m_new, start, end)

        payload = S.segments_payload(segs)
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]['device_name'], '옛 온습도계')
        self.assertIsNotNone(payload[0]['to'])
        self.assertIsNone(payload[1]['to'])


if __name__ == '__main__':
    unittest.main()
