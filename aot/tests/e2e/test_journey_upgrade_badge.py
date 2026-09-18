# coding=utf-8
"""L2 · P2 — 업그레이드가 있으면 관리 메뉴의 "업그레이드" 가 **눈에 띄고 읽힌다**.

표시는 `Misc.aot_upgrade_available` 한 값으로 정해진다(업그레이드 화면이 저장소를
확인할 때 채운다). 검사는 그 값을 직접 켜고 끈다 — 업그레이드 화면을 열면 실제
저장소 상태로 덮어쓰므로 열지 않는다.

지켜 온 사고: 강조색이 호버·특정도 싸움에 져서 **배경과 글자가 같은 계열**이
되어 읽을 수 없던 것(2026-08-13), 클래스가 빠져 강조 자체가 사라지는 것.
"""
import subprocess
import time

import pytest

from aot.tests.e2e.daemon import COMPOSE_FILE

pytestmark = pytest.mark.e2e

UPGRADE_ITEM = '#dropdownManage + .dropdown-menu a.dropdown-item[href*="upgrade"]'
NEIGHBOR_ITEM = '#dropdownManage + .dropdown-menu a.dropdown-item[href*="backup"]'


def _set_upgrade_available(value):
    code = ("import sqlite3; from aot.config import SQL_DATABASE_AOT as p; "
            "c = sqlite3.connect(p); "
            f"c.execute('update misc set aot_upgrade_available = {1 if value else 0}'); "
            "c.commit()")
    subprocess.run(['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T',
                    'aot-app', 'python', '-c', code],
                   check=True, capture_output=True, timeout=60)


@pytest.fixture
def upgrade_flag():
    yield _set_upgrade_available
    _set_upgrade_available(False)


def _item_style(page, selector):
    return page.eval_on_selector(selector, """el => {
        const s = getComputedStyle(el);
        return {cls: el.className, bg: s.backgroundColor, fg: s.color};
    }""")


def _luminance(rgb):
    parts = [int(float(x)) for x in rgb[rgb.index('(') + 1:rgb.index(')')].split(',')[:3]]
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    a, b = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _open_manage_menu(page, base_url, highlighted):
    """관리 메뉴를 연다 — 표시가 DB 값을 따라올 때까지 다시 연다.

    화면 변수의 Misc 는 워커마다 10 초 캐시된다(routes_static._cached_misc).
    DB 를 바꾼 직후에는 옛 값이 보이는 것이 정상이라, 캐시 수명을 넘겨 기다린다.
    """
    deadline = time.time() + 25
    while True:
        page.goto(f'{base_url}/output', wait_until='domcontentloaded')
        # 메뉴 링크의 중심을 부모 <li> 가 덮는다 — 부모를 누른다.
        page.locator('#dropdownManage').locator('xpath=..').click()
        page.wait_for_selector(UPGRADE_ITEM, state='visible', timeout=10000)
        has = 'aot-nav-upgrade' in _item_style(page, UPGRADE_ITEM)['cls']
        if has == highlighted or time.time() > deadline:
            return
        page.wait_for_timeout(2000)


def test_an_available_upgrade_is_highlighted_and_readable(page, base_url,
                                                          upgrade_flag):
    upgrade_flag(True)
    _open_manage_menu(page, base_url, highlighted=True)
    item = _item_style(page, UPGRADE_ITEM)
    plain = _item_style(page, NEIGHBOR_ITEM)
    assert 'aot-nav-upgrade' in item['cls'], '업그레이드가 있는데 강조 클래스가 없습니다'
    assert item['bg'] != plain['bg'], (
        f"업그레이드 항목이 옆 항목과 같은 배경입니다({item['bg']}) — 눈에 띄지 않습니다")
    ratio = _contrast(item['fg'], item['bg'])
    assert ratio >= 3, (
        f"업그레이드 항목의 글자가 배경 위에서 읽히지 않습니다 — 명암비 {ratio:.2f} "
        f"(글자 {item['fg']}, 배경 {item['bg']})")

    # 마우스를 올려도 읽혀야 한다(호버 규칙이 덮어쓰던 사고)
    page.hover(UPGRADE_ITEM)
    page.wait_for_timeout(300)
    hovered = _item_style(page, UPGRADE_ITEM)
    ratio = _contrast(hovered['fg'], hovered['bg'])
    assert ratio >= 3, (
        f"마우스를 올리면 업그레이드 글자가 읽히지 않습니다 — 명암비 {ratio:.2f}")


def test_no_upgrade_means_no_highlight(page, base_url, upgrade_flag):
    upgrade_flag(False)
    _open_manage_menu(page, base_url, highlighted=False)
    item = _item_style(page, UPGRADE_ITEM)
    plain = _item_style(page, NEIGHBOR_ITEM)
    assert 'aot-nav-upgrade' not in item['cls'], '업그레이드가 없는데 강조돼 있습니다'
    assert item['bg'] == plain['bg'], '업그레이드가 없는데 배경이 옆 항목과 다릅니다'
