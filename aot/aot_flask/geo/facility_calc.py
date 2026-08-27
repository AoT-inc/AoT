# coding=utf-8
"""
Facility Capacity Calculator (PRD/DESIGN-GEO-FACILITY-001).

1차 산정 참고치 (±5~10%) — 기계설비 견적 단계용 reference values.
정밀 설계용이 아니며, 작물·지역·단열재 세부 정보 추가 시 정확도 향상 가능(차기).

@phase active
"""
import math
import logging

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# Material thermal/optical properties (DESIGN §5-1)
# ----------------------------------------------------------------
# u            — W/m²K, conduction through the cover
# transmittance — share of sunlight that passes straight through
# absorptance   — share of sunlight absorbed by the cover itself. What is
#                 neither transmitted nor absorbed is reflected away. This is
#                 the only term that separates a white cover from a black one:
#                 they conduct identically, both stop all light, and the
#                 difference the grower feels is how much of the sun the
#                 surface soaks up and then radiates inward.
MATERIALS = {
    # ── Glazing — light gets through, little is absorbed ────────────────────
    'vinyl_single':     {'u': 6.0,  'transmittance': 0.85, 'absorptance': 0.08},
    'vinyl_double':     {'u': 4.0,  'transmittance': 0.78, 'absorptance': 0.10},
    'po_film':          {'u': 6.5,  'transmittance': 0.85, 'absorptance': 0.08},
    'polycarbonate':    {'u': 3.0,  'transmittance': 0.78, 'absorptance': 0.10},
    'glass':            {'u': 5.8,  'transmittance': 0.85, 'absorptance': 0.08},
    'non_woven_fabric': {'u': 3.5,  'transmittance': 0.50, 'absorptance': 0.20},
    'pe_film':          {'u': 6.5,  'transmittance': 0.85, 'absorptance': 0.08},
    'air_cushion':      {'u': 2.8,  'transmittance': 0.75, 'absorptance': 0.10},

    # ── Opaque — light does not get through ─────────────────────────────────
    # Pigmented films are the same polymer at the same thickness as the clear
    # ones, so they keep the film U-value; only the light is stopped. Colour
    # lives entirely in absorptance: white reflects most of the sun away, black
    # takes nearly all of it in.
    'film_white_opaque': {'u': 6.5,  'transmittance': 0.0, 'absorptance': 0.25},
    'film_grey':         {'u': 6.5,  'transmittance': 0.0, 'absorptance': 0.55},
    'film_black':        {'u': 6.5,  'transmittance': 0.0, 'absorptance': 0.90},
    # Insulated panel, ~50 mm EPS/urethane core — by far the best U here, which
    # is the reason to build a wall out of it instead of covering it. Its light
    # painted steel skin absorbs moderately, and almost none of that reaches
    # the inside anyway (see inward_absorbed_fraction).
    'sandwich_panel':    {'u': 0.45, 'transmittance': 0.0, 'absorptance': 0.30},
    # Bare structural walls, no added insulation: ~200 mm concrete, ~190 mm brick.
    'concrete':          {'u': 3.1,  'transmittance': 0.0, 'absorptance': 0.60},
    'brick':             {'u': 2.4,  'transmittance': 0.0, 'absorptance': 0.70},
}
DEFAULT_MATERIAL = 'vinyl_double'

# ----------------------------------------------------------------
# Reference assumptions — PoC defaults, replaceable per-facility later
# ----------------------------------------------------------------
ASSUMPTIONS = {
    'delta_T_heating_K':     20.0,   # 외기-내부 온도차(한겨울 가정)
    'delta_T_cooling_K':     10.0,   # 한여름 가정
    'solar_radiation_W_m2':  500.0,  # 평균 일사
    'transpiration_W_m2':    100.0,  # 작물 증산 부하
    'r_airgap_m2K_W':        0.18,   # 정지 공기층 열저항
    'h_outside_W_m2K':       23.0,   # 외표면 열전달계수(여름 기준, ASHRAE ~22.7)
    'wind_factor_m_s':       1.5,    # 자연환기 환산 풍속
    'fan_default_m3h':       5000.0, # 매핑된 팬 1대 표준 용량
    'vent_height_m':         1.2,    # 측창 표준 높이
    'vent_length_ratio':     0.8,    # 측면 길이 대비 측창 길이 비
    'roof_vent_width_m':     0.8,    # 천창 표준 폭
}


