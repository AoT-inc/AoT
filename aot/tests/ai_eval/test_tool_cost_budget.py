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

# 2026-08-15 기준선(70ba1ff6). 낮추는 것은 언제든 환영이고, 올리려면 근거를
# 커밋에 남길 것.
#   에이전트 루프 매니페스트: 도구 87개 · 47,921자 · 약 11,980토큰 → 상한 12,000
#   MCP 카탈로그:             도구 97개 · 74,293자 · 약 18,573토큰 → 상한 18,700
#
# ── 2026-08-20 재기준선 ────────────────────────────────────────────────────
#
# 상한을 넘긴 채로 다섯 커밋을 지났다. 어디서 늘었는지 재 보면 전부 **도구를
# 더한 기능 작업**이고, 문구가 부풀어서가 아니다:
#
#   커밋        에이전트   MCP      무엇이
#   70ba1ff6    11,980    18,573   기준선(도구 87)
#   aedacb77    12,016    19,076   구획 분할 인자 확장(angle_deg·widths_cm…)
#   dc705d09    12,070    19,642   koat MCP 수정 + 도구 1
#   692839fa    12,551    19,592   관리 프로그램 레이어(도구 +4)
#   799f11b6    12,914    19,765   구획 단계·자원 도구 +3
#   fa90d527    12,914    19,598   propose_plot_split 설명 정리(-677자)
#   dbca0eed    12,999    19,763   단계 지침(`stage.guidance`) 사용 규칙
#   이 커밋      13,191    19,7xx   두 갈래 병합 — delete_program(도구 +1) +
#                                   P6 자원 역할. 도구 94→95.
#
# 이번 증가는 **세션 두 갈래가 서로를 모른 채 각자 도구·설명을 더한 결과**다.
# `delete_program`(CRUD 완성)과 단계 지침 규칙이 따로 만들어졌고, 합쳐질 때에야
# 한 저울에 올라왔다. 문구가 부푼 것이 아니라 도구가 하나 더 늘었다.
#
# 87개용으로 잡은 예산을 94개에 그대로 씌우면 **실제 규칙을 지워야** 맞출 수
# 있다. 이 설명들은 한 줄씩이 과거의 실패에서 나온 것이라(센서 출처를 안 밝혀
# 구역 대표값을 구획 값으로 보고한 일 등) 자릿수를 맞추자고 지울 것이 아니다.
# 그래서 도구 수가 늘어난 만큼 상한을 올리되, 여유는 예전과 같이 좁게 둔다.
#
# ⚠ **서랍 배정으로는 이 숫자가 내려가지 않는다.** 여기서 재는 것은 등급을 끈
# (기본값) 매니페스트라 도구가 전부 실린다 — 배정은 등급을 켰을 때 값을 한다.
# 그 값이 얼마인지는 아래 `TIERED_MANIFEST_TOKEN_CEILING` 이 보인다.
#
# ── 2026-08-21 재기준선 ────────────────────────────────────────────────────
#
#   무엇                          에이전트    MCP     도구
#   직전(dbca0eed 계열)            13,560   19,763   99 / 98
#   대시보드 위젯 도구 6종            14,023   21,363  105 / 108
#
# 늘어난 것은 둘이다.
#  (1) 위젯 도구 6종(list_dashboards·list_widget_types·get_widget·create/
#      modify/delete_widget) — 화면 구성은 지금까지 AI 가 손댈 수 없던 축이다.
#  (2) 탭 도구 4종의 **MCP 배선**. 도구 자체는 전부터 있었지만 카탈로그
#      (`_MCP_TOOL_PAYLOADS`)에 없어 어떤 MCP 클라이언트에도 안 보였다 —
#      선언만으로는 안 나간다는 그 함정에 걸려 있던 것을 이제 실었다. 그래서
#      MCP 쪽 증가(+1,600)가 에이전트 쪽(+463)보다 크다.
#
# **에이전트 상한은 직전에 이미 초과 상태였다**(13,560 > 13,260). 이번 작업이
# 낸 초과가 아니라 앞선 커밋들이 넘긴 채 지나간 것이고, 여기서 그 몫까지 함께
# 재기준선으로 삼는다.
#
# ⚠ **MCP 카탈로그 상한의 의미가 이 커밋부터 달라졌다.** 서랍(`AOT_MCP_TOOL_
# TIERING`, 기본 켜짐)이 붙으면서 `tools/list` 에 실제로 나가는 것은 core +
# 서랍 기계장치 9개뿐이다 — 실측 2,783토큰으로, 여기 적힌 21,363 은 **서랍을
# 껐을 때의 값**이다. 카탈로그가 커지는 것이 예전만큼 곧바로 비용은 아니지만,
# 서랍을 끈 서버가 있는 한 이 상한은 계속 의미가 있으므로 남긴다. 실제로 나가는
# 값은 `aot/tests/test_mcp_tool_surface.py::test_listed_surface_stays_small`
# 이 잰다 — 그쪽이 이제 진짜 고정비다.
AGENT_MANIFEST_TOKEN_CEILING = 14_100
MCP_CATALOG_TOKEN_CEILING = 21_500

