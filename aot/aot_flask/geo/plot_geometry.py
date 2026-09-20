# coding=utf-8
"""식생 구획(작기)의 기하·치수·소속·센서 — `plot_context` 에서 뗀 순수 기반층.

`plot_context.py` 의 함수 83개 중 이 묶음(기하 헬퍼·치수·소속·센서)만 **밖으로
나가는 참조가 0** 이었다 — 나머지는 서로 순환 의존이 있어 떼지 않았다. 이 모듈은
`plot_context` 를 들여오지 않는다(들여오면 순환이 생긴다); `plot_context` 가
이 모듈을 들여와 이름을 재노출한다.

설계 정본: docs/design/geo-vegetation-plot.md
"""
import logging

from aot.aot_flask.geo import device_membership
from aot.aot_flask.geo.facility_calc import _ring_area_m2
from aot.databases.models import Input, Output

logger = logging.getLogger(__name__)

_POLY_TYPES = ('Polygon', 'MultiPolygon')


# ---------------------------------------------------------------------------
# 기하 헬퍼
# ---------------------------------------------------------------------------

def geometry_of(row, facilities=None):
    """GeoPlot | GeoShape → GeoJSON geometry dict ({} 이면 없음).

    ## 시설 구획은 여기서 기하를 **파생**한다 (p6_39)

    시설 구획은 위치의 정본이 부모(`facility_uuid`/`bay_id`)라 자기 기하가
    없다. 그런 행은 시설 외피의 기하를 돌려준다 — **지도에 그리고, 클릭하고,
    상위 zone 을 판정하기 위한 것**이다.

    이 함수가 유일한 폴백 지점인 것이 핵심이다. `area_m2` · `dimensions` ·
    `sensors_for_plot` · `zone_for_plot` · `valves_for_plot` 이
    전부 여기를 지나므로, 폴백을 여기 한 번 넣으면 나머지가 따라온다.
    **새 읽기 경로에서 `row.feature` 를 직접 파지 말 것** — 그 자리에서
    시설 구획만 조용히 빠진다(이 도메인이 반복해서 겪은 "읽는 경로마다 기준이
    다름" 이 정확히 그렇게 생긴다).

    ⚠ **파생값을 저장하지 말 것.** 응답에만 실린다. 되써 넣으면 시설을 옮겨도
    구획은 옛 자리에 남는다(색 각인 sync-back 이 만든 것과 같은 종류의 고정).

    ⚠ **면적의 근거로 쓰지 말 것.** 파생 기하는 구역이 아니라 시설 외피라
    실제 재배 면적보다 크고, 애초에 시설은 노지형·베드형·수직형에 따라 같은
    바닥 면적이 전혀 다른 재배 규모다. 면적을 내는 자리는
    `has_own_geometry()` 로 먼저 거른다.

    `facilities` 를 넘기면(= `{facility_uuid: geometry}`) 시설 조회를 생략한다.
    """
    import json

    feat = getattr(row, 'feature', None)
    if isinstance(feat, str):
        try:
            feat = json.loads(feat)
        except (ValueError, TypeError):
            feat = None
    if isinstance(feat, dict):
        geom = feat.get('geometry')
        if isinstance(geom, dict) and geom.get('coordinates'):
            return geom

    facility_uuid = getattr(row, 'facility_uuid', None)
    if facility_uuid:
        return facility_geometry(facility_uuid,
                                 bay_id=getattr(row, 'bay_id', None),
                                 facilities=facilities)

    return {}


def facility_geometry(facility_uuid, bay_id=None, facilities=None):
    """시설(또는 그 구역)의 GeoJSON geometry ({} 이면 없음).

    `bay_id` 를 주면 **그 구역만큼**으로 좁힌다(`facility_bays.slice_geometry`).
    좁히지 못하면 시설 외피로 폴백한다 — 재료(중심·방위·치수)가 없는 시설도
    지도에 자리는 있어야 하기 때문이다. 지어내지 않고 넓게 잡는 쪽을 고른다.
    """
    brief = facility_brief(facility_uuid, facilities=facilities)
    if bay_id:
        geom = (brief.get('bay_geometries') or {}).get(bay_id)
        if geom:
            return geom
    return brief.get('geometry') or {}


_CAPACITY_UNITS = ('bed', 'row', 'tray', 'area', 'house')


