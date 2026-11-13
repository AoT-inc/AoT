# coding=utf-8
"""값으로 안쪽 도구를 고르는 훅 `Op.pick_by_arg` 와 그것을 쓰는 세 합치기(재설계 PR 6, 2026-11-03).

  control.function_on·function_off → control.function_set(state)
  record.schedule_add_batch        → record.schedule_add(entries)
  cultivate.stage_confirm·reschedule·guidance·add·undo → cultivate.stage(action)

고정하는 것: 고른 안쪽 도구·인자, 가지마다의 필수·받는 인자, 승인·효과가 가지 사이에서 같다는 계약, 옛 이름 별칭,
help 의 값별 표.
"""
import json
import unittest
from dataclasses import replace
from unittest import mock

from aot.tools.domain import contract, registry
from aot.tools.domain.registry import Op, Pick, find_op, leaves, merge_branches


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


def _refused(tool, args, kind=None):
    v = _plan(tool, args, kind)
    assert v[0] == 'refuse', v
    return json.loads(v[1][0]['text'])


class FunctionSetTest(unittest.TestCase):

    def test_state_picks_the_inner_tool(self):
        self.assertEqual(('activate_function', {'function_id': 'id-1'}),
                         _call('control', {'op': 'function_set', 'target': 'f', 'state': 'on'}, 'function'))
        self.assertEqual(('deactivate_function', {'function_id': 'id-1'}),
                         _call('control', {'op': 'function_set', 'target': 'f', 'state': 'off'}, 'function'))

    def test_state_accepts_the_usual_spellings(self):
        for value, want in ((True, 'activate_function'), ('true', 'activate_function'), ('ON', 'activate_function'),
                            (False, 'deactivate_function'), (0, 'deactivate_function')):
            self.assertEqual(want, _call('control', {'op': 'function_set', 'target': 'f', 'state': value},
                                         'function')[0], value)

    def test_a_state_it_cannot_read_runs_nothing(self):
        body = _refused('control', {'op': 'function_set', 'target': 'f', 'state': 'maybe'}, 'function')
        self.assertEqual('bad_state', body['reason_code'])
        self.assertIn('off, on', body['message'])           # 받는 값을 말한다

    def test_state_is_required(self):
        body = _refused('control', {'op': 'function_set', 'target': 'f'}, 'function')
        self.assertEqual('missing_argument', body['reason_code'])
        self.assertIn('state', body['message'])

    def test_old_names_are_aliases_that_fix_the_state(self):
        for old, want in (('function_on', 'activate_function'), ('function_off', 'deactivate_function')):
            self.assertEqual(want, _call('control', {'op': old, 'target': 'f'}, 'function')[0])
        from aot.tools.domain import renames
        _t, _a, got = renames.resolve_call('control', {'op': 'function_on', 'target': 'f'})
        self.assertEqual({'op=function_on': 'function_set'}, got)

    def test_both_branches_need_approval_and_are_automation(self):
        from aot.tools import tool_registry as R
        o = find_op(_ops(), 'control', 'function_set')
        self.assertEqual('automation', o.effect)
        for _v, leaf in leaves(o):
            self.assertTrue(set(leaf.inner.values()) <= set(R.approval_required_tools()))


class ScheduleAddTest(unittest.TestCase):

    def test_without_entries_it_is_one_task(self):
        inner, a = _call('record', {'op': 'schedule_add', 'target': 'z', 'at': '2026-11-05', 'text': '제초'}, 'zone')
        self.assertEqual('add_schedule', inner)
        self.assertEqual('제초', a['content'])

    def test_with_entries_it_is_a_batch(self):
        entries = [{'target': 'a', 'time': '09:00'}, {'target': 'b', 'time': '10:00'}]
        inner, a = _call('record', {'op': 'schedule_add', 'at': '2026-11-05', 'text': '점검', 'entries': entries})
        self.assertEqual('add_schedule_batch', inner)
        self.assertEqual(entries, a['entries'])
        self.assertEqual('점검', a['content'])

    def test_the_old_batch_name_is_an_alias(self):
        inner, _a = _call('record', {'op': 'schedule_add_batch', 'at': '2026-11-05', 'entries': [{'target': 'a'}]})
        self.assertEqual('add_schedule_batch', inner)

    def test_a_batch_takes_no_target_of_its_own(self):
        body = _refused('record', {'op': 'schedule_add', 'target': 'z', 'at': '2026-11-05',
                                   'entries': [{'target': 'a'}]}, 'zone')
        self.assertNotEqual('', body.get('message', ''))

    def test_a_single_task_still_needs_its_text(self):
        body = _refused('record', {'op': 'schedule_add', 'target': 'z', 'at': '2026-11-05'}, 'zone')
        self.assertEqual('missing_argument', body['reason_code'])
        self.assertIn('text', body['message'])


