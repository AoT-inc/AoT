# coding=utf-8
"""L2 · J6 — 시퀀스 단계 순서가 저장되는가.

시퀀스는 단계를 **위에서 아래로** 실행한다. 그래서 순서가 곧 동작이다 —
"창을 열고, 기다리고, 팬을 켠다" 가 "팬을 켜고, 기다리고, 창을 연다" 가 되면
같은 설정으로 다른 일이 벌어진다.

그런데 순서를 바꾸는 방법이 드래그이고, 저장은 놓은 뒤 0.5초 디바운스로
조용히 나간다(`/function_save_order`). 화면은 놓는 순간 이미 새 순서로 보이므로,
저장이 끊겨도 **그 자리에서는 아무 표시가 없다.** 다시 열어 봐야 드러난다.
2026 년에 이 계열(시퀀스 위젯 순서 드래그·저장)이 실제로 여러 번 깨졌다.

카드 세 장의 라벨은 모두 같다(같은 종류의 액션이다). 그래서 **id 로** 순서를
읽는다 — 라벨로 읽으면 순서가 바뀌어도 구분하지 못한다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e


def _open_sequence_settings(page, base_url):
    page.goto(f'{base_url}/function', wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1500)

    card = page.locator('.grid-stack-item').filter(
        has=page.locator(f'input[value="{F.FUNCTION_SEQUENCE}"]')).first
    card.locator('a.aot-function-settings-open').first.click()
    page.wait_for_selector('[id^="mod_action_"]', timeout=20000)
    page.wait_for_timeout(1200)


def _step_order(page):
    """액션 id 를 화면에 놓인 순서(gs-y)대로. 이것이 곧 실행 순서다."""
    return page.evaluate("""() => {
        const items = Array.from(document.querySelectorAll('[id^="mod_action_"]'))
            .filter(el => el.getBoundingClientRect().height > 0)
            .map(el => ({
                id: el.id.replace('mod_action_', ''),
                y: parseInt(el.getAttribute('gs-y') || '0'),
                h: el.getBoundingClientRect().height,
            }));
        items.sort((a, b) => a.y - b.y);
        return items;
    }""")


def _drag_first_step_to_the_end(page, steps):
    """맨 위 단계를 맨 아래로 끌어다 놓는다."""
    first = page.locator(f'#mod_action_{steps[0]["id"]}')
    handle = first.locator('.aot-action-drag').first
    handle.scroll_into_view_if_needed()
    box = handle.bounding_box()
    assert box, '단계 드래그 손잡이를 찾지 못했습니다'

    # 카드 높이 × (남은 단계 수) 만큼 내려가면 맨 아래를 지난다. 넉넉히 준다.
    distance = sum(s['h'] for s in steps[1:]) + steps[0]['h'] / 2
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    for i in range(1, 15):
        page.mouse.move(start_x, start_y + distance * i / 14)
        page.wait_for_timeout(20)
    page.mouse.up()


def test_the_seeded_steps_are_in_order(page, base_url):
    """받침 — 단계가 시드가 정한 순서대로 그려지는가.

    이것이 서면 아래 검사가 "단계가 없어서" 통과하는 일이 없다.
    """
    _open_sequence_settings(page, base_url)
    steps = _step_order(page)
    assert len(steps) == len(F.SEQUENCE_STEPS), (
        f'단계가 {len(steps)}개 보입니다 — {len(F.SEQUENCE_STEPS)}개여야 합니다')
    ys = [s['y'] for s in steps]
    assert ys == sorted(ys) and len(set(ys)) == len(ys), (
        f'단계가 같은 자리에 겹쳐 있거나 순서가 없습니다: {ys}')


def test_a_reordered_step_stays_reordered(page, base_url):
    """맨 위 단계를 맨 아래로 옮기고 → 저장되고 → 다시 열어도 그대로인가."""
    _open_sequence_settings(page, base_url)
    before = _step_order(page)
    moved_id = before[0]['id']

    with page.expect_response(
            lambda r: '/function_save_order' in r.url and r.request.method == 'POST',
            timeout=20000) as saved:
        _drag_first_step_to_the_end(page, before)
    assert saved.value.status == 200, (
        f'순서 저장이 HTTP {saved.value.status} 로 끝났습니다')

    after_drag = _step_order(page)
    assert after_drag[0]['id'] != moved_id, (
        '화면에서 단계가 움직이지 않았습니다 — 손잡이가 덮였거나 '
        '그리드가 드래그를 받지 못했습니다')

    # 여기까지는 화면 이야기다. 아래가 본론 — 다시 열었을 때 그 순서인가.
    page.wait_for_timeout(1200)   # 디바운스 저장이 끝날 틈
    _open_sequence_settings(page, base_url)
    reopened = _step_order(page)

    assert [s['id'] for s in reopened] == [s['id'] for s in after_drag], (
        f"다시 열었더니 순서가 되돌아갔습니다 — 저장이 반영되지 않았습니다.\n"
        f"  옮긴 직후: {[s['id'][:8] for s in after_drag]}\n"
        f"  다시 열자: {[s['id'][:8] for s in reopened]}")
    assert reopened[-1]['id'] == moved_id, (
        f"맨 아래로 옮긴 단계({moved_id[:8]})가 맨 아래에 없습니다: "
        f"{[s['id'][:8] for s in reopened]}")

    # 픽스처를 원래대로 되돌린다. 맨 위를 맨 아래로 보내는 것은 **회전**이라
    # 한 번 더 한다고 제자리가 되지 않는다 — 단계 수만큼 돌려야 원위치다.
    # (이미 한 번 돌렸으므로 남은 횟수는 len - 1.)
    current = reopened
    for _ in range(len(before) - 1):
        with page.expect_response(
                lambda r: ('/function_save_order' in r.url
                           and r.request.method == 'POST'),
                timeout=20000):
            _drag_first_step_to_the_end(page, current)
        page.wait_for_timeout(1200)
        current = _step_order(page)

    assert [s['id'] for s in current] == [s['id'] for s in before], (
        f"되돌리기가 끝나지 않았습니다 — 픽스처가 바뀐 채로 남습니다.\n"
        f"  처음: {[s['id'][:8] for s in before]}\n"
        f"  지금: {[s['id'][:8] for s in current]}")
