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
#  Last modified: 2025-10-11

import logging
import datetime
from flask import jsonify
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

from aot.utils.constraints_pass import constraints_pass_positive_value

# --- local validator: UTC offset must be within [-12.0, 14.0]
# returns (True, None) if ok, else (False, 'error message')
def constraints_pass_utc_offset(value):
    try:
        v = float(value)
    except Exception:
        return False, lazy_gettext('숫자여야 합니다.')
    if v < -12.0 or v > 14.0:
        return False, lazy_gettext('허용 범위는 -12.0 ~ +14.0 입니다.')
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
def output_last_session_public(device_unique_id, channel_id):
    try:
        data = _sess_read(device_unique_id, channel_id)
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

# ---- Public variant ----
def output_started_at_public(device_unique_id, channel_id):
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

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_timer',
    'widget_name': 'AoT 타이머',
    'widget_library': 'timer',
    'no_class': True,

    'message': (
        '시간입력창에 "시/분/초"를 입력하면 입력한 시간만큼 장치가 작동하고 꺼집니다.'
        '입력된 시간이 "0"이면 종료 전까지 연속 작동합니다.'
        '토글 스위치를 "ON"으로 하면 장치가 켜지고, "OFF"로 하면 장치가 꺼집니다.'
    ),

    'widget_width': 24,
    'widget_height': 7,

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('장치 설정')
        },
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'options_select': [
                'Output_Channels',
            ],
            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('제어할 Output 을 선택하세요.')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 5.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("동기화"), lazy_gettext("초")),
            'phrase': lazy_gettext('사용할 측정값의 최대 유효 시간')
        },
        {
            'type': 'header',
            'name': lazy_gettext('표시 설정')
        },
        {
            'id': 'enable_status',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('상태 표시'),
            'phrase': lazy_gettext('작동상태를 타이틀바에 표시 합니다.')
        },
        {
            'id': 'status_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('상태 크기'),
            'phrase': lazy_gettext('(em) 단위')
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('작동시간'),
            'phrase': lazy_gettext('작동시간을 표시 합니다.')
        },
        {
            'id': 'widget_name_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('작동시간 글자 크기'),
            'phrase': lazy_gettext('(em) 단위')
        },
        {
            'type': 'header',
            'name': lazy_gettext('시간 설정')
        },
        {
            'id': 'enable_output_controls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('타이머'),
            'phrase': lazy_gettext('타이머 기능을 활성화 합니다.')
        },
        {
            'id': 'font_em_time_input',
            'type': 'float',
            'default_value': 1.2,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('시간입력창 크기'),
            'phrase': lazy_gettext('(em) 단위')
        },
        {
            'id': 'tz_offset',
            'type': 'select',
            'default_value': '9.0',
            'options_select': [
                ('9.0', '서울 (UTC+9)'),
                ('8.0', '베이징 (UTC+8)'),
                ('7.0', '방콕 (UTC+7)'),
                ('6.0', '다카 (UTC+6)'),
                ('5.5', '뉴델리 (UTC+5:30)'),
                ('4.0', '두바이 (UTC+4)'),
                ('3.0', '리야드 (UTC+3)'),
                ('1.0', '베를린 (UTC+1)'),
                ('0.0', '런던 (UTC±0)'),
                ('-3.0', '부에노스아이레스 (UTC-3)'),
                ('-5.0', '뉴욕 (UTC-5)'),
                ('-6.0', '시카고 (UTC-6)'),
                ('-8.0', '로스앤젤레스 (UTC-8)'),
                ('-9.0', '앵커리지 (UTC-9)'),
                ('-10.0', '하와이 (UTC-10)')
            ],
            'name': lazy_gettext('시간대'),
            'phrase': lazy_gettext('도시를 선택하면 숫자 오프셋으로 적용됩니다.')
        }
    ],

    # ------------------ HEAD (CSS) ------------------
    'widget_dashboard_head': """<!-- No head content -->""",

    'endpoints': [
        ("/output_started_at/<device_unique_id>/<channel_id>", "output_started_at", output_started_at, ["GET"]),
        ("/output_started_at_public/<device_unique_id>/<channel_id>", "output_started_at_public", output_started_at_public, ["GET"]),

        ("/output_last_duration/<device_unique_id>/<channel_id>", "output_last_duration", output_last_duration, ["GET"]),
        ("/output_last_duration_public/<device_unique_id>/<channel_id>", "output_last_duration_public", output_last_duration_public, ["GET"]),
        ("/output_last_session_public/<device_unique_id>/<channel_id>", "output_last_session_public", output_last_session_public, ["GET"]),
        ("/output_last_session_set/<device_unique_id>/<channel_id>", "output_last_session_set", output_last_session_set, ["POST"]),
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
    {%- set wo = widget_options if widget_options is defined else {} -%}
    {%- set output = wo.get('output', '') -%}
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if output and ',' in output -%}
      {%- set device_id = output.split(',')[0] -%}
      {%- set channel_id = output.split(',')[1] -%}
    {%- endif -%}

    {%- set effective_offset = (widget_options.get('tz_offset', '9.0')) -%}

    <!-- 최상위 컨테이너: aot_tm_{{unique_id}} -->
    <div class="frame-aot" id="aot_tm_{{each_widget.unique_id}}" data-controls-enabled="{{ 'true' if widget_options['enable_output_controls'] else 'false' }}" data-offset="{{ effective_offset }}">

      <!-- 첫 번째 행 -->
      <div class="row-aot-1">
        <!-- Timestamp 표시 (왼쪽) -->
        <div class="col-aot-1">
          <span id="tm_timestamp_{{each_widget.unique_id}}" class="prt-text" style="font-size: {{widget_options['widget_name_font_em']}}em;">
            <!-- 여기 타이머 경과시간 등 표시 -->
          </span>
        </div>

        <!-- 토글 스위치 (오른쪽) -->
        <div class="col-aot-2">
          <label class="btn-toggle">
            <input type="checkbox" 
                  id="tm_tog_{{each_widget.unique_id}}"
                  class="timer-toggle-input btn-toggle-input"
                  name="{{device_id}}/{{channel_id}}">
            <span class="btn-toggle-slider">
              <span class="btn-toggle-thumb"></span>
            </span>
          </label>
        </div>
      </div>

      {% if widget_options['enable_output_controls'] %}
      <!-- 두 번째 행 -->
      <div class="row-aot-2">
        <!-- 시간 입력 영역 -->
        <div class="input-time">
          <input type="number" min="0" max="48"
                id="tm_hh_{{each_widget.unique_id}}"
                class="input-time-hh"
                value="0">
          <input type="number" min="0" max="59"
                id="tm_mm_{{each_widget.unique_id}}"
                class="input-time-mm"
                value="0">
          <input type="number" min="0" max="59"
                id="tm_ss_{{each_widget.unique_id}}"
                class="input-time-ss"
                value="0">
        </div>

        <!-- 버튼 영역 -->
        <div class="btn-time">
          <input id="tm_reset_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="재설정">
          <input id="tm_plus5_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="5분">
          <input id="tm_plus10_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="10분">
        </div>
      </div>
      {% endif %}
    </div>
    """,

    # ------------------ JAVASCRIPT ------------------
    'widget_dashboard_js': """
    // TIME DISPLAY RULES (2025-10 rev):
    // ---- Central time helpers (single source of truth) ----
    function tm_nowMs(){ return Date.now(); } // System/browser clock
    function tm_toDate(ms){ return new Date(ms); }
    // Read numeric UTC offset (hours) from data-offset; fallback 9.0
    function tm_getOffsetHours(widget_id){
      try{
        const $frame = $('#aot_tm_'+widget_id);
        const raw = ($frame.attr('data-offset') || '').trim();
        // Accept comma decimal or weird spacing
        const norm = raw.replace(',', '.');
        let v = parseFloat(norm);
        if (!Number.isFinite(v)) throw new Error('NaN');
        // Clamp to sane range [-12, 14]
        if (v < -12) v = -12;
        if (v > 14) v = 14;
        return v;
      }catch(e){
        return 9.0;
      }
    }
    // ---- Server clock offset (server_now_ms - client_now_ms) ----
    let tm_serverNowOffsetMs = 0;
    function tm_updateServerNowOffsetFromResponse(res)
    {
      try{
        const dateHdr = res.headers.get('date');
        if(!dateHdr) return;
        const srvMs = Date.parse(dateHdr);
        if(!isNaN(srvMs)){
          const off = srvMs - Date.now();
          // Only accept small drift (±120s); ignore absurd offsets (e.g., server sends local time as GMT)
          if (Math.abs(off) <= 120000) {
            tm_serverNowOffsetMs = off;
            if(window.AoT_DEBUG_TIMER){ console.debug('AoT Timer: server-now offset(ms)=', tm_serverNowOffsetMs); }
          } else {
            // ignore
            if(window.AoT_DEBUG_TIMER){ console.warn('AoT Timer: ignoring absurd server offset(ms)=', off); }
            tm_serverNowOffsetMs = 0;
          }
        }
      }catch(e){}
    }
    // ---- Safe server-now helpers (guard against misconfigured Date header) ----
    function tm_safeOffsetMs(){
      const off = tm_serverNowOffsetMs || 0;
      // clamp to ±120s; if outside, treat as 0 to avoid +9h jumps
      return (Math.abs(off) <= 120000) ? off : 0;
    }
    function tm_nowServerMs(){
      return tm_nowMs() + tm_safeOffsetMs();
    }

    // ---- Stable text setter to prevent flicker ----
    const EPOCH_2000_MS = 946684800000; // guard for invalid 1970 timestamps
    let tm_lastRenderedText = {}; // wid -> last text
    function tm_setTextStable(widget_id, text){
      const $el = $('#tm_timestamp_'+widget_id);
      if (!$el.length) return;
      const t = String(text);
      if (tm_lastRenderedText[widget_id] === t) return; // no repaint
      tm_lastRenderedText[widget_id] = t;
      $el.text(t);
    }
    // 1) No input-duration caching (localStorage) — removed.
    // 2) Timestamps are rendered in browser-local time via JS Date (no server TZ conversion).
    // 3) Elapsed time increases only while server-reported state is ON and a valid server start-time exists.
    // 4) OFF state shows "00:00:00" (no ticking). All other server fetches (e.g., start-time) run only on refresh_seconds cadence.
    function modOutputOutput_tm(cmdStr, widget_id) {
      $.ajax({
        type: 'GET',
        url: '/output_mod/' + cmdStr,
        success: function(data) {
          getGPIOStateOutput_tm(widget_id);
        },
        error: function(jqXHR, textStatus, errorThrown) {
          console.log("modOutputOutput_tm error:", errorThrown);
        }
      });
    }

    function getGPIOStateOutput_tm(widget_id) {
      // 토글(checkbox) 찾기
      const $chk = $('#tm_tog_'+widget_id);
      if (!$chk.length) return;

      const devName = $chk.attr('name');
      if (!devName || devName.indexOf('/') === -1) {
        // Unbound widget: stop all timers and show stable zeros to avoid bogus 09:00:xx
        tm_clearStartBases(widget_id);
        tm_stopCountdown(widget_id);
        tm_stopTimestamp(widget_id, false);
        tm_setTextStable(widget_id, '00:00:00');
        console.debug('[AoT Timer] name missing or invalid for wid', widget_id);
        return;
      }
      const parts = devName.split('/');
      const dev_id = parts[0];
      const ch_id  = parts[1];
      if (!dev_id || !ch_id) {
        tm_clearStartBases(widget_id);
        tm_stopCountdown(widget_id);
        tm_stopTimestamp(widget_id, false);
        tm_setTextStable(widget_id, '00:00:00');
        console.debug('[AoT Timer] device_id/channel_id missing for wid', widget_id);
        return;
      }

      // 최상위 컨테이너 (배경색 변경용) — 옵션과 무관하게 전체 프레임에 적용
      const $frame = $('#aot_tm_'+widget_id);

      // 상태표시용 span
      const $txt = $('#tm_state_'+widget_id);

      // Ajax로 상태 읽어오기
      $.getJSON('/outputstate_unique_id/' + dev_id + '/' + ch_id, function(state) {

        if (state === 'off') {
          $chk.prop('checked', false);
          $frame.removeClass('active-background pause-background')
                .addClass('inactive-background');
          tm_lockInputs(widget_id, false);
          if ($txt.length) $txt.text('(Inactive)');

          // Restore previously frozen OFF display immediately to avoid brief disappearance
          if (typeof tm_offFrozenText[widget_id] === 'string' && tm_offFrozenText[widget_id].length > 0) {
            tm_setTextStable(widget_id, tm_offFrozenText[widget_id]);
          }

          // If we still have no frozen display, seed from local cache to avoid one-frame disappearance
          if (!(typeof tm_offFrozenText[widget_id] === 'string' && tm_offFrozenText[widget_id].length > 0)
              && typeof tm_frozenElapsedSec[widget_id] !== 'number') {
            tm_renderFromLastSession(widget_id); // uses localStorage {start_ms, elapsed_sec}
            if (typeof tm_lastRenderedText[widget_id] === 'string' && tm_lastRenderedText[widget_id].length > 0) {
              tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];
            }
          }

          tm_stopCountdown(widget_id);
          tm_stopTimestamp(widget_id, false);
          // Safety: ensure no interval is ticking
          if (tm_timestampInterval[widget_id]) {
            clearInterval(tm_timestampInterval[widget_id]);
            tm_timestampInterval[widget_id] = null;
          }
          // ---- Cross-browser last-session cache: freeze elapsed, persist on ON→OFF ----
          const hadBase = (typeof tm_timestampStartSec[widget_id] !== 'undefined');
          const justTurnedOff = (tm_prevState[widget_id] === 'on');

          if (hadBase && justTurnedOff) {
            // 1) ON→OFF 전환 시점에만 경과를 확정하고 저장 (서버 시계 오프셋 반영)
            const nowMs = tm_nowServerMs();
            const startMs = tm_timestampStartDate[widget_id].getTime();
            const elapsed = Math.max(0, Math.floor((nowMs - startMs)/1000));
            tm_frozenElapsedSec[widget_id] = elapsed; // 이후 OFF 주기에는 이 값을 그대로 표시
            const elapsedStr = tm_formatHMS(elapsed);
            let startedStr = '';
            try { startedStr = tm_formatMD_HMS(tm_timestampStartDate[widget_id], widget_id) || ''; } catch(e) { startedStr=''; }
            tm_setTextStable(widget_id, elapsedStr + (startedStr ? ", " + startedStr : ''));
            tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];

            // 서버에도 1회 저장 (교차 브라우저용)
            (async function(){
              try{
                await tm_saveLastSessionServer(widget_id, dev_id, ch_id,
                  Math.floor(startMs), nowMs, elapsed);
              }catch(e){}
            })();
            // Also persist locally for instant restore on refresh
            tm_storeLastSession(widget_id, Math.floor(startMs), elapsed);

          } else if (typeof tm_frozenElapsedSec[widget_id] === 'number') {
            // 2) 이미 OFF 상태이고 고정 경과값이 있으면, 그 값을 그대로 표시 (증가 금지)
            const elapsedStr = tm_formatHMS(tm_frozenElapsedSec[widget_id]);
            const dOff = tm_getOffStartDate(widget_id);
            const startedStr = dOff ? tm_formatMD_HMS(dOff, widget_id) : '';
            tm_setTextStable(widget_id, elapsedStr + (startedStr ? ", " + startedStr : ''));
          tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];

          } else {
            // 3) 베이스가 없고 고정값도 없으면: 서버 캐시 1회 조회 후 고정 표시
            //    실패 시에는 기존 표시를 유지하고, 아무 표시가 없을 때만 00:00:00로 초기화
            (async function(){
              const hadDisplay = (typeof tm_lastRenderedText[widget_id] === 'string' && tm_lastRenderedText[widget_id].length > 0);
              try{
                const js = await tm_fetchLastSessionServer(dev_id, ch_id);
                if (js && typeof js.elapsed_sec==='number'){
                  tm_frozenElapsedSec[widget_id] = Math.max(0, Math.floor(js.elapsed_sec));
                  const d = (typeof js.start_ms==='number') ? tm_toDate(js.start_ms) : null;
                  const startedStr = d ? tm_formatMD_HMS(d, widget_id) : '';
                  const elapsedStr = tm_formatHMS(tm_frozenElapsedSec[widget_id]);
                  tm_setTextStable(widget_id, elapsedStr + (startedStr? ", "+startedStr: ''));
                  tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];
                  // Mirror server last-session into local cache for immediate reuse on next load
                  if (typeof js.start_ms === 'number' && typeof js.elapsed_sec === 'number') {
                    tm_storeLastSession(widget_id, Math.floor(js.start_ms), Math.max(0, Math.floor(js.elapsed_sec)));
                  }
                } else if (!hadDisplay) {
                  // 표시가 전혀 없는 경우에만 기본값 출력 (+ 가능한 경우 시작시간 포함)
                  const dOff = tm_getOffStartDate(widget_id);
                  const startedStr = dOff ? tm_formatMD_HMS(dOff, widget_id) : '';
                  tm_setTextStable(widget_id, '00:00:00' + (startedStr? ", "+startedStr: ''));
                  tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];
                }
              }catch(e){
                if (!hadDisplay) {
                  const dOff = tm_getOffStartDate(widget_id);
                  const startedStr = dOff ? tm_formatMD_HMS(dOff, widget_id) : '';
                  tm_setTextStable(widget_id, '00:00:00' + (startedStr? ", "+startedStr: ''));
                  tm_offFrozenText[widget_id] = tm_lastRenderedText[widget_id];
                }
              }
            })();
          }

          // clear stale bases so 다음 ON 주기에서 새 시작 시각을 강제로 동기화
          tm_clearStartBases(widget_id);

          tm_prevState[widget_id] = 'off';
          console.debug("AoT Timer: state=off; duration-based frozen display.");

        } else if (state === 'on') {
          const was = tm_prevState[widget_id];
          tm_prevState[widget_id] = 'on';
          // Clear OFF display cache on ON transition so live timer can render
          delete tm_offFrozenText[widget_id];
          if (was !== 'on') {
            // Transition OFF→ON:
            // If we already have a provisional/local base (e.g., user just toggled ON), keep it.
            // Otherwise, clear stale bases to force server re-sync.
            const hasLocalBase = (tm_timestampStartDate[widget_id] instanceof Date) && (typeof tm_timestampStartSec[widget_id] === 'number');
            if (!hasLocalBase) {
              tm_clearStartBases(widget_id);
            }
            delete tm_frozenElapsedSec[widget_id];
          }
          $chk.prop('checked', true);
          $frame.removeClass('inactive-background pause-background')
                .addClass('active-background');
          tm_lockInputs(widget_id, true);
          if ($txt.length) $txt.text('(Active)');
          // If we don't have a valid start base yet, wait for server start timestamp (no provisional local base)
          if (typeof tm_timestampStartSec[widget_id] === 'undefined' || typeof tm_timestampStartDate[widget_id] === 'undefined') {
            // No valid base yet; show a short syncing hint and immediately fetch server start-time once.
            if (tm_lastRenderedText[widget_id] !== '동기화 중…') tm_setTextStable(widget_id, '동기화 중…');
            (async function(){
              const devName = $chk.attr('name');
              const dev_id = devName ? devName.split('/')[0] : null;
              const ch_id  = devName ? devName.split('/')[1] : null;
              if (!dev_id || !ch_id) return;
              try { await tm_maybeSyncServerStart(widget_id, dev_id, ch_id); } catch(e) {}
            })();
            return;
          }

          // Base exists; still allow light sync in background (no flicker due to ±120s guard)
          (async function(){
            const devName = $chk.attr('name');
            const dev_id = devName ? devName.split('/')[0] : null;
            const ch_id  = devName ? devName.split('/')[1] : null;
            if (!dev_id || !ch_id) return;
            try { await tm_maybeSyncServerStart(widget_id, dev_id, ch_id); } catch(e) {}
          })();

        } else {
          // UI 변경 없이 오류 로그만 남깁니다.
          console.error("AoT Timer: No connection for widget:", widget_id);
        }
      });
    }

        // --- Per-widget server-start status flags ---
        let tm_serverStartKnown = {};   // wid -> boolean
        let tm_lastServerTsMs   = {};   // wid -> number (ms)
        let tm_baseSetAtMs      = {}; // wid -> ms (when tm_setTimestampBase last ran)
        // ---- Server-side Start-Time Sync Helpers ----
        async function tm_fetchServerStartTime(dev_id, ch_id, widget_id) {
          const BASE = (window.AoT_BASE_PATH || '');

          async function fetchStart(url) {
            console.debug("AoT Timer: trying start-time endpoint", url);
            try {
              const res = await fetch(url, { method: 'GET', headers: { 'Accept': 'application/json' } });
              tm_updateServerNowOffsetFromResponse(res);

              // 401/403: 인증 이슈 → 상위에서 private로 폴백할지 판단
              if (res.status === 401 || res.status === 403) {
                return { kind: 'auth_needed' };
              }

              // 204: 내용 없음 → JSON 파싱 시도 금지
              if (res.status === 204) {
                console.debug("AoT Timer: start-time 204 No Content from", url);
                return { kind: 'none' };
              }

              if (!res.ok) {
                console.debug("AoT Timer: start-time non-OK status", res.status, "from", url);
                return { kind: 'none' };
              }

              const ctype = (res.headers.get('content-type') || '').toLowerCase();
              if (!ctype.includes('application/json')) {
                const txt = await res.text(); // 디버그용
                console.debug("AoT Timer: start-time non-JSON body from", url, "len=", (txt || '').length);
                return { kind: 'none' };
              }

              let data = null;
              try { data = await res.json(); } catch (e) {
                console.debug("AoT Timer: start-time JSON parse error from", url);
                return { kind: 'none' };
              }

              const ts = tm_extractTimestampFromResponse(data, widget_id);
              if (ts) return { kind: 'ts', ts };
              return { kind: 'none' };
            } catch (e) {
              console.debug("AoT Timer: start-time fetch error for", url, e);
              return { kind: 'none' };
            }
          }

          const prefixes = [];
          if (BASE) prefixes.push(BASE);
          prefixes.push("");

          // Try endpoints in order: public then (if auth needed) private, across prefixes
          for (const pre of prefixes) {
            const pubUrl = `${pre}/output_started_at_public/${dev_id}/${ch_id}`;
            const pubRes = await fetchStart(pubUrl);
            if (pubRes.kind === 'ts') return pubRes.ts;
            if (pubRes.kind === 'auth_needed') {
              const prvUrl = `${pre}/output_started_at/${dev_id}/${ch_id}`;
              const prvRes = await fetchStart(prvUrl);
              if (prvRes.kind === 'ts') return prvRes.ts;
            }
            // kind 'none' 또는 기타 → 다음 prefix 시도
          }

          return null;
        }
        // Ensure newest implementation overrides legacy globals
        window.tm_fetchServerStartTime = tm_fetchServerStartTime;


        function tm_extractTimestampFromResponse(data, widget_id) {
          if (!data || typeof data !== 'object') return null;

          function normEpochMs(v){
            if (typeof v !== 'number' || !isFinite(v)) return null;
            return (v >= 1e12) ? Math.floor(v) : Math.floor(v * 1000);
          }

          const ms_from_epoch = normEpochMs(data.started_at_epoch);
          const ms_from_started_ms = normEpochMs(data.started_at_ms);
          const ms_from_point_ts = normEpochMs(data.point_ts_epoch);

          let epochMs = ms_from_epoch || ms_from_started_ms || null;

          // If point_ts is present and differs by ~6–12h, prefer point_ts (sanitize locally-encoded epochs)
          if (epochMs && ms_from_point_ts) {
            const diff = Math.abs(epochMs - ms_from_point_ts);
            const LOWER = (6*3600*1000) - (15*60*1000);
            const UPPER = (12*3600*1000) + (15*60*1000);
            if (diff >= LOWER && diff <= UPPER) {
              epochMs = ms_from_point_ts;
            }
          }

          if (epochMs && epochMs >= EPOCH_2000_MS) return epochMs;

          if (typeof data.started_at_iso === 'string') {
            const t = Date.parse(data.started_at_iso);
            if (!isNaN(t) && t >= EPOCH_2000_MS) return t;
          }

          if (data.meta && (data.meta.started_at_epoch || data.meta.started_at_ms || data.meta.started_at_iso || data.meta.point_ts_epoch)) {
            return tm_extractTimestampFromResponse(data.meta, widget_id);
          }
          return null;
        }

    // Start immediately on user-initiated ON: use local UTC-now as provisional base
    function tm_setLocalStartBase(widget_id){
      const nowMs = tm_nowServerMs();
      const d = tm_toDate(nowMs);                   // UTC Date
      tm_timestampStartDate[widget_id] = d;
      tm_timestampStartSec[widget_id]  = Math.floor(nowMs/1000);
      tm_startedUtcMs[widget_id]       = Math.floor(nowMs); // cache UTC only
      // Start ticking immediately at 00:00:00
      if (!tm_timestampInterval[widget_id]){
        tm_timestampInterval[widget_id] = setInterval(function(){ tm_updateTimestamp(widget_id); }, 1000);
      }
      // Render immediately using TZ only for formatting
      const startedStr = tm_formatMD_HMS(d, widget_id) || '';
      tm_setTextStable(widget_id, '00:00:00' + (startedStr ? ", " + startedStr : ''));
    }

    // CONTRACT: startMs must be UTC epoch (ms). Timezone offsets are applied only when formatting labels.
    function tm_setTimestampBase(widget_id, startMs) {
      // NOTE: startMs is treated as a UTC epoch from the server; no timezone heuristics are applied.
      // NOTE: Do not perform any timezone/drift compensation here. Server provides UTC epoch; we format to Asia/Seoul only at render time.
      if (!(Number.isFinite(startMs)) || startMs < EPOCH_2000_MS) {
        console.debug('AoT Timer: ignored invalid server start ms', startMs);
        return;
      }
      if (startMs < 1e12) {
        console.debug('AoT Timer: startMs appears in seconds; normalizing to ms', startMs);
        startMs = Math.floor(startMs * 1000);
      }
      // If we already have a provisional/local base, only rebase when the server differs by >120s
      if (tm_timestampStartDate[widget_id] instanceof Date) {
        const existing = tm_timestampStartDate[widget_id].getTime();
        const DIFF = Math.abs(startMs - existing);
        if (DIFF <= 120000) {
          // Keep current base to avoid flicker and label disappearing
          if (window.AoT_DEBUG_TIMER) {
            console.debug('AoT Timer: keeping existing base; server within 120s', { wid: widget_id, existing, server: startMs });
          }
          // Mark that server start is known so we don't keep fetching
          tm_serverStartKnown[widget_id] = true;
          tm_lastServerTsMs[widget_id]   = Math.floor(startMs);
          return;
        }
      }
      const d = tm_toDate(startMs);
      tm_timestampStartDate[widget_id] = d;                 // UTC Date
      tm_startedUtcMs[widget_id]       = Math.floor(startMs); // cache UTC only
      tm_timestampStartSec[widget_id]  = Math.floor(startMs / 1000);
      tm_lastServerTsMs[widget_id]     = Math.floor(startMs);
      tm_serverStartKnown[widget_id]   = true;
      tm_baseSetAtMs[widget_id] = tm_nowMs();
      console.debug('AoT Timer: base set', {
        startMs,
        startISO: new Date(startMs).toISOString(),
        startSec: tm_timestampStartSec[widget_id]
      });
      if (window.AoT_DEBUG_TIMER) {
        console.debug('AoT Timer: baseSetAtMs', { wid: widget_id, baseSetAtMs: tm_baseSetAtMs[widget_id] });
      }
      tm_stopTimestamp(widget_id, false);
      tm_updateTimestamp(widget_id);
      const $chk = $('#tm_tog_'+widget_id);
      if ($chk.length && $chk.is(':checked')) {
        if (!tm_timestampInterval[widget_id]) {
          tm_timestampInterval[widget_id] = setInterval(function(){ tm_updateTimestamp(widget_id); }, 1000);
        }
      } else {
        if (tm_timestampInterval[widget_id]) {
          clearInterval(tm_timestampInterval[widget_id]);
          tm_timestampInterval[widget_id] = null;
        }
      }
    }

        async function tm_maybeSyncServerStart(widget_id, dev_id, ch_id) {
          try {
            // If we already have a server-certified base for this ON session, do not rebase.
            if (tm_serverStartKnown[widget_id]) return;

            const ts = await tm_fetchServerStartTime(dev_id, ch_id, widget_id);
            if (!ts) return; // 204/none

            // Adopt server start time unconditionally on first acquisition for this session.
            tm_setTimestampBase(widget_id, ts);
          } catch (e) { /* ignore */ }
        }

    // ---- Last-session server cache helpers ----
    async function tm_saveLastSessionServer(widget_id, dev_id, ch_id, startMs, stopMs, elapsedSec){
      try{
        const res = await fetch(`/output_last_session_set/${dev_id}/${ch_id}`, {
          method: 'POST', headers: { 'Content-Type':'application/json', 'Accept':'application/json' },
          body: JSON.stringify({ widget_id: String(widget_id||''), start_ms: Math.floor(startMs), stop_ms: Math.floor(stopMs), elapsed_sec: Math.max(0, Math.floor(elapsedSec||0)) })
        });
        return res.ok;
      }catch(e){ return false; }
    }
    async function tm_fetchLastSessionServer(dev_id, ch_id){
      try{
        const res = await fetch(`/output_last_session_public/${dev_id}/${ch_id}`, { headers: { 'Accept':'application/json' } });
        if(!res.ok) return null;
        const js = await res.json();
        return js && typeof js==='object' ? js : null;
      }catch(e){ return null; }
    }

    // --- Per-widget UI state (to detect OFF→ON transitions) ---
    let tm_prevState = {};        // wid -> 'on' | 'off' | undefined

    // Helper: clear known server start and local bases
    function tm_clearStartBases(widget_id) {
      tm_serverStartKnown[widget_id] = false;
      tm_lastServerTsMs[widget_id]   = undefined;
      tm_timestampStartSec[widget_id]= undefined;
      tm_timestampStartDate[widget_id]= undefined;
      tm_baseSetAtMs[widget_id] = 0; // reset cooldown so next ON fetches immediately
      // Do not clear display to avoid flicker; ticking will restart when a new base arrives
      tm_stopTimestamp(widget_id, false);
      tm_baseCorrectedOnce[widget_id] = false;
      tm_startedUtcMs[widget_id] = undefined;
    }

    // 자동 갱신
    function tm_initAutoRefresh(widget_id, refreshSec) {
      if (!refreshSec || refreshSec <= 0) { return; }

      // Ensure per-widget cadence state
      if (typeof window._tm_refreshTick === 'undefined') window._tm_refreshTick = {};

      window._tm_refreshTick[widget_id] = setInterval(async function(){
        // Always poll on/off state on the configured cadence
        getGPIOStateOutput_tm(widget_id);

        // Only try to sync server start-time if ON
        const $chkOn = $('#tm_tog_'+widget_id);
        if ($chkOn.length && $chkOn.is(':checked')) {
          const devName = $chkOn.attr('name');
          if (!devName) return;
          const dev_id = devName.split('/')[0];
          const ch_id  = devName.split('/')[1];
          await tm_maybeSyncServerStart(widget_id, dev_id, ch_id);
        }
      }, refreshSec * 1000);
    }

    // 카운트다운 로직
    let tm_countdown = {};
    let tm_currentSec = {};

    function tm_getInputSec(widget_id){
      let hh = parseInt($('#tm_hh_'+widget_id).val()) || 0;
      let mm = parseInt($('#tm_mm_'+widget_id).val()) || 0;
      let ss = parseInt($('#tm_ss_'+widget_id).val()) || 0;
      if(hh>48) hh=48;
      if(mm>59) mm=59;
      if(ss>59) ss=59;
      return (hh*3600 + mm*60 + ss);
    }

    function tm_applyInputSec(widget_id, totalSec){
      if(totalSec<0) totalSec=0;
      let hh = Math.floor(totalSec/3600);
      let mm = Math.floor((totalSec%3600)/60);
      let ss = totalSec % 60;
      $('#tm_hh_'+widget_id).val(hh);
      $('#tm_mm_'+widget_id).val(mm);
      $('#tm_ss_'+widget_id).val(ss);
    }

    function tm_startCountdown(widget_id){
      if(tm_countdown[widget_id]) return; // 이미 동작 중이면 무시

      const totalSec = tm_getInputSec(widget_id);
      tm_currentSec[widget_id] = totalSec;

      // When a timer starts (ON with duration), reset last-session elapsed to 0 at now
      const nowMs_for_timer = tm_nowMs();
      tm_storeLastSession(widget_id, nowMs_for_timer, 0);

      tm_lockInputs(widget_id, true);

      if(totalSec <= 0){
        // 0초면 무기한
        return;
      }

      tm_countdown[widget_id] = setInterval(function(){
        if(tm_currentSec[widget_id] > 0){
          tm_currentSec[widget_id]--;
        }
        tm_applyInputSec(widget_id, tm_currentSec[widget_id]);

        if(tm_currentSec[widget_id] <= 0){
          clearInterval(tm_countdown[widget_id]);
          tm_countdown[widget_id] = null;

          // 서버 OFF
          let baseName = $('#tm_tog_'+widget_id).attr('name');
          if(baseName){
            let dev_id= baseName.split('/')[0];
            let ch_id= baseName.split('/')[1];
            let cmd= dev_id+'/'+ch_id+'/off/sec/0';
            modOutputOutput_tm(cmd, widget_id);
          }
        }
      }, 1000);
    }

    function tm_stopCountdown(widget_id){
      if(tm_countdown[widget_id]){
        clearInterval(tm_countdown[widget_id]);
        tm_countdown[widget_id] = null;
      }
      tm_lockInputs(widget_id, false);
    }

    function tm_lockInputs(widget_id, isLock){
      $('#tm_hh_'+widget_id).prop('readOnly', isLock);
      $('#tm_mm_'+widget_id).prop('readOnly', isLock);
      $('#tm_ss_'+widget_id).prop('readOnly', isLock);
      $('#tm_reset_'+widget_id).prop('disabled', isLock);
      $('#tm_plus5_'+widget_id).prop('disabled', isLock);
      $('#tm_plus10_'+widget_id).prop('disabled', isLock);
    }

    // 타임스탬프 로직
    let tm_timestampInterval = {};
    let tm_timestampStartSec = {};
    let tm_timestampStartDate = {};
    // OFF 상태에서 재표시 시 증가를 막기 위한 고정 경과시간(초)
    let tm_frozenElapsedSec = {}; // wid -> number(sec)
    // Cache the last valid rendered start-time label per widget (prevents occasional disappearance)
    let tm_startedUtcMs = {}; // wid -> number (ms)
     // Per-widget: whether initial timezone correction was applied for this ON session
    let tm_baseCorrectedOnce = {}; // wid -> boolean
    let tm_offFrozenText = {}; // wid -> string

    function tm_stopTimestamp(widget_id, clearDisplay=true){
      if(tm_timestampInterval[widget_id]){
        clearInterval(tm_timestampInterval[widget_id]);
        tm_timestampInterval[widget_id] = null;
      }
      if(clearDisplay){
        $('#tm_timestamp_'+widget_id).text('');
      }
    }

    function tm_startTimestamp(widget_id){
      // Deprecated: timestamp now starts only when server provides a start time.
      if (tm_timestampInterval[widget_id]) return;
      // Do nothing here. tm_setTimestampBase() will be called when server start-time is known
      // and will start ticking only if the device is ON.
    }

    function tm_updateTimestamp(widget_id){
      // Update only when we have a valid base AND the device is ON
      const $chk = $('#tm_tog_'+widget_id);
      if (!$chk.length || !$chk.is(':checked')) return;
      if (typeof tm_timestampStartSec[widget_id] === 'undefined' || typeof tm_timestampStartDate[widget_id] === 'undefined') {
        // No valid base yet; avoid provisional 00:00:00 and show a short syncing hint once.
        if (tm_lastRenderedText[widget_id] !== '동기화 중…') tm_setTextStable(widget_id, '동기화 중…');
        return;
      }
      const nowMs = tm_nowServerMs();
      const startMs = tm_timestampStartDate[widget_id].getTime();
      const elapsed = Math.max(0, Math.floor((nowMs - startMs)/1000));
      // DEBUG: numeric sanity (can be removed once stable)
      if (window.AoT_DEBUG_TIMER) {
        console.debug('AoT Timer DEBUG', {
          nowMs: nowMs,
          startMs: startMs,
          diffMs: nowMs - startMs,
          elapsed_s: elapsed,
          start_iso: tm_timestampStartDate[widget_id] ? tm_timestampStartDate[widget_id].toISOString() : null
        });
      }
      const elapsedStr = tm_formatHMS(elapsed);
      let startedStr = '';
      try { startedStr = tm_formatMD_HMS(tm_timestampStartDate[widget_id], widget_id) || ''; } catch(e) { startedStr = ''; }
      tm_setTextStable(widget_id, elapsedStr + (startedStr ? ", " + startedStr : ''));
    }

    function tm_formatHMS(sec){
      if(sec<0) sec=0;
      const hh= Math.floor(sec/3600);
      const mm= Math.floor((sec%3600)/60);
      const ss= sec%60;
      return String(hh).padStart(2,'0') + ":" +
             String(mm).padStart(2,'0') + ":" +
             String(ss).padStart(2,'0');
    }
    function tm_formatMD_HMS(d, widget_id){
      // Render the timestamp using the widget-selected timezone offset (tz_offset)
      // We shift the underlying UTC epoch by offset hours, then read UTC fields to format.
      try{
        const offH = tm_getOffsetHours(widget_id); // e.g., +9.0 for Seoul
        const shifted = new Date(d.getTime() + Math.round(offH * 3600 * 1000));
        const M = String(shifted.getUTCMonth() + 1).padStart(2, '0');
        const D = String(shifted.getUTCDate()).padStart(2, '0');
        const h = String(shifted.getUTCHours()).padStart(2, '0');
        const m = String(shifted.getUTCMinutes()).padStart(2, '0');
        const s = String(shifted.getUTCSeconds()).padStart(2, '0');
        return `${M}월 ${D}일 ${h}:${m}:${s}`;
      }catch(e){
        return '';
      }
    }
    // ---- Input cache (persist across reloads) ----
    // (Removed: no input-duration caching)

    // ---- Last session cache (persist last start time and elapsed at stop) ----
    function tm_lastSessKey(widget_id) { return 'aot_tm_last_'+widget_id; }

    function tm_storeLastSession(widget_id, startMs, elapsedSec) {
      try {
        const payload = { start_ms: (typeof startMs==='number'? Math.floor(startMs): null),
                          elapsed_sec: (typeof elapsedSec==='number'? Math.max(0, Math.floor(elapsedSec)): null) };
        localStorage.setItem(tm_lastSessKey(widget_id), JSON.stringify(payload));
      } catch(e) { /* ignore */ }
    }
    
    // Resolve a start-time Date for OFF display: prefer in-memory base first, else localStorage cache
    function tm_getOffStartDate(widget_id){
      try{
        if (tm_timestampStartDate[widget_id] instanceof Date) return tm_timestampStartDate[widget_id];
        const sess = tm_loadLastSession(widget_id);
        if (sess && typeof sess.start_ms === 'number' && sess.start_ms >= EPOCH_2000_MS) {
          return new Date(Math.floor(sess.start_ms));
        }
      }catch(e){}
      return null;
    }

    function tm_loadLastSession(widget_id) {
      try {
        const raw = localStorage.getItem(tm_lastSessKey(widget_id));
        if (!raw) return null;
        const obj = JSON.parse(raw);
        if (!obj || (typeof obj !== 'object')) return null;
        if (typeof obj.start_ms !== 'number') return null;
        const startMs = Math.floor(obj.start_ms);
        const elapsed = (typeof obj.elapsed_sec === 'number') ? Math.max(0, Math.floor(obj.elapsed_sec)) : null;
        return { start_ms: startMs, elapsed_sec: elapsed };
      } catch(e) { return null; }
    }

    function tm_renderFromLastSession(widget_id) {
      const sess = tm_loadLastSession(widget_id);
      if (!sess) { tm_setTextStable(widget_id, '00:00:00'); return; }
      const d = tm_toDate(sess.start_ms);
      let startedStr = '';
      try { startedStr = tm_formatMD_HMS(d, widget_id) || ''; } catch(e) { startedStr = ''; }
      const elapsedStr = tm_formatHMS((typeof sess.elapsed_sec==='number')? sess.elapsed_sec: 0);
      tm_setTextStable(widget_id, elapsedStr + (startedStr ? ", " + startedStr : ''));
    }
    // Resume countdown based on (cached total) - (elapsed since start)
    function tm_resumeCountdownFromCache(widget_id){
      // Input-duration caching and resume logic removed.
    }

    // --- Event bindings: time buttons (delegated) ---
    // Reset
    $(document)
      .off('click.aot_timer_reset', 'input[id^="tm_reset_"]')
      .on('click.aot_timer_reset', 'input[id^="tm_reset_"]', function(){
        const wid = this.id.replace('tm_reset_','');
        tm_applyInputSec(wid, 0);
      });

    // +5 minutes
    $(document)
      .off('click.aot_timer_plus5', 'input[id^="tm_plus5_"]')
      .on('click.aot_timer_plus5', 'input[id^="tm_plus5_"]', function(){
        const wid = this.id.replace('tm_plus5_','');
        const cur = tm_getInputSec(wid);
        const capped = Math.min(48*3600, cur + 5*60);
        tm_applyInputSec(wid, capped);
      });

    // +10 minutes
    $(document)
      .off('click.aot_timer_plus10', 'input[id^="tm_plus10_"]')
      .on('click.aot_timer_plus10', 'input[id^="tm_plus10_"]', function(){
        const wid = this.id.replace('tm_plus10_','');
        const cur = tm_getInputSec(wid);
        const capped = Math.min(48*3600, cur + 10*60);
        tm_applyInputSec(wid, capped);
      });

    // --- Event bindings: toggle ON/OFF (delegated) ---
    // 위임 바인딩으로 위젯이 동적으로 생성/교체되어도 안정 동작
    $(document)
      .off('change.aot_timer', 'input.timer-toggle-input')
      .on('change.aot_timer', 'input.timer-toggle-input', function(){
        const wid   = this.id.replace('tm_tog_','');
        const isOn  = $(this).is(':checked');
        const devNm = $(this).attr('name');
        if (!devNm) return;

        const dev_id = devNm.split('/')[0];
        const ch_id  = devNm.split('/')[1];

        const totalSec = tm_getInputSec(wid);

        if (isOn) {
          // ON: duration 0이면 무기한(on/sec/0)으로 서버가 처리
          const cmd = dev_id + '/' + ch_id + '/on/sec/' + totalSec;
          modOutputOutput_tm(cmd, wid);
          // Immediately start timer at 00:00:00 and freeze the start label
          tm_setLocalStartBase(wid);
          tm_startCountdown(wid);     // 0초면 내부적으로 카운트다운 없음(무기한)
          // 서버 시작시각 동기화는 getGPIOStateOutput_tm → tm_fetchServerStartTime 경로에서 처리
        } else {
          // OFF
          const cmd = dev_id + '/' + ch_id + '/off/sec/0';
          modOutputOutput_tm(cmd, wid);
          tm_stopCountdown(wid);
          tm_stopTimestamp(wid, false);
        }
      });
    """,

    # ------------------ JS READY ------------------
    'widget_dashboard_js_ready': """
    {%- set wo = widget_options if widget_options is defined else {} -%}
    {%- set output = wo.get('output', '') -%}
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if output and ',' in output -%}
      {%- set device_id = output.split(',')[0] -%}
      {%- set channel_id = output.split(',')[1] -%}
    {%- endif -%}

    {%- if device_id and channel_id -%}
      // [AoT Timer] READY: name assignment only (no fetch here)
      (function(){
        const wid   = "{{each_widget.unique_id}}";
        const devId = "{{device_id}}";
        const chId  = "{{channel_id}}";
        const $chk  = $('#tm_tog_'+wid);
        $chk.attr('name', devId + '/' + chId);
        console.debug("[AoT Timer] READY: name assigned", devId, chId);
      })();
    {%- else -%}
      console.debug("[AoT Timer] READY: device_id/channel_id not provided yet; will be set in READY_END.");
    {%- endif -%}
    """,

    # ------------------ JS READY END ------------------
    'widget_dashboard_js_ready_end': """
    {%- set wo = widget_options if widget_options is defined else {} -%}
    {%- set output = wo.get('output', '') -%}
    {%- set refresh_seconds = wo.get('refresh_seconds', 3) -%}
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if output and ',' in output -%}
      {%- set device_id = output.split(',')[0] -%}
      {%- set channel_id = output.split(',')[1] -%}
    {%- endif -%}

    {%- if device_id and channel_id -%}
      // [AoT Timer] READY_END: assign name and kick off initial fetches
      (function(){
        const wid   = "{{each_widget.unique_id}}";
        const devId = "{{device_id}}";
        const chId  = "{{channel_id}}";
        const $chk  = $('#tm_tog_'+wid);

        // 1) Set the 'name' attribute (dev/ch pair) only if both exist
        if (devId && chId) {
          $chk.attr('name', devId + '/' + chId);
          console.debug('[AoT Timer] READY_END: name assigned', devId, chId);
          // 2) Initial state check
          getGPIOStateOutput_tm(wid);
          // 3) Periodic state refresh
          tm_initAutoRefresh(wid, {{ refresh_seconds }});
        } else {
          console.debug('[AoT Timer] READY_END: device_id/channel_id missing. Polling skipped for', wid);
          tm_setTextStable(wid, '00:00:00');
        }

      })();
    {%- else -%}
      console.warn("[AoT Timer] READY_END: device_id or channel_id missing. Name not assigned.");
    {%- endif -%}
    """
}
