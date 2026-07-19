# coding=utf-8
"""
EKG (Experience Knowledge Graph) — data models.

Phase 5 / 005_EDGE_OPTIMIZED_SPECIFICATION.yaml
Tables: ekg_human_notes, ekg_daemon_events, ekg_pattern_clusters, ekg_edges

Design: Standalone — NOT dependent on AIUserSemanticMemory.
Ref: 010_IMPLEMENTATION_PLAN.yaml Phase A / A-3
"""
import enum

from sqlalchemy import JSON
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db
from aot.utils.time_utils import utc_now


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class EdgeType(enum.Enum):
    """Edge type vocabulary for EKG graph relationships."""
    PRECEDES   = 'PRECEDES'    # Note occurred before DaemonEvent (temporal)
    CORRELATES = 'CORRELATES'  # Pearson r >= threshold (statistical)
    ANNOTATES  = 'ANNOTATES'   # HumanNote describes a DaemonEvent
    CLUSTERS   = 'CLUSTERS'    # Node belongs to a PatternCluster
    # NOTE: Treat as append-only — altering ENUM values on MariaDB is costly.


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class HumanNote(CRUDMixin, db.Model):
    """
    Represents a human-authored note ingested into the EKG.
    Linked to the originating Notes row via source_notes_id FK.

    @phase active
    @stability stable
    @dependency Notes
    """
    __tablename__ = 'ekg_human_notes'
    __table_args__ = {'extend_existing': True}

    id          = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id   = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    content     = db.Column(
        db.Text().with_variant(LONGTEXT, 'mysql', 'mariadb'),
        nullable=False,
        default=''
    )
    created_at    = db.Column(db.DateTime, nullable=False, default=utc_now)
    tags          = db.Column(JSON, default=list)           # list[str]
    author_locale = db.Column(db.String(10), default='en')
    source_notes_id = db.Column(
        db.String(36),
        db.ForeignKey('notes.unique_id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    source_note = db.relationship(
        'Notes',
        foreign_keys=[source_notes_id],
        lazy='select',
    )

    @classmethod
    def from_notes_row(cls, note):
        """
        Factory used by the EKG feedback wire (ai_scheduler_service) and
        the Notes post-commit signal listener (EKGService.register_signal_listener).
        """
        return cls(
            content=note.note or note.name or '',
            tags=[note.category] if note.category else [],
            author_locale='en',
            source_notes_id=note.unique_id,
        )

    def __repr__(self):
        return f"<HumanNote(id={self.id}, src={self.source_notes_id})>"


class DaemonEvent(CRUDMixin, db.Model):
    """
    Represents a physical device event captured by the Daemon.

    @phase active
    @stability stable
    """
    __tablename__ = 'ekg_daemon_events'
    __table_args__ = (
        db.Index('idx_ekg_de_timestamp',     'timestamp'),
        db.Index('idx_ekg_de_device_metric', 'device_id', 'metric'),
        {'extend_existing': True},
    )

    id        = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    device_id = db.Column(db.String(64),  nullable=False)
    metric    = db.Column(db.String(64),  nullable=False)
    value     = db.Column(db.Float,       nullable=False)
    timestamp = db.Column(db.DateTime,    nullable=False, default=utc_now)
    spatial_ref = db.Column(db.String(128), nullable=True)

    def __repr__(self):
        return f"<DaemonEvent(device={self.device_id}, metric={self.metric})>"


class PatternCluster(CRUDMixin, db.Model):
    """
    Groups correlated HumanNotes and DaemonEvents.
    Promoted to a DraftAction when correlation_score >= threshold.
    decay_score decreases by DECAY_RATE_PER_DAY each day — stale clusters
    eventually cease to generate draft actions.

    @phase active
    @stability stable
    """
    __tablename__ = 'ekg_pattern_clusters'
    __table_args__ = (
        db.Index('idx_ekg_pc_decay', 'decay_score'),
        {'extend_existing': True},
    )

    id                 = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id          = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    note_ids           = db.Column(JSON, default=list)    # list[str] HumanNote.unique_id
    event_ids          = db.Column(JSON, default=list)    # list[str] DaemonEvent.unique_id
    correlation_score  = db.Column(db.Float, nullable=False)
    predictive_trigger = db.Column(JSON, default=dict)    # structured action hint
    created_at         = db.Column(db.DateTime, nullable=False, default=utc_now)
    last_seen_at       = db.Column(db.DateTime, nullable=False, default=utc_now)
    decay_score        = db.Column(db.Float, nullable=False, default=1.0)

    def __repr__(self):
        return f"<PatternCluster(id={self.id}, score={self.correlation_score:.2f})>"


class EdgeRecord(CRUDMixin, db.Model):
    """
    Directed weighted edge in the EKG graph.

    @phase active
    @stability stable
    """
    __tablename__ = 'ekg_edges'
    __table_args__ = (
        db.Index('idx_ekg_edge_type',         'edge_type'),
        db.Index('idx_ekg_edge_source_target', 'source_id', 'target_id'),
        {'extend_existing': True},
    )

    id        = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    edge_type = db.Column(
        SAEnum(EdgeType, name='edgetype',
               values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    source_id  = db.Column(db.String(64), nullable=False)
    target_id  = db.Column(db.String(64), nullable=False)
    weight     = db.Column(db.Float, nullable=False, default=1.0)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def __repr__(self):
        return f"<EdgeRecord(type={self.edge_type.value}, src={self.source_id})>"
