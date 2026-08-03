# coding=utf-8
"""Shared gate fixtures for AI scheduler tests.

Both `AISchedulerService.init_app()` and the module-level scheduler jobs
(`_context_broadcast_job`, `_weather_summary_job`, …) refuse to do anything
until two preconditions hold:

  1. `AIGlobalSettings.ai_enabled` is true — read from the DB inside an
     application context. Any failure is swallowed and treated as "disabled",
     so a test that hands `init_app()` a bare mock app silently gets zero
     `add_job()` calls instead of an error.
  2. the module-level `_flask_app` is set — the jobs return immediately
     without it, since their whole body runs inside `_flask_app.app_context()`.

Tests that mock only the scheduler therefore observe nothing and, worse, the
ones written as "must not raise" pass vacuously. These helpers stand the gates
up so the behaviour under test actually runs.
"""
import contextlib
from unittest.mock import MagicMock, patch


def make_ai_settings(**overrides):
    """Build an AIGlobalSettings stub with every gate open unless overridden."""
    settings = MagicMock()
    settings.ai_enabled = True
    settings.context_broadcast_enabled = True
    for name, value in overrides.items():
        setattr(settings, name, value)
    return settings


@contextlib.contextmanager
def ai_enabled(**overrides):
    """Make `AIGlobalSettings.query.first()` return an enabled settings row.

    The production code imports the model inside the function body
    (`from aot.databases.models import AIGlobalSettings`), so the patch has to
    land on the source module rather than on any importer's namespace.
    """
    model = MagicMock()
    model.query.first.return_value = make_ai_settings(**overrides)
    with patch('aot.databases.models.AIGlobalSettings', model):
        yield model


@contextlib.contextmanager
def scheduler_flask_app():
    """Set `ai_scheduler_service._flask_app` to a stub with a no-op context.

    Restores the previous value on exit — `init_app()` assigns this global, so
    leaving it set leaks into unrelated test modules.
    """
    import aot.ai.services.ai_scheduler_service as sched_mod

    app = MagicMock()
    app.app_context.return_value.__enter__ = MagicMock(return_value=None)
    app.app_context.return_value.__exit__ = MagicMock(return_value=False)

    previous = sched_mod._flask_app
    sched_mod._flask_app = app
    try:
        yield app
    finally:
        sched_mod._flask_app = previous


@contextlib.contextmanager
def ai_scheduler_job_env(**overrides):
    """Both gates a module-level scheduler job has to clear before running."""
    with scheduler_flask_app() as app, ai_enabled(**overrides):
        yield app
