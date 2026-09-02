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

from aot.scripts.measure_ai_tool_cost import _tok, measure_manifest

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
# ── 2026-08-21 재기준선 (2) — 프로그램 채우기 P1 ──────────────────────────
#
#   무엇                          에이전트    MCP     도구
#   직전                           14,023   21,363  105 / 108
#   create/modify_program 설명      14,316   21,363  105 / 108
#
# **도구는 하나도 늘지 않았다.** 이번 +293 은 이미 있던 도구 둘의 설명이다 —
# 이런 증가야말로 이 상한이 잡으라고 있는 것이라 근거를 적는다.
#
# `create_program` 핸들러는 처음부터 `stages[].guidance` 와 `target_defs` 를
# 받았는데 **매니페스트가 그것을 말하지 않았다.** 그래서 AI 는 지침을 채울 수
# 있다는 사실 자체를 몰랐고, 단계 지침은 사람이 코드 상수(`_STAGE_GUIDANCE`)에
# 손으로 적어 배포해야만 늘어났다 — 작목 하나 추가가 커밋 하나였다. 스키마를
# 실제 핸들러에 맞추고, 스마트팜코리아에서 검증된 RECIPE 패턴(절차를
# `usage_hint` 에 주입)을 같은 방식으로 얹은 것이 이 증가의 전부다.
#
# 되돌려 아끼면 그 293토큰만큼 **기능이 없어진다**(AI 가 프로그램을 채우지 못하고
# 사람이 다시 코드로 적는다). 문구가 부푼 경우와 구분되는 지점이라 상한을 올린다.
# `create_program` 설명에서 스키마 중복(days 규칙·source_note)은 hint 로 옮겨
# 덜어냈다 — propose_plot_split 때와 같은 정리이고, 그것으로 26토큰을 되찾았다.
# ── 2026-08-22 재기준선 — 프로그램 도구를 MCP 에 싣는다 ─────────────────────
#
#   무엇                          에이전트    MCP     도구
#   직전                           14,316   21,363  105 / 108
#   프로그램 도구 5종 MCP 배선        14,316   23,004  105 / 113
#
# **에이전트 쪽은 한 톨도 안 늘었다** — 도구는 2026-08-19 부터 있었고, 없던 것은
# `_MCP_TOOL_PAYLOADS` 항목뿐이다. 카탈로그에도 서랍에도 없으면 **그 도구는 어떤
# MCP 클라이언트로도 부를 수 없다**(실측: `_drawer_index` 에도 'program' 이 없었다).
# 탭 도구 4종이 걸렸던 것과 같은 함정이고, 이번에는 증상이 더 뚜렷했다 —
# `create_plot` 스키마가 이미 "unique_id from list_programs" 라고 안내하는데
# 정작 그 도구가 안 보였다.
#
# 늘어난 1,641 은 **없던 기능이 아니라 닿지 않던 기능의 값**이다. 되돌리면
# 프로그램은 MCP 사용자에게 존재하지 않는 기능으로 되돌아간다.
#
# ⚠ 이 숫자는 **서랍을 껐을 때**의 값이다(위 2026-08-21 주석 참조). 서랍이
# 기본 켜짐이라 `tools/list` 에 실제로 나가는 것은 core + 서랍 기계장치뿐이고,
# 이 5종은 `_TIER_ASSIGNMENT` 에서 space/drawer 라 서랍 인덱스에 **이름만**
# 늘어난다. 실제 고정비는 test_mcp_tool_surface.py 가 잰다.
# ── 2026-08-24 재기준선 — 지식 도구가 조사 결과를 받게 한다 ─────────────────
#
#   무엇                              에이전트    MCP     도구
#   직전                               14,316   23,004  105 / 113
#   지식 도구 문구 정합 + source_url     14,411   23,142  105 / 113
#
# **도구 수는 그대로다.** 늘어난 것은 두 가지뿐이고 둘 다 문구가 아니라 계약이다:
#
# (1) `knowledge_shelve` 가 "네가 **조사한** 결과" 의 적립을 명시 허용한다.
#     예전 설명은 "derived / observed / were told" 뿐이라, MCP 로 연결된 외부
#     LLM 이 웹에서 조사한 요약을 "이 도구 대상이 아니다" 로 읽을 수 있었다.
#     도구는 처음부터 부를 수 있었지만 **부를 이유가 안 적혀 있었다** — 2026-08-22
#     의 "닿지 않던 기능" 과 같은 계열이고, 이번엔 배선이 아니라 문장이 막고 있었다.
# (2) `source_url` 파라미터 신설. 출처 주소를 담을 자리가 없으면 리뷰어가 원문으로
#     돌아갈 수 없고, 그러면 §3.2 승격 경로가 실질적으로 막혀 AI 가 비친 지식이
#     영원히 미확인으로 남는다. 스키마 필드 하나의 값이다.
#
# 문구 부풀림 쪽은 **먼저 덜어냈다**(propose_plot_split 선례): 연쇄 레시피를 두
# 표면에 중복으로 싣지 않고 나눴고 — 내장 에이전트는 루프 프롬프트가 그 지시를
# 이미 싣는다 — read_manual 대비 설명이 description 과 usage_hint 에 두 번 있던
# 것, attribution 안내가 description 과 스키마에 겹치던 것을 각각 한 곳으로
# 합쳤다. 그 정리로 288토큰 중 대부분을 되찾고 남은 것이 위 숫자다.
# ── 2026-08-24 재기준선 (2) — main 병합 후 실측 ─────────────────────────────
#
#   무엇                          에이전트      MCP    도구
#   지식 도구 정합(이 브랜치 단독)   14,411   23,142  105 / 113
#   main (구획 단계 일정 병합분)     14,975   23,024  110 / 113
#   병합 결과                       15,070   23,162  110 / 113
#
# **두 몫을 나눠 적는다. 대부분이 내 것이 아니다.**
# - main 이 도구 5종을 더하면서 상한을 함께 올리지 않아 **병합 전부터 이미
#   14,975 > 14,400 으로 넘어 있었다**(main 체크아웃에서 이 테스트를 돌려
#   확인). 575 는 그쪽 몫이다.
# - 내 몫은 95(에이전트)·138(MCP) 이고 도구 수는 **하나도 안 늘었다** —
#   knowledge_shelve 설명 정합과 source_url 파라미터, knowledge_search 의
#   core 승격뿐이다.
#
# 상한을 올려 그쪽 누락을 덮는 모양이 되는 것이 마음에 걸리지만, 병합된 트리를
# 재는 검사라 내 몫만 반영할 방법이 없다. 대신 위 표에 두 몫을 남겨 두어
# 나중에 "왜 575 가 늘었나" 를 되짚을 수 있게 한다.
# ── 2026-08-24 재기준선 (3) — 참조표 도구 2종 ───────────────────────────────
#
#   무엇                        에이전트    MCP     도구
#   직전                         15,070   23,162  110 / 113
#   참조표 도구 2종               15,423   23,480  112 / 115
#
# **도구를 더했으니 오른 값이다**(문구 부풀림이 아니다). 그리고 이 둘은 오히려
# 매니페스트를 **줄이려고** 만든 것이다: 행이 수천 개인 표를 지식 항목으로
# 적재하면 매 질의의 검색 후보가 그만큼 늘어난다(실측 ECOCROP 2,568종에서
# 14ms → 73ms, 그보다 엉뚱한 행이 근거로 실리는 쪽이 문제였다). 표를 등록만
# 하고 물어볼 때 조회하는 쪽으로 바꾸면서 그 비용이 통째로 사라졌다 —
# 고정비 353토큰을 내고 가변비를 없앤 거래다.
#
# 둘 다 `record` 서랍이라 서랍을 켠 상태의 상시 노출에는 이름만 늘어난다.
# ── 2026-08-25 재기준선 (4) — 연결된 API 를 물어볼 때 조회 ──────────────────
#
# `query_data_source` 신설(+1 도구). 등록된 REST 소스를 **고정 동기화가 아니라
# 질문할 때** 두드린다.
#
# 왜 이 비용을 내는가: 그 전에는 소스를 등록할 때 정한 파라미터 하나로만 답할 수
# 있었다. 실측(2026-08-25) 스마트팜코리아 노지 농가 1,650곳 중 라이브러리에 들어온
# 것은 **한 곳**뿐이었고, "다른 농가는 어떤가" 는 새 소스를 등록해야 답이 됐다.
# 도구 하나로 1,650곳이 답변 범위에 들어온다.
#
# 목록 도구는 늘리지 않고 이름만 바꿨다(list_reference_tables →
# list_lookup_sources): 표와 API 를 한 자리에서 보여준다. 발견 지점을 둘로 나누면
# 모델이 한쪽만 보고 "없다" 고 단정한다 — 실측으로 이미 한 번 겪었다.
#
# ── 2026-08-25 재기준선 — **자를 바꿨다. 표면은 그대로다** ──────────────────
#
# 아래 세 상한은 지금까지 문자수/4 로 쟀다. 그 가정이 응답 캡에서 두 번 틀렸고
# (08-21, 08-25 — 캡이 통과시킨 응답을 호스트가 거부했다), 실행층은 식별자
# 밀도를 반영한 추정기로 옮겼다. 예산만 옛 자를 쓰면 한쪽은 고쳐지고 한쪽은
# 낙관적인 채로 남으므로 `measure_ai_tool_cost._tok` 이 실행층 추정기를 부르게
# 하고, 그 자로 다시 잰 값으로 상한을 옮긴다.
#
#   대상                   도구    문자     옛 자(/4)   새 자    새 상한
#   에이전트 매니페스트     113   62,953    15,738    31,595    31,800
#   MCP 카탈로그           116   95,471    23,867    47,804    48,100
#   등급 켠 매니페스트       20   14,896     3,724     7,511     7,600
#
# **도구도 설명도 늘리지 않았다** — 숫자가 두 배가 된 것은 전부 자 때문이다.
# 그래서 여유는 예전과 같이 좁게(약 0.6~1%) 둔다.
#
# 여기서 드러난 것: 등급 켠 매니페스트의 "여유 26토큰" 은 실제로는 7,511 이었다.
# 상한이 낙관적인 자로 매겨져 있으면, 예산을 지키고 있다는 표시 자체가 틀린다.
AGENT_MANIFEST_TOKEN_CEILING = 31_800
# 2026-08-25: query_reference_table 에 columns 파라미터가 붙어 23,554 가 됐다.
# 23,600 으로 올린다 — 이 파라미터는 **고정비를 내고 가변비를 줄인다**:
# ECOCROP 한 행이 41컬럼 1,152자라 5행이면 ~2,200토큰인데, 요약 컬럼으로
# 677토큰(3.3배 감소), 필요한 컬럼만 지정하면 276토큰이다(실측 2026-08-25).
# 스키마 몇십 토큰으로 호출당 1,500여 토큰을 아낀다.
# ── 2026-08-25 재기준선 (5) — 구획 단계 원장 8종을 MCP 에 싣는다 ────────────
#
#   무엇                          에이전트    MCP     도구
#   직전                          31,399   46,707  113 / 116
#   단계 원장 8종 MCP 배선          31,399   50,086  113 / 124
#
# **에이전트 쪽은 한 톨도 안 늘었다** — 도구는 2026-08-24(624fa873) 부터 있었고,
# 없던 것은 `_MCP_TOOL_PAYLOADS` 항목뿐이다. 2026-08-22 프로그램 도구 5종과
# **같은 함정을 같은 자리에서 다시 밟았다**(tool_registry.py 의 경고 주석이
# 가리키는 바로 그것): 카탈로그에 없으면 서랍 인덱스에도 없고, 그러면 어떤 MCP
# 클라이언트도 그 이름을 볼 수 없다. `get_plot` 이 `stage_proposal` 을 내며
# "확인하라" 고 안내하는데 확인할 도구가 안 보이는 상태였다.
#
# 늘어난 3,379 는 **없던 기능이 아니라 닿지 않던 기능의 값**이다. 되돌리면
# 외부 MCP 사용자에게 단계 원장은 읽기 전용으로 되돌아간다 — 전환을 확인할
# 수도, 밀린 일정을 적을 수도 없다.
#
# 문구 부풀림 쪽은 먼저 봤다: 파라미터 규칙(days/shift_days/started_on 중
# 하나, after 의 빈 문자열 규약, stage_key 의 출처)은 전부 스키마에만 두고
# description 에서 되풀이하지 않았다. 가장 큰 것이 reschedule_plot_stage
# 1,353자로, `SINGLE_TOOL_CHAR_CEILING` 의 40% 다.
#
# ⚠ 이 숫자는 **서랍을 껐을 때**의 값이다. 8종 모두 `_TIER_ASSIGNMENT` 에서
# space/drawer 라, 서랍이 켜진 실제 `tools/list` 에는 서랍 인덱스에 **이름만**
# 늘어난다.
#
# 여유는 관례대로 좁게 둔다(0.6%).
#
# ── 2026-09-02 재기준선 (6) — 구획/구역 일지(Journal) 조회 2종 ──────────────
#
#   무엇                          에이전트    MCP     도구
#   직전(08-25 기준)               31,399   50,086  113 / 124
#   현재(일지 2종 + 그 사이 배선)    31,799   51,623  115 / 127
#
# 늘어난 1,537 중 618(list_plot_journals+get_plot_journal, space/drawer)이
# 이번 커밋 몫이고, 나머지는 그 사이 이미 배선된 get_note_attachment 등이
# 이 상한에 한 번도 반영되지 않았던 것 — 08-25 이후 처음 다시 잰 값이다.
#
# 문구 부풀림 쪽은 먼저 봤다: 두 도구 모두 journal_id 를 "내부 핸들, 사용자에게
# 보이지 말 것"으로 스키마 설명 한 줄에만 적고 되풀이하지 않았다. 가장 큰 것도
# list_plot_journals 695자로 `SINGLE_TOOL_CHAR_CEILING` 의 20%다.
#
# 여유는 관례대로 좁게 둔다(0.6%).
MCP_CATALOG_TOKEN_CEILING = 51_950

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
# 2026-08-24: `knowledge_search` core 승격으로 3,600 → 3,679(+79: 도구 167,
# 서랍 인덱스에서 이름 하나 빠져 -88). 상한을 3,700 으로 올린다.
#
# **먼저 무엇을 대신 내릴지 봤다**(이 상한이 강제하는 질문이다). 지금 등급
# 매니페스트 20개 중 knowledge_search 보다 덜 중요한 것을 찾지 못했다 —
# list_ai_agents(40)·list_device_types(96) 가 후보로 보였으나, 둘 다 이 작업과
# 무관한 흐름(AI 설정, 장치 정의)이 쓰는 도구라 여기서 판단할 일이 아니다.
# 배정표는 "주기적으로 사람이 다시 보는 판단" 이고, 곁다리로 건드릴 자리가
# 아니다.
#
# 올리는 근거: 이 도구가 안 보이면 LLM 은 주제 질문에 **자기 기억으로 답한다**
# — 라이브러리 전체가 막으려는 실패이고, 2026-08-24 에 실제로 그 상태였다
# (docs/design/ai-library-redesign.md §10.1). 쓰기 동사(knowledge_shelve)는
# 올리지 않았다: 그것이 필요해질 때는 이미 record 서랍이 열려 있다.
# 2026-08-24(2): main 병합 후 3,708. main 단독은 3,544(19항목), 내 쪽에서
# knowledge_search 가 core 로 올라와 20항목이 됐다. 3,750 으로 올린다.
TIERED_MANIFEST_TOKEN_CEILING = 7_600

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

        # 위 두 상한과 **같은 자로** 잰다. 여기만 문자수/4 로 세던 탓에 이
        # 숫자가 실제의 절반으로 보였다(2026-08-25 재기준선 주석 참조).
        _, tokens = _tok(json.dumps(entries, ensure_ascii=False, default=str))
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
