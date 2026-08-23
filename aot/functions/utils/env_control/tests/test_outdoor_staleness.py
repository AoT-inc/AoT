# coding=utf-8
"""실외 관측이 잠깐 늦었을 때 지어낸 값이 제어로 흘러가지 않는가 (2026-08-22).

## 무엇을 고정하는가

`situation.py` 의 EnvContext 구성은 external 에 'T'/'RH' 가 없으면 **20°C/60%**
를 채운다. 그 가짜 실외는 VPD 0.93 이라 웬만한 야간 실내(0.3 안팎)보다 높아서,
환기 무익 게이트가 "창을 열면 건조해진다" 로 읽고 창을 연다. 실제 실외
(23°C/96% → VPD 0.11)면 정반대 판단이다.

2026-08-22 aot-005 새벽 창호 진동이 정확히 이것이었다. 기상대 관측이 간헐적으로
최대 31분 벌어지는데(중앙값 60초) `sensor_max_age`(1200초)를 넘긴 사이클마다
가짜 실외가 들어가 **40분 주기로 창이 열렸다 닫혔다** 했다. 실측 리플레이에서
가짜 실외가 뜬 야간 사이클 10회와 창이 열린 10회가 1:1 로 대응했다.

## 왜 이 테스트가 필요한가

- 이 결함은 **에러를 내지 않는다.** 로그에는 근거코드(NO_GRADIENT/PRIMARY)만
  남고 "이번 사이클의 실외값은 지어낸 것이었다" 는 어디에도 안 남는다.
- 기존 env_control 테스트는 전부 **합성 입력**이라 실외값이 항상 존재한다.
  그래서 이 경로를 한 번도 타지 않았고, 2026-08-06 에 같은 증상을 겨냥한
  수정(`b23c84a3`, 테스트 19건 추가)을 하고도 재발했다.

그래서 여기서는 승계 동작만이 아니라 **가짜 실외가 판정을 뒤집는다는 사실
자체**를 고정한다. 승계가 사라지면 두 번째 테스트가 먼저 깨진다.
"""
import math

import pytest

from aot.functions.utils.env_control.ext_context_fallback import (
    CARRY_FORWARD_KEYS, carry_forward_outdoor)


def _vpd(t_c, rh_pct):
    """포화수증기압 결손 [kPa] — 판정이 뒤집히는 이유를 수치로 보이기 위한 것."""
    svp = 0.61078 * math.exp(17.27 * t_c / (t_c + 237.3))
    return svp * (1.0 - rh_pct / 100.0)


class TestCarryForwardOutdoor:
    """빈 실외값을 마지막 유효 실측으로 잇는다."""

    def test_빈_값을_캐시로_잇는다(self):
        external = {'wind': 0.1}
        carried = carry_forward_outdoor(
            external, {'T': 23.0, 'RH': 96.0, 'T_ext': 23.0, 'RH_ext': 96.0})
        assert external['T'] == 23.0
        assert external['RH'] == 96.0
        assert set(carried) == set(CARRY_FORWARD_KEYS)

    def test_이미_있는_값은_덮어쓰지_않는다(self):
        """이번 사이클에 실측이 있으면 그것이 이긴다 — 캐시는 어디까지나 대타다."""
        external = {'T': 22.0, 'RH': 90.0}
        carried = carry_forward_outdoor(external, {'T': 5.0, 'RH': 5.0})
        assert external['T'] == 22.0
        assert external['RH'] == 90.0
        assert 'T' not in carried and 'RH' not in carried

    def test_캐시가_비면_손대지_않는다(self):
        """근거가 아무 데도 없으면 **채우지 않는다.**

        여기서 무언가를 채우면 그게 바로 이 사고의 재발이다. 값이 없다는 사실은
        호출부(P2-2 fallback 컨텍스트)로 그대로 전달되어야 한다.
        """
        external = {'wind': 0.0}
        carried = carry_forward_outdoor(external, {})
        assert 'T' not in external
        assert 'RH' not in external
        assert carried == []

    def test_안전게이트용_키도_함께_잇는다(self):
        """'T'/'RH' 는 situation 이, 'T_ext'/'RH_ext' 는 안전 게이트가 읽는다.

        한쪽만 이으면 같은 사이클에서 두 판단이 서로 다른 실외를 보게 된다.
        """
        assert 'T' in CARRY_FORWARD_KEYS and 'T_ext' in CARRY_FORWARD_KEYS
        assert 'RH' in CARRY_FORWARD_KEYS and 'RH_ext' in CARRY_FORWARD_KEYS

    def test_external_이_빈_dict_면_그것이야말로_채울_경우다(self):
        """`{}` 를 falsy 로 걸러내면 안 된다.

        실외 수집기가 없는 설치에서 관측이 늦은 사이클의 external 은 정확히
        `{}` 다 — 즉 이 사고가 나는 바로 그 상황이다. 처음 헬퍼를 뽑을 때
        `if not external:` 로 걸러 두는 바람에 승계가 통째로 죽었고, 이 테스트가
        그것을 잡았다. 걸러낼 것은 None 뿐이다.
        """
        external = {}
        carried = carry_forward_outdoor(external, {'T': 23.0, 'RH': 96.0})
        assert external['T'] == 23.0
        assert set(carried) == {'T', 'RH'}
        assert carry_forward_outdoor(None, {'T': 20.0}) == []


