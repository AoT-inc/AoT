# coding=utf-8
"""
knowledge_library_service.py — the LIBRARY's human-facing side (C6).

Two things live here that `knowledge_shelve_service` deliberately does not do:

  1. **Browsing every item**, not just the AI's own notes. The review surface
     (P5) only ever listed `provenance='ai_curated'`, because its job was
     "check what the AI wrote". But the page is supposed to be 지식 저장소
     관리 (§8) — and an operator who cannot SEE what the library holds cannot
     judge whether it is worth anything, cannot spot a stale external feed,
     and cannot tell an empty library from a broken one.

  2. **Hand-entering knowledge.** Every write path so far needed either a
     registered external source or an AI turn. That makes the library a thing
     only the AI fills, which is backwards for an operator who already KNOWS
     the answer — the person who has run this farm for ten years should not
     have to ask an AI to write down that the north block floods in July.
     See feedback: 기능이 어려우면 AI 말고 화면을 고칠 것.

Trust: a person typing knowledge in IS the authority for it, so these rows
are `provenance='user_provided'`, `context_state='user_confirmed'` (§3.1 —
"사용자가 대화/업로드로 확정한 사실 → 높음"). That is the one place trust is
granted at write time in this system, and it is granted because a human is
the one doing the writing, not because the content looks authoritative.
"""
import hashlib
import logging

from sqlalchemy import or_

from aot.aot_flask.extensions import db
from aot.databases.models import AIKnowledgeChunk
from aot.ai.services.knowledge_shelve_service import (
    _clean_source_url, get_or_create_reserved_source,
)

logger = logging.getLogger(__name__)

_USER_SOURCE_NAME = '직접 입력 (Hand-entered Knowledge)'
_USER_PARAMETER_NAME = 'user_provided.manual'

# 한 화면에 담을 수 있는 만큼. 라이브러리가 커지면 필터로 좁히는 것이 맞지,
# 수천 행을 한 번에 그리는 것이 맞지는 않다.
_PAGE_SIZE = 50

_PROVENANCE_LABELS = {
    'external_authority': '권위',
    'user_provided': '사용자',
    'data_derived': '관측',
    'ai_curated': 'AI 정리',
}


def _parse_tags(tags):
    if isinstance(tags, str):
        return [t.strip().lower() for t in tags.split(',') if t.strip()]
    return [t.strip().lower() for t in (tags or []) if t and t.strip()]


def _to_dict(row):
    return {
        'chunk_id': row.unique_id,
        'heading': row.section_title,
        'content': row.digest_text,
        'tags': [t.strip() for t in (row.tags or '').split(',') if t.strip()],
        'provenance': row.provenance,
        'provenance_label': _PROVENANCE_LABELS.get(row.provenance, row.provenance),
        'context_state': row.context_state,
        'attribution': row.attribution,
        'source_url': row.source_url,
        'source_name': row.source_name,
        'flagged_reason': row.flagged_reason,
        'reuse_count': row.reuse_count or 0,
        'is_enabled': bool(row.is_enabled),
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }


# @ANCHOR: KNOWLEDGE_BROWSE
def browse(query=None, tag=None, provenance=None, include_disabled=False,
           page=1, page_size=_PAGE_SIZE):
    """Every knowledge item, filtered. Ordered newest first.

    Deliberately a plain DB query, NOT `knowledge_search`: browsing asks
    "what is in here" and must show items a relevance ranker would drop,
    including retired ones when asked. Relevance scoring is the AI's read
    path, not a person's inventory."""
    q = AIKnowledgeChunk.query
    if not include_disabled:
        q = q.filter(AIKnowledgeChunk.is_enabled.is_(True))
    if provenance:
        q = q.filter(AIKnowledgeChunk.provenance == provenance)
    if tag:
        # 태그는 쉼표로 이어 붙인 한 컬럼이라 LIKE 로 본다. 부분 일치가
        # 섞이지 않게 양쪽에 쉼표를 붙여 비교한다('무' 가 '무름병' 에
        # 걸리지 않도록).
        needle = tag.strip().lower()
        q = q.filter(or_(
            AIKnowledgeChunk.tags == needle,
            AIKnowledgeChunk.tags.like(f'{needle},%'),
            AIKnowledgeChunk.tags.like(f'%,{needle},%'),
            AIKnowledgeChunk.tags.like(f'%,{needle}'),
        ))
    if query:
        like = f'%{query.strip()}%'
        q = q.filter(or_(
            AIKnowledgeChunk.section_title.ilike(like),
            AIKnowledgeChunk.digest_text.ilike(like),
            AIKnowledgeChunk.attribution.ilike(like),
        ))

    total = q.count()
    page = max(1, int(page or 1))
    rows = (q.order_by(AIKnowledgeChunk.created_at.desc())
             .limit(page_size).offset((page - 1) * page_size).all())
    return {
        'items': [_to_dict(r) for r in rows],
        'total': total,
        'page': page,
        'page_size': page_size,
        'has_more': total > page * page_size,
    }


