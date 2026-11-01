# coding=utf-8
"""관측이 아닌 입력 판정 — 입력 모듈이 밝힌 성질만 본다(예보·모델값·시뮬레이터). 실측·미러는 그대로."""
import time

from aot.twin import engine, models
from aot.twin import obs_basis as OB
from aot.twin.types import Status, TargetKind, TargetSpec, SeriesRef, Provenance
from .helpers import MemSource, facility_spec, field_spec, recent
from .test_engine import FULL, _src

INFO = {
    'OPEN_METEO_HOURLY_FORECAST': {'data_time': 'forecast', 'data_origin': 'model', 'measurements_dict': {0: {}}},
    'OPEN_METEO_DAILY_FORECAST': {'data_origin': 'model', 'measurements_dict': {0: {'forecast_lead_d': 1}}},
    'OPEN_METEO_FORECAST': {'data_origin': 'model', 'measurements_dict': {0: {'measurement': 'temperature'}}},
    'NEW_FORECAST_MODULE': {'measurements_dict': {0: {'measurement': 'temperature'}, 1: {'forecast_lead_d': 2}}},
    'TEST_SAVE_VALUE': {'measurements_dict': {0: {}}},
    'MQTT_PAHO_JSON': {'measurements_dict': {0: {}}},                    # 미러 센서 — 현장 실측의 사본
    'chirpstack_mqtt_jmespath': {'measurements_dict': {0: {}}},
    'KMA_weather_500': {'measurements_dict': {0: {}}},
}


def test_forecast_model_and_simulated_are_not_observations():
    r = OB.non_observation_reason
    assert r('OPEN_METEO_HOURLY_FORECAST', INFO, 0) == OB.FORECAST       # data_time='forecast'
    assert r('OPEN_METEO_DAILY_FORECAST', INFO, 0) == OB.FORECAST        # forecast_lead_d
    assert r('OPEN_METEO_FORECAST', INFO, 0) == OB.MODEL                 # data_origin='model' — 'SIM 김제 기상대'·'환경센서:meteo'
    assert r('TEST_SAVE_VALUE', INFO, 0) == OB.SIMULATED                 # 모듈 표식(is_simulated driver_test)


def test_channel_meta_decides_for_a_module_that_mixes_observation_and_forecast_channels():
    assert OB.non_observation_reason('NEW_FORECAST_MODULE', INFO, 0) is None
    assert OB.non_observation_reason('NEW_FORECAST_MODULE', INFO, 1) == OB.FORECAST      # 새 모듈도 코드 변경 없이
    assert OB.non_observation_reason('NEW_FORECAST_MODULE', INFO, '1') == OB.FORECAST     # 채널이 문자열이어도


def test_measured_and_mirror_sensors_stay():
    for m in ('MQTT_PAHO_JSON', 'chirpstack_mqtt_jmespath', 'KMA_weather_500'):
        assert OB.non_observation_reason(m, INFO, 0) is None, m


def test_unknown_module_or_missing_info_is_an_observation():
    assert OB.non_observation_reason('NOT_A_MODULE', INFO, 0) is None
    assert OB.non_observation_reason('OPEN_METEO_FORECAST', None, 0) is None   # 모듈 정보를 못 읽으면 빼지 않는다
    assert OB.non_observation_reason('', INFO, 0) is None


def test_name_does_not_decide():
    """장치 이름 접두(SIM …)는 판정에 쓰지 않는다 — 모듈이 밝힌 성질만."""
    assert OB.non_observation_reason('MQTT_PAHO_JSON', INFO, 0) is None


def test_excluded_line_reads_the_same_everywhere():
    assert OB.excluded_line('비', OB.MODEL, 'SIM 김제 기상대') == '관측이 아님 — 동기화에서 제외: 비(모델값, SIM 김제 기상대)'
    assert OB.excluded_line('토양수분', OB.SIMULATED) == '관측이 아님 — 동기화에서 제외: 토양수분(시뮬레이터)'


def test_engine_appends_the_excluded_line_to_the_result():
    now = time.time()
    line = OB.excluded_line('토양수분', OB.SIMULATED, 'SIM 현장센서')
    spec = field_spec(excluded_inputs={'theta': {'reason': OB.SIMULATED, 'line': line}})
    spec.inputs.clear()                                                 # 동기화에서 빠져 배선이 비었다
    r = engine.run_target(spec, MemSource({}), models.get('field', 'dummy_field'), FULL, now)
    assert r.status == Status.NOT_TWINNABLE
    assert line in r.reason and '필수 입력 미배선' in r.reason


def test_engine_result_is_unchanged_without_excluded_inputs():
    now = time.time()
    r = engine.run_target(facility_spec(), _src(now), models.get('facility', 'dummy_facility'), FULL, now)
    assert r.status == Status.OK and OB.EXCLUDED_LINE not in r.reason
