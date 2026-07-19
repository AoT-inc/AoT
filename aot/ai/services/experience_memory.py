# coding=utf-8
"""
ExperienceMemory — v3.1 tier architecture, Phase 4 (memory loop).

The system's tiered memory of how it's used and where it fails (proposal §7),
and the second half of the evolution loop Phase 2/3 started. Phase 3 already
turns advisory-language (style) violations into rules; Phase 4 adds the other
two memory types and closes the ERROR path:

  - error  : degraded responses, CLARIFY loops, user rejections. Aggregated by
             pattern; when a pattern recurs ≥ threshold it becomes a PENDING
             behavior AIRuleProposal (user-confirm — never auto-applied, §4).
  - emotion: user dissatisfaction / friction (re-question, frustration markers)
             detected deterministically from the user's message. Tracked for a
             satisfaction trend (operator alert / style calibration are later).
  - usage  : recurring goals (direction) — scaffolded here, populated later.

Tiered by occurrence_count: hot (frequent/recent) / warm / cold. All recording
runs in the existing async advisory-audit worker — never on the request path.
Flag-gated (t3_memory_loop_enabled); no-op when off.

@phase active
@stability new
@dependency AIExperienceMemory, AIRuleProposal
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Occurrence thresholds for tier promotion.
_HOT_THRESHOLD = 3
_WARM_THRESHOLD = 2

# Degraded-response text markers — a best-effort FALLBACK only. The primary
# degraded signal is structural (status/intent, see detect_error_pattern), which
# is language-agnostic. These cover the common ko/en phrasings of the gettext'd
# degraded messages; other languages fall through to the structural check.
# (Truly language-agnostic text classification is the deferred LLM-judge layer.)
_DEGRADED_MARKERS = (
    'temporarily unavailable', 'Service is temporarily unavailable',
    "couldn't process", 'could not generate', '일시적으로 이용', '서비스 이용 불가',
    '처리하지 못했습니다', '다시 시도',
)

# User-dissatisfaction / friction markers (emotion signal) — the user pushing
# back, re-asking, or expressing frustration. Inherently language-specific: a
# substring heuristic cannot be language-agnostic, so this is a MULTILINGUAL MAP
# (extend per language as needed). Full language coverage is the LLM-judge layer;
# this fast pre-filter deliberately favors precision (false negatives ok).
_DISSATISFACTION_MARKERS_BY_LANG = {
    'ko': (
        '아니 ', '아니야', '아니오', '틀렸', '잘못', '왜 안', '왜 못', '안 돼', '안돼',
        '다시 해', '다시해', '그게 아니', '이게 아니', '짜증', '답답',
    ),
    'en': (
        'wrong', 'no,', "that's not", 'not what', 'try again', 'incorrect',
        "doesn't work", 'still not', 'useless',
    ),
    'ja': ('違う', 'ちがう', 'できない', 'もう一度', 'なぜ'),
}
# Flat tuple used by the deterministic scan (all languages at once — the user's
# message is in one language, so unrelated markers simply won't match).
_DISSATISFACTION_MARKERS = tuple(
    m for markers in _DISSATISFACTION_MARKERS_BY_LANG.values() for m in markers
)


def is_enabled():
    """True if the memory loop flag is on. Fails safe to False."""
    try:
        from aot.databases.models import AIGlobalSettings
        settings = AIGlobalSettings.query.first()
        return bool(settings and getattr(settings, 't3_memory_loop_enabled', False))
    except Exception as e:
        logger.debug(f"[ExperienceMemory] flag read failed, defaulting off: {e}")
        return False


def detect_error_pattern(insight, status, intent):
    """Return a stable error pattern_key for a failed/reworked response, or None.

    Prefers STRUCTURAL, language-agnostic signals (intent / status fields) over
    text so it works for any user language; the multilingual `_DEGRADED_MARKERS`
    are only a fallback for degraded responses that still report status 'success'
    (e.g. a graceful "temporarily unavailable" message)."""
    # Structural first — these fields are language-independent.
    if intent == 'CLARIFY':
        return 'error:clarify'
    if status in ('error', 'escalate', 'fail', 'failed'):
        return 'error:degraded'
    # Text fallback (best-effort, covers the common ko/en degraded phrasings).
    if insight and any(m in insight for m in _DEGRADED_MARKERS):
        return 'error:degraded'
    return None


def detect_dissatisfaction(user_text):
    """Return True if the user's message reads as dissatisfaction/friction.
    High-precision deterministic markers (emotion signal)."""
    if not user_text:
        return False
    low = user_text.lower()
    return any(m in user_text or m in low for m in _DISSATISFACTION_MARKERS)


def record(signal_type, pattern_key, evidence_id=None, summary=None, facility_id=None):
    """Record one occurrence of an experience pattern, promoting its tier by
    occurrence. Dedupes on pattern_key (one row per pattern, count grows).
    No-op when the flag is off. Never raises. Returns the row's (count, tier)
    or None."""
    try:
        if not is_enabled():
            return None
        from aot.databases.models.ai import AIExperienceMemory
        from aot.aot_flask.extensions import db

        row = AIExperienceMemory.query.filter_by(pattern_key=pattern_key).first()
        if row is None:
            row = AIExperienceMemory(
                signal_type=signal_type,
                pattern_key=pattern_key,
                summary=summary,
                occurrence_count=1,
                importance=1,
                tier='cold',
                evidence_ids=json.dumps([evidence_id] if evidence_id else []),
                facility_id=facility_id,
            )
            db.session.add(row)
        else:
            row.occurrence_count = (row.occurrence_count or 0) + 1
            row.last_seen_at = datetime.now(timezone.utc)
            if evidence_id:
                try:
                    ev = json.loads(row.evidence_ids) if row.evidence_ids else []
                except (ValueError, TypeError):
                    ev = []
                if evidence_id not in ev:
                    ev.append(evidence_id)
                    row.evidence_ids = json.dumps(ev[-50:])  # cap
            if summary:
                row.summary = summary

        # Tier + importance promotion by occurrence.
        c = row.occurrence_count
        row.tier = 'hot' if c >= _HOT_THRESHOLD else ('warm' if c >= _WARM_THRESHOLD else 'cold')
        row.importance = min(c, 10)
        db.session.commit()
        return (row.occurrence_count, row.tier)
    except Exception as e:
        logger.debug(f"[ExperienceMemory] record skipped ({pattern_key}): {e}")
        return None


def hot_memories(signal_type=None, limit=20):
    """Return hot-tier experience rows (optionally filtered by type), most
    important first. The injection-eligible slice ('사용 방향' / active friction).
    Empty when flag off."""
    try:
        if not is_enabled():
            return []
        from aot.databases.models.ai import AIExperienceMemory
        q = AIExperienceMemory.query.filter_by(tier='hot')
        if signal_type:
            q = q.filter_by(signal_type=signal_type)
        return q.order_by(AIExperienceMemory.importance.desc()).limit(limit).all()
    except Exception as e:
        logger.debug(f"[ExperienceMemory] hot_memories failed: {e}")
        return []


def promote_errors_to_proposals():
    """For each hot error-memory pattern (occurrence ≥ hot threshold), create a
    PENDING behavior AIRuleProposal (user-confirm) if one doesn't already exist.
    Behavior proposals are NEVER auto-applied (§4) — this only surfaces them for
    operator review. Returns list of pattern_keys proposed. No-op when off."""
    try:
        if not is_enabled():
            return []
        from aot.databases.models.ai import AIExperienceMemory, AIRuleProposal
        from aot.aot_flask.extensions import db

        proposed = []
        hot_errors = AIExperienceMemory.query.filter_by(signal_type='error', tier='hot').all()
        for mem in hot_errors:
            pk = f"behavior:{mem.pattern_key}"
            if AIRuleProposal.query.filter_by(pattern_key=pk).first():
                continue
            proposal = AIRuleProposal(
                proposed_rule_text=_behavior_fragment(mem.pattern_key),
                category='behavior',           # → pending, user-confirm, NOT auto-applied
                role_scope='all',
                evidence_ids=mem.evidence_ids or '[]',
                evidence_count=mem.occurrence_count,
                pattern_key=pk,
                status='pending',
                created_by='experience_memory_generator',
            )
            db.session.add(proposal)
            proposed.append(pk)
        if proposed:
            db.session.commit()
            logger.info(f"[ExperienceMemory] Created {len(proposed)} pending behavior proposal(s): {proposed}")
        return proposed
    except Exception as e:
        logger.debug(f"[ExperienceMemory] promote_errors_to_proposals failed: {e}")
        return []


def _behavior_fragment(pattern_key):
    """The prompt-fragment a behavior proposal carries (a suggestion for the
    operator to review, not an auto-applied rule). Written in English — it is an
    AI-steering instruction, applied regardless of the user's output language."""
    if pattern_key == 'error:clarify':
        return (
            "Repeated clarifying-question (CLARIFY) loops observed. When user intent "
            "is ambiguous, consider proposing the most likely interpretation first and "
            "asking for confirmation, rather than asking to clarify up front."
        )
    if pattern_key == 'error:degraded':
        return (
            "Repeated processing-failure / service-unavailable responses observed. "
            "Check the cause (credentials, router, tool connectivity) and, on failure, "
            "offer the user a concrete alternative instead of a generic error."
        )
    return f"Recurring error pattern ({pattern_key}) observed — review for improvement."
