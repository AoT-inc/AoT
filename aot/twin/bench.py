# coding=utf-8
"""시작 시 벤치마크 → 기능 축소 (계획서 원칙 5). 노드 성능에 맞춰 앙상블 수·지평·주기를 정한다.

계약 §4: 경량 모드는 지평 24 h, 앙상블 없음(p50 만), 격자 간격은 그대로. 주기는 늘릴 수 있다.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Capability:
    tier: str              # 'full' | 'deterministic' | 'light'
    ensemble_size: int     # 1 이면 p50 만 낸다
    horizon_frac: float    # 1.0 = 전체 지평, 0.5 = 절반(48 h → 24 h)
    period_s: float        # 발행 주기
    per_member_s: float    # 벤치로 잰 멤버 1개 비용(초)
    forced: bool = False


FULL = Capability("full", 50, 1.0, 3600.0, 0.0)


def measure(run_member: Callable[[], object], repeats: int = 3) -> float:
    """멤버 1개(전체 지평) 실행 시간의 중앙값(초). 첫 호출은 준비 비용이라 버린다."""
    run_member()
    ts = []
    for _ in range(max(1, repeats)):
        t = time.perf_counter()
        run_member()
        ts.append(time.perf_counter() - t)
    ts.sort()
    return ts[len(ts) // 2]


def decide(per_member_s: float, n_targets: int = 1, period_s: float = 3600.0,
           budget_frac: float = 0.25, max_ensemble: int = 50, min_ensemble: int = 10,
           light_horizon_frac: float = 0.5) -> Capability:
    """주기의 `budget_frac` 만 계산에 쓴다고 보고, 대상 수로 나눈 시간 안에 들어가는 만큼만 켠다.

    - 멤버가 min_ensemble 개 이상 들어가면 full (앙상블, 분위수 p10/50/90)
    - 1개는 들어가면 deterministic (전체 지평, p50 만)
    - 그것도 안 되면 light (지평 절반, p50 만) — 그래도 안 들어가면 주기를 늘린다
    """
    per = max(per_member_s, 1e-6)
    n_targets = max(1, n_targets)
    budget = period_s * budget_frac / n_targets
    fit = int(budget // per)
    if fit >= min_ensemble:
        return Capability("full", min(fit, max_ensemble), 1.0, period_s, per_member_s)
    if fit >= 1:
        return Capability("deterministic", 1, 1.0, period_s, per_member_s)
    need = per * light_horizon_frac * n_targets / budget_frac
    period = max(period_s, math.ceil(need / 3600.0) * 3600.0)
    return Capability("light", 1, light_horizon_frac, period, per_member_s)


def forced(tier: Optional[str], period_s: float = 3600.0) -> Optional[Capability]:
    """설정으로 단계를 못박을 때(시험·한 기기 모드). 모르는 이름이면 None."""
    table = {"full": Capability("full", 50, 1.0, period_s, 0.0, True),
             "deterministic": Capability("deterministic", 1, 1.0, period_s, 0.0, True),
             "light": Capability("light", 1, 0.5, period_s, 0.0, True)}
    return table.get(tier or "")