class TestFabricatedOutdoorFlipsVentVerdict:
    """**왜** 승계가 필요한가 — 지어낸 실외는 환기 판정을 뒤집는다.

    `_ventilation_is_futile` 은 need(목표−측정)와 avail(실외−측정)의 부호가
    같은 변수가 하나라도 있으면 "환기로 개선 가능" 으로 본다. 실외를 지어내면
    avail 의 부호가 통째로 뒤집힌다.
    """

    # situation.py 가 external 에 값이 없을 때 채우는 상수. 이 값이 바뀌면
    # 이 테스트의 전제도 함께 바뀌어야 하므로 여기 이름을 붙여 둔다.
    FABRICATED_T = 20.0
    FABRICATED_RH = 60.0

    def test_지어낸_실외는_실내보다_건조하다(self):
        """이것이 판정을 뒤집는 물리적 이유다."""
        가짜_실외 = _vpd(self.FABRICATED_T, self.FABRICATED_RH)
        실제_실외 = _vpd(23.0, 96.0)   # 2026-08-22 새벽 aot-005 실측
        야간_실내 = _vpd(24.0, 91.0)   # 같은 시각 실측

        assert 가짜_실외 > 야간_실내, (
            '가짜 실외가 실내보다 건조해 보이므로 "열면 건조해진다" 로 읽힌다')
        assert 실제_실외 < 야간_실내, (
            '실제 실외는 실내보다 습해서 열수록 습해진다 — 환기가 무익하다')

    def test_부호가_반대다(self):
        """need 는 그대로인데 avail 의 부호만 뒤집힌다 = 판정이 뒤집힌다."""
        목표, 실내 = 0.67, _vpd(24.0, 91.0)
        need = 목표 - 실내                       # + : VPD 를 올려야 한다
        avail_실제 = _vpd(23.0, 96.0) - 실내      # − : 열면 오히려 내려간다
        avail_가짜 = _vpd(self.FABRICATED_T, self.FABRICATED_RH) - 실내   # +

        assert need > 0
        assert avail_실제 < 0, '실제 실외로는 목표 방향으로 못 간다(무익)'
        assert avail_가짜 > 0, '가짜 실외는 목표 방향으로 갈 수 있다고 말한다'
        assert (need > 0) is not (avail_실제 > 0)
        assert (need > 0) is (avail_가짜 > 0)

    def test_승계하면_실제_실외가_유지된다(self):
        """관측이 한 사이클 늦어도 판정이 뒤집히지 않는다."""
        external = {}                                  # 이번 사이클 실외 없음
        carry_forward_outdoor(external, {'T': 23.0, 'RH': 96.0})
        실내 = _vpd(24.0, 91.0)
        avail = _vpd(external['T'], external['RH']) - 실내
        assert avail < 0, '승계 덕에 "환기 무익" 판정이 유지된다'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
