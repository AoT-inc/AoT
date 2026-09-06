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

from aot.utils.constraints_pass import constraints_pass_positive_value
from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)


WIDGET_INFORMATION = {
  'widget_name_unique': 'AoT_fcst_announcement',
  'widget_name': lazy_gettext('AoT Weather Forecast'),
  'widget_library': '',
  'no_class': True,
  'message': lazy_gettext('Displays the KMA (Korea Meteorological Administration) short-term forecast for the period selected by the user.'),
  'widget_width': 4,
  'widget_height': 5,
  'custom_options': [
      {
          'id': 'measurement_max_age',
          'type': 'integer',
          'default_value': 3600,
          'required': True,
          'constraints_pass': constraints_pass_positive_value,
          'name': lazy_gettext('Maximum Validity Time'),
          'phrase': lazy_gettext('Set the maximum validity for the forecast announcement. (Seconds)')
      },
      {
          'id': 'refresh_seconds',
          'type': 'text',
          'class': 'aot-time-input',
          'default_value': 1800,
          'constraints_pass': constraints_pass_positive_value,
          'name': lazy_gettext('Refresh'),
          'phrase': lazy_gettext('Set the interval to refresh the forecast. (Seconds)')
      },
      {
          'id': 'font_em_tmp',
          'type': 'float',
          'default_value': 4.0,
          'constraints_pass': constraints_pass_positive_value,
          'name': lazy_gettext('Temperature Font Size (em)'),
          'phrase': lazy_gettext('Set the font size for the temperature display.')
      },
      {
          'id': 'font_em_text',
          'type': 'float',
          'default_value': 1.2,
          'constraints_pass': constraints_pass_positive_value,
          'name': lazy_gettext('Font Size (em)'),
          'phrase': lazy_gettext('Set the general font size.')
      },
      {
          'id': 'show_row_aot_weather_2',
          'type': 'bool',
          'default_value': True,
          'name': lazy_gettext('Detailed Forecast'),
          'phrase': lazy_gettext('Toggle the display of the detailed forecast announcement.')
      }
  ],
  'widget_dashboard_head': """
  <!-- No head content -->
  """,

  'widget_dashboard_title_bar': """
  {#- 이름은 셸이 렌더한다. 여기는 이름 옆 예보 시각(캡션)만 —
      예전에는 이것이 `aot-w-title` 이라 제목 행세를 했고, 그래서 이 위젯만
      대시보드에서 이름이 안 보였다. -#}
  <span id="forecast-time-{{each_widget.unique_id}}"
        class="widget-title-bar-forecast aot-w-caption"></span>
  """,

  # Body area (row-aot-weather-1, 2, 3)
  'widget_dashboard_body': """<style>
  /* 예보 표 — JS 가 만들어 넣는 표의 뼈대. 예전에는 이 네 줄이 JS 문자열의
     인라인 style 로 들어가 있었고 행 간격만 `10px` 로 사다리를 벗어나 있었다. */
  .aot-fcst-table {
    table-layout: fixed;
    width: 100%;
    border-collapse: separate;
    border-spacing: 0 var(--aot-space-3);
  }
</style>
  <div id="forecast-container-{{each_widget.unique_id}}" class="frame-aot day-background">
    <div class="row-aot-weather-1">
      <!-- 1) Icon display -->
      <div class="col-wether-graphic">
          <div id="forecast-icon-{{each_widget.unique_id}}" class="icon-aot-weather">
              <!-- Weather icon display -->
          </div>
      </div>

      <!-- 2) Current temperature (TMP) -->
      <div class="col-wether-tmp">
          <!-- Area filled in by JavaScript -->
          <span id="forecast-tmp-{{each_widget.unique_id}}"></span>
      </div>

      <!-- 3) Min/max temperature (TMN / TMX) -->
      <div class="col-wether-tmntmx">
          <div id="forecast-tmn-{{each_widget.unique_id}}"></div>
          <div id="forecast-tmx-{{each_widget.unique_id}}"></div>
      </div>
    </div>

    {% if widget_options.show_row_aot_weather_2 %}
    <div class="row-aot-weather-2">
      <div class="col-wether-announcment">
        <span id="forecast-text-{{each_widget.unique_id}}">
            <!-- Forecast announcement display -->
        </span>
      </div>
    </div>
    {% endif %}

    <div class="row-aot-weather-3">
      <span id="slider-container-{{each_widget.unique_id}}" style="width:80%;">
        <input type="range"
                class="btn-aot-slide-time"
                style="width:100%;"
                id="forecast-slider-{{each_widget.unique_id}}"
                min="-24"
                max="48"
                value="{{ each_widget.forecast_offset | default(0) }}">
      </span>
    </div>
  </div>
  """,
  'widget_dashboard_js': """
  // Additional JS functions can be defined here
  """,

  'widget_dashboard_js_ready': """
  // Additional JS setup code
  """,

'widget_dashboard_js_ready_end': """
$(document).ready(function(){
  var unique_id = '{{ each_widget.unique_id }}';
  var refreshSeconds = {{ widget_options.refresh_seconds | default(1800) }};

  var slider = document.getElementById('forecast-slider-' + unique_id);
  var iconContainer = document.getElementById('forecast-icon-' + unique_id);
  var textContainer = document.getElementById('forecast-text-' + unique_id);
  var container = document.getElementById('forecast-container-' + unique_id);
  var widgetTitleBar = document.getElementById('forecast-time-' + unique_id);

  var forecastData = null;

  // Newly applied font-size options:
  //   font_em_tmp  -> TMP (temperature) size
  //   font_em_text -> size of the remaining general text
  var fontTmp  = "{{ widget_options.font_em_tmp  | default(4.0) }}";  // number only
  var fontText = "{{ widget_options.font_em_text | default(1.2) }}";  // number only

  var tmpContainer = document.getElementById('forecast-tmp-' + unique_id);
  var tmnContainer = document.getElementById('forecast-tmn-' + unique_id);
  var tmxContainer = document.getElementById('forecast-tmx-' + unique_id);

  // Helper: convert a "yyyymmddhhmm" string into a Date object
  function parseDateString(dstr) {
    if (!dstr || dstr.length < 12) {
      return new Date();
    }
    var year = parseInt(dstr.substr(0,4));
    var month = parseInt(dstr.substr(4,2)) - 1;
    var day = parseInt(dstr.substr(6,2));
    var hour = parseInt(dstr.substr(8,2));
    var minute = parseInt(dstr.substr(10,2));
    return new Date(year, month, day, hour, minute, 0, 0);
  }

  // Helper: return the current time as a "yyyymmddhh00" string (minutes=00)
  function getWidgetNow() {
    var now = new Date();
    now.setMinutes(0);
    now.setSeconds(0);
    now.setMilliseconds(0);
    var year = now.getFullYear();
    var month = ('0' + (now.getMonth()+1)).slice(-2);
    var day = ('0' + now.getDate()).slice(-2);
    var hour = ('0' + now.getHours()).slice(-2);
    return "" + year + month + day + hour + "00";
  }

  function getWeatherIcon(data, forecastHour) {
    var isDay = (forecastHour >= 6 && forecastHour < 18);
    var sky = data.SKY;
    var pty = data.PTY;
    var pop = parseFloat(data.POP) || 0;
    var rn1 = parseFloat(data.RN1) || 0;
    var sno = parseFloat(data.SNO) || 0;
    var wsd = parseFloat(data.WSD) || 0;
    var tmp = parseFloat(data.TMP) || 0;

    // 1. Clear condition: SKY is "맑음", PTY is "없음", POP <= 20, RN1 and SNO are negligible (< 0.1)
    if (sky === "맑음" && pty === "없음" && pop <= 20 && rn1 < 0.1 && sno < 0.1) {
      if (wsd < 5) {
        return isDay
          ? "{{ url_for('static', filename='icons/sunny.svg') }}"
          : "{{ url_for('static', filename='icons/clear_night.svg') }}";
      } else {
        return isDay
          ? "{{ url_for('static', filename='icons/sunny_windy.svg') }}"
          : "{{ url_for('static', filename='icons/clear_night_windy.svg') }}";
      }
    }

    // 2. Partly cloudy condition: SKY is "맑음", "약간 구름" or "구름많음", PTY is "없음", POP 21-40%
    if ((sky === "맑음" || sky === "약간 구름" || sky === "구름많음") &&
        pty === "없음" && pop > 20 && pop <= 40) {
      return isDay
        ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
        : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
    }

    // 3. Mostly cloudy / overcast condition: SKY is "구름많음" or "흐림", PTY is "없음"
    if ((sky === "구름많음" || sky === "흐림") && pty === "없음") {
      if (pop > 40 && pop <= 70) {
        return "{{ url_for('static', filename='icons/cloudy.svg') }}";
      } else if (pop >= 70) {
        return "{{ url_for('static', filename='icons/overcast.svg') }}";
      } else {
        // Even with low precipitation probability, fall back to the partly-cloudy icon
        return isDay
          ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
          : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
      }
    }

    // 4. Rain condition: PTY is "비"
    if (pty === "비") {
      // Distinguish light vs heavy rain by threshold (using RN1, POP)
      if ((pop >= 40 && pop <= 70) || (rn1 >= 0.1 && rn1 <= 2)) {
        return "{{ url_for('static', filename='icons/light_rain.svg') }}";
      } else if (pop >= 70 || rn1 > 2) {
        return "{{ url_for('static', filename='icons/heavy_rain.svg') }}";
      } else if (wsd >= 7) {
        return "{{ url_for('static', filename='icons/rain_windy.svg') }}";
      } else {
        // Apply the rain icon even when no condition is met
        return "{{ url_for('static', filename='icons/light_rain.svg') }}";
      }
    }

    // 5. Rain/snow mix condition: PTY is "비/눈"
    if (pty === "비/눈") {
      return "{{ url_for('static', filename='icons/rain_snow_mix.svg') }}";
    }

    // 6. Snow condition: PTY is "눈" or SNO >= 1 (integer basis)
    if (pty === "눈" || sno >= 1) {
      return "{{ url_for('static', filename='icons/snow.svg') }}";
    }

    // 7. Shower condition: PTY is "소나기"
    if (pty === "소나기") {
      return "{{ url_for('static', filename='icons/shower.svg') }}";
    }

    // Fallback option: if no condition matches, decide based on the SKY value
    if (sky === "맑음") {
      return isDay
        ? "{{ url_for('static', filename='icons/sunny.svg') }}"
        : "{{ url_for('static', filename='icons/clear_night.svg') }}";
    } else if (sky === "약간 구름") {
      return isDay
        ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
        : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
    } else if (sky === "구름많음" || sky === "흐림") {
      return isDay
        ? "{{ url_for('static', filename='icons/cloudy.svg') }}"
        : "{{ url_for('static', filename='icons/overcast.svg') }}";
    }
    // In all other cases, return the partly-cloudy icon by default
    return isDay
      ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
      : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
  }

  function windDirection(vec) {
    vec = vec % 360;
    if (vec < 45) return window._("N");
    else if (vec < 90) return window._("NE");
    else if (vec < 135) return window._("E");
    else if (vec < 180) return window._("SE");
    else if (vec < 225) return window._("S");
    else if (vec < 270) return window._("SW");
    else if (vec < 315) return window._("W");
    else return window._("NW");
  }

  // (3) updateForecast()
  function updateForecast(hour) {
    hour = Math.max(-24, Math.min(48, parseInt(hour)));
    if (!forecastData || !forecastData.forecasts) {
      iconContainer.innerHTML = '<div>' + window._('Forecast data not found.') + '</div>';
      textContainer.innerHTML = "";
      tmpContainer.innerHTML = "";
      tmnContainer.innerHTML = "";
      tmxContainer.innerHTML = "";
      widgetTitleBar.textContent = "";
      container.classList.remove("day-background", "night-background");
      return;
    }

    var widget_now_str = getWidgetNow();
    var forecast_now_str = forecastData.now || widget_now_str;
    var widget_now = parseDateString(widget_now_str);
    var forecast_now = parseDateString(forecast_now_str);
    var deltaHours = Math.round((widget_now - forecast_now) / (1000 * 3600));

    var adjustedHour = parseInt(hour) + deltaHours;
    console.log("updateForecast - hour:", hour, "deltaHours:", deltaHours, "adjustedHour:", adjustedHour);
    var dataForHour = forecastData.forecasts[adjustedHour.toString()];

    if (!dataForHour) {
      iconContainer.innerHTML = '<div>' + window._('No forecast for the selected time.') + '</div>';
      textContainer.innerHTML = "";
      tmpContainer.innerHTML = "";
      tmnContainer.innerHTML = "";
      tmxContainer.innerHTML = "";
      widgetTitleBar.textContent = "";
      container.classList.remove("day-background", "night-background");
      return;
    }

    // As a simple example, keep the day/night background
    var forecastTime = new Date();
    forecastTime.setHours(forecastTime.getHours() + parseInt(hour));
    var forecastHour = forecastTime.getHours();

    if (forecastHour >= 6 && forecastHour < 18) {
      container.classList.add("day-background");
      container.classList.remove("night-background");
    } else {
      container.classList.add("night-background");
      container.classList.remove("day-background");
    }

    // Title bar
    var offset = hour;
    var forecastTime = new Date();
    forecastTime.setHours(forecastTime.getHours() + offset);
    var forecastHour = forecastTime.getHours();
    var forecastTimeString = "";
    if (offset < 0) {
        forecastTimeString = Math.abs(offset) + window._("h ago") + " ";
    } else if (offset === 0) {
        forecastTimeString = window._("Current Time") + " ";
    } else {
        forecastTimeString = offset + window._("h later") + " ";
    }
    // 담는 span 이 이미 `.aot-w-caption` 이다(제목줄 계약: 이름은 셸이 그리고
    // 위젯은 그 옆 부가물만 넣는다). 여기서 `.aot-w-title` 을 다시 씌우면
    // 예보 시각이 이름 옆에서 **두 번째 제목**처럼 커진다. 글자만 넣는다.
    widgetTitleBar.textContent = forecastTimeString + forecastHour + ':00 ' + window._('Forecast');

    // Center-align the icon
    iconContainer.style.display = 'flex';
    iconContainer.style.alignItems = 'center';
    iconContainer.style.justifyContent = 'center';

    var iconWrapper = $(iconContainer);
    var iconSrc = getWeatherIcon(dataForHour, forecastHour);
    var newImage = $('<img />', {
          src: iconSrc,
          class: 'icon-aot-weather',
          style: 'display:none;'
    });
    iconWrapper.empty();
    newImage.appendTo(iconWrapper);
    newImage.on('load', function() {
          $(this).fadeIn(500);
    });
    if (newImage[0].complete) {
          newImage.trigger('load');
    }

    // Extract values
    function formatNumber(val, decimals) {
      if (val === undefined || val === null || val === "") return null;
      var num = parseFloat(val);
      if (isNaN(num)) return null;
      if (decimals === 0) {
        return Math.round(num).toString();
      }
      return num.toFixed(decimals);
    }

    var tmp = formatNumber(dataForHour.TMP, 0);
    var reh = formatNumber(dataForHour.REH, 0);
    var tmn = formatNumber(dataForHour.TMN, 0);
    var tmx = formatNumber(dataForHour.TMX, 0);
    var pop = formatNumber(dataForHour.POP, 0);
    var rn1 = formatNumber(dataForHour.RN1, 1);
    var sno = formatNumber(dataForHour.SNO, 1);
    var windSpeed = formatNumber(dataForHour.WSD, 1);
    var windDirVal = dataForHour.VEC || 0;
    var directionStr = windDirection(windDirVal);

    // [1] TMP (current temperature): use font_em_tmp
    var tmpDisplay = tmp !== null ? tmp + '°' : '-';
    tmpContainer.innerHTML =
      '<span class="aot-w-value">' + tmpDisplay + '</span>';

    // [2] Remaining text such as TMN, TMX, forecast announcement
    var tmnDisplay = tmn !== null ? tmn + '°' : '-';
    var tmxDisplay = tmx !== null ? tmx + '°' : '-';
    tmnContainer.innerHTML =
      '<div class="aot-w-body aot-w-row-between">' +
      '<span>' + window._('Min:') + '</span>' +
      '<span>' + tmnDisplay + '</span>' +
      '</div>';
    tmxContainer.innerHTML =
      '<div class="aot-w-body aot-w-row-between">' +
      '<span>' + window._('Max:') + '</span>' +
      '<span>' + tmxDisplay + '</span>' +
      '</div>';

    directionStr += " ";  // space after the wind direction

    var forecastText = '<table class="aot-w-body aot-fcst-table">';
    forecastText += '<tr>';

    // (1) Humidity
    forecastText += '  <td class="aot-w-cell" style="width:33%">'
                  + '    <div class="aot-w-row-between">'
                  + '      <span>' + window._('Humidity:') + '</span>'
                  + '      <b>' + (reh !== null ? reh : '-') + '</b>'
                  + '      <span>%</span>'
                  + '    </div>'
                  + '  </td>';

    // (2) Precipitation probability
    forecastText += '  <td class="aot-w-cell" style="width:33%">'
                  + '    <div class="aot-w-row-between">'
                  + '      <span>' + window._('Precip:') + '</span>'
                  + '      <b>' + (pop !== null ? pop : '-') + '</b>'
                  + '      <span>%</span>'
                  + '    </div>'
                  + '  </td>';

    // (3) Snowfall or precipitation amount
    if (sno !== null && parseFloat(sno) > 0) {
      forecastText += '  <td class="aot-w-cell" style="width:34%">'
                    + '    <div class="aot-w-row-between">'
                    + '      <span>' + window._('Snowfall:') + '</span>'
                    + '      <b>' + sno + 'cm</b>'
                    + '    </div>'
                    + '  </td>';
    } else {
      forecastText += '  <td class="aot-w-cell" style="width:34%">'
                    + '    <div class="aot-w-row-between">'
                    + '      <span>' + window._('Rainfall:') + '</span>'
                    + '      <b>' + (rn1 !== null ? rn1 + 'mm' : '-') + '</b>'
                    + '    </div>'
                    + '  </td>';
    }
    forecastText += '</tr>';

    // Second row: wind direction, wind speed
    forecastText += '<tr>';
    forecastText += '  <td class="aot-w-cell" style="width:50%">'
                  + '    <div class="aot-w-row-between">'
                  + '      <span>' + window._('Wind Dir:') + '</span>'
                  + '      <b>' + directionStr + '</b>'
                  + '    </div>'
                  + '  </td>';
    forecastText += '  <td class="aot-w-cell" style="width:50%">'
                  + '    <div class="aot-w-row-between">'
                  + '      <span>' + window._('Wind Speed:') + '</span>'
                  + '      <b>' + windSpeed + '</b>'
                  + '      <span>m/s</span>'
                  + '    </div>'
                  + '  </td>';
    forecastText += '</tr>';
    forecastText += '</table>';

    textContainer.innerHTML = forecastText;
  }

  // (4) fetchForecastData
  function fetchForecastData(callback) {
    $.getJSON("{{ url_for('static', filename='json/forecast.json') }}")
      .done(function(data) {
        forecastData = data;
        if (callback) callback();
      })
      .fail(function() {
        forecastData = null;
        iconContainer.innerHTML = '<div>' + window._('Unable to load forecast data.') + '</div>';
        textContainer.innerHTML = "";
        tmpContainer.innerHTML = "";
        tmnContainer.innerHTML = "";
        tmxContainer.innerHTML = "";
        widgetTitleBar.textContent = "";
        container.classList.remove("day-background", "night-background");
      });
  }

  // Slider event
  slider.addEventListener("input", function() {
    var hour = parseInt(this.value);
    localStorage.setItem('forecast_slider_' + unique_id, hour);
    updateForecast(hour);
  });

  // Initial load
  var storedHour = localStorage.getItem('forecast_slider_' + unique_id);
  if (storedHour !== null) {
    slider.value = storedHour;
  }

  fetchForecastData(function() {
    updateForecast(parseInt(slider.value));
  });

  // [AoT] Responsive Resize Logic (ResizeObserver)
  if (window.ResizeObserver && container) {
      var baseFontTmp = parseFloat("{{ widget_options.font_em_tmp  | default(4.0) }}");
      var baseFontText = parseFloat("{{ widget_options.font_em_text | default(1.2) }}");
      // [Tuning] Mobile-First Base Width (375px)
      var baseWidth = 375; 

      var resizeObserver = new ResizeObserver(function(entries) {
          for (var i = 0; i < entries.length; i++) {
              // width from contentRect
              var width = entries[i].contentRect.width;
              if (width > 0) {
                  var scale = width / baseWidth;
                  
                  // [Tuning] Apply clamping (0.8 ~ 1.0)
                  // Mobile (375px): 1.0x (Standard)
                  // Desktop (800px+): Max 1.0x (Capped at standard size)
                  // Small: Min 0.8x
                  scale = Math.min(Math.max(scale, 0.8), 1.0);

                  // Update global font variables
                  fontTmp = (baseFontTmp * scale).toFixed(2);
                  fontText = (baseFontText * scale).toFixed(2);

                  // Trigger re-render immediately
                  updateForecast(parseInt(slider.value));
              }
          }
      });
      resizeObserver.observe(container);
  }

  // Periodic refresh
  setInterval(function(){
    fetchForecastData(function(){
      updateForecast(parseInt(slider.value));
    });
  }, refreshSeconds * 1000);
});
"""
}