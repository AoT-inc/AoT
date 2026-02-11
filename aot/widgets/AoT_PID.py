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
#  Last modified: 2025-04-21

import logging
from flask import jsonify
from flask_babel import lazy_gettext
from flask_login import current_user

from aot.databases.models import Conversion, DeviceMeasurements, PID
from aot.aot_client import DaemonControl
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.influx import read_influxdb_single
from aot.utils.system_pi import return_measurement_info, str_is_float

logger = logging.getLogger(__name__)

def return_point_timestamp(dev_id, unit, period, measurement=None, channel=None):
    """데이터 조회 후 (timestamp, value) 형태로 반환"""
    last_data = read_influxdb_single(
        dev_id, unit, channel,
        measure=measurement, value='LAST',
        duration_sec=period
    )
    if not last_data:
        return [None, None]
    return last_data

def last_data_pid(pid_id, input_period):
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
        data_dict = {
            'activated': pid.is_activated,
            'paused': pid.is_paused,
            'held': pid.is_held,
            'pid_p_value': p_val,
            'pid_i_value': i_val,
            'pid_d_value': d_val,
            'pid_pid_value': pid_sum_val,
            'duration_time': return_point_timestamp(pid_id, 's', input_period, measurement='duration_time')
        }
        data_dict['actual'] = return_point_timestamp(dev_id, a_unit, input_period, measurement=a_measurement, channel=a_channel)
        return jsonify(data_dict)
    except Exception as ex:
        logger.error(f"Error in last_data_pid(): {ex}", exc_info=True)
        return '', 204

def pid_mod_unique_id(unique_id, state):
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to manipulate PID'
    if not unique_id or unique_id == 'None':
        return "No PID selected"
    pid = PID.query.filter(PID.unique_id == unique_id).first()
    if not pid:
        return "No PID found"
    daemon = DaemonControl()
    try:
        if state == 'activate':
            pid.is_activated = True
            pid.is_paused = False
            pid.is_held = False
            pid.save()
            _, msg = daemon.controller_activate(pid.unique_id)
            return msg
        elif state == 'deactivate':
            pid.is_activated = False
            pid.is_paused = False
            pid.is_held = False
            pid.save()
            _, msg = daemon.controller_deactivate(pid.unique_id)
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

