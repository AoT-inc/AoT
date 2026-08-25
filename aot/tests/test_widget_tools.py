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
import json
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


class TestOptionSchemaIsJsonSerializable(unittest.TestCase):
    """옵션 스키마에 lazy_gettext 객체가 새어 나가면 도구가 응답을 못 만든다.

    위젯 정의는 사람이 읽는 문구를 전부 `lazy_gettext` 로 감싸는데 그 객체는
    `str` 의 하위 타입이 아니라 `json.dumps` 가 통째로 실패한다
    (`Object of type LazyString is not JSON serializable`). 그런데 실패하는
    자리는 위젯이 아니라 **응답을 직렬화하는 MCP 층**이라, 도구 코드에는
    아무 흔적이 남지 않고 클라이언트만 에러를 본다.

    2026-08-23 koat 운영 서버 실측에서 `get_widget` 이 select 형 옵션을 가진
    위젯(AoT_map·AoT_graph 등)에서 전부 그렇게 죽었다 — `name`/`phrase` 는
    `str()` 로 감쌌는데 `options_select` 만 빠져 있었다. 설치된 27종 중
    **10종**이 그 상태였다(AoT_PID·AoT_advice·AoT_facility·AoT_gauge_angular·
    AoT_graph·AoT_map·AoT_timer·widget_calendar·widget_camera·
    widget_trigger_sequence).

    그래서 필드별 `str()` 이 아니라 `_jsonable` 재귀 변환을 지나게 했고, 여기서
    **설치된 위젯 전종**을 훑는다 — 새 위젯이 lazy 문구를 새 자리에 넣어도
    잡히도록.
    """

    def test_lazy_labels_in_options_select_do_not_leak(self):
        from flask_babel import lazy_gettext
        info = {'custom_options': [
            {'id': 'style', 'type': 'select', 'default_value': 'circle',
             'name': lazy_gettext('Sensor Marker Style'),
             'phrase': lazy_gettext('How the marker is drawn.'),
             'options_select': [('circle', lazy_gettext('Circle')),
                                ('text', lazy_gettext('Text label'))]},
            {'id': 'map_uuid', 'type': 'select_device',
             'options_select': ['Map']},
        ]}
        schema = Service._widget_option_schema(info)
        json.dumps(schema)  # 여기서 죽으면 도구가 응답을 못 만든다
        style = schema[0]
        self.assertEqual(style['accepts'],
                         [['circle', 'Circle'], ['text', 'Text label']])
        self.assertEqual(schema[1]['accepts'], ['Map'])

    def test_lazy_default_value_does_not_leak_either(self):
        """`default_value` 도 lazy 를 담을 수 있다.

        지금은 그런 항목이 전부 `id` 없는 `message` 라 걸러지지만, `id` 가 붙는
        순간 같은 방식으로 조용히 깨진다 — 그 자리를 미리 막아 둔다.
        """
        from flask_babel import lazy_gettext
        info = {'custom_options': [
            {'id': 'note', 'type': 'text',
             'default_value': lazy_gettext('Press Ctrl to select more')},
        ]}
        schema = Service._widget_option_schema(info)
        json.dumps(schema)
        self.assertEqual(schema[0]['default'], 'Press Ctrl to select more')

    def test_every_installed_widget_type_serializes(self):
        import glob
        import importlib
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        widget_dir = os.path.join(os.path.dirname(here), 'widgets')
        paths = sorted(glob.glob(os.path.join(widget_dir, '*.py')))
        self.assertTrue(paths, '위젯 정의를 하나도 못 찾았다 — 경로가 바뀌었나')

        checked, broken = 0, []
        for path in paths:
            mod = os.path.splitext(os.path.basename(path))[0]
            if mod.startswith('__'):
                continue
            try:
                module = importlib.import_module('aot.widgets.' + mod)
            except Exception:
                # 위젯 하나가 선택적 의존성 때문에 import 안 되는 것은 이
                # 검사의 관심사가 아니다(다른 테스트가 본다).
                continue
            info = getattr(module, 'WIDGET_INFORMATION', None)
            if not info:
                continue
            checked += 1
            try:
                json.dumps(Service._widget_option_schema(info))
            except TypeError as e:
                broken.append('%s (%s)' % (mod, e))
        self.assertTrue(checked, '검사한 위젯이 0종이다 — 검사가 무력하다')
        self.assertEqual(
            broken, [],
            '이 위젯 종류의 옵션 스키마가 JSON 으로 안 나간다 — get_widget/'
            'list_widget_types 가 그 종류에서 통째로 실패한다: %s' % broken)


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