# ----------------------------------------------------------------
# Geometry helpers — local equirectangular projection (small site)
# ----------------------------------------------------------------
def polygon_area_m2(geometry):
    """(Multi)Polygon area in square meters using local meter projection."""
    if not geometry:
        return 0.0
    gt = geometry.get('type')
    if gt == 'Polygon':
        rings = geometry.get('coordinates') or []
        return _ring_area_m2(rings[0]) if rings else 0.0
    if gt == 'MultiPolygon':
        polys = geometry.get('coordinates') or []
        total = 0.0
        for poly in polys:
            if poly:
                total += _ring_area_m2(poly[0])
        return total
    return 0.0


def polygon_perimeter_m(geometry):
    """(Multi)Polygon outer-ring perimeter in meters (sum across parts)."""
    if not geometry:
        return 0.0
    gt = geometry.get('type')
    if gt == 'Polygon':
        rings = geometry.get('coordinates') or []
        return _ring_perimeter_m(rings[0]) if rings else 0.0
    if gt == 'MultiPolygon':
        polys = geometry.get('coordinates') or []
        total = 0.0
        for poly in polys:
            if poly:
                total += _ring_perimeter_m(poly[0])
        return total
    return 0.0


def _ring_area_m2(coords):
    if len(coords) < 3:
        return 0.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    m_per_deg_lat = 111320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    pts = [(c[0] * m_per_deg_lng, c[1] * m_per_deg_lat) for c in coords]
    s = 0.0
    n = len(pts)
    for i in range(n - 1):
        s += pts[i][0] * pts[i+1][1] - pts[i+1][0] * pts[i][1]
    return abs(s) / 2.0


def _ring_perimeter_m(coords):
    if len(coords) < 2:
        return 0.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    m_per_deg_lat = 111320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0))
    p = 0.0
    for i in range(len(coords) - 1):
        dx = (coords[i+1][0] - coords[i][0]) * m_per_deg_lng
        dy = (coords[i+1][1] - coords[i][1]) * m_per_deg_lat
        p += math.sqrt(dx*dx + dy*dy)
    return p


def arch_section_area(span, rise):
    """Cross-section area of an arch roof modeled as half-ellipse (m²)."""
    a = span / 2.0
    b = max(rise, 0.0)
    return math.pi * a * b / 2.0


def arch_section_perimeter(span, rise):
    """Arc length of half-ellipse arch (m). Ramanujan approximation, halved."""
    a = span / 2.0
    b = max(rise, 0.0)
    if a <= 0 or b <= 0:
        return float(span)
    full = math.pi * (3*(a+b) - math.sqrt((3*a+b) * (a+3*b)))
    return full / 2.0


def roof_section_area(roof_type, span, rise):
    """Roof cross-section area dispatched by roof_type.

    arch   → half-ellipse: π·(span/2)·rise / 2
    gable  → triangle:     span × rise / 2
    gable2 → two triangles over half a span each: 2 × (span/2 × rise / 2)
             — the same total as one gable. Halving the base and doubling the
             count cancels out, so a second ridge buys height, not volume.
    flat   → 0 (no extra height above eave)
    """
    rt = (roof_type or 'arch').lower()
    if rt in ('gable', 'gable2'):
        return float(span) * max(rise, 0.0) / 2.0
    if rt == 'flat':
        return 0.0
    return arch_section_area(span, rise)


def roof_section_perimeter(roof_type, span, rise):
    """Roof surface length (along cross-section) dispatched by roof_type.

    arch   → half-ellipse arc length (Ramanujan)
    gable  → 2 × √((span/2)² + rise²)  (two slopes of an isoceles triangle)
    gable2 → 4 × √((span/4)² + rise²)  (four slopes, each over a quarter span).
             Unlike the area this does NOT match a single gable: the same
             volume is wrapped in more surface, which is the point of the
             shape and what the U-value/heat-loss figures have to see.
    flat   → span (flat top equals the span)
    """
    rt = (roof_type or 'arch').lower()
    if rt == 'gable':
        a = span / 2.0
        return 2.0 * math.sqrt(a*a + max(rise, 0.0)**2)
    if rt == 'gable2':
        a = span / 4.0
        return 4.0 * math.sqrt(a*a + max(rise, 0.0)**2)
    if rt == 'flat':
        return float(span)
    return arch_section_perimeter(span, rise)


