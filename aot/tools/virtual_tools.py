# coding=utf-8
"""가상 도구(VIRTUAL_TOOLS) 정의 — 도구 계층 소유.

MCP 프로토콜(`{tool_name, description, input_schema}`)로 advertise 되는 도구
카탈로그는 `aot.tools.tool_registry.virtual_tools()` 가 만든다(SSOT는
`tool_registry._MCP_TOOL_PAYLOADS`). 이 모듈은 그 결과를 `VIRTUAL_TOOLS` 라는
이름으로 다시 내보내기만 한다 — `aot/ai/agents/mcp_aot.py` 가 예전에 이
이름으로 직접 계산해 두던 것을 그대로 쓸 수 있게 하기 위한 하위호환 지점이다
(그쪽 방향, 즉 aot.ai 가 aot.tools 를 import 하는 것은 허용된다).

**모듈 로드 시점에 한 번 계산해 캐시한다** — 예전 `mcp_aot.VIRTUAL_TOOLS` 와
같은 타이밍/동작이다. 도구 정의가 요청마다 바뀔 일이 없으므로 재계산 비용을
피한다. 최신 값이 필요하면 `refresh()` 를 부른다.
"""
from aot.tools.tool_registry import virtual_tools as _virtual_tools

VIRTUAL_TOOLS = _virtual_tools()


def refresh():
    """VIRTUAL_TOOLS 를 tool_registry 에서 다시 계산해 갱신한다.

    보통 필요 없다(도구 정의는 프로세스 수명 동안 고정) — 테스트가 티어링
    설정을 바꾼 뒤 다시 읽고 싶을 때만 쓴다."""
    global VIRTUAL_TOOLS
    VIRTUAL_TOOLS = _virtual_tools()
    return VIRTUAL_TOOLS
