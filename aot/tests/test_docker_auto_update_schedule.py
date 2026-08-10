# coding=utf-8
"""Docker 자동 업데이트 스케줄 회귀 가드.

"매일 03:00 에 업데이트" 는 조용히 틀리기 쉬운 기능이다. 세 가지가 특히 그렇다:

1. **시간대.** 농장 관리자가 03:00 이라고 하면 현지 시각 03:00 이다.
   `time_utils.get_timezone_name()` 은 Flask 앱 컨텍스트가 없으면 조용히 UTC 로
   폴백하는데, 데몬에는 컨텍스트가 없다 — 그대로 두면 KST 사용자가 정오에
   업데이트를 맞게 된다. 그래서 데몬은 Misc 행에서 직접 tz 를 읽어 넘긴다.
2. **경계.** 지금이 정확히 예약 시각이면 다음 실행은 내일이어야 한다. 아니면
   업데이트 직후 같은 시각이 다시 조건을 만족해 하루 종일 반복한다.
3. **재무장 시점.** 실패해도 다음 실행 시각은 전진해야 한다. 성공할 때만
   전진하면 실패한 날에는 루프가 돌 때마다 재시도한다.

읽기 전용이고 네트워크·Docker 를 쓰지 않는다.
"""
import datetime
import sys
import types

import pytest

from aot.utils import docker_update as du

KST = datetime.timezone(datetime.timedelta(hours=9))


def _at(year, month, day, hour, minute, tz=KST):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=tz).timestamp()


def test_parse_schedule_accepts_times_of_day_only():
    assert du.parse_schedule('03:00') == (3, 0)
    assert du.parse_schedule('3:00') == (3, 0)
    assert du.parse_schedule(' 23:59 ') == (23, 59)
    for bad in ('', None, '24:00', '03:60', '-1:00', 'abc', '0300', '03-00',
                '03:00:00'):
        assert du.parse_schedule(bad) is None, bad


def test_schedule_is_interpreted_in_the_given_timezone():
    """같은 '03:00' 이 시간대에 따라 다른 절대 시각이어야 한다 — 이게 같아지면
    tz 인자가 무시되고 있다는 뜻이다."""
    after = _at(2026, 8, 10, 0, 0)
    seoul = du.next_scheduled_run('03:00', after=after, tz_name='Asia/Seoul')
    utc = du.next_scheduled_run('03:00', after=after, tz_name='UTC')
    assert seoul != utc
    # 서울 03:00 = 전날 18:00 UTC
    assert (datetime.datetime.fromtimestamp(seoul, datetime.timezone.utc)
            .strftime('%H:%M')) == '18:00'


def test_exact_match_moves_to_tomorrow():
    """정확히 예약 시각이면 '오늘' 이 아니라 '내일' 이다. 아니면 방금 끝난
    업데이트가 같은 창에서 다시 자격을 얻는다."""
    now = _at(2026, 8, 10, 3, 0)
    nxt = du.next_scheduled_run('03:00', after=now, tz_name='Asia/Seoul')
    assert nxt == _at(2026, 8, 11, 3, 0)


def test_before_and_after_the_hour():
    before = du.next_scheduled_run('03:00', after=_at(2026, 8, 10, 2, 59),
                                   tz_name='Asia/Seoul')
    assert before == _at(2026, 8, 10, 3, 0)

    after = du.next_scheduled_run('03:00', after=_at(2026, 8, 10, 3, 1),
                                  tz_name='Asia/Seoul')
    assert after == _at(2026, 8, 11, 3, 0)


def test_crossing_midnight():
    nxt = du.next_scheduled_run('00:30', after=_at(2026, 8, 10, 23, 59),
                                tz_name='Asia/Seoul')
    assert nxt == _at(2026, 8, 11, 0, 30)


def test_unusable_schedule_is_never_now():
    """읽을 수 없는 시각은 '지금 실행' 이 아니라 '실행 안 함' 이다."""
    for bad in ('', None, 'nope', '99:99'):
        assert du.next_scheduled_run(bad) is None


