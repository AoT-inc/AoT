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
    if E2E_BASE_URL:
        _assert_stack_serves_this_worktree()


# ---------------------------------------------------------------------------
# 스택이 **이 워크트리**를 보고 있는가
# ---------------------------------------------------------------------------
#: 컨테이너가 `/app` 에 통째로 마운트하는 것은 워크트리 하나뿐이고, 스택은
#: 8085 에 하나뿐이다. 다른 워크트리에서 `docker compose ... up` 을 부르면
#: 그쪽으로 다시 묶이므로, 여기서 pytest 를 돌려도 검사하는 코드는 남의
#: 워크트리가 된다 — 방금 고친 것이 아닌 것을 보고 "통과" 라고 말하게 된다
#: (2026-09-20 실제로 그랬다). 그래서 시작할 때 한 번 확인하고 멈춘다.
E2E_APP_CONTAINER = os.environ.get('AOT_E2E_APP_CONTAINER', 'aot-e2e-aot-app-1')


def _repo_root():
    import subprocess
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                         cwd=os.path.dirname(os.path.abspath(__file__)),
                         capture_output=True, text=True, timeout=30)
    return os.path.realpath(out.stdout.strip()) if out.returncode == 0 else None


def _mounted_source():
    """컨테이너가 `/app` 으로 마운트한 호스트 경로. 볼 수 없으면 None."""
    import subprocess
    fmt = ('{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}'
           '{{end}}{{end}}')
    try:
        out = subprocess.run(
            ['docker', 'inspect', E2E_APP_CONTAINER, '--format', fmt],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _assert_stack_serves_this_worktree():
    # 원격 스택·CI 처럼 호스트에서 컨테이너를 못 보는 경우가 있다. 그때는
    # 확인할 방법이 없으므로 조용히 넘어간다(끄는 스위치도 둔다).
    if os.environ.get('AOT_E2E_SKIP_MOUNT_CHECK'):
        return
    mounted, here = _mounted_source(), _repo_root()
    if not mounted or not here or os.path.realpath(mounted) == here:
        return
    raise pytest.UsageError(
        f'E2E 스택이 다른 워크트리를 보고 있습니다 — 검사해도 지금 고친 코드가 '
        f'아닙니다.\n  컨테이너: {mounted}\n  여기: {here}\n'
        f'  다시 묶으려면: docker compose -f docker/docker-compose.e2e.yml '
        f'--profile control up -d\n'
        f'  (그 뒤 시드: ... exec -T -e AOT_E2E=1 aot-app '
        f'python -m aot.tests.e2e.seed)')


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


#: 검사가 만든 HTTP 세션들 — 웹 앱을 재시작한 뒤 연결 풀을 비우는 데 쓴다.
_SESSIONS = []


def _tracked(session):
    """검사용 세션 — 읽기 요청(GET)은 끊긴 연결에서 두 번까지 다시 보낸다.

    gunicorn 은 유휴 keep-alive 연결을 곧 닫는다. 검사가 그 무렵에 같은 연결을
    다시 쓰면 "Remote end closed connection without response" 로 실패한다 — 앱의
    잘못이 아니라 연결 재사용의 경합이다(2026-09-19, 2초 간격 폴링에서 반복).
    쓰기(POST 등)는 다시 보내지 않는다 — 두 번 실행될 수 있다.
    """
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(total=2, connect=2, read=2, status=0, backoff_factor=0.2,
                  allowed_methods=frozenset({'GET', 'HEAD'}), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    _SESSIONS.append(session)
    return session


def reset_http_sessions():
    """웹 앱을 재시작한 뒤 부른다 — 세션들의 연결 풀을 비운다.

    requests 세션은 연결을 다시 쓴다. 앱이 재시작되면 풀에 남은 연결은 죽어 있어,
    나중에 그것을 집은 요청이 "Remote end closed connection without response" 로
    실패한다 — 재시작 뒤 **아무 검사에서나** 우연히 터진다(2026-09-19 L3 C4).
    로그인 쿠키는 세션에 그대로 있으므로 로그인은 유지된다.
    """
    for session in _SESSIONS:
        session.close()


@pytest.fixture(scope='session')
def admin_http(base_url):
    """관리자로 로그인한 `requests.Session`."""
    import requests
    from aot.tests.e2e import fixtures as F

    session = _tracked(requests.Session())
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

    session = _tracked(requests.Session())
    _login(session, base_url, F.GUEST_USER, F.GUEST_PASS)
    return session


@pytest.fixture(scope='session')
def monitor_http(base_url):
    """보기 권한만 있는 사용자(Monitor) — 화면은 열리고 쓰기만 막혀야 한다."""
    import requests
    from aot.tests.e2e import fixtures as F

    session = _tracked(requests.Session())
    _login(session, base_url, F.MONITOR_USER, F.MONITOR_PASS)
    return session


@pytest.fixture(scope='session')
def editor_http(base_url):
    """편집자(Editor) — 설정·제어는 되지만 관리자 전용은 막혀야 한다."""
    import requests
    from aot.tests.e2e import fixtures as F

    session = _tracked(requests.Session())
    _login(session, base_url, F.EDITOR_USER, F.EDITOR_PASS)
    return session


def csrf_headers(session, base_url):
    """세션의 CSRF 토큰을 머리글로 — JSON API 를 화면처럼 부를 때."""
    token = session.get(f'{base_url}/csrf-token', timeout=30).json()['csrf_token']
    return {'X-CSRFToken': token}


def form_csrf(html):
    """화면 폼의 csrf_token 값."""
    return _csrf_token(html)


@pytest.fixture(scope='session')
def anon_http():
    """로그인하지 않은 세션 — 인증 게이트 검사용."""
    import requests
    return _tracked(requests.Session())


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
def daemon(admin_http, base_url):
    """데몬이 떠 있고 **실제로 응답할 때** 도는 검사용.

    데몬은 `--profile control` 로만 뜬다. 띄우지 않았으면 **건너뛴다** —
    "데몬이 없어서 통과" 가 아니라 "돌지 않았음" 으로 보이게 하는 것이 맞다.

    띄워져 있으면 **말이 될 때까지 기다린다.** 컨테이너가 running 인 것과
    앱이 데몬과 말이 되는 것은 다른 사건이고, 그 사이는 CI 처럼 스택을 방금
    올린 곳에서 특히 길다 — 로컬에서는 데몬이 이미 오래 떠 있어 이 대기가
    없어도 통과하다가, CI 에서만 "시작 상태를 만들지 못했습니다" 로 깨졌다
    (2026-09-18 실측).
    """
    from aot.tests.e2e import daemon as daemon_ctl

    if not daemon_ctl.is_running():
        pytest.skip(
            '데몬이 떠 있지 않습니다. 제어 폐루프 검사는 데몬이 필요합니다:\n'
            '  docker compose -f docker/docker-compose.e2e.yml '
            '--profile control up -d aot_daemon')

    def _answers():
        resp = admin_http.get(f'{base_url}/outputstate', timeout=20,
                              headers={'Accept': 'application/json'})
        return resp.status_code == 200 and bool(resp.json())

    if not daemon_ctl.wait_until_ready(_answers, wait_s=180):
        pytest.skip('데몬이 떠 있지만 3분 안에 응답하지 않았습니다')
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
