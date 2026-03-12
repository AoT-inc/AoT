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
#  Korean Summary:
#    이 소프트웨어는 오픈소스 Mycodo 프로젝트를 기반으로 AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#    본 파일은 GNU GPLv3 라이선스에 따라 배포되며, 원저작권 조건을 그대로 따릅니다.
#
#  Last modified: 2025-11-11

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
from aot.databases.models import OutputChannel
from flask_babel import lazy_gettext
from aot.aot_client import DaemonControl
from aot.aot_flask.utils import utils_general
from aot.utils.constraints_pass import constraints_pass_positive_value

# --- local validator: UTC offset must be within [-12.0, 14.0]
# returns (True, None) if ok, else (False, 'error message')
def constraints_pass_utc_offset(value):
    try:
        v = float(value)
    except Exception:
        return False, lazy_gettext('Must be a number.')
    if v < -12.0 or v > 14.0:
        return False, lazy_gettext('Allowed range is -12.0 ~ +14.0.')
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
# ---- On/Off counter state (file + memory cache) ----
_COUNTER_LOCK = threading.Lock()
_COUNTER_STATE_CACHE = {}
_COUNTER_WORKERS = {}
_COUNTER_PRESETS_CACHE = {}
def _sanitize_token(value: str) -> str:
    return ''.join(c for c in str(value) if c.isalnum() or c in ('-', '_'))
def _counter_state_path(device_unique_id: str, channel_id: str) -> str:
    return os.path.join(
        _SESS_DIR,
        f"{_sanitize_token(device_unique_id)}__{_sanitize_token(channel_id)}__counter.json"
    )


def _counter_preset_path(device_unique_id: str, channel_id: str) -> str:
    return os.path.join(
        _SESS_DIR,
        f"{_sanitize_token(device_unique_id)}__{_sanitize_token(channel_id)}__presets.json"
    )
