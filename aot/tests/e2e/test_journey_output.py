# coding=utf-8
"""L2 · J5 — 출력 카드에 조작 수단이 남아 있는가.

겨냥하는 사고는 이것이다(2026 년 실제 커밋):

  * "채널 행이 없는 출력의 On/Off 버튼이 통째로 사라지던 것"
  * "채널 0개 카드 빈 흰 상자"

둘 다 **화면을 열어 보지 않으면 모르는** 종류다. 서버는 200 을 주고, 카드도
그려지고, 다만 누를 것이 없다. 그래서 여기서는 카드가 그려졌는지와 누를 것이
있는지를 나눠서 본다.

데몬은 띄우지 않는다. 실제로 켜지는지(폐루프)는 L3 가 본다 — 이 시나리오가
겨냥하는 것은 "누를 수단이 화면에 있는가" 다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

# 시드가 만드는 세 출력. 각각 다른 모양을 시험한다.
#   multi      — 채널 여럿
#   nochannel  — OutputChannel 행이 하나도 없는 출력
#   pwm        — On/Off 가 아니라 값으로 다루는 출력
SEEDED = (F.OUTPUT_MULTI, F.OUTPUT_NOCHANNEL, F.OUTPUT_PWM)


def _cards(page):
    return page.evaluate("""() => {
        const out = {};
        for (const el of document.querySelectorAll('.grid-stack-item')) {
            const text = (el.innerText || '').trim();
            const name = text.split('\\n')[0];
            const rect = el.getBoundingClientRect();
            const controls = Array.from(
                el.querySelectorAll('button, input[type=button], input[type=submit], a.btn'))
                .map(e => (e.innerText || e.value || '').trim())
                .filter(Boolean);
            out[name] = {
                height: rect.height,
                width: rect.width,
                // 조작 수단 — On/Off 든 값 설정이든 "누를 것"이 하나도 없으면
                // 그 카드는 보이기만 하고 쓸 수 없다.
                controls: controls,
            };
        }
        return out;
    }""")


@pytest.fixture(scope='module')
def output_page(browser, storage_state, base_url):
    context = browser.new_context(
        storage_state=storage_state,
        viewport={'width': 1440, 'height': 900}, locale='ko-KR')
    page = context.new_page()
    page.goto(f'{base_url}/output', wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1500)
    yield page
    context.close()


@pytest.mark.parametrize('name', SEEDED)
def test_the_card_is_drawn_with_a_body(output_page, name):
    """카드가 그려지고, 빈 상자가 아니다."""
    cards = _cards(output_page)
    assert name in cards, f'출력 카드가 화면에 없습니다: {name} (있는 것: {list(cards)})'
    assert cards[name]['height'] > 0 and cards[name]['width'] > 0, (
        f'{name}: 카드가 0 크기입니다 — 빈 흰 상자')


@pytest.mark.parametrize('name', SEEDED)
def test_the_card_still_offers_something_to_press(output_page, name):
    """카드마다 조작 수단이 최소 하나는 남아 있어야 한다.

    켜는 방식은 출력마다 다르다(On/Off 쌍, 값 입력). 그래서 특정 버튼 문구를
    요구하지 않고 **누를 것이 있는가**만 본다 — 문구를 박아 두면 UI 를 손볼
    때마다 거짓 경보가 나고, 정작 "통째로 사라진" 사고는 이 조건으로 충분히
    걸린다.
    """
    card = _cards(output_page)[name]
    meaningful = [c for c in card['controls']
                  if c not in ('×', '닫기', '삭제', 'Close', 'Delete')]
    assert meaningful, (
        f'{name}: 카드에 누를 것이 하나도 없습니다 — 조작 수단이 사라졌습니다. '
        f'(카드 안 버튼: {card["controls"]})')
