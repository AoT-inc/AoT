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
import math
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


def local_frame(geom):
    """geometry → `(to_m, from_m, lat0)` — 도↔미터 변환 함수 쌍.

    **투영 정의는 여기 한 곳뿐이어야 한다.** 면적(`_ring_area_m2`)·치수
    (`dimensions`)·분할(`planting_split`)이 각자 상수를 들고 있으면 같은 구획이
    계산마다 조금씩 다른 평면에서 재어지고, 그 차이는 화면에서 설명되지 않는다.

    `from_m` 은 `to_m` 의 정확한 역함수다 — 분할처럼 미터 평면에서 만든 도형을
    다시 위경도로 돌려놓아야 하는 쪽이 쓴다.
    """
    import math

    lat0 = _mean_lat(geom)
    if lat0 is None:
        return None, None, None
    m_per_deg_lat = 111320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    if m_per_deg_lng == 0:
        return None, None, None

    def to_m(x, y, z=None):
        return (x * m_per_deg_lng, y * m_per_deg_lat)

    def from_m(x, y, z=None):
        return (x / m_per_deg_lng, y / m_per_deg_lat)

    return to_m, from_m, lat0


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
    to_m, _from_m, _lat0 = local_frame(geom)
    if to_m is None:
        return None
    return transform(to_m, poly)


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
                      edge_margin_cm=None, bed_pitch_cm=None,
                      rows_per_bed=None):
    """간격(cm) → 줄 수·그루 수. 아무것도 안 주면 None(묻지 않은 것).

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

    **`bed_pitch_cm` + `rows_per_bed` 가 있으면 두둑 배치로 센다.**

    처음에는 두둑 폭 + 고랑 폭을 따로 받았다가 폐기했다. 농부는 둘을 따로 세지
    않는다 — 두둑을 만들면 고랑은 딸려 온다. 그래서 "두둑 폭" 을 물으면 고랑을
    뺀 윗면으로 답하는 사람과 고랑까지 포함한 한 세트로 답하는 사람이 갈리고,
    같은 밭이 120+40 으로도 160+0 으로도 기록된다. 에러 없이 두둑 수만 달라진다.
    **간격 하나(고랑 포함 중심간 거리)로 받으면 그 갈림이 성립하지 않는다.**

    대신 두둑 하나에 몇 줄을 놓는지를 받는다 — 고추는 한 줄, 상추·배추는 두세
    줄이라 이 값 없이는 줄 수를 셀 수 없다. `row_spacing_cm` 은 **평평한
    배치에서만** 쓴다: 두둑 배치에서는 두둑당 줄 수가 그 자리를 대신하므로
    요구하면 쓰지도 않을 값을 묻는 셈이 된다.

    배치를 모르면 평평하게 깐 것으로 계산하되 응답에 `ask_user` 를 실어, 묻거나
    제안해 확정한 뒤 **구획 노트로 남기라고** 시킨다 — 고랑에는 아무것도 안
    심으므로 균일 배치는 두둑 농사에서 20~30% 과다추정이 되는데, 그 사실이
    응답에 없으면 AI 가 그 숫자를 그대로 확신하고 답한다.

    Raises:
        ValueError: 필요한 값이 빠졌거나, 두둑 배치를 한쪽만 주거나, 양수로
            읽히지 않는 값을 준 경우. 조용히 건너뛰면 사용자는 조건을 말했는데
            답에는 그것이 반영되지 않은 상태가 된다 — 무시된 것을 아무도 모른다.
    """
    if all(v is None for v in (row_spacing_cm, plant_spacing_cm,
                               edge_margin_cm, bed_pitch_cm, rows_per_bed)):
        return None
    if plant_spacing_cm is None:
        # 그루 간격 없이는 어떤 배치에서도 셀 수 없다. 조용히 무시하면
        # 사용자는 자기가 말한 조건이 반영된 줄 알고 답을 읽는다.
        raise ValueError('plant_spacing_cm is required to count anything')
    if (bed_pitch_cm is None) != (rows_per_bed is None):
        raise ValueError(
            'bed_pitch_cm and rows_per_bed must be given together — a bed '
            'spacing alone does not say how many rows go on one bed')

    def _cm(value, field):
        try:
            out = float(value)
        except (TypeError, ValueError):
            raise ValueError('%s must be a number in centimeters' % field)
        if out <= 0:
            raise ValueError('%s must be greater than 0' % field)
        return out

    def _cm0(value, field):
        """0 을 허용하는 길이 — 여백은 "없음" 이 유효한 값이다."""
        try:
            out = float(value)
        except (TypeError, ValueError):
            raise ValueError('%s must be a number in centimeters' % field)
        if out < 0:
            raise ValueError('%s cannot be negative' % field)
        return out

    def _count(value, field):
        """줄 수는 개수라 정수여야 한다 — 2.5줄은 밭에 놓을 수 없다."""
        try:
            out = float(value)
        except (TypeError, ValueError):
            raise ValueError('%s must be a whole number' % field)
        if out != int(out) or int(out) < 1:
            raise ValueError('%s must be a whole number of 1 or more' % field)
        return int(out)

    plant_cm = _cm(plant_spacing_cm, 'plant_spacing_cm')
    margin_cm = (0.0 if edge_margin_cm is None
                 else _cm0(edge_margin_cm, 'edge_margin_cm'))
    bedded = bed_pitch_cm is not None
    pitch_cm = _cm(bed_pitch_cm, 'bed_pitch_cm') if bedded else None
    per_bed = _count(rows_per_bed, 'rows_per_bed') if bedded else None

    # 줄 간격은 평평한 배치에서만 필요하다. 두둑 배치에서 요구하면 쓰지도 않을
    # 값을 묻는 셈이 된다.
    row_cm = None
    if not bedded:
        if row_spacing_cm is None:
            raise ValueError(
                'row_spacing_cm is required unless a bed layout is given '
                '(bed_pitch_cm + rows_per_bed)')
        row_cm = _cm(row_spacing_cm, 'row_spacing_cm')

    if not dims:
        return None

    # 공표된(반올림된) 치수로 센다 — AI 나 사용자가 답을 손으로 검산했을 때
    # 같은 숫자가 나와야 한다.
    usable_w = max(dims['width_m'] * 100.0 - 2 * margin_cm, 0.0)
    usable_l = max(dims['length_m'] * 100.0 - 2 * margin_cm, 0.0)

    per_row = int(usable_l // plant_cm)
    beds = None

    if bedded:
        # 간격이 이미 고랑을 품고 있으므로 `폭 ÷ 간격` 이 곧 두둑 수다. 폭과
        # 고랑을 따로 받던 때의 "마지막 고랑은 빼야 한다" 보정은 여기서 성립하지
        # 않는다 — 고랑이 얼마인지 더 이상 알지 못하기 때문이다. 그래서 마지막
        # 두둑의 고랑까지 세는 셈이 되어 한 두둑쯤 보수적으로 나올 수 있다.
        beds = int(usable_w // pitch_cm)
        rows = beds * per_bed
    else:
        rows = int(usable_w // row_cm)

    if rows == 0 or per_row == 0:
        if bedded and not beds:
            basis = (
                'Nothing fits: the usable width is %.1f m, not enough for one bed '
                'at %.0f cm spacing. Narrow the bed spacing or the edge margin.'
                % (usable_w / 100.0, pitch_cm))
        elif bedded:
            basis = (
                'Nothing fits: the usable length is %.1f m, shorter than one %.0f cm '
                'plant spacing.' % (usable_l / 100.0, plant_cm))
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
                '%d beds fit across the %.1f m usable width at %.0f cm spacing '
                '(that spacing already includes the furrow), with %d row(s) on each '
                'bed. Furrows carry no plants. The last bed\'s furrow is counted too, '
                'so this can be one bed conservative. '
                % (beds, usable_w / 100.0, pitch_cm, per_bed))
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
        out['bed_pitch_cm'] = pitch_cm
        out['rows_per_bed'] = per_bed
        # "두둑을 몇 줄이나 만들 수 있을까" 는 실제로 받은 질문이다. 줄 수에서
        # 역산하게 두지 말고 그 숫자 자체를 낸다.
        out['beds_possible'] = beds
    else:
        out['ask_user'] = _FLAT_LAYOUT_ASK

    return out


# 두둑 배치를 모를 때 응답에 싣는 지시. **조용히 균일 배치로 계산하고 마는 것이
# 이 필드가 막으려는 실패다** — 고랑에는 아무것도 안 심는데 균일 배치는 거기까지
# 줄을 세우므로 두둑 농사에서 20~30% 과다추정이 된다. 그런데 그 사실이 응답
# 어디에도 없으면 AI 는 그 숫자를 그대로 확신하고 답한다.
#
# 배치를 여기서 정해 내려보내지 않는 이유: 작물·지역·농기계 폭에 따라 달라서
# 서버가 아는 척할 수 있는 값이 아니다. 대신 묻거나 제안해 확정하고, 그 결론을
# **구획 노트로 남기라고** 시킨다.
#
# ⚠ 컬럼으로 저장하지 않는다. 한 번 그렇게 만들었다가 되돌렸다 —
# 대화에서 나오는 결론(두둑 배치·멀칭·지주·관행)마다 컬럼을 늘릴 수는 없고,
# 모호한 사람의 말을 정수 칸에 밀어 넣는 순간 "두둑 폭이 고랑 포함이냐" 같은
# 갈림이 생겨 같은 밭이 두 가지로 기록된다. 노트는 정확히 그런 것을 담으라고
# 있는 자리이고, 엔티티별 노트 다이제스트가 이미 AI 컨텍스트에 미리 실린다 —
# 다음 대화에서는 이 문장을 읽고 숫자만 파라미터로 넘기면 된다.
#
# ⚠ 특정 나라의 관행을 문장에 박지 말 것. 처음 판은 "Most **Korean** open-field
# vegetables…" 였는데, 이 제품은 ko/ja 를 함께 쓰고 설치처의 나라도 고정이 아니다.
_FLAT_LAYOUT_ASK = (
    'NO bed layout was assumed: rows are spread evenly across the whole width, '
    'which is only right for flat or broadcast planting. Open-field vegetables '
    'are commonly grown on raised beds with furrows between them, and furrows '
    'carry no plants — where that is the practice it cuts the count by 20-30%. '
    'Before you report this number, settle the layout with the grower: the bed '
    'spacing (centre to centre, the furrow included — ask it as ONE number, '
    'growers do not count a bed and its furrow separately) and how many rows go '
    'on one bed. Ask, or propose both and get them confirmed. Then call again '
    'with bed_pitch_cm and rows_per_bed. Once settled, WRITE IT DOWN as a note '
    'on this plot: create_note(target_id=<this planting_id>, '
    'target_type="planting", note="..."). The note is how the next conversation '
    'knows it — plot notes are pre-injected into your context, so nobody has to '
    'be asked twice. Do not present the flat-layout number as the answer without '
    'settling this first.'
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


def sensors_for_planting(planting, containers=None, markers=None):
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
        _label='planting %s' % planting.unique_id, markers=markers)))

    zone = zone_for_planting(planting, containers=containers)
    from_zone = []
    if zone is not None:
        from_zone = sorted(_only_sensor_ids(
            device_membership.device_ids_in_shape(zone, markers=markers)))

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
# 관수 — 밸브 담당 구역과의 교차
# ---------------------------------------------------------------------------
#
# 밸브와 식생은 **계층이 아니라 교차**다. 밸브 하나가 상추와 배추를 같이
# 적시고, 한 작물이 두 밸브에 걸치기도 한다. 그래서 소속으로 묶지 않고
# 겹치는 면적을 낸다(설계 §자원 배분).
#
# 담당 구역은 `GeoShape type='device'` 폴리곤이다. 장치 해소는 `device_binding`
# 이 정본이고, 바인딩이 없으면 미배정 슬롯 — 그 자체가 정보라 함께 돌려준다
# ("이 구획은 밸브가 안 정해진 구역에 걸쳐 있다").

