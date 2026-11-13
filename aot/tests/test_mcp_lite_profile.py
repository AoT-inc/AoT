# coding=utf-8
"""가벼움(lite) 묶음 — 무료 요금제에서 대화 한도가 질문 한두 개로 차지 않게.

실제 대화 35개 계산(2026-10-10)에서 대화당 입력의 53~70% 가 매 요청 실리는 도구
목록이었다. 가벼움은 **할 수 있는 일은 운영과 같고 처음 싣는 목록만 작다**:

  1. 목록은 LITE_LISTED 뿐이고, 크기는 상한(5,000 추정 토큰) 안이다.
  2. 목록 밖 운영 도구도 부를 수 있다(use_tool·직접 호출) — 거절하면 기능이 사라진다.
  3. read_tool·use_tool 의 **설명**이 목록 밖 운영 도구의 이름을 싣는다 — 이름이
     안 보이면 모델은 "못 한다" 로 결론짓는다(서랍 실험). 안내문(instructions)이
     아니라 설명에 싣는 것은 claude.ai 가 안내문을 모델에 주지 않는 것으로
     보였기 때문이다(2026-10-10 파일럿).
  5. 상세 조회·서랍은 가벼움의 좁은 목록에 묶이지 않는다(파일럿: get_tool_detail
     ('get_plot') 이 실패했다).
  6. 읽기 도구에는 읽기 전용 표시를 붙이고, read_tool 은 쓰기 도구를 거부한다.
  4. 연결 주소 `?tools=lite` 는 좁히기만 한다.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from aot.tests.test_mcp_tool_profiles import CFG, OPS, R, _AppFixture, _PREFIX

LITE = 'lite'
#: 5,000 → 5,100(2026-10-10): get_screen 을 목록에 올렸다 — "이 화면" 을 말하는
#: 사용자는 도구 이름을 모른다(사용자 결정). 다른 도구를 올릴 때 이 여유를 쓰지 말 것.
LITE_TOKEN_CEILING = 5_100


class LiteProfileValueTest(unittest.TestCase):

    def test_value_round_trips(self):
        from aot.databases.models import user_api_key as K
        self.assertIn(LITE, R.TOOL_PROFILES)
        self.assertEqual(tuple(R.TOOL_PROFILES), tuple(K.TOOL_PROFILES))
        self.assertEqual(LITE, R.parse_tool_profile(LITE))
        self.assertEqual(LITE, R.normalize_tool_profile(LITE))
        self.assertEqual(LITE, R.profile_from_storage(LITE, 'plots,map'))
        self.assertEqual((LITE, None), K.tool_profile_columns(LITE, ['plots']))

    def test_reaches_exactly_what_operations_reaches(self):
        self.assertEqual(R.profile_tools(OPS), R.profile_tools(LITE))
        self.assertEqual(frozenset(), R.profile_modules(LITE))

    def test_listed_tools_are_operations_tools(self):
        for name in R.LITE_LISTED - {'use_tool', 'get_tool_detail', 'read_tool'}:
            self.assertTrue(R.tool_in_profile(name, OPS), name)


class LiteListingTest(_AppFixture):

    def _lite_role(self, who='Editor'):
        return self._auth(self._issue(who, 'full', LITE))

    def _tools(self, role):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        return te._get_all_tools(self.app, role=role,
                                 profile=mcp_auth.tool_profile_of(role))

    def test_only_the_lite_set_is_listed(self):
        names = {t['name'] for t in self._tools(self._lite_role())}
        self.assertLessEqual(names, R.LITE_LISTED)
        for must in ('get_place_overview', 'operate_device', 'use_tool',
                     'get_tool_detail', 'respond_to_confirmation'):
            self.assertIn(must, names)

    def test_host_size_is_under_the_ceiling(self):
        from aot.tools import tool_execution as te
        tools = self._tools(self._lite_role('Admin'))
        tokens = (te._estimate_tokens(json.dumps(te.model_view(tools),
                                                 ensure_ascii=False))
                  + te._estimate_tokens(te._server_instructions(LITE)))
        self.assertLessEqual(tokens, LITE_TOKEN_CEILING, tokens)

    def test_delegate_descriptions_name_every_unlisted_operations_tool(self):
        from aot.tools import tool_execution as te
        tools = {t['name']: t for t in self._tools(self._lite_role('Admin'))}
        reads, writes = (tools['read_tool']['description'],
                         tools['use_tool']['description'])
        # 도메인 전용 안쪽 도구(DOMAIN_ONLY_TOOLS)는 옛 목록·색인 어디에도 싣지 않는다. 도메인 운영으로 올린 도구
        # (DOMAIN_PROMOTED_TOOLS, 재설계 PR 4)도 원래 모듈이 꺼진 옛 묶음에서는 목록·색인 어디에도 없다 — 이 키에서 못 쓰는 도구다.
        for name in (R.profile_tools(OPS) - R.LITE_LISTED - R.DOMAIN_ONLY_TOOLS
                     - R.legacy_hidden_tools(OPS)):
            if R.mcp_profile_of(name) != OPS:
                continue
            if te._is_reading(name):
                self.assertIn(name, reads)
                self.assertNotIn(name + ',', writes)
            else:
                self.assertIn(name, writes)
        for text in (reads, writes):
            self.assertNotIn('create_function', text)  # 설정 모듈 도구

    def test_names_are_not_repeated_in_instructions(self):
        from aot.tools import tool_execution as te
        text = te._server_instructions(LITE)
        self.assertNotIn('search_schedule', text)
        self.assertIn('read_tool', text)

    def test_instructions_speak_domain_names_unless_legacy(self):
        from aot.tools import tool_execution as te
        with mock.patch.dict(os.environ, {'AOT_MCP_SURFACE': ''}):
            text = te._server_instructions(LITE)
            for old in ('read_tool', 'use_tool', 'get_tool_detail',
                        'get_place_overview', 'set_tool_profile'):
                self.assertNotIn(old, text)
            self.assertIn('overview', text)
            self.assertIn('configure.tool_profile_set', text)
        with mock.patch.dict(os.environ, {'AOT_MCP_SURFACE': 'legacy'}):
            self.assertIn('read_tool', te._server_instructions(LITE))

    def test_write_index_hides_tools_the_role_cannot_use(self):
        tools = {t['name']: t for t in self._tools(self._lite_role('Monitor'))}
        self.assertIn('read_tool', tools)
        use = tools.get('use_tool')
        if use is not None:
            self.assertNotIn('create_notice', use['description'])

    def test_detail_and_drawer_see_unlisted_operations_tools(self):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        role = self._lite_role()
        full = {t['name'] for t in te._get_all_tools(
            self.app, role=role, tiered=False,
            profile=mcp_auth.tool_profile_of(role), facades=False)}
        for name in ('get_plot', 'search_schedule', 'create_note', 'list_notices'):
            self.assertIn(name, full)
        self.assertNotIn('create_function', full)      # 설정 모듈은 그대로 밖
        body = self._call(role, 'get_tool_detail', {'tool_name': 'get_plot'})
        self.assertNotEqual('error', body.get('status'), body)
        self.assertNotIn('error', body, body)

    def test_read_tools_carry_the_read_only_hint(self):
        tools = {t['name']: t for t in self._tools(self._lite_role('Admin'))}
        hint = lambda n: (tools[n].get('annotations') or {}).get('readOnlyHint')
        for name in ('get_place_overview', 'get_sensor_reading', 'list_plots',
                     'get_tool_detail', 'read_tool'):
            self.assertIs(True, hint(name), name)
        for name in ('operate_device', 'use_tool', 'respond_to_confirmation'):
            self.assertIsNone(hint(name), name)

    def test_read_tool_refuses_writes_and_runs_reads(self):
        from aot.tools import tool_execution as te
        role = self._lite_role()
        # screen_action 은 저장하지 않지만 화면을 바꾼다 — 읽기 도구가 아니다.
        for name in ('create_note', 'operate_device', 'notice', 'use_tool',
                     'screen_action'):
            body = self._call(role, 'read_tool',
                              {'tool_name': name, 'arguments': {}})
            self.assertIn('read_tool runs read-only tools only',
                          json.dumps(body, ensure_ascii=False), (name, body))
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success', 'ok': 1}):
            body = self._call(role, 'read_tool',
                              {'tool_name': 'get_spatial_tree', 'arguments': {}})
        self.assertEqual(1, body.get('ok'), body)

    def test_lite_responses_are_capped_lower(self):
        from aot.tools import tool_execution as te
        # 캡은 결과를 제자리에서 고치므로 호출마다 새로 만든다.
        def big(*_a, **_k):
            return {'status': 'success',
                    'items': [{'name': 'x%d' % i, 'blob': 'y' * 200}
                              for i in range(400)]}
        with mock.patch.object(te, '_dispatch_virtual_tool', side_effect=big):
            lite = self._call(self._lite_role(), 'read_tool',
                              {'tool_name': 'get_spatial_tree', 'arguments': {}})
        lite_tokens = te._estimate_tokens(json.dumps(lite, ensure_ascii=False))
        self.assertLessEqual(lite_tokens, te._LITE_MAX_RESPONSE_TOKENS)
        self.assertIn('_truncated', lite)
        with mock.patch.object(te, '_dispatch_virtual_tool', side_effect=big):
            ops = self._call(self._auth(self._issue('Editor', 'full', OPS)),
                             'get_spatial_tree', {})
        self.assertGreater(len(ops['items']), len(lite['items']))

    def test_screen_action_is_reachable_but_not_marked_read_only(self):
        tools = {t['name']: t for t in self._tools(self._lite_role('Editor'))}
        self.assertIn('get_screen', tools)                      # 목록에 직접
        self.assertIn('screen_action', tools['use_tool']['description'])
        self.assertNotIn('screen_action', tools['read_tool']['description'])
        ops = {t['name']: t for t in self._tools(
            self._auth(self._issue('Editor', 'full', OPS)))}
        self.assertIn('screen_action', ops)
        self.assertIsNone((ops['screen_action'].get('annotations') or {})
                          .get('readOnlyHint'))
        self.assertIs(True, ops['get_screen']['annotations']['readOnlyHint'])

    def test_screen_action_lists_open_notes_on_the_mcp_path(self):
        """MCP 로 실제 나가는 screen_action 스키마(운영 키)에 open_notes 가 있고,
        그 값이 처리기의 허용 동작과 어긋나지 않는다(외부 AI 가 노트창을 열 수 있다)."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from aot.tools.tool_registry import build_tool_map
        ops = {t['name']: t for t in self._tools(
            self._auth(self._issue('Editor', 'full', OPS)))}
        enum = ops['screen_action']['inputSchema']['properties']['action']['enum']
        self.assertIn('open_notes', enum)
        self.assertEqual(set(enum), set(S._SCREEN_ACTIONS))
        self.assertIn('screen_action', build_tool_map())
        self.assertIn('notes', ops['screen_action']['description'])

    def test_read_tool_is_lite_only(self):
        from aot.tools import tool_execution as te
        role = self._auth(self._issue('Editor', 'full', OPS))
        names = {t['name'] for t in self._tools(role)}
        self.assertNotIn('read_tool', names)

    def _call(self, role, tool, args):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, tool, args,
                               agent_id='user:%s' % _PREFIX.lower(), role=role,
                               scope_user_uuid=getattr(role, 'user_id', None),
                               transport='mcp_http',
                               tool_profile=mcp_auth.tool_profile_of(role))
        return json.loads(out[0]['text'])

    def test_unlisted_operations_tool_still_runs_setup_tool_is_refused(self):
        from aot.tools import tool_execution as te
        role = self._lite_role()
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success'}):
            body = self._call(role, 'use_tool',
                              {'tool_name': 'get_spatial_tree', 'arguments': {}})
            self.assertNotEqual('refused', body.get('status'), body)
            body = self._call(role, 'create_function',
                              {'name': 'x', 'function_type': 'y'})
        self.assertEqual('refused', body.get('status'), body)
        self.assertEqual('tool_profile', body.get('reason_code'))


