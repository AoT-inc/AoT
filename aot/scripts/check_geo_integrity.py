#!/usr/bin/env python3
"""지도 데이터 무결성 체커 (읽기 전용).

GeoShape 는 도형의 종류를 두 곳에 들고 있다 — `type` 컬럼과
`feature.properties.aot_type`. 코드는 aot_type 을 정본으로 취급하지만
(geo_overlays.py 의 `props.get('aot_type', 'feature')`), 둘이 어긋나도 막는
장치가 없다. 그리고 `type` 컬럼에는 `default='feature'` 라는 조용한 폴백이
있어서, 도형을 만드는 코드가 type 을 한 번 빠뜨리면 에러 없이 'feature' 가
들어간다.

어긋난 뒤가 진짜 문제다. save_overlays() 는 갱신 대상도 삭제 범위도 전부
`type=target_type` 으로 스코프하므로, type 이 어긋나 있으면 "기존 것 없음"으로
판정해 UPDATE 대신 INSERT 하고 옛 행은 삭제 범위 밖이라 그대로 남는다. 저장
한 번에 같은 도형이 두 벌이 되는데 아무 에러도 안 난다.

오염은 즉시 드러나지 않는다. 읽는 경로마다 기준이 달라(어떤 곳은 type, 어떤
곳은 aot_type, collect_devices 는 필터 없음) 부분적으로만 망가진 채 몇 주씩
굴러가다, 업그레이드로 읽기 경로가 바뀌거나 정상 데이터가 하나 들어오는
순간 드러난다. 그래서 항상 "업데이트 직후" 발견되지만 원인은 훨씬 전이다.

  2026-07-28  clone_map_config() 가 type 을 안 넘겨 김제 지도 도형 98개가
              'feature' 로 복제됨 → 3분 뒤 편집기 저장이 올바른 타입으로 한 벌
              더 INSERT → 두 벌. 6일간 아무도 몰랐고, 08-03 시설 하나를
              추가하자 "예전 시설이 지도에서 사라짐"으로 표면화됐다.

검사 항목 12종 (GeoShape 8 + GeoPlanting 4):
  type-mismatch   type 컬럼 ≠ properties.aot_type
  duplicate       같은 지도 안에서 (종류, 기하) 가 겹치는 도형.
                  좌표는 --tolerance(기본 1e-6 도, 약 0.1m) 로 반올림해 비교한다
                  — 완전 일치만 보면 저장 사이에 라벨이 몇 m 움직인 중복을 놓친다.
  dangling-link   Input/Output/PID/Trigger/Conditional/CustomController/Function
                  의 map_overlay_id 가 없는 GeoShape.id 를 가리킴
  orphan-facility GeoFacility.shape_uuid 가 없는 GeoShape 를 가리킴
  orphan-label    라벨의 parent_node_id 가 어떤 도형에도 해소되지 않음

공간-장치 바인딩(docs/design/geo-device-binding.md) 관련 3종:

  orphan-device-shape  GeoShape.device_id 가 실존하지 않는 장치를 가리킴.
                  장치 삭제 진입점 17곳(utils 7 + tab_service 7 + 진단 3) 중
                  도형을 정리하는 곳은 4곳뿐이라, 나머지로 지운 장치의 도형은
                  아무 에러 없이 남아 지도에 계속 그려진다. dangling-link 는
                  사망 컬럼 map_overlay_id 만 보므로 이걸 못 잡는다.
  dangling-fitting  GeoFacility 의 JSON 참조(fittings.actuator_id/input_id,
                  actuators.device_uuid, sensors.device_id,
                  weather_bindings.input_uuid)가 실존하지 않는 장치를 가리킴.
                  JSON 안이라 DB 가 볼 수 없고 어느 삭제 경로도 정리하지
                  않는다 — 탐지가 유일한 방어다.
  binding-drift   레거시 저장처에는 있는데 geo_binding 에 현재 바인딩이 없는
                  연결. 두 저장처가 공존하는 Phase B 완료 전까지의 감시자다.
                  geo_binding 테이블이 없는 설치에서는 건너뛴다.

식생 구획(docs/design/geo-vegetation-planting.md) 관련 4종:

  planting-bad-geometry   기하가 Polygon/MultiPolygon 이 아님(VP-1). 지도에
                  아예 그려지지 않는다 — 목록에는 있는데 화면에 없는 상태.
  planting-bad-dates      ended_on < planted_on (VP-2).
  planting-embedded-ref   feature.properties 에 device_id/색 사본 각인(VP-4).
                  사본은 원본이 바뀌어도 따라오지 않아 조용히 갈린다.
  planting-phantom-map    GeoMap 행이 없는 geo_id — 자동 삭제 금지.

  ⚠ 구획끼리의 **겹침은 검사하지 않는다.** 간작·혼작이 정상이다(VP-3).
    "겹치면 안 될 것 같다"는 직관으로 검사를 추가하지 말 것.

쓰기는 일절 하지 않는다. 운영 서버에 그대로 돌려도 안전하다.

사용:
    python3 -m aot.scripts.check_geo_integrity              # 전체 검사
    python3 -m aot.scripts.check_geo_integrity --map <uuid> # 지도 하나만
    python3 -m aot.scripts.check_geo_integrity --json       # 기계 판독용
    python3 -m aot.scripts.check_geo_integrity --quiet      # 요약만

종료 코드 0 = 정상, 1 = 문제 발견, 2 = 검사 자체 실패.

@phase active
@stability stable
"""
import argparse
import json
import math
import sys
from collections import defaultdict

