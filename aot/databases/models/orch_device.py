# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class OrchDevice(CRUDMixin, db.Model):
    """
    Represents a device capable of executing tasks (e.g., Raspberry Pi, HQ Server).

    @phase active
    @stability stable
    """
    __tablename__ = "orch_device"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    name = db.Column(db.String(255), nullable=False)
    device_type = db.Column(db.String(50), default='raspberry_pi')  # raspberry_pi, headquarters
    
    # Capabilities (JSON-encoded list of task_types this device can handle)
    capabilities = db.Column(db.Text, default='[]')
    
    status = db.Column(db.String(20), default='offline')  # online, offline, busy, maintenance
    last_seen = db.Column(db.DateTime, nullable=True)
    
    ip_address = db.Column(db.String(45), nullable=True)
    metadata_json = db.Column(db.Text, default='{}')
    
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<OrchDevice(name={self.name}, type={self.device_type}, status={self.status})>"
