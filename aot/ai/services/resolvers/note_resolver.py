# coding=utf-8
# @ANCHOR: NOTE_RESOLVER
"""
NoteResolver — handles 'note' and 'abstract_plan' action types.
Ref: SBS-002_V2_STRATEGY (pluggable_resolver.resolvers[NoteResolver])
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver

logger = logging.getLogger(__name__)


class NoteResolver(BaseActionResolver):
    """
    Handles 'note' and 'abstract_plan' action types.

    @phase active
    @stability stable
    @dependency Notes
    """

    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:

        if action_type == 'abstract_plan':
            reason = params.get('reasoning', 'Activity marker')
            logger.info(f"[NoteResolver] AbstractPlan — space '{target_id}': {reason}")
            return {"status": "success", "result": f"Abstract plan active on {target_id}"}

        if action_type == 'note':
            try:
                from aot.databases.models.notes import Notes
                message = params.get('message') or params.get('content') or str(target_id)
                resolved_type = params.get('_resolved_type') or 'general'
                new_note = Notes(
                    note=message,
                    target_id=target_id if str(target_id) != message else None,
                    target_type=resolved_type,
                    category='ai_log',
                    tags='ai_created',
                )
                new_note.save()
                logger.info(f"[NoteResolver] Created note {new_note.unique_id}: {message}")
                return {
                    "status": "success",
                    "result": "Note created and saved to database",
                    "note_id": new_note.unique_id,
                }
            except Exception as e:
                logger.error(f"[NoteResolver] Failed to save note: {e}")
                return {"status": "error", "message": f"Failed to save note: {str(e)}"}

        return {"status": "error", "message": f"NoteResolver: unhandled action_type '{action_type}'"}