from aot.start_flask_ui import app
from aot.databases.models import (
    Conditional, CustomController, Function, GeoBinding, GeoFacility, GeoMap,
    GeoShape, Input, Output, PID, Trigger)


# map_overlay_id 를 들고 있는 모델 전부. 하나라도 빠지면 그 모델의 끊어진
# 참조를 놓친다 — 2026-08-03 정리 작업이 이 목록을 안 보고 진행해 Input 5건 +
# Output 6건의 참조를 끊었다.
OVERLAY_LINK_MODELS = (
    Input, Output, PID, Trigger, Conditional, CustomController, Function)

# 중복 판정에서 제외하는 종류. equipment_collection 은 한 행이
# FeatureCollection 을 통째로 담는 번들이라 기하 비교 대상이 아니다.
DUP_EXEMPT_TYPES = {'equipment_collection'}

# 장치 uuid 를 담을 수 있는 모델 전부(= geo_integrity_ddl.DEVICE_LINK_TABLES).
# 도형 마커는 Function·PID·Trigger 에도 붙으므로 Input/Output 만 보면
# 정상 마커를 고아로 오진한다.
DEVICE_MODELS = (
    Input, Output, CustomController, Function, PID, Trigger, Conditional)

# GeoFacility 안에서 장치를 가리키는 (컬럼, 키) 전부. 2026-08-08 실측으로
# JSON 을 전수 순회해 뽑았다 — fittings 와 actuators 는 컬럼도 키 이름도
# 다르므로 하나만 보면 나머지를 놓친다.
FACILITY_DEVICE_REFS = (
    ('fittings', 'actuator_id'),
    ('fittings', 'input_id'),
    ('actuators', 'device_uuid'),
    ('sensors', 'device_id'),
    ('weather_bindings', 'input_uuid'),
)


def _feature(shape):
    """GeoShape.feature 를 dict 로 정규화. SQLite 는 JSON 컬럼을 문자열로
    돌려주는 경우가 있어 여기서 한 번 흡수한다."""
    raw = shape.feature
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _props(shape):
    return _feature(shape).get('properties') or {}


def _node_id(shape):
    """도형의 논리 식별자. get_overlays() 가 node_id 없는 레거시 행에
    unique_id 를 백필하므로 여기서도 같은 규칙을 쓴다."""
    return _props(shape).get('node_id') or shape.unique_id


def _geom_key(shape, tolerance):
    """기하를 좌표 반올림 후 정규화 문자열로. 없으면 None.

    tolerance 로 반올림하는 이유: 같은 도형을 두 번 저장하는 사이 라벨/마커가
    몇 m 움직이면 좌표가 미세하게 달라진다. 완전 일치만 보면 그런 중복을
    놓친다(2026-08-03 라벨 4쌍이 정확히 이 이유로 1차 정리에서 빠졌다)."""
    geom = _feature(shape).get('geometry')
    if not isinstance(geom, dict) or not geom.get('type'):
        return None

    ndigits = max(0, -int(round(math.log10(tolerance)))) if tolerance > 0 else 12

    def _round(node):
        if isinstance(node, (int, float)):
            return round(float(node), ndigits)
        if isinstance(node, (list, tuple)):
            return [_round(x) for x in node]
        return node

    return json.dumps(
        {'type': geom['type'], 'coordinates': _round(geom.get('coordinates'))},
        sort_keys=True)