class LiteArgHintTest(unittest.TestCase):
    """색인에 싣는 인자는 실제 스키마와 같아야 한다 — 어긋나면 모델이 없는 인자로
    부르고, 그 실패는 상세 조회를 아끼려던 왕복을 오히려 늘린다."""

    def test_hints_match_the_schema(self):
        from aot.tools import tool_execution as te
        for name, args in R.LITE_ARG_HINTS.items():
            schema = te._tool_schema(name)
            self.assertIsNotNone(schema, name)
            props = set((schema.get('properties') or {}))
            self.assertLessEqual(set(args), props, name)
            # 필수 인자를 빠뜨리면 그 서명만 보고 부른 호출이 실패한다.
            self.assertLessEqual(set(schema.get('required') or ()), set(args), name)

    def test_hinted_tools_are_in_the_lite_index(self):
        for name in R.LITE_ARG_HINTS:
            self.assertNotIn(name, R.LITE_LISTED, name)
            self.assertEqual(OPS, R.mcp_profile_of(name), name)

    def test_signature_marks_optional_args(self):
        from aot.tools import tool_execution as te
        self.assertEqual('create_note(note, name?, target_name?)',
                         te._lite_signature('create_note'))
        self.assertEqual('get_spatial_tree', te._lite_signature('get_spatial_tree'))


