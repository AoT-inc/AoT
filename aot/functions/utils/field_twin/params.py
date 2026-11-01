# coding=utf-8
"""
field_twin/params.py — 노지 구획 물 수지 모델의 토성·작물·센서 파라미터.

계약 §10.2 의 ⑧(토양 수리 파라미터)·⑨(작물계수 배율)와 관측식 y = a·θ_k + b 의
보정 a·b 를 여기서 정한다. 값의 출처:

- 포장용수량 θfc·위조점 θwp·쉽게 증발하는 물 REW: FAO-56 표 19 범위의 가운데값.
- 포화 θsat: Rawls et al. (1982) 전공극률.
- 배수 시정수 tau_drain_d: **어림값**이다(포장용수량 위 물이 10 cm 층에서 빠지는 데
  걸리는 날). 비 뒤 건조 속도로 EnKF 가 고친다.
- 작물: FAO-56 표 17·12. 들깨는 표에 없어 같은 유지작물인 참깨 값을 빌린다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, Optional, Sequence, Tuple

# 층 경계 [m] — 계약 §10.2 기본값 0~10 · 10~30 · 30~60 cm.
DEFAULT_LAYER_EDGES_M: Tuple[float, ...] = (0.0, 0.10, 0.30, 0.60)


@dataclass(frozen=True)
class TextureClass:
    """토성 한 종류의 사전값. tau_drain_d 는 10 cm 층 기준."""
    name: str
    theta_fc: float
    theta_wp: float
    theta_sat: float
    rew_mm: float
    tau_drain_d: float


# FAO-56 표 19 (θfc·θwp·REW 가운데값) + Rawls 1982 (θsat). 이름은 USDA 토성.
TEXTURES: Dict[str, TextureClass] = {t.name: t for t in (
    TextureClass('sand',            0.120, 0.045, 0.437, 4.5, 0.3),
    TextureClass('loamy_sand',      0.150, 0.065, 0.437, 6.0, 0.5),
    TextureClass('sandy_loam',      0.230, 0.110, 0.453, 8.0, 1.0),
    TextureClass('loam',            0.250, 0.120, 0.463, 9.0, 2.0),
    TextureClass('silt_loam',       0.290, 0.150, 0.501, 9.5, 3.0),
    TextureClass('silt',            0.320, 0.170, 0.501, 9.5, 3.0),
    TextureClass('silty_clay_loam', 0.335, 0.205, 0.471, 9.5, 5.0),
    TextureClass('silty_clay',      0.360, 0.230, 0.479, 10.0, 7.0),
    TextureClass('clay',            0.360, 0.220, 0.475, 10.0, 10.0),
)}

DEFAULT_TEXTURE = 'loam'


def nearest_texture(theta_fc: float, tau_drain_d: float,
                    theta_wp: Optional[float] = None) -> Tuple[str, float]:
    """추정한 (θfc, 배수 시정수[, θwp]) 에 가장 가까운 토성과 그 거리.

    θfc 는 0.05 단위, 시정수는 log 축 1 단위(약 2.7 배)로 정규화한다. θwp 는 마른 쪽
    자료가 있어야 식별되므로 넘겨줄 때만 쓴다.
    """
    best, best_d = DEFAULT_TEXTURE, float('inf')
    for t in TEXTURES.values():
        d = ((theta_fc - t.theta_fc) / 0.05) ** 2
        d += math.log(max(tau_drain_d, 1e-3) / t.tau_drain_d) ** 2
        if theta_wp is not None:
            d += ((theta_wp - t.theta_wp) / 0.05) ** 2
        if d < best_d:
            best, best_d = t.name, d
    return best, math.sqrt(best_d)


@dataclass(frozen=True)
class CropParams:
    """FAO-56 이중 작물계수의 기저 작물계수 곡선과 뿌리·고갈 계수.

    stage_days: (초기, 발달, 중기, 후기) 길이 [일]. 정식·파종일(`started_on`) 기준.
    """
    name: str = 'generic'
    kcb_ini: float = 0.15
    kcb_mid: float = 1.05
    kcb_end: float = 0.25
    stage_days: Tuple[float, float, float, float] = (20.0, 30.0, 40.0, 20.0)
    zr_min_m: float = 0.15
    zr_max_m: float = 1.0
    p_tab: float = 0.6          # 표 22 고갈 허용률(ETc 5 mm/d 기준)
    h_max_m: float = 1.0        # 최대 초장 — 피복률 식 지수
    t_base_c: float = 10.0      # 적산온도 기준
    kc_min: float = 0.15        # 맨땅 최소 Kc (피복률 식)

    def kcb(self, dap: float) -> float:
        """정식 후 일수 dap 의 Kcb (FAO-56 그림 34 의 꺾은선)."""
        l1, l2, l3, l4 = self.stage_days
        if dap <= l1:
            return self.kcb_ini
        if dap <= l1 + l2:
            return self.kcb_ini + (self.kcb_mid - self.kcb_ini) * (dap - l1) / l2
        if dap <= l1 + l2 + l3:
            return self.kcb_mid
        if dap <= l1 + l2 + l3 + l4:
            return self.kcb_mid + (self.kcb_end - self.kcb_mid) * (dap - l1 - l2 - l3) / l4
        return self.kcb_end


CROPS: Dict[str, CropParams] = {
    # 들깨: 표 17 에 없다. 참깨(sesame) Kcb 0.15/1.05/0.20·p 0.6 을 빌리고, 정식묘라
    # 초기를 짧게(15 일) 둔다. 수확 뒤 잔재가 남으므로 끝값은 0.25.
    'perilla': CropParams(name='perilla', kcb_ini=0.15, kcb_mid=1.05, kcb_end=0.25,
                          stage_days=(15.0, 30.0, 40.0, 20.0), zr_min_m=0.15,
                          zr_max_m=1.0, p_tab=0.6, h_max_m=1.2, t_base_c=10.0),
    # 작물이 없거나 모를 때: 맨땅에 가까운 낮은 Kcb.
    'bare': CropParams(name='bare', kcb_ini=0.10, kcb_mid=0.10, kcb_end=0.10,
                       zr_min_m=0.10, zr_max_m=0.10, h_max_m=0.05),
}


@dataclass(frozen=True)
class SensorSpec:
    """관측식 y = a·100·θ_layer + b [센서 %] 의 한 센서.

    a·b 는 스칼라 또는 앙상블 배열(EnKF 가 보정을 함께 추정할 때)이다.
    r_sd: 일평균 관측 오차 표준편차 [%p]. estimate_cal 이 참이면 EnKF 가 a·b 를
    상태에 붙여 함께 고친다.
    """
    sensor_id: str
    layer: int = 1
    a: object = 1.0
    b: object = 0.0
    r_sd: float = 1.5
    estimate_cal: bool = True
    a_prior_sd: float = 0.2     # a 는 로그 정규, 이것은 log 표준편차
    b_prior_sd: float = 4.0     # [%p]

    def with_cal(self, a, b) -> 'SensorSpec':
        return replace(self, a=a, b=b)

    @staticmethod
    def layer_for_depth(depth_cm: float,
                        edges_m: Sequence[float] = DEFAULT_LAYER_EDGES_M) -> int:
        """설치 깊이 [cm] 가 든 층 번호(0 부터). 맨 아래보다 깊으면 마지막 층."""
        d = depth_cm / 100.0
        for i in range(len(edges_m) - 1):
            if edges_m[i] <= d < edges_m[i + 1]:
                return i
        return len(edges_m) - 2


@dataclass
class FieldPrior:
    """EnKF 초기 앙상블의 사전분포. 평균은 토성에서, 퍼짐은 아래 값.

    theta0: 층별 초기 체적수분 [m³/m³]. None 이면 포장용수량에서 시작.
    """
    texture: str = DEFAULT_TEXTURE
    theta0: Optional[Sequence[float]] = None
    theta0_sd: float = 0.04
    theta_fc_sd: float = 0.05
    theta_wp_sd: float = 0.03
    theta_sat_sd: float = 0.03
    tau_log_sd: float = 0.8
    kcb_scale: float = 1.0
    kcb_scale_sd: float = 0.3
    # 하부 배수 계수(1 = 자유 배수, 0 = 막힘). 기본은 자유 배수로 두고 추정하지 않는다 —
    # 김제 A 재현에서 추정해도 오차가 줄지 않았다(계획서 §9.5). 경반층·지하수위 자료가
    # 생기면 k_bottom_sd 를 열고 EnKF 걸음(`process_sd['k_bottom']`)도 준다.
    k_bottom: float = 1.0
    k_bottom_sd: float = 0.0
    overrides: Dict[str, float] = field(default_factory=dict)

    def texture_class(self) -> TextureClass:
        t = TEXTURES.get(self.texture, TEXTURES[DEFAULT_TEXTURE])
        if self.overrides:
            t = replace(t, **{k: v for k, v in self.overrides.items()
                              if k in TextureClass.__dataclass_fields__})
        return t
