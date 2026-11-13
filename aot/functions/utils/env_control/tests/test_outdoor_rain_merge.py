# coding=utf-8
"""실외 강우 — 실측과 예보 모델을 섞지 않고, 단위를 mm/h 로 맞춘다 (2026-10-10).

폐루프 `rain_gauge_vs_forecast_primary`: 강우계(실측)와 Open-Meteo 예보를 순위 표시 없이
(= 둘 다 메인) 묶은 설치에서 `read_outdoor_sensors` 가 둘을 **평균**했다 — 강우계 0 +
예보 1.2 → 0.6 ≥ 문턱 0.5. 실측이 섞였으니 출처는 'measured'(`rain_origin_of` 는 전부
모델일 때만 'model') 라 한낮에 창을 **전부** 닫았다(실내 47.6 °C).

지키는 것:
  · 신선한 실측 강우가 하나라도 있으면 실측만(순위보다 앞선다), 같은 묶음 안에서는 최댓값.
  · 예보는 실측이 없을 때만 — 그때 출처 'model'.
  · 끊긴 실측이 비를 보고 있었으면 예보로 갈아타지 않는다(규칙 A — 게이트가 마지막 실측으로 닫는다).
  · 온도·습도·풍속·일사도 같은 순위 안에서는 실측 먼저(순위는 사용자가 적은 대로).
  · 단위: 15 분 누적 → ×4, 시간 합 → ×1, 감우기 0/1 그대로, 모르면 그대로, 실측은 줄이지 않는다.
"""
import types
from unittest.mock import patch

import pytest

import aot.space.facility_sensors as fs
import aot.utils.inputs as ui
from aot.functions.utils.env_control.safety_gates import (
    RAIN_LEVEL_CLOSE, RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_NONE, classify_rain)


def _s(dev, meas, mtype, priority=None):
    s = {'fitting_id': 'fit-' + meas, 'name': mtype, 'sensor_role': 'outdoor',
         'measurement_type': mtype, 'input_uuid': dev, 'measurement_id': meas}
    if priority is not None:
        s['sensor_priority'] = priority
    return s


def _glm(values):
    def fn(device_id, measurement_id, max_age=None):
        v = values.get((device_id, measurement_id))
        return [1000.0, v] if v is not None else [None, None]
    return fn


@pytest.fixture
def env(monkeypatch):
    """'om' 이 예보 모델(Open-Meteo), 나머지는 실측. 단위 환산은 따로 시험한다(여기선 그대로)."""
    monkeypatch.setattr(ui, 'model_origin_device_ids',
                        lambda ids: {d for d in ids if d.startswith('om')})
    monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})
    monkeypatch.setattr(fs, '_normalise_rain', lambda v, dm: v)

    def read(values, sensors, **kw):
        with patch('aot.utils.influx.get_last_measurement', side_effect=_glm(values)):
            return fs.read_outdoor_sensors(sensors, max_age=600, **kw)
    return read


_GAUGE_FC = [_s('gauge', 'gR', 'rain'), _s('om', 'oR', 'rain')]     # 순위 표시 없음 = 둘 다 메인


