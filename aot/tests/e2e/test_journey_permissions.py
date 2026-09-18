# coding=utf-8
"""L2 · J19 — 권한 없는 사용자가 무엇을 못 하는가.

L0 는 **익명**이 비공개 경로에 닿는지 본다. 여기서 보는 것은 다르다 —
로그인은 했지만 **권한이 없는** 사용자다. 이쪽이 더 조용히 샌다: 세션이 있으니
`login_required` 는 통과하고, 그 다음 역할 검사를 빠뜨린 자리만 열린다.

게스트 역할은 설정상 전부 `False` 다(edit_settings·edit_controllers·edit_users·
view_settings·view_logs …). 그러므로 **관리 화면은 닫히고, 쓰기는 거부**돼야
한다. 다만 장치 목록처럼 보기만 하는 화면은 열린다 — 과잉 차단도 사고다.
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

# 게스트가 **들어가면 안 되는** 화면.
FORBIDDEN_PAGES = (
    '/settings/users',
    '/settings/general',
    '/settings/api_key',
    '/admin/upgrade',
    '/audit_log',
    '/logview',
    '/geo/design',
)

# 게스트도 **볼 수 있어야 하는** 화면. 과잉 차단을 잡는 쪽이다.
ALLOWED_PAGES = (
    '/output',
    '/input',
    '/function',
    '/notes',
)


def _blocked(resp):
    """막혔는가 — 거부 응답이거나, 원래 가려던 화면이 아닌 곳으로 되돌려졌거나.

    이 앱의 역할 게이트는 대개 홈(`/`)으로 되돌린다(403 을 주지 않는다). 그래서
    "리디렉션되었다" 자체를 막힘으로 본다. 200 으로 화면이 그려졌다면 열린 것이다.
    """
    return (resp.status_code in (401, 403)
            or resp.status_code in (301, 302, 303, 307, 308))


@pytest.mark.parametrize('path', FORBIDDEN_PAGES)
def test_a_guest_cannot_open_management_screens(guest_http, base_url, path):
    resp = guest_http.get(base_url + path, timeout=30, allow_redirects=False)
    assert _blocked(resp), (
        f'게스트가 {path} 를 열었습니다(HTTP {resp.status_code}) — '
        f'역할 검사가 빠졌습니다')


@pytest.mark.parametrize('path', ALLOWED_PAGES)
def test_a_guest_can_still_see_what_they_are_allowed_to(guest_http, base_url,
                                                        path):
    """과잉 차단 감시 — 볼 수 있어야 하는 화면까지 막으면 그것도 사고다."""
    resp = guest_http.get(base_url + path, timeout=30, allow_redirects=False)
    assert resp.status_code == 200, (
        f'게스트가 볼 수 있어야 하는 {path} 가 막혔습니다'
        f'(HTTP {resp.status_code} → {resp.headers.get("Location", "")})')


def test_a_guest_cannot_operate_an_output(guest_http, admin_http, base_url):
    """보기만 되는 사용자가 **장치를 켤 수 있으면** 안 된다.

    출력 제어는 `GET /output_mod/<출력>/<채널>/on/sec/0` 이다. 화면에 버튼이
    보이느냐와 별개로 **서버가 거부**해야 한다 — 버튼을 숨기는 것만으로 막았다고
    여기면, 주소를 아는 사람에게는 열려 있는 셈이다.
    """
    # 대상 출력 id 는 관리자로 얻는다(게스트가 목록을 못 볼 수도 있으므로).
    page = admin_http.get(f'{base_url}/output', timeout=30)
    import re
    match = re.search(r'name="([0-9a-f-]{36})/0/on/sec/0"', page.text)
    assert match, '출력 제어 버튼을 찾지 못했습니다'
    output_id = match.group(1)

    resp = guest_http.get(f'{base_url}/output_mod/{output_id}/0/on/sec/0',
                          timeout=30, allow_redirects=False)

    said_ok = resp.status_code == 200 and 'SUCCESS' in resp.text.upper()
    assert not said_ok, (
        f'게스트가 출력을 켰습니다 — 역할 검사가 없습니다. 응답: '
        f'{resp.status_code} {resp.text[:80]!r}')


def test_a_guest_cannot_save_a_dashboard_layout(guest_http, base_url):
    """쓰기 API 하나를 더 본다 — 배치 저장은 `edit_controllers` 가 필요하다."""
    resp = guest_http.post(f'{base_url}/save_dashboard_layout',
                           json=[{'id': 'x', 'x': 0, 'y': 0, 'w': 1, 'h': 1}],
                           timeout=30, allow_redirects=False)
    assert resp.status_code != 200 or 'success' not in resp.text.lower(), (
        f'게스트가 대시보드 배치를 저장했습니다: '
        f'{resp.status_code} {resp.text[:80]!r}')
