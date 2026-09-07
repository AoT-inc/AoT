#!/usr/bin/env python3
"""geo_shape 피처에 남은 파생 `bbox` 정리 (기본 dry-run).

GeoJSON 의 `bbox` 는 좌표에서 언제든 다시 구할 수 있는 파생값이라 정본이
아니다. 그런데 turf 의 `lineSplit` 은 내부 rbush 색인의 검색 키로 쓰려고
결과 피처에 `bbox` 를 붙여서 돌려준다 — 그것도 `turf.square()` 로 정사각형
까지 부풀린 값이다(색인 용도에선 과대추정이 안전하니 turf 쪽은 정상).
그 조각이 그대로 레이어의 정본 feature 가 되고(aot-geo-preview.js
`_splitPipesByMains` → `l.feature = f`), saveDesign 이 feature 를 통째로 실어
보내 `equipment_collection` 번들에 영구히 저장됐다.

2026-09-06 실측 (로컬 라이브 DB): 지도 4곳의 `equipment_collection` 안
`pipe_branch` 142건이 `bbox` 를 갖고 있었고 그중 130건이 좌표와 어긋났다
— 위도 35도에서 정사각형(도 단위) 상자는 동서로 더 넓어지므로, 산양삼
지도의 최악 사례는 실제보다 75.1m 넓었다(김제 62.2m, p90 28.5m).

**되계산이 아니라 삭제**가 답이다:

* 저장된 값을 진실로 읽는 곳이 없다. 서버는 전부 좌표에서 직접 계산하고
  (`plot_journal._geom_bbox`, `ai_context_service`), 클라이언트에서 이 값이
  실제로 닿는 유일한 곳은 `aot-map-utils.js` 의 `booleanIntersects` 앞
  기각 프리필터다 — 상자가 커지면 위양성만 늘고 정밀검사에서 걸러진다.
* 반대로 남겨 두면 위험하다. `turf.bbox()` 는 피처에 `bbox` 가 있으면
  좌표를 보지 않고 그 값을 돌려주므로, 앞으로 누가 이 파이프의 실제 범위를
  물으면 틀린 답을 받는다. 게다가 기하가 편집돼도 `bbox` 는 따라 갱신되지
  않아(`aot-geo-geometry._trimOvershoot` 는 `feature.geometry` 만 교체한다)
  지금 맞는 12건도 다음 편집이면 틀어진다.

그래서 좌표와 일치하는 `bbox` 도 남기지 않고 전부 지운다. 저장 경로는
이제 (aot-geo-preview `_splitPipesByMains`, geo_overlays `_strip_derived_bbox`)
이 값을 다시 싣지 않도록 고쳤다 — 이 스크립트는 **이미 쌓인** 것을 치운다.

기본은 **dry-run** 이라 아무것도 쓰지 않는다. 실제 반영은 --apply.
운영 서버에 쓰기 전에는 반드시 백업을 먼저 뜰 것.

사용:
    python3 -m aot.scripts.fix_geo_feature_bbox              # 미리보기
    python3 -m aot.scripts.fix_geo_feature_bbox --apply      # 실제 반영
    python3 -m aot.scripts.fix_geo_feature_bbox --json       # 기계 판독
    python3 -m aot.scripts.fix_geo_feature_bbox --map <uuid> # 지도 하나만

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
from aot.databases.models import GeoMap, GeoShape
from aot.aot_flask.extensions import db


def _as_dict(raw):
    """GeoShape.feature 를 dict 로 정규화. SQLite 가 JSON 컬럼을 문자열로
    돌려주는 경우가 있어 여기서 흡수한다."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _members(feature):
    """행 하나가 품은 피처들. `equipment_collection` 은 FeatureCollection
    번들이라 자식들이, 나머지는 자기 자신이 대상이다."""
    feats = feature.get('features')
    if isinstance(feats, list):
        return [f for f in feats if isinstance(f, dict)]
    return [feature] if feature else []


def _real_bbox(geometry):
    """좌표에서 직접 구한 `[w, s, e, n]`. 좌표가 없으면 None."""
    coords = (geometry or {}).get('coordinates')
    box = None
    stack = [coords]
    while stack:
        item = stack.pop()
        if not isinstance(item, (list, tuple)) or not item:
            continue
        if (len(item) >= 2 and isinstance(item[0], (int, float))
                and isinstance(item[1], (int, float))):
            x, y = float(item[0]), float(item[1])
            box = ([x, y, x, y] if box is None else
                   [min(box[0], x), min(box[1], y),
                    max(box[2], x), max(box[3], y)])
            continue
        stack.extend(item)
    return box


