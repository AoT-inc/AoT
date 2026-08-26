# coding=utf-8
"""
env_control/effect_functions.py — 액추에이터별 EffectFn 구현체.

모든 함수는 R1 단위 규약을 준수한다:
  magnitude_native = 변수 native 단위 / 1 사이클 (cmd_pct=100 기준)

K_* 계수는 모듈 기본값. 실제 사용 시 apply_calibration()으로 장치별 오버라이드.

참조: docs/dev/integrated_env_control_design.md §3.3
"""

import math

from .types import VENTILATING_KINDS, EffectResult, EnvContext


def _svp_kpa(T: float) -> float:
    """포화 수증기압 [kPa] (Magnus). VPD effect 유도용."""
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


# 선언된 humidity effect 가 **수분 이동이 아니라 온도 변화의 부산물**인 종류.
# 난방기('온도 상승 → 같은 절대습도에서 RH 하락')와 냉방기('응결로 RH 상승
# 경향')가 그렇다. dsvp/dT 항이 이 RH 변화를 이미 담고 있으므로 dea 에 다시
# 더하면 이중계상이다. 개구부·분무·배기/흡기팬은 실제로 수분을 옮기므로 남긴다.
# (커튼·차광막·보광등은 humidity effect 자체를 선언하지 않는다.)
_THERMAL_RH_KINDS = frozenset({'heater', 'cooler'})


def _vpd_gap(env: EnvContext):
    """실내 → 실외 VPD 폭. 실외를 모르면 None(클램프하지 않는다).

    실외를 모를 때 0 으로 두면 환기 효과가 통째로 0 이 되어 창이 영영 안 열린다.
    모르는 것과 없는 것을 구분한다.
    """
    T_e, RH_e = env.get('T_ext'), env.get('RH_ext')
    T_i, RH_i = env.get('T_int'), env.get('RH_int')
    if None in (T_e, RH_e, T_i, RH_i):
        return None
    vpd_ext = _svp_kpa(float(T_e)) * (1.0 - float(RH_e) / 100.0)
    vpd_int = _svp_kpa(float(T_i)) * (1.0 - float(RH_i) / 100.0)
    return vpd_ext - vpd_int


def vent_reachable(magnitude: float, gap: float) -> float:
    """환기 효과를 **도달 가능한 끝점**으로 자른다 (2026-08-26).

    환기는 실내 공기를 실외 공기로 바꾸는 것이므로 종착점이 실외 하나다 —
    아무리 크게 열어도 실외를 **지나칠 수 없다**. 그런데 개구부 효과식은

        magnitude = |내외 차| × (개도/100) × k × 풍속보정 × 면적계수

    라서 `k × 풍속보정 × 면적계수` 가 1 을 넘으면 도달 한계를 넘어선 값이 나온다.
    면적계수는 기준 면적 대비 비율이라 큰 측창에서는 쉽게 10 을 넘는다.

    실측(2026-08-26 イチゴ): 측창 하나의 VPD 유효도가 **2.0 kPa** 였는데
    실제로 갈 수 있는 폭은 실내 0.28 → 실외 0.895, 즉 **0.615 kPa** 였다
    (3.3배 과대). 결과는 조용했다 — 측창 둘이 7.4%·10.6% 만 열려도 부하분담
    누적이 편차를 넘어서서, 가장 유효한 **천창이 "이미 다 됐다" 로 읽고
    닫힌 채** 있었다(e_norm = −0.146). 창이 덜 열리니 그 몫은 난방기가 졌다.

    ⚠ 이 클램프는 **환기 계열에만** 옳다. 난방기·냉방기·분무기는 외기와 무관하게
    열·수분을 직접 넣고 빼므로 실외를 지나칠 수 있다 — 거기에 걸면 폭염에
    냉방이 실외 온도에서 멈춘다. 판정은 `types.ACTUATOR_DOMAIN` 의 'vent' 다.
    """
    return min(abs(magnitude), abs(gap))


