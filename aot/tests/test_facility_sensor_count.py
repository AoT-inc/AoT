# coding=utf-8
"""[현재] 블록이 센서를 **세는 방식**과 무엇을 보이는가.

2026-08-20 육묘장에서 나온 둘:

1. 바닥센서 하나가 이슬점·풍속만 재는데 "센서 응답 4/5" 로 셌다. 그 센서는
   멀쩡히 응답하고 [환경·제어] 탭에는 값이 다 보인다 — 세는 기준이 "실내 환경
   평균에 쓰이는 다섯 키(T/RH/CO2/VPD/light) 중 하나라도 있나" 였기 때문이다.
   문구는 "센서 응답" 인데 세는 것은 **환경 기여**였다. 사용자는 멀쩡한 장치를
   찾아 헤맨다.
2. VPD 를 재고 있는데 [현재]에 안 나왔다 — 화면이 온·습도·CO2 만 읽었다.
   VPD 는 이 시설의 **1차 제어 목표**다.
"""
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')


def _read(path):
    with open(os.path.join(_ROOT, path), encoding='utf-8') as fh:
        return fh.read()


class TestRespondedCount(unittest.TestCase):

    def test_counts_any_reading_not_only_env_keys(self):
        src = _read('aot_flask/geo/facility_sensors.py')
        self.assertIn("'responded':        any(v is not None for v in vals.values())",
                      src)
        self.assertIn("valid = sum(1 for d in detail if d.get('responded'))", src)
        # 옛 판정(다섯 키 한정)이 되살아나면 이슬점 전용 센서가 다시 고장으로 셈된다.
        self.assertNotIn(
            "if any(d.get(k) is not None for k in ('T', 'RH', 'CO2', 'VPD', 'light'))",
            src)

    def test_env_keys_still_recorded_for_averaging(self):
        """응답 여부와 별개로 환경 평균에 쓰는 키는 그대로 담는다."""
        src = _read('aot_flask/geo/facility_sensors.py')
        self.assertIn("**{k: vals.get(k) for k in ('T', 'RH', 'CO2', 'VPD', 'light')}",
                      src)


class TestVpdIsShown(unittest.TestCase):

    def test_now_block_reads_vpd(self):
        js = _read('aot_flask/static/js/widgets/AoT_map/aot-map-widget-vector.js')
        self.assertIn('indoor.vpd_kpa != null', js,
                      'VPD 를 재고 있는데 [현재]가 읽지 않으면 1차 목표가 화면에서 사라진다')

    def test_vpd_can_carry_target_and_deviation(self):
        """목표·편차가 붙으려면 측정 키가 목표 키와 이어져 있어야 한다."""
        js = _read('aot_flask/static/js/widgets/AoT_map/aot-map-popup.js')
        body = js.split('_NOW_TO_TARGET = {', 1)[1].split('}', 1)[0]
        self.assertIn("VPD: 'vpd'", body)


if __name__ == '__main__':
    unittest.main()


