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


def resolve_location_tz_and_source(target_id: Optional[str]):
    """resolve_location_tz 와 같은 해석 + **출처**: (tzinfo, 'device'|'system').

    'system' 은 그 대상의 위치를 몰라 시스템 시간대로 추정했다는 뜻이다(장치 행이
    시스템 폴백이거나, 대상을 못 찾았거나, 대상이 없음). 예약 앵커가 이것을 그대로
    적어야 화면이 '장치 현지 시각' 이 아니라 '시스템 추정' 이라고 말할 수 있다.
    (docs/design/timezone-management.md §3.2·§15.4)
    """
    if target_id and target_id != 'none':
        try:
            from aot.databases.models.geo import GeoShape
            shape = GeoShape.query.filter_by(unique_id=target_id).first()
            if shape is not None:
                tz = shape.resolve_timezone()
                if tz is not None:
                    return tz, 'device'
        except Exception as exc:
            logger.debug(f"resolve_location_tz: GeoShape lookup failed for {target_id}: {exc}")

        # 식생 구획(GeoPlot)은 GeoShape 가 아니라 별도 테이블이다. 여기에
        # 없으면 시스템 tz 로 조용히 떨어져, 여러 지역에 걸친 지도에서 구획에
        # 걸린 일정의 벽시계가 남의 지역 시각으로 표시된다.
        #
        # 해석은 **소속 구역**을 따른다 — 설계 §8 "운영 그룹은 한 시계를
        # 공유한다" 와 같은 규칙이고, 구획은 공간적으로 그 구역 안에 있다.
        # 소속은 저장하지 않고 파생하므로 여기서도 파생해서 쓴다.
        try:
            from aot.databases.models import GeoPlot
            plot = GeoPlot.query.filter_by(unique_id=target_id).first()
            if plot is not None:
                from aot.aot_flask.geo import plot_context
                container = plot_context.zone_for_plot(plot)
                if container is not None:
                    tz = container.resolve_timezone()
                    if tz is not None:
                        return tz, 'device'
        except Exception as exc:
            logger.debug(f"resolve_location_tz: GeoPlot lookup failed for {target_id}: {exc}")

        # 시설(GeoFacility)도 자기 위치가 있다 — 여기서 몰랐던 동안 시설에 건
        # 일정·구획의 '오늘' 이 시스템 시간대로 떨어졌다.
        try:
            from aot.databases.models.geo import GeoFacility
            fac = GeoFacility.query.filter_by(unique_id=target_id).first()
            if fac is not None:
                tz = fac.resolve_timezone()
                if tz is not None:
                    return tz, 'device'
        except Exception as exc:
            logger.debug(f"resolve_location_tz: GeoFacility lookup failed for {target_id}: {exc}")

        try:
            from aot.databases.models import Input, Output, Function, Conditional, Trigger, PID, CustomController
            for model in (Input, Output, Function, Conditional, Trigger, PID, CustomController):
                row = model.query.filter_by(unique_id=target_id).first()
                if row is not None:
                    from aot.utils.timekit import SOURCE_SYSTEM, SOURCE_UTC, resolve_tz
                    tz, src = resolve_tz(row)
                    return tz, ('system' if src in (SOURCE_SYSTEM, SOURCE_UTC) else 'device')
        except Exception as exc:
            logger.debug(f"resolve_location_tz: device lookup failed for {target_id}: {exc}")

        # 지도 자체(GeoMap uuid) — 그 지도의 사이트 도형(없으면 아무 도형)의 시계.
        # 새로 그리는 구획처럼 아직 자기 행이 없는 것의 '현지' 가 여기다.
        try:
            from aot.databases.models.geo import GeoShape
            shapes = GeoShape.query.filter_by(geo_id=target_id).limit(50).all()
            # site(1) → zone(2) → 나머지 순 — level_id 는 열이 아니라 속성이다.
            for shape in sorted(shapes, key=lambda x: x.level_id):
                tz = shape.resolve_timezone()
                if tz is not None:
                    return tz, 'device'
        except Exception as exc:
            logger.debug(f"resolve_location_tz: map lookup failed for {target_id}: {exc}")

    # No target_id, or nothing matched — system-wide fallback chain.
    return get_device_tz(None), 'system'


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
    return resolve_location_tz_and_source(target_id)[0]


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


def apply_system_tz_fallback(row, system_tz_name: Optional[str]) -> bool:
    """위치 없는 새 장치 행에 시스템 시간대를 복사하고 **출처를 'system' 으로
    남긴다**. 복사했으면 True.

    출처 없이 복사하면 나중에 이 값이 사람이 정한 것인지 폴백인지 가릴 수 없어
    `resolve_tz` 가 'explicit' 로 보고, 시스템 시간대를 바꿔도 따라가지 않았다.
    'system' 표시가 있는 행은 시스템 시간대를 저장할 때 새 값을 따른다
    (sync_system_tz_copies). (docs/design/timezone-management.md §15.4)
    """
    if row is None or not system_tz_name:
        return False
    if getattr(row, 'latitude', None) or getattr(row, 'longitude', None):
        return False
    row.timezone = system_tz_name
    if hasattr(row, 'tz_source'):
        row.tz_source = 'system'
    return True


DEVICE_TZ_MODELS = ('Input', 'Output', 'Function', 'Conditional', 'Trigger',
                    'PID', 'CustomController')


def sync_system_tz_copies(system_tz_name: Optional[str]) -> int:
    """시스템 시간대를 복사해 둔 장치 행(tz_source='system')을 새 값으로.

    사람이 정했거나(explicit) 좌표·도형에서 온(coords·inherited) 값은 건드리지
    않는다. 호출자가 commit 한다. 바꾼 행 수를 돌려준다.
    """
    if not system_tz_name:
        return 0
    import aot.databases.models as models
    changed = 0
    for name in DEVICE_TZ_MODELS:
        model = getattr(models, name)
        changed += (model.query
                    .filter(model.tz_source == 'system',
                            model.timezone.isnot(None),
                            model.timezone != system_tz_name)
                    .update({model.timezone: system_tz_name},
                            synchronize_session=False))
    return changed


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
    "resolve_location_tz_and_source",
    "apply_system_tz_fallback",
    "sync_system_tz_copies",
    "refresh_device_timezone",
]
