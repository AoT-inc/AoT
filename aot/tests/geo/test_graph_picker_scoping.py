# coding=utf-8
"""그래프 선택 목록의 두 축 — 구역 필터와 복합장치 단위.

측정값 목록은 설치가 커질수록 쓸모없어진다. 로컬 개발 DB 조차 입력만 117개다.
"1-1 하우스의 온도"를 찾으려고 117줄을 훑는 것은 목록이 아니라 벌이다.

여기서 지키는 것은 셋이다.

1. **구역 필터는 "거르지 않음"과 "아무것도 없음"을 구분한다.** 지워진 구역을
   필터로 들고 있을 때 후자로 접으면 화면이 통째로 빈다.
2. **복합장치는 그릇이다.** 값을 재지 않으므로 고르면 그 안의 측정값 전부를
   뜻한다. 하위 판정은 소유(`parent_device_id`)뿐 — 장치 페이지 요약과
   `expand_device()` 가 쓰는 기준과 같아야 한다. 셋이 갈리면 같은 장치가
   화면마다 다른 것을 담는다.
3. **편 결과로 체크박스를 그리지 않는다.** 사람이 고른 것은 장치 하나인데
   편 결과로 그리면 장치를 골랐던 사실이 화면에서 사라진다.
"""
import unittest

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_membership as M
from aot.aot_flask.utils import utils_general as U
from aot.databases.models import (
    CustomController, DeviceMeasurements, GeoMap, GeoShape, Input, Output)


MAP = 'map-uuid-picker'
ZONE = 'zone-uuid-picker'
DEVICE = 'device-uuid-picker'
CHILD_IN = 'child-input-picker'
CHILD_OUT = 'child-output-picker'
LONER = 'loner-input-picker'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    # 선택지 생성은 모듈 선언을 읽고 그 문구가 번역 대상이라 babel 이 필요하다.
    Babel(app)
    return app


def _poly(uid, geo_id, coords, name):
    GeoShape(unique_id=uid, geo_id=geo_id, type='zone',
             feature={'type': 'Feature',
                      'properties': {'label_name': name},
                      'geometry': {'type': 'Polygon',
                                   'coordinates': [coords]}}).save()


def _marker(uid, geo_id, device_id, lng, lat):
    GeoShape(unique_id=uid, geo_id=geo_id, type='aot_device',
             device_id=device_id,
             feature={'type': 'Feature', 'properties': {},
                      'geometry': {'type': 'Point',
                                   'coordinates': [lng, lat]}}).save()


