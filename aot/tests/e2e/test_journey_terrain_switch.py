# coding=utf-8
"""L2 — 물 회로 **지형(DEM) 바꾸기** 여정: 비교 → 바꾸기 → 되돌리기.

장비 드로어의 압력 블록에서 사람이 하는 그대로 지난다.

  1. "다른 지형 비교" 를 누른다 → 후보 타일을 받는 동안 안내가 나온다
  2. 끝나면 이전 → 이후 숫자와 바뀌는 구간이 나온다 (아무것도 저장되지 않았다)
  3. "이 지형으로 바꾸기" → "지형이 바뀌어 다시 계산됨" 한 줄, 압력이 새 지형으로 다시 풀린다
  4. "되돌리기" → 원래 DEM 이 켜진 채로 돌아온다

단위·JS 하네스 시험은 서버 규칙과 마크업을 각각 본다. 이 여정이 보는 것은 **둘이 실제 앱 화면에서 맞물리는가**다 —
버튼이 서버를 부르고, 서버가 합성 고도 타일을 받아 풀고, 드로어가 그 결과를 다시 그린다.

타일은 컴포즈의 `dem-tiles` 서비스(`dem_server.py`)가 준다. 고도가 일차식이라 기대 경사 길이를 **계산으로** 낸다
(앱이 낸 숫자를 그대로 믿지 않는다). 시드: 완만한 DEM 이 켜져 있고 가파른 DEM 이 비교 후보다.
"""
import math
import os
import re
import time

import pytest

from aot.tests.e2e import dem_server as D
from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import csrf_headers

pytestmark = pytest.mark.e2e

MAP_SETTLE_MS = 6000
ARTIFACT_DIR = os.path.join('.local', 'e2e-artifacts')

#: 시드 배치(`seed._seed_water_terrain`)의 배관 — (길이 m, 가는 방향 'x'=동 / 'z'=북)
PIPES = ((80.0, 'x'), (60.0, 'z'))
SEGMENTS = 4        # 펌프 쪽 주배관 구간 하나 + 가지 세 구간 — 대지·구역 양쪽에 보여도 4 여야 한다


def _slant_total(profile):
    """프로필의 배관 경사 길이 합 — 일차 고도라 구간마다 √(L² + (경사·L)²)."""
    sx, sz = D.PROFILES[profile]
    return sum(length * math.sqrt(1 + (sx if axis == 'x' else sz) ** 2) for length, axis in PIPES)


def _numbers(text):
    return [float(v) for v in re.findall(r'-?\d+(?:\.\d+)?', text)]


@pytest.fixture
def design(page, base_url, admin_http):
    """설계 지도의 장비 드로어를 연 페이지. 끝나면 지형을 시작 상태(완만한 DEM)로 되돌린다."""
    page.route(f'{F.DEM_TILE_BASE}/**', lambda route: route.fulfill(status=404))   # 브라우저는 타일을 받지 않는다(서버가 받는다)

    def open_design():
        with page.expect_request(lambda r: '/api/geo/overlays?map_uuid=' in r.url, timeout=30000) as req:
            page.goto(f'{base_url}/geo/design', wait_until='domcontentloaded')
        page.wait_for_selector('#tool-fullscreen', timeout=25000)
        page.wait_for_timeout(MAP_SETTLE_MS)
        return re.search(r'map_uuid=([0-9a-f-]+)', req.value.url).group(1)

    map_uuid = open_design()
    api = f'{base_url}/api/geo/water_net/terrain_switch'
    # 시작 상태: 완만한 DEM 을 레이어 관리자의 켜기 경로(운영자가 하는 그대로)로 켠다. 시드는 DEM 입력을 꺼 둔다.
    start = admin_http.get(f'{api}?map_uuid={map_uuid}', timeout=30).json()
    assert start['current'] is None, f'시작 전에 켜진 DEM 이 있습니다: {start["current"]}'
    gentle = next(c['id'] for c in start['candidates'] if c['name'] == F.DEM_GENTLE)
    _set_layer(admin_http, base_url, gentle, True)
    # 지금 DEM 의 지형 선계산이 끝나 있어야 한다 — 막 올린 스택에서는 백그라운드가 아직 받는 중이고(압력 블록이 'warming'),
    # 그동안 끝나면서 드로어가 다시 그려져 누르려던 단추가 흔들린다. 끝난 뒤 다시 열어 안정된 화면에서 시작한다.
    deadline = time.time() + 180
    while _active_dem_name(admin_http, base_url, map_uuid) != F.DEM_GENTLE:
        assert time.time() < deadline, '지금 DEM 의 지형 선계산이 3분 안에 끝나지 않았습니다'
        time.sleep(3)
    map_uuid = open_design()

    page.get_by_text('장비', exact=True).first.click()
    page.wait_for_selector('[data-terrain-switch]', timeout=30000)
    page.map_uuid = map_uuid
    yield page

    # 어느 단계에서 실패해도 다음 실행·다른 여정이 같은 상태에서 시작하게 한다 — 바꾼 것을 되돌리고 DEM 입력을 모두 끈다.
    state = admin_http.get(f'{api}?map_uuid={map_uuid}', timeout=30).json()
    if state.get('switched'):
        admin_http.post(f'{api}/revert', json={'map_uuid': map_uuid},
                        headers=csrf_headers(admin_http, base_url), timeout=60)
        state = admin_http.get(f'{api}?map_uuid={map_uuid}', timeout=30).json()
    if state.get('current'):
        _set_layer(admin_http, base_url, state['current']['id'], False)


