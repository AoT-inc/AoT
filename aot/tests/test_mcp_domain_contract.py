# coding=utf-8
"""도메인 틀 1단계 — 안전 계약(docs/design/mcp-domain-surface.md §9-2).

차단 조건(하나라도 실패하면 통과 실패):
  - 명부 매핑 완전성(쓰기 도구 정확히 한 번 · 읽기 적어도 한 번 · 없는 도구 0)
  - 승인 완화 없음(한 operation 안 승인 성격 일관 · 명부에 승인 칸 없음 —
    승인은 안쪽 도구 이름으로 지금 게이트가 판정)
  - 실행 경로는 `_execute_tool` 재귀 하나(빠져나가는 길 없음)
  - 무단 다중 대상 쓰기 0(여러 대상·그릇·모호함은 게이트 앞에서 거절)
  - 승인 뒤 바뀐 대상은 실행하지 않음
  - 명부 검사가 실패하면 쓰기가 꺼진다(fail-closed), 읽기는 남는다

결정론적 서버 테스트다 — 실제 모델의 도구 선택은 벤치(§8)가 따로 본다.
"""
import ast
import inspect
import json
import unittest
from unittest import mock

from aot.tools.domain.registry import Op


def _cat():
    """작은 가짜 카탈로그 — 계약 검사의 판정만 본다."""
    def d(*props, arrays=()):
        p = {k: {'type': 'string'} for k in props}
        for a in arrays:
            p[a] = {'type': 'array', 'items': {'type': 'string'}}
        return {'inputSchema': {'type': 'object', 'properties': p}}
    return {
        'get_sensor_reading': d('device_id'),
        'get_zone_sensor_summary': d('measurement_type', arrays=('zone_ids',)),
        'operate_device': d('device_id', 'state', 'value'),
        'create_note': d('note', 'target_id'),
        'add_schedule_batch': d('content', arrays=('entries',)),
        'delete_input': d('input_id'),
    }


def _ops(**over):
    base = [
        Op('measure', 'latest', 'Current values', {'input': 'get_sensor_reading',
           'zone': 'get_zone_sensor_summary'}, 'read',
           args={'measurement': 'measurement_type'},
           target_arg={'input': 'device_id', 'zone': 'zone_ids'}),
        Op('control', 'device_set', 'Turn a device on or off',
           {'output': 'operate_device'}, 'physical',
           target_arg={'output': 'device_id'},
           extra_args={'state': 'on/off action', 'value': 'set value'}),
        Op('record', 'note_add', 'Write a note', {'zone': 'create_note',
           'none': 'create_note'}, 'record', args={'value': 'note'},
           target_arg={'zone': 'target_id'}),
        Op('record', 'schedule_batch', 'Several tasks at once',
           {'none': 'add_schedule_batch'}, 'record',
           extra_args={'entries': 'one per target', 'content': 'shared text'},
           expand_write=True, max_targets=10),
        Op('remove', 'input_delete', 'Delete a sensor', {'input': 'delete_input'},
           'config', target_arg={'input': 'input_id'}),
    ]
    return base


def _fake_gate():
    """분류만 흉내 — 쓰기 도구와 승인·물리 집합."""
    writes = {'operate_device', 'create_note', 'add_schedule_batch', 'delete_input'}
    return (mock.patch('aot.tools.mcp_safety_gate.classify_permission',
                       lambda n: 'write' if n in writes else 'read'),
            mock.patch('aot.tools.tool_registry.approval_required_tools',
                       lambda: frozenset({'operate_device', 'delete_input'})))


class ContractCheckTest(unittest.TestCase):

    def _problems(self, ops):
        from aot.tools.domain import contract
        p1, p2 = _fake_gate()
        with p1, p2, mock.patch('aot.tools.tool_registry.MCP_FACADES', {}), \
                mock.patch('aot.tools.tool_registry.ACTS_WITHOUT_SAVING', frozenset()):
            return contract.problems(ops, _cat())

    def test_good_registry_has_no_problems(self):
        self.assertEqual([], self._problems(_ops()))

    def test_unmapped_and_duplicated_writes_block(self):
        ops = [o for o in _ops() if o.op != 'input_delete']
        self.assertTrue(any("unmapped write tool 'delete_input'" in p
                            for p in self._problems(ops)))
        dup = _ops() + [Op('record', 'note_again', 'x', {'zone': 'create_note'},
                           'record', target_arg={'zone': 'target_id'})]
        self.assertTrue(any('mapped more than once' in p for p in self._problems(dup)))

    def test_read_tool_cannot_route_to_a_write_and_vice_versa(self):
        bad = _ops() + [Op('find', 'oops', 'x', {'none': 'delete_input'}, 'read')]
        self.assertTrue(any('read tool routes to write tool' in p
                            for p in self._problems(bad)))

    def test_physical_tool_must_be_marked_physical(self):
        ops = [o if o.op != 'device_set' else Op(
            'control', 'device_set', 'x', {'output': 'operate_device'}, 'config',
            target_arg={'output': 'device_id'},
            extra_args={'state': 'a', 'value': 'b'}) for o in _ops()]
        self.assertTrue(any('not marked physical' in p for p in self._problems(ops)))

    def test_one_op_cannot_mix_approval_and_no_approval(self):
        ops = [o if o.op != 'note_add' else Op(
            'record', 'note_add', 'x', {'zone': 'create_note', 'input': 'delete_input'},
            'record', target_arg={'zone': 'target_id', 'input': 'input_id'})
            for o in _ops() if o.op != 'input_delete']
        self.assertTrue(any('mixes approval' in p for p in self._problems(ops)))

    def test_args_must_exist_in_the_inner_schema(self):
        ops = [o if o.op != 'device_set' else Op(
            'control', 'device_set', 'x', {'output': 'operate_device'}, 'physical',
            target_arg={'output': 'device_id'}, extra_args={'speed': 'made up'})
            for o in _ops()]
        self.assertTrue(any("extra arg 'speed' not in inner schema" in p
                            for p in self._problems(ops)))

    def test_registry_has_no_approval_field_to_lower(self):
        """승인 요구는 안쪽 도구에서만 온다 — 명부가 승인을 적을 칸 자체가 없다."""
        fields = set(Op.__dataclass_fields__)
        self.assertFalse({f for f in fields if 'approv' in f}, fields)


