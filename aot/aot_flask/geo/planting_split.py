# coding=utf-8
"""대지/구역 도형을 두둑(식생 구획)으로 분할한다 — 순수 기하 계산.

설계 정본: docs/design/geo-vegetation-planting.md

## 왜 필요한가

`create_planting` 은 GeoJSON 폴리곤을 받는데, **LLM 은 구역이 지도 어디에 있는지
알 방법이 없다** — 어떤 도구도 구역 경계 폴리곤을 내주지 않는다. 그래서 좌표를
지어내면 엉뚱한 자리에 저장되고, 실패했다고 말해주지도 않는다(구역 밖이면
`zone_uuid` 가 null 로 남을 뿐이다).

여기서는 **사람이 이미 그려 둔 도형**(site/zone)을 입력으로 받아 서버가 나눈다.
LLM 이 만드는 숫자는 간격 하나뿐이고, 좌표는 하나도 만들지 않는다.

## 방향 — 가장 긴 변을 따른다

농경지는 대체로 직각을 선호하지만 대지가 비정형인 경우가 많다. 그럴 때 축(정북)
기준으로 자르면 두둑이 밭을 비스듬히 가로질러 자투리만 잔뜩 생긴다. 실제 농사는
**밭의 긴 방향을 따라** 두둑을 놓는다.

그 방향은 `dimensions()` 가 쓰는 것과 같은 **최소회전 외접사각형**에서 나온다 —
그 사각형의 긴 변이 곧 밭의 지배 방향이다. 방향을 그렇게 잡으면 비정형 가장자리는
교차 연산이 알아서 잘라내므로, 예외 처리를 따로 쓸 일이 없다.

## 하지 않는 것

- **공원식 둘레 식재는 다루지 않는다.** 구역 둘레로 나무·꽃을 심고 내부는 규칙이
  없는 경우가 흔한데, 그것은 "분할" 이 아니라 배치이고 규칙이 사람마다 다르다.
  가이드로만 남기고 도구로 만들지 않는다(설계 문서 참조).
- **저장하지 않는다.** 여기서 나온 폴리곤은 제안일 뿐이고, 사람이 지도에서 보고
  적용해야 실제 구획이 된다.
"""
import logging
import math

from aot.aot_flask.geo import planting_context

logger = logging.getLogger(__name__)

# 자투리 기준. 긴 방향 길이가 이보다 짧은 조각은 두둑으로 치지 않는다 —
# 비정형 대지의 뾰족한 끝에서 30cm 짜리 삼각형이 나오는 것을 "두둑 1개" 로
# 세면 개수와 식재량이 모두 부풀어 오른다.
_MIN_BED_LENGTH_M = 2.0

# 분할 상한. 사람이 지도에서 확인해야 하는 제안이므로, 실수로 폭 1cm 를 넣어
# 수천 개가 만들어지는 것을 막는다. 넘으면 잘라내지 않고 **거부한다** — 조용히
# 자르면 사용자는 자기가 본 것이 전부인 줄 안다.
_MAX_STRIPS = 200


def _longest_edge_angle(rect):
    """최소회전 사각형 → 가장 긴 변의 방위각(도, 반시계).

    사각형의 첫 세 꼭짓점이 인접한 두 변을 준다. 긴 쪽을 고른다.
    """
    c = list(rect.exterior.coords)
    if len(c) < 3:
        return None
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    long_e = e1 if (e1[0] ** 2 + e1[1] ** 2) >= (e2[0] ** 2 + e2[1] ** 2) else e2
    return math.degrees(math.atan2(long_e[1], long_e[0]))


