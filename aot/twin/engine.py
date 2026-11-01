# coding=utf-8
"""한 대상의 한 번 실행: 읽기 → 동기화(자리표시자) → 앙상블 예측 → TwinOutput.

모델은 확률을 모른다(계약 §10.7). 앙상블은 여기서 초기 상태·외기에 잡음을 넣어 만든다.
동기화는 아직 "최신 관측으로 초기화"뿐이다 — UKF(시설)·EnKF(노지)는 P1 에서 이 자리에 들어온다.
"""
from __future__ import annotations

import logging
import math
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

import numpy as np

from . import output as O
from .bench import Capability
from .expiry import valid_until_for
from .interfaces import TwinModel, TwinSource
from .types import Status, TargetKind, TargetSpec, TwinOutput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GridPlan:
    name: str
    step_s: float
    n_full: int          # k = 0 … n_full-1
    t0_floor_s: float    # t0 를 내리는 단위
    tables: tuple        # (분위수 변수 표, p50 전용 표, 사건 표)

    def n_points(self, horizon_frac: float) -> int:
        return 1 + int((self.n_full - 1) * horizon_frac)


GRID_PLANS: Dict[TargetKind, List[GridPlan]] = {
    TargetKind.FACILITY: [GridPlan("fast", 600.0, 289, 60.0,
                                   (O.FACILITY_Q, {}, O.FACILITY_EVENTS))],
    # 노지 시 격자(hourly)는 진짜 노지 모델 쪽에서 계획에 추가한다.
    TargetKind.FIELD: [GridPlan("daily", 86400.0, 15, 3600.0,
                                (O.FIELD_DAILY_Q, O.FIELD_DAILY_P50_ONLY, O.FIELD_DAILY_EVENTS))],
}
DEFAULT_MAX_AGE_S = {TargetKind.FACILITY: 1800.0, TargetKind.FIELD: 6 * 3600.0}
OBS_WINDOW_S = {TargetKind.FACILITY: 3 * 3600.0, TargetKind.FIELD: 3 * 86400.0}
EXT_SIGMA = {"T_ext": 1.5, "RH_ext": 8.0}      # 외기 예보 불확실성(자리표시자, 선행시간 무관 상수)


@dataclass
class RunResult:
    output: Optional[TwinOutput]
    status: Status
    reason: str = ""
    n_points: int = 0
    timings: Dict[str, float] = field(default_factory=dict)
    info: Dict[str, object] = field(default_factory=dict)     # 사람용 요약(모델이 채운다)
    #: 작동 시계열(`env_twin_act`) 계열 — 모델이 채운다(`twin_effects.scenario.ActSeries` 목록). 없으면 쓰지 않는다.
    act: List[object] = field(default_factory=list)
    #: 장치 효과 보고 `[{id, kind, channel, status, source}]`(설계서 §6.2 `effects[]`). 장치 목록을 모르면 빈 목록.
    effects: List[Dict[str, object]] = field(default_factory=list)


def _floor(t: float, unit: float) -> float:
    return math.floor(t / unit) * unit


def run_member_fn(model: TwinModel, x0, u, w, plan: GridPlan, n_pts: int):
    """멤버 하나의 궤적(파생 변수 dict 의 목록, k=0…n_pts-1)."""
    dt = min(float(model.dt_nominal_s), plan.step_s)
    sub = max(1, int(math.ceil(plan.step_s / dt)))
    dt_sub = plan.step_s / sub
    x = dict(x0)
    traj = [model.derived(x)]
    for _ in range(1, n_pts):
        for _ in range(sub):
            x = model.step(x, u, w, dt_sub)
        traj.append(model.derived(x))
    return traj


def excluded_lines(spec: TargetSpec) -> List[str]:
    """동기화에서 뺀 입력(예보·모델값·시뮬레이터 — `discovery` 가 `options['excluded_inputs']` 로 남긴다)의 결과 한 줄들."""
    ex = spec.options.get("excluded_inputs") or {}
    return [str(e.get("line")) for e in ex.values() if isinstance(e, dict) and e.get("line")]


def run_target(spec: TargetSpec, source: TwinSource, model: TwinModel, cap: Capability,
               now: float, period_s: Optional[float] = None, seed: Optional[int] = None) -> RunResult:
    """대상 하나를 돌린다. 관측이 아니라 뺀 입력이 있으면 그 줄('관측이 아님 — 동기화에서 제외')을 결과 이유에 붙인다."""
    res = _run_target(spec, source, model, cap, now, period_s, seed)
    lines = excluded_lines(spec)
    if lines:
        res.reason = "; ".join([x for x in [res.reason] + lines if x])
    return res


