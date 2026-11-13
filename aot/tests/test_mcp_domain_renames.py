# coding=utf-8
"""옛 이름 별칭표(`domain.renames`)와 화면 따라가기 정책(`NO_FOLLOW_OPS`) — 2026-11-03 재설계 PR 1.

고정하는 계약:
  1. 별칭은 op 이름·인자 이름·고정 인자를 함께 다루고, 정식 이름과 똑같이 계획된다.
  2. 옛 이름이 실제 쓰인 호출의 응답에만 `renamed` 가 붙는다(안 쓰였으면 키 자체가 없다).
  3. 별칭표의 모든 항목은 등록일을 갖고, 가리키는 op/인자가 실제로 있다(일괄 제거를 쉽게).
  4. 계산뿐인 조회(find.nearest·distance·address·resolve)는 기본으로 화면을 안 따라가고 명시한 'on' 에는 따라간다.
     나머지 읽기는 지금처럼 따라가고 'off' 로 끈다. 스키마의 `_show_on_screen` 은 measure·detail 에만 있다.
"""
import json
import re
import unittest
from unittest import mock

from aot.tools.domain import renames
from aot.tools.domain.registry import Op

_TODAY = '2026-11-03'


def _op(tool, name, args=None, extra=None, inner=None, effect='read'):
    return Op(tool, name, 'x', inner or {'none': 'inner_tool'}, effect,
              args=args or {}, extra_args=extra or {})


