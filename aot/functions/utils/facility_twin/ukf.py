# coding=utf-8
"""
facility_twin/ukf.py — 시설 9상태 무향 칼만 필터 (계약 §3, 계획서 P1).

측정(T·RH·CO₂) 상태와 숨은 열질량 Tm, 느린 파라미터 두 개(로그 배율)를 한 벡터로 추정한다.
시그마점 19개(스케일드 UT). 파라미터 칸은 느린 무작위 걸음으로 두고, 관측이 공분산을 따라 고친다 —
"실내가 외기를 더 빨리 따라간다" → θ_UA↑ / θ_leak↑, "밤새 서서히 식는다" → Tm 이 덜 데워졌다 …

잔차 감시: 정규화 혁신(NIS)이 크면 센서 고장이거나 모델이 모르는 사건(문 열림 등)이다.
- 성분별 |혁신|/√S 가 `gate_sigma` 를 넘으면 그 성분은 이번 갱신에서 **버린다**(이상치가 파라미터를 끌고 가지 않게).
- 같은 성분이 `gate_max_run` 번 연속 버려지면 이상치가 아니라 **상태가 바뀐 것**(문이 열린 채 등)이라 받아들인다 —
  계속 버리면 필터가 낡은 상태에 갇힌다.
- 버린 횟수·NIS 는 `stats` 에 쌓여 일치도·상태 코드(계약 §7)에 쓰인다.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

import numpy as np

from .model import (I_AH, I_CO2, I_LLK, I_LSOL, I_LUA, I_LTR, I_LVENT, I_T, I_TM, LN_BOUND, LN_BOUND_TR, N_STATE, FacilityTwinModel)

OBS_NAMES = ("T", "RH", "CO2")

# 기본 불확실성 (모델 오차는 √h 당, 측정 잡음은 표준편차). 시설 설정이 덮어쓴다.
DEFAULT_PROCESS_SD_PER_SQRT_H = {"T": 0.30, "AH": 0.15, "CO2": 15.0, "Tm": 0.15, "lnUA": 0.010, "lnLeak": 0.030,
                                       "lnSol": 0.020, "lnVent": 0.020, "lnTr": 0.040}
DEFAULT_OBS_SD = {"T": 0.15, "RH": 1.5, "CO2": 15.0}
DEFAULT_P0_SD = {"T": 0.3, "AH": 0.5, "CO2": 30.0, "Tm": 2.0, "lnUA": 0.25, "lnLeak": 0.5, "lnSol": 0.4, "lnVent": 0.4, "lnTr": 2.0}
_NAMES = ("T", "AH", "CO2", "Tm", "lnUA", "lnLeak", "lnSol", "lnVent", "lnTr")


def _diag(d: Dict[str, float], square: bool = True) -> np.ndarray:
    v = np.array([d[n] for n in _NAMES], dtype=float)
    return np.diag(v * v if square else v)


class FacilityUKF:
    def __init__(self, model: FacilityTwinModel,
                 process_sd: Optional[Dict[str, float]] = None,
                 obs_sd: Optional[Dict[str, float]] = None,
                 p0_sd: Optional[Dict[str, float]] = None,
                 gate_sigma: float = 5.0, gate_max_run: int = 5, alpha: float = 0.5, beta: float = 2.0, kappa: float = 0.0):
        self.m = model
        self.q = dict(DEFAULT_PROCESS_SD_PER_SQRT_H, **(process_sd or {}))
        self.r_sd = dict(DEFAULT_OBS_SD, **(obs_sd or {}))
        self.p0_sd = dict(DEFAULT_P0_SD, **(p0_sd or {}))
        self.gate_sigma = float(gate_sigma)
        self.gate_max_run = int(gate_max_run)
        self._run = {k: 0 for k in OBS_NAMES}
        n = N_STATE
        lam = alpha * alpha * (n + kappa) - n
        self._lam = lam
        self._wm = np.full(2 * n + 1, 0.5 / (n + lam))
        self._wc = self._wm.copy()
        self._wm[0] = lam / (n + lam)
        self._wc[0] = lam / (n + lam) + (1.0 - alpha * alpha + beta)
        self.z: Optional[np.ndarray] = None
        self.P: Optional[np.ndarray] = None
        self.stats = {"n_upd": 0, "n_gated": 0, "nis_sum": 0.0, "nis_n": 0}

    # ── 시작 ────────────────────────────────────────────────────────────────
    def init(self, T: float, RH: float, CO2: float, Tm: Optional[float] = None) -> None:
        self.z = self.m.init_state(T, RH, CO2, Tm)
        self.P = _diag(self.p0_sd)

    # ── 시그마점 ────────────────────────────────────────────────────────────
    def _sigma(self, z: np.ndarray, P: np.ndarray) -> np.ndarray:
        n = N_STATE
        try:
            S = np.linalg.cholesky((n + self._lam) * P)
        except np.linalg.LinAlgError:               # 수치 오차로 양의 정부호가 깨졌다 — 고유값을 올려 복구
            w, V = np.linalg.eigh((P + P.T) / 2.0)
            S = np.linalg.cholesky((n + self._lam) * (V @ np.diag(np.clip(w, 1e-10, None)) @ V.T))
        pts = np.empty((2 * n + 1, n))
        pts[0] = z
        for i in range(n):
            pts[1 + i] = z + S[:, i]
            pts[1 + n + i] = z - S[:, i]
        return pts

    def _clip(self, z: np.ndarray) -> np.ndarray:
        z[I_LUA] = min(LN_BOUND, max(-LN_BOUND, z[I_LUA]))
        z[I_LLK] = min(LN_BOUND, max(-LN_BOUND, z[I_LLK]))
        z[I_LSOL] = min(LN_BOUND, max(-LN_BOUND, z[I_LSOL]))
        z[I_LVENT] = min(LN_BOUND, max(-LN_BOUND, z[I_LVENT]))
        z[I_LTR] = min(LN_BOUND_TR, max(-LN_BOUND_TR, z[I_LTR]))
        z[I_AH] = max(0.0, z[I_AH])
        return z

    # ── 예측 ────────────────────────────────────────────────────────────────
    def predict(self, dt: float, ext, cmds) -> None:
        pts = self._sigma(self.z, self.P)
        prop = np.array([self.m.propagate(p, ext, cmds, dt) for p in pts])
        z = self._wm @ prop
        d = prop - z
        P = (d * self._wc[:, None]).T @ d + _diag(self.q) * (dt / 3600.0)
        self.z, self.P = self._clip(z), (P + P.T) / 2.0

    # ── 갱신 ────────────────────────────────────────────────────────────────
    def update(self, obs: Dict[str, float]) -> Dict[str, float]:
        """obs: {"T","RH","CO2"} 중 있는 것. 반환: 성분별 혁신(버린 성분은 NaN 표시 안 함 — `gated` 참고)."""
        idx = [i for i, k in enumerate(OBS_NAMES) if k in obs and obs[k] is not None
               and not (isinstance(obs[k], float) and math.isnan(obs[k]))]
        if not idx:
            return {}
        pts = self._sigma(self.z, self.P)
        Y = np.array([self.m.observe(p) for p in pts])[:, idx]
        y = self._wm @ Y
        dy = Y - y
        dz = pts - self.z
        R = np.diag([self.r_sd[OBS_NAMES[i]] ** 2 for i in idx])
        S = (dy * self._wc[:, None]).T @ dy + R
        yo = np.array([obs[OBS_NAMES[i]] for i in idx], dtype=float)
        nu = yo - y
        # 성분별 이상치 문턱 — 버린 성분은 R 을 크게 해 무시한다(다른 성분은 그대로 쓴다)
        z_i = np.abs(nu) / np.sqrt(np.diag(S))
        bad = z_i > self.gate_sigma
        for j, i in enumerate(idx):                      # 연속 버림 횟수 — 넘으면 받아들인다
            k = OBS_NAMES[i]
            self._run[k] = self._run[k] + 1 if bad[j] else 0
            if bad[j] and self._run[k] > self.gate_max_run:
                bad[j] = False
        out = {OBS_NAMES[i]: float(nu[j]) for j, i in enumerate(idx)}
        self.stats["n_upd"] += 1
        if bad.any():
            self.stats["n_gated"] += int(bad.sum())
            keep = [j for j in range(len(idx)) if not bad[j]]
            if not keep:
                return dict(out, gated=1.0)
            idx = [idx[j] for j in keep]
            Y = Y[:, keep]
            y = y[keep]
            dy = dy[:, keep]
            R = np.diag([self.r_sd[OBS_NAMES[i]] ** 2 for i in idx])
            S = (dy * self._wc[:, None]).T @ dy + R
            nu = nu[keep]
        Pzy = (dz * self._wc[:, None]).T @ dy
        K = Pzy @ np.linalg.inv(S)
        self.z = self._clip(self.z + K @ nu)
        P = self.P - K @ S @ K.T
        self.P = (P + P.T) / 2.0 + np.eye(N_STATE) * 1e-10
        self.stats["nis_sum"] += float(nu @ np.linalg.solve(S, nu)) / max(len(nu), 1)
        self.stats["nis_n"] += 1
        if bad.any():
            out["gated"] = 1.0
        return out

    # ── 표본 ────────────────────────────────────────────────────────────────
    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """사후 N(z, P) 에서 n 개 (n, 9). 첫 행은 평균 그대로(결정론 멤버)."""
        w, V = np.linalg.eigh((self.P + self.P.T) / 2.0)
        A = V @ np.diag(np.sqrt(np.clip(w, 0.0, None)))
        out = np.array([self.z + A @ rng.standard_normal(N_STATE) for _ in range(n)])
        out[0] = self.z
        return np.array([self._clip(r) for r in out])

    @property
    def nis_mean(self) -> float:
        n = self.stats["nis_n"]
        return self.stats["nis_sum"] / n if n else float("nan")
