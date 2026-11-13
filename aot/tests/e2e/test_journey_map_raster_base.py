# coding=utf-8
"""L2 — 래스터 베이스(타일 지도)를 켠 지도 위젯이 제대로 뜨는가.

켜진 래스터 베이스는 기술 스타일(벡터)의 타일·스프라이트와 도형·라벨 API 의 await 를 기다리지
않고, 스타일 객체가 서는 즉시(`style.load`) 올라간다(`AoTMapLayerPanel.earlyBase`). 그렇게
일찍 올려도 깨지면 안 되는 것은 둘이다.

1. 베이스 레이어는 도형·라벨보다 **아래**에 있다 — 먼저 올라갔으니 맨 아래에 붙고, 도형은 나중에
   그 위로 쌓인다. 순서가 뒤집히면 도형이 타일 밑에 가려진다(화면은 멀쩡해 보이고 도형만 없다).
2. 베이스를 갈아탄 뒤에도, 다시 돌아온 뒤에도 같은 순서가 유지된다.

시각 기록(`performance.mark('aot-map:...')`)도 함께 본다: 일찍 올리는 길이 실제로 `map-load` 보다
앞서야 의미가 있다. 타일은 시험이 가로채 가짜 이미지로 채우므로 외부 망 없이 돈다.
"""
import base64
import json
import re
import time

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e

# 1x1 투명 PNG
_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
_CORS = {'access-control-allow-origin': '*'}
# 기술 스타일: 배경 + 래스터 하나. 래스터 베이스가 올라오면 이 레이어는 감춰진다.
_TECH_STYLE = {
    'version': 8,
    'sources': {'e2e-tech': {'type': 'raster', 'tileSize': 256,
                             'tiles': ['https://e2e-tech.invalid/{z}/{x}/{y}.png']}},
    'layers': [
        {'id': 'e2e-bg', 'type': 'background', 'paint': {'background-color': '#cfd8dc'}},
        {'id': 'e2e-tech-raster', 'type': 'raster', 'source': 'e2e-tech'},
    ],
}

_STATE = """(baseNames) => {
    const inst = Object.values(window.AoTWidgetInstances || {}).find(i => i && i.map);
    const map = inst.map;
    const layers = map.getStyle().layers;
    const idx = id => layers.findIndex(l => l.id === id);
    const radios = {};
    document.querySelectorAll('input[type=radio][data-layer-name]').forEach(r => {
        radios[r.dataset.layerName] = r.dataset.layerId + '_layer';
    });
    const bases = {};
    baseNames.forEach(n => {
        const id = radios[n];
        bases[n] = id && map.getLayer(id)
            ? {index: idx(id), visibility: map.getLayoutProperty(id, 'visibility') || 'visible'}
            : null;
    });
    const shapeIds = [...inst.layers.keys()].filter(id => map.getLayer(id));
    return {
        bases,
        shapes: shapeIds.map(id => idx(id)),
        techVisibility: map.getLayer('e2e-tech-raster')
            ? (map.getLayoutProperty('e2e-tech-raster', 'visibility') || 'visible') : null,
    };
}"""

_MARKS = """() => {
    const t = n => performance.getEntriesByName('aot-map:' + n).map(e => e.startTime);
    return {
        widgetStart: t('widget-start'), styleLoad: t('style-load'), mapLoad: t('map-load'),
        earlyBase: t('early-base-added'), sourceAdd: t('raster-source-add'),
        firstTileReq: t('raster-first-tile-request'), firstTileDone: t('raster-first-tile-done'),
        lazyStart: performance.getEntriesByName('aot-map:lazy-start').map(e => e.detail && e.detail.reason),
    };
}"""


@pytest.fixture
def raster_page(page, base_url):
    page.route(re.compile(r'demotiles\.maplibre\.org/style\.json'),
               lambda route: route.fulfill(status=200, content_type='application/json',
                                           body=json.dumps(_TECH_STYLE), headers=_CORS))
    page.route(re.compile(r'tile\.(openstreetmap|opentopomap)\.org'),
               lambda route: route.fulfill(status=200, content_type='image/png',
                                           body=_PNG, headers=_CORS))
    page.route(re.compile(r'e2e-tech\.invalid'),
               lambda route: route.fulfill(status=200, content_type='image/png',
                                           body=_PNG, headers=_CORS))
    open_dashboard(page, base_url, F.RASTER_DASHBOARD)
    page.wait_for_selector('.maplibregl-canvas', timeout=40000)
    # 도형·라벨 적재가 끝났다 — 이때부터 "도형 아래" 판정이 의미를 가진다.
    page.wait_for_function(
        "() => { const i = Object.values(window.AoTWidgetInstances || {}).find(x => x && x.map);"
        " return !!(i && i._itemsLoaded); }", timeout=40000)
    # 레이어 패널의 입력은 패널을 열 때 만들어진다 — 사람이 하는 그대로 연다.
    page.evaluate("() => document.querySelector('[id^=tool-layers-]').click()")
    page.wait_for_selector('input[type=radio][data-layer-name]', state='attached', timeout=10000)
    return page


