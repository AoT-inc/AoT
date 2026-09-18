# coding=utf-8
"""L0 — 라우트 스모크.

앱이 등록한 GET 라우트를 **전부** 한 번씩 열어 본다. 한 페이지도 빠뜨리지
않는 것이 요점이다. 새 페이지를 추가하면 다음 실행부터 자동으로 대상이 되고,
아무도 테스트를 쓰지 않아도 "렌더가 터지는 화면"은 여기서 걸린다.

두 가지를 본다.
  1. 관리자로 열었을 때 5xx 가 나지 않고 템플릿이 끝까지 렌더된다.
  2. 로그인하지 않고 열면 전부 로그인으로 튕긴다(공개 허용 목록 제외).
     `check_route_auth.py` 가 데코레이터를 정적으로 보는 것과 달리, 이쪽은
     **실제 응답**을 본다 — 데코레이터가 붙어 있어도 그 안에서 새는 경우가
     있기 때문이다.
"""
import json
import os
import re
import subprocess

import pytest

pytestmark = pytest.mark.e2e

COMPOSE_FILE = os.environ.get(
    'AOT_E2E_COMPOSE', 'docker/docker-compose.e2e.yml')

# ---------------------------------------------------------------------------
# 호출하지 않는 GET 라우트 — 사유를 반드시 적는다.
#
# "느려서" 는 사유가 아니다. 부작용이 있거나(세션을 죽인다, 외부로 나간다),
# 이 층에서 판정할 수 없는 것만 뺀다.
# ---------------------------------------------------------------------------
SKIP_GET = {
    '/logout': '세션을 파기한다 — 뒤따르는 모든 검사가 무너진다',
    '/login/google/start': '외부 OAuth 로 나간다',
    '/oauth/google/start': '외부 OAuth 로 나간다',
    '/api/export_import/export_influxdb': '측정 DB 전체를 내려받는다',
    '/api/export_import/export_settings': '설정 DB 를 통째로 내려받는다',
    '/audit_log/export': '감사 로그 전체를 내려받는다',
    '/logview/download': '로그 파일 전체를 내려받는다',
    '/admin/backup': '백업 생성을 트리거할 수 있다',
    '/api/geo/proxy/rainviewer/timestamps': '외부 서비스로 나간다 — 판정이 '
                                            '인터넷 상태에 달린다',
}

# 로그인한 사용자가 열면 **되돌려지는 것이 정상**인 페이지. 관리자 검사에서만
# 빼고, 익명 검사에서는 공개로 열려야 하므로 그대로 둔다.
REDIRECTS_WHEN_LOGGED_IN = (
    '/login', '/login_password', '/login_totp', '/login_keypad',
    '/login_keypad_code/', '/create_admin', '/forgot_password',
    '/reset_password',
)

# 로그인 없이 열려도 되는 경로 — 여기 없는 것이 익명에게 200 을 주면 실패한다.
PUBLIC_PREFIXES = (
    '/login', '/create_admin', '/forgot_password', '/reset_password',
    '/static/', '/robots.txt', '/favicon.ico', '/favicon.png',
    '/terms_of_service', '/privacy_policy', '/legal',
    '/terms-of-service', '/privacy-policy',
    '/auth/', '/newremote/', '/remote_login', '/oauth/', '/health',
    # 로그인 화면 자체가 쓰는 것들 — 로그인 전에 받아야 한다.
    '/custom.css', '/csrf-token', '/api/v1/locale',
    # 비로그인 방문자에게 보여 주는 소개 화면(routes_general.home 이
    # 인증 여부로 갈라 landing.html 을 그린다).
    '/',
    # flask-restx 가 자동으로 붙이는 문서 표면. 스키마가 드러나는 것이
    # 의도인지는 별도 판단이 필요하다 — 지금 상태를 사실대로 적어 둔다.
    '/api/swagger.json',
)


def _dump_routes_from_container():
    """돌고 있는 앱에서 라우트 목록을 받아온다."""
    target = '/app/aot_local/e2e_routes.json'
    subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'aot-app',
         'python', '-m', 'aot.tests.e2e.dump_routes', target],
        check=True, capture_output=True, timeout=300)
    out = subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T', 'aot-app',
         'cat', target],
        check=True, capture_output=True, timeout=60)
    return json.loads(out.stdout)


@pytest.fixture(scope='session')
def routes():
    try:
        return _dump_routes_from_container()
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired) as err:
        pytest.skip(f'E2E 컨테이너에서 라우트 목록을 얻지 못했습니다: {err}')


@pytest.fixture(scope='session')
def get_routes(routes):
    """인자가 없는 GET 라우트만. 인자가 있는 것은 L2 시나리오가 다룬다."""
    return [r for r in routes
            if 'GET' in r['methods']
            and not r['has_args']
            and r['rule'] not in SKIP_GET
            and not r['rule'].startswith('/static/')]


def _is_public(rule):
    return any(rule.startswith(p) for p in PUBLIC_PREFIXES)


