# coding=utf-8
"""예약된 작업이 **실행되지 않았는데** COMPLETED 로 기록되는 것을 막는다.

2026-08-13 감사의 결과를 고정한다. 사건은 이랬다: 지도 위젯에서 만든 출력
예약 10건이 전부 예정 시각 1~3초 안에 정시 발화했고, `SchedulerJobMeta` 에는
전부 COMPLETED 로 남았고, **장치는 한 번도 켜지지 않았다.** 승인 큐에는 아무도
답할 수 없는 pending 확인요청만 쌓였다.

원인은 한 줄짜리 버그가 아니라 반복되는 **모양**이다 —

    바깥 status 만 보고 성공이라 부른다.

실행되지 않았다는 사실은 예외가 아니라 **정상 응답의 내용물**로 온다:
  - 승인 게이트: {"status":"pending_approval", ... "It was NOT executed ..."}
  - 게이트 거부: {"status":"refused","reason_code":"rate_limited", ...}
  - 도구 자체 실패: {"status":"success","result":{"error": ...}} (한 겹 감싼 것)
  - MCP 규격 오류: {"result":{"isError":true, ...}}
  - 데몬: 예외를 안 던지고 None 이나 (code, msg) 를 돌려준다
  - 아예 안 돈 경우: APScheduler 의 misfire — 이벤트조차 EXECUTED 가 아니다

여기 있는 검사는 DB·데몬·무선·MCP 서브프로세스를 하나도 건드리지 않는다.
"""
import ast
import inspect
import json
import pathlib

import pytest


# ── 응답 표본 ────────────────────────────────────────────────────────────────
# 실제 관측된 모양 그대로. MCP 응답은 result.content[].text 안에 JSON 문자열이
# 한 겹 더 들어 있어서, 바깥 dict 만 보면 어느 것도 실패로 보이지 않는다.

def _mcp(payload):
    return {'status': 'success',
            'result': {'content': [{'type': 'text',
                                    'text': json.dumps(payload, ensure_ascii=False)}]}}


PENDING_APPROVAL = _mcp({
    "status": "pending_approval", "reason_code": "awaiting_user",
    "confirmation_id": "3d68648f-ad95-4e70-aa97-286e7969e718",
    "tool_name": "operate_device",
    "message": ("This tool changes system state, so it needs user approval. "
                "It was NOT executed."),
    "call_state": "pending_approval",
})

REFUSED_RATE_LIMITED = _mcp({
    "status": "refused", "reason_code": "rate_limited",
    "message": "Rate limit exceeded for 'operate_device': 20 calls/hour.",
    "call_state": "refused",
})

REFUSED_WRITE_DISABLED = _mcp({
    "status": "refused", "reason_code": "write_disabled",
    "message": "This server is in advice-only mode (AOT_MCP_WRITE_ENABLED=0).",
    "call_state": "refused",
})

TOOL_FAILED = _mcp({
    "status": "error", "message": "Output not found", "call_state": "failed",
})

GENUINE_SUCCESS = _mcp({
    "status": "success", "message": "Output turned on", "call_state": "executed",
})

EXECUTED_ON_APPROVAL = _mcp({
    "status": "already_executed", "reason_code": "executed_on_approval",
    "result": {"status": "success"}, "call_state": "already_executed",
})

LEGACY_BLOCKED = {
    "status": "error",
    "message": "[LEGACY_BLOCKED] 'output' action type is deprecated.",
}

MCP_IS_ERROR = {'status': 'success',
                'result': {'isError': True,
                           'content': [{'type': 'text', 'text': 'device busy'}]}}

EMPTY_CONTENT = {'status': 'success', 'result': {'content': []}}


# ── 1. 스케줄러의 미실행 판정 ────────────────────────────────────────────────

def _detect(retval):
    from aot.ai.services.ai_scheduler_service import AISchedulerService
    return AISchedulerService._retval_indicates_not_executed(retval)


