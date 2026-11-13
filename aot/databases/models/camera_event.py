# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases.sqla import db


class CameraEvent(CRUDMixin, db.Model):
    """카메라 감지 이벤트 기록. 설계 §5.3. 판정 시각은 received_at_utc(서버 시각).

    P2 는 표만 만든다. 기록·디스패치는 P4.

    @phase active
    """
    __tablename__ = "camera_event"
    __table_args__ = (db.Index('ix_camera_event_camera_received', 'camera_id', 'received_at_utc'),
                      {'extend_existing': True})

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    camera_id = db.Column(db.String(36), db.ForeignKey('camera.unique_id', ondelete='CASCADE'),
                          nullable=False, index=True)
    kind = db.Column(db.Text, nullable=False)
    enhanced = db.Column(db.Text, nullable=True)
    raw_type = db.Column(db.Text, nullable=True)
    camera_time_utc = db.Column(db.DateTime, nullable=True)
    received_at_utc = db.Column(db.DateTime, nullable=False)
    dispatch_state = db.Column(db.Text, nullable=False, default='none')
    dispatch_note = db.Column(db.Text, nullable=True)
