# coding=utf-8
"""
AIContextSource — External data source for AI knowledge injection.
Represents a configured external source that is periodically synced to AIContextRecord.

Source types:
- rest_api: Fetch from external REST API endpoint
- document: Parse uploaded PDF/text/markdown file
- web_url: Scrape web page content
- internal_query: Execute parameterized DB query
- google_drive: Parse a file picked from the operator's Google Drive (PDF/text/
  markdown, or a Google Doc/Sheet exported to text/CSV) — reuses the OAuth
  connection already established for Calendar sync (UserCalendarConnection),
  not a separate credential. See aot/utils/google_drive_api.py.
"""
import enum
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class SourceType(str, enum.Enum):
    REST_API = "rest_api"
    DOCUMENT = "document"
    WEB_URL = "web_url"
    INTERNAL_QUERY = "internal_query"
    GOOGLE_DRIVE = "google_drive"


# @ANCHOR: AI_CONTEXT_SOURCE_MODEL
class AIContextSource(CRUDMixin, db.Model):
    """
    Represents an external data source configured to inject knowledge into AIContextRecord.
    Each source is tied to a facility and maps to a parameter_name in the context pipeline.

    @phase active
    @stability stable
    """
    __tablename__ = "ai_context_source"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Facility binding
    facility_id = db.Column(db.String(36), nullable=False, index=True)

    # Source identity
    source_name = db.Column(db.String(100), nullable=False)
    source_type = db.Column(db.String(30), nullable=False, default=SourceType.REST_API)

    # Context pipeline target
    parameter_name = db.Column(db.String(100), nullable=False)

    # Source-specific configuration as JSON
    config_json = db.Column(db.Text, default='{}')

    # Sync schedule (minutes, 0 = manual only)
    sync_interval_min = db.Column(db.Integer, default=60)

    # Sync state tracking
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(db.String(20), nullable=True)  # 'ok', 'error', None

    # Lifecycle
    is_active = db.Column(db.Boolean, default=True)
    # user-toggle: activate / deactivate. Defaults False — a newly created
    # source has no config yet, so it must not sync until the user configures
    # and explicitly activates it via the /activate route.
    is_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<AIContextSource(name={self.source_name}, "
            f"type={self.source_type}, param={self.parameter_name})>"
        )