def test_every_get_route_renders_for_an_admin(admin_http, base_url, get_routes):
    """관리자로 열었을 때 5xx·렌더 실패가 없어야 한다."""
    assert len(get_routes) > 100, (
        f'라우트가 {len(get_routes)}개뿐입니다 — 덤프가 잘못됐을 가능성이 큽니다')

    failures = []
    for route in get_routes:
        rule = route['rule']
        url = base_url + rule
        # flask-restx 는 Accept 를 보고 406 을 내므로 API 에는 JSON 을 요구한다.
        headers = ({'Accept': 'application/json'}
                   if rule.startswith('/api/') else None)
        try:
            resp = admin_http.get(url, timeout=30, allow_redirects=False,
                                  headers=headers)
        except Exception as err:            # noqa: BLE001 — 무엇이든 실패로 센다
            failures.append((rule, f'요청 실패: {err!r}'))
            continue

        if resp.status_code >= 500:
            failures.append((rule, f'HTTP {resp.status_code}'))
            continue

        # 로그인으로 튕기면 관리자 세션이 끊긴 것이다 — 그대로 두면 이후 전부
        # 통과처럼 보인다(조용한 실패).
        if (resp.is_redirect
                and '/login' in resp.headers.get('Location', '')
                and route['rule'] not in REDIRECTS_WHEN_LOGGED_IN):
            failures.append((rule, '관리자인데 로그인으로 튕겼습니다'))
            continue

        body = resp.text if 'text/html' in resp.headers.get(
            'Content-Type', '') else ''
        if body:
            # 템플릿이 중간에 끊기면 Jinja 구문이 그대로 남는다.
            leftover = re.search(r'\{\{\s*\w+|\{%\s*(if|for|block)\b', body)
            if leftover:
                failures.append(
                    (rule, f'렌더되지 않은 템플릿 구문: {leftover.group(0)!r}'))

    assert not failures, '\n'.join(
        f'  {rule} — {why}' for rule, why in failures)


def test_every_private_get_route_rejects_anonymous(anon_http, base_url,
                                                   get_routes):
    """로그인하지 않으면 비공개 경로는 전부 막혀야 한다.

    정적 검사(`check_route_auth.py`)가 보는 것은 데코레이터이고, 이 검사가
    보는 것은 실제 응답이다. 둘 다 필요하다 — 데코레이터가 붙어 있는데도
    응답이 새는 경우가 실제로 있었다(위젯 미인증 경로).
    """
    leaks = []
    for route in get_routes:
        rule = route['rule']
        if _is_public(rule):
            continue
        headers = ({'Accept': 'application/json'}
                   if rule.startswith('/api/') else None)
        try:
            resp = anon_http.get(base_url + rule, timeout=30,
                                 allow_redirects=False, headers=headers)
        except Exception as err:            # noqa: BLE001
            leaks.append((rule, f'요청 실패: {err!r}'))
            continue

        blocked = (
            resp.status_code in (301, 302, 303, 307, 308)
            and '/login' in resp.headers.get('Location', '')
        ) or resp.status_code in (401, 403)

        if not blocked:
            leaks.append((rule, f'익명에게 HTTP {resp.status_code} 를 줬습니다'))

    assert not leaks, (
        '로그인 없이 접근됐습니다. 의도한 공개라면 PUBLIC_PREFIXES 에 '
        '사유와 함께 등록하세요:\n' + '\n'.join(
            f'  {rule} — {why}' for rule, why in leaks))


# ---------------------------------------------------------------------------
# 코드가 가리키는 엔드포인트가 실제로 있는가
# ---------------------------------------------------------------------------
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
_URL_FOR = re.compile(r"url_for\(\s*['\"]([A-Za-z_]\w*\.[A-Za-z_]\w*)['\"]")


def _url_for_targets():
    """파이썬·템플릿에 **글자 그대로** 적힌 `url_for('블루프린트.함수')` 대상."""
    found = {}
    roots = [os.path.join(_REPO, 'aot', 'aot_flask'),
             os.path.join(_REPO, 'aot', 'widgets')]
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(('.py', '.html')):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                for match in _URL_FOR.finditer(text):
                    line = text.count('\n', 0, match.start()) + 1
                    found.setdefault(match.group(1), []).append(
                        f'{os.path.relpath(path, _REPO)}:{line}')
    return found


def test_every_url_for_points_at_a_real_endpoint(routes):
    """`url_for` 가 없는 엔드포인트를 가리키면 그 줄이 실행되는 순간 500 이다.

    평소 흐름에서는 안 지나가는 가지(권한 거절·오류 처리)에 숨어 있다가
    드물게 터진다. 2026-09-18: 전류 에너지 화면이 권한 없는 POST 를
    `routes_page.page_usage`(없는 엔드포인트)로 돌려보내 거절 대신 500 이
    났다. 정적 스캔만으로는 블루프린트를 여러 파일이 나눠 쓰는 경우를 오판하므로
    **실제 앱의 URL 맵**과 대조한다.
    """
    endpoints = {r['endpoint'] for r in routes}
    missing = {name: where for name, where in _url_for_targets().items()
               if not name.startswith('static') and not name.endswith('.static')
               and name not in endpoints}
    assert not missing, (
        '없는 엔드포인트를 가리키는 url_for 가 있습니다 — 그 줄이 실행되면 500 '
        '입니다:\n' + '\n'.join(f'  {n}  ← {", ".join(w[:3])}'
                                for n, w in sorted(missing.items())))
