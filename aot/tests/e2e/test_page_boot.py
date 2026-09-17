# coding=utf-8
"""L1 — 페이지 부팅 검사.

앱의 모든 페이지를 브라우저로 한 번씩 열고, **화면이 실제로 부팅됐는지**만
본다. 무엇이 예쁜지는 보지 않는다. 다음 다섯 가지 중 하나라도 어긋나면
그 페이지는 사람이 열었을 때 이미 망가져 있다.

  1. JS 콘솔에 오류가 없다            — 번역문이 인라인 JS 를 깨뜨려 그리드스택이
                                        통째로 죽었던 사고가 이 조건에 걸린다
  2. 4xx/5xx 응답을 받지 않았다        — CSS·JS 링크 누락, 권한 누락
  3. 빈 스타일시트가 없다              — `@layer` 순서 사고로 벤더 CSS 3개가
                                        통째로 안 실렸던 것, 주석 오타로 규칙이
                                        증발했던 것이 정확히 이 조건이다
  4. 앵커 요소가 그려져 있다           — 흰 화면·접힌 레이아웃
  5. 가로로 넘치지 않는다              — 정렬 사고

판정이 "페이지가 부팅됐는가"이므로 기능이 바뀌어도 잘 깨지지 않는다. 대신
대상이 넓다 — 손대지 않은 화면이 죽는 것을 잡는 것이 목적이기 때문이다.
"""
import os
import re

import pytest

from aot.tests.e2e import pages as P
from aot.tests.e2e.routes_cache import get_routes

pytestmark = pytest.mark.e2e

# --------------------------------------------------------------------------
# 수집 시점에 페이지 목록을 정한다 — 페이지마다 테스트가 하나씩 생겨야
# 실패가 어느 화면인지 바로 보인다.
# --------------------------------------------------------------------------
_ROUTES = get_routes() if os.environ.get('AOT_E2E_BASE_URL') else []
PAGE_RULES = P.page_rules(_ROUTES)

# 무시하는 콘솔 오류 — 사유와 날짜를 반드시 적는다.
IGNORED_CONSOLE = (
    # 데몬이 없으면(L0·L1 은 데몬 없이 돈다) 상태 폴링이 실패한다.
    re.compile(r'daemon|9081', re.I),
    # 외부 타일·날씨 제공자. 인터넷 상태에 판정이 달리면 안 된다.
    re.compile(r'rainviewer|openweather|sentinel|agromonitoring', re.I),
)

# 무시하는 실패 응답 — 같은 규칙.
IGNORED_RESPONSES = (
    re.compile(r'/api/geo/proxy/'),
    re.compile(r'rainviewer|openweather|tile\.openstreetmap'),
    # 브라우저가 자동으로 찾는 것들.
    re.compile(r'/favicon\.ico$'),
)


# 실패했을 때 사람이 볼 것을 남기는 자리. CI 가 아티팩트로 업로드한다.
ARTIFACT_DIR = os.path.join('.local', 'e2e-artifacts')


def _ignored(patterns, text):
    return any(p.search(text or '') for p in patterns)


def _evidence_name(rule):
    return (rule.strip('/').replace('/', '_') or 'root')


def _save_evidence(page, rule, problems, console_errors, bad_responses):
    """스크린샷과 수집한 사실을 파일로 남긴다.

    "콘솔 오류 3건" 만 보고 원인을 찾는 것과, 그 순간의 화면을 같이 보는 것은
    진단 속도가 다르다. 실패했을 때만 남기므로 통과 경로의 비용은 0 이다.
    """
    try:
        os.makedirs(ARTIFACT_DIR, exist_ok=True)
        stem = os.path.join(ARTIFACT_DIR, _evidence_name(rule))
        page.screenshot(path=f'{stem}.png', full_page=True)
        with open(f'{stem}.txt', 'w') as f:
            f.write(f'경로: {rule}\n\n문제:\n')
            f.writelines(f'  - {p}\n' for p in problems)
            f.write('\n콘솔 오류:\n')
            f.writelines(f'  {e}\n' for e in console_errors)
            f.write('\n실패 응답:\n')
            f.writelines(f'  {r}\n' for r in bad_responses)
    except Exception:                        # noqa: BLE001
        # 증거 저장이 실패해도 판정 자체는 그대로 알려야 한다.
        pass


