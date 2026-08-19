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
"""

# 슬라이스 경계 밖 허용 오차(m) — 벽체 두께/배치 스냅 오차 흡수용.
_EDGE_TOLERANCE_M = 1.0


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
    }, ...]
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
        })
    return slices


def bay_id_for_position(slices, position):
    """fitting.position → 소속 bay id. 귀속 불가(위치 없음/범위 밖)면 None.

    슬라이스 사이 간격(detached spacing)이나 경계 오차 범위에 있으면 가장
    가까운 슬라이스로 귀속한다. 시설 전체 범위를 _EDGE_TOLERANCE_M 이상
    벗어난 위치는 None (= 시설 공통) 으로 둔다.
    """
    if not slices:
        return None
    x = _pos_x(position)
    if x is None:
        return None
    if (x < slices[0]['x_min'] - _EDGE_TOLERANCE_M or
            x > slices[-1]['x_max'] + _EDGE_TOLERANCE_M):
        return None
    for s in slices:
        if s['x_min'] <= x <= s['x_max']:
            return s['id']
    nearest = min(slices, key=lambda s: abs(x - s['x_center']))
    return nearest['id']


def build_fitting_bay_map(slices, fittings):
    """fittings 목록 → {fitting_id: bay_id} (귀속 가능한 fitting 만 포함)."""
    if not slices:
        return {}
    mapping = {}
    for f in (fittings or []):
        fid = f.get('id')
        if not fid:
            continue
        bid = bay_id_for_position(slices, f.get('position'))
        if bid:
            mapping[fid] = bid
    return mapping


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
