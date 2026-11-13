# coding=utf-8
"""센서 상태가 읽기 → 코디네이터 → 컨텍스트 → 로그까지 흐르고, 행동은 하나만 바뀐다.

고정하는 것:
  1. 판독 분류 — valid/stale/missing/outlier/out_of_range (`compute_spatial_internal`).
  2. out_of_range 는 제어에 닿지 않는다: 실내 온도 95 °C 같은 값은 `None` 이 되어
     기존 "측정 없음" 경로(근거 21, 제자리 유지)를 탄다.
  3. 실외 컨텍스트(공유 컨텍스트 포함)도 같은 범위 검사를 지난다.
  (VPD 출처는 `test_vpd_source.py`.)
"""
from unittest.mock import MagicMock, patch

import pytest

import aot.space.facility_sensors as fs
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.utils.env_control import coordinator as C
from aot.utils import sensor_status as SS
from aot.functions.utils.env_control import situation as S
from aot.functions.utils.env_control.authority import derive_authority
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.goal import build_env_target
from aot.functions.utils.env_control.log_channels import (
    REASON_NO_MEASUREMENT,
)
from aot.functions.utils.env_control.situation import compute_vpd
from aot.functions.utils.env_control.types import ActuatorProfile


# ─────────────────────────────────────────────────────────────────────────────
# 하니스
# ─────────────────────────────────────────────────────────────────────────────

def _sensor(uuid, mid, mtype):
    return {'fitting_id': 'fit-' + mid, 'name': mtype, 'position': None,
            'sensor_role': 'indoor', 'measurement_type': mtype,
            'input_uuid': uuid, 'measurement_id': mid,
            'input_name': None, 'input_device': None}


def _glm_factory(fresh=None, stale=None):
    """fresh: {mid: 값} 신선. stale: {mid: 값} — max_age 가 있으면 None, 없으면 값."""
    fresh, stale = fresh or {}, stale or {}

    def _glm(device_id, measurement_id, max_age=None):
        if measurement_id in fresh:
            return [1000.0, fresh[measurement_id]]
        if measurement_id in stale and max_age is None:
            return [1.0, stale[measurement_id]]
        return [None, None]
    return _glm


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})


def _spatial(sensors, fresh=None, stale=None, **kw):
    with patch('aot.utils.influx.get_last_measurement',
               side_effect=_glm_factory(fresh, stale)):
        return fs.compute_spatial_internal(sensors, max_age=300, **kw)


def _coordinator(sensors):
    obj = MagicMock()
    obj._collect_internal = HelpersMixin._collect_internal.__get__(obj)
    obj._sensors_resolved = sensors
    obj._sensors_resolved_outdoor = []
    obj.logger = MagicMock()
    obj.debug_logging = False
    obj._vpd_ema = None
    obj._t_ema = None
    obj._rh_ema = None
    return obj


def _collect(obj, fresh=None, stale=None):
    with patch('aot.utils.influx.get_last_measurement',
               side_effect=_glm_factory(fresh, stale)):
        return obj._collect_internal(300.0)


T_RH = [_sensor('dT', 'mT', 'temperature'), _sensor('dRH', 'mRH', 'humidity')]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 판독 분류
# ─────────────────────────────────────────────────────────────────────────────

