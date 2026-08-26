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
#  AoT_output_pwm.py - Dashboard widget for a single PWM output.
#
#  Replaces widget_output_pwm_slider.py. The card layout (row skeleton, slider,
#  elapsed-time label) is shared with the map/facility widget's actuator
#  controller (aot-map-popup.js buildOutputRow / _buildActRow's 'pwm' branch) —
#  reuses the same aot-act-* CSS so a PWM output looks and behaves the same
#  whether it's controlled from the map or from a dashboard widget.
#
#  The value shown is the daemon's real-time output state (/outputstate_unique_id),
#  the same source the map widget reads — not the logged InfluxDB measurement.
#  One source of truth means the widget and the map never disagree on what a
#  PWM output is currently doing.
#
#  Unlike the old widget, there is no per-widget "Invert Status" option: the
#  output's own 'Invert Signal' custom-channel-option (set once, on the output
#  itself) is read server-side and applied automatically to that real-time
#  state endpoint (see get_pwm_invert_signal() / routes_general.gpio_state_unique_id).
import logging

from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_output_pwm',
    'widget_name': lazy_gettext('AoT PWM Output'),
    'widget_library': '',
    'no_class': True,

    'message': lazy_gettext('Displays and controls a PWM output with a single slider.'),

    'widget_width': 5,
    'widget_height': 6,

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_measurement_channel',
            'default_value': '',
            'options_select': [
                'Output_PWM_Channels_Measurements',
            ],
            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select the output to display and control')
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
<link rel="stylesheet" href="/static/css/widget/aot-facility-widget.css?v=31">
<style>
  .aot-pwm-widget-body { padding: 0.5em 0.75em; height: 100%; }
</style>
""",

    'widget_dashboard_title_bar': """
    <span style="padding-right: 0.5em">{{each_widget.name}}</span>
""",

    'widget_dashboard_body': """
{%- set device_id = widget_options['output'].split(",")[0] -%}
{%- set channel_id = widget_options['output'].split(",")[2] -%}

<div class="aot-pwm-widget-body" id="container-output-{{each_widget.unique_id}}">
  <div class="aot-act-row">
    <div class="aot-act-line">
      <span class="aot-act-name">{{each_widget.name}}</span>
      <span class="aot-act-val" id="value-{{each_widget.unique_id}}">&mdash;</span>
    </div>
    <div class="aot-act-meta">
      <span class="aot-act-meta-text" id="runtime-{{each_widget.unique_id}}">&mdash;</span>
      <span class="aot-act-meta-ctrl">
        <input id="range_{{each_widget.unique_id}}" type="range" class="aot-act-slider"
               min="0" max="100" step="1" value="0"
               oninput="AoTOutputPWM.onSlide('{{each_widget.unique_id}}', this.value)"
               onchange="AoTOutputPWM.onCommit('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', this.value)">
      </span>
    </div>
  </div>
</div>
""",

    'widget_dashboard_js': """
window.AoTOutputPWM = window.AoTOutputPWM || (function () {
  var _intervals = {};

  function _fmtElapsed(sec) {
    sec = Math.max(0, Math.floor(sec));
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    return (h > 0 ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
  }

  // Live label while dragging (no network call).
  function onSlide(widgetId, val) {
    var el = document.getElementById('value-' + widgetId);
    if (el) el.textContent = Math.round(val) + '%';
  }

  // Command sent only on drag-end. 0% turns the output fully off; anything
  // above 0 sets that PWM duty cycle. No separate Off button/duty-entry —
  // the slider is the only control (same interaction as the map widget's
  // actuator card).
  function onCommit(widgetId, outputId, channelId, val) {
    var duty = Math.round(val);
    var cmd = duty <= 0
      ? outputId + '/' + channelId + '/off/sec/0'
      : outputId + '/' + channelId + '/on/pwm/' + duty;
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

  // Real-time daemon state — same source the map widget's actuator card
  // reads (DaemonControl.output_states_all() → is_on()). The server already
  // corrects for the output's 'Invert Signal' option here (routes_general.
  // gpio_state_unique_id), so this widget never has to know about it.
  function _getState(widgetId, deviceId, channelId) {
    var url = '/outputstate_unique_id/' + deviceId + '/' + channelId;
    $.getJSON(url, function (state, statusText, jqXHR) {
      var valueEl = document.getElementById('value-' + widgetId);
      var range = document.getElementById('range_' + widgetId);
      if (!valueEl) return;
      if (jqXHR.status === 204 || state === null) {
        valueEl.textContent = '{{_("No Connection")}}';
        return;
      }
      if (state === 'off') {
        valueEl.textContent = '0%';
        if (range && document.activeElement !== range) range.value = 0;
        return;
      }
      if (typeof state !== 'number') {
        // 'fault' | 'pending' | anything unexpected
        valueEl.textContent = String(state);
        return;
      }
      valueEl.textContent = state.toFixed(0) + '%';
      // Don't fight the user mid-drag.
      if (range && document.activeElement !== range) range.value = state.toFixed(0);
    }).fail(function () {
      var valueEl = document.getElementById('value-' + widgetId);
      if (valueEl) valueEl.textContent = '{{_("No Connection")}}';
    });
  }

  function _getRuntime(widgetId, outputId, channelId) {
    $.ajax('/api/geo/output_runtimes', {
      type: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({items: [{id: outputId, channel: channelId}]}),
      success: function (resp) {
        var el = document.getElementById('runtime-' + widgetId);
        if (!el || !resp || !resp.ok) return;
        var entry = resp.runtimes[outputId + '::' + channelId];
        if (!entry) { el.textContent = '\\u2014'; return; }
        if (entry.elapsed_sec) {
          el.textContent = _fmtElapsed(entry.elapsed_sec);
          el.classList.add('aot-act-val-current');
        } else if (entry.last_duration_sec) {
          el.textContent = _fmtElapsed(entry.last_duration_sec);
          el.classList.remove('aot-act-val-current');
        } else {
          el.textContent = '\\u2014';
        }
      },
      error: function () {}
    });
  }

  function start(widgetId, deviceId, channelId, refreshSec) {
    stop(widgetId);
    var tick = function () {
      _getState(widgetId, deviceId, channelId);
      _getRuntime(widgetId, deviceId, channelId);
    };
    tick();
    _intervals[widgetId] = setInterval(tick, refreshSec * 1000);
  }

  function stop(widgetId) {
    if (_intervals[widgetId]) { clearInterval(_intervals[widgetId]); delete _intervals[widgetId]; }
  }

  return {onSlide: onSlide, onCommit: onCommit, start: start, stop: stop};
})();
""",

    'widget_dashboard_js_ready_end': """
{%- set device_id = widget_options['output'].split(",")[0] -%}
{%- set channel_id = widget_options['output'].split(",")[2] -%}
AoTOutputPWM.start('{{each_widget.unique_id}}', '{{device_id}}', '{{channel_id}}', {{widget_options['refresh_seconds']}});
"""
}
