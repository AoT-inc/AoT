# coding=utf-8
"""
엔진별 프롬프트 예산 계약.

왜 이 파일이 있는가 (2026-08-24 진단). `_build_prompt` 는 예산을 넘으면 프롬프트
**꼬리를 하드 컷** 하는데, 꼬리에는 `SYSTEM INSTRUCTIONS` 블록과 재진술된 목표가
있다. 즉 예산 초과는 답변이 조금 나빠지는 일이 아니라 **모델이 지시를 잃는 일**
이다.

그런데 base_ai 의 standard 기본값이 100,000자였고, 실제로 쓰이던 엔진(gemini)만
그것을 600k 로 오버라이드해 두었다. 오버라이드가 없던 다섯
(anthropic·openai·openai_compatible·mistral·ollama)은 이 설치의 실측 프롬프트
197,267자에서 **97,767자를 잃고 있었다** — 그리고 AoT 는 사용자가 엔진을 고르는
시스템이다(모델 불가지 원칙). 개발자가 쓰던 엔진에서만 맞는 값은 기본값이 아니다.

여기서 고정하는 것은 숫자 자체가 아니라 **숫자가 왜 그 값인지 사람이 다시 보게
만드는 것**이다. 표를 바꾸려면 이 테스트를 함께 고쳐야 하고, 그때 아래 주석을
읽게 된다.
"""
import importlib
import inspect
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from aot.ai.agents.base_ai import AbstractAI

_ENGINES = ['anthropic', 'gemini', 'groq', 'minimax', 'mistral',
            'ollama', 'openai', 'openai_compatible']

# 자기 창을 아는 엔진은 스스로 선언한다. 여기 없는 엔진은 base_ai 기본값을 쓴다.
_HAS_OWN_BUDGET = {'gemini', 'groq', 'minimax', 'ollama', 'openai_compatible'}

# **일부러 기본값보다 낮게** 잡은 엔진과 그 이유. 낮은 값이 실수가 아니라 판단
# 이라는 것을 여기 적어 둔다 — 나중에 "왜 이것만 작지?" 하고 올리는 일을 막는다.
_DELIBERATELY_SMALL = {
    'ollama': '로컬 num_ctx 가 실제 상한이고, 넘기면 Ollama 가 앞에서부터 자른다',
    'groq': '창이 아니라 TPM(분당 토큰) 요금제 한도가 실제 제약이다',
    'openai_compatible': '어느 엔드포인트인지 알 수 없다 — 모를 때는 작게 잡는다',
}

_TIERS = ('lightweight', 'standard', 'heavy')


def _budget_fn(name):
    """엔진 모듈에서 그 엔진의 클래스를 찾는다.

    `issubclass(obj, AbstractAI)` 로 고르지 않는다. 전체 스위트로 돌리면 다른
    테스트가 `base_ai` 를 다른 경로로 import 해 **같은 이름의 다른 클래스 객체**
    가 생기고, 그러면 상속 판정이 거짓이 되어 이 파일만 조용히 깨졌다(파일 하나만
    돌리면 통과, `pytest aot/tests` 로 돌리면 실패 — 2026-08-24 실측).

    그래서 정체성이 아니라 **모양**으로 고른다: 그 모듈에서 정의됐고
    `get_context_budget` 을 가진 클래스. 이 검사가 재려는 것이 정확히 그것이다."""
    mod = importlib.import_module('aot.ai.agents.%s' % name)
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj.__module__ == mod.__name__ and hasattr(obj, 'get_context_budget'):
            return obj.__dict__.get('get_context_budget') or AbstractAI.get_context_budget, obj
    raise AssertionError('%s 에서 엔진 클래스를 찾지 못했다' % name)


def _budget(name, tier):
    fn, _ = _budget_fn(name)
    return fn(type('S', (), {'model_tier': tier})())


