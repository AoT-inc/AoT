# coding=utf-8
"""L2 · J6b — 시퀀스 위젯에서 **그룹은 한 블록으로만** 움직이는가.

같은 그룹 이름의 단계는 한 시간 슬롯을 나눠 **동시에** 켜진다. 그래서 그룹이
목록에서 쪼개지면(멤버 사이에 단독 단계가 끼면) 실행 순서의 뜻이 달라진다.
위젯의 드래그는 이것을 원천적으로 막도록 짜여 있다 —

  * 그룹 멤버 아무거나 잡아도 **멤버 전부가 함께** 움직인다.
  * 놓는 자리는 **다른 블록 전체의 앞이나 뒤**뿐이다. 그룹 한가운데에 놓아도
    그룹 앞(또는 뒤)에 꽂힌다.

그리고 드래그한 순서는 `/function_save_order` 로 저장돼 컨트롤러의 실행 순서
(`Actions.position` ← `gridstack_y`)가 된다. 위젯은 그릴 때 그룹 멤버를 붙여
그리므로 **위젯 화면만 봐서는 DB 가 쪼개졌는지 모른다** — 그래서 끝에 함수 설정
화면(`gs-y` = 저장된 순서 그대로)에서도 확인한다.

단계 이름이 모두 달라 이름으로 순서를 읽는다(J6 은 라벨이 같아 id 로 읽었다).
시드: 단독(First) · 그룹 A · 그룹 B · 단독(Last). 끝나면 원래 순서로 되돌린다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import csrf_headers
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e

SOLO_FIRST, PAIR_A, PAIR_B, SOLO_LAST = (name for name, _ in F.GROUP_SEQUENCE_STEPS)
SEED_ORDER = [SOLO_FIRST, PAIR_A, PAIR_B, SOLO_LAST]


def _open_widget(page, base_url):
    open_dashboard(page, base_url, F.GROUP_DASHBOARD)
    box = page.locator('.seq-widget-container').first
    box.wait_for(timeout=20000)
    wid = box.get_attribute('data-wid')
    page.wait_for_function(
        """(sel) => document.querySelectorAll(sel).length > 0""",
        arg=f'#seq-list-{wid} .seq-list-item', timeout=20000)
    return wid, box.get_attribute('data-fid')


def _rows(page, wid):
    """위젯 목록의 행 — 위에서 아래로. 이 순서가 곧 실행 순서다."""
    return page.evaluate("""(wid) => Array.from(
            document.querySelectorAll('#seq-list-' + wid + ' .seq-list-item'))
        .map(r => ({
            uid: r.dataset.uid,
            block: r.dataset.block,
            name: r.querySelector('.seq-col-name').innerText.trim(),
        }))""", wid)


def _names(rows):
    return [r['name'] for r in rows]


def _drag_row(page, wid, name, to_y):
    """이름 칸을 눌러 잡고 화면 높이 `to_y` 까지 천천히 끌어 놓는다."""
    cell = page.locator(f'#seq-list-{wid} .seq-list-item .seq-col-name',
                        has_text=name).first
    cell.scroll_into_view_if_needed()
    box = cell.bounding_box()
    assert box, f'{name} 행을 찾지 못했습니다'
    x = box['x'] + 40
    y = box['y'] + box['height'] / 2

    page.mouse.move(x, y)
    page.mouse.down()
    for i in range(1, 21):
        page.mouse.move(x, y + (to_y - y) * i / 20)
        page.wait_for_timeout(25)
    page.mouse.up()


def _row_box(page, wid, name):
    return page.locator(f'#seq-list-{wid} .seq-list-item',
                        has_text=name).first.bounding_box()


def _drag_and_save(page, wid, name, to_y):
    with page.expect_response(
            lambda r: '/function_save_order' in r.url and r.request.method == 'POST',
            timeout=20000) as saved:
        _drag_row(page, wid, name, to_y)
    assert saved.value.status == 200 and saved.value.json().get('status') == 'success', (
        f'순서 저장이 실패했습니다: HTTP {saved.value.status} {saved.value.text()[:200]}')


def _pair_is_one_block(names):
    a, b = names.index(PAIR_A), names.index(PAIR_B)
    return b == a + 1


def _saved_order_ids(page, base_url):
    """함수 설정 화면의 단계 순서(id) — 저장된 `gridstack_y` 그대로, 그룹으로
    다시 붙이지 않는다. 컨트롤러가 돌리는 순서가 이것이다."""
    page.goto(f'{base_url}/function', wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1500)
    card = page.locator('.grid-stack-item').filter(
        has=page.locator(f'input[value="{F.GROUP_SEQUENCE}"]')).first
    card.locator('a.aot-function-settings-open').first.click()
    page.wait_for_selector('[id^="mod_action_"]', timeout=20000)
    page.wait_for_timeout(1200)
    return page.evaluate("""() => Array.from(document.querySelectorAll('[id^="mod_action_"]'))
        .filter(el => el.getBoundingClientRect().height > 0)
        .map(el => ({id: el.id.replace('mod_action_', ''),
                     y: parseInt(el.getAttribute('gs-y') || '0')}))
        .sort((a, b) => a.y - b.y)
        .map(s => s.id)""")


def _restore(admin_http, base_url, fid, rows_by_name):
    """시드 순서로 되돌린다 — 위젯이 부르는 그 경로로."""
    order = {rows_by_name[name]: i for i, name in enumerate(SEED_ORDER)}
    resp = admin_http.post(f'{base_url}/function_save_order',
                           json={'function_id': fid, 'order': order},
                           headers=csrf_headers(admin_http, base_url), timeout=30)
    assert resp.status_code == 200 and resp.json().get('status') == 'success', (
        f'순서를 되돌리지 못했습니다 — 다음 검사가 바뀐 픽스처로 돈다: '
        f'{resp.status_code} {resp.text[:200]}')


def _no_modal_opened(page):
    """드래그가 끝난 칸의 이름·시간 모달이 덩달아 열리면 안 된다."""
    return page.evaluate("""() => !Array.from(document.querySelectorAll('.seq-step-modal'))
        .some(el => el.offsetParent !== null
                    && getComputedStyle(el).display !== 'none'
                    && getComputedStyle(el).visibility !== 'hidden')""")


def test_the_group_is_drawn_as_one_block(page, base_url):
    """받침 — 시드 순서대로, 그룹 둘은 같은 블록으로 붙어 그려진다."""
    wid, _ = _open_widget(page, base_url)
    rows = _rows(page, wid)
    assert _names(rows) == SEED_ORDER, f'시드 순서가 아닙니다: {_names(rows)}'
    blocks = {r['name']: r['block'] for r in rows}
    assert blocks[PAIR_A] == blocks[PAIR_B], (
        f'같은 그룹인데 블록이 다릅니다: {blocks[PAIR_A]} / {blocks[PAIR_B]}')
    assert blocks[SOLO_FIRST] != blocks[PAIR_A] != blocks[SOLO_LAST], (
        '단독 단계가 그룹 블록에 묶여 있습니다')


def test_grabbing_one_member_moves_the_whole_group(page, base_url, admin_http):
    """두 번째 멤버(B)를 잡아 맨 위로 — A 까지 함께, 그 순서 그대로 올라간다."""
    wid, fid = _open_widget(page, base_url)
    ids = {r['name']: r['uid'] for r in _rows(page, wid)}
    try:
        top = _row_box(page, wid, SOLO_FIRST)
        _drag_and_save(page, wid, PAIR_B, top['y'] + 4)
        assert _no_modal_opened(page), '드래그가 끝난 칸의 모달이 열렸습니다'

        moved = _names(_rows(page, wid))
        assert moved == [PAIR_A, PAIR_B, SOLO_FIRST, SOLO_LAST], (
            f'그룹이 통째로 올라가지 않았습니다: {moved}')

        # 다시 열어도 그 순서 — 화면이 아니라 저장된 것을 읽는다.
        page.wait_for_timeout(1200)
        wid, _ = _open_widget(page, base_url)
        reopened = _names(_rows(page, wid))
        assert reopened == moved, (
            f'다시 열었더니 순서가 다릅니다.\n  옮긴 직후: {moved}\n  다시 열자: {reopened}')

        saved = _saved_order_ids(page, base_url)
        assert saved == [ids[n] for n in moved], (
            f'위젯과 실행 순서(함수 설정)가 다릅니다: '
            f'{[next(k for k, v in ids.items() if v == i) for i in saved]}')
    finally:
        _restore(admin_http, base_url, fid, ids)


def test_dropping_into_the_group_lands_outside_it(page, base_url, admin_http):
    """단독 단계를 그룹 한가운데(A 와 B 사이)에 놓아도 그룹은 쪼개지지 않는다."""
    wid, fid = _open_widget(page, base_url)
    ids = {r['name']: r['uid'] for r in _rows(page, wid)}
    try:
        between = _row_box(page, wid, PAIR_B)['y']   # A 와 B 의 경계
        _drag_and_save(page, wid, SOLO_LAST, between)
        assert _no_modal_opened(page), '드래그가 끝난 칸의 모달이 열렸습니다'

        moved = _names(_rows(page, wid))
        assert moved != SEED_ORDER, f'단계가 움직이지 않았습니다: {moved}'
        assert _pair_is_one_block(moved), f'그룹이 쪼개졌습니다: {moved}'

        page.wait_for_timeout(1200)
        saved = _saved_order_ids(page, base_url)
        saved_names = [next(k for k, v in ids.items() if v == i) for i in saved]
        assert _pair_is_one_block(saved_names), (
            f'위젯은 붙여 그리지만 **저장된** 실행 순서에서 그룹이 쪼개졌습니다: '
            f'{saved_names}')
        assert saved_names == moved, (
            f'위젯과 실행 순서가 다릅니다.\n  위젯: {moved}\n  저장: {saved_names}')
    finally:
        _restore(admin_http, base_url, fid, ids)
