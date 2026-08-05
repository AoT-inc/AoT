#!/usr/bin/env python3
"""지도 테마색 갈래 정리 (기본 dry-run).

색의 정본은 `GeoSetting.theme_config`(전역 싱글톤) 하나여야 한다. 그런데 같은
질문("이 도형은 무슨 색인가")에 네 곳이 제각기 답하고 있었다:

  ① GeoSetting.theme_config              — 정본
  ② GeoMap.state_json['theme_config']    — 지도별 override
  ③ GeoShape.feature.properties.color    — 도형에 각인된 색
  ④ localStorage.aot_config_color_*      — 브라우저별 잔재

②는 geo/design 에서 색을 고를 때 "그 세션에서 만진 키만 담긴 부분 dict"가 지도
저장에 함께 실려 생겼고, AoT_map 위젯이 이를 전역 위에 덮어써서 그 지도만 옛
색으로 굳었다(전역을 바꿔도 안 바뀜). ③은 도형을 그릴 때 계산한 색을 다시
properties 에 써 넣던 sync-back 의 산물로, 테마를 바꿔도 그 도형만 옛 색으로
되돌아왔다. 게다가 위젯은 ③을 아예 읽지 않아서, 같은 도형이 geo/design 화면과
위젯에서 서로 다른 색으로 그려졌다.

읽기 경로는 전부 정본 하나만 보도록 고쳤다(static/js/common/aot-geo-theme-colors.js,
geo/widget/maps.py). 이 스크립트는 DB 에 남아 있는 ②③ 을 지우고, 색 해석의
입력인 device_type 이 비어 있는 도형을 채운다. ④는 geo/design 페이지가 로드될 때
스스로 지운다(aot-geo-ui.js applyThemeConfig).

정리 항목 3종:
  map-theme     GeoMap.state_json 의 theme_config 키 제거
  shape-color   GeoShape.feature.properties 의 color/fillColor 제거
                (type=aot_device/device 인 장치 도형만)
  device-type   device_id 는 있는데 device_type 이 비어 있는 장치 도형에
                실제 종류(input/output/function)를 채움

기본은 **dry-run** 이라 아무것도 쓰지 않는다. 실제 반영은 --apply.
운영 서버에 쓰기 전에는 반드시 백업을 먼저 뜰 것.

사용:
    python3 -m aot.scripts.fix_geo_theme_drift              # 미리보기(쓰기 없음)
    python3 -m aot.scripts.fix_geo_theme_drift --apply      # 실제 반영
    python3 -m aot.scripts.fix_geo_theme_drift --json       # 기계 판독
    python3 -m aot.scripts.fix_geo_theme_drift --map <uuid> # 지도 하나만

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
from aot.databases.models import (
    Conditional, CustomController, Function, GeoMap, GeoShape,
    Input, Output, PID, Trigger)


# 장치 도형의 type 컬럼 값. 'device' 는 레거시(읽기 경로가 aot_device 로 정규화).
DEVICE_SHAPE_TYPES = ('aot_device', 'device')

# 도형에 각인돼 있던 스타일 키. 색의 정본이 아니므로 지운다.
BAKED_STYLE_KEYS = ('color', 'fillColor')

# device_type 백필용 — 모델과 테마 키의 대응. Function 계열(PID/Trigger/
# Conditional/CustomController/Function)은 전부 'function' 하나로 수렴한다
# (AoTGeoTheme.normalizeDeviceType 과 같은 규칙).
DEVICE_TYPE_MODELS = (
    (Input, 'input'),
    (Output, 'output'),
    (PID, 'function'),
    (Trigger, 'function'),
    (Conditional, 'function'),
    (CustomController, 'function'),
    (Function, 'function'),
)


def _feature(shape):
    """GeoShape.feature 를 dict 로 정규화. SQLite 가 JSON 컬럼을 문자열로
    돌려주는 경우가 있어 여기서 흡수한다."""
    raw = shape.feature
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _build_device_type_index():
    """device unique_id → 'input'|'output'|'function' 매핑."""
    index = {}
    for model, type_key in DEVICE_TYPE_MODELS:
        try:
            for row in model.query.with_entities(model.unique_id).all():
                index[row.unique_id] = type_key
        except Exception:
            # 모델 테이블이 없는 설치본(부분 업그레이드)에서도 나머지는 처리한다.
            continue
    return index


def collect(map_uuid=None):
    """정리 대상을 모아 반환한다. 쓰기는 하지 않는다."""
    findings = {'map-theme': [], 'shape-color': [], 'device-type': []}

    # 1. 지도별 theme_config
    maps_q = GeoMap.query
    if map_uuid:
        maps_q = maps_q.filter_by(unique_id=map_uuid)
    for gmap in maps_q.all():
        state = gmap.state_dict() or {}
        if 'theme_config' not in state:
            continue
        findings['map-theme'].append({
            'map_uuid': gmap.unique_id,
            'map_name': gmap.name,
            'value': state.get('theme_config'),
        })

    # 2/3. 장치 도형의 각인 색 + 빈 device_type
    shapes_q = GeoShape.query.filter(GeoShape.type.in_(DEVICE_SHAPE_TYPES))
    if map_uuid:
        shapes_q = shapes_q.filter_by(geo_id=map_uuid)
    shapes = shapes_q.all()

    type_index = _build_device_type_index() if shapes else {}

    for shape in shapes:
        props = _feature(shape).get('properties') or {}

        baked = {k: props[k] for k in BAKED_STYLE_KEYS if props.get(k)}
        if baked:
            findings['shape-color'].append({
                'shape_id': shape.id,
                'shape_uuid': shape.unique_id,
                'map_uuid': shape.geo_id,
                'device_type': props.get('device_type'),
                'baked': baked,
            })

        if not props.get('device_type'):
            # device_id 는 채널 접미사 없는 base UUID 로 저장된다.
            base_id = (shape.device_id or props.get('device_id') or '')
            base_id = str(base_id).split('::')[0]
            resolved = type_index.get(base_id)
            findings['device-type'].append({
                'shape_id': shape.id,
                'shape_uuid': shape.unique_id,
                'map_uuid': shape.geo_id,
                'device_id': base_id or None,
                'resolved': resolved,
            })

    return findings


def apply(findings):
    """collect() 결과를 DB 에 반영. 반영한 건수를 돌려준다."""
    counts = {'map-theme': 0, 'shape-color': 0, 'device-type': 0}

    for item in findings['map-theme']:
        gmap = GeoMap.query.filter_by(unique_id=item['map_uuid']).first()
        if not gmap:
            continue
        state = gmap.state_dict() or {}
        if 'theme_config' not in state:
            continue
        state.pop('theme_config', None)
        gmap.state_json = json.dumps(state, ensure_ascii=False)
        counts['map-theme'] += 1

    # 한 도형이 두 항목에 동시에 걸릴 수 있으므로(각인 색 + 빈 device_type)
    # feature 를 shape_id 단위로 한 번만 읽고 한 번만 되쓴다.
    pending = {}

    def _load(shape_id):
        if shape_id not in pending:
            shape = db.session.get(GeoShape, shape_id)
            # 반드시 사본을 고친다. _feature() 가 돌려주는 dict 는 ORM 이 들고
            # 있는 바로 그 객체라, 제자리에서 고치면 "로드된 값"까지 함께 바뀐다
            # → flush 때 old/new 비교가 같다고 나와 UPDATE 가 통째로 생략된다
            # (JSON 컬럼은 MutableDict 가 아니라 값 비교로 변경을 판단한다).
            # 실제로 한 번 겪었다: commit 은 성공하는데 DB 는 그대로였다.
            copy = json.loads(json.dumps(_feature(shape))) if shape else None
            pending[shape_id] = (shape, copy) if shape else (None, None)
        return pending[shape_id]

    for item in findings['shape-color']:
        shape, feat = _load(item['shape_id'])
        if not shape:
            continue
        props = feat.setdefault('properties', {})
        removed = False
        for key in BAKED_STYLE_KEYS:
            if key in props:
                props.pop(key)
                removed = True
        if removed:
            counts['shape-color'] += 1

    for item in findings['device-type']:
        if not item['resolved']:
            # 어떤 장치인지 해소되지 않으면 건드리지 않는다. 읽기 경로는 이
            # 경우 장치 공통색(device)으로 수렴하므로 화면이 깨지지는 않는다.
            continue
        shape, feat = _load(item['shape_id'])
        if not shape:
            continue
        props = feat.setdefault('properties', {})
        props['device_type'] = item['resolved']
        counts['device-type'] += 1

    for shape, feat in pending.values():
        if shape and feat is not None:
            # JSON 컬럼은 같은 객체를 되대입하면 변경 감지가 안 될 수 있어
            # 새 dict 로 교체한다.
            shape.feature = json.loads(json.dumps(feat))

    db.session.commit()
    return counts


def _report(findings, counts=None, quiet=False):
    total = sum(len(v) for v in findings.values())
    unresolved = [f for f in findings['device-type'] if not f['resolved']]

    if not quiet:
        for item in findings['map-theme']:
            print(f"  [map-theme]   {item['map_name']} ({item['map_uuid'][:8]}) "
                  f"theme_config={json.dumps(item['value'], ensure_ascii=False)}")
        for item in findings['shape-color']:
            print(f"  [shape-color] shape#{item['shape_id']} "
                  f"({item.get('device_type') or 'device_type 없음'}) "
                  f"{json.dumps(item['baked'])}")
        for item in findings['device-type']:
            state = item['resolved'] or '해소 실패(그대로 둠)'
            print(f"  [device-type] shape#{item['shape_id']} "
                  f"device_id={item['device_id'] or '없음'} → {state}")
        if total:
            print()

    print(f"map-theme {len(findings['map-theme'])}건 · "
          f"shape-color {len(findings['shape-color'])}건 · "
          f"device-type {len(findings['device-type'])}건"
          + (f" (해소 실패 {len(unresolved)}건)" if unresolved else ""))

    if counts is not None:
        print(f"반영: map-theme {counts['map-theme']} · "
              f"shape-color {counts['shape-color']} · "
              f"device-type {counts['device-type']}")
    elif total:
        print("dry-run — 아무것도 쓰지 않았습니다. 반영하려면 --apply")


def main():
    parser = argparse.ArgumentParser(
        description='지도 테마색 갈래(지도별 override·도형 각인 색) 정리')
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
            counts = apply(findings) if args.apply else None
    except Exception as err:  # noqa: BLE001 — 검사 실패는 종료코드 2로 구분
        print(f"실행 실패: {err}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({'findings': findings, 'applied': counts},
                         ensure_ascii=False, indent=2))
    else:
        _report(findings, counts, quiet=args.quiet)

    total = sum(len(v) for v in findings.values())
    if args.apply:
        return 0
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
