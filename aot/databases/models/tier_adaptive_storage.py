# coding=utf-8
"""
Tier Adaptive Storage Models — Adaptive Document Storage Architecture.

Implements:
  - TierThreshold: Configurable thresholds per tier level
  - TierDecision: Audit trail for all tier change decisions
  - DocumentAccessLog: Tracks document access for pattern analysis

Ref: TIER_DECISION_LOGIC.md (ADS_TIER_001, v1.0, 2026-04-04)
Design: Adaptive Document Storage Architecture Section 3.1
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


# =============================================================================
# Tier Threshold Configuration
# =============================================================================

class TierThreshold(CRUDMixin, db.Model):
    """
    Configurable thresholds for tier promotion/demotion decisions.

    @phase active
    @stability stable
    """
    __tablename__ = "tier_thresholds"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    tier_level = db.Column(db.Integer, nullable=False)  # 1, 2, or 3
    threshold_type = db.Column(db.String(50), nullable=False)  # 'promotion' or 'demotion'

    # Access frequency thresholds
    access_count_min = db.Column(db.Integer, default=0)
    access_count_max = db.Column(db.Integer, default=999999)
    promotion_window_hours = db.Column(db.Integer, default=168)  # 7 days
    demotion_window_hours = db.Column(db.Integer, default=720)  # 30 days

    # Size thresholds (in tokens)
    token_size_max = db.Column(db.Integer, default=2000)

    # Behavioral flags
    auto_promote = db.Column(db.Boolean, default=True)
    auto_demote = db.Column(db.Boolean, default=True)

    description = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint('tier_level', 'threshold_type', name='uq_tier_threshold_type'),
    )

    def __repr__(self):
        return f"<TierThreshold(tier={self.tier_level}, type={self.threshold_type})>"


# =============================================================================
# Tier Decision Audit Trail
# =============================================================================

class TierDecision(CRUDMixin, db.Model):
    """
    Audit trail for all tier change decisions.

    Tracks: document_id, previous_tier, new_tier, decision_score,
    reasoning, timestamp, confidence_score

    @phase active
    @stability stable
    """
    __tablename__ = "tier_decisions"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Document reference
    document_id = db.Column(db.String(36), nullable=False, index=True)
    document_type = db.Column(db.String(50), default='notes')  # 'notes', 'ai_summary', etc.

    # Tier change details
    previous_tier = db.Column(db.Integer, nullable=False)
    new_tier = db.Column(db.Integer, nullable=False)

    # Decision metadata
    decision_score = db.Column(db.Float, default=0.0)
    confidence_score = db.Column(db.Float, default=0.0)
    reasoning = db.Column(db.Text, default="")

    # Multi-topic detection result at decision time
    is_multi_topic = db.Column(db.Boolean, default=False)
    topic_tags = db.Column(db.Text, default="")  # JSON serialized list

    # Access pattern at decision time
    access_count_in_window = db.Column(db.Integer, default=0)
    days_since_last_access = db.Column(db.Integer, default=0)
    token_count = db.Column(db.Integer, default=0)

    # Audit fields
    triggered_by = db.Column(db.String(20), default='system')  # 'system', 'manual', 'scheduled'
    transition_type = db.Column(db.String(20), default='evaluated')  # 'promotion', 'demotion', 'evaluated', 'manual'
    timestamp = db.Column(db.DateTime, default=utc_now, index=True)

    def __repr__(self):
        return f"<TierDecision(doc={self.document_id[:8]}, {self.previous_tier}->{self.new_tier})>"


# =============================================================================
# Document Access Log
# =============================================================================

class DocumentAccessLog(CRUDMixin, db.Model):
    """
    Tracks individual document access events for pattern analysis.

    Used by TierDecisionEngine to calculate:
    - Access frequency
    - Access bursts
    - Future access likelihood

    @phase active
    @stability stable
    """
    __tablename__ = "document_access_log"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Document reference
    document_id = db.Column(db.String(36), nullable=False, index=True)
    document_type = db.Column(db.String(50), default='notes')

    # Access details
    access_type = db.Column(db.String(20), default='read')  # 'read', 'write', 'search'
    access_count = db.Column(db.Integer, default=1)  # Batch increment support

    # Timing
    timestamp = db.Column(db.DateTime, default=utc_now, index=True)

    def __repr__(self):
        return f"<DocumentAccessLog(doc={self.document_id[:8]}, {self.access_type})>"


# =============================================================================
# Adaptive Document Storage Settings
# =============================================================================

class AdaptiveStorageSettings(CRUDMixin, db.Model):
    """
    Global settings for adaptive document storage system.

    @phase active
    @stability stable
    """
    __tablename__ = "adaptive_storage_settings"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)

    # Feature toggles
    enabled = db.Column(db.Boolean, default=True)
    auto_promotion_enabled = db.Column(db.Boolean, default=True)
    auto_demotion_enabled = db.Column(db.Boolean, default=True)

    # Weights for scoring algorithm
    access_frequency_weight = db.Column(db.Float, default=0.4)
    freshness_weight = db.Column(db.Float, default=0.25)
    size_weight = db.Column(db.Float, default=0.2)
    topic_diversity_weight = db.Column(db.Float, default=0.15)

    # Tier thresholds (score-based)
    tier_1_threshold = db.Column(db.Float, default=0.75)
    tier_2_threshold = db.Column(db.Float, default=0.40)

    # Batch processing
    reclassification_interval_hours = db.Column(db.Integer, default=1)
    batch_size = db.Column(db.Integer, default=100)

    # Multi-topic detection
    multi_topic_paragraph_count = db.Column(db.Integer, default=3)

    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<AdaptiveStorageSettings(enabled={self.enabled})>"


# =============================================================================
# Database Seeding
# =============================================================================

def seed_tier_thresholds():
    """Seed default tier thresholds if not present."""
    defaults = [
        # Tier 1 (Hot/Summary) - high access documents
        {
            'tier_level': 1,
            'threshold_type': 'promotion',
            'access_count_min': 100,
            'access_count_max': 999999,
            'token_size_max': 2000,
            'promotion_window_hours': 168,  # 7 days
            'demotion_window_hours': 720,  # 30 days
            'auto_promote': True,
            'auto_demote': True,
            'description': 'Tier 1 promotion: high frequency access'
        },
        {
            'tier_level': 1,
            'threshold_type': 'demotion',
            'access_count_min': 0,
            'access_count_max': 99,
            'token_size_max': 2000,
            'promotion_window_hours': 168,
            'demotion_window_hours': 720,
            'auto_promote': True,
            'auto_demote': True,
            'description': 'Tier 1 demotion: low frequency or inactive'
        },
        # Tier 2 (Warm/Standard) - medium access documents
        {
            'tier_level': 2,
            'threshold_type': 'promotion',
            'access_count_min': 10,
            'access_count_max': 99,
            'token_size_max': 8000,
            'promotion_window_hours': 168,
            'demotion_window_hours': 720,
            'auto_promote': True,
            'auto_demote': True,
            'description': 'Tier 2 promotion: moderate frequency access'
        },
        {
            'tier_level': 2,
            'threshold_type': 'demotion',
            'access_count_min': 0,
            'access_count_max': 9,
            'token_size_max': 8000,
            'promotion_window_hours': 168,
            'demotion_window_hours': 720,
            'auto_promote': True,
            'auto_demote': True,
            'description': 'Tier 2 demotion: low frequency access'
        },
        # Tier 3 (Cold/Archive) - low access documents
        {
            'tier_level': 3,
            'threshold_type': 'promotion',
            'access_count_min': 10,
            'access_count_max': 99,
            'token_size_max': 999999,
            'promotion_window_hours': 168,
            'demotion_window_hours': None,  # No auto-demotion from tier 3
            'auto_promote': False,  # Manual or explicit only
            'auto_demote': False,
            'description': 'Tier 3 promotion: requires manual intervention'
        },
    ]

    for defaults_row in defaults:
        existing = TierThreshold.query.filter_by(
            tier_level=defaults_row['tier_level'],
            threshold_type=defaults_row['threshold_type']
        ).first()
        if not existing:
            tier_threshold = TierThreshold(**defaults_row)
            db.session.add(tier_threshold)
            logger.info(f"Seeded TierThreshold: tier={defaults_row['tier_level']}, type={defaults_row['threshold_type']}")

    # Seed default adaptive storage settings
    if not AdaptiveStorageSettings.query.first():
        settings = AdaptiveStorageSettings()
        db.session.add(settings)
        logger.info("Seeded AdaptiveStorageSettings")


def seed_tier_thresholds_if_empty():
    """Public wrapper for seeding function."""
    seed_tier_thresholds()
