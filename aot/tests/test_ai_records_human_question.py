# coding=utf-8
"""
AI 기록 "대화" 탭 — 저장된 요청에서 사람이 쓴 질문만 남기는지.

내장 AI 에 보낸 원문 앞에는 시스템이 붙인 문맥(모드·페이지 문맥·페이지 구조·
대시보드 값)이 쌓여 있다. 그대로 싣으면 기록 첫 줄이 전부 "[MODE: FAST] …"
이고 페이지 UUID 가 보였다(2026-09-10 실측, 40건 중 17건).
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.aot_flask.routes_ai_agent import _human_question

UUID = '618d4ae7-a577-4f31-9b07-09b3aa11bb22'


def test_mode_and_page_context_lines_are_dropped():
    raw = ("[MODE: FAST] Answer concisely and directly; keep it brief.\n"
           "[MODE: ADVICE-ONLY] Do not propose any executable action.\n"
           "[Page Context: URL=https://x/device, Title='AoT - 장치', Focused function='Modbus PLC' (ID: %s)]\n"
           "IMPORTANT: Provide specific advice or help based on the Page Context provided above.\n"
           "Please analyze the 'Modbus PLC' (function) device." % UUID)
    out = _human_question(raw)
    assert out == "Please analyze the 'Modbus PLC' (function) device."
    assert UUID not in out


def test_page_structure_block_and_indented_widget_lines_are_dropped():
    raw = ("[MODE: FAST] Answer concisely and directly; keep it brief.\n"
           "[Page Context: URL=https://x/dashboard/%s, Title='AoT - 김제 대시보드']\n"
           "[Page structure — what this page is for (use this to describe the page):\n"
           "  Heading: Aug 26 – Sep 24, 2026\n"
           "  This is the actual page the user is viewing now.\n"
           "]\n"
           "IMPORTANT: Provide specific advice or help based on the Page Context provided above.\n"
           "[Current dashboard widget data (server-fetched) — what is on the user's screen right now]\n"
           "  - 습도 (AoT_gauge_angular): humidity = 100.0 percent\n"
           "  - 온도 (AoT_gauge_angular): temperature = 23.34 C\n"
           "지금 온실 습도가 너무 높은가?" % UUID)
    assert _human_question(raw) == "지금 온실 습도가 너무 높은가?"


def test_system_context_line_with_dashboard_uuid_is_dropped():
    """실측 22건이 이 모양으로 시작했다 — 대시보드 UUID 가 기록 첫 줄에 보였다."""
    raw = ("[System Context: The user is currently viewing Dashboard ID '%s']\n"
           "불필요한 정보 늘어놓지 말라니까" % UUID)
    out = _human_question(raw)
    assert out == "불필요한 정보 늘어놓지 말라니까"
    assert UUID not in out


def test_a_question_that_itself_starts_with_a_bracket_is_kept():
    """사람이 쓴 괄호([3-1] 처럼 대문자 이름·콜론 모양이 아닌 것)는 건드리지 않는다."""
    assert _human_question("[3-1] 구획 물 줘도 돼?") == "[3-1] 구획 물 줘도 돼?"


def test_plain_question_is_kept_as_is():
    assert _human_question("설원6은 어떻게 정식해야하지?") == "설원6은 어떻게 정식해야하지?"


def test_empty_and_none_are_safe():
    assert _human_question(None) == ''
    assert _human_question("[MODE: FAST] only context\n") == ''
