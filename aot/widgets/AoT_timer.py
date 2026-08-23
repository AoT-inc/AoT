# coding=utf-8
#
#  This file is a modified version of a source file from the Mycodo project.
#  The modifications were made by AoT to adapt the software to the AoT project needs.
#
#  -----------------------------------------------------------------------
#  🔹 Original Mycodo License and Copyright
#
#  Copyright (C) 2015-2022 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <https://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#
#  -----------------------------------------------------------------------
#  🔸 Modifications by AoT
#
#  This file has been modified from the original Mycodo version to serve
#  the purposes of the AoT project.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Modified by AoT, a smart agriculture technology company based in Korea.
#
#  License:
#  This modified version continues to be licensed under the GNU General Public License v3,
#  in accordance with the terms of the original license.
#
#  Summary:
#    This software is a derivative of the open-source Mycodo project, modified to suit the AoT project.
#    This file is distributed under the GNU GPLv3 license and retains the original copyright terms.
#
#  Last modified: 2025-10-11

import logging
import datetime
import copy
from flask import jsonify, request
import threading
import queue
import time
import os
import json
from flask_login import current_user
from pytz import timezone
from aot.utils.influx import read_influxdb_list
from aot.utils.database import db_retrieve_table_daemon
from aot.databases.models import OutputChannel, Output, Misc
from aot.aot_client import DaemonControl
from aot.aot_flask.access import scope
from aot.aot_flask.utils import utils_general
from aot.utils.device_tz import get_device_tz
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.constraints_pass import constraints_pass_positive_or_zero_value

# --- local validator: UTC offset must be within [-12.0, 14.0]
# returns (True, None) if ok, else (False, 'error message')
def constraints_pass_utc_offset(value):
    try:
        v = float(value)
    except Exception:
        return False, lazy_gettext('Must be a number.')
    if v < -12.0 or v > 14.0:
        return False, lazy_gettext('Allowed range is -12.0 to +14.0.')
    return True, None


logger = logging.getLogger(__name__)

# ---- Last session cache (file-backed) ----
_SESS_DIR = "/tmp/aot_timer_sessions"
os.makedirs(_SESS_DIR, exist_ok=True)

def _sess_path(device_unique_id: str, channel_id: str) -> str:
    safe_dev = ''.join(c for c in device_unique_id if c.isalnum() or c in ('-', '_'))
    safe_ch = ''.join(c for c in channel_id if c.isalnum() or c in ('-', '_'))
    return os.path.join(_SESS_DIR, f"{safe_dev}__{safe_ch}.json")

def _sess_read(device_unique_id: str, channel_id: str):
    try:
        p = _sess_path(device_unique_id, channel_id)
        if not os.path.exists(p):
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _sess_write(device_unique_id: str, channel_id: str, payload: dict) -> bool:
    try:
        p = _sess_path(device_unique_id, channel_id)
        tmp = p + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except Exception:
        return False
#
# ---- Last session cache endpoints (file-backed) ----
def aot_timer_output_last_session_public(device_unique_id, channel_id):
    try:
        data = _sess_read(device_unique_id, channel_id)
        if not data:
            return '', 204
        return jsonify(data)
    except Exception:
        return '', 204

def aot_timer_output_last_session_set(device_unique_id, channel_id):
    """Private: save last session (start_ms, stop_ms, elapsed_sec, widget_id).
    Body: JSON {"widget_id": str, "start_ms": int, "stop_ms": int, "elapsed_sec": int}
    """
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        from flask import request
        js = request.get_json(silent=True) or {}
        wid = str(js.get('widget_id', '')).strip()
        start_ms = int(js.get('start_ms', 0))
        stop_ms = int(js.get('stop_ms', 0))
        elapsed_sec = int(js.get('elapsed_sec', 0))
        if start_ms <= 0 or stop_ms < start_ms or elapsed_sec < 0:
            return jsonify({"error": "invalid"}), 400
        payload = {
            "widget_id": wid,
            "start_ms": start_ms,
            "stop_ms": stop_ms,
            "elapsed_sec": elapsed_sec,
            "saved_at_ms": int(time.time() * 1000)
        }
        ok = _sess_write(device_unique_id, channel_id, payload)
        if not ok:
            return '', 204
        return jsonify({"ok": True})
    except Exception:
        return '', 204

#
# Helper: resolve channel id that may be an integer index or an OutputChannel unique_id (UUID)
def _resolve_channel_index(device_unique_id, channel_id):
    """
    Returns an integer channel index if resolvable, else None.
    Accepts either plain integer strings (e.g., '0') or OutputChannel.unique_id (UUID).
    """
    # Fast path: integer-like channel_id
    try:
        return int(channel_id)
    except Exception:
        pass
    # UUID path: look up OutputChannel by unique_id
    try:
        oc = db_retrieve_table_daemon(OutputChannel).filter(OutputChannel.unique_id == channel_id).first()
        if oc is not None and getattr(oc, 'channel', None) is not None:
            return int(getattr(oc, 'channel'))
    except Exception as e:
        logger.debug(f"_resolve_channel_index lookup failed for device {device_unique_id}, channel_id {channel_id}: {e}")
    return None

#
#
# Helper: try multiple channels and pick the freshest start-time
def _read_latest_started_at(device_unique_id, primary_ch_index, lookback_sec):
    """
    Attempts to read 'output_started_at' from Influx for the given output.
    Tries the primary channel index first, then reasonable fallbacks (0..3),
    returning the newest (latest) point among those that exist.
    Returns: dict with metadata, or None.
    """
    try:
        tried = set()
        candidates = []  # list[(last_ts:int, last_val:any)]

        def _read_one(ch):
            data = read_influxdb_list(
                unique_id=device_unique_id,
                unit='s',
                channel=ch,
                measure='output_started_at',
                duration_sec=lookback_sec
            )
            if data:
                # read_influxdb_list 는 시간순을 보장하지 않는다 — data[-1] 을 최신으로
                # 집으면 몇 시간 전 ON 시각이 뽑혀 '작동 시간' 이 00:00 이 아니라
                # 1:48:xx 부터 세기 시작한다(2026-08-13 실측).
                last_ts, last_val = max(data, key=lambda _p: int(_p[0]))
                candidates.append((int(last_ts), last_val))

        # Primary first
        if primary_ch_index is not None:
            tried.add(primary_ch_index)
            try:
                _read_one(primary_ch_index)
            except Exception:
                pass

        # Small fallback channels commonly used
        for ch in (0, 1, 2, 3):
            if ch in tried:
                continue
            try:
                _read_one(ch)
            except Exception:
                pass

        if not candidates:
            return None

        # Pick newest by point timestamp
        point_ts, last_val = max(candidates, key=lambda p: p[0])

        # Parse value as epoch seconds if looks like seconds/ms
        value_epoch = None
        try:
            v = int(float(last_val))
            if v > 1e10:         # ms → sec
                value_epoch = int(v / 1000)
            elif v >= 1e9:       # sec
                value_epoch = v
        except Exception:
            value_epoch = None

        selected = point_ts
        source = 'point_ts'

        # If value looks valid, prefer it unless it smells like a locally-encoded epoch (e.g., KST as UTC)
        if isinstance(value_epoch, int):
            diff = abs(value_epoch - point_ts)
            # Treat a 6–12 hour difference (±15min tolerance) as suspect; prefer point_ts in that case
            if 6*3600 - 900 <= diff <= 12*3600 + 900:
                selected = point_ts
                source = 'point_ts_sanitized'
            else:
                selected = value_epoch
                source = 'value'

        return {
            "selected_epoch": int(selected),
            "point_ts_epoch": int(point_ts),
            "value_epoch": int(value_epoch) if isinstance(value_epoch, int) else None,
            "source": source
        }
    except Exception:
        return None

#
# ---- Timeout-safe wrapper for _read_latest_started_at ----
def _read_latest_started_at_safe(device_unique_id, primary_ch_index, lookback_sec, timeout_sec=2.0):
    """Call _read_latest_started_at in a worker thread with a hard timeout.
    Returns None on timeout or exceptions, guaranteeing the Flask route responds.
    """
    q: "queue.Queue[object]" = queue.Queue(maxsize=1)

    def _worker():
        try:
            res = _read_latest_started_at(device_unique_id, primary_ch_index, lookback_sec)
            try:
                q.put_nowait(res)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"_read_latest_started_at_safe worker error: {e}")
            try:
                q.put_nowait(None)
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        res = q.get(timeout=timeout_sec)
        return res
    except Exception:
        logger.debug(f"_read_latest_started_at_safe timeout after {timeout_sec}s for device={device_unique_id} ch={primary_ch_index}")
        return None

