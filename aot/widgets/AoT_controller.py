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
#  Last modified: 2025-04-21

import logging
from flask import jsonify
from flask_babel import lazy_gettext
from flask_login import current_user

from aot.databases.models import Conditional, CustomController, Function, Input, Trigger
from aot.aot_client import DaemonControl
from aot.aot_flask.access import scope
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

def aot_controller_state(unique_id):
    """Query the activation state of any controller (Input/Function/Trigger/Conditional/CustomController).

    @phase active
    @stability stable
    @dependency Input, Function, CustomController, Trigger, Conditional
    """
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


def aot_controller_activate_deactivate(unique_id, state):
    """Activate or deactivate any controller by unique_id.

    @phase active
    @stability stable
    @dependency DaemonControl
    """
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to manipulate Controller'

    # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
    if not scope.can_operate_device(unique_id):
        return 'ERROR: ' + scope.deny_message()

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
    'widget_name': lazy_gettext('AoT Controller Switch'),
    'widget_library': '',
    'no_class': True,

    'message': lazy_gettext('Switch to turn controllers on and off.'),

    'widget_width': 24,
    'widget_height': 5,

    # On mobile (<=768px), take the whole row instead of sharing it with a
    # second widget. Each row is a controller name plus its switch; at half a
    # phone row the name wraps away from the switch it belongs to, which is
    # exactly the pairing a user must not misread before flipping it.
    'mobile_full_width': True,

    'endpoints': [
        # Route URL, route endpoint name, view function, methods
        ("/aot_controller_state/<unique_id>", "aot_controller_state", aot_controller_state, ["GET"]),
        ("/aot_controller_activate_deactivate/<unique_id>/<state>", "aot_controller_activate_deactivate", aot_controller_activate_deactivate, ["GET"])
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
                # PID, CustomController, etc. can be added here if needed
            ],
            'name': lazy_gettext('Controller'),
            'phrase': lazy_gettext('Select the controller.')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 3.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Frequency of widget refresh (seconds)')
        }
    ],

    # -------------------- HEAD (CSS) --------------------
    'widget_dashboard_head': """
    """,

    # -------------------- TITLE BAR --------------------
    'widget_dashboard_title_bar': """
{#- 이름은 셸이 렌더한다(dashboard_entry.html) — 여기는 이름 옆 부가물 전용.
    예전에 있던 "이름이 비면 'Controller Switch' 로 대체" 는 뺐다: 제목 span 이
    둘이 되어 라이브 미리보기가 이름을 빈 쪽에 써 넣으면 두 이름이 겹쳤고,
    이름을 비워 둔 위젯을 24종은 그냥 비워 두는데 이 하나만 달랐다. -#}
""",

    # -------------------- BODY --------------------
    'widget_dashboard_body': """
    <style>
    /* Controller widget UI improvements */
    #frame_aot_{{each_widget.unique_id}} .col-aot-2 {
      width: 60px !important;
    }
    </style>
  <div class="frame-aot inactive-background"

      id="frame_aot_{{each_widget.unique_id}}">
    
    <div class="row-aot-1-1">
      <div class="col-aot-1">
        <span class="prt-text" id="aot_controller_txt_{{each_widget.unique_id}}">
          {{_('Inactive')}}
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
    // Skip the screen update and send the error to the console and server log.
    console.error("AoT Controller Error on widget:", wid);

    // Optional: send the error info to the server log endpoint via AJAX
    $.ajax({
      type: "POST",
      url: "/log_error",  // server-side endpoint that receives the log (to be implemented)
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

  // Check controller state (once)
  function getControllerStateAoT(wid, dev_id){
    $.ajax({
      url: "/aot_controller_state/" + dev_id,
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

  // Update UI (toggle/background color/text)
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
      stateSpan.innerHTML = "{{_('Active')}}";
    } else {
      toggler.checked = false;
      contDiv.classList.add("inactive-background");
      stateSpan.innerHTML = "{{_('Inactive')}}";
    }
  }

// Controller On/Off
function setControllerStateAoT(dev_id, newState, wid){
  $.ajax({
    url: "/aot_controller_activate_deactivate/"+dev_id+"/"+newState,
    type: "GET",
    success: function(res){
      // Toastr message removed
      // (replace with console.log if desired)
      console.log("Controller set success:", res, "dev_id:", dev_id, "action:", newState, "wid:", wid);

      // Re-check after the command (once)
      getControllerStateAoT(wid, dev_id);
    },
    error: function(jqXHR, textStatus, errorThrown){
      console.error("Controller set error:", textStatus, errorThrown);
      printControllerErrorAoT(wid);
    }
  });
}

// ---------------------- Restored "periodic state refresh" logic ----------------------
function repeatControllerStateAoT(wid, dev_id, refSec){
  // If refresh_seconds <= 0, disable auto-refresh
  if(!refSec || refSec <= 0){
    console.log("[AoT Controller] Auto-refresh disabled for widget:", wid);
    return;
  }

  console.log("[AoT Controller] Auto-refresh every", refSec, "seconds (widget:", wid, ")");
  window._aotctrl_intervals = window._aotctrl_intervals || {};
  if (window._aotctrl_intervals[wid]) { clearInterval(window._aotctrl_intervals[wid]); }
  window._aotctrl_intervals[wid] = setInterval(function(){
    getControllerStateAoT(wid, dev_id);
  }, refSec * 1000);
}
""",

    # -------------------- JS READY --------------------
    'widget_dashboard_js_ready': """
$(document).ready(function() {
  // Document-delegated so it keeps working after a live-preview body swap (which
  // replaces the toggle input) without needing js_ready to re-run.
  $(document).off('change.controller').on('change.controller', '.controller-toggle-input', function(){
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