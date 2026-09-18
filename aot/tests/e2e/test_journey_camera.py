# coding=utf-8
"""L2 · P2 — 카메라를 추가하고, 찍고, 지운다.

실제 카메라는 없다. 대신 **앱이 내놓는 정적 이미지를 URL 카메라로** 찍는다 —
컨테이너 안에서 `http://127.0.0.1/static/...jpg` 를 OpenCV 가 한 장 읽는다.
그래서 촬영 → 저장 → "마지막 이미지" 까지 장치 없이 끝까지 간다.

2026-09-18 처음 돌렸을 때 두 가지가 나왔다:
  * 확인창까지 거친 **삭제가 저장으로 처리돼** 카메라가 남았다 — 설정 폼에 늘
    들어 있는 `camera_mod` 숨은 칸을 서버가 삭제보다 먼저 봤다.
  * 카메라 블루프린트 전체가 로그인만 봤다 — 게스트가 화면을 열고 카메라를
    추가·수정·삭제·촬영할 수 있었다. `view_camera` 는 어디서도 검사되지 않았다.
"""
import re

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import csrf_headers, form_csrf
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e


def _camera_ids(page):
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('.grid-stack-item'))"
        "  .map(e => e.getAttribute('gs-id'))")


def _open_camera_page(page, base_url):
    page.goto(f'{base_url}/camera', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)


def test_add_point_capture_and_delete_a_camera(page, base_url):
    page.on('dialog', lambda dialog: dialog.accept())   # 삭제 확인(브라우저 confirm)
    _open_camera_page(page, base_url)
    before = set(_camera_ids(page))

    # 추가 — IP 카메라
    choose_option(page, 'camera_type_select', 'IP')
    page.click('input[name=camera_add]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(2000)
    new = [uid for uid in _camera_ids(page) if uid not in before]
    assert len(new) == 1, f'카메라가 하나 추가되지 않았습니다(새로 생긴 것 {len(new)}개)'
    uid = new[0]

    # 설정 — 이름과 주소(앱의 정적 이미지)
    page.click(f'[data-target="#modal_config_{uid}"]')
    page.wait_for_timeout(1200)
    form = f'#form_camera_options_{uid}'
    page.fill(f'{form} input[name=name]', F.CAMERA_NAME)
    page.fill(f'{form} input[name=ip_address]', F.CAMERA_IMAGE_URL)
    page.click(f'#modal_config_{uid} .modal-footer button[onclick*="camera_mod"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(2000)
    assert page.input_value(f'#camera_name_{uid}') == F.CAMERA_NAME, (
        '카메라 이름이 저장되지 않았습니다')

    # 활성화해야 촬영 단추가 켜진다
    page.click(f'#camera_activate_{uid}')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(2000)

    # 촬영 — 서버가 실제로 한 장을 저장하고, "마지막 이미지" 가 그것을 준다
    page.click(f'[data-target="#modal_config_{uid}"]')
    page.wait_for_timeout(1200)
    with page.expect_response(lambda r: f'/camera/capture/{uid}' in r.url,
                              timeout=60000) as shot:
        page.click(f'#btn_capture_start_{uid}')
    body = shot.value.json()
    assert shot.value.status == 200 and body.get('status') == 'success', (
        f'촬영이 실패했습니다: HTTP {shot.value.status}, {body}')
    image = page.context.request.get(f'{base_url}/camera/last_image/{uid}')
    assert image.status == 200 and image.headers.get('content-type', '').startswith('image/'), (
        f'마지막 이미지를 받지 못했습니다: HTTP {image.status}')
    assert len(image.body()) > 10000, '마지막 이미지가 비어 있습니다'

    # 삭제 — 확인창을 지나 실제로 사라진다
    page.click(f'#modal_config_{uid} .modal-footer button[onclick*="camera_delete"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(2000)
    assert uid not in _camera_ids(page), (
        '삭제를 확인했는데 카메라가 남아 있습니다 — 삭제가 저장으로 처리됐습니다')


def test_a_guest_cannot_see_or_touch_cameras(guest_http, admin_http, base_url):
    # 보기 — view_camera 가 없으면 화면이 열리지 않는다
    resp = guest_http.get(f'{base_url}/camera', timeout=30, allow_redirects=False)
    assert resp.status_code in (302, 303), (
        f'게스트가 카메라 화면을 열었습니다(HTTP {resp.status_code})')

    # 쓰기 — 관리자 화면의 폼 토큰으로 게스트가 추가를 보내 본다
    html = guest_http.get(f'{base_url}/export', timeout=30).text   # 게스트도 열리는 폼
    token = form_csrf(html)
    before = admin_http.get(f'{base_url}/camera', timeout=30).text.count('grid-stack-item"')
    guest_http.post(f'{base_url}/camera', timeout=30, allow_redirects=False,
                    data={'csrf_token': token, 'camera_type': 'ip_camera',
                          'camera_add': '1'})
    after = admin_http.get(f'{base_url}/camera', timeout=30).text.count('grid-stack-item"')
    assert after == before, '게스트가 보낸 카메라 추가가 저장됐습니다'

    # 촬영·순서 저장 — API 는 403. CSRF 는 실어 보낸다(없으면 그 앞에서 400).
    headers = csrf_headers(guest_http, base_url)
    for path in ('/camera/capture/none', '/camera/save_order'):
        resp = guest_http.post(f'{base_url}{path}', timeout=30, json={},
                               headers=headers)
        assert resp.status_code == 403, (
            f'게스트의 {path} 가 HTTP {resp.status_code} 입니다 — 거절돼야 합니다')
    resp = guest_http.get(f'{base_url}/camera/last_image/none', timeout=30)
    assert resp.status_code == 403, f'게스트가 카메라 이미지 경로에 닿았습니다({resp.status_code})'
