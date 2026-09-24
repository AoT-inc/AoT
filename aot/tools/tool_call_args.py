# coding=utf-8
"""인앱 도구 호출 `params` → (도구 이름, 처리기 인자) — **한 벌**.

인앱 AI 의 `virtual_tool_call`·`mcp_tool_call` 은 인자를
`{'tool_name', 'arguments' | 'params' | 펼친 키…}` 로 보낸다. 실제 실행
(`VirtualToolResolver`·`MCPToolCallResolver`)과 권한 판정
(`AIActionService._requester_denial`·`AIAgentService._approval_denial`)이 이
모양을 **각자** 풀었더니 어긋났다: 실행은 `arguments or params` 로 빈
`arguments` 를 건너뛰고 `params` 를 썼는데, 판정은 빈 `arguments` 를 그대로
받아 아무것도 보지 않았다(2026-09-23 재현 — `{'arguments': {}, 'params':
{...}}` 로 스코프 밖 장치에 일정이 생겼다).

그래서 실행과 판정이 같은 함수를 부른다. 판정이 보는 인자가 곧 처리기가
받는 인자다.
"""

#: 도구 인자가 아닌 틀 키 — 펼친 인자(`params` 에 인자를 바로 담은 경우)에서 뺀다.
META_KEYS = frozenset({'tool_name', 'server_id', 'agent_unique_id', 'context',
                       'page_context'})


def _handler_takes_arguments(tool_name):
    """처리기가 `arguments` 라는 인자를 직접 받는가(use_tool 등) — 그러면 두 겹을
    벗기지 않는다."""
    try:
        import inspect
        from aot.tools.tool_registry import build_tool_map
        handler = build_tool_map().get(tool_name)
        if handler is None:
            return False
        return 'arguments' in inspect.signature(handler).parameters
    except Exception:
        return False


def extract_tool_call(params, target_id=None, flatten=True, unwrap=True,
                      handler=None):
    """(도구 이름, 인자 dict).

    - 도구 이름: `params['tool_name']`, 없으면 `target_id`(모델이 이름을 거기
      넣는 일이 있다).
    - 인자: `arguments` → 비었으면 `params` → 그것도 비었고 `flatten` 이면
      틀 키를 뺀 나머지 전부.
    - `unwrap`: 인자가 `{'arguments': {...}}` 한 겹으로 더 싸였으면 벗긴다 —
      처리기가 `arguments` 를 직접 받으면 벗기지 않는다.

    `flatten`/`unwrap` 은 `virtual_tool_call` 실행 경로의 규칙이다.
    `mcp_tool_call` 은 둘 다 끈다(그 리졸버가 예전부터 그랬다).
    """
    p = params if isinstance(params, dict) else {}
    tool = p.get('tool_name') or (target_id if isinstance(target_id, str) else None)
    arguments = p.get('arguments') or p.get('params') or {}
    if not isinstance(arguments, dict):
        arguments = {}
    if not arguments and flatten:
        flat = {k: v for k, v in p.items() if k not in META_KEYS}
        if flat:
            arguments = flat
    if (unwrap and len(arguments) == 1
            and isinstance(arguments.get('arguments'), dict)):
        if handler is not None:
            try:
                import inspect
                takes = 'arguments' in inspect.signature(handler).parameters
            except (TypeError, ValueError):
                takes = False
        else:
            takes = _handler_takes_arguments(tool)
        if not takes:
            arguments = arguments['arguments']
    return tool, dict(arguments)


#: 서랍 위임 도구. 외부 MCP 표면(`tool_execution._execute_tool`)이 안쪽 도구를
#: 대신 실행한다 — 판정은 **안쪽 도구**로 해야 한다.
USE_TOOL = 'use_tool'

#: use_tool 을 벗기는 최대 겹수. 실행층은 use_tool 안의 use_tool 을 거절하지만,
#: 판정 쪽은 그 사실에 기대지 않고 몇 겹이든 벗겨 본다. 한도를 넘으면
#: 이름이 `use_tool` 로 남고, 호출자는 그것을 쓰기로 본다(닫힌 쪽).
USE_TOOL_MAX_DEPTH = 4


def unwrap_use_tool(tool, arguments):
    """`use_tool{tool_name, arguments}` → (안쪽 도구 이름, 안쪽 인자).

    인앱 AI 의 `mcp_tool_call` 이 내장 서버의 `use_tool` 을 부르면 실제로
    도는 것은 안쪽 도구다. 역할·그룹 스코프·쓰기 분류를 겉 이름(`use_tool`)
    으로 하면 전부 "읽기" 로 보여 빠진다(2026-09-23 재현 — Monitor 가
    `use_tool{create_note}` 로 노트를, 익명 요청자가 `use_tool{add_schedule}`
    로 일정을 만들었다).

    실행층과 같은 규칙으로 벗긴다: 겉의 `_` 로 시작하는 메타 키는 안쪽에
    없을 때 넘겨준다(`_confirmation_id` 등). 모양이 틀리면(이름 없음·인자가
    dict 아님) 그대로 돌려준다 — 실행층도 그 호출을 오류로 끝낸다.
    """
    args = arguments if isinstance(arguments, dict) else {}
    for _ in range(USE_TOOL_MAX_DEPTH):
        if tool != USE_TOOL:
            break
        inner = args.get('tool_name')
        inner_args = args.get('arguments')
        if inner_args is None:
            inner_args = {}
        if not isinstance(inner, str) or not inner.strip() \
                or not isinstance(inner_args, dict):
            break
        merged = dict(inner_args)
        for k, v in args.items():
            if isinstance(k, str) and k.startswith('_') and k not in merged:
                merged[k] = v
        tool, args = inner.strip(), merged
    return tool, dict(args)
