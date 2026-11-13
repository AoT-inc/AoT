# coding=utf-8
"""L2 — 지도 컨트롤의 `3D` 단추(지형 켜기/끄기). 지도 위젯과 /geo/design 양쪽.

3D 는 누른 그 지도에만 적용된다. 상태는 그 브라우저의 localStorage 에 지도별로 남고(서버 저장 없음),
기본은 꺼짐이라 누르기 전에는 고도 타일을 한 장도 받지 않는다. 새로고침하면 그 지도만 복원한다.

시드에는 고도 입력이 없다 — 시험이 `AOT_GEO_CONFIG.terrain` 을 주입한 뒤 단추를 다시 묶는다.
고도 타일 주소는 시험이 가로채 요청 수를 센다.
"""
import io

import pytest
from PIL import Image

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e

_DEM_TILE = io.BytesIO()
Image.new('RGB', (256, 256), (129, 144, 0)).save(_DEM_TILE, 'PNG')

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
_MAP = "[...window.__aotMaps].find(m => m.getStyle && m.getCanvas)"
_INJECT_DEM = """() => {
    window.AOT_GEO_CONFIG.terrain = {
        id: 'e2e-dem', type: 'raster-dem', url: location.origin + '/e2e-dem/{z}/{x}/{y}.png',
        attribution: 'e2e', terrain: {encoding: 'terrarium', tileSize: 256, maxzoom: 12}};
}"""
# 위젯: 단추 id 의 꼬리가 위젯 id, 인스턴스 표에서 그 지도를 찾는다.
_WIDGET_MAP = "(id) => (window.AoTWidgetInstances[id] || {}).map"
_WIDGET_IDS = """() => Object.keys(window.AoTWidgetInstances || {}).filter(
    k => window.AoTWidgetInstances[k] && window.AoTWidgetInstances[k].map).sort()"""
_BIND_WIDGET = """(id) => window.AoTTerrainToggle.bind(
    window.AoTWidgetInstances[id].map, document.getElementById('tool-terrain-' + id), 'widget:' + id)"""
_TERRAIN_ON = "(id) => !!window.AoTWidgetInstances[id].map.getTerrain()"


class _Watch:
    def __init__(self, page):
        self.dem = 0
        self.posts = []
        page.route('**/e2e-dem/**', self._dem(page))
        # 설정 저장(POST)은 없어야 한다 — 읽기(GET)는 지도 부팅의 일부다.
        page.on('request', lambda r: self.posts.append(r.url)
                if r.method == 'POST' and '/api/geo/settings' in r.url else None)

    def _dem(self, page):
        def handle(route):
            self.dem += 1
            route.fulfill(status=200, content_type='image/png', body=_DEM_TILE.getvalue())
        return handle


def _clear_storage(page):
    page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('aot_terrain:'))"
                  ".forEach(k => localStorage.removeItem(k))")


def _open_two_maps(page, base_url):
    open_dashboard(page, base_url, F.TWO_MAP_DASHBOARD)
    page.wait_for_function(
        "() => { const v = Object.values(window.AoTWidgetInstances || {}).filter(x => x && x.map);"
        " return v.length === 2 && v.every(x => x._itemsLoaded); }", timeout=60000)
    ids = page.evaluate(_WIDGET_IDS)
    assert len(ids) == 2
    return ids


def _prepare(page, ids):
    page.evaluate(_INJECT_DEM)
    for i in ids:
        assert page.evaluate(_BIND_WIDGET, i) is True


def _open_design(page, base_url):
    page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
    page.wait_for_selector('#tool-fullscreen', timeout=25000)
    page.wait_for_function("() => !!%s" % _MAP, timeout=30000)
    page.wait_for_timeout(4000)


def test_widget_without_dem_input_hides_the_button(page, base_url):
    open_dashboard(page, base_url, F.MAP_DASHBOARD)
    page.wait_for_selector('.maplibregl-canvas', timeout=30000)
    page.wait_for_timeout(1500)
    assert page.locator('[id^=tool-terrain-]').count() == 1
    assert not page.locator('[id^=tool-terrain-]').is_visible()


def test_design_without_dem_input_hides_the_button(page, base_url):
    page.add_init_script(_TRACK_MAPS)
    _open_design(page, base_url)
    assert not page.locator('#tool-terrain').is_visible()


