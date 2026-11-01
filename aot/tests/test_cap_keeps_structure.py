# coding=utf-8
"""응답 상한에 걸려도 트리·요약이 "이름만 남은 목록" 이 되지 않는다.

캡은 가장 무거운 열부터 **모든 항목에서** 뺀다. 공간 트리에서 그것은
children, 구역 센서 요약에서는 sensors 였고, 빠지면 값이 하나도 없는 응답이
나갔다(2026-10-09 실측 — 장소 58개 평평한 목록, 구역 이름 10개). 두 도구가
`keep_last: [('*', 열)]` 로 그 열을 지키면 캡은 뒤쪽 항목부터 잘라, 남은
앞쪽 항목은 구조와 값이 그대로다.
"""
import unittest

from aot.tools.tool_execution import CAP_PRIORITY_KEY, _cap_result


def _tree(n_roots=30, n_kids=12):
    return {"hierarchy": [
        {"name": "site-%d" % i, "type": "site", "unique_id": "s%d-xxxxxxxxxxxxxxxx" % i,
         "children": [{"name": "zone-%d-%d" % (i, j), "type": "zone",
                       "unique_id": "z%d-%d-xxxxxxxxxxxxxxxxxxxxxxxx" % (i, j),
                       "children": [{"name": "dev", "type": "aot_device",
                                     "unique_id": "d%d-%d-yyyyyyyyyyyyyyyyyyyy" % (i, j)}]}
                      for j in range(n_kids)]}
        for i in range(n_roots)]}


def _zones(n_zones=20, n_devs=10):
    return {"zones": [
        {"zone_name": "z%d" % i, "sensors": [
            {"device_name": "dev-%d-%d" % (i, k), "device_id": "x" * 36,
             "channels": [{"channel": c, "measurement": "temperature", "unit": "C",
                           "last_value": 20.5, "min": 1.0, "max": 30.0, "avg": 15.0}
                          for c in range(3)]}
            for k in range(n_devs)]}
        for i in range(n_zones)]}


class TestCapKeepsStructure(unittest.TestCase):

    def test_without_the_hint_children_are_stripped_everywhere(self):
        """고치기 전의 모양 — 대비를 위해 남긴다."""
        out = _cap_result(_tree(), 'get_spatial_tree', max_tokens=3000)
        self.assertTrue(all('children' not in r for r in out['hierarchy']))

    def test_tree_keeps_children_and_cuts_roots_from_the_end(self):
        res = _tree()
        res[CAP_PRIORITY_KEY] = {'keep_last': [['*', 'children']]}
        out = _cap_result(res, 'get_spatial_tree', max_tokens=3000)
        roots = out['hierarchy']
        self.assertLess(len(roots), 30)
        self.assertEqual(roots[0]['name'], 'site-0')
        for r in roots:
            self.assertEqual(len(r['children']), 12)
            self.assertTrue(all('children' in z for z in r['children']))
        self.assertIn('hierarchy_truncated', out)

    def test_zone_summary_keeps_values_and_cuts_zones_from_the_end(self):
        res = _zones()
        res[CAP_PRIORITY_KEY] = {'keep_last': [['*', 'sensors'], ['*', 'channels']]}
        out = _cap_result(res, 'get_zone_sensor_summary', max_tokens=3000)
        self.assertLess(len(out['zones']), 20)
        for z in out['zones']:
            self.assertTrue(z['sensors'])
            self.assertTrue(all(d['channels'] for d in z['sensors']))
        self.assertIn('zones_truncated', out)

    def test_the_hint_is_never_left_in_the_reply(self):
        res = _zones(2, 2)
        res[CAP_PRIORITY_KEY] = {'keep_last': [['*', 'sensors']]}
        out = _cap_result(res, 'get_zone_sensor_summary', max_tokens=15000)
        self.assertNotIn(CAP_PRIORITY_KEY, out)


class TestToolsDeclareTheHint(unittest.TestCase):

    def test_both_tools_declare_keep_last(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        space = open(os.path.join(root, 'tools', 'data_tools', 'space.py'),
                     encoding='utf-8').read()
        meas = open(os.path.join(root, 'tools', 'data_tools', 'measurement.py'),
                    encoding='utf-8').read()
        self.assertIn("'keep_last': [['*', 'children']]", space)
        self.assertIn("'keep_last': [['*', 'groups'], ['*', 'sensors'],", meas)


if __name__ == '__main__':
    unittest.main()