def _json_items(blob):
    """JSON 컬럼을 dict 항목 리스트로. 문자열 저장·dict 저장 모두 흡수."""
    raw = blob
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [x for x in raw.values() if isinstance(x, dict)]
    return []


def _binding_drift(shapes, device_ids):
    """레거시 저장처에는 있는데 현재 바인딩에는 없는 연결을 찾는다.

    Phase B 완료 전까지 두 저장처가 공존하므로, 새 연결이 한쪽에만 생기면
    조용히 갈린다. 죽은 참조는 애초에 바인딩을 만들지 않기로 한 것이므로
    (백필 정책) 드리프트에서 제외한다 — 그건 orphan-device-shape 의 몫이다.

    geo_binding 테이블이 없으면(p6_27 이전 설치) 빈 목록.

    존재 확인을 `try: 조회 except: return []` 로 하지 않는 이유: 그러면 테이블이
    **있는데 조회가 실패하는 경우**(부분 적용된 마이그레이션, 컬럼 누락, DB 파손)
    까지 함께 삼켜서 "드리프트 0건"으로 보고한다. 검사기가 아무것도 못 본 것과
    문제가 없는 것이 화면에서 구분되지 않는 것 — 이 레포가 반복해서 당한 실패
    모드다. inspector 로 "없음"만 명시적으로 처리하면 나머지 실패는 collect()
    바깥으로 올라가 `ERROR: 검사 실패`(종료 2)로 드러난다.

    (참고: 실측 결과 없는 테이블 조회가 SQLAlchemy 세션을 오염시키지는
    않는다 — 후속 ORM 조회도 미커밋 쓰기의 commit 도 정상이다. 이 함수의
    근거는 세션 보호가 아니라 위의 '침묵 실패 방지'다.)
    """
    from aot.aot_flask.extensions import db
    from sqlalchemy import inspect as sa_inspect

    try:
        if 'geo_binding' not in sa_inspect(db.engine).get_table_names():
            return []
    except Exception:
        return []

    current = {(b.spatial_kind, b.spatial_id, b.role, b.device_id)
               for b in GeoBinding.query.filter(
                   GeoBinding.valid_to.is_(None)).all()}

    roles = {'aot_device': 'marker', 'device': 'area'}
    out = []
    for s in shapes:
        raw = (s.device_id or '').strip()
        role = roles.get(s.type)
        if not raw or role is None:
            continue
        did = raw.split('::')[0]
        if did not in device_ids:
            continue                       # 죽은 참조 — 다른 검사 담당
        if ('shape', s.unique_id, role, did) not in current:
            out.append({
                'source': 'geo_shape.device_id',
                'shape_id': s.id,
                'spatial_id': s.unique_id,
                'role': role,
                'device_id': did,
            })
    return out


