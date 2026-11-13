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
    from aot.utils.camera_platform import PlatformDetector
    from aot.utils.camera_types import CAMERA_TYPES
    
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

    # VIGI 카메라의 드라이버 상태(비밀 없음)와 탭 목록 — 설정 모달이 쓴다
    from aot.camera_drivers.status import build_status, recent_events
    from aot.aot_flask.extensions import db
    from aot.databases.models import CameraDriver, Tab
    vigi_ids = [c.unique_id for c in cameras if c.library in ('vigi', 'onvif')]   # 상태 dict 이름은 템플릿 호환
    vigi_status = {}
    if vigi_ids:
        rows = {r.camera_id: r for r in CameraDriver.query.filter(
            CameraDriver.camera_id.in_(vigi_ids)).all()}
        vigi_status = {cid: build_status(rows.get(cid), recent_events(db.session, cid))
                       for cid in vigi_ids}

    # 카메라 조작 패널(PTZ·주야·경보)은 조작할 수 있는 사람에게만 그린다 —
    # 제어 경로(/camera/driver/<id>/control/*)와 같은 두 문: 역할 → 그 카메라의 탭 스코프.
    vigi_can_control = {}
    if vigi_ids and utils_general.user_has_permission('edit_controllers', silent=True):
        from aot.aot_flask.access import scope
        vigi_can_control = {cid: scope.can_operate_device(cid) for cid in vigi_ids}

    return render_template(
        'pages/camera.html',
        vigi_status=vigi_status,
        vigi_can_control=vigi_can_control,
        tabs=Tab.query.order_by(Tab.name).all(),
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
    from aot.utils.camera_platform import PlatformDetector
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
        from aot.utils.timekit import utc_now
        from aot.utils.timekit import iso_at, FARM
        return jsonify({
            'status': 'success',
            'filename': filename,
            'timestamp': iso_at(utc_now(), FARM)
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

    image_path = _latest_still(image_dir)
    if not image_path:
        return jsonify({'status': 'error', 'message': 'No images'}), 404

    # 경로 탈출 방지
    if not os.path.abspath(image_path).startswith(os.path.abspath(image_dir)):
        return jsonify({'status': 'error', 'message': 'Invalid path'}), 403

    # 대시보드 카메라 위젯이 이 주소를 몇 초마다 다시 부른다. 앱 기본값
    # (SEND_FILE_MAX_AGE_DEFAULT = 1년, public)을 그대로 쓰면 브라우저가 서버에 묻지도
    # 않으므로 위젯이 `?t=` 로 캐시를 깨야 했고, 그 결과 같은 사진을 매번 통째로 받았다.
    # max_age=0 이면 `no-cache`(매번 재검증) + ETag 라, 사진이 그대로일 때는 304 한 줄로
    # 끝난다. 로그인한 사람만 보는 사진이므로 공유 캐시에는 남기지 않는다(private).
    mimetype = 'image/png' if image_path.lower().endswith('.png') else 'image/jpeg'
    response = send_file(image_path, mimetype=mimetype, max_age=0)
    response.cache_control.private = True
    response.cache_control.public = False
    return response


#: 사진 폴더 → (폴더 mtime_ns, 가장 최근 파일 이름).
#: 폴더의 mtime 은 파일이 추가·삭제·이름 변경될 때 바뀐다. 그대로면 "가장 최근 파일"도
#: 그대로라, 폴링마다 폴더 전체를 훑고 정렬하지 않아도 된다(사진이 쌓일수록 그 비용이
#: SD 카드에서 선형으로 커진다). 같은 이름에 덮어쓰는 카메라는 이름이 같으므로 맞다.
#: 워커마다 따로 들고 있어도 무해하다 — 어긋나면 한 번 다시 훑을 뿐이다.
_LATEST_STILL_CACHE = {}
_STILL_SUFFIXES = ('.jpg', '.jpeg', '.png')


def _latest_still(image_dir):
    """`image_dir` 에서 가장 최근 사진의 전체 경로. 없으면 None."""
    try:
        dir_mtime = os.stat(image_dir).st_mtime_ns
    except OSError:
        return None
    hit = _LATEST_STILL_CACHE.get(image_dir)
    if hit and hit[0] == dir_mtime:
        cached = os.path.join(image_dir, hit[1])
        if os.path.isfile(cached):
            return cached

    newest = None  # (mtime_ns, name)
    try:
        with os.scandir(image_dir) as entries:
            for entry in entries:
                if not entry.name.lower().endswith(_STILL_SUFFIXES):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    mtime = entry.stat().st_mtime_ns
                except OSError:
                    continue
                if newest is None or mtime > newest[0]:
                    newest = (mtime, entry.name)
    except OSError:
        return None
    if newest is None:
        _LATEST_STILL_CACHE.pop(image_dir, None)
        return None
    _LATEST_STILL_CACHE[image_dir] = (dir_mtime, newest[1])
    return os.path.join(image_dir, newest[1])


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
