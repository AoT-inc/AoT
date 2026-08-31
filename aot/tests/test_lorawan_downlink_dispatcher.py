# coding=utf-8
"""전송 대기가 **호출 스레드를 붙잡지 않는가**, 그리고 재시도가 큐를 부풀리지 않는가.

## 왜 이 테스트가 있나

출력 제어는 Pyro5 RPC 로 들어오고 그 왕복 예산은 8초다(하드캡 10초).
그런데 예전 `_enqueue_raw` 는 `pace_send()` 로 사이트 슬롯을 **동기로** 기다린
뒤 전송까지 마치고 돌아왔다. 페이싱 간격이 4초이므로 동시에 들어온 세 번째
명령부터 대기가 8초에 닿는다 — **밸브 셋을 함께 조작하는 순간부터** 호출자가
타임아웃을 본다.

Pyro5 는 클라이언트가 포기해도 데몬 스레드를 멈추지 않으므로 명령은 결국
나갔다. 호출자만 실패로 읽고 재시도했고, 그 재시도가 슬롯을 새로 예약해 뒤에
선 모두의 대기를 늘렸다 — 실패 판정이 진짜 실패를 만드는 되먹임이다.

실측(aot-004, 2026-08-31): 관수 스텝 전환 시각에만 `Output OFF timed out` 23건이
몰렸고, 그 시각 밸브들의 개방 시간은 정상 기록돼 있었다. 즉 꺼졌는데 실패로
보고된 것이다.
"""
import threading
import time

import pytest

from aot.utils import lorawan_pacing as lp


@pytest.fixture(autouse=True)
def _clean_queue(monkeypatch):
    # 실제 간격(4초)으로 돌리면 한 테스트가 워커를 몇 분씩 붙잡아 뒤 테스트가
    # 그 잔여 대기를 물려받는다. 간격 자체를 검증하는 테스트는 자기 값을 쓴다.
    monkeypatch.setattr(lp, 'MIN_GLOBAL_DOWNLINK_INTERVAL_S', 0.02)
    lp._reset_for_test()
    yield
    lp._reset_for_test()


def test_submitting_does_not_block_the_caller():
    """핵심 회귀. 여러 건을 넣어도 호출자는 즉시 돌아와야 한다.

    옛 구현이라면 세 번째 호출에서 이미 8초를 잤다.
    """
    sent = []
    started = time.time()
    for i in range(8):
        assert lp.submit_downlink(f'k{i}', lambda i=i: sent.append(i)) is True
    elapsed = time.time() - started

    # RPC 예산(8초)은커녕 한 슬롯(4초)에도 한참 못 미쳐야 한다.
    assert elapsed < 1.0, f"접수가 {elapsed:.1f}초를 잡아먹었다 — 동기 대기가 남아 있다"


def test_the_same_target_is_replaced_not_queued_twice():
    """의도 큐다 — 밸브에게 의미 있는 것은 마지막 명령 하나뿐이다."""
    lp.submit_downlink(('out', 0, 'ctrl'), lambda: None, label='on')
    lp.submit_downlink(('out', 0, 'ctrl'), lambda: None, label='off')
    lp.submit_downlink(('out', 0, 'ctrl'), lambda: None, label='on')
    assert lp.queue_depth() == 1


def test_the_replacement_keeps_its_place_in_line():
    """자리를 뒤로 미루면 먼저 온 명령이 계속 밀려 굶는다."""
    lp.submit_downlink('a', lambda: None)
    lp.submit_downlink('b', lambda: None)
    lp.submit_downlink('a', lambda: None)      # 갱신
    with lp._Q_LOCK:
        keys = [i['key'] for i in lp._QUEUE]
    assert keys == ['a', 'b']


def test_different_targets_queue_separately():
    lp.submit_downlink(('out', 0, 'ctrl'), lambda: None)
    lp.submit_downlink(('out', 1, 'ctrl'), lambda: None)
    lp.submit_downlink(('other', 0, 'ctrl'), lambda: None)
    assert lp.queue_depth() == 3


def test_config_commands_are_never_merged():
    """설정 명령은 내용이 제각각이라 덮어쓰면 조용히 유실된다."""
    lp.submit_downlink('cfg-1', lambda: None, merge=False)
    lp.submit_downlink('cfg-2', lambda: None, merge=False)
    lp.submit_downlink('cfg-3', lambda: None, merge=False)
    assert lp.queue_depth() == 3


def test_a_full_queue_refuses_instead_of_dropping_silently():
    """조용히 버리면 호출자는 성공으로 읽는다 — 그게 이 도메인의 최악이다."""
    for i in range(lp.MAX_QUEUE_DEPTH):
        assert lp.submit_downlink(f'k{i}', lambda: None, merge=False) is True
    assert lp.submit_downlink('overflow', lambda: None, merge=False) is False


def test_backlog_estimate_grows_with_the_queue():
    """확인 창을 이만큼 넓히지 않으면, 늦게 나간 명령은 창이 닫힌 뒤에 전파돼
    멀쩡한 장치가 통신 장애로 판정된다."""
    assert lp.backlog_seconds() == 0
    lp.submit_downlink('a', lambda: None)
    lp.submit_downlink('b', lambda: None)
    assert lp.backlog_seconds() == pytest.approx(2 * lp.MIN_GLOBAL_DOWNLINK_INTERVAL_S)


# ---- 워커: 실제로 내보내는가, 간격을 지키는가 ----

