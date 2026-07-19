# coding=utf-8
"""
AILibrarySyncLog — Audit trail for AIContextSource sync operations.

Records one row per sync attempt (success or error) for each AIContextSource.
Stores a snapshot of the raw fetched payload before processing, enabling
debugging of sync failures without re-triggering the sync.

Retention: _prune_sync_log() keeps the most recent 20 rows per source_id.
"""
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


# @ANCHOR: AI_LIBRARY_SYNC_LOG_MODEL
class AILibrarySyncLog(CRUDMixin, db.Model):
    """
    Stores one audit row per sync attempt for each AIContextSource.
    raw_payload captures the raw fetched content before processing (truncated at 10000 chars).
    sync_status is 'ok' on success or 'error' on failure.

    @phase active
    @stability stable
    @dependency AIContextSource
    """
    __tablename__ = 'ai_library_sync_log'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    log_id = db.Column(db.String(36), nullable=False, unique=True)

    # Source reference (logical FK to AIContextSource.source_id)
    source_id = db.Column(db.String(36), nullable=False, index=True)
    facility_id = db.Column(db.String(36), nullable=False, index=True)

    # Timestamps
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Snapshots at sync time
    source_type = db.Column(db.String(30), nullable=True)
    preset_key = db.Column(db.String(50), nullable=True)

    # Raw payload before processing (truncated at 10000 chars)
    raw_payload = db.Column(db.Text, nullable=True)

    # Outcome
    records_written = db.Column(db.Integer, default=0)
    sync_status = db.Column(db.String(20), default='ok')
    error_message = db.Column(db.Text, nullable=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.log_id:
            self.log_id = set_uuid()

    def __repr__(self):
        return (
            f"<AILibrarySyncLog(log_id={self.log_id}, source_id={self.source_id}, "
            f"status={self.sync_status}, synced_at={self.synced_at})>"
        )
