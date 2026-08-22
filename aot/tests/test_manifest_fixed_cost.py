# coding=utf-8
"""매니페스트 고정비 — 매 호출에 실리는 것에서 무엇을 뺐고, 무엇은 남아야 하는가.

`get_action_manifest()` 는 **질문 내용과 무관하게 매 호출에 실린다.** "1구역
온도 몇 도야?" 한 마디에도 통째로 나가므로, 여기 들어간 한 줄은 그대로 요금이
된다. 2026-08-21 실측(로컬, 출력 57개)에서 두 가지를 뺐다:

  전               95,454자 ≈23,863토큰
  mcp_binding 제거  75,898자 ≈18,974토큰   (-4,889)
  카탈로그 제거      69,066자 ≈17,266토큰   (-1,708)

**뺀 것보다 남긴 것이 중요하다.** `operate_device` 는 system_tools 매니페스트에
자기 항목이 없다(tool_registry 의 선언 주석 참조) — 예전에는 출력 장치마다 붙던
`mcp_binding.hint` 가 그 사용법을 알려주는 **유일한 자리**였다. 반복을 걷어내면서
그 사용법까지 사라지면 AI 는 장치를 켜는 방법을 어디서도 배우지 못하는데,
**그 실패는 "도구가 없다" 가 아니라 잘못된 인자로 호출하는 모습**으로 나타난다.
그래서 규칙을 `output_control` 로 한 번 싣고, 이 검사가 그것이 살아 있는지 본다.

DB·앱 컨텍스트가 필요하므로 소스 수준에서 본다 — 이 파일이 지키려는 것은 값이
아니라 **구조**(어디에 무엇이 실리는가)라 그것으로 충분하다.
"""
import ast
import inspect
import unittest

from aot.ai.services.ai_action_service import AIActionService


class TestOutputControlRuleSurvives(unittest.TestCase):

    def setUp(self):
        self.src = inspect.getsource(AIActionService.get_action_manifest)

    def test_per_output_binding_is_not_reintroduced(self):
        """장치마다 제어 설명을 붙이면 같은 문장이 장치 수만큼 반복된다.

        실측에서 outputs 섹션의 78%(19,038자)가 그 반복이었고, 서로 다른
        부분은 device_id 하나뿐이었다 — 그 값은 항목의 unique_id 에 이미 있다.
        """
        self.assertNotIn(
            'out_item["mcp_binding"]', self.src,
            '출력 항목마다 mcp_binding 을 다시 붙이고 있다 — 제어 방법은 '
            'manifest["output_control"] 에 한 번만 싣는다')

    def test_the_rule_itself_is_still_there(self):
        """반복은 지우되 **사용법은 남아야 한다.**"""
        self.assertIn('manifest["output_control"]', self.src,
                      'output_control 규칙이 사라졌다 — operate_device 의 사용법이 '
                      '매니페스트 어디에도 없게 된다')

    def test_the_rule_carries_what_the_model_needs(self):
        """규칙에 인자 이름과 금지사항이 실제로 들어 있는가.

        키만 있고 내용이 비면 검사는 통과하는데 모델은 여전히 못 부른다.
        """
        tree = ast.parse(inspect.cleandoc(self.src))
        rule_text = ''
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Subscript)):
                target = node.targets[0]
                key = getattr(target.slice, 'value', None)
                if key == 'output_control':
                    rule_text = ast.dump(node.value)
        self.assertTrue(rule_text, 'output_control 대입을 찾지 못했다')
        for needed in ('operate_device', 'device_id', 'state', 'action_type',
                       'capabilities'):
            self.assertIn(needed, rule_text,
                          "규칙에 '%s' 가 없다 — 모델이 호출 형식을 알 수 없다"
                          % needed)


class TestCatalogsAreNotShippedEveryCall(unittest.TestCase):
    """설치 가능한 **종류** 카탈로그는 대화 대부분과 무관하다.

    사용자가 가진 장치가 아니라 "만들 수 있는 것" 목록이라, 매 호출에 실으면
    비용만 드는 것이 아니라 모델이 그것을 사용자의 장치인 양 읊는 문제까지
    생긴다(같은 이유로 intent=='DATA_QUERY' 분기가 이미 걷어내고 있었다).
    """

    def setUp(self):
        self.src = inspect.getsource(AIActionService.get_action_manifest)

    def test_slim_manifest_keeps_the_pointer_not_the_catalog(self):
        head = self.src.split('# Phase 6: Return summary only for slimming')[0]
        self.assertNotIn(
            'manifest["creatable_inputs"].append', head,
            'slim 매니페스트가 설치 가능한 입력 종류를 다시 싣고 있다 — 개수와 '
            '조회 방법만 남기고 목록은 list_device_types 가 준다')

    def test_the_summary_points_somewhere_real(self):
        """포인터가 가리키는 곳이 실재해야 한다. 목록을 빼 놓고 갈 곳을 안
        알려주면 AI 는 장치를 만들 방법을 잃는다."""
        self.assertIn('list_device_types', self.src,
                      'creatable_inputs_summary 가 list_device_types 를 가리키지 '
                      '않는다')
        from aot.ai.services import tool_registry as registry
        self.assertIn('list_device_types', registry.build_tool_map(),
                      'summary 가 가리키는 list_device_types 가 디스패치되지 않는다')


