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

import logging

from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)


WIDGET_INFORMATION = {
  'widget_name_unique': 'AoT_fcst_announcement',
  'widget_name': 'AoT 단기예보문',
  'widget_library': '',
  'no_class': True,
  'message': '사용자가 선택한 시간의 기상청 발표 단기예보를 출력합니다.',
  'widget_width': 4,
  'widget_height': 5,
  'custom_options': [
      {
          'id': 'measurement_max_age',
          'type': 'integer',
          'default_value': 3600,
          'required': True,
          'constraints_pass': constraints_pass_positive_value,
          'name': '최대 유효 시간',
          'phrase': '최대 유효 발표 시간을 설정하세요. (초)'
      },
      {
          'id': 'refresh_seconds',
          'type': 'text',
          'class': 'aot-time-input',
          'default_value': 1800,
          'constraints_pass': constraints_pass_positive_value,
          'name': '새로고침',
          'phrase': '단기예보를 새로고침할 시간을 설정하세요. (초)'
      },
      {
          'id': 'font_em_tmp',
          'type': 'float',
          'default_value': 4.0,
          'constraints_pass': constraints_pass_positive_value,
          'name': '온도 크기(em)',
          'phrase': '온도표시 글자 크기를 설정하세요.'
      },
      {
          'id': 'font_em_text',
          'type': 'float',
          'default_value': 1.2,
          'constraints_pass': constraints_pass_positive_value,
          'name': '글자 크기(em)',
          'phrase': '일반 글자 크기를 설정하세요.'
      },
      {
          'id': 'show_row_aot_weather_2',
          'type': 'bool',
          'default_value': True,
          'name': '상세 예보',
          'phrase': '상세 예보문 표시 여부를 설정하세요.'
      }
  ],
  'widget_dashboard_head': """
  <!-- No head content -->
  """,

  'widget_dashboard_title_bar': """
  <span id="forecast-time-{{each_widget.unique_id}}" 
        class="widget-title-bar-forecast" 
        style="padding-right: 0.5em; font-size: {{each_widget.font_em_name}}em;">
  </span>
  """,

  # 바디 영역 (row-aot-weather-1, 2, 3)
  'widget_dashboard_body': """
  <div id="forecast-container-{{each_widget.unique_id}}" class="frame-aot day-background">
    <div class="row-aot-weather-1">
      <!-- 1) 아이콘 표시 -->
      <div class="col-wether-graphic">
          <div id="forecast-icon-{{each_widget.unique_id}}" class="icon-aot-weather">
              <!-- 날씨 아이콘 표시 --> 
          </div>
      </div>

      <!-- 2) 현재 온도 (TMP) -->
      <div class="col-wether-tmp">
          <!-- 자바스크립트에서 채워질 영역 -->
          <span id="forecast-tmp-{{each_widget.unique_id}}"></span>
      </div>

      <!-- 3) 최저/최고 온도 (TMN / TMX) -->
      <div class="col-wether-tmntmx" style="font-size: {{ widget_options.font_em_text | default(1) }}em;">
          <div id="forecast-tmn-{{each_widget.unique_id}}"></div>
          <div id="forecast-tmx-{{each_widget.unique_id}}"></div>
      </div>
    </div>

    {% if widget_options.show_row_aot_weather_2 %}
    <div class="row-aot-weather-2">
      <div class="col-wether-announcment">
        <span id="forecast-text-{{each_widget.unique_id}}">
            <!-- 예보문 표시 -->
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
  // 추가 JS 함수 정의 가능
  """,

  'widget_dashboard_js_ready': """
  // 추가 준비 JS 코드
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

  // 새로 적용한 폰트 크기 옵션:
  //   font_em_tmp  -> TMP(온도) 크기
  //   font_em_text -> 나머지 일반 텍스트 크기
  var fontTmp  = "{{ widget_options.font_em_tmp  | default(4.0) }}";  // 숫자만
  var fontText = "{{ widget_options.font_em_text | default(1.2) }}";  // 숫자만

  var tmpContainer = document.getElementById('forecast-tmp-' + unique_id);
  var tmnContainer = document.getElementById('forecast-tmn-' + unique_id);
  var tmxContainer = document.getElementById('forecast-tmx-' + unique_id);

  // 헬퍼 함수: "yyyymmddhhmm" 형식의 문자열을 Date 객체로 변환
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

  // 헬퍼 함수: 현재 시각을 "yyyymmddhh00" 형식의 문자열로 반환 (분=00)
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

    // 1. 맑음 조건: SKY가 "맑음", PTY가 "없음", POP가 20 이하, RN1과 SNO가 미세한 값(0.1 미만)
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

    // 2. 부분 구름 조건: SKY가 "맑음", "약간 구름" 또는 "구름많음"이고, PTY가 "없음", POP가 21~40%
    if ((sky === "맑음" || sky === "약간 구름" || sky === "구름많음") &&
        pty === "없음" && pop > 20 && pop <= 40) {
      return isDay
        ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
        : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
    }

    // 3. 구름 많음 / 흐림 조건: SKY가 "구름많음" 또는 "흐림", PTY가 "없음"
    if ((sky === "구름많음" || sky === "흐림") && pty === "없음") {
      if (pop > 40 && pop <= 70) {
        return "{{ url_for('static', filename='icons/cloudy.svg') }}";
      } else if (pop >= 70) {
        return "{{ url_for('static', filename='icons/overcast.svg') }}";
      } else {
        // 강수확률이 낮더라도 fallback으로 부분 구름 아이콘 적용
        return isDay
          ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
          : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
      }
    }

    // 4. 비 조건: PTY가 "비"
    if (pty === "비") {
      // 경계값에 따라 가벼운 비와 강한 비 구분 (RN1, POP 사용)
      if ((pop >= 40 && pop <= 70) || (rn1 >= 0.1 && rn1 <= 2)) {
        return "{{ url_for('static', filename='icons/light_rain.svg') }}";
      } else if (pop >= 70 || rn1 > 2) {
        return "{{ url_for('static', filename='icons/heavy_rain.svg') }}";
      } else if (wsd >= 7) {
        return "{{ url_for('static', filename='icons/rain_windy.svg') }}";
      } else {
        // 모든 조건 미충족 시에도 비 아이콘 적용
        return "{{ url_for('static', filename='icons/light_rain.svg') }}";
      }
    }

    // 5. 비/눈 혼합 조건: PTY가 "비/눈"
    if (pty === "비/눈") {
      return "{{ url_for('static', filename='icons/rain_snow_mix.svg') }}";
    }

    // 6. 눈 조건: PTY가 "눈" 또는 SNO가 1 이상 (정수 기준)
    if (pty === "눈" || sno >= 1) {
      return "{{ url_for('static', filename='icons/snow.svg') }}";
    }

    // 7. 소나기 조건: PTY가 "소나기"
    if (pty === "소나기") {
      return "{{ url_for('static', filename='icons/shower.svg') }}";
    }

    // Fallback 옵션: 조건에 걸리지 않을 경우, SKY 값을 기준으로 처리
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
    // 그 외의 경우에도 기본적으로 부분 구름 아이콘 반환
    return isDay
      ? "{{ url_for('static', filename='icons/partly_cloudy.svg') }}"
      : "{{ url_for('static', filename='icons/partly_cloudy_night.svg') }}";
  }

  function windDirection(vec) {
    vec = vec % 360;
    if (vec < 45) return "북풍";
    else if (vec < 90) return "북동풍";
    else if (vec < 135) return "동풍";
    else if (vec < 180) return "남동풍";
    else if (vec < 225) return "남풍";
    else if (vec < 270) return "남서풍";
    else if (vec < 315) return "서풍";
    else return "북서풍";
  }

  // (3) updateForecast()
  function updateForecast(hour) {
    hour = Math.max(-24, Math.min(48, parseInt(hour)));
    if (!forecastData || !forecastData.forecasts) {
      iconContainer.innerHTML = '<div>예보 데이터를 찾을 수 없습니다.</div>';
      textContainer.innerHTML = "";
      tmpContainer.innerHTML = "";
      tmnContainer.innerHTML = "";
      tmxContainer.innerHTML = "";
      widgetTitleBar.innerHTML = "";
      container.classList.remove("day-background", "night-background");
      return;
    }

    var widget_now_str = getWidgetNow();
    var forecast_now_str = forecastData.now || widget_now_str;
    var widget_now = parseDateString(widget_now_str);
    var forecast_now = parseDateString(forecast_now_str);
    var deltaHours = Math.round((widget_now - forecast_now) / (1000 * 3600));

    var adjustedHour = parseInt(hour) - deltaHours;
    var dataForHour = forecastData.forecasts[adjustedHour.toString()];

    if (!dataForHour) {
      iconContainer.innerHTML = '<div>선택한 시간의 예보가 없습니다.</div>';
      textContainer.innerHTML = "";
      tmpContainer.innerHTML = "";
      tmnContainer.innerHTML = "";
      tmxContainer.innerHTML = "";
      widgetTitleBar.innerHTML = "";
      container.classList.remove("day-background", "night-background");
      return;
    }

    // 단순 예시로 주/야간 배경은 유지
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

    // 타이틀바
    var offset = hour;
    var forecastTime = new Date();
    forecastTime.setHours(forecastTime.getHours() + offset);
    var forecastHour = forecastTime.getHours();
    var forecastTimeString = "";
    if (offset < 0) {
        forecastTimeString = Math.abs(offset) + "시간 전 ";
    } else if (offset === 0) {
        forecastTimeString = "현재 시간 ";
    } else {
        forecastTimeString = offset + "시간 뒤 ";
    }
    widgetTitleBar.innerHTML = '<span style="font-size:' + fontText + 'em; font-weight: bold;">' + forecastTimeString + forecastHour + ':00 예보</span>';

    // 아이콘 중앙 정렬
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

    // 값 추출
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

    // [1] TMP(현재 온도): font_em_tmp 사용
    var tmpDisplay = tmp !== null ? tmp + '°' : '-';
    tmpContainer.innerHTML =
      '<span style="font-size:' + parseFloat(fontTmp).toFixed(1) + 'em; font-weight:600;">' + tmpDisplay + '</span>';

    // [2] TMN, TMX, 예보문 등 나머지 텍스트: font_em_text 사용
    var tmnDisplay = tmn !== null ? tmn + '°' : '-';
    var tmxDisplay = tmx !== null ? tmx + '°' : '-';
    tmnContainer.innerHTML =
      '<div style="display:flex; justify-content:space-between; width:100%; font-size:' + fontText + 'em;">' +
      '<span>최저:</span>' +
      '<span>' + tmnDisplay + '</span>' +
      '</div>';
    tmxContainer.innerHTML =
      '<div style="display:flex; justify-content:space-between; width:100%; font-size:' + fontText + 'em;">' +
      '<span>최고:</span>' +
      '<span>' + tmxDisplay + '</span>' +
      '</div>';

    directionStr += " ";  // 풍향 뒤에 공백

    var forecastText = '<table style="table-layout: fixed; width: 100%; border-collapse: separate; border-spacing: 0 10px; font-size:' + parseFloat(fontText).toFixed(1) + 'em;">';
    forecastText += '<tr>';

    // (1) 습도
    forecastText += '  <td style="width:33%; padding: 0 8px; vertical-align: bottom;">'
                  + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                  + '      <span style="font-size:' + fontText + 'em;">습도:</span>'
                  + '      <b style="font-size:' + fontText + 'em;">' + (reh !== null ? reh : '-') + '</b>'
                  + '      <span style="font-size:' + fontText + ';">%</span>'
                  + '    </div>'
                  + '  </td>';

    // (2) 강수확률
    forecastText += '  <td style="width:33%; padding: 0 8px; vertical-align: bottom;">'
                  + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                  + '      <span style="font-size:' + fontText + 'em;">강수:</span>'
                  + '      <b style="font-size:' + fontText + 'em;">' + (pop !== null ? pop : '-') + '</b>'
                  + '      <span style="font-size:' + fontText + ';">%</span>'
                  + '    </div>'
                  + '  </td>';

    // (3) 적설 or 강수량
    if (sno !== null && parseFloat(sno) > 0) {
      forecastText += '  <td style="width:34%; padding: 0 8px; vertical-align: bottom;">'
                    + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                    + '      <span style="font-size:' + fontText + 'em;">적설:</span>'
                    + '      <b style="font-size:' + fontText + 'em;">' + sno + 'cm</b>'
                    + '    </div>'
                    + '  </td>';
    } else {
      forecastText += '  <td style="width:34%; padding: 0 8px; vertical-align: bottom;">'
                    + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                    + '      <span style="font-size:' + fontText + 'em;">강수량:</span>'
                    + '      <b style="font-size:' + fontText + 'em;">' + (rn1 !== null ? rn1 + 'mm' : '-') + '</b>'
                    + '    </div>'
                    + '  </td>';
    }
    forecastText += '</tr>';

    // 두 번째 행: 풍향, 풍속
    forecastText += '<tr>';
    forecastText += '  <td style="width:50%; padding: 0 8px; vertical-align: bottom;">'
                  + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                  + '      <span style="font-size:' + fontText + 'em;">풍향:</span>'
                  + '      <b style="font-size:' + fontText + 'em;">' + directionStr + '</b>'
                  + '    </div>'
                  + '  </td>';
    forecastText += '  <td style="width:50%; padding: 0 8px; vertical-align: bottom;">'
                  + '    <div style="display:flex;justify-content:space-between;align-items:flex-end;">'
                  + '      <span style="font-size:' + fontText + 'em;">풍속:</span>'
                  + '      <b style="font-size:' + fontText + 'em;">' + windSpeed + '</b>'
                  + '      <span style="font-size:' + fontText + ';">m/s</span>'
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
        iconContainer.innerHTML = '<div>예보 데이터를 불러올 수 없습니다.</div>';
        textContainer.innerHTML = "";
        tmpContainer.innerHTML = "";
        tmnContainer.innerHTML = "";
        tmxContainer.innerHTML = "";
        widgetTitleBar.innerHTML = "";
        container.classList.remove("day-background", "night-background");
      });
  }

  // 슬라이더 이벤트
  slider.addEventListener("input", function() {
    var hour = parseInt(this.value);
    localStorage.setItem('forecast_slider_' + unique_id, hour);
    updateForecast(hour);
  });

  // 초기 로드
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

  // 주기적 갱신
  setInterval(function(){
    fetchForecastData(function(){
      updateForecast(parseInt(slider.value));
    });
  }, refreshSeconds * 1000);
});
"""
}