# ----------------------------------------------------------------
# Effective envelope properties (single vs double layer)
# ----------------------------------------------------------------
def effective_u(layer_count, outer_material, inner_material=None, r_airgap=None):
    """U_eff (W/m²K). Double layer: 1 / (1/U_o + R_gap + 1/U_i)."""
    u_outer = MATERIALS.get(outer_material, MATERIALS[DEFAULT_MATERIAL])['u']
    if int(layer_count or 1) != 2 or not inner_material:
        return u_outer
    u_inner = MATERIALS.get(inner_material, MATERIALS[DEFAULT_MATERIAL])['u']
    r_gap = r_airgap if r_airgap is not None else ASSUMPTIONS['r_airgap_m2K_W']
    r_total = 1.0/u_outer + r_gap + 1.0/u_inner
    return 1.0 / r_total


def effective_transmittance(layer_count, outer_material, inner_material=None):
    """Multiplicative transmittance for stacked layers."""
    t_outer = MATERIALS.get(outer_material, MATERIALS[DEFAULT_MATERIAL])['transmittance']
    if int(layer_count or 1) != 2 or not inner_material:
        return t_outer
    t_inner = MATERIALS.get(inner_material, MATERIALS[DEFAULT_MATERIAL])['transmittance']
    return t_outer * t_inner


def solar_absorptance(outer_material):
    """Solar absorptance of the surface the sun actually strikes.

    Only the outer layer takes any argument here: sunlight is absorbed at the
    first surface it meets, so an inner liner cannot change how much of it the
    cover soaks up. That asymmetry is why this takes a material rather than a
    layer stack like effective_u/effective_transmittance.
    """
    m = MATERIALS.get(outer_material, MATERIALS[DEFAULT_MATERIAL])
    return float(m.get('absorptance', 0.0))


def inward_absorbed_fraction(u_value):
    """Share of the absorbed sunlight that ends up inside rather than back out.

    Heat absorbed by the cover leaves in both directions; how much comes inward
    is set by the ratio of the path in (the assembly's U) to the path out (the
    outside surface film). This is the standard opaque-wall simplification,
    N = U / h_o — the same reasoning behind sol-air temperature.

    It is what makes an insulated panel indifferent to its colour (U 0.45 → under
    2 % of what it absorbs gets in) while a bare film passes nearly a third of
    it, so black film bakes the house and white film does not.
    """
    h_o = ASSUMPTIONS['h_outside_W_m2K']
    if h_o <= 0:
        return 0.0
    return min(max(float(u_value), 0.0) / h_o, 1.0)


# ----------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------
# ─────────────────────────────────────────────────────────────────────────────
# 차광 커튼 투과율 — **시설이 아는 값이다**
# ─────────────────────────────────────────────────────────────────────────────
# 닫힌 차광막을 빛이 얼마나 통과하는가(0~1). 0.30 = 70% 차광.
#
# 예전에는 두 곳이 각자 알고 있었다:
#   · 이 파일이 냉방부하 계산에 **0.50 을 하드코딩**했고,
#   · 통합환경제어 함수가 사용자에게 `shade_transmittance` 를 **또 물었다**.
# 차광막은 시설의 물건이고 그 성질은 시설이 안다 — 설계문서 D9(2026-08-27).
# 이제 정본은 `envelope.curtain.shade.transmittance` 하나이고, 함수는 그것을
# 읽는다.
#
# ⚠ 미설정은 **0 이 아니라 기본 가정**이다. 0 으로 읽으면 "빛이 하나도 안
#   통과한다" 가 되어 실내 광량 추정이 0 으로 굳는다 — 보광등이 대낮에 켜진다.
DEFAULT_SHADE_TRANSMITTANCE = 0.50


def _shade_tau(shade_spec):
    """`envelope.curtain.shade` → 투과율(0~1). 없거나 범위 밖이면 기본값."""
    try:
        tau = float((shade_spec or {}).get('transmittance'))
    except (TypeError, ValueError):
        return DEFAULT_SHADE_TRANSMITTANCE
    if not (0.0 < tau <= 1.0):
        return DEFAULT_SHADE_TRANSMITTANCE
    return tau


