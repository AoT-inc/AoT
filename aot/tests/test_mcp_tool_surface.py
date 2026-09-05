# coding=utf-8
"""MCP 표면의 고정비와 응답 크기 — 서랍(tier)과 캡(_cap_result) 회귀.

두 가지를 고정한다. 둘 다 **실패가 조용한** 부류라 사람이 눈으로 잡기 어렵다.

1) 서랍: `tools/list` 는 core + 면제 도구만 싣고, 나머지는 open_drawer 로
   꺼내 use_tool 로 실행한다. 여기서 무너질 수 있는 것은 "도구가 사라지는
   것"이다 — 카탈로그에서 빠졌는데 어느 서랍에도 없으면 그 도구는 어떤
   클라이언트에서도 부를 수 없고, **에러는 나지 않는다.** LLM 은 그냥 "그런
   기능은 없다"고 답한다.

2) 캡: 클라이언트 상한을 넘긴 응답은 호스트가 잘라내거나 버리는데 서버는
   성공으로 안다. 실패가 서버에 안 보이므로 크기는 나가기 전에 재야 한다.

DB·데몬·네트워크를 쓰지 않는다. 앱이 필요한 것(_get_all_tools 의 네이티브
도구)은 여기서 다루지 않고, 순수 파생과 순수 함수만 본다.
"""
import json
import os
import unittest

from aot.ai.services import tool_registry as registry


def _load_server():
    """전송 계층(`aot_mcp_server`) — stdio/HTTP 로 받아 실행층에 넘긴다."""
    import importlib
    return importlib.import_module('aot.aot_mcp_server')


def _load_exec():
    """실행층(`tool_execution`) — 게이트·감사·응답 캡·도구 목록.

    **여기가 본질이고 전송은 어댑터다.** 내부 AI 도 같은 모듈을 직접 부르므로,
    실행층을 보는 검사는 전송을 거치지 않고 이쪽을 본다.
    """
    import importlib
    return importlib.import_module('aot.ai.services.tool_execution')


class TestDrawerSurface(unittest.TestCase):
    """서랍을 켰을 때 무엇이 상시 노출되고, 무엇이 닿을 수 있는가."""

    def test_core_stays_bounded(self):
        """core 는 "서랍을 안 열어도 흔한 요청이 해결되는" 최소 집합이다.

        처음에는 5개로 잡았다 — core 가 넓으면 LLM 이 서랍을 안 연다는 판단
        때문이었다. **실측이 그 방향을 뒤집었다**(2026-08-21, 외부 MCP
        클라이언트에 Gemini 를 붙여 같은 5개 요청):

            core 5개(노출 7)   왕복 6.6회 · 턴한도 초과 4/5 · 정상 응답 0
            core 31개(노출 27) 왕복 3.0회 · 턴한도 초과 1/5 · 정상 응답 2
            서랍 끔(노출 68)   왕복 3.0회 · 턴한도 초과 1/5 · 정상 응답 2

        LLM 은 core 가 좁다고 서랍을 여는 것이 아니라 **그냥 못 한다.** 좁히면
        서랍을 열게 만드는 것이 아니라 요청을 실패하게 만든다. 27개 지점은
        전량 노출과 동등한 성능을 크기 45%로 냈다 — core 의 목적은 서랍을
        열게 만드는 압력이 아니라 **서랍을 안 열어도 되게 하는 것**이다.

        그래도 상한은 둔다. 전부 core 가 되면 서랍이 이름만 남는다.
        """
        core = registry.core_tools()
        self.assertLessEqual(
            len(core), 35,
            'core 가 %d개다. 늘리려면 무엇을 대신 서랍으로 내릴지 함께 정할 것: %s'
            % (len(core), sorted(core)))
        self.assertGreaterEqual(
            len(core), 20,
            'core 가 %d개로 좁다 — 위 실측에서 좁은 core 는 요청을 실패시켰다'
            % len(core))

    def test_drawer_index_carries_tool_names(self):
        """서랍 이름만 보여 주면 LLM 은 열지 말지를 추측해야 한다.

        이름 목록이 있어야 판단이 추측에서 조회로 바뀐다. 이것이 "서랍을 안
        열어본다"는 실패 모드에 대한 실질적 방어라 비용(3KB 미만)을 감수한다.
        """
        index = registry.drawer_index()
        self.assertTrue(index)
        for entry in index:
            self.assertIn('tools', entry, '서랍에 도구 이름 목록이 없다: %s' % entry)
        named = sum(len(e['tools']) for e in index)
        self.assertGreater(named, 50, '인덱스가 도구를 거의 안 싣고 있다')
        size = len(json.dumps(index, ensure_ascii=False).encode())
        self.assertLess(size, 8000,
                        '서랍 인덱스가 %d B 다 — 상시 노출이므로 커지면 안 된다' % size)

    def test_drawer_index_respects_available(self):
        """표면마다 도구 집합이 다르다. 없는 도구를 광고하면 열어도 안 나온다."""
        # 서랍에 실제로 남아 있는 도구여야 한다(core 로 올라간 것은 안 나온다).
        catalog = {t['tool_name'] for t in registry.virtual_tools()}
        in_drawers = [n for d in registry.DRAWERS
                      for n in registry.tools_in_drawer(d, available=catalog)]
        self.assertTrue(in_drawers, '서랍이 비었다 — core 가 전부를 먹었다')
        sample = in_drawers[0]
        index = registry.drawer_index(available={sample})
        listed = {n for e in index for n in e['tools']}
        self.assertEqual(listed, {sample})

    def test_exempt_tools_never_appear_inside_a_drawer(self):
        """상시 노출인 것이 서랍에도 보이면 LLM 은 헛되이 서랍을 연다.

        그 왕복이 정확히 서랍이 없애려던 비용이다. core 도구는 등급 검사가
        걸러 주지만 **면제 도구는 안 걸러진다** — core 가 아니라 면제이기
        때문이다(respond_to_confirmation 이 실제로 그렇게 보였다).
        """
        import importlib
        server = importlib.import_module('aot.aot_mcp_server')

        # 실제 표면은 카탈로그 + _EXTRA_TOOLS 다. 카탈로그만 보면 이 검사는
        # 아무것도 잡지 못한다 — 문제가 된 respond_to_confirmation 이 바로
        # _EXTRA_TOOLS 쪽에만 있기 때문이다(처음에 그렇게 써서 통과했다).
        surface = ({t['tool_name'] for t in registry.virtual_tools()}
                   | {t['name'] for t in server._EXTRA_TOOLS})
        self.assertTrue(surface & set(server._TIER_EXEMPT_TOOLS),
                        '표면이 면제 도구를 하나도 안 담고 있다 — 검사가 헛돈다')

        contents = set()
        for drawer in registry.DRAWERS:
            contents.update(registry.tools_in_drawer(
                drawer, available=server._exclude_always_listed(surface)))
        overlap = sorted(contents & set(server._TIER_EXEMPT_TOOLS))
        self.assertEqual(overlap, [],
                         '상시 노출인데 서랍에도 있는 도구: %s' % overlap)

        # 그 제외를 안 하면 실제로 중복이 생긴다는 것도 함께 고정한다 —
        # 아래가 비면 위 판정은 지켜 주는 것이 없는 셈이다.
        unfiltered = set()
        for drawer in registry.DRAWERS:
            unfiltered.update(registry.tools_in_drawer(drawer, available=surface))
        self.assertTrue(
            unfiltered & set(server._TIER_EXEMPT_TOOLS),
            '면제를 빼지 않아도 중복이 없다면 _exclude_always_listed 는 무의미하다 '
            '— 배정표가 바뀌었는지 확인할 것')

    def test_mcp_catalog_tools_are_all_reachable(self):
        """카탈로그의 도구는 core 이거나 어느 서랍엔가 있어야 한다.

        둘 다 아니면 그 도구는 tools/list 에서 빠진 채 서랍에도 없다 = 어떤
        클라이언트도 부를 수 없다. 이 기능이 절대 해서는 안 되는 일이다.
        """
        catalog = {t['tool_name'] for t in registry.virtual_tools()}
        core = registry.core_tools()
        in_drawers = set()
        for drawer in registry.DRAWERS:
            in_drawers.update(registry.tools_in_drawer(drawer, available=catalog))
        lost = sorted(catalog - core - in_drawers)
        self.assertEqual(lost, [], '서랍을 켜면 닿을 수 없어지는 MCP 도구: %s' % lost)

    def test_listed_surface_stays_small(self):
        """**진짜 고정비** — tools/list 에 실제로 나가는 것의 크기.

        `test_tool_cost_budget.py` 의 MCP 상한은 서랍을 **끈** 카탈로그 전량을
        잰다. 도구를 더하면 그 숫자는 반드시 오르므로, 서랍을 켠 뒤로는 그것이
        곧 비용이 아니다 — 대화마다 실제로 나가는 것은 여기서 재는 값이다.
        (2026-08-21 실측: 전량 108개 21,363토큰. 상시 노출은 core 를 넓힌 뒤
        30개 6,958토큰 — core 5개일 때는 2,783토큰이었지만 그 크기로는 외부
        클라이언트가 요청을 끝내지 못했다. test_core_stays_bounded 참조.)

        네이티브 도구(get_sensor_reading 등)는 스키마가 DB 의 장치 목록에서
        만들어져 시스템마다 크기가 다르므로 여기서 빼고 잰다 — 앱 없이 도는
        검사로 남기기 위해서다. 그만큼 상한에 여유를 두었다.

        2026-08-24: `knowledge_search` 를 core 로 올려 31개 7,164토큰이 됐다
        (근거는 tool_registry `_TIER_ASSIGNMENT` 의 해당 항목 주석). **상한까지
        36토큰 남았다** — 다음에 core 도구를 더하거나 설명을 늘리려면 무엇을
        서랍으로 내릴지 함께 정해야 한다. 상한을 올리는 것은 마지막 수단이다:
        이 숫자가 곧 대화마다 나가는 고정비다.
        """
        import importlib
        server = importlib.import_module('aot.aot_mcp_server')

        core = registry.core_tools()
        listed = [{'name': t['tool_name'], 'description': t['description'],
                   'inputSchema': t['input_schema']}
                  for t in registry.virtual_tools() if t['tool_name'] in core]
        listed += [dict(t) for t in server._EXTRA_TOOLS]
        tokens = len(json.dumps(listed, ensure_ascii=False)) // 4
        self.assertLessEqual(
            tokens, 7_200,
            '상시 노출이 %d토큰이다(도구 %d개). 도구를 core 로 올렸거나 core '
            '도구의 설명이 길어졌다 — 무엇을 대신 서랍으로 내릴지 함께 정할 것: %s'
            % (tokens, len(listed), sorted(t['name'] for t in listed)))

    def test_exempt_tools_are_the_drawer_machinery(self):
        """면제 목록이 임의로 늘면 고정비를 줄이려던 이유가 사라진다.

        면제는 서랍을 여닫고 실행하는 수단 + 승인 응답뿐이어야 한다.
        """
        server = _load_server()
        self.assertEqual(
            set(server._TIER_EXEMPT_TOOLS),
            {'respond_to_confirmation', 'open_drawer', 'get_tool_detail', 'use_tool'},
            '면제 목록이 바뀌었다 — 늘리려면 근거를 주석에 적을 것')

    def test_use_tool_exists_because_hosts_cannot_call_unlisted_tools(self):
        """use_tool 이 빠지면 서랍은 장식이 된다.

        MCP 호스트는 tools/list 에 실린 도구만 모델에게 함수로 준다. 서랍을
        열어 정의를 받아도 그것을 호출할 수단이 없다 — 내부 AI 매니페스트는
        프롬프트 텍스트라 이 제약이 없어서, 같은 서랍이 두 표면에서 다르게
        동작한다. 이 도구가 그 차이를 메운다.
        """
        server = _load_server()
        names = {t['name'] for t in server._EXTRA_TOOLS}
        for needed in ('open_drawer', 'get_tool_detail', 'use_tool'):
            self.assertIn(needed, names, '%s 가 상시 노출 목록에서 빠졌다' % needed)


