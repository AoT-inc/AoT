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
    REASON_LIMIT_HUMID_MAX, REASON_UNKNOWN, STRING_REASON_CODES,
    ch_coord_cmd, ch_coord_reason, ch_goal_target, ch_integral,
    ch_situation_deviation,
    write_cycle_metrics, write_final_commands,
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

    def test_vpd_deviation_channel(self):
        """VPD 직접 제어 모드에서는 CH30/31 이 0(온습도가 제어목표에서 빠짐)
        이라, 실제로 액추에이터를 움직이는 편차는 CH33 뿐이다 — 이 채널이
        빠지면 '왜 그 명령이 나왔는지'를 사후에 재구성할 방법이 없다
        (2026-08-29 영양 육묘장: VPD 편차와 반대로 난방기가 40분간 올라간
        사건을 로그로 못 잡았다)."""
        ctx = {
            'T_int': 29.0, 'RH_int': 65.0, 'VPD_int': 1.2, 'CO2_int': 700.0,
            'T_ext': 25.0, 'RH_ext': 70.0, 'wind': 0.0, 'wind_dir': 0.0, 'rain': 0.0,
        }
        deviation = {'vpd': 0.61}
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx=ctx, target={}, deviation=deviation,
                commands={}, limiting_factor=None, modes=[],
            )

        assert recorded[30] == pytest.approx(0.0), 'temperature 는 demote 돼 없음 — 0 이 맞다'
        assert recorded[31] == pytest.approx(0.0)
        assert recorded[33] == pytest.approx(0.61)

    def test_vpd_deviation_channel_defaults_to_zero_when_absent(self):
        """온습도 직접 제어 모드(VPD 미사용)에서는 CH33 이 0 — 값이 없다고
        채널 자체를 건너뛰면 '기록 안 됨'과 '편차 0'을 구분할 수 없다."""
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[channel] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_cycle_metrics(
                unique_id='fn', ctx={}, target={},
                deviation={'temperature': 1.0, 'humidity': -2.0},
                commands={}, limiting_factor=None, modes=[],
            )

        assert recorded[33] == pytest.approx(0.0)

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


class TestFinalCommandLoggingNeverBreaksTheCycle:
    """`write_final_commands` 는 `_dispatch` **앞**에 있다 — 여기서 예외가 나면
    이미 계산된 명령이 통째로 전송되지 않는다.

    2026-08-30 에 실제로 그랬다. 임계 오버라이드 헬퍼들은 근거를 문자열로
    남기는데(`{'value': 0.0, 'reason': 'humid_max'}`), 그것을 `float()` 에
    넘겨 ValueError 가 났다. 하필 **하드 임계가 걸린 그 사이클**의 명령이
    미실행됐다 — 안전 동작이 필요한 순간에 정확히 멈춘 것이다.
    """

    def _capture(self, final_cmds):
        recorded = {}

        def _fake_write(uid, meas, value, channel, extra_tags=None):
            recorded[meas] = value

        with patch(_PATCH_TARGET, side_effect=_fake_write):
            write_final_commands('fn', final_cmds, {'aaaaaaaa-1111': 0})
        return recorded

    def test_a_string_reason_does_not_raise(self):
        rec = self._capture({'aaaaaaaa-1111': {'value': 0.0,
                                               'reason': 'humid_max'}})
        assert rec['coord_actuator_aaaaaaaa_final'] == pytest.approx(0.0)
        assert rec['coord_actuator_aaaaaaaa_final_reason'] == pytest.approx(
            REASON_LIMIT_HUMID_MAX)

    def test_every_string_reason_in_the_codebase_is_mapped(self):
        """소스가 실제로 쓰는 문자열 근거 전수를 표와 대조한다.

        새 문자열 근거를 만들고 표에 안 넣으면 '근거 미상'으로 떨어져
        화면이 이유를 말하지 못한다 — 죽지는 않으니 조용하다.
        """
        import ast
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl \
            import _cycle_mixin
        tree = ast.parse(inspect.getsource(_cycle_mixin))
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == 'reason'
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)):
                    found.add(v.value)
        assert found, '문자열 근거를 하나도 못 찾았습니다 — 탐지가 깨졌습니다'
        assert found <= set(STRING_REASON_CODES), (
            '표에 없는 문자열 근거: %s' % sorted(found - set(STRING_REASON_CODES)))

    def test_an_unknown_reason_is_recorded_not_swallowed(self):
        rec = self._capture({'aaaaaaaa-1111': {'value': 5.0,
                                               'reason': 'brand_new_rule'}})
        assert rec['coord_actuator_aaaaaaaa_final_reason'] == pytest.approx(
            REASON_UNKNOWN)

    def test_a_broken_entry_does_not_stop_the_others(self):
        """한 액추에이터가 망가져도 나머지는 기록돼야 한다."""
        rec = self._capture({
            'aaaaaaaa-1111': {'value': 7.0, 'reason': 1},
            'bbbbbbbb-2222': None,
        })
        assert rec['coord_actuator_aaaaaaaa_final'] == pytest.approx(7.0)

    def test_a_non_numeric_value_is_skipped_quietly(self):
        rec = self._capture({'aaaaaaaa-1111': {'value': 'open',
                                               'reason': 1}})
        assert 'coord_actuator_aaaaaaaa_final' not in rec
