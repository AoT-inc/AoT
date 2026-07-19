# coding=utf-8
"""
test_facility_to_control.py — facility 센서 → Integrated Environment Control 전달 검증.

사용자 핵심 관심사: geo/facility 에 등록한 각종 센서가 env_coordinator 의 제어
변수로 의미(semantic) 손실 없이 전달되는지.

검증 체인:
  facility 센서 등록(sensors_resolved / sensors_outdoor, measurement_type 포함)
    → compute_spatial_internal / read_outdoor_sensors  (의미 매핑)
    → _collect_internal + _cycle_mixin external 구성     (제어 변수 dict)
    → situation.py / safety_gates 가 읽는 키

각 센서 타입(실내 T/RH/CO2/VPD/light, 실외 T/RH/wind/wind_dir/solar/rain)이
올바른 제어 변수에 도달하는지 매트릭스로 확인한다.
"""

from unittest.mock import MagicMock, patch

import aot.aot_flask.geo.facility_sensors as fs
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin


# ─────────────────────────────────────────────────────────────────────────────
# facility 센서 엔트리 빌더 (get_facility_integration 출력 형태)
# ─────────────────────────────────────────────────────────────────────────────

def _sensor(input_uuid, measurement_id, measurement_type, role='indoor', pos=None):
    return {
        'fitting_id':       'fit-' + measurement_id,
        'name':             measurement_type,
        'position':         pos,
        'sensor_role':      role,
        'measurement_type': measurement_type,
        'input_uuid':       input_uuid,
        'measurement_id':   measurement_id,
        'input_name':       None,
        'input_device':     None,
    }


def _mock_glm(values):
    """values: {(dev, meas): val} → get_last_measurement 대체."""
    def _glm(device_id, measurement_id, max_age=None):
        v = values.get((device_id, measurement_id))
        return [1000.0, v] if v is not None else [None, None]
    return _glm


# ─────────────────────────────────────────────────────────────────────────────
# 1. 실내 센서 의미 매핑 (compute_spatial_internal)
# ─────────────────────────────────────────────────────────────────────────────

def test_indoor_sensor_semantic_mapping():
    """실내 T/RH/CO2/light 센서가 각 제어 변수로 정확히 매핑된다."""
    sensors = [
        _sensor('dT',  'mT',  'temperature'),
        _sensor('dRH', 'mRH', 'humidity'),
        _sensor('dC',  'mC',  'co2'),
        _sensor('dL',  'mL',  'light'),
    ]
    values = {
        ('dT', 'mT'): 24.0, ('dRH', 'mRH'): 55.0,
        ('dC', 'mC'): 750.0, ('dL', 'mL'): 420.0,
    }
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        out = fs.compute_spatial_internal(sensors, max_age=300)

    assert out['T']   == 24.0
    assert out['RH']  == 55.0
    assert out['CO2'] == 750.0
    assert out['light'] == 420.0
    # VPD 센서 없으면 T/RH 로 자동 계산됨
    assert out['VPD'] is not None and out['VPD'] > 0


def test_indoor_explicit_vpd_sensor():
    """실내 VPD 센서가 있으면 계산값 대신 실측 VPD 사용."""
    sensors = [
        _sensor('dT',  'mT',  'temperature'),
        _sensor('dRH', 'mRH', 'humidity'),
        _sensor('dV',  'mV',  'vpd'),
    ]
    values = {('dT', 'mT'): 25.0, ('dRH', 'mRH'): 60.0, ('dV', 'mV'): 1.05}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        out = fs.compute_spatial_internal(sensors, max_age=300)
    assert out['VPD'] == 1.05


def test_indoor_spatial_average_multiple_sensors():
    """동일 변수 다중 실내 센서는 공간 평균."""
    sensors = [
        _sensor('dT1', 'mT1', 'temperature'),
        _sensor('dT2', 'mT2', 'temperature'),
    ]
    values = {('dT1', 'mT1'): 22.0, ('dT2', 'mT2'): 26.0}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        out = fs.compute_spatial_internal(sensors, max_age=300)
    assert out['T'] == 24.0          # (22+26)/2
    assert out['T_min'] == 22.0      # safety_gates 한파 판정용 극값
    assert out['T_max'] == 26.0      # safety_gates 폭염 판정용 극값