class LiteResponseCapRuleTest(unittest.TestCase):

    def test_cap_rule(self):
        from aot.tools import tool_execution as te
        with mock.patch.object(te, '_MAX_RESPONSE_TOKENS', 15000), \
                mock.patch.object(te, '_LITE_MAX_RESPONSE_TOKENS', 6000), \
                mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '1'}):
            self.assertEqual(6000, te._response_cap_for(LITE))
            self.assertEqual(15000, te._response_cap_for(OPS))
            self.assertEqual(15000, te._response_cap_for(None))
        # 끄는 수단은 둘 다 살아 있어야 한다.
        with mock.patch.object(te, '_MAX_RESPONSE_TOKENS', 0), \
                mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '1'}):
            self.assertEqual(0, te._response_cap_for(LITE))
        with mock.patch.object(te, '_MAX_RESPONSE_TOKENS', 15000), \
                mock.patch.object(te, '_LITE_MAX_RESPONSE_TOKENS', 0), \
                mock.patch.dict(os.environ, {'AOT_MCP_TOOL_PROFILES': '1'}):
            self.assertEqual(15000, te._response_cap_for(LITE))


class SharedPlotSensorsTest(unittest.TestCase):
    """구획 목록의 구역·기상 센서는 한 번만 — 같은 목록일 때만 올린다."""

    def _plot(self, zone, zsens, site='site-1', wsens=('w1', 'w2')):
        return {'unique_id': 'p-' + zone, 'sensors': {
            'in_plot': [], 'source': 'zone', 'zone_uuid': zone,
            'zone_name': zone.upper(), 'zone_kind': 'zone',
            'from_zone': list(zsens), 'weather_site_uuid': site,
            'from_weather': list(wsens), 'weather_source': 'inferred'}}

    def _hoist(self, items):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService._hoist_shared_sensors(items)

    def test_same_lists_are_given_once(self):
        items = [self._plot('z1', ['a', 'b']), self._plot('z1', ['a', 'b']),
                 self._plot('z2', ['c'])]
        out = self._hoist(items)
        self.assertEqual({'z1', 'z2'}, set(out['zone_sensors']))
        self.assertEqual(['a', 'b'], out['zone_sensors']['z1']['sensors'])
        self.assertEqual({'site-1'}, set(out['weather_sensors']))
        for p in items:
            s = p['sensors']
            self.assertNotIn('from_zone', s)
            self.assertNotIn('from_weather', s)
            self.assertEqual('zone', s['source'])       # 판정에 쓰는 값은 남는다
            self.assertIn('zone_uuid', s)
            self.assertIn('in_plot', s)
        self.assertIn('sensors_note', out)

    def test_differing_lists_stay_on_the_plot(self):
        items = [self._plot('z1', ['a', 'b']), self._plot('z1', ['a', 'x'])]
        self._hoist(items)
        self.assertNotIn('from_zone', items[0]['sensors'])
        self.assertEqual(['a', 'x'], items[1]['sensors']['from_zone'])

    def test_nothing_to_hoist_adds_nothing(self):
        self.assertEqual({}, self._hoist([{'unique_id': 'p', 'sensors': None}]))


