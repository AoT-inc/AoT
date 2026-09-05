# coding=utf-8
"""타이머가 **끄는 데 실패했을 때 그것을 알아채는가**.

## 왜 이 테스트가 있나

타이머 위젯(`aot/widgets/AoT_timer.py`)과 타이머 트리거 컨트롤러
(`aot/controllers/controller_trigger.py`)에는 **테스트가 한 건도 없었다.**
그 사이 타이머 수정 커밋이 다섯 건 들어갔고(예약 워커·토글 깜빡임·전체 시간
표시), 어느 것도 회귀로 고정되지 않았다.

고친 것은 셋이다.

**① 끄는 명령의 결과를 아무도 안 봤다.** ON 은 3회 재시도가 있었는데 OFF 는
한 번 쏘고 반환값을 버렸고, 정지 핸들러는 그 결과와 무관하게 화면에 "User
stopped" 를 썼다. 원격 출력이 느리거나 두절이면 **화면은 정지인데 밸브는
열린 채**다 — 이 프로젝트가 이미 운영 사고로 겪은 모양이다.

⚠ 재시도 헬퍼에 `stop_event` 를 넘기면 안 된다. 그것이 서 있으면 즉시
`cancelled` 로 돌아오는데, OFF 를 보내는 자리는 거의 언제나 정지 중이라
**끄는 명령만 골라서 재시도가 사라진다.**

**② PWM 듀티 명령의 반환값을 안 봤다**(`set_output_duty_cycle`). 명령이 못
나가도 설정점 곡선만 조용히 진행해, 화면의 설정점과 실제 출력이 갈린다.

**③ `get_method_output` 이 `None` 을 돌려줄 수 있는데 호출부가 튜플로 풀었다.**
`TypeError` 가 `timer_period` 갱신 **전**에 나므로 루프가 매 주기 같은 예외를
되풀이한다(로그 폭주 + 헛도는 루프).

`(code, msg)` 규약에서 **튜플이 아닌 반환은 성공**이다 — 반환값이 없는
드라이버가 정상이고 감사 계층(`controller_output.output_on_off`)도 같은 규약을
쓴다. 그것을 실패로 바꾸면 멀쩡한 명령이 전부 실패로 보고된다.
"""
import ast
import inspect
import pathlib
from unittest.mock import MagicMock

import pytest

TIMER_SRC = (pathlib.Path(__file__).parent.parent
             / 'widgets' / 'AoT_timer.py').read_text()


# ---- ① OFF 는 검사하고 재시도한다 ----

def test_off_helper_retries_and_reports():
    """OFF 전용 헬퍼가 재시도 경로를 쓰고 실패를 돌려주는가."""
    import aot.widgets.AoT_timer as timer

    calls = []

    def fake_on_off(dev, state, output_type=None, amount=0.0, output_channel=None,
                    additional_options=None):
        calls.append(state)
        return 1, 'output offline'          # 계속 실패

    daemon = MagicMock()
    daemon.output_on_off = fake_on_off

    ok, err = timer._issue_output_off(daemon, 'dev-1', 0, why='test')

    assert ok is False
    assert err == 'output offline'
    assert calls == ['off', 'off', 'off'], f'재시도가 3회가 아니다: {calls}'


def test_off_helper_reports_success_when_it_goes_through():
    import aot.widgets.AoT_timer as timer

    daemon = MagicMock()
    daemon.output_on_off = MagicMock(return_value=(0, 'ok'))
    ok, err = timer._issue_output_off(daemon, 'dev-1', 0)
    assert ok is True and err is None


def test_a_driver_that_returns_nothing_still_counts_as_success():
    """`(code,msg)` 를 안 돌려주는 드라이버가 정상이다 — 실패로 보면
    멀쩡한 명령이 전부 실패로 보고된다."""
    import aot.widgets.AoT_timer as timer

    daemon = MagicMock()
    daemon.output_on_off = MagicMock(return_value=None)
    ok, _ = timer._issue_output_off(daemon, 'dev-1', 0)
    assert ok is True