class _Base(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        GeoMap(unique_id=MAP, name='김제').save()
        _poly(ZONE, MAP, [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]], '1-1')

        CustomController(unique_id=DEVICE, name='AoT-C',
                         device='device_aot_c').save()
        Input(unique_id=CHILD_IN, name='노드 센서',
              parent_device_id=DEVICE).save()
        Output(unique_id=CHILD_OUT, name='노드 밸브',
               parent_device_id=DEVICE).save()
        Input(unique_id=LONER, name='바깥 센서').save()

        for dev in (CHILD_IN, CHILD_OUT, LONER):
            DeviceMeasurements(device_id=dev, channel=0,
                               measurement='temperature', unit='C').save()

        # 그릇만 지도에 놓는다 — 하위 장치는 보통 자기 마커가 없다.
        _marker('marker-device', MAP, DEVICE, 5, 5)
        _marker('marker-loner', MAP, LONER, 50, 50)   # 구역 밖

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TestAreaFilter(_Base):

    def test_areas_are_labelled_with_their_map(self):
        """같은 이름의 구역이 여러 지도에 있는 것이 정상이다(1-1 하우스는
        농장마다 있다). 이름만으로는 어느 것인지 고를 수 없다."""
        choices = M.area_choices()
        self.assertEqual([c['item'] for c in choices], ['김제 · 1-1'])

    def test_kinds_are_reported_so_the_screen_can_group_them(self):
        """필지와 구역을 이름순으로 섞으면 '1-1'~'1-9' 같은 구역이 위를 다
        차지하고 필지는 아래로 밀려, 화면만 보고는 필지가 아예 없는 줄 안다 —
        실제로 그렇게 보고받았다."""
        SITE = 'site-uuid-picker'
        GeoShape(unique_id=SITE, geo_id=MAP, type='site',
                 feature={'type': 'Feature',
                          'properties': {'label_name': '1포장'},
                          'geometry': {'type': 'Polygon',
                                       'coordinates': [[[0, 0], [0, 20],
                                                        [20, 20], [20, 0],
                                                        [0, 0]]]}}).save()
        kinds = {c['kind'] for c in M.area_choices()}
        self.assertEqual(kinds, {'site', 'zone'})

    def test_an_area_with_nothing_in_it_is_left_out(self):
        """로컬 실측에서 36개 중 25개가 장치도 노트도 없었다. 그런 항목을
        고르면 모든 목록이 통째로 비어 "필터가 고장났다"로 읽힌다."""
        GeoShape(unique_id='empty-zone', geo_id=MAP, type='zone',
                 feature={'type': 'Feature',
                          'properties': {'label_name': '빈 구역'},
                          'geometry': {'type': 'Polygon',
                                       'coordinates': [[[90, 90], [90, 95],
                                                        [95, 95], [95, 90],
                                                        [90, 90]]]}}).save()
        values = {c['value'] for c in M.area_choices()}
        self.assertNotIn('empty-zone', values)

    def test_an_area_with_only_notes_is_kept(self):
        """장치가 없어도 노트가 있으면 고를 값이 있다("3-2 구역의 기록만 보기")."""
        from aot.databases.models import Notes
        GeoShape(unique_id='note-only-zone', geo_id=MAP, type='zone',
                 feature={'type': 'Feature',
                          'properties': {'label_name': '기록만 있는 구역'},
                          'geometry': {'type': 'Polygon',
                                       'coordinates': [[[60, 60], [60, 65],
                                                        [65, 65], [65, 60],
                                                        [60, 60]]]}}).save()
        Notes(unique_id='n1', name='메모', note='', target_id='note-only-zone').save()

        values = {c['value'] for c in M.area_choices()}
        self.assertIn('note-only-zone', values)

    def test_an_unnamed_shape_is_left_out(self):
        """목록에서 고르는 수단은 이름뿐이라 자리표시를 넣어 봐야 무엇인지 알
        방법이 없고, 이름 있는 것들을 아래로 밀어낸다."""
        GeoShape(unique_id='nameless-zone', geo_id=MAP, type='zone',
                 feature={'type': 'Feature', 'properties': {},
                          'geometry': {'type': 'Polygon',
                                       'coordinates': [[[0, 0], [0, 1],
                                                        [1, 1], [1, 0],
                                                        [0, 0]]]}}).save()
        values = {c['value'] for c in M.area_choices()}
        self.assertNotIn('nameless-zone', values)

    def test_a_device_inside_the_zone_is_kept(self):
        self.assertIn(DEVICE, M.device_ids_in_area(ZONE))

    def test_a_device_outside_the_zone_is_dropped(self):
        self.assertNotIn(LONER, M.device_ids_in_area(ZONE))

    def test_children_of_a_device_in_the_zone_come_along(self):
        """하위 장치는 자기 마커가 없어 기하 판정만으로는 빠진다 — 그러면
        "이 구역의 값"에서 정작 값을 재는 것들이 사라진다."""
        ids = M.device_ids_in_area(ZONE)
        self.assertIn(CHILD_IN, ids)
        self.assertIn(CHILD_OUT, ids)

    def test_a_missing_area_means_do_not_filter(self):
        """지워진 구역을 필터로 들고 있을 때 빈 집합을 돌려주면 화면이 통째로
        빈다. None 은 "거르지 않는다" 이고 그 둘은 다르다."""
        self.assertIsNone(M.device_ids_in_area('does-not-exist'))


class TestAreaMembershipIsNotJustMarkers(_Base):
    """마커만 보면 목록이 통째로 빈다.

    로컬 실측: 출력 16개 중 마커가 있는 것은 1개, PID 2개 중 0개, 함수 17개 중
    1개. 마커는 "지도에 점을 찍었다"는 뜻일 뿐이고, 구역을 담당하는 장치는
    보통 구역 폴리곤이나 시설 설비에 매여 있거나, 그 장치들을 참조한다.
    """

    def setUp(self):
        super(TestAreaMembershipIsNotJustMarkers, self).setUp()
        from aot.databases.geo_integrity_ddl import apply_binding
        raw = db.engine.raw_connection()
        try:
            apply_binding(raw)
            raw.commit()
        finally:
            raw.close()

    def test_a_device_bound_to_a_polygon_inside_counts(self):
        """마커가 없어도 그 구역 폴리곤이 맡긴 장치는 이 구역의 것이다."""
        from aot.aot_flask.geo import device_binding as B
        inner = 'inner-zone-picker'
        GeoShape(unique_id=inner, geo_id=MAP, type='device',
                 feature={'type': 'Feature', 'properties': {},
                          'geometry': {'type': 'Polygon',
                                       'coordinates': [[[1, 1], [1, 4],
                                                        [4, 4], [4, 1],
                                                        [1, 1]]]}}).save()
        far = 'far-output-picker'
        Output(unique_id=far, name='마커 없는 밸브').save()
        B.bind('shape', inner, 'area', 'output', far, commit=True)

        self.assertIn(far, M.device_ids_in_area(ZONE))

    def test_a_pid_reading_a_device_inside_counts(self):
        """PID 는 자기 마커를 갖는 일이 거의 없다. 읽는 센서와 움직이는 출력이
        이 구역이면 그 PID 는 이 구역의 것이다 — 아니면 구역을 고르는 순간
        PID 목록이 통째로 비고 사용자는 "필터가 고장났다"로 읽는다."""
        from aot.databases.models import PID
        PID(unique_id='pid-picker', name='관수 PID',
            measurement='%s,some-measurement' % CHILD_IN).save()

        self.assertIn('pid-picker', M.device_ids_in_area(ZONE))

    def test_an_unrelated_pid_does_not_come_along(self):
        from aot.databases.models import PID
        PID(unique_id='pid-elsewhere', name='남의 PID',
            measurement='%s,some-measurement' % LONER).save()

        self.assertNotIn('pid-elsewhere', M.device_ids_in_area(ZONE))


