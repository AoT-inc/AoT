# coding=utf-8
"""종류별 합치기(재설계 PR 7, 2026-11-03) — `remove.delete`(지우기 14→1)·`configure.edit`(고치기 6→1).

PR 조건(사용자 결정 9-5): **종류마다 되묻기·되읽기·승인 흐름이 그대로**여야 한다 — 그래서 종류마다 시험한다.
`kind` 는 PR 6 의 훅(`Op.pick_by_arg`, `infer=True`)이 읽는다: 말하면 그 종류의 가지로 좁히고(그 종류의 id 도 받는다),
안 말하면 평소처럼 대상에서 종류를 알아낸다(모호하면 되묻는다).
"""
import json
import unittest
from unittest import mock

from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_registry as R
from aot.tools.domain import contract, dispatch
from aot.tools.domain.registry import find_op, leaves

#: 종류 → (안쪽 도구, 대상 id 를 넣는 안쪽 인자)
DELETE = {
    'note': ('delete_note', 'note_id'), 'notice': ('delete_notice', 'notice_id'),
    'schedule': ('delete_schedule', 'job_id'),
    'plot': ('delete_plot', 'plot_id'), 'program': ('delete_program', 'program_id'),
    'input': ('delete_input', 'input_id'), 'output': ('delete_output', 'output_id'),
    'function': ('delete_function', 'function_id'), 'gis_layer': ('delete_gis_input', 'layer_id'),
    'widget': ('delete_widget', 'widget_id'), 'tab': ('delete_tab', 'tab_id'),
    'ai_agent': ('delete_ai_agent', 'agent_id'), 'shape': ('delete_geo_shape', 'shape_id'),
}
EDIT = {
    'input': ('modify_input', 'input_id'), 'output': ('modify_output', 'output_id'),
    'gis_layer': ('modify_gis_input', 'layer_id'), 'widget': ('modify_widget', 'widget_id'),
    'tab': ('modify_tab', 'tab_id'), 'ai_agent': ('modify_ai_agent', 'agent_id'),
}
OLD_DELETE = {'notice': 'notice_delete', 'note': 'note_delete', 'schedule': 'schedule_delete',
              'plot': 'plot_delete', 'program': 'program_delete',
              'input': 'input_delete', 'output': 'output_delete', 'function': 'function_delete',
              'gis_layer': 'gis_input_delete', 'widget': 'widget_delete', 'tab': 'tab_delete',
              'ai_agent': 'ai_agent_delete', 'shape': 'shape_delete'}
OLD_EDIT = {'input': 'input_edit', 'output': 'output_edit', 'gis_layer': 'gis_input_edit',
            'widget': 'widget_edit', 'tab': 'tab_edit', 'ai_agent': 'ai_agent_edit'}

#: 종류마다 아직 안 돌려 본 필수 인자(고치기)
EDIT_ARGS = {'input': {'params': {'a': 1}}, 'output': {'params': {'a': 1}}, 'gis_layer': {'params': {'a': 1}},
             'widget': {'options': {'a': 1}}, 'tab': {'name': '새 탭'}, 'ai_agent': {'system_prompt': 'x'}}


def _ops():
    from aot.tools.domain.registry_data import OPS
    return OPS


def _plan(tool, args, kind=None, state='ok', calls=None, amb=('input', 'function')):
    def resolve(ref, **kw):
        if calls is not None:
            calls.append(kw)
        if state == 'ambiguous':
            return 'ambiguous', [{'kind': k, 'id': 'id-%s' % k, 'name': str(ref), 'path': '%s > %s' % (k, ref)}
                                 for k in amb]
        if state == 'none':
            return 'none', {'error': 'Unknown target %r.' % ref}
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref), 'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {'kind': t.get('kind')}):
        return dispatch.plan(tool, dict(args))


def _call(tool, args, kind=None, **kw):
    v = _plan(tool, args, kind, **kw)
    assert v[0] == 'call', v
    return v[1], v[2]


def _body(v):
    assert v[0] == 'refuse', v
    return json.loads(v[1][0]['text'])