def test_the_off_path_never_passes_the_stop_event():
    """정지 중에는 stop_event 가 서 있다 — 넘기면 OFF 재시도가 통째로 사라진다."""
    src = inspect.getsource(
        __import__('aot.widgets.AoT_timer', fromlist=['x'])._issue_output_off)
    assert 'stop_event=None' in src, (
        'OFF 재시도에 stop_event 를 넘기면 정지 중에는 한 번도 재시도하지 않는다')


# ---- ① 정지 핸들러가 결과를 화면에 정직하게 쓴다 ----

def _stop_worker_src():
    src = TIMER_SRC
    start = src.index('def _cyc_stop_worker(')
    return src[start:src.index('\ndef ', start + 10)]


def test_stop_switches_off_before_it_writes_the_screen():
    """예전에는 화면을 먼저 쓰고 껐다 — 실패해도 '정지' 라고 적혔다."""
    body = _stop_worker_src()
    i_off = body.index('_force_output_off')
    i_msg = body.index("'User stopped'")
    assert i_off < i_msg, (
        'OFF 결과를 보기 전에 화면을 쓴다 — 못 껐는데 정지라고 보고하게 된다')


def test_stop_reports_an_error_when_the_off_failed():
    body = _stop_worker_src()
    assert "phase='error'" in body, '끄지 못한 경우를 화면에 알리지 않는다'
    assert 'OFF Failed' in body


def test_every_off_call_in_the_worker_goes_through_the_checked_helper():
    """워커 안 OFF 가 하나라도 옛 미검사 호출로 남으면 그 경로만 조용해진다."""
    assert "_issue_output_command(daemon, device_unique_id, channel_index, 'off'" \
        not in TIMER_SRC, '검사하지 않는 OFF 호출이 남아 있다'
    assert TIMER_SRC.count('_issue_output_off(daemon') >= 3


# ---- ② PWM 듀티 명령의 결과를 본다 ----

def test_set_output_duty_cycle_reports_a_refused_command():
    import aot.controllers.controller_trigger as tc

    inst = object.__new__(tc.TriggerController)
    inst.logger = MagicMock()
    inst.trigger = MagicMock(unique_id_2='out-1', unique_id_3=None)
    inst.control = MagicMock()
    inst.control.output_on = MagicMock(return_value=(1, 'timed out'))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tc, 'db_retrieve_table_daemon', lambda *a, **kw: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
        assert inst.set_output_duty_cycle(50) is False

    assert inst.logger.error.called, '거부된 PWM 명령이 아무 데도 안 남는다'


def test_set_output_duty_cycle_accepts_a_driver_without_a_return():
    import aot.controllers.controller_trigger as tc

    inst = object.__new__(tc.TriggerController)
    inst.logger = MagicMock()
    inst.trigger = MagicMock(unique_id_2='out-1', unique_id_3=None)
    inst.control = MagicMock()
    inst.control.output_on = MagicMock(return_value=None)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tc, 'db_retrieve_table_daemon', lambda *a, **kw: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))
        assert inst.set_output_duty_cycle(50) is True

    assert not inst.logger.error.called


# ---- ③ 메서드가 값을 못 내도 루프가 헛돌지 않는다 ----

def test_get_method_output_always_returns_a_pair():
    """맨 `return`(=None) 이면 호출부의 튜플 언패킹이 터진다."""
    import aot.controllers.controller_trigger as tc

    inst = object.__new__(tc.TriggerController)
    inst.unique_id = 'trig-1'
    inst.logger = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tc, 'db_retrieve_table_daemon',
                   lambda *a, **kw: MagicMock(method_start_time=None))
        result = inst.get_method_output('method-1')

    assert isinstance(result, tuple) and len(result) == 2
    setpoint, ended = result          # 여기서 터지면 옛 버그가 살아난 것이다
    assert setpoint is None and ended is False


