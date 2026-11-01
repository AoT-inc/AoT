# coding=utf-8
"""습윤형 분무의 해 질 녘 제한 — 판정은 **이 모듈 한 곳**이다 (2026-10-10).

## 왜 있는가

습윤형 분무(아래 향 살수, 굵은 물방울)는 공중에서 증발하지 않고 잎·트레이에 내려앉는다. 젖은 면이
마르는 속도는 일사와 공기의 건조도가 정한다. 해가 약해지는 저녁에 뿌리면 잎이 마를 틈 없이 밤을
넘긴다 — 엽면 습윤 시간이 길수록 잿빛곰팡이·노균병 위험이 커진다.

실측(영양 육묘장, 개발서버 2026-10-10, 토마토 VPD 목표 1.0 kPa, `nursery_mode` 꺼짐): 분무기
"육묘장-분무"(습윤형)가 12:00 부터 17:00 까지 100 %(근거 1, VPD) 로 돌았다. 그동안 일사는 150 →
46 → 31 W/m² 로 떨어졌고 VPD 는 목표에 다가갔다(16:30 1.18 → 17:00 0.87, 일몰 17:54). 기존 저녁
차단(`nursery_evening_fog`)과 일소 잠금은 **육묘 모드에서만** 서므로 이 설치에는 걸리지 않았다.

## 규칙 (습윤형 분무기에만 — 고압 미세포그는 잎을 적시지 않아 대상이 아니다, `is_wetting_fogger`)

    약한 해    실외 일사 ≥ `WFD_SOLAR_FULL_W`(150) → 제한 없음
               `WFD_SOLAR_ZERO_W`(50) ~ 150 → 명령 × (일사 − 50) ÷ 100  (비례 감쇠)
               ≤ 50 → 0
    해 질 녘   일몰 − `WFD_CUTOFF_MIN`(90분) ~ 다음 일출 → 0 (일사와 무관 — 일사를 못 읽어도 선다)

둘 중 더 센 쪽이 이긴다. **분무를 켜는 쪽으로는 아무 것도 하지 않는다** — 습도 하한(`humid_min`)이
분무를 100 % 로 강제해 놓았어도 이 규칙이 그 뒤에서 깎는다(`apply_wetting_fog_dusk_limit` 은
온습도 임계 뒤). 모자라는 습도는 저녁에 환기·고압 분무의 몫이고, 습윤 분무로 채우는 것은 밤을 젖은
잎으로 넘기는 값이다.

## 일사의 출처

`solar_vent.solar_load` — 실측(차광 판정과 같은 `heat_protect._outdoor_solar`) → 맑은 하늘 × 구름비
→ 맑은 하늘 × `SV_UNMEASURED_CLOUD`. 좌표도 일사도 모르면 **None 이고 제한하지 않는다**(위치를
모른다고 정상 가습을 막지 않는다 — `_evening_fog_blocked` 와 같은 판단).

## 육묘 모드에서도 선다 — 구간만 육묘 옵션을 따른다 (2026-10-10 김제)

처음에는 `nursery_mode` 를 빼 두었다(자기 규칙이 있다고 보았다). 극한 날씨 시뮬레이션(`heatwave_tropical_night`,
김제 육묘장)이 그 가정을 깼다: 일소 잠금이 낮 내내 분무를 막다가 저녁에 풀리면 **해가 진 뒤에 습윤 분무가
돌아 작물이 밤마다 590분쯤 젖어 있었다.** 일소 잠금은 *강한* 해를 막고, 저녁 차단(`nursery_evening_fog`)은
기본이 "허용"이라 아무도 *약한* 해·밤을 막지 않았다. 그래서 육묘 모드도 같은 규칙을 받는다.

    일소 잠금·감쇠(근거 36)        그대로 — 강한 해(낮)를 맡는다. 이 규칙은 약한 해·저녁·밤을 맡는다.
    일사 비례 감쇠 150 → 50        육묘 모드도 같다.
    구간 시작                      육묘 모드: 일몰 − `nursery_evening_cutoff_min`(기본 120분). 아니면 90분.
    끄는 법                        `wetting_fog_dusk_stop` 끔 — 육묘 모드도 이 하나로 끈다.

`nursery_evening_fog`("일몰 전 분무 허용", 기본 켜짐)와의 관계 — 두 옵션이 서로 모순되지 않게:

    wetting_fog_dusk_stop 켜짐(기본)   저녁·밤 분무는 선다. `nursery_evening_fog` 는 **의미가 없다**
                                      (켜짐이어도 이 규칙이 세운다 — 기본값이라 명시한 선택과 구분되지 않는다).
                                      `nursery_evening_fog` 를 끄면 안전 게이트의 저녁 차단이 같은 구간
                                      (`nursery_evening_cutoff_min`)에서 겹쳐 서는 것뿐이다.
    wetting_fog_dusk_stop 꺼짐         종전 그대로 — `nursery_evening_fog` 가 저녁 분무를 정한다.

즉 `nursery_evening_fog` 는 이제 "이 규칙을 껐을 때만" 읽히는 옵션이고, 옵션 문구에 그렇게 적는다.
`nursery_evening_cutoff_min` 은 두 규칙이 **함께** 읽는다(구간 시작 하나).

상수는 재배자가 판단할 값이 아니다(옵션으로 내지 않는다). 켜고 끄는 스위치 하나만 옵션이다
(`wetting_fog_dusk_stop`, 기본 켜짐).
"""
# @manual ai/env-control#wetting-fog-dusk
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 상수 — 재배자가 판단할 값이 아니다(옵션으로 내지 않는다)
# ─────────────────────────────────────────────────────────────────────────────
WFD_SOLAR_FULL_W = 150.0   # 이 이상이면 제한 없음(일소 해제 문턱 `nursery_solar_release` 와 같은 값)
WFD_SOLAR_ZERO_W = 50.0    # 이 이하면 0 — 젖은 잎이 사실상 마르지 않는다
WFD_CUTOFF_MIN = 90.0      # 일몰 이만큼 전부터 일출까지 쉰다(육묘 모드가 아닌 설치의 값)
WFD_NURSERY_CUTOFF_DEFAULT_MIN = 120.0   # 육묘 모드의 기본 — `nursery_evening_cutoff_min` 옵션의 기본과 같다


