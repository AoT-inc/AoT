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

    Priority: device.timezone → coords → system (Misc.timezone) → UTC.
    Accepts any object with `timezone`, `latitude`, `longitude` attributes
    (Input/Output/Controller/Function rows all qualify).

    Wrapper: the resolution chain now lives in aot.utils.timekit.resolve_tz
    (single source of truth — see docs/design/timezone-management.md).
    Behavior is unchanged; this thin shim is kept for existing callers.
    """
    from aot.utils.timekit import resolve_tz
    tzinfo, _source = resolve_tz(device)
    return tzinfo


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


def resolve_location_tz(target_id: Optional[str]) -> pytz.BaseTzInfo:
    """
    Resolve the pytz timezone for ANY location/entity identified by `target_id`
    — a GeoShape (zone/site/facility outline), a device row (Input/Output/
    Function/Conditional/Trigger/PID/CustomController), or None/'none'/unknown
    (system-wide fallback: Misc.timezone → UTC, same chain as get_device_tz).

    This is the single entry point AI-facing code should use whenever it needs
    "what is LOCAL time at this location" — e.g. formatting a schedule tied to
    a zone, or answering "지금 3-1 구역은 몇시야?". Every entity in the system
    that carries a location (GeoShape coordinates, or a device's own lat/lng)
    can answer this without the caller knowing which table `target_id` lives in.
    """
    if target_id and target_id != 'none':
        try:
            from aot.databases.models.geo import GeoShape
            shape = GeoShape.query.filter_by(unique_id=target_id).first()
            if shape is not None:
                tz = shape.resolve_timezone()
                if tz is not None:
                    return tz
        except Exception as exc:
            logger.debug(f"resolve_location_tz: GeoShape lookup failed for {target_id}: {exc}")

        # 식생 구획(GeoPlanting)은 GeoShape 가 아니라 별도 테이블이다. 여기에
        # 없으면 시스템 tz 로 조용히 떨어져, 여러 지역에 걸친 지도에서 구획에
        # 걸린 일정의 벽시계가 남의 지역 시각으로 표시된다.
        #
        # 해석은 **소속 구역**을 따른다 — 설계 §8 "운영 그룹은 한 시계를
        # 공유한다" 와 같은 규칙이고, 구획은 공간적으로 그 구역 안에 있다.
        # 소속은 저장하지 않고 파생하므로 여기서도 파생해서 쓴다.
        try:
            from aot.databases.models import GeoPlanting
            planting = GeoPlanting.query.filter_by(unique_id=target_id).first()
            if planting is not None:
                from aot.aot_flask.geo import planting_context
                container = planting_context.zone_for_planting(planting)
                if container is not None:
                    tz = container.resolve_timezone()
                    if tz is not None:
                        return tz
        except Exception as exc:
            logger.debug(f"resolve_location_tz: GeoPlanting lookup failed for {target_id}: {exc}")

        try:
            from aot.databases.models import Input, Output, Function, Conditional, Trigger, PID, CustomController
            for model in (Input, Output, Function, Conditional, Trigger, PID, CustomController):
                row = model.query.filter_by(unique_id=target_id).first()
                if row is not None:
                    return get_device_tz(row)
        except Exception as exc:
            logger.debug(f"resolve_location_tz: device lookup failed for {target_id}: {exc}")

    # No target_id, or nothing matched — system-wide fallback chain.
    return get_device_tz(None)


def resolve_location_coords(target_id: Optional[str]):
    """Resolve (lat, lng) for ANY location/entity identified by `target_id` —
    mirrors resolve_location_tz's dispatch (GeoShape first, which also covers
    a linked GeoFacility since GeoFacility has no polygon of its own; then
    device rows with their own latitude/longitude columns). Returns
    (None, None) if target_id is missing or nothing resolves — callers should
    treat that as "no map to show", not an error.
    """
    if target_id and target_id != 'none':
        try:
            from aot.databases.models.geo import GeoShape
            shape = GeoShape.query.filter_by(unique_id=target_id).first()
            if shape is not None:
                centroid = shape.get_centroid()
                if centroid:
                    return centroid
        except Exception as exc:
            logger.debug(f"resolve_location_coords: GeoShape lookup failed for {target_id}: {exc}")

        try:
            from aot.databases.models import Input, Output, Function, Conditional, Trigger, PID, CustomController
            for model in (Input, Output, Function, Conditional, Trigger, PID, CustomController):
                row = model.query.filter_by(unique_id=target_id).first()
                if row is not None:
                    lat = getattr(row, 'latitude', None)
                    lng = getattr(row, 'longitude', None)
                    if lat is not None and lng is not None:
                        return (lat, lng)
        except Exception as exc:
            logger.debug(f"resolve_location_coords: device lookup failed for {target_id}: {exc}")

    return (None, None)


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
    "resolve_location_tz",
    "refresh_device_timezone",
]
