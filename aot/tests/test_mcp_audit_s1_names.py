# coding=utf-8
"""2026-11-03 MCP 점검 S1 — 도메인 표면이 없는 이름을 가리키던 것(A7·A8·A10).

  A7 help 는 op 를 고르는 도구가 아니다: 스키마에 target 하나, 모르는 말에는 후보를 준다.
  A8 도메인 스키마·서버 안내문·응답 되돌림이 옛 도구 이름 대신 이 표면의 operation 이름을 쓴다.
  A10 find.lookup_sources 의 Open-Meteo 소개에 낡은 '기상청 전용' 문장이 없다.
"""
import unittest
from unittest import mock

from aot.tools import tool_execution as te
from aot.tools.domain import dispatch, surface
from aot.tools.domain.registry_data import OPS


class HelpTest(unittest.TestCase):

    def _entry(self):
        ent = surface.entries(OPS, lambda n: True, set())
        return next(e for e in ent if e['name'] == 'help')

    def test_help_schema_is_one_optional_target_without_a_fake_op(self):
        schema = self._entry()['inputSchema']
        self.assertEqual({'target'}, set(schema['properties']))
        self.assertEqual([], schema['required'])
        self.assertNotIn('op:', self._entry()['description'])

    def test_old_tool_name_points_at_its_operation_first(self):
        ops = dispatch.help_card('get_plot')['operations']
        self.assertEqual('detail.plot', ops[0])
        self.assertEqual('find.widget_types', dispatch.help_card('list_widget_types')['operations'][0])

    def test_wrong_op_of_a_known_tool_lists_that_tools_ops(self):
        ops = dispatch.help_card('weather.current')['operations']
        self.assertIn('weather.now', ops[:3])

    def test_nothing_matching_still_lists_operations_not_an_empty_answer(self):
        card = dispatch.help_card('qqqq')
        self.assertTrue(card['operations'])
        self.assertIn('help(target=', card['next'])


class OldNamesTest(unittest.TestCase):

    GONE = ('get_function_detail', 'get_plot', 'list_widget_types', 'get_screen', 'resolve_target')

    def test_registry_texts_do_not_use_names_this_surface_lacks(self):
        for o in OPS:
            texts = [o.use] + list(o.extra_args.values()) + list(o.renamed.values())
            for text in texts:
                for old in self.GONE:
                    self.assertNotRegex(text or '', r'\b%s\b' % old, '%s.%s' % (o.tool, o.op))

    def test_help_renames_names_inside_the_inner_argument_docs(self):
        card = dispatch.help_card('record.note_add')
        doc = card['other_args']['target_name']['description']
        self.assertNotIn('resolve_target', doc)
        self.assertIn('find.resolve', doc)

    def test_remaining_plots_point_at_the_listing_with_offset_and_query(self):
        names = dispatch._inner_to_op()
        self.assertEqual('find.plots', names['list_plots'])
        self.assertEqual('measure.latest', names['get_zone_sensor_summary'])

    def test_every_renamed_hint_points_at_an_operation_that_exists(self):
        # 2026-11-07: 개요의 `_more` 가 이미 없어진 measure.summary 를 가리켰다 — AI 가 없는 호출을 시도한다.
        real = {'%s.%s' % (o.tool, o.op) for o in OPS}
        for inner, op in dispatch._inner_to_op().items():
            self.assertIn(op, real, inner)

    def test_time_paragraph_names_the_domain_op_when_the_domain_surface_is_on(self):
        with mock.patch.object(te, 'domain_surface_enabled', return_value=True):
            self.assertIn('weather.local_time', te._server_instructions())
            self.assertNotIn('get_local_time', te._server_instructions())
        with mock.patch.object(te, 'domain_surface_enabled', return_value=False):
            self.assertIn('get_local_time', te._server_instructions())


class LookupSourcesTest(unittest.TestCase):

    def test_openmeteo_blurb_has_no_stale_kma_only_claim(self):
        from aot.ai.services import data_source_query_service as svc
        text = svc._PRESET_ANSWERS['ext_openmeteo']
        self.assertNotIn('기상청 전용', text)
        self.assertNotIn('get_weather_forecast', text)


if __name__ == '__main__':
    unittest.main()
