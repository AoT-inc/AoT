# coding=utf-8
"""
Google Calendar two-way sync — category-routed multi-calendar (Phase C+D).

The user's design: AoT events split by category into separate Google calendars
so they stay visually distinct and personal events never mix in:
    automated_fire → "AoT · AI"      (ai)
    human          → "AoT · 사용자"   (user)
    control_output → "AoT · 장치"     (device)

Content round-trips via a structured 키:값 format (aot/utils/calendar_event_format.py)
written into each event's description on push and parsed back on pull — so
editing content/location/device/state in Google reflects into AoT.

Direction rules (deliberate, not symmetric):
  - PUSH: every pushable AoT job goes out to ITS category's calendar, carrying
    the structured field block.
  - PULL-CREATE (a brand-new Google event becomes a new AoT job): from the
    'user' AND 'device' calendars (NOT 'ai' — the AI authors its own jobs). The
    parsed fields decide the type: a resolvable '장치' ⇒ a control_output job
    created as DRAFT / approval-required (it stays inert until a human approves
    it in AoT — only approval registers the executing trigger, so a Google event
    never silently fires a device); otherwise a human task (PENDING, never fires).
  - PULL-EDIT / PULL-CANCEL (reschedule/re-content or delete of a previously
    linked event): from ALL category calendars, matched by aot_job_id / link.

Conflict model: last-write-wins on each side's mtime vs the per-link
high-water mark (CalendarEventLink.last_synced_at). Each Google calendar carries
its own incremental syncToken (stored in connection.category_calendars).

NOTE: cannot be exercised without live Google credentials + a connected account
with the category calendars created; written to the documented API contracts.
"""
import contextlib
import json as _json
import logging
from datetime import datetime, timezone, timedelta

from aot.databases.models import db
from aot.databases.models.calendar_integration import UserCalendarConnection, CalendarEventLink
from aot.databases.models.scheduler import SchedulerJobMeta, ScheduleType
from aot.utils import google_oauth, google_calendar_api
from aot.utils.time_utils import utc_now

logger = logging.getLogger("aot.calendar_sync")

_PUSHABLE_STATES = ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')
_DEFAULT_DURATION_MIN = 30

# (category key, Google calendar display name, allow pull-create?)
# device now allows create too — with the structured '장치/상태' format a Google
# event carries enough to build a control job, BUT it's created as DRAFT
# (approval-required) so a human confirms the physical action in AoT before it
# fires. AI stays create-off (the AI authors its own jobs; only edits sync back).
_CATEGORY_DEFS = [
    ('ai', 'AoT · AI', False),
    ('user', 'AoT · 사용자', True),
    ('device', 'AoT · 장치', True),
]
_CATEGORY_KEYS = [c[0] for c in _CATEGORY_DEFS]


def _category_for_action(action_type):
    # Single canonical mapping (shared with the widget picker + event feed).
    from aot.utils.calendar_event_providers import action_category
    return action_category(action_type)


