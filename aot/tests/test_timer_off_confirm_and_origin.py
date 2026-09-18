# coding=utf-8
"""OFF 를 보낸 것으로 끝내지 않는가, 그리고 그 명령의 주인이 남는가.

## 왜 이 테스트가 있나

2026-09-14 현장(고객사 서버): 타이머로 45분 가동 / 15분 휴지를 돌리던 밸브가
20시간 연속 열린 채였는데, **감사로그에는 ON/OFF 가 번갈아 `success` 로**
남아 있었다. 사람이 손으로 끌 때까지 물이 계속 나왔다.

두 구멍이다.

**① OFF 는 보낸 것으로 끝났다.** 감사로그의 `success` 는 "드라이버가 오류를
안 냈다" 까지다. LoRaWAN 처럼 큐를 타는 전송에서 `output_switch('off')` 의 0 은
"전송 큐가 접수했다" 는 뜻이고, 전파와 장치 동작은 그 뒤에 온다. 끝내 닿지
않아도 위젯은 다음 사이클로 태연히 넘어갔다 — 끄는 척하며 계속 켜져 있는
상태다. ON 쪽은 이미 `_wait_for_confirm` 으로 확인을 기다리는데 OFF 쪽만
없었다.

**② 그 명령이 누구 것인지 남지 않았다.** 워커는 요청 문맥 밖의 배경
스레드라 출처 판정이 `unknown` 으로 떨어진다. 현장 감사로그의 타이머 행이
전부 `origin=unknown` 이라, 기록만 봐서는 타이머가 한 것인지 우회 경로인지
구분되지 않았다.
"""
import os
import time as _t

import aot.widgets.AoT_timer as timer


class _FakeDaemon:
    """명령을 기록하는 가짜 데몬.

    off_reports=False 면 장치가 영영 꺼졌다고 보고하지 않는다(다운링크 유실).
    origins 를 주면 명령마다 그 시점의 출처 판정을 함께 기록한다.
    """

    def __init__(self, calls, off_reports=True, origins=None):
        self._calls = calls
        self._off_reports = off_reports
        self._origins = origins
        self._state = 'off'

    def output_on_off(self, dev, state, output_type=None, amount=0.0,
                      output_channel=None, additional_options=None):
        self._calls.append(state)
        if self._origins is not None:
            from aot.utils.command_origin import resolve_origin
            self._origins.append(resolve_origin())
        if state == 'on':
            self._state = 'on'
        elif self._off_reports:
            self._state = 'off'
        return (0, 'ok')

    def output_state(self, dev, output_channel=None):
        return self._state


def _cleanup(dev, ch):
    with timer._CYCLE_LOCK:
        timer._CYCLE_WORKERS.pop(timer._cyc_key(dev, ch), None)
    for path in (timer._cyc_state_path(dev, ch), timer._cyc_preset_path(dev, ch)):
        try:
            os.remove(path)
        except OSError:
            pass


# ---- ① OFF 확인 ----

def test_an_unconfirmed_off_stops_the_cycle_and_says_so(monkeypatch):
    """OFF 명령은 나갔는데 장치가 꺼졌다고 하지 않으면 멈추고 알려야 한다.

    이것이 현장에서 가장 위험했던 모습이다 — 기록은 성공인데 밸브는 열려 있었다.
    """
    dev, ch = 'dev-off-unconfirmed', '0'
    _cleanup(dev, ch)
    calls = []
    monkeypatch.setattr(timer, 'DaemonControl',
                        lambda *a, **kw: _FakeDaemon(calls, off_reports=False))
    monkeypatch.setattr(timer, '_wait_for_off_confirm', lambda *a, **kw: 'timeout')

    timer._cyc_start_worker(dev, ch, 0, 1, 1, 3, 'cycle', None, '00:00')
    try:
        deadline = _t.time() + 8.0
        st = {}
        while _t.time() < deadline:
            st = timer._cyc_state_snapshot(dev, ch)
            if st.get('phase') == 'error':
                break
            _t.sleep(0.1)
        assert st.get('phase') == 'error', (
            f'OFF 가 확인되지 않았는데도 사이클을 계속 돌린다: {st}')
        assert st.get('error') == 'off_not_confirmed'
        assert st.get('active') is False, '화면이 계속 가동 중으로 보인다'
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')
        _cleanup(dev, ch)


