# coding=utf-8
"""식생 구획(작기)의 파생 계산 — 소속·센서·면적.

설계 정본: docs/design/geo-vegetation-planting.md

이 모듈이 내는 값은 **하나도 저장되지 않는다.** zone 소속도, 참조 센서도,
면적도 매번 계산한다. 물질화한 소속이 어떻게 썩는지는 `map_overlay_id` 가
이미 보여줬다(2026-08-03: 밸브 16개가 존재하지 않는 도형을 가리켰다) —
복제가 남의 링크를 복사하고, zone 재생성이 참조를 끊고, 도형 삭제가 고아를
남겼다. 저장하지 않으면 그 오염 계열 전체가 성립하지 않는다.

면적은 `facility_calc._ring_area_m2` 와 같은 근사(평균 위도 기준 평면 투영)를
쓴다. 같은 지도에서 두 면적이 다른 방식으로 계산되면 "구획 합이 zone 을
넘는다" 같은 물리적으로 불가능한 화면이 나온다.
"""
import logging
from datetime import date

from aot.aot_flask.geo import device_membership
from aot.aot_flask.geo.facility_calc import _ring_area_m2
from aot.databases.models import GeoPlanting, GeoShape, Input

logger = logging.getLogger(__name__)

_POLY_TYPES = ('Polygon', 'MultiPolygon')


# ---------------------------------------------------------------------------
# 기하 헬퍼
# ---------------------------------------------------------------------------

def geometry_of(row):
    """GeoPlanting | GeoShape → GeoJSON geometry dict ({} 이면 없음)."""
    import json

    feat = getattr(row, 'feature', None)
    if isinstance(feat, str):
        try:
            feat = json.loads(feat)
        except (ValueError, TypeError):
            return {}
    if not isinstance(feat, dict):
        return {}
    geom = feat.get('geometry')
    return geom if isinstance(geom, dict) else {}


def _shapely(geom):
    """geometry dict → shapely, 실패/비폴리곤이면 None."""
    from shapely.geometry import shape as shapely_shape

    if not geom or geom.get('type') not in _POLY_TYPES:
        return None
    try:
        return shapely_shape(geom)
    except Exception as exc:
        logger.warning('planting: 기하 해석 실패: %s', exc)
        return None


def shapely_area_m2(geom):
    """shapely 기하 → m². 구멍(interior)을 뺀다.

    합집합 결과는 구멍을 가질 수 있다 — 도넛 모양으로 둘러싼 구획들의 union
    이 그렇다. 외곽만 재면 미배정 면적이 실제보다 작게(음수까지) 나온다.
    """
    if geom is None or geom.is_empty:
        return 0.0
    gtype = geom.geom_type
    if gtype == 'Polygon':
        area = _ring_area_m2(list(geom.exterior.coords))
        for ring in geom.interiors:
            area -= _ring_area_m2(list(ring.coords))
        return max(area, 0.0)
    if gtype in ('MultiPolygon', 'GeometryCollection'):
        return sum(shapely_area_m2(g) for g in geom.geoms
                   if g.geom_type in _POLY_TYPES)
    return 0.0


def area_m2(row):
    """GeoPlanting | GeoShape 의 면적 (m²). 기하가 없으면 0."""
    return shapely_area_m2(_shapely(geometry_of(row)))


# ---------------------------------------------------------------------------
# 치수 — 면적 하나로는 답할 수 없는 질문을 위해
# ---------------------------------------------------------------------------
#
# "40cm 간격으로 8줄 심을 공간이 되나" 는 방향이 있는 질문인데 `area_m2` 는
# 스칼라라 방향이 없다. 1837m² 가 40×46 인지 5×367 인지에 따라 답이 갈린다.
#
# 그렇다고 원본 좌표를 그대로 내보내면 안 된다 — 구획 하나가 좌표 수백 개고,
# AI 컨텍스트에 실리는 값은 `_planting_brief` 가 `feature` 를 떼는 것으로
# 이미 한 번 판단이 끝난 문제다. 여기서 내는 것은 **계산된 요약 두 숫자**다.