class RealRegistryTest(unittest.TestCase):
    """실제 명부가 지금 도구 표면과 계약을 지킨다 — 차단 조건."""

    def test_registry_matches_the_current_surface(self):
        from aot.tools.domain import contract
        self.assertEqual([], contract.problems())

    def test_card_takes_screen_and_run_call_aliases_the_two_names(self):
        from aot.tools.domain import dispatch
        v = dispatch.plan('screen', {'op': 'card', 'message': 'x', 'screen': 'k1'})
        self.assertEqual('call', v[0], v)
        self.assertEqual('k1', v[2]['screen'])
        seen = {}

        def run(app, tool, arguments, ctx, show, answer_time):
            seen.update(tool=tool, args=arguments, show=show)
            return None
        for tool, given in (('screen', {'_show_on_screen': 'k9'}),
                            ('measure', {'screen': 'k9'})):
            seen.clear()
            with mock.patch.object(dispatch, '_run_call_inner', run), \
                    mock.patch('aot.tools.screen_follow.slow_read_notice',
                               lambda *a, **k: mock.MagicMock()):
                dispatch._run_call(None, tool, dict(given, op='latest'), {})
            if tool == 'screen':
                self.assertEqual('k9', seen['args'].get('screen'))
            else:
                self.assertEqual('k9', seen['show'])
                self.assertNotIn('screen', seen['args'])

    def test_candidates_show_kind_when_the_path_is_a_bare_name(self):
        from aot.tools.domain import dispatch
        got = dispatch._candidates([
            {'kind': 'map', 'name': '영양', 'path': '영양', 'id': 'm1'},
            {'kind': 'dashboard', 'name': '영양', 'path': 'dashboard > 영양', 'id': 'd1'},
            {'kind': 'tab', 'name': '영양', 'path': 'input tabs > 영양', 'id': 't1'}])
        self.assertEqual(['map > 영양', 'dashboard > 영양', 'input tabs > 영양'],
                         [c['path'] for c in got])
        self.assertIn('map > 영양', dispatch._kinds_said(
            [{'kind': 'map', 'name': '영양', 'path': '영양'}]))

    def test_reserved_names_cannot_be_passed_through(self):
        from aot.tools.domain import contract
        p1, p2 = _fake_gate()
        bad = _ops() + [Op('find', 'clash', 'x', {'none': 'get_sensor_reading'},
                           'read', extra_args={'op': 'inner op'})]
        with p1, p2, mock.patch('aot.tools.tool_registry.MCP_FACADES', {}), \
                mock.patch('aot.tools.tool_registry.ACTS_WITHOUT_SAVING', frozenset()):
            found = contract.problems(bad, _cat())
        self.assertTrue(any('collides with the domain' in p for p in found), found)


class FailClosedTest(unittest.TestCase):

    def test_registry_problem_switches_writes_off_but_not_reads(self):
        from aot.tools.domain import contract, dispatch
        with mock.patch.object(contract, 'problems', lambda *a, **k: ['broken']):
            self.assertFalse(contract.writes_enabled(refresh=True))
            verdict = dispatch.plan('control', {'op': 'device_set', 'target': 'x'},
                                    ops=_ops())
            self.assertEqual('refuse', verdict[0])
            self.assertIn('registry_check_failed', verdict[1][0]['text'])
            with mock.patch.object(dispatch.targets, 'resolve',
                                   lambda r, **kw: ('ok', {'kind': 'input', 'id': 'in-1',
                                                     'name': 'n', 'path': 'p'})):
                self.assertEqual('call', dispatch.plan(
                    'measure', {'op': 'latest', 'target': 'n'}, ops=_ops())[0])
        contract._STATE.clear()

    def test_check_crash_means_writes_off(self):
        from aot.tools.domain import contract
        def boom(*a, **k):
            raise RuntimeError('x')
        with mock.patch.object(contract, 'problems', boom):
            self.assertFalse(contract.writes_enabled(refresh=True))
        contract._STATE.clear()


