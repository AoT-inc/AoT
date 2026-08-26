# coding=utf-8
"""답을 내보내기 전에 스스로 점검한다.

왜 이 방향인가. 2026-08-25~26 동안 "이렇게 하지 말라" 를 단계 프롬프트에
계속 얹었고 8,300자·CRITICAL 류 지시 14개까지 늘었는데, 실사용에서 그
지시들이 나란히 무시됐다 — 묻지 않은 센서값 나열, 내부 설정 용어 설명,
금지한 존칭 대신 새 존칭 만들어 쓰기, 채우기 사과.

사용자 판단: "많이 준다고 다 잘하는게 아니야. 스스로 목표를 달성했는지
검토하고 답변을 제공하는게 더 합리적."

그래서 '답변이 어떠해야 하는가' 부류는 앞에서 빼고 끝의 점검으로 옮겼다.
점검 프롬프트는 짧고 초점이 하나라 열네 번째 규칙처럼 묻히지 않는다.
"""
import pytest


class _Engine:
    """점검 호출을 가로채는 대역."""

    def __init__(self, reply=None):
        self.reply = reply
        self.prompt = None
        self.calls = 0

    def run_reasoning(self, context, prompt):
        self.calls += 1
        self.prompt = prompt
        if self.reply is None:
            raise RuntimeError('engine down')
        return {'insight': self.reply}


def _review(engine, command, draft):
    from aot.ai.services.agent_loop_service import AgentLoopService
    return AgentLoopService._self_review(engine, command, draft)


class TestTheReviewCanRewrite:
    def test_a_rewritten_answer_replaces_the_draft(self):
        eng = _Engine('9월 상순에 관부가 반쯤 묻히게 심습니다.')
        out = _review(eng, '설원6 정식 어떻게 해?',
                      '지식 라이브러리에서 찾을 수 없습니다.')
        assert out == '9월 상순에 관부가 반쯤 묻히게 심습니다.'

    def test_an_unchanged_draft_survives(self):
        draft = '관부가 반쯤 묻히게 심고 충분히 관수합니다.'
        assert _review(_Engine(draft), '정식 방법', draft) == draft


class TestItNeverLosesTheAnswer:
    """점검이 답을 잃는 일은 없어야 한다 — 있으나 마나가 아니라 해로워진다."""

    def test_an_engine_failure_keeps_the_draft(self):
        draft = '원래 답변'
        assert _review(_Engine(None), '질문', draft) == draft

    def test_an_empty_review_keeps_the_draft(self):
        draft = '원래 답변'
        assert _review(_Engine('   '), '질문', draft) == draft

    def test_an_empty_draft_does_not_call_the_engine(self):
        eng = _Engine('무언가')
        assert _review(eng, '질문', '') == ''
        assert eng.calls == 0, '빈 초안에 호출을 낭비하지 않는다'


class TestTheChecklistCoversTheObservedFailures:
    """실사용에서 실제로 나온 것들만 담는다 — 일반론을 늘리면 다시 희석된다."""

    def _prompt(self):
        eng = _Engine('ok')
        _review(eng, '설원6은 어떻게 정식해?', '초안')
        return eng.prompt

    def test_it_asks_whether_that_question_was_answered(self):
        """'적합하냐' 에 현재 센서값을 나열하던 것."""
        p = self._prompt()
        assert 'Does it answer THAT question' in p
        assert 'A related fact is not an answer' in p

    def test_it_checks_the_opening(self):
        p = self._prompt()
        assert 'Does it open with the answer' in p

    def test_it_names_the_internals_to_cut(self):
        """추상적으로 적으면 안 걸린다 — 실제로 나온 용어를 적는다."""
        p = self._prompt()
        for term in ('knowledge library', 'API keys', 'coordinates', 'stale'):
            assert term in p, term

    def test_it_checks_for_unrequested_data(self):
        p = self._prompt()
        assert 'anything they did not ask for' in p
        assert 'current sensor values' in p

    def test_it_names_the_address_forms(self):
        """고객님을 막았더니 '조원님' 을 만들어 썼다 — 부류로 적어야 한다."""
        p = self._prompt()
        assert '고객님' in p and 'お客様' in p
        assert 'the grower who runs this place' in p

    def test_it_demands_only_the_answer_back(self):
        """점검 결과가 사용자 화면에 새면 고치려다 더 나빠진다."""
        p = self._prompt()
        assert 'Return ONLY the final answer text' in p
        assert 'no labels' in p

    def test_the_draft_and_request_are_both_shown(self):
        p = self._prompt()
        assert '설원6은 어떻게 정식해?' in p
        assert '초안' in p


class TestTheStepPromptShedTheseRules:
    """앞에 남겨 두면 다시 열네 개가 된다 — 옮겼으면 빼야 한다."""

    def _step_prompt(self):
        from aot.ai.services.agent_loop_service import AgentLoopService
        return AgentLoopService._build_step_prompt('설원6 정식 방법', [], 0)

    @pytest.mark.parametrize('rule', [
        'NEVER NARRATE YOUR OWN MACHINERY',
        'DO NOT PAD',
        'NEVER OPEN WITH WHAT YOU COULD NOT FIND',
        'ANSWER THE QUESTION THAT WAS ASKED',
        'HOW TO ADDRESS THEM',
    ])
    def test_the_answer_style_rule_is_gone(self, rule):
        assert rule not in self._step_prompt()

    def test_the_tool_rules_stayed(self):
        """옮긴 것은 '답변이 어떠해야 하는가' 뿐이다. 무엇을 할지에 대한
        지시는 단계 프롬프트에 남아야 한다."""
        p = self._step_prompt()
        assert 'SUBJECT / DOMAIN QUESTIONS' in p
        assert "NEVER FABRICATE THIS INSTALLATION'S STATE" in p

    def test_the_prompt_actually_got_smaller(self):
        """옮기기 전 실측이 8,334자·CRITICAL 류 14개였다. 옮긴 뒤 6,447자·10개.

        상한을 실측 바로 위에 둔다 — 여유를 크게 주면 다시 채워 넣게 되고,
        그러면 지시가 서로를 희석시키는 원래 문제로 돌아간다."""
        import re

        p = self._step_prompt()
        assert len(p) < 7000, len(p)
        assert len(re.findall(r'CRITICAL|NEVER|ALWAYS|DO NOT|Do NOT', p)) <= 11