def _assert_base_under_shapes(state, active, other=None):
    base = state['bases'][active]
    assert base, f'{active} 래스터 레이어가 없습니다: {state}'
    assert base['visibility'] == 'visible', f'{active} 가 보이지 않습니다: {state}'
    assert state['shapes'], f'도형 레이어가 하나도 없습니다(시드 부지·구역): {state}'
    assert base['index'] < min(state['shapes']), (
        f"베이스(index {base['index']})가 도형(index {sorted(state['shapes'])})보다 위에 있습니다 — 도형이 타일에 가려집니다")
    if other is not None and state['bases'][other]:
        assert state['bases'][other]['visibility'] == 'none', f'{other} 가 안 감춰졌습니다: {state}'


def test_the_raster_base_is_added_before_map_load(raster_page):
    marks = raster_page.evaluate(_MARKS)
    assert marks['earlyBase'], f'일찍 올리는 길이 쓰이지 않았습니다(early-base-added 없음): {marks}'
    assert marks['mapLoad'], f'map-load 기록이 없습니다: {marks}'
    assert marks['earlyBase'][0] <= marks['mapLoad'][0], (
        f'래스터 베이스가 map load 뒤에야 올라왔습니다: {marks}')
    assert marks['sourceAdd'], f'raster-source-add 기록이 없습니다: {marks}'
    assert marks['firstTileReq'], f'활성 소스의 첫 타일 요청이 기록되지 않았습니다: {marks}'
    assert marks['firstTileDone'][0] >= marks['firstTileReq'][0]
    # 화면 안 위젯은 잠잠해지길 기다리지 않고 load 직후 시작한다.
    assert 'near' in marks['lazyStart'], f'지연 로드가 화면 안 시작으로 기록되지 않았습니다: {marks}'


def test_the_raster_base_hides_the_technical_style_and_stays_under_shapes(raster_page):
    state = raster_page.evaluate(_STATE, [F.RASTER_BASE_A, F.RASTER_BASE_B])
    _assert_base_under_shapes(state, F.RASTER_BASE_A)
    assert state['techVisibility'] == 'none', f'기술 스타일 래스터가 감춰지지 않았습니다: {state}'


def test_the_order_survives_switching_the_base_and_back(raster_page):
    names = [F.RASTER_BASE_A, F.RASTER_BASE_B]
    switch = """(name) => {
        const r = document.querySelector('input[type=radio][data-layer-name="' + name + '"]');
        r.click();
    }"""
    raster_page.evaluate(switch, F.RASTER_BASE_B)
    raster_page.wait_for_function(
        """([b]) => { const i = Object.values(window.AoTWidgetInstances || {}).find(x => x && x.map);
        const r = document.querySelector('input[type=radio][data-layer-name="' + b + '"]');
        const id = r && r.dataset.layerId + '_layer';
        return !!(id && i.map.getLayer(id)
            && (i.map.getLayoutProperty(id, 'visibility') || 'visible') === 'visible'); }""",
        arg=[F.RASTER_BASE_B], timeout=20000)
    state = raster_page.evaluate(_STATE, names)
    _assert_base_under_shapes(state, F.RASTER_BASE_B, other=F.RASTER_BASE_A)

    raster_page.evaluate(switch, F.RASTER_BASE_A)
    raster_page.wait_for_function(
        """([a, b]) => { const i = Object.values(window.AoTWidgetInstances || {}).find(x => x && x.map);
        const ra = document.querySelector('input[type=radio][data-layer-name="' + a + '"]');
        const rb = document.querySelector('input[type=radio][data-layer-name="' + b + '"]');
        const la = ra.dataset.layerId + '_layer', lb = rb.dataset.layerId + '_layer';
        const vis = id => i.map.getLayer(id) && (i.map.getLayoutProperty(id, 'visibility') || 'visible');
        return vis(la) === 'visible' && vis(lb) === 'none'; }""",
        arg=[F.RASTER_BASE_A, F.RASTER_BASE_B], timeout=20000)
    state = raster_page.evaluate(_STATE, names)
    _assert_base_under_shapes(state, F.RASTER_BASE_A, other=F.RASTER_BASE_B)


def _credit_text(page):
    return page.evaluate(
        "() => (document.querySelector('.maplibregl-ctrl-attrib-inner') || {}).textContent || ''")


