# coding=utf-8
"""분무 효과가 실제로 뿌리는 양과 공기가 받는 양을 넘지 않는가 (2026-08-25).

## 무엇이 문제였나

습윤형 분무기의 효과 모델이 실제보다 **46배** 크게 신고했다. 원인이 둘이고
서로 독립이다.

**① 시간 불일치 (20배).** `_fog_liters` 가 `cycle_sec`(600초)로 곱하는데,
디스패처(`PulseDosingAdapter`)는 1회 분무를 `max_on_sec`(기본 30초, 육묘
20초)로 끊는다. **결정하는 쪽과 실제 뿌리는 쪽이 분무 시간을 다르게 알고**
있었고, 그 배율이 그대로 과대평가가 됐다.

2026-08-20 육묘장 사고 기록에 "그 한 값이 결합 drive 가중치를 20배로
지배했다" 고 적혀 있다 — 그때 고친 것은 유량 출처(`fog_flow_lpm` 를
`irrigation_flow_lpm` 에서 분리)였고, 지속 시간은 그대로 남아 있었다.

**② 포화를 비율로만 다뤘다 (약 6배).** `_evaporation_availability` 는 증발
**속도**의 구동력을 [0,1] 로 낮출 뿐 증발할 수 있는 **총량**을 막지 않는다.
그래서 습한 공기에 아무리 뿌려도 전부 증발한 것으로 계산됐다.

실측(2026-08-25 イチゴ — 164 L/min · 5,463 m³ · 23.6 °C · RH 89%):

    수정 전  명령 100% → 증발 1,640 L → ΔT −219.7 °C/사이클
    수정 후  명령 100% → 증발    12.8 L → ΔT   −1.71 °C/사이클
    물리 상한(흡수 가능분 전부 증발)      ΔT   −4.67 °C

## 왜 이 테스트가 필요한가

에러가 나지 않는다. 과대평가된 냉각·가습은 그냥 "아주 잘 듣는 분무기" 로
보이고, 결합 drive 에서 이 항의 이득이 창·차광을 압도해 **다른 축이 전부
무의미해진다.** 증상은 "분무를 켰더니 다른 제어가 이상해졌다" 라, 원인에
닿기 어렵다.
"""
import math

import pytest

from aot.functions.utils.env_control import effect_functions as ef
from aot.functions.utils.env_control.types import CmdConstraints

VOL_M3 = 5463.0          # イチゴ 실측
FOG_LPM = 164.0          # 스프링클러 246개 × 40 L/h
CYCLE_S = 600.0


class _Profile:
    def __init__(self, cmd_constraints=None, volume_m3=VOL_M3, fog_lpm=FOG_LPM):
        self.capacity_meta = {'volume_m3': volume_m3, 'fog_flow_lpm': fog_lpm}
        self.cmd_constraints = cmd_constraints or CmdConstraints()


def _env(rh=89.0, t=23.6, cycle=CYCLE_S):
    return {'cycle_sec': cycle, 'volume_m3': VOL_M3,
            'T': t, 'RH': rh, 'T_int': t, 'RH_int': rh}


def _absorbable(t, rh, vol=VOL_M3):
    """테스트가 독립적으로 다시 계산한 흡수 가능 총량 [L]."""
    svp = 610.78 * math.exp(17.27 * t / (t + 237.3))
    rho_sat = svp * 0.018 / (8.314 * (t + 273.15)) * 1000.0
    return rho_sat * (1.0 - rh / 100.0) * vol / 1000.0


