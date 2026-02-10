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

from aot.databases.models import Conditional, CustomController, Function, Input, Trigger
from aot.aot_client import DaemonControl
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

def controller_state(unique_id):
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"

    input_ = Input.query.filter(Input.unique_id == unique_id).first()
    function = Function.query.filter(Function.unique_id == unique_id).first()
    customfunction = CustomController.query.filter(CustomController.unique_id == unique_id).first()
    trigger = Trigger.query.filter(Trigger.unique_id == unique_id).first()
    conditional = Conditional.query.filter(Conditional.unique_id == unique_id).first()

    controller = None
    if input_:
        controller = input_
    elif function:
        controller = function
    elif customfunction:
        controller = customfunction
    elif trigger:
        controller = trigger
    elif conditional:
        controller = conditional

    if controller:
        return jsonify({"status": "Success", "state": controller.is_activated})

    return jsonify({"status": "Error", "state": f"Could not find Controller with ID {unique_id}"})


def controller_activate_deactivate(unique_id, state):
    """Activate/Deactivate Controller (Input/Function/Trigger/Conditional/CustomController)."""
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to manipulate Controller'

    input_ = Input.query.filter(Input.unique_id == unique_id).first()
    function = Function.query.filter(Function.unique_id == unique_id).first()
    customfunction = CustomController.query.filter(CustomController.unique_id == unique_id).first()
    trigger = Trigger.query.filter(Trigger.unique_id == unique_id).first()
    conditional = Conditional.query.filter(Conditional.unique_id == unique_id).first()

    controller = None
    if input_:
        controller = input_
    elif function:
        controller = function
    elif customfunction:
        controller = customfunction
    elif trigger:
        controller = trigger
    elif conditional:
        controller = conditional

    if not controller or not unique_id or state not in ['activate', 'deactivate']:
        return "Invalid inputs: Controller ID or State"

    daemon = DaemonControl()
    if state == 'activate':
        controller.is_activated = True
        controller.save()
        _, return_str = daemon.controller_activate(unique_id)
        return return_str
    elif state == 'deactivate':
        controller.is_activated = False
        controller.save()
        _, return_str = daemon.controller_deactivate(unique_id)
        return return_str

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_controller_act_deact',
    'widget_name': 'AoT 컨트롤러 스위치',
    'widget_library': '',
    'no_class': True,

    'message': '컨트롤러를 켜고 끌 수 있는 스위치.',

    'widget_width': 24,
    'widget_height': 5,

    'endpoints': [
        ("/controller_state/<unique_id>", "controller_state", controller_state, ["GET"]),
        ("/controller_activate_deactivate/<unique_id>/<state>", "controller_activate_deactivate", controller_activate_deactivate, ["GET"])
    ],

    'custom_options': [
        {
            'id': 'controller',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Input',
                'Function',
                'Conditional',
                'Trigger'
                # PID, CustomController 등은 필요시 확장 가능
            ],
            'name': lazy_gettext('컨트롤러'),
            'phrase': lazy_gettext('컨트롤러를 선택하세요.')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 3.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': '{} ({})'.format(lazy_gettext("새로고침"), lazy_gettext("초")),
            'phrase': '위젯을 주기적으로 새로 고침하는 간격 (초)'
        }
    ],

    # -------------------- HEAD (CSS) --------------------
    'widget_dashboard_head': """
    """,

    # -------------------- TITLE BAR --------------------
    'widget_dashboard_title_bar': """
{%- if each_widget.name %}
  <span>{{ each_widget.name }}</span>
{%- else %}
  <span>컨트롤러 스위치</span>
{%- endif %}
""",

    # -------------------- BODY --------------------
    'widget_dashboard_body': """
  <div class="frame-aot inactive-background"
      id="frame_aot_{{each_widget.unique_id}}">
    
    <div class="row-aot-1-1">
      <div class="col-aot-1">
        <span class="prt-text" id="aot_controller_txt_{{each_widget.unique_id}}">
          대기중
        </span>
      </div>

      <div class="col-aot-2">
        <label class="btn-toggle">
          <input type="checkbox"
                 id="aot_controller_toggle_{{each_widget.unique_id}}"
                 class="controller-toggle-input btn-toggle-input"
                 name="{{widget_options['controller']}}">
          <span class="btn-toggle-slider">
            <span class="btn-toggle-thumb"></span>
          </span>
        </label>
      </div>
    </div>

  </div>
""",

    # -------------------- JAVASCRIPT --------------------
    'widget_dashboard_js': """
  function printControllerErrorAoT(wid){
    // 화면 업데이트를 제거하고, 오류를 콘솔 및 서버 로그로 전송합니다.
    console.error("AoT Controller Error on widget:", wid);
    
    // 선택사항: AJAX로 서버 로그 엔드포인트에 오류 정보를 전송
    $.ajax({
      type: "POST",
      url: "/log_error",  // 서버에 로그를 수신하는 엔드포인트 (구현 필요)
      data: JSON.stringify({
        widget: "AoT_controller",
        widget_id: wid,
        error: "(Error)"
      }),
      contentType: "application/json",
      success: function(){},
      error: function(){ console.error("Error logging failed."); }
    });
  }

  // 컨트롤러 상태 확인 (1회)
  function getControllerStateAoT(wid, dev_id){
    $.ajax({
      url: "/controller_state/" + dev_id,
      type: "GET",
      success: function(data, textStatus, jqXHR){
        if(data.status === "Error"){
          printControllerErrorAoT(wid);
        } else {
          let isActive = data.state; // data.state: true or false
          updateControllerUIAoT(wid, isActive);
        }
      },
      error: function(jqXHR, textStatus, errorThrown){
        printControllerErrorAoT(wid);
      }
    });
  }

  // UI 갱신 (토글/배경색/문구)
  function updateControllerUIAoT(wid, isActive){
    let toggler = document.getElementById("aot_controller_toggle_"+wid);
    let contDiv = document.getElementById("frame_aot_"+wid);
    let stateSpan = document.getElementById("aot_controller_txt_"+wid);
    
    if(!toggler || !contDiv || !stateSpan) return;

    contDiv.classList.remove("pause-background",
                            "active-background",
                            "inactive-background");

    if(isActive){
      toggler.checked = true;
      contDiv.classList.add("active-background");
      stateSpan.innerHTML = "작동중";
    } else {
      toggler.checked = false;
      contDiv.classList.add("inactive-background");
      stateSpan.innerHTML = "대기중";
    }
  }

// 컨트롤러 On/Off
function setControllerStateAoT(dev_id, newState, wid){
  $.ajax({
    url: "/controller_activate_deactivate/"+dev_id+"/"+newState,
    type: "GET",
    success: function(res){
      // Toastr 메시지 제거됨
      // (원하면 console.log로 대체)
      console.log("Controller set success:", res, "dev_id:", dev_id, "action:", newState, "wid:", wid);

      // 명령 후 재확인 (1회)
      getControllerStateAoT(wid, dev_id);
    },
    error: function(jqXHR, textStatus, errorThrown){
      console.error("Controller set error:", textStatus, errorThrown);
      printControllerErrorAoT(wid);
    }
  });
}

// ---------------------- 복원된 "주기적 상태 갱신" 로직 ----------------------
function repeatControllerStateAoT(wid, dev_id, refSec){
  // refresh_seconds <= 0이면 자동 갱신 X
  if(!refSec || refSec <= 0){
    console.log("[AoT Controller] Auto-refresh disabled for widget:", wid);
    return;
  }

  console.log("[AoT Controller] Auto-refresh every", refSec, "seconds (widget:", wid, ")");
  setInterval(function(){
    getControllerStateAoT(wid, dev_id);
  }, refSec * 1000);
}
""",

    # -------------------- JS READY --------------------
    'widget_dashboard_js_ready': """
$(document).ready(function() {
  $('.controller-toggle-input').off('change.controller').on('change.controller', function(){
    const btn = $(this);
    const dev_id = btn.attr('name');
    const wid = btn.attr('id').replace('aot_controller_toggle_', '');
    const isOn = btn.is(':checked');

    console.log("Toggle changed:", { wid, dev_id, isOn });

    if (!dev_id) {
      console.error("No Controller ID found for widget:", wid);
      return;
    }

    const action = isOn ? 'activate' : 'deactivate';
    setControllerStateAoT(dev_id, action, wid);
  });
});
""",

    # -------------------- JS READY END --------------------
    'widget_dashboard_js_ready_end': """
  $('#aot_controller_toggle_{{each_widget.unique_id}}')
  .attr('name', '{{widget_options['controller']}}');

  getControllerStateAoT('{{each_widget.unique_id}}', '{{widget_options['controller']}}');

  repeatControllerStateAoT(
    '{{each_widget.unique_id}}',
    '{{widget_options['controller']}}',
    {{widget_options['refresh_seconds']}}
  );
"""
}

#
# Optionally, you can add the following log line manually inside controller_activate_deactivate:
# logger.info(f"[AoT_controller] Toggle requested: {unique_id} → {state}")