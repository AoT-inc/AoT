# coding=utf-8
"""실외 센서는 메인과 백업으로 나뉜다 (2026-09-14).

현장 기상대가 메인이고, 기상대가 가끔 꺼질 때를 대비해 위성·예보 API 를
백업으로 붙인다. 예전에는 둘을 **동등하게 평균**해서, 멀쩡한 기상대 값이
API 쪽으로 끌려갔다.

실측(2026-09-14 aot-005 09:40): 기상대 22.9 °C · 62 %, Open-Meteo 19.5 °C ·
79 %. 평균하면 실외가 실제보다 차고 습해져 창이 늦게 열린다.
"""
from unittest.mock import patch

import aot.aot_flask.geo.facility_sensors as fs


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


_SENSORS = [
    _s('station', 'sT', 'temperature'),
    _s('station', 'sRH', 'humidity'),
    _s('station', 'sW', 'wind_speed'),
    _s('api', 'aT', 'temperature', 'backup'),
    _s('api', 'aRH', 'humidity', 'backup'),
    _s('api', 'aW', 'wind_speed', 'backup'),
]
_BOTH = {('station', 'sT'): 22.9, ('station', 'sRH'): 62.0, ('station', 'sW'): 0.6,
         ('api', 'aT'): 19.5, ('api', 'aRH'): 79.0, ('api', 'aW'): 1.0}


def _read(values, sensors=_SENSORS):
    with patch('aot.utils.influx.get_last_measurement', side_effect=_glm(values)):
        return fs.read_outdoor_sensors(sensors, max_age=300)


def test_메인이_살아_있으면_백업은_섞이지_않는다():
    od = _read(_BOTH)
    assert od['T_ext'] == 22.9
    assert od['RH_ext'] == 62.0
    assert od['wind_ms'] == 0.6
    assert od['backup_keys'] == []


def test_메인이_꺼지면_백업을_쓴다():
    values = {k: v for k, v in _BOTH.items() if k[0] == 'api'}
    od = _read(values)
    assert od['T_ext'] == 19.5
    assert od['RH_ext'] == 79.0
    assert od['wind_ms'] == 1.0
    assert set(od['backup_keys']) == {'T', 'RH', 'wind_ms'}


def test_온도와_습도는_같은_순위에서_짝으로_온다():
    """메인 습도만 끊기면 메인 온도 + 백업 습도로 섞지 않는다."""
    values = dict(_BOTH)
    del values[('station', 'sRH')]
    od = _read(values)
    assert (od['T_ext'], od['RH_ext']) == (19.5, 79.0)


def test_어느_쪽도_짝이_없으면_있는_것을_쓴다():
    values = {('station', 'sT'): 22.9, ('api', 'aRH'): 79.0}
    od = _read(values)
    assert (od['T_ext'], od['RH_ext']) == (22.9, 79.0)


def test_종류마다_따로_넘어간다():
    """풍속만 끊긴 메인은 온습도는 계속 메인이다."""
    values = dict(_BOTH)
    del values[('station', 'sW')]
    od = _read(values)
    assert od['T_ext'] == 22.9 and od['wind_ms'] == 1.0
    assert od['backup_keys'] == ['wind_ms']


def test_순위가_없는_기존_설치는_예전처럼_평균한다():
    sensors = [_s('a', 'aT', 'temperature'), _s('b', 'bT', 'temperature')]
    od = _read({('a', 'aT'): 20.0, ('b', 'bT'): 24.0}, sensors)
    assert od['T_ext'] == 22.0
    assert od['backup_keys'] == []


def test_같은_순위끼리는_평균한다():
    sensors = [_s('a', 'aT', 'temperature', 'backup'),
               _s('b', 'bT', 'temperature', 'backup')]
    od = _read({('a', 'aT'): 20.0, ('b', 'bT'): 24.0}, sensors)
    assert od['T_ext'] == 22.0


def test_모르는_순위_값은_메인이다():
    assert fs.sensor_priority_of({'sensor_priority': 'Backup '}) == 'backup'
    assert fs.sensor_priority_of({'sensor_priority': 'secondary'}) == 'primary'
    assert fs.sensor_priority_of({}) == 'primary'


def test_편집기가_고른_순위를_설비에_기록한다():
    """선택 상자만 있고 변경 처리가 없으면 화면만 바뀌고 저장되지 않는다.

    처음 구현에서 실제로 그랬다 — 백업으로 골라도 설비의 순위가 비어 있었다.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[4]
           / 'aot_flask' / 'static' / 'js' / 'geo' / 'facility' / 'sensor-ui.js'
           ).read_text(encoding='utf-8')
    assert 'data-field="sensor_priority"' in src
    assert "patchFitting(f.id, {sensor_priority:" in src


def test_시설_통합이_순위를_싣는다():
    """편집기에서 고른 순위가 제어까지 가는 길 — 한 곳에서 빠지면 조용히 메인이 된다."""
    import inspect
    from aot.aot_flask.geo import facility_integration as fi
    assert "'sensor_priority':  sensor_priority_of(f)" in inspect.getsource(fi)
