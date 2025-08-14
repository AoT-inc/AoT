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

import json
import logging
import re

from flask import flash
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

def execute_at_creation(error, new_widget, dict_widget):
    """ 위젯 생성 시, 풍향/풍속 전용으로 min/max/색상 등을 설정 """
    custom_options_json = json.loads(new_widget.custom_options)

    # 풍향 범위 고정
    custom_options_json['min'] = 0
    custom_options_json['max'] = 360

    # range_colors는 선택 사항 (없으면 빈 배열)
    if 'range_colors' not in custom_options_json:
        custom_options_json['range_colors'] = []

    # 불필요한 키 제거
    if 'stops' in custom_options_json:
        del custom_options_json['stops']
    if 'preset_config' in custom_options_json:
        del custom_options_json['preset_config']

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

    # 사용자 색상 구간 파싱 (구간 끝은 자동 계산)
    sorted_colors, error = custom_colors_gauge(request_form, error)
    sorted_colors = fill_missing_highs(custom_options_json_postsave, sorted_colors)

    # 불필요 키 제거
    if 'stops' in custom_options_json_postsave:
        del custom_options_json_postsave['stops']
    if 'preset_config' in custom_options_json_postsave:
        del custom_options_json_postsave['preset_config']

    custom_options_json_postsave['range_colors'] = sorted_colors

    # 풍향 범위 고정
    custom_options_json_postsave['min'] = 0
    custom_options_json_postsave['max'] = 360

    return allow_saving, page_refresh, mod_widget, custom_options_json_postsave

