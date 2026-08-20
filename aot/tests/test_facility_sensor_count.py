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