class TestRainMeasuredFirst:
    def test_강우계_0_과_예보가_평균되지_않는다(self, env):
        od = env({('gauge', 'gR'): 0.0, ('om', 'oR'): 1.2}, _GAUGE_FC)
        assert od['rain_mm'] == 0.0
        assert od['rain_origin'] == 'measured'
        # 게이트: 예전 0.6(실측) → 전부 닫음. 이제 비 없음.
        assert classify_rain(od['rain_mm'], od['rain_origin'], 1.0,
                             threshold=0.5) == RAIN_LEVEL_NONE

    def test_실측이_없으면_예보를_쓰고_출처는_모델(self, env):
        od = env({('om', 'oR'): 1.2}, _GAUGE_FC)
        assert od['rain_mm'] == 1.2 and od['rain_origin'] == 'model'

    def test_예보만_있는_설치(self, env):
        od = env({('om', 'oR'): 0.4}, [_s('om', 'oR', 'rain')])
        assert (od['rain_mm'], od['rain_origin']) == (0.4, 'model')
        assert classify_rain(od['rain_mm'], od['rain_origin'], None,
                             threshold=0.5) == RAIN_LEVEL_HOLD_ROOF

    def test_백업_예보는_신선한_메인_강우계가_있으면_무시된다(self, env):
        sensors = [_s('gauge', 'gR', 'rain'), _s('om', 'oR', 'rain', 'backup')]
        od = env({('gauge', 'gR'): 0.0, ('om', 'oR'): 1.8}, sensors)
        assert (od['rain_mm'], od['rain_origin']) == (0.0, 'measured')
        assert od['backup_keys'] == []

    def test_실측은_순위를_넘어_예보를_이긴다(self, env):
        """예보가 메인·강우계가 백업이어도 신선한 실측이 있으면 실측이다."""
        sensors = [_s('om', 'oR', 'rain'), _s('gauge', 'gR', 'rain', 'backup')]
        od = env({('gauge', 'gR'): 2.0, ('om', 'oR'): 0.3}, sensors)
        assert (od['rain_mm'], od['rain_origin']) == (2.0, 'measured')
        assert od['backup_keys'] == ['rain_mm']

    def test_실측끼리는_최댓값(self, env):
        """감우기 1 과 강우율 0 을 평균하면 0.5 — 뜻 없는 숫자다. 비를 본 쪽을 따른다."""
        sensors = [_s('gauge', 'gR', 'rain'), _s('switch', 'sR', 'rain')]
        od = env({('gauge', 'gR'): 0.0, ('switch', 'sR'): 1.0}, sensors)
        assert od['rain_mm'] == 1.0 and od['rain_origin'] == 'measured'


class TestRuleAStaleGauge:
    def test_기억이_없으면_예보가_넘겨받는다(self, env):
        od = env({('om', 'oR'): 1.2}, _GAUGE_FC, rain_seen={})
        assert (od['rain_mm'], od['rain_origin'], od['rain_held']) == (1.2, 'model', False)

    def test_비를_보던_강우계가_끊기면_예보로_풀지_않는다(self, env):
        seen = {}
        od = env({('gauge', 'gR'): 3.0, ('om', 'oR'): 0.2}, _GAUGE_FC, rain_seen=seen)
        assert od['rain_mm'] == 3.0
        assert seen == {'measured_mm': 3.0, 'devices': ['gauge']}
        # 강우계 끊김(값 없음), 예보는 약한 비 — 예보를 내면 게이트가 실측 래치를 지운다.
        od = env({('om', 'oR'): 0.2}, _GAUGE_FC, rain_seen=seen)
        assert od['rain_mm'] is None and od['rain_origin'] is None
        assert od['rain_held'] is True
        # 게이트는 마지막 실측(잃음)으로 본다 — 완화 없이 닫는다.
        assert classify_rain(seen['measured_mm'], 'measured', 0.5, threshold=0.5,
                             rain_lost=True) == RAIN_LEVEL_CLOSE

    def test_마지막_실측이_0_이면_예보가_넘겨받는다(self, env):
        seen = {}
        env({('gauge', 'gR'): 0.0, ('om', 'oR'): 0.0}, _GAUGE_FC, rain_seen=seen)
        od = env({('om', 'oR'): 1.5}, _GAUGE_FC, rain_seen=seen)
        assert (od['rain_mm'], od['rain_origin'], od['rain_held']) == (1.5, 'model', False)

    def test_강우계가_돌아오면_실측(self, env):
        seen = {'measured_mm': 3.0, 'devices': ['gauge']}
        od = env({('gauge', 'gR'): 0.0, ('om', 'oR'): 0.2}, _GAUGE_FC, rain_seen=seen)
        assert (od['rain_mm'], od['rain_origin'], od['rain_held']) == (0.0, 'measured', False)
        assert seen['measured_mm'] == 0.0

    def test_강우계를_뺀_설치는_기억에_묶이지_않는다(self, env):
        seen = {'measured_mm': 3.0, 'devices': ['gauge']}
        od = env({('om', 'oR'): 1.2}, [_s('om', 'oR', 'rain')], rain_seen=seen)
        assert (od['rain_mm'], od['rain_origin']) == (1.2, 'model')


