# coding=utf-8
"""
geo/irrigation_nozzles.py — 관수 노즐 배치에서 엽면 습윤 위험 지표를 산출한다.

시설 디자이너가 저장하는 ``irrigation_device`` 피팅은 노즐 한 개당
``position{x,y,z}`` / ``orientation`` / ``sub_type`` / ``flow_lph`` / ``radius_m``
를 모두 갖고 있다. 지금까지 통합환경제어(env_coordinator)로 넘어가는 값은
유량 합계 하나뿐이라, 제어기는 "물이 얼마나 나오는지"만 알고 "어디에, 어느
방향으로, 얼마나 굵게 떨어지는지"를 몰랐다.

2026-07-31 aot-005 육묘장 일소 사건: VPD 편차가 최대인 정오에 포그 이득이
가장 커서 조율자가 분무를 최대로 선택했고, 갓 출아한 자엽에 물방울이 맺힌
채로 최대 일사를 받아 일소가 발생했다. 제어기가 "잎이 젖는다"는 사실 자체를
모른 것이 근본 원인이다.

이 모듈은 배치 도면만으로 다음을 산출해 그 공백을 메운다:

  wetting          — 엽면 습윤형 노즐인가 (고압 미세포그가 아닌가)
  precip_mm_h_max  — 최대 강수강도 [mm/h] (= L/h/m²)
  overlap_max      — 살수 원이 겹치는 최대 중첩 수
  min_height_m     — 최저 설치 높이 [m]

판정 기준(WETTING_*)의 근거: 고압 미세포그(액적 5~10µm, 40~70bar)는 노즐당
3~7 L/h, 확산 반경 1m 미만이다. 그보다 유량이 크거나 반경이 넓으면 액적이
100µm 이상이라 잎에 닿는 즉시 맺힌다. 하향(down) 분사는 작물 직상 낙하라
그 자체로 습윤 요인이다.
"""

from __future__ import annotations

import math

# ─────────────────────────────────────────────────────────────────────────────
# 습윤형 판정 임계
# ─────────────────────────────────────────────────────────────────────────────

# 노즐당 유량이 이 값 이상이면 미세포그가 아니다 [L/h]
WETTING_FLOW_LPH = 15.0
# 살수 반경이 이 값 이상이면 미세포그 확산이 아니라 스프링클러 패턴이다 [m]
WETTING_RADIUS_M = 1.0

# 강수강도 격자 샘플링 파라미터
_GRID_MIN_CELL_M = 0.25     # 최소 격자 한 변 [m]
_GRID_MAX_CELLS  = 200_000  # 누적 셀 수 상한 (연산량 방어)


def _fnum(value, default=0.0) -> float:
    """None/빈문자/문자열 숫자를 안전하게 float 로 변환한다."""
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _device_xz(dev) -> tuple:
    """노즐의 수평 좌표 (x, z). 좌표가 없으면 None."""
    pos = dev.get('position')
    if not isinstance(pos, dict):
        return None
    x = pos.get('x')
    z = pos.get('z')
    if x is None or z is None:
        return None
    return _fnum(x), _fnum(z)


def _device_height(dev, layer_height=None):
    """노즐 설치 높이 [m]. position.y 우선, 없으면 레이어 높이."""
    pos = dev.get('position')
    if isinstance(pos, dict) and pos.get('y') is not None:
        return _fnum(pos.get('y'))
    if layer_height is not None:
        return _fnum(layer_height)
    return None