class TestClassification:

    def test_정상_센서는_valid(self):
        sp = _spatial(T_RH, fresh={'mT': 22.0, 'mRH': 60.0}, with_status=True)
        assert sp['status']['T']['status'] == SS.VALID
        assert sp['status']['RH']['counts'] == {SS.VALID: 1}

    def test_max_age_밖이지만_데이터가_있으면_stale(self):
        sp = _spatial(T_RH, fresh={'mRH': 60.0}, stale={'mT': 22.0},
                      with_status=True)
        assert sp['status']['T']['status'] == SS.STALE
        assert sp['T'] is None            # 값은 종전처럼 평균에 안 들어간다

    def test_데이터가_아예_없으면_missing(self):
        sp = _spatial(T_RH, fresh={'mRH': 60.0}, with_status=True)
        assert sp['status']['T']['status'] == SS.MISSING
        assert sp['status']['T']['n'] == 1       # 센서는 달려 있다

    def test_센서가_안_달린_축은_n_이_0(self):
        sp = _spatial(T_RH, fresh={'mT': 22.0, 'mRH': 60.0}, with_status=True)
        assert sp['status']['CO2'] == {'status': SS.MISSING, 'counts': {}, 'n': 0}

    def test_공간_이상치는_outlier(self):
        sensors = [_sensor('d%d' % i, 'm%d' % i, 'temperature') for i in range(4)]
        sp = _spatial(sensors, fresh={'m0': 22.0, 'm1': 22.1, 'm2': 21.9, 'm3': 29.0},
                      with_status=True)
        st = sp['status']['T']
        assert st['counts'] == {SS.VALID: 3, SS.OUTLIER: 1}
        assert st['status'] == SS.VALID           # 축은 최선
        assert sp['rejected_count'] == 1
        assert sp['detail'][3]['status']['T'] == SS.OUTLIER

    def test_물리_범위_밖은_out_of_range_이고_평균에_안_섞인다(self):
        sensors = [_sensor('d%d' % i, 'm%d' % i, 'temperature') for i in range(2)]
        sp = _spatial(sensors, fresh={'m0': 22.0, 'm1': 150.0}, with_status=True)
        assert sp['T'] == 22.0
        assert sp['status']['T']['counts'] == {SS.VALID: 1, SS.OUT_OF_RANGE: 1}

    def test_센서_하나가_범위_밖이면_축은_out_of_range_이고_값이_없다(self):
        sp = _spatial(T_RH, fresh={'mT': 95.0, 'mRH': 60.0}, with_status=True)
        assert sp['T'] is None
        assert sp['status']['T']['status'] == SS.OUT_OF_RANGE

    def test_RH_101_은_100_으로_자르고_유효(self):
        sp = _spatial(T_RH, fresh={'mT': 22.0, 'mRH': 101.0}, with_status=True)
        assert sp['RH'] == 100.0
        assert sp['status']['RH']['status'] == SS.VALID

    def test_RH_130_은_범위밖이고_값이_없다(self):
        sp = _spatial(T_RH, fresh={'mT': 22.0, 'mRH': 130.0}, with_status=True)
        assert sp['RH'] is None
        assert sp['status']['RH']['status'] == SS.OUT_OF_RANGE

    def test_범위_검사는_상태를_묻지_않아도_한다(self):
        """표시 경로(with_status 없음)도 평균 오염을 막는다. 상태 키만 없다."""
        sp = _spatial(T_RH, fresh={'mT': 22.0, 'mRH': 130.0})
        assert sp['RH'] is None and 'status' not in sp

    def test_상태를_안_물으면_추가_조회가_없다(self):
        calls = []

        def _glm(device_id, measurement_id, max_age=None):
            calls.append(max_age)
            return [None, None]
        with patch('aot.utils.influx.get_last_measurement', side_effect=_glm):
            fs.compute_spatial_internal(T_RH, max_age=300)
        assert calls == [300, 300]               # max_age=None 재조회가 없다


class TestOutdoorClassification:

    def _out(self, fresh, stale=None):
        sensors = [
            {'input_uuid': 'o1', 'measurement_id': 'oT', 'measurement_type': 'temperature'},
            {'input_uuid': 'o2', 'measurement_id': 'oW', 'measurement_type': 'wind_speed'},
            {'input_uuid': 'o3', 'measurement_id': 'oS', 'measurement_type': 'light'},
            {'input_uuid': 'o4', 'measurement_id': 'oR', 'measurement_type': 'rain'},
        ]
        with patch('aot.utils.influx.get_last_measurement',
                   side_effect=_glm_factory(fresh, stale)):
            return fs.read_outdoor_sensors(sensors, max_age=300, with_status=True)

    def test_다섯_축_분류(self):
        od = self._out(fresh={'oT': 12.0, 'oW': -3.0, 'oR': 0.0}, stale={'oS': 400.0})
        st = od['status']
        assert st['T_ext']['status'] == SS.VALID
        assert st['wind']['status'] == SS.OUT_OF_RANGE      # 음수 풍속
        assert od['wind_ms'] is None
        assert st['solar']['status'] == SS.STALE
        assert st['rain']['status'] == SS.VALID
        assert st['RH_ext']['status'] == SS.MISSING and st['RH_ext']['n'] == 0

    def test_음수_일사는_범위밖_작은_음수는_0(self):
        assert self._out(fresh={'oS': -50.0})['solar_wm2'] is None
        od = self._out(fresh={'oS': -2.0})
        assert od['solar_wm2'] == 0.0 and od['status']['solar']['status'] == SS.VALID


