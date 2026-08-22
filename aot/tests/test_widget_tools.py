# coding=utf-8
"""대시보드 위젯 AI 도구 — 회귀.

AI 가 대시보드를 만질 수 있게 되면서 새로 생긴 위험 두 가지를 고정한다.

1) **대시보드 탭의 정본은 `Dashboard` 테이블이다.** `Widget.tab_id` 의 FK
   선언은 `tab.unique_id` 를 가리키고 `TAB_PAGE_TYPES` 에도 'dashboard' 가
   있어서, 코드를 읽으면 `TabService.get_tabs_for_page('dashboard')` 가 맞아
   보인다. 실제로는 그 조회가 **빈 목록**을 돌려준다 — 대시보드 행은 `tab` 이
   아니라 `dashboard` 테이블에 있고, 화면(`routes_dashboard.page_dashboard`)도
   그쪽을 읽는다. FK 강제가 꺼져 있어 이 어긋남은 아무 에러도 내지 않으므로,
   "대시보드가 하나도 없습니다" 라는 그럴듯한 오답으로만 나타난다(실제로 이
   도구를 만들면서 한 번 그렇게 짰다).

2) **옵션 이름이 틀리면 조용히 무시하지 않고 거부한다.** 무시하면 오타 하나가
   "설정했다는데 화면이 안 바뀐다" 로 나타나고, 그때 원인이 위젯인지 도구인지
   가릴 방법이 없다.

DB·데몬·앱 컨텍스트를 쓰지 않는다 — 순수 로직과 소스 검사만 본다.
"""
import ast
import inspect
import unittest

from aot.ai.services.aot_data_tool_service import AoTDataToolService as Service


class TestWidgetOptionCoercion(unittest.TestCase):

    SCHEMA = {'custom_options': [
        {'id': 'count', 'type': 'integer'},
        {'id': 'ratio', 'type': 'float'},
        {'id': 'shown', 'type': 'bool'},
        {'id': 'source', 'type': 'select_measurement'},
        {'id': 'label', 'type': 'text'},
    ]}

    def test_types_are_coerced(self):
        clean, errors = Service._coerce_widget_options(
            self.SCHEMA, {'count': '5', 'ratio': '1.5', 'shown': 1,
                          'source': 'abc,input,0', 'label': 'x'})
        self.assertEqual(errors, [])
        self.assertEqual(clean, {'count': 5, 'ratio': 1.5, 'shown': True,
                                 'source': 'abc,input,0', 'label': 'x'})

    def test_unknown_option_is_rejected_not_ignored(self):
        clean, errors = Service._coerce_widget_options(
            self.SCHEMA, {'count': 1, 'no_such_option': 'x'})
        self.assertTrue(errors, '스키마에 없는 옵션이 조용히 통과했다')
        self.assertIn('no_such_option', errors[0])
        self.assertNotIn('no_such_option', clean)

    def test_wrong_type_is_reported_with_the_expected_type(self):
        _clean, errors = Service._coerce_widget_options(
            self.SCHEMA, {'count': 'not a number'})
        self.assertTrue(errors)
        self.assertIn('integer', errors[0], '무엇을 기대했는지 알려 줘야 고친다')

    def test_empty_options_are_harmless(self):
        for value in (None, {}):
            clean, errors = Service._coerce_widget_options(self.SCHEMA, value)
            self.assertEqual((clean, errors), ({}, []))


class TestDashboardIsTheSourceOfTruth(unittest.TestCase):
    """위 1)번 — 대시보드를 어디서 읽는가."""

    WIDGET_TOOLS = ('list_dashboards', 'create_widget', 'modify_widget')

    def _source(self, name):
        return inspect.getsource(getattr(Service, name))

    def test_widget_tools_read_the_dashboard_table(self):
        for name in self.WIDGET_TOOLS:
            src = self._source(name)
            self.assertIn(
                'Dashboard', src,
                '%s 가 Dashboard 테이블을 안 본다 — 대시보드 탭의 정본이다' % name)

    def test_widget_tools_do_not_resolve_dashboards_through_tabservice(self):
        """`TabService` 로 대시보드를 찾으면 **빈 목록**이 온다.

        에러가 아니라 빈 결과라서, 바꿔 놔도 테스트 없이는 아무도 모른다.
        """
        for name in self.WIDGET_TOOLS:
            src = self._source(name)
            tree = ast.parse(inspect.cleandoc(src))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == 'TabService'):
                    self.fail('%s 가 TabService.%s 로 대시보드를 찾고 있다 — '
                              '대시보드 행은 tab 테이블에 없어서 조용히 빈 결과가 '
                              '된다' % (name, func.attr))


class TestWidgetToolsAreWiredEverywhere(unittest.TestCase):
    """선언·디스패치·승인·MCP 카탈로그 네 곳이 갈라지지 않았는가.

    `test_tool_registry_ssot.py` 가 전반을 보지만, 위젯 도구에서 특히 조용한
    실패는 **MCP 카탈로그 누락**이다 — 선언만 있으면 디스패치는 되는데
    `tools/list` 에 안 실려 클라이언트가 도구를 아예 못 본다.
    """

    READ = ('list_dashboards', 'list_widget_types', 'get_widget')
    WRITE = ('create_widget', 'modify_widget', 'delete_widget')

    def test_handlers_exist(self):
        from aot.ai.services import tool_registry as registry
        tool_map = registry.build_tool_map()
        for name in self.READ + self.WRITE:
            self.assertIn(name, tool_map, '%s 가 디스패치 표에 없다' % name)

    def test_writes_need_approval(self):
        from aot.ai.services import tool_registry as registry
        approval = registry.approval_required_tools()
        for name in self.WRITE:
            self.assertIn(name, approval,
                          '%s 는 사용자의 화면을 바꾼다 — 승인 대상이어야 한다' % name)
        for name in self.READ:
            self.assertNotIn(name, approval, '%s 는 읽기다' % name)

    def test_all_are_in_the_mcp_catalog(self):
        from aot.ai.services import tool_registry as registry
        catalog = {t['tool_name'] for t in registry.virtual_tools()}
        for name in self.READ + self.WRITE:
            self.assertIn(name, catalog,
                          '%s 가 _MCP_TOOL_PAYLOADS 에 없다 — 서버에는 등록되지만 '
                          'MCP 클라이언트에는 안 보인다' % name)

    def test_tab_tools_are_in_the_mcp_catalog_too(self):
        """탭 도구는 오래 이 상태였다(선언은 있고 카탈로그에는 없음)."""
        from aot.ai.services import tool_registry as registry
        catalog = {t['tool_name'] for t in registry.virtual_tools()}
        for name in ('list_tabs', 'create_tab', 'modify_tab', 'delete_tab'):
            self.assertIn(name, catalog, '%s 가 MCP 카탈로그에 없다' % name)


if __name__ == '__main__':
    unittest.main()
