# coding=utf-8
"""대시보드가 지도 전역 스택(maplibre-gl + geo 번들 + map-modal, 약 1MB 동기 로드)을
지도가 있을 때만 싣는지 고정한다.

- 빈 대시보드·지도 없는 대시보드: 싣지 않는다(저사양 폰 첫 로드의 가장 큰 공통 비용).
- 지도 위젯·달력 위젯: 싣는다(페이지가 미리 실어 두기를 전제).
- 사용자 정의 위젯: 무엇을 쓰는지 모르므로 싣는다.
- 새 내장 위젯이 maplibregl 을 쓰기 시작하면 목록에 넣어야 한다 — 소스를 훑어 잡는다.
"""
import os
import unittest
from unittest.mock import patch

from aot.aot_flask import routes_dashboard
from aot.aot_flask.routes_dashboard import MAP_STACK_WIDGETS, dashboard_needs_map

_AOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUILTIN = {'AoT_map': {}, 'widget_calendar': {}, 'AoT_gauge_angular': {},
            'AoT_camera': {}, 'AoT_facility': {}}


class DashboardNeedsMapTest(unittest.TestCase):

    def setUp(self):
        p = patch.object(routes_dashboard, 'parse_widget_information',
                         lambda exclude_custom=False: _BUILTIN)
        p.start()
        self.addCleanup(p.stop)

    def test_empty_dashboard_skips_map(self):
        self.assertFalse(dashboard_needs_map([]))

    def test_non_map_widgets_skip_map(self):
        self.assertFalse(dashboard_needs_map(['AoT_gauge_angular', 'AoT_camera', 'AoT_facility']))

    def test_map_widget_loads_map(self):
        self.assertTrue(dashboard_needs_map(['AoT_gauge_angular', 'AoT_map']))

    def test_calendar_loads_map(self):
        self.assertTrue(dashboard_needs_map(['widget_calendar']))

    def test_custom_widget_loads_map(self):
        self.assertTrue(dashboard_needs_map(['AoT_gauge_angular', 'my_custom_widget']))

    def test_lookup_failure_loads_map(self):
        def boom(exclude_custom=False):
            raise RuntimeError('x')
        with patch.object(routes_dashboard, 'parse_widget_information', boom):
            self.assertTrue(dashboard_needs_map(['AoT_gauge_angular']))


def _uses_maplibre(text):
    return 'maplibregl' in text


def test_every_builtin_widget_using_maplibre_is_listed():
    """위젯 정의(.py)나 위젯 전용 JS 폴더(static/js/widgets/<이름>/)에서 maplibregl 을
    쓰는 내장 위젯은 MAP_STACK_WIDGETS 에 있어야 한다. 빠지면 지도 없는 판정으로
    대시보드가 지도 스택을 빼고 그려져 그 위젯이 깨진다."""
    from aot.utils.widgets import parse_widget_information
    builtin = parse_widget_information(exclude_custom=True)
    widgets_dir = os.path.join(_AOT, 'widgets')
    js_dir = os.path.join(_AOT, 'aot_flask', 'static', 'js', 'widgets')
    missing = []
    for name, info in builtin.items():
        texts = []
        module_file = info.get('file_path') or os.path.join(widgets_dir, name + '.py')
        if os.path.isfile(module_file):
            with open(module_file, encoding='utf-8') as f:
                texts.append(f.read())
        own_js = os.path.join(js_dir, name)
        if os.path.isdir(own_js):
            for root, dirs, files in os.walk(own_js):
                dirs[:] = [d for d in dirs if d not in ('dist', 'node_modules')]
                for fn in files:
                    if fn.endswith('.js') and '.min.' not in fn:
                        with open(os.path.join(root, fn), encoding='utf-8') as f:
                            texts.append(f.read())
        if any(_uses_maplibre(t) for t in texts) and name not in MAP_STACK_WIDGETS:
            missing.append(name)
    assert not missing, missing
    # 목록이 헛돌지 않는지 — 실제로 지도 스택을 쓰는 위젯이어야 한다.
    for name in MAP_STACK_WIDGETS:
        assert name in builtin, name


if __name__ == '__main__':
    unittest.main()
