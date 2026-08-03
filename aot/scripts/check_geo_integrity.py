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

검사 항목 5종:
  type-mismatch   type 컬럼 ≠ properties.aot_type
  duplicate       같은 지도 안에서 (종류, 기하) 가 겹치는 도형.
                  좌표는 --tolerance(기본 1e-6 도, 약 0.1m) 로 반올림해 비교한다
                  — 완전 일치만 보면 저장 사이에 라벨이 몇 m 움직인 중복을 놓친다.
  dangling-link   Input/Output/PID/Trigger/Conditional/CustomController/Function
                  의 map_overlay_id 가 없는 GeoShape.id 를 가리킴
  orphan-facility GeoFacility.shape_uuid 가 없는 GeoShape 를 가리킴
  orphan-label    라벨의 parent_node_id 가 어떤 도형에도 해소되지 않음

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
    Conditional, CustomController, Function, GeoFacility, GeoMap, GeoShape,
    Input, Output, PID, Trigger)


# map_overlay_id 를 들고 있는 모델 전부. 하나라도 빠지면 그 모델의 끊어진
# 참조를 놓친다 — 2026-08-03 정리 작업이 이 목록을 안 보고 진행해 Input 5건 +
# Output 6건의 참조를 끊었다.
OVERLAY_LINK_MODELS = (
    Input, Output, PID, Trigger, Conditional, CustomController, Function)

# 중복 판정에서 제외하는 종류. equipment_collection 은 한 행이
# FeatureCollection 을 통째로 담는 번들이라 기하 비교 대상이 아니다.
DUP_EXEMPT_TYPES = {'equipment_collection'}


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

    return dict(findings), len(shapes)


HEADINGS = {
    'type-mismatch':   'type 컬럼과 properties.aot_type 불일치',
    'duplicate':       '같은 지도 안 (종류, 기하) 중복',
    'dangling-link':   '끊어진 map_overlay_id',
    'orphan-facility': '고아 GeoFacility (도형 없음)',
    'orphan-label':    '부모를 잃은 라벨',
}

# 데이터가 실제로 안 보이거나 잘못 붙는 항목. 이게 있으면 화면이 이미 틀어져 있다.
SEVERE = ('type-mismatch', 'dangling-link', 'orphan-facility')


def report(findings, shape_count, quiet=False):
    total = sum(len(v) for v in findings.values())
    if not total:
        print(f'OK: 도형 {shape_count}개, 문제 없음.')
        return 0

    for key in ('type-mismatch', 'duplicate', 'dangling-link',
                'orphan-facility', 'orphan-label'):
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