def _set_layer(admin_http, base_url, layer_id, on):
    """레이어 관리자의 켜기·끄기 — 화면 단추가 보내는 그 폼."""
    resp = admin_http.post(f'{base_url}/geo/input/submit',
                           data={'input_id': layer_id, 'input_activate' if on else 'input_deactivate': '1'},
                           headers=csrf_headers(admin_http, base_url), timeout=60)
    assert resp.status_code == 200, f'DEM 입력 {"켜기" if on else "끄기"}가 HTTP {resp.status_code}'
    body = resp.json()['data']
    assert not body['messages']['error'], body['messages']['error']


def _block(page):
    return page.locator('[data-terrain-switch]')


def _row(page, label):
    """지형 블록(또는 압력 블록) 안에서 제목이 `label` 인 행."""
    return page.locator('.aot-geo-pressure .aot-modal-option-row').filter(
        has=page.locator('.aot-modal-option-label', has_text=label)).first


def _shot(page, name):
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    # 진단용 캡처다. 비교→미리보기→바꾸기→되돌리기에서 블록이 통째로 다시 그려지며
    # 잠깐 DOM 에서 떨어질 수 있는데, 그걸 맞추려 스크롤하다 던지면 여정이 통째로 깨졌다.
    # 블록이 없으면 그냥 전체를 찍는다 — 스크린샷은 단언이 아니다.
    try:
        _block(page).scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    page.screenshot(path=os.path.join(ARTIFACT_DIR, f'terrain-switch-{name}.png'))


def _layout_problems(page):
    """압력 블록의 행마다: 제목·힌트와 컨트롤이 서로 겹치지 않고, 아무것도 드로어 밖으로 삐져나가지 않는다.

    DEM 이름이 든 긴 글이 컨트롤 칸(줄지 않는다)을 넘쳐 옆 힌트 위로 번지던 것(2026-11-04, '되돌리기' 행)을 잡는다.
    """
    return page.evaluate("""() => {
        const out = [];
        const dialog = document.querySelector('[data-terrain-switch]').closest('.modal-dialog').getBoundingClientRect();
        const hit = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2
                           && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2;
        for (const row of document.querySelectorAll('.aot-geo-pressure .aot-modal-option-row')) {
            const label = row.querySelector('.aot-modal-option-label, .aot-geo-pressure-note');
            const ctrl = row.querySelector('.aot-modal-option-control');
            const name = (label ? label.innerText : row.innerText).trim().slice(0, 40);
            if (label && ctrl && hit(label.getBoundingClientRect(), ctrl.getBoundingClientRect())) out.push('겹침: ' + name);
            for (const el of row.querySelectorAll('button, select, span, .aot-modal-body-text')) {
                const r = el.getBoundingClientRect();
                if (r.width && (r.right > dialog.right + 1 || r.left < dialog.left - 1)) out.push('밖으로 넘침: ' + name + ' / ' + el.tagName);
            }
            // 제목이 빈 행(동작 단추 줄)은 컨트롤 칸 왼쪽이 비어 있어 단추가 칸보다 넓어도 아무것도 덮지 않는다.
            if (ctrl && label && label.innerText.trim()) {
                for (const el of ctrl.children) {
                    const r = el.getBoundingClientRect(), c = ctrl.getBoundingClientRect();
                    if (r.width && (r.left < c.left - 1 || r.right > c.right + 1)) out.push('컨트롤 칸을 넘침: ' + name + ' / ' + el.innerText.trim().slice(0, 30));
                }
            }
        }
        return out;
    }""")


def _terrain(admin_http, base_url, map_uuid):
    return admin_http.get(f'{base_url}/api/geo/water_net/terrain_switch?map_uuid={map_uuid}', timeout=30).json()


def _active_dem_name(admin_http, base_url, map_uuid):
    """압력 점검 응답이 **실제로 쓴** DEM 이름 — 화면 글이 아니라 서버의 계산 근거를 본다."""
    body = admin_http.get(f'{base_url}/api/geo/water_net?map_uuid={map_uuid}', timeout=60).json()
    names = {(a.get('terrain') or {}).get('dem_name') for a in body.get('areas') or [] if a.get('terrain')}
    assert len(names) <= 1, f'구역마다 다른 DEM 으로 풀렸습니다: {names}'
    return next(iter(names), None)


