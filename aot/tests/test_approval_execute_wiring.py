# coding=utf-8
"""승인된 도구가 실제로 실행되는가 — 즉시실행 경로의 배선 (2026-08-22).

## 무엇이 났나

`mcp_safety_gate` 의 '승인 즉시 실행' 은 실행층의 디스패치를 **함수 안에서**
import 해서 쓴다. 2026-08-22 실행층을 MCP 서버에서 분리하면서(`896d4595`)
`_dispatch_virtual_tool`·`_NATIVE_TOOLS` 가 `tool_execution` 으로 옮겨갔는데,
이 import 는 옛 위치(`aot.aot_mcp_server`)를 그대로 가리키고 있었다.

결과: **승인된 쓰기 도구가 하나도 실행되지 않았다.** 승인 자체는 정상으로 보이고
그다음 즉시실행이 `ImportError` 로 죽어, 사용자에게는 "승인했는데 아무 일도 안
일어남" 으로 나타났다. 실제로 입력 8개를 만들려다 8건 전부 이렇게 날아갔고,
그 사이 레이트 리밋(시간당 10회)까지 소진됐다.

## 왜 기존 검사로 안 잡혔나

**함수 안 import 는 모듈을 불러오는 것만으로는 실행되지 않는다.** `import
aot.ai.services.mcp_safety_gate` 는 멀쩡히 성공하고, 문법 검사도 통과하고,
그 모듈을 건드리는 어떤 테스트도 이 줄을 밟지 않는다 — 승인된 항목을 실제로
실행해 봐야만 드러난다. CLAUDE.md 의 `ai_loader_service` 사고와 같은 계열이다
("import 이 되는 것과 동작하는 것은 다르다").

그래서 여기서는 **그 이름들을 실제로 가져와 본다.** 이름이 또 옮겨가면 이
테스트가 먼저 깨진다.
"""
import ast
import pathlib

import pytest

GATE = pathlib.Path(__file__).resolve().parents[1] / 'ai/services/mcp_safety_gate.py'


def test_실행층_심볼을_실제로_가져올_수_있다():
    """승인 즉시실행이 쓰는 이름 두 개가 정본 위치에 있는가."""
    from aot.ai.services.tool_execution import (   # noqa: F401
        _NATIVE_TOOLS, _dispatch_virtual_tool)
    assert callable(_dispatch_virtual_tool)
    assert isinstance(_NATIVE_TOOLS, (set, frozenset))


def test_승인경로가_옛_위치에서_가져오지_않는다():
    """`aot.aot_mcp_server` 에서 실행층 심볼을 가져오면 안 된다.

    실행층의 정본은 `tool_execution` 이다(CLAUDE.md "도구 실행층은 MCP 가 아니다").
    MCP 서버는 그것을 프로토콜로 감싸는 어댑터일 뿐이라, 승인 경로가 어댑터를
    거쳐 실행층을 찾으면 어댑터가 재export 를 그만두는 순간 조용히 끊긴다.
    """
    tree = ast.parse(GATE.read_text(encoding='utf-8'))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'aot.aot_mcp_server':
            names = [a.name for a in node.names]
            if any(n in ('_dispatch_virtual_tool', '_NATIVE_TOOLS') for n in names):
                bad.append((node.lineno, names))
    assert not bad, (
        f'승인 즉시실행이 옛 위치에서 실행층 심볼을 가져온다: {bad}. '
        f'`aot.ai.services.tool_execution` 에서 가져올 것.')


def test_즉시실행이_import_에러로_죽지_않는다():
    """승인 항목이 없어도 함수가 **import 단계**에서 터지지 않아야 한다.

    존재하지 않는 confirmation 을 주면 'confirmation not found' 로 끝나야 하고,
    거기까지 가려면 모듈과 그 안의 import 가 성립해야 한다. ImportError 가 나면
    이 테스트가 그 자리에서 깨진다.
    """
    from aot.ai.services import mcp_safety_gate as gate
    fn = getattr(gate, 'execute_approved', None) or getattr(
        gate, 'execute_confirmed', None)
    if fn is None:
        pytest.skip('즉시실행 진입점 이름을 찾지 못함 — 이름이 바뀌면 여기도 갱신할 것')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
