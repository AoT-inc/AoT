# coding=utf-8
"""
knowledge_promotion_service.py — human-driven trust transitions + reuse-based
auto-corroboration (P5, docs/design/ai-library-redesign.md §3.2, §8).

§3.2's transition diagram has four branches; this module implements them with
a deliberately narrower automatic scope than the diagram literally suggests:

  IMPLEMENTED, human-driven (safe — a person is deciding):
    - confirm_item / edit_item  -> user_confirmed  ("사용자 확인/수정")
    - retire_item               -> retired         ("사용자 반박")

  IMPLEMENTED, fully automatic (safe — reuse count alone is the signal,
  no semantic judgment required):
    - note_reuse -> corroborated once a system_generated item survives
      _REUSE_PROMOTION_THRESHOLD retrievals ("N회 재사용·무반박")

  DELIBERATELY advisory-only, NOT automatic (§3.2 names these as their own
  branches — "권위 소스와 교차일치" and "모순 탐지 → retired" — but this
  module surfaces them as a badge/flag for a human to act on instead):
    - list_review_items()'s `authoritative_match` field: a same-tag,
      same-heading external_authority/user_provided item exists. Sharing a
      heading is NOT proof the two AGREE — verifying that needs semantic
      comparison this deterministic module doesn't do, so promoting on a
      heading match alone risked corroborating a note that actually
      contradicts the authority it "matched". A human confirms instead.
    - P4's flagged_reason (peer-trust heading collision): NOT auto-retired
      here, for the mirror reason — a collision doesn't say WHICH of the two
      conflicting notes is wrong. A human reads flagged_reason and retires
      whichever one is actually incorrect.
"""
import logging

from aot.aot_flask.extensions import db
from aot.databases.models import AIKnowledgeChunk
from aot.ai.services.knowledge_shelve_service import find_heading_matches

logger = logging.getLogger(__name__)

# How many times a system_generated item must be retrieved by knowledge_search
# before it's trusted enough to auto-promote. Deliberately not tiny — a couple
# of hits could just mean the same conversation asked twice.
_REUSE_PROMOTION_THRESHOLD = 5

_AUTHORITATIVE_PROVENANCE = ('external_authority', 'user_provided')


def _get_ai_curated(chunk_id):
    return AIKnowledgeChunk.query.filter_by(unique_id=chunk_id, provenance='ai_curated').first()


def list_review_items(context_state=None):
    """AI-curated items for the review surface (§8). Each is annotated with
    an `authoritative_match` badge — advisory only, see module docstring."""
    q = AIKnowledgeChunk.query.filter_by(provenance='ai_curated')
    if context_state:
        q = q.filter_by(context_state=context_state)
    items = q.order_by(AIKnowledgeChunk.created_at.desc()).all()

    out = []
    for row in items:
        tag_list = [t.strip() for t in (row.tags or '').split(',') if t.strip()]
        matches = find_heading_matches(row.section_title, tag_list, _AUTHORITATIVE_PROVENANCE)
        out.append({
            'chunk_id': row.unique_id,
            'heading': row.section_title,
            'content': row.digest_text,
            'tags': tag_list,
            'attribution': row.attribution,
            # C4: 원문 주소. 리뷰어가 "이게 맞는 말인가" 를 확인할 유일한 수단이고,
            # 그 확인이 §3.2 승격의 전제다 — 없으면 항목은 영원히 미확인으로 남는다.
            'source_url': row.source_url,
            'context_state': row.context_state,
            'flagged_reason': row.flagged_reason,
            'reuse_count': row.reuse_count or 0,
            'is_enabled': bool(row.is_enabled),
            'created_at': row.created_at.isoformat() if row.created_at else None,
            'authoritative_match': matches[0].source_name if matches else None,
        })
    return out


def confirm_item(chunk_id):
    row = _get_ai_curated(chunk_id)
    if not row:
        return {'success': False, 'error': 'Item not found.'}
    row.context_state = 'user_confirmed'
    row.is_enabled = True
    db.session.commit()
    return {'success': True}


def edit_item(chunk_id, content=None, heading=None, tags=None):
    """A human editing an ai_curated note IS a confirmation — §3.2 groups
    '사용자 확인/수정' as a single branch, both landing on user_confirmed."""
    row = _get_ai_curated(chunk_id)
    if not row:
        return {'success': False, 'error': 'Item not found.'}

    if content is not None and str(content).strip():
        row.digest_text = str(content).strip()
    if heading is not None and str(heading).strip():
        row.section_title = str(heading).strip()
    if tags is not None:
        tag_list = (
            [t.strip().lower() for t in tags.split(',') if t.strip()]
            if isinstance(tags, str)
            else [t.strip().lower() for t in tags if t and t.strip()]
        )
        if not tag_list:
            return {'success': False, 'error': 'tags must not be empty.'}
        row.tags = ','.join(tag_list)

    row.context_state = 'user_confirmed'
    row.is_enabled = True
    db.session.commit()
    return {'success': True}


def retire_item(chunk_id):
    """§3.2: excluded from search, row/history kept (not deleted)."""
    row = _get_ai_curated(chunk_id)
    if not row:
        return {'success': False, 'error': 'Item not found.'}
    row.context_state = 'retired'
    row.is_enabled = False
    db.session.commit()
    return {'success': True}


def reactivate_item(chunk_id):
    """Undo an accidental retire. Goes back to system_generated (not
    user_confirmed) — un-retiring isn't the same as having reviewed it."""
    row = _get_ai_curated(chunk_id)
    if not row:
        return {'success': False, 'error': 'Item not found.'}
    row.context_state = 'system_generated'
    row.is_enabled = True
    db.session.commit()
    return {'success': True}


# @ANCHOR: NOTE_REUSE
def note_reuse(chunk_ids):
    """Called from knowledge_search.search() for every ai_curated hit it
    surfaces. Increments reuse_count via a raw UPDATE — deliberately bypassing
    the ORM so this does NOT touch updated_at (Column(onupdate=...) is a
    Python-side, ORM-flush-only hook; a hand-written text() UPDATE never
    triggers it) and therefore does NOT bust knowledge_search's
    process-level library cache (keyed on max(updated_at)) on every search
    hit — only promotion, which should invalidate that cache, uses the
    normal ORM path below.

    Silently no-ops on any error: this is best-effort bookkeeping on a read
    path, never allowed to break a search call."""
    if not chunk_ids:
        return
    try:
        from sqlalchemy import text, bindparam
        stmt = text(
            "UPDATE ai_knowledge_chunk SET reuse_count = COALESCE(reuse_count, 0) + 1 "
            "WHERE unique_id IN :ids AND provenance = 'ai_curated' AND context_state = 'system_generated'"
        ).bindparams(bindparam('ids', expanding=True))
        db.session.execute(stmt, {'ids': list(chunk_ids)})
        db.session.commit()

        promotable = (
            AIKnowledgeChunk.query
            .filter(AIKnowledgeChunk.unique_id.in_(list(chunk_ids)))
            .filter_by(provenance='ai_curated', context_state='system_generated')
            .filter(AIKnowledgeChunk.reuse_count >= _REUSE_PROMOTION_THRESHOLD)
            .all()
        )
        for row in promotable:
            row.context_state = 'corroborated'
            logger.info(
                "[KnowledgePromotion] auto-corroborated chunk_id=%s after %d reuses",
                row.unique_id, row.reuse_count,
            )
        if promotable:
            db.session.commit()
    except Exception as e:
        logger.warning("[KnowledgePromotion] note_reuse failed: %s", e)
        db.session.rollback()
