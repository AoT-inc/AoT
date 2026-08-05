# coding=utf-8
"""Unit tests for the LoRaWAN mode manager's operating-hours (day window) resolution.

고정 시각 기준과 태양시 기준을 모두 검증한다. 태양 커널은 스텁으로 갈아끼워
DB·위치 없이 분기만 본다(라이브 DB 대상 테스트 금지 규칙).
"""
from datetime import datetime, timedelta

import pytest
import pytz

from aot.functions.lorawan_mode_manager import (
    MODE_B,
    MODE_C,
    ModeOpts,
    compute_target_mode_period,
    resolve_day_window,
)

TARGET = 'cccccccc-0000-0000-0000-000000000000'


def _minute(hour, minute=0):
    return hour * 60 + minute


def _opts(**kwargs):
    base = dict(day_start_hour=4, day_end_hour=18, perf_lead_min=10)
    base.update(kwargs)
    return ModeOpts(**base)


# ---------------------------------------------------------------------------
# fixed — 기존 동작이 그대로여야 한다
# ---------------------------------------------------------------------------

def test_fixed_window_daytime():
    day, until = resolve_day_window(_opts(), _minute(10))
    assert day is True
    assert until == _minute(18)  # 다음 04시까지 18시간


def test_fixed_window_night():
    day, _until = resolve_day_window(_opts(), _minute(2))
    assert day is False


def test_fixed_window_wrapping_past_midnight():
    """종료 시각이 시작보다 이르면 자정을 넘긴 구간이다."""
    o = _opts(day_start_hour=20, day_end_hour=6)
    assert resolve_day_window(o, _minute(23))[0] is True
    assert resolve_day_window(o, _minute(3))[0] is True
    assert resolve_day_window(o, _minute(12))[0] is False


def test_fixed_window_equal_hours_means_all_day():
    o = _opts(day_start_hour=8, day_end_hour=8)
    assert resolve_day_window(o, _minute(3))[0] is True


def test_fixed_window_ignores_solar_offsets():
    o = _opts(sun_offset_start_min=600, sun_offset_end_min=-600)
    assert resolve_day_window(o, _minute(10))[0] is True


# ---------------------------------------------------------------------------
# solar — 위치의 일출~일몰
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_solar(monkeypatch):
    """태양 커널 스텁. state['day'] / state['next_sunrise'] 로 응답을 조종한다."""
    state = {'day': True, 'next_sunrise': None, 'seen': {}}

    def _is_daytime(target_id=None, at=None, start_offset_minutes=0, end_offset_minutes=0, **_kw):
        state['seen'].update(target_id=target_id, at=at,
                             start=start_offset_minutes, end=end_offset_minutes)
        return state['day']

    def _next_sun_event(kind, target_id=None, now=None, time_offset_minutes=0, **_kw):
        state['seen'].update(kind=kind, offset=time_offset_minutes)
        return state['next_sunrise']

    monkeypatch.setattr('aot.utils.solar.is_daytime', _is_daytime)
    monkeypatch.setattr('aot.utils.solar.next_sun_event', _next_sun_event)
    return state


def test_solar_window_uses_kernel(stub_solar):
    now = datetime(2026, 7, 31, 3, 0, tzinfo=pytz.utc)   # 12:00 KST
    stub_solar['day'] = True
    stub_solar['next_sunrise'] = now + timedelta(hours=17)

    o = _opts(day_window_mode='solar', sun_offset_start_min=-30, sun_offset_end_min=15)
    day, until = resolve_day_window(o, _minute(12), target_id=TARGET, now=now)

    assert day is True
    assert until == 17 * 60
    # 오프셋과 위치가 커널로 그대로 전달된다.
    assert stub_solar['seen']['target_id'] == TARGET
    assert stub_solar['seen']['start'] == -30
    assert stub_solar['seen']['end'] == 15
    assert stub_solar['seen']['kind'] == 'sunrise'


def test_solar_window_ignores_fixed_hours(stub_solar):
    """고정 시각으로는 야간인 시각이라도 태양시가 주간이면 주간이다."""
    now = datetime(2026, 6, 21, 20, 0, tzinfo=pytz.utc)  # 05:00 KST — 하지 무렵 이미 밝음
    stub_solar['day'] = True
    stub_solar['next_sunrise'] = now + timedelta(hours=24)

    o = _opts(day_window_mode='solar', day_start_hour=9, day_end_hour=17)
    assert resolve_day_window(o, _minute(5), target_id=TARGET, now=now)[0] is True


