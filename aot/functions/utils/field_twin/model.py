# coding=utf-8
"""
field_twin/model.py — 노지 구획 물 수지 모델 (FAO-56 이중 작물계수 + 층 버킷).

계약(docs/design/digital-twin.md) §10.7 의 공통 인터페이스 `TwinModel` 을 노지 쪽으로
구현한다: `kind='field'`, 상태 순서 `state_names`, 느린 파라미터 `param_names`,
결정론 `step(x, u, w, dt_s)`, 관측식 `observe(x, sensor)`, 파생 `derived(x)`,
위험 사건 `risks(traj)`.

## 상태 벡터 (계약 §10.2)

    x = [theta1, theta2, theta3, Ts1, gdd | theta_wp, theta_fc, theta_sat, tau_drain_d, kcb_scale, k_bottom]

앞 5개가 상태, 뒤 6개가 파라미터다. 파라미터를 상태 뒤에 붙여 두면 EnKF 가 한 벡터로
함께 고칠 수 있다(증강 상태). `step` 은 파라미터를 바꾸지 않는다. 모든 연산은 마지막
축에서 이름으로 꺼내 쓰므로 x 가 (n,) 이든 앙상블 (N, n) 이든 그대로 돈다.

## 한 스텝 (부분 스텝 ≤ 3 h 로 쪼개 순서대로)

1. **들어옴**: 비 + 관수가 1층에 들어간다. 포화를 넘는 물은 아래층으로 넘치고, 맨
   아래까지 포화면 지표 유출.
2. **배수**: 포장용수량 위 물이 선형 저수조로 빠진다 — q = S_excess·(1 − e^(−h/τ_i)),
   τ_i = tau_drain_d·(층 두께/10 cm). 지수형이라 h 가 τ 보다 커도 안정. 아랫층이
   포화면 받을 만큼만 내려가고, 맨 아래에서는 심부 침투 × k_bottom.
   **k_bottom**(0~1)은 하부 배수 계수다 — 논토양의 경반층이나 높은 지하수위가 아래로
   빠지는 물을 막으면 0 에 가깝고, 그러면 3층이 차서 2층도 못 빠진다. 김제 A 토양_3
   은 08 월 내내 44 % 에 머물다 09-04 부터 나흘 만에 57 → 28 % 로 빠졌다 — 뿌리 흡수로
   는 하루 2 %p 도 안 된다. 하부가 막혔다가 열린 모양(이웃 논 물떼기 등)일 수 있어 자리를
   두었지만, 이 자료에서는 추정해도 1 일 선행 오차가 줄지 않아 기본은 1(자유 배수) 고정.
3. **증발**(FAO-56 이중 작물계수): 표토 = 1층(Ze = 1층 두께). 고갈 De = (θfc − θ1)·Ze,
   TEW = (θfc − 0.5 θwp)·Ze, REW 는 토성값. Kr 은 De 가 REW 를 넘으면 줄고,
   Ke = min(Kr·(Kc_max − Kcb), few·Kc_max). 1층은 기건(0.5 θwp)까지 마른다.
4. **증산**: T = Ks·Kcb·kcb_scale·ET0. Ks 는 뿌리층 고갈 Dr·TAW·RAW(p 는 ETc 로 보정,
   FAO-56 식 84) 에서. 뿌리 깊이 Zr 은 Kcb 가 자라는 만큼 Zr_min → Zr_max(층 바닥으로
   자름). 각 층의 뿌리 몫 × 쓸 수 있는 물에 비례해 뽑는다.
5. **지온·적산온도**: Ts1 은 일평균 기온을 1 일 시정수로 따라간다(P1 은 물이 먼저 —
   열전도 1차원은 다음 판). gdd += max(T − T_base, 0)·일.

관수 `u['irr_mm']` 가 NaN(모름)이면 0 으로 넣고, 계약 §10.7 대로 그 사실은 메타
(`irrigation_known=0`)에 남는다 — 모델은 확률을 모르고, 모르는 입력은 빼기만 한다.

## 아직 없는 것 (기록)

- 모세관 상승·지하수: 김제 A 센서의 긴 평탄 구간(08 월 44 %, 09 월 20 %)은 뿌리 흡수
  만으로 설명되지 않는다. 지하수위나 이웃 논의 영향일 수 있다 — 자료가 생기면 하부
  경계를 넣는다.
- 층마다 다른 토성. 지금은 한 토성.
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from .params import (CROPS, DEFAULT_LAYER_EDGES_M, CropParams, FieldPrior,
                     SensorSpec, TEXTURES)

MODEL_REV = 1

STATE_NAMES: Tuple[str, ...] = ('theta1', 'theta2', 'theta3', 'Ts1', 'gdd')
PARAM_NAMES: Tuple[str, ...] = ('theta_wp', 'theta_fc', 'theta_sat', 'tau_drain_d', 'kcb_scale',
                                'k_bottom')

# 파라미터 물리 범위 — EnKF 갱신 뒤 자를 때도 쓴다.
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    'theta_wp': (0.02, 0.30),
    'theta_fc': (0.06, 0.45),
    'theta_sat': (0.30, 0.60),
    'tau_drain_d': (0.05, 30.0),
    'kcb_scale': (0.0, 2.0),
    'k_bottom': (0.0, 1.0),
}

_MIN_GAP = 0.02          # θwp + gap ≤ θfc ≤ θsat − gap
_SUBSTEP_S = 10800.0     # 부분 스텝 상한 3 h
_TS_TAU_D = 1.0          # 지온 시정수 [일]


def _amount(v):
    """비·관수량 [mm]: None·NaN(모름)은 0, 음수는 0. 배열이면 원소마다."""
    if v is None:
        return 0.0
    a = np.nan_to_num(np.asarray(v, dtype=float), nan=0.0)
    a = np.maximum(a, 0.0)
    return float(a) if a.ndim == 0 else a


class FieldBucketModel:
    """노지 구획 하나(또는 격자 칸 하나)의 층 버킷 물 수지.

    crop: CropParams 또는 `CROPS` 의 이름. edges_m: 층 경계. rew_mm: 쉽게 증발하는
    물 — None 이면 사전분포 토성에서 읽는다(`init_state` 가 정한다).
    """

    kind = 'field'
    state_names = STATE_NAMES
    param_names = PARAM_NAMES
    dt_nominal_s = 86400.0

    def __init__(self, crop='perilla', edges_m: Sequence[float] = DEFAULT_LAYER_EDGES_M,
                 rew_mm: Optional[float] = None):
        self.crop: CropParams = CROPS[crop] if isinstance(crop, str) else crop
        self.edges_m = tuple(float(e) for e in edges_m)
        self.dz_m = np.diff(np.asarray(self.edges_m))
        if len(self.dz_m) != 3 or np.any(self.dz_m <= 0):
            raise ValueError('층은 3개, 경계는 증가해야 한다: %r' % (edges_m,))
        self.rew_mm = rew_mm
        self.names = self.state_names + self.param_names
        self.idx = {n: i for i, n in enumerate(self.names)}
        self.n = len(self.names)

    # ── 상태 꺼내기 ──────────────────────────────────────────────────────────
    def _get(self, x, name):
        return x[..., self.idx[name]]

    def soil(self, x):
        """(θwp, θfc, θsat) — 순서가 깨진 앙상블 멤버도 물리적으로 맞게 자른다."""
        wp = np.clip(self._get(x, 'theta_wp'), *PARAM_BOUNDS['theta_wp'])
        sat = np.clip(self._get(x, 'theta_sat'), *PARAM_BOUNDS['theta_sat'])
        fc = np.clip(self._get(x, 'theta_fc'), wp + _MIN_GAP, sat - _MIN_GAP)
        return wp, fc, sat

    def clip(self, x):
        """파라미터 범위·순서와 θ 의 물리 범위(기건 ~ 포화)를 강제한 사본."""
        x = np.array(x, dtype=float, copy=True)
        for n, (lo, hi) in PARAM_BOUNDS.items():
            x[..., self.idx[n]] = np.clip(x[..., self.idx[n]], lo, hi)
        wp, fc, sat = self.soil(x)
        x[..., self.idx['theta_wp']] = wp
        x[..., self.idx['theta_fc']] = fc
        x[..., self.idx['theta_sat']] = sat
        for k in range(3):
            j = self.idx['theta%d' % (k + 1)]
            x[..., j] = np.clip(x[..., j], 0.5 * wp, sat)
        return x

    # ── 계약 인터페이스 ──────────────────────────────────────────────────────
    def init_state(self, target=None, t0=None, prior: Optional[FieldPrior] = None,
                   n: Optional[int] = None, rng=None):
        """사전분포 평균(n=None) 또는 앙상블 n 개를 만든다.

        θfc·θwp·θsat 는 정규, 배수 시정수·kcb_scale 은 로그 정규(양수 보장)로 뽑는다.
        """
        prior = prior or FieldPrior()
        tex = prior.texture_class()
        if self.rew_mm is None:
            self.rew_mm = tex.rew_mm
        theta0 = np.asarray(prior.theta0 if prior.theta0 is not None
                            else [tex.theta_fc] * 3, dtype=float)
        mean = np.zeros(self.n)
        mean[[self.idx['theta1'], self.idx['theta2'], self.idx['theta3']]] = theta0
        mean[self.idx['Ts1']] = 20.0
        mean[self.idx['gdd']] = 0.0
        mean[self.idx['theta_wp']] = tex.theta_wp
        mean[self.idx['theta_fc']] = tex.theta_fc
        mean[self.idx['theta_sat']] = tex.theta_sat
        mean[self.idx['tau_drain_d']] = tex.tau_drain_d
        mean[self.idx['kcb_scale']] = prior.kcb_scale
        mean[self.idx['k_bottom']] = prior.k_bottom
        if n is None:
            return self.clip(mean)
        rng = rng if rng is not None else np.random.default_rng()
        X = np.tile(mean, (n, 1))
        for k in range(3):
            X[:, self.idx['theta%d' % (k + 1)]] += rng.normal(0, prior.theta0_sd, n)
        X[:, self.idx['theta_wp']] += rng.normal(0, prior.theta_wp_sd, n)
        X[:, self.idx['theta_fc']] += rng.normal(0, prior.theta_fc_sd, n)
        X[:, self.idx['theta_sat']] += rng.normal(0, prior.theta_sat_sd, n)
        X[:, self.idx['tau_drain_d']] *= np.exp(rng.normal(0, prior.tau_log_sd, n))
        X[:, self.idx['kcb_scale']] *= np.exp(rng.normal(0, prior.kcb_scale_sd, n))
        X[:, self.idx['k_bottom']] += rng.normal(0, prior.k_bottom_sd, n)
        return self.clip(X)

    def step(self, x, u: Optional[Mapping] = None, w: Optional[Mapping] = None,
             dt_s: float = 86400.0):
        """한 스텝 적분한 새 상태. 결정론. 흐름 내역이 필요하면 `step_fluxes`."""
        return self.step_fluxes(x, u, w, dt_s)[0]

    def observe(self, x, sensor: SensorSpec):
        """관측식 y = a·100·θ_layer + b [센서 %]. a·b 는 스칼라 또는 앙상블 배열."""
        theta = self._get(x, 'theta%d' % (sensor.layer + 1))
        return np.asarray(sensor.a) * 100.0 * theta + np.asarray(sensor.b)

    def derived(self, x, dap: float = 0.0) -> Dict[str, np.ndarray]:
        """뿌리층 평균 θ_root[%], 고갈 Dr[mm], TAW·RAW[mm], Ks, 과습 여부 기준값."""
        wp, fc, sat = self.soil(x)
        kcb = self.crop.kcb(dap)
        zr = self._root_depth(kcb)
        ov = self._overlap(zr)
        th = np.stack([self._get(x, 'theta%d' % (k + 1)) for k in range(3)], axis=-1)
        root_m = ov.sum()
        theta_root = (th * ov).sum(axis=-1) / root_m
        taw = ((fc - wp)[..., None] * ov).sum(axis=-1) * 1000.0
        dr = (np.maximum(fc[..., None] - th, 0.0) * ov).sum(axis=-1) * 1000.0
        dr = np.minimum(dr, taw)
        p = self.crop.p_tab
        raw = p * taw
        ks = np.clip((taw - dr) / np.maximum((1.0 - p) * taw, 1e-9), 0.0, 1.0)
        wet_thr = fc + 0.5 * (sat - fc)
        return {'theta_root_pct': 100.0 * theta_root, 'Dr_mm': dr, 'TAW_mm': taw,
                'RAW_mm': raw, 'Ks': ks, 'overwet': theta_root >= wet_thr}

    def risks(self, traj, dap0: float = 0.0, dt_d: float = 1.0) -> Dict[str, np.ndarray]:
        """앙상블 궤적 (N, K, n) 에서 일별 사건 확률 (계약 §10.6 · §10.4 채널 70·71·74)."""
        traj = np.asarray(traj)
        K = traj.shape[1]
        p1, p07, pwet = np.zeros(K), np.zeros(K), np.zeros(K)
        for k in range(K):
            d = self.derived(traj[:, k, :], dap=dap0 + k * dt_d)
            p1[k] = np.mean(d['Ks'] < 1.0)
            p07[k] = np.mean(d['Ks'] < 0.7)
            pwet[k] = np.mean(d['overwet'])
        return {'p_water_short': p1, 'p_water_short_severe': p07, 'p_overwet': pwet}

    # ── 물리 ─────────────────────────────────────────────────────────────────
    def _root_depth(self, kcb: float) -> float:
        c = self.crop
        span = max(c.kcb_mid - c.kcb_ini, 1e-9)
        frac = min(max((kcb - c.kcb_ini) / span, 0.0), 1.0)
        zr = c.zr_min_m + (c.zr_max_m - c.zr_min_m) * frac
        return min(max(zr, self.dz_m[0]), self.edges_m[-1])

    def _overlap(self, zr: float) -> np.ndarray:
        """층마다 [0, Zr] 와 겹치는 두께 [m]."""
        top = np.asarray(self.edges_m[:-1])
        bot = np.asarray(self.edges_m[1:])
        return np.clip(np.minimum(bot, zr) - top, 0.0, None)

    def _cover(self, kcb: float) -> float:
        """피복률 fc — FAO-56 식 76. 초장은 Kcb 비율로 어림."""
        c = self.crop
        kc_max = max(1.20, kcb + 0.05)
        h = c.h_max_m * min(max((kcb - c.kcb_ini) / max(c.kcb_mid - c.kcb_ini, 1e-9), 0.0), 1.0)
        base = max(kcb - c.kc_min, 0.0) / max(kc_max - c.kc_min, 1e-9)
        return float(min(max(base ** (1.0 + 0.5 * h), 0.0), 0.99))

    def step_fluxes(self, x, u: Optional[Mapping] = None, w: Optional[Mapping] = None,
                    dt_s: float = 86400.0):
        """(새 상태, 흐름 내역 dict[mm]). 흐름: rain·irr·runoff·evap·transp·drain(심부)."""
        u = u or {}
        w = w or {}
        x = np.array(x, dtype=float, copy=True)
        if self.rew_mm is None:
            self.rew_mm = TEXTURES['loam'].rew_mm
        # 비·관수는 스칼라 또는 멤버별 배열(EnKF 가 비 입력 오차를 섞을 때)
        rain = _amount(w.get('rain_mm'))
        irr = _amount(u.get('irr_mm'))
        et0 = max(float(w.get('et0_mm', 0.0) or 0.0), 0.0)
        t_mean = w.get('t_mean')
        dap = float(w.get('dap', 0.0) or 0.0)

        wp, fc, sat = self.soil(x)
        tau = np.clip(self._get(x, 'tau_drain_d'), *PARAM_BOUNDS['tau_drain_d'])
        k_bot = np.clip(self._get(x, 'k_bottom'), *PARAM_BOUNDS['k_bottom'])
        kscale = np.clip(self._get(x, 'kcb_scale'), *PARAM_BOUNDS['kcb_scale'])
        dz_mm = self.dz_m * 1000.0
        S = np.stack([self._get(x, 'theta%d' % (k + 1)) for k in range(3)], axis=-1) * dz_mm
        S_sat = sat[..., None] * dz_mm
        S_fc = fc[..., None] * dz_mm
        S_wp = wp[..., None] * dz_mm
        S_dry1 = 0.5 * wp * dz_mm[0]

        c = self.crop
        kcb0 = c.kcb(dap)
        kcb = kcb0 * kscale
        kc_max = max(1.20, kcb0 + 0.05)
        few = max(1.0 - self._cover(kcb0), 0.01)
        zr = self._root_depth(kcb0)
        ov = self._overlap(zr)
        ov_frac = ov / self.dz_m
        ze_mm = dz_mm[0]
        rew = float(self.rew_mm)
        tew = np.maximum((fc - 0.5 * wp) * ze_mm, rew + 1e-6)
        etc_day = (kcb + 0.3) * et0
        p = np.clip(c.p_tab + 0.04 * (5.0 - etc_day), 0.1, 0.8)

        n_sub = max(1, int(math.ceil(dt_s / _SUBSTEP_S)))
        h_d = dt_s / 86400.0 / n_sub
        tot = {k: np.zeros(S.shape[:-1]) for k in
               ('rain', 'irr', 'runoff', 'evap', 'transp', 'drain')}
        for _ in range(n_sub):
            # 1) 들어옴과 넘침
            inflow = (rain + irr) / n_sub
            tot['rain'] = tot['rain'] + rain / n_sub
            tot['irr'] = tot['irr'] + irr / n_sub
            S[..., 0] = S[..., 0] + inflow
            for k in range(2):
                over = np.maximum(S[..., k] - S_sat[..., k], 0.0)
                S[..., k] -= over
                S[..., k + 1] += over
            over = np.maximum(S[..., 2] - S_sat[..., 2], 0.0)
            if np.any(over > 0):
                # 맨 아래까지 찼다 — 위로 되밀어 채우고 남는 것은 지표 유출
                S[..., 2] -= over
                for k in (1, 0):
                    room = np.maximum(S_sat[..., k] - S[..., k], 0.0)
                    put = np.minimum(over, room)
                    S[..., k] += put
                    over = over - put
                tot['runoff'] = tot['runoff'] + over
            # 2) 배수 (선형 저수조, 위에서 아래로)
            for k in range(3):
                tau_k = tau * (self.dz_m[k] / 0.10)
                q = np.maximum(S[..., k] - S_fc[..., k], 0.0) * (1.0 - np.exp(-h_d / tau_k))
                if k < 2:
                    q = np.minimum(q, np.maximum(S_sat[..., k + 1] - S[..., k + 1], 0.0))
                    S[..., k + 1] += q
                else:
                    q = q * k_bot
                    tot['drain'] = tot['drain'] + q
                S[..., k] -= q
            # 3) 표토 증발
            et0_h = et0 / n_sub
            de = np.clip(S_fc[..., 0] - S[..., 0], 0.0, None)
            kr = np.where(de <= rew, 1.0, np.clip((tew - de) / (tew - rew), 0.0, 1.0))
            ke = np.minimum(kr * np.maximum(kc_max - kcb, 0.0), few * kc_max)
            e = np.minimum(ke * et0_h, np.maximum(S[..., 0] - S_dry1, 0.0))
            S[..., 0] -= e
            tot['evap'] = tot['evap'] + e
            # 4) 증산
            if ov.sum() > 0 and et0_h > 0:
                taw = ((S_fc - S_wp) * ov_frac).sum(axis=-1)
                dr = (np.maximum(S_fc - S, 0.0) * ov_frac).sum(axis=-1)
                dr = np.minimum(dr, taw)
                ks = np.clip((taw - dr) / np.maximum((1.0 - p) * taw, 1e-9), 0.0, 1.0)
                t_dem = ks * kcb * et0_h
                avail = np.maximum(S - S_wp, 0.0) * ov_frac
                tot_av = avail.sum(axis=-1)
                share = np.where(tot_av[..., None] > 0,
                                 avail / np.maximum(tot_av[..., None], 1e-12), 0.0)
                take = np.minimum(t_dem[..., None] * share, avail)
                S -= take
                tot['transp'] = tot['transp'] + take.sum(axis=-1)

        for k in range(3):
            x[..., self.idx['theta%d' % (k + 1)]] = S[..., k] / dz_mm[k]
        dt_d = dt_s / 86400.0
        if t_mean is not None and not (isinstance(t_mean, float) and math.isnan(t_mean)):
            j = self.idx['Ts1']
            x[..., j] += (float(t_mean) - x[..., j]) * (1.0 - math.exp(-dt_d / _TS_TAU_D))
            x[..., self.idx['gdd']] += max(float(t_mean) - c.t_base_c, 0.0) * dt_d
        return x, tot

    def storage_mm(self, x):
        """프로필 전체 저수량 [mm] — 물 수지 검산용."""
        dz_mm = self.dz_m * 1000.0
        return sum(self._get(x, 'theta%d' % (k + 1)) * dz_mm[k] for k in range(3))