class DeleteEachKindTest(unittest.TestCase):

    def test_every_kind_reaches_its_own_inner_tool_and_id_argument(self):
        for kind, (inner, arg) in DELETE.items():
            with self.subTest(kind=kind):
                got, a = _call('remove', {'op': 'delete', 'kind': kind, 'target': 'x'}, kind)
                self.assertEqual(inner, got)
                self.assertEqual('id-1', a[arg])
                self.assertNotIn('kind', a)                      # 고른 인자는 안쪽에 넘기지 않는다
                self.assertIn(dispatch.SNAPSHOT_KEY, a)          # 승인 대기가 되읽을 대상 사진은 그대로 실린다

    def test_every_kind_keeps_its_approval_requirement(self):
        approval = set(R.approval_required_tools())
        for kind, (inner, _arg) in DELETE.items():
            self.assertIn(inner, approval, kind)                  # 도메인 op 가 승인을 낮출 수단은 없다
        o = find_op(_ops(), 'remove', 'delete')
        self.assertEqual({v[0] for v in DELETE.values()}, set(o.inner_tools))
        self.assertEqual([], contract.problems())

    def test_the_old_op_names_still_reach_the_same_calls(self):
        for kind, old in OLD_DELETE.items():
            with self.subTest(old=old):
                self.assertEqual(_call('remove', {'op': 'delete', 'kind': kind, 'target': 'x'}, kind),
                                 _call('remove', {'op': old, 'target': 'x'}, kind))

    def test_an_id_the_resolver_does_not_know_is_read_as_the_kind_said(self):
        # 노트·공지·일정은 id 로만 가리킨다 — kind 를 말하면 그 id 로 간다.
        for kind in ('note', 'notice', 'schedule', 'program', 'shape', 'gis_layer', 'ai_agent'):
            with self.subTest(kind=kind):
                inner, a = _call('remove', {'op': 'delete', 'kind': kind,
                                            'target': '3f2c9a8e-1111-4222-8333-444455556666'}, state='none')
                self.assertEqual(DELETE[kind][0], inner)
                self.assertEqual('3f2c9a8e-1111-4222-8333-444455556666', a[DELETE[kind][1]])

    def test_without_a_kind_an_unknown_id_asks_for_the_kind_and_runs_nothing(self):
        body = _body(_plan('remove', {'op': 'delete', 'target': '3f2c9a8e-1111-4222-8333-444455556666'},
                           state='none'))
        self.assertEqual('unknown_target', body['reason_code'])
        self.assertIn('kind=', body['message'])
        self.assertIn('note', body['next']['call'])

    def test_naming_the_kind_narrows_the_search_to_it(self):
        seen = []
        _call('remove', {'op': 'delete', 'kind': 'input', 'target': '센서A'}, 'input', calls=seen)
        self.assertEqual({'input'}, set(seen[0]['accepts']))     # 같은 이름의 함수·위젯은 후보가 아니다

    def test_without_a_kind_the_target_decides_as_before(self):
        self.assertEqual('delete_input', _call('remove', {'op': 'delete', 'target': '센서A'}, 'input')[0])
        self.assertEqual('delete_widget', _call('remove', {'op': 'delete', 'target': '위젯A'}, 'widget')[0])

    def test_a_name_of_two_kinds_still_asks_which_and_runs_nothing(self):
        body = _body(_plan('remove', {'op': 'delete', 'target': '관수'}, state='ambiguous'))
        self.assertEqual('ambiguous_target', body['reason_code'])
        self.assertEqual({'input', 'function'}, {c['kind'] for c in body['candidates']})
        # kind 를 말하면 되묻지 않고 그 종류로 좁혀 푼다(해석기가 그 종류만 보게).
        seen = []
        _call('remove', {'op': 'delete', 'kind': 'function', 'target': '관수'}, 'function', calls=seen)
        self.assertEqual({'function'}, set(seen[0]['accepts']))

    def test_a_name_that_is_not_of_the_said_kind_runs_nothing(self):
        # 해석기는 말한 종류만 본다 — 그 종류에 없는 이름은 못 찾은 것이고, 다른 종류로 대신 지우지 않는다.
        body = _body(_plan('remove', {'op': 'delete', 'kind': 'input', 'target': '3-1'}, state='none'))
        self.assertEqual('unknown_target', body['reason_code'])

    def test_a_kind_it_does_not_know_runs_nothing_and_lists_the_kinds(self):
        body = _body(_plan('remove', {'op': 'delete', 'kind': 'device', 'target': 'x'}, 'device'))
        self.assertEqual('bad_kind', body['reason_code'])
        for kind in DELETE:
            self.assertIn(kind, body['message'])

    def test_a_few_other_words_for_a_kind_are_understood(self):
        self.assertEqual('delete_gis_input',
                         _call('remove', {'op': 'delete', 'kind': 'gis_input', 'target': 'x'}, 'gis_layer')[0])
        self.assertEqual('delete_tab', _call('remove', {'op': 'delete', 'kind': 'Dashboard', 'target': 'x'}, 'tab')[0])

    def test_the_kinds_own_arguments_only(self):
        inner, a = _call('remove', {'op': 'delete', 'kind': 'schedule', 'target': 'j1', 'reason': '비'}, 'schedule')
        self.assertEqual('비', a['reason'])
        body = _body(_plan('remove', {'op': 'delete', 'kind': 'note', 'target': 'n', 'reason': 'x'}, 'note'))
        self.assertEqual('unknown_argument', body['reason_code'])

    def test_one_target_per_call_and_a_missing_target_run_nothing(self):
        body = _body(_plan('remove', {'op': 'delete', 'kind': 'input', 'target': ['a', 'b']}, 'input'))
        self.assertEqual('single_target_only', body['reason_code'])
        body = _body(_plan('remove', {'op': 'delete', 'kind': 'input'}, 'input'))
        self.assertIn(body['reason_code'], ('target_required', 'missing_argument'))

    def test_the_other_two_deleting_ops_are_not_merged(self):
        names = {o.op for o in _ops() if o.tool == 'remove'}
        self.assertEqual({'alias_delete', 'delete', 'stage_remove'}, names)
        self.assertEqual('delete_target_alias', find_op(_ops(), 'remove', 'alias_delete').inner['none'])

    def test_help_tells_what_each_kind_is_and_needs(self):
        card = dispatch.help_card('remove.delete')
        self.assertEqual('kind', card['choose_by'])
        self.assertEqual(set(DELETE), set(card['by_value']))
        self.assertIn('mistakes only', card['by_value']['plot']['use'])
        self.assertTrue(card['needs_approval'])

    def test_old_help_name_finds_the_merged_op(self):
        self.assertEqual('remove.delete', dispatch.help_card('remove.plot_delete')['operation'])


