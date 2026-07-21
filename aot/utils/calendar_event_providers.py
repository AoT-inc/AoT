# coding=utf-8
"""
Calendar event provider registry — pure, framework-free adapters that turn a
data source into a common calendar-event shape for the /api/v1/scheduler/
calendar_events endpoint (aot/aot_flask/routes_scheduler.py) and the calendar
dashboard widget (aot/widgets/widget_calendar.py).

This module owns NO Flask (`request`/`jsonify`) or AI-tool concerns — it is a
plain (source_key -> normalized_event_list) registry, matching the style of
other framework-free helpers in this package (widgets.py, time_utils.py).

Only 'schedule' is implemented today. 'notice'/'note' are documented
extension points (see CALENDAR_EVENT_PROVIDERS below) — the widget's UI and
this registry are both designed so adding a new source later is additive
(new function + one registry line), not a redesign.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# @ANCHOR: SCHEDULE_CATEGORY_COLOR_MAP — deterministic action_type -> one of
# the 6 reactive --aot-chart-* tokens (aot-theme-variables.css), so widget CSS
# never has to hardcode a color per category; it just reads data-category.
_CATEGORY_COLOR_HINT = {
    'human': 'chart-1',
    'control_output': 'chart-6',
    'automated_fire': 'chart-3',
}
_DEFAULT_COLOR_HINT = 'chart-2'

# Job states shown on the calendar. ARCHIVED (cancelled/superseded) is
# deliberately excluded — a cancelled event cluttering a calendar view is
# noise, not signal (matches the scheduler page's own "History" vs "Active"
# split intent, though DRAFT/PENDING/RUNNING/COMPLETED/FAILED are all still
# calendar-relevant unlike the read-only /timeline endpoint's narrower set).
_CALENDAR_VISIBLE_STATES = ('DRAFT', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED')


def _parse_range_bound(value):
    """Parse a FullCalendar-supplied start/end query param (ISO 8601, usually
    with an offset) into a naive-UTC datetime — matching how schedule_time is
    stored (SQLite has no tz type; naive-stored == UTC by this project's own
    convention, see aot/utils/tz_utils.py). Returns None on missing/bad input
    so the caller can fall back to an open-ended bound rather than erroring."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def provide_schedule_events(start=None, end=None, limit=500):
    """Registered provider for source key 'schedule'. Queries SchedulerJobMeta
    with schedule_time in [start, end) (either bound optional — an unbounded
    query is still capped by `limit`), reuses
    AoTDataToolService._schedule_summary() for content/location resolution
    (same enrichment as _enrich_job_display in routes_scheduler.py — imported,
    not duplicated), and returns a list of normalized calendar-event dicts:

        {id, jobId, title, start, end, allDay, sourceType, category, state,
         colorHint, content, location, worker, rowEditable, rowDeletable, deepLink}

    `jobId` is the raw integer SchedulerJobMeta.id (not the `id` field's
    "schedule-<uuid>" DOM-safe string) — the widget's edit/delete UI needs it
    verbatim to call PUT/DELETE /api/v1/scheduler/jobs/<int:job_id>.
    `editable`/`deletable` mirror SchedulerJobMeta.is_editable/is_deletable —
    per-row flags, not just a permission check (e.g. an already-fired device
    command is correctly locked even for an editor).
    """
    from aot.databases.models.scheduler import SchedulerJobMeta
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.utils.time_utils import serialize_ts

    start_dt = _parse_range_bound(start)
    end_dt = _parse_range_bound(end)

    query = SchedulerJobMeta.query.filter(
        SchedulerJobMeta.state.in_(_CALENDAR_VISIBLE_STATES)
    )
    if start_dt is not None:
        query = query.filter(SchedulerJobMeta.schedule_time >= start_dt)
    if end_dt is not None:
        query = query.filter(SchedulerJobMeta.schedule_time < end_dt)
    # Rows with no schedule_time at all (rare, but action_type='human' rows
    # created without a time are possible) have nothing to place on a
    # calendar — exclude them here rather than letting them collapse onto
    # created_at, which would misrepresent "when" this is actually happening.
    query = query.filter(SchedulerJobMeta.schedule_time.isnot(None))

    rows = query.order_by(SchedulerJobMeta.schedule_time.asc()).limit(limit).all()

    events = []
    for row in rows:
        try:
            summary = AoTDataToolService._schedule_summary(row)
        except Exception:
            logger.exception("provide_schedule_events: _schedule_summary failed for job %s", row.id)
            continue

        title = summary['content']
        if summary['location']:
            title = f"{title} · {summary['location']}"

        end_iso = None
        if row.end_time is not None:
            end_iso = serialize_ts(row.end_time)

        events.append({
            'id': f"schedule-{row.unique_id}",
            'jobId': row.id,
            'title': title,
            'start': serialize_ts(row.schedule_time),
            'end': end_iso,
            'allDay': False,
            'sourceType': 'schedule',
            'category': row.action_type,
            'state': row.state,
            'colorHint': _CATEGORY_COLOR_HINT.get(row.action_type, _DEFAULT_COLOR_HINT),
            'content': summary['content'],
            'location': summary['location'],
            'worker': summary['worker'],
            # NOT named 'editable'/'deletable': FullCalendar reserves the
            # top-level 'editable' key for drag/resize interactivity — a
            # same-named field here gets consumed as THAT flag instead of
            # landing in extendedProps (the widget's Edit button silently
            # stopped rendering this way; caught in browser testing). Prefixed
            # to sidestep FullCalendar's whole reserved-key surface, not just
            # the one collision found so far.
            'rowEditable': summary['editable'],
            'rowDeletable': summary['deletable'],
            'deepLink': '/scheduler',
        })
    return events


# --- Extension points (not implemented in this MVP) ------------------------
# When implementing, register below AND add a matching `include_notice`/
# `include_note` bool to widget_calendar.py's custom_options (a toggle for a
# source with no registered provider is dead UI — see widget_calendar.py's
# own comment on why those options are deferred to this same PR).
#
# def provide_notice_events(start=None, end=None, limit=500):
#     """Adapt NoticePost rows (aot/databases/models/notice.py) — same fields
#     /notice/api/latest already serializes (see widget_notice.py). Map
#     post.date_time -> start (allDay=True), sourceType='notice',
#     deepLink='/notice'."""
#     raise NotImplementedError
#
# def provide_note_events(start=None, end=None, limit=500):
#     """Adapt Notes rows (aot/databases/models/notes.py). sourceType='note',
#     deepLink='/notes'."""
#     raise NotImplementedError

CALENDAR_EVENT_PROVIDERS = {
    'schedule': provide_schedule_events,
    # 'notice': provide_notice_events,  # uncomment when implemented
    # 'note': provide_note_events,
}
