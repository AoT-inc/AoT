# coding=utf-8
"""
facility_bays.py — facility bay(구역) 슬라이스 계산 + fitting 귀속 공통 모듈.

시설의 bay 분할은 폭 방향(span) 등분 슬라이스로 생성된다
(aot-facility-design.js buildOuterGeoJSON 과 동일한 기하 규칙):
  - connected : 한 외피 안에 bay_count 개 슬라이스, 벽 공유 (spacing 0)
  - single    : bay_count 개 분리 동(棟), 동 사이 spacing_m 간격

fitting.position 은 시설 로컬 미터 좌표 [x, y, z] (x = 폭 방향 0..totalWidth)
이므로, bay 귀속은 지오 변환 없이 로컬 x 좌표 → 슬라이스 매핑으로 결정한다.

사용처:
  - facility_integration.get_facility_integration() — 센서/액추에이터 bay 귀속
  - facility_io.FacilityManager._to_dict()          — 위젯용 bay_slices 노출
  - env_coordinator _profile_loader_mixin           — bay_scope 필터링
  - plot_io / plot_geometry / plot_context          — 구획의 구역(F3: `fitting_zone_map` 등)
"""

# 슬라이스 경계 밖 허용 오차(m) — 벽체 두께/배치 스냅 오차 흡수용.
_EDGE_TOLERANCE_M = 1.0
EDGE_TOLERANCE_M = _EDGE_TOLERANCE_M   # facility_layout.EDGE_TOLERANCE_M 과 같은 값
_LEGACY_LENGTH_M = 30.0                # layout_from_legacy 의 길이 기본값과 같다
_LEGACY_LEVEL_ID = 'L1'                # 기존 시설은 층 1개


def _pos_x(position):
    """fitting.position ([x,y,z] 배열 또는 {x,y,z} dict) → 로컬 x(폭 방향) float."""
    if position is None:
        return None
    try:
        if isinstance(position, (list, tuple)) and len(position) >= 1:
            return float(position[0])
        if isinstance(position, dict) and position.get('x') is not None:
            return float(position['x'])
    except (TypeError, ValueError):
        return None
    return None


