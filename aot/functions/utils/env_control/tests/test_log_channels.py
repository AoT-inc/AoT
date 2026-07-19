# coding=utf-8
"""
log_channels.py 단위 테스트.

대상:
  - write_cycle_metrics: 사이클당 InfluxDB 기록 채널 매핑
  - 채널 번호 계산 헬퍼 (ch_goal_target, ch_coord_cmd, ...)
"""

from unittest.mock import patch

import pytest

from aot.functions.utils.env_control.coordinator import ActuatorCommand
from aot.functions.utils.env_control.log_channels import (
    CH_COORD_CMD_BASE, CH_COORD_REASON_BASE, CH_INTEGRAL_BASE,
    CH_SITUATION_DEV_BASE,
    ch_coord_cmd, ch_coord_reason, ch_goal_target, ch_integral,
    ch_situation_deviation,
    write_cycle_metrics,
)

from .conftest import make_ctx, make_target


# ─────────────────────────────────────────────────────────────────────────────
# 채널 번호 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

class TestChannelHelpers:
    def test_goal_target_temperature(self):
        assert ch_goal_target('temperature') == 0

    def test_goal_target_humidity(self):
        assert ch_goal_target('humidity') == 1

    def test_coord_cmd_index0(self):
        assert ch_coord_cmd(0) == CH_COORD_CMD_BASE

    def test_coord_cmd_index1(self):
        assert ch_coord_cmd(1) == CH_COORD_CMD_BASE + 2

    def test_coord_reason_index0(self):
        assert ch_coord_reason(0) == CH_COORD_REASON_BASE

    def test_situation_deviation_co2(self):
        assert ch_situation_deviation('co2') == CH_SITUATION_DEV_BASE + 2

    def test_integral_vpd_index(self):
        """vpd → VAR_INDEX=3 → CH_INTEGRAL_BASE + 3."""
        assert ch_integral('vpd') == CH_INTEGRAL_BASE + 3

    def test_integral_unknown_fallback(self):
        """알 수 없는 var → fallback 인덱스 9."""
        assert ch_integral('unknown_var') == CH_INTEGRAL_BASE + 9


# ─────────────────────────────────────────────────────────────────────────────
# write_cycle_metrics
# ─────────────────────────────────────────────────────────────────────────────

_PATCH_TARGET = 'aot.functions.utils.env_control.log_channels.write_influxdb_value'


def _make_actuator_command(value: float = 50.0, reason: int = 1):
    return ActuatorCommand(value=value, reason=reason)


class TestWriteCycleMetrics:
    """write_cycle_metrics 가 올바른 채널에 InfluxDB 를 기록하는지 검증."""

    def test_calls_write_influx_each_cycle(self):
        """호출 시 write_influxdb_value 가 최소 1회 이상 호출된다."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        target = make_target(vpd=1.2)
        commands = {'vent_01': _make_actuator_command(30.0)}
        deviation = {'temperature': 0.5, 'humidity': -3.0}

        with patch(_PATCH_TARGET) as mock_write:
            write_cycle_metrics(
                unique_id='test-fn',
                ctx=ctx,
                target=target,
                deviation=deviation,
                commands=commands,
                limiting_factor=None,
                modes=['cooling'],
            )
        assert mock_write.call_count >= 1

    def test_no_raw_sensor_channels(self):
        """raw 센서 값(내부/외부)은 기록하지 않는다 — Input/Output 이 이미 기록.

        과거에는 CH 0~3(내부), CH 10~14(외부)에 센서값을 중복 기록했으나
        '이미 기록된 데이터는 다시 저장하지 않는다' 정책으로 제거됨.
        """
        ctx = {
            'T_int': 23.5, 'RH_int': 60.0, 'VPD_int': 1.1, 'CO2_int': 700.0,
            'T_ext': 30.0, 'RH_ext': 40.0, 'wind': 8.5, 'wind_dir': 270.0, 'rain': 0.0,
        }
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation={},
                commands={}, limiting_factor=None, modes=[],
            )

        # 센서 raw 채널(0~14)에는 아무것도 기록되지 않아야 한다
        for ch in range(0, 15):
            assert ch not in recorded

    def test_target_channels(self):
        """목표값이 CH 20~23 에 기록된다 (VPD, T, RH, CO2)."""
        target = make_target(vpd=1.2, T=24.0, RH=60.0, co2=800.0)
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx={}, target=target, deviation={},
                commands={}, limiting_factor=None, modes=[],
            )

        assert recorded[20] == pytest.approx(1.2)    # VPD target
        assert recorded[21] == pytest.approx(24.0)   # T target
        assert recorded[22] == pytest.approx(60.0)   # RH target
        assert recorded[23] == pytest.approx(800.0)  # CO2 target

    def test_priority_channels(self):
        """우선순위가 CH 24~27 에 기록된다 (goal_priority 통합 — 중복 제거)."""
        target = make_target(vpd=1.2, T=24.0, RH=60.0, co2=800.0)
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx={}, target=target, deviation={},
                commands={}, limiting_factor=None, modes=[],
            )

        assert recorded[24] == pytest.approx(1.0)   # VPD priority
        assert recorded[25] == pytest.approx(0.8)   # T priority
        assert recorded[26] == pytest.approx(0.8)   # RH priority
        assert recorded[27] == pytest.approx(0.5)   # CO2 priority

    def test_deviation_channels(self):
        """편차가 CH 30~32 에 기록된다."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        deviation = {'temperature': 2.5, 'humidity': -5.0, 'co2': 100.0}
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation=deviation,
                commands={}, limiting_factor=None, modes=[],
            )

        assert recorded[30] == pytest.approx(2.5)
        assert recorded[31] == pytest.approx(-5.0)
        assert recorded[32] == pytest.approx(100.0)

    def test_mode_channel_cooling(self):
        """cooling 모드 → CH 72 = 1."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation={},
                commands={}, limiting_factor=None, modes=['cooling'],
            )

        assert recorded[72] == pytest.approx(1.0)  # MODE_CODES['cooling'] = 1

    def test_limiting_factor_channel(self):
        """limiting_factor='co2' → CH 71 = 2."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation={},
                commands={}, limiting_factor='co2', modes=[],
            )

        assert recorded[71] == pytest.approx(2.0)  # LIMIT_CODES['co2'] = 2

    def test_facility_id_passed_as_extra_tag(self):
        """facility_id 지정 시 extra_tags 로 전달된다."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        tags_seen = []

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            tags_seen.append(extra_tags)

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation={},
                commands={}, limiting_factor=None, modes=[],
                facility_id='facility-abc',
            )

        assert all(t == {'facility_id': 'facility-abc'} for t in tags_seen)

    def test_no_facility_id_no_extra_tag(self):
        """facility_id=None 이면 extra_tags 없음."""
        ctx = {
            'T_int': 22.0, 'RH_int': 65.0, 'VPD_int': 0.94, 'CO2_int': 600.0,
            'T_ext': 25.0, 'RH_ext': 55.0, 'wind': 2.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        tags_seen = []

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            tags_seen.append(extra_tags)

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation={},
                commands={}, limiting_factor=None, modes=[],
                facility_id=None,
            )

        assert all(t is None for t in tags_seen)