def _ew_excess_m(stored, real):
    """저장된 상자가 실제보다 동서로 몇 m 넓은가. 비교 불가면 None.

    위도에 따라 경도 1도의 길이가 달라지므로 상자 중앙 위도에서 잰다."""
    if not (isinstance(stored, (list, tuple)) and len(stored) == 4 and real):
        return None
    try:
        lat = (real[1] + real[3]) / 2.0
        span = (float(stored[2]) - float(stored[0])) - (real[2] - real[0])
        return span * 111320.0 * math.cos(math.radians(lat))
    except (TypeError, ValueError):
        return None


def collect(map_uuid=None):
    """정리 대상을 모아 반환한다. 쓰기는 하지 않는다.

    도형(행) 단위로 묶어 보고한다 — 피처를 하나하나 늘어놓으면 수백 줄이
    되어 사람이 볼 수 없다(fix_geo_sprinkler_markers.py 와 같은 이유)."""
    findings = []

    shapes_q = GeoShape.query
    if map_uuid:
        shapes_q = shapes_q.filter_by(geo_id=map_uuid)

    map_names = {m.unique_id: m.name for m in GeoMap.query.all()}

    for shape in shapes_q.all():
        feature = _as_dict(shape.feature)
        if not feature:
            continue

        total = 0
        mismatched = 0
        worst_excess = None
        worst_sub_type = None
        sub_types = {}

        for member in _members(feature):
            if 'bbox' not in member:
                continue
            total += 1
            sub_type = (member.get('properties') or {}).get('sub_type') or '-'
            sub_types[sub_type] = sub_types.get(sub_type, 0) + 1

            real = _real_bbox(member.get('geometry'))
            stored = member.get('bbox')
            if real is None or not (isinstance(stored, (list, tuple))
                                    and len(stored) == 4):
                continue
            try:
                differs = any(abs(float(a) - b) > 1e-12
                              for a, b in zip(stored, real))
            except (TypeError, ValueError):
                differs = True
            if not differs:
                continue
            mismatched += 1
            excess = _ew_excess_m(stored, real)
            if excess is not None and (worst_excess is None
                                       or excess > worst_excess):
                worst_excess = excess
                worst_sub_type = sub_type

        if not total:
            continue

        findings.append({
            'shape_id': shape.id,
            'shape_type': shape.type,
            'map_uuid': shape.geo_id,
            'map_name': map_names.get(shape.geo_id, shape.geo_id),
            'bbox_count': total,
            'mismatched_count': mismatched,
            'worst_ew_excess_m': (round(worst_excess, 2)
                                  if worst_excess is not None else None),
            'worst_sub_type': worst_sub_type,
            'sub_types': sub_types,
        })

    return findings


def apply(findings):
    """collect() 결과를 DB 에 반영. 지운 bbox 개수를 돌려준다."""
    total_removed = 0

    for item in findings:
        shape = db.session.get(GeoShape, item['shape_id'])
        if not shape:
            continue

        # 반드시 사본을 고친다 — ORM 이 들고 있는 dict 를 제자리에서 고치면
        # flush 때 old/new 비교가 같다고 나와 UPDATE 가 통째로 생략된다
        # (JSON 컬럼은 MutableDict 가 아니라 값 비교로 변경을 판단한다).
        # fix_geo_sprinkler_markers.py 가 같은 함정을 이미 겪었다.
        feature = json.loads(json.dumps(_as_dict(shape.feature)))
        removed = 0
        for member in _members(feature):
            if member.pop('bbox', None) is not None:
                removed += 1
        if removed <= 0:
            continue

        shape.feature = feature
        total_removed += removed

    db.session.commit()
    return total_removed


def _report(findings, removed=None, quiet=False):
    if not quiet:
        for item in findings:
            worst = ''
            if item['mismatched_count'] and item['worst_ew_excess_m'] is not None:
                worst = (f", 최대 동서 +{item['worst_ew_excess_m']}m"
                         f"({item['worst_sub_type']})")
            kinds = ', '.join(f"{k} {v}개"
                              for k, v in sorted(item['sub_types'].items()))
            print(f"  [{item['map_name']}] shape#{item['shape_id']} "
                  f"({item['shape_type']}) "
                  f"bbox {item['bbox_count']}개 "
                  f"— 좌표와 어긋남 {item['mismatched_count']}개{worst} "
                  f"[{kinds}]")
        if findings:
            print()

    total = sum(f['bbox_count'] for f in findings)
    bad = sum(f['mismatched_count'] for f in findings)
    print(f"도형 {len(findings)}건 · bbox 합계 {total}개 (어긋남 {bad}개)")

    if removed is not None:
        print(f"반영: bbox {removed}개 제거")
    elif findings:
        print("dry-run — 아무것도 쓰지 않았습니다. 반영하려면 --apply")


def main():
    parser = argparse.ArgumentParser(
        description='geo_shape 피처에 남은 파생 bbox 정리')
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
