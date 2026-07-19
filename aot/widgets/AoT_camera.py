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

try:
    from aot.camera.dependencies import CAMERA_DEPENDENCIES
    from aot.camera.service import CameraService
except ImportError as e:
    logger.error(f"Failed to import camera dependencies: {e}")
    CAMERA_DEPENDENCIES = {}
    CameraService = None

# This widget follows the AoT_ai widget pattern
# It can define its own endpoints or reuse camera_api

def execute_at_creation(error, new_widget, dict_widget):
    """
    Called when a new camera widget is created.
    Can trigger dependency installation here if needed, 
    though CameraService.add_camera() handles it at the resource level.
    """
    return error, new_widget

def execute_at_modification(mod_widget, request_form, custom_options_json_presave, custom_options_json_postsave):
    return True, True, mod_widget, custom_options_json_postsave

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_camera',
    'widget_name': lazy_gettext('Modern Camera'),
    'widget_library': 'aot.camera',
    'no_class': True,
    'message': lazy_gettext('Advanced camera widget with auto-dependency installation and profile support.'),
    
    # Auto-installation of core dependencies via the system's widget installer
    'dependencies_module': [
        ('pip-pypi', 'opencv-python', 'opencv-python>=4.8.0'),
        ('pip-pypi', 'python-onvif-zeep', 'python-onvif-zeep>=0.2.12')
    ],
    
    'execute_at_creation': execute_at_creation,
    'execute_at_modification': execute_at_modification,
    
    'widget_width': 6,
    'widget_height': 12,
    
    'custom_options': [
        {
            'id': 'camera_id',
            'type': 'select',
            'default_value': '',
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
        }
    ],
    
    'widget_dashboard_body': """
    <div id="{{each_widget.id}}-container" class="camera-container" style="width:100%; height:100%; background:#000; overflow:hidden; position:relative;">
        <img id="{{each_widget.id}}-video" src="" style="width:100%; height:100%; object-fit:contain; display:block;">
        <!-- 라이브 영상 위 HUD 오버레이: 임의 영상 배경 위에서 항상 보이도록 흰색+그림자 고정(테마 무관) -->
        <div id="{{each_widget.id}}-overlay" style="position:absolute; top:10px; left:10px; color:#fff; font-size:0.8em; text-shadow:1px 1px 2px #000;">
            <span id="{{each_widget.id}}-status">{{_('Connecting...')}}</span>
        </div>
    </div>
    """,
    
    'widget_dashboard_js': """
    const widgetId = '{{each_widget.id}}';
    const cameraId = '{{widget_options["camera_id"]}}';
    const mode = '{{widget_options["display_mode"]}}';
    const refresh = {{widget_options["refresh_rate"]}} * 1000;
    
    function updateCameraWidget() {
        const img = document.getElementById(widgetId + '-video');
        const status = document.getElementById(widgetId + '-status');
        
        if (mode === 'live') {
            img.src = '/api/camera/stream/' + cameraId + '?t=' + new Date().getTime();
            status.innerText = '{{_("LIVE")}}';
        } else if (mode === 'snapshot') {
            // Placeholder for snapshot endpoint
            img.src = '/api/camera/snapshot/' + cameraId + '?t=' + new Date().getTime();
            status.innerText = '{{_("SNAPSHOT")}}';
        }
    }
    
    $(document).ready(function() {
        updateCameraWidget();
        if (mode !== 'live') {
            setInterval(updateCameraWidget, refresh);
        }
    });
    """
}
