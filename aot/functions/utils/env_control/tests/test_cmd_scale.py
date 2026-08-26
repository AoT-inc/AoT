# coding=utf-8
"""명령이 요구대로 못 나가는 제약은 **코디네이터가 알아야 한다** (2026-08-26).

## 무엇이 일어났나

풍향 가중치와 습도 상한 게이트가 둘 다 `coordinate()` **밖**에서 명령을 깎고
있었다. 그러면 코디네이터는 원래 값이 나갔다고 믿는다. 결과가 셋이다.

1. **적분이 영영 수렴하지 못한다.** 코디네이터가 24.6% 를 명령하고 5.0% 가
   나가면, `prev` 는 장치에서 5.0 으로 동기화되는데 적분은 24.6 이 나간 줄
   안다. 다음 사이클에 또 24 를 부르고 또 5 로 깎인다 — 화면에서는 "창이
   안 풀린다" 로 보인다.
2. **부하분담에 과장된 효과가 실린다.** 실제의 5배가 같은 도메인의 다른
   개구부에게 "이미 이만큼 했다" 로 전달된다.
3. **제약이 풀리는 순간 계단으로 튀어나온다.** 습윤형 분무기는 게이트가 0 으로
   끊는 동안에도 적분이 64.3 까지 차올라 있었다 — 습도가 문턱 아래로 내려가면
   그 값이 그대로 60% 분무로 나간다.

실측 두 건(イチゴ):

    側面窓右   24.6% 명령 / 5.0% 실제   풍향 가중치 0.2 (24.6 × 0.2 = 4.92)
    バルブ3    61%   명령 / 0%   실제   습도 상한 게이트

## 고친 형태

제약을 `ActuatorProfile.cmd_scale` 로 **coordinate() 앞에** 싣는다.
`finalize_command` 가 슬루보다 **먼저** 곱하므로, 슬루·min-ON·부하분담·
anti-windup 이 전부 실제로 나가는 값을 기준으로 돈다.

## 무풍인데 풍향 가중치가 걸리던 문제

가중치의 근거는 풍압이라 풍속이 0 이면 깎을 이유가 없다. 그런데 기상 소스는
무풍일 때 풍향을 `0.0`(정북)으로 내보내는 일이 흔하고(OpenWeather 가 그렇다),
`0.0` 은 `None` 이 아니라서 "정보 없음" 분기에도 안 걸린다. 그러면 북향이
아닌 측창이 **영구히 leeward** 로 판정돼 하한 0.2 에 갇힌다.
"""
import inspect

import pytest

from aot.aot_flask.geo.facility_wind import (
    WIND_BIAS_MIN_MS, wind_biased_opening,
)
from aot.functions.utils.env_control.coordinator import finalize_command
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _profile(kind='opening', slew=20.0, min_on=0.0, scale=1.0):
    p = ActuatorProfile(
        actuator_id='a1', kind=kind,
        cmd_constraints=CmdConstraints(slew_per_cycle=slew, min_on_pct=min_on),
        safe_default=0.0)
    p.cmd_scale = scale
    return p


# ═════════════════════════════════════════════════════════════════════════════
# 1. 무풍이면 풍향 가중치를 걸지 않는다
# ═════════════════════════════════════════════════════════════════════════════

_SIDE_RIGHT = {'actuator_id': 'right', 'kind': 'side_window',
               'surface_normal': [1, 0, 0]}
_SIDE_LEFT  = {'actuator_id': 'left', 'kind': 'side_window',
               'surface_normal': [-1, 0, 0]}


class TestCalmMeansNoBias:

    def test_풍속_0_이면_전부_1_0_이다(self):
        w = wind_biased_opening([_SIDE_RIGHT, _SIDE_LEFT], 0.0,
                                wind_speed_ms=0.0)
        assert w == {'right': 1.0, 'left': 1.0}

    def test_풍향_0도는_정보없음이_아니다(self):
        """0.0 은 None 이 아니라 기존 '방향 불명' 분기에 안 걸린다.

        이 테스트가 통과하는 것 자체가 버그의 성립 조건을 고정한다 — 풍속을
        안 넘기면 예전 그대로 0.2 가 나온다.
        """
        w = wind_biased_opening([_SIDE_RIGHT], 0.0)
        assert w['right'] == pytest.approx(0.2), (
            '풍속 없이 부르면 종전 동작이어야 한다(하위호환)')

    def test_문턱_위_바람은_그대로_가중된다(self):
        """항상 1.0 이면 이 기능이 통째로 죽은 것이다."""
        w = wind_biased_opening([_SIDE_RIGHT], 0.0,
                                wind_speed_ms=WIND_BIAS_MIN_MS + 1.0)
        assert w['right'] == pytest.approx(0.2)
        w2 = wind_biased_opening([_SIDE_RIGHT], 270.0,
                                 wind_speed_ms=WIND_BIAS_MIN_MS + 1.0)
        assert w2['right'] == pytest.approx(1.0)

    def test_모르면_가중한다(self):
        """None = 모름. 모른다고 무풍으로 단정하면 강풍에 창이 안 닫힌다."""
        w = wind_biased_opening([_SIDE_RIGHT], 0.0, wind_speed_ms=None)
        assert w['right'] == pytest.approx(0.2)