#
# ---- Read last duration (sec) from Influx; try multiple common measure names ----
def _read_last_duration(device_unique_id, primary_ch_index, lookback_sec):
    try:
        if primary_ch_index is None:
            return None
        measures = ['output_duration_sec', 'output_duration']
        last = None
        for m in measures:
            try:
                data = read_influxdb_list(
                    unique_id=device_unique_id,
                    unit='s',
                    channel=primary_ch_index,
                    measure=m,
                    duration_sec=lookback_sec
                )
                if data:
                    # take newest by ts — read_influxdb_list 는 시간순을 보장하지
                    # 않으므로 data[-1] 이 아니라 timestamp 최대값으로 고른다.
                    last_ts, last_val = max(data, key=lambda _p: int(_p[0]))
                    try:
                        v = int(float(last_val))
                    except Exception:
                        v = None
                    if v is not None and v >= 0:
                        if last is None or int(last_ts) > int(last[0]):
                            last = (last_ts, v)
            except Exception:
                continue
        if last is None:
            return None
        # Return seconds
        return int(last[1])
    except Exception:
        return None

# ---- Timeout-safe wrapper for _read_last_duration ----
def _read_last_duration_safe(device_unique_id, primary_ch_index, lookback_sec, timeout_sec=2.0):
    q: "queue.Queue[object]" = queue.Queue(maxsize=1)
    def _worker():
        try:
            res = _read_last_duration(device_unique_id, primary_ch_index, lookback_sec)
            try:
                q.put_nowait(res)
            except Exception:
                pass
        except Exception:
            try:
                q.put_nowait(None)
            except Exception:
                pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    try:
        return q.get(timeout=timeout_sec)
    except Exception:
        return None

# ---- Server endpoint: return last duration seconds (most recent completed ON session)
def aot_timer_output_last_duration(device_unique_id, channel_id):
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        duration_sec = 30 * 24 * 3600
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return '', 204
        dur = _read_last_duration_safe(device_unique_id, ch_index, duration_sec, timeout_sec=2.0)
        if dur is None:
            return '', 204
        return jsonify({"last_duration_sec": int(dur)})
    except Exception:
        return '', 204

# ---- Public variant ----
def aot_timer_output_last_duration_public(device_unique_id, channel_id):
    try:
        duration_sec = 30 * 24 * 3600
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return '', 204
        dur = _read_last_duration_safe(device_unique_id, ch_index, duration_sec, timeout_sec=2.0)
        if dur is None:
            return '', 204
        return jsonify({"last_duration_sec": int(dur)})
    except Exception:
        return '', 204

# ---- Server endpoint: return output start-time from Influx (duration_time, unit s)
def aot_timer_output_started_at(device_unique_id, channel_id):
    """
    Returns the most recent ON start timestamp for this output/channel.
    Only uses the new measurement 'output_started_at' (epoch seconds in value).
    Response:
      200: {"started_at_epoch": <sec>, "started_at_iso": "<ISO8601>"}
      204: when no data available or channel not resolvable
      401: when not authenticated (private endpoint)
    """
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401

        # Look-back window (extended to 30 days)
        duration_sec = 30 * 24 * 3600

        # Resolve channel index (supports integer or OutputChannel UUID)
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            logger.debug(f"output_started_at: channel resolve failed device={device_unique_id} channel_id={channel_id}")
            return '', 204

        # ---------- Only new measure: output_started_at ----------
        logger.debug(f"output_started_at: entering device={device_unique_id} ch={ch_index} lookback={duration_sec}s")
        res = _read_latest_started_at_safe(device_unique_id, ch_index, duration_sec, timeout_sec=2.0)
        if res is None:
            logger.debug(f"output_started_at: no 'output_started_at' points device={device_unique_id} ch={ch_index} (with fallbacks)")

            return '', 204

        if isinstance(res, int):
            started_ts = int(res)
            point_ts_epoch = None
            source = 'legacy'
        else:
            started_ts = int(res.get('selected_epoch'))
            point_ts_epoch = int(res.get('point_ts_epoch')) if res.get('point_ts_epoch') is not None else None
            source = str(res.get('source') or 'value')

        started_dt = datetime.datetime.utcfromtimestamp(int(started_ts)).replace(tzinfo=timezone('UTC'))
        payload = {
            "started_at_epoch": int(started_ts),
            "started_at_iso": started_dt.isoformat(),
            "point_ts_epoch": int(point_ts_epoch) if point_ts_epoch is not None else None,
            "source": source
        }
        return jsonify(payload)
    except Exception as e:
        logger.debug(f"output_started_at error: {e}")
        return '', 204

# ---- Public variant ----
def aot_timer_output_started_at_public(device_unique_id, channel_id):
    """
    Public version of output_started_at (no auth check).
    """
    try:
        # Look-back window (extended to 30 days)
        duration_sec = 30 * 24 * 3600

        # Resolve channel index
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return '', 204

        # ---------- Only new measure: output_started_at ----------
        res = _read_latest_started_at_safe(device_unique_id, ch_index, duration_sec, timeout_sec=2.0)
        if res is None:
            return '', 204

        if isinstance(res, int):
            started_ts = int(res)
            point_ts_epoch = None
            source = 'legacy'
        else:
            started_ts = int(res.get('selected_epoch'))
            point_ts_epoch = int(res.get('point_ts_epoch')) if res.get('point_ts_epoch') is not None else None
            source = str(res.get('source') or 'value')

        started_dt = datetime.datetime.utcfromtimestamp(int(started_ts)).replace(tzinfo=timezone('UTC'))
        payload = {
            "started_at_epoch": int(started_ts),
            "started_at_iso": started_dt.isoformat(),
            "point_ts_epoch": int(point_ts_epoch) if point_ts_epoch is not None else None,
            "source": source
        }
        return jsonify(payload)
    except Exception:
        return '', 204

# =====================================================================
# Unified cycle engine (merged from AoT_on_off_counter)
# Server-side worker drives output ON/OFF for two operation modes:
#   - simple : single run for run_sec (run_sec == 0 => infinite hold until stop)
#   - cycle  : run_sec ON / rest_sec OFF, repeated target_cycles times
# Optional scheduled start (wall-clock hh:mm in the device timezone).
# State/preset files reuse the *_counter.json / *_presets.json names so an
# existing On/Off Counter widget's saved session is picked up after migration.
# =====================================================================
_CYCLE_LOCK = threading.Lock()
_CYCLE_STATE_CACHE = {}
_CYCLE_WORKERS = {}
_CYCLE_PRESETS_CACHE = {}


def _cyc_sanitize(value):
    return ''.join(c for c in str(value) if c.isalnum() or c in ('-', '_'))


def _cyc_state_path(device_unique_id, channel_id):
    return os.path.join(_SESS_DIR, f"{_cyc_sanitize(device_unique_id)}__{_cyc_sanitize(channel_id)}__counter.json")


def _cyc_preset_path(device_unique_id, channel_id):
    return os.path.join(_SESS_DIR, f"{_cyc_sanitize(device_unique_id)}__{_cyc_sanitize(channel_id)}__presets.json")


