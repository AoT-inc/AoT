# coding=utf-8
"""
AI Context Routes - Blueprint for AIContextRecord REST endpoints.

The standalone AI Context page (and its /ai/context/submit form handler) was
removed; context sources are managed on the AI Library page, so /ai/context
now redirects there.

Philosophy alignment:
- P1_Honesty: context_state field makes trust level explicit
- P2_Co_Growth: confirmations trigger facility learning updates
- P4_User_Agency: users can confirm, reject, or edit every record
"""

from flask import Blueprint, redirect, url_for, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils.utils_ai_context import (
    context_record_confirm,
    context_record_reject,
    context_record_delete,
)
from aot.databases.models import AIContextRecord

blueprint = Blueprint('routes_ai_context', __name__)


@blueprint.route('/ai/context')
@login_required
def page_ai_context():
    """Legacy /ai/context URL — kept for old bookmarks, points at the AI Library."""
    return redirect(url_for('routes_ai_library.page_ai_library'), code=302)


# @ANCHOR: api_context_stats
@blueprint.route('/api/v1/ai/context/stats')
@login_required
def api_context_stats():
    """
    REST API v1: Return counts of context records by context_state for a facility.

    Query params:
        facility_id: Facility identifier

    Returns:
        JSON: {
            "status": "success",
            "counts": {
                "user_confirmed": int,
                "pending": int,
                "system_generated": int,
                "total": int
            }
        }
    """
    facility_id = request.args.get('facility_id', '')

    base_query = AIContextRecord.query
    if facility_id:
        base_query = base_query.filter_by(facility_id=facility_id)

    # Count by context_state
    state_counts = (
        base_query
        .with_entities(AIContextRecord.context_state, func.count(AIContextRecord.id))
        .group_by(AIContextRecord.context_state)
        .all()
    )

    counts = {
        'user_confirmed': 0,
        'pending': 0,
        'system_generated': 0,
        'total': 0
    }
    for state, count in state_counts:
        if state in counts:
            counts[state] = count
        counts['total'] += count

    return jsonify({'status': 'success', 'counts': counts})


# @ANCHOR: api_context_record_action
@blueprint.route('/api/v1/ai/context/<int:record_id>', methods=['PATCH', 'DELETE'])
@login_required
def api_context_record_action(record_id):
    """
    REST API v1: Confirm, reject, or delete a single context record.

    PATCH body: {"action": "confirm" | "reject"}
    DELETE: no body required

    Returns:
        JSON: {"status": "success", "messages": {...}}
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'status': 'error', 'messages': {'error': ['Permission denied']}}), 403

    if request.method == 'DELETE':
        messages = context_record_delete(record_id, current_user.id)
    else:
        data = request.get_json(silent=True) or {}
        action = data.get('action', '')
        if action == 'confirm':
            messages = context_record_confirm(record_id, current_user.id)
        elif action == 'reject':
            messages = context_record_reject(record_id, current_user.id)
        else:
            return jsonify({'status': 'error', 'messages': {'error': ['Unknown action']}}), 400

    has_error = bool(messages.get('error'))
    return jsonify({
        'status': 'error' if has_error else 'success',
        'messages': messages
    })