def split_shape(shape_or_geom, parts=None, strip_width_cm=None,
                edge_margin_cm=0, min_bed_length_m=_MIN_BED_LENGTH_M):
    """도형을 띠 폴리곤 목록으로 → `(strips, info)` 또는 `(None, 오류문구)`.

    **조각 하나가 무엇인지는 호출자가 정한다.** 구역을 세 작물로 나누는 것과
    두둑마다 따로 기록하는 것은 같은 연산이고 굵기만 다르다.

    - `parts=3`            → 3등분. 조각 하나가 작기 하나(GeoPlanting 한 행).
    - `strip_width_cm=160` → 1.6m 띠. 두둑 단위로 관리할 때.

    둘 중 하나만 준다. 둘 다 없으면 무엇을 원하는지 알 수 없으므로 거부한다 —
    기본값을 정해 두면 사용자가 말하지 않은 굵기로 나뉜 제안을 보게 된다.

    Parameters
    ----------
    shape_or_geom : GeoShape 행 또는 GeoJSON geometry dict
    parts         : 등분 수 (2 이상 정수)
    strip_width_cm: 띠 폭 (cm). 두둑 간격으로 쓸 때는 고랑 포함 값.
    edge_margin_cm: 도형 경계에서 안쪽으로 뺄 여백 (cm). 농기계 선회 공간.
    min_bed_length_m : 이보다 짧은 조각은 버린다.

    Returns
    -------
    strips : [{'geometry': GeoJSON Polygon, 'index': int, 'length_m': float,
               'area_m2': float}, ...] — 긴 축을 따라 놓이고 짧은 축 순서로 번호.
    info : {'orientation_deg', 'strip_width_cm', 'edge_margin_cm', 'count',
            'source_area_m2', 'covered_area_m2', 'dropped', 'note'}
    """
    from shapely import affinity
    from shapely.geometry import box, mapping
    from shapely.ops import transform

    geom = (shape_or_geom if isinstance(shape_or_geom, dict)
            else planting_context.geometry_of(shape_or_geom))
    if not geom:
        return None, 'no polygon to split'

    if (parts is None) == (strip_width_cm is None):
        return None, ('give either parts (how many pieces) or strip_width_cm '
                      '(how wide each piece) — not both, not neither')
    if parts is not None:
        try:
            parts = int(parts)
        except (TypeError, ValueError):
            return None, 'parts must be a whole number'
        if parts < 2:
            return None, 'parts must be 2 or more'
    try:
        margin_m = float(edge_margin_cm or 0) / 100.0
    except (TypeError, ValueError):
        return None, 'edge_margin_cm must be a number in centimeters'
    if margin_m < 0:
        return None, 'edge_margin_cm cannot be negative'

    to_m, from_m, _lat0 = planting_context.local_frame(geom)
    if to_m is None:
        return None, 'could not project the shape'
    poly = planting_context._shapely(geom)
    if poly is None or poly.is_empty:
        return None, 'no polygon to split'
    plane = transform(to_m, poly)

    # 여백은 **안쪽으로 파고드는 버퍼**다. 외접사각형에서 빼면 비정형 대지의
    # 오목한 곳에서는 여백이 실제로 남지 않는다.
    if margin_m > 0:
        plane = plane.buffer(-margin_m)
        if plane.is_empty:
            return None, ('edge_margin_cm %.0f cm leaves nothing of this shape'
                          % (margin_m * 100))

    try:
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning,
                                    message='.*oriented_envelope.*')
            rect = plane.minimum_rotated_rectangle
    except Exception as exc:
        logger.warning('planting_split: 외접사각형 실패: %s', exc)
        return None, 'could not find the shape orientation'
    angle = _longest_edge_angle(rect) if hasattr(rect, 'exterior') else None
    if angle is None:
        return None, 'shape has no area to split'

    # 긴 축을 수평으로 눕힌다. 이후 자르기는 수평 띠 = 긴 방향을 따르는 조각이다.
    origin = rect.centroid
    flat = affinity.rotate(plane, -angle, origin=origin)
    minx, miny, maxx, maxy = flat.bounds
    across = maxy - miny
    if across <= 0:
        return None, 'shape has no width to split'

    # 등분이면 폭이 나오고, 폭이면 개수가 나온다 — 같은 연산의 두 입구다.
    if parts is not None:
        count = parts
        step_m = across / float(parts)
        offset = 0.0          # 등분은 남는 폭이 없다
    else:
        try:
            step_m = float(strip_width_cm) / 100.0
        except (TypeError, ValueError):
            return None, 'strip_width_cm must be a number in centimeters'
        if step_m <= 0:
            return None, 'strip_width_cm must be greater than 0'
        if across < step_m:
            return None, ('the shape is only %.1f m across its short axis, '
                          'less than one %.0f cm strip'
                          % (across, step_m * 100))
        count = int(across // step_m)
        # 남는 폭은 양쪽에 반씩 — 한쪽으로 몰면 밭 한 변에만 자투리가 붙는다.
        offset = (across - count * step_m) / 2.0

    if count > _MAX_STRIPS:
        return None, ('that would be %d pieces, more than this tool will '
                      'propose (%d). Use fewer parts or a wider strip.'
                      % (count, _MAX_STRIPS))

    strips, dropped, covered = [], 0, 0.0
    for i in range(count):
        y0 = miny + offset + i * step_m
        band = box(minx - 1.0, y0, maxx + 1.0, y0 + step_m)
        piece = flat.intersection(band)
        if piece.is_empty:
            dropped += 1
            continue
        # 오목한 대지에서는 한 띠가 여러 조각으로 끊긴다. 끊긴 것은 **각각 다른
        # 구획**이다 — 하나로 묶으면 "길이 67m" 이 실제로는 30m 짜리 둘인 상태가
        # 되어 식재량이 맞지 않는다.
        #
        # ⚠ 이 변수를 `parts` 로 쓰지 말 것. 파라미터 `parts` 를 덮어써서 두 번째
        #   반복부터 등분 수가 사라진다(each_input 클로버 버그와 같은 형태).
        pieces = (list(piece.geoms) if piece.geom_type.startswith('Multi')
                  else [piece])
        for part in pieces:
            if part.geom_type != 'Polygon' or part.is_empty:
                continue
            px0, _py0, px1, _py1 = part.bounds
            length_m = px1 - px0
            if length_m < min_bed_length_m:
                dropped += 1
                continue
            back = affinity.rotate(part, angle, origin=origin)
            lonlat = transform(from_m, back)
            area = planting_context.shapely_area_m2(lonlat)
            covered += area
            strips.append({
                'index': len(strips) + 1,
                'geometry': mapping(lonlat),
                'length_m': round(length_m, 1),
                'area_m2': round(area, 1),
            })

    if not strips:
        return None, ('nothing usable came out — every strip was shorter than '
                      '%.1f m' % min_bed_length_m)

    source_area = planting_context.shapely_area_m2(poly)
    info = {
        'orientation_deg': round(angle % 180.0, 1),
        'strip_width_m': round(step_m, 2),
        'edge_margin_cm': round(margin_m * 100),
        'count': len(strips),
        'source_area_m2': round(source_area, 1),
        # **덮은 면적**이지 심는 면적이 아니다. 띠는 도형을 빈틈없이 덮으므로
        # 이 값은 도형 면적에 가깝다. 고랑을 뺀 실제 식재 면적은 계산하지
        # 않는다 — 고랑 폭을 모르는 것이 이 설계의 선택이기 때문이다.
        'covered_area_m2': round(covered, 1),
        'dropped': dropped,
        'note': ('Pieces follow the shape\'s longest side (%.0f deg). Irregular '
                 'edges are clipped, so pieces differ in length; %d were dropped '
                 'as too short. covered_area_m2 is the ground the pieces cover, '
                 'NOT the plantable area — furrows are not subtracted.'
                 % (angle % 180.0, dropped)),
    }
    return strips, info