class PlanSafetyTest(unittest.TestCase):
    """게이트 앞에서 거절되는가 — 실행 없이 판정만 본다."""

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        cat = _cat()
        p = mock.patch('aot.tools.domain.contract.catalog', lambda: cat)
        p.start()
        self.addCleanup(p.stop)

    def _plan(self, tool, args, resolve):
        from aot.tools.domain import dispatch
        with mock.patch.object(dispatch.targets, 'resolve', resolve):
            return dispatch.plan(tool, args, ops=_ops())

    @staticmethod
    def _one(kind, id_='id-1'):
        return lambda ref, **kw: ('ok', {'kind': kind, 'id': id_, 'name': ref,
                                   'path': 'map > ' + ref, 'matched': 'exact'})

    def test_write_with_several_targets_is_refused(self):
        v = self._plan('control', {'op': 'device_set', 'target': ['a', 'b'],
                                   'state': 'on'}, self._one('output'))
        self.assertEqual('refuse', v[0])
        self.assertIn('single_target_only', v[1][0]['text'])

    def test_write_with_a_container_never_fans_out(self):
        from aot.tools.domain import dispatch
        kid = {'kind': 'output', 'id': 'o-1', 'name': 'v1', 'path': 'm > s > v1'}
        with mock.patch.object(dispatch, '_children_of', lambda t: [kid]):
            v = self._plan('control', {'op': 'device_set', 'target': '김제',
                                       'state': 'off'}, self._one('map'))
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertEqual('target_kind_not_accepted', body['reason_code'])
        self.assertEqual(['o-1'], [c['id'] for c in body['candidates']])

    def test_ambiguous_target_is_not_picked(self):
        two = lambda ref, **kw: ('ambiguous', [{'kind': 'map', 'id': 'm', 'name': ref},
                                         {'kind': 'site', 'id': 's', 'name': ref}])
        v = self._plan('record', {'op': 'note_add', 'target': '영양', 'value': 'x'}, two)
        self.assertEqual('refuse', v[0])
        self.assertIn('ambiguous_target', v[1][0]['text'])

    def test_write_carries_resolved_id_and_snapshot(self):
        v = self._plan('record', {'op': 'note_add', 'target': '3-1', 'value': '진딧물'},
                       self._one('zone', 'zone-31'))
        self.assertEqual('call', v[0])
        _c, inner, args = v
        self.assertEqual('create_note', inner)
        self.assertEqual('zone-31', args['target_id'])
        self.assertEqual('진딧물', args['note'])
        self.assertEqual({'kind': 'zone', 'id': 'zone-31', 'name': '3-1',
                          'path': 'map > 3-1'}, args['_domain_target'])

    def test_read_has_no_snapshot_and_list_args_get_lists(self):
        v = self._plan('measure', {'op': 'latest', 'target': '3-1'},
                       self._one('zone', 'zone-31'))
        self.assertEqual(('call', 'get_zone_sensor_summary'), v[:2])
        self.assertEqual(['zone-31'], v[2]['zone_ids'])
        self.assertNotIn('_domain_target', v[2])

    def test_allowed_batch_keeps_its_own_list(self):
        v = self._plan('record', {'op': 'schedule_batch', 'entries': [{}, {}],
                                  'content': 'x'}, self._one('zone'))
        self.assertEqual(('call', 'add_schedule_batch'), v[:2])

    def test_unknown_argument_is_refused_not_dropped(self):
        v = self._plan('control', {'op': 'device_set', 'target': 'v1', 'state': 'on',
                                   'speed': 3}, self._one('output'))
        self.assertEqual('refuse', v[0])
        self.assertIn('unknown_argument', v[1][0]['text'])


class OneExitTest(unittest.TestCase):

    def test_run_calls_execute_tool_once_with_the_inner_name(self):
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        calls = []
        cat = _cat()
        with mock.patch('aot.tools.domain.contract.catalog', lambda: cat), \
                mock.patch.object(dispatch, '_ops', _ops), \
                mock.patch.object(dispatch.targets, 'resolve',
                                  lambda r, **kw: ('ok', {'kind': 'output', 'id': 'o-1',
                                                    'name': r, 'path': r})), \
                mock.patch('aot.tools.tool_execution._execute_tool',
                           lambda app, name, args, **k: calls.append((name, args)) or []):
            dispatch.run(None, 'control', {'op': 'device_set', 'target': 'v1',
                                           'state': 'on'}, role=None)
            dispatch.run(None, 'control', {'op': 'device_set', 'target': ['a', 'b'],
                                           'state': 'on'}, role=None)
        self.assertEqual(1, len(calls), calls)
        self.assertEqual('operate_device', calls[0][0])
        self.assertEqual('o-1', calls[0][1]['device_id'])

    def test_dispatch_module_has_no_other_execution_path(self):
        """처리기·게이트·승인을 직접 부르지 않는다 — `_execute_tool` 만."""
        from aot.tools.domain import dispatch
        tree = ast.parse(inspect.getsource(dispatch))
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else
                  getattr(n.func, 'id', None)
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        banned = {'_dispatch_virtual_tool', 'execute', 'gate', 'execute_approved',
                  'approve', '_run_gated_tool', 'handler'}
        self.assertFalse(called & banned, called & banned)


class StaleTargetTest(unittest.TestCase):

    def test_changed_target_stops_both_execution_paths(self):
        from aot.tools import mcp_safety_gate as gate
        params = {'note': 'x', '_domain_target': {'kind': 'zone', 'id': 'z',
                                                  'name': '3-1', 'path': 'p'}}
        with mock.patch('aot.tools.domain.targets.changed',
                        lambda s: 'the target no longer exists'):
            self.assertIn('no longer exists', gate.stale_target(params))
        with mock.patch('aot.tools.domain.targets.changed', lambda s: None):
            self.assertIsNone(gate.stale_target(params))
        self.assertIsNone(gate.stale_target({'note': 'x'}))
        # 처리기에는 스냅샷이 안 가고, 승인 스냅샷(비교 기준)에는 남는다.
        self.assertNotIn('_domain_target', gate.handler_args(params))
        self.assertIn('_domain_target', json.loads(gate._canonical_params(params)))

    def test_both_execution_sites_check_before_running(self):
        """승인 실행(execute_approved)과 직접 실행(_run_gated_tool) 둘 다
        처리기를 부르기 전에 stale_target 을 본다 — 소스 순서로 고정."""
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        for fn in (gate.execute_approved, te._run_gated_tool):
            src = inspect.getsource(fn)
            self.assertIn('stale_target(', src, fn.__name__)
            first_run = min(i for i in (src.find('_dispatch_virtual_tool('),
                                        src.find('.execute(')) if i >= 0)
            self.assertLess(src.find('stale_target('), first_run, fn.__name__)
            self.assertIn('handler_args(', src, fn.__name__)