class TestExecutionLayerIsShared(unittest.TestCase):
    """게이트는 **전송에 딸린 것이 아니라 둘이 공유하는 층**이다.

    예전에는 실행층이 `aot_mcp_server.py` 안에 있었고, 내부 AI 는 그것을 쓰려고
    `MCPBridge` 로 subprocess 를 띄워 **자기 자신에게 JSON-RPC 를 보냈다.**
    같은 프로세스 안에 도구 구현이 있는데도. 대가는 앱을 한 벌 더 로드하는
    메모리(약 400MB), 두 프로세스의 코드 버전이 갈리는 것, 그리고 한쪽이 죽어도
    다른 경로로 우회돼 **아무도 모르는 것**이었다(실제로 `mcp_tools: 0` 인 채
    굴러갔다).

    이 검사가 지키는 것은 그 구조가 되돌아오지 않는 것이다.
    """

    def test_gate_and_audit_live_in_the_execution_layer(self):
        import inspect
        exec_mod = _load_exec()
        src = inspect.getsource(exec_mod._execute_tool)
        self.assertIn('gate.gate(', src, '승인 게이트가 실행층에 없다')
        self.assertIn('_record_audit', src, '감사 기록이 실행층에 없다')
        self.assertIn('_cap_result', src, '응답 캡이 실행층에 없다')

    def test_transport_does_not_own_the_gate(self):
        """전송 계층이 게이트를 자기 안에 다시 들이면 두 벌이 된다."""
        import inspect
        server = _load_server()
        src = inspect.getsource(server)
        self.assertNotIn('def _execute_tool(', src,
                         '전송 계층이 실행층을 다시 정의하고 있다 — '
                         'tool_execution 에서 가져다 쓸 것')
        self.assertIn('from aot.ai.services.tool_execution import', src,
                      '전송 계층이 실행층을 import 하지 않는다')

    def test_internal_entry_point_exists_and_returns_bridge_shape(self):
        """내부 AI 진입점은 브리지와 **같은 반환 형식**이어야 한다.

        리졸버가 그 형식을 기대한다 — 호출 방식이 바뀐 것이지 계약이 바뀐 것이
        아니다.
        """
        exec_mod = _load_exec()
        self.assertTrue(hasattr(exec_mod, 'execute_for_agent'))
        self.assertTrue(hasattr(exec_mod, 'tools_for_agent'))
        import inspect
        src = inspect.getsource(exec_mod.execute_for_agent)
        self.assertIn('_check_tool_access', src,
                      'ACL 이 빠졌다 — 브리지를 우회하면서 에이전트 권한 제어가 '
                      '함께 사라진다(매핑이 없으면 기본 거부라 더 위험하다)')
        self.assertIn('call_state', src,
                      '성공 판정을 call_state 로 하지 않는다 — 도구별 status '
                      '어휘는 12종이라 믿을 수 없다')

    def test_builtin_server_is_identified_by_command_everywhere(self):
        """내장 판별 기준이 갈라지면 한쪽만 프로토콜을 타게 된다.

        이름은 사람이 바꿀 수 있고 unique_id 는 설치마다 다르므로 `command` 로
        본다. 세 곳이 같은 기준을 써야 한다.
        """
        import inspect
        from aot.aot_flask import app as flask_app
        from aot.ai.services import ai_action_service
        from aot.ai.services import mcp_bridge_service
        from aot.ai.services.resolvers import mcp_tool_call_resolver

        # app.py 는 기동 시 MCP 를 **예열**한다 — 내장 서버를 빼지 않으면
        # 없앤 subprocess 가 기동 때마다 그대로 돌아온다(실측 186MB).
        for mod in (ai_action_service, mcp_bridge_service, mcp_tool_call_resolver,
                    flask_app):
            src = inspect.getsource(mod)
            self.assertIn("'aot_mcp_server'", src,
                          '%s 가 내장 서버를 command 로 판별하지 않는다'
                          % mod.__name__)


