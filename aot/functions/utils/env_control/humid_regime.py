# coding=utf-8
"""과습 구간 — 공기가 포화에 가까우면 환기를 **수증기압**으로 판단한다 (2026-10-01).

## 왜 따로 다루는가

VPD 는 온도가 같이 움직이는 양이다. 실외가 더 따뜻하면 실외 공기가 **수분이 훨씬
많아도** 실외 VPD 가 더 높게 나온다. 그러면 VPD 기준의 환기 판단은 "열면 VPD 가
오른다" 고 읽고 창을 연다 — 실제로는 습한 공기를 들이는 일이다.

실측(2026-10-01 로컬):

    쿠마모토 03:20   실내 이슬점 13.5 °C · 실외 18.2 °C   VPD 는 실외가 더 높다(0.28 대 0.13)
    3포장 22~01시    실내 이슬점 13.3 °C · 실외 16.5 °C   같은 모양

둘 다 창이 열렸고, 쿠마모토는 그 창이 2시간 동안 8 → 21 % 로 천천히 올라갔다.
그 구간의 실내 습도는 93 % 라 VPD 는 0.1 kPa 대다 — RH 1 %p 가 0.02 kPa 라 센서의
정수 단위 잡음이 그대로 제어 신호가 된다.

## 규칙

  · 진입: VPD 가 `ENTER_VPD_KPA` 미만이거나 이슬점 여유가 `ENTER_MARGIN_C` 미만.
    나가는 문턱은 더 높다(`EXIT_*`) — 문턱 근처에서 구간이 깜빡이지 않게 한다.
  · 이 구간에서 환기는 **실외 이슬점이 실내보다 `RELIEF_DEW_GAP_C` 이상 낮을 때만**
    연다. 열려 있던 중이면 문턱이 절반이다(`RELIEF_KEEP_FRAC`) — 경계에서 여닫지 않는다.
  · 열어도 되는 경우에도 `CAP_PCT` 를 넘기지 않는다. 습기를 빼는 것이 목적이지
    환기로 온도·VPD 를 맞추는 것이 아니다. **단 열 손실이 작고 실외가 충분히 건조하면 상한을 푼다**
    (`relief_cap_pct`, 아래 '상한 풀기').
  · 실외가 더 습하면 창으로는 해소할 수 없다 — 그 창은 닫는 쪽으로 간다(파킹).
    난방·제습 장치가 있으면 그쪽이 맡는다.
  · **실외가 너무 차가우면 열지 않는다**(겨울 난방 중). 실외 이슬점은 훨씬 낮아 "습기를 뺀다"
    로 읽히지만, 온도차가 크면 열 손실과 저온 피해가 습기 제거보다 크다. 실내보다
    `MAX_COLD_DELTA_C` 넘게 차거나, **실내가 온도 기준선 이하**이거나 난방 요구(최저 온도 한계의
    `_force_heat` 포함)가 서 있는데 실외가 더 차가우면 닫는 쪽이다(온도가 이슬점 판단을 이긴다).
    기준선은 `temp_edge_c` 한 곳이 정한다 — 온도가 제어 목표면 목표 + 허용오차, **VPD 직접 모드면
    유도 범위의 아래 끝**(아래 '아침 습기 빼기'와 '과습 열림' 절).

## 과습 열림 — VPD 직접 모드의 기준선 (2026-10-14)

김제 2026-10-13 12:48~15:59: 실내 VPD 0.21~0.45 · RH 82~91 % 가 3시간 넘게 이어졌다. 실외는 기온이 거의
같고(차 ≤ 1.4 °C) 이슬점이 3~4 °C 낮아 열면 습기가 빠지는 조건이었는데 측창은 6~30 % 였고, 13:48 에는 근거
27(COLD)로 닫혔다(외기 21 °C). 이 모드의 유도 온도 목표는 지금 실내 + 0.6 × (VPD 를 맞추는 데 필요한 만큼)이라
습할수록 실내보다 더 앞서 간다. 그것을 '목표 근처 이하' 의 기준으로 쓰면 '실내 ≤ 목표 + 허용오차' 가 늘 참이
되어 실외가 1 °C 만 차가워도 COLD 였다. 아침 습기 빼기가 먼저 겪은 같은 함정이라 **기준선 정의를 한 함수**
(`temp_edge_c`)로 모았다. 같은 이유로 유도 목표에서 나온 '난방 요구' (`_demand == 'heat'`) 도 이 판정에는 쓰지 않는다
— 온도가 제어 목표인 모드에서는 어차피 기준선 이하에 포함되고(허용오차 > 0), VPD 직접 모드에서는 유도 목표에서
나온 가짜 요구이기 때문이다.

## 상한 풀기 (2026-10-14)

`CAP_PCT` 의 뜻은 "열어서 온도·VPD 를 맞추지 않는다" 였다. 그러나 실외가 **거의 같은 온도이고 더 건조**하면
더 열수록 습기가 더 빠지고 열 손실은 늘지 않는다. 그 조건이면 상한을 푼다(`relief_cap_pct`):

    열 손실이 작다   실외 ≥ 실내 − `CAP_LIFT_MAX_COLD_C`(2 °C)       더 열어도 온도가 거의 안 떨어진다
    실외가 충분히 건조 실내 이슬점 − 실외 이슬점 ≥ `CAP_LIFT_DEW_GAP_C`(3 °C)   열수록 빠지는 양이 크다 (플레인 문턱의 두 배)

이미 풀려 있었다면 문턱이 완화된다(경계에서 상한이 오르내리지 않게 — 온도 +1 °C, 이슬점 차 × `CAP_LIFT_KEEP_FRAC`).
실외가 그보다 차거나 덜 건조하면 지금처럼 `CAP_PCT` 다.

## 아침 습기 빼기 (근거 54, 2026-10-10)

해가 뜬 뒤 실내가 과습 구간인데 위 규칙이 **COLD 로 닫는** 때가 있다. 영양 육묘장(2026-10-10 07:00~09:30): 실내
RH 91 % · VPD 0.1~0.4 인 채 해로 9.5 → 22.9 °C 까지 데워지는 동안 천창·측창이 내내 0 % (근거 27). 실외는
더 건조했다(RH 90 → 58 %, 이슬점이 실내보다 10 °C 가까이 낮다). 난방 요구가 서 있고(실내가 목표 + 허용오차
이하) 실외가 1 °C만 더 차도 COLD 라서다. 그러나 해가 들면 그 열은 **공짜로 들어오는** 열이고, 몇 시간의 RH 90 %
이상은 잿빛곰팡이 같은 병의 조건이다. 관행도 해가 집을 데우기 시작하면 환기창을 **조금** 열어 밤새 쌓인 습기를
내보낸다.

    해가 있다     실외 일사(`solar_vent.solar_load` — 실측 → 맑은 하늘 × 구름비) ≥ `PURGE_SOLAR_ON_W`
                 (이력 `PURGE_SOLAR_OFF_W`). 밤에는 일사가 0 이라 낮에만 선다(야간 파킹 중인 창은 제외)
    과습이다      실내가 위의 과습 구간 안(진입/이탈 이력은 구간 것을 그대로 쓴다 — 문턱을 따로 두지 않는다)
    열면 빠진다   실내 이슬점 − 실외 이슬점 ≥ `PURGE_DEW_GAP_C` (켜진 뒤엔 절반) — 수증기압 기준이라 실외가
                 따뜻해 VPD 가 높아도 습기를 들이는 창은 열지 않는다
    열 손실이 작다 실내가 온도 하한 아래 `PURGE_NEAR_BELOW_C` 안이면 그냥, 그보다 더 아래
                 `PURGE_FAR_BELOW_C` 까지는 **오르는 중일 때만**, 그 아래·강제 난방(최저 온도 한계의 래치
                 `_force_heat`)이면 안 연다. 하한 아래에서 떨어지는 중이어도, 실외가 `PURGE_MAX_COLD_DELTA_C`
                 넘게 차도 안 연다. 하한은 `temp_edge_c` — 온도가 제어 목표면 목표 − 허용오차이고, **VPD 직접 모드면 유도
                 범위의 아래 끝**이다 — 유도 온도 목표는 지금 실내 + 0.6 × (VPD 를 맞추는 데 필요한 만큼)이라
                 늘 실내보다 앞서 가고 습할수록 더 멀어져서(영양 2026-10-10: 실내 15.8 → 18.5, 20.8 → 22.7),
                 하한으로 쓰면 가장 습한 때 '너무 춥다' 로 막힌다.

넷이 서면 환기 장치에 **작은 열림 하한**(`PURGE_MIN_PCT` ~ `PURGE_MAX_PCT`)을 건다 — 습도 초과와 일사가 클수록
크고, 하한선 아래에서는 최소만 연다. 습기를 빼는 것이 목적이라 온도·VPD 를 맞추려 더 열지 않는다(그건 PI 와
일사 환기의 몫). 실내가 과습 구간을 나가면 풀린다.

⚠ 오르는 중인지는 **사이클 간 변화**로 잰다(`PurgeState.dT_h`). 상황 보고의 `T_trend` 는 5분 창이라 600초
주기 시설에서는 점이 하나뿐이라 늘 0 이다 — 그것으로 재면 '오르는 중' 이 영영 서지 않는다.

## 이 모듈이 하지 않는 것

온도 비상(`_force_cool`)·온도 상한 항이 서 있으면 이 구간을 **적용하지 않는다** —
호출부(`coordinator.decide_parking`)가 거른다. 덥고 습한 날의 환기는 습도가 아니라
온도가 요구한다.
"""
# @manual ai/env-control#humid-zone
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aot.utils import psychro