def test_solar_window_falls_back_to_fixed_when_unresolved(monkeypatch):
    """좌표를 못 구하면 운영시간을 잃지 않고 고정 시각으로 물러난다."""
    monkeypatch.setattr('aot.utils.solar.is_daytime', lambda **_kw: None)

    warnings = []
    logger = type('L', (), {'warning': lambda _self, msg: warnings.append(msg)})()

    o = _opts(day_window_mode='solar')
    day, until = resolve_day_window(o, _minute(10), target_id=TARGET, logger=logger)

    assert day is True                 # 고정 시각(04–18)의 10시 → 주간
    assert until == _minute(18)
    assert warnings and '고정 시각' in warnings[0]


def test_solar_window_falls_back_when_kernel_raises(monkeypatch):
    def _boom(**_kw):
        raise RuntimeError('astral 미설치')
    monkeypatch.setattr('aot.utils.solar.is_daytime', _boom)

    o = _opts(day_window_mode='solar')
    assert resolve_day_window(o, _minute(2), target_id=TARGET)[0] is False


# ---------------------------------------------------------------------------
# compute_target_mode_period 와의 결합 — 선행 전환(perf_lead_min) 포함
# ---------------------------------------------------------------------------

def _mode(o, now_minute, **kwargs):
    # 기본 전압은 "배터리는 넉넉하다" 는 뜻일 뿐이다. 리터럴(12.5V)을 박아 뒀더니
    # 임계값이 납산→인산철 4S 로 바뀌자(2026-08-04) 같은 값이 '치명'이 되어 이
    # 파일 전체가 깨졌다 — 배터리와 무관한 주/야간 테스트인데도. 기준을 옵션에서
    # 끌어와 임계값이 다시 바뀌어도 의미가 유지되게 한다.
    params = dict(vbat_V=ModeOpts().vbat_recover_v + 0.5,
                  now_hour=now_minute // 60, now_minute=now_minute,
                  valve_active=False, link_rssi=None, link_snr=None, o=o)
    params.update(kwargs)
    return compute_target_mode_period(**params)


def test_fixed_daytime_gives_performance_mode():
    mode, _period, reason = _mode(_opts(), _minute(10))
    assert mode == MODE_C
    assert reason == 'day_perf'


def test_fixed_night_gives_saving_mode():
    mode, _period, reason = _mode(_opts(), _minute(1))
    assert mode == MODE_B
    assert reason == 'night_b_guard'


def test_fixed_lead_switches_early():
    """운영 시작 5분 전이면 미리 성능 모드로 올린다."""
    mode, _period, reason = _mode(_opts(), _minute(3, 55))
    assert mode == MODE_C
    assert reason == 'day_perf_prefetch'


def test_fixed_lead_not_applied_when_always_on():
    """시작==종료(24시간 운영)는 선행 전환할 대상이 없다 — 이미 주간이다."""
    mode, _period, reason = _mode(_opts(day_start_hour=8, day_end_hour=8), _minute(3))
    assert mode == MODE_C
    assert reason == 'day_perf'


def test_solar_lead_switches_early_before_sunrise(stub_solar):
    """태양시 기준에서도 일출 직전이면 미리 성능 모드로 올린다."""
    now = datetime(2026, 7, 31, 20, 0, tzinfo=pytz.utc)
    stub_solar['day'] = False
    stub_solar['next_sunrise'] = now + timedelta(minutes=5)

    o = _opts(day_window_mode='solar')
    mode, _period, reason = _mode(o, _minute(5), target_id=TARGET, now=now)
    assert mode == MODE_C
    assert reason == 'day_perf_prefetch'


def test_solar_night_stays_in_saving_mode(stub_solar):
    now = datetime(2026, 7, 31, 16, 0, tzinfo=pytz.utc)
    stub_solar['day'] = False
    stub_solar['next_sunrise'] = now + timedelta(hours=6)

    o = _opts(day_window_mode='solar')
    mode, _period, reason = _mode(o, _minute(1), target_id=TARGET, now=now)
    assert mode == MODE_B
    assert reason == 'night_b_guard'


def test_battery_gate_still_wins_over_solar_daytime(stub_solar):
    """태양시가 주간이어도 배터리 임계 이하면 절전이 우선이다."""
    now = datetime(2026, 7, 31, 3, 0, tzinfo=pytz.utc)
    stub_solar['day'] = True
    stub_solar['next_sunrise'] = now + timedelta(hours=17)

    o = _opts(day_window_mode='solar')
    mode, _period, reason = _mode(o, _minute(12),
                                  vbat_V=ModeOpts().vbat_critical_v - 0.5,
                                  target_id=TARGET, now=now)
    assert mode == MODE_B
    assert reason == 'critical_battery_b_mode'
