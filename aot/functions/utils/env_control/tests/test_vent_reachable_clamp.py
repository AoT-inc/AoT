# coding=utf-8
"""환기 효과는 실외를 지나칠 수 없다 (2026-08-26).

## 무엇이 문제였나

개구부 효과식은 이렇다.

    magnitude = |내외 차| × (개도/100) × k × 풍속보정 × 면적계수

`면적계수 = 개구부 면적 / 기준 면적(10 m²)` 이라 큰 측창에서는 쉽게 10 을
넘는다. 그러면 `k × 풍속보정 × 면적계수` 가 1 을 넘어 **도달 한계를 넘어선
값**이 나온다. 환기는 실내 공기를 실외 공기로 바꾸는 것이라 종착점이 실외
하나인데, 모델은 그것을 모른다.

실측(2026-08-26 イチゴ · 측창 157 m² · 바람 2.06 m/s):

    측창 하나의 VPD 유효도   2.0    kPa
    실제 도달 가능 폭        0.6152 kPa   (실내 0.28 → 실외 0.895)
                             ↑ 3.3 배 과대

## 왜 조용했나

과대평가 자체는 화면에 안 보인다. 드러난 곳은 **부하분담**이었다. 측창 둘이
7.4% · 10.6% 만 열려도 누적 기여가 편차(0.272)를 넘어서서, 잔여가 음(−)이
된다. 그래서 가장 유효한 **천창이 "이미 다 됐다" 로 읽고 닫힌 채** 있었다
(e_norm = −0.146). 창이 덜 열리니 그 몫은 난방기가 졌다 — 실외가 28.5 °C 로
공짜로 데워 줄 수 있는 상황에서 난방기가 66% 였다.

## ⚠ 환기 계열에만 건다

난방기·냉방기·분무기는 외기와 무관하게 열·수분을 직접 넣고 뺀다. 거기에
같은 클램프를 걸면 **폭염에 냉방이 실외 온도에서 멈춘다.** 판정은
`types.ACTUATOR_DOMAIN` 의 'vent' 하나이고, 어휘를 두 벌 두지 않는다.
"""
import pytest

from aot.functions.utils.env_control.effect_functions import (
    _svp_kpa, _vpd_gap, build_effect_model, vent_reachable,
)
from aot.functions.utils.env_control.types import (
    ACTUATOR_DOMAIN, VENTILATING_KINDS,
)


# 실측 환경 (2026-08-26 イチゴ)
_ENV = {'T_int': 22.9, 'RH_int': 89.0,
        'T_ext': 28.5, 'RH_ext': 77.0, 'wind': 2.06}


class _BigWindow:
    """실측 측창 — 82.45 m × 1.9 m ≈ 157 m² (기준 면적의 15.7 배)."""
    kind = 'opening'
    area_m2 = 157.0
    capacity_meta = {}


def _vpd_gap_kpa(env):
    return (_svp_kpa(env['T_ext']) * (1 - env['RH_ext'] / 100.0)
            - _svp_kpa(env['T_int']) * (1 - env['RH_int'] / 100.0))


class TestClampedToReachable:

    def test_측창_vpd_가_도달_폭을_안_넘는다(self):
        """이것이 회귀의 본체다 — 클램프 전에는 2.0 kPa 였다."""
        eff = build_effect_model('opening', {})['vpd'](_ENV, 100.0, _BigWindow())
        assert eff.magnitude_native <= abs(_vpd_gap_kpa(_ENV)) + 1e-9
        assert eff.magnitude_native == pytest.approx(
            abs(_vpd_gap_kpa(_ENV)), rel=1e-6), '도달 폭에 딱 붙어야 한다'

    def test_온도축도_내외차를_안_넘는다(self):
        eff = build_effect_model('opening', {})['temperature'](
            _ENV, 100.0, _BigWindow())
        assert eff.magnitude_native <= abs(_ENV['T_ext'] - _ENV['T_int']) + 1e-9

    def test_습도축도_내외차를_안_넘는다(self):
        eff = build_effect_model('opening', {})['humidity'](
            _ENV, 100.0, _BigWindow())
        assert eff.magnitude_native <= abs(_ENV['RH_ext'] - _ENV['RH_int']) + 1e-9

    def test_방향은_안_바뀐다(self):
        """크기만 자른다 — 부호를 건드리면 창이 반대로 움직인다."""
        m = build_effect_model('opening', {})
        assert m['temperature'](_ENV, 100.0, _BigWindow()).direction == '↑'
        assert m['humidity'](_ENV, 100.0, _BigWindow()).direction == '↓'
        assert m['vpd'](_ENV, 100.0, _BigWindow()).direction == '↑'

    def test_작은_창은_안_잘린다(self):
        """항상 개입하면 그 자체가 회귀다 — 면적계수가 작으면 원래 값 그대로."""
        class _Small:
            kind = 'opening'; area_m2 = 1.0; capacity_meta = {}
        eff = build_effect_model('opening', {})['temperature'](_ENV, 100.0, _Small())
        assert eff.magnitude_native < abs(_ENV['T_ext'] - _ENV['T_int']) * 0.5


