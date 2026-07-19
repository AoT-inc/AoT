# coding=utf-8
import logging
from sqlalchemy import text
from aot.databases.models import AITask
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

def task_status_aggregator(task_id):
    """
    Recursively calculates and updates the status of a parent task based on its children.
    
    Status rollup rules:
    - If any child is 'failed' -> parent is 'failed' (unless overridden by business logic).
    - If any child is 'in_progress' -> parent is 'in_progress'.
    - If all children are 'completed' -> parent is 'completed'.
    - CHECKPOINT GATE: If a child of type 'checkpoint' is NOT 'completed', 
      the parent cannot transition to 'completed'.
    
    :param task_id: unique_id of the task to aggregate.
    :return: The aggregated status string.
    """
    task = AITask.query.filter_by(unique_id=task_id).first()
    if not task:
        return None

    children = task.children
    if not children:
        return task.status

    # Recursive call to update all children first (bottom-up)
    child_statuses = []
    for child in children:
        status = task_status_aggregator(child.unique_id)
        child_statuses.append((child.task_type, status))

    # Aggregation Logic
    new_status = 'pending'
    
    # Check for failure
    if any(status == 'failed' for _, status in child_statuses):
        new_status = 'failed'
    # Check for in_progress
    elif any(status == 'in_progress' for _, status in child_statuses):
        new_status = 'in_progress'
    # Check for completion (with Checkpoint Gate)
    elif all(status == 'completed' for _, status in child_statuses):
        new_status = 'completed'
    else:
        # Mix of pending/completed/etc.
        if any(status == 'completed' for _, status in child_statuses):
            new_status = 'in_progress'
        else:
            new_status = 'pending'

    # Checkpoint Gate Enforcement
    has_uncompleted_checkpoint = any(
        t_type == 'checkpoint' and status != 'completed' 
        for t_type, status in child_statuses
    )
    
    if has_uncompleted_checkpoint and new_status == 'completed':
        new_status = 'in_progress'  # Blocked by checkpoint

    # Update if changed (caller handles final commit)
    if task.status != new_status:
        logger.info(f"Task {task.unique_id} ({task.title}) status updated: {task.status} -> {new_status}")
        task.status = new_status
        db.session.flush()

    return new_status


def sync_parent_dates(parent_id):
    """
    Recalculates a parent task's start_date and end_date from its children's range.
    Recursively walks up to update grandparent if needed.
    """
    parent = AITask.query.filter_by(unique_id=parent_id).first()
    if not parent:
        return

    children = parent.children
    if not children:
        return

    min_start = None
    max_end = None

    for child in children:
        if child.start_date:
            if min_start is None or child.start_date < min_start:
                min_start = child.start_date
        if child.end_date:
            if max_end is None or child.end_date > max_end:
                max_end = child.end_date

    changed = False
    if min_start and parent.start_date != min_start:
        parent.start_date = min_start
        changed = True
    if max_end and parent.end_date != max_end:
        parent.end_date = max_end
        changed = True

    if changed:
        logger.info(f"Parent {parent.unique_id} ({parent.title}) dates synced: {min_start} ~ {max_end}")
        db.session.commit()
        # Recursively update grandparent
        if parent.parent_id:
            sync_parent_dates(parent.parent_id)


def prevent_cycle(parent_id, child_id):
    """
    Checks if setting child_id's parent to parent_id would create a cycle.
    Uses a simple recursive check.
    """
    if not parent_id:
        return False
    
    if parent_id == child_id:
        return True
    
    current_parent = AITask.query.filter_by(unique_id=parent_id).first()
    while current_parent and current_parent.parent_id:
        if current_parent.parent_id == child_id:
            return True
        current_parent = AITask.query.filter_by(unique_id=current_parent.parent_id).first()
        
    return False
