# coding=utf-8
"""Tests for aot.utils.geo_tiler — XYZ tile pyramid generation from a 4-corner
image placement."""
import os
import math

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from aot.utils import geo_tiler


def _make_image(path, w, h):
    # Distinct quadrant colours so a sampled tile is visibly non-uniform.
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (255 if x < w // 2 else 0,
                        255 if y < h // 2 else 0,
                        128)
    img.save(path, 'PNG')


def test_merc_roundtrip():
    for lon, lat in [(126.978, 37.5665), (0.0, 0.0), (-122.4, 37.8)]:
        mx, my = geo_tiler._lonlat_to_merc(lon, lat)
        lon2, lat2 = geo_tiler._merc_to_lonlat(mx, my)
        assert abs(lon - lon2) < 1e-6
        assert abs(lat - lat2) < 1e-6


def test_homography_maps_corners():
    # lng/lat corners -> pixel rectangle; corners must map exactly.
    coords = [[126.9770, 37.5670], [126.9790, 37.5670],
              [126.9790, 37.5660], [126.9770, 37.5660]]
    W, H = 400, 300
    ll = [(c[0], c[1]) for c in coords]
    rect = [(0, 0), (W, 0), (W, H), (0, H)]
    Hm = geo_tiler._solve_homography(ll, rect)
    for (lon, lat), (ex, ey) in zip(ll, rect):
        ux, uy = geo_tiler._apply_h(Hm, lon, lat)
        assert abs(ux - ex) < 1e-3
        assert abs(uy - ey) < 1e-3


def test_zoom_range_bounded():
    coords = [[126.9770, 37.5670], [126.9790, 37.5670],
              [126.9790, 37.5660], [126.9770, 37.5660]]
    minz, maxz, bbox = geo_tiler._compute_zoom_range(coords, width_px=8000)
    assert 0 <= minz <= maxz <= geo_tiler.HARD_MAX_ZOOM
    minx, miny, maxx, maxy = bbox
    assert maxx > minx and maxy > miny


def test_generate_tiles(tmp_path):
    src = os.path.join(str(tmp_path), 'src.png')
    _make_image(src, 512, 384)
    coords = [[126.9770, 37.5670], [126.9790, 37.5670],
              [126.9790, 37.5660], [126.9770, 37.5660]]
    out = os.path.join(str(tmp_path), 'tiles')
    info = geo_tiler.generate_tiles(src, coords, out, max_tiles=5000)

    assert info['tile_count'] > 0
    assert info['minzoom'] <= info['maxzoom']
    # At least one tile file exists and is a valid 256px PNG.
    found = []
    for root, _dirs, files in os.walk(out):
        for f in files:
            if f.endswith('.png'):
                found.append(os.path.join(root, f))
    assert found
    t = Image.open(found[0])
    assert t.size == (geo_tiler.TILE_SIZE, geo_tiler.TILE_SIZE)
    assert t.mode == 'RGBA'  # transparency outside the footprint


def test_generate_tiles_atomic_replace(tmp_path):
    src = os.path.join(str(tmp_path), 'src.png')
    _make_image(src, 256, 256)
    coords = [[126.9770, 37.5670], [126.9790, 37.5670],
              [126.9790, 37.5660], [126.9770, 37.5660]]
    out = os.path.join(str(tmp_path), 'tiles')
    geo_tiler.generate_tiles(src, coords, out, max_tiles=2000)
    first = sum(len(f) for _r, _d, f in os.walk(out))
    # Re-run: should replace cleanly, no leftover temp dir.
    geo_tiler.generate_tiles(src, coords, out, max_tiles=2000)
    assert first > 0
    assert not os.path.isdir(os.path.join(str(tmp_path), '.tiles.tmp'))
