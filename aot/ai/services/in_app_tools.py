# -*- coding: utf-8 -*-
"""인앱 AI 의 도구 표면 — 도메인 명부 하나(아키텍처 개선 26-11 5단계).

예전에는 인앱 AI 가 옛 도구 112개(system_tools, 약 65,000자)와 도메인 도구(내장
MCP 서버를 등록한 설치에서만)를 함께 받았다. 같은 기능에 두 표면이면 모델은 한쪽만
쓰고 다른 쪽은 검증되지 않은 채 썩는다(ops-archive "도구 실행층은 MCP 가 아니다").
이제 인앱 AI 가 보는 도구는 외부 MCP 와 같은 도메인 도구 14개뿐이다.

이 모듈이 하는 일은 셋이다.

1. **목록** — `domain_tool_entries()`: `tools_for_agent` 의 도메인 명부를 인앱
   매니페스트 항목 모양({tool_name, description, usage_hint})으로.
2. **승인 판정** — `requires_approval()`: 도메인 쓰기 호출이 풀리는 **안쪽 도구**로
   판정한다. 도메인 이름(`control`)만 보면 승인 집합에 없어서, 엔진의 자체 도구
   루프(gemini·anthropic)가 장치 제어를 승인 없이 실행하려 든다.
3. **실행 길** — `normalize()`: 승인이 필요한 쓰기는 안쪽 도구 호출로 **바꿔 쓴다**.
   그러면 그 뒤의 인앱 승인 카드·일정 모호성 확인·물리 제어 하드 게이트가 지금과
   똑같이 안쪽 도구 이름으로 돈다. 나머지(읽기, 승인 없는 기록·화면)는 도구
   실행층(`tool_execution.execute_for_agent`)으로 — 외부 MCP 와 같은 응답이다.
"""
import logging

logger = logging.getLogger(__name__)


def is_domain_tool(name):
    from aot.tools.domain.registry import DOMAIN_TOOLS
    return bool(name) and name in DOMAIN_TOOLS


# ── 1. 목록 ──────────────────────────────────────────────────────────────────

def _usage_hint(schema):
    """인자 스키마를 한 줄로 — 엔진 어댑터는 인자를 `arguments` 객체 하나로 받고 그
    설명 자리에 이 줄을 싣는다(gemini.py·anthropic.py `_build_tools_schema`)."""
    props = (schema or {}).get('properties') or {}
    required = set((schema or {}).get('required') or ())
    parts = []
    for name, spec in props.items():
        spec = spec or {}
        if spec.get('enum'):
            what = '|'.join(str(v) for v in spec['enum'])
        else:
            what = spec.get('description') or spec.get('type') or ''
        parts.append('%s%s: %s' % (name, '*' if name in required else '', what))
    return 'params.arguments: {%s} (* = required)' % '; '.join(parts)


def domain_tool_entries(app=None):
    """인앱 매니페스트의 도구 항목 — 도메인 명부 그대로(설명을 자르지 않는다:
    operation 목록이 설명 안에 있다)."""
    try:
        if app is None:
            from flask import current_app
            app = current_app._get_current_object()
        from aot.tools import tool_execution
        tools = tool_execution.tools_for_agent(app)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("[in_app_tools] 도메인 명부를 못 만들었다: %s", exc)
        return []
    # action_type 은 싣지 않는다 — 모델이 이름만 내야 정규화(`normalize`)가 승인 경로를 고른다.
    return [{
        "tool_name": t["name"],
        "description": t.get("description", ""),
        "usage_hint": _usage_hint(t.get("inputSchema")),
    } for t in tools]


# ── 2·3. 승인 판정과 실행 길 ─────────────────────────────────────────────────

def _inner_requires_approval(inner):
    from aot.ai.services.ai_action_service import AIActionService
    return AIActionService.requires_approval(inner)