# --- time helpers (project convention: naive datetimes are UTC) --------------
def _naive_utc_to_rfc3339(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _rfc3339_to_naive_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --- token -------------------------------------------------------------------
def get_valid_access_token(connection):
    now = utc_now().replace(tzinfo=None)
    token = connection.get_access_token()
    if token and connection.token_expiry and connection.token_expiry > now:
        return token
    result = google_oauth.refresh_access_token(connection.get_refresh_token())
    if result.get('error'):
        connection.last_sync_status = 'error'
        connection.last_sync_error = "token refresh: {}".format(result['error'])
        db.session.commit()
        logger.warning("[CalendarSync] token refresh failed for connection %s: %s",
                       connection.id, result['error'])
        return None
    connection.set_access_token(result['access_token'])
    connection.token_expiry = datetime.fromtimestamp(result['expires_at'], tz=timezone.utc).replace(tzinfo=None)
    db.session.commit()
    return result['access_token']


# --- per-category calendars --------------------------------------------------
def ensure_category_calendars(connection, access_token):
    """Create any missing category calendar in Google and record its id. Returns
    the category_calendars dict, or None if a creation failed."""
    cc = dict(connection.category_calendars or {})
    changed = False
    for key, summary, _allow in _CATEGORY_DEFS:
        entry = cc.get(key) or {}
        if not entry.get('calendar_id'):
            data, err = google_calendar_api.create_calendar(access_token, summary)
            if err:
                logger.warning("[CalendarSync] create_calendar '%s' failed: %s", summary, err)
                return None
            entry = {'calendar_id': data.get('id'), 'sync_token': None}
            cc[key] = entry
            changed = True
    if changed:
        connection.category_calendars = cc   # reassign so SQLAlchemy tracks the JSON change
        db.session.commit()
    return cc


# --- field mapping -----------------------------------------------------------
def _entity_name(model_names, target_id):
    """Resolve an entity's display name from unique_id across the given models.
    Returns None if unresolved."""
    if not target_id or target_id == 'none':
        return None
    try:
        from aot.databases import models as _m
        for mn in model_names:
            model = getattr(_m, mn, None)
            if model is None:
                continue
            row = model.query.filter_by(unique_id=target_id).first()
            if row is not None:
                return row.name
    except Exception:
        pass
    return None


def _output_name(target_id):
    return _entity_name(['Output'], target_id) or (target_id if target_id and target_id != 'none' else None)


def _job_event_body(job):
    """Serialize a job to a Google event using the shared structured format
    (aot/utils/calendar_event_format.py), so its content round-trips when a user
    edits it in Google. Shape depends on action_type: device on/off/value
    (장치/상태/값/지속), PID setpoint (PID/목표값), function trigger (함수/실행),
    human/AI (장소/내용/담당)."""
    from aot.tools.aot_data_tool_service import AoTDataToolService
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils import calendar_event_format as fmt
    import json as _j

    try:
        params = _j.loads(job.params_json) if job.params_json else {}
    except Exception:
        params = {}
    at = job.action_type

    if at == 'pid':
        pid_name = params.get('target_name') or _entity_name(['PID'], job.target_id)
        setting = params.get('setting', 'setpoint')
        value = params.get('value')
        summary = fmt.format_job_summary('pid', pid=pid_name, setting=setting, value=value, setpoint=value)
        description = fmt.format_job_description('pid', pid=pid_name, setting=setting, value=value, setpoint=value)
    elif at == 'function':
        fn_name = params.get('target_name') or _entity_name(['Function', 'Trigger', 'Conditional', 'CustomController'], job.target_id)
        summary = fmt.format_job_summary('function', function=fn_name)
        description = fmt.format_job_description('function', function=fn_name)
    elif at in ('activate', 'deactivate'):
        tgt = params.get('target_name') or _entity_name(
            ['Input', 'Conditional', 'Trigger', 'PID', 'CustomController'], job.target_id)
        summary = fmt.format_job_summary(at, target=tgt)
        description = fmt.format_job_description(at, target=tgt)
    elif at == 'control_output':
        device_name = params.get('target_name') or _output_name(job.target_id)
        if params.get('state') == 'set_value':
            value = params.get('value')
            summary = fmt.format_job_summary('device', device=device_name, value=value)
            description = fmt.format_job_description('device', device=device_name, value=value)
        else:
            state = params.get('state')
            duration_min = params.get('duration_minutes') or (job.duration_sec // 60 if job.duration_sec else None)
            summary = fmt.format_job_summary('device', device=device_name, state=state)
            description = fmt.format_job_description('device', device=device_name, state=state, duration_min=duration_min)
    else:
        cat = 'user'
        try:
            s = AoTDataToolService._schedule_summary(job)
        except Exception:
            s = {'content': job.reasoning or job.action_type, 'location': None, 'worker': None}
        summary = fmt.format_job_summary(cat, content=s.get('content'), location=s.get('location'))
        description = fmt.format_job_description(cat, content=s.get('content'),
                                                location=s.get('location'), worker=s.get('worker'))

    start = job.schedule_time
    end = job.end_time or (start + timedelta(minutes=_DEFAULT_DURATION_MIN) if start else None)
    tz = resolve_location_tz(job.target_id)
    tz_name = str(tz) if tz is not None else 'UTC'
    return google_calendar_api.build_event_body(
        summary=summary, description=description,
        start_iso=_naive_utc_to_rfc3339(start), end_iso=_naive_utc_to_rfc3339(end),
        time_zone=tz_name, aot_job_id=job.id)


# --- PUSH (AoT → Google), routed by category ---------------------------------
def push_connection(connection, access_token, cc):
    stats = {'inserted': 0, 'updated': 0, 'deleted': 0, 'errors': 0}
    links = {l.job_id: l for l in CalendarEventLink.query.filter_by(connection_id=connection.id).all()}

    jobs = (SchedulerJobMeta.query
            .filter(SchedulerJobMeta.state.in_(_PUSHABLE_STATES))
            .filter(SchedulerJobMeta.schedule_time.isnot(None))
            .filter((SchedulerJobMeta.source_type.is_(None)) |
                    (SchedulerJobMeta.source_type != 'google_calendar'))
            .all())
    pushable_ids = set()

    for job in jobs:
        pushable_ids.add(job.id)
        category = _category_for_action(job.action_type)
        cal_id = (cc.get(category) or {}).get('calendar_id')
        if not cal_id:
            stats['errors'] += 1
            continue
        body = _job_event_body(job)
        link = links.get(job.id)
        if link is None:
            data, err = google_calendar_api.insert_event(access_token, cal_id, body)
            if err:
                stats['errors'] += 1
                continue
            link = CalendarEventLink(
                connection_id=connection.id, job_id=job.id,
                google_event_id=data.get('id'), google_calendar_id=cal_id,
                google_etag=data.get('etag'), origin='aot')
            db.session.add(link)
            link.last_synced_at = utc_now().replace(tzinfo=None)
            stats['inserted'] += 1
        else:
            job_mtime = job.last_edited_at or job.created_at
            if link.last_synced_at and job_mtime and job_mtime <= link.last_synced_at:
                continue
            target_cal = link.google_calendar_id or cal_id
            data, err = google_calendar_api.update_event(access_token, target_cal, link.google_event_id, body)
            if err == 'not_found':
                data, err = google_calendar_api.insert_event(access_token, cal_id, body)
                if not err:
                    link.google_event_id = data.get('id')
                    link.google_calendar_id = cal_id
            if err:
                stats['errors'] += 1
                continue
            link.google_etag = data.get('etag')
            link.last_synced_at = utc_now().replace(tzinfo=None)
            stats['updated'] += 1

    # Delete remote events whose AoT job is no longer pushable (origin='aot' only).
    for job_id, link in list(links.items()):
        if job_id in pushable_ids or link.origin != 'aot':
            continue
        target_cal = link.google_calendar_id or (cc.get('user') or {}).get('calendar_id')
        if not target_cal:
            continue
        _data, err = google_calendar_api.delete_event(access_token, target_cal, link.google_event_id)
        if err:
            stats['errors'] += 1
            continue
        db.session.delete(link)
        stats['deleted'] += 1

    db.session.commit()
    return stats


# --- PULL (Google → AoT), per-category calendar ------------------------------
def _resolve_target_by_name(name):
    """Resolve a 장치/장소 name to (target_id, target_type, resolved_name).
    Device-aware: tries an Output device FIRST (exact/partial), then falls back
    to the zone/note resolver — so 'valve1' links to the Output, not a shape
    that happens to fuzzy-match. Returns (None, None, None) if nothing solid."""
    if not name:
        return (None, None, None)
    try:
        # 이름이 겹치면 고르지 않는다 — 여기서 잘못 엮이면 캘린더의 한 줄이
        # 영구히 엉뚱한 장치에 붙는다(이 링크는 이후 동기화에서 재사용된다).
        from aot.services.resolvers.device_resolver import resolve_output
        match = resolve_output(name, allow_partial=True)
        if match.error:
            logger.warning("[CalendarSync] %s", match.error)
            return (None, None, None)
        if match.row is not None:
            return (match.row.unique_id, 'output', match.row.name)
    except Exception:
        pass
    try:
        from aot.tools.aot_data_tool_service import AoTDataToolService
        tid, ttype, rname, _lat, _lng = AoTDataToolService._resolve_note_target(name)
        # Only accept an EXACT name match here — partial zone matches are exactly
        # what corrupted a device link before (밸브1 → a shape named '1').
        if tid and rname and _norm_name(rname) == _norm_name(name):
            return (tid, ttype, rname)
    except Exception:
        pass
    return (None, None, None)


def _norm_name(s):
    return ''.join(str(s).split()).lower()


def _resolve_activatable(name):
    """Resolve an Input/Conditional/Trigger/PID/CustomController by unique_id or
    name (for activate/deactivate). Returns (unique_id, type_label, name) or None."""
    if not name:
        return None
    try:
        from sqlalchemy import or_
        from aot.databases.models import Input
        from aot.databases.models.function import Conditional, Trigger
        from aot.databases.models.controller import CustomController
        from aot.databases.models.pid import PID
        for model, label in ((Conditional, 'Conditional'), (Trigger, 'Trigger'),
                             (PID, 'PID'), (CustomController, 'Function'), (Input, 'Input')):
            row = (model.query.filter(or_(model.unique_id == name, model.name == name)).first()
                   or model.query.filter(model.name.ilike('%{}%'.format(name))).first())
            if row is not None:
                return (row.unique_id, label, row.name)
    except Exception:
        pass
    return None


def _apply_google_event_to_job(job, event, allow_relink=False):
    """Apply a Google event's structured fields back onto an AoT job (content
    round-trip). Time/content/worker/state/duration always follow. The target
    (device/zone) is re-linked ONLY when allow_relink=True (Google-origin events
    the user owns) AND the name actually changed — never for AoT-origin pushed
    events, whose target_id is authoritative on the AoT side. Re-linking our own
    pushes by fuzzy name previously corrupted a valve link to a shape named '1'."""
    from aot.utils import calendar_event_format as fmt

    fields = fmt.parse_event_fields(event.get('summary') or '',
                                    (event.get('description') or ''))
    start = _rfc3339_to_naive_utc((event.get('start') or {}).get('dateTime')
                                  or (event.get('start') or {}).get('date'))
    end = _rfc3339_to_naive_utc((event.get('end') or {}).get('dateTime')
                                or (event.get('end') or {}).get('date'))
    try:
        params = _json.loads(job.params_json) if job.params_json else {}
    except Exception:
        params = {}

    if 'content' in fields:
        params['content'] = fields['content']
    if 'worker' in fields:
        params['worker'] = fields['worker']
    if 'state' in fields:
        params['state'] = fields['state']
    if fields.get('duration'):
        params['duration_minutes'] = fields['duration']
    # value / PID setpoint edits round-trip too.
    if fields.get('setpoint') is not None:
        params['setting'] = 'setpoint'
        params['value'] = fields['setpoint']
    elif fields.get('value') is not None:
        params['value'] = fields['value']
        if fields.get('setting'):
            from aot.utils import calendar_event_format as _f
            params['setting'] = _f.normalize_pid_setting(fields['setting'])

    if allow_relink:
        name = fields.get('device') or fields.get('location') or fields.get('pid') or fields.get('function')
        cur = params.get('target_name')
        if name and _norm_name(name) != _norm_name(cur or ''):
            tid, ttype, rname = _resolve_target_by_name(name)
            if tid:
                job.target_id = tid
                params['target_type'] = ttype
                params['target_name'] = rname

    job.params_json = _json.dumps(params)
    if start:
        job.schedule_time = start
    if end:
        job.end_time = end
        if start:
            job.duration_sec = int((end - start).total_seconds())
    elif fields.get('duration') and start:
        job.duration_sec = fields['duration'] * 60
        job.end_time = start + timedelta(minutes=fields['duration'])
    job.last_edited_at = utc_now().replace(tzinfo=None)
    job.last_edited_by = 'HUMAN'


def _connection_owner(connection):
    """연결 주인의 `User` 행. 못 찾으면 None."""
    try:
        from aot.databases.models import User
        return User.query.get(connection.user_id)
    except Exception:
        logger.exception("[CalendarSync] 연결 주인 조회 실패")
        return None


@contextlib.contextmanager
def _acting_as_owner(owner):
    """가져오기 동안의 쓰기를 **연결 주인**으로 묶는다.

    달력 가져오기는 주기 작업(사람 없는 스레드)이나 주인 자신의 "지금 동기화"
    에서 돈다. 묶지 않으면 쓰기 시점 강제(`write_scope.enforce`)가 "사람이
    없는 호출" 로 보고 아무것도 막지 않는다 — 그래서 예전에는 가져온 사람
    작업이 역할·그룹 판정 없이 PENDING 으로 들어왔다. 예약 발화와 같은 방식
    (요청자 표지 + `acting_as`)으로 묶는다.
    """
    from aot.ai import ai_request_context as _ai_ctx
    from aot.aot_flask.access import write_scope
    prev = _ai_ctx.set_requester(_ai_ctx.Requester(owner.unique_id))
    try:
        with write_scope.acting_as(owner.unique_id,
                                   tool='google_calendar_import'):
            yield
    finally:
        _ai_ctx.restore_requester(prev)


def _job_params(job):
    try:
        params = _json.loads(job.params_json) if job.params_json else {}
    except Exception:
        params = {}
    return params if isinstance(params, dict) else {}


def _job_import_denial(owner, job):
    """연결 주인이 이 예약 행을 들이거나·고치거나·보관할 수 있는가.

    막으면 사유, 되면 None. 스케줄러 화면의 만들기(`job_denial` — 실제로 돌
    도구의 역할과 그룹 스코프)와, 처리기의 쓰기 시점 강제(`write_scope.
    enforce` — 구역은 담은 시설·지도로)를 **둘 다** 본다. 판정이 깨지면
    막는다(모르면 좁게).
    """
    if owner is None:
        return 'a connection owner is required'
    from aot.ai.services.ai_scheduler_service import AISchedulerService
    from aot.aot_flask.access import write_scope
    try:
        denial = AISchedulerService.job_denial(
            owner, job.action_type, job.target_id, _job_params(job))
        if denial:
            return denial
        write_scope.enforce(job)
    except write_scope.WriteScopeDenied:
        return write_scope.deny_message()
    except Exception:
        logger.exception("[CalendarSync] 가져오기 권한 판정 실패 — 막는다")
        return 'permission check failed'
    return None


_JOB_EDIT_FIELDS = ('target_id', 'params_json', 'schedule_time', 'end_time',
                    'duration_sec', 'last_edited_at', 'last_edited_by')


def _apply_if_allowed(owner, job, event, allow_relink):
    """구글에서 고친 내용을 예약에 옮기되, 주인이 **고치기 전 대상과 고친 뒤
    대상 둘 다** 쓸 수 있을 때만. 옮겼으면 True.

    앞만 보면 그룹 밖 대상으로 다시 연결(relink)하는 편집이 지나가고, 뒤만
    보면 그룹 밖 예약의 시각·내용을 바꾸는 편집이 지나간다.
    """
    from aot.aot_flask.access import write_scope
    if _job_import_denial(owner, job):
        return False
    before = {f: getattr(job, f) for f in _JOB_EDIT_FIELDS}
    try:
        _apply_google_event_to_job(job, event, allow_relink=allow_relink)
        allowed = not _job_import_denial(owner, job)
    except write_scope.WriteScopeDenied:
        # 대상 이름을 푸는 리졸버가 쓰기 시점 강제로 막았다.
        allowed = False
    if not allowed:
        for f, v in before.items():
            setattr(job, f, v)
    return allowed


def pull_connection(connection, access_token, cc):
    stats = {'imported': 0, 'updated': 0, 'cancelled': 0, 'errors': 0,
             'refused': 0}
    owner = _connection_owner(connection)
    if owner is None or not pull_allowed(connection):
        # sync_connection 이 먼저 거르지만, 이 함수를 곧바로 부르는 길도 같은
        # 문을 지나게 한다.
        stats['skipped'] = 'permission'
        return stats
    links_by_event = {l.google_event_id: l
                      for l in CalendarEventLink.query.filter_by(connection_id=connection.id).all()}

    cc = dict(cc)
    with _acting_as_owner(owner):
        for key, _summary, allow_create in _CATEGORY_DEFS:
            entry = dict(cc.get(key) or {})
            cal_id = entry.get('calendar_id')
            if not cal_id:
                continue
            new_token = _pull_one_calendar(connection, access_token, cal_id,
                                           entry.get('sync_token'), allow_create,
                                           links_by_event, stats, owner=owner)
            if new_token:
                entry['sync_token'] = new_token
                cc[key] = entry

    if stats['refused']:
        # 일정 하나가 막혔다고 동기화 전체를 실패로 두지 않는다 — 막힌 것만
        # 건너뛰고 몇 건인지 알린다.
        logger.warning("[CalendarSync] %d event(s) skipped — the connection "
                       "owner cannot change their target", stats['refused'])
    connection.category_calendars = cc
    db.session.commit()
    return stats


def _pull_one_calendar(connection, access_token, cal_id, sync_token, allow_create,
                       links_by_event, stats, owner=None):
    time_min = None
    if not sync_token:
        time_min = _naive_utc_to_rfc3339((utc_now() - timedelta(days=30)).replace(tzinfo=None))
    page_token = None
    new_sync_token = None
    guard = 0
    from aot.aot_flask.access import write_scope
    while True:
        guard += 1
        if guard > 50:
            break
        data, err = google_calendar_api.list_events(
            access_token, cal_id, sync_token=sync_token, time_min=time_min, page_token=page_token)
        if err == 'sync_token_expired':
            sync_token = None
            time_min = _naive_utc_to_rfc3339((utc_now() - timedelta(days=30)).replace(tzinfo=None))
            continue
        if err:
            connection.last_sync_status = 'error'
            connection.last_sync_error = "pull[{}]: {}".format(cal_id, err)
            stats['errors'] += 1
            return None
        for event in data.get('items', []):
            try:
                _process_pulled_event(connection, cal_id, event, allow_create,
                                      links_by_event, stats, owner=owner)
            except write_scope.WriteScopeDenied:
                # 장치·장소 이름을 푸는 리졸버가 주인의 그룹 밖 대상을 막았다
                # (BaseException 이라 아래의 `except Exception` 들이 못 잡는다).
                # 그 일정만 건너뛴다 — 쓰기 전에 난 거부라 남은 변경이 없다.
                stats['refused'] += 1
        page_token = data.get('nextPageToken')
        new_sync_token = data.get('nextSyncToken') or new_sync_token
        if not page_token:
            break
    return new_sync_token


def _new_google_job(connection, action_type, target_id, params, start, end,
                    state='DRAFT', approval_required=True, reasoning='Imported from Google Calendar'):
    dur = int((end - start).total_seconds()) if (start and end) else 0
    if params.get('duration_minutes'):
        dur = int(params['duration_minutes']) * 60
    return SchedulerJobMeta(
        source_type='google_calendar', action_type=action_type, target_id=target_id,
        params_json=_json.dumps(params), schedule_time=start, end_time=end,
        duration_sec=dur, proposed_by='HUMAN', reasoning=reasoning,
        approval_required=approval_required, state=state, schedule_type=ScheduleType.human,
        is_editable=True, is_deletable=True, user_id=connection.user_id)


def _build_imported_job(connection, fields, event, start, end):
    """Decide the AoT job type from parsed structured fields and build it.
    Priority: PID setpoint → function trigger → device value/PWM → device on/off
    → human task. Control jobs are DRAFT (approval-required); a device name that
    doesn't resolve degrades to a labeled human reminder rather than being lost.
    Returns a SchedulerJobMeta (uncommitted) or None."""
    from aot.utils import calendar_event_format as fmt
    from aot.tools.aot_data_tool_service import AoTDataToolService
    from sqlalchemy import or_

    # --- Activate / deactivate an Input or controller ---
    for act_type in ('activate', 'deactivate'):
        if fields.get(act_type):
            ename = fields[act_type]
            ent = _resolve_activatable(ename)
            if ent is not None:
                params = {'target_type': ent[1], 'target_name': ent[2]}
                return _new_google_job(connection, act_type, ent[0], params, start, end,
                                       reasoning='Imported from Google Calendar ({} {} — awaiting approval)'.format(ent[2], act_type))
            # named but unresolved → human reminder rather than dropping it
            return _new_google_job(connection, 'human', 'none',
                                   {'content': '{}: {} (미해석)'.format(act_type, ename)},
                                   start, end, state='PENDING', approval_required=False)

    # --- PID setpoint / gain change ---
    if fields.get('pid') is not None or (fields.get('setpoint') is not None and not fields.get('device')):
        pid = None
        pname = fields.get('pid')
        if pname:
            try:
                from aot.databases.models import PID
                pid = (PID.query.filter(or_(PID.unique_id == pname, PID.name == pname)).first()
                       or PID.query.filter(PID.name.ilike('%{}%'.format(pname))).first())
            except Exception:
                pid = None
        if pid is not None:
            if fields.get('setpoint') is not None:
                setting, value = 'setpoint', fields['setpoint']
            else:
                setting = fmt.normalize_pid_setting(fields.get('setting', 'setpoint'))
                value = fields.get('value')
            if value is None:
                return None   # a PID change with no value is not actionable
            params = {'setting': setting, 'value': value, 'target_type': 'pid', 'target_name': pid.name}
            return _new_google_job(connection, 'pid', pid.unique_id, params, start, end,
                                   reasoning='Imported from Google Calendar (PID {} — awaiting approval)'.format(setting))

    # --- Function trigger once ---
    if fields.get('function'):
        fname = fields['function']
        fn = None
        try:
            from aot.databases.models import Function
            fn = (Function.query.filter(or_(Function.unique_id == fname, Function.name == fname)).first()
                  or Function.query.filter(Function.name.ilike('%{}%'.format(fname))).first())
        except Exception:
            fn = None
        if fn is not None:
            params = {'target_type': 'function', 'target_name': fn.name}
            return _new_google_job(connection, 'function', fn.unique_id, params, start, end,
                                   reasoning='Imported from Google Calendar (function trigger — awaiting approval)')

    # --- Device control (value/PWM or on/off) ---
    if fields.get('device'):
        output = None
        try:
            # 이름이 겹치면 예약을 만들지 않는다 — 나중에 사람이 지켜보지 않는
            # 시각에 실행되므로, 잘못 고르면 알아채기 어렵다.
            from aot.services.resolvers.device_resolver import resolve_output
            _m = resolve_output(fields['device'], allow_partial=True)
            if _m.error:
                logger.warning("[CalendarSync] %s", _m.error)
            output = _m.row
        except Exception:
            output = None
        if output is not None:
            if fields.get('value') is not None and not fields.get('state'):
                params = {'state': 'set_value', 'value': fields['value'],
                          'target_type': 'output', 'target_name': output.name,
                          'content': '{} = {}'.format(output.name, fields['value'])}
                return _new_google_job(connection, 'control_output', output.unique_id, params, start, end,
                                       reasoning='Imported from Google Calendar (output value — awaiting approval)')
            state = fields.get('state', 'on')
            duration = fields.get('duration', 5)
            params = {'state': state, 'duration_minutes': duration,
                      'target_type': 'output', 'target_name': output.name,
                      'content': fields.get('content') or '{} {}'.format(output.name, state)}
            return _new_google_job(connection, 'control_output', output.unique_id, params, start, end,
                                   reasoning='Imported from Google Calendar (device control — awaiting approval)')

    # --- Human task (fallback) ---
    content = fields.get('content') or (event.get('summary') or '(untitled)')
    if fields.get('device'):   # named a device but it didn't resolve
        content = '장치 제어(미해석): {} {}'.format(fields['device'], fields.get('state', '')).strip()
    params = {'content': content}
    if fields.get('worker'):
        params['worker'] = fields['worker']
    target_id = 'none'
    if fields.get('location'):
        try:
            tid, ttype, rname, _la, _lo = AoTDataToolService._resolve_note_target(fields['location'])
            if tid:
                target_id = tid
                params['target_type'] = ttype
                params['target_name'] = rname
            elif ttype == 'ambiguous':
                # 이름이 여러 곳에 걸렸다 — 고르지 않고 위치 없이 들이되, 그
                # 사실을 일정에 남겨 사람이 붙일 수 있게 한다(조용히 비우지 않는다).
                amb = AoTDataToolService._ambiguous_places(fields['location']) or []
                params['location_ambiguous'] = fields['location']
                params['location_candidates'] = [
                    c.get('use_name') or c.get('where') or c.get('name') for c in amb][:10]
                logger.warning("[CalendarSync] location '%s' matches %d places — "
                               "imported without a location", fields['location'], len(amb))
        except Exception:
            pass
    return _new_google_job(connection, 'human', target_id, params, start, end,
                           state='PENDING', approval_required=False,
                           reasoning='Imported from Google Calendar')


def _process_pulled_event(connection, cal_id, event, allow_create, links_by_event,
                          stats, owner=None):
    """구글 일정 하나를 AoT 예약에 반영한다.

    만들기·고치기·보관 모두 연결 주인(`owner`)이 그 예약을 쓸 수 있을 때만
    한다(`_job_import_denial`). 막힌 일정은 건너뛰고 `stats['refused']` 에
    센다 — 동기화 전체를 실패시키지 않는다.
    """
    if owner is None:
        owner = _connection_owner(connection)
    event_id = event.get('id')
    status = event.get('status')
    ext = ((event.get('extendedProperties') or {}).get('private') or {})
    aot_job_id = ext.get(google_calendar_api.AOT_JOB_ID_KEY)
    link = links_by_event.get(event_id)

    if status == 'cancelled':
        if link is not None:
            job = SchedulerJobMeta.query.get(link.job_id)
            if job is not None and link.origin == 'google' and job.state != 'ARCHIVED':
                if _job_import_denial(owner, job):
                    stats['refused'] += 1
                else:
                    job.state = 'ARCHIVED'
                    job.deletion_reason = 'Cancelled in Google Calendar'
                    stats['cancelled'] += 1
            db.session.delete(link)
        return

    event_updated = _rfc3339_to_naive_utc(event.get('updated'))

    # Event we previously pushed (carries our tag) → apply Google edit if newer.
    if aot_job_id:
        job = SchedulerJobMeta.query.get(int(aot_job_id)) if str(aot_job_id).isdigit() else None
        if job is None or link is None or not event_updated:
            return
        hw = link.last_synced_at
        job_mtime = job.last_edited_at or job.created_at
        if (hw is None or event_updated > hw) and (job_mtime is None or event_updated > job_mtime):
            # AoT-origin (our push): never re-link the target from the event —
            # target_id is authoritative on the AoT side.
            if not _apply_if_allowed(owner, job, event, allow_relink=False):
                stats['refused'] += 1
                return
            link.last_synced_at = utc_now().replace(tzinfo=None)
            link.google_etag = event.get('etag')
            stats['updated'] += 1
        return

    # Google-origin event already imported → update if newer (user owns it, so
    # a changed 장치/장소 may re-link — guarded by _resolve_target_by_name).
    if link is not None:
        job = SchedulerJobMeta.query.get(link.job_id)
        if job is not None and event_updated and (link.last_synced_at is None or event_updated > link.last_synced_at):
            if not _apply_if_allowed(owner, job, event,
                                     allow_relink=(link.origin == 'google')):
                stats['refused'] += 1
                return
            link.last_synced_at = utc_now().replace(tzinfo=None)
            link.google_etag = event.get('etag')
            stats['updated'] += 1
        return

    # Brand-new Google-origin event → create an AoT job (allow_create gates this;
    # AI calendar stays off). Type is decided by the parsed structured fields,
    # not the calendar. All control jobs are created DRAFT (approval-required) so
    # a human confirms in AoT before anything fires; human tasks are PENDING.
    if not allow_create:
        return
    from aot.utils import calendar_event_format as fmt

    start = _rfc3339_to_naive_utc((event.get('start') or {}).get('dateTime')
                                  or (event.get('start') or {}).get('date'))
    if start is None:
        return
    end = _rfc3339_to_naive_utc((event.get('end') or {}).get('dateTime')
                                or (event.get('end') or {}).get('date'))
    fields = fmt.parse_event_fields(event.get('summary') or '', event.get('description') or '')
    job = _build_imported_job(connection, fields, event, start, end)
    if job is None:
        return
    if _job_import_denial(owner, job):
        # 들이지 않는다. 링크도 남기지 않으므로 그 일정이 구글에서 다시
        # 고쳐지거나 전체 동기화가 돌면 그때 다시 판정한다.
        stats['refused'] += 1
        return
    db.session.add(job)
    db.session.flush()
    link = CalendarEventLink(
        connection_id=connection.id, job_id=job.id, google_event_id=event_id,
        google_calendar_id=cal_id, google_etag=event.get('etag'), origin='google')
    db.session.add(link)
    link.last_synced_at = utc_now().replace(tzinfo=None)
    links_by_event[event_id] = link
    stats['imported'] += 1


# --- orchestration -----------------------------------------------------------
def _connection_locale(connection):
    """The IANA-ish language code to render structured labels in — the
    connection owner's configured UI language (User.language), falling back to
    English (the system's base language)."""
    try:
        from aot.databases.models import User
        u = User.query.get(connection.user_id)
        if u and getattr(u, 'language', None):
            return str(u.language).strip()
    except Exception:
        pass
    return 'en'


def pull_allowed(connection):
    """이 연결의 주인이 구글 달력에서 예약을 들여올 수 있는 역할인가.

    가져오기는 사람 작업(`human`)과 제어 초안을 **그 주인 이름으로** 만들고,
    내보냈던 예약의 시각을 고치고, 취소된 일정을 보관으로 내린다 — 스케줄러
    화면과 같은 쓰기다. 그래서 같은 편집자 권한(`HUMAN_TASK_PERMISSION`)을
    요구한다. 연결은 자기 계정 동작이라 권한 문 없이 누구나 걸 수 있으므로,
    여기서 안 보면 보기 전용 계정이 달력으로 사람 작업을 만든다. 판정이
    깨지면 막는다(모르면 좁게). 내보내기(읽기 전용 사본)는 막지 않는다.
    """
    try:
        from aot.ai.services.ai_scheduler_service import HUMAN_TASK_PERMISSION
        from aot.databases.models import Role, User
        from aot.tools.mcp_auth import role_row_allows
        user = User.query.get(connection.user_id)
        if user is None or not getattr(user, 'is_enabled', False):
            return False
        role = Role.query.filter(Role.id == user.role_id).first()
        return role is not None and role_row_allows(role, HUMAN_TASK_PERMISSION)
    except Exception:
        logger.exception("[CalendarSync] 가져오기 권한 판정 실패 — 막는다")
        return False


def sync_connection(connection_id):
    connection = UserCalendarConnection.query.get(connection_id)
    if connection is None or not connection.is_active:
        return {"error": ["connection not found or inactive"]}
    if not google_oauth.is_configured():
        return {"error": ["Google OAuth not configured"]}
    token = get_valid_access_token(connection)
    if not token:
        return {"error": ["could not obtain access token"]}

    cc = ensure_category_calendars(connection, token)
    if cc is None:
        return {"error": ["could not create category calendars"]}

    # Render/parse the structured 키:값 labels in the owner's language. Both push
    # and pull run under the same forced locale so gettext writes and reads the
    # same wording (round-trip), while the parser's hardcoded synonym table still
    # accepts any other language a user might type.
    from contextlib import contextmanager
    try:
        from flask_babel import force_locale
    except Exception:
        @contextmanager
        def force_locale(_loc):
            yield

    result = {}
    try:
        with force_locale(_connection_locale(connection)):
            if connection.push_enabled:
                result['push'] = push_connection(connection, token, cc)
            if connection.pull_enabled and not pull_allowed(connection):
                # 보기 전용 역할 — 달력에서 예약을 만들거나 고치지 않는다.
                result['pull'] = {'skipped': 'permission',
                                  'requires': 'edit_controllers'}
            elif connection.pull_enabled:
                # push may have created calendars/links; reload the freshest cc
                result['pull'] = pull_connection(connection, token, connection.category_calendars or cc)
        connection.last_synced_at = utc_now().replace(tzinfo=None)
        connection.last_sync_status = 'ok'
        connection.last_sync_error = None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        connection.last_sync_status = 'error'
        connection.last_sync_error = str(exc)[:500]
        db.session.commit()
        logger.exception("[CalendarSync] sync failed for connection %s", connection_id)
        return {"error": [str(exc)]}
    return result
