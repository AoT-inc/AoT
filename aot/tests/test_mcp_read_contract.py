# coding=utf-8
"""읽기 도구의 응답이 스키마가 약속하지 않은 일을 시키지 않는다.

배경(2026-10-08): 새로 연결한(메모리 없는) Sonnet 이 공간·장치 조회에서
"도구가 설명과 다르다" 를 반복 보고했다. 그중 하나가 `list_plots` 였다 —
잘린 응답이 "limit 을 올려 다시 부르라" 고 안내하는데 스키마에 `limit` 이
없었다(26-09-29 에 토큰 예산 때문에 일부러 숨겼다). 모델은 스키마에 없는
인자를 쓰지 않고, 안내와 스키마가 어긋난다고 보고한 뒤 나머지를 보지 못했다.

규칙: 응답 문구가 인자 이름을 가리키면 그 인자는 tools/list 에 있어야 한다.
"""
import inspect
import re
import unittest


#: 잘린 응답이 "limit 을 올리라" 고 말하는 문구.
_LIMIT_HINT = re.compile(r'higher limit|raise limit', re.I)


class TestTruncationHintArgsAreAdvertised(unittest.TestCase):

    def test_truncation_hint_args_are_advertised(self):
        from aot.tools import tool_registry as reg
        tool_map = reg.build_tool_map()
        missing, checked = [], 0
        for p in reg._MCP_TOOL_PAYLOADS:
            name = p['tool_name']
            handler = tool_map.get(name)
            if handler is None:
                continue
            try:
                src = inspect.getsource(handler)
            except (OSError, TypeError):
                continue
            if not _LIMIT_HINT.search(src):
                continue
            checked += 1
            props = (p.get('input_schema') or {}).get('properties') or {}
            if 'limit' not in props:
                missing.append(name)
        # 이 검사가 아무것도 안 보는 상태로 조용히 통과하지 않게 한다.
        # (2026-11-07: search_schedule 의 잘림 안내가 "limit 을 올려라" 에서 "offset=N 으로 이어 받아라" 로 바뀌어 3 → 2.)
        self.assertGreaterEqual(checked, 2, '안내 문구를 가진 도구를 못 찾았다')
        self.assertEqual(missing, [],
                         '응답이 limit 을 올리라고 안내하는데 스키마에 limit 이 '
                         '없다: %s' % missing)


class TestSpatialTreeCompaction(unittest.TestCase):
    """depth·filter_type 으로 펼친 트리는 빈 값과 properties 껍데기를 뺀다
    — depth=0 이 응답 상한을 넘어 매번 잘리던 것(20,493 추정 토큰)."""

    def test_compact_drops_nulls_and_flattens_properties(self):
        from aot.tools.data_tools.space import SpaceToolsMixin as S
        tree = [{
            'name': '3포장', 'type': 'site', 'unique_id': 's1',
            'device_id': None, 'properties': {'area': 31446.4},
            'children': [{
                'name': 'v331', 'type': 'aot_device', 'unique_id': 'd1',
                'device_id': 'dev-1',
                'properties': {'device_type': 'output'}, 'children': [],
            }],
        }]
        out = S._compact_nodes(tree)
        site = out[0]
        self.assertNotIn('device_id', site)
        self.assertNotIn('properties', site)
        self.assertEqual(site['area_m2'], 31446)
        dev = site['children'][0]
        self.assertEqual(dev['device_type'], 'output')
        # 빈 children 은 싣지 않는다 — 잘린 것이 아니라 없는 것이다.
        self.assertNotIn('children', dev)
        # 장치 노드는 ID 를 하나만 싣는다 — 실제 장치 ID 다(마커 번호 아님).
        self.assertEqual((dev['name'], dev['type'], dev['unique_id']),
                         ('v331', 'aot_device', 'dev-1'))
        self.assertNotIn('device_id', dev)

    def test_place_nodes_drop_their_internal_device_id(self):
        """곳 노드의 device_id 는 장치가 아니라 도형 내부 번호다(2026-10-09:
        depth=0 이 이것과 장치 마커 번호 때문에 상한을 넘어 계층이 사라졌다)."""
        from aot.tools.data_tools.space import SpaceToolsMixin as S
        out = S._compact_nodes([{'name': '1포장', 'type': 'site',
                                 'unique_id': 's1', 'device_id': '4f67-6a3a'}])
        self.assertEqual(out[0], {'name': '1포장', 'type': 'site', 'unique_id': 's1'})

    def test_use_name_sits_right_after_the_name(self):
        """끝에 붙이면 긴 children 뒤로 밀려 외부 모델이 "없다" 고 읽었다."""
        from aot.tools.data_tools.space import SpaceToolsMixin as S
        n = {'name': '1포장', 'type': 'site', 'unique_id': 's1',
             'children': [{'name': '1-%d' % i} for i in range(5)]}
        S._put_after_name(n, 'use_name', '김제 1포장')
        self.assertEqual(list(n)[:2], ['name', 'use_name'])
        self.assertEqual(len(n['children']), 5)



