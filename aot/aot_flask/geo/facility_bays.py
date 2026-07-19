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
