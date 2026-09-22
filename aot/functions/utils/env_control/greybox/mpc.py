# coding=utf-8
"""
greybox/mpc.py — greybox 모델 기반 수신지평(receding-horizon) MPC.

greybox 물리 모델로 H-스텝 미래를 예측하며 climate 채널 명령
(heat/cool/vent/fog/co2_inj) 을 직접 최적화한다. move-blocking(첫 move 만 자유,
지평 동안 유지) 으로 차원을 ≤5 로 낮춰 scipy L-BFGS-B 로 푼다. scipy 부재/실패 시
CEM(교차엔트로피) 으로 폴백한다.

목적함수:
  J(u) = Σ_k Σ_var w_var·((pred_k[var]-target_var)/scale_var)²
       + Σ_ch effort·(u_ch/100)² + Σ_ch slew_w·((u_ch-prev_ch)/100)²
  s.t. 0 ≤ u_ch ≤ 100  (actuator 가 존재하는 채널만 자유, 나머지 0 고정)

산출 채널 명령은 distribute_to_actuators 로 해당 kind actuator 들에 분배되고,
coordinator.finalize_command 로 slew·min-ON·operating-range 후처리된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .model import predict_horizon
from .params import GreyboxParams
from .channels import CHANNELS, channel_for_kind

_VAR_IDX = {'temperature': 0, 'humidity': 1, 'co2': 2}


@dataclass
class MPCConfig:
    horizon: int = 10            # 예측 지평(사이클 수)
    max_iter: int = 30           # 옵티마이저 반복 상한(시간 예산 대용)
    effort_weight: float = 0.002  # 에너지/개도 패널티
    slew_weight: float = 0.0005   # 이전 명령 대비 변화 패널티
    co2_scale: float = 100.0      # CO2 정규화 스케일(ppm)
    # 범위 벌점 가중치 — 벗어난 1 °C / 1 % 당(제곱). 추종 항(우선도/허용오차²,
    # VPD 1.2/0.1² = 120 kPa⁻²)과 견주어, 범위를 1 °C 넘는 것이 VPD 를 약 0.9 kPa
    # 놓치는 것만큼 아프다 — 온도 범위가 VPD 보다 확실히 앞선다. 10 이면 난방만
    # 있는 습한 밤에 VPD 를 좇느라 범위를 2 °C 넘었다(테스트 기록).
    # ⚠ 지평 동안 명령을 하나로 두는(move-blocking) 탓에 끝에서 0.5 °C 쯤은 넘을 수 있다.
    bound_weight: float = 100.0
    # ── C 단계 (2026-09-22) ────────────────────────────────────────────────
    # 에너지: 채널 kW(정격전력 × 종류별 단가, 호출부가 계산) × 가동률, 사이클마다.
    #   5 kW 난방 한 사이클 전량 = 0.1 — 온도 0.5 °C 오차(1.2·0.25 = 0.3)보다 싸다.
    energy_weight: float = 0.02
    # 난방·냉방 동시 가동: (u_heat/100)·(u_cool/100) 에 곱한다. 둘 다 전량이면
    #   사이클당 50 — 어떤 추종 이득으로도 정당화되지 않게.
    hc_weight: float = 50.0
    # 마모: 움직인 양(%)과, 직전 움직임과 **반대 방향**으로 움직인 양에 1차 벌점.
    #   개도 50 % 이동 = 0.025, 반대로 50 % = 추가 0.1. 추종을 막지 않고 흔들림만 누른다.
    move_weight: float = 0.05
    reversal_weight: float = 0.2


@dataclass
class MPCResult:
    channel_cmds: Dict[str, float]   # {channel: pct} 첫 move
    cost: float
    converged: bool
    method: str                      # 'lbfgsb' | 'cem' | 'noop'
    end_state: Optional[Tuple[float, float, float]] = None   # 지평 끝 예측 (T, RH, CO2)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def available_channels(profiles) -> List[str]:
    """프로필에 존재하는 actuator 가 커버하는 greybox 채널(정렬)."""
    have = set()
    for p in profiles:
        c = channel_for_kind(getattr(p, 'kind', None))
        if c:
            have.add(c)
    return [c for c in CHANNELS if c in have]


def optimize_channels(
    state: Tuple[float, float, float],
    targets: Dict[str, tuple],     # {var: (setpoint, tolerance, priority)}
    profiles,
    ext_seq: List[dict],           # 예보 ext 시퀀스(길이 ≤ H 면 마지막으로 패딩)
    params: GreyboxParams,
    prev_channel_cmds: Optional[Dict[str, float]],
    cycle_sec: float = 60.0,
    config: Optional[MPCConfig] = None,
    fixed_cmds: Optional[Dict[str, float]] = None,
    soft_bounds: Optional[Dict[str, tuple]] = None,
    channel_kw: Optional[Dict[str, float]] = None,
    prev_move: Optional[Dict[str, float]] = None,
) -> MPCResult:
    """`fixed_cmds`: 최적화하지 않지만 모델이 읽는 입력(예: 차광막 개도) — 지평 동안
    지금 값으로 둔다. 빠뜨리면 모델은 차광막이 걷힌 것으로 보고 일사를 과대 예측한다.

    `targets` 에 'vpd' 가 있으면 예측 (T, RH) 로 계산한 VPD 를 추종한다(결정 D3 —
    VPD 방식에서도 MPC 가 돈다). PI 의 VPD 직접 제어가 틀린 이유는 온도 결과를 모른
    채 밀었기 때문인데, MPC 는 온도를 예측하므로 `soft_bounds`
    ({'temperature': (lo, hi), 'humidity': (lo, hi)}, 벗어난 만큼 제곱 벌점)와
    함께 쓰면 극한 고온에서도 VPD 를 아주 덥거나 찬 공기로 맞추지 않는다.

    `channel_kw`: 채널별 에너지 무게(정격 kW × 종류별 단가) — 없으면 에너지 항 없음.
    `prev_move`: 채널별 직전 움직임(이번 사이클 전 명령 − 그 전 명령) — 반대 방향 벌점.
    """
    cfg = config or MPCConfig()
    avail = available_channels(profiles)
    if not avail or not ext_seq:
        return MPCResult({c: 0.0 for c in CHANNELS}, 0.0, True, 'noop')

    H = max(1, min(cfg.horizon, len(ext_seq)))
    seq = list(ext_seq[:H])
    while len(seq) < H:
        seq.append(seq[-1])

    # 변수 가중치: priority / tolerance²  (타이트·고우선 변수일수록 큼)
    weights: Dict[str, float] = {}
    for var, tv in targets.items():
        if (var not in _VAR_IDX and var != 'vpd') or tv is None:
            continue
        sp, tol, prio = tv
        if sp is None:
            continue
        t = tol if (tol and tol > 0) else 1.0
        weights[var] = float(prio if prio else 1.0) / (t * t)
    if not weights:
        return MPCResult({c: 0.0 for c in CHANNELS}, 0.0, True, 'noop')

    scale = {'temperature': 1.0, 'humidity': 1.0, 'co2': cfg.co2_scale, 'vpd': 1.0}
    soft = {k: v for k, v in (soft_bounds or {}).items()
            if k in ('temperature', 'humidity') and v}
    prev = prev_channel_cmds or {}
    kw = dict(channel_kw or {})
    pm = dict(prev_move or {})

    fixed = dict(fixed_cmds or {})

    def cost(uvec) -> float:
        cmds = {c: 0.0 for c in CHANNELS}
        cmds.update(fixed)
        for c, u in zip(avail, uvec):
            cmds[c] = float(u)
        traj = predict_horizon(state[0], state[1], state[2],
                               seq, [cmds] * H, params, cycle_sec)
        J = 0.0
        for (T, RH, CO2) in traj:
            sv = {'temperature': T, 'humidity': RH, 'co2': CO2}
            if 'vpd' in weights:
                sv['vpd'] = _vpd(T, RH)
            for var, wv in weights.items():
                sp = targets[var][0]
                J += wv * ((sv[var] - sp) / scale.get(var, 1.0)) ** 2
            for var, (lo, hi) in soft.items():
                x = sv.get(var)
                if x is None:
                    continue
                over = (lo - x) if (lo is not None and x < lo) else \
                       (x - hi) if (hi is not None and x > hi) else 0.0
                if over > 0.0:
                    J += cfg.bound_weight * over * over
        for c, u in zip(avail, uvec):
            J += cfg.effort_weight * (u / 100.0) ** 2
            du = u - prev.get(c, 0.0)
            J += cfg.slew_weight * (du / 100.0) ** 2
            # 에너지 — 명령을 지평 동안 유지하므로 H 사이클치
            J += cfg.energy_weight * kw.get(c, 0.0) * (u / 100.0) * H
            # 마모 — 매끄러운 |du| 와, 직전 방향과 반대인 몫
            J += cfg.move_weight * (_soft_abs(du) / 100.0)
            last = pm.get(c, 0.0)
            if abs(last) > 0.5:
                against = -du if last > 0 else du
                J += cfg.reversal_weight * (_soft_relu(against) / 100.0)
        # 난방·냉방 동시 가동
        if 'heat' in avail and 'cool' in avail:
            uh = uvec[avail.index('heat')] / 100.0
            uc = uvec[avail.index('cool')] / 100.0
            J += cfg.hc_weight * uh * uc * H
        return J

    x0 = [float(prev.get(c, 0.0)) for c in avail]
    bounds = [(0.0, 100.0)] * len(avail)

    method = 'lbfgsb'
    try:
        from scipy.optimize import minimize
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': cfg.max_iter})
        xbest = [float(v) for v in res.x]
        converged = bool(res.success)
    except Exception:
        xbest, converged = _cem(cost, x0, bounds, cfg.max_iter)
        method = 'cem'

    cmds = {c: 0.0 for c in CHANNELS}
    for c, u in zip(avail, xbest):
        cmds[c] = _clamp(u, 0.0, 100.0)
    end = None
    try:
        traj = predict_horizon(state[0], state[1], state[2], seq,
                               [dict(cmds, **fixed)] * H, params, cycle_sec)
        end = traj[-1] if traj else None
    except Exception:
        end = None
    return MPCResult(cmds, cost(xbest), converged, method, end)


def _soft_abs(x: float, eps: float = 1.0) -> float:
    """|x| 의 매끄러운 근사(% 단위, eps 1 %) — L-BFGS-B 가 미분할 수 있게."""
    import math
    return math.sqrt(x * x + eps * eps) - eps


def _soft_relu(x: float, eps: float = 1.0) -> float:
    """max(0, x) 의 매끄러운 근사 — 항상 0 이상(0 에서 eps/2)."""
    import math
    return 0.5 * (x + math.sqrt(x * x + eps * eps))


def _vpd(T: float, RH: float) -> float:
    import math
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    return max(0.0, svp * (1.0 - max(0.0, min(100.0, RH)) / 100.0))


def _cem(cost, x0, bounds, max_iter, pop=24, elite=6, seed_iters=None):
    """의존성 없는 교차엔트로피 최적화(샘플링 기반). scipy 폴백."""
    n = len(x0)
    mu = list(x0)
    sigma = [max((hi - lo) * 0.5, 1.0) for (lo, hi) in bounds]
    # 결정적 의사난수(시드 고정 — 재현성). LCG.
    rstate = 1234567
    def rnd():
        nonlocal rstate
        rstate = (1103515245 * rstate + 12345) & 0x7fffffff
        return rstate / 0x7fffffff
    def gauss(m, s):
        # Box-Muller
        import math
        u1 = max(rnd(), 1e-9); u2 = rnd()
        return m + s * math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    best_x = list(mu); best_j = cost(mu)
    iters = max(4, max_iter // 4)
    for _ in range(iters):
        samples = []
        for _p in range(pop):
            x = []
            for i in range(n):
                lo, hi = bounds[i]
                x.append(_clamp(gauss(mu[i], sigma[i]), lo, hi))
            j = cost(x)
            samples.append((j, x))
            if j < best_j:
                best_j = j; best_x = list(x)
        samples.sort(key=lambda t: t[0])
        top = [x for _j, x in samples[:elite]]
        for i in range(n):
            vals = [x[i] for x in top]
            mu[i] = sum(vals) / len(vals)
            var = sum((v - mu[i]) ** 2 for v in vals) / len(vals)
            sigma[i] = max(var ** 0.5, 0.5)
    return best_x, True


def distribute_to_actuators(channel_cmds: Dict[str, float], profiles) -> Dict[str, float]:
    """채널 명령(pct)을 해당 kind actuator 들에 분배(각 actuator = 채널 setpoint).

    greybox 모델이 채널을 집약값으로 다루므로, 같은 채널의 모든 actuator 에 동일
    setpoint 를 부여한다(레거시의 actuator 별 동일 자성 규약과 일관). 미모델 kind
    actuator 는 포함하지 않는다(호출부가 레거시로 별도 처리).
    """
    out: Dict[str, float] = {}
    for p in profiles:
        c = channel_for_kind(getattr(p, 'kind', None))
        if c is not None:
            out[p.actuator_id] = float(channel_cmds.get(c, 0.0))
    return out
