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

import json
import os
import logging
import re

from flask import flash
from flask_babel import lazy_gettext

from aot.config import PATH_JS_USER
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

def execute_at_creation(error, new_widget, dict_widget):
    """ On widget creation, override min/max/colors etc. based on preset_config """
    custom_options_json = json.loads(new_widget.custom_options)

    # 1) Check preset_config
    preset = custom_options_json.get('preset_config', 'custom')

    # 2) Default custom color list
    # Global 5-band measurement palette (--aot-band-1..5) + custom_ui band_1..5 오버레이
    try:
        from aot.aot_flask.utils.utils_theme import get_band_palette
        color_list = get_band_palette()
    except Exception:
        color_list = ["#2DB4FF", "#54BCC1", "#32c85a", "#FEAE5F", "#CF5C58"]

    # 3) Override min/max, color array etc. based on the preset
    if preset == 'temperature':
        custom_options_json['min'] = -5
        custom_options_json['max'] = 45

    elif preset == 'humidity':
        # Reverse the color array
        color_list = list(reversed(color_list))

    elif preset == 'vpd':
        # VPD: min=0, max=3
        custom_options_json['min'] = 0
        custom_options_json['max'] = 3

        # Fix "stops" to 5 as well
        custom_options_json['stops'] = 5

        # Optionally pre-build VPD-specific ranges (explicit example)
        # e.g. [0~0.25], [0.25~0.5], [0.5~1.2], [1.2~2], [2~3]
        # Colors here use color_list
        # (if you want fixed ranges instead of user input, hard-code as below)
        custom_options_json['range_colors'] = [
            f"0,0.25,{color_list[0]}",
            f"0.25,0.5,{color_list[1]}",
            f"0.5,1.2,{color_list[2]}",
            f"1.2,2,{color_list[3]}",
            f"2,3,{color_list[4]}",
        ]

    # 4) Apply defaults if stops/min/max values are missing
    if 'stops' not in custom_options_json or custom_options_json['stops'] < 2:
        custom_options_json['stops'] = 2
    if 'min' not in custom_options_json:
        custom_options_json['min'] = 0
    if 'max' not in custom_options_json:
        custom_options_json['max'] = 100
    
    # 5) Set defaults for max_measure_age and refresh_seconds (important!)
    if 'max_measure_age' not in custom_options_json or custom_options_json['max_measure_age'] is None:
        custom_options_json['max_measure_age'] = 1800
    if 'refresh_seconds' not in custom_options_json or custom_options_json['refresh_seconds'] is None:
        custom_options_json['refresh_seconds'] = 30

    # 6) Auto-generate range_colors with the existing logic
    #    (if 'range_colors' already exists, it may be left as-is)
    if 'range_colors' not in custom_options_json:
        custom_options_json['range_colors'] = []
        stop = custom_options_json['min']
        maximum = custom_options_json['max']
        difference = float(maximum - stop)
        stop_size = difference / custom_options_json['stops']

        # First range
        custom_options_json['range_colors'].append(
            f"{stop},{stop + stop_size},{color_list[0]}"
        )
        # Remaining ranges
        for i in range(custom_options_json['stops'] - 1):
            stop += stop_size
            if i+1 < len(color_list):
                color = color_list[i+1]
            else:
                color = "#CF5C58"  # default (band-5)
            custom_options_json['range_colors'].append(
                f"{stop},{stop + stop_size},{color}"
            )

    new_widget.custom_options = json.dumps(custom_options_json)
    return error, new_widget


def execute_at_modification(
        mod_widget,
        request_form,
        custom_options_json_presave,
        custom_options_json_postsave):
    allow_saving = True
    page_refresh = True
    error = []

    # Parse the user-submitted color range form (without "range end")
    sorted_colors, error = custom_colors_gauge(request_form, error)

    # Apply the existing gauge_reformat_stops() logic
    sorted_colors = gauge_reformat_stops(
        custom_options_json_presave['stops'],
        custom_options_json_postsave['stops'],
        current_colors=sorted_colors)

    # Automatically fill in the "range end" values
    sorted_colors = fill_missing_highs(custom_options_json_postsave, sorted_colors)

    custom_options_json_postsave['range_colors'] = sorted_colors
    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave

def generate_page_variables(widget_unique_id, widget_options):
    # Retrieve custom colors for gauges
    colors_gauge_angular = []

    # 프리셋(temperature/humidity/vpd) 게이지는 렌더 시점에 항상 전역 밴드
    # 팔레트(custom_ui band_1..5 오버레이)를 따른다 — 생성 시 저장된 색에
    # 고정되지 않도록. 구간 수가 5가 아니면(사용자 변형) 저장색 유지.
    # 'custom' 프리셋은 위젯 개별 색을 그대로 사용한다.
    band_palette = None
    preset = widget_options.get('preset_config', 'custom')
    if preset in ('temperature', 'humidity', 'vpd'):
        try:
            from aot.aot_flask.utils.utils_theme import get_band_palette
            band_palette = get_band_palette()
            if preset == 'humidity':
                band_palette = list(reversed(band_palette))
        except Exception:
            band_palette = None

    try:
        if 'range_colors' in widget_options and widget_options['range_colors']:
            color_areas = widget_options['range_colors']
        else:
            color_areas = []

        use_band = band_palette and len(color_areas) == len(band_palette)
        for i, each_range in enumerate(color_areas):
            colors_gauge_angular.append({
                'low': each_range.split(',')[0],
                'high': each_range.split(',')[1],
                'hex': band_palette[i] if use_band else each_range.split(',')[2]})
    except IndexError:
        logger.exception(1)
        # flash("Colors Index Error", "error")

    return {"colors_gauge_angular": colors_gauge_angular}


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_gauge_angular',
    'widget_name': lazy_gettext('AoT Circular Gauge'),
    'widget_library': 'Highcharts',
    'no_class': True,

    # Widget description
    'message': lazy_gettext('Displays data in a circular gauge. Ensure the maximum value option matches the last section (High) for correct display. Selecting presets like Temperature, Humidity, or VPD automatically sets min/max values and color sections.'),

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': generate_page_variables,

    'dependencies_module': [
        ('bash-commands',
        [
            os.path.join(PATH_JS_USER, 'highstock-9.1.2.js'),
            os.path.join(PATH_JS_USER, 'highcharts-more-9.1.2.js')
        ],
        [
            'rm -rf Highcharts-Stock-9.1.2.zip',
            'wget https://code.highcharts.com/zips/Highcharts-Stock-9.1.2.zip 2>&1',
            'unzip Highcharts-Stock-9.1.2.zip -d Highcharts-Stock-9.1.2',
            f'cp -rf Highcharts-Stock-9.1.2/code/highstock.js {os.path.join(PATH_JS_USER, "highstock-9.1.2.js")}',
            f'cp -rf Highcharts-Stock-9.1.2/code/highstock.js.map {os.path.join(PATH_JS_USER, "highstock.js.map")}',
            f'cp -rf Highcharts-Stock-9.1.2/code/highcharts-more.js {os.path.join(PATH_JS_USER, "highcharts-more-9.1.2.js")}',
            f'cp -rf Highcharts-Stock-9.1.2/code/highcharts-more.js.map {os.path.join(PATH_JS_USER, "highcharts-more.js.map")}',
            'rm -rf Highcharts-Stock-9.1.2.zip',
            'rm -rf Highcharts-Stock-9.1.2'
        ])
    ],

    'dependencies_message': lazy_gettext('Highcharts is free for open source and personal use. However, if used as part of a commercial product, a commercial license may be required. Please check https://shop.highsoft.com for the most accurate information.'),

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': generate_page_variables,

    'widget_width': 5,
    'widget_height': 10,

    'custom_options': [
        {
            'id': 'measurement',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function',
                'PID'
            ],
            'name': lazy_gettext('Measurement'),
            'phrase': lazy_gettext('Select the measurement to display')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 1800,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Set the maximum valid time for the measurement')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 30.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Set the refresh interval for the widget')
        },
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Decimal Places'),
            'phrase': lazy_gettext('Set the number of decimal places to display')
        },
        {
            'id': 'min',
            'type': 'float',
            'default_value': 0,
            'name': lazy_gettext('Minimum Value'),
            'phrase': lazy_gettext('Set the minimum value of the gauge')
        },
        {
            'id': 'max',
            'type': 'float',
            'default_value': 100,
            'name': lazy_gettext('Maximum Value'),
            'phrase': lazy_gettext('Set the maximum value of the gauge')
        },
        {
            'id': 'stops',
            'type': 'integer',
            'default_value': 5,  # changed 4 -> 5
            'name': lazy_gettext('Number of Color Sections'),
            'phrase': lazy_gettext('Set the number of sections to distinguish gauge colors')
        },
        {
            'id': 'preset_config',
            'type': 'select',
            'default_value': 'custom',  # default: custom
            'options_select': [
                ('custom', lazy_gettext('Custom')),
                ('temperature', lazy_gettext('Temperature')),
                ('humidity', lazy_gettext('Humidity')),
                ('vpd', lazy_gettext('VPD'))
            ],
            'name': lazy_gettext('Preset Config'),
            'phrase': lazy_gettext('Selecting a preset configuration automatically applies default settings such as min/max values. Preset gauges follow the global band colors (Settings > Custom UI); choose Custom to set individual section colors.')
        },
        {
            # Data font size
            'id': 'text_font_size',
            'type': 'float',
            'default_value': 1.5,
            'name': lazy_gettext('Data Font Size'),
            'phrase': lazy_gettext('Set the font size of the data inside the gauge. Default is 1.5 (medium).')
        },
        {
            # Unit font size
            'id': 'unit_font_size',
            'type': 'float',
            'default_value': 0.7,
            'name': lazy_gettext('Unit Font Size'),
            'phrase': lazy_gettext('Set the font size of the unit inside the gauge. Default is 0.7 (small).')
        },
        {
            # Unit font size
            'id': 'unit_font_tick',
            'type': 'float',
            'default_value': 500,
            'name': lazy_gettext('Unit Font Weight'),
            'phrase': lazy_gettext('Set the font weight inside the gauge. Default is 500 (medium).')
        },
        {
            'id': 'text_y_offset',
            'type': 'float',
            'default_value': 30,
            'name': lazy_gettext('Data Position Offset'),
            'phrase': lazy_gettext('Set the vertical position offset of the data text inside the gauge (numeric only).')
        }        
    ],

    'widget_dashboard_head': """{% if "highstock" not in dashboard_dict %}
  <script src="{{ asset('highcharts-stack') }}"></script>
  {% set _dummy = dashboard_dict.update({"highstock": 1}) %}
{% endif %}

{% if current_user.theme in dark_themes %}
  <script type="text/javascript" src="/static/js/vendor/user_js/dark-unica-custom.js"></script>
{% endif %}
""",

    'widget_dashboard_title_bar': """<span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>""",

    # Actual widget display area
    'widget_dashboard_body': """<div class="not-draggable" id="container-gauge-{{each_widget.unique_id}}" style="position: absolute; left: 0; top: 0; bottom: 0; right: 0; overflow: hidden;"></div>""",

    # Section for editing color ranges on the settings screen
    # The "range end" field is completely removed. Only range start and color are shown
    'widget_dashboard_configure_options': """
        {% for n in range(widget_variables['colors_gauge_angular']|length) %}
          {% set index = '{0:0>2}'.format(n) %}
        <div class="form-row">
          <div class="col-auto">
            <label class="control-label" for="color_low_number{{index}}">[{{n}}] {{_('Section Start')}}</label>
            <div>
              <input class="form-control" id="color_low_number{{index}}" name="color_low_number{{index}}" type="text" value="{{widget_variables['colors_gauge_angular'][n]['low']}}">
            </div>
          </div>
          <div class="col-auto">
            <label class="control-label" for="color_hex_number{{index}}">[{{n}}] {{_('Color')}}</label>
            <div>
              <input id="color_hex_number{{index}}" name="color_hex_number{{index}}" placeholder="#000000" type="color" value="{{widget_variables['colors_gauge_angular'][n]['hex']}}">
            </div>
          </div>
        </div>
        {% endfor %}
        {# 역방향 저장: 이 위젯의 구간색(앞 5개)을 전역 밴드 색(custom_ui band_1..5)으로 #}
        <div class="form-row" style="margin-top: 8px;">
          <div class="col-auto">
            <button type="button" class="btn aot-pill-btn"
                    onclick="(function(btn){
                      var colors = [];
                      for (var i = 0; i < 5; i++) {
                        var el = document.getElementById('color_hex_number0' + i);
                        if (el && el.value) colors.push(el.value);
                      }
                      if (!colors.length) return;
                      var csrf = document.querySelector('input[name=csrf_token]');
                      fetch('/settings/custom_ui/global_colors', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.value : ''},
                        body: JSON.stringify({kind: 'band', colors: colors})
                      }).then(function(r){ return r.json().then(function(d){ return r.ok ? d : Promise.reject(new Error(d.error || 'failed')); }); })
                        .then(function(){ if (window.toastr) toastr.success('{{_('Saved as global band colors')}}'); })
                        .catch(function(e){ if (window.toastr) toastr.error(e.message); else alert(e.message); });
                    })(this)">{{_('Save as Global Band Colors')}}</button>
            <span class="aot-modal-body-text">{{_('Applies the first 5 section colors to Settings > Custom UI band colors.')}}</span>
          </div>
        </div>
    """,

    'widget_dashboard_js': """
  function getLastDataGaugeAngular(widget_id,
                       unique_id,
                       measure_type,
                       measurement_id,
                       max_measure_age_sec) {
    const url = '/last/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + max_measure_age_sec.toString();
    $.ajax(url, {
      success: function(data, responseText, jqXHR) {
        if (jqXHR.status === 204) {
          widget[widget_id].series[0].points[0].update(null);
        }
        else {
          const formattedTime = epoch_to_timestamp(data[0] * 1000);
          const measurement = data[1];
          widget[widget_id].series[0].points[0].update(measurement);
        }
      },
      error: function(jqXHR, textStatus, errorThrown) {
        widget[widget_id].series[0].points[0].update(null);
      }
    });
  }

  // Repeat function for getLastDataGaugeAngular()
  function repeatLastDataGaugeAngular(widget_id,
                          dev_id,
                          measure_type,
                          measurement_id,
                          period_sec,
                          max_measure_age_sec) {
    setInterval(function () {
      getLastDataGaugeAngular(widget_id,
                  dev_id,
                  measure_type,
                  measurement_id,
                  max_measure_age_sec)
    }, period_sec * 1000);
  }
""",

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
{%- set device_id = widget_options['measurement'].split(",")[0] -%}
{%- set measurement_id = widget_options['measurement'].split(",")[1] -%}