def test_the_early_base_shows_its_credit(raster_page):
    """일찍 올린 베이스도 저작권을 낸다 — 출처는 소스의 attribution 에서 오고, 베이스를 갈아타면 따라 바뀐다."""
    raster_page.wait_for_function(
        "() => ((document.querySelector('.maplibregl-ctrl-attrib-inner') || {}).textContent || '')"
        ".indexOf('OpenStreetMap') >= 0", timeout=20000)
    assert 'OpenTopoMap' not in _credit_text(raster_page)
    # 우리 쪽 ⓘ 패널도 같은 내용을 보여 준다(AoTMapAttribution 이 네이티브 목록을 읽는다).
    # 첫 idle 에 저절로 열렸을 수 있다 — 닫혀 있을 때만 눌러 연다(열린 것을 누르면 닫힌다).
    raster_page.evaluate(
        "() => { const p = document.querySelector('.aot-map-attrib-panel');"
        " if (!p || p.style.display === 'none') document.querySelector('.aot-map-attrib-group a').click(); }")
    raster_page.wait_for_function(
        "() => { const p = document.querySelector('.aot-map-attrib-panel');"
        " return !!p && p.style.display !== 'none' && p.textContent.indexOf('OpenStreetMap') >= 0; }",
        timeout=20000)
    raster_page.evaluate(
        "(n) => document.querySelector('input[type=radio][data-layer-name=\"' + n + '\"]').click()",
        F.RASTER_BASE_B)
    raster_page.wait_for_function(
        "() => ((document.querySelector('.maplibregl-ctrl-attrib-inner') || {}).textContent || '')"
        ".indexOf('OpenTopoMap') >= 0", timeout=20000)


# 일찍 올리는 길을 끈 상태(= 예전 흐름: 베이스는 패널이 map load 와 도형 적재 뒤에 올린다).
_NO_EARLY = """
(function () {
  var v;
  Object.defineProperty(window, 'AoTMapLayerPanel', {configurable: true,
    get: function () { return v; },
    set: function (x) { if (x && x.earlyBase) { x.earlyBase = function () {}; } v = x; }});
})();
"""

_TIMES = """() => {
    const t = n => { const e = performance.getEntriesByName('aot-map:' + n)[0]; return e ? Math.round(e.startTime) : null; };
    const w = t('widget-start');
    const rel = n => { const v = t(n); return v == null ? null : v - w; };
    return {styleLoad: rel('style-load'), sourceAdd: rel('raster-source-add'),
            firstTileReq: rel('raster-first-tile-request'), firstTileDone: rel('raster-first-tile-done'),
            mapLoad: rel('map-load')};
}"""

_TECH_DELAY_S = 3


@pytest.mark.parametrize('early', [True, False], ids=['after', 'before'])
def test_slow_technical_tiles_do_not_delay_the_raster_base(page, base_url, early, capsys):
    """기술 스타일 타일이 느려도(여기서는 3초 붙잡는다) 래스터 베이스의 첫 타일은 기다리지 않는다.

    before = 일찍 올리는 길을 끈 예전 흐름, after = 지금 흐름. 같은 브라우저·같은 시드·같은 가로채기에서
    위젯 시작(widget-start)부터 잰 값을 로그에 남긴다.
    """
    held = []
    state = {'released': False}

    def tech(route):
        if state['released']:
            route.fulfill(status=200, content_type='image/png', body=_PNG, headers=_CORS)
        else:
            held.append(route)

    page.route(re.compile(r'demotiles\.maplibre\.org/style\.json'),
               lambda route: route.fulfill(status=200, content_type='application/json',
                                           body=json.dumps(_TECH_STYLE), headers=_CORS))
    page.route(re.compile(r'tile\.(openstreetmap|opentopomap)\.org'),
               lambda route: route.fulfill(status=200, content_type='image/png',
                                           body=_PNG, headers=_CORS))
    page.route(re.compile(r'e2e-tech\.invalid'), tech)
    if not early:
        page.add_init_script(_NO_EARLY)

    open_dashboard(page, base_url, F.RASTER_DASHBOARD)
    page.wait_for_selector('.maplibregl-canvas', timeout=40000)
    done = "() => performance.getEntriesByName('aot-map:raster-first-tile-done').length > 0"
    started = time.time()
    if early:
        page.wait_for_function(done, timeout=20000)
        assert not state['released'], '기술 스타일 타일을 풀어 주기 전에 베이스 타일이 와야 합니다'
    else:
        page.wait_for_timeout(_TECH_DELAY_S * 1000)
        state['released'] = True
        for route in held:
            route.fulfill(status=200, content_type='image/png', body=_PNG, headers=_CORS)
        page.wait_for_function(done, timeout=30000)
    times = page.evaluate(_TIMES)
    with capsys.disabled():
        print(f"\n[map-raster-first] {'after ' if early else 'before'} "
              f"(기술 타일 {_TECH_DELAY_S}초 지연, 대기 {time.time() - started:.1f}s): {times}")
    if early:
        assert times['firstTileDone'] < _TECH_DELAY_S * 1000, (
            f"래스터 베이스 첫 타일이 기술 스타일 지연({_TECH_DELAY_S}s)을 기다렸습니다: {times}")
