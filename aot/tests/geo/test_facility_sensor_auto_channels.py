# coding=utf-8
"""장치를 고르면 그 장치의 채널을 시스템이 해석한다 (2026-08-26).

## 무엇이 문제였나

화면은 **"이 장치를 실내/실외 센서로 쓴다"** 를 고르게 한다. 그런데 백엔드는
`channel_measurements` 에 체크된 채널만 읽었다. 그래서 기상대를 실외 센서로
지정해도, 그때 체크된 채널 하나만 살고 나머지는 **없는 것**이 됐다.

없으면 조용히 지어냈다 — `ext_context_fallback` 이 실외를 실내로 채운다.
그 위에서 모든 판단이 돌았다.

실측(2026-08-26 イチゴ):

    気象台 channel_measurements = [light]        ← 하나뿐
    read_outdoor_sensors → T_ext=null RH_ext=null wind_ms=null wind_deg=null

    그 결과
      · 내외 차가 0 이라 환기 무익 판정 → 창이 닫힌다
      · 풍향이 기본 0°(정북) → 북향이 아닌 측창이 영구 leeward (가중치 0.2)
      · 실외 VPD 0.87 이라는 정보가 사라져, 창으로 될 일을 난방기가 한다

바인딩된 Input(Kumamoto)에는 온도·습도·풍속·풍향·강우가 **전부 들어와 있었다.**
장치 이름이 무엇이든 uuid + 채널로 해석할 수 있는 정보였다.

## 고친 형태

명시 선택은 그대로 두고, **남은 종류만** 장치에서 자동으로 채운다.

⚠ **모호하면 자동 해석하지 않는다.** 같은 종류의 채널이 둘 이상인 장치(예:
temp1f~temp6f 를 한꺼번에 내보내는 기상 콘솔)에서 전부 끌어오면 서로 다른
자리의 값이 한 평균으로 섞인다. 그건 사용자가 골라야 할 판단이다.

⚠ **자동으로 채운 것은 `auto: True` 로 표시한다.** 조용히 채우면 지어내던 것과
같은 문제가 된다 — 화면이 무엇이 어떻게 읽히는지 말할 수 있어야 한다.
"""
import pytest

from aot.aot_flask.geo import facility_integration as fi


class _DM:
    """DeviceMeasurements 흉내 — 자동 해석은 `measurement` 이름만 본다."""
    def __init__(self, uid, device_id, measurement):
        self.unique_id = uid
        self.device_id = device_id
        self.measurement = measurement


def test_추론표가_기상_채널을_안다():
    """자동 해석의 전제 — 이 표에 없으면 아무리 채널이 있어도 못 채운다."""
    for name, expect in (('temperature', 'temperature'),
                         ('humidity', 'humidity'),
                         ('speed', 'wind_speed'),
                         ('direction', 'wind_direction')):
        assert fi._infer_mtype_from_dm(_DM('m', 'd', name)) == expect, name


class TestCompositeNamesFallBackToWordMatching(object):
    """미러(MQTT_PAHO_JSON) 등 원시 이름이 그대로 들어오는 장치는
    `solar_radiation` 처럼 알려진 낱말에 접두/접미가 붙은 복합 이름을 쓴다.
    완전일치가 실패하면 '_'/'-'/공백/'.' 로 나눈 낱말 단위로 다시 찾는다.
    """

    def test_a_compound_name_resolves_via_its_word(self):
        assert fi._infer_mtype_from_dm(
            _DM('m', 'd', 'solar_radiation')) == 'light'
        assert fi._infer_mtype_from_dm(
            _DM('m', 'd', 'wind-speed-avg')) == 'wind_speed'

    def test_exact_match_is_tried_first(self):
        """낱말 단위 폴백을 켰다고 완전일치 우선순위가 바뀌면 안 된다."""
        assert fi._infer_mtype_from_dm(_DM('m', 'd', 'light')) == 'light'

    def test_it_never_matches_a_substring(self):
        """`par` 는 표에 있는 낱말이다('light' 로 매핑) — 부분 문자열까지
        허용하면 `parameter` 안에서 우연히 걸린다. 낱말 전체가 '_'/'-'/공백/
        '.' 로 갈라져 나와야만 그 낱말로 인정한다."""
        assert fi._infer_mtype_from_dm(_DM('m', 'd', 'parameter')) is None
        assert fi._infer_mtype_from_dm(_DM('m', 'd', 'some_parameter_x')) is None

    def test_no_word_in_the_table_returns_none(self):
        assert fi._infer_mtype_from_dm(_DM('m', 'd', 'unknown_channel_9')) is None

    def test_empty_or_missing_name_does_not_raise(self):
        assert fi._infer_mtype_from_dm(_DM('m', 'd', '')) is None
        assert fi._infer_mtype_from_dm(None) is None


