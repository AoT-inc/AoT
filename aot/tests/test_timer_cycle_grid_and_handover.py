# coding=utf-8
"""타이머 위젯 사이클 엔진의 시간 동작 — 2026-11-11 점검에서 재현한 세 결함.

1. **재시작이 다른 프로세스로 가면 새 실행이 꺼졌다.** 옛 작업 스레드는 교체를 알아채고
   나가며 OFF 를 보냈는데, 그 사이 새 실행이 이미 출력을 켰다 — 화면은 작동 중, 출력은
   꺼짐. 이제 재시작은 새 run_id 를 먼저 적고, 옛 스레드는 그것을 보면 끄지 않는다.
2. **웹 앱이 꺼져 있는 동안 예약 시각이 지나면 상태가 "Scheduled" 로 굳었다.** 이제
   놓쳤다고 적는다(늦게 켜지는 않는다).
3. **반복 주기가 확인 대기만큼 주기마다 늦어졌다.** 이제 주기 k 는
   `원점 + (k-1) x (켜짐+쉼)` 에 시작하고, 확인 대기는 쉼에서 뺀다.
"""
import time as _t

import pytest

pytestmark = pytest.mark.usefixtures('timer_sessions')


class _Daemon:
    """명령을 (시각, 상태)로 남긴다. `lag_polls` 번 물어본 뒤에야 바뀐 상태를 알려 준다
    — 원격 출력처럼 확인이 늦게 오는 장치."""

    def __init__(self, log, lag_polls=0):
        self.log = log
        self.lag_polls = lag_polls
        self.state = 'off'
        self.pending = 0

    def __call__(self, *a, **kw):
        return self

    def output_on_off(self, dev, state, output_type=None, amount=0.0,
                      output_channel=None, additional_options=None):
        self.log.append((_t.time(), state))
        if state != self.state:
            self.state = state
            self.pending = self.lag_polls
        return (0, 'ok')

    def output_state(self, dev, output_channel=None):
        if self.pending > 0:
            self.pending -= 1
            return 'on' if self.state == 'off' else None
        return self.state


@pytest.fixture
def timer(monkeypatch):
    import aot.widgets.AoT_timer as mod
    monkeypatch.setattr(mod, '_resolve_channel_index', lambda d, c: 0)
    return mod


def _wait_phase(timer, dev, ch, phase, timeout=4.0):
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if timer._cyc_state_snapshot(dev, ch).get('phase') == phase:
            return True
        _t.sleep(0.05)
    return False


def test_restart_landing_on_another_process_does_not_switch_the_new_run_off(timer, monkeypatch):
    log = []
    monkeypatch.setattr(timer, 'DaemonControl', _Daemon(log))
    dev, ch = 'dev-handover', '0'
    timer._cyc_start_worker(dev, ch, 0, 30, 5, 3, 'cycle', None)
    try:
        assert _wait_phase(timer, dev, ch, 'running')
        # 다른 gunicorn 워커 프로세스가 '시작' 을 받은 것처럼: 이 프로세스의 작업 스레드는
        # 그 프로세스의 목록에 없다 — 디스크로만 알 수 있다.
        with timer._CYCLE_LOCK:
            timer._CYCLE_WORKERS.pop(timer._cyc_key(dev, ch))
        timer._cyc_start_worker(dev, ch, 0, 30, 5, 3, 'cycle', None)
        assert _wait_phase(timer, dev, ch, 'running')
        new_on = max(t for t, s in log if s == 'on')
        _t.sleep(2.5)   # 옛 스레드가 교체를 알아채고(최대 1초) 나갈 시간
        late_off = [t for t, s in log if s == 'off' and t > new_on]
        assert not late_off, f'옛 스레드가 새 실행의 ON 뒤에 OFF 를 보냈다: {log}'
        assert timer._cyc_state_snapshot(dev, ch).get('phase') == 'running'
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')


def test_stop_landing_on_another_process_still_switches_off(timer, monkeypatch):
    """정지(run_id 를 비움)는 예전처럼 옛 스레드도 끈다 — 끄는 쪽을 약하게 하지 않는다."""
    log = []
    monkeypatch.setattr(timer, 'DaemonControl', _Daemon(log))
    dev, ch = 'dev-handover-stop', '0'
    timer._cyc_start_worker(dev, ch, 0, 30, 5, 3, 'cycle', None)
    try:
        assert _wait_phase(timer, dev, ch, 'running')
        before = sum(1 for _, s in log if s == 'off')
        timer._cyc_state_update(dev, ch, run_id=None)
        deadline = _t.time() + 3.0
        while _t.time() < deadline and sum(1 for _, s in log if s == 'off') <= before:
            _t.sleep(0.05)
        assert sum(1 for _, s in log if s == 'off') > before
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')