def _run_target(spec: TargetSpec, source: TwinSource, model: TwinModel, cap: Capability,
                now: float, period_s: Optional[float] = None, seed: Optional[int] = None) -> RunResult:
    kind = spec.kind
    opts = spec.options
    req = tuple(model.required_for(spec)) if hasattr(model, "required_for") \
        else tuple(getattr(model, "required_inputs", ()))
    max_age = float(opts.get("max_obs_age_s", DEFAULT_MAX_AGE_S[kind]))
    period = float(period_s or cap.period_s)

    # 1) 전제: 필수 입력이 배선돼 있어야 한다 (계약 §3)
    unwired = [k for k in req if k not in spec.inputs]
    if unwired:
        return _unusable(spec, now, period, Status.NOT_TWINNABLE, f"필수 입력 미배선: {unwired}")
    degraded_reason = ""        # 출처 표시(실측·미러·가상)는 판정에 쓰지 않는다 — 위치로 정해진 입력을 그대로 동기화한다

    # 모델이 실행 전체를 맡는 경우(노지 EnKF — 이력 전체를 동화한다). 전제 검사는 위에서 끝났다.
    if hasattr(model, "run_target"):
        try:
            res = model.run_target(spec, source, cap, now, period, seed)
        except Exception as e:
            logger.exception("트윈 계산 실패 %s", spec.key)
            return _unusable(spec, now, period, Status.ERROR, f"계산 실패: {e!r}")
        if degraded_reason and res.output is not None and res.status == Status.OK:
            res.status = Status.DEGRADED
            res.output.meta["status"] = int(Status.DEGRADED)
        if degraded_reason:
            res.reason = (degraded_reason + "; " + res.reason).strip("; ")
        return res

    # 2) 읽기
    window = float(opts.get("obs_window_s", OBS_WINDOW_S[kind]))
    last: Dict[str, tuple] = {}
    for name, ref in spec.inputs.items():
        try:
            s = source.read_series(ref, window, now)
        except Exception as e:                                     # 읽기 실패는 그 입력의 결측으로 본다
            logger.warning("트윈 읽기 실패 %s/%s: %s", spec.server_id, name, e)
            s = None
        if s is not None and len(s):
            last[name] = s.last()
    missing_req = [k for k in req if k not in last]
    if missing_req:
        return _unusable(spec, now, period, Status.UNSYNCED, f"필수 입력 관측 없음: {missing_req}")
    ages = {k: now - last[k][0] for k in req}
    if max(ages.values()) > max_age:
        return _unusable(spec, now, period, Status.UNSYNCED,
                         f"관측이 낡음: {max(ages.values()):.0f}s > {max_age:.0f}s")
    missing_opt = [k for k in spec.inputs if k not in req and k not in last]
    if missing_opt:
        degraded_reason = (degraded_reason + "; " if degraded_reason else "") + f"보조 입력 결측: {missing_opt}"

    obs = {k: v[1] for k, v in last.items()}
    newest = max(last[k][0] for k in req)
    plans = GRID_PLANS[kind]
    t0 = _floor(newest, plans[0].t0_floor_s)

    # 3) 상태 초기화 + 예측 (정책 0 = 현재 설정 고정: 제어 입력은 마지막 값)
    try:
        x0 = model.init_state(spec, t0, obs)
        u = {k: last[k][1] if k in last else float("nan") for k in spec.controls}
        w = dict(obs)
        rng = np.random.default_rng(seed if seed is not None else
                                    zlib.crc32(f"{spec.key}:{t0}".encode()))
        out = TwinOutput(kind=kind, target_id=spec.target_id, t0=t0, facility=spec.facility)
        n_members = cap.ensemble_size
        sigma = getattr(model, "noise_sigma", {})
        for plan in plans:
            n_pts = plan.n_points(cap.horizon_frac)
            members = []
            for m in range(n_members):
                if m == 0:
                    xm, wm = x0, w                                  # 0번 멤버는 잡음 없는 결정론
                else:
                    xm = {k: v + sigma.get(k, 0.0) * rng.standard_normal() for k, v in x0.items()}
                    wm = {k: v + EXT_SIGMA.get(k, 0.0) * rng.standard_normal() if k in EXT_SIGMA else v
                          for k, v in w.items()}
                traj = run_member_fn(model, xm, u, wm, plan, n_pts)
                members.append((traj, model.risks(traj, spec)))
            _collect(out, plan, members, t0, n_pts, n_members)
    except Exception as e:
        logger.exception("트윈 계산 실패 %s", spec.key)
        return _unusable(spec, now, period, Status.ERROR, f"계산 실패: {e!r}")

    status = Status.DEGRADED if degraded_reason else Status.OK
    horizon = (plans[0].n_points(cap.horizon_frac) - 1) * plans[0].step_s
    out.meta = {
        "status": int(status),
        "valid_until": valid_until_for(t0, period, status,
                                       "field_daily" if kind == TargetKind.FIELD else "facility"),
        ("horizon_d" if kind == TargetKind.FIELD else "horizon_h"):
            horizon / (86400.0 if kind == TargetKind.FIELD else 3600.0),
        "ensemble_size": n_members,
        "stale_s": max(0.0, now - t0),
        "model_rev": getattr(model, "model_rev", 0),
    }
    if kind == TargetKind.FACILITY:
        out.meta.update({"policy": 0, "weather_src": 4})     # 현재 설정 고정 · 실측 외기 지속
    return RunResult(out, status, degraded_reason, n_points=sum(len(g) for g in out.grids.values()))