# 진입/이탈 문턱 — 들어가는 쪽이 낮고 나오는 쪽이 높다.
ENTER_VPD_KPA = 0.30
EXIT_VPD_KPA = 0.40
# 이슬점 여유(온도 − 이슬점) 문턱 — **정의는 여기 하나다**. 야간 파킹의 결로 탈출구
# (`_helpers_mixin.condensation_escape`)도 같은 문턱을 import 해 쓴다(2026-10-09):
# 둘 다 "공기가 포화에 가깝다" 를 묻는 같은 질문이라 따로 적으면 한쪽만 바뀌어 어긋난다.
ENTER_MARGIN_C = 2.0        # 온도 − 이슬점. 20 °C 에서 RH ≈ 88 %
EXIT_MARGIN_C = 3.0

# 실외 이슬점이 이만큼 낮아야 "환기가 습기를 뺀다" 고 본다.
RELIEF_DEW_GAP_C = 1.5
RELIEF_KEEP_FRAC = 0.5      # 이미 열려 있으면 이 비율로 완화(경계 깜빡임 방지)

# 과습 구간에서 허용하는 최대 개도(%).
CAP_PCT = 30.0
# 상한을 푸는 조건(`relief_cap_pct`, 2026-10-14 김제). 상한의 뜻은 "열어서 온도·VPD 를 맞추지 않는다" 이지 "습기를
# 덜 뺀다" 가 아니다. 열 손실이 작고(실외 ≥ 실내 − 2 °C: 완전히 열어도 실온이 외기보다 2 °C 이상 떨어질 수 없다)
# 실외가 충분히 건조하면(이슬점 차 3 °C = 플레인 문턱 1.5 의 두 배 — 열수록 빠지는 양이 분명히 큰 때) 더 열수록 습기가
# 더 빠진다. 김제 2026-10-13: 외기 19~22 °C 로 실내와 ≤ 1.4 °C 차, 이슬점 3~4 °C 낮음 — 이 조건.
CAP_LIFT_MAX_COLD_C = 2.0
CAP_LIFT_DEW_GAP_C = 3.0
CAP_LIFT_KEEP_FRAC = 0.67   # 이미 풀려 있으면 이슬점 차 문턱 3 → 2 °C · 온도 문턱 +1 °C (경계 깜빡임 방지)
CAP_LIFT_KEEP_COLD_C = 1.0
CAP_FREE_PCT = 100.0        # 상한 없음

