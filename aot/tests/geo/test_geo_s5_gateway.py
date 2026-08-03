# coding=utf-8
"""S5 — 배치 게이트웨이 계약과 소유권 검사기 회귀 테스트.

게이트웨이(device_placement)는 지도 불변식을 호출자 대신 지킨다. AI
대량생성·장치위치 API·복제 어느 쪽에서 오든 같은 문을 지나므로, 여기서
계약이 깨지면 전부 깨진다 — 그래서 계약을 테스트로 고정한다.

소유권 검사기(check_geo_writes)는 '규칙을 모르는 코드'가 geo 패키지
밖에서 지도를 직접 쓰는 것을 CI 시점에 막는다. 위반 0 상태를 회귀로
고정해, 새 우회가 들어오면 그 커밋에서 터지게 한다.
"""
import importlib.util
import os
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.geo_integrity_ddl import apply_tier1, apply_tier2
from aot.databases.models import GeoMap, GeoShape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    try:                                    # 모델 저장 경로가 gettext 사용
        from flask_babel import Babel
        Babel(app)
    except Exception:
        pass
    return app


class TestPlacementGateway(unittest.TestCase):
    """Tier-1+2 트리거가 켜진 DB 에서 게이트웨이 계약을 검증한다."""

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        raw = db.engine.raw_connection()
        try:
            apply_tier1(raw)
            apply_tier2(raw)
            raw.commit()
        finally:
            raw.close()
        GeoMap(unique_id='m1', name='게이트웨이 검증', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_place_device_satisfies_all_invariants(self):
        from aot.aot_flask.geo.device_placement import place_device
        m = place_device('dev-1', 'm1', 35.8, 126.9,
                         device_type='output', name='v01', commit=True)
        self.assertIsNotNone(m)
        self.assertEqual(m.type, 'aot_device')       # I1 어휘
        self.assertEqual(m.channel_id, '0')          # 채널 정규화
        self.assertNotIn('aot_type', m.feature['properties'])   # I6
        self.assertEqual(m.feature['geometry']['coordinates'],
                         [126.9, 35.8])              # [lng, lat] 순서

    def test_repeated_placement_moves_not_duplicates(self):
        # AI 대량생성이 같은 장치를 두 번 배치해도 마커는 하나여야 한다
        # (과거: channel_id 누락으로 첫 위치 저장에서 중복 발생).
        from aot.aot_flask.geo.device_placement import place_device
        place_device('dev-1', 'm1', 35.8, 126.9, commit=True)
        place_device('dev-1', 'm1', 35.9, 127.0, commit=True)
        rows = GeoShape.query.filter_by(geo_id='m1', device_id='dev-1').all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].feature['geometry']['coordinates'],
                         [127.0, 35.9])              # 이동 반영

    def test_channel_zero_and_none_are_the_same_slot(self):
        # NULL/'0' 비대칭이 중복 마커의 실제 발생 경로였다.
        from aot.aot_flask.geo.device_placement import place_device
        place_device('dev-2', 'm1', 35.8, 126.9, channel_id=None, commit=True)
        place_device('dev-2', 'm1', 35.8, 126.9, channel_id=0, commit=True)
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', device_id='dev-2').count(), 1)

    def test_separate_channels_are_separate_markers(self):
        from aot.aot_flask.geo.device_placement import place_device
        place_device('dev-3', 'm1', 35.8, 126.9, channel_id=0, commit=True)
        place_device('dev-3', 'm1', 35.8, 126.91, channel_id=1, commit=True)
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', device_id='dev-3').count(), 2)

    def test_missing_coords_unplaces(self):
        from aot.aot_flask.geo.device_placement import place_device
        place_device('dev-4', 'm1', 35.8, 126.9, commit=True)
        place_device('dev-4', 'm1', None, None, commit=True)
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', device_id='dev-4').count(), 0)

    def test_delete_shape_relies_on_trigger_cascade(self):
        # 호출자는 정리 순서를 몰라도 된다 — 그것이 이 문의 존재 이유다.
        from aot.aot_flask.geo.device_placement import delete_shape
        from aot.databases.models import GeoFacility
        shape = GeoShape(unique_id='fs1', geo_id='m1', type='facility',
                         feature={'type': 'Feature',
                                  'geometry': {'type': 'Polygon',
                                               'coordinates': [[[0, 0], [0, 1],
                                                                [1, 1], [0, 0]]]},
                                  'properties': {}})
        shape.save()
        GeoFacility(unique_id='f1', shape_uuid='fs1', geo_id='m1',
                    name='시설', render_mode='parametric').save()
        stype = delete_shape('fs1', commit=True)
        self.assertEqual(stype, 'facility')
        self.assertEqual(GeoFacility.query.filter_by(
            unique_id='f1').count(), 0)              # 트리거 연쇄
        self.assertIsNone(delete_shape('없는-uuid'))  # 없으면 None


class TestWriteOwnershipChecker(unittest.TestCase):
    """소유권 검사기 자체의 회귀 — 위반 0 을 고정한다."""

    def _load(self):
        path = os.path.join(ROOT, 'aot', 'scripts', 'check_geo_writes.py')
        spec = importlib.util.spec_from_file_location('check_geo_writes', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_no_violations_in_tree(self):
        violations = self._load().scan()
        self.assertEqual(
            violations, [],
            'geo 패키지 밖에서 지도 데이터를 직접 씁니다:\n' +
            '\n'.join('  %s:%d [%s] %s' % v for v in violations))

    def test_checker_detects_a_planted_violation(self):
        # 검사기가 실제로 잡는지 — 항상 통과하는 검사기는 무의미하다.
        mod = self._load()
        v = mod._Visitor()
        import ast
        v.visit(ast.parse('def f():\n    x = GeoShape(geo_id="m")\n'))
        self.assertTrue(any('직접 생성' in label for _, label in v.hits))

    def test_docstring_mention_is_not_a_violation(self):
        mod = self._load()
        v = mod._Visitor()
        import ast
        v.visit(ast.parse('def f():\n    """GeoShape (zone/site) first."""\n'
                          '    return 1\n'))
        self.assertEqual(v.hits, [])


if __name__ == '__main__':
    unittest.main()
