# coding=utf-8
"""L2 · P2 — 로그뷰와 감사 로그가 **일어난 일을 보여 주는가**.

로그뷰는 줄을 읽어 오고, 수준·검색 거르기가 실제로 거르고, 내려받기는 화면이
보여 주는 것과 같은 줄이어야 한다. 감사 로그는 사건이 남는지를 본다 — 확실히
남는 사건으로 **로그인 실패**를 일으켜 목록·거르기·CSV 내보내기에서 찾는다.

2026-09-18 처음 돌렸을 때 감사 로그의 주소가 전부 'unknown address' 였다.
주소 함수가 프록시 머리글만 봤고, 운영 구성은 gunicorn 이 직접 받아 그 머리글이
없다 — 감사 기록에 주소가 없고, 요청 제한은 익명 접속자 전체가 한 바구니를
나눠 썼다.
"""
import csv
import io
import time

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import _login

pytestmark = pytest.mark.e2e

LEVEL_RANK = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}


def _log(admin_http, base_url, **params):
    resp = admin_http.get(f'{base_url}/logview/data', params=params, timeout=30)
    assert resp.status_code == 200, f'로그 조회가 HTTP {resp.status_code}'
    return resp.json()


# --------------------------------------------------------------------------
# 로그뷰
# --------------------------------------------------------------------------
def test_the_log_viewer_draws_the_lines_it_reads(page, admin_http, base_url):
    data = _log(admin_http, base_url, lines=50)
    assert data['entries'], f"기본 로그({data.get('source')})가 비어 있습니다"

    page.goto(f'{base_url}/logview', wait_until='domcontentloaded')
    page.wait_for_function(
        "() => (document.getElementById('logview-pane') || {}).innerText"
        " && document.getElementById('logview-pane').innerText.trim().length > 0",
        timeout=20000)
    shown = page.inner_text('#logview-pane')
    newest = data['entries'][-1]['message'][:40]
    assert newest and newest in shown, (
        '로그 화면이 서버가 돌려준 가장 최근 줄을 보여 주지 않습니다')


def test_level_and_search_filters_really_filter(admin_http, base_url):
    everything = _log(admin_http, base_url, lines=500)['entries']
    assert everything, '거를 줄이 없습니다'

    warnings = _log(admin_http, base_url, lines=500, level='WARNING')['entries']
    below = [e for e in warnings
             if LEVEL_RANK.get(e.get('level') or '', 99) < LEVEL_RANK['WARNING']]
    assert not below, f'WARNING 거르기에 더 낮은 수준이 섞였습니다: {below[:2]}'

    # 실제로 있는 낱말로 찾는다 — 결과 전부가 그 낱말을 품어야 하고, 하나는 나와야 한다.
    word = everything[-1]['logger']
    found = _log(admin_http, base_url, lines=500, search=word)['entries']
    assert found, f"'{word}' 로 찾았는데 한 줄도 나오지 않았습니다"
    stray = [e['raw'] for e in found if word.lower() not in e['raw'].lower()]
    assert not stray, f"'{word}' 가 없는 줄이 검색 결과에 섞였습니다: {stray[:2]}"


def test_download_is_the_same_lines(admin_http, base_url):
    shown = _log(admin_http, base_url, lines=100, level='INFO')['entries']
    resp = admin_http.get(f'{base_url}/logview/download',
                          params={'lines': 100, 'level': 'INFO'}, timeout=30)
    assert resp.status_code == 200
    assert 'attachment' in resp.headers.get('Content-Disposition', '')
    body = resp.text
    # 내려받는 사이에 새 줄이 붙을 수 있다 — 화면의 줄이 파일에 있는지만 본다.
    missing = [e['raw'] for e in shown[:20] if e['raw'] not in body]
    assert not missing, f'화면에 보인 줄이 내려받은 파일에 없습니다: {missing[:2]}'


# --------------------------------------------------------------------------
# 감사 로그
# --------------------------------------------------------------------------
def test_a_failed_login_is_recorded_with_who_and_where(admin_http, base_url):
    import requests

    nobody = f'e2e-nobody-{int(time.time())}'   # 없는 사용자 — 잠글 계정이 없다
    _login(requests.Session(), base_url, nobody, 'wrong-password')

    listing = admin_http.get(f'{base_url}/audit_log',
                             params={'username': nobody}, timeout=30)
    assert listing.status_code == 200
    assert nobody in listing.text and 'login.failure' in listing.text, (
        '로그인 실패가 감사 로그 목록에 없습니다')

    exported = admin_http.get(f'{base_url}/audit_log/export',
                              params={'username': nobody}, timeout=30)
    assert exported.status_code == 200
    rows = [r for r in csv.DictReader(io.StringIO(exported.text))
            if r.get('username') == nobody]
    assert rows, 'CSV 내보내기에 그 로그인 실패가 없습니다'
    row = rows[0]
    assert row['action'] == 'login.failure' and row['result'] == 'failure'
    assert row['ip_address'] and row['ip_address'] != 'unknown address', (
        f"감사 기록에 접속 주소가 없습니다({row['ip_address']!r}) — 누가 어디서 "
        f"시도했는지 남지 않습니다")


def test_the_action_filter_keeps_only_that_action(admin_http, base_url):
    resp = admin_http.get(f'{base_url}/audit_log/export',
                          params={'action': 'login.failure'}, timeout=30)
    assert resp.status_code == 200
    actions = {r['action'] for r in csv.DictReader(io.StringIO(resp.text))}
    assert actions <= {'login.failure'}, f'다른 사건이 섞였습니다: {actions}'