# 실외가 실내보다 이만큼 넘게 차가우면 환기로 습기를 빼지 않는다(°C). 외기를 10 % 섞어도
# 실온이 0.8 °C 떨어지는 크기다 — 난방 중인 겨울 온실이 창을 열어 열을 버리는 것을 막는다.
MAX_COLD_DELTA_C = 8.0
# 난방 요구가 서 있을 때는 실외가 이만큼만 더 차가워도(°C) 열지 않는다.
HEAT_DEMAND_COLD_DELTA_C = 1.0


def dewpoint_c(T: Optional[float], RH: Optional[float]) -> Optional[float]:
    """이슬점(°C). 모르면 None."""
    if T is None or RH is None or RH <= 0.0:
        return None
    return psychro.dewpoint(psychro.vapor_pressure(float(T), float(RH)))


def vpd_kpa(T: Optional[float], RH: Optional[float]) -> Optional[float]:
    if T is None or RH is None:
        return None
    return psychro.svp(float(T)) * (1.0 - float(RH) / 100.0)


def in_overhumid_zone(T_in, RH_in, was_in: bool = False) -> bool:
    """실내가 과습 구간인가. 실내를 모르면 False(구간을 지어내지 않는다)."""
    if T_in is None or RH_in is None:
        return False
    v = vpd_kpa(T_in, RH_in)
    td = dewpoint_c(T_in, RH_in)
    if v is None or td is None:
        return False
    margin = float(T_in) - td
    if was_in:
        # 나가려면 **둘 다** 회복돼야 한다.
        return v < EXIT_VPD_KPA or margin < EXIT_MARGIN_C
    return v < ENTER_VPD_KPA or margin < ENTER_MARGIN_C


