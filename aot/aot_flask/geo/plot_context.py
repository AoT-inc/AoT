# coding=utf-8
"""식생 구획(작기)의 파생 계산 — 소속·센서·면적.

설계 정본: docs/design/geo-vegetation-plot.md

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
from aot.databases.models import GeoPlot, GeoShape, Input

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


# 자원 역할 → 시설 fitting 종류. **관수만 현장 어휘가 있다.**
#
# 시설 설계기의 fitting 종류에 시비(fertigation) 항목이 아직 없다. 없는 어휘를
# 지어내지 않는다 — 지어내면 화면에 나가는 순간 되돌리기 어렵고, 실제 배관과
# 무관한 분류가 데이터에 남는다(`_FIXED_TARGET_DEFS` 가 가축·시설을 빈 목록으로
# 시작하는 것과 같은 태도). 그래서 시비·기타는 "이 자리에서 찾을 수 없음" 으로
# 정직하게 보고하고, 그 이유(`reason`)를 함께 낸다.
_ROLE_FITTING_KINDS = {
    'irrigation': ('irrigation_valve', 'irrigation_layer'),
}


def declared_roles(stage, program_row=None):
    """이 단계가 요구하는 자원 역할 → `[{role, source}]` (P6).

    프로그램의 `resource_defs` 가 기본값을 정하고 단계의 `resources` 가 그것을
    덮어쓴다 — 목표(`_stage_targets`)와 같은 패턴이다. `source` 로 어느 쪽에서
    왔는지 밝힌다(`'stage'` | `'default'`): 밝히지 않으면 사람이 "이 단계에서
    일부러 끈 것" 과 "원래 안 쓰는 것" 을 구분할 수 없다.
    """
    defs = []
    if program_row is not None:
        try:
            defs = program_row.resource_def_list() or []
        except Exception:                                   # noqa: BLE001
            defs = []
    if not defs:
        return []

    over = (stage or {}).get('resources') if isinstance(stage, dict) else None
    over = over if isinstance(over, dict) else {}

    out = []
    for d in defs:
        role = (d or {}).get('role')
        if not role:
            continue
        if role in over:
            use, source = bool(over[role]), 'stage'
        else:
            use, source = bool(d.get('default', True)), 'default'
        if use:
            out.append({'role': role, 'source': source})
    return out


def functions_for_role(role, plot):
    """그 역할을 이 자리에서 맡는 함수 → `(list, reason)`.

    ## 계획이 아니라 현장이 답한다

    프로그램은 역할만 선언한다(P6 재설계). **무엇이 그 일을 하는지는 여기서
    푼다** — 계획이 함수를 미리 지목하면 같은 프로그램을 두 번째 자리에서 쓸 때
    복제해야 하고, 그 순간 작물 지식이 두 벌이 되어 한쪽만 고쳐진다.

    ## 경로

    시설이 이미 "어느 출력이 관수인가" 를 알고 있다(`fittings[].kind`). 그
    출력을 켜는 함수를 `Actions.do_unique_id` 로 되짚는다 — 함수가 무엇을 켜는지는
    그 표가 정본이다(`irrigation_status` 가 쓰는 것과 같은 길).

    `bay_id` 가 있으면 그 구역의 피팅만 본다(`facility_sensor_ids` 와 같은
    슬라이스 매핑). 없으면 시설 전체다.

    ## 찾지 못하면 이유를 낸다

    빈 목록만 돌려주면 화면은 "없다" 까지만 말하고 사람은 무엇을 고쳐야 할지
    모른다. `reason` 은 `'ok'` | `'no-facility'`(노지 — 아직 현장 어휘가 없다) |
    `'no-vocabulary'`(그 역할에 대응하는 fitting 종류가 없다) |
    `'not-placed'`(자리는 맞는데 그 역할의 장치가 배치돼 있지 않다).

    ⚠ 반환값을 저장하지 말 것 — `sensors_for_plot` 과 같은 이유다(파생값을 컬럼에
    쓰면 구획이 끝나도 옛 값이 남는다).
    """
    kinds = _ROLE_FITTING_KINDS.get(role)
    if not kinds:
        return [], 'no-vocabulary'

    facility_uuid = getattr(plot, 'facility_uuid', None) if plot else None
    if not facility_uuid:
        # 노지 구획. 출력 마커를 기하로 찾는 길은 있으나 "이 출력이 관수다" 를
        # 말해 주는 어휘가 노지에는 아직 없다 — 시설의 fitting 종류에 해당하는
        # 것이 없다. 없는 것을 추측해 물을 틀지 않는다.
        return [], 'no-facility'

    from .facility_bays import build_fitting_bay_map, compute_bay_slices
    from .facility_io import FacilityManager

    # `_to_dict` 를 지나야 fitting 의 장치가 바인딩 기준으로 해소된다.
    fac, err = FacilityManager.get_facility(facility_uuid)
    if err or not fac:
        return [], 'not-placed'

    fittings = [f for f in (fac.get('fittings') or [])
                if isinstance(f, dict) and f.get('kind') in kinds
                and f.get('actuator_id')]
    if not fittings:
        return [], 'not-placed'

    bay_id = getattr(plot, 'bay_id', None)
    if bay_id:
        slices = compute_bay_slices(fac)
        fitting_bay = build_fitting_bay_map(slices, fittings)
        scoped = [f for f in fittings
                  if fitting_bay.get(f.get('id')) == bay_id]
        # 구역에 하나도 없으면 시설 전체로 넓히지 **않는다** — 넓히면 옆 구역의
        # 밸브를 이 구획의 것이라고 말하게 된다. 센서(표시)와 달리 자원은
        # 물이 나오는 쪽이라 폴백이 조용히 틀리면 안 된다.
        fittings = scoped
        if not fittings:
            return [], 'not-placed'

    outputs = {f['actuator_id'] for f in fittings}
    return _functions_driving(outputs), 'ok'


def _functions_driving(output_uuids):
    """그 출력을 켜는 함수 → `[{id, name, active}]`.

    `Actions.do_unique_id` 는 `'uuid,channel'` 형태로도 온다 — 출력 uuid 만 본다.
    """
    if not output_uuids:
        return []
    from aot.databases.models import (Actions, Conditional, CustomController,
                                      PID, Trigger)

    try:
        rows = Actions.query.all()
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[자원] 액션 조회 실패: %s', exc)
        return []

    fn_ids = []
    for a in rows:
        ref = (a.do_unique_id or '').strip()
        if ref and ref.split(',')[0] in output_uuids and a.function_id:
            if a.function_id not in fn_ids:
                fn_ids.append(a.function_id)

    out = []
    for fid in fn_ids:
        for model in (CustomController, Conditional, Trigger, PID):
            row = model.query.filter_by(unique_id=fid).first()
            if row is not None:
                out.append({
                    'id': fid,
                    'name': getattr(row, 'name', None),
                    'active': bool(getattr(row, 'is_activated', False)),
                })
                break
    return out


def program_brief(plot, programs=None):
    """구획이 참조하는 재배 프로그램 요약 → dict (없으면 None).

    **구획이 고정해 둔 버전을 기준으로 읽는다.** 프로그램이 그 뒤에 바뀌었으면
    그 사실(`newer_version`)만 알리고, 해석은 고정 버전으로 한다 — 진행 중인
    작기의 근거가 저절로 바뀌면 "그때 무엇을 목표로 길렀나" 의 답이 달라진다.

    P1 은 **표시까지**다. 단계 판정(경과일/GDD)과 목표 적용은 이후 단계에서
    붙는다 — 여기서는 "무엇을 따르고 있는가" 만 말한다.

    `programs` 를 넘기면 캐시로 쓴다(목록 응답에서 구획마다 다시 읽지 않도록).
    """
    program_uuid = getattr(plot, 'program_uuid', None)
    if not program_uuid:
        return None

    if isinstance(programs, dict) and program_uuid in programs:
        row = programs[program_uuid]
    else:
        from aot.databases.models import GeoProgram
        row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
        if isinstance(programs, dict):
            programs[program_uuid] = row
    if row is None:
        # 프로그램이 지워졌다 — 조용히 없는 척하지 않는다. 화면이 "근거를
        # 잃었다" 고 말할 수 있어야 사람이 다시 고를 수 있다.
        return {'unique_id': program_uuid, 'missing': True}

    pinned = getattr(plot, 'program_version', None) or row.version or 1
    stages = row.stage_list()
    return {
        'unique_id': row.unique_id,
        'name': row.name,
        'subject': row.subject,
        'variety': row.variety,
        'source': row.source,
        'version': pinned,
        'latest_version': row.version or 1,
        'newer_version': (row.version or 1) > pinned,
        'stage_count': len(stages),
        'total_days': row.total_days(),
        'usable_for_control': row.usable_for_control(),
    }


def effective_stages(plot, program_row):
    """이 구획이 실제로 따르는 **단계 목록** → list.

    프로그램의 목록에서 뺀 것을 빼고, 더한 것을 자리에 끼우고, 지침을 덮는다
    (`GeoPlot.stage_overrides`). 목록을 복제하지 않고 **차이만** 얹으므로,
    손대지 않은 단계는 프로그램을 고치면 그대로 따라온다.

    ## 지침도 목표도 구획이 이긴다

    구획이 적는 지침은 "이 자리에서 이 시기에 무엇을 하나" 이고, 프로그램의
    지침은 그 작물의 일반 사항이다. 둘을 나란히 보이면 화면이 같은 자리에서 두
    가지를 말하게 되므로, **구획이 적었으면 그것이 이긴다**(적지 않았으면
    프로그램 것이 그대로 보인다).

    **목표(`targets`)도 같다**(2026-08-27 방향 전환). 예전에는 여기서 건드리지
    않았고 근거는 *"제어로 흐르는 값이라 구획마다 손대기 시작하면 무엇을
    목표로 길렀나 의 답이 흩어진다"* 였다. 걱정은 옳지만 답이 반대였다 —

      · 구획이 못 고치면 사람은 **프로그램을 고친다**. 그러면 그 프로그램을
        쓰는 **다른 구획까지** 함께 바뀐다. 흩어짐을 막으려던 규칙이 오히려
        남의 작기를 건드리게 만든다.
      · 프로그램은 **참고 계획**이고 실제 계획은 구획이다. "무엇을 목표로
        길렀나" 의 답도 그러므로 구획에 있어야 한다.

    ⚠ 이 함수가 **유일한 삽입점**이다. 여기서 얹으면 `_stage_targets` →
      `stage_of` → 화면·AI·제어가 전부 같은 값을 본다. 소비처마다 따로 얹으면
      갈라지고, 갈라지면 화면과 제어가 다른 목표를 말한다.
    """
    stages = program_row.stage_list() if program_row is not None else []
    if plot is None or not hasattr(plot, 'stage_override_map'):
        return list(stages)
    ov = plot.stage_override_map()
    if not (ov['removed'] or ov['added'] or ov['guidance'] or ov['targets']):
        return list(stages)

    out = []
    for st in stages:
        key = st.get('key')
        if key in ov['removed']:
            continue
        out.append(dict(st))

    # 더한 단계는 `after` 가 가리키는 칸 **뒤**에 끼운다. 가리킨 칸이 없으면
    # (프로그램이 그 사이 바뀌었다) 맨 뒤에 붙인다 — 조용히 버리지 않는다.
    for add in ov['added']:
        item = dict(add)
        after = item.pop('after', None)
        pos = None
        if after:
            for i, st in enumerate(out):
                if st.get('key') == after:
                    pos = i + 1
                    break
        if pos is None:
            pos = 0 if after == '' else len(out)
        out.insert(pos, item)

    for st in out:
        key = st.get('key')
        text = ov['guidance'].get(key)
        if text:
            st['guidance'] = text
        # 목표는 **항목 단위로** 덮는다. 단계의 dict 를 통째로 갈아치우면
        # 사람이 손대지 않은 항목까지 사라진다 — 프로그램이 정한 나머지는
        # 그대로 따라와야 한다.
        over = ov['targets'].get(key)
        if over:
            base = st.get('targets')
            merged = dict(base) if isinstance(base, dict) else {}
            merged.update(over)
            st['targets'] = merged
    return out


def stage_schedule(plot, program=None, on=None, plan=None, anchors=None,
                   programs=None):
    """구획의 **단계 경계** 한 벌 → dict|None. 정본: program-layer.md §P8

    ## 프로그램은 참고고, 경계는 구획이 갖는다

    단계 길이(`days`)는 표준이다. 현실은 표준대로 가지 않으므로 사람이 경계를
    직접 잡을 수 있고(`GeoPlot.stage_plan`), 그 날이 프로그램 길이를 이긴다.

        기준점(마지막 확정 전환, 없으면 시작일)에서 출발
        다음 단계 시작일 = 계획 경계가 있으면 그 날, 없으면 앞 경계 + days

    그래서 **명시한 경계는 고정되고 나머지는 밀린다.** 한 단계를 늘리면 뒤가
    통째로 밀리는 것이 기본이고, "이 단계만 늘리고 다음은 그대로" 는 다음 경계도
    함께 박으면 된다 — 같은 결과를 데이터로 표현할 수 있으면 모드 플래그를
    만들지 않는다.

    ## 왜 한 곳인가

    예전에는 `stage_of`·`timeline`·`expected_end`·`stage_proposal` 이 각자
    기준점 + `days` 를 다시 조립했고 **실제로 어긋나 있었다** — `timeline()` 은
    GDD 를 보지 않고 `stage_of` 는 봐서, 같은 모달 안에서 축이 가리키는 단계와
    "현재 단계" 줄이 서로 다른 근거로 계산됐다.

    반환:
      program_row  GeoProgram
      run          기준점 단계부터의 프로그램 단계 목록(원본 dict)
      base_index   기준점 단계의 0-based 위치(프로그램 전체 기준)
      anchored     원장에 확정 전환이 있는가
      planned      계획 경계가 하나라도 걸렸는가
      ref          판정 기준일(종료된 작기는 종료일)
      not_started  아직 시작 전인가
      boundaries   [{index, key, name, days, starts_on, ends_on, source}]
                   source = 'actual'(확정) | 'planned'(사람이 잡음) | 'program'
      end_on       마지막 날(열린 구간이면 None)
      open_end     마지막 단계에 길이가 없는가
    """
    from datetime import timedelta

    if plot is None or getattr(plot, 'started_on', None) is None:
        return None
    if program is None:
        program = program_brief(plot)
    if not program or program.get('missing'):
        return None

    from aot.databases.models import GeoProgram
    # `program_brief` 가 방금 읽은 것을 다시 읽지 않는다 — 같은 캐시를 쓴다.
    row = (programs or {}).get(program.get('unique_id'))
    if row is None:
        row = GeoProgram.query.filter_by(
            unique_id=program.get('unique_id')).first()
        if isinstance(programs, dict) and row is not None:
            programs[program.get('unique_id')] = row
    if row is None:
        return None
    stages = effective_stages(plot, row)
    if not stages:
        return None

    anchor = stage_anchor(plot, anchors=anchors)
    base_index = int((anchor or {}).get('stage_index') or 1) - 1
    # 프로그램이 짧아졌을 수 있다(단계를 지운 편집). 범위를 벗어난 기준점으로
    # 슬라이스하면 빈 목록이 되어 그 구획의 단계가 통째로 사라진다.
    base_index = max(0, min(base_index, len(stages) - 1))
    base_on = (anchor or {}).get('started_on') or plot.started_on
    run = stages[base_index:]

    # `plan` 을 주면 저장된 값 대신 그것으로 계산한다 — 저장 **전에** "이렇게
    # 되는가" 를 같은 규칙으로 검사하기 위한 자리다(계산을 한 벌 더 쓰지 않는다).
    if plan is None:
        plan = plot.stage_plan_map() if hasattr(plot, 'stage_plan_map') else {}

    bounds = []
    planned_used = False
    prev_start, prev_days = None, None
    for i, st in enumerate(run):
        key = st.get('key')
        try:
            days = st.get('days')
            days = None if days in (None, '') else int(days)
        except (TypeError, ValueError, AttributeError):
            days = None
        if days is not None and days <= 0:
            days = None
        if i == 0:
            # 기준점 단계의 시작일은 **계획이 손대지 못한다** — 확정된 사실이거나
            # 구획의 시작일이다. 고치고 싶으면 원장을 무르는 것이 그 수단이다.
            starts_on, source = base_on, ('actual' if anchor else 'program')
        elif key and key in plan:
            starts_on, source = plan[key], 'planned'
            planned_used = True
        elif prev_start is not None and prev_days:
            starts_on, source = prev_start + timedelta(days=prev_days), 'program'
        else:
            # 앞 단계가 "끝까지"(days 없음)라 다음 경계를 셀 수 없다. 지어내지
            # 않는다 — 날짜가 없는 칸으로 남기고 화면이 그렇게 말한다.
            starts_on, source = None, 'program'
        bounds.append({'index': base_index + i + 1, 'key': key,
                       'name': st.get('name') or key, 'days': days,
                       'guidance': st.get('guidance') or None,
                       'starts_on': starts_on, 'ends_on': None,
                       'source': source})
        prev_start, prev_days = starts_on, days

    for i, b in enumerate(bounds):
        nxt = bounds[i + 1] if i + 1 < len(bounds) else None
        if nxt is not None and nxt['starts_on'] is not None:
            b['ends_on'] = nxt['starts_on'] - timedelta(days=1)
        elif b['starts_on'] is not None and b['days']:
            b['ends_on'] = b['starts_on'] + timedelta(days=b['days'] - 1)

    ref = plot.ended_on or (on or date.today())
    last = bounds[-1]
    return {
        'program_row': row,
        'run': run,
        'base_index': base_index,
        'anchored': bool(anchor),
        'planned': planned_used,
        'ref': ref,
        'not_started': plot.started_on > ref,
        'boundaries': bounds,
        'end_on': last['ends_on'],
        'open_end': last['days'] is None,
    }


def _fill_ends(bounds):
    """경계 목록의 빈 `ends_on` 을 다음 칸의 시작에서 채운다 → 같은 목록.

    지난 칸은 원장이 시작일만 적으므로 끝이 비어 있다. 축과 표가 각자 채우면
    한쪽만 고쳐진다.
    """
    from datetime import timedelta

    for i, b in enumerate(bounds[:-1]):
        if b['ends_on'] is None and b['starts_on'] is not None:
            nxt = bounds[i + 1]['starts_on']
            if nxt is not None:
                b['ends_on'] = nxt - timedelta(days=1)
    return bounds


def _past_boundaries(plot, sched, events=None):
    """기준점 **앞**의 단계 → 목록.

    파생에는 쓰지 않는다(계산은 기준점부터다). 화면의 일정 표에만 붙인다 —
    3단계가 확인된 구획에서 앞의 두 줄이 통째로 사라지면, 그 표는 "이 작기가
    어떻게 흘러왔나" 를 답하지 못한다.

    ## 날짜는 원장이 아는 것 먼저, 없으면 프로그램으로 잇는다

    원장에는 **확인된 전환만** 있다. 자동 승인이 3단계를 한 번에 따라잡으면
    1·2단계에는 줄이 없어서, 원장만 보면 그 칸들이 영영 비어 있다 — 실제로
    화면이 "— " 다섯 줄을 보였다.

    그것은 모르는 값이 아니다. 확인된 전환이 나오기 전까지는 **시작일에서
    프로그램 길이로 이어 온 그 날짜**가 그 구획이 따르던 일정이었다. 그래서
    시작일에서부터 걸어 내려오며 원장이 아는 칸에서만 갈아탄다.
    """
    from datetime import timedelta

    base_index = sched['base_index']
    if base_index <= 0:
        return []
    full = effective_stages(plot, sched['program_row'])

    seen = {}
    for h in stage_history(plot, events=events):
        if h.get('undone') or not h.get('started_on'):
            continue
        seen[h['stage_key']] = _as_date(h['started_on'])

    # **기준점을 넘어설 수 없다.** 프로그램 길이로 걸어 내려온 날짜가 확인된
    # 전환보다 뒤에 서면 축이 뒤엉킨다 — 성숙이 9/4 에 시작하는데 수확은 8/19 에
    # 확인돼 있으면 칸 폭이 음수가 되고, "오늘" 마커는 앞 칸에 찍히는데 현재
    # 단계는 뒤 칸으로 표시된다(실제로 그렇게 보였다).
    #
    # 그때는 그 칸들을 기준점에 붙여 **폭 0** 으로 둔다. 확인된 사실이 이기고,
    # "여기서 한 번에 건너뛰었다" 가 축에 그대로 보인다 — 지어낸 날짜로 사이를
    # 메우면 언제 무엇을 했는지가 거짓이 된다.
    b0 = (sched['boundaries'] or [None])[0]
    limit = (b0 or {}).get('starts_on')

    out = []
    cur = getattr(plot, 'started_on', None)
    for i, st in enumerate(full[:base_index]):
        key = st.get('key')
        if key in seen and seen[key] is not None:
            cur, source = seen[key], 'actual'
        else:
            source = 'program'
        if limit is not None and cur is not None and cur > limit:
            cur = limit
        try:
            days = st.get('days')
            days = None if days in (None, '') else int(days)
        except (TypeError, ValueError, AttributeError):
            days = None
        out.append({'index': i + 1, 'key': key,
                    'name': st.get('name') or key,
                    'days': days,
                    'guidance': st.get('guidance') or None,
                    'starts_on': cur,
                    'ends_on': None,
                    'source': source})
        # 다음 칸의 자리. 길이를 모르면(끝까지) 더 셀 수 없다 — 지어내지 않는다.
        cur = (cur + timedelta(days=days)) if (cur and days) else None
    return out


def _as_date(iso):
    """'YYYY-MM-DD' → date|None. 깨진 값은 없는 값으로 본다."""
    if not iso:
        return None
    try:
        y, m, d = (int(x) for x in str(iso).split('-')[:3])
        return date(y, m, d)
    except (TypeError, ValueError):
        return None


def _view_targets(stage, program_row):
    """단계 하나의 목표 → 화면이 **고칠 수 있는** 목록.

    `_stage_targets` 가 낸 것에서 편집에 필요한 것만 남긴다.

    ⚠ **못 고치는 것은 곡선이 걸린 항목뿐이다.** 숫자를 받아도 곡선이 이기므로,
      고칠 수 있는 것처럼 보이면 사람이 값을 넣고 왜 안 먹는지 묻게 된다.

    ⚠ **`fixed` 로 판정하지 말 것.** 그것은 "이 **정의**가 시스템 소유" 라는
      뜻이지(라벨·단위·범위) 값을 못 고친다는 뜻이 아니다 —
      `program_io._merge_target_defs` 가 *"라벨·단위·범위는 시스템 소유지만
      기본 목표값은 사람의 것"* 이라고 적어 두고 있다. 온도·습도·CO₂·DLI·VPD
      가 전부 `fixed` 정의라, 그것으로 막으면 **고칠 수 있는 항목이 하나도
      남지 않는다**(2026-08-27 실측: 다섯 항목 전부 읽기 전용이었다).
    """
    if not stage:
        return []
    out = []
    for t in _stage_targets(stage, program_row):
        out.append({
            'key': t.get('key'),
            'label': t.get('label'),
            'unit': t.get('unit'),
            'value': t.get('value'),
            'source': t.get('source'),
            'method_name': t.get('method_name'),
            # 곡선이 걸린 항목만 못 고친다(위 주석 참조).
            'editable': t.get('source') != 'method',
        })
    return out


def stage_schedule_view(plot, program=None, on=None, sched=None, events=None,
                        stage=None):
    """화면·AI 가 그대로 읽는 일정 → list. 없으면 `[]`.

    `[{index, key, name, days, starts_on, ends_on, source, state}]`

    `state` 는 `'done'` | `'current'` | `'future'`. **고칠 수 있는 것은 아직 오지
    않은 경계뿐**이라 화면이 그것을 알아야 한다 — 지나간 경계를 옮기는 일은
    원장(확인·되돌리기)이 하는 일이고, 두 수단이 같은 값을 다투면 무엇이 정본
    인지 알 수 없다.
    """
    if sched is None:
        sched = stage_schedule(plot, program=program, on=on)
    if sched is None:
        return []
    ref = sched['ref']
    bounds = _fill_ends(list(_past_boundaries(plot, sched, events=events))
                        + list(sched['boundaries']))

    # **현재 칸은 `stage_of` 가 정한다.** 날짜만으로 고르면 승인 대기로 고정된
    # 구획에서 표의 '지금' 과 "현재 단계" 줄이 서로 다른 칸을 가리킨다(P8 게이팅).
    if stage is None:
        stage = stage_of(plot, program=program, on=on, sched=sched)
    cur = None
    if stage and stage.get('state') == 'running' and stage.get('index'):
        for i, b in enumerate(bounds):
            if b['index'] == stage['index']:
                cur = i
                break
    elif stage and stage.get('state') == 'past_end':
        cur = len(bounds) - 1
    if sched['not_started']:
        cur = None

    # 지나간 경계는 고칠 수 없다 — 그것은 원장(확인·되돌리기)이 다루는 사실이다.
    first_editable = len(bounds) - len(sched['boundaries'])

    # 목표는 경계(`bounds`)가 아니라 **단계 정의**에 있다. 경계는 날짜만 담는다.
    program_row = sched.get('program_row')
    full_by_key = {st.get('key'): st
                   for st in effective_stages(plot, program_row)}

    out = []
    for i, b in enumerate(bounds):
        if cur is None:
            state = 'future'
        elif i < cur:
            state = 'done'
        elif i == cur:
            state = 'current'
        else:
            state = 'future'
        nxt = bounds[i + 1] if i + 1 < len(bounds) else None
        # **실제 기간**은 경계 사이의 날수다. 프로그램이 적은 길이와 다를 수 있고
        # (사람이 고쳤다), 화면이 고치는 값도 이쪽이다. 마지막 칸과 셀 수 없는
        # 칸은 없는 값으로 둔다 — 0 으로 두면 "0일짜리 단계" 로 읽힌다.
        length = None
        if (nxt is not None and nxt['starts_on'] is not None
                and b['starts_on'] is not None):
            length = (nxt['starts_on'] - b['starts_on']).days
        elif nxt is None:
            length = None
        else:
            length = b['days']
        out.append({
            'index': b['index'],
            'key': b['key'],
            'name': b['name'],
            # 실제 기간(일). 화면·AI 가 고치는 값이다.
            'days': length,
            # 프로그램이 적은 길이 — "표준과 얼마나 다른가" 를 말할 수 있게 함께.
            'program_days': b['days'],
            'starts_on': b['starts_on'].isoformat() if b['starts_on'] else None,
            'ends_on': b['ends_on'].isoformat() if b['ends_on'] else None,
            'source': b['source'],
            'state': state,
            # 이 시기에 무엇을 하나. 구획이 적었으면 그것이, 아니면 프로그램의
            # 것이 온다(`effective_stages`).
            'guidance': b.get('guidance'),
            # 마지막 칸은 다음 경계가 없어 기간을 정할 수 없다(끝내는 날은
            # 재배 종료가 정한다).
            'editable': i >= first_editable and nxt is not None,
            # 지나간 단계는 뺄 수 없다 — 확인된 전환이 그것을 가리킨다.
            # 지침은 지나간 단계에도 적을 수 있다(관찰의 기록이다).
            'removable': i >= first_editable and len(bounds) > 1,
            # 이 단계의 **목표**. 구획이 정했으면 그것이, 아니면 프로그램의
            # 것이 온다(`effective_stages`) — 지침과 같은 규칙이다.
            #
            # ⚠ **`_stage_targets` 를 재사용한다.** 항목 어휘·단위·곡선 처리가
            #   거기 못 박혀 있어, 화면용으로 다시 조립하면 항목을 늘릴 때 한쪽만
            #   늘어난다(그 함수 주석의 경고 그대로).
            'targets': _view_targets(full_by_key.get(b['key']), program_row),
        })
    return out


def stage_of(plot, program=None, on=None, with_observability=False,
             gated=True, sched=None):
    """구획의 **현재 단계** → dict (판정 불가면 None).

    ## 계산

    경계는 `stage_schedule` 이 만든다(기준점 + 계획 경계 + 프로그램 길이).
    여기서는 그 경계 중 기준일이 들어 있는 칸을 고른다.

    ## `gated` — 승인 전에는 넘어가지 않는다 (P8)

    기준점이 있는 구획에서 파생이 기준점보다 앞서가면 **기준점의 단계를
    유지**하고 앞서간 사실을 `pending` 으로 얹는다. 제어가 이 값을 읽으므로
    (`coordinator_plot`), 이것이 없으면 화면이 "확인하시겠습니까" 를 묻는 동안
    목표 온도는 이미 다음 단계 값으로 바뀌어 있다 — 그 상태의 승인 버튼은
    무엇을 승인하는 것인지 말할 수 없다.

    끄는 자리는 **제안을 만드는 곳뿐**이다(`stage_proposal`). 제안은 "앞서갔다"
    는 사실 자체라 고정된 값을 보면 영영 뜨지 않는다.

    ## `with_observability`

    켜면 단계 목표마다 "이 구획이 그것을 재는 센서를 갖고 있는가" 를 얹는다
    (`_mark_observable`). **기본은 꺼짐이다** — 구획마다 센서 조회가 한 번씩
    더 붙으므로 목록 화면에서 켜면 N+1 이 된다. 구획 하나를 여는 화면에서만 켠다.

    ## 지어내지 않는 경우

    - 프로그램이 없거나 단계가 비었으면 `None`.
    - **파종일이 미래**면 `not_started` — 계획만 세운 구획을 "육묘기" 라고 부르면
      아직 심지도 않은 것을 기르는 중으로 읽는다.
    - 마지막 단계에 길이가 있고 그마저 지났으면 `past_end` — "수확기" 로 눌러
      두면 프로그램이 끝난 사실이 사라진다.

    ## `source` 는 무엇으로 판정했는지 말한다

    `'days'` | `'gdd'`. 화면이 근거를 말할 수 있어야 사람이 그 값을 믿는다
    (측정값의 `source` 와 같은 태도).
    """
    # `sched` 를 받으면 다시 만들지 않는다 — 한 구획을 그리는 데 `stage_of` ·
    # `timeline` · `expected_end` · `stage_proposal` 이 모두 같은 일정을 쓰므로,
    # 각자 만들면 목록 화면 한 장에서 구획마다 네 벌씩 조회가 돈다.
    if sched is None:
        sched = stage_schedule(plot, program=program, on=on)
    if sched is None:
        return None

    row = sched['program_row']
    run = sched['run']
    base_index = sched['base_index']
    total = base_index + len(run)

    if sched['not_started']:
        return {'state': 'not_started', 'source': 'days', 'total': total,
                'days_until_start': (plot.started_on - sched['ref']).days}

    # ── GDD 로 판정할 수 있으면 그쪽이 이긴다 ──────────────────────────
    #
    # 날짜로만 넘기면 서늘한 봄과 더운 여름이 같은 날 넘어간다. 다만 **셋이 모두
    # 갖춰졌을 때만** 쓴다(기준온도 · 단계 목표 · 자료 커버리지) — 하나라도
    # 없으면 날짜로 되돌아가고, 되돌아간 **이유를 함께 싣는다**. 이유 없이
    # 되돌아가면 "왜 GDD 가 안 잡히지" 를 알 방법이 없다.
    #
    # **계획 경계가 하나라도 있으면 GDD 를 쓰지 않는다**(P8). 사람이 날짜를
    # 잡았는데 적산온도가 그것을 앞질러 가면 그 편집이 무의미해진다
    # (선언 > 계획 > GDD > 경과일). 계획을 전부 지우면 GDD 로 돌아온다.
    out = None
    gdd = None
    if not sched['planned'] and any(st.get('gdd') is not None for st in run):
        gdd = gdd_accumulated(plot, row, on=on, with_series=True)
        if gdd.get('usable'):
            out = _stage_by_gdd(run, gdd, row, base_index, plot)

    if out is None:
        out = _stage_by_dates(sched, row, plot)
    if out is None:
        return None
    if gdd is not None:
        out['gdd'] = {k: v for k, v in gdd.items() if k != 'series'}

    out = _hold_at_anchor(out, sched, row, plot, gated)
    if with_observability and out.get('state') == 'running':
        _mark_observable(out, plot)
    return out


def _stage_by_dates(sched, program_row, plot):
    """경계 목록에서 기준일이 들어 있는 칸을 고른다 → 단계 payload."""
    ref = sched['ref']
    bounds = sched['boundaries']
    run = sched['run']
    base_index = sched['base_index']

    idx = 0
    for i, b in enumerate(bounds):
        if b['starts_on'] is None:
            break                     # 셀 수 없는 구간 — 여기서 멈춘다
        if b['starts_on'] <= ref:
            idx = i
        else:
            break

    b = bounds[idx]
    ends_on = b['ends_on']
    if ends_on is not None and ref > ends_on:
        # 마지막 단계에 길이가 있고 그마저 지났다(중간 단계는 다음 경계가
        # 잡아 주므로 여기 오지 않는다).
        return {'state': 'past_end', 'source': 'days',
                'total': base_index + len(run),
                'days_past': (ref - ends_on).days}

    start = b['starts_on']
    day_in_stage = None if start is None else (ref - start).days + 1
    days_left = None if ends_on is None else (ends_on - ref).days
    return _stage_payload(run[idx], idx, run, day_in_stage, days_left,
                          program_row, base_index, plot)


def _hold_at_anchor(out, sched, program_row, plot, gated=True):
    """승인 전에는 단계가 넘어가지 않는다 (P8) → 고정된 payload.

    **예외 둘 — 둘 다 "사람이 이미 결정했다" 는 자리다.**

    - `auto_advance` 가 켜진 구획: "확인 없이 넘어가도 된다" 는 결정이 이미 있다.
      고정하면 그 구획의 목표가 **아무도 상세 화면을 열지 않는 동안 멈춘다**
      (원장 기록은 읽을 때 따라잡지만 제어는 매 사이클 돈다).
    - 원장이 빈 구획: 승인은 한 번 누른 시점부터 의미를 갖는다(§P5). 이 예외가
      없으면 업그레이드가 기존 구획 **전부**의 단계를 첫 단계로 얼린다.
    """
    if not gated or out.get('state') != 'running':
        return out
    if not sched['anchored'] or getattr(plot, 'auto_advance', False):
        return out
    base_index = sched['base_index']
    if (out.get('index') or 1) <= base_index + 1:
        return out

    b0 = sched['boundaries'][0]
    ref = sched['ref']
    start = b0['starts_on']
    held = _stage_payload(
        sched['run'][0], 0, sched['run'],
        None if start is None else (ref - start).days + 1, 0,
        program_row, base_index, plot)
    # 앞서간 사실은 없애지 않는다 — 화면이 "예정보다 N일" 을 말할 수 있어야
    # 사람이 확인할지 연기할지 정한다.
    held['overdue_days'] = (max(0, (ref - b0['ends_on']).days)
                            if b0['ends_on'] else 0)
    held['pending'] = {'stage_key': out.get('key'),
                       'stage_index': out.get('index'),
                       'stage_name': out.get('name'),
                       'source': out.get('source')}
    if out.get('gdd') is not None:
        held['gdd'] = out['gdd']
    return held


def measurable_in_plot(plot):
    """이 구획이 실제로 재는 measurement 이름 집합 → set.

    구획이 참조하는 센서(`sensors_for_plot` — 구획 안이 1순위, 없으면 zone 폴백)의
    `DeviceMeasurements.measurement` 를 모은다. 목표 항목의 `measurement` 와 같은
    어휘이므로 그대로 대조할 수 있다.

    ## 왜 필요한가

    **실제 시설이 모든 항목을 재지 못하는 것은 당연하다.** 노지 상추에 CO₂ 센서가
    없는 것이 정상인데, 화면이 CO₂ 목표 칸을 그냥 비워 두면 사용자는 자기가 아직
    안 채운 것으로 읽는다. "이 구획엔 그 센서가 없습니다" 라고 말할 수 있어야
    빈칸이 압박이 아니라 정보가 된다.

    비어 있는 집합은 "못 잰다" 가 아니라 **"모른다"** 로 다뤄야 한다(센서를 아직
    안 이었을 수도, 조회가 실패했을 수도 있다) — 호출부가 그렇게 구분한다.
    """
    from aot.databases.models import DeviceMeasurements

    try:
        found = sensors_for_plot(plot) or {}
    except Exception:
        return set()
    # sensors_for_plot 의 우선순위(구역 → 시설 → zone, 좁은 쪽이 이긴다)와
    # 같아야 한다 — 시설 구획은 `in_plot` 이 항상 비어 있어 `in_bay`/
    # `from_facility` 를 보지 않으면 무조건 zone 폴백으로 떨어진다.
    ids = (list(found.get('in_plot') or [])
           or list(found.get('in_bay') or [])
           or list(found.get('from_facility') or [])
           or list(found.get('from_zone') or []))
    if not ids:
        return set()
    try:
        rows = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id.in_(ids)).all()
    except Exception:
        return set()
    return {m.measurement for m in rows if m.measurement}


def _mark_observable(out, plot):
    """단계 목표에 `observable` 을 얹는다(제자리 수정) → out.

    `True` 재는 센서가 있다 · `False` 없다 · `None` 알 수 없다(센서를 하나도 못
    찾았거나 항목에 `measurement` 가 없다 — 사용자가 만든 항목이 그렇다).

    **없다고 값을 지우거나 감추지 않는다.** 프로그램은 시설과 독립이어야 다른 곳에
    재사용된다(`coordinator-plot-targets.md` 의 분담) — 여기서 하는 일은 화면이
    사실을 말할 수 있게 근거를 붙이는 것뿐이다.
    """
    targets = (out or {}).get('targets') or []
    if not targets:
        return out
    have = measurable_in_plot(plot)
    for t in targets:
        m = t.get('measurement')
        if not m or not have:
            t['observable'] = None
        else:
            t['observable'] = m in have
    return out


def _stage_by_gdd(stages, gdd, program_row, base_index=0, plot=None):
    """누적 GDD 를 단계 목표에 대어 현재 단계를 찾는다 (판정 불가면 None).

    단계의 `gdd` 는 **그 단계의 길이**다(`days` 와 같은 규약) — 누적값이 아니다.
    두 뜻이 섞이면 마지막 단계만 맞고 나머지가 다 어긋나는데, 화면에서는 그냥
    "단계가 이상하다" 로만 보인다.

    `gdd` 가 없는 단계가 섞여 있으면 **판정하지 않는다**(None). 그 단계를 0 으로
    치면 건너뛰어지고, 날짜로 메우면 두 기준이 한 프로그램 안에서 섞인다.
    """
    total = gdd.get('value')
    if total is None:
        return None

    lengths = []
    for st in stages:
        raw = st.get('gdd')
        if raw is None:
            if st is stages[-1]:
                lengths.append(None)           # 마지막 "끝까지" 는 허용
                continue
            return None
        try:
            lengths.append(float(raw))
        except (TypeError, ValueError):
            return None

    cursor = 0.0
    for idx, (st, length) in enumerate(zip(stages, lengths)):
        if length is None:
            out = _gdd_payload(st, idx, stages, total - cursor, None,
                               program_row, base_index, plot)
            out['started_on'] = _gdd_crossed_on(gdd, cursor)
            return out
        if total <= cursor + length:
            out = _gdd_payload(st, idx, stages, total - cursor,
                               cursor + length - total, program_row,
                               base_index, plot)
            # **이 단계가 시작된 날.** 자동 승인(P7)이 기록할 날짜라 "오늘" 로
            # 두면 안 된다 — 아무도 안 본 사이에 넘어갔으면 기록이 관찰 시점에
            # 따라 달라진다. 누적이 앞 단계의 합을 넘어선 날을 되짚는다.
            out['started_on'] = _gdd_crossed_on(gdd, cursor)
            return out
        cursor += length

    return {'state': 'past_end', 'source': 'gdd',
            'total': len(stages) + base_index,
            'gdd_past': round(total - cursor, 1)}



def _gdd_crossed_on(gdd, threshold):
    """누적 GDD 가 `threshold` 를 넘어선 **다음 날** → ISO 문자열|None.

    그 날부터 새 단계다(임계를 넘긴 날은 아직 앞 단계의 마지막 날이다).
    계열이 없으면 None — 지어내지 않는다(사람이 화면에서 고른다).
    """
    from datetime import timedelta

    series = gdd.get('series')
    if not series:
        return None
    acc = 0.0
    for day, gain in series:
        acc += gain
        if acc > threshold:
            return (day + timedelta(days=1)).isoformat()
    return None


def _gdd_payload(st, idx, stages, gdd_in_stage, gdd_left, program_row,
                 base_index=0, plot=None):
    """GDD 판정 결과. 날짜 판정과 **키를 맞춘다** — 화면이 두 모양을 알게 되면
    한쪽만 고쳐진다. 다른 것은 `source` 와 단위뿐이다."""
    out = _stage_payload(st, idx, stages, None, None, program_row,
                         base_index, plot)
    out['source'] = 'gdd'
    out['gdd_in_stage'] = round(gdd_in_stage, 1)
    out['gdd_left'] = None if gdd_left is None else round(gdd_left, 1)
    return out


def _stage_payload(st, idx, stages, day_in_stage, days_left,
                   program_row=None, base_index=0, plot=None):
    nxt = stages[idx + 1] if idx + 1 < len(stages) else None
    return {
        'state': 'running',
        'source': 'days',
        'key': st.get('key'),
        'name': st.get('name') or st.get('key'),
        # 1-based, **전체 기준**. 기준점(P5) 이후 구간으로 잘라 계산해도 화면에
        # 나가는 순번은 프로그램 전체를 기준으로 해야 한다 — 잘린 기준으로
        # 내보내면 2단계가 확인된 구획에서 "정식 (1/5)" 처럼 보인다.
        'index': idx + 1 + base_index,
        'total': len(stages) + base_index,
        'day_in_stage': day_in_stage,
        'days_left': days_left,                # None = 끝까지
        'next_key': (nxt or {}).get('key'),
        'next_name': (nxt or {}).get('name') if nxt else None,
        'targets': _stage_targets(st, program_row),
        # 이 단계의 지침(자유 텍스트). AI 가 그대로 인용하고, AI 를 안 쓰는
        # 사용자는 구획 모달에서 읽는다 — 프로그램을 고른 것만으로 그 시기의
        # 일반사항을 얻는 것이 이 필드의 값어치다.
        'guidance': st.get('guidance') or None,
        # 자원(P6) — 선언(역할)과 현장(찾은 함수)을 나란히. 프로그램은 함수를
        # 가리키지 않고, 켜고 끄지도 않는다.
        'resources': stage_resources(st, program_row, plot),
    }


def _stage_targets(stage, program_row=None):
    """이 단계의 목표 → 화면이 그대로 그리는 목록(없으면 []).

    ## 왜 서버가 만드는가

    항목 어휘(`_TARGET_FIELDS`)와 단위가 서버에 못 박혀 있다. 화면이 다시
    조립하면 항목을 늘릴 때 한쪽만 늘어난다 — 이 저장소가 반복해서 겪은 실패다.

    ## 곡선이 있는 항목은 **숫자를 내지 않는다**

    `targets_methods` 에 곡선이 걸린 항목은 단계 값이 아니라 곡선을 따른다.
    그런데 곡선의 "지금 값" 은 메서드 종류마다 계산 방식이 달라(`calculate_setpoint`
    의 인자가 종류마다 다르다) 여기서 일반적으로 구할 수 없다. 그래서 단계 값을
    대신 보이지 **않는다** — 그러면 화면이 실제로 쓰이지 않는 숫자를 목표라고
    말하게 된다. 곡선 이름만 내고 값은 비운다.

    (곡선의 현재 값을 내는 것은 제어 연결과 같은 계산을 필요로 하므로 그때 함께
    한다. 그 전까지 이 화면은 "곡선을 따름" 까지만 말한다.)

    ## 표시 전용이다

    이 값은 아직 어떤 제어도 바꾸지 않는다(`targets_note` 가 화면에서 같은 말을
    한다). 여기서 조용히 제어로 흘리지 말 것 — `source='ai'` 인 프로그램의 지어낸
    숫자가 곧바로 온실 설정이 되는 것을 막는 검토 게이트가 무의미해진다.
    """
    from aot.aot_flask.geo.program_io import _public_target_def

    defs = (program_row.target_def_list()
            if program_row is not None and hasattr(program_row, 'target_def_list')
            else [])
    targets = stage.get('targets') if isinstance(stage, dict) else None
    curves = getattr(program_row, 'targets_methods', None) or {}
    if not isinstance(curves, dict):
        curves = {}
    has_default = any(d.get('default') is not None for d in defs)
    if not targets and not curves and not has_default:
        return []

    names = {}
    if curves:
        try:
            from aot.databases.models import Method
            rows = Method.query.filter(
                Method.unique_id.in_(list(curves.values()))).all()
            names = {m.unique_id: m.name for m in rows}
        except Exception:
            names = {}

    out = []
    for spec in defs:                          # 정의 순서를 따른다(화면 순서)
        # 숨긴 항목은 내지 않는다 — 사람이 "이 시설엔 없다" 고 이미 말한 것이다.
        if spec.get('hidden'):
            continue
        key = spec.get('key')
        pub = _public_target_def(spec)
        base = {'key': key, 'label': pub.get('label'),
                'unit': spec.get('unit'), 'measurement': spec.get('measurement'),
                'shape': spec.get('shape'), 'fixed': bool(spec.get('fixed')),
                # 'day'/'night' — 이 목표가 낮에만/밤에만 적용되는가. 빠져 있으면
                # 읽는 쪽이 야간 목표를 한낮 실측과 견주게 된다(실측 2026-08-26:
                # 야간 12도 목표 대 한낮 35.6도 → 23.6도 차이라는 허위 경보).
                'when': spec.get('when')}
        curve_uuid = curves.get(key)
        if curve_uuid:
            out.append(dict(base, value=None, source='method',
                            method_uuid=curve_uuid,
                            # 죽은 참조는 저장 때 거절되지만, 나중에 지워질 수는
                            # 있다 — 그때 이름 없이 "곡선" 으로만 보인다.
                            method_name=names.get(curve_uuid)))
            continue
        if isinstance(targets, dict) and targets.get(key) is not None:
            out.append(dict(base, value=targets[key], source='stage'))
            continue
        # 단계에 값이 없으면 **프로그램 기본값**이 그 단계의 목표다.
        #
        # 목표는 대개 작기 내내 같고 단계마다 달라지는 것은 그중 일부다. 기본값이
        # 없으면 바뀌지 않는 값도 단계 수만큼 다시 적어야 하고, 실제로 만들어 보면
        # 거기서 그만두게 된다. `source` 로 어느 쪽에서 왔는지 밝힌다 — 화면이
        # "이 단계에서 따로 정한 값" 과 "프로그램 기본값" 을 구분해 말할 수 있어야
        # 사람이 무엇을 고치면 되는지 안다.
        if spec.get('default') is not None:
            out.append(dict(base, value=spec['default'], source='default'))
    return out


def expected_end(plot, program=None, sched=None, programs=None, anchors=None):
    """예상 종료일 → `(date, source)`. 없으면 `(None, None)`.

    **사람이 적은 값이 이긴다.** 프로그램의 기간은 표준이고, 현장에서 그것과
    다르게 잡는 것은 정상이다 — 사람 입력을 덮으면 다음에 열었을 때 자기가 적은
    날짜가 사라진 것을 보게 된다.

    사람 값이 없을 때만 `started_on + 총 기간 − 1` 로 파생한다(심은 날이 1일차라
    −1 이다 — `elapsed_days` 와 같은 기준이어야 "140일 프로그램" 의 마지막 날이
    140일차가 된다).

    ⚠ **파생값을 컬럼에 써 넣지 않는다.** 저장하면 프로그램을 바꿔도 옛 날짜가
    남고, 그 값이 사람이 적은 것인지 계산된 것인지 구분할 수 없게 된다.
    """
    if plot.expected_end_on is not None:
        return plot.expected_end_on, 'manual'
    if plot.started_on is None:
        return None, None
    if program is None:
        program = program_brief(plot, programs=programs)
    if not program or program.get('missing'):
        return None, None
    # 일정(§P8)이 있으면 그것이 답이다 — 확인된 전환과 사람이 잡은 경계가
    # 이미 반영된 마지막 날이다. 시작일 + 총 기간으로 다시 세면 승인·연기가
    # 예상 종료일에 닿지 않아, 2주 미룬 구획이 여전히 옛 날짜로 끝난다고 말한다.
    if sched is None:
        sched = stage_schedule(plot, program=program, anchors=anchors,
                               programs=programs)
    if sched is not None and sched.get('end_on') is not None:
        return sched['end_on'], 'program'

    total = program.get('total_days') or 0
    if total <= 0:
        return None, None
    from datetime import timedelta
    return plot.started_on + timedelta(days=total - 1), 'program'


def facility_control_for_plot(plot):
    """시설 구획을 담당하는 제어 → `{facility, bay, coordinators, actuators, source}`.

    노지 구획은 `valves_for_plot()` 이 지도 도형(`type='device'` 폴리곤)과의
    면적 교차로 밸브를 찾는다. 시설 안에서는 그 방법이 통하지 않는다 — 창호·팬·
    난방기는 지도 도형이 아니라 `facility.fittings[]` 에 로컬 좌표로 붙어 있고,
    환경 제어는 밸브 하나가 아니라 **코디네이터**(env_coordinator)가 한다.

    ## 읽기 전용이다. 여기서 제어를 걸지 않는다

    재료(누가 이 구역을 맡고 있는가)만 내고 판단은 사람이 한다 — 관수량을
    계산하지 않는 것(Phase 3)과 같은 결이다. 구획은 3개월 뒤 사라지는 대상이라
    제어의 주체가 될 수 없다.

    ## 코디네이터를 고르는 규칙

    `bay_scope` 가 구획의 `bay_id` 와 같으면 그 구역 전담이고, 비어 있으면 시설
    전체를 맡는다(그 구역도 포함된다). **둘 다 돌려준다** — 구역 전담이 있어도
    시설 전체 코디네이터가 함께 도는 구성이 정상이고, 한쪽만 보이면 사람은
    "왜 내 설정이 안 먹지" 를 설명할 근거를 잃는다. 어느 쪽인지는 `scope` 로
    구분한다.

    `source` 는 `'bay' | 'facility' | 'none'` — 이 구획을 **가장 좁게** 맡는
    단위가 무엇인가(센서 쪽 `sensors_for_plot` 과 같은 어휘).
    """
    import json as _json

    facility_uuid = getattr(plot, 'facility_uuid', None)
    bay_id = getattr(plot, 'bay_id', None)
    out = {'facility': None, 'bay': None, 'coordinators': [], 'actuators': [],
           'source': 'none'}
    if not facility_uuid:
        return out

    from aot.databases.models import CustomController

    brief = facility_brief(facility_uuid)
    if not brief:
        return out
    out['facility'] = {'unique_id': facility_uuid, 'name': brief.get('name')}
    if bay_id:
        out['bay'] = {'id': bay_id,
                      'name': (brief.get('bay_names') or {}).get(bay_id)}

    # ── 코디네이터 ────────────────────────────────────────────────────
    for c in CustomController.query.filter_by(device='env_coordinator').all():
        try:
            opts = _json.loads(c.custom_options) if c.custom_options else {}
        except (ValueError, TypeError):
            opts = {}
        if opts.get('geo_facility_id') != facility_uuid:
            continue
        scope_bay = (opts.get('bay_scope') or '').strip() or None
        if scope_bay and bay_id and scope_bay != bay_id:
            continue
        if scope_bay and not bay_id:
            # 구획이 시설 전체인데 코디네이터는 한 구역만 맡는다 — 이 구획을
            # 대표해서 맡는다고 말할 수 없다.
            continue
        out['coordinators'].append({
            'function_id': c.unique_id,
            'name': c.name,
            'is_activated': bool(c.is_activated),
            'scope': 'bay' if scope_bay else 'facility',
            'bay_id': scope_bay,
        })

    # ── 액추에이터 ────────────────────────────────────────────────────
    # 구역 귀속은 기하 교차가 아니라 로컬 x 좌표 → 슬라이스 매핑이다
    # (`facility_sensor_ids` 와 같은 방식).
    from .facility_bays import build_fitting_bay_map, compute_bay_slices
    from .facility_io import FacilityManager

    fac, err = FacilityManager.get_facility(facility_uuid)
    if not err and fac:
        fittings = [f for f in (fac.get('fittings') or [])
                    if f.get('kind') != 'sensor' and f.get('actuator_id')]
        fitting_bay = ({} if not bay_id
                       else build_fitting_bay_map(compute_bay_slices(fac), fittings))
        for f in fittings:
            in_bay = (fitting_bay.get(f.get('id')) == bay_id) if bay_id else False
            if bay_id and not in_bay:
                # 구역 밖 설비도 시설 공통(난방기 등)일 수 있어 버리지 않는다.
                # 어느 쪽인지는 `scope` 가 말한다.
                pass
            out['actuators'].append({
                'fitting_id': f.get('id'),
                'name': f.get('name') or f.get('kind'),
                'kind': f.get('kind'),
                'output_id': f.get('actuator_id'),
                'scope': 'bay' if in_bay else 'facility',
            })

    if any(c['scope'] == 'bay' for c in out['coordinators']) or \
            any(a['scope'] == 'bay' for a in out['actuators']):
        out['source'] = 'bay'
    elif out['coordinators'] or out['actuators']:
        out['source'] = 'facility'
    return out


def plots_in_facility(facility_uuid, bay_id=None, on=None,
                      include_planned=False):
    """시설(또는 그 구역)에서 지금 자라는 구획들 — **제어 → 식생** 방향.

    코디네이터·구역 모달이 "지금 이 동에 무엇이 며칠째" 를 말할 수 있어야
    설정값의 근거가 생긴다. 이것이 없으면 식생은 기록일 뿐 제어와 만나지 않는다.

    `bay_id` 를 주면 그 구역 것만. 다만 **구역이 지정되지 않은 구획**(시설 전체에
    심은 것)도 함께 낸다 — 그 작물도 이 구역에서 자라고 있기 때문이다.

    ## `include_planned` 는 **화면 전용**이다

    시작일이 아직 오지 않은 구획(계획)은 기본으로 빠진다. 이 함수의 주 소비처가
    **제어**이기 때문이다 — 코디네이터가 아직 심지도 않은 작물의 목표를 따르면
    빈 온실을 그 작물 기준으로 덥히고 적신다. 목록을 보여 주는 자리
    (`_facility_plots_block`)만 켠다.
    """
    from aot.databases.models import GeoPlot

    if not facility_uuid:
        return []
    on = on or date.today()
    q = GeoPlot.query.filter(GeoPlot.facility_uuid == facility_uuid)
    if not include_planned:
        q = q.filter(GeoPlot.started_on <= on)
    rows = q.filter(
        (GeoPlot.ended_on.is_(None)) | (GeoPlot.ended_on > on)
    ).all()
    if bay_id:
        rows = [r for r in rows if r.bay_id in (bay_id, None)]
    return rows


def plot_for_coordinator(fn, on=None):
    """이 코디네이터가 따르는 **기준 구획** → dict. 정본은 여기 하나뿐이다.

    코디네이터(데몬)와 화면이 같은 함수를 부른다. 규칙을 화면에 다시 쓰면
    "읽는 경로마다 기준이 다름" 이 되고, 이 저장소는 그 실패를 이미 여러 번
    겪었다. 정본 설계: `docs/design/coordinator-plot-targets.md`.

    ## 규칙 (R0~R5)

    - **R0** 스코프는 코디네이터 옵션의 `geo_facility_id` + `bay_scope`.
    - **R1** 후보는 `plots_in_facility(facility, bay)` — 활성 판정(부등호)을
      그쪽과 공유한다.
    - **R2** 후보 0개면 아무것도 하지 않는다(`reason='none'`). 코디네이터는 자기
      값으로 돈다 — **폴백을 없애지 말 것.** 온실을 비워도 난방은 돌아야 한다.
    - **R3** 후보 1개면 그것이 기준이다. **저장하지 않는다** — 파생값을 컬럼에
      쓰면 구획이 끝나도 옛 값이 남고, 사람이 고른 것인지 계산된 것인지
      구분할 수 없게 된다(`expected_end` 와 같은 규율).
    - **R4** 후보 2개 이상이면 **자동으로 고르지 않는다**(`reason='ambiguous'`).
      겹침(간작·혼작)이 정상인 도메인이라 자동 선택은 조용히 틀린다. 사람이
      `source_plot_id` 로 지정한다.
    - **R5** 지정한 구획이 끝났거나 스코프 밖으로 갔거나 사라지면 판정에서
      빼고 R2~R4 를 다시 적용하되, **옵션 값은 지우지 않는다**
      (`pinned_missing=True` 로 화면이 말한다). 조용히 지우면 사람이 무엇을
      골랐었는지 알 수 없다.

    ## 방향이 다르면 기준도 다르다 — 이 비대칭은 의도된 것이다

    `facility_control_for_plot()` 은 "이 **구획**을 맡는 제어가 누구인가" 라
    구역 코디네이터 × 시설 전체 구획을 **제외**한다(구획 전체를 대표해 맡는다고
    말할 수 없다). 여기는 "내 **구역**에서 무엇이 자라나" 라 같은 짝을
    **포함**한다(그 작물은 이 구역에서도 자란다). 둘을 같게 만들지 말 것.
    """
    import json as _json

    out = {'facility_uuid': None, 'bay_id': None, 'candidates': [],
           'plot': None, 'reason': 'no-facility',
           'pinned': None, 'pinned_missing': False}
    if fn is None:
        return out

    try:
        opts = _json.loads(fn.custom_options) if fn.custom_options else {}
    except (TypeError, ValueError):
        opts = {}
    facility_uuid = (opts.get('geo_facility_id') or '').strip() or None
    bay_id = (opts.get('bay_scope') or '').strip() or None
    pinned = (opts.get('source_plot_id') or '').strip() or None
    out['facility_uuid'] = facility_uuid
    out['bay_id'] = bay_id
    out['pinned'] = pinned
    if not facility_uuid:
        return out

    rows = plots_in_facility(facility_uuid, bay_id=bay_id, on=on)
    out['candidates'] = [plot_brief_for_control(r, on=on) for r in rows]

    if pinned:
        hit = [r for r in rows if r.unique_id == pinned]
        if hit:
            out['plot'] = plot_brief_for_control(hit[0], on=on)
            out['reason'] = 'pinned'
            return out
        # R5 — 지정이 더는 후보가 아니다. 값은 남기고 사실만 말한다.
        out['pinned_missing'] = True

    if not rows:
        out['reason'] = 'none'
    elif len(rows) == 1:
        out['plot'] = out['candidates'][0]
        out['reason'] = 'only'
    else:
        out['reason'] = 'ambiguous'
    return out


def timeline(plot, program=None, on=None, sched=None, stage=None,
             events=None):
    """구획의 기간을 **한 축**으로 → `{start, end, today_pct, stages[]}`.

    화면이 날짜 셋(시작·오늘·종료)과 단계 경계를 텍스트로 늘어놓는 대신 축
    하나로 보이기 위한 것이다. 사람은 "8/17 시작, 4일차, 생육기 2/3" 를 머릿속
    에서 배치해야 알 수 있지만, 축은 보는 순간 안다.

    ## 계산은 서버가 한다 — 그리고 `stage_of` 와 **같은 경계**를 쓴다

    단계 길이·기준점(P5 승인)·계획 경계(P8)·"끝까지" 단계 처리가 전부
    `stage_schedule` 의 규칙이라, 화면이 다시 조립하면 두 곳이 곧 갈린다.
    예전에는 이 함수가 자기만의 조립을 갖고 있었고 GDD 를 보지 않아, 같은
    모달에서 축이 가리키는 단계와 "현재 단계" 줄이 다를 수 있었다.

    ## 끝이 없는 프로그램

    마지막 단계의 `days` 가 비어 있으면(수확기 = 사람이 끝낼 때까지) 축의 끝을
    정할 수 없다. 그때는 **마지막 단계를 열린 구간**으로 표시하고 `open_end`
    를 True 로 준다 — 임의의 종료일을 지어내면 화면이 "언제 끝난다" 고
    말하게 된다.

    반환:
      start      ISO date | None
      end        ISO date | None      (열린 구간이면 None)
      open_end   bool
      today_pct  0~100 | None         (축 위 현재 위치)
      elapsed_days, total_days
      stages     [{key, name, days, source, from_pct, to_pct, current}]
                 `source` 는 그 경계를 누가 정했나 — 'actual'(확정) |
                 'planned'(사람이 잡음) | 'program'. 프로그램과 달라진 구간이
                 보여야 "참고는 프로그램, 실제는 이것" 이 이해된다.
    """
    from datetime import timedelta

    if sched is None:
        sched = stage_schedule(plot, program=program, on=on)
    if sched is None:
        return None

    # **지나간 단계도 축에 남긴다.** 기준점 이후만 그리면 3단계가 확인된 구획의
    # 축이 3단계에서 시작해, 그 작기가 어떻게 흘러왔는지가 화면에서 사라진다 —
    # 축은 "지금 어디쯤" 을 답하는 그림이고, 앞이 없으면 '어디쯤' 이 성립하지 않는다.
    bounds = _fill_ends(list(_past_boundaries(plot, sched, events=events))
                        + list(sched['boundaries']))
    base_on = bounds[0]['starts_on'] or plot.started_on
    ref = sched['ref']

    # 칸의 폭 — 경계가 잡힌 구간은 **실제 날짜 차이**다(계획으로 늘린 단계가
    # 축에서도 길어진다). 마지막 열린 구간에도 폭이 필요하다: 0 이면 축에서
    # 사라진다. 앞 구간 평균만큼 주되 "여기서 끝난다" 고 말하지 않는다.
    spans = []
    for i, b in enumerate(bounds):
        nxt = bounds[i + 1] if i + 1 < len(bounds) else None
        if (nxt is not None and nxt['starts_on'] is not None
                and b['starts_on'] is not None):
            spans.append(max(0, (nxt['starts_on'] - b['starts_on']).days))
        else:
            spans.append(b['days'] if b['days'] else None)
    known = [w for w in spans if w]
    tail = int(sum(known) / len(known)) if known else 7
    # **폭 0 은 0 이다.** `tail` 은 길이를 *모르는* 칸(열린 마지막 구간)을 위한
    # 값이고, 길이가 **없는** 칸과는 다르다. 둘을 같이 다루면 확인된 전환 때문에
    # 0일이 된 칸이 평균 폭을 차지해, "오늘" 마커가 앞 칸에 찍히는데 현재 단계는
    # 뒤 칸으로 표시된다(2026-08-24 실제로 그렇게 보였다).
    widths = [tail if w is None else w for w in spans]
    total = sum(widths) or 1

    # 아직 시작 전(계획)이면 **어느 단계도 진행 중이 아니다.** 예전에는
    # `max(0, …)` 이 경과를 0 으로 눕혀 첫 단계가 `current` 로 잡혔고, 화면은
    # 심지도 않은 구획을 "육묘기 진행 중" 이라고 말했다.
    not_started = sched['not_started']
    elapsed = max(0, (ref - base_on).days)

    # **현재 칸은 `stage_of` 가 정한다.** 축이 자기 폭으로 따로 고르면 승인 대기로
    # 고정된 구획에서 축이 가리키는 단계와 "현재 단계" 줄이 서로 다른 칸을
    # 가리킨다 — 실제로 그렇게 갈렸다(축은 녹협, 줄은 수확).
    if stage is None:
        stage = stage_of(plot, program=program, on=on, sched=sched)
    marked = None
    if stage and stage.get('state') == 'running' and stage.get('index'):
        for i, b in enumerate(bounds):
            if b['index'] == stage['index']:
                marked = i
                break
    elif stage and stage.get('state') == 'past_end':
        marked = len(bounds) - 1

    out_stages = []
    acc = 0
    cur_idx = None
    for i, (b, w) in enumerate(zip(bounds, widths)):
        frm, to = acc, acc + w
        if cur_idx is None and elapsed < to:
            cur_idx = i
        out_stages.append({
            'key': b['key'],
            'name': b['name'],
            'days': b['days'],
            'source': b['source'],
            'starts_on': (b['starts_on'].isoformat()
                          if b['starts_on'] else None),
            'from_pct': round(frm * 100.0 / total, 2),
            'to_pct': round(to * 100.0 / total, 2),
            'current': False,
        })
        acc = to
    if marked is not None:
        cur_idx = marked
    if cur_idx is None:
        cur_idx = len(out_stages) - 1
    if out_stages and not not_started:
        out_stages[cur_idx]['current'] = True

    end_on = sched['end_on']
    if end_on is None and not sched['open_end']:
        end_on = base_on + timedelta(days=total - 1)
    anchor_on = (sched['boundaries'][0]['starts_on']
                 if sched['boundaries'] else base_on) or base_on
    return {
        'start': plot.started_on.isoformat(),
        # 기준점은 여전히 **확인된 전환**의 날이다 — 축의 왼쪽 끝(시작일)과 다르다.
        'anchor': anchor_on.isoformat(),
        'end': end_on.isoformat() if end_on else None,
        'open_end': sched['open_end'],
        # 100 을 넘길 수 있다(예정보다 오래 끌고 있다) — 넘긴 사실 자체가
        # 정보라 자르지 않고, 화면이 축 밖 표시로 그린다.
        #
        # **시작 전이면 `None` 이다.** 0 으로 두면 화면이 축의 맨 왼쪽에 오늘
        # 마커를 세워 "이제 막 시작했다" 로 읽힌다 — 시작하지 않은 것의 위치는
        # 0 이 아니라 **없는 값**이다.
        'today_pct': None if not_started else round(elapsed * 100.0 / total, 2),
        'elapsed_days': None if not_started else elapsed + 1,   # 심은 날이 1일차
        # 시작까지 남은 날 — 축은 그대로 그리고 이 값이 "언제부터" 를 말한다.
        'days_until_start': ((plot.started_on - ref).days
                             if not_started else None),
        'total_days': total,
        'stages': out_stages,
    }


def plot_brief_for_control(row, on=None, capacities=None):
    """제어 화면이 한 줄로 읽을 수 있는 최소 요약.

    면적·치수는 넣지 않는다 — 시설에서는 낼 수 없는 값이고, 제어가 알아야 하는
    것은 "무엇이 며칠째" 다.

    `capacities` 를 주면 몫(p6_50)을 파생 비율과 함께 낸다. 시설 하나의 총량을
    호출부가 **한 번** 읽어 넘기는 형태다 — 구획마다 시설을 다시 조회하면 목록
    하나에 N+1 이 된다.
    """
    due, _src = expected_end(row)
    out = {
        'unique_id': row.unique_id,
        'subject': row.subject,
        'variety': row.variety,
        'name': row.name,
        'bay_id': row.bay_id,
        'allocation': allocation_view(
            row.allocation,
            (capacities or {}).get(row.bay_id) if capacities else None),
        'started_on': row.started_on.isoformat() if row.started_on else None,
        'days_since_planted': _days_shown(row, on=on),
        # 아직 시작 전인 구획(계획). 목록에 함께 보이므로 **자기가 계획이라는
        # 사실을 스스로 말해야** 한다 — 날짜만 보고 사람이 계산하게 두면
        # 자라는 것과 예정된 것이 같은 줄로 읽힌다.
        'planned': row.started_on is not None and row.started_on > (on or date.today()),
        'days_until_start': days_until_start(row, on=on),
        'expected_end_on': due.isoformat() if due else None,
    }
    # 제어 화면이 "지금 어느 단계인가" 를 함께 말할 수 있어야 설정값의 근거가
    # 생긴다 — 같은 24℃ 가 육묘기와 착과기에서 다른 뜻이다.
    prog = program_brief(row)
    if prog:
        out['program_name'] = prog.get('name')
        st = stage_of(row, program=prog, on=on)
        if st and st.get('state') == 'running':
            out['stage_name'] = st.get('name')
            out['stage_index'] = st.get('index')
            out['stage_total'] = st.get('total')
        # 기간 축 — 화면이 날짜를 늘어놓는 대신 한 줄로 보인다. 계산은 여기서
        # 한 번만 한다(단계 길이·기준점·"끝까지" 처리가 전부 서버 규칙이다).
        out['timeline'] = timeline(row, program=prog, on=on)
    return out


def sensors_for_plot(plot, containers=None, markers=None):
    """구획이 참조할 장치 → `{'in_plot', 'from_zone', 'zone_uuid', 'source'}`.

    1순위는 구획 폴리곤 안의 장치, 없으면 소속 zone 의 장치다. 노지 zone 의
    센서는 현실적으로 한두 개라 **폴백이 기본 경로가 된다** — 여러 구획이 같은
    값을 보게 되는데, 그래도 된다. 식생 구획은 센서의 단위가 아니라 **해석의
    단위**다: 같은 25도라도 상추에는 높고 토마토에는 적정이다.

    `source` 는 'plot' | 'bay' | 'facility' | 'zone' | 'none' — 화면이 "이 값은
    구역 대표값" 임을 말할 수 있어야 한다. 말하지 않으면 사용자는 구획마다 따로
    잰 값으로 읽는다.

    시설 구획(기하 없이 부모에 매단 것)은 **마커가 아니라 fitting** 에서 센서를
    찾는다(`facility_sensor_ids`) — 구역 → 시설 → zone 순으로 좁은 쪽이 이긴다.

    ⚠ 반환값을 어디에도 저장하지 말 것. 바인딩(`geo_binding`)을 만드는 것도
    금지다 — 3개월 뒤 사라지는 대상에 바인딩을 매다는 것이 이 설계가 피하려는
    바로 그 구조다.
    """
    facility_uuid = getattr(plot, 'facility_uuid', None)
    own_geom = (plot.has_own_geometry()
                if hasattr(plot, 'has_own_geometry') else True)

    # 시설 구획(기하 없음)은 마커 판정을 아예 건너뛴다. 파생 기하는 **시설
    # 외피**라, 그것으로 폴리곤 안 마커를 세면 시설 어딘가에 있는 장치가 전부
    # 이 구획의 것으로 잡힌다 — 파생값을 사실처럼 쓰는 순간이다.
    if facility_uuid and not own_geom:
        fs = facility_sensor_ids(facility_uuid, getattr(plot, 'bay_id', None))
        zone = zone_for_plot(plot, containers=containers)
        from_zone = []
        if zone is not None:
            from_zone = sorted(_only_sensor_ids(
                device_membership.device_ids_in_shape(zone, markers=markers)))
        if fs['in_bay']:
            source = 'bay'
        elif fs['facility']:
            source = 'facility'
        elif from_zone:
            source = 'zone'
        else:
            source = 'none'
        return {
            'in_plot': [],
            'in_bay': fs['in_bay'],
            'from_facility': fs['facility'],
            'from_zone': from_zone,
            'facility_uuid': facility_uuid,
            'bay_id': getattr(plot, 'bay_id', None),
            'zone_uuid': zone.unique_id if zone is not None else None,
            'zone_name': _shape_name(zone) if zone is not None else None,
            # **`zone_uuid` 는 zone 이 아닐 수 있다.** 이름이 그렇게 읽히지만
            # 값은 `container_for_geometry` 가 준 것이고, 그 계약은 "감싸는
            # site/zone"(겹치면 zone 이 이긴다)이다 — zone 이 없는 자리에서는
            # **site 도형**이 온다. 그것을 zone 으로 믿고 구역 화면을 열면
            # 조회가 빈 손으로 끝나고 화면이 스켈레톤에 멈춘다(실측: 시설 구획의
            # 뒤로가기가 그랬다 — 필지와 시설의 이름까지 같아 오래 안 보였다).
            #
            # 그래서 **종류를 함께 낸다.** 이름을 바꾸는 대신 판단 근거를 주는
            # 쪽을 고른 이유는 소비처가 여럿이고, 종류가 없으면 각자 다시
            # 조회해서 확인해야 하기 때문이다.
            'zone_kind': getattr(zone, 'type', None) if zone is not None else None,
            'source': source,
        }

    in_plot = sorted(_only_sensor_ids(device_membership.device_ids_in_geometry(
        plot.geo_id, geometry_of(plot),
        _label='plot %s' % plot.unique_id, markers=markers)))

    zone = zone_for_plot(plot, containers=containers)
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
        # 위 주석 참조 — zone 일 수도 site 일 수도 있다. 노지 구획도 zone 이
        # 없는 지도에서는 site 가 온다.
        'zone_kind': getattr(zone, 'type', None) if zone is not None else None,
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

def active_plots(map_uuid=None, on=None, include_planned=False):
    """`on`(기본 오늘) 시점에 재배 중인 구획 목록.

    지도 기본 렌더의 판정과 같아야 한다 — 여기와 `GeoPlot.is_active` 가
    갈리면 목록에는 있는데 지도에 없는 구획이 생긴다.

    `map_uuid` 를 주지 않으면 **전체 지도**를 본다(운영 페이지 `/plots`).
    지도를 오가며 세 번 조회하는 것과 한 번에 받는 것은 "이번 철에 무엇을
    어디에 심었나" 를 보는 화면에서 전혀 다른 일이다.

    `include_planned` 는 시작일이 아직 오지 않은 구획까지 낸다. **지도 렌더에는
    쓰지 않는다** — 아직 심지 않은 것을 그리면 있는 것처럼 보인다. 목록 화면
    (`/plots`)만 켠다.
    """
    on = on or date.today()
    # `ended_on > on` — 종료일은 "종료된 날" 이라 그날부터 이미 활성이 아니다.
    # GeoPlot.is_active 와 **같은 부등호**여야 한다(그 docstring 참조).
    q = GeoPlot.query
    if not include_planned:
        q = q.filter(GeoPlot.started_on <= on)
    if map_uuid:
        q = q.filter(GeoPlot.geo_id == map_uuid)
    return q.filter(
        (GeoPlot.ended_on.is_(None)) | (GeoPlot.ended_on > on)
    ).all()


def plots_overlapping(map_uuid, geom, since=None, until=None,
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

    q = GeoPlot.query.filter(GeoPlot.geo_id == map_uuid)
    if since is not None:
        q = q.filter((GeoPlot.ended_on.is_(None)) |
                     (GeoPlot.ended_on >= since))
    if until is not None:
        q = q.filter(GeoPlot.started_on <= until)
    if not include_active:
        q = q.filter(GeoPlot.ended_on.isnot(None))

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

    out.sort(key=lambda t: (t[0].started_on or date.min), reverse=True)
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

def valves_for_plot(plot):
    """구획과 겹치는 **장치 영역** 목록.

    ⚠ **이름이 오해를 부른다 — 이 함수는 관수 장치를 가려내지 않는다.**
    판정 근거는 `GeoShape.type == 'device'` 인 영역 도형이 구획과 면적을 갖고
    겹친다는 것 하나뿐이다. 그 장치가 물을 주는지 빛을 주는지 바람을 넣는지
    시스템은 모른다 — 실측(김제): 영역에 묶인 출력이 전부
    `output_type='virtual_on_off_single'`(범용 on/off)이고, 'v341' 같은 이름은
    그 농장의 작명일 뿐 어디서도 읽지 않는다. 화면 문구를 "적신다" 로 쓰지
    말 것(coverageHtml 주석 참조). 이름은 역사적인 것이다.

    `[{shape_uuid, shape_name, device_id, device_name, overlap_m2,
       coverage_pct}]` — `coverage_pct` 는 **구획 면적 대비** 덮인 비율이다.
    밸브 구역 대비가 아니다: 사람이 알고 싶은 것은 "내 두둑이 얼마나 젖는가"
    이지 "밸브가 얼마나 쓰이는가" 가 아니다.

    관수량을 여기서 계산하지 않는다. 겹친 영역에서 물은 물리적으로 공유되므로
    작물별 요구량을 합산하면 틀린 숫자가 나온다 — 재료만 내고 판단은 사람이
    한다(설계 §자원 배분).
    """
    from aot.aot_flask.geo import device_binding

    src = _shapely(geometry_of(plot))
    if src is None:
        return []
    total = shapely_area_m2(src)

    rows = GeoShape.query.filter(
        GeoShape.geo_id == plot.geo_id,
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
            logger.warning('plot: 밸브 바인딩 해소 실패(%s): %s',
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


def plots_covered_by_shape(shape_geom, map_uuid, on=None,
                               exclude_uuid=None, candidates=None,
                               prepared=None):
    """도형(관수 구역 등)이 덮는 **재배 중인** 구획들.

    `valves_for_plot` 의 **역방향**이다. 그쪽이 "이 구획을 적시는 밸브" 라면
    이쪽은 "이 밸브가 적시는 구획들" 이다.

    제어 화면에 이 방향이 필요한 이유: 밸브를 켜는 사람이 알아야 하는 것은 "이
    구획이 얼마나 젖는가" 가 아니라 **"켜면 무엇이 함께 젖는가"** 다. 겹침이
    정상인 도메인(간작·혼작, VP-3)이라 한 밸브가 여러 작물을 적시는 것이 예외가
    아니라 기본이고, 그 사실을 말하지 않으면 사용자는 자기가 고른 작물에만
    물을 준다고 읽는다.

    `candidates` 로 활성 구획 목록을 넘기면 재사용한다 — 밸브마다 다시 조회하면
    밸브 수 × 구획 수가 된다.

    `prepared`(`{구획 uuid: shapely}`)를 주면 도형 변환도 재사용한다. 이것이
    없으면 밸브마다 같은 구획의 기하를 **다시 파싱**한다 — 밸브 16개 × 구획
    23개면 같은 일을 368번 한다(실측: `geometry_of` 호출 441회).
    """
    src = _shapely(shape_geom)
    if src is None:
        return []

    # 겹치지 않는 쌍을 **경계 상자로 먼저 걸러 낸다.** 교차 계산과 면적 투영은
    # 둘 다 비싸고, 지도에서 서로 멀리 떨어진 두둑과 밸브 구역이 대부분이다.
    # 상자는 겹치는데 실제로는 안 겹치는 경우가 있으므로 **걸러 내기에만** 쓴다
    # (통과한 쌍은 그대로 정확히 계산한다).
    try:
        sxmin, symin, sxmax, symax = src.bounds
    except Exception:
        sxmin = None

    rows = candidates if candidates is not None else active_plots(map_uuid, on=on)
    out = []
    for row in rows:
        if exclude_uuid and row.unique_id == exclude_uuid:
            continue
        other = (prepared or {}).get(row.unique_id)
        if other is None:
            other = _shapely(geometry_of(row))
        if other is None:
            continue
        if sxmin is not None:
            try:
                oxmin, oymin, oxmax, oymax = other.bounds
                if (oxmax < sxmin or oxmin > sxmax
                        or oymax < symin or oymin > symax):
                    continue
            except Exception:
                pass
        try:
            inter = src.intersection(other)
        except Exception:
            continue
        if inter.is_empty:
            continue
        # 경계를 맞대고 있을 뿐인 옆 두둑을 "함께 젖는다" 고 하면 안 된다 —
        # 면적이 있는 교차만 센다(plots_overlapping 과 같은 기준).
        overlap = shapely_area_m2(inter)
        if overlap <= 0:
            continue
        out.append({
            'unique_id': row.unique_id,
            'subject': row.subject,
            'name': row.name,
            'overlap_m2': round(overlap, 1),
        })
    out.sort(key=lambda p: p['overlap_m2'], reverse=True)
    return out


def plots_by_valve_device(map_uuid, on=None):
    """`{device_id: [구획, ...]}` — 지도의 **영역 장치**별로 "무엇에 걸치는가".

    ⚠ 관수 장치라는 근거는 없다 — `valves_for_plot` 의 경고를 그대로 읽을 것.

    **구역 모달과 식생 모달이 함께 쓴다.** 구역에서 켠 밸브도 그 안의 여러
    작물에 물을 준다 — 식생 모달에만 경고를 붙이면 "구역에서 켜면 안전하다"는
    잘못된 대비가 생긴다. 같은 사실을 양쪽이 같은 근거로 말해야 한다.

    지도 전체를 **한 번에** 만든다. 출력마다 되짚으면 출력 수 × 도형 수 ×
    구획 수가 되는데, 구역 모달은 출력이 여럿이라 그 곱이 바로 드러난다.
    """
    from aot.aot_flask.geo import device_binding

    active = active_plots(map_uuid, on=on)
    if not active:
        return {}

    shapes = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.type == 'device').all()

    # 구획 기하는 **한 번만** 변환한다. 밸브마다 다시 파싱하면 밸브 수 ×
    # 구획 수만큼 같은 일을 되풀이한다.
    prepared = {}
    for row in active:
        geom = _shapely(geometry_of(row))
        if geom is not None:
            prepared[row.unique_id] = geom

    out = {}
    for shape in shapes:
        covered = plots_covered_by_shape(
            geometry_of(shape), map_uuid, on=on, candidates=active,
            prepared=prepared)
        if not covered:
            continue
        try:
            binding = device_binding.current_one('shape', shape.unique_id,
                                                 role='area')
        except Exception as exc:
            logger.warning('plot: 밸브 바인딩 해소 실패(%s): %s',
                           shape.unique_id, exc)
            continue
        device_id = binding.device_id if binding is not None else None
        if not device_id:
            # 밸브 미배정 구역 — 켤 장치가 없으니 "함께 젖는다" 를 말할 대상도
            # 없다. 미배정 사실 자체는 valves_for_plot 이 따로 낸다.
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


def nearest_devices(plot, candidate_ids, markers=None, limit=1):
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

    poly = _shapely(geometry_of(plot))
    if poly is None:
        return []
    try:
        ref = poly.representative_point()
    except Exception:
        return []

    to_m, _from_m, lat0 = local_frame(geometry_of(plot))
    if to_m is None:
        return []
    rx, ry = to_m(ref.x, ref.y)

    if markers is None:
        markers = device_membership.load_markers(plot.geo_id)

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


def covered_subject_names(covered, exclude_uuid=None):
    """구획 목록 → 화면에 쓸 이름들. **uuid 는 내보내지 않는다.**

    `subject` 이 사람이 부르는 이름이고, 없으면 구획 이름으로 떨어진다.
    """
    names = []
    for c in covered or []:
        if exclude_uuid and c.get('unique_id') == exclude_uuid:
            continue
        label = c.get('subject') or c.get('name')
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

    rows = active_plots(zone_shape.geo_id, on=on)
    containers = device_membership.load_containers(zone_shape.geo_id)

    items, geoms = [], []
    for row in rows:
        # 같은 지도의 다른 zone 소속은 뺀다. 비교는 인스턴스가 아니라
        # unique_id 로 한다 — zone_shape 가 호출자가 따로 조회한 행이면
        # load_containers 가 돌려준 인스턴스와 다를 수 있다.
        # 시설 구획은 배분에서 제외한다. 기하가 파생(시설 외피)이라 넣으면
        # 온실 하나가 zone 을 통째로 덮은 것처럼 계산되고, 애초에 노지 면적과
        # 시설 면적은 한 분모에 섞이면 둘 다 못 읽는 숫자가 된다.
        if not row.has_own_geometry():
            continue
        zone_of = zone_for_plot(row, containers=containers)
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
            'subject': row.subject,
            'variety': row.variety,
            'area_m2': round(a, 1),
            'ratio_pct': round(a / zone_area * 100.0, 1) if zone_area > 0 else None,
            # 달력만 보는 값이라 여기서 함께 낸다 — 구역 [현황]이 "무엇이
            # 며칠째 자라고 있나" 를 한 줄로 말할 수 있어야 한다.
            'days_since_planted': _days_shown(row, on=on),
        })
        # 현재 단계 — **면적을 대신하는 값**이다(2026-08-20). 면적은 심고 나면
        # 안 바뀌므로 "지금 어떤가" 를 묻는 [현황]에서는 아무 날에 봐도 같은
        # 숫자다. 단계는 날마다 옮겨 가고, 그것이 이 구역에서 지금 무슨 일이
        # 일어나는지를 말한다. 면적은 구획 모달 [개요]가 갖는다.
        #
        # 시설의 구획 목록(`plot_brief_for_control`)과 **같은 키**를 쓴다 —
        # 계층이 같아야 사용자가 옮겨 다녀도 같은 자리에서 같은 것을 찾는다.
        try:
            _st = stage_of(row, on=on)
        except Exception:                                   # noqa: BLE001
            _st = None
        if _st and _st.get('state') == 'running':
            # **이름만 낸다.** 순번(3/6)은 목록에서 뜻을 만들지 못한다 — 전체가
            # 몇 단계인지 아는 사람만 읽을 수 있고, 다섯 줄이 나란히 서면 그
            # 숫자들이 서로 비교되는 것처럼 보인다(다른 프로그램이라 비교 대상이
            # 아니다). 순번이 필요한 자리는 구획 모달이다.
            items[-1]['stage_name'] = _st.get('name')

    used = 0.0
    if geoms:
        try:
            from shapely.ops import unary_union

            union = unary_union(geoms)
            if zone_poly is not None:
                union = union.intersection(zone_poly)
            used = shapely_area_m2(union)
        except Exception as exc:
            logger.warning('plot: 합집합 계산 실패 — 미배정 생략: %s', exc)
            used = None

    unassigned = None
    if used is not None and zone_area > 0:
        unassigned = max(zone_area - used, 0.0)

    return {
        'zone_uuid': zone_shape.unique_id,
        'zone_area_m2': round(zone_area, 1) if zone_area else 0.0,
        'plots': items,
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

def elapsed_days(row, on=None, since=None):
    """재배 일수 — **심은 날이 1일차**. 기하가 아니라 달력만 본다.

    +1 을 여기서 한 번만 한다. 화면마다 "0일차부터 세는 곳" 과 "1일차부터 세는
    곳" 이 갈리면 같은 두둑이 창마다 하루씩 다른 나이를 갖는다. 농사에서 "정식
    후 며칠" 은 심은 날을 1일로 세는 관행이라 그쪽에 맞춘다.

    종료된 작기는 오늘이 아니라 **종료일** 을 기준으로 센다 — 작년에 끝난 작기가
    오늘까지 계속 나이를 먹으면 이력 목록이 곧 거짓말이 된다.
    """
    # `since` 가 있으면 그 날을 1일차로 센다 — 확인된 단계 전환(P5)이 기준점을
    # 옮겼을 때 쓴다. 없으면 시작일이 1일차다(종전 동작).
    base = since or row.started_on
    if base is None:
        return None
    ref = row.ended_on or (on or date.today())
    # **음수를 여기서 막지 않는다.** 시작 전이면 음수가 나오는데, `stage_of` 가
    # 그 부호로 계획 상태(`not_started`)를 판정한다 — 여기서 None 으로 눕히면
    # 그 판정이 통째로 사라진다(실제로 한 번 그렇게 고쳤다가 회귀를 냈다).
    # 화면에 나가는 값은 응답을 만드는 자리에서 막는다(`_days_shown`).
    return (ref - base).days + 1


def _days_shown(row, on=None):
    """화면에 내보내는 재배 일수 — **시작 전이면 없는 값**이다.

    계산(`elapsed_days`)은 음수를 그대로 내야 `stage_of` 가 계획을 알아본다.
    응답에 그 음수를 실으면 화면이 "-29일차" 를 그리므로 여기서 한 번 막는다.
    남은 날은 별개 값(`days_until_start`)으로 간다 — 두 뜻을 한 숫자에 담으면
    부호를 아는 화면만 옳게 읽는다.
    """
    d = elapsed_days(row, on=on)
    return d if (d is not None and d > 0) else None


def days_until_start(row, on=None):
    """시작일까지 남은 날. 이미 시작했거나 시작일이 없으면 None.

    `elapsed_days` 와 **한 쌍**이다 — 둘 중 하나만 값을 갖는다.
    """
    if row.started_on is None:
        return None
    on = on or date.today()
    return (row.started_on - on).days if row.started_on > on else None


def days_to_expected_end(row, on=None, programs=None, anchors=None):
    """예상 종료일까지 남은 날 (음수 = 지났다). 없으면 None.

    지난 것을 숨기지 않는다 — "예상보다 20일 지났다" 는 수확을 미루고 있다는
    뜻이라 그 자체가 사용자가 봐야 할 사실이다.
    """
    if row.ended_on is not None:
        return None
    # 사람이 안 적었어도 프로그램이 있으면 파생 종료일로 센다 — 그러지 않으면
    # 프로그램을 골라 둔 구획이 "예상 종료 없음" 으로 보인다.
    due, _src = expected_end(row, programs=programs, anchors=anchors)
    if due is None:
        return None
    return (due - (on or date.today())).days


def to_dict(row, containers=None, with_sensors=False, markers=None,
            with_valves=None, with_dims=None, facilities=None,
            programs=None, anchors=None, events=None):
    """GeoPlot → API 응답 dict.

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

    ## 시설 구획은 면적·치수·밸브를 내지 않는다

    `area_m2` 는 `None`(0 이 아니다 — 0 은 "면적이 없다"는 거짓말이다), `dims`
    와 `valves` 는 아예 싣지 않는다. 파생 기하가 **시설 외피**라 실제 재배
    구역보다 넓고, 무엇보다 시설은 노지형(땅에 심고 온실만 씌운 것)·베드형·
    수직형에 따라 **같은 바닥 면적이 전혀 다른 재배 규모**다. 면적에 재식거리를
    곱하는 노지식 추정은 형태에 따라 몇 배씩 틀린 숫자를 내는데, 틀렸다는 표시가
    어디에도 없다 — 숫자가 나온다는 것이 이 실패의 전부다.

    규모를 적는 자리는 스키마가 아니라 **구획 노트**다(`p6_36` 이 배치 컬럼을
    걷어낸 것과 같은 이유). "베드 12줄 × 30m, 3단" 은 노트 한 줄이면 되고, 노트
    다이제스트가 AI 컨텍스트에 실린다.
    """
    own_geom = row.has_own_geometry()
    facility_uuid = row.facility_uuid
    out = {
        'unique_id': row.unique_id,
        'geo_id': row.geo_id,
        'feature': row.feature,
        # 위치의 정본이 어느 쪽인가 — 'own'(기하) | 'facility'(부모).
        # 화면이 "이 구획은 구역 전체를 가리킨다" 를 말할 수 있어야 한다.
        'location_source': 'own' if own_geom else (
            'facility' if facility_uuid else 'none'),
        'facility_uuid': facility_uuid,
        'bay_id': row.bay_id,
        'name': row.name,
        # 대상 종류('vegetation' | 'livestock' | 'facility' | 'other').
        # 저장해 놓고 내보내지 않으면 화면이 프로그램을 종류로 좁힐 수 없다 —
        # 식생 구획에 가축 프로그램이 보이게 된다.
        'kind': row.kind or 'vegetation',
        'subject': row.subject,
        'variety': row.variety,
        'started_on': row.started_on.isoformat() if row.started_on else None,
        'ended_on': row.ended_on.isoformat() if row.ended_on else None,
        'expected_end_on': (row.expected_end_on.isoformat()
                            if row.expected_end_on else None),
        'ended_reason': row.ended_reason,
        'source_kind': row.source_kind,
        'source_ref': row.source_ref,
        'color': row.color,
        'active': row.is_active(),
        # 시설 구획은 면적을 내지 않는다(위 docstring 참조).
        'area_m2': round(area_m2(row), 1) if own_geom else None,
        # 달력만 보는 값이라 목록에서도 항상 싣는다 — 구역 모달의 "지금 심겨
        # 있는 것" 목록이 이 값으로 재배 일수를 보인다.
        'days_since_planted': _days_shown(row),
        'planned': row.started_on is not None and row.started_on > date.today(),
        'days_until_start': days_until_start(row),
        'days_to_expected_end': days_to_expected_end(row, programs=programs,
                                                     anchors=anchors),
    }
    if facility_uuid:
        brief = facility_brief(facility_uuid, facilities=facilities)
        out['facility_name'] = brief.get('name')
        out['bay_name'] = (brief.get('bay_names') or {}).get(row.bay_id)
        # 구역 안에서의 몫 (p6_50) — 적힌 값과 **파생 비율**을 함께 낸다.
        # 비율을 저장하지 않는 이유가 여기 있다: 총량이 바뀌면 비율도 따라
        # 바뀌어야 하는데, 저장해 두면 둘이 조용히 갈린다.
        out['allocation'] = allocation_view(
            row.allocation, (brief.get('bay_capacities') or {}).get(row.bay_id))
        # 고를 수 있는 구역 목록 — 모달에서 구역을 바꾸려면 **선택지**가 있어야
        # 한다. 노지 구획은 위치를 도형 편집으로 옮기지만, 시설 구획의 위치는
        # `bay_id` 문자열이라 옮기는 일이 곧 고르는 일이다.
        out['facility_bays'] = [{'id': bid, 'name': name or bid}
                                for bid, name in
                                sorted((brief.get('bay_names') or {}).items())]
        if not own_geom:
            # 지도·목록이 그릴 수 있도록 파생 기하를 함께 싣는다. `feature` 에
            # 넣지 않는 이유는 하나다 — 그 값을 그대로 되돌려 저장하면 파생이
            # 정본으로 승격해 시설을 옮겨도 구획이 옛 자리에 남는다.
            geom = ((brief.get('bay_geometries') or {}).get(row.bay_id)
                    or brief.get('geometry') or {})
            out['derived_feature'] = ({
                'type': 'Feature',
                'geometry': geom,
                'properties': {'derived_from': row.bay_id and 'bay' or 'facility'},
            } if geom else None)

    prog = program_brief(row, programs=programs)
    if prog:
        out['program'] = prog
        # 목표를 재는 센서가 이 구획에 있는지는 **상세에서만** 붙인다 —
        # 구획마다 센서 조회가 한 번씩 더 붙으므로 목록에서 켜면 N+1 이 된다
        # (`with_sensors` 가 이미 같은 성격의 비용 스위치다).
        # 일정은 **한 번만** 만든다 — 아래 넷이 전부 같은 것을 쓴다. 각자
        # 만들면 목록 화면 한 장(수십 구획)이 구획마다 네 벌씩 조회한다.
        sched = stage_schedule(row, program=prog, anchors=anchors,
                               programs=programs)
        st = stage_of(row, program=prog, with_observability=bool(with_sensors),
                      sched=sched)
        # 대기 중 전환·이력. **저장하지 않는 값과 저장된 값이 함께 나간다** —
        # 화면이 "지금 이렇게 보이는데 확인하시겠습니까" 를 말하려면 둘 다 필요하다.
        out['stage_proposal'] = stage_proposal(row, program=prog,
                                               sched=sched, anchors=anchors)
        out['stage_history'] = stage_history(row, events=events)
        # 단계 일정(P8) — 화면이 경계를 고치는 자리다. 여기서 내지 않으면
        # 사람은 전환이 **닥친 뒤에** 확인/연기만 할 수 있고, 미리 잡아 둘 수 없다.
        out['stage_schedule'] = stage_schedule_view(row, program=prog,
                                                    sched=sched, stage=st,
                                                    events=events)
        # 자동 승인은 구획의 성질이다(P8) — 프로그램이 아니라 여기서 낸다.
        out['auto_advance'] = bool(getattr(row, 'auto_advance', False))
        if st:
            out['stage'] = st
        # 기간 축 — 단계 이름·경계·오늘 위치. 화면이 날짜를 늘어놓는 대신 한 줄로
        # 보인다. 계산은 여기서 한 번만 한다(단계 길이·기준점·"끝까지" 처리가
        # 전부 서버 규칙이다). `plot_brief_for_control` 이 이미 같은 값을 싣고
        # 있었는데 **모달이 쓰는 이 응답에는 없어서**, 지도 위젯의 구획 모달만
        # 단계 이름 없이 경과/남음 두 칸으로 그려야 했다.
        out['timeline'] = timeline(row, program=prog, sched=sched,
                                   stage=st, events=events)
    due, due_src = expected_end(row, program=prog, programs=programs,
                                anchors=anchors,
                                sched=(sched if prog else None))
    if due is not None:
        out['expected_end_on'] = due.isoformat()
        # 사람이 적은 값인지 프로그램에서 나온 값인지 화면이 구분해 말해야 한다.
        out['expected_end_source'] = due_src

    if with_valves is None:
        with_valves = with_sensors
    if with_dims is None:
        with_dims = with_sensors
    # 시설 구획은 치수·밸브를 내지 않는다 — 근거는 파생 기하(시설 외피)뿐이라
    # 숫자가 나오는데 틀린다. 제어 쪽은 별도 축(구역 → 코디네이터)이 맡는다.
    if not own_geom:
        with_dims = False
        with_valves = False
    if with_dims:
        out['dims'] = dimensions(row)
    if with_sensors:
        out['sensors'] = sensors_for_plot(row, containers=containers,
                                              markers=markers)
    else:
        zone = zone_for_plot(row, containers=containers)
        out['zone_uuid'] = zone.unique_id if zone is not None else None
        # 이름과 종류도 함께 낸다 — **이미 손에 든 도형**이라 조회가 늘지 않는다.
        #
        # 목록만 받은 화면이 "상위로" 를 세우려면 uuid 만으로는 모자란다: 어느
        # 창을 열지는 종류가 정하고(구역이 없는 지도에서는 여기 필지가 온다),
        # 버튼의 이름표는 이름이 채운다. 이것이 없으면 화면은 상세 응답을
        # 기다려야 하고, 그동안 제목줄의 화살표만 늦게 나타난다.
        out['zone_name'] = _shape_name(zone) if zone is not None else None
        out['zone_kind'] = getattr(zone, 'type', None) if zone is not None else None
        # site — zone 과 별개 축으로 낸다. zone 이 site 를 이기므로 위 zone 이
        # 이미 site 종류면 그 자신이 site 다. zone 종류면 그 zone 을 감싸는
        # site 를 따로 찾는다(device_membership.site_for_geometry).
        if zone is not None and getattr(zone, 'type', None) == 'site':
            site = zone
        else:
            site = device_membership.site_for_geometry(
                row.geo_id, geometry_of(row, facilities=facilities),
                containers=containers)
        out['site_uuid'] = site.unique_id if site is not None else None
        out['site_name'] = _shape_name(site) if site is not None else None
    if with_valves:
        # 목록에서 구획마다 지도 도형을 전량 훑으면 구획 수 × 도형 수가 된다.
        out['valves'] = valves_for_plot(row)
    return out


# ── GDD (적산온도) ──────────────────────────────────────────────────────────
#
# 자료 커버리지 하한. 센서가 며칠 비면 그만큼 덜 쌓이고 단계가 조용히 뒤처진다 —
# 화면에는 "아직 육묘기" 로만 보이고 왜인지는 어디에도 없다. 그래서 부족하면
# GDD 를 **쓰지 않고** 날짜로 되돌아가되, 되돌아간 이유를 함께 싣는다.
#
# 이 값은 사실이 아니라 **정책**이다. 옳은 숫자가 따로 있는 것이 아니라, 어디까지
# 비면 판정을 포기할지 정한 것이다.
_GDD_MIN_COVERAGE = 0.8

# 온도로 볼 측정 이름. `DeviceMeasurements.measurement` 어휘를 그대로 쓴다.
_GDD_TEMP_MEASURE = 'temperature'


def _daily_extremes(device_id, channel, measure, start_ts, end_ts):
    """장치 채널의 **일별 최고·최저** → {date: (tmax, tmin)}.

    Influx 에 창 집계를 시킨다 — 원자료를 다 받아 파이썬에서 접으면 몇 달치가
    수만 점이 된다. 쿼리는 장치당 2회(최고·최저)지, 날짜당 2회가 아니다.

    **마지막 버킷은 버린다.** 오늘은 아직 안 끝났고, 그대로 두면 하루가 절반만
    쌓인 채 더해진다(그날의 Tmax 가 낮게 잡혀 GDD 가 과소평가된다).
    """
    from aot.utils.influx import query_string

    out = {}
    for fn in ('max', 'min'):
        try:
            tables = query_string(
                'C', device_id, channel=channel, measure=measure,
                start_str=start_ts, end_str=end_ts,
                group_sec=86400, group_fn=fn)
        except Exception as exc:
            logger.debug('GDD: %s 조회 실패(%s): %s', device_id, fn, exc)
            return {}
        for table in (tables or []):
            for rec in table.records:
                try:
                    day = rec.get_time().date()
                    val = float(rec.get_value())
                except (TypeError, ValueError, AttributeError):
                    continue
                cur = out.get(day) or [None, None]
                idx = 0 if fn == 'max' else 1
                # 같은 날짜가 두 번 나올 수 있다(창 경계). 극값으로 접는다.
                if cur[idx] is None:
                    cur[idx] = val
                elif fn == 'max':
                    cur[idx] = max(cur[idx], val)
                else:
                    cur[idx] = min(cur[idx], val)
                out[day] = cur
    return {d: (v[0], v[1]) for d, v in out.items()
            if v[0] is not None and v[1] is not None}


def _plot_temperature_channels(plot):
    """구획이 참조하는 온도 채널 → [(device_id, channel)].

    구획 안 센서가 1순위, 없으면 bay → 시설 → zone 순으로 폴백한다
    (`sensors_for_plot` 의 `source` 우선순위와 같은 규율 — 시설 구획은
    `in_plot` 이 항상 비어 있어 `in_bay`/`from_facility` 를 빼먹으면 무조건
    zone 폴백으로 떨어진다).
    """
    from aot.databases.models import DeviceMeasurements

    try:
        found = sensors_for_plot(plot) or {}
    except Exception:
        return []
    ids = (list(found.get('in_plot') or [])
           or list(found.get('in_bay') or [])
           or list(found.get('from_facility') or [])
           or list(found.get('from_zone') or []))
    out = []
    seen = set()
    for did in ids:
        if did in seen:
            continue
        seen.add(did)
        try:
            rows = DeviceMeasurements.query.filter_by(device_id=did).all()
        except Exception:
            continue
        for m in rows:
            if m.measurement == _GDD_TEMP_MEASURE:
                out.append((did, m.channel))
    return out


def gdd_accumulated(plot, program_row=None, on=None, with_series=False):
    """구획의 누적 GDD → dict (판정 불가면 `usable=False` + 이유).

    `GDD_day = max(0, (Tmax + Tmin) / 2 - T_base)` 를 날마다 더한다. 사용자가 고른
    공식이고, 하루 두 값만 있으면 되므로 센서 해상도에 덜 민감하다.

    ⚠ `env_control/cumulative_tracker` 의 GDD 와 **다른 값이다.** 그쪽은 제어
    보상용으로 사이클마다 적분하고 env_coordinator 함수가 있어야 한다. 노지
    구획에는 코디네이터가 없으므로 여기에 얹을 수 없다. 두 값이 다른 것은
    정상이다 — 한쪽을 다른 쪽에 맞추려 하지 말 것(docs/design/program-layer.md).
    """
    from datetime import timedelta

    info = {'usable': False, 'value': None, 'reason': None,
            't_base': None, 'days_counted': 0, 'days_expected': 0,
            'coverage_pct': None, 'sensor_count': 0}

    if program_row is None:
        return dict(info, reason='no-program')

    photo = getattr(program_row, 'photosynthesis', None) or {}
    t_base = photo.get('T_base') if isinstance(photo, dict) else None
    try:
        t_base = None if t_base is None else float(t_base)
    except (TypeError, ValueError):
        t_base = None
    if t_base is None:
        # 지어내지 않는다 — 기준온도가 없으면 GDD 라는 값이 성립하지 않는다.
        return dict(info, reason='no-t-base')
    info['t_base'] = t_base

    start = getattr(plot, 'started_on', None)
    if start is None:
        return dict(info, reason='no-start-date')
    today = on or date.today()
    end = min(getattr(plot, 'ended_on', None) or today, today)
    if end < start:
        return dict(info, reason='not-started')
    info['days_expected'] = (end - start).days      # 오늘(미완성)은 세지 않는다
    if info['days_expected'] <= 0:
        return dict(info, reason='too-early')

    channels = _plot_temperature_channels(plot)
    info['sensor_count'] = len(channels)
    if not channels:
        return dict(info, reason='no-temperature-sensor')

    start_ts = start.isoformat() + 'T00:00:00Z'
    end_ts = (end + timedelta(days=1)).isoformat() + 'T00:00:00Z'

    # 채널이 여럿이면 **날마다 평균**한다. 최고끼리·최저끼리 평균하는 것이라
    # 한 센서의 이상값이 그날을 통째로 끌고 가지 않는다.
    per_day = {}
    for did, ch in channels:
        for day, (tmax, tmin) in _daily_extremes(
                did, ch, _GDD_TEMP_MEASURE, start_ts, end_ts).items():
            if day < start or day > end:
                continue
            acc = per_day.setdefault(day, [[], []])
            acc[0].append(tmax)
            acc[1].append(tmin)

    total = 0.0
    series = []
    for day in sorted(per_day):
        maxes, mins = per_day[day]
        t_avg = (sum(maxes) / len(maxes) + sum(mins) / len(mins)) / 2.0
        gain = max(0.0, t_avg - t_base)
        total += gain
        series.append((day, gain))

    # 계열은 **요청할 때만** 싣는다. 몇 달치면 수백 항목이라 응답에 그대로
    # 들어가면 모달 페이로드가 부풀고, 화면은 그 값을 쓰지도 않는다.
    # 쓰는 곳은 하나다 — 단계가 넘어간 **날짜**를 되짚는 자리(P7 자동 승인).
    if with_series:
        info['series'] = series

    info['days_counted'] = len(per_day)
    info['value'] = round(total, 1)
    info['coverage_pct'] = round(
        100.0 * len(per_day) / info['days_expected'], 1)

    if len(per_day) < info['days_expected'] * _GDD_MIN_COVERAGE:
        return dict(info, reason='low-coverage')
    return dict(info, usable=True)


# ── 단계 전환 원장 (P5) ────────────────────────────────────────────────────
#
# 승인은 기록이 아니라 **보정**이다 — 확인된 전환 날짜부터 남은 단계를 다시
# 계산한다. 정본: docs/design/program-layer.md §P5


def _anchor_of(row):
    return {'unique_id': row.unique_id, 'stage_key': row.stage_key,
            'stage_index': row.stage_index, 'started_on': row.started_on,
            'source': row.source, 'decided_at': row.decided_at,
            'decided_by': row.decided_by}


def stage_events_for(plot_uuids):
    """여러 구획의 전환 원장을 **한 번에** → `{plot_uuid: [row, ...]}`.

    기준점(`stage_anchors_for`)과 이력(`stage_history`)이 같은 표를 읽으므로
    한 번만 읽어 둘 다 여기서 파생시킨다 — 따로 읽으면 구획당 두 번이 된다.
    무른 행도 담는다(이력이 그것을 낸다). 표가 없는 설치에서는 빈 dict.
    """
    from aot.databases.models import GeoPlotStageEvent

    uuids = [u for u in (plot_uuids or []) if u]
    out = {u: [] for u in uuids}
    if not uuids:
        return out
    try:
        rows = (GeoPlotStageEvent.query
                .filter(GeoPlotStageEvent.plot_uuid.in_(uuids))
                .all())
    except Exception:
        return out
    for row in rows:
        out.setdefault(row.plot_uuid, []).append(row)
    return out


def stage_anchors_for(plot_uuids, events=None):
    """여러 구획의 기준점을 **한 번에** → `{plot_uuid: dict|None}`.

    `stage_anchor` 는 구획마다 원장을 한 번씩 읽는다. 목록은 그것을 구획 수만큼
    반복하는데, `to_dict` 안에서 `stage_schedule` 과 `stage_proposal` 이 각각
    부르므로 **구획당 두 번**이다(라즈베리파이 실측: 구획 24개에 44쿼리).
    원시 SQL 시간은 작아도 ORM 왕복이 쌓인다 — 같은 실측에서 쿼리 95건이
    290ms 중 108ms 를 썼다.

    **키가 없는 것과 값이 None 인 것은 같은 뜻이다**(그 구획에 원장이 없음).
    호출부가 렌더할 구획 전체를 넘기는 것을 전제로 한다.
    """
    uuids = [u for u in (plot_uuids or []) if u]
    out = {u: None for u in uuids}
    if not uuids:
        return out
    if events is None:
        events = stage_events_for(uuids)
    best = {}
    for uuid in uuids:
        for row in events.get(uuid) or []:
            if row.undone_at is not None:
                continue             # 무른 행은 기준점이 되지 않는다
            key = (row.started_on, row.stage_index, row.id)
            cur = best.get(uuid)
            if cur is None or key > cur[0]:
                best[uuid] = (key, row)
    for uuid, (_key, row) in best.items():
        out[uuid] = _anchor_of(row)
    return out


def stage_anchor(plot, anchors=None):
    """이 구획의 기준점 → dict|None.

    "안 무른 행 중 가장 늦게 시작된 것". 원장이 비면 None 이고, 그때 기준점은
    시작일이다(기존 구획에 소급해서 승인을 요구하지 않는다).

    **`started_on` 으로 고른다, `decided_at` 이 아니다.** 사흘 뒤에 확인해도 단계는
    사흘 전에 시작됐고, 나중에 과거 전환을 뒤늦게 적을 수도 있다.

    `anchors`(`stage_anchors_for` 의 결과)가 있고 이 구획이 그 안에 있으면 그것을
    쓴다 — 구획을 여럿 도는 자리는 그렇게 넘길 것.
    """
    from aot.databases.models import GeoPlotStageEvent

    uuid = getattr(plot, 'unique_id', None)
    if not uuid:
        return None
    if anchors is not None and uuid in anchors:
        return anchors[uuid]
    try:
        rows = (GeoPlotStageEvent.query
                .filter_by(plot_uuid=uuid)
                .filter(GeoPlotStageEvent.undone_at.is_(None))
                .all())
    except Exception:
        return None                      # 표가 없는 설치 — 종전대로 파생한다
    if not rows:
        return None
    row = max(rows, key=lambda r: (r.started_on, r.stage_index, r.id))
    return _anchor_of(row)


def stage_history(plot, events=None):
    """이 구획의 전환 이력(무른 것 포함) — 시작일 오름차순.

    무른 행도 낸다. "확인했다가 물렀다" 는 사실 자체가 이력이고, 숨기면 같은
    판단을 다시 하게 된다.

    `events`(`stage_events_for` 의 결과)가 있으면 그것을 쓴다 — 구획을 여럿
    도는 자리는 넘길 것.
    """
    from aot.databases.models import GeoPlotStageEvent

    uuid = getattr(plot, 'unique_id', None)
    if not uuid:
        return []
    if events is not None:
        rows = list(events.get(uuid) or [])
    else:
        try:
            rows = GeoPlotStageEvent.query.filter_by(plot_uuid=uuid).all()
        except Exception:
            return []
    rows.sort(key=lambda r: (r.started_on, r.id))
    return [{'unique_id': r.unique_id, 'stage_key': r.stage_key,
             'stage_index': r.stage_index,
             'started_on': r.started_on.isoformat() if r.started_on else None,
             'source': r.source,
             'decided_by': r.decided_by,
             'auto': bool(getattr(r, 'auto', False)),
             'undone': r.undone_at is not None} for r in rows]


def stage_proposal(plot, program=None, on=None, assume_start=False, anchors=None,
                   sched=None):
    """대기 중인 전환 제안 → dict|None. **저장하지 않는다.**

    기준점 이후로 계산한 단계가 기준점보다 앞서 있으면 그것이 제안이다. 행으로
    만들면 프로그램을 고치거나 GDD 가 밀릴 때 조용히 낡고, 아무도 보지 않는
    구획을 위해 배경 잡이 필요해진다 — 읽을 때 계산한다.

    **원장이 비어 있으면 제안하지 않는다.** 승인은 사람이 한 번 누른 시점부터
    의미를 갖는다(기존 구획 전부에 "승인하세요" 를 띄우지 않는다).

    `assume_start` 는 그 규칙의 **자동 승인 전용 예외**다(P8). 자동 승인을 켠
    구획은 배너를 띄우지 않고 조용히 기록하므로 "소급해서 승인을 요구한다" 는
    문제가 없고, 켜 두었는데 첫 전환이 영영 기록되지 않으면 그 사람은 기능이
    꺼진 것으로 본다. 이때 기준점은 시작일(1단계)로 친다.
    """
    anchor = stage_anchor(plot, anchors=anchors)
    if not anchor:
        if not (assume_start and getattr(plot, 'auto_advance', False)):
            return None

    if sched is None:
        sched = stage_schedule(plot, program=program, on=on)
    if sched is None:
        return None
    from_index = int((anchor or {}).get('stage_index') or 1)
    from_key = ((anchor or {}).get('stage_key')
                or (sched['boundaries'][0].get('key') if sched['boundaries']
                    else None))

    # **고정을 풀고 본다**(`gated=False`) — 제안은 "파생이 앞서갔다" 는 사실
    # 자체라, 고정된 값을 보면 영영 뜨지 않는다.
    st = stage_of(plot, program=program, on=on, gated=False, sched=sched)
    if not st or st.get('state') != 'running':
        return None
    # `stage_of` 의 `index` 는 이미 **전체 기준**이다(기준점 이후 구간으로 잘라
    # 계산하되 순번은 프로그램 전체로 낸다). 여기서 또 더하면 두 번 보정된다.
    idx = st.get('index') or 1
    if idx <= from_index:
        return None
    return {'stage_key': st.get('key'), 'stage_index': idx,
            'stage_name': st.get('name'),
            'from_key': from_key,
            'from_index': from_index,
            'source': st.get('source'),
            # 언제부터였나 — 승인하면 이 날이 새 기준점이 된다. 사람이 화면에서
            # 고칠 수 있어야 한다(관찰과 계산이 다를 수 있다).
            'started_on': _proposed_start(plot, st, on=on)}


def _proposed_start(plot, st, on=None):
    """제안된 단계가 시작된 날(추정) → ISO 문자열|None.

    GDD 판정이면 누적이 임계를 넘어선 날을 되짚어 쓴다 — **관찰 시점과 무관해야
    한다.** 아무도 안 본 사이에 넘어갔는데 "오늘" 로 적으면 자동 승인(P7)의 기록이
    언제 열어 봤는지에 따라 달라진다.

    날짜 판정이면 "지금 단계에 들어온 지 N일" 을 거꾸로 센다. 둘 다 없으면 오늘로
    두고 사람이 화면에서 고친다(지어낸 날짜를 기록에 남기지 않는다).
    """
    from datetime import timedelta

    # GDD 판정은 누적이 임계를 넘어선 날을 되짚어 둔다(`_gdd_crossed_on`).
    # 그것이 있으면 그 날이 정답이다 — 관찰 시점과 무관하다.
    if st.get('started_on'):
        return st['started_on']

    today = on or date.today()
    n = st.get('day_in_stage')
    if isinstance(n, int) and n > 0:
        return (today - timedelta(days=n - 1)).isoformat()
    return today.isoformat()


def stage_resources(stage, program_row=None, plot=None):
    """이 단계의 자원 → **선언(역할)과 현장(찾은 함수)을 나란히** 낸 목록.

    ## 프로그램은 역할만 말하고, 현장이 함수를 답한다 (2026-08-20 재설계)

    예전에는 단계가 함수 uuid 를 들고 있었다(`stages[].functions`). 그러면
    프로그램이 템플릿이기를 그만둔다 — 두 번째 온실에서 쓰려면 복제해야 하고,
    복제한 순간 작물 지식이 두 벌이 되어 한쪽만 고쳐진다. 게다가 그 uuid 로
    함수를 켜는 일에는 아무 맥락도 실리지 않았다(`_set_function_activation` 은
    전역 스위치다) — 두 구획이 같은 함수를 선언하면 두 번째 [적용]은 무동작이고
    어느 쪽 현장 데이터도 거동을 바꾸지 못했다.

    ## 이 기능의 값은 자동화가 아니라 **대조**다

    "이 단계에는 시비가 돌아야 하는데 꺼져 있다" 는 사람이 지금 알 수 없는
    사실이고, 알면 바로 고칠 수 있다. 프로그램이 함수를 스스로 켜고 끄는 것보다
    어긋남을 보이는 것이 먼저다 — 관수를 켜는 것은 물이 나오는 일이라
    `activate_function` 이 승인 대상인 것과 같은 이유다.

    재설계로 **말할 수 있는 사실이 하나 늘었다**: 예전에는 "지목한 함수가 꺼져
    있다" 까지였고, 이제는 "이 단계는 관수를 요구하는데 이 자리에 관수 함수가
    아예 없다" 를 말한다. 후자가 실제로 더 자주 일어나는 사고인데 예전 구조에는
    그것을 표현할 자리가 없었다.

    ## 없음은 조용히 넘기지 않는다

    찾지 못하면 목록에서 빼는 것이 아니라 `found: False` + `reason` 으로 남긴다.
    빼면 그 단계에서 자원이 통째로 사라진 것을 아무도 모른다(옛 구조의 "죽은
    참조를 지우지 않는다" 와 같은 원칙이 자리를 옮긴 것이다).
    """
    roles = declared_roles(stage, program_row)
    if not roles:
        return []

    out = []
    for entry in roles:
        role = entry['role']
        fns, reason = functions_for_role(role, plot)
        out.append({
            'role': role,
            'source': entry['source'],      # 'stage' | 'default'
            'functions': fns,
            'found': bool(fns),
            'reason': reason,
            # 하나라도 돌고 있으면 "작동 중" 이다. 여럿이 잡히는 것은 정상이다
            # (밸브가 여럿인 시설) — 무엇이 지금 도는지는 목록이 말한다.
            'active': any(f.get('active') for f in fns) if fns else None,
        })
    return out
