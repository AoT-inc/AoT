# coding=utf-8
"""광량은 **작물이 받는 값**으로 판정한다 (2026-09-16).

## 무엇이 문제였나

차광막 투과율을 도입할 때(`estimate_indoor_light`) 그 값을 `light_est` 라는
새 키에만 넣고 `internal['light']` 은 실외 원본 그대로 두었다. 그래서 새 키를
아는 두 곳(광량 하드 임계·육묘 일소 게이트)만 차광을 반영했고, 나머지는 예전
키를 계속 읽어 **실외 원본으로 판정**했다.

    DLI 일적산            차광막을 닫아 둔 날도 목표를 채운 것으로 쌓인다
    광합성 제한 인자      "빛은 충분하다" → 우선순위 격상이 제어로 흘러간다
    상황 판정의 광 점수   같은 판정을 한 번 더, 역시 실외로
    런타임 요약 표시      화면이 막 위 값을 보인다

그리고 피복재 투과율은 아예 빠져 있었다 — 유리온실의 250 과 부직포 하우스의
250 이 작물에게는 두 배 차이인데 같은 설정으로 다뤄졌다.
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    estimate_indoor_light)
from aot.functions.utils.env_control.situation import _assess_limiting_factor
from aot.functions.utils.env_control.types import ActuatorProfile


def _shade(tau=0.5):
    return ActuatorProfile(actuator_id='sh', kind='shade',
                           capacity_meta={'shade_transmittance': tau})


class TestCoverTransmittance:
    """지붕은 차광막이 없어도 늘 빛을 깎는다."""

    def test_차광막이_없어도_피복을_통과한_값이다(self):
        assert estimate_indoor_light(500.0, [], {}, cover_tau=0.78) == pytest.approx(390.0)

    def test_차광막과_피복이_함께_곱해진다(self):
        # 실외 486 · 차광막 완전폐쇄(투과 0.5) · 피복 0.78 → 486×0.5×0.78
        got = estimate_indoor_light(486.0, [_shade(0.5)], {'sh': 0.0},
                                    cover_tau=0.78)
        assert got == pytest.approx(486.0 * 0.5 * 0.78)

    def test_차광막을_걷으면_피복만_남는다(self):
        got = estimate_indoor_light(486.0, [_shade(0.5)], {'sh': 100.0},
                                    cover_tau=0.78)
        assert got == pytest.approx(486.0 * 0.78)

    def test_피복을_모르면_깎지_않는다(self):
        """0 으로 깎으면 실내 광량이 0 으로 굳어 대낮에 보광등이 켜진다."""
        assert estimate_indoor_light(500.0, [], {}) == pytest.approx(500.0)
        assert estimate_indoor_light(500.0, [], {}, cover_tau=0.0) == pytest.approx(500.0)
        assert estimate_indoor_light(500.0, [], {}, cover_tau=1.7) == pytest.approx(500.0)


class TestLimitingFactorUsesBelowScreen:

    def _ctx(self, solar, light_int):
        return {'solar': solar, 'light_int': light_int, 'T_int': 22.0,
                'RH_int': 60.0, 'CO2_int': 900.0, 'VPD_int': 0.9}

    def test_차광막을_닫아_생긴_광부족을_본다(self):
        """실외는 밝은데 막 아래가 어두우면 광이 제한 인자다."""
        assert _assess_limiting_factor(
            self._ctx(solar=600.0, light_int=90.0), light_sat=300.0) == 'light'

    def test_실외로_재면_못_보던_것이었다(self):
        """대조군 — 같은 상황을 실외 값으로 재면 광 제한이 안 잡힌다."""
        assert _assess_limiting_factor(
            self._ctx(solar=600.0, light_int=600.0), light_sat=300.0) != 'light'

    def test_야간_판정은_실외로_한다(self):
        """차광막을 닫은 대낮을 밤으로 읽으면 광합성 평가가 통째로 꺼진다."""
        assert _assess_limiting_factor(
            self._ctx(solar=600.0, light_int=5.0), light_sat=300.0) == 'light'
        assert _assess_limiting_factor(
            self._ctx(solar=5.0, light_int=5.0), light_sat=300.0) is None

    def test_막_아래_값이_없으면_실외로_되돌아간다(self):
        ctx = self._ctx(solar=100.0, light_int=None)
        assert _assess_limiting_factor(ctx, light_sat=300.0) == 'light'


class TestEveryConsumerReadsBelowScreen:
    """새 키를 아는 곳만 고쳐지는 실패가 이 결함의 본체였다 — 소스로 고정한다."""

    def _src(self, *parts):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[4].joinpath(*parts)
                ).read_text(encoding='utf-8')

    def test_dli_적산이_막_아래_값을_쌓는다(self):
        src = self._src('functions', 'custom_functions',
                        'env_coordinator_impl', '_helpers_mixin.py')
        assert "light_value=internal.get('light_est', internal.get('light'))" in src

    def test_광합성_판정과_요약이_막_아래_값을_본다(self):
        src = self._src('functions', 'custom_functions',
                        'env_coordinator_impl', '_cycle_mixin.py')
        assert "_light_int = internal.get('light_est', internal.get('light'))" in src
        assert "ppfd_from_wm2(internal.get('light_est', internal.get('light')))" in src

    def test_상황_컨텍스트가_막_아래_값을_싣는다(self):
        src = self._src('functions', 'utils', 'env_control', 'situation.py')
        assert "'light_int'" in src

    def test_추정에_피복_투과율이_들어간다(self):
        src = self._src('functions', 'custom_functions',
                        'env_coordinator_impl', '_cycle_mixin.py')
        assert src.count('cover_tau=self._facility_cover_transmittance()') == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
