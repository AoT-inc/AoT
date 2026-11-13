# coding=utf-8
"""
facility_layout.py — 시설 모형 `층 → 덩어리 → 공간` (설계: 시설 모형 구조 확장 제안, 단계 F0).

Flask·DB 를 쓰지 않는 순수 함수만 둔다. 입력과 출력은 JSON 으로 직렬화되는
dict/list 뿐이다. F0 는 **읽을 때 변환**만 한다 — `geo_facility.layout` 칸도,
라우트도, 화면도, 기존 소비자의 변경도 없다. 기존 시설은 `layout_from_legacy()`
가 `geometry_3d` 와 구역 메타에서 같은 뜻의 모형을 만든다.

공개 함수
---------
validate_layout(layout)        스키마 1 검증. 오류 목록(빈 목록이면 유효).
layout_from_legacy(facility)   기존 시설 값 → 층 1·덩어리 N·공간 N 모형.
compile_layout(layout, envelope=None)  공간별 면적·체적·외피·내부 경계, 공기 구획(F4), 시설 합계.
locate(layout, x, y, z)        높이로 층, 평면으로 공간을 찾는다.
footprint_points(layout, step_m=None)  덩어리 외곽의 표본점(지형 단계용).
footprint_union(layout)        전 층 외형의 합집합(F3, 시설 도형 유도).
footprint_geometry(...)        합집합 → 지도 도형 GeoJSON(F3).
recenter(...)                  모형 박스가 바뀌어도 로컬 원점이 지도에서 그대로 있는 새 중심(F3).
layout_zones(layout, envelope) 화면에 보일 구역 목록(F3, 표시 전용 — 제어 경로가 아니다).
locate_fittings(layout, fs)    fitting → 공간 id(층까지 보는 기본 locate).
location_changes(old, new, fs) 모형을 바꾸면 구역이 달라지는 장치 목록(F3).

좌표계
------
기존 fitting 과 같은 **시설 로컬 미터**다. 평면 점은 `[x, z]`, 높이는 `y`.
  · x : 폭(span) 방향. `x = 0` 은 가장 서쪽 동(棟) 바깥 벽선이다.
  · z : 길이 방향. `z = 0` 은 동의 한쪽 끝 벽선, `z = length_m` 이 반대쪽이다.
  · y : 높이. `y = 0` 은 바닥.
  시설 중심(`geometry_3d.center_lng/lat`)은 로컬 `(총폭/2, 길이/2)` 에 놓이고
  `orientation_deg` 회전은 이 모듈이 적용하지 않는다(지도 변환은 호출자 몫,
  `facility_bays.slice_geometry` 참조).

스키마 1 (요약)
--------------
{
  "schema": 1,
  "levels":  [{"id","name","elevation_m","height_m"}],
  "blocks":  [{"id","level_id","outline":[[x,z],...],
               "roof":  {"type": "flat|arch|gable|gable2", "rise_m", "ridge_axis": "x|z", "runs"},
               "walls": {"cover": <facility_calc.MATERIALS 키>},
               "spans": 1}],
  "spaces":  [{"id","block_id","name","crop","outline"?,"block_ids"?}],
  "boundaries": [{"between": [space_id, space_id], "type": "wall|curtain|open"}],
  "voids":   [{"level_id","outline"}],
  "id_seq":  {"L": n, "B": n}
}
  · `id_seq` 는 편집기가 쓴 층·덩어리 번호의 장부다(번호를 다시 쓰지 않는다). 계산은 읽지 않는다.
  · `space.capacity` 는 구역 총량이다. `/bay_capacity` 만 쓰고 저장은 저장된 값을 잇는다
    (`merged_capacity`). 편집본의 값은 믿지 않는다.
  · `level.height_m` 는 **처마까지의 벽 높이**다. 지붕 상승(`rise_m`)은 그 위에 얹힌다.
  · `roof.runs` 는 폭 방향으로 반복되는 용마루 수다(연동 N동 = N). 곡면·박공 지붕은
    직사각형 덩어리에만 둘 수 있고, `ridge_axis` 방향으로 용마루가 달린다(기본 `z`).
  · `space.outline` 을 생략하면 덩어리 전체가 그 공간이다(그 덩어리에 공간이 하나일 때).
    `block_ids` 는 한 공간이 여러 덩어리에 걸칠 때(기존 분리동 구역) 쓴다.
  · `spaces` 를 통째로 생략하면 덩어리마다 공간 1개가 암묵적으로 생긴다.

외피 유도 (제안 §3 규칙 1·2)
----------------------------
외벽 = 덩어리 외곽선 중 같은 층의 다른 덩어리와 맞닿지 않은 부분 × 벽 높이.
지붕 = 바로 위층 덩어리가 덮지 않은 윗면. 공간 경계는 벽·커튼·열림 중 하나이며
선언하지 않은 맞닿음은 벽이다.

기존 `facility_calc.compute_capacity` 와의 알려진 차이 두 가지
--------------------------------------------------------------
1. 연동(connected) N동의 박공 단면: 기존은 양 끝 2개만 세고, 여기서는 동마다
   삼각(박공) 단면이 있으므로 2N 개를 센다(`gable_m2`, `envelope_m2` 가 그만큼 크다).
2. `glazing_m2`: 기존은 외피 전부를 투광면으로 가정(PoC). 여기서는 덮개의
   투과율이 0 인 재질(샌드위치 패널·불투명 필름)이면 0 으로 센다.
회귀 스크립트(`aot/scripts/check_facility_layout_regression.py`)가 두 차이를
정확한 관계식으로 확인하고 '알려진 차이'로 따로 센다.

@phase active
"""
import math

from .facility_calc import (
    DEFAULT_MATERIAL,
    MATERIALS,
    roof_section_area,
    roof_section_perimeter,
)

SCHEMA_VERSION = 1

ROOF_TYPES = ('flat', 'arch', 'gable', 'gable2')
BOUNDARY_TYPES = ('wall', 'curtain', 'open')

# locate(): 공간 범위 밖이어도 이 거리 안이면 가장 가까운 공간으로 귀속한다.
# `facility_bays._EDGE_TOLERANCE_M` 과 같은 값(벽체 두께·배치 스냅 오차 흡수).
EDGE_TOLERANCE_M = 1.0
NAME_MAX = 200

# 위층 바닥판 두께(m). 윗층 elevation_m = 아래층 elevation_m + height_m + SLAB_T_M.
# `core/layout-mesh.js` 의 SLAB_T, `geo/facility/layout-edit.js` 의 SLAB_T 와 같은 값이다.
SLAB_T_M = 0.2

_EPS = 1e-6
_LEGACY_DEFAULTS = {'span_width_m': 7.0, 'eave_height_m': 2.0,
                    'ridge_height_m': 4.0, 'length_m': 30.0}


# ----------------------------------------------------------------
# 평면 기하 도우미
# ----------------------------------------------------------------
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_point(p):
    return isinstance(p, (list, tuple)) and len(p) == 2 and _num(p[0]) and _num(p[1])


def _is_ring(r):
    return isinstance(r, (list, tuple)) and len(r) >= 3 and all(_is_point(p) for p in r)


def _signed_area(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        s += x1 * z2 - x2 * z1
    return s / 2.0


def _area(ring):
    return abs(_signed_area(ring))


def _centroid(ring):
    a = _signed_area(ring)
    n = len(ring)
    if abs(a) < _EPS:
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    cx = cz = 0.0
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        f = x1 * z2 - x2 * z1
        cx += (x1 + x2) * f
        cz += (z1 + z2) * f
    return (cx / (6 * a), cz / (6 * a))


def _edges(ring):
    n = len(ring)
    return [(tuple(ring[i]), tuple(ring[(i + 1) % n])) for i in range(n)]


def _perimeter(ring):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in _edges(ring))


