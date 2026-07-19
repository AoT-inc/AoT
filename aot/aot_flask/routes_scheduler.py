# coding=utf-8
"""
Scheduler routes - Page views and API endpoints for the collaborative scheduler.
"""
import json
import logging
from datetime import datetime

import flask_login
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required

from aot.databases.models import db, Misc, Output, OutputChannel
from aot.utils.time_utils import serialize_ts
from aot.databases.models.scheduler import SchedulerJobMeta, SchedulerAuditLog
from aot.ai.services.ai_scheduler_service import (
    AISchedulerService, JOB_STATE_DRAFT, JOB_STATE_PENDING,
    JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_ARCHIVED
)
from aot.aot_flask.utils.utils_general import user_has_permission

logger = logging.getLogger(__name__)
blueprint = Blueprint('routes_scheduler', __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@blueprint.route('/scheduler', methods=['GET'])
@login_required
def page_scheduler():
    """Scheduler main page - Timeline + Proposal Queue."""
    if not user_has_permission('edit_controllers'):
        return redirect(url_for('routes_ai_agent.page_ai_dashboard'))

    jobs = SchedulerJobMeta.query.order_by(
        SchedulerJobMeta.created_at.desc()
    ).limit(200).all()

    drafts = [j for j in jobs if j.state == JOB_STATE_DRAFT]
    active_jobs = [j for j in jobs if j.state in (JOB_STATE_PENDING, 'RUNNING')]
    completed_jobs = [j for j in jobs if j.state in (JOB_STATE_COMPLETED, JOB_STATE_FAILED, JOB_STATE_ARCHIVED)]

    # Combined manifest for manual task creation
    from aot.ai.services.ai_action_service import AIActionService
    from aot.databases.models import AIAgent
    action_manifest = AIActionService.get_action_manifest()
    active_agents = AIAgent.query.filter_by(is_activated=True).all()

    return render_template('pages/ai/scheduler.html',
                           drafts=drafts,
                           active_jobs=active_jobs,
                           completed_jobs=completed_jobs,
                           all_jobs=jobs,
                           outputs=action_manifest.get('outputs', []),
                           pids=action_manifest.get('pid_controllers', []),
                           functions=action_manifest.get('predefined_functions', []),
                           zones=action_manifest.get('spatial_zones', []),
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
        if data.get('schedule_time'):
            schedule_time = datetime.fromisoformat(data['schedule_time'])

        meta = AISchedulerService.propose_job(
            action_type=data['action_type'],
            target_id=data['target_id'],
            params=data.get('params', {}),
            reasoning=data.get('reasoning', 'Manual task'),
            schedule_time=schedule_time,
            duration_sec=data.get('duration_sec', 0),
            schedule_cron=data.get('schedule_cron'),
            proposed_by='HUMAN',
            approval_required=False,
            priority=data.get('priority', 1)
        )
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

    data = request.get_json() or {}
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

    data = request.get_json() or {}
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


@blueprint.route('/api/v1/scheduler/timeline', methods=['GET'])
@login_required
def api_timeline_events():
    """Return jobs formatted for FullCalendar."""
    jobs = SchedulerJobMeta.query.filter(
        SchedulerJobMeta.state.in_([JOB_STATE_DRAFT, JOB_STATE_PENDING, 'RUNNING', JOB_STATE_COMPLETED])
    ).order_by(SchedulerJobMeta.created_at.desc()).limit(200).all()

    events = []
    for j in jobs:
        event = {
            'id': j.id,
            'title': f"{j.action_type}: {j.target_id[:8]}",
            'start': (j.schedule_time or j.created_at).isoformat(),
            'className': _state_to_css_class(j.state),
            'extendedProps': {
                'state': j.state,
                'proposed_by': j.proposed_by,
                'reasoning': j.reasoning or '',
                'action_type': j.action_type,
                'target_id': j.target_id,
                'priority': j.priority
            }
        }
        if j.state == JOB_STATE_DRAFT:
            event['borderColor'] = '#FEA60B'
            event['backgroundColor'] = 'rgba(254, 166, 11, 0.15)'
        events.append(event)
    return jsonify(events)


def _serialize_job(meta):
    """Serialize SchedulerJobMeta to dict."""
    return {
        'id': meta.id,
        'unique_id': meta.unique_id,
        'action_type': meta.action_type,
        'target_id': meta.target_id,
        'params': json.loads(meta.params_json) if meta.params_json else {},
        'schedule_time': serialize_ts(meta.schedule_time),  # tz: UTC→user_tz for display
        'schedule_cron': json.loads(meta.schedule_cron) if meta.schedule_cron else None,
        'proposed_by': meta.proposed_by,
        'reasoning': meta.reasoning,
        'approval_required': meta.approval_required,
        'priority': meta.priority,
        'state': meta.state,
        'decided_by': meta.decided_by,
        'decided_at': serialize_ts(meta.decided_at),   # tz: UTC→user_tz for display
        'user_feedback': meta.user_feedback,
        'executed_at': serialize_ts(meta.executed_at),  # tz: UTC→user_tz for display
        'execution_result': meta.execution_result,
        'created_at': serialize_ts(meta.created_at)    # tz: UTC→user_tz for display
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
