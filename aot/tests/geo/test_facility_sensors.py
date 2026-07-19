# coding=utf-8
"""Tests for facility_sensors.py — sensor aggregation & validation."""
import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _binding(role='indoor_temp', device_id='dev-1', measurement_id='dm-1',
             name='Sensor A', weight=1.0):
    return {'role': role, 'device_id': device_id,
            'measurement_id': measurement_id, 'name': name, 'weight': weight}


# ─────────────────────────────────────────────────────────────────────────────
# validate_sensor_binding
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateSensorBinding:
    from aot.aot_flask.geo.facility_sensors import validate_sensor_binding

    def test_valid(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding())
        assert ok
        assert reason == 'ok'

    def test_missing_role(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(role=''))
        assert not ok
        assert 'role' in reason

    def test_missing_device_id(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(device_id=''))
        assert not ok
        assert 'device_id' in reason

    def test_missing_measurement_id(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(measurement_id=''))
        assert not ok
        assert 'measurement_id' in reason

    def test_unknown_role(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(role='unknown_role'))
        assert not ok
        assert 'unknown role' in reason

    def test_weight_zero(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(weight=0))
        assert not ok
        assert 'weight' in reason

    def test_weight_negative(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(weight=-1))
        assert not ok

    def test_weight_non_numeric(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, reason = validate_sensor_binding(_binding(weight='heavy'))
        assert not ok

    def test_weight_optional(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        b = _binding()
        del b['weight']
        ok, _ = validate_sensor_binding(b)
        assert ok

    @pytest.mark.parametrize('role', [
        'indoor_temp', 'indoor_humidity', 'indoor_co2',
        'outdoor_temp', 'outdoor_humidity',
        'outdoor_wind', 'outdoor_wind_dir', 'outdoor_solar',
    ])
    def test_all_known_roles(self, role):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_binding
        ok, _ = validate_sensor_binding(_binding(role=role))
        assert ok


class TestValidateSensorBindings:
    def test_empty_list(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_bindings
        ok, errors = validate_sensor_bindings([])
        assert ok
        assert errors == []

    def test_not_a_list(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_bindings
        ok, errors = validate_sensor_bindings({'role': 'indoor_temp'})
        assert not ok
        assert errors

    def test_mixed_valid_invalid(self):
        from aot.aot_flask.geo.facility_sensors import validate_sensor_bindings
        bindings = [_binding(), _binding(role='')]
        ok, errors = validate_sensor_bindings(bindings)
        assert not ok
        assert len(errors) == 1
        assert 'sensors[1]' in errors[0]


# ─────────────────────────────────────────────────────────────────────────────
# read_facility_sensors
# ─────────────────────────────────────────────────────────────────────────────

class TestReadFacilitySensors:
    """Mock get_last_measurement to avoid InfluxDB dependency."""

    def _run(self, bindings, measurement_map, max_age=300):
        """measurement_map: {(device_id, measurement_id): (ts, value)}"""
        from aot.aot_flask.geo.facility_sensors import read_facility_sensors

        def fake_get_last(device_id, measurement_id, max_age=None):
            key = (device_id, measurement_id)
            return measurement_map.get(key, [None, None])

        with patch('aot.aot_flask.geo.facility_sensors.get_last_measurement',
                   side_effect=fake_get_last):
            return read_facility_sensors(bindings, max_age=max_age)

    # ── Basic cases ─────────────────────────────────────────────────────────

    def test_empty_bindings(self):
        result = self._run([], {})
        assert result['indoor']['temp_c'] is None
        assert result['outdoor']['wind_ms'] is None
        assert result['valid_count'] == 0
        assert result['total_count'] == 0
        assert not result['degraded']

    def test_single_valid_sensor(self):
        bindings = [_binding(role='indoor_temp', device_id='d1', measurement_id='m1')]
        result = self._run(bindings, {('d1', 'm1'): (1000.0, 22.5)})
        assert result['indoor']['temp_c'] == pytest.approx(22.5)
        assert result['valid_count'] == 1
        assert result['total_count'] == 1
        assert not result['degraded']

    def test_no_data_sensor(self):
        bindings = [_binding(role='indoor_temp', device_id='d1', measurement_id='m1')]
        result = self._run(bindings, {})  # no data at all
        assert result['indoor']['temp_c'] is None
        assert result['valid_count'] == 0
        assert result['total_count'] == 1
        assert result['degraded']
        assert result['sensors'][0]['degraded_reason'] == 'no_data'

    def test_stale_sensor(self):
        # max_age query → None, unlimited query → has value (stale)
        bindings = [_binding(role='indoor_temp', device_id='d1', measurement_id='m1')]
        call_results = {}
        def fake_get_last(device_id, measurement_id, max_age=None):
            if max_age is not None:
                return [None, None]   # stale — outside max_age
            return [900.0, 21.0]      # unlimited — data exists but old

        from aot.aot_flask.geo.facility_sensors import read_facility_sensors
        with patch('aot.aot_flask.geo.facility_sensors.get_last_measurement',
                   side_effect=fake_get_last):
            result = read_facility_sensors(bindings, max_age=60)

        assert result['indoor']['temp_c'] is None
        assert result['sensors'][0]['stale'] is True
        assert result['degraded']

    # ── Multiple sensors, same role ──────────────────────────────────────────

    def test_two_sensors_equal_weight(self):
        bindings = [
            _binding(role='indoor_temp', device_id='d1', measurement_id='m1', weight=1.0),
            _binding(role='indoor_temp', device_id='d2', measurement_id='m2', weight=1.0),
        ]
        result = self._run(bindings, {
            ('d1', 'm1'): (1000.0, 20.0),
            ('d2', 'm2'): (1000.0, 24.0),
        })
        assert result['indoor']['temp_c'] == pytest.approx(22.0)
        assert result['valid_count'] == 2

    def test_two_sensors_unequal_weight(self):
        bindings = [
            _binding(role='indoor_temp', device_id='d1', measurement_id='m1', weight=3.0),
            _binding(role='indoor_temp', device_id='d2', measurement_id='m2', weight=1.0),
        ]
        result = self._run(bindings, {
            ('d1', 'm1'): (1000.0, 20.0),
            ('d2', 'm2'): (1000.0, 28.0),
        })
        # (20*3 + 28*1) / 4 = 88/4 = 22.0
        assert result['indoor']['temp_c'] == pytest.approx(22.0)

    def test_one_of_two_stale_uses_remaining(self):
        bindings = [
            _binding(role='indoor_temp', device_id='d1', measurement_id='m1', weight=1.0),
            _binding(role='indoor_temp', device_id='d2', measurement_id='m2', weight=1.0),
        ]
        result = self._run(bindings, {
            ('d1', 'm1'): (1000.0, 20.0),
            # d2 has no data → stale/no_data
        })
        # Only d1 is valid; use its value directly
        assert result['indoor']['temp_c'] == pytest.approx(20.0)
        assert result['valid_count'] == 1
        assert result['total_count'] == 2
        assert result['degraded']

    # ── Multiple roles ───────────────────────────────────────────────────────

    def test_multiple_roles_independent(self):
        bindings = [
            _binding(role='indoor_temp',     device_id='d1', measurement_id='m1'),
            _binding(role='indoor_humidity', device_id='d2', measurement_id='m2'),
            _binding(role='indoor_co2',      device_id='d3', measurement_id='m3'),
        ]
        result = self._run(bindings, {
            ('d1', 'm1'): (1000.0, 23.0),
            ('d2', 'm2'): (1000.0, 65.0),
            ('d3', 'm3'): (1000.0, 800.0),
        })
        assert result['indoor']['temp_c']       == pytest.approx(23.0)
        assert result['indoor']['humidity_pct'] == pytest.approx(65.0)
        assert result['indoor']['co2_ppm']      == pytest.approx(800.0)

    def test_outdoor_roles(self):
        bindings = [
            _binding(role='outdoor_temp',    device_id='d1', measurement_id='m1'),
            _binding(role='outdoor_wind',    device_id='d2', measurement_id='m2'),
            _binding(role='outdoor_solar',   device_id='d3', measurement_id='m3'),
        ]
        result = self._run(bindings, {
            ('d1', 'm1'): (1000.0, 15.0),
            ('d2', 'm2'): (1000.0, 3.5),
            ('d3', 'm3'): (1000.0, 450.0),
        })
        assert result['outdoor']['temp_c']    == pytest.approx(15.0)
        assert result['outdoor']['wind_ms']   == pytest.approx(3.5)
        assert result['outdoor']['solar_wm2'] == pytest.approx(450.0)

    # ── Malformed bindings ───────────────────────────────────────────────────

    def test_skips_unknown_role(self):
        bindings = [
            _binding(role='unknown_thing', device_id='d1', measurement_id='m1'),
        ]
        result = self._run(bindings, {('d1', 'm1'): (1000.0, 99.0)})
        # Unknown role is silently skipped — total_count stays 0
        assert result['total_count'] == 0

    def test_skips_missing_device_id(self):
        bindings = [{'role': 'indoor_temp', 'device_id': '', 'measurement_id': 'm1'}]
        result = self._run(bindings, {})
        assert result['total_count'] == 0

    def test_query_exception_handled(self):
        bindings = [_binding(role='indoor_temp', device_id='d1', measurement_id='m1')]
        from aot.aot_flask.geo.facility_sensors import read_facility_sensors
        with patch('aot.aot_flask.geo.facility_sensors.get_last_measurement',
                   side_effect=RuntimeError('influx down')):
            result = read_facility_sensors(bindings)
        assert result['indoor']['temp_c'] is None
        assert result['sensors'][0]['degraded_reason'].startswith('query_error')
        assert result['degraded']

    # ── Sensor detail list ───────────────────────────────────────────────────

    def test_sensor_detail_fields(self):
        bindings = [_binding(role='indoor_temp', device_id='d1', measurement_id='m1',
                             name='East Sensor')]
        result = self._run(bindings, {('d1', 'm1'): (1234.0, 21.5)})
        detail = result['sensors'][0]
        assert detail['role']  == 'indoor_temp'
        assert detail['name']  == 'East Sensor'
        assert detail['value'] == pytest.approx(21.5)
        assert detail['ts']    == pytest.approx(1234.0)
        assert detail['valid'] is True
        assert detail['stale'] is False


# ─────────────────────────────────────────────────────────────────────────────
# _reject_spatial_outliers — 등가 환경 전제 하 공간 outlier 제거
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectSpatialOutliers:
    def test_too_few_for_rejection(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # 2개면 어느 쪽이 outlier 인지 판단 불가 — 둘 다 유지
        kept, rej = _reject_spatial_outliers([(0, 20.0), (1, 40.0)])
        assert len(kept) == 2
        assert rej == []

    def test_all_equal_no_rejection(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # MAD = 0 — reject 불필요
        kept, rej = _reject_spatial_outliers([(0, 25.0), (1, 25.0), (2, 25.0), (3, 25.0)])
        assert len(kept) == 4
        assert rej == []

    def test_single_outlier_rejected(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # 4 모서리 중 1개가 크게 튐 — 그 센서만 제외
        kept, rej = _reject_spatial_outliers([
            (0, 25.0), (1, 25.2), (2, 24.8), (3, 45.0),
        ])
        kept_idx = sorted(i for i, _ in kept)
        assert kept_idx == [0, 1, 2]
        assert rej == [3]

    def test_majority_outlier_keeps_all(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # 2-2 양분 — 어느 쪽이 정상인지 통계로 판단 불가, 전부 유지
        kept, rej = _reject_spatial_outliers([
            (0, 25.0), (1, 25.0), (2, 60.0), (3, 60.0),
        ])
        assert len(kept) == 4
        assert rej == []

    def test_minority_outlier_rejected_in_5(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # 5개 중 2개가 튐 — 3개 다수 의견을 신뢰하고 2개 reject
        kept, rej = _reject_spatial_outliers([
            (0, 25.0), (1, 25.0), (2, 25.0), (3, 60.0), (4, 60.0),
        ])
        kept_idx = sorted(i for i, _ in kept)
        assert kept_idx == [0, 1, 2]
        assert sorted(rej) == [3, 4]

    def test_normal_variation_not_rejected(self):
        from aot.aot_flask.geo.facility_sensors import _reject_spatial_outliers
        # 등가 환경 잡음 수준 (±0.5°C) — 아무도 reject 되면 안 됨
        kept, rej = _reject_spatial_outliers([
            (0, 24.9), (1, 25.1), (2, 25.0), (3, 25.2),
        ])
        assert len(kept) == 4
        assert rej == []


# ─────────────────────────────────────────────────────────────────────────────
# compute_spatial_internal — outlier 제거 + 극값 노출
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSpatialInternal:
    def _make_sensor(self, fitting_id, value, key='T'):
        """입력값을 _read_one_sensor 가 받을 형태로 변환 — 본 테스트에선 직접 read 우회."""
        return {
            'fitting_id':       fitting_id,
            'input_uuid':       f'dev-{fitting_id}',
            'name':             f'sensor-{fitting_id}',
            'measurement_id':   f'meas-{fitting_id}',
            'measurement_type': 'temperature' if key == 'T' else 'humidity',
        }

    def _run_with_values(self, sensors, value_map):
        """value_map: {input_uuid: {key: value}}"""
        from aot.aot_flask.geo import facility_sensors as fs

        def fake_read(input_uuid, mtype, max_age, measurement_id=None):
            return value_map.get(input_uuid, {})

        with patch.object(fs, '_read_one_sensor', side_effect=fake_read):
            return fs.compute_spatial_internal(sensors)

    def test_four_corner_normal(self):
        # 등가 환경, 정상 변동 — 평균 ≈ 25
        sensors = [self._make_sensor(i, 0) for i in range(4)]
        vals = {f'dev-{i}': {'T': v} for i, v in enumerate([24.9, 25.1, 25.0, 25.2])}
        r = self._run_with_values(sensors, vals)
        assert r['T'] == pytest.approx(25.05, abs=0.01)
        assert r['T_max'] == pytest.approx(25.2)
        assert r['T_min'] == pytest.approx(24.9)
        assert r['rejected_count'] == 0
        assert all(d['rejected'] == {} for d in r['detail'])

    def test_one_corner_malfunction_excluded_from_mean(self):
        # 4개 중 1개가 45°C 로 튐 → 평균에서 제외되어 ~25°C 유지
        sensors = [self._make_sensor(i, 0) for i in range(4)]
        vals = {f'dev-{i}': {'T': v} for i, v in enumerate([25.0, 25.0, 25.0, 45.0])}
        r = self._run_with_values(sensors, vals)
        assert r['T'] == pytest.approx(25.0, abs=0.1)  # outlier 제거 후 평균
        assert r['T_max'] == pytest.approx(25.0)        # outlier 제거 후 극값
        assert r['rejected_count'] == 1
        assert r['detail'][3]['rejected'].get('T') is True
        # 다른 센서들은 reject 표시 없음
        for i in range(3):
            assert r['detail'][i]['rejected'] == {}

    def test_t_max_visible_when_no_outlier(self):
        # outlier 없지만 한 모서리가 실제로 살짝 더 높음 — T_max 가 그 값 반영
        sensors = [self._make_sensor(i, 0) for i in range(4)]
        vals = {f'dev-{i}': {'T': v} for i, v in enumerate([25.0, 25.5, 26.0, 26.5])}
        r = self._run_with_values(sensors, vals)
        assert r['rejected_count'] == 0
        assert r['T_max'] == pytest.approx(26.5)
        assert r['T_min'] == pytest.approx(25.0)

    def test_single_sensor_passes_through(self):
        # 단일 센서: outlier 판단 불가 — 그대로 통과, max/min 동일
        sensors = [self._make_sensor(0, 0)]
        vals = {'dev-0': {'T': 22.0}}
        r = self._run_with_values(sensors, vals)
        assert r['T'] == pytest.approx(22.0)
        assert r['T_max'] == pytest.approx(22.0)
        assert r['T_min'] == pytest.approx(22.0)
        assert r['rejected_count'] == 0

    def test_two_sensors_no_rejection(self):
        # 2개일 때 큰 편차여도 어느 쪽이 잘못인지 모르므로 둘 다 유지
        sensors = [self._make_sensor(i, 0) for i in range(2)]
        vals = {f'dev-{i}': {'T': v} for i, v in enumerate([25.0, 45.0])}
        r = self._run_with_values(sensors, vals)
        assert r['rejected_count'] == 0
        assert r['T'] == pytest.approx(35.0)  # 평균 — 분리 불가
        assert r['T_max'] == pytest.approx(45.0)