def make_vpd_effect(temp_fn, humid_fn, humid_is_moisture: bool = True,
                    vent_bounded: bool = False):
    """액추에이터의 T·RH effect 로부터 VPD effect 를 연쇄법칙으로 유도한다.

    VPD = svp(T) − ea 로 두고 **(T, ea) 좌표**에서 미분한다.
      ∂VPD/∂T  = dsvp/dT              (> 0)
      ∂VPD/∂ea = −1  → dRH 로 환산 = −svp/100
      dVPD = ∂VPD/∂T·dT + ∂VPD/∂RH·dRH
    dT·dRH 는 해당 액추에이터의 기존 T·RH effect(부호 있는 magnitude)에서 가져온다.
    이때 **선언된 dRH 는 "온도가 그대로일 때 수분 출입이 만드는 RH 변화"** 로
    읽는다(분무의 가습, 환기의 교환). 온도 변화가 스스로 만드는 RH 이동은
    dsvp/dT 항이 이미 담고 있으므로, 그것을 dRH 로 신고하는 종류
    (`_THERMAL_RH_KINDS`)는 `humid_is_moisture=False` 로 받아 제외한다.
    → 액추에이터별 VPD 함수를 따로 작성할 필요 없이 모든 kind 에 일관 적용.

    **(1−RH/100) 을 곱하지 않는다.** 예전에는 (T, RH) 좌표의 편미분
    (1−RH/100)·dsvp 를 썼는데, 이는 "온도를 바꾸는 동안 RH 가 그대로" 라는
    뜻이라 물을 넣지 않고는 성립하지 않는다. 그래서 RH=100% 에서
    ∂VPD/∂T = 0 이 되어 **난방기의 VPD 효과가 0** 으로 나왔다 — 포화 상태에서
    VPD 를 올릴 수단이 아예 없다고 판단하는 원인이었다. RH=50% 에서도 실제의
    절반만 잡혔다(24.34°C, dT=2°C 실측: 옛 0.182 vs 실제 0.365 kPa).
    """
    def vpd_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
        T  = env.get('T_int', 0.0)
        svp_ = _svp_kpa(T)
        dsvp = svp_ * 17.27 * 237.3 / (T + 237.3) ** 2
        dVPD_dT  = dsvp                  # (T, ea) 좌표 — RH 고정 인자를 곱하지 않는다
        dVPD_dRH = -svp_ / 100.0

        def _signed(fn):
            if fn is None:
                return 0.0
            r = fn(env, cmd_pct, profile)
            s = 1.0 if r.direction == '↑' else (-1.0 if r.direction == '↓' else 0.0)
            return r.magnitude_native * s

        dRH = _signed(humid_fn) if humid_is_moisture else 0.0
        dVPD = dVPD_dT * _signed(temp_fn) + dVPD_dRH * dRH
        if abs(dVPD) < 1e-6:
            return EffectResult('0', 0.0)
        mag = abs(dVPD)
        if vent_bounded:
            # 환기는 실외 VPD 를 지나칠 수 없다. dT·dRH 를 각각 잘라도 부족하다 —
            # 연쇄법칙은 1차 근사라 큰 이동에서 두 항이 합쳐지며 실제 도달폭을
            # 넘어선다(실측: 개별 클램프 후에도 1.28 vs 실제 0.615).
            # 그래서 VPD 축에서 직접 자른다.
            gap = _vpd_gap(env)
            if gap is not None:
                mag = vent_reachable(mag, gap)
                if mag < 1e-6:
                    return EffectResult('0', 0.0)
        return EffectResult('↑' if dVPD > 0 else '↓', mag)

    return vpd_effect

# ─────────────────────────────────────────────────────────────────────────────
# 보수적 기본 계수 (K_*) — Phase F 에서 자동 캘리브레이션으로 정밀화
# ─────────────────────────────────────────────────────────────────────────────
# 개구부: 외내부 온도차×개방률에 비례하는 경험적 배율
K_OPENING_T   = 0.08   # °C/cycle per (°C_delta × cmd_pct/100)
K_OPENING_RH  = 0.06   # %/cycle per (%_delta × cmd_pct/100)
K_OPENING_CO2 = 0.04   # ppm/cycle per (ppm_excess × cmd_pct/100)
# 냉방기
K_COOLER_T    = 2.5    # °C/cycle at 100%
K_COOLER_RH   = 0.8    # %/cycle at 100% (응결 가습)
# 포그·관수
K_FOG_RH      = 3.0    # %/cycle at 100%
K_FOG_T       = 0.5    # °C/cycle at 100% (증발냉각)
# 난방기
K_HEATER_T    = 2.0    # °C/cycle at 100%
K_HEATER_RH   = 1.5    # %/cycle at 100% (온도 상승 → 상대습도 하락)
# CO₂ 주입기
K_CO2_INJ     = 80.0   # ppm/cycle at 100%
# 차광막·보온커튼 (온도 영향만)
# 규약: 모든 액추에이터 cmd_pct = 개도(100=완전 열림, 0=완전 닫힘).
#   차광막 100%=열림=빛 유입(온도↑), 0%=닫힘=차광(온도↓ 효과)
#   보온커튼 100%=열림/걷힘=단열 없음, 0%=닫힘=보온(외피 열손실 차단)
K_SHADE_T     = 1.0    # °C/cycle at 100% 개도(=빛 완전 유입) per 일사기준
K_CURTAIN_U   = 0.04   # 보온커튼 개방 시 외피 열교환 계수 (°C/cycle per ΔT × 개도)
                       # 개구부(0.08)보다 작음 — 환기가 아닌 전도/복사 손실.

# 풍속 부스트 상한 (m/s)
WIND_BOOST_CAP = 8.0
WIND_BOOST_K   = 0.15  # 풍속 1m/s 당 효과 배율 증가

# G3: 면적·단열성능 가중 기준값 (참조용; 실측 캘리브레이션 시 조정)
REFERENCE_OPENING_AREA_M2 = 10.0   # 일반 온실 측창 1면 표준
REFERENCE_U_EFF           = 4.0    # vinyl_double 단층 기준 (W/m²K)

# 일사 기반 차광 효과 정규화 기준값 (W/m²)
# shade 를 내렸을 때 온도 하락 폭은 일사 강도에 비례. 흐린 날 차광은 효과 없음.
SOLAR_REFERENCE_W = 600.0


def _wind_boost(env: EnvContext) -> float:
    wind = min(env.get('wind', 0.0), WIND_BOOST_CAP)
    return 1.0 + WIND_BOOST_K * wind


def _calibrated_k(profile, var: str, default: float) -> float:
    """profile.calibrated_K[var] 가 있으면 반환, 없으면 default(모듈 상수) 사용.

    Stage 1 CalibrationRegistry 가 ActuatorProfile.calibrated_K 를 주입한다.
    주입 전까지는 기존 상수 동작 그대로 유지 (후방 호환).
    """
    cal_k = getattr(profile, 'calibrated_K', None)
    if cal_k and var in cal_k:
        return float(cal_k[var])
    return default