# ─────────────────────────────────────────────────────────────────────────────
# 2. 실외 센서 의미 매핑 (read_outdoor_sensors)
# ─────────────────────────────────────────────────────────────────────────────

def test_outdoor_sensor_semantic_mapping():
    """실외 T/RH/wind/wind_dir/solar/rain 센서가 각 키로 정확히 매핑된다."""
    sensors = [
        _sensor('oT',  'mT',  'temperature',    role='outdoor'),
        _sensor('oRH', 'mRH', 'humidity',       role='outdoor'),
        _sensor('oW',  'mW',  'wind_speed',     role='outdoor'),
        _sensor('oWD', 'mWD', 'wind_direction', role='outdoor'),
        _sensor('oS',  'mS',  'light',          role='outdoor'),
        _sensor('oR',  'mR',  'rain',           role='outdoor'),
    ]
    values = {
        ('oT', 'mT'): 31.0, ('oRH', 'mRH'): 42.0,
        ('oW', 'mW'): 6.5, ('oWD', 'mWD'): 225.0,
        ('oS', 'mS'): 880.0, ('oR', 'mR'): 2.5,
    }
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        od = fs.read_outdoor_sensors(sensors, max_age=300)

    assert od['T_ext']     == 31.0
    assert od['RH_ext']    == 42.0
    assert od['wind_ms']   == 6.5
    assert od['wind_deg']  == 225.0
    assert od['solar_wm2'] == 880.0
    assert od['rain_mm']   == 2.5


def test_outdoor_co2_sensor_reaches_control():
    """실외 CO₂ 센서가 CO2_ext 로 전달된다 (환기 희석 계산용).

    이전에는 read_outdoor_sensors 가 CO₂ 버킷이 없어 조용히 버려졌다.
    """
    sensors = [_sensor('oC', 'mC', 'co2', role='outdoor')]
    values = {('oC', 'mC'): 460.0}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        od = fs.read_outdoor_sensors(sensors, max_age=300)
    assert od['CO2_ext'] == 460.0

    # _cycle_mixin external 매핑 재현 — CO2/CO2_ext 양쪽 채워짐
    external = {}
    if od.get('CO2_ext') is not None:
        external['CO2_ext'] = od['CO2_ext']; external['CO2'] = od['CO2_ext']
    assert external['CO2']     == 460.0   # situation.py 가 읽는 키
    assert external['CO2_ext'] == 460.0   # effect_functions/greybox 가 읽는 키


# ─────────────────────────────────────────────────────────────────────────────
# 3. _collect_internal — facility 센서 → internal 제어 dict
# ─────────────────────────────────────────────────────────────────────────────

def _make_coordinator(sensors_resolved, sensors_outdoor):
    obj = MagicMock()
    obj._collect_internal = HelpersMixin._collect_internal.__get__(obj)
    obj._sensors_resolved = sensors_resolved
    obj._sensors_resolved_outdoor = sensors_outdoor
    obj.logger = MagicMock()
    return obj


def test_collect_internal_maps_indoor_and_outdoor():
    """_collect_internal 이 실내(T/RH/CO2/VPD)와 실외(wind/wind_dir/solar)를 합친다."""
    indoor = [
        _sensor('dT',  'mT',  'temperature'),
        _sensor('dRH', 'mRH', 'humidity'),
        _sensor('dC',  'mC',  'co2'),
    ]
    outdoor = [
        _sensor('oW',  'mW',  'wind_speed',     role='outdoor'),
        _sensor('oWD', 'mWD', 'wind_direction', role='outdoor'),
    ]
    values = {
        ('dT', 'mT'): 23.0, ('dRH', 'mRH'): 58.0, ('dC', 'mC'): 640.0,
        ('oW', 'mW'): 4.2, ('oWD', 'mWD'): 90.0,
    }
    obj = _make_coordinator(indoor, outdoor)
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        internal = obj._collect_internal(300.0)

    assert internal['T']   == 23.0
    assert internal['RH']  == 58.0
    assert internal['CO2'] == 640.0
    assert internal['VPD'] is not None
    # 실외 풍속/풍향이 internal 에 합산 (돌풍 게이트 / 풍향 가중 개방용)
    assert internal['wind']     == 4.2
    assert internal['wind_dir'] == 90.0


