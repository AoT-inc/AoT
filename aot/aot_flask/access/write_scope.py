# coding=utf-8
"""쓰기 시점 그룹 스코프 강제 — **처리기가 실제로 쓸 대상**에 묻는다.

정본 설계: `docs/design/access-scope-groups.md` §6-2a

## 왜 따로 있는가

AI·MCP 도구 호출의 그룹 스코프는 원래 **처리기보다 먼저** 인자를 훑어
대상을 짐작했다(`scope.can_operate_tool_call` + `tool_execution.
scope_arguments`). 그런데 처리기는 대상을 제각각 푼다 — 이름, 옛 별칭, 중첩
인자, 다른 모델 종류(함수 id 자리에 이름을 주면 `Conditional`·`Trigger`·`PID`
를 이름으로 찾는다), 일정 id → 그 일정의 대상, 시퀀스 단계 id → 부모 함수.
짐작과 실제가 한 군데라도 어긋나면 샌다. 검토 세 차례가 매번 새 우회를 찾은
이유가 이것이다.

그래서 **판정을 실제 대상 위로 옮긴다.** 처리기(또는 처리기가 쓰는 공용
리졸버)가 쓸 행을 손에 쥔 순간 `enforce(row)` 를 부른다. 앞의 짐작 검사는
이른 거부(승인 큐에 헛된 항목이 쌓이지 않게)로 남지만, 경계는 여기다.

## 신원

실행층이 호출 동안 **누가 쓰는가** 를 묶어 둔다(`acting_as`):

  - 외부 MCP — `tool_execution._execute_tool` 이 전송 계층이 확인한 키
    소유자(`scope_user_uuid`)로.
  - 인앱 AI — `AIActionService.execute_action` 이 요청자
    (`ai_request_context.current_requester`)로. 로그인하지 않은 요청자는
    `anonymous` 로 묶는다(제한된 자원은 전부 거부).
  - 승인 실행 — `mcp_safety_gate.execute_approved` 가 승인자로. 외부 AI 가
    승인된 확인 번호로 다시 부르면(`tool_execution._run_gated_tool`) 호출자와
    승인자 **둘 다**(`also_acting_as`).
  - 예약 발화 — `ai_scheduler_service._execute_scheduled_action` 이 예약의
    책임자(`SchedulerJobMeta.user_id`)로.
  - 웹 화면 — 일정 편집·삭제처럼 쓰기 처리기를 곧바로 부르는 라우트가
    로그인한 사람으로(`acting_as_current_user`).

묶인 것이 없으면 **사람이 없는 호출**(백그라운드 AI 잡·주기 요약·데몬)이라
면제다 — §6-1·§6-2 와 같은 근거다. 워커 스레드로 넘어갈 때는
`ai_request_context.bind_worker` 가 함께 넘긴다.

## 거부는 BaseException 이다

`WriteScopeDenied` 는 일부러 `Exception` 이 아니라 `BaseException` 을
상속한다. 처리기 여럿이 `except Exception:` 으로 조회 실패를 삼키고 다른
경로(이름 부분 일치 등)로 넘어가는데, 거부가 거기 삼켜지면 그 다른 경로가
쓰기를 해 버린다. 묶는 쪽(`acting_as` 를 연 실행층)만 이것을 잡아 거부
응답으로 바꾼다. 묶인 것이 없으면 절대 던지지 않는다.

이 모듈은 가볍게 둔다(모델·스코프는 함수 안에서 늦게 import) —
`ai_request_context` 같은 잎 모듈이 불러도 순환이 생기지 않게.
"""
import contextlib
import json
import logging
import threading
import types

logger = logging.getLogger(__name__)

_local = threading.local()


class WriteScopeDenied(BaseException):
    """묶인 사람이 이 대상을 조작할 수 없다 — 쓰기 전에 멈춘다.

    `BaseException` 인 이유는 모듈 설명 참조. 메시지는 다른 거부와 같은
    문구(`scope.deny_message`)라 처리기가 어쩌다 문자열로 바꿔 돌려줘도
    사용자에게 같은 말이 간다.
    """

    def __init__(self, resource_uuid=None):
        self.resource_uuid = resource_uuid
        super().__init__(resource_uuid)

    def __str__(self):
        return deny_message()


def deny_message():
    try:
        from aot.aot_flask.access import scope
        return scope.deny_message()
    except Exception:                    # pragma: no cover - 방어
        return "This resource is assigned to another group."


