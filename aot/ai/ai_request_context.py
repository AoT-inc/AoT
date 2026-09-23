# coding=utf-8
"""Request-scoped AI context (thread-local).

Carries per-request chat inputs that must reach deep into the reasoning
pipeline — image attachments and the judgment-level controls (depth /
autonomy) — WITHOUT threading them through the dozens of fan-out call
signatures in ``AIAgentService``.

The whole reasoning pipeline for one chat turn runs synchronously in a single
thread (the Flask request thread for non-streaming, or the single SSE
background thread for streaming), so a ``threading.local`` is visible to every
provider ``run_reasoning`` call in that turn. ``process_natural_language_command``
pushes the context on entry and restores the previous values on exit, so nested
re-entry (e.g. the goal loop) does not clobber the outer turn's context.

Kept as a leaf module (no imports from services/agents) so both the service
layer and the provider engines can import it without a circular dependency.

@phase active
@stability stable
"""
import threading

_local = threading.local()


def _snapshot():
    return (
        getattr(_local, 'attachments', None),
        getattr(_local, 'depth', None),
        getattr(_local, 'autonomy', None),
        getattr(_local, 'thread_id', None),
    )


def push(attachments=None, depth=None, autonomy=None, thread_id=None):
    """Set the current request's AI context and return the previous snapshot
    (an opaque token to hand back to :func:`pop`)."""
    prev = _snapshot()
    _local.attachments = list(attachments) if attachments else []
    _local.depth = depth
    _local.autonomy = autonomy
    _local.thread_id = thread_id
    return prev


def pop(token):
    """Restore the context captured by a prior :func:`push`."""
    attachments, depth, autonomy, thread_id = token
    _local.attachments = attachments
    _local.depth = depth
    _local.autonomy = autonomy
    _local.thread_id = thread_id


def get_attachments():
    """List of {media_type, base64_data} for the current turn (never None)."""
    return getattr(_local, 'attachments', None) or []


def get_depth():
    """'fast' | 'deep' | None."""
    return getattr(_local, 'depth', None)


def get_autonomy():
    """'advice' | 'approve' | 'auto' | None."""
    return getattr(_local, 'autonomy', None)


def get_thread_id():
    """The chat thread this turn belongs to, or None (background jobs).

    Used as the session key of the MCP call-quality ledger so that the tool
    calls of one conversation can be grouped. It is hashed before storage.
    """
    return getattr(_local, 'thread_id', None)


def bind_thread_id(fn):
    """Wrap ``fn`` so a worker thread runs it under the CALLER's thread_id.

    Thread pools start with an empty ``threading.local``, so tool calls made
    from worker threads (the planner's parallel steps) would lose the chat
    thread and land in the quality ledger without a session key. Only the
    thread_id is carried over — attachments, depth and autonomy are left
    exactly as a bare worker thread sees them today (unset), so in-app AI
    behaviour does not change. The worker's previous thread_id is restored
    afterwards because pool threads are reused.
    """
    tid = get_thread_id()

    def _run(*args, **kwargs):
        prev = getattr(_local, 'thread_id', None)
        _local.thread_id = tid
        try:
            return fn(*args, **kwargs)
        finally:
            _local.thread_id = prev

    return _run
