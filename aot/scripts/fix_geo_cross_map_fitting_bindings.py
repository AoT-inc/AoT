#!/usr/bin/env python3
"""한 장치가 **여러 지도**의 시설 설비에 동시에 매인 것을 정리한다(기본 dry-run).

## 무엇이 문제인가

`GeoBinding` 의 `spatial_id` 가 `<시설uuid>:<설비id>` 인 행은 "이 시설의 이
설비를 이 장치가 맡는다" 는 뜻이다. 같은 장치가 **서로 다른 지도**의 시설
설비에 동시에 매여 있으면, 한 지도에서 그 설비를 조작할 때 다른 지도의
시설에서도 같은 출력이 움직인다 — 화면상 서로 다른 온실의 측창이 함께
열린다. 시뮬레이션 장치라면 무해하지만 실물이면 남의 온실을 여는 일이다.

바인딩은 지우는 것이 아니라 **끝내는** 것이다(`valid_to` + `ended_reason`).
그래서 이 스크립트는 `device_binding.unbind(..., 'unbound')` 를 쓴다 — 행을
지우면 "이 슬롯을 언제 어떤 장치가 맡았나" 라는 이력이 사라지고, 그 이력이
곧 장치 교체를 관통하는 시계열 접합의 근거다(GeoBinding docstring 참조).

## 어떻게 쌓이나

한 번에 만들어지지 않는다. 새 시설에 매면서 앞의 것을 끊지 않으면 남는다.
2026-09-06 로컬 실측: 설비 바인딩이 있는 장치 28개 중 4개가 여러 지도에
걸쳐 있었고, 생성 시각이 전부 달랐다(8-27 08:50 / 8-27 10:08 / 8-28 13:16).

## 쓰는 법

    # 무엇이 걸쳐 있는지만 본다(아무것도 안 쓴다)
    python3 aot/scripts/fix_geo_cross_map_fitting_bindings.py

    # 특정 지도의 바인딩만 남기고 나머지를 끝낸다
    python3 aot/scripts/fix_geo_cross_map_fitting_bindings.py --keep-map 김제
    python3 aot/scripts/fix_geo_cross_map_fitting_bindings.py --keep-map 김제 --apply

`--keep-map` 은 지도 이름 또는 uuid. **남길 바인딩이 없는 장치는 건너뛴다** —
전부 끊으면 그 장치가 어디에도 안 매이게 되어, 두 지도에서 함께 사라진다.
그런 장치는 목록에 이유와 함께 남기고 사람이 정한다.

⚠ 운영 DB 에 쓰기 전에 반드시 백업을 먼저 뜰 것.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def _app():
    """조회·수정에 필요한 최소 앱 컨텍스트."""
    from flask import Flask
    from flask_babel import Babel

    from aot.aot_flask.extensions import db
    from aot.config import SQL_DATABASE_AOT

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///%s' % SQL_DATABASE_AOT
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['BABEL_DEFAULT_LOCALE'] = 'ko'
    Babel(app)
    db.init_app(app)
    return app, db


def _device_name(device_id):
    from aot.databases.models import Input, Output
    for model in (Output, Input):
        row = model.query.filter_by(unique_id=device_id).first()
        if row is not None:
            return row.name or device_id
    return device_id


def collect():
    """{device_id: [(binding, facility, map_name)]} — 여러 지도에 걸친 것만."""
    from aot.databases.models import GeoBinding, GeoFacility, GeoMap

    rows = GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'fitting',
        GeoBinding.valid_to.is_(None)).all()

    facs, maps = {}, {}
    by_device = collections.defaultdict(list)
    for b in rows:
        fac_uuid = b.spatial_id.split(':')[0]
        if fac_uuid not in facs:
            facs[fac_uuid] = GeoFacility.query.filter_by(
                unique_id=fac_uuid).first()
        fac = facs[fac_uuid]
        if fac is None:
            continue                       # 시설이 사라진 고아 — 이 도구 소관 아님
        if fac.geo_id not in maps:
            m = GeoMap.query.filter_by(unique_id=fac.geo_id).first()
            maps[fac.geo_id] = (m.name if m else fac.geo_id)
        by_device[b.device_id].append((b, fac, maps[fac.geo_id]))

    return {d: items for d, items in by_device.items()
            if len({i[2] for i in items}) > 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--keep-map', help='남길 지도 이름 또는 uuid')
    ap.add_argument('--apply', action='store_true',
                    help='실제로 바인딩을 끝낸다(기본은 dry-run)')
    args = ap.parse_args()

    app, db = _app()
    with app.app_context():
        from aot.aot_flask.geo import device_binding

        found = collect()
        if not found:
            print('여러 지도에 걸친 설비 바인딩 없음.')
            return 0

        print('여러 지도에 걸친 장치 %d개' % len(found))
        to_end, skipped = [], []
        for device_id, items in sorted(found.items(),
                                       key=lambda kv: _device_name(kv[0])):
            name = _device_name(device_id)
            print('\n=== %s ===' % name)
            keep = [i for i in items
                    if args.keep_map in (i[2], i[1].geo_id)] if args.keep_map else []
            for b, fac, map_name in sorted(items, key=lambda x: x[2]):
                mark = '  '
                if args.keep_map:
                    mark = '남김' if (b, fac, map_name) in keep else '끊음'
                print('  [%s] %-10s %-12s %s'
                      % (mark, map_name, fac.name or '-',
                         b.spatial_id.split(':', 1)[1]))
            if not args.keep_map:
                continue
            if not keep:
                skipped.append(name)
                print('  ⚠ 남길 바인딩이 없다 — 건너뛴다(전부 끊으면 어디에도 '
                      '안 매인 장치가 된다). 사람이 정할 것.')
                continue
            to_end += [i[0] for i in items if i not in keep]

        if not args.keep_map:
            print('\n(--keep-map <지도> 를 주면 그 지도만 남기고 나머지를 끝낸다)')
            return 0

        print('\n끝낼 바인딩 %d개, 건너뛴 장치 %d개%s'
              % (len(to_end), len(skipped),
                 (': ' + ', '.join(skipped)) if skipped else ''))
        if not args.apply:
            print('(예행 — 실제로 반영하려면 --apply. 그 전에 DB 백업.)')
            return 0

        for b in to_end:
            device_binding.unbind(b.unique_id, 'unbound')
        db.session.commit()
        print('%d개 종료(ended_reason=unbound).' % len(to_end))
        return 0


if __name__ == '__main__':
    sys.exit(main())
