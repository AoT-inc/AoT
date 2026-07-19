# coding=utf-8
# @ANCHOR: AI_MEMORY_MANAGER
"""
AIMemoryManager — Layer 3 (User-Specific Learning) In-Memory Buffer + Correction Protocol.

Write strategy (SBS-002_V2_STRATEGY, layer_3_user_learning.write_strategy):
  Buffer: module-level dict keyed by user_id, holds pending AIUserSemanticMemory records.
  Flush triggers:
    - Periodic:   Every 60 s via start_periodic_flush() (uses threading.Timer, daemon).
    - Idle/Event: Call flush() on session end (agentStop event).
    - Threshold:  Auto-flush per-user if buffer exceeds FLUSH_THRESHOLD (50 records).
  Write mode: Bulk upsert via SQLAlchemy. Single transaction per flush cycle.
  Failure: If flush fails, buffer is retained and retried on next trigger. No data loss.

Correction Protocol (REF-003):
  list_memories(user_id, memory_type)  — audit Layer 3 records.
  forget(user_id, memory_id)           — soft-delete a specific record.
  forget_all(user_id, memory_type)     — bulk soft-delete.
  correct(user_id, memory_id, value)   — update value + reset confidence to 1.0.

Ref: SBS-002_V2_STRATEGY (layer_3_user_learning, correction_protocol)
"""
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── In-Memory Buffer ───────────────────────────────────────────────────────
# {user_id: [{'memory_type', 'key', 'value', 'confidence', 'source'}, ...]}
_buffer: Dict[int, List[Dict[str, Any]]] = {}
_buffer_lock = threading.Lock()

FLUSH_THRESHOLD = 50  # records per user before auto-flush


