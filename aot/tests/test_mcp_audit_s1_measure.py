# coding=utf-8
"""2026-11-03 MCP 점검 S1 — 측정 읽기의 설명과 오류 안내(A9·A13·A14).

  A9  measure.energy 는 기간으로 거르지 않는다 — 인자·기간 표시를 두지 않고, 응답에 장치 이름을 싣는다.
  A13 이름·종류·값이 없을 때의 오류가 다음 걸음을 알린다.
  A14 get_zone_sensor_summary 설명이 기본 응답(최신값 평균)과 맞는다.
"""
import unittest
from unittest import mock

from aot.tools.domain import dispatch
from aot.tools.domain.registry_data import OPS


def _op(tool, name):
    return next(o for o in OPS if o.tool == tool and o.op == name)


class EnergyTest(unittest.TestCase):

    def test_energy_op_takes_no_period_so_it_cannot_claim_to_have_read_one(self):
        o = _op('measure', 'energy')
        self.assertNotIn('period', o.args)
        self.assertEqual('', o.period_form)
        self.assertIn('no date filter', o.use)


class SummaryWordsTest(unittest.TestCase):

    def test_summary_does_not_promise_stats_it_does_not_return(self):
        self.assertNotIn('stats', _op('measure', 'latest').use)      # summary 는 latest 로 합쳐졌다(재설계 PR 3)
        from aot.tools import tool_registry as R
        text = next(t['description'] for t in R.virtual_tools()
                    if t['tool_name'] == 'get_zone_sensor_summary')
        self.assertIn('detail=true', text)


class NextStepTest(unittest.TestCase):

    def _plan(self, args, kind, found=True):
        got = ('ok', {'kind': kind, 'id': 'T', 'name': 'x', 'path': 'm > x'}) if found else \
            ('none', {'error': "Nothing named 'x' — no map, place, plot or device has that name."})
        with mock.patch.object(dispatch.targets, 'resolve', lambda ref, **kw: got), \
                mock.patch.object(dispatch, '_ancestors', lambda *a, **k: []), \
                mock.patch.object(dispatch, '_expand_places', lambda *a, **k: None):
            return dispatch.plan('measure', args, ops=OPS)

    def _body(self, verdict):
        import json
        self.assertEqual('refuse', verdict[0])
        return json.loads(verdict[1][0]['text'])

    def test_wrong_kind_says_where_to_find_the_right_one(self):
        body = self._body(self._plan({'op': 'cumulative', 'target': 'x'}, 'widget'))
        self.assertIn("find(op='functions')", body['next']['call'])

    def test_unknown_name_says_how_to_look_around(self):
        body = self._body(self._plan({'op': 'latest', 'target': 'x'}, 'zone', found=False))
        self.assertEqual('unknown_target', body['reason_code'])
        self.assertIn("find(op='tree')", body['next']['call'])

    def test_kind_lookup_without_a_known_kind_falls_back_to_resolve(self):
        self.assertIn('find(op=\'resolve\'', dispatch._kind_lookup(['widget']))

    def test_no_recent_reading_names_the_next_calls(self):
        from flask import Flask
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        row = mock.Mock(unique_id='d1')
        row.name = '토양온습도_2'
        with Flask('t').app_context(), \
                mock.patch.object(S, '_read_device', return_value=(row, 'input', None)), \
                mock.patch.object(S, 'get_sensor_detail',
                                  return_value={'message': "No data for device '토양온습도_2' in the last 1h."}):
            out = N._sensor_reading_one('d1')
        self.assertEqual('no_recent_data', out['reason_code'])
        self.assertIn('get_device_freshness', out['next']['call'])

    def test_water_estimate_without_a_run_time_says_what_to_pass(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S._water_estimate('p1', None, None, None, None)
        self.assertEqual('missing_argument', out['reason_code'])
        self.assertIn('duration_minutes', out['message'])


if __name__ == '__main__':
    unittest.main()