def bay_capacities(fac):
    """`GeoFacility` 행 → `{bay_id: {'unit': str, 'total': number}}` (p6_50).

    구역 메타(`bays[]`)에 사람이 적어 둔 총량만 추린다. 값이 없거나 모양이
    어긋난 구역은 **그냥 빠진다** — 총량이 없는 것은 오류가 아니라 "아직 안
    적었다" 이고, 그때는 구획이 비율(percent)로 몫을 적는다.

    단위를 자유 문자열로 두지 않는 이유는 번역과 집계가 곧 갈리기 때문이다.
    어휘를 고정하고 표시 문구만 번역한다.
    """
    out = {}
    bays = fac.bays if isinstance(fac.bays, list) else []
    for b in bays:
        if not isinstance(b, dict):
            continue
        cap = b.get('capacity')
        if not isinstance(cap, dict):
            continue
        try:
            total = float(cap.get('total'))
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        unit = cap.get('unit')
        if unit not in _CAPACITY_UNITS:
            unit = 'bed'
        bid = b.get('id')
        if not bid:
            continue
        out[bid] = {'unit': unit,
                    'total': int(total) if float(total).is_integer()
                             else round(total, 2)}
    return out


def allocation_view(allocation, capacity):
    """저장된 몫 + 구역 총량 → 화면이 그대로 쓰는 dict (없으면 None).

        {'amount': 4, 'total': 12, 'unit': 'bed', 'percent': 33.3}
        {'percent': 33}                      # 총량이 없는 시설

    `percent` 는 **여기서 파생한다.** `amount` 만 저장하고 비율을 만들어 내는
    것이 요지다 — 총량을 12에서 10으로 고치면 같은 4베드가 33%에서 40%가 되어야
    하는데, 비율을 저장해 두면 그 순간 둘이 갈린다.

    총량이 있는데 구획이 `percent` 로 적혀 있으면(총량을 나중에 적은 경우)
    그 값을 그대로 쓴다 — 서버가 어림해 `amount` 로 옮겨 적지 않는다. 어느
    베드인지는 사람만 안다.
    """
    if not isinstance(allocation, dict) or not allocation:
        return None
    out = dict(allocation)
    if isinstance(capacity, dict) and capacity.get('total'):
        out['total'] = capacity.get('total')
        out['unit'] = capacity.get('unit')
        if out.get('amount') is not None:
            try:
                pct = float(out['amount']) / float(capacity['total']) * 100.0
                out['percent'] = round(pct, 1)
            except (TypeError, ValueError, ZeroDivisionError):
                pass
    return out


def facility_brief(facility_uuid, facilities=None):
    """시설 요약 → `{'unique_id', 'name', 'geometry'}` (없으면 빈 dict).

    `bay_geometries` 는 `{bay_id: geometry}` — 구역 단위 파생 기하다(파생이므로
    저장하지 않는다). `bay_names` 는 `{bay_id: 이름}` — 사람은 'bay_2' 가 아니라
    '2동' 이라고 읽는다.

    `facilities` 를 넘기면 그 dict 를 캐시로 쓴다(목록 응답에서 시설 조회가
    구획 수만큼 반복되지 않도록). 캐시 값의 모양은 이 함수의 반환값과 같다 —
    캐시마다 다른 모양을 담으면 쓰는 쪽이 각자 기억해야 한다.
    """
    if not facility_uuid:
        return {}
    if isinstance(facilities, dict) and facility_uuid in facilities:
        return facilities.get(facility_uuid) or {}

    from aot.databases.models import GeoFacility, GeoShape

    brief = {}
    fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if fac is not None:
        geom = {}
        if fac.shape_uuid:
            shape = GeoShape.query.filter_by(unique_id=fac.shape_uuid).first()
            if shape is not None:
                geom = geometry_of(shape)
        # 구역 기하는 시설 하나당 한 번만 계산해 캐시에 담는다 — 구획마다
        # 다시 만들면 같은 삼각함수를 행 수만큼 돈다.
        bay_geoms, bay_names = {}, {}
        try:
            from .facility_bays import (compute_bay_slices, slice_geometry,
                                        spec_from_row)
            spec = spec_from_row(fac)
            for sl in compute_bay_slices(spec):
                bay_names[sl['id']] = sl.get('name')
                g = slice_geometry(spec, sl)
                if g:
                    bay_geoms[sl['id']] = g
        except Exception as exc:
            logger.warning('plot: 시설 %s 구역 기하 계산 실패 — 외피로 '
                           '폴백: %s', facility_uuid, exc)
        # 구역 총량(p6_50) — "12베드" 처럼 **사람이 세는 단위**의 전체 수량.
        # 구획의 몫(`allocation.amount`)이 이것을 분모로 삼는다. 시설이 정하는
        # 사실이므로 구획은 참조만 한다 — 구획 저장이 이 값을 고칠 수 있으면
        # 마지막에 저장한 구획이 분모를 정하게 된다.
        brief = {'unique_id': fac.unique_id, 'name': fac.name, 'geometry': geom,
                 'bay_geometries': bay_geoms, 'bay_names': bay_names,
                 'bay_capacities': bay_capacities(fac)}
    if isinstance(facilities, dict):
        facilities[facility_uuid] = brief
    return brief