class _Principal(object):
    """이 호출 동안 쓰는 사람. uuid 는 로그에 흘리지 않는다."""
    __slots__ = ('user_uuid', 'anonymous', 'tool', 'denied', 'co', '_user',
                 '_loaded')

    def __init__(self, user_uuid=None, anonymous=False, tool=None):
        self.user_uuid = user_uuid
        self.anonymous = anonymous
        self.tool = tool
        self.denied = []
        #: 함께 판정받는 사람(`also_acting_as`) — 전원이 통과해야 쓴다.
        self.co = []
        self._user = None
        self._loaded = False

    def __repr__(self):
        return '_Principal(%s)' % ('anonymous' if self.anonymous else 'user')

    def user(self):
        """판정에 넘길 사용자 행. 익명이면 그룹도 면제도 없는 빈 사람.

        uuid 로 찾았는데 행이 없으면 None — 판정 근거가 없으므로 거부하지
        않는다(`tool_execution._scope_refusal`·예약 재검사와 같은 판단).
        """
        if self._loaded:
            return self._user
        self._loaded = True
        if self.anonymous:
            self._user = types.SimpleNamespace(id=None, role_id=None,
                                               unique_id=None, name='')
            return self._user
        try:
            from aot.databases.models import User
            self._user = User.query.filter(
                User.unique_id == self.user_uuid).first()
        except Exception:
            logger.exception('[write-scope] 사용자 조회 실패')
            self._user = None
        return self._user


def current():
    """지금 묶인 사람. 없으면 None(사람이 없는 호출)."""
    return getattr(_local, 'principal', None)


def bind(principal):
    """이미 만든 묶음을 이 스레드에 건다(`bind_worker` 용). 이전 값을 돌려준다."""
    prev = getattr(_local, 'principal', None)
    _local.principal = principal
    return prev


def restore(prev):
    _local.principal = prev


@contextlib.contextmanager
def acting_as(user_uuid=None, anonymous=False, tool=None):
    """이 블록 동안의 쓰기를 `user_uuid` 의 그룹 스코프로 판정한다.

    신원이 없으면(`user_uuid=None` 이고 익명도 아님) **바깥 묶음을 그대로
    둔다** — 인앱 요청자가 묶어 둔 채 내장 MCP 로 들어가는 경우처럼, 안쪽이
    신원을 몰라도 바깥의 사람이 계속 판정 대상이어야 한다. 바깥도 없으면
    사람이 없는 호출이다.
    """
    if not user_uuid and not anonymous:
        yield current()
        return
    principal = _Principal(user_uuid=user_uuid, anonymous=anonymous, tool=tool)
    prev = bind(principal)
    try:
        yield principal
    finally:
        restore(prev)


@contextlib.contextmanager
def also_acting_as(user_uuid, tool=None):
    """지금 묶인 사람에 **한 사람을 더** 붙인다 — 이 블록의 쓰기는 둘 다
    통과해야 한다.

    승인된 확인 번호로 다시 부르는 경로가 쓴다: 부른 사람(키 소유자·요청자)과
    승인한 사람이 다를 수 있고, 어느 한쪽만 보면 다른 쪽의 그룹 밖 대상이
    그대로 움직인다. 묶인 사람이 없으면(사람이 없는 호출) 이 사람만 묶는다.
    `user_uuid` 가 없거나 이미 묶인 사람과 같으면 아무것도 바꾸지 않는다.
    """
    cur = current()
    if not user_uuid:
        yield cur
        return
    if cur is None:
        with acting_as(user_uuid, tool=tool) as principal:
            yield principal
        return
    if not cur.anonymous and cur.user_uuid == user_uuid:
        yield cur
        return
    extra = _Principal(user_uuid=user_uuid, tool=tool or cur.tool)
    cur.co.append(extra)
    try:
        yield cur
    finally:
        try:
            cur.co.remove(extra)
        except ValueError:               # pragma: no cover - 방어
            pass


def current_user_uuid():
    """지금 **실제** 웹 요청의 로그인 사용자 uuid. 요청 밖이면 None,
    로그인하지 않았으면 ''(익명)."""
    try:
        from flask import has_request_context
        if not has_request_context():
            return None
        import flask_login
        user = flask_login.current_user
        if user is None or not getattr(user, 'is_authenticated', False):
            return ''
        return getattr(user, 'unique_id', None) or ''
    except Exception:
        logger.exception('[write-scope] 로그인 사용자 확인 실패 — 익명으로 본다')
        return ''