def generate_page_variables(widget_unique_id, widget_options):
    # Retrieve custom colors for gauges
    colors_gauge_angular = []
    try:
        if 'range_colors' in widget_options and widget_options['range_colors']:
            color_areas = widget_options['range_colors']
        else:
            color_areas = []

        for each_range in color_areas:
            colors_gauge_angular.append({
                'low': each_range.split(',')[0],
                'high': each_range.split(',')[1],
                'hex': each_range.split(',')[2]})
    except IndexError:
        logger.exception(1)
        # flash("Colors Index Error", "error")

    return {"colors_gauge_angular": colors_gauge_angular}


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_wind_angular',
    'widget_name': 'AoT 풍향/풍속 게이지',
    'widget_library': 'Native SVG',
    'no_class': True,

    # 위젯 설명 (한글화)
    'message': '풍향은 원형 링(0~360°)으로 표시하고, 중앙에는 풍속을 표시합니다. 주요 8개 방위(0/45/90/135/180/225/270/315°) 보조선을 제공합니다.',

    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': generate_page_variables,

    'dependencies_module': [],

    'widget_width': 5,
    'widget_height': 10,

    'custom_options': [
        {
            'id': 'measurement_direction',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('풍향 측정값'),
            'phrase': lazy_gettext('풍향(0~360°) 측정값을 선택하세요')
        },
        {
            'id': 'measurement_speed',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('풍속 측정값'),
            'phrase': lazy_gettext('풍속 측정값을 선택하세요')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 1800,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('최대 유효 시간'), lazy_gettext('초')),
            'phrase': lazy_gettext('해당 측정값의 최대 유효 시간을 설정하세요')
        },
        {
            'id': 'refresh_seconds',
            'type': 'float',
            'default_value': 30.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': '{} ({})'.format(lazy_gettext("새로고침"), lazy_gettext("초")),
            'phrase': '위젯을 새로고침할 주기를 설정하세요'
        },
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': '소수점 자릿수',
            'phrase': '소수점 이하 표시 자릿수를 설정하세요'
        },
        {
            'id': 'min',
            'type': 'float',
            'default_value': 0,
            'name': '최소값',
            'phrase': '게이지의 최소값을 설정하세요'
        },
        {
            'id': 'max',
            'type': 'float',
            'default_value': 360,
            'name': '최대값',
            'phrase': '게이지의 최대값을 설정하세요'
        },
        {
            # ★ 데이터 폰트 크기
            'id': 'text_font_size',
            'type': 'float',
            'default_value': 1.5,
            'name': '데이터 문자 크기',
            'phrase': '게이지 내부 데이터의 문자 크기를 설정하세요. 기본값 1.5는 중간 크기입니다.'
        },
        {
            # ★ 단위 폰트 크기
            'id': 'unit_font_size',
            'type': 'float',
            'default_value': 0.7,
            'name': '단위 문자 크기',
            'phrase': '게이지 내부 단위의 문자 크기를 설정하세요. 기본값 0.7은 작은 크기입니다.'
        },
        {
            # ★ 단위 폰트 크기
            'id': 'unit_font_tick',
            'type': 'float',
            'default_value': 500,
            'name': '단위 문자 굵기',
            'phrase': '게이지 내부 문자 굵기를 설정하세요. 기본값 500은 중간 굵기입니다.'
        },
        {
            'id': 'text_y_offset',
            'type': 'float',
            'default_value': 30,
            'name': '데이터 위치 오프셋',
            'phrase': '게이지 내부 데이터 텍스트의 수직 위치 오프셋을 설정하세요 (숫자만 입력, 단위는 자동 처리)'
        }
    ],

    'widget_dashboard_head': """<!-- No external JS dependencies. Using native SVG. -->""",

    'widget_dashboard_title_bar': """<span style="padding-right: 0.5em; font-size: {{each_widget.font_em_name}}em">{{each_widget.name}}</span>""",

    # 위젯 실제 표시 영역
    'widget_dashboard_body': """<div class="not-draggable" id="container-gauge-{{each_widget.unique_id}}" style="position: absolute; left: 0; top: 0; bottom: 0; right: 0; overflow: hidden; z-index: 1; min-height: 120px;"></div>""",

    # 설정 화면에서 색상 구간 수정하는 부분
    # "구간 끝" 필드 완전히 제거. 구간 시작, 색상만 표시
    'widget_dashboard_configure_options': """
        {% for n in range(widget_variables['colors_gauge_angular']|length) %}
          {% set index = '{0:0>2}'.format(n) %}
        <div class="form-row">
          <div class="col-auto">
            <label class="control-label" for="color_low_number{{index}}">[{{n}}] 구간 시작</label>
            <div>
              <input class="form-control" id="color_low_number{{index}}" name="color_low_number{{index}}" type="text" value="{{widget_variables['colors_gauge_angular'][n]['low']}}">
            </div>
          </div>
          <div class="col-auto">
            <label class="control-label" for="color_hex_number{{index}}">[{{n}}] 색상</label>
            <div>
              <input id="color_hex_number{{index}}" name="color_hex_number{{index}}" placeholder="#000000" type="color" value="{{widget_variables['colors_gauge_angular'][n]['hex']}}">
            </div>
          </div>
        </div>
        {% endfor %}
    """,

    'widget_dashboard_js': """
  // --- SVG Gauge helpers (no external libs) ---
  function aotEnsureGauge(widget_id) {
    if (!window.widget) window.widget = {};
    if (!window.widget[widget_id]) window.widget[widget_id] = {};
    var el = document.getElementById('container-gauge-' + widget_id);
    if (!el) return;

    // Avoid duplicate build
    if (document.getElementById('svg-' + widget_id)) return;

    // Compute size
    var w = el.clientWidth || 300;
    var h = el.clientHeight || 240;
    var size = Math.min(w, h);
    var cx = size / 2, cy = size / 2;
    var rOuter = size * 0.45;
    var rTicks = rOuter;
    var rNeedle = rOuter * 0.9;

    // Build SVG
    var svgNS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('id', 'svg-' + widget_id);
    svg.setAttribute('width', '100%');
    svg.setAttribute('height', '100%');
    svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    // Background circle
    var bg = document.createElementNS(svgNS, 'circle');
    bg.setAttribute('cx', cx);
    bg.setAttribute('cy', cy);
    bg.setAttribute('r', rOuter);
    bg.setAttribute('fill', 'none');
    bg.setAttribute('stroke', '#e0e0e0');
    bg.setAttribute('stroke-width', 2);
    svg.appendChild(bg);

    // 8-direction tick lines (every 45°)
    var directions = [0,45,90,135,180,225,270,315];
    directions.forEach(function(deg){
      var rad = (deg - 90) * Math.PI / 180.0; // start at North
      var x1 = cx + Math.cos(rad) * (rTicks - 8);
      var y1 = cy + Math.sin(rad) * (rTicks - 8);
      var x2 = cx + Math.cos(rad) * (rTicks);
      var y2 = cy + Math.sin(rad) * (rTicks);
      var line = document.createElementNS(svgNS, 'line');
      line.setAttribute('x1', x1);
      line.setAttribute('y1', y1);
      line.setAttribute('x2', x2);
      line.setAttribute('y2', y2);
      line.setAttribute('stroke', '#cccccc');
      line.setAttribute('stroke-width', 2);
      svg.appendChild(line);
    });

    // Cardinal labels N/E/S/W
    var labels = [{d:0,t:'N'},{d:90,t:'E'},{d:180,t:'S'},{d:270,t:'W'}];
    labels.forEach(function(o){
      var rad = (o.d - 90) * Math.PI / 180.0;
      var rx = cx + Math.cos(rad) * (rOuter - 18);
      var ry = cy + Math.sin(rad) * (rOuter - 18) + 4;
      var text = document.createElementNS(svgNS, 'text');
      text.setAttribute('x', rx);
      text.setAttribute('y', ry);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', Math.max(10, size * 0.06));
      text.setAttribute('fill', '#666666');
      text.textContent = o.t;
      svg.appendChild(text);
    });

    // Needle group
    var needleGroup = document.createElementNS(svgNS, 'g');
    needleGroup.setAttribute('id', 'needle-' + widget_id);
    needleGroup.setAttribute('transform', 'rotate(0 ' + cx + ' ' + cy + ')');

    var needle = document.createElementNS(svgNS, 'line');
    needle.setAttribute('x1', cx);
    needle.setAttribute('y1', cy);
    needle.setAttribute('x2', cx);
    needle.setAttribute('y2', cy - rNeedle);
    needle.setAttribute('stroke', '#3e3f46');
    needle.setAttribute('stroke-width', 4);
    needle.setAttribute('stroke-linecap', 'round');
    needleGroup.appendChild(needle);

    // Needle center cap
    var cap = document.createElementNS(svgNS, 'circle');
    cap.setAttribute('cx', cx);
    cap.setAttribute('cy', cy);
    cap.setAttribute('r', 6);
    cap.setAttribute('fill', '#3e3f46');
    needleGroup.appendChild(cap);

    svg.appendChild(needleGroup);

    // Speed text (center)
    var speedText = document.createElementNS(svgNS, 'text');
    speedText.setAttribute('id', 'speed-' + widget_id);
    speedText.setAttribute('x', cx);
    speedText.setAttribute('y', cy + (size * 0.12));
    speedText.setAttribute('text-anchor', 'middle');
    speedText.setAttribute('font-size', Math.max(12, size * 0.12));
    speedText.setAttribute('fill', '#3e3f46');
    speedText.textContent = '';
    svg.appendChild(speedText);

    el.appendChild(svg);

    // store geometry for updates
    window.widget[widget_id].__cx = cx;
    window.widget[widget_id].__cy = cy;
  }

  function aotUpdateNeedle(widget_id, deg) {
    var g = document.getElementById('needle-' + widget_id);
    if (!g) return;
    var cx = window.widget[widget_id].__cx || 0;
    var cy = window.widget[widget_id].__cy || 0;
    // SVG 0° is to the right; we want 0° at North -> rotate(deg)
    g.setAttribute('transform', 'rotate(' + deg + ' ' + cx + ' ' + cy + ')');
  }

  function aotUpdateSpeed(widget_id, val, unit, decimals, dataFontSizeEm, unitFontSizeEm) {
    var t = document.getElementById('speed-' + widget_id);
    if (!t) return;
    var v = (val === null || val === undefined) ? '' : Number(val).toFixed(decimals || 1);
    var dataSpan = '<tspan style="font-size:' + (dataFontSizeEm || 1.5) + 'em;">' + v + '</tspan>';
    var unitSpan = unit ? '<tspan style="font-size:' + (unitFontSizeEm || 0.7) + 'em;"> ' + unit + '</tspan>' : '';
    t.innerHTML = dataSpan + unitSpan;
  }

  // --- Data fetchers (unchanged endpoints) ---
  function getLastDataGaugeAngular(widget_id,
                       unique_id,
                       measure_type,
                       measurement_id,
                       max_measure_age_sec) {
    const url = '/last/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + max_measure_age_sec.toString();
    $.ajax(url, {
      success: function(data, responseText, jqXHR) {
        if (jqXHR.status === 204) {
          if (!window.widget) window.widget = {};
          if (!window.widget[widget_id]) window.widget[widget_id] = {};
          window.widget[widget_id].lastDir = null;
          aotUpdateNeedle(widget_id, 0);
        }
        else {
          const measurement = data[1];
          if (!window.widget) window.widget = {};
          if (!window.widget[widget_id]) window.widget[widget_id] = {};
          window.widget[widget_id].lastDir = measurement;
          aotUpdateNeedle(widget_id, measurement);
        }
      },
      error: function() {
        if (!window.widget) window.widget = {};
        if (!window.widget[widget_id]) window.widget[widget_id] = {};
        window.widget[widget_id].lastDir = null;
        aotUpdateNeedle(widget_id, 0);
      }
    });
  }

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

  function getLastDataWindSpeed(widget_id,
                                unique_id,
                                measure_type,
                                measurement_id,
                                max_measure_age_sec,
                                decimals,
                                dataFontEm,
                                unitFontEm,
                                unitLabel) {
    const url = '/last/' + unique_id + '/' + measure_type + '/' + measurement_id + '/' + max_measure_age_sec.toString();
    $.ajax(url, {
      success: function(data, responseText, jqXHR) {
        if (!window.widget) window.widget = {};
        if (!window.widget[widget_id]) window.widget[widget_id] = {};
        if (jqXHR.status === 204) {
          window.widget[widget_id].lastSpeed = null;
        } else {
          window.widget[widget_id].lastSpeed = data[1];
        }
        aotUpdateSpeed(widget_id, window.widget[widget_id].lastSpeed, unitLabel, decimals, dataFontEm, unitFontEm);
      },
      error: function() {
        if (!window.widget) window.widget = {};
        if (!window.widget[widget_id]) window.widget[widget_id] = {};
        window.widget[widget_id].lastSpeed = null;
        aotUpdateSpeed(widget_id, window.widget[widget_id].lastSpeed, unitLabel, decimals, dataFontEm, unitFontEm);
      }
    });
  }

  function repeatLastDataWindSpeed(widget_id,
                                   dev_id,
                                   measure_type,
                                   measurement_id,
                                   period_sec,
                                   max_measure_age_sec,
                                   decimals,
                                   dataFontEm,
                                   unitFontEm,
                                   unitLabel) {
    setInterval(function () {
      getLastDataWindSpeed(widget_id,
                           dev_id,
                           measure_type,
                           measurement_id,
                           max_measure_age_sec,
                           decimals,
                           dataFontEm,
                           unitFontEm,
                           unitLabel)
    }, period_sec * 1000);
  }
  """,

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
  {%- set meas_dir = widget_options.get('measurement_direction', '') -%}
  {%- set parts_dir = meas_dir.split(",") if meas_dir else [] -%}
  {%- set device_id_dir = parts_dir[0] if parts_dir|length > 1 else '' -%}
  {%- set measurement_id_dir = parts_dir[1] if parts_dir|length > 1 else '' -%}

  {%- set meas_spd = widget_options.get('measurement_speed', '') -%}
  {%- set parts_spd = meas_spd.split(",") if meas_spd else [] -%}
  {%- set device_id_spd = parts_spd[0] if parts_spd|length > 1 else '' -%}
  {%- set measurement_id_spd = parts_spd[1] if parts_spd|length > 1 else '' -%}

  (function(){
    try {
      // --- Ensure SVG helpers are loaded ---
      if (typeof window.aotEnsureGauge === 'undefined') {
        var s = document.createElement('script');
        s.src = '/static/js/aot_gauge_svg.js';
        document.head.appendChild(s);
      }
      // Continue only after helpers are loaded
      function aotInitWidget() {
        if (typeof window.aotEnsureGauge === 'undefined') {
          setTimeout(aotInitWidget, 50);
          return;
        }
        if (typeof window.widget === 'undefined') {
          window.widget = {};
        }
        var el = document.getElementById('container-gauge-{{each_widget.unique_id}}');
        if (el) {
          if (!el.offsetHeight || !el.offsetWidth) {
            el.style.minHeight = '120px';
          }
          if (!el.style.zIndex) {
            el.style.zIndex = '1';
          }
          if (el.parentElement && getComputedStyle(el.parentElement).position === 'static') {
            el.parentElement.style.position = 'relative';
          }
        }
        // Build SVG once
        aotEnsureGauge('{{each_widget.unique_id}}');

        // Initialize storage
        window.widget['{{each_widget.unique_id}}'].lastDir = null;
        window.widget['{{each_widget.unique_id}}'].lastSpeed = null;

        // Direction fetchers (guarded)
        {% if device_id_dir and measurement_id_dir %}
        {% for each_input in input  if each_input.unique_id == device_id_dir %}
        getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'input', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
        repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'input', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
        {%- endfor -%}
        {% for each_function in function if each_function.unique_id == device_id_dir %}
        getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'function', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
        repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'function', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
        {%- endfor -%}
        {% for each_pid in pid if each_pid.unique_id == device_id_dir %}
        getLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'pid', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
        repeatLastDataGaugeAngular('{{each_widget.unique_id}}', '{{device_id_dir}}', 'pid', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
        {%- endfor -%}
        {% endif %}

        // Determine unit label for speed (server dictionaries if available)
        var unitLabel = (function(){
          {% if measurement_id_spd %}
            {% if measurement_id_spd in dict_measure_units and dict_measure_units[measurement_id_spd] in dict_units and dict_units[dict_measure_units[measurement_id_spd]]['unit'] %}
              return '{{ dict_units[dict_measure_units[measurement_id_spd]]["unit"] }}';
            {% elif measurement_id_spd in device_measurements_dict %}
              return '{{ dict_units[device_measurements_dict[measurement_id_spd].unit]["unit"] }}';
            {% else %}
              return '';
            {% endif %}
          {% else %}
            return '';
          {% endif %}
        })();

        // Speed fetchers (guarded)
        {% if device_id_spd and measurement_id_spd %}
        {% for each_input in input  if each_input.unique_id == device_id_spd %}
        getLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'input', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        repeatLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'input', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        {%- endfor -%}
        {% for each_function in function if each_function.unique_id == device_id_spd %}
        getLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'function', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        repeatLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'function', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        {%- endfor -%}
        {% for each_pid in pid if each_pid.unique_id == device_id_spd %}
        getLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'pid', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        repeatLastDataWindSpeed('{{each_widget.unique_id}}', '{{device_id_spd}}', 'pid', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
        {%- endfor -%}
        {% endif %}
      }
      aotInitWidget();
    } catch (e) {
      console && console.error && console.error('AoT_wind_angular init error:', e);
    }
  })();
  """}


def is_rgb_color(color_hex):
    """
    Check if string is a valid 6-digit hex color (e.g. #FF0000)
    """
    return bool(re.compile(r'#[a-fA-F0-9]{6}$').match(color_hex))


############################
# “구간 끝” 제거 버전
############################
def custom_colors_gauge(form, error):
    """
    "구간 시작"(low), "색상"(hex)만 파싱한다. "구간 끝"(high)은 비워둔 채로 sorted_colors에 저장.
    """
    sorted_colors = []
    colors_hex = {}

    for key in form.keys():
        # "color_low_number##" / "color_hex_number##" 만 존재
        if 'color_low_number' in key or 'color_hex_number' in key:
            idx = int(key[16:])  # 예: color_low_number00 → 인덱스 00 → int(0)
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

    # 인덱스 순서대로 "low,,hex" 형태로 임시 저장
    for i in sorted(colors_hex.keys()):
        try:
            low_val = colors_hex[i].get('low', '0')
            hex_val = colors_hex[i].get('hex', '#000000')
            # middle(High)은 비워둠
            sorted_colors.append(f"{low_val},,{hex_val}")
        except Exception as err_msg:
            logger.exception(1)
            error.append(str(err_msg))

    return sorted_colors, error



def fill_missing_highs(custom_options_json, sorted_colors):
    """
    구간 전체에 대해,
    middle(High)이 비어 있는 경우 자동 계산:
    - 다음 구간의 Low → 현재 구간 High
    - 마지막 구간은 widget 'max' 값이 High
    """
    max_val = custom_options_json['max']

    for i in range(len(sorted_colors) - 1):
        low_i, high_i, color_i = sorted_colors[i].split(',')
        low_next, high_next, color_next = sorted_colors[i+1].split(',')

        # 현재 구간 High가 비어 있으면 다음 구간 Low를 대입
        if not high_i.strip():
            high_i = low_next
            sorted_colors[i] = f"{low_i},{high_i},{color_i}"

    # 마지막 구간 처리
    last_idx = len(sorted_colors) - 1
    low_last, high_last, color_last = sorted_colors[last_idx].split(',')
    if not high_last.strip():
        high_last = str(max_val)  # 마지막 구간 끝은 max
        sorted_colors[last_idx] = f"{low_last},{high_last},{color_last}"

    return sorted_colors