# coding=utf-8
"""제어 VPD 의 출처 — 걸러진 실내 T/RH 에서 계산한 **공기 VPD** 가 기본이다.

장치(센서)가 준 VPD 채널 중에는 `auto_vpd` 처럼 엽온(기온 - 1.5 °C) 기준으로
계산한 것이 있다. 공기 VPD 보다 0.1~0.45 kPa(10~35 °C; 2026-10-09 전 식은 0.04~0.23) 낮은데, 목표와
`decompose_vpd_to_T_RH` 는 공기 VPD 를 가정한다. 그래서:

  - T 와 RH 가 있으면 장치 VPD 가 얼마든 제어는 `psychro` 계산값을 쓴다
    (장치 VPD 와의 차이는 진단 채널로만 남긴다).
  - T 또는 RH 를 잃고 장치 VPD 만 살아 있을 때만 그것으로 잇는다(출처 `device`).
  - 화면이 읽는 `compute_spatial_internal()['VPD']` 의 뜻은 그대로다.
"""
import pytest

from aot.utils import sensor_status as SS
from aot.functions.utils.env_control.situation import compute_vpd

from .test_sensor_status_flow import (   # noqa: F401 — 하니스와 autouse 픽스처 재사용
    T_RH, _coordinator, _collect, _no_db, _sensor, _spatial,
)

VPD_SENSORS = T_RH + [_sensor('dV', 'mV', 'vpd')]


class TestVpdSource:

    def test_장치_VPD_가_달라도_제어는_T_RH_로_계산한다(self):
        """엽온 기준 VPD(공기보다 낮다)가 와도 제어 VPD 는 공기 VPD 다."""
        obj = _coordinator(VPD_SENSORS)
        air = compute_vpd(25.0, 70.0)
        leaf = round(air - 0.2, 3)
        internal = _collect(obj, fresh={'mT': 25.0, 'mRH': 70.0, 'mV': leaf})
        assert internal['VPD'] == pytest.approx(air, abs=2e-3)
        assert internal['VPD'] != pytest.approx(leaf, abs=0.05)
        assert obj._vpd_source == SS.VPD_COMPUTED

    def test_차이는_진단으로_남는다_장치_빼기_제어(self):
        obj = _coordinator(VPD_SENSORS)
        air = compute_vpd(25.0, 70.0)
        _collect(obj, fresh={'mT': 25.0, 'mRH': 70.0, 'mV': round(air - 0.2, 3)})
        assert obj._vpd_device_diff == pytest.approx(-0.2, abs=3e-3)
        snap = SS.snapshot(obj)
        assert snap['vpd_source'] == 'computed'
        assert snap['axes']['VPD']['source'] == 'computed'
        assert snap['axes']['VPD']['device'] == SS.VALID

    def test_장치_VPD_가_없어도_계산이다_차이는_None(self):
        obj = _coordinator(T_RH)
        internal = _collect(obj, fresh={'mT': 25.0, 'mRH': 70.0})
        assert internal['VPD'] == pytest.approx(compute_vpd(25.0, 70.0), abs=2e-3)
        assert obj._vpd_source == SS.VPD_COMPUTED
        assert obj._vpd_device_diff is None

    def test_RH_를_잃으면_장치_VPD_로_잇고_출처를_밝힌다(self):
        obj = _coordinator(VPD_SENSORS)
        internal = _collect(obj, fresh={'mT': 25.0, 'mV': 0.8})
        assert internal['VPD'] == pytest.approx(0.8)
        assert 'RH' not in internal
        assert obj._vpd_source == SS.VPD_DEVICE
        assert SS.snapshot(obj)['axes']['VPD']['status'] == SS.VALID

    def test_T_RH_도_장치도_없으면_출처는_none(self):
        obj = _coordinator(VPD_SENSORS)
        internal = _collect(obj, fresh={})
        assert 'VPD' not in internal
        assert obj._vpd_source == SS.VPD_NONE
        assert SS.snapshot(obj)['axes']['VPD']['status'] == SS.MISSING

    def test_범위_밖_장치_VPD_는_폴백으로도_쓰지_않는다(self):
        obj = _coordinator(VPD_SENSORS)
        internal = _collect(obj, fresh={'mT': 25.0, 'mV': 55.0})
        assert 'VPD' not in internal
        assert obj._vpd_source == SS.VPD_NONE
        assert obj._indoor_status['VPD']['device'] == SS.OUT_OF_RANGE

    def test_T_가_범위_밖이면_계산하지_않고_장치_VPD_로_잇는다(self):
        obj = _coordinator(VPD_SENSORS)
        internal = _collect(obj, fresh={'mT': 95.0, 'mRH': 60.0, 'mV': 0.9})
        assert 'T' not in internal
        assert internal['VPD'] == pytest.approx(0.9)
        assert obj._vpd_source == SS.VPD_DEVICE


class TestSpatialVpdKeysForDisplay:
    """화면이 읽는 `VPD` 의 뜻은 그대로다 — 새 키 둘이 따로 붙는다."""

    def test_VPD_는_장치값이_있으면_장치값(self):
        sp = _spatial(VPD_SENSORS, fresh={'mT': 25.0, 'mRH': 70.0, 'mV': 0.6})
        assert sp['VPD'] == 0.6 and sp['vpd_measured'] is True
        assert sp['VPD_device'] == 0.6
        assert sp['VPD_calc'] == pytest.approx(compute_vpd(25.0, 70.0), abs=2e-3)

    def test_장치값이_없으면_계산값(self):
        sp = _spatial(T_RH, fresh={'mT': 25.0, 'mRH': 70.0})
        assert sp['vpd_measured'] is False and sp['VPD_device'] is None
        assert sp['VPD'] == sp['VPD_calc']