# 등급(`AOT_AI_TOOL_TIERING=1`)을 켰을 때의 매니페스트. 2026-08-21 실측
# 19항목 · 14,064자 · 약 3,516토큰 — 끈 상태의 **25%** 다.
#
# 2026-08-20 에는 15항목 2,787토큰이었다. 늘어난 이유는 둘 다 실측에서 나왔다:
# (1) core 를 5→31개로 넓혔다 — 좁은 core 로는 외부 클라이언트가 요청을 끝내지
#     못했다(aot/tests/test_mcp_tool_surface.py::test_core_stays_bounded 의 표).
# (2) 서랍 인덱스가 그 안의 **도구 이름까지** 싣는다 — 이름이 없으면 LLM 이
#     열지 말지를 추측해야 하고, 그러면 열지 않는다.
#
# 이것을 따로 재는 이유: 위 두 상한은 도구를 더하면 반드시 오르므로 "무엇을
# 서랍으로 내릴지" 를 판단하게 만들지 못한다. 이 상한이 그 일을 한다 — core 에
# 도구를 하나 더 얹거나 `_TIER_ASSIGNMENT` 에서 배정을 빠뜨리면(빠뜨린 도구는
# 서랍 기본값으로 떨어지므로 이 숫자는 안 움직이지만, 바로 아래
# `test_every_tool_has_a_tier_assignment` 가 잡는다) 여기서 보인다.
TIERED_MANIFEST_TOKEN_CEILING = 3_600

# 도구 하나가 이보다 크면 설명이 아니라 문서다. 2026-08-15 에는 가장 큰 것이
# get_plot 3,164자였고 그 정도를 상한선으로 봤다.
#
# 2026-08-20: `propose_plot_split` 이 3,636자로 이 선을 넘었다 — 설명이
# `input_schema` 의 파라미터 문서를 통째로 되풀이하고 있었다(분할 모드 셋의 뜻,
# 방향 기본값, angle_deg 규칙). 스키마 쪽만 남기고 677자를 덜어 2,959자가 됐다.
# **상한은 올리지 않았다** — 여기 걸리는 것은 대개 이런 중복이지 부족한 설명이
# 아니고, 실제로 그랬다.
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
            '이 숫자는 등급을 끈 상태를 재므로 **서랍 배정으로는 내려가지 '
            '않는다** — 문구를 줄이거나 도구를 없애거나, 늘어난 근거를 적고 '
            '상한을 올릴 것(위 재기준선 표와 같은 형식으로). 서랍 배정의 값은 '
            'test_tiered_manifest_stays_small 이 잰다 — '
            'docs/design/ai-tool-architecture.md §노출 등급과 서랍'
            % (block['tokens'], AGENT_MANIFEST_TOKEN_CEILING, block['count']))

    def test_mcp_catalog_within_budget(self):
        block = self.manifest['mcp_catalog']
        self.assertLessEqual(
            block['tokens'], MCP_CATALOG_TOKEN_CEILING,
            'MCP 카탈로그가 예산을 넘었다 (%d토큰 > %d, 도구 %d개)'
            % (block['tokens'], MCP_CATALOG_TOKEN_CEILING, block['count']))

    def test_tiered_manifest_stays_small(self):
        """등급을 켰을 때의 고정비 — **서랍 배정이 실제로 값을 하는가.**

        위 두 상한은 도구를 더하면 반드시 오르므로 "무엇을 core 에 둘까" 를
        판단하게 만들지 못한다. 이 검사가 그 일을 한다: core 에 도구를 하나 더
        얹으면 여기서 보인다.
        """
        import json
        import os

        from aot.ai.services import tool_registry as registry

        old = os.environ.get('AOT_AI_TOOL_TIERING')
        os.environ['AOT_AI_TOOL_TIERING'] = '1'
        try:
            # `tiering_enabled()` 는 매번 환경변수를 읽으므로 reload 가 필요 없다.
            entries = registry.manifest_system_tools()
        finally:
            if old is None:
                os.environ.pop('AOT_AI_TOOL_TIERING', None)
            else:
                os.environ['AOT_AI_TOOL_TIERING'] = old

        chars = len(json.dumps(entries, ensure_ascii=False, default=str))
        tokens = chars // 4
        self.assertLessEqual(
            tokens, TIERED_MANIFEST_TOKEN_CEILING,
            '등급을 켠 매니페스트가 예산을 넘었다 (%d토큰 > %d, 도구 %d개). '
            'core 로 승격한 도구가 있다면 무엇을 대신 내릴지 함께 정할 것 — '
            'docs/design/ai-tool-architecture.md §노출 등급과 서랍'
            % (tokens, TIERED_MANIFEST_TOKEN_CEILING, len(entries)))

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
            len(core), 35,
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
