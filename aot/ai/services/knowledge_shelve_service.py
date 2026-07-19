# coding=utf-8
"""
knowledge_shelve_service.py — the 'shelve' write verb (P4).

AI-initiated knowledge write: the counterpart to knowledge_search's read verb
(docs/design/ai-library-redesign.md §4). Every row this writes is
provenance='ai_curated', context_state='system_generated' — the lowest trust
tier — regardless of how confident the caller sounds. Promotion to a higher
trust state is the (not yet built) P5 transition pipeline's job (§3.2); this
module never grants trust at write time. §3's core rule — "an ai_curated
item must never override an authoritative one" — is enforced at citation
time instead (ai_agent_service._MANUAL_GROUNDING_DIRECTIVE tells the model to
prefer a [권위]/[Library] entry over an [AI 정리 — 미확인] one covering the
same point), not by blocking the write here.

Governance implemented here (§3.3, P4 scope — dedup/quota/flagging only;
promotion/retirement transitions and the review UI are P5):
  - dedup: identical content (by hash, across ANY source) is a no-op.
  - quota: a rolling 24h cap on ai_curated writes bounds a runaway
    self-reinforcement loop (the AI shelving the same kind of note forever).
  - contradiction flagging: a new item whose heading collides with an
    existing PEER-trust item's heading (same tags, different content) is
    flagged via `flagged_reason` for the future review surface — not
    blocked, not auto-retired. Peer trust = {ai_curated, data_derived}; a
    collision with an external_authority/user_provided item isn't flagged
    here because citation-time preference already handles that case.

AIKnowledgeChunk.source_id is a NOT NULL FK to ai_context_source — a shelve()
write has no registered external source, so all of them are attributed to
one reserved, never-synced AIContextSource row (see
_get_or_create_ai_curated_source) rather than loosening the FK. This keeps
every existing consumer that assumes a non-null source_id working unchanged,
and gives the AI's shelved notes a normal-looking entry in the source list.
"""
import hashlib
import logging
from datetime import datetime, timedelta

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIKnowledgeChunk

logger = logging.getLogger(__name__)

# Bounds a runaway shelve() loop (e.g. an agent re-deriving and re-saving the
# same kind of observation every turn). Generous on purpose — this guards
# against pathological repetition, not normal use. Not yet operator-facing;
# a config flag can replace this constant later without changing callers.
_DAILY_QUOTA = 50

_AI_CURATED_SOURCE_NAME = 'AI 자율 비치 (AI Curated Notes)'
_AI_CURATED_PARAMETER_NAME = 'ai_curated.shelve'

# Peer-trust provenances for contradiction flagging (§3.3) — deliberately
# excludes external_authority/user_provided: a collision with those is
# handled at citation time (the model is told to prefer them), not here.
_PEER_TRUST_PROVENANCE = ('ai_curated', 'data_derived')


def _get_or_create_ai_curated_source():
    """The reserved AIContextSource all shelve() writes are attributed to.
    sync_interval_min=0 so the scheduler never registers a job for it (see
    ai_scheduler_service.py: 'if interval_min <= 0: continue') — this source
    is never synced, only written to directly by shelve_knowledge()."""
    source = AIContextSource.query.filter_by(parameter_name=_AI_CURATED_PARAMETER_NAME).first()
    if source:
        return source
    source = AIContextSource(
        facility_id='global',
        source_name=_AI_CURATED_SOURCE_NAME,
        source_type='ai_curated',
        parameter_name=_AI_CURATED_PARAMETER_NAME,
        config_json='{}',
        sync_interval_min=0,
        is_active=True,
        is_enabled=False,
    )
    db.session.add(source)
    db.session.commit()
    return source


def _quota_remaining():
    """Rows with provenance='ai_curated' created in the last 24h. Counts
    regardless of is_enabled/context_state — a retired note still counts
    against the quota, since the write itself is what's bounded, not its
    surviving usefulness."""
    since = datetime.utcnow() - timedelta(hours=24)
    count = AIKnowledgeChunk.query.filter(
        AIKnowledgeChunk.provenance == 'ai_curated',
        AIKnowledgeChunk.created_at >= since,
    ).count()
    return _DAILY_QUOTA - count


def _normalize_heading(heading):
    return (heading or '').strip().lower()


# @ANCHOR: FIND_HEADING_MATCHES
def find_heading_matches(heading, tag_list, provenances, exclude_hash=None):
    """Existing enabled items, restricted to `provenances`, that share at
    least one tag AND have the same normalized heading. A deterministic,
    bounded stand-in for "this is about the same specific topic" (no
    LLM/semantic comparison) — shared by:
      - _detect_heading_collision (P4): matches within peer trust
        ('ai_curated','data_derived') are treated as a contradiction signal.
      - knowledge_promotion_service.list_review_items (P5): matches against
        authoritative provenance are shown as an ADVISORY badge only — see
        that module's docstring for why this isn't auto-promotion."""
    norm_heading = _normalize_heading(heading)
    if not norm_heading or not tag_list:
        return []
    q = (
        AIKnowledgeChunk.query
        .filter(AIKnowledgeChunk.provenance.in_(provenances))
        .filter(AIKnowledgeChunk.is_enabled.is_(True))
    )
    if exclude_hash:
        q = q.filter(AIKnowledgeChunk.content_hash != exclude_hash)
    tag_set = set(tag_list)
    matches = []
    for row in q.all():
        if _normalize_heading(row.section_title) != norm_heading:
            continue
        row_tags = {t.strip().lower() for t in (row.tags or '').split(',') if t.strip()}
        if tag_set & row_tags:
            matches.append(row)
    return matches


