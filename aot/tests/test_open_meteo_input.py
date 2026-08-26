# coding=utf-8
"""Open-Meteo 입력 — 단위와 시각 선택 (2026-08-25).

## 왜 만들었나

일사(W/m²)를 주는 무료 소스가 필요했다. 일소 잠금(`safety_gates`)은 광량으로
습윤형 분무를 막는데, 광센서가 없는 설치에는 태양고도로 어림한 맑은날 값밖에
없고 그것은 **구름을 무시**한다.

## 이 테스트가 지키는 것

**① 단위.** Open-Meteo 의 기본 풍속 단위는 **km/h** 다. 요청에 명시하지
않으면 `m_s` 로 선언한 채널에 3.6 배 값이 조용히 들어간다 — 실제로 첫 판본이
그랬고 응답의 `hourly_units` 를 대조해서야 발견했다. 에러가 없고, 값도 그럴듯한
크기라 화면만 봐서는 모른다.

**② 시각 선택.** `hourly` 배열에서 **지나온 마지막 정시**를 골라야 한다.
미래 행을 고르면 아직 오지 않은 날씨로 제어하게 된다.

⚠ 네트워크를 쓰지 않는다. 실제 응답 형태를 고정한 표본으로만 본다 — API 가
살아 있는지는 이 테스트의 관심사가 아니고, CI 가 외부 서비스에 매달리면
그쪽이 흔들릴 때마다 빨간불이 된다.
"""
from datetime import datetime, timezone

import pytest

from aot.inputs.open_meteo_weather import (
    INPUT_INFORMATION, _HOURLY_VARS, InputModule, measurements_dict,
)

# 2026-08-25 구마모토(32.8, 130.7) 실제 응답에서 뽑은 단위.
# `wind_speed_unit=ms` 를 명시했을 때의 값이다.
OBSERVED_UNITS = {
    'temperature_2m': '°C',
    'relative_humidity_2m': '%',
    'shortwave_radiation': 'W/m²',
    'wind_speed_10m': 'm/s',
    'wind_direction_10m': '°',
    'precipitation': 'mm',
    'vapour_pressure_deficit': 'kPa',
    'dew_point_2m': '°C',
}

# 선언 단위 → API 단위. 여기 어긋나면 값이 조용히 배수로 틀어진다.
UNIT_MATCH = {
    'C': '°C', 'percent': '%', 'W_m2': 'W/m²', 'm_s': 'm/s',
    'bearing': '°', 'mm': 'mm', 'kPa': 'kPa',
}


class TestUnitsAreExplicit:
    """① 기본값에 기대지 않는다."""

    def test_풍속_단위를_요청에_명시한다(self):
        """Open-Meteo 기본이 km/h 라 안 적으면 3.6 배가 들어온다."""
        import inspect
        src = inspect.getsource(InputModule.get_measurement)
        assert "'wind_speed_unit': 'ms'" in src, (
            '풍속 단위를 명시하지 않으면 km/h 가 m_s 채널에 들어간다')

    def test_온도_강수_단위도_함께_못박는다(self):
        import inspect
        src = inspect.getsource(InputModule.get_measurement)
        assert "'temperature_unit': 'celsius'" in src
        assert "'precipitation_unit': 'mm'" in src

    def test_선언_단위가_API_단위와_맞는다(self):
        """실측한 응답 단위와 `measurements_dict` 선언을 대조한다."""
        bad = []
        for ch, var in _HOURLY_VARS.items():
            declared = measurements_dict[ch]['unit']
            api = OBSERVED_UNITS[var]
            if UNIT_MATCH.get(declared) != api:
                bad.append('ch%s %s: 선언 %s ↔ API %s' % (ch, var, declared, api))
        assert not bad, bad

    def test_모든_채널이_변수에_대응한다(self):
        """채널만 늘리고 변수를 안 넣으면 그 채널은 영원히 빈다."""
        assert set(_HOURLY_VARS) == set(measurements_dict)


class TestRowSelection:
    """② 지나온 마지막 정시를 고른다."""

    TIMES = ['2026-08-25T10:00', '2026-08-25T11:00',
             '2026-08-25T12:00', '2026-08-25T13:00']

    def _pick(self, hh, mm=30):
        now = datetime(2026, 8, 25, hh, mm, tzinfo=timezone.utc)
        return InputModule._pick_row(self.TIMES, now)

    def test_현재_시각이_속한_행(self):
        assert self._pick(12) == 2

    def test_정시_정각도_그_행이다(self):
        assert self._pick(12, 0) == 2

    def test_미래_행을_고르지_않는다(self):
        """아직 오지 않은 날씨로 제어하면 안 된다."""
        assert self._pick(11, 59) == 1

    def test_마지막_행_이후면_마지막_행(self):
        assert self._pick(23) == 3

    def test_모든_행이_미래면_None(self):
        now = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        assert InputModule._pick_row(self.TIMES, now) is None

    def test_빈_입력에_죽지_않는다(self):
        now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        assert InputModule._pick_row(None, now) is None
        assert InputModule._pick_row([], now) is None

    def test_망가진_시각_문자열은_건너뛴다(self):
        now = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
        assert InputModule._pick_row(
            ['쓰레기', '2026-08-25T12:00'], now) == 1


class TestRegistration:
    """시스템이 이 모듈을 실제로 집는가."""

    def test_필수_키가_있다(self):
        for k in ('input_name_unique', 'input_manufacturer', 'input_name',
                  'measurements_dict', 'options_enabled'):
            assert k in INPUT_INFORMATION, k

    def test_좌표_옵션이_켜져_있다(self):
        """좌표가 없으면 아무 값도 못 받는다."""
        assert 'coordinates' in INPUT_INFORMATION['options_enabled']

    def test_API_키는_선택이다(self):
        """무료 비상업 사용이 기본 경로다 — 필수로 만들면 못 쓴다."""
        opt = next(o for o in INPUT_INFORMATION['custom_options']
                   if o['id'] == 'api_key')
        assert opt['required'] is False


def test_일사_채널이_있다():
    """이 모듈을 만든 이유다 — 없으면 존재 의의가 없다."""
    solar = [ch for ch, m in measurements_dict.items()
             if m['measurement'] == 'light' and m['unit'] == 'W_m2']
    assert solar, '일사(W/m²) 채널이 없다'
    assert _HOURLY_VARS[solar[0]] == 'shortwave_radiation'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