def dew_gap_c(T_in, RH_in, T_out, RH_out) -> Optional[float]:
    """실내 이슬점 − 실외 이슬점(°C). 양수면 실외가 **더 건조**하다. 모르면 None."""
    td_in = dewpoint_c(T_in, RH_in)
    td_out = dewpoint_c(T_out, RH_out)
    if td_in is None or td_out is None:
        return None
    return td_in - td_out


def temp_edge_c(t_real, t_guide_low, upper: bool = False) -> Optional[float]:
    """온도 기준선(°C) — '실내가 온도 쪽에서 더 식힐 이유가 없는 곳' 을 가르는 선. **정의는 여기 하나다.**
    과습 열림 판정(`coordinator.decide_parking` 2.65 의 `_warm_side`)과 아침 습기 빼기의 온도 하한(2.95)이 같이 쓴다.

    · 온도가 제어 목표면(`t_real`: value·tolerance 를 가진 TargetVar) 목표 ∓ 허용오차 — `upper=False` 면
      아래 선(목표 − 허용오차), `upper=True` 면 위 선(목표 + 허용오차). 과습 열림의 '목표 근처 이하'
      는 위 선이었고 그대로다. 아침 습기 빼기의 하한은 아래 선이다.
    · **VPD 직접 모드면 온도가 제어 목표에 없다**(`t_real` 없음). 유도 온도 목표는 지금 실내 + 0.6 × (VPD 를
      맞추는 데 필요한 만큼)이라 늘 실내보다 앞서 가고 습할수록 더 멀다 — 그것을 기준으로 쓰면 '실내 ≤ 목표 +
      허용오차' 가 늘 참이다. 그때는 유도 범위의 아래 끝(`t_guide_low`, 하드 최저로 좁힌 뒤)이 기준선이며
      위·아래 선의 구분이 없다.
    모르면 None(선을 지어내지 않는다).
    """
    if t_real is not None:
        tol = float(getattr(t_real, 'tolerance', 0.0) or 0.0)
        return float(t_real.value) + (tol if upper else -tol)
    return None if t_guide_low is None else float(t_guide_low)