def _gis_factor(profile, use_u: bool = True):
    """GIS 메타에서 (area_factor, u_factor) 산출.

    profile 또는 필드가 없으면 1.0 (효과 변동 없음).
    """
    af, uf = 1.0, 1.0
    if profile is None:
        return af, uf
    area_m2 = getattr(profile, 'area_m2', None)
    if area_m2 and area_m2 > 0:
        af = float(area_m2) / REFERENCE_OPENING_AREA_M2
    if use_u:
        cap_meta = getattr(profile, 'capacity_meta', None) or {}
        u_eff = cap_meta.get('u_effective')
        if u_eff and u_eff > 0:
            uf = REFERENCE_U_EFF / float(u_eff)
    return af, uf


# ─────────────────────────────────────────────────────────────────────────────
# 개구부 (opening)
# ─────────────────────────────────────────────────────────────────────────────

def opening_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """외부 온도 방향으로 내부 온도를 끌어당긴다. 풍속·면적 보정.

    참고: 개구부가 열리면 envelope u_eff 는 우회되므로 u_factor 미적용.
    u_factor 는 curtain/외피 단열 변경 효과에서 의미가 있다.
    """
    delta = env.get('T_ext', 0.0) - env.get('T_int', 0.0)
    if abs(delta) < 0.5:
        return EffectResult('0', 0.0)
    direction = '↑' if delta > 0 else '↓'
    af, _u = _gis_factor(profile, use_u=False)
    k = _calibrated_k(profile, 'temperature', K_OPENING_T)
    # 환기는 실외를 지나칠 수 없다 — 도달 한계(|내외 차|)로 자른다.
    magnitude = vent_reachable(
        abs(delta) * (cmd_pct / 100.0) * k * _wind_boost(env) * af, delta)
    return EffectResult(direction, magnitude)


def opening_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """외부 습도 방향으로 내부 RH를 끌어당긴다. 풍속·면적 보정."""
    delta = env.get('RH_ext', 0.0) - env.get('RH_int', 0.0)
    if abs(delta) < 1.0:
        return EffectResult('0', 0.0)
    direction = '↑' if delta > 0 else '↓'
    af, _u = _gis_factor(profile, use_u=False)
    k = _calibrated_k(profile, 'humidity', K_OPENING_RH)
    magnitude = vent_reachable(
        abs(delta) * (cmd_pct / 100.0) * k * _wind_boost(env) * af, delta)
    return EffectResult(direction, magnitude)


def _co2_excess(env) -> float:
    """실내 CO₂ − 외기 CO₂. **측정이 없으면 0** (초과분을 알 수 없다).

    예전에는 `env.get('CO2_int', 400.0)` 처럼 기본값을 썼는데, 그러면 센서가
    없는 시설에서도 "외기와 같다" 는 가정이 값처럼 흘러 효과 모델이 돈다.
    지금 `CO2_int` 는 측정이 없으면 **None** 이라(situation.py), 기본값을 두면
    None 을 받아 그대로 TypeError 가 난다.
    """
    inside = env.get('CO2_int')
    if inside is None:
        return 0.0
    return float(inside) - float(env.get('CO2_ext') or 400.0)


def opening_co2_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """외부 CO₂(~400ppm)로 수렴. 내부가 더 높을 때만 희석 방향."""
    excess = _co2_excess(env)
    if excess <= 20:
        return EffectResult('0', 0.0)
    af, _ = _gis_factor(profile, use_u=False)
    k = _calibrated_k(profile, 'co2', K_OPENING_CO2)
    # 환기로 갈 수 있는 끝점은 외기 농도다 — 초과분을 넘겨 내릴 수 없다.
    magnitude = vent_reachable(excess * (cmd_pct / 100.0) * k * af, excess)
    return EffectResult('↓', magnitude)