def valves_for_planting(planting):
    """구획을 적시는 밸브 목록.

    `[{shape_uuid, shape_name, device_id, device_name, overlap_m2,
       coverage_pct}]` — `coverage_pct` 는 **구획 면적 대비** 덮인 비율이다.
    밸브 구역 대비가 아니다: 사람이 알고 싶은 것은 "내 두둑이 얼마나 젖는가"
    이지 "밸브가 얼마나 쓰이는가" 가 아니다.

    관수량을 여기서 계산하지 않는다. 겹친 영역에서 물은 물리적으로 공유되므로
    작물별 요구량을 합산하면 틀린 숫자가 나온다 — 재료만 내고 판단은 사람이
    한다(설계 §자원 배분).
    """
    from aot.aot_flask.geo import device_binding

    src = _shapely(geometry_of(planting))
    if src is None:
        return []
    total = shapely_area_m2(src)

    rows = GeoShape.query.filter(
        GeoShape.geo_id == planting.geo_id,
        GeoShape.type == 'device').all()

    out = []
    for shape in rows:
        other = _shapely(geometry_of(shape))
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

        device_id, device_name = None, None
        try:
            binding = device_binding.current_one('shape', shape.unique_id,
                                                 role='area')
            if binding is not None:
                device_id = binding.device_id
                device_name = device_binding._device_names(
                    [device_id]).get(device_id)
        except Exception as exc:
            logger.warning('planting: 밸브 바인딩 해소 실패(%s): %s',
                           shape.unique_id, exc)

        out.append({
            'shape_uuid': shape.unique_id,
            'shape_name': _shape_name(shape),
            'device_id': device_id,
            'device_name': device_name,
            'overlap_m2': round(overlap, 1),
            'coverage_pct': round(overlap / total * 100.0, 1) if total > 0 else None,
            # 밸브가 안 정해진 구역에 걸친 것도 알아야 한다 — 물을 줄 수단이
            # 아직 없다는 뜻이다.
            'unassigned': device_id is None,
        })

    out.sort(key=lambda v: v['overlap_m2'], reverse=True)
    return out


