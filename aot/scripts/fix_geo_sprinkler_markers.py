#!/usr/bin/env python3
"""geo/design 스프링클러 점 마커 잔존/중복 정리 (기본 dry-run).

정본 이미터는 `sprinkler_coverage`(원형 커버리지) 하나뿐이고, 점 마커
(`sub_type='sprinkler'`)는 편집 세션에서만 보이는 화면용 장식이다
(aot-geo-stats.js "sprinkler_coverage is the canonical emitter; sprinkler dot
markers are ephemeral", plot_journal._EMITTER_SUB_TYPE 동일 규칙). 그런데
지금까지 이 마커가 실제로는 저장 페이로드에 실려 `equipment_collection`
번들에 영구 저장되고 있었다 — 클라이언트의 `_loadAllFeatures` 는 이 점을
애초에 다시 불러오지 않으므로, 한 번 저장된 점은 다음 세션에서 클라이언트
자신도 보지 못해 지울 방법이 없었다. 이미터를 재생성(반경/유량 조정)할
때마다 지우지 못한 옛 사본 위에 새 사본만 계속 쌓였다.

2026-09-03 실측 (나주 지도, `GeoShape.type='equipment_collection'` uuid 접두
`eea6b77a`): 정본 이미터(`sprinkler_coverage`) 274개에 점 마커
(`sprinkler`) 2,466개 — 고유 좌표 676곳 중 한 지점에 최대 8겹, 274곳은
옛 유량(850)과 새 유량(70)이 함께 남아 있었다. 저장 경로는 이제
(aot-geo-design-v3.js collectLayer, aot-geo-preview.js collectEq,
geo_overlays._is_ephemeral_sprinkler_marker) 이 마커를 앞으로 저장하지
않도록 고쳤다 — 이 스크립트는 **이미 쌓인** 데이터를 치운다.

정리 규칙: `equipment_collection` 번들 안에서 `sub_type == 'sprinkler'` 인
Point 피처를 **전부** 제거한다(중복분만이 아니라 전부 — 애초에 저장돼선
안 되는 종류이므로 유일한 사본도 남기지 않는다). `sprinkler_coverage`
및 다른 장비(배관 등)는 그대로 둔다.

기본은 **dry-run** 이라 아무것도 쓰지 않는다. 실제 반영은 --apply.
운영 서버에 쓰기 전에는 반드시 백업을 먼저 뜰 것.

사용:
    python3 -m aot.scripts.fix_geo_sprinkler_markers              # 미리보기
    python3 -m aot.scripts.fix_geo_sprinkler_markers --apply      # 실제 반영
    python3 -m aot.scripts.fix_geo_sprinkler_markers --json       # 기계 판독
    python3 -m aot.scripts.fix_geo_sprinkler_markers --map <uuid> # 지도 하나만

종료 코드 0 = 정상(정리할 게 없거나 반영 완료), 1 = 정리 대상 있음(dry-run),
2 = 실행 실패.

@phase active
@stability stable
"""
import argparse
import json
import sys

from aot.start_flask_ui import app
from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape


def _bundle(shape):
    """GeoShape.feature 를 dict 로 정규화. SQLite 가 JSON 컬럼을 문자열로
    돌려주는 경우가 있어 여기서 흡수한다."""
    raw = shape.feature
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def collect(map_uuid=None):
    """정리 대상을 모아 반환한다. 쓰기는 하지 않는다.

    번들(shape) 단위로 하나씩 묶어 보고한다 — 마커 하나하나를 늘어놓으면
    수천 줄이 되어 사람이 볼 수 없다(fix_geo_theme_drift.py 와 같은 이유).
    """
    findings = []

    shapes_q = GeoShape.query.filter_by(type='equipment_collection')
    if map_uuid:
        shapes_q = shapes_q.filter_by(geo_id=map_uuid)

    map_names = {m.unique_id: m.name for m in GeoMap.query.all()}

    for shape in shapes_q.all():
        bundle = _bundle(shape)
        feats = bundle.get('features') if isinstance(bundle, dict) else None
        if not isinstance(feats, list):
            continue

        marker_node_ids = []
        by_coord = {}
        for f in feats:
            if not isinstance(f, dict):
                continue
            if (f.get('properties') or {}).get('sub_type') != 'sprinkler':
                continue
            marker_node_ids.append(f.get('properties', {}).get('node_id'))
            coords = (f.get('geometry') or {}).get('coordinates')
            if isinstance(coords, list) and len(coords) >= 2:
                key = (round(coords[0], 6), round(coords[1], 6))
                by_coord[key] = by_coord.get(key, 0) + 1

        if not marker_node_ids:
            continue

        findings.append({
            'shape_id': shape.id,
            'map_uuid': shape.geo_id,
            'map_name': map_names.get(shape.geo_id, shape.geo_id),
            'marker_count': len(marker_node_ids),
            'distinct_locations': len(by_coord),
            'max_duplicate_at_one_point': max(by_coord.values()) if by_coord else 0,
            'other_feature_count': len(feats) - len(marker_node_ids),
        })

    return findings


def apply(findings):
    """collect() 결과를 DB 에 반영. 지운 마커 개수를 돌려준다."""
    total_removed = 0

    for item in findings:
        shape = db.session.get(GeoShape, item['shape_id'])
        if not shape:
            continue

        # 반드시 사본을 고친다 — _bundle() 이 돌려주는 dict 를 제자리에서
        # 고치면 ORM 이 들고 있는 "로드된 값"까지 함께 바뀌어, flush 때
        # old/new 비교가 같다고 나와 UPDATE 가 통째로 생략된다(JSON 컬럼은
        # MutableDict 가 아니라 값 비교로 변경을 판단한다). fix_geo_theme_drift.py
        # 가 이미 한 번 겪은 실패 모드와 동일하다.
        bundle = json.loads(json.dumps(_bundle(shape)))
        feats = bundle.get('features')
        if not isinstance(feats, list):
            continue

        before = len(feats)
        feats = [f for f in feats
                 if not (isinstance(f, dict)
                         and (f.get('properties') or {}).get('sub_type') == 'sprinkler')]
        removed = before - len(feats)
        if removed <= 0:
            continue

        bundle['features'] = feats
        shape.feature = bundle
        total_removed += removed

    db.session.commit()
    return total_removed


def _report(findings, removed=None, quiet=False):
    if not quiet:
        for item in findings:
            print(f"  [{item['map_name']}] shape#{item['shape_id']} "
                  f"점 마커 {item['marker_count']}개 "
                  f"(고유 좌표 {item['distinct_locations']}곳, "
                  f"최대 중복 {item['max_duplicate_at_one_point']}겹) "
                  f"— 다른 장비 {item['other_feature_count']}개는 그대로 둠")
        if findings:
            print()

    total_markers = sum(f['marker_count'] for f in findings)
    print(f"equipment_collection {len(findings)}건 · 점 마커 합계 {total_markers}개")

    if removed is not None:
        print(f"반영: 점 마커 {removed}개 제거")
    elif findings:
        print("dry-run — 아무것도 쓰지 않았습니다. 반영하려면 --apply")


def main():
    parser = argparse.ArgumentParser(
        description='geo/design 스프링클러 점 마커(sub_type=sprinkler) 잔존/중복 정리')
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
        print(f"실행 실패: {err}", file=sys.stderr)
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
