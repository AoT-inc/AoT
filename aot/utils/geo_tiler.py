# coding=utf-8
"""
geo_tiler.py
Slippy-map (XYZ / EPSG:3857) tile pyramid generator for large image overlays.

A ``gis_image_overlay`` is normally drawn as a single MapLibre ``image`` source
defined by four ground-corner coordinates. That is fine for small drone shots,
but a large orthomosaic exceeds the WebGL ``MAX_TEXTURE_SIZE`` and wastes memory
(the whole image is resident at every zoom). For such images we pre-generate a
standard ``{z}/{x}/{y}.png`` tile pyramid so the map only loads the 256px tiles
visible at the current zoom — the proper zoom-responsive strategy.

The image is placed by a planar rubber-sheet: the 4 corner lng/lat coordinates
map to the image's pixel rectangle (TL,TR,BR,BL -> (0,0),(W,0),(W,H),(0,H)).
That is a homography (lng/lat -> pixel). For each output tile we project the
tile's web-mercator corners back through that homography to source pixels and
resample with a PIL PERSPECTIVE transform. Only Pillow + numpy are required
(both existing project deps); no GDAL.

@phase active
@stability experimental
"""
import math
import os
import shutil

try:
    import numpy as np
    from PIL import Image
    _DEPS_OK = True
except Exception:  # pragma: no cover - Pillow/numpy are hard project deps
    _DEPS_OK = False

# Web-mercator constant: half the equatorial circumference in metres.
ORIGIN_SHIFT = 2.0 * math.pi * 6378137.0 / 2.0  # 20037508.342789244
TILE_SIZE = 256

# Safety cap: refuse to generate an unbounded pyramid. If the native resolution
# would require more tiles than this across the whole pyramid, maxzoom is reduced
# until the estimate fits. Keeps a runaway upload from filling the disk.
DEFAULT_MAX_TILES = 60000
# Never resolve finer than this regardless of native pixel size.
HARD_MAX_ZOOM = 24


# ---------------------------------------------------------------------------
# Web-mercator helpers
# ---------------------------------------------------------------------------

def _lonlat_to_merc(lon, lat):
    """lng/lat (deg) -> EPSG:3857 metres."""
    mx = lon * ORIGIN_SHIFT / 180.0
    lat = max(-85.05112878, min(85.05112878, lat))
    my = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    my = my * ORIGIN_SHIFT / 180.0
    return mx, my


def _merc_to_lonlat(mx, my):
    """EPSG:3857 metres -> lng/lat (deg)."""
    lon = (mx / ORIGIN_SHIFT) * 180.0
    lat = (my / ORIGIN_SHIFT) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def _resolution(zoom):
    """3857 metres per pixel at the given zoom (256px tiles)."""
    return (2.0 * ORIGIN_SHIFT) / (TILE_SIZE * (2 ** zoom))


def _merc_to_pixel(mx, my, zoom):
    """3857 metres -> global pixel coords (origin top-left) at zoom."""
    res = _resolution(zoom)
    px = (mx + ORIGIN_SHIFT) / res
    py = (ORIGIN_SHIFT - my) / res
    return px, py


def _tile_bounds_merc(z, x, y):
    """3857 bounds (minx, miny, maxx, maxy) of tile (z,x,y)."""
    res = _resolution(z)
    minx = x * TILE_SIZE * res - ORIGIN_SHIFT
    maxx = (x + 1) * TILE_SIZE * res - ORIGIN_SHIFT
    maxy = ORIGIN_SHIFT - y * TILE_SIZE * res
    miny = ORIGIN_SHIFT - (y + 1) * TILE_SIZE * res
    return minx, miny, maxx, maxy


# ---------------------------------------------------------------------------
# Homography
# ---------------------------------------------------------------------------

