"""
Timezone utility for schedule services.
Rule: all internal datetimes are UTC-aware.
      UI display converts via get_user_tz() / to_user_tz().

Project standard: pytz (see requirements.txt).
Source of truth for user timezone: Misc.timezone (settings/general page).
Docker container timezone is always treated as UTC; never rely on os.timezone.
"""
import pytz
from datetime import datetime, timezone

from aot.utils.time_utils import get_timezone_name, utc_now, to_local


def get_user_tz() -> pytz.BaseTzInfo:
    """Return user timezone from Misc model (settings/general). Falls back to UTC."""
    tz_str = get_timezone_name()
    try:
        return pytz.timezone(tz_str)
    except Exception:
        return pytz.utc


def to_utc(dt: datetime) -> datetime:
    """Convert any aware datetime to UTC. Raises ValueError if dt is naive."""
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime passed to to_utc: {dt!r}")
    return dt.astimezone(timezone.utc)


def to_user_tz(dt: datetime) -> datetime:
    """Convert UTC datetime to user local timezone for display."""
    return to_local(dt)


__all__ = ["get_user_tz", "to_utc", "to_user_tz", "now_utc"]

# Re-export now_utc from time_utils for convenience
from aot.utils.time_utils import utc_now as now_utc  # noqa: E402,F401