if __name__ == '__main__':
    unittest.main()


class SurfaceListingTest(unittest.TestCase):
    """도구 목록(설계 §4·§6): 닿는 operation 만, 쓰기는 위험 표시, 고유 인자는 필수만."""

    def _entries(self, ok=lambda n: True, lite=False):
        from aot.tools.domain import surface
        return {e['name']: e for e in surface.entries(
            _ops(), ok, approval={'operate_device', 'delete_input'}, lite=lite)}

    def test_only_reachable_ops_and_tools_are_listed(self):
        got = self._entries(ok=lambda n: n != 'delete_input')
        self.assertNotIn('remove', got)          # 닿는 operation 이 없는 도구는 없다
        latest = self._entries(ok=lambda n: n != 'get_zone_sensor_summary')
        self.assertIn('latest', latest['measure']['inputSchema']['properties']['op']['enum'])

    def test_write_lines_carry_risk_and_required_args(self):
        got = self._entries()
        text = got['control']['description']
        self.assertIn('device_set', text)
        self.assertIn('physical', text)
        self.assertIn('approval', text)
        self.assertEqual({'title': 'Run devices', 'readOnlyHint': False,
                          'destructiveHint': False, 'openWorldHint': False},
                         got['control']['annotations'])
        self.assertEqual({'title': 'Sensor values', 'readOnlyHint': True},
                         got['measure']['annotations'])
        self.assertTrue(got['remove']['annotations']['destructiveHint'])

    def test_only_the_remove_tool_is_destructive(self):
        """claude.ai 는 표시로 허락 창을 정한다 — 파괴적인 도구는 '항상 허용' 이 먹지 않는다
        (2026-10-14). 지우기를 `remove` 하나에 모았으니 그것만 파괴적이고, 나머지 쓰기
        도구는 파괴적이지 않음을 **명시**한다(빠지면 MCP 기본값이 '파괴적' 이다)."""
        from aot.tools.domain import surface
        from aot.tools.domain.registry import WRITE_TOOLS
        from aot.tools.domain.registry_data import OPS
        got = {e['name']: e['annotations'] for e in surface.entries(OPS, lambda n: True, set())}
        for tool in WRITE_TOOLS:
            self.assertIs(tool == 'remove', got[tool]['destructiveHint'], tool)
            self.assertIs(False, got[tool]['readOnlyHint'], tool)
        for tool, ann in got.items():
            self.assertTrue(ann.get('title'), tool)
        deleting = sorted('%s.%s' % (o.tool, o.op) for o in OPS
                          if any(n.startswith(('delete_', 'remove_')) for n in o.inner.values()))
        self.assertTrue(deleting)
        self.assertTrue(all(d.startswith('remove.') for d in deleting), deleting)

    def test_optional_extra_args_are_left_to_help(self):
        got = self._entries()
        props = got['record']['inputSchema']['properties']
        self.assertNotIn('content', props)          # 선택 인자 — help 로
        self.assertIn('help(', got['record']['description'])


class AppContextTest(unittest.TestCase):
    """HTTP 서버는 dispatch 시점에 앱 컨텍스트 밖이다 — 대상 해석(DB)은 컨텍스트 안에서
    돌아야 한다(2026-10-14 벤치: 이름 해석이 전부 SQLAlchemy 오류)."""

    def test_plan_runs_inside_the_app_context(self):
        import contextlib
        from aot.tools.domain import dispatch
        state = {'inside': False, 'seen': None}

        class App:
            @contextlib.contextmanager
            def app_context(self):
                state['inside'] = True
                try:
                    yield
                finally:
                    state['inside'] = False

        def fake_plan(tool, args, ops=None, user=None, session=None):
            state['seen'] = state['inside']
            return 'refuse', []
        with mock.patch.object(dispatch, 'plan', fake_plan):
            dispatch.run(App(), 'measure', {'op': 'latest', 'target': 'x'})
        self.assertTrue(state['seen'])


class VocabularyRuleTest(unittest.TestCase):

    def test_a_name_given_as_query_is_the_target_when_the_op_has_no_query(self):
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        cat = _cat()
        seen = []
        def res(ref, **kw):
            seen.append(ref)
            return ('ok', {'kind': 'zone', 'id': 'z', 'name': ref, 'path': ref})
        with mock.patch('aot.tools.domain.contract.catalog', lambda: cat), \
                mock.patch.object(dispatch.targets, 'resolve', res):
            v = dispatch.plan('measure', {'op': 'latest', 'query': '3-1'}, ops=_ops())
        self.assertEqual('call', v[0], v)
        self.assertEqual(['3-1'], seen)

    def _functions(self, args, resolve):
        from aot.tools.domain import contract, dispatch
        from aot.tools.domain.registry_data import OPS
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        cat = {'get_function_list': {'inputSchema': {'type': 'object', 'properties': {
            k: {'type': 'string'} for k in ('query', 'function_type', 'active_only', 'limit', 'offset')}}}}
        ops = [o for o in OPS if (o.tool, o.op) == ('find', 'functions')]
        with mock.patch('aot.tools.domain.contract.catalog', lambda: cat), \
                mock.patch.object(dispatch.targets, 'resolve', resolve), \
                mock.patch.object(dispatch, '_place_keys', lambda r: {'fac-3'}), \
                mock.patch.object(dispatch, '_ancestors', lambda t: []):
            return dispatch.plan('find', dict(args, op='functions'), ops=ops)

    def test_a_place_given_as_query_filters_a_place_list(self):
        # 실사용 26-11-07~09: find.functions 에 query='3포장' → "does not take query" 거절.
        res = lambda ref, **kw: ('ok', {'kind': 'facility', 'id': 'f', 'name': ref, 'path': ref})
        v = self._functions({'query': '3포장'}, res)
        self.assertEqual(('filter', 'get_function_list'), v[:2], v)
        self.assertNotIn('query', v[2])
        self.assertEqual('facility_id', v[3]['place_key'])

    def test_a_word_that_is_no_place_is_a_name_part(self):
        res = lambda ref, **kw: ('none', {'error': 'Nothing named'})
        v = self._functions({'query': 'VPD'}, res)
        self.assertEqual(('call', 'get_function_list'), v[:2], v)
        self.assertEqual('VPD', v[2]['query'])