class StageTest(unittest.TestCase):
    ROUTES = {'confirm': 'confirm_plot_stage', 'reschedule': 'reschedule_plot_stage',
              'guidance': 'set_plot_stage_guidance', 'add': 'add_plot_stage', 'undo': 'undo_plot_stage'}

    def test_each_action_reaches_its_inner_tool(self):
        given = {'confirm': {'stage_key': 'k'}, 'reschedule': {'stage_key': 'k', 'shift_days': 3},
                 'guidance': {'stage_key': 'k', 'text': '물 주기'}, 'add': {'name': '순화', 'days': 5}, 'undo': {}}
        for action, inner in self.ROUTES.items():
            got, a = _call('cultivate', dict({'op': 'stage', 'target': 'p', 'action': action}, **given[action]), 'plot')
            self.assertEqual(inner, got, action)
            self.assertEqual('id-1', a['plot_id'])
            self.assertNotIn('action', a)                     # 고른 인자는 안쪽에 넘기지 않는다

    def test_text_becomes_guidance_in_both_branches_that_take_it(self):
        _i, a = _call('cultivate', {'op': 'stage', 'target': 'p', 'action': 'guidance', 'stage_key': 'k',
                                    'text': '환기'}, 'plot')
        self.assertEqual('환기', a['guidance'])
        _i, a = _call('cultivate', {'op': 'stage', 'target': 'p', 'action': 'add', 'name': 'x', 'days': 4,
                                    'text': '관수'}, 'plot')
        self.assertEqual('관수', a['guidance'])

    def test_each_action_keeps_its_own_required_arguments(self):
        for action, need in (('confirm', 'stage_key'), ('reschedule', 'stage_key'), ('guidance', 'stage_key'),
                             ('add', 'name')):
            body = _refused('cultivate', {'op': 'stage', 'target': 'p', 'action': action}, 'plot')
            self.assertEqual('missing_argument', body['reason_code'], action)
            self.assertIn(need, body['message'], action)
        body = _refused('cultivate', {'op': 'stage', 'target': 'p', 'action': 'guidance', 'stage_key': 'k'}, 'plot')
        self.assertIn('text', body['message'])

    def test_an_argument_of_another_action_is_refused(self):
        body = _refused('cultivate', {'op': 'stage', 'target': 'p', 'action': 'confirm', 'stage_key': 'k',
                                      'days': 3}, 'plot')
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('days', body['message'])

    def test_a_wrong_or_missing_action_runs_nothing(self):
        body = _refused('cultivate', {'op': 'stage', 'target': 'p', 'action': 'remove', 'stage_key': 'k'}, 'plot')
        self.assertEqual('bad_action', body['reason_code'])
        for a in self.ROUTES:
            self.assertIn(a, body['message'])
        body = _refused('cultivate', {'op': 'stage', 'target': 'p'}, 'plot')
        self.assertEqual('missing_argument', body['reason_code'])

    def test_old_names_are_aliases_that_fix_the_action(self):
        self.assertEqual('confirm_plot_stage',
                         _call('cultivate', {'op': 'stage_confirm', 'target': 'p', 'stage_key': 'k'}, 'plot')[0])
        self.assertEqual('undo_plot_stage', _call('cultivate', {'op': 'stage_undo', 'target': 'p'}, 'plot')[0])
        self.assertEqual('add_plot_stage',
                         _call('cultivate', {'op': 'stage_add', 'target': 'p', 'name': 'x', 'days': 2}, 'plot')[0])

    def test_removing_a_stage_stays_a_delete(self):
        o = find_op(_ops(), 'remove', 'stage_remove')
        self.assertEqual({'plot': 'remove_plot_stage'}, o.inner)

    def test_one_listing_line_replaces_five(self):
        names = {o.op for o in _ops() if o.tool == 'cultivate'}
        self.assertIn('stage', names)
        self.assertFalse({'stage_confirm', 'stage_reschedule', 'stage_guidance', 'stage_add', 'stage_undo'} & names)


class HelpCardTest(unittest.TestCase):

    def test_help_lists_what_each_value_needs_and_takes(self):
        from aot.tools.domain import dispatch
        card = dispatch.help_card('cultivate.stage')
        self.assertEqual('action', card['choose_by'])
        by = card['by_value']
        self.assertEqual({'confirm', 'reschedule', 'guidance', 'add', 'undo'}, set(by))
        self.assertIn('stage_key', by['confirm']['needs'])
        self.assertIn('name', by['add']['needs'])
        self.assertIn('shift_days', by['reschedule']['takes'])
        self.assertNotIn('shift_days', by['confirm']['takes'])
        self.assertTrue(card['needs_approval'])

    def test_help_for_an_old_name_finds_the_new_op(self):
        from aot.tools.domain import dispatch
        card = dispatch.help_card('control.function_on')
        self.assertEqual('control.function_set', card['operation'])
        self.assertEqual({'on', 'off'}, set(card['by_value']))


