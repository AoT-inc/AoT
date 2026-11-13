# coding=utf-8
"""
env_control/sim/plant.py — 폐루프 시뮬레이터의 시설 **참값** 모델.

통합환경제어(`env_coordinator`)를 닫힌 고리로 시험하려고 만든 "가짜 온실"이다.
현장 실내 센서가 다른 장치의 거울이라(명령에 반응하지 않는다) 목표 추종·헌팅·
안전 동작을 현장 기록으로 판단할 수 없어서, 명령에 **반응하는** 시설을 따로 둔다.

## 독립성 (가장 중요한 규칙)

이 모델은 제어기가 믿는 효과 모델과 **따로** 서야 한다. 같은 가정을 공유하면 제어기의
착각이 시뮬레이터에서 그대로 "참" 이 되어 아무것도 검증하지 못한다.

- `effect_functions.py`·greybox 학습 파라미터를 **import 하지 않는다.**
- 순수 물성(포화 수증기압·습구온도·분무 증발)만 `psychro` 에서 빌린다 — 물리 법칙은
  하나여야 하므로. 하네스 컨테이너에서는 같은 판을 `_psychro.py` 로 옆에 복사해 쓴다
  (시험 대상 코드 판이 바뀌어도 시설은 같아야 A/B 비교가 성립한다).
- 시설 치수는 DB 의 시설 정의(`geo_facility.geometry_3d`·`fittings`)에서 **직접**
  계산한다. 제어기의 `capacity_meta` 를 쓰지 않는다(그것도 제어기 쪽 추정이다).

## 상태와 수지

    상태 [T 실내 공기 °C, w 습도비 kg/kg_da, C CO₂ ppm, Tm 바닥·작물 열질량 °C,
          pool 잎·바닥 젖은 물 kg]

    공기   C_a dT/dt  = 일사(공기분) + h_m A (Tm−T) + UA (Te−T) + ρc_p G (Te−T)
                        + 난방 − 냉방(현열) − 분무 증발 흡열 + 결로 잠열(절반) + 보광
    질량   C_m dTm/dt = 일사(작물·바닥분) − h_m A (Tm−T) − L (증산 + 젖은면 증발)
                        − 지중 손실 − 하늘 복사 − 못 날린 물 데우기
    수분   M dw/dt    = 증산 + 젖은면 증발 + 분무 증발 − 피복 결로 − 냉방 제습 + ρG (we−w)
    CO₂    V dC/dt    = G (Ce−C) + 주입 − 광합성 + 호흡
    pool   d/dt       = 못 날린 분무(작물에 떨어진 몫) + 결로 낙수 − 젖은면 증발

G 는 환기량 [m³/s] = 누기 + 균형 팬 + √(자연환기² + 불균형 팬²) (ASHRAE 중첩).

## 장치 (types.ACTUATOR_KINDS 의 kind 별)

- opening      개구 면적 × 개도 → 풍력 + 굴뚝 효과 환기. 비 오는데 열려 있으면 기록.
- intake/exhaust_fan  정격 m³/h × 가동률. 흡·배기 불균형분은 보충 개구(창+누기)가
                 좁으면 정압이 올라 풍량이 준다(팬 곡선). 창이 열려 있으면 일부가
                 가까운 창으로 단락돼 실내 전체를 못 쓸고 지나간다.
- fogger       `psychro.evaporate` — 노즐 효율 η × 분무량 과, 실제로 분무를 지나는
                 공기(환기·팬 처리량 + 노즐 동반류 + 유동팬)의 포화 여유 중 작은 쪽.
                 못 날린 물은 작물 젖음(pool)으로 쌓인다. 물 공급이 끊기면 0.
- heater/cooler 정격 kW × 가동률(냉방은 이슬점이 코일보다 높을 때 제습분).
- shade        일사 투과율 감소 → 열 유입과 증산 구동력 둘 다 준다.
- curtain      UA 절감 + 일사 투과율 감소 + 하늘 복사 차단. 부분 전개는 선형.
- co2_injector kg/h × 가동률.
- circulation_fan  ① 분무 처리 공기를 늘린다. ② (2026-10-12) **잎 둘레 공기 움직임**: 정격 풍량이 바닥 1 m² 당
                 `circ_ref_m3h_m2` 이상이면 1(그 아래는 비례). 경계층이 얇아져 (a) **공기보다 찬** 질량(잎)과 공기의
                 대류 `h_mass` 가 `1 + circ_coupling` 배까지 — 잎이 복사로 공기보다 식는 폭이 준다(이슬 덜 맺힘),
                 (b) **젖은 면의 증발**(`leaf_g`)이 `1 + circ_leaf_g` 배까지 — 마르는 데 걸리는 시간이 준다.
                 이슬 **맺힘**(음의 `dws`)의 전도도는 키우지 않는다(보수적으로: 바람이 결로를 더 맺히게 하는
                 효과는 크게 안 본다). 질량이 공기보다 **따뜻할 때**(지중열을 받는 바닥·트레이가 섞인 덩어리)는
                 결합을 키우지 않는다 — 이 모델의 Tm 은 잎 하나가 아니라 바닥·트레이를 합친 덩어리라, 따뜻한 바닥을
                 팬이 식혀 잎을 이슬점에 더 가깝게 만드는 것은 덩어리 모델의 인공물이지 팬의 효과가 아니다
                 (첫 판이 recorded 에서 그렇게 잎 젖음을 늘렸다). 팬이 없으면 배수가 1 이라 종전과 비트 단위로 같다.

## 명령 해석

`set_command(output_type, amount)` 는 데몬이 받는 형태 그대로 받는다:
'value'/'pwm' = 목표 개도·가동률 %, 'sec' = 지금부터 amount 초 켜짐, 'vol' = mL(분무),
'off' = 끔. 모터 장치(travel_*_s > 0)는 주행 시간만큼 천천히 따라간다.
고장(`dead`/`stuck`)은 명령을 받아 **드라이버의 믿음(believed)** 은 바꾸되 물리는
움직이지 않는다 — 현장 고장이 그렇게 보이기 때문이다.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# 하네스 복사본을 먼저 본다 — 컨테이너의 PYTHONPATH 에는 시험 대상 코드(-c)가 올라와 있어서,
# aot.utils 를 먼저 찾으면 시험 대상 판의 물성을 쓰게 되고 A/B 의 시설이 달라진다.
try:                                  # 하네스 컨테이너: 같은 판을 옆에 복사해 둔다
    from . import _psychro as ps      # type: ignore
except ImportError:                   # 저장소 안: aot.utils.psychro
    from aot.utils import psychro as ps

P_KPA = ps.P_STD_KPA
CP_DA = 1006.0            # J/(kg·K)
CP_V = 1860.0             # J/(kg·K)
CP_W = 4186.0             # J/(kg·K)
L0 = 2.501e6              # J/kg 0 °C 증발잠열
G_ACC = 9.81
CO2_KG_M3 = 1.83          # kg/m³ (20 °C)


def latent(T: float) -> float:
    """증발잠열 [J/kg] — T °C 에서."""
    return L0 - 2370.0 * T


# ─────────────────────────────────────────────────────────────────────────────
# 파라미터
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlantParams:
    """시설 참값 파라미터. 기본값은 단동 비닐 육묘장(김제 육묘장3 규모) 기준이다.

    DB 에 없는 값은 문헌상 그럴듯한 값을 고르고 근거를 옆에 적는다. 제어기의
    `capacity_meta`·효과 모델 상수와 **일부러 맞추지 않는다.**
    """
    name: str = 'generic'
    # ── 치수 ──
    floor_m2: float = 340.0
    volume_m3: float = 1130.0
    cover_m2: float = 650.0            # 피복(지붕+측벽+박공) 면적
    span_m: float = 7.0
    length_m: float = 48.5
    mean_height_m: float = 3.3
    latitude: float = 35.86
    longitude: float = 126.88
    # ── 피복 ──
    U_cover: float = 6.5               # W/m²K 단일 PE(복사 포함, 무풍). 풍속 1 m/s 당 +4 %
    tau_cover: float = 0.77            # 일사 투과(필름 0.85 × 골조 그늘 0.9)
    solar_air_frac: float = 0.30       # 투과 일사 중 골조·피복 대류로 공기에 바로 가는 몫
    solar_mass_frac: float = 0.45      # 작물·바닥·벤치가 흡수하는 몫(나머지는 반사·장파 손실)
    # ── 열용량·결합 ──
    air_cap_mult: float = 2.0          # 공기 열용량 배수(얇은 골조·벤치 포함)
    mass_cap_J_m2K: float = 8.0e4      # 바닥 표층 5 cm + 트레이·작물 [J/(m²K)]
    h_mass: float = 8.0                # 질량–공기 대류 W/m²K
    h_ground: float = 1.0              # 질량–지중 W/m²K
    T_ground: float = 18.0             # 지중 온도(시나리오가 덮어쓸 수 있다)
    h_sky_mass: float = 2.0            # 작물 → 하늘 순장파(PE 필름 장파 일부 투과) W/m²K
    # ── 피복 결로 ──
    h_cover_in: float = 6.0            # 실내측 표면 열전달 W/m²K
    h_cover_out: float = 8.0           # 실외측(무풍) W/m²K, 풍속 1 m/s 당 +3
    h_cover_sky: float = 4.0           # 피복 → 하늘(맑음) W/m²K
    sky_depression_K: float = 18.0     # 맑은 하늘 유효 온도 = 외기 − 이 값
    cover_solar_abs: float = 0.08      # 피복이 직접 흡수하는 일사 비율(낮 피복 온도)
    # ── 환기 ──
    opening_cd: float = 0.6            # 유량계수
    opening_cw: float = 0.09           # 풍압계수(측창, Boulard)
    opening_net_factor: float = 0.7    # 방충망 등 유효 면적 비율
    opening_area_scale: float = 1.0    # 시나리오용(작은 개구 능력 재현)
    opening_stack_h: float = 1.2       # 개구 높이(굴뚝 효과) m
    leak_ach: float = 0.5              # 누기 1/h (무풍)
    leak_ach_wind: float = 0.15        # 풍속 1 m/s 당 누기 증가 1/h
    leak_area_m2: float = 1.3          # 누기 등가 면적(불균형 팬 보충) m²
    # ── 팬 ──
    fan_dp_max: float = 50.0           # 팬 차단 정압 Pa(박스팬 40~60)
    fan_short_circuit: float = 0.4     # 창 만개 시 팬 풍량 중 실내를 못 쓸고 단락되는 몫
    fan_kw_per_m3h: float = 3.3e-5     # 30,000 m³/h ≈ 1 kW
    # ── 작물(육묘 트레이) ──
    crop_cover: float = 0.8            # 바닥 대비 작물(트레이) 피복률
    transp_k_rad: float = 0.45         # 흡수 일사 중 증산 잠열로 가는 최대 비율
    transp_k_vpd: float = 1.2e-5       # VPD 구동 증산 kg/(m²·s·kPa)
    leaf_g: float = 0.008              # 젖은면 물질전달 전도도 m/s
    leaf_water_cap: float = 0.12       # 잎·트레이가 붙잡는 물 kg/m²(넘치면 배수)
    # 순환팬의 잎 둘레 공기 움직임(2026-10-12). 문헌: 잎 경계층 전도도는 풍속의 제곱근에 비례하고,
    # 정체 공기(0.1 m/s 미만)에서 0.5 m/s 로 가면 대류 전달이 ~2 배 — 여기서는 보수적으로 1.5 배·1.6 배만.
    circ_ref_m3h_m2: float = 30.0      # 이 풍량(m³/h 당 바닥 m²) 이상이면 효과 최대 — 수평 공기흐름 팬 설계 풍량대
    circ_coupling: float = 0.5         # 최대 효과일 때 h_mass 증가 비율
    circ_leaf_g: float = 0.6           # 최대 효과일 때 젖은 면 증발 전도도 증가 비율
    photo_max: float = 2.5e-3 / 3600   # 광합성 최대 CO₂ 흡수 kg/(m²·s)
    resp: float = 0.3e-3 / 3600        # 호흡 CO₂ 방출 kg/(m²·s)
    # ── 분무 ──
    fog_eps: float = 0.7               # 분무 통과 공기의 포화효율
    fog_recirc_per_nozzle: float = 0.15  # 노즐 하나가 끌어들이는 동반 공기 m³/s
    fog_water_T: float = 16.0          # 지하수 °C
    fog_land_on_crop: float = 0.85     # 못 날린 물 중 작물·트레이에 떨어지는 몫
    fog_pump_kw: float = 0.75
    water_available: bool = True
    # ── 냉난방 ──
    heater_eff: float = 0.9
    cooler_cop: float = 3.0
    cooler_latent_frac: float = 0.25   # 이슬점 > 코일일 때 냉방 능력 중 제습분
    cooler_coil_T: float = 10.0
    # ── 스크린 ──
    shade_tau: float = 0.45            # 차광막 닫힘 시 일사 투과
    curtain_tau: float = 0.55          # 보온커튼 닫힘 시 일사 투과
    curtain_ua_saving: float = 0.45    # 보온커튼 닫힘 시 UA 절감

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActuatorSpec:
    """장치 한 대의 물리 사양. kind 는 `types.ACTUATOR_KINDS` 와 같은 어휘다."""
    actuator_id: str
    kind: str
    name: str = ''
    area_m2: float = 0.0           # opening: 개구 면적(만개)
    azimuth_deg: Optional[float] = None
    rated_m3h: float = 0.0         # fan
    flow_kg_s: float = 0.0         # fogger: 노즐 총 유량
    nozzles: int = 0
    eta: float = 0.9               # fogger: 노즐이 증발 가능하게 쪼개는 비율
    wetting: bool = False          # fogger: 습윤형(미니스프링클러)
    rated_kw: float = 0.0          # heater/cooler/lighting
    co2_kg_h: float = 0.0
    travel_open_s: float = 0.0     # 0 이면 즉시
    travel_close_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _ActState:
    pos: float = 0.0               # 물리 개도·가동률 %
    target: float = 0.0
    believed: float = 0.0          # 드라이버가 믿는 위치(DB last_position_pct 로 간다)
    pulse: bool = False
    on_until: float = 0.0
    dead: bool = False
    stuck: Optional[float] = None
    n_cmd: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# 기상
# ─────────────────────────────────────────────────────────────────────────────
# weather(t) 는 dict 를 돌려준다:
#   T [°C], RH [%], solar [W/m² 수평 전천], wind [m/s], wind_dir [deg],
#   rain [mm/h], co2 [ppm], cloud [0..1]
WeatherFn = Callable[[float], Dict[str, float]]


# ─────────────────────────────────────────────────────────────────────────────
# 시설
# ─────────────────────────────────────────────────────────────────────────────

class Plant:
    """단일 구역 시설. `advance(t_end, weather)` 로 적분한다."""

    TRACE_EVERY = 60.0

    def __init__(self, params: PlantParams, actuators: List[ActuatorSpec],
                 t0: float, T: float = 20.0, RH: float = 70.0, CO2: float = 420.0,
                 Tm: Optional[float] = None):
        self.p = params
        self.specs: Dict[str, ActuatorSpec] = {a.actuator_id: a for a in actuators}
        self.st: Dict[str, _ActState] = {a.actuator_id: _ActState() for a in actuators}
        self.t = float(t0)
        e = ps.vapor_pressure(T, RH)
        self.x = [float(T), ps.humidity_ratio(e, P_KPA), float(CO2),
                  float(T if Tm is None else Tm), 0.0]
        self.acc: Dict[str, float] = {k: 0.0 for k in (
            'fog_water_kg', 'fog_evap_kg', 'fog_unevap_kg', 'fog_on_s',
            'surf_evap_kg', 'dew_kg', 'transp_kg', 'drain_kg',
            'cond_kg', 'cond_s', 'crop_dew_s', 'leaf_wet_s',
            'rain_open_s', 'heat_cool_s', 'heater_kwh', 'cooler_kwh',
            'fan_kwh', 'fog_pump_kwh', 'fog_while_humid_s',
            # 작물 높이의 일사 적분 [J/m²] — 받은 것(스크린 반영)과 스크린을 다 걷었다면 받았을 것.
            'light_crop_J', 'light_open_J')}
        self.fine: Dict[str, list] = {k: [] for k in (
            't', 'T', 'RH', 'VPD', 'CO2', 'Tm', 'pool', 'G', 'open', 'fan',
            'fog', 'rain', 'heat', 'cool', 'T_cover', 'Td', 'T_ext', 'air_speed')}
        self.fine_pos: Dict[str, list] = {aid: [] for aid in self.specs}
        self._next_trace = self.t
        self._max_open_area = sum(a.area_m2 for a in actuators if a.kind == 'opening') or 1.0

    # ── 명령 ─────────────────────────────────────────────────────────────────
    def set_command(self, actuator_id: str, output_type: Optional[str],
                    amount: Optional[float], now: Optional[float] = None) -> None:
        s = self.st.get(actuator_id)
        spec = self.specs.get(actuator_id)
        if s is None or spec is None:
            return
        now = self.t if now is None else float(now)
        s.n_cmd += 1
        ot = (output_type or 'value').lower()
        if ot == 'off':
            s.pulse = False
            s.on_until = now
            s.target = 0.0
        elif ot == 'sec':
            s.pulse = True
            s.on_until = now + max(0.0, float(amount or 0.0))
            s.target = 100.0
        elif ot == 'vol':
            flow = spec.flow_kg_s if spec.flow_kg_s > 0 else 1.0
            sec = max(0.0, float(amount or 0.0)) / 1000.0 / flow
            s.pulse = True
            s.on_until = now + sec
            s.target = 100.0
        else:   # value / pwm
            s.pulse = False
            s.target = max(0.0, min(100.0, float(amount or 0.0)))
        s.believed = 0.0 if s.pulse and ot == 'off' else (
            100.0 if s.pulse else s.target)
        if not s.pulse and spec.travel_open_s <= 0 and spec.travel_close_s <= 0:
            if not s.dead and s.stuck is None:
                s.pos = s.target

    def set_fault(self, actuator_id: str, dead: Optional[bool] = None,
                  stuck: Optional[float] = None, clear_stuck: bool = False) -> None:
        s = self.st.get(actuator_id)
        if s is None:
            return
        if dead is not None:
            s.dead = bool(dead)
        if clear_stuck:
            s.stuck = None
        elif stuck is not None:
            s.stuck = float(stuck)
            s.pos = s.stuck

    def set_position(self, actuator_id: str, pct: float) -> None:
        """초기 위치(물리·믿음 모두)."""
        s = self.st.get(actuator_id)
        if s is not None:
            s.pos = s.target = s.believed = max(0.0, min(100.0, float(pct)))

    def believed_position(self, actuator_id: str) -> float:
        s = self.st.get(actuator_id)
        return s.believed if s else 0.0

    def physical_position(self, actuator_id: str) -> float:
        s = self.st.get(actuator_id)
        return s.pos if s else 0.0

    # ── 관측 ─────────────────────────────────────────────────────────────────
    def observe(self) -> Dict[str, float]:
        T, w, C, Tm, pool = self.x
        e = ps.vapor_pressure_from_ratio(w, P_KPA)
        return {
            'T': T, 'RH': ps.relative_humidity(T, e), 'VPD': ps.vpd(T, e),
            'CO2': C, 'w': w, 'Td': ps.dewpoint(e), 'Tm': Tm, 'pool': pool,
        }

    # ── 장치 → 이번 스텝 입력 ────────────────────────────────────────────────
    def _ratio(self, aid: str, t0: float, h: float) -> float:
        """[t0, t0+h] 동안의 평균 물리 가동률 0..1. 모터는 주행을 반영해 위치도 옮긴다."""
        s, spec = self.st[aid], self.specs[aid]
        if s.dead:
            return 0.0 if spec.kind != 'opening' else s.pos / 100.0
        if s.stuck is not None:
            s.pos = s.stuck
            return s.stuck / 100.0
        if s.pulse:
            on = max(0.0, min(t0 + h, s.on_until) - t0)
            frac = on / h if h > 0 else 0.0
            s.pos = 100.0 if s.on_until > t0 + h - 1e-9 else 0.0
            return frac
        p0 = s.pos
        if s.target != s.pos:
            travel = spec.travel_open_s if s.target > s.pos else spec.travel_close_s
            if travel <= 0:
                s.pos = s.target
            else:
                step = 100.0 / travel * h
                if abs(s.target - s.pos) <= step:
                    s.pos = s.target
                else:
                    s.pos += step if s.target > s.pos else -step
        return 0.5 * (p0 + s.pos) / 100.0

    def _inputs(self, t0: float, h: float, wx: Dict[str, float]) -> dict:
        p = self.p
        u = {
            'T_e': float(wx.get('T', 20.0)), 'RH_e': float(wx.get('RH', 60.0)),
            'I': max(0.0, float(wx.get('solar', 0.0) or 0.0)),
            'wind': max(0.0, float(wx.get('wind', 0.0) or 0.0)),
            'rain': max(0.0, float(wx.get('rain', 0.0) or 0.0)),
            'C_e': float(wx.get('co2', 420.0) or 420.0),
            'cloud': max(0.0, min(1.0, float(wx.get('cloud', 0.5) or 0.0))),
            'A_open': 0.0, 'A_open_raw': 0.0, 'Q_in': 0.0, 'Q_ex': 0.0, 'Q_circ': 0.0,
            'm_w': 0.0, 'eta_w': 0.0, 'nozzles': 0.0, 'Q_heat': 0.0, 'Q_cool': 0.0,
            'shade_closed': 0.0, 'curtain_closed': 0.0, 'co2_inj': 0.0, 'Q_light': 0.0,
            'fog_ratio': 0.0,
        }
        u['w_e'] = ps.humidity_ratio(ps.vapor_pressure(u['T_e'], u['RH_e']), P_KPA)
        n_shade = n_curt = 0
        for aid, spec in self.specs.items():
            r = self._ratio(aid, t0, h)
            k = spec.kind
            if k == 'opening':
                u['A_open_raw'] += spec.area_m2 * r
            elif k == 'intake_fan':
                u['Q_in'] += spec.rated_m3h / 3600.0 * r
            elif k == 'exhaust_fan':
                u['Q_ex'] += spec.rated_m3h / 3600.0 * r
            elif k == 'circulation_fan':
                u['Q_circ'] += spec.rated_m3h / 3600.0 * r
            elif k == 'fogger':
                if p.water_available and r > 0:
                    m = spec.flow_kg_s * r
                    u['m_w'] += m
                    u['eta_w'] += spec.eta * m
                    u['nozzles'] += spec.nozzles * r
                u['fog_ratio'] = max(u['fog_ratio'], r)
            elif k == 'heater':
                u['Q_heat'] += spec.rated_kw * 1000.0 * r
            elif k == 'cooler':
                u['Q_cool'] += spec.rated_kw * 1000.0 * r
            elif k == 'shade':
                u['shade_closed'] += 1.0 - r
                n_shade += 1
            elif k == 'curtain':
                u['curtain_closed'] += 1.0 - r
                n_curt += 1
            elif k == 'co2_injector':
                u['co2_inj'] += spec.co2_kg_h / 3600.0 * r
            elif k == 'lighting':
                u['Q_light'] += spec.rated_kw * 1000.0 * r
        if n_shade:
            u['shade_closed'] /= n_shade
        if n_curt:
            u['curtain_closed'] /= n_curt
        u['eta_w'] = u['eta_w'] / u['m_w'] if u['m_w'] > 0 else 0.0
        u['A_open'] = u['A_open_raw'] * p.opening_net_factor * p.opening_area_scale
        u['open_frac'] = min(1.0, u['A_open_raw'] / self._max_open_area)
        u['T_sky'] = u['T_e'] - p.sky_depression_K * (1.0 - u['cloud'])
        tau = p.tau_cover * (1.0 - (1.0 - p.shade_tau) * u['shade_closed']) \
            * (1.0 - (1.0 - p.curtain_tau) * u['curtain_closed'])
        u['I_in'] = u['I'] * tau
        return u

    # ── 환기량 ───────────────────────────────────────────────────────────────
    def exchange(self, T: float, u: dict) -> Tuple[float, dict]:
        """환기량 G [m³/s] 와 내역."""
        p = self.p
        A = u['A_open']
        G_w = p.opening_cd * math.sqrt(p.opening_cw) * u['wind'] * A / 2.0
        dT = T - u['T_e']
        G_s = p.opening_cd * A / 3.0 * math.sqrt(
            G_ACC * p.opening_stack_h * abs(dT) / (u['T_e'] + 273.15))
        G_nat = math.hypot(G_w, G_s)
        G_leak = p.volume_m3 * (p.leak_ach + p.leak_ach_wind * u['wind']) / 3600.0
        Q_in, Q_ex = u['Q_in'], u['Q_ex']
        Q_bal = min(Q_in, Q_ex)
        Q_unb_r = abs(Q_in - Q_ex)
        Q_unb = 0.0
        if Q_unb_r > 0:
            A_mk = A + p.leak_area_m2
            a = 1.2 / (2.0 * (p.opening_cd * A_mk) ** 2)
            Q_unb = Q_unb_r / math.sqrt(1.0 + a * Q_unb_r ** 2 / p.fan_dp_max)
        sc = 1.0 - p.fan_short_circuit * u['open_frac']
        Q_mech_b, Q_mech_u = Q_bal * sc, Q_unb * sc
        G = G_leak + Q_mech_b + math.hypot(G_nat, Q_mech_u)
        return G, {'wind': G_w, 'stack': G_s, 'leak': G_leak, 'fan_bal': Q_mech_b,
                   'fan_unb': Q_mech_u, 'fan_raw': Q_in + Q_ex, 'fan_unb_raw': Q_unb_r}

    def circ_frac(self, u: dict) -> float:
        """순환팬이 만드는 잎 둘레 공기 움직임 0~1 — 정격 풍량 ÷ (바닥 면적 × `circ_ref_m3h_m2`). 팬이 안 돌면 0."""
        q = float(u.get('Q_circ', 0.0) or 0.0) * 3600.0
        ref = self.p.circ_ref_m3h_m2 * self.p.floor_m2
        return 0.0 if q <= 0.0 or ref <= 0.0 else min(1.0, q / ref)

    # ── 미분 ────────────────────────────────────────────────────────────────
    def rates(self, x, u: dict, diag: bool = False):
        p = self.p
        T, w, C, Tm, pool = x
        T = max(-40.0, min(90.0, T))
        w = max(1e-6, w)
        e = ps.vapor_pressure_from_ratio(w, P_KPA)
        RH = ps.relative_humidity(T, e)
        vpd = ps.vpd(T, e)
        rho_da = ps.dry_air_density(T, e, P_KPA)
        cp = CP_DA + w * CP_V
        Lv = latent(T)
        A_f = p.floor_m2
        A_crop = A_f * p.crop_cover
        G, gparts = self.exchange(T, u)

        # 일사
        Q_sol_air = p.solar_air_frac * u['I_in'] * A_f
        Q_sol_mass = p.solar_mass_frac * u['I_in'] * A_f
        # 외피·환기
        UA = p.U_cover * (1.0 + 0.04 * u['wind']) * p.cover_m2 \
            * (1.0 - p.curtain_ua_saving * u['curtain_closed'])
        Q_env = UA * (u['T_e'] - T)
        Q_vent = rho_da * cp * G * (u['T_e'] - T)
        circ = self.circ_frac(u)            # 순환팬 공기 움직임 0~1 (팬이 없으면 0)
        # 순환팬은 공기보다 **찬** 잎을 공기 쪽으로 끌어올린다 — 따뜻한 덩어리(지중열)는 식히지 않는다(모듈 머리말).
        h_m = p.h_mass * (1.0 + p.circ_coupling * circ) if Tm < T else p.h_mass
        Q_mass = h_m * A_f * (Tm - T)

        # 분무 — 실제로 분무를 지나는 공기만 물을 받는다.
        E_fog = 0.0
        unevap = 0.0
        if u['m_w'] > 0:
            Q_thru = G + p.fog_recirc_per_nozzle * u['nozzles'] + u['Q_circ']
            m_da = rho_da * Q_thru
            ev = ps.evaporate(T, RH, m_da, u['m_w'], eta=u['eta_w'], eps=p.fog_eps,
                              p=P_KPA, T_water=p.fog_water_T)
            E_fog = ev.E
            unevap = ev.unevaporated
        Q_fog = -E_fog * (L0 + CP_V * T - CP_W * p.fog_water_T)
        land = unevap * p.fog_land_on_crop

        # 증산 — 일사 × VPD 구동, 잎이 젖은 만큼 줄고 고VPD 에서 기공이 닫힌다.
        cap = p.leaf_water_cap * A_crop
        wet_frac = min(1.0, pool / cap) if cap > 0 else 0.0
        R_crop = Q_sol_mass / A_f
        f_vpd = min(1.0, 0.3 + 0.7 * vpd / 1.0)
        stress = 1.0 / (1.0 + max(0.0, vpd - 3.0))
        E_tr = A_crop * (p.transp_k_rad * R_crop / Lv * f_vpd + p.transp_k_vpd * vpd) \
            * stress * (1.0 - wet_frac)
        E_tr = max(0.0, E_tr)
        # 젖은면 증발 / 이슬 맺힘 (잎 온도 ≈ Tm)
        dws = ps.w_sat(Tm, P_KPA) - w
        if dws > 0:
            E_surf = rho_da * p.leaf_g * (1.0 + p.circ_leaf_g * circ) * A_crop * wet_frac * dws
        else:
            E_surf = rho_da * p.leaf_g * A_crop * dws      # 음수 = 작물 결로
        # 피복 결로
        h_out = p.h_cover_out + 3.0 * u['wind']
        h_sky = p.h_cover_sky * (1.0 - u['cloud'])
        T_cov = (p.h_cover_in * T + h_out * u['T_e'] + h_sky * u['T_sky']
                 + p.cover_solar_abs * u['I']) / (p.h_cover_in + h_out + h_sky)
        A_cov = p.cover_m2 * (1.0 - 0.7 * u['curtain_closed'])
        g_c = p.h_cover_in / (rho_da * cp)
        E_cond = rho_da * g_c * A_cov * max(0.0, w - ps.w_sat(T_cov, P_KPA))
        Q_cond = 0.5 * Lv * E_cond
        # 냉방
        Q_cool_s = u['Q_cool']
        E_coil = 0.0
        if Q_cool_s > 0 and w > ps.w_sat(p.cooler_coil_T, P_KPA):
            E_coil = p.cooler_latent_frac * Q_cool_s / Lv
            Q_cool_s *= (1.0 - p.cooler_latent_frac)

        C_a = p.air_cap_mult * 1200.0 * p.volume_m3
        C_m = p.mass_cap_J_m2K * A_f
        M_da = rho_da * p.volume_m3

        Q_air = (Q_sol_air + Q_mass + Q_env + Q_vent + u['Q_heat'] - Q_cool_s
                 + Q_fog + Q_cond + u['Q_light'])
        Q_sky_m = p.h_sky_mass * A_f * (Tm - u['T_sky']) * (1.0 - u['cloud']) \
            * (1.0 - 0.7 * u['curtain_closed']) * (1.0 - 0.5 * u['shade_closed'])
        Q_m = (Q_sol_mass - Q_mass - Lv * (E_tr + E_surf)
               - p.h_ground * A_f * (Tm - p.T_ground) - Q_sky_m
               - land * CP_W * (Tm - p.fog_water_T))
        dT = Q_air / C_a
        dTm = Q_m / C_m
        dw = (E_tr + E_surf + E_fog - E_cond - E_coil + rho_da * G * (u['w_e'] - w)) / M_da
        photo = A_crop * p.photo_max * min(1.0, u['I_in'] / 400.0) * C / (C + 300.0)
        respir = A_crop * p.resp
        dC = G / p.volume_m3 * (u['C_e'] - C) \
            + 1e6 / (CO2_KG_M3 * p.volume_m3) * (u['co2_inj'] - photo + respir)
        dpool = land + 0.3 * E_cond - E_surf
        d = (dT, dw, dC, dTm, dpool)
        if not diag:
            return d
        return d, {
            'G': G, 'gparts': gparts, 'E_fog': E_fog, 'unevap': unevap, 'land': land,
            'E_tr': E_tr, 'E_surf': E_surf, 'E_cond': E_cond, 'T_cover': T_cov,
            'Td': ps.dewpoint(e), 'RH': RH, 'VPD': vpd, 'cap': cap,
            'Q': {'sol_air': Q_sol_air, 'sol_mass': Q_sol_mass, 'env': Q_env,
                  'vent': Q_vent, 'mass_to_air': Q_mass, 'heat': u['Q_heat'],
                  'cool': -Q_cool_s, 'fog': Q_fog, 'cond': Q_cond, 'light': u['Q_light'],
                  'sky_mass': -Q_sky_m, 'latent_mass': -Lv * (E_tr + E_surf),
                  'ground': -p.h_ground * A_f * (Tm - p.T_ground),
                  'water_sens': -land * CP_W * (Tm - p.fog_water_T)},
            'C_a': C_a, 'C_m': C_m, 'M_da': M_da,
        }

    def _substeps(self, u: dict, h: float) -> int:
        p = self.p
        G, _ = self.exchange(self.x[0], u)
        C_a = p.air_cap_mult * 1200.0 * p.volume_m3
        a_T = (p.U_cover * p.cover_m2 + 1200.0 * G
               + p.h_mass * (1.0 + p.circ_coupling * self.circ_frac(u)) * p.floor_m2) / C_a   # 상한(안전 쪽)
        a_x = (G + p.fog_recirc_per_nozzle * u['nozzles'] + u['Q_circ']) / p.volume_m3
        a = max(a_T, a_x, 1e-9)
        return max(1, min(200, int(a * h / 0.4) + 1))

    # ── 적분 ────────────────────────────────────────────────────────────────
    def advance(self, t_end: float, weather: WeatherFn, dt: float = 10.0) -> None:
        """`t_end` 까지 적분한다. 펄스가 끝나는 시각에서 스텝을 끊는다."""
        while self.t < t_end - 1e-9:
            h = min(dt, t_end - self.t)
            for s in self.st.values():
                if s.pulse and self.t < s.on_until < self.t + h:
                    h = s.on_until - self.t
            h = max(h, 1e-3)
            wx = weather(self.t + 0.5 * h)
            u = self._inputs(self.t, h, wx)
            self._record(u, h)
            n = self._substeps(u, h)
            hs = h / n
            for _ in range(n):
                self.x = self._rk4(self.x, u, hs)
            self.t += h

    def _rk4(self, x, u, h):
        def add(a, b, s):
            return [ai + s * bi for ai, bi in zip(a, b)]
        k1 = self.rates(x, u)
        k2 = self.rates(add(x, k1, h / 2), u)
        k3 = self.rates(add(x, k2, h / 2), u)
        k4 = self.rates(add(x, k3, h), u)
        xn = [xi + h / 6.0 * (a + 2 * b + 2 * c + d)
              for xi, a, b, c, d in zip(x, k1, k2, k3, k4)]
        # 물리 한계
        T = max(-40.0, min(90.0, xn[0]))
        xn[0] = T
        xn[1] = max(1e-6, min(xn[1], ps.w_sat(T, P_KPA) * 1.02))
        xn[2] = max(0.0, xn[2])
        cap = self.p.leaf_water_cap * self.p.floor_m2 * self.p.crop_cover
        if xn[4] > cap:
            self.acc['drain_kg'] += xn[4] - cap
            xn[4] = cap
        xn[4] = max(0.0, xn[4])
        return xn

    def _record(self, u: dict, h: float) -> None:
        """스텝 시작 상태로 누적량·세밀 기록을 남긴다(스텝 길이 h 만큼)."""
        p = self.p
        _, dg = self.rates(self.x, u, diag=True)
        a = self.acc
        a['fog_water_kg'] += u['m_w'] * h
        a['fog_evap_kg'] += dg['E_fog'] * h
        a['fog_unevap_kg'] += dg['unevap'] * h
        if u['fog_ratio'] > 0:
            a['fog_on_s'] += u['fog_ratio'] * h
            if dg['RH'] >= 90.0:
                a['fog_while_humid_s'] += u['fog_ratio'] * h
        a['transp_kg'] += dg['E_tr'] * h
        if dg['E_surf'] >= 0:
            a['surf_evap_kg'] += dg['E_surf'] * h
        else:
            a['dew_kg'] += -dg['E_surf'] * h
            a['crop_dew_s'] += h
        a['cond_kg'] += dg['E_cond'] * h
        # 결로 '분' 은 피복 1 m² 당 0.5 g/h 이상일 때만 센다(이슬 한 방울로 세지 않는다).
        if dg['E_cond'] > 0.5e-3 / 3600.0 * p.cover_m2:
            a['cond_s'] += h
        if self.x[4] > 0.02 * p.floor_m2 * p.crop_cover:
            a['leaf_wet_s'] += h
        if u['rain'] > 0.1 and u['open_frac'] > 0.05:
            a['rain_open_s'] += h
        if u['Q_heat'] > 0 and u['Q_cool'] > 0:
            a['heat_cool_s'] += h
        a['heater_kwh'] += u['Q_heat'] / p.heater_eff / 3.6e6 * h
        a['cooler_kwh'] += u['Q_cool'] / p.cooler_cop / 3.6e6 * h
        a['fan_kwh'] += (u['Q_in'] + u['Q_ex'] + u['Q_circ']) * 3600.0 \
            * p.fan_kw_per_m3h * h / 3600.0
        a['fog_pump_kwh'] += p.fog_pump_kw * u['fog_ratio'] * h / 3600.0
        a['light_crop_J'] += u['I_in'] * h
        a['light_open_J'] += u['I'] * p.tau_cover * h
        if self.t + 1e-9 >= self._next_trace:
            o = self.observe()
            f = self.fine
            f['t'].append(round(self.t, 1))
            f['T'].append(round(o['T'], 3))
            f['RH'].append(round(o['RH'], 2))
            f['VPD'].append(round(o['VPD'], 4))
            f['CO2'].append(round(o['CO2'], 1))
            f['Tm'].append(round(o['Tm'], 3))
            f['pool'].append(round(o['pool'], 3))
            f['G'].append(round(dg['G'], 3))
            f['open'].append(round(u['open_frac'], 4))
            f['fan'].append(round((u['Q_in'] + u['Q_ex']) * 3600.0, 1))
            f['fog'].append(round(u['fog_ratio'], 3))
            f['rain'].append(round(u['rain'], 2))
            f['heat'].append(round(u['Q_heat'] / 1000.0, 2))
            f['cool'].append(round(u['Q_cool'] / 1000.0, 2))
            f['T_cover'].append(round(dg['T_cover'], 2))
            f['Td'].append(round(dg['Td'], 2) if dg['Td'] is not None else None)
            f['T_ext'].append(round(u['T_e'], 2))
            sect = max(p.span_m * p.mean_height_m, 1.0)
            f['air_speed'].append(round((dg['gparts']['fan_bal']) / sect, 3))
            for aid, s in self.st.items():
                self.fine_pos[aid].append(round(s.pos, 1))
            self._next_trace += self.TRACE_EVERY

    def energy_terms(self, weather_now: Dict[str, float]) -> dict:
        """현재 상태의 열·수분 내역(시험·진단용). 장치 상태는 바꾸지 않는다."""
        saved = {aid: (s.pos, s.target, s.on_until) for aid, s in self.st.items()}
        u = self._inputs(self.t, 1e-6, weather_now)
        for aid, (pos, tgt, ou) in saved.items():
            self.st[aid].pos, self.st[aid].target, self.st[aid].on_until = pos, tgt, ou
        _, dg = self.rates(self.x, u, diag=True)
        return dg


# ─────────────────────────────────────────────────────────────────────────────
# DB 시설 정의 → 파라미터·장치
# ─────────────────────────────────────────────────────────────────────────────

_COVER_PROPS = {
    # cover: (U W/m²K, 필름 투과율)
    'vinyl_single': (6.5, 0.85),
    'vinyl_double': (4.2, 0.75),
    'po_single':    (6.3, 0.88),
    'glass':        (6.0, 0.88),
    'pc':           (3.5, 0.80),
}
_FAN_DEFAULT_M3H = 30000.0


def _arch_dims(g: dict) -> dict:
    span = float(g.get('span_width_m') or 7.0)
    length = float(g.get('length_m') or 50.0)
    eave = float(g.get('eave_height_m') or 2.0)
    ridge = float(g.get('ridge_height_m') or (eave + 1.5))
    rise = max(0.0, ridge - eave)
    if (g.get('roof_type') or 'arch') == 'arch':
        section = span * eave + 2.0 / 3.0 * span * rise
        roof_w = span * (1.0 + 8.0 / 3.0 * (rise / span) ** 2)
    else:                                   # 박공·평지붕 근사
        section = span * eave + 0.5 * span * rise
        roof_w = 2.0 * math.hypot(span / 2.0, rise)
    return {'span': span, 'length': length, 'eave': eave, 'ridge': ridge,
            'section': section, 'roof_w': roof_w}


def facility_from_db(db_path: str, facility_uuid: str
                     ) -> Tuple[PlantParams, List[ActuatorSpec], dict]:
    """시설 정의(sqlite)에서 참값 파라미터와 장치 목록을 만든다.

    제어기 코드(`facility_integration`·`capacity_meta`)를 거치지 않는다 — 시험
    대상 코드 판이 바뀌어도 시설은 그대로여야 하기 때문이다.
    """
    uri = db_path if db_path.startswith('file:') else f'file:{db_path}?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    try:
        row = db.execute(
            'select name, geometry_3d, envelope, fittings, actuators, bay_count '
            'from geo_facility where unique_id = ?', (facility_uuid,)).fetchone()
        if row is None:
            raise ValueError(f'facility not found: {facility_uuid}')
        name, g_raw, env_raw, fit_raw, act_raw, bays = row
        g = json.loads(g_raw or '{}') or {}
        env = json.loads(env_raw or '{}') or {}
        fittings = json.loads(fit_raw or '[]') or []
        act_list = json.loads(act_raw or '[]') or []
        if not isinstance(act_list, list):
            act_list = []
        out_names = {}
        travel = {}
        for oid, oname in db.execute('select unique_id, name from output'):
            out_names[oid] = oname
        for oid, ch, opts in db.execute(
                'select output_id, channel, custom_options from output_channel'):
            if ch not in (0, None):
                continue
            try:
                o = json.loads(opts or '{}')
            except Exception:
                o = {}
            if 'travel_time_open_sec' in o or 'travel_time_close_sec' in o:
                travel[oid] = (float(o.get('travel_time_open_sec') or 0.0),
                               float(o.get('travel_time_close_sec') or 0.0))
    finally:
        db.close()

    nb = max(1, int(bays or 1))
    d = _arch_dims(g)
    floor = d['span'] * d['length'] * nb
    volume = d['section'] * d['length'] * nb
    cover_area = (d['roof_w'] * d['length'] * nb + 2.0 * d['eave'] * d['length']
                  + 2.0 * d['section'] * nb)
    layers = env.get('layers') or []
    cover = (layers[0].get('cover') if layers else None) or 'vinyl_single'
    U, tau_film = _COVER_PROPS.get(cover, _COVER_PROPS['vinyl_single'])
    if len([l for l in layers if (l.get('type') or 'full') == 'full']) >= 2:
        U *= 0.65
        tau_film *= 0.88
    stage_h = sum(float(s.get('height_m') or 0.0) for s in
                  (((env.get('side_vent') or {}).get('outer') or {}).get('stages') or []))
    orient = float(g.get('orientation_deg') or 0.0)

    params = PlantParams(
        name=name or facility_uuid[:8],
        floor_m2=round(floor, 2), volume_m3=round(volume, 2),
        cover_m2=round(cover_area, 2), span_m=d['span'], length_m=d['length'],
        mean_height_m=round(d['section'] / d['span'], 3),
        latitude=float(g.get('center_lat') or 35.86),
        longitude=float(g.get('center_lng') or 126.88),
        U_cover=U, tau_cover=round(tau_film * 0.9, 3),
        opening_stack_h=stage_h or 1.2,
        leak_area_m2=round(0.002 * cover_area, 2),
    )

    def _az(normal):
        if not normal or len(normal) < 3:
            return None
        nx, nz = float(normal[0]), float(normal[2])
        if abs(nx) < 1e-9 and abs(nz) < 1e-9:
            return None
        # 시설 좌표: x=폭(동), z=길이(남→북) 가정. 방위 0=N, 90=E.
        return round((math.degrees(math.atan2(nx, nz)) + orient) % 360.0, 1)

    specs: Dict[str, ActuatorSpec] = {}
    layer_flow: Dict[str, list] = {}
    for f in fittings:
        if f.get('kind') == 'irrigation_device':
            sub = (f.get('sub_type') or '').lower()
            if sub in ('drip', 'dripper', 'drip_emitter'):
                continue
            layer_flow.setdefault(f.get('layer_id'), []).append(f)
    list_specs = {a.get('device_uuid'): a for a in act_list if a.get('device_uuid')}

    for f in fittings:
        aid = f.get('actuator_id')
        if not aid:
            continue
        k = f.get('kind')
        size = f.get('size') or {}
        nm = out_names.get(aid, f.get('name') or aid[:8])
        to, tc = travel.get(aid, (0.0, 0.0))
        if k in ('side_window', 'window', 'door'):
            w = float(size.get('w') or 0.0)
            h = float(size.get('h') or 0.0)
            if k == 'side_window' and f.get('source') == 'envelope' and stage_h > 0:
                h = stage_h            # 감아 올리는 높이가 실제 개구다(골조 높이가 아니라)
            sp = specs.get(aid) or ActuatorSpec(aid, 'opening', nm, travel_open_s=to,
                                                travel_close_s=tc)
            sp.area_m2 += w * h
            sp.azimuth_deg = _az(f.get('surface_normal'))
            specs[aid] = sp
        elif k == 'fan':
            role = f.get('fan_role') or 'circulation_fan'
            la = list_specs.get(aid) or {}
            rated = float(((la.get('specs') or {}).get('airflow_cmh'))
                          or f.get('airflow_cmh') or _FAN_DEFAULT_M3H)
            specs[aid] = ActuatorSpec(aid, la.get('kind') or role, nm, rated_m3h=rated,
                                      azimuth_deg=_az(f.get('surface_normal')))
        elif k in ('irrigation_valve', 'fogger'):
            devs = layer_flow.get(f.get('layer_id')) or []
            lph = sum(float(x.get('flow_lph') or 0.0) for x in devs)
            n = len(devs)
            if k == 'fogger' and lph <= 0:
                lph, n = 360.0, 60          # 고압 포그 기본: 6 L/h × 60
            if lph <= 0:
                continue                    # 점적 전용 — 환경 장치 아님
            wetting = any((x.get('orientation') == 'down') or
                          float(x.get('flow_lph') or 0.0) >= 20.0 for x in devs) \
                if devs else False
            specs[aid] = ActuatorSpec(
                aid, 'fogger', nm, flow_kg_s=lph / 3600.0, nozzles=n,
                eta=0.35 if wetting else 0.9, wetting=wetting)
        elif k in ('heater', 'cooler'):
            specs[aid] = ActuatorSpec(aid, k, nm, rated_kw=float(
                f.get('capacity_kw') or (0.15 if k == 'heater' else 0.2) * floor))
        elif k in ('curtain', 'shade_curtain'):
            specs[aid] = ActuatorSpec(aid, 'curtain' if k == 'curtain' else 'shade', nm,
                                      travel_open_s=to or 240.0, travel_close_s=tc or 240.0)
        elif k == 'co2_injector':
            specs[aid] = ActuatorSpec(aid, 'co2_injector', nm, co2_kg_h=0.01 * floor)
        elif k == 'lighting':
            specs[aid] = ActuatorSpec(aid, 'lighting', nm, rated_kw=0.05 * floor)

    # 목록형(ActuatorUI) 장치 중 피팅이 없는 것
    ui_kind = {'side_window_motor': 'opening', 'roof_vent_motor': 'opening',
               'thermal_curtain_motor': 'curtain', 'shade_curtain_motor': 'shade',
               'exhaust_fan': 'exhaust_fan', 'intake_fan': 'intake_fan',
               'circulation_fan': 'circulation_fan', 'heater': 'heater',
               'cooler': 'cooler', 'heat_pump': 'cooler'}
    for aid, a in list_specs.items():
        if aid in specs:
            continue
        k = ui_kind.get(a.get('kind'))
        if not k:
            continue
        sp = a.get('specs') or {}
        nm = out_names.get(aid, aid[:8])
        if k in ('exhaust_fan', 'intake_fan', 'circulation_fan'):
            specs[aid] = ActuatorSpec(aid, k, nm, rated_m3h=float(
                sp.get('airflow_cmh') or _FAN_DEFAULT_M3H))
        elif k in ('heater', 'cooler'):
            specs[aid] = ActuatorSpec(aid, k, nm, rated_kw=float(
                sp.get('capacity_kw') or (0.15 if k == 'heater' else 0.2) * floor))
        elif k in ('curtain', 'shade'):
            specs[aid] = ActuatorSpec(aid, k, nm, travel_open_s=240.0, travel_close_s=240.0)
        elif k == 'opening':
            specs[aid] = ActuatorSpec(aid, k, nm, area_m2=float(sp.get('area_m2') or 10.0))

    info = {'cover': cover, 'side_vent_stage_h': stage_h, 'dims': d, 'bays': nb}
    return params, sorted(specs.values(), key=lambda s: (s.kind, s.name)), info


__all__ = ['PlantParams', 'ActuatorSpec', 'Plant', 'facility_from_db', 'latent']
