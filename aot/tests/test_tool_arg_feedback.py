# coding=utf-8
"""도구가 **알 수 없는 인자를 조용히 삼키지 않는가** — 회귀.

`aot_data_tool_service` 의 도구 함수 대부분이 `**extra` 를 단다. 근거는 있다 —
외부 AI 는 잉여 인자를 흔히 실어 보내고, `**extra` 가 없으면 그 한 번의 잉여
인자로 `TypeError` 가 나 도구가 통째로 못 쓰이게 된다.

그런데 그 방벽은 **이름을 틀린 경우까지 함께 삼킨다.** 2026-08-23 koat 실측:
`get_zone_sensor_summary(zone_ids=…)` 를 `zone_id=…` 로 9회 불렀고, 9회 모두
필터가 사라진 **전체 스캔**(54,129자)이 정상 응답으로 돌아왔다. 겉보기가
정상이라 "서버가 필터를 무시한다" 로 오진하는 데 오래 걸렸다.

`_dispatch_virtual_tool` 에는 이미 `_ignored_arguments` 로 알려 주는 장치가
있었지만 **`**kwargs` 가 없는 핸들러에만** 걸렸다 — 즉 문제가 실제로 생기는
쪽(`**extra` 를 단 74개)에서는 정확히 건너뛰어졌다.

여기서 고정하는 것은 둘이다:
  1) `**extra` 를 받기만 하고 안 쓰는 핸들러에서도 잉여 키를 알려 준다.
  2) `extra` 를 **본론으로 쓰는** 핸들러(`create_input`·`modify_plot` 등 25개)는
     제외한다 — 거기서는 잉여 키가 오류가 아니다. 이름으로는 못 가른다
     (쓰는 쪽도 안 쓰는 쪽도 똑같이 `extra` 다).

DB·데몬·앱 컨텍스트를 쓰지 않는다.
"""
import unittest

from aot.ai.services import tool_execution
from aot.ai.services.tool_execution import (
    _discarded_kwarg_sink, _dispatch_virtual_tool)


