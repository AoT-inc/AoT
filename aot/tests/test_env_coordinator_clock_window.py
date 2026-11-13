# coding=utf-8
"""env_coordinator 운전 시간창·야간 파킹 시각은 `HH:MM` 을 **분 단위로** 읽고 저장 단계에서 거른다.

2026-11-11 함수 상태 위젯 점검에서 재현된 결함: `time_start`/`time_end` 가 자유 텍스트라
`'6:00'` 이 그대로 저장됐고, `_in_time_window` 가 `'HH:MM'` 문자열을 사전식으로 비교해
`'6:00' > '20:00'` → 창이 자정 넘는 구간으로 뒤집혀 00:00~05:59 가 "창 안" 이 되었다.
(야간 파킹 시각 `night_vent_start/end` 도 같은 비교였다.)

고정하는 것:
  - 읽는 쪽: 자리를 안 맞춘 값(`'6:00'`)도 분 단위로 바르게 비교한다.
  - 자정을 넘는 창(22:00~06:00)과 시설 시간대·DST 경계에서의 현지 시각 판정은 그대로다.
  - 쓰는 쪽: 시각이 아닌 값은 저장을 거부한다(`constraints_pass_hhmm`) — 위젯 상세 모달과
    일반 편집 페이지가 같은 검사(`custom_options_return_json`)를 지난다.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from aot.functions.custom_functions.env_coordinator_impl._function_info import (
    FUNCTION_INFORMATION)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin)
from aot.utils import clock_hhmm as ck
from aot.utils.constraints_pass import constraints_pass_hhmm


class _Coord(HelpersMixin):
    """믹스인의 시각 판정만 쓰는 최소 스텁."""

    def __init__(self, window, now_local=None, **attrs):
        self.logger = mock.Mock()
        self._window = window
        if now_local is not None:        # 없으면 믹스인의 실제 `_facility_local_now` 를 쓴다
            self._facility_local_now = lambda: now_local
        self.photo_method_id_device_id = ''
        self.time_start, self.time_end = window
        for k, v in attrs.items():
            setattr(self, k, v)



def _inside(window, hour, minute=0):
    c = _Coord(window, datetime(2026, 11, 11, hour, minute))
    return c._in_time_window()


# ── 파서 ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('text,minutes', [
    ('06:00', 360), ('6:00', 360), (' 6:05 ', 365), ('23:59', 1439),
    ('24:00', 1440), ('06:00:30', 360),
])
def test_parse_accepts_unpadded_and_seconds(text, minutes):
    assert ck.parse_hhmm(text) == minutes


@pytest.mark.parametrize('text', [
    '', None, 'abc', '25:00', '24:01', '6', '6:5', '12:60', '-1:00', '06-00'])
def test_parse_rejects_non_times(text):
    assert ck.parse_hhmm(text) is None


def test_normalize_pads():
    assert ck.normalize_hhmm('6:00') == '06:00'
    assert ck.normalize_hhmm('x') is None


# ── 읽는 쪽: 운전 시간창 ──────────────────────────────────────────────────────
def test_unpadded_start_no_longer_flips_the_window():
    """'6:00'~'20:00' 이면 05:00 은 창 밖이다(예전엔 사전식 비교로 '창 안')."""
    window = ('6:00', '20:00')
    assert _inside(window, 5, 0) is False
    assert _inside(window, 3, 30) is False
    assert _inside(window, 6, 0) is True
    assert _inside(window, 10, 30) is True
    assert _inside(window, 20, 0) is True
    assert _inside(window, 20, 1) is False
    assert _inside(window, 23, 0) is False


def test_padded_and_unpadded_agree_everywhere():
    for hour in range(24):
        for minute in (0, 30, 59):
            assert _inside(('6:00', '20:00'), hour, minute) == \
                _inside(('06:00', '20:00'), hour, minute)


def test_overnight_window_is_kept():
    """자정을 넘는 창(22:00~06:00)은 기존 동작 그대로."""
    window = ('22:00', '06:00')
    assert _inside(window, 23, 30) is True
    assert _inside(window, 3, 0) is True
    assert _inside(window, 6, 0) is True
    assert _inside(window, 6, 1) is False
    assert _inside(window, 12, 0) is False
    assert _inside(('22:00', '6:00'), 3, 0) is True       # 끝 시각이 자리 안 맞춤


def test_unreadable_stored_value_falls_back_to_default_and_logs_once():
    c = _Coord(('abc', '20:00'), datetime(2026, 11, 11, 5, 0))
    assert c._in_time_window() is False                    # 시작 기본값 06:00 → 05:00 은 밖
    c._facility_local_now = lambda: datetime(2026, 11, 11, 10, 0)
    assert c._in_time_window() is True
    assert c.logger.error.call_count == 1                  # 사이클마다 찍지 않는다


# ── 시설 현지 시각(시간대·DST)은 그대로 ────────────────────────────────────────
def _at_utc(window, tz_name, utc_dt):
    c = _Coord(window)
    c._get_facility_tz = lambda: ZoneInfo(tz_name)
    with mock.patch('aot.utils.timekit.utc_now', return_value=utc_dt):
        return c._in_time_window()


def test_window_follows_facility_timezone():
    utc = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)   # 서울 05:00(다음 날)
    assert _at_utc(('6:00', '20:00'), 'Asia/Seoul', utc) is False
    assert _at_utc(('6:00', '20:00'), 'America/New_York', utc) is True   # 뉴욕 15:00


def test_window_edge_on_dst_fall_back_day():
    """뉴욕 2026-11-01 은 06:00Z 에 01:00 EDT → 01:00 EST 로 되돌아간다."""
    before = datetime(2026, 11, 1, 10, 59, tzinfo=timezone.utc)  # 05:59 EST
    after = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)    # 06:00 EST
    assert _at_utc(('6:00', '20:00'), 'America/New_York', before) is False
    assert _at_utc(('6:00', '20:00'), 'America/New_York', after) is True


def test_window_edge_on_dst_spring_forward_day():
    """뉴욕 2026-03-08 은 07:00Z 에 02:00 EST → 03:00 EDT 로 건너뛴다."""
    before = datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)    # 01:59 EST
    after = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)      # 03:00 EDT
    assert _at_utc(('3:00', '20:00'), 'America/New_York', before) is False
    assert _at_utc(('3:00', '20:00'), 'America/New_York', after) is True


# ── 읽는 쪽: 야간 파킹 시각(clock 기준) ────────────────────────────────────────
def _night(start, end, hour, minute=0):
    c = _Coord(('06:00', '20:00'), datetime(2026, 11, 11, hour, minute),
               night_vent_basis='clock', night_vent_start=start, night_vent_end=end)
    return c._night_vent_clock()


def test_night_clock_unpadded_start_is_night_in_the_evening():
    """'8:00'~'06:00' 이면 19:00 은 밤이다(예전엔 사전식 비교로 '밤 아님')."""
    assert _night('8:00', '06:00', 19)[0] is True
    assert _night('8:00', '06:00', 23)[0] is True
    assert _night('8:00', '06:00', 3)[0] is True
    assert _night('8:00', '06:00', 7)[0] is False
    assert _night('08:00', '06:00', 19)[0] is True


def test_night_clock_keeps_default_overnight_and_taper():
    assert _night('18:00', '06:00', 20)[0] is True
    assert _night('18:00', '06:00', 12)[0] is False
    in_night, until = _night('18:00', '06:00', 17, 55)      # 파킹 시작 5분 전
    assert in_night is False and until == pytest.approx(300.0)
    assert _night('18:00', '06:00', 12)[1] is None           # 먼 낮에는 완충 구간 아님
    assert _night('6:00', '18:00', 5, 55)[1] == pytest.approx(300.0)


# ── 쓰는 쪽: 저장 검사 ────────────────────────────────────────────────────────
@pytest.mark.parametrize('text', ['06:00', '6:00', '24:00', '', None])
def test_constraint_accepts_times_and_empty(text):
    assert constraints_pass_hhmm(None, text)[0] is True


@pytest.mark.parametrize('text', ['abc', '25:00', '6', '12:60', '06-00'])
def test_constraint_rejects_non_times(text):
    ok, errors, _ = constraints_pass_hhmm(None, text)
    assert ok is False and errors


def test_the_four_time_options_use_the_constraint():
    by_id = {o['id']: o for o in FUNCTION_INFORMATION['custom_options'] if o.get('id')}
    for option_id in ('time_start', 'time_end', 'night_vent_start', 'night_vent_end'):
        assert by_id[option_id]['constraints_pass'] is constraints_pass_hhmm, option_id


def test_save_path_rejects_bad_time_for_both_editors():
    """위젯 모달과 일반 편집 페이지가 쓰는 `custom_options_return_json` 이 거부한다."""
    from werkzeug.datastructures import MultiDict
    from aot.aot_flask.utils.utils_general import custom_options_return_json

    info = {'env_coordinator': FUNCTION_INFORMATION}
    device = SimpleNamespace(device='env_coordinator')
    for value, expect_error in (('6:00', False), ('06:30', False), ('abc', True), ('25:99', True)):
        errors, saved = custom_options_return_json(
            [], info, request_form=MultiDict({'time_start': value}),
            mod_dev=device, device='env_coordinator', use_defaults=False,
            custom_options={})
        assert bool(errors) is expect_error, (value, errors)
        stored = __import__('json').loads(saved).get('time_start')
        assert (stored == value) == (not expect_error), (value, stored)
