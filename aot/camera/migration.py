# coding=utf-8
import logging
from aot.databases.models import Camera
from aot.aot_flask.extensions import db
from aot.camera.legacy_support import LEGACY_CAMERA_MAPPING

logger = logging.getLogger(__name__)

def migrate_legacy_cameras():
    """Migrate legacy camera configurations to the modernized backend structure.

    @phase active
    @stability stable
    @dependency Camera, LEGACY_CAMERA_MAPPING
    """
    cameras = Camera.query.all()
    migrated_count = 0

    for camera in cameras:
        old_type = camera.camera_type
        if old_type in LEGACY_CAMERA_MAPPING:
            mapping = LEGACY_CAMERA_MAPPING[old_type]
            
            logger.info(f"Migrating camera {camera.name} from {old_type} to {mapping['new_type']}")
            
            camera.camera_type = mapping['new_type']
            if mapping['legacy_backend']:
                # 레거시 백엔드를 사용하도록 설정 (필요시)
                # 현재는 library 필드를 그대로 두거나 매핑된 라이브러리로 교체
                pass
            
            # 기본 촬영 모드 설정
            if not camera.capture_mode:
                camera.capture_mode = 'snapshot'
            if not camera.capture_settings:
                camera.capture_settings = {}
                
            migrated_count += 1

    if migrated_count > 0:
        db.session.commit()
    
    return migrated_count
