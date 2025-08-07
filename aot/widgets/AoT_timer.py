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
from flask_babel import lazy_gettext
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_timer',
    'widget_name': 'AoT 타이머',
    'widget_library': 'timer',
    'no_class': True,

    'message': (
        '타이머에 입력한 시간만큼 장치가 작동하고 꺼집니다.'
        '타이머 시간이 "0"이면 종료 전까지 연속 작동합니다.'
        '* 주의: 리로드/창 이탈 시 시간 초기화 될 수 있음.'
    ),

    'widget_width': 24,
    'widget_height': 7,

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'options_select': [
                'Output_Channels',
            ],
            'name': lazy_gettext('Output'),
            'phrase': '제어할 Output 을 선택하세요.'
        },
        {
            'id': 'refresh_seconds',
            'type': 'float',
            'default_value': 3.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': '{} ({})'.format(lazy_gettext("동기화"), lazy_gettext("초")),
            'phrase': lazy_gettext('사용할 측정값의 최대 유효 시간')
        },
        {
            'id': 'enable_status',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('상태 표시'),
            'phrase': lazy_gettext('작동상태를 타이틀바에 표시 합니다.')
        },
        {
            'id': 'status_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('상태 크기'),
            'phrase': '(em) 단위'
        },
        {
            'id': 'enable_timestamp',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('작동시간'),
            'phrase': lazy_gettext('작동시간을 표시 합니다.')
        },
        {
            'id': 'widget_name_font_em',
            'type': 'float',
            'default_value': 1.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('작동시간 글자 크기'),
            'phrase': '(em) 단위'
        },
        {
            'id': 'enable_output_controls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('타이머'),
            'phrase': lazy_gettext('타이머 기능을 활성화 합니다.')
        },
        {
            'id': 'font_em_time_input',
            'type': 'float',
            'default_value': 1.2,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('시간입력창 크기'),
            'phrase': '(em) 단위'
        }
    ],

    # ------------------ HEAD (CSS) ------------------
    'widget_dashboard_head': """<!-- No head content -->""",

    # ------------------ TITLE BAR ------------------
    'widget_dashboard_title_bar': """
    {%- if widget_options['enable_status'] -%}
      <span id="tm_state_{{each_widget.unique_id}}"></span>
    {%- else -%}
      <span style="display:none" id="tm_state_{{each_widget.unique_id}}"></span>
    {%- endif %}

    <span style="padding-right: 0.5em"> {{each_widget.name}}</span>
    """,

    # ------------------ BODY ------------------
    'widget_dashboard_body': """
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if widget_options['output'] and ',' in widget_options['output'] -%}
      {%- set device_id = widget_options['output'].split(',')[0] -%}
      {%- set channel_id = widget_options['output'].split(',')[1] -%}
    {%- endif -%}

    <!-- 최상위 컨테이너: aot_tm_{{unique_id}} -->
    <div class="frame-aot" id="aot_tm_{{each_widget.unique_id}}">

      <!-- 첫 번째 행 -->
      <div class="row-aot-1">
        <!-- Timestamp 표시 (왼쪽) -->
        <div class="col-aot-1">
          <span id="tm_timestamp_{{each_widget.unique_id}}" class="prt-text">
            <!-- 여기 타이머 경과시간 등 표시 -->
          </span>
        </div>

        <!-- 토글 스위치 (오른쪽) -->
        <div class="col-aot-2">
          <label class="btn-toggle">
            <input type="checkbox" 
                  id="tm_tog_{{each_widget.unique_id}}"
                  class="timer-toggle-input btn-toggle-input"
                  name="{{device_id}}/{{channel_id}}">
            <span class="btn-toggle-slider">
              <span class="btn-toggle-thumb"></span>
            </span>
          </label>
        </div>
      </div>

      <!-- 두 번째 행 -->
      <div class="row-aot-2">
        <!-- 시간 입력 영역 -->
        <div class="input-time">
          <input type="number" min="0" max="48"
                id="tm_hh_{{each_widget.unique_id}}"
                class="input-time-hh"
                value="0">
          <input type="number" min="0" max="59"
                id="tm_mm_{{each_widget.unique_id}}"
                class="input-time-mm"
                value="0">
          <input type="number" min="0" max="59"
                id="tm_ss_{{each_widget.unique_id}}"
                class="input-time-ss"
                value="0">
        </div>

        <!-- 버튼 영역 -->
        <div class="btn-time">
          <input id="tm_reset_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="재설정">
          <input id="tm_plus5_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="5분">
          <input id="tm_plus10_{{each_widget.unique_id}}"
                class="btn-time-item"
                type="button"
                value="10분">
        </div>
      </div>
    </div>
    """,

    # ------------------ JAVASCRIPT ------------------
    'widget_dashboard_js': """
    // (서버 통신 함수) 기존 명령어 그대로 유지
    function modOutputOutput_tm(cmdStr, widget_id) {
      $.ajax({
        type: 'GET',
        url: '/output_mod/' + cmdStr,
        success: function(data) {
          getGPIOStateOutput_tm(widget_id);
        },
        error: function(jqXHR, textStatus, errorThrown) {
          console.log("modOutputOutput_tm error:", errorThrown);
        }
      });
    }

    function getGPIOStateOutput_tm(widget_id) {
      // 토글(checkbox) 찾기
      const $chk = $('#tm_tog_'+widget_id);
      if (!$chk.length) return;

      const devName = $chk.attr('name'); 
      if (!devName) return;

      const dev_id = devName.split('/')[0];
      const ch_id  = devName.split('/')[1];

      // 최상위 컨테이너 (배경색 변경용)
      const $frame = $('#aot_tm_'+widget_id);

      // 상태표시용 span
      const $txt = $('#tm_state_'+widget_id);

      // Ajax로 상태 읽어오기
      $.getJSON('/outputstate_unique_id/' + dev_id + '/' + ch_id, function(state) {

        if (state === 'off') {
          $chk.prop('checked', false);
          $frame.removeClass('active-background pause-background')
                .addClass('inactive-background');
          tm_lockInputs(widget_id, false);
          if ($txt.length) $txt.text('(Inactive)');

          tm_stopCountdown(widget_id);
          tm_stopTimestamp(widget_id, false);

        } else if (state === 'on') {
          $chk.prop('checked', true);
          $frame.removeClass('inactive-background pause-background')
                .addClass('active-background');
          tm_lockInputs(widget_id, true);
          if ($txt.length) $txt.text('(Active)');

          tm_startTimestamp(widget_id);

        } else {
          // UI 변경 없이 오류 로그만 남깁니다.
          console.error("AoT Timer: No connection for widget:", widget_id);
          
          // 선택사항: AJAX로 서버 로그 엔드포인트에 오류 정보를 전송
          $.ajax({
            type: "POST",
            url: "/log_error",  // 서버 로그 엔드포인트 (구현 필요)
            data: JSON.stringify({
              widget: "AoT_timer",
              widget_id: widget_id,
              error: "(No Connection)"
            }),
            contentType: "application/json",
            success: function(){},
            error: function(){ console.error("Error logging failed."); }
          });
        }
      });
    }

    // 자동 갱신
    function tm_initAutoRefresh(widget_id, refreshSec) {
      if (!refreshSec || refreshSec <= 0) {
        return;
      }
      setInterval(function(){
        getGPIOStateOutput_tm(widget_id);
      }, refreshSec * 1000);
    }

    // 카운트다운 로직
    let tm_countdown = {};
    let tm_currentSec = {};

    function tm_getInputSec(widget_id){
      let hh = parseInt($('#tm_hh_'+widget_id).val()) || 0;
      let mm = parseInt($('#tm_mm_'+widget_id).val()) || 0;
      let ss = parseInt($('#tm_ss_'+widget_id).val()) || 0;
      if(hh>48) hh=48;
      if(mm>59) mm=59;
      if(ss>59) ss=59;
      return (hh*3600 + mm*60 + ss);
    }

    function tm_applyInputSec(widget_id, totalSec){
      if(totalSec<0) totalSec=0;
      let hh = Math.floor(totalSec/3600);
      let mm = Math.floor((totalSec%3600)/60);
      let ss = totalSec % 60;
      $('#tm_hh_'+widget_id).val(hh);
      $('#tm_mm_'+widget_id).val(mm);
      $('#tm_ss_'+widget_id).val(ss);
    }

    function tm_startCountdown(widget_id){
      if(tm_countdown[widget_id]) return; // 이미 동작 중이면 무시

      const totalSec = tm_getInputSec(widget_id);
      tm_currentSec[widget_id] = totalSec;

      tm_lockInputs(widget_id, true);

      if(totalSec <= 0){
        // 0초면 무기한
        return;
      }

      tm_countdown[widget_id] = setInterval(function(){
        if(tm_currentSec[widget_id] > 0){
          tm_currentSec[widget_id]--;
        }
        tm_applyInputSec(widget_id, tm_currentSec[widget_id]);

        if(tm_currentSec[widget_id] <= 0){
          clearInterval(tm_countdown[widget_id]);
          tm_countdown[widget_id] = null;

          // 서버 OFF
          let baseName = $('#tm_tog_'+widget_id).attr('name');
          if(baseName){
            let dev_id= baseName.split('/')[0];
            let ch_id= baseName.split('/')[1];
            let cmd= dev_id+'/'+ch_id+'/off/sec/0';
            modOutputOutput_tm(cmd, widget_id);
          }
        }
      }, 1000);
    }

    function tm_stopCountdown(widget_id){
      if(tm_countdown[widget_id]){
        clearInterval(tm_countdown[widget_id]);
        tm_countdown[widget_id] = null;
      }
      tm_lockInputs(widget_id, false);
    }

    function tm_lockInputs(widget_id, isLock){
      $('#tm_hh_'+widget_id).prop('readOnly', isLock);
      $('#tm_mm_'+widget_id).prop('readOnly', isLock);
      $('#tm_ss_'+widget_id).prop('readOnly', isLock);
      $('#tm_reset_'+widget_id).prop('disabled', isLock);
      $('#tm_plus5_'+widget_id).prop('disabled', isLock);
      $('#tm_plus10_'+widget_id).prop('disabled', isLock);
    }

    // 타임스탬프 로직
    let tm_timestampInterval = {};
    let tm_timestampStartSec = {};
    let tm_timestampStartDate = {};

    function tm_stopTimestamp(widget_id, clearDisplay=true){
      if(tm_timestampInterval[widget_id]){
        clearInterval(tm_timestampInterval[widget_id]);
        tm_timestampInterval[widget_id] = null;
      }
      if(clearDisplay){
        $('#tm_timestamp_'+widget_id).text('');
      }
    }

    function tm_startTimestamp(widget_id){
      if(tm_timestampInterval[widget_id]) return;

      const nowDate = new Date();
      tm_timestampStartDate[widget_id] = nowDate;
      tm_timestampStartSec[widget_id]  = Math.floor(nowDate.getTime()/1000);

      tm_updateTimestamp(widget_id);
      tm_timestampInterval[widget_id] = setInterval(function(){
        tm_updateTimestamp(widget_id);
      }, 1000);
    }

    function tm_updateTimestamp(widget_id){
      const now = Math.floor(new Date().getTime()/1000);
      const elapsed = now - tm_timestampStartSec[widget_id];
      const elapsedStr = tm_formatHMS(elapsed);
      const startedStr = tm_formatMD_HMS(tm_timestampStartDate[widget_id]);

      $('#tm_timestamp_'+widget_id).text(elapsedStr + ", " + startedStr);
    }

    function tm_formatHMS(sec){
      if(sec<0) sec=0;
      const hh= Math.floor(sec/3600);
      const mm= Math.floor((sec%3600)/60);
      const ss= sec%60;
      return String(hh).padStart(2,'0') + ":" +
             String(mm).padStart(2,'0') + ":" +
             String(ss).padStart(2,'0');
    }
    function tm_formatMD_HMS(d){
      let M = d.getMonth() + 1;
      let D = d.getDate();
      let h = d.getHours();
      let m = d.getMinutes();
      let s = d.getSeconds();
      return String(M).padStart(2, '0') + '월 '
           + String(D).padStart(2, '0') + '일 '
           + String(h).padStart(2, '0') + ":"
           + String(m).padStart(2, '0') + ":"
           + String(s).padStart(2, '0');
    }
    """,

    # ------------------ JS READY ------------------
    'widget_dashboard_js_ready': """
    // 버튼/이벤트 바인딩
    $('[id^="tm_reset_"]').click(function(){
      let wid= this.id.replace('tm_reset_','');
      $('#tm_hh_'+wid).val(0);
      $('#tm_mm_'+wid).val(0);
      $('#tm_ss_'+wid).val(0);
    });

    $('[id^="tm_plus5_"]').click(function(){
      let wid= this.id.replace('tm_plus5_','');
      let sec= tm_getInputSec(wid);
      sec += 5*60;
      if(sec>48*3600) sec=48*3600;
      tm_applyInputSec(wid, sec);
    });

    $('[id^="tm_plus10_"]').click(function(){
      let wid= this.id.replace('tm_plus10_','');
      let sec= tm_getInputSec(wid);
      sec += 10*60;
      if(sec>48*3600) sec=48*3600;
      tm_applyInputSec(wid, sec);
    });

    /* 토글 (ON/OFF) */
    $(document).off('change.timer', '.timer-toggle-input')
               .on('change.timer', '.timer-toggle-input', function(){
      let wid  = this.id.replace('tm_tog_','');
      let isOn = $(this).is(':checked');
      let devNm= $(this).attr('name');
      if(!devNm) return;

      let dev_id= devNm.split('/')[0];
      let ch_id = devNm.split('/')[1];
      let totalSec = tm_getInputSec(wid);

      if(isOn){
        // ON
        let cmd= dev_id+'/'+ch_id+'/on/sec/'+ totalSec;
        modOutputOutput_tm(cmd, wid);

        tm_startCountdown(wid);
        tm_startTimestamp(wid);

      } else {
        // OFF
        let cmd= dev_id+'/'+ch_id+'/off/sec/0';
        modOutputOutput_tm(cmd, wid);

        tm_stopCountdown(wid);
        tm_stopTimestamp(wid, false);
      }
    });

    document.querySelectorAll('.btn-time-item').forEach(function(btn) {
      btn.addEventListener('touchend', function() {
        btn.blur();
      });
    });
    """,

    # ------------------ JS READY END ------------------
    'widget_dashboard_js_ready_end': """
    {%- set device_id = '' -%}
    {%- set channel_id = '' -%}
    {%- if widget_options['output'] and ',' in widget_options['output'] -%}
      {%- set device_id = widget_options['output'].split(',')[0] -%}
      {%- set channel_id = widget_options['output'].split(',')[1] -%}
    {%- endif -%}

    {%- if device_id and channel_id -%}
      // 토글 name 속성
      $('#tm_tog_{{each_widget.unique_id}}')
        .attr('name', '{{device_id}}/{{channel_id}}');

      // 로드 시 1회 상태 확인
      getGPIOStateOutput_tm('{{each_widget.unique_id}}');

      // refresh_seconds 간격 자동 갱신
      tm_initAutoRefresh('{{each_widget.unique_id}}', {{widget_options['refresh_seconds']}});
    {%- else -%}
      console.warn("AoT_timer: device_id or channel_id missing.");
    {%- endif -%}
    """
}
