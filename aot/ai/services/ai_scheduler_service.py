# coding=utf-8
"""
AISchedulerService - APScheduler integration for AI-driven task scheduling.

Manages the lifecycle of scheduled jobs including AI-proposed drafts,
human approval workflow, and persistent job storage via SQLAlchemyJobStore.
"""
import logging
import json
import re
import threading
import pytz
from datetime import datetime, timezone, timedelta
from aot.utils.time_utils import utc_now, get_local_now, to_local

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from aot.config import DATABASE_PATH
from aot.aot_flask.extensions import db
from aot.utils.execution_context import set_execution_context, clear_execution_context

logger = logging.getLogger(__name__)


# Scheduler DB is separate from main aot.db to avoid lock contention
SCHEDULER_DB_PATH = f'sqlite:///{DATABASE_PATH}/aot_scheduler.db'

# Job state constants
JOB_STATE_DRAFT = 'DRAFT'
JOB_STATE_PENDING = 'PENDING'
JOB_STATE_RUNNING = 'RUNNING'
JOB_STATE_COMPLETED = 'COMPLETED'
JOB_STATE_FAILED = 'FAILED'
JOB_STATE_ARCHIVED = 'ARCHIVED'

JOB_STATES = [
    JOB_STATE_DRAFT, JOB_STATE_PENDING, JOB_STATE_RUNNING,
    JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_ARCHIVED
]

# Singleton instances
_scheduler = None
_flask_app = None
_last_fired_at = {}  # For throttling: { 'trigger_id': timestamp }