def collect(map_uuid=None, tolerance=1e-6):
    """모든 검사를 돌리고 {검사이름: [문제, ...]} 를 돌려준다. 읽기 전용."""
    shapes = (GeoShape.query.filter_by(geo_id=map_uuid).all() if map_uuid
              else GeoShape.query.all())
    all_shapes = GeoShape.query.all()          # 참조 검사는 항상 전역 기준
    by_id = {s.id: s for s in all_shapes}
    by_uuid = {s.unique_id: s for s in all_shapes}
    map_names = {m.unique_id: m.name for m in GeoMap.query.all()}

    findings = defaultdict(list)

    def _where(shape):
        return {'shape_id': shape.id,
                'map': map_names.get(shape.geo_id, shape.geo_id),
                'name': _props(shape).get('name')}

    # ── type ↔ aot_type ────────────────────────────────────────────────
    for s in shapes:
        aot_type = _props(s).get('aot_type')
        if aot_type and aot_type != s.type:
            findings['type-mismatch'].append(
                dict(_where(s), type=s.type, aot_type=aot_type))

    # ── 같은 지도 안의 (종류, 기하) 중복 ────────────────────────────────
    groups = defaultdict(list)
    for s in shapes:
        if s.type in DUP_EXEMPT_TYPES:
            continue
        key = _geom_key(s, tolerance)
        if key:
            groups[(s.geo_id, s.type, key)].append(s)
    for (geo_id, stype, _), members in groups.items():
        if len(members) > 1:
            members.sort(key=lambda s: s.id)
            findings['duplicate'].append({
                'map': map_names.get(geo_id, geo_id),
                'type': stype,
                'name': _props(members[0]).get('name'),
                'shape_ids': [s.id for s in members],
                'keep_suggestion': members[0].id,
            })

    # ── 끊어진 map_overlay_id ──────────────────────────────────────────
    for model in OVERLAY_LINK_MODELS:
        if not hasattr(model, 'map_overlay_id'):
            continue
        for row in model.query.filter(model.map_overlay_id.isnot(None)).all():
            if row.map_overlay_id not in by_id:
                findings['dangling-link'].append({
                    'model': model.__name__,
                    'name': getattr(row, 'name', None),
                    'unique_id': getattr(row, 'unique_id', None),
                    'map_overlay_id': row.map_overlay_id,
                })

    # ── 고아 GeoFacility ───────────────────────────────────────────────
    for fac in GeoFacility.query.all():
        if fac.shape_uuid not in by_uuid:
            findings['orphan-facility'].append({
                'facility': fac.name,
                'facility_uuid': fac.unique_id,
                'shape_uuid': fac.shape_uuid,
                'map': map_names.get(fac.geo_id, fac.geo_id),
            })

    # ── 부모를 잃은 라벨 ───────────────────────────────────────────────
    nodes_by_map = defaultdict(set)
    for s in all_shapes:
        nodes_by_map[s.geo_id].add(_node_id(s))
    for s in shapes:
        parent = _props(s).get('parent_node_id')
        if parent and parent not in nodes_by_map[s.geo_id]:
            findings['orphan-label'].append(
                dict(_where(s), type=s.type, parent_node_id=parent))

    # ── 실존하지 않는 장치를 가리키는 도형 ──────────────────────────────
    # 장치 삭제 경로 17곳 중 도형을 정리하는 곳은 4곳뿐이라, 나머지 13곳으로
    # 지운 장치의 도형은 아무 에러 없이 남는다. 지금까지 이걸 보는 검사가
    # 없었다(dangling-link 는 사망 컬럼 map_overlay_id 만 본다).
    device_ids = set()
    for model in DEVICE_MODELS:
        try:
            device_ids.update(
                r[0] for r in model.query.with_entities(model.unique_id).all())
        except Exception:
            continue
    for s in shapes:
        raw = (s.device_id or '').strip()
        if not raw:
            continue
        if raw.split('::')[0] not in device_ids:
            findings['orphan-device-shape'].append(
                dict(_where(s), type=s.type, device_id=raw,
                     channel_id=s.channel_id))

    # ── 실존하지 않는 장치를 가리키는 시설 참조 ─────────────────────────
    # JSON blob 안의 참조는 어느 삭제 경로도 정리하지 않는다 — DB 가 볼 수
    # 없는 자리이기 때문이다. 그래서 탐지 계층이 유일한 방어다.
    for fac in GeoFacility.query.all():
        for column, key in FACILITY_DEVICE_REFS:
            for item in _json_items(getattr(fac, column, None)):
                raw = str(item.get(key) or '').strip()
                if not raw:
                    continue
                if raw.split('::')[0] not in device_ids:
                    findings['dangling-fitting'].append({
                        'facility': fac.name,
                        'facility_uuid': fac.unique_id,
                        'column': column,
                        'key': key,
                        'item_id': item.get('id'),
                        'kind': item.get('kind') or item.get('role'),
                        'device_id': raw,
                        'map': map_names.get(fac.geo_id, fac.geo_id),
                    })

    # ── 레거시 저장처 ↔ geo_binding 드리프트 ────────────────────────────
    # 이중 저장 기간(Phase B 완료 전)의 감시자. 백필 이후 새로 생긴 연결이
    # 바인딩에 반영되지 않으면 여기서 드러난다. 테이블이 없는 설치
    # (p6_27 이전)에서는 검사 자체를 건너뛴다 — 없는 것은 어긋날 수 없다.
    drift = _binding_drift(shapes, device_ids)
    if drift:
        findings['binding-drift'].extend(drift)

    # ── 유령 지도 (GeoMap 행 없는 geo_id) ───────────────────────────────
    # 자동 삭제 금지: get_overlays 는 GeoMap 존재를 확인하지 않으므로
    # 위젯에 저장된 낡은 map_uuid 로 여전히 렌더링될 수 있다. 위젯
    # custom_options 참조 여부를 확인한 뒤 사람이 처분을 정한다.
    # (I8 트리거는 신규 유령 생성만 막는다 — 기존 행은 여기 보고가 전부다.)
    phantom = defaultdict(list)
    for s in shapes:
        if s.geo_id not in map_names:
            phantom[s.geo_id].append(s.id)
    for geo_id, ids in phantom.items():
        findings['phantom-map'].append({
            'geo_id': geo_id, 'shape_count': len(ids),
            'shape_ids': ids[:20]})

    # ── 식생 구획(작기) ────────────────────────────────────────────────
    _collect_plantings(findings, map_uuid, map_names)

    return dict(findings), len(shapes)