class TestPulseDurationIsHonoured:
    """① 효과 모델이 디스패처와 같은 분무 시간을 본다."""

    def test_펄스가_있으면_사이클이_아니라_펄스_시간으로_센다(self):
        """건조한 공기에서 봐야 총량 상한에 가려지지 않는다."""
        env = _env(rh=20.0)
        pulse = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))
        assert ef._fog_liters(env, 100.0, pulse) == pytest.approx(
            FOG_LPM * 30.0 / 60.0)

    def test_펄스가_없으면_종전대로_사이클_전체(self):
        """고압 미세포그는 연속 변조라 이 변경의 영향을 받지 않아야 한다.

        ⚠ 총량 상한에 가리지 않게 **작은 분무기**로 본다. 164 L/min 로는
        건조한 공기(RH 20% → 92.9 L)에서도 사이클 전체 1,640 L 가 상한에
        먼저 걸려, 시간 축만 따로 확인할 수 없다.
        """
        env = _env(rh=20.0)
        small = 5.0                                # L/min — 상한(92.9 L) 아래
        cont = _Profile(CmdConstraints(), fog_lpm=small)   # max_on_sec = 0
        assert ef._fog_liters(env, 100.0, cont) == pytest.approx(
            small * CYCLE_S / 60.0)
        pulse = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0),
                         fog_lpm=small)
        assert ef._fog_liters(env, 100.0, pulse) == pytest.approx(
            small * 30.0 / 60.0)

    def test_육묘_펄스가_더_적게_뿌린다(self):
        """육묘 모드는 '더 조이는 축' 이다 — 20초 < 30초."""
        env = _env(rh=20.0)
        normal = ef._fog_liters(env, 100.0,
                                _Profile(CmdConstraints(max_on_sec=30.0,
                                                        min_off_sec=180.0)))
        nursery = ef._fog_liters(env, 100.0,
                                 _Profile(CmdConstraints(max_on_sec=20.0,
                                                         min_off_sec=600.0)))
        assert nursery < normal

    def test_프로필에_제약이_없어도_죽지_않는다(self):
        """옛 호출부·테스트 fake 는 cmd_constraints 를 갖고 있지 않다."""
        class Bare:
            capacity_meta = {'volume_m3': VOL_M3, 'fog_flow_lpm': FOG_LPM}
        assert ef._fog_liters(_env(rh=20.0), 100.0, Bare()) is not None


class TestSaturationCapsTheTotal:
    """② 공기가 받을 수 있는 총량을 넘지 않는다."""

    def test_흡수_가능량을_넘지_않는다(self):
        env = _env(rh=89.0)
        liters = ef._fog_liters(env, 100.0,
                                _Profile(CmdConstraints(max_on_sec=30.0,
                                                        min_off_sec=180.0)))
        assert liters <= _absorbable(23.6, 89.0) + 1e-6

    def test_포화_공기에는_아무것도_증발하지_않는다(self):
        env = _env(rh=100.0)
        assert ef._fog_liters(env, 100.0, _Profile()) == pytest.approx(0.0)

    def test_건조한_공기에서는_상한이_걸리지_않는다(self):
        """상한이 정상 동작을 갉아먹으면 안 된다 — 뿌린 만큼이 답이다."""
        env = _env(rh=20.0)
        prof = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))
        assert ef._fog_liters(env, 100.0, prof) == pytest.approx(
            FOG_LPM * 30.0 / 60.0)

    def test_온습도를_모르면_상한을_걸지_않는다(self):
        """모르는 값을 지어내 자르면 그것대로 틀린 제어가 된다."""
        env = {'cycle_sec': CYCLE_S, 'volume_m3': VOL_M3}
        assert ef._absorbable_liters(env, VOL_M3) == float('inf')

    def test_체적을_모르면_상한을_걸지_않는다(self):
        assert ef._absorbable_liters(_env(), 0.0) == float('inf')


class TestEffectStaysBelowPhysics:
    """실측 사례가 물리 상한 아래로 들어왔는가."""

    def test_냉각이_물리_상한을_넘지_않는다(self):
        env = _env()
        prof = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))
        ceiling = _absorbable(23.6, 89.0) * ef._L_VAP_KJ_KG / (VOL_M3 * ef._RHO_CP_AIR)
        got = ef.fogger_temp_effect(env, 100.0, prof).magnitude_native
        assert got <= ceiling + 1e-6, (
            '증발냉각 %.2f °C 가 물리 상한 %.2f °C 를 넘는다' % (got, ceiling))

    def test_사고_당시_규모가_재발하지_않는다(self):
        """수정 전 이 조건에서 −219.7 °C/사이클 이 나왔다."""
        env = _env()
        prof = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))
        got = ef.fogger_temp_effect(env, 100.0, prof).magnitude_native
        assert got < 10.0, '한 사이클에 %.1f °C 는 물리적으로 불가능하다' % got

    def test_가습도_같은_상한을_따른다(self):
        env = _env()
        prof = _Profile(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))
        got = ef.fogger_humid_effect(env, 100.0, prof).magnitude_native
        assert got <= 100.0 - 89.0 + 1e-6, (
            'RH 89%%에서 +%.1f%% 는 100%%를 넘긴다' % got)


class TestKConstantPathUnchanged:
    """노즐 유량을 모르는 장치는 종전 동작 그대로여야 한다."""

    def test_유량_미상이면_보수적_상수로_떨어진다(self):
        class NoFlow:
            capacity_meta = {'volume_m3': VOL_M3}
            cmd_constraints = CmdConstraints()
        assert ef._fog_liters(_env(), 50.0, NoFlow()) is None
        r = ef.fogger_temp_effect(_env(), 50.0, NoFlow())
        assert r.magnitude_native > 0.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
