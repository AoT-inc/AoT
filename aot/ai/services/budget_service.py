# coding=utf-8
"""
BudgetService — v3.1 tier architecture, Phase 6 (budget governance §13-2-F).

Meters per-connection usage against AIGlobalSettings.budget_limit_usd and
enforces it in stages: 80% alert / 100% soft-downgrade (rebind every role to
the cheapest conformant model on the same key) / optional hard-stop. The user's
"월 사용량 상한" — set once in onboarding, enforced automatically.

Cost is ESTIMATED (chars/4 ≈ tokens × a coarse per-provider price table),
because the engine layer doesn't surface real API usage here. Stated plainly:
this is directional budget control, not billing reconciliation. When engines
start returning real token counts, record_usage's estimate is the only thing
that changes.

All enforcement is expressed as role-binding updates (role_binder) + a dispatch
gate — no separate code path — so downgrade/stop/recover are just rebinds.
Flag-gated (t3_budget_governance_enabled); fully dormant when off.

@phase active
@stability new
@dependency AIUsageMeter, AIEntry, AIGlobalSettings, role_binder
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Coarse price table: model_type (or model_name substring) → (input_$/1M, output_$/1M).
# Directional only. Order matters — first substring match wins.
_PRICE_TABLE = [
    ('haiku',   (1.0, 5.0)),
    ('sonnet',  (3.0, 15.0)),
    ('opus',    (5.0, 25.0)),
    ('fable',   (10.0, 50.0)),
    # NOTE: exact compound keys only here, never a bare 'mini'/'nano' — 'mini' is
    # a substring of 'gemini' and 'minimax', which would silently misprice both.
    ('gpt-5.4-nano', (0.05, 0.4)),
    ('gpt-5.4-mini', (0.25, 2.0)),
    ('gpt-5',   (1.25, 10.0)),  # e.g. gpt-5.4, gpt-5.5
    ('minimax', (0.3, 1.2)),
    ('gemini-2.5-pro',   (1.25, 10.0)),
    ('gemini-2.5-flash', (0.3, 2.5)),
    ('gemini',  (0.3, 1.2)),
    ('groq',    (0.1, 0.3)),
    ('llama',   (0.1, 0.3)),
    ('mistral', (0.3, 0.9)),
]
_DEFAULT_PRICE = (1.0, 3.0)

ALERT_RATIO = 0.80  # 80% → alert


def is_enabled():
    try:
        from aot.databases.models import AIGlobalSettings
        s = AIGlobalSettings.query.first()
        return bool(s and getattr(s, 't3_budget_governance_enabled', False))
    except Exception as e:
        logger.debug(f"[BudgetService] flag read failed, defaulting off: {e}")
        return False


def _period():
    return datetime.now(timezone.utc).strftime('%Y-%m')


def _price_for(model_type, model_name):
    hay = f"{(model_name or '')} {(model_type or '')}".lower()
    for key, price in _PRICE_TABLE:
        if key in hay:
            return price
    return _DEFAULT_PRICE


def _estimate_cost(model_type, model_name, in_chars, out_chars):
    in_tok = (in_chars or 0) / 4.0
    out_tok = (out_chars or 0) / 4.0
    pin, pout = _price_for(model_type, model_name)
    return (in_tok / 1_000_000.0) * pin + (out_tok / 1_000_000.0) * pout


def record_usage(entry_unique_id, model_type, model_name, in_chars, out_chars):
    """Add one request's estimated cost to this month's meter for a connection.
    No-op when the flag is off. Never raises. After recording, checks the
    threshold and triggers enforcement if newly crossed."""
    try:
        if not is_enabled() or not entry_unique_id:
            return
        from aot.databases.models.ai import AIUsageMeter
        from aot.aot_flask.extensions import db

        cost = _estimate_cost(model_type, model_name, in_chars, out_chars)
        period = _period()
        row = AIUsageMeter.query.filter_by(entry_unique_id=entry_unique_id, period=period).first()
        if row is None:
            row = AIUsageMeter(entry_unique_id=entry_unique_id, period=period,
                               estimated_cost_usd=cost, request_count=1)
            db.session.add(row)
        else:
            row.estimated_cost_usd = (row.estimated_cost_usd or 0.0) + cost
            row.request_count = (row.request_count or 0) + 1
        db.session.commit()

        status = check_status(entry_unique_id)
        if status in ('over', 'stopped'):
            enforce(entry_unique_id, status)
    except Exception as e:
        logger.debug(f"[BudgetService] record_usage skipped: {e}")


def month_cost(entry_unique_id):
    """This month's estimated cost for a connection (0.0 if none)."""
    try:
        from aot.databases.models.ai import AIUsageMeter
        row = AIUsageMeter.query.filter_by(entry_unique_id=entry_unique_id, period=_period()).first()
        return row.estimated_cost_usd if row else 0.0
    except Exception:
        return 0.0