def _mean_lat(geom):
    """폴리곤 외곽 꼭짓점들의 평균 위도.

    `_ring_area_m2` 와 **같은 기준점**이어야 한다. 투영 기준 위도가 갈리면
    같은 구획의 면적과 치수가 서로 다른 평면에서 재어져, `width × length` 와
    `area_m2` 를 나란히 놓았을 때 설명되지 않는 차이가 생긴다.
    """
    rings = []
    gt = geom.get('type')
    if gt == 'Polygon':
        rings = (geom.get('coordinates') or [])[:1]
    elif gt == 'MultiPolygon':
        rings = [p[0] for p in (geom.get('coordinates') or []) if p]
    pts = [c for ring in rings for c in ring if len(c) >= 2]
    if not pts:
        return None
    return sum(c[1] for c in pts) / len(pts)


def _to_local_m(geom):
    """geometry dict → 로컬 등장방형 평면(미터)의 shapely 기하.

    새 투영 라이브러리를 들이지 않는다 — `facility_calc._ring_area_m2` 가 쓰는
    것과 **같은 근사**(평균 위도 기준 도→미터 환산)를 그대로 쓴다. 농장 한 곳
    규모에서 이 근사의 오차는 무시할 수준이고, 지도 안에서 계산 방식이 두 벌이
    되는 쪽이 훨씬 비싸다.

    각 변의 길이를 재려면 **미터 평면에서 외접사각형을 구해야 한다.** 도(degree)
    공간에서 구하면 경도 1도가 위도 1도보다 짧은 만큼(위도 35°에서 약 0.82배)
    사각형이 찌그러진 채로 최소화되어, 실제 최소 사각형이 아닌 것이 나온다.
    """
    from shapely.ops import transform

    poly = _shapely(geom)
    if poly is None or poly.is_empty:
        return None
    lat0 = _mean_lat(geom)
    if lat0 is None:
        return None
    import math

    m_per_deg_lat = 111320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    return transform(lambda x, y, z=None: (x * m_per_deg_lng, y * m_per_deg_lat),
                     poly)


# 외접사각형 면적이 실제 면적의 이 배를 넘으면 "사각형으로 보면 안 된다" 고
# 말한다. 삼각형이 정확히 2.0, ㄱ자가 대략 1.4~2.0 이고, 두둑처럼 실제로 네모난
# 구획은 1.0~1.1 에 머문다. 경계에 걸리는 것은 마름모꼴 밭 정도다.
_SHAPE_WARN_RATIO = 1.3

_SHAPE_WARN_NOTE = (
    "This plot is not rectangular — its bounding rectangle is much larger than "
    "the plot itself, so the real number of rows/plants will be FEWER than any "
    "estimate based on these dimensions. Say so when you report a number."
)


def dimensions(row):
    """구획의 치수 → `{width_m, length_m, rect_fill_pct, shape_note}` (없으면 None).

    최소회전 외접사각형(`minimum_rotated_rectangle`)의 두 변이다. 축 정렬
    bounding box 가 아니다 — 비스듬히 놓인 두둑은 축 정렬로 재면 실제보다
    한참 크고 뚱뚱한 사각형이 나온다.

    `width_m` 이 항상 짧은 변이다. 줄(row)은 긴 변을 따라 놓고 짧은 변을
    가로질러 세는 것이 관행이라, 이 약속이 깨지면 "몇 줄" 의 답이 뒤집힌다.

    `rect_fill_pct` 는 그 사각형을 실제 구획이 얼마나 채우는가다. 이 숫자를
    같이 내는 이유는 경고 문구만으로는 AI 가 얼마나 깎아야 하는지 알 수 없기
    때문이다 — 삼각형(50%)과 살짝 기운 사각형(95%)에 같은 말을 할 수는 없다.
    """
    geom = geometry_of(row)
    projected = _to_local_m(geom)
    if projected is None:
        return None

    try:
        # shapely 2.1 의 oriented_envelope 는 **축에 정렬된 변**을 만나면 기울기
        # 계산에서 0으로 나눠 numpy RuntimeWarning 을 낸다(결과는 정확하다).
        # 위성사진 보고 그린 두둑은 축에 가까운 것이 많아 그냥 두면 조회 한 번에
        # 경고가 수십 줄씩 쌓인다 — 이 호출에서만 막는다.
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning,
                                    message='.*oriented_envelope.*')
            rect = projected.minimum_rotated_rectangle
    except Exception as exc:
        logger.warning('planting: 외접사각형 계산 실패: %s', exc)
        return None

    ring = getattr(rect, 'exterior', None)
    coords = list(ring.coords) if ring is not None else []
    if len(coords) < 3:
        # 면적이 0인 기하(한 점·직선)는 사각형이 아니라 선/점으로 축약된다.
        return None

    def _dist(p, q):
        import math
        return math.hypot(q[0] - p[0], q[1] - p[1])

    sides = sorted((_dist(coords[0], coords[1]), _dist(coords[1], coords[2])))
    width_m, length_m = round(sides[0], 1), round(sides[1], 1)

    actual = shapely_area_m2(_shapely(geom))
    rect_area = width_m * length_m
    fill = (actual / rect_area) if rect_area > 0 else 0.0

    return {
        'width_m': width_m,
        'length_m': length_m,
        'rect_fill_pct': round(fill * 100.0, 1),
        'shape_note': (_SHAPE_WARN_NOTE
                       if fill > 0 and (1.0 / fill) > _SHAPE_WARN_RATIO else None),
    }