def test_off_confirm_reports_off_when_the_device_says_so():
    """정상일 때는 곧바로 'off' 를 돌려줘야 한다 — 매번 30초를 까먹으면 안 된다."""
    daemon = _FakeDaemon([])
    assert timer._wait_for_off_confirm(daemon, 'dev', 0, timeout=3.0) == 'off'


def test_off_confirm_times_out_when_the_device_never_answers():
    daemon = _FakeDaemon([], off_reports=False)
    daemon._state = 'on'
    assert timer._wait_for_off_confirm(daemon, 'dev', 0, timeout=2.0) == 'timeout'


# ---- ② 출처 귀속 ----

def test_timer_is_an_audited_origin_type():
    from aot.utils.command_origin import AUDITED_TYPES, TYPE_TIMER
    assert TYPE_TIMER in AUDITED_TYPES, (
        '타이머 출처가 감사 대상이 아니면 밸브 명령 기록이 통째로 사라진다 — '
        '`unknown` 으로 남는 것보다 나쁘다')


def test_worker_commands_are_attributed_to_the_timer(monkeypatch):
    """감사로그가 origin=unknown 이 아니라 timer 로 남는가."""
    dev, ch = 'dev-origin', '0'
    _cleanup(dev, ch)
    origins = []
    monkeypatch.setattr(timer, 'DaemonControl',
                        lambda *a, **kw: _FakeDaemon([], origins=origins))

    timer._cyc_start_worker(dev, ch, 0, 30, 30, 1, 'cycle', None, '00:00')
    try:
        deadline = _t.time() + 3.0
        while _t.time() < deadline and not origins:
            _t.sleep(0.05)
        assert origins, '워커가 명령을 내지 않았다'
        types = {o['type'] for o in origins}
        assert types == {'timer'}, (
            f'타이머 명령이 {types} 로 기록된다 — 현장에서 전부 unknown 이었다')
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')
        _cleanup(dev, ch)


# ---- ③ OFF 확인 대기 중 다른 프로세스에 넘어간 상태를 덮어쓰지 않는가 ----

def test_off_confirm_timeout_does_not_clobber_a_different_process_restart(monkeypatch):
    """OFF 확인 대기(최대 30초) 동안 *다른* gunicorn 워커 프로세스가 같은
    장치/채널을 재시작시켰으면, 그 프로세스가 이미 디스크에 새 run_id 를 써
    둔다 — 이 스레드의 stop_event 는 그 프로세스에서 보이지 않으니
    `_cyc_should_stop` 의 run_id 대조가 유일한 감지 수단이다(_cyc_sleep 이
    이미 쓰는 것과 같은 메커니즘). 이 워커가 타임아웃 뒤 그 상태를
    'OFF not confirmed' 오류로 덮어쓰면, 방금 시작된 새 실행이 화면에서
    사라진다.
    """
    dev, ch = 'dev-off-cross-process', '0'
    _cleanup(dev, ch)
    calls = []
    other_run_id = 'other-process-run-id'

    def _fake_off_confirm(daemon, device_unique_id, channel_index, stop_event=None, timeout=30.0):
        # 다른 프로세스가 이 30초 대기 동안 같은 장치/채널을 재시작시킨
        # 상황을 흉내낸다 — 디스크에 새 run_id 로 곧바로 새 실행이 있다고 쓴다.
        timer._cyc_state_update(
            dev, ch, run_id=other_run_id,
            active=True, phase='initializing', message='Initializing (other process)')
        return 'timeout'

    monkeypatch.setattr(timer, 'DaemonControl', lambda *a, **kw: _FakeDaemon(calls))
    monkeypatch.setattr(timer, '_wait_for_off_confirm', _fake_off_confirm)

    timer._cyc_start_worker(dev, ch, 0, 1, 1, 3, 'cycle', None, '00:00')
    try:
        deadline = _t.time() + 8.0
        st = {}
        while _t.time() < deadline:
            st = timer._cyc_state_snapshot(dev, ch)
            if st.get('run_id') == other_run_id:
                break
            _t.sleep(0.1)
        assert st.get('run_id') == other_run_id, (
            f'다른 프로세스가 써 둔 새 실행 상태가 안 보인다: {st}')
        assert st.get('phase') == 'initializing' and st.get('active') is True, (
            f'superseded 된 워커가 다른 프로세스의 새 실행 상태를 '
            f"'off_not_confirmed' 로 덮어썼다: {st}")
    finally:
        with timer._CYCLE_LOCK:
            timer._CYCLE_WORKERS.pop(timer._cyc_key(dev, ch), None)
        _cleanup(dev, ch)