def check_status(entry_unique_id):
    """Return budget status for a connection:
      'ok'      < 80% of budget
      'alert'   ≥ 80% and < 100%
      'over'    ≥ 100%, soft-downgrade regime
      'stopped' ≥ 100% AND budget_hard_stop set
    Returns 'disabled' when the flag is off."""
    try:
        if not is_enabled():
            return 'disabled'
        from aot.databases.models import AIGlobalSettings
        s = AIGlobalSettings.query.first()
        budget = float(getattr(s, 'budget_limit_usd', 0) or 0)
        if budget <= 0:
            return 'ok'  # no cap set
        cost = month_cost(entry_unique_id)
        ratio = cost / budget
        if ratio >= 1.0:
            return 'stopped' if getattr(s, 'budget_hard_stop', False) else 'over'
        if ratio >= ALERT_RATIO:
            return 'alert'
        return 'ok'
    except Exception as e:
        logger.debug(f"[BudgetService] check_status failed: {e}")
        return 'ok'


def is_hard_stopped(entry_unique_id):
    """True if this connection is at/over budget with hard-stop enabled — the
    dispatch gate consults this to block new AI work until next month."""
    return check_status(entry_unique_id) == 'stopped'


def cheapest_model_on_entry(entry):
    """Pick the cheapest model available on a connection. Prefers the entry's
    engine AI_INFORMATION.models (the models the key can actually use); falls
    back to the entry's own model_name. Returns a model_name string or None."""
    try:
        from aot.ai.services.ai_agent_service import AIAgentService
        info = AIAgentService.get_engine_info(entry.model_type) or {}
        models = [m.get('value') for m in info.get('models', []) if m.get('value')]
        if not models:
            return entry.model_name
        return min(models, key=lambda mn: sum(_price_for(entry.model_type, mn)))
    except Exception:
        return getattr(entry, 'model_name', None)


def enforce(entry_unique_id, status):
    """Apply the budget decision. 'over' → rebind every role to the cheapest
    conformant model on this connection (soft-downgrade). 'stopped' → the
    dispatch gate (is_hard_stopped) blocks work; no rebind needed. Returns the
    action taken."""
    try:
        from aot.databases.models.ai import AIEntry
        entry = AIEntry.query.filter_by(unique_id=entry_unique_id).first()
        if not entry:
            return 'no_entry'
        if status == 'stopped':
            logger.warning(f"[BudgetService] '{entry.name}' at hard-stop — AI work blocked until next month.")
            return 'hard_stopped'
        if status == 'over':
            cheap = cheapest_model_on_entry(entry)
            from aot.ai.services.role_binder import autobind_all_roles
            autobind_all_roles(entry_unique_id, cheapest_model=cheap)
            logger.warning(f"[BudgetService] '{entry.name}' over budget — downgraded all roles to cheapest model '{cheap}'.")
            return f'downgraded:{cheap}'
        return 'noop'
    except Exception as e:
        logger.debug(f"[BudgetService] enforce failed: {e}")
        return 'error'