@pytest.mark.parametrize('name,retval', [
    ('pending_approval', PENDING_APPROVAL),
    ('refused/rate_limited', REFUSED_RATE_LIMITED),
    ('refused/write_disabled', REFUSED_WRITE_DISABLED),
    ('tool failed inside success wrapper', TOOL_FAILED),
    ('legacy blocked', LEGACY_BLOCKED),
    ('MCP isError', MCP_IS_ERROR),
])
def test_not_executed_payloads_are_detected(name, retval):
    """바깥이 success 여도 안이 '실행 안 함'이면 잡아야 한다.

    이 중 pending_approval 은 실측된 사건 그 자체다(meta id 272~281).
    refused 계열은 같은 게이트의 다른 출구인데 'pending_approval' 이라는
    단어가 없어서, 문자열 마커만 보던 초기 수정본을 그대로 통과했다.
    """
    assert _detect(retval), f"{name}: 미실행을 성공으로 통과시켰다"


@pytest.mark.parametrize('name,retval', [
    ('genuine success', GENUINE_SUCCESS),
    ('already executed at approval time', EXECUTED_ON_APPROVAL),
    ('plain string result', 'Setpoint set to 24.0'),
    ('none', None),
])
def test_executed_payloads_are_not_flagged(name, retval):
    """과대탐지를 택했지만, 실제로 실행된 것을 실패로 뒤집으면 안 된다.

    already_executed 가 특히 중요하다 — 사람이 승인 버튼을 누른 순간 서버가
    이미 실행한 경우(p6_26)라서, 이걸 미실행으로 적으면 켜진 장치가 꺼진 것으로
    기록된다.
    """
    assert _detect(retval) is None, f"{name}: 정상 실행을 실패로 뒤집었다"


def test_every_non_executed_call_state_is_detected():
    """`call_state` 어휘가 늘어나면 이 검사가 먼저 깨져야 한다.

    `mcp_safety_gate.CALL_STATES` 가 정본이다. 새 상태(예: 'deferred')를
    추가하면서 스케줄러 쪽 판정을 안 고치면, 그 상태의 미실행이 조용히
    COMPLETED 로 기록된다. 그래서 목록을 여기 복사하지 않고 SSOT 에서 읽는다.
    """
    from aot.ai.services import mcp_safety_gate
    from aot.ai.services.ai_scheduler_service import AISchedulerService

    executed = AISchedulerService._EXECUTED_CALL_STATES
    assert executed <= set(mcp_safety_gate.CALL_STATES), \
        "실행됨으로 보는 call_state 가 SSOT 에 없다"

    for state in mcp_safety_gate.CALL_STATES:
        payload = _mcp({"status": "whatever", "call_state": state})
        got = _detect(payload)
        if state in executed:
            assert got is None, f"call_state={state} 는 실행된 것인데 실패로 잡혔다"
        else:
            assert got, f"call_state={state} 는 미실행인데 성공으로 통과했다"


def test_gate_refusal_reason_codes_are_all_covered():
    """`call_state` 키가 없는 응답에서도 게이트 거부를 알아봐야 한다.

    call_state 는 `aot_mcp_server._execute_tool` 이 찍는다 — 즉 그 서버를 지나온
    응답에만 있다. `mcp_safety_gate.gate()` 를 다른 자리에서 직접 부르면(현재
    routes_mcp_api·aot_data_tool_service 가 그렇다) reason_code 만 남는다.
    """
    from aot.ai.services import mcp_safety_gate

    src = pathlib.Path(inspect.getsourcefile(mcp_safety_gate)).read_text(encoding='utf-8')
    tree = ast.parse(src)
    codes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == 'reason_code'
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                codes.add(value.value)

    assert 'awaiting_user' in codes, "게이트 소스에서 reason_code 를 못 읽었다"
    # 승인 시점에 이미 실행된 건은 미실행이 아니다 — 유일한 예외.
    codes.discard('executed_on_approval')

    for code in sorted(codes):
        payload = _mcp({"status": "refused", "reason_code": code, "message": "x"})
        assert _detect(payload), f"reason_code={code} 를 성공으로 통과시켰다"