class DeleteApprovalFlowTest(unittest.TestCase):
    """합쳐도 승인은 안쪽 도구 이름으로 일어난다 — 같은 안쪽 호출이 나가고, 되읽기 글은 안쪽 도구가 만든다."""

    def test_the_approval_text_is_built_from_the_same_inner_call(self):
        # 되읽기는 도메인 op 와 무관하다: 안쪽 도구·인자가 같으면 글도 같다(옛 op 로 부르든 새 op 로 부르든).
        for kind, old in OLD_DELETE.items():
            with self.subTest(kind=kind):
                new = _call('remove', {'op': 'delete', 'kind': kind, 'target': 'x'}, kind)
                oldv = _call('remove', {'op': old, 'target': 'x'}, kind)
                self.assertEqual(gate.read_back_text(new[0], new[1]), gate.read_back_text(oldv[0], oldv[1]))

    def test_the_note_kind_reads_back_title_place_and_first_line(self):
        self.assertIn('노트 삭제', gate.read_back_text('delete_note', {'note_id': 'nope'}))


class EditEachKindTest(unittest.TestCase):

    def test_every_kind_reaches_its_own_inner_tool_and_id_argument(self):
        for kind, (inner, arg) in EDIT.items():
            with self.subTest(kind=kind):
                got, a = _call('configure', dict({'op': 'edit', 'kind': kind, 'target': 'x'}, **EDIT_ARGS[kind]), kind)
                self.assertEqual(inner, got)
                self.assertEqual('id-1', a[arg])
                self.assertNotIn('kind', a)

    def test_every_kind_keeps_its_approval_requirement(self):
        approval = set(R.approval_required_tools())
        for kind, (inner, _arg) in EDIT.items():
            self.assertTrue((inner in approval) is True, kind)

    def test_the_old_op_names_still_reach_the_same_calls(self):
        for kind, old in OLD_EDIT.items():
            with self.subTest(old=old):
                args = dict({'target': 'x'}, **EDIT_ARGS[kind])
                self.assertEqual(_call('configure', dict({'op': 'edit', 'kind': kind}, **args), kind),
                                 _call('configure', dict({'op': old}, **args), kind))

    def test_without_a_kind_the_target_decides_as_before(self):
        self.assertEqual('modify_widget',
                         _call('configure', {'op': 'edit', 'target': 'w', 'options': {'a': 1}}, 'widget')[0])
        self.assertEqual('modify_output', _call('configure', {'op': 'edit', 'target': 'o', 'params': {}}, 'output')[0])

    def test_each_kind_takes_its_own_arguments_and_refuses_the_others(self):
        # 입력·출력·GIS 입력은 params, 위젯은 options — 섞으면 거절하고 그 종류가 받는 인자를 알려 준다.
        body = _body(_plan('configure', {'op': 'edit', 'kind': 'input', 'target': 'x', 'options': {}}, 'input'))
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('params', body['message'])
        body = _body(_plan('configure', {'op': 'edit', 'kind': 'widget', 'target': 'x', 'params': {}}, 'widget'))
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('options', body['message'])
        _i, a = _call('configure', {'op': 'edit', 'kind': 'widget', 'target': 'x', 'width': 4, 'height': 2}, 'widget')
        self.assertEqual((4, 2), (a['width'], a['height']))
        _i, a = _call('configure', {'op': 'edit', 'kind': 'ai_agent', 'target': 'x', 'role': 'r', 'model_tier': 't'},
                      'ai_agent')
        self.assertEqual('t', a['model_tier'])

    def test_a_tab_needs_its_new_name(self):
        body = _body(_plan('configure', {'op': 'edit', 'kind': 'tab', 'target': 'x'}, 'tab'))
        self.assertEqual('missing_argument', body['reason_code'])
        self.assertIn('name', body['message'])

    def test_naming_the_kind_narrows_the_search_and_a_name_of_two_kinds_asks(self):
        seen = []
        _call('configure', {'op': 'edit', 'kind': 'input', 'target': '센서A', 'params': {}}, 'input', calls=seen)
        self.assertEqual({'input'}, set(seen[0]['accepts']))
        body = _body(_plan('configure', {'op': 'edit', 'target': '관수', 'name': 'n'}, state='ambiguous',
                           amb=('input', 'widget')))
        self.assertEqual('ambiguous_target', body['reason_code'])
        self.assertEqual({'input', 'widget'}, {c['kind'] for c in body['candidates']})

    def test_a_wrong_kind_runs_nothing(self):
        body = _body(_plan('configure', {'op': 'edit', 'kind': 'sensor2', 'target': 'x'}, 'input'))
        self.assertEqual('bad_kind', body['reason_code'])
        body = _body(_plan('configure', {'op': 'edit', 'kind': 'widget', 'target': '3-1', 'options': {}}, state='none'))
        self.assertEqual('unknown_target', body['reason_code'])

    def test_activate_is_the_one_from_pr3_and_edit_points_to_it(self):
        self.assertIn('activate', find_op(_ops(), 'configure', 'edit').use)
        self.assertIsNotNone(find_op(_ops(), 'configure', 'activate'))

    def test_help_lists_each_kind(self):
        card = dispatch.help_card('configure.edit')
        self.assertEqual(set(EDIT), set(card['by_value']))
        self.assertIn('params', card['by_value']['input']['takes'])
        self.assertNotIn('params', card['by_value']['widget']['takes'])
        self.assertIn('options', card['by_value']['widget']['takes'])