def _scheduled_state(timer, dev, ch, sched_ms):
    timer._cyc_state_update(
        dev, ch, active=True, phase='scheduled', message='Scheduled', run_id='old',
        mode='cycle', run_sec=60, rest_sec=60, target_cycles=3, start_at='06:00',
        scheduled_until_ms=sched_ms, next_transition_ms=sched_ms)


def test_schedule_passed_while_app_was_down_is_reported_missed(timer, monkeypatch):
    log = []
    monkeypatch.setattr(timer, 'DaemonControl', _Daemon(log))
    dev, ch = 'dev-missed', '0'
    _scheduled_state(timer, dev, ch, int(_t.time() * 1000) - 10 * 60 * 1000)
    timer.recover_scheduled_workers()
    st = timer._cyc_state_snapshot(dev, ch)
    assert st['phase'] == 'error' and st['active'] is False, st
    assert st['message'] == 'Scheduled start missed'
    assert st['scheduled_until_ms'] is None
    assert not log, '놓친 예약을 늦게라도 켰다 — 예약한 시각이 아니다'


def test_schedule_that_just_passed_is_left_to_a_live_worker(timer, monkeypatch):
    """예약 시각 직후(1분 안)는 다른 프로세스의 살아 있는 스레드가 막 깨어나는 중일 수 있다."""
    monkeypatch.setattr(timer, 'DaemonControl', _Daemon([]))
    dev, ch = 'dev-missed-grace', '0'
    _scheduled_state(timer, dev, ch, int(_t.time() * 1000) - 5 * 1000)
    timer.recover_scheduled_workers()
    assert timer._cyc_state_snapshot(dev, ch)['phase'] == 'scheduled'


def test_cycles_start_on_a_fixed_grid_despite_confirm_lag(timer, monkeypatch):
    """켜짐 1초·쉼 3초 → 주기 4초. ON·OFF 확인이 각각 약 1초 늦어도 주기 시작은
    0·4·8초여야 한다(예전: 0·6·12초 — 확인 대기가 주기마다 쌓였다)."""
    log = []
    monkeypatch.setattr(timer, 'DaemonControl', _Daemon(log, lag_polls=1))
    dev, ch = 'dev-grid', '0'
    timer._cyc_start_worker(dev, ch, 0, 1, 3, 3, 'cycle', None)
    try:
        deadline = _t.time() + 14.0
        while _t.time() < deadline and sum(1 for _, s in log if s == 'on') < 3:
            _t.sleep(0.05)
        ons = [t for t, s in log if s == 'on']
        assert len(ons) >= 3, log
        origin = timer._cyc_state_snapshot(dev, ch)['cycle_origin_ms'] / 1000.0
        offsets = [round(t - origin, 1) for t in ons[:3]]
        for k, off in enumerate(offsets):
            assert abs(off - 4 * k) < 0.6, f'주기 {k + 1} 시작이 격자({4 * k}s)에서 벗어났다: {offsets}'
        # 켜짐은 확인된 때부터 다 채운다(Model A) — 쉼만 줄어든다.
        st = timer._cyc_state_snapshot(dev, ch)
        assert st['run_sec'] == 1 and st['rest_sec'] == 3
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')


def test_rest_left_absorbs_lag_and_never_goes_negative(timer):
    # 원점 0, 켜짐 60·쉼 120 → 주기 1 다음 시작은 180초.
    assert timer._cyc_rest_left_sec(0, 1, 60, 120, 75_000) == 105.0    # 15초 늦음 → 쉼 105
    assert timer._cyc_rest_left_sec(0, 1, 60, 120, 60_000) == 120.0    # 늦지 않음 → 쉼 그대로
    assert timer._cyc_rest_left_sec(0, 1, 60, 120, 200_000) == 0.0     # 쉼보다 늦음 → 0
    assert timer._cyc_rest_left_sec(0, 1, 60, 120, 10_000) == 120.0    # 원점 이상해도 쉼 이상 안 쉼


def test_resume_keeps_the_original_grid(timer):
    # 상태에 원점이 있으면 그것을 쓴다.
    assert timer._cyc_grid_origin({'origin_ms': 1_000, 'cycle': 2, 'kind': 'rest',
                                   'remaining_sec': 5}, 99_999, 60, 120) == 1_000
    # 예전 상태 파일(원점 없음): 주기 2 의 쉼이 30초 남았으면 주기 3 은 지금+30초 →
    # 원점 = 그 시각 - 2 x 180초.
    now = 1_000_000
    got = timer._cyc_grid_origin({'cycle': 2, 'kind': 'rest', 'remaining_sec': 30},
                                 now, 60, 120)
    assert got == now + 30_000 - 2 * 180_000
    # 켜짐 중간: 주기 2 켜짐이 20초 남음 → 주기 2 시작 = 지금+20-60초.
    got = timer._cyc_grid_origin({'cycle': 2, 'kind': 'run', 'remaining_sec': 20},
                                 now, 60, 120)
    assert got == now + 20_000 - 60_000 - 180_000
