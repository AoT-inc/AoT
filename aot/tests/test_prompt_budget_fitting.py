# coding=utf-8
"""
프롬프트 예산 맞추기 — `_fit_context_to_budget` 계약.

무엇이 문제였나(2026-08-24 실측). `_build_prompt` 는 조립을 끝낸 프롬프트가
예산을 넘으면 **꼬리를 하드 컷** 했다. 그런데 조립 순서상 꼬리에 있는 것은
`SYSTEM INSTRUCTIONS` 블록과 재진술된 목표다 — 즉 예산 초과는 "데이터를 조금
덜 받는" 일이 아니라 **모델이 지시를 통째로 잃는** 일이었다. 197,267자
프롬프트를 100,000자로 자르면 지시(pos 184,266)와 목표(187,459)가 사라졌다.

해법은 순서를 바꾸는 것이 **아니다.** 지시를 앞으로 옮기면 절단이 없는 요청까지
모든 엔진의 프롬프트가 바뀌는데, 그건 검증 없이 할 일이 아니다(지시를 뒤에 두는
배치 자체가 최신성을 노린 것이기도 하다). 대신 들어갈 자리를 먼저 계산해
**컨텍스트만** 줄인다.

그래서 이 파일이 지키는 첫 번째 계약은 "잘 줄인다" 가 아니라
**"넘지 않으면 아무것도 하지 않는다"** 이다.
"""
import json
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.ai.agents.base_ai import AbstractAI


class _Fitter:
    """`_fit_context_to_budget` 만 떼어 쓰는 최소 껍데기 — 엔진 인스턴스를
    만들려면 DB 설정이 필요하고, 이 메서드는 그중 아무것도 쓰지 않는다."""

    def __init__(self, budget):
        self._budget = budget

    def get_context_budget(self):
        return self._budget

    _RESPONSE_FORMAT_TRAILER = AbstractAI._RESPONSE_FORMAT_TRAILER
    _NEVER_DROPPED_CONTEXT_KEYS = AbstractAI._NEVER_DROPPED_CONTEXT_KEYS
    _MIN_DROPPABLE_CHARS = AbstractAI._MIN_DROPPABLE_CHARS
    _fit_context_to_budget = AbstractAI._fit_context_to_budget


def _ctx(**sizes):
    return {k: 'x' * n for k, n in sizes.items()}


def _fit(budget, context, goal='goal', instructions='instr', mcp='', overview='ov'):
    ctx_str = json.dumps(context, separators=(',', ':'), default=str)
    return _Fitter(budget)._fit_context_to_budget(
        context, ctx_str, goal, instructions, mcp, overview)


class TestFitsWithinBudget(unittest.TestCase):

    def test_under_budget_returns_the_context_byte_identical(self):
        """가장 중요한 계약. 예산 안이면 이 코드가 없던 것과 **바이트 단위로**
        같아야 한다 — 그래야 라이브 검증 없이 넣을 수 있다."""
        ctx = _ctx(system_state=5000, capabilities=4000, user_command=20)
        original = json.dumps(ctx, separators=(',', ':'), default=str)
        self.assertEqual(original, _fit(1_000_000, ctx))

    def test_over_budget_drops_whole_keys_so_the_json_stays_parseable(self):
        """문자열을 중간에서 자르면 JSON 이 깨지고, 잘린 도구 목록은 모델에게
        '도구가 이것뿐' 으로 보인다. 키를 통째로 빼면 둘 다 없다."""
        ctx = _ctx(system_state=60000, capabilities=50000, user_command=20)
        out = _fit(40000, ctx)
        parsed = json.loads(out)          # 깨졌으면 여기서 실패한다
        self.assertLessEqual(len(out), 40000)
        self.assertIn('user_command', parsed)

    def test_it_says_what_it_left_out(self):
        """빠진 줄 모르는 모델은 '그런 장치는 없습니다' 라고 단정한다 —
        없는 것과 못 본 것을 구분 못 하는 답이 가장 나쁘다."""
        ctx = _ctx(system_state=60000, capabilities=50000, user_command=20)
        parsed = json.loads(_fit(40000, ctx))
        self.assertIn('_omitted', parsed)
        note = parsed['_omitted']
        self.assertIn('system_state', note, '무엇이 빠졌는지 이름을 대야 한다')
        self.assertIn('does not exist', note.lower(),
                      '없는 것과 못 본 것을 혼동하지 말라는 경고가 있어야 한다')

    def test_the_request_and_its_grounding_are_never_dropped(self):
        """요청과 근거를 버리면 모델은 무엇을 답할지 모른 채 데이터만 받는다."""
        ctx = _ctx(system_state=90000, capabilities=90000,
                   manual_reference=8000, user_command=40, page_context=30)
        parsed = json.loads(_fit(30000, ctx))
        for key in ('manual_reference', 'user_command', 'page_context'):
            self.assertIn(key, parsed, '%s 가 버려졌다' % key)

    def test_biggest_key_goes_first(self):
        """한 번에 가장 많이 회수되는 쪽부터 빼야 덜 잃는다."""
        ctx = _ctx(huge=80000, small=3000, user_command=20)
        parsed = json.loads(_fit(30000, ctx))
        self.assertNotIn('huge', parsed)
        self.assertIn('small', parsed)

    def test_room_is_reserved_for_the_instructions_and_the_trailer(self):
        """이 메서드의 존재 이유. 지시가 길수록 컨텍스트에 남는 자리가 줄어야
        하고, 그 반대가 되면 다시 지시가 잘린다."""
        ctx = _ctx(system_state=40000, user_command=20)
        short = _fit(50000, ctx, instructions='i' * 100)
        long = _fit(50000, ctx, instructions='i' * 20000)
        self.assertLessEqual(len(long), len(short))

    def test_a_broken_calculation_never_breaks_the_request(self):
        """이 계산은 프롬프트를 다듬는 일이지 응답 경로가 아니다 — 실패하면
        원본을 그대로 돌려주고, 종전의 하드컷이 받아 준다."""
        class _Boom(_Fitter):
            def get_context_budget(self):
                raise RuntimeError('boom')
        ctx = _ctx(a=100)
        ctx_str = json.dumps(ctx, separators=(',', ':'))
        self.assertEqual(ctx_str, _Boom(0)._fit_context_to_budget(
            ctx, ctx_str, 'g', 'i', '', 'o'))


if __name__ == '__main__':
    unittest.main()