@contextlib.contextmanager
def acting_as_current_user(tool=None):
    """웹 라우트용 — 로그인한 사람으로 묶는다(로그인 안 했으면 익명).

    쓰기 처리기(`AoTDataToolService.*`)를 라우트가 곧바로 부르는 자리에서
    쓴다. 묶지 않으면 그 처리기의 `enforce` 가 "사람이 없는 호출" 로 보고
    아무것도 막지 않는다. 요청 밖에서 부르면 바깥 묶음을 그대로 둔다.
    """
    uid = current_user_uuid()
    if uid is None:
        yield current()
        return
    with acting_as(uid or None, anonymous=not uid, tool=tool) as principal:
        yield principal


# ---------------------------------------------------------------- 대상 풀기

_SCOPED_ROW_MODELS = ('Input', 'Output', 'Function', 'Conditional', 'Trigger',
                      'PID', 'CustomController', 'Widget', 'Tab', 'Dashboard',
                      'GeoMap', 'GeoFacility')

#: 부모 id 를 담는 자식 행 — 부모로 판정한다(`scope.can_operate_record` 가
#: 자식 행을 스코프 밖으로 두는 것과 같은 뜻: 부모를 조작할 수 있어야 한다).
_CHILD_PARENT_FIELDS = {
    'Actions': ('function_id',),
    'ConditionalConditions': ('conditional_id',),
    'FunctionChannel': ('function_id',),
    'InputChannel': ('input_id',),
    'OutputChannel': ('output_id',),
    'DeviceMeasurements': ('device_id',),
}


def _row_refs(row):
    """ORM 행 → 판정할 (모델 이름, uuid) 목록."""
    name = type(row).__name__
    uid = getattr(row, 'unique_id', None)
    if name in _SCOPED_ROW_MODELS:
        return [(name, uid)] if uid else []
    if name in _CHILD_PARENT_FIELDS:
        out = []
        for field in _CHILD_PARENT_FIELDS[name]:
            parent = getattr(row, field, None)
            if parent:
                out.extend(_id_refs(parent))
        return out
    if name == 'GeoShape':
        return _shape_refs(row)
    if name == 'SchedulerJobMeta':
        return _job_refs(row)
    return []


def _shape_refs(shape):
    """지도 도형이 가리키는 스코프 대상 — 연결된 장치와 시설.

    도형 자체(구역·자리)의 지도 단위 스코프는 여기서 새로 걸지 않는다 —
    구역 스코프는 따로 다룬다(설계 §6-2a "스코프 대상이 아닌 종류").
    """
    out = []
    device_id = getattr(shape, 'device_id', None)
    if device_id:
        out.extend(_id_refs(device_id))
    try:
        from aot.databases.models import GeoFacility
        for fac in GeoFacility.query.filter(
                GeoFacility.shape_uuid == shape.unique_id).all():
            out.append(('GeoFacility', fac.unique_id))
    except Exception:
        logger.exception('[write-scope] 시설 조회 실패')
    return out


def _job_refs(meta):
    """예약 행 → 그 예약이 움직이는 대상.

    겉의 `target_id` 와, 인자 안의 장치(이름이면 푼다)·uuid 값 전부. 일정
    id 는 uuid 모양이 아니고 대상과 이어지는 흔적도 호출 인자에 없어서, 앞의
    짐작 검사로는 볼 수 없던 자리다.
    """
    out = []
    target = getattr(meta, 'target_id', None)
    if target:
        out.extend(_id_refs(target))
    try:
        params = json.loads(getattr(meta, 'params_json', None) or '{}')
    except Exception:
        params = {}
    if isinstance(params, dict):
        from aot.aot_flask.access import scope
        args = params.get('arguments')
        for src in (params, args if isinstance(args, dict) else {}):
            for key in ('device_id', 'output_id', 'unique_id', 'target_id'):
                token = src.get(key)
                if isinstance(token, str) and token.strip():
                    out.extend(_id_refs(scope.resolve_device_token(token.strip())))
        for value in dict.fromkeys(scope._uuid_values(params)):
            out.extend(_id_refs(value))
    return out


