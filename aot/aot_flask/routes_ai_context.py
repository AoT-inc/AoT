# coding=utf-8
"""
AI Context Routes - Blueprint for managing external context injection into AI system.

Pattern mirrors routes_geo.py page_layer + page_layer_submit flow.
Provides UI and API for managing AIContextRecord entries with CRUD operations.

Philosophy alignment:
- P1_Honesty: context_state field makes trust level explicit
- P2_Co_Growth: confirmations trigger facility learning updates
- P4_User_Agency: users can confirm, reject, or edit every record
"""

from flask import Blueprint, render_template, redirect, url_for, jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func
from aot.aot_flask.utils import utils_general
from aot.aot_flask.forms.forms_ai_context import ContextRecordAdd, ContextRecordMod
from aot.aot_flask.utils.utils_ai_context import (
    context_record_add,
    context_record_confirm,
    context_record_reject,
    context_record_delete,
    context_record_get_for_facility
)
from aot.databases.models import Misc
from aot.databases.models import AIContextRecord

blueprint = Blueprint('routes_ai_context', __name__)


@blueprint.route('/ai/context')
@login_required
def page_ai_context():
    """
    AI Context Manager page — now redirects to the unified AI dashboard.
    /ai#context-records hosts the context records section since Phase 2.
    Legacy /ai/context URL is preserved for backward compatibility.
    """
    return redirect('/ai#context-records', code=302)


@blueprint.route('/ai/context/legacy')
@login_required
def page_ai_context_legacy():
    """
    Legacy standalone AI Context Manager page (pre-Phase 2).
    Kept for debugging and admin use.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    # Get facility_id from query args or use first available
    facility_id = request.args.get('facility_id')
    if not facility_id:
        facility_id = request.args.get('facility_id', '')

    # Get context records for this facility
    context_records = context_record_get_for_facility(facility_id) if facility_id else []

    # Instantiate forms
    form_add = ContextRecordAdd()
    form_mod = ContextRecordMod()

    from flask_wtf.csrf import generate_csrf

    return render_template(
        'pages/ai_context.html',
        active_page='ai_context',
        context_records=context_records,
        form_add=form_add,
        form_mod=form_mod,
        facility_id=facility_id,
        csrf_token=generate_csrf
    )


@blueprint.route('/ai/context/submit', methods=['POST'])
@login_required
def page_ai_context_submit():
    """
    Submit handler for AI Context form actions.
    Dispatches based on which button was pressed: add, mod, delete, confirm, reject.

    Returns:
        JSON: {"messages": {...}, "action": "...", "record_id": "..."}
    """
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    # Permission check
    if not utils_general.user_has_permission('edit_settings'):
        messages["error"].append("Your permissions do not allow this action")
        return jsonify(data={'messages': messages})

    # Instantiate forms
    form_add = ContextRecordAdd()
    form_mod = ContextRecordMod()

    facility_id = request.form.get('facility_id', '')
    action_type = None
    record_id = None

    # Dispatch based on which submit button was pressed
    if form_add.record_add.data:
        # Add new context record
        messages = context_record_add(form_add, facility_id, current_user.id)
        action_type = 'record_add'

    elif form_mod.record_mod.data:
        # Modify existing record
        record_id = form_mod.record_id.data
        new_value = form_mod.raw_input.data
        messages = context_record_confirm(
            int(record_id) if record_id else None,
            current_user.id,
            new_value=new_value
        )
        action_type = 'record_mod'

    elif form_mod.record_confirm.data:
        # Confirm a pending record
        record_id = form_mod.record_id.data
        new_value = form_mod.raw_input.data
        messages = context_record_confirm(
            int(record_id) if record_id else None,
            current_user.id,
            new_value=new_value
        )
        action_type = 'record_confirm'

    elif form_mod.record_reject.data:
        # Reject a pending record
        record_id = form_mod.record_id.data
        messages = context_record_reject(
            int(record_id) if record_id else None,
            current_user.id
        )
        action_type = 'record_reject'

    elif form_mod.record_delete.data:
        # Delete a record
        record_id = form_mod.record_id.data
        messages = context_record_delete(
            int(record_id) if record_id else None,
            current_user.id
        )
        action_type = 'record_delete'

    # Check global message settings
    misc = Misc.query.first()
    if misc:
        if misc.hide_alert_success:
            messages['success'] = []
        if misc.hide_alert_info:
            messages['info'] = []
        if misc.hide_alert_warning:
            messages['warning'] = []

    return jsonify(data={
        'messages': messages,
        'action': action_type,
        'record_id': record_id
    })


@blueprint.route('/ai/context/api/records/<facility_id>')
@login_required
def api_context_records(facility_id):
    """
    JSON API endpoint to fetch all context records for a facility.
    Used by frontend to refresh list after submit without full page reload.

    Args:
        facility_id: Facility identifier

    Returns:
        JSON list of context records
    """
    records = context_record_get_for_facility(facility_id)
    return jsonify(records)


# @ANCHOR: api_context_records_v1
@blueprint.route('/api/v1/ai/context')
@login_required
def api_v1_context_records():
    """
    REST API v1: Fetch context records for a facility with optional filters.

    Query params:
        facility_id: Facility identifier
        status: context_state filter (user_confirmed / pending / system_generated)
        q: Keyword search on parameter_name or value

    Returns:
        JSON: {"status": "success", "records": [...]}
    """
    facility_id = request.args.get('facility_id', '')
    status_filter = request.args.get('status', '')
    query = request.args.get('q', '')

    records = context_record_get_for_facility(facility_id) if facility_id else []

    # Apply status filter
    if status_filter:
        records = [r for r in records if r.get('context_state') == status_filter]

    # Apply keyword search
    if query:
        q_lower = query.lower()
        records = [
            r for r in records
            if q_lower in (r.get('parameter_name') or '').lower()
            or q_lower in (r.get('value') or '').lower()
        ]

    return jsonify({'status': 'success', 'records': records})


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
