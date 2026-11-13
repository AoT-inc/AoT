# coding=utf-8
"""L2 — 지도 위젯이 베이스 지도와 시설 3D 를 **실제로 그리는가**.

MapLibre 5 로 올리면 시설 3D 가 에러 없이 사라졌다. 커스텀 레이어가 받는
`modelViewProjectionMatrix`(폐기 예정)가 5 에서 틀린 행렬이라 모델이 화면
밖에 놓였기 때문이다 — 로그도 없고 외곽선만 남아서 화면은 멀쩡해 보였다.
그래서 "그렸다" 를 이벤트가 아니라 **픽셀 차이**로 판정한다: 시설 3D 레이어의
`render` 를 비운 화면과 켠 화면을 같은 카메라로 찍어, 가운데(카메라가 시설
위에 있다)에서 달라지는 픽셀이 있어야 한다. 3D 를 그리는 레이어를 켜는 순간
2D 시설 외곽선은 이미 숨겨져 있으므로, 차이는 3D 모델에서만 나온다.
"""
import io

import pytest
from PIL import Image, ImageChops

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e

# 지도·타일·시설 모델이 다 뜨는 데 걸리는 시간. 느린 CI 를 감안해 넉넉히.
SETTLE_MS = 12000
LAYER_ID = 'aot-facility-3d-layer'
# 3D 모델이 차지하는 최소 픽셀(채널 차이가 눈에 띄는 것만). 모델은 수천 픽셀이다.
MIN_CHANGED_PIXELS = 400

_TRACK_MAPS = """
(function () {
  window.__aotMaps = new Set();
  var v;
  Object.defineProperty(window, 'maplibregl', {configurable: true,
    get: function () { return v; },
    set: function (x) {
      v = x;
      try {
        ['on', 'once'].forEach(function (n) {
          var o = x.Map.prototype[n];
          x.Map.prototype[n] = function () { window.__aotMaps.add(this); return o.apply(this, arguments); };
        });
      } catch (e) {}
    }});
})();
"""


@pytest.fixture
def map_page(page, base_url):
    page.add_init_script(_TRACK_MAPS)
    open_dashboard(page, base_url, F.MAP_DASHBOARD)
    page.wait_for_selector('.maplibregl-canvas', timeout=30000)
    page.wait_for_timeout(SETTLE_MS)
    return page


def test_the_base_map_style_is_loaded(map_page):
    """베이스 지도가 실제로 올라왔는가 — 스타일이 읽히고 레이어가 있다."""
    info = map_page.evaluate("""() => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        if (!m) return null;
        const st = m.getStyle();
        return {loaded: m.isStyleLoaded(), layers: st.layers.length,
                sources: Object.keys(st.sources).length};
    }""")
    assert info, '지도 인스턴스를 찾지 못했습니다'
    assert info['loaded'], '스타일이 끝내 읽히지 않았습니다'
    assert info['layers'] > 1 and info['sources'] > 0, f'베이스 지도가 비었습니다: {info}'


def _center_shot(page):
    """지도 가운데(카메라가 시설 위)를 찍는다."""
    box = page.evaluate("""() => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        const r = m.getContainer().getBoundingClientRect();
        return {x: r.x + r.width / 2 - 160, y: r.y + r.height / 2 - 110, w: 320, h: 220};
    }""")
    png = page.screenshot(clip={'x': max(box['x'], 0), 'y': max(box['y'], 0),
                                'width': box['w'], 'height': box['h']})
    return Image.open(io.BytesIO(png)).convert('RGB')


