# coding=utf-8
"""Tests for geo_photo_georef.py — drone photo footprint computation."""
import math

import pytest

from aot.utils.geo_photo_georef import (
    compute_footprint,
    default_footprint,
    extract_photo_metadata,
)


def _ew_ns_extent(corners, lat):
    """Return (east-west, north-south) bounding extent in metres for 4 corners."""
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    ew = (max(lons) - min(lons)) * 111320.0 * math.cos(math.radians(lat))
    ns = (max(lats) - min(lats)) * 111320.0
    return ew, ns


def _center(corners):
    lons = [c[0] for c in corners]
    lats = [c[1] for c in corners]
    return sum(lons) / 4.0, sum(lats) / 4.0


# ─────────────────────────────────────────────────────────────────────────────
# compute_footprint
# ─────────────────────────────────────────────────────────────────────────────

def test_nadir_footprint_scale_and_center():
    # 100 m altitude, 24 mm (35mm-equiv) -> ground width 36/24*100 = 150 m
    meta = {'lat': 37.5, 'lon': 127.0, 'rel_altitude': 100.0, 'focal_35mm': 24.0,
            'width': 4000, 'height': 3000, 'yaw': 0.0, 'has_geo': True}
    fp = compute_footprint(meta)
    assert fp is not None and len(fp) == 4
    clon, clat = _center(fp)
    assert clon == pytest.approx(127.0, abs=1e-6)
    assert clat == pytest.approx(37.5, abs=1e-6)
    ew, ns = _ew_ns_extent(fp, 37.5)
    assert ew == pytest.approx(150.0, abs=0.5)
    assert ns == pytest.approx(112.5, abs=0.5)  # 4:3 aspect


def test_yaw_90_rotates_footprint():
    base = {'lat': 37.5, 'lon': 127.0, 'rel_altitude': 100.0, 'focal_35mm': 24.0,
            'width': 4000, 'height': 3000, 'has_geo': True}
    fp = compute_footprint({**base, 'yaw': 90.0})
    ew, ns = _ew_ns_extent(fp, 37.5)
    # A 90° heading swaps the bounding extents (image "up" now points east).
    assert ew == pytest.approx(112.5, abs=0.5)
    assert ns == pytest.approx(150.0, abs=0.5)


def test_corner_order_is_tl_tr_br_bl():
    meta = {'lat': 37.5, 'lon': 127.0, 'rel_altitude': 100.0, 'focal_35mm': 24.0,
            'width': 4000, 'height': 3000, 'yaw': 0.0, 'has_geo': True}
    tl, tr, br, bl = compute_footprint(meta)
    assert tl[1] > bl[1]          # top above bottom
    assert tr[1] > br[1]
    assert tl[0] < tr[0]          # left west of right
    assert bl[0] < br[0]


def test_insufficient_metadata_returns_none():
    assert compute_footprint({'lat': 37.5, 'lon': 127.0, 'has_geo': False}) is None
    assert compute_footprint({'has_geo': True}) is None  # no lat/lon
    assert compute_footprint(None) is None


def test_default_box_uses_requested_ground_width():
    df = default_footprint(37.5, 127.0, 80.0)
    assert df is not None
    ew, ns = _ew_ns_extent(df, 37.5)
    assert ew == pytest.approx(80.0, abs=0.5)
    assert ns == pytest.approx(60.0, abs=0.5)  # default 4:3


def test_focal_length_fallback_without_35mm_equiv():
    # No focal_35mm: should still produce a footprint using the crop-factor estimate.
    meta = {'lat': 37.5, 'lon': 127.0, 'rel_altitude': 100.0, 'focal_length': 16.0,
            'width': 4000, 'height': 3000, 'yaw': 0.0, 'has_geo': True}
    fp = compute_footprint(meta)
    assert fp is not None
    ew, _ = _ew_ns_extent(fp, 37.5)
    # est_focal35 = 16 * 1.5 = 24 -> width 150
    assert ew == pytest.approx(150.0, abs=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# extract_photo_metadata (degradation)
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_on_non_image_degrades_gracefully():
    meta = extract_photo_metadata(b'this is not an image')
    assert meta.get('has_geo') is False


def test_xmp_scan_pulls_dji_pose():
    # Minimal synthetic XMP packet with DJI drone-dji fields.
    xmp = (
        b'\xff\xd8\xff\xe1 garbage'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:Description '
        b'drone-dji:RelativeAltitude="+62.30" '
        b'drone-dji:GimbalYawDegree="+135.0" '
        b'drone-dji:GpsLatitude="37.123456" '
        b'drone-dji:GpsLongitude="127.654321"/>'
        b'</x:xmpmeta>'
    )
    from aot.utils.geo_photo_georef import _parse_xmp
    out = _parse_xmp(xmp)
    assert out.get('rel_altitude') == pytest.approx(62.30)
    assert out.get('gimbal_yaw') == pytest.approx(135.0)
    assert out.get('xmp_lat') == pytest.approx(37.123456)
    assert out.get('xmp_lon') == pytest.approx(127.654321)
