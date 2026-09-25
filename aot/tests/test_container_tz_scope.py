# coding=utf-8
"""컨테이너 `TZ` 환경변수가 무엇에 영향을 주고 무엇에는 주지 않는지 고정한다.

문서(`docs/time-handling*.md`)의 약속: 예약·스케줄의 벽시계는 컨테이너 시계가 아니라
장치/도형/좌표/시스템(Misc.timezone) 시간대로 해석한다. 컨테이너 `TZ` 는
  1) 로그 시각,
  2) 첫 DB 생성 때 `Misc.timezone` 기본값
에만 쓰여야 한다. 아래 앞 두 묶음은 그 약속이 지켜지는 경로를, 마지막 xfail 은
아직 컨테이너 시계를 쓰는 경로(결함)를 기록한다.
"""
import os
import time

import pytest

from aot.databases.models import _host_timezone_name
from aot.utils.system_pi import epoch_of_next_time


@pytest.fixture
def container_tz():
    """`TZ` 를 바꾸고 `time.tzset()` 으로 프로세스 시계에 반영한다(컨테이너 재현)."""
    old = os.environ.get('TZ')

    def _set(name):
        os.environ['TZ'] = name
        time.tzset()

    yield _set
    if old is None:
        os.environ.pop('TZ', None)
    else:
        os.environ['TZ'] = old
    time.tzset()


def test_first_run_default_follows_container_tz(container_tz):
    container_tz('Asia/Seoul')
    assert _host_timezone_name() == 'Asia/Seoul'
    container_tz('America/Chicago')
    assert _host_timezone_name() == 'America/Chicago'


def test_invalid_tz_falls_back_to_a_valid_name(container_tz, monkeypatch):
    container_tz('Not/AZone')
    monkeypatch.setattr('builtins.open', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(os.path, 'realpath', lambda p: p)
    assert _host_timezone_name() == 'UTC'


def test_tz_aware_schedule_epoch_ignores_container_tz(container_tz):
    """장치/도형 tz 를 준 벽시계 예약은 컨테이너 TZ 와 무관하다."""
    container_tz('UTC')
    a = epoch_of_next_time('08:00:00', tz='Asia/Dhaka')
    container_tz('Asia/Seoul')
    b = epoch_of_next_time('08:00:00', tz='Asia/Dhaka')
    assert a == b


@pytest.mark.xfail(strict=True, reason=(
    '결함: lorawan_class_scheduler 는 datetime.now()(컨테이너 시계)로 수동 C 창·'
    '동절기·강제 활성 만료를 판정한다. 위치 tz(resolve_location_tz)를 써야 한다.'))
def test_class_scheduler_expiry_is_independent_of_container_tz(container_tz):
    from aot.functions.lorawan_class_scheduler import CustomModule

    sched = object.__new__(CustomModule)
    sched.manual_c_expire = '17:00'

    container_tz('UTC')
    a = sched._today_time_epoch('17:00')
    container_tz('Asia/Seoul')
    b = sched._today_time_epoch('17:00')
    assert a == b