def _counter_state_read(device_unique_id: str, channel_id: str):
    try:
        path = _counter_state_path(device_unique_id, channel_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None
def _counter_state_write(state: dict) -> bool:
    try:
        device_unique_id = state.get('device_unique_id', '')
        channel_id = state.get('channel_id', '')
        path = _counter_state_path(device_unique_id, channel_id)
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.debug(f"counter state write failed: {exc}")
        return False


def _counter_preset_write(device_unique_id: str, channel_id: str, payload: dict) -> None:
    try:
        path = _counter_preset_path(device_unique_id, channel_id)
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug(f"counter preset write failed: {exc}")


def _counter_preset_read(device_unique_id: str, channel_id: str):
    try:
        path = _counter_preset_path(device_unique_id, channel_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
def _counter_state_default(device_unique_id: str, channel_id: str) -> dict:
    now = int(time.time() * 1000)
    return {
        "device_unique_id": device_unique_id,
        "channel_id": channel_id,
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
        "message": "Inactive",
        "error": None,
        "updated_ms": now
    }
def _counter_key(device_unique_id: str, channel_id: str) -> str:
    return f"{device_unique_id}::{channel_id}"
def _counter_state_ref(device_unique_id: str, channel_id: str) -> dict:
    key = _counter_key(device_unique_id, channel_id)
    state = _COUNTER_STATE_CACHE.get(key)
    if state is None:
        loaded = _counter_state_read(device_unique_id, channel_id)
        state = loaded if isinstance(loaded, dict) else _counter_state_default(device_unique_id, channel_id)
        _COUNTER_STATE_CACHE[key] = state
    return state
def _counter_state_snapshot(device_unique_id: str, channel_id: str) -> dict:
    with _COUNTER_LOCK:
        state = copy.deepcopy(_counter_state_ref(device_unique_id, channel_id))
    return state
def _counter_state_update(device_unique_id: str, channel_id: str, **updates) -> dict:
    now = int(time.time() * 1000)
    with _COUNTER_LOCK:
        state = _counter_state_ref(device_unique_id, channel_id)
        state.update(updates)
        state['device_unique_id'] = device_unique_id
        state['channel_id'] = channel_id
        state['updated_ms'] = now
        _counter_state_write(state)
        return copy.deepcopy(state)


def _counter_preset_get(device_unique_id: str, channel_id: str):
    key = _counter_key(device_unique_id, channel_id)
    with _COUNTER_LOCK:
        cached = copy.deepcopy(_COUNTER_PRESETS_CACHE.get(key))
    if cached is not None:
        return cached
    data = _counter_preset_read(device_unique_id, channel_id)
    if isinstance(data, dict):
        with _COUNTER_LOCK:
            _COUNTER_PRESETS_CACHE[key] = data
        return copy.deepcopy(data)
    return None


def _counter_preset_set(device_unique_id: str, channel_id: str, run_sec: int, rest_sec: int, cycles: int):
    payload = {
        "run_sec": int(run_sec),
        "rest_sec": int(rest_sec),
        "cycles": int(cycles),
        "updated_ms": int(time.time() * 1000)
    }
    key = _counter_key(device_unique_id, channel_id)
    with _COUNTER_LOCK:
        _COUNTER_PRESETS_CACHE[key] = payload
    _counter_preset_write(device_unique_id, channel_id, payload)
def _decorate_state_for_response(state: dict) -> dict:
    payload = copy.deepcopy(state)
    now_ms = int(time.time() * 1000)
    payload['server_now_ms'] = now_ms
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
    return payload
def _sleep_with_cancel(stop_event: threading.Event, seconds: int) -> bool:
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
def _issue_output_command(daemon: DaemonControl, device_unique_id: str, channel_index: int, state: str, duration_sec: int) -> tuple:
    try:
        amount = max(0.0, float(duration_sec))
        res = daemon.output_on_off(device_unique_id, state, output_type='sec', amount=amount, output_channel=channel_index)
        if isinstance(res, tuple) and res and res[0]:
            return False, res[1]
        return True, None
    except Exception as exc:
        return False, str(exc)
def _force_output_off(device_unique_id: str, channel_id: str) -> None:
    try:
        ch_index = _resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return
        daemon = DaemonControl()
        _issue_output_command(daemon, device_unique_id, ch_index, 'off', 0)
    except Exception as exc:
        logger.debug(f"force_output_off failed: {exc}")
def _stop_existing_worker(device_unique_id: str, channel_id: str, reason: str = 'user_stop') -> None:
    key = _counter_key(device_unique_id, channel_id)
    worker = None
    with _COUNTER_LOCK:
        worker = _COUNTER_WORKERS.pop(key, None)
    if worker:
        worker['stop_event'].set()
        thread = worker.get('thread')
    else:
        thread = None
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
    message = 'User stopped' if reason == 'user_stop' else 'Initializing'
    _counter_state_update(
        device_unique_id,
        channel_id,
        active=False,
        phase='stopped',
        message=message,
        error=None,
        next_transition_ms=None,
        phase_duration_sec=0,
        phase_started_ms=None,
        stopped_at_ms=int(time.time() * 1000)
    )
    _force_output_off(device_unique_id, channel_id)
def _counter_cycle_worker(device_unique_id: str,
                          channel_id: str,
                          channel_index: int,
                          run_sec: int,
                          rest_sec: int,
                          total_cycles: int,
                          stop_event: threading.Event) -> None:
    key = _counter_key(device_unique_id, channel_id)
    daemon = DaemonControl()
    try:
        now_ms = int(time.time() * 1000)
        _counter_state_update(
            device_unique_id,
            channel_id,
            active=True,
            phase='initializing',
            message='Initializing',
            run_sec=run_sec,
            rest_sec=rest_sec,
            target_cycles=total_cycles,
            current_cycle=0,
            completed_cycles=0,
            started_at_ms=now_ms,
            stopped_at_ms=None,
            next_transition_ms=None,
            phase_started_ms=None,
            phase_duration_sec=0,
            error=None
        )
        for cycle in range(1, total_cycles + 1):
            if stop_event.is_set():
                break
            ok, err = _issue_output_command(daemon, device_unique_id, channel_index, 'on', run_sec)
            if not ok:
                _counter_state_update(
                    device_unique_id,
                    channel_id,
                    active=False,
                    phase='error',
                    message=lazy_gettext('ON Failed: {}').format(err),
                    error=str(err),
                    next_transition_ms=None,
                    phase_duration_sec=0,
                    phase_started_ms=None,
                    stopped_at_ms=int(time.time() * 1000)
                )
                return
            phase_start = int(time.time() * 1000)
            _counter_state_update(
                device_unique_id,
                channel_id,
                phase='running',
                current_cycle=cycle,
                message=f'{cycle}/{total_cycles}, Active',
                phase_started_ms=phase_start,
                phase_duration_sec=max(1, run_sec),
                next_transition_ms=phase_start + run_sec * 1000,
                active=True
            )
            if not _sleep_with_cancel(stop_event, run_sec):
                break
            _issue_output_command(daemon, device_unique_id, channel_index, 'off', 0)
            now_ms = int(time.time() * 1000)
            if rest_sec > 0:
                _counter_state_update(
                    device_unique_id,
                    channel_id,
                    completed_cycles=cycle,
                    message=f'{cycle}/{total_cycles}, Resting',
                    phase='resting',
                    phase_started_ms=now_ms,
                    phase_duration_sec=rest_sec,
                    next_transition_ms=now_ms + rest_sec * 1000
                )
                if not _sleep_with_cancel(stop_event, rest_sec):
                    break
            else:
                _counter_state_update(
                    device_unique_id,
                    channel_id,
                    completed_cycles=cycle,
                    message=f'{cycle}/{total_cycles}, Completed',
                    phase='waiting',
                    phase_started_ms=None,
                    phase_duration_sec=0,
                    next_transition_ms=None
                )
        # Determine final status
        if stop_event.is_set():
            _counter_state_update(
                device_unique_id,
                channel_id,
                active=False,
                phase='stopped',
                message='User stopped',
                next_transition_ms=None,
                phase_duration_sec=0,
                phase_started_ms=None,
                stopped_at_ms=int(time.time() * 1000)
            )
        else:
            _counter_state_update(
                device_unique_id,
                channel_id,
                active=False,
                phase='completed',
                message='All cycles completed',
                current_cycle=total_cycles,
                completed_cycles=total_cycles,
                next_transition_ms=None,
                phase_duration_sec=0,
                phase_started_ms=None,
                stopped_at_ms=int(time.time() * 1000)
            )
    finally:
        _issue_output_command(daemon, device_unique_id, channel_index, 'off', 0)
        with _COUNTER_LOCK:
            existing = _COUNTER_WORKERS.get(key)
            if existing and existing.get('thread') is threading.current_thread():
                _COUNTER_WORKERS.pop(key, None)
def _start_cycle_worker(device_unique_id: str,
                        channel_id: str,
                        channel_index: int,
                        run_sec: int,
                        rest_sec: int,
                        total_cycles: int) -> None:
    _stop_existing_worker(device_unique_id, channel_id, reason='restart')
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_counter_cycle_worker,
        args=(device_unique_id, channel_id, channel_index, run_sec, rest_sec, total_cycles, stop_event),
        daemon=True
    )
    key = _counter_key(device_unique_id, channel_id)
    with _COUNTER_LOCK:
        _COUNTER_WORKERS[key] = {
            'thread': thread,
            'stop_event': stop_event
        }
    thread.start()

#
# ---- Last session cache endpoints (file-backed) ----
def output_last_session_public(device_unique_id, channel_id):
    try:
        data = _sess_read(device_unique_id, channel_id)
        if not data:
            return '', 204
        return jsonify(data)
    except Exception:
        return '', 204
    
def output_cycle_status_public(device_unique_id, channel_id):
    try:
        state = _counter_state_snapshot(device_unique_id, channel_id)
        return jsonify(_decorate_state_for_response(state))
    except Exception:
        return '', 204
def _validate_cycle_payload(payload: dict):
    try:
        run_sec = int(payload.get('run_sec', 0))
        rest_sec = int(payload.get('rest_sec', 0))
        cycles = int(payload.get('cycles', 0))
    except Exception:
        return None
    if run_sec <= 0 or rest_sec < 0 or cycles <= 0:
        return None
    max_seconds = 24 * 3600
    if run_sec > max_seconds or rest_sec > max_seconds or cycles > 1000:
        return None
    return run_sec, rest_sec, cycles
def output_cycle_start(device_unique_id, channel_id):
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        if not utils_general.user_has_permission('edit_controllers'):
            return jsonify({"error": "forbidden"}), 403
        payload = request.get_json(silent=True) or {}
        validated = _validate_cycle_payload(payload)
        if not validated:
            return jsonify({"error": "invalid"}), 400
        run_sec, rest_sec, cycles = validated
        channel_index = _resolve_channel_index(device_unique_id, channel_id)
        if channel_index is None:
            return jsonify({"error": "channel"}), 400
        _counter_preset_set(device_unique_id, channel_id, run_sec, rest_sec, cycles)
        _start_cycle_worker(device_unique_id, channel_id, channel_index, run_sec, rest_sec, cycles)
        state = _counter_state_snapshot(device_unique_id, channel_id)
        return jsonify(_decorate_state_for_response(state))
    except Exception as exc:
        logger.debug(f"output_cycle_start error: {exc}")
        return jsonify({"error": "server_error"}), 500
def output_cycle_stop(device_unique_id, channel_id):
    try:
        if not current_user.is_authenticated:
            return jsonify({"error": "unauthorized"}), 401
        if not utils_general.user_has_permission('edit_controllers'):
            return jsonify({"error": "forbidden"}), 403
        _stop_existing_worker(device_unique_id, channel_id, reason='user_stop')
        state = _counter_state_snapshot(device_unique_id, channel_id)
        return jsonify(_decorate_state_for_response(state))
    except Exception as exc:
        logger.debug(f"output_cycle_stop error: {exc}")
        return jsonify({"error": "server_error"}), 500


def output_cycle_presets(device_unique_id, channel_id):
    try:
        data = _counter_preset_get(device_unique_id, channel_id)
        if not data:
            return '', 204
        return jsonify(data)
    except Exception:
        return '', 204

def output_last_session_set(device_unique_id, channel_id):
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
                last_ts, last_val = data[-1]
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
                    # take newest by ts
                    last_ts, last_val = data[-1]
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
def output_last_duration(device_unique_id, channel_id):
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
def output_last_duration_public(device_unique_id, channel_id):
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
def output_started_at(device_unique_id, channel_id):
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
    


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_on_off_counter',
    'widget_name': lazy_gettext('AoT On/Off Counter'),
    'widget_library': 'timer',
    'no_class': True,

    'message': lazy_gettext(
        'Automatically turns the designated output ON/OFF when a run time, rest time, and number of cycles are input. '
        'The current progress is saved on the server and can be checked after refreshing or on other browsers.'
    ),

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
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Sync"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Maximum validity time for measurements used')
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
            'id': 'status_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Status Size'),
            'phrase': lazy_gettext('Size in (em)')
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Operation Time'),
            'phrase': lazy_gettext('Display operation time.')
        },
        {
            'id': 'widget_name_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Operation Time Font Size'),
            'phrase': lazy_gettext('Size in (em)')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Counter Settings')
        },
        {
            'id': 'enable_output_controls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Timer'),
            'phrase': lazy_gettext('Enable the timer function.')
        },
        {
            'id': 'font_em_time_input',
            'type': 'float',
            'default_value': 1.2,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Time Input Size'),
            'phrase': lazy_gettext('Size in (em)')
        },
        {
            'id': 'tz_offset',
            'type': 'select',
            'default_value': '9.0',
            'options_select': [
                ('9.0', lazy_gettext('Seoul (UTC+9)')),
                ('8.0', lazy_gettext('Beijing (UTC+8)')),
                ('7.0', lazy_gettext('Bangkok (UTC+7)')),
                ('6.0', lazy_gettext('Dhaka (UTC+6)')),
                ('5.5', lazy_gettext('New Delhi (UTC+5:30)')),
                ('4.0', lazy_gettext('Dubai (UTC+4)')),
                ('3.0', lazy_gettext('Riyadh (UTC+3)')),
                ('1.0', lazy_gettext('Berlin (UTC+1)')),
                ('0.0', lazy_gettext('London (UTC±0)')),
                ('-3.0', lazy_gettext('Buenos Aires (UTC-3)')),
                ('-5.0', lazy_gettext('New York (UTC-5)')),
                ('-6.0', lazy_gettext('Chicago (UTC-6)')),
                ('-8.0', lazy_gettext('Los Angeles (UTC-8)')),
                ('-9.0', lazy_gettext('Anchorage (UTC-9)')),
                ('-10.0', lazy_gettext('Honolulu (UTC-10)'))
            ],
            'name': lazy_gettext('Timezone'),
            'phrase': lazy_gettext('Select a city to apply its numeric offset.')
        },
        {
            'id': 'default_run_seconds',
            'type': 'float',
            'default_value': 10.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Default Run Time (s)'),
            'phrase': lazy_gettext('Default run time to use at start')
        },
        {
            'id': 'default_rest_seconds',
            'type': 'float',
            'default_value': 10.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Default Rest Time (s)'),
            'phrase': lazy_gettext('Default rest time between cycles')
        },
        {
            'id': 'default_cycles',
            'type': 'float',
            'default_value': 5.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Default Cycle Count'),
            'phrase': lazy_gettext('Default number of automatic cycles')
        }
    ],

    # ------------------ HEAD (CSS) ------------------
    'widget_dashboard_head': """
    <link rel="stylesheet" href="/static/css/components/aot-toggle.css">
    """,

    'endpoints': [
        ("/output_started_at/<device_unique_id>/<channel_id>", "output_started_at", output_started_at, ["GET"]),

        ("/output_last_duration/<device_unique_id>/<channel_id>", "output_last_duration", output_last_duration, ["GET"]),
        ("/output_last_duration_public/<device_unique_id>/<channel_id>", "output_last_duration_public", output_last_duration_public, ["GET"]),
        ("/output_last_session_public/<device_unique_id>/<channel_id>", "output_last_session_public", output_last_session_public, ["GET"]),
        ("/output_last_session_set/<device_unique_id>/<channel_id>", "output_last_session_set", output_last_session_set, ["POST"]),
        ("/output_cycle_status_public/<device_unique_id>/<channel_id>", "output_cycle_status_public", output_cycle_status_public, ["GET"]),
        ("/output_cycle_start/<device_unique_id>/<channel_id>", "output_cycle_start", output_cycle_start, ["POST"]),
        ("/output_cycle_stop/<device_unique_id>/<channel_id>", "output_cycle_stop", output_cycle_stop, ["POST"]),
        ("/output_cycle_presets/<device_unique_id>/<channel_id>", "output_cycle_presets", output_cycle_presets, ["GET"]),
    ],

    # ------------------ TITLE BAR ------------------
    'widget_dashboard_title_bar': """
    {%- if widget_options['enable_status'] -%}
      <span id="tm_state_{{each_widget.unique_id}}"></span>
    {%- else -%}
      <span style="display:none" id="tm_state_{{each_widget.unique_id}}"></span>
    {%- endif %}

    <span style="padding-right: 0.5em"> {{each_widget.name}}</span>
    """,

    # ------------------ BODY ------------------
    'widget_dashboard_body': """
    <style>
    /* 온오프 카운터 위젯 전용 UI 개선 */
    #aot_counter_{{each_widget.unique_id}} .col-aot-2 {
      width: 60px !important;
    }
    #aot_counter_{{each_widget.unique_id}} .input-time {
      border: none !important;
      box-shadow: none !important;
    }
    #aot_counter_{{each_widget.unique_id}} .input-time-ss {
      background-color: #ffffff !important;
      border: none !important;
      box-shadow: none !important;
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
    {%- set default_run = wo.get('default_run_seconds', 10) -%}
    {%- set default_rest = wo.get('default_rest_seconds', 10) -%}
    {%- set default_cycles = wo.get('default_cycles', 5) -%}

    <div class="frame-aot inactive-background"
         id="aot_counter_{{each_widget.unique_id}}"
         data-device="{{device_id}}"
         data-channel="{{channel_id}}"
         data-refresh="{{refresh_seconds}}">
      <div class="row-aot-1">
        <div class="col-aot-1">
          <span class="prt-text prt-text-inline" id="aot_counter_summary_{{each_widget.unique_id}}" style="font-size: {{widget_options['widget_name_font_em']}}em;">
            0/0
          </span>
          <span class="prt-text prt-text-inline" id="aot_counter_phase_{{each_widget.unique_id}}" style="font-size: {{widget_options['widget_name_font_em']}}em;">
            {{_('Inactive')}}
          </span>
        </div>
        <div class="col-aot-2" style="display:flex; justify-content:flex-end;">
          <label class="btn-toggle">
            <input type="checkbox"
                   id="tm_tog_{{each_widget.unique_id}}"
                   class="btn-toggle-input aot-counter-toggle"
                   data-wid="{{each_widget.unique_id}}"
                   name="{{device_id}}/{{channel_id}}">
            <span class="btn-toggle-slider">
              <span class="btn-toggle-thumb"></span>
            </span>
          </label>
        </div>
      </div>

      {% if widget_options['enable_output_controls'] %}
      <div class="row-aot-2">
        <div class="input-time" style="margin-left:auto;">
          <label style="margin-right:0.5em;">
            {{_('Run (s)')}}
            <input type="number"
                   min="1"
                   id="aot_counter_run_{{each_widget.unique_id}}"
                   class="input-time-hh"
                   value="{{ default_run|int }}"
                   style="font-size: {{widget_options['font_em_time_input']}}em;">
          </label>
          <label style="margin-right:0.5em;">
            {{_('Rest (s)')}}
            <input type="number"
                   min="0"
                   id="aot_counter_rest_{{each_widget.unique_id}}"
                   class="input-time-mm"
                   value="{{ default_rest|int }}"
                   style="font-size: {{widget_options['font_em_time_input']}}em;">
          </label>
          <label style="margin-right:0.5em;">
            {{_('Cycles')}}
            <input type="number"
                   min="1"
                   id="aot_counter_cycles_{{each_widget.unique_id}}"
                   class="input-time-ss"
                   value="{{ default_cycles|int }}"
                   style="font-size: {{widget_options['font_em_time_input']}}em;">
          </label>
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

      function frame(wid){ return $('#aot_counter_'+wid); }

      function parseInfo(wid){
        const $frame = frame(wid);
        return {
          device: ($frame.attr('data-device') || '').trim(),
          channel: ($frame.attr('data-channel') || '').trim(),
          refresh: parseFloat($frame.attr('data-refresh') || '5')
        };
      }

      function applyPresetValues(wid, data){
        if (!data || typeof data !== 'object') return;
        if (Number.isFinite(data.run_sec) && data.run_sec > 0) {
          $('#aot_counter_run_'+wid).val(parseInt(data.run_sec, 10));
        }
        if (Number.isFinite(data.rest_sec) && data.rest_sec >= 0) {
          $('#aot_counter_rest_'+wid).val(parseInt(data.rest_sec, 10));
        }
        if (Number.isFinite(data.cycles) && data.cycles > 0) {
          $('#aot_counter_cycles_'+wid).val(parseInt(data.cycles, 10));
        }
      }

      async function fetchPresetValues(wid){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        try{
          const res = await fetch((window.AoT_BASE_PATH || '') + `/output_cycle_presets/${info.device}/${info.channel}`, {
            headers: {
              'Accept': 'application/json',
              'X-CSRFToken': $('meta[name="csrf-token"]').attr('content')
            }
          });
          if (!res.ok || res.status === 204) { return; }
          const data = await res.json();
          applyPresetValues(wid, data);
        }catch(err){
          console.warn('[AoT Counter] preset fetch error', err);
        }
      }

      function fmtSeconds(sec){
        if (!isFinite(sec) || sec <= 0) { return '--'; }
        const total = Math.max(0, Math.floor(sec));
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        const parts = [];
        if (h > 0) parts.push(h + 'h');
        if (m > 0) parts.push(m + 'm');
        if (h === 0 && (m === 0 || s > 0)) {
          parts.push(s + 's');
        } else if (s > 0) {
          parts.push(s + 's');
        }
        return parts.join(' ');
      }

      async function fetchStatus(wid){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        try {
          const res = await fetch((window.AoT_BASE_PATH || '') + `/output_cycle_status_public/${info.device}/${info.channel}`, {
            headers: {
              'Accept': 'application/json',
              'X-CSRFToken': $('meta[name="csrf-token"]').attr('content')
            }
          });
          if (!res.ok || res.status === 204) { return; }
          const data = await res.json();
          render(wid, data);
        } catch (err) {
          console.warn('[AoT Counter] status fetch error', err);
        }
      }

      function render(wid, data){
        if (!data || typeof data !== 'object') { return; }
        const current = (typeof data.current_cycle === 'number' && data.current_cycle > 0)
          ? data.current_cycle : (data.completed_cycles || 0);
        const total = (typeof data.target_cycles === 'number' && data.target_cycles > 0)
          ? data.target_cycles : 0;
        const rawMessage = (typeof data.message === 'string' ? data.message : '').trim();
        // Updated regex to handle both Korean '회' and English 'Completed/Resting/Active'
        const strippedMessage = rawMessage.replace(/^\s*\d+\s*\/\s*\d+\s*([가-힣a-zA-Z]+)?\s*,?\s*/,'').trim();
        const phaseLine = window._(strippedMessage || rawMessage || 'Inactive');
        const summaryText = `${current}/${total || 0}`;
        $('#aot_counter_summary_'+wid).text(summaryText);
        $('#aot_counter_phase_'+wid).text(phaseLine);

        const $msg = $('#aot_counter_message_'+wid);
        if ($msg.length) {
          if (data.error) {
            $msg.text(window._(data.error)).addClass('text-danger');
          } else if (data.message) {
            $msg.text(window._(data.message)).removeClass('text-danger');
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
        if (!info.device || !info.channel) {
          alert(window._('Please select an Output first.'));
          return;
        }
        const run = parseInt($('#aot_counter_run_'+wid).val(), 10) || 0;
        const rest = parseInt($('#aot_counter_rest_'+wid).val(), 10) || 0;
        const cycles = parseInt($('#aot_counter_cycles_'+wid).val(), 10) || 0;
        if (run <= 0 || rest < 0 || cycles <= 0) {
          alert(window._('Please check the run/rest/cycle values.'));
          return;
        }
        const payload = { run_sec: run, rest_sec: rest, cycles: cycles };
        const $msg = $('#aot_counter_message_'+wid);
        const toggleEl = opts && opts.toggleEl ? opts.toggleEl : null;
        try {
          const res = await fetch((window.AoT_BASE_PATH || '') + `/output_cycle_start/${info.device}/${info.channel}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-CSRFToken': $('meta[name="csrf-token"]').attr('content')
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
            $msg.text(errText).addClass('text-danger');
            if (toggleEl) { toggleEl.prop('checked', false); }
          }
        } catch (err) {
          $msg.text(window._('Error during start')).addClass('text-danger');
          if (toggleEl) { toggleEl.prop('checked', false); }
        }
      }

      async function stop(wid, opts){
        const info = parseInfo(wid);
        if (!info.device || !info.channel) { return; }
        const $msg = $('#aot_counter_message_'+wid);
        const toggleEl = opts && opts.toggleEl ? opts.toggleEl : null;
        try {
          const res = await fetch((window.AoT_BASE_PATH || '') + `/output_cycle_stop/${info.device}/${info.channel}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json',
              'X-CSRFToken': $('meta[name="csrf-token"]').attr('content')
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
            $msg.text(errText).addClass('text-danger');
            if (toggleEl) { toggleEl.prop('checked', true); }
          }
        } catch (err) {
          $msg.text(window._('Error during stop')).addClass('text-danger');
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

      window.initAoTCounter = function(wid){
        fetchPresetValues(wid).finally(function(){
          schedule(wid);
        });
      };

      $(document)
        .off('change.aot_counter_toggle', '.aot-counter-toggle')
        .on('change.aot_counter_toggle', '.aot-counter-toggle', function(){
          const $el = $(this);
          const wid = $el.data('wid');
          if (!wid) { return; }
          if ($el.is(':checked')) {
            start(String(wid), { toggleEl: $el });
          } else {
            stop(String(wid), { toggleEl: $el });
          }
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
      initAoTCounter('{{each_widget.unique_id}}');
    {%- else -%}
      console.warn('[AoT Counter] Output not configured for widget {{each_widget.unique_id}}');
    {%- endif -%}
    """
}