def _detect_heading_collision(heading, tag_list, content_hash):
    """Return a flagged_reason string if an existing peer-trust, enabled item
    shares at least one tag AND has the same normalized heading but different
    content — a deterministic, bounded stand-in for "conflicting information
    on the same topic" (no LLM/semantic comparison — see module docstring).
    None if no collision."""
    matches = find_heading_matches(heading, tag_list, _PEER_TRUST_PROVENANCE, exclude_hash=content_hash)
    if not matches:
        return None
    row = matches[0]
    tag_set = set(tag_list)
    row_tags = {t.strip().lower() for t in (row.tags or '').split(',') if t.strip()}
    return (
        f"동일 태그({','.join(sorted(tag_set & row_tags))})·동일 제목의 기존 "
        f"{row.provenance} 항목(id={row.unique_id})과 내용이 달라 검토 필요."
    )


def shelve_knowledge(content, tags, heading=None, entity_ref=None,
                      attribution=None, content_kind='prose', ttl=None):
    """Write one AI-curated knowledge item. This IS the knowledge_shelve verb
    (§4) — callers (the action dispatch layer) pass through whatever the
    model provided; this function owns all the trust/governance decisions.

    Args:
        content: the knowledge text (required, non-empty).
        tags: list[str] or comma-separated str — REQUIRED and must be
            non-empty. Unlike a registered source's chunk (where an untagged
            item is deliberately "always a candidate", §2), an untagged
            ai_curated note would be maximally broad noise at the AI's own
            lowest trust tier — so this write path refuses it rather than
            silently defaulting to unscoped.
        heading: short title; defaults to a content-derived stub if omitted.
        entity_ref: optional AoT GIS entity unique_id link.
        attribution: human-readable citation (e.g. "대화 2026-07-18",
            "텔레메트리 분석"). Defaults to a generic "AI 자율 비치" note if
            the caller doesn't supply one — never fabricated beyond that.
        content_kind: 'prose' (default) or 'structured'.
        ttl: optional expiry datetime.

    Returns: {status, message, chunk_id, flagged_reason} —
        status is one of 'created' | 'duplicate' | 'quota_exceeded' | 'rejected'.
    """
    content = (content or '').strip()
    if not content:
        return {'status': 'rejected', 'message': 'content is required.', 'chunk_id': None}

    if isinstance(tags, str):
        tag_list = [t.strip().lower() for t in tags.split(',') if t.strip()]
    else:
        tag_list = [t.strip().lower() for t in (tags or []) if t and t.strip()]
    if not tag_list:
        return {
            'status': 'rejected',
            'message': 'tags is required and must be non-empty for an AI-curated note '
                       '(an untagged item would be unscoped and surface for every query).',
            'chunk_id': None,
        }

    remaining = _quota_remaining()
    if remaining <= 0:
        return {
            'status': 'quota_exceeded',
            'message': f'Daily ai_curated shelve quota ({_DAILY_QUOTA}) reached — try again later.',
            'chunk_id': None,
        }

    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    existing = AIKnowledgeChunk.query.filter_by(content_hash=content_hash, is_enabled=True).first()
    if existing:
        return {
            'status': 'duplicate',
            'message': 'Identical content already shelved — no new row written.',
            'chunk_id': existing.unique_id,
        }

    heading = (heading or '').strip() or content[:60]
    flagged_reason = _detect_heading_collision(heading, tag_list, content_hash)

    source = _get_or_create_ai_curated_source()
    chunk = AIKnowledgeChunk(
        source_id=source.source_id,
        source_name=source.source_name,
        section_title=heading,
        digest_text=content,
        raw_excerpt=content[:4000],
        content_hash=content_hash,
        context_state='system_generated',
        is_enabled=True,
        provenance='ai_curated',
        content_kind=content_kind if content_kind in ('prose', 'structured') else 'prose',
        tags=','.join(tag_list),
        entity_ref=entity_ref,
        attribution=(attribution or '').strip() or 'AI 자율 비치 (출처 미기재)',
        ttl=ttl,
        flagged_reason=flagged_reason,
    )
    db.session.add(chunk)
    db.session.commit()

    logger.info(
        "[KnowledgeShelve] shelved chunk_id=%s tags=%s flagged=%s (quota remaining after write: %d)",
        chunk.unique_id, tag_list, bool(flagged_reason), remaining - 1,
    )
    return {
        'status': 'created',
        'message': 'Shelved as ai_curated (unconfirmed) knowledge.'
                   + (f' Flagged: {flagged_reason}' if flagged_reason else ''),
        'chunk_id': chunk.unique_id,
        'flagged_reason': flagged_reason,
    }
