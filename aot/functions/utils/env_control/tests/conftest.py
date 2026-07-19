# coding=utf-8
"""
공용 픽스처 — env_control 단위 테스트.

모든 외부 의존성(InfluxDB, DB, 시계)을 mock으로 격리한다.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List
from unittest.mock import patch, MagicMock

import pytest

from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, EnvTarget,
    ManualLockState, TargetVar,
)


# ─────────────────────────────────────────────────────────────────────────────
# InfluxDB mock — 테스트 내 모든 write 를 무시
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_influx(monkeypatch):
    """write_influxdb_value 를 no-op 으로 교체해 DB 없이 실행."""
    monkeypatch.setattr(
        'aot.utils.influx.write_influxdb_value',
        lambda *a, **kw: None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 고정 시계 픽스처
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def fixed_ts():
    """테스트마다 동일한 epoch(정오 2026-01-01) 반환."""
    return 1767240000.0  # 2026-01-01 12:00:00 UTC


# ─────────────────────────────────────────────────────────────────────────────
# 기본 EnvContext 팩토리
# ─────────────────────────────────────────────────────────────────────────────

def make_ctx(
    T_int: float = 22.0,
    RH_int: float = 65.0,
    CO2_int: float = 600.0,
    T_ext: float = 25.0,
    RH_ext: float = 55.0,
    wind: float = 2.0,
    rain: float = 0.0,
    solar: float = 400.0,
    VPD_int: float = None,
    cycle_sec: float = 60.0,
    now_ts: float = None,
) -> dict:
    import math

    def svp(T):
        return 0.6108 * math.exp(17.27 * T / (T + 237.3))

    vpd = VPD_int if VPD_int is not None else (1 - RH_int / 100) * svp(T_int)
    return {
        'T_int': T_int, 'RH_int': RH_int, 'CO2_int': CO2_int, 'VPD_int': vpd,
        'T_ext': T_ext, 'RH_ext': RH_ext, 'CO2_ext': 400.0,
        'wind': wind, 'rain': rain, 'solar': solar, 'dewpoint': 10.0,
        'now_ts': now_ts or 1767240000.0,
        'cycle_sec': cycle_sec,
        'last_ext_ts': (now_ts or 1767240000.0) - 30,
        'last_int_ts': (now_ts or 1767240000.0) - 30,
        'internal': {'T': T_int, 'RH': RH_int, 'CO2': CO2_int},
        'external': {'T': T_ext, 'RH': RH_ext, 'wind': wind, 'rain': rain, 'solar': solar},
    }


@pytest.fixture
def ctx():
    """대표 정상 환경 컨텍스트."""
    return make_ctx()


# ─────────────────────────────────────────────────────────────────────────────
# 기본 EnvTarget 팩토리
# ─────────────────────────────────────────────────────────────────────────────

def make_target(
    vpd: float = 1.2,
    vpd_tol: float = 0.1,
    T: float = None,
    RH: float = None,
    co2: float = None,
) -> EnvTarget:
    t: EnvTarget = {}
    t['vpd'] = TargetVar(value=vpd, tolerance=vpd_tol, priority=1.0, unit='kPa')
    if T is not None:
        t['temperature'] = TargetVar(value=T, tolerance=1.0, priority=0.8)
    if RH is not None:
        t['humidity'] = TargetVar(value=RH, tolerance=5.0, priority=0.8)
    if co2 is not None:
        t['co2'] = TargetVar(value=co2, tolerance=50.0, priority=0.5)
    return t


@pytest.fixture
def target():
    """VPD=1.2 kPa 기본 목표."""
    return make_target(vpd=1.2)


# ─────────────────────────────────────────────────────────────────────────────
# ActuatorProfile 팩토리
# ─────────────────────────────────────────────────────────────────────────────

def make_opening_profile(
    actuator_id: str = 'vent_01',
    area_m2: float = 10.0,
    azimuth_deg: float = 90.0,
) -> ActuatorProfile:
    """냉각·제습 방향 단일 개구부 프로필."""
    from aot.functions.utils.env_control.effect_functions import opening_temp_effect, opening_humid_effect

    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='opening',
        effect_model={
            'temperature': opening_temp_effect,
            'humidity': opening_humid_effect,
        },
        cmd_constraints=CmdConstraints(slew_per_cycle=20.0, min_on_pct=5.0),
        gains={'kp': 1.0, 'ki': 0.05},
        safe_default=0.0,
        area_m2=area_m2,
        azimuth_deg=azimuth_deg,
    )


def make_heater_profile(actuator_id: str = 'heater_01') -> ActuatorProfile:
    from aot.functions.utils.env_control.effect_functions import heater_temp_effect, heater_humid_effect

    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='heater',
        effect_model={
            'temperature': heater_temp_effect,
            'humidity': heater_humid_effect,
        },
        cmd_constraints=CmdConstraints(slew_per_cycle=20.0, min_on_pct=5.0),
        gains={'kp': 1.0, 'ki': 0.05},
        safe_default=0.0,
    )