class TestOtherKeysMeasuredFirst:
    _SENSORS = [_s('station', 'sT', 'temperature'), _s('station', 'sRH', 'humidity'),
                _s('station', 'sW', 'wind_speed'),
                _s('om', 'oT', 'temperature'), _s('om', 'oRH', 'humidity'),
                _s('om', 'oW', 'wind_speed'), _s('om', 'oL', 'light')]
    _ALL = {('station', 'sT'): 22.9, ('station', 'sRH'): 62.0, ('station', 'sW'): 0.6,
            ('om', 'oT'): 19.5, ('om', 'oRH'): 79.0, ('om', 'oW'): 3.0, ('om', 'oL'): 500.0}

    def test_같은_순위의_예보는_실측에_섞이지_않는다(self, env):
        od = env(self._ALL, self._SENSORS)
        assert (od['T_ext'], od['RH_ext'], od['wind_ms']) == (22.9, 62.0, 0.6)
        # 실측이 없는 종류는 예보가 그대로 채운다
        assert od['solar_wm2'] == 500.0
        assert od['backup_keys'] == []

    def test_실측이_끊기면_예보(self, env):
        vals = {k: v for k, v in self._ALL.items() if k[0] == 'om'}
        od = env(vals, self._SENSORS)
        assert (od['T_ext'], od['RH_ext'], od['wind_ms']) == (19.5, 79.0, 3.0)

    def test_사용자가_적은_순위가_먼저다(self, env):
        """메인 예보 + 백업 기상대 — 온습도는 순위를 따른다(강우만 순위를 넘는다)."""
        sensors = [_s('om', 'oT', 'temperature'), _s('om', 'oRH', 'humidity'),
                   _s('station', 'sT', 'temperature', 'backup'),
                   _s('station', 'sRH', 'humidity', 'backup')]
        od = env(self._ALL, sensors)
        assert (od['T_ext'], od['RH_ext']) == (19.5, 79.0)

    def test_실측끼리는_예전처럼_평균(self, env):
        sensors = [_s('a', 'aT', 'temperature'), _s('b', 'bT', 'temperature')]
        od = env({('a', 'aT'): 20.0, ('b', 'bT'): 22.0}, sensors)
        assert od['T_ext'] == 21.0


# ─────────────────────────────────────────────────────────────────────────────
# 단위 — 게이트는 mm/h
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('unit,meas,name,driver,model,factor,kind', [
    ('mm', 'precipitation', '강수15분', 'KMA_weather_500', False, 4.0, 'rate'),   # rn_15m
    ('mm', 'precipitation', '', 'KMA_weather_500', False, 4.0, 'rate'),           # 드라이버 표
    ('mm', 'precipitation', '15-min Precipitation', None, False, 4.0, 'rate'),    # 이름
    ('mm', 'rain_15m', '', None, False, 4.0, 'rate'),
    ('mm', 'rn15m', '', None, False, 4.0, 'rate'),
    ('mm', 'rain_10m', '', None, False, 6.0, 'rate'),
    ('mm', 'rain_1h', '', None, False, 1.0, 'rate'),
    ('mm', 'rain', '', 'OPEN_METEO_FORECAST', True, 1.0, 'rate'),                 # 시간 합
    ('mm', 'rain', '', 'NASA_POWER_DAILY', True, 1.0 / 24.0, 'rate'),             # 모델 일 합계는 줄인다
    ('mm', 'rain_24h', '', None, False, 1.0, 'rate'),                             # 실측은 줄이지 않는다
    ('mm', 'precipitation', '15mm', None, False, 1.0, 'unknown'),                 # '15mm' 는 구간이 아니다
    ('mm', 'rain', '', None, False, 1.0, 'unknown'),                              # 모르면 그대로
    ('in', 'length', '', None, False, 25.4, 'unknown'),
    ('mm_h', 'precipitation', '', 'ecowitt_weather', False, 1.0, 'rate'),
    ('in_h', 'precipitation', '', None, False, 25.4, 'rate'),
    ('none', 'precipitation', '강수', 'KMA_weather_500', False, 1.0, 'switch'),     # 감우기 0/1
    ('bool', 'rain', '', None, False, 1.0, 'switch'),
])
def test_강우_단위(unit, meas, name, driver, model, factor, kind):
    f, k = ui.rain_unit_scale(unit, meas, name, driver, model)
    assert k == kind
    assert f == pytest.approx(factor)