def test_terrain_is_per_map_off_by_default_and_restores_only_that_map(page, base_url):
    page.add_init_script(_TRACK_MAPS)
    watch = _Watch(page)
    ids = _open_two_maps(page, base_url)
    _clear_storage(page)
    a, b = ids
    _prepare(page, ids)

    # 기본 꺼짐: 눌러 보기 전에는 둘 다 꺼져 있고 고도 타일 요청이 없다.
    page.wait_for_timeout(1500)
    for i in ids:
        assert page.evaluate(_TERRAIN_ON, i) is False
        assert page.locator(f'#tool-terrain-{i}').get_attribute('aria-pressed') == 'false'
    assert watch.dem == 0

    # A 만 켠다 — B 는 그대로 꺼져 있다.
    page.locator(f'#tool-terrain-{a}').click()
    page.wait_for_function("(id) => !!window.AoTWidgetInstances[id].map.getTerrain()", arg=a, timeout=20000)
    page.wait_for_timeout(1500)
    assert page.evaluate(_TERRAIN_ON, b) is False
    assert page.locator(f'#tool-terrain-{b}').get_attribute('aria-pressed') == 'false'
    assert page.locator(f'#tool-terrain-{a}').get_attribute('aria-pressed') == 'true'
    assert watch.dem > 0

    # 새로고침: A 만 복원된다. B 와 /geo/design 은 고도 타일을 받지 않는다.
    page.reload(wait_until='domcontentloaded')
    watch.dem = 0
    page.wait_for_function(
        "() => { const v = Object.values(window.AoTWidgetInstances || {}).filter(x => x && x.map);"
        " return v.length === 2 && v.every(x => x._itemsLoaded); }", timeout=60000)
    _prepare(page, ids)
    page.wait_for_function("(id) => !!window.AoTWidgetInstances[id].map.getTerrain()", arg=a, timeout=20000)
    page.wait_for_timeout(1500)
    assert page.evaluate(_TERRAIN_ON, b) is False
    assert page.locator(f'#tool-terrain-{a}').get_attribute('aria-pressed') == 'true'

    watch.dem = 0   # 위젯 A 가 받은 타일은 셈에서 뺀다
    _open_design(page, base_url)
    page.evaluate(_INJECT_DEM)
    page.wait_for_timeout(1500)
    assert not page.evaluate("() => !!document.querySelector('#tool-terrain.active')")
    assert watch.dem == 0

    # 끄고 새로고침하면 꺼짐으로 남는다.
    page.go_back(wait_until='domcontentloaded')
    ids = _open_two_maps(page, base_url)
    _prepare(page, ids)
    page.wait_for_function("(id) => !!window.AoTWidgetInstances[id].map.getTerrain()", arg=a, timeout=20000)
    page.locator(f'#tool-terrain-{a}').click()
    page.wait_for_function("(id) => !window.AoTWidgetInstances[id].map.getTerrain()", arg=a, timeout=20000)
    page.reload(wait_until='domcontentloaded')
    ids = _open_two_maps(page, base_url)
    _prepare(page, ids)
    page.wait_for_timeout(8000)   # 복원 안전망(6초)이 지나도 켜지지 않아야 한다
    for i in ids:
        assert page.evaluate(_TERRAIN_ON, i) is False

    # 전역 설정은 한 번도 저장하지 않았다.
    assert watch.posts == []


def test_design_button_toggles_only_its_own_map_and_restores(page, base_url):
    page.add_init_script(_TRACK_MAPS)
    watch = _Watch(page)
    _open_design(page, base_url)
    _clear_storage(page)
    page.evaluate(_INJECT_DEM)
    # 페이지가 실제로 넘기는 값(호환 래퍼)으로 묶는다.
    bind = "() => window.AoTTerrainToggle.bind(window.geoDesign.map, document.getElementById('tool-terrain'), 'geo_design')"
    assert page.evaluate(bind) is True
    btn = page.locator('#tool-terrain')
    assert btn.is_visible()
    assert btn.get_attribute('aria-pressed') == 'false'
    assert watch.dem == 0

    btn.click()
    page.wait_for_function("() => !!%s.getTerrain()" % _MAP, timeout=20000)
    assert btn.get_attribute('aria-pressed') == 'true'
    assert watch.dem > 0
    assert page.evaluate("() => localStorage.getItem('aot_terrain:geo_design')") == '1'

    # 새로고침하면 복원된다.
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function("() => !!%s" % _MAP, timeout=30000)
    page.wait_for_timeout(3000)
    page.evaluate(_INJECT_DEM)
    assert page.evaluate(bind) is True
    page.wait_for_function("() => !!%s.getTerrain()" % _MAP, timeout=20000)

    btn.click()
    page.wait_for_function("() => !%s.getTerrain()" % _MAP, timeout=20000)
    assert page.evaluate("() => localStorage.getItem('aot_terrain:geo_design')") is None
    assert watch.posts == []


def test_blocked_local_storage_still_toggles_on_this_screen(page, base_url):
    _Watch(page)
    ids = _open_two_maps(page, base_url)
    a = ids[0]
    page.evaluate("""() => {
        Storage.prototype.getItem = function () { throw new Error('blocked'); };
        Storage.prototype.setItem = function () { throw new Error('blocked'); };
        Storage.prototype.removeItem = function () { throw new Error('blocked'); };
    }""")
    _prepare(page, [a])
    page.locator(f'#tool-terrain-{a}').click()
    page.wait_for_function("(id) => !!window.AoTWidgetInstances[id].map.getTerrain()", arg=a, timeout=20000)