{% set measure = { 'measurement_id': None } %}
  widget['{{each_widget.unique_id}}'] = new Highcharts.chart({
    chart: {
      renderTo: 'container-gauge-{{each_widget.unique_id}}',
      type: 'gauge',
      animation: false,
      plotBackgroundColor: null,
      plotBackgroundImage: null,
      plotBorderWidth: 0,
      plotShadow: false,
      events: {
        load: function () {
          {% for each_input in input  if each_input.unique_id == device_id %}
          getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'input', '{{measurement_id}}', {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'input', '{{measurement_id}}', {{widget_options['refresh_seconds'] if widget_options['refresh_seconds'] else 30}}, {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          {%- endfor -%}
          
          {% for each_function in function if each_function.unique_id == device_id %}
          getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'function', '{{measurement_id}}', {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'function', '{{measurement_id}}', {{widget_options['refresh_seconds'] if widget_options['refresh_seconds'] else 30}}, {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          {%- endfor -%}

          {%- for each_pid in pid if each_pid.unique_id == device_id %}
          getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'pid', '{{measurement_id}}', {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id}}', 'pid', '{{measurement_id}}', {{widget_options['refresh_seconds'] if widget_options['refresh_seconds'] else 30}}, {{widget_options['max_measure_age'] if widget_options['max_measure_age'] else 120}});
          {%- endfor -%}
        }
      },
      spacingTop: 0,
      spacingLeft: 0,
      spacingRight: 0,
      spacingBottom: 0
    },

    title: null,

    exporting: {
      enabled: false
    },

    pane: {
        // Align with wind gauge layout:
        // - Horizontal padding 12% ⇒ size ≈ 76%
        // - Top padding ~4% ⇒ centerY ≈ 42% (since size/2 = 38%, 42-38 = 4%)
        center: [ '50%', '42%' ],
        size: '76%',
        startAngle: -120,
        endAngle: 120,
        background: [{
          backgroundColor: 'none',
          borderWidth: 0,
          outerRadius: '0%',
          innerRadius: '0%'
        }]
    },

    yAxis: {
        min: {{widget_options['min']}},
        max: {{widget_options['max']}},
        title: {
          text: '',
          y: 20
        },

        minColor: "#3e3f46",
        maxColor: "#3e3f46",

        minorTickInterval: 'auto',
        minorTickWidth: 0,
        minorTickLength: 0,
        minorTickPosition: 'inside',
        minorTickColor: '#666',

        tickPixelInterval: 50,
        tickWidth: 0,
        
        tickPosition: 'inside',
        tickLength: 0,
        tickColor: '#666',

        labels: {
            step: 2,
            rotation: 'auto',
            style: {
                color: 'var(--aot-color-text-secondary, #666666)'
            }
        },
        plotBands: [
          {% for n in range(widget_variables['colors_gauge_angular']|length) %}
            {% set index = '{0:0>2}'.format(n) %}
        {
            from: {{widget_variables['colors_gauge_angular'][n]['low']}},
            to: {{widget_variables['colors_gauge_angular'][n]['high']}},
            color: '{{widget_variables['colors_gauge_angular'][n]['hex']}}'
        },
          {% endfor %}
        ]
    },

    series: [{
      name: '
      {%- for each_input in input if each_input.unique_id == device_id -%}
        {%- if measurement_id in device_measurements_dict -%}
          {{each_input.name}} (
            {%- if not device_measurements_dict[measurement_id].single_channel -%}
              {{'CH' + (device_measurements_dict[measurement_id].channel|int)|string}}
            {%- endif -%}
            {%- if device_measurements_dict[measurement_id].measurement -%}
              {{', ' + dict_measurements[device_measurements_dict[measurement_id].measurement]['name']}}
            {%- endif -%}
          {%- endif -%}
      {%- endfor -%}
      
      {%- for each_function in function if each_function.unique_id == device_id -%}
        {{each_function.measure|safe}}
      {%- endfor -%}
      
      {%- for each_pid in pid if each_pid.unique_id == device_id -%}
        {{each_pid.measure|safe}}
      {%- endfor -%}
      )',
      data: [null],
      dataLabels: {
        enabled: true,
        useHTML: true,
        crop: false,
        overflow: 'allow',
        allowOverlap: true,
        borderWidth: 0,
        backgroundColor: 'none',
        style: {
          textOutline: 'none',
          color: 'var(--aot-color-text-primary, #333333)',
          fontWeight: '{{ widget_options.get("text_font_tick", 500) }}',
          fontSize: '{{ widget_options.get("text_font_size", 2) }}em'
        },
        y: {{ widget_options.get("text_y_offset", 30) }},
        formatter: function() {
          var dec = {{ widget_options.get("decimal_places", 1) }};
          var val = (this.y === null) ? '' : Highcharts.numberFormat(this.y, dec);
          var dataFontSize = {{ widget_options.get("text_font_size", 1.5) }};
          var unitFontSize = {{ widget_options.get("unit_font_size", 0.7) }};
          // Get the unit the existing way
          var unitLabel = {% if measurement_id in dict_measure_units and dict_measure_units[measurement_id] in dict_units and dict_units[dict_measure_units[measurement_id]]['unit'] %}
              '{{ dict_units[dict_measure_units[measurement_id]]["unit"] }}'
          {% else %}
              {%- if measurement_id in device_measurements_dict and device_measurements_dict[measurement_id].unit in dict_units -%}
                '{{ dict_units[device_measurements_dict[measurement_id].unit]["unit"] }}'
              {%- else -%}
                'N/A'
              {%- endif -%}
          {% endif %};
          return '<span style="font-size:var(--aot-fs-value)">' + val + '</span>' +
                '<span style="font-size:var(--aot-fs-unit);margin-left:0.2em">' + unitLabel + '</span>';
        }
      },
      yAxis: 0,
      dial: {
        backgroundColor: '{% if current_user.theme in dark_themes %}#e3e4f4{% else %}#3e3f46{% endif %}',
        baseWidth: 5
      },
      tooltip: {
      {%- for each_input in input if each_input.unique_id == device_id %}
        pointFormatter: function () {
          return this.series.name + ':<b> ' + Highcharts.numberFormat(this.y, 2) + ' {% if measurement_id in device_measurements_dict and device_measurements_dict[measurement_id].unit in dict_units %}{{ dict_units[device_measurements_dict[measurement_id].unit]["unit"] }}{% endif %}</b><br>';
        },
      {%- endfor -%}
        valueSuffix: '
      {%- for each_input in input if each_input.unique_id == device_id -%}
        {%- if measurement_id in device_measurements_dict and device_measurements_dict[measurement_id].unit in dict_units -%}
          {{' ' + dict_units[device_measurements_dict[measurement_id].unit]["unit"]}}
        {%- endif -%}
      {%- endfor -%}
      
      {%- for each_function in function if each_function.unique_id == device_id -%}
        {{' ' + each_function.measure_units|safe}}
      {%- endfor -%}
      
      {%- for each_pid in pid if each_pid.unique_id == device_id -%}
        {{' ' + each_pid.measure_units|safe}}
      {%- endfor -%}'
      }
    }],

    credits: {
      enabled: false,
      href: "https://github.com/AoT-inc/AoT",
      text: "aot"
    }
  });
"""}


def is_rgb_color(color_hex):
    """
    Check if string is a valid 6-digit hex color (e.g. #FF0000)
    """
    return bool(re.compile(r'#[a-fA-F0-9]{6}$').match(color_hex))


############################
# Version with the "range end" field removed
############################
def custom_colors_gauge(form, error):
    """
    Parse only "range start" (low) and "color" (hex). "range end" (high) is left blank when stored in sorted_colors.
    """
    sorted_colors = []
    colors_hex = {}

    for key in form.keys():
        # Only "color_low_number##" / "color_hex_number##" exist
        if 'color_low_number' in key or 'color_hex_number' in key:
            idx = int(key[16:])  # e.g. color_low_number00 -> index 00 -> int(0)
            if idx not in colors_hex:
                colors_hex[idx] = {}

        if 'color_hex_number' in key:
            for value in form.getlist(key):
                if not is_rgb_color(value):
                    error.append('Invalid hex color value')
                colors_hex[idx]['hex'] = value

        elif 'color_low_number' in key:
            for value in form.getlist(key):
                colors_hex[idx]['low'] = value

    # Temporarily store as "low,,hex" in index order
    for i in sorted(colors_hex.keys()):
        try:
            low_val = colors_hex[i].get('low', '0')
            hex_val = colors_hex[i].get('hex', '#000000')
            # Leave the middle (High) blank
            sorted_colors.append(f"{low_val},,{hex_val}")
        except Exception as err_msg:
            logger.exception(1)
            error.append(str(err_msg))

    return sorted_colors, error


def gauge_reformat_stops(current_stops, new_stops, current_colors=None):
    """Existing aot stops logic. Adjusts colors when the number of ranges grows or shrinks."""
    # Handle None values
    if new_stops is None:
        new_stops = 5  # Default value
    if current_stops is None:
        current_stops = 5  # Default value
    
    if current_colors:
        colors = current_colors
    else:
        # Default example of 5 colors (when newly added)
        # Global 5-band measurement palette (aot-theme-variables.css --aot-band-1..5)
        colors = ['0,20,#2DB4FF', '20,40,#54BCC1', '40,60,#32c85a', '60,80,#FEAE5F', '80,100,#CF5C58']

    if new_stops > current_stops:
        try:
            stop = float(colors[-1].split(",")[1])
        except:
            stop = 80
        for _ in range(new_stops - current_stops):
            stop += 20
            colors.append(f"{stop - 20},{stop},#CF5C58")

    elif new_stops < current_stops:
        colors = colors[:len(colors) - (current_stops - new_stops)]

    return colors


def fill_missing_highs(custom_options_json, sorted_colors):
    """
    For every range, automatically compute the middle (High) when it is blank:
    - The next range's Low becomes the current range's High
    - For the last range, the widget 'max' value becomes High
    """
    max_val = custom_options_json['max']

    for i in range(len(sorted_colors) - 1):
        low_i, high_i, color_i = sorted_colors[i].split(',')
        low_next, high_next, color_next = sorted_colors[i+1].split(',')

        # If the current range's High is blank, use the next range's Low
        if not high_i.strip():
            high_i = low_next
            sorted_colors[i] = f"{low_i},{high_i},{color_i}"

    # Handle the last range
    last_idx = len(sorted_colors) - 1
    low_last, high_last, color_last = sorted_colors[last_idx].split(',')
    if not high_last.strip():
        high_last = str(max_val)  # the last range's end is max
        sorted_colors[last_idx] = f"{low_last},{high_last},{color_last}"

    return sorted_colors