# coding=utf-8
"""
Phase A 회귀 테스트 — 에이전트 루프의 지식 접지 계약.

왜 이 파일이 있는가. P2/P6 은 "지식 검색·주입·신뢰 표기는 모델이 아니라 서버가
보장한다" 를 계약으로 세우고 fast path/collab 경로에 구현했다. 그 뒤 응답 경로가
AgentLoopService 로 이관되면서 두 장치(_manual_grounding 주입,
_enforce_unconfirmed_disclosure 고지 가드)가 새 경로에 옮겨지지 않아 **계약이
조용히 깨졌다** — 유닛테스트 65건은 그대로 통과했고, 서비스에서만 지식이 안 닿았다.

그래서 여기서 검사하는 것은 knowledge_search 의 동작이 아니라 **루프가 그것을
부르고 결과를 어디에 싣는가** 다. 다음 경로 이관 때 같은 방식으로 끊기면 여기서
잡힌다.

In-memory sqlite, 가짜 엔진 — 라이브 DB·실제 LLM 미접촉
(feedback_never_test_against_live_db).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.ai.services.agent_loop_service import AgentLoopService
from aot.ai.services.ai_agent_service import AIAgentService


_UNCONFIRMED_BLOCK = (
    "[Knowledge search: 'test' — 2 section(s)]\n\n"
    "### 김제 2포장 급수 밸브  [AI 정리 — 미확인]\n"
    "개방 후 관로 압력이 안정되기까지 약 45초가 걸린다. 유량계는 그 전에 낮게 읽힌다.\n\n"
    "---\n\n"
    "### 온도 조절  (Functions.ko.md)\n"
    "PID 컨트롤러로 설정값을 맞춘다.\n"
)


def _make_test_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class _FakeEngine:
    """엔진 대역 — 받은 context/prompt 를 기록하고 즉시 최종답변을 낸다."""

    def __init__(self, insight="약 45초가 걸립니다."):
        self.calls = []
        self._insight = insight

    def run_reasoning(self, context, prompt):
        self.calls.append({'context': context, 'prompt': prompt})
        return {'insight': self._insight, 'actions': []}


class _FakeAgent:
    unique_id = 'agent-test'
    model_tier = 'standard'


class TestLoopPromptCarriesGroundingContract(unittest.TestCase):
    """프롬프트 계약 — 앱 컨텍스트가 필요 없는 순수 문자열 검사."""

    def test_directive_present_only_when_grounding_is(self):
        with_ref = AgentLoopService._build_step_prompt(
            'q', [], 0, history=None, manual_ref=_UNCONFIRMED_BLOCK)
        without = AgentLoopService._build_step_prompt('q', [], 0, history=None)
        self.assertIn('KNOWLEDGE GROUNDING', with_ref)
        self.assertNotIn('KNOWLEDGE GROUNDING', without,
                         "근거가 없는데 인용 규약만 실리면 모델이 없는 블록을 찾는다")

    def test_positive_library_rule_is_always_present(self):
        """'노트 질문에 knowledge_search 쓰지 말라' 는 부정 지시만 있던 상태로
        돌아가면 잡는다 — 짝이 없으면 모델은 도서관을 아예 안 뒤진다."""
        p = AgentLoopService._build_step_prompt('q', [], 0, history=None)
        self.assertIn('USE THE LIBRARY FIRST', p)
        self.assertIn('knowledge_shelve', p)


class TestLoopInjectsGrounding(unittest.TestCase):
    def setUp(self):
        self.app = _make_test_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _run(self, engine, grounding=_UNCONFIRMED_BLOCK, insight=None):
        with mock.patch.object(AgentLoopService, '_resolve_agent', return_value=_FakeAgent()), \
             mock.patch.object(AIAgentService, 'get_engine', return_value=engine), \
             mock.patch.object(AIAgentService, 'get_thread_history', return_value=[]), \
             mock.patch.object(AIAgentService, '_manual_grounding', return_value=grounding) as g, \
             mock.patch('aot.ai.services.ai_action_service.AIActionService.get_action_manifest',
                        return_value={'system_tools': []}), \
             mock.patch('aot.ai.services.ai_context_service.AIContextService.get_master_context',
                        return_value={'devices': []}), \
             mock.patch('aot.ai.ai_dispatch_service.AIDispatchService._dispatch_actions',
                        side_effect=lambda **kw: {'proposed': [], 'immediate_results': [],
                                                  'draft_ids': [], 'history_id': 1,
                                                  '_insight_seen': kw.get('insight')}) as d:
            res = AgentLoopService.run('밸브 압력 안정화 얼마나 걸려?')
        return res, g, d

    def test_grounding_is_injected_at_the_front_of_the_context(self):
        """base_ai 는 컨텍스트를 삽입 순서로 직렬화하고 티어 예산에서 프롬프트
        꼬리를 하드 절단한다. 뒤에 붙이면 큰 설치에서 통째로 잘린다(2026-07-19
        fast path 실측). 그래서 '실렸는가' 가 아니라 '앞에 실렸는가' 를 잰다."""
        engine = _FakeEngine()
        self._run(engine)
        keys = list(engine.calls[0]['context'].keys())
        self.assertIn('manual_reference', keys)
        self.assertEqual('manual_reference', keys[0])

    def test_grounding_is_retrieved_once_not_per_step(self):
        engine = _FakeEngine()
        _, grounding_mock, _ = self._run(engine)
        self.assertEqual(1, grounding_mock.call_count)

    def test_short_followup_in_an_ongoing_conversation_is_not_grounded(self):
        """fast path 실측: '안내해줘' 같은 짧은 이어말에 역량 문서를 실으면
        답변이 일반적인 시스템 소개로 납치된다. 접지를 루프로 옮길 때 접지를
        **하지 않을 조건**도 같이 옮겨야 한다."""
        engine = _FakeEngine()
        with mock.patch.object(AgentLoopService, '_resolve_agent', return_value=_FakeAgent()), \
             mock.patch.object(AIAgentService, 'get_engine', return_value=engine), \
             mock.patch.object(AIAgentService, 'get_thread_history',
                               return_value=[{'role': 'user', 'content': '앞선 대화'}]), \
             mock.patch.object(AIAgentService, '_manual_grounding',
                               return_value=_UNCONFIRMED_BLOCK) as g, \
             mock.patch('aot.ai.services.ai_action_service.AIActionService.get_action_manifest',
                        return_value={'system_tools': []}), \
             mock.patch('aot.ai.services.ai_context_service.AIContextService.get_master_context',
                        return_value={}), \
             mock.patch('aot.ai.ai_dispatch_service.AIDispatchService._dispatch_actions',
                        side_effect=lambda **kw: {'proposed': [], 'immediate_results': [],
                                                  'draft_ids': [], 'history_id': 1}):
            AgentLoopService.run('안내해줘', thread_id='t1')
        self.assertEqual(0, g.call_count, "짧은 이어말엔 조회조차 하지 않는다")
        self.assertNotIn('manual_reference', engine.calls[0]['context'])

    def test_no_grounding_means_no_manual_reference_key(self):
        engine = _FakeEngine()
        self._run(engine, grounding='')
        self.assertNotIn('manual_reference', engine.calls[0]['context'])

    def test_unconfirmed_note_gets_disclosure_appended(self):
        """모델이 미확인 메모를 인용하고도 그 사실을 안 밝히면 서버가 붙인다.
        루프가 기본 경로가 된 뒤 이 가드가 없어 계약이 깨져 있었다.

        여기서 재는 것은 **가드가 루프에 배선됐는가** 이지 가드의 민감도가
        아니다(민감도는 test_knowledge_p6 몫). 그래서 답변 문구는 가드의
        문서화된 발화 조건(고유 숫자 1개 + 고유 단어 2개 이상)을 분명히
        만족하도록 골랐다.

        (2026-08-24: 부분문자열 매칭이 한국어 어미 변형을 놓치던 한계는
        fast path와 공유하는 _enforce_unconfirmed_disclosure 자체에서 어간
        비교로 고쳤다 — 이 루프도 같은 함수를 부르므로 자동으로 적용된다.
        해당 케이스는 test_knowledge_p6.test_disclosure_survives_korean_inflection
        몫이라 여기서 되풀이하지 않는다.)"""
        engine = _FakeEngine(insight="유량계는 개방 후 45초 뒤에 읽으십시오.")
        res, _, _ = self._run(engine)
        self.assertIn('미확인', res['insight'])

    def test_disclosure_not_duplicated_when_model_already_disclosed(self):
        engine = _FakeEngine(insight="미확인 메모에 따르면 약 45초입니다.")
        res, _, _ = self._run(engine)
        self.assertEqual(1, res['insight'].count('미확인'))

    def test_answer_unrelated_to_the_unconfirmed_note_is_left_alone(self):
        engine = _FakeEngine(insight="PID 컨트롤러로 설정값을 맞추시면 됩니다.")
        res, _, _ = self._run(engine)
        self.assertNotIn('미확인', res['insight'])


if __name__ == '__main__':
    unittest.main()
