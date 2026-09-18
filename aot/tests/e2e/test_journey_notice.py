# coding=utf-8
"""L2 · J15 — 공지를 쓰면 대시보드 위젯까지 가는가.

공지는 **읽히라고 쓰는 글**이다. 목록에는 있는데 대시보드 위젯에 안 뜨면,
쓴 사람은 알렸다고 믿고 읽을 사람은 보지 못한다. 그 어긋남은 화면 한쪽만
봐서는 드러나지 않는다.

그래서 쓰는 화면(`/notice`)과 읽는 자리(대시보드의 공지 위젯) **양쪽**을 본다.
시드가 대시보드에 공지 위젯을 놓아 두는 이유가 이것이다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e


def _open_notice_page(page, base_url):
    page.goto(f'{base_url}/notice', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)


def _post_notice(page, base_url, title, body):
    _open_notice_page(page, base_url)
    page.get_by_role('button', name='새 글쓰기').first.click()
    page.wait_for_selector('.modal.show input[name="title"]', timeout=15000)
    page.wait_for_timeout(400)

    page.fill('.modal.show input[name="title"]', title)
    page.fill('.modal.show textarea[name="body"]', body)

    with page.expect_response(
            lambda r: r.request.method == 'POST' and '/notice' in r.url,
            timeout=30000) as posted:
        page.locator('.modal.show [name="notice_add"]').first.click()
    assert posted.value.status in (200, 302), (
        f'공지 게시가 HTTP {posted.value.status} 로 끝났습니다')
    page.wait_for_timeout(2000)


def _delete_notice_if_present(page, base_url, title):
    """뒷정리 — 이 검사가 쓴 글은 이 검사가 치운다."""
    try:
        _open_notice_page(page, base_url)
        row = page.locator('tr, .aot-settings-row, li', has_text=title).first
        if not row.count():
            return
        button = row.locator('button, a').filter(
            has_text=__import__('re').compile('삭제|Delete')).first
        if button.count():
            page.once('dialog', lambda d: d.accept())
            button.click()
            page.wait_for_timeout(1500)
    except Exception:                        # noqa: BLE001 — 정리 실패가 판정을 덮지 않게
        pass


def test_a_posted_notice_shows_up_on_the_dashboard_widget(page, base_url):
    """쓴 공지가 목록에도, 대시보드 위젯에도 보이는가."""
    try:
        _post_notice(page, base_url, F.NOTICE_TITLE, F.NOTICE_BODY)

        # 1) 쓰는 화면의 목록에 있다.
        _open_notice_page(page, base_url)
        assert F.NOTICE_TITLE in page.inner_text('body'), (
            f'게시했는데 공지 목록에 없습니다: {F.NOTICE_TITLE!r}')

        # 2) 읽는 자리(대시보드 위젯)에도 있다. 여기까지 와야 "알렸다" 이다.
        open_dashboard(page, base_url, F.DASHBOARD)
        page.wait_for_timeout(2500)
        assert F.NOTICE_TITLE in page.inner_text('body'), (
            f'공지가 대시보드 위젯에 뜨지 않습니다 — 목록에는 있는데 읽는 '
            f'자리에는 없습니다({F.NOTICE_TITLE!r})')
    finally:
        _delete_notice_if_present(page, base_url, F.NOTICE_TITLE)