def _normalize_envelope(envelope):
    """Return a view of envelope normalized to the new layers/stages schema.

    Accepts:
      - New format: {layers: [...], side_vent: {outer: {enabled, stages: [...]}}, roof_vent, curtain}
      - Old format: {layer_count, outer: {...}, inner: {...}, curtain: {thermal, shade}}

    Returns dict with keys:
      outer_cover, inner_cover (or None), layer_count,
      side_vent_enabled, side_vent_stages (list of {height_m, from_floor_m}),
      roof_vent_enabled,
      curtain_ceiling_enabled, curtain_ceiling_layers,
      curtain_wall_enabled, curtain_wall_sides,
      curtain_shade_enabled, curtain_shade_transmittance
    """
    if envelope.get('layers') is not None:
        layers = envelope.get('layers') or []
        outer_cover = DEFAULT_MATERIAL
        inner_cover = None
        for L in layers:
            role = (L.get('role') or '')
            if role == 'outer':
                outer_cover = L.get('cover') or outer_cover
            elif role == 'inner':
                inner_cover = L.get('cover') or inner_cover
        sv = ((envelope.get('side_vent') or {}).get('outer') or {})
        rv = ((envelope.get('roof_vent') or {}).get('outer') or {})
        cu = envelope.get('curtain') or {}
        tc = cu.get('thermal_ceiling') or {}
        tw = cu.get('thermal_wall') or {}
        sh = cu.get('shade') or {}
        return {
            'outer_cover': outer_cover,
            'inner_cover': inner_cover,
            'layer_count': 2 if inner_cover else 1,
            'side_vent_enabled': bool(sv.get('enabled')),
            'side_vent_stages': sv.get('stages') or [{'height_m': ASSUMPTIONS['vent_height_m'], 'from_floor_m': 0.3}],
            'roof_vent_enabled': bool(rv.get('enabled')),
            'curtain_ceiling_enabled': bool(tc.get('enabled')),
            'curtain_ceiling_layers': int(tc.get('layers') or 1),
            'curtain_wall_enabled': bool(tw.get('enabled')),
            'curtain_wall_sides': tw.get('sides') or [],
            'curtain_shade_enabled': bool(sh.get('enabled')),
            'curtain_shade_transmittance': _shade_tau(sh),
        }
    # Legacy format
    outer = envelope.get('outer') or {}
    inner = envelope.get('inner') or {}
    o_side = outer.get('side_vent') or {}
    o_roof = outer.get('roof_vent') or {}
    i_side = inner.get('side_vent') or {}
    i_roof = inner.get('roof_vent') or {}
    curtain = envelope.get('curtain') or {}
    layer_count = int(envelope.get('layer_count') or 1)
    # 이중 외피 시 내피 환기가 independent면 추가 개구면적 산입
    inner_side_independent = (
        layer_count == 2
        and bool(i_side.get('enabled'))
        and i_side.get('control_mode') == 'independent'
    )
    inner_roof_independent = (
        layer_count == 2
        and bool(i_roof.get('enabled'))
        and i_roof.get('control_mode') == 'independent'
    )
    return {
        'outer_cover': outer.get('cover_material') or DEFAULT_MATERIAL,
        'inner_cover': inner.get('cover_material') if layer_count == 2 else None,
        'layer_count': layer_count,
        'side_vent_enabled': bool(o_side.get('enabled')),
        'side_vent_stages': [{'height_m': ASSUMPTIONS['vent_height_m'], 'from_floor_m': 0.3}],
        'roof_vent_enabled': bool(o_roof.get('enabled')),
        'inner_side_vent_independent': inner_side_independent,
        'inner_roof_vent_independent': inner_roof_independent,
        'curtain_ceiling_enabled': bool(curtain.get('thermal')),
        'curtain_ceiling_layers': 1,
        'curtain_wall_enabled': False,
        'curtain_wall_sides': [],
        'curtain_shade_enabled': bool(curtain.get('shade')),
        # 옛 형식은 켬/끔 불리언뿐이라 값이 없다 — 기본 가정으로 돌아간다.
        'curtain_shade_transmittance': DEFAULT_SHADE_TRANSMITTANCE,
    }


def _aggregate_actuators(actuators):
    """Return totals from new-format list or legacy dict.

    Returns:
      exhaust_cmh, circulation_cmh: total airflow (m³/h)
      heating_kw, cooling_kw: total nameplate capacity
      counts: per-kind dict
    """
    out = {
        'exhaust_cmh': 0.0,
        'circulation_cmh': 0.0,
        'heating_kw': 0.0,
        'cooling_kw': 0.0,
        'counts': {},
    }
    if isinstance(actuators, list):
        for a in actuators:
            kind = a.get('kind')
            specs = a.get('specs') or {}
            out['counts'][kind] = out['counts'].get(kind, 0) + 1
            if kind == 'exhaust_fan':
                out['exhaust_cmh'] += float(specs.get('airflow_cmh') or ASSUMPTIONS['fan_default_m3h'])
            elif kind == 'circulation_fan':
                out['circulation_cmh'] += float(specs.get('airflow_cmh') or ASSUMPTIONS['fan_default_m3h'])
            elif kind == 'heater':
                out['heating_kw'] += float(specs.get('capacity_kw') or 0)
            elif kind in ('cooler', 'heat_pump'):
                out['cooling_kw'] += float(specs.get('capacity_kw') or 0)
        return out
    # Legacy dict {slot_key: device_uuid}
    if isinstance(actuators, dict):
        for slot, uuid in (actuators or {}).items():
            if not uuid:
                continue
            out['counts'][slot] = out['counts'].get(slot, 0) + 1
            if slot in ('exhaust_fan', 'circulation_fan'):
                out['exhaust_cmh' if slot == 'exhaust_fan' else 'circulation_cmh'] += ASSUMPTIONS['fan_default_m3h']
    return out


