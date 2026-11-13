# coding=utf-8
"""
field_twin/sim/field_plant.py — 노지 구획의 **참값** 모델 (설계서 §8-4, E3).

시설의 `env_control/sim/plant.py` 와 같은 자리다. 트윈의 물 수지가 맞는지 재려면 트윈과 다른 방식으로 푼 땅이 필요하다.

## 독립성

`field_twin.model`·`params` 를 **import 하지 않는다.** 같은 가정을 공유하면 모델의 착각이 그대로 참이 된다. 구조가 일부러 다르다:

| | 버킷 모델(`FieldBucketModel`) | 이 참값 |
|---|---|---|
| 층 | 3층 | 12층 이상(위가 얇다) |
| 물 이동 | 포장용수량 위 물이 시정수로 빠짐 | 층 사이 Darcy 흐름 — 수두 차이 + 중력, Campbell 수리 함수 |
| 들어옴 | 전부 1층에 넣고 넘치면 유출 | 표면 흡수 능력(포화 수리전도도)을 넘는 비율은 유출 |
| 증발 | FAO-56 Ke·REW | 표층 건조도에 따른 저항 |
| 증산 | FAO-56 Ks·Kcb | 뿌리 분포 × 수분 스트레스(Feddes 형) |

"독립" 은 구조 독립이지 현실 독립이 아니다(설계서 §8-6) — 같은 저자가 썼다.

## 물 수지

매 부분 스텝마다 장부에 적는다. 저장 변화는 흐름의 합으로만 바뀐다:

    공급(비 + 관수) = Δ저장 + 증발 + 증산 + 배수 + 유출

`check_balance` 가 그 차이를 돌려준다. 수치 적분이지만 층 사이 흐름은 주는 만큼 받으므로 차이는 반올림 수준이다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

_DT_MAX_S = 600.0            # 부분 스텝 상한
_GRAVITY = 1.0               # 중력 기울기 — 수두와 깊이를 둘 다 mm 로 재므로 1


@dataclass(frozen=True)
class FieldSoil:
    """Campbell(1974) 수리 함수의 땅. 기본값은 양토 근방이지만 버킷 쪽 표에서 가져온 값이 아니다.

    psi_e_mm 공기 유입 수두, b 모양 계수, ks_mm_s 포화 수리전도도, theta_sat 포화 함수율.
    """
    theta_sat: float = 0.46
    psi_e_mm: float = 240.0
    b: float = 5.0
    ks_mm_s: float = 0.0020
    theta_dry: float = 0.02

    def psi_mm(self, theta: float) -> float:
        """토양 수두 [mm, 음수]."""
        s = min(max(theta / self.theta_sat, 1e-4), 1.0)
        return -self.psi_e_mm * s ** (-self.b)

    def k_mm_s(self, theta: float) -> float:
        """불포화 수리전도도 [mm/s]."""
        s = min(max(theta / self.theta_sat, 1e-4), 1.0)
        return self.ks_mm_s * s ** (2.0 * self.b + 3.0)


@dataclass(frozen=True)
class FieldCrop:
    """증산과 뿌리. `root_m` 뿌리 깊이, `kc` 증산 계수(기준증발산 대비)."""
    root_m: float = 0.45
    kc: float = 0.9
    psi_stress_mm: float = -30000.0    # 이 수두 아래로는 흡수가 준다
    psi_wilt_mm: float = -150000.0     # 흡수 멈춤


def _layers(depth_m: float, n: int) -> List[float]:
    """층 두께 [mm] — 아래로 갈수록 두껍다(등비)."""
    r = 1.15
    first = depth_m * 1000.0 * (r - 1.0) / (r ** n - 1.0)
    return [first * r ** i for i in range(n)]


class FieldPlant:
    """1차원 땅 기둥 하나. 시각은 일 단위로만 묻는다 — `step_day` 가 부분 스텝으로 쪼갠다."""

    def __init__(self, soil: FieldSoil = FieldSoil(), crop: FieldCrop = FieldCrop(), depth_m: float = 1.2,
                 n_layers: int = 16, theta0: float = 0.28):
        if n_layers < 10:
            raise ValueError('참값은 10층 이상이어야 한다(버킷과 구조가 달라야 한다)')
        self.soil, self.crop = soil, crop
        self.dz = _layers(depth_m, n_layers)
        self.theta = [float(theta0)] * n_layers
        z = 0.0
        self.mid: List[float] = []
        for d in self.dz:
            self.mid.append(z + 0.5 * d)
            z += d
        self.bottom_mm = z
        self.ledger: Dict[str, float] = {k: 0.0 for k in ('rain', 'irr', 'runoff', 'evap', 'transp', 'drain')}
        self.s0 = self.storage_mm()

    def storage_mm(self) -> float:
        return sum(t * d for t, d in zip(self.theta, self.dz))

    def theta_at(self, top_m: float, bottom_m: float) -> float:
        """깊이 구간 평균 함수율 — 센서·뿌리층이 보는 값."""
        a, b = top_m * 1000.0, bottom_m * 1000.0
        acc = span = 0.0
        z = 0.0
        for t, d in zip(self.theta, self.dz):
            lap = max(0.0, min(z + d, b) - max(z, a))
            acc += t * lap
            span += lap
            z += d
        return acc / span if span > 0 else float('nan')

    def check_balance(self) -> float:
        """공급 − (Δ저장 + 나간 물) [mm]. 닫혀 있으면 0 에 가깝다."""
        led = self.ledger
        supply = led['rain'] + led['irr']
        out = led['evap'] + led['transp'] + led['drain'] + led['runoff']
        return supply - (self.storage_mm() - self.s0) - out

    def _dt(self, flux: Sequence[float], top_in: float) -> float:
        """층 하나가 한 스텝에 공극의 일부만 잃거나 얻도록 줄인다(명시 적분 안정)."""
        dt = _DT_MAX_S
        for i, d in enumerate(self.dz):
            top = top_in if i == 0 else flux[i - 1]
            rate = abs(top - flux[i])
            if rate > 1e-12:
                dt = min(dt, 0.05 * d * self.soil.theta_sat / rate)
        return max(dt, 1.0)

    def _fluxes(self) -> List[float]:
        """층 경계 아래쪽 양수 흐름 [mm/s] — i 번째는 i → i+1, 맨 끝은 바닥 자유 배수."""
        s, th = self.soil, self.theta
        out = []
        for i in range(len(th) - 1):
            gap = self.mid[i + 1] - self.mid[i]
            k = math.sqrt(s.k_mm_s(th[i]) * s.k_mm_s(th[i + 1]))        # 기하 평균
            q = k * ((s.psi_mm(th[i]) - s.psi_mm(th[i + 1])) / gap + _GRAVITY)
            room = (s.theta_sat - th[i + 1]) * self.dz[i + 1] / 60.0     # 분 단위로 받을 수 있는 만큼
            have = max(th[i] - s.theta_dry, 0.0) * self.dz[i] / 60.0
            out.append(min(q, room, have) if q > 0 else max(q, -min(
                (s.theta_sat - th[i]) * self.dz[i] / 60.0, max(th[i + 1] - s.theta_dry, 0.0) * self.dz[i + 1] / 60.0)))
        out.append(s.k_mm_s(th[-1]) * _GRAVITY)
        return out

    def _roots(self) -> List[float]:
        """층마다 뿌리 몫(합 1) — 위가 많은 삼각 분포."""
        root_mm = self.crop.root_m * 1000.0
        w = [max(0.0, 1.0 - z / root_mm) * d for z, d in zip(self.mid, self.dz)]
        total = sum(w) or 1.0
        return [x / total for x in w]

    def _stress(self, theta: float) -> float:
        psi, c = self.soil.psi_mm(theta), self.crop
        if psi >= c.psi_stress_mm:
            return 1.0
        return max(0.0, (psi - c.psi_wilt_mm) / (c.psi_stress_mm - c.psi_wilt_mm))

    def step_day(self, rain_mm: float = 0.0, irr_mm: float = 0.0, et0_mm: float = 0.0, event_h: float = 2.0) -> None:
        """하루. 비·관수는 하루 앞쪽 `event_h` 시간에 내린다 — 강도가 표면 흡수 능력을 넘으면 그 몫은 유출이다."""
        event_s = event_h * 3600.0
        day_s, t = 86400.0, 0.0
        rate = (max(rain_mm, 0.0) + max(irr_mm, 0.0)) / event_s if event_s > 0 else 0.0
        share_rain = max(rain_mm, 0.0) / (max(rain_mm, 0.0) + max(irr_mm, 0.0) + 1e-12)
        et_rate = max(et0_mm, 0.0) / day_s
        roots = self._roots()
        while t < day_s - 1e-6:
            flux = self._fluxes()
            wet = rate if t < event_s else 0.0
            soak = min(wet, self.soil.ks_mm_s * 4.0,
                       max(self.soil.theta_sat - self.theta[0], 0.0) * self.dz[0] / 60.0)
            dt = self._dt(flux, soak)
            dt = min(dt, day_s - t)
            if t < event_s:
                dt = min(dt, event_s - t)
            self._apply(flux, soak, wet, share_rain, et_rate, roots, dt)
            t += dt

    def _apply(self, flux, soak, wet, share_rain, et_rate, roots, dt) -> None:
        led, th, dz = self.ledger, self.theta, self.dz
        led['rain'] += wet * share_rain * dt
        led['irr'] += wet * (1.0 - share_rain) * dt
        led['runoff'] += (wet - soak) * dt
        for i, d in enumerate(dz):
            top = soak if i == 0 else flux[i - 1]
            th[i] += (top - flux[i]) * dt / d
        led['drain'] += flux[-1] * dt
        # 표층 증발 — 표층이 마를수록 저항이 커진다
        s, top = self.soil, th[0]
        relative = max(top - s.theta_dry, 0.0) / (s.theta_sat - s.theta_dry)
        e = min(et_rate * (1.0 - min(self.crop.kc, 1.0) * 0.7) * relative ** 2 * dt,
                max(top - s.theta_dry, 0.0) * dz[0])
        th[0] -= e / dz[0]
        led['evap'] += e
        # 증산 — 뿌리 몫 × 스트레스
        for i, d in enumerate(dz):
            if roots[i] <= 0:
                continue
            want = et_rate * self.crop.kc * roots[i] * self._stress(th[i]) * dt
            take = min(want, max(th[i] - s.theta_dry, 0.0) * d)
            th[i] -= take / d
            led['transp'] += take

    def run(self, days: Sequence[Tuple[float, float, float]]) -> List[float]:
        """(비, 관수, ET0) 들 → 날마다 끝의 저장량 [mm]."""
        out = []
        for rain, irr, et0 in days:
            self.step_day(rain, irr, et0)
            out.append(self.storage_mm())
        return out
