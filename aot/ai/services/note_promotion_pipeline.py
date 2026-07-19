# coding=utf-8
"""
NotePromotionPipeline — promotes Notes through the AI action pipeline.

State machine:
  RAW_NOTE       → Notes model (aot/databases/models/notes.py)
  ENRICHED_NOTE  → EKGService PatternCluster (Phase 5 stub)
  DRAFT_ACTION   → AITask (status='proposed')
  PENDING        → SchedulerJobMeta (state='DRAFT', pending human approval)
  APPROVED       → SchedulerJobMeta (state='PENDING' after approve_job())
  EXECUTED       → SchedulerJobMeta (state='COMPLETED') + AITask (status='completed')
  REJECTED       → SchedulerJobMeta (state='ARCHIVED' after reject_job())

Atomicity:
  DRAFT_ACTION + PENDING are created in a single db.session transaction via
  _register_drafts_no_commit() + propose_job_no_commit() + single commit.
  AITask.scheduler_job_id FK links both records.

Approval:
  _check_approval_required() always returns True (ai_agent_service.py:2990).
  All transitions require human approval via the UI / AISchedulerService.approve_job().

Ref: 010_IMPLEMENTATION_PLAN.yaml Phase D / D-1
"""
import json
import logging
from datetime import datetime, timedelta

from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)


