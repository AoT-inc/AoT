# coding=utf-8
"""
ExtSmartfarmSetpoints — SQLite cache model for EXT-KR-01 data.

013_DATA_SOURCES.yaml:
    table  : ext_smartfarm_setpoints
    source : EXT-KR-01 (RDA SmartFarm Productivity Model)
    keys   : [crop_type, growth_stage]
    ttl    : 7 days (TTL column: fetched_at)
"""
from datetime import datetime, timezone

from aot.aot_flask.extensions import db


# ---------------------------------------------------------------------------
# @ANCHOR: EXT_SMARTFARM_SETPOINTS_MODEL
# ---------------------------------------------------------------------------

class ExtSmartfarmSetpoints(db.Model):
    """
    SQLite cache for RDA SmartFarm optimal environment setpoints.

    Stores crop-type and growth-stage keyed optimal ranges for temperature, humidity,
    CO2, and light. Refreshed on a 7-day TTL driven by the fetched_at column.
    Ref: EXT-KR-01 (013_DATA_SOURCES.yaml).

    @phase active
    """
    __tablename__ = "ext_smartfarm_setpoints"

    __table_args__ = (
        db.UniqueConstraint('crop_type', 'growth_stage', name='uq_ext_sf_crop_stage'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # --- Key columns (013_DATA_SOURCES.yaml storage.tables[0].key_columns) ---
    crop_type    = db.Column(db.String(64), nullable=False, index=True)
    growth_stage = db.Column(db.String(64), nullable=False, index=True)

    # --- Optimal environment ranges (NRM-01: Celsius / percent / ppm / lux) ---
    opt_temp_min     = db.Column(db.Float, nullable=True)   # optTmpMin
    opt_temp_max     = db.Column(db.Float, nullable=True)   # optTmpMax
    opt_humidity_min = db.Column(db.Float, nullable=True)   # optHmtMin
    opt_humidity_max = db.Column(db.Float, nullable=True)   # optHmtMax
    opt_co2_min      = db.Column(db.Float, nullable=True)   # optCo2Min
    opt_co2_max      = db.Column(db.Float, nullable=True)   # optCo2Max
    opt_light_min    = db.Column(db.Float, nullable=True)   # optIlmnMin (lux)
    opt_light_max    = db.Column(db.Float, nullable=True)   # optIlmnMax (lux)

    # --- TTL column (013_DATA_SOURCES.yaml: ttl_column = fetched_at) ---
    fetched_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<ExtSmartfarmSetpoints(crop={self.crop_type!r}, "
            f"stage={self.growth_stage!r}, "
            f"temp=[{self.opt_temp_min}, {self.opt_temp_max}])>"
        )
