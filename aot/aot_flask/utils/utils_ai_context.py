# coding=utf-8
"""
utils_ai_context.py - Business logic for AIContextRecord CRUD.
All functions return a messages dict: {"success": [], "info": [], "warning": [], "error": []}.
"""
import json
import logging
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextRecord
from aot.ai.services.ai_facility_learning_service import AIFacilityLearningService

logger = logging.getLogger(__name__)


def context_record_add(form, facility_id, user_id):
    """Add a new AIContextRecord from form data."""
    messages = {"success": [], "info": [], "warning": [], "error": []}

    try:
        parameter_name = form.parameter_name.data
        raw_input_val = form.raw_input.data
        source_type = form.source_type.data
        notes = form.notes.data or ""

        if not parameter_name or not raw_input_val:
            messages["error"].append("Parameter name and value are required.")
            return messages

        # Normalize value based on source_type
        if source_type == "free_text":
            value = raw_input_val
        elif source_type == "url":
            value = json.dumps({"url": raw_input_val, "fetched": None})
        else:  # manual
            value = raw_input_val

        # Build source trace
        source = f"{source_type}:{raw_input_val[:80]}"
        if notes:
            source = f"{source} | note:{notes[:50]}"

        record = AIContextRecord(
            facility_id=facility_id,
            parameter_name=parameter_name,
            value=value,
            source=source,
            context_state="pending",
            created_by=str(user_id),
        )
        db.session.add(record)
        db.session.commit()

        messages["success"].append(f"Context record added: {parameter_name}")

    except Exception as e:
        logger.exception("context_record_add")
        db.session.rollback()
        messages["error"].append(str(e))

    return messages


def context_record_confirm(record_id, user_id, new_value=None):
    """Confirm an AIContextRecord and feed into facility learning."""
    messages = {"success": [], "info": [], "warning": [], "error": []}

    try:
        record = AIContextRecord.query.filter_by(id=record_id).first()
        if not record:
            messages["error"].append("Record not found.")
            return messages

        old_value = record.value

        if new_value is not None:
            record.value = new_value

        record.context_state = "user_confirmed"
        record.confirmed_by = user_id
        record.confirmed_at = datetime.utcnow()

        db.session.commit()

        # Feed into facility learning
        try:
            AIFacilityLearningService.record_feedback(
                facility_id=record.facility_id,
                user_id=user_id,
                event_type="confirmed",
                parameter_name=record.parameter_name,
                previous_value=old_value,
                new_value=record.value,
                context_record_id=record.unique_id,
            )
        except Exception as e:
            logger.warning(f"record_feedback call failed: {e}")

        messages["success"].append(f"Confirmed: {record.parameter_name}")

    except Exception as e:
        logger.exception("context_record_confirm")
        db.session.rollback()
        messages["error"].append(str(e))

    return messages


def context_record_reject(record_id, user_id, reason=None):
    """Reject an AIContextRecord (returns to pending for re-review)."""
    messages = {"success": [], "info": [], "warning": [], "error": []}

    try:
        record = AIContextRecord.query.filter_by(id=record_id).first()
        if not record:
            messages["error"].append("Record not found.")
            return messages

        record.context_state = "pending"
        if reason:
            record.source = (record.source or "") + f" | rejected:{reason[:50]}"

        db.session.commit()

        # Feed into facility learning
        try:
            AIFacilityLearningService.record_feedback(
                facility_id=record.facility_id,
                user_id=user_id,
                event_type="rejected",
                parameter_name=record.parameter_name,
                previous_value=record.value,
                new_value=None,
            )
        except Exception as e:
            logger.warning(f"record_feedback call failed: {e}")

        messages["info"].append(f"Rejected: {record.parameter_name}")

    except Exception as e:
        logger.exception("context_record_reject")
        db.session.rollback()
        messages["error"].append(str(e))

    return messages


def context_record_delete(record_id, user_id):
    """Delete an AIContextRecord."""
    messages = {"success": [], "info": [], "warning": [], "error": []}

    try:
        record = AIContextRecord.query.filter_by(id=record_id).first()
        if not record:
            messages["error"].append("Record not found.")
            return messages

        if record.context_state == "user_confirmed":
            messages["warning"].append(
                "Deleting a confirmed record reduces facility calibration. Proceeding."
            )

        param_name = record.parameter_name
        db.session.delete(record)
        db.session.commit()

        messages["success"].append(f"Deleted: {param_name}")

    except Exception as e:
        logger.exception("context_record_delete")
        db.session.rollback()
        messages["error"].append(str(e))

    return messages


def context_record_get_for_facility(facility_id):
    """Get all context records for a facility, ordered by created_at desc."""
    records = (
        AIContextRecord.query
        .filter_by(facility_id=facility_id)
        .order_by(AIContextRecord.created_at.desc())
        .all()
    )
    result = []
    for r in records:
        result.append({
            "id": r.id,
            "unique_id": r.unique_id,
            "parameter_name": r.parameter_name,
            "value": r.value,
            "source": r.source,
            "context_state": r.context_state,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
        })
    return result
