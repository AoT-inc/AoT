# coding=utf-8
"""
ExtPestAlerts — SQLite cache model for EXT-KR-03 data.

013_DATA_SOURCES.yaml:
    table  : ext_pest_alerts
    source : EXT-KR-03 (National Pest Management System — 국가병해충관리시스템)
    keys   : [crop_type, pest_code]
    ttl    : 6 hours (TTL column: fetched_at)
"""
from datetime import datetime, timezone
from aot.aot_flask.extensions import db


# ---------------------------------------------------------------------------
# @ANCHOR: EXT_PEST_ALERTS_MODEL
# ---------------------------------------------------------------------------

class ExtPestAlerts(db.Model):
    """
    SQLite cache for National Pest Management System alert data.

    Stores crop-type and pest-code keyed pest alert records including severity,
    region, and recommended control methods. Refreshed on a 6-hour TTL driven by
    the fetched_at column. Ref: EXT-KR-03 (013_DATA_SOURCES.yaml).

    @phase active
    """
    __tablename__ = "ext_pest_alerts"
    __table_args__ = (
        db.UniqueConstraint('crop_type', 'pest_code', name='uq_ext_pa_crop_pest'),
        {'extend_existing': True},
    )
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    crop_type  = db.Column(db.String(64),  nullable=False, index=True)
    pest_code  = db.Column(db.String(64),  nullable=False, index=True)
    pest_name  = db.Column(db.String(128), nullable=True)
    severity   = db.Column(db.String(32),  nullable=True)   # 'low' | 'medium' | 'high' | 'critical'
    region     = db.Column(db.String(128), nullable=True)
    control_method = db.Column(db.Text,   nullable=True)
    fetched_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<ExtPestAlerts(crop={self.crop_type!r}, "
            f"pest={self.pest_code!r}, severity={self.severity!r})>"
        )
