# coding=utf-8
"""센서 판독 상태 분류 — 순수 함수 (`sensor_status`) 와 로그 채널 규약.

다섯 상태(valid/stale/missing/outlier/out_of_range)를 가르는 규칙과 경계값을
고정한다. 여기서 중요한 것은 **행동이 하나만 바뀐다**는 점이다 — out_of_range 만
값이 `None` 이 되고, 나머지는 기록 전용이다.
"""
import math

import pytest

from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import sensor_status as SS


class TestCheckValueBoundaries:

    @pytest.mark.parametrize('kind,value', [
        ('T', -40.0), ('T', 70.0), ('T', 22.5),
        ('RH', 0.0), ('RH', 100.0), ('RH', 55.0),
        ('CO2', 150.0), ('CO2', 10000.0), ('CO2', 420.0),
        ('VPD', 0.0), ('VPD', 10.0),
        ('wind', 0.0), ('wind', 100.0),
        ('rain', 0.0), ('rain', 5000.0),        # 강수 상한은 두지 않는다
        ('light', 0.0), ('light', 3000.0),      # 일사 상한도 두지 않는다
    ])
    def test_경계값은_유효하다(self, kind, value):
        status, v = SS.check_value(kind, value)
        assert status == SS.VALID and v == value

    @pytest.mark.parametrize('kind,value', [
        ('T', -40.01), ('T', 70.01), ('T', 150.0),
        ('RH', -0.1), ('RH', 102.01), ('RH', 130.0),
        ('CO2', 149.9), ('CO2', 10000.1), ('CO2', 0.0),
        ('VPD', -0.01), ('VPD', 10.01),
        ('wind', -0.1), ('wind', 100.1),
        ('rain', -0.1),
        ('light', -5.01), ('light', -300.0),
    ])
    def test_경계_밖은_범위밖이고_값은_None_이다(self, kind, value):
        assert SS.check_value(kind, value) == (SS.OUT_OF_RANGE, None)

    @pytest.mark.parametrize('bad', [None, 'abc', float('nan'),
                                     float('inf'), float('-inf')])
    def test_숫자가_아니면_범위밖이다(self, bad):
        assert SS.check_value('T', bad) == (SS.OUT_OF_RANGE, None)


class TestToleranceClamps:
    """눈금 오차는 고장이 아니다 — 자르고 valid 로 쓴다."""

    def test_RH_101_은_100_으로_자르고_유효하다(self):
        assert SS.check_value('RH', 101.0) == (SS.VALID, 100.0)

    def test_RH_102_까지는_자른다(self):
        assert SS.check_value('RH', 102.0) == (SS.VALID, 100.0)

    def test_RH_130_은_고장이다(self):
        assert SS.check_value('RH', 130.0) == (SS.OUT_OF_RANGE, None)

    def test_일사계_밤_음수_오프셋은_0_으로_올린다(self):
        assert SS.check_value('light', -3.0) == (SS.VALID, 0.0)
        assert SS.check_value('light', -5.0) == (SS.VALID, 0.0)

    def test_허용_안의_자르기는_상수_한_곳에서_온다(self):
        assert SS.RH_OVERSHOOT_MAX == 102.0
        assert SS.LIGHT_NEGATIVE_TOLERANCE == 5.0


class TestAxisStatus:

    def test_축은_쓸_수_있는_것_중_최선이다(self):
        assert SS.best_status([SS.MISSING, SS.STALE, SS.VALID]) == SS.VALID
        assert SS.best_status([SS.MISSING, SS.OUT_OF_RANGE]) == SS.OUT_OF_RANGE
        assert SS.best_status([SS.MISSING, SS.STALE]) == SS.STALE
        assert SS.best_status([SS.OUTLIER, SS.OUT_OF_RANGE]) == SS.OUTLIER

    def test_센서가_없으면_missing_이고_n_이_0_이다(self):
        s = SS.summarize([])
        assert s['status'] == SS.MISSING and s['n'] == 0

    def test_개수를_센다(self):
        s = SS.summarize([SS.VALID, SS.VALID, SS.OUTLIER, SS.STALE])
        assert s == {'status': SS.VALID, 'n': 4,
                     'counts': {SS.VALID: 2, SS.OUTLIER: 1, SS.STALE: 1}}

    def test_두_출처를_합치면_좋은_쪽_이고_개수는_더한다(self):
        a = SS.summarize([SS.STALE])
        b = SS.summarize([SS.VALID])
        m = SS.merge(a, b)
        assert m['status'] == SS.VALID and m['n'] == 2

    def test_범위밖_키를_빼고_나머지는_자른다(self):
        vals = {'T_ext': 150.0, 'RH_ext': 101.0, 'wind': 3.0, 'other': 1}
        out = SS.strip_out_of_range(vals, SS.EXTERNAL_KEY_AXIS)
        assert 'T_ext' not in vals
        assert vals['RH_ext'] == 100.0 and vals['wind'] == 3.0
        assert out['T_ext']['status'] == SS.OUT_OF_RANGE
        assert out['RH_ext']['status'] == SS.VALID
        assert 'solar' not in out        # 없는 키는 검사하지 않는다

    def test_상태_코드는_서로_다르고_valid_가_0_이다(self):
        assert SS.STATUS_CODES[SS.VALID] == 0
        assert len(set(SS.STATUS_CODES.values())) == len(SS.STATUS_CODES) == 6
        assert set(SS.STATUS_ORDER) == set(SS.STATUS_CODES)

    def test_요약이_없으면_missing_코드다(self):
        assert SS.encode(None) == SS.STATUS_CODES[SS.MISSING]

    def test_축_열_개가_범위표와_이어진다(self):
        assert len(SS.ALL_AXES) == 10
        for a in SS.ALL_AXES:
            assert SS.AXIS_KIND[a] in SS.PHYSICAL_RANGE