def _daemon_stub(tmp_path, monkeypatch, upgrade=None, updater_present=True):
    """run_docker_auto_update() 를 self 스텁으로 호출하기 위한 최소 환경."""
    import importlib
    import json
    import os

    from aot import config
    update_dir = tmp_path / 'update'
    for name, value in (
            ('DOCKER_UPDATE_PATH', str(update_dir)),
            ('DOCKER_UPDATE_REQUEST_FILE', str(update_dir / 'request.json')),
            ('DOCKER_UPDATE_STATUS_FILE', str(update_dir / 'status.json')),
            ('DOCKER_UPDATE_HEARTBEAT_FILE', str(update_dir / 'heartbeat.json')),
            ('DOCKER_UPDATE_LOG_FILE', str(update_dir / 'update.log'))):
        monkeypatch.setattr(config, name, value)
    module = importlib.reload(importlib.import_module('aot.utils.docker_update'))

    os.makedirs(update_dir, exist_ok=True)

    from aot import aot_daemon
    monkeypatch.setattr(aot_daemon, 'docker_update', module)
    monkeypatch.setattr(aot_daemon, 'updater_status',
                        lambda: {'present': updater_present})
    monkeypatch.setattr(
        aot_daemon, 'check_upgrade_exists',
        lambda: ((True, ['26.09.0'], [], '26.09.0', []) if upgrade
                 else (False, [], [], '26.08.2', [])))
    monkeypatch.setattr(aot_daemon, 'audit_log', lambda *a, **k: None)

    logged = []
    stub = types.SimpleNamespace(
        logger=types.SimpleNamespace(
            info=lambda m: logged.append(('info', m)),
            debug=lambda m: logged.append(('debug', m)),
            warning=lambda m: logged.append(('warning', m)),
            error=lambda m: logged.append(('error', m)),
            exception=lambda m: logged.append(('exception', m))),
        docker_auto_update_time='03:00',
        docker_auto_update_tz='Asia/Seoul',
        docker_update_next_run=1.0,
        flask_app=types.SimpleNamespace(
            app_context=lambda: _NullContext()),
    )
    return aot_daemon, stub, module, update_dir, logged


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fires_and_writes_a_request_when_an_update_exists(tmp_path, monkeypatch):
    import json

    daemon_mod, stub, module, update_dir, logged = _daemon_stub(
        tmp_path, monkeypatch, upgrade=True)

    daemon_mod.DaemonController.run_docker_auto_update(stub)

    request = json.loads((update_dir / 'request.json').read_text())
    assert request['target'] == '26.09.0'
    assert request['requested_by'] == 'auto-update'
    # 다음 실행 시각이 전진했다
    assert stub.docker_update_next_run > 1.0


def test_no_updater_means_no_request(tmp_path, monkeypatch):
    daemon_mod, stub, module, update_dir, logged = _daemon_stub(
        tmp_path, monkeypatch, upgrade=True, updater_present=False)

    daemon_mod.DaemonController.run_docker_auto_update(stub)

    assert not (update_dir / 'request.json').exists()
    assert any(level == 'warning' for level, _ in logged), \
        "설치할 수단이 없는데 조용하면 안 된다"
    # 수단이 없어도 일정은 전진한다 — 매 루프 재시도 방지
    assert stub.docker_update_next_run > 1.0


def test_up_to_date_writes_nothing(tmp_path, monkeypatch):
    daemon_mod, stub, module, update_dir, logged = _daemon_stub(
        tmp_path, monkeypatch, upgrade=False)

    daemon_mod.DaemonController.run_docker_auto_update(stub)

    assert not (update_dir / 'request.json').exists()
    # 하루 한 번, "확인했고 할 일 없었다" 는 남아야 한다 — 침묵은 일정이
    # 아예 안 도는 것과 구분되지 않는다
    assert any(level == 'info' for level, _ in logged)


def test_schedule_advances_even_when_the_registry_fails(tmp_path, monkeypatch):
    daemon_mod, stub, module, update_dir, logged = _daemon_stub(
        tmp_path, monkeypatch, upgrade=False)

    def boom():
        raise RuntimeError("registry unreachable")

    monkeypatch.setattr(daemon_mod, 'check_upgrade_exists', boom)
    daemon_mod.DaemonController.run_docker_auto_update(stub)

    assert stub.docker_update_next_run > 1.0, \
        "실패해도 전진하지 않으면 하루 종일 루프마다 재시도한다"
    assert any(level == 'exception' for level, _ in logged)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