def plantings_covered_by_shape(shape_geom, map_uuid, on=None,
                               exclude_uuid=None, candidates=None):
    """도형(관수 구역 등)이 덮는 **재배 중인** 구획들.

    `valves_for_planting` 의 **역방향**이다. 그쪽이 "이 구획을 적시는 밸브" 라면
    이쪽은 "이 밸브가 적시는 구획들" 이다.

    제어 화면에 이 방향이 필요한 이유: 밸브를 켜는 사람이 알아야 하는 것은 "이
    구획이 얼마나 젖는가" 가 아니라 **"켜면 무엇이 함께 젖는가"** 다. 겹침이
    정상인 도메인(간작·혼작, VP-3)이라 한 밸브가 여러 작물을 적시는 것이 예외가
    아니라 기본이고, 그 사실을 말하지 않으면 사용자는 자기가 고른 작물에만
    물을 준다고 읽는다.

    `candidates` 로 활성 구획 목록을 넘기면 재사용한다 — 밸브마다 다시 조회하면
    밸브 수 × 구획 수가 된다.
    """
    src = _shapely(shape_geom)
    if src is None:
        return []

    rows = candidates if candidates is not None else active_plantings(map_uuid, on=on)
    out = []
    for row in rows:
        if exclude_uuid and row.unique_id == exclude_uuid:
            continue
        other = _shapely(geometry_of(row))
        if other is None:
            continue
        try:
            inter = src.intersection(other)
        except Exception:
            continue
        if inter.is_empty:
            continue
        # 경계를 맞대고 있을 뿐인 옆 두둑을 "함께 젖는다" 고 하면 안 된다 —
        # 면적이 있는 교차만 센다(plantings_overlapping 과 같은 기준).
        overlap = shapely_area_m2(inter)
        if overlap <= 0:
            continue
        out.append({
            'unique_id': row.unique_id,
            'crop': row.crop,
            'name': row.name,
            'overlap_m2': round(overlap, 1),
        })
    out.sort(key=lambda p: p['overlap_m2'], reverse=True)
    return out


