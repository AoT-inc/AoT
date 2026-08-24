# coding=utf-8
"""
AIKnowledgeChunk — unified knowledge item (AI library redesign, P1).

Where AIContextRecord holds flat parameter/value pairs, this table holds
document-shaped knowledge: prose digests (PDF/text/web sources, external
guides) and, going forward, AI-curated notes written via the knowledge_shelve
verb. A row's `provenance` records WHERE it came from and `context_state`
records HOW MUCH it's trusted — these are independent axes, not one pipeline
(an external_authority row starts and stays trusted; an ai_curated row starts
low-trust and may be promoted or retired). See
docs/design/ai-library-redesign.md §2-3.

Scoping is domain-agnostic: `tags` (free text — crop, livestock, road,
railway, whatever the operator is actually managing) and `entity_ref` (an
optional AoT GIS entity unique_id) replace the old facility_id axis, which
could not represent farms/sites with no matching facility row.
"""
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


# @ANCHOR: AI_KNOWLEDGE_CHUNK_MODEL
class AIKnowledgeChunk(CRUDMixin, db.Model):
    """
    One knowledge item — a digested chunk of a registered source (document/
    web_url/ext_* today; ai_curated shelve() writes going forward).

    context_state values (trust pipeline, independent of provenance):
        system_generated  — default on write; unreviewed.
        user_confirmed    — a person reviewed and confirmed it (or edited it —
                             §3.2 groups confirm/edit as one branch), OR set
                             directly by knowledge_shelve_service for the
                             AI-curated source of truth stamped by a human.
        corroborated       — auto-promoted after surviving repeated retrieval
                             without dispute (see knowledge_promotion_service.
                             note_reuse) — the only FULLY AUTOMATIC transition;
                             everything else here is human-driven (P5 scope
                             decision: matching headings with an authoritative
                             source, or a P4 contradiction flag, are only
                             ADVISORY signals shown to a reviewer, not
                             auto-promotion/auto-retirement triggers — neither
                             can be verified as actually agreeing/conflicting
                             without semantic judgment this module doesn't do).
        retired            — a human retired it (possibly prompted by a P4
                             flagged_reason); excluded from search, row kept.
    See knowledge_promotion_service.py (P5) for the transition functions.

    @phase active
    @stability new
    """
    __tablename__ = "ai_knowledge_chunk"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    source_id = db.Column(db.String(36), db.ForeignKey('ai_context_source.source_id', ondelete='CASCADE'),
                           nullable=False, index=True)
    # Denormalized at write time so search/display never needs to join back to
    # ai_context_source on every query.
    source_name = db.Column(db.String(100), nullable=True)
    # Legacy multi-site axis — superseded by tags/entity_ref (see module
    # docstring). Left in place (unused by knowledge_search) rather than
    # dropped, to avoid a destructive migration before anything reads it.
    facility_id = db.Column(db.String(36), nullable=True, index=True)

    section_title = db.Column(db.String(255), nullable=True)
    digest_text = db.Column(db.Text, nullable=False)
    keywords = db.Column(db.Text, nullable=True)  # comma-separated, incl. domain aliases
    raw_excerpt = db.Column(db.Text, nullable=True)  # source text this chunk was digested from (audit only)

    # --- Unified item model additions (P1, docs/design/ai-library-redesign.md §2) ---
    # Origin category — drives default trust weight at injection time.
    # 'external_authority' | 'user_provided' | 'data_derived' | 'ai_curated'.
    provenance = db.Column(db.String(20), nullable=False, default='user_provided')
    # Free-text scope tags, comma-separated (e.g. 'tomato,flowering' or
    # 'railway,bridge-a') — domain-agnostic stand-in for what used to be a
    # hardcoded facility_id filter. Empty/NULL = unscoped (always a candidate,
    # same as the always-global markdown manual).
    tags = db.Column(db.Text, nullable=True)
    # Optional link to an AoT GIS entity (site/zone/device/facility unique_id).
    # Logical FK only — the target table varies by what the knowledge is about.
    entity_ref = db.Column(db.String(36), nullable=True, index=True)
    # Human-readable citation for the injected block ("RDA SmartFarm API",
    # "대화 2026-07-18", "텔레메트리 분석") — always shown so the AI can
    # distinguish authority from its own unconfirmed notes when citing.
    attribution = db.Column(db.Text, nullable=True)
    # C4: 원문 주소. `attribution` 이 사람이 읽는 표기("농사로 무 재배 정보")
    # 라면 이쪽은 **되짚어 갈 수 있는 주소**다. 둘을 나눈 이유는 화면이 링크를
    # 걸려면 "여기에 주소가 있다" 가 스키마여야 하기 때문 — 자유 텍스트에서
    # URL 을 긁어내는 방식은 쓰는 쪽의 표기 습관에 기댄다.
    #
    # 이 값이 있다고 신뢰가 오르지는 않는다. 쓰는 쪽의 자기 신고를 믿으면
    # §3.3 오염 방지가 무너진다 — 진입은 여전히 ai_curated/미확인이고, 이
    # 컬럼은 **사람이 확인할 수 있게** 할 뿐이다(§3.2 승격 경로의 전제).
    source_url = db.Column(db.String(500), nullable=True)
    # 'prose' (digest text, searched by keyword) | 'structured' (a
    # regular-shaped fact meant to be read as data, not prose — not yet
    # produced by any writer in P1; reserved for P3's structured adapter).
    content_kind = db.Column(db.String(16), nullable=False, default='prose')
    # Optional expiry (e.g. a pest alert) — expired rows are excluded from
    # search regardless of context_state. NULL = never expires.
    ttl = db.Column(db.DateTime, nullable=True)
    # P4 (knowledge_shelve_service): a bounded, deterministic contradiction
    # signal set at write time — a same-tag, same-heading, different-content
    # peer-trust item already existed. NOT a block, NOT a state (still
    # searchable) — surfaced for the P5 review UI. NULL = no collision found.
    flagged_reason = db.Column(db.Text, nullable=True)
    # P5 (knowledge_promotion_service.note_reuse): times this item was
    # surfaced by knowledge_search while still system_generated. Incremented
    # via raw SQL (deliberately bypassing the ORM so it does NOT touch
    # updated_at / bust knowledge_search's process-level cache on every
    # search hit) — only the actual promotion write goes through the ORM.
    reuse_count = db.Column(db.Integer, nullable=False, default=0)

    locale = db.Column(db.String(8), default='ko')
    chunk_index = db.Column(db.Integer, default=0)
    content_hash = db.Column(db.String(64), nullable=False, index=True)  # sha256 of raw_excerpt

    context_state = db.Column(db.String(20), default='system_generated')
    is_enabled = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return (
            f"<AIKnowledgeChunk(id={self.id}, source={self.source_name}, "
            f"section={self.section_title}, provenance={self.provenance}, "
            f"state={self.context_state})>"
        )
