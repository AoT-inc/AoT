# coding=utf-8
"""
facility_twin/sync.py — 이력을 시간 격자에 올려 필터를 돌린다 (계약 §3·§7, 계획서 P1 '일치도').

입력은 모두 `(times, values)` 계열이다(AoT 측정 그대로 — 균일 격자일 필요 없다).
- 측정 `obs`  : T, RH, (CO2)     — 필터 갱신에 쓴다
- 외기 `ext`  : T_ext, RH_ext, solar, wind, (CO2_ext) — 마지막 값 유지(`ext_max_hold_s` 넘게 낡으면 없는 것으로)
- 명령 `cmds` : heat, cool, vent, fog, co2_inj, shade, curtain (%) — 마지막 값 유지. 모르는 칸은 기본값(0, 차광·커튼은 걷힘)

일치도(P1 지표): 필터가 지나가는 동안 `lead_s` 마다 **지금까지의 정보만으로 한 선행 예측**을 꺼내 두었다가,
그 시각의 실제 측정과 견준다. 선행 예측의 외기는 두 가지로 센다 —
`actual`(앞 한 시간의 실제 외기·**실제 명령**을 아는 경우 — 모델 자체의 실력) 과 `persist`(발행 시점 외기·명령을 유지 —
제품이 실제로 내는 것. 되먹임 제어가 한 시간 안에 명령을 바꾸면 그 몫이 오차에 섞인다).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .model import FacilityTwinModel
from .ukf import FacilityUKF

Series = Tuple[Sequence[float], Sequence[float]]
DEFAULT_CMDS = {"heat": 0.0, "cool": 0.0, "vent": 0.0, "fog": 0.0, "co2_inj": 0.0, "shade": 100.0, "curtain": 100.0}
DEFAULT_EXT = {"T_ext": 15.0, "RH_ext": 60.0, "CO2_ext": 420.0, "solar": 0.0, "wind": 1.0}


class _Hold:
    """마지막 값 유지 조회. 시각 정렬 목록과 이분 탐색."""

    def __init__(self, series: Optional[Series], max_hold_s: float = math.inf):
        t, v = series if series else ([], [])
        pairs = sorted((float(a), float(b)) for a, b in zip(t, v) if b is not None and not math.isnan(float(b)))
        self.t = [p[0] for p in pairs]
        self.v = [p[1] for p in pairs]
        self.max_hold = max_hold_s

    def at(self, t: float) -> Optional[float]:
        i = bisect.bisect_right(self.t, t) - 1
        if i < 0 or t - self.t[i] > self.max_hold:
            return None
        return self.v[i]

    def window(self, t_lo: float, t_hi: float) -> Optional[float]:
        """(t_lo, t_hi] 안의 마지막 값."""
        i = bisect.bisect_right(self.t, t_hi) - 1
        if i < 0 or self.t[i] <= t_lo:
            return None
        return self.v[i]

    def first_time(self) -> Optional[float]:
        return self.t[0] if self.t else None


@dataclass
class SyncResult:
    ukf: FacilityUKF
    model: FacilityTwinModel
    t_end: float
    n_steps: int = 0
    n_obs: int = 0
    last_obs_t: float = float("nan")
    # 1스텝 혁신(관측 − 예측) 제곱합 — 성분별
    innov_ss: Dict[str, float] = field(default_factory=lambda: {"T": 0.0, "RH": 0.0, "CO2": 0.0})
    innov_n: Dict[str, int] = field(default_factory=lambda: {"T": 0, "RH": 0, "CO2": 0})
    # lead_s → 변수 → [오차...]  (모델 실력 'actual' / 제품 'persist')
    lead_err: Dict[str, Dict[float, Dict[str, List[float]]]] = field(
        default_factory=lambda: {"actual": {}, "persist": {}})

    # 선행 오차의 대상 시각 (진단용) — lead_err 와 같은 모양
    lead_t: Dict[str, Dict[float, Dict[str, List[float]]]] = field(
        default_factory=lambda: {"actual": {}, "persist": {}})

    def rmse_1step(self, name: str) -> float:
        n = self.innov_n.get(name, 0)
        return math.sqrt(self.innov_ss[name] / n) if n else float("nan")

    def rmse_lead(self, lead_s: float, name: str, kind: str = "persist") -> float:
        e = self.lead_err[kind].get(lead_s, {}).get(name, [])
        return math.sqrt(sum(x * x for x in e) / len(e)) if e else float("nan")

    def n_lead(self, lead_s: float, name: str = "T", kind: str = "persist") -> int:
        return len(self.lead_err[kind].get(lead_s, {}).get(name, []))


def assimilate(model: FacilityTwinModel, ukf: FacilityUKF, t_start: float, t_end: float,
               obs: Mapping[str, Series], ext: Mapping[str, Series], cmds: Mapping[str, Series],
               dt_s: float = 120.0, ext_max_hold_s: float = 3 * 3600.0,
               lead_s: Sequence[float] = (3600.0,), lead_every_s: float = 1800.0,
               lead_skip_s: float = 3 * 3600.0, obs_tol_s: float = 600.0) -> Optional[SyncResult]:
    """`t_start`~`t_end` 를 `dt_s` 격자로 돌린다. 첫 T·RH 관측으로 초기화하고, 관측이 없으면 None.

    lead_skip_s : 시작 후 이 시간까지는 선행 오차를 세지 않는다(필터가 자리 잡는 시간).
    obs_tol_s   : 선행 예측과 견줄 실제 측정을 찾는 허용 시차.
    """
    o = {k: _Hold(obs.get(k)) for k in ("T", "RH", "CO2")}
    ex = {k: _Hold(ext.get(k), ext_max_hold_s) for k in DEFAULT_EXT}
    cm = {k: _Hold(cmds.get(k), 6 * 3600.0) for k in DEFAULT_CMDS}
    ts = [h.first_time() for h in (o["T"], o["RH"]) if h.first_time() is not None]
    if len(ts) < 2:
        return None

    def ext_at(t: float) -> Dict[str, float]:
        return {k: (v if (v := ex[k].at(t)) is not None else DEFAULT_EXT[k]) for k in DEFAULT_EXT}

    def cmds_at(t: float) -> Dict[str, float]:
        return {k: (v if (v := cm[k].at(t)) is not None else DEFAULT_CMDS[k]) for k in DEFAULT_CMDS}

    res = SyncResult(ukf=ukf, model=model, t_end=t_end)
    t = max(t_start, max(ts))
    # 시작: 그 시점의 마지막 측정으로 초기화
    T0, RH0 = o["T"].at(t), o["RH"].at(t)
    if T0 is None or RH0 is None:
        return None
    ukf.init(T0, RH0, o["CO2"].at(t) if o["CO2"].at(t) is not None else 420.0)
    t_first = t
    next_lead = t + lead_skip_s
    pending: List[Tuple[float, str, float, np.ndarray, Dict[str, float]]] = []   # (대상 시각, 종류, 선행, 예측, ...)

    while t < t_end - 1e-6:
        e_now, c_now = ext_at(t), cmds_at(t)
        ukf.predict(dt_s, e_now, c_now)
        t += dt_s
        res.n_steps += 1
        ob = {}
        for k in ("T", "RH", "CO2"):
            v = o[k].window(t - dt_s, t)
            if v is not None:
                ob[k] = v
        if ob:
            innov = ukf.update(ob)
            res.n_obs += 1
            res.last_obs_t = t
            for k in ("T", "RH", "CO2"):
                if k in innov and not innov.get("gated"):
                    res.innov_ss[k] += innov[k] ** 2
                    res.innov_n[k] += 1
        # 선행 예측 꺼내 두기
        if t >= next_lead and t < t_end - min(lead_s):
            next_lead = t + lead_every_s
            for L in lead_s:
                n_pts = int(round(L / 600.0)) + 1
                e_frozen = dict(ext_at(t))
                c_frozen = cmds_at(t)
                tr_p = model.predict(ukf.z, lambda _t, e=e_frozen: e, c_frozen, t, 600.0, n_pts)
                tr_a = model.predict(ukf.z, ext_at, cmds_at, t, 600.0, n_pts)
                pending.append((t + L, "persist", L, model.observe(tr_p[-1])))
                pending.append((t + L, "actual", L, model.observe(tr_a[-1])))
        # 만기가 된 선행 예측과 실제 측정 비교 — 측정이 도착한 뒤(t ≥ 대상 시각) 가까운 값을 쓴다
        if pending:
            keep = []
            for item in pending:
                tt, kind, L, pred = item
                if t < tt:
                    keep.append(item)
                    continue
                vals = {}
                for k, idx in (("T", 0), ("RH", 1), ("CO2", 2)):
                    h = o[k]
                    i = bisect.bisect_right(h.t, tt) - 1
                    if i >= 0 and tt - h.t[i] <= obs_tol_s:
                        vals[k] = (h.v[i], pred[idx])
                    else:                                   # 대상 시각 직후 값도 허용
                        j = bisect.bisect_left(h.t, tt)
                        if j < len(h.t) and h.t[j] - tt <= obs_tol_s:
                            vals[k] = (h.v[j], pred[idx])
                for k, (y, p) in vals.items():
                    res.lead_err[kind].setdefault(L, {}).setdefault(k, []).append(p - y)
                    res.lead_t[kind].setdefault(L, {}).setdefault(k, []).append(tt)
            pending = keep
    return res
