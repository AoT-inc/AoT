"""
SQLAlchemy event listeners that auto-populate `timezone` on device rows
whenever latitude/longitude changes.

Registered once at import time. Models attached: Input, Output,
CustomController, Function, Conditional, Trigger.
"""
import logging

from sqlalchemy import event
from sqlalchemy.orm.attributes import get_history

logger = logging.getLogger(__name__)


def _maybe_refresh(target):
    try:
        from aot.utils.device_tz import resolve_tz_from_coords
        new_tz = resolve_tz_from_coords(
            getattr(target, "latitude", None),
            getattr(target, "longitude", None),
        )
        if new_tz and getattr(target, "timezone", None) != new_tz:
            target.timezone = new_tz
        elif new_tz is None:
            target.timezone = None
    except Exception as exc:
        logger.warning(f"device_tz auto-refresh failed: {exc}")


def _coords_changed(target):
    lat_h = get_history(target, "latitude")
    lon_h = get_history(target, "longitude")
    return bool(lat_h.added or lat_h.deleted or lon_h.added or lon_h.deleted)


def _on_insert(mapper, connection, target):
    existing_tz = getattr(target, "timezone", None)
    # 'UTC' is often a pre-assigned fallback (from Misc.timezone when coords are
    # absent), not an intentional explicit setting.  Still attempt coord-based
    # resolution so devices created with valid lat/lon get the correct timezone.
    if existing_tz and existing_tz != 'UTC':
        return
    _maybe_refresh(target)


def _on_update(mapper, connection, target):
    if not _coords_changed(target):
        return
    _maybe_refresh(target)


def register_device_tz_listeners():
    from aot.databases.models.input import Input
    from aot.databases.models.output import Output
    from aot.databases.models.pid import PID
    from aot.databases.models.controller import CustomController
    from aot.databases.models.function import Function, Conditional, Trigger

    for model in (Input, Output, PID, CustomController, Function, Conditional, Trigger):
        if not getattr(model, "_device_tz_listener_attached", False):
            event.listen(model, "before_insert", _on_insert)
            event.listen(model, "before_update", _on_update)
            model._device_tz_listener_attached = True
