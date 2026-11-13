# coding=utf-8
import uuid
from flask import flash
from flask_babel import gettext
from aot.databases.models import Camera
from aot.aot_flask.extensions import db
from aot.aot_flask.camera.net_auth import clear_auth_latch
from aot.aot_flask.access import scope

CAMERA_TYPE_TO_LIBRARY = {
    'usb': 'opencv',
    'csi': 'libcamera',
    'ip': 'ip_camera',
    'ip_snapshot': 'ip_snapshot',
    'vigi': 'vigi',
    'onvif': 'onvif',
}

# CameraAdd.camera_type choices ('usb'/'csi'/'ip') use shorter keys than
# aot.utils.camera_types.CAMERA_TYPES ('usb_webcam'/'rpi_csi'/'ip_camera')
CAMERA_TYPE_TO_CONFIG_KEY = {
    'usb': 'usb_webcam',
    'csi': 'rpi_csi',
    'ip': 'ip_camera',
    'ip_snapshot': 'ip_camera',
    'vigi': 'vigi',
    'onvif': 'onvif',
}

#: camera_driver 행을 쓰는 카메라 종류(= library)
DRIVER_LIBRARIES = ('vigi', 'onvif')


def _stop_stream(camera_id):
    """실행 중인 스트림 스레드에 종료를 알린다(없으면 아무 일 없음)."""
    try:
        from aot.aot_flask.camera.base_camera import BaseCamera
        if camera_id in BaseCamera.running:
            BaseCamera.stop(camera_id)
    except Exception:
        pass


def _denied(camera_id):
    """그룹 스코프(A1b): 이 카메라의 탭을 조작할 수 없으면 flash 하고 True. **부수 효과보다 먼저** 부른다."""
    if scope.can_operate_device(camera_id):
        return False
    flash(scope.deny_message(), 'error')
    return True


def _save_driver(camera, form, req_form):
    """VIGI·ONVIF 카메라의 연결 설정을 camera_driver 에 저장한다(설계 §5.2, §9.2).
    ONVIF 는 `openapi_port` 칸을 ONVIF 서비스 포트로 재사용한다(범위 D6a) — 폼의 onvif_port.

    - 비밀번호 칸이 비어 있으면 저장된 값을 유지한다(화면은 저장된 값을 보여 주지 않는다).
    - 주소·계정·비밀번호가 **바뀔 때만** 인증 상태를 unverified 로 되돌린다. 같은 값으로 다시
      저장해도 래치(failed/locked)는 풀리지 않는다 — 푸는 것은 사용자의 '다시 연결' 뿐이다.
    - 주소·계정이 바뀌면 검증 기록과 인증서 고정을 지운다(다른 장치일 수 있다).
    """
    from aot.camera_drivers import secrets as secrets_mod
    from aot.camera_drivers.auth_guard import credential_fp
    from aot.databases.models import CameraDriver
    drv = CameraDriver.query.filter_by(camera_id=camera.unique_id).first()
    if drv is None:
        drv = CameraDriver(camera_id=camera.unique_id, vendor=camera.library)
        db.session.add(drv)
        drv.host, drv.username = '', 'admin'
    host = (form.ip_address.data or '').strip()
    user = (form.username.data or '').strip() or 'admin'
    new_pw = form.password.data or ''
    target_changed = (host != (drv.host or '')) or (user != (drv.username or ''))
    if camera.library == 'onvif':
        from aot.camera_drivers.onvif.soap import DEFAULT_PORT
        port = form.onvif_port.data or DEFAULT_PORT
        if not 1 <= int(port) <= 65535:
            port = DEFAULT_PORT
        if int(port) != (drv.openapi_port or 0):
            target_changed = True
            drv.openapi_port = int(port)
    drv.host, drv.username = host, user
    if new_pw:
        drv.password_sealed = secrets_mod.seal_password(new_pw)
    plain = new_pw or secrets_mod.open_password(drv.password_sealed)[0]
    fp = credential_fp(user, plain, secrets_mod.fp_key()) if plain else None
    if new_pw or target_changed or fp != drv.credential_fp:
        drv.credential_fp = fp
        drv.auth_state = 'unverified'
        drv.attempt_lease_until = None
        drv.auth_iface = drv.auth_code = drv.auth_at = None
    if target_changed:
        drv.verified_fp = None
        drv.tls_pin_sha256 = None
    profile = req_form.get('vigi_live_profile')
    if profile in (('main', 'sub') if camera.library == 'onvif' else ('main', 'sub', 'mjpeg')):
        drv.live_profile = profile
    # camera.library 는 그대로 둔다(vigi/onvif)


def _apply_tab(camera, req_form):
    """설정 모달의 '탭' 줄. 비우면 전원 공개. 넣을 탭도 조작할 수 있어야 한다."""
    if 'vigi_tab_id' not in req_form:       # VIGI·ONVIF 모달이 같은 이름을 쓴다
        return True
    tab_id = (req_form.get('vigi_tab_id') or '').strip() or None
    if tab_id and not scope.can_operate('tab', tab_id):
        flash(scope.deny_message(), 'error')
        return False
    camera.tab_id = tab_id
    return True