############################################################################
# 아래 WIDGET_INFORMATION(custom_options) 변경 없음.
# 단, 실제 UI/JS에서 custom_options를 반영하도록 개선함.
############################################################################
WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_pid',
    'widget_name': 'AoT PID',
    'widget_library': 'controller',
    'no_class': True,

    'message': 'Displays and allows control of a PID Controller.',

    'widget_width': 24,
    'widget_height': 7,

    'endpoints': [
        ("/last_pid/<pid_id>/<input_period>", "last_pid", last_data_pid, ["GET"]),
        ("/pid_mod_unique_id/<unique_id>/<state>", "pid_mod_unique_id", pid_mod_unique_id, ["GET"])
    ],

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('장치 설정')
        },
        {
            'id': 'pid',
            'type': 'select_device',
            'default_value': '',
            'options_select': ['PID'],
            'name': lazy_gettext('PID 컨트롤러'),
            'phrase': lazy_gettext('제어할 PID 컨트롤러를 선택하세요.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('실행 설정')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 3600,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('최대유효시간'), lazy_gettext('초')),
            'phrase': lazy_gettext('사용할 측정값의 최대 유효 시간')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 3.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("새로고침"), lazy_gettext("초")),
            'phrase': lazy_gettext('위젯을 새로 고침하는 간격')
        },
        {
            'type': 'header',
            'name': lazy_gettext('표시 설정')
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('타임스탬프'),
            'phrase': lazy_gettext('위젯에 타임스탬프를 표시 합니다.')
        },
        {
            'id': 'font_em_timestamp',
            'type': 'float',
            'default_value': 1.0,
            'name': lazy_gettext('타임스탬프 문자 크기'),
            'phrase': lazy_gettext('타임스탬프 문자 크기를 설정 합니다.')
        },
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('소수점'),
            'phrase': lazy_gettext('숫자의 소수점 자리수를 정할 수 있습니다.')
        },
        {
            'id': 'enable_status',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('상태표시'),
            'phrase': lazy_gettext('현재 제어장치의 상태를 표시 합니다.')
        },
        {
            'id': 'show_pid_info',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('PID 정보'),
            'phrase': lazy_gettext('현재 PID 설정값 보기')
        },
        {
            'id': 'show_set_setpoint',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('목표'),
            'phrase': lazy_gettext('목표 값을 설정할 수 있습니다.')
        }
    ],

  # ------------------ HEAD (CSS) ------------------
  'widget_dashboard_head': """<!-- No head content -->""",

  # ------------------ TITLE BAR ------------------
  'widget_dashboard_title_bar': """
  {%- if widget_options['enable_status'] -%}
    <span id="text-pid-state-{{each_widget.unique_id}}"></span>{{' '}}
  {%- else -%}
    <span style="display: none" id="text-pid-state-{{each_widget.unique_id}}"></span>
  {%- endif -%}

  <span style="padding-right: 0.5em"> {{each_widget.name}}</span>
  """,

  # ------------------ BODY ------------------
  'widget_dashboard_body': """
{% set this_pid = table_pid.query.filter(table_pid.unique_id == widget_options['pid']).first() %}

<div class="frame-aot" id="pid_container_{{each_widget.unique_id}}">
  <div class="row-aot-1">
    <div class="col-aot-1">
      <div class="prt-text">
        <div class="pid-aot-timestamp">
          {% if widget_options.get('enable_timestamp',True) %}
            지난 작동: 
            <span 
              id="duration_time-{{each_widget.unique_id}}">
            </span>초,
            {% if widget_options.get('enable_timestamp',True) %}
            <span
              id="duration_time-{{each_widget.unique_id}}-timestamp">
            </span>
            {% endif %}
            <span 
              id="duration_time-{{each_widget.unique_id}}">
            </span>
          {% endif %}
        </div>
        {% if widget_options.get('show_pid_info',True) %}
        <div class="pid-info">
          PID =
          <span  
            id="pid_pid_value-{{each_widget.unique_id}}"></span>
        </div>
        {% else %}
        <div class="pid-aot-hidden">
        </div>
        {% endif %}
      </div>
    </div>
    <!-- 토글 버튼 -->
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

  <!-- 2행: 컨트롤 영역 -->
  <div class="row-aot-2">
    <div class="prt-text-inline">
      현재: <span id="actual-{{each_widget.unique_id}}"></span>
    </div>
    <div class="btn-aot-pid">
    {% if widget_options.get('show_set_setpoint',True) %}
      {% if this_pid %}
        <input type="text"
               id="pid_setpoint_{{widget_options['pid']}}"
               class="input-aot-pid"
               placeholder="목표"
               value="{{this_pid.setpoint}}">
      {% else %}
        <input type="text"
               id="pid_setpoint_{{widget_options['pid']}}"
               class="input-aot-pid"
               placeholder="목표">
      {% endif %}
      <button id="btn_pid_set_{{each_widget.unique_id}}"
              name="{{widget_options['pid']}}/set_setpoint_pid|"
              class="btn-aot-pid-sm"
              onclick="setSetpointAoT('{{each_widget.unique_id}}')">
        목표
      </button>
    {% else %}
      <input type="text"
             id="pid_setpoint_{{widget_options['pid']}}"
             style="display:none;">
      <button id="btn_pid_set_{{each_widget.unique_id}}"
              style="display:none;"></button>
    {% endif %}

      <button id="btn_pid_pause_{{each_widget.unique_id}}"
              name="{{widget_options['pid']}}/pause"
              class="btn-aot-pid-sm"
              onclick="sendPIDCommandAoT(this.name)">
        중지
      </button>
      <button id="btn_pid_hold_{{each_widget.unique_id}}"
              name="{{widget_options['pid']}}/hold"
              class="btn-aot-pid-sm"
              onclick="sendPIDCommandAoT(this.name)">
        고정
      </button>
      <button id="btn_pid_resume_{{each_widget.unique_id}}"
              name="{{widget_options['pid']}}/resume"
              class="btn-aot-pid-resume"
              style="display:none;"
              onclick="sendPIDCommandAoT(this.name)">
        복귀
      </button>
    </div>
  </div>
</div>

<!-- 숨김 버튼 -->
<input type="button"
       id="hidden_pid_activate_{{each_widget.unique_id}}"
       style="display:none;"
       name="{{widget_options['pid']}}/activate"
       value="activate"/>
<input type="button"
       id="hidden_pid_deactivate_{{each_widget.unique_id}}"
       style="display:none;"
       name="{{widget_options['pid']}}/deactivate"
       value="deactivate"/>
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
      // 추가 UI 업데이트가 필요하면 여기서 처리합니다.
    },
    error: function(err) {
      console.error("Error:", err);
    }
  });
}

function printPidValueAoT(data, nm, wid, decs) {
  if(data[nm] && data[nm][1] != null) {
    let val = parseFloat(data[nm][1]).toFixed(decs);
    $("#"+nm+"-"+wid).text(val);
  } else {
    $("#"+nm+"-"+wid).text("N/A");
  }
  // 타임스탬프 표시 여부 (enable_timestamp)
  if(data[nm] && data[nm][0]) {
    if(document.getElementById(nm + "-" + wid + "-timestamp")) {
      document.getElementById(nm + "-" + wid + "-timestamp").innerHTML = epoch_to_timestamp(data[nm][0]*1000);
    }
  }
}

function printPidErrorAoT(wid) {
  $("#actual-"+wid).text("ERR");
  $("#duration_time-"+wid).text("ERR");
  if(document.getElementById("duration_time-"+wid+"-timestamp")) {
    document.getElementById("duration_time-"+wid+"-timestamp").innerHTML = "";
  }
  $("#pid_p_value-"+wid).text("ERR");
  $("#pid_i_value-"+wid).text("ERR");
  $("#pid_d_value-"+wid).text("ERR");
  $("#pid_pid_value-"+wid).text("ERR");

  let container = document.getElementById("pid_container_"+wid);
  container.classList.remove("pause-background","active-background","inactive-background");
  container.classList.add("inactive-background");
}

function getPidDataAoT(wid, pidid, max_age, decs) {
  if(!pidid || pidid==='None'){
    printPidErrorAoT(wid);
    toastr.error("No PID selected");
    return;
  }
  $.ajax("/last_pid/"+pidid+"/"+max_age, {
    success:function(data, txtStatus, jqXHR){
      if(jqXHR.status===204) {
        printPidErrorAoT(wid);
        toastr.error("No PID found or no measurement");
        return;
      }
      if(data.actual){
        printPidValueAoT(data, "actual", wid, decs);
      }
      if(data.duration_time){
        printPidValueAoT(data, "duration_time", wid, decs);
      }
      if(data.pid_p_value && data.pid_i_value && data.pid_d_value && data.pid_pid_value) {
        printPidValueAoT(data, "pid_p_value", wid, 1);
        printPidValueAoT(data, "pid_i_value", wid, 1);
        printPidValueAoT(data, "pid_d_value", wid, 1);
        printPidValueAoT(data, "pid_pid_value", wid, 1);
      }

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
      printPidErrorAoT(wid);
      toastr.error("Error: " + JSON.stringify(err));
    }
  });
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
    },
    error: function(err) {
      console.error("Error:", err);
    }
  });
}

function repeatPidDataAoT(wid, pidid, refsec, max_age, decs) {
  setInterval(function(){
    getPidDataAoT(wid, pidid, max_age, decs);
  }, refsec*1000);
}
""",

    'widget_dashboard_js_ready': """
$('[id^="hidden_pid_activate_"]').click(function(){
  sendPIDCommandAoT(this.name);
});
$('[id^="hidden_pid_deactivate_"]').click(function(){
  sendPIDCommandAoT(this.name);
});
""",

    # custom_options인 refresh_seconds, max_measure_age, decimal_places 활용
    # => getPidDataAoT()와 repeatPidDataAoT() 호출 시 적용
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
"""
}

logger.info("widget_AoT_PID.py with custom_options integrated, official endpoints, UI partially modified")