# coding=utf-8
"""타이머 위젯의 "시작 시각"(start_at)이 실제로 저장되는가.

## 왜 이 테스트가 있나

가동/휴지/횟수는 `_cyc_preset_set`이 저장해 다음 페이지 로드 때
`fetchPresetValues`가 되살리지만, `start_at`은 그 함수의 인자에 아예
없었다 — 사용자가 "시작 시각"을 몇 시로 바꾸든 프리셋에도, 사이클 상태
파일에도 결코 기록되지 않고 위젯 옵션의 기본값(대개 00:00)으로 항상
되돌아갔다(실사용 신고, 2026-09-13). 예약 자체(`scheduled_until_ms`)는
그 순간 제출된 값으로 정확히 계산되어 동작은 했지만, 그 값을 기억하는
곳이 없어 새로고침하면 사라졌다.
"""
import threading
import time as _t

import aot.widgets.AoT_timer as timer


def test_preset_set_saves_start_at():
    dev, ch = 'dev-startat-preset', 'chan-1'
    timer._cyc_preset_set(dev, ch, run_sec=120, rest_sec=60, cycles=3, start_at='11:30')
    data = timer._cyc_preset_get(dev, ch)
    assert data['start_at'] == '11:30', (
        'start_at 이 프리셋에 저장되지 않는다 — 새로고침하면 항상 위젯 기본값으로 되돌아간다')


def test_preset_set_defaults_start_at_when_omitted():
    dev, ch = 'dev-startat-preset-default', 'chan-1'
    timer._cyc_preset_set(dev, ch, run_sec=120, rest_sec=60, cycles=3)
    data = timer._cyc_preset_get(dev, ch)
    assert data['start_at'] == '00:00'


def test_cycle_start_route_persists_start_at_into_the_preset(monkeypatch):
    """실제 라우트(aot_timer_cycle_start)가 start_at을 프리셋에 넘기는가."""
    import flask

    app = flask.Flask(__name__)
    app.config['TESTING'] = True

    class _FakeUser:
        is_authenticated = True

    monkeypatch.setattr(timer, 'current_user', _FakeUser())
    monkeypatch.setattr(timer.utils_general, 'user_has_permission', lambda *a, **kw: True)
    monkeypatch.setattr(timer.scope, 'can_operate_device', lambda *a, **kw: True)
    monkeypatch.setattr(timer, '_resolve_channel_index', lambda dev, ch: 0)
    monkeypatch.setattr(timer, '_cyc_start_worker', lambda *a, **kw: None)

    dev, ch = 'dev-startat-route', '0'
    with app.test_request_context(
            f'/aot_timer_cycle_start/{dev}/{ch}', method='POST',
            json={'mode': 'cycle', 'run_sec': 90, 'rest_sec': 30, 'cycles': 4, 'start_at': '06:15'}):
        timer.aot_timer_cycle_start(dev, ch)

    data = timer._cyc_preset_get(dev, ch)
    assert data['start_at'] == '06:15', (
        'aot_timer_cycle_start 라우트가 start_at을 프리셋에 저장하지 않는다')


def test_worker_writes_start_at_into_the_cycle_state(monkeypatch):
    """실제로 사이클이 시작되면 상태 파일(status API 응답)에도 start_at이 남는가."""
    class _FakeDaemon:
        def __init__(self, *a, **kw):
            pass

        def output_on_off(self, *a, **kw):
            return (0, 'ok')

        def output_state(self, *a, **kw):
            return 'on'

    monkeypatch.setattr(timer, 'DaemonControl', _FakeDaemon)

    dev, ch = 'dev-startat-worker', '0'
    timer._cyc_start_worker(dev, ch, 0, 5, 5, 2, 'cycle', None, '07:45')
    try:
        deadline = _t.time() + 3.0
        st = {}
        while _t.time() < deadline:
            st = timer._cyc_state_snapshot(dev, ch)
            if st.get('phase') in ('running', 'initializing'):
                break
            _t.sleep(0.05)
        assert st.get('start_at') == '07:45', (
            f'워커가 시작한 사이클의 상태에 start_at 이 반영되지 않았다: {st}')
    finally:
        timer._cyc_stop_worker(dev, ch, reason='test_cleanup')


def test_recovery_passes_the_persisted_start_at_through(monkeypatch):
    """재시작 복구도 상태 파일에 적힌 start_at을 그대로 다음 워커에 넘기는가."""
    dev, ch = 'dev-startat-recovery', '0'
    timer._cyc_release_recovery_claim(dev, ch)
    with timer._CYCLE_LOCK:
        timer._CYCLE_WORKERS.pop(timer._cyc_key(dev, ch), None)

    future_ms = int(_t.time() * 1000) + 60_000
    timer._cyc_state_write({
        'device_unique_id': dev, 'channel_id': ch, 'phase': 'scheduled',
        'scheduled_until_ms': future_ms, 'run_sec': 5, 'rest_sec': 5,
        'target_cycles': 1, 'mode': 'cycle', 'start_at': '22:10',
    })

    seen = []
    monkeypatch.setattr(timer, '_cyc_start_worker',
                        lambda *a, **kw: seen.append(a))
    try:
        timer.recover_scheduled_workers()
        assert seen, '복구가 워커를 시작하지 않았다'
        assert seen[0][-1] == '22:10', (
            f'복구가 start_at 을 잃어버리고 다른 값을 넘겼다: {seen[0]}')
    finally:
        timer._cyc_release_recovery_claim(dev, ch)
        try:
            import os
            os.remove(timer._cyc_state_path(dev, ch))
        except OSError:
            pass