def compute_bay_slices(facility):
    """facility dict → bay 슬라이스 목록. 단동(bay 1개)도 슬라이스 1개를 생성해
    지도 위젯 구역 칩/모달의 진입점이 되게 한다 (이름 기본값 = 시설 이름).

    facility 는 FacilityManager._to_dict() 형태의 dict:
    structure, bay_count, geometry_3d{span_width_m, spacing_m}, bays(메타).

    Returns
    -------
    [{
        'id':       str,    # connected 는 bays 메타의 id, 그 외 'bay_<n>'
        'index':    int,    # 0-based 슬라이스 인덱스 (폭 방향 순서)
        'name':     str,
        'crop':     str | None,
        'x_min':    float,  # 로컬 미터 (폭 방향)
        'x_max':    float,
        'x_center': float,
        'outline':  [[x, z], ...],  # F1: 구역 평면 외곽(시설 로컬 미터, 직사각형 4점)
        'level_id': str,            # F1: 속한 층 id (기존 시설은 'L1')
    }, ...]

    `outline`·`level_id` 는 시설 모형(`facility_layout`)이 같은 구역을 가리키는 값이다.
    기존 시설은 층 1개·직사각형이라 외곽은 `x_min..x_max` × `0..length_m` 이다
    (분리동 구역이 여러 동에 걸치면 동 사이 틈까지 덮는 하나의 직사각형 — `locate` 가
    덩어리들의 볼록 껍질을 구역 범위로 보는 것과 같다). 기존 키는 그대로다.
    """
    try:
        bay_count = int(facility.get('bay_count') or 1)
    except (TypeError, ValueError):
        bay_count = 1
    g3d = facility.get('geometry_3d') or {}
    try:
        span_w = float(g3d.get('span_width_m') or 0)
    except (TypeError, ValueError):
        span_w = 0.0
    if span_w <= 0:
        return []

    structure = facility.get('structure') or 'single'
    is_connected = structure == 'connected'
    try:
        spacing = 0.0 if is_connected else float(g3d.get('spacing_m') or 0)
    except (TypeError, ValueError):
        spacing = 0.0

    bays_meta = facility.get('bays')
    if not isinstance(bays_meta, list):
        bays_meta = []

    length = _f(g3d.get('length_m'), 0.0)
    if length <= 0:
        length = _LEGACY_LENGTH_M
    default_level = _LEGACY_LEVEL_ID

    def _outline(x_min, x_max):
        return [[x_min, 0.0], [x_max, 0.0], [x_max, round(length, 6)], [x_min, round(length, 6)]]

    def _bay_x(idx_1based):
        """bay 번호(1-based) → (x_min, x_max) 로컬 미터."""
        x_min = (idx_1based - 1) * (span_w + spacing)
        return x_min, x_min + span_w

    # ── 사용자 정의 구역 (bay 범위 병합) ───────────────────────────────────
    # 시설 편집기의 구역 UI 가 저장한 {id, name, crop, bay_start, bay_end}.
    # 범위가 유효한 항목만 채택, bay_start 순으로 정렬. 하나도 없으면 아래의
    # bay 당 1구역 합성으로 폴백 (기존 동작).
    zone_metas = []
    for m in bays_meta:
        if not isinstance(m, dict):
            continue
        try:
            s = int(m.get('bay_start') or 0)
            e = int(m.get('bay_end') or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= s <= e <= bay_count:
            zone_metas.append((s, e, m))
    if zone_metas:
        zone_metas.sort(key=lambda t: t[0])
        slices = []
        for i, (s, e, m) in enumerate(zone_metas):
            x_min = _bay_x(s)[0]
            x_max = _bay_x(e)[1]
            default_id = 'bay_%d' % s if s == e else 'bay_%d_%d' % (s, e)
            default_nm = 'Bay %d' % s if s == e else 'Bay %d-%d' % (s, e)
            slices.append({
                'id':        str(m.get('id') or default_id),
                'index':     i,
                'name':      m.get('name') or default_nm,
                'crop':      m.get('crop'),
                'bay_start': s,
                'bay_end':   e,
                'x_min':     round(x_min, 3),
                'x_max':     round(x_max, 3),
                'x_center':  round((x_min + x_max) / 2.0, 3),
                'outline':   _outline(round(x_min, 3), round(x_max, 3)),
                'level_id':  default_level,
            })
        return slices

    # ── 폴백: bay 당 1구역 합성 ────────────────────────────────────────────
    # connected 의 레거시 bays 메타(범위 없는 bay 별 항목)는 이름만 차용.
    legacy_meta = bays_meta if (is_connected or bay_count == 1) else []
    slices = []
    for i in range(bay_count):
        x_min, x_max = _bay_x(i + 1)
        meta = legacy_meta[i] if i < len(legacy_meta) and isinstance(legacy_meta[i], dict) else {}
        bay_id = meta.get('id') or 'bay_%d' % (i + 1)
        # 단동: 구역 이름 미설정 시 시설 이름을 그대로 사용
        if bay_count == 1:
            default_name = facility.get('name') or 'Bay 1'
        else:
            default_name = 'Bay %d' % (i + 1)
        slices.append({
            'id':        str(bay_id),
            'index':     i,
            'name':      meta.get('name') or default_name,
            'crop':      meta.get('crop'),
            'bay_start': i + 1,
            'bay_end':   i + 1,
            'x_min':     round(x_min, 3),
            'x_max':     round(x_max, 3),
            'x_center':  round((x_min + x_max) / 2.0, 3),
            'outline':   _outline(round(x_min, 3), round(x_max, 3)),
            'level_id':  default_level,
        })
    return slices


def slice_x_range(sl):
    """구역 슬라이스 → (x_min, x_max) 로컬 미터, 알 수 없으면 None.

    `outline` 이 있으면 그 바운딩 박스, 없으면(옛 슬라이스) `x_min`·`x_max`.
    구역 폭을 쓰는 소비자(`_profile_loader_mixin._bay_capacity_fraction`)가 쓴다.
    """
    try:
        ol = sl.get('outline')
        if isinstance(ol, (list, tuple)) and len(ol) >= 3:
            xs = [float(p[0]) for p in ol]
            return min(xs), max(xs)
        return float(sl.get('x_min')), float(sl.get('x_max'))
    except (TypeError, ValueError, AttributeError, IndexError):
        return None


def layout_from_slices(slices):
    """구역 슬라이스 목록 → 귀속 판정용 최소 모형(스키마 1). 구역 하나 = 덩어리 하나 = 공간 하나.

    덩어리·공간 id 는 슬라이스 순번(`B<i>`·`S<i>`)이다 — 사용자가 정한 구역 id 가 겹쳐도
    모형이 깨지지 않는다. 층 높이는 판정에 쓰이지 않아 자리값(1 m)이다. 이 모형으로는
    면적·외피를 계산하지 말 것(그것은 `layout_from_legacy`). 모형이 성립하지 않으면 None.
    """
    if not slices:
        return None
    levels, blocks, spaces = {}, [], []
    for i, sl in enumerate(slices):
        ol = sl.get('outline')
        if not (isinstance(ol, (list, tuple)) and len(ol) >= 3):
            rng = slice_x_range(sl)
            if rng is None:
                return None
            ol = [[rng[0], 0.0], [rng[1], 0.0], [rng[1], _LEGACY_LENGTH_M], [rng[0], _LEGACY_LENGTH_M]]
        lid = str(sl.get('level_id') or _LEGACY_LEVEL_ID)
        levels.setdefault(lid, {'id': lid, 'name': lid, 'elevation_m': 0, 'height_m': 1.0})
        blocks.append({'id': 'B%d' % i, 'level_id': lid, 'outline': [list(p) for p in ol]})
        spaces.append({'id': 'S%d' % i, 'block_id': 'B%d' % i})
    return {'schema': 1, 'levels': list(levels.values()), 'blocks': blocks,
            'spaces': spaces, 'boundaries': [], 'voids': []}


def _locate_slices(slices, positions):
    """positions(fitting.position 목록) → 구역 id|None 목록. 귀속 공통 경로.

    `facility_layout.locate_points(..., x_band=True)` — 기존 x 범위 판정과 같은 결과.
    """
    from .facility_layout import locate_points

    out = [None] * len(positions)
    if not slices:
        return out
    layout = layout_from_slices(slices)
    if layout is None:
        return out
    idx, pts = [], []
    for k, pos in enumerate(positions):
        x = _pos_x(pos)
        if x is None:
            continue
        idx.append(k)
        pts.append((x, None, None))
    res = locate_points(layout, pts, EDGE_TOLERANCE_M, x_band=True)
    for k, r in zip(idx, res):
        if r:
            out[k] = slices[int(r['space_id'][1:])]['id']
    return out


def bay_id_for_position(slices, position):
    """fitting.position → 소속 bay id. 귀속 불가(위치 없음/범위 밖)면 None.

    슬라이스 사이 간격(detached spacing)이나 경계 오차 범위에 있으면 가장
    가까운 슬라이스로 귀속한다. 시설 전체 범위를 _EDGE_TOLERANCE_M 이상
    벗어난 위치는 None (= 시설 공통) 으로 둔다.
    판정은 `facility_layout.locate`(x_band) 로 한다 — `build_fitting_bay_map` 과 같은 경로.
    """
    return _locate_slices(slices, [position])[0]


def build_fitting_bay_map(slices, fittings):
    """fittings 목록 → {fitting_id: bay_id} (귀속 가능한 fitting 만 포함)."""
    if not slices:
        return {}
    items = [f for f in (fittings or []) if f.get('id')]
    ids = _locate_slices(slices, [f.get('position') for f in items])
    return {f['id']: bid for f, bid in zip(items, ids) if bid}


# ---------------------------------------------------------------------------
# 구획·검토 화면의 구역 (F3) — 시설 모형(`layout`)이 있으면 그 공간이 구역이다
# ---------------------------------------------------------------------------
#
# ⚠ `compute_bay_slices`·`spec_from_row`·`build_fitting_bay_map`·`/bays`(bay_scope 후보)·
#   코디네이터·트윈은 `layout` 시설에서도 저장된 `geometry_3d`·`bays` 를 그대로 읽는다. 여기
#   함수들은 구획(`GeoPlot.bay_id`)이 가리키는 자리를 보여 주고 검사한다. x 만 보는 기존 귀속
#   (`x_band`)은 legacy 시설 전용이고, `layout` 시설의 귀속은 층까지 보는 기본 `locate` 다.
#   제어에 닿는 것은 두 가지뿐이다: 구역을 옛 구역에 잇는 `zone_control_bays`(후보 구획)와
#   위층 장치를 빼는 `facility_layout.upper_fittings`(`control_view`). 다공간 계산은 쓰지 않는다.

def layout_of(fac):
    """시설 dict 또는 행에서 모형. 없으면 None."""
    if isinstance(fac, dict):
        return fac.get('layout') or None
    return getattr(fac, 'layout', None) or None


def layout_zone_ids(fac):
    """`layout` 시설의 구역(공간) id 목록. 모형이 없거나 올바르지 않으면 빈 목록."""
    from .facility_layout import layout_zones
    layout = layout_of(fac)
    return [z['id'] for z in layout_zones(layout)] if layout else []


def plot_bay_ids(fac):
    """`GeoPlot.bay_id` 로 인정할 id 집합. 구획 저장과 고아 판정이 같은 값을 본다.

    `layout` 시설은 그 구역, 그 밖에는(모형이 올바르지 않은 때도) 옛 구역 목록이다.
    """
    zones = layout_zone_ids(fac)
    if zones:
        return set(zones)
    spec = fac if isinstance(fac, dict) else spec_from_row(fac)
    return {sl['id'] for sl in compute_bay_slices(spec)}


def zone_control_bays(fac):
    """`layout` 시설의 구역 → 그 구역을 맡는 옛 구역 id 목록 `{zone_id: [bay_id, ...]}`.

    제어는 `layout` 시설에서도 옛 구역(`compute_bay_slices`)만 안다. 구역을 나누면 새 구역 id 는
    `bay_scope` 후보에 없으므로, 그 구역의 작물이 옛 구역 코디네이터에서 빠지지 않게 여기서 잇는다.

    · 이름이 같은 옛 구역이 있으면 그것 하나다(나눌 때 큰 쪽이 id 를 잇는다).
    · 아니면 폭(x) 구간이 겹치는 옛 구역 전부다. 제어가 장치를 x 로 귀속하므로 같은 축을 본다.
      걸치는 양이 작으면 치지 않는다 — 벽 위 오차가 옆 구역 후보를 늘려 판정을 흐리지 않게 한다.
    · 위층 구역과 옛 폭 밖 구역은 빈 목록이다. 이을 제어가 없다는 뜻이고 `control_notes` 가 알린다.

    `layout` 이 없거나 올바르지 않은 시설은 `{}` 다. 이 시설들의 제어 경로는 지금 그대로다.
    """
    from .facility_layout import layout_zones
    layout = layout_of(fac)
    zones = layout_zones(layout) if layout else []
    if not zones:
        return {}
    slices = compute_bay_slices(fac if isinstance(fac, dict) else spec_from_row(fac))
    ids = {sl['id'] for sl in slices}
    out = {}
    for z in zones:
        if not z.get('ground'):
            out[z['id']] = []
        elif z['id'] in ids:
            out[z['id']] = [z['id']]
        else:
            xs = [p[0] for ring in z['outlines'] for p in ring]
            lo, hi = min(xs), max(xs)
            need = min(EDGE_TOLERANCE_M, (hi - lo) / 2.0)
            out[z['id']] = [sl['id'] for sl in slices
                            if min(hi, sl['x_max']) - max(lo, sl['x_min']) >= need]
    return out


def upper_zone_ids(fac):
    """`layout` 시설의 위층 구역 id 집합(`layout_zones` 의 `ground` 가 거짓인 구역).

    위층 구역은 환경제어 대상이 아니다 — 위층 장치를 제어 입력에서 뺀 규칙과 같다.
    `layout` 이 없거나 올바르지 않으면 빈 집합이다. 옛 폭 밖의 **1층** 구역은 위층이 아니므로
    넣지 않는다(그 구역의 동작은 그대로다).
    """
    from .facility_layout import layout_zones
    layout = layout_of(fac)
    if not layout:
        return set()
    return {z['id'] for z in layout_zones(layout) if not z.get('ground')}


def zones_of_control_bay(fac, bay_id):
    """옛 구역 하나에 이어진 `layout` 구역 id 집합 — `zone_control_bays` 의 역방향."""
    return {zid for zid, bays in zone_control_bays(fac).items() if bay_id in bays}


def _is_control_fitting(f):
    """제어 입력이 되는 fitting — 실내 센서이거나 출력이 묶인 장치."""
    if f.get('kind') == 'sensor':
        return bool(f.get('input_id')) and (f.get('sensor_role') or 'indoor') == 'indoor'
    return bool(f.get('actuator_id'))


def control_notes(fac):
    """`layout` 시설에서 화면과 제어가 다르게 보는 자리. `fac` 은 시설 dict, 모형이 없으면 `{}`.

    `{'zones': {구역: [옛 구역]}, 'unlinked_zones': [{id,name,level_name}],
      'upper_fittings': [{id,name,kind,zone_id}], 'outside_fittings': [{id,name,kind,zone_id}]}`

    · `unlinked_zones`: 어느 옛 구역에도 이어지지 않아 `bay_scope` 코디네이터가 맡지 않는 구역.
    · `upper_fittings`: 위층 장치. 제어 입력에서 뺀다(`facility_integration` 의 `control_view`).
    · `outside_fittings`: 맨 아래 층인데 옛 구역 폭 밖이라 어느 구역 코디네이터도 맡지 않는 장치.
      구역을 안 정한 코디네이터에게는 지금처럼 시설 공통이다.
    """
    from .facility_layout import layout_zones, locate_fittings, upper_fittings, validate_layout
    layout = layout_of(fac)
    if not layout or validate_layout(layout):
        return {}
    links = zone_control_bays(fac)
    fittings = [f for f in fac.get('fittings') or []
                if isinstance(f, dict) and f.get('id') and _is_control_fitting(f)]
    upper = upper_fittings(layout, fittings)
    zone_of = locate_fittings(layout, fittings)
    legacy = build_fitting_bay_map(compute_bay_slices(fac), fittings)

    def brief(f):
        return {'id': f['id'], 'name': f.get('name') or f.get('kind'), 'kind': f.get('kind'),
                'zone_id': zone_of.get(f['id'])}
    return {
        'zones': links,
        'unlinked_zones': [{'id': z['id'], 'name': z['name'], 'level_name': z['level_name']}
                           for z in layout_zones(layout) if not links.get(z['id'])],
        'upper_fittings': [brief(f) for f in fittings if f['id'] in upper],
        'outside_fittings': [brief(f) for f in fittings
                             if f['id'] not in upper and f['id'] not in legacy],
    }


def fitting_zone_map(fac, fittings):
    """구획 화면용 귀속 `{fitting_id: 구역 id}`. `fac` 은 시설 dict 다.

    `layout` 시설은 층까지 보는 `locate`, 그 밖에는 기존 `build_fitting_bay_map` 이다.
    """
    layout = layout_of(fac)
    if layout:
        from .facility_layout import locate_fittings, validate_layout
        if not validate_layout(layout):
            return locate_fittings(layout, fittings)
    return build_fitting_bay_map(compute_bay_slices(fac), fittings)


# ---------------------------------------------------------------------------
# 구역의 지리 기하 — 로컬 미터 → 지도 좌표
# ---------------------------------------------------------------------------
#
# 시설 구획(GeoPlot.facility_uuid)은 자기 기하가 없다. 위치의 정본이 구역
# 자체이기 때문이다(docs/design/geo-vegetation-plot.md). 그래도 지도에
# **그리고 클릭하려면** 좌표가 있어야 하므로 여기서 파생한다.
#
# ⚠ 파생값이다. 저장하지 말 것 — 되써 넣으면 시설을 옮겨도 구획은 옛 자리에
#   남는다. 그리고 이 값이 틀려도 이력은 오염되지 않는다(정본은 `bay_id`
#   문자열이다). 그래서 여기서는 정밀도보다 **일관성**이 중요하다: 아래 계산은
#   `aot-facility-design.js` 의 `rotatedRectRing` 과 **같은 규칙**이어야 하고,
#   그쪽 규칙이 바뀌면 여기도 바뀌어야 한다.

_M_PER_DEG_LAT = 111320.0


def spec_from_row(fac):
    """GeoFacility 행 → 이 모듈의 함수들이 받는 최소 dict.

    `FacilityManager._to_dict()` 를 부르지 않는다 — 구역 목록 하나를 얻으려고
    시설 전체(장치 해소·바인딩 조회)를 끌어올 이유가 없다.
    """
    return {
        'structure':   fac.structure,
        'bay_count':   fac.bay_count,
        'geometry_3d': fac.geometry_3d or {},
        'bays':        fac.bays if isinstance(fac.bays, list) else [],
        'name':        fac.name,
    }


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rect_ring(center_lng, center_lat, off_x, off_y, width_m, length_m, deg):
    """로컬 오프셋의 사각형 → 닫힌 링(경위도).

    `aot-facility-design.js` 의 `rotatedRectRing` 과 같은 계산이다. 상수도
    같은 값을 쓴다(111320) — 여기서 더 정확한 측지 공식을 쓰면 편집기가 그린
    외피와 구역이 미세하게 어긋나 "구역이 시설 밖으로 삐져나온" 것처럼 보인다.
    """
    import math

    half_w, half_l = width_m / 2.0, length_m / 2.0
    corners = [
        (off_x - half_w, off_y - half_l),
        (off_x + half_w, off_y - half_l),
        (off_x + half_w, off_y + half_l),
        (off_x - half_w, off_y + half_l),
    ]
    theta = math.radians(deg or 0.0)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    m_per_deg_lng = _M_PER_DEG_LAT * math.cos(math.radians(center_lat))
    if abs(m_per_deg_lng) < 1e-9:
        return None                      # 극점 — 그릴 수 없다

    ring = []
    for dx, dy in corners:
        rx = dx * cos_t - dy * sin_t
        ry = dx * sin_t + dy * cos_t
        ring.append([center_lng + rx / m_per_deg_lng,
                     center_lat + ry / _M_PER_DEG_LAT])
    ring.append(ring[0])
    return ring


def slice_geometry(facility, sl):
    """구역 슬라이스 → GeoJSON geometry (없으면 None).

    `compute_bay_slices()` 가 내는 슬라이스 하나를 받아 그 구역이 지도에서
    차지하는 자리를 만든다. 재료는 전부 `geometry_3d` 에 있다 —
    `center_lng`/`center_lat`/`orientation_deg`/`span_width_m`/`length_m`.
    하나라도 없으면 **None 을 돌려준다**(호출부가 시설 외피로 폴백한다).
    지어내지 않는 것이 중요하다: 엉뚱한 자리에 그리면 사람은 그것을 측량
    결과로 읽는다.

    분리동(`structure='single'` + 여러 동)은 동 사이가 실제로 비어 있으므로
    **MultiPolygon** 으로 낸다 — 하나의 사각형으로 덮으면 건물이 아닌 땅까지
    그 구역인 것처럼 보인다.
    """
    if not sl:
        return None
    g3d = (facility or {}).get('geometry_3d') or {}
    c_lng, c_lat = g3d.get('center_lng'), g3d.get('center_lat')
    if c_lng is None or c_lat is None:
        return None                      # 아직 지도에 배치되지 않은 시설
    c_lng, c_lat = _f(c_lng, None), _f(c_lat, None)
    if c_lng is None or c_lat is None:
        return None

    span = _f(g3d.get('span_width_m'))
    length = _f(g3d.get('length_m'))
    if span <= 0 or length <= 0:
        return None

    deg = _f(g3d.get('orientation_deg'))
    is_connected = (facility.get('structure') or 'single') == 'connected'
    spacing = 0.0 if is_connected else _f(g3d.get('spacing_m'))
    try:
        bay_count = max(int(facility.get('bay_count') or 1), 1)
    except (TypeError, ValueError):
        bay_count = 1

    total_w = span * bay_count + spacing * max(bay_count - 1, 0)
    half_total = total_w / 2.0

    # 슬라이스의 로컬 x 범위는 폭 방향 0..total_w 이고, 편집기의 사각형은
    # 중심 기준이라 -half_total 만큼 옮겨야 같은 좌표계가 된다.
    start = int(sl.get('bay_start') or 1)
    end = int(sl.get('bay_end') or start)
    start = max(start, 1)
    end = min(max(end, start), bay_count)

    if spacing > 0:
        # 분리동 — 동마다 사각형 하나.
        polys = []
        for i in range(start, end + 1):
            off_x = -half_total + span / 2.0 + (i - 1) * (span + spacing)
            ring = _rect_ring(c_lng, c_lat, off_x, 0.0, span, length, deg)
            if ring:
                polys.append([ring])
        if not polys:
            return None
        if len(polys) == 1:
            return {'type': 'Polygon', 'coordinates': polys[0]}
        return {'type': 'MultiPolygon', 'coordinates': polys}

    # 연동(또는 단동) — 범위를 하나의 사각형으로.
    x_min = (start - 1) * span
    x_max = end * span
    width = x_max - x_min
    off_x = (x_min + x_max) / 2.0 - half_total
    ring = _rect_ring(c_lng, c_lat, off_x, 0.0, width, length, deg)
    if not ring:
        return None
    return {'type': 'Polygon', 'coordinates': [ring]}


def geometry_for_bay(facility, bay_id):
    """구역 id → GeoJSON geometry (구역을 못 찾거나 재료가 없으면 None)."""
    if not bay_id:
        return None
    for sl in compute_bay_slices(facility):
        if sl.get('id') == bay_id:
            return slice_geometry(facility, sl)
    return None
