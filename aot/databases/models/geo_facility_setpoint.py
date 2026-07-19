# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class GeoFacilitySetpoint(CRUDMixin, db.Model):
    """
    Operator-defined setpoints for a facility (one row per facility).

    Mirrors env_coordinator Function settings so the IEC widget can read
    and write them. Column names correspond 1:1 to env_coordinator custom_options.

    Primary control target:
      target_vpd_kpa  → target_vpd       VPD target the function tracks

    VPD decomposition guidance ranges (VPD is decomposed to T/RH within these):
      guide_t_min_c / guide_t_max_c      → guide_T_min / guide_T_max
      guide_rh_min_pct / guide_rh_max_pct → guide_RH_min / guide_RH_max

    Hard safety constraints (force heating/cooling regardless of VPD target):
      temp_min_c / temp_max_c            → temp_min / temp_max
      humid_min_pct / humid_max_pct      → humid_min / humid_max

    Secondary:
      target_co2_ppm                     → target_co2

    source records who last wrote the row: 'manual' (widget), 'ai', 'auto'.

    @phase active
    """
    __tablename__ = 'geo_facility_setpoint'
    __table_args__ = {'extend_existing': True}

    id            = db.Column(db.Integer, primary_key=True)
    unique_id     = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    facility_uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)

    # VPD — primary control target
    target_vpd_kpa   = db.Column(db.Float, nullable=True)

    # VPD decomposition guidance ranges
    guide_t_min_c    = db.Column(db.Float, nullable=True)
    guide_t_max_c    = db.Column(db.Float, nullable=True)
    guide_rh_min_pct = db.Column(db.Float, nullable=True)
    guide_rh_max_pct = db.Column(db.Float, nullable=True)

    # Hard safety constraints
    temp_min_c    = db.Column(db.Float, nullable=True)
    temp_max_c    = db.Column(db.Float, nullable=True)
    humid_min_pct = db.Column(db.Float, nullable=True)
    humid_max_pct = db.Column(db.Float, nullable=True)

    # CO2 — secondary target
    target_co2_ppm = db.Column(db.Float, nullable=True)

    # Metadata
    source     = db.Column(db.String(16), nullable=False, default='manual')
    operator   = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'facility_uuid':    self.facility_uuid,
            'target_vpd_kpa':   self.target_vpd_kpa,
            'guide_t_min_c':    self.guide_t_min_c,
            'guide_t_max_c':    self.guide_t_max_c,
            'guide_rh_min_pct': self.guide_rh_min_pct,
            'guide_rh_max_pct': self.guide_rh_max_pct,
            'temp_min_c':       self.temp_min_c,
            'temp_max_c':       self.temp_max_c,
            'humid_min_pct':    self.humid_min_pct,
            'humid_max_pct':    self.humid_max_pct,
            'target_co2_ppm':   self.target_co2_ppm,
            'source':           self.source,
            'updated_at':       self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return (f'<GeoFacilitySetpoint facility={self.facility_uuid} '
                f'vpd={self.target_vpd_kpa}>')
