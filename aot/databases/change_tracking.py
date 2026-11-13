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


def _on_change(kind, on_change):
    def _handler(mapper, connection, target):
        try:
            name = type(target).__name__
            when = None
            try:
                from aot.utils.timekit import to_tz, FARM, utc_now
                when = to_tz(utc_now(), FARM).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
            on_change(change_note=f"{name} {kind}", when_iso=when)
        except Exception as e:  # never break the user's write
            logger.debug(f"[ChangeTracking] mark_dirty on {kind} failed: {e}")
    return _handler


def register_change_listeners(on_change):
    """Attach after_insert/update/delete → ``on_change(change_note=, when_iso=)`` on all
    tracked config models. Idempotent; safe to call once at startup.

    아키텍처 7c: 모델 층이 AI 서비스를 직접 import 하지 않게, 무엇을 할지는 앱 팩토리가
    콜백으로 넘긴다. 필수 인자인 이유 — 빠뜨리면 AI 지식 갱신이 조용히 멈추므로
    호출 쪽이 TypeError 로 바로 드러나게 한다."""
    global _registered
    if _registered:
        return
    try:
        from sqlalchemy import event
        import aot.databases.models as models
        ins, upd, dele = (_on_change("added", on_change), _on_change("updated", on_change),
                          _on_change("removed", on_change))
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
