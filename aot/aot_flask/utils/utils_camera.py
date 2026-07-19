# coding=utf-8
import uuid
from flask import flash
from flask_babel import gettext
from aot.databases.models import Camera
from aot.aot_flask.extensions import db

CAMERA_TYPE_TO_LIBRARY = {
    'usb': 'opencv',
    'csi': 'libcamera',
    'ip': 'ip_camera'
}

# CameraAdd.camera_type choices ('usb'/'csi'/'ip') use shorter keys than
# aot.camera.types.CAMERA_TYPES ('usb_webcam'/'rpi_csi'/'ip_camera')
CAMERA_TYPE_TO_CONFIG_KEY = {
    'usb': 'usb_webcam',
    'csi': 'rpi_csi',
    'ip': 'ip_camera'
}

def camera_add(form, platform='unknown'):
    """새 카메라 추가"""
    from aot.camera.types import CAMERA_TYPES
    try:
        camera_type = form.camera_type.data
        library = CAMERA_TYPE_TO_LIBRARY.get(camera_type, 'opencv')
        config = CAMERA_TYPES.get(CAMERA_TYPE_TO_CONFIG_KEY.get(camera_type, camera_type), {})

        max_pos = db.session.query(db.func.max(Camera.position_y)).scalar()
        new_camera = Camera(
            unique_id=str(uuid.uuid4()),
            name=f"{gettext('New Camera')} ({config.get('display_name', camera_type)})",
            camera_type=camera_type,
            library=library,
            is_activated=False,
            position_y=(max_pos or 0) + 1,  # 맨 뒤에 추가
            capture_mode='snapshot',
            capture_settings={}
        )
        db.session.add(new_camera)
        db.session.commit()
        flash(gettext('Camera added successfully.'), 'success')
        return new_camera
    except Exception as e:
        db.session.rollback()
        flash(f"{gettext('Error adding camera')}: {str(e)}", 'error')
        return None

def camera_mod(form, camera_id):
    """카메라 설정 수정"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if not camera:
        flash(gettext('Camera not found.'), 'error')
        return False

    try:
        camera.name = form.name.data
        camera.width = form.width.data
        camera.height = form.height.data
        camera.stream_fps = form.fps.data

        # 촬영 모드
        if hasattr(form, 'capture_mode') and form.capture_mode.data:
            camera.capture_mode = form.capture_mode.data

        if camera.camera_type in ('usb', 'usb_webcam'):
            camera.opencv_device = form.device_id.data
        elif camera.camera_type in ('ip', 'ip_camera', 'stream_url'):
            camera.url_stream = form.ip_address.data
            camera.auth_username = form.username.data
            camera.auth_password = form.password.data
            camera.library = 'ip_camera'

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
        flash(gettext('Camera settings updated.'), 'success')
        return True
    except Exception as e:
        db.session.rollback()
        flash(f"{gettext('Error updating camera')}: {str(e)}", 'error')
        return False

def camera_activate(camera_id):
    """카메라 활성화"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        camera.is_activated = True
        db.session.commit()
        flash(gettext('Camera activated.'), 'success')
        return True
    return False

def camera_deactivate(camera_id):
    """카메라 비활성화"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        camera.is_activated = False
        db.session.commit()
        flash(gettext('Camera deactivated.'), 'success')
        return True
    return False

def camera_delete(camera_id):
    """카메라 삭제"""
    camera = Camera.query.filter_by(unique_id=camera_id).first()
    if camera:
        try:
            db.session.delete(camera)
            db.session.commit()
            flash(gettext('Camera deleted successfully.'), 'success')
            return True
        except Exception as e:
            db.session.rollback()
            flash(f"{gettext('Error deleting camera')}: {str(e)}", 'error')
            return False
    return False
