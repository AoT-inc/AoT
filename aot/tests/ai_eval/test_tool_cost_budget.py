# coding=utf-8
"""도구 표면의 고정비 예산 — 늘어나면 실패한다 (설계 §불변식 T5).

매니페스트는 **질문 내용과 무관하게 매 호출에 실린다.** "1구역 온도 몇 도야?"
에도 전부 읽는다. 그런데 도구를 하나 추가하는 일은 지금까지 아무 비용도
보이지 않았고, 그래서 87개까지 늘었다.

이 테스트는 그 비용을 **보이게** 만든다. 상한을 넘기려면 아래 상수를 사람이
고쳐야 하고, 고치는 순간 "무엇을 얻으려고 얼마를 더 쓰는가" 가 커밋에 남는다.

**지금 상한은 목표치가 아니라 기준선이다.** 설계 문서(§불변식 T5)는 목표치를
현재값보다 낮게 잡으라고 하지만, 그 숫자는 Phase 2 의 측정 뒤에 정한다.
Phase 0 에서 이 테스트가 하는 일은 하나 — **더 나빠지는 것을 막는 것**이다.

    python3 -m pytest aot/tests/ai_eval/test_tool_cost_budget.py

의존성 없이 돈다(선언만 읽는다). DB·LLM·API 키가 필요 없으므로 설치가 깨져도
판정이 가려지지 않는다 — ai-tool-registry.yml 의 `gating` 잡과 같은 이유다.
"""
import unittest

from aot.scripts.measure_ai_tool_cost import measure_manifest

# 2026-08-15 기준선. 낮추는 것은 언제든 환영이고, 올리려면 근거를 커밋에 남길 것.
#   에이전트 루프 매니페스트: 도구 87개 · 47,921자 · 약 11,980토큰
#   MCP 카탈로그:             도구 97개 · 74,293자 · 약 18,573토큰
AGENT_MANIFEST_TOKEN_CEILING = 12_000
MCP_CATALOG_TOKEN_CEILING = 18_700

# 도구 하나가 이보다 크면 설명이 아니라 문서다. 가장 큰 것이 get_planting
# 3,164자인데, 그 정도가 이미 상한선이라고 본다.
SINGLE_TOOL_CHAR_CEILING = 3_400


