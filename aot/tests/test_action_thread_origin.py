# coding=utf-8
"""액션이 백그라운드 스레드로 넘기는 장치 명령도 **출처를 밝히는가**.

## 왜 이 테스트가 있나

액션 모듈들은 명령을 `threading.Thread(target=self.control.output_on_off, ...)`
로 넘긴다. 실행 컨텍스트는 thread-local 이라 그 경계를 넘지 못한다. 그래서
컨트롤러가 `set_execution_context(SOURCE_SEQUENCE, ...)` 를 심어도 명령이
실제로 나가는 자식 스레드에서는 비어 있고, `resolve_origin()` 이 데몬 프로세스
판정으로 떨어져 `automation` 이 된다 — 그 타입은 `AUDITED_TYPES` 에 없으므로
감사 기록이 통째로 사라진다.

실측(2026-08-30 로컬 감사로그): 시퀀스의 OFF 는 컨트롤러가 직접 보내
`origin=sequence` 로 91건 남았는데, 같은 시퀀스의 ON 은 이 스레드를 타서
**한 건도** 남지 않았다. 밸브를 끈 기록만 있고 켠 기록이 없는 상태다.
"""
import threading
from unittest.mock import MagicMock

import pytest

from aot.utils.command_origin import TYPE_SEQUENCE, should_audit
from aot.utils.execution_context import (clear_execution_context, get_context,
                                         run_in_thread, set_execution_context)


@pytest.fixture(autouse=True)
def _clean_context():
    clear_execution_context()
    yield
    clear_execution_context()


def _capture():
    """자식 스레드가 본 컨텍스트를 담아 돌려주는 (target, box)."""
    box = {}
    done = threading.Event()

    def target(*args, **kwargs):
        box['ctx'] = get_context()
        box['args'] = args
        box['kwargs'] = kwargs
        done.set()

    return target, box, done


def test_context_crosses_the_thread_boundary():
    target, box, done = _capture()
    set_execution_context(TYPE_SEQUENCE, source_id='seq-1')
    run_in_thread(target, args=('out-1', 'on'), kwargs={'amount': 300})
    assert done.wait(5)

    assert box['ctx']['source_type'] == TYPE_SEQUENCE
    assert box['ctx']['source_id'] == 'seq-1'
    assert box['args'] == ('out-1', 'on')
    assert box['kwargs'] == {'amount': 300}


def test_captured_origin_survives_the_callers_clear():
    """호출자는 `finally: clear_execution_context()` 로 곧장 컨텍스트를 지운다.

    자식이 그때 가서 읽으면 이미 비어 있다 — 그래서 컨텍스트는 스레드를 만들기
    전에 호출자 스레드에서 캡처해야 한다.
    """
    started = threading.Event()
    target, box, done = _capture()

    def slow_target(*args, **kwargs):
        started.wait(5)          # 호출자가 clear 를 지나갈 때까지 기다린다
        target(*args, **kwargs)

    set_execution_context(TYPE_SEQUENCE, source_id='seq-1')
    try:
        run_in_thread(slow_target)
    finally:
        clear_execution_context()
    started.set()
    assert done.wait(5)

    assert box['ctx']['source_type'] == TYPE_SEQUENCE


def test_origin_from_this_thread_would_be_audited():
    """자식이 본 출처가 감사 대상이어야 기록이 남는다."""
    target, box, done = _capture()
    set_execution_context(TYPE_SEQUENCE, source_id='seq-1')
    run_in_thread(target)
    assert done.wait(5)
    assert should_audit({'type': box['ctx']['source_type']})


def test_child_context_does_not_leak_into_the_caller():
    target, _box, done = _capture()
    run_in_thread(target)
    assert done.wait(5)
    assert not get_context().get('source_type')


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_failed_command_does_not_disturb_the_caller():
    """Pyro5 타임아웃 등으로 명령이 터져도 호출자 스레드는 그대로여야 한다.

    자식의 컨텍스트 정리(`_run` 의 finally)가 호출자를 건드리면, 컨트롤러가
    다음에 보내는 명령이 출처를 잃는다.
    """
    def boom():
        raise RuntimeError("Pyro5 timeout")

    set_execution_context(TYPE_SEQUENCE, source_id='seq-1')
    thread = run_in_thread(boom)
    thread.join(5)

    assert not thread.is_alive()
    assert get_context()['source_type'] == TYPE_SEQUENCE


def test_no_context_set_is_not_an_error():
    target, box, done = _capture()
    run_in_thread(target, args=(1,))
    assert done.wait(5)
    assert box['ctx']['source_type'] is None


# ---- 액션 모듈이 실제로 이 경로를 쓰는가 ----
#
# 여기서 raw `threading.Thread` 로 되돌아가면 위 성질이 전부 무의미해진다.

OUTPUT_ACTIONS = [
    'output_on_off',
    'output_pwm',
    'output_value',
    'output_volume',
    'output_ramp_pwm',
    'output_actuator_paired',
]


@pytest.mark.parametrize('module_name', OUTPUT_ACTIONS)
def test_output_actions_dispatch_with_context(module_name):
    import pathlib
    path = pathlib.Path(__file__).parent.parent / 'actions' / f'{module_name}.py'
    source = path.read_text()
    assert 'run_in_thread' in source, f"{module_name}: 출처가 스레드를 못 넘는다"
    assert 'threading.Thread' not in source, (
        f"{module_name}: raw 스레드로 되돌아갔다 — 감사에서 명령이 사라진다")