def _ops():
    from aot.tools.domain.registry_data import OPS
    return OPS


class ContractTest(unittest.TestCase):
    """계약 검사가 가지마다 돈다 — 가지를 하나 빠뜨리거나 승인·효과를 섞으면 쓰기가 꺼진다."""

    def _swap(self, tool, op, fn):
        return [fn(o) if (o.tool, o.op) == (tool, op) else o for o in _ops()]

    def _replace_branch(self, o, value, **changes):
        pk = o.pick_by_arg
        branches = dict(pk.branches)
        branches[value] = replace(branches[value], **changes)
        return replace(o, pick_by_arg=replace(pk, branches=branches))

    def test_the_real_registry_is_clean(self):
        self.assertEqual([], contract.problems())

    def test_dropping_a_branch_leaves_its_write_tool_unmapped(self):
        def drop(o):
            pk = o.pick_by_arg
            return replace(o, pick_by_arg=replace(pk, branches={k: v for k, v in pk.branches.items() if k != 'undo'}))
        found = contract.problems(ops=self._swap('cultivate', 'stage', drop))
        self.assertTrue(any("unmapped write tool 'undo_plot_stage'" in p for p in found), found)

    def test_a_branch_that_repeats_another_branchs_tool_is_mapped_twice(self):
        def twice(o):
            return self._replace_branch(o, 'off', inner={'function': 'activate_function'})
        found = contract.problems(ops=self._swap('control', 'function_set', twice))
        self.assertTrue(any("mapped more than once" in p and 'activate_function' in p for p in found), found)

    def test_branches_cannot_mix_approval_and_no_approval(self):
        def mix(o):
            return self._replace_branch(o, '*', inner={'none': 'create_notice'})
        found = contract.problems(ops=self._swap('record', 'schedule_add', mix))
        self.assertTrue(any('mix approval' in p for p in found), found)

    def test_branches_cannot_differ_in_effect(self):
        found = contract.problems(ops=self._swap(
            'control', 'function_set', lambda o: self._replace_branch(o, 'off', effect='config')))
        self.assertTrue(any('differ in effect' in p for p in found), found)

    def test_a_branch_is_checked_like_any_op(self):
        found = contract.problems(ops=self._swap(
            'cultivate', 'stage', lambda o: self._replace_branch(o, 'confirm', extra_args={'nope': 'x'})))
        self.assertTrue(any("extra arg 'nope' not in inner schema" in p for p in found), found)

    def test_a_pick_argument_must_be_an_argument_of_the_op(self):
        def bad(o):
            return replace(o, extra_args={k: v for k, v in o.extra_args.items() if k != 'action'})
        found = contract.problems(ops=self._swap('cultivate', 'stage', bad))
        self.assertTrue(any("pick argument 'action'" in p for p in found), found)

    def test_a_write_op_with_a_broken_branch_switches_writes_off(self):
        found = contract.problems(ops=self._swap(
            'control', 'function_set', lambda o: self._replace_branch(o, 'on', inner={'function': 'no_such_tool'})))
        self.assertTrue(found)

    def test_merge_gives_the_parent_the_union_for_the_listing(self):
        o = find_op(_ops(), 'cultivate', 'stage')
        self.assertIsInstance(o.pick_by_arg, Pick)
        self.assertEqual({'plot': 'confirm_plot_stage'}, o.inner)       # 목록용 — 실행은 가지가 한다
        self.assertEqual(set(self.ROUTES_TOOLS), set(o.inner_tools))
        for extra in ('stage_key', 'days', 'shift_days', 'started_on', 'after', 'name', 'action'):
            self.assertIn(extra, o.extra_args)

    ROUTES_TOOLS = ('confirm_plot_stage', 'reschedule_plot_stage', 'set_plot_stage_guidance',
                    'add_plot_stage', 'undo_plot_stage')


class ListingTest(unittest.TestCase):

    def test_the_listing_shows_the_merged_ops_with_the_picking_argument(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        ents = {e['name']: e for e in surface.entries(_ops(), lambda n: True, set(R.approval_required_tools()))}
        stage = ents['cultivate']['inputSchema']['properties']
        self.assertIn('action', stage)
        self.assertIn('stage', stage['op']['enum'])
        self.assertIn('stage — ', ents['cultivate']['description'])
        self.assertIn('[setup; approval]', [l for l in ents['cultivate']['description'].splitlines()
                                            if l.startswith('stage — ')][0])
        ctl = ents['control']['inputSchema']['properties']
        self.assertIn('function_set', ctl['op']['enum'])
        self.assertIn('state', ctl)
        self.assertIn('entries', ents['record']['inputSchema']['properties'])


if __name__ == '__main__':
    unittest.main()
