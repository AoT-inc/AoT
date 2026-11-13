# coding=utf-8
"""합친 op(재설계 PR 3, 2026-11-03) — 옛 이름은 별칭이 받아 같은 안쪽 호출로 간다.

  measure.summary → measure.latest · overview.crops → find.plots · overview.active_functions → find.functions
  find.device_location → detail.device · find.distance → find.nearest · find.device_list → find.devices
  find.maps → find.tree · records.journal → records.journals · configure.input_activate / gis_input_activate → configure.activate
"""
import json
import unittest
from unittest import mock


def _plan(tool, args, kind=None):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, args)


def _call(tool, args, kind=None):
    v = _plan(tool, args, kind)
    assert v[0] == 'call', v
    return v[1], {k: x for k, x in v[2].items() if not k.startswith('_')}


class MergedOpsTest(unittest.TestCase):

    def test_summary_is_latest_without_a_target(self):
        inner, a = _call('measure', {'op': 'summary', 'measurement': 'temperature'})
        self.assertEqual('get_zone_sensor_summary', inner)
        self.assertIs(True, a['brief'])
        inner, b = _call('measure', {'op': 'latest', 'measurement': 'temperature'})
        self.assertEqual(a, b)

    def test_summary_with_a_zone_is_latest_with_a_zone(self):
        self.assertEqual(_call('measure', {'op': 'summary', 'target': 'z'}, 'zone'),
                         _call('measure', {'op': 'latest', 'target': 'z'}, 'zone'))

    def test_a_device_still_reads_one_sensor(self):
        inner, _a = _call('measure', {'op': 'latest', 'target': 's'}, 'input')
        self.assertEqual('get_sensor_reading', inner)

    def test_crops_is_find_plots_and_a_facility_reads_crop_status(self):
        inner, a = _call('overview', {'op': 'crops', 'target': 'f'}, 'facility')
        self.assertEqual('get_crop_status', inner)
        self.assertEqual('id-1', a['facility_id'])
        self.assertIs(False, a['detail'])
        self.assertEqual((inner, a), _call('find', {'op': 'plots', 'target': 'f'}, 'facility'))
        inner, _a = _call('overview', {'op': 'crops'})
        self.assertEqual('list_plots', inner)
        _i, a = _call('overview', {'op': 'crops', 'detail': True, 'limit': 5}, 'zone')
        self.assertIs(True, a['detail'])
        self.assertEqual(5, a['limit'])

    def test_crops_facility_name_becomes_the_target(self):
        from aot.tools.domain import renames
        tool, args, got = renames.resolve_call('overview', {'op': 'crops', 'facility_name': '육묘장3'})
        self.assertEqual(('find', 'plots', '육묘장3'), (tool, args['op'], args['target']))
        self.assertEqual({'op=crops': 'find.plots', 'facility_name': 'target'}, got)

    def test_active_functions_is_find_functions_only_active(self):
        inner, a = _call('overview', {'op': 'active_functions'})
        self.assertEqual('get_function_list', inner)
        self.assertIs(True, a['active_only'])
        _i, b = _call('find', {'op': 'functions', 'only_active': True})
        self.assertEqual(a, b)

    def test_device_location_is_the_location_field_of_the_device(self):
        inner, a = _call('find', {'op': 'device_location', 'target': 'd'}, 'output')
        self.assertEqual('get_device_detail', inner)
        self.assertEqual(['location'], a['fields'])
        self.assertEqual((inner, a), _call('detail', {'op': 'device', 'target': 'd', 'fields': ['location']}, 'output'))

    def test_distance_is_nearest_with_one_candidate(self):
        inner, a = _call('find', {'op': 'distance', 'target': 'office', 'target_b': 'barn'}, 'zone')
        self.assertEqual('nearest', inner)
        self.assertEqual(['barn'], a['candidates'])
        _i, b = _call('find', {'op': 'nearest', 'target': 'office', 'candidates': ['barn']}, 'zone')
        self.assertEqual(a, b)
        _i, c = _call('find', {'op': 'distance', 'target': 'office', 'target_b': ['a', 'b']}, 'zone')
        self.assertEqual(['a', 'b'], c['candidates'])

    def test_device_list_is_devices_without_a_keyword(self):
        inner, a = _call('find', {'op': 'device_list', 'limit': 40, 'offset': 40})
        self.assertEqual('search_devices', inner)
        self.assertEqual({'limit': 40, 'offset': 40}, a)

    def test_maps_is_the_tree_without_a_target(self):
        inner, a = _call('find', {'op': 'maps'})
        self.assertEqual('get_spatial_tree', inner)
        self.assertIs(True, a['brief'])

    def test_journal_is_journals_with_a_journal_as_target(self):
        inner, a = _call('records', {'op': 'journal', 'target': 'j1', 'granularity': 'weekly'}, 'journal')
        self.assertEqual('get_plot_journal', inner)
        self.assertEqual({'journal_id': 'id-1', 'granularity': 'weekly'}, a)
        inner, _b = _call('records', {'op': 'journals', 'target': 'p'}, 'plot')
        self.assertEqual('list_plot_journals', inner)

    def test_activate_picks_the_inner_tool_by_kind(self):
        inner, a = _call('configure', {'op': 'activate', 'target': 'i', 'state': 'on'}, 'input')
        self.assertEqual(('activate_input', True), (inner, a['active']))
        inner, a = _call('configure', {'op': 'activate', 'target': 'g', 'state': 'off'}, 'gis_layer')
        self.assertEqual(('activate_gis_input', False), (inner, a['active']))
        for old, kind in (('input_activate', 'input'), ('gis_input_activate', 'gis_layer')):
            self.assertEqual(_call('configure', {'op': 'activate', 'target': 'x', 'state': 'on'}, kind),
                             _call('configure', {'op': old, 'target': 'x', 'active': True}, kind))

    def test_activate_does_not_mix_approval(self):
        from aot.tools.domain import contract
        self.assertEqual([], contract.problems())

    def test_a_merged_name_is_not_listed_but_the_target_op_is(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = {e['name']: e['inputSchema']['properties']['op']['enum']
                for e in surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))
                if 'op' in e['inputSchema']['properties']}
        gone = {'measure': 'summary', 'overview': 'crops', 'find': 'maps', 'records': 'journal',
                'configure': 'input_activate'}
        for tool, op in gone.items():
            self.assertNotIn(op, ents[tool], (tool, op))
        for tool, op in (('measure', 'latest'), ('find', 'plots'), ('find', 'tree'), ('records', 'journals'),
                         ('configure', 'activate'), ('find', 'devices'), ('find', 'nearest')):
            self.assertIn(op, ents[tool], (tool, op))
        self.assertNotIn('active_functions', ents['overview'])
        self.assertNotIn('device_list', ents['find'])
        self.assertNotIn('distance', ents['find'])
        self.assertNotIn('device_location', ents['find'])

    def test_help_accepts_the_old_names_across_tools(self):
        from aot.tools.domain import dispatch
        card = dispatch.help_card('overview.crops')
        self.assertEqual('find.plots', card['operation'])
        self.assertEqual('detail.device', dispatch.help_card('find.device_location')['operation'])