def _collect(out: TwinOutput, plan: GridPlan, members, t0: float, n_pts: int, n_members: int) -> None:
    q_tab, p50_tab, ev_tab = plan.tables
    times = [t0 + k * plan.step_s for k in range(n_pts)]
    out.grids[plan.name] = times
    keys = [k for k in members[0][0][0] if k in q_tab or k in p50_tab]
    qout: Dict[str, Dict[str, list]] = {}
    for var in keys:
        arr = np.array([[s[var] for s in traj] for traj, _ in members], dtype=float)
        if n_members >= 2:
            p10, p50, p90 = np.percentile(arr, [10, 50, 90], axis=0)
            qout[var] = {"p10": p10.tolist(), "p50": p50.tolist(), "p90": p90.tolist()}
        else:
            qout[var] = {"p50": arr[0].tolist()}                 # 앙상블 없음: 가짜 띠를 쓰지 않는다(계약 §5)
    out.quantiles[plan.name] = qout
    ev: Dict[str, list] = {}
    for name in ev_tab:
        rows = [r[name] for _, r in members if name in r]
        if rows:
            ev[name] = np.mean(np.array(rows, dtype=float), axis=0).tolist()
    out.events[plan.name] = ev


def _field_header_t0(spec: TargetSpec, now: float) -> float:
    """노지 머리말만 내는 발행의 `t0` — 구획 시간대의 오늘 00 시. 정상 발행(일 격자 k=0)과 **같은 시각**이라 같은 날
    나중에 정상으로 돌면 이 머리말을 덮어쓴다. 시간 단위로 내리면(예전) 오전에 한 번 '계산 불가' 로 발행한 구획이
    설정을 고친 뒤 정상으로 돌아도, 더 늦은 시각의 낡은 머리말이 '가장 최근' 으로 읽혀 다음 날 00 시까지 지도에서
    숨겨졌다(3포장, 2026-10-25)."""
    from .models.field_bucket import _tz_offset_s
    tz = _tz_offset_s(str(spec.options.get("timezone", "UTC")), now)
    return math.floor((now + tz) / 86400.0) * 86400.0 - tz


def _unusable(spec: TargetSpec, now: float, period: float, status: Status, reason: str) -> RunResult:
    """곡선 없이 머리말만 발행한다. 즉시 만료(valid_until = t0) — 소비자는 트윈을 숨긴다(계약 §7-3)."""
    logger.info("트윈 %s → %s: %s", spec.key, status.name, reason)
    kind = spec.kind
    t0 = _floor(now, 60.0) if kind == TargetKind.FACILITY else _field_header_t0(spec, now)
    out = TwinOutput(kind=kind, target_id=spec.target_id, t0=t0, facility=spec.facility)
    out.meta = {"status": int(status), "valid_until": valid_until_for(t0, period, status),
                "stale_s": max(0.0, now - t0)}
    return RunResult(out, status, reason)


unusable = _unusable          # 모델 부품이 같은 규칙으로 머리말만 발행할 때 쓴다
