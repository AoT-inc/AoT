# coding=utf-8
"""
Scheduler routes - Page views and API endpoints for the collaborative scheduler.
"""
import json
import logging
from datetime import datetime, timezone

import flask_login
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required

from aot.databases.models import db, Misc, Output, OutputChannel, Input
from aot.utils.time_utils import serialize_ts, to_local
from aot.utils.timekit import iso_utc
from aot.databases.models.scheduler import SchedulerJobMeta, SchedulerAuditLog
from aot.ai.services.ai_scheduler_service import (
    AISchedulerService, JOB_STATE_DRAFT, JOB_STATE_PENDING,
    JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_ARCHIVED
)
from aot.aot_flask.utils.utils_general import current_user_id
from aot.aot_flask.utils.utils_general import user_has_permission

logger = logging.getLogger(__name__)
blueprint = Blueprint('routes_scheduler', __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

def _resolve_target_name(target_id):
    """Best-effort id→name lookup for CARD/MODAL DISPLAY ONLY (not the AI-facing
    name→id resolver — that's AoTDataToolService._resolve_note_target). Tries
    GeoShape (zone/site/facility) first, then Output/Input. Returns None if the
    id is empty/'none' or nothing matches — caller falls back to a neutral label,
    never a raw UUID (that's the whole point: the card must never show one)."""
    if not target_id or target_id == 'none':
        return None
    try:
        import json as _json
        from aot.databases.models.geo import GeoShape
        shape = GeoShape.query.filter_by(unique_id=target_id).first()
        if shape is not None:
            feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
            name = (feat.get('properties') or {}).get('name')
            if name:
                return name
    except Exception:
        pass
    try:
        for model in (Output, Input):
            row = model.query.filter_by(unique_id=target_id).first()
            if row is not None:
                return row.name
    except Exception:
        pass
    return None


def _enrich_job_display(job):
    """Attach human-facing display fields to a SchedulerJobMeta ROW (plain Python
    attributes, not DB columns) so the template never has to touch target_id/
    params_json directly. Reuses AoTDataToolService._schedule_summary (already
    tested via the AI schedule tools) for content/location/editable/deletable,
    with a live id→name fallback when the row predates location-linking (no
    params.target_name stored) or has no summary-derivable location."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    summary = AoTDataToolService._schedule_summary(job)
    job.display_content = summary['content']
    job.display_location = summary['location'] or _resolve_target_name(job.target_id)
    job.display_editable = summary['editable']
    job.display_deletable = summary['deletable']
    job.display_worker = summary['worker']
    # Display in the job's ANCHOR tz (device-local by policy) so the datetime-local
    # edit seed matches how edit_schedule_tool re-interprets it on save (device
    # anchor). Using the system clock here while the save path anchors to the
    # device tz would reintroduce the 9h round-trip drift. (timezone-management.md §6·§7)
    anchor = getattr(job, 'anchor_tz', None)
    if not anchor and job.target_id and job.target_id != 'none':
        try:
            from aot.utils.device_tz import resolve_location_tz
            anchor = str(resolve_location_tz(job.target_id))
        except Exception:
            anchor = None

    def _fmt(dt, pattern):
        if not dt:
            return None
        if anchor:
            from aot.utils.timekit import to_tz
            return to_tz(dt, anchor).strftime(pattern)
        return to_local(dt).strftime(pattern)

    job.display_created_at = _fmt(job.created_at, '%m/%d %H:%M') or '-'
    job.display_schedule_time = _fmt(job.schedule_time, '%Y-%m-%d %H:%M')
    job.display_end_time = _fmt(job.end_time, '%Y-%m-%d %H:%M')
    job.display_tz = anchor  # shown as a label next to the time so device≠viewer is explicit
    return job


@blueprint.route('/scheduler', methods=['GET'])
@login_required
def page_scheduler():
    """Scheduler main page - Timeline + Proposal Queue."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))

    # 기계가 스스로 남긴 실행 기록(automated_fire)은 **기본으로 숨긴다.**
    #
    # 실측: 전체 323건 중 249건(77%)이 automated_fire 다. 최근 200건을 그대로
    # 실으면 사람이 만든 일정(13건)·장치 예약(12건)이 그 속에 묻혀, 이 화면이
    # "내 일을 보는 곳" 이 아니라 "로그를 보는 곳" 이 된다.
    #
    # 숨기되 **몇 건을 숨겼는지 화면에 적는다** — 말없이 빼면 "일정이
    # 사라졌다" 로 읽힌다. 토글(`?show_automated=1`)로 언제든 되돌린다.
    show_automated = request.args.get('show_automated') in ('1', 'true', 'True')

    base = SchedulerJobMeta.query
    automated_count = base.filter(
        SchedulerJobMeta.action_type == 'automated_fire').count()
    if not show_automated:
        base = base.filter(SchedulerJobMeta.action_type != 'automated_fire')

    jobs = base.order_by(SchedulerJobMeta.created_at.desc()).limit(200).all()
    for j in jobs:
        _enrich_job_display(j)

    drafts = [j for j in jobs if j.state == JOB_STATE_DRAFT]
    active_jobs = [j for j in jobs if j.state in (JOB_STATE_PENDING, 'RUNNING')]
    completed_jobs = [j for j in jobs if j.state in (JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_ARCHIVED)]

    # Manual task creation target lists.
    # NOTE: intentionally NOT AIActionService.get_action_manifest() — that manifest is
    # AI-automation scoped (Output.is_ai_enabled, PID.is_activated) and hid most real
    # devices from a human manually creating a task (e.g. 5 of 49 outputs on this box).
    # A human picking a target here should see every real device, regardless of
    # whether the AI is separately permitted to touch it.
    from aot.databases.models import AIAgent, PID, Function
    from aot.databases.models.geo import GeoShape
    from aot.utils.device_tz import get_device_tz

    # Each target carries its anchor tz (device-local) so the new-task form can
    # show a live dual-clock (device time / your time / UTC). tz is read from the
    # materialized device.timezone column — O(1), no per-row finder. §6·§7
    manual_outputs = []
    for o in Output.query.order_by(Output.name).all():
        channels = OutputChannel.query.filter_by(output_id=o.unique_id).order_by(OutputChannel.channel).all()
        manual_outputs.append({
            'unique_id': o.unique_id,
            'name': o.name,
            'type': o.output_type,
            'tz': str(get_device_tz(o)),
            'channels': [{'index': ch.channel, 'name': ch.name or f'CH{ch.channel}'} for ch in channels],
        })

    manual_pids = [{'unique_id': p.unique_id, 'name': p.name, 'tz': str(get_device_tz(p))}
                   for p in PID.query.order_by(PID.name).all()]
    manual_functions = [{'unique_id': f.unique_id, 'name': f.name, 'tz': str(get_device_tz(f))}
                        for f in Function.query.order_by(Function.name).all()]

    manual_zones = []
    for z in GeoShape.query.filter_by(type='zone').all():
        meta = z.meta_json if z.meta_json else {}
        try:
            _ztz = z.resolve_timezone()
            ztz = str(_ztz) if _ztz is not None else str(get_device_tz(None))
        except Exception:
            ztz = str(get_device_tz(None))
        manual_zones.append({'unique_id': z.unique_id, 'name': meta.get('name', f'Zone_{z.id}'), 'tz': ztz})

    active_agents = AIAgent.query.filter_by(is_activated=True).all()

    # _mcp_pending_approvals.html include 가 요구한다. 물리 제어 목록은 게이트가
    # 정본이다 — 화면에 하드코딩하면 도구가 늘 때 조용히 어긋나고, 그 어긋남이
    # 곧 "확인 없이 밸브가 열리는" 상태가 된다.
    from aot.ai.services import mcp_safety_gate as gate

    return render_template('pages/ai/scheduler.html',
                           show_automated=show_automated,
                           automated_count=automated_count,
                           physical_tools=sorted(gate.PHYSICAL_TOOLS),
                           drafts=drafts,
                           active_jobs=active_jobs,
                           completed_jobs=completed_jobs,
                           all_jobs=jobs,
                           outputs=manual_outputs,
                           pids=manual_pids,
                           functions=manual_functions,
                           zones=manual_zones,
                           active_agents=active_agents,
                           active_page='ai_scheduler',
                           settings=Misc.query.first())


@blueprint.route('/api/v1/scheduler/smart_propose', methods=['POST'])
@login_required
def api_smart_propose():
    """Process natural language command using an AI agent.

    @ANCHOR: PHASE3_AGENT_LOOP_MIGRATION (docs/design/ai-agent-loop.md §10)
    Was AIAgentService.process_natural_language_command (legacy router
    pipeline). Migrated straight to AgentLoopService.run() — it already
    resolves both 'auto' and an explicit agent_id (AgentLoopService._resolve_agent),
    and returns the same {status, insight, proposed_actions, ...} shape via the
    same _dispatch_actions this endpoint's frontend (scheduler.html askAI())
    already expects, so no caller-side change was needed.
    """
    data = request.json
    agent_id = data.get('agent_id')
    command = data.get('command')

    if not agent_id or not command:
        return jsonify({'status': 'error', 'message': 'Missing agent_id or command'}), 400

    from aot.ai.services.agent_loop_service import AgentLoopService
    result = AgentLoopService.run(command, agent_id=agent_id)
    return jsonify(result)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@blueprint.route('/api/v1/scheduler/jobs', methods=['GET'])
@login_required
def api_get_jobs():
    """Get all jobs, optionally filtered by state."""
    state = request.args.get('state')
    jobs = AISchedulerService.get_jobs(state=state)
    return jsonify([_serialize_job(j) for j in jobs])


@blueprint.route('/api/v1/scheduler/drafts', methods=['GET'])
@login_required
def api_get_drafts():
    """Get all DRAFT proposals awaiting review."""
    drafts = AISchedulerService.get_drafts()
    return jsonify([_serialize_job(d) for d in drafts])


@blueprint.route('/api/v1/scheduler/propose', methods=['POST'])
@login_required
def api_propose_job():
    """Create a new job (manual task by human)."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    required = ['action_type', 'target_id']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400

    try:
        schedule_time = None
        _anchor_name = None
        _anchor_src = None
        if data.get('schedule_time'):
            # data['schedule_time'] is the raw value of an <input type="datetime-local">:
            # a naive wall-clock string, no offset. Confirmed policy: for a device
            # task this is the DEVICE'S own local time, so anchor to the target's
            # tz (device-local), not the browser/system clock. Storage is UTC;
            # display re-derives device-local. (timezone-management.md §6)
            from aot.ai.services.aot_data_tool_service import AoTDataToolService
            from aot.utils.timekit import wall_to_utc
            _atz, _anchor_name, _anchor_src = \
                AoTDataToolService._resolve_schedule_anchor(data.get('target_id'))
            schedule_time = wall_to_utc(data['schedule_time'], _atz)

        action_type = data['action_type']
        target_id = data['target_id']
        params = data.get('params', {})

        # 'output' is a deprecated action_type — ActionResolverRegistry hard-blocks it
        # (LegacyGuardResolver, see resolvers/registry.py) so any job saved with it would
        # fire on schedule and immediately fail with LEGACY_BLOCKED. All physical device
        # control must go through action_type='mcp_tool_call' / tool_name='operate_device'
        # (same translation AIActionService.get_action_manifest() documents via mcp_binding).
        if action_type == 'output':
            # 사람이 대시보드에서 만든 장치 예약이다. **MCP 로 보내지 않는다.**
            #
            # 예전에는 여기서 mcp_tool_call/operate_device 로 바꿔 보냈다 —
            # "'output' 은 폐기됐고 모든 물리 제어는 MCP 도구로" 라는 규칙 때문이다.
            # 그런데 그 도구는 AI 호출자를 전제로 MCP **서버** 쪽 승인 게이트를 갖고
            # 있고, 스케줄러가 넘기는 _approved=True 는 로컬 리졸버까지만 살아남는다
            # (MCPBridgeService.call_tool 에 승인 인자가 없다). 그래서 "대시보드에서
            # 예약 → 실행 시각에 사람 승인을 다시 요구 → 그 시각엔 아무도 없음" 이
            # 되어 **한 번도 켜지지 않았다**. 2026-08-13 실측: 예약 6건 전부 정시에
            # 트리거되고도 미실행, 승인 큐에 pending 확인요청만 8건 쌓였다.
            #
            # human_device_control 은 대시보드 즉시 버튼과 같은 데몬 경로로 직접
            # 실행하며, _approved=True 없이는 거부된다(AI 경로는 그대로 둔다).
            action_type = 'human_device_control'
            _p = {'state': params.get('state', 'on')}
            if params.get('channel') is not None:
                _p['channel'] = params.get('channel')
            if params.get('amount'):
                _p['duration_sec'] = params.get('amount')
            params = _p

        meta = AISchedulerService.propose_job(
            action_type=action_type,
            target_id=target_id,
            params=params,
            reasoning=data.get('reasoning', 'Manual task'),
            schedule_time=schedule_time,
            duration_sec=data.get('duration_sec', 0),
            schedule_cron=data.get('schedule_cron'),
            proposed_by='HUMAN',
            approval_required=False,
            priority=data.get('priority', 1),
            # 예약을 만든 사람. 발화 시 이 신원으로 스코프를 **다시** 묻는다
            # — 없으면 "지금 못 켜니 1분 뒤로 예약" 이 제어 게이트의 우회로가
            # 된다(docs/design/access-scope-groups.md §6-3·§8-7).
            user_id=current_user_id()
        )
        # Persist the device-local tz anchor so display re-derives device time.
        if _anchor_name:
            try:
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src
                db.session.commit()
            except Exception:
                pass
        return jsonify(_serialize_job(meta)), 201
    except Exception as e:
        logger.exception("Error proposing job")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/v1/scheduler/approve/<int:job_id>', methods=['POST'])
@login_required
def api_approve_job(job_id):
    """Approve a DRAFT job."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json(silent=True) or {}
    try:
        meta = AISchedulerService.approve_job(
            job_id,
            adjusted_params=data.get('adjusted_params'),
            user_feedback=data.get('feedback')
        )
        return jsonify(_serialize_job(meta))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception("Error approving job")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/v1/scheduler/reject/<int:job_id>', methods=['POST'])
@login_required
def api_reject_job(job_id):
    """Reject a DRAFT job."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json(silent=True) or {}
    try:
        meta = AISchedulerService.reject_job(
            job_id,
            user_feedback=data.get('feedback')
        )
        return jsonify(_serialize_job(meta))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception("Error rejecting job")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/v1/scheduler/jobs/<int:job_id>', methods=['PUT'])
@login_required
def api_update_job(job_id):
    """Edit an existing job's time/duration/content/worker/location.

    Reuses AoTDataToolService.edit_schedule_tool — NOT the older, cruder
    /api/scheduler/job/<id> PUT in routes_ai_api.py, which overwrites
    params_json wholesale and never reschedules the underlying APScheduler
    trigger on a time change (a real correctness gap for device-control jobs).
    edit_schedule_tool merges params properly and calls job.modify(...) on the
    live APScheduler job when the schedule time changes.
    """
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    data = request.get_json(silent=True) or {}
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    result = AoTDataToolService.edit_schedule_tool(
        job_id=str(job_id),
        date=data.get('date'),
        time=data.get('time'),
        content=data.get('content'),
        worker=data.get('worker'),
        target_name=data.get('target_name'),
        duration_minutes=data.get('duration_minutes'),
    )
    if result.get('error'):
        status = 404 if 'not found' in result['error'].lower() else 400
        return jsonify(result), status
    return jsonify(result)


@blueprint.route('/api/v1/scheduler/jobs/<int:job_id>', methods=['DELETE'])
@login_required
def api_delete_job(job_id):
    """Cancel a job (soft-delete → ARCHIVED) and remove its APScheduler trigger
    if one is registered. Reuses AoTDataToolService.delete_schedule_tool for
    the same reason as api_update_job above."""
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    # silent=True 는 필수다. 본문(reason)은 선택인데, silent 없이 부르면 Flask 가
    # Content-Type 이 application/json 이 아닌 요청에 **415 를 던지고 뷰에 들어오지도
    # 않는다** — `or {}` 는 실행될 기회가 없다. 취소 버튼처럼 본문 없이 DELETE 만
    # 보내는 호출부가 정상인데도 실패한다(지도 위젯의 [예약 취소] 가 그랬다).
    data = request.get_json(silent=True) or {}
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    result = AoTDataToolService.delete_schedule_tool(
        job_id=str(job_id),
        reason=data.get('reason'),
    )
    if result.get('error'):
        status = 404 if 'not found' in result['error'].lower() else 400
        return jsonify(result), status
    return jsonify(result)


@blueprint.route('/api/v1/scheduler/jobs/<int:job_id>/location', methods=['GET'])
@login_required
def api_job_location(job_id):
    """Resolve (lat, lng) for a job's target_id, for the calendar widget's
    edit-modal map preview. Deliberately its own on-demand endpoint rather
    than a field on calendar_events' bulk feed — resolve_location_coords does
    up to ~8 DB lookups per call (GeoShape, then up to 7 device tables), fine
    for one job when its modal opens, but an N+1 storm across a month of
    events on every calendar refresh."""
    meta = SchedulerJobMeta.query.get(job_id)
    if meta is None:
        return jsonify({'error': 'Schedule not found'}), 404
    from aot.utils.device_tz import resolve_location_coords
    lat, lng = resolve_location_coords(meta.target_id)
    return jsonify({'lat': lat, 'lng': lng})


@blueprint.route('/api/v1/scheduler/calendar_events', methods=['GET'])
@login_required
def api_calendar_events():
    """Calendar-widget event feed — additive, NOT a replacement for
    /api/v1/scheduler/timeline (that one is consumed as-is by this page's own
    FullCalendar instance; changing its shape would risk breaking it).

    Unlike /timeline, this supports FullCalendar's own start/end range params
    (so a month view only pays for a month of rows) and a `sources` filter
    (comma-separated: 'schedule' | 'note' | 'notice' — see
    aot/utils/calendar_event_providers.py). Event titles are resolved
    content+location (never a raw target_id/UUID).

    세 소스를 한 피드로 합치는 이유: 저장 위치가 셋일 뿐 사용자에게는 같은
    것이다(문장 + 어디 + 언제). 실제로 경계가 양방향으로 새고 있다 —
    `action_type='note'` 인 일정과 `category='schedule'` 인 노트가 둘 다 있다.
    """
    from aot.utils.calendar_event_providers import CALENDAR_EVENT_PROVIDERS

    start = request.args.get('start')
    end = request.args.get('end')
    limit = request.args.get('limit', 500, type=int)
    # Optional bucket filter (ai|user|device) so the widget can show each AoT
    # category as its own toggle-able source. None = all buckets.
    category = request.args.get('category') or None
    requested_sources = [s.strip() for s in request.args.get('sources', 'schedule').split(',') if s.strip()]

    events = []
    for source in requested_sources:
        provider = CALENDAR_EVENT_PROVIDERS.get(source)
        if provider is None:
            # Unregistered source (e.g. a future 'notice'/'note' the frontend
            # already offers before the backend ships it) — ignore, not error,
            # so frontend/backend rollout doesn't have to be lockstep.
            continue
        try:
            events.extend(provider(start=start, end=end, limit=limit, category=category))
        except Exception:
            logger.exception("api_calendar_events: provider '%s' failed", source)

    return jsonify(events)


def _job_target_tz_name(job):
    """Resolve the IANA tz a job should display in (device-local — the
    confirmed anchor policy, docs/design/timezone-management.md §12).

    For mcp_tool_call jobs the physical device lives in
    params.arguments.device_id (target_id is the MCP server, which has no
    location); otherwise target_id is the device/shape itself. Falls back to
    the system tz (resolve_location_tz's own chain) when nothing resolves.
    """
    from aot.utils.device_tz import resolve_location_tz
    tid = job.target_id
    try:
        if job.action_type == 'mcp_tool_call' and job.params_json:
            args = (json.loads(job.params_json) or {}).get('arguments') or {}
            tid = args.get('device_id') or tid
    except Exception:
        pass
    try:
        return str(resolve_location_tz(tid))
    except Exception:
        return 'UTC'


@blueprint.route('/api/v1/scheduler/timeline', methods=['GET'])
@login_required
def api_timeline_events():
    """Return jobs formatted for FullCalendar."""
    # 페이지 목록과 **같은 기본값**을 쓴다 — 목록에서 숨긴 것이 달력에는
    # 그대로 뜨면 두 화면이 다른 말을 한다.
    _tl = SchedulerJobMeta.query.filter(
        SchedulerJobMeta.state.in_([JOB_STATE_DRAFT, JOB_STATE_PENDING, 'RUNNING', JOB_STATE_COMPLETED])
    )
    if request.args.get('show_automated') not in ('1', 'true', 'True'):
        _tl = _tl.filter(SchedulerJobMeta.action_type != 'automated_fire')
    jobs = _tl.order_by(SchedulerJobMeta.created_at.desc()).limit(200).all()

    events = []
    for j in jobs:
        tz_name = _job_target_tz_name(j)
        event = {
            'id': j.id,
            'title': f"{j.action_type}: {j.target_id[:8]}",
            # UTC+offset ISO so FullCalendar places the event at the correct
            # absolute instant. Previously .isoformat() on a naive-UTC column
            # emitted no offset → FullCalendar read it as browser-local and
            # shifted every event by the viewer's UTC offset.
            'start': iso_utc(j.schedule_time or j.created_at),
            'className': _state_to_css_class(j.state),
            'extendedProps': {
                'state': j.state,
                'proposed_by': j.proposed_by,
                'reasoning': j.reasoning or '',
                'action_type': j.action_type,
                'target_id': j.target_id,
                'priority': j.priority,
                'tz': tz_name,   # device-local tz for display/labeling
            }
        }
        if j.state == JOB_STATE_DRAFT:
            event['borderColor'] = '#FEA60B'
            event['backgroundColor'] = 'rgba(254, 166, 11, 0.15)'
        events.append(event)
    return jsonify(events)


def _serialize_job(meta):
    """Serialize SchedulerJobMeta to dict."""
    # Device-local (anchor tz) view of schedule_time, alongside the legacy
    # system-tz `schedule_time` kept for back-compat. §6·§7
    anchor = getattr(meta, 'anchor_tz', None)
    if not anchor and meta.target_id and meta.target_id != 'none':
        try:
            anchor = str(_job_target_tz_name(meta))
        except Exception:
            anchor = None
    schedule_local = None
    if meta.schedule_time and anchor:
        try:
            from aot.utils.timekit import to_tz
            schedule_local = to_tz(meta.schedule_time, anchor).isoformat()
        except Exception:
            schedule_local = None
    return {
        'id': meta.id,
        'unique_id': meta.unique_id,
        'action_type': meta.action_type,
        'target_id': meta.target_id,
        'params': json.loads(meta.params_json) if meta.params_json else {},
        'schedule_time': serialize_ts(meta.schedule_time),  # tz: UTC→user_tz for display (legacy)
        'schedule_time_local': schedule_local,  # device-local (anchor tz) ISO
        'anchor_tz': anchor,
        'schedule_cron': json.loads(meta.schedule_cron) if meta.schedule_cron else None,
        'proposed_by': meta.proposed_by,
        'reasoning': meta.reasoning,
        'approval_required': meta.approval_required,
        'priority': meta.priority,
        'state': meta.state,
        'decided_by': meta.decided_by,
        'decided_at': iso_utc(meta.decided_at),    # UTC+offset ISO; client renders in viewer tz
        'user_feedback': meta.user_feedback,
        'executed_at': iso_utc(meta.executed_at),  # UTC+offset ISO; client renders in viewer tz
        'execution_result': meta.execution_result,
        'created_at': iso_utc(meta.created_at)     # UTC+offset ISO; client renders in viewer tz
    }


def _state_to_css_class(state):
    """Map job state to CSS class for FullCalendar events."""
    mapping = {
        'DRAFT': 'fc-event-draft',
        'PENDING': 'fc-event-pending',
        'RUNNING': 'fc-event-running',
        'COMPLETED': 'fc-event-completed',
        'FAILED': 'fc-event-failed',
        'ARCHIVED': 'fc-event-archived'
    }
    return mapping.get(state, '')
