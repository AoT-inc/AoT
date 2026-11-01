# coding=utf-8
"""find 조회 도구의 쪽 나누기 인자 통일(2026-10-28 MCP 점검 D).

find.functions·devices·device_list 가 limit 을 거부하고, find.plots 는 응답이 권하는 offset 을
거부했다. 이제 네 곳이 같은 limit·offset 을 받고, 자르면 응답이 전체 수와 다음 offset 을 알린다.
"""
import unittest


def _service():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


class PageRowsTest(unittest.TestCase):

    def test_whole_list_when_no_limit_or_offset(self):
        rows, info = _service()._page_rows(list(range(5)))
        self.assertEqual(list(range(5)), rows)
        self.assertIsNone(info)

    def test_limit_and_offset_report_total_and_next_offset(self):
        rows, info = _service()._page_rows(list(range(10)), limit=3, offset=2)
        self.assertEqual([2, 3, 4], rows)
        self.assertEqual({'total': 10, 'shown': 3, 'offset': 2, 'next_offset': 5}, info)

    def test_last_page_has_no_next_offset(self):
        rows, info = _service()._page_rows(list(range(10)), limit=5, offset=8)
        self.assertEqual([8, 9], rows)
        self.assertNotIn('next_offset', info)

    def test_default_applies_only_when_limit_is_not_given(self):
        rows, info = _service()._page_rows(list(range(100)), default=40)
        self.assertEqual(40, len(rows))
        self.assertEqual(40, info['next_offset'])
        rows, _ = _service()._page_rows(list(range(100)), limit=70, default=40)
        self.assertEqual(70, len(rows))

    def test_bad_numbers_fall_back_to_the_default(self):
        rows, _ = _service()._page_rows(list(range(5)), limit='x', offset='y')
        self.assertEqual(list(range(5)), rows)


class FindOpsTakePagingArgsTest(unittest.TestCase):

    def _plan(self, args):
        from aot.tools.domain import dispatch
        return dispatch.plan('find', args)

    def test_functions_devices_device_list_accept_limit_and_offset(self):
        for args in ({'op': 'functions', 'limit': 3, 'offset': 1},
                     {'op': 'devices', 'query': 'x', 'limit': 2, 'offset': 4},
                     {'op': 'device_list', 'limit': 5, 'offset': 40}):
            v = self._plan(args)
            self.assertEqual('call', v[0], (args, v))
            self.assertEqual(args['limit'], v[2]['limit'])
            self.assertEqual(args['offset'], v[2]['offset'])

    def test_plots_offset_is_accepted_like_its_own_advice(self):
        v = self._plan({'op': 'plots', 'limit': 2, 'offset': 2})
        self.assertEqual('call', v[0], v)
        self.assertEqual({'limit': 2, 'offset': 2}, {k: v[2][k] for k in ('limit', 'offset')})


if __name__ == '__main__':
    unittest.main()
