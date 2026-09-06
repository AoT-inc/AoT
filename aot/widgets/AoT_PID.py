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
#    This software is a derivative version based on the open-source Mycodo project, modified to suit the purposes of the AoT project.
#    This file is distributed under the GNU GPLv3 license and adheres to the original copyright terms.
#
#  Last modified: 2025-04-21

import logging
from flask import jsonify
from flask_babel import lazy_gettext
from flask_login import current_user

from aot.databases.models import Conversion, DeviceMeasurements, Method, MethodData, PID
from aot.aot_client import DaemonControl
from aot.aot_flask.access import scope
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.influx import read_influxdb_single
from aot.utils.method import create_method_handler
from aot.utils.system_pi import return_measurement_info, str_is_float
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)

def return_point_timestamp(dev_id, unit, period, measurement=None, channel=None):
    """Query InfluxDB and return a (timestamp, value) tuple for the given device and period.

    @phase active
    @stability stable
    @dependency read_influxdb_single
    """
    last_data = read_influxdb_single(
        dev_id, unit, channel,
        measure=measurement, value='LAST',
        duration_sec=period
    )
    if not last_data:
        return [None, None]
    return last_data

def _compute_weeks_elapsed(pid, facility_tz) -> float:
    """Compute weeks_elapsed the same way the PID controller does.

    Priority:
      1. pid.schedule_start_time (date-only YYYY-MM-DD -> facility_tz midnight)
      2. pid.method_start_time (time the method was first activated)
      3. 0.0 (fallback)
    """
    import re as _re
    import datetime as _dt
    from aot.utils.method import parse_db_time

    week_offset = float(getattr(pid, 'schedule_week_offset', 0.0) or 0.0)
    now_utc = _dt.datetime.now(_dt.timezone.utc)

    start_raw = (getattr(pid, 'schedule_start_time', None) or '').strip()
    if start_raw:
        try:
            from dateutil.parser import isoparse
            date_only = bool(_re.fullmatch(r'\d{4}-\d{2}-\d{2}', start_raw))
            if date_only:
                if facility_tz is None:
                    return 0.0
                year, month, day = map(int, start_raw.split('-'))
                local_midnight = _dt.datetime(year, month, day, 0, 0, 0)
                try:
                    start_dt = facility_tz.localize(local_midnight)
                except AttributeError:
                    start_dt = local_midnight.replace(tzinfo=facility_tz)
            else:
                start_dt = isoparse(start_raw)
                if start_dt.tzinfo is None:
                    if facility_tz is not None:
                        try:
                            start_dt = facility_tz.localize(start_dt)
                        except AttributeError:
                            start_dt = start_dt.replace(tzinfo=facility_tz)
                    else:
                        start_dt = start_dt.replace(tzinfo=_dt.timezone.utc)
            elapsed_sec = (now_utc - start_dt).total_seconds()
            return max(0.0, elapsed_sec / (7 * 86400) + week_offset)
        except Exception:
            return 0.0

    method_start_raw = getattr(pid, 'method_start_time', None)
    if not method_start_raw:
        return 0.0
    try:
        start_dt = parse_db_time(str(method_start_raw))
        if start_dt is None:
            return 0.0
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=_dt.timezone.utc)
        elapsed_sec = (now_utc - start_dt).total_seconds()
        return max(0.0, elapsed_sec / (7 * 86400) + week_offset)
    except Exception:
        return 0.0


def last_data_pid(pid_id, input_period):
    """Return the latest PID values (P, I, D, sum) and duration time for the widget display.

    @phase active
    @stability stable
    @dependency PID, DeviceMeasurements, Conversion, DaemonControl
    """
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not str_is_float(input_period):
        return '', 204
    try:
        if not pid_id or pid_id == 'None':
            return '', 204
        pid = PID.query.filter(PID.unique_id == pid_id).first()
        if not pid:
            return '', 204
        if len(pid.measurement.split(',')) == 2:
            dev_id = pid.measurement.split(',')[0]
            meas_id= pid.measurement.split(',')[1]
        else:
            return '', 204
        d_meas = DeviceMeasurements.query.filter(DeviceMeasurements.unique_id == meas_id).first()
        if not d_meas:
            return '', 204
        d_conv = Conversion.query.filter(Conversion.unique_id == d_meas.conversion_id).first() if d_meas else None
        a_channel, a_unit, a_measurement = return_measurement_info(d_meas, d_conv)
        p_val = return_point_timestamp(pid_id, 'pid_value', input_period, measurement='pid_p_value')
        i_val = return_point_timestamp(pid_id, 'pid_value', input_period, measurement='pid_i_value')
        d_val = return_point_timestamp(pid_id, 'pid_value', input_period, measurement='pid_d_value')
        pid_sum_val = None
        if None not in (p_val[1], i_val[1], d_val[1]):
            sum_pid = float(p_val[1]) + float(i_val[1]) + float(d_val[1])
            pid_sum_val = [p_val[0], f'{sum_pid:.1f}']
        # Current setpoint: method tracking → compute directly from the method curve
        # (more reliable than InfluxDB which requires PID to have run recently)
        tracking_type = pid.setpoint_tracking_type or ''
        tracking_id   = pid.setpoint_tracking_id   or ''
        method_setpoint = None
        if tracking_type == 'method' and tracking_id:
            try:
                method_db   = Method.query.filter(Method.unique_id == tracking_id).first()
                method_data = MethodData.query.filter(MethodData.method_id == tracking_id)
                if method_db and method_data:
                    handler = create_method_handler(method_db, method_data, logger)
                    now = utc_now()
                    if method_db.method_type == 'DailyMultiPoint':
                        from aot.utils.device_tz import get_device_tz
                        facility_tz = get_device_tz(pid)
                        weeks_elapsed = _compute_weeks_elapsed(pid, facility_tz)
                        sp, _ = handler.calculate_setpoint(
                            now, pid.method_start_time,
                            weeks_elapsed=weeks_elapsed,
                            facility_tz=facility_tz)
                    else:
                        sp, _ = handler.calculate_setpoint(now, pid.method_start_time)
                    if sp is not None:
                        method_setpoint = round(float(sp), 6)
            except Exception as ex:
                logger.warning(f"method setpoint compute failed: {ex}")

        data_dict = {
            'activated': pid.is_activated,
            'paused': pid.is_paused,
            'held': pid.is_held,
            'pid_p_value': p_val,
            'pid_i_value': i_val,
            'pid_d_value': d_val,
            'pid_pid_value': pid_sum_val,
            'duration_time': return_point_timestamp(pid_id, 's', input_period, measurement='duration_time'),
            'setpoint_tracking_type': tracking_type,
            'setpoint_tracking_id':   tracking_id,
            'pid_static_setpoint':    pid.setpoint,
            'method_setpoint':        method_setpoint,
        }
        data_dict['actual'] = return_point_timestamp(dev_id, a_unit, input_period, measurement=a_measurement, channel=a_channel)
        return jsonify(data_dict)
    except Exception as ex:
        logger.error(f"Error in last_data_pid(): {ex}", exc_info=True)
        return '', 204

