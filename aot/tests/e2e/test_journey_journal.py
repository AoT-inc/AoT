# coding=utf-8
"""L2 · J7 — 일지를 만들면 실제로 남는가.

일지는 **남에게 넘기거나 인쇄하는 문서**다. 화면에서 "만들었다" 고 말하고
실제로는 비어 있거나 사라지면, 그것을 알아차리는 시점은 대개 남에게 보낸
뒤다. 그래서 만들고 → 목록·상세에서 다시 찾는 데까지 확인한다.

일지 화면 계열(`journal_view.html`·`plot_journal.py`)은 2026 년에 fix 커밋이
많이 몰린 곳이기도 하다.
"""
import datetime

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e


def _wait_for_the_document_to_be_built(page, timeout_ms=90000):
    """일지는 **비동기로** 만들어진다.

    생성 요청이 200 을 준 직후의 화면은 "일지를 생성하고 있습니다. 이 페이지는
    자동으로 새로고침됩니다." 다. 그 상태에서 내용을 확인하면 당연히 비어 있다 —
    그것을 실패로 세면 검사가 거짓 경보를 내고, 반대로 그 화면을 통과로 세면
    **영영 완성되지 않는 일지**를 못 잡는다. 완성될 때까지 기다린 뒤에 본다.
    """
    page.wait_for_function(
        """(names) => {
            const t = document.body.innerText || '';
            if (/생성하고 있습니다|being generated|생성 중/.test(t)) return false;
            return names.some(n => t.includes(n));
        }""",
        arg=[F.GEO_PLOT, F.GEO_PLOT_SUBJECT],
        timeout=timeout_ms)


def _open_hub(page, base_url):
    page.goto(f'{base_url}/geo/journal', wait_until='domcontentloaded')
    page.wait_for_selector('#journal-generate', timeout=25000)
    page.wait_for_timeout(1500)


def test_the_seeded_plot_can_be_chosen(page, base_url):
    """받침 — 고를 것이 없으면 아래 검사는 "빈 목록이라 통과" 가 된다."""
    _open_hub(page, base_url)
    options = page.eval_on_selector(
        '#journal-plot-select',
        'el => Array.from(el.options).map(o => o.text.trim())')
    assert F.GEO_PLOT in options, (
        f'일지 화면의 구획 목록에 시드 구획이 없습니다: {options}')


def test_generating_a_journal_produces_a_document(page, base_url):
    """구획과 기간을 골라 만들면, 그 일지가 실제로 열리는가."""
    _open_hub(page, base_url)

    choose_option(page, 'journal-plot-select', F.GEO_PLOT)
    today = datetime.date.today()
    page.fill('#journal-start', (today - datetime.timedelta(days=14)).isoformat())
    page.fill('#journal-end', today.isoformat())

    with page.expect_response(
            lambda r: r.url.rstrip('/').endswith('/geo/journal')
            and r.request.method == 'POST',
            timeout=60000) as made:
        page.click('#journal-generate')

    assert made.value.status in (200, 201), (
        f'일지 생성이 HTTP {made.value.status} 로 끝났습니다')

    # 만들어진 일지가 열려야 한다. 상세로 이동하든 같은 화면에 펼치든,
    # **대상 이름이 문서 안에 있어야** 내용이 빈 것이 아니다.
    try:
        _wait_for_the_document_to_be_built(page)
    except Exception:                        # noqa: BLE001 — 시간초과도 실패다
        body = page.inner_text('body')
        raise AssertionError(
            f'일지가 완성되지 않았습니다(90초). 화면: {body[:200]!r}')


def test_a_generated_journal_survives_a_reload(page, base_url):
    """만든 일지를 주소만으로 다시 열 수 있는가 — 넘겨받는 사람이 하는 일이다."""
    _open_hub(page, base_url)
    choose_option(page, 'journal-plot-select', F.GEO_PLOT)
    today = datetime.date.today()
    page.fill('#journal-start', (today - datetime.timedelta(days=7)).isoformat())
    page.fill('#journal-end', today.isoformat())

    with page.expect_response(
            lambda r: r.url.rstrip('/').endswith('/geo/journal')
            and r.request.method == 'POST',
            timeout=60000):
        page.click('#journal-generate')
    page.wait_for_timeout(2000)

    made_url = page.url
    if '/geo/journal/' not in made_url:
        pytest.skip('일지 생성이 상세 주소로 이동하지 않습니다 — '
                    '이 화면 흐름에서는 주소 재방문을 검사할 수 없습니다')

    page.goto(made_url, wait_until='domcontentloaded')
    try:
        _wait_for_the_document_to_be_built(page)
    except Exception:                        # noqa: BLE001
        body = page.inner_text('body')
        raise AssertionError(
            f'다시 연 일지에 대상이 없습니다 → {made_url} / 화면: {body[:200]!r}')
