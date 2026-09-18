# coding=utf-8
import os

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_babel import gettext
from flask_login import login_required, current_user

from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_camera
from aot.databases.models import Camera, Misc
from aot.aot_flask.utils import utils_general, utils_camera
from aot.config import PATH_CAMERAS
from aot.config_translations import TRANSLATIONS

blueprint = Blueprint(
    'routes_camera',
    __name__,
    static_folder='../static',
    template_folder='../templates'
)


#: 보기만 하는 엔드포인트 — 역할의 `view_camera`.
_VIEW_ENDPOINTS = frozenset({
    'routes_camera.camera_last_image',
})

#: 카메라를 바꾸거나 움직이는 엔드포인트 — `edit_controllers`(`/camera_submit`
#: 이 쓰던 기준). `/camera` 는 GET 이 보기, POST 가 추가·수정·삭제다.
_EDIT_ENDPOINTS = frozenset({
    'routes_camera.camera_detect',
    'routes_camera.camera_save_order',
    'routes_camera.camera_capture',
    'routes_camera.camera_timelapse',
    'routes_camera.camera_record_video',
})


@blueprint.before_request
def _require_camera_permission():
    """역할 검사 — 이 블루프린트는 로그인만 보고 있었다.

    2026-09-18 E2E 가 실측: 게스트(모든 권한 거짓)가 카메라 화면을 열고, 카메라를
    추가·수정(저장 경로 포함)·삭제하고, 촬영을 시킬 수 있었다. `view_camera` 는
    역할 설정 화면에서 켜고 끌 수 있었지만 **어디서도 검사되지 않았다.**
    """
    if not current_user.is_authenticated:
        return None   # login_required 가 로그인으로 돌려보낸다

    endpoint = request.endpoint
    if endpoint == 'routes_camera.page_camera':
        permission = 'edit_controllers' if request.method == 'POST' else 'view_camera'
    elif endpoint in _VIEW_ENDPOINTS:
        permission = 'view_camera'
    elif endpoint in _EDIT_ENDPOINTS:
        permission = 'edit_controllers'
    else:
        return None

    if utils_general.user_has_permission(permission, silent=True):
        return None
    message = gettext("Insufficient permission: %(permission)s",
                      permission=permission)
    if endpoint == 'routes_camera.page_camera':
        flash(message, 'error')
        return redirect(url_for('routes_general.home'))
    return jsonify({'status': 'error', 'message': message}), 403


@blueprint.route('/camera', methods=('GET', 'POST'))
@login_required
def page_camera():
    """카메라 페이지"""
    from aot.camera.platform import PlatformDetector
    from aot.camera.types import CAMERA_TYPES
    
    form_add_camera = forms_camera.CameraAdd()
    form_mod_camera = forms_camera.CameraMod()

    platform = PlatformDetector.detect_platform()
    available_camera_types = PlatformDetector.get_camera_types_for_platform(platform)
    detected_cameras = PlatformDetector.detect_available_cameras()
    
    # 카메라 목록 조회
    cameras = Camera.query.order_by(Camera.position_y, Camera.id).all()

    # POST 요청 처리
    if request.method == 'POST':
        action = None
        # 삭제를 **저장보다 먼저** 본다. 설정 폼에는 Enter 로도 저장되도록
        # `camera_mod` 숨은 칸이 늘 들어 있어서, 삭제 단추가 `camera_delete` 를
        # 덧붙여 보내도 저장 분기가 먼저 잡았다 — 확인창까지 거친 삭제가 조용히
        # 저장으로 처리되고 카메라는 남았다(2026-09-18 E2E 실측).
        if 'camera_add' in request.form:
            utils_camera.camera_add(form_add_camera, platform)
        elif 'camera_delete' in request.form:
            utils_camera.camera_delete(request.form.get('camera_id'))
        elif 'camera_activate' in request.form:
            utils_camera.camera_activate(request.form.get('camera_id'))
        elif 'camera_deactivate' in request.form:
            utils_camera.camera_deactivate(request.form.get('camera_id'))
        elif 'camera_mod' in request.form:
            utils_camera.camera_mod(form_mod_camera, request.form.get('camera_id'))

        return redirect(url_for('routes_camera.page_camera'))

    misc = Misc.query.first()

    return render_template(
        'pages/camera.html',
        cameras=cameras,
        dict_cameras=CAMERA_TYPES,
        available_camera_types=available_camera_types,
        detected_cameras=detected_cameras,
        platform=platform,
        dict_translation=TRANSLATIONS,
        form_add_camera=form_add_camera,
        form_mod_camera=form_mod_camera,
        misc=misc
    )