def test_the_facility_3d_model_is_drawn(map_page):
    """시설 3D 모델이 화면에 그려지는가 — 레이어를 비운 화면과 켠 화면을 비교한다."""
    ok = map_page.evaluate("""(id) => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        const L = m.style._layers[id];
        if (!L) return false;
        const impl = L.implementation;
        window.__facRender = impl.render;
        impl.render = function () {};     // 레이어를 비운다
        m.triggerRepaint();
        return true;
    }""", LAYER_ID)
    assert ok, '시설 3D 레이어가 지도에 없습니다'
    map_page.wait_for_timeout(2500)
    without = _center_shot(map_page)

    map_page.evaluate("""(id) => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        m.style._layers[id].implementation.render = window.__facRender;
        m.triggerRepaint();
    }""", LAYER_ID)
    map_page.wait_for_timeout(2500)
    with_3d = _center_shot(map_page)

    diff = ImageChops.difference(without, with_3d).convert('L')
    changed = diff.point(lambda v: 255 if v > 24 else 0).histogram()[255]
    assert changed >= MIN_CHANGED_PIXELS, (
        f'시설 3D 가 화면에 그려지지 않았습니다(달라진 픽셀 {changed}개). '
        '5 에서는 투영 행렬이 틀리면 모델이 화면 밖에 놓입니다')


# 고도 400 m 평지 terrarium 타일(R·G·B = 129·144·0). 외부망 없이 시험 안에서 돌려준다.
DEM_METERS = 400
_DEM_TILE = io.BytesIO()
Image.new('RGB', (256, 256), (129, 144, 0)).save(_DEM_TILE, 'PNG')
_ENABLE_DEM = """() => {
    const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
    window.AOT_GEO_CONFIG.terrain = {
        id: 'e2e-dem', type: 'raster-dem', url: location.origin + '/e2e-dem/{z}/{x}/{y}.png',
        attribution: 'e2e', terrain: {encoding: 'terrarium', tileSize: 256, maxzoom: 12}};
    window.AoTMapSeam.enableTerrain(m);
}"""


def test_without_a_dem_input_the_map_stays_2d(map_page):
    """DEM 입력이 없으면 지형을 켜는 호출도 아무 일도 하지 않는다."""
    state = map_page.evaluate("""() => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        window.AoTMapSeam.enableTerrain(m);
        return {input: window.AOT_GEO_CONFIG.terrain || null,
                terrain: m.getTerrain() || null,
                dem: Object.values(m.getStyle().sources).filter(s => s.type === 'raster-dem').length};
    }""")
    assert state == {'input': None, 'terrain': None, 'dem': 0}


def test_the_facility_model_sits_on_the_terrain(map_page):
    """고도가 있는 지형에서도 시설 모델이 그려지고, 경사면이 고도를 따른다."""
    map_page.route('**/e2e-dem/**', lambda r: r.fulfill(
        status=200, content_type='image/png', body=_DEM_TILE.getvalue()))
    map_page.evaluate(_ENABLE_DEM)
    # 경사면은 화면 안 시설만 계산한다. 시드의 다른 시설은 화면 밖에 있어 0 으로 남는다.
    map_page.wait_for_function("""(want) => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        return window.AoTFacilityMap3D.terrainFits(m).some(f => Math.abs(f.c - want) < 1);
    }""", arg=DEM_METERS, timeout=30000)

    map_page.evaluate("""(id) => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        const impl = m.style._layers[id].implementation;
        window.__facRender = impl.render;
        impl.render = function () {};
        m.triggerRepaint();
    }""", LAYER_ID)
    map_page.wait_for_timeout(2500)
    without = _center_shot(map_page)
    map_page.evaluate("""(id) => {
        const m = [...window.__aotMaps].find(m => m.getStyle && m.getCanvas);
        m.style._layers[id].implementation.render = window.__facRender;
        m.triggerRepaint();
    }""", LAYER_ID)
    map_page.wait_for_timeout(2500)
    with_3d = _center_shot(map_page)
    diff = ImageChops.difference(without, with_3d).convert('L')
    changed = diff.point(lambda v: 255 if v > 24 else 0).histogram()[255]
    assert changed >= MIN_CHANGED_PIXELS, f'지형 위 시설 3D 가 보이지 않습니다(달라진 픽셀 {changed}개)'