def temp_band_c(t_real, t_guide_low, t_guide_high) -> tuple:
    """온도 기준 **띠** `(아래 선, 위 선)`(°C) — `temp_edge_c` 의 두 선을 한 번에. 스크린 판단(보온커튼 밤 닫기·틈)이 쓴다.

    · 온도가 제어 목표면 목표 − 허용오차 / 목표 + 허용오차 — `temp_edge_c` 의 두 선 그대로다.
    · **VPD 직접 모드면 유도 범위의 아래·위 끝**(`t_guide_low`·`t_guide_high`) — 유도 온도 목표(`_temperature_constraint`)
      ± 허용오차를 쓰지 않는다. 그 목표는 VPD 를 맞추려고 실내보다 앞서 가는 값이라(습하면 위로, 건조하면 아래로) 띠가
      실내를 따라 움직여 '춥다'(습할 때)·'덥다'(건조할 때) 가 늘 참이다. 아래 선은 `temp_edge_c` 와 같은 값(유도 하한)이다.
    모르는 선은 None(지어내지 않는다).
    """
    if t_real is not None:
        return temp_edge_c(t_real, t_guide_low), temp_edge_c(t_real, t_guide_low, upper=True)
    return (None if t_guide_low is None else float(t_guide_low),
            None if t_guide_high is None else float(t_guide_high))


def warm_side(t_now, t_real, t_guide_low, force_heat: bool = False) -> bool:
    """'보온이 필요한 쪽' — 난방 요구(`_force_heat`)가 서 있거나 실내가 온도 기준선(`temp_edge_c`, 위 선) 이하.

    `relief_verdict`·`condensation_escape` 의 `heat_demand` 로 넘어가 '실외가 `HEAT_DEMAND_COLD_DELTA_C` 넘게 차면
    열지 않는다' 를 가른다. **과습 열림(`coordinator.decide_parking` 2.65)과 야간 결로 탈출(`_night_vent_decide`)이
    같은 함수를 쓴다** — 유도 온도 목표(`_temperature_constraint`)를 기준으로 삼으면 VPD 직접 모드에서 늘 참이 되는
    함정이 두 군데 다 있었다. `t_real` 은 'temperature' 제어 목표(없으면 None — `_temperature_constraint` 를 넘기지 말 것).
    실내 온도나 기준선을 모르면 `force_heat` 만 본다.
    """
    if force_heat:
        return True
    edge = temp_edge_c(t_real, t_guide_low, upper=True)
    return t_now is not None and edge is not None and float(t_now) <= edge


# 난방 출력 상한 — 유도 범위 상한에 닿기 이만큼(°C) 앞에서부터 선형으로 줄여 상한에서 0 이 된다.
HEAT_CAP_BAND_C = 1.0