def _cyc_state_read(device_unique_id, channel_id):
    try:
        path = _cyc_state_path(device_unique_id, channel_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _cyc_state_write(state):
    try:
        path = _cyc_state_path(state.get('device_unique_id', ''), state.get('channel_id', ''))
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.debug(f"cycle state write failed: {exc}")
        return False


def _cyc_preset_write(device_unique_id, channel_id, payload):
    try:
        path = _cyc_preset_path(device_unique_id, channel_id)
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug(f"cycle preset write failed: {exc}")


def _cyc_preset_read(device_unique_id, channel_id):
    try:
        path = _cyc_preset_path(device_unique_id, channel_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cyc_state_default(device_unique_id, channel_id):
    now = int(time.time() * 1000)
    return {
        "device_unique_id": device_unique_id,
        "channel_id": channel_id,
        "mode": "simple",
        "run_sec": 0,
        "rest_sec": 0,
        "target_cycles": 0,
        "current_cycle": 0,
        "completed_cycles": 0,
        "phase": "idle",
        "active": False,
        "phase_started_ms": None,
        "phase_duration_sec": 0,
        "next_transition_ms": None,
        "started_at_ms": None,
        "stopped_at_ms": None,
        "start_at": "00:00",
        "scheduled_until_ms": None,
        "message": "Inactive",
        "error": None,
        "updated_ms": now
    }


def _cyc_key(device_unique_id, channel_id):
    return f"{device_unique_id}::{channel_id}"


def _cyc_state_ref(device_unique_id, channel_id):
    key = _cyc_key(device_unique_id, channel_id)
    state = _CYCLE_STATE_CACHE.get(key)
    if state is None:
        loaded = _cyc_state_read(device_unique_id, channel_id)
        state = loaded if isinstance(loaded, dict) else _cyc_state_default(device_unique_id, channel_id)
        _CYCLE_STATE_CACHE[key] = state
    return state


def _cyc_state_snapshot(device_unique_id, channel_id):
    with _CYCLE_LOCK:
        return copy.deepcopy(_cyc_state_ref(device_unique_id, channel_id))


def _cyc_state_update(device_unique_id, channel_id, **updates):
    now = int(time.time() * 1000)
    with _CYCLE_LOCK:
        state = _cyc_state_ref(device_unique_id, channel_id)
        state.update(updates)
        state['device_unique_id'] = device_unique_id
        state['channel_id'] = channel_id
        state['updated_ms'] = now
        _cyc_state_write(state)
        return copy.deepcopy(state)


def _cyc_preset_get(device_unique_id, channel_id):
    key = _cyc_key(device_unique_id, channel_id)
    with _CYCLE_LOCK:
        cached = copy.deepcopy(_CYCLE_PRESETS_CACHE.get(key))
    if cached is not None:
        return cached
    data = _cyc_preset_read(device_unique_id, channel_id)
    if isinstance(data, dict):
        with _CYCLE_LOCK:
            _CYCLE_PRESETS_CACHE[key] = data
        return copy.deepcopy(data)
    return None


def _cyc_preset_set(device_unique_id, channel_id, run_sec, rest_sec, cycles):
    payload = {
        "run_sec": int(run_sec),
        "rest_sec": int(rest_sec),
        "cycles": int(cycles),
        "updated_ms": int(time.time() * 1000)
    }
    key = _cyc_key(device_unique_id, channel_id)
    with _CYCLE_LOCK:
        _CYCLE_PRESETS_CACHE[key] = payload
    _cyc_preset_write(device_unique_id, channel_id, payload)


def _cyc_decorate(state):
    payload = copy.deepcopy(state)
    now_ms = int(time.time() * 1000)
    payload['server_now_ms'] = now_ms
    # Total operation time must not run before operation actually begins:
    # null out started_at_ms for pre-operation phases so no client (even a
    # cached/old one) can count during the scheduled wait or init.
    if payload.get('phase') in ('scheduled', 'initializing', 'idle'):
        payload['started_at_ms'] = None
    phase_start = payload.get('phase_started_ms')
    phase_duration = payload.get('phase_duration_sec') or 0
    if isinstance(phase_start, int) and phase_start > 0 and phase_duration > 0:
        elapsed = max(0, int((now_ms - phase_start) / 1000))
        remaining = max(0, int(phase_duration) - elapsed)
    else:
        elapsed = 0
        remaining = 0
    payload['phase_elapsed_sec'] = elapsed
    payload['phase_remaining_sec'] = remaining
    sched = payload.get('scheduled_until_ms')
    payload['scheduled_remaining_sec'] = (
        max(0, int((sched - now_ms) / 1000)) if isinstance(sched, int) and sched > now_ms else 0)
    return payload


def _sleep_with_cancel(stop_event, seconds):
    """Sleep for 'seconds' while watching stop_event. Returns True if completed."""
    if seconds <= 0:
        return True
    end_time = time.time() + seconds
    while True:
        remaining = end_time - time.time()
        if remaining <= 0:
            return True
        if stop_event.wait(timeout=min(1.0, max(0.1, remaining))):
            return False


def _issue_output_command(daemon, device_unique_id, channel_index, state, duration_sec):
    try:
        amount = max(0.0, float(duration_sec))
        res = daemon.output_on_off(device_unique_id, state, output_type='sec', amount=amount, output_channel=channel_index)
        if isinstance(res, tuple) and res and res[0]:
            return False, res[1]
        return True, None
    except Exception as exc:
        return False, str(exc)


def _issue_output_command_with_retry(daemon, device_unique_id, channel_index, state, duration_sec,
                                     stop_event=None, retries=3, retry_delay=3.0):
    """Call _issue_output_command up to `retries` times.
    Waits `retry_delay` seconds between attempts; returns immediately if stop_event is set.
    """
    last_err = None
    for attempt in range(1, retries + 1):
        if stop_event is not None and stop_event.is_set():
            return False, 'cancelled'
        ok, err = _issue_output_command(daemon, device_unique_id, channel_index, state, duration_sec)
        if ok:
            return True, None
        last_err = err
        if attempt < retries:
            logger.debug(
                "output_command retry %d/%d failed for %s ch=%s state=%s: %s",
                attempt, retries, device_unique_id, channel_index, state, err)
            if stop_event is not None:
                if stop_event.wait(timeout=retry_delay):
                    return False, 'cancelled'
            else:
                time.sleep(retry_delay)
    return False, last_err


def _wait_for_confirm(daemon, device_unique_id, channel_index, stop_event, timeout=20.0):
    """Poll output_state until the device confirms the ON (Model A: runtime counts
    from the confirmed-on, not the dispatch).

    Returns:
      'on'        — device confirmed on (a synchronous output returns this at once)
      'fault'     — device did not confirm (offline); caller shows an offline phase
      'timeout'   — no resolution within the window (treated like offline)
      'cancelled' — the timer was stopped while waiting
    """
    end = time.time() + max(1.0, float(timeout))
    while time.time() < end:
        if stop_event is not None and stop_event.is_set():
            return 'cancelled'
        try:
            st = daemon.output_state(device_unique_id, output_channel=channel_index)
        except Exception:
            st = None
        if st == 'on' or (isinstance(st, (int, float)) and not isinstance(st, bool) and st > 0):
            return 'on'
        if st == 'fault':
            return 'fault'
        if stop_event is not None and stop_event.wait(timeout=1.0):
            return 'cancelled'
        if stop_event is None:
            time.sleep(1.0)
    return 'timeout'


def _force_output_off(device_unique_id, channel_id):
    try:
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return
        _issue_output_command(DaemonControl(), device_unique_id, ch_index, 'off', 0)
    except Exception as exc:
        logger.debug(f"force_output_off failed: {exc}")


def _cyc_stop_worker(device_unique_id, channel_id, reason='user_stop'):
    key = _cyc_key(device_unique_id, channel_id)
    with _CYCLE_LOCK:
        worker = _CYCLE_WORKERS.pop(key, None)
    thread = None
    if worker:
        worker['stop_event'].set()
        thread = worker.get('thread')
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    message = 'User stopped' if reason == 'user_stop' else 'Initializing'
    _cyc_state_update(
        device_unique_id, channel_id,
        active=False, phase='stopped', message=message, error=None,
        next_transition_ms=None, phase_duration_sec=0, phase_started_ms=None,
        scheduled_until_ms=None, stopped_at_ms=int(time.time() * 1000))
    _force_output_off(device_unique_id, channel_id)


def _cyc_worker(device_unique_id, channel_id, channel_index,
                run_sec, rest_sec, total_cycles, mode, scheduled_until_ms, stop_event):
    key = _cyc_key(device_unique_id, channel_id)
    # extended_timeout=True: allow up to 30 s Pyro5 RPC so remote-output HTTP
    # calls (which may need 15+ s on slow networks) don't time out mid-command.
    daemon = DaemonControl(pyro_timeout=90, extended_timeout=True)
    try:
        now_ms = int(time.time() * 1000)
        # started_at_ms is intentionally left None here so the total-time counter
        # does NOT run during the scheduled wait — it is set when operation begins.
        _cyc_state_update(
            device_unique_id, channel_id,
            active=True, phase='initializing', message='Initializing', mode=mode,
            run_sec=run_sec, rest_sec=rest_sec, target_cycles=total_cycles,
            current_cycle=0, completed_cycles=0, started_at_ms=None, stopped_at_ms=None,
            next_transition_ms=None, phase_started_ms=None, phase_duration_sec=0,
            scheduled_until_ms=scheduled_until_ms, error=None)

        # ---- Scheduled start: wait until the target wall-clock time ----
        if isinstance(scheduled_until_ms, int) and scheduled_until_ms > now_ms:
            wait_total = max(0, int((scheduled_until_ms - now_ms) / 1000))
            _cyc_state_update(
                device_unique_id, channel_id, phase='scheduled', message='Scheduled',
                phase_started_ms=now_ms, phase_duration_sec=wait_total,
                next_transition_ms=scheduled_until_ms)
            if not _sleep_with_cancel(stop_event, wait_total):
                _cyc_state_update(
                    device_unique_id, channel_id, active=False, phase='stopped',
                    message='User stopped', next_transition_ms=None, phase_duration_sec=0,
                    phase_started_ms=None, scheduled_until_ms=None,
                    stopped_at_ms=int(time.time() * 1000))
                return
            _cyc_state_update(device_unique_id, channel_id, scheduled_until_ms=None)

        # ---- Operation begins now: start the total-time counter here so the
        #      scheduled wait above is excluded from total operation time. ----
        _cyc_state_update(device_unique_id, channel_id, started_at_ms=int(time.time() * 1000))

        # ---- Infinite hold (simple mode, run_sec <= 0): ON until stopped ----
        if run_sec <= 0:
            ok, err = _issue_output_command_with_retry(
                daemon, device_unique_id, channel_index, 'on', 0, stop_event=stop_event)
            if not ok:
                _cyc_state_update(
                    device_unique_id, channel_id, active=False, phase='error',
                    message=lazy_gettext('ON Failed: {}').format(err), error=str(err),
                    next_transition_ms=None, phase_duration_sec=0, phase_started_ms=None,
                    stopped_at_ms=int(time.time() * 1000))
                return
            # Model A: only count runtime once the device confirms the ON.
            cst = _wait_for_confirm(daemon, device_unique_id, channel_index, stop_event)
            if cst == 'cancelled':
                return
            phase_start = int(time.time() * 1000)
            if cst == 'on':
                _cyc_state_update(
                    device_unique_id, channel_id, phase='running', current_cycle=1,
                    message='Active', phase_started_ms=phase_start, phase_duration_sec=0,
                    next_transition_ms=None, active=True)
            else:
                # Offline: device never confirmed. Show a distinct offline state and
                # do NOT count runtime; a later confirmation is not awaited here
                # (hold mode holds until stopped regardless).
                _cyc_state_update(
                    device_unique_id, channel_id, phase='offline', current_cycle=1,
                    message='Offline (no response)', phase_started_ms=None,
                    phase_duration_sec=0, next_transition_ms=None, active=True)
            stop_event.wait()  # hold indefinitely until stopped
            _issue_output_command(daemon, device_unique_id, channel_index, 'off', 0)
            _cyc_state_update(
                device_unique_id, channel_id, active=False, phase='stopped',
                message='User stopped', next_transition_ms=None, phase_duration_sec=0,
                phase_started_ms=None, completed_cycles=1, stopped_at_ms=int(time.time() * 1000))
            return

        # ---- Normal run / (rest) x cycles ----
        for cycle in range(1, total_cycles + 1):
            if stop_event.is_set():
                break
            ok, err = _issue_output_command_with_retry(
                daemon, device_unique_id, channel_index, 'on', run_sec, stop_event=stop_event)
            if not ok:
                _cyc_state_update(
                    device_unique_id, channel_id, active=False, phase='error',
                    message=lazy_gettext('ON Failed: {}').format(err), error=str(err),
                    next_transition_ms=None, phase_duration_sec=0, phase_started_ms=None,
                    stopped_at_ms=int(time.time() * 1000))
                return
            # Model A: gate the run countdown on device confirmation so runtime
            # reflects confirmed-on, not dispatch. Offline -> show offline, no count.
            cst = _wait_for_confirm(daemon, device_unique_id, channel_index, stop_event)
            if cst == 'cancelled':
                break
            phase_start = int(time.time() * 1000)
            if cst == 'on':
                _cyc_state_update(
                    device_unique_id, channel_id, phase='running', current_cycle=cycle,
                    message=f'{cycle}/{total_cycles}, Active', phase_started_ms=phase_start,
                    phase_duration_sec=max(1, run_sec), next_transition_ms=phase_start + run_sec * 1000,
                    active=True)
            else:
                _cyc_state_update(
                    device_unique_id, channel_id, phase='offline', current_cycle=cycle,
                    message=f'{cycle}/{total_cycles}, Offline (no response)', phase_started_ms=None,
                    phase_duration_sec=0, next_transition_ms=phase_start + run_sec * 1000,
                    active=True)
            if not _sleep_with_cancel(stop_event, run_sec):
                break
            _issue_output_command(daemon, device_unique_id, channel_index, 'off', 0)
            now_ms = int(time.time() * 1000)
            if rest_sec > 0:
                _cyc_state_update(
                    device_unique_id, channel_id, completed_cycles=cycle,
                    message=f'{cycle}/{total_cycles}, Resting', phase='resting',
                    phase_started_ms=now_ms, phase_duration_sec=rest_sec,
                    next_transition_ms=now_ms + rest_sec * 1000)
                if not _sleep_with_cancel(stop_event, rest_sec):
                    break
            else:
                _cyc_state_update(
                    device_unique_id, channel_id, completed_cycles=cycle,
                    message=f'{cycle}/{total_cycles}, Completed', phase='waiting',
                    phase_started_ms=None, phase_duration_sec=0, next_transition_ms=None)

        if stop_event.is_set():
            _cyc_state_update(
                device_unique_id, channel_id, active=False, phase='stopped',
                message='User stopped', next_transition_ms=None, phase_duration_sec=0,
                phase_started_ms=None, stopped_at_ms=int(time.time() * 1000))
        else:
            _cyc_state_update(
                device_unique_id, channel_id, active=False, phase='completed',
                message='All cycles completed', current_cycle=total_cycles,
                completed_cycles=total_cycles, next_transition_ms=None, phase_duration_sec=0,
                phase_started_ms=None, stopped_at_ms=int(time.time() * 1000))
    finally:
        _issue_output_command(daemon, device_unique_id, channel_index, 'off', 0)
        with _CYCLE_LOCK:
            existing = _CYCLE_WORKERS.get(key)
            if existing and existing.get('thread') is threading.current_thread():
                _CYCLE_WORKERS.pop(key, None)


def _cyc_start_worker(device_unique_id, channel_id, channel_index,
                      run_sec, rest_sec, total_cycles, mode, scheduled_until_ms):
    _cyc_stop_worker(device_unique_id, channel_id, reason='restart')
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_cyc_worker,
        args=(device_unique_id, channel_id, channel_index, run_sec, rest_sec,
              total_cycles, mode, scheduled_until_ms, stop_event),
        daemon=True)
    key = _cyc_key(device_unique_id, channel_id)
    with _CYCLE_LOCK:
        _CYCLE_WORKERS[key] = {'thread': thread, 'stop_event': stop_event}
    thread.start()


_RECOVERED = False
_RECOVER_LOCK = threading.Lock()


def _cyc_trigger_recovery_once():
    """Kick off scheduled-worker recovery exactly once, in the background.

    Triggered lazily from a request handler (NOT during app creation) so it can
    never block or break aotflask startup. The actual work runs in a daemon
    thread so the request returns immediately even if the daemon RPC is slow.

    The flag is checked+set under a lock: with gunicorn gthread, two concurrent
    first polls could otherwise both pass the check and spawn duplicate recovery
    threads, re-arming the same schedule twice (two workers fighting one output
    -> toggle flicker / output not operating).
    """
    global _RECOVERED
    with _RECOVER_LOCK:
        if _RECOVERED:
            return
        _RECOVERED = True
    try:
        threading.Thread(target=recover_scheduled_workers, daemon=True).start()
    except Exception as exc:
        logger.debug("recovery thread spawn failed: %s", exc)


def recover_scheduled_workers():
    """Re-arm scheduled-but-not-yet-fired workers persisted to disk.

    The cycle worker runs as an in-memory daemon thread, so an aotflask restart
    loses any pending schedule. Scans the state files and restarts workers for
    entries still in the 'scheduled' phase with a future target time, so a
    schedule armed before a restart still fires.
    """
    try:
        now_ms = int(time.time() * 1000)
        if not os.path.isdir(_SESS_DIR):
            return
        for fn in os.listdir(_SESS_DIR):
            if not fn.endswith('__counter.json'):
                continue
            try:
                with open(os.path.join(_SESS_DIR, fn), 'r', encoding='utf-8') as f:
                    st = json.load(f)
            except Exception:
                continue
            if not isinstance(st, dict) or st.get('phase') != 'scheduled':
                continue
            sched = st.get('scheduled_until_ms')
            if not (isinstance(sched, int) and sched > now_ms):
                continue
            dev = st.get('device_unique_id')
            ch = st.get('channel_id')
            if not dev or ch in (None, ''):
                continue
            key = _cyc_key(dev, ch)
            with _CYCLE_LOCK:
                if key in _CYCLE_WORKERS:
                    continue
            ch_index = _resolve_channel_index(dev, ch)
            if ch_index is None:
                continue
            run = int(st.get('run_sec', 0) or 0)
            rest = int(st.get('rest_sec', 0) or 0)
            cycles = int(st.get('target_cycles', 1) or 1)
            mode = st.get('mode', 'cycle')
            logger.info(
                "AoT_timer: re-arming scheduled worker %s::%s (fires in %ss)",
                dev, ch, int((sched - now_ms) / 1000))
            _cyc_start_worker(dev, ch, ch_index, run, rest, cycles, mode, sched)
    except Exception as exc:
        logger.debug("recover_scheduled_workers failed: %s", exc)


def _cyc_device_tz(device_unique_id):
    """pytz timezone for the output device, using the app-wide common standard
    (aot.utils.device_tz.get_device_tz): device.timezone -> coords(timezonefinder)
    -> Misc.timezone -> UTC. This honors the device's physical location."""
    out = None
    try:
        out = db_retrieve_table_daemon(Output, unique_id=device_unique_id)
    except Exception:
        out = None
    try:
        return get_device_tz(out)
    except Exception:
        return timezone('UTC')


def _cyc_compute_scheduled_ms(start_at, device_unique_id):
    """'HH:MM' -> epoch ms of next occurrence in the device's (location-based) timezone.
    '00:00' (or invalid) -> None (immediate). If today's time already passed, use tomorrow.
    Localizes via pytz so DST transitions are handled correctly."""
    try:
        parts = str(start_at or '').strip().split(':')
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        return None
    if hh == 0 and mm == 0:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    tz = _cyc_device_tz(device_unique_id)
    now_local = datetime.datetime.now(tz)

    def _localize(naive):
        # pytz needs localize() for correct (DST-aware) offsets; fall back for zoneinfo.
        try:
            return tz.localize(naive)
        except (AttributeError, ValueError):
            return naive.replace(tzinfo=tz)

    naive_target = now_local.replace(tzinfo=None).replace(hour=hh, minute=mm, second=0, microsecond=0)
    target = _localize(naive_target)
    if target <= now_local:
        target = _localize(naive_target + datetime.timedelta(days=1))
    return int(target.timestamp() * 1000)


def _cyc_validate(payload, mode):
    try:
        run_sec = int(payload.get('run_sec', 0))
        rest_sec = int(payload.get('rest_sec', 0))
        cycles = int(payload.get('cycles', 0))
    except Exception:
        return None
    max_seconds = 24 * 3600
    if mode == 'cycle':
        # run_sec == 0 => infinite hold (run until off); otherwise normal run/rest cycle
        if run_sec < 0 or rest_sec < 0 or cycles <= 0:
            return None
        if run_sec > max_seconds or rest_sec > max_seconds or cycles > 1000:
            return None
        return run_sec, rest_sec, cycles
    # simple: run_sec >= 0 (0 = infinite hold), single cycle, no rest
    if run_sec < 0 or run_sec > max_seconds:
        return None
    return run_sec, 0, 1


def aot_timer_cycle_status_public(device_unique_id, channel_id):
    _cyc_trigger_recovery_once()
    try:
        return jsonify(_cyc_decorate(_cyc_state_snapshot(device_unique_id, channel_id)))
    except Exception:
        return '', 204


def aot_timer_cycle_presets(device_unique_id, channel_id):
    try:
        data = _cyc_preset_get(device_unique_id, channel_id)
        if not data:
            return '', 204
        return jsonify(data)
    except Exception:
        return '', 204


def aot_timer_cycle_start(device_unique_id, channel_id):
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        if not utils_general.user_has_permission('edit_controllers'):
            return jsonify({"error": "forbidden"}), 403
        # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
        if not scope.can_operate_device(device_unique_id):
            return jsonify({"error": "forbidden",
                            "message": scope.deny_message()}), 403
        payload = request.get_json(silent=True) or {}
        mode = 'cycle' if str(payload.get('mode', 'simple')) == 'cycle' else 'simple'
        validated = _cyc_validate(payload, mode)
        if not validated:
            return jsonify({"error": "invalid"}), 400
        run_sec, rest_sec, cycles = validated
        channel_index = _resolve_channel_index(device_unique_id, channel_id)
        if channel_index is None:
            return jsonify({"error": "channel"}), 400
        scheduled_until_ms = _cyc_compute_scheduled_ms(payload.get('start_at', '00:00'), device_unique_id)
        _cyc_preset_set(device_unique_id, channel_id, run_sec, rest_sec, cycles)
        _cyc_start_worker(device_unique_id, channel_id, channel_index,
                          run_sec, rest_sec, cycles, mode, scheduled_until_ms)
        return jsonify(_cyc_decorate(_cyc_state_snapshot(device_unique_id, channel_id)))
    except Exception as exc:
        logger.debug(f"aot_timer_cycle_start error: {exc}")
        return jsonify({"error": "server_error"}), 500


def aot_timer_cycle_stop(device_unique_id, channel_id):
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        if not utils_general.user_has_permission('edit_controllers'):
            return jsonify({"error": "forbidden"}), 403
        # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
        if not scope.can_operate_device(device_unique_id):
            return jsonify({"error": "forbidden",
                            "message": scope.deny_message()}), 403
        _cyc_stop_worker(device_unique_id, channel_id, reason='user_stop')
        return jsonify(_cyc_decorate(_cyc_state_snapshot(device_unique_id, channel_id)))
    except Exception as exc:
        logger.debug(f"aot_timer_cycle_stop error: {exc}")
        return jsonify({"error": "server_error"}), 500


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_timer',
    'widget_name': lazy_gettext('AoT Timer'),
    # On mobile (<=768px), place only one widget per row (full width). If False/unset, allow two per row.
    'mobile_full_width': True,
    'widget_library': 'timer',
    'no_class': True,

    'message': lazy_gettext('Use the toggle switch to turn the device on and off. Turn on "Timer" to operate on a timer: in Simple mode the device runs once for the set time (0 = run until stopped), and in Cycle mode it repeats a Run / Rest sequence for the set number of cycles. "Scheduled Start" begins operation at a set wall-clock time in the device timezone. When "Timer" is off, the toggle simply switches the device on or off regardless of the time settings.'),

    'widget_width': 24,
    'widget_height': 7,

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('Device Settings')
        },
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'options_select': [
                'Output_Channels',
            ],
            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select the Output to control.')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 5.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Sync (seconds)'),
            'phrase': lazy_gettext('How often the widget refreshes the operation status from the server (in seconds).')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Display Settings')
        },
        {
            'id': 'enable_status',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show Status'),
            'phrase': lazy_gettext('Display operation status on the title bar.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Time Settings')
        },
        {
            'id': 'enable_output_controls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Timer'),
            'phrase': lazy_gettext('When enabled, shows the timed controls (Run / Rest / Cycles / Scheduled Start). When disabled, the toggle simply turns the device on or off.')
        },
        {
            'id': 'operation_mode',
            'type': 'select',
            'default_value': 'simple',
            'options_select': [
                ('simple', lazy_gettext('Simple (single run / hold)')),
                ('cycle', lazy_gettext('Cycle (run / rest repeated)')),
            ],
            'name': lazy_gettext('Operation Mode'),
            'phrase': lazy_gettext('Cycle: shows Run / Rest / Cycles inputs, repeats the run/rest for a number of cycles. Simple: single Run time only (0 = run until stopped).')
        },
        {
            'id': 'start_at',
            'type': 'text',
            'default_value': '00:00',
            'name': lazy_gettext('Scheduled Start (hh:mm)'),
            'phrase': lazy_gettext('Start at this wall-clock time (device timezone). 00:00 = start immediately. If the time already passed today, starts tomorrow.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Cycle Settings')
        },
        {
            'id': 'default_run_seconds',
            'type': 'float',
            'default_value': 0.0,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_gettext('Default Run Time (s)'),
            'phrase': lazy_gettext('Default run time to use at start')
        },
        {
            'id': 'default_rest_seconds',
            'type': 'float',
            'default_value': 0.0,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_gettext('Default Rest Time (s)'),
            'phrase': lazy_gettext('Default rest time between cycles (cycle mode)')
        },
        {
            'id': 'default_cycles',
            'type': 'float',
            'default_value': 5.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Default Cycle Count'),
            'phrase': lazy_gettext('Default number of automatic cycles (cycle mode)')
        }
    ],

    # ------------------ HEAD (CSS) ------------------
    'widget_dashboard_head': """
    <link rel="stylesheet" href="/static/css/components/aot-toggle.css?v=20260814a">
    <!-- Shared time-wheel module (also used by other widgets) -->
    <link rel="stylesheet" href="/static/css/components/aot-time-wheel.css?v=20260813a">
    <script src="/static/js/components/aot-time-wheel.js?v=20260813d"></script>
    """,

    'endpoints': [
        ("/aot_timer_output_started_at/<device_unique_id>/<channel_id>", "aot_timer_output_started_at", aot_timer_output_started_at, ["GET"]),
        ("/aot_timer_output_started_at_public/<device_unique_id>/<channel_id>", "aot_timer_output_started_at_public", aot_timer_output_started_at_public, ["GET"]),

        ("/aot_timer_output_last_duration/<device_unique_id>/<channel_id>", "aot_timer_output_last_duration", aot_timer_output_last_duration, ["GET"]),
        ("/aot_timer_output_last_duration_public/<device_unique_id>/<channel_id>", "aot_timer_output_last_duration_public", aot_timer_output_last_duration_public, ["GET"]),
        ("/aot_timer_output_last_session_public/<device_unique_id>/<channel_id>", "aot_timer_output_last_session_public", aot_timer_output_last_session_public, ["GET"]),
        ("/aot_timer_output_last_session_set/<device_unique_id>/<channel_id>", "aot_timer_output_last_session_set", aot_timer_output_last_session_set, ["POST"]),

        ("/aot_timer_cycle_status_public/<device_unique_id>/<channel_id>", "aot_timer_cycle_status_public", aot_timer_cycle_status_public, ["GET"]),
        ("/aot_timer_cycle_start/<device_unique_id>/<channel_id>", "aot_timer_cycle_start", aot_timer_cycle_start, ["POST"]),
        ("/aot_timer_cycle_stop/<device_unique_id>/<channel_id>", "aot_timer_cycle_stop", aot_timer_cycle_stop, ["POST"]),
        ("/aot_timer_cycle_presets/<device_unique_id>/<channel_id>", "aot_timer_cycle_presets", aot_timer_cycle_presets, ["GET"]),
    ],

    # ------------------ TITLE BAR ------------------
    'widget_dashboard_title_bar': """
    {%- if widget_options['enable_status'] -%}
      <span id="tm_state_{{each_widget.unique_id}}"></span>
    {%- else -%}
      <span style="display:none" id="tm_state_{{each_widget.unique_id}}"></span>
    {%- endif %}

    <span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>
    """,

    # ------------------ BODY ------------------
    'widget_dashboard_body': """
    <style>
    /* ===== AoT On/Off Counter — Modern UI ===== */
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-controls {
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: 100%;
      padding: 4px 0 6px 0;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      min-height: 36px;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-label {
      font-size: 0.9em;
      font-weight: 600;
      color: var(--aot-text-main, #333);
      white-space: nowrap;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-field {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    /* Hour:Minute:Second trigger - tapping opens the custom drum-wheel overlay */
    /* time trigger & cycles input share the SAME box width */
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-trigger,
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-cycles {
      box-sizing: border-box;
      width: 7.6em;
      height: 34px;
      text-align: center;
      font-variant-numeric: tabular-nums;
      border: 1px solid var(--border-neutral, #d7d3c4);
      border-radius: 9999px !important;
      background: var(--aot-input-bg, #fff);
      color: var(--aot-text-main, #333);
      box-shadow: none !important;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-trigger {
      font-weight: 600;
      letter-spacing: 0.04em;
      padding: 0 1em !important;
      cursor: pointer;
      transition: border-color 0.15s ease;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-cycles {
      font-weight: 500;
      padding: 0 !important;
      -webkit-appearance: none;
      -moz-appearance: textfield;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-trigger:hover,
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-trigger:focus {
      outline: none;
      border-color: var(--color-zone-mode, #2ecc71);
    }
    /* active phase counting down */
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-trigger.is-counting {
      color: var(--color-zone-mode, #2ecc71);
      border-color: var(--color-zone-mode, #2ecc71);
      font-weight: 700;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-cycles::-webkit-inner-spin-button,
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-cycles::-webkit-outer-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-cycles:focus {
      outline: none;
      border-color: var(--color-zone-mode, #2ecc71);
    }
    /* Reserve horizontal width for the toggle column (same as AoT_timer.py) */
    #aot_tm_{{each_widget.unique_id}} .col-aot-2 {
      width: 60px !important;
      border: none !important;
    }
    /* live time-counting line (total + current phase) */
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-times {
      display: flex;
      align-items: center;
      gap: 0.3em;
      line-height: 1.2;
    }
    /* Font size is unified in the global .prt-text-inline rule - here only color/weight */
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-lbl {
      font-weight: 600;
      color: var(--text-medium-gray, #8a8a8a);
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-time-val {
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: var(--aot-text-main, #333);
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-msg {
      font-size: 0.8em;
      line-height: 1.3;
      color: var(--text-medium-gray, #8a8a8a);
    }
    #aot_tm_{{each_widget.unique_id}} .aot-cnt-msg:empty {
      display: none;
    }
    </style>

    {%- set wo = widget_options if widget_options is defined else {} -%}

    {%- set output = wo.get('output', '') -%}
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if output and ',' in output -%}
      {%- set device_id = output.split(',')[0] -%}
      {%- set channel_id = output.split(',')[1] -%}
    {%- endif -%}
    {%- set refresh_seconds = wo.get('refresh_seconds', 5.0) -%}
    {%- set default_run = [wo.get('default_run_seconds', 0)|int, 86399]|min -%}
    {%- set default_rest = [wo.get('default_rest_seconds', 0)|int, 86399]|min -%}
    {%- set default_cycles = wo.get('default_cycles', 5)|int -%}
    {%- set operation_mode = wo.get('operation_mode', 'simple') -%}
    {%- set start_at = wo.get('start_at', '00:00') -%}
    {%- set run_hms = '%02d:%02d:%02d'|format(default_run // 3600, (default_run % 3600) // 60, default_run % 60) -%}
    {%- set rest_hms = '%02d:%02d:%02d'|format(default_rest // 3600, (default_rest % 3600) // 60, default_rest % 60) -%}

    <div class="frame-aot inactive-background"
         id="aot_tm_{{each_widget.unique_id}}"
         data-device="{{device_id}}"
         data-channel="{{channel_id}}"
         data-mode="{{operation_mode}}"
         data-timer="{{ '1' if widget_options['enable_output_controls'] else '0' }}"
         data-refresh="{{refresh_seconds}}">
      <div class="row-aot-1">
        <div class="col-aot-1">
          <div class="aot-cnt-status aot-w-body" style="display:flex;align-items:center;flex-wrap:wrap;gap:0.2em 0.55em">
            <span class="prt-text prt-text-inline" id="aot_tm_summary_{{each_widget.unique_id}}">0/0</span>
            <span class="prt-text prt-text-inline" id="aot_tm_phase_{{each_widget.unique_id}}">{{_('Inactive')}}</span>
            <span class="aot-cnt-times">
              <span class="prt-text prt-text-inline aot-cnt-time-lbl">{{_('Total')}}</span>
              <span class="prt-text prt-text-inline aot-cnt-time-val" id="aot_tm_total_{{each_widget.unique_id}}">--</span>
            </span>
          </div>
        </div>
        <div class="col-aot-2">
          <label class="btn-toggle">
            <input type="checkbox"
                   id="tm_tog_{{each_widget.unique_id}}"
                   class="btn-toggle-input aot-tm-cycle-toggle"
                   data-wid="{{each_widget.unique_id}}"
                   name="{{device_id}}/{{channel_id}}">
            <span class="btn-toggle-slider">
              <span class="btn-toggle-thumb"></span>
            </span>
          </label>
        </div>
      </div>

      <span class="prt-text aot-cnt-msg" id="aot_tm_message_{{each_widget.unique_id}}"></span>

      {% if widget_options['enable_output_controls'] %}
      <div class="aot-cnt-controls">

        <div class="aot-cnt-row">
          <span class="aot-cnt-label" title="hh:mm:ss">{% if operation_mode == 'cycle' %}{{_('Run')}}{% else %}{{_('Time')}}{% endif %}</span>
          <div class="aot-cnt-field">
            <input type="hidden" id="aot_tm_run_{{each_widget.unique_id}}" value="{{ run_hms }}">
            <button type="button"
                    id="aot_tm_run_trigger_{{each_widget.unique_id}}"
                    class="aot-cnt-time-trigger aot-tm-wheel-trigger"
                    data-wid="{{each_widget.unique_id}}" data-key="run"
                    title="hh:mm:ss"
                    aria-label="{{_('Run')}} (hh:mm:ss)">{{ run_hms }}</button>
          </div>
        </div>

        {% if operation_mode == 'cycle' %}
        <div class="aot-cnt-row">
          <span class="aot-cnt-label" title="hh:mm:ss">{{_('Rest')}}</span>
          <div class="aot-cnt-field">
            <input type="hidden" id="aot_tm_rest_{{each_widget.unique_id}}" value="{{ rest_hms }}">
            <button type="button"
                    id="aot_tm_rest_trigger_{{each_widget.unique_id}}"
                    class="aot-cnt-time-trigger aot-tm-wheel-trigger"
                    data-wid="{{each_widget.unique_id}}" data-key="rest"
                    title="hh:mm:ss"
                    aria-label="{{_('Rest')}} (hh:mm:ss)">{{ rest_hms }}</button>
          </div>
        </div>

        <div class="aot-cnt-row">
          <span class="aot-cnt-label">{{_('Cycles')}}</span>
          <div class="aot-cnt-field">
            <input type="number" min="1" inputmode="numeric"
                   id="aot_tm_cycles_{{each_widget.unique_id}}"
                   class="aot-cnt-cycles" value="{{ default_cycles }}" aria-label="cycles">
          </div>
        </div>
        {% else %}
        <input type="hidden" id="aot_tm_rest_{{each_widget.unique_id}}" value="00:00:00">
        <input type="hidden" id="aot_tm_cycles_{{each_widget.unique_id}}" value="1">
        {% endif %}

        <div class="aot-cnt-row">
          <span class="aot-cnt-label" title="hh:mm">{{_('Start at')}}</span>
          <div class="aot-cnt-field">
            <input type="hidden" id="aot_tm_startat_{{each_widget.unique_id}}" value="{{ start_at }}">
            <button type="button"
                    id="aot_tm_startat_trigger_{{each_widget.unique_id}}"
                    class="aot-cnt-time-trigger aot-tm-wheel-trigger"
                    data-wid="{{each_widget.unique_id}}" data-key="startat"
                    title="hh:mm"
                    aria-label="{{_('Start at')}} (hh:mm)">{{ start_at }}</button>
          </div>
        </div>

      </div>
      {% endif %}

      {% if not (device_id and channel_id) %}
      <div class="row-aot-2">
        <span class="prt-text">{{_('Select the Output to control in the widget options.')}}</span>
      </div>
      {% endif %}
    </div>
    """,

    # ------------------ JAVASCRIPT ------------------
    'widget_dashboard_js': """
    (function(){
      const counterIntervals = {};

      function frame(wid){ return $('#aot_tm_'+wid); }

      // Route user-facing feedback through the global toast (respects
      // AoTGlobalSettings hide flags); fall back to console if unavailable.
      function notify(message, type){
        if (typeof window.showToast === 'function') {
          window.showToast(message, type || 'info');
        } else {
          console.warn('[AoT Timer]', message);
        }
      }

      function parseInfo(wid){
        const $frame = frame(wid);
        return {
          device: ($frame.attr('data-device') || '').trim(),
          channel: ($frame.attr('data-channel') || '').trim(),
          refresh: parseFloat($frame.attr('data-refresh') || '5')
        };
      }

      // ---- hh:mm:ss helpers (value stored as "HH:MM:SS" in hidden input) ----
      const HMS_MAX = 86399; // 23:59:59
      function pad2(n){ return (n < 10 ? '0' : '') + n; }
      function secToHMS(totalSec){
        let total = parseInt(totalSec, 10);
        if (!Number.isFinite(total) || total < 0) total = 0;
        if (total > HMS_MAX) total = HMS_MAX;
        const hh = Math.floor(total / 3600);
        const mm = Math.floor((total % 3600) / 60);
        const ss = total % 60;
        return pad2(hh)+':'+pad2(mm)+':'+pad2(ss);
      }
      function readHMS(wid, key){
        const raw = ($('#aot_tm_'+key+'_'+wid).val() || '').trim();
        if (!raw) { return 0; }
        const parts = raw.split(':');
        const hh = parseInt(parts[0], 10) || 0;
        const mm = parseInt(parts[1], 10) || 0;
        const ss = parts.length > 2 ? (parseInt(parts[2], 10) || 0) : 0;
        return (hh * 3600) + (mm * 60) + ss;
      }
      function writeHMS(wid, key, totalSec){
        const str = secToHMS(totalSec);
        $('#aot_tm_'+key+'_'+wid).val(str);
        $('#aot_tm_'+key+'_trigger_'+wid).text(str);
      }

      // ===== Time picker: delegate to the shared AoTTimeWheel module =====
      // (module: /static/js/components/aot-time-wheel.js + .css — reusable by other widgets)
      function openWheel(wid, key){
        if (!window.AoTTimeWheel) { console.warn('[AoT Timer] AoTTimeWheel module not loaded'); return; }
        if (key === 'startat') {
          // Scheduled start uses hh:mm only.
          window.AoTTimeWheel.open({
            title: window._('Start at'),
            value: readHMS(wid, 'startat'),
            fields: 'hm',
            onConfirm: function(totalSec, hm){
              $('#aot_tm_startat_'+wid).val(hm);
              $('#aot_tm_startat_trigger_'+wid).text(hm);
            }
          });
          return;
        }
        const label = (key === 'run') ? window._('Run') : window._('Rest');
        window.AoTTimeWheel.open({
          title: label,
          value: readHMS(wid, key),
          max: 86399,
          onConfirm: function(totalSec){ writeHMS(wid, key, totalSec); }
        });
      }

      function applyPresetValues(wid, data){
        if (!data || typeof data !== 'object') return;
        if (Number.isFinite(data.run_sec) && data.run_sec > 0) {
          writeHMS(wid, 'run', data.run_sec);
        }
        if (Number.isFinite(data.rest_sec) && data.rest_sec >= 0) {
          writeHMS(wid, 'rest', data.rest_sec);
        }
        if (Number.isFinite(data.cycles) && data.cycles > 0) {
          $('#aot_tm_cycles_'+wid).val(parseInt(data.cycles, 10));
        }
      }

      async function fetchPresetValues(wid){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        try{
          const res = await fetch(`/aot_timer_cycle_presets/${info.device}/${info.channel}`, {
            headers: { 'Accept': 'application/json' }
          });
          if (!res.ok || res.status === 204) { return; }
          const data = await res.json();
          applyPresetValues(wid, data);
        }catch(err){
          console.warn('[AoT Timer] preset fetch error', err);
        }
      }

      async function fetchStatus(wid){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        try {
          const res = await fetch(`/aot_timer_cycle_status_public/${info.device}/${info.channel}`, {
            headers: { 'Accept': 'application/json' }
          });
          if (!res.ok || res.status === 204) { return; }
          const data = await res.json();
          render(wid, data);
        } catch (err) {
          console.warn('[AoT Timer] status fetch error', err);
        }
      }

      // Never surface internal UUIDs to the user.
      const _UUID_RE = /[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g;
      function stripUuid(s){
        if (typeof s !== 'string') { return s; }
        return s.replace(_UUID_RE, '').replace(/\s{2,}/g, ' ').trim();
      }
      // 총 작동 시간은 늘 HH:MM:SS 다. 예전에는 1시간 미만일 때 시 자리를 떨어뜨려
      // "12:34" 로 나왔는데, 바로 아래 Run/Rest 는 secToHMS 로 "00:12:34" 라
      // 같은 카드 안에서 자릿수가 갈렸다.
      // secToHMS 를 쓰면 안 된다 — 그쪽은 시간 입력 위젯용이라 23:59:59 에서
      // 값을 자른다. 총 작동 시간은 하루를 넘길 수 있으므로 자르지 않는 공용
      // 포매터를 쓴다.
      function fmtClock(sec){
        const total = Math.max(0, Math.floor(sec));
        if (window.AoTTime && window.AoTTime.formatDuration) {
          return window.AoTTime.formatDuration(total);
        }
        return pad2(Math.floor(total / 3600)) + ':' +
               pad2(Math.floor((total % 3600) / 60)) + ':' + pad2(total % 60);
      }

      // ---- Live time counting (shared-timer style, ref AoT_timer.py) ----
      // Row 1 shows the TOTAL operation time; the per-phase countdown runs directly
      // inside the Run / Rest time displays (the active phase ticks down, the other
      // shows its configured value).
      const _tickData = {};
      const _tickTimers = {};
      function restoreTrigger(wid, key){
        const setStr = ($('#aot_tm_'+key+'_'+wid).val() || '').trim() || '00:00:00';
        const $t = $('#aot_tm_'+key+'_trigger_'+wid);
        $t.text(setStr).removeClass('is-counting');
      }
      function updateTimeDisplay(wid){
        const d = _tickData[wid];
        const $tot = $('#aot_tm_total_'+wid);
        if (!d) { return; }
        const now = Date.now() + (d.off || 0);
        // Total operation time (row 1) — NOT counted before operation begins
        // (scheduled wait / initializing show '--').
        const preOp = (d.phase === 'scheduled' || d.phase === 'initializing');
        if (d.startedAtMs && !preOp) {
          const endMs = d.active ? now : (d.stoppedAtMs || now);
          $tot.text(fmtClock((endMs - d.startedAtMs) / 1000));
        } else {
          $tot.text('--');
        }
        // Per-phase countdown inside Run / Rest displays
        if (d.active && d.phaseStartMs && d.phaseDur > 0 && (d.phase === 'running' || d.phase === 'resting')) {
          const remain = Math.max(0, d.phaseDur - (now - d.phaseStartMs) / 1000);
          const activeKey = (d.phase === 'running') ? 'run' : 'rest';
          const otherKey = (activeKey === 'run') ? 'rest' : 'run';
          $('#aot_tm_'+activeKey+'_trigger_'+wid).text(secToHMS(remain)).addClass('is-counting');
          restoreTrigger(wid, otherKey);
        } else {
          restoreTrigger(wid, 'run');
          restoreTrigger(wid, 'rest');
        }
      }
      function startTick(wid){
        if (_tickTimers[wid]) { return; }
        _tickTimers[wid] = setInterval(function(){ updateTimeDisplay(wid); }, 1000);
      }
      function stopTick(wid){
        if (_tickTimers[wid]) { clearInterval(_tickTimers[wid]); delete _tickTimers[wid]; }
      }

      function render(wid, data){
        if (!data || typeof data !== 'object') { return; }
        const current = (typeof data.current_cycle === 'number' && data.current_cycle > 0)
          ? data.current_cycle : (data.completed_cycles || 0);
        const total = (typeof data.target_cycles === 'number' && data.target_cycles > 0)
          ? data.target_cycles : 0;
        const rawMessage = stripUuid((typeof data.message === 'string' ? data.message : '').trim());
        // Updated regex to handle both Korean '회' and English 'Completed/Resting/Active'
        const strippedMessage = rawMessage.replace(/^\s*\d+\s*\/\s*\d+\s*([가-힣a-zA-Z]+)?\s*,?\s*/,'').trim();
        const phaseLine = window._(strippedMessage || rawMessage || 'Inactive');
        const summaryText = `${current}/${total || 0}`;
        $('#aot_tm_summary_'+wid).text(summaryText);
        $('#aot_tm_phase_'+wid).text(phaseLine);

        // Set up / refresh the live time counter from server-reported timestamps.
        _tickData[wid] = {
          active: !!data.active,
          phase: (typeof data.phase === 'string') ? data.phase : '',
          startedAtMs: (typeof data.started_at_ms === 'number' && data.started_at_ms > 0) ? data.started_at_ms : null,
          stoppedAtMs: (typeof data.stopped_at_ms === 'number' && data.stopped_at_ms > 0) ? data.stopped_at_ms : null,
          phaseStartMs: (typeof data.phase_started_ms === 'number' && data.phase_started_ms > 0) ? data.phase_started_ms : null,
          phaseDur: data.phase_duration_sec || 0,
          off: (typeof data.server_now_ms === 'number') ? (data.server_now_ms - Date.now()) : 0
        };
        if (data.active) { startTick(wid); } else { stopTick(wid); }
        updateTimeDisplay(wid);

        const $msg = $('#aot_tm_message_'+wid);
        if ($msg.length) {
          if (data.error) {
            $msg.text(stripUuid(window._(data.error))).addClass('text-danger');
          } else if (data.message) {
            $msg.text(stripUuid(window._(data.message))).removeClass('text-danger');
          } else {
            $msg.text('').removeClass('text-danger');
          }
        }

        const $frame = frame(wid);
        if (data.active) {
          $frame.removeClass('inactive-background pause-background')
                .addClass('active-background');
        } else {
          $frame.removeClass('active-background pause-background')
                .addClass('inactive-background');
        }

        const $toggle = $('#tm_tog_'+wid);
        if ($toggle.length) {
          const shouldCheck = !!data.active;
          if ($toggle.is(':checked') !== shouldCheck) {
            $toggle.prop('checked', shouldCheck);
          }
        }

        const stateLine = `${summaryText} ${phaseLine}`;
        const $state = $('#tm_state_'+wid);
        if ($state.length) {
          $state.text(stateLine);
        }
      }

      async function start(wid, opts){
        const info = parseInfo(wid);
        const toggleEl = opts && opts.toggleEl ? opts.toggleEl : null;
        if (!info.device || !info.channel) {
          notify(window._('Please select an Output first.'), 'warning');
          if (toggleEl) { toggleEl.prop('checked', false); }
          return;
        }
        // When the Timer function is disabled, the time controls are not rendered,
        // so the toggle acts as a plain on/off: hold the device ON (run_sec 0 =
        // run until stopped) regardless of any time settings. This keeps the
        // toggle idempotent with the "Timer off" option instead of failing on
        // the missing run/rest/cycle inputs.
        const timerEnabled = ($('#aot_tm_'+wid).attr('data-timer') || '1') !== '0';
        let mode, run, rest, cycles, startAt;
        if (!timerEnabled) {
          mode = 'simple'; run = 0; rest = 0; cycles = 1; startAt = '00:00';
        } else {
          mode = ($('#aot_tm_'+wid).attr('data-mode') || 'simple').trim();
          run = readHMS(wid, 'run');
          rest = (mode === 'cycle') ? readHMS(wid, 'rest') : 0;
          cycles = (mode === 'cycle') ? (parseInt($('#aot_tm_cycles_'+wid).val(), 10) || 0) : 1;
          startAt = ($('#aot_tm_startat_'+wid).val() || '00:00').trim();
          if (mode === 'cycle') {
            // run == 0 is allowed: run until off (infinite hold)
            if (run < 0 || rest < 0 || cycles <= 0) {
              notify(window._('Please check the run/rest/cycle values.'), 'warning');
              if (toggleEl) { toggleEl.prop('checked', false); }
              return;
            }
          } else if (run < 0) {
            if (toggleEl) { toggleEl.prop('checked', false); }
            return;
          }
        }
        const payload = { mode: mode, run_sec: run, rest_sec: rest, cycles: cycles, start_at: startAt };
        try {
          const csrfToken = $('meta[name="csrf-token"]').attr('content');
          const res = await fetch(`/aot_timer_cycle_start/${info.device}/${info.channel}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
          });
          if (res.ok) {
            const data = await res.json();
            render(wid, data);
            fetchStatus(wid);
          } else {
            let errText = window._('Failed to start');
            try {
              const js = await res.json();
              if (js && js.error) { errText = window._(js.error); }
            } catch (_) {}
            notify(errText, 'error');
            if (toggleEl) { toggleEl.prop('checked', false); }
          }
        } catch (err) {
          notify(window._('Error during start'), 'error');
          if (toggleEl) { toggleEl.prop('checked', false); }
        }
      }

      async function stop(wid, opts){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        const toggleEl = opts && opts.toggleEl ? opts.toggleEl : null;
        try {
          const csrfToken = $('meta[name="csrf-token"]').attr('content');
          const res = await fetch(`/aot_timer_cycle_stop/${info.device}/${info.channel}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-CSRFToken': csrfToken
            },
            body: '{}'
          });
          if (res.ok) {
            const data = await res.json();
            render(wid, data);
            fetchStatus(wid);
          } else {
            let errText = window._('Failed to stop');
            try {
              const js = await res.json();
              if (js && js.error) { errText = window._(js.error); }
            } catch (_) {}
            notify(errText, 'error');
            if (toggleEl) { toggleEl.prop('checked', true); }
          }
        } catch (err) {
          notify(window._('Error during stop'), 'error');
          if (toggleEl) { toggleEl.prop('checked', true); }
        }
      }

      function schedule(wid){
        if (counterIntervals[wid]) {
          clearInterval(counterIntervals[wid]);
          delete counterIntervals[wid];
        }
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        const refreshMs = Math.max(2, info.refresh || 5) * 1000;
        counterIntervals[wid] = setInterval(function(){ fetchStatus(wid); }, refreshMs);
        fetchStatus(wid);
      }

      window.initAoTTimerCycle = function(wid){
        fetchPresetValues(wid).finally(function(){
          schedule(wid);
        });
      };

      $(document)
        .off('change.aot_tm_toggle', '.aot-tm-cycle-toggle')
        .on('change.aot_tm_toggle', '.aot-tm-cycle-toggle', function(){
          const $el = $(this);
          const wid = $el.data('wid');
          if (!wid) { return; }
          if ($el.is(':checked')) {
            start(String(wid), { toggleEl: $el });
          } else {
            stop(String(wid), { toggleEl: $el });
          }
        });

      // Open the drum-wheel picker when a Run/Rest time field is tapped.
      $(document)
        .off('click.aot_tm_wheel', '.aot-tm-wheel-trigger')
        .on('click.aot_tm_wheel', '.aot-tm-wheel-trigger', function(){
          const $el = $(this);
          openWheel(String($el.data('wid')), String($el.data('key')));
        });
    })();
    """,

    # ------------------ JS READY ------------------
    'widget_dashboard_js_ready': """<!-- Counter widget ready hook -->""",

    # ------------------ JS READY END ------------------
    'widget_dashboard_js_ready_end': """
    {%- set wo = widget_options if widget_options is defined else {} -%}
    {%- set output = wo.get('output', '') -%}
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if output and ',' in output -%}
      {%- set device_id = output.split(',')[0] -%}
      {%- set channel_id = output.split(',')[1] -%}
    {%- endif -%}

    {%- if device_id and channel_id -%}
      initAoTTimerCycle('{{each_widget.unique_id}}');
    {%- else -%}
      console.warn('[AoT Timer] Output not configured for widget {{each_widget.unique_id}}');
    {%- endif -%}
    """
}