def camera_add(form, platform='unknown'):
    """새 카메라 추가"""
    from aot.utils.camera_types import CAMERA_TYPES
    try:
        camera_type = form.camera_type.data
        library = CAMERA_TYPE_TO_LIBRARY.get(camera_type, 'opencv')
        config = CAMERA_TYPES.get(CAMERA_TYPE_TO_CONFIG_KEY.get(camera_type, camera_type), {})

        msg_new_camera = gettext('New Camera')
        max_pos = db.session.query(db.func.max(Camera.position_y)).scalar()
        new_camera = Camera(
            unique_id=str(uuid.uuid4()),
            name=f"{msg_new_camera} ({config.get('display_name', camera_type)})",
            camera_type=camera_type,
            library=library,
            is_activated=False,
            position_y=(max_pos or 0) + 1,  # 맨 뒤에 추가
            capture_mode='snapshot',
            capture_settings={}
        )
        db.session.add(new_camera)
        db.session.commit()
        if library in DRIVER_LIBRARIES:
            from aot.databases.models import CameraDriver
            db.session.add(CameraDriver(camera_id=new_camera.unique_id, vendor=library,
                                        **({'openapi_port': 80} if library == 'onvif' else {})))
            db.session.commit()
        flash(gettext('Camera added successfully.'), 'success')
        return new_camera
    except Exception as e:
        db.session.rollback()
        msg_error = gettext('Error adding camera')
        flash(f"{msg_error}: {str(e)}", 'error')
        return None

def camera_mod(form, camera_id):
    """카메라 설정 수정"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        flash(gettext('Camera not found.'), 'error')
        return False
    if _denied(camera_id):
        return False

    try:
        camera.name = form.name.data
        camera.width = form.width.data
        camera.height = form.height.data
        camera.stream_fps = form.fps.data

        # 촬영 모드
        if hasattr(form, 'capture_mode') and form.capture_mode.data:
            camera.capture_mode = form.capture_mode.data

        if camera.library in DRIVER_LIBRARIES:
            from flask import request
            if not _apply_tab(camera, request.form):
                db.session.rollback()
                return False
            _save_driver(camera, form, request.form)
        elif camera.camera_type in ('usb', 'usb_webcam'):
            camera.opencv_device = form.device_id.data
        elif camera.camera_type in ('ip', 'ip_camera', 'stream_url'):
            camera.url_stream = form.ip_address.data
            camera.auth_username = form.username.data
            camera.auth_password = form.password.data
            camera.library = 'ip_camera'
        elif camera.camera_type == 'ip_snapshot':
            camera.url_still = form.ip_address.data
            camera.auth_username = form.username.data
            camera.auth_password = form.password.data
            camera.library = 'ip_snapshot'

        # 저장 경로
        camera.path_still = form.path_still.data or ''
        camera.path_timelapse = form.path_timelapse.data or ''
        camera.path_video = form.path_video.data or ''

        # 표시 옵션
        camera.hide_still = form.hide_still.data
        camera.hide_timelapse = form.hide_timelapse.data
        camera.show_preview = form.show_preview.data
        camera.output_format = form.output_format.data or None

        # 캡처 전후 명령어
        camera.cmd_pre_camera = form.cmd_pre_camera.data or ''
        camera.cmd_post_camera = form.cmd_post_camera.data or ''

        db.session.commit()
        clear_auth_latch(camera_id)  # 설정을 저장하면 인증 실패 래치를 푼다(다음 시청에 1회 시도)
        _stop_stream(camera_id)  # 다음 시청부터 새 설정으로 접속
        flash(gettext('Camera settings updated.'), 'success')
        return True
    except Exception as e:
        db.session.rollback()
        msg_error = gettext('Error updating camera')
        flash(f"{msg_error}: {str(e)}", 'error')
        return False

def camera_activate(camera_id):
    """카메라 활성화"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        if _denied(camera_id):
            return False
        camera.is_activated = True
        db.session.commit()
        clear_auth_latch(camera_id)
        flash(gettext('Camera activated.'), 'success')
        return True
    return False

def camera_deactivate(camera_id):
    """카메라 비활성화"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        if _denied(camera_id):
            return False
        camera.is_activated = False
        db.session.commit()
        _stop_stream(camera_id)
        flash(gettext('Camera deactivated.'), 'success')
        return True
    return False

def camera_delete(camera_id):
    """카메라 삭제"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        if _denied(camera_id):
            return False
        try:
            from aot.databases.models import CameraDriver, CameraEvent
            # SQLite 는 FK 연쇄 삭제가 꺼져 있을 수 있어 직접 지운다
            CameraEvent.query.filter_by(camera_id=camera_id).delete()
            CameraDriver.query.filter_by(camera_id=camera_id).delete()
            db.session.delete(camera)
            db.session.commit()
            _stop_stream(camera_id)
            flash(gettext('Camera deleted successfully.'), 'success')
            return True
        except Exception as e:
            db.session.rollback()
            msg_error = gettext('Error deleting camera')
            flash(f"{msg_error}: {str(e)}", 'error')
            return False
    return False