class VocabTest(unittest.TestCase):
    """공통 어휘의 해석은 한 곳(domain/vocab.py) — 설계 §3."""

    def test_everyday_measurement_words_map_to_stored_names(self):
        from aot.tools.domain import vocab
        have = {'temperature', 'volumetric_water_content', 'rain', 'length', 'light'}
        self.assertEqual('volumetric_water_content', vocab.measurement('soil_moisture', have))
        self.assertEqual('volumetric_water_content', vocab.measurement('토양수분', have))
        self.assertEqual('rain', vocab.measurement('강수량', have))
        self.assertEqual('length', vocab.measurement('rain', {'length'}))
        self.assertEqual('temperature', vocab.measurement('temperature', have))
        self.assertEqual('ec', vocab.measurement('ec', have))      # 모르는 말은 그대로

    def test_period_grammar(self):
        from datetime import date
        from aot.tools.domain import vocab
        today = date(2026, 10, 14)       # 수요일
        self.assertEqual((today, today), vocab.period('today', today))
        self.assertEqual((date(2026, 10, 15),) * 2, vocab.period('tomorrow', today))
        self.assertEqual((date(2026, 10, 12), date(2026, 10, 18)),
                         vocab.period('this_week', today))
        self.assertEqual((date(2026, 10, 14), date(2026, 10, 16)),
                         vocab.period('2026-10-14/2026-10-16', today))
        self.assertEqual((date(2026, 10, 7), today), vocab.period('7d', today))
        self.assertIsNone(vocab.period('someday', today))
        self.assertTrue(vocab.in_period('2026-10-14T09:00:00+09:00',
                                        vocab.period('2026-10-14', today)))
        self.assertFalse(vocab.in_period('2026-10-15T09:00:00+09:00',
                                         vocab.period('2026-10-14', today)))


class ReadReachTest(unittest.TestCase):
    """읽기의 닿는 규칙(§2-3): 작은 것은 감싸는 장소로 올리고, 장소는 그 안의 장치로
    내리고, 대상 없이 도는 목록은 그 장소의 장치로 거른다. 쓰기에는 하나도 안 된다."""

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        cat = dict(_cat())
        cat['get_output_state'] = {'inputSchema': {'type': 'object', 'properties': {
            'device_ids': {'type': 'array', 'items': {'type': 'string'}}}}}
        cat['get_device_list'] = {'inputSchema': {'type': 'object', 'properties': {}}}
        p = mock.patch('aot.tools.domain.contract.catalog', lambda: cat)
        p.start()
        self.addCleanup(p.stop)
        self.ops = _ops() + [
            Op('measure', 'output_state', 'x', {'output': 'get_output_state'}, 'read',
               target_arg={'output': 'device_ids'}),
            Op('find', 'device_list', 'x', {'none': 'get_device_list'}, 'read'),
        ]

    def _plan(self, tool, args, kind, **patches):
        from aot.tools.domain import dispatch
        res = lambda ref, **kw: ('ok', {'kind': kind, 'id': 'T', 'name': ref, 'path': ref})
        with mock.patch.object(dispatch.targets, 'resolve', res), \
                mock.patch.multiple(dispatch, **patches):
            return dispatch.plan(tool, args, ops=self.ops)

    def test_facility_reads_for_the_zone_that_contains_it(self):
        zone = {'kind': 'zone', 'id': 'z-1', 'name': '3-1', 'path': '3포장 > 3-1'}
        v = self._plan('measure', {'op': 'latest', 'target': '육묘장3'}, 'facility',
                       _ancestors=lambda t: [zone])
        self.assertEqual(('fanout', 'get_zone_sensor_summary'), v[:2])
        self.assertEqual(['z-1'], v[2][0][1]['zone_ids'])
        self.assertIn('read_for', v[3])

    def test_place_reads_the_devices_inside_in_one_call(self):
        devs = [{'kind': 'output', 'id': 'o%d' % i, 'name': 'v%d' % i, 'path': 'v'}
                for i in range(3)]
        v = self._plan('measure', {'op': 'output_state', 'target': '3포장'}, 'site',
                       _device_ids_in=lambda t: ['o0', 'o1', 'o2'],
                       _device_targets=lambda ids, kinds: devs)
        self.assertEqual(('fanout', 'get_output_state'), v[:2])
        self.assertEqual(['o0', 'o1', 'o2'], v[2][0][1]['device_ids'])

    def test_list_op_with_a_place_filters_to_its_devices(self):
        v = self._plan('find', {'op': 'device_list', 'target': '3포장'}, 'site',
                       _device_ids_in=lambda t: ['o1'])
        self.assertEqual(('filter', 'get_device_list'), v[:2])
        self.assertEqual(['o1'], v[3]['ids'])
        from aot.tools.domain import dispatch
        out = [{'type': 'text', 'text': json.dumps(
            {'count': 2, 'devices': [{'id': 'o1', 'name': 'a'}, {'id': 'o9', 'name': 'b'}]})}]
        body = json.loads(dispatch._filter_ids(out, dict(v[3]))[0]['text'])
        self.assertEqual(['o1'], [d['id'] for d in body['devices']])
        self.assertEqual(1, body['count'])

    def test_writes_never_reach_up_or_down(self):
        zone = {'kind': 'zone', 'id': 'z-1', 'name': '3-1', 'path': 'p'}
        v = self._plan('control', {'op': 'device_set', 'target': '3포장', 'state': 'on'},
                       'site', _ancestors=lambda t: [zone],
                       _device_ids_in=lambda t: ['o1'], _children_of=lambda t: [])
        self.assertEqual('refuse', v[0])


