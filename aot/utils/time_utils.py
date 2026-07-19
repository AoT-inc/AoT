import re
import logging
import pytz
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def get_timezone_name():
    """
    Returns the configured timezone name from the database.
    Defaults to 'UTC' if not set or if database is inaccessible.
    """
    try:
        from aot.databases.models.misc import Misc
        # Use a safe query that doesn't trigger circular imports if possible
        # Or rely on the caller to provide it if we are in a sensitive context
        settings = Misc.query.first()
        if settings and settings.timezone:
            return settings.timezone
    except Exception:
        # Fallback to UTC if DB and models aren't ready (e.g. during startup/migration)
        pass
    return 'UTC'


def parse_flexible_time(val):
    """
    Parses a variety of time input formats into total seconds and a formatted HH:MM:SS string.
    Supported:
      - 123 (interpreted as seconds)
      - 05:16 (interpreted as MM:SS)
      - 01:02:03 (interpreted as HH:MM:SS)
    
    Returns:
       dict: { 'total_seconds': int, 'formatted': 'HH:MM:SS' } or None on failure.
    """
    if val is None:
        return None
    
    # If already a number
    if isinstance(val, (int, float)):
        total_sec = int(val)
        return _format_result(total_sec)
    
    # Clean string
    s_val = str(val).strip()
    if not s_val:
        return None
    
    # Remove all non-numeric characters except colons and dots (for floats)
    s_val = re.sub(r'[^0-9:.]', '', s_val)
    
    # Split by colon
    parts = s_val.split(':')
    
    try:
        if len(parts) == 1:
            # Entirely seconds
            total_sec = int(float(parts[0]))
        elif len(parts) == 2:
            # MM:SS
            m = int(float(parts[0]))
            s = int(float(parts[1]))
            total_sec = m * 60 + s
        elif len(parts) >= 3:
            # HH:MM:SS (extra parts ignored)
            h = int(float(parts[0]))
            m = int(float(parts[1]))
            s = int(float(parts[2]))
            total_sec = h * 3600 + m * 60 + s
        else:
            return None
            
        return _format_result(total_sec)
    except Exception as e:
        logger.warning(f"Failed to parse flexible time '{val}': {e}")
        return None

def utc_now():
    """timezone-aware UTC datetime 반환. 모든 신규 코드에서 사용."""
    return datetime.now(timezone.utc)

def get_local_now(tz_name=None):
    """
    Returns the current time in the configured local timezone.
    """
    if tz_name is None:
        tz_name = get_timezone_name()
    try:
        tz = pytz.timezone(tz_name)
        return datetime.now(tz)
    except Exception:
        return utc_now()

def to_local(dt, tz_name=None):
    """
    Converts a UTC datetime (aware or naive) to the configured local timezone.
    """
    if dt is None:
        return None
    if tz_name is None:
        tz_name = get_timezone_name()
    try:
        tz = pytz.timezone(tz_name)
        if dt.tzinfo is None:
            # Assume naive datetime is UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)
    except Exception:
        return dt


def serialize_ts(dt, tz_name=None):
    """
    UTC datetime(naive or aware)을 로컬 타임존으로 변환하여 ISO 8601 문자열로 반환.
    예: 2026-03-24T18:00:00+09:00  (Asia/Seoul)
    dt가 None이면 None을 반환.
    API JSON 응답에서 timestamp 직렬화의 표준 함수로 사용.
    """
    converted = to_local(dt, tz_name)
    if converted is None:
        return None
    return converted.isoformat()


def api_iso(dt):
    """
    API 응답용 표준 직렬화: 항상 UTC + offset 포함 ISO 8601 문자열.
    예: '2026-05-06T12:34:56+00:00'
    프론트엔드가 device TZ 또는 viewer TZ로 변환하는 단일 진실 공급원.
    naive datetime은 UTC로 가정하여 변환.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _format_result(total_sec):
    if total_sec < 0:
        total_sec = 0
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    formatted = f"{h:02d}:{m:02d}:{s:02d}"
    return {
        'total_seconds': total_sec,
        'formatted': formatted
    }
