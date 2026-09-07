#!/usr/bin/env python3
"""시설로 등록되지 않은 `facility` 도형 정리 (기본 dry-run).

`type='facility'` 인데 `GeoFacility` 행이 없는 도형은 지도에 그려지지만
**눌러도 열리지 않는다** — 시설 모달이 뜨려면 GeoFacility 가 있어야 한다.
필지 모달의 목록은 그런 줄을 아예 빼므로 화면에서는 더 안 보인다. 그래서
`check_geo_integrity` 의 `unregistered-facility-shape` 가 유일한 통로다.

실물은 대체로 **그리다 만 초안**이다. 2026-09-06 김제 지도 실측: 4건 전부
2026-05 생성이고 이름이 기본값(`New facility` 둘, 이름 없음 하나)이거나
종류가 어긋나 있었다(`Main Pipe` — 배관 이름인데 `type='facility'` 폴리곤,
`sub_type='pipe_main'`). 하나는 `drawType: rectangle` 과 원본 draw id 를
그대로 달고 있었다. 같은 지도의 정상 시설 넷은 전부 제 이름과 GeoFacility
행을 갖고 있었다.

**참조를 먼저 확인한다.** 검사기가 경고하는 그대로다 — 지우기 전에
`GeoFacility.shape_uuid`, `GeoShape.parent_id`, 7개 모델의 `map_overlay_id`
를 전부 봐야 한다. 여기에 `geo_binding`(공간↔장치), `geo_plot.facility_uuid`,
라벨의 `parent_node_id` 까지 더해 훑고, **하나라도 걸리면 그 도형은 지우지
않고 보고만 한다.** 사람이 한 번 손으로 확인하고 끝내는 것보다 도구가 매번
확인하는 편이 낫다 — 서버마다 상황이 다르다.

`geo_containment_cache` 는 참조로 세지 않는다. 기하에서 재계산되는 파생
캐시이고 삭제 후 버린다(`_drop_containment_cache`).

⚠ 이름이 붙어 있고 참조가 없는 도형도 대상에 든다. **dry-run 출력의 이름과
면적을 반드시 눈으로 확인할 것** — "열리지 않는 시설 도형" 이라는 사실만으로
사용자가 그 자리를 기억하지 못한다고 단정할 수는 없다.

기본은 **dry-run** 이라 아무것도 쓰지 않는다. 실제 반영은 --apply.
운영 서버에 쓰기 전에는 반드시 백업을 먼저 뜰 것.

사용:
    python3 -m aot.scripts.fix_geo_unregistered_facility_shapes           # 미리보기
    python3 -m aot.scripts.fix_geo_unregistered_facility_shapes --apply   # 실제 반영
    python3 -m aot.scripts.fix_geo_unregistered_facility_shapes --json    # 기계 판독
    python3 -m aot.scripts.fix_geo_unregistered_facility_shapes --map <uuid>

종료 코드 0 = 정상(정리할 게 없거나 반영 완료), 1 = 정리 대상 있음(dry-run),
2 = 실행 실패.

@phase active
@stability stable
"""
import argparse
import json
import math
import sys

from aot.start_flask_ui import app
from aot.aot_flask.extensions import db
from aot.databases.models import (
    Conditional, CustomController, Function, GeoBinding, GeoFacility, GeoMap,
    GeoPlot, GeoShape, Input, Output, PID, Trigger)


# `map_overlay_id` 를 들고 있는 모델 전부 — check_geo_integrity 의
# OVERLAY_LINK_MODELS 와 같은 7종이다. 하나라도 빠지면 그 모델이 가리키던
# 도형을 조용히 지우고 참조를 끊는다(2026-08-03 정리가 그렇게 Input 5건 +
# Output 6건을 끊었다).
OVERLAY_LINK_MODELS = (
    Input, Output, PID, Trigger, Conditional, CustomController, Function)


def _feature(shape):
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
    return _props(shape).get('node_id') or shape.unique_id


def _area_m2(shape):
    """폴리곤 넓이(제곱미터). 등장방형 근사 — 지역 규모에서 충분하다."""
    geom = _feature(shape).get('geometry') or {}
    coords = geom.get('coordinates')
    if geom.get('type') != 'Polygon' or not coords:
        return None
    ring = coords[0]
    if not ring or len(ring) < 3:
        return None
    try:
        lat0 = sum(p[1] for p in ring) / len(ring)
        k = math.cos(math.radians(lat0))
        total = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0] * k * 111320.0, ring[i][1] * 110574.0
            x2, y2 = ring[i + 1][0] * k * 111320.0, ring[i + 1][1] * 110574.0
            total += x1 * y2 - x2 * y1
        return abs(total) / 2.0
    except (TypeError, ValueError, IndexError):
        return None


