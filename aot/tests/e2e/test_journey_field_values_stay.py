# coding=utf-8
"""L2 · 입력칸을 벗어나도 **넣은 값이 그대로** 남는가.

2026-09-18 E2E(메소드 빌더)가 잡은 회귀. 지속시간 표기 도우미(공용 시간 번들)가
이름·id 에 sec/period/duration/delay 가 든 칸이면 전부 붙어, 칸을 벗어나는 순간
값을 "HH:MM:SS" 로 바꿨다. 그 파일이 2026-08-13 공용 번들에 처음 실리면서 켜졌고:

  * 'secondary'·'secret' 에도 'sec' 가 든다 — 색상 설정의 보조색 hex 가 시각
    문자열이 되고, Google OAuth client secret 이 망가졌다.
  * 숫자 칸은 그 문자열을 받지 못해 **값이 비워졌다** — 일정의 작업 지속시간,
    메소드 구간 길이.

저장은 하지 않는다 — 값을 넣고 칸을 벗어난 순간만 본다.
"""
import pytest

pytestmark = pytest.mark.e2e

CASES = (
    # (화면, 칸, 넣을 값) — 모두 페이지를 열 때 이미 그려져 있는 칸이다.
    ('/settings/custom_ui', '#hex_bd_secondary', '#123456'),
    ('/settings/custom_ui', '#hex_text_color_secondary', '#654321'),
    ('/settings/integrations', '#google_oauth_client_secret', 'e2e-secret-123'),
    ('/scheduler', '#taskDuration', '45'),
)


@pytest.mark.parametrize('path,selector,value', CASES,
                         ids=[f'{c[0]} {c[1]}' for c in CASES])
def test_leaving_a_field_keeps_what_was_typed(page, base_url, path, selector, value):
    page.goto(f'{base_url}{path}', wait_until='domcontentloaded')
    page.wait_for_timeout(1200)
    field = page.locator(selector).first
    assert field.count(), f'{path} 에 {selector} 칸이 없습니다'
    # 칸이 모달 안에 숨어 있을 수 있다 — 사람의 입력과 같은 사건(값 → blur)을 직접 낸다.
    kept = field.evaluate("""(el, value) => {
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('blur'));
        el.blur();
        return el.value;
    }""", value)
    assert kept == value, (
        f'{path} 의 {selector} 에 {value!r} 를 넣고 벗어났더니 {kept!r} 가 됐습니다')
