# coding=utf-8
"""지도 위젯 지연 로드 계약.

대시보드의 지도 위젯은 번들 넷(widget-shared · aot-map-widget · widget-map-extra · widget-map-tail)을
head 에서 동기로 받고 본문에서 곧바로 초기화했다 — 나머지 위젯이 뜨기 전에 지도가 파서와 네트워크를 쥐었다.
이제 `AoTMapLazy` 가 load 직후(화면 안) 또는 보일 때(화면 밖, 상한 20초) 번들을 받고 초기화한다.
깨져도 지도는 똑같이 뜨고 느려질 뿐이라 이 테스트가 본다.
"""
import os
import re
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', 'widgets', 'AoT_map.py')


def _text():
    with open(_SRC, encoding='utf-8') as handle:
        return handle.read()


class TestMapWidgetLazyLoad(unittest.TestCase):

    def test_bundles_are_not_loaded_by_sync_script_tags(self):
        text = _text()
        for name in ('widget-shared', 'aot-map-widget', 'widget-map-extra', 'widget-map-tail'):
            self.assertNotRegex(
                text, r'<script src="\{\{ asset\(\'%s\'\) \}\}"></script>' % re.escape(name),
                '%s 를 동기 <script> 로 싣는다 — AoTMapLazy 가 시작할 때 받아야 한다' % name)
            self.assertIn("asset('%s')|tojson" % name, text)

    def test_init_goes_through_the_scheduler(self):
        text = _text()
        self.assertIn('AoTMapLazy.schedule(_uid', text)
        # 본문이 initAoTMapVectorWidget 을 곧바로(파싱 중에) 부르는 옛 모양으로 돌아가지 않는다.
        self.assertNotRegex(text, r"if \(typeof window\.initAoTMapVectorWidget === 'function'\) \{\n\s+window\.initAoTMapVectorWidget\(")

    def test_onscreen_map_does_not_wait_for_quiet(self):
        text = _text()
        # 대시보드는 폴링이 계속 돌아 "잠잠" 조건이 거의 안 맞는다 — 화면 안 위젯은 load 직후 바로 시작한다.
        self.assertNotIn('QUIET_MS', text)
        self.assertNotIn('jQuery.active', text)
        self.assertIn("start(id, 'near')", text)

    def test_has_a_hard_cap_so_the_map_always_starts(self):
        text = _text()
        self.assertRegex(text, r'OFFSCREEN_CAP_MS\s*=\s*\d+')
        # 화면 밖 위젯도 상한 타이머로 결국 시작한다.
        self.assertIn("setTimeout(function () { start(id, 'offscreen-cap'); }, OFFSCREEN_CAP_MS)", text)

    def test_bundles_download_in_parallel_but_run_in_order(self):
        text = _text()
        self.assertIn('Promise.all(SRC.map(', text)
        self.assertIn('el.async = false', text)    # 동적 삽입 + async=false: 동시 다운로드, 삽입 순서 실행

    def test_start_reason_is_recorded(self):
        self.assertIn("performance.mark('aot-map:lazy-start'", _text())

    def test_external_readers_can_force_a_start(self):
        text = _text()
        self.assertIn('new Proxy(inst', text)       # 인스턴스를 id 로 읽으면 시작
        self.assertIn('start: start', text)
        self.assertIn('isPending', text)

    def test_placeholder_keeps_the_widget_size(self):
        text = _text()
        self.assertIn('id="aot-map-lazy-ph-{{each_widget.unique_id}}"', text)
        self.assertIn('position:absolute;inset:0', text)    # 자리표시는 겹쳐 놓아 크기를 바꾸지 않는다


if __name__ == '__main__':
    unittest.main()
