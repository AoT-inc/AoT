# coding=utf-8
"""
SystemKnowledgeService — the AI's standing, authoritative picture of the user's
CONFIGURED system (registered devices, functions, zones), so it answers system
questions from LEARNED knowledge instead of re-investigating every request.

Why this exists (design, .local/plans/ai_system_knowledge_redesign.md):
  - Each UI page is a legacy, human-oriented screen. Having the AI "read the page
    like a user" (DOM scrape + live-data fetch) is slow and token-heavy, and it
    still misses the actual inventory — so the model fell back to reciting the
    'creatable_*' catalog (installable TYPES) as if it were the user's devices.
  - Instead, each DOMAIN summarizes ONLY what the AI needs, DIRECTLY from its DB
    models (deterministic, no LLM, no DOM). We aggregate those into one compact
    "SYSTEM KNOWLEDGE" block and inject it into the answering context.

Freshness (requirement ①): the aggregate is cached and rebuilt at most daily
(_TTL_SECONDS), OR immediately when the system changes — SystemKnowledgeService
.mark_dirty() is called by the device-change listeners (P3, change_tracking.py),
so an answer right after the user edits a device reflects the change, never a
stale pre-change snapshot.

All reads are best-effort and never raise — a provider failure degrades to a
partial block, never a broken prompt.

@phase active
@stability new
@dependency Input, Output, Camera, Function, Conditional, Trigger, PID,
            CustomController, GeoMap, GeoShape
"""
import logging
import threading

logger = logging.getLogger(__name__)

# Rebuild at most once/day unless invalidated by a change (requirement: ≥1x/day).
_TTL_SECONDS = 86400

# Per-domain item cap so the injected block stays compact on large installs.
_MAX_PER_DOMAIN = 80

_lock = threading.Lock()
_cache = {
    "text": None,        # rendered block
    "built_at": 0.0,     # epoch seconds of last build
    "dirty": True,       # set True by change listeners / on first use
    "last_change_at": None,  # ISO string of the most recent system change seen
    "counts": {},        # {domain: n}
}


def mark_dirty(change_note=None, when_iso=None):
    """Invalidate the cache so the next read rebuilds. Called by the device-change
    listeners (change_tracking.py) whenever an Input/Output/Function/zone is
    added, edited, or removed. Cheap and thread-safe; records when the change
    happened so the injected block can say 'last change <time>'."""
    with _lock:
        _cache["dirty"] = True
        if when_iso:
            _cache["last_change_at"] = when_iso
        if change_note:
            logger.debug(f"[SystemKnowledge] marked dirty: {change_note}")


def _now():
    """Epoch seconds. Isolated so time is easy to reason about / stub."""
    import time
    return time.time()


def _now_iso():
    try:
        from aot.utils.time_utils import get_local_now
        return get_local_now().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Per-domain providers — each reads ONLY its own models and returns a compact
# list of short strings. Deterministic, no LLM, no live-sensor / InfluxDB calls.
# ---------------------------------------------------------------------------

def _inputs():
    from aot.databases.models import Input
    rows = Input.query.limit(_MAX_PER_DOMAIN).all()
    out = []
    for r in rows:
        flag = "" if getattr(r, "is_activated", True) else " [inactive]"
        out.append(f"{(r.name or r.unique_id)} ({r.device}){flag}")
    return out, Input.query.count()


def _outputs():
    from aot.databases.models import Output
    rows = Output.query.limit(_MAX_PER_DOMAIN).all()
    out = []
    for r in rows:
        out.append(f"{(r.name or r.unique_id)} ({getattr(r, 'output_type', '') or 'output'})")
    return out, Output.query.count()


def _cameras():
    try:
        from aot.databases.models import Camera
        rows = Camera.query.filter_by(is_activated=True).limit(_MAX_PER_DOMAIN).all()
        return [f"{(r.name or r.unique_id)} ({getattr(r, 'camera_type', '') or 'camera'})" for r in rows], len(rows)
    except Exception:
        return [], 0


def _functions():
    """PID / Conditional / Trigger / CustomController / Function, labelled by kind."""
    items = []
    total = 0
    specs = [
        ("PID", "PID", None),
        ("Conditional", "Conditional", None),
        ("Trigger", "Trigger", "trigger_type"),
        ("Custom", "CustomController", None),
        ("Function", "Function", "function_type"),
    ]
    for label, model_name, type_attr in specs:
        try:
            import aot.databases.models as _m
            Model = getattr(_m, model_name, None)
            if Model is None:
                continue
            rows = Model.query.limit(_MAX_PER_DOMAIN).all()
            total += Model.query.count()
            for r in rows:
                nm = getattr(r, "name", None) or getattr(r, "unique_id", "?")
                tp = f":{getattr(r, type_attr)}" if (type_attr and getattr(r, type_attr, None)) else ""
                act = "" if getattr(r, "is_activated", True) else " [inactive]"
                items.append(f"[{label}{tp}] {nm}{act}")
        except Exception as e:
            logger.debug(f"[SystemKnowledge] function provider {model_name} skipped: {e}")
    return items, total