def _bar_range(text):
    """'3.60-4.43 bar' → (3.6, 4.43)."""
    m = re.search(r'(\d+\.\d+)\s*-\s*(\d+\.\d+)\s*bar', text)
    assert m, f'압력 범위를 읽지 못했습니다: {text!r}'
    return float(m.group(1)), float(m.group(2))


def test_compare_switch_and_revert_a_terrain(design, admin_http, base_url):
    page, map_uuid = design, design.map_uuid

    # 시작: 완만한 DEM 이 켜져 있고, 가파른 DEM 이 비교 후보다.
    start = _terrain(admin_http, base_url, map_uuid)
    assert start['current']['name'] == F.DEM_GENTLE and not start['switched']
    assert [c['name'] for c in start['candidates']] == [F.DEM_STEEP]
    assert _row(page, '지형 입력').inner_text().count(F.DEM_GENTLE) == 1
    assert _active_dem_name(admin_http, base_url, map_uuid) == F.DEM_GENTLE
    assert _row(page, '노즐 압력').count() >= 1

    # 1) 비교를 시작하면 후보 타일을 받는 동안 안내가 나온다.
    page.get_by_role('button', name='다른 지형 비교').click()
    warming = page.locator('.aot-geo-pressure-note[role="status"]', has_text=F.DEM_STEEP)
    warming.wait_for(timeout=10000)
    assert '받는 중' in warming.inner_text()
    assert page.locator('[data-terrain-pick]').input_value() == start['candidates'][0]['id']
    _shot(page, '1-warming')

    # 2) 끝나면 이전 → 이후. 서버가 타일을 받아 두 지형으로 풀었다.
    page.get_by_role('button', name='이 지형으로 바꾸기').wait_for(timeout=120000)
    total = _row(page, '경사 길이 합').inner_text()
    before, after = _numbers(total.split('→')[0])[0], _numbers(total.split('→')[1])[0]
    assert before == pytest.approx(_slant_total('gentle'), abs=0.06), total
    assert after == pytest.approx(_slant_total('steep'), abs=0.06), total
    assert after > before

    # 같은 제목의 행이 둘이다 — 지금 압력(화살표 없음)과 비교 줄(이전 → 이후). 비교 줄만 고른다.
    pressure = page.locator('.aot-geo-pressure .aot-modal-option-row').filter(
        has=page.locator('.aot-modal-option-label', has_text='노즐 압력')).filter(has_text='→').first.inner_text()
    bar_before, bar_after = _bar_range(pressure.split('→')[0] + 'bar'), _bar_range(pressure.split('→')[1])
    assert bar_after[0] < bar_before[0], f'가파른 오르막인데 압력이 떨어지지 않았습니다: {pressure!r}'

    changed = page.locator('.aot-geo-pressure a[data-toggle="collapse"]', has_text='바뀌는 구간')
    assert f'({SEGMENTS})' in changed.inner_text(), (
        f'바뀌는 구간이 {SEGMENTS}개여야 합니다(대지·구역에 같은 구간이 두 번 들어도 한 번만 센다): {changed.inner_text()!r}')
    changed.click()
    page.wait_for_timeout(500)
    rows = page.locator('#design-terrain-switch-seg .aot-modal-option-row')
    assert rows.count() == SEGMENTS
    assert re.search(r'→', rows.first.inner_text())
    _shot(page, '2-preview')
    assert _layout_problems(page) == []

    # 미리보기는 아무것도 바꾸지 않는다.
    assert _terrain(admin_http, base_url, map_uuid)['current']['name'] == F.DEM_GENTLE
    assert _active_dem_name(admin_http, base_url, map_uuid) == F.DEM_GENTLE

    # 3) 바꾸면 한 줄로 알리고, 압력을 새 지형으로 다시 읽는다.
    page.get_by_role('button', name='이 지형으로 바꾸기').click()
    switched = _row(page, '지형이 바뀌어 다시 계산됨')
    switched.wait_for(timeout=30000)
    # 무엇에서 무엇으로 바뀌었는지는 아래 한 줄 문장이 말한다. 단추 글은 짧고(되돌리기), 보조기기용 이름에 돌아갈 DEM 이 든다.
    note = page.locator('.aot-geo-pressure-note', has_text=f'{F.DEM_GENTLE} → {F.DEM_STEEP}')
    assert note.is_visible()
    assert switched.get_by_role('button', name='되돌리기').inner_text() == '되돌리기'
    assert page.get_by_role('button', name=f'{F.DEM_GENTLE}(으)로 되돌리기').is_visible()
    assert _terrain(admin_http, base_url, map_uuid)['current']['name'] == F.DEM_STEEP
    assert _active_dem_name(admin_http, base_url, map_uuid) == F.DEM_STEEP
    # 드로어의 압력 줄이 새 지형 값으로 다시 그려졌다.
    page.wait_for_function(
        """(lo) => { const el = document.querySelector('.aot-geo-pressure');
                     return el && /(\\d+\\.\\d+) - (\\d+\\.\\d+)\\s*bar/.test(el.innerText)
                       && parseFloat(el.innerText.match(/(\\d+\\.\\d+) - (\\d+\\.\\d+)\\s*bar/)[1]) <= lo + 0.01; }""",
        arg=bar_after[0], timeout=60000)
    _shot(page, '3-switched')
    assert _layout_problems(page) == []

    # 4) 되돌리면 그때 켜져 있던 DEM 이 그대로 돌아온다.
    page.get_by_role('button', name=f'{F.DEM_GENTLE}(으)로 되돌리기').click()
    # 비교 단추는 바꾼 뒤에도 보인다 — 되돌려졌다는 신호는 "바뀌어 다시 계산됨" 줄이 사라지는 것이다.
    _row(page, '지형이 바뀌어 다시 계산됨').wait_for(state='detached', timeout=30000)
    page.get_by_role('button', name='다른 지형 비교').wait_for(timeout=30000)
    back = _terrain(admin_http, base_url, map_uuid)
    assert back['current']['name'] == F.DEM_GENTLE and back['switched'] is None
    assert [c['name'] for c in back['candidates']] == [F.DEM_STEEP]
    assert _active_dem_name(admin_http, base_url, map_uuid) == F.DEM_GENTLE
    assert _row(page, '지형 입력').inner_text().count(F.DEM_GENTLE) == 1


