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

All conversions are done via aot.utils.timekit.
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
from aot.utils.timekit import utc_now
from aot.utils.timekit import parse_utc

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


def location_window(start, end, target_id: Optional[str]):
    """현지 날짜·시각 구간 → (시작 UTC, 끝 UTC, 시작 현지 ISO, 끝 현지 ISO).

    `target_id` 가 놓인 곳의 시간대로 읽는다(`iso_at` 과 같은 해석 — 측정 시각을
    다루는 도구는 시간대를 직접 풀지 않는다). 'YYYY-MM-DD' 만 주면 start 는 그날 0시,
    end 는 **그날을 포함**(다음 날 0시). 시각이나 오프셋을 주면 그대로. end 가 없으면 지금.
    못 읽으면 ValueError.
    """
    from datetime import timedelta
    from aot.utils.timekit import tz_of, wall_to_utc
    try:
        tz = tz_of(target_id)
    except Exception:                                       # noqa: BLE001
        tz = pytz.utc

    def parse(text, is_end):
        text = str(text).strip()
        if len(text) == 10:
            d = datetime.strptime(text, '%Y-%m-%d')
            if is_end:
                d += timedelta(days=1)
        else:
            d = text
        # 오프셋이 붙어 있으면 그 순간, 없으면 target_id 가 놓인 곳의 벽시계로 읽는다.
        return wall_to_utc(d, tz)

    t0 = parse(start, False)
    t1 = parse(end, True) if end else utc_now()
    local = lambda d: d.astimezone(tz).isoformat(timespec='minutes')
    return t0.astimezone(timezone.utc), t1.astimezone(timezone.utc), local(t0), local(t1)


def resolve_location_coords(target_id: Optional[str]):
    """Resolve (lat, lng) for ANY location/entity identified by `target_id` —
    mirrors timekit.tz_of's dispatch (GeoShape first, which also covers
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
            # 장치 위치의 정본은 리졸버 하나 — 장치 행의 latitude/longitude 를 직접 읽지 않는다.
            from aot.space.device_binding import resolve_device_kind
            from aot.space.device_location import locate
            kind = resolve_device_kind(target_id)
            if kind is not None:
                pl = locate(kind, target_id)
                if pl is not None and pl.point is not None:
                    return (pl.point[0], pl.point[1])
        except Exception as exc:
            logger.debug(f"resolve_location_coords: device lookup failed for {target_id}: {exc}")

    return (None, None)


__all__ = [
    "resolve_tz_from_coords",
    "location_window",
    "resolve_location_coords",
]