def heat_cap_pct(t_now, t_real, t_guide_low, t_guide_high, force_heat: bool = False) -> Optional[float]:
    """VPD 직접 모드의 난방 출력 상한(%) — 실내가 유도 범위 상한(`temp_band_c` 의 위 선)에 가까울수록 낮아지고 상한 이상이면 0.

    VPD 를 올리려고(공기를 말리려고) 데우는 일은 **유도 범위 안에서만** 한다. 온도가 제어 목표가 아니라서 난방기가
    받는 요구는 VPD 하나이고, 맞서는 짝 파킹(`decide_parking` 2.55)은 유도 목표 + 허용오차를 넘어야 서는데 유도 목표가
    유도 범위 상한으로 잘려 있어 실제 문턱이 상한 + 허용오차다 — 해 진 뒤 낮 VPD 목표가 천천히 내려오는 동안 실내가 상한을 1~3 °C
    넘는데 난방기는 80~100 % 로 돌고 열린 커튼으로 버렸다(폐루프 recorded/screens_heated 18~21 시: 난방 kWh +7 %).
    상한은 `temp_band_c` 의 위 선 — 과습 열림·야간 결로 탈출·스크린 판단과 같은 정의다.

    · 온도가 제어 목표면(`t_real`) None — 그때는 목표 + 허용오차가 제어 항으로 이미 난방기를 멈춘다(종전과 같다).
    · `force_heat`(최저 온도 한계)이면 None — 하드 한계가 이긴다. 실내나 상한을 모르면 None(상한을 지어내지 않는다).
    """
    if force_heat or t_real is not None or t_now is None:
        return None
    hi = temp_band_c(t_real, t_guide_low, t_guide_high)[1]
    if hi is None:
        return None
    return 100.0 * max(0.0, min(1.0, (float(hi) - float(t_now)) / HEAT_CAP_BAND_C))


def relief_cap_pct(T_in, RH_in, T_out, RH_out, was_lifted: bool = False) -> float:
    """과습 구간에서 열어도 되는 때(`relief_verdict` 가 OK)의 열림 상한(%): `CAP_PCT` 또는 `CAP_FREE_PCT`.

    실외가 거의 같은 온도 이상이고(≥ 실내 − `CAP_LIFT_MAX_COLD_C`) 충분히 건조하면(이슬점 차 ≥
    `CAP_LIFT_DEW_GAP_C`) 상한을 푼다 — 모듈 머리말 '상한 풀기'. `was_lifted` 면 문턱이 완화된다.
    모르는 값이 있으면 종전대로 `CAP_PCT`(풀지 않는다).
    """
    if None in (T_in, RH_in, T_out, RH_out):
        return CAP_PCT
    gap = dew_gap_c(T_in, RH_in, T_out, RH_out)
    if gap is None:
        return CAP_PCT
    cold = CAP_LIFT_MAX_COLD_C + (CAP_LIFT_KEEP_COLD_C if was_lifted else 0.0)
    need = CAP_LIFT_DEW_GAP_C * (CAP_LIFT_KEEP_FRAC if was_lifted else 1.0)
    if float(T_in) - float(T_out) <= cold and gap >= need:
        return CAP_FREE_PCT
    return CAP_PCT


OK = 'ok'            # 열어도 된다(상한 CAP_PCT — 열 손실이 작고 실외가 충분히 건조하면 풀린다, `relief_cap_pct`)
WET = 'wet'          # 실외가 더 습하다 — 열면 습기를 들인다
COLD = 'cold'        # 실외가 너무 차다 — 열면 열을 버린다(난방 중·저온 위험)


def relief_verdict(T_in, RH_in, T_out, RH_out, was_open: bool = False,
                   heat_demand: bool = False) -> Optional[str]:
    """환기로 과습을 풀 수 있는가: OK / WET / COLD, 실외를 모르면 None.

    COLD 를 WET 보다 **먼저** 본다 — 겨울에는 실외 이슬점이 훨씬 낮아 WET 가 아니라서, 온도를
    안 보면 난방 중에 창이 열린다(2026-10-01 사용자 지적).
    """
    if T_in is None or T_out is None or RH_out is None or RH_in is None:
        return None
    drop = float(T_in) - float(T_out)
    if drop > MAX_COLD_DELTA_C * (1.0 + (0.25 if was_open else 0.0)):
        return COLD
    if heat_demand and drop > HEAT_DEMAND_COLD_DELTA_C:     # 목표 근처 이하·난방 요구
        return COLD
    gap = dew_gap_c(T_in, RH_in, T_out, RH_out)
    if gap is None:
        return None
    need = RELIEF_DEW_GAP_C * (RELIEF_KEEP_FRAC if was_open else 1.0)
    return OK if gap >= need else WET