def test_the_map_stays_visible_beside_the_drawer(design):
    """지형 비교 중에도 지도는 드로어에 가려지지 않는다 — 비교는 모달이 아니라 드로어 안에서 한다."""
    page = design
    page.get_by_role('button', name='다른 지형 비교').click()
    page.wait_for_selector('[data-terrain-pick]', timeout=10000)

    geometry = page.evaluate("""() => {
        const rect = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; };
        const canvas = document.querySelector('.maplibregl-canvas');
        const block = document.querySelector('[data-terrain-switch]');
        // 드로어 패널 = 지형 블록을 품은 `.modal-dialog`(고정 위치). 바깥 `.modal` 은 화면 전체를 덮는 껍데기지만
        // 클릭을 지도로 흘려보낸다(pointer-events: none).
        const dialog = block.closest('.modal-dialog');
        return {map: rect(canvas), drawer: dialog ? rect(dialog) : null, view: window.innerWidth,
                fixed: !!dialog && getComputedStyle(dialog).position === 'fixed',
                backdrop: !!document.querySelector('.modal-backdrop.show')};
    }""")
    assert geometry['drawer'] and geometry['fixed'], '지형 블록이 드로어 패널 안에 있지 않습니다'
    assert not geometry['backdrop'], '지형 비교가 어두운 막을 깔았습니다 — 지도를 가립니다'
    assert geometry['map']['r'] <= geometry['drawer']['l'] + 1, (
        f'지도가 드로어와 겹칩니다: {geometry}')
    assert geometry['map']['r'] - geometry['map']['l'] >= 400, f'지도가 너무 좁게 눌렸습니다: {geometry}'
    # 지도의 보이는 가운데 점이 드로어 밖에 있다 — 눌러 볼 수 있다.
    center_x = (geometry['map']['l'] + geometry['map']['r']) / 2
    hit = page.evaluate("(x) => document.elementFromPoint(x, 500).closest('.maplibregl-map') !== null", center_x)
    assert hit, '지도 가운데에서 지도가 눌리지 않습니다'
    page.get_by_role('button', name='취소').click()
    page.get_by_role('button', name='다른 지형 비교').wait_for(timeout=10000)


def test_the_blocks_fit_a_phone_width(design):
    """폰 폭(375 px)에서도 비교 줄·바꾼 뒤 줄이 넘치거나 겹치지 않는다."""
    page = design
    page.set_viewport_size({'width': 375, 'height': 812})
    page.wait_for_timeout(800)
    page.get_by_role('button', name='다른 지형 비교').click()
    page.get_by_role('button', name='이 지형으로 바꾸기').wait_for(timeout=120000)
    _shot(page, 'm1-preview')
    assert _layout_problems(page) == []

    page.get_by_role('button', name='이 지형으로 바꾸기').click()
    _row(page, '지형이 바뀌어 다시 계산됨').wait_for(timeout=30000)
    _shot(page, 'm2-switched')
    assert _layout_problems(page) == []
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), '가로 스크롤이 생겼습니다'