def get_scheduler():
    """Return the global scheduler instance, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        import logging as _logging
        _logging.getLogger('apscheduler.executors').setLevel(_logging.WARNING)
        _scheduler = BackgroundScheduler(
            timezone=pytz.utc,  # APScheduler requires a pytz tz (has .localize/.normalize); stdlib timezone.utc is rejected
            # Explicit UTC — without this, APScheduler defaults to the OS/system-local
            # tz (tzlocal) for any naive datetime/cron field it's given. Storage
            # convention here is naive-UTC everywhere; tz_utils.py's docstring assumes
            # "Docker container timezone is always treated as UTC", but that's not
            # guaranteed (this dev box's OS tz is Asia/Seoul) — pin it instead of
            # hoping the OS matches, so a naive schedule_time is never misfired ~9h off.
            jobstores={
                'default': SQLAlchemyJobStore(url=SCHEDULER_DB_PATH)
            },
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300
            }
        )
        _scheduler.add_listener(_job_event_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        # 건너뛴 실행(misfire)도 들어야 한다. 예전에는 EXECUTED|ERROR 만 들어서,
        # 앱이 misfire_grace_time 보다 오래 내려가 있으면 그 예약은 **한 번도
        # 돌지 않고 조용히 사라졌다** — meta 행은 PENDING(1회성) 이나 직전 실행의
        # COMPLETED(반복) 로 남아 아무도 누락을 알아채지 못한다.
        _scheduler.add_listener(_job_missed_listener, EVENT_JOB_MISSED)
    return _scheduler


def _ai_scheduler_mcp_health_job():
    """Background job to check health of all activated MCP servers.

    Skipped unless AI background operation is active (ai_runtime_state
    .ai_background_active: AI enabled AND started AND at least one activated
    agent) — no AI code path can reach MCP tools otherwise, so probing servers
    (and keeping their subprocesses warm) is wasted work. Any live subprocesses
    are torn down on the transition so OFF means OFF.
    """
    from aot.ai.services.mcp_bridge_service import MCPBridgeService
    global _flask_app
    if not _flask_app:
        logger.error("[027_STEP_1] MCP health job called without _flask_app")
        return

    with _flask_app.app_context():
        try:
            from aot.ai.services import ai_runtime_state
            if not ai_runtime_state.ai_background_active():
                # Tear down any subprocesses left running from a prior ON window
                if getattr(MCPBridgeService, '_instances', None):
                    try:
                        MCPBridgeService.shutdown_all()
                        logger.debug(
                            "[027_STEP_1] %s — MCP bridge subprocesses shut down",
                            ai_runtime_state.background_skip_reason())
                    except Exception as _sd_err:
                        logger.warning(f"[027_STEP_1] MCP shutdown_all failed: {_sd_err}")
                return

            MCPBridgeService.health_check_all()
        except Exception as e:
            logger.error(f"[027_STEP_1] Error in MCP health check job: {e}")


# Last error reported per source, so a stuck one says it once instead of once
# per interval. { source_id: "joined error text" }
_context_sync_last_error = {}


def _prune_orphan_jobs(scheduler, prefix, live_ids, tag):
    """Drop per-entity jobs whose entity is no longer active.

    The jobstore is persistent, so deactivating a source/connection leaves its
    job behind. That used to be self-healing — the job noticed on its next fire
    and removed itself — but the runtime gate now returns *before* that check
    whenever AI is stopped, which is precisely when the job would otherwise sit
    there firing forever with nothing to do.
    """
    try:
        for job in scheduler.get_jobs():
            if not job.id.startswith(prefix):
                continue
            if job.id[len(prefix):] in live_ids:
                continue
            scheduler.remove_job(job.id)
            logger.info("%s Removed orphan job %s (entity inactive/deleted)", tag, job.id)
    except Exception as exc:
        logger.warning("%s Orphan job prune failed: %s", tag, exc)


# @ANCHOR: CONTEXT_SOURCE_SYNC_JOB_FUNC
def _context_source_sync_job(source_id):
    """
    Background job: sync a single AIContextSource by source_id.
    Runs inside Flask app context so DB and extensions are available.
    Delegates to sync_source() which handles last_synced_at / last_sync_status updates.

    Skipped unless AI autonomy is on (ai_runtime_state.ai_autonomy_enabled: AI
    enabled AND started). Pulling external data into the AI context is exactly
    the "AI works on its own" behaviour the start switch governs — no model is
    called, so ai_background_active (which also demands an agent) would be too
    strict.
    """
    global _flask_app
    if not _flask_app:
        logger.error("[ContextSourceSync] Job called without _flask_app, source_id=%s", source_id)
        return

    with _flask_app.app_context():
        try:
            from aot.ai.services import ai_runtime_state
            if not ai_runtime_state.ai_autonomy_enabled():
                logger.debug("[ContextSourceSync] %s — source_id=%s skipped",
                             ai_runtime_state.background_skip_reason(), source_id)
                return

            from aot.ai.services.context_source_service import sync_source
            messages = sync_source(source_id)
            if messages.get("error"):
                # Source gone/deactivated is an expected, self-healing condition — drop the
                # recurring job so it stops firing; log at INFO, not WARNING (was noise).
                if any("not found or inactive" in e for e in messages["error"]):
                    job_id = f'context_source_sync_{source_id}'
                    _context_sync_last_error.pop(source_id, None)
                    try:
                        get_scheduler().remove_job(job_id)
                        logger.info("[ContextSourceSync] Removed stale job %s (source inactive/deleted)", job_id)
                    except Exception:
                        pass
                else:
                    # Real sync failure — loud once. A misconfigured source (no
                    # file_path, no API key) fails identically every interval and
                    # will not fix itself; repeating it hourly buries the log
                    # without telling anyone anything new. A *changed* error is
                    # new information, so it gets its own warning.
                    text = '; '.join(messages["error"])
                    if _context_sync_last_error.get(source_id) == text:
                        logger.debug("[ContextSourceSync] source_id=%s still failing: %s",
                                     source_id, text)
                    else:
                        _context_sync_last_error[source_id] = text
                        logger.warning(
                            "[ContextSourceSync] source_id=%s errors: %s "
                            "(repeats logged at DEBUG until this changes)",
                            source_id, messages["error"])
            else:
                if _context_sync_last_error.pop(source_id, None):
                    logger.info("[ContextSourceSync] source_id=%s recovered", source_id)
                logger.debug("[ContextSourceSync] source_id=%s synced successfully", source_id)
        except Exception as exc:
            logger.exception("[ContextSourceSync] Unhandled error for source_id=%s: %s", source_id, exc)


# @ANCHOR: CALENDAR_SYNC_JOB_FUNC
def _calendar_sync_job(connection_id):
    """Background job: two-way sync one UserCalendarConnection (Google Calendar).
    Runs inside app context; delegates to calendar_sync_service.sync_connection
    which handles token refresh + last_synced_at/status.

    Skipped unless AI autonomy is on (ai_runtime_state.ai_autonomy_enabled: AI
    enabled AND started), same gate as the context-source sync: OFF means
    nothing in the AI scheduler moves on its own. Connecting a calendar does not
    by itself start the sync — the AI service has to be running too.
    """
    global _flask_app
    if not _flask_app:
        logger.error("[CalendarSync] Job called without _flask_app, connection_id=%s", connection_id)
        return
    with _flask_app.app_context():
        try:
            from aot.ai.services import ai_runtime_state
            if not ai_runtime_state.ai_autonomy_enabled():
                logger.debug("[CalendarSync] %s — connection_id=%s skipped",
                             ai_runtime_state.background_skip_reason(), connection_id)
                return

            from aot.ai.services.calendar_sync_service import sync_connection
            messages = sync_connection(connection_id)
            if messages.get("error"):
                if any("not found or inactive" in e for e in messages["error"]):
                    job_id = f'calendar_sync_{connection_id}'
                    try:
                        get_scheduler().remove_job(job_id)
                        logger.info("[CalendarSync] Removed stale job %s (connection inactive/deleted)", job_id)
                    except Exception:
                        pass
                else:
                    logger.warning("[CalendarSync] connection_id=%s errors: %s", connection_id, messages["error"])
            else:
                logger.debug("[CalendarSync] connection_id=%s synced: %s", connection_id, messages)
        except Exception as exc:
            logger.exception("[CalendarSync] Unhandled error for connection_id=%s: %s", connection_id, exc)


def ensure_calendar_sync_job(connection_id, interval_min=15, run_soon=True):
    """Register/refresh the per-connection Google Calendar sync job. Called on
    connect so a new link starts syncing without waiting for an app restart.
    run_soon schedules a first fire ~10s out for immediate feedback. Best-effort:
    a failure here is logged, not raised (the startup registration is the
    backstop)."""
    try:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        kwargs = dict(
            func=_calendar_sync_job,
            args=[connection_id],
            trigger='interval',
            minutes=max(1, int(interval_min or 15)),
            id=f'calendar_sync_{connection_id}',
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )
        if run_soon:
            kwargs['next_run_time'] = _dt.now(_tz.utc) + _td(seconds=10)
        get_scheduler().add_job(**kwargs)
        return True
    except Exception as exc:
        logger.warning("[CalendarSync] ensure_calendar_sync_job failed for %s: %s", connection_id, exc)
        return False


def remove_calendar_sync_job(connection_id):
    """Drop the per-connection sync job on disconnect. Best-effort."""
    try:
        get_scheduler().remove_job(f'calendar_sync_{connection_id}')
        return True
    except Exception:
        return False


# @ANCHOR: AI_SCHEDULER_WEATHER_SUMMARY  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_4]
def _weather_summary_job():
    """
    Background job: generate a structured Weather Summary Note every 6 hours.
    Stores result in Notes(category='ai_weather_summary') for instant context
    retrieval by the AI without triggering real-time data queries.
    """
    global _flask_app
    if not _flask_app:
        logger.error("[WeatherSummary] Job called without _flask_app")
        return

    with _flask_app.app_context():
        try:
            from aot.databases.models import Input, Notes
            from aot.ai.services.ai_doc_service import AiDocService
            from aot.ai.services.ai_action_service import AIActionService
            from aot.ai.services import ai_runtime_state
            from aot.aot_flask.extensions import db

            # Skip unless AI background operation is active — this job produces
            # AI output, so it has nothing to do without a started service and
            # at least one activated agent.
            if not ai_runtime_state.ai_background_active():
                logger.debug("[WeatherSummary] %s — skipping",
                             ai_runtime_state.background_skip_reason())
                return

            # 1. Identify weather-tagged input devices
            all_inputs = Input.query.filter_by(is_activated=True).all()
            weather_inputs = [
                inp for inp in all_inputs
                if AiDocService.classify_weather_device(inp.name, getattr(inp, 'notes', '') or '')
            ]

            if not weather_inputs:
                logger.debug("[WeatherSummary] No weather devices found. Skipping.")
                return

            # 2. Fetch latest reading for each weather device
            readings = []
            for inp in weather_inputs:
                try:
                    res = AIActionService.execute_action(
                        'virtual_tool_call',
                        'system_internal',
                        {
                            'server_id': 'system_internal',
                            'tool_name': 'get_sensor_detail',
                            'arguments': {'unique_id': inp.unique_id, 'limit': 1},
                        }
                    )
                    if res.get('status') == 'success':
                        readings.append({
                            'device': inp.name,
                            'unique_id': inp.unique_id,
                            'data': res.get('data') or res.get('result'),
                        })
                except Exception as _exc:
                    logger.debug("[WeatherSummary] Failed to fetch %s: %s", inp.unique_id, _exc)

            if not readings:
                logger.warning("[WeatherSummary] No readings retrieved from weather devices.")
                return

            # 3. Compose summary note
            summary_lines = [f"[Weather Summary] Generated: {get_local_now().strftime('%Y-%m-%d %H:%M')}"]
            for r in readings:
                summary_lines.append(f"  - {r['device']}: {r['data']}")
            summary_text = '\n'.join(summary_lines)

            # 4. Upsert: replace existing active summary to keep table lean
            existing = Notes.query.filter_by(
                category='ai_weather_summary', name='Weather Summary Note'
            ).first()
            if existing:
                existing.note = summary_text
            else:
                note = Notes(
                    name='Weather Summary Note',
                    note=summary_text,
                    category='ai_weather_summary',
                )
                db.session.add(note)
            db.session.commit()
            logger.info("[WeatherSummary] Summary updated with %d device(s).", len(readings))

        except Exception as exc:
            logger.error("[WeatherSummary] Job failed: %s", exc)


# @ANCHOR: REALTIME_ALERT_CHECK_JOB
# Per-scope cooldown tracker: scope_key -> last_alert datetime
_realtime_alert_last_sent: dict = {}
_realtime_alert_lock = threading.Lock()


def _realtime_alert_check_job() -> None:
    """
    Background job: lightweight, LLM-free threshold check for device anomalies.

    Runs every REALTIME_ALERT_CHECK_MINUTES (default 5 min).  Unlike the
    full context broadcast job this function never calls an AI model — it
    only evaluates rule-based thresholds via AIAnomalyDetector and pushes
    an SSE event if a violation is detected and the per-scope cooldown has
    expired.

    Call Hierarchy
    --------------
    AISummaryService.gather_scope_data(scope_type='system')
      ↓
    AIAnomalyDetector._check_threshold_violations(current_data, previous_summary=None)
      ↓  (if violations at warning/critical level)
    NotificationService.send_anomaly_alert(...)  → email to admins (if SMTP set)
    NotificationService.send_webui_toast(...)    → retired no-op since 2026-07-19
      (the in-app SSE toast path was removed; it held a gthread worker per tab
       and starved the pool. Deliver alerts via email / Conditional Functions.)

    Parent  : APScheduler (interval trigger, period = REALTIME_ALERT_CHECK_MINUTES)
              registered inside AISchedulerService.init_app()
    Children: AISummaryService.gather_scope_data()
              AIAnomalyDetector._check_threshold_violations()
              NotificationService.send_webui_toast()
    """
    global _flask_app, _realtime_alert_last_sent
    if not _flask_app:
        return

    with _flask_app.app_context():
        try:
            from aot.config.mcp_config import REALTIME_ALERT_COOLDOWN_MINUTES
            from aot.ai.services.ai_summary_service import AISummaryService
            from aot.ai.services.ai_anomaly_detector import AIAnomalyDetector
            from aot.ai.services.notification_service import NotificationService
            from aot.ai.services import ai_runtime_state
            from datetime import datetime, timezone

            # Skip unless the AI service has been started. This one gates on
            # ai_autonomy_enabled, not ai_background_active: the check is
            # rule-based and calls no model, so an empty agent roster is no
            # reason to stop alerting. What must stop it is the operator
            # deciding the AI service isn't running.
            if not ai_runtime_state.ai_autonomy_enabled():
                logger.debug("[RealtimeAlert] AI 자율 작동 꺼짐 — skipping")
                return

            current_data = AISummaryService.gather_scope_data('system', None)
            violations = AIAnomalyDetector._check_threshold_violations(current_data, None)
            if not violations:
                return

            level = AIAnomalyDetector._determine_alert_level(violations)
            if level not in ('warning', 'critical'):
                return

            scope_key = 'system:None'
            now = datetime.now(timezone.utc)
            with _realtime_alert_lock:
                last = _realtime_alert_last_sent.get(scope_key)
                if last is not None:
                    elapsed_minutes = (now - last).total_seconds() / 60
                    if elapsed_minutes < REALTIME_ALERT_COOLDOWN_MINUTES:
                        logger.debug(
                            "[RealtimeAlert] cooldown active (%.1f / %d min), skip",
                            elapsed_minutes, REALTIME_ALERT_COOLDOWN_MINUTES,
                        )
                        return
                _realtime_alert_last_sent[scope_key] = now

            first_msg = violations[0].get('message', 'Threshold exceeded')
            toast_level = 'error' if level == 'critical' else 'warning'
            NotificationService.send_webui_toast(
                user_id='__all__',
                message=f"[{level.upper()}] {first_msg}",
                level=toast_level,
                duration=8000 if level == 'critical' else 5000,
            )
            logger.warning("[RealtimeAlert] SSE pushed — %s: %s", level.upper(), first_msg)

        except Exception as exc:
            logger.error("[RealtimeAlert] Job failed: %s", exc, exc_info=True)


# @ANCHOR: CONTEXT_BROADCAST_JOB
def _context_broadcast_job() -> None:
    """
    Background job: build and broadcast a unified domain context snapshot
    to all active facilities on a configurable interval.

    Call Hierarchy (6-step sequence)
    ---------------------------------
    Step 1 — DomainContextLoader.get_all_active_facilities()
               Retrieve the list of facility IDs that have an active domain
               module registered in the facility registry.

    Step 2 — AIContextService.get_master_context(tier='standard')
               Fetch the current master context object (system-wide sensor
               readings, recent events, notes) used as the shared backdrop
               for all per-facility reasoning.

    Step 3 — DomainContextLoader.load_active_module(facility_id)
               For each facility returned in step 1, load its fully resolved
               domain module (YAML config + operational state).

    Step 4 — AISummaryService.get_summary_history(scope_type='facility', scope_id=facility_id, limit=CONTEXT_ACCUMULATION_DEPTH)
               Retrieve recent AI summary records up to
               CONTEXT_ACCUMULATION_DEPTH entries to provide temporal
               context for the reasoning engine.

    Step 5 — Forward the domain module into the summary prompt
               domain_module (crop/growth-stage/pest/weather, Step 3) is
               passed straight through as generate_system_summary's
               domain_context kwarg, which folds it into the same prompt as
               gather_scope_data's device/env_control data (see
               AISummaryService.generate_system_summary). master_context and
               summary_history are gathered above but NOT forwarded here —
               master_context is a system-wide capability snapshot with no
               facility-specific value for this prompt, and summary_history's
               deeper trend view beyond generate_system_summary's own
               get_latest_summary() call is a separate, not-yet-built
               improvement (see .local/plans/phase6_knowledge_digest_design.md
               multi-site addendum).

    Step 6 — AISummaryService.generate_system_summary(scope_type='facility', scope_id=facility_id, domain_context=domain_module)
               Persist the reasoning output as a new AISystemSummary record,
               making it available for future context retrieval cycles.

    Parent  : APScheduler (interval trigger, period = CONTEXT_BROADCAST_INTERVAL_HOURS)
              registered inside AISchedulerService.init_app()
    Children: DomainContextLoader.get_all_active_facilities()
              AIContextService.get_master_context(tier='standard')
              DomainContextLoader.load_active_module(facility_id)
              AISummaryService.get_summary_history(scope_type='facility', scope_id=facility_id, limit=CONTEXT_ACCUMULATION_DEPTH)
              AISummaryService.generate_system_summary(scope_type='facility', scope_id=facility_id, domain_context=domain_module)
    """
    global _flask_app
    if not _flask_app:
        logger.warning("[ContextBroadcast] _flask_app not set — skipping (no app context)")
        return

    # The entire job body must run inside an application context — get_master_context()
    # and the summary/domain queries below all touch the DB via Flask-SQLAlchemy.
    with _flask_app.app_context():
        from aot.ai.services import ai_runtime_state

        # Feature toggle check: skip unless AI background operation is active
        # (enabled AND started AND at least one activated agent), or when the
        # context-broadcast sub-toggle is off.
        _settings = ai_runtime_state.get_settings()
        if not ai_runtime_state.ai_background_active(_settings):
            logger.debug("[ContextBroadcast] %s — skipping",
                         ai_runtime_state.background_skip_reason(_settings))
            return
        if _settings.context_broadcast_enabled is False:
            logger.debug("[ContextBroadcast] Disabled via AI Settings — skipping")
            return

        from aot.ai.services.domain_context_loader import DomainContextLoader
        from aot.ai.services.ai_context_service import AIContextService
        from aot.ai.services.ai_summary_service import AISummaryService
        from aot.config.mcp_config import CONTEXT_ACCUMULATION_DEPTH

        try:
            # Step 1 — get all active facilities
            facilities = DomainContextLoader.get_all_active_facilities()
        except Exception as exc:
            logger.error("[ContextBroadcast] Step 1 failed: %s", exc)
            return

        try:
            # Step 2 — fetch master context once for all facilities
            master_context = AIContextService.get_master_context(tier='standard')
        except Exception as exc:
            logger.error("[ContextBroadcast] Step 2 failed: %s", exc)
            master_context = {}

        for facility_id in facilities:
            try:
                # Step 3 — load domain module for this facility
                domain_module = DomainContextLoader.load_active_module(facility_id)
            except Exception as exc:
                logger.error("[ContextBroadcast] Step 3 failed for %s: %s", facility_id, exc)
                continue

            try:
                # Step 4 — retrieve recent summary history
                summary_history = AISummaryService.get_summary_history(
                    scope_type='facility',
                    scope_id=facility_id,
                    limit=CONTEXT_ACCUMULATION_DEPTH,
                )
            except Exception as exc:
                logger.error("[ContextBroadcast] Step 4 failed for %s: %s", facility_id, exc)
                summary_history = []

            # Step 5 — domain_module (crop/growth-stage/pest/weather, Step 3) is
            # forwarded into the summary prompt below via domain_context.
            # master_context and summary_history are gathered but not
            # forwarded here — see the docstring's Step 5 note.
            _ = master_context, summary_history  # gathered above; not yet consumed (see docstring)

            try:
                # Step 6 — persist reasoning output as a new system summary
                AISummaryService.generate_system_summary(
                    scope_type='facility',
                    scope_id=facility_id,
                    domain_context=domain_module,
                )
            except Exception as exc:
                logger.error("[ContextBroadcast] Step 6 failed for %s: %s", facility_id, exc)


# @ANCHOR: TIER_RECLASSIFICATION_JOB
def _tier_reclassification_job() -> None:
    """
    Background job: periodic tier reclassification for adaptive document storage.

    Runs every hour (configurable via AdaptiveStorageSettings.reclassification_interval_hours).
    Queries documents due for tier evaluation, executes tier migration decisions,
    and logs all tier transition events.

    Call Hierarchy
    --------------
    Parent  : APScheduler (interval trigger, default 1 hour)
              registered inside AISchedulerService.init_app()
    Children: TierDecisionService.evaluate_and_log()
              TierMigrationService.migrate_document()

    @phase active
    """
    global _flask_app
    if not _flask_app:
        logger.warning("[TierReclassification] _flask_app not set — skipping job")
        return

    with _flask_app.app_context():
        try:
            from aot.ai.services.tier_decision_engine import TierDecisionEngine, TierDecisionService, TierMigrationService
            from aot.databases.models import Notes
            from aot.databases.models.tier_adaptive_storage import AdaptiveStorageSettings

            # Check if adaptive storage is enabled
            settings = AdaptiveStorageSettings.query.first()
            if not settings or not settings.enabled:
                logger.debug("[TierReclassification] Adaptive storage disabled — skipping job")
                return

            batch_size = settings.batch_size or 100

            # Get documents to evaluate (Notes model with tier field)
            documents = Notes.query.filter(
                Notes.is_archived == False
            ).limit(batch_size).all()

            evaluated = 0
            promotions = 0
            demotions = 0
            migrations = 0
            errors = 0

            for doc in documents:
                try:
                    # Determine current tier (default to 2 if not set)
                    current_tier = getattr(doc, 'tier', 2) or 2

                    # Evaluate tier
                    result = TierDecisionEngine.evaluate_tier(
                        document=doc,
                        access_history=None,  # TODO: pass actual access history
                        current_tier=current_tier,
                        document_type='notes'
                    )

                    # Log the decision
                    TierDecisionService.evaluate_and_log(
                        document=doc,
                        document_type='notes',
                        access_history=None,
                        current_tier=current_tier,
                        triggered_by='scheduled'
                    )

                    # Execute tier migration if needed
                    if result.should_promote and current_tier > 1:
                        target_tier = max(1, current_tier - 1)
                        migration_result = TierMigrationService.migrate_document(
                            document=doc,
                            target_tier=target_tier,
                            triggered_by='scheduled'
                        )
                        if migration_result['success']:
                            migrations += 1
                            promotions += 1

                    elif result.should_demote and current_tier < 3:
                        target_tier = min(3, current_tier + 1)
                        migration_result = TierMigrationService.migrate_document(
                            document=doc,
                            target_tier=target_tier,
                            triggered_by='scheduled'
                        )
                        if migration_result['success']:
                            migrations += 1
                            demotions += 1

                    evaluated += 1

                except Exception as doc_err:
                    logger.warning(f"[TierReclassification] Failed to evaluate doc {getattr(doc, 'unique_id', 'unknown')}: {doc_err}")
                    errors += 1

            logger.info(
                "[TierReclassification] Batch complete: evaluated=%d, migrations=%d, promotions=%d, demotions=%d, errors=%d",
                evaluated, migrations, promotions, demotions, errors
            )

        except Exception as exc:
            logger.error("[TierReclassification] Job failed: %s", exc, exc_info=True)


# @ANCHOR: AUDIT_LOG_PURGE_JOB
def _audit_log_purge_job() -> None:
    """Background job: drop audit_log rows past the retention period.

    Without this the audit table grows without bound. Retention defaults to
    config.AUDIT_LOG_RETENTION_DAYS (1 year — the minimum the personal-data
    safeguards standard requires for access records).

    Module-level (not a closure) because APScheduler has to be able to
    reference the function by qualified name.
    """
    global _flask_app
    if not _flask_app:
        logger.warning("[AuditLogPurge] _flask_app not set — skipping job")
        return

    with _flask_app.app_context():
        try:
            from aot.utils.audit import purge_old_audit_logs
            deleted = purge_old_audit_logs()
            if deleted:
                logger.info("[AuditLogPurge] Removed %d expired audit entries", deleted)
        except Exception as exc:
            logger.error("[AuditLogPurge] Job failed: %s", exc, exc_info=True)


def _job_event_listener(event):
    """Handle job execution results and update metadata."""
    from aot.ai.services.ai_scheduler_service import AISchedulerService, _flask_app
    if not _flask_app:
        logger.error("Job event listener called without _flask_app")
        return

    with _flask_app.app_context():
        try:
            if event.exception:
                logger.error(f"Job {event.job_id} failed: {event.exception}")
                AISchedulerService.update_job_state(event.job_id, JOB_STATE_FAILED,
                                                    execution_result=str(event.exception))
            else:
                # 예외가 없다고 실행된 것이 아니다. MCP 도구는 승인 게이트에 걸리면
                # 예외 대신 {"status":"pending_approval", ... "It was NOT executed"}
                # 를 정상 반환한다. 그걸 그대로 COMPLETED 로 적으면 **한 번도 켜지지
                # 않은 예약이 성공으로 기록**된다 — 2026-08-13 지도 위젯 예약 6건이
                # 전부 정시에 트리거되고도 장치를 켜지 못한 채 COMPLETED 였다.
                # 승인 큐에는 아무도 답할 수 없는 pending 확인요청만 쌓였다.
                _rv = event.retval
                _not_run = AISchedulerService._retval_indicates_not_executed(_rv)
                if _not_run:
                    logger.error("Job %s fired on time but did NOT execute: %s",
                                 event.job_id, _not_run)
                    AISchedulerService.update_job_state(
                        event.job_id, JOB_STATE_FAILED,
                        execution_result=f"NOT EXECUTED: {_not_run} | {_rv}")
                else:
                    logger.debug(f"Job {event.job_id} completed")
                    AISchedulerService.update_job_state(event.job_id, JOB_STATE_COMPLETED,
                                                        execution_result=str(_rv))
        except Exception as e:
            logger.exception(f"Error in job event listener for {event.job_id}: {e}")


def _job_missed_listener(event):
    """건너뛴 실행(EVENT_JOB_MISSED)을 눈에 보이는 실패로 남긴다.

    APScheduler 는 예정 시각이 misfire_grace_time 을 넘어서야 잡을 집으면
    실행하지 않고 이 이벤트만 낸다(앱이 내려가 있었거나, 잡스토어가 밀렸거나,
    같은 잡이 max_instances 로 겹쳤을 때). 아무도 듣지 않으면:
      - 1회성 예약: meta 는 PENDING 인 채로 영원히 남고 APScheduler 잡은 사라진다.
      - 반복(cron) 예약: 직전 성공의 COMPLETED 가 그대로 남아 **이번 회차가
        건너뛰어진 사실이 어디에도 없다.**
    두 경우 다 화면상 '문제 없음'으로 보이는 미실행이다.
    """
    from aot.ai.services.ai_scheduler_service import AISchedulerService, _flask_app
    if not _flask_app:
        logger.error("Job missed listener called without _flask_app")
        return
    with _flask_app.app_context():
        try:
            _when = getattr(event, 'scheduled_run_time', None)
            logger.error("Job %s MISSED its scheduled run at %s — it did NOT execute",
                         event.job_id, _when)
            AISchedulerService.update_job_state(
                event.job_id, JOB_STATE_FAILED,
                execution_result=(f"NOT EXECUTED: misfire — scheduled run at {_when} was "
                                  f"skipped (app down or past misfire_grace_time)"))
        except Exception as e:
            logger.exception(f"Error in job missed listener for {event.job_id}: {e}")


class AISchedulerService:
    """
    Service layer for managing scheduled jobs with Human-AI collaboration.
    Draft jobs proposed by AI require human approval before being promoted
    to PENDING state and actually scheduled in APScheduler.

    @phase active
    @stability stable
    @dependency SchedulerJobMeta
    """

    # 도구가 "실행하지 않았다" 고 말하는 응답을 판별한다.
    #
    # 예외를 던지지 않는 미실행이 여러 형태로 온다:
    #   - 승인 게이트: {"status":"pending_approval", "reason_code":"awaiting_user", ...}
    #   - 내부 오류를 감싼 성공: {"status":"success","result":{... "status":"error" ...}}
    # MCP 응답은 result.content[].text 안에 JSON 문자열이 한 겹 더 들어 있어서
    # 상위 status 만 보면 전부 success 로 보인다. 그래서 문자열까지 훑는다 —
    # 구조가 바뀌어도 조용히 통과하지 않는 쪽을 택한다(과소탐지보다 과대탐지).
    _NOT_RUN_MARKERS = (
        'pending_approval', 'awaiting_user', 'was NOT executed',
        'LEGACY_BLOCKED', 'requires_approval', 'not_executed',
        # 승인 게이트의 거부 어휘. gate() 는 승인 대기 말고도 여러 이유로
        # "실행하지 않음"을 돌려주는데, 그 응답에는 'pending_approval' 이 없다:
        #   insufficient_role · write_disabled · rate_limited · user_declined ·
        #   confirmation_expired/rejected/params_mismatch/already_used …
        # 전부 status='refused' 다. 이 줄들이 없으면 레이트 리밋에 걸린 예약이
        # 그대로 COMPLETED 로 기록된다.
        'insufficient_role', 'write_disabled', 'rate_limited', 'user_declined',
        'confirmation_not_found', 'confirmation_tool_mismatch',
        'confirmation_already_used', 'confirmation_rejected',
        'confirmation_expired', 'confirmation_params_mismatch',
        'needs_disambiguation',
    )

    # AoT MCP 서버가 **모든** tools/call 응답에 찍는 단일 판정 축
    # (mcp_safety_gate.CALL_STATES / aot_mcp_server._execute_tool).
    # 도구별 status 어휘(created/modified/placed…12종)를 몰라도 "이번 호출에서
    # 실제로 돌았는가"만 답한다. 문자열 마커보다 이쪽이 정본이다.
    _EXECUTED_CALL_STATES = frozenset({'executed', 'already_executed'})
    _CALL_STATE_RE = re.compile(r'["\']call_state["\']\s*:\s*["\']([a-z_]+)["\']')
    _IS_ERROR_RE = re.compile(r'["\']isError["\']\s*:\s*(?:True|true)')

    @staticmethod
    def _retval_indicates_not_executed(retval):
        """미실행으로 보이면 그 근거 문자열을, 정상 실행이면 None 을 돌려준다.

        판정 순서:
          1) 최상위 dict 의 status (호출 래퍼가 스스로 실패라고 말한 경우)
          2) 페이로드 어디에든 있는 call_state (MCP 응답의 정본 축)
          3) 문자열 마커 (구조를 못 알아본 경우의 그물)
        과소탐지보다 과대탐지를 택한다 — 안 켜진 예약을 성공으로 적는 쪽이
        훨씬 위험하다.
        """
        if retval is None:
            return None
        if isinstance(retval, dict):
            st = str(retval.get('status', '')).lower()
            if st in ('error', 'failed', 'blocked', 'pending_approval', 'refused'):
                return f"status={retval.get('status')}"
        blob = str(retval)
        for state in AISchedulerService._CALL_STATE_RE.findall(blob):
            if state not in AISchedulerService._EXECUTED_CALL_STATES:
                return f"call_state={state}"
        # MCP 표준 오류 플래그. MCPBridgeService.call_tool 은 이걸 읽지 않고
        # {"status":"success","result":{...}} 로 감싸므로, 서드파티 MCP 서버가
        # 도구 실행 실패를 규격대로 알려와도 바깥에서는 성공으로 보인다.
        if AISchedulerService._IS_ERROR_RE.search(blob):
            return 'isError=true'
        for mk in AISchedulerService._NOT_RUN_MARKERS:
            if mk.lower() in blob.lower():
                return mk
        return None

    @staticmethod
    def init_app(app):
        """Initialize the scheduler with Flask app context."""
        global _flask_app
        _flask_app = app

        scheduler = get_scheduler()
        if not scheduler.running:
            scheduler.start(paused=False)
            logger.debug("APScheduler started")

        # Register signal handlers regardless of AI enabled state
        from aot.utils.signals import trigger_fired, conditional_fired
        trigger_fired.connect(_on_trigger_fired)
        conditional_fired.connect(_on_conditional_fired)

        # AI jobs are only registered when AI is enabled
        with app.app_context():
            try:
                from aot.databases.models import AIGlobalSettings
                settings = AIGlobalSettings.query.first()
                ai_enabled = settings is not None and settings.ai_enabled
            except Exception:
                ai_enabled = False

        if not ai_enabled:
            logger.debug("AI disabled — AI scheduler jobs not registered")
            return

        # @ANCHOR: AI_SCHEDULER_MCP_HEALTH_CHECK
        try:
            scheduler.add_job(
                func=_ai_scheduler_mcp_health_job,
                trigger='interval',
                seconds=60,
                id='ai_scheduler_mcp_health',
                coalesce=True,
                max_instances=1,
                replace_existing=True
            )
        except Exception as _mcp_s1_err:
            logger.warning(f"[027_STEP_1] Could not register MCP health check: {_mcp_s1_err}")

        # @ANCHOR: AI_SCHEDULER_WEATHER_SUMMARY (registration site)
        try:
            scheduler.add_job(
                func=_weather_summary_job,
                trigger='interval',
                hours=6,
                id='ai_scheduler_weather_summary',
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
        except Exception as _ws_err:
            logger.warning("[WeatherSummary] Could not register weather summary job: %s", _ws_err)

        # @ANCHOR: CONTEXT_BROADCAST_JOB (registration site)
        try:
            from aot.config.mcp_config import CONTEXT_BROADCAST_INTERVAL_HOURS
            scheduler.add_job(
                func=_context_broadcast_job,
                trigger='interval',
                hours=CONTEXT_BROADCAST_INTERVAL_HOURS,
                id='ai_scheduler_context_broadcast',
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
        except Exception as _cb_err:
            logger.warning("[ContextBroadcast] Could not register context broadcast job: %s", _cb_err)

        # @ANCHOR: REALTIME_ALERT_CHECK_JOB (registration site)
        try:
            from aot.config.mcp_config import REALTIME_ALERT_CHECK_MINUTES
            scheduler.add_job(
                func=_realtime_alert_check_job,
                trigger='interval',
                minutes=REALTIME_ALERT_CHECK_MINUTES,
                id='ai_scheduler_realtime_alert_check',
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
        except Exception as _ra_err:
            logger.warning("[RealtimeAlert] Could not register realtime alert check job: %s", _ra_err)

        # @ANCHOR: CONTEXT_SOURCE_SYNC_JOBS (registration site)
        try:
            from aot.databases.models.ai_context_source import AIContextSource
            with app.app_context():
                active_sources = AIContextSource.query.filter_by(is_active=True).all()
            for source in active_sources:
                interval_min = source.sync_interval_min or 60
                if interval_min <= 0:
                    continue
                job_id = f'context_source_sync_{source.source_id}'
                scheduler.add_job(
                    func=_context_source_sync_job,
                    args=[str(source.source_id)],
                    trigger='interval',
                    minutes=interval_min,
                    id=job_id,
                    coalesce=True,
                    max_instances=1,
                    replace_existing=True,
                )
            _prune_orphan_jobs(
                scheduler, 'context_source_sync_',
                {str(s.source_id) for s in active_sources}, '[ContextSourceSync]')
        except Exception as _css_err:
            logger.warning("[ContextSourceSync] Could not register context source sync jobs: %s", _css_err)

        # @ANCHOR: CALENDAR_SYNC_JOBS (registration site)
        try:
            from aot.databases.models.calendar_integration import UserCalendarConnection
            with app.app_context():
                active_connections = UserCalendarConnection.query.filter_by(is_active=True).all()
            for conn in active_connections:
                interval_min = conn.sync_interval_min or 15
                if interval_min <= 0:
                    continue
                scheduler.add_job(
                    func=_calendar_sync_job,
                    args=[conn.id],
                    trigger='interval',
                    minutes=interval_min,
                    id=f'calendar_sync_{conn.id}',
                    coalesce=True,
                    max_instances=1,
                    replace_existing=True,
                )
            _prune_orphan_jobs(
                scheduler, 'calendar_sync_',
                {str(c.id) for c in active_connections}, '[CalendarSync]')
        except Exception as _cal_err:
            logger.warning("[CalendarSync] Could not register calendar sync jobs: %s", _cal_err)

        # @ANCHOR: TIER_RECLASSIFICATION_JOB (registration site)
        try:
            scheduler.add_job(
                func=_tier_reclassification_job,
                trigger='interval',
                hours=1,
                id='tier_reclassification',
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
        except Exception as _tr_err:
            logger.warning("[TierReclassification] Could not register tier reclassification job: %s", _tr_err)

        # @ANCHOR: AUDIT_LOG_PURGE_JOB (registration site)
        # Daily is plenty — retention is measured in days, so a finer interval
        # would just re-scan the table for nothing.
        try:
            scheduler.add_job(
                func=_audit_log_purge_job,
                trigger='interval',
                hours=24,
                id='audit_log_purge',
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
        except Exception as _ap_err:
            logger.warning("[AuditLogPurge] Could not register audit log purge job: %s", _ap_err)


    @staticmethod
    def trigger_context_broadcast_now() -> bool:
        """
        Reschedule the context broadcast job to run immediately.
        Called by anomaly detection when alert_level is 'warning' or 'critical'.

        Call Hierarchy
        --------------
        Parent  : AISummaryService.generate_system_summary() (OI-02 event trigger)
        Children: APScheduler _scheduler.get_job().modify()
        """
        # @ANCHOR: TRIGGER_CONTEXT_BROADCAST_NOW
        global _scheduler
        if not _scheduler:
            logger.warning("[ContextBroadcast] trigger_context_broadcast_now: _scheduler not initialized.")
            return False
        try:
            from datetime import datetime, timezone
            job = _scheduler.get_job('ai_scheduler_context_broadcast')
            if job:
                job.modify(next_run_time=datetime.now(timezone.utc))
                logger.info("[ContextBroadcast] Triggered immediately via anomaly event (OI-02).")
                return True
            logger.warning("[ContextBroadcast] trigger_context_broadcast_now: job not found.")
            return False
        except Exception as exc:
            logger.warning("[ContextBroadcast] Immediate trigger failed: %s", exc)
            return False

    @staticmethod
    def propose_job(action_type, target_id, params, reasoning,
                    schedule_time=None, schedule_cron=None, duration_sec=0,
                    proposed_by='AI', approval_required=True, priority=1, **kwargs):
        """
        Register a new job as DRAFT. Does NOT schedule in APScheduler yet.
        Commits the session. For atomic multi-model transactions use
        propose_job_no_commit() and commit externally.
        """
        meta = AISchedulerService.propose_job_no_commit(
            action_type, target_id, params, reasoning,
            schedule_time=schedule_time, schedule_cron=schedule_cron,
            duration_sec=duration_sec, proposed_by=proposed_by,
            approval_required=approval_required, priority=priority, **kwargs
        )
        db.session.commit()

        # If human-proposed and no approval needed, auto-promote
        if proposed_by == 'HUMAN' and not approval_required:
            return AISchedulerService.approve_job(meta.id)

        logger.info(f"Job proposed as DRAFT (id={meta.id}, by={proposed_by}): {reasoning[:80]}")
        return meta

    @staticmethod
    def propose_job_no_commit(action_type, target_id, params, reasoning,
                              schedule_time=None, schedule_cron=None, duration_sec=0,
                              proposed_by='AI', approval_required=True, priority=1, **kwargs):
        """
        Phase 5: no-commit variant of propose_job().
        Creates SchedulerJobMeta (state=DRAFT) and adds to session,
        but does NOT call db.session.commit(). The caller is responsible for
        committing (or rolling back) the session. flush() is NOT called here
        so the caller controls ID generation timing.
        Used by NotePromotionPipeline for atomic AITask + SchedulerJobMeta creation.
        Ref: 010_IMPLEMENTATION_PLAN.yaml C-2
        """
        from aot.databases.models.scheduler import SchedulerJobMeta

        # Calculate end_time if start time and duration are provided
        end_time = None
        if schedule_time and duration_sec > 0:
            end_time = schedule_time + timedelta(seconds=duration_sec)

        from aot.databases.models.scheduler import ScheduleType
        meta = SchedulerJobMeta(
            action_type=action_type,
            target_id=target_id,
            params_json=json.dumps(params) if isinstance(params, dict) else params,
            reasoning=reasoning,
            proposed_by=proposed_by,
            approval_required=approval_required,
            priority=priority,
            state=JOB_STATE_DRAFT,
            source_type=kwargs.get('source_type', 'scheduler'),
            schedule_time=schedule_time,
            duration_sec=duration_sec,
            end_time=end_time,
            schedule_cron=json.dumps(schedule_cron) if schedule_cron else None,
            schedule_type=kwargs.get('schedule_type', ScheduleType.ai_system),
            user_id=kwargs.get('user_id', None)
        )
        db.session.add(meta)
        return meta

    @staticmethod
    def approve_job(meta_id, adjusted_params=None, user_feedback=None, decided_by='HUMAN'):
        """
        Approve a DRAFT job → promote to PENDING and schedule in APScheduler.

        Args:
            meta_id: SchedulerJobMeta.id
            adjusted_params: optional dict to override original params
            user_feedback: optional human note about the approval
            decided_by: actor who approved ('HUMAN' or 'AI'). Default 'HUMAN'.
        Returns:
            updated SchedulerJobMeta

        Note: Jobs with action_type='human' are never scheduled in APScheduler —
        they represent human work items that require no automated execution.
        """
        from aot.databases.models.scheduler import SchedulerJobMeta

        meta = SchedulerJobMeta.query.get(meta_id)
        if not meta or meta.state != JOB_STATE_DRAFT:
            raise ValueError(f"Job {meta_id} is not in DRAFT state")

        if adjusted_params:
            meta.params_json = json.dumps(adjusted_params)
        if user_feedback:
            meta.user_feedback = user_feedback

        meta.state = JOB_STATE_PENDING
        meta.decided_at = utc_now()
        meta.decided_by = decided_by

        # Human-type jobs are reminder/calendar entries — no automated execution needed
        if meta.action_type == 'human':
            db.session.commit()
            logger.info(f"Job {meta_id} approved as human schedule (no APScheduler trigger)")
            AISchedulerService._log_audit(meta, 'APPROVED', user_feedback)
            return meta

        # Schedule the actual job in APScheduler
        scheduler = get_scheduler()
        job_kwargs = {
            'action_type': meta.action_type,
            'target_id': meta.target_id,
            'params': json.loads(meta.params_json),
            'meta_id': meta.id  # passed to _execute_scheduled_action for state update
        }

        if meta.schedule_time:
            # meta.schedule_time is naive-UTC (project storage convention). APScheduler
            # has no explicit timezone= configured, so it defaults to the SYSTEM-LOCAL tz
            # (Asia/Seoul on this box) for naive run_date values — that silently fired
            # jobs 9h off (or dropped them past misfire_grace_time) until this datetime
            # was made explicitly UTC-aware so APScheduler converts it correctly.
            run_date = meta.schedule_time
            if run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=timezone.utc)
            scheduler.add_job(
                _execute_scheduled_action,
                trigger='date',
                run_date=run_date,
                id=f'scheduler_meta_{meta.id}',
                kwargs=job_kwargs,
                misfire_grace_time=3600  # fire even if run_date was up to 1h ago
            )
        elif meta.schedule_cron:
            trigger_args = json.loads(meta.schedule_cron)
            trigger_type = trigger_args.pop('trigger', 'cron')

            # For recurring 'cron' schedules the hour/minute are wall-clock numbers in
            # the DEVICE'S local time (confirmed anchor policy). Hand the anchor tz to
            # APScheduler's CronTrigger via timezone= so it fires at that local
            # wall-clock AND follows DST — instead of freezing it to a fixed UTC hour
            # (drifts 1h across a DST boundary) or interpreting it in the system tz
            # (wrong for a device in another zone). (timezone-management.md §6)
            if trigger_type == 'cron':
                anchor_tz = None
                _name = getattr(meta, 'anchor_tz', None)
                if _name:
                    try:
                        anchor_tz = pytz.timezone(_name)
                    except Exception:
                        anchor_tz = None
                if anchor_tz is None:
                    try:
                        from aot.utils.device_tz import resolve_location_tz
                        _tid = meta.target_id
                        if meta.action_type == 'mcp_tool_call':
                            _args = (json.loads(meta.params_json) if meta.params_json else {}).get('arguments') or {}
                            _tid = _args.get('device_id') or _tid
                        anchor_tz = resolve_location_tz(_tid)  # pytz; falls back to system tz
                    except Exception:
                        anchor_tz = None
                if anchor_tz is not None:
                    trigger_args['timezone'] = anchor_tz

            scheduler.add_job(
                _execute_scheduled_action,
                trigger=trigger_type,
                id=f'scheduler_meta_{meta.id}',
                kwargs=job_kwargs,
                **trigger_args
            )
        else:
            # Immediate one-time execution
            scheduler.add_job(
                _execute_scheduled_action,
                id=f'scheduler_meta_{meta.id}',
                kwargs=job_kwargs
            )

        db.session.commit()
        logger.info(f"Job {meta_id} approved and scheduled")

        # Log to audit
        AISchedulerService._log_audit(meta, 'APPROVED', user_feedback)
        return meta

    @staticmethod
    def reject_job(meta_id, user_feedback=None):
        """
        Reject a DRAFT job → move to ARCHIVED.
        Stores rejection reason for AI feedback loop.
        """
        from aot.databases.models.scheduler import SchedulerJobMeta

        meta = SchedulerJobMeta.query.get(meta_id)
        if not meta or meta.state != JOB_STATE_DRAFT:
            raise ValueError(f"Job {meta_id} is not in DRAFT state")

        meta.state = JOB_STATE_ARCHIVED
        meta.user_feedback = user_feedback or ''
        meta.decided_at = utc_now()

        meta.decided_by = 'HUMAN'
        db.session.commit()

        # Store rejection as semantic context for AI learning
        AISchedulerService._store_feedback_as_note(meta, 'REJECTED', user_feedback)
        AISchedulerService._log_audit(meta, 'REJECTED', user_feedback)

        logger.info(f"Job {meta_id} rejected: {user_feedback}")
        return meta

    @staticmethod
    def update_job_state(job_id, new_state, execution_result=None):
        """Update job metadata state after execution events."""
        from aot.databases.models.scheduler import SchedulerJobMeta

        # job_id from APScheduler is 'scheduler_meta_{id}'
        if isinstance(job_id, str) and job_id.startswith('scheduler_meta_'):
            meta_id = int(job_id.replace('scheduler_meta_', ''))
        else:
            meta_id = job_id

        meta = SchedulerJobMeta.query.get(meta_id)
        if meta:
            meta.state = new_state
            if execution_result:
                meta.execution_result = execution_result[:2000]
            meta.executed_at = utc_now()

            db.session.commit()

    @staticmethod
    def get_jobs(state=None):
        """Get all jobs, optionally filtered by state."""
        from aot.databases.models.scheduler import SchedulerJobMeta
        query = SchedulerJobMeta.query.order_by(SchedulerJobMeta.created_at.desc())
        if state:
            query = query.filter_by(state=state)
        return query.all()

    @staticmethod
    def get_drafts():
        """Get all pending AI proposals awaiting human review."""
        return AISchedulerService.get_jobs(state=JOB_STATE_DRAFT)

    # @ANCHOR: SCHEDULE_CATEGORY_KEYWORDS — lightweight keyword classifier over
    # free-text schedule content, mirroring the existing pattern in
    # AiDocService.classify_weather_device. No schema change (no `category`
    # column on SchedulerJobMeta) — content stays free text, category is derived
    # on read for context-injection grouping only.
    _CATEGORY_KEYWORDS = (
        ('방제', ('방제', '농약', '살포', '병해충', '해충', '살균', '살충')),
        ('정식', ('정식', '이식', '아주심기', '육묘', '파종')),
        ('수확', ('수확', '채취', '따기')),
        ('출하', ('출하', '납품', '배송', '포장작업')),
        ('점검', ('점검', '진단', '확인', '체크')),
        ('청소', ('청소', '세척', '소독')),
        ('관수', ('관수', '급수', '물주기')),
    )

    @staticmethod
    def _classify_schedule_category(content: str) -> str:
        """Return a category label for schedule content, '기타' if no keyword matches."""
        text = (content or '')
        for label, keywords in AISchedulerService._CATEGORY_KEYWORDS:
            if any(kw in text for kw in keywords):
                return label
        return '기타'

    @staticmethod
    def get_schedule_horizon(days_ahead: int = 30, limit: int = 100) -> dict:
        """
        Return upcoming human-scheduled entries from SchedulerJobMeta, bucketed
        into a multi-layer horizon so the AI can reference near-term work in
        detail while staying aware of the month ahead without a token blowout.

        Queries rows where action_type='human', state in (PENDING, APPROVED),
        and schedule_time falls within the next `days_ahead` days (default 30),
        ordered by schedule_time ascending, capped at `limit` rows.

        Returns:
            dict: {
                'imminent':   list[dict] — next 48h, full detail
                'this_week':  list[dict] — 48h to 7 days, full detail
                'this_month': list[dict] — 7 to `days_ahead` days, full detail
                              (get_human_schedule_context summarizes this tier
                              as per-category counts to control context size)
                'truncated':  bool — True if `limit` rows were hit (more may exist
                              beyond `days_ahead` or within it but past the cap)
            }
            Each entry dict: {job_id, job_name, location, target_id,
            category, schedule_time (ISO 8601 UTC), user_id}.
            Returns all-empty-lists dict (never raises) on error.
        """
        # @ANCHOR: GET_SCHEDULE_HORIZON [2026-07-20 — replaces get_pending_human_schedules]
        empty = {'imminent': [], 'this_week': [], 'this_month': [], 'truncated': False}
        try:
            from aot.databases.models.scheduler import SchedulerJobMeta
            now = utc_now()
            week_cutoff = now + timedelta(hours=48)
            month_cutoff = now + timedelta(days=days_ahead)

            rows = (
                SchedulerJobMeta.query
                .filter(
                    SchedulerJobMeta.action_type == 'human',
                    SchedulerJobMeta.state.in_(['PENDING', 'APPROVED']),
                    SchedulerJobMeta.schedule_time >= now,
                    SchedulerJobMeta.schedule_time <= month_cutoff,
                )
                .order_by(SchedulerJobMeta.schedule_time.asc())
                .limit(limit + 1)  # fetch one extra to detect truncation
                .all()
            )

            truncated = len(rows) > limit
            rows = rows[:limit]

            result = {'imminent': [], 'this_week': [], 'this_month': [], 'truncated': truncated}
            for row in rows:
                # job_name/location from params (content + resolved location entity),
                # NOT target_id — target_id is the entity link (a uuid), unreadable as
                # a label. Location makes the future-reference context place-aware.
                try:
                    _p = json.loads(row.params_json) if row.params_json else {}
                except Exception:
                    _p = {}
                content = _p.get('content') or row.reasoning or 'work item'
                entry = {
                    'job_id': row.unique_id,
                    'job_name': content,
                    'location': _p.get('target_name') or None,
                    'target_id': row.target_id if row.target_id and row.target_id != 'none' else None,
                    'category': AISchedulerService._classify_schedule_category(content),
                    'user_id': row.user_id,
                }
                # schedule_time is stored naive (SQLite has no tz type); the project
                # convention is that a naive stored datetime IS UTC (see tz_utils.py).
                # Attach tzinfo BEFORE using it anywhere — both for the aware-cutoff
                # comparison below and for the returned isoformat string, so a bare
                # 'YYYY-MM-DDTHH:MM:SS' (no offset) is never handed to the LLM as if
                # it were local time (it isn't — it's UTC).
                row_time = row.schedule_time
                if row_time is not None and row_time.tzinfo is None:
                    row_time = row_time.replace(tzinfo=timezone.utc)
                entry['schedule_time'] = row_time.isoformat() if row_time else None

                if row_time is not None and row_time <= week_cutoff:
                    result['imminent'].append(entry)
                elif row_time is not None and row_time <= (now + timedelta(days=7)):
                    result['this_week'].append(entry)
                else:
                    result['this_month'].append(entry)
            return result
        except Exception:
            logger.exception("get_schedule_horizon: query failed")
            return empty

    @staticmethod
    def _log_audit(meta, decision, feedback=None):
        """Record decision in the audit log."""
        from aot.databases.models.scheduler import SchedulerAuditLog
        log = SchedulerAuditLog(
            job_meta_id=meta.id,
            actor='HUMAN',
            decision=decision,
            feedback=feedback or '',
            previous_state=JOB_STATE_DRAFT,
            new_state=meta.state
        )
        db.session.add(log)
        db.session.commit()

    @staticmethod
    def _store_feedback_as_note(meta, decision, feedback):
        """Store human feedback as a semantic note for AI context."""
        if not feedback:
            return
        try:
            from aot.databases.models import Notes
            note = Notes(
                name=f"Scheduler {decision}: {meta.action_type} on {meta.target_id}",
                note=f"[{decision}] {feedback}\nOriginal reasoning: {meta.reasoning}",
                category='ai_semantic'
            )
            db.session.add(note)
            db.session.commit()
            # --- EKG FEEDBACK WIRE (005_EDGE_OPTIMIZED_SPECIFICATION / Phase 5 C-4) ---
            try:
                from aot.ai.services.experience_knowledge_graph import EKGService
                from aot.databases.models.ekg import HumanNote
                EKGService.ingest([HumanNote.from_notes_row(note)])
            except Exception as _ekg_exc:
                logger.debug("[EKG] Feedback wire non-critical error: %s", _ekg_exc)
            # --- END EKG WIRE ---
        except Exception as e:
            logger.warning(f"Failed to store feedback as note: {e}")

def _execute_scheduled_action(action_type, target_id, params, meta_id=None):
    """
    Wrapper function called by APScheduler to execute an action.
    Routes through SafetyService validation before actual execution.
    _approved=True: this is a human-approved scheduled execution.
    """
    from aot.ai.services.ai_action_service import AIActionService
    from aot.ai.services.safety_service import SafetyService

    if not _flask_app:
        logger.error("Scheduled action called without _flask_app context")
        return {"status": "error", "message": "Missing app context"}

    with _flask_app.app_context():
        try:
            # Safety validation first
            SafetyService.validate(action_type, target_id, params)

            # Set execution context for the scheduled job
            set_execution_context(source_type='scheduler', source_id=target_id)
            try:
                # _approved=True: job was approved by human via approve_job(); bypass PC-089 gate.
                result = AIActionService.execute_action(action_type, target_id, params, _approved=True)
                logger.info(f"Scheduled action executed: {action_type} on {target_id} -> {result.get('status')}")
            finally:
                clear_execution_context()

            # Update SchedulerJobMeta state after execution.
            #
            # 최상위 status 만 보면 안 된다 — 승인 게이트에 걸린 MCP 호출은
            # {"status":"success","result":{...content[].text 안에 pending_approval...}}
            # 로 온다. _job_event_listener 가 나중에 같은 판정을 한 번 더 하지만,
            # 여기서도 같은 헬퍼를 쓰는 이유가 둘 있다: (1) 리스너가 어떤 이유로든
            # 못 돌면 이 값이 최종본이 되고, (2) 아래 500자 자르기가 근거를 잘라내지
            # 않도록 근거 문자열을 **맨 앞**에 붙여야 한다.
            if meta_id:
                import json as _json
                try:
                    _payload = _json.dumps(result, ensure_ascii=False, default=str)
                except Exception:
                    _payload = str(result)
                _not_run = AISchedulerService._retval_indicates_not_executed(result)
                if _not_run:
                    logger.error("Scheduled action %s on %s did NOT execute: %s",
                                 action_type, target_id, _not_run)
                    AISchedulerService.update_job_state(
                        meta_id, JOB_STATE_FAILED,
                        f"NOT EXECUTED: {_not_run} | {_payload}"[:2000])
                elif result.get('status') == 'success':
                    AISchedulerService.update_job_state(
                        meta_id, JOB_STATE_COMPLETED, _payload[:2000])
                else:
                    AISchedulerService.update_job_state(
                        meta_id, JOB_STATE_FAILED,
                        f"status={result.get('status')} | {_payload}"[:2000])

            return result

        except Exception as e:
            logger.exception(f"Error executing scheduled action {action_type} on {target_id}")
            if meta_id:
                try:
                    AISchedulerService.update_job_state(meta_id, JOB_STATE_FAILED, str(e)[:500])
                except Exception:
                    pass
            return {"status": "error", "message": str(e)}

def _on_trigger_fired(sender, **kwargs):
    """Signal handler for trigger_fired."""
    _handle_fired_event('trigger', kwargs.get('trigger_id'), kwargs.get('name'), kwargs.get('next_run'))

def _on_conditional_fired(sender, **kwargs):
    """Signal handler for conditional_fired."""
    _handle_fired_event('conditional', kwargs.get('conditional_id'), kwargs.get('name'), kwargs.get('next_run'))

def _handle_fired_event(source_type, source_id, name, next_run_epoch):
    """Common logic for handling automated fire events with throttling."""
    from aot.ai.services.ai_scheduler_service import _flask_app, _last_fired_at, AISchedulerService
    import time
    from datetime import datetime
    
    now = time.time()
    last_fire = _last_fired_at.get(source_id, 0)

    # Root cause fixed at the source: controller_conditional.py now only
    # sends conditional_fired when AbstractConditional.action_fired was set
    # this cycle (run_action()/run_all_actions() actually called), not on
    # every period tick — see project_scheduler_conditional_flood_incident
    # memory (41,000+ noise rows/month on aot-005 before this). This 5s
    # window is just a plain duplicate-delivery guard, not a volume cap.
    if now - last_fire < 5:
        return
        
    _last_fired_at[source_id] = now
    
    if not _flask_app:
        return

    with _flask_app.app_context():
        try:
            from aot.databases.models.scheduler import SchedulerJobMeta
            from aot.aot_flask.extensions import db
            
            # Record a completed "shadow" job for the timeline
            next_run = datetime.fromtimestamp(next_run_epoch, tz=timezone.utc) if next_run_epoch else None

            
            from aot.databases.models.scheduler import ScheduleType
            meta = SchedulerJobMeta(
                action_type='automated_fire',
                target_id=source_id,
                params_json='{}',
                reasoning=f"Automated execution of {source_type}: {name}",
                proposed_by='SYSTEM',
                approval_required=False,
                state='COMPLETED',
                source_type=source_type,
                executed_at=utc_now(),
                schedule_time=next_run,
                schedule_type=ScheduleType.ai_system,
                user_id=None
            )
            db.session.add(meta)
            db.session.commit()
            logger.debug(f"Recorded automated {source_type} firing for {source_id}")
        except Exception as e:
            logger.error(f"Failed to record automated fire event: {e}")