class TestSpatialTreeOneLinePerDevice(unittest.TestCase):
    """트리는 지도 도형을 내보내, 마커와 영역이 둘 다 그려진 장치가 두 줄·두 번
    세어졌고 이름도 도형의 것이었다(2026-10-09: 3-2 가 12, 실제 8 — 같은
    질문에 search_devices 와 다른 답)."""

    def _tree(self):
        return [{'name': '3-2', 'type': 'zone', 'unique_id': 'z', 'device_id': None,
                 'children': [
                     {'name': 'v331', 'type': 'aot_device', 'unique_id': 'm1',
                      'device_id': 'dev-1', 'children': []},
                     {'name': 'Device 526', 'type': 'device', 'unique_id': 'a1',
                      'device_id': 'dev-1', 'children': []},
                     {'name': 'SIM 暖房機 1', 'type': 'aot_device', 'unique_id': 'm2',
                      'device_id': 'dev-2', 'children': []},
                     {'name': '빈 영역', 'type': 'device', 'unique_id': 'a2',
                      'device_id': None, 'children': []}]}]

    def _merged(self):
        from unittest import mock
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        names = {'dev-1': 'v331', 'dev-2': 'イチゴ-暖房機 1'}
        with mock.patch.object(S, '_device_names',
                               classmethod(lambda cls, ids: names)):
            tree = self._tree()
            out = S._merge_device_nodes(tree)
        return S, tree, out

    def test_one_line_per_device_with_its_real_name(self):
        S, _, out = self._merged()
        kids = out[0]['children']
        self.assertEqual([k['name'] for k in kids],
                         ['v331', 'イチゴ-暖房機 1', '빈 영역'])

    def test_the_place_count_is_devices_not_shapes(self):
        S, _, out = self._merged()
        self.assertEqual(S._fold_devices(out)[0]['devices'], 3)

    def test_the_source_tree_is_not_mutated(self):
        """공급자가 캐시된 트리를 줄 수 있다 — 제자리에서 고치면 다음 호출이 받는다."""
        S, tree, _ = self._merged()
        self.assertEqual(len(tree[0]['children']), 4)
        self.assertEqual(tree[0]['children'][2]['name'], 'SIM 暖房機 1')


class TestZoneSummaryNamesEveryDeviceKind(unittest.TestCase):
    """구역 센서 요약이 이름을 입력에서만 찾아, 장소에 매인 밸브(출력)가
    이름 대신 ID 로 나갔다(2026-10-09)."""

    def test_names_come_from_the_shared_lookup(self):
        import os
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'tools', 'data_tools',
            'measurement.py'), encoding='utf-8').read()
        self.assertIn('names = cls._device_names(all_ids)', src)

    def test_the_shared_lookup_covers_outputs(self):
        import inspect
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        body = inspect.getsource(S._device_names)
        for model in ('Input', 'Output', 'Function', 'CustomController'):
            self.assertIn(model, body)


class TestIdsAgreeAcrossTools(unittest.TestCase):
    """같은 것이 도구·보기마다 다른 ID 로 나와 대조할 수 없었다(2026-10-09)."""

    def test_a_root_device_node_carries_the_device_id_in_the_default_view(self):
        from aot.tools.data_tools.space import SpaceToolsMixin as S
        out = S._fold_devices([
            {'name': 'OpenWeather', 'type': 'aot_device', 'unique_id': 'marker-1',
             'device_id': 'dev-1', 'children': []},
            {'name': '3포장', 'type': 'site', 'unique_id': 'site-1', 'device_id': 'x',
             'children': [{'name': 'v1', 'type': 'aot_device', 'unique_id': 'm2',
                           'device_id': 'dev-2', 'children': []}]}])
        self.assertEqual(out[0]['unique_id'], 'dev-1')
        self.assertEqual(out[1]['unique_id'], 'site-1')     # 장소는 그대로
        self.assertEqual(out[1]['devices'], 1)

    def test_control_state_carries_both_facility_ids(self):
        import os
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'tools', 'data_tools', 'device.py'),
            encoding='utf-8').read()
        self.assertIn('"facility_place_id": fac_shape.get(fid)', src)
        self.assertIn('cls._resolve_facility(facility_id)', src)


class TestForecastIsMarked(unittest.TestCase):
    """Open-Meteo 예보가 구역 센서 목록에 실측처럼 섞였다(2026-10-09)."""

    def test_the_driver_declares_it_and_the_parser_keeps_it(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        drv = open(os.path.join(root, 'inputs', 'open_meteo_weather.py'),
                   encoding='utf-8').read()
        self.assertIn("'data_origin': 'model'", drv)
        par = open(os.path.join(root, 'utils', 'inputs.py'), encoding='utf-8').read()
        self.assertIn("dict_has_value(dict_inputs, input_custom, 'data_origin')", par)

    def test_tools_mark_model_values(self):
        import os
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'tools', 'data_tools', 'measurement.py'),
            encoding='utf-8').read()
        self.assertIn('dev["data_origin"] = "model"', src)
        self.assertIn("out['weather_device']['data_origin'] = 'model'", src)

if __name__ == '__main__':
    unittest.main()