class TestIndoorSummary:

    def test_VPD_축은_계산이면_T_RH_가_있는_한_유효하다(self):
        out = SS.indoor_summary({'T': 22.0, 'RH': 60.0, 'VPD': 1.0},
                                {'VPD': SS.summarize([SS.OUT_OF_RANGE])},
                                {}, SS.VPD_COMPUTED)
        assert out['VPD']['status'] == SS.VALID
        assert out['VPD']['source'] == SS.VPD_COMPUTED
        assert out['VPD']['device'] == SS.OUT_OF_RANGE      # 장치 채널은 따로 남는다

    def test_센서_요약이_없는_축은_값의_유무로_정한다(self):
        out = SS.indoor_summary({'T': 22.0}, {}, {}, SS.VPD_NONE)
        assert out['T']['status'] == SS.VALID
        assert out['RH']['status'] == SS.MISSING
        assert out['VPD']['status'] == SS.MISSING

    def test_역할_폴백으로_댄_축은_출처를_남긴다(self):
        out = SS.indoor_summary({'T': 22.0}, {}, {'T': 'role_fallback'}, SS.VPD_NONE)
        assert out['T']['via'] == 'role_fallback'


class TestLogChannels:

    def test_채널은_서로_다르고_예약_번호를_피한다(self):
        nums = [LC.ch_sensor_status(a) for a in LC.SENSOR_STATUS_AXES]
        nums += [LC.CH_VPD_SOURCE, LC.CH_VPD_DEVICE_DIFF]
        assert len(set(nums)) == len(nums)
        # 75·76 은 극한 고온 보호가 예약했다.
        assert not ({75, 76} & set(nums))
        assert min(nums) >= 80

    def test_축_순서가_상태_모듈과_같다(self):
        assert tuple(LC.SENSOR_STATUS_AXES) == SS.ALL_AXES

    def test_모르는_축은_조용히_다른_번호로_가지_않는다(self):
        with pytest.raises(ValueError):
            LC.ch_sensor_status('nope')

    def test_기록은_열_축과_VPD_출처를_쓴다(self, monkeypatch):
        calls = []
        monkeypatch.setattr(LC, '_safe_write',
                            lambda uid, meas, val, ch=None, extra=None:
                            calls.append((meas, ch, val)))
        LC.write_sensor_status('u1', {
            'axes': {'T': {'status': SS.OUT_OF_RANGE}, 'RH': {'status': SS.VALID}},
            'vpd_source': SS.VPD_COMPUTED, 'vpd_device_diff': -0.12})
        by_ch = {ch: val for _m, ch, val in calls}
        assert {m for m, _c, _v in calls} == {LC.MEAS_SENSOR_STATUS}
        assert by_ch[LC.ch_sensor_status('T')] == 4.0
        assert by_ch[LC.ch_sensor_status('RH')] == 0.0
        assert by_ch[LC.ch_sensor_status('solar')] == 2.0     # 빠진 축은 missing
        assert by_ch[LC.CH_VPD_SOURCE] == 1.0
        assert math.isclose(by_ch[LC.CH_VPD_DEVICE_DIFF], -0.12)
        assert len(calls) == 10 + 2

    def test_장치_VPD_가_없으면_차이_채널을_쓰지_않는다(self, monkeypatch):
        calls = []
        monkeypatch.setattr(LC, '_safe_write',
                            lambda uid, meas, val, ch=None, extra=None:
                            calls.append(ch))
        LC.write_sensor_status('u1', {'axes': {}, 'vpd_source': 'none',
                                      'vpd_device_diff': None})
        assert LC.CH_VPD_DEVICE_DIFF not in calls

    def test_기록이_터져도_예외를_던지지_않는다(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError('influx down')
        monkeypatch.setattr(LC, '_safe_write', boom)
        LC.write_sensor_status('u1', {'axes': {}, 'vpd_source': 'none'})