def compute_capacity(spec):
    """Compute reference capacity from a facility spec dict.

    Returns dict of m²/m³/kW/ACH values plus a `_note` disclaimer.
    Falls back to dimensional estimate if outer_geometry missing.
    """
    geom_3d = spec.get('geometry_3d') or {}
    envelope_raw = spec.get('envelope') or {}
    envelope = _normalize_envelope(envelope_raw)
    actuators_raw = spec.get('actuators')
    act_totals = _aggregate_actuators(actuators_raw)
    fittings = spec.get('fittings') or []
    bay_count = max(int(spec.get('bay_count') or 1), 1)
    structure = spec.get('structure') or 'single'

    # ---- 1. Footprint ----
    footprint = spec.get('outer_geometry')
    floor_m2 = polygon_area_m2(footprint)
    perimeter_m = polygon_perimeter_m(footprint)

    span      = float(geom_3d.get('span_width_m') or 7)
    eave_h    = float(geom_3d.get('eave_height_m') or 2)
    ridge_h   = float(geom_3d.get('ridge_height_m') or 4)
    length    = float(geom_3d.get('length_m') or 30)
    spacing   = float(geom_3d.get('spacing_m') or 0)
    roof_type = (geom_3d.get('roof_type') or 'arch')
    rise      = max(ridge_h - eave_h, 0.0)

    if floor_m2 <= 0:
        if structure == 'connected':
            effective_span = span * bay_count
            floor_m2 = effective_span * length
            perimeter_m = 2 * (effective_span + length)
        else:
            # single (1 bay) OR detached single+bays row
            floor_m2 = (span * length) * bay_count
            perimeter_m = (2 * (span + length)) * bay_count

    bay_mul = max(int(bay_count or 1), 1)
    eff_spacing  = 0.0 if structure == 'connected' else spacing
    total_width  = bay_count * span + (bay_count - 1) * eff_spacing

    # ---- 2. Envelope decomposition (roof_type aware) ----
    roof_arc  = roof_section_perimeter(roof_type, span, rise)
    roof_sect = roof_section_area(roof_type, span, rise)

    # roof_runs = number of roof ridge lines along `length`
    # connected: one continuous envelope but bays still each have their own roof ridge
    # single (1 or N bays): each detached bay has its own roof
    roof_runs = bay_mul

    # gables (end walls):
    #   connected: 2 (only the two ends of the joined envelope)
    #   single + N detached bays: 2 per bay = 2N
    if structure == 'connected':
        gable_count = 2
    else:
        gable_count = 2 * bay_mul

    sidewall_m2 = perimeter_m * eave_h
    roof_m2     = roof_arc * length * roof_runs
    gable_m2    = roof_sect * gable_count
    envelope_m2 = sidewall_m2 + roof_m2 + gable_m2

    # ---- 3. Volume ----
    roof_vol_per_bay = roof_sect * length
    volume_m3 = floor_m2 * eave_h + roof_vol_per_bay * roof_runs

    # ---- 4. U_eff & transmittance ----
    layer_count = envelope['layer_count']
    outer_mat = envelope['outer_cover']
    inner_mat = envelope['inner_cover']

    u_eff = effective_u(layer_count, outer_mat, inner_mat, r_airgap=None)
    t_eff = effective_transmittance(layer_count, outer_mat, inner_mat)

    # ---- 5. Envelope-derived vent area + individual opening descriptors ----
    # Envelope fittings (source='envelope') are never saved to the DB — they are
    # virtual, recomputed at runtime by _renderEnvelopeFittings in the frontend.
    # We reproduce the same geometry here so vent_openings is complete.
    # Stage heights use the same equal-split formula as _equalStages() (margin=0.05,
    # gap=0.10) so areas match what the 3D view shows.
    side_len = max(length, 0.0)
    envelope_vent_m2 = 0.0
    envelope_vent_openings = []   # virtual descriptors added to vent_openings below

    if envelope['side_vent_enabled']:
        n_stages = max(len(envelope['side_vent_stages']), 1)
        _m, _g = 0.05, 0.10
        avail_h = max(eave_h - 2 * _m - (n_stages - 1) * _g, 0.4)
        step_h  = avail_h / n_stages
        eff_len = side_len * 0.97
        stage_lbl = ['Lower', 'Upper'] if n_stages == 2 else [('Stage ' + str(i + 1)) for i in range(n_stages)]
        for si in range(n_stages):
            stage_y = _m + si * (step_h + _g) + step_h / 2
            area_per = round(eff_len * step_h, 3)
            lbl = stage_lbl[si] if si < len(stage_lbl) else ('Stage ' + str(si + 1))
            for face, sn in [('west', [-1, 0, 0]), ('east', [1, 0, 0])]:
                envelope_vent_openings.append({
                    'id':             'env_side_vent_outer_' + ('left' if face == 'west' else 'right') + '_' + (
                                       'single' if n_stages == 1 else ('lower' if si == 0 else ('upper' if si == n_stages - 1 else 's' + str(si)))),
                    'kind':           'side_window',
                    'area_m2':        area_per,
                    'label':          'Side Vent ' + ('Left' if face == 'west' else 'Right') + ' ' + lbl,
                    'position':       {'x': 0 if face == 'west' else round(total_width, 3),
                                       'y': round(stage_y, 3), 'z': round(side_len / 2, 3)},
                    'surface_normal': sn,
                    'face':           face,
                    'actuator_id':    None,
                    'source':         'envelope',
                })
                envelope_vent_m2 += area_per

    if envelope['roof_vent_enabled']:
        rv_w = ASSUMPTIONS['roof_vent_width_m']
        area_per = round(side_len * rv_w, 3)
        for b in range(bay_count):
            envelope_vent_openings.append({
                'id':             'env_roof_vent_outer_b' + str(b),
                'kind':           'window',
                'area_m2':        area_per,
                'label':          'Roof Vent' + ((' #' + str(b + 1)) if bay_count > 1 else ''),
                'position':       {'x': round(span * (b + 0.5), 3),
                                   'y': round(ridge_h, 3), 'z': round(side_len / 2, 3)},
                'surface_normal': [0, 1, 0],
                'face':           'roof',
                'actuator_id':    None,
                'source':         'envelope',
            })
            envelope_vent_m2 += area_per

    if envelope.get('inner_side_vent_independent'):
        inner_h  = ASSUMPTIONS['vent_height_m']
        area_per = round(side_len * ASSUMPTIONS['vent_length_ratio'] * inner_h, 3)
        for face, sn in [('west', [-1, 0, 0]), ('east', [1, 0, 0])]:
            envelope_vent_openings.append({
                'id':             'env_inner_side_vent_' + face,
                'kind':           'side_window',
                'area_m2':        area_per,
                'label':          'Inner Side Vent ' + ('Left' if face == 'west' else 'Right'),
                'position':       {'x': 0 if face == 'west' else round(total_width, 3),
                                   'y': round(inner_h / 2 + 0.3, 3), 'z': round(side_len / 2, 3)},
                'surface_normal': sn,
                'face':           face,
                'actuator_id':    None,
                'source':         'envelope',
            })
            envelope_vent_m2 += area_per

    if envelope.get('inner_roof_vent_independent'):
        rv_w = ASSUMPTIONS['roof_vent_width_m']
        area_per = round(side_len * rv_w, 3)
        envelope_vent_openings.append({
            'id':             'env_inner_roof_vent',
            'kind':           'window',
            'area_m2':        area_per,
            'label':          'Inner Roof Vent',
            'position':       {'x': round(total_width / 2, 3),
                               'y': round(ridge_h - 0.3, 3), 'z': round(side_len / 2, 3)},
            'surface_normal': [0, 1, 0],
            'face':           'roof',
            'actuator_id':    None,
            'source':         'envelope',
        })
        envelope_vent_m2 += area_per

    # ---- 6. Glazing — assume transparent envelope (greenhouse PoC) ----
    glazing_m2 = envelope_m2

    # ---- 7. Heating load (kW) ----
    # Effective U reduced when ceiling thermal curtain is deployed (static estimate)
    u_for_heating = u_eff
    if envelope['curtain_ceiling_enabled']:
        # Each layer of ceiling curtain reduces U by ~25% (static rule of thumb)
        u_for_heating *= max(1.0 - 0.25 * envelope['curtain_ceiling_layers'], 0.4)
    heating_kw = envelope_m2 * u_for_heating * ASSUMPTIONS['delta_T_heating_K'] / 1000.0

    # ---- 8. Cooling load (kW) ----
    # Sun reaches the inside two ways, and an opaque cover only closes the first:
    #   · transmitted — straight through the glazing. A shade curtain intercepts
    #     this, which is what it is for.
    #   · absorbed    — soaked up by the cover, then conducted inward. An indoor
    #     shade curtain cannot touch it: the heat is already past the glazing,
    #     so this term is deliberately left unshaded.
    # Without the second term every opaque cover looked identical and colour was
    # a purely cosmetic choice.
    solar = ASSUMPTIONS['solar_radiation_W_m2']
    t_for_cooling = t_eff
    if envelope['curtain_shade_enabled']:
        # 시설이 아는 값이다 — 예전에는 여기 0.50 이 박혀 있었고, 같은 값을
        # 통합환경제어 함수가 사용자에게 따로 물었다(설계문서 D9).
        t_for_cooling *= envelope['curtain_shade_transmittance']

    absorptance = solar_absorptance(outer_mat)
    absorbed_W_m2 = solar * absorptance * inward_absorbed_fraction(u_eff)

    # Both terms ride on roof_m2: the model treats the roof as the sunlit
    # surface, and putting the absorbed share on a different area would mean
    # inventing a second irradiance figure for the walls.
    solar_absorbed_kw   = roof_m2 * absorbed_W_m2 / 1000.0
    solar_transmitted_kw = roof_m2 * solar * t_for_cooling / 1000.0

    cooling_W = (roof_m2 * (solar * t_for_cooling + absorbed_W_m2)
                 + floor_m2 * ASSUMPTIONS['transpiration_W_m2'])
    cooling_kw = cooling_W / 1000.0

    # ---- 9. Nameplate capacities from actuators (override defaults if present) ----
    nameplate_heating_kw = act_totals['heating_kw']
    nameplate_cooling_kw = act_totals['cooling_kw']

    # ---- 10. Fittings aggregation (user-placed fittings only) ----
    # Envelope-derived fittings (source='envelope') are never saved to the DB —
    # they are virtual, computed at runtime by _renderEnvelopeFittings in the
    # frontend.  Their contribution is already captured in envelope_vent_m2 above.
    # Only user-placed fittings (doors, explicit windows, fans) are in `fittings`.
    # Final vent area = envelope_vent_m2 + fittings_vent_m2 (additive, no override).
    VENT_KINDS = {'window', 'side_window', 'door', 'fan'}
    fittings_by_kind = {}
    fittings_total_area = 0.0
    fittings_vent_m2 = 0.0
    vent_openings = []
    for f in fittings:
        kind = f.get('kind') or 'fixture'
        sz = f.get('size') or {}
        w = float(sz.get('w') or 0)
        h = float(sz.get('h') or 0)
        if kind in ('window', 'side_window', 'door', 'fan', 'curtain'):
            area = w * h
        else:
            area = w * float(sz.get('d') or 0)
        fittings_by_kind[kind] = fittings_by_kind.get(kind, 0) + 1
        fittings_total_area += area

        if kind in VENT_KINDS:
            fittings_vent_m2 += area
            replica = f.get('replica_info') or {}
            vent_openings.append({
                'id':              f.get('id'),
                'kind':            kind,
                'area_m2':         round(area, 3),
                'position':        f.get('position'),
                'surface_normal':  f.get('surface_normal'),
                'face':            replica.get('face'),
                'actuator_id':     f.get('actuator_id'),
                'link_group':      f.get('link_group'),
            })

    # Additive policy: envelope openings + user-placed fittings are both included.
    vent_openings = envelope_vent_openings + vent_openings
    vent_open_m2  = envelope_vent_m2 + fittings_vent_m2
    if fittings_vent_m2 > 0 and envelope_vent_m2 > 0:
        vent_open_src = 'fittings+envelope'
    elif fittings_vent_m2 > 0:
        vent_open_src = 'fittings'
    elif envelope_vent_m2 > 0:
        vent_open_src = 'envelope'
    else:
        vent_open_src = 'none'

    # ---- 11. ACH (uses resolved vent_open_m2) ----
    ach_natural = 0.0
    if volume_m3 > 0 and vent_open_m2 > 0:
        ach_natural = (vent_open_m2 * ASSUMPTIONS['wind_factor_m_s'] / volume_m3) * 3600.0

    forced_m3h = act_totals['exhaust_cmh'] + act_totals['circulation_cmh']
    ach_forced = (forced_m3h / volume_m3) if volume_m3 > 0 else 0.0
    ach_total = ach_natural + ach_forced

    return {
        'floor_m2':       round(floor_m2, 2),
        'envelope_m2':    round(envelope_m2, 2),
        'sidewall_m2':    round(sidewall_m2, 2),
        'roof_m2':        round(roof_m2, 2),
        'gable_m2':       round(gable_m2, 2),
        'volume_m3':      round(volume_m3, 2),
        'glazing_m2':     round(glazing_m2, 2),
        'vent_open_m2':   round(vent_open_m2, 2),
        'vent_open_source':   vent_open_src,          # 'fittings' | 'envelope' | 'none'
        'vent_open_envelope_m2': round(envelope_vent_m2, 2),  # envelope-derived (reference)
        'vent_open_fittings_m2': round(fittings_vent_m2, 2),  # fittings-derived (authoritative)
        'vent_openings':  vent_openings,              # per-opening face/normal/area/actuator
        'u_effective':    round(u_eff, 3),
        'transmittance':  round(t_eff, 3),
        # Absorptance and the heat it lets in are reported separately: with an
        # opaque cover they are the whole of the solar load, and without them
        # on screen there is no way to see why black and white differ.
        'absorptance':    round(absorptance, 3),
        'solar_transmitted_kw': round(solar_transmitted_kw, 2),
        'solar_absorbed_kw':    round(solar_absorbed_kw, 2),
        'heating_kw':         round(heating_kw, 2),
        'cooling_kw':         round(cooling_kw, 2),
        'nameplate_heating_kw': round(nameplate_heating_kw, 2),
        'nameplate_cooling_kw': round(nameplate_cooling_kw, 2),
        'ach_natural':    round(ach_natural, 2),
        'ach_forced':     round(ach_forced, 2),
        'ach_total':      round(ach_total, 2),
        'ach_m3h':        round(ach_total * volume_m3, 0) if volume_m3 else 0,
        'fittings_count': sum(fittings_by_kind.values()),
        'fittings_by_kind': fittings_by_kind,
        'fittings_total_area_m2': round(fittings_total_area, 2),
        'actuator_counts': act_totals['counts'],
        '_note':          'First-pass reference estimate (±5-10%)',
    }


