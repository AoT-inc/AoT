# coding=utf-8
"""L3 — 제어 폐루프.

여기서만 **데몬이 필요하다**. L0~L2 는 "화면이 옳은가" 를 보지만, 이 층은
"누른 것이 실제로 장치까지 갔는가, 그리고 그 결과가 정직하게 돌아오는가" 를
본다. 겨냥하는 사고는 이 저장소에서 가장 위험한 계열이다:

  * `execute_action` 이 status 를 검사하지 않아 **제어 실패를 성공으로 보고**하던 것
  * 위젯이 미인증 경로로 새던 것

화면이 "켰습니다" 라고 말하는데 장치는 꺼져 있는 상태는, 사람이 그것을 믿고
다음 판단을 하기 때문에 조용한 오작동보다 나쁘다.

대상은 시드가 만든 **가상 출력**뿐이다. 실장비를 건드리지 않는다.
"""
import time

import pytest

from aot.tests.e2e import fixtures as F

pytestmark = pytest.mark.e2e

# 데몬이 명령을 처리하고 상태에 반영되기까지 주는 시간.
SETTLE_S = 3.0


def _card(page, name):
    return page.locator('.grid-stack-item', has_text=name).first


def _press(page, name, action):
    """출력 카드의 첫 채널 On/Off 를 누른다(사람이 누르는 그 버튼)."""
    selector = '.aot-btn-on' if action == 'on' else '.aot-btn-off'
    _card(page, name).locator(selector).first.click()


def _open_output_page(page, base_url):
    page.goto(f'{base_url}/output', wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1500)


def _daemon_answers(output_states, output_id):
    """지금 데몬이 말이 되는가 — 그 출력의 상태가 돌아오면 참.

    컨테이너가 떴는지도, 로그가 무어라 했는지도 보지 않는다. 앱이 데몬에게
    물어서 답을 받아 오는 것만이 "제어를 보낼 수 있다" 는 뜻이다.
    """
    try:
        return bool(output_states().get(output_id))
    except Exception:                        # noqa: BLE001
        return False


def _channel_state(output_states, output_id, channel='0'):
    """`/outputstate` 응답에서 채널 상태 하나를 꺼낸다."""
    return (output_states().get(output_id) or {}).get(channel)


def _wait_for_state(output_states, output_id, expected, timeout_s=25,
                    channel='0'):
    """상태가 기대한 값이 될 때까지 기다린다.

    고정 sleep 으로 충분하지 않은 구간이 있다 — **데몬을 되살린 직후**가
    그렇다. 데몬 로그가 "started" 라고 말해도 출력 상태가 앱까지 돌아오는 데는
    더 걸려서, 곧바로 읽으면 빈 응답이 온다. 그 사이를 실패로 세면 검사가
    거짓 경보를 내고, 반대로 무시하면 진짜 고장을 놓친다.

    돌려주는 것은 **마지막으로 본 값**이다 — 단언 메시지에 그대로 쓴다.
    """
    deadline = time.time() + timeout_s
    seen = None
    while time.time() < deadline:
        seen = _channel_state(output_states, output_id, channel)
        if seen == expected:
            return seen
        time.sleep(1.0)
    return seen


def _output_id_from_screen(page, name):
    """출력 id 를 **화면에서** 얻는다.

    On 버튼의 `name` 이 `<출력id>/<채널>/on/sec/0` 이다. 별도 API 를 부르지
    않는 편이 낫다 — 화면이 실제로 다루는 그 id 를 쓰게 되고, 검사가 API
    스키마 변경에 흔들리지 않는다.
    """
    value = page.evaluate("""(name) => {
        const card = Array.from(document.querySelectorAll('.grid-stack-item'))
            .find(el => (el.innerText || '').includes(name));
        if (!card) return null;
        const btn = card.querySelector('.aot-btn-on');
        return btn ? btn.getAttribute('name') : null;
    }""", name)
    assert value, f'출력 카드나 켜기 버튼을 찾지 못했습니다: {name}'
    return value.split('/')[0]


def test_pressing_on_actually_turns_it_on(daemon, page, base_url,
                                          output_states):
    """C1 — 켜면 데몬이 켜졌다고 말하고, 끄면 꺼졌다고 말한다.

    화면 표시가 아니라 `/outputstate`(데몬의 대답)를 본다. 둘이 갈리는 것이
    바로 이 검사가 찾는 사고다.
    """
    _open_output_page(page, base_url)
    multi_output_id = _output_id_from_screen(page, F.OUTPUT_MULTI)

    # 어느 상태에서 시작하든 같은 자리에서 출발한다.
    _press(page, F.OUTPUT_MULTI, 'off')
    assert _wait_for_state(output_states, multi_output_id, 'off') == 'off', (
        '시작 상태를 off 로 만들지 못했습니다')

    _press(page, F.OUTPUT_MULTI, 'on')
    after_on = _wait_for_state(output_states, multi_output_id, 'on')
    assert after_on == 'on', (
        f"켜기를 눌렀는데 데몬은 '{after_on}' 라고 답합니다 — 명령이 장치까지 "
        f"가지 않았거나, 갔는데 상태가 돌아오지 않습니다")

    _press(page, F.OUTPUT_MULTI, 'off')
    after_off = _wait_for_state(output_states, multi_output_id, 'off')
    assert after_off == 'off', (
        f"끄기를 눌렀는데 데몬은 '{after_off}' 라고 답합니다")