class TestNonVentIsUntouched:
    """⚠ 냉난방·분무는 실외를 지나칠 수 있다."""

    def test_냉방기는_안_잘린다(self):
        """폭염에 실외 온도에서 멈추면 냉방기가 아니다."""
        hot = dict(_ENV, T_ext=40.0, T_int=30.0)
        eff = build_effect_model('cooler', {})['temperature'](hot, 100.0, None)
        assert eff.direction == '↓' and eff.magnitude_native == pytest.approx(2.5)

    def test_난방기_vpd_는_안_잘린다(self):
        """실내가 실외보다 습해도 난방으로 VPD 를 올릴 수 있어야 한다."""
        eff = build_effect_model('heater', {})['vpd'](_ENV, 100.0, None)
        assert eff.direction == '↑' and eff.magnitude_native > 0.0

    def test_분무기는_안_잘린다(self):
        eff = build_effect_model('fogger', {})['humidity'](_ENV, 100.0, None)
        assert eff.magnitude_native > 0.0


class TestUnknownOutdoorDoesNotZero:
    """모르는 것과 없는 것을 구분한다."""

    def test_실외를_모르면_클램프하지_않는다(self):
        """0 으로 두면 환기 효과가 통째로 죽어 창이 영영 안 열린다."""
        assert _vpd_gap({'T_int': 22.9, 'RH_int': 89.0}) is None
        blind = {'T_int': 22.9, 'RH_int': 89.0, 'T_ext': 28.5, 'wind': 0.0}
        assert _vpd_gap(blind) is None

    def test_실외를_알면_폭을_돌려준다(self):
        assert _vpd_gap(_ENV) == pytest.approx(_vpd_gap_kpa(_ENV))


class TestClampHelper:

    def test_크기만_자른다(self):
        assert vent_reachable(2.0, 0.6) == pytest.approx(0.6)
        assert vent_reachable(0.3, 0.6) == pytest.approx(0.3)

    def test_부호는_양수로_돌려준다(self):
        """effect 의 방향은 별도 필드다 — 크기는 언제나 양수여야 한다."""
        assert vent_reachable(-2.0, -0.6) == pytest.approx(0.6)


class TestVocabularyIsShared:
    """어휘를 두 벌 두면 갈라지고, 갈라지면 한쪽만 고쳐진다."""

    def test_환기_어휘가_도메인_표에서_나온다(self):
        assert VENTILATING_KINDS == frozenset(
            k for k, d in ACTUATOR_DOMAIN.items() if d == 'vent')

    def test_coordinator_가_같은_표를_쓴다(self):
        from aot.functions.utils.env_control import coordinator as c
        from aot.functions.utils.env_control import types as t
        assert c.ACTUATOR_DOMAIN is t.ACTUATOR_DOMAIN
        assert c.VENTILATING_KINDS is t.VENTILATING_KINDS

    def test_환기_계열_전부_클램프된다(self):
        """opening 만 고치고 배기·흡기팬을 빠뜨리면 그쪽으로 샌다."""
        import inspect
        from aot.functions.utils.env_control import effect_functions as ef
        src = inspect.getsource(ef._inject_vpd)
        assert 'vent_bounded=(kind in VENTILATING_KINDS)' in src


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