class NarrowProfileTest(unittest.TestCase):

    def _role(self, profile):
        from aot.tools.mcp_auth import RoleInfo
        fields = {f: None for f in RoleInfo._fields}
        fields['tool_profile'] = profile
        return RoleInfo(**fields)

    def test_lite_narrows_any_key(self):
        from aot.tools.mcp_auth import narrow_profile
        for p in (OPS, CFG, 'operations+plots'):
            self.assertEqual(LITE, narrow_profile(self._role(p), 'lite').tool_profile)

    def test_other_values_never_widen(self):
        from aot.tools.mcp_auth import narrow_profile
        role = self._role(OPS)
        for v in (None, '', 'configuration', 'unrestricted', 'all'):
            self.assertIs(role, narrow_profile(role, v))
        self.assertIsNone(narrow_profile(None, 'lite'))

    def test_http_and_stdio_entry_points_apply_it(self):
        import inspect
        from aot import aot_mcp_server
        src = inspect.getsource(aot_mcp_server)
        self.assertGreaterEqual(src.count('narrow_profile(role, request.args.get("tools"))'), 3)
        self.assertIn('os.environ.get("AOT_MCP_TOOLS")', src)


class PlaceOverviewAggregationTest(unittest.TestCase):
    """장소 요약의 센서 집계 — 예보·출력·방위는 섞지 않는다(앱 없이)."""

    def _S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def test_sensor_aggregation_rules(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        fresh = (now - timedelta(minutes=5)).isoformat()
        old = (now - timedelta(hours=5)).isoformat()
        summary = {'zones': [{'sensors': [
            {'device_name': 'a', 'last_time': fresh, 'channels': [
                {'measurement': 'temperature', 'unit': 'C', 'last_value': 20.0},
                {'measurement': 'direction', 'unit': 'bearing', 'last_value': 350}]},
            {'device_name': 'b', 'last_time': fresh, 'channels': [
                {'measurement': 'temperature', 'unit': 'C', 'last_value': 24.0}]},
            {'device_name': 'forecast', 'last_time': fresh, 'data_origin': 'model',
             'channels': [{'measurement': 'temperature', 'unit': 'C', 'last_value': 99}]},
            {'device_name': 'valve', 'last_time': fresh, 'device_kind': 'output',
             'channels': [{'measurement': 'duty_cycle', 'unit': 'percent', 'last_value': 85}]},
            {'device_name': 'dead', 'last_time': old, 'channels': [
                {'measurement': 'temperature', 'unit': 'C', 'last_value': -5}]},
        ]}]}
        S = self._S()
        with mock.patch.object(S, 'get_zone_sensor_summary', return_value=summary):
            sensors, stale = S._overview_sensors(SimpleNamespace(unique_id='z'), brief=False)
        self.assertEqual({'temperature'}, set(sensors))
        t = sensors['temperature']
        self.assertEqual((22.0, 2, 20.0, 24.0), (t['avg'], t['n'], t['min'], t['max']))
        self.assertEqual({'count': 1, 'names': ['dead']}, stale)

    def test_outdoor_is_kept_out_of_the_average_and_shown_apart(self):
        from datetime import datetime, timedelta, timezone
        fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        ch = lambda v: [{'measurement': 'temperature', 'unit': 'C', 'last_value': v}]  # noqa: E731
        summary = {'zones': [{'stale_excluded': [{'device_id': 'frozen'}], 'sensors': [
            {'device_id': 'a', 'device_name': 'a', 'last_time': fresh,
             'location': 'indoor', 'channels': ch(20.0)},
            {'device_id': 'b', 'device_name': 'b', 'last_time': fresh,
             'location': 'indoor', 'channels': ch(24.0)},
            {'device_id': 'wx', 'device_name': 'wx', 'last_time': fresh,
             'location': 'outdoor', 'channels': ch(5.0)},
            {'device_id': 'frozen', 'device_name': 'frozen', 'last_time': fresh,
             'location': 'indoor', 'channels': ch(39.0)},
        ]}]}
        S = self._S()
        with mock.patch.object(S, 'get_zone_sensor_summary', return_value=summary):
            sensors, stale = S._overview_sensors(SimpleNamespace(unique_id='z'), brief=False)
        self.assertEqual(22.0, sensors['temperature']['avg'])
        self.assertEqual(2, sensors['temperature']['n'])
        self.assertEqual(5.0, sensors['outdoor']['temperature']['avg'])
        self.assertEqual(['frozen'], stale['names'])


if __name__ == '__main__':
    unittest.main()


class SetToolProfileTest(_AppFixture):
    """AI 에게 요청해 이 연결의 키 묶음을 바꾼다 — 부른 키만, 승인을 거쳐."""

    def _call(self, role, args, approved=True):
        from aot.tools import mcp_auth
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        ctx = (mock.patch.object(gate, 'gate', return_value=None) if approved
               else mock.patch.object(gate, 'gate', wraps=gate.gate))
        with ctx:
            out = te._execute_tool(self.app, 'set_tool_profile', dict(args),
                                   agent_id='user:%s' % _PREFIX.lower(), role=role,
                                   scope_user_uuid=getattr(role, 'user_id', None),
                                   transport='mcp_http',
                                   tool_profile=mcp_auth.tool_profile_of(role))
        return json.loads(out[0]['text'])

    def _key_profile(self, key):
        from aot.databases.models import UserAPIKey
        self.db.session.remove()
        row = UserAPIKey.query.order_by(UserAPIKey.id.desc()).all()
        return {r.unique_id: r.tool_profile_spec for r in row}

    def test_switches_only_the_calling_key(self):
        from aot.databases.models import UserAPIKey
        other = self._issue('Admin', 'full', OPS)           # 다른 사람의 키
        other_id = UserAPIKey.query.order_by(UserAPIKey.id.desc()).first().unique_id
        role = self._auth(self._issue('Editor', 'full', OPS))
        self.assertIsNotNone(role.key_id)
        body = self._call(role, {'profile': 'lite', 'key_id': other_id})
        self.assertEqual('success', body.get('status'), body)
        profiles = self._key_profile(None)
        self.assertEqual('lite', profiles[role.key_id])
        self.assertEqual(OPS, profiles[other_id])           # 남의 키는 그대로
        self.assertTrue(other)

    def test_operations_with_modules_and_bad_values(self):
        role = self._auth(self._issue('Editor', 'full', LITE))
        body = self._call(role, {'profile': 'operations', 'modules': ['plots']})
        self.assertEqual('operations+plots', body['tool_profile']['after'], body)
        body = self._call(role, {'profile': 'everything'})
        self.assertEqual('error', body.get('status'), body)

    def test_needs_human_approval(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        body = self._call(role, {'profile': 'lite'}, approved=False)
        self.assertEqual('pending_approval', body.get('status'), body)
        self.assertEqual(OPS, self._key_profile(None)[role.key_id])


class CentralLinkProfileTest(_AppFixture):
    """인가 서버(OAuth)로 들어온 연결 — claude.ai 원격 커넥터는 키를 못 넣어 이
    경로로 온다. 예전에는 묶음이 토큰 범위로 고정돼 키에서 가벼움을 골라도
    닿지 않았다(2026-10-10). 이제 계정 연결 행의 묶음을 따르되 토큰 범위를
    넘지 않는다."""

    def test_restrict_role_matrix(self):
        from aot.tools import mcp_central as C
        from aot.tools.mcp_auth import RoleInfo
        role = RoleInfo(name='Editor', can_write=True, user_id='u',
                        can_edit_settings=True, can_use_ai_chat=True,
                        can_edit_plots=True)
        cfg_scopes = {C.SCOPE_READ, C.SCOPE_CONTROL, C.SCOPE_CONFIG}
        ops_scopes = {C.SCOPE_READ, C.SCOPE_CONTROL}
        cases = [
            (None, cfg_scopes, CFG), (None, ops_scopes, OPS),
            ('lite', cfg_scopes, LITE), ('lite', ops_scopes, LITE),
            ('operations+plots', cfg_scopes, 'operations+plots'),
            ('operations+plots', ops_scopes, OPS),
            ('configuration', ops_scopes, OPS), ('garbage', cfg_scopes, CFG),
        ]
        for link_profile, scopes, want in cases:
            with self.subTest(link_profile=link_profile, scopes=sorted(scopes)):
                got = C.restrict_role(role, scopes, link_profile).tool_profile
                self.assertEqual(want, got)

    def _link(self, who='Editor', profile=None):
        from aot.databases.models import MCPExternalAccount
        user = self._user(who)
        link = MCPExternalAccount(issuer='https://auth.example', subject='sub-' + who,
                                  user_id=user.id, label='claude.ai',
                                  tool_profile=profile)
        self.db.session.add(link)
        self.db.session.commit()
        return user, link

    def _central_role(self, user, link):
        from aot.tools import mcp_auth, mcp_central as C
        claims = SimpleNamespace(scopes={C.SCOPE_READ, C.SCOPE_CONTROL, C.SCOPE_CONFIG},
                                 client_name='Claude', iss=link.issuer, sub=link.subject)
        with mock.patch.object(C, 'is_active', return_value=True), \
                mock.patch.object(C, 'authenticate',
                                  return_value=C.CentralResult(C.OK, user, claims, link)):
            ok, agent, role, err = mcp_auth._authenticate_central('jwt')
        self.assertTrue(ok, err)
        return role

    def tearDown(self):
        from aot.databases.models import MCPExternalAccount
        try:
            MCPExternalAccount.query.filter(
                MCPExternalAccount.issuer == 'https://auth.example').delete()
            self.db.session.commit()
        finally:
            super().tearDown()

    def test_link_profile_is_used_and_link_id_is_carried(self):
        user, link = self._link(profile='lite')
        role = self._central_role(user, link)
        self.assertEqual(LITE, role.tool_profile)
        self.assertEqual(link.id, role.link_id)
        self.assertIsNone(role.key_id)

    def test_ai_can_switch_its_own_linked_account(self):
        from aot.databases.models import MCPExternalAccount
        from aot.tools import mcp_auth, mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        user, link = self._link()
        _other_user, other = self._link('Admin', profile='configuration')
        link_id, other_id = link.id, other.id
        role = self._central_role(user, link)
        self.assertEqual(CFG, role.tool_profile)          # 고른 값 없음 → 토큰 범위
        with mock.patch.object(gate, 'gate', return_value=None):
            out = te._execute_tool(self.app, 'set_tool_profile',
                                   {'profile': 'lite', 'link_id': other_id},
                                   agent_id='user:x/Claude', role=role,
                                   scope_user_uuid=role.user_id, transport='mcp_http',
                                   tool_profile=mcp_auth.tool_profile_of(role))
        body = json.loads(out[0]['text'])
        self.assertEqual('success', body.get('status'), body)
        self.db.session.remove()
        self.assertEqual('lite', MCPExternalAccount.query.get(link_id).tool_profile)
        self.assertEqual('configuration', MCPExternalAccount.query.get(other_id).tool_profile)
        # 다음 요청부터 — 다시 인증하면 가벼움이다.
        fresh = MCPExternalAccount.query.get(link_id)
        self.assertEqual(LITE, self._central_role(self._user('Editor'), fresh).tool_profile)
