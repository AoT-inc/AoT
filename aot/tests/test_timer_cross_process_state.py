# coding=utf-8
"""타이머 위젯의 사이클 엔진이 gunicorn 여러 워커 **프로세스**에서도 맞는가.

## 왜 이 테스트가 있나

`AoT_timer.py`의 사이클 엔진(`_CYCLE_WORKERS`, `_cyc_state_ref`의 예전 캐시)은
전부 모듈 전역이었다. 이는 스레드 사이에서는 공유되지만 **프로세스 사이에서는
공유되지 않는다.** `install/gunicorn_conf.py`가 워커 프로세스 수를 1로 묶어
두던 제약을 2026-09-09에 풀면서(장 스케줄러 쪽만 고려해 daemon 하나로
실행을 몰았을 뿐, 이 위젯은 그 감사에서 빠졌다) 이 위젯의 전역 상태도 여러
프로세스에 흩어지게 됐다 — 실사용 증상: 토글이 켜졌다 꺼졌다를 반복하고,
Output 페이지에서 직접 켜도 위젯이 그 상태와 동기화되지 않으며, 정지를
눌러도 다른 프로세스에 남아 있는 워커 스레드가 이를 모른 채 다음 사이클에
다시 ON 을 쏜다.

고친 것은 둘이다.

**① 상태 읽기에 프로세스 캐시를 두지 않는다.** `_cyc_state_ref`가 첫 조회
결과를 프로세스 메모리에 캐싱하던 것을 없앴다 — 상태 파일이 곧 모든
프로세스가 동의하는 유일한 정본이다.

**② `run_id` 로 프로세스 경계를 넘는 정지 신호를 만든다.** 시작마다
새 `run_id` 를 발급해 상태 파일에 적어 두고, 워커 루프는 매 초 그 값이
자신의 것과 같은지 디스크에서 확인한다(`_cyc_should_stop`). 다른
프로세스에서 들어온 정지/재시작 요청은 (그 프로세스의) `stop_event` 에는
닿지 않지만 파일은 고쳐 쓸 수 있으므로, 원래 워커가 스스로 알아채고
출력을 끄고 종료한다.
"""
import os
import time as _t

import pytest


class _FakeDaemon:
    """output_on_off/output_state 호출만 기록하는 가짜 데몬. 즉시 'on' 을
    확인해 주므로 _wait_for_confirm 이 곧바로 통과한다."""

    def __init__(self, calls, *a, **kw):
        self._calls = calls

    def output_on_off(self, dev, state, output_type=None, amount=0.0,
                      output_channel=None, additional_options=None):
        self._calls.append(state)
        return (0, 'ok')

    def output_state(self, dev, output_channel=None):
        return 'on'


def test_status_read_always_reflects_the_latest_disk_state():
    """_cyc_state_ref 에 프로세스 캐시가 되살아나는 것을 막는 회귀 검사.

    캐시가 있으면, 상태 폴링 요청이 여러 gunicorn 워커 프로세스로 흩어질 때
    한 프로세스는 처음 본 스냅샷을 영원히 돌려주게 되어 토글이 깜빡인다."""
    import aot.widgets.AoT_timer as timer

    dev, ch = 'dev-cache-regress', 'chan-1'
    base = timer._cyc_state_default(dev, ch)

    base.update(active=True, phase='running', run_id='run-a')
    timer._cyc_state_write(dict(base))
    assert timer._cyc_state_snapshot(dev, ch)['phase'] == 'running'

    # 다른 호출(=다른 프로세스라고 가정)이 쓴 값이 바로 다음 조회에 보여야 한다.
    base.update(active=False, phase='stopped', run_id=None)
    timer._cyc_state_write(dict(base))
    assert timer._cyc_state_snapshot(dev, ch)['phase'] == 'stopped'