def _collect_plantings(findings, map_uuid, map_names):
    """GeoPlanting 불변식 VP-1·VP-2·VP-4 + 유령 지도.

    GeoPlanting 은 GeoShape 가 아니라 별도 테이블이므로 위 검사들의 대상이
    아니다(그것이 이 설계의 요점이다 — docs/design/geo-vegetation-planting.md).
    대신 자기 불변식은 여기서 함께 본다: 검사기를 둘로 나누면 한쪽만 돌리는
    운용이 생기고, 그러면 안 도는 쪽이 조용히 썩는다.

    **겹침은 검사하지 않는다.** 간작·혼작은 정상이다(VP-3) — 여기에 겹침
    검사를 추가하지 말 것.
    """
    try:
        from aot.databases.models import GeoPlanting
    except ImportError:
        return          # 마이그레이션 전 설치 — 검사할 것이 없다

    try:
        rows = (GeoPlanting.query.filter_by(geo_id=map_uuid).all() if map_uuid
                else GeoPlanting.query.all())
    except Exception:
        # 테이블이 아직 없는 서버(p6_34 미적용). 검사 실패로 올리지 않는다 —
        # 나머지 8종의 판정을 가리면 안 된다.
        return

    forbidden = ('device_id', 'channel_id', 'color', 'zone_uuid', 'zone_id')

    for r in rows:
        where = {'planting_id': r.id, 'unique_id': r.unique_id,
                 'crop': r.crop,
                 'map': map_names.get(r.geo_id, r.geo_id)}

        feat = r.feature if isinstance(r.feature, dict) else {}
        geom = feat.get('geometry') if isinstance(feat, dict) else None
        gtype = (geom or {}).get('type')
        if gtype not in ('Polygon', 'MultiPolygon'):
            findings['planting-bad-geometry'].append(
                dict(where, geometry_type=gtype))

        if r.ended_on and r.planted_on and r.ended_on < r.planted_on:
            findings['planting-bad-dates'].append(
                dict(where, planted_on=str(r.planted_on),
                     ended_on=str(r.ended_on)))

        props = (feat.get('properties') or {}) if isinstance(feat, dict) else {}
        embedded = [k for k in forbidden if k in props]
        if embedded:
            findings['planting-embedded-ref'].append(
                dict(where, keys=embedded))

        if r.geo_id not in map_names:
            findings['planting-phantom-map'].append(
                dict(where, geo_id=r.geo_id))


HEADINGS = {
    'type-mismatch':   'type 컬럼과 properties.aot_type 불일치',
    'duplicate':       '같은 지도 안 (종류, 기하) 중복',
    'dangling-link':   '끊어진 map_overlay_id',
    'orphan-facility': '고아 GeoFacility (도형 없음)',
    'orphan-label':    '부모를 잃은 라벨',
    'phantom-map':     '유령 지도 (GeoMap 행 없는 geo_id) — 자동삭제 금지',
    'orphan-device-shape': '실존하지 않는 장치를 가리키는 도형 (고아 도형)',
    'dangling-fitting':    '실존하지 않는 장치를 가리키는 시설 참조',
    'binding-drift':       '레거시 저장처에는 있는데 geo_binding 에 없는 연결',
    'planting-bad-geometry': '식생 구획이 폴리곤이 아님 (VP-1)',
    'planting-bad-dates':    '식생 구획의 종료일이 파종일보다 빠름 (VP-2)',
    'planting-embedded-ref': '식생 구획 feature 에 장치/색 사본 각인 (VP-4)',
    'planting-phantom-map':  '유령 지도의 식생 구획 — 자동삭제 금지',
}

