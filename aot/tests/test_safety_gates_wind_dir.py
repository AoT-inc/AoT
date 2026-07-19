# coding=utf-8
"""G4 — SafetyPreGate 풍향 차등 폐쇄 검증."""
import pytest

from aot.functions.utils.env_control.safety_gates import (
    SafetyPreGate, PreGateConfig,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _opening(actuator_id, azimuth_deg=None):
    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='opening',
        azimuth_deg=azimuth_deg,
    )


def _make_env(wind=15.0, wind_dir=0.0, rain=0.0, T_int=25.0, T_ext=20.0):
    """기본: 강풍 (wind=15, threshold=12), 풍향 N(0°)."""
    import time
    now = time.time()
    return {
        'internal': {'T': T_int, 'RH': 60.0},
        'external': {'T': T_ext, 'RH': 60.0,
                     'wind': wind, 'wind_dir': wind_dir, 'rain': rain},
        'now_ts': now,
        'last_ext_ts': now,
        'last_int_ts': now,
    }


# ─── 풍향 차등 작동 ────────────────────────────────────────────────────────

def test_wind_only_with_dir_closes_windward_only():
    """강풍 N + opening N(azimuth=0)/S(azimuth=180): N만 폐쇄."""
    profiles = [
        _opening('north_vent', azimuth_deg=0.0),
        _opening('south_vent', azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0), profiles, 'test')
    assert res.partial is True
    assert res.triggered is False  # partial 모드는 triggered=False
    assert 'north_vent' in res.forced_commands
    assert 'south_vent' not in res.forced_commands
    assert res.forced_commands['north_vent']['value'] == 0.0


def test_wind_east_closes_east_only():
    profiles = [
        _opening('e_vent', azimuth_deg=90.0),
        _opening('w_vent', azimuth_deg=270.0),
        _opening('n_vent', azimuth_deg=0.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=90), profiles, 'test')
    assert res.partial is True
    assert 'e_vent' in res.forced_commands
    assert 'w_vent' not in res.forced_commands
    assert 'n_vent' not in res.forced_commands  # 90 ± 60 → N 안 들어감


def test_wind_arc_boundary_at_60_degrees():
    """default windward_arc=60°: 정확히 60° 차이는 경계 — 미포함."""
    profiles = [
        _opening('boundary', azimuth_deg=60.0),     # diff = 60° (경계)
        _opening('inside',   azimuth_deg=59.0),     # diff = 59° (포함)
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0), profiles, 'test')
    assert 'inside' in res.forced_commands
    assert 'boundary' not in res.forced_commands


# ─── Fallback: 정보 부족 → 보수적 일괄 폐쇄 ────────────────────────────────

def test_wind_dir_none_falls_back_to_close_all():
    profiles = [
        _opening('a', azimuth_deg=0.0),
        _opening('b', azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    env = _make_env(wind=15)
    env['external']['wind_dir'] = None
    res = gate.evaluate(env, profiles, 'test')
    assert res.partial is False
    assert res.triggered is True
    assert 'a' in res.forced_commands and res.forced_commands['a']['value'] == 0.0
    assert 'b' in res.forced_commands and res.forced_commands['b']['value'] == 0.0


def test_no_azimuth_falls_back_to_close_all():
    profiles = [
        _opening('a', azimuth_deg=None),   # azimuth 미설정
        _opening('b', azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0), profiles, 'test')
    assert res.partial is False
    assert 'a' in res.forced_commands
    assert 'b' in res.forced_commands


# ─── 다른 게이트 동시 발동 → 보수적 일괄 폐쇄 ──────────────────────────────

def test_wind_plus_rain_closes_all():
    profiles = [
        _opening('windward', azimuth_deg=0.0),
        _opening('leeward',  azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0, rain=1.0), profiles, 'test')
    # 강우 동시 → per_opening_mode 비활성 → 일괄 폐쇄
    assert res.partial is False
    assert res.triggered is True
    assert 'windward' in res.forced_commands
    assert 'leeward' in res.forced_commands


# ─── 비-opening kind 영향 안 받음 ──────────────────────────────────────────

def test_non_opening_kind_unaffected_by_per_opening_mode():
    from aot.functions.utils.env_control.types import ActuatorProfile
    profiles = [
        _opening('windward', azimuth_deg=0.0),
        ActuatorProfile(actuator_id='cooler1', kind='cooler'),
        ActuatorProfile(actuator_id='heater1', kind='heater'),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0), profiles, 'test')
    # cooler/heater 는 wind 명령 받지 않음
    assert 'cooler1' not in res.forced_commands
    assert 'heater1' not in res.forced_commands
    assert 'windward' in res.forced_commands


# ─── 정상 (강풍 미발동) → 게이트 발동 안 함 ─────────────────────────────

def test_normal_wind_no_trigger():
    profiles = [_opening('a', azimuth_deg=0.0)]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=5, wind_dir=0), profiles, 'test')
    assert res.triggered is False
    assert res.partial is False
    assert not res.forced_commands
