# coding=utf-8
"""
Modernized Camera Widget for AoT_ai.
Integrates with the new camera system and supports auto-dependency installation.
"""
import logging
import json
from flask import Blueprint, jsonify, request, Response
from flask_login import current_user
from flask_babel import lazy_gettext
logger = logging.getLogger(__name__)

# This widget follows the AoT_ai widget pattern
# It can define its own endpoints or reuse camera_api

def execute_at_creation(error, new_widget, dict_widget):
    """
    Called when a new camera widget is created.
    Dependencies are installed by the widget installer (dependencies_module).
    """
    return error, new_widget

def execute_at_modification(mod_widget, request_form, custom_options_json_presave, custom_options_json_postsave):
    return True, True, mod_widget, custom_options_json_postsave

# 영상 위 카메라 조작(PTZ) — 설계 §9.3. 그릴지 말지는 서버가 정한다:
#   VIGI 카메라이고, 연결이 확인됐고(능력을 읽음), PTZ 능력이 있고,
#   보는 사람이 조작할 수 있을 때(역할 edit_controllers + 그 카메라의 탭 스코프)만.
# 제어 경로(/camera/driver/<id>/control/*)가 같은 두 문을 다시 묻는다 — 여기서 숨기는 것은 화면 정리일 뿐이다.
_OVERLAY_FEATURES = ('ptz.pan_tilt', 'ptz.zoom', 'ptz.preset')


def ptz_overlay_features(camera_id, show_option=True):
    """위젯 겹침에 그릴 능력 목록. 그리지 않을 때는 빈 목록."""
    if not camera_id or not show_option:
        return []
    try:
        from aot.aot_flask.access import scope
        from aot.aot_flask.utils import utils_general
        from aot.camera_drivers.status import build_status
        from aot.databases.models import Camera, CameraDriver
        cam = Camera.query.filter_by(unique_id=camera_id).first()
        if cam is None or cam.library != 'vigi':
            return []
        if not utils_general.user_has_permission('edit_controllers', silent=True):
            return []
        if not scope.can_operate_device(camera_id):
            return []
        status = build_status(CameraDriver.query.filter_by(camera_id=camera_id).first())
        if status.get('auth_state') != 'ok':
            return []
        feats = (status.get('capabilities') or {}).get('features') or []
        return [f for f in _OVERLAY_FEATURES if f in feats]
    except Exception:
        logger.exception("camera widget: PTZ overlay check failed")
        return []


def widget_variables(widget_unique_id, widget_options):
    return {'ptz_features': ptz_overlay_features(
        (widget_options or {}).get('camera_id'),
        (widget_options or {}).get('show_ptz', True) not in (False, 'false', 'False', 0, '0'))}


WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_camera',
    'widget_name': lazy_gettext('Modern Camera'),
    'widget_library': 'aot.camera_drivers',
    'no_class': True,
    'message': lazy_gettext('Advanced camera widget with auto-dependency installation and profile support.'),
    
    # Auto-installation of core dependencies via the system's widget installer
    'dependencies_module': [
        ('pip-pypi', 'cv2', 'opencv-python-headless==4.9.0.80'),
        ('pip-pypi', 'onvif', 'onvif-zeep>=0.2.12')
    ],
    
    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    'generate_page_variables': widget_variables,
    
    'widget_width': 6,
    'widget_height': 12,
    
    'custom_options': [
        {
            'id': 'camera_id',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Camera'
            ],
            'name': lazy_gettext('Camera ID'),
            'phrase': lazy_gettext('Select the camera instance to display')
        },
        {
            'id': 'display_mode',
            'type': 'select',
            'default_value': 'live',
            'options_select': [
                ('live', 'Live Streaming (MJPEG)'),
                ('snapshot', 'Recent Snapshot'),
                ('timelapse', 'Latest Timelapse Frame')
            ],
            'name': lazy_gettext('Display Mode')
        },
        {
            'id': 'refresh_rate',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Refresh Rate (sec)')
        },
        {
            'id': 'show_ptz',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show camera controls'),
            'phrase': lazy_gettext(
                'Show direction, zoom and preset controls over the video when the camera supports them '
                'and you are allowed to operate it.')
        }
    ],
    
    'widget_dashboard_body': """<style>
  /* 영상 뒤 바탕 — 앱 다른 곳의 카메라 미리보기와 같은 색을 쓴다
     (모달의 카메라 미리보기가 이미 이 토큰을 쓴다). */
  .aot-camw-stage {
    width: 100%; height: 100%; position: relative;
    overflow: hidden;
    background: var(--camera-preview-bg, #1a1a1a);
  }
  .aot-camw-video { width: 100%; height: 100%; object-fit: contain; display: block; }
  /* HUD 오버레이: **임의의 영상 위**에 얹히므로 테마 토큰을 따르지 않는다 —
     밝은 장면에서도 읽히도록 흰 글자 + 그림자로 고정한다. 크기만 사다리에서 고른다. */
  .aot-camw-hud {
    position: absolute; top: var(--aot-space-2); left: var(--aot-space-2);
    color: #fff;
    font-size: var(--aot-fs-caption);
    text-shadow: 1px 1px 2px #000;
  }
</style>
    <div id="{{each_widget.id}}-container" class="camera-container aot-camw-stage aot-ptz-stage">
        <img id="{{each_widget.id}}-video" src="" class="aot-camw-video">
        <div id="{{each_widget.id}}-overlay" class="aot-camw-hud">
            <span id="{{each_widget.id}}-status">{{_('Connecting...')}}</span>
        </div>
        {%- if widget_variables and widget_variables.ptz_features %}
        {%- from 'macros/aot_ptz.html' import ptz_controller %}
        {{ ptz_controller(widget_options['camera_id'], 'overlay', widget_variables.ptz_features) }}
        {%- endif %}
    </div>
    """,
    
    # widget_dashboard_js 는 위젯 종류당 한 번 그려지는 전역 영역이라 each_widget /
    # widget_options 가 없다 — 위젯마다 다른 값은 widget_dashboard_js_ready_end 에서 넘긴다.
    #
    # MJPEG 는 <img> 하나가 연결 하나다. 화면 폭 전환(모바일 전체폭)·탭 전환·네트워크
    # 변동에서 브라우저가 그 연결을 끊으면 이미지가 멈춘 채 오류 이벤트도 없다 —
    # 그래서 이벤트(resize·visibilitychange·error)마다 다시 연다. 다만 실패가
    # 이어질 때 카메라를 두드리지 않도록 재시도 간격을 늘린다(카메라가 반복된 접속
    # 실패에 잠글 수 있다).
    'widget_dashboard_js': """
    var aotCameraState = {};
    function aotCameraWidgetUpdate(widgetId, cameraId, mode) {
        const img = document.getElementById(widgetId + '-video');
        const status = document.getElementById(widgetId + '-status');
        if (!img) { return; }
        if (!cameraId) {
            status.innerText = '{{_("No camera selected")}}';
            return;
        }
        if (mode === 'snapshot') {
            aotCameraSnapshot(widgetId, cameraId, img, status);
        }
    }

    // 스냅숏은 같은 주소를 "매번 재검증"으로 다시 묻는다. 서버는 ETag 를 주고 사진이
    // 그대로면 304 를 돌려준다 — 본문은 오지 않는다. fetch 는 304 를 캐시본 200 으로
    // 돌려주므로 ETag 가 직전과 같으면 그림을 바꾸지 않는다(디코딩도 건너뜀).
    // 예전에는 `?t=시각` 으로 캐시를 깨 같은 사진을 1초마다 통째로 받았다.
    function aotCameraSnapshot(widgetId, cameraId, img, status) {
        const st = aotCameraState[widgetId] = aotCameraState[widgetId] || {fails: 0, timer: null};
        if (st.snapBusy) { return; }
        st.snapBusy = true;
        fetch('/camera/last_image/' + cameraId, {credentials: 'same-origin', cache: 'no-cache'})
            .then(function(r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                const etag = r.headers.get('ETag') || '';
                if (etag && etag === st.snapEtag) { return null; }
                return r.blob().then(function(blob) { return {etag: etag, blob: blob}; });
            })
            .then(function(got) {
                status.innerText = '{{_("SNAPSHOT")}}';
                if (!got) { return; }
                const url = URL.createObjectURL(got.blob);
                const old = st.snapUrl;
                st.snapUrl = url;
                st.snapEtag = got.etag;
                img.src = url;
                if (old) { URL.revokeObjectURL(old); }
            })
            .catch(function() {
                status.innerText = '{{_("Reconnecting...")}}';
            })
            .then(function() { st.snapBusy = false; });
    }

    function aotCameraLive(widgetId, cameraId) {
        const img = document.getElementById(widgetId + '-video');
        const status = document.getElementById(widgetId + '-status');
        if (!img || !cameraId) { return; }
        const st = aotCameraState[widgetId] = aotCameraState[widgetId] || {fails: 0, timer: null};
        clearTimeout(st.timer);
        status.innerText = '{{_("Connecting...")}}';
        img.src = '/video_feed/' + cameraId + '?t=' + new Date().getTime();
    }

    function aotCameraBindLive(widgetId, cameraId) {
        const img = document.getElementById(widgetId + '-video');
        const status = document.getElementById(widgetId + '-status');
        if (!img || !cameraId) { return; }
        const st = aotCameraState[widgetId] = aotCameraState[widgetId] || {fails: 0, timer: null};
        img.addEventListener('load', function() {
            st.fails = 0;
            status.innerText = '{{_("LIVE")}}';
        });
        img.addEventListener('error', function() {
            // 숨김 탭에서 일부러 끊은 것은 실패가 아니다 — 다시 붙지 않는다.
            if (document.hidden) { return; }
            st.fails += 1;
            status.innerText = '{{_("Reconnecting...")}}';
            clearTimeout(st.timer);
            const wait = Math.min(5000 * Math.pow(2, st.fails - 1), 60000);
            st.timer = setTimeout(function() { aotCameraLive(widgetId, cameraId); }, wait);
        });
        let resizeTimer = null;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimer);
            if (document.hidden) { return; }
            resizeTimer = setTimeout(function() { aotCameraLive(widgetId, cameraId); }, 800);
        });
        // 탭이 숨으면 스트림을 끊는다. <img> 의 MJPEG 은 화면에 안 보여도 프레임을
        // 계속 받는다 — 폴링과 달리 전역 폴링 정지(aot-poll-visibility)가 닿지 않는
        // 상시 전송이다. src 속성을 지우면 요청이 끊기고 error 도 나지 않는다.
        // 돌아오면 기존처럼 다시 연다.
        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                clearTimeout(st.timer);
                clearTimeout(resizeTimer);
                img.removeAttribute('src');
            } else {
                aotCameraLive(widgetId, cameraId);
            }
        });
        aotCameraLive(widgetId, cameraId);
    }
    """,

    'widget_dashboard_js_ready_end': """
    $(function() {
        const widgetId = '{{each_widget.id}}';
        const cameraId = '{{widget_options["camera_id"]}}';
        let mode = '{{widget_options["display_mode"]}}';
        let refresh = {{widget_options["refresh_rate"] or 1}} * 1000;
        // 경량 모드(templates/_lite_mode.html)에서는 실시간 영상(끊임없는 MJPEG) 대신
        // 최근 사진을 5초 이상 간격으로 — 같은 사진이면 304 라 본문도 오지 않는다.
        if (document.documentElement.classList.contains('aot-lite')) {
            if (mode === 'live') { mode = 'snapshot'; }
            refresh = Math.max(refresh, 5000);
        }
        if (mode === 'live') {
            aotCameraBindLive(widgetId, cameraId);
        } else {
            aotCameraWidgetUpdate(widgetId, cameraId, mode);
            setInterval(function() { aotCameraWidgetUpdate(widgetId, cameraId, mode); }, refresh);
        }
    });
    """
}
