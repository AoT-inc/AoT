"""
Device timezone utilities.

Each device (Input/Output/Controller/Function/PID/Trigger) carries its own
location (latitude/longitude), auto-assigned from the system map center on
creation. The IANA timezone for that location is resolved from the coordinates
and cached in the device's `timezone` column.

Resolution chain (priority order):
  1. device.timezone  (explicitly stored, derived from coords)
  2. resolve from device.latitude/device.longitude via timezonefinder
  3. Misc.timezone    (system-wide fallback stored in DB)
  4. 'UTC'

All conversions are done via aot.utils.tz_utils / time_utils helpers.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

# h3 4.x → 3.x API 호환 shim.
# timezonefinder 6.5.x 는 h3 3.x 의 geo_to_h3 을 사용하는데,
# h3 4.x 에서 latlng_to_cell 로 이름이 바뀌었다.
# timezonefinder 를 재설치하지 않고 런타임 패치로 해결한다.
try:
    import h3.api.numpy_int as _h3_api
    if not hasattr(_h3_api, 'geo_to_h3') and hasattr(_h3_api, 'latlng_to_cell'):
        _h3_api.geo_to_h3 = lambda lat, lng, resolution: _h3_api.latlng_to_cell(lat, lng, resolution)
except Exception:
    pass

import pytz

logger = logging.getLogger(__name__)

_TF_UNAVAILABLE = object()  # sentinel — distinct from None and False
_tf_instance = None         # None = not tried yet; _TF_UNAVAILABLE = unavailable; else = finder
_tz_cache: dict = {}


def _get_finder():
    """Lazy-load timezonefinder. Returns None if package unavailable."""
    global _tf_instance
    if _tf_instance is _TF_UNAVAILABLE:
        return None
    if _tf_instance is not None:
        return _tf_instance
    try:
        from timezonefinder import TimezoneFinder
        _tf_instance = TimezoneFinder(in_memory=True)
        return _tf_instance
    except Exception as exc:
        logger.warning(f"timezonefinder unavailable, falling back to UTC: {exc}")
        _tf_instance = _TF_UNAVAILABLE
        return None


def resolve_tz_from_coords(latitude: Optional[float],
                           longitude: Optional[float]) -> Optional[str]:
    """
    Return IANA timezone name for given coordinates, or None.

    Cached per (lat,lon) rounded to 4 decimals (~11m precision) to avoid
    repeated lookups. Returns None if coords missing or finder unavailable.
    """
    if latitude is None or longitude is None:
        return None
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    key = (round(lat, 4), round(lon, 4))
    if key in _tz_cache:
        return _tz_cache[key]

    finder = _get_finder()
    if finder is None:
        return None
    try:
        name = finder.timezone_at(lat=lat, lng=lon)
    except Exception as exc:
        logger.warning(f"timezone lookup failed for ({lat},{lon}): {exc}")
        name = None
    _tz_cache[key] = name
    return name


def get_device_tz(device) -> pytz.BaseTzInfo:
    """
    Return pytz timezone for a device row.

    Priority: device.timezone → coords → user setting → UTC.
    Accepts any object with `timezone`, `latitude`, `longitude` attributes
    (Input/Output/Controller/Function rows all qualify).
    """
    tz_name = None
    if device is not None:
        tz_name = getattr(device, 'timezone', None)
        if not tz_name:
            tz_name = resolve_tz_from_coords(
                getattr(device, 'latitude', None),
                getattr(device, 'longitude', None),
            )
    if not tz_name:
        # System-wide fallback: read Misc.timezone via the daemon-compatible
        # SQLite helper first.  This works in BOTH Flask and daemon contexts.
        # get_timezone_name() (Flask-SQLAlchemy) is skipped here because it
        # silently returns 'UTC' in the daemon context instead of raising.
        try:
            from aot.utils.database import db_retrieve_table_daemon
            from aot.databases.models.misc import Misc
            misc = db_retrieve_table_daemon(Misc, entry='first')
            if misc and getattr(misc, 'timezone', None):
                tz_name = misc.timezone
        except Exception:
            tz_name = None

    if not tz_name:
        # Final fallback: Flask-SQLAlchemy path (Flask app context only).
        try:
            from aot.utils.time_utils import get_timezone_name
            name = get_timezone_name()
            if name and name != 'UTC':
                tz_name = name
        except Exception:
            tz_name = None
    try:
        return pytz.timezone(tz_name or 'UTC')
    except Exception:
        return pytz.utc


def to_device_tz(dt: Optional[datetime], device) -> Optional[datetime]:
    """Convert a UTC datetime (naive treated as UTC) to the device's local tz."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_device_tz(device))


def device_tz_name(device) -> str:
    """Return the IANA tz string a device should display in."""
    return str(get_device_tz(device))


def refresh_device_timezone(device) -> Optional[str]:
    """
    Recompute device.timezone from its current coords and write it back.
    Caller is responsible for db.session.commit(). Returns the new tz name.
    """
    if device is None:
        return None
    new_tz = resolve_tz_from_coords(
        getattr(device, 'latitude', None),
        getattr(device, 'longitude', None),
    )
    if new_tz and getattr(device, 'timezone', None) != new_tz:
        device.timezone = new_tz
    return new_tz


__all__ = [
    "resolve_tz_from_coords",
    "get_device_tz",
    "to_device_tz",
    "device_tz_name",
    "refresh_device_timezone",
]
