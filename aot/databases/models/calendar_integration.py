# coding=utf-8
"""
Per-user external calendar integration (Google Calendar, two-way sync).

Two tables:
  - UserCalendarConnection: one row per (user, provider) — the OAuth link and
    its sync state. refresh/access tokens are stored ENCRYPTED (aot.utils.crypto)
    — the only encrypted-at-rest credentials in the project, because they grant
    standing access to a user's personal Google account.
  - CalendarEventLink: maps an AoT SchedulerJobMeta row to the Google event it
    corresponds to, per connection (the same job pushed to two operators'
    calendars is two links). Enables idempotent upsert on push and dedup on pull.

Design notes live in .local/plans/google-calendar-sync.md.
"""
import logging
from datetime import datetime

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db

logger = logging.getLogger("aot.calendar_integration")


class UserCalendarConnection(CRUDMixin, db.Model):
    """One operator's OAuth link to an external calendar provider + sync state."""
    __tablename__ = "user_calendar_connection"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Owner (users.id — the natural PK; see aot/databases/models/user.py).
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    provider = db.Column(db.String(32), nullable=False, default='google')
    account_email = db.Column(db.String(255), nullable=True)   # connected account, for display

    # OAuth tokens — ENCRYPTED via aot.utils.crypto (never plaintext).
    refresh_token_enc = db.Column(db.Text, nullable=True)
    access_token_enc = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)       # UTC-naive, when access_token expires
    scope = db.Column(db.Text, nullable=True)

    # Legacy single-calendar fields (kept for back-compat; multi-calendar mode
    # below supersedes them). 'primary' or a single dedicated calendar id.
    google_calendar_id = db.Column(db.String(255), nullable=True, default='primary')
    sync_token = db.Column(db.Text, nullable=True)

    # Multi-calendar routing by AoT event category (user's design: AI / User /
    # Device get separate Google calendars). Shape:
    #   {'ai':   {'calendar_id': '...', 'sync_token': '...'},
    #    'user': {'calendar_id': '...', 'sync_token': '...'},
    #    'device':{'calendar_id': '...', 'sync_token': '...'}}
    # Created on first sync (ensure_category_calendars). Each calendar carries
    # its own incremental sync cursor (syncToken is per-calendar in Google).
    category_calendars = db.Column(db.JSON, nullable=True)

    # Direction toggles (both default on = two-way per user's decision).
    push_enabled = db.Column(db.Boolean, default=True)   # AoT → Google
    pull_enabled = db.Column(db.Boolean, default=True)   # Google → AoT

    sync_interval_min = db.Column(db.Integer, default=15)

    is_active = db.Column(db.Boolean, default=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_sync_status = db.Column(db.String(16), nullable=True)   # 'ok' | 'error'
    last_sync_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- token accessors (encrypt/decrypt at the boundary) --------------------
    def set_refresh_token(self, value):
        from aot.utils.crypto import encrypt_secret
        self.refresh_token_enc = encrypt_secret(value)

    def get_refresh_token(self):
        from aot.utils.crypto import decrypt_secret
        return decrypt_secret(self.refresh_token_enc)

    def set_access_token(self, value):
        from aot.utils.crypto import encrypt_secret
        self.access_token_enc = encrypt_secret(value)

    def get_access_token(self):
        from aot.utils.crypto import decrypt_secret
        return decrypt_secret(self.access_token_enc)

    def __repr__(self):
        return "<UserCalendarConnection(id={s.id}, user_id={s.user_id}, provider={s.provider})>".format(s=self)


class CalendarEventLink(CRUDMixin, db.Model):
    """Maps a SchedulerJobMeta row ↔ a remote calendar event, per connection."""
    __tablename__ = "calendar_event_link"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    connection_id = db.Column(db.Integer, db.ForeignKey('user_calendar_connection.id'),
                              nullable=False, index=True)

    # AoT side (SchedulerJobMeta.id) and remote side (Google event id +
    # which calendar it lives in — needed for update/delete under multi-calendar).
    job_id = db.Column(db.Integer, nullable=False, index=True)
    google_event_id = db.Column(db.String(255), nullable=False, index=True)
    google_calendar_id = db.Column(db.String(255), nullable=True)
    google_etag = db.Column(db.String(255), nullable=True)

    # Which side created this link first — 'aot' (pushed out) or 'google'
    # (pulled in as a SchedulerJobMeta with source_type='google_calendar').
    origin = db.Column(db.String(8), nullable=False, default='aot')

    last_synced_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return "<CalendarEventLink(id={s.id}, job_id={s.job_id}, google_event_id={s.google_event_id})>".format(s=self)
