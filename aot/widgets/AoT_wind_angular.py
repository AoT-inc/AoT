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
import logging
import re

from flask import flash
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

def execute_at_creation(error, new_widget, dict_widget):
    """ On widget creation, set min/max/colors etc. specifically for wind direction/speed """
    custom_options_json = json.loads(new_widget.custom_options)

    # Fix the wind-direction range
    custom_options_json['min'] = 0
    custom_options_json['max'] = 360

    # range_colors is optional (empty array if absent)
    if 'range_colors' not in custom_options_json:
        custom_options_json['range_colors'] = []

    # Remove unneeded keys
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

    # Remove unneeded keys
    if 'stops' in custom_options_json_postsave:
        del custom_options_json_postsave['stops']
    if 'preset_config' in custom_options_json_postsave:
        del custom_options_json_postsave['preset_config']

    # Fix the wind-direction range
    custom_options_json_postsave['min'] = 0
    custom_options_json_postsave['max'] = 360

    # --- Persist color/size options explicitly (avoid framework merge issues) ---
    def _norm_hex(val, default_val):
        if val is None:
            return default_val
        s = str(val).strip()
        if not s:
            return default_val
        # add leading '#'
        if re.fullmatch(r'[0-9a-fA-F]{6}', s):
            s = '#' + s
        if is_rgb_color(s):
            return s
        return default_val

    try:
        if 'border_color' in request_form:
            custom_options_json_postsave['border_color'] = _norm_hex(request_form.get('border_color'), custom_options_json_postsave.get('border_color', '#D5D5D5'))
        if 'direction_color' in request_form:
            custom_options_json_postsave['direction_color'] = _norm_hex(request_form.get('direction_color'), custom_options_json_postsave.get('direction_color', '#F4D624'))
    except Exception:
        logger.exception('Color option parse failed')

    # numeric options that may come as strings
    def _to_float(val, default_val):
        try:
            if val is None:
                return default_val
            f = float(val)
            return f
        except Exception:
            return default_val

    if 'direction_dot_px' in request_form:
        custom_options_json_postsave['direction_dot_px'] = _to_float(request_form.get('direction_dot_px'), custom_options_json_postsave.get('direction_dot_px', 10))
    if 'text_y_offset' in request_form:
        custom_options_json_postsave['text_y_offset'] = _to_float(request_form.get('text_y_offset'), custom_options_json_postsave.get('text_y_offset', 5))
    if 'direction_label_font_em' in request_form:
        custom_options_json_postsave['direction_label_font_em'] = _to_float(request_form.get('direction_label_font_em'), custom_options_json_postsave.get('direction_label_font_em', 1.5))

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
    'widget_name': lazy_gettext('AoT Wind Direction/Speed Gauge'),
    'widget_library': 'Native SVG',
    'no_class': True,

    'message': lazy_gettext('Displays wind direction on a circular ring (0-360°) and wind speed in the center. Includes auxiliary lines for the 8 primary compass points.'),

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
            'name': lazy_gettext('Wind Direction Measurement'),
            'phrase': lazy_gettext('Select the wind direction (0-360°) measurement.')
        },
        {
            'id': 'measurement_speed',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('Wind Speed Measurement'),
            'phrase': lazy_gettext('Select the wind speed measurement.')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 1800,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("{} ({})").format(lazy_gettext('Maximum Validity Time'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Set the maximum validity for the measurement.')
        },
        {
            'id': 'refresh_seconds',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 30.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('{} ({})').format(lazy_gettext("Refresh"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('Set the refresh interval for the widget.')
        },
        {
            'id': 'decimal_places',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Decimal Places'),
            'phrase': lazy_gettext('Set the number of decimal places to display.')
        },
        {
            'type': 'header',
            'name': lazy_gettext('Range')
        },

        {
            'id': 'min',
            'type': 'float',
            'default_value': 0,
            'name': lazy_gettext('Minimum Value'),
            'phrase': lazy_gettext('Set the minimum value for the gauge.')
        },
        {
            'id': 'max',
            'type': 'float',
            'default_value': 360,
            'name': lazy_gettext('Maximum Value'),
            'phrase': lazy_gettext('Set the maximum value for the gauge.')
        },
        {
            'type': 'collapse_start',
            'id': 'appearance',
            'name': lazy_gettext('Appearance')
        },

        {
            'id': 'text_font_size',
            'type': 'float',
            'default_value': 1.5,
            'name': lazy_gettext('Data Font Size'),
            'phrase': lazy_gettext('Set the font size for the data inside the gauge. (Default: 1.5)')
        },
        {
            'id': 'unit_font_size',
            'type': 'float',
            'default_value': 0.7,
            'name': lazy_gettext('Unit Font Size'),
            'phrase': lazy_gettext('Set the font size for the unit inside the gauge. (Default: 0.7)')
        },
        {
            'id': 'border_color',
            'type': 'hidden',
            'default_value': '#D5D5D5',
            'name': lazy_gettext('Border Color'),
            'phrase': lazy_gettext('Selected from the palette. (Default: #D5D5D5)')
        },
        {
            'id': 'direction_color',
            'type': 'hidden',
            'default_value': '#F4D624',
            'name': lazy_gettext('Wind Direction Indicator Color'),
            'phrase': lazy_gettext('Selected from the palette. (Default: #F4D624)')
        },
        {
            'id': 'direction_dot_px',
            'type': 'float',
            'default_value': 10,
            'name': lazy_gettext('Direction Dot Size (px)'),
            'phrase': lazy_gettext('Set the radius (px) of the wind direction indicator dot. (Default: 10)')
        },
        {
            'id': 'direction_label_font_em',
            'type': 'float',
            'default_value': 1.5,
            'name': lazy_gettext('Compass Font Size (em)'),
            'phrase': lazy_gettext('Set the font size for the compass labels (N/E/S/W etc.) in em scale. (Default: 1.0)')
        },
        {
            'id': 'text_y_offset',
            'type': 'float',
            'default_value': 5,
            'name': lazy_gettext('Data Position Offset'),
            'phrase': lazy_gettext('Set the vertical position offset (%) for the data text inside the gauge. (Default: 5)')
        },
        {
            'type': 'collapse_end'
        }
    ],

    'widget_dashboard_head': """<!-- No external JS dependencies. Using native SVG. -->""",

    'widget_dashboard_title_bar': """""",

    # Actual widget display area
    'widget_dashboard_body': """<style>
  /* SVG 글자색은 `fill` 이라 텍스트 색 토큰이 자동으로 따라오지 않는다.
     예전에는 `#111`·`#333`·`#9aa0a6` 을 JS 가 직접 박아 넣어서, **다크 테마에서
     어두운 카드 위 검은 글자**가 됐다. CSS 의 `fill` 은 표현속성보다 세므로
     여기서 토큰으로 한 번만 정한다. */
  .aot-windw-value { fill: var(--aot-text-main, var(--aot-color-text-primary)); }
  .aot-windw-sub   { fill: var(--aot-color-text-secondary); }
  .aot-windw-rose  { fill: var(--aot-color-text-secondary); opacity: 0.7; }
</style>
<div class="not-draggable" id="container-gauge-{{each_widget.unique_id}}" style="position: absolute; left: 0; top: 0; bottom: 0; right: 0; overflow: hidden; z-index: 1; min-height: 120px;"></div>""",

    # Section for editing color ranges on the settings screen
    # The "range end" field is completely removed. Only range start and color are shown
    # 설정 화면의 색 지정 — 표준 옵션 행(.aot-modal-option-row)을 쓴다.
    #
    # ⚠ 예전에는 이 자리에 부트스트랩 `form-row`/`col-auto` 와 자체 `<style>` 로
    #   만든 칩이 있었고, 그 아래에 `direction_dot_px`·`text_y_offset` 을 **한 번 더**
    #   그렸다 — 두 필드가 같은 이름으로 모달에 두 번 나와(실측 확인) 어느 쪽을
    #   고쳐도 먼저 나온 값만 저장됐다. 아래 두 색만 여기서 그리고,
    #   나머지 옵션은 전부 표준 렌더러(custom_options)에 맡긴다.
    'widget_dashboard_configure_options': """
<div class="aot-modal-section-title">{{_('Colors')}}</div>
<div class="aot-modal-container">
{%- set _uid = each_widget.unique_id %}
<div class="aot-modal-option-row aot-modal-option-row-wrap">
  <label class="aot-modal-option-label" for="{{_uid}}_border_color">{{_('Border Color')}}</label>
  <div class="aot-modal-option-control">
    {%- set color_id = _uid ~ '_border_color' -%}
    {%- set color_name = 'border_color' -%}
    {%- set color_value = widget_options.get('border_color', '#D5D5D5') -%}
    {%- set color_presets = ['#F4D624', '#3E3F46', '#8BC1C1', '#2AA876', '#1F78B4', '#FEA60B'] -%}
    {% include 'pages/form_options/Color_Presets.html' %}
  </div>
</div>
<div class="aot-modal-option-row aot-modal-option-row-wrap">
  <label class="aot-modal-option-label" for="{{_uid}}_direction_color">{{_('Wind Direction Indicator Color')}}</label>
  <div class="aot-modal-option-control">
    {%- set color_id = _uid ~ '_direction_color' -%}
    {%- set color_name = 'direction_color' -%}
    {%- set color_value = widget_options.get('direction_color', '#F4D624') -%}
    {%- set color_presets = ['#DF5353', '#1F78B4', '#2AA876', '#7B5EA7', '#000000', '#FF7F0E'] -%}
    {% include 'pages/form_options/Color_Presets.html' %}
  </div>
</div>
</div>
    """,

    'widget_dashboard_js': """
  // --- SVG Gauge helpers (no external libs) ---
  function aotWindEnsureGauge(widget_id) {
    if (!window.widget) window.widget = {};
    if (!window.widget[widget_id]) window.widget[widget_id] = {};
    var el = document.getElementById('container-gauge-' + widget_id);
    if (!el) return;

    // Rebuild every call to apply latest geometry/needle (remove legacy long-needle SVG if present)
    var existing = document.getElementById('svg-' + widget_id);
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }

    // Compute size
    var w = el.clientWidth || 300;
    var h = el.clientHeight || 240;
    var size = Math.min(w, h);
    // outer padding like general gauge mock (~10%)
    var pad = size * 0.1;
    var cx = size * 0.50, cy = size * 0.45; // align center with AoT_gauge_angular, keep current radius
    var rOuter = (size / 2) - pad;
    var rTicks = rOuter;

    // helper: sanitize color strings coming from options/inputs
    function sanitizeColor(c, fallback){
      if (c === undefined || c === null) return fallback;
      var s = String(c).trim();
      if (!s || s.toLowerCase() === 'undefined' || s.toLowerCase() === 'null') return fallback;
      if (/^#[0-9a-fA-F]{6}$/.test(s)) return s;
      if (/^[0-9a-fA-F]{6}$/.test(s)) return '#' + s; // accept hex without '#'
      return fallback;
    }

    // Colors and text offset from runtime options (set in ready_end)
    var _opts = (window.widget[widget_id] && window.widget[widget_id].opts) ? window.widget[widget_id].opts : {};
    var borderColor = sanitizeColor(_opts.border_color, '#D5D5D5');
    var dirColor = sanitizeColor(_opts.direction_color, '#F4D624');
    var dotR = parseFloat(_opts.direction_dot_px);
    if (!isFinite(dotR) || dotR <= 0) dotR = 10;
    var textOffsetPct = parseFloat(_opts.text_y_offset); if (!isFinite(textOffsetPct)) textOffsetPct = 5;
    var dirFontEm = parseFloat(_opts.direction_label_font_em); if (!isFinite(dirFontEm)) dirFontEm = 1.5;

    // Fixed border thickness (~4% of size)
    var borderStroke = Math.max(3, size * 0.04);

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
    bg.setAttribute('stroke', borderColor);
    bg.setAttribute('stroke-width', borderStroke);
    svg.appendChild(bg);

    // Ticks removed per spec; only labels remain.

    // Cardinal labels N/E/S/W
    var labels = [{d:0,t:'N'},{d:90,t:'E'},{d:180,t:'S'},{d:270,t:'W'}];
    labels.forEach(function(o){
      var rad = (o.d - 90) * Math.PI / 180.0;
      var rx = cx + Math.cos(rad) * (rOuter - 9);
      var ry = cy + Math.sin(rad) * (rOuter - 9) + 4;
      var text = document.createElementNS(svgNS, 'text');
      text.setAttribute('x', rx);
      text.setAttribute('y', ry);
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('font-size', Math.max(12, size * 0.07));
      text.setAttribute('class', 'aot-windw-rose');
      text.textContent = o.t;
      svg.appendChild(text);
    });

    // Direction marker group (small circle at outer ring)
    var needleGroup = document.createElementNS(svgNS, 'g');
    needleGroup.setAttribute('id', 'needle-' + widget_id);
    needleGroup.setAttribute('transform', 'rotate(0 ' + cx + ' ' + cy + ')');

    // Circle positioned at the exact center of the ring stroke
    var marker = document.createElementNS(svgNS, 'circle');
    marker.setAttribute('cx', cx);
    marker.setAttribute('cy', cy - (rOuter));
    marker.setAttribute('r', dotR);
    marker.setAttribute('fill', dirColor);
    marker.setAttribute('stroke', dirColor);
    marker.setAttribute('stroke-width', 1);
    needleGroup.appendChild(marker);

    svg.appendChild(needleGroup);

    // Speed text (center)
    var speedText = document.createElementNS(svgNS, 'text');
    speedText.setAttribute('id', 'speed-' + widget_id);
    speedText.setAttribute('x', cx);
    speedText.setAttribute('y', cy + (size * (textOffsetPct/100.0)));
    speedText.setAttribute('text-anchor', 'middle');
    speedText.setAttribute('font-weight', '700');
    // speedText.setAttribute('font-family', 'Inter, "Noto Sans KR", system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif');
    speedText.setAttribute('font-size', Math.max(12, size * 0.12));
    speedText.setAttribute('class', 'aot-windw-value');
    speedText.textContent = '';
    svg.appendChild(speedText);

    // Direction text under speed
    var dirText = document.createElementNS(svgNS, 'text');
    dirText.setAttribute('id', 'dirtext-' + widget_id);
    dirText.setAttribute('x', cx);
    dirText.setAttribute('y', cy + (size * (textOffsetPct/100.0)) + Math.max(18, size*0.10));
    dirText.setAttribute('text-anchor', 'middle');
    dirText.setAttribute('font-size', Math.max(10, size * 0.06) * dirFontEm);
    // dirText.setAttribute('font-family', 'Inter, "Noto Sans KR", system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif');
    dirText.setAttribute('class', 'aot-windw-sub');
    dirText.textContent = '';
    svg.appendChild(dirText);

    el.appendChild(svg);

    // Adjust dirText Y based on computed speed font-size (to keep spacing tidy)
    setTimeout(function(){
      try{
        var t = document.getElementById('speed-' + widget_id);
        var dtxt = document.getElementById('dirtext-' + widget_id);
        if (t && dtxt){
          var fs = parseFloat(getComputedStyle(t).fontSize) || (size*0.12);
          var baseY = cy + (size * (textOffsetPct/100.0));
          // place direction ~0.75 of speed font below baseline + small padding
          dtxt.setAttribute('y', baseY + fs*0.75 + Math.max(6, size*0.02));
        }
      }catch(e){}
    }, 0);

    // store geometry for updates
    window.widget[widget_id].__cx = cx;
    window.widget[widget_id].__cy = cy;
    window.widget[widget_id].__rOuter = rOuter;
  }

  function aotWindAngleToCompass8(deg){
    var d = ((Number(deg)%360)+360)%360;
    var card = function(x){ 
      return [window._('N'), window._('E'), window._('S'), window._('W')][x]; 
    };
    // If within 22.5° of a cardinal, return it directly
    var near = [0,90,180,270];
    for (var i=0;i<near.length;i++){
      if (Math.abs(d - near[i]) <= 22.5 || Math.abs(d - near[i] + 360) <= 22.5) {
        return card(i);
      }
    }
    // Determine quadrant
    if (d > 0 && d < 90){ // N-E
      return window._('NE');
    } else if (d > 90 && d < 180){ // E-S
      return window._('SE');
    } else if (d > 180 && d < 270){ // S-W
      return window._('SW');
    } else { // 270..360 or 0
      return window._('NW');
    }
  }

  function aotWindUpdateNeedle(widget_id, deg) {
    var g = document.getElementById('needle-' + widget_id);
    if (!g) return;
    var cx = window.widget[widget_id].__cx || 0;
    var cy = window.widget[widget_id].__cy || 0;
    // Normalize input (handles strings, NaN, negatives, >360)
    var d = Number(deg);
    if (!isFinite(d)) d = 0;
    var lbl = document.getElementById('dirtext-' + widget_id);
    // ⚠ 값이 없을 때 바늘을 0° 로 돌리면 **북풍이라는 멀쩡한 측정값처럼 보인다.**
    // 예전에는 204(데이터 없음)와 통신 실패 모두 이 함수를 0 으로 불렀다.
    // 값이 없으면 바늘을 감추고 방향 글자도 대시로 둔다.
    if (deg === null || deg === undefined) {
      g.style.display = 'none';
      if (lbl) { lbl.textContent = '—'; lbl.setAttribute('class', 'aot-windw-sub aot-w-nodata'); }
      return;
    }
    g.style.display = '';
    d = ((d % 360) + 360) % 360; // wrap into [0,360)
    // Our needle geometry points to North when 0°, so rotate by d directly.
    g.setAttribute('transform', 'rotate(' + (d % 360) + ' ' + cx + ' ' + cy + ')');
    if (lbl) { lbl.textContent = aotWindAngleToCompass8(d); lbl.setAttribute('class', 'aot-windw-sub'); }
  }

  function aotWindUpdateSpeed(widget_id, val, unit, decimals, dataFontSizeEm, unitFontSizeEm) {
    var t = document.getElementById('speed-' + widget_id);
    if (!t) return;
    // 값이 없으면 **빈 칸이 아니라 대시**. 빈 칸은 "0" 인지 "센서가 죽었" 는지
    // "아직 안 왔" 는지를 구분해 주지 못한다. 단위도 붙이지 않는다.
    if (val === null || val === undefined) {
      t.innerHTML = '<tspan class="aot-w-nodata" style="font-size:var(--aot-fs-value)">—</tspan>';
      return;
    }
    var v = Number(val).toFixed(decimals || 1);
    var dataSpan = '<tspan style="font-size:var(--aot-fs-value)">' + v + '</tspan>';
    var unitSpan = unit ? '<tspan style="font-size:var(--aot-fs-unit)"> ' + unit + '</tspan>' : '';
    t.innerHTML = dataSpan + unitSpan;
  }

  // --- Data fetchers (unchanged endpoints) ---
  function aotWindGetLastDir(widget_id,
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
          aotWindUpdateNeedle(widget_id, null);
        }
        else {
          const measurement = data[1];
          if (!window.widget) window.widget = {};
          if (!window.widget[widget_id]) window.widget[widget_id] = {};
          window.widget[widget_id].lastDir = measurement;
          aotWindUpdateNeedle(widget_id, measurement);
        }
      },
      error: function() {
        if (!window.widget) window.widget = {};
        if (!window.widget[widget_id]) window.widget[widget_id] = {};
        window.widget[widget_id].lastDir = null;
        aotWindUpdateNeedle(widget_id, null);
      }
    });
  }

  function aotWindRepeatLastDir(widget_id,
                          dev_id,
                          measure_type,
                          measurement_id,
                          period_sec,
                          max_measure_age_sec) {
    // Store the interval per widget and clear the previous one so a live-preview
    // re-init doesn't stack a second polling interval.
    window._wind_intervals = window._wind_intervals || {};
    var _k = widget_id + '_dir';
    if (window._wind_intervals[_k]) { clearInterval(window._wind_intervals[_k]); }
    window._wind_intervals[_k] = setInterval(function () {
      aotWindGetLastDir(widget_id,
                  dev_id,
                  measure_type,
                  measurement_id,
                  max_measure_age_sec)
    }, period_sec * 1000);
  }

  function aotWindGetLastSpeed(widget_id,
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
        aotWindUpdateSpeed(widget_id, window.widget[widget_id].lastSpeed, unitLabel, decimals, dataFontEm, unitFontEm);
      },
      error: function() {
        if (!window.widget) window.widget = {};
        if (!window.widget[widget_id]) window.widget[widget_id] = {};
        window.widget[widget_id].lastSpeed = null;
        aotWindUpdateSpeed(widget_id, window.widget[widget_id].lastSpeed, unitLabel, decimals, dataFontEm, unitFontEm);
      }
    });
  }

  function aotWindRepeatLastSpeed(widget_id,
                                   dev_id,
                                   measure_type,
                                   measurement_id,
                                   period_sec,
                                   max_measure_age_sec,
                                   decimals,
                                   dataFontEm,
                                   unitFontEm,
                                   unitLabel) {
    window._wind_intervals = window._wind_intervals || {};
    var _k = widget_id + '_speed';
    if (window._wind_intervals[_k]) { clearInterval(window._wind_intervals[_k]); }
    window._wind_intervals[_k] = setInterval(function () {
      aotWindGetLastSpeed(widget_id,
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
      if (typeof window.widget === 'undefined') window.widget = {};
      var wid = '{{each_widget.unique_id}}';
      if (!window.widget[wid]) window.widget[wid] = {};

      // Pass customizable options to JS FIRST (so build picks them up)
      window.widget[wid].opts = {
        border_color: '{{ widget_options.get('border_color', '#D5D5D5') }}',
        direction_color: '{{ widget_options.get('direction_color', '#F4D624') }}',
        direction_dot_px: {{ widget_options.get('direction_dot_px', 10) | float }},
        text_y_offset: {{ widget_options.get('text_y_offset', 5) | float }},
        direction_label_font_em: {{ widget_options.get('direction_label_font_em', 1.5) | float }}
      };

      // Prepare container styles
      var el = document.getElementById('container-gauge-' + wid);
      if (el) {
        if (!el.offsetHeight || !el.offsetWidth) el.style.minHeight = '120px';
        if (!el.style.zIndex) el.style.zIndex = '1';
        if (el.parentElement && getComputedStyle(el.parentElement).position === 'static') {
          el.parentElement.style.position = 'relative';
        }
      }

      // Build SVG once (uses options above)
      aotWindEnsureGauge(wid);

      // Initialize storage
      window.widget[wid].lastDir = null;
      window.widget[wid].lastSpeed = null;

      // Direction fetchers (guarded)
      {% if device_id_dir and measurement_id_dir %}
      {% for each_input in input  if each_input.unique_id == device_id_dir %}
      aotWindGetLastDir(wid, '{{device_id_dir}}', 'input', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
      aotWindRepeatLastDir(wid, '{{device_id_dir}}', 'input', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
      {%- endfor -%}
      {% for each_function in function if each_function.unique_id == device_id_dir %}
      aotWindGetLastDir(wid, '{{device_id_dir}}', 'function', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
      aotWindRepeatLastDir(wid, '{{device_id_dir}}', 'function', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
      {%- endfor -%}
      {% for each_pid in pid if each_pid.unique_id == device_id_dir %}
      aotWindGetLastDir(wid, '{{device_id_dir}}', 'pid', '{{measurement_id_dir}}', {{widget_options['max_measure_age']}});
      aotWindRepeatLastDir(wid, '{{device_id_dir}}', 'pid', '{{measurement_id_dir}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}});
      {%- endfor -%}
      {% endif %}

      // Determine unit label for speed
      var unitLabel = (function(){
        {% if measurement_id_spd %}
          {% if measurement_id_spd in dict_measure_units and dict_measure_units[measurement_id_spd] in dict_units and dict_units[dict_measure_units[measurement_id_spd]]['unit'] %}
            return '{{ dict_units[dict_measure_units[measurement_id_spd]]["unit"] }}';
          {% elif measurement_id_spd in device_measurements_dict and device_measurements_dict[measurement_id_spd].unit in dict_units %}
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
      aotWindGetLastSpeed(wid, '{{device_id_spd}}', 'input', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      aotWindRepeatLastSpeed(wid, '{{device_id_spd}}', 'input', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      {%- endfor -%}
      {% for each_function in function if each_function.unique_id == device_id_spd %}
      aotWindGetLastSpeed(wid, '{{device_id_spd}}', 'function', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      aotWindRepeatLastSpeed(wid, '{{device_id_spd}}', 'function', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      {%- endfor -%}
      {% for each_pid in pid if each_pid.unique_id == device_id_spd %}
      aotWindGetLastSpeed(wid, '{{device_id_spd}}', 'pid', '{{measurement_id_spd}}', {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      aotWindRepeatLastSpeed(wid, '{{device_id_spd}}', 'pid', '{{measurement_id_spd}}', {{widget_options['refresh_seconds']}}, {{widget_options['max_measure_age']}}, {{ widget_options.get("decimal_places", 1) }}, {{ widget_options.get("text_font_size", 1.5) }}, {{ widget_options.get("unit_font_size", 0.7) }}, unitLabel);
      {%- endfor -%}
      {% endif %}
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
# Version with the "range end" field removed
############################
def custom_colors_gauge(form, error):
    """
    Parse only "range start" (low) and "color" (hex). "range end" (high) is left blank when stored in sorted_colors.
    Works safely even if the form has no entries or only some of them.
    """
    sorted_colors = []
    colors_hex = {}

    for key in form.keys():
        if key.startswith('color_low_number'):
            try:
                idx = int(key.replace('color_low_number', ''))
            except Exception:
                continue
            if idx not in colors_hex:
                colors_hex[idx] = {}
            for value in form.getlist(key):
                colors_hex[idx]['low'] = value
        elif key.startswith('color_hex_number'):
            try:
                idx = int(key.replace('color_hex_number', ''))
            except Exception:
                continue
            if idx not in colors_hex:
                colors_hex[idx] = {}
            for value in form.getlist(key):
                if not is_rgb_color(value):
                    error.append('Invalid hex color value')
                colors_hex[idx]['hex'] = value

    # Temporarily store as "low,,hex" in index order (add only if both exist)
    for i in sorted(colors_hex.keys()):
        low_val = colors_hex[i].get('low')
        hex_val = colors_hex[i].get('hex')
        if low_val is None or hex_val is None:
            continue
        sorted_colors.append(f"{low_val},,{hex_val}")

    return sorted_colors, error



def fill_missing_highs(custom_options_json, sorted_colors):
    """
    For every range, automatically compute the middle (High) when it is blank:
    - The next range's Low becomes the current range's High
    - For the last range, the widget 'max' value becomes High
    Safeguards:
    - Returns an empty list if sorted_colors is empty
    - Skips malformed entries
    """
    if not sorted_colors:
        return []

    max_val = custom_options_json.get('max', 360)
    # First parse: "low,high,hex" or "low,,hex"
    parsed = []
    for item in sorted_colors:
        parts = item.split(',')
        if len(parts) != 3:
            continue
        low_i, high_i, color_i = parts[0].strip(), parts[1].strip(), parts[2].strip()
        parsed.append([low_i, high_i, color_i])

    if not parsed:
        return []

    # Fill High using the next range's Low
    for i in range(len(parsed) - 1):
        low_i, high_i, color_i = parsed[i]
        low_next, _, _ = parsed[i + 1]
        if not high_i:
            parsed[i][1] = low_next

    # If the last range's High is blank, set it to max
    if not parsed[-1][1]:
        parsed[-1][1] = str(max_val)

    # Reassemble into strings
    return [f"{low},{high},{color}" for (low, high, color) in parsed]