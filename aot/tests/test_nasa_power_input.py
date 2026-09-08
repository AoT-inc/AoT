# coding=utf-8
"""NASA POWER 입력 — ET0 산식과 결측 처리 (2026-09-07).

## 왜 만들었나

관개량 산정의 기준값인 **FAO-56 기준증발산 ET0** 를 주는 입력이 없었다.
POWER 에도 ET0 파라미터는 없어서(2026-09 실측: AG 일 단위 152개 중 증발산
계열은 `EVLAND`·`EVPTRNS` 뿐) 이 모듈이 직접 계산한다. 계산이 틀리면 값은
그럴듯한 크기로 나오고 아무도 모른다 — 그래서 **문서에 published 된 값**과
대조한다.

## 이 테스트가 지키는 것

**① 산식.** FAO-56 예제(Ra 41.09 / 38.06, ET0 3.9mm)를 재현한다. 계수 하나를
잘못 옮기면 여기서 걸린다.

**② 결측.** POWER 는 미보고값을 `-999.0` 으로 채운다(응답 헤더 `fill_value`).
그대로 받으면 기온 -999°C 가 실측값이 된다 — 기상청 자료에서 이미 겪은 사고다.
게다가 **끝쪽 며칠이 통째로 결측인 것이 정상**이라(실측: 오늘 기준 7~13일
지연), 가장 최근 날짜만 보고 포기하면 이 입력은 늘 빈손이 된다.

⚠ 네트워크를 쓰지 않는다. 실제 응답에서 뽑은 표본으로만 본다.
"""
import pytest

from aot.inputs.nasa_power import (
    INPUT_INFORMATION, _MJ_PER_DAY_TO_W_M2, _PARAM_BY_CHANNEL, InputModule,
    _valid, extraterrestrial_radiation, measurements_dict, reference_et0,
)


class TestFao56:
    """① 산식 — FAO-56 문서의 예제 값을 재현한다."""

    def test_대기외일사_브뤼셀_7월(self):
        """FAO-56 Example 18: 50°48'N, 7월 6일 → Ra = 41.09 MJ/m²/day."""
        assert extraterrestrial_radiation(50.8, 187) == pytest.approx(41.09, abs=0.02)

    def test_대기외일사_방콕_4월(self):
        """FAO-56 Example 17: 13°44'N, 4월 15일 → Ra = 38.06 MJ/m²/day."""
        assert extraterrestrial_radiation(13.73, 105) == pytest.approx(38.06, abs=0.02)

    def test_극지방에서_죽지_않는다(self):
        """백야·극야에서는 arccos 인자가 [-1,1] 을 벗어난다."""
        assert extraterrestrial_radiation(89.0, 172) > 0     # 백야
        assert extraterrestrial_radiation(89.0, 355) == pytest.approx(0, abs=0.5)

    def test_ET0_브뤼셀_예제(self):
        """FAO-56 Example 18 → 3.9 mm/day.

        문서는 RHmax/RHmin 을 쓰고 POWER 는 일평균 습도만 주므로 ea 가 조금
        커진다(1.47 ↔ 1.41 kPa). 그만큼 ET0 가 낮게 나오는 것이 정상이라
        허용오차를 0.1 로 둔다 — 이보다 벌어지면 산식이 틀린 것이다.
        """
        et0 = reference_et0(
            t_mean=(21.5 + 12.3) / 2, t_max=21.5, t_min=12.3,
            rh_mean=(84 + 63) / 2, wind_2m=2.78, solar_mj=22.07,
            lat_deg=50.8, elevation_m=100, day_of_year=187)
        assert et0 == pytest.approx(3.9, abs=0.1)

    def test_한여름_한국_필지가_그럴듯한_범위(self):
        """2026-08-25 POWER 실측값(35.8N, 127.0E)으로 계산."""
        et0 = reference_et0(
            t_mean=28.01, t_max=32.01, t_min=24.62, rh_mean=80.93,
            wind_2m=0.98, solar_mj=20.41, lat_deg=35.8,
            elevation_m=35.85, day_of_year=237)
        assert 3.0 < et0 < 6.0, et0

    def test_흐린_날은_ET0_가_낮다(self):
        """일사만 낮춘 같은 날은 반드시 더 작아야 한다."""
        common = dict(t_mean=28.0, t_max=32.0, t_min=24.6, rh_mean=81.0,
                      wind_2m=1.0, lat_deg=35.8, elevation_m=36,
                      day_of_year=237)
        assert reference_et0(solar_mj=6.7, **common) < reference_et0(
            solar_mj=20.4, **common)