def test_cross_process_stop_is_noticed_by_an_orphaned_thread(monkeypatch):
    """다른 프로세스가 보낸 정지를, 실제 워커 스레드가 있는 이 프로세스가
    알아채고 출력을 꺼야 한다 — 장치는 계속 돌고 화면만 꺼진 척하면 안 된다."""
    import aot.widgets.AoT_timer as timer

    calls = []
    monkeypatch.setattr(timer, 'DaemonControl',
                        lambda *a, **kw: _FakeDaemon(calls, *a, **kw))

    dev, ch = 'dev-xproc-test', '0'
    timer._cyc_start_worker(dev, ch, 0, 5, 5, 3, 'cycle', None)
    try:
        deadline = _t.time() + 3.0
        st = {}
        while _t.time() < deadline:
            st = timer._cyc_state_snapshot(dev, ch)
            if st.get('phase') == 'running':
                break
            _t.sleep(0.05)
        assert st.get('phase') == 'running', f'실행 단계에 도달하지 못했다: {st}'
        off_count_before = calls.count('off')

        # 다른 gunicorn 워커 프로세스에서 들어온 정지를 흉내낸다: 이 프로세스의
        # _CYCLE_WORKERS 에는 없고 실제 stop_event 에도 닿지 않는다 — 할 수
        # 있는 건 상태 파일의 run_id 를 지우는 것뿐이다.
        timer._cyc_state_update(dev, ch, run_id=None)

        deadline = _t.time() + 3.0
        while _t.time() < deadline and calls.count('off') <= off_count_before:
            _t.sleep(0.05)
        assert calls.count('off') > off_count_before, (
            'run_id 가 지워졌는데도(다른 프로세스의 정지) 이 프로세스에 남아 '
            '있는 워커 스레드가 출력을 끄지 않았다 — 장치가 켜진 채 계속 돈다')

        on_count_after_off = calls.count('on')
        _t.sleep(1.2)
        assert calls.count('on') == on_count_after_off, (
            '지워진(superseded) run_id 로 다음 사이클에서 다시 ON 을 쏘고 있다')
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')


def test_should_stop_detects_run_id_mismatch_without_local_stop_event():
    import threading

    import aot.widgets.AoT_timer as timer

    dev, ch = 'dev-should-stop', 'chan-2'
    timer._cyc_state_update(dev, ch, run_id='mine')
    stop_event = threading.Event()

    assert timer._cyc_should_stop(dev, ch, 'mine', stop_event) is False

    timer._cyc_state_update(dev, ch, run_id='someone-elses')
    assert timer._cyc_should_stop(dev, ch, 'mine', stop_event) is True

    # 로컬 stop_event 가 서 있으면 run_id 와 무관하게 즉시 정지로 본다.
    stop_event.set()
    assert timer._cyc_should_stop(dev, ch, 'someone-elses', stop_event) is True


# ---- 재시작 순간의 예약 복구 경합 ----
#
# _cyc_trigger_recovery_once 의 _RECOVERED 게이트는 프로세스 하나 안에서만
# 중복을 막는다. gunicorn 워커가 N 개면 재시작 직후 N 개 프로세스가 각자
# recover_scheduled_workers() 를 한 번씩 돌려, 아직 'scheduled' 인 같은
# 상태 파일을 거의 동시에 보고 각자 워커를 띄울 수 있었다 — run_id 로
# 결국 하나만 남긴 하지만, 그 찰나에 ON/OFF 명령이 겹쳐 나간다.
# _cyc_try_claim_recovery 가 그 경합 자체를 막는다.

def test_recovery_claim_is_exclusive_and_releasable():
    import aot.widgets.AoT_timer as timer

    dev, ch = 'dev-claim-test', 'chan-3'
    timer._cyc_release_recovery_claim(dev, ch)  # 깨끗한 상태에서 시작

    assert timer._cyc_try_claim_recovery(dev, ch) is True
    # 바로 뒤이어 경합하는 두 번째 프로세스는 이길 수 없어야 한다.
    assert timer._cyc_try_claim_recovery(dev, ch) is False

    timer._cyc_release_recovery_claim(dev, ch)
    # 해제된 뒤에는(=복구를 마친 뒤) 다음 재시작이 다시 잡을 수 있어야 한다.
    assert timer._cyc_try_claim_recovery(dev, ch) is True
    timer._cyc_release_recovery_claim(dev, ch)


