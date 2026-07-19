# coding=utf-8
"""
ExtNongsaroGuides — SQLite cache model for EXT-KR-02 data.

013_DATA_SOURCES.yaml:
    table  : ext_nongsaro_guides
    source : EXT-KR-02 (Nongsaro Open API — 농사로)
    keys   : [crop_type, guide_type]
    ttl    : 1 day (TTL column: fetched_at)
"""
from datetime import datetime, timezone

from aot.aot_flask.extensions import db


# ---------------------------------------------------------------------------
# @ANCHOR: EXT_NONGSARO_GUIDES_MODEL
# ---------------------------------------------------------------------------

class ExtNongsaroGuides(db.Model):
    """
    SQLite cache for Nongsaro cultivation and weekly guide articles.

    Stores crop-type and guide-type keyed agricultural content including title,
    body text, and season. Refreshed on a 1-day TTL driven by the fetched_at column.
    Ref: EXT-KR-02 (013_DATA_SOURCES.yaml).

    @phase active
    """
    __tablename__ = "ext_nongsaro_guides"

    __table_args__ = (
        db.UniqueConstraint('crop_type', 'guide_type', name='uq_ext_ng_crop_type'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # --- Key columns (013_DATA_SOURCES.yaml: keys = [crop_type, guide_type]) ---
    crop_type  = db.Column(db.String(64),  nullable=False, index=True)
    guide_type = db.Column(db.String(32),  nullable=False, index=True)  # 'cultivation' | 'weekly'

    # --- Guide content columns ---
    title      = db.Column(db.String(256), nullable=True)
    content    = db.Column(db.Text,        nullable=True)
    season     = db.Column(db.String(32),  nullable=True)

    # --- TTL column (013_DATA_SOURCES.yaml: ttl_column = fetched_at) ---
    fetched_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<ExtNongsaroGuides(crop={self.crop_type!r}, type={self.guide_type!r})>"