class ResolveTest(unittest.TestCase):

    def _patch(self, op_aliases=None, arg_aliases=None, op_arg_aliases=None):
        for name, value in (('OP_ALIASES', op_aliases or {}), ('ARG_ALIASES', arg_aliases or {}),
                            ('OP_ARG_ALIASES', op_arg_aliases or {})):
            p = mock.patch.object(renames, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_op_alias_renames_op_moves_args_and_fixes_values(self):
        self._patch(op_aliases={('control', 'function_on'): renames.OpAlias(
            'function_set', since=_TODAY, rename={'function_id': 'target'}, fixed={'state': 'on'})})
        ops = [_op('control', 'function_set', extra={'state': 'on|off'}, effect='automation')]
        args, got = renames.resolve('control', {'op': 'function_on', 'function_id': 'f1'}, ops)
        self.assertEqual({'op': 'function_set', 'target': 'f1', 'state': 'on'}, args)
        self.assertEqual({'op=function_on': 'function_set', 'function_id': 'target'}, got)

    def test_fixed_values_never_override_what_the_call_gave(self):
        self._patch(op_aliases={('control', 'function_on'): renames.OpAlias(
            'function_set', since=_TODAY, fixed={'state': 'on'})})
        ops = [_op('control', 'function_set', extra={'state': 'x'})]
        args, _ = renames.resolve('control', {'op': 'function_on', 'state': 'off'}, ops)
        self.assertEqual('off', args['state'])

    def test_a_live_op_name_beats_an_alias(self):
        self._patch(op_aliases={('find', 'distance'): renames.OpAlias('nearest', since=_TODAY)})
        ops = [_op('find', 'distance'), _op('find', 'nearest')]
        args, got = renames.resolve('find', {'op': 'distance'}, ops)
        self.assertEqual('distance', args['op'])
        self.assertEqual({}, got)
        self.assertEqual('distance', renames.canonical_op('find', 'distance', ops))

    def test_global_arg_alias_applies_only_where_the_new_name_is_taken(self):
        self._patch(arg_aliases={'note': renames.ArgAlias('text', _TODAY)})
        takes = _op('record', 'note', args={'text': 'note'})
        other = _op('record', 'other', args={'value': 'x'})
        args, got = renames.resolve('record', {'op': 'note', 'note': 'hi'}, [takes, other])
        self.assertEqual({'op': 'note', 'text': 'hi'}, args)
        self.assertEqual({'note': 'text'}, got)
        args, got = renames.resolve('record', {'op': 'other', 'note': 'hi'}, [takes, other])
        self.assertEqual({'op': 'other', 'note': 'hi'}, args)
        self.assertEqual({}, got)

    def test_an_op_that_still_takes_the_old_name_keeps_it(self):
        self._patch(arg_aliases={'note': renames.ArgAlias('text', _TODAY)})
        both = _op('record', 'both', args={'text': 'note'}, extra={'note': 'legacy'})
        args, got = renames.resolve('record', {'op': 'both', 'note': 'hi'}, [both])
        self.assertEqual({'op': 'both', 'note': 'hi'}, args)
        self.assertEqual({}, got)

    def test_both_names_given_the_new_one_wins_and_nothing_is_dropped(self):
        self._patch(arg_aliases={'note': renames.ArgAlias('text', _TODAY)})
        takes = _op('record', 'note', args={'text': 'note'})
        args, got = renames.resolve('record', {'op': 'note', 'note': 'old', 'text': 'new'}, [takes])
        self.assertEqual('new', args['text'])
        self.assertEqual('old', args['note'])           # 거절도 삼킴도 하지 않는다 — 안쪽이 모르는 칸으로 알린다
        self.assertEqual({}, got)

    def test_op_scoped_arg_alias_only_in_that_op(self):
        self._patch(op_arg_aliases={('record', 'journal_create'): {
            'start': renames.ArgAlias('period', _TODAY)}})
        ops = [_op('record', 'journal_create', extra={'x': 'y'}), _op('record', 'sequence')]
        args, got = renames.resolve('record', {'op': 'journal_create', 'start': 'today'}, ops)
        self.assertEqual({'op': 'journal_create', 'period': 'today'}, args)
        args, got = renames.resolve('record', {'op': 'sequence', 'start': '08:00'}, ops)
        self.assertEqual({'op': 'sequence', 'start': '08:00'}, args)
        self.assertEqual({}, got)

    def test_nothing_to_rename_returns_the_same_arguments_and_no_note(self):
        self._patch()
        ops = [_op('measure', 'latest')]
        given = {'op': 'latest', 'target': 'x'}
        args, got = renames.resolve('measure', given, ops)
        self.assertEqual(given, args)
        self.assertEqual({}, got)
        self.assertIsNot(given, args)                    # 호출자의 dict 는 건드리지 않는다


class TableIntegrityTest(unittest.TestCase):
    """별칭표가 실제 이름을 가리키고 등록일이 있다 — 기본 표면 전환 2주 뒤 일괄 제거의 기준."""

    def test_every_entry_has_a_registration_date(self):
        for row in renames.rows():
            self.assertRegex(row[2], r'^\d{4}-\d{2}-\d{2}$', row)

    def test_op_aliases_point_at_real_ops_and_args(self):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        from aot.tools.domain.registry import READ_TOOLS
        for (tool, old), a in renames.OP_ALIASES.items():
            real = find_op(OPS, a.tool or tool, a.op)
            self.assertIsNotNone(real, (tool, old))
            # 도구를 넘는 별칭은 읽기↔쓰기를 넘지 않는다(권한·승인이 도구 단위다).
            self.assertEqual(tool in READ_TOOLS, (a.tool or tool) in READ_TOOLS, (tool, old))
            self.assertIsNone(find_op(OPS, tool, old), 'alias %s.%s is also a live op' % (tool, old))
            accepted = set(real.args) | set(real.extra_args) | {'target', 'op'}
            for new in a.rename.values():
                self.assertIn(new, accepted, (tool, old, new))
            for key in a.fixed:
                self.assertIn(key, accepted, (tool, old, key))

    def test_arg_aliases_point_at_an_op_that_takes_the_new_name(self):
        from aot.tools.domain.registry_data import OPS
        for old, al in renames.ARG_ALIASES.items():
            takers = [o for o in OPS if al.new in o.args or al.new in o.extra_args]
            self.assertTrue(takers, 'no op takes %r (alias of %r)' % (al.new, old))
        for (tool, op), table in renames.OP_ARG_ALIASES.items():
            from aot.tools.domain.registry import find_op
            o = find_op(OPS, tool, op)
            self.assertIsNotNone(o, (tool, op))
            for old, al in table.items():
                self.assertTrue(al.new in o.args or al.new in o.extra_args or al.new == 'target',
                                (tool, op, old, al.new))

    def test_aliases_are_not_advertised_anywhere(self):
        """별칭은 그 도구의 목록·op enum 에 안 실린다(토큰 0)."""
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = {e['name']: e for e in surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))}
        for (tool, old) in renames.OP_ALIASES:
            e = ents[tool]
            self.assertNotIn(old, e['inputSchema']['properties']['op']['enum'], (tool, old))
            self.assertNotIn('\n%s ' % old, e['description'], (tool, old))


