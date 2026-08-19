#!/usr/bin/env python3
"""시설 bay 의 작물(`bays[].crop`)을 식생 구획(GeoPlot)으로 옮긴다.

설계 정본: docs/design/geo-vegetation-plot.md (Phase 2)

## 왜 옮기는가

작물 정보가 두 곳에 있다. 노지는 `geo_plot`, 온실은 `GeoFacility.bays[].crop`
— 그래서 "무엇이 심겨 있나" 를 묻는 코드가 두 소스를 각자 기억해야 하고,
`bays[].crop` 은 **문자열 하나**라 파종일도 이력도 없다. 다음 작물을 적으면
이전 작물이 그냥 사라진다(연작 판단이 불가능하다).

## 기하는 참조가 아니라 **스냅샷**이다

bay 폴리곤(`GeoShape type='facility_bay'`)을 가리키지 않고 그 시점 기하를
복사한다. 나중에 `bay_count` 를 바꾸면 bay 가 다시 나뉘는데, 과거 작기가 그걸
따라가면 "작년에 여기 뭐가 있었나" 의 답이 조용히 달라진다. 출처는
`source_kind='bay_snapshot'`, `source_ref='<facility_uuid>:<bay_id>'` 로 남긴다.

## 옮기지 않는 것

- 기하를 못 찾는 bay(`polygon_shape_uuid` 없음 — bay_start~bay_end 범위로만
  정의된 구역). 기하 없이 만들면 지도에 그려지지 않는 유령 구획이 된다.
  **보고만 하고 만들지 않는다** — 죽은 참조를 승격시키면 고아가 정본이 된다
  (backfill_geo_binding 과 같은 원칙).
- 이미 같은 bay 에서 옮겨진 것(`source_ref` 중복). 재실행해도 두 벌이 되지 않는다.

`bays[].crop` 은 **지우지 않는다.** 읽기 경로가 GeoPlot 우선 + bay 폴백으로
돌고 있어, 폴백이 0 인 것을 운영에서 확인한 뒤에야 걷어낼 수 있다.

사용:
    python3 -m aot.scripts.backfill_facility_bay_crops            # 미리보기(쓰기 없음)
    python3 -m aot.scripts.backfill_facility_bay_crops --apply    # 실제 반영(DB 백업 후)
    python3 -m aot.scripts.backfill_facility_bay_crops --json     # 기계 판독

종료 코드 0 = 정상, 1 = 옮길 것이 남음(dry-run), 2 = 실패.
"""
import argparse
import json
import sys
from datetime import date


def _plan(app):
    """옮길 것 / 건너뛸 것을 계산한다. 쓰기 없음."""
    from aot.databases.models import GeoFacility, GeoPlot, GeoShape

    planned, skipped = [], []

    # 이미 옮겨진 bay 는 source_ref 로 알아본다.
    existing = {p.source_ref for p in
                GeoPlot.query.filter_by(source_kind='bay_snapshot').all()
                if p.source_ref}

    for fac in GeoFacility.query.all():
        bays = fac.bays if isinstance(fac.bays, list) else []
        for bay in bays:
            if not isinstance(bay, dict):
                continue
            crop = (bay.get('crop') or '').strip()
            if not crop:
                continue                      # 작물이 없는 bay 는 옮길 것이 없다

            bay_id = str(bay.get('id') or '')
            ref = '%s:%s' % (fac.unique_id, bay_id)
            if ref in existing:
                skipped.append({'facility': fac.name, 'bay': bay_id,
                                'subject': crop, 'why': 'already-migrated'})
                continue

            shape_uuid = bay.get('polygon_shape_uuid')
            shape = (GeoShape.query.filter_by(unique_id=shape_uuid).first()
                     if shape_uuid else None)
            geom = None
            if shape is not None:
                feat = shape.feature if isinstance(shape.feature, dict) else {}
                geom = (feat or {}).get('geometry')

            if not geom or geom.get('type') not in ('Polygon', 'MultiPolygon'):
                # 기하 없이 만들면 지도에 안 그려지는 구획이 된다.
                skipped.append({'facility': fac.name, 'bay': bay_id,
                                'subject': crop, 'why': 'no-geometry'})
                continue

            planned.append({
                'facility': fac.name,
                'facility_uuid': fac.unique_id,
                'bay': bay_id,
                'bay_name': bay.get('name'),
                'subject': crop,
                'geo_id': shape.geo_id,
                'geometry': geom,
                'source_ref': ref,
            })

    return planned, skipped


def _apply(app, planned):
    """계획대로 GeoPlot 을 만든다. 게이트웨이(plot_io)를 지나간다."""
    from aot.aot_flask.geo import plot_io

    made, failed = [], []
    for item in planned:
        result, err = plot_io.save_plot({
            'map_uuid': item['geo_id'],
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': item['geometry']},
            'subject': item['subject'],
            'name': item['bay_name'] or item['bay'],
            # 파종일을 모른다. 오늘로 둔다 — 없는 날짜를 지어내는 것보다
            # "언제 심었는지 모른다" 를 사람이 고치게 하는 편이 낫다.
            'started_on': date.today().isoformat(),
            'source_kind': 'bay_snapshot',
            'source_ref': item['source_ref'],
        })
        if err:
            failed.append(dict(item, error=err))
        else:
            made.append({'subject': item['subject'], 'bay': item['bay'],
                         'unique_id': result['unique_id']})
    return made, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true', help='실제로 반영한다')
    ap.add_argument('--json', action='store_true', help='기계 판독 출력')
    args = ap.parse_args()

    try:
        from aot.aot_flask.app import create_app
        app = create_app()
    except Exception as exc:
        print('검사 실패: 앱을 만들 수 없습니다 — %s' % exc, file=sys.stderr)
        return 2

    with app.app_context():
        try:
            planned, skipped = _plan(app)
        except Exception as exc:
            print('검사 실패: %s' % exc, file=sys.stderr)
            return 2

        made, failed = ([], [])
        if args.apply and planned:
            made, failed = _apply(app, planned)

    if args.json:
        print(json.dumps({'planned': [{k: v for k, v in p.items()
                                       if k != 'geometry'} for p in planned],
                          'skipped': skipped, 'made': made, 'failed': failed},
                         ensure_ascii=False, indent=1))
    else:
        if not planned and not skipped:
            print('OK: 시설 bay 에 옮길 작물이 없습니다.')
        for p in planned:
            mark = '옮김' if args.apply else '옮길 것'
            print('  [%s] %s / %s → %s' % (mark, p['facility'], p['bay'], p['subject']))
        for s in skipped:
            print('  [건너뜀:%s] %s / %s (%s)' % (s['why'], s['facility'],
                                                  s['bay'], s['subject']))
        for f in failed:
            print('  [실패] %s / %s — %s' % (f['facility'], f['bay'], f['error']))
        if planned and not args.apply:
            print('\n미리보기입니다. 반영하려면 --apply (DB 백업 후).')
        if args.apply:
            print('\n%d건 생성, %d건 실패.' % (len(made), len(failed)))
            print('`bays[].crop` 은 그대로 둡니다 — 읽기 폴백이 0 인 것을 '
                  '확인한 뒤에 걷어냅니다.')

    if failed:
        return 2
    return 1 if (planned and not args.apply) else 0


if __name__ == '__main__':
    sys.exit(main())