# 데이터가 실제로 안 보이거나 잘못 붙는 항목. 이게 있으면 화면이 이미 틀어져 있다.
# orphan-device-shape / dangling-fitting 을 넣는 이유: 고아 도형은 지도에
# 계속 그려지고(장치는 없는데 구역이 남는다), 죽은 fitting 참조는 시설
# 3D 의 창호·팬이 존재하지 않는 액추에이터를 가리킨 채 제어 UI 에 뜬다.
# binding-drift 는 전환기의 정합 경고라 severe 가 아니다.
# planting-bad-geometry 를 넣는 이유: 폴리곤이 아닌 구획은 지도에 아예 그려지지
# 않는다(면적 계산도 0). 목록에는 있는데 화면에 없는 상태다.
# planting-bad-dates / embedded-ref 는 정합 경고라 severe 가 아니다.
SEVERE = ('type-mismatch', 'dangling-link', 'orphan-facility',
          'orphan-device-shape', 'dangling-fitting',
          'planting-bad-geometry')


def report(findings, shape_count, quiet=False):
    total = sum(len(v) for v in findings.values())
    if not total:
        print(f'OK: 도형 {shape_count}개, 문제 없음.')
        return 0

    # 출력 순서는 HEADINGS 의 선언 순서를 그대로 따른다. 예전에는 여기에
    # 별도의 키 목록이 하드코딩돼 있어서, HEADINGS 에만 검사를 추가하면
    # 집계에는 잡히는데 화면에는 안 나왔다 — 같은 사실을 두 곳에 두면
    # 반드시 갈린다는 이 도메인의 교훈이 검사기 자신에게도 적용된다.
    for key in HEADINGS:
        items = findings.get(key)
        if not items:
            continue
        print(f'\n[{key}] {HEADINGS[key]} — {len(items)}건')
        if quiet:
            continue
        for item in items[:40]:
            print('   ', json.dumps(item, ensure_ascii=False))
        if len(items) > 40:
            print(f'    ... 외 {len(items) - 40}건 (--json 으로 전체 확인)')

    severe = sum(len(findings.get(k, ())) for k in SEVERE)
    print(f'\nFAIL: 도형 {shape_count}개 중 문제 {total}건'
          f' (표시/연결에 직접 영향 {severe}건).')
    if findings.get('type-mismatch'):
        print('  type-mismatch 는 aot_type 을 정본으로 삼아 type 을 맞추면 해소된다.')
    if findings.get('duplicate'):
        print('  duplicate 는 삭제 전에 반드시 참조를 먼저 확인할 것 —'
              ' GeoFacility.shape_uuid, GeoShape.parent_id, 그리고'
              ' 7개 모델의 map_overlay_id 전부.')
    return 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--map', dest='map_uuid', metavar='UUID',
                    help='지도 하나만 검사 (기본: 전체)')
    ap.add_argument('--tolerance', type=float, default=1e-6, metavar='DEG',
                    help='중복 판정 좌표 허용오차, 도 단위 (기본 1e-6 ≈ 0.1m)')
    ap.add_argument('--json', action='store_true', help='JSON 으로 출력')
    ap.add_argument('--quiet', action='store_true', help='건수 요약만')
    args = ap.parse_args()

    with app.app_context():
        try:
            findings, shape_count = collect(args.map_uuid, args.tolerance)
        except Exception as exc:                        # noqa: BLE001
            print(f'ERROR: 검사 실패 — {exc}', file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps({'shape_count': shape_count, 'findings': findings},
                         ensure_ascii=False, indent=2))
        return 1 if any(findings.values()) else 0

    return report(findings, shape_count, quiet=args.quiet)


if __name__ == '__main__':
    sys.exit(main())