class TestKwargSinkDetection(unittest.TestCase):

    def test_a_handler_that_ignores_extra_is_detected(self):
        def handler(a=None, **extra):
            return {'status': 'success', 'a': a}
        self.assertEqual(_discarded_kwarg_sink(handler), 'extra')

    def test_a_handler_that_reads_extra_is_excluded(self):
        def handler(a=None, **extra):
            return {'status': 'success', 'b': extra.get('b')}
        self.assertIsNone(
            _discarded_kwarg_sink(handler),
            'extra 를 본론으로 쓰는 핸들러에 경고를 붙이면 정상 호출이 오류처럼 보인다')

    def test_a_handler_that_forwards_extra_is_excluded(self):
        def handler(a=None, **extra):
            return dict(a=a, **extra)
        self.assertIsNone(_discarded_kwarg_sink(handler))

    def test_a_handler_without_a_kwarg_sink_has_none(self):
        def handler(a=None):
            return a
        self.assertIsNone(_discarded_kwarg_sink(handler))

    def test_real_tools_split_the_way_the_source_says(self):
        """실제 도구로도 갈리는지 — 합성 함수만으로는 계약이 안 고정된다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        # 잉여 키를 버리는 조회 도구 — 오타가 조용한 전체 스캔이 되는 쪽.
        for name in ('get_zone_sensor_summary', 'get_plot', 'list_plots'):
            self.assertEqual(
                _discarded_kwarg_sink(getattr(AoTDataToolService, name)), 'extra',
                '%s 의 잉여 인자가 아무 말 없이 사라진다' % name)

        # 잉여 키를 **본론으로** 받는 도구 — 여기에 경고가 붙으면 안 된다.
        for name in ('create_input', 'modify_plot', 'create_note',
                     'search_notes_tool', 'set_device_location'):
            self.assertIsNone(
                _discarded_kwarg_sink(getattr(AoTDataToolService, name)),
                '%s 는 extra 를 실제로 쓴다 — 경고 대상이 아니다' % name)


class TestDispatchReportsIgnoredArguments(unittest.TestCase):
    """`_dispatch_virtual_tool` 이 실제로 응답에 실어 주는가."""

    def _dispatch(self, handler, arguments, tool_name='fake_tool'):
        from aot.ai.services import tool_registry

        original = tool_registry.build_tool_map
        tool_registry.build_tool_map = lambda: {tool_name: handler}
        try:
            return _dispatch_virtual_tool(tool_name, arguments)
        finally:
            tool_registry.build_tool_map = original

    def test_unknown_key_is_reported_even_when_extra_absorbs_it(self):
        def handler(zone_ids=None, **extra):
            return {'status': 'success', 'zone_ids': zone_ids}

        out = self._dispatch(handler, {'zone_id': 'abc'})
        self.assertEqual(out['status'], 'success')
        self.assertEqual(out['_ignored_arguments'], ['zone_id'],
                         '오타 하나가 필터를 없애는데 응답이 아무 말도 안 한다')
        self.assertIn('zone_id', out['_ignored_note'])

    def test_a_correct_call_says_nothing(self):
        def handler(zone_ids=None, **extra):
            return {'status': 'success', 'zone_ids': zone_ids}

        out = self._dispatch(handler, {'zone_ids': ['a']})
        self.assertNotIn('_ignored_arguments', out,
                         '정상 호출에 경고가 붙으면 경고를 아무도 안 읽는다')

    def test_extra_is_still_passed_through(self):
        """extra 를 통째로 다른 곳에 넘기는 핸들러는 '쓰는' 쪽이라 경고가 없다.

        `seen.update(extra)` 는 특정 키를 읽지는 않지만 `extra` 를 이름으로
        참조한다 — `_discarded_kwarg_sink` 의 AST 판정은 참조 여부만 보므로
        (TestKwargSinkDetection.test_a_handler_that_forwards_extra_is_excluded
        와 같은 판정), 이것도 '쓰는' 쪽으로 갈린다. 그래도 값은 그대로
        핸들러에 닿는다 — 경고가 없다고 데이터가 사라진 것은 아니다.
        """
        seen = {}

        def handler(a=None, **extra):
            seen.update(extra)
            return {'status': 'success'}

        out = self._dispatch(handler, {'a': 1, 'b': 2})
        self.assertEqual(seen, {'b': 2}, '값은 그대로 핸들러에 닿아야 한다')
        self.assertNotIn('_ignored_arguments', out,
                         'extra 를 통째로 포워딩하는 것도 쓰는 것이다 — 경고 대상이 아니다')

    def test_a_handler_that_reads_extra_gets_no_warning(self):
        def handler(a=None, **extra):
            return {'status': 'success', 'b': extra.get('b')}

        out = self._dispatch(handler, {'a': 1, 'b': 2})
        self.assertEqual(out['b'], 2)
        self.assertNotIn('_ignored_arguments', out)

    def test_handlers_without_a_sink_keep_the_old_behaviour(self):
        """`**kwargs` 가 없는 핸들러는 예전처럼 인자를 **버리고** 알려 준다.

        버리지 않으면 `TypeError` 로 도구가 통째로 못 쓰이게 된다.
        """
        def handler(a=None):
            return {'status': 'success', 'a': a}

        out = self._dispatch(handler, {'a': 1, 'b': 2})
        self.assertEqual(out['a'], 1)
        self.assertEqual(out['_ignored_arguments'], ['b'])


class TestTheWarningCannotBeMistakenForFailure(unittest.TestCase):
    """경고 문구가 예약 실패 판정에 걸리면 성공한 예약이 FAILED 로 남는다.

    `AISchedulerService._retval_indicates_not_executed` 는 응답 **전체를 문자열로
    훑어** 미실행 마커를 찾는다(도구별 status 어휘가 12종이라 그물이 필요하다).
    그래서 여기에 새로 넣는 문구는 그 마커와 겹쳐서는 안 된다.
    """

    def test_the_note_carries_no_not_executed_marker(self):
        from aot.ai.services.ai_scheduler_service import AISchedulerService

        def handler(a=None, **extra):
            return {'status': 'success'}

        from aot.ai.services import tool_registry
        original = tool_registry.build_tool_map
        tool_registry.build_tool_map = lambda: {'fake_tool': handler}
        try:
            out = _dispatch_virtual_tool('fake_tool', {'typo': 1})
        finally:
            tool_registry.build_tool_map = original

        self.assertIn('_ignored_note', out)
        self.assertIsNone(
            AISchedulerService._retval_indicates_not_executed(out),
            '경고 문구가 미실행 마커와 겹친다 — 성공한 예약이 FAILED 로 기록된다')


class TestTheSinkCacheDoesNotConfuseHandlers(unittest.TestCase):

    def test_two_handlers_are_judged_separately(self):
        def uses(a=None, **extra):
            return extra.get('x')

        def drops(a=None, **extra):
            return a

        # 캐시는 코드 객체 기준이다 — 이름이 같아도 섞이지 않아야 한다.
        self.assertIsNone(_discarded_kwarg_sink(uses))
        self.assertEqual(_discarded_kwarg_sink(drops), 'extra')
        self.assertIsNone(_discarded_kwarg_sink(uses))

    def test_a_handler_without_source_is_silent_not_noisy(self):
        """소스를 못 읽으면 근거 없는 경고를 내지 않는다."""
        handler = eval(compile('lambda a=None, **extra: a', '<nowhere>', 'eval'))
        tool_execution._KWARG_SINK_CACHE.pop(handler.__code__, None)
        self.assertIsNone(_discarded_kwarg_sink(handler))


if __name__ == '__main__':
    unittest.main()
