# coding=utf-8
"""잎–공기 VPD 의 식 하나(`psychro.leaf_vpd`)와 그것을 저장하는 두 곳(`auto_vpd`·`AoT_VPD`).

증산을 미는 것은 svp(T_leaf) − RH·svp(T_air) 다. 공기 RH 를 잎 포화압에 곱한 옛 계산
(`sensorutils.calculate_vapor_pressure_deficit(엽온, RH)`)은 잎이 공기보다 찰 때 부풀고
(25 °C·70 %·잎 −1.5 °C: 0.87 대 0.68 kPa) 따뜻할 때 줄었다(30 °C·50 %·잎 +2: 2.38 대 2.63).
"""
import logging
import math

import pytest

from aot.functions.utils.env_control import psychro


# ─────────────────────────────────────────────────────────────────────────────
# 식
# ─────────────────────────────────────────────────────────────────────────────

class TestFormula:
    def test_cool_leaf_example(self):
        """25 °C · 70 % · 잎 −1.5 °C — 공기 0.95, 잎 0.68, 옛 계산 0.87 kPa."""
        assert psychro.vpd_from_rh(25.0, 70.0) == pytest.approx(0.95, abs=0.005)
        assert psychro.leaf_vpd(23.5, 25.0, 70.0) == pytest.approx(0.68, abs=0.005)
        old = (1 - 0.70) * psychro.svp(23.5)
        assert old == pytest.approx(0.87, abs=0.005)

    def test_warm_leaf_example(self):
        """30 °C · 50 % · 잎 +2.0 °C — 공기 2.12, 잎 2.63, 옛 계산 2.38 kPa."""
        assert psychro.vpd_from_rh(30.0, 50.0) == pytest.approx(2.12, abs=0.005)
        assert psychro.leaf_vpd(32.0, 30.0, 50.0) == pytest.approx(2.63, abs=0.005)
        assert (1 - 0.50) * psychro.svp(32.0) == pytest.approx(2.38, abs=0.005)

    def test_leaf_at_air_temperature_is_air_vpd(self):
        for T in (5.0, 18.0, 25.0, 38.0):
            for RH in (30.0, 60.0, 95.0):
                assert psychro.leaf_vpd(T, T, RH) == pytest.approx(
                    psychro.vpd_from_rh(T, RH), rel=1e-12)

    def test_condensing_leaf_is_zero_not_negative(self):
        assert psychro.leaf_vpd(10.0, 25.0, 90.0) == 0.0

    def test_translation_round_trips(self):
        """옮긴 공기 목표에서 공기를 맞추면 잎 VPD 가 원래 목표가 된다."""
        for T_air, T_leaf, v in ((25.0, 23.5, 0.8), (30.0, 32.0, 1.2), (18.0, 15.0, 0.5)):
            a = psychro.air_target_from_leaf(v, T_air, T_leaf)
            RH = 100.0 * (1.0 - a / psychro.svp(T_air))
            assert psychro.leaf_vpd(T_leaf, T_air, RH) == pytest.approx(v, abs=1e-9)

    def test_translation_direction(self):
        assert psychro.air_target_from_leaf(0.8, 25.0, 23.5) > 0.8   # 찬 잎 → 공기 목표 ↑
        assert psychro.air_target_from_leaf(0.8, 25.0, 27.0) < 0.8   # 따뜻한 잎 → ↓


# ─────────────────────────────────────────────────────────────────────────────
# 저장 계산 두 곳 — auto_vpd · AoT_VPD
# ─────────────────────────────────────────────────────────────────────────────

class TestStoredLeafVpd:
    def test_auto_vpd_uses_leaf_to_air(self, monkeypatch):
        from types import SimpleNamespace as NS
        from contextlib import contextmanager
        from aot.utils import auto_vpd as AV
        import aot.databases.utils as dbu

        rows = (NS(channel=0, unit='C'), NS(channel=1, unit='percent'), None,
                NS(channel=2), 1)
        monkeypatch.setattr(AV, '_classify_channels', lambda s, d: rows)

        @contextmanager
        def _scope(_path):
            yield NS(add=lambda r: None)
        monkeypatch.setattr(dbu, 'session_scope', _scope)
        out = AV._inject('dev', {0: {'value': 25.0, 'unit': 'C'},
                                  1: {'value': 70.0, 'unit': 'percent'}})
        assert out[2]['unit'] == 'kPa'
        assert out[2]['value'] == pytest.approx(0.68, abs=0.005)    # 옛 값 0.87

    @pytest.mark.parametrize('leaf_bound, expect_kpa', [
        (True, 0.68),      # 엽온 23.5 °C 를 잰 경우
        (False, 0.68),     # 엽온이 없어 오프셋 −1.5 °C 로 어림한 경우 — 같은 식
    ])
    def test_aot_vpd_function_stores_leaf_to_air_in_pa(self, monkeypatch, leaf_bound,
                                                      expect_kpa):
        from types import SimpleNamespace as NS
        from aot.functions import AoT_VPD as M
        stored = []
        values = {'t': 25.0, 'h': 70.0, 'l': 23.5}
        monkeypatch.setattr(M, 'get_measurement', lambda mid: NS(conversion_id='c'))
        monkeypatch.setattr(M, 'db_retrieve_table_daemon', lambda *a, **k: None)
        monkeypatch.setattr(M, 'return_measurement_info',
                            lambda dm, conv: (0, 'Pa' if dm == 'vpd' else 'x', 'm'))
        monkeypatch.setattr(M, 'convert_from_x_to_y_unit', lambda a, b, v: v)
        monkeypatch.setattr(M, 'add_measurements_influxdb',
                            lambda uid, d: stored.append(d[0]['value']))
        c = M.CustomModule.__new__(M.CustomModule)
        c.logger = logging.getLogger('test_aot_vpd')
        c.unique_id = 'f'
        c.timer_loop = 0.0
        c.period = 60
        c.channels_measurement = {0: 'vpd'}
        c.channels_conversion = {0: None}
        c.select_measurement_temperature_c_device_id = 'd'
        c.select_measurement_temperature_c_measurement_id = 't'
        c.select_measurement_humidity_device_id = 'd'
        c.select_measurement_humidity_measurement_id = 'h'
        c.select_measurement_leaf_temp_device_id = 'd' if leaf_bound else None
        c.select_measurement_leaf_temp_measurement_id = 'l' if leaf_bound else None
        c.max_measure_age_temperature_c = c.max_measure_age_humidity = 360
        c.max_measure_age_leaf_temp = 360
        c.leaf_temp_offset = -1.5
        c.get_last_measurement = lambda dev, mid, max_age=None: (
            (1.0, values[mid]) if mid else None)
        c.loop()
        assert stored and stored[0] == pytest.approx(expect_kpa * 1000.0, abs=5.0)   # Pa


def test_sensorutils_formula_is_untouched_for_air_vpd_drivers():
    """센서 드라이버는 같은 T/RH 로 공기 VPD 를 낸다 — 이 식은 그대로 둔다."""
    from aot.inputs.sensorutils import calculate_vapor_pressure_deficit as cvpd
    assert cvpd(25.0, 70.0) / 1000.0 == pytest.approx(psychro.vpd_from_rh(25.0, 70.0),
                                                      rel=2e-3)
    assert math.isclose(cvpd(25.0, 100.0), 0.0, abs_tol=1e-9)
