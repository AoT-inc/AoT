# coding=utf-8
"""장치 단위 교체 — `device_binding.rebind_device()`.

`rebind()` 는 슬롯 하나만 다룬다. 현장에서 "이 장치를 저 장치로 갈았다"는 말은
그 장치가 맡던 자리 전부를 뜻하므로, 그 쓸기가 여기 있다. 설계 문서
`geo-device-binding.md` 「결정」 절의 3건이 그대로 이 파일의 검사다.

1. **채널 축소**(8채널 → 4채널)는 거부가 아니라 미배정 전환이다. 거부하면
   정당한 교체가 막혀 사람이 다시 "새로 만들고 옛것 삭제"로 돌아가고, 그대로
   두면 "장치가 붙어 있는데 아무 명령도 안 가는" 자리가 남는다.
2. **마커 충돌**은 쓰기 전에 거부한다. 옛 마커를 자동으로 지우거나 옮기지
   않는다 — 좌표는 측량 결과이고 둘 중 무엇이 맞는지는 사람만 안다.
3. **시설 슬롯은 옮기지 않는다.** 시설 편집기가 정본이라, 여기서 만든 바인딩은
   다음 시설 저장이 지운다(실측). 조용히 건너뛰지 않고 이유와 함께 돌려준다.

여기에 하나 더: **마커의 레거시 `device_id` 컬럼도 함께 옮겨야 한다.**
`place_device`/`unplace_device` 가 마커를 그 컬럼으로 찾기 때문에, 바인딩만
옮기면 새 장치를 배치할 때 마커가 하나 더 생기고 옛 장치를 치울 때 새 장치의
마커가 지워진다. `binding-drift` 는 "레거시에만 있는 연결"만 보므로 이
어긋남을 못 잡는다 — 그래서 테스트가 본다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding as B
from aot.databases.geo_integrity_ddl import apply_binding
from aot.databases.models import (
    GeoBinding, GeoMap, GeoShape, Output, OutputChannel)


MAP_A = 'map-uuid-aaaa'
MAP_B = 'map-uuid-bbbb'
OLD = 'dev-old-0001'
NEW = 'dev-new-0002'


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

        GeoMap(unique_id=MAP_A, name='지도 A').save()
        GeoMap(unique_id=MAP_B, name='지도 B').save()
        Output(unique_id=OLD, name='옛 릴레이').save()
        Output(unique_id=NEW, name='새 릴레이').save()
        self._channels(NEW, ['0', '1', '2', '3'])
        self._channels(OLD, ['0', '1', '2', '3', '4', '5', '6', '7'])

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _channels(self, output_id, channels):
        for ch in channels:
            OutputChannel(output_id=output_id, channel=int(ch)).save()

    def _zone(self, uid, device_id=None, channel='0'):
        GeoShape(unique_id=uid, geo_id=MAP_A, type='device',
                 device_id=device_id, channel_id=channel,
                 feature={'type': 'Feature', 'properties': {'name': uid}}).save()
        return uid

    def _marker(self, uid, device_id, channel='0', geo_id=MAP_A):
        GeoShape(unique_id=uid, geo_id=geo_id, type='aot_device',
                 device_id=device_id, channel_id=channel,
                 feature={'type': 'Feature',
                          'properties': {'name': uid,
                                         'unique_id': device_id}}).save()
        return uid

    def _shape(self, uid):
        return GeoShape.query.filter(GeoShape.unique_id == uid).first()


class TestSweep(_Base):

    def test_every_map_slot_moves(self):
        self._zone('zone-1')
        self._zone('zone-2')
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)
        B.bind('shape', 'zone-2', 'area', 'output', OLD, channel_id='1',
               commit=True)

        result = B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual(len(result['moved']), 2)
        self.assertEqual(B.current_one('shape', 'zone-1', role='area').device_id,
                         NEW)
        self.assertEqual(
            B.current_one('shape', 'zone-2', role='area', channel_id='1').device_id,
            NEW)

    def test_the_old_binding_is_kept_as_history(self):
        """이력이 남지 않으면 교체를 관통하는 시계열 접합의 근거가 사라진다."""
        self._zone('zone-1')
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)

        B.rebind_device(OLD, NEW, commit=True)

        past = [b for b in B.history('shape', 'zone-1', role='area')
                if b.valid_to is not None]
        self.assertEqual(len(past), 1)
        self.assertEqual(past[0].device_id, OLD)
        self.assertEqual(past[0].ended_reason, 'replaced')

    def test_no_bindings_is_refused(self):
        with self.assertRaises(B.BindingNotFound):
            B.rebind_device(OLD, NEW, commit=True)

    def test_same_device_is_refused(self):
        with self.assertRaises(B.BindingError):
            B.rebind_device(OLD, OLD, commit=True)

    def test_unknown_new_device_is_refused(self):
        self._zone('zone-1')
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)
        with self.assertRaises(B.BindingError):
            B.rebind_device(OLD, 'nope-nope-nope', commit=True)


class TestChannelReduction(_Base):
    """결정 1 — 매핑 불가 채널은 미배정 전환 + 경고."""

    def test_channels_the_new_device_lacks_become_unassigned(self):
        self._zone('zone-1')
        self._zone('zone-5')
        B.bind('shape', 'zone-1', 'area', 'output', OLD, channel_id='1',
               commit=True)
        B.bind('shape', 'zone-5', 'area', 'output', OLD, channel_id='5',
               commit=True)

        result = B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual([m['channel_id'] for m in result['moved']], ['1'])
        self.assertEqual([u['channel_id'] for u in result['unassigned']], ['5'])
        # 미배정 = 현재 바인딩이 없다. 도형은 그대로 남는다.
        self.assertIsNone(B.current_one('shape', 'zone-5', role='area',
                                        channel_id='5'))
        self.assertIsNotNone(self._shape('zone-5'))

    def test_the_unmapped_channel_ends_as_replaced_not_unbound(self):
        """끝난 원인은 교체다. 'unbound' 로 적으면 사람이 직접 뗀 것과 구분되지
        않는데, 그쪽이 더 큰 정보 손실이다."""
        self._zone('zone-5')
        B.bind('shape', 'zone-5', 'area', 'output', OLD, channel_id='5',
               commit=True)

        B.rebind_device(OLD, NEW, commit=True)

        past = B.history('shape', 'zone-5', role='area')
        self.assertEqual(past[-1].ended_reason, 'replaced')

    def test_uncountable_channels_move_everything_with_a_warning(self):
        """셀 수 없는 것과 없는 것은 다르다. 같은 값으로 접으면 채널을 셀 수
        없는 종류를 교체할 때 모든 비-0 채널이 미배정으로 떨어진다."""
        from aot.databases.models import CustomController
        CustomController(unique_id='dev-composite', name='복합장치').save()
        self._zone('zone-5')
        B.bind('shape', 'zone-5', 'area', 'output', OLD, channel_id='5',
               commit=True)

        result = B.rebind_device(OLD, 'dev-composite', commit=True)

        self.assertEqual(len(result['moved']), 1)
        self.assertEqual(result['unassigned'], [])
        self.assertTrue(result['warnings'])


class TestMarkerConflict(_Base):
    """결정 2 — 거부하되 어디가 충돌인지 알려준다."""

    def test_a_marker_of_the_new_device_on_the_same_map_refuses_the_swap(self):
        self._marker('marker-old', OLD)
        self._marker('marker-new', NEW)
        B.bind('shape', 'marker-old', 'marker', 'output', OLD, commit=True)

        with self.assertRaises(B.BindingConflict):
            B.rebind_device(OLD, NEW, commit=True)

    def test_nothing_is_written_when_the_swap_is_refused(self):
        """거부는 쓰기 전에 일어나야 한다. 반쯤 옮겨 놓고 실패하면 어느 자리가
        옮겨졌는지 사람이 알 수 없다."""
        self._zone('zone-1')
        self._marker('marker-old', OLD)
        self._marker('marker-new', NEW)
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)
        B.bind('shape', 'marker-old', 'marker', 'output', OLD, commit=True)

        with self.assertRaises(B.BindingConflict):
            B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual(B.current_one('shape', 'zone-1', role='area').device_id,
                         OLD)
        self.assertEqual(GeoBinding.query.filter(
            GeoBinding.device_id == NEW).count(), 0)

    def test_a_marker_on_a_different_map_is_not_a_conflict(self):
        """I2 유일성은 지도 단위다. 다른 지도의 마커까지 막으면 정상적인
        다중 지도 운용이 통째로 막힌다."""
        self._marker('marker-old', OLD, geo_id=MAP_A)
        self._marker('marker-elsewhere', NEW, geo_id=MAP_B)
        B.bind('shape', 'marker-old', 'marker', 'output', OLD, commit=True)

        result = B.rebind_device(OLD, NEW, commit=True)
        self.assertEqual(len(result['moved']), 1)

    def test_zone_polygons_do_not_conflict(self):
        """한 장치가 여러 구역을 맡는 것은 정상이다(밸브 하나가 두 구역에 관수).
        I2 도 마커에만 걸린다."""
        self._zone('zone-old', device_id=OLD)
        self._zone('zone-new', device_id=NEW)
        B.bind('shape', 'zone-old', 'area', 'output', OLD, commit=True)

        result = B.rebind_device(OLD, NEW, commit=True)
        self.assertEqual(len(result['moved']), 1)


class TestLegacyColumnStaysInStep(_Base):
    """바인딩만 옮기면 마커가 둘로 갈린다 — 정합성 미학이 아니라 고장이다."""

    def test_the_marker_column_follows_the_binding(self):
        self._marker('marker-old', OLD)
        B.bind('shape', 'marker-old', 'marker', 'output', OLD, commit=True)

        B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual(self._shape('marker-old').device_id, NEW)

    def test_the_front_end_entry_id_follows_too(self):
        """properties.unique_id 는 프런트가 엔트리를 식별하는 계약이다(GB-5b).
        여기를 안 고치면 마커를 눌렀을 때 없는 장치를 조회한다."""
        self._marker('marker-old', OLD, channel='2')
        B.bind('shape', 'marker-old', 'marker', 'output', OLD, channel_id='2',
               commit=True)

        B.rebind_device(OLD, NEW, commit=True)

        props = self._shape('marker-old').feature['properties']
        self.assertEqual(props['unique_id'], '%s::2' % NEW)

    def test_zone_polygons_keep_their_legacy_column_untouched(self):
        """구역의 레거시 컬럼은 마커 조회에 쓰이지 않는다. 건드릴 이유가 없고,
        건드리면 GB-6 명부만 늘어난다."""
        self._zone('zone-1', device_id=OLD)
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)

        B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual(self._shape('zone-1').device_id, OLD)


class TestFacilitySlotsAreRefused(_Base):
    """결정 — 시설 편집기가 정본이라 여기서 만든 바인딩은 다음 저장이 지운다."""

    def test_fitting_slots_are_reported_not_moved(self):
        self._zone('zone-1')
        B.bind('shape', 'zone-1', 'area', 'output', OLD, commit=True)
        B.bind('fitting', 'fitting-uuid-1', 'actuator', 'output', OLD,
               commit=True)

        result = B.rebind_device(OLD, NEW, commit=True)

        self.assertEqual(len(result['moved']), 1)
        self.assertEqual(len(result['refused']), 1)
        self.assertEqual(result['refused'][0]['spatial_kind'], 'fitting')
        self.assertTrue(result['refused'][0]['reason'])
        # 건드리지 않았다 — 옛 장치가 그대로 맡고 있다.
        self.assertEqual(
            B.current_one('fitting', 'fitting-uuid-1', role='actuator').device_id,
            OLD)


if __name__ == '__main__':
    unittest.main()