# ----------------------------------------------------------------
# Self-check (run: python facility_calc.py)
# ----------------------------------------------------------------
if __name__ == '__main__':
    standard_single = {
        'structure': 'single',
        'bay_count': 1,
        'geometry_3d': {
            'span_width_m': 7, 'eave_height_m': 2, 'ridge_height_m': 4,
            'length_m': 30, 'roof_type': 'arch'
        },
        'envelope': {
            'layer_count': 1,
            'outer': {'cover_material': 'vinyl_double',
                      'side_vent': {'enabled': True},
                      'roof_vent': {'enabled': False}},
            'inner': None,
            'curtain': {'thermal': False, 'shade': False},
        },
        'actuators': {'circulation_fan': 'fake-output-uuid'},
    }

    standard_double = dict(standard_single)
    standard_double['envelope'] = {
        'layer_count': 2,
        'outer': {'cover_material': 'vinyl_double',
                  'side_vent': {'enabled': True},
                  'roof_vent': {'enabled': False}},
        'inner': {'cover_material': 'non_woven_fabric',
                  'air_gap_m': 0.5,
                  'side_vent': {'enabled': True, 'control_mode': 'synced'},
                  'roof_vent': {'enabled': False, 'control_mode': 'synced'}},
        'curtain': {'thermal': False, 'shade': False},
    }

    print("=== Standard greenhouse (7m × 30m, single layer vinyl_double) ===")
    r1 = compute_capacity(standard_single)
    for k, v in r1.items():
        print(f"  {k:18} {v}")

    print("\n=== Same, double layer (vinyl_double + non_woven_fabric) ===")
    r2 = compute_capacity(standard_double)
    for k, v in r2.items():
        print(f"  {k:18} {v}")

    ratio = r2['heating_kw'] / r1['heating_kw'] if r1['heating_kw'] else 0
    print(f"\nHeating load ratio (double / single): {ratio:.2f}  (target ≈ 0.55~0.65)")
