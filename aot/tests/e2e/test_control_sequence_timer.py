# coding=utf-8
"""L3 · C3~C5 — 시퀀스와 타이머가 **데몬 기준으로** 약속을 지키는가.

  * C3 시퀀스를 켜면 데몬이 그 단계를 실제로 돌리고, 위젯이 보여 주는 것이
    데몬의 사실과 같다.
  * C5 시퀀스를 끄면 그 단계의 출력이 **확실히** 꺼진다 — 끈 줄 알았는데 밸브가
    열려 있는 것이 이 계열에서 가장 위험한 사고다.
  * C4 타이머가 도는 중에 웹 앱이 재시작돼도 출력과 표시가 사실과 맞고, 반복은
    남은 주기를 이어 돈다. 타이머의 반복은 웹 프로세스 안의 작업 스레드가 돌리므로,
    재시작이 곧 그 스레드의 죽음이다 — 복구가 상태 파일로 그 자리를 되찾는다.

대상은 시드가 만든 가상 출력(E2E Virtual Multi)의 채널 1(시퀀스)·2(타이머)다.
채널 0 은 다른 제어 검사와 에너지 검사가 쓴다.
"""
import time

import pytest

from aot.tests.e2e import fixtures as F
from aot.tests.e2e.conftest import csrf_headers, reset_http_sessions
from aot.tests.e2e.journeys import open_dashboard

pytestmark = pytest.mark.e2e


def _output_id(admin_http, base_url):
    """시퀀스 단계가 가리키는 출력 — 시퀀스 상태가 알려 주는 장치에서 읽지 않고,
    출력 화면의 켜기 단추 이름(`<출력id>/<채널>/on/...`)에서 읽는다."""
    import re
    html = admin_http.get(f'{base_url}/output', timeout=60).text
    i = html.find(F.OUTPUT_MULTI)
    found = re.search(r'name="([0-9a-f-]{36})/\d+/on/', html[i:])
    assert i >= 0 and found, '출력 화면에서 시험 출력을 찾지 못했습니다'
    return found.group(1)


def _channel(output_states, output_id, channel):
    return (output_states().get(output_id) or {}).get(str(channel))


def _wait_channel(output_states, output_id, channel, expected, timeout_s):
    deadline = time.time() + timeout_s
    seen = None
    while time.time() < deadline:
        seen = _channel(output_states, output_id, channel)
        if seen == expected:
            return seen
        time.sleep(1.0)
    return seen


def _force(admin_http, base_url, output_id, channel, state):
    admin_http.get(f'{base_url}/output_mod/{output_id}/{channel}/{state}/sec/0',
                   timeout=30)


def _sequence_status(admin_http, base_url, function_id):
    return admin_http.get(f'{base_url}/function_status_activated/{function_id}',
                          timeout=30).json()


def _set_sequence(admin_http, base_url, function_id, on):
    """위젯의 스위치가 부르는 그 경로 — 뒷정리·준비용."""
    state = 'activate' if on else 'deactivate'
    admin_http.get(f'{base_url}/sequence_func_activate_toggle/{function_id}/{state}',
                   timeout=60)


def _open_sequence_widget(page, base_url):
    open_dashboard(page, base_url, F.CONTROL_DASHBOARD)
    box = page.locator('.seq-widget-container').first
    box.wait_for(timeout=20000)
    return box.get_attribute('data-wid'), box.get_attribute('data-fid')


def _flip_widget_switch(page, wid):
    # 체크박스는 숨은 입력이다 — 사람이 누르는 것은 그것을 감싼 스위치다.
    page.locator(f'#seq-main-toggle-{wid}').locator('xpath=..').click()


# 단계가 시작하려면 다음 사이클 경계를 기다려야 할 수 있다(주기 60 초).
STEP_START_S = F.SEQUENCE_RUN_PERIOD_SEC + 30