def test_the_loop_skips_the_output_when_there_is_no_setpoint():
    """`amount=None` 으로 출력 명령이 나가면 안 된다."""
    src = inspect.getsource(
        __import__('aot.controllers.controller_trigger', fromlist=['x'])
        .TriggerController.loop)
    i_period = src.index('self.timer_period += self.trigger.period')
    i_guard = src.index('if pwm_duty_cycle is None:')
    assert i_period < i_guard, (
        '설정점 판정이 timer_period 갱신보다 앞이면, 예외가 날 때 루프가 '
        '같은 주기를 되풀이한다')
    assert 'else:' in src[i_guard:], '설정점이 있을 때 출력을 건드리지 않는다'


# ---- ④ refresh 중 loop() 재진입 교착 ----
#
# `initialize_variables` 는 기동 때만 도는 게 아니라 `refresh_settings()` 를
# 통해서도 도는데, 그쪽은 `pause_loop=True` 를 걸어 둔 채 부른다. 그 상태에서
# `initialize_variables` 가 `self.loop()` 를 다시 부르면, 재진입한 loop 는
# `while self.pause_loop` 에서 park 하고 그 플래그를 풀 코드는 자기를 기다리는
# refresh_settings 하나뿐이라 서로 영원히 기다린다. 실증으로 확인했다
# (2026-09-05): 3초 안에 반환하지 않았다.

def test_initialize_variables_never_re_enters_the_loop():
    """이 한 줄이 되살아나면 설정 저장이 그 트리거를 영영 멈춘다.

    ⚠ 문자열로 검사하면 **"부르지 말 것" 이라고 적은 주석까지 호출로 센다**
    (실제로 그렇게 한 번 걸렸다). 그러면 왜 부르면 안 되는지를 설명하는 것이
    금지되어, 다음 사람이 이유를 모른 채 되살리게 된다. AST 로 진짜 호출만 본다.
    """
    import textwrap

    src = textwrap.dedent(inspect.getsource(
        __import__('aot.controllers.controller_trigger', fromlist=['x'])
        .TriggerController.initialize_variables))
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and n.func.attr == 'loop'
        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'self'
    ]
    assert not calls, (
        'initialize_variables 가 loop() 를 다시 부른다 — refresh_settings 가 '
        'pause_loop 를 건 채 부르므로 교착이다')


def test_actions_at_start_still_fires_on_the_next_pass():
    """직접 호출을 뺀 대신 기준점을 뒤로 눕혀 다음 loop 에서 발화해야 한다."""
    src = inspect.getsource(
        __import__('aot.controllers.controller_trigger', fromlist=['x'])
        .TriggerController.initialize_variables)
    assert 'self.timer_period = now - self.trigger.period' in src, (
        '기준점을 눕히지 않으면 「시작 시 동작」이 통째로 사라진다')


def test_refresh_settings_always_releases_the_pause():
    """`initialize_variables()` 가 터져도 pause_loop 를 풀어야 한다 —
    안 풀면 메인 루프가 park 한 채 트리거가 조용히 죽는다."""
    import aot.controllers.controller_trigger as tc

    inst = object.__new__(tc.TriggerController)
    inst.logger = MagicMock()
    inst.pause_loop = False
    inst.verify_pause_loop = True          # 즉시 통과
    inst.initialize_variables = MagicMock(side_effect=RuntimeError('db gone'))

    with pytest.raises(RuntimeError):
        inst.refresh_settings()

    assert inst.pause_loop is False, 'pause_loop 가 True 로 남아 트리거가 멈춘다'


def test_refresh_settings_does_not_wait_forever_for_the_ack():
    """확인은 loop() 안에서만 세워진다 — 스레드가 죽었으면 영영 안 온다."""
    import aot.controllers.controller_trigger as tc

    inst = object.__new__(tc.TriggerController)
    inst.logger = MagicMock()
    inst.pause_loop = False
    inst.verify_pause_loop = False         # 아무도 확인해 주지 않는다
    inst.initialize_variables = MagicMock()
    inst.PAUSE_ACK_TIMEOUT_S = 0.3

    import time as _t
    t0 = _t.time()
    inst.refresh_settings()
    assert _t.time() - t0 < 5.0, '확인을 무한정 기다린다'
    assert inst.initialize_variables.called, '기다리다 포기했으면 설정은 읽어야 한다'
    assert inst.logger.error.called, '기다리지 못한 사실이 아무 데도 안 남는다'
