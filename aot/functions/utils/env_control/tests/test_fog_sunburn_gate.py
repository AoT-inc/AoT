# coding=utf-8
"""일소 잠금은 육묘 모드의 부속이 아니다 (2026-08-25).

## 무엇이 문제였나

강일사에 젖은 잎이 타는 것을 막는 잠금이 **통째로 `nursery_mode` 안에**
있었다 — 하드 잠금(`safety_gates._eval_nursery_lock`)도, 그 아래 구간의
선형 감쇠(`_cycle_mixin.apply_nursery_fog_derate`)도 첫 줄에서 육묘 모드가
아니면 그냥 돌아갔다.

그래서 딸기 온실이 육묘 모드를 끄는 순간(2026-08-25 イチゴ) 두상 살수
246개(6.4 mm/h)의 일소 보호가 함께 사라졌다. 설정값
(`nursery_solar_lockout` 250 등)은 DB 에 그대로 남아 화면에도 보이는데
**아무도 읽지 않는 상태**가 된다 — "잠금 250 으로 해뒀는데 왜 한낮에
뿌리지?" 가 된다.

물방울이 렌즈가 되어 빛을 모으는 것은 어린 모종만의 일이 아니다. 그래서
잠금은 **습윤형 분무기가 있으면 늘** 서고, 육묘 모드는 그 위에서 **더
조이는 축**이 된다:

    공통    : 잠금 250 W/m² · 해제 150 W/m² · 펄스 30초 / 휴지 180초
    육묘 추가: 지하수면 150/100 · 펄스 20초 / 휴지 600초 · 저녁 차단

## 이 테스트가 지키는 것

1. 육묘 모드가 **꺼져 있어도** 습윤형 분무기가 잠긴다(회귀의 본체).
2. 육묘 모드 설치의 동작이 **바뀌지 않는다**(더 조이는 쪽이 유지된다).
3. 드립·고압 미세포그는 여전히 걸리지 않는다.
"""
import pytest

from aot.functions.utils.env_control.safety_gates import PreGateConfig, SafetyPreGate
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _env(light=None, solar=None, evening=False):
    internal = {}
    if light is not None:
        internal['light_est'] = light
    if evening:
        internal['evening_block'] = True
    external = {}
    if solar is not None:
        external['solar'] = solar
    return {'internal': internal, 'external': external}


def _gate(nursery=False, lockout=250.0, release=150.0):
    return SafetyPreGate(PreGateConfig(
        nursery_mode=nursery,
        nursery_solar_lockout=lockout,
        nursery_solar_release=release,
    ))


class TestLockoutDoesNotRequireNurseryMode:
    """① 회귀의 본체 — 육묘 모드를 꺼도 잠긴다."""

    def test_육묘_꺼짐에도_강일사면_잠긴다(self):
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env(light=300.0)) is True

    def test_육묘_켜짐과_같은_판정이다(self):
        """육묘 여부로 **잠금 유무**가 갈리면 안 된다(임계는 갈릴 수 있다)."""
        off = _gate(nursery=False)._eval_nursery_lock(_env(light=300.0))
        on = _gate(nursery=True)._eval_nursery_lock(_env(light=300.0))
        assert off == on is True

    def test_약한_빛에서는_잠기지_않는다(self):
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env(light=100.0)) is False


class TestHysteresisSurvives:
    """래치는 그대로여야 한다 — 구름에 켜졌다 꺼졌다 하면 안 된다."""

    def test_해제_임계_아래로_내려가야_풀린다(self):
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env(light=300.0)) is True
        assert g._eval_nursery_lock(_env(light=200.0)) is True, (
            '잠금(250)과 해제(150) 사이에서는 잠금이 유지돼야 한다')
        assert g._eval_nursery_lock(_env(light=100.0)) is False

    def test_저녁_차단은_광량과_무관하게_우선한다(self):
        g = _gate(nursery=True)
        assert g._eval_nursery_lock(_env(light=0.0, evening=True)) is True


class TestFallbacksUnchanged:
    """센서가 없는 설치에서 잠금이 통째로 죽지 않아야 한다."""

    def test_실외_일사_양수는_측정값으로_인정한다(self):
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env(solar=400.0)) is True

    def test_실외_일사_0은_측정값이_아니다(self):
        """`ext_context_collector` 가 센서 없이 0.0 을 채운다 — 한밤중이 아니다."""
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env(solar=0.0)) is False

    def test_아무_근거도_없으면_잠그지_않는다(self):
        g = _gate(nursery=False)
        assert g._eval_nursery_lock(_env()) is False


class TestNurseryStillTightens:
    """② 육묘 모드는 사라지지 않고 '더 조이는 축' 으로 남는다."""

    def test_육묘_임계가_더_낮으면_더_일찍_잠긴다(self):
        """지하수 하향(150/100)은 initialize 가 육묘일 때만 적용한다."""
        normal = _gate(nursery=False, lockout=250.0, release=150.0)
        nursery = _gate(nursery=True, lockout=150.0, release=100.0)
        assert normal._eval_nursery_lock(_env(light=200.0)) is False
        assert nursery._eval_nursery_lock(_env(light=200.0)) is True

    def test_지하수_하향은_육묘에서만_적용된다(self):
        """`initialize()` 배선을 소스로 고정한다 — 성체 작물을 150 W/m² 로
        묶으면 흐린 아침부터 분무가 막힌다."""
        import pathlib as _pl
        src = (_pl.Path(__file__).resolve().parents[4]
               / 'functions/custom_functions/env_coordinator.py'
               ).read_text(encoding='utf-8')
        i = src.index('groundwater')
        window = src[max(0, i - 400):i + 200]
        assert 'bool(self.nursery_mode)' in window, (
            '지하수 임계 하향이 육묘 모드 조건과 함께 있어야 한다')


class TestOnlyWettingNozzlesAreGated:
    """③ 드립·고압 미세포그는 걸리지 않는다."""

    def test_게이트가_습윤형만_고른다(self):
        """마스크를 세우는 조건이 `is_wetting_fogger` 인지 소스로 본다."""
        import inspect
        from aot.functions.utils.env_control import safety_gates as sg
        src = inspect.getsource(sg.SafetyPreGate.evaluate)
        assert 'is_wetting_fogger(p) for p in profiles' in src


def test_감쇠도_육묘_모드를_전제하지_않는다():
    """하드 잠금과 감쇠가 서로 다른 조건에서 서면 구간이 어긋난다.

    잠금만 일반화하고 감쇠를 육묘에 남기면, 비육묘 설치에서 분무가 절벽처럼
    끊긴다(release~lockout 사이의 완만한 감소가 사라진다).
    """
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
    src = inspect.getsource(_cycle_mixin.apply_nursery_fog_derate)
    assert "if not internal.get('_nursery_mode'):" not in src, (
        '감쇠가 다시 육묘 모드 안으로 들어갔다')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
