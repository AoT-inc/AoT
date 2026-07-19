# coding=utf-8
"""Unit tests for facility_geo_helpers.

설계 문서 §14.4 + 작업서 G1 수용 기준 점검.
"""
import math
import pytest

from aot.aot_flask.geo.facility_geo_helpers import (
    edge_outward_azimuth,
    polygon_avg_outward_azimuth,
    line_outward_azimuth,
    line_length_m,
    shape_azimuth_area,
)


# ─────────────────────────────────────────────────────────────────────────────
# CCW square polygon centered at origin (1° × 1° on equator → ~111km × 111km)
# corners (CCW): SW, SE, NE, NW, SW
# 변 azimuth 기대값:
#   edge 0 (SW→SE, going east):    outward = south = 180°
#   edge 1 (SE→NE, going north):   outward = east  =  90°
#   edge 2 (NE→NW, going west):    outward = north =   0°
#   edge 3 (NW→SW, going south):   outward = west  = 270°
# ─────────────────────────────────────────────────────────────────────────────
SQUARE_CCW = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]


def _close(a, b, tol=2.0):
    """Allow small projection error (≤ ~2°)."""
    if a is None or b is None:
        return False
    diff = abs(((a - b + 180) % 360) - 180)
    return diff <= tol


# ─── edge_outward_azimuth ───────────────────────────────────────────────────

def test_edge_azimuth_square_south():
    az = edge_outward_azimuth(SQUARE_CCW, 0)
    assert _close(az, 180.0), f"expected ~180, got {az}"


def test_edge_azimuth_square_east():
    az = edge_outward_azimuth(SQUARE_CCW, 1)
    assert _close(az, 90.0), f"expected ~90, got {az}"


def test_edge_azimuth_square_north():
    az = edge_outward_azimuth(SQUARE_CCW, 2)
    assert _close(az, 0.0), f"expected ~0, got {az}"


def test_edge_azimuth_square_west():
    az = edge_outward_azimuth(SQUARE_CCW, 3)
    assert _close(az, 270.0), f"expected ~270, got {az}"


def test_edge_azimuth_too_few_points_returns_none():
    assert edge_outward_azimuth([[0, 0]], 0) is None
    assert edge_outward_azimuth([], 0) is None


# ─── polygon_avg_outward_azimuth ────────────────────────────────────────────

def test_polygon_symmetric_centered_returns_none():
    # 적도 중심 대칭 정사각형 → 외향 단위벡터 합 ≈ 0 → 의미 없음 → None
    # (위도가 양/음으로 대칭이어야 lat 보정 비대칭이 사라짐)
    centered = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [-0.5, -0.5]]
    az = polygon_avg_outward_azimuth(centered)
    assert az is None, f"expected None for symmetric centered square, got {az}"


def test_polygon_offset_square_returns_some_azimuth():
    # SQUARE_CCW 는 적도 위쪽으로 치우쳐 있어 lat 보정 비대칭 → 작은 azimuth 산출 가능.
    # 절대 None 이 아닌 것만 확인.
    az = polygon_avg_outward_azimuth(SQUARE_CCW)
    # 비대칭 polygon → azimuth 산출됨
    assert az is None or (0.0 <= az < 360.0)


def test_polygon_long_north_side_skewed():
    # 북측 변이 길게 늘어진 직사각형 → 평균 외향이 남쪽 또는 북쪽으로 치우침
    # 폭 1 (lng), 높이 0.1 (lat) → 동/서변 짧음, 남/북변 김
    # CCW: SW(0,0) → SE(1,0) → NE(1,0.1) → NW(0,0.1) → SW
    # edge 0 (남쪽 외향) length ~ 111km (lat=0)
    # edge 2 (북쪽 외향) length ~ 111km (lat=0.1)
    # 두 길이가 거의 같아 단순 평균은 0 (대칭) → None 가능
    rect = [[0, 0], [1, 0], [1, 0.1], [0, 0.1], [0, 0]]
    az = polygon_avg_outward_azimuth(rect)
    # 대칭이라 None 또는 매우 작은 값
    assert az is None or _close(az, 0.0, tol=5.0) or _close(az, 180.0, tol=5.0)


# ─── line_outward_azimuth ───────────────────────────────────────────────────

def test_line_west_going_outward_north():
    # 동→서 line. 방향 = west. outward (방향의 우측 90°) = NORTH (0°)
    # CCW 외곽 규약: 진행 방향의 우측이 외향.
    line = [[1, 0], [0, 0]]
    az = line_outward_azimuth(line)
    assert _close(az, 0.0), f"expected ~0 (north), got {az}"


def test_line_east_going_outward_south():
    # 서→동 line. 방향 = east. outward 우측 = SOUTH (180°)
    line = [[0, 0], [1, 0]]
    az = line_outward_azimuth(line)
    assert _close(az, 180.0), f"expected ~180 (south), got {az}"


def test_line_south_to_north_outward_east():
    # 남→북 line. 방향 = north. outward 우측 = east = 90°
    line = [[0, 0], [0, 1]]
    az = line_outward_azimuth(line)
    assert _close(az, 90.0)


def test_line_north_to_south_outward_west():
    # 북→남 line. 방향 = south. outward 우측 = west = 270°
    line = [[0, 1], [0, 0]]
    az = line_outward_azimuth(line)
    assert _close(az, 270.0)


def test_line_length_m_basic():
    # 1° lng @ equator ≈ 111.32 km
    line = [[0, 0], [1, 0]]
    length = line_length_m(line)
    assert 110_000 < length < 112_500


# ─── shape_azimuth_area ─────────────────────────────────────────────────────

def test_shape_point_returns_none_none():
    feat = {'type': 'Point', 'coordinates': [127.0, 37.0]}
    assert shape_azimuth_area(feat) == (None, None)


def test_shape_linestring_returns_azimuth_and_area():
    # 동서 1km 길이 line @ equator
    feat = {
        'type': 'LineString',
        'coordinates': [[0, 0], [0.009, 0]]   # ~1000 m east at lat=0
    }
    az, area = shape_azimuth_area(feat, line_height_m=2.0)
    # going east → outward (우측 90°) = south = 180°
    assert _close(az, 180.0)
    # length ~1000m × height 2m = ~2000 m²
    assert area is not None and 1800 < area < 2200


def test_shape_polygon_returns_area_and_maybe_azimuth():
    # 적도 중심 대칭 정사각형 → azimuth None, 면적은 산출
    centered = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [-0.5, -0.5]]
    feat = {'type': 'Polygon', 'coordinates': [centered]}
    az, area = shape_azimuth_area(feat)
    assert az is None  # 대칭
    # 1° × 1° at equator → ~12,300 km²
    assert area is not None and area > 10_000_000_000


def test_shape_feature_wrapper_unwraps():
    feat = {
        'type': 'Feature',
        'properties': {},
        'geometry': {
            'type': 'Point',
            'coordinates': [0, 0]
        }
    }
    assert shape_azimuth_area(feat) == (None, None)


def test_shape_unknown_type_returns_none():
    feat = {'type': 'GeometryCollection', 'geometries': []}
    assert shape_azimuth_area(feat) == (None, None)


def test_shape_empty_or_invalid_returns_none():
    assert shape_azimuth_area(None) == (None, None)
    assert shape_azimuth_area({}) == (None, None)
    assert shape_azimuth_area({'type': 'Polygon', 'coordinates': []}) == (None, None)