def compute_precipitation(devices) -> dict:
    """살수 원 격자 샘플링으로 강수강도와 중첩도를 산출한다.

    노즐 하나가 반경 r 원에 flow_lph 를 균등 살포한다고 보면 그 원 안의
    강수강도는 ``flow_lph / (π r²)`` [L/h/m²] 이고, 1 L/m² = 1 mm 이므로
    그대로 mm/h 다. 겹치는 지점은 각 노즐 기여를 더한다.

    격자를 순회하며 노즐을 찾는(gather) 대신 노즐마다 자기 원의 외접
    사각형 셀에만 기여를 뿌리는(scatter) 방식이라 연산량이 노즐 수에
    비례한다.

    Returns:
        {'precip_mm_h_max', 'precip_mm_h_mean', 'overlap_max', 'covered_m2'}
        유효 노즐이 없으면 값은 모두 0.
    """
    empty = {
        'precip_mm_h_max':  0.0,
        'precip_mm_h_mean': 0.0,
        'overlap_max':      0,
        'covered_m2':       0.0,
    }

    usable = []
    for d in devices:
        xz = _device_xz(d)
        if xz is None:
            continue
        r    = _fnum(d.get('radius_m'))
        flow = _fnum(d.get('flow_lph'))
        if r <= 0.0 or flow <= 0.0:
            continue
        usable.append((xz[0], xz[1], r, flow))

    if not usable:
        return empty

    # 격자 크기: 가장 작은 살수 원을 최소 8칸으로 나눌 수 있게 잡되,
    # 총 셀 수가 상한을 넘으면 키운다.
    min_r = min(u[2] for u in usable)
    cell = max(_GRID_MIN_CELL_M, min_r / 4.0)
    while True:
        cells_per_nozzle = (2.0 * max(u[2] for u in usable) / cell + 1.0) ** 2
        if cells_per_nozzle * len(usable) <= _GRID_MAX_CELLS:
            break
        cell *= 2.0

    density: dict = {}   # (i, j) → mm/h 누적
    overlap: dict = {}   # (i, j) → 중첩 노즐 수

    for x, z, r, flow in usable:
        intensity = flow / (math.pi * r * r)      # mm/h — 이 노즐 단독 기여
        i0 = int(math.floor((x - r) / cell))
        i1 = int(math.floor((x + r) / cell))
        j0 = int(math.floor((z - r) / cell))
        j1 = int(math.floor((z + r) / cell))
        r_sq = r * r
        for i in range(i0, i1 + 1):
            cx = (i + 0.5) * cell
            dx = cx - x
            if dx * dx > r_sq:
                continue
            for j in range(j0, j1 + 1):
                cz = (j + 0.5) * cell
                dz = cz - z
                if dx * dx + dz * dz > r_sq:
                    continue
                key = (i, j)
                density[key] = density.get(key, 0.0) + intensity
                overlap[key] = overlap.get(key, 0) + 1

    if not density:
        return empty

    values = list(density.values())
    return {
        'precip_mm_h_max':  round(max(values), 2),
        'precip_mm_h_mean': round(sum(values) / len(values), 2),
        'overlap_max':      max(overlap.values()),
        'covered_m2':       round(len(density) * cell * cell, 2),
    }


def summarize_nozzles(devices, layer_height=None) -> dict:
    """노즐 목록에서 엽면 습윤 위험 요약을 만든다.

    Args:
        devices:      ``irrigation_device`` 피팅 dict 목록
        layer_height: 레이어 설치 높이 [m] — position.y 가 없을 때 사용

    Returns:
        요약 dict. 노즐이 하나도 없으면 count=0, wetting=False.
    """
    summary = {
        'count':           0,
        'sprinkler_count': 0,
        'drip_count':      0,
        'down_count':      0,
        'wetting':         False,
        'wetting_reasons': [],
        'max_flow_lph':    0.0,
        'min_radius_m':    0.0,
        'min_height_m':    None,
        'total_flow_lph':  0.0,
        'precip_mm_h_max':  0.0,
        'precip_mm_h_mean': 0.0,
        'overlap_max':      0,
        'covered_m2':       0.0,
    }
    if not devices:
        return summary

    sprinklers = []
    radii      = []
    heights    = []
    for d in devices:
        summary['count'] += 1
        sub = (d.get('sub_type') or 'sprinkler').strip().lower()
        flow = _fnum(d.get('flow_lph'))
        summary['total_flow_lph'] += flow
        summary['max_flow_lph'] = max(summary['max_flow_lph'], flow)

        if sub == 'drip':
            summary['drip_count'] += 1
            continue

        summary['sprinkler_count'] += 1
        sprinklers.append(d)
        if (d.get('orientation') or 'down').strip().lower() == 'down':
            summary['down_count'] += 1
        r = _fnum(d.get('radius_m'))
        if r > 0.0:
            radii.append(r)
        h = _device_height(d, layer_height)
        if h is not None:
            heights.append(h)

    summary['min_radius_m'] = round(min(radii), 2) if radii else 0.0
    summary['min_height_m'] = round(min(heights), 2) if heights else None
    summary['total_flow_lph'] = round(summary['total_flow_lph'], 1)
    summary['max_flow_lph'] = round(summary['max_flow_lph'], 1)

    # ── 습윤형 판정 — 드립 전용이면 잎에 닿지 않으므로 대상 아님 ──────────────
    if not sprinklers:
        return summary

    reasons = []
    max_spr_flow = max(_fnum(d.get('flow_lph')) for d in sprinklers)
    if max_spr_flow >= WETTING_FLOW_LPH:
        reasons.append('flow')
    if radii and max(radii) >= WETTING_RADIUS_M:
        reasons.append('radius')
    if summary['down_count'] > 0:
        reasons.append('downward')

    summary['wetting'] = bool(reasons)
    summary['wetting_reasons'] = reasons
    summary.update(compute_precipitation(sprinklers))
    return summary


