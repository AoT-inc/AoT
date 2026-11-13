# coding=utf-8
"""L2 — 대시보드의 지도 위젯이 지연 로드되고도 끝까지 뜨는가.

지도 위젯의 번들과 초기화는 페이지 load 뒤로 미뤄진다(`AoTMapLazy`, widgets/AoT_map.py).
깨져도 조용하다 — 번들이 안 실리거나 시작 조건이 영영 안 맞으면 지도 자리가 빈 채로 남고,
나머지 위젯은 멀쩡해 보인다. 그래서 실제 브라우저로 본다:

1. 지도가 결국 뜬다(canvas · 인스턴스의 map), 자리표시는 사라진다.
2. 지도 번들은 DOMContentLoaded **뒤에** 요청된다 — 동기 로드로 되돌아가면 깨진다.
3. 나머지 위젯(측정·공지)은 지도와 함께 그려지고, 페이지 오류가 없다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard, widget_boxes

pytestmark = pytest.mark.e2e


def test_the_map_widget_still_comes_up_after_the_lazy_start(page, base_url):
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))

    open_dashboard(page, base_url, F.DASHBOARD)
    # 상한(load 뒤 4초, 화면 밖이어도 20초)을 넘겨도 안 뜨면 지연 로드가 지도를 놓친 것이다.
    page.wait_for_selector('.maplibregl-canvas', timeout=40000)

    state = page.evaluate("""() => {
        const id = document.querySelector('.aot-map-container').id.replace('aot-map-', '');
        const inst = (window.AoTWidgetInstances || {})[id];
        return {
            hasMap: !!(inst && inst.map),
            placeholder: !!document.getElementById('aot-map-lazy-ph-' + id),
            pending: window.AoTMapLazy ? window.AoTMapLazy.isPending(id) : null,
        };
    }""")
    assert state['hasMap'], f'지도 인스턴스가 만들어지지 않았습니다: {state}'
    assert not state['pending'], f'지연 로드가 아직 시작 전입니다: {state}'
    page.wait_for_function(
        "() => !document.querySelector('[id^=aot-map-lazy-ph-]')", timeout=15000)
    assert not errors, f'페이지 오류: {errors}'


def test_the_map_bundle_is_requested_after_domcontentloaded(page, base_url):
    open_dashboard(page, base_url, F.DASHBOARD)
    page.wait_for_selector('.maplibregl-canvas', timeout=40000)
    timing = page.evaluate("""() => {
        const nav = performance.getEntriesByType('navigation')[0];
        const bundle = performance.getEntriesByType('resource')
            .find(r => /aot-map-widget\\.bundle/.test(r.name));
        return {dcl: nav.domContentLoadedEventEnd, bundleStart: bundle ? bundle.startTime : null};
    }""")
    assert timing['bundleStart'] is not None, '지도 위젯 번들이 요청되지 않았습니다'
    assert timing['bundleStart'] >= timing['dcl'], (
        f"지도 번들이 DOMContentLoaded({timing['dcl']:.0f}ms) 전에 요청됐습니다"
        f"({timing['bundleStart']:.0f}ms) — 동기 로드로 돌아갔습니다")


def test_the_other_widgets_are_drawn_beside_the_lazy_map(page, base_url):
    open_dashboard(page, base_url, F.DASHBOARD)
    boxes = widget_boxes(page)
    names = list(boxes)
    assert any('Measurement' in n for n in names), f'측정 위젯이 안 보입니다: {names}'
    assert any('Notice' in n for n in names), f'공지 위젯이 안 보입니다: {names}'
    assert any('Map' in n for n in names), f'지도 위젯 자리가 없습니다: {names}'
