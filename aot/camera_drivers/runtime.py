# coding=utf-8
"""DB 의 camera_driver 행 → 실행에 필요한 객체(자격 증명·허브·스냅샷). 데몬·gunicorn 워커 공용.

비밀번호는 여기서 열어 객체에만 담고 밖으로 내지 않는다(로그·반환 dict 에 없음).
"""
from aot.camera_drivers import frames as F
from aot.camera_drivers import secrets as S
from aot.camera_drivers.auth_guard import AuthGuard
from aot.camera_drivers.db_store import DbAuthStore
from aot.camera_drivers.driver import Credential
from aot.camera_drivers.onvif import sources as onvif_src
from aot.camera_drivers.vigi import snapshot as snap
from aot.camera_drivers.vigi.sources import RtspCv2Source


def load_config(camera_id):
    """행이 없거나 비밀번호를 열 수 없으면 None."""
    from aot.config import AOT_DB_PATH
    from aot.databases.models import CameraDriver
    from aot.databases.utils import session_scope
    with session_scope(AOT_DB_PATH) as s:
        r = s.query(CameraDriver).filter(CameraDriver.camera_id == camera_id).first()
        if r is None or not r.host:
            return None
        cfg = dict(host=r.host, user=r.username, sealed=r.password_sealed, rtsp_port=r.rtsp_port,
                   live_profile=r.live_profile or 'sub', vendor=r.vendor or 'vigi',
                   openapi_port=r.openapi_port)
    pw, _ = S.open_password(cfg.pop('sealed'))
    if not pw:
        return None
    cfg['credential'] = Credential(cfg.pop('user'), pw)
    return cfg


def source_factory(camera_id, profile=None, store=None, cv2_module=None):
    """FrameHub 에 줄 소스 공장. 만들 때마다 DB 에서 설정을 다시 읽는다(설정 변경 반영)."""
    def make():
        cfg = load_config(camera_id)
        if cfg is None:
            raise F.SourceError('not_configured', fatal=True)
        if cfg['vendor'] == 'onvif':
            return onvif_src.OnvifRtspSource(
                AuthGuard(store or DbAuthStore()), camera_id, cfg['credential'], cfg['host'],
                cfg['openapi_port'], S.fp_key(), profile or cfg['live_profile'], cv2_module=cv2_module)
        return RtspCv2Source(AuthGuard(store or DbAuthStore()), camera_id, cfg['credential'],
                             cfg['host'], cfg['rtsp_port'], S.fp_key(),
                             profile or cfg['live_profile'], cv2_module=cv2_module)
    return make


def live_hub(camera_id, **kw):
    return F.get_hub(camera_id, source_factory(camera_id, **kw))


def snapshot_jpeg(camera_id, store=None, cv2_module=None, directory=None):
    """설계 §7 제안 A. 실패하면 SnapshotError(벤더별 — 호출자는 `snapshot_errors()` 로 잡는다)."""
    cfg = load_config(camera_id)
    if cfg is not None and cfg['vendor'] == 'onvif':
        return onvif_src.take_snapshot(
            camera_id, cfg['credential'], cfg['host'], cfg['openapi_port'],
            AuthGuard(store or DbAuthStore()), S.fp_key(),
            source_factory(camera_id, 'sub', store=store, cv2_module=cv2_module), directory=directory)
    return snap.take_snapshot(
        camera_id, source_factory(camera_id, 'mjpeg', store=store, cv2_module=cv2_module),
        directory=directory)


def snapshot_errors():
    """snapshot_jpeg 가 던질 수 있는 예외 클래스들(벤더 공통으로 잡기 위한 묶음)."""
    return (snap.SnapshotError, onvif_src.SnapshotError)
