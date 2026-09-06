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
#  AoT_output_value.py - Dashboard widget for a single 'value'-type output
#  (a positional/open-close actuator: actuator_paired, actuator_paired_bus,
#  DAC 0-10V, etc — anything whose OUTPUT_INFORMATION lists 'value' in
#  output_types).
#
#  Card layout and interaction mirror the map/facility widget's actuator
#  controller (aot-map-popup.js buildOutputRow / _buildActRow's 'value'
#  branch) — same close/stop/open 3-button row plus a fine-adjust slider,
#  and the same "target vs. current" distinction: a positional actuator
#  takes time to travel, so what was last commanded (target) and where it
#  actually is right now (current) can legitimately disagree while moving.
#
#  Commands go through the same /output_mod/ route every other widget uses
#  (open -> on/value/100, close -> on/value/0, stop -> off/value/0, slider
#  -> on/value/<pct>) — no new control path, so it inherits the same
#  scope/permission gate (see check_scope_gates.py GATED_CONTROL_VIEWS,
#  which already covers utils_general.controller_activate_deactivate's
#  chokepoint; output_mod has its own scope.can_operate_device() check).
import logging

from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_output_value',
    'widget_name': lazy_gettext('AoT Actuator Position'),
    'widget_library': '',
    'no_class': True,

    'message': lazy_gettext(
        'Displays and controls a positional (open/close) actuator: close/stop/open '
        'buttons plus a fine-adjust slider.'),

    'widget_width': 6,
    'widget_height': 6,

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_measurement_channel',
            'default_value': '',
            'options_select': [
                'Output_Value_Channels_Measurements',
            ],
            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select the actuator to display and control')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 10.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('The period of time between refreshing the widget')
        }
    ],

    'widget_dashboard_head': """
{% if "css_facility_widget" not in dashboard_dict %}
{% if "css_facility_widget" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-facility-widget.css') }}">
{% set _dummy = dashboard_dict.update({"css_facility_widget": 1}) %}
{% endif %}
{% set _dummy = dashboard_dict.update({"css_facility_widget": 1}) %}
{% endif %}
{% if "css_sensor_label" not in dashboard_dict %}
{% if "css_sensor_label" not in dashboard_dict %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/widget/aot-sensor-label.css') }}">
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}
{% set _dummy = dashboard_dict.update({"css_sensor_label": 1}) %}
{% endif %}
<style>
  .aot-value-widget-body { padding: 0.5em 0.75em; height: 100%; }
</style>
""",

    'widget_dashboard_title_bar': """""",

    'widget_dashboard_body': """
{%- set device_id = widget_options['output'].split(",")[0] -%}
{%- set channel_id = widget_options['output'].split(",")[2] -%}

<div class="aot-value-widget-body" id="container-output-{{each_widget.unique_id}}">
  <div class="aot-act-row">
    <div class="aot-act-line">
      <span class="aot-act-name">{{each_widget.name}}</span>
      <div class="aot-act-3btn">
        <button type="button" class="aot-act-pbtn" id="btn-close-{{each_widget.unique_id}}"
                onclick="AoTOutputValue.onCommand('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', 'close')">{{ _('Close') }}</button>
        <button type="button" class="aot-act-pbtn" id="btn-stop-{{each_widget.unique_id}}"
                onclick="AoTOutputValue.onCommand('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', 'stop')">{{ _('Stop') }}</button>
        <button type="button" class="aot-act-pbtn" id="btn-open-{{each_widget.unique_id}}"
                onclick="AoTOutputValue.onCommand('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', 'open')">{{ _('Open') }}</button>
      </div>
    </div>
    <div class="aot-act-meta">
      <span class="aot-act-meta-text" id="value-{{each_widget.unique_id}}">&mdash;</span>
      <span class="aot-act-meta-ctrl">
        {#- 스크린리더가 읽을 이름 — 없으면 "슬라이더" 로만 읽힌다. -#}
        <input id="range_{{each_widget.unique_id}}" type="range" class="aot-act-slider"
               aria-label="{{_('Value')}}"
               min="0" max="100" step="1" value="0"
               oninput="AoTOutputValue.onSlide('{{each_widget.unique_id}}', this.value)"
               onchange="AoTOutputValue.onCommand('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', 'set', this.value)">
      </span>
    </div>
  </div>
</div>
""",

    'widget_dashboard_js': """
window.AoTOutputValue = window.AoTOutputValue || (function () {
  var _intervals = {};
  var _t = function (x) { return (window._ ? window._(x) : x); };

  function _setActiveButtons(widgetId, curPct) {
    var closeBtn = document.getElementById('btn-close-' + widgetId);
    var openBtn = document.getElementById('btn-open-' + widgetId);
    if (closeBtn) closeBtn.classList.toggle('active', curPct <= 1);
    if (openBtn) openBtn.classList.toggle('active', curPct >= 99);
  }

  // Live label while dragging (no network call).
  function onSlide(widgetId, val) {
    var el = document.getElementById('value-' + widgetId);
    if (el) el.textContent = Math.round(val) + '%';
  }

  function onCommand(widgetId, outputId, channelId, action, val) {
    var cmd;
    if (action === 'open') cmd = outputId + '/' + channelId + '/on/value/100';
    else if (action === 'close') cmd = outputId + '/' + channelId + '/on/value/0';
    else if (action === 'stop') cmd = outputId + '/' + channelId + '/off/value/0';
    else cmd = outputId + '/' + channelId + '/on/value/' + Math.round(val);

    $.ajax({
      type: 'GET',
      url: '/output_mod/' + cmd,
    {% if not misc.hide_alert_success %}
      success: function (data) {
        if (data.startsWith('SUCCESS')) { toastr['success']('Output: ' + data); }
        else { toastr['error']('Output: ' + data); }
      },
    {% endif %}
    {% if not misc.hide_alert_warning %}
      error: function () { toastr['error']('Output ' + outputId + ': command failed'); }
    {% endif %}
    });
  }

  // Real-time daemon state (actual position) — same source the map widget reads.
  function _getState(widgetId, deviceId, channelId) {
    $.getJSON('/outputstate_unique_id/' + deviceId + '/' + channelId, function (state, statusText, jqXHR) {
      var valueEl = document.getElementById('value-' + widgetId);
      var range = document.getElementById('range_' + widgetId);
      if (!valueEl) return;
      if (jqXHR.status === 204 || state === null) {
        valueEl.textContent = _t('No Connection');
        return;
      }
      var curPct = (typeof state === 'number') ? state : (state === 'off' ? 0 : null);
      if (curPct === null) { valueEl.textContent = String(state); return; }
      valueEl.dataset.current = curPct;
      _renderLabel(widgetId);
      if (range && document.activeElement !== range) range.value = curPct.toFixed(0);
      _setActiveButtons(widgetId, curPct);
    }).fail(function () {
      var valueEl = document.getElementById('value-' + widgetId);
      if (valueEl) valueEl.textContent = _t('No Connection');
    });
  }

  // Last commanded target — a positional actuator takes time to travel, so
  // this can legitimately differ from the real-time state above while moving.
  function _getTarget(widgetId, deviceId, channelId) {
    $.getJSON('/output_target_pct/' + deviceId + '/' + channelId, function (resp) {
      var valueEl = document.getElementById('value-' + widgetId);
      if (!valueEl || !resp || resp.value === null || resp.value === undefined) return;
      valueEl.dataset.target = resp.value;
      valueEl.dataset.targetSource = resp.source || '';
      _renderLabel(widgetId);
    }).fail(function () {});
  }

  function _renderLabel(widgetId) {
    var el = document.getElementById('value-' + widgetId);
    if (!el) return;
    var cur = el.dataset.current;
    var target = el.dataset.target;
    var srcLabel = el.dataset.targetSource === 'manual' ? _t('Manual')
                 : el.dataset.targetSource === 'system' ? _t('System')
                 : _t('Target');
    var parts = [];
    if (target !== undefined && target !== '') {
      parts.push(srcLabel + ' ' + Math.round(target) + '%');
    }
    if (cur !== undefined && cur !== '') {
      parts.push(_t('Current') + ' ' + Math.round(cur) + '%');
    }
    el.textContent = parts.length ? parts.join(' \\u00b7 ') : '\\u2014';
  }

  function start(widgetId, deviceId, channelId, refreshSec) {
    stop(widgetId);
    var tick = function () {
      _getState(widgetId, deviceId, channelId);
      _getTarget(widgetId, deviceId, channelId);
    };
    tick();
    _intervals[widgetId] = setInterval(tick, refreshSec * 1000);
  }

  function stop(widgetId) {
    if (_intervals[widgetId]) { clearInterval(_intervals[widgetId]); delete _intervals[widgetId]; }
  }

  return {onSlide: onSlide, onCommand: onCommand, start: start, stop: stop};
})();
""",

    'widget_dashboard_js_ready_end': """
{%- set device_id = widget_options['output'].split(",")[0] -%}
{%- set channel_id = widget_options['output'].split(",")[2] -%}
AoTOutputValue.start('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', {{widget_options['refresh_seconds']}});
"""
}