# ─────────────────────────────────────────────────────────────────────────────
# 2. 행동: 범위 밖 실내 온도 → 제자리 (근거 21)
# ─────────────────────────────────────────────────────────────────────────────

_EXT = {'T': 5.0, 'RH': 50.0, 'T_ext': 5.0, 'RH_ext': 50.0,
        'wind': 1.0, 'solar': 300.0}


def _profile(kind, aid):
    return ActuatorProfile(actuator_id=aid, kind=kind,
                           effect_model=build_effect_model(kind, {}),
                           safe_default=0.0)


def _decide(internal, profiles, prev):
    target = build_env_target(T_target=22.0, T_tol=1.0, T_pri=0.5,
                              RH_target=60.0, RH_tol=5.0, RH_pri=0.5,
                              CO2_target=1000.0)
    target.pop('co2', None)
    report, _ = S.assess(target, internal, _EXT, cycle_sec=60.0,
                         authority=derive_authority(profiles))
    state = C.CoordinatorState(prev_commands=dict(prev))
    for _ in range(3):
        commands, state = C.coordinate(report, profiles, state)
    return report, commands


class TestOutOfRangeHoldsInPlace:

    def test_95도_는_제어에_닿지_않는다(self):
        obj = _coordinator(T_RH)
        internal = _collect(obj, fresh={'mT': 95.0, 'mRH': 60.0})
        assert 'T' not in internal and 'T_raw' not in internal
        assert internal['RH'] == 60.0
        assert obj._indoor_status['T']['status'] == SS.OUT_OF_RANGE

    def test_난방기는_제자리에_선다_근거_21(self):
        obj = _coordinator(T_RH)
        internal = _collect(obj, fresh={'mT': 95.0, 'mRH': 60.0})
        profiles = [_profile('heater', 'h1')]
        report, commands = _decide(internal, profiles, prev={'h1': 40.0})
        assert report.context['T_int'] is None
        assert 'temperature' in report.context['unmeasured']
        assert commands['h1'].reason == REASON_NO_MEASUREMENT
        assert commands['h1'].value == pytest.approx(40.0)

    def test_같은_95도가_stale_이면_행동은_종전과_같다(self):
        """stale 은 기록 전용 — 값이 없다는 점에서 out_of_range 와 제어가 같고,
        차이는 상태 기록뿐이다."""
        obj = _coordinator(T_RH)
        internal = _collect(obj, fresh={'mRH': 60.0}, stale={'mT': 22.0})
        assert 'T' not in internal
        assert obj._indoor_status['T']['status'] == SS.STALE
        profiles = [_profile('heater', 'h1')]
        _r, commands = _decide(internal, profiles, prev={'h1': 40.0})
        assert commands['h1'].reason == REASON_NO_MEASUREMENT

    def test_outlier_는_기록_전용이라_평균은_종전과_같다(self):
        sensors = [_sensor('d%d' % i, 'm%d' % i, 'temperature') for i in range(4)]
        obj = _coordinator(sensors + [_sensor('dRH', 'mRH', 'humidity')])
        internal = _collect(obj, fresh={'m0': 22.0, 'm1': 22.1, 'm2': 21.9,
                                        'm3': 29.0, 'mRH': 60.0})
        assert internal['T_raw'] == pytest.approx(22.0, abs=0.05)
        assert internal['_spatial_rejected_count'] == 1
        assert obj._indoor_status['T']['counts'][SS.OUTLIER] == 1

    def test_역할_폴백_경로도_범위를_검사한다(self):
        """공간 경로가 빈손일 때 쓰는 `read_facility_sensors` 값에도 같은 검사가 걸린다."""
        obj = _coordinator([_sensor('dT', 'mT', 'temperature')])
        role = {'indoor': {'temp_c': 150.0, 'humidity_pct': 55.0, 'co2_ppm': None}}
        with patch.object(fs, 'read_facility_sensors', return_value=role):
            internal = _collect(obj, fresh={})
        assert 'T' not in internal                       # 150 °C 는 버린다
        assert internal['RH'] == 55.0
        assert obj._indoor_status['RH']['via'] == 'role_fallback'
        assert obj._indoor_status['T']['status'] == SS.OUT_OF_RANGE