_KIND_MODEL = {'device': 'Output', 'widget': 'Widget', 'tab': 'Tab',
               'dashboard': 'Dashboard', 'geo_map': 'GeoMap',
               'geo_facility': 'GeoFacility'}


def _id_refs(record_uuid):
    """uuid 문자열 → 판정할 (모델 이름, uuid) 목록. 스코프 대상이 아니면 [].

    장치는 모델을 가리지 않고 `Output` 으로 적는다 — 판정 근거가 **그 장치의
    탭**(`scope.tab_of_device` 가 장치 모델 전부를 본다)이라 같은 결과다.
    """
    if not isinstance(record_uuid, str) or not record_uuid.strip():
        return []
    uid = record_uuid.strip()
    from aot.aot_flask.access import scope
    found = scope._resource_of_uuid(uid)
    if found is not None:
        kind, ruid = found
        return [(_KIND_MODEL[kind], ruid)]
    try:
        from aot.databases.models import GeoShape
        shape = GeoShape.query.filter(GeoShape.unique_id == uid).first()
    except Exception:
        shape = None
    if shape is not None:
        return _shape_refs(shape)
    return []


def refs_of(target):
    """판정 대상 → (모델 이름, uuid) 목록.

    target: ORM 행 | uuid 문자열 | (모델 이름, uuid) | 그것들의 list.
    """
    if target is None:
        return []
    if (isinstance(target, tuple) and len(target) == 2
            and isinstance(target[0], str) and target[0] in _SCOPED_ROW_MODELS):
        return [target] if target[1] else []
    if isinstance(target, (list, tuple, set, frozenset)):
        out = []
        for item in target:
            out.extend(refs_of(item))
        return out
    if isinstance(target, str):
        return _id_refs(target)
    return _row_refs(target)


# ---------------------------------------------------------------- 강제

def enforce(target):
    """묶인 사람이 `target` 을 조작할 수 없으면 `WriteScopeDenied` 를 던진다.

    처리기가 **쓰기 직전**, 쓸 행을 손에 쥔 자리에서 부른다. 묶인 사람이
    없으면(사람이 없는 호출) 아무것도 하지 않는다. 스코프를 쓰지 않는
    설치(grant 0건)도 곧바로 돌아간다. 함께 묶인 사람(`also_acting_as`)이
    있으면 **전원**을 판정한다.

    판정 자체가 깨지면 **거부**로 닫는다 — 이 함수가 불리는 곳은 이미
    사람이 쓰려는 자리이고, 열린 채 실패하면 남의 장치가 움직인다.
    """
    principal = current()
    if principal is None:
        return
    for who in [principal] + list(principal.co):
        denied = _denial(who, target)
        if denied is not _ALLOWED:
            principal.denied.append(denied)
            logger.warning('[write-scope] refused %s write',
                           principal.tool or 'tool')
            raise WriteScopeDenied(denied)


_ALLOWED = object()


def _denial(principal, target):
    """이 사람이 `target` 을 쓸 수 없으면 거부된 uuid(판정 실패면 None),
    쓸 수 있으면 `_ALLOWED`. 아무것도 기록하지 않는다."""
    from aot.aot_flask.access import scope
    try:
        if not scope.scoping_active():
            return _ALLOWED
        user = principal.user()
        if user is None:
            return _ALLOWED
        if not principal.anonymous and scope.is_exempt(user):
            return _ALLOWED
        refs = refs_of(target)
    except Exception:
        logger.exception('[write-scope] 대상 판정 실패 — 거부로 닫는다')
        return None
    for name, uid in dict.fromkeys(refs):
        try:
            allowed = scope.can_operate_record(name, uid, user=user)
        except Exception:
            logger.exception('[write-scope] 판정 실패 — 거부로 닫는다')
            allowed = False
        if not allowed:
            return uid
    return _ALLOWED


def refusal(exc=None):
    """거부 응답 본문 — 앞 단계 거부(`_execute_tool`)와 같은 모양."""
    body = {"status": "refused", "reason_code": "group_scope",
            "message": deny_message()}
    if exc is not None and getattr(exc, 'resource_uuid', None):
        body["target"] = exc.resource_uuid
    return body


def was_denied(principal=None):
    """이 묶음 안에서 거부가 한 번이라도 났는가 — 처리기가 거부를 삼켰어도
    실행층이 결과를 거부로 바로잡을 수 있게."""
    principal = principal if principal is not None else current()
    return bool(principal is not None and principal.denied)
