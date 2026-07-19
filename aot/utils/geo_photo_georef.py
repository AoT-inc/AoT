# coding=utf-8
"""
geo_photo_georef.py
Drone / aerial photo georeferencing helpers.

Two responsibilities:
  1. extract_photo_metadata(): pull GPS + camera/gimbal pose out of a JPEG/TIFF
     using EXIF (standard) and XMP (DJI ``drone-dji`` namespace, raw-byte scan).
  2. compute_footprint(): turn that pose into 4 ground-corner lng/lat coordinates
     for a near-nadir shot, so the image can be drawn as a MapLibre ``image``
     source. The result is an *initial* placement; the UI lets the user nudge the
     four corners afterwards (rubber-sheeting), which absorbs oblique/altitude error.

Only Pillow is required (already a project dependency); when XMP/EXIF is absent or
insufficient, the functions degrade to returning ``None`` rather than guessing, and
the caller falls back to a manual default placement.

@phase active
@stability experimental
"""
import io
import math
import re

try:
    from PIL import Image, ExifTags
    _PIL_OK = True
except Exception:  # pragma: no cover - Pillow is a hard project dep, this is defensive
    _PIL_OK = False

# Earth radius constants for the local flat-earth approximation. Footprints are a
# few hundred metres at most, so a tangent-plane (ENU) approximation is well within
# the manual-correction tolerance.
_M_PER_DEG_LAT = 111320.0

# Reference frame width of a full-frame 35mm sensor (mm). Used together with the
# EXIF "focal length in 35mm film" tag to derive field-of-view without needing the
# real (and often unreported) physical sensor dimensions.
_FRAME_35MM_WIDTH = 36.0

# Map standard EXIF tag *names* back to their numeric ids once, for fast lookup.
if _PIL_OK:
    _EXIF_NAME_TO_ID = {v: k for k, v in ExifTags.TAGS.items()}
    _GPS_NAME_TO_ID = {v: k for k, v in ExifTags.GPSTAGS.items()}