def capacity_estimate(dims, row_spacing_cm=None, plant_spacing_cm=None,
                      edge_margin_cm=None, bed_width_cm=None,
                      path_width_cm=None, bed_spec_source='given'):
    """간격(cm) → 줄 수·그루 수. 간격이 둘 다 없으면 None(묻지 않은 것).

    `get_facility_capacity` 가 냉난방 용량을 서버에서 계산해 내려주는 것과 같은
    이유로 여기서 센다 — LLM 에 암산을 맡기면 조용히 틀린다.

    **세는 방식: 한 그루가 간격 하나만큼의 칸을 차지한다** (`floor(폭 / 간격)`).
    처음에는 울타리 기둥 세기(`구간 수 + 1`)로 셌는데, 그것은 양 끝 줄이 경계선
    **위에** 서 있다고 보는 계산이라 밭에서 성립하지 않는다. 칸으로 세면 양쪽에
    간격의 절반씩 여백이 자동으로 남는다 — 폭 4m 를 40cm 간격으로 나누면 10줄이
    20cm 씩 떨어져 서고, 기둥 세기의 11줄은 맨 바깥 두 줄이 경계에 걸린 값이다.

    `edge_margin_cm` 은 그 위에 **추가로** 빼는 여백이다. 농기계 선회 공간이나
    두둑 어깨처럼 미터 단위로 필요한 것은 간격의 절반으로 감당되지 않는다.
    주지 않으면 0 — 즉 기본값은 "칸으로만 센 값"이고, 여백을 뺐다고 거짓말하지
    않는다.

    **`bed_width_cm` + `path_width_cm` 이 있으면 두둑 배치로 센다.** 없으면
    평평하게 깐 것으로 계산하되 응답에 `ask_user` 를 실어, 규격을 묻거나
    제안해 확정한 뒤 다시 부르라고 시킨다 — 고랑에는 아무것도 안 심으므로
    균일 배치는 두둑 농사에서 20~30% 과다추정이 되는데, 그 사실이 응답에
    없으면 AI 가 그 숫자를 그대로 확신하고 답한다.

    Raises:
        ValueError: 간격을 한쪽만 주거나(두둑 규격도 마찬가지), 양수로 읽히지
            않는 값을 준 경우. 조용히 건너뛰면 사용자는 조건을 말했는데 답에는
            그것이 반영되지 않은 상태가 된다 — 무시된 것을 아무도 모른다.
    """
    if row_spacing_cm is None and plant_spacing_cm is None:
        if all(v is None for v in
               (edge_margin_cm, bed_width_cm, path_width_cm)):
            return None
        # 여백이나 두둑 규격만 주는 것은 계산이 성립하지 않는다. 조용히
        # 무시하면 사용자는 그것이 반영된 줄 알고 답을 읽는다.
        raise ValueError(
            'row_spacing_cm and plant_spacing_cm are required to compute '
            'anything from edge_margin_cm / bed_width_cm / path_width_cm')
    if row_spacing_cm is None or plant_spacing_cm is None:
        raise ValueError(
            'row_spacing_cm and plant_spacing_cm must be given together')

    def _cm(value, field, allow_zero=False):
        try:
            out = float(value)
        except (TypeError, ValueError):
            raise ValueError('%s must be a number in centimeters' % field)
        if out < 0 or (out == 0 and not allow_zero):
            raise ValueError('%s must be greater than 0' % field)
        return out

    if (bed_width_cm is None) != (path_width_cm is None):
        raise ValueError(
            'bed_width_cm and path_width_cm must be given together')

    row_cm = _cm(row_spacing_cm, 'row_spacing_cm')
    plant_cm = _cm(plant_spacing_cm, 'plant_spacing_cm')
    margin_cm = (0.0 if edge_margin_cm is None
                 else _cm(edge_margin_cm, 'edge_margin_cm', allow_zero=True))
    bedded = bed_width_cm is not None
    bed_cm = _cm(bed_width_cm, 'bed_width_cm') if bedded else None
    path_cm = _cm(path_width_cm, 'path_width_cm', allow_zero=True) if bedded else None

    if not dims:
        return None

    # 공표된(반올림된) 치수로 센다 — AI 나 사용자가 답을 손으로 검산했을 때
    # 같은 숫자가 나와야 한다.
    usable_w = max(dims['width_m'] * 100.0 - 2 * margin_cm, 0.0)
    usable_l = max(dims['length_m'] * 100.0 - 2 * margin_cm, 0.0)

    per_row = int(usable_l // plant_cm)
    beds = rows_per_bed = None

    if bedded:
        # 두둑 n 개는 n·두둑 + (n-1)·고랑 만큼을 쓴다 — 마지막 두둑 뒤에는
        # 고랑이 필요 없다. 이걸 n·(두둑+고랑) 으로 세면 밭 하나가 통째로 빠진다.
        beds = int((usable_w + path_cm) // (bed_cm + path_cm))
        rows_per_bed = int(bed_cm // row_cm)
        rows = beds * rows_per_bed
    else:
        rows = int(usable_w // row_cm)

    if rows == 0 or per_row == 0:
        if bedded and beds and rows_per_bed == 0:
            basis = (
                'Nothing fits: a %.0f cm bed is narrower than the %.0f cm row '
                'spacing, so not even one row fits on a bed. Widen the bed or '
                'narrow the row spacing.' % (bed_cm, row_cm))
        elif bedded and not beds:
            basis = (
                'Nothing fits: the usable width is %.1f m, not enough for one '
                '%.0f cm bed. Narrow the bed, the furrow or the edge margin.'
                % (usable_w / 100.0, bed_cm))
        else:
            basis = (
                'Nothing fits: after taking %.0f cm off each edge the usable area '
                'is %.1f m x %.1f m, smaller than one %.0f x %.0f cm spacing. '
                'Either the margin or the spacing has to come down.'
                % (margin_cm, usable_w / 100.0, usable_l / 100.0, row_cm, plant_cm))
        rows = per_row = 0
    else:
        basis = ('Approximate, from the plot\'s bounding rectangle (%.1f m x %.1f m). '
                 % (dims['width_m'], dims['length_m']))
        if bedded:
            basis += (
                '%d beds of %.0f cm fit across the %.1f m usable width with %.0f cm '
                'furrows between them, and %d rows fit on each bed. Furrows carry '
                'no plants. '
                % (beds, bed_cm, usable_w / 100.0, path_cm, rows_per_bed))
            if bed_spec_source == 'stored':
                basis += ('The bed spec is the one recorded on this plot, not one '
                          'you supplied. ')
        else:
            basis += (
                'Each plant is given a full %.0f x %.0f cm cell, so half a spacing '
                'is already left free at every edge. '
                % (row_cm, plant_cm))
        if margin_cm > 0:
            basis += ('%.0f cm was taken off each edge, leaving %.1f m x %.1f m. '
                      % (margin_cm, usable_w / 100.0, usable_l / 100.0))
        else:
            basis += ('No headland was subtracted — pass edge_margin_cm (e.g. 200 '
                      'for a 2 m turning strip) if this plot needs one. ')

    if dims.get('shape_note'):
        basis += ' ' + dims['shape_note']

    out = {
        'row_spacing_cm': row_cm,
        'plant_spacing_cm': plant_cm,
        'edge_margin_cm': margin_cm,
        'usable_width_m': round(usable_w / 100.0, 1),
        'usable_length_m': round(usable_l / 100.0, 1),
        'layout': 'beds' if bedded else 'flat',
        'rows_possible': rows,
        'plants_per_row': per_row,
        'total_plants': rows * per_row,
        'basis': basis.strip(),
    }
    if bedded:
        out['bed_width_cm'] = bed_cm
        out['path_width_cm'] = path_cm
        # 구획에 기록된 규격인지, 이번 호출에서 받은 값인지. 사람이 확인해
        # 저장해 둔 값과 그때그때 가정한 값은 신뢰도가 다르다.
        out['bed_spec_source'] = bed_spec_source
        # "두둑을 몇 줄이나 만들 수 있을까" 는 실제로 받은 질문이다. 줄 수에서
        # 역산하게 두지 말고 그 숫자 자체를 낸다.
        out['beds_possible'] = beds
        out['rows_per_bed'] = rows_per_bed
    else:
        out['ask_user'] = _FLAT_LAYOUT_ASK

    return out


# 두둑 규격을 모를 때 응답에 싣는 지시. **조용히 균일 배치로 계산하고 마는 것이
# 이 필드가 막으려는 실패다** — 고랑에는 아무것도 안 심는데 균일 배치는 거기까지
# 줄을 세우므로 두둑 농사에서 20~30% 과다추정이 된다. 그런데 그 사실이 응답
# 어디에도 없으면 AI 는 그 숫자를 그대로 확신하고 답한다.
#
# 규격을 여기서 정해 내려보내지 않는 이유: 작물·지역·농기계 폭에 따라 달라서
# 서버가 아는 척할 수 있는 값이 아니다. 대신 **묻거나 제안해서 확정하라**고
# 시키고, 확정된 값은 구획에 저장하게 한다(modify_planting) — 같은 밭에 대해
# 매번 다시 묻는 것도 그 자체로 실패다.
#
# ⚠ 특정 나라의 관행을 문장에 박지 말 것. 처음 판에 "Most **Korean** open-field
# vegetables…" 라고 적었는데, 이 제품은 ko/ja 를 함께 쓰고 설치처의 나라도
# 고정이 아니다. 두둑 농사 자체는 어디서나 흔하므로 나라 이름 없이도 같은 말이
# 된다 — 굳이 붙이면 다른 지역 사용자에게는 틀린 근거가 된다.
_FLAT_LAYOUT_ASK = (
    'NO bed layout was assumed: rows are spread evenly across the whole width, '
    'which is only right for flat or broadcast planting. Open-field vegetables '
    'are commonly grown on raised beds with furrows between them, and furrows '
    'carry no plants — where that is the practice it cuts the count by 20-30%. '
    'Before you report this number, ask the grower how this plot is laid out '
    '(bed width and furrow width), or propose a spec and get it confirmed, then '
    'call again with bed_width_cm and path_width_cm. Once it is settled, record '
    'it on the plot with modify_planting so nobody has to be asked again. Do not '
    'present the flat-layout number as the answer without settling this first.'
)


# ---------------------------------------------------------------------------
# 소속 — 파생, 저장하지 않는다
# ---------------------------------------------------------------------------

def zone_for_planting(planting, containers=None):
    """구획을 감싸는 zone/site GeoShape (없으면 None).

    `containers` 를 넘기면 재사용한다 — 목록 응답에서 구획마다 지도 도형
    전량을 다시 훑지 않도록.
    """
    return device_membership.container_for_geometry(
        planting.geo_id, geometry_of(planting), containers=containers)


# ---------------------------------------------------------------------------
# 센서 — 참조하되 매달지 않는다
# ---------------------------------------------------------------------------

def _only_sensor_ids(device_ids):
    """장치 참조 집합에서 Input(센서)만 남긴다.

    `device_ids_in_geometry`/`device_ids_in_shape` 는 폴리곤 안의 장치 참조
    전부(Input·Output 구분 없이)를 돌려주는 범용 계약이다(device_membership
    모듈 docstring 참조) — 그 자체는 옳다. 여기서 거르지 않으면 Output(밸브
    등)이 'sensors' 라는 이름으로 나가 AI/화면이 액추에이터를 센서로 오인해
    읽으려 시도한다(2026-08-13 실측: virtual_on_off_single 밸브가 in_plot/
    from_zone 에 섞여 get_sensor_reading 이 실패했다).
    """
    if not device_ids:
        return set()
    rows = Input.query.with_entities(Input.unique_id).filter(
        Input.unique_id.in_(list(device_ids))).all()
    return {r[0] for r in rows}


def sensors_for_planting(planting, containers=None):
    """구획이 참조할 장치 → `{'in_plot', 'from_zone', 'zone_uuid', 'source'}`.

    1순위는 구획 폴리곤 안의 장치, 없으면 소속 zone 의 장치다. 노지 zone 의
    센서는 현실적으로 한두 개라 **폴백이 기본 경로가 된다** — 여러 구획이 같은
    값을 보게 되는데, 그래도 된다. 식생 구획은 센서의 단위가 아니라 **해석의
    단위**다: 같은 25도라도 상추에는 높고 토마토에는 적정이다.

    `source` 는 'plot' | 'zone' | 'none' — 화면이 "이 값은 구역 대표값" 임을
    말할 수 있어야 한다. 말하지 않으면 사용자는 구획마다 따로 잰 값으로 읽는다.

    ⚠ 반환값을 어디에도 저장하지 말 것. 바인딩(`geo_binding`)을 만드는 것도
    금지다 — 3개월 뒤 사라지는 대상에 바인딩을 매다는 것이 이 설계가 피하려는
    바로 그 구조다.
    """
    in_plot = sorted(_only_sensor_ids(device_membership.device_ids_in_geometry(
        planting.geo_id, geometry_of(planting),
        _label='planting %s' % planting.unique_id)))

    zone = zone_for_planting(planting, containers=containers)
    from_zone = []
    if zone is not None:
        from_zone = sorted(_only_sensor_ids(
            device_membership.device_ids_in_shape(zone)))

    if in_plot:
        source = 'plot'
    elif from_zone:
        source = 'zone'
    else:
        source = 'none'

    return {
        'in_plot': in_plot,
        'from_zone': from_zone,
        'zone_uuid': zone.unique_id if zone is not None else None,
        'zone_name': _shape_name(zone) if zone is not None else None,
        'source': source,
    }


def _shape_name(shape):
    props = {}
    feat = shape.feature if isinstance(shape.feature, dict) else {}
    if isinstance(feat, dict):
        props = feat.get('properties') or {}
    return props.get('name') or props.get('label') or None


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def active_plantings(map_uuid, on=None):
    """`on`(기본 오늘) 시점에 재배 중인 구획 목록.

    지도 기본 렌더의 판정과 같아야 한다 — 여기와 `GeoPlanting.is_active` 가
    갈리면 목록에는 있는데 지도에 없는 구획이 생긴다.
    """
    on = on or date.today()
    # `ended_on > on` — 종료일은 "종료된 날" 이라 그날부터 이미 활성이 아니다.
    # GeoPlanting.is_active 와 **같은 부등호**여야 한다(그 docstring 참조).
    rows = GeoPlanting.query.filter(
        GeoPlanting.geo_id == map_uuid,
        GeoPlanting.planted_on <= on,
    ).filter(
        (GeoPlanting.ended_on.is_(None)) | (GeoPlanting.ended_on > on)
    ).all()
    return rows


def plantings_overlapping(map_uuid, geom, since=None, until=None,
                          include_active=True):
    """기하가 겹치는 구획 — "이 자리에 뭐가 있었나".

    연작 장해·윤작 판단의 근거다. 토양 병해는 3~5년 주기로 보므로 기본은
    기간 제한 없이 전부 돌려주고, 좁히는 것은 호출자가 정한다.

    겹침 판정은 `intersects` 가 아니라 **면적이 있는 교차**로 한다 — 경계를
    맞대고 있을 뿐인 옆 두둑까지 "같은 자리" 로 잡으면 목록이 쓸모없어진다.
    """
    src = _shapely(geom)
    if src is None:
        return []

    q = GeoPlanting.query.filter(GeoPlanting.geo_id == map_uuid)
    if since is not None:
        q = q.filter((GeoPlanting.ended_on.is_(None)) |
                     (GeoPlanting.ended_on >= since))
    if until is not None:
        q = q.filter(GeoPlanting.planted_on <= until)
    if not include_active:
        q = q.filter(GeoPlanting.ended_on.isnot(None))

    out = []
    for row in q.all():
        other = _shapely(geometry_of(row))
        if other is None:
            continue
        try:
            inter = src.intersection(other)
        except Exception:
            continue
        if inter.is_empty:
            continue
        overlap = shapely_area_m2(inter)
        if overlap <= 0:
            continue
        out.append((row, overlap))

    out.sort(key=lambda t: (t[0].planted_on or date.min), reverse=True)
    return out


# ---------------------------------------------------------------------------
# 면적 배분
# ---------------------------------------------------------------------------

def zone_allocation(zone_shape, on=None):
    """zone 의 면적 배분 → 각 구획의 면적/비율 + 미배정 면적.

    **겹침이 정상이므로 비율의 합은 100%를 넘을 수 있다**(간작·혼작). 그래서
    합계를 내지 않는다 — 화면에 합계를 띄우면 사용자는 그것을 오류로 읽는다.

    미배정은 반드시 **합집합**으로 뺀다. 단순 합으로 빼면 겹친 만큼 이중으로
    빠져 미배정이 음수가 된다.
    """
    zone_geom = geometry_of(zone_shape)
    zone_poly = _shapely(zone_geom)
    zone_area = shapely_area_m2(zone_poly)

    rows = active_plantings(zone_shape.geo_id, on=on)
    containers = device_membership.load_containers(zone_shape.geo_id)

    items, geoms = [], []
    for row in rows:
        # 같은 지도의 다른 zone 소속은 뺀다. 비교는 인스턴스가 아니라
        # unique_id 로 한다 — zone_shape 가 호출자가 따로 조회한 행이면
        # load_containers 가 돌려준 인스턴스와 다를 수 있다.
        zone_of = zone_for_planting(row, containers=containers)
        if zone_of is None or zone_of.unique_id != zone_shape.unique_id:
            continue
        poly = _shapely(geometry_of(row))
        if poly is None:
            continue
        a = shapely_area_m2(poly)
        geoms.append(poly)
        items.append({
            'unique_id': row.unique_id,
            'name': row.name,
            'crop': row.crop,
            'variety': row.variety,
            'area_m2': round(a, 1),
            'ratio_pct': round(a / zone_area * 100.0, 1) if zone_area > 0 else None,
        })

    used = 0.0
    if geoms:
        try:
            from shapely.ops import unary_union

            union = unary_union(geoms)
            if zone_poly is not None:
                union = union.intersection(zone_poly)
            used = shapely_area_m2(union)
        except Exception as exc:
            logger.warning('planting: 합집합 계산 실패 — 미배정 생략: %s', exc)
            used = None

    unassigned = None
    if used is not None and zone_area > 0:
        unassigned = max(zone_area - used, 0.0)

    return {
        'zone_uuid': zone_shape.unique_id,
        'zone_area_m2': round(zone_area, 1) if zone_area else 0.0,
        'plantings': items,
        'assigned_m2': round(used, 1) if used is not None else None,
        'unassigned_m2': round(unassigned, 1) if unassigned is not None else None,
        # 합계를 내지 않는 이유는 위 docstring 참조. 겹침이 있으면
        # sum(ratio_pct) > 100 이 정상이다.
        'overlaps': _has_overlap(geoms),
    }


def _has_overlap(geoms):
    """구획끼리 면적 있는 겹침이 있는가 — 화면에 "겹침 있음" 을 표시하기 위한 것.

    막기 위한 검사가 **아니다**. 겹침은 요구사항이다(VP-3).
    """
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            try:
                inter = geoms[i].intersection(geoms[j])
            except Exception:
                continue
            if not inter.is_empty and shapely_area_m2(inter) > 0:
                return True
    return False


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------

def to_dict(row, containers=None, with_sensors=False):
    """GeoPlanting → API 응답 dict."""
    out = {
        'unique_id': row.unique_id,
        'geo_id': row.geo_id,
        'feature': row.feature,
        'name': row.name,
        'crop': row.crop,
        'variety': row.variety,
        'planted_on': row.planted_on.isoformat() if row.planted_on else None,
        'ended_on': row.ended_on.isoformat() if row.ended_on else None,
        'expected_end_on': (row.expected_end_on.isoformat()
                            if row.expected_end_on else None),
        'ended_reason': row.ended_reason,
        'source_kind': row.source_kind,
        'source_ref': row.source_ref,
        'color': row.color,
        'active': row.is_active(),
        'area_m2': round(area_m2(row), 1),
        # None 은 "평평하다" 가 아니라 "모른다" — 화면과 AI 가 그 둘을 구분할 수
        # 있어야 규격을 물을 시점을 안다.
        'bed_width_cm': row.bed_width_cm,
        'path_width_cm': row.path_width_cm,
    }
    if with_sensors:
        out['sensors'] = sensors_for_planting(row, containers=containers)
    else:
        zone = zone_for_planting(row, containers=containers)
        out['zone_uuid'] = zone.unique_id if zone is not None else None
    return out