class TestToolSurfaceBudget(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manifest = measure_manifest()

    def test_agent_manifest_within_budget(self):
        block = self.manifest['agent_manifest']
        self.assertLessEqual(
            block['tokens'], AGENT_MANIFEST_TOKEN_CEILING,
            '에이전트 매니페스트가 예산을 넘었다 (%d토큰 > %d, 도구 %d개). '
            '도구를 늘렸다면 무엇을 서랍으로 내릴지 함께 정할 것 — '
            'docs/design/ai-tool-architecture.md §노출 등급과 서랍'
            % (block['tokens'], AGENT_MANIFEST_TOKEN_CEILING, block['count']))

    def test_mcp_catalog_within_budget(self):
        block = self.manifest['mcp_catalog']
        self.assertLessEqual(
            block['tokens'], MCP_CATALOG_TOKEN_CEILING,
            'MCP 카탈로그가 예산을 넘었다 (%d토큰 > %d, 도구 %d개)'
            % (block['tokens'], MCP_CATALOG_TOKEN_CEILING, block['count']))

    def test_no_single_tool_is_a_document(self):
        """한 도구가 지나치게 크면 그 자체로 다른 모든 질문에 세금이 된다."""
        oversized = [(t['tool'], t['chars'])
                     for t in self.manifest['mcp_catalog']['tools']
                     if t['chars'] > SINGLE_TOOL_CHAR_CEILING]
        self.assertEqual(
            oversized, [],
            '도구 설명이 너무 크다(%d자 초과): %s. 사용법 상세는 '
            'get_tool_detail 로 내릴 수 있다' % (SINGLE_TOOL_CHAR_CEILING, oversized))

    def test_every_tool_has_a_tier_assignment(self):
        """도구를 추가하고 배정표를 빠뜨리면 조용히 서랍 기본값으로 떨어진다.

        보수적 기본값이라 사고는 아니지만, **아무도 그 도구를 배치하기로
        판단한 적이 없다**는 사실이 묻힌다. 양방향으로 잡는다.
        """
        from aot.ai.services import tool_registry as registry

        declared = {t.name for t in registry.TOOLS}
        assigned = set(registry._TIER_ASSIGNMENT)
        self.assertEqual(sorted(declared - assigned), [],
                         '배정표에 없는 도구가 있다 — 어느 서랍인지 정할 것')
        self.assertEqual(sorted(assigned - declared), [],
                         '배정표에 유령 항목이 있다(도구가 사라졌다)')

    def test_drawer_names_are_declared(self):
        """서랍 이름 오타는 그 도구를 아무도 못 여는 서랍에 넣는다."""
        from aot.ai.services import tool_registry as registry

        unknown = sorted({d for d, _, _ in registry._TIER_ASSIGNMENT.values()}
                         - set(registry.DRAWERS))
        self.assertEqual(unknown, [], '선언되지 않은 서랍: %s' % unknown)

    def test_core_set_stays_small(self):
        """상시 노출이 늘면 고정비를 줄이려던 이유가 사라진다."""
        from aot.ai.services import tool_registry as registry

        core = registry.core_tools()
        self.assertLessEqual(
            len(core), 25,
            'core 가 %d개다. 늘리려면 무엇을 서랍으로 내릴지 함께 정할 것: %s'
            % (len(core), sorted(core)))

    def test_the_drawer_opener_is_never_in_a_drawer(self):
        """서랍을 여는 수단이 서랍에 있으면 나머지가 영영 안 열린다."""
        from aot.ai.services import tool_registry as registry

        for essential in ('get_tool_detail', 'resolve_target', 'ask_user'):
            self.assertIn(essential, registry.core_tools(),
                          '%s 은 상시 노출이어야 한다' % essential)

    def test_tiering_is_off_by_default(self):
        """배포만으로 동작이 바뀌면 안 된다. 켜는 것이 명시적 결정이어야 한다."""
        import os

        from aot.ai.services import tool_registry as registry

        self.assertNotIn('AOT_AI_TOOL_TIERING', os.environ,
                         '테스트 환경에 스위치가 켜져 있으면 아래 판정이 무의미하다')
        self.assertFalse(registry.tiering_enabled())

    def test_every_tool_stays_reachable_when_tiering_is_on(self):
        """등급을 켜도 **도달 불가능한 도구가 생기면 안 된다.**

        상시 노출에서 빠진 것은 전부 어느 서랍엔가 있어야 한다. 하나라도
        어느 쪽에도 없으면 그 도구는 조용히 사라진 것이고, 그것이 이 기능이
        절대 해서는 안 되는 일이다.
        """
        from aot.ai.services import tool_registry as registry

        core = registry.core_tools()
        in_drawers = set()
        for drawer in registry.DRAWERS:
            in_drawers.update(registry.tools_in_drawer(drawer))

        manifested = {t.name for t in registry.TOOLS if t.manifest}
        lost = sorted(manifested - core - in_drawers)
        self.assertEqual(lost, [], '등급을 켜면 닿을 수 없어지는 도구: %s' % lost)

    def test_unknown_drawer_returns_the_list_not_an_error(self):
        """이름을 틀렸을 때 '없다' 로 끝나면 LLM 이 포기한다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        result = AoTDataToolService.open_drawer('없는이름')
        self.assertTrue(result.get('drawers'),
                        '모르는 서랍 이름에 목록을 함께 줘야 다시 고를 수 있다')

    def test_measurement_is_reproducible(self):
        """계측 자체가 흔들리면 예산도 의미가 없다."""
        again = measure_manifest()
        self.assertEqual(again['agent_manifest']['chars'],
                         self.manifest['agent_manifest']['chars'])


if __name__ == '__main__':
    unittest.main()