class RunNotesTest(unittest.TestCase):
    """도구를 넘은 별칭도 응답 계약·카드·감사는 정식 도구/op 로 본다."""

    def test_a_cross_tool_alias_runs_as_the_new_tool(self):
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        seen = {}

        def inner(app, tool, arguments, ctx, show, answer_time):
            seen.update(tool=tool, op=arguments.get('op'))
            return [{'type': 'text', 'text': json.dumps({'status': 'success'})}]
        with mock.patch.object(dispatch, '_run_call_inner', inner):
            out = dispatch._run_call(None, 'overview', {'op': 'crops'},
                                     {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        self.assertEqual(('find', 'plots'), (seen['tool'], seen['op']))
        self.assertEqual({'op=crops': 'find.plots'}, json.loads(out[0]['text'])['renamed'])


class SearchDevicesDelegationTest(unittest.TestCase):

    def test_no_keyword_lists_every_device(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as DeviceTools
        with mock.patch.object(DeviceTools, 'get_device_list_tool', return_value={'devices': [1]}) as m:
            got = DeviceTools.search_devices(limit=10, offset=20)
        self.assertEqual({'devices': [1]}, got)
        m.assert_called_once_with(limit=10, offset=20)

    def test_a_keyword_still_searches(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as DeviceTools
        with mock.patch.object(DeviceTools, 'get_device_list_tool') as m, \
                mock.patch.object(DeviceTools, '_search_devices_all', return_value={'results': [], 'count': 0}):
            DeviceTools.search_devices(query='valve')
        m.assert_not_called()


if __name__ == '__main__':
    unittest.main()