def relief_allowed(T_in, RH_in, T_out, RH_out, was_open: bool = False,
                   heat_demand: bool = False) -> Optional[bool]:
    """`relief_verdict` 가 OK 인가. 실외를 모르면 None(판단하지 않는다)."""
    v = relief_verdict(T_in, RH_in, T_out, RH_out, was_open, heat_demand)
    return None if v is None else v == OK


# ─────────────────────────────────────────────────────────────────────────────
# 아침 습기 빼기 (근거 54) — 모듈 머리말 "아침 습기 빼기"
# ─────────────────────────────────────────────────────────────────────────────
# 재배자가 판단할 값이 아니다(옵션으로 내지 않는다).
PURGE_SOLAR_ON_W = 100.0      # 이 이상이면 해가 집을 데운다
PURGE_SOLAR_OFF_W = 70.0      # 켜진 뒤에는 이 아래로 와야 풀린다
PURGE_DEW_GAP_C = 2.0         # 실내 이슬점 − 실외 이슬점. 켜진 뒤엔 절반(`RELIEF_KEEP_FRAC`)
PURGE_NEAR_BELOW_C = 1.0      # 온도 하한 − 이만큼 위까지는 온도를 따지지 않고 연다
PURGE_FAR_BELOW_C = 3.0       # 이만큼 넘게 아래면 안 연다(켜진 뒤엔 +0.5 °C 완화)
PURGE_RISING_C_PER_H = 0.5    # 하한 아래 구간에서 '오르는 중' 의 문턱(켜진 뒤엔 0)
PURGE_FALLING_C_PER_H = -1.0  # 하한 아래에서 이보다 빨리 떨어지면 닫는다
PURGE_MAX_COLD_DELTA_C = 15.0  # 실외가 이보다 더 차면 안 연다(켜진 뒤엔 ×1.25)
PURGE_MIN_PCT = 5.0
PURGE_MAX_PCT = 15.0
PURGE_RH_REF = 85.0           # 습도 초과의 기준 — 이 위로 PURGE_RH_SPAN 만큼 가면 최대
PURGE_RH_SPAN = 10.0
PURGE_SOLAR_SPAN_W = 400.0    # 켬 문턱 위로 이만큼 가면 일사 몫이 최대
_TREND_BLEND = 0.5            # 사이클 간 온도 변화율의 평활(새 값 몫)


@dataclass
class PurgeState:
    """사이클을 넘는 이력 — 켜짐 여부, 직전 실내 온도, 평활한 온도 변화율(°C/h).
    `cycle_memory` 가 재시작을 넘긴다(`humid_zone` 과 같다) — 안 그러면 재시작 직후 한 사이클은 켬 문턱·추세 모름으로 읽는다."""
    on: bool = False
    T_prev: Optional[float] = None
    dT_h: Optional[float] = None


@dataclass
class PurgeDecision:
    active: bool = False
    pct: float = 0.0
    why_off: Optional[str] = None
    # 'unknown' | 'dry' | 'no_sun' | 'wet' | 'cold_out' | 'cold_in' | 'falling'

    def describe(self) -> str:
        if self.active:
            return '해가 들고 실내가 과습 — 실외가 더 건조해 환기창을 %.0f %% 까지 연다' % self.pct
        return '아침 습기 빼기 없음(%s)' % {
            'unknown': '실내·실외·일사·온도 하한 중 모르는 값', 'dry': '과습 구간 밖',
            'no_sun': '일사 부족', 'wet': '실외가 충분히 건조하지 않음',
            'cold_out': '실외가 너무 참', 'cold_in': '실내가 온도 하한보다 많이 낮음',
            'falling': '실내가 하한 아래에서 식는 중'}.get(self.why_off, '-')


