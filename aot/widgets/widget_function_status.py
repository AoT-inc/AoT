# coding=utf-8
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
import json
import logging

from flask import jsonify
from flask import request
from flask_babel import lazy_gettext
from flask_login import current_user
from werkzeug.datastructures import MultiDict

from aot.aot_flask.access import scope
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.databases.models import Conditional
from aot.databases.models import CustomController
from aot.databases.models import PID
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.functions import parse_function_information
from aot.utils.system_pi import parse_custom_option_values

logger = logging.getLogger(__name__)


# Only these custom_options types can be shown as a toggle switch or a value/text
# input in the widget's detail modal (matches the field kinds requested for this
# widget: slide toggle for bool, value/text input for everything else supported).
EDITABLE_OPTION_TYPES = ('bool', 'float', 'integer', 'text')

# PID doesn't store its tunables in a custom_options JSON blob (unlike Function),
# it uses fixed model columns, so its "schema" is declared here instead. Labels
# match AoT_PID.py's own detail-settings modal wording exactly (same msgids;
# "P (Kp)"/"I (Ki)"/"D (Kd)" are left untranslated there too, like other
# control-theory abbreviations elsewhere in the app).
PID_OPTION_FIELDS = (
    ('setpoint', 'float', lazy_gettext('Setpoint')),
    ('p', 'float', 'P (Kp)'),
    ('i', 'float', 'I (Ki)'),
    ('d', 'float', 'D (Kd)'),
    ('period', 'float', lazy_gettext('Period')),
    ('band', 'float', lazy_gettext('Band')),
    ('integrator_min', 'float', lazy_gettext('Integrator Min')),
    ('integrator_max', 'float', lazy_gettext('Integrator Max')),
)


def _resolve_controller(unique_id):
    """The widget's 'function_id' option can point at a Function, Conditional, or
    PID (see custom_options/function_id below) but only stores the unique_id, not
    which table it came from, so it has to be looked up the same way the rest of
    the app does it (e.g. AoT_controller.py)."""
    controller = CustomController.query.filter(CustomController.unique_id == unique_id).first()
    if controller:
        return 'function', controller
    controller = Conditional.query.filter(Conditional.unique_id == unique_id).first()
    if controller:
        return 'conditional', controller
    controller = PID.query.filter(PID.unique_id == unique_id).first()
    if controller:
        return 'pid', controller
    return None, None


def function_status_options_get(unique_id):
    if not current_user.is_authenticated:
        return "Not logged in", 401

    controller_type, controller = _resolve_controller(unique_id)
    if not controller:
        return jsonify({'status': 'error', 'message': 'Not found'}), 404

    if controller_type == 'function':
        dict_controllers = parse_function_information()
        dev_info = dict_controllers.get(controller.device, {})
        schema = dev_info.get('custom_options', [])
        current_values = parse_custom_option_values(
            controller, dict_controllers).get(controller.unique_id, {})
        mod_without_deactivate = bool(dev_info.get('modify_settings_without_deactivating'))
        editable = (not controller.is_activated) or mod_without_deactivate

        options = []
        for each_option in schema:
            if 'id' not in each_option or each_option.get('type') not in EDITABLE_OPTION_TYPES:
                continue
            options.append({
                'id': each_option['id'],
                'type': each_option['type'],
                'name': str(each_option.get('name', each_option['id'])),
                'phrase': str(each_option.get('phrase', '')),
                'value': current_values.get(each_option['id'], each_option.get('default_value')),
            })

        return jsonify({
            'status': 'ok',
            'controller_type': controller_type,
            'name': controller.name,
            'is_activated': bool(controller.is_activated),
            'editable': editable,
            'options': options,
        })

    if controller_type == 'pid':
        options = [{
            'id': field_id,
            'type': field_type,
            # Matches AoT_PID.py's own modal: "Period (s)", not a separate msgid.
            'name': str(field_name) + (' (s)' if field_id == 'period' else ''),
            'phrase': '',
            'value': getattr(controller, field_id),
        } for field_id, field_type, field_name in PID_OPTION_FIELDS]

        return jsonify({
            'status': 'ok',
            'controller_type': controller_type,
            'name': controller.name,
            'is_activated': bool(controller.is_activated),
            'editable': True,
            'options': options,
        })

    # Conditional has a custom_options column but no module declares a schema for
    # it anywhere in the app (unlike Function), so there's nothing to render here.
    return jsonify({
        'status': 'ok',
        'controller_type': controller_type,
        'name': controller.name,
        'is_activated': bool(controller.is_activated),
        'editable': False,
        'options': [],
    })


