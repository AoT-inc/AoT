# coding=utf-8
"""
Cold Storage Models for Tier 3 (Cold/Archive) Document Storage.

Implements the archive storage layer for the Adaptive Document Storage system.
Documents are compressed and stored in year/month directory structure.
"""
from datetime import datetime

from aot.utils.time_utils import utc_now

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class ColdDocuments(CRUDMixin, db.Model):
    """
    Stores archived documents in compressed format.

    Archives are organized in year/month directory structure for efficient
    storage management and retention policy enforcement.
    """
    __tablename__ = "cold_documents"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Document reference
    document_id = db.Column(db.String(36), nullable=False, index=True)

    # Content verification
    content_hash = db.Column(db.String(64), nullable=False)  # SHA-256 hash

    # Archive storage path (year/month structure)
    archive_path = db.Column(db.Text, nullable=False)

    # Metadata stored as JSON
    # 컬럼명이 `metadata` 가 아닌 이유: SQLAlchemy Declarative 가 `metadata` 를
    # 예약해 두어(모든 모델의 MetaData 핸들), 그 이름으로 컬럼을 선언하면
    # 클래스 정의 시점에 InvalidRequestError 로 **import 자체가 실패**한다.
    # 이 파일이 models/__init__.py 에 등록돼 있지 않은 덕에 앱은 멀쩡히 떴고,
    # 그래서 한 번도 드러나지 않았다(2026-08-04 발견).
    meta_json = db.Column(db.Text, default=None)  # JSON string

    # Timestamps
    archived_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_accessed = db.Column(db.DateTime, default=utc_now, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Compression info
    compression_type = db.Column(db.String(16), default='gzip')  # gzip or brotli
    original_size = db.Column(db.Integer, default=0)
    compressed_size = db.Column(db.Integer, default=0)

    # Status
    is_restored = db.Column(db.Boolean, default=False)
    restore_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return "<{cls}(id={s.id}, document_id={s.document_id})>".format(
            s=self, cls=self.__class__.__name__
        )

    @property
    def compression_ratio(self) -> float:
        """Calculate compression ratio as percentage."""
        if self.original_size == 0:
            return 0.0
        return round((1 - self.compressed_size / self.original_size) * 100, 2)


class ArchiveIndex(CRUDMixin, db.Model):
    """
    Index for archive lifecycle management and retention policies.

    Tracks retention policies and deletion schedules for archived documents.
    """
    __tablename__ = "archive_index"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Document reference
    document_id = db.Column(db.String(36), nullable=False, index=True)

    # Archive dates
    archive_date = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)
    deletion_date = db.Column(db.DateTime, nullable=True, index=True)

    # Retention policy
    retention_policy = db.Column(db.String(32), default='default')  # default, 1year, 3year, 7year, permanent
    retention_days = db.Column(db.Integer, default=1095)  # 3 years default

    # Status
    status = db.Column(db.String(16), default='active')  # active, pending_deletion, deleted
    is_purgeable = db.Column(db.Boolean, default=False)

    # Audit
    archived_by = db.Column(db.String(64), default='system')  # system, user, scheduled
    deletion_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self):
        return "<{cls}(id={s.id}, document_id={s.document_id}, status={s.status})>".format(
            s=self, cls=self.__class__.__name__
        )

    def calculate_deletion_date(self) -> datetime:
        """Calculate deletion date based on retention policy."""
        if self.deletion_date:
            return self.deletion_date
        from datetime import timedelta
        return self.archive_date + timedelta(days=self.retention_days)


class ArchiveAuditLog(CRUDMixin, db.Model):
    """
    Audit log for archive operations.

    Tracks all archive, restore, and deletion operations for compliance.
    """
    __tablename__ = "archive_audit_log"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Operation details
    operation = db.Column(db.String(32), nullable=False)  # archive, restore, delete, purge
    document_id = db.Column(db.String(36), nullable=False, index=True)

    # Timestamps
    timestamp = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)

    # Operation metadata
    performed_by = db.Column(db.String(64), default='system')
    compression_type = db.Column(db.String(16), nullable=True)
    original_size = db.Column(db.Integer, nullable=True)
    compressed_size = db.Column(db.Integer, nullable=True)

    # Result
    status = db.Column(db.String(16), default='success')  # success, failed, partial
    error_message = db.Column(db.Text, nullable=True)

    # Additional context (컬럼명 사유는 ColdDocuments.meta_json 주석 참조)
    meta_json = db.Column(db.Text, nullable=True)  # JSON string for extra info

    def __repr__(self):
        return "<{cls}(id={s.id}, operation={s.operation}, document_id={s.document_id})>".format(
            s=self, cls=self.__class__.__name__
        )


# Retention policy constants
RETENTION_POLICIES = {
    'default': 1095,    # 3 years
    '1year': 365,
    '3year': 1095,
    '7year': 2555,
    'permanent': -1,    # Never delete
}

# Compression type constants
COMPRESSION_TYPES = ['gzip', 'brotli']
DEFAULT_COMPRESSION = 'gzip'