def pid_mod_unique_id(unique_id, state):
    """Send a command to a PID controller (activate, deactivate, pause, hold, resume, set_setpoint).

    @phase active
    @stability stable
    @dependency PID, DaemonControl
    """
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to manipulate PID'

    # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
    if not scope.can_operate_device(unique_id):
        return 'ERROR: ' + scope.deny_message()
    if not unique_id or unique_id == 'None':
        return "No PID selected"
    pid = PID.query.filter(PID.unique_id == unique_id).first()
    if not pid:
        return "No PID found"
    try:
        daemon = DaemonControl()
        if state == 'activate':
            if not pid.measurement or len(pid.measurement.split(',')) != 2:
                return "PID has no valid measurement configured"
            if not pid.raise_output_id and not pid.lower_output_id:
                return "PID has no raise/lower output configured"
            _, msg = daemon.controller_activate(pid.unique_id)
            if _ == 0:
                pid.is_activated = True
                pid.is_paused = False
                pid.is_held = False
                pid.save()
            return msg
        elif state == 'deactivate':
            _, msg = daemon.controller_deactivate(pid.unique_id)
            pid.is_activated = False
            pid.is_paused = False
            pid.is_held = False
            pid.save()
            return msg
        elif state == 'pause':
            pid.is_paused = True
            pid.is_held = False
            pid.save()
            if pid.is_activated:
                return daemon.pid_pause(pid.unique_id)
            else:
                return "PID Paused (Note: not active)"
        elif state == 'hold':
            pid.is_held = True
            pid.is_paused = False
            pid.save()
            if pid.is_activated:
                return daemon.pid_hold(pid.unique_id)
            else:
                return "PID Held (Note: not active)"
        elif state == 'resume':
            pid.is_held = False
            pid.is_paused = False
            pid.save()
            if pid.is_activated:
                return daemon.pid_resume(pid.unique_id)
            else:
                return "PID Resumed (Note: not active)"
        elif 'set_setpoint_pid' in state:
            new_sp = state.split('|')[1]
            pid.setpoint = float(new_sp)
            pid.save()
            if pid.is_activated:
                return daemon.pid_set(pid.unique_id, 'setpoint', float(new_sp))
            else:
                return "PID setpoint changed (Note: not active)"
        else:
            return "Invalid state requested", 400
    except Exception as ex:
        logger.error(f"Error in pid_mod_unique_id({state}): {ex}", exc_info=True)
        return f"Error: {ex}"