def plantings_by_valve_device(map_uuid, on=None):
    """`{device_id: [구획, ...]}` — 지도의 관수 장치별로 "무엇을 적시는가".

    **구역 모달과 식생 모달이 함께 쓴다.** 구역에서 켠 밸브도 그 안의 여러
    작물에 물을 준다 — 식생 모달에만 경고를 붙이면 "구역에서 켜면 안전하다"는
    잘못된 대비가 생긴다. 같은 사실을 양쪽이 같은 근거로 말해야 한다.

    지도 전체를 **한 번에** 만든다. 출력마다 되짚으면 출력 수 × 도형 수 ×
    구획 수가 되는데, 구역 모달은 출력이 여럿이라 그 곱이 바로 드러난다.
    """
    from aot.aot_flask.geo import device_binding

    active = active_plantings(map_uuid, on=on)
    if not active:
        return {}

    shapes = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.type == 'device').all()

    out = {}
    for shape in shapes:
        covered = plantings_covered_by_shape(
            geometry_of(shape), map_uuid, on=on, candidates=active)
        if not covered:
            continue
        try:
            binding = device_binding.current_one('shape', shape.unique_id,
                                                 role='area')
        except Exception as exc:
            logger.warning('planting: 밸브 바인딩 해소 실패(%s): %s',
                           shape.unique_id, exc)
            continue
        device_id = binding.device_id if binding is not None else None
        if not device_id:
            # 밸브 미배정 구역 — 켤 장치가 없으니 "함께 젖는다" 를 말할 대상도
            # 없다. 미배정 사실 자체는 valves_for_planting 이 따로 낸다.
            continue
        # 같은 장치가 여러 관수 구역에 걸릴 수 있다 — 구획 기준으로 합친다.
        bucket = out.setdefault(device_id, {})
        for c in covered:
            prev = bucket.get(c['unique_id'])
            if prev is None or c['overlap_m2'] > prev['overlap_m2']:
                bucket[c['unique_id']] = c

    return {did: sorted(items.values(),
                        key=lambda p: p['overlap_m2'], reverse=True)
            for did, items in out.items()}