@dataclass
class WettingFogDuskDecision:
    """한 사이클의 결론. 쓰는 곳은 이것만 읽는다."""
    scale: float = 1.0                 # 습윤형 분무 명령에 곱할 값 0…1
    why: Optional[str] = None          # 'dusk' | 'low_sun' | None(제한 없음)
    solar_w: Optional[float] = None
    cutoff_min: float = WFD_CUTOFF_MIN  # 쉬기 시작하는 일몰 전 분(알림 문구용)

    @property
    def limited(self) -> bool:
        return self.scale < 1.0

    def describe(self) -> str:
        if self.why == 'dusk':
            return '해 질 녘 — 일몰 %d분 전부터 일출까지 습윤형 분무는 쉼' % int(self.cutoff_min)
        if self.why == 'low_sun':
            return '일사 %.0f W/m² — 습윤형 분무 %.0f %% 로 제한' % (
                self.solar_w or 0.0, self.scale * 100.0)
        return '제한 없음'


def cutoff_minutes(nursery_mode: bool, nursery_cutoff_min=None) -> float:
    """쉬기 시작하는 일몰 전 분. 육묘 모드는 자기 옵션(`nursery_evening_cutoff_min`)을, 아니면 고정 90분.

    옵션이 비었거나 읽을 수 없으면 육묘 기본(120분). 0 이하는 0 — 일몰부터 쉰다.
    """
    if not nursery_mode:
        return WFD_CUTOFF_MIN
    if nursery_cutoff_min is None:
        return WFD_NURSERY_CUTOFF_DEFAULT_MIN
    try:
        return max(0.0, float(nursery_cutoff_min))
    except (TypeError, ValueError):
        return WFD_NURSERY_CUTOFF_DEFAULT_MIN


def solar_scale(solar_w: Optional[float]) -> float:
    """일사 → 분무 허용 비율 0…1. 일사를 모르면 1(제한하지 않는다)."""
    if solar_w is None:
        return 1.0
    span = WFD_SOLAR_FULL_W - WFD_SOLAR_ZERO_W
    return max(0.0, min(1.0, (float(solar_w) - WFD_SOLAR_ZERO_W) / span))


# @manual ai/env-control#wetting-fog-dusk
def evaluate_wetting_fog_dusk(solar_w: Optional[float], past_cutoff: bool,
                              cutoff_min: float = WFD_CUTOFF_MIN) -> WettingFogDuskDecision:
    """이번 사이클의 판단. `past_cutoff` = 지금이 (일몰 − `cutoff_min`) ~ 다음 일출인가(모르면 False)."""
    if past_cutoff:
        return WettingFogDuskDecision(scale=0.0, why='dusk', solar_w=solar_w, cutoff_min=cutoff_min)
    scale = solar_scale(solar_w)
    if scale < 1.0:
        return WettingFogDuskDecision(scale=scale, why='low_sun', solar_w=solar_w, cutoff_min=cutoff_min)
    return WettingFogDuskDecision(scale=1.0, why=None, solar_w=solar_w, cutoff_min=cutoff_min)