def _references(shape, all_shapes):
    """이 도형을 가리키는 살아 있는 참조 전부. 비어 있어야 지울 수 있다."""
    refs = []

    for child in all_shapes:
        if child.parent_id == shape.id:
            refs.append({'kind': 'geo_shape.parent_id',
                         'detail': 'shape#%s (%s)' % (child.id, child.type)})

    for model in OVERLAY_LINK_MODELS:
        if not hasattr(model, 'map_overlay_id'):
            continue
        for row in model.query.filter_by(map_overlay_id=shape.id).all():
            refs.append({'kind': '%s.map_overlay_id' % model.__name__,
                         'detail': getattr(row, 'name', None) or row.unique_id})

    for b in GeoBinding.query.filter_by(spatial_kind='shape',
                                        spatial_id=shape.unique_id).all():
        if b.valid_to is None:
            refs.append({'kind': 'geo_binding',
                         'detail': '%s → %s' % (b.role, b.device_id)})

    if hasattr(GeoPlot, 'facility_uuid'):
        for p in GeoPlot.query.filter_by(facility_uuid=shape.unique_id).all():
            refs.append({'kind': 'geo_plot.facility_uuid',
                         'detail': getattr(p, 'name', None) or p.unique_id})

    node = _node_id(shape)
    for other in all_shapes:
        if other.id == shape.id:
            continue
        if _props(other).get('parent_node_id') == node:
            refs.append({'kind': 'parent_node_id',
                         'detail': 'shape#%s (%s)' % (other.id, other.type)})

    return refs


def collect(map_uuid=None):
    """정리 대상과 그 참조를 모아 반환한다. 쓰기는 하지 않는다."""
    registered = {f.shape_uuid for f in GeoFacility.query.all()}
    all_shapes = GeoShape.query.all()
    map_names = {m.unique_id: m.name for m in GeoMap.query.all()}

    findings = []
    for shape in all_shapes:
        if shape.type != 'facility' or shape.unique_id in registered:
            continue
        if map_uuid and shape.geo_id != map_uuid:
            continue
        props = _props(shape)
        refs = _references(shape, all_shapes)
        area = _area_m2(shape)
        findings.append({
            'shape_id': shape.id,
            'shape_uuid': shape.unique_id,
            'map_uuid': shape.geo_id,
            'map_name': map_names.get(shape.geo_id, shape.geo_id),
            'name': props.get('label_name') or props.get('name'),
            'sub_type': props.get('sub_type'),
            'area_m2': round(area) if area is not None else None,
            'created_at': str(shape.created_at)[:19],
            'references': refs,
            'deletable': not refs,
        })
    return findings


def apply(findings):
    """참조가 없는 것만 지운다. 지운 개수를 돌려준다.

    삭제 자체는 ORM 으로 한 행씩 한다 — 벌크 `Query.delete()` 는 트리거는
    타지만 ORM 연쇄를 건너뛴다. 여기서 기대는 것은 DB 트리거 쪽이다
    (I3 시설·setpoint·bay 연쇄, I4 map_overlay_id NULL, GB-4 바인딩 종료).
    """
    deletable = [f for f in findings if f['deletable']]
    for item in deletable:
        row = db.session.get(GeoShape, item['shape_id'])
        if row is None:
            continue
        db.session.delete(row)
    db.session.commit()

    if deletable:
        # 기하가 바뀌었으니 포함 관계 캐시는 낡았다. 지우기만 하므로 과하게
        # 불러도 손해는 재계산 비용뿐이다(geo_overlays 와 같은 관례).
        try:
            from aot.aot_flask.geo.geo_overlays import _drop_containment_cache
            _drop_containment_cache()
        except Exception:
            pass
    return len(deletable)


def _report(findings, removed=None, quiet=False):
    blocked = [f for f in findings if not f['deletable']]
    if not quiet:
        for item in findings:
            name = item['name'] or '(이름 없음)'
            area = ('%s m2' % item['area_m2']) if item['area_m2'] is not None else '면적 미상'
            sub = (' sub_type=%s' % item['sub_type']) if item['sub_type'] else ''
            mark = '지움  ' if item['deletable'] else '남김  '
            print('  %s[%s] shape#%-4s %-18s %-10s %s%s'
                  % (mark, item['map_name'], item['shape_id'], name, area,
                     item['created_at'], sub))
            for r in item['references']:
                print('           ↳ 참조: %s — %s' % (r['kind'], r['detail']))
        if findings:
            print()

    print('미등록 facility 도형 %d건 (참조 없어 지울 수 있는 것 %d건)'
          % (len(findings), len(findings) - len(blocked)))
    if blocked:
        print('  참조가 있어 남긴 것 %d건 — 위 ↳ 줄을 먼저 정리할 것' % len(blocked))

    if removed is not None:
        print('반영: 도형 %d개 삭제' % removed)
    elif findings:
        print('dry-run — 아무것도 쓰지 않았습니다. 반영하려면 --apply')
        print('⚠ 지도에서 폴리곤이 사라집니다. 위 이름·면적을 눈으로 확인할 것.')


def main():
    parser = argparse.ArgumentParser(
        description='시설로 등록되지 않은 facility 도형 정리')
    parser.add_argument('--apply', action='store_true',
                        help='실제로 DB에 반영 (기본은 dry-run)')
    parser.add_argument('--map', dest='map_uuid', default=None,
                        help='지도 하나만 대상으로')
    parser.add_argument('--json', action='store_true', help='기계 판독용 출력')
    parser.add_argument('--quiet', action='store_true', help='요약만')
    args = parser.parse_args()

    try:
        with app.app_context():
            findings = collect(args.map_uuid)
            removed = apply(findings) if args.apply else None
    except Exception as err:  # noqa: BLE001 — 검사 실패는 종료코드 2로 구분
        print('실행 실패: %s' % err, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({'findings': findings, 'removed': removed},
                         ensure_ascii=False, indent=2))
    else:
        _report(findings, removed, quiet=args.quiet)

    if args.apply:
        return 0
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
