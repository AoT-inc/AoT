# coding=utf-8
"""L2 · P2 — 내보낸 것이 쓸모 있는가: 측정값 CSV, 그리고 **다시 가져올 수 있는**
설정 백업.

설정 가져오기는 실제로 돌리지 않는다 — DB 를 갈아 끼우고 데몬을 세우므로 이
스택의 나머지 검사를 무너뜨린다. 대신 **파일명 검사를 통과하는가** 까지만 본다:
내보낸 이름 그대로의 zip 에 DB 대신 빈 파일을 넣어 올리면, 이름 검사를 지나
"zip 안에 DB 가 없다" 에서 멈춰야 한다.

2026-09-18 처음 돌렸을 때 그 왕복이 끊겨 있었다(처음 커밋부터) — 내보내기는
`AoT_버전_setup_…zip` 으로 이름을 짓고, 가져오기는 세 번째 조각이 `Settings` 가
아니면 거절했다. 백업은 되는데 복원이 안 되는 상태였다.
"""
import datetime
import io
import re
import zipfile

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import form_csrf

pytestmark = pytest.mark.e2e

DATABASE_NAME = 'aot.db'


def _export_page(session, base_url):
    resp = session.get(f'{base_url}/export', timeout=60)
    assert resp.status_code == 200
    return resp.text


def _export_settings(admin_http, base_url):
    html = _export_page(admin_http, base_url)
    resp = admin_http.post(f'{base_url}/export', timeout=120, data={
        'csrf_token': form_csrf(html), 'export_settings_zip': '1'})
    assert resp.status_code == 200
    assert resp.headers.get('Content-Type', '').startswith('application/zip'), (
        f"설정 내보내기가 zip 이 아닙니다: {resp.headers.get('Content-Type')}")
    name = re.search(r'filename="?([^";]+)"?',
                     resp.headers.get('Content-Disposition', ''))
    assert name, '내려받는 파일 이름이 없습니다'
    return name.group(1), resp.content


def _upload(admin_http, base_url, filename, payload):
    html = _export_page(admin_http, base_url)
    resp = admin_http.post(
        f'{base_url}/export', timeout=120,
        data={'csrf_token': form_csrf(html), 'settings_import_upload': '1'},
        files={'settings_import_file': (filename, payload, 'application/zip')})
    return resp


def _refused_by_name(html):
    """가져오기가 파일 **이름**에서 거절했는가 — 거절 문구는 `조각 != 기대값` 이다.

    페이지 스크립트에도 `!=` 가 흔하므로 기대값(AoT·Settings)까지 붙여 찾는다.
    """
    return re.search(r'!= (AoT|Settings)\b', html) is not None


def _zip_without_database():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('not-the-database.txt', 'e2e')
    return buf.getvalue()


def test_measurements_come_out_as_csv(admin_http, base_url):
    html = _export_page(admin_http, base_url)
    option = re.search(r'<option value="([^"]+)">[^<]*' + re.escape(F.INPUT_RAM)
                       + r'[^<]*RAM Free', html)
    assert option, '내보내기 목록에 시드 입력의 측정이 없습니다'
    # 넉넉한 기간 — 서버는 이 문자열을 **서버 지역시각**으로 읽는다.
    now = datetime.datetime.now()
    fmt = '%m/%d/%Y %H:%M'
    period = (f'{(now - datetime.timedelta(days=3)).strftime(fmt)} - '
              f'{(now + datetime.timedelta(days=1)).strftime(fmt)}')
    resp = admin_http.post(f'{base_url}/export', timeout=120, data={
        'csrf_token': form_csrf(html), 'measurement': option.group(1),
        'date_range': period, 'export_data_csv': '1'})
    assert resp.status_code == 200, f'측정값 내보내기가 HTTP {resp.status_code}'
    assert '/export_data/' in resp.url, f'CSV 로 가지 않았습니다: {resp.url}'
    lines = [l for l in resp.text.splitlines() if l.strip()]
    assert len(lines) > 24, f'CSV 가 {len(lines)} 줄뿐입니다 — 시드는 3일에 시간당 한 점'
    values = [float(v) for l in lines[1:] for v in re.findall(r',(\d+(?:\.\d+)?)\s*$', l)]
    assert values and all(1000 <= v < 1120 for v in values), (
        f'CSV 값이 시드(1000~1119 MB)와 다릅니다: {values[:5]}')


def test_a_settings_backup_is_a_zip_with_the_database(admin_http, base_url):
    filename, content = _export_settings(admin_http, base_url)
    assert filename.startswith('AoT_') and '_Settings_' in filename, (
        f'백업 파일 이름이 가져오기 형식(AoT_버전_Settings_…)이 아닙니다: {filename}')
    names = zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert DATABASE_NAME in names, f'백업 zip 에 {DATABASE_NAME} 가 없습니다: {names}'


@pytest.mark.parametrize('style', ['current', 'before-2026-09-18'])
def test_a_backup_name_passes_the_import_check(admin_http, base_url, style):
    """내보낸 이름(그리고 예전 이름)이 가져오기의 이름 검사를 통과한다."""
    filename, _content = _export_settings(admin_http, base_url)
    if style != 'current':
        filename = filename.replace('_Settings_', '_setup_')
    resp = _upload(admin_http, base_url, filename, _zip_without_database())
    assert resp.status_code == 200, f'가져오기가 HTTP {resp.status_code}'
    assert not _refused_by_name(resp.text), (
        f'내보낸 이름 그대로({filename})인데 가져오기가 이름을 거절했습니다 — '
        f'백업을 복원할 수 없습니다')
    assert DATABASE_NAME in resp.text, (
        '이름 검사 다음 단계(zip 안의 DB 확인)까지 가지 않았습니다')


