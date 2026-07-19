# coding=utf-8
"""
Thread-local execution context for tracking the source of device actions.

Every execution path (Trigger, Conditional, Function, Scheduler, Manual)
sets its source_type before calling output_on_off(). The InfluxDB writer
reads get_extra_tags() to attach source metadata to runtime records.

Usage:
    from aot.utils.execution_context import set_execution_context, clear_execution_context

    set_execution_context('trigger', source_id=trigger.unique_id)
    try:
        output.output_on_off('on', ...)
    finally:
        clear_execution_context()
"""
import threading

_context = threading.local()


def set_execution_context(source_type, source_id=None, job_meta_id=None):
    """Set execution context on the current thread."""
    _context.source_type = source_type
    _context.source_id = source_id
    _context.job_meta_id = job_meta_id


def get_context():
    """Return the current thread's execution context as a dict."""
    return {
        'source_type': getattr(_context, 'source_type', None),
        'source_id': getattr(_context, 'source_id', None),
        'job_meta_id': getattr(_context, 'job_meta_id', None),
    }


def clear_execution_context():
    """Clear the current thread's execution context."""
    for attr in ('source_type', 'source_id', 'job_meta_id'):
        if hasattr(_context, attr):
            delattr(_context, attr)


def get_extra_tags():
    """Return InfluxDB-ready tags dict (only non-None values)."""
    ctx = get_context()
    tags = {}
    if ctx['source_type']:
        tags['source_type'] = ctx['source_type']
    if ctx['source_id']:
        tags['source_id'] = ctx['source_id']
    return tags
