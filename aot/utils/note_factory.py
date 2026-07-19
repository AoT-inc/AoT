# coding=utf-8
"""
note_factory.py — shared utility for safely creating Notes records from daemon processes.

Works via session_scope(AOT_DB_PATH) without a Flask app context, so it can be
imported from Action modules, base_function, and any other daemon component.
"""
import logging
import re

from aot.config import AOT_DB_PATH
from aot.databases.models import Notes, NoteTags
from aot.databases.utils import session_scope

logger = logging.getLogger(__name__)


def create_note_record(
    note_text,
    *,
    name=None,
    tag_ids=None,
    tag_names=None,
    target_id=None,
    target_type=None,
    category='general',
    priority=0,
    gps_lat=None,
    gps_lng=None,
    append_text=None,
):
    """Create a Notes record and return its unique_id. Returns None on failure.

    Tag resolution priority:
      1. tag_ids  — list of already-validated UUIDs (checked for DB existence)
      2. tag_names — list of names; created automatically if missing

    :param note_text:    note body (required)
    :param name:         title; if None, auto-extracted from the first body line
    :param tag_ids:      list of NoteTags.unique_id strings
    :param tag_names:    list of tag name strings (used when tag_ids is absent)
    :param target_id:    unique_id of the linked target entity
    :param target_type:  'function' | 'input' | 'output' | 'device', etc.
    :param category:     'general' | 'observation' | 'alarm' | 'maintenance'
    :param priority:     0=normal, 1=high, 2=critical
    :param gps_lat:      latitude (float, optional)
    :param gps_lng:      longitude (float, optional)
    :param append_text:  text to append at the end of the body (system messages, etc.)
    :return:             the created Notes.unique_id, or None
    """
    try:
        body = (note_text or '').strip()
        if append_text:
            body = body + '\n\n' + append_text.strip() if body else append_text.strip()

        final_name = (name or '').strip()
        if not final_name:
            first_line = body.split('\n')[0].strip()
            final_name = (first_line[:47] + '...') if len(first_line) > 50 else first_line
            if not final_name:
                final_name = 'New Note'

        with session_scope(AOT_DB_PATH) as session:
            resolved_ids = []

            if tag_ids:
                for tid in tag_ids:
                    tid = tid.strip()
                    if not tid:
                        continue
                    exists = session.query(NoteTags).filter(NoteTags.unique_id == tid).first()
                    if exists:
                        resolved_ids.append(tid)
                    else:
                        logger.warning(f"[note_factory] tag UUID '{tid}' not found, skipping")

            elif tag_names:
                for tname in tag_names:
                    tname = tname.strip()
                    if not tname:
                        continue
                    tag = session.query(NoteTags).filter(NoteTags.name == tname).first()
                    if tag:
                        resolved_ids.append(tag.unique_id)
                    else:
                        new_tag = NoteTags(name=tname)
                        session.add(new_tag)
                        session.flush()
                        resolved_ids.append(new_tag.unique_id)
                        logger.debug(f"[note_factory] tag '{tname}' auto-created")

            new_note = Notes()
            new_note.name = final_name
            new_note.note = body
            new_note.tags = ','.join(resolved_ids)
            new_note.target_id = target_id
            new_note.target_type = target_type
            new_note.category = category
            new_note.priority = int(priority)
            new_note.gps_lat = gps_lat
            new_note.gps_lng = gps_lng

            # Detect [task:UUID] pattern → auto-set parent_task_id
            task_match = re.search(r'\[task:([a-f0-9\-]{36})\]', body, re.I)
            if task_match:
                new_note.parent_task_id = task_match.group(1)

            session.add(new_note)
            session.flush()
            note_uid = new_note.unique_id

        logger.info(f"[note_factory] note created: {note_uid} (target={target_type}:{target_id})")
        return note_uid

    except Exception as e:
        logger.exception(f"[note_factory] note creation failed: {e}")
        return None