def _problems(rule, state, console_errors, bad_responses):
    problems = []

    if '/login' in state['final_url'] and rule != '/':
        problems.append(
            f"로그인으로 튕겼습니다 → {state['final_url']} "
            f"(관리자 세션이 끊겼거나 권한 게이트가 과합니다)")

    if console_errors:
        problems.append('콘솔 오류 %d건: %s' % (
            len(console_errors), ' | '.join(console_errors[:3])))

    if bad_responses:
        problems.append('실패 응답 %d건: %s' % (
            len(bad_responses), ' | '.join(bad_responses[:3])))

    if state['dead_sheets']:
        problems.append(
            '규칙이 있는데 하나도 적용되지 않은 스타일시트: %s'
            % ', '.join(state['dead_sheets'][:3]))

    if state['body_height'] == 0:
        problems.append('본문 높이가 0 입니다 — 빈 화면')

    if state['overflow_x'] > 1:
        problems.append(f"가로로 {state['overflow_x']}px 넘칩니다")

    for selector, height in state['anchors'].items():
        if height is None:
            problems.append(f'앵커 요소가 없습니다: {selector}')
        elif height == 0:
            problems.append(f'앵커 요소의 높이가 0 입니다: {selector}')

    return problems


@pytest.fixture(scope='module')
def boot_context(browser, storage_state):
    """L1 전용 컨텍스트 — 페이지마다 새로 만들면 54번 로그인 쿠키를 다시 싣는다."""
    context = browser.new_context(
        storage_state=storage_state,
        viewport={'width': 1440, 'height': 900},
        locale='ko-KR')
    yield context
    context.close()


def _open_and_collect(context, base_url, rule):
    """페이지를 열고 콘솔·네트워크·DOM 상태를 거둬, 문제 목록을 돌려준다.

    판정을 이 안에서 하는 이유는 하나다 — 문제가 있을 때 **페이지를 닫기 전에**
    스크린샷을 남겨야 하기 때문이다.
    """
    url = base_url + rule
    console_errors = []
    bad_responses = []

    page = context.new_page()
    page.on('console', lambda msg: (
        console_errors.append(msg.text)
        if msg.type == 'error' and not _ignored(IGNORED_CONSOLE, msg.text)
        else None))
    page.on('pageerror', lambda err: (
        console_errors.append(f'pageerror: {err}')
        if not _ignored(IGNORED_CONSOLE, str(err)) else None))
    page.on('response', lambda resp: (
        bad_responses.append(f'{resp.status} {resp.url}')
        if resp.status >= 400 and not _ignored(IGNORED_RESPONSES, resp.url)
        else None))

    try:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        # 부팅 JS(위젯·지도·그리드스택)가 돌 시간을 준다. networkidle 은
        # 폴링이 있는 화면에서 영영 오지 않으므로 쓰지 않는다.
        page.wait_for_timeout(1500)

        state = page.evaluate(r"""async () => {
            // 같은 출처인데 규칙이 하나도 없는 시트를 찾는다. 다만 **비어 있는
            // 것이 정상인 파일**이 있다(예: custom-light.css 는 "라이트 기본과
            // 다른 값만" 담는 규칙이라 지금은 주석뿐이다). 그래서 파일을 실제로
            // 받아 보고, 규칙 블록이 있는데도 cssRules 가 0 인 것만 사고로 센다
            // — 그것이 @layer 순서·주석 오타로 CSS 가 통째로 안 실린 모습이다.
            const suspects = [];
            for (const sheet of Array.from(document.styleSheets)) {
                let rules = null;
                try { rules = sheet.cssRules; } catch (e) { continue; }  // 교차출처
                if (rules && rules.length === 0 && sheet.href) suspects.push(sheet.href);
            }
            const dead = [];
            for (const href of suspects) {
                try {
                    const text = await (await fetch(href)).text();
                    const withoutComments = text.replace(/\/\*[\s\S]*?\*\//g, '');
                    if (withoutComments.includes('{')) dead.push(href);
                } catch (e) {
                    dead.push(href + ' (본문을 받지 못함: ' + e + ')');
                }
            }
            const de = document.documentElement;
            return {
                url: location.pathname,
                dead_sheets: dead,
                empty_but_ok: suspects.length - dead.length,
                sheet_count: document.styleSheets.length,
                body_height: document.body ? document.body.scrollHeight : 0,
                overflow_x: de.scrollWidth - de.clientWidth,
            };
        }""")
        state['anchors'] = {}
        for selector in P.ANCHORS.get(page.url.split('?')[0].replace(
                page.url.split('/')[0] + '//' + page.url.split('/')[2], ''), []):
            el = page.query_selector(selector)
            box = el.bounding_box() if el else None
            state['anchors'][selector] = (
                None if el is None else (box['height'] if box else 0))
        state['final_url'] = page.url
        problems = _problems(rule, state, console_errors, bad_responses)
        if problems:
            _save_evidence(page, rule, problems, console_errors, bad_responses)
        return problems
    finally:
        page.close()


@pytest.mark.skipif(not PAGE_RULES,
                    reason='라우트 목록을 얻지 못했습니다(E2E 스택 미기동?)')
@pytest.mark.parametrize('rule', PAGE_RULES)
def test_page_boots(boot_context, base_url, rule):
    problems = _open_and_collect(boot_context, base_url, rule)
    assert not problems, f'{rule}\n' + '\n'.join(f'  - {p}' for p in problems)