def test_c3_an_activated_sequence_runs_and_the_widget_agrees(
        daemon, page, admin_http, base_url, output_states):
    out = _output_id(admin_http, base_url)
    ch = F.SEQUENCE_RUN_CHANNEL
    wid, fid = _open_sequence_widget(page, base_url)
    _set_sequence(admin_http, base_url, fid, False)
    _force(admin_http, base_url, out, ch, 'off')
    assert _wait_channel(output_states, out, ch, 'off', 20) == 'off'

    try:
        with page.expect_response(lambda r: '/sequence_func_activate_toggle/' in r.url,
                                  timeout=60000) as toggled:
            _flip_widget_switch(page, wid)
        assert toggled.value.status == 200, (
            f'위젯의 켜기가 HTTP {toggled.value.status}: {toggled.value.text()[:200]}')

        # 데몬의 사실 — 단계의 출력이 켜진다
        seen = _wait_channel(output_states, out, ch, 'on', STEP_START_S)
        assert seen == 'on', (
            f'시퀀스를 켰는데 {STEP_START_S}초 안에 단계의 출력이 켜지지 않았습니다'
            f"(데몬의 대답: {seen!r})")

        # 위젯이 받는 상태 — 데몬과 같은 말을 한다
        status = _sequence_status(admin_http, base_url, fid)
        step = next((s for s in status.get('steps', [])
                     if s.get('is_active')), None)
        assert status.get('is_activated') and status.get('status_code') == 'running', (
            f"데몬은 단계를 돌리는데 상태는 {status.get('status_code')!r} 입니다")
        assert step is not None, '데몬은 출력을 켰는데 상태에 진행 중인 단계가 없습니다'
        assert step.get('output_state') == 'on', (
            f"진행 중인 단계의 출력 상태가 {step.get('output_state')!r} — 데몬은 on")

        # 화면 — 그 단계 행이 진행 중으로 그려진다(위젯은 5초마다 새로 읽는다)
        row = page.locator(f'#seq-container-{wid} .seq-list-item[data-uid="{step["unique_id"]}"]')
        page.wait_for_function(
            """(sel) => { const el = document.querySelector(sel);
                          return !!el && el.classList.contains('active'); }""",
            arg=f'#seq-container-{wid} .seq-list-item[data-uid="{step["unique_id"]}"]',
            timeout=30000)
        assert row.count() == 1
    finally:
        _set_sequence(admin_http, base_url, fid, False)
        _force(admin_http, base_url, out, ch, 'off')


def test_c5_deactivating_a_sequence_turns_its_output_off(
        daemon, page, admin_http, base_url, output_states):
    out = _output_id(admin_http, base_url)
    ch = F.SEQUENCE_RUN_CHANNEL
    wid, fid = _open_sequence_widget(page, base_url)
    _force(admin_http, base_url, out, ch, 'off')
    _set_sequence(admin_http, base_url, fid, True)
    try:
        assert _wait_channel(output_states, out, ch, 'on', STEP_START_S) == 'on', (
            '시작 상태(단계가 도는 중)를 만들지 못했습니다')
        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector(f'#seq-main-toggle-{wid}', state='attached', timeout=20000)
        page.wait_for_function(
            f"() => document.getElementById('seq-main-toggle-{wid}').checked",
            timeout=20000)

        # 사람이 스위치를 끈다 — 단계가 한창 도는 중에
        with page.expect_response(lambda r: '/sequence_func_activate_toggle/' in r.url,
                                  timeout=60000) as toggled:
            _flip_widget_switch(page, wid)
        assert toggled.value.status == 200

        after = _wait_channel(output_states, out, ch, 'off', 20)
        assert after == 'off', (
            f"시퀀스를 껐는데 단계의 출력이 켜진 채입니다(데몬의 대답: {after!r}) — "
            f"끈 줄 알았던 밸브가 열려 있는 상태")
        status = _sequence_status(admin_http, base_url, fid)
        assert not status.get('is_activated'), '껐는데 시퀀스가 켜져 있다고 보고됩니다'

        # 그리고 **꺼진 채로 남는다** — 다음 사이클 경계를 넘겨도 다시 켜지지 않는다
        time.sleep(F.SEQUENCE_RUN_PERIOD_SEC / 2)
        assert _channel(output_states, out, ch) == 'off', '끈 시퀀스가 출력을 다시 켰습니다'
    finally:
        _set_sequence(admin_http, base_url, fid, False)
        _force(admin_http, base_url, out, ch, 'off')


