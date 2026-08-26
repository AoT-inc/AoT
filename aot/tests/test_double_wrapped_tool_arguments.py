# coding=utf-8
"""인자가 `arguments` 안에 한 겹 더 들어와 도구가 빈손으로 불리던 것.

실사용(2026-08-26). 사용자가 "설원6이 뭐야" 라고 물었고, 모델은 **올바른
구획 id 로 get_plot 을 불렀다**. 그런데 실행 로그는 이랬다:

    Params: {'arguments': {'arguments': {'plot_id': '22501c0f-…'}}, ...}
    [VirtualToolResolver] get_plot returned error: plot_id is required

사용자에게는 "정보를 가져올 수 없습니다" 만 보였다.

왜 두 겹인가. 도구 설명이 `params.arguments: {...}` 라고 알려 주므로 모델이
그 모양으로 보내는데, 엔진 어댑터가 그것을 다시 `{'arguments': raw_args}` 로
감싼다(gemini.py, anthropic.py 둘 다).

왜 조용했나. 한 겹만 벗기면 `handler(arguments={...})` 가 되고, 핸들러
대부분이 `**extra` 를 받으므로 **예외 없이** 통과하면서 정작 필수 인자는
비어 있다. 그래서 "필수 인자가 없다" 는 도구 자신의 오류로만 나타났다.
"""
import json

import pytest

from aot.config import ProdConfig


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'wrap.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _run(params):
    from aot.ai.services.resolvers.virtual_tool_resolver import VirtualToolResolver
    return VirtualToolResolver().execute(None, 'system_internal', params, None)


class TestDoubleWrappedArguments:
    def test_a_double_wrapped_call_reaches_the_handler(self, app):
        """이것이 실사용에서 조용히 실패하던 모양 그대로다."""
        with app.app_context():
            out = _run({'tool_name': 'list_plots',
                        'arguments': {'arguments': {}}})
            assert 'Unknown virtual tool' not in json.dumps(out, ensure_ascii=False)
            assert out.get('status') != 'error' or 'required' not in json.dumps(
                out, ensure_ascii=False), out

    def test_a_required_argument_is_not_lost(self, app):
        """빈 인자면 통과했는지 알 수 없다 — 필수 인자가 실제로 닿는지 본다."""
        with app.app_context():
            wrapped = _run({'tool_name': 'get_plot',
                            'arguments': {'arguments': {'plot_id': 'no-such-plot'}}})
            msg = json.dumps(wrapped, ensure_ascii=False)
            # 존재하지 않는 id 라 '못 찾음' 은 정상이다. 다만 **'plot_id is
            # required' 여서는 안 된다** — 그것이 인자를 잃었다는 증거다.
            assert 'plot_id is required' not in msg, msg

    def test_a_normal_call_is_unchanged(self, app):
        with app.app_context():
            out = _run({'tool_name': 'get_plot', 'arguments': {'plot_id': 'no-such-plot'}})
            assert 'plot_id is required' not in json.dumps(out, ensure_ascii=False)

    def test_only_a_lone_arguments_key_is_unwrapped(self, app):
        """`arguments` 옆에 다른 인자가 있으면 그것은 진짜 인자 이름이다 —
        벗기면 나머지를 잃는다."""
        from aot.ai.services.resolvers import virtual_tool_resolver as vtr
        import inspect

        body = inspect.getsource(vtr.VirtualToolResolver.execute)
        assert 'len(arguments) == 1' in body

    def test_a_handler_that_really_takes_arguments_is_left_alone(self, app):
        """use_tool(tool_name, arguments) 같은 도구가 생기면 벗기면 안 된다.
        서명을 보고 판단하는지 고정한다."""
        from aot.ai.services.resolvers import virtual_tool_resolver as vtr
        import inspect

        body = inspect.getsource(vtr.VirtualToolResolver.execute)
        assert 'inspect.signature(handler).parameters' in body


class TestTheEngineAdaptersAreTheSource:
    def test_the_wrapping_pattern_still_exists(self):
        """이 검사는 원인을 기록해 둔다 — 어댑터가 감싸는 한 리졸버의 해제가
        필요하다. 어댑터를 고쳐 이 검사가 깨지면, 해제 쪽도 함께 재검토할 것."""
        import inspect

        from aot.ai.agents import gemini

        assert "'params': {'arguments': raw_args}" in inspect.getsource(gemini)


class TestActionEnvelopeUsedAsAToolName:
    """모델이 **액션 봉투를 도구 이름 자리에** 넣던 것.

    실측(2026-08-26), "구획이 설원6에 얼마나 적합한 환경을 가지고 있지?" 에서:

        tool=mcp_tool_call
        args={'tool_name': 'get_plot', 'arguments': {'plot_id': …}, 'target_id': …}
        → [resolve_action] Unknown tool: 'mcp_tool_call'
        → 사용자에게는 "도구 실행에 문제가 발생했습니다"

    도구 카탈로그가 액션 종류(mcp_tool_call / virtual_tool_call)와 도구 이름을
    둘 다 보여 주므로 앞엣것을 도구로 착각한 것이다. 진짜 호출은 그 안에
    온전히 들어 있어 버릴 이유가 없다.
    """

    def _norm(self, action):
        from aot.ai.ai_routing_service import AIRoutingService
        ok, msg = AIRoutingService._validate_and_normalize_action(action)
        return ok, msg, action

    def test_the_real_tool_is_recovered_from_the_envelope(self, app):
        with app.app_context():
            ok, msg, a = self._norm({
                'tool_name': 'mcp_tool_call',
                'params': {'arguments': {'tool_name': 'get_plot',
                                         'arguments': {'plot_id': 'p1'},
                                         'target_id': 'srv-1'}}})
            assert ok, msg
            assert a['params']['tool_name'] == 'get_plot'

    def test_the_inner_arguments_survive(self, app):
        """봉투만 벗기고 인자를 잃으면 같은 실패가 이름만 바꿔 이어진다."""
        with app.app_context():
            _, _, a = self._norm({
                'tool_name': 'mcp_tool_call',
                'params': {'arguments': {'tool_name': 'get_plot',
                                         'arguments': {'plot_id': 'p1'}}}})
            assert a['params']['arguments'] == {'plot_id': 'p1'}

    def test_a_virtual_tool_still_routes_internally(self, app):
        """봉투가 mcp 라고 말해도, 내부 도구면 내부로 가야 한다 —
        기존 오분류 교정과 맞물리는지 본다."""
        with app.app_context():
            _, _, a = self._norm({
                'tool_name': 'mcp_tool_call',
                'params': {'arguments': {'tool_name': 'get_plot',
                                         'arguments': {'plot_id': 'p1'}}}})
            assert a['action_type'] == 'virtual_tool_call'

    def test_a_normal_action_is_untouched(self, app):
        with app.app_context():
            ok, msg, a = self._norm({'tool_name': 'get_plot',
                                     'params': {'arguments': {'plot_id': 'p1'}}})
            assert ok, msg
            assert a['params']['tool_name'] == 'get_plot'
            assert a['params']['arguments'] == {'plot_id': 'p1'}

    def test_an_envelope_without_an_inner_tool_is_not_invented(self, app):
        """안에 도구 이름이 없으면 벗길 것이 없다 — 지어내지 않고 실패한다."""
        with app.app_context():
            ok, _, _ = self._norm({'tool_name': 'mcp_tool_call',
                                   'params': {'arguments': {'plot_id': 'p1'}}})
            assert not ok