#: 도메인 표면 목록 크기 — 상한(사용자 결정 2026-10-14, 같은 날 9,000·15,000 으로 올림)과 래칫(설계 §4·§7). 앱 없이
#: 카탈로그로 잰 관리자 키 기준(역할로 숨기는 것 없음). 첫 기록: 운영 7,596 · 설정 12,277
#: (지금 표면 21,886 · 42,649). 가벼움은 운영과 합쳤다 — 같은 목록이다.
#: 2026-10-14 경로 표기('place > name')를 target 설명에 넣으며 문구를 줄여 7,536 · 12,211.
#: 2026-10-14 동작에 꼭 필요한 고유 인자(`shown` — 화면 조작의 action·page·confirm_token,
#: 고치기의 바꿀 내용)를 스키마에 실어 7,910 · 12,793. 모델이 스키마에 없는 인자를 넣지
#: 않아 화면 이동이 끝내 안 됐다(사용자 시험) — 일부러 올린 값이다.
#: 2026-10-14 화면 조작에 대상만 주면 보여 준다는 안내(screen 머리)로 7,953 · 12,836.
#: 2026-10-14 사용자 결정 — 상한 9,000 · 15,000(옛 표면 20,000 · 40,000 에 비하면 여전히
#: 작다). 너무 줄인 설명에 AI 가 혼란스러워해서, 늘어난 여유로 동작에 꼭 필요한 고유
#: 인자를 스키마에 실었다(일정·메모 쓰기, 단계 옮기기, 구획 include_ended, 만들기의 핵심
#: 필드 …) → 8,709 · 14,224. 세부 조정(구획 나누기 폭, 자료원 12개 인자 …)은 help 로.
#: 지우기를 `remove` 도구로 떼어 냈다(2026-10-14 사용자 결정 — 나머지 쓰기 도구에 '항상
#: 허용' 이 먹게) → 도구 하나의 머리·스키마만큼 늘어 8,929 · 14,506.
#: 리허설 첫 접촉 결함(사진 파일 이름을 스키마에) → 8,959 · 14,547.
#: 상한은 사람이 정한 선이다. 래칫은 의도 없이 느는 것을 막는다 — 늘리는 것이 맞다면
#: DOMAIN_MEASURED 를 **일부러** 고친다(상한 안에서).
#: 2026-10-22 사용자 결정 — 운영 상한을 9,000 → 10,000 으로 올렸다(screen.card 전용 작업: AI 가 'post' 를
#: 카드로 알아보지 못해 "카드로 띄워 줘" 에 화면 이동만 했다 → 이름이 분명한 작업으로 분리).
DOMAIN_CEILING = {'operations': 10000, 'configuration': 15000}
# 2026-10-19: +12 — 노트 사진 filename 설명에 '첨부가 하나면 생략 가능' 을 더했다
# (필수에서 빠지고 shown 으로 옮겨 스키마에는 그대로 남는다). 상한 안.
# 2026-10-22: +96 · +96 — screen.card(작업 한 줄·title/message 스키마). 상한 안(운영은 위 사용자 결정).
# 2026-10-26: 진입 도구(overview·help) 머리에 "사용자 언어로만, 도구·단계 서술 금지" 한 줄씩(+~28)을 넣고,
# 각 도구 끝의 'More arguments per op' 포인터를 'More args' 로 줄여 상쇄했다 → 9,066 · 14,642(-1 · -13).
# claude.ai 커넥터는 서버 안내문을 모델에 주지 않아 첫 한마디가 영어로 나왔다 — 호출 전에 닿는 곳은 도구 설명뿐.
# 2026-10-28: +117 · +114 — weather.forecast 의 `focus`(enum)와 screen 의 `screen` 을 스키마에 올렸다. 둘 다 `use`·extra_args 에만 있어 AI 가
# 스키마에 없는 인자를 넣지 않던 것이 지도 시간이 안 옮겨진 원인 중 하나였다(10-27 대화 기록). 상한 안(상한은 올리지 않았다).
# 2026-11-03 재설계 PR 1: `_show_on_screen` 을 measure·detail 스키마에 올렸다(+82 · +82, 사고가 난 읽기 두 도구) 그리고
# 같은 PR 에서 긴 `use` 줄 11개를 줄여 상쇄 → 9,196 · 14,777(측정값; 직전 origin/main 9,202 · 14,801 — S1 점검 병합 뒤).
# 2026-11-03 재설계 PR 2: 공통 어휘 `text title duration state offset samples` 를 VOCAB_SCHEMA 에 올리고 op 별로 흩어져 있던
# 본문·길이 인자(note·body·content·message·advice·guidance, duration_seconds·minutes, active·enabled)를 그 한 벌로 합쳤다
# → 9,001 · 14,478(직전 9,196 · 14,777). 옛 이름은 `renames` 별칭이 받아 스키마 토큰이 0이다.
# 2026-11-03 재설계 PR 3: 쉬운 합치기 — summary·crops·active_functions·device_location·distance·device_list·maps·journal·
# input_activate+gis_input_activate 를 옆 op 로(옛 이름은 별칭) → 8,772 · 14,122(직전 9,001 · 14,478).
# 2026-11-03 재설계 PR 4: 위치 조회(find.nearest·address)와 공지 고치기·지우기(record.notice_edit·remove.notice_delete)를 도메인 운영으로
# 올렸다 → 운영 9,011(+239, PR 3 의 −229 와 거의 상쇄해 PR 2 의 9,001 근처) · 설정 14,136(+14, address 의 VWorld 안내).
# 2026-11-03 재설계 PR 5(노트): record.note_add·note_edit·note_tier → record.note 한 op, remove.note_delete 추가, records.notes 가 노트 id·숨긴
# 노트를 읽음 → 설정 14,034(-102) · 운영 8,999(-12; 새 op 줄을 다른 설명 줄 다듬기로 상쇄). 옛 카탈로그는 delete_note(+176)를 효과 없는
# set_document_tier(-236)로 상쇄해 43,296 → 43,250.
# 2026-11-03 재설계 PR 6(안쪽 선택 훅 Op.pick_by_arg): function_on·off → function_set(state), schedule_add_batch → schedule_add(entries),
# cultivate.stage_* 다섯 → stage(action) → 운영 8,904(-95) · 설정 13,732(-302).
# 2026-11-03 재설계 PR 7(종류별 합치기): remove.*_delete 14 → remove.delete(kind), configure.*_edit 6 → configure.edit(kind)
# → 운영 8,879(-25) · 설정 12,881(-851).
# 2026-11-03 재설계 PR 8(출처 일반화): records.smartfarmkorea 삭제, configure.library_source_configure(전용 인자 15개) → configure.library_source
# (params 한 객체, api_key 없음) → 설정 12,786(-95) · 운영 8,877(-2; data_source 줄이 늘어난 만큼 다른 설명 줄 다듬기). 옛 카탈로그 43,250 → 43,182.
# 2026-11-03 S4: 응답 줄이기(fields·limit 낱말은 기존 것 재사용)·날짜 범위는 period·시각 창은 window_*(start/end 설명이 필수 칸에서 빠짐)
# → 설정 12,730(-56) · 운영 8,830(-47)(measure 3건 손질로 늘어난 설명은 다른 use 줄 다듬기로 상쇄). 옛 카탈로그는 안쪽 도구를 안 건드려 그대로.
# 2026-11-09 claude.ai 점검: 설명이 말하는 인자(weather·find 의 detail, screen.card 의 card·attach)를 스키마에 올리고
# a|b|c 나열 인자를 enum 으로 — 같은 뜻을 되풀이하던 use 줄 꼬리(detail=true …, card=<id> …)는 뺐다 → 운영 9,025 · 설정 12,757.
DOMAIN_MEASURED = {'operations': 9025, 'configuration': 12757}
DOMAIN_SLACK = 1.03