# 개구부 effect_model 묶음
OPENING_EFFECT_MODEL = {
    'temperature': opening_temp_effect,
    'humidity':    opening_humid_effect,
    'co2':         opening_co2_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# 냉방기 (cooler)
# ─────────────────────────────────────────────────────────────────────────────

def cooler_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """항상 냉각. 외부 조건 무관. (실내기 — 면적·u_eff 가중 미적용)"""
    k = _calibrated_k(profile, 'temperature', K_COOLER_T)
    return EffectResult('↓', k * (cmd_pct / 100.0))


def cooler_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """응결로 RH 약간 상승 경향."""
    k = _calibrated_k(profile, 'humidity', K_COOLER_RH)
    return EffectResult('↑', k * (cmd_pct / 100.0))


COOLER_EFFECT_MODEL = {
    'temperature': cooler_temp_effect,
    'humidity':    cooler_humid_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# 포그·관수 가습기 (fogger)
# ─────────────────────────────────────────────────────────────────────────────

# 물 증발잠열 (kJ/kg)
_L_VAP_KJ_KG   = 2430.0
# 공기 열용량 (kJ/kg·K) × 밀도(kg/m³) → kJ/m³·K
_RHO_CP_AIR    = 1.21 * 1.006   # ≈ 1.217 kJ/(m³·K)
# 참조 사이클 길이 (s) — K_FOG_* 상수 기준
_CYCLE_REF_S   = 60.0
# 참조 체적 (m³) — K_FOG_* 상수 기준 (소형 온실 기준)
_VOLUME_REF_M3 = 100.0

# 포화수증기밀도 계산용 (물 몰질량 kg/mol, 기체상수 J/mol·K)
_M_WATER_KG_MOL = 0.018
_R_GAS          = 8.314

# 증발 가용도의 기준 습도 [%] — K_FOG_* 상수가 서 있는 조건.
# 이 습도 이하에서는 계수를 그대로 쓰고(가용도 1.0), 위로 갈수록 줄어 포화에서 0.
_EVAP_REF_RH = 70.0


def _absorbable_liters(env: EnvContext, volume_m3: float) -> float:
    """이 공기가 **더 받아들일 수 있는 물의 총량** [L]. 증발의 물리 상한이다.

    `_evaporation_availability` 는 증발 **속도**의 구동력을 비율로 낮출 뿐,
    증발할 수 있는 **총량**은 막지 않는다. 그래서 습한 공기에 아무리 많이
    뿌려도 모델은 그 전부가 증발한 것으로 계산한다 — RH 89% · 5,463 m³ 온실이
    실제로는 12.8 L 밖에 못 받는데 82 L 가 증발한 것으로 잡혔다(실측).

    포화수증기밀도에서 현재 수증기밀도를 뺀 만큼이 여유이고, 거기에 체적을
    곱한 것이 상한이다. 온도·습도를 모르면 상한을 걸 근거가 없으므로 무한대를
    돌려준다 — 모르는 값을 지어내 자르면 그것대로 틀린 제어가 된다.

    ⚠ 이것은 **닫힌 공간 기준의 상한**이다. 환기 중이면 수증기가 빠져나가
    실제로는 더 증발할 수 있다. 그쪽으로 틀리는 것(과소평가)은 분무를 덜 쓰게
    만들 뿐이지만, 반대로 틀리면 결합 drive 에서 이 항이 나머지를 압도한다
    (2026-08-20 육묘장 사고). 그래서 보수적인 쪽을 택한다.
    """
    if volume_m3 <= 0.0:
        return float('inf')
    t = env.get('T_int')
    if t is None:
        t = env.get('T')
    rh = env.get('RH_int')
    if rh is None:
        rh = env.get('RH')
    if t is None or rh is None:
        return float('inf')
    try:
        t = float(t)
        rh = max(0.0, min(100.0, float(rh)))
    except (TypeError, ValueError):
        return float('inf')
    # 포화수증기압 [Pa] → 포화수증기밀도 [g/m³]
    svp = 610.78 * math.exp(17.27 * t / (t + 237.3))
    rho_sat = svp * _M_WATER_KG_MOL / (_R_GAS * (t + 273.15)) * 1000.0
    head_g_m3 = rho_sat * (1.0 - rh / 100.0)
    return max(0.0, head_g_m3 * volume_m3 / 1000.0)


def _evaporation_availability(env: EnvContext) -> float:
    """분무한 물이 실제로 **증발할 수 있는 비율** [0,1].

    증발을 미는 힘은 VPD 다. 포화 공기(RH=100%)는 수증기를 더 받지 못하므로
    분무해도 증발하지 않는다 — 냉각도 가습도 일어나지 않고 표면만 젖는다.
    그런데 모델은 RH 와 무관하게 같은 ΔT·ΔRH 를 신고했다. 2026-08-20 로컬
    육묘장이 정확히 RH 100% 였고, 거기서 분무가 냉각 효과를 주장한 것이
    결합 drive 를 엉뚱하게 몰고 간 성분 중 하나다.

    ⚠ 이 `(1−RH/100)` 은 `make_vpd_effect` 에서 **제거한** 인자와 형태만 같고
    성격이 다르다. 거기서는 "온도를 바꿀 때 RH 가 고정" 이라는 틀린 가정이었고,
    여기서는 증발의 실제 구동력이다. 한쪽을 고쳤다고 다른 쪽까지 지우지 말 것.

    `_EVAP_REF_RH` 로 정규화해 기준 습도 이하에서는 1.0 에 걸어 둔다 — K_FOG_*
    는 이미 보수적인 실사용 계수라, 건조할 때 그 값을 넘겨 키우면 근거가 없다.
    """
    rh   = float(env.get('RH_int') or 0.0)
    head = 1.0 - max(0.0, min(100.0, rh)) / 100.0
    ref  = 1.0 - _EVAP_REF_RH / 100.0
    return max(0.0, min(1.0, head / ref))


def _fog_liters(env: EnvContext, cmd_pct: float, profile=None):
    """사이클당 **증발하는** 분무 리터. 유량을 모르면 None.

    유량은 `capacity_meta['fog_flow_lpm']` 하나만 본다 — 그 액추에이터의 노즐
    중 드립이 아닌 것들의 합(`sprinkler_flow_lph`/60)이고, 프로필 로더가
    노즐 정보가 있을 때만 넣는다.

    **`irrigation_flow_lpm` 을 쓰지 않는다.** 그 값은 투여량 환산용이라
    (1) 뿌리로 가는 드립을 포함하고 (2) 액추에이터 값이 없으면 시설 합계로
    폴백한다. 2026-08-20 로컬 육묘장에서 노즐이 없는 분무기가 그 폴백으로
    시설 전체 관수 216 L/min(드립 에미터 324개)을 받아, 9448 m³ 온실에서
    증발냉각 **45.6 °C/사이클** 이 나왔다. 결합 drive 에서 이 한 항의 가중치가
    나머지의 20배가 되면서 다른 축이 전부 무의미해졌다.

    모르면 **지어내지 않고 None** 을 돌려준다. 호출부는 그때 보수적 K 상수로
    떨어진다 — 없는 유량을 참조값으로 메우면 그 값이 실측처럼 흘러다닌다.
    """
    cap  = getattr(profile, 'capacity_meta', None) or {}
    flow = float(cap.get('fog_flow_lpm') or 0.0)
    if flow <= 0.0:
        return None
    cycle = float(env.get('cycle_sec', _CYCLE_REF_S) or _CYCLE_REF_S)

    # ── 펄스 도징이면 사이클 전체가 아니라 1회 분무 시간만 뿌린다 ────────────
    # 습윤형 분무기는 `PulseDosingAdapter` 가 1회 가동을 `max_on_sec` 로 끊는다
    # (기본 30초, 육묘 모드 20초). 그런데 이 계산은 `cycle_sec`(기본 600초)로
    # 곱하고 있었다 — **결정하는 쪽과 실제 뿌리는 쪽이 분무 시간을 다르게 안
    # 상태**이고, 그 배율이 그대로 효과 과대평가가 된다(600/30 = 20배).
    #
    # 2026-08-20 육묘장 사고 기록에 "그 한 값이 결합 drive 가중치를 20배로
    # 지배했다" 고 적혀 있는데, 그때 고친 것은 유량 출처(`fog_flow_lpm` 분리)
    # 였고 지속 시간은 남아 있었다. 실측(2026-08-25 イチゴ, 164 L/min ·
    # 5,463 m³): 명령 100% 에서 ΔT −219.7 °C/사이클.
    #
    # 정본은 `CmdConstraints` 하나다 — capacity_meta 에 값을 복사해 두면
    # 두 벌이 되고 갈라진다. 펄스가 꺼진 장치(고압 미세포그)는 max_on_sec 이
    # 0 이라 종전대로 사이클 전체로 돈다.
    cc     = getattr(profile, 'cmd_constraints', None)
    max_on = float(getattr(cc, 'max_on_sec', 0.0) or 0.0)
    run_sec = min(cycle, max_on) if max_on > 0.0 else cycle

    sprayed = flow * run_sec * (cmd_pct / 100.0) / 60.0

    # ── 공기가 받아들일 수 있는 양을 넘길 수 없다 ──────────────────────────
    # `_evaporation_availability` 는 비율이라 총량을 막지 못한다. 여기서 자른다.
    cap_l = _absorbable_liters(env, float(cap.get('volume_m3') or 0.0))
    return min(sprayed, cap_l)


def fogger_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """분무 → 증발 → RH 상승.

    우선순위: 캘리브레이션 K → 노즐 유량 기반 물리 → 보수적 K 상수.
    어느 경로든 마지막에 증발 가용도(`_evaporation_availability`)를 곱한다 —
    포화 공기에서는 분무해도 RH 가 오르지 않는다.
    단순화: ΔRH ≈ liters × 1000g × (100 / volume_m3) × RH_per_g/m3
    volume_m3 미설정 시 _VOLUME_REF_M3 사용.
    """
    avail = _evaporation_availability(env)
    if avail <= 0.0:
        return EffectResult('0', 0.0)

    k_cal = _calibrated_k(profile, 'humidity', 0.0)
    if k_cal > 0.0:
        # 캘리브레이션 값 우선
        return EffectResult('↑', k_cal * (cmd_pct / 100.0) * avail)

    liters = _fog_liters(env, cmd_pct, profile)
    if liters is None:
        # 노즐 유량 미상 — 물리 계산 불가. 보수적 기본 계수로 떨어진다.
        return EffectResult('↑', K_FOG_RH * (cmd_pct / 100.0) * avail)

    cap      = getattr(profile, 'capacity_meta', None) or {}
    vol      = float(cap.get('volume_m3') or 0.0) or _VOLUME_REF_M3
    # 1 L = 1000 g → 수증기량(g/m³) 증가 → RH 변환 (포화수증기량 기준 약 1% per 0.2 g/m³ @20°C)
    # 실용적 근사: ΔRH ≈ liters × 1000 / vol × 0.5
    delta_rh = liters * 1000.0 / vol * 0.5
    return EffectResult(
        '↑', max(delta_rh, K_FOG_RH * (cmd_pct / 100.0) * 0.1) * avail)


def fogger_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """증발냉각으로 온도 하락.

    우선순위: 캘리브레이션 K → 노즐 유량 기반 물리 → 보수적 K 상수.
    어느 경로든 마지막에 증발 가용도(`_evaporation_availability`)를 곱한다 —
    증발하지 않은 물은 잠열을 가져가지 않는다(표면만 젖는다).
    ΔT = -(liters × _L_VAP_KJ_KG) / (volume_m3 × _RHO_CP_AIR)
    """
    avail = _evaporation_availability(env)
    if avail <= 0.0:
        return EffectResult('0', 0.0)

    k_cal = _calibrated_k(profile, 'temperature', 0.0)
    if k_cal > 0.0:
        return EffectResult('↓', k_cal * (cmd_pct / 100.0) * avail)

    liters = _fog_liters(env, cmd_pct, profile)
    if liters is None:
        return EffectResult('↓', K_FOG_T * (cmd_pct / 100.0) * avail)

    cap    = getattr(profile, 'capacity_meta', None) or {}
    vol    = float(cap.get('volume_m3') or 0.0) or _VOLUME_REF_M3
    delta_t = liters * _L_VAP_KJ_KG / (vol * _RHO_CP_AIR)
    return EffectResult(
        '↓', max(delta_t, K_FOG_T * (cmd_pct / 100.0) * 0.1) * avail)


FOGGER_EFFECT_MODEL = {
    'temperature': fogger_temp_effect,
    'humidity':    fogger_humid_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# 난방기 (heater)
# ─────────────────────────────────────────────────────────────────────────────

def heater_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    k = _calibrated_k(profile, 'temperature', K_HEATER_T)
    return EffectResult('↑', k * (cmd_pct / 100.0))


def heater_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """온도 상승 → 같은 절대습도에서 RH 하락."""
    k = _calibrated_k(profile, 'humidity', K_HEATER_RH)
    return EffectResult('↓', k * (cmd_pct / 100.0))


HEATER_EFFECT_MODEL = {
    'temperature': heater_temp_effect,
    'humidity':    heater_humid_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# CO₂ 주입기 (co2_injector)
# ─────────────────────────────────────────────────────────────────────────────

def co2_injector_co2_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    return EffectResult('↑', K_CO2_INJ * (cmd_pct / 100.0))


CO2_INJECTOR_EFFECT_MODEL = {
    'co2': co2_injector_co2_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# 차광막·보온커튼 (shade / curtain)
# ─────────────────────────────────────────────────────────────────────────────

def shade_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """차광막: 개도(100%=열림)에 따른 일사 유입 → 온도 상승.

    장치 규약상 cmd_pct 는 '개도'다(100=열림=빛 완전 유입, 0=닫힘=차광).
    따라서 열수록(개도↑) 일사가 들어와 온도가 오른다(↑). 닫으면(0%) 차광되어
    효과 0. 일사가 없으면(야간·흐린 날·센서 미설치 solar=0) 효과 0.
    """
    af, _ = _gis_factor(profile, use_u=False)
    solar  = env.get('solar') or 0.0
    solar_factor = min(max(solar / SOLAR_REFERENCE_W, 0.0), 2.0)
    return EffectResult('↑', K_SHADE_T * (cmd_pct / 100.0) * af * solar_factor)


def curtain_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """보온커튼: 개도(100%=열림/걷힘)에 따른 외피 열교환.

    장치 규약상 cmd_pct 는 '개도'다(100=열림=단열 없음, 0=닫힘=보온).
    걷으면(개도↑) 단열이 사라져 내부 온도가 외기 쪽으로 끌린다(전도/복사 손실,
    약한 환기와 유사하나 풍속 무관·계수 작음). 닫으면(0%) 외피가 단열되어 효과 0.
    """
    delta = env.get('T_ext', 0.0) - env.get('T_int', 0.0)
    if abs(delta) < 0.5:
        return EffectResult('0', 0.0)
    af, _ = _gis_factor(profile, use_u=False)
    k = _calibrated_k(profile, 'temperature', K_CURTAIN_U)
    return EffectResult('↑' if delta > 0 else '↓',
                        abs(delta) * (cmd_pct / 100.0) * k * af)


SHADE_EFFECT_MODEL = {
    'temperature': shade_temp_effect,
}

CURTAIN_EFFECT_MODEL = {
    'temperature': curtain_temp_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# 보광등 (lighting)
# ─────────────────────────────────────────────────────────────────────────────

K_LIGHT_PPFD = 200.0   # µmol/m²/s per cycle at 100%


def lighting_light_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    return EffectResult('↑', K_LIGHT_PPFD * (cmd_pct / 100.0))


LIGHTING_EFFECT_MODEL = {
    'light': lighting_light_effect,
}


# ─────────────────────────────────────────────────────────────────────────────
# P3-1: fan 계열 효과 함수
# ─────────────────────────────────────────────────────────────────────────────
# 순환팬: 균질화 효과 (T/RH 구배 해소). 에너지 투입은 없음 — 효과 크기는 작음.
K_CIRC_FAN_T   = 0.3   # °C/cycle at 100% (T 불균일 완화)
K_CIRC_FAN_RH  = 0.5   # %/cycle at 100%

# 배기팬: ACH 기반. capacity_meta['rated_m3h'] (m³/h) + volume_m3 필요.
K_EXHAUST_FAN_FACTOR = 1.0   # 경험적 보정 계수 (추후 캘리브레이션)


def circulation_fan_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """순환팬 → 내부 T 구배 완화 (미미한 효과)."""
    return EffectResult('~', K_CIRC_FAN_T * (cmd_pct / 100.0))


def circulation_fan_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    return EffectResult('~', K_CIRC_FAN_RH * (cmd_pct / 100.0))


CIRCULATION_FAN_EFFECT_MODEL = {
    'temperature': circulation_fan_temp_effect,
    'humidity':    circulation_fan_humid_effect,
}


def _exhaust_ach(cmd_pct: float, profile) -> float:
    """ACH (Air Changes per Hour) = rated_m3h × cmd/100 / volume_m3."""
    meta = getattr(profile, 'capacity_meta', {}) or {}
    rated = float(meta.get('rated_m3h', 0.0) or 0.0)
    volume = float(meta.get('volume_m3', 0.0) or 0.0)
    if rated <= 0 or volume <= 0:
        return 0.0
    return rated * (cmd_pct / 100.0) / volume


VENT_PRESSURE_F0 = 0.25  # 개구부 평균 개도가 이 분율 이상이면 배기팬 압력차 소멸(무력).
                         # 덕트 없는 벽면 배기팬은 창이 닫혀 있어야 압력이 걸려 작동.


def _exhaust_pressure_factor(env: EnvContext) -> float:
    """덕트 없는 벽면 배기팬의 압력 유효도 [0,1].

    배기가 작동하려면 팬 반대편이 '작게' 열려 압력차가 생겨야 한다. 창이 활짝
    열리면(개도↑) 압력이 안 생겨 팬 주변 공기만 돌고 실질 배기가 0 이 된다.
    개구부 평균 개도(vent_open_frac)가 클수록 유효도가 0 으로 떨어진다.
    """
    frac = env.get('vent_open_frac', 0.0) or 0.0
    return max(0.0, 1.0 - frac / VENT_PRESSURE_F0)


def exhaust_fan_temp_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """배기팬 → 외내부 온도차 × ACH 기반 T 변화 (개구부 압력 유효도 반영)."""
    pf = _exhaust_pressure_factor(env)
    if pf <= 0.0:
        return EffectResult('0', 0.0)   # 창이 열려 압력 안 걸림 → 배기 무력
    ach = _exhaust_ach(cmd_pct, profile)
    delta_T = env.get('T_ext', 20.0) - env.get('T_int', 25.0)
    if ach <= 0:
        # rated_m3h 미설정 → 환기(구배 의존)로 근사. 무구배에 상수 효과를 주면
        # (구 K_CIRC_FAN_T 폴백) 무구배에도 큰 효과를 주장해 결합 drive 가 팬을
        # 헛돌리는 와인드업을 유발한다. 배기팬은 순환(내부혼합)이 아니라 환기이므로
        # 개구부와 동일하게 |ΔT|·K_OPENING_T 로 스케일한다.
        if abs(delta_T) < 0.5:
            return EffectResult('0', 0.0)
        return EffectResult('↑' if delta_T > 0 else '↓',
                            abs(delta_T) * (cmd_pct / 100.0) * K_OPENING_T * pf)
    mag = abs(delta_T) * ach * (1 / 60.0) * K_EXHAUST_FAN_FACTOR * pf
    return EffectResult('↑' if delta_T > 0 else '↓', mag)


def exhaust_fan_humid_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """배기팬 → 외내부 RH 차 × ACH 기반 RH 변화 (개구부 압력 유효도 반영)."""
    pf = _exhaust_pressure_factor(env)
    if pf <= 0.0:
        return EffectResult('0', 0.0)
    ach = _exhaust_ach(cmd_pct, profile)
    delta_rh = env.get('RH_ext', 60.0) - env.get('RH_int', 70.0)
    if ach <= 0:
        # rated_m3h 미설정 → 환기(구배 의존)로 근사 (temp 와 일관, VPD 유도 정확도)
        if abs(delta_rh) < 1.0:
            return EffectResult('0', 0.0)
        return EffectResult('↑' if delta_rh > 0 else '↓',
                            abs(delta_rh) * (cmd_pct / 100.0) * K_OPENING_RH * pf)
    mag = abs(delta_rh) * ach * (1 / 60.0) * K_EXHAUST_FAN_FACTOR * pf
    return EffectResult('↑' if delta_rh > 0 else '↓', mag)


def exhaust_fan_co2_effect(env: EnvContext, cmd_pct: float, profile=None) -> EffectResult:
    """배기팬 → CO₂ 희석 (실내 CO₂ > 외부 가정, 개구부 압력 유효도 반영)."""
    pf = _exhaust_pressure_factor(env)
    ach = _exhaust_ach(cmd_pct, profile)
    if ach <= 0 or pf <= 0.0:
        return EffectResult('~', 0.0)
    excess = max(0.0, _co2_excess(env))
    mag = excess * ach * (1 / 60.0) * K_EXHAUST_FAN_FACTOR * pf
    return EffectResult('↓', mag)


EXHAUST_FAN_EFFECT_MODEL = {
    'temperature': exhaust_fan_temp_effect,
    'humidity':    exhaust_fan_humid_effect,
    'co2':         exhaust_fan_co2_effect,
}

# 흡기팬: 배기팬과 동일 물리 모델 (보완 관계) — 별도 조율은 coordinator 에서 처리
INTAKE_FAN_EFFECT_MODEL = dict(EXHAUST_FAN_EFFECT_MODEL)


# ─────────────────────────────────────────────────────────────────────────────
# kind → 기본 effect_model 조회
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_EFFECT_MODELS = {
    'opening':          OPENING_EFFECT_MODEL,
    'cooler':           COOLER_EFFECT_MODEL,
    'heater':           HEATER_EFFECT_MODEL,
    'fogger':           FOGGER_EFFECT_MODEL,
    'co2_injector':     CO2_INJECTOR_EFFECT_MODEL,
    'shade':            SHADE_EFFECT_MODEL,
    'curtain':          CURTAIN_EFFECT_MODEL,
    'lighting':         LIGHTING_EFFECT_MODEL,
    'circulation_fan':  CIRCULATION_FAN_EFFECT_MODEL,
    'exhaust_fan':      EXHAUST_FAN_EFFECT_MODEL,
    'intake_fan':       INTAKE_FAN_EFFECT_MODEL,
}


def _inject_vpd(model: dict, kind: str = None) -> dict:
    """effect_model 에 'vpd' 키가 없고 T/RH effect 가 있으면 유도 VPD effect 추가.

    kind 를 넘겨야 두 가지가 갈린다.
      · 난방·냉방의 '열에 의한 RH 이동' 신고를 dea 에서 뺀다(`_THERMAL_RH_KINDS`)
      · 환기 계열에만 **도달 한계 클램프**를 건다(실외를 지나칠 수 없다).
        난방·냉방·분무에 걸면 폭염에 냉방이 실외 온도에서 멈춘다.
    kind 미상이면 신고를 그대로 수분으로 보고, 클램프는 걸지 않는다(보수적).
    """
    if 'vpd' not in model and ('temperature' in model or 'humidity' in model):
        model['vpd'] = make_vpd_effect(
            model.get('temperature'), model.get('humidity'),
            humid_is_moisture=(kind not in _THERMAL_RH_KINDS),
            vent_bounded=(kind in VENTILATING_KINDS),
        )
    return model


# 기본 모델 전체에 유도 VPD effect 주입 (VPD 직접 제어용)
for _kind, _m in DEFAULT_EFFECT_MODELS.items():
    _inject_vpd(_m, _kind)


def build_effect_model(kind: str, k: dict) -> dict:
    """build_effect_model 래퍼 — 결과에 유도 VPD effect 를 주입한다."""
    return _inject_vpd(_build_effect_model_raw(kind, k), kind)


def _build_effect_model_raw(kind: str, k: dict) -> dict:
    """
    kind 와 캘리브레이션 계수 k 로 effect_model 딕셔너리를 생성.

    k 에 K_* 키가 있으면 모듈 기본값을 오버라이드한다 (R2).
    k 가 빈 dict 이면 모듈 기본값 그대로 반환.

    Args:
        kind: ACTUATOR_KINDS 중 하나 ('cooler', 'heater', ...)
        k:    캘리브레이션 계수 dict  {'K_COOLER_T': 3.0, ...}

    Returns:
        effect_model dict  {var: EffectFn, ...}
    """
    if not k:
        return dict(DEFAULT_EFFECT_MODELS.get(kind, {}))

    # 계수 오버라이드가 있는 경우 클로저로 새 함수 생성
    # 모든 람다는 (env, pct, profile=None) 시그니처. opening/shade 는 GIS 가중 적용.
    if kind == 'opening':
        k_t   = k.get('K_OPENING_T',   K_OPENING_T)
        k_rh  = k.get('K_OPENING_RH',  K_OPENING_RH)
        k_co2 = k.get('K_OPENING_CO2', K_OPENING_CO2)

        def _t(env, pct, profile=None, _k=k_t):
            d = env.get('T_ext', 0) - env.get('T_int', 0)
            if abs(d) < 0.5:
                return EffectResult('0', 0.0)
            af, _u = _gis_factor(profile, use_u=False)
            return EffectResult('↑' if d > 0 else '↓', vent_reachable(
                abs(d) * (pct/100) * _k * _wind_boost(env) * af, d))

        def _rh(env, pct, profile=None, _k=k_rh):
            d = env.get('RH_ext', 0) - env.get('RH_int', 0)
            if abs(d) < 1.0:
                return EffectResult('0', 0.0)
            af, _u = _gis_factor(profile, use_u=False)
            return EffectResult('↑' if d > 0 else '↓', vent_reachable(
                abs(d) * (pct/100) * _k * _wind_boost(env) * af, d))

        def _co2(env, pct, profile=None, _k=k_co2):
            ex = _co2_excess(env)
            if ex <= 20:
                return EffectResult('0', 0.0)
            af, _u = _gis_factor(profile, use_u=False)
            return EffectResult('↓', vent_reachable(
                ex * (pct/100) * _k * af, ex))

        return {'temperature': _t, 'humidity': _rh, 'co2': _co2}

    elif kind == 'cooler':
        k_t  = k.get('K_COOLER_T',  K_COOLER_T)
        k_rh = k.get('K_COOLER_RH', K_COOLER_RH)
        return {
            'temperature': lambda env, pct, profile=None, _k=k_t:  EffectResult('↓', _k * (pct / 100)),
            'humidity':    lambda env, pct, profile=None, _k=k_rh: EffectResult('↑', _k * (pct / 100)),
        }
    elif kind == 'heater':
        k_t  = k.get('K_HEATER_T',  K_HEATER_T)
        k_rh = k.get('K_HEATER_RH', K_HEATER_RH)
        return {
            'temperature': lambda env, pct, profile=None, _k=k_t:  EffectResult('↑', _k * (pct / 100)),
            'humidity':    lambda env, pct, profile=None, _k=k_rh: EffectResult('↓', _k * (pct / 100)),
        }
    elif kind == 'fogger':
        k_rh = k.get('K_FOG_RH', K_FOG_RH)
        k_t  = k.get('K_FOG_T',  K_FOG_T)
        return {
            'humidity':    lambda env, pct, profile=None, _k=k_rh: EffectResult('↑', _k * (pct / 100)),
            'temperature': lambda env, pct, profile=None, _k=k_t:  EffectResult('↓', _k * (pct / 100)),
        }
    elif kind == 'co2_injector':
        k_co2 = k.get('K_CO2_INJ', K_CO2_INJ)
        return {
            'co2': lambda env, pct, profile=None, _k=k_co2: EffectResult('↑', _k * (pct / 100)),
        }
    elif kind == 'shade':
        k_t = k.get('K_SHADE_T', K_SHADE_T)

        def _shade_t(env, pct, profile=None, _k=k_t):
            # 규약: pct=개도(100=열림=빛 유입→온도↑). 일사 없으면 효과 0.
            af, _u = _gis_factor(profile, use_u=False)
            solar  = env.get('solar') or 0.0
            solar_factor = min(max(solar / SOLAR_REFERENCE_W, 0.0), 2.0)
            return EffectResult('↑', _k * (pct / 100) * af * solar_factor)

        return {'temperature': _shade_t}
    elif kind == 'curtain':
        k_t = k.get('K_CURTAIN_U', K_CURTAIN_U)

        def _curtain_t(env, pct, profile=None, _k=k_t):
            # 규약: pct=개도(100=걷힘=단열없음). 걷으면 외기로 열교환(↑/↓), 닫으면 0.
            delta = env.get('T_ext', 0.0) - env.get('T_int', 0.0)
            if abs(delta) < 0.5:
                return EffectResult('0', 0.0)
            af, _u = _gis_factor(profile, use_u=False)
            return EffectResult('↑' if delta > 0 else '↓',
                                abs(delta) * (pct / 100) * _k * af)

        return {'temperature': _curtain_t}
    elif kind == 'lighting':
        k_ppfd = k.get('K_LIGHT_PPFD', K_LIGHT_PPFD)
        return {
            'light': lambda env, pct, profile=None, _k=k_ppfd: EffectResult('↑', _k * (pct / 100)),
        }
    elif kind in ('circulation_fan', 'exhaust_fan', 'intake_fan'):
        # fan 계열은 k_override 없으면 DEFAULT_EFFECT_MODELS 그대로 사용
        return dict(DEFAULT_EFFECT_MODELS.get(kind, {}))
    else:
        return {}
