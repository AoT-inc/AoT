# coding=utf-8
"""함수 상태에 찍히는 시각은 서버(컨테이너) 시계가 아니라 **함수가 걸린 장소의 시계**다.

2026-11-11 점검 8번: `lorawan_class_scheduler`(마지막 전환)와 `camera_libcamera`(타임랩스
시작·끝·다음 촬영)가 `datetime.fromtimestamp(epoch)` 로 naive 서버 로컬 시각을 만들어 보여
줬다. 컨테이너 `TZ` 가 UTC 이면 서울 장소에서도 UTC 시각이 찍혔고, 시간대 표기도 없다.
`check_time_rules` 는 `utcfromtimestamp` 만 잡아 이것을 놓쳤다.

고정하는 것: 프로세스 `TZ` 를 어떻게 바꿔도 같은 장소 시각이 나오고, DST 경계의 장소
시각이 맞는다. 저장된 `tl_start_str`(파일 이름용)은 건드리지 않는다.
"""
import os
import time
from datetime import datetime, timezone
from unittest import mock

import pytest
import pytz

from aot.functions import camera_libcamera as cam
from aot.functions import lorawan_class_scheduler as lora
from aot.utils import timekit


@pytest.fixture
def process_tz():
    """프로세스(서버) 시간대를 바꾼다 — 예전 코드는 이 값을 그대로 찍었다."""
    saved = os.environ.get('TZ')

    def _set(name):
        os.environ['TZ'] = name
        time.tzset()

    yield _set
    if saved is None:
        os.environ.pop('TZ', None)
    else:
        os.environ['TZ'] = saved
    time.tzset()


def _place(tz_name):
    """장소 시계를 고정한다(`tz_of` 가 어떤 id 에든 이 시간대를 돌려준다)."""
    return mock.patch.object(timekit, 'tz_of', lambda where=None, cache=None: pytz.timezone(tz_name))


def _epoch(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


# ── lorawan_class_scheduler ──────────────────────────────────────────────────
def _lora(last_tr):
    scheduler = lora.CustomModule.__new__(lora.CustomModule)
    scheduler.unique_id = 'lora-1'
    scheduler.control_mode = 'auto'
    values = {'sched_last_transition_ts': str(last_tr)}
    scheduler.get_custom_option = lambda key, default=None: values.get(key, default)
    scheduler._persisted_devices = lambda: []
    return scheduler


def _last_transition(text):
    return next(line for line in text.splitlines() if line.startswith('Last transition:'))


@pytest.mark.parametrize('server_tz', ['UTC', 'America/Los_Angeles', 'Asia/Tokyo'])
def test_lorawan_last_transition_is_in_the_place_clock(process_tz, server_tz):
    process_tz(server_tz)
    epoch = _epoch(2026, 11, 11, 20, 0)                  # 서울 2026-11-12 05:00
    with _place('Asia/Seoul'):
        line = _last_transition(_lora(epoch).function_status()['string_status'])
    assert line == 'Last transition: 2026-11-12 05:00'


def test_lorawan_last_transition_dst_fall_back(process_tz):
    process_tz('UTC')
    with _place('America/New_York'):
        before = _last_transition(_lora(_epoch(2026, 11, 1, 5, 30)).function_status()['string_status'])
        after = _last_transition(_lora(_epoch(2026, 11, 1, 6, 30)).function_status()['string_status'])
    assert before == 'Last transition: 2026-11-01 01:30'   # 아직 EDT
    assert after == 'Last transition: 2026-11-01 01:30'    # 되돌린 뒤 EST 의 두 번째 01:30


def test_lorawan_no_transition_yet_is_a_dash():
    with _place('Asia/Seoul'):
        assert _last_transition(_lora(0).function_status()['string_status']) == 'Last transition: -'


# ── camera_libcamera ─────────────────────────────────────────────────────────
def _camera(start_epoch, duration, next_epoch, paused=False):
    camera = cam.CustomModule.__new__(cam.CustomModule)
    camera.unique_id = 'cam-1'
    camera.tl_active = True
    camera.tl_pause = paused
    camera.tl_start_epoch = start_epoch
    camera.tl_start_str = 'SERVER-LOCAL-START'        # 파일 이름용 저장 문자열
    camera.tl_end_str = 'SERVER-LOCAL-END'
    camera.tl_duration_sec = duration
    camera.tl_period_sec = 600
    camera.tl_capture_number = 3
    camera.timer_loop = next_epoch
    return camera


@pytest.mark.parametrize('server_tz', ['UTC', 'Pacific/Honolulu'])
def test_camera_timelapse_times_are_in_the_place_clock(process_tz, server_tz):
    process_tz(server_tz)
    start = _epoch(2026, 11, 11, 0, 0)                   # 서울 09:00
    future = time.time() + 3600
    with _place('Asia/Seoul'):
        camera = _camera(start, 86400, future)
        text = camera.function_status()['string_status']
    assert 'Start: 2026-11-11 09:00:00' in text
    assert 'End: 2026-11-12 09:00:00' in text
    assert 'SERVER-LOCAL' not in text
    expected_next = datetime.fromtimestamp(future, pytz.timezone('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')
    assert f'Next Capture Time: {expected_next}' in text


def test_camera_falls_back_to_stored_strings_without_an_epoch():
    with _place('Asia/Seoul'):
        text = _camera(None, 86400, time.time() + 60).function_status()['string_status']
    assert 'Start: SERVER-LOCAL-START' in text and 'End: SERVER-LOCAL-END' in text


def test_camera_next_capture_dst_spring_forward():
    """뉴욕 2026-03-08 07:00Z 는 03:00 EDT(02:00 은 존재하지 않는다)."""
    future = _epoch(2026, 3, 8, 7, 0)
    with _place('America/New_York'), mock.patch.object(cam.time, 'time', return_value=future - 60):
        text = _camera(_epoch(2026, 3, 1), 86400 * 30, future).function_status()['string_status']
    assert 'Next Capture Time: 2026-03-08 03:00:00' in text