else:  # pragma: no cover
    _EXIF_NAME_TO_ID = {}
    _GPS_NAME_TO_ID = {}


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _to_float(value):
    """Best-effort float() that also handles PIL IFDRational and tuples."""
    if value is None:
        return None
    try:
        if isinstance(value, (tuple, list)):
            # Rational stored as (num, den)
            if len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
                return float(value[0]) / float(value[1]) if value[1] else None
            return None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms_to_deg(dms, ref):
    """Convert EXIF GPS (degrees, minutes, seconds) + hemisphere ref to signed deg."""
    try:
        d = _to_float(dms[0]) or 0.0
        m = _to_float(dms[1]) or 0.0
        s = _to_float(dms[2]) or 0.0
    except (TypeError, IndexError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    if ref and str(ref).upper() in ('S', 'W'):
        deg = -deg
    return deg


def _parse_exif_gps(img):
    """Return (lat, lon, abs_altitude) from standard EXIF GPS tags, or Nones."""
    lat = lon = alt = None
    try:
        exif = img.getexif()
        if not exif:
            return lat, lon, alt
        gps_ifd_id = _EXIF_NAME_TO_ID.get('GPSInfo')
        gps = exif.get_ifd(gps_ifd_id) if gps_ifd_id else None
        if not gps:
            return lat, lon, alt
        lat = _dms_to_deg(gps.get(_GPS_NAME_TO_ID.get('GPSLatitude')),
                          gps.get(_GPS_NAME_TO_ID.get('GPSLatitudeRef')))
        lon = _dms_to_deg(gps.get(_GPS_NAME_TO_ID.get('GPSLongitude')),
                          gps.get(_GPS_NAME_TO_ID.get('GPSLongitudeRef')))
        alt = _to_float(gps.get(_GPS_NAME_TO_ID.get('GPSAltitude')))
    except Exception:
        pass
    return lat, lon, alt


def _parse_exif_camera(img):
    """Return (focal_length_mm, focal_35mm) from EXIF, or Nones."""
    focal = focal35 = None
    try:
        exif = img.getexif()
        if not exif:
            return focal, focal35
        # FocalLength / FocalLengthIn35mmFilm live in the Exif sub-IFD.
        exif_ifd_id = _EXIF_NAME_TO_ID.get('ExifOffset')
        sub = exif.get_ifd(exif_ifd_id) if exif_ifd_id else {}
        focal = _to_float(sub.get(_EXIF_NAME_TO_ID.get('FocalLength')))
        focal35 = _to_float(sub.get(_EXIF_NAME_TO_ID.get('FocalLengthIn35mmFilm')))
    except Exception:
        pass
    return focal, focal35


# DJI and several other drone makers embed pose data in an XMP packet. Scanning the
# raw bytes with regex is far more robust across Pillow versions and vendor quirks
# than relying on Image.getxmp() dict shapes.
_XMP_PATTERNS = {
    'rel_altitude': r'(?:drone-dji:)?RelativeAltitude\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'abs_altitude': r'(?:drone-dji:)?AbsoluteAltitude\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'gimbal_yaw':   r'(?:drone-dji:)?GimbalYawDegree\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'gimbal_pitch': r'(?:drone-dji:)?GimbalPitchDegree\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'gimbal_roll':  r'(?:drone-dji:)?GimbalRollDegree\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'flight_yaw':   r'(?:drone-dji:)?FlightYawDegree\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'xmp_lat':      r'(?:drone-dji:)?GpsLatitude\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
    'xmp_lon':      r'(?:drone-dji:)?GpsLongitude\s*=\s*["\']?\s*([+\-]?[0-9.]+)',
}


def _parse_xmp(raw_bytes):
    """Scan raw file bytes for an XMP packet and pull drone pose fields out of it."""
    out = {}
    try:
        # Locate the XMP packet; it is plain UTF-8/Latin-1 XML embedded in the file.
        start = raw_bytes.find(b'<x:xmpmeta')
        if start == -1:
            start = raw_bytes.find(b'<?xpacket')
        if start == -1:
            return out
        end = raw_bytes.find(b'</x:xmpmeta>', start)
        chunk = raw_bytes[start:end + 12] if end != -1 else raw_bytes[start:start + 65536]
        text = chunk.decode('latin-1', errors='ignore')
        for key, pattern in _XMP_PATTERNS.items():
            m = re.search(pattern, text)
            if m:
                try:
                    out[key] = float(m.group(1))
                except ValueError:
                    pass
    except Exception:
        pass
    return out


def extract_photo_metadata(source):
    """
    Extract georeferencing metadata from a drone/aerial photo.

    Args:
        source: file path (str), bytes, or a file-like object.

    Returns:
        dict with any of the following keys present when found:
          lat, lon              - decimal degrees (XMP preferred, EXIF fallback)
          rel_altitude          - metres above takeoff/ground (DJI RelativeAltitude)
          abs_altitude          - metres above sea level
          yaw                   - camera heading, deg clockwise from north
          pitch, roll           - gimbal angles, deg
          focal_length, focal_35mm
          width, height         - image pixel dimensions
          has_geo               - bool: enough to attempt an automatic footprint
    """
    if not _PIL_OK:
        return {'has_geo': False, 'error': 'Pillow not available'}

    # Normalise input to both a bytes buffer (for XMP scan) and a PIL image.
    raw = None
    try:
        if isinstance(source, bytes):
            raw = source
        elif hasattr(source, 'read'):
            raw = source.read()
            try:
                source.seek(0)
            except Exception:
                pass
        else:
            with open(source, 'rb') as fh:
                raw = fh.read()
    except Exception as e:
        return {'has_geo': False, 'error': 'read failed: %s' % e}

    meta = {}
    try:
        img = Image.open(io.BytesIO(raw))
        meta['width'], meta['height'] = img.size

        lat, lon, abs_alt = _parse_exif_gps(img)
        focal, focal35 = _parse_exif_camera(img)
        if focal is not None:
            meta['focal_length'] = focal
        if focal35 is not None:
            meta['focal_35mm'] = focal35
        if abs_alt is not None:
            meta['abs_altitude'] = abs_alt
    except Exception as e:
        return {'has_geo': False, 'error': 'image open failed: %s' % e}

    xmp = _parse_xmp(raw)
    # XMP GPS is usually more precise / present for drones; prefer it, fall back to EXIF.
    if 'xmp_lat' in xmp:
        lat = xmp['xmp_lat']
    if 'xmp_lon' in xmp:
        lon = xmp['xmp_lon']
    if lat is not None:
        meta['lat'] = lat
    if lon is not None:
        meta['lon'] = lon
    if 'rel_altitude' in xmp:
        meta['rel_altitude'] = xmp['rel_altitude']
    if 'abs_altitude' in xmp:
        meta['abs_altitude'] = xmp['abs_altitude']
    # Gimbal yaw is the camera heading; FlightYaw is a fallback if the gimbal field is absent.
    if 'gimbal_yaw' in xmp:
        meta['yaw'] = xmp['gimbal_yaw']
    elif 'flight_yaw' in xmp:
        meta['yaw'] = xmp['flight_yaw']
    if 'gimbal_pitch' in xmp:
        meta['pitch'] = xmp['gimbal_pitch']
    if 'gimbal_roll' in xmp:
        meta['roll'] = xmp['gimbal_roll']

    # "Enough to attempt an automatic footprint" = position + a scale source
    # (relative altitude) + a way to derive FOV (35mm-equiv or real focal length).
    has_alt = 'rel_altitude' in meta
    has_fov = ('focal_35mm' in meta) or ('focal_length' in meta)
    meta['has_geo'] = bool('lat' in meta and 'lon' in meta and has_alt and has_fov)
    return meta


# ---------------------------------------------------------------------------
# Footprint computation
# ---------------------------------------------------------------------------

def _offset_to_lnglat(lat0, lon0, east_m, north_m):
    """Convert a local ENU metre offset to [lng, lat] on a tangent plane."""
    dlat = north_m / _M_PER_DEG_LAT
    dlon = east_m / (_M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return [lon0 + dlon, lat0 + dlat]


def compute_footprint(meta, default_ground_width_m=None):
    """
    Compute 4 ground-corner coordinates for a near-nadir photo.

    Args:
        meta: dict from extract_photo_metadata().
        default_ground_width_m: if given and metadata is insufficient, build a
            simple north-aligned square of this ground width centred on lat/lon.

    Returns:
        list of 4 [lng, lat] pairs in MapLibre ``image`` source order
        (top-left, top-right, bottom-right, bottom-left), or None if a footprint
        cannot be derived and no default was requested.
    """
    if not meta:
        return None
    lat = meta.get('lat')
    lon = meta.get('lon')
    if lat is None or lon is None:
        return None

    width_px = meta.get('width') or 0
    height_px = meta.get('height') or 0
    aspect = (height_px / width_px) if (width_px and height_px) else 0.75  # default 4:3

    ground_width = None
    if meta.get('has_geo'):
        alt = meta.get('rel_altitude')
        focal35 = meta.get('focal_35mm')
        focal = meta.get('focal_length')
        if alt and focal35:
            # ground_width = 2 * alt * tan(hfov/2); hfov = 2*atan(36 / (2*focal35))
            ground_width = (_FRAME_35MM_WIDTH / focal35) * alt
        elif alt and focal:
            # Without a 35mm equiv we cannot know sensor width; assume APS-C-ish
            # crop (~1.5x). This is rough but only seeds the manual correction.
            est_focal35 = focal * 1.5
            ground_width = (_FRAME_35MM_WIDTH / est_focal35) * alt

    if ground_width is None:
        if default_ground_width_m is None:
            return None
        ground_width = float(default_ground_width_m)

    ground_height = ground_width * aspect
    half_w = ground_width / 2.0
    half_h = ground_height / 2.0

    # Local corners before rotation, (east, north) in metres. Image "up" = north.
    # Order: TL, TR, BR, BL to match MapLibre image source coordinate order.
    local = [
        (-half_w, half_h),   # top-left
        (half_w, half_h),    # top-right
        (half_w, -half_h),   # bottom-right
        (-half_w, -half_h),  # bottom-left
    ]

    yaw = meta.get('yaw')
    theta = math.radians(yaw) if yaw is not None else 0.0
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    corners = []
    for east, north in local:
        # Rotate so the image "up" axis points toward the yaw bearing (cw from north).
        e2 = east * cos_t + north * sin_t
        n2 = -east * sin_t + north * cos_t
        corners.append(_offset_to_lnglat(lat, lon, e2, n2))
    return corners


def default_footprint(lat, lon, ground_width_m, aspect=0.75):
    """North-aligned rectangular footprint centred on lat/lon. Used as the manual
    fallback when no usable metadata exists."""
    return compute_footprint(
        {'lat': lat, 'lon': lon, 'has_geo': False,
         'width': 1000, 'height': int(1000 * aspect)},
        default_ground_width_m=ground_width_m,
    )