class TestStdioProtocolStreamIsClean(unittest.TestCase):
    """stdio 는 **stdout 이 프로토콜 그 자체다.**

    `create_app()` 이 부르는 `configure_aot_file_logging()` 은 'aot' 로거에
    `StreamHandler(sys.stdout)` 을 붙인다(데몬에게는 맞다 — 도커/systemd 가
    stdout 을 수집한다). MCP 서버도 create_app 을 부르므로, 그 로그가
    JSON-RPC 스트림 한가운데로 쏟아져 클라이언트의 첫 줄 파싱이 실패했다.

    증상이 고약했다: 관대한 클라이언트('{' 로 시작하지 않는 줄을 건너뛰는
    쪽)는 멀쩡히 붙었고, 엄격한 `MCPBridge` 만 조용히 실패했다. 그래서 "붙는
    클라이언트가 있다" 는 사실이 오히려 고장을 가렸다 — 내부 AI 는 매니페스트에
    `mcp_tools: 0`, 즉 operate_device 를 포함한 MCP 도구를 **하나도 못 받는**
    상태로 돌고 있었다(2026-08-21 수정, 수정 후 9개 수신 확인).
    """

    def setUp(self):
        import importlib
        self.server = importlib.import_module('aot.aot_mcp_server')

    def test_send_does_not_write_to_sys_stdout(self):
        """`sys.stdout` 이라는 이름은 로그 쪽으로 넘어가 있다."""
        import inspect
        src = inspect.getsource(self.server.StdioMCPServer._send)
        self.assertNotIn('sys.stdout', src.split('"""')[-1],
                         '_send 가 sys.stdout 에 쓰고 있다 — 그 이름은 이제 '
                         'stderr 다. 주입받은 프로토콜 스트림을 쓸 것')

    def test_stdout_is_diverted_before_the_app_is_created(self):
        """순서가 전부다.

        StreamHandler 는 **생성 시점의 스트림 객체**를 붙잡는다. create_app()
        이 핸들러를 만든 뒤에 sys.stdout 을 갈아도, 이미 붙은 핸들러는 옛
        객체(진짜 stdout)를 계속 쓴다 — 고쳤다고 생각하는데 아무것도 안 바뀐다.
        """
        import inspect
        src = inspect.getsource(self.server.main)
        divert = src.find('sys.stdout = sys.stderr')
        # 주석에도 create_app() 이 나오므로 **실제 호출**을 찾는다.
        create = src.find('app = create_app()')
        self.assertGreater(divert, 0, 'stdio 에서 stdout 을 비켜 두지 않는다')
        self.assertGreater(create, 0)
        self.assertLess(divert, create,
                        'create_app() 뒤에서 stdout 을 바꾸고 있다 — 그때는 이미 '
                        '로그 핸들러가 진짜 stdout 을 붙잡은 뒤다')

    def test_http_mode_keeps_its_stdout(self):
        """HTTP 모드는 stdout 이 프로토콜이 아니다 — 로그를 빼앗지 않는다."""
        import inspect
        src = inspect.getsource(self.server.main)
        self.assertIn('if not args.http:', src,
                      'stdout 전환이 stdio 모드로 한정돼 있지 않다')


class TestResponseCap(unittest.TestCase):
    """응답 크기 캡 — 넘겼는지 재고, 구조를 유지한 채 줄이는가."""

    def setUp(self):
        self.server = _load_exec()

    def test_small_result_is_untouched(self):
        cap = self.server._cap_result({'ok': True, 'items': [1, 2, 3]}, 'x')
        self.assertEqual(cap, {'ok': True, 'items': [1, 2, 3]})
        self.assertNotIn('_truncated', cap)

    def test_token_estimate_errs_large(self):
        """추정이 작게 빗나가면 캡이 통과시킨 응답을 호스트가 버린다.

        그 실패는 서버에 안 보이므로, 추정은 반드시 큰 쪽으로 틀려야 한다.
        JSON 은 구두점이 촘촘해 영어 산문의 4자/토큰보다 토큰이 많이 나온다.
        """
        self.assertLessEqual(self.server._CHARS_PER_TOKEN_ASCII, 3)
        ascii_text = 'a' * 300
        self.assertGreaterEqual(self.server._estimate_tokens(ascii_text), 100)
        # 한글은 글자당 대략 1토큰 — 바이트/4 로 세던 방식보다 크게 잡아야 한다.
        self.assertGreaterEqual(self.server._estimate_tokens('가' * 100), 100)

    def test_big_list_is_trimmed_and_stays_valid_json(self):
        """자를 때 문자열이 아니라 구조를 줄인다 — 조각난 JSON 은 읽을 수 없다."""
        payload = {'plots': [{'name': 'plot-%d' % i, 'blob': 'x' * 400}
                             for i in range(300)]}
        cap = self.server._cap_result(payload, 'list_plots', max_tokens=2000)
        text = json.dumps(cap, ensure_ascii=False)
        self.assertLessEqual(self.server._estimate_tokens(text), 2000)
        self.assertIsInstance(json.loads(text), dict)
        self.assertLess(len(cap['plots']), 300)
        self.assertIn('plots_truncated', cap)
        self.assertIn('300', cap['plots_truncated'], '원래 건수를 알려 줘야 한다')
        self.assertIn('_truncated', cap)
        self.assertIn('INCOMPLETE', cap['_truncated']['advice'])

    def test_uneven_list_converges_in_one_pass(self):
        """항목 크기 편차가 큰 목록도 한 번에 줄어야 한다.

        평균 항목 크기로 셈하면 큰 항목이 앞에 몰린 목록에서 두어 개씩만
        줄어, 반복 상한에 걸린 채 여전히 큰 응답이 나간다(공간 계층이 실제로
        그런 모양이다 — 첫 노드가 나머지를 합친 것보다 크다).
        """
        payload = {'hierarchy': [{'n': 0, 'blob': 'x' * 40000}]
                                + [{'n': i, 'blob': 'y' * 50} for i in range(1, 60)]}
        cap = self.server._cap_result(payload, 'get_spatial_tree', max_tokens=1500)
        text = json.dumps(cap, ensure_ascii=False)
        self.assertLessEqual(self.server._estimate_tokens(text), 1500)
        trims = cap['_truncated']['lists_trimmed']
        list_trims = [t for t in trims if 'kept' in t]
        self.assertEqual(len(list_trims), 1,
                         '한 목록을 여러 번 나눠 자르고 있다: %s' % trims)
        self.assertEqual(list_trims[0]['total'], 60, '원래 건수를 잃었다')
        # 남은 한 항목 자체가 거대하면 문자열까지 잘라야 목표에 닿는다. 그것도
        # 한 번에 끝나야 한다 — 조금씩 자르면 안내문이 그만큼을 도로 채워 진동한다.
        str_trims = [t for t in trims if 'kept_chars' in t]
        self.assertLessEqual(len(str_trims), 1, '문자열을 나눠 자르며 진동한다: %s' % trims)

    def test_long_string_is_trimmed_when_there_is_no_list(self):
        """긴 본문 하나가 대부분인 응답(문서·매뉴얼)도 줄어야 한다.

        리스트가 없다고 포기하면 캡이 무력한 응답 부류가 생기는데, 하필 그
        부류가 가장 크다.
        """
        payload = {'document': '가' * 30000, 'title': 'manual'}
        cap = self.server._cap_result(payload, 'get_archived_document', max_tokens=1000)
        text = json.dumps(cap, ensure_ascii=False)
        self.assertLessEqual(self.server._estimate_tokens(text), 1000)
        self.assertIsInstance(json.loads(text), dict)
        self.assertIn('document_truncated', cap)
        self.assertEqual(cap['title'], 'manual', '작은 값까지 건드리면 안 된다')

    def test_cap_can_be_disabled(self):
        """되돌릴 수단 없이 켜면 안 된다."""
        payload = {'items': [{'blob': 'x' * 400} for _ in range(300)]}
        cap = self.server._cap_result(dict(payload), 'x', max_tokens=0)
        self.assertNotIn('_truncated', cap)

    def test_switches_default_the_way_the_comments_claim(self):
        """기본값이 주석과 어긋나면 그 주석은 다음 사람을 속인다."""
        self.assertNotIn('AOT_MCP_TOOL_TIERING', os.environ,
                         '테스트 환경에 스위치가 켜져 있으면 판정이 무의미하다')
        self.assertTrue(self.server._tiering_enabled(),
                        'MCP 표면의 서랍은 기본 **켜짐**이다 — core 31개 지점에서 '
                        '전량 노출과 동등한 성능을 크기 33%로 냈다(2026-08-21, '
                        '20건 실측). _tiering_enabled 의 표 참조')
        self.assertGreater(self.server._MAX_RESPONSE_TOKENS, 0)


