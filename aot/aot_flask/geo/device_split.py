# coding=utf-8
"""site/zone 도형을 잘라 **장치 담당 구역**(`type='device'`)으로 만든다.

설계 정본: docs/design/geo-device-area-split.md

## 왜 필요한가

밸브 5개가 놓인 밭을 5구역으로 나눠 각 밸브에 맡기는 것은 흔한 작업인데,
지금까지는 구역 폴리곤을 **손으로 다섯 번 그려야** 했다. 구역 경계를 눈대중으로
맞추다 보니 조각마다 폭이 달라지고, 비스듬한 밭에서는 특히 어렵다.

식생 구획 나누기(`planting_split`)가 이미 같은 문제를 푼다 — 다만 결과물이
`GeoPlanting` 이다. 기하 계산은 완전히 같으므로 **엔진을 그대로 쓰고**
(`planting_split.split_shape`), 만들어지는 행만 `GeoShape(type='device')` 로
바꾼 것이 이 모듈이다.

## 장치 연결 — 조각 안의 마커로 자동 배정

조각을 만든 뒤 **그 조각 안에 들어온 장치 마커**(`aot_device` 점)를 찾아 그
장치를 조각에 배정한다. 사람이 이미 밸브를 지도에 놓아 뒀다면 추가 입력 없이
연결이 끝난다 — "밸브 5개 놓인 밭을 5구역으로" 라는 작업 순서와 정확히 맞다.

애매하면 **배정하지 않고 그대로 알린다**:
  - 조각 안에 마커가 없다  → 미배정 (사람이 나중에 '장치 배정' 으로 고른다)
  - 조각 안에 마커가 둘 이상 → 미배정 (어느 것인지 이 도구가 정할 수 없다)
조용히 첫 번째를 고르면 사용자는 틀린 배정을 눈치채지 못한다.

## 하지 않는 것

- **마커를 옮기거나 만들지 않는다.** 배치는 `device_placement` 의 일이다.
- **소속(membership)을 건드리지 않는다.** 장치가 어느 zone 에 속하는지는
  위치로 파생되는 별개 축이다(`device_membership` 의 경고 참조).
"""
import logging

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_binding, device_membership, planting_split
from aot.databases.models import GeoShape

logger = logging.getLogger(__name__)

# 장치 담당 구역은 두둑이 아니다 — `planting_split` 의 기본 하한(2m, 두둑 기준)을
# 그대로 쓰면 밸브 하나가 맡는 좁은 구역이 조용히 버려진다. 여기서는 자투리만
# 걸러낼 정도로만 낮춘다.
_MIN_AREA_LENGTH_M = 0.5


def _clean_feature(geometry, name=None):
    """저장할 Feature — **구조 속성을 넣지 않는다.**

    `aot_type`/`device_id`/`channel_id` 는 읽을 때 파생해 주입되는 값이라
    저장하면 안 된다(트리거 GEO-I6/GB-5 가 막는다). 종류는 `GeoShape.type`
    이 정본이고, 장치 연결은 `GeoBinding` 이 정본이다.
    """
    props = {}
    if name:
        props['name'] = name
    return {'type': 'Feature', 'properties': props, 'geometry': geometry}


def _kind_of(raw):
    """마커 device_id → (uuid, 채널, device_kind). 실존하지 않으면 kind 가 None."""
    base, _sep, ch = str(raw).partition('::')
    return base, (ch or '0'), device_binding.resolve_device_kind(base)


def split_shape_into_device_areas(shape, name_base=None, device_kind=None,
                                  **split_kwargs):
    """`shape` 를 잘라 장치 구역 행들을 만든다 → `(result, 오류문구)`.

    `split_kwargs` 는 `planting_split.split_shape` 와 같다(parts /
    strip_width_cm / widths_cm / orientation / angle_deg / edge_margin_cm).

    반환 `result`:
      - `created`  : [{'unique_id', 'index', 'name', 'device_id'|None, 'area_m2'}]
      - `info`     : split_shape 의 info 그대로
      - `assigned` : 자동 배정된 조각 수
      - `unassigned`: [{'index', 'reason': 'no_device'|'ambiguous', 'candidates'}]
    """
    split_kwargs.setdefault('min_bed_length_m', _MIN_AREA_LENGTH_M)
    strips, info = planting_split.split_shape(shape, **split_kwargs)
    if strips is None:
        return None, info          # info 가 오류문구다

    # 마커는 한 번만 읽는다 — 조각마다 다시 읽으면 조회가 조각 수만큼 반복된다.
    markers = device_membership.load_markers(shape.geo_id)

    created, unassigned = [], []
    assigned = 0
    for strip in strips:
        name = ('%s %d' % (name_base, strip['index'])) if name_base else None
        row = GeoShape()
        row.type = 'device'        # GEO-I7 — 넣은 뒤에는 못 바꾼다
        row.geo_id = shape.geo_id
        row.feature = _clean_feature(strip['geometry'], name)
        db.session.add(row)
        db.session.flush()         # unique_id 확보 (바인딩이 이것을 가리킨다)

        device_id = _auto_bind(row, strip, markers, unassigned, device_kind)
        if device_id:
            assigned += 1
        created.append({
            'unique_id': row.unique_id,
            'index': strip['index'],
            'name': name,
            'device_id': device_id,
            'area_m2': strip['area_m2'],
        })

    db.session.commit()
    return {'created': created, 'info': info,
            'assigned': assigned, 'unassigned': unassigned}, None


def _auto_bind(row, strip, markers, unassigned, device_kind=None):
    """조각 안에 후보가 **정확히 하나**일 때만 배정한다. 배정한 device_id 또는 None.

    `device_kind` 를 주면 그 종류의 장치만 후보로 본다. 이것이 없으면 실사용에서
    거의 항상 "애매함" 으로 끝난다 — 밭 하나에 센서·밸브·함수 마커가 수십 개
    섞여 있어서, 조각 안에 딱 하나만 들어오는 일이 드물다(실측: 마커 32개인
    지도에서 16조각으로 잘랐더니 배정 0건, 전부 없음/애매함). "밸브만 보고
    나눈다" 로 좁히면 그제서야 조각과 장치가 1:1 로 맞는다.
    """
    ids = device_membership.device_ids_in_geometry(
        row.geo_id, strip['geometry'], markers=markers)

    # 종류로 후보를 좁힌다. 실존하지 않는 장치의 마커도 여기서 함께 걸러진다.
    resolved = []
    for raw in ids:
        base, ch, kind = _kind_of(raw)
        if not kind:
            continue                       # 지워진 장치의 마커 등
        if device_kind and kind != device_kind:
            continue
        resolved.append((base, ch, kind))

    if not resolved:
        unassigned.append({'index': strip['index'], 'reason': 'no_device',
                           'candidates': 0})
        return None
    if len(resolved) > 1:
        # 어느 장치인지 이 도구가 정할 수 없다 — 조용히 하나 고르면 틀린 배정을
        # 사람이 눈치채지 못한다.
        unassigned.append({'index': strip['index'], 'reason': 'ambiguous',
                           'candidates': len(resolved)})
        return None

    base, ch, kind = resolved[0]
    try:
        device_binding.bind('shape', row.unique_id, 'area', kind, base,
                            channel_id=ch)
    except device_binding.BindingError as exc:
        logger.warning('device_split: 배정 실패 index=%s: %s', strip['index'], exc)
        unassigned.append({'index': strip['index'], 'reason': 'no_device',
                           'candidates': 0})
        return None
    return base