# --------------------------------------------------------------------------
# C4 — 타이머가 도는 중에 웹 앱이 재시작되면
# --------------------------------------------------------------------------
TIMER_RUN_SEC = 40


def _timer_status(session, base_url, out, channel_id):
    resp = session.get(f'{base_url}/aot_timer_cycle_status_public/{out}/{channel_id}',
                       timeout=30)
    return resp.json() if resp.status_code == 200 and resp.text.strip() else {}


def _start_timer_then_restart_app(daemon, admin_http, base_url, output_states,
                                  payload=None):
    """타이머를 켜고(기본: TIMER_RUN_SEC 한 번), 도는 중에 웹 앱을 재시작한다."""
    from aot.tests.e2e import daemon as control

    out = _output_id(admin_http, base_url)
    channel_id = _channel_uuid(out)
    _force(admin_http, base_url, out, F.TIMER_CHANNEL, 'off')
    started = admin_http.post(
        f'{base_url}/aot_timer_cycle_start/{out}/{channel_id}', timeout=60,
        headers=csrf_headers(admin_http, base_url),
        json=payload or {'mode': 'simple', 'run_sec': TIMER_RUN_SEC})
    assert started.status_code == 200, f'타이머 시작이 HTTP {started.status_code}'
    t0 = time.time()
    assert _wait_channel(output_states, out, F.TIMER_CHANNEL, 'on', 20) == 'on', (
        '타이머가 출력을 켜지 못했습니다')

    def _up():
        return admin_http.get(f'{base_url}/outputstate', timeout=10,
                              headers={'Accept': 'application/json'}).status_code == 200
    assert control.restart_app(_up), '웹 앱이 재시작 뒤 응답하지 않습니다'
    reset_http_sessions()   # 재시작 전 연결은 죽었다 — 모든 세션의 풀을 비운다
    return out, channel_id, t0


def _channel_uuid(output_id):
    """채널 식별자 — 컨테이너의 DB 에서 읽는다(화면이 이 값을 노출하지 않는다)."""
    import subprocess
    from aot.tests.e2e.daemon import COMPOSE_FILE
    code = ("import sqlite3; from aot.config import SQL_DATABASE_AOT as p; "
            "c = sqlite3.connect(p); "
            f"print(c.execute('select unique_id from output_channel where output_id=? "
            f"and channel=?', ('{output_id}', {F.TIMER_CHANNEL})).fetchone()[0])")
    out = subprocess.run(['docker', 'compose', '-f', COMPOSE_FILE, 'exec', '-T',
                          'aot-app', 'python', '-c', code],
                         check=True, capture_output=True, text=True, timeout=60)
    return out.stdout.strip().splitlines()[-1]


def test_c4_a_timed_run_still_ends_across_an_app_restart(
        daemon, admin_http, base_url, output_states):
    """출력은 제시간에 꺼진다 — 켤 때 기간을 데몬에 실어 보내므로 앱이 죽어도."""
    out, channel_id, t0 = _start_timer_then_restart_app(
        daemon, admin_http, base_url, output_states)
    try:
        remaining = TIMER_RUN_SEC - (time.time() - t0)
        after = _wait_channel(output_states, out, F.TIMER_CHANNEL, 'off',
                              max(5, remaining) + 20)
        assert after == 'off', (
            f'{TIMER_RUN_SEC}초 타이머가 앱 재시작 뒤 끝나지 않았습니다 — 출력이 '
            f'켜진 채입니다({after!r})')
        # 재시작 뒤에도 로그인 세션이 산다 — 뒤따르는 검사들이 같은 세션을 쓴다
        assert '/login' not in admin_http.get(f'{base_url}/output', timeout=30).url
    finally:
        admin_http.post(f'{base_url}/aot_timer_cycle_stop/{out}/{channel_id}', timeout=60,
                        headers=csrf_headers(admin_http, base_url))
        _force(admin_http, base_url, out, F.TIMER_CHANNEL, 'off')