def _zones():
    """Farms (GeoMap) that actually contain zones, with their zone names. A GeoMap
    is auto-created per device/function (dozens of empty 'X Map' rows), so we skip
    maps with no zones — only real, zoned farms are useful to the AI."""
    try:
        from aot.databases.models import GeoMap, GeoShape
        out = []
        for gm in GeoMap.query.all():
            zones = []
            for s in GeoShape.query.filter_by(geo_id=gm.unique_id, type='zone').limit(_MAX_PER_DOMAIN).all():
                try:
                    zones.append((s.feature or {}).get('properties', {}).get('name') or 'Unnamed')
                except Exception:
                    zones.append('Unnamed')
            if zones:  # skip the auto-created empty per-device maps
                out.append(f"{gm.name}: {', '.join(zones)}")
        return out, len(out)
    except Exception as e:
        logger.debug(f"[SystemKnowledge] zone provider skipped: {e}")
        return [], 0


def _render():
    """Build the compact SYSTEM KNOWLEDGE block from all providers. Never raises."""
    sections = []
    counts = {}

    def add(title, provider):
        try:
            items, total = provider()
        except Exception as e:
            logger.debug(f"[SystemKnowledge] provider '{title}' failed: {e}")
            items, total = [], 0
        counts[title] = total
        if not items:
            sections.append(f"{title} (0): (none registered)")
            return
        shown = "; ".join(items)
        more = f" … (+{total - len(items)} more)" if total > len(items) else ""
        sections.append(f"{title} ({total}): {shown}{more}")

    add("Inputs (sensors/data sources)", _inputs)
    add("Outputs (actuators)", _outputs)
    add("Cameras", _cameras)
    add("Functions/Automation", _functions)
    add("Farms/Zones", _zones)

    built = _now_iso()
    last_change = _cache.get("last_change_at")
    header = (
        f"[SYSTEM KNOWLEDGE — the user's ACTUAL registered system, built {built}"
        + (f"; last change {last_change}" if last_change else "")
        + "]\n"
        "This is the authoritative inventory of what the user HAS. Answer "
        "\"what do I have / list my devices / 장치·함수·구역 목록\" directly from THIS, "
        "in the user's language. Do NOT recite 'creatable_*' (those are installable "
        "TYPES, not registered devices) and do NOT re-investigate when the answer is here.\n"
    )
    return header + "\n".join(f"- {s}" for s in sections) + "\n", counts


def get_knowledge_text(force=False):
    """Return the cached SYSTEM KNOWLEDGE block, rebuilding if stale (>TTL) or
    dirty (a system change happened) or forced. Cheap on the hot path: a hit is a
    dict read. Returns '' on total failure (never breaks prompt assembly)."""
    try:
        with _lock:
            fresh = (
                _cache["text"] is not None
                and not _cache["dirty"]
                and (_now() - _cache["built_at"]) < _TTL_SECONDS
            )
            if fresh and not force:
                return _cache["text"]
        # Build outside the lock (DB reads can be slow); then publish.
        text, counts = _render()
        with _lock:
            _cache["text"] = text
            _cache["built_at"] = _now()
            _cache["dirty"] = False
            _cache["counts"] = counts
        return text
    except Exception as e:
        logger.warning(f"[SystemKnowledge] get_knowledge_text failed: {e}")
        return _cache.get("text") or ""


def get_inventory_answer():
    """A user-facing rendering of the inventory — the section lines WITHOUT the
    AI-instruction header. Used as a deterministic fallback answer for inventory
    questions when the LLM meta-stalls ("I'll fetch the list…") instead of just
    listing what is already in front of it. Guarantees the user gets the real
    inventory. '' if nothing is registered."""
    text = get_knowledge_text()
    if not text:
        return ""
    # Drop the leading instruction header (everything up to the first "- " line).
    idx = text.find("\n- ")
    body = text[idx + 1:] if idx != -1 else text
    return body.strip()


def get_status():
    """Diagnostics: current cache state (for debugging / a future admin view)."""
    with _lock:
        return {
            "built_at": _cache["built_at"],
            "dirty": _cache["dirty"],
            "last_change_at": _cache["last_change_at"],
            "counts": dict(_cache["counts"]),
            "age_seconds": (_now() - _cache["built_at"]) if _cache["built_at"] else None,
        }
