# coding=utf-8
"""E2E 공통 픽스처.

**수집 게이트**: `AOT_E2E_BASE_URL` 이 없으면 이 디렉터리의 테스트를 아예
수집하지 않는다(아래 `collect_ignore_glob`). 그래서 `pytest aot/tests` 는
지금까지와 똑같이 동작하고, 브라우저도 서버도 필요 없다. E2E 를 돌리려면
환경변수를 주는 것이 곧 의사 표시가 된다.
"""
import os

import pytest

E2E_BASE_URL = os.environ.get('AOT_E2E_BASE_URL', '').rstrip('/')

# 상위 conftest 가 만든 임시 DB 격리는 E2E 와 무관하다(E2E 는 HTTP 로만 앱을
# 만난다). 해롭지도 않으므로 그대로 둔다.
if not E2E_BASE_URL:
    collect_ignore_glob = ['test_*.py']


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'e2e: 실제 서버와 브라우저가 필요한 종단 테스트')


# ---------------------------------------------------------------------------
# HTTP 계층 (L0)
# ---------------------------------------------------------------------------
@pytest.fixture(scope='session')
def base_url():
    return E2E_BASE_URL


def _csrf_token(html):
    """폼의 csrf_token hidden 값을 뽑는다."""
    import re
    m = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(
        r'value="([^"]+)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else None


def _login(session, base, username, password):
    """비밀번호 로그인. 성공하면 세션에 쿠키가 남는다."""
    page = session.get(f'{base}/login_password', timeout=30)
    token = _csrf_token(page.text)
    assert token, '로그인 페이지에서 csrf_token 을 찾지 못했습니다'
    resp = session.post(
        f'{base}/login_password',
        data={'csrf_token': token,
              'aot_username': username,
              'aot_password': password,
              'form_login': 'Login'},
        allow_redirects=True, timeout=30)
    return resp


@pytest.fixture(scope='session')
def admin_http(base_url):
    """관리자로 로그인한 `requests.Session`."""
    import requests
    from aot.tests.e2e import fixtures as F

    session = requests.Session()
    resp = _login(session, base_url, F.ADMIN_USER, F.ADMIN_PASS)
    assert resp.status_code == 200, f'관리자 로그인 실패: {resp.status_code}'
    assert '/login' not in resp.url, (
        f'관리자 로그인이 되돌려졌습니다 → {resp.url}. 시드를 먼저 실행했는지 '
        f'확인하세요: docker compose -f docker/docker-compose.e2e.yml '
        f'exec -T aot-app python -m aot.tests.e2e.seed')
    return session


@pytest.fixture(scope='session')
def guest_http(base_url):
    """게스트(권한 낮음)로 로그인한 세션 — 권한 경계 검사용."""
    import requests
    from aot.tests.e2e import fixtures as F

    session = requests.Session()
    _login(session, base_url, F.GUEST_USER, F.GUEST_PASS)
    return session


@pytest.fixture(scope='session')
def anon_http():
    """로그인하지 않은 세션 — 인증 게이트 검사용."""
    import requests
    return requests.Session()


# ---------------------------------------------------------------------------
# 브라우저 계층 (L1·L2)
#
# pytest-playwright 플러그인을 쓰지 않고 직접 픽스처를 만든다. 플러그인은
# 편하지만 CLI 옵션·마커·픽스처 이름을 통째로 끌고 들어와 기존 5천여 개
# 스위트와 섞인다. 필요한 것은 브라우저 하나와 로그인된 컨텍스트뿐이다.
# ---------------------------------------------------------------------------
@pytest.fixture(scope='session')
def playwright_instance():
    sync_playwright = pytest.importorskip(
        'playwright.sync_api',
        reason='playwright 가 설치되지 않았습니다: pip install playwright && '
               'playwright install chromium').sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope='session')
def browser(playwright_instance):
    browser = playwright_instance.chromium.launch(
        headless=os.environ.get('AOT_E2E_HEADED') != '1')
    yield browser
    browser.close()


@pytest.fixture(scope='session')
def storage_state(browser, base_url, tmp_path_factory):
    """관리자로 한 번만 로그인해 쿠키를 파일로 남긴다.

    테스트마다 로그인 폼을 거치면 54개 페이지 검사가 그만큼 느려지고,
    로그인 화면의 사소한 변경이 전 테스트를 무너뜨린다.
    """
    from aot.tests.e2e import fixtures as F

    path = tmp_path_factory.mktemp('e2e') / 'storage_state.json'
    context = browser.new_context()
    page = context.new_page()
    page.goto(f'{base_url}/login_password', wait_until='domcontentloaded')
    page.fill('input[name="aot_username"]', F.ADMIN_USER)
    page.fill('input[name="aot_password"]', F.ADMIN_PASS)
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state('domcontentloaded')
    assert '/login' not in page.url, (
        f'브라우저 로그인이 되돌려졌습니다 → {page.url}')
    context.storage_state(path=str(path))
    context.close()
    return str(path)


@pytest.fixture
def context(browser, storage_state):
    """로그인된 브라우저 컨텍스트 — 테스트마다 새로 만든다."""
    context = browser.new_context(
        storage_state=storage_state,
        viewport={'width': 1440, 'height': 900},
        locale='ko-KR')
    yield context
    context.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    yield page
    page.close()


# ---------------------------------------------------------------------------
# L3 — 제어 폐루프
# ---------------------------------------------------------------------------
@pytest.fixture(scope='session')
def daemon():
    """데몬이 떠 있어야 도는 검사용.

    데몬은 `--profile control` 로만 뜬다. 띄우지 않았으면 **건너뛴다** —
    "데몬이 없어서 통과" 가 아니라 "돌지 않았음" 으로 보이게 하는 것이 맞다.
    """
    from aot.tests.e2e import daemon as daemon_ctl

    if not daemon_ctl.is_running():
        pytest.skip(
            '데몬이 떠 있지 않습니다. 제어 폐루프 검사는 데몬이 필요합니다:\n'
            '  docker compose -f docker/docker-compose.e2e.yml '
            '--profile control up -d aot_daemon')
    return daemon_ctl


@pytest.fixture
def output_states(admin_http, base_url):
    """데몬이 아는 출력 상태를 그대로 읽어 온다 — `{출력id: {채널: 'on'|'off'}}`.

    화면 표시가 아니라 **데몬의 대답**이다. 둘이 갈리는 것이 곧 사고이므로
    폐루프 검사는 이쪽을 본다.
    """
    def _read():
        resp = admin_http.get(f'{base_url}/outputstate', timeout=30,
                              headers={'Accept': 'application/json'})
        assert resp.status_code == 200, (
            f'출력 상태 조회가 HTTP {resp.status_code} 를 냈습니다')
        return resp.json()
    return _read