def test_the_other_channels_are_left_alone(daemon, page, base_url,
                                           output_states):
    """C1-2 — 한 채널을 켜도 옆 채널은 그대로다.

    다채널 출력에서 채널 하나를 켰는데 이웃까지 움직이면, 화면에서는
    "켰다" 만 보이고 **엉뚱한 장치가 같이 돈다.** 밸브·펌프에서는 사고다.
    """
    _open_output_page(page, base_url)
    multi_output_id = _output_id_from_screen(page, F.OUTPUT_MULTI)
    _press(page, F.OUTPUT_MULTI, 'off')
    time.sleep(SETTLE_S)

    before = output_states().get(multi_output_id) or {}
    others_before = {ch: st for ch, st in before.items() if ch != '0'}

    _press(page, F.OUTPUT_MULTI, 'on')
    time.sleep(SETTLE_S)
    after = output_states().get(multi_output_id) or {}
    others_after = {ch: st for ch, st in after.items() if ch != '0'}

    assert others_after == others_before, (
        f'채널 0 만 켰는데 다른 채널이 움직였습니다: '
        f'{others_before} → {others_after}')

    _press(page, F.OUTPUT_MULTI, 'off')
    time.sleep(SETTLE_S)


def test_a_control_failure_is_reported_not_swallowed(daemon, page, base_url,
                                                     output_states):
    """C2 — 제어가 실패하면 화면이 **실패라고 말해야** 한다.

    이 저장소에서 가장 위험한 사고 계열이다. 실패를 성공으로 보고하면 사람은
    그것을 믿고 다음 판단을 한다 — "환기를 켰으니 괜찮겠지" 하고 자리를 뜬다.

    실패는 데몬을 잠시 내려 만든다. 가짜 오류를 주입하는 것보다 현실적이다
    (데몬이 죽어 있는 동안 사람이 버튼을 누르는 것은 실제로 일어나는 일이다).
    끝나면 반드시 되살린다.
    """
    _open_output_page(page, base_url)
    multi_output_id = _output_id_from_screen(page, F.OUTPUT_MULTI)
    _press(page, F.OUTPUT_MULTI, 'off')
    time.sleep(SETTLE_S)

    daemon.stop()
    try:
        page.reload(wait_until='domcontentloaded')
        page.wait_for_selector('.grid-stack-item', timeout=25000)
        page.wait_for_timeout(1500)

        _press(page, F.OUTPUT_MULTI, 'on')
        page.wait_for_timeout(6000)

        # 1) 화면이 성공이라고 말하면 안 된다.
        notices = page.evaluate("""() => Array.from(
            document.querySelectorAll('.toast, #toast-container div, .alert'))
            .map(e => (e.innerText || '').trim()).filter(Boolean)""")
        said_success = [n for n in notices if 'SUCCESS' in n.upper()]
        assert not said_success, (
            f'데몬이 없는데 화면이 성공이라고 말합니다 — 실패를 삼켰습니다: '
            f'{said_success[:2]}')

        # 2) 그리고 무언가 잘못됐다고 **말은 해야** 한다. 아무 말도 없으면
        #    사람은 눌린 줄 알고 넘어간다.
        assert notices, (
            '데몬이 없는데 화면에 아무 안내도 없습니다 — 눌러도 아무 일이 '
            '없었다는 것을 사람이 알 길이 없습니다')
    finally:
        revived_ok = daemon.start(
            lambda: _daemon_answers(output_states, multi_output_id))
        assert revived_ok, '데몬을 되살리지 못했습니다'

    # 되살아난 뒤에는 다시 정상으로 제어돼야 한다(데몬 재시작이 제어 경로를
    # 망가뜨리지 않는지까지 본다).
    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('.grid-stack-item', timeout=25000)
    page.wait_for_timeout(1500)
    _press(page, F.OUTPUT_MULTI, 'on')
    revived = _wait_for_state(output_states, multi_output_id, 'on', timeout_s=40)
    assert revived == 'on', (
        f"데몬을 되살린 뒤에도 제어가 닿지 않습니다(데몬의 대답: {revived!r})")

    _press(page, F.OUTPUT_MULTI, 'off')
    _wait_for_state(output_states, multi_output_id, 'off')