def nearest_devices(planting, candidate_ids, markers=None, limit=1):
    """구획에서 **가장 가까운** 장치 → `[(device_id, 거리_m)]`.

    구획 안에도 없고 구획을 적시지도 않는데 "이 구역에 있다" 는 이유만으로
    목록에 넣으면, 식생 패널이 구역 패널의 복사본이 된다 — 그럴 거면 구역
    패널을 열면 된다. 직접 닿는 것이 하나도 없을 때만, 값을 읽을 최소한의
    수단으로 가장 가까운 것을 낸다.

    거리는 구획의 **대표점**에서 장치 마커까지다. 대표점은 오목한 폴리곤에서도
    반드시 내부에 있다(centroid 는 밖으로 나갈 수 있다 — container_for_geometry
    와 같은 이유).

    마커가 없는 장치는 **뺀다**. 위치를 모르면 "가장 가깝다" 고 말할 근거가
    없고, 근거 없이 고른 것을 대표값으로 내세우는 쪽이 아무것도 안 내는 것보다
    나쁘다.
    """
    if not candidate_ids:
        return []

    poly = _shapely(geometry_of(planting))
    if poly is None:
        return []
    try:
        ref = poly.representative_point()
    except Exception:
        return []

    to_m, _from_m, lat0 = local_frame(geometry_of(planting))
    if to_m is None:
        return []
    rx, ry = to_m(ref.x, ref.y)

    if markers is None:
        markers = device_membership.load_markers(planting.geo_id)

    best = {}
    for device_id, pt in markers:
        if device_id not in candidate_ids or not pt:
            continue
        mx, my = to_m(pt[0], pt[1])
        d = math.hypot(mx - rx, my - ry)
        if device_id not in best or d < best[device_id]:
            best[device_id] = d

    ordered = sorted(best.items(), key=lambda kv: kv[1])
    return [(did, round(d, 1)) for did, d in ordered[:max(limit, 0)]]


