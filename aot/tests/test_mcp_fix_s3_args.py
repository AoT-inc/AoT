# coding=utf-8
"""2026-11-03 MCP 수정 S3 #1 — 안쪽 도구의 안내문이 쓰는 인자 이름(`time_range`)이 이 표면에서도 통한다."""
import json
import unittest

from aot.tools.domain import dispatch, renames


class ArgNamesInHints(unittest.TestCase):

    def setUp(self):
        dispatch._INNER_TO_OP.clear()             # 다른 시험이 바꾼 명부로 채운 캐시를 쓰지 않는다
        self.addCleanup(dispatch._INNER_TO_OP.clear)

    def test_no_recent_data_next_uses_the_domain_names(self):
        body = {'status': 'error', 'reason_code': 'no_recent_data',
                'next': {'call': "get_sensor_detail with time_range='7d' shows its last readings; "
                                 "get_device_freshness lists sensors that went silent"}}
        dispatch._domain_hints(body)
        text = json.dumps(body)
        self.assertIn("measure.history with period='7d'", text)
        self.assertNotIn('time_range', text)

    def test_old_argument_names_are_accepted_on_history(self):
        _tool, args, renamed = renames.resolve_call(
            'measure', {'op': 'history', 'target': 'x', 'time_range': '7d'})
        self.assertEqual('7d', args['period'])
        self.assertNotIn('time_range', args)
        self.assertEqual({'time_range': 'period'}, renamed)

    def test_sensor_type_means_measurement(self):
        _tool, args, _r = renames.resolve_call(
            'measure', {'op': 'latest', 'target': 'x', 'sensor_type': 'humidity'})
        self.assertEqual('humidity', args['measurement'])


if __name__ == '__main__':
    unittest.main()
