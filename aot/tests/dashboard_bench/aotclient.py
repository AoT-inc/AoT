# coding=utf-8
"""AoT 서버에 로그인한 HTTP 세션 — 프로필 생성기와 측정 실행기가 함께 쓴다.

자격 증명은 인자 → 환경변수(`AOT_BENCH_USER`/`AOT_BENCH_PASSWORD`) → E2E 픽스처 순.
E2E 픽스처 계정은 E2E 스택(8085)에만 있다. 다른 서버에는 그 서버의 계정을 준다.
세션 쿠키는 디스크에 쓰지 않는다(필요하면 메모리에서 Playwright 로 넘긴다).
"""
import os
import re

DEFAULT_URL = 'http://127.0.0.1:8085'


def csrf_from_html(html):
    """폼의 csrf_token hidden 값. 없으면 None."""
    m = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
         or re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html))
    return m.group(1) if m else None


def default_credentials():
    user = os.environ.get('AOT_BENCH_USER')
    password = os.environ.get('AOT_BENCH_PASSWORD')
    if user and password:
        return user, password
    from aot.tests.e2e import fixtures as F
    return F.ADMIN_USER, F.ADMIN_PASS


class AotClient:
    """로그인한 `requests.Session` 의 얇은 껍데기."""

    def __init__(self, base_url, user=None, password=None, timeout=60):
        import requests
        self.base = base_url.rstrip('/')
        self.timeout = timeout
        self.s = requests.Session()
        if user is None or password is None:
            user, password = default_credentials()
        self.user = user
        self._login(user, password)

    def _login(self, user, password):
        page = self.s.get(f'{self.base}/login_password', timeout=self.timeout)
        token = csrf_from_html(page.text)
        if not token:
            raise RuntimeError('로그인 페이지에서 csrf_token 을 찾지 못했습니다')
        resp = self.s.post(
            f'{self.base}/login_password', timeout=self.timeout,
            data={'csrf_token': token, 'aot_username': user,
                  'aot_password': password, 'form_login': 'Login'})
        if '/login' in resp.url:
            raise RuntimeError(f'로그인 실패: {self.base} 사용자 {user}')

    def get(self, path, **kw):
        kw.setdefault('timeout', self.timeout)
        return self.s.get(self.base + path, **kw)

    def post(self, path, **kw):
        kw.setdefault('timeout', self.timeout)
        return self.s.post(self.base + path, **kw)

    def csrf_token(self):
        return self.get('/csrf-token').json()['csrf_token']

    def json_post(self, path, payload, method='POST'):
        """CSRF 머리글을 붙인 JSON 요청."""
        return self.s.request(
            method, self.base + path, json=payload, timeout=self.timeout,
            headers={'X-CSRFToken': self.csrf_token()})

    def cookies(self):
        """Playwright `context.add_cookies` 에 넘길 쿠키 목록(메모리 안에서만 쓴다)."""
        return [{'name': c.name, 'value': c.value, 'url': self.base} for c in self.s.cookies]