class TestEngineContextBudgets(unittest.TestCase):

    def test_base_default_matches_the_unknown_tier_fallback(self):
        """standard 가 '모르는 등급' 기본값보다 낮으면 그것이 이상 신호다 —
        실제로 100,000 < 300,000 이었고, 그 불일치가 이번 사고의 형태였다."""
        shim_std = type('S', (), {'model_tier': 'standard'})()
        shim_unknown = type('S', (), {'model_tier': 'no_such_tier'})()
        self.assertEqual(AbstractAI.get_context_budget(shim_unknown),
                         AbstractAI.get_context_budget(shim_std))

    def test_tiers_are_monotonic_for_every_engine(self):
        for name in _ENGINES:
            vals = [_budget(name, t) for t in _TIERS]
            self.assertEqual(sorted(vals), vals,
                             '%s 의 등급별 예산이 단조증가가 아니다: %s' % (name, vals))

    def test_every_engine_that_goes_below_the_default_says_why(self):
        """기본값보다 낮은 예산은 판단이어야 하고, 판단에는 이유가 있어야 한다.
        새 엔진이 이유 없이 낮은 값을 들고 들어오면 여기서 걸린다."""
        default_std = AbstractAI.get_context_budget(
            type('S', (), {'model_tier': 'standard'})())
        for name in _ENGINES:
            if _budget(name, 'standard') < default_std:
                self.assertIn(name, _DELIBERATELY_SMALL,
                              '%s 가 기본값보다 낮은 예산을 쓰는데 이유가 '
                              '_DELIBERATELY_SMALL 에 없다' % name)

    def test_engines_without_a_documented_reason_fit_a_realistic_prompt(self):
        """실측 근거: 이 설치의 에이전트 루프 프롬프트는 197,267자다.
        '작게 잡은 이유'가 없는 엔진은 그 크기를 담을 수 있어야 한다 — 못 담으면
        시스템 지시가 잘려 나간다."""
        measured_prompt_chars = 197_267
        for name in _ENGINES:
            if name in _DELIBERATELY_SMALL:
                continue
            self.assertGreaterEqual(
                _budget(name, 'standard'), measured_prompt_chars,
                '%s 의 standard 예산이 실측 프롬프트보다 작다 — SYSTEM '
                'INSTRUCTIONS 와 재진술 목표가 잘린다' % name)

    def test_declared_overrides_match_reality(self):
        """_HAS_OWN_BUDGET 가 실제 코드와 어긋나면, 위 검사들이 엉뚱한 대상을
        재게 된다."""
        for name in _ENGINES:
            _, cls = _budget_fn(name)
            has_own = 'get_context_budget' in cls.__dict__
            self.assertEqual(name in _HAS_OWN_BUDGET, has_own,
                             '%s 의 오버라이드 보유 여부가 표와 다르다' % name)

    def test_no_engine_sits_below_the_fixed_prompt_floor(self):
        """실측(2026-08-24): 컨텍스트를 완전히 비워도 프롬프트에 **17,645자**가
        남는다 — 머리말, 시스템 지시, 목표(앞·뒤 2회), 응답형식 꼬리. 예산이
        그보다 작으면 줄일 컨텍스트가 없어 **지시부터** 잘린다. 즉 그 아래
        값은 '작게 잡았다' 가 아니라 '작동하지 않는다' 는 뜻이다.

        여유를 두어 20,000 을 하한으로 본다. 여기 걸리는 엔진이 생기면 숫자를
        낮출 게 아니라 그 엔진에 이 프롬프트를 태우는 것이 맞는지를 먼저
        물어야 한다."""
        MEASURED_FLOOR = 17_645
        for name in _ENGINES:
            for tier in _TIERS:
                self.assertGreater(
                    _budget(name, tier), MEASURED_FLOOR,
                    '%s/%s 예산이 고정 프롬프트 바닥(%d)보다 작다 — 컨텍스트가 '
                    '아니라 시스템 지시가 잘린다' % (name, tier, MEASURED_FLOOR))

    def test_tool_result_cap_is_a_separate_dial(self):
        """도구 결과 상한을 프롬프트 예산에 묶으면, 예산을 올리는 순간 도구 하나가
        컨텍스트를 통째로 먹을 수 있게 된다. 두 값은 따로 있어야 한다."""
        self.assertNotIn('get_context_budget',
                         inspect.getsource(AbstractAI.truncate_tool_result_json))


if __name__ == '__main__':
    unittest.main()