# ═════════════════════════════════════════════════════════════════════════════
# 2. cmd_scale 은 finalize_command 를 지난다
# ═════════════════════════════════════════════════════════════════════════════

class TestCmdScaleGoesThroughFinalize:

    def test_비율이_적용된다(self):
        cmd = finalize_command(_profile(scale=0.2, slew=100.0),
                               aperture_pct=100.0, prev_aperture=100.0,
                               cycle_sec=600.0, reason=1)
        assert cmd.control_value() == pytest.approx(20.0)

    def test_0_은_슬루를_지나지_않고_즉시_끊긴다(self):
        """게이트 차단(습도 상한)이 이 경로로 표현된다.

        ⚠ 비율(0<s<1)과 0 은 뜻이 다르다. 비율은 "위치 목표를 낮춰라" 라서
        장치가 자기 속도로 이동하는 게 맞지만, 0 은 "아예 주지 마라" 라 중간
        위치를 거칠 것이 없다. 슬루를 태우면 직전 80% 였던 분무기가 차단 후에도
        60% → 40% 로 계속 뿌린다.
        """
        cmd = finalize_command(_profile(scale=0.0, slew=20.0),
                               aperture_pct=80.0, prev_aperture=80.0,
                               cycle_sec=600.0, reason=1)
        assert cmd.control_value() == 0.0, (
            '차단인데 슬루로 내려오고 있다 — 그 사이 계속 뿌린다')

    def test_슬루보다_먼저_곱한다(self):
        """뒤에 곱하면 실제 움직임이 속도 한계를 안 받는다.

        직전 0% · 슬루 20%/사이클 · 요구 100% · 비율 0.2 →
          먼저 곱하면  min(20, 0+20) = 20   (한 사이클에 갈 수 있는 만큼)
          뒤에 곱하면  min(100,20) × 0.2 = 4  (속도 한계를 못 받은 값)
        """
        cmd = finalize_command(_profile(scale=0.2, slew=20.0),
                               aperture_pct=100.0, prev_aperture=0.0,
                               cycle_sec=600.0, reason=1)
        assert cmd.control_value() == pytest.approx(20.0)

    def test_1_0_이면_아무것도_안_바뀐다(self):
        cmd = finalize_command(_profile(scale=1.0), aperture_pct=37.0,
                               prev_aperture=37.0, cycle_sec=600.0, reason=1)
        assert cmd.control_value() == pytest.approx(37.0)

    def test_비율은_slewed_에도_반영된다(self):
        """적분 되먹임이 이 값을 쓴다 — 반영 안 되면 적분이 안 배운다.

        차단(0)에서 `slewed` 가 옛 값으로 남으면 코디네이터는 "요구대로 나갔다"
        고 읽어 적분을 안 내린다. 그러면 게이트가 풀리는 순간 쌓인 적분이 그대로
        분무로 튀어나온다 — 실측 64.3 (≈60% 분무).
        """
        cmd = finalize_command(_profile(scale=0.0, slew=20.0),
                               aperture_pct=80.0, prev_aperture=80.0,
                               cycle_sec=600.0, reason=1)
        assert cmd.slewed == pytest.approx(0.0)


# ═════════════════════════════════════════════════════════════════════════════
# 3. 배선 — coordinate() 밖에서 곱하지 않는다
# ═════════════════════════════════════════════════════════════════════════════

class TestNoPostCoordinateMultiplication:

    def _src(self):
        from aot.functions.custom_functions.env_coordinator_impl import (
            _cycle_mixin as m)
        return inspect.getsource(m.CycleMixin._run_cycle)

    def test_풍향_가중치가_coordinate_앞에서_실린다(self):
        src = self._src()
        i_scale = src.index('_apply_cmd_scales')
        i_ctrl = src.index('self._run_control(')
        assert i_scale < i_ctrl, (
            'coordinate() 뒤에서 걸면 코디네이터가 제약을 배우지 못한다')

    def test_명령에_직접_곱하는_코드가_없다(self):
        """`_cmd.value * _w` 형태가 되살아나면 같은 사고가 재발한다."""
        src = self._src()
        assert 'wind_biased_opening' not in src, (
            '_run_cycle 안에서 직접 가중치를 계산·적용하고 있다 — '
            '_apply_cmd_scales 로 옮길 것')

    def test_비율은_매_사이클_초기화된다(self):
        """남겨 두면 바람이 멎은 뒤에도 옛 가중치가 계속 걸린다."""
        from aot.functions.custom_functions.env_coordinator_impl import (
            _cycle_mixin as m)
        src = inspect.getsource(m.CycleMixin._apply_cmd_scales)
        i_reset = src.index('cmd_scale = 1.0')
        i_fog = src.index('_fog_humidity_block')
        assert i_reset < i_fog, '초기화가 제약 적용보다 뒤에 있다'


def test_기본값은_1_0_이다():
    """프로필을 새로 만드는 코드가 이 필드를 몰라도 종전대로 동작해야 한다."""
    assert ActuatorProfile(actuator_id='x', kind='heater').cmd_scale == 1.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
