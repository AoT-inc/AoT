# coding=utf-8
"""L2 · J17 — 구획 목록이 실제 구획을 보여 주는가.

구획은 "무엇을 어디서 언제부터 키우는가" 를 담는 단위다. 목록이 비거나 엉뚱한
값을 보이면 그 위에 얹힌 것(일지·목표·자원 계산)이 전부 어긋난다.

⚠ 이 화면은 **늦게 그려진다.** 처음 탐침했을 때 3.5초 뒤에는 본문이 72자였고
비어 보였지만, 6초 뒤에는 구획이 멀쩡히 있었다. 그 사이를 "구획이 없다" 로
판정했다면 있지도 않은 사고를 쫓았을 것이다 — 그래서 **요소가 나타날 때까지
기다린 뒤에** 본다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e


def _open_plots(page, base_url):
    page.goto(f'{base_url}/plots', wait_until='domcontentloaded')
    # 고정 대기가 아니라 **내용이 나타날 때까지** 기다린다.
    page.wait_for_function(
        "(subject) => (document.body.innerText || '').includes(subject)",
        arg=F.GEO_PLOT_SUBJECT, timeout=40000)
    page.wait_for_timeout(800)


def test_the_seeded_plot_is_listed_with_its_facts(page, base_url):
    """시드 구획이 목록에 있고, 딸린 사실도 함께 보이는가."""
    _open_plots(page, base_url)
    body = page.inner_text('body')

    assert F.GEO_PLOT_SUBJECT in body, (
        f'구획 목록에 {F.GEO_PLOT_SUBJECT!r} 가 없습니다')

    # 시드는 30일 전에 시작한 구획을 놓는다. 화면은 경과 일수를 말해야 한다 —
    # 목록에 이름만 있고 사실이 비면 "있긴 한데 아무것도 모르는" 상태다.
    assert '일차' in body or 'day' in body.lower(), (
        f'구획의 경과 일수가 보이지 않습니다(본문: {body[:200]!r})')
    assert 'm²' in body, '구획 면적이 보이지 않습니다'


def test_opening_the_plot_shows_that_plot(page, base_url):
    """목록에서 구획을 열면 **그 구획**이 나오는가.

    목록과 상세가 다른 것을 가리키는 어긋남은, 구획이 하나뿐일 때는 눈에 띄지
    않다가 여러 개가 되면 조용히 틀린 값을 보여 준다.
    """
    _open_plots(page, base_url)

    edit = page.get_by_role('button', name='편집').first
    if not edit.count():
        edit = page.get_by_text('편집', exact=True).first
    assert edit.count(), '구획을 여는 단추를 찾지 못했습니다'
    edit.click()
    page.wait_for_timeout(3000)

    body = page.inner_text('body')
    assert F.GEO_PLOT_SUBJECT in body, (
        f'구획을 열었는데 그 구획({F.GEO_PLOT_SUBJECT!r})이 보이지 않습니다')