# ─────────────────────────────────────────────────────────────────────────────
# 3. 실외 컨텍스트 — 공유 컨텍스트 값도 같은 검사를 지난다
# ─────────────────────────────────────────────────────────────────────────────

class _ExtHost:
    """`_collect_external_context` 가 쓰는 속성만 가진 대역."""

    def __init__(self, outdoor=False):
        import logging
        from aot.functions.utils.env_control.ext_context_fallback import (
            ExtContextCache)
        self.logger = logging.getLogger('test.sensor_status')
        self._sensors_resolved_outdoor = [{'input_uuid': 'wx'}] if outdoor else []
        self._ext_cache = ExtContextCache()


def _collect_external(host, shared, od=None):
    import time
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
        CycleMixin)
    shared = dict(shared, last_ext_ts=time.time())
    with patch('aot.functions.ext_context_collector.get_shared_context',
               return_value=shared), \
         patch('aot.functions.ext_context_collector.shared_context_is_current',
               return_value=True), \
         patch.object(fs, 'read_outdoor_sensors', return_value=od or {}):
        return CycleMixin._collect_external_context(host, None)


class TestExternalContextRange:

    def test_공유_컨텍스트의_범위_밖_값은_키째_빠진다(self):
        host = _ExtHost()
        external, _ = _collect_external(
            host, {'T_ext': 150.0, 'RH_ext': 55.0, 'wind': -4.0, 'rain': 0.0})
        for k in ('T_ext', 'T', 'wind'):
            assert k not in external
        assert external['RH_ext'] == 55.0 and external['RH'] == 55.0
        st = host._outdoor_status
        assert st['T_ext']['status'] == SS.OUT_OF_RANGE
        assert st['wind']['status'] == SS.OUT_OF_RANGE
        assert st['RH_ext']['status'] == SS.VALID
        assert st['solar']['status'] == SS.MISSING

    def test_RH_101_은_100_으로_자르고_RH_별칭도_같다(self):
        host = _ExtHost()
        external, _ = _collect_external(host, {'T_ext': 10.0, 'RH_ext': 101.0})
        assert external['RH_ext'] == 100.0 and external['RH'] == 100.0

    def test_센서가_낡았어도_공유_컨텍스트가_값을_주면_축은_valid(self):
        host = _ExtHost(outdoor=True)
        od = {'T_ext': None, 'RH_ext': None, 'rain_mm': None, 'wind_ms': None,
              'wind_deg': None, 'solar_wm2': None,
              'status': {a: SS.summarize([SS.STALE]) for a in SS.OUTDOOR_AXES}}
        _ext, _od = _collect_external(host, {'T_ext': 10.0, 'RH_ext': 55.0}, od=od)
        st = host._outdoor_status
        assert st['T_ext']['status'] == SS.VALID
        assert st['wind']['status'] == SS.STALE

    def test_스냅샷은_열_개_축과_VPD_출처를_싣는다(self):
        host = _ExtHost()
        _collect_external(host, {'T_ext': 10.0})
        host._indoor_status = SS.indoor_summary({'T': 22.0}, {}, {}, SS.VPD_NONE)
        host._vpd_source = SS.VPD_NONE
        snap = SS.snapshot(host)
        assert set(snap['axes']) == set(SS.ALL_AXES)
        assert snap['vpd_source'] == 'none' and snap['vpd_device_diff'] is None