# ── 2. 물리 실행 검증 (PC-099 "Fake Success is prohibited") ──────────────────

def _verify(result):
    from aot.ai.services.resolvers.physical_control_resolver import PhysicalControlResolver
    return PhysicalControlResolver()._verify_physical_outcome(
        'operate_device', json.loads(json.dumps(result)))


@pytest.mark.parametrize('name,result', [
    ('pending_approval', PENDING_APPROVAL),
    ('refused/rate_limited', REFUSED_RATE_LIMITED),
    ('MCP isError', MCP_IS_ERROR),
    ('no content at all', EMPTY_CONTENT),
    ('explicit failure keyword', _mcp({"status": "error", "message": "Device control failed"})),
])
def test_physical_outcome_rejects_non_execution(name, result):
    """실행 증거가 없으면 성공이라 부르지 않는다.

    내용 없는 응답(`EMPTY_CONTENT`)이 특히 고약했다 — 검사 대상 문자열이 ''
    이라 키워드 검사가 통째로 건너뛰어지고 곧장
    "[LAW_3][PHYSICAL_VERIFIED] hardware execution confirmed" 가 찍혔다.
    """
    out = _verify(result)
    assert out.get('status') == 'error', f"{name}: 미실행을 물리 성공으로 확인했다"
    assert out.get('physical_outcome') != 'success'


def test_physical_outcome_accepts_real_success():
    out = _verify(GENUINE_SUCCESS)
    assert out.get('status') == 'success'
    assert out.get('physical_outcome') == 'success'


def test_physical_outcome_reads_every_text_block():
    """텍스트 블록이 여럿이면 전부 본다 — 첫 블록만 보고 break 하면 못 잡는다."""
    result = {'status': 'success', 'result': {'content': [
        {'type': 'text', 'text': 'command queued'},
        {'type': 'text', 'text': 'device returned an error'},
    ]}}
    assert _verify(result).get('status') == 'error'


# ── 3. 감싸기 삼킴 — {"status":"success","result": <실패 페이로드>} ──────────

@pytest.mark.parametrize('name,inner', [
    ('needs_disambiguation', {"status": "needs_disambiguation",
                              "error": "target_not_found", "message": "위치를 특정 못함"}),
    ('bare error key', {"error": "Device (output) to control not found: xxx"}),
    ('inner error status', {"status": "error", "message": "boom"}),
])
def test_schedule_resolver_does_not_wrap_failure_as_success(name, inner):
    """ScheduleResolver 는 도구가 만든 실패를 그대로 감싸 성공으로 만들었다.

    `add_schedule_tool` 은 위치를 해석 못 하면 예외 대신
    {"status":"needs_disambiguation", ...} 를 돌려준다. 예전 코드는
    `return {"status": "success", "result": res}` 였으므로 **일정이 하나도
    만들어지지 않았는데 등록 성공으로 기록됐다.** 같은 파일의
    VirtualToolResolver 는 이미 result.get('error') 를 검사하고 있었다.
    """
    from aot.ai.services.resolvers.schedule_resolver import ScheduleResolver
    out = ScheduleResolver._wrap('add_schedule', inner)
    assert out['status'] == 'error', f"{name}: 실패 페이로드를 success 로 감쌌다"
    assert out.get('result') == inner, "원본 페이로드는 진단을 위해 보존해야 한다"
    assert _detect(out), "스케줄러 판정도 이 결과를 미실행으로 봐야 한다"


def test_schedule_resolver_passes_real_success():
    from aot.ai.services.resolvers.schedule_resolver import ScheduleResolver
    inner = {"status": "success", "message": "Scheduled", "scheduler_job_id": 7}
    assert ScheduleResolver._wrap('add_schedule', inner)['status'] == 'success'