def test_15분_누적이_시간당으로_게이트에_간다(monkeypatch):
    """KMA 15 분 0.4 mm = 1.6 mm/h — 예전에는 0.4 < 0.5 라 '비 없음' 이었다."""
    dm = types.SimpleNamespace(unique_id='m6', device_id='kma', measurement='precipitation',
                               unit='mm', name='강수15분', conversion_id='')
    monkeypatch.setattr(fs, '_dm_row', lambda mid: dm)
    monkeypatch.setattr(ui, 'input_driver_of', lambda d: 'KMA_weather_500')
    monkeypatch.setattr(ui, 'model_input_drivers', lambda: frozenset({'OPEN_METEO_FORECAST'}))
    with patch('aot.utils.influx.get_last_measurement', return_value=[1000.0, 0.4]):
        out = fs._read_one_sensor('kma', 'rain', 600, measurement_id='m6')
    assert out['rain_mm'] == pytest.approx(1.6)
    assert classify_rain(out['rain_mm'], 'measured', None,
                         threshold=0.5) == RAIN_LEVEL_CLOSE


def test_모르는_채널은_값을_바꾸지_않는다(monkeypatch):
    monkeypatch.setattr(fs, '_dm_row', lambda mid: None)
    with patch('aot.utils.influx.get_last_measurement', return_value=[1000.0, 0.4]):
        out = fs._read_one_sensor('x', 'rain', 600, measurement_id='m')
    assert out['rain_mm'] == 0.4


def test_환산이_실패해도_값을_그대로(monkeypatch):
    dm = types.SimpleNamespace(device_id='kma', measurement='precipitation', unit='mm',
                               name='강수15분', conversion_id='')

    def boom(d):
        raise RuntimeError('db down')
    monkeypatch.setattr(ui, 'input_driver_of', boom)
    assert ui.rain_channel_mm_h(0.4, dm, unit='mm') == 0.4


@pytest.mark.parametrize('meas,unit,ok', [
    ('precipitation', 'mm', True),
    ('length', 'mm', True),
    ('anything', 'mm_h', True),
    ('precipitation', 'percent', False),      # 강수 확률(KMA_forecast POP)
    ('evapotranspiration', 'mm', False),      # NASA POWER ET0
    ('temperature', 'C', False),
])
def test_강우_채널_고르기(meas, unit, ok):
    dm = types.SimpleNamespace(measurement=meas, unit=unit, conversion_id='')
    assert fs._is_rain_channel(dm) is ok


def test_수집기도_강우를_시간당으로(monkeypatch):
    import logging
    import time
    import aot.functions.ext_context_collector as ecc
    monkeypatch.setattr(ecc, 'write_influxdb_value', lambda *a, **k: None)
    monkeypatch.setattr(ecc._freshness, 'freshness_by_device', lambda ids: {})
    monkeypatch.setattr(ecc, '_shared_context', {})
    monkeypatch.setattr(ecc, '_shared_context_ts', 0.0)
    monkeypatch.setattr(ui, 'model_origin_device_ids', lambda ids: set())
    monkeypatch.setattr(ui, 'rain_measurement_mm_h',
                        lambda v, mid: v * 4.0 if mid == 'rn15' else v)
    f = ecc.CustomFunction.__new__(ecc.CustomFunction)
    f.logger, f.unique_id = logging.getLogger('test.collector'), 'collector'
    f.update_period, f.sensor_max_age = 60.0, 0.0
    f.sensor_temperature = f.sensor_humidity = f.sensor_wind = None
    f.sensor_rain = 'kma,rn15'
    f.sensor_solar = f.sensor_dewpoint = f.sensor_co2 = None
    now = time.time()
    f.get_last_measurement = lambda d, m, max_age=None: [now - 30, 0.4]
    f._collect_and_publish()
    assert ecc.get_shared_context()['rain'] == pytest.approx(1.6)