def _domain_tokens(prof):
    from aot.tools import tool_registry as R
    from aot.tools import tool_execution as te
    from aot.tools.domain import surface
    from aot.tools.domain.registry_data import OPS
    p = te._effective_profile(prof)
    ent = surface.entries(OPS, lambda n: R.tool_in_profile(n, p, via_domain=True),
                          set(R.approval_required_tools()))
    return ent, te._estimate_tokens(json.dumps(te.model_view(ent), ensure_ascii=False))


class DomainSurfaceArgsMentionedAreInSchemaTest(unittest.TestCase):
    """설명이 `x=...` 로 부르라고 한 인자는 그 도구 스키마에 있어야 한다 — 선택 인자를 목록에서 뺀(help 로 넘긴)
    뒤 설명에 `detail=true`·`card=<id>` 가 남아, claude.ai 가 "없는 인자를 쓰라고 한다" 고 읽었다(2026-11-09 점검 8번)."""

    def test_every_arg_a_description_names_is_in_the_schema(self):
        import re
        for prof in DOMAIN_CEILING:
            ent, _ = _domain_tokens(prof)
            for e in ent:
                props = e['inputSchema']['properties']
                texts = [e['description']] + [v.get('description', '') for v in props.values()]
                if e['name'] == 'help':
                    continue
                for t in texts:
                    t = re.sub(r"help\(target='[^']*'\)", '', t)      # 'More args: help(...)' 는 help 의 인자
                    for word in re.findall(r'(?<![\w.])([a-z_]+)=', t):
                        self.assertIn(word, props, '%s/%s: 설명이 %s= 를 말하는데 스키마에 없다' % (
                            prof, e['name'], word))
                    for tool, arg in re.findall(r'\b([a-z_]+)\.[a-z_]+\(([a-z_]+)=', t):
                        other = next((x for x in ent if x['name'] == tool), None)
                        if other is not None:
                            self.assertIn(arg, other['inputSchema']['properties'],
                                          '%s: %s 의 %s= 는 없는 인자다' % (e['name'], tool, arg))

    def test_detail_takes_a_list_so_the_header_does_not_say_one(self):
        ent, _ = _domain_tokens('configuration')
        d = next(e for e in ent if e['name'] == 'detail')
        self.assertNotIn('ONE ', d['description'])
        self.assertIn('a list for several', d['inputSchema']['properties']['target']['description'])

    def test_word_lists_are_enums(self):
        ent, _ = _domain_tokens('configuration')
        screen = next(e for e in ent if e['name'] == 'screen')['inputSchema']['properties']
        self.assertIn('map_control', screen['action']['enum'])
        self.assertNotIn('not the action', json.dumps(screen))