class TestNotesAndTagsFollowTheArea(_Base):
    """태그 자체는 구역에 속하지 않는다("관수"는 농장 전체의 어휘다).
    구역에 속하는 것은 노트다."""

    def _note(self, uid, target_id, tags='', lat=None, lng=None):
        from aot.databases.models import Notes
        Notes(unique_id=uid, name=uid, note='', target_id=target_id,
              tags=tags, gps_lat=lat, gps_lng=lng).save()

    def test_a_note_attached_to_the_area_itself_counts(self):
        """로컬 실측에서 노트의 target 은 대부분 공간이다(site·zone·시설).
        장치만 보고 만들었더니 구역을 골라도 노트가 0건이었다."""
        self._note('note-on-zone', ZONE)
        self.assertIn('note-on-zone', M.note_ids_in_area(ZONE))

    def test_a_note_attached_to_a_device_inside_counts(self):
        self._note('note-on-device', CHILD_IN)
        self.assertIn('note-on-device', M.note_ids_in_area(ZONE))

    def test_a_note_placed_by_coordinates_counts(self):
        self._note('note-by-gps', None, lat=5, lng=5)
        self.assertIn('note-by-gps', M.note_ids_in_area(ZONE))

    def test_a_note_elsewhere_is_left_out(self):
        self._note('note-outside', LONER)
        self.assertNotIn('note-outside', M.note_ids_in_area(ZONE))

    def test_only_tags_that_actually_have_notes_here_survive(self):
        """골라도 아무것도 안 뜨는 태그가 남으면 필터가 거짓말이 된다."""
        self._note('note-tagged', ZONE, tags='tag-a,tag-b')
        self._note('note-far', LONER, tags='tag-c')
        notes = M.note_ids_in_area(ZONE)
        self.assertEqual(M.tag_ids_for_notes(notes), {'tag-a', 'tag-b'})

    def test_a_missing_area_means_do_not_filter_notes(self):
        self.assertIsNone(M.note_ids_in_area('does-not-exist'))


class TestCompositeDeviceChoices(_Base):

    def test_a_device_with_measurements_is_offered(self):
        items = [c['item'] for c in U.choices_composite_devices()]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].startswith('AoT-C'))

    def test_a_device_without_measurements_is_not_offered(self):
        """골라도 그래프에 아무것도 안 나오는 항목은 "고장났다"로 읽힌다."""
        DeviceMeasurements.query.delete()
        db.session.commit()
        self.assertEqual(U.choices_composite_devices(), [])

    def test_the_device_expands_to_the_measurements_it_holds(self):
        rows = U.composite_device_measurements(DEVICE)
        self.assertEqual(sorted(r[0] for r in rows),
                         sorted([CHILD_IN, CHILD_OUT]))
        self.assertEqual(sorted(r[2] for r in rows), ['input', 'output'])

    def test_a_referenced_but_unowned_device_is_not_included(self):
        """하위 판정은 소유(parent_device_id)뿐이다 — 남의 구성에 참조로 끼워
        넣은 항목이 이 장치의 측정값이 되면 안 된다."""
        from aot.databases.models import DeviceMember
        DeviceMember(device_id=DEVICE, member_type='input',
                     member_id=LONER).save()
        rows = U.composite_device_measurements(DEVICE)
        self.assertNotIn(LONER, [r[0] for r in rows])


class TestSelectionExpansion(_Base):

    def _expand(self, selected):
        from aot.aot_flask.routes_page import _expand_device_choices
        return _expand_device_choices(selected)

    def test_a_device_choice_becomes_its_measurements(self):
        out = self._expand(['%s,ALL,device' % DEVICE])
        self.assertEqual(len(out), 2)
        for item in out:
            self.assertEqual(len(item.split(',')), 3)
            self.assertIn(item.split(',')[2], ('input', 'output'))

    def test_ordinary_choices_pass_through_untouched(self):
        plain = 'abc,def,input'
        self.assertEqual(self._expand([plain]), [plain])

    def test_a_device_with_nothing_inside_expands_to_nothing(self):
        CustomController(unique_id='empty-device', name='빈 장치',
                         device='device_aot_c').save()
        self.assertEqual(self._expand(['empty-device,ALL,device']), [])


if __name__ == '__main__':
    unittest.main()