# @ANCHOR: NOTE_PROMOTION_PIPELINE
class NotePromotionPipeline:
    """
    Promotes a Notes row through the AI action pipeline.
    All methods are static — no instance state required.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def promote(note_id: str, agent_name: str = 'AI', reasoning: str = '') -> dict:
        """
        RAW_NOTE → ENRICHED_NOTE → DRAFT_ACTION + PENDING (atomic).

        Args:
            note_id:    Notes.unique_id to promote.
            agent_name: Name logged on the resulting AITask.
            reasoning:  Human-readable rationale stored on both records.

        Returns:
            {'aitask_id': str, 'scheduler_job_meta_id': int, 'state': 'DRAFT'}

        Raises:
            PermissionError: NOTE_PROMOTION capability disabled.
            ValueError:      Note not found.
        """
        # ── Guard ─────────────────────────────────────────────────────
        try:
            from aot.config.feature_flags import capability_manager
            if not capability_manager.is_enabled('NOTE_PROMOTION'):
                raise PermissionError(
                    "[NotePromotionPipeline] NOTE_PROMOTION capability is disabled "
                    "for the current hardware profile."
                )
        except ImportError:
            pass  # CapabilityManager not yet available — proceed (fail-open)

        # ── Fetch source note ─────────────────────────────────────────
        from aot.databases.models.notes import Notes
        note = Notes.query.filter_by(unique_id=note_id).first()
        if not note:
            raise ValueError(f"[NotePromotionPipeline] Note '{note_id}' not found.")

        # ── ENRICHED_NOTE: EKG enrichment (Phase 5 stub) ─────────────
        action = NotePromotionPipeline._enrich_note(note)

        # ── DRAFT_ACTION + PENDING: atomic creation ───────────────────
        effective_reasoning = reasoning or f"Note promotion: {note.unique_id}"
        return NotePromotionPipeline._promote_to_draft(
            note=note,
            action=action,
            reasoning=effective_reasoning,
            agent_name=agent_name,
        )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    @staticmethod
    def _enrich_note(note) -> dict:
        """
        ENRICHED_NOTE stage: derive action payload from EKGService.
        Phase 5 stub — returns deterministic action dict.
        TODO Phase 6: replace with EKGService.enrich(note) for pattern-driven actions.
        """
        return {
            'action_type': 'NOTE_ENRICHMENT',
            'target_id': note.unique_id,
            'params': {
                'tags': note.tags if hasattr(note, 'tags') and note.tags else [],
                'category': note.category or 'general',
            },
            'display_summary': f"[NotePromotion] {note.name or note.unique_id}",
            'priority': 3,
        }

    @staticmethod
    def _promote_to_draft(note, action: dict, reasoning: str, agent_name: str) -> dict:
        """
        Atomically creates AITask (status='proposed') and SchedulerJobMeta (state='DRAFT').
        Links them via AITask.scheduler_job_id FK.
        Uses db.session.begin_nested() (SAVEPOINT) for rollback isolation.
        """
        from aot.databases.models.ai_task import AITask
        from aot.databases.models.scheduler import SchedulerJobMeta
        from aot.ai.services.ai_agent_service import AIAgentService
        from aot.ai.services.ai_scheduler_service import AISchedulerService

        now = datetime.utcnow()

        try:
            sp = db.session.begin_nested()   # SAVEPOINT

            # ── 1. AITask (DRAFT_ACTION) ──────────────────────────────
            actions_list = [{
                'action_type':    action['action_type'],
                'target_id':      action['target_id'],
                'params':         action.get('params', {}),
                'display_summary': action.get('display_summary', ''),
                'priority':       action.get('priority', 3),
            }]
            draft_ids = AIAgentService._register_drafts_no_commit(
                actions_list, reasoning, agent_name
            )
            if not draft_ids:
                raise ValueError("_register_drafts_no_commit returned no IDs.")
            db.session.flush()   # assign task.id

            task = AITask.query.filter_by(unique_id=draft_ids[0]).first()
            if not task:
                raise ValueError(f"AITask '{draft_ids[0]}' not found after flush.")

            # ── 2. SchedulerJobMeta (PENDING) ─────────────────────────
            meta = AISchedulerService.propose_job_no_commit(
                action_type=action['action_type'],
                target_id=action['target_id'],
                params=action.get('params', {}),
                reasoning=reasoning,
                proposed_by='AI',
                approval_required=True,    # _check_approval_required() always True
                priority=action.get('priority', 3),
                schedule_time=now + timedelta(minutes=10),
                duration_sec=3600,
                source_type='note_promotion',
            )
            db.session.flush()   # assign meta.id

            # ── 3. FK link ────────────────────────────────────────────
            task.scheduler_job_id = meta.id

            # ── 4. Back-reference on Notes ────────────────────────────
            note.parent_task_id = task.unique_id

            # ── 5. Single commit ──────────────────────────────────────
            sp.commit()
            db.session.commit()

            logger.info(
                "[NotePromotionPipeline] Promoted note %s → AITask %s + SchedulerJobMeta %s",
                note.unique_id, task.unique_id, meta.id,
            )
            return {
                'aitask_id': task.unique_id,
                'scheduler_job_meta_id': meta.id,
                'state': 'DRAFT',
            }

        except Exception:
            db.session.rollback()
            logger.exception(
                "[NotePromotionPipeline] Atomic promotion failed for note '%s'",
                note.unique_id,
            )
            raise

    # ------------------------------------------------------------------
    # State query
    # ------------------------------------------------------------------
    @staticmethod
    def get_pipeline_state(note_id: str) -> str:
        """
        Returns the current pipeline state for a given Notes.unique_id.
        SchedulerJobMeta.state is the authoritative source after DRAFT_ACTION.

        State map:
          SchedulerJobMeta.state  →  pipeline state
          DRAFT                   →  PENDING
          PENDING                 →  APPROVED
          RUNNING / COMPLETED / FAILED  →  EXECUTED
          ARCHIVED                →  REJECTED
        """
        from aot.databases.models.notes import Notes
        from aot.databases.models.ai_task import AITask
        from aot.databases.models.scheduler import SchedulerJobMeta

        note = Notes.query.filter_by(unique_id=note_id).first()
        if not note or not getattr(note, 'parent_task_id', None):
            return 'RAW_NOTE'

        task = AITask.query.filter_by(unique_id=note.parent_task_id).first()
        if not task:
            return 'RAW_NOTE'

        # M5_3: FUNCTION_GENERATION action_type — separate state machine path
        if getattr(task, 'action_type', None) == 'FUNCTION_GENERATION':
            _func_state_map = {
                'proposed':  'DRAFT_FUNCTION',
                'sandboxed': 'SANDBOXED',
                'approved':  'APPROVED',
                'completed': 'REGISTERED',
            }
            return _func_state_map.get(task.status, 'DRAFT_FUNCTION')

        if not getattr(task, 'scheduler_job_id', None):
            return 'ENRICHED_NOTE' if task.status == 'enriched' else 'DRAFT_ACTION'

        meta = SchedulerJobMeta.query.get(task.scheduler_job_id)
        if not meta:
            return 'DRAFT_ACTION'

        _state_map = {
            'DRAFT':     'PENDING',
            'PENDING':   'APPROVED',
            'RUNNING':   'EXECUTED',
            'COMPLETED': 'EXECUTED',
            'FAILED':    'EXECUTED',
            'ARCHIVED':  'REJECTED',
        }
        return _state_map.get(meta.state, 'DRAFT_ACTION')

    # ------------------------------------------------------------------
    # Function generation path (M5_3 — Phase 5)
    # ------------------------------------------------------------------
    @staticmethod
    def promote_function(
        contract: dict,
        logic_source: str,
        agent_name: str = 'AI',
        reasoning: str = '',
    ) -> dict:
        """
        DRAFT_FUNCTION → SANDBOXED → PENDING_APPROVAL → APPROVED → REGISTERED flow.

        Parallel to promote() but for AI-generated AbstractFunction subclasses.
        Does NOT modify the existing promote() method (Law 1 — additive only).

        Args:
            contract:     FunctionContract dict (must have validation_status='APPROVED',
                          source_type='AI_GENERATED', file_path, entry_class).
            logic_source: Python source string for the AbstractFunction subclass.
            agent_name:   Name logged on the resulting AITask.
            reasoning:    Human-readable rationale stored on the record.

        Returns:
            {
              'file_path':        str,
              'registered_class': str,
              'state':            'REGISTERED',
              'index_verify_stdout': str,
            }

        Raises:
            PermissionError: FUNCTION_GENERATION capability disabled or contract invalid.
        """
        # ── Guard ─────────────────────────────────────────────────────
        try:
            from aot.config.feature_flags import capability_manager
            if not capability_manager.is_enabled('FUNCTION_GENERATION'):
                raise PermissionError(
                    "[NotePromotionPipeline] FUNCTION_GENERATION capability is disabled "
                    "for the current hardware profile."
                )
        except ImportError:
            pass  # CapabilityManager unavailable — fail-open

        # ── Validate contract ─────────────────────────────────────────
        if contract.get('source_type') != 'AI_GENERATED':
            raise PermissionError(
                "[NotePromotionPipeline] promote_function() requires source_type='AI_GENERATED'."
            )
        if contract.get('validation_status') != 'APPROVED':
            raise PermissionError(
                "[NotePromotionPipeline] promote_function() requires validation_status='APPROVED'."
            )
        file_path_val = contract.get('file_path', '')
        if not file_path_val.startswith('aot/functions/custom_functions/'):
            raise PermissionError(
                f"[NotePromotionPipeline] file_path must be within "
                f"'aot/functions/custom_functions/'. Got: '{file_path_val}'"
            )

        # ── Write and load via FunctionLoader ─────────────────────────
        from aot.ai.services.function_loader import FunctionLoader
        file_path = FunctionLoader.write_approved_function(contract, logic_source)
        cls = FunctionLoader.load_function(file_path, contract)

        # ── Update contract state ─────────────────────────────────────
        contract['validation_status'] = 'REGISTERED'
        contract['registered_class'] = cls.__name__
        # contract['index_verify_stdout'] already stored by register_in_index()

        logger.info(
            "[NotePromotionPipeline] Function '%s' registered. file=%s agent=%s",
            cls.__name__, file_path, agent_name,
        )
        return {
            'file_path': file_path,
            'registered_class': cls.__name__,
            'state': 'REGISTERED',
            'index_verify_stdout': contract.get('index_verify_stdout', ''),
        }