class HelpSpeaksThisSurfaceTest(unittest.TestCase):
    """help 는 안쪽 도구 설명을 보여 주되, 그 안의 안쪽 인자 이름·다른 op 몫의 값은 이 표면 것으로(2026-11-09 재점검)."""

    def test_inner_arg_names_in_help_are_this_surfaces_names(self):
        from aot.tools.domain.dispatch import help_card
        day = help_card('control.sequence_step')['other_args']['day']['description']
        self.assertNotIn('duration_seconds', day)
        self.assertNotIn('enabled', day)
        self.assertIn('state', day)

    def test_screen_act_action_lists_only_its_own_values(self):
        from aot.tools.domain.dispatch import help_card
        card = help_card('screen.act')
        self.assertNotIn('post', card['other_args']['action']['enum'])
        self.assertNotIn('post', card['action_target_pairs'])


class DomainSurfaceBudgetTest(unittest.TestCase):

    def test_domain_list_stays_under_the_ceiling_and_does_not_grow_silently(self):
        for prof, ceiling in DOMAIN_CEILING.items():
            ent, tokens = _domain_tokens(prof)
            self.assertEqual(14, len(ent), prof)
            self.assertLessEqual(tokens, ceiling,
                                 '%s 도메인 목록 %d — 상한 %d(사용자 결정)를 넘었다' %
                                 (prof, tokens, ceiling))
            self.assertLessEqual(
                tokens, int(DOMAIN_MEASURED[prof] * DOMAIN_SLACK),
                '%s 도메인 목록이 %d 추정 토큰이다(기록 %d). operation 을 더했거나 설명이 '
                '길어졌다 — 의도한 것이면 DOMAIN_MEASURED 를 고친다.' % (
                    prof, tokens, DOMAIN_MEASURED[prof]))

    def test_entry_tools_carry_the_language_and_no_narration_rule(self):
        """안내문이 안 닿는 호스트(claude.ai 커넥터)도 호출 전에 보는 도구 설명에 규칙이 있다 — 진입 도구 overview 한 곳에,
        응답 계약(next·say) 규약과 함께(2026-10-29 행동·말하기 나누기). 다른 도구 머리는 '언제 부르나' 만 적는다."""
        ent, _ = _domain_tokens('operations')
        by = {e['name']: e['description'] for e in ent}
        self.assertIn('in their language', by['overview'])
        self.assertIn('Never narrate tools', by['overview'])
        self.assertIn('never spoken', by['overview'])
        self.assertNotIn('narrate', by['help'])

    def test_lite_is_merged_into_operations(self):
        """가벼움 키는 도메인 표면에서 운영과 같은 목록을 받는다."""
        from aot.tools.domain import surface
        from aot.tools import tool_registry as R
        got = {}
        for prof in (R.TOOL_PROFILE_LITE, R.TOOL_PROFILE_OPERATIONS):
            with mock.patch('aot.tools.tool_execution._hidden_tools', lambda role: set()):
                got[prof] = surface.for_key(None, None, prof)
        self.assertEqual(json.dumps(got[R.TOOL_PROFILE_OPERATIONS], sort_keys=True),
                         json.dumps(got[R.TOOL_PROFILE_LITE], sort_keys=True))


class VerifiedNameTest(unittest.TestCase):
    """이름만 받는 안쪽 인자에는 같은 대상으로 되돌아오는 이름만 넘긴다(벤치 f32:
    uuid 를 넘기자 안쪽 해석이 다른 구역으로 풀었다)."""

    def test_name_must_round_trip_to_the_same_id(self):
        from aot.tools.domain import dispatch
        t = {'kind': 'zone', 'id': 'z-31', 'name': '3-1', 'path': '김제 > 3포장 > 3-1',
             'map': '김제'}
        table = {'3-1': ('z-other',), '김제 3-1': ('z-31',)}
        with mock.patch('aot.tools.aot_data_tool_service.AoTDataToolService.'
                        '_resolve_note_target',
                        lambda n: table.get(n, (None,))):
            self.assertEqual('김제 3-1', dispatch._verified_name(t))
        with mock.patch('aot.tools.aot_data_tool_service.AoTDataToolService.'
                        '_resolve_note_target', lambda n: ('z-other',)):
            self.assertIsNone(dispatch._verified_name(t))


class ModalTabHintTest(unittest.TestCase):
    def test_hint_mentions_underlying_dialog_for_drawer(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        hint = dispatch._kinds_by_arg_hint(find_op(OPS, 'screen', 'act'))
        self.assertIn('dialog_tabs', hint)
        self.assertIn('underlying_dialog', hint)


class FirstContactTest(unittest.TestCase):
    """처음 붙은 모델이 걸린 자리(2026-10-14 리허설) — 명부로 고정한다."""

    def test_place_crops_read_the_plots_of_that_place(self):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'find', 'plots')               # overview.crops 는 find.plots 로 합쳐졌다(재설계 PR 3)
        for kind in ('map', 'site', 'zone'):
            self.assertEqual('list_plots', o.inner[kind], kind)
        self.assertEqual('get_crop_status', o.inner['facility'])

    def test_note_photo_filename_is_in_the_schema(self):
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        got = {e['name']: e for e in surface.entries(OPS, lambda n: True, set())}
        self.assertIn('filename', got['records']['inputSchema']['properties'])

