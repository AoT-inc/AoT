# coding=utf-8
"""
coordinator 폐루프 안정성 테스트 (P6 position-form PI 재설계).

배경: 기존 deadbeat 법칙(cmd = residual/unit_mag×100)은 작은 편차도 100% 로
포화시켜, 환기창이 0↔100 사이를 왕복하는 릴레이 진동을 일으켰다(현장 aot-005).
position-form PI 는 평형 개도로 수렴해 부드럽게 유지해야 한다.

여기서는 간단한 1차 열 플랜트(환기 개도에 비례한 냉각 + 일정한 일사 부하)를
coordinator 와 폐루프로 돌려 다음을 검증한다.
  1. 개도가 내부 평형값(0%·100% 가 아닌)으로 수렴
  2. 정착 후 개도 진폭(표준편차)이 작다 — bang-bang 없음
  3. 내부온도가 목표 근방으로 수렴
"""

import statistics

from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import TargetVar

from .conftest import make_ctx, make_opening_profile


def _simulate(n_cycles=80, T_start=30.0, T_ext=20.0, target_T=24.0,
              tol=0.5, heat_per_cycle=0.12, k_cool=0.06, slew=20.0):
    """환기 개도에 비례해 냉각되는 1차 열 플랜트 폐루프 시뮬레이션.

    Returns: (apertures, temps) — 사이클별 개도(%)와 내부온도(°C) 궤적.
    """
    target = {'temperature': TargetVar(value=target_T, tolerance=tol, priority=1.0)}
    p = make_opening_profile('v1')
    p.cmd_constraints.slew_per_cycle = slew

    state = CoordinatorState()
    T_int = T_start
    apertures, temps = [], []

    for _ in range(n_cycles):
        ctx = make_ctx(T_int=T_int, T_ext=T_ext, RH_int=60.0, RH_ext=55.0)
        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        cmds, state = coordinate(report, [p], state)
        ap = cmds['v1'].aperture
        apertures.append(ap)
        temps.append(T_int)

        # 플랜트 1차 업데이트: 일사 부하(+) - 환기 냉각(개도·내외 온도차 비례)
        cooling = max(0.0, (T_int - T_ext)) * k_cool * (ap / 100.0)
        T_int = T_int + heat_per_cycle - cooling

    return apertures, temps


class TestClosedLoopStability:
    def test_converges_to_interior_equilibrium(self):
        """개도가 0%·100% 가 아닌 내부 평형값으로 수렴한다 (릴레이 아님)."""
        apertures, _ = _simulate()
        settled = apertures[-20:]
        mean_ap = statistics.mean(settled)
        # 내부 평형 — 양 끝에 붙어있지 않음
        assert 5.0 < mean_ap < 95.0, f"개도가 평형이 아닌 끝에 고착: {mean_ap:.1f}%"

    def test_no_bang_bang_oscillation(self):
        """정착 후 개도 진폭(표준편차)이 작다 — 0↔100 왕복이 아님."""
        apertures, _ = _simulate()
        settled = apertures[-20:]
        spread = max(settled) - min(settled)
        std = statistics.pstdev(settled)
        # 릴레이 진동이면 spread 가 ~100 에 달함. 평활 제어는 작은 범위.
        assert spread < 25.0, f"개도 진폭 과다(진동 의심): spread={spread:.1f}%"
        assert std < 10.0, f"개도 표준편차 과다: std={std:.1f}%"

    def test_temperature_converges_near_target(self):
        """내부온도가 목표(24°C) 근방으로 수렴한다."""
        _, temps = _simulate()
        settled = temps[-20:]
        mean_T = statistics.mean(settled)
        assert abs(mean_T - 24.0) < 1.5, f"온도 미수렴: 평균 {mean_T:.2f}°C"

    def test_no_conflict_toggle_limit_cycle(self):
        """T-RH 트레이드오프(냉방 개방이 습도 악화) 상황에서 개도가 토글하지 않는다.

        현장 aot-005 전환구간(15:30~18:30) 재현: 온도는 냉방 위해 열고 싶은데
        창호를 열면 외부 습공기가 들어와 습도가 악화된다. 구 binary conflict +
        relax-close 는 open→close→open limit-cycle(개도 0↔65 왕복)을 만들었다.
        결합 drive(다목적 gradient-descent)는 단일 평형으로 수렴해야 한다.
        """
        target = {
            'temperature': TargetVar(value=24.0, tolerance=0.5, priority=1.0),
            'humidity':    TargetVar(value=55.0, tolerance=3.0, priority=1.2),
        }
        p = make_opening_profile('v1')
        p.cmd_constraints.slew_per_cycle = 20.0

        st = CoordinatorState()
        T, RH = 26.0, 58.0
        ap = []
        for _ in range(60):
            ctx = make_ctx(T_int=T, T_ext=20.0, RH_int=RH, RH_ext=80.0)
            report, _ = assess(target, ctx['internal'], ctx['external'],
                               cycle_sec=60.0, now_ts=ctx['now_ts'])
            cmds, st = coordinate(report, [p], st)
            a = cmds['v1'].aperture
            ap.append(a)
            # 플랜트: 개방 시 T↓(외기20), RH↑(외기80) — 냉방-제습 상충
            T  += 0.10 - (T - 20.0) * 0.08 * (a / 100.0)
            RH += -0.30 + (80.0 - RH) * 0.05 * (a / 100.0)

        settled = ap[-20:]
        spread = max(settled) - min(settled)
        std = statistics.pstdev(settled)
        mean_ap = statistics.mean(settled)
        # 토글이면 spread 가 수십 % (0↔65). 단일 평형이면 거의 0.
        assert spread < 12.0, f"충돌 토글 의심: spread={spread:.1f}%"
        assert std < 5.0, f"개도 표준편차 과다: std={std:.1f}%"
        # 양 끝이 아닌 내부 평형(냉방-제습 절충)으로 수렴
        assert 5.0 < mean_ap < 95.0, f"평형이 끝에 고착: {mean_ap:.1f}%"

    def test_overshoot_then_close(self):
        """목표보다 차가워지면(과냉) 개도가 닫히는 방향으로 줄어든다."""
        # 외기가 매우 차고 일사부하 작음 → 쉽게 과냉 → 닫혀야 함
        apertures, temps = _simulate(T_start=26.0, T_ext=10.0, target_T=24.0,
                                     heat_per_cycle=0.05, k_cool=0.12)
        # 정착 후 온도가 목표 이하로 내려가면 개도는 낮게 유지(닫힘 우세)
        settled_T = statistics.mean(temps[-20:])
        settled_ap = statistics.mean(apertures[-20:])
        if settled_T <= 24.0:
            assert settled_ap < 50.0, \
                f"과냉인데 개도가 닫히지 않음: T={settled_T:.2f}, ap={settled_ap:.1f}%"