def nozzles_by_actuator(fittings) -> dict:
    """관수 액추에이터(Output uuid) → 노즐 요약 맵을 만든다.

    ``irrigation_layer.actuator_id`` (레이어 전체를 여닫는 펌프·밸브)와
    ``irrigation_valve.actuator_id`` (레이어 안의 개별 밸브) 양쪽을 모두 훑는다.
    밸브는 담당 배관(pipe_id)이 지정돼 있으면 그 배관의 노즐만, 아니면 레이어
    전체 노즐을 대상으로 본다.

    같은 Output 이 여러 레이어에 걸쳐 있으면 노즐을 합쳐서 한 번에 평가한다
    (한 밸브가 여는 물길 전체가 곧 그 액추에이터의 습윤 특성이다).

    Args:
        fittings: GeoFacility.fittings 목록

    Returns:
        {output_uuid: 노즐 요약 dict}
    """
    if not fittings:
        return {}

    layers = [f for f in fittings if f.get('kind') == 'irrigation_layer']
    valves = [f for f in fittings if f.get('kind') == 'irrigation_valve']
    devs   = [f for f in fittings if f.get('kind') == 'irrigation_device']
    if not devs:
        return {}

    devs_by_layer: dict = {}
    for d in devs:
        devs_by_layer.setdefault(d.get('layer_id'), []).append(d)

    layer_height = {L.get('id'): L.get('height_m') for L in layers}

    # {output_uuid: ([devices], [heights])} — 액추에이터별로 노즐을 모은 뒤 일괄 평가
    collected: dict = {}

    def _collect(aid, device_list, height):
        if not aid or not device_list:
            return
        entry = collected.setdefault(aid, {'devices': [], 'heights': []})
        entry['devices'].extend(device_list)
        if height is not None:
            entry['heights'].append(_fnum(height))

    for L in layers:
        lid = L.get('id')
        _collect(L.get('actuator_id'), devs_by_layer.get(lid) or [], L.get('height_m'))

    for v in valves:
        lid = v.get('layer_id')
        layer_devs = devs_by_layer.get(lid) or []
        pipe_id = v.get('pipe_id')
        if pipe_id:
            scoped = [d for d in layer_devs if d.get('pipe_id') == pipe_id]
            # 밸브가 특정 배관에 붙어 있어도 그 배관에 노즐이 없으면
            # (지관 생성 전 등) 레이어 전체로 폴백한다.
            layer_devs = scoped or layer_devs
        _collect(v.get('actuator_id'), layer_devs, layer_height.get(lid))

    result = {}
    for aid, entry in collected.items():
        heights = entry['heights']
        result[aid] = summarize_nozzles(
            entry['devices'],
            layer_height=(min(heights) if heights else None),
        )
    return result
