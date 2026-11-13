# coding=utf-8
"""L2 — 지도 카메라: 우클릭 회전 방향 · 3D 기울기 상한.

* 회전: MapLibre 기본(aroundCenter)은 화면 가운데 줄을 지나면 방향이 뒤집힌다. 같은 방향으로
  끌면 어디를 잡았든 bearing 이 한 방향으로만 변해야 한다(±180 경계는 이어서 센다).
* 기울기 상한은 2D·3D 모두 60°. 3D 줌 17 이상에서 팬으로 움직여도 줌·기울기는 프레임 사이에 변하지 않는다.

"""
import io

import pytest
from PIL import Image

from aot.tests.e2e.test_journey_map_terrain_button import (
    _DEM_TILE, _INJECT_DEM, _MAP, _TRACK_MAPS, _clear_storage, _open_design)

pytestmark = pytest.mark.e2e


def _ramp_tile():
    # terrarium: 고도 = (R*256 + G + B/256) - 32768. 가로로 올라가는 비탈(픽셀당 8 m).
    img = Image.new('RGB', (256, 256))
    px = img.load()
    for x in range(256):
        v = 32768 + x * 8 + 200
        for y in range(256):
            px[x, y] = (v >> 8, v & 255, 0)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()

_DRAG = """async ([x0, y0, dx, dy, steps]) => {
  const m = %s; const cv = m.getCanvas(); const r = cv.getBoundingClientRect();
  const ev = (t, x, y, b) => new MouseEvent(t, {bubbles: true, cancelable: true, view: window,
      clientX: r.left + x, clientY: r.top + y, button: 2, buttons: b});
  const out = [];
  cv.dispatchEvent(ev('mousedown', x0, y0, 2));
  for (let i = 1; i <= steps; i++) {
    document.dispatchEvent(ev('mousemove', x0 + dx * i / steps, y0 + dy * i / steps, 2));
    // 이벤트마다 지도가 그 프레임을 처리할 때까지 기다린다. 부하가 큰 CI 에서 이동 몇 번이 한 프레임에
    // 뭉쳐 처리되면 한 걸음이 180° 를 넘어 ±180 이어 세기가 방향을 거꾸로 읽는다(2026-11-05 나스 CI).
    await new Promise(res => setTimeout(res, 20));
    await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
    out.push(m.getBearing());
  }
  document.dispatchEvent(ev('mouseup', x0 + dx, y0 + dy, 0));
  return out;
}""" % _MAP


def _unwrapped_steps(series):
    """±180 경계를 이어서 본 연속 변화량."""
    steps, prev = [], 0.0
    for b in series:
        d = (b - prev + 180.0) % 360.0 - 180.0
        steps.append(d)
        prev = b
    return steps


def _open(page, base_url):
    page.add_init_script(_TRACK_MAPS)
    page.route('**/e2e-dem/**', lambda route: route.fulfill(
        status=200, content_type='image/png', body=_DEM_TILE.getvalue()))
    _open_design(page, base_url)
    page.evaluate("() => { const m = %s; m.jumpTo({pitch: 45, bearing: 0}); }" % _MAP)


@pytest.mark.parametrize('y0', [60, 300, 330, 560])
def test_right_drag_rotates_one_way_wherever_it_is_grabbed(page, base_url, y0):
    _open(page, base_url)
    size = page.evaluate("() => { const c = %s.getCanvas(); return [c.clientWidth, c.clientHeight]; }" % _MAP)
    w = size[0]
    page.evaluate("() => %s.jumpTo({bearing: 0, pitch: 45})" % _MAP)
    # 한 걸음이 몇 도 안 되게 짧게 끈다 — 부하로 몇 걸음이 뭉쳐도 180° 를 넘지 않는다(±180 이어 세기가 안전).
    series = page.evaluate(_DRAG, [20, min(y0, size[1] - 20), min(w - 40, 240), 0, 24])
    steps = _unwrapped_steps(series)
    assert all(s > 0 for s in steps), (y0, series)
    # 감도도 한 가지다 — 가운데 줄을 지나도 갑자기 달라지지 않는다.
    assert max(steps) - min(steps) < max(1.0, 0.1 * max(steps)), (y0, steps)


def test_pitch_limit_is_60_in_2d_and_3d_and_pan_does_not_shake(page, base_url):
    _open(page, base_url)
    _clear_storage(page)
    ramp = _ramp_tile()
    page.route('**/e2e-dem/**', lambda route: route.fulfill(
        status=200, content_type='image/png', body=ramp))
    assert page.evaluate("() => %s.getMaxPitch()" % _MAP) == 60
    page.evaluate(_INJECT_DEM)
    page.evaluate("() => window.AoTMapSeam.enableTerrain(%s)" % _MAP)
    page.wait_for_function("() => !!%s.getTerrain()" % _MAP, timeout=20000)
    page.wait_for_timeout(3000)
    assert page.evaluate("() => %s.getMaxPitch()" % _MAP) == 60
    page.evaluate("() => %s.jumpTo({pitch: 85})" % _MAP)
    assert page.evaluate("() => %s.getPitch()" % _MAP) == 60

    series = page.evaluate("""async () => {
        const m = %s;
        const c0 = m.getCenter();
        m.jumpTo({zoom: 17.5, pitch: 60, bearing: 30});
        await new Promise(r => setTimeout(r, 2500));
        const out = [];
        for (let i = 0; i < 60; i++) {
            m.jumpTo({center: [c0.lng + i * 0.000004, c0.lat + i * 0.000003]});
            out.push({z: m.getZoom(), p: m.getPitch(), ce: m.getCenterElevation()});
            await new Promise(r => setTimeout(r, 5));
        }
        return out;
    }""" % _MAP)
    for a, b in zip(series, series[1:]):
        assert b['z'] == a['z'] and b['p'] == a['p'], (a, b)   # 팬 중 줌·기울기는 그대로
        assert abs(b['ce'] - a['ce']) < 1.0, (a, b)            # 중심 고도는 연속

    page.evaluate("() => window.AoTMapSeam.disableTerrain(%s)" % _MAP)
    assert page.evaluate("() => %s.getMaxPitch()" % _MAP) == 60