def test_stale_recovery_claim_can_be_stolen():
    """죽은 프로세스가 남긴 잠금 때문에 그 예약이 영영 복구되지 않으면 안 된다."""
    import os as _os

    import aot.widgets.AoT_timer as timer

    dev, ch = 'dev-claim-stale-test', 'chan-4'
    timer._cyc_release_recovery_claim(dev, ch)
    assert timer._cyc_try_claim_recovery(dev, ch) is True

    # 임계값만큼 실제로 기다리는 대신, 잠금 파일이 오래된 것처럼 시간만 되돌린다.
    old = _t.time() - (timer._RECOVERY_CLAIM_STALE_SEC + 5)
    path = timer._cyc_recovery_claim_path(dev, ch)
    _os.utime(path, (old, old))

    assert timer._cyc_try_claim_recovery(dev, ch) is True, (
        '오래된(죽은 프로세스의) 잠금을 되찾지 못해 예약 복구가 영원히 막힌다')
    timer._cyc_release_recovery_claim(dev, ch)


def test_recovery_race_between_two_processes_starts_the_worker_once(monkeypatch):
    """두 gunicorn 워커 프로세스가 함께 부팅하며 각자 recover_scheduled_workers()
    를 한 번씩 부른다 — 클레임이 없으면 둘 다 같은 예약을 복구해 워커를 두 번
    띄운다."""
    import threading

    import aot.widgets.AoT_timer as timer

    dev, ch = 'dev-recovery-race', '0'
    timer._cyc_release_recovery_claim(dev, ch)
    with timer._CYCLE_LOCK:
        timer._CYCLE_WORKERS.pop(timer._cyc_key(dev, ch), None)

    future_ms = int(_t.time() * 1000) + 60_000
    timer._cyc_state_write({
        'device_unique_id': dev, 'channel_id': ch, 'phase': 'scheduled',
        'scheduled_until_ms': future_ms, 'run_sec': 5, 'rest_sec': 5,
        'target_cycles': 1, 'mode': 'cycle',
    })

    starts = []

    def fake_start(*a, **kw):
        # 실제 백그라운드 스레드는 세우지 않는다 — 이 테스트는 클레임 배선만
        # 본다. (실서비스에서는 성공 시 클레임을 곧바로 풀지 않는다 — 풀면
        # 그 사이 새 스레드의 첫 상태 기록이 아직 안 닿아 phase 가 여전히
        # 'scheduled' 로 보이는 틈에 경쟁자가 다시 잡을 수 있다.)
        starts.append(a)

    monkeypatch.setattr(timer, '_cyc_start_worker', fake_start)
    try:
        barrier = threading.Barrier(2)

        def run():
            barrier.wait(timeout=2.0)
            timer.recover_scheduled_workers()

        threads = [threading.Thread(target=run) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5.0)

        assert len(starts) == 1, (
            f'같은 예약을 {len(starts)}번 복구했다 — 재시작 경합에서 ON/OFF 가 겹쳐 나간다')
    finally:
        timer._cyc_release_recovery_claim(dev, ch)
        # phase='scheduled' 인 상태 파일을 남겨 두면, 이후 어떤 테스트든
        # recover_scheduled_workers() 를 부를 때마다 이 가짜 예약을 다시
        # 주워 담는다. 실제 _SESS_DIR(/tmp/aot_timer_sessions)와도 같은
        # 규칙이므로 반드시 지운다.
        try:
            os.remove(timer._cyc_state_path(dev, ch))
        except OSError:
            pass