class TestDrawerIndexNamesTheTools(unittest.TestCase):
    """서랍 안내가 **도구 이름까지** 싣는가 (내부 AI 표면).

    서랍 이름과 한 줄 설명만으로는 LLM 이 자기가 찾는 기능이 그 안에 있는지
    확신하지 못해, 열어 보는 대신 "그런 기능은 없다" 로 결론짓는다. 그 실패는
    에러가 아니라 조용한 오답이라 로그에도 안 남는다.
    """

    def test_index_lists_tool_names(self):
        from aot.ai.services import tool_registry as registry
        entry = registry._drawer_index_manifest()
        desc = entry['description']
        available = {t.name for t in registry.TOOLS if t.manifest}
        named = [n for drawer in registry.DRAWERS
                 for n in registry.tools_in_drawer(drawer, available=available)]
        self.assertTrue(named, '서랍에 담긴 도구가 하나도 없다')
        missing = [n for n in named if n not in desc]
        self.assertEqual(missing[:5], [],
                         '서랍 안내에 이름이 빠진 도구: %s' % missing[:5])

    def test_index_does_not_advertise_tools_it_cannot_hand_out(self):
        """`open_drawer` 는 manifest 가 있는 도구만 돌려준다. 그 밖의 이름을
        광고하면 열어도 안 나와, 서랍에서 한 번 더 멀어지게 만든다."""
        from aot.ai.services import tool_registry as registry
        desc = registry._drawer_index_manifest()['description']
        no_manifest = [t.name for t in registry.TOOLS if not t.manifest]
        listed = [n for n in no_manifest if ', %s' % n in desc or ': %s' % n in desc]
        self.assertEqual(listed, [],
                         '매니페스트가 없어 열어도 안 나오는데 광고된 도구: %s' % listed)


class TestContextIsNotShippedRaw(unittest.TestCase):
    """컨텍스트(`get_master_context`)도 매 호출에 실린다 — 매니페스트보다 크다.

    2026-08-21 실측(로컬): 컨텍스트 137,408자 ≈34,352토큰, 그중 좌표 43,326자와
    위젯 설정 36,993자. 둘 다 **LLM 이 읽어서 하는 일이 없는 원본 데이터**였다.
    접은 뒤 92,706자 ≈23,176토큰.
    """

    def setUp(self):
        from aot.ai.services.ai_context_service import AIContextService
        self.C = AIContextService
        self.polygon = {'type': 'Polygon', 'coordinates': [
            [[126.8, 35.8], [126.9, 35.8], [126.9, 35.9], [126.8, 35.8]]]}

    def test_polygon_coordinates_are_folded_by_default(self):
        """기본(standard)에서 꼭짓점이 그대로 나가면 안 된다.

        LLM 은 꼭짓점으로 할 수 있는 일이 없다 — 면적은 properties 에 있고,
        거리·최근접·포함 판정은 서버가 도구로 한다. 필요한 것은 중심점과
        크기 감각뿐이다.
        """
        out = self.C.simplify_geometry(dict(self.polygon))
        self.assertEqual(out.get('type'), 'Abstract',
                         'standard 티어에서 좌표가 접히지 않았다')
        self.assertIn('centroid', out)
        self.assertIn('bbox', out)
        self.assertNotIn('coordinates', out, '접었는데 좌표가 남아 있다')
        self.assertEqual(out.get('original_type'), 'Polygon',
                         '무엇을 접은 것인지 남겨야 한다')

    def test_heavy_tier_still_gets_the_real_geometry(self):
        """접기를 되돌릴 수단은 남겨 둔다."""
        out = self.C.simplify_geometry(dict(self.polygon), tier='heavy')
        self.assertEqual(out.get('type'), 'Polygon')
        self.assertIn('coordinates', out)

    def test_points_are_not_folded(self):
        """점은 좌표가 둘뿐이라 bbox/centroid 로 바꾸면 오히려 커진다."""
        out = self.C.simplify_geometry(
            {'type': 'Point', 'coordinates': [126.812345678, 35.812345678]})
        self.assertEqual(out.get('type'), 'Point')
        self.assertIn('coordinates', out)

    def test_widget_options_keep_only_references(self):
        """설정 원본은 이미 파생됐다(live_readings·visual_interpretation).

        그래도 '이 화면이 무슨 장치를 보여주는가' 는 남아야 한다 — 프롬프트의
        [Viewport Awareness] 지시가 그것을 근거로 답하라고 시킨다.
        """
        refs = self.C._widget_option_refs({
            'device_ids': ['dev-1'], 'active_layers': ['ndvi'],
            'color': '#ffffff', 'max': 100, 'refresh_seconds': 30,
            'fallback_center': [35.1, 126.1],
        })
        self.assertEqual(refs, {'device_ids': ['dev-1'], 'active_layers': ['ndvi']})

    def test_widget_option_filter_survives_odd_input(self):
        for value in (None, {}, 'not a dict', []):
            self.assertEqual(self.C._widget_option_refs(value), {})

    def test_dashboard_context_folds_options_after_consuming_them(self):
        """순서가 중요하다 — 파생(live_readings 등) **뒤에** 접어야 한다.

        먼저 접으면 라이브 값 조회와 시각 해석이 빈 설정을 받아 조용히
        아무것도 안 한다.
        """
        import inspect
        src = inspect.getsource(self.C.get_dashboard_context)
        fold = src.find('_widget_option_refs')
        consume = src.find('get_widget_visual_summary')
        self.assertGreater(fold, 0, '위젯 설정을 접는 자리가 없다')
        self.assertGreater(consume, 0, 'visual_interpretation 파생이 사라졌다')
        self.assertGreater(fold, consume,
                           '소비보다 먼저 접고 있다 — 파생이 빈 설정을 받는다')


if __name__ == '__main__':
    unittest.main()
