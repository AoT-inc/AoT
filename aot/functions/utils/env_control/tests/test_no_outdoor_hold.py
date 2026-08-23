# coding=utf-8
"""실외 근거가 없으면 개구부를 **움직이지 않는다** (2026-08-22).

## 무엇이 문제였나

실외 센서가 없거나 값을 못 받으면 `build_fallback_context()` 가 실외를 **내부값
으로 가정**해 채운다(캐시조차 비었을 때 `T_ext = T_int`). 그러면 내외 차이가 0 이라
환기 무익 게이트가 서고, 개구부가 `safe_default`(=닫힘)로 수렴한다.

**즉 기상대가 죽으면 창이 닫힌다.** 한여름이면 그대로 피해다. 그리고 아무 에러도
로그도 없다 — 근거코드는 그냥 `NO_GRADIENT`(15) 라, 실외를 몰라서 그런 건지 정말로
내외 차이가 없어서 그런 건지 사후에 구분할 수 없다.

실측(aot-005 야간 리플레이에서 기상대 계열만 제거, 71사이클):
    수정 전 : NO_GRADIENT 71회 · 개도 0~80 · 변화 7회   → 창이 닫힌다
    수정 후 : NO_OUTDOOR  71회 · 개도 100~100 · 변화 0회 → 제자리
정상 데이터에서는 둘이 **완전히 동일**하다(변화 6/6/7/7, 범위·근거 일치).

## 왜 '닫기'가 아니라 '제자리'인가

근거가 없다는 것은 열 이유도 닫을 이유도 없다는 뜻이다. 파킹(무익 게이트)은
`safe_default` 로 수렴시키므로 개구부에는 **닫는 동작**이다. 모른다는 이유로 장비를
움직이면, 그 움직임 자체가 근거 없는 제어다.

## 왜 마지막 실측은 여기 안 걸리나

캐시에 마지막 실외 실측이 남아 있으면 `_ext_synthetic` 이 False 다. 20~30분 된
실측은 근거가 되고(밤사이 실외는 천천히 변한다), 그건 `carry_forward_outdoor()`
가 맡는다 — [[test_outdoor_staleness]] 참조.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.ext_context_fallback import (
    ExtContextCache, build_fallback_context,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_NO_GRADIENT, REASON_NO_OUTDOOR_DATA,
)
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import TargetVar

from .conftest import make_ctx, make_opening_profile

START_PCT = 55.0          # 시작 개도 — 제자리인지 보려면 0/100 이 아니어야 한다
NIGHT = dict(T_int=22.8, RH_int=86.0)


class TestSyntheticOutdoorMarker:
    """지어낸 실외와 마지막 실측을 구분하는 표지."""

    def test_캐시가_비면_지어낸_것으로_표시된다(self):
        fb = build_fallback_context(ExtContextCache(), {'T': 22.8, 'RH': 86.0})
        assert fb['_ext_synthetic'] is True
        # 실외를 실내값으로 가정한다 = 내외 차이 0 → 환기 무익 판정이 선다
        assert fb['T_ext'] == 22.8

    def test_캐시에_실측이_있으면_지어낸_것이_아니다(self):
        cache = ExtContextCache()
        cache.update({'T': 21.0, 'RH': 95.0, 'T_ext': 21.0, 'RH_ext': 95.0}, now=100.0)
        fb = build_fallback_context(cache, {'T': 22.8, 'RH': 86.0}, now=200.0)
        assert fb['_ext_synthetic'] is False
        assert fb['T_ext'] == 21.0, '마지막 실측이 쓰인다'


def _run(external_extra, start=START_PCT):
    """개구부 하나로 한 사이클 — (명령, 시작개도) 반환."""
    profile = make_opening_profile('v1')
    profile.effect_model = build_effect_model('opening', {})

    vpd_int = compute_vpd(NIGHT['T_int'], NIGHT['RH_int'])
    target = {'vpd': TargetVar(value=0.46, tolerance=0.1, priority=1.2, unit='kPa')}
    ctx = make_ctx(VPD_int=vpd_int, T_ext=21.0, RH_ext=95.0, **NIGHT)
    external = dict(ctx['external'])
    external.update(external_extra)

    report, _ = assess(target, dict(ctx['internal'], VPD=vpd_int), external,
                       cycle_sec=600.0, now_ts=ctx['now_ts'])
    report.context['vent_futility_gate'] = True

    state = CoordinatorState()
    state.integral['v1'] = start
    state.prev_commands['v1'] = start
    cmds, _ = coordinate(report, [profile], state)
    return cmds['v1']


class TestHoldWhenOutdoorUnknown:

    def test_지어낸_실외면_제자리_유지(self):
        cmd = _run({'_ext_synthetic': True})
        assert cmd.reason == REASON_NO_OUTDOOR_DATA
        assert cmd.control_value() == pytest.approx(START_PCT), (
            '근거가 없으면 열지도 닫지도 않는다')

    def test_지어낸_실외가_아니면_종전대로_판정한다(self):
        """마지막 실측이 있으면 무익 게이트가 정상 동작해야 한다.

        이 케이스가 깨지면 hold 가 정상 제어까지 잡아먹은 것이다.
        """
        cmd = _run({'_ext_synthetic': False})
        assert cmd.reason != REASON_NO_OUTDOOR_DATA

    def test_표지가_없으면_종전대로(self):
        """표지를 안 넣는 경로(정상 실외 수신)는 아무 영향이 없어야 한다."""
        cmd = _run({})
        assert cmd.reason != REASON_NO_OUTDOOR_DATA

    def test_닫히지_않는다(self):
        """수정 전에는 여기서 safe_default(0) 쪽으로 감쇠했다."""
        cmd = _run({'_ext_synthetic': True}, start=80.0)
        assert cmd.control_value() > 70.0, '기상대가 죽었다고 창을 닫으면 안 된다'

    def test_근거코드가_구분된다(self):
        """`NO_GRADIENT`(판단함) 와 `NO_OUTDOOR_DATA`(판단 못 함)는 다른 사건이다."""
        assert REASON_NO_OUTDOOR_DATA != REASON_NO_GRADIENT


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
