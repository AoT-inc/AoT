# coding=utf-8
"""L2 · P2 — 기준 메소드를 만들고, 점을 쌓고, 그 곡선을 읽고, 지운다.

메소드는 PID·조건이 따라가는 **목표값의 시간표**다. 빌더 화면에서 넣은 구간이
`/method-data` 가 돌려주는 곡선과 같아야 한다 — 곡선이 다르면 제어는 사람이
설계한 것과 다른 목표를 따라간다.

지속시간(Duration) 메소드로 두 구간을 쌓는다: 60 초 동안 20 → 25, 이어서 120 초
동안 25 → 30. 곡선은 20 에서 시작해 30 에서 끝나고, 길이는 180 초여야 한다.
"""
import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.journeys import choose_option

pytestmark = pytest.mark.e2e

SEGMENTS = ((60, 20, 25), (120, 25, 30))   # (초, 시작값, 끝값)


def _add_form(page):
    return page.locator("form:has(input[name='form-name'][value='addMethod'])")


def test_build_a_duration_method_and_read_its_curve(page, admin_http, base_url):
    page.on('dialog', lambda dialog: dialog.accept())   # 삭제 확인(브라우저 confirm)

    # 만들기
    page.goto(f'{base_url}/method', wait_until='domcontentloaded')
    # 이 화면에는 메소드마다 이름 칸·종류 칸이 있다 — 만들기 폼 안에서만 고른다.
    create = page.locator('form[action="/method-build/0"]')
    create.locator('input[name=name]').fill(F.METHOD_NAME)
    # 선택지 글자는 언어마다 다르다("지속시간"/"Duration") — 값으로 찾아 그 글자로 고른다.
    label = create.locator('select[name=method_type] option[value="Duration"]').inner_text().strip()
    choose_option(page, 'method_type', label)
    create.locator('input[name=Submit]').click()
    page.wait_for_url('**/method-build/*', timeout=20000,
                      wait_until='domcontentloaded')
    method_id = page.url.rstrip('/').rsplit('/', 1)[-1]
    assert method_id and method_id != '0', f'빌더로 가지 않았습니다: {page.url}'

    # 구간 쌓기 — 저장할 때마다 화면이 새로 읽힌다
    for seconds, start, end in SEGMENTS:
        form = _add_form(page)
        form.locator('input[name=duration]').fill(str(seconds))
        form.locator('input[name=setpoint_start]').fill(str(start))
        form.locator('input[name=setpoint_end]').fill(str(end))
        form.locator('input[name=save]').click()
        page.wait_for_load_state('domcontentloaded')
        page.wait_for_timeout(800)

    # 곡선 — 넣은 구간과 같아야 한다
    curve = admin_http.get(f'{base_url}/method-data/{method_id}', timeout=30).json()
    assert curve and isinstance(curve[0], list), f'곡선이 비었거나 형식이 다릅니다: {curve[:3]}'
    values = [point[1] for point in curve]
    times = [point[0] for point in curve]
    assert values[0] == pytest.approx(SEGMENTS[0][1]), (
        f'곡선이 {values[0]} 에서 시작합니다 — 첫 구간의 시작값은 {SEGMENTS[0][1]}')
    assert values[-1] == pytest.approx(SEGMENTS[-1][2]), (
        f'곡선이 {values[-1]} 에서 끝납니다 — 마지막 구간의 끝값은 {SEGMENTS[-1][2]}')
    span_s = (times[-1] - times[0]) / (1000 if times[-1] > 1e11 else 1)
    total = sum(seconds for seconds, _s, _e in SEGMENTS)
    assert abs(span_s - total) <= 2, f'곡선 길이가 {span_s} 초입니다 — 구간 합은 {total} 초'

    # 지우기 — 목록에서 사라지고 곡선도 없다
    page.goto(f'{base_url}/method', wait_until='domcontentloaded')
    page.click(f'a[href="/method-delete/{method_id}"]')
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(800)
    assert page.locator(f'a[href="/method-build/{method_id}"]').count() == 0, (
        '삭제한 메소드가 목록에 남아 있습니다')


def test_a_monitor_cannot_create_a_method(monitor_http, admin_http, base_url):
    from aot.tests.e2e.conftest import form_csrf

    html = monitor_http.get(f'{base_url}/method', timeout=30).text
    before = admin_http.get(f'{base_url}/method', timeout=30).text.count('/method-build/')
    monitor_http.post(f'{base_url}/method-build/0', timeout=30, allow_redirects=False,
                      data={'csrf_token': form_csrf(html), 'form-name': 'createMethod',
                            'name': 'E2E Monitor Method', 'method_type': 'Duration',
                            'Submit': 'Add'})
    after = admin_http.get(f'{base_url}/method', timeout=30).text.count('/method-build/')
    assert after == before, '보기 권한만 있는 사람이 메소드를 만들었습니다'
