# coding=utf-8
"""
Tier Adaptive Storage Models — Adaptive Document Storage Architecture.

Implements:
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
