# coding=utf-8
"""
Weekly schedule utility.

Schema (stored as JSON in Trigger.timer_schedule):
    {
        "version": 1,
        "mode": "shared" | "per_day",
        "shared": {"start": "16:30", "end": "19:00", "period": 3600},
        "days": {
            "0": {"enabled": true, "start": "16:30", "end": "19:00", "period": 3600,
                  "actions": {"<action_uid>": true, ...}},
            ...
            "6": {"enabled": false, "start": "16:30", "end": "19:00", "period": 3600}
        }
    }

The optional per-day "actions" map overrides each action's global enabled flag
for that weekday. A missing map or missing uid falls back to the global flag.

Rules:
- Day indices follow Python weekday convention: 0=Mon ... 6=Sun.
- Times are wall-clock (device local timezone) HH:MM strings.
- "24:00" is a valid end time meaning end-of-day. Stored internally as 1440 minutes.
- start < end enforced (no midnight-crossing). Each day operates within 00:00-24:00.
- Continuity: if prev_day.end == "24:00" and next_day.start == "00:00",
  both enabled, and days are adjacent — the daemon does NOT reset the cycle at midnight.

Callers must supply the device timezone (from get_device_tz). This module
never reads the clock directly; it receives tz-aware context from the caller.
"""
import json
import logging
from datetime import datetime
from typing import Optional, Tuple

import pytz

logger = logging.getLogger(__name__)

DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


# ---------------------------------------------------------------------------
# Time helpers (24:00 = 1440 minutes)
# ---------------------------------------------------------------------------

def time_to_minutes(hhmm: str) -> int:
    """Parse "HH:MM" to minutes since midnight (0–1440). "24:00" → 1440."""
    try:
        parts = str(hhmm).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        total = h * 60 + m
        if total < 0 or total > 1440:
            raise ValueError(f"out of range: {hhmm}")
        return total
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Invalid time {hhmm!r}: {exc}")


def minutes_to_hhmm(minutes: int) -> str:
    """Convert minutes since midnight to "HH:MM". 1440 → "24:00"."""
    if not (0 <= minutes <= 1440):
        raise ValueError(f"Minutes out of range: {minutes}")
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _default_entry(start="16:30", end="19:00", period=3600, enabled=True) -> dict:
    return {"enabled": bool(enabled), "start": str(start), "end": str(end), "period": int(period)}


