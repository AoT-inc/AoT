# coding=utf-8
import re
import logging

logger = logging.getLogger(__name__)

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