def plan(tool, arguments):
    """도메인 호출 하나가 인앱에서 어느 길로 가는가.

    ('direct',)              — 도구 실행층으로(읽기, 승인 없는 쓰기, 틀이 거절할 호출)
    ('inner', 이름, 인자)     — 승인이 필요한 쓰기: 안쪽 도구 호출로 바꿔 인앱 승인으로
    ('many', 이름)           — 승인이 필요한 쓰기인데 대상이 여럿: 하나씩 다시 부르게
    ('error', 문장)          — 판정 실패(쓰기는 안전한 쪽 — 실행하지 않는다)
    """
    from aot.tools.domain.registry import WRITE_TOOLS
    if tool not in WRITE_TOOLS:
        return ('direct',)
    arguments = arguments if isinstance(arguments, dict) else {}
    if len(arguments) == 1 and isinstance(arguments.get('arguments'), dict):
        arguments = arguments['arguments']        # 엔진 어댑터가 한 겹 더 싼 모양
    try:
        from aot.tools import screen_follow
        from aot.tools.domain import dispatch, renames
        canon, args, _renamed = renames.resolve_call(
            tool, dict(arguments or {}), dispatch._ops())
        args, _show = screen_follow.pop_show_arg(args)
        verdict = dispatch.plan(canon, args)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("[in_app_tools] %s 호출 판정 실패: %s", tool, exc)
        return ('error', "Could not resolve this %s call: %s" % (tool, exc))
    kind = verdict[0]
    if kind == 'call':
        inner, inner_args = verdict[1], verdict[2]
        if not _inner_requires_approval(inner):
            return ('direct',)
        from aot.tools.domain.dispatch import META_KEY, SNAPSHOT_KEY
        clean = {k: v for k, v in (inner_args or {}).items()
                 if k not in (META_KEY, SNAPSHOT_KEY)}
        return ('inner', inner, clean)
    if kind == 'fanwrite':
        return ('many', verdict[1]) if _inner_requires_approval(verdict[1]) \
            else ('direct',)
    return ('direct',)          # 'refuse' — 실행층이 같은 거절 본문을 낸다


def requires_approval(tool, arguments):
    """도메인 호출이 사람 승인을 거쳐야 하는가(안쪽 도구 기준)."""
    return plan(tool, arguments)[0] != 'direct'


def action_arguments(action):
    from aot.tools.tool_call_args import extract_tool_call
    _name, args = extract_tool_call(action.get('params'), action.get('target_id'))
    return args if isinstance(args, dict) else {}


def normalize(action, tool):
    """도메인 호출 action 을 인앱 실행 모양으로 고친다.

    반환: None — 안쪽 도구 호출로 바꿔 썼으니 이어서 보통 정규화를 하라.
          (True, "OK") — 도구 실행층으로 갈 virtual_tool_call 로 마쳤다.
          (False, 문장) — 실행하지 않는다(모델에게 돌려줄 이유).
    """
    args = action_arguments(action)
    verdict = plan(tool, args)
    if verdict[0] == 'inner':
        action.pop('action_type', None)
        action.pop('target_id', None)
        action['params'] = {'tool_name': verdict[1], 'arguments': verdict[2]}
        logger.info("[in_app_tools] %s → %s (승인 경로)", tool, verdict[1])
        return None
    if verdict[0] == 'many':
        return False, ("%s needs approval for each target separately here — call it "
                       "once per target." % tool)
    if verdict[0] == 'error':
        return False, verdict[1]
    action['action_type'] = 'virtual_tool_call'
    action['target_id'] = 'system_internal'
    action['params'] = {'tool_name': tool, 'arguments': args,
                        'server_id': 'system_internal'}
    return True, "OK"


def run(tool, arguments, agent_unique_id=None):
    """도메인 도구를 도구 실행층으로 실행한다 — 외부 MCP 와 같은 길·같은 응답.

    승인이 필요한 쓰기가 정규화를 거치지 않고 여기 오면(호출자가 action_type 을 미리
    붙인 경우) 실행하지 않는다 — 인앱 승인은 안쪽 도구 호출로 바뀐 action 에만 있다."""
    verdict = plan(tool, arguments)
    if verdict[0] != 'direct':
        return {"status": "error", "reason_code": "needs_approval",
                "message": verdict[1] if verdict[0] == 'error' else
                ("%s needs the user's approval — propose it as an action instead of "
                 "running it." % tool)}
    from flask import current_app
    from aot.ai import ai_request_context
    from aot.tools import tool_execution
    rq = ai_request_context.get_requester()
    res = tool_execution.execute_for_agent(
        current_app._get_current_object(), tool, arguments or {},
        agent_unique_id=agent_unique_id,
        scope_user_uuid=rq.user_uuid if rq is not None else None,
        session_key=ai_request_context.get_thread_id())
    # help 는 안내 카드라 실행 판정(call_state)이 없다 — execute_for_agent 가 그것을
    # 미실행(error)으로 싸면 모델은 받은 안내를 실패로 읽는다. 본문이 성공이면 성공이다.
    inner = res.get('result') if isinstance(res, dict) else None
    if (tool == 'help' and res.get('status') == 'error' and isinstance(inner, dict)
            and inner.get('status') == 'success'):
        return {"status": "success", "result": inner}
    return res


__all__ = ['action_arguments', 'domain_tool_entries', 'is_domain_tool', 'normalize', 'plan',
           'requires_approval', 'run']