def _normalize_entry(raw: dict, defaults: dict) -> dict:
    """Fill missing keys with defaults."""
    return {
        "enabled": bool(raw.get("enabled", defaults.get("enabled", True))),
        "start":   str(raw.get("start",   defaults.get("start", "16:30"))),
        "end":     str(raw.get("end",     defaults.get("end", "19:00"))),
        "period":  int(float(raw.get("period", defaults.get("period", 3600)))),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def from_legacy(timer_start_time: str,
                timer_end_time: str,
                timer_weekday: Optional[str],
                period: float = 3600) -> dict:
    """
    Convert legacy Trigger columns to weekly schedule schema.

    Handles midnight-crossing windows (start >= end) by clamping end to "24:00"
    and logging a warning.
    """
    start = (timer_start_time or "16:30").strip()
    end   = (timer_end_time   or "19:00").strip()

    try:
        s_min = time_to_minutes(start)
        e_min = time_to_minutes(end)
        if s_min >= e_min:
            logger.warning(
                "weekly_schedule.from_legacy: midnight-crossing window %s-%s "
                "clamped to %s-24:00", start, end, start)
            end = "24:00"
    except ValueError:
        logger.warning("weekly_schedule.from_legacy: invalid times %r/%r, using defaults", start, end)
        start, end = "16:30", "19:00"

    period_int = max(1, int(period))

    # Parse enabled days
    if timer_weekday and timer_weekday.strip():
        enabled_days = set()
        for tok in timer_weekday.split(','):
            tok = tok.strip()
            if tok.isdigit() and 0 <= int(tok) <= 6:
                enabled_days.add(int(tok))
    else:
        enabled_days = {0, 1, 2, 3, 4, 5, 6}

    days = {
        str(i): _default_entry(start=start, end=end, period=period_int, enabled=(i in enabled_days))
        for i in range(7)
    }

    return {
        "version": 1,
        "mode": "shared",
        "shared": {"start": start, "end": end, "period": period_int},
        "days": days,
    }


def parse_schedule(raw) -> Optional[dict]:
    """
    Parse and validate a schedule from a JSON string or dict.
    Returns the normalised dict, or None if invalid.
    """
    if raw is None:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return None

    errors = validate(data)
    if errors:
        logger.warning("weekly_schedule.parse_schedule: validation errors: %s", errors)
        return None
    return data


def validate(schedule: dict) -> list:
    """Return a list of error strings (empty list = valid)."""
    if not isinstance(schedule, dict):
        return ["schedule must be a dict"]

    errors = []

    if schedule.get("version") != 1:
        errors.append(f"unknown version {schedule.get('version')!r}")
        return errors

    if schedule.get("mode") not in ("shared", "per_day"):
        errors.append(f"mode must be 'shared' or 'per_day', got {schedule.get('mode')!r}")

    shared = schedule.get("shared")
    if not isinstance(shared, dict):
        errors.append("missing 'shared' block")
    else:
        errors.extend(_validate_entry(shared, "shared"))

    days = schedule.get("days")
    if not isinstance(days, dict):
        errors.append("missing 'days' block")
    else:
        for i in range(7):
            key = str(i)
            if key not in days:
                errors.append(f"missing days['{key}']")
            elif not isinstance(days[key], dict):
                errors.append(f"days['{key}'] must be a dict")
            else:
                errors.extend(_validate_entry(days[key], f"days['{key}']"))

    return errors


def _validate_entry(entry: dict, label: str) -> list:
    errors = []
    s_min = e_min = None

    try:
        s_min = time_to_minutes(entry.get("start", ""))
    except ValueError as exc:
        errors.append(f"{label}.start: {exc}")

    try:
        e_min = time_to_minutes(entry.get("end", ""))
    except ValueError as exc:
        errors.append(f"{label}.end: {exc}")

    if s_min is not None and e_min is not None:
        if e_min == 0:
            errors.append(f"{label}.end cannot be 00:00")
        elif s_min >= e_min:
            errors.append(
                f"{label}: start ({entry.get('start')}) must be before end ({entry.get('end')})"
            )

    period = entry.get("period")
    try:
        if float(period) <= 0:
            raise ValueError("non-positive")
    except (TypeError, ValueError):
        errors.append(f"{label}.period must be a positive number, got {period!r}")

    actions = entry.get("actions")
    if actions is not None and not isinstance(actions, dict):
        errors.append(f"{label}.actions must be a dict of action_uid -> bool")

    # Optional per-day overrides for group membership and operation duration
    # (parallel maps keyed by action_uid), used in per_day mode.
    groups = entry.get("groups")
    if groups is not None and not isinstance(groups, dict):
        errors.append(f"{label}.groups must be a dict of action_uid -> group_name")
    durations = entry.get("durations")
    if durations is not None and not isinstance(durations, dict):
        errors.append(f"{label}.durations must be a dict of action_uid -> seconds")

    return errors


def day_action_enabled(schedule: dict, day_idx: int, action_uid: str, default: bool = True) -> bool:
    """
    Return the effective enabled state of an action for a given weekday.

    The per-day actions map overrides the global flag; a missing map or
    missing uid falls back to `default` (the action's global enabled flag).
    """
    try:
        actions = schedule.get("days", {}).get(str(day_idx), {}).get("actions")
        if isinstance(actions, dict) and action_uid in actions:
            return bool(actions[action_uid])
    except Exception:
        pass
    return default


def day_action_group(schedule: dict, day_idx: int, action_uid: str, default=None):
    """
    Return the effective device-group name of an action for a given weekday.

    The per-day `groups` map overrides the global group_name; a missing map or
    missing uid falls back to `default` (the action's global group_name).
    An empty string in the map means "explicitly ungrouped for this day".
    """
    try:
        groups = schedule.get("days", {}).get(str(day_idx), {}).get("groups")
        if isinstance(groups, dict) and action_uid in groups:
            val = groups[action_uid]
            val = (val or "").strip() if isinstance(val, str) else ""
            return val or None
    except Exception:
        pass
    return default


def day_action_duration(schedule: dict, day_idx: int, action_uid: str, default=None):
    """
    Return the effective operation duration (seconds) of an action for a
    given weekday. The per-day `durations` map overrides the global
    action_duration; a missing map or missing uid falls back to `default`.
    """
    try:
        durations = schedule.get("days", {}).get(str(day_idx), {}).get("durations")
        if isinstance(durations, dict) and action_uid in durations:
            return float(durations[action_uid])
    except Exception:
        pass
    return default


def active_entry_now(schedule: dict, tz) -> Optional[Tuple[int, dict]]:
    """
    Return (weekday_idx, entry) for the currently active window, or None.

    Evaluates only today's window (no midnight-crossing).
    tz: pytz timezone object or IANA string — supplied by the caller via get_device_tz().
    """
    try:
        tz_obj = pytz.timezone(str(tz)) if isinstance(tz, str) else tz
        local_now = datetime.now(tz_obj)
    except Exception:
        local_now = datetime.utcnow()

    today_idx = local_now.weekday()
    now_min = local_now.hour * 60 + local_now.minute

    days = schedule.get("days", {})
    entry = days.get(str(today_idx))
    if not entry or not entry.get("enabled", True):
        return None

    try:
        s_min = time_to_minutes(entry["start"])
        e_min = time_to_minutes(entry["end"])
    except (ValueError, KeyError):
        return None

    # Window: [s_min, e_min). e_min == 1440 means "until end of day".
    in_window = s_min <= now_min < (e_min if e_min < 1440 else 1440) or (e_min == 1440 and now_min >= s_min)
    return (today_idx, entry) if in_window else None


def _epoch_of_wall_minutes(minutes: int, tz, now_epoch: float) -> Optional[float]:
    """`now_epoch` 가 속한 기기-로컬 날짜의 자정 + `minutes` 를 epoch 로.

    `minutes` 는 1440("24:00", 다음날 자정)까지 허용한다. 벽시계 → UTC 변환은
    `timekit.wall_to_utc` 에 맡긴다 — `naive.replace(tzinfo=)` 로 붙이면 DST
    경계에서 과거 offset 이 고정되는 pytz 함정에 걸린다.
    """
    try:
        from datetime import timedelta

        from aot.utils.timekit import wall_to_utc

        tz_obj = pytz.timezone(str(tz)) if isinstance(tz, str) else (tz or pytz.utc)
        midnight = datetime.fromtimestamp(now_epoch, tz_obj).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        return wall_to_utc(midnight + timedelta(minutes=int(minutes)), tz_obj).timestamp()
    except Exception:
        logger.exception("_epoch_of_wall_minutes: 벽시계 → epoch 변환 실패")
        return None


def window_bounds_epoch(entry: dict, tz, now_epoch: float):
    """(창 시작 epoch, 창 끝 epoch). 어느 쪽이든 못 구하면 그 자리는 None.

    끝을 아는 것이 왜 필요한가: 남은 창이 한 pass 보다 짧은데 새 사이클을
    시작하면, 밸브가 열리자마자 창이 닫혀 강제로 끊긴다. 그렇게 끊긴 스텝은
    개방 시간이 기록되지 않아 흔적조차 남지 않는다.
    """
    start = end = None
    try:
        start = _epoch_of_wall_minutes(time_to_minutes(entry["start"]), tz, now_epoch)
    except (KeyError, TypeError, ValueError):
        pass
    try:
        end = _epoch_of_wall_minutes(time_to_minutes(entry["end"]), tz, now_epoch)
    except (KeyError, TypeError, ValueError):
        pass
    return start, end


def window_start_epoch(entry: dict, tz, now_epoch: float) -> Optional[float]:
    """`now_epoch` 가 속한 기기-로컬 날짜의 창 시작 시각을 epoch 로 돌려준다.

    시퀀스 사이클 **격자의 원점**이다. 격자를 창 시작에 고정해야 실행 지연이
    다음 사이클 시작으로 새지 않는다. 기준점을 매번 `= now` 로 다시 잡으면
    한 번 늦은 만큼이 그대로 다음 기준점에 상속돼 영구히 누적된다 — 원격
    출력처럼 왕복이 들쭉날쭉한 경로에서는 그 누적이 하루 수십 분에 이른다.
    타이머 트리거(`controller_trigger.py`)가 `+= period` / `epoch_of_next_time`
    으로 격자를 지키는 것과 같은 이유다.

    벽시계 → UTC 변환은 `timekit.wall_to_utc` 에 맡긴다. `naive.replace(tzinfo=)`
    로 붙이면 DST 경계에서 과거 offset 이 고정되는 pytz 함정에 걸린다.

    :return: 창 시작의 UTC epoch. start 가 없거나 파싱 불가면 None.
    """
    try:
        start_min = time_to_minutes(entry["start"])
    except (KeyError, TypeError, ValueError):
        return None
    return _epoch_of_wall_minutes(start_min, tz, now_epoch)


def is_continuity_boundary(schedule: dict, prev_day_idx: int, next_day_idx: int) -> bool:
    """
    Return True if the transition from prev_day to next_day is a continuity boundary:
    - Days are adjacent (next = (prev + 1) % 7)
    - prev_day.end == "24:00"
    - next_day.start == "00:00"
    - Both days are enabled
    """
    if (prev_day_idx + 1) % 7 != next_day_idx:
        return False

    days = schedule.get("days", {})
    prev = days.get(str(prev_day_idx), {})
    nxt  = days.get(str(next_day_idx), {})

    if not prev.get("enabled", True) or not nxt.get("enabled", True):
        return False

    try:
        return time_to_minutes(prev.get("end", "")) == 1440 and \
               time_to_minutes(nxt.get("start", "")) == 0
    except ValueError:
        return False


def get_today_idx(tz) -> int:
    """Return today's weekday index (0=Mon...6=Sun) in device timezone."""
    try:
        tz_obj = pytz.timezone(str(tz)) if isinstance(tz, str) else tz
        return datetime.now(tz_obj).weekday()
    except Exception:
        return datetime.utcnow().weekday()


def to_legacy(schedule: dict) -> Tuple[str, str, str, float]:
    """
    Extract legacy column values from a schedule for backward-compat sync.
    Returns (start_time, end_time, weekday_str, period).

    shared mode: uses shared entry.
    per_day mode: uses the first enabled day as representative for start/end/period.
    weekday_str is always derived from enabled days.
    """
    mode = schedule.get("mode", "shared")
    shared = schedule.get("shared", {})
    days = schedule.get("days", {})

    if mode == "shared":
        start  = shared.get("start",  "16:30")
        end    = shared.get("end",    "19:00")
        period = float(shared.get("period", 3600))
    else:
        start, end, period = "16:30", "19:00", 3600.0
        for i in range(7):
            entry = days.get(str(i), {})
            if entry.get("enabled", True):
                start  = entry.get("start",  "16:30")
                end    = entry.get("end",    "19:00")
                period = float(entry.get("period", 3600))
                break

    enabled = [str(i) for i in range(7) if days.get(str(i), {}).get("enabled", True)]
    weekday_str = ','.join(enabled)

    return start, end, weekday_str, period


def apply_shared_window(schedule: dict, start=None, end=None, period=None) -> bool:
    """레거시 컬럼 값을 **정본 JSON 에 반영**한다. `to_legacy()` 의 반대 방향.

    데몬은 `parse_schedule(timer_schedule) or from_legacy(...)` 로 창을 정하므로,
    JSON 이 한 번이라도 만들어진 시퀀스에서는 **레거시 컬럼만 고치면 아무 효과가
    없다**. 화면은 레거시 컬럼을 되읽어 새 값을 보여주고 데몬은 옛 창으로 계속
    도는, 조용한 어긋남이 된다(실측 2026-09-05: 레거시 `timer_end_time` 을
    11:11 로 바꿔도 실효 window_end 는 JSON 의 23:59 그대로였다).

    :return: 반영했으면 True. **per_day 모드면 아무것도 하지 않고 False** —
        요일마다 창이 다른 것이 per_day 의 존재 이유라, 전역 값 하나를 7일에
        퍼뜨리면 짜 둔 구성이 통째로 사라진다(주기에서 실제로 겪은 사고다).
        호출자는 False 를 받으면 **사용자에게 알려야 한다** — 조용히 버리면
        이 함수를 만든 이유가 없어진다.

    ⚠ 같은 계산이 아직 두 곳에 인라인으로 남아 있다(둘 다 정상 동작 중이라
    이번에는 건드리지 않았다). 셋 중 하나를 고치면 나머지도 함께 볼 것:
      - `routes_function.function_sequence_update_settings` (시간휠 shared 경로)
      - `widgets/widget_trigger_sequence.execute_at_modification` (위젯 저장)
    """
    if schedule.get("mode", "shared") != "shared":
        return False

    shared = schedule.setdefault("shared", {})
    days = schedule.setdefault("days", {})
    if start:
        shared["start"] = start
    if end:
        shared["end"] = end
    if period is not None:
        shared["period"] = int(float(period))

    # shared 모드는 "모든 요일이 같다" 가 정의다 — 요일 항목까지 맞춰야
    # `active_entry_now()` 가 오늘 항목에서 새 값을 읽는다.
    for i in range(7):
        entry = days.setdefault(str(i), {})
        if start:
            entry["start"] = start
        if end:
            entry["end"] = end
        if period is not None:
            entry["period"] = int(float(period))
    return True


def build_warnings(schedule: dict) -> list:
    """
    Return human-readable warnings for a valid schedule (e.g. period > window length).
    Does not re-validate structure.
    """
    warnings = []
    days = schedule.get("days", {})
    for i in range(7):
        entry = days.get(str(i), {})
        if not entry.get("enabled", True):
            continue
        try:
            s_min   = time_to_minutes(entry["start"])
            e_min   = time_to_minutes(entry["end"])
            period  = int(entry.get("period", 3600))
            win_sec = (e_min - s_min) * 60
            if period > win_sec:
                warnings.append(
                    f"{DAY_NAMES[i]}: period ({period}s) > window length ({win_sec}s) — "
                    "cycle will be cut short"
                )
        except (ValueError, KeyError):
            pass
    return warnings