def _shapely(geom):
    """geometry dict → shapely, 실패/비폴리곤이면 None."""
    from shapely.geometry import shape as shapely_shape

    if not geom or geom.get('type') not in _POLY_TYPES:
        return None
    try:
        return shapely_shape(geom)
    except Exception as exc:
        logger.warning('plot: 기하 해석 실패: %s', exc)
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
    """GeoPlot | GeoShape 의 면적 (m²). 기하가 없으면 0."""
    return shapely_area_m2(_shapely(geometry_of(row)))


# ---------------------------------------------------------------------------
# 치수 — 면적 하나로는 답할 수 없는 질문을 위해
# ---------------------------------------------------------------------------
#
# "40cm 간격으로 8줄 심을 공간이 되나" 는 방향이 있는 질문인데 `area_m2` 는
# 스칼라라 방향이 없다. 1837m² 가 40×46 인지 5×367 인지에 따라 답이 갈린다.
#
# 그렇다고 원본 좌표를 그대로 내보내면 안 된다 — 구획 하나가 좌표 수백 개고,
# AI 컨텍스트에 실리는 값은 `_plot_brief` 가 `feature` 를 떼는 것으로
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
    (`dimensions`)·분할(`plot_split`)이 각자 상수를 들고 있으면 같은 구획이
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
        logger.warning('plot: 외접사각형 계산 실패: %s', exc)
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
    'which is only right for flat or broadcast plot. Open-field vegetables '
    'are commonly grown on raised beds with furrows between them, and furrows '
    'carry no plants — where that is the practice it cuts the count by 20-30%. '
    'Before you report this number, settle the layout with the grower: the bed '
    'spacing (centre to centre, the furrow included — ask it as ONE number, '
    'growers do not count a bed and its furrow separately) and how many rows go '
    'on one bed. Ask, or propose both and get them confirmed. Then call again '
    'with bed_pitch_cm and rows_per_bed. Once settled, WRITE IT DOWN as a note '
    'on this plot: create_note(target_id=<this plot_id>, '
    'target_type="plot", note="..."). The note is how the next conversation '
    'knows it — plot notes are pre-injected into your context, so nobody has to '
    'be asked twice. Do not present the flat-layout number as the answer without '
    'settling this first.'
)


# ---------------------------------------------------------------------------
# 소속 — 파생, 저장하지 않는다
# ---------------------------------------------------------------------------

def zone_for_plot(plot, containers=None):
    """구획을 감싸는 zone/site GeoShape (없으면 None).

    `containers` 를 넘기면 재사용한다 — 목록 응답에서 구획마다 지도 도형
    전량을 다시 훑지 않도록.
    """
    return device_membership.container_for_geometry(
        plot.geo_id, geometry_of(plot), containers=containers)


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


def _only_output_ids(device_ids):
    """장치 참조 집합에서 Output(액추에이터)만 남긴다 — `_only_sensor_ids`의 대칭.

    `device_membership.device_ids_in_area()`는 PID·CustomController의 uuid도
    함께 낸다(구역을 참조하는 제어기까지 잡는 것이 그 함수의 목적이다). 여기서
    거르지 않으면 그 uuid들이 'control' 목록에 섞여 화면이 존재하지 않는
    가동시간을 조회하려 든다 — 모델에 없는 uuid는 이 필터로 자연히 탈락한다.
    """
    if not device_ids:
        return set()
    rows = Output.query.with_entities(Output.unique_id).filter(
        Output.unique_id.in_(list(device_ids))).all()
    return {r[0] for r in rows}