def tag_counts(limit=40):
    """Tags actually in use, with how many enabled items carry each — the
    filter bar's vocabulary. Built by scanning rather than a GROUP BY because
    tags live comma-joined in one column; the row count here is small enough
    (this is a curated library, not telemetry) that it isn't worth a schema
    change to normalize."""
    counts = {}
    for (tags,) in db.session.query(AIKnowledgeChunk.tags).filter(
            AIKnowledgeChunk.is_enabled.is_(True)).all():
        for t in (tags or '').split(','):
            t = t.strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{'tag': t, 'count': c} for t, c in ordered[:limit]]


def usage_stats():
    """무엇이 실제로 **쓰이고** 있는가.

    지금까지 이 화면은 저장소에 무엇이 **있는지**만 보여줬다. 그런데 고도화
    방향을 정하려면 다른 질문에 답해야 한다 — 넣어 둔 것이 인용은 되고 있나,
    AI 가 비친 것 중 사람이 검토한 비율은 얼마나 되나, 폐기율이 높다면 AI 가
    쓸모없는 것을 적립하고 있다는 뜻인가.

    `reuse_count` 는 knowledge_search 가 항목을 실제로 내보낼 때마다 오른다
    (knowledge_promotion_service.note_reuse) — 즉 "검색에 걸렸다" 의 횟수이지
    "답변에 인용됐다" 는 아니다. 그 둘을 구분할 계측은 아직 없으므로, 화면
    문구도 '검색에 걸린 횟수'라고 정확히 말해야 한다."""
    rows = AIKnowledgeChunk.query.all()
    ai_rows = [r for r in rows if r.provenance == 'ai_curated']
    reviewed = [r for r in ai_rows if r.context_state in ('user_confirmed', 'corroborated')]
    retired = [r for r in ai_rows if r.context_state == 'retired']
    used = [r for r in rows if (r.reuse_count or 0) > 0]
    top = sorted(rows, key=lambda r: -(r.reuse_count or 0))[:5]
    return {
        'total': len(rows),
        'never_retrieved': len(rows) - len(used),
        'ai_curated_total': len(ai_rows),
        'ai_curated_reviewed': len(reviewed),
        'ai_curated_retired': len(retired),
        'with_source_url': len([r for r in rows if r.source_url]),
        'top_retrieved': [
            {'heading': r.section_title, 'reuse_count': r.reuse_count or 0,
             'provenance': r.provenance}
            for r in top if (r.reuse_count or 0) > 0
        ],
    }


def summary():
    """Counts per provenance — what the page shows above the list so an
    operator can tell 'nothing here yet' from 'plenty here, none of it
    authoritative'."""
    out = {'total': 0, 'by_provenance': {}}
    for prov, in db.session.query(AIKnowledgeChunk.provenance).filter(
            AIKnowledgeChunk.is_enabled.is_(True)).all():
        out['by_provenance'][prov] = out['by_provenance'].get(prov, 0) + 1
        out['total'] += 1
    return out


# @ANCHOR: ADD_USER_KNOWLEDGE
def add_user_knowledge(content, tags, heading=None, attribution=None,
                       source_url=None, entity_ref=None):
    """An operator writes knowledge in by hand.

    Enters at `user_provided` / `user_confirmed` — see the module docstring
    for why this is the one write path that grants trust immediately. No
    quota (a person typing is self-limiting) and no contradiction flagging
    against peers (that signal exists to police the AI's own output).
    Duplicate content is still refused: the same text twice is a mistake
    whoever typed it."""
    content = (content or '').strip()
    if not content:
        return {'success': False, 'error': 'content is required.'}

    tag_list = _parse_tags(tags)
    if not tag_list:
        return {'success': False,
                'error': 'At least one tag is required — an untagged item '
                         'would surface for every unrelated query.'}

    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
    existing = AIKnowledgeChunk.query.filter_by(
        content_hash=content_hash, is_enabled=True).first()
    if existing:
        return {'success': False, 'error': 'Identical content is already in the library.',
                'chunk_id': existing.unique_id}

    source = get_or_create_reserved_source(
        _USER_PARAMETER_NAME, _USER_SOURCE_NAME, 'user_provided')
    heading = (heading or '').strip() or content[:60]
    row = AIKnowledgeChunk(
        source_id=source.source_id,
        source_name=source.source_name,
        section_title=heading,
        digest_text=content,
        raw_excerpt=content[:4000],
        content_hash=content_hash,
        provenance='user_provided',
        context_state='user_confirmed',
        content_kind='prose',
        tags=','.join(tag_list),
        entity_ref=(entity_ref or None),
        attribution=(attribution or '').strip() or '직접 입력',
        source_url=_clean_source_url(source_url),
        is_enabled=True,
    )
    db.session.add(row)
    db.session.commit()
    logger.info("[KnowledgeLibrary] hand-entered chunk_id=%s tags=%s", row.unique_id, tag_list)
    return {'success': True, 'chunk_id': row.unique_id, 'item': _to_dict(row)}


def set_enabled(chunk_id, enabled):
    """Take an item out of the AI's reach, or put it back — for ANY item, not
    just the AI's own notes (which have their own retire/reactivate path with
    trust-state semantics). Used for a stale hand-entered note or a bad
    synced chunk. The row is kept either way."""
    row = AIKnowledgeChunk.query.filter_by(unique_id=chunk_id).first()
    if not row:
        return {'success': False, 'error': 'Item not found.'}
    row.is_enabled = bool(enabled)
    db.session.commit()
    return {'success': True, 'is_enabled': row.is_enabled}