def pid_set_params(pid_id):
    """Apply multiple PID parameters at once from the detail settings modal.

    Accepts JSON body: { setpoint, p, i, d, period, band, integrator_min, integrator_max }
    Live-updates setpoint/kp/ki/kd via daemon.pid_set(); reinitialises via daemon.pid_mod()
    for period/band/integrator changes.
    """
    from flask import request
    if not current_user.is_authenticated:
        return "Not logged in", 401
    if not user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to modify PID', 403

    # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
    if not scope.can_operate_device(pid_id):
        return (scope.deny_message(), 403)
    if not pid_id or pid_id == 'None':
        return 'No PID specified', 400
    pid = PID.query.filter(PID.unique_id == pid_id).first()
    if not pid:
        return 'PID not found', 404
    try:
        data = request.get_json(silent=True) or {}
        live_map = {
            'setpoint': 'setpoint',
            'p':        'kp',
            'i':        'ki',
            'd':        'kd',
        }
        mod_fields = ['period', 'band', 'integrator_min', 'integrator_max']
        live_updates = []
        needs_mod    = False
        changed      = False

        for key, daemon_key in live_map.items():
            if key in data and data[key] != '':
                val = float(data[key])
                setattr(pid, key, val)
                live_updates.append((daemon_key, val))
                changed = True

        for key in mod_fields:
            if key in data and data[key] != '':
                setattr(pid, key, float(data[key]))
                changed = True
                needs_mod = True

        if changed:
            pid.save()
            if pid.is_activated:
                daemon = DaemonControl()
                for daemon_key, val in live_updates:
                    daemon.pid_set(pid.unique_id, daemon_key, val)
                if needs_mod:
                    daemon.pid_mod(pid.unique_id)

        return jsonify({'status': 'ok'})
    except Exception as ex:
        logger.error(f"Error in pid_set_params(): {ex}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(ex)}), 500


############################################################################
# The WIDGET_INFORMATION(custom_options) below is unchanged.
# However, it has been improved so that custom_options are reflected in the actual UI/JS.
############################################################################
WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_pid',
    'widget_name': lazy_gettext('AoT PID'),
    # On mobile (<=768px), place only one per row horizontally (full width). When False/unspecified, two per row are allowed.
    'mobile_full_width': True,
    'widget_library': 'controller',
    'no_class': True,

    'message': lazy_gettext('Displays and allows control of a PID Controller.'),

    'widget_width': 24,
    'widget_height': 13,

    'endpoints': [
        ("/last_pid/<pid_id>/<input_period>", "last_pid", last_data_pid, ["GET"]),
        ("/pid_mod_unique_id/<unique_id>/<state>", "pid_mod_unique_id", pid_mod_unique_id, ["GET"]),
        ("/pid_set_params/<pid_id>", "pid_set_params", pid_set_params, ["POST"]),
    ],

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('Device Settings')
        },
        {
            'id': 'pid',
            'type': 'select_device',
            'default_value': '',
            'options_select': ['PID'],
            'name': lazy_gettext('PID Controller'),
            'phrase': lazy_gettext('Select the PID controller to control.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Execution Settings')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 3600,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Maximum validity time for measurements used')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 3.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Frequency of widget refresh')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Display Settings')
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Timestamp'),
            'phrase': lazy_gettext('Display timestamp on the widget.')
        },
        {
            'id': 'font_em_timestamp',
            'type': 'float',
            'default_value': 1.0,
            'name': lazy_gettext('Timestamp Font Size'),
            'phrase': lazy_gettext('Set the font size for the timestamp.')
        },
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Decimal Places'),
            'phrase': lazy_gettext('Number of decimal places for numeric values.')
        },
        {
            'id': 'enable_status',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Status Display'),
            'phrase': lazy_gettext('Display the status of the controller.')
        },
        {
            'id': 'show_pid_info',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('PID Info'),
            'phrase': lazy_gettext('Show current PID configuration.')
        },
        {
            'id': 'show_set_setpoint',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Setpoint'),
            'phrase': lazy_gettext('Allows setting a target value.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Graph Settings')
        },
        {
            'id': 'enable_graph',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Graph'),
            'phrase': lazy_gettext('Display a graph of setpoint, measured value, and output.')
        },
        {
            'id': 'graph_height_px',
            'type': 'integer',
            'default_value': 200,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Graph Height (px)'),
            'phrase': lazy_gettext('Height of the graph area in pixels.')
        },
        {
            'id': 'graph_x_axis_unit',
            'type': 'select',
            'default_value': 'hour',
            'options_select': [
                ('day', lazy_gettext('Day')),
                ('hour', lazy_gettext('Hour')),
                ('minute', lazy_gettext('Minute')),
            ],
            'name': lazy_gettext('X-Axis Duration Unit'),
            'phrase': lazy_gettext('Unit for the X-axis duration of the graph.')
        },
        {
            'id': 'graph_x_axis_duration',
            'type': 'integer',
            'default_value': 6,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('X-Axis Duration'),
            'phrase': lazy_gettext('Amount of past data to display on the graph X-axis.')
        },
        {
            'id': 'enable_auto_refresh',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Auto Refresh Graph'),
            'phrase': lazy_gettext('Automatically append new data to the graph at the refresh interval.')
        },
        {
            'id': 'enable_xaxis_reset',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Reset X-Axis on Refresh'),
            'phrase': lazy_gettext('Reset the X-axis range when refreshing the graph.')
        }
    ],

  # ------------------ HEAD (CSS) ------------------
  'widget_dashboard_head': """
{% if "highstock" not in dashboard_dict %}
  <script type="text/javascript" src="{{ asset('highcharts-stack') }}"></script>
  {% set _dummy = dashboard_dict.update({"highstock": 1}) %}
{% endif %}
{% if "aot_chart_core" not in dashboard_dict %}
  <script src="{{ asset('app-chart-core') }}"></script>
  {% set _dummy = dashboard_dict.update({"aot_chart_core": 1}) %}
{% endif %}
{% if current_user.theme in dark_themes %}
  <script type="text/javascript" src="/static/js/vendor/user_js/dark-unica-custom.js?v=20260814a"></script>
{% endif %}
""",

  # ------------------ TITLE BAR ------------------
  'widget_dashboard_title_bar': """
  {%- if widget_options['enable_status'] -%}
    <span id="text-pid-state-{{each_widget.unique_id}}"></span>{{' '}}
  {%- else -%}
    <span style="display: none" id="text-pid-state-{{each_widget.unique_id}}"></span>
  {%- endif -%}

  <span class="aot-w-title" style="padding-right:0.5em"> {{each_widget.name}}</span>
  """,

  # ------------------ BODY ------------------
  'widget_dashboard_body': """
<style>
/* ===== AoT PID — Modern UI (matching AoT_timer tone and manner) ===== */
#pid_container_{{each_widget.unique_id}} {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
#pid_container_{{each_widget.unique_id}} .col-aot-2 {
  width: 60px !important;
  border: none !important;
}

/* Widget background — gray when deactivated, current inactive color (light) when activated
   (light theme reference: --bg-active=#D1D5D5 gray, --bg-inactive=#F3F6F5 light) */
/* 상태 클래스 ↔ 토큰: active(작동 중)→bg_active, inactive(꺼짐)→bg_inactive,
   pause/hold(일시정지·유지)→bg_pause(=bg_warning)/bg_hold(=bg_pending).
   과거 active/inactive 가 서로 뒤바뀌어 있었다(관리자가 설정한 색과 정반대로
   보이는 버그, custom_ui.html 의 bg_inactive 도움말 "PID container
   background" 문구와도 모순됨) — color-system.md 참조. */
#pid_container_{{each_widget.unique_id}}.active-background {
  background-color: var(--bg-active) !important;
}
#pid_container_{{each_widget.unique_id}}.inactive-background {
  background-color: var(--bg-inactive) !important;
}
#pid_container_{{each_widget.unique_id}}.pause-background {
  background-color: var(--bg-pause) !important;
}
#pid_container_{{each_widget.unique_id}}.hold-background {
  background-color: var(--bg-hold) !important;
}

/* Row 1: last-active text — hidden; spans kept for JS reference */
#pid_container_{{each_widget.unique_id}} .pid-aot-timestamp {
  display: none;
}
#pid_container_{{each_widget.unique_id}} .pid-aot-timestamp span {
  display: none;
}

/* Common row */
#pid_container_{{each_widget.unique_id}} .pid-aot-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

/* Row 2: PID equation */
#pid_container_{{each_widget.unique_id}} .pid-eq {
  font-size: var(--aot-fs-label);
  font-weight: var(--aot-fw-semibold);
  color: var(--text-medium-gray, #8a8a8a);
  line-height: 1.3;
  word-break: break-all;
}
#pid_container_{{each_widget.unique_id}} .pid-eq .pid-eq-sum {
  color: var(--aot-text-main, #333);
  font-variant-numeric: tabular-nums;
}
#pid_container_{{each_widget.unique_id}} .pid-eq span[id^="pid_"] {
  font-variant-numeric: tabular-nums;
}

/* Row 4: setpoint — label on the left, input field on the right */
#pid_container_{{each_widget.unique_id}} .pid-setpoint-row {
  justify-content: space-between;
}
#pid_container_{{each_widget.unique_id}} .pid-aot-label {
  font-size: var(--aot-fs-body);
  font-weight: var(--aot-fw-semibold);
  color: var(--aot-text-main, #333);
  white-space: nowrap;
}

/* Row 5: pause/hold — right-aligned, group of two buttons (78+4+78=160) */
#pid_container_{{each_widget.unique_id}} .pid-btn-row {
  justify-content: flex-end;
  gap: 4px;
}


/* Buttons — pill, same as dashboard tabs on hover
   (!important needed to override aot.css rules like .btn-aot-pid-sm{width:54px!important})
   widths: pause/hold = 78px, resume = 160px (individual rules below) */
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-sm,
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-resume {
  box-sizing: border-box;
  flex: 0 0 auto;
  height: 34px !important;
  padding: 0 0.4em !important;
  font-size: var(--aot-fs-label) !important;
  font-weight: var(--aot-fw-semibold);
  white-space: nowrap;
  text-overflow: clip;
  border: 1px solid var(--border-neutral, #d7d3c4) !important;
  border-radius: 9999px !important;
  background: var(--aot-input-bg, #fff) !important;
  color: var(--aot-text-main, #333) !important;
  box-shadow: none !important;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-sm:hover,
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-resume:hover {
  background: var(--bd-btn-primary, #13261B) !important;
  color: var(--text-color-tertiary, #FFFFFF) !important;
  border-color: var(--bd-btn-primary, #13261B) !important;
}
/* pause/hold = 78px (78+4+78=160), resume = 160px */
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-sm {
  width: 78px !important;
  min-width: 78px !important;
}
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-resume {
  width: 160px !important;
  min-width: 160px !important;
}

/* Row 3: graph */
#pid_container_{{each_widget.unique_id}} .pid-graph {
  width: 100%;
}

/* PID Settings button — same pill style, 160px */
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-detail {
  box-sizing: border-box;
  flex: 0 0 auto;
  width: 160px !important;
  min-width: 160px !important;
  height: 34px !important;
  padding: 0 0.4em !important;
  font-size: var(--aot-fs-label) !important;
  font-weight: var(--aot-fw-semibold);
  white-space: nowrap;
  border: 1px solid var(--border-neutral, #d7d3c4) !important;
  border-radius: 9999px !important;
  background: var(--aot-input-bg, #fff) !important;
  color: var(--aot-text-main, #333) !important;
  box-shadow: none !important;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
#pid_container_{{each_widget.unique_id}} .btn-aot-pid-detail:hover {
  background: var(--bd-btn-primary, #13261B) !important;
  color: var(--text-color-tertiary, #FFFFFF) !important;
  border-color: var(--bd-btn-primary, #13261B) !important;
}

/* PID Settings Modal — overlay + panel styled to match .aot-option-modal */
#pid_modal_{{each_widget.unique_id}} {
  position: fixed;
  inset: 0;
  z-index: var(--aot-z-modal);
  background: rgba(0, 0, 0, 0.45);
  align-items: center;
  justify-content: center;
  padding: 0.5rem;
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-content {
  display: flex;
  flex-direction: column;
  width: 400px;
  max-width: 100%;
  max-height: calc(100vh - 1rem);
  overflow: hidden;
  background: var(--aot-surface-card, #fff);
  border-radius: 1rem;
  border: none;
  box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 50px;
  padding: 0 1rem;
  border-bottom: 1px solid var(--border-neutral, #dee2e6);
  background: var(--aot-surface-card, #fff);
  border-top-left-radius: 1rem;
  border-top-right-radius: 1rem;
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-header h5 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--aot-text-main, #333);
  line-height: 1.4;
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  color: var(--aot-text-secondary, #888);
  padding: 0;
  opacity: 0.7;
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-close:hover { opacity: 1; }
#pid_modal_{{each_widget.unique_id}} .pid-modal-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0.5rem 1rem 0.75rem;
  -webkit-overflow-scrolling: touch;
  /* 배경 2단 레이어링: 헤더/푸터(배경 기본)와 대비되는 배경 보조 —
     .aot-option-modal 과 동일한 규칙(color-system.md 참조). */
  background: var(--aot-surface-body, #F3F6F5);
}
#pid_modal_{{each_widget.unique_id}} .pid-modal-footer {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.25rem;
  min-height: 50px;
  padding: 9px 1rem;
  border-top: 1px solid var(--border-neutral, #dee2e6);
  background: var(--aot-surface-card, #fff);
  border-bottom-left-radius: 1rem;
  border-bottom-right-radius: 1rem;
}
</style>


<link rel="stylesheet" href="{{ url_for('static', filename='css/components/aot-toggle.css') }}">
{% set this_pid = table_pid.query.filter(table_pid.unique_id == widget_options['pid']).first() %}

<div class="frame-aot" id="pid_container_{{each_widget.unique_id}}">

  <!-- Row 1: last active + toggle button -->
  <div class="row-aot-1">
    <div class="col-aot-1">
      <div class="prt-text pid-aot-timestamp" style="display:none;">
        <span id="duration_time-{{each_widget.unique_id}}"></span>
        <span id="duration_time-{{each_widget.unique_id}}-timestamp"></span>
      </div>
    </div>
    <div class="col-aot-2">
      <label class="btn-toggle">
        <input type="checkbox"
              id="toggle_input_{{each_widget.unique_id}}"
              class="btn-toggle-input"
              onclick="togglePID_AoT('{{each_widget.unique_id}}')">
        <span class="btn-toggle-slider">
              <span class="btn-toggle-thumb"></span>
        </span>
      </label>
    </div>
  </div>

  <!-- Row 2: graph (same Highstock graph as AoT_graph, including range selector) -->
  {% if widget_options.get('enable_graph', True) %}
  <div class="not-draggable pid-graph"
       id="container-synchronous-graph-{{each_widget.unique_id}}"
       style="position: relative; width: 100%; height: {{ (widget_options.get('graph_height_px', 200)|int) + 32 }}px; margin: 0 0 8px 0; border-radius: 8px; overflow: hidden;"></div>
  {% endif %}

  <!-- Row 3: PID equation -->
  {% if widget_options.get('show_pid_info',True) %}
  <div class="pid-aot-row pid-eq">
    <span>
      PID: <span class="pid-eq-sum" id="pid_pid_value-{{each_widget.unique_id}}"></span>
      = <span id="pid_p_value-{{each_widget.unique_id}}"></span> (P),
      <span id="pid_i_value-{{each_widget.unique_id}}"></span> (I),
      <span id="pid_d_value-{{each_widget.unique_id}}"></span> (D)
    </span>
  </div>
  {% else %}
  <span style="display:none" id="pid_pid_value-{{each_widget.unique_id}}"></span>
  <span style="display:none" id="pid_p_value-{{each_widget.unique_id}}"></span>
  <span style="display:none" id="pid_i_value-{{each_widget.unique_id}}"></span>
  <span style="display:none" id="pid_d_value-{{each_widget.unique_id}}"></span>
  {% endif %}

  <!-- Row 4: PID Detail Settings button -->
  {% if widget_options.get('show_set_setpoint', True) %}
  <div class="pid-aot-row pid-setpoint-row">
    <span class="pid-aot-label">{{_('PID Detail Settings')}}</span>
    <button class="btn-aot-pid-detail"
            onclick="openPidDetailModal('{{each_widget.unique_id}}')">
      {{_('PID Settings')}}
    </button>
  </div>
  {% endif %}
  <!-- Hidden apply trigger (used by setSetpointAoT) -->
  <button id="btn_pid_set_{{each_widget.unique_id}}"
          name="{{widget_options['pid']}}/set_setpoint_pid|"
          style="display:none;"></button>

  <!-- Row 5: pause / hold buttons -->
  <div class="pid-aot-row pid-btn-row">
    <button id="btn_pid_pause_{{each_widget.unique_id}}"
            name="{{widget_options['pid']}}/pause"
            class="btn-aot-pid-sm"
            onclick="sendPIDCommandAoT(this.name)">
      {{_('Pause')}}
    </button>
    <button id="btn_pid_hold_{{each_widget.unique_id}}"
            name="{{widget_options['pid']}}/hold"
            class="btn-aot-pid-sm"
            onclick="sendPIDCommandAoT(this.name)">
      {{_('Hold')}}
    </button>
    <button id="btn_pid_resume_{{each_widget.unique_id}}"
            name="{{widget_options['pid']}}/resume"
            class="btn-aot-pid-resume"
            style="display:none;"
            onclick="sendPIDCommandAoT(this.name)">
      {{_('Resume')}}
    </button>
  </div>
</div>

<!-- PID Settings Modal (always in DOM so JS can update pid_setpoint input) -->
<div id="pid_modal_{{each_widget.unique_id}}" style="display:none;">
  <div class="pid-modal-content">

    <div class="pid-modal-header">
      <h5>{{_('PID Settings')}}</h5>
      <button class="pid-modal-close"
              onclick="closePidDetailModal('{{each_widget.unique_id}}')">&#215;</button>
    </div>

    <div class="pid-modal-body">

      <!-- Target -->
      <p class="aot-modal-section-title">{{_('Target')}}</p>
      <div class="aot-modal-container">
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">{{_('Setpoint')}}</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_setpoint_{{widget_options['pid']}}"
                   class="aot-modern-input"
                   placeholder="—"
                   {% if this_pid %}value="{{this_pid.setpoint}}"{% endif %}
                   {% if this_pid and this_pid.setpoint_tracking_type %}readonly{% endif %}>
          </div>
        </div>
      </div>

      <!-- Gains -->
      <p class="aot-modal-section-title">{{_('Gains')}}</p>
      <div class="aot-modal-container">
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">P (Kp)</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_p_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.p}}"{% endif %}>
          </div>
        </div>
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">I (Ki)</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_i_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.i}}"{% endif %}>
          </div>
        </div>
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">D (Kd)</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_d_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.d}}"{% endif %}>
          </div>
        </div>
      </div>

      <!-- Timing & Limits -->
      <p class="aot-modal-section-title">{{_('Timing & Limits')}}</p>
      <div class="aot-modal-container">
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">{{_('Period')}} (s)</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any" min="1"
                   id="pid_period_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.period}}"{% endif %}>
          </div>
        </div>
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">{{_('Band')}}</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any" min="0"
                   id="pid_band_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.band}}"{% endif %}>
          </div>
        </div>
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">{{_('Integrator Min')}}</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_imin_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.integrator_min}}"{% endif %}>
          </div>
        </div>
        <div class="aot-modal-option-row">
          <label class="aot-modal-option-label">{{_('Integrator Max')}}</label>
          <div class="aot-modal-option-control">
            <input type="number" step="any"
                   id="pid_imax_{{each_widget.unique_id}}"
                   class="aot-modern-input" placeholder="—"
                   {% if this_pid %}value="{{this_pid.integrator_max}}"{% endif %}>
          </div>
        </div>
      </div>

    </div><!-- /.pid-modal-body -->

    <div class="pid-modal-footer">
      <button class="btn aot-pill-btn"
              onclick="closePidDetailModal('{{each_widget.unique_id}}')">{{_('Cancel')}}</button>
      <button class="btn aot-pill-btn aot-pill-btn-primary"
              onclick="applyPidModalSettings('{{each_widget.unique_id}}')">{{_('Apply')}}</button>
    </div>

  </div><!-- /.pid-modal-content -->
</div>

<!-- Hidden buttons -->
<input type="button"
       id="hidden_pid_activate_{{each_widget.unique_id}}"
       style="display:none;"
       name="{{widget_options['pid']}}/activate"
       value="{{_('activate')}}"/>
<input type="button"
       id="hidden_pid_deactivate_{{each_widget.unique_id}}"
       style="display:none;"
       name="{{widget_options['pid']}}/deactivate"
       value="{{_('deactivate')}}"/>
""",

    'widget_dashboard_js': """
function togglePID_AoT(wid) {
  let toggleInput = document.getElementById("toggle_input_" + wid);
  let actBtn      = document.getElementById("hidden_pid_activate_" + wid);
  let deactBtn    = document.getElementById("hidden_pid_deactivate_" + wid);

  if(toggleInput.checked) {
    if(actBtn) actBtn.click();
  } else {
    if(deactBtn) deactBtn.click();
  }
}

function openPidDetailModal(wid) {
  let modal = document.getElementById("pid_modal_" + wid);
  modal.style.display = "flex";
  modal.onclick = function(e) {
    if (e.target === modal) closePidDetailModal(wid);
  };
}

function closePidDetailModal(wid) {
  let modal = document.getElementById("pid_modal_" + wid);
  modal.style.display = "none";
}

function applyPidModalSettings(wid) {
  let btn_set = document.getElementById("btn_pid_set_" + wid);
  if (!btn_set) return;
  let pid_id = btn_set.name.split('/')[0];

  function val(id) {
    let el = document.getElementById(id);
    return (el && el.value !== '') ? el.value : undefined;
  }

  let payload = {};
  let sp = val("pid_setpoint_" + pid_id);
  if (sp !== undefined) payload.setpoint = sp;

  let fields = [
    ["p",              "pid_p_"    + wid],
    ["i",              "pid_i_"    + wid],
    ["d",              "pid_d_"    + wid],
    ["period",         "pid_period_" + wid],
    ["band",           "pid_band_"   + wid],
    ["integrator_min", "pid_imin_"   + wid],
    ["integrator_max", "pid_imax_"   + wid],
  ];
  fields.forEach(function(f) {
    let v = val(f[1]);
    if (v !== undefined) payload[f[0]] = v;
  });

  if (Object.keys(payload).length === 0) {
    closePidDetailModal(wid);
    return;
  }

  $.ajax({
    type: 'POST',
    url: '/pid_set_params/' + pid_id,
    contentType: 'application/json',
    data: JSON.stringify(payload),
    success: function() {
      closePidDetailModal(wid);
    },
    error: function(err) {
      window.showToast("{{_('Error')}}: " + JSON.stringify(err), "error");
    }
  });
}

function setSetpointAoT(wid) {
  let btn_set = document.getElementById("btn_pid_set_" + wid);
  let sp_id   = btn_set.name.split('/')[0];
  let sp_val  = document.getElementById("pid_setpoint_" + sp_id).value;
  if(sp_val) {
    let cmd = btn_set.name + sp_val;
    sendPIDCommandAoT(cmd);
  }
}

function sendPIDCommandAoT(cmd) {
  if (!cmd || cmd.startsWith("None/")) {
    console.error("No PID selected");
    return;
  }
  $.ajax({
    type: 'GET',
    url: '/pid_mod_unique_id/' + cmd,
    success: function(res) {
      console.log("Server response:", res);
      // Handle any additional UI updates here if needed.
    },
    error: function(err) {
      console.error("Error:", err);
    }
  });
}

function printPidValueAoT(data, nm, wid, decs) {
  let entry = data[nm];
  if(entry && Array.isArray(entry) && entry[1] != null) {
    // duration_time 은 출력이 켜져 있던 '초' 다 — 숫자로 찍으면 사람이 암산해야 한다.
    let val = (nm === "duration_time")
      ? AoTChart.formatDuration(parseFloat(entry[1]))
      : parseFloat(entry[1]).toFixed(decs);
    $("#"+nm+"-"+wid).text(val);
    if(entry[0]) {
      let tsEl = document.getElementById(nm + "-" + wid + "-timestamp");
      if(tsEl) tsEl.innerHTML = epoch_to_timestamp(entry[0]*1000);
    }
  } else {
    $("#"+nm+"-"+wid).text("N/A");
  }
}

function printPidErrorAoT(wid, pidid) {
  $("#duration_time-"+wid).text("ERR");
  if(document.getElementById("duration_time-"+wid+"-timestamp")) {
    document.getElementById("duration_time-"+wid+"-timestamp").innerHTML = "";
  }
  $("#pid_p_value-"+wid).text("ERR");
  $("#pid_i_value-"+wid).text("ERR");
  $("#pid_d_value-"+wid).text("ERR");
  $("#pid_pid_value-"+wid).text("ERR");

  if(pidid) {
    let spInput = document.getElementById("pid_setpoint_"+pidid);
    if(spInput) { spInput.readOnly = false; spInput.style.opacity=''; spInput.style.cursor=''; }
    // The Set button is hidden (applied via Enter), so do not toggle its display
  }

  let container = document.getElementById("pid_container_"+wid);
  container.classList.remove("pause-background","active-background","inactive-background","hold-background");
  container.classList.add("inactive-background");
}

function getPidDataAoT(wid, pidid, max_age, decs) {
  if(!pidid || pidid==='None'){
    printPidErrorAoT(wid, null);
    window.showToast("{{_('No PID selected')}}", "error");
    return;
  }
  $.ajax("/last_pid/"+pidid+"/"+max_age, {
    success:function(data, txtStatus, jqXHR){
      if(jqXHR.status===204) {
        printPidErrorAoT(wid, pidid);
        window.showToast("{{_('No PID found or no measurement')}}", "error");
        return;
      }
      // The actual value is replaced by the graph and not displayed
      printPidValueAoT(data, "duration_time", wid, decs);
      // PID equation — 4 digits, sum (PID) = P+I+D
      printPidValueAoT(data, "pid_p_value", wid, 4);
      printPidValueAoT(data, "pid_i_value", wid, 4);
      printPidValueAoT(data, "pid_d_value", wid, 4);
      (function(){
        let p = (data.pid_p_value && data.pid_p_value[1] != null) ? parseFloat(data.pid_p_value[1]) : null;
        let i = (data.pid_i_value && data.pid_i_value[1] != null) ? parseFloat(data.pid_i_value[1]) : null;
        let d = (data.pid_d_value && data.pid_d_value[1] != null) ? parseFloat(data.pid_d_value[1]) : null;
        if (p != null && i != null && d != null) {
          $("#pid_pid_value-"+wid).text((p + i + d).toFixed(4));
        } else {
          $("#pid_pid_value-"+wid).text("N/A");
        }
      })();

      // ── Update the setpoint input field ─────────────────────────────────────────
      let spInput = document.getElementById("pid_setpoint_" + pidid);
      if (spInput) {
        let isTracking = data.setpoint_tracking_type && data.setpoint_tracking_type !== '';
        let spVal = null;
        if (isTracking && data.method_setpoint != null) {
          // While method tracking → current setpoint computed directly by the server
          spVal = parseFloat(data.method_setpoint).toFixed(decs);
        } else if (data.pid_static_setpoint != null) {
          // Static setpoint
          spVal = parseFloat(data.pid_static_setpoint).toFixed(decs);
        }
        if (spVal !== null) spInput.value = spVal;
        // Read-only while method tracking
        spInput.readOnly = isTracking;
        spInput.style.opacity = isTracking ? '0.65' : '';
        spInput.style.cursor  = isTracking ? 'default' : '';
      }
      // ─────────────────────────────────────────────────────────────────────

      let toggleInput = document.getElementById("toggle_input_"+wid);
      toggleInput.checked = false; // default off

      let btnPause  = document.getElementById("btn_pid_pause_"+wid);
      let btnHold   = document.getElementById("btn_pid_hold_"+wid);
      let btnResume = document.getElementById("btn_pid_resume_"+wid);
      btnResume.style.display = "none";

      let container = document.getElementById("pid_container_"+wid);
      container.classList.remove("pause-background","active-background","inactive-background");

      if(data.activated) {
        toggleInput.checked = true;
        if(data.paused) {
          container.classList.add("pause-background");
          btnResume.style.display="inline-block";
          btnPause.style.display ="none";
          btnHold.style.display  ="none";
        } else if(data.held) {
          container.classList.add("pause-background");
          btnResume.style.display="inline-block";
          btnPause.style.display ="none";
          btnHold.style.display  ="none";
        } else {
          container.classList.add("active-background");
          btnPause.style.display ="inline-block";
          btnHold.style.display  ="inline-block";
        }
      } else {
        container.classList.add("inactive-background");
        btnPause.style.display ="inline-block";
        btnHold.style.display  ="inline-block";
      }
    },
    error:function(err){
      printPidErrorAoT(wid, pidid);
      window.showToast("{{_('Error')}}: " + JSON.stringify(err), "error");
    }
  });
}


function repeatPidDataAoT(wid, pidid, refsec, max_age, decs) {
  // Store per widget + clear prior so a live-preview re-init doesn't stack intervals.
  window._pid_intervals = window._pid_intervals || {};
  var _k = wid + '_data';
  if (window._pid_intervals[_k]) { clearInterval(window._pid_intervals[_k]); }
  window._pid_intervals[_k] = setInterval(function(){
    getPidDataAoT(wid, pidid, max_age, decs);
  }, refsec*1000);
}

// ===== PID graph — shared Highcharts defaults via aot-chart-core =====
// (the global widget[] registry is declared in dashboard.html)
AoTChart.applyGlobalDefaults();
if (typeof window.last_output_time_mil === 'undefined') window.last_output_time_mil = {};
var last_output_time_mil = window.last_output_time_mil;
if (typeof window._aot_pid_user_range === 'undefined') window._aot_pid_user_range = {};
var _aot_pid_user_range = window._aot_pid_user_range;

function redrawGraphPidg(widget_id, refresh_seconds, xaxis_duration_min, xaxis_reset) {
  AoTChart.deferWhileScrolling(function () {
    widget[widget_id].redraw();
    if (xaxis_reset && !_aot_pid_user_range[widget_id]) {
      const epoch_max = Date.now();
      const epoch_min = epoch_max - (xaxis_duration_min * 60 * 1000);
      widget[widget_id].xAxis[0].update({ min: epoch_min, max: epoch_max }, false);
      widget[widget_id].xAxis[0].setExtremes(epoch_min, epoch_max, true);
      widget[widget_id].xAxis[0].isDirty = true;
    }
  });
}

function getPastDataPidg(widget_id, series, unique_id, measure_type, measurement_id, past_seconds, sign) {
  sign = (sign === undefined) ? 1 : sign;
  const epoch_mil = new Date().getTime();
  const url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + past_seconds;
  const update_id = widget_id + "-" + series + "-" + unique_id + "-" + measure_type + '-' + measurement_id;
  $.getJSON(url, function(data, responseText, jqXHR) {
    if (jqXHR.status !== 204 && data && data.length) {
      let past_data = [];
      let newest_time = 0;
      for (let i = 0; i < data.length; i++) {
        const new_time = new Date(data[i][0] * 1000).getTime();
        past_data.push([new_time, parseFloat(data[i][1]) * sign]);
        // Data is not guaranteed sorted — track the newest, not the last element.
        if (new_time > newest_time) newest_time = new_time;
      }
      if (newest_time > 0) last_output_time_mil[update_id] = newest_time;
      widget[widget_id].series[series].isDirty = true;
      const epoch_min = new Date().setMinutes(new Date().getMinutes() - (past_seconds / 60));
      widget[widget_id].xAxis[0].setExtremes(epoch_min, epoch_mil);
      widget[widget_id].series[series].setData(past_data, true, false);
    }
  });
}

function retrieveLiveDataPidg(widget_id, series, unique_id, measure_type, measurement_id, xaxis_duration_min, xaxis_reset, refresh_seconds, sign) {
  sign = (sign === undefined) ? 1 : sign;
  let url = '';
  const epoch_mil = new Date().getTime();
  let update_id = widget_id + "-" + series + "-" + unique_id + "-" + measure_type + '-' + measurement_id;
  if (update_id in last_output_time_mil) {
    const past_seconds = Math.floor((epoch_mil - last_output_time_mil[update_id]) / 1000);
    url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + past_seconds;
  } else {
    url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + refresh_seconds;
  }
  $.getJSON(url, function(data, responseText, jqXHR) {
    if (jqXHR.status !== 204 && data && data.length) {
      const oldest_timestamp_allowed = epoch_mil - (xaxis_duration_min * 60 * 1000);
      // Points at or before last_known are already on the chart — the server window
      // may overlap, and re-adding them duplicates points without bound (heap blowup).
      const last_known_mil = last_output_time_mil[update_id] || 0;
      let newest_time = last_known_mil;
      for (let i = 0; i < data.length; i++) {
        const time_point = new Date(data[i][0] * 1000).getTime();
        if (time_point <= last_known_mil) continue;
        widget[widget_id].series[series].addPoint([time_point, parseFloat(data[i][1]) * sign], false, false);
        if (time_point > newest_time) newest_time = time_point;
      }
      if (newest_time > last_known_mil) last_output_time_mil[update_id] = newest_time;
      const s_pid = widget[widget_id].series[series];
      for (let i = s_pid.options.data.length - 1; i >= 0; i--) {
        const pt = s_pid.options.data[i];
        if ((Array.isArray(pt) ? pt[0] : pt.x) < oldest_timestamp_allowed) {
          s_pid.removePoint(i, false);
        }
      }
      redrawGraphPidg(widget_id, refresh_seconds, xaxis_duration_min, xaxis_reset);
    }
  });
}

function getLiveDataPidg(widget_id, series, unique_id, measure_type, measurement_id, xaxis_duration_min, xaxis_reset, refresh_seconds, sign) {
  sign = (sign === undefined) ? 1 : sign;
  window._pid_intervals = window._pid_intervals || {};
  var _k = widget_id + '_live_' + series;
  if (window._pid_intervals[_k]) { clearInterval(window._pid_intervals[_k]); }
  window._pid_intervals[_k] = setInterval(function () {
    retrieveLiveDataPidg(widget_id, series, unique_id, measure_type, measurement_id, xaxis_duration_min, xaxis_reset, refresh_seconds, sign);
  }, refresh_seconds * 1000);
}
""",

    'widget_dashboard_js_ready': """
// Document-delegated so the handlers survive a live-preview body swap (which
// replaces the activate/deactivate buttons) without needing rebind, and stay
// single (off before on) if this block ever runs again.
$(document).off('click.pidact').on('click.pidact', '[id^="hidden_pid_activate_"]', function(){
  sendPIDCommandAoT(this.name);
});
$(document).off('click.piddeact').on('click.piddeact', '[id^="hidden_pid_deactivate_"]', function(){
  sendPIDCommandAoT(this.name);
});
""",

    # Use the custom_options refresh_seconds, max_measure_age, decimal_places
    # => applied when calling getPidDataAoT() and repeatPidDataAoT()
    'widget_dashboard_js_ready_end': """
{% set refresh_sec = widget_options.get('refresh_seconds', 3.0) %}
{% set max_age     = widget_options.get('max_measure_age', 3600) %}
{% set dec_places  = widget_options.get('decimal_places', 1) %}

{% for each_pid in pid if each_pid.unique_id == widget_options['pid'] and each_pid.measurement.split(',')|length == 2 %}
getPidDataAoT('{{each_widget.unique_id}}','{{widget_options['pid']}}',{{max_age}},{{dec_places}});
repeatPidDataAoT('{{each_widget.unique_id}}','{{widget_options['pid']}}',{{refresh_sec}},{{max_age}},{{dec_places}});
{% else %}
getPidDataAoT('{{each_widget.unique_id}}','{{widget_options['pid']}}',{{max_age}},{{dec_places}});
{% endfor %}

{# ===== Graph: look up setpoint/measured-value/output measurement IDs stored in the DB → same chart as AoT_graph ===== #}
{% if widget_options.get('enable_graph', True) and widget_options['pid'] %}
  {% set pid_id = widget_options['pid'] %}
  {% set this_pid = table_pid.query.filter(table_pid.unique_id == pid_id).first() %}
  {# Setpoint: PID device channel 0 (measurement_type=setpoint) #}
  {% set sp_meas = table_device_measurements.query
        .filter(table_device_measurements.device_id == pid_id)
        .filter(table_device_measurements.channel == 0).first() %}
  {# Measured value: the input measurement the PID reads (pid.measurement = 'dev_id,meas_id') #}
  {% set act_dev = '' %}{% set act_mid = '' %}
  {% if this_pid and this_pid.measurement and ',' in this_pid.measurement %}
    {% set act_dev = this_pid.measurement.split(',')[0] %}
    {% set act_mid = this_pid.measurement.split(',')[1] %}
  {% endif %}
  {% set sp_mid = sp_meas.unique_id if sp_meas else '' %}

  {# Output: use the raise/lower output DEVICE measurements directly (avoid store_lower_as_negative ambiguity) #}
  {% set raise_dev_id = '' %}{% set lower_dev_id = '' %}
  {% if this_pid and this_pid.raise_output_id and ',' in this_pid.raise_output_id %}
    {% set raise_dev_id = this_pid.raise_output_id.split(',')[0] %}
  {% endif %}
  {% if this_pid and this_pid.lower_output_id and ',' in this_pid.lower_output_id %}
    {% set lower_dev_id = this_pid.lower_output_id.split(',')[0] %}
  {% endif %}
  {% set raise_out_meas = table_device_measurements.query.filter(table_device_measurements.device_id == raise_dev_id).filter(table_device_measurements.measurement == 'duration_time').first() if raise_dev_id else None %}
  {% set lower_out_meas = table_device_measurements.query.filter(table_device_measurements.device_id == lower_dev_id).filter(table_device_measurements.measurement == 'duration_time').first() if lower_dev_id else None %}
  {% set raise_out_mid = raise_out_meas.unique_id if raise_out_meas else '' %}
  {% set lower_out_mid = lower_out_meas.unique_id if lower_out_meas else '' %}
  {# lower sign: follow the PID store_lower_as_negative setting as-is #}
  {% set lower_sign = -1 if (this_pid and this_pid.store_lower_as_negative) else 1 %}

  {# Measured-value unit (shared with the setpoint) #}
  {% set val_meas_type = dict_measure_units[act_mid] if act_mid and act_mid in dict_measure_units else '' %}
  {% set val_unit_name = dict_units[val_meas_type]['name'] if val_meas_type and val_meas_type in dict_units else '' %}
  {% set val_unit = dict_units[val_meas_type]['unit'] if val_meas_type and val_meas_type in dict_units else '' %}

  {# Convert the x-axis duration #}
  {% set x_unit = widget_options.get('graph_x_axis_unit', 'hour') %}
  {% set x_dur  = widget_options.get('graph_x_axis_duration', 6) %}
  {% if x_unit == 'day' %}{% set x_min = x_dur * 1440 %}
  {% elif x_unit == 'minute' %}{% set x_min = x_dur %}
  {% else %}{% set x_min = x_dur * 60 %}{% endif %}
  {% set x_sec = x_min * 60 %}
  {% set xreset = widget_options.get('enable_xaxis_reset', True)|int %}
  {% set auto   = widget_options.get('enable_auto_refresh', True) %}

  // Idempotency guard for live-preview re-init (no page reload): destroy the
  // previous chart + clear this widget's stored data/live intervals before
  // rebuilding, so re-init doesn't leak a Highcharts instance or stack intervals.
  try {
    if (typeof widget !== 'undefined' && widget['{{each_widget.unique_id}}']) {
      widget['{{each_widget.unique_id}}'].destroy();
      delete widget['{{each_widget.unique_id}}'];
    }
  } catch (e) {}
  if (window._pid_intervals) {
    Object.keys(window._pid_intervals).forEach(function (k) {
      if (k.indexOf('{{each_widget.unique_id}}') === 0) {
        clearInterval(window._pid_intervals[k]);
        delete window._pid_intervals[k];
      }
    });
  }

widget['{{each_widget.unique_id}}'] = new Highcharts.StockChart({
  {# 전역 차트 시리즈 팔레트 — aot.config GRAPH_SERIES_PALETTE(_DARK), inject_variables 주입 #}
  {% if current_user.theme in dark_themes %}
  colors: {{ graph_series_palette_dark | tojson }},
  {% else %}
  colors: {{ graph_series_palette | tojson }},
  {% endif %}
  chart: {
    renderTo: 'container-synchronous-graph-{{each_widget.unique_id}}',
    zoomType: 'x',
    alignTicks: false,
    spacingTop: 16,
    spacingBottom: 16,
    resetZoomButton: { theme: { style: { display: 'none' } } },
    events: {
      render: function () {
        AoTChart.axisAdjust(this);
      },
      load: function () {
        {% if sp_mid %}
        getPastDataPidg('{{each_widget.unique_id}}', 0, '{{pid_id}}', 'pid', '{{sp_mid}}', {{x_sec}});
        {% if auto %}getLiveDataPidg('{{each_widget.unique_id}}', 0, '{{pid_id}}', 'pid', '{{sp_mid}}', {{x_min}}, {{xreset}}, {{refresh_sec}});{% endif %}
        {% endif %}
        {% if act_mid %}
        getPastDataPidg('{{each_widget.unique_id}}', 1, '{{act_dev}}', 'input', '{{act_mid}}', {{x_sec}});
        {% if auto %}getLiveDataPidg('{{each_widget.unique_id}}', 1, '{{act_dev}}', 'input', '{{act_mid}}', {{x_min}}, {{xreset}}, {{refresh_sec}});{% endif %}
        {% endif %}
        {% if raise_out_mid %}
        getPastDataPidg('{{each_widget.unique_id}}', 2, '{{raise_dev_id}}', 'output', '{{raise_out_mid}}', {{x_sec}}, 1);
        {% if auto %}getLiveDataPidg('{{each_widget.unique_id}}', 2, '{{raise_dev_id}}', 'output', '{{raise_out_mid}}', {{x_min}}, {{xreset}}, {{refresh_sec}}, 1);{% endif %}
        {% endif %}
        {% if lower_out_mid %}
        getPastDataPidg('{{each_widget.unique_id}}', 3, '{{lower_dev_id}}', 'output', '{{lower_out_mid}}', {{x_sec}}, {{lower_sign}});
        {% if auto %}getLiveDataPidg('{{each_widget.unique_id}}', 3, '{{lower_dev_id}}', 'output', '{{lower_out_mid}}', {{x_min}}, {{xreset}}, {{refresh_sec}}, {{lower_sign}});{% endif %}
        {% endif %}
      }
    }
  },
  title: { text: '' },
  legend: {
    enabled: true,
    useHTML: true,
    labelFormatter: function () {
      let lastVal = this.yData[this.yData.length - 1];
      let unit = this.tooltipOptions.valueSuffix || '';
      return this.name + ': <b>' + Highcharts.numberFormat(lastVal, 2) + unit + '</b>';
    }
  },
  xAxis: {
    type: 'datetime',
    ordinal: false,
    labels: {
      style: { color: 'var(--aot-color-text-secondary, #666666)' }
    },
    events: {
      afterSetExtremes: function(e) {
        if (e.trigger) {
          _aot_pid_user_range['{{each_widget.unique_id}}'] = true;
        }
      }
    }
  },
  yAxis: [
    AoTChart.unitYAxis({
      id: 'val',
      unit: '{% if val_unit %}{{val_unit}}{% else %}{{val_unit_name}}{% endif %}',
      extra: { labels: { format: '{value}', x: -8, style: { fontSize: '1em', color: 'var(--aot-color-text-secondary, #666666)' } } }
    }),
    AoTChart.unitYAxis({
      id: 'out',
      unit: 's',
      extra: { gridLineWidth: 0, labels: { format: '{value}', x: -8, style: { fontSize: '1em', color: 'var(--aot-color-text-secondary, #666666)' } } }
    })
  ],
  exporting: { enabled: false },
  navigator: { enabled: false },
  scrollbar: { enabled: false },
  rangeSelector: {
    enabled: true,
    inputEnabled: false,
    labelStyle: { color: 'var(--aot-color-text-secondary, #666666)' },
    buttonTheme: {
      style: { color: 'var(--aot-color-text-secondary, #666666)' },
      states: {
        hover: { style: { color: 'var(--aot-color-text-primary, #333333)' } },
        select: { style: { color: 'var(--aot-color-text-primary, #333333)' } },
        disabled: { style: { color: 'var(--aot-color-text-secondary, #cccccc)' } }
      }
    },
    buttons: [
      { count: 5,  type: 'minute', text: '{{_("5m")}}' },
      { count: 30, type: 'minute', text: '{{_("30m")}}' },
      { count: 1,  type: 'hour',   text: '{{_("1h")}}' },
      { count: 6,  type: 'hour',   text: '{{_("6h")}}' },
      { count: 1,  type: 'day',    text: '{{_("1d")}}' },
      { type: 'all', text: '{{_("All")}}' }
    ],
    selected: 3
  },
  credits: { enabled: false },
  tooltip: {
    shared: true,
    useHTML: true,
    formatter: function () {
      let s = '<b>' + AoTChart.formatDateTime(this.x) + '</b>';
      $.each(this.points, function (i, point) {
        s += '<br/><span style="color:' + point.color + '">\\u25CF</span> '
           + point.series.name + ': ' + AoTChart.formatPointValue(point);
      });
      return s;
    }
  },
  plotOptions: {
    column: { maxPointWidth: 10 },
    series: { connectNulls: true, states: { hover: { enabled: false } } }
  },
  series: [
    {
      name: '{{_('Setpoint')}}', type: 'line', yAxis: 'val',
      dataGrouping: { enabled: true, approximation: 'average', groupPixelWidth: 2 },
      tooltip: { valueSuffix: '{% if val_unit %} {{val_unit}}{% endif %}', valueDecimals: {{dec_places}} },
      data: []
    },
    {
      name: '{{_('Actual')}}', type: 'line', yAxis: 'val',
      dataGrouping: { enabled: true, approximation: 'average', groupPixelWidth: 2 },
      tooltip: { valueSuffix: '{% if val_unit %} {{val_unit}}{% endif %}', valueDecimals: {{dec_places}} },
      data: []
    },
    {
      name: '{{_('Raise')}}', type: 'column', yAxis: 'out',
      dataGrouping: { enabled: true, approximation: 'max', groupPixelWidth: 4 },
      tooltip: { valueSuffix: ' s', valueDecimals: 1 },
      data: []
    },
    {
      name: '{{_('Lower')}}', type: 'column', yAxis: 'out',
      dataGrouping: { enabled: true, approximation: 'min', groupPixelWidth: 4 },
      tooltip: { valueSuffix: ' s', valueDecimals: 1 },
      data: []
    }
  ]
});
{% endif %}
"""
}

logger.info("widget_AoT_PID.py with custom_options integrated, official endpoints, UI partially modified")