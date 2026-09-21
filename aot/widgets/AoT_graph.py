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

import datetime
import json
import logging
import re

import flask_login
from flask import flash
from flask import jsonify
from flask_babel import lazy_gettext
from flask_login import current_user
from pytz import timezone

from aot.config import THEMES_DARK
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import Measurement
from aot.databases.models import NoteTags
from aot.databases.models import Notes
from aot.databases.models import Output
from aot.databases.models import PID
from aot.aot_flask.utils.utils_general import use_unit_generate
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.influx import read_influxdb_list
from aot.utils.system_pi import add_custom_measurements
from aot.utils.system_pi import return_measurement_info
from aot.utils.system_pi import str_is_float

logger = logging.getLogger(__name__)


def past_data(unique_id, measure_type, measurement_id, past_seconds):
    """Return data from past_seconds until present from influxdb."""
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"
    if not str_is_float(past_seconds):
        return '', 204

    if measure_type == 'tag':
        notes_list = []

        tag = NoteTags.query.filter(NoteTags.unique_id == unique_id).first()
        notes = Notes.query.filter(
            Notes.date_time >= (datetime.datetime.utcnow() - datetime.timedelta(seconds=int(past_seconds)))).all()

        for each_note in notes:
            if tag.unique_id in each_note.tags.split(','):
                notes_list.append(
                    [each_note.date_time.replace(tzinfo=timezone('UTC')).timestamp(), each_note.name, each_note.note])

        if notes_list:
            return jsonify(notes_list)
        else:
            return '', 204

    elif measure_type in ['input', 'function', 'output', 'pid']:
        if measure_type in ['input', 'function', 'output', 'pid']:
            measure = DeviceMeasurements.query.filter(
                DeviceMeasurements.unique_id == measurement_id).first()
        else:
            measure = None

        if not measure:
            return "Could not find measurement"

        if measure:
            conversion = Conversion.query.filter(
                Conversion.unique_id == measure.conversion_id).first()
        else:
            conversion = None

        channel, unit, measurement = return_measurement_info(
            measure, conversion)

        if hasattr(measure, 'measurement_type') and measure.measurement_type == 'setpoint':
            setpoint_pid = PID.query.filter(PID.unique_id == measure.device_id).first()
            if setpoint_pid and ',' in setpoint_pid.measurement:
                pid_measurement = setpoint_pid.measurement.split(',')[1]
                setpoint_measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == pid_measurement).first()
                if setpoint_measurement:
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == setpoint_measurement.conversion_id).first()
                    _, unit, measurement = return_measurement_info(setpoint_measurement, conversion)

        try:
            list_data = read_influxdb_list(
                unique_id, unit,
                channel=channel,
                measure=measurement,
                duration_sec=past_seconds)

            if not list_data:
                return '', 204

            return jsonify(list_data)
        except Exception as err:
            logger.debug(f"URL for 'past_data' raised and error: {err}")
            return '', 204


def execute_at_creation(error, new_widget, dict_widget):
    # Create initial default values
    custom_options_json = json.loads(new_widget.custom_options)
    custom_options_json['use_custom_colors'] = "y"
    custom_options_json['disable_data_grouping'] = ""
    custom_options_json['series_type'] = ""
    custom_options_json['custom_yaxes'] = ""
    custom_options_json['custom_colors'] = ""
    new_widget.custom_options = json.dumps(custom_options_json)
    return error, new_widget


def execute_at_modification(
        mod_widget,
        request_form,
        custom_options_json_presave,
        custom_options_json_postsave):
    allow_saving = True
    page_refresh = False
    error = []

    for key in request_form.keys():
        if key == 'use_custom_colors':
            custom_options_json_postsave['use_custom_colors'] = request_form.get(key)
        elif key == 'enable_manual_y_axis':
            custom_options_json_postsave['enable_manual_y_axis'] = request_form.get(key)
        elif key == 'enable_align_ticks':
            custom_options_json_postsave['enable_align_ticks'] = request_form.get(key)
        elif key == 'enable_start_on_tick':
            custom_options_json_postsave['enable_start_on_tick'] = request_form.get(key)
        elif key == 'enable_end_on_tick':
            custom_options_json_postsave['enable_end_on_tick'] = request_form.get(key)
        elif key == 'enable_graph_legend':
            custom_options_json_postsave['enable_graph_legend'] = request_form.get(key)
        elif key == 'hide_axis_labels_on_mobile':
            custom_options_json_postsave['hide_axis_labels_on_mobile'] = request_form.get(key)

    custom_options_json_postsave['custom_yaxes'] = custom_yaxes_str_from_form(request_form)

    sorted_colors, error = custom_colors_graph(request_form, error)
    custom_options_json_postsave['custom_colors'] = sorted_colors

    disable_data_grouping, error = data_grouping_graph(request_form, error)
    custom_options_json_postsave['disable_data_grouping'] = disable_data_grouping

    series_type, error = series_type_graph(request_form, error)
    custom_options_json_postsave['series_type'] = series_type

    for each_error in error:
        flash(each_error, "error")

    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave


def generate_page_variables(widget_unique_id, widget_options):
    dict_measurements = add_custom_measurements(Measurement.query.all())
    colors_graph = dict_custom_colors(widget_options)
    y_axes = graph_y_axes(dict_measurements, widget_options)
    custom_yaxes = dict_custom_yaxes_min_max(y_axes, widget_options)

    # Unit conversion
    x_axis_duration = widget_options.get('x_axis_duration', 1)
    x_axis_duration_unit = widget_options.get('x_axis_duration_unit', 'day')

    # Always compute internally in minutes for consistency
    if x_axis_duration_unit == 'day':
        x_axis_duration_minutes = x_axis_duration * 1440  # one day = 1440 minutes
    elif x_axis_duration_unit == 'hour':
        x_axis_duration_minutes = x_axis_duration * 60
    elif x_axis_duration_unit == 'minute':
        x_axis_duration_minutes = x_axis_duration
    else:
        x_axis_duration_minutes = 1440  # default 1 day

    # Convert to seconds for JS and server communication
    x_axis_duration_sec = x_axis_duration_minutes * 60

    dict_return = {
        'colors_graph': colors_graph,
        'y_axes': y_axes,
        'custom_yaxes': custom_yaxes,
        'x_axis_duration_min': x_axis_duration_minutes,  # used internally by JS
        'x_axis_duration_sec': x_axis_duration_sec  # for server communication
    }

    return dict_return


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_graph',
    'widget_name': lazy_gettext('AoT Graph'),
    'widget_library': 'ECharts',
    'no_class': True,

    'message': lazy_gettext('Displays a synchronous graph. Data selected will be displayed on the X-axis for the configured duration.'),

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': generate_page_variables,

    'endpoints': [
        # Route URL, route endpoint name, view function, methods
        ("/past/<unique_id>/<measure_type>/<measurement_id>/<past_seconds>", "past", past_data, ["GET"]),
    ],

    'widget_width': 24,
    'widget_height': 15,

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('Time Axis Settings')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 90.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Set the refresh interval for the widget')
        },
        {
            'id': 'x_axis_duration_unit',
            'type': 'select',
            'default_value': 'day',
            'options_select': [
                ('day', lazy_gettext('Day')),
                ('hour', lazy_gettext('Hour')),
                ('minute', lazy_gettext('Minute')),
            ],
            'name': lazy_gettext('X-Axis Duration Unit'),
            'phrase': lazy_gettext('Select the unit for the X-axis duration.')
        },
        {
            'id': 'x_axis_duration',
            'type': 'integer',
            'default_value': 1,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('X-Axis Duration'),
            'phrase': lazy_gettext('Enter the duration to display on the X-axis.')
        },
        {
            'id': 'enable_auto_refresh',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable Auto Refresh'),
            'phrase': lazy_gettext('Automatically refresh graph data at the specified interval.')
        },
        {
            'id': 'enable_xaxis_reset',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable X-Axis Reset'),
            'phrase': lazy_gettext('Reset the X-axis when refreshing the graph.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Graph Style')
        },
        {
            'id': 'enable_header_buttons',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable Header Buttons'),
            'phrase': lazy_gettext('Display graph control buttons in the widget header.')
        },
        {
            'id': 'enable_title',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Enable Title'),
            'phrase': lazy_gettext('Display the graph title.')
        },
        {
            'id': 'enable_navbar',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Enable NavBar'),
            'phrase': lazy_gettext('Enable the graph navigation bar.')
        },
        {
            'id': 'enable_night_shading',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Shade Night'),
            'phrase': lazy_gettext('Shades the periods between sunset and sunrise so readings can be read against the solar day rather than the clock. Sun times come from this farm\'s location.')
        },
        {
            'id': 'enable_export',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Enable Export'),
            'phrase': lazy_gettext('Enable the button to export the graph.')
        },
        {
            'id': 'enable_range_selector',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Enable Range Selector'),
            'phrase': lazy_gettext('Enable the graph range selector.')
        },
        {
            'id': 'enable_graph_legend',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable Legend'),
            'phrase': lazy_gettext('Display the legend at the bottom of the graph.')
        },
        {
            'id': 'hide_axis_labels_on_mobile',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Hide Axis Labels on Mobile'),
            'phrase': lazy_gettext('Hide graph axis tick labels and unit titles on small screens (chart width < 480px).')
        },
        {
            'type': 'collapse_start',
            'id': 'text_size',
            'name': lazy_gettext('Text Size')
        },

        {
            'id': 'graph_font_size_em_axes',
            'type': 'float',
            'default_value': 0.8,
            'name': lazy_gettext('Axis Font Size (em)'),
            'phrase': lazy_gettext('Set the font size for graph axes (em).')
        },
        {
            'id': 'graph_font_size_em_axes_title',
            'type': 'float',
            'default_value': 1.0,
            'name': lazy_gettext('Axis Title Font Size (em)'),
            'phrase': lazy_gettext('Set the font size for graph axis titles (em).')
        },
        {
            'id': 'graph_font_size_em_legend',
            'type': 'float',
            'default_value': 1.0,
            'name': lazy_gettext('Legend Font Size (em)'),
            'phrase': lazy_gettext('Set the font size for the legend (em).')
        },
        {
            'id': 'graph_font_size_em_title',
            'type': 'float',
            'default_value': 1.0,
            'name': lazy_gettext('Title Font Size (em)'),
            'phrase': lazy_gettext('Set the font size for the title (em).')
        },
        {
            'type': 'collapse_end'
        },
        {
            'type': 'header',
            'name': lazy_gettext('Data Source')
        },
        {
            'id': 'measurements_input',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'Input'
            ],
            'name': lazy_gettext('Input'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'id': 'measurements_function',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'Function'
            ],
            'name': lazy_gettext('Function'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'id': 'measurements_output',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'Output'
            ],
            'name': lazy_gettext('Output'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'id': 'measurements_pid',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'PID'
            ],
            'name': lazy_gettext('PID'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'id': 'measurements_note_tag',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'Tag'
            ],
            'name': lazy_gettext('Note Tag'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'type': 'message',
            'default_value': lazy_gettext('Press <kbd>Ctrl</kbd> or <kbd>&#8984;</kbd> to select multiple items.'),
        }
    ],

    'widget_dashboard_head': """{% if "echarts" not in dashboard_dict %}
  <script src="{{ asset('echarts-stack') }}"></script>
  {% set _dummy = dashboard_dict.update({"echarts": 1}) %}
{% endif %}
{% if "aot_chart_core" not in dashboard_dict %}
  <script src="{{ asset('app-chart-core') }}"></script>
  {% set _dummy = dashboard_dict.update({"aot_chart_core": 1}) %}
{% endif %}
{% if "timeseries_chart" not in dashboard_dict %}
  <script src="{{ asset('widget-timeseries-chart') }}"></script>
  {% set _dummy = dashboard_dict.update({"timeseries_chart": 1}) %}
{% endif %}
""",

    'widget_dashboard_title_bar': """
        {#- 이름은 셸이 렌더한다(dashboard_entry.html). 여기는 제목줄 오른쪽 도구만.
            버튼은 공용 규격 `.aot-w-tool` 하나를 쓴다 — 예전에는 부트스트랩
            `btn btn-sm btn-success`(초록 그라디언트)라 이 위젯만 다른 앱처럼 보였다. -#}
        {% if widget_options['enable_header_buttons'] -%}
        <div class="widget-graph-controls" id="widget-graph-controls-{{each_widget.unique_id}}">
            <div class="widget-graph-responsive-controls" id="widget-graph-responsive-controls-{{each_widget.unique_id}}">
                <a class="aot-w-tool" role="button" tabindex="0" id="updateData{{each_widget.unique_id}}"
                   aria-label="{{_('Update')}}" title="{{_('Update')}}">
                    <i class="fa fa-download"></i>
                </a>
                <a class="aot-w-tool" role="button" tabindex="0" id="resetZoom{{each_widget.unique_id}}"
                   aria-label="{{_('Reset')}}" title="{{_('Reset')}}">
                    <i class="fa fa-undo-alt"></i>
                </a>
                <a class="aot-w-tool" role="button" tabindex="0" id="showhidebutton{{each_widget.unique_id}}"
                   aria-label="{{_('Hide')}}" title="{{_('Hide')}}">
                    <i class="fa fa-eye-slash"></i>
                </a>
            </div>
            <a href="javascript:void(0);" class="aot-w-tool menu"
               onclick="return graphMenuFunction('{{each_widget.unique_id}}');"
               aria-label="{{_('Options')}}" title="{{_('Options')}}">
                <i class="fa fa-bars"></i>
            </a>
        </div>
        {% endif %}
    """,

    'widget_dashboard_body': """<div class="not-draggable" id="container-synchronous-graph-{{each_widget.unique_id}}" style="position: absolute; left: 0; top: 0; bottom: 0; right: 0; overflow: hidden;"></div>""",

    'widget_dashboard_configure_options': """
        <div class="aot-modal-section-title">{{_('Graph Series Options')}}</div>
        <div class="aot-modal-container">

          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label" for="use_custom_colors">{{_('Use Custom Colors')}}</label>
            <div class="aot-modal-option-control">
              <label class="btn-toggle">
                <input id="use_custom_colors" name="use_custom_colors" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options['use_custom_colors'] %} checked{% endif %}>
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
              </label>
            </div>
          </div>

          {% for n in range(widget_variables['colors_graph']|length) %}
          {% set index = '{0:0>2}'.format(n) %}
          <div class="aot-modal-detail-item">
            <div class="aot-modal-detail-head">
              {{widget_variables['colors_graph'][n]['type']}}
              {%- if 'channel' in widget_variables['colors_graph'][n] and widget_variables['colors_graph'][n]['channel'] is not none -%}
                {{', CH' + widget_variables['colors_graph'][n]['channel']|string}}
              {%- endif -%}
              {%- if widget_variables['colors_graph'][n]['name'] -%}
                {{', ' + widget_variables['colors_graph'][n]['name']}}
              {%- endif -%}
              {%- if widget_variables['colors_graph'][n]['measure_name'] -%}
                {{', ' + widget_variables['colors_graph'][n]['measure_name']}}
              {%- endif -%}
              {%- if widget_variables['colors_graph'][n]['unit'] in dict_units -%}
                {{' (' + dict_units[widget_variables['colors_graph'][n]['unit']]['name'] + ')'}}
              {%- endif -%}
            </div>
            <div class="aot-modal-detail-fields">
              <div class="aot-modal-detail-field aot-detail-field-color">
                <label for="color_number{{index}}">{{_('Select Color')}}</label>
                <input id="color_number{{index}}" name="color_number{{index}}" placeholder="#000000" type="color" value="{{widget_variables['colors_graph'][n]['color']}}">
              </div>
              {% if widget_variables['colors_graph'][n]['type'] != 'Tag' %}
              <div class="aot-modal-detail-field aot-detail-field-toggle">
                <label for="disable_data_grouping-{{widget_variables['colors_graph'][n]['measure_id']}}">{{_('Disable Data Grouping')}}</label>
                <label class="btn-toggle">
                  <input id="disable_data_grouping-{{widget_variables['colors_graph'][n]['measure_id']}}" name="disable_data_grouping-{{widget_variables['colors_graph'][n]['measure_id']}}" type="checkbox" value="y" class="btn-toggle-input"{% if widget_variables['colors_graph'][n]['disable_data_grouping'] %} checked{% endif %}>
                  <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
                </label>
              </div>
              <div class="aot-modal-detail-field">
                <label for="series_type-{{widget_variables['colors_graph'][n]['measure_id']}}">{{_('Series Type')}}</label>
                <select id="series_type-{{widget_variables['colors_graph'][n]['measure_id']}}" name="series_type-{{widget_variables['colors_graph'][n]['measure_id']}}" class="aot-modern-select">
                  <option value="line" {% if widget_variables['colors_graph'][n]['series_type'] == "line" %} selected{% endif %}>{{_('Line')}}</option>
                  <option value="step-left" {% if widget_variables['colors_graph'][n]['series_type'] == "step-left" %} selected{% endif %}>{{_('Step (Left)')}}</option>
                  <option value="step-center" {% if widget_variables['colors_graph'][n]['series_type'] == "step-center" %} selected{% endif %}>{{_('Step (Center)')}}</option>
                  <option value="step-right" {% if widget_variables['colors_graph'][n]['series_type'] == "step-right" %} selected{% endif %}>{{_('Step (Right)')}}</option>
                  <option value="column" {% if widget_variables['colors_graph'][n]['series_type'] == "column" %} selected{% endif %}>{{_('Column')}}</option>
                </select>
              </div>
              {% endif %}
            </div>
          </div>
          {% endfor %}

          {# 역방향 저장: 이 그래프의 시리즈색(앞 6개)을 전역 차트 색(custom_ui chart_1..6)으로 #}
          <div style="margin-top: 0.8rem;">
            <button type="button" class="btn aot-pill-btn"
                    onclick="(function(btn){
                      var colors = [];
                      for (var i = 0; i < 6; i++) {
                        var el = document.getElementById('color_number0' + i);
                        if (el && el.value) colors.push(el.value);
                      }
                      if (!colors.length) return;
                      var csrf = document.querySelector('input[name=csrf_token]');
                      fetch('/settings/custom_ui/global_colors', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.value : ''},
                        body: JSON.stringify({kind: 'chart', colors: colors})
                      }).then(function(r){ return r.json().then(function(d){ return r.ok ? d : Promise.reject(new Error(d.error || 'failed')); }); })
                        .then(function(){ if (window.toastr) toastr.success('{{_('Saved as global chart colors')}}'); })
                        .catch(function(e){ if (window.toastr) toastr.error(e.message); else alert(e.message); });
                    })(this)">{{_('Save as Global Chart Colors')}}</button>
            <div class="aot-modal-body-text">{{_('Applies the first 6 series colors to Settings > Custom UI chart colors.')}}</div>
          </div>
        </div>

        <div class="aot-modal-section-title">{{_('Y-Axis Options')}}</div>
        <div class="aot-modal-container">

          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label" for="enable_manual_y_axis">{{_('Enable Manual Y-Axis Min/Max')}}</label>
            <div class="aot-modal-option-control">
              <label class="btn-toggle">
                <input id="enable_manual_y_axis" name="enable_manual_y_axis" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options['enable_manual_y_axis'] %} checked{% endif %}>
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
              </label>
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label" for="enable_align_ticks">{{_('Enable Align Ticks')}}</label>
            <div class="aot-modal-option-control">
              <label class="btn-toggle">
                <input id="enable_align_ticks" name="enable_align_ticks" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options['enable_align_ticks'] %} checked{% endif %}>
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
              </label>
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label" for="enable_start_on_tick">{{_('Enable Start On Tick')}}</label>
            <div class="aot-modal-option-control">
              <label class="btn-toggle">
                <input id="enable_start_on_tick" name="enable_start_on_tick" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options['enable_start_on_tick'] %} checked{% endif %}>
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
              </label>
            </div>
          </div>
          <div class="aot-modal-option-row">
            <label class="aot-modal-option-label" for="enable_end_on_tick">{{_('Enable End On Tick')}}</label>
            <div class="aot-modal-option-control">
              <label class="btn-toggle">
                <input id="enable_end_on_tick" name="enable_end_on_tick" type="checkbox" value="y" class="btn-toggle-input"{% if widget_options['enable_end_on_tick'] %} checked{% endif %}>
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
              </label>
            </div>
          </div>

          {% for each_yaxis in widget_variables['y_axes'] if each_yaxis in dict_units %}
          {% set index = '{0:0>2}'.format(loop.index) %}
          <div class="aot-modal-detail-item">
            <input type="hidden" name="custom_yaxis_name_{{index}}" value="{{each_yaxis}}">
            <div class="aot-modal-detail-head">{{dict_units[each_yaxis]['name']}}{% if dict_units[each_yaxis]['unit'] != '' %} ({{dict_units[each_yaxis]['unit']}}){% endif %}</div>
            <div class="aot-modal-detail-fields">
              <div class="aot-modal-detail-field">
                <label for="yaxis_min_{{index}}">{{_('Y-Axis Min')}}</label>
                <input id="yaxis_min_{{index}}" class="aot-modern-input" name="custom_yaxis_min_{{index}}" type="number" value="{% if widget_variables['custom_yaxes'][each_yaxis] %}{{widget_variables['custom_yaxes'][each_yaxis]['minimum']}}{% endif %}">
              </div>
              <div class="aot-modal-detail-field">
                <label for="yaxis_max_{{index}}">{{_('Y-Axis Max')}}</label>
                <input id="yaxis_max_{{index}}" class="aot-modern-input" name="custom_yaxis_max_{{index}}" type="number" value="{% if widget_variables['custom_yaxes'][each_yaxis] %}{{widget_variables['custom_yaxes'][each_yaxis]['maximum']}}{% endif %}">
              </div>
            </div>
          </div>
          {% endfor %}
        </div>
""",

    'widget_dashboard_js': """
  AoTChart.applyGlobalDefaults();

  if (typeof window.note_timestamps === 'undefined') window.note_timestamps = {};
  if (typeof window.last_output_time_mil === 'undefined') window.last_output_time_mil = {};
  if (typeof window._graph_intervals === 'undefined') window._graph_intervals = {};
  // History browsing state (per widget id)
  if (typeof window._graph_series_meta === 'undefined') window._graph_series_meta = {};
  if (typeof window._graph_load_gen === 'undefined') window._graph_load_gen = {};
  if (typeof window._graph_load_debounce === 'undefined') window._graph_load_debounce = {};
  var note_timestamps = window.note_timestamps;
  var last_output_time_mil = window.last_output_time_mil;

  // ---- History browsing -------------------------------------------------
  // This widget normally holds only x_axis_duration of data. When the user
  // navigates (range button / navigator / zoom / date input) to a time earlier
  // than what is loaded, fetch the missing earlier slice (downsampled via
  // /async) and merge it in, so users can look further back without
  // reconfiguring the widget. While earlier data is shown ("browsing"), the
  // live auto-reset and trim are suppressed so it stays visible; the header
  // Reset button returns to the live sliding window.
  //
  // widget[id] is an AoTTimeSeries handle (aot-timeseries-chart.js). Ranges set
  // from code (setExtremes) never call back into onUserZoom, so no suppress
  // flag is needed around them.

  function _graphRegisterSeries(widget_id, series, unique_id, measure_type, measurement_id) {
    if (!window._graph_series_meta[widget_id]) window._graph_series_meta[widget_id] = [];
    window._graph_series_meta[widget_id][series] = {
      id: unique_id, type: measure_type, measure: measurement_id
    };
  }

  // Browsing = loaded data reaches meaningfully earlier than the live window.
  function _graphIsBrowsing(ts, xaxis_duration_min) {
    if (!ts) return false;
    const oldest = ts.oldest();
    if (oldest === null) return false;
    return oldest < (Date.now() - xaxis_duration_min * 60000) - (5 * 60000);
  }

  // Fetch [start_mil, end_mil] downsampled via /async for every non-tag series
  // and merge in the points older than what is already loaded. onDone() fires
  // once every series settles.
  function _graphLoadRange(widget_id, ts, start_mil, end_mil, onDone) {
    const meta = window._graph_series_meta[widget_id] || [];
    const gen = (window._graph_load_gen[widget_id] = (window._graph_load_gen[widget_id] || 0) + 1);
    let pending = 0, started = false;
    ts.showLoading();
    const finish = function () {
      if (gen !== window._graph_load_gen[widget_id]) return;
      ts.hideLoading();
      ts.redraw();
      if (onDone) onDone();
    };
    meta.forEach(function (m, idx) {
      if (!m || m.type === 'tag' || idx >= ts.seriesCount) return;
      started = true; pending++;
      const url = '/async/' + m.id + '/' + m.type + '/' + m.measure + '/' +
                  Math.round(start_mil) / 1000 + '/' + Math.round(end_mil) / 1000;
      $.getJSON(url, function (data, txt, jq) {
        if (gen !== window._graph_load_gen[widget_id]) return;
        if (jq.status !== 204 && data && data.length) {
          ts.prepend(idx, data.map(function (d) { return [d[0] * 1000, d[1]]; }));
        }
      }).always(function () {
        if (gen !== window._graph_load_gen[widget_id]) return;
        pending--;
        if (pending <= 0) finish();
      });
    });
    if (!started) finish();
  }

  // Navigator / drag-zoom / date input: load earlier data on demand.
  function _graphOnUserZoom(widget_id, ts, e, xaxis_duration_min) {
    const now = Date.now();
    const live_min = now - (xaxis_duration_min * 60 * 1000);
    if (e.min == null || e.min >= live_min - 1000) return;
    const loaded_min = ts.oldest();
    if (loaded_min !== null && e.min >= loaded_min - 1000) return;
    const fetchEnd = (loaded_min !== null) ? loaded_min : live_min;
    if (window._graph_load_debounce[widget_id]) clearTimeout(window._graph_load_debounce[widget_id]);
    window._graph_load_debounce[widget_id] = setTimeout(function () {
      _graphLoadRange(widget_id, ts, e.min, fetchEnd, null);
    }, 250);
  }

  // Range buttons reach past the loaded data (1w / 1mo / All) — load it, then fit.
  function _graphRangeButtonClick(widget_id, ts, btn, xaxis_duration_min) {
    if (!btn) return;
    const now = Date.now();
    const live_min = now - (xaxis_duration_min * 60 * 1000);
    const isAll = (btn.type === 'all');
    const start = isAll ? 0 : (now - AoTTimeSeries.buttonSpanMs(btn));
    // Within the live window: the chart already zoomed.
    if (!isAll && start >= live_min - 1000) return;
    const loaded_min = ts.oldest();
    if (!isAll && loaded_min !== null && start >= loaded_min - 1000) {
      ts.setExtremes(start, now);  // already loaded
      return;
    }
    const fetchEnd = (loaded_min !== null) ? loaded_min : live_min;
    if (window._graph_load_debounce[widget_id]) clearTimeout(window._graph_load_debounce[widget_id]);
    window._graph_load_debounce[widget_id] = setTimeout(function () {
      _graphLoadRange(widget_id, ts, isAll ? 0 : start, fetchEnd, function () {
        if (isAll) { ts.setExtremes(null, null); return; }
        ts.setExtremes(start, now);
      });
    }, 250);
  }

  // Return to the live sliding window: trim earlier data and snap to [now-dur, now].
  function _graphResetToLive(widget_id, xaxis_duration_min) {
    const ts = widget[widget_id];
    if (!ts) return;
    // cancel any in-flight history loads
    window._graph_load_gen[widget_id] = (window._graph_load_gen[widget_id] || 0) + 1;
    ts.hideLoading();
    const epoch_max = Date.now();
    const epoch_min = epoch_max - (xaxis_duration_min * 60 * 1000);
    for (let i = 0; i < ts.seriesCount; i++) ts.removeBefore(i, epoch_min);
    ts.setExtremes(epoch_min, epoch_max);
    ts.redraw();
  }

  function graphMenuFunction(widget_id) {
    // 제목 래퍼는 이제 셸이 준다(`#widget-title-<uid>`). 예전에는 이 위젯이
    // 자기 제목 div 를 만들어 className 을 통째로 갈아끼웠는데, 그 방식은
    // 다른 클래스가 하나라도 붙는 순간 그것을 지운다. classList 로 바꾼다.
    var x = document.getElementById("widget-graph-responsive-controls-" + widget_id);
    var y = document.getElementById("widget-title-" + widget_id);
    if (x) { x.classList.toggle("responsive"); }
    if (y) { y.classList.toggle("responsive"); }
  }

  // Redraw a particular chart — deferred during scroll to avoid jank
  function redrawGraph(widget_id, refresh_seconds, xaxis_duration_min, xaxis_reset) {
    AoTChart.deferWhileScrolling(function () {
      const ts = widget[widget_id];
      if (!ts) return;
      // Don't snap back to the live window while the user is browsing earlier data.
      if (xaxis_reset && !_graphIsBrowsing(ts, xaxis_duration_min)) {
        const epoch_max = Date.now();
        ts.setExtremes(epoch_max - (xaxis_duration_min * 60 * 1000), epoch_max);
      }
      ts.redraw();
    });
  }

  // Note text keeps runs of spaces visible (the tooltip is HTML).
  function _graphNoteText(s) {
    return String(s == null ? '' : s).replace(/  /g, '\\u2591\\u2591');
  }

  // Retrieve initial graph data set from the past (duration set by user)
  function getPastDataSynchronousGraph(widget_id,
                       series,
                       unique_id,
                       measure_type,
                       measurement_id,
                       past_seconds) {
    const url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + past_seconds;
    const update_id = widget_id + "-" + series + "-" + unique_id + "-" + measure_type + '-' + measurement_id;
    // Record series metadata so on-demand history loads can target the right device.
    _graphRegisterSeries(widget_id, series, unique_id, measure_type, measurement_id);

    $.getJSON(url,
      function(data, responseText, jqXHR) {
        const ts = widget[widget_id];
        if (!ts || jqXHR.status === 204) return;
        let past_data = [];
        const note_key = widget_id + "_" + series;
        let newest_time = 0;

        for (let i = 0; i < data.length; i++) {
          const new_time = new Date(data[i][0] * 1000).getTime();

          if (measure_type === 'tag') {
            if (!(note_key in note_timestamps)) note_timestamps[note_key] = [];
            if (!note_timestamps[note_key].includes(new_time)) {
              past_data.push({ x: new_time, title: data[i][1], text: _graphNoteText(data[i][2]) });
              note_timestamps[note_key].push(new_time);
            }
          }
          else {
            past_data.push([new_time, data[i][1]]);
          }

          // Data is not guaranteed sorted — track the newest timestamp, not the last element.
          // Storing an older timestamp here makes every later poll re-fetch and re-add the
          // whole window, which grows the series without bound (hundreds of MB over hours).
          if (new_time > newest_time) newest_time = new_time;
        }
        if (newest_time > 0) {
          last_output_time_mil[update_id] = (measure_type === 'tag') ? newest_time + 3000 : newest_time;
        }

        const epoch_mil = Date.now();
        ts.setData(series, past_data);
        ts.setExtremes(epoch_mil - past_seconds * 1000, epoch_mil);
        ts.redraw();
      }
    );
  }

  // Retrieve chart data for the period since the last data acquisition (refresh period set by user)
  function retrieveLiveDataSynchronousGraph(widget_id,
                            series,
                            unique_id,
                            measure_type,
                            measurement_id,
                            xaxis_duration_min,
                            xaxis_reset,
                            refresh_seconds) {
    // Determine the timestamp of the last known measurement on the graph and
    // calculate the number of seconds from then until now, then build the URL
    // to query the measurements from that time period.
    let url = '';
    const epoch_mil = new Date().getTime();
    let update_id = widget_id + "-" + series + "-" + unique_id + "-" + measure_type + '-' + measurement_id;
    if (update_id in last_output_time_mil) {
      const past_seconds = Math.floor((epoch_mil - last_output_time_mil[update_id]) / 1000);  // seconds (integer)
      url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + past_seconds;
    } else {
      url = '/past/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + refresh_seconds;
    }

    $.getJSON(url,
      function(data, responseText, jqXHR) {
        const ts = widget[widget_id];
        if (!ts || jqXHR.status === 204) return;
        const note_key = widget_id + "_" + series;
        // The timestamp of the beginning of the graph (oldest timestamp allowed on the graph)
        const oldest_timestamp_allowed = epoch_mil - (xaxis_duration_min * 60 * 1000);
        // Points at or before this timestamp are already on the chart — the server window
        // may overlap, and re-adding them duplicates points without bound.
        const last_known_mil = last_output_time_mil[update_id] || 0;
        let newest_time = last_known_mil;

        for (let i = 0; i < data.length; i++) {
          const time_point = new Date(data[i][0] * 1000).getTime();

          if (measure_type === 'tag') {
            if (!(note_key in note_timestamps)) note_timestamps[note_key] = [];
            if (!note_timestamps[note_key].includes(time_point)) {
              ts.addPoint(series, { x: time_point, title: data[i][1], text: _graphNoteText(data[i][2]) });
              note_timestamps[note_key].push(time_point);
            }
            if (time_point > newest_time) newest_time = time_point;
          }
          else {
            if (time_point <= last_known_mil) continue;
            ts.addPoint(series, [time_point, data[i][1]]);
            if (time_point > newest_time) newest_time = time_point;
          }
        }

        // Store the newest timestamp seen (data is not guaranteed sorted)
        if (newest_time > last_known_mil) {
          last_output_time_mil[update_id] = (measure_type === 'tag') ? newest_time + 3000 : newest_time;
        }

        // Remove any points before beginning of chart. Skip while the user is
        // browsing earlier data, or it would delete the earlier history we just
        // loaded on the next refresh.
        if (!_graphIsBrowsing(ts, xaxis_duration_min)) {
          const gone = ts.removeBefore(series, oldest_timestamp_allowed);
          if (measure_type === 'tag' && note_timestamps[note_key]) {
            gone.forEach(function (pt) {
              const idx = note_timestamps[note_key].indexOf(pt.x);
              if (idx > -1) note_timestamps[note_key].splice(idx, 1);
            });
          }
        }

        // Redraw after cleanup so removed points never appear on screen
        redrawGraph(widget_id, refresh_seconds, xaxis_duration_min, xaxis_reset);
      }
    );
  }

  // Repeat function for retrieveLiveData()
  function getLiveDataSynchronousGraph(widget_id,
                       series,
                       unique_id,
                       measure_type,
                       measurement_id,
                       xaxis_duration_min,
                       xaxis_reset,
                       refresh_seconds) {
    const interval_key = widget_id + '_' + series + '_' + unique_id + '_' + measure_type;
    if (window._graph_intervals[interval_key]) {
      clearInterval(window._graph_intervals[interval_key]);
    }
    window._graph_intervals[interval_key] = setInterval(function () {
      retrieveLiveDataSynchronousGraph(widget_id,
                       series,
                       unique_id,
                       measure_type,
                       measurement_id,
                       xaxis_duration_min,
                       xaxis_reset,
                       refresh_seconds);
    }, refresh_seconds * 1000);
  }
""",


    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
{% set graph_output_ids = widget_options['measurements_output'] %}
{% set graph_input_ids = widget_options['measurements_input'] %}
{% set graph_function_ids = widget_options['measurements_function'] %}
{% set graph_pid_ids = widget_options['measurements_pid'] %}
{% set graph_note_tag_ids = widget_options['measurements_note_tag'] %}

  // Idempotency guard: when this script is re-run for live option preview (no
  // page reload), tear down the previous chart, its live-data intervals and the
  // per-widget history state so re-init starts clean (no leaked chart
  // instance, no stacked intervals, no stale series bookkeeping).
  try {
    if (typeof widget !== 'undefined' && widget['{{each_widget.unique_id}}']) {
      widget['{{each_widget.unique_id}}'].dispose();
      delete widget['{{each_widget.unique_id}}'];
    }
  } catch (e) {}
  if (window._graph_intervals) {
    Object.keys(window._graph_intervals).forEach(function (k) {
      if (k.indexOf('{{each_widget.unique_id}}' + '_') === 0) {
        clearInterval(window._graph_intervals[k]);
        delete window._graph_intervals[k];
      }
    });
  }
  if (window._graph_series_meta) { delete window._graph_series_meta['{{each_widget.unique_id}}']; }
  if (window._graph_load_debounce && window._graph_load_debounce['{{each_widget.unique_id}}']) {
    clearTimeout(window._graph_load_debounce['{{each_widget.unique_id}}']);
    delete window._graph_load_debounce['{{each_widget.unique_id}}'];
  }

  widget['{{each_widget.unique_id}}'] = AoTTimeSeries.create(document.getElementById('container-synchronous-graph-{{each_widget.unique_id}}'), {
  {% if widget_options['use_custom_colors'] and widget_variables['colors_graph'] -%}
    {% set color_list = widget_variables['colors_graph'] %}
    colors: [
    {%- for each_series in color_list if each_series['color'] -%}
      "{{each_series['color']}}"{% if not loop.last %},{% endif %}
     {%- endfor -%}],
  {%- endif -%}

    title: {
      text: {{ (each_widget.name if widget_options['enable_title'] else '')|tojson }},
      fontSizeEm: {{widget_options['graph_font_size_em_title']}}
    },
    legend: {
      enabled: {% if widget_options['enable_graph_legend'] %}true{% else %}false{% endif %},
      fontSizeEm: {{widget_options['graph_font_size_em_legend']}}
    },
    axisFontSizeEm: {{widget_options['graph_font_size_em_axes']}},
    alignTicks: {% if widget_options['enable_align_ticks'] %}true{% else %}false{% endif %},
    hideOnMobile: {% if widget_options.get('hide_axis_labels_on_mobile', True) %}true{% else %}false{% endif %},
    nightShading: {% if widget_options['enable_night_shading'] %}true{% else %}false{% endif %},
    navigator: {% if widget_options['enable_navbar'] %}true{% else %}false{% endif %},
    exporting: {
      enabled: {% if widget_options['enable_export'] %}true{% else %}false{% endif %},
      name: {{ each_widget.name|tojson }}
    },
    tooltipMs: true,
    columnMaxWidth: 3,
    rangeSelector: {
      enabled: {% if widget_options['enable_range_selector'] %}true{% else %}false{% endif %},
      buttons: [
        { type: 'minute', count: 1,  text: '{{_("1m")}}' },
        { type: 'minute', count: 5,  text: '{{_("5m")}}' },
        { type: 'minute', count: 15, text: '{{_("15m")}}' },
        { type: 'minute', count: 30, text: '{{_("30m")}}' },
        { type: 'hour',   count: 1,  text: '{{_("1h")}}' },
        { type: 'hour',   count: 6,  text: '{{_("6h")}}' },
        { type: 'day',    count: 1,  text: '{{_("1d")}}' },
        { type: 'week',   count: 1,  text: '{{_("1w")}}' },
        { type: 'month',  count: 1,  text: '{{_("1mo")}}' },
        { type: 'month',  count: 3,  text: '{{_("3mo")}}' },
        { type: 'all',               text: '{{_("All")}}' }
      ]
    },
    onRangeButton: function (i, btn) {
      _graphRangeButtonClick('{{each_widget.unique_id}}', widget['{{each_widget.unique_id}}'], btn, {{widget_variables['x_axis_duration_min']}});
    },
    onUserZoom: function (e) {
      _graphOnUserZoom('{{each_widget.unique_id}}', widget['{{each_widget.unique_id}}'], e, {{widget_variables['x_axis_duration_min']}});
    },
    yAxes: [
  {% for each_axis_meas in widget_variables['y_axes'] if each_axis_meas in dict_units %}
      {
        id: '{{each_axis_meas}}',
        unit: "{% if dict_units[each_axis_meas]['unit'] != '' %}{{dict_units[each_axis_meas]['unit']}}{% else %}{{dict_units[each_axis_meas]['name']}}{% endif %}",
        fontSizeEm: {{widget_options['graph_font_size_em_axes']}},
        titleFontSizeEm: {{widget_options['graph_font_size_em_axes_title']}},
    {% if widget_options['enable_manual_y_axis'] and
          widget_variables['custom_yaxes'][each_axis_meas]['minimum'] != widget_variables['custom_yaxes'][each_axis_meas]['maximum'] %}
        fixed: {
          min: {{widget_variables['custom_yaxes'][each_axis_meas]['minimum']}},
          max: {{widget_variables['custom_yaxes'][each_axis_meas]['maximum']}},
          startOnTick: {% if widget_options['enable_start_on_tick'] %}true{% else %}false{% endif %},
          endOnTick: {% if widget_options['enable_end_on_tick'] %}true{% else %}false{% endif %}
        }
    {% endif %}
      },
  {% endfor %}
    ],
    series: [
  {%- for input_and_measurement_ids in graph_input_ids -%}
    {%- set input_id = input_and_measurement_ids.split(',')[0] -%}
    {%- set this_input = table_input.query.filter(table_input.unique_id == input_id).first() -%}
    {%- if this_input -%}
      {%- set measurement_id = input_and_measurement_ids.split(',')[1] -%}
      {%- set ns = namespace() -%}

      {%- set ns.disable_data_grouping = false -%}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['disable_data_grouping'] %}
        {%- set ns.disable_data_grouping = true -%}
      {% endfor %}
      
      {%- set ns.series_type = "line" %}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['series_type'] %}
        {% set ns.series_type = each_series['series_type'] -%}
      {% endfor %}

      {%- if measurement_id in device_measurements_dict -%}
      {

        name: "{{this_input.name}}{% if device_measurements_dict[measurement_id].channel is not none %} CH{{device_measurements_dict[measurement_id].channel}}{% endif %}{% if device_measurements_dict[measurement_id].name %} {{device_measurements_dict[measurement_id].name}}{% endif %}",
        kind: '{{ 'column' if ns.series_type == 'column' else 'line' }}',
        step: {% if ns.series_type.startswith('step-') %}'{{ ns.series_type[5:] }}'{% else %}null{% endif %},
        grouping: { enabled: {% if ns.disable_data_grouping %}false{% else %}true{% endif %}, approximation: 'average' },
        valueSuffix: '
        {%- if device_measurements_dict[measurement_id].conversion_id -%}
          {{' ' + dict_units[table_conversion.query.filter(table_conversion.unique_id == device_measurements_dict[measurement_id].conversion_id).first().convert_unit_to]['unit']}}
        {%- elif device_measurements_dict[measurement_id].rescaled_unit -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].rescaled_unit]['unit']}}
        {%- else -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
        {%- endif -%}
          ',
        valueDecimals: 3,
        yAxis: '
        {%- if measurement_id in dict_measure_units -%}
          {{dict_measure_units[measurement_id]}}
        {%- endif -%}
            '
      },

      {%- endif -%}
    {%- endif -%}
  {%- endfor -%}

  {% for each_function in function -%}
    {%- for function_and_measurement_ids in graph_function_ids if each_function.unique_id == function_and_measurement_ids.split(',')[0] -%}
      {%- set measurement_id = function_and_measurement_ids.split(',')[1] -%}
      {%- set ns = namespace() -%}

      {%- set ns.disable_data_grouping = false -%}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['disable_data_grouping'] %}
        {%- set ns.disable_data_grouping = true -%}
      {% endfor %}
      
      {%- set ns.series_type = "line" %}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['series_type'] %}
        {% set ns.series_type = each_series['series_type'] -%}
      {% endfor %}

      {%- if measurement_id in device_measurements_dict -%}
      {
      name: "{{each_function.name}}{% if device_measurements_dict[measurement_id].channel is not none %} CH{{device_measurements_dict[measurement_id].channel}}{% endif %}{% if device_measurements_dict[measurement_id].name %} {{device_measurements_dict[measurement_id].name}}{% endif %}",
        kind: '{{ 'column' if ns.series_type == 'column' else 'line' }}',
        step: {% if ns.series_type.startswith('step-') %}'{{ ns.series_type[5:] }}'{% else %}null{% endif %},
      grouping: { enabled: {% if ns.disable_data_grouping %}false{% else %}true{% endif %}, approximation: 'average' },
      valueSuffix: '
        {%- if device_measurements_dict[measurement_id].conversion_id -%}
          {{' ' + dict_units[table_conversion.query.filter(table_conversion.unique_id == device_measurements_dict[measurement_id].conversion_id).first().convert_unit_to]['unit']}}
        {%- elif device_measurements_dict[measurement_id].rescaled_unit -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].rescaled_unit]['unit']}}
        {%- else -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
        {%- endif -%}
        ',
      valueDecimals: 3,
      yAxis: '
        {%- if measurement_id in dict_measure_units -%}
          {{dict_measure_units[measurement_id]}}
        {%- endif -%}
          '
    },

      {%- endif -%}
    {%- endfor -%}
  {% endfor %}

  {%- for output_and_measurement_ids in graph_output_ids -%}
    {%- set output_id = output_and_measurement_ids.split(',')[0] -%}
    {%- set this_output = table_output.query.filter(table_output.unique_id == output_id).first() -%}
    {%- if this_output -%}
      {%- set measurement_id = output_and_measurement_ids.split(',')[1] -%}
      {%- set ns = namespace() -%}

      {%- set ns.disable_data_grouping = false -%}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['disable_data_grouping'] %}
        {%- set ns.disable_data_grouping = true -%}
      {% endfor %}
      
      {%- set ns.series_type = "column" %}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['series_type'] %}
        {% set ns.series_type = each_series['series_type'] -%}
      {% endfor %}

      {%- if measurement_id in device_measurements_dict -%}
      {
        name: "{{this_output.name}}{% if device_measurements_dict[measurement_id].channel is not none %} CH{{device_measurements_dict[measurement_id].channel}}{% endif %}{% if device_measurements_dict[measurement_id].name %} {{device_measurements_dict[measurement_id].name}}{% endif %}",
        kind: '{{ 'column' if ns.series_type == 'column' else 'line' }}',
        step: {% if ns.series_type.startswith('step-') %}'{{ ns.series_type[5:] }}'{% else %}null{% endif %},
        grouping: { enabled: {% if ns.disable_data_grouping %}false{% else %}true{% endif %}, approximation: 'average' },
        valueSuffix: '
        {%- if device_measurements_dict[measurement_id].conversion_id -%}
          {{' ' + dict_units[table_conversion.query.filter(table_conversion.unique_id == device_measurements_dict[measurement_id].conversion_id).first().convert_unit_to]['unit']}}
        {%- elif device_measurements_dict[measurement_id].rescaled_unit -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].rescaled_unit]['unit']}}
        {%- else -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
        {%- endif -%}
          ',
        valueDecimals: 3,
        yAxis: '
        {%- if measurement_id in dict_measure_units -%}
          {{dict_measure_units[measurement_id]}}
        {%- endif -%}
            '
      },

      {%- endif -%}
    {%- endif -%}
  {%- endfor -%}

  {%- for each_pid in pid -%}
    {%- for pid_and_measurement_ids in graph_pid_ids if each_pid.unique_id == pid_and_measurement_ids.split(',')[0] -%}
      {%- set measurement_id = pid_and_measurement_ids.split(',')[1] -%}
      {%- set ns = namespace() -%}

      {%- set ns.disable_data_grouping = false -%}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['disable_data_grouping'] %}
        {%- set ns.disable_data_grouping = true -%}
      {% endfor %}
      
      {%- set ns.series_type = "line" %}
      {% for each_series in widget_variables['colors_graph'] if each_series['measure_id'] == measurement_id and each_series['series_type'] %}
        {% set ns.series_type = each_series['series_type'] -%}
      {% endfor %}

      {%- if measurement_id in device_measurements_dict -%}
    {
      name: "{{each_pid.name}}{% if device_measurements_dict[measurement_id].channel is not none %} CH{{device_measurements_dict[measurement_id].channel}}{% endif %}{% if device_measurements_dict[measurement_id].name %} {{device_measurements_dict[measurement_id].name}}{% endif %}",
        kind: '{{ 'column' if ns.series_type == 'column' else 'line' }}',
        step: {% if ns.series_type.startswith('step-') %}'{{ ns.series_type[5:] }}'{% else %}null{% endif %},
      grouping: { enabled: {% if ns.disable_data_grouping %}false{% else %}true{% endif %}, approximation: 'average' },
      valueSuffix: '
        {%- if measurement_id in dict_measure_units and dict_measure_units[measurement_id] in dict_units -%}
          {{' ' + dict_units[dict_measure_units[measurement_id]]['unit']}}
        {%- endif -%}
        ',
      valueDecimals: 3,
      yAxis: '
        {%- if measurement_id in dict_measure_units -%}
          {{dict_measure_units[measurement_id]}}
        {%- endif -%}
          '
    },

      {%- endif -%}
    {%- endfor -%}
  {% endfor %}

  {%- for each_tag in tags -%}
    {%- for each_graph_note_tag_id in graph_note_tag_ids if each_tag.unique_id == each_graph_note_tag_id.split(',')[0] -%}
      {
        name: 'Note Tag: {{each_tag.name}}',
        kind: 'flags'
      },
    {% endfor %}
  {% endfor %}

    ]
  });

    {% set count_series = [] -%}

    {%- for input_and_measurement_ids in graph_input_ids -%}
      {%- set input_id = input_and_measurement_ids.split(',')[0] -%}
      {%- set measurement_id = input_and_measurement_ids.split(',')[1] -%}
      {%- set all_input = table_input.query.filter(table_input.unique_id == input_id).all() -%}
      {%- if all_input -%}
        {% for each_input in all_input %}
    getPastDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_input.unique_id}}', 'input', '{{measurement_id}}', {{widget_variables['x_axis_duration_sec']}});
          {% if widget_options['enable_auto_refresh'] -%}
    getLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_input.unique_id}}', 'input', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
          {%- endif -%}
          {%- do count_series.append(1) -%}
        {%- endfor -%}
      {%- endif -%}
    {%- endfor -%}

    {%- for function_and_measurement_ids in graph_function_ids -%}
      {%- set function_id = function_and_measurement_ids.split(',')[0] -%}
      {%- set measurement_id = function_and_measurement_ids.split(',')[1] -%}
      {%- set all_function = table_function.query.filter(table_function.unique_id == function_id).all() -%}
      {%- if all_function -%}
        {% for each_function in all_function %}
    getPastDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_function.unique_id}}', 'function', '{{measurement_id}}', {{widget_variables['x_axis_duration_sec']}});
          {% if widget_options['enable_auto_refresh'] %}
    getLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_function.unique_id}}', 'function', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
          {% endif %}
          {%- do count_series.append(1) %}
        {%- endfor -%}
      {%- endif -%}
    {%- endfor -%}

    {%- for output_and_measurement_ids in graph_output_ids -%}
      {%- set output_id = output_and_measurement_ids.split(',')[0] -%}
      {%- set measurement_id = output_and_measurement_ids.split(',')[1] -%}
      {%- set all_output = table_output.query.filter(table_output.unique_id == output_id).all() -%}
      {%- if all_output -%}
        {% for each_output in all_output %}
    getPastDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_output.unique_id}}', 'output', '{{measurement_id}}', {{widget_variables['x_axis_duration_sec']}});
          {% if widget_options['enable_auto_refresh'] -%}
    getLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_output.unique_id}}', 'output', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
          {%- endif -%}
          {%- do count_series.append(1) -%}
        {%- endfor -%}
      {%- endif -%}
    {%- endfor -%}

    {%- for each_pid in pid -%}
      {%- for pid_and_measurement_id in graph_pid_ids if each_pid.unique_id == pid_and_measurement_id.split(',')[0] %}
        {%- set measurement_id = pid_and_measurement_id.split(',')[1] -%}
    getPastDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_pid.unique_id}}', 'pid', '{{measurement_id}}', {{widget_variables['x_axis_duration_sec']}});
    {% if widget_options['enable_auto_refresh'] %}
    getLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_pid.unique_id}}', 'pid', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
    {% endif %}
        {%- do count_series.append(1) %}
      {%- endfor -%}
    {%- endfor -%}

    {%- for each_tag in tags -%}
      {%- for tag_and_measurement_id in graph_note_tag_ids if each_tag.unique_id == tag_and_measurement_id.split(',')[0] %}
        {%- set measurement_id = tag_and_measurement_id.split(',')[1] -%}
    getPastDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_tag.unique_id}}', 'tag', '{{measurement_id}}', {{widget_variables['x_axis_duration_sec']}});
    {% if widget_options['enable_auto_refresh'] %}
    getLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_tag.unique_id}}', 'tag', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
    {% endif %}
        {%- do count_series.append(1) %}
      {%- endfor -%}
    {%- endfor -%}

  $('#updateData{{each_widget.unique_id}}').off('click').on('click', function() {
    {% set count_series = [] -%}

    {% for each_output in output -%}
      {% for output_and_measurement_ids in graph_output_ids if each_output.unique_id == output_and_measurement_ids.split(',')[0] %}
        {%- set measurement_id = output_and_measurement_ids.split(',')[1] -%}
    retrieveLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_output.unique_id}}', 'output', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
        {%- do count_series.append(1) %}
      {% endfor %}
    {%- endfor -%}

    {% for each_input in input -%}
      {% for input_and_measurement_ids in graph_input_ids if each_input.unique_id == input_and_measurement_ids.split(',')[0] %}
        {%- set measurement_id = input_and_measurement_ids.split(',')[1] -%}
    retrieveLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_input.unique_id}}', 'input', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
        {%- do count_series.append(1) %}
      {% endfor %}
    {%- endfor -%}

    {% for each_function in function -%}
      {% for function_and_measurement_id in graph_function_ids if each_function.unique_id == function_and_measurement_id.split(',')[0] %}
        {%- set measurement_id = function_and_measurement_id.split(',')[1] -%}
    retrieveLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_function.unique_id}}', 'function', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
        {%- do count_series.append(1) %}
      {% endfor %}
    {%- endfor -%}

    {% for each_pid in pid -%}
      {% for pid_and_measurement_id in graph_pid_ids if each_pid.unique_id == pid_and_measurement_id.split(',')[0] %}
        {%- set measurement_id = pid_and_measurement_id.split(',')[1] -%}
    retrieveLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_pid.unique_id}}', 'pid', '{{measurement_id}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
        {%- do count_series.append(1) %}
      {% endfor %}
    {%- endfor -%}

    {%- for each_tag in tag -%}
      {% for each_id_and_measure in graph_note_tag_ids if each_pid.unique_id == each_id_and_measure.split(',')[0] %}
    retrieveLiveDataSynchronousGraph('{{each_widget.unique_id}}', {{count_series|count}}, '{{each_id_and_measure.split(',')[1]}}', '{{each_id_and_measure.split(',')[0]}}', {{widget_variables['x_axis_duration_min']}}, {{widget_options['enable_xaxis_reset']|int}}, {{widget_options['refresh_seconds']}});
        {%- do count_series.append(1) %}
      {% endfor %}
    {%- endfor -%}
  });

  $('#resetZoom{{each_widget.unique_id}}').off('click').on('click', function() {
    // Return to the live sliding window (trims any browsed-in earlier history).
    _graphResetToLive('{{each_widget.unique_id}}', {{widget_variables['x_axis_duration_min']}});
  });

  $('#showhidebutton{{each_widget.unique_id}}').off('click').on('click', function() {
    const ts = widget['{{each_widget.unique_id}}'];
    if (ts) ts.toggleAll();
  });
""",
}


def data_grouping_graph(form, error):
    """
    Get checkbox options for data grouping
    :param form: form object submitted by user on web page
    :param error: list of accumulated errors to add to
    :return:
    """
    list_data_grouping = []
    for key in form.keys():
        if 'disable_data_grouping' in key:
            list_data_grouping.append(key[22:])
    return list_data_grouping, error


def series_type_graph(form, error):
    """
    Get select options for series type
    :param form: form object submitted by user on web page
    :param error: list of accumulated errors to add to
    :return:
    """
    series_types = {}
    for key in form.keys():
        if 'series_type' in key:
            for value in form.getlist(key):
                if value not in ["column", "line", "step-left", "step-center", "step-right"]:
                    error.append("Invalid series type")
                series_types[key[12:]] = value
    return series_types, error


def custom_yaxes_str_from_form(form):
    """
    Parse several yaxis min/max inputs
    :param form: UI form submitted by aot
    :return: string of CSV data sets separated by ';'
    """
    # Parse custom y-axis options from the UI form
    yaxes = {}
    for key in form.keys():
        if 'custom_yaxis_name_' in key:
            for value in form.getlist(key):
                unique_number = key[18:]
                if unique_number not in yaxes:
                    yaxes[unique_number] = {}
                yaxes[unique_number]['name'] = value
        if 'custom_yaxis_min_' in key:
            for value in form.getlist(key):
                unique_number = key[17:]
                if unique_number not in yaxes:
                    yaxes[unique_number] = {}
                yaxes[unique_number]['minimum'] = value
        if 'custom_yaxis_max_' in key:
            for value in form.getlist(key):
                unique_number = key[17:]
                if unique_number not in yaxes:
                    yaxes[unique_number] = {}
                yaxes[unique_number]['maximum'] = value
    # Create a list of CSV sets in the format 'y-axis, minimum, maximum'
    yaxes_list = []
    for _, yaxis_type in yaxes.items():
        yaxes_list.append('{},{},{}'.format(
            yaxis_type['name'], yaxis_type['minimum'], yaxis_type['maximum']))
    # Join the list of CSV sets with ';'
    return yaxes_list


def is_rgb_color(color_hex):
    """
    Check if string is a hex color value for the web UI
    :param color_hex: string to check if it represents a hex color value
    :return: bool
    """
    return bool(re.compile(r'#[a-fA-F0-9]{6}$').match(color_hex))


def custom_colors_graph(form, error):
    """
    Get variable number of graph color inputs, turn into CSV string
    :param form: form object submitted by user on web page
    :param error: list of accumulated errors to add to
    :return:
    """
    colors = {}
    short_list = []
    for key in form.keys():
        if 'color_number' in key:
            for value in form.getlist(key):
                if not is_rgb_color(value):
                    error.append("Invalid hex color value")
                colors[key[12:]] = value
    sorted_list = [(k, colors[k]) for k in sorted(colors)]
    for each_color in sorted_list:
        short_list.append(each_color[1])
    return short_list, error


def dict_custom_colors(widget_options):
    """
    Generate a dictionary of custom colors from CSV strings saved in the
    database. If custom colors aren't already saved, fill in with a default
    palette.

    :return: dictionary of graph_ids and lists of custom colors
    """
    color_count = []
    # 전역 차트 시리즈 팔레트 (aot.config 단일 소스 + custom_ui chart_1..6 오버레이)
    from aot.aot_flask.utils.utils_theme import get_graph_series_palette
    default_palette = get_graph_series_palette(
        dark=flask_login.current_user.theme in THEMES_DARK)

    try:
        # Get current saved colors
        if widget_options['custom_colors']:  # Split into list
            colors = widget_options['custom_colors']
        else:  # Create empty list
            colors = []
        # Fill end of list with empty strings
        while len(colors) < len(default_palette):
            colors.append('')

        # Populate empty strings with default colors
        for x, _ in enumerate(default_palette):
            if colors[x] == '':
                colors[x] = default_palette[x]

        index_sum = 0
        total = []

        # NOTE: 아래 처리 순서(Input, Function, Output, PID, Tag)는 실제 차트 시리즈가
        # 추가되는 순서(위젯 템플릿의 series: 블록, devices_list = [input, function,
        # output, pid])와 반드시 일치해야 한다. 순서가 어긋나면 옵션에서 지정한 색상이
        # 엉뚱한 시리즈에 적용된다.
        if widget_options['measurements_input']:
            index = 0
            for each_set in widget_options['measurements_input']:
                if not each_set:
                    continue

                input_unique_id = each_set.split(',')[0]
                input_measure_id = each_set.split(',')[1]

                device_measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == input_measure_id).first()
                if device_measurement:
                    measurement_name = device_measurement.name
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == device_measurement.conversion_id).first()
                else:
                    measurement_name = None
                    conversion = None
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion)

                input_dev = Input.query.filter_by(unique_id=input_unique_id).first()

                # Custom colors
                if (index < len(widget_options['measurements_input']) and
                        len(colors) > index_sum + index):
                    color = colors[index_sum + index]
                else:
                    color = '#FF00AA'

                # Data grouping
                disable_data_grouping = False
                if 'disable_data_grouping' in widget_options and input_measure_id in widget_options['disable_data_grouping']:
                    disable_data_grouping = True

                # Series type
                series_type = 'line'
                if 'series_type' in widget_options and input_measure_id in widget_options['series_type']:
                    series_type = widget_options['series_type'][input_measure_id]

                if None not in [input_dev, device_measurement]:
                    total.append({
                        'unique_id': input_unique_id,
                        'measure_id': input_measure_id,
                        'type': 'Input',
                        'name': input_dev.name,
                        'channel': channel,
                        'unit': unit,
                        'measure': measurement,
                        'measure_name': measurement_name,
                        'color': color,
                        'disable_data_grouping': disable_data_grouping,
                        'series_type': series_type
                    })
                    index += 1
            index_sum += index

        if widget_options['measurements_function']:
            index = 0
            for each_set in widget_options['measurements_function']:
                if not each_set:
                    continue

                function_unique_id = each_set.split(',')[0]
                function_measure_id = each_set.split(',')[1]

                device_measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == function_measure_id).first()
                if device_measurement:
                    measurement_name = device_measurement.name
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == device_measurement.conversion_id).first()
                else:
                    measurement_name = None
                    conversion = None
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion)

                function = CustomController.query.filter_by(unique_id=function_unique_id).first()

                # Custom colors
                if (index < len(widget_options['measurements_function']) and
                        len(colors) > index_sum + index):
                    color = colors[index_sum + index]
                else:
                    color = '#FF00AA'

                # Data grouping
                disable_data_grouping = False
                if 'disable_data_grouping' in widget_options and function_measure_id in widget_options['disable_data_grouping']:
                    disable_data_grouping = True

                # Series type
                series_type = 'line'
                if 'series_type' in widget_options and function_measure_id in widget_options['series_type']:
                    series_type = widget_options['series_type'][function_measure_id]

                if function is not None:
                    total.append({
                        'unique_id': function_unique_id,
                        'measure_id': function_measure_id,
                        'type': 'Function',
                        'name': function.name,
                        'channel': channel,
                        'unit': unit,
                        'measure': measurement,
                        'measure_name': measurement_name,
                        'color': color,
                        'disable_data_grouping': disable_data_grouping,
                        'series_type': series_type
                    })
                    index += 1
            index_sum += index

        if widget_options['measurements_output']:
            index = 0
            for each_set in widget_options['measurements_output']:
                if not each_set:
                    continue

                output_unique_id = each_set.split(',')[0]
                output_measure_id = each_set.split(',')[1]

                device_measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == output_measure_id).first()
                if device_measurement:
                    measurement_name = device_measurement.name
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == device_measurement.conversion_id).first()
                else:
                    measurement_name = None
                    conversion = None
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion)

                output = Output.query.filter_by(unique_id=output_unique_id).first()

                if (index < len(widget_options['measurements_output']) and
                        len(colors) > index_sum + index):
                    color = colors[index_sum + index]
                else:
                    color = '#FF00AA'

                # Data grouping
                disable_data_grouping = False
                if 'disable_data_grouping' in widget_options and output_measure_id in widget_options['disable_data_grouping']:
                    disable_data_grouping = True

                # Series type
                series_type = 'column'
                if 'series_type' in widget_options and output_measure_id in widget_options['series_type']:
                    series_type = widget_options['series_type'][output_measure_id]

                if None not in [output, device_measurement]:
                    total.append({
                        'unique_id': output_unique_id,
                        'measure_id': output_measure_id,
                        'type': 'Output',
                        'name': output.name,
                        'channel': channel,
                        'unit': unit,
                        'measure': measurement,
                        'measure_name': measurement_name,
                        'color': color,
                        'disable_data_grouping': disable_data_grouping,
                        'series_type': series_type
                    })
                    index += 1
            index_sum += index

        if widget_options['measurements_pid']:
            index = 0
            for each_set in widget_options['measurements_pid']:
                if not each_set:
                    continue

                pid_unique_id = each_set.split(',')[0]
                pid_measure_id = each_set.split(',')[1]

                device_measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == pid_measure_id).first()
                if device_measurement:
                    measurement_name = device_measurement.name
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == device_measurement.conversion_id).first()
                else:
                    measurement_name = None
                    conversion = None
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion)

                pid = PID.query.filter_by(unique_id=pid_unique_id).first()

                # Custom colors
                if (index < len(widget_options['measurements_pid']) and
                        len(colors) > index_sum + index):
                    color = colors[index_sum + index]
                else:
                    color = '#FF00AA'

                # Data grouping
                disable_data_grouping = False
                if 'disable_data_grouping' in widget_options and pid_measure_id in widget_options['disable_data_grouping']:
                    disable_data_grouping = True

                # Series type
                series_type = 'line'
                if 'series_type' in widget_options and pid_measure_id in widget_options['series_type']:
                    series_type = widget_options['series_type'][pid_measure_id]

                if None not in [pid, device_measurement]:
                    total.append({
                        'unique_id': pid_unique_id,
                        'measure_id': pid_measure_id,
                        'type': 'PID',
                        'name': pid.name,
                        'channel': channel,
                        'unit': unit,
                        'measure': measurement,
                        'measure_name': measurement_name,
                        'color': color,
                        'disable_data_grouping': disable_data_grouping,
                        'series_type': series_type
                    })
                    index += 1
            index_sum += index

        if widget_options['measurements_note_tag']:
            index = 0
            for each_set in widget_options['measurements_note_tag']:
                if not each_set:
                    continue

                tag_unique_id = each_set.split(',')[0]

                device_measurement = NoteTags.query.filter_by(unique_id=tag_unique_id).first()

                if (index < len(widget_options['measurements_note_tag']) and
                        len(colors) > index_sum + index):
                    color = colors[index_sum + index]
                else:
                    color = '#FF00AA'
                if device_measurement is not None:
                    total.append({
                        'unique_id': tag_unique_id,
                        'measure_id': None,
                        'type': 'Tag',
                        'name': device_measurement.name,
                        'channel': None,
                        'unit': None,
                        'measure': None,
                        'measure_name': None,
                        'color': color,
                        'disable_data_grouping': None,
                        'series_type': None
                    })
                    index += 1
            index_sum += index

        color_count += total
    except IndexError:
        logger.exception("Index")
    except Exception:
        logger.exception("Exception")

    return color_count


def check_func(all_devices,
               unique_id,
               y_axes,
               measurement,
               dict_measurements,
               device_measurements,
               input_dev,
               output,
               function,
               unit=None):
    """
    Generate a list of y-axes for Synchronous and Asynchronous Graphs
    :param all_devices: Input, Output, and PID SQL entries of a table
    :param unique_id: The ID of the measurement
    :param y_axes: empty list to populate
    :param measurement:
    :param dict_measurements:
    :param device_measurements:
    :param input_dev:
    :param output:
    :param function
    :param unit:
    :return: None
    """
    # Iterate through each device entry
    for each_device in all_devices:

        # If the ID saved to the dashboard element matches the table entry ID
        if each_device.unique_id == unique_id:

            use_unit = use_unit_generate(
                device_measurements, input_dev, output, function)

            # Add duration
            if measurement == 'duration_time':
                if 'second' not in y_axes:
                    y_axes.append('second')

            # Add duty cycle
            elif measurement == 'duty_cycle':
                if 'percent' not in y_axes:
                    y_axes.append('percent')

            # Use custom-converted units
            elif (unique_id in use_unit and
                  measurement in use_unit[unique_id] and
                  use_unit[unique_id][measurement]):
                measure_short = use_unit[unique_id][measurement]
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # Find the y-axis the setpoint or bands apply to
            elif measurement in ['setpoint', 'setpoint_band_min', 'setpoint_band_max']:
                for each_input in input_dev:
                    if each_input.unique_id == each_device.measurement.split(',')[0]:
                        pid_measurement = each_device.measurement.split(',')[1]

                        # If PID uses input with custom conversion, use custom unit
                        if (each_input.unique_id in use_unit and
                                pid_measurement in use_unit[each_input.unique_id] and
                                use_unit[each_input.unique_id][pid_measurement]):
                            measure_short = use_unit[each_input.unique_id][pid_measurement]
                            if measure_short not in y_axes:
                                y_axes.append(measure_short)
                        # Else use default unit for input measurement
                        else:
                            if pid_measurement in dict_measurements:
                                measure_short = dict_measurements[pid_measurement]['meas']
                                if measure_short not in y_axes:
                                    y_axes.append(measure_short)

            # Append all other measurements if they don't already exist
            elif measurement in dict_measurements and not unit:
                measure_short = dict_measurements[measurement]['meas']
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # use custom y-axis
            elif measurement not in dict_measurements or unit not in dict_measurements[measurement]['units']:
                meas_name = '{meas}_{un}'.format(meas=measurement, un=unit)
                if meas_name not in y_axes and unit:
                    y_axes.append(meas_name)

    return y_axes


def graph_y_axes(dict_measurements, widget_options):
    """Determine which y-axes to use for each Graph."""
    y_axes = []

    function = CustomController.query.all()
    device_measurements = DeviceMeasurements.query.all()
    input_dev = Input.query.all()
    output = Output.query.all()
    pid = PID.query.all()

    devices_list = [input_dev, function, output, pid]

    # Iterate through device tables
    for each_device in devices_list:

        if each_device == output and widget_options['measurements_output']:
            dev_and_measure_ids = widget_options['measurements_output']
        elif each_device == input_dev and widget_options['measurements_input']:
            dev_and_measure_ids = widget_options['measurements_input']
        elif each_device == function and widget_options['measurements_function']:
            dev_and_measure_ids = widget_options['measurements_function']
        elif each_device == pid and widget_options['measurements_pid']:
            dev_and_measure_ids = widget_options['measurements_pid']
        else:
            dev_and_measure_ids = []

        # Iterate through each set of ID and measurement of the
        # dashboard element
        for each_id_measure in dev_and_measure_ids:

            if ',' in each_id_measure:

                measure_id = each_id_measure.split(',')[1]

                for each_measurement in device_measurements:
                    if each_measurement.unique_id == measure_id:

                        unit = None
                        if each_measurement.measurement_type == 'setpoint':
                            setpoint_pid = PID.query.filter(PID.unique_id == each_measurement.device_id).first()
                            if setpoint_pid and ',' in setpoint_pid.measurement:
                                pid_measurement = setpoint_pid.measurement.split(',')[1]
                                setpoint_measurement = DeviceMeasurements.query.filter(
                                    DeviceMeasurements.unique_id == pid_measurement).first()
                                if setpoint_measurement:
                                    conversion = Conversion.query.filter(
                                        Conversion.unique_id == setpoint_measurement.conversion_id).first()
                                    _, unit, measurement = return_measurement_info(setpoint_measurement, conversion)
                        else:
                            conversion = Conversion.query.filter(
                                Conversion.unique_id == each_measurement.conversion_id).first()
                            _, unit, _ = return_measurement_info(each_measurement, conversion)

                        if unit:
                            if not y_axes:
                                y_axes = [unit]
                            elif y_axes and unit not in y_axes:
                                y_axes.append(unit)

            elif len(each_id_measure.split(',')) == 4:

                unit = each_id_measure.split(',')[2]

                if not y_axes:
                    y_axes = [unit]
                elif y_axes and unit not in y_axes:
                    y_axes.append(unit)

            elif len(each_id_measure.split(',')) == 2:

                unique_id = each_id_measure.split(',')[0]
                measurement = each_id_measure.split(',')[1]

                y_axes = check_func(
                    each_device,
                    unique_id,
                    y_axes,
                    measurement,
                    dict_measurements,
                    device_measurements,
                    input_dev,
                    output,
                    function)

            elif len(each_id_measure.split(',')) == 3:

                unique_id = each_id_measure.split(',')[0]
                measurement = each_id_measure.split(',')[1]
                unit = each_id_measure.split(',')[2]

                y_axes = check_func(
                    each_device,
                    unique_id,
                    y_axes,
                    measurement,
                    dict_measurements,
                    device_measurements,
                    input_dev,
                    output,
                    function,
                    unit=unit)

    return y_axes


def dict_custom_yaxes_min_max(yaxes, widget_options):
    """Generate a dictionary of the y-axis minimum and maximum for each graph."""
    dict_yaxes = {}

    for each_yaxis in yaxes:
        dict_yaxes[each_yaxis] = {}
        dict_yaxes[each_yaxis]['minimum'] = 0
        dict_yaxes[each_yaxis]['maximum'] = 0

        for each_custom_yaxis in widget_options['custom_yaxes']:
            if each_custom_yaxis.split(',')[0] == each_yaxis:
                dict_yaxes[each_yaxis]['minimum'] = each_custom_yaxis.split(',')[1]
                dict_yaxes[each_yaxis]['maximum'] = each_custom_yaxis.split(',')[2]

    return dict_yaxes