# ── 구역(bay)은 시설 **안**만 답한다 ──────────────────────────────────────
#
# 2026-08-20: 육묘장 구역 모달의 센서 목록에 '기상대'(실외)가 함께 떴다.
#
# **위치로는 안팎을 가릴 수 없다.** 기상대도 시설 어딘가에 서 있어서 좌표 →
# 슬라이스 매핑이 그것에 구역을 붙인다 — 실측 payload 에서 그 fitting 이
# `bay_id: 'bay_1_6'` 을 달고 나온다. 그래서 구역 필터가 `bay_id` 만 보면
# 실외 센서가 그 구역의 것으로 딸려 들어오고, 같은 '온도' 가 두 뜻으로 한
# 목록에 선다.
#
# **깨져도 조용하다** — 목록에 줄이 하나 더 있을 뿐 에러가 없고, 값도 그럴듯하다.
# 구역 칩(지도 위)에서는 더 조용하다: 실내·실외 온도가 **평균**돼 한 숫자가 된다.
class TestBayIsIndoorOnly(unittest.TestCase):

    _BAY = os.path.join('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                        'aot-map-bay.js')
    _WIDGET = os.path.join('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                           'aot-map-widget-vector.js')

    def test_bay_filter_looks_at_the_role_not_only_the_bay_id(self):
        """`filterSensors` 가 `bay_id` 만 보면 실외가 들어온다."""
        src = _read(self._BAY)
        body = src.split('function filterSensors', 1)[1].split('\n  }', 1)[0]
        self.assertIn('isIndoor', body,
                      '구역 필터가 sensor_role 을 보지 않는다 — 기상대도 '
                      'bay_id 를 달고 오므로 위치만으로는 걸러지지 않는다')

    def test_unset_role_counts_as_indoor(self):
        """미설정은 실내 — 서버(`facility_integration`·`read_fitting_sensors`)와
        **같은 폴백**이라야 한다. 여기서만 다르게 잡으면 같은 센서가 화면마다
        안팎이 갈린다."""
        src = _read(self._BAY)
        body = src.split('function isIndoor', 1)[1].split('\n  }', 1)[0]
        self.assertIn("'indoor'", body)
        self.assertIn("'outdoor'", body)
        # 서버 쪽 폴백이 실제로 그렇다는 것도 함께 고정한다.
        for path, needle in (
                (os.path.join('aot_flask', 'geo', 'facility_integration.py'),
                 "f.get('sensor_role') or 'indoor'"),
                (os.path.join('aot_flask', 'geo', 'facility_sensors.py'),
                 "s.get('sensor_role') or 'indoor'")):
            self.assertIn(needle, _read(path),
                          '%s 의 폴백이 바뀌었다 — 화면과 갈린다' % path)

    def test_facility_common_sensors_are_filtered_too(self):
        """구역에 배정되지 않은 시설 공통 센서(`bay_id == null`)도 같은 기준을
        지나야 한다 — 여기만 빠뜨리면 배정 없는 기상대가 그대로 들어온다."""
        src = _read(self._WIDGET)
        body = src.split('function _baySensors', 1)[1].split('\n        }', 1)[0]
        self.assertIn('isIndoor', body,
                      '시설 공통 센서 목록이 실외를 거르지 않는다')

    def test_the_chip_average_excludes_outdoor(self):
        """지도 칩은 "여기가 지금 어떤가" 를 **한 숫자**로 답한다. 기상대를
        평균에 넣으면 그 숫자가 안팎의 평균이 된다 — 실측 재현: 실내 25°C ·
        실외 -5°C 에서 칩이 **10°C** 라고 말했다. 어느 곳도 가리키지 않는 값인데
        에러도 없고 숫자도 그럴듯해서 조용하다.

        거르는 자리는 `_sensorSummary` **한 곳**이다 — 부르는 쪽(시설 칩·구역
        칩)이 각자 기억하게 두면 새 호출부가 생길 때마다 다시 새는 자리가 된다.
        """
        src = _read(self._WIDGET)
        body = src.split('function _sensorSummary', 1)[1].split(
            '\n        function ', 1)[0]
        self.assertIn('isIndoor', body,
                      '칩 평균이 실외를 거르지 않는다 — 안팎 평균이 한 숫자로 나간다')

    def test_outdoor_still_reaches_the_screen(self):
        """실외를 **버리는** 것이 아니다 — 시설 [현재] 카드의 '실외' 줄은 별도
        경로(`runtime.outdoor`)로 계속 온다. 그 줄까지 사라지면 "밖이 더운 날인가"
        를 판단할 근거가 없어진다."""
        src = _read(self._WIDGET)
        body = src.split('function _prependFacilityEnvNow', 1)[1].split(
            '\n        }', 1)[0]
        self.assertIn('rt.outdoor', body)
        self.assertIn('outdoor: outdoor', body)