def covered_crop_names(covered, exclude_uuid=None):
    """구획 목록 → 화면에 쓸 이름들. **uuid 는 내보내지 않는다.**

    `crop` 이 사람이 부르는 이름이고, 없으면 구획 이름으로 떨어진다.
    """
    names = []
    for c in covered or []:
        if exclude_uuid and c.get('unique_id') == exclude_uuid:
            continue
        label = c.get('crop') or c.get('name')
        if label and label not in names:
            names.append(label)
    return names


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
            # 달력만 보는 값이라 여기서 함께 낸다 — 구역 [현황]이 "무엇이
            # 며칠째 자라고 있나" 를 한 줄로 말할 수 있어야 한다.
            'days_since_planted': elapsed_days(row, on=on),
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

def elapsed_days(row, on=None):
    """재배 일수 — **심은 날이 1일차**. 기하가 아니라 달력만 본다.

    +1 을 여기서 한 번만 한다. 화면마다 "0일차부터 세는 곳" 과 "1일차부터 세는
    곳" 이 갈리면 같은 두둑이 창마다 하루씩 다른 나이를 갖는다. 농사에서 "정식
    후 며칠" 은 심은 날을 1일로 세는 관행이라 그쪽에 맞춘다.

    종료된 작기는 오늘이 아니라 **종료일** 을 기준으로 센다 — 작년에 끝난 작기가
    오늘까지 계속 나이를 먹으면 이력 목록이 곧 거짓말이 된다.
    """
    if row.planted_on is None:
        return None
    ref = row.ended_on or (on or date.today())
    return (ref - row.planted_on).days + 1


def days_to_expected_end(row, on=None):
    """예상 종료일까지 남은 날 (음수 = 지났다). 없으면 None.

    지난 것을 숨기지 않는다 — "예상보다 20일 지났다" 는 수확을 미루고 있다는
    뜻이라 그 자체가 사용자가 봐야 할 사실이다.
    """
    if row.expected_end_on is None or row.ended_on is not None:
        return None
    return (row.expected_end_on - (on or date.today())).days


def to_dict(row, containers=None, with_sensors=False, markers=None,
            with_valves=None, with_dims=None):
    """GeoPlanting → API 응답 dict.

    `with_valves` 는 기본적으로 `with_sensors` 를 따른다 — 상세 조회의 기존
    동작을 그대로 둔다. 목록처럼 **센서만** 필요한 자리는 `with_valves=False`
    로 밸브 교차를 뺀다. 실측(구획 8개): 센서 37 쿼리 · 밸브 120 쿼리로 비용의
    대부분이 밸브 쪽이라, 둘을 한 플래그로 묶어 두면 가벼운 센서까지 함께
    막힌다.

    `with_dims` 도 기본은 `with_sensors` 를 따른다. DB 를 타지 않지만 구획마다
    최소회전 외접사각형을 구하는 기하 계산이라, 목록 응답에서 행 수만큼 돌릴
    이유가 없다 — 치수를 읽는 자리는 상세(모달) 하나다.

    ⚠ `dims['shape_note']` 는 **사람에게 보여줄 문구가 아니다.** AI 에게 "이
    숫자를 보고할 때 이렇게 말하라" 고 지시하는 문장이라, 화면에 그대로 띄우면
    사용자가 자기에게 하는 말이 아닌 지시문을 읽게 된다. 화면은 대신
    `rect_fill_pct` 를 근거로 자기 문구를 만든다.
    """
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
        # 달력만 보는 값이라 목록에서도 항상 싣는다 — 구역 모달의 "지금 심겨
        # 있는 것" 목록이 이 값으로 재배 일수를 보인다.
        'days_since_planted': elapsed_days(row),
        'days_to_expected_end': days_to_expected_end(row),
    }
    if with_valves is None:
        with_valves = with_sensors
    if with_dims is None:
        with_dims = with_sensors
    if with_dims:
        out['dims'] = dimensions(row)
    if with_sensors:
        out['sensors'] = sensors_for_planting(row, containers=containers,
                                              markers=markers)
    else:
        zone = zone_for_planting(row, containers=containers)
        out['zone_uuid'] = zone.unique_id if zone is not None else None
    if with_valves:
        # 목록에서 구획마다 지도 도형을 전량 훑으면 구획 수 × 도형 수가 된다.
        out['valves'] = valves_for_planting(row)
    return out
