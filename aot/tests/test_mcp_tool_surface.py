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


if __name__ == '__main__':
    unittest.main()