def _solve_homography(src_pts, dst_pts):
    """Return the 3x3 homography H mapping src_pts -> dst_pts (4 correspondences)."""
    A = []
    B = []
    for (sx, sy), (dx, dy) in zip(src_pts, dst_pts):
        A.append([sx, sy, 1, 0, 0, 0, -dx * sx, -dx * sy])
        B.append(dx)
        A.append([0, 0, 0, sx, sy, 1, -dy * sx, -dy * sy])
        B.append(dy)
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    h = np.linalg.solve(A, B)
    return np.array([[h[0], h[1], h[2]],
                     [h[3], h[4], h[5]],
                     [h[6], h[7], 1.0]], dtype=np.float64)


def _apply_h(H, x, y):
    """Apply homography H to a single point."""
    d = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    if abs(d) < 1e-12:
        d = 1e-12
    ux = (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / d
    uy = (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / d
    return ux, uy


def _pil_perspective_coeffs(dst_quad, src_quad):
    """PIL PERSPECTIVE coeffs mapping each OUTPUT pixel (dst_quad) to a source
    pixel (src_quad). Both are 4 (x,y) corners in matching order."""
    matrix = []
    for (dx, dy), (sx, sy) in zip(dst_quad, src_quad):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    A = np.asarray(matrix, dtype=np.float64)
    B = np.asarray([c for pt in src_quad for c in pt], dtype=np.float64)
    res = np.linalg.solve(A, B)
    return res.tolist()


# ---------------------------------------------------------------------------
# Zoom range
# ---------------------------------------------------------------------------

def _compute_zoom_range(coords, width_px, max_tiles=DEFAULT_MAX_TILES):
    """Derive (minzoom, maxzoom) plus the 3857 bbox from corners + image width.

    maxzoom is where a tile pixel matches the image's native ground resolution;
    minzoom is where the whole footprint fits within ~one tile. maxzoom is
    clamped so the total tile estimate stays under ``max_tiles``.
    """
    merc = [_lonlat_to_merc(lon, lat) for lon, lat in coords]
    xs = [m[0] for m in merc]
    ys = [m[1] for m in merc]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    # Native resolution: top edge length (TL->TR) in 3857 metres / image width.
    tl, tr = merc[0], merc[1]
    top_len = math.hypot(tr[0] - tl[0], tr[1] - tl[1])
    bl, br = merc[3], merc[2]
    bot_len = math.hypot(br[0] - bl[0], br[1] - bl[1])
    edge = max(top_len, bot_len)
    native_res = (edge / width_px) if width_px else _resolution(18)

    maxzoom = int(math.ceil(math.log2((2.0 * ORIGIN_SHIFT) / (TILE_SIZE * native_res))))
    maxzoom = max(0, min(HARD_MAX_ZOOM, maxzoom))

    bbox_w = max(maxx - minx, 1e-6)
    bbox_h = max(maxy - miny, 1e-6)
    span = max(bbox_w, bbox_h)
    minzoom = int(math.floor(math.log2((2.0 * ORIGIN_SHIFT) / span)))
    minzoom = max(0, min(minzoom, maxzoom))

    # Clamp maxzoom so the pyramid stays bounded.
    def _estimate(mz):
        total = 0
        for z in range(minzoom, mz + 1):
            res = _resolution(z)
            tx = bbox_w / (TILE_SIZE * res) + 1
            ty = bbox_h / (TILE_SIZE * res) + 1
            total += math.ceil(tx) * math.ceil(ty)
        return total

    while maxzoom > minzoom and _estimate(maxzoom) > max_tiles:
        maxzoom -= 1

    return minzoom, maxzoom, (minx, miny, maxx, maxy)


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def generate_tiles(image_path, coords, out_dir, max_tiles=DEFAULT_MAX_TILES):
    """Generate an XYZ tile pyramid for a 4-corner-placed image.

    Args:
        image_path: path to the source image on disk.
        coords:     4 [lng, lat] corners in TL, TR, BR, BL order.
        out_dir:    directory to write ``{z}/{x}/{y}.png`` into. Created fresh
                    (any existing content is replaced atomically via a temp dir).
        max_tiles:  pyramid size cap (maxzoom is reduced to respect it).

    Returns:
        dict: { 'minzoom', 'maxzoom', 'tile_count' }.

    Raises:
        RuntimeError if dependencies are missing or coords are invalid.
    """
    if not _DEPS_OK:
        raise RuntimeError('geo_tiler requires Pillow and numpy')
    if not coords or len(coords) != 4:
        raise RuntimeError('coords must be 4 [lng,lat] corners')

    src = Image.open(image_path).convert('RGBA')
    W, H = src.size

    # Homography: lng/lat -> source pixel (TL,TR,BR,BL -> image rectangle).
    ll = [(float(c[0]), float(c[1])) for c in coords]
    px_rect = [(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))]
    H_ll2px = _solve_homography(ll, px_rect)

    minzoom, maxzoom, (minx, miny, maxx, maxy) = _compute_zoom_range(coords, W, max_tiles)

    # Write into a temp dir, then swap, so a half-finished run never replaces a
    # good pyramid.
    parent = os.path.dirname(os.path.abspath(out_dir))
    base = os.path.basename(os.path.abspath(out_dir))
    tmp_dir = os.path.join(parent, '.%s.tmp' % base)
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    fill = (0, 0, 0, 0)
    dst_quad = [(0.0, 0.0), (float(TILE_SIZE), 0.0),
                (float(TILE_SIZE), float(TILE_SIZE)), (0.0, float(TILE_SIZE))]
    tile_count = 0

    for z in range(minzoom, maxzoom + 1):
        x0, _ = _merc_to_pixel(minx, maxy, z)
        x1, _ = _merc_to_pixel(maxx, miny, z)
        _, y0 = _merc_to_pixel(minx, maxy, z)
        _, y1 = _merc_to_pixel(maxx, miny, z)
        tx_min = int(math.floor(min(x0, x1) / TILE_SIZE))
        tx_max = int(math.floor(max(x0, x1) / TILE_SIZE))
        ty_min = int(math.floor(min(y0, y1) / TILE_SIZE))
        ty_max = int(math.floor(max(y0, y1) / TILE_SIZE))
        nmax = 2 ** z - 1
        tx_min = max(0, tx_min); tx_max = min(nmax, tx_max)
        ty_min = max(0, ty_min); ty_max = min(nmax, ty_max)

        for tx in range(tx_min, tx_max + 1):
            for ty in range(ty_min, ty_max + 1):
                bminx, bminy, bmaxx, bmaxy = _tile_bounds_merc(z, tx, ty)
                # Tile corners (TL,TR,BR,BL) in 3857 -> lng/lat -> source pixel.
                corners_merc = [(bminx, bmaxy), (bmaxx, bmaxy),
                                (bmaxx, bminy), (bminx, bminy)]
                src_quad = []
                for mx, my in corners_merc:
                    lon, lat = _merc_to_lonlat(mx, my)
                    sx, sy = _apply_h(H_ll2px, lon, lat)
                    src_quad.append((sx, sy))

                # Skip tiles whose source quad lies entirely outside the image.
                sxs = [p[0] for p in src_quad]; sys = [p[1] for p in src_quad]
                if max(sxs) < 0 or min(sxs) > W or max(sys) < 0 or min(sys) > H:
                    continue

                try:
                    coeffs = _pil_perspective_coeffs(dst_quad, src_quad)
                except Exception:
                    continue
                tile = src.transform((TILE_SIZE, TILE_SIZE), Image.PERSPECTIVE,
                                     coeffs, Image.BICUBIC, fillcolor=fill)
                # Drop fully-transparent tiles (footprint did not actually cover them).
                if not tile.getbbox():
                    continue

                tdir = os.path.join(tmp_dir, str(z), str(tx))
                os.makedirs(tdir, exist_ok=True)
                tile.save(os.path.join(tdir, '%d.png' % ty), 'PNG')
                tile_count += 1

    # Atomic-ish swap: remove old, move temp into place.
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(parent, exist_ok=True)
    os.rename(tmp_dir, out_dir)

    return {'minzoom': minzoom, 'maxzoom': maxzoom, 'tile_count': tile_count}