class RenamedNoteTest(unittest.TestCase):
    """옛 이름이 쓰인 호출에만 응답에 `renamed` 한 줄 — status·say·next 다음, data 앞."""

    def _run(self, args, inner_body=None):
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        body = inner_body or {'status': 'success', 'value': 21}

        def inner(app, tool, arguments, ctx, show, answer_time):
            self.seen = dict(arguments)
            return [{'type': 'text', 'text': json.dumps(body)}]
        with mock.patch.object(dispatch, '_run_call_inner', inner):
            out = dispatch._run_call(None, 'measure', args,
                                     {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        return json.loads(out[0]['text'])

    def test_old_op_name_adds_the_note_and_runs_the_new_one(self):
        body = self._run({'op': 'now', 'target': 'x'})
        self.assertEqual({'op=now': 'latest'}, body['renamed'])
        self.assertEqual('latest', self.seen['op'])
        keys = list(body)
        self.assertLess(keys.index('status'), keys.index('renamed'))
        self.assertLess(keys.index('renamed'), keys.index('value'))

    def test_new_name_adds_nothing(self):
        body = self._run({'op': 'latest', 'target': 'x'})
        self.assertNotIn('renamed', body)

    def test_the_note_sits_after_say_and_next(self):
        body = self._run({'op': 'now', 'target': 'x'},
                         {'status': 'success', 'value': 1, 'say': {'tell': 'a'}, 'next': {'call': 'b'}})
        # `card` 는 값 조회(measure.latest)에 서버가 싣는 viz 카드 결과(#571) — renamed 다음, data 앞.
        self.assertEqual(['status', 'say', 'next', 'renamed', 'card', 'value'], list(body))

    def test_a_non_json_answer_is_left_alone(self):
        from aot.tools.domain import renames as R
        out = [{'type': 'text', 'text': 'plain'}]
        from aot.tools.domain import dispatch
        self.assertEqual(out, dispatch._with_renamed(out, {'a': 'b'}))
        self.assertEqual(out, dispatch._with_renamed(out, {}))
        del R


class ScreenPolicyTest(unittest.TestCase):
    """계산뿐인 조회는 기본으로 화면을 안 따라간다 — 양방향(2026-11-03 사용자 결정 4)."""

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)

    def _run(self, tool, op, extra=None):
        from aot.tools.domain import dispatch
        follows, shows = [], []
        ops = [Op('find', 'nearest', 'Rank', {'zone': 'nearest'}, 'read', target_arg={'zone': 'origin'}),
               Op('find', 'plots', 'Plots', {'zone': 'list_plots'}, 'read', target_arg={'zone': 'zone_id'}),
               Op('find', 'address', 'Address', {'zone': 'get_address'}, 'read', target_arg={'zone': 'target_name'})]
        cat = lambda: {name: {'inputSchema': {'type': 'object', 'properties': {
            k: {'type': 'string'} for k in ('origin', 'zone_id', 'target_name')}}}
            for name in ('nearest', 'list_plots', 'get_address')}

        def fake_execute(app, name, a, **ctx):
            return [{'type': 'text', 'text': json.dumps({'status': 'success'})}]

        def fake_follow(kind, ident, user, profile, transport, show=None, trace=None, session_key=None):
            follows.append((kind, ident, show))
            return {'opened': ident}

        def fake_slow(app, tool_name, permission, user, profile, transport, show=None):
            shows.append(show)
            return mock.MagicMock()
        with mock.patch('aot.tools.tool_execution._execute_tool', fake_execute), \
                mock.patch('aot.tools.screen_follow.follow_resolved', fake_follow), \
                mock.patch('aot.tools.domain.contract.catalog', cat), \
                mock.patch.object(dispatch.targets, 'resolve', lambda ref, **kw: (
                    'ok', {'kind': 'zone', 'id': 'Z', 'name': ref, 'path': 'm > ' + ref})), \
                mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}), \
                mock.patch.object(dispatch, '_ops', lambda: ops):
            args = dict({'op': op, 'target': '3-1'}, **(extra or {}))
            dispatch._run(None, tool, args, {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        return follows

    def _moved(self, tool, op, extra=None):
        """화면을 실제로 움직일 호출만 — follow_resolved 는 show='off' 로 불려도 스스로 아무것도 안 한다."""
        return [f for f in self._run(tool, op, extra) if f[2] != 'off']

    def test_calculation_only_ops_do_not_follow_by_default(self):
        self.assertEqual([], self._moved('find', 'nearest'))
        self.assertEqual([], self._moved('find', 'address'))
        self.assertEqual([('zone', 'Z', 'off')], self._run('find', 'nearest'))

    def test_the_default_can_be_flipped_on_per_call(self):
        self.assertEqual([('zone', 'Z', 'on')], self._run('find', 'nearest', {'_show_on_screen': 'on'}))
        self.assertEqual([('zone', 'Z', 'k9')], self._run('find', 'nearest', {'_show_on_screen': 'k9'}))

    def test_auto_and_off_keep_a_calculation_op_still(self):
        self.assertEqual([], self._moved('find', 'nearest', {'_show_on_screen': 'auto'}))
        self.assertEqual([], self._moved('find', 'nearest', {'_show_on_screen': 'off'}))

    def test_reads_of_one_target_still_follow_and_off_turns_them_off(self):
        self.assertEqual([('zone', 'Z', None)], self._run('find', 'plots'))
        self.assertEqual([('zone', 'Z', 'off')], self._run('find', 'plots', {'_show_on_screen': 'off'}))

    def test_effective_show_covers_every_no_follow_op(self):
        from aot.tools.domain import dispatch
        for tool, op in dispatch.NO_FOLLOW_OPS:
            self.assertEqual('off', dispatch.effective_show(tool, op, None), (tool, op))
            self.assertEqual('on', dispatch.effective_show(tool, op, 'on'), (tool, op))
        self.assertIsNone(dispatch.effective_show('measure', 'latest', None))

    def test_no_follow_ops_exist_in_the_registry_or_are_aliased(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        for tool, op in dispatch.NO_FOLLOW_OPS:
            live = find_op(OPS, tool, op) is not None
            aliased = (tool, op) in renames.OP_ALIASES
            self.assertTrue(live or aliased, (tool, op))

    def test_explicit_on_helper(self):
        from aot.tools import screen_follow as sf
        for v in ('on', 'ON', 'yes', 'true', '1', True, 'k9-screen'):
            self.assertTrue(sf.show_is_explicit_on(v), v)
        for v in (None, False, 'off', 'auto', 'default', '', 'no'):
            self.assertFalse(sf.show_is_explicit_on(v), v)


class ShowArgSchemaTest(unittest.TestCase):

    def test_only_measure_and_detail_carry_it(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))
        have = {e['name'] for e in ents if '_show_on_screen' in e['inputSchema']['properties']}
        self.assertEqual({'measure', 'detail'}, have)


if __name__ == '__main__':
    unittest.main()