def test_c4_after_an_app_restart_the_timer_does_not_claim_to_run(
        daemon, admin_http, base_url, output_states):
    """끝난 타이머가 "진행 중" 으로 남으면 사람은 그것을 믿는다.

    2026-09-18 까지 그랬다 — 재시작 뒤 복구가 시작 전 예약만 다시 걸어, 도는 중이던
    타이머는 스레드와 함께 사라지고 상태가 running 으로 굳었다.
    """
    out, channel_id, t0 = _start_timer_then_restart_app(
        daemon, admin_http, base_url, output_states)
    try:
        while time.time() - t0 < TIMER_RUN_SEC + 15:
            time.sleep(2)
        status = _timer_status(admin_http, base_url, out, channel_id)
        assert _channel(output_states, out, F.TIMER_CHANNEL) == 'off'
        assert not status.get('active') and status.get('phase') != 'running', (
            f"타이머가 끝난 지 15초가 지났는데 상태는 {status.get('phase')!r}"
            f"(active={status.get('active')}) 입니다 — 재시작으로 사라진 작업을 "
            f"아직 돌고 있다고 보고합니다")
    finally:
        admin_http.post(f'{base_url}/aot_timer_cycle_stop/{out}/{channel_id}', timeout=60,
                        headers=csrf_headers(admin_http, base_url))
        _force(admin_http, base_url, out, F.TIMER_CHANNEL, 'off')


CYCLE_RUN_SEC, CYCLE_REST_SEC, CYCLES = 20, 15, 2


def test_c4_a_cycle_timer_picks_up_its_remaining_cycles_after_a_restart(
        daemon, admin_http, base_url, output_states):
    """반복 타이머는 재시작 뒤 **남은 주기를 이어 돈다** — 누가 화면을 열지 않아도.

    20초 켜짐 · 15초 쉼 · 2주기를 첫 켜짐 도중에 재시작한다. 그 뒤로는 타이머 상태를
    조회하지 않는다(예전에는 상태 조회가 들어와야 복구가 돌았다 — 밤 관수처럼 아무도
    보지 않으면 다시 걸리지 않았다). 2주기가 제 시각에 켜지면 앱이 스스로 이은 것이다.
    """
    out, channel_id, t0 = _start_timer_then_restart_app(
        daemon, admin_http, base_url, output_states,
        payload={'mode': 'cycle', 'run_sec': CYCLE_RUN_SEC,
                 'rest_sec': CYCLE_REST_SEC, 'cycles': CYCLES})
    ch = F.TIMER_CHANNEL
    try:
        # 1주기 켜짐이 끝나면 꺼지고(데몬이 기간으로 끈다),
        first_end = CYCLE_RUN_SEC - (time.time() - t0)
        assert _wait_channel(output_states, out, ch, 'off', max(5, first_end) + 15) == 'off', (
            '1주기 켜짐이 끝나지 않았습니다')
        # 쉼이 지나면 2주기가 **다시 켜진다** — 이어서 돌고 있다는 증거
        second_start = CYCLE_RUN_SEC + CYCLE_REST_SEC - (time.time() - t0)
        again = _wait_channel(output_states, out, ch, 'on', max(5, second_start) + 25)
        assert again == 'on', (
            f'재시작 뒤 2주기가 켜지지 않았습니다({again!r}) — 남은 주기가 사라졌습니다')
        # 2주기가 끝나면 꺼지고, 상태는 완료다
        total = CYCLES * CYCLE_RUN_SEC + (CYCLES - 1) * CYCLE_REST_SEC
        assert _wait_channel(output_states, out, ch, 'off',
                             max(5, total - (time.time() - t0)) + 20) == 'off'
        # 작업 스레드는 마지막 주기 뒤에도 쉼을 한 번 거친 다음 '완료' 로 적는다.
        deadline = time.time() + CYCLE_REST_SEC + 20
        status = {}
        while time.time() < deadline:
            status = _timer_status(admin_http, base_url, out, channel_id)
            if status.get('phase') == 'completed':
                break
            time.sleep(2)
        assert status.get('phase') == 'completed' and not status.get('active'), (
            f"모든 주기가 끝났는데 상태가 {status.get('phase')!r} 입니다")
        assert status.get('completed_cycles') == CYCLES
    finally:
        admin_http.post(f'{base_url}/aot_timer_cycle_stop/{out}/{channel_id}', timeout=60,
                        headers=csrf_headers(admin_http, base_url))
        _force(admin_http, base_url, out, ch, 'off')