class TestMissingValues:
    """② 결측(-999) — 값으로 새어 들어가면 안 된다."""

    def test_센티널을_버린다(self):
        assert _valid(-999.0) is None
        assert _valid('-999') is None
        assert _valid(-901) is None

    def test_정상값은_통과한다(self):
        assert _valid(28.01) == 28.01
        assert _valid('0') == 0.0
        # 실제로 있을 수 있는 저온. -900 아래만 결측으로 본다.
        assert _valid(-40.0) == -40.0

    def test_숫자가_아니면_결측(self):
        assert _valid(None) is None
        assert _valid('') is None
        assert _valid('nan') is None


class TestLatestDay:
    """② 끝쪽 며칠이 결측인 것이 POWER 의 정상 상태다."""

    # 실제 응답 모양: 최근 날짜가 통째로 -999.
    BLOCK = {
        'T2M': {'20260823': 28.3, '20260824': 28.56, '20260825': 28.01,
                '20260826': -999.0, '20260827': -999.0},
        'RH2M': {'20260823': 81.65, '20260824': 79.67, '20260825': 80.93,
                 '20260826': -999.0, '20260827': -999.0},
    }

    def test_결측일을_건너뛰고_최근_유효일을_고른다(self):
        date_str, row = InputModule._pick_latest_day(
            self.BLOCK, ['T2M', 'RH2M'])
        assert date_str == '20260825'
        assert row == {'T2M': 28.01, 'RH2M': 80.93}

    def test_한_항목만_결측이어도_그_날은_안_쓴다(self):
        """ET0 는 다섯 값이 다 있어야 계산된다 — 반쪽 날짜는 쓸 수 없다."""
        block = {
            'T2M': {'20260824': 28.56, '20260825': 28.01},
            'RH2M': {'20260824': 79.67, '20260825': -999.0},
        }
        date_str, _row = InputModule._pick_latest_day(block, ['T2M', 'RH2M'])
        assert date_str == '20260824'

    def test_전부_결측이면_None(self):
        block = {'T2M': {'20260826': -999.0, '20260827': -999.0}}
        date_str, row = InputModule._pick_latest_day(block, ['T2M'])
        assert date_str is None and row is None


class TestUnits:
    """선언 단위와 API 단위가 어긋나면 값이 조용히 배수로 틀어진다."""

    def test_일사_변환이_하루_평균_W_m2(self):
        """POWER 는 MJ/m²/day, 채널은 W/m². 1 W/m² = 0.0864 MJ/m²/day."""
        assert 1.0 * _MJ_PER_DAY_TO_W_M2 == pytest.approx(11.574, abs=0.001)
        # 여름 맑은 날 20.41 MJ → 약 236 W/m² (하루 평균이라 정오값보다 작다)
        assert 20.41 * _MJ_PER_DAY_TO_W_M2 == pytest.approx(236.2, abs=0.5)

    def test_증발산_측정항목이_시스템에_등록돼_있다(self):
        """없으면 채널 0 이 저장 단계에서 조용히 버려진다."""
        from aot.config_devices_units import MEASUREMENTS
        assert 'evapotranspiration' in MEASUREMENTS
        assert 'mm' in MEASUREMENTS['evapotranspiration']['units']

    def test_모든_채널이_선언된_측정항목을_쓴다(self):
        from aot.config_devices_units import MEASUREMENTS, UNITS
        for channel, info in measurements_dict.items():
            assert info['measurement'] in MEASUREMENTS, channel
            assert info['unit'] in UNITS, channel


class TestRegistration:
    """시스템이 이 모듈을 실제로 집는가."""

    def test_필수_키가_있다(self):
        for key in ('input_name_unique', 'input_manufacturer', 'input_name',
                    'measurements_dict', 'options_enabled'):
            assert key in INPUT_INFORMATION, key

    def test_좌표_옵션이_켜져_있다(self):
        assert 'coordinates' in INPUT_INFORMATION['options_enabled']

    def test_ET0_채널은_POWER_파라미터가_아니다(self):
        """ET0 는 계산값이라 파라미터 표에 있으면 안 된다(있으면 -999 를 받는다)."""
        assert 0 not in _PARAM_BY_CHANNEL
        assert measurements_dict[0]['measurement'] == 'evapotranspiration'

    def test_계산_외_채널은_모두_파라미터에_대응한다(self):
        """채널만 늘리고 파라미터를 안 넣으면 그 채널은 영원히 빈다."""
        assert set(_PARAM_BY_CHANNEL) | {0} == set(measurements_dict)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
