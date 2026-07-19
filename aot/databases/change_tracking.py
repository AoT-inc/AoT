# coding=utf-8
"""
Change tracking for the AI system-knowledge layer (P3).

The system-knowledge snapshot (system_knowledge_service) is cached and rebuilt at
most once a day — cheap, but it would go STALE the moment the user adds/edits/
removes a device between rebuilds. That is exactly the failure the requirement
calls out: "user changed setting A, but the periodic learning is pre-change → the
AI answers about the old state."

Fix: register SQLAlchemy after_insert / after_update / after_delete listeners on
the configuration models. Any change flips the snapshot to dirty (with the change
time), so the very next AI answer rebuilds from current DB state and can even note
"last change <time>". The listeners are trivial (a flag flip) and never touch the
session, so they are safe to run inside the ORM flush.

Registered once at app start via register_change_listeners() (app.py), mirroring
device_tz_listeners.
"""
import logging

logger = logging.getLogger(__name__)

# Config models whose add/edit/remove changes what the user "has". Kept as name
# strings so a missing model (partial install) is skipped, not fatal.
_TRACKED_MODELS = (
    "Input", "Output", "Camera",
    "Function", "Conditional", "Trigger", "PID", "CustomController",
    "GeoShape", "GeoMap",
)

_registered = False


def _on_change(kind):
    def _handler(mapper, connection, target):
        try:
            from aot.ai.services import system_knowledge_service as sk
            name = type(target).__name__
            when = None
            try:
                from aot.utils.time_utils import get_local_now
                when = get_local_now().strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            sk.mark_dirty(change_note=f"{name} {kind}", when_iso=when)
        except Exception as e:  # never break the user's write
            logger.debug(f"[ChangeTracking] mark_dirty on {kind} failed: {e}")
    return _handler


def register_change_listeners():
    """Attach after_insert/update/delete → system-knowledge invalidation on all
    tracked config models. Idempotent; safe to call once at startup."""
    global _registered
    if _registered:
        return
    try:
        from sqlalchemy import event
        import aot.databases.models as models
        ins, upd, dele = _on_change("added"), _on_change("updated"), _on_change("removed")
        attached = []
        for name in _TRACKED_MODELS:
            Model = getattr(models, name, None)
            if Model is None:
                continue
            event.listen(Model, "after_insert", ins)
            event.listen(Model, "after_update", upd)
            event.listen(Model, "after_delete", dele)
            attached.append(name)
        _registered = True
        logger.info(f"[ChangeTracking] system-knowledge invalidation listeners attached to: {', '.join(attached)}")
    except Exception as e:
        logger.warning(f"[ChangeTracking] listener registration failed: {e}")