class AIMemoryManager:
    """
    Layer 3 memory buffer, correction protocol, and flush scheduler.

    @phase active
    @stability stable
    @dependency AIUserSemanticMemory
    """

    # ── Buffer API ─────────────────────────────────────────────────────────

    @classmethod
    def buffer_memory(
        cls,
        user_id: int,
        memory_type: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = 'inferred',
    ) -> None:
        """
        Add a learning record to the in-memory buffer.
        Auto-flushes per-user buffer when FLUSH_THRESHOLD is reached.
        """
        if not user_id:
            return
        record = {
            'memory_type': memory_type,
            'key': key,
            'value': value,
            'confidence': confidence,
            'source': source,
        }
        with _buffer_lock:
            _buffer.setdefault(user_id, []).append(record)
            should_flush = len(_buffer[user_id]) >= FLUSH_THRESHOLD

        if should_flush:
            logger.info(f"[AIMemoryManager] Threshold reached for user {user_id}. Auto-flushing.")
            cls.flush(user_id=user_id)

    @classmethod
    def flush(cls, user_id: Optional[int] = None) -> None:
        """
        Flush buffered records to DB via bulk upsert (INSERT or UPDATE on key conflict).
        If user_id is None, flushes all users' buffers.
        Retains buffer on failure so the next trigger can retry.
        """
        with _buffer_lock:
            if user_id is not None:
                targets = {user_id: _buffer.pop(user_id, [])}
            else:
                targets = dict(_buffer)
                _buffer.clear()

        if not targets:
            return

        try:
            from aot.databases.models.ai_memory import AIUserSemanticMemory
            from aot.aot_flask.extensions import db

            now = datetime.utcnow()
            total_written = 0

            for uid, records in targets.items():
                if not records:
                    continue
                for rec in records:
                    existing = AIUserSemanticMemory.query.filter_by(
                        user_id=uid,
                        memory_type=rec['memory_type'],
                        key=rec['key'],
                        is_active=True,
                    ).first()
                    if existing:
                        existing.value = rec['value']
                        existing.confidence = rec['confidence']
                        existing.source = rec['source']
                        existing.last_used_at = now
                    else:
                        db.session.add(AIUserSemanticMemory(
                            user_id=uid,
                            memory_type=rec['memory_type'],
                            key=rec['key'],
                            value=rec['value'],
                            confidence=rec['confidence'],
                            source=rec['source'],
                        ))
                    total_written += 1

            db.session.commit()
            logger.info(f"[AIMemoryManager] Flushed {total_written} records to DB.")

        except Exception as e:
            logger.error(f"[AIMemoryManager] Flush failed — buffer retained for retry: {e}")
            # Restore unwritten records to buffer
            with _buffer_lock:
                for uid, records in targets.items():
                    existing = _buffer.get(uid, [])
                    _buffer[uid] = records + existing

    @classmethod
    def start_periodic_flush(cls, interval: int = 60) -> None:
        """
        Start a daemon background thread that calls flush() every `interval` seconds.
        Safe to call at app startup. Does not block shutdown.
        """
        def _tick():
            cls.flush()
            t = threading.Timer(interval, _tick)
            t.daemon = True
            t.start()

        first_timer = threading.Timer(interval, _tick)
        first_timer.daemon = True
        first_timer.start()
        logger.info(f"[AIMemoryManager] Periodic flush scheduler started (interval={interval}s).")

    # ── Correction Protocol (REF-003) ──────────────────────────────────────

    @classmethod
    def list_memories(
        cls,
        user_id: int,
        memory_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Returns all active memories for a user, optionally filtered by memory_type.
        Ref: SBS-002_V2_STRATEGY (correction_protocol.methods[list_memories])
        """
        try:
            from aot.databases.models.ai_memory import AIUserSemanticMemory
            q = AIUserSemanticMemory.query.filter_by(user_id=user_id, is_active=True)
            if memory_type:
                q = q.filter_by(memory_type=memory_type)
            rows = q.order_by(AIUserSemanticMemory.last_used_at.desc()).all()
            return [
                {
                    'id': r.unique_id,
                    'memory_type': r.memory_type,
                    'key': r.key,
                    'value': r.value,
                    'confidence': r.confidence,
                    'source': r.source,
                    'created_at': r.created_at.isoformat(),
                    'last_used_at': r.last_used_at.isoformat(),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"[AIMemoryManager] list_memories failed: {e}")
            return []

    @classmethod
    def forget(cls, user_id: int, memory_id: str) -> Dict[str, Any]:
        """
        Soft-delete a specific memory record (sets is_active=False).
        Ref: SBS-002_V2_STRATEGY (correction_protocol.methods[forget])
        """
        try:
            from aot.databases.models.ai_memory import AIUserSemanticMemory
            record = AIUserSemanticMemory.query.filter_by(
                unique_id=memory_id, user_id=user_id
            ).first()
            if not record:
                return {'status': 'error', 'reason': 'memory_not_found'}
            record.is_active = False
            record.save()
            logger.info(f"[AIMemoryManager] Forgot memory {memory_id} for user {user_id}.")
            return {'status': 'success', 'memory_id': memory_id}
        except Exception as e:
            logger.error(f"[AIMemoryManager] forget failed: {e}")
            return {'status': 'error', 'reason': str(e)}

    @classmethod
    def forget_all(
        cls,
        user_id: int,
        memory_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Bulk soft-delete. Optionally scoped to a memory_type.
        Ref: SBS-002_V2_STRATEGY (correction_protocol.methods[forget_all])
        """
        try:
            from aot.databases.models.ai_memory import AIUserSemanticMemory
            from aot.aot_flask.extensions import db
            q = AIUserSemanticMemory.query.filter_by(user_id=user_id, is_active=True)
            if memory_type:
                q = q.filter_by(memory_type=memory_type)
            count = q.update({'is_active': False})
            db.session.commit()
            logger.info(f"[AIMemoryManager] Forgot {count} memories for user {user_id} (type={memory_type}).")
            return {'status': 'success', 'deleted_count': count}
        except Exception as e:
            logger.error(f"[AIMemoryManager] forget_all failed: {e}")
            return {'status': 'error', 'reason': str(e)}

    @classmethod
    def correct(
        cls,
        user_id: int,
        memory_id: str,
        new_value: str,
    ) -> Dict[str, Any]:
        """
        Update the value of an existing memory and reset confidence to 1.0.
        Ref: SBS-002_V2_STRATEGY (correction_protocol.methods[correct])
        """
        try:
            from aot.databases.models.ai_memory import AIUserSemanticMemory
            record = AIUserSemanticMemory.query.filter_by(
                unique_id=memory_id, user_id=user_id, is_active=True
            ).first()
            if not record:
                return {'status': 'error', 'reason': 'memory_not_found'}
            record.value = new_value
            record.confidence = 1.0
            record.source = 'user_correction'
            record.last_used_at = datetime.utcnow()
            record.save()
            logger.info(f"[AIMemoryManager] Corrected memory {memory_id} for user {user_id}.")
            return {'status': 'success', 'memory_id': memory_id, 'new_value': new_value}
        except Exception as e:
            logger.error(f"[AIMemoryManager] correct failed: {e}")
            return {'status': 'error', 'reason': str(e)}