@blueprint.route('/camera/detect', methods=['GET'])
@login_required
def camera_detect():
    """카메라 자동 감지 API"""
    from aot.camera.platform import PlatformDetector
    try:
        platform = PlatformDetector.detect_platform()
        detected = PlatformDetector.detect_available_cameras()
        return jsonify({'status': 'success', 'platform': platform, 'cameras': detected})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@blueprint.route('/camera/save_order', methods=['POST'])
@login_required
def camera_save_order():
    """카메라 순서 저장"""
    positions = request.get_json()
    
    if not positions:
        return jsonify({'status': 'error', 'message': 'No data received'}), 400

    for camera_id, position_y in positions.items():
        camera = Camera.query.filter_by(unique_id=camera_id).first()
        if camera:
            camera.position_y = position_y
    
    db.session.commit()

    return jsonify({'status': 'success'})


@blueprint.route('/camera/capture/<camera_id>', methods=['POST'])
@login_required
def camera_capture(camera_id):
    """스냅샷 촬영 API"""
    from aot.devices.camera import camera_record

    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    path, filename = camera_record('photo', camera_id)
    if path and filename:
        from aot.utils.time_utils import utc_now, serialize_ts
        return jsonify({
            'status': 'success',
            'filename': filename,
            'timestamp': serialize_ts(utc_now())
        })
    return jsonify({'status': 'error', 'message': 'Capture failed'}), 500


@blueprint.route('/camera/last_image/<camera_id>')
@login_required
def camera_last_image(camera_id):
    """마지막 촬영 이미지 반환"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    # still 이미지 경로 결정
    if camera.path_still:
        image_dir = camera.path_still
    else:
        image_dir = os.path.join(PATH_CAMERAS, camera_id, 'still')

    if not os.path.isdir(image_dir):
        return jsonify({'status': 'error', 'message': 'No images'}), 404

    # 가장 최근 파일 찾기
    files = [f for f in os.listdir(image_dir)
             if os.path.isfile(os.path.join(image_dir, f))
             and f.lower().endswith(('.jpg', '.jpeg', '.png'))]

    if not files:
        return jsonify({'status': 'error', 'message': 'No images'}), 404

    files.sort(key=lambda f: os.path.getmtime(os.path.join(image_dir, f)), reverse=True)
    image_path = os.path.join(image_dir, files[0])

    # 경로 탈출 방지
    if not os.path.abspath(image_path).startswith(os.path.abspath(image_dir)):
        return jsonify({'status': 'error', 'message': 'Invalid path'}), 403

    return send_file(image_path, mimetype='image/jpeg')


@blueprint.route('/camera/timelapse/<camera_id>', methods=['POST'])
@login_required
def camera_timelapse(camera_id):
    """타임랩스 시작/중지 API"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    data = request.get_json()
    action = data.get('action') if data else None

    if action == 'start':
        camera.timelapse_started = True
        db.session.commit()
        return jsonify({'status': 'success', 'action': 'start'})
    elif action == 'stop':
        camera.timelapse_started = False
        db.session.commit()
        return jsonify({'status': 'success', 'action': 'stop'})

    return jsonify({'status': 'error', 'message': 'Invalid action'}), 400


@blueprint.route('/camera/record/<camera_id>', methods=['POST'])
@login_required
def camera_record_video(camera_id):
    """비디오 녹화 시작/중지 API"""
    from aot.devices.camera import camera_record

    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    data = request.get_json()
    action = data.get('action') if data else None

    if action == 'start':
        path, filename = camera_record('video', camera_id)
        if path and filename:
            return jsonify({'status': 'success', 'action': 'start', 'filename': filename})
        return jsonify({'status': 'error', 'message': 'Record start failed'}), 500
    elif action == 'stop':
        camera.stream_started = False
        db.session.commit()
        return jsonify({'status': 'success', 'action': 'stop'})

    return jsonify({'status': 'error', 'message': 'Invalid action'}), 400
