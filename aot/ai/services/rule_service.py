# coding=utf-8
"""
RuleService — v3.1 tier architecture, Phase 3 (3-tier evolving rules).

Two responsibilities, both flag-gated (t3_rule_layer_enabled):

1. INJECTION (enforcement/learned layer): return the prompt fragments of active
   AIRule rows matching a role, so brain_resolver can append them to the system
   prompt right after the philosophy preamble (the constitution). This is how a
   language-style rule is enforced — by prompting, not sync regex (§12-4).

2. PROMOTION (learned layer): scan the advisory-audit evidence Phase 2 records
   on AIHistory.metadata_json, aggregate repeated violations by pattern, and
   when a pattern accumulates ≥ threshold evidence create an AIRuleProposal.
   `style` proposals (advisory-language framing) auto-approve into an active
   AIRule; `behavior`/`scope` stay pending for user confirmation. The promoted
   artifact is a PROMPT FRAGMENT, never a regex (§12-4).

This closes the evolution loop: violation observed (Phase 2) → evidence ≥N →
proposal → auto-approve (style) → rule injected → next responses steered away
from the violation. "기억이 규칙이 된다."

@phase active
@stability new
@dependency AIRule, AIRuleProposal, AIHistory, AIGlobalSettings
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Evidence threshold before a violation pattern becomes a proposal. Matches the
# architecture proposal's "증거 ≥3" auto-approve criterion (§4).
EVIDENCE_THRESHOLD = 3

# Roles that receive injected enforcement rules — same user-facing set the
# philosophy preamble targets (ai_philosophy_preamble.PHILOSOPHY_ROLES).
_USER_FACING_ROLES = frozenset({'synthesizer', 'worker', 'chat'})

# Maps an advisory-audit violation category to the promotion path + the prompt
# fragment a rule for it should carry. execution_declaration / completion_claim
# / user_command are all advisory-language *style* violations → auto-approvable.
# Rule fragments are INSTRUCTIONS TO THE AI, injected into its prompt. They are
# written language-neutrally (English, conceptual) so they steer behavior in ANY
# output language — the AI still replies in the user's language. Do not phrase
# these around one human language's grammar.
_CATEGORY_SPEC = {
    'execution_declaration': {
        'category': 'style',
        'fragment': (
            "Never describe a device-control action as something you ARE doing or "
            "WILL do (a first-person execution statement). Physical control runs only "
            "after user approval, so always phrase it as a proposal awaiting approval "
            "(e.g. 'Prepared a draft to run [device] for [duration] — approve?'), in "
            "the user's language."
        ),
    },
    'completion_claim': {
        'category': 'style',
        'fragment': (
            "Never claim a physical action is already complete (e.g. 'turned on', "
            "'activated', 'done') before approval and execution (Law 3, physical "
            "truth). State only intent / a proposal until the tool result confirms it."
        ),
    },
    'user_command': {
        'category': 'style',
        'fragment': (
            "Never issue imperative commands to the user. Use advisory, informational "
            "phrasing — the operator decides (absolute user-agency principle)."
        ),
    },
}


def is_enabled():
    """True if the rule layer flag is on. Fails safe to False."""
    try:
        from aot.databases.models import AIGlobalSettings
        settings = AIGlobalSettings.query.first()
        return bool(settings and getattr(settings, 't3_rule_layer_enabled', False))
    except Exception as e:
        logger.debug(f"[RuleService] flag read failed, defaulting off: {e}")
        return False


# ---------------------------------------------------------------------------
# 1. Injection
# ---------------------------------------------------------------------------

def active_enforcement_fragment(role):
    """Return the concatenated prompt fragments of active AIRule rows that apply
    to `role` (role_scope == role or 'all'), or '' when the flag is off / none
    apply. Called from brain_resolver after the philosophy preamble. Never
    raises — a failure here must not break prompt assembly."""
    try:
        if not is_enabled():
            return ''
        from aot.databases.models.ai import AIRule
        rules = AIRule.query.filter_by(is_active=True).all()
        applicable = [
            r for r in rules
            if r.role_scope == 'all' or r.role_scope == role
        ]
        if not applicable:
            return ''
        lines = [f"- {r.content}" for r in applicable]
        # Prompt injection — an instruction the AI reads, so it is written in
        # language-neutral English. The AI still replies in the user's language.
        return (
            "\n## Learned Enforcement Rules\n"
            "The rules below were reinforced from past observed violations. "
            "You must comply with them:\n"
            + "\n".join(lines) + "\n"
        )
    except Exception as e:
        logger.debug(f"[RuleService] injection skipped: {e}")
        return ''


def inject_rules(system_prompt, role):
    """Append active enforcement-rule fragments to a system prompt for a
    user-facing role. No-op for internal roles / flag off / no rules."""
    if role not in _USER_FACING_ROLES:
        return system_prompt
    fragment = active_enforcement_fragment(role)
    if not fragment:
        return system_prompt
    return (system_prompt or '') + fragment


# ---------------------------------------------------------------------------
# 2. Promotion (evidence → proposal → auto-approved rule)
# ---------------------------------------------------------------------------

class RuleProposalGenerator:
    """Turns accumulated advisory-audit evidence into rule proposals."""

    @staticmethod
    def scan_and_propose(limit=500):
        """Scan recent AIHistory records carrying advisory-audit violations,
        aggregate by (category), and create/refresh an AIRuleProposal per
        pattern that has ≥ EVIDENCE_THRESHOLD distinct evidence records. Style
        proposals auto-approve into an active AIRule.

        Returns a summary dict. No-op (returns disabled) when the flag is off.
        Idempotent: re-running updates evidence on the existing proposal for a
        pattern rather than duplicating it (pattern_key dedupe).
        """
        if not is_enabled():
            return {'status': 'disabled'}

        from aot.databases.models.ai import AIHistory, AIRuleProposal
        from aot.aot_flask.extensions import db

        # Gather evidence: AIHistory rows whose metadata mentions advisory_audit.
        rows = (
            AIHistory.query
            .filter(AIHistory.metadata_json.like('%advisory_audit%'))
            .order_by(AIHistory.id.desc())
            .limit(limit)
            .all()
        )

        # Aggregate evidence history-ids by violation category.
        evidence_by_category = {}
        for row in rows:
            try:
                meta = json.loads(row.metadata_json) if row.metadata_json else {}
            except (ValueError, TypeError):
                continue
            audit = meta.get('advisory_audit')
            if not audit:
                continue
            for v in audit.get('violations', []):
                cat = v.get('category')
                if cat not in _CATEGORY_SPEC:
                    continue
                evidence_by_category.setdefault(cat, set()).add(row.unique_id)

        created, auto_approved, updated = [], [], []
        for cat, ev_ids in evidence_by_category.items():
            if len(ev_ids) < EVIDENCE_THRESHOLD:
                continue
            spec = _CATEGORY_SPEC[cat]
            pattern_key = f"advisory:{cat}"
            proposal = AIRuleProposal.query.filter_by(pattern_key=pattern_key).first()

            if proposal is None:
                proposal = AIRuleProposal(
                    proposed_rule_text=spec['fragment'],
                    category=spec['category'],
                    role_scope='all',
                    evidence_ids=json.dumps(sorted(ev_ids)),
                    evidence_count=len(ev_ids),
                    pattern_key=pattern_key,
                    status='pending',
                    created_by='advisory_audit_generator',
                )
                db.session.add(proposal)
                db.session.flush()  # assign unique_id
                created.append(pattern_key)
            else:
                # Refresh evidence on an existing proposal.
                proposal.evidence_ids = json.dumps(sorted(ev_ids))
                proposal.evidence_count = len(ev_ids)
                updated.append(pattern_key)

            # Auto-approve style proposals that aren't already resolved.
            if spec['category'] == 'style' and proposal.status in ('pending',):
                rule_uid = RuleProposalGenerator._approve(proposal, auto=True)
                auto_approved.append(pattern_key)

        db.session.commit()
        return {
            'status': 'ok',
            'created': created,
            'updated': updated,
            'auto_approved': auto_approved,
            'categories_seen': list(evidence_by_category.keys()),
        }

    @staticmethod
    def _approve(proposal, auto=False):
        """Turn a proposal into an active AIRule (learned layer) and mark it
        resolved. Returns the new AIRule.unique_id. Conflict guard: if an active
        rule already exists for this proposal's pattern, don't duplicate."""
        from aot.databases.models.ai import AIRule
        from aot.aot_flask.extensions import db

        existing = AIRule.query.filter_by(source=f"proposal:{proposal.unique_id}", is_active=True).first()
        if existing:
            proposal.resulting_rule_id = existing.unique_id
            return existing.unique_id

        rule = AIRule(
            name=f"learned:{proposal.pattern_key}",
            layer='learned',
            role_scope=proposal.role_scope,
            inject_at='system_prompt',
            content=proposal.proposed_rule_text,
            severity='warn',
            is_active=True,
            source=f"proposal:{proposal.unique_id}",
        )
        db.session.add(rule)
        db.session.flush()
        proposal.status = 'auto_approved' if auto else 'approved'
        proposal.resulting_rule_id = rule.unique_id
        proposal.reviewed_at = datetime.now(timezone.utc)
        logger.info(f"[RuleService] {'Auto-approved' if auto else 'Approved'} proposal {proposal.pattern_key} → active rule {rule.unique_id}")
        return rule.unique_id