def _virtual_tool_result(monkeypatch, payload):
    """VirtualToolResolver 를 가짜 핸들러 하나로 돌린다 (DB·데몬 없음)."""
    from aot.ai.services import tool_registry
    from aot.ai.services.resolvers.virtual_tool_resolver import VirtualToolResolver

    monkeypatch.setattr(tool_registry, 'build_tool_map',
                        lambda *a, **k: {'probe_tool': lambda **kw: payload})
    return VirtualToolResolver().execute(
        'virtual_tool_call', 'system_internal', {'tool_name': 'probe_tool'}, None, True)


@pytest.mark.parametrize('name,payload', [
    ('bare error key', {"error": "Device (output) to control not found"}),
    ('inner error status', {"status": "error", "message": "boom"}),
])
def test_virtual_tool_failures_are_not_wrapped_as_success(monkeypatch, name, payload):
    """가상 도구도 실패 관행이 둘이다 — 한쪽만 보면 절반이 샌다.

    `mcp_safety_gate.call_state()` 의 주석이 실측 근거다: {"status":"error"} 38곳,
    {"error": ...} 217곳. 이 리졸버는 뒤쪽만 봤다.
    """
    out = _virtual_tool_result(monkeypatch, payload)
    assert out['status'] == 'error', f"{name}: 실패를 success 로 감쌌다"


def test_virtual_tool_needs_disambiguation_is_not_an_error(monkeypatch):
    """되묻기는 실패가 아니다.

    resolve_target 같은 읽기 도구의 정상 결과이고, 프롬프트가 그 status 를 보고
    사용자에게 확인하도록 안내한다. 여기서 error 로 바꾸면 그 흐름이 끊긴다 —
    "일정이 안 만들어졌다"는 판정은 ScheduleResolver 자리에서만 한다.
    """
    out = _virtual_tool_result(monkeypatch, {
        "status": "needs_disambiguation", "available_targets": ['3-1', '3-2']})
    assert out['status'] == 'success'


# ── 4. 데몬 반환값을 안 읽고 성공이라 하는 자리 (정적 검사) ──────────────────

def _execute_action_ast():
    from aot.ai.services import ai_action_service
    src = pathlib.Path(inspect.getsourcefile(ai_action_service)).read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 'execute_action':
            return node
    raise AssertionError('execute_action 을 못 찾았다')


def _is_success_return_of(stmt, name):
    """`return {"status": "success", "result": <name>}` 인가."""
    if not (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict)):
        return False
    pairs = {}
    for key, value in zip(stmt.value.keys, stmt.value.values):
        if isinstance(key, ast.Constant):
            pairs[key.value] = value
    status = pairs.get('status')
    result = pairs.get('result')
    return (isinstance(status, ast.Constant) and status.value == 'success'
            and isinstance(result, ast.Name) and result.id == name)


def test_no_daemon_call_is_returned_as_success_unchecked():
    """DaemonControl 호출 결과를 검사 없이 success 로 감싸면 안 된다.

    `aot_client.daemon_call_failed` 의 docstring 이 그대로 설명한다: 제어 메서드는
    Pyro5 타임아웃과 통신 오류를 **잡아서** (code, msg) 로 돌려주고, 데몬 쪽
    `pid_set`/`trigger_all_actions` 는 예외를 로그만 남기고 None 또는 오류
    문자열을 돌려준다. 그래서 try/except 만으로는 실패가 보이지 않는다 —
    예약된 PID 조정은 PID 가 꺼져 있어도 매번 COMPLETED 였다.

    AST 로 보는 이유: 이 함수는 app context·타깃 해석·데몬 프록시를 요구해서
    분기 하나를 부르려면 앱을 통째로 세워야 한다. 검사가 무거우면 안 돌아가고,
    안 도는 검사는 없는 검사다.
    """
    fn = _execute_action_ast()
    offenders = []
    for parent in ast.walk(fn):
        body = getattr(parent, 'body', None)
        if not isinstance(body, list):
            continue
        for stmt, nxt in zip(body, body[1:]):
            if not (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)):
                continue
            func = stmt.value.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == 'daemon'):
                continue
            target = stmt.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if _is_success_return_of(nxt, target.id):
                offenders.append(f"line {stmt.lineno}: daemon.{func.attr}() → "
                                 f"return success without reading {target.id}")

    assert not offenders, (
        "데몬 반환값을 검사하지 않고 성공으로 보고하는 자리:\n  " + "\n  ".join(offenders))