def test_a_wrong_file_is_refused_and_nothing_breaks(admin_http, base_url):
    resp = _upload(admin_http, base_url, 'holiday-photos.zip', _zip_without_database())
    assert resp.status_code == 200, f'잘못된 파일이 HTTP {resp.status_code} 로 끝났습니다'
    assert _refused_by_name(resp.text), '엉뚱한 이름의 파일이 이름 검사를 지나갔습니다'
    # 그대로다 — 로그인도, 데이터도
    still = admin_http.get(f'{base_url}/input', timeout=60)
    assert still.status_code == 200 and '/login' not in still.url
    assert F.INPUT_RAM in still.text


def test_a_guest_cannot_download_the_settings(guest_http, base_url):
    """(관리자 전용이 된 뒤에도 남겨 둔다 — 가장 낮은 역할의 경계.)"""
    html = _export_page(guest_http, base_url)
    resp = guest_http.post(f'{base_url}/export', timeout=60, allow_redirects=False,
                           data={'csrf_token': form_csrf(html),
                                 'export_settings_zip': '1'})
    assert not resp.headers.get('Content-Type', '').startswith('application/zip'), (
        '게스트가 설정 DB(사용자·비밀번호 해시 포함)를 내려받았습니다')


def test_only_an_admin_can_import_settings(editor_http, admin_http, base_url):
    """설정 가져오기는 관리자만 — 설정 DB 에는 사용자 표가 들어 있다.

    편집자가 관리자 계정을 담은 DB 를 올리면 스스로 관리자가 될 수 있다
    (2026-09-18 결정: 관리자 전용). 편집자는 가져오기 칸이 안 보이고, 요청을
    직접 보내도 **이름 검사에도 닿지 못하고** 거절된다.
    """
    html = _export_page(editor_http, base_url)
    assert 'name="settings_import_file"' not in html, (
        '편집자 화면에 설정 가져오기 칸이 있습니다')
    assert 'name="export_settings_zip"' not in html, (
        '편집자 화면에 설정 내보내기 단추가 있습니다')
    resp = editor_http.post(f'{base_url}/export', timeout=60, data={
        'csrf_token': form_csrf(html), 'export_settings_zip': '1'})
    assert not resp.headers.get('Content-Type', '').startswith('application/zip'), (
        '편집자가 웹 화면에서 설정 DB 를 내려받았습니다')

    filename, _content = _export_settings(admin_http, base_url)
    resp = editor_http.post(
        f'{base_url}/export', timeout=120, allow_redirects=True,
        data={'csrf_token': form_csrf(html), 'settings_import_upload': '1'},
        files={'settings_import_file': (filename, _zip_without_database(),
                                        'application/zip')})
    assert resp.status_code == 200
    assert DATABASE_NAME + ' ' not in resp.text and 'not included in zip' not in resp.text, (
        '편집자의 가져오기가 파일 검사까지 진행됐습니다 — 권한 검사가 없습니다')
    assert 'edit_users' in resp.text, '편집자에게 권한 부족을 알리지 않았습니다'

    # 관리자에게는 칸이 있다
    assert 'name="settings_import_file"' in _export_page(admin_http, base_url)


API_EXPORT_SETTINGS = '/api/export_import/export_settings'


def test_only_an_admin_gets_the_settings_db_by_api(admin_http, editor_http,
                                                   monitor_http, base_url):
    """API 로 설정 DB 를 받는 것도 관리자만(2026-09-18 결정).

    예전에는 설정 보기(view_settings)만 봐서 모니터 역할도 사용자 표·비밀번호
    해시가 든 설정 DB 를 통째로 받았다.
    """
    headers = {'Accept': 'application/vnd.aot.v1+json'}
    for who, session in (('모니터', monitor_http), ('편집자', editor_http)):
        resp = session.get(base_url + API_EXPORT_SETTINGS, headers=headers, timeout=60)
        assert resp.status_code == 403, (
            f'{who}가 API 로 설정 DB 를 받았습니다(HTTP {resp.status_code})')
    resp = admin_http.get(base_url + API_EXPORT_SETTINGS, headers=headers, timeout=120)
    assert resp.status_code == 200 and resp.content[:2] == b'PK', (
        f'관리자가 API 로 설정 DB 를 받지 못했습니다(HTTP {resp.status_code})')


def _backup_action(session, base_url, action):
    """없는 백업으로 복원·내려받기를 요청한다 — 권한을 지나도 경로 검사에서 멈춘다."""
    token = form_csrf(_export_page(session, base_url))   # 세션 단위 토큰
    return session.post(f'{base_url}/admin/backup', timeout=60, data={
        'csrf_token': token, action: '1',
        'full_path': '/nonexistent/AoT-backup-e2e', 'selected_dir': 'e2e-none'})


@pytest.mark.parametrize('action', ['restore', 'download'])
def test_only_an_admin_can_restore_or_download_a_backup(admin_http, editor_http,
                                                         base_url, action):
    """백업 복원·내려받기는 관리자만 — 백업에는 설정 DB(사용자 표)가 통째로 있다."""
    refused = _backup_action(editor_http, base_url, action)
    assert refused.status_code == 200
    assert 'edit_users' in refused.text, (
        f'편집자의 {action} 요청이 권한에서 거절되지 않았습니다(경로 검사까지 갔습니다)')
    page = editor_http.get(f'{base_url}/admin/backup', timeout=60).text
    assert f'name="{action}"' not in page, f'편집자 화면에 {action} 단추가 있습니다'

    passed = _backup_action(admin_http, base_url, action)
    assert passed.status_code == 200
    assert 'edit_users' not in passed.text, f'관리자의 {action} 요청이 권한에서 거절됐습니다'
