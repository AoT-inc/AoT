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

It also carries the **requester** — who asked — so that write-permission
checks still see a person after the planner hands a step to a worker thread
(see ``bind_worker``). No requester means a background job with nobody behind
it.

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


# ── 요청을 낸 사람(requester) ─────────────────────────────────────────────
#
# 쓰기 권한 판정(역할·그룹 스코프)은 "사람이 낸 요청인가, 사람이 없는
# 백그라운드 잡인가" 를 먼저 가른다. 예전에는 그것을 Flask 의
# `has_request_context()` 로 판정했는데, 계획 실행기의 병렬 단계처럼 **요청
# 스레드에서 워커 스레드로 넘어간 호출**은 요청 컨텍스트가 없어 백그라운드로
# 오인되고 검사를 통째로 건너뛰었다(2026-09-23 재현: Monitor 가 계획 단계로
# 노트를 저장).
#
# 그래서 사람을 **명시적 표지**로 들고 다닌다. 요청 스레드에서 잡아 두고
# (`current_requester`), 워커로 넘길 때 함께 넘긴다(`bind_worker`). 표지가
# 없으면 사람이 없는 호출이다 — 스케줄러·Function 이 부르는 AI 는 표지를
# 만들지 않으므로 지금처럼 면제다.

# 코드가 스스로 연 test_request_context 에 붙이는 표지(environ 키). 요청마다
# 따로라 바깥의 진짜 요청으로 새지 않는다(`g` 는 앱 컨텍스트를 공유할 수 있어
# 쓰지 않는다). aot/tools/tool_execution.py 도 같은 문자열을 쓴다.
SYNTHETIC_REQUEST_KEY = 'aot.synthetic_request'


def mark_synthetic_request():
    """지금 요청 컨텍스트를 '코드가 연 가짜 요청' 으로 표시한다."""
    try:
        from flask import has_request_context, request
        if has_request_context():
            request.environ[SYNTHETIC_REQUEST_KEY] = True
    except Exception:
        pass


class Requester(tuple):
    """요청을 낸 사람. `user_uuid` 가 None 이면 로그인하지 않은 사람이다
    (사람은 있으나 신원이 없다 → 쓰기는 거부)."""
    __slots__ = ()

    def __new__(cls, user_uuid):
        return tuple.__new__(cls, (user_uuid,))

    @property
    def user_uuid(self):
        return self[0]

    def __repr__(self):                  # uuid 를 로그에 흘리지 않는다
        return 'Requester(%s)' % ('user' if self[0] else 'anonymous')


def get_requester():
    """이 스레드에 묶인 요청자 표지. 없으면 None(사람이 없는 호출)."""
    return getattr(_local, 'requester', None)


def set_requester(requester):
    """요청자 표지를 묶고 이전 값을 돌려준다(`restore_requester` 에 넘긴다)."""
    prev = getattr(_local, 'requester', None)
    _local.requester = requester
    return prev


def restore_requester(prev):
    _local.requester = prev


def requester_from_flask():
    """지금 스레드의 **실제** Flask 요청에서 요청자를 만든다. 요청이 없으면 None.

    요청이 있다는 것 자체가 사람이 있다는 뜻이다(HTTP 로 들어온 호출).
    로그인하지 않았으면 신원 없는 요청자다. 이 함수는 호출자가 가짜 요청
    컨텍스트(test_request_context)를 밀어 넣기 **전에** 불러야 한다.
    """
    try:
        from flask import has_request_context, request
        if not has_request_context():
            return None
        # 코드가 스스로 밀어 넣은 가짜 요청(도구 실행·execute_action 이 gettext
        # 때문에 여는 test_request_context)은 사람이 아니다. 외부 MCP 호출은
        # 그 안에서 돌지만 키 역할로 이미 게이트를 지났다.
        if request.environ.get(SYNTHETIC_REQUEST_KEY):
            return None
        import flask_login
        user = flask_login.current_user
        if user is None or not getattr(user, 'is_authenticated', False):
            return Requester(None)
        from aot.databases.models import User
        row = User.query.filter(User.name == user.name).first()
        return Requester(row.unique_id if row else None)
    except Exception:
        # 요청은 있는데 신원을 못 읽었다 — 사람이 있는 쪽으로(=쓰기 거부) 닫는다.
        return Requester(None)


def current_requester():
    """요청자: 묶인 표지가 있으면 그것, 없으면 실제 Flask 요청의 로그인 사용자.

    둘 다 없으면 None — 사람이 없는 백그라운드 호출이다.
    """
    rq = get_requester()
    if rq is not None:
        return rq
    return requester_from_flask()


def bind_worker(fn):
    """Wrap ``fn`` so a worker thread runs it under the CALLER's thread_id and
    requester.

    Thread pools start with an empty ``threading.local``. Two things must
    survive the hop:

      - thread_id — the session key of the MCP call-quality ledger.
      - requester — who asked. Without it a worker looks like a background
        job and the write-permission checks (role, group scope) are skipped.
      - the write-scope principal (``aot.aot_flask.access.write_scope``) —
        who the write-time group-scope check judges, if one is bound.

    Call this in the submitting (request) thread — the requester is captured
    at wrap time. Only these are carried over — attachments, depth and
    autonomy stay exactly as a bare worker thread sees them (unset), so in-app
    AI behaviour does not change. The worker's previous values are restored
    afterwards because pool threads are reused.
    """
    tid = get_thread_id()
    rq = current_requester()
    # 쓰기 시점 그룹 스코프의 묶음(write_scope)도 함께 넘긴다 — 묶인 호출
    # 안에서 워커로 넘어간 쓰기가 "사람이 없는 호출" 로 보이면 면제가 된다.
    from aot.aot_flask.access import write_scope as _ws
    principal = _ws.current()

    def _run(*args, **kwargs):
        prev_tid = getattr(_local, 'thread_id', None)
        prev_rq = getattr(_local, 'requester', None)
        _local.thread_id = tid
        _local.requester = rq
        prev_ws = _ws.bind(principal)
        try:
            return fn(*args, **kwargs)
        finally:
            _local.thread_id = prev_tid
            _local.requester = prev_rq
            _ws.restore(prev_ws)

    return _run


# 예전 이름. 이제 요청자도 함께 넘긴다.
bind_thread_id = bind_worker