class TestCapThinsColumnsBeforeRows(unittest.TestCase):
    """상한을 넘기면 **행보다 열을 먼저** 줄인다.

    행을 자르면 남는 것은 "몇 건 중 몇 건" 이다. 실측(2026-08-26, 로컬
    get_system_brief 21,485 토큰): 예전 캡은 공간 계층을 **루트 47개 중 1개**
    로 잘랐다 — 농장이 몇 개 대지로 나뉘는지조차 답할 수 없는 응답이다.
    열로 줄이면 같은 상한에서 47개가 다 남는다.
    """

    def setUp(self):
        self.server = _load_exec()

    def _payload(self, n=40):
        """항목마다 무거운 중첩(heavy)과 짧은 스칼라를 함께 가진 목록."""
        return {'rows': [{
            'unique_id': 'id-%d' % i,
            'name': 'row %d' % i,
            'heavy': [{'k': j, 'blob': 'x' * 200} for j in range(6)],
            'mid': {'note': 'y' * 300},
        } for i in range(n)]}

    def test_every_row_survives_when_columns_are_enough(self):
        cap = self.server._cap_result(self._payload(), 'x', max_tokens=3000)
        self.assertEqual(40, len(cap['rows']), '행이 잘렸다')
        self.assertNotIn('rows_truncated', cap)
        self.assertIn('heavy', cap['rows_fields_omitted'])

    def test_scalars_that_identify_the_row_are_kept(self):
        """이름·식별자까지 떨어뜨리면 남은 행이 무엇인지 알 수 없어져,
        행을 자른 것과 다를 바가 없어진다."""
        cap = self.server._cap_result(self._payload(), 'x', max_tokens=3000)
        for i, row in enumerate(cap['rows']):
            self.assertEqual('id-%d' % i, row['unique_id'])
            self.assertEqual('row %d' % i, row['name'])

    def test_the_response_says_which_fields_left(self):
        """빠진 필드를 말하지 않으면 모델이 "그 값이 없다" 로 읽는다."""
        cap = self.server._cap_result(self._payload(), 'x', max_tokens=3000)
        note = cap['rows_fields_omitted']
        self.assertIn('heavy', note)
        self.assertIn('40', note, '전 건이 남았다는 사실이 없다')
        trim = cap['_truncated']['lists_trimmed'][0]
        self.assertEqual(trim['kept'], trim['total'],
                         '열만 줄였는데 행이 준 것처럼 기록된다')
        self.assertIn('heavy', trim['fields_dropped'])

    def test_the_note_accumulates_across_rounds(self):
        """두 번째 열을 뺄 때 안내를 덮어쓰면, 먼저 빠진 필드는 '원래 없던
        값' 이 된다."""
        cap = self.server._cap_result(self._payload(), 'x', max_tokens=900)
        note = cap['rows_fields_omitted']
        self.assertIn('heavy', note)
        self.assertIn('mid', note)

    def test_rows_are_cut_only_after_columns_run_out(self):
        """열을 다 빼도 안 되면 행 자르기가 이어진다 — 그때 그 목록은 이미
        얇아져 있어 같은 상한에 더 많은 행이 남는다."""
        cap = self.server._cap_result(self._payload(200), 'x', max_tokens=600)
        self.assertLess(len(cap['rows']), 200, '줄지 않았다')
        self.assertIn('rows_truncated', cap)
        trim = next(d for d in cap['_truncated']['lists_trimmed']
                    if d['path'] == 'rows')
        self.assertEqual(200, trim['total'], '원래 건수를 잃었다')
        # 열로 줄인 사실이 행 자르기 기록에 덮이면 안 된다 — 진단에서
        # "왜 이 항목에 이 필드가 없나" 의 답이 사라진다.
        self.assertTrue(trim.get('fields_dropped'))

    def test_a_column_only_trim_does_not_claim_the_list_is_incomplete(self):
        """열만 줄인 응답은 목록이 온전하다. 거기에 "INCOMPLETE, 좁혀서 다시
        부르라" 고 하면 모델은 없는 항목을 찾아 같은 조회를 되풀이하고, 그
        재조회는 같은 상한에 걸려 같은 답을 받는다."""
        cap = self.server._cap_result(self._payload(), 'x', max_tokens=3000)
        advice = cap['_truncated']['advice']
        self.assertNotIn('INCOMPLETE', advice)
        self.assertIn('COMPLETE', advice)
        self.assertIn('fields_omitted', advice, '어디를 보라는 말이 없다')

    def test_a_row_trim_still_warns(self):
        """행이 잘렸는데 경고를 빼면 모델이 일부를 전부로 읽는다 — 열만
        줄인 경우와 반드시 갈라야 하는 이유가 이쪽에 있다."""
        cap = self.server._cap_result(self._payload(200), 'x', max_tokens=600)
        self.assertIn('INCOMPLETE', cap['_truncated']['advice'])

    def test_a_truncated_body_still_warns(self):
        """긴 본문이 잘린 것도 불완전이다 — 목록이 아니라고 놓치면 안 된다."""
        cap = self.server._cap_result({'document': '가' * 20000, 'title': 'm'},
                                      'x', max_tokens=1200)
        self.assertIn('INCOMPLETE', cap['_truncated']['advice'])

    def test_a_list_of_scalars_is_not_thinned(self):
        """열이 없는 목록(스칼라 배열)은 예전대로 행으로 줄인다."""
        cap = self.server._cap_result(
            {'rows': ['z' * 400 for _ in range(50)]}, 'x', max_tokens=600)
        self.assertLess(len(cap['rows']), 50)
        self.assertIn('rows_truncated', cap)

    def test_one_huge_string_still_goes_down_the_old_path(self):
        """긴 본문 하나가 대부분인 응답(문서·매뉴얼)은 컨테이너가 없어 열
        자르기에 걸리지 않는다. 그 부류는 문자열 절삭이 맡는다."""
        cap = self.server._cap_result({'document': '가' * 20000, 'title': 'm'},
                                      'x', max_tokens=1200)
        self.assertLessEqual(
            self.server._estimate_tokens(json.dumps(cap, ensure_ascii=False)),
            1200)
        self.assertIn('document_truncated', cap)

    def test_several_lists_share_the_overflow(self):
        """**이번 설계의 핵심.** 목록 하나에 초과분 전체를 떠넘기면 어느
        목록도 열만으로는 예산에 못 들어와 전부 행 자르기로 떨어진다(처음에
        그렇게 만들었다가 공간 계층이 다시 1/47 로 잘리는 것을 보고 고쳤다).
        응답 전체를 놓고 고르면 셋이 초과분을 나눠 지고 전 건이 남는다."""
        payload = {
            'a': [{'id': i, 'big': ['x' * 100] * 5} for i in range(20)],
            'b': [{'id': i, 'big': ['y' * 100] * 5} for i in range(20)],
            'c': [{'id': i, 'big': ['z' * 100] * 5} for i in range(20)],
        }
        cap = self.server._cap_result(payload, 'x', max_tokens=2000)
        for k in ('a', 'b', 'c'):
            self.assertEqual(20, len(cap[k]), '%s 가 행으로 잘렸다' % k)


