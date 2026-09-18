# coding=utf-8
"""L2 · P2 — 에너지 사용량 두 화면이 **맞는 숫자**를 내는가.

화면이 뜨는 것만으로는 부족하다 — 이 화면의 쓸모는 숫자다. 시드가 검산할 수
있는 값을 넣는다:

  * 출력: E2E Virtual Multi 채널 0 에 전류 2 A, 지난 하루 1 시간 켜짐
    → 1 시간 · 전압 × 2 A × 1 h / 1000 kWh
  * 전류 입력: 2 A 일정 → 평균 2 A, 1 시간 = 전압 × 2 / 1000 kWh,
    1 일 = 그 × 24

그리고 보기 권한만 있는 사람(Monitor)이 추가를 누르면 **거절**이어야 한다 —
2026-09-18 까지 이 거절 가지가 없는 엔드포인트로 돌려보내 500 이 났다.
"""
import re

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import form_csrf

pytestmark = pytest.mark.e2e


def _rows_from(html, marker):
    """`marker` 가 든 행부터의 표 행들 — 칸 글자 목록의 목록."""
    start = html.find(marker)
    assert start >= 0, f"'{marker}' 가 화면에 없습니다"
    # 표식이 행 **안에** 있으면(출력 이름) 그 행부터, 행 밖이면(표 머리) 그 자리부터.
    enclosing = html.rfind('<tr', 0, start)
    if enclosing >= 0 and html.find('</tr>', enclosing, start) < 0:
        start = enclosing
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html[start:], flags=re.S):
        rows.append([re.sub(r'<[^>]+>|\s+', ' ', td).strip()
                     for td in re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)])
    return rows


def _hours_and_kwh(rows):
    """kWh 행과 그 바로 앞 행(켜짐 시간 또는 전류 평균)의 숫자.

    행 이름표는 언어마다 다르므로 언어와 무관한 `kWh (@N V)` 를 기준으로 삼는다.
    """
    for i, row in enumerate(rows):
        if any(cell.startswith('kWh (@') for cell in row):
            kwh = _numbers(row)
            # 앞 행은 번호·채널 칸이 앞에 붙을 수 있다 — 기간 칸만 뒤에서 자른다.
            return _numbers(rows[i - 1])[-len(kwh):], kwh
    raise AssertionError(f'kWh 행을 찾지 못했습니다: {rows[:4]}')


def _numbers(cells):
    return [float(c) for c in cells if re.fullmatch(r'-?\d+(\.\d+)?', c)]


def _volts(html):
    found = re.search(r'kWh \(@(\d+) V\)', html)
    assert found, '전압 표시(kWh (@N V))를 찾지 못했습니다'
    return int(found.group(1))


def test_output_energy_is_hours_times_volts_times_amps(admin_http, base_url):
    html = admin_http.get(f'{base_url}/energy_usage_outputs', timeout=60).text
    volts = _volts(html)
    # 채널 0 이 첫 행이다(채널 순서대로 그린다). 그 행 다음이 시간·kWh·비용.
    hours, kwh = _hours_and_kwh(_rows_from(html, F.OUTPUT_MULTI))
    assert len(hours) == 5 and len(kwh) == 5, (
        f'기간 5칸(일·주·월·월(기준일)·년)이 아닙니다: {hours} / {kwh}')

    expected_hours = F.ENERGY_OUTPUT_SEC_ON / 3600
    # 제어 검사(L3·승인 게이트)가 같은 채널을 몇 초씩 켰다 끈다 — 그만큼만 허용.
    assert expected_hours <= hours[0] <= expected_hours + 0.05, (
        f'지난 하루 켜짐이 {hours[0]} 시간입니다 — 시드는 {expected_hours} 시간')
    expected_kwh = volts * F.ENERGY_OUTPUT_AMPS * hours[0] / 1000
    assert abs(kwh[0] - expected_kwh) < 0.01, (
        f'kWh 가 {kwh[0]} 입니다 — {volts} V × {F.ENERGY_OUTPUT_AMPS} A × '
        f'{hours[0]} h = {expected_kwh:.3f}')
    # 기간이 길어질수록 줄어들 수 없다(일 ≤ 주 ≤ 월 ≤ 년).
    day, week, month, _month_from, year = hours
    assert day <= week <= month <= year, f'기간별 누적이 거꾸로입니다: {hours}'


def test_input_current_energy_is_added_and_computed(admin_http, base_url):
    page = f'{base_url}/energy_usage_input_amp'
    html = admin_http.get(page, timeout=60).text
    option = re.search(
        r'<option value="([^"]+)"[^>]*>([^<]*' + re.escape(F.ENERGY_INPUT_MEASUREMENT)
        + r'[^<]*)</option>', html)
    assert option, '추가 목록에 전류(A) 측정이 없습니다'
    before = html.count('collapseContainer-input-')

    resp = admin_http.post(page, timeout=60, data={
        'csrf_token': form_csrf(html),
        'energy_usage_select': option.group(1),
        'energy_usage_add': '1'})
    assert resp.status_code == 200, f'추가가 HTTP {resp.status_code}'

    html = admin_http.get(page, timeout=60).text
    assert html.count('collapseContainer-input-') > before, '항목이 추가되지 않았습니다'
    volts = _volts(html)
    # 마지막 항목(방금 추가한 것)의 표 — 전류 평균·kWh 두 행
    last = html.rfind('collapseContainer-input-')
    amps, kwh = _hours_and_kwh(_rows_from(html[last:], '<table'))
    assert amps and all(abs(a - F.ENERGY_INPUT_AMPS) < 0.01 for a in amps), (
        f'전류 평균이 {amps} 입니다 — 시드는 {F.ENERGY_INPUT_AMPS} A 일정')
    hour_kwh = volts * F.ENERGY_INPUT_AMPS / 1000
    assert abs(kwh[0] - hour_kwh) < 0.01 and abs(kwh[1] - hour_kwh * 24) < 0.01, (
        f'kWh(시간·하루)가 {kwh[:2]} 입니다 — 기대 {hour_kwh:.3f}, '
        f'{hour_kwh * 24:.3f}')


def test_a_monitor_is_turned_away_not_crashed(monitor_http, base_url):
    """보기만 되는 사람이 추가를 누르면 **거절**된다 — 500 이 아니다."""
    page = f'{base_url}/energy_usage_input_amp'
    html = monitor_http.get(page, timeout=60).text
    before = html.count('collapseContainer-input-')
    option = re.search(r'<option value="([^",]+,[^"]+)"', html)
    assert option, '모니터 화면에 측정 목록이 없습니다(보기는 되어야 합니다)'
    resp = monitor_http.post(page, timeout=60, allow_redirects=False, data={
        'csrf_token': form_csrf(html),
        'energy_usage_select': option.group(1),
        'energy_usage_add': '1'})
    assert resp.status_code in (302, 303), (
        f'권한 없는 추가가 HTTP {resp.status_code} 입니다 — 거절 대신 오류')
    after = monitor_http.get(page, timeout=60).text.count('collapseContainer-input-')
    assert after == before, '보기 권한만 있는 사람의 추가가 저장됐습니다'