def function_status_options_post(unique_id):
    if not current_user.is_authenticated:
        return "Not logged in", 401
    if not user_has_permission('edit_controllers'):
        return jsonify({'status': 'error', 'message': 'Insufficient user permissions'}), 403

    # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
    if not scope.can_operate_device(unique_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403

    controller_type, controller = _resolve_controller(unique_id)
    if not controller or controller_type != 'function':
        return jsonify({
            'status': 'error',
            'message': str(lazy_gettext('This function type has no editable options.'))
        }), 400

    data = request.get_json(silent=True) or {}
    values = data.get('values', {})
    if not isinstance(values, dict):
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

    dict_controllers = parse_function_information()
    if controller.device not in dict_controllers:
        # custom_options_return_json() would otherwise wipe custom_options to {}
        # for an unrecognized device — bail out instead of saving anything.
        return jsonify({'status': 'error', 'message': 'Unknown function type'}), 400
    dev_info = dict_controllers[controller.device]
    schema = dev_info.get('custom_options', [])
    mod_without_deactivate = bool(dev_info.get('modify_settings_without_deactivating'))
    if controller.is_activated and not mod_without_deactivate:
        # Same wording (and msgid) as the full Function edit page's own warning
        # for this exact situation (custom_function_options.html).
        return jsonify({
            'status': 'error',
            'message': str(lazy_gettext(
                'This controller is active. Deactivate it before saving changes, '
                'or they will not be applied.'))
        }), 400

    editable_ids = {
        each['id'] for each in schema
        if 'id' in each and each.get('type') in EDITABLE_OPTION_TYPES
    }

    # Reuse the same request_form-shaped parsing/validation (constraints_pass,
    # type coercion, etc.) that the full Function edit page uses, so this mini
    # editor can't drift from the normal save behavior.
    payload = MultiDict()
    for key, val in values.items():
        if key not in editable_ids:
            continue
        payload.add(key, '' if val is None else str(val))

    try:
        custom_options_presave = json.loads(controller.custom_options) if controller.custom_options else {}
    except Exception:
        custom_options_presave = {}

    errors = []
    errors, custom_options_json = custom_options_return_json(
        errors, dict_controllers,
        request_form=payload,
        mod_dev=controller,
        device=controller.device,
        use_defaults=False,
        custom_options=custom_options_presave)

    if errors:
        return jsonify({'status': 'error', 'message': '; '.join(errors)}), 400

    controller.custom_options = custom_options_json
    controller.save()

    return jsonify({'status': 'ok'})


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_function_status',
    'widget_name': lazy_gettext('Function Status'),
    'widget_library': '',
    'no_class': True,

    'message': lazy_gettext('Displays the status of a Function (if supported).'),

    'widget_width': 7,
    'widget_height': 10,

    'endpoints': [
        ("/function_status_options/<unique_id>", "function_status_options_get", function_status_options_get, ["GET"]),
        ("/function_status_options/<unique_id>", "function_status_options_post", function_status_options_post, ["POST"]),
    ],

    'custom_options': [
        {
            'id': 'function_id',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Function',
                'Conditional',
                'PID'
            ],
            'name': lazy_gettext('Function'),
            'phrase': lazy_gettext('Select a Function to display the status of')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 30.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('The period of time between refreshing the widget')
        },
    ],

    'widget_dashboard_head': """<!-- No head content -->""",

    'widget_dashboard_title_bar': """<span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>""",

    'widget_dashboard_body': """<link rel="stylesheet" href="/static/css/components/aot-toggle.css?v=20260814a">
<style>
#fsw-body-{{each_widget.unique_id}} {
  background-color: var(--aot-input-bg);
  border: 1px solid var(--gray);
  border-radius: 16px;
  padding: 14px 16px;
  margin: 12px;
}
#fsw-body-{{each_widget.unique_id}} .aot-w-body {
  font-size: {{each_widget.font_em_name or 1.0}}em;
  white-space: pre-line;
}
</style>
<!-- 상태는 **한 덩이**다. 예전에는 "활성화됨"/"항상" 두 줄이었는데, 그 구분은
     값이 어느 엔드포인트에서 왔는가(`_activated` = 돌고 있는 컨트롤러,
     `_always` = 함수 모듈이 선언한 모듈 수준 함수)라는 구현 사실이지 사용자가
     가진 개념이 아니다. 게다가 "always" 는 "컨트롤러가 안 돌아도 **항상** 물어볼
     수 있다" 는 뜻이라 꾸미는 대상이 상태가 아니라 조회 시점이고, 한국어
     라벨 "항상" 은 무엇이 항상인지 말하지 못했다. 모듈 수준 상태를 가진 종류는
     `camera_libcamera` 하나뿐이라 나머지 전부가 빈 줄(예전에는 오류 한 줄)을
     달고 있었다. 둘 다 있으면 같은 블록에 이어 붙인다. -->
<div id="fsw-body-{{each_widget.unique_id}}" data-function-id="{{widget_options['function_id']}}">
  <span class="aot-w-body" id="fsw-status-{{each_widget.unique_id}}"></span>
</div>
<div style="display: flex; justify-content: flex-end; margin: 0 12px 12px;">
  <button type="button" class="btn aot-pill-btn aot-fsw-detail-btn" data-toggle="modal" data-target="#fsw-modal-{{each_widget.unique_id}}">{{_('Details')}}</button>
</div>

<div class="modal fade aot-option-modal" id="fsw-modal-{{each_widget.unique_id}}" tabindex="-1" role="dialog" aria-hidden="true" data-function-id="{{widget_options['function_id']}}" data-can-edit="{{ 'true' if permission_edit_settings else 'false' }}">
  <div class="modal-dialog aot-modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="fsw-modal-title-{{each_widget.unique_id}}">{{each_widget.name}}</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="{{_('Close')}}"><span aria-hidden="true">&times;</span></button>
      </div>
      <div class="modal-body">
        <div class="text-muted small" id="fsw-modal-status-{{each_widget.unique_id}}"></div>
        <div class="aot-modal-container" id="fsw-modal-options-{{each_widget.unique_id}}">
          <div class="text-muted small">{{_('Loading...')}}</div>
        </div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn aot-pill-btn" data-dismiss="modal">{{_('Close')}}</button>
      </div>
    </div>
  </div>
</div>""",

    'widget_dashboard_js': """
    // function_id is read fresh from the DOM on every call (not passed in and
    // captured by closure) because changing the widget's "함수" option
    // auto-saves and swaps the body in place without reloading the page or
    // re-running this init script — a captured function_id would keep polling
    // the function selected at the last full page load forever.
    function functionStatusCurrentId(widget_id) {
      var el = document.getElementById("fsw-body-" + widget_id);
      return el ? el.getAttribute("data-function-id") : null;
    }

    // 두 엔드포인트가 한 칸을 함께 채운다. 각자 자기 몫만 갈아 끼우고 다시
    // 그리므로, 한쪽이 늦게 와도 다른 쪽 내용을 지우지 않는다.
    var functionStatusParts = {};

    function functionStatusRender(widget_id) {
      var el = document.getElementById("fsw-status-" + widget_id);
      if (!el) return;
      var parts = functionStatusParts[widget_id] || {};
      var lines = (parts.activated || []).concat(parts.always || []);
      // Plain text (no <p>/<br>), so this stays a leaf node — the dashboard's
      // live-save body swap only preserves leaf-node text across a re-render
      // (dashboard-widget-live-preview.js), otherwise this goes blank every
      // time an option is changed and saved.
      el.textContent = lines.join('\\n');
    }

    function functionStatusLinesOf(data) {
      var lines = [];
      if (data && 'error' in data) {
        for (var i = 0, size = data['error'].length; i < size; i++){
          lines.push("{{_('Error')}}: " + data['error'][i]);
        }
      }
      if (data && 'string_status' in data) {
        lines.push(data['string_status']);
      }
      return lines;
    }

    function function_status_activated(widget_id) {
      var function_id = functionStatusCurrentId(widget_id);
      if (!function_id) return;
      const url = '/function_status_activated/' + function_id;
      $.getJSON(url,
        function(data, responseText, jqXHR) {
          var parts = functionStatusParts[widget_id] || (functionStatusParts[widget_id] = {});
          if (jqXHR.status !== 204) {
            // 데몬은 활성화된 컨트롤러만 들고 있으므로, 꺼진 함수에는 "모르는
            // id" 라고 답한다. 그 문장을 그대로 보이면 사용자는 고장으로 읽는다
            // — 서버가 실제 활성 여부를 함께 실어 보내므로 그것으로 말한다.
            if (data && data.is_activated === false) {
              parts.activated = ["{{_('Deactivated')}}"];
            } else {
              parts.activated = functionStatusLinesOf(data);
            }
          }
          else {
            parts.activated = ["{{_('Error')}}"];
          }
          functionStatusRender(widget_id);
        }
      );
    }
    // Repeat function for function_status()
    function repeat_function_status_activated(widget_id, period_sec) {
      setInterval(function () {
        function_status_activated(widget_id)
      }, period_sec * 1000);
    }

    // 이 함수를 마지막으로 "이 유형에는 없다" 는 답을 받은 function_id.
    // 없는 것을 5초마다 다시 묻지 않되, 위젯의 함수를 바꾸면(그때 id 가 달라
    // 진다) 자동으로 다시 묻는다.
    var functionStatusAlwaysUnsupported = {};

    function function_status_always(widget_id) {
      var function_id = functionStatusCurrentId(widget_id);
      if (!function_id) return;
      if (functionStatusAlwaysUnsupported[widget_id] === function_id) return;
      const url_2 = '/function_status_always/' + function_id;
      $.getJSON(url_2,
        function(data, responseText, jqXHR) {
          var parts = functionStatusParts[widget_id] || (functionStatusParts[widget_id] = {});
          if (data && data.supported === false) {
            // 이 함수 유형은 모듈 수준 상태가 없다. 실패가 아니므로 아무것도
            // 보이지 않는다 — 예전에는 여기서 오류 한 줄이 상시 떠 있었다.
            functionStatusAlwaysUnsupported[widget_id] = function_id;
            parts.always = [];
          }
          else if (jqXHR.status !== 204) {
            parts.always = functionStatusLinesOf(data);
          }
          else {
            parts.always = [];
          }
          functionStatusRender(widget_id);
        }
      );
    }
    // Repeat function for function_status_always()
    function repeat_function_status_always(widget_id, period_sec) {
      setInterval(function () {
        function_status_always(widget_id)
      }, period_sec * 1000);
    }

    // ---- Function/Conditional/PID option detail modal ----

    function functionStatusEscapeHtml(value) {
      var div = document.createElement('div');
      div.textContent = (value === null || value === undefined) ? '' : String(value);
      return div.innerHTML;
    }

    function functionStatusBuildOptionRow(opt) {
      var label = '<label class="aot-modal-option-label" title="' +
        functionStatusEscapeHtml(opt.phrase || '') + '">' +
        functionStatusEscapeHtml(opt.name) + '</label>';
      var control;
      if (opt.type === 'bool') {
        var checked = opt.value ? ' checked' : '';
        control = '<div class="aot-modal-option-control"><label class="btn-toggle mb-0">' +
          '<input type="checkbox" class="btn-toggle-input" data-opt-id="' + functionStatusEscapeHtml(opt.id) +
          '" data-opt-type="bool" value="y"' + checked + '>' +
          '<div class="btn-toggle-slider"><div class="btn-toggle-thumb"></div></div></label></div>';
      } else {
        var inputType = (opt.type === 'text') ? 'text' : 'number';
        var step = (opt.type === 'float') ? ' step="any"' : '';
        var val = (opt.value === null || opt.value === undefined) ? '' : opt.value;
        control = '<div class="aot-modal-option-control"><input class="form-control aot-modern-input" type="' +
          inputType + '"' + step + ' data-opt-id="' + functionStatusEscapeHtml(opt.id) +
          '" data-opt-type="' + opt.type + '" value="' + functionStatusEscapeHtml(val) + '"></div>';
      }
      return '<div class="aot-modal-option-row">' + label + control + '</div>';
    }

    function functionStatusSetOptionsDisabled(container, disabled) {
      container.querySelectorAll('[data-opt-id]').forEach(function(el) {
        el.disabled = disabled;
      });
    }

    function functionStatusLoadOptions(widgetId) {
      var modal = document.getElementById('fsw-modal-' + widgetId);
      if (!modal) return;
      var functionId = modal.getAttribute('data-function-id');
      var canEdit = modal.getAttribute('data-can-edit') === 'true';
      var statusEl = document.getElementById('fsw-modal-status-' + widgetId);
      var container = document.getElementById('fsw-modal-options-' + widgetId);
      var titleEl = document.getElementById('fsw-modal-title-' + widgetId);

      if (!functionId) {
        statusEl.textContent = '';
        container.innerHTML = '<div class="text-muted small">{{_('No Function selected.')}}</div>';
        return;
      }

      statusEl.textContent = '';
      container.innerHTML = '<div class="text-muted small">{{_('Loading...')}}</div>';

      $.getJSON('/function_status_options/' + functionId, function(data) {
        if (!data || data.status !== 'ok') {
          container.innerHTML = '<div class="text-danger small">{{_('Failed to load')}}</div>';
          return;
        }
        modal.setAttribute('data-controller-type', data.controller_type);
        if (titleEl && data.name) titleEl.textContent = data.name;
        statusEl.textContent = data.is_activated ? '{{_('Activated')}}' : '{{_('Deactivated')}}';

        if (!data.options || !data.options.length) {
          container.innerHTML = '<div class="text-muted small">{{_('This function type has no editable options.')}}</div>';
          return;
        }

        var html = '';
        for (var i = 0; i < data.options.length; i++) {
          html += functionStatusBuildOptionRow(data.options[i]);
        }
        container.innerHTML = html;

        // Options auto-save on change, the same as every other widget setting
        // in this app — no separate Save button.
        var editable = canEdit && data.editable;
        functionStatusSetOptionsDisabled(container, !editable);
        if (editable) {
          container.querySelectorAll('[data-opt-id]').forEach(function(el) {
            var evt = (el.getAttribute('data-opt-type') === 'bool') ? 'change' : 'input';
            el.addEventListener(evt, function() {
              functionStatusScheduleSave(widgetId);
            });
          });
        }
        if (!data.editable) {
          statusEl.textContent += ' — {{_('This controller is active. Deactivate it before saving changes, or they will not be applied.')}}';
        }
      }).fail(function() {
        container.innerHTML = '<div class="text-danger small">{{_('Failed to load')}}</div>';
      });
    }

    var functionStatusSaveTimers = {};

    function functionStatusScheduleSave(widgetId) {
      clearTimeout(functionStatusSaveTimers[widgetId]);
      functionStatusSaveTimers[widgetId] = setTimeout(function() {
        functionStatusSaveOptions(widgetId);
      }, 500);
    }

    function functionStatusSaveOptions(widgetId) {
      var modal = document.getElementById('fsw-modal-' + widgetId);
      if (!modal) return;
      var functionId = modal.getAttribute('data-function-id');
      var controllerType = modal.getAttribute('data-controller-type');
      var container = document.getElementById('fsw-modal-options-' + widgetId);
      if (!functionId || !controllerType) return;

      var inputs = container.querySelectorAll('[data-opt-id]');
      var values = {};
      inputs.forEach(function(el) {
        var id = el.getAttribute('data-opt-id');
        var type = el.getAttribute('data-opt-type');
        if (type === 'bool') {
          // Always send the key (even unchecked as ''), never omit it: an empty
          // payload (e.g. the only option is a single toggle being turned off)
          // would otherwise be treated server-side as "no form submitted".
          values[id] = el.checked ? 'y' : '';
        } else {
          values[id] = el.value;
        }
      });

      var url, payload;
      if (controllerType === 'pid') {
        url = '/pid_set_params/' + functionId;
        payload = values;
      } else {
        url = '/function_status_options/' + functionId;
        payload = {values: values};
      }

      $.ajax({
        type: 'POST',
        url: url,
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function() {
          if (window.showToast) { window.showToast('{{_('Saved')}}', 'success'); }
        },
        error: function(err) {
          var msg = '{{_('Save failed')}}';
          try { msg = JSON.parse(err.responseText).message || msg; } catch(e) {}
          if (window.showToast) { window.showToast(msg, 'error'); }
        }
      });
    }

    $(document).on('show.bs.modal', '[id^="fsw-modal-"]', function() {
      functionStatusLoadOptions(this.id.replace('fsw-modal-', ''));
    });""",

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
  function_status_activated('{{each_widget.unique_id}}');
  repeat_function_status_activated('{{each_widget.unique_id}}', {{widget_options['refresh_seconds']}});
  function_status_always('{{each_widget.unique_id}}');
  repeat_function_status_always('{{each_widget.unique_id}}', {{widget_options['refresh_seconds']}});
"""
}