def temp_trend_h(prev: Optional[PurgeState], T_in, cycle_sec) -> Optional[float]:
    """실내 온도 변화율(°C/h) — 직전 사이클의 실내 온도와의 차를 `cycle_sec` 로 나눠 평활한다.
    직전 값이나 실내를 모르면 None(지어내지 않는다)."""
    if T_in is None or prev is None or prev.T_prev is None:
        return None
    if not cycle_sec or float(cycle_sec) <= 0.0:
        return prev.dT_h
    new = (float(T_in) - prev.T_prev) / float(cycle_sec) * 3600.0
    return new if prev.dT_h is None else (
        _TREND_BLEND * new + (1.0 - _TREND_BLEND) * prev.dT_h)


# @manual ai/env-control#morning-purge
def morning_purge(T_in, RH_in, T_out, RH_out, solar_w, T_low, in_zone: bool,
                  prev: Optional[PurgeState] = None, force_heat: bool = False,
                  dT_h: Optional[float] = None) -> PurgeDecision:
    """아침 습기 빼기 판단 → `PurgeDecision`(모듈 머리말). 상태는 건드리지 않는다.

    `in_zone` 은 호출부가 구간 이력으로 이미 정한 과습 구간 여부, `prev.on` 은 직전 사이클에 켜져
    있었나(문턱 완화), `dT_h` 는 평활한 실내 온도 변화율(°C/h, 모르면 None).
    """
    was_on = bool(prev.on) if prev is not None else False
    num = lambda v: None if v is None else float(v)       # noqa: E731
    T_i, T_e, RH_i, RH_e = num(T_in), num(T_out), num(RH_in), num(RH_out)
    sol, low = num(solar_w), num(T_low)
    if None in (T_i, T_e, RH_i, RH_e, sol, low):
        return PurgeDecision(why_off='unknown')
    if not in_zone:
        return PurgeDecision(why_off='dry')
    if sol < (PURGE_SOLAR_OFF_W if was_on else PURGE_SOLAR_ON_W):
        return PurgeDecision(why_off='no_sun')
    gap = dew_gap_c(T_i, RH_i, T_e, RH_e)
    if gap is None:
        return PurgeDecision(why_off='unknown')
    if gap < PURGE_DEW_GAP_C * (RELIEF_KEEP_FRAC if was_on else 1.0):
        return PurgeDecision(why_off='wet')
    if T_i - T_e > PURGE_MAX_COLD_DELTA_C * (1.25 if was_on else 1.0):
        return PurgeDecision(why_off='cold_out')
    below = low - T_i                       # 양수 = 온도 하한 아래
    far = PURGE_FAR_BELOW_C + (0.5 if was_on else 0.0)
    if force_heat or below > far:
        return PurgeDecision(why_off='cold_in')
    if below > 0.0 and dT_h is not None and float(dT_h) <= PURGE_FALLING_C_PER_H:
        return PurgeDecision(why_off='falling')
    if below > PURGE_NEAR_BELOW_C:
        # 하한에서 멀다 — 해가 데우고 있을 때(오르는 중)만. 모르면 열지 않는다.
        need = 0.0 if was_on else PURGE_RISING_C_PER_H
        if dT_h is None or float(dT_h) < need:
            return PurgeDecision(why_off='cold_in')
    # 크기: 습도 초과와 일사로 5~15 %. 하한선 아래에서는 최소만.
    x_rh = min(1.0, max(0.0, (RH_i - PURGE_RH_REF) / PURGE_RH_SPAN))
    x_sun = min(1.0, max(0.0, (sol - PURGE_SOLAR_ON_W) / PURGE_SOLAR_SPAN_W))
    pct = PURGE_MIN_PCT + (PURGE_MAX_PCT - PURGE_MIN_PCT) * 0.5 * (x_rh + x_sun)
    if below > PURGE_NEAR_BELOW_C:
        pct = PURGE_MIN_PCT
    return PurgeDecision(active=True, pct=pct)
