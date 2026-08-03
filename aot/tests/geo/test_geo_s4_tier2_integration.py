# coding=utf-8
"""S4 통합 테스트 — Tier-2 트리거가 켜진 DB 위에서 앱 저장 경로가 통과하고,
되먹임 고리가 실제로 죽었는지 종단 재현으로 고정한다.

Tier-2 (I6/I7/I8) 는 "앱이 규칙을 지키면 통과, 어기면 DB 가 거부" 다.
공격 테스트(test_geo_invariants_attack.py)가 '어기면 거부'를 증명한다면,
이 파일은 '앱의 정상 저장이 지키면서 통과'를 증명한다 — 둘 다 있어야
Tier-2 를 운영에 켤 수 있다.

핵심은 되먹임 고리 종단 재현이다 (2026-08-03 조사에서 확정된 스모킹건):
  GET 이 표시용으로 aot_type 을 주입·정규화('device'→'aot_device') →
  위젯 라벨 이름 변경이 그 feature 를 그대로 /delta 로 재전송 →
  (과거) row.type 덮어씀 → 다음 전체 저장의 type 스코프에서 벗어나
  UPDATE 대신 INSERT → 도형 두 벌.
이제 같은 시퀀스가 type 을 바꾸지도, 도형을 늘리지도 않아야 한다.
"""
import json
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.geo_integrity_ddl import apply_tier1, apply_tier2
from aot.databases.models import GeoMap, GeoShape


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    try:                                    # 일부 하위 경로가 gettext 사용
        from flask_babel import Babel
        Babel(app)
    except Exception:
        pass
    return app


def _feat(props, geom=None):
    return {'type': 'Feature',
            'geometry': geom or {'type': 'Point', 'coordinates': [1.0, 1.0]},
            'properties': props}


def _stored_props(unique_id=None, shape_id=None):
    q = GeoShape.query
    row = (q.filter_by(unique_id=unique_id).first() if unique_id
           else q.filter_by(id=shape_id).first())
    f = row.feature
    if isinstance(f, str):
        f = json.loads(f)
    return row, (f.get('properties') or {})


class TestTier2AppPathIntegration(unittest.TestCase):
    """Tier-1+2 트리거가 실제로 걸린 DB 에서 앱 저장 함수를 호출한다."""

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
        GeoMap(unique_id='m1', name='통합검증 지도', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_save_overlays_strips_aot_type_and_passes_i6(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        # 클라이언트 계약대로 aot_type 을 실은 페이로드 — 서버가 걷어내고
        # 저장해야 I6 트리거를 통과한다.
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'zone',
            'features': [_feat({'node_id': 'n-z1', 'aot_type': 'zone',
                                'name': '1-1'},
                               {'type': 'Polygon',
                                'coordinates': [[[0, 0], [0, 9], [9, 9],
                                                 [9, 0], [0, 0]]]})],
        })
        self.assertIsNone(err, err)
        self.assertEqual(result['stats']['inserted'], 1)
        row = GeoShape.query.filter_by(geo_id='m1', type='zone').first()
        _, props = _stored_props(shape_id=row.id)
        self.assertNotIn('aot_type', props)      # I6: 저장본에 사본 없음
        self.assertEqual(props.get('name'), '1-1')

    def test_get_overlays_reinjects_aot_type_for_frontend(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        GeoShape(unique_id='s-z', geo_id='m1', type='zone',
                 feature=_feat({'name': 'Z'})).save()
        fc, err = GeoOverlayManager.get_overlays('m1', target_type='zone')
        self.assertIsNone(err)
        self.assertEqual(
            fc['features'][0]['properties'].get('aot_type'), 'zone')

    def test_feedback_loop_is_dead_end_to_end(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        # 1) 디자인 편집기가 type='device' 구역 도형을 만든다.
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'device', 'device_id': 'dev-1',
            'features': [_feat({'node_id': 'n-d1', 'device_id': 'dev-1'},
                               {'type': 'Polygon',
                                'coordinates': [[[0, 0], [0, 5], [5, 5],
                                                 [5, 0], [0, 0]]]})],
        })
        self.assertIsNone(err, err)
        row = GeoShape.query.filter_by(geo_id='m1', device_id='dev-1').first()
        self.assertEqual(row.type, 'device')

        # 2) 지도 위젯이 GET — 서버가 aot_type 을 주입하며
        #    'device' → 'aot_device' 로 표시용 정규화한다.
        fc, _ = GeoOverlayManager.get_overlays('m1', target_type='aot_device')
        echoed = next(f for f in fc['features']
                      if (f['properties'] or {}).get('device_id') == 'dev-1')
        self.assertEqual(echoed['properties']['aot_type'], 'aot_device')

        # 3) 위젯 라벨 이름 변경 — 받은 feature 를 그대로 /delta 로 재전송.
        echoed['properties']['name'] = '새이름'
        result, err = GeoOverlayManager.save_delta({
            'map_uuid': 'm1', 'upserts': [echoed]})
        self.assertIsNone(err, err)

        # 4) (과거 사고 지점) type 이 바뀌지 않았어야 한다 — I7.
        row = GeoShape.query.filter_by(geo_id='m1', device_id='dev-1').first()
        self.assertEqual(row.type, 'device')
        _, props = _stored_props(shape_id=row.id)
        self.assertNotIn('aot_type', props)
        self.assertEqual(props.get('name'), '새이름')   # 이름 변경은 반영

        # 5) 다음 전체 저장 — 여전히 type='device' 스코프에서 찾아져
        #    UPDATE 여야 하고, 도형은 늘어나지 않아야 한다.
        feat2 = dict(echoed)
        feat2['properties'] = dict(echoed['properties'],
                                   db_id=row.id, name='새이름2')
        result, err = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'device', 'device_id': 'dev-1',
            'features': [feat2]})
        self.assertIsNone(err, err)
        self.assertEqual(result['stats']['updated'], 1)
        self.assertEqual(result['stats']['inserted'], 0)   # 이중화 없음
        self.assertEqual(GeoShape.query.filter_by(
            geo_id='m1', device_id='dev-1').count(), 1)

    def test_delta_insert_of_new_shape_still_works_under_tier2(self):
        from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
        result, err = GeoOverlayManager.save_delta({
            'map_uuid': 'm1',
            'upserts': [_feat({'node_id': 'n-new', 'aot_type': 'label_aux'})],
        })
        self.assertIsNone(err, err)
        row = GeoShape.query.filter_by(geo_id='m1', type='label_aux').first()
        self.assertIsNotNone(row)                # 신규 생성 계약은 유지
        _, props = _stored_props(shape_id=row.id)
        self.assertNotIn('aot_type', props)      # 저장본은 스트립

    def test_facility_save_passes_i6(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        data, err = FacilityManager.save_facility({
            'geo_id': 'm1', 'name': '육묘장',
            'outer_geometry': {'type': 'Polygon',
                               'coordinates': [[[0, 0], [0, 3], [3, 3],
                                                [3, 0], [0, 0]]]},
        })
        self.assertIsNone(err, err)
        row = GeoShape.query.filter_by(geo_id='m1', type='facility').first()
        _, props = _stored_props(shape_id=row.id)
        self.assertNotIn('aot_type', props)
        self.assertEqual(props.get('name'), '육묘장')


if __name__ == '__main__':
    unittest.main()