class ListingTest(unittest.TestCase):

    def test_two_lines_replace_twenty(self):
        names = {(o.tool, o.op) for o in _ops()}
        for old in OLD_DELETE.values():
            self.assertNotIn(('remove', old), names)
        for old in OLD_EDIT.values():
            self.assertNotIn(('configure', old), names)
        self.assertIn(('remove', 'delete'), names)
        self.assertIn(('configure', 'edit'), names)

    def test_the_listing_marks_delete_as_needing_approval(self):
        from aot.tools.domain import surface
        ents = {e['name']: e for e in surface.entries(_ops(), lambda n: True, set(R.approval_required_tools()))}
        line = [l for l in ents['remove']['description'].splitlines() if l.startswith('delete — ')][0]
        self.assertIn('approval', line)
        self.assertIn('kind', ents['remove']['inputSchema']['properties'])
        self.assertEqual('remove', 'remove')                              # 지우는 도구 하나(destructiveHint)
        self.assertTrue(surface.annotations_for('remove').get('destructiveHint'))


class ContractTest(unittest.TestCase):

    def test_a_delete_branch_cannot_move_out_of_the_remove_tool(self):
        from dataclasses import replace
        o = find_op(_ops(), 'remove', 'delete')
        pk = o.pick_by_arg
        branches = dict(pk.branches)
        branches['note'] = replace(branches['note'], inner={'note': 'create_note'})
        bad = replace(o, pick_by_arg=replace(pk, branches=branches))
        found = contract.problems(ops=[bad if x is o else x for x in _ops()])
        self.assertTrue(any('deleting inner tools belong only in' in p or 'mix approval' in p for p in found), found)

    def test_a_merged_op_must_state_an_effect_one_of_its_branches_has(self):
        from dataclasses import replace
        o = find_op(_ops(), 'remove', 'delete')
        found = contract.problems(ops=[replace(o, effect='physical') if x is o else x for x in _ops()])
        self.assertTrue(any('differ in effect' in p for p in found), found)


if __name__ == '__main__':
    unittest.main()
