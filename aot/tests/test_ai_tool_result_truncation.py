# coding=utf-8
"""Regression tests for AbstractAI.truncate_tool_result_json().

Anthropic's and Gemini's native tool-calling loops (fc_turn while-loop in
anthropic.py / gemini.py) append each tool's raw JSON result to the running
message/contents list with no length guard, unlike _build_prompt()'s initial
prompt, which is truncated via get_context_budget(). Because those APIs are
stateless, every subsequent fc_turn resends the whole accumulated history —
one unfiltered tool call (e.g. list_plantings with no map_id) can burn a
request's entire token budget. truncate_tool_result_json() caps each
individual tool result before it enters that loop; these tests pin that it
actually shrinks oversized payloads instead of passing them through raw, and
that both engines are wired to call it instead of bare json.dumps().
"""
import inspect
import json

from aot.ai.agents.base_ai import AbstractAI


class ConcreteAI(AbstractAI):
    """Minimal concrete subclass — bypasses __init__ (which needs a DB-backed
    agent_config) since truncate_tool_result_json only reads self.model_tier
    and self.__class__.__name__."""

    def __init__(self, model_tier='standard'):
        self.name = "Test AI"
        self.model_tier = model_tier

    def run_reasoning(self, context, goal):
        pass

    def parse_actions(self, raw_response):
        pass


def test_small_result_passes_through_unchanged():
    ai = ConcreteAI()
    exec_result = {"status": "success", "value": 42}
    raw = ai.truncate_tool_result_json(exec_result)
    assert json.loads(raw) == exec_result


def test_oversized_list_field_is_shrunk_with_note():
    ai = ConcreteAI(model_tier='standard')  # 12000 char budget
    plots = [{"crop": f"crop_{i}", "variety": f"variety_{i}", "area_m2": i * 1.5}
             for i in range(200)]
    exec_result = {"count": len(plots), "plantings": plots}

    raw_unbounded = json.dumps(exec_result, ensure_ascii=False)
    assert len(raw_unbounded) > ai.TOOL_RESULT_MAX_CHARS['standard'], \
        "fixture must actually exceed the budget for this test to mean anything"

    shrunk_raw = ai.truncate_tool_result_json(exec_result)
    parsed = json.loads(shrunk_raw)  # must still be valid JSON

    assert len(parsed["plantings"]) < len(plots)
    assert len(parsed["plantings"]) == max(1, len(plots) // 4)
    assert "_plantings_truncated" in parsed
    assert str(len(plots)) in parsed["_plantings_truncated"]
    assert len(shrunk_raw) <= ai.TOOL_RESULT_MAX_CHARS['standard']


def test_largest_list_key_is_shrunk_first():
    # standard budget (12000 chars) — shrinking "big" alone is enough to fit,
    # so "small" should be left untouched, proving the largest-first ordering.
    ai = ConcreteAI(model_tier='standard')
    small_list = [{"id": i} for i in range(5)]
    big_list = [{"id": i, "note": "x" * 50} for i in range(200)]
    exec_result = {"small": small_list, "big": big_list}

    shrunk_raw = ai.truncate_tool_result_json(exec_result)
    parsed = json.loads(shrunk_raw)

    assert "_big_truncated" in parsed
    assert len(parsed["big"]) < len(big_list)
    assert "_small_truncated" not in parsed
    assert len(parsed["small"]) == len(small_list)


def test_still_oversized_after_shrink_hard_truncates_without_crashing():
    ai = ConcreteAI(model_tier='lightweight')  # 4000 char budget
    # Individual items are themselves huge, so shrinking the list to 1/4
    # still doesn't fit — must fall through to the hard-truncation path.
    huge_items = [{"blob": "x" * 5000} for _ in range(10)]
    exec_result = {"rows": huge_items}

    result = ai.truncate_tool_result_json(exec_result)
    assert isinstance(result, str)
    assert len(result) <= ai.TOOL_RESULT_MAX_CHARS['lightweight'] + 200
    assert "TRUNCATED" in result


def test_non_dict_exec_result_does_not_crash():
    ai = ConcreteAI(model_tier='lightweight')
    exec_result = ["x" * 1000 for _ in range(20)]  # top-level list, not dict
    result = ai.truncate_tool_result_json(exec_result)
    assert isinstance(result, str)
    assert len(result) <= ai.TOOL_RESULT_MAX_CHARS['lightweight'] + 200


def test_tier_budgets_are_distinct_and_ordered():
    assert (AbstractAI.TOOL_RESULT_MAX_CHARS['lightweight']
            < AbstractAI.TOOL_RESULT_MAX_CHARS['standard']
            < AbstractAI.TOOL_RESULT_MAX_CHARS['heavy'])


def test_unknown_tier_falls_back_to_standard_budget():
    ai = ConcreteAI(model_tier='some_future_tier')
    plots = [{"crop": f"crop_{i}"} for i in range(2000)]
    exec_result = {"plantings": plots}
    shrunk_raw = ai.truncate_tool_result_json(exec_result)
    assert len(shrunk_raw) <= AbstractAI.TOOL_RESULT_MAX_CHARS['standard']


def test_anthropic_native_loop_calls_the_shared_truncator():
    """Guards against reverting to a bare json.dumps(exec_result) at the
    tool_result_str assignment inside AnthropicAI's fc_turn loop, which would
    silently remove the cap this module exists to enforce."""
    from aot.ai.agents import anthropic as anthropic_module
    source = inspect.getsource(anthropic_module.AnthropicAI.run_reasoning)
    assert "self.truncate_tool_result_json(exec_result)" in source
    assert "json.dumps(exec_result, ensure_ascii=False, default=str)" not in source


def test_gemini_native_loop_calls_the_shared_truncator():
    from aot.ai.agents import gemini as gemini_module
    source = inspect.getsource(gemini_module.GeminiAI.run_reasoning)
    assert "self.truncate_tool_result_json(exec_result)" in source
    assert "json.dumps(exec_result, ensure_ascii=False, default=str)" not in source
