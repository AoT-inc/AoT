# coding=utf-8
"""
facility_geo_helpers.py — GeoJSON feature → (azimuth_deg, area_m2) 산출.

설계 문서 §14.4 참조.

GeoJSON 규약 (RFC 7946):
- 외곽 ring 은 CCW (counter-clockwise)
- coordinates 는 [longitude, latitude]

좌표계: 입력은 lat/lng (도). 작은 사이트 가정으로 평균 위도 기준 등각투영 → 미터.
azimuth: 방위각 (0=N, 90=E, 180=S, 270=W).

@phase active
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

from aot.aot_flask.geo.facility_calc import (
    _ring_area_m2,
    _ring_perimeter_m,
    ASSUMPTIONS,
)

# Line feature → 면적 산출 시 사용할 기본 개구부 높이 (m).
# vent_height_m 은 facility_calc.ASSUMPTIONS 에 이미 정의되어 있어 동일 값 재사용.
DEFAULT_LINE_HEIGHT_M = ASSUMPTIONS.get('vent_height_m', 1.2)


def _meters_per_deg(lat0_deg: float) -> Tuple[float, float]:
    """평균 위도에서 위도/경도 1도가 몇 미터인지."""
    m_per_deg_lat = 111320.0
    m_per_deg_lng = m_per_deg_lat * math.cos(math.radians(lat0_deg))
    return m_per_deg_lat, m_per_deg_lng


def _bearing_from_normal(nx: float, ny: float) -> Optional[float]:
    """미터 좌표계 외향 법선 (nx=east, ny=north) → 방위각 deg (0=N, 90=E)."""
    if nx == 0.0 and ny == 0.0:
        return None
    bearing_rad = math.atan2(nx, ny)
    bearing_deg = math.degrees(bearing_rad)
    if bearing_deg < 0:
        bearing_deg += 360.0
    return bearing_deg


def edge_outward_azimuth(coords, edge_index: int = 0) -> Optional[float]:
    """polygon 외곽 변의 외향 법선 방위각 (deg, 0–360, 0=N, 90=E).

    GeoJSON CCW 외곽 가정. 변 (p1 → p2) 에 대해 외향 = (p2 − p1) 우측 90° 회전
    = (dy, −dx) — 미터 좌표계에서.

    Args:
        coords: list of [lng, lat] — closed ring (마지막 점 = 첫 점)
        edge_index: 어느 변을 볼지 (0..n-2)

    Returns:
        방위각 deg, 또는 None (좌표 부족/0벡터).
    """
    if not coords or len(coords) < 2:
        return None
    n = len(coords)
    if edge_index < 0 or edge_index >= n - 1:
        edge_index = 0

    p1 = coords[edge_index]
    p2 = coords[edge_index + 1]

    lat0 = (p1[1] + p2[1]) / 2.0
    m_per_deg_lat, m_per_deg_lng = _meters_per_deg(lat0)

    dx = (p2[0] - p1[0]) * m_per_deg_lng   # east meters
    dy = (p2[1] - p1[1]) * m_per_deg_lat   # north meters

    # CCW outer ring → outward normal = rotate (dx, dy) by -90° = (dy, -dx)
    nx = dy
    ny = -dx
    return _bearing_from_normal(nx, ny)


def _edge_length_m(p1, p2) -> float:
    lat0 = (p1[1] + p2[1]) / 2.0
    m_per_deg_lat, m_per_deg_lng = _meters_per_deg(lat0)
    dx = (p2[0] - p1[0]) * m_per_deg_lng
    dy = (p2[1] - p1[1]) * m_per_deg_lat
    return math.sqrt(dx * dx + dy * dy)


def polygon_avg_outward_azimuth(coords) -> Optional[float]:
    """polygon 모든 외곽 변의 외향 azimuth 의 변 길이 가중 평균.

    원형 평균은 단순 산술평균이 아닌 단위벡터 합으로 계산한다.
    매우 대칭인 polygon (정사각형, 원형) 은 합이 0 에 가까워 None 반환 가능 —
    이 경우 polygon 의 평면 azimuth 는 의미가 약하므로 호출측이 line 또는
    가장 긴 변 단독으로 처리하는 것이 좋다.
    """
    if not coords or len(coords) < 3:
        return None

    sum_x = 0.0
    sum_y = 0.0
    n = len(coords)
    edges = n - 1  # closed ring 가정 (마지막 = 첫 점)

    for i in range(edges):
        p1, p2 = coords[i], coords[i + 1]
        bearing = edge_outward_azimuth(coords, i)
        if bearing is None:
            continue
        length = _edge_length_m(p1, p2)
        if length <= 0:
            continue
        rad = math.radians(bearing)
        # 단위벡터 분해 (북=cos, 동=sin) 후 길이 가중
        sum_x += math.sin(rad) * length   # east
        sum_y += math.cos(rad) * length   # north

    if abs(sum_x) < 1e-6 and abs(sum_y) < 1e-6:
        return None  # 대칭 → 무의미
    return _bearing_from_normal(sum_x, sum_y)


def line_outward_azimuth(coords) -> Optional[float]:
    """LineString feature → 외향 법선 방위각.

    line 은 polygon 외곽이 아니므로 "외향" 정의가 모호.
    관행: 사용자가 그린 방향 (start → end) 의 우측 90° 회전을 외향으로 본다.
    (실외 측창은 시설 외부 시선으로 그린다는 가정.)
    """
    return edge_outward_azimuth(coords, 0)


def line_length_m(coords) -> float:
    """LineString 의 누적 길이 (m)."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(len(coords) - 1):
        total += _edge_length_m(coords[i], coords[i + 1])
    return total


def shape_azimuth_area(feature: dict,
                       line_height_m: float = DEFAULT_LINE_HEIGHT_M
                       ) -> Tuple[Optional[float], Optional[float]]:
    """GeoJSON feature → (azimuth_deg, area_m2).

    feature 는 GeoJSON Feature 또는 Geometry dict 모두 허용.

    Geometry types:
        Point        → (None, None)        # 점은 방향/면적 없음
        LineString   → (외향 azimuth, length × line_height_m)
        Polygon      → (avg outward azimuth, ring area)
        MultiPolygon → (None, total area)  # 평균 azimuth 의미 약함
        그 외        → (None, None)
    """
    if not feature:
        return None, None

    # Feature wrapper unwrap
    geom = feature
    if isinstance(feature, dict) and feature.get('type') == 'Feature':
        geom = feature.get('geometry') or {}

    if not isinstance(geom, dict):
        return None, None

    gtype = geom.get('type')
    coords = geom.get('coordinates')

    if gtype == 'Point':
        return None, None

    if gtype == 'LineString':
        if not coords or len(coords) < 2:
            return None, None
        azimuth = line_outward_azimuth(coords)
        length = line_length_m(coords)
        area = length * float(line_height_m) if length > 0 else None
        return azimuth, area

    if gtype == 'Polygon':
        if not coords or not coords[0]:
            return None, None
        outer = coords[0]
        azimuth = polygon_avg_outward_azimuth(outer)
        area = _ring_area_m2(outer) if len(outer) >= 3 else None
        return azimuth, area

    if gtype == 'MultiPolygon':
        if not coords:
            return None, None
        total = 0.0
        for poly in coords:
            if poly and poly[0] and len(poly[0]) >= 3:
                total += _ring_area_m2(poly[0])
        return None, (total if total > 0 else None)

    return None, None
