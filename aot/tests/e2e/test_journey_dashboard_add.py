# coding=utf-8
"""L2 — 대시보드 추가는 눌렀을 때만, 눌러서 한 번만 일어난다.

`/dashboard-add` 는 예전에 GET 만으로 빈 대시보드를 만들었다. 인자 없는 GET 을
전부 여는 L0·L1 이 실행마다 둘씩 쌓았고(25개까지), 사람의 새로고침·링크
미리읽기도 같았다. 지금은 POST 전용이라 화면의 두 진입점(탭 줄의 "+" 와
내비게이션의 "대시보드 추가")이 CSRF 토큰이 붙은 폼 버튼이다.

여기서는 그 두 버튼이 **실제 브라우저에서** 하나씩 만들어 그 화면으로 보내는지,
그리고 GET 은 아무것도 만들지 않는지를 본다. 만든 것은 검사가 끝나면 지운다.

**개수는 DB 에서 센다.** 탭 줄(`inject_variables` 의 대시보드 목록)은 로컬 TTL
10초 캐시이고 추가·삭제가 그것을 비우지 않는다 — 방금 만든 대시보드가 최대 10초간
탭 줄에 없다(옛 GET 경로에서도 같았다). 화면으로 세면 그 낡은 목록에 판정이 달린다.
"""
import json
import os
import re
import subprocess

import pytest

from aot.tests.e2e.conftest import form_csrf

pytestmark = pytest.mark.e2e

COMPOSE_FILE = os.environ.get(
    'AOT_E2E_COMPOSE', 'docker/docker-compose.e2e.yml')

_READ_IDS = (
    "import json, sqlite3;"
    "from aot.config import AOT_DB_PATH;"
    "c = sqlite3.connect(AOT_DB_PATH.replace('sqlite:///', ''));"
    "print(json.dumps([r[0] for r in "
    "c.execute('select unique_id from dashboard order by id')]))")


def _dashboard_ids():
    """지금 DB 에 있는 대시보드들의 unique_id (캐시를 거치지 않는다)."""
    try:
        out = subprocess.run(
            ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'aot-app',
             'python', '-c', _READ_IDS],
            check=True, capture_output=True, text=True, timeout=60)
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired) as err:
        pytest.skip(f'E2E 컨테이너에서 대시보드 목록을 얻지 못했습니다: {err}')
    # 부팅 로그가 섞일 수 있어 마지막 줄만 본다.
    return json.loads(out.stdout.strip().splitlines()[-1])


def _delete_dashboard(http, base_url, dashboard_id):
    """검사가 만든 대시보드를 화면과 같은 폼 POST 로 지운다."""
    page = http.get(f'{base_url}/dashboard/{dashboard_id}', timeout=30)
    http.post(f'{base_url}/dashboard/{dashboard_id}', timeout=30, data={
        'csrf_token': form_csrf(page.text),
        'dashboard_id': dashboard_id,
        'dash_delete': 'Delete',
    })


def _assert_added_exactly_one(page, admin_http, base_url, before, click):
    """`click()` 이 눌러서 이동한 곳이 **새로 생긴 단 하나의 대시보드**인지 본다."""
    created = []
    try:
        with page.expect_navigation(url=re.compile(r'/dashboard/[0-9a-f-]{36}$'),
                                    wait_until='domcontentloaded'):
            click()
        landed_on = page.url.rsplit('/', 1)[-1]

        after = _dashboard_ids()
        created = [i for i in after if i not in before]
        assert len(created) == 1, (
            f'한 번 눌렀는데 새 대시보드가 {len(created)}개 생겼습니다: {created}')
        assert landed_on == created[0], (
            '눌렀을 때 새로 만든 대시보드가 아닌 곳으로 이동했습니다')
        # 화면이 실제로 그 대시보드를 그리는지 — 없는 것을 열면 되돌려진다.
        opened = admin_http.get(f'{base_url}/dashboard/{landed_on}', timeout=30,
                                allow_redirects=False)
        assert opened.status_code == 200, (
            f'새 대시보드가 열리지 않습니다 (HTTP {opened.status_code})')
    finally:
        for dashboard_id in created:
            _delete_dashboard(admin_http, base_url, dashboard_id)

    assert _dashboard_ids() == before, '검사가 만든 대시보드를 지우지 못했습니다'


def test_get_never_creates_a_dashboard(admin_http, base_url):
    """열기만 해서는 생기지 않는다 — 405 이고 개수가 그대로다."""
    before = _dashboard_ids()
    assert before, '대시보드가 하나도 없습니다 — 시드를 먼저 돌렸는지 확인하세요'

    for _ in range(3):
        resp = admin_http.get(f'{base_url}/dashboard-add', timeout=30,
                              allow_redirects=False)
        assert resp.status_code == 405, (
            f'GET /dashboard-add 가 HTTP {resp.status_code} 를 줬습니다 (405 여야 합니다)')

    assert _dashboard_ids() == before, 'GET 만으로 대시보드가 생겼습니다'


def test_the_tab_row_plus_button_adds_exactly_one(page, admin_http, base_url):
    """탭 줄의 "+" — 눌러서 하나 만들고 그 대시보드로 이동한다."""
    before = _dashboard_ids()
    page.goto(f'{base_url}/dashboard', wait_until='domcontentloaded')
    page.wait_for_selector('button[form="dash-add-form"]', timeout=20000)
    _assert_added_exactly_one(
        page, admin_http, base_url, before,
        lambda: page.click('button[form="dash-add-form"]'))


def test_the_navbar_menu_item_adds_exactly_one(page, admin_http, base_url):
    """내비게이션 > 대시보드 > "대시보드 추가" — 같은 동작."""
    before = _dashboard_ids()
    page.goto(f'{base_url}/dashboard', wait_until='domcontentloaded')
    # 데스크톱에서는 메뉴가 항목(li)에 올리면 열린다(CSS :hover).
    page.locator('li.nav-item.dropdown:has(#dropdownDashboard)').hover()
    item = page.locator('form[action="/dashboard-add"] button.dropdown-item')
    item.wait_for(state='visible', timeout=10000)
    _assert_added_exactly_one(page, admin_http, base_url, before, item.click)
