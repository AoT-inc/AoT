# coding=utf-8
"""
field_twin/enkf.py — 노지 물 수지 동기화: 증강 상태 앙상블 칼만 필터(EnKF).

계약 §10.2: 노지는 상태가 많고 관측이 듬성듬성해 EnKF 로 동기화한다(시설은 UKF).
앙상블이 곧 분위수(p10/p50/p90)의 재료다. 모델은 확률을 모르고(`step` 결정론),
불확실성은 여기서 만든다:

- **상태·파라미터 증강**: X = [모델 상태 | 모델 파라미터 | 센서별 보정 a·b]. 관측이
  θ 를 고치면 공분산을 따라 θfc·배수 시정수·kcb_scale·보정까지 함께 움직인다 —
  "비 뒤 상승 폭"이 보정 a 와 포장용수량을, "건조 속도"가 배수 시정수를 정한다.
- **예측 오차**: 상태에 더하는 잡음(층 θ), 파라미터의 느린 무작위 걸음, 그리고 **비
  입력 오차**(멤버마다 로그 정규 배율). 관측소 한 점의 비는 구획의 비와 다르다(계획서
  §9.4.2 — 기상청과 예보가 10배 어긋난 날이 있다).
- **갱신**: 섭동 관측(stochastic) EnKF. 갱신 뒤 물리 범위로 자른다.
- **혁신 문턱**: |혁신| 이 문턱(기본 3σ)을 넘고 그날 비가 거의 없을 때, 하락이면 "센서
  이동/교란"으로 본다 — 보정 b 의 퍼짐을 사전분포로 되돌린 뒤 동화해 b 가 계단을 흡수
  하게 한다. 상승이면 "입력 누락"(관측소가 놓친 비·모르는 관수)이라 층 수분을 연다.
  김제 A 토양_3 은 09-28 11 시에 비 없이 21 → 12 % 로 떨어지고 같은 시각 토양온도
  일교차가 5 → 25 °C 로 커졌다(같은 구역 토양_1 은 그 시각 두절) — 밭 작업으로 센서가
  얕아졌거나 드러난 신호다. 이런 계단을 토양 물이 빠진 것으로 읽으면 θfc 가 망가진다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

from .model import FieldBucketModel
from .params import FieldPrior, SensorSpec

# 하루당 잡음 표준편차. 파라미터 중 양수 배율류는 로그 공간에서 걷는다.
DEFAULT_PROCESS_SD: Dict[str, float] = {
    'theta1': 0.010, 'theta2': 0.008, 'theta3': 0.005, 'Ts1': 0.3, 'gdd': 0.0,
    'theta_wp': 0.0005, 'theta_fc': 0.002, 'theta_sat': 0.001,
    'tau_drain_d': 0.03, 'kcb_scale': 0.03,     # 로그
    'k_bottom': 0.0,                            # 기본 고정(params.FieldPrior 주석)
    'cal_a': 0.002, 'cal_b': 0.02,              # a 는 로그, b 는 %p — 보정은 거의 고정
}
_LOG_WALK = ('tau_drain_d', 'kcb_scale', 'cal_a')
CAL_A_BOUNDS = (0.3, 4.0)
CAL_B_BOUNDS = (-60.0, 60.0)


@dataclass
class UpdateInfo:
    """한 번 갱신의 기록 (검증·메타 `obs_n` 용)."""
    sensor_id: str
    y: float
    prior_mean: float
    prior_sd: float
    innovation: float
    used: bool
    shift: bool = False
    wetting: bool = False


@dataclass
class FieldEnKF:
    """구획 하나의 앙상블. `forecast` → `update` 를 일 격자로 되풀이한다.

    rain_log_sd: 비 입력 배율 오차(로그 표준편차). 0 이면 비를 그대로 믿는다.
    shift_gate_sigma·shift_rain_mm: 혁신 문턱과 "비 없음" 기준.
    """
    model: FieldBucketModel
    sensors: Sequence[SensorSpec]
    n_members: int = 64
    prior: FieldPrior = field(default_factory=FieldPrior)
    seed: int = 0
    process_sd: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PROCESS_SD))
    rain_log_sd: float = 0.35
    shift_gate_sigma: float = 3.0
    shift_rain_mm: float = 2.0
    X: np.ndarray = field(init=False)
    log: List[UpdateInfo] = field(init=False, default_factory=list)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.names = list(self.model.names)
        self.cal_idx: Dict[str, tuple] = {}
        for s in self.sensors:
            if s.estimate_cal:
                self.cal_idx[s.sensor_id] = (len(self.names), len(self.names) + 1)
                self.names += ['cal_a:' + s.sensor_id, 'cal_b:' + s.sensor_id]
        N = self.n_members
        Xm = self.model.init_state(prior=self.prior, n=N, rng=self.rng)
        X = np.zeros((N, len(self.names)))
        X[:, :self.model.n] = Xm
        for s in self.sensors:
            if s.sensor_id in self.cal_idx:
                ia, ib = self.cal_idx[s.sensor_id]
                X[:, ia] = float(s.a) * np.exp(self.rng.normal(0, s.a_prior_sd, N))
                X[:, ib] = float(s.b) + self.rng.normal(0, s.b_prior_sd, N)
        self.X = X
        self._last_rain = 0.0

    # ── 보조 ────────────────────────────────────────────────────────────────
    def _clip(self, X):
        X[:, :self.model.n] = self.model.clip(X[:, :self.model.n])
        for ia, ib in self.cal_idx.values():
            X[:, ia] = np.clip(X[:, ia], *CAL_A_BOUNDS)
            X[:, ib] = np.clip(X[:, ib], *CAL_B_BOUNDS)
        return X

    def sensor_view(self, s: SensorSpec, X=None) -> SensorSpec:
        """앙상블 보정 a·b 를 실은 센서(멤버별 배열)."""
        X = self.X if X is None else X
        if s.sensor_id not in self.cal_idx:
            return s
        ia, ib = self.cal_idx[s.sensor_id]
        return s.with_cal(X[:, ia], X[:, ib])

    def predict_obs(self, s: SensorSpec, X=None) -> np.ndarray:
        X = self.X if X is None else X
        return self.model.observe(X[:, :self.model.n], self.sensor_view(s, X))

    def _noise(self, dt_d: float):
        N = self.n_members
        sq = math.sqrt(max(dt_d, 0.0))
        for j, name in enumerate(self.names):
            key = name.split(':')[0]
            sd = self.process_sd.get(key, 0.0) * sq
            if sd <= 0:
                continue
            if key in _LOG_WALK:
                self.X[:, j] *= np.exp(self.rng.normal(0, sd, N))
            else:
                self.X[:, j] += self.rng.normal(0, sd, N)

    # ── 예측·갱신 ───────────────────────────────────────────────────────────
    def forecast(self, u: Optional[Mapping] = None, w: Optional[Mapping] = None,
                 dt_s: float = 86400.0, noise: bool = True, rain_noise: Optional[bool] = None):
        """모든 멤버를 한 스텝 앞으로. 비는 멤버마다 배율 오차를 곱한다.

        noise: 상태·파라미터 잡음. rain_noise: 비 배율 오차(기본은 noise 를 따른다).
        """
        w = dict(w or {})
        rain = float(w.get('rain_mm') or 0.0)
        rain_noise = noise if rain_noise is None else rain_noise
        # 입력이 `rain_log_sd` 를 실어 오면 그 스텝만 그 값을 쓴다(예보 리드가 길수록 큰 오차)
        sd = w.pop('rain_log_sd', None)
        sd = self.rain_log_sd if sd is None else float(sd)
        if rain_noise and rain > 0 and sd > 0:
            w['rain_mm'] = rain * np.exp(self.rng.normal(-0.5 * sd ** 2, sd, self.n_members))
        self._last_rain = rain
        n = self.model.n
        self.X[:, :n] = self.model.step(self.X[:, :n], u, w, dt_s)
        if noise:
            self._noise(dt_s / 86400.0)
        self.X = self._clip(self.X)

    def update(self, obs: Mapping[str, float]) -> List[UpdateInfo]:
        """관측 {sensor_id: 값[%]} 을 한 센서씩 차례로 동화한다(관측 오차가 서로 독립)."""
        infos = []
        by_id = {s.sensor_id: s for s in self.sensors}
        for sid, y in obs.items():
            s = by_id.get(sid)
            if s is None or y is None or not np.isfinite(y):
                continue
            hx = self.predict_obs(s)
            mu, sd = float(hx.mean()), float(hx.std(ddof=1))
            r = s.r_sd ** 2
            innov = float(y) - mu
            shift = wetting = False
            gate = self.shift_gate_sigma * math.sqrt(sd ** 2 + r)
            if abs(innov) > gate and self._last_rain < self.shift_rain_mm:
                if innov < 0 and sid in self.cal_idx:
                    # 비 없이 설명 못 할 만큼 떨어졌다 — 센서 계단으로 보고 b 를 다시 연다
                    self.reopen_calibration(sid)
                    shift = True
                elif innov > 0:
                    # 비 없이 젖었다 — 관측소가 놓친 비·모르는 관수(입력 누락). 보정이
                    # 아니라 층 수분을 열어 관측이 물을 넣게 한다
                    self.inflate_water(s.layer)
                    wetting = True
                hx = self.predict_obs(s)
            self._assimilate(hx, float(y), r)
            infos.append(UpdateInfo(sid, float(y), mu, sd, innov, True, shift, wetting))
        self.log.extend(infos)
        return infos

    def reopen_calibration(self, sensor_id: str, b_only: bool = False):
        """센서가 옮겨졌거나 교란됐을 때: 보정 b(와 a)의 퍼짐을 사전분포로 되돌린다.

        설치 위치가 바뀐 신호(토양온도 일교차 급증 — `validity.placement_changes`)나
        비 없는 큰 하락 혁신에서 부른다. 평균은 그대로 두고 퍼짐만 연다.
        """
        if sensor_id not in self.cal_idx:
            return
        s = {x.sensor_id: x for x in self.sensors}[sensor_id]
        ia, ib = self.cal_idx[sensor_id]
        N = self.n_members
        self.X[:, ib] += self.rng.normal(0, s.b_prior_sd, N)
        if not b_only:
            self.X[:, ia] *= np.exp(self.rng.normal(0, 0.5 * s.a_prior_sd, N))
        self.X = self._clip(self.X)

    def inflate_water(self, layer: int, sd: float = 0.04):
        """관측 층과 그 위 층의 수분 퍼짐을 키운다(입력 누락 대응)."""
        N = self.n_members
        for k in range(layer + 1):
            j = self.model.idx['theta%d' % (k + 1)]
            self.X[:, j] += np.abs(self.rng.normal(0, sd, N))
        self.X = self._clip(self.X)

    def _assimilate(self, hx: np.ndarray, y: float, r: float):
        N = self.n_members
        A = self.X - self.X.mean(axis=0)
        ha = hx - hx.mean()
        c_xy = A.T @ ha / (N - 1)
        c_yy = float(ha @ ha) / (N - 1)
        k = c_xy / (c_yy + r)
        y_pert = y + self.rng.normal(0, math.sqrt(r), N)
        self.X = self.X + np.outer(y_pert - hx, k)
        self.X = self._clip(self.X)

    # ── 읽기 ────────────────────────────────────────────────────────────────
    def mean(self) -> Dict[str, float]:
        return dict(zip(self.names, self.X.mean(axis=0)))

    def quantiles(self, name: str, q=(0.1, 0.5, 0.9)) -> np.ndarray:
        return np.quantile(self.X[:, self.names.index(name)], q)

    def obs_quantiles(self, sensor_id: str, q=(0.1, 0.5, 0.9)) -> np.ndarray:
        s = {x.sensor_id: x for x in self.sensors}[sensor_id]
        return np.quantile(self.predict_obs(s), q)

    def run_ahead(self, inputs: Sequence[Mapping], dt_s: float = 86400.0) -> np.ndarray:
        """현재 앙상블을 바꾸지 않고 앞으로 굴린 모델 상태 궤적 (N, K, n). 잡음 없이,
        비 배율 오차만 섞는다(예측 분위수의 재료)."""
        saved_X, saved_rng = self.X.copy(), self.rng.bit_generator.state
        traj = []
        try:
            for w in inputs:
                self.forecast(w.get('u'), w, dt_s, noise=False, rain_noise=True)
                traj.append(self.X[:, :self.model.n].copy())
        finally:
            self.X = saved_X
            self.rng.bit_generator.state = saved_rng
        return np.stack(traj, axis=1)
