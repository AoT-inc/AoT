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
import re

from flask import flash
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)


def _band_palette():
    """측정 5단 밴드 팔레트 — 앱 전체가 쓰는 단일 소스.

    ⚠ 예전에는 이 위젯만 차트 라이브러리 기본색 4단
    (`#33CCFF · #55BF3B · #DDDF0D · #DF5353`)을 자체 하드코딩했다. 그래서
    같은 대시보드에 각도 게이지와 나란히 놓으면 **같은 "낮음→높음"이 서로
    다른 색 언어**로 보였고, 설정(custom_ui)에서 사용자가 밴드 색을 바꿔도
    이 위젯만 따라오지 않았다.

    `get_band_palette()` 는 `aot/config` 의 BAND_PALETTE 에 사용자
    오버레이를 얹어 **항상 5색**을 돌려준다.
    """
    try:
        from aot.aot_flask.utils.utils_theme import get_band_palette
        return get_band_palette()
    except Exception:
        # 앱 컨텍스트 밖(테스트·마이그레이션)에서는 오버레이 없이 기본값만.
        from aot.config import BAND_PALETTE
        return list(BAND_PALETTE)


def execute_at_creation(error, new_widget, dict_widget):
    color_list = _band_palette()
    custom_options_json = json.loads(new_widget.custom_options)
    custom_options_json['range_colors'] = []

    if custom_options_json['stops'] < 2:
        custom_options_json['stops'] = 2

    difference = int(custom_options_json['max'] - custom_options_json['min'])
    stop_size = int(difference / custom_options_json['stops'])
    stop = custom_options_json['min'] + stop_size
    custom_options_json['range_colors'].append('{stop},{color}'.format(stop=stop, color=color_list[0]))
    for i in range(custom_options_json['stops'] - 1):
        stop += stop_size
        if i + 1 < len(color_list):
            color = color_list[i + 1]
        else:
            # 팔레트보다 구간이 많으면 마지막 단(가장 높음)을 반복한다.
            color = color_list[-1]
        custom_options_json['range_colors'].append('{stop},{color}'.format(stop=stop, color=color))

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

    sorted_colors, error = custom_colors_gauge(request_form, error)
    sorted_colors = gauge_reformat_stops(
        custom_options_json_presave['stops'],
        custom_options_json_postsave['stops'],
        current_colors=sorted_colors)

    custom_options_json_postsave['range_colors'] = sorted_colors
    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave


def generate_page_variables(widget_unique_id, widget_options):
    # Retrieve custom colors for gauges
    colors_gauge_solid = []
    colors_gauge_solid_form = []
    try:
        if 'range_colors' in widget_options and widget_options['range_colors']:
            color_areas = widget_options['range_colors']
        else:  # Create empty list
            color_areas = []

        try:
            gauge_low = widget_options['min']
            gauge_high = widget_options['max']
            gauge_difference = gauge_high - gauge_low
            for each_range in color_areas:
                percent_of_range = float((float(each_range.split(',')[0]) - gauge_low) / gauge_difference)
                colors_gauge_solid.append({
                    'stop': '{:.2f}'.format(percent_of_range),
                    'hex': each_range.split(',')[1]})
                colors_gauge_solid_form.append({
                    'stop': each_range.split(',')[0],
                    'hex': each_range.split(',')[1]})
        except:
            # Prevent mathematical errors from preventing proper page render
            for each_range in color_areas:
                colors_gauge_solid.append({
                    'stop': '0',
                    'hex': each_range.split(',')[1]})
                colors_gauge_solid_form.append({
                    'stop': '0',
                    'hex': each_range.split(',')[1]})
    except IndexError:
        logger.exception(1)
        flash("Colors Index Error", "error")

    dict_return = {
        "colors_gauge_solid": colors_gauge_solid,
        "colors_gauge_solid_form": colors_gauge_solid_form,
    }
    return dict_return


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_gauge_solid',
    'widget_name': lazy_gettext('Gauge (Solid)'),
    'widget_library': 'ECharts',
    'no_class': True,

    'message': lazy_gettext('Displays a solid gauge. Be sure to set the Maximum option to the last Stop value for the gauge to display properly.'),

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': generate_page_variables,

    'widget_width': 4,
    'widget_height': 8,

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
            'phrase': lazy_gettext('Select a measurement to display')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 120,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
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
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Decimal Places'),
            'phrase': lazy_gettext('The number of digits to display after the decimal')
        },
        {
            'id': 'min',
            'type': 'float',
            'default_value': 0,
            'name': lazy_gettext('Minimum'),
            'phrase': lazy_gettext('The gauge minimum')
        },
        {
            'id': 'max',
            'type': 'float',
            'default_value': 100,
            'name': lazy_gettext('Maximum'),
            'phrase': lazy_gettext('The gauge maximum')
        },
        {
            'id': 'stops',
            'type': 'integer',
            # 밴드 팔레트가 5단이라 기본도 5단으로 맞춘다(각도 게이지와 동일).
            # 이미 만들어 둔 위젯의 저장값은 건드리지 않는다 — 이 기본값은
            # 새로 추가할 때만 쓰인다.
            'default_value': 5,
            'name': lazy_gettext('Stops'),
            'phrase': lazy_gettext('The number of color stops')
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
{% if "gauge_chart" not in dashboard_dict %}
  <script src="{{ asset('widget-gauge-chart') }}"></script>
  {% set _dummy = dashboard_dict.update({"gauge_chart": 1}) %}
{% endif %}
""",

    'widget_dashboard_title_bar': """""",

    'widget_dashboard_body': """<div class="not-draggable" id="container-gauge-{{each_widget.unique_id}}" style="position: absolute; left: 0; top: 0; bottom: 0; right: 0; overflow: hidden;"></div>""",

    # 각도 게이지와 **같은 모양**을 쓴다 — 구간 수가 사용자 설정이라
    # custom_options 로는 선언할 수 없고, 여기서 표준 옵션 행으로 그린다.
    # 예전에는 부트스트랩 form-row 였고 라벨 "Stop"/"Color" 가 번역 함수 없이
    # 영어로 박혀 있었다(22개 언어로 나가는 앱이다).
    'widget_dashboard_configure_options': """
<div class="aot-modal-section-title">{{_('Color Sections')}}</div>
<div class="aot-modal-container">
{% for n in range(widget_variables['colors_gauge_solid_form']|length) %}
  {% set index = '{0:0>2}'.format(n) %}
<div class="aot-modal-option-row">
  <label class="aot-modal-option-label" for="color_stop_number{{index}}">{{_('Section')}} {{ n + 1 }}</label>
  <div class="aot-modal-option-control">
    <input class="form-control aot-modern-input aot-gauge-stop-input"
           id="color_stop_number{{index}}" name="color_stop_number{{index}}" type="text"
           value="{{widget_variables['colors_gauge_solid_form'][n]['stop']}}"
           aria-label="{{_('Value')}}" title="{{_('Value')}}">
    <input type="color" id="color_hex_number{{index}}" name="color_hex_number{{index}}"
           value="{{widget_variables['colors_gauge_solid_form'][n]['hex']}}"
           aria-label="{{_('Color')}}" title="{{_('Color')}}">
  </div>
</div>
{% endfor %}
</div>
""",

    'widget_dashboard_js': """
  function getLastDataGaugeSolid(widget_id,
                       unique_id,
                       measure_type,
                       measurement_id,
                       max_measure_age_sec) {
    const url = '/last/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + max_measure_age_sec.toString();
    $.ajax(url, {
      success: function(data, responseText, jqXHR) {
        if (jqXHR.status === 204) {
          widget[widget_id].setValue(null);
        }
        else {
          const measurement = data[1];
          widget[widget_id].setValue(measurement);
        }
      },
      error: function(jqXHR, textStatus, errorThrown) {
        widget[widget_id].setValue(null);
      }
    });
  }

  // Repeat function for getLastDataGaugeSolid()
  function repeatLastDataGaugeSolid(widget_id,
                          dev_id,
                          measure_type,
                          measurement_id,
                          period_sec,
                          max_measure_age_sec) {
    window._gauge_intervals = window._gauge_intervals || {};
    if (window._gauge_intervals[widget_id]) { clearInterval(window._gauge_intervals[widget_id]); }
    window._gauge_intervals[widget_id] = setInterval(function () {
      getLastDataGaugeSolid(widget_id,
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

  // Idempotency guard for live-preview re-init (no page reload): dispose prior
  // chart + clear its polling interval before rebuilding.
  try {
    if (typeof widget !== 'undefined' && widget['{{each_widget.unique_id}}']) {
      widget['{{each_widget.unique_id}}'].dispose();
      delete widget['{{each_widget.unique_id}}'];
    }
  } catch (e) {}
  if (window._gauge_intervals && window._gauge_intervals['{{each_widget.unique_id}}']) {
    clearInterval(window._gauge_intervals['{{each_widget.unique_id}}']);
    delete window._gauge_intervals['{{each_widget.unique_id}}'];
  }
  widget['{{each_widget.unique_id}}'] = AoTGauge.solid(document.getElementById('container-gauge-{{each_widget.unique_id}}'), {
    min: {{widget_options['min']}},
    max: {{widget_options['max']}},
    stops: [
      {%- for n in range(widget_variables['colors_gauge_solid']|length) %}
      [{{widget_variables['colors_gauge_solid'][n]['stop']}}, '{{widget_variables['colors_gauge_solid'][n]['hex']}}'],
      {%- endfor %}
    ],
    decimals: {{ widget_options['decimal_places'] }},
    // 호 위 제목(옛 판 yAxis.title)
    unit: '
      {%- if dict_measure_units[measurement_id] in dict_units and
             dict_units[dict_measure_units[measurement_id]]['unit'] -%}
        {{dict_units[dict_measure_units[measurement_id]]['unit']}}
      {%- endif -%}',
    // 값 아래 줄(옛 판 dataLabels 의 measure_unit)
    valueUnit: '{{measure_unit}}',
    tooltipUnit: '
      {%- for each_input in input if each_input.unique_id == device_id -%}
        {{dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
      {%- endfor -%}
      {%- for each_function in function if each_function.unique_id == device_id -%}
        {{dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
      {%- endfor -%}
      {%- for each_pid in pid if each_pid.unique_id == device_id -%}
        {{dict_units[device_measurements_dict[measurement_id].unit]['unit']}}
      {%- endfor -%}',
    name: '
        {%- for each_input in input if each_input.unique_id == device_id and measurement_id in device_measurements_dict -%}
          {{each_input.name}} (
            {%- if not device_measurements_dict[measurement_id].single_channel -%}
              {{'CH' + (device_measurements_dict[measurement_id].channel|int)|string}}
            {%- endif -%}
            {%- if device_measurements_dict[measurement_id].measurement -%}
          {{', ' + dict_measurements[device_measurements_dict[measurement_id].measurement]['name']}}
            {%- endif -%}
        {%- endfor -%}
        
        {%- for each_function in function if each_function.unique_id == device_id and measurement_id in device_measurements_dict -%}
          {{each_function.name}} (
            {%- if not device_measurements_dict[measurement_id].single_channel -%}
              {{'CH' + (device_measurements_dict[measurement_id].channel|int)|string}}
            {%- endif -%}
            {%- if device_measurements_dict[measurement_id].measurement -%}
          {{', ' + dict_measurements[device_measurements_dict[measurement_id].measurement]['name']}}
            {%- endif -%}
        {%- endfor -%}

        {%- for each_pid in pid if each_pid.unique_id == device_id and measurement_id in device_measurements_dict -%}
          {{each_pid.name}} (
            {%- if not device_measurements_dict[measurement_id].single_channel -%}
              {{'CH' + (device_measurements_dict[measurement_id].channel|int)|string}}
            {%- endif -%}
            {%- if device_measurements_dict[measurement_id].measurement -%}
          {{', ' + dict_measurements[device_measurements_dict[measurement_id].measurement]['name']}}
            {%- endif -%}
        {%- endfor -%})'
  });

  {% for each_input in input if each_input.unique_id == device_id %}
  getLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'input', '{{measurement_id}}', {{widget_options['max_measure_age']}});
  repeatLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'input', '{{measurement_id}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
  {%- endfor -%}
  
  {% for each_function in function if each_function.unique_id == device_id %}
  getLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'function', '{{measurement_id}}', {{widget_options['max_measure_age']}});
  repeatLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'function', '{{measurement_id}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
  {%- endfor -%}

  {%- for each_pid in pid  if each_pid.unique_id == device_id %}
  getLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'pid', '{{measurement_id}}', {{widget_options['max_measure_age']}});
  repeatLastDataGaugeSolid('{{each_widget.unique_id}}', '{{device_id}}', 'pid', '{{measurement_id}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
  {%- endfor -%}
"""
}


def is_rgb_color(color_hex):
    """
    Check if string is a hex color value for the web UI
    :param color_hex: string to check if it represents a hex color value
    :return: bool
    """
    return bool(re.compile(r'#[a-fA-F0-9]{6}$').match(color_hex))


def custom_colors_gauge(form, error):
    """Get variable number of gauge color inputs, turn into CSV string."""
    sorted_colors = []
    colors_hex = {}
    # Combine all color form inputs to dictionary
    for key in form.keys():
        if 'color_hex_number' in key or 'color_stop_number' in key:
            if 'color_hex_number' in key and int(key[16:]) not in colors_hex:
                colors_hex[int(key[16:])] = {}
            if 'color_stop_number' in key and int(key[17:]) not in colors_hex:
                colors_hex[int(key[17:])] = {}
        if 'color_hex_number' in key:
            for value in form.getlist(key):
                if not is_rgb_color(value):
                    error.append("Invalid hex color value")
                colors_hex[int(key[16:])]['hex'] = value
        elif 'color_stop_number' in key:
            for value in form.getlist(key):
                if not is_rgb_color(value):
                    error.append("Invalid hex color value")
                colors_hex[int(key[17:])]['stop'] = value

    # Build string of colors and associated gauge values
    for i, _ in enumerate(colors_hex):
        try:
            try:
                sorted_colors.append("{},{}".format(colors_hex[i]['stop'], colors_hex[i]['hex']))
            except Exception as err_msg:
                error.append(err_msg)
                sorted_colors.append("0,{}".format(colors_hex[i]['hex']))
        except Exception as err_msg:
            error.append(err_msg)
    return sorted_colors, error


def gauge_reformat_stops(current_stops, new_stops, current_colors=None):
    """Generate stops and colors for new and modified gauges."""
    palette = _band_palette()

    if current_colors:
        # 사용자가 이미 고른 색이 있으면 **그대로 둔다** — 팔레트로 덮지 않는다.
        colors = current_colors
    else:  # 새로 추가하는 게이지에만 팔레트 기본값을 쓴다.
        colors = ['{},{}'.format((i + 1) * 20, c) for i, c in enumerate(palette)]

    if new_stops > current_stops:
        try:
            stop = float(colors[-1].split(",")[0])
        except:
            stop = 80
        for _ in range(new_stops - current_stops):
            stop += 20
            colors.append('{},{}'.format(stop, palette[-1]))
    elif new_stops < current_stops:
        colors = colors[: len(colors) - (current_stops - new_stops)]

    return colors
