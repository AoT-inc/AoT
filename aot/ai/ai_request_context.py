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
    )


def push(attachments=None, depth=None, autonomy=None):
    """Set the current request's AI context and return the previous snapshot
    (an opaque token to hand back to :func:`pop`)."""
    prev = _snapshot()
    _local.attachments = list(attachments) if attachments else []
    _local.depth = depth
    _local.autonomy = autonomy
    return prev


def pop(token):
    """Restore the context captured by a prior :func:`push`."""
    attachments, depth, autonomy = token
    _local.attachments = attachments
    _local.depth = depth
    _local.autonomy = autonomy


def get_attachments():
    """List of {media_type, base64_data} for the current turn (never None)."""
    return getattr(_local, 'attachments', None) or []


def get_depth():
    """'fast' | 'deep' | None."""
    return getattr(_local, 'depth', None)


def get_autonomy():
    """'advice' | 'approve' | 'auto' | None."""
    return getattr(_local, 'autonomy', None)