def test_worker_sends_and_respects_the_pacing_interval(monkeypatch):
    monkeypatch.setattr(lp, 'MIN_GLOBAL_DOWNLINK_INTERVAL_S', 0.2)
    stamps = []
    done = threading.Event()

    def mark(i):
        stamps.append(time.time())
        if len(stamps) == 3:
            done.set()

    for i in range(3):
        lp.submit_downlink(f'k{i}', lambda i=i: mark(i), merge=False)

    assert done.wait(10), "워커가 큐를 비우지 못했다"
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    for gap in gaps:
        assert gap >= 0.15, f"간격 {gap:.2f}초 — 페이싱이 지켜지지 않았다"


def test_a_failing_send_does_not_kill_the_worker():
    """한 건의 예외로 워커가 죽으면 그 뒤 모든 제어가 조용히 멈춘다."""
    done = threading.Event()

    def boom():
        raise RuntimeError("ChirpStack unreachable")

    lp.submit_downlink('bad', boom, merge=False)
    lp.submit_downlink('good', done.set, merge=False)

    assert done.wait(15), "예외 뒤 워커가 다음 명령을 처리하지 못했다"


def test_a_stale_command_is_dropped_not_sent_late(monkeypatch):
    """30초 기다린 밸브 명령은 이미 현재 의도가 아니다."""
    monkeypatch.setattr(lp, 'MAX_QUEUE_AGE_S', -1.0)   # 넣는 즉시 만료
    monkeypatch.setattr(lp, 'MIN_GLOBAL_DOWNLINK_INTERVAL_S', 0.05)
    sent = []
    lp.submit_downlink('stale', lambda: sent.append(1), merge=False)
    # 뒤따르는 정상 명령으로 워커가 앞의 것을 처리했음을 확인한다.
    done = threading.Event()
    monkeypatch.setattr(lp, 'MAX_QUEUE_AGE_S', 30.0)
    lp.submit_downlink('fresh', done.set, merge=False)

    assert done.wait(10)
    assert sent == [], "만료된 명령이 뒤늦게 전송됐다"


# ---- 드라이버가 실제로 이 경로를 쓰는가 ----
#
# 큐를 만들어 두고 드라이버가 예전처럼 동기로 기다리면 아무것도 나아지지 않는다.

def _driver_names():
    """드라이버가 **실제로 부르거나 가져오는** 이름만 모은다.

    문자열로 훑으면 주석에서 그 이름을 설명하는 것까지 걸린다 — 왜 그렇게
    고쳤는지 적어 둔 문장이 회귀로 잡히면 설명을 지우게 된다.
    """
    import ast
    import pathlib
    src = (pathlib.Path(__file__).parent.parent
           / 'outputs' / 'on_off_chirpstack.py').read_text()
    tree = ast.parse(src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.name)
    return names, src


def test_chirpstack_driver_does_not_block_on_pacing():
    names, _src = _driver_names()
    assert 'submit_downlink' in names, "드라이버가 디스패처를 쓰지 않는다"
    assert 'pace_send' not in names, (
        "드라이버가 다시 동기 페이싱으로 돌아갔다 — RPC 예산을 넘겨 "
        "밸브 셋부터 타임아웃이 재발한다")


def test_control_commands_carry_a_merge_key():
    """제어가 병합 키 없이 나가면 재시도가 큐를 부풀려 되먹임이 되살아난다."""
    _names, src = _driver_names()
    assert "merge_key=(self.unique_id, output_channel, 'ctrl')" in src


# ---- 확인 창은 큐 대기만큼 넓어져야 한다 ----

class _FakeConfirmable:
    """`ConfirmableOutputMixin` 의 창 계산만 떼어 본다."""

    def __init__(self, timeout=8.0):
        from aot.outputs.confirmable_output import ConfirmableOutputMixin
        self.__class__ = type('F', (ConfirmableOutputMixin,), dict(self.__class__.__dict__))
        self._timeout = timeout
        self.output_states = {0: False}
        self.unique_id = 'fake'
        self._confirm_init()

    def command_timeout_s(self, output_channel=0):
        return self._timeout

    def confirmation_capable(self):
        return True

    def resend_interval_floor_s(self):
        return 4.0

    def _arm_confirm_timer(self, *a, **kw):
        pass          # 타이머는 이 테스트의 관심사가 아니다


def _deadline(inst):
    return inst._cmd_pending[0]['deadline']


def test_window_is_extended_by_the_queue_wait():
    from aot.utils.time_utils import utc_now
    base = _FakeConfirmable()
    base.begin_command(0, 'on', False, dispatched_ok=True)
    plain = _deadline(base) - utc_now().timestamp()

    delayed = _FakeConfirmable()
    delayed.begin_command(0, 'on', False, dispatched_ok=True, extra_window_s=12.0)
    widened = _deadline(delayed) - utc_now().timestamp()

    assert widened - plain == pytest.approx(12.0, abs=0.5), (
        "큐에서 기다린 만큼 창이 넓어지지 않으면, 늦게 나간 명령은 창이 닫힌 "
        "뒤에 전파돼 멀쩡한 장치가 통신 장애로 판정된다")


def test_synchronous_outputs_are_unaffected():
    """동기 전송(GPIO 등)은 대기가 없으므로 창이 그대로여야 한다."""
    from aot.utils.time_utils import utc_now
    inst = _FakeConfirmable()
    inst.begin_command(0, 'on', False, dispatched_ok=True, extra_window_s=0.0)
    assert _deadline(inst) - utc_now().timestamp() == pytest.approx(8.0, abs=0.5)


def test_a_bad_extra_window_does_not_break_the_command():
    inst = _FakeConfirmable()
    inst.begin_command(0, 'on', False, dispatched_ok=True, extra_window_s='x')
    assert 0 in inst._cmd_pending
