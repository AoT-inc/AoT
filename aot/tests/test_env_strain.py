# coding=utf-8
"""설비가 목표를 **못 따라가고 있는가** 판정 (`_assess_strain`).

화면이 "냉각기 100%" 만 보이면 그것이 좋은 신호인지 나쁜 신호인지 알 수 없다.
최대로 밀고 있는데도 편차가 안 줄면 그건 설비 한계이고, 그때 사람이 할 판단이
생긴다(차광을 더 치든, 목표를 낮추든, 장비를 늘리든).

**한두 사이클의 흔들림을 "한계" 라고 부르면 경고가 값을 잃는다** — 그래서
지속 시간을 함께 본다. 이 파일이 지키는 것은 그 문턱이다.

DB·데몬을 쓰지 않는다 — 판정 함수는 입력만으로 결정된다.
"""
import unittest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin,
)


class _TV(object):
    def __init__(self, value, tolerance):
        self.value = value
        self.tolerance = tolerance


class _Situation(object):
    def __init__(self, deviation):
        self.deviation_native = deviation


class _Coord(CycleMixin):
    """판정에 필요한 것만 가진 최소 객체 — 데몬 컨트롤러를 세우지 않는다."""


def _assess(dev, outputs, trend=None, tol=0.5, now=1000.0, coord=None):
    c = coord or _Coord()
    target = {k: _TV(20.0, tol) for k in dev}
    ctx = {'T_trend': (trend or {}).get('temperature'),
           'RH_trend': (trend or {}).get('humidity'),
           'CO2_trend': (trend or {}).get('co2')}
    return c, c._assess_strain(_Situation(dev), target, outputs, ctx, now)


class TestStrain(unittest.TestCase):

    def test_within_tolerance_is_not_strain(self):
        _c, out = _assess({'temperature': 0.3}, {'cooler': 100.0})
        self.assertIsNone(out)

    def test_needs_sustained_time(self):
        """첫 사이클에 바로 "한계" 라고 말하지 않는다 — 15분을 넘겨야 한다."""
        c, out = _assess({'temperature': 2.0}, {'cooler': 100.0}, now=1000.0)
        self.assertIsNone(out)
        _c2, out2 = _assess({'temperature': 2.0}, {'cooler': 100.0},
                            now=1000.0 + 16 * 60, coord=c)
        self.assertIsNotNone(out2)
        self.assertEqual('saturated', out2['reason'])
        self.assertEqual(['cooler'], out2['kinds'])
        self.assertGreaterEqual(out2['since_s'], 900)

    def test_not_saturated_is_not_strain(self):
        """아직 밀 여지가 있으면 한계가 아니다 — 그때 경고하면 늑대소년이 된다."""
        c, _ = _assess({'temperature': 2.0}, {'cooler': 100.0, 'opening': 40.0})
        _c, out = _assess({'temperature': 2.0}, {'cooler': 100.0, 'opening': 40.0},
                          now=1000.0 + 16 * 60, coord=c)
        self.assertIsNone(out)

    def test_improving_trend_is_not_strain(self):
        """목표 쪽으로 오고 있으면 기다리면 된다."""
        c, _ = _assess({'temperature': 2.0}, {'cooler': 100.0},
                       trend={'temperature': -0.2})
        _c, out = _assess({'temperature': 2.0}, {'cooler': 100.0},
                          trend={'temperature': -0.2},
                          now=1000.0 + 16 * 60, coord=c)
        self.assertIsNone(out)

    def test_recovery_clears_the_timer(self):
        """한 번 풀리면 시계도 풀린다 — 안 그러면 다음에 잠깐 벗어나도 즉시
        "30분째" 라고 말한다."""
        c, _ = _assess({'temperature': 2.0}, {'cooler': 100.0})
        _assess({'temperature': 0.1}, {'cooler': 100.0},
                now=1000.0 + 60, coord=c)           # 목표 안으로 복귀
        _c, out = _assess({'temperature': 2.0}, {'cooler': 100.0},
                          now=1000.0 + 16 * 60, coord=c)
        self.assertIsNone(out, '복귀 뒤에도 옛 시계를 들고 있다')

    def test_no_actuator_is_reported_differently(self):
        """밀 장치가 아예 없는 것은 "한계" 와 다른 사실이다 — 사람이 할 일도
        다르다(설비를 붙이는 일이지 운전을 바꾸는 일이 아니다)."""
        _c, out = _assess({'temperature': 2.0}, {'curtain': 40.0})
        self.assertIsNotNone(out)
        self.assertEqual('no_actuator', out['reason'])
        self.assertEqual([], out['kinds'])

    def test_kind_vocabulary_matches_the_server(self):
        """`_STRAIN_KINDS` 가 서버 어휘에서 벗어나면 그 종류는 영영 포화로
        잡히지 않는다 — 조용히 판정이 안 서는 계열이다."""
        from aot.functions.custom_functions.env_coordinator_impl._function_info \
            import _KIND_CAPABILITIES
        used = set()
        for kinds in CycleMixin._STRAIN_KINDS.values():
            used.update(kinds)
        self.assertEqual(set(), used - set(_KIND_CAPABILITIES),
                         '서버에 없는 종류: %s' % (used - set(_KIND_CAPABILITIES)))


if __name__ == '__main__':
    unittest.main()