def facility_sensor_ids(facility_uuid, bay_id=None):
    """시설 구획이 볼 센서 → `{'in_bay': [...], 'facility': [...]}` (Input uuid).

    시설 센서는 `facility.fittings[]` 에 로컬 미터 좌표로 붙어 있고 **지도
    마커가 아니다.** 그래서 `device_ids_in_geometry`(마커만 본다)로는 하나도
    잡히지 않는다 — 이것이 온실 안 구획이 시설 밖 zone 센서로 폴백하던 원인이다.

    구역 귀속은 기하 교차가 아니라 **로컬 x 좌표 → 슬라이스 매핑**으로 한다
    (`facility_bays.build_fitting_bay_map`). 부모 참조가 이미 구역 id 를 들고
    있으므로 겹침 계산이 필요 없다.

    `bay_id` 가 None(= 다동 시설에서 "시설 전체")이면 `in_bay` 는 비고 시설
    전체가 `facility` 로 나온다.

    ⚠ 반환값을 저장하지 말 것 — 바인딩을 만드는 것도 금지다
    (`sensors_for_plot` 의 같은 경고와 같은 이유).
    """
    from .facility_bays import build_fitting_bay_map, compute_bay_slices
    from .facility_io import FacilityManager

    if not facility_uuid:
        return {'in_bay': [], 'facility': []}

    # _to_dict 를 지나야 fitting 의 장치가 **바인딩 기준**으로 해소된다
    # (facility_io 의 유일한 출구). 저장된 레거시 값을 직접 읽으면 배정을
    # 바꿔도 여기만 옛 장치를 계속 본다.
    fac, err = FacilityManager.get_facility(facility_uuid)
    if err or not fac:
        return {'in_bay': [], 'facility': []}

    fittings = fac.get('fittings') or []
    # ⚠ **실외 센서는 뺀다.** 구획은 시설 **안**에서 무엇이 자라는가의 단위이고,
    # 그 값은 기르는 대상이 실제로 겪는 환경이어야 한다. 기상대를 섞으면 같은
    # '온도' 가 두 뜻으로 한 목록에 서고, 겨울에 안 25°C · 밖 -5°C 면 어느 쪽이
    # 이 작물의 온도인지 화면이 답하지 못한다.
    #
    # 안팎을 가르는 것은 사람이 시설 편집기에서 정한 `sensor_role` 하나뿐이다 —
    # **위치로는 가릴 수 없다**(기상대도 시설 어딘가에 서 있어서 좌표 → 슬라이스
    # 매핑이 그것에 동을 붙인다). 미설정은 실내로 본다: 서버·프런트가 쓰는 것과
    # 같은 폴백이라, 여기서만 다르게 잡으면 같은 센서가 화면마다 안팎이 갈린다.
    #
    # 반대로 **시설 모달의 환경 카드에는 실외가 들어간다** — 시설은 안과 밖을
    # 함께 다루는 단위이고, 창을 열거나 커튼을 치는 판단이 바깥값에서 나온다.
    # 두 화면이 같은 시설을 보면서 목록이 다른 것은 의도된 것이다.
    sensor_fittings = [f for f in fittings
                       if f.get('kind') == 'sensor' and f.get('input_id')
                       and (f.get('sensor_role') or 'indoor') != 'outdoor']
    if not sensor_fittings:
        return {'in_bay': [], 'facility': []}

    all_ids = {f['input_id'] for f in sensor_fittings}
    in_bay = set()
    if bay_id:
        slices = compute_bay_slices(fac)
        fitting_bay = build_fitting_bay_map(slices, sensor_fittings)
        for f in sensor_fittings:
            if fitting_bay.get(f.get('id')) == bay_id:
                in_bay.add(f['input_id'])

    # 실존 확인은 여기서 한 번만 — fitting 은 죽은 참조를 들고 있을 수 있다
    # (check_geo_integrity 의 dangling-fitting 이 세는 그것).
    live = _only_sensor_ids(all_ids)
    return {
        'in_bay':   sorted(i for i in in_bay if i in live),
        'facility': sorted(live),
    }
