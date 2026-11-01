# coding=utf-8
"""G4 — SafetyPreGate 풍향 차등 폐쇄 검증.

2026-10-10 부터 풍향 차등은 강풍 **1단계**(10분 평균 ≥ 문턱×0.6, 근거 55)의 일이다.
2단계(문턱 이상)는 언제나 개구부를 전부 닫는다 — 예전의 "강풍 단독이면 풍상측만" 은
모든 개구부에 방위각이 있어야 섰고 현장에서 한 번도 서지 못했다(`safety_gates.classify_wind`).
"""
import pytest

from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_WIND, GATE_BIT_WIND_LIGHT, REASON_WIND_RESTRICT)
from aot.functions.utils.env_control.safety_gates import (
    WIND_ROOF_CAP_PCT, WIND_SIDE_CAP_PCT, PreGateConfig, SafetyPreGate,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _opening(actuator_id, azimuth_deg=None, vent_form='side'):
    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='opening',
        azimuth_deg=azimuth_deg,
        vent_form=vent_form,
    )


def _make_env(wind=8.0, wind_dir=0.0, rain=0.0, T_int=25.0, T_ext=20.0):
    """기본: 강풍 1단계 (wind=8, threshold=12 → 0.6×12=7.2 이상), 풍향 N(0°)."""
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


# ─── 풍향 차등 작동(1단계) ─────────────────────────────────────────────────

def test_wind_only_with_dir_closes_windward_only():
    """강풍 1단계 N + opening N(azimuth=0)/S(azimuth=180): N만 폐쇄, S 는 상한."""
    profiles = [
        _opening('north_vent', azimuth_deg=0.0),
        _opening('south_vent', azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind_dir=0), profiles, 'test')
    assert res.gate_mask & GATE_BIT_WIND_LIGHT and not res.gate_mask & GATE_BIT_WIND
    assert res.partial is True
    assert res.triggered is False  # partial 모드는 triggered=False
    assert res.forced_commands['north_vent']['value'] == 0.0
    assert res.forced_commands['north_vent']['reason'] == REASON_WIND_RESTRICT
    assert 'south_vent' not in res.forced_commands
    assert res.vent_caps['south_vent'] == pytest.approx(WIND_SIDE_CAP_PCT)
    assert res.vent_cap_reasons['south_vent'] == REASON_WIND_RESTRICT


def test_wind_east_closes_east_only():
    profiles = [
        _opening('e_vent', azimuth_deg=90.0),
        _opening('w_vent', azimuth_deg=270.0),
        _opening('n_vent', azimuth_deg=0.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind_dir=90), profiles, 'test')
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
    res = gate.evaluate(_make_env(wind_dir=0), profiles, 'test')
    assert 'inside' in res.forced_commands
    assert 'boundary' not in res.forced_commands


def test_leeward_roof_is_capped_not_closed():
    profiles = [_opening('roof_s', azimuth_deg=180.0, vent_form='ridge')]
    res = SafetyPreGate().evaluate(_make_env(wind_dir=0), profiles, 'test')
    assert 'roof_s' not in res.forced_commands
    assert res.vent_caps['roof_s'] == pytest.approx(WIND_ROOF_CAP_PCT)


# ─── 정보 부족 → 엄격한 쪽 ─────────────────────────────────────────────────

def test_wind_dir_none_closes_roof_and_caps_side():
    """풍향을 모르면 풍상측을 못 가린다 — 천창은 닫고 측창은 상한만(1단계)."""
    profiles = [
        _opening('side', azimuth_deg=0.0),
        _opening('roof', azimuth_deg=180.0, vent_form='ridge'),
    ]
    env = _make_env()
    env['external']['wind_dir'] = None
    res = SafetyPreGate().evaluate(env, profiles, 'test')
    assert res.partial is True
    assert res.forced_commands['roof']['value'] == 0.0
    assert 'side' not in res.forced_commands
    assert res.vent_caps['side'] == pytest.approx(WIND_SIDE_CAP_PCT)


def test_no_azimuth_side_is_capped_roof_is_closed():
    profiles = [
        _opening('a', azimuth_deg=None),                       # 측창, 방위각 미설정
        _opening('r', azimuth_deg=None, vent_form=None),       # 형태도 모름 → 천창
        _opening('b', azimuth_deg=180.0),                      # 풍하측
    ]
    res = SafetyPreGate().evaluate(_make_env(wind_dir=0), profiles, 'test')
    assert 'a' not in res.forced_commands
    assert res.vent_caps['a'] == pytest.approx(WIND_SIDE_CAP_PCT)
    assert res.forced_commands['r']['value'] == 0.0
    assert res.vent_caps['b'] == pytest.approx(WIND_SIDE_CAP_PCT)


# ─── 2단계 · 다른 게이트 동시 발동 → 일괄 폐쇄 ─────────────────────────────

def test_level2_closes_all_even_with_azimuth():
    profiles = [
        _opening('windward', azimuth_deg=0.0),
        _opening('leeward',  azimuth_deg=180.0),
    ]
    res = SafetyPreGate().evaluate(_make_env(wind=15, wind_dir=0), profiles, 'test')
    assert res.gate_mask & GATE_BIT_WIND
    assert res.partial is False and res.triggered is True
    assert res.forced_commands['windward']['value'] == 0.0
    assert res.forced_commands['leeward']['value'] == 0.0
    assert res.vent_caps == {}


def test_wind_plus_rain_closes_all():
    profiles = [
        _opening('windward', azimuth_deg=0.0),
        _opening('leeward',  azimuth_deg=180.0),
    ]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=15, wind_dir=0, rain=1.0), profiles, 'test')
    assert res.partial is False
    assert res.triggered is True
    assert 'windward' in res.forced_commands
    assert 'leeward' in res.forced_commands


# ─── 비-opening kind 영향 안 받음 ──────────────────────────────────────────

def test_non_opening_kind_unaffected_by_wind_restriction():
    profiles = [
        _opening('windward', azimuth_deg=0.0),
        ActuatorProfile(actuator_id='cooler1', kind='cooler'),
        ActuatorProfile(actuator_id='heater1', kind='heater'),
    ]
    res = SafetyPreGate().evaluate(_make_env(wind_dir=0), profiles, 'test')
    assert 'cooler1' not in res.forced_commands and 'cooler1' not in res.vent_caps
    assert 'heater1' not in res.forced_commands and 'heater1' not in res.vent_caps
    assert 'windward' in res.forced_commands


# ─── 정상 (강풍 미발동) → 게이트 발동 안 함 ─────────────────────────────

def test_normal_wind_no_trigger():
    profiles = [_opening('a', azimuth_deg=0.0)]
    gate = SafetyPreGate()
    res = gate.evaluate(_make_env(wind=5, wind_dir=0), profiles, 'test')
    assert res.triggered is False
    assert res.partial is False
    assert not res.forced_commands
    assert not res.vent_caps