def _is_convex(ring):
    n = len(ring)
    sign = 0
    for i in range(n):
        a, b, c = ring[i], ring[(i + 1) % n], ring[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < _EPS:
            continue
        s = 1 if cr > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _clip_convex(subject, clip):
    """Sutherland–Hodgman. `clip` 은 볼록이어야 한다. 결과 링(없으면 [])."""
    if _signed_area(clip) < 0:
        clip = list(reversed(clip))
    out = [tuple(p) for p in subject]
    for a, b in _edges(clip):
        if not out:
            break
        inp, out = out, []
        for i in range(len(inp)):
            cur, prev = inp[i], inp[i - 1]
            side_c = (b[0] - a[0]) * (cur[1] - a[1]) - (b[1] - a[1]) * (cur[0] - a[0])
            side_p = (b[0] - a[0]) * (prev[1] - a[1]) - (b[1] - a[1]) * (prev[0] - a[0])
            if side_c >= -_EPS:
                if side_p < -_EPS:
                    out.append(_isect(prev, cur, a, b))
                out.append(cur)
            elif side_p >= -_EPS:
                out.append(_isect(prev, cur, a, b))
    return out


def _isect(p1, p2, a, b):
    d1 = (p2[0] - p1[0], p2[1] - p1[1])
    d2 = (b[0] - a[0], b[1] - a[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return p2
    t = ((a[0] - p1[0]) * d2[1] - (a[1] - p1[1]) * d2[0]) / den
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def _overlap_area(a, b, warnings=None, tag=''):
    """두 다각형의 겹친 넓이. 둘 다 오목이면 계산하지 못해 0 과 경고."""
    if _is_convex(b):
        r = _clip_convex(a, b)
    elif _is_convex(a):
        r = _clip_convex(b, a)
    else:
        if warnings is not None:
            warnings.append({'code': 'non_convex_overlap', 'message': '오목한 두 평면의 겹침을 계산하지 못함 %s' % tag})
        return 0.0
    return _area(r) if len(r) >= 3 else 0.0


def _point_in_ring(pt, ring):
    """경계 포함 점-다각형 판정."""
    x, z = pt
    inside = False
    n = len(ring)
    for i in range(n):
        x1, z1 = ring[i]
        x2, z2 = ring[(i + 1) % n]
        if _seg_dist(pt, (x1, z1), (x2, z2)) < 1e-9:
            return True
        if (z1 > z) != (z2 > z):
            xi = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
            if x < xi:
                inside = not inside
    return inside


def _seg_dist(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dz * dz
    if L2 < 1e-18:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dz))


def _dist_to_ring(pt, ring):
    if _point_in_ring(pt, ring):
        return 0.0
    return min(_seg_dist(pt, a, b) for a, b in _edges(ring))


def _overlap_len(e1, e2):
    """두 선분이 한 직선 위에서 겹치는 길이(평행·공선이 아니면 0)."""
    (ax, az), (bx, bz) = e1
    (cx, cz), (dx, dz) = e2
    ux, uz = bx - ax, bz - az
    L = math.hypot(ux, uz)
    if L < _EPS:
        return 0.0
    ux, uz = ux / L, uz / L
    # 두 끝점이 e1 직선에서 떨어진 거리
    if (abs((cx - ax) * uz - (cz - az) * ux) > 1e-6 or
            abs((dx - ax) * uz - (dz - az) * ux) > 1e-6):
        return 0.0
    t1 = (cx - ax) * ux + (cz - az) * uz
    t2 = (dx - ax) * ux + (dz - az) * uz
    lo, hi = max(0.0, min(t1, t2)), min(L, max(t1, t2))
    return max(hi - lo, 0.0)


def _hull(points):
    pts = sorted(set((round(p[0], 9), round(p[1], 9)) for p in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _segments_cross(a, b, c, d):
    """내부에서 엇갈리는지(끝점만 닿는 것은 제외)."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _self_intersects(ring):
    es = _edges(ring)
    n = len(es)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(es[i][0], es[i][1], es[j][0], es[j][1]):
                return True
    return False


def _is_rect(ring):
    """축에 나란한 직사각형인지(꼭짓점 4개)."""
    if len(ring) != 4:
        return False
    xs = sorted(set(round(p[0], 6) for p in ring))
    zs = sorted(set(round(p[1], 6) for p in ring))
    return len(xs) == 2 and len(zs) == 2 and abs(_area(ring) - (xs[1] - xs[0]) * (zs[1] - zs[0])) < 1e-6


# ----------------------------------------------------------------
# 검증
# ----------------------------------------------------------------
def _check_name(item, path, err):
    """이름은 없거나 문자열이다. 층·구역 이름은 화면 곳곳에 그대로 나간다."""
    name = item.get('name')
    if name is not None and (not isinstance(name, str) or len(name) > NAME_MAX):
        err('bad_name', path + '.name', '이름은 %d자 이하 문자열이어야 한다' % NAME_MAX)


def validate_layout(layout):
    """스키마 1 검증. 오류 `[{'code','path','message'}]` 목록을 돌려준다(빈 목록 = 유효).

    기하(겹침·덮임)의 의미 검사는 하지 않고, 계산이 깨지는 구조 오류만 막는다.
    """
    errs = []

    def err(code, path, msg):
        errs.append({'code': code, 'path': path, 'message': msg})

    if not isinstance(layout, dict):
        err('not_object', '', 'layout 은 객체여야 한다')
        return errs
    if layout.get('schema') != SCHEMA_VERSION:
        err('bad_schema', 'schema', 'schema 는 %d 이어야 한다' % SCHEMA_VERSION)

    # ── levels ──
    levels = layout.get('levels')
    level_idx = {}
    if not isinstance(levels, list) or not levels:
        err('levels_required', 'levels', '층이 하나 이상 있어야 한다')
        levels = []
    for i, lv in enumerate(levels):
        p = 'levels[%d]' % i
        if not isinstance(lv, dict):
            err('bad_level', p, '층은 객체여야 한다')
            continue
        _check_name(lv, p, err)
        lid = lv.get('id')
        if not isinstance(lid, str) or not lid:
            err('bad_id', p + '.id', '층 id 는 비어 있지 않은 문자열이어야 한다')
        elif lid in level_idx:
            err('duplicate_id', p + '.id', '층 id 중복: %s' % lid)
        else:
            level_idx[lid] = i
        if not _num(lv.get('elevation_m')):
            err('bad_number', p + '.elevation_m', 'elevation_m 은 숫자여야 한다')
        h = lv.get('height_m')
        if not _num(h) or h <= 0:
            err('bad_number', p + '.height_m', 'height_m 은 0 보다 큰 숫자여야 한다')
    ok_lv = [lv for lv in levels if isinstance(lv, dict) and _num(lv.get('elevation_m'))
             and _num(lv.get('height_m')) and lv.get('height_m') > 0]
    ok_lv.sort(key=lambda lv: lv['elevation_m'])
    for a, b in zip(ok_lv, ok_lv[1:]):
        if a['elevation_m'] + a['height_m'] > b['elevation_m'] + _EPS:
            err('level_overlap', 'levels', '층이 겹친다: %s / %s' % (a.get('id'), b.get('id')))

    # ── blocks ──
    blocks = layout.get('blocks')
    block_ids = {}
    if not isinstance(blocks, list) or not blocks:
        err('blocks_required', 'blocks', '덩어리가 하나 이상 있어야 한다')
        blocks = []
    order = sorted(level_idx, key=lambda k: levels[level_idx[k]].get('elevation_m')
                   if _num(levels[level_idx[k]].get('elevation_m')) else 0)
    rank = {lid: r for r, lid in enumerate(order)}
    for i, b in enumerate(blocks):
        p = 'blocks[%d]' % i
        if not isinstance(b, dict):
            err('bad_block', p, '덩어리는 객체여야 한다')
            continue
        bid = b.get('id')
        if not isinstance(bid, str) or not bid:
            err('bad_id', p + '.id', '덩어리 id 는 비어 있지 않은 문자열이어야 한다')
        elif bid in block_ids:
            err('duplicate_id', p + '.id', '덩어리 id 중복: %s' % bid)
        else:
            block_ids[bid] = b
        if b.get('level_id') not in level_idx:
            err('unknown_level', p + '.level_id', '없는 층: %s' % b.get('level_id'))
        outline = b.get('outline')
        ring_ok = _is_ring(outline)
        if not ring_ok:
            err('bad_outline', p + '.outline', '외곽은 [x,z] 점 3개 이상이어야 한다')
        elif _self_intersects(outline):
            err('self_intersecting_outline', p + '.outline', '외곽이 스스로 교차한다')
        elif _area(outline) < _EPS:
            err('degenerate_outline', p + '.outline', '외곽 넓이가 0 이다')
        roof = b.get('roof') or {}
        if not isinstance(roof, dict):
            err('bad_roof', p + '.roof', 'roof 는 객체여야 한다')
            roof = {}
        rt = str(roof.get('type') or 'flat').lower()
        if rt not in ROOF_TYPES:
            err('bad_roof_type', p + '.roof.type', '지붕 종류는 %s 중 하나' % '/'.join(ROOF_TYPES))
        if 'rise_m' in roof and (not _num(roof['rise_m']) or roof['rise_m'] < 0):
            err('bad_number', p + '.roof.rise_m', 'rise_m 은 0 이상의 숫자여야 한다')
        runs = roof.get('runs', 1)
        if isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
            err('bad_number', p + '.roof.runs', 'runs 는 1 이상의 정수여야 한다')
        if roof.get('ridge_axis', 'z') not in ('x', 'z'):
            err('bad_roof', p + '.roof.ridge_axis', 'ridge_axis 는 x 또는 z')
        if rt != 'flat' and ring_ok and not _is_rect(outline):
            err('curved_roof_needs_rect', p + '.roof', '곡면·박공 지붕은 축에 나란한 직사각형 덩어리에만 둘 수 있다')
        walls = b.get('walls') or {}
        cover = walls.get('cover') if isinstance(walls, dict) else None
        if cover is not None and cover not in MATERIALS:
            err('unknown_cover', p + '.walls.cover', '알 수 없는 덮개 재질: %s' % cover)
        spans = b.get('spans', 1)
        if isinstance(spans, bool) or not isinstance(spans, int) or spans < 1:
            err('bad_number', p + '.spans', 'spans 는 1 이상의 정수여야 한다')
        elif b.get('level_id') in rank and rank[b['level_id']] + spans > len(order):
            err('spans_out_of_levels', p + '.spans', 'spans 가 층 수를 넘는다')

    # ── spaces ──
    spaces = layout.get('spaces')
    space_ids = set()
    if spaces is None:
        spaces = []
    if not isinstance(spaces, list):
        err('bad_spaces', 'spaces', 'spaces 는 목록이어야 한다')
        spaces = []
    uses = {}          # block_id → 그 덩어리를 쓰는 공간 id 목록
    nooutline_blocks = {}
    for i, s in enumerate(spaces):
        p = 'spaces[%d]' % i
        if not isinstance(s, dict):
            err('bad_space', p, '공간은 객체여야 한다')
            continue
        _check_name(s, p, err)
        sid = s.get('id')
        if not isinstance(sid, str) or not sid:
            err('bad_id', p + '.id', '공간 id 는 비어 있지 않은 문자열이어야 한다')
        elif sid in space_ids:
            err('duplicate_id', p + '.id', '공간 id 중복: %s' % sid)
        else:
            space_ids.add(sid)
        bid = s.get('block_id')
        bids = s.get('block_ids')
        if bids is not None:
            if (not isinstance(bids, list) or not bids or
                    any(x not in block_ids for x in bids) or (bid is not None and bid not in bids)):
                err('unknown_block', p + '.block_ids', 'block_ids 가 없는 덩어리를 가리킨다')
                bids = None
            elif s.get('outline') is not None:
                err('outline_with_block_ids', p + '.outline', 'block_ids 가 있으면 outline 을 둘 수 없다')
            else:
                levels_of = set(block_ids[x].get('level_id') for x in bids)
                if len(levels_of) > 1:
                    err('space_multi_level', p + '.block_ids', '한 공간의 덩어리는 같은 층이어야 한다')
        if bid not in block_ids and bids is None:
            err('unknown_block', p + '.block_id', '없는 덩어리: %s' % bid)
            continue
        used = bids if bids else [bid]
        outline = s.get('outline')
        if outline is not None:
            if not _is_ring(outline) or _area(outline) < _EPS:
                err('bad_outline', p + '.outline', '공간 외곽이 올바르지 않다')
            elif bid in block_ids and _is_ring(block_ids[bid].get('outline')):
                bo = block_ids[bid]['outline']
                if any(_dist_to_ring(tuple(v), bo) > 1e-6 for v in outline):
                    err('space_outside_block', p + '.outline', '공간 외곽이 덩어리 밖으로 나간다')
        for b_ in used:
            uses.setdefault(b_, []).append(sid)
            if outline is None:
                nooutline_blocks.setdefault(b_, []).append(sid)
    for b_, lst in nooutline_blocks.items():
        if len(uses.get(b_, [])) > 1:
            err('outline_required', 'spaces', '덩어리 %s 에 공간이 여럿이면 모두 outline 이 있어야 한다' % b_)
    for b_, lst in uses.items():
        b = block_ids.get(b_)
        if not b or not _is_ring(b.get('outline')):
            continue
        tot = 0.0
        for s in spaces:
            if isinstance(s, dict) and s.get('id') in lst and _is_ring(s.get('outline')):
                tot += _area(s['outline'])
        if tot > _area(b['outline']) + 0.01:
            err('spaces_overlap', 'spaces', '덩어리 %s 안 공간 넓이의 합이 덩어리보다 크다(겹침)' % b_)
    # 암묵 공간 id 와 충돌
    for b_ in block_ids:
        if b_ not in uses and _implicit_space_id(b_) in space_ids:
            err('duplicate_id', 'spaces', '암묵 공간 id 와 충돌: %s' % _implicit_space_id(b_))

    # ── boundaries ──
    all_space_ids = set(space_ids) | {_implicit_space_id(b_) for b_ in block_ids if b_ not in uses}
    bounds = layout.get('boundaries') or []
    if not isinstance(bounds, list):
        err('bad_boundaries', 'boundaries', 'boundaries 는 목록이어야 한다')
        bounds = []
    seen = set()
    for i, bd in enumerate(bounds):
        p = 'boundaries[%d]' % i
        if not isinstance(bd, dict):
            err('bad_boundary', p, '경계는 객체여야 한다')
            continue
        bt = bd.get('between')
        if (not isinstance(bt, list) or len(bt) != 2 or bt[0] == bt[1]
                or bt[0] not in all_space_ids or bt[1] not in all_space_ids):
            err('bad_boundary', p + '.between', 'between 은 서로 다른 두 공간 id 여야 한다')
        else:
            key = frozenset(bt)
            if key in seen:
                err('duplicate_boundary', p, '같은 두 공간의 경계가 중복이다')
            seen.add(key)
        if bd.get('type') not in BOUNDARY_TYPES:
            err('bad_boundary_type', p + '.type', '경계 종류는 %s 중 하나' % '/'.join(BOUNDARY_TYPES))

    # ── voids ──
    voids = layout.get('voids') or []
    if not isinstance(voids, list):
        err('bad_voids', 'voids', 'voids 는 목록이어야 한다')
        voids = []
    for i, v in enumerate(voids):
        p = 'voids[%d]' % i
        if not isinstance(v, dict) or v.get('level_id') not in level_idx:
            err('unknown_level', p + '.level_id', '없는 층')
        elif not _is_ring(v.get('outline')) or _area(v['outline']) < _EPS:
            err('bad_outline', p + '.outline', '구멍 외곽이 올바르지 않다')
    return errs


def _implicit_space_id(block_id):
    return 'space_' + block_id


# ----------------------------------------------------------------
# 내부 정리 — 검증을 통과한 모형을 계산하기 좋은 꼴로
# ----------------------------------------------------------------
def _prep(layout, default_cover=DEFAULT_MATERIAL):
    levels = sorted(layout['levels'], key=lambda lv: lv['elevation_m'])
    lv_by_id = {lv['id']: lv for lv in levels}
    lv_rank = {lv['id']: i for i, lv in enumerate(levels)}
    blocks = {}
    for b in layout['blocks']:
        spans = int(b.get('spans') or 1)
        r = lv_rank[b['level_id']]
        top_lv = levels[min(r + spans - 1, len(levels) - 1)]
        base = lv_by_id[b['level_id']]
        roof = b.get('roof') or {}
        blocks[b['id']] = {
            'id': b['id'], 'level_id': b['level_id'], 'rank': r, 'spans': spans,
            'outline': [tuple(p) for p in b['outline']],
            'wall_h': top_lv['elevation_m'] + top_lv['height_m'] - base['elevation_m'],
            'roof_type': str(roof.get('type') or 'flat').lower(),
            'rise': float(roof.get('rise_m') or 0.0),
            'runs': int(roof.get('runs') or 1),
            'ridge_axis': roof.get('ridge_axis') or 'z',
            'cover': (b.get('walls') or {}).get('cover') or default_cover,
        }
    spaces = []
    used_blocks = set()
    for s in layout.get('spaces') or []:
        bids = s.get('block_ids') or [s['block_id']]
        if s.get('outline') is not None:
            parts = [(s['block_id'], [tuple(p) for p in s['outline']])]
        else:
            parts = [(x, blocks[x]['outline']) for x in bids]
        used_blocks.update(bids)
        spaces.append({'id': s['id'], 'name': s.get('name'), 'crop': s.get('crop'),
                       'block_id': s['block_id'], 'parts': parts})
    for b in layout['blocks']:
        if b['id'] not in used_blocks:
            spaces.append({'id': _implicit_space_id(b['id']), 'name': b.get('name'), 'crop': None,
                           'block_id': b['id'], 'parts': [(b['id'], blocks[b['id']]['outline'])]})
    for sp in spaces:
        sp['level_id'] = blocks[sp['block_id']]['level_id']
        sp['rank_lo'] = min(blocks[x]['rank'] for x, _ in sp['parts'])
        sp['rank_hi'] = max(blocks[x]['rank'] + blocks[x]['spans'] - 1 for x, _ in sp['parts'])
    return levels, lv_by_id, lv_rank, blocks, spaces


def _cover_u(cover):
    return MATERIALS.get(cover, MATERIALS[DEFAULT_MATERIAL])['u']


def _transparent(cover):
    return MATERIALS.get(cover, MATERIALS[DEFAULT_MATERIAL])['transmittance'] > 0


def _roof_dims(b):
    """직사각형 덩어리의 지붕 치수 → (run 폭, 용마루 길이). 평지붕·비직사각형은 None."""
    if b['roof_type'] == 'flat' or not _is_rect(b['outline']):
        return None
    xs = [p[0] for p in b['outline']]
    zs = [p[1] for p in b['outline']]
    w, l = max(xs) - min(xs), max(zs) - min(zs)
    across, along = (w, l) if b['ridge_axis'] == 'z' else (l, w)
    return across / b['runs'], along


# ----------------------------------------------------------------
# 컴파일
# ----------------------------------------------------------------
def compile_layout(layout, envelope=None):
    """모형 → 공간별·덩어리별 수치와 시설 합계.

    반환 dict::

        {'schema': 1,
         'levels': {id: {elevation_m, height_m}},
         'blocks': {id: {level_id, floor_m2, footprint_m2, perimeter_m, wall_height_m,
                         sidewall_m2, roof_m2, gable_m2, envelope_m2, volume_m3,
                         glazing_m2, roof_exposed_fraction}},
         'spaces': {id: {block_id, level_id, name, crop, floor_m2, volume_m3,
                         sidewall_m2, roof_m2, gable_m2, envelope_m2, glazing_m2,
                         interior_boundaries: [{to, type, length_m, area_m2}]}},
         'boundaries': [{between, type, length_m, area_m2}],
         'totals': {floor_m2, envelope_m2, sidewall_m2, roof_m2, gable_m2,
                    volume_m3, glazing_m2, interior_boundary_m2: {wall, curtain, open}},
         'warnings': [...]}

    `totals` 의 키 이름은 `facility_calc.compute_capacity` 와 같다(소수 2자리).
    공간 몫은 덩어리의 지붕·박공·체적 중 지붕 부분을 바닥 넓이 비율로 나눈 것이다
    (덩어리 안 공간이 덩어리를 빈틈없이 채우면 합이 덩어리 값과 같다).
    `layout` 이 검증을 통과하지 못하면 ValueError.

    F4 — 외피 상속: 덩어리에 `walls.cover` 가 없으면 `envelope`(시설 `envelope` 설정, 새·옛
    형식 모두)의 바깥 덮개를 쓰고, `envelope` 도 없으면 `DEFAULT_MATERIAL`. 덩어리·공간에
    `cover`(공간은 덮개별 외피 `envelope_by_cover`)와 `ua_w_k`(외피 면적×덮개 U 의 합,
    W/K — 덮개 한 겹 기준, 겹수·보온 커튼은 보지 않는다)가 붙는다.

    F4 — 공기 구획: 결과의 `air_zones` 는 `open` 경계로 맞닿은 공간과 슬래브 구멍(`voids`)
    으로 이어진 공간을 한 구획으로 묶은 목록이다(사람이 묶지 않는다). 구획 값은 공간 값의
    합이고, 외기에 닿는 벽·지붕·투광면만 센다. 구획 사이 `wall`·`curtain` 경계는
    `to_other_zones` 에 면적으로 남긴다. 층간 열·공기 이동은 모형화하지 않으며, 이 값은
    제어 판단에 쓰이지 않는다(소비자 없음).
    """
    errs = validate_layout(layout)
    if errs:
        raise ValueError('invalid layout: %s' % '; '.join('%s(%s)' % (e['code'], e['path']) for e in errs[:5]))
    warnings = []
    default_cover = _legacy_cover(envelope) if envelope else DEFAULT_MATERIAL
    levels, lv_by_id, lv_rank, blocks, spaces = _prep(layout, default_cover)
    voids = layout.get('voids') or []

    by_rank = {}
    for b in blocks.values():
        by_rank.setdefault(b['rank'], []).append(b)

    # 같은 층 덩어리끼리 맞닿은 벽 → 외벽에서 뺀다
    for b in blocks.values():
        ext_ratio = []
        for e in _edges(b['outline']):
            ln = math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1])
            shared = 0.0
            for o in blocks.values():
                if o is b or o['rank'] != b['rank']:
                    continue
                for oe in _edges(o['outline']):
                    shared += _overlap_len(e, oe)
            ext_ratio.append(max(ln - shared, 0.0) / ln if ln > _EPS else 0.0)
        b['edge_ext_ratio'] = ext_ratio

    out_blocks = {}
    for b in blocks.values():
        A = _area(b['outline'])
        per = _perimeter(b['outline'])
        ext_len = sum(math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]) * r
                      for e, r in zip(_edges(b['outline']), b['edge_ext_ratio']))
        # 이 층 슬래브 구멍은 바닥 넓이에서 뺀다(공기는 통하므로 체적은 그대로)
        void_area = 0.0
        for v in voids:
            if v['level_id'] == b['level_id']:
                void_area += _overlap_area([tuple(p) for p in v['outline']], b['outline'], warnings, 'void')
        floor = max(A - void_area, 0.0)

        dims = _roof_dims(b)
        if dims:
            span_run, along = dims
            arc = roof_section_perimeter(b['roof_type'], span_run, b['rise'])
            sect = roof_section_area(b['roof_type'], span_run, b['rise'])
            roof_full = arc * along * b['runs']
            gable = sect * 2 * b['runs']
            roof_vol = sect * along * b['runs']
        else:
            roof_full, gable, roof_vol = A, 0.0, 0.0
        # 윗면 중 바로 위층 덩어리가 덮은 만큼은 지붕이 아니다
        above = b['rank'] + b['spans']
        covered = 0.0
        for o in by_rank.get(above, []):
            covered += _overlap_area(b['outline'], o['outline'], warnings, '%s/%s' % (b['id'], o['id']))
        frac = max(1.0 - covered / A, 0.0) if A > _EPS else 0.0
        if dims and covered > _EPS:
            warnings.append({'code': 'curved_roof_covered', 'message': '곡면 지붕 덩어리 %s 위에 다른 덩어리가 있다' % b['id']})
        roof = roof_full * frac
        side = ext_len * b['wall_h']
        env = side + roof + gable
        transparent = _transparent(b['cover'])
        out_blocks[b['id']] = {
            'level_id': b['level_id'], 'footprint_m2': A, 'floor_m2': floor, 'perimeter_m': per,
            'wall_height_m': b['wall_h'], 'sidewall_m2': side, 'roof_m2': roof, 'gable_m2': gable,
            'envelope_m2': env, 'volume_m3': A * b['wall_h'] + roof_vol,
            'glazing_m2': env if transparent else 0.0, 'roof_exposed_fraction': frac,
            'cover': b['cover'], 'ua_w_k': env * _cover_u(b['cover']),
            '_roof_vol': roof_vol,
        }

    # 공간별
    out_spaces = {}
    for sp in spaces:
        r = {'block_id': sp['block_id'], 'level_id': sp['level_id'], 'name': sp['name'], 'crop': sp['crop'],
             'floor_m2': 0.0, 'volume_m3': 0.0, 'sidewall_m2': 0.0, 'roof_m2': 0.0, 'gable_m2': 0.0,
             'envelope_m2': 0.0, 'glazing_m2': 0.0, 'ua_w_k': 0.0, 'envelope_by_cover': {},
             'interior_boundaries': []}
        for bid, ring in sp['parts']:
            b, ob = blocks[bid], out_blocks[bid]
            a = _area(ring)
            share = a / ob['footprint_m2'] if ob['footprint_m2'] > _EPS else 0.0
            # 외벽: 공간 둘레 중 덩어리 외벽에 겹치는 길이
            ext_len = 0.0
            for e in _edges(ring):
                for be, ratio in zip(_edges(b['outline']), b['edge_ext_ratio']):
                    ext_len += _overlap_len(e, be) * ratio
            side = ext_len * b['wall_h']
            if b['roof_type'] == 'flat' or not _is_rect(b['outline']):
                # 평지붕: 이 공간 윗면 중 바로 위층 덩어리가 덮은 만큼만 뺀다(덮인 자리가
                # 어느 공간 위인지가 중요하다 — 구획마다 외기 접촉 지붕이 달라진다)
                cov = 0.0
                for o in by_rank.get(b['rank'] + b['spans'], []):
                    cov += _overlap_area(ring, o['outline'], warnings, '%s/%s' % (sp['id'], o['id']))
                roof = max(a - cov, 0.0)
            else:
                roof = ob['roof_m2'] * share
            gable = ob['gable_m2'] * share
            env = side + roof + gable
            r['floor_m2'] += a * (ob['floor_m2'] / ob['footprint_m2'] if ob['footprint_m2'] > _EPS else 0.0)
            r['volume_m3'] += a * b['wall_h'] + ob['_roof_vol'] * share
            r['sidewall_m2'] += side
            r['roof_m2'] += roof
            r['gable_m2'] += gable
            r['envelope_m2'] += env
            if _transparent(b['cover']):
                r['glazing_m2'] += env
            r['ua_w_k'] += env * _cover_u(b['cover'])
            r['envelope_by_cover'][b['cover']] = r['envelope_by_cover'].get(b['cover'], 0.0) + env
        out_spaces[sp['id']] = r

    # 내부 경계: 맞닿은 공간 쌍
    declared = {}
    for bd in layout.get('boundaries') or []:
        declared[frozenset(bd['between'])] = bd['type']
    boundaries = []
    interior = {t: 0.0 for t in BOUNDARY_TYPES}
    contacts = {}
    for i, s1 in enumerate(spaces):
        for s2 in spaces[i + 1:]:
            if s1['rank_hi'] < s2['rank_lo'] or s2['rank_hi'] < s1['rank_lo']:
                continue
            length = 0.0
            for b1, r1 in s1['parts']:
                for b2, r2 in s2['parts']:
                    if blocks[b1]['rank'] != blocks[b2]['rank']:
                        continue
                    for e1 in _edges(r1):
                        for e2 in _edges(r2):
                            length += _overlap_len(e1, e2)
            if length > _EPS:
                contacts[frozenset((s1['id'], s2['id']))] = (s1, s2, length)
    for key, (s1, s2, length) in contacts.items():
        t = declared.get(key, 'wall')
        h = min(blocks[s1['block_id']]['wall_h'], blocks[s2['block_id']]['wall_h'])
        area = length * h
        rec = {'between': [s1['id'], s2['id']], 'type': t,
               'length_m': round(length, 3), 'area_m2': round(area, 3)}
        boundaries.append(rec)
        interior[t] += area
        out_spaces[s1['id']]['interior_boundaries'].append(
            {'to': s2['id'], 'type': t, 'length_m': rec['length_m'], 'area_m2': rec['area_m2']})
        out_spaces[s2['id']]['interior_boundaries'].append(
            {'to': s1['id'], 'type': t, 'length_m': rec['length_m'], 'area_m2': rec['area_m2']})
    for key in declared:
        if key not in contacts:
            warnings.append({'code': 'boundary_without_contact',
                             'message': '선언한 경계 %s 의 두 공간이 맞닿지 않는다' % '/'.join(sorted(key))})

    air_zones = _air_zones(layout, spaces, blocks, out_spaces, contacts, declared, voids, warnings)

    def r2(v, nd=2):
        return round(v + 0.0, nd)
    totals_raw = {k: sum(b[k] for b in out_blocks.values())
                  for k in ('floor_m2', 'envelope_m2', 'sidewall_m2', 'roof_m2', 'gable_m2',
                            'volume_m3', 'glazing_m2')}
    totals = {k: r2(v) for k, v in totals_raw.items()}
    totals['interior_boundary_m2'] = {t: r2(v) for t, v in interior.items()}

    for ob in out_blocks.values():
        ob.pop('_roof_vol', None)
        for k in list(ob):
            if isinstance(ob[k], float):
                ob[k] = round(ob[k], 3)
    for r in out_spaces.values():
        for k in list(r):
            if isinstance(r[k], float):
                r[k] = round(r[k], 3)
        r['envelope_by_cover'] = {c: round(v, 3) for c, v in r['envelope_by_cover'].items()}
    for z in air_zones:
        for k in list(z):
            if isinstance(z[k], float):
                z[k] = round(z[k], 3)
        z['envelope_by_cover'] = {c: round(v, 3) for c, v in z['envelope_by_cover'].items()}
        for o in z['to_other_zones']:
            o['area_m2'] = round(o['area_m2'], 3)
    return {
        'schema': SCHEMA_VERSION,
        'levels': {lv['id']: {'elevation_m': lv['elevation_m'], 'height_m': lv['height_m']} for lv in levels},
        'blocks': out_blocks,
        'spaces': out_spaces,
        'air_zones': air_zones,
        'boundaries': boundaries,
        'totals': totals,
        'warnings': warnings,
    }


def _air_zones(layout, spaces, blocks, out_spaces, contacts, declared, voids, warnings):
    """공간을 `open` 경계·슬래브 구멍으로 이어 공기 구획으로 묶는다(합집합 찾기).

    · `open`: 선언한 경계이면서 실제로 맞닿은 공간 쌍만(맞닿지 않으면 경고만 있고 잇지 않는다).
    · 구멍: 구멍 층의 공간 중 구멍과 평면이 겹치는 공간과, 그 바로 아래층 공간 중 겹치는
      공간을 모두 한 구획으로 잇는다. 맨 아래 층의 구멍은 이을 아래층이 없어 경고만 한다.
    구획 id 는 `zone_N`, 번호는 공간 순서에서 첫 공간이 앞선 순이다.
    """
    parent = {sp['id']: sp['id'] for sp in spaces}
    reasons = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, why):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        reasons.setdefault(frozenset((a, b)), why)

    for key, (s1, s2, _len) in contacts.items():
        if declared.get(key) == 'open':
            union(s1['id'], s2['id'], 'open')

    levels = sorted(layout['levels'], key=lambda lv: lv['elevation_m'])
    lv_rank = {lv['id']: i for i, lv in enumerate(levels)}
    for vi, v in enumerate(voids):
        r = lv_rank[v['level_id']]
        vr = [tuple(p) for p in v['outline']]

        def hit(sp, rr):
            return any(blocks[b]['rank'] <= rr <= blocks[b]['rank'] + blocks[b]['spans'] - 1
                       and _overlap_area(ring, vr, warnings, 'void%d/%s' % (vi, sp['id'])) > _EPS
                       for b, ring in sp['parts'])
        upper = [sp for sp in spaces if sp['rank_lo'] <= r <= sp['rank_hi'] and hit(sp, r)]
        lower = [sp for sp in spaces if sp['rank_lo'] <= r - 1 <= sp['rank_hi'] and not
                 (sp['rank_lo'] <= r <= sp['rank_hi']) and hit(sp, r - 1)]
        if not lower:
            warnings.append({'code': 'void_without_space_below',
                             'message': '슬래브 구멍 %d 아래에 이어질 공간이 없다' % vi})
            continue
        ids = [sp['id'] for sp in upper + lower]
        for other in ids[1:]:
            union(ids[0], other, 'void')

    groups = {}
    order = []
    for sp in spaces:
        root = find(sp['id'])
        if root not in groups:
            groups[root] = []
            order.append(root)
        groups[root].append(sp['id'])
    zone_of = {}
    zones = []
    for n, root in enumerate(order, 1):
        zid = 'zone_%d' % n
        for sid in groups[root]:
            zone_of[sid] = zid
        z = {'id': zid, 'space_ids': list(groups[root]), 'level_ids': [],
             'floor_m2': 0.0, 'volume_m3': 0.0, 'sidewall_m2': 0.0, 'roof_m2': 0.0,
             'gable_m2': 0.0, 'envelope_m2': 0.0, 'glazing_m2': 0.0, 'ua_w_k': 0.0,
             'envelope_by_cover': {}, 'joined_by': [], 'to_other_zones': []}
        for sid in groups[root]:
            o = out_spaces[sid]
            for k in ('floor_m2', 'volume_m3', 'sidewall_m2', 'roof_m2', 'gable_m2',
                      'envelope_m2', 'glazing_m2', 'ua_w_k'):
                z[k] += o[k]
            for c, v in o['envelope_by_cover'].items():
                z['envelope_by_cover'][c] = z['envelope_by_cover'].get(c, 0.0) + v
            if o['level_id'] not in z['level_ids']:
                z['level_ids'].append(o['level_id'])
        z['level_ids'].sort(key=lambda i: lv_rank[i])
        members = set(groups[root])
        z['joined_by'] = sorted({w for k, w in reasons.items() if k <= members})
        zones.append(z)
    # 구획 사이 벽·커튼(같은 층에서 맞닿은 것만 — 층간은 모형화하지 않는다)
    agg = {}
    for key, (s1, s2, _len) in contacts.items():
        z1, z2 = zone_of[s1['id']], zone_of[s2['id']]
        if z1 == z2:
            continue
        t = declared.get(key, 'wall')
        rec = out_spaces[s1['id']]['interior_boundaries']
        area = next(b['area_m2'] for b in rec if b['to'] == s2['id'])
        for a, b in ((z1, z2), (z2, z1)):
            k = (a, b, t)
            agg[k] = agg.get(k, 0.0) + area
    by_id = {z['id']: z for z in zones}
    for (a, b, t), area in sorted(agg.items()):
        by_id[a]['to_other_zones'].append({'zone': b, 'type': t, 'area_m2': area})
    for sid, zid in zone_of.items():
        out_spaces[sid]['zone_id'] = zid
    return zones


# ----------------------------------------------------------------
# locate
# ----------------------------------------------------------------
def locate(layout, x, y, z, tolerance_m=EDGE_TOLERANCE_M, x_band=False):
    """시설 로컬 좌표 → `{'level_id','block_id','space_id'}`. 귀속 불가면 None.

    층: `y` 이하에서 가장 높은 층(`elevation_m <= y`). 가장 낮은 층보다 아래면 맨 아래 층,
    `y` 가 None 이면 맨 아래 층. 지붕·박공 높이도 그 위쪽 층 없이 처마 층에 속한다.
    공간: 그 층에 걸친 공간 중 평면 `(x, z)` 가 외곽에 드는 첫 공간. 어느 공간에도
    들지 않으면 가장 가까운 공간이며, 층 전체 공간의 바운딩 박스를 `tolerance_m` 만큼
    넓힌 x 범위 밖이면 None 이다(z 는 제한하지 않는다, 아래 주석) — 기존 `facility_bays.bay_id_for_position` 이 x 범위로 하던
    것(경계 ±1 m 밖은 시설 공통, 안쪽 틈은 가장 가까운 구역)과 같은 규칙이다.
    한 공간이 여러 덩어리에 걸치면 그 덩어리들의 볼록 껍질이 공간의 범위다
    (분리동 구역 안의 동 사이 틈이 그 구역에 드는 것은 기존과 같다).

    `x_band=True` (F1, 기존 구역 귀속과 정확히 같은 판정): 폭(x)만 본다. 공간의 x 범위
    (바운딩 박스)에 드는 첫 공간, 없으면 x 중심이 가장 가까운 공간(같으면 앞선 공간).
    z 는 보지 않는다. 구역 사이 틈에서 '변까지 거리'와 '중심까지 거리'가 달라지는
    폭이 다른 구역도 기존과 같게 갈린다. 평면이 2차원인 모형(F2 이후)은 기본값(False)을 쓴다.
    """
    r = locate_points(layout, [(x, y, z)], tolerance_m, x_band)
    return r[0] if r else None


def locate_points(layout, points, tolerance_m=EDGE_TOLERANCE_M, x_band=False):
    """`locate` 를 여러 점에 — 검증·정리를 한 번만 한다. `[(x, y, z), ...]` → 결과 목록.

    모형이 올바르지 않으면 점마다 None 인 목록이 아니라 **빈 목록**이다
    (호출부는 `locate` 의 None 과 구분할 필요가 있을 때 길이를 본다).
    """
    if not isinstance(layout, dict) or validate_layout(layout):
        return []
    prep = _prep(layout)
    return [_locate_prepared(prep, x, y, z, tolerance_m, x_band) for (x, y, z) in points]


def _locate_prepared(prep, x, y, z, tolerance_m, x_band):
    levels, lv_by_id, lv_rank, blocks, spaces = prep
    try:
        px = float(x)
        pz = 0.0 if (x_band and z is None) else float(z)
    except (TypeError, ValueError):
        return None
    rank = 0
    if y is not None:
        try:
            py = float(y)
        except (TypeError, ValueError):
            py = None
        if py is not None:
            for i, lv in enumerate(levels):
                if lv['elevation_m'] <= py + _EPS:
                    rank = i
    cands = [s for s in spaces if s['rank_lo'] <= rank <= s['rank_hi']]
    if not cands:
        return None

    def region(sp):
        if len(sp['parts']) == 1:
            return sp['parts'][0][1]
        return _hull([p for _, ring in sp['parts'] for p in ring])

    def res(s):
        return {'level_id': levels[rank]['id'], 'block_id': s['block_id'], 'space_id': s['id']}

    regs = [(s, region(s)) for s in cands]
    allp = [p for _, ring in regs for p in ring]
    tol = float(tolerance_m)
    if x_band:
        if px < min(p[0] for p in allp) - tol or px > max(p[0] for p in allp) + tol:
            return None
        bands = [(s, min(p[0] for p in ring), max(p[0] for p in ring)) for s, ring in regs]
        for s, lo, hi in bands:
            if lo <= px <= hi:
                return res(s)
        return res(min(bands, key=lambda t: abs(px - (t[1] + t[2]) / 2.0))[0])
    pt = (px, pz)
    for s, ring in regs:
        if len(ring) >= 3 and _point_in_ring(pt, ring):
            return res(s)
    # 범위 밖 판정은 x(폭 방향)만 본다 — 기존 규칙과 같다. 길이 방향(z)으로 끝벽 밖에
    # 놓인 fitting(출입구 앞 설비 등, 실측 개발서버 4건이 4 m 까지)도 그 시설의 가장
    # 가까운 공간에 귀속되어야 구역 귀속이 달라지지 않는다. 좁히는 것은 F1 의 몫.
    if px < min(p[0] for p in allp) - tol or px > max(p[0] for p in allp) + tol:
        return None

    def key(item):
        s, ring = item
        c = _centroid(ring)
        return (round(_dist_to_ring(pt, ring), 9), abs(px - c[0]) + abs(pz - c[1]))
    return res(min(regs, key=key)[0])


# ----------------------------------------------------------------
# footprint_points
# ----------------------------------------------------------------
def footprint_points(layout, step_m=None):
    """덩어리 외곽의 표본점 `[[x, z], ...]` (시설 로컬 미터, 모듈 머리말의 좌표계).

    원점: `x = 0` 은 가장 서쪽 동 바깥 벽선, `z = 0` 은 길이 방향 한쪽 끝 벽선이며
    기존 fitting 로컬 좌표와 같다. 지형 단계가 경사면(고도) 표본으로 쓴다.

    포함하는 점: 모든 덩어리(모든 층)의 외곽 꼭짓점, 덩어리 중심(면적 무게중심),
    그리고 `step_m` 이 있으면 각 변을 `ceil(변 길이 / step_m)` 등분한 점.
    `step_m` 이 None 이면 꼭짓점과 중심만 낸다. 같은 점은 한 번만 낸다(소수 3자리).
    층이 달라도 평면 위치가 같으면 한 점이다. 검증을 통과하지 못하면 빈 목록.
    """
    if not isinstance(layout, dict) or validate_layout(layout):
        return []
    step = None
    if step_m is not None:
        step = float(step_m)
        if not step > 0:
            raise ValueError('step_m 은 0 보다 커야 한다')
    seen = set()
    pts = []

    def add(p):
        k = (round(p[0], 3), round(p[1], 3))
        if k not in seen:
            seen.add(k)
            pts.append([k[0] + 0.0, k[1] + 0.0])
    for b in layout['blocks']:
        ring = [tuple(p) for p in b['outline']]
        for (a, c) in _edges(ring):
            add(a)
            if step:
                ln = math.hypot(c[0] - a[0], c[1] - a[1])
                n = int(math.ceil(ln / step - 1e-9))
                for i in range(1, n):
                    t = i / n
                    add((a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t))
        add(_centroid(ring))
    return pts


# ----------------------------------------------------------------
# 시설 도형 유도 (F3) — 전 층 외형의 합집합 → 지도 도형
# ----------------------------------------------------------------
_M_PER_DEG_LAT = 111320.0     # facility_bays._M_PER_DEG_LAT, rotatedRectRing 과 같은 값


def layout_bounds(layout):
    """모든 덩어리 외곽의 바운딩 박스 `(min_x, min_z, max_x, max_z)`, 덩어리가 없으면 None."""
    xs, zs = [], []
    for b in (layout or {}).get('blocks') or []:
        for p in b.get('outline') or []:
            xs.append(float(p[0]))
            zs.append(float(p[1]))
    if not xs:
        return None
    return (min(xs), min(zs), max(xs), max(zs))


def footprint_union(layout):
    """전 층 외형의 합집합 → 로컬 평면 다각형 목록 `[{'outer': ring, 'holes': [ring, ...]}]`.

    맞닿은 외형은 한 다각형, 떨어진(모서리만 닿은 것 포함) 외형은 따로 나온다. 안뜰처럼 둘러싸인
    빈 곳은 `holes` 다. 링은 닫지 않은 `[[x, z], ...]` 다. 스스로 꼬인 외곽은 `buffer(0)` 으로
    정리한다(검증은 교차를 막지만 저장본이 언제나 지금 검증을 지난 것은 아니다).
    모형이 올바르지 않으면 빈 목록.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    if not isinstance(layout, dict) or validate_layout(layout):
        return []
    polys = []
    for b in layout['blocks']:
        p = Polygon([(round(float(x), 6), round(float(z), 6)) for x, z in b['outline']])
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    merged = unary_union(polys).simplify(0)
    parts = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]

    def ring(coords):
        pts = [[round(c[0], 6), round(c[1], 6)] for c in coords]
        return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts
    out = []
    for g in parts:
        if g.geom_type != 'Polygon' or g.area < _EPS:
            continue
        out.append({'outer': ring(g.exterior.coords),
                    'holes': [ring(h.coords) for h in g.interiors]})
    return out


def local_to_lnglat(x, z, cx, cz, center_lng, center_lat, orientation_deg):
    """로컬 미터 `(x, z)` → `[lng, lat]`. `(cx, cz)` 가 지도 중심에 놓인다.

    모형 +X = 동, +Z = 남이고 `orientation_deg` 는 나침반 시계 방향이다
    (`aot-facility-map-3d.js` 의 `_buildTransform`, `aot-map-bay.js` 의 `_offsetToLngLat` 와 같다).
    회전이 0 이면 `x` 가 늘수록 동쪽, `z` 가 늘수록 남쪽이다. 미터 환산 상수는 편집기
    `rotatedRectRing` 과 같다.
    """
    dx, dz = float(x) - cx, float(z) - cz
    t = math.radians(float(orientation_deg or 0))
    east = dx * math.cos(t) + dz * math.sin(t)
    north = dx * math.sin(t) - dz * math.cos(t)
    return [center_lng + east / (_M_PER_DEG_LAT * math.cos(math.radians(center_lat))),
            center_lat + north / _M_PER_DEG_LAT]


def recenter(center_lng, center_lat, orientation_deg, old_bounds, new_bounds):
    """모형 박스가 바뀌어도 로컬 `(0, 0)` 이 지도에서 그대로 있도록 하는 새 중심 `(lng, lat)`.

    지도 경로는 모형 박스 중심을 시설 중심에 맞춘다. 외형을 늘려 박스가 커지면 중심을 옮기지
    않은 시설 전체가 밀린다.
    새 중심 = 옛 중심 + R(orientation_deg) · (새 박스 중심 − 옛 박스 중심)
    """
    ocx, ocz = (old_bounds[0] + old_bounds[2]) / 2.0, (old_bounds[1] + old_bounds[3]) / 2.0
    ncx, ncz = (new_bounds[0] + new_bounds[2]) / 2.0, (new_bounds[1] + new_bounds[3]) / 2.0
    lng, lat = local_to_lnglat(ncx, ncz, ocx, ocz, center_lng, center_lat, orientation_deg)
    return lng, lat


def _geojson_from_rings(polygons):
    if not polygons:
        return None
    if len(polygons) == 1:
        return {'type': 'Polygon', 'coordinates': polygons[0]}
    return {'type': 'MultiPolygon', 'coordinates': polygons}


def _closed(ring, to_ll):
    pts = [to_ll(p[0], p[1]) for p in ring]
    pts.append(list(pts[0]))
    return pts


def footprint_geometry(layout, center_lng, center_lat, orientation_deg):
    """모형 → 지도 도형 GeoJSON(Polygon|MultiPolygon). 만들 수 없으면 None.

    모형 박스 중심이 `(center_lng, center_lat)` 에 놓인다. 오목한 평면은 그 모양 그대로,
    떨어진 외형은 MultiPolygon, 안뜰은 구멍 링으로 낸다.
    """
    parts = footprint_union(layout)
    b = layout_bounds(layout)
    if not parts or b is None:
        return None
    cx, cz = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0

    def to_ll(x, z):
        return local_to_lnglat(x, z, cx, cz, center_lng, center_lat, orientation_deg)
    return _geojson_from_rings([[_closed(g['outer'], to_ll)] + [_closed(h, to_ll) for h in g['holes']]
                                for g in parts])


# ----------------------------------------------------------------
# 구역 표시 (F3) — 구획·검토 화면 전용. 제어 경로는 이 함수를 쓰지 않는다.
# ----------------------------------------------------------------
def layout_zones(layout, envelope=None):
    """모형 → 화면에 보일 구역 목록. 층이 낮은 순, 같은 층은 모형 순서.

    `[{'id','name','crop','level_id','level_name','ground','floor_m2','outlines': [ring, ...]}]`.
    `ground` 는 맨 아래 층에 걸친 구역이다 — 제어가 보는 옛 구역과 이을 수 있는 것은 이쪽뿐이다.
    이름이 없는 구역은 층 이름(한 층에 여럿이면 층 이름 + 번호)이다.
    모형이 올바르지 않으면 빈 목록 — 화면은 기존 구역으로 물러선다.

    ⚠ 표시 전용이다. 제어는 `facility_bays.compute_bay_slices`(저장된 `geometry_3d`·`bays`)를
    그대로 읽으므로 공간 id 를 `bay_scope` 후보로 내면 안 된다.
    """
    if not isinstance(layout, dict) or validate_layout(layout):
        return []
    compiled = compile_layout(layout, envelope)
    levels, _lv, lv_rank, _blocks, spaces = _prep(layout)
    count = {}
    for sp in spaces:
        count[sp['level_id']] = count.get(sp['level_id'], 0) + 1
    seen = {}
    out = []
    for sp in sorted(spaces, key=lambda s: lv_rank[s['level_id']]):
        lv = _lv[sp['level_id']]
        lv_name = lv.get('name') or lv['id']
        seen[sp['level_id']] = seen.get(sp['level_id'], 0) + 1
        name = sp.get('name')
        if not name:
            name = lv_name if count[sp['level_id']] == 1 else '%s %d' % (lv_name, seen[sp['level_id']])
        out.append({'id': sp['id'], 'name': name, 'crop': sp.get('crop'),
                    'level_id': sp['level_id'], 'level_name': lv_name,
                    'ground': sp['rank_lo'] == 0,
                    'floor_m2': compiled['spaces'][sp['id']]['floor_m2'],
                    'outlines': [[list(p) for p in ring] for _b, ring in sp['parts']]})
    return out


def zone_geometry(layout, zone, center_lng, center_lat, orientation_deg):
    """`layout_zones` 항목 하나 → 지도 도형 GeoJSON. 재료가 없으면 None."""
    b = layout_bounds(layout)
    rings = (zone or {}).get('outlines') or []
    if b is None or not rings or center_lng is None or center_lat is None:
        return None
    cx, cz = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0

    def to_ll(x, z):
        return local_to_lnglat(x, z, cx, cz, center_lng, center_lat, orientation_deg)
    return _geojson_from_rings([[_closed(r, to_ll)] for r in rings])


def _fitting_xyz(position):
    """fitting.position(`[x,y,z]` 또는 `{x,y,z}`) → `(x, y, z)` 또는 None."""
    try:
        if isinstance(position, dict):
            return float(position['x']), float(position.get('y') or 0), float(position['z'])
        if isinstance(position, (list, tuple)) and len(position) >= 3:
            return float(position[0]), float(position[1]), float(position[2])
    except (KeyError, TypeError, ValueError):
        return None
    return None


def locate_fittings(layout, fittings):
    """fittings → `{fitting_id: space_id}`. 층까지 보는 기본 `locate` 로 판정한다(`x_band` 아님)."""
    items = []
    for f in fittings or []:
        xyz = _fitting_xyz(f.get('position')) if isinstance(f, dict) and f.get('id') else None
        if xyz:
            items.append((f['id'], xyz))
    res = locate_points(layout, [xyz for _, xyz in items])
    return {fid: r['space_id'] for (fid, _), r in zip(items, res) if r}


def upper_fittings(layout, fittings):
    """위층 구역에 든 fitting `{fitting_id: space_id}` — 맨 아래 층에 걸치지 않은 구역이다.

    `layout` 시설의 제어는 층을 모르는 옛 구역이라 이 장치들을 제어 입력에 넣으면 안 된다.
    복층 공간(맨 아래 층부터 위로 트인 곳)은 맨 아래 층이고, 어느 구역에도 들지 못한 점은 위층으로
    치지 않는다(판정은 `locate_fittings` 와 같다).
    """
    if not isinstance(layout, dict) or validate_layout(layout):
        return {}
    upper = {sp['id'] for sp in _prep(layout)[4] if sp['rank_lo'] > 0}
    return {fid: sid for fid, sid in locate_fittings(layout, fittings).items() if sid in upper}


def merged_capacity(old_layout, new_layout):
    """저장된 모형의 구역 총량을 새 모형으로 옮긴 `{space_id: capacity}`.

    · 구역 총량은 `/bay_capacity` 만 쓴다. 편집본의 값은 열 때 복사본이라 그사이 고치거나 지운 값을
      되살리므로 믿지 않는다. 같은 id 는 저장된 값이 그대로 이어진다.
    · 나누기: id 를 잇는 큰 쪽이 총량을 그대로 갖고, 새 구역은 비어 있다. 나눈 비율은 넓이일 뿐
      베드 수가 아니므로 지어내지 않는다. 사람이 다시 적는다.
    · 합치기: 사라진 구역이 남은 구역 안으로 들어갔고 두 총량의 단위가 같으면 더한다. 어느 쪽이
      비어 있거나 단위가 다르면 남은 구역 값을 그대로 둔다. 어림한 분모는 몫을 틀리게 만든다.
    """
    if not isinstance(old_layout, dict) or not isinstance(new_layout, dict):
        return {}
    if validate_layout(old_layout) or validate_layout(new_layout):
        return {}
    new_spaces = _prep(new_layout)[4]
    new_ids = {sp['id'] for sp in new_spaces}
    old_caps = {s['id']: s['capacity'] for s in old_layout.get('spaces') or []
                if isinstance(s, dict) and isinstance(s.get('capacity'), dict)}
    out = {sid: cap for sid, cap in old_caps.items() if sid in new_ids}
    for sp in _prep(old_layout)[4]:
        cap = old_caps.get(sp['id'])
        if cap is None or sp['id'] in new_ids:
            continue
        pt = _centroid(sp['parts'][0][1])
        host = next((n for n in new_spaces
                     if n['level_id'] == sp['level_id']
                     and any(_point_in_ring(pt, ring) for _, ring in n['parts'])), None)
        kept = out.get(host['id']) if host else None
        if kept and kept.get('unit') == cap.get('unit'):
            try:
                out[host['id']] = dict(kept, total=float(kept['total']) + float(cap['total']))
            except (KeyError, TypeError, ValueError):
                pass
    return out


def location_changes(old_layout, new_layout, fittings):
    """모형을 바꾸면 구역이 달라지는 장치 `[{'id','from','to'}]`. fitting 좌표는 옮기지 않는다.

    외피가 만든 항목(`source == 'envelope'`)은 세지 않는다 — 사람이 놓은 장치가 아니다.
    """
    items = [f for f in fittings or []
             if isinstance(f, dict) and f.get('source') != 'envelope' and f.get('id')]
    before = locate_fittings(old_layout, items)
    after = locate_fittings(new_layout, items)
    out = []
    for f in items:
        a, b = before.get(f['id']), after.get(f['id'])
        if a != b:
            out.append({'id': f['id'], 'from': a, 'to': b})
    return out


# ----------------------------------------------------------------
# 기존 시설 → 모형
# ----------------------------------------------------------------
def _f(v, default):
    try:
        r = float(v)
    except (TypeError, ValueError):
        return default
    return r if r else default


def layout_from_legacy(facility):
    """기존 시설 값 → 모형 (읽을 때 변환, 저장하지 않는다).

    `facility` 는 `structure`, `bay_count`, `geometry_3d`, `bays`(구역 메타), `name`,
    `envelope` 를 가진 dict 다(`facility_bays.spec_from_row` 와 `compute_capacity` 의
    입력이 둘 다 맞는다). 빠진 치수는 `compute_capacity` 와 같은 기본값(폭 7·처마 2·
    용마루 4·길이 30)을 쓴다.

    · `connected` N동: 덩어리 1개(폭 N·span, 지붕 `runs=N`)와 구역마다 공간 1개,
      이웃한 공간 사이는 `open` 경계.
    · `single` N동: 덩어리 N개(동 사이 `spacing_m`), 구역이 걸친 동을 공간이 가진다.
    구역(공간) 범위와 id·이름은 `facility_bays.compute_bay_slices` 가 낸 것을 그대로 쓴다.
    """
    from .facility_bays import compute_bay_slices

    facility = facility or {}
    g = facility.get('geometry_3d') or {}
    span = _f(g.get('span_width_m'), _LEGACY_DEFAULTS['span_width_m'])
    eave = _f(g.get('eave_height_m'), _LEGACY_DEFAULTS['eave_height_m'])
    ridge = _f(g.get('ridge_height_m'), _LEGACY_DEFAULTS['ridge_height_m'])
    length = _f(g.get('length_m'), _LEGACY_DEFAULTS['length_m'])
    try:
        n = max(int(facility.get('bay_count') or 1), 1)
    except (TypeError, ValueError):
        n = 1
    connected = (facility.get('structure') or 'single') == 'connected'
    spacing = 0.0 if connected else _f(g.get('spacing_m'), 0.0)
    rise = max(ridge - eave, 0.0)
    rt = str(g.get('roof_type') or 'arch').lower()
    if rt not in ROOF_TYPES:
        rt = 'arch'            # compute_capacity 도 알 수 없는 종류를 arch 로 센다
    env = facility.get('envelope') or {}
    cover = _legacy_cover(env)

    roof = {'type': rt, 'rise_m': round(rise, 6), 'ridge_axis': 'z'}
    walls = {'cover': cover}
    blocks = []
    if connected:
        blocks.append({'id': 'B1', 'level_id': 'L1',
                       'outline': _rect(0.0, span * n, length),
                       'roof': dict(roof, runs=n), 'walls': dict(walls)})
    else:
        for i in range(n):
            x0 = i * (span + spacing)
            blocks.append({'id': 'B%d' % (i + 1), 'level_id': 'L1',
                           'outline': _rect(x0, x0 + span, length),
                           'roof': dict(roof, runs=1), 'walls': dict(walls)})

    fac = dict(facility)
    fac['geometry_3d'] = dict(g, span_width_m=span, spacing_m=spacing, length_m=length)
    slices = compute_bay_slices(fac)
    spaces = []
    for sl in slices:
        s = {'id': sl['id'], 'name': sl.get('name'), 'crop': sl.get('crop')}
        s0, s1 = int(sl.get('bay_start') or sl['index'] + 1), int(sl.get('bay_end') or sl['index'] + 1)
        if connected:
            s['block_id'] = 'B1'
            s['outline'] = _rect(sl['x_min'], sl['x_max'], length)
        else:
            ids = ['B%d' % k for k in range(s0, s1 + 1)]
            s['block_id'] = ids[0]
            if len(ids) > 1:
                s['block_ids'] = ids
        spaces.append(s)
    boundaries = []
    if connected:
        for a, b in zip(spaces, spaces[1:]):
            boundaries.append({'between': [a['id'], b['id']], 'type': 'open'})

    layout = {
        'schema': SCHEMA_VERSION,
        'levels': [{'id': 'L1', 'name': '1층', 'elevation_m': 0, 'height_m': eave}],
        'blocks': blocks,
        'spaces': spaces,
        'boundaries': boundaries,
        'voids': [],
    }
    return layout


def _rect(x0, x1, length):
    return [[round(x0, 6), 0.0], [round(x1, 6), 0.0], [round(x1, 6), round(length, 6)], [round(x0, 6), round(length, 6)]]


def _legacy_cover(envelope):
    """외피 설정(새·옛 형식)에서 바깥 덮개 재질. facility_calc 와 같은 규칙."""
    from .facility_calc import _normalize_envelope
    try:
        cover = _normalize_envelope(envelope or {})['outer_cover']
    except Exception:
        return DEFAULT_MATERIAL
    return cover if cover in MATERIALS else DEFAULT_MATERIAL