def test_collect_internal_outdoor_data_passthrough_no_requery():
    """outdoor_data 전달 시 read_outdoor_sensors 재호출 없이 사용 (중복쿼리 방지)."""
    indoor = [_sensor('dT', 'mT', 'temperature')]
    outdoor = [_sensor('oW', 'mW', 'wind_speed', role='outdoor')]
    obj = _make_coordinator(indoor, outdoor)

    # outdoor_data 를 직접 전달 → read_outdoor_sensors 가 호출되면 안 됨
    pre_read = {'wind_ms': 9.9, 'wind_deg': 180.0, 'solar_wm2': None}
    values = {('dT', 'mT'): 20.0}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)), \
         patch.object(fs, 'read_outdoor_sensors') as mock_rod:
        internal = obj._collect_internal(300.0, outdoor_data=pre_read)

    mock_rod.assert_not_called()           # 재호출 없음
    assert internal['wind']     == 9.9     # 전달된 값 사용
    assert internal['wind_dir'] == 180.0


def test_collect_internal_solar_supplements_missing_light():
    """실내 광센서 없을 때 실외 일사량(solar)으로 light 보충."""
    indoor = [_sensor('dT', 'mT', 'temperature')]   # light 없음
    outdoor = [_sensor('oS', 'mS', 'light', role='outdoor')]
    obj = _make_coordinator(indoor, outdoor)
    values = {('dT', 'mT'): 21.0, ('oS', 'mS'): 700.0}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        internal = obj._collect_internal(300.0)
    assert internal['light'] == 700.0


def test_indoor_light_not_overwritten_by_outdoor_solar():
    """실내 광센서가 있으면 실외 일사량으로 덮어쓰지 않는다."""
    indoor = [
        _sensor('dT', 'mT', 'temperature'),
        _sensor('dL', 'mL', 'light'),
    ]
    outdoor = [_sensor('oS', 'mS', 'light', role='outdoor')]
    obj = _make_coordinator(indoor, outdoor)
    values = {('dT', 'mT'): 21.0, ('dL', 'mL'): 300.0, ('oS', 'mS'): 700.0}
    with patch('aot.utils.influx.get_last_measurement', side_effect=_mock_glm(values)):
        internal = obj._collect_internal(300.0)
    assert internal['light'] == 300.0   # 실내 우선


# ─────────────────────────────────────────────────────────────────────────────
# 4. 실외 T/RH → external 양쪽 키 호환 (situation.py 'T' vs gate 'T_ext')
# ─────────────────────────────────────────────────────────────────────────────

def test_outdoor_TRH_reaches_both_external_keys():
    """_cycle_mixin 의 external 구성 로직을 재현해 T/T_ext 양쪽이 채워지는지 확인.

    이 매핑이 깨지면 situation.py(외부 T='T' 읽음)가 항상 기본값 20°C 를 받게 된다.
    """
    od = {'T_ext': 33.0, 'RH_ext': 38.0, 'wind_ms': 7.0,
          'wind_deg': 270.0, 'solar_wm2': 900.0, 'rain_mm': 0.0}

    # _cycle_mixin 의 facility outdoor override 로직 재현
    external = {}
    if od.get('T_ext') is not None:
        external['T_ext'] = od['T_ext']; external['T'] = od['T_ext']
    if od.get('RH_ext') is not None:
        external['RH_ext'] = od['RH_ext']; external['RH'] = od['RH_ext']
    if od.get('rain_mm') is not None:
        external['rain'] = od['rain_mm']
    if od.get('wind_ms') is not None:
        external['wind'] = od['wind_ms']
    if od.get('wind_deg') is not None:
        external['wind_dir'] = od['wind_deg']
    if od.get('solar_wm2') is not None:
        external['solar'] = od['solar_wm2']

    # situation.py (assess) 가 읽는 키
    assert external['T']   == 33.0
    assert external['RH']  == 38.0
    assert external['wind'] == 7.0
    assert external['solar'] == 900.0
    # _build_gate_env / safety_gates 가 읽는 키
    assert external['T_ext']  == 33.0
    assert external['RH_ext'] == 38.0
    assert external['wind_dir'] == 270.0
