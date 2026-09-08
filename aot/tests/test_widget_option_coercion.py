# coding=utf-8
"""위젯 옵션의 두 쓰기 경로가 같은 타입 규칙을 지키는지."""
import os, unittest
from aot.aot_flask.utils.utils_general import coerce_custom_option_values

_DW = {'custom_options': [
    {'id': 'label_min_zoom', 'type': 'integer', 'name': '축소 시 라벨 숨기기'},
    {'id': 'global_label_size', 'type': 'float', 'name': '라벨 크기'},
    {'id': 'show_plots', 'type': 'bool', 'name': '구획 표시'},
    {'id': 'popup_default_tab', 'type': 'select', 'name': '기본 탭'}]}


class TestWidgetOptionCoercion(unittest.TestCase):
    """`/save_widget_custom_options`(AJAX)는 예전에 **아무 검증도 하지 않았다.**

    타입에 안 맞는 값 하나가 남으면, 그 값을 건드리지도 않은 다음 폼 저장이
    통째로 거부된다 — 2026-08-23 `label_min_zoom=17.5` 가 **팝업 기본 탭**
    변경을 막았고, 사용자에게는 자기가 만진 적 없는 항목 이름이 떴다.
    """

    def test_integer_option_takes_a_fractional_value(self):
        out, err = coerce_custom_option_values(_DW, {'label_min_zoom': '17.5'})
        self.assertEqual({'label_min_zoom': 17}, out)
        self.assertEqual([], err)

    def test_each_declared_type_lands_as_that_type(self):
        out, err = coerce_custom_option_values(_DW, {
            'label_min_zoom': 17.5, 'global_label_size': '1.2',
            'show_plots': 'true', 'popup_default_tab': 'now'})
        self.assertEqual([], err)
        self.assertIsInstance(out['label_min_zoom'], int)
        self.assertIsInstance(out['global_label_size'], float)
        self.assertIs(True, out['show_plots'])
        self.assertEqual('now', out['popup_default_tab'])   # select 는 손대지 않는다

    def test_a_non_numeric_value_is_reported_not_guessed(self):
        """기본값으로 때우면 사용자가 적은 값이 조용히 사라진다."""
        out, err = coerce_custom_option_values(_DW, {'label_min_zoom': 'abc'})
        self.assertEqual({}, out)
        self.assertEqual(1, len(err))
        self.assertIn('축소 시 라벨 숨기기', err[0])

    def test_undeclared_keys_pass_through(self):
        """선언에 없는 키는 위젯 자신의 훅이 판단할 몫이다."""
        payload = {'unknown_key': {'a': 1}}
        out, err = coerce_custom_option_values(_DW, payload)
        self.assertEqual(payload, out)
        self.assertEqual([], err)


class TestBothWritePathsAreWired(unittest.TestCase):
    """규칙을 한 곳에만 달면 느슨한 쪽이 실질 권한이 된다.

    두 쓰기 경로(설정 폼 · AJAX 부분 저장)는 이제 같은 함수를 지난다
    (`utils_dashboard.apply_widget_option_changes`). 그래서 "소스에 몇 번
    나오는가" 대신 **그 함수가 실제로 다듬는가**를 본다 — 앞의 방식은 호출을
    한 군데로 모으는 정리만으로도 깨졌다.
    """

    def _widget(self):
        import types
        return types.SimpleNamespace(graph_type='X', custom_options='{}')

    def test_shared_write_path_coerces(self):
        from aot.aot_flask.utils.utils_dashboard import apply_widget_option_changes
        ok, errors, final = apply_widget_option_changes(
            self._widget(), {}, {'label_min_zoom': '17.5'},
            dict_widgets={'X': _DW}, partial=True)
        self.assertTrue(ok)
        self.assertEqual([], errors)
        self.assertEqual(17, final['label_min_zoom'])

    def test_shared_write_path_rejects_a_non_numeric_value(self):
        from aot.aot_flask.utils.utils_dashboard import apply_widget_option_changes
        ok, errors, _ = apply_widget_option_changes(
            self._widget(), {}, {'label_min_zoom': 'abc'},
            dict_widgets={'X': _DW}, partial=True)
        self.assertFalse(ok)
        self.assertEqual(1, len(errors))
        self.assertIn('축소 시 라벨 숨기기', errors[0])

    def test_partial_save_keeps_untouched_options(self):
        """부분 저장은 패치다 — 보내지 않은 값이 사라지면 안 된다."""
        from aot.aot_flask.utils.utils_dashboard import apply_widget_option_changes
        ok, errors, final = apply_widget_option_changes(
            self._widget(), {'show_plots': True}, {'label_min_zoom': 18},
            dict_widgets={'X': _DW}, partial=True)
        self.assertTrue(ok)
        self.assertEqual({'show_plots': True, 'label_min_zoom': 18}, final)

    def test_read_path_also_coerces(self):
        """읽기(get_widget_custom_options)도 같은 규칙을 거쳐야 한다."""
        here = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(here, '..', 'aot_flask', 'routes_dashboard.py'),
                   encoding='utf-8').read()
        self.assertIn('coerce_custom_option_values', src)


if __name__ == '__main__':
    unittest.main()