# ── 5. 건너뛴 실행(misfire)도 들어야 한다 ────────────────────────────────────

def test_scheduler_listens_for_missed_jobs():
    """EVENT_JOB_MISSED 리스너가 실제로 등록돼 있어야 한다.

    예전에는 EXECUTED|ERROR 만 들었다. 앱이 misfire_grace_time 보다 오래 내려가
    있으면 그 예약은 실행되지 않고 이벤트만 나는데, 아무도 안 들으므로
    1회성 예약은 PENDING 인 채 영원히 남고 반복 예약은 **직전 성공의 COMPLETED
    가 그대로 남아 이번 회차가 건너뛰어진 사실이 어디에도 안 남는다.**

    소스를 AST 로 본다 — get_scheduler() 를 부르면 SQLAlchemyJobStore 가 실제
    스케줄러 DB 를 연다.
    """
    from aot.ai.services import ai_scheduler_service as svc

    src = pathlib.Path(inspect.getsourcefile(svc)).read_text(encoding='utf-8')
    tree = ast.parse(src)

    listened = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_listener'):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id.startswith('EVENT_JOB_'):
                    listened.add(sub.id)

    for event in ('EVENT_JOB_EXECUTED', 'EVENT_JOB_ERROR', 'EVENT_JOB_MISSED'):
        assert event in listened, f"{event} 를 듣지 않는다"

    assert callable(getattr(svc, '_job_missed_listener', None))


# ── 6. 예약 실행 경로가 미실행을 COMPLETED 로 적지 않는다 ───────────────────

class _FakeAppContext(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeApp(object):
    def app_context(self):
        return _FakeAppContext()


@pytest.mark.parametrize('name,result,expect_completed', [
    ('pending_approval', PENDING_APPROVAL, False),
    ('refused', REFUSED_RATE_LIMITED, False),
    ('genuine success', GENUINE_SUCCESS, True),
])
def test_execute_scheduled_action_state(monkeypatch, name, result, expect_completed):
    """`_execute_scheduled_action` 자신도 바깥 status 만 보면 안 된다.

    리스너가 뒤이어 같은 판정을 한 번 더 하지만, 리스너가 못 돌면 여기서 적힌
    값이 최종본이 된다.
    """
    from aot.ai.services import ai_scheduler_service as svc
    from aot.ai.services import ai_action_service, safety_service

    monkeypatch.setattr(svc, '_flask_app', _FakeApp())
    monkeypatch.setattr(safety_service.SafetyService, 'validate',
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(ai_action_service.AIActionService, 'execute_action',
                        staticmethod(lambda *a, **k: result))
    monkeypatch.setattr(svc, 'set_execution_context', lambda **k: None)
    monkeypatch.setattr(svc, 'clear_execution_context', lambda: None)

    written = {}

    def _update(meta_id, state, execution_result=None):
        written['state'] = state
        written['result'] = execution_result

    monkeypatch.setattr(svc.AISchedulerService, 'update_job_state', staticmethod(_update))

    svc._execute_scheduled_action('mcp_tool_call', 'srv-1', {}, meta_id=1)

    if expect_completed:
        assert written['state'] == svc.JOB_STATE_COMPLETED
    else:
        assert written['state'] == svc.JOB_STATE_FAILED, \
            f"{name}: 실행되지 않은 예약을 COMPLETED 로 적었다"
        # 근거가 잘림 앞쪽에 있어야 진단이 된다.
        assert written['result'].startswith('NOT EXECUTED:')