class TestSpatialTreeDepth(unittest.TestCase):
    """공간 계층은 깊이로 접힌다.

    왜. 이 트리는 농장이 커질수록 장치가 대부분을 차지한다(실측 2026-08-26:
    노드 154개 중 68개가 장치, 13,978 토큰 중 6,859). 다 펴서 응답 상한을
    넘기면 캡이 **루트 목록**을 잘라 47개 중 2개만 나가고, 그러면 농장 구조
    자체를 못 본다 — 깊이를 접는 쪽이 훨씬 적게 잃는다.
    """

    def setUp(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        self.svc = AoTDataToolService
        # site > zone > device 3단. 잎(빈 자식)도 하나 둔다.
        self.tree = [{
            'name': '1포장', 'type': 'site', 'unique_id': 's1', 'children': [
                {'name': '1-1', 'type': 'zone', 'unique_id': 'z1', 'children': [
                    {'name': 'v111', 'type': 'aot_device', 'unique_id': 'd1',
                     'children': []},
                    {'name': 'v112', 'type': 'device', 'unique_id': 'd2',
                     'children': [
                         {'name': 'ch', 'type': 'aot_device',
                          'unique_id': 'd3', 'children': []}]},
                ]},
                {'name': '펌프실', 'type': 'facility', 'unique_id': 'f1',
                 'children': []},
            ]}]

    def _depth(self, nodes, lvl=1):
        best = 0
        for n in nodes:
            kids = n.get('children') or []
            best = max(best, lvl if not kids else self._depth(kids, lvl + 1))
        return best

    def test_depth_two_stops_at_zones(self):
        out = self.svc._prune_depth(self.tree, 2)
        self.assertEqual(2, self._depth(out))

    def test_the_original_is_not_modified(self):
        """`get_spatial_hierarchy` 는 캐시 미스일 때 **캐시에 넣은 그 객체**를
        돌려준다. 제자리에서 자르면 잘린 트리가 캐시에 남아, 그 다음부터는
        depth 를 크게 줘도 전체를 볼 수 없다."""
        self.svc._prune_depth(self.tree, 2)
        zone = self.tree[0]['children'][0]
        self.assertEqual(2, len(zone['children']), '원본이 잘렸다')
        self.assertNotIn('children_omitted', zone)

    def test_cut_nodes_say_what_was_below_them(self):
        """빈 `children` 만 남기면 "이 구역에는 아무것도 없다" 로 읽힌다.
        잘린 것과 없는 것은 다르다."""
        out = self.svc._prune_depth(self.tree, 2)
        zone = out[0]['children'][0]
        self.assertEqual([], zone['children'])
        # 손자(d3)까지 세야 "이 아래 장치가 몇 개인가" 에 답이 된다.
        self.assertEqual({'aot_device': 2, 'device': 1},
                         zone['children_omitted'])

    def test_a_leaf_does_not_claim_it_was_cut(self):
        """자식이 없는 노드에 안내를 붙이면, 없는 것을 잘렸다고 말하게 된다."""
        out = self.svc._prune_depth(self.tree, 2)
        facility = out[0]['children'][1]
        self.assertNotIn('children_omitted', facility)

    def _patched(self, **kw):
        from unittest import mock
        from aot.ai.services.ai_context_service import AIContextService
        with mock.patch.object(AIContextService, 'get_spatial_hierarchy',
                               staticmethod(lambda *a, **k: self.tree)):
            return self.svc.get_spatial_tree(**kw)

    def test_zero_means_no_limit(self):
        """`if depth:` 로 쓰면 0 이 falsy 라 기본값으로 되살아나, 끄는 수단이
        조용히 사라진다."""
        out = self._patched(depth=0)
        self.assertEqual(4, self._depth(out['hierarchy']))
        self.assertNotIn('_reading', out)

    def test_a_cut_tree_says_so(self):
        out = self._patched(depth=2)
        self.assertEqual(2, out['depth'])
        self.assertIn('children_omitted', out['_reading'])

    def test_filter_type_is_not_cut_by_depth(self):
        """종류를 찾아 달라는 요청인데 깊이에서 먼저 끊으면 찾을 것이 사라진다 —
        결과가 비는데 '없다' 와 구분되지 않는다."""
        out = self._patched(depth=2, filter_type='aot_device')
        found = []

        def walk(ns):
            for n in ns:
                if n.get('type') == 'aot_device':
                    found.append(n['unique_id'])
                walk(n.get('children') or [])
        walk(out['hierarchy'])
        self.assertEqual({'d1', 'd3'}, set(found))

    def test_the_schema_documents_the_contract(self):
        """설명이 기본 깊이를 말하지 않으면 모델은 트리가 전부인 줄 알고,
        구역 아래가 비어 보이는 것을 '장치 없음' 으로 답한다."""
        spec = next(t for t in registry._MCP_TOOL_PAYLOADS
                    if t['tool_name'] == 'get_spatial_tree')
        depth = spec['input_schema']['properties']['depth']['description']
        self.assertIn('children_omitted', depth)
        self.assertIn('0', depth, '무제한을 어떻게 주는지 없다')



class TestJournalNarrowsAndFolds(unittest.TestCase):
    """일지 조회는 **호출자가 좁힌 만큼** 가벼워져야 한다.

    실측(2026-09-05): 하루를 요청해도 6단계의 목표·지침(2,495토큰)과 이탈
    통계(4,192)가 통째로 실려, 캡이 정작 그 하루의 측정값을 밀어냈다.
    좁힌 뒤 — 원본 11,720 → 6,681, 잘림 없음.
    """

    def _src(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(AoTDataToolService.get_plot_journal)

    def test_dates_narrow_the_stage_plan_too(self):
        """기간 밖 단계는 이름·기간만 남기고 목표·지침을 뺀다. 지우지는
        않는다 — 앞뒤에 무엇이 있었는지는 문서의 값이다."""
        src = self._src()
        self.assertIn("'outside_period'", src.replace('"', "'"))
        self.assertIn("k not in ('targets', 'guidance')", src)
        # 뺐다는 사실을 말한다(빈 값과 구분되어야 한다)
        self.assertIn("'stages_note'", src.replace('"', "'"))

    def test_dates_narrow_the_stage_summaries_too(self):
        """`stages` 만 줄이면 같은 무게가 `stage_summaries` 로 옮겨 갈 뿐이다 —
        실제로 그렇게 되어 398 → 4,192 토큰이 됐다."""
        src = self._src()
        self.assertIn("k not in ('target_drift', 'no_sensor_for')", src)

    def test_long_unscoped_reads_fold_by_default(self):
        """좁히지도 접지도 않은 긴 조회는 캡이 버킷을 잘라 "51건 중 3건" 이
        된다 — 그 문서로는 아무것도 답할 수 없다. 도구 설명이 이미 안내하는
        대로 기본값이 접는다."""
        src = self._src()
        self.assertIn('auto_folded', src)
        # 무엇으로 접었는지 말하고, 일별로 보는 길도 알려준다
        self.assertIn("granularity_view", src)
        self.assertIn("granularity='day'", src)

    def test_folding_keeps_going_until_it_fits(self):
        """한 단계만 접어서는 모자랄 수 있다 — 51일을 주간으로 접어도 8버킷
        이라 캡이 "8건 중 3건" 으로 잘랐다."""
        src = self._src()
        self.assertIn("order = ['week', 'month', 'all']", src)
        self.assertIn('budget', src)
        self.assertIn('_MAX_RESPONSE_TOKENS', src)

    def test_folded_reads_drop_per_stage_drift(self):
        """접어서 보는 조회는 개괄을 원한다는 뜻이다. 단계마다 센서별 이탈까지
        실으면(실측 4,192토큰, 고정비의 절반) 그만큼 버킷이 잘려 나간다."""
        src = self._src()
        self.assertIn("if auto_folded and summaries", src)
        self.assertIn("k != 'target_drift'", src)
        self.assertIn("'stage_summaries_note'", src.replace('"', "'"))

    def test_repeated_target_fields_are_hoisted(self):
        """목표 하나가 열한 필드인데 절반은 `key` 로 정해진다 — 6단계 × 5목표
        = 30번 반복되어 2,288 토큰이었다."""
        src = self._src()
        self.assertIn('target_defs', src)
        self.assertIn("_DEF_KEYS", src)

    def test_explicit_day_is_still_honoured(self):
        """자동 접기는 **인자를 주지 않았을 때만** 끼어든다."""
        src = self._src()
        self.assertIn('if not granularity and stored ==', src)

class TestPlotCurrentValuesAreNarrowed(unittest.TestCase):
    """`get_plot` 은 목표 대조에 쓰이는 measurement 만 읽어야 한다.

    예전에는 구획·구역 센서의 **모든 채널**을 하나씩 읽어(실측 25회)
    `rssi`·`snr`·전위처럼 목표와 무관한 값까지 InfluxDB 를 왕복했다.
    예열 후 5회 중앙값: 75회 0.291초 → 39회 0.170초, `target_check.rows` 는 동일.
    """

    def _src(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(AoTDataToolService._latest_by_measurement)

    def test_narrowing_is_by_measurement_not_by_channel(self):
        """같은 측정을 재는 다른 센서를 `others` 로 내보내는 계약이 있다 —
        채널로 좁히면 그 목록이 조용히 비어, 공기 온도 목표가 토양 센서 값과
        비교되던 실측 사고로 돌아간다."""
        src = self._src()
        self.assertIn('wanted', src)
        # measurement 이름으로 거른다
        self.assertIn('str(meas).strip().lower() not in want', src)
        # 그리고 그 판정 뒤에도 센서별 후보를 계속 모은다(others 계약)
        self.assertIn("found.setdefault", src)
        self.assertIn("'others'", src.replace('"', "'"))

    def test_conversion_is_loaded_once_not_per_channel(self):
        """채널마다 `Conversion.query` 를 돌면 채널 수만큼 DB 를 왕복한다(N+1)."""
        src = self._src()
        self.assertIn('Conversion.unique_id.in_(conv_ids)', src)
        self.assertNotIn('Conversion.unique_id == m.conversion_id', src)

    def test_without_wanted_everything_is_still_read(self):
        """`wanted` 를 주지 않는 호출부의 동작은 그대로여야 한다."""
        src = self._src()
        self.assertIn('want = ', src)
        self.assertIn('if want is not None', src)

    def test_caller_derives_wanted_from_the_targets(self):
        """무엇을 읽을지는 목표 항목이 정한다 — 목록을 손으로 적으면 목표가
        늘 때 조용히 빠진다."""
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        src = inspect.getsource(AoTDataToolService._stage_target_check)
        self.assertIn('wanted_meas', src)
        self.assertIn("t.get('measurement') or t.get('key')", src)
        self.assertIn('wanted=wanted_meas', src)

class TestGuidanceIsLabelledAsThePlanNotTheOutcome(unittest.TestCase):
    """지침을 인용하라고 시키면서 **그것이 지켜지는지 볼 곳**은 말하지 않았다.

    `list_plots` 와 `get_crop_status` 는 단계 지침을 싣고 "그대로 인용하라" 고
    지시한다. 그런데 목표 대조(`target_check` — 지금 값이 목표에서 얼마나
    벗어났는가, 며칠째 같은 쪽으로 벗어나는가)는 `get_plot` 에만 있다.
    그래서 모델은 계획을 읽고 **그것이 곧 현재 상태인 것처럼** 답할 수 있다.

    이 프로젝트가 시뮬레이션으로 확인한 것이 정확히 그 어긋남이다 — 야간
    온도 목표가 78일 중 78일 초과(평균 +5.77℃)인데 지침은 그대로였다.
    가이드가 현장에서 성립하지 않는다는 사실은 **사용자가 받아야 할 발견**
    이고, 지침만 인용하면 그것이 영영 드러나지 않는다.

    비용은 두 도구 합쳐 약 100토큰이다(실측 2026-09-05: list_plots
    5,792 → 5,875, get_crop_status 6,844 → 6,861).
    """

    def _src(self, fn_name):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(getattr(AoTDataToolService, fn_name))

    def test_the_list_says_guidance_is_a_plan(self):
        src = self._src('list_plots')
        self.assertIn('target_check', src)
        self.assertIn('the PLAN', src)

    def test_the_crop_summary_lists_target_check_among_what_is_missing(self):
        """"여기 없는 것" 목록에서 빠지면 모델은 그것이 존재하는 줄도 모른다."""
        src = self._src('get_crop_status')
        self.assertIn('target_check', src)

    def test_the_pointer_names_the_tool_that_actually_has_it(self):
        """"어딘가 다른 곳" 은 안내가 아니다 — 부를 이름을 적어야 한다."""
        for fn in ('list_plots', 'get_crop_status'):
            self.assertIn('get_plot', self._src(fn))


class TestTruncationSaysHowToNarrow(unittest.TestCase):
    """"좁혀서 다시 부르라" 만으로는 두 번째 호출이 달라지지 않는다.

    캡은 자기가 자른 응답이 어떤 도구의 것인지 모르므로 인자 이름을 말할 수
    없다. 실측(2026-09-04): 일지를 통째로 부르면 측정값이 잘리는데 안내가
    일반론이라 모델이 **같은 조회를 반복**했다. `date_from`/`granularity` 가
    있다는 것을 말해 주면 그 반복이 사라진다.
    """

    def _cap(self, result, limit, priority=None):
        from aot.ai.services import tool_execution as TE
        if priority is not None:
            result = dict(result)
            result[TE.CAP_PRIORITY_KEY] = priority
        return TE._cap_result(result, "test_tool", max_tokens=limit)

    def _big(self):
        # 행이 잘리게 만든다 — 열 자르기만으로는 끝나지 않도록 열이 하나뿐인
        # 항목을 많이 둔다.
        return {'rows': [{'v': 'x' * 300} for _ in range(40)]}

    def test_the_tool_sentence_is_appended_when_rows_were_cut(self):
        out = self._cap(self._big(), 900,
                        {'narrow_with': "Call again with date_from=…"})
        advice = out['_truncated']['advice']
        self.assertIn('INCOMPLETE', advice)
        self.assertIn('date_from', advice)

    def test_a_tool_that_says_nothing_keeps_the_old_wording(self):
        out = self._cap(self._big(), 900)
        self.assertIn('INCOMPLETE', out['_truncated']['advice'])
        self.assertNotIn('date_from', out['_truncated']['advice'])

    def test_the_hint_never_reaches_the_client(self):
        """`narrow_with` 는 캡을 위한 지시이지 응답의 내용이 아니다."""
        from aot.ai.services import tool_execution as TE
        out = self._cap(self._big(), 900, {'narrow_with': "…"})
        self.assertNotIn(TE.CAP_PRIORITY_KEY, out)
        # 자를 필요가 없을 때도 떼어낸다
        small = self._cap({'a': 1}, 100000, {'narrow_with': "…"})
        self.assertNotIn(TE.CAP_PRIORITY_KEY, small)

    def test_a_complete_list_does_not_get_told_to_narrow(self):
        """열만 줄인 응답은 목록이 온전하다. 거기에 "좁혀서 다시 부르라" 를
        붙이면 모델이 없는 항목을 찾아 같은 조회를 되풀이하고, 그 재조회는
        같은 상한에 걸려 또 같은 답을 받는다."""
        result = {'rows': [{'name': 'n%d' % i, 'blob': ['y' * 400]}
                           for i in range(8)]}
        out = self._cap(result, 1200, {'narrow_with': "Call again with date_from=…"})
        tr = out['_truncated']
        # 전제 확인 — 이 입력이 실제로 '열만 잘린' 경우여야 검증이 성립한다.
        self.assertTrue(all(d['kept'] == d['total'] for d in tr['lists_trimmed']))
        self.assertNotIn('INCOMPLETE', tr['advice'])
        self.assertNotIn('date_from', tr['advice'])

    def test_the_journal_tool_names_its_own_arguments(self):
        """문구를 캡 쪽에 두면 도구가 늘 때마다 두 곳이 갈라진다 — 도구가
        자기 인자를 적는다."""
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        src = inspect.getsource(AoTDataToolService.get_plot_journal)
        self.assertIn("'narrow_with'", src)
        for arg in ('date_from', 'date_to', 'granularity'):
            self.assertIn(arg, src)


class TestPlotCurrentValuesAreReadInOneRoundTrip(unittest.TestCase):
    """채널마다 InfluxDB 를 왕복하던 것을 한 번으로.

    좁히기(`wanted`)로 25 → 13회가 된 뒤에도 **채널 수만큼 왕복**하는 구조는
    그대로였다. `query_last_values_bulk` 가 device+unit 합집합을 한 번 물어
    계열마다 `last()` 를 내주므로 1회면 된다 — 지도 위젯이 같은 이유로 이미
    쓰던 함수라 새로 만들 것이 없었다.

    실측(2026-09-05, 김제 3-1, 예열 후 5회 중앙값):
    13회 0.178초 → **1회 0.104초**, `target_check` 는 전후 동일.
    """

    def _src(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(AoTDataToolService._latest_by_measurement)

    def test_the_bulk_query_is_issued_once_not_per_channel(self):
        """루프 안에서 부르면 왕복 수가 그대로다 — 이름만 바뀐 셈이 된다."""
        src = self._src()
        self.assertEqual(src.count('query_last_values_bulk_status('), 1)
        # 호출이 채널 루프보다 **앞**에 있어야 한다.
        call_at = src.index('query_last_values_bulk_status(')
        loop_at = src.index('for dev, unit, channel, meas in picks')
        self.assertLess(call_at, loop_at)

    def test_a_failed_query_falls_back_but_an_empty_one_does_not(self):
        """빈 결과는 두 가지 뜻이다 — 못 돌았거나, 돌았는데 그 계열에 값이
        없거나. 가르지 않으면 값이 없는 정상 상태에서 채널마다 다시 묻는
        옛 경로로 통째로 되돌아가고, **N 이 가장 클 때 폴백이 가장 비싸다.**"""
        src = self._src()
        self.assertIn(', ok = ', src)
        self.assertIn('if ok:', src)
        # 개별 조회는 폴백 안에만 남는다
        self.assertEqual(src.count('read_influxdb_list('), 1)

    def test_the_lookup_key_goes_through_the_shared_normalisation(self):
        """Influx 태그는 문자열이라 채널 `0` 과 `'0'` 이 다르다. 키를 손으로
        만들면 만드는 쪽과 찾는 쪽이 조용히 어긋나 **전부 미스**가 되는데,
        폴백이 없으면 값이 통째로 비고 있으면 옛 성능으로 돌아간다."""
        src = self._src()
        self.assertIn('bulk_key(unit, dev, channel, meas)', src)

    def test_narrowing_still_shrinks_what_is_asked(self):
        """한 번에 묻더라도 `wanted` 는 살아 있어야 한다 — 좁히면 묻는
        unit·device 집합이 함께 작아진다."""
        src = self._src()
        picks_at = src.index('picks.append(')
        want_at = src.index('str(meas).strip().lower() not in want')
        self.assertLess(want_at, picks_at)

    def test_the_timestamp_stays_an_absolute_utc_instant(self):
        """벌크는 epoch 초를 돌려준다. 그대로 `str()` 하면 `at` 이 숫자가 되고,
        naive 로 되돌리면 서버 지역시간으로 읽혀 **몇 시간 어긋난다.**"""
        src = self._src()
        self.assertIn('datetime.fromtimestamp(hit[0], tz=timezone.utc)', src)


class TestCapPriorityHint(unittest.TestCase):
    """캡이 무게로만 고르면 **호출자가 달라고 한 것**이 먼저 잘린다.

    실측(2026-09-05): 일지를 하루로 좁혀 불러도 그 하루의 측정값
    (`buckets.env`)이 빠지고, 날짜와 무관하게 늘 실리는 단계 요약이 남았다.
    도구가 순서를 말할 수 있게 하고, 말하지 않는 도구는 예전 그대로 둔다.
    """

    def _big(self, filler=400):
        """캡에 걸리게 만든 응답 — 무게 순서는 heavy > wanted 다.

        ⚠ 값을 **컨테이너**로 둔다. 자동 선택(`_heaviest_column`)은 dict/list
        열만 후보로 삼기 때문이다(스칼라는 그 항목이 무엇인지 말하는
        이름·식별자라 지킨다). 문자열로 두면 열 자르기가 아예 안 걸려
        행 자르기로 떨어지고, 그러면 이 테스트가 열 선택을 보지 못한다.
        """
        return {
            'rows': [{'heavy': ['x' * filler], 'wanted': ['y' * (filler // 4)],
                      'id': i} for i in range(12)],
        }

    def test_without_hint_the_heaviest_column_goes_first(self):
        """힌트를 주지 않는 도구는 예전 동작 그대로여야 한다.

        상한은 **열 하나를 빼면 들어가는 크기**로 잡는다 — 더 조이면 열
        자르기로는 못 내려가 행 자르기로 떨어지고, 그러면 이 테스트가 열
        선택을 보는 것이 아니게 된다(처음에 그렇게 짰다가 12행이 1행으로
        잘리면서 무거운 열이 그대로 남았다).
        """
        from aot.ai.services import tool_execution as TE
        res = TE._cap_result(self._big(), 'x', max_tokens=1600)
        self.assertEqual(len(res['rows']), 12, '행이 잘렸다 — 상한을 다시 잡을 것')
        self.assertNotIn('heavy', res['rows'][0])   # 무거운 쪽이 먼저 빠졌다
        self.assertIn('wanted', res['rows'][0])

    def test_hint_can_protect_a_column_even_when_it_is_heaviest(self):
        """`keep_last` 로 지목한 열은 다른 후보가 남아 있는 동안 지켜진다."""
        from aot.ai.services import tool_execution as TE
        payload = self._big()
        # 무게를 뒤집는다 — wanted 가 가장 무겁지만 지켜져야 한다.
        for r in payload['rows']:
            r['wanted'] = ['y' * 600]
        payload[TE.CAP_PRIORITY_KEY] = {
            'drop_first': [['rows', 'heavy']],
            'keep_last': [['rows', 'wanted']],
        }
        res = TE._cap_result(payload, 'x', max_tokens=4400)
        self.assertEqual(len(res['rows']), 12, '행이 잘렸다 — 상한을 다시 잡을 것')
        self.assertNotIn('heavy', res['rows'][0])
        self.assertIn('wanted', res['rows'][0],
                      'keep_last 로 지목한 열이 먼저 잘렸다')

    def test_keep_last_is_not_dropped_even_as_a_last_resort(self):
        """열은 통째로 빠지므로, 조금 모자란 것을 메우려고 지켜야 할 열을
        뽑으면 과잉 절삭이 된다 — 실측: 340 토큰이 모자란데 5,682 토큰짜리
        `env` 를 통째로 뺐다. 남은 몫은 행 자르기가 맡는다."""
        from aot.ai.services import tool_execution as TE
        payload = {'rows': [{'wanted': ['y' * 500], 'id': i} for i in range(12)]}
        payload[TE.CAP_PRIORITY_KEY] = {'keep_last': [['rows', 'wanted']]}
        res = TE._cap_result(payload, 'x', max_tokens=1500)
        self.assertIn('wanted', res['rows'][0],
                      '뺄 것이 그것뿐일 때도 keep_last 는 지켜져야 한다')
        self.assertLess(len(res['rows']), 12, '대신 행이 잘렸어야 한다')

    def test_hint_is_never_returned_to_the_client(self):
        """힌트는 캡을 위한 지시이지 응답의 내용이 아니다 — 캡이 꺼져 있거나
        자를 필요가 없을 때도 떼어내야 한다."""
        from aot.ai.services import tool_execution as TE
        for max_tokens in (0, 300, 10 ** 9):
            payload = self._big()
            payload[TE.CAP_PRIORITY_KEY] = {'drop_first': [['rows', 'heavy']]}
            res = TE._cap_result(payload, 'x', max_tokens=max_tokens)
            self.assertNotIn(TE.CAP_PRIORITY_KEY, res,
                             'max_tokens=%r 에서 힌트가 남았다' % max_tokens)

    def test_journal_declares_its_own_order(self):
        """그 기간의 측정값과 노트는 이 도구에만 있다 — 단계 계획의 산문·이탈
        통계는 `get_plot` 으로도 볼 수 있으므로 그쪽을 먼저 버린다."""
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        src = inspect.getsource(AoTDataToolService.get_plot_journal)
        self.assertIn('CAP_PRIORITY_KEY', src)
        self.assertIn("'keep_last'", src.replace('"', "'"))
        # 측정값과 노트가 보호 대상이다
        flat = src.replace('"', "'").replace(' ', '')
        self.assertIn("['buckets','env']", flat)
        self.assertIn("['buckets','notes']", flat)

class TestSystemBriefIsSummaryNotUnion(unittest.TestCase):
    """`get_system_brief` 가 하위 도구의 응답을 통째로 담으면 혼자서 상한을 넘는다.

    실측(2026-09-05): `get_spatial_tree` + `get_crop_status` + `get_control_state`
    를 그대로 담아 **18,974 토큰** — 상한 15,000 을 넘어 잘린 채 전달됐다.
    게다가 `crops` 6,844 는 `get_crop_status` 와 정확히 같은 값이라, 브리핑을 읽고
    그 도구를 다시 부르면 같은 값을 두 번 냈다. 요약으로 바꿔 1,633 토큰이 됐다.
    """

    def _src(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(AoTDataToolService.get_system_brief)

    def test_subtool_responses_are_not_embedded_whole(self):
        """하위 도구를 그대로 대입하는 형태가 되살아나면 상한을 다시 넘는다."""
        src = self._src()
        for call in ('S.get_spatial_tree(depth=2)',
                     'S.get_crop_status()',
                     'S.get_control_state()'):
            self.assertNotIn('lambda: %s' % call, src,
                             '%s 를 그대로 담으면 안 된다 — 요약을 거칠 것' % call)
        # 요약 함수를 거친다
        for fn in ('_spatial_summary', '_crops_summary', '_control_summary'):
            self.assertIn(fn, src)

    def test_names_survive_the_summary(self):
        """이름을 빼면 "구획 39건" 만 남아 반드시 되묻게 되고, 줄인 만큼을
        두 번째 호출이 도로 쓴다."""
        src = self._src()
        self.assertIn("'names'", src.replace('"', "'"))
        self.assertIn("'subjects'", src.replace('"', "'"))

    def test_name_lists_are_capped_with_a_remainder(self):
        """설치가 커지면 이름만으로도 응답이 불어난다. 자르되 몇 건이 더 있는지
        말해야 한다."""
        src = self._src()
        self.assertIn('_NAME_CAP', src)
        self.assertIn('more', src)

    def test_plot_count_is_the_sum_not_the_open_field_only(self):
        """원본 `plot_count` 는 노지만 센다 — 그대로 실으면 시설 구획과 더한
        합이 맞지 않는다(실측: 39 / 39 / 5)."""
        src = self._src()
        self.assertIn('len(open_plots) + len(bay_plots)', src)
        self.assertNotIn("cs.get(\"plot_count\"", src)

    def test_anomalies_stay_whole(self):
        """이상 상태는 작고(348토큰) 이 도구의 존재 이유에 가장 가깝다 —
        요약하다 이것까지 줄이면 브리핑이 답해야 할 것을 못 답한다."""
        self.assertIn('S.get_anomalies()', self._src())

if __name__ == '__main__':
    unittest.main()
