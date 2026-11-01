# -*- coding: utf-8 -*-
"""MCP 표면 동결 — 도구·인자 이름이 늘지 않게 (2026-10-13).

기능마다 도구 하나·인자 이름 하나씩 덧붙여 도구 136개·인자 이름 219개가 됐다
(대상을 가리키는 이름만 23가지). 외부 AI 는 이름을 추측하다 틀리고(10-12~13
실패 97건 중 49건), 목록은 줄여도 다시 커졌다. 그래서 표면을 도메인 도구 +
operation 명부로 다시 짠다 — 설계 docs/design/mcp-domain-surface.md.

옮기는 동안 이 검사가 지킨다:
- 카탈로그의 도구 이름과 인자 이름은 `mcp_surface_freeze.json` 밖으로 늘 수 없다.
  새 기능은 새 도구가 아니라 새 틀의 operation 이다(설계 §1).
- 새 틀의 도메인 도구 이름(`DOMAIN_TOOLS`)만 예외다.
- 줄었으면 동결 목록에서도 지운다(목록이 실제와 같아야 다음 사람이 믿는다).

늘려야 한다면 그것은 이 틀을 바꾸는 결정이다 — 목록을 고치기 전에 사용자에게 묻는다.
"""
import json
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))

#: 설계 §4 의 도메인 도구 — 새 틀이 들어오며 생기는 이름.
DOMAIN_TOOLS = frozenset({
    'overview', 'measure', 'weather', 'find', 'detail', 'records',
    'screen_view', 'help', 'control', 'record', 'cultivate', 'configure',
    'screen',
    # 지우기만 모은 도구 — '항상 허용' 이 나머지 쓰기 도구에 먹게(2026-10-14 사용자 결정).
    'remove',
})

_HOW = ("새 기능은 새 도구·새 인자 이름이 아니라 새 틀의 operation 이다 — "
        "docs/design/mcp-domain-surface.md §1. 꼭 늘려야 한다면 사용자 결정을 "
        "받은 뒤 aot/tests/mcp_surface_freeze.json 을 고친다.")


def _catalog():
    from aot.tests.test_mcp_tool_profiles import _catalog_definitions
    return _catalog_definitions()


def _frozen():
    with open(os.path.join(_HERE, 'mcp_surface_freeze.json'), encoding='utf-8') as f:
        return json.load(f)


class MCPSurfaceFreezeTest(unittest.TestCase):

    def test_no_new_tools(self):
        new = sorted(set(_catalog()) - set(_frozen()['tools']) - DOMAIN_TOOLS)
        self.assertEqual([], new, '새 MCP 도구: %s. %s' % (new, _HOW))

    def test_no_new_argument_names(self):
        defs = _catalog()
        args = {p: n for n, t in defs.items() if n not in DOMAIN_TOOLS
                for p in ((t.get('inputSchema') or {}).get('properties') or {})}
        new = sorted(set(args) - set(_frozen()['args']))
        self.assertEqual([], ['%s (%s)' % (a, args[a]) for a in new],
                         '새 인자 이름. %s' % _HOW)

    def test_freeze_list_matches_what_exists(self):
        """줄어든 것은 동결 목록에서도 지운다 — 래칫."""
        defs = _catalog()
        gone_tools = sorted(set(_frozen()['tools']) - set(defs))
        args = {p for t in defs.values()
                for p in ((t.get('inputSchema') or {}).get('properties') or {})}
        gone_args = sorted(set(_frozen()['args']) - args)
        self.assertEqual(([], []), (gone_tools, gone_args),
                         '없어진 이름을 mcp_surface_freeze.json 에서 지울 것')


if __name__ == '__main__':
    unittest.main()
