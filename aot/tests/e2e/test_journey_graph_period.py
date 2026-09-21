# coding=utf-8
"""L2 · J11 — 그래프 기간 버튼이 축을 그 기간으로 바꾸는가.

2026 년에 이 화면의 기간 버튼이 **엉뚱한 시작점**에 앵커되던 버그가 있었다
(rangeSelector 앵커). "1일" 을 눌렀는데 1일이 아닌 창이 그려지면, 사람은 그것을
최근 하루로 읽고 틀린 판단을 한다.

⚠ 판정 전에 알아 둘 것 둘.

* **기간 버튼은 "그래프 보기" 를 눌러야 적용된다.** 버튼만 누르면 활성 표시만
  바뀌고 축은 그대로다(설계대로다). 버튼만 누르고 축을 재면 "기간 버튼이 안
  먹는다" 로 잘못 읽는다 — 실제로 처음에 그렇게 읽었다.
* **기간 버튼은 첫 "그래프 보기" 뒤에 나타난다.** 측정을 고르자마자 기간을
  누르려 하면 버튼이 없다. 사람이 하는 순서 — 먼저 그리고, 기간을 바꾸고, 다시
  그린다 — 를 그대로 따른다.
* **데이터가 기간보다 충분히 길어야 한다.** 시드가 26시간치만 쓸 때는 "1일"
  (24h)과 "전체"(25.5h)의 폭이 구별되지 않았다. 지금은 5일치를 쓴다.

그리고 이 여정은 **센서 값이 실제로 저장돼야** 성립한다. 신규 도커 설치에서
측정 DB 버전 감지가 빗나가 값이 한 점도 저장되지 않던 결함이 바로 이 여정을
만들다 드러났다(`aot/scripts/measurement_db.py::_ping`).
"""
import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

HOUR_MS = 3600 * 1000


def _open_graph(page, base_url):
    page.goto(f'{base_url}/graph-async', wait_until='domcontentloaded')
    page.wait_for_selector('button.aot-measure-btn', timeout=25000)
    page.wait_for_timeout(2000)


def _choose_ram_measurement(page):
    """측정 드롭다운을 열어 시드 입력의 첫 채널을 고른다."""
    page.locator('button.aot-measure-btn', has_text='입력').first.click()
    page.wait_for_timeout(800)
    page.locator('.dropdown-menu.show label', has_text=F.INPUT_RAM).first.click()
    page.wait_for_timeout(500)
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)


def _draw(page):
    page.locator('button', has_text='그래프 보기').first.click()
    # 차트가 데이터를 받을 때까지 기다린다.
    # 페이지가 차트 핸들을 window.aotAsyncGraph 에 둔다(공용 시계열 차트 모듈).
    page.wait_for_function(
        "() => { const g = window.aotAsyncGraph;"
        "  return !!(g && g.getExtremes().dataMax != null); }",
        timeout=30000)
    page.wait_for_timeout(800)


def _axis(page):
    """지금 그려진 x 축의 범위와 점 수."""
    return page.evaluate(
        "() => { const g = window.aotAsyncGraph;"
        "  const x = g.getExtremes();"
        "  let pts = 0;"
        "  for (let i = 0; i < g.seriesCount; i++) pts += g.data(i).length;"
        "  return {min: x.min, max: x.max, dataMax: x.dataMax, points: pts}; }")


def _pick_period_and_draw(page, label):
    page.locator('.aot-period-btn', has_text=label).first.click()
    page.wait_for_timeout(500)
    _draw(page)


def test_the_chart_draws_the_seeded_measurements(page, base_url):
    """받침 — 데이터가 실제로 그려지는가. 이것이 서야 기간 판정이 의미 있다."""
    _open_graph(page, base_url)
    _choose_ram_measurement(page)
    _draw(page)
    axis = _axis(page)
    assert axis['points'] > 0, (
        '차트에 점이 하나도 없습니다 — 측정값이 저장되지 않았거나 조회가 '
        '빗나갔습니다(측정 DB 버전 감지를 먼저 의심할 것)')


def test_one_day_draws_about_one_day(page, base_url):
    """"1일" 은 최근 하루를 그린다 — 폭이 하루쯤이고, 끝이 최신 값이다."""
    _open_graph(page, base_url)
    _choose_ram_measurement(page)
    _draw(page)                       # 먼저 한 번 그려야 기간 버튼이 나타난다
    _pick_period_and_draw(page, '1일')
    axis = _axis(page)

    span_h = (axis['max'] - axis['min']) / HOUR_MS
    assert 20 <= span_h <= 26, (
        f'"1일" 인데 축 폭이 {span_h:.1f}시간입니다 — 기간이 맞지 않습니다')
    # 앵커 — 창의 끝이 최신 데이터여야 한다. 엉뚱한 시작점에 붙으면 끝이
    # 과거로 밀린다(그것이 예전 버그의 모습이었다).
    assert abs(axis['max'] - axis['dataMax']) <= 2 * HOUR_MS, (
        '"1일" 창의 끝이 최신 값에서 멀리 떨어져 있습니다 — 엉뚱한 시점에 '
        '앵커됐습니다')


def test_a_longer_period_draws_a_wider_window(page, base_url):
    """"1주" 는 "1일" 보다 넓게 그린다."""
    _open_graph(page, base_url)
    _choose_ram_measurement(page)
    _draw(page)

    _pick_period_and_draw(page, '1일')
    day = _axis(page)
    _pick_period_and_draw(page, '1주')
    week = _axis(page)

    day_h = (day['max'] - day['min']) / HOUR_MS
    week_h = (week['max'] - week['min']) / HOUR_MS
    assert week_h > day_h * 3, (
        f'"1주"({week_h:.0f}h)가 "1일"({day_h:.0f}h)보다 뚜렷이 넓지 않습니다 '
        f'— 기간 버튼이 축에 먹지 않았습니다')
