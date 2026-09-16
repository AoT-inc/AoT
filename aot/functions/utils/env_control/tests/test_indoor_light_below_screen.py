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
        # 세 곳이다 — 실내 추정 · 맑은날 폴백 · "막을 걷었을 때" 추정.
        assert src.count('cover_tau=self._facility_cover_transmittance()') == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# ─────────────────────────────────────────────────────────────────────────────
# 차광 판정은 "막을 걷었을 때" 값으로 한다 (왕복 제거, 2026-09-16)
# ─────────────────────────────────────────────────────────────────────────────

class _Logged:
    """로그를 모으는 가짜 로거 — 1회성 경고를 세기 위해."""
    def __init__(self):
        self.errors = []
    def error(self, msg, *a):
        self.errors.append(msg % a if a else msg)
    def debug(self, *a, **k):
        pass
    def warning(self, *a, **k):
        pass
    def info(self, *a, **k):
        pass


def _coord(light_max=250.0, light_min=150.0, shade_tau=0.5, cover_tau=0.85,
           aperture=100.0):
    """차광막 하나를 단 코디네이터 — 실제 판정 코드를 그대로 쓴다."""
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
        import CycleMixin
    from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin \
        import HelpersMixin

    profiles = [ActuatorProfile(actuator_id='sh', kind='shade',
                                capacity_meta={'shade_transmittance': shade_tau})]

    class _State:
        prev_commands = {'sh': aperture}

    class C(CycleMixin, HelpersMixin):
        unique_id = 'x'
        log_level_debug = False
        temp_max = temp_min = humid_max = humid_min = None
        nursery_mode = False
        nursery_solar_lockout = 250.0
        nursery_solar_release = 150.0

        def __init__(self):
            self.logger = _Logged()
            self._profiles = profiles
            self._coord_state = _State()
            self.light_max = light_max
            self.light_min = light_min
            self._constraint_breach_state = {
                'T_max': False, 'T_min': False, 'RH_max': False, 'RH_min': False}
            self._light_breach_state = {'max': False, 'min': False}

        def _facility_shade_transmittance(self):
            return shade_tau

        def _facility_cover_transmittance(self):
            return cover_tau

        def _evening_fog_blocked(self):
            return False

        def _clear_sky_light_fallback(self):
            return None

    return C(), _State


def _run(c, outdoor, cycles=8):
    """실제 사이클처럼 돌린다 — 판정 결과가 다음 사이클의 개도가 된다."""
    trace = []
    for _ in range(cycles):
        internal = {'light': outdoor, '_light_is_outdoor': True}
        c._compute_light_est(internal, {})
        c._check_hard_constraints(internal)
        ap = c._coord_state.prev_commands['sh']
        if internal.get('_force_shade'):
            ap = 0.0
        elif internal.get('_force_suplight'):
            ap = 100.0
        c._coord_state.prev_commands['sh'] = ap
        trace.append((round(internal['light_est']), ap,
                      bool(internal.get('_force_shade')),
                      bool(internal.get('_force_suplight')),
                      bool(internal.get('_light_band_conflict'))))
    return trace


class TestShadeDoesNotFlap:
    """실측 조합: 영양 육묘장(피복 0.85 · 차광막 0.5), 상한 250 · 하한 150."""

    def test_한번_닫으면_해가_높은_동안_닫힌_채_있다(self):
        c, _ = _coord()
        trace = _run(c, 486.0)
        assert trace[0][2] is True, '첫 사이클에 차광 판정이 서야 한다'
        assert all(t[1] == 0.0 for t in trace[1:]), '내내 닫혀 있어야 한다'
        assert all(t[2] for t in trace), '차광 판정이 풀리면 안 된다'
        assert not any(t[3] for t in trace), '보광 강제가 서면 안 된다'

    def test_예전_기준이었다면_풀렸을_값이다(self):
        """대조 — 닫은 뒤 실내는 207 로 해제선(225) 아래다.

        지금 상태의 광량으로 판정하던 때는 여기서 판정이 풀리고, 차광막이
        걷혔다가 다시 밝아져 닫히기를 반복했다.
        """
        c, _ = _coord()
        trace = _run(c, 486.0)
        closed_est = trace[-1][0]
        assert closed_est == 207, closed_est
        assert closed_est < 250 * (1 - 0.10), '해제선 아래인 것이 이 시험의 전제'
        assert trace[-1][2] is True, '그래도 닫힌 채여야 한다'

    def test_해가_내려가면_판정이_풀린다(self):
        """계속 닫아 두는 것이 아니다 — 걷어도 상한 아래면 푼다."""
        c, _ = _coord()
        _run(c, 486.0)                       # 먼저 닫아 둔다
        trace = _run(c, 200.0)               # 걷으면 170 → 상한 아래
        assert trace[-1][2] is False
        assert trace[-1][1] == 100.0, '차광막이 걷혀야 한다'

    def test_그늘이_필요없는_날은_닫지_않는다(self):
        c, _ = _coord()
        trace = _run(c, 250.0)               # 걷으면 212 < 250
        assert not any(t[2] for t in trace)


class TestContradictorySettings:
    """닫으면 하한 아래가 되는 설정 — 장치를 흔들지 않고 사람에게 알린다."""

    def test_차광이_이기고_보광은_서지_않는다(self):
        c, _ = _coord(light_max=250.0, light_min=250.0)   # 닫으면 207 < 250
        trace = _run(c, 486.0)
        assert all(t[2] for t in trace), '차광은 유지된다'
        assert not any(t[3] for t in trace), '보광·개방 강제가 서면 안 된다'
        assert all(t[1] == 0.0 for t in trace[1:]), '왕복하지 않는다'

    def test_모순을_표시한다(self):
        c, _ = _coord(light_max=250.0, light_min=250.0)
        trace = _run(c, 486.0)
        assert trace[-1][4] is True, '모순 사실이 internal 에 남아야 한다'

    def test_설정_경고는_한_번만_나온다(self):
        c, _ = _coord(light_max=250.0, light_min=150.0)   # 150 ≥ 250×0.425
        for _ in range(3):
            c._warn_light_band_conflict_once()
        assert len(c.logger.errors) == 1
        msg = c.logger.errors[0]
        assert '모순' in msg and '106' in msg

    def test_정상_설정에는_경고가_없다(self):
        c, _ = _coord(light_max=250.0, light_min=100.0)   # 100 < 106
        c._warn_light_band_conflict_once()
        assert c.logger.errors == []

    def test_한쪽을_껐으면_모순이_아니다(self):
        c, _ = _coord(light_max=250.0, light_min=0.0)
        c._warn_light_band_conflict_once()
        assert c.logger.errors == []


class TestIndoorSensorFallback:
    """실외를 모르면 예전처럼 지금 값으로 판정한다 — 없는 값을 지어내지 않는다."""

    def test_실외를_모르면_걷었을_때_값이_없다(self):
        c, _ = _coord()
        internal = {'light': 300.0}          # 실내 센서 실측(막 아래)
        c._compute_light_est(internal, {})
        assert 'light_open_est' not in internal
        c._check_hard_constraints(internal)
        assert internal.get('_force_shade') is True   # 300 > 250
