# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases.sqla import db


class CameraDriver(CRUDMixin, db.Model):
    """제조사 중립 카메라 드라이버 설정 (Camera 1:1). 설계 docs/design/vigi-camera-module.md §5.2.

    비밀번호는 `password_sealed`(seal_secret)로만 저장한다. 인증 래치·시도 임대·검증된
    지문은 여러 프로세스(데몬·gunicorn 워커)가 compare-and-set 으로 함께 쓴다.
    시간 컬럼은 naive UTC 로 저장한다(timekit.naive_utc).

    @phase active
    """
    __tablename__ = "camera_driver"
    __table_args__ = {'extend_existing': True}

    camera_id = db.Column(db.String(36), db.ForeignKey('camera.unique_id', ondelete='CASCADE'),
                          primary_key=True)
    vendor = db.Column(db.Text, nullable=False, default='vigi')
    host = db.Column(db.Text, nullable=False, default='')
    mac = db.Column(db.Text, nullable=True)
    openapi_port = db.Column(db.Integer, nullable=False, default=20443)
    rtsp_port = db.Column(db.Integer, nullable=False, default=554)
    username = db.Column(db.Text, nullable=False, default='admin')
    password_sealed = db.Column(db.Text, nullable=True)
    credential_fp = db.Column(db.Text, nullable=True)
    verified_fp = db.Column(db.Text, nullable=True)
    auth_state = db.Column(db.Text, nullable=False, default='unverified')
    auth_iface = db.Column(db.Text, nullable=True)
    auth_code = db.Column(db.Integer, nullable=True)
    auth_at = db.Column(db.DateTime, nullable=True)
    attempt_lease_until = db.Column(db.DateTime, nullable=True)
    tls_pin_sha256 = db.Column(db.Text, nullable=True)
    device_info = db.Column(db.JSON, nullable=True)
    capabilities = db.Column(db.JSON, nullable=True)
    capabilities_at = db.Column(db.DateTime, nullable=True)
    live_profile = db.Column(db.Text, nullable=False, default='sub')
    events_enabled = db.Column(db.Boolean, nullable=False, default=False)
    event_kinds = db.Column(db.JSON, nullable=True)
    event_state = db.Column(db.Text, nullable=False, default='off')
    event_state_at = db.Column(db.DateTime, nullable=True)
    event_note = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return "<CameraDriver(camera_id='{}', vendor='{}', auth_state='{}')>".format(
            self.camera_id, self.vendor, self.auth_state)
