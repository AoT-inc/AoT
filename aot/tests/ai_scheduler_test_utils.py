# coding=utf-8
"""Shared gate fixtures for AI scheduler tests.

Both `AISchedulerService.init_app()` and the module-level scheduler jobs
(`_context_broadcast_job`, `_weather_summary_job`, …) refuse to do anything
until these preconditions hold:

  1. `AIGlobalSettings.ai_enabled` is true — read from the DB inside an
     application context. Any failure is swallowed and treated as "disabled",
     so a test that hands `init_app()` a bare mock app silently gets zero
     `add_job()` calls instead of an error.
  2. `AIGlobalSettings.ai_running` is true — the separate "작동 시작" switch on
     the AI page (see aot/ai/services/ai_runtime_state.py). Enabling the AI
     service no longer starts autonomous work by itself.
  3. at least one activated `AIAgent` exists, for the jobs that call a model.
     Without it there is nothing to ask, and the old code logged an ERROR every
     cycle instead of skipping.
  4. the module-level `_flask_app` is set — the jobs return immediately
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
    settings.ai_running = True
    settings.context_broadcast_enabled = True
    for name, value in overrides.items():
        setattr(settings, name, value)
    return settings


@contextlib.contextmanager
def ai_enabled(agent_count=1, **overrides):
    """Make `AIGlobalSettings.query.first()` return an enabled+started row.

    The production code imports the models inside the function body
    (`from aot.databases.models import AIGlobalSettings` / `AIAgent`), so the
    patches have to land on the source module rather than on any importer's
    namespace.

    `agent_count` stands up gate 3 (activated agents). Pass 0 to test the
    "AI started but no model registered" path — the jobs must skip quietly.
    """
    model = MagicMock()
    model.query.first.return_value = make_ai_settings(**overrides)
    agent_model = MagicMock()
    agent_model.query.filter_by.return_value.count.return_value = agent_count
    with patch('aot.databases.models.AIGlobalSettings', model), \
            patch('aot.databases.models.AIAgent', agent_model):
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