class TestAutoChannelSelection:
    """실제 함수(`auto_channels_for_device`)를 부른다 — 규칙을 재현하지 않는다.

    테스트가 구현을 베껴 쓰면 둘이 조용히 갈라지고, 갈라지면 테스트가 통과해도
    아무것도 보장하지 않는다.
    """

    @staticmethod
    def _auto(rows, explicit_types):
        return {c['measurement_type']: c['measurement_id']
                for c in fi.auto_channels_for_device(rows, explicit_types)}

    def _weather_station(self):
        return [_DM('m_t', 'kum', 'temperature'),
                _DM('m_h', 'kum', 'humidity'),
                _DM('m_l', 'kum', 'light'),
                _DM('m_s', 'kum', 'speed'),
                _DM('m_d', 'kum', 'direction'),
                _DM('m_r', 'kum', 'rain')]

    def test_안_묶인_종류를_채운다(self):
        """실사고 재현 — light 만 명시된 기상대."""
        got = self._auto(self._weather_station(), {'light'})
        assert set(got) == {'temperature', 'humidity',
                            'wind_speed', 'wind_direction', 'rain'}

    def test_명시_선택은_덮어쓰지_않는다(self):
        """사용자가 고른 것이 언제나 이긴다."""
        got = self._auto(self._weather_station(), {'light', 'temperature'})
        assert 'temperature' not in got

    def test_같은_종류가_둘이면_고르지_않는다(self):
        """temp1f~temp6f 를 전부 평균내면 서로 다른 자리의 값이 섞인다."""
        rows = [_DM('m1', 'ec', 'temperature'), _DM('m2', 'ec', 'temperature'),
                _DM('m3', 'ec', 'humidity')]
        got = self._auto(rows, set())
        assert 'temperature' not in got, '모호한데 골랐다'
        assert got.get('humidity') == 'm3', '모호하지 않은 것까지 막으면 안 된다'

    def test_메타_채널은_끌어오지_않는다(self):
        """배터리·신호세기는 사용자가 "센서로 쓴다" 고 고른 대상이 아니다.

        ⚠ `_DM_NAME_TO_MTYPE` 에는 **일부러** rssi/snr/battery 가 들어 있다
        (장치 상태 표시가 그 표로 채널을 찾는다). 그래서 추론표만 믿고 자동
        해석하면 고르지도 않은 채널이 센서 목록에 나타난다 — 이 테스트가
        처음 돌 때 실제로 그랬다. 별도 허용 목록이 필요한 이유다.
        """
        rows = [_DM('m1', 'x', 'battery'), _DM('m2', 'x', 'rssi'),
                _DM('m3', 'x', 'pressure'), _DM('m4', 'x', 'temperature')]
        assert self._auto(rows, set()) == {'temperature': 'm4'}

    def test_허용_목록이_추론표보다_좁다(self):
        """넓히려면 '자동으로 끌어와도 되는가' 를 종류마다 판단해야 한다."""
        assert fi._AUTO_RESOLVABLE_MTYPES < set(fi._DM_NAME_TO_MTYPE.values())


class TestContract:
    """배선이 조용히 되돌아가지 않게 소스로 고정한다."""

    def _src(self):
        import inspect
        return inspect.getsource(fi)

    def test_자동_해석이_실제로_배선돼_있다(self):
        src = self._src()
        assert '_auto_channels' in src and '_explicit_by_role' in src, (
            '장치의 나머지 채널을 해석하는 경로가 사라졌다')

    def test_명시_선택이_역할_전체에서_이긴다(self):
        """센서를 둘로 나눠 단 설치에서 자동 해석이 남의 몫을 끌어오면 안 된다.

        실측(2026-08-26 イチゴ):
            気象台1  [temperature, humidity, wind_speed, wind_direction] ← 직접
            気象台2  [light, rain]                                       ← 직접
        気象台2 의 자동 해석이 온도·바람을 또 올려 두 장치가 **평균**됐다 —
        풍속 7.2 와 1.92 가 4.56 이 되어, 직접 고른 값이 조용히 희석됐다.
        """
        src = self._src()
        i = src.index('_explicit_by_role')
        window = src[i:i + 1400]
        assert '_explicit_by_role.get(role' in window, (
            'fitting 하나 안에서만 판정하고 있다 — 역할 전체로 넓힐 것')

    def test_자동_해석도_역할_안에서_한_번만_한다(self):
        """장치가 셋이면 자동 해석이 같은 종류를 셋 올려 또 평균된다."""
        src = self._src()
        assert '_auto_taken' in src

    def test_모호할_때_거르는_규칙이_남아_있다(self):
        """행동으로도 고정돼 있지만(위 클래스) 규칙 자체를 소스로도 못박는다."""
        import inspect
        body = inspect.getsource(fi.auto_channels_for_device)
        assert 'len(rows) == 1' in body, (
            '같은 종류가 여럿일 때 거르는 규칙이 사라졌다 — 서로 다른 자리의 '
            '값이 한 평균으로 섞인다')

    def test_자동_여부를_표시한다(self):
        assert "'auto':" in self._src(), (
            '조용히 채우면 지어내던 것과 같은 문제가 된다')


class TestMissingOutdoorWarning:
    """자동 해석으로도 못 채우면 **시끄럽게** 알린다."""

    def test_실외_센서가_없으면_경고하지_않는다(self):
        """실외를 안 쓰는 설치는 정상이다 — 여기서 경고하면 노이즈가 된다."""
        from aot.functions.custom_functions.env_coordinator_impl import (
            _profile_loader_mixin as m)
        assert m._missing_outdoor_channels([]) == []

    def test_반만_묶였으면_빠진_것을_말한다(self):
        from aot.functions.custom_functions.env_coordinator_impl import (
            _profile_loader_mixin as m)
        missing = m._missing_outdoor_channels(
            [{'measurement_type': 'light'}])
        assert len(missing) == 4, missing

    def test_다_묶였으면_조용하다(self):
        from aot.functions.custom_functions.env_coordinator_impl import (
            _profile_loader_mixin as m)
        assert m._missing_outdoor_channels([
            {'measurement_type': 'temperature'},
            {'measurement_type': 'humidity'},
            {'measurement_type': 'wind_speed'},
            {'measurement_type': 'wind_direction'},
        ]) == []

    def test_경고는_ERROR_로_남긴다(self):
        """⚠ 컨트롤러 로거는 기본 ERROR 다 — warning 은 아무 데도 안 남는다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import (
            _profile_loader_mixin as m)
        src = inspect.getsource(m)
        i = src.index('_outdoor_missing = _missing_outdoor_channels')
        assert 'self.logger.error(' in src[i:i + 900], (
            'warning 으로 남기면 기본 설치에서 보이지 않는다')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
