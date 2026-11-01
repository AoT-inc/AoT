# coding=utf-8
"""낮 일사 부하 환기 — 판정과 정책은 **이 모듈 한 곳**이다 (2026-10-10).

## 왜 있는가

해가 드는 온실은 창을 닫으면 몇 분 만에 데워진다. 일사가 피복을 지나 작물·바닥을 데우고, 그 열을
빼는 길은 공기 교환뿐이다. 그런데 코디네이터는 환기의 효과를 **지금의** 안팎 차이로만 잰다:

    VPD 축   실외가 더 건조하다 → "열면 VPD 가 오른다" → 닫는다(근거 1, 주작용 vpd)
    온도 축  안팎 차가 1 °C 남짓 → 구동력이 문턱 아래 → 무구배(근거 15) → 닫힘으로 감쇠

실측(영양 육묘장, 개발서버 2026-10-10 12:45, 토마토 착과기 VPD 목표 1.0 kPa): 실내 28.7 °C ·
49 % · VPD 2.0(상승 중, +1.5 °C/h), 실외 27.6 °C · 40 % · VPD 2.2, 맑음. 천창·측창 0 %(근거 1·15),
분무 100 %. "VPD 가 높은데 창은 안 열고 닫고 분무만 한다". 두 판정 모두 물리적으로 틀렸다:

- 닫힌 온실은 일사로 계속 더워진다 — 그 열은 지금의 안팎 차이에 아직 나타나지 않았다.
- 분무의 증발냉각은 습해진 공기를 내보내야 이어진다. 분무 + 환기 + 차광이 함께 가는 수단이다.
- 작은 안팎 차이는 분무가 식혀서 생긴 것이다 — 장치가 만든 상태로 그 장치의 쓸모를 재는 고리
  (보온커튼 근거 49 · PR #108 과 같은 모양).

"습도를 지키려고 창을 닫는다" 는 **일사 열부하가 없을 때**(밤·흐림·서늘함)만 맞다.

## 규칙

    해가 있다   실외 일사(실측 → 맑은 하늘 × 구름비 → 맑은 하늘 × `SV_UNMEASURED_CLOUD`)
               ≥ `SV_SOLAR_ON_W`, 이력 `SV_SOLAR_OFF_W`
    덥다       실내 > 선 — 풀림은 그 선 − `SV_EXIT_MARGIN_C`, 단 선 뒤 `SV_MIN_ON_S`(30 분)는
               온도로 풀리지 않는다(`temperature_line`)
               선 = 온도 목표 + 허용오차(온도가 작물의 의도인 제어 목표일 때)
                  = min(유도 목표 + 허용오차, 작물 선)(VPD 직접 모드 — 유도 목표가 VPD 를 좇는다)
               작물 선 = 단계 온도 + 1 °C → 없으면 유도 범위 위쪽 1/3 지점, 보호 문턱 − 0.5 °C 이하
    바깥이     실외 > 실내 + `SV_HOT_OUTSIDE_C` 이면 걸지 않는다 — 환기가 열을 들인다
    더 덥지 않다

셋이 서면 환기 장치에 **열림 하한**을 건다. VPD·습도 항은 그 아래로 닫지 못한다 — 모자라는
습도는 분무(증발냉각과 가습을 함께)와 차광(`screen_policy` FREE/TRADE)이 맡는다.

    하한 = (SV_FLOOR_MIN_PCT + (SV_FLOOR_MAX_PCT − SV_FLOOR_MIN_PCT) × x) × w
      x = 초과분 ÷ (보호 문턱 − 선)   0…1   (보호 문턱 = `heat_protect` 문턱, 꺼졌으면 temp_max)
      w = SV_SOLAR_W_MIN + (1 − SV_SOLAR_W_MIN) × (일사 − ON) ÷ (SV_SOLAR_FULL_W − ON)   0.7…1

선 바로 위에서 15 %(약한 해면 10.5 %), 보호 문턱에서 80 %. 문턱 위에서는 x = 1 이라 극한 고온
보호(`heat_protect`)가 들어올 때 하한이 그대로 이어진다(보호 중에도 바깥이 더 덥지 않은 창에는
하한이 남는다 — 넘겨받는 순간 창이 계단으로 닫히지 않는다). 대상은 개구부, 개구부가 없으면 팬이다
(팬은 전기를 쓴다 — 창으로 뺄 수 있는 열을 팬으로 빼지 않는다).

## '덥다' 는 작물의 온도 의도로 정한다 — VPD 를 좇는 온도가 아니다 (2026-10-10)

VPD 직접 모드의 유도 온도 목표는 VPD 를 맞추려고 온도를 옮긴 값이다(`decompose_vpd_to_T_RH`). 습하면
VPD 를 올리려고 실내보다 위에 서고 실내를 따라 오른다. 폐루프 김제 `foehn_dry_wind` 이튿날: 밤새 강풍
게이트로 닫혀 집이 습했고(RH 58~73 %), 유도 목표가 실내보다 0.3~0.7 °C 위에서 26.75 → 32.0 °C 로 올라
(07:20~08:40) 하한이 90 분 늦게(08:50) 섰다 — 해가 닫힌 집을 데우는 동안(밤새 창이 열려 덜 습했던 강풍
게이트 전 코드 판은 07:20). 그래서 그 목표는 작물 선을 넘지 못한다(min). 건조해 유도 목표가 낮으면
종전처럼 그쪽이 선이다. 아침 습기 빼기(근거 54)가 VPD 직접 모드에서 유도 목표 대신 유도 하한
(`T_guide_low`)을 쓰는 것과 같은 판단이다 — 두 하한은 부딪치지 않는다(둘 다 하한이라 큰 쪽이 남는다).

## 효과 모델은 바꾸지 않는다 — 무구배(근거 15)는 하한이 맡는다

환기의 온도 효과를 "닫힌 채 일사가 만들 상승" 까지 세도록(실효 차 = max(실내 − 실외, 0.01 °C/(W/m²)
× 일사)) 바꿔 보았다. 폐루프(영양 DB, normal)에서 창이 **덜** 열렸다(해 있는 동안 평균 41 → 35 %,
왕복 0.93 → 1.15 회/h). PI 의 결합 오차는 항들의 가중 평균이라, 오차는 작은데(초과 0.5 °C ÷ 밴드 6 °C)
가중치만 커진 온도 항이 "더 열라" 는 VPD 항을 희석한다. 빼고 나니 normal 은 기준과 같고 hot_humid 의
개선(°C·min > 30 −7 %, 왕복 1.45 → 0.72)은 그대로였다. 그래서 일사가 있고 실내가 선 위인 구간의
무구배·VPD 닫기는 **하한이** 막고, 효과 모델은 그대로 둔다(MPC·greybox 와 같은 판단 — 동결).

## 위가 이긴다(하한을 걸지 않는다)

강우·강풍(안전 게이트) · 실외 모름(제자리, 2.6) · 강우·풍속 모름(더 열지 않음) · 야간 파킹 ·
파킹 직전 완충(근거 48) · 냉난방 연동 · 보호의 '바깥이 더 덥다'(근거 28) · 습도 하드 한계·온도
하드 한계(뒤에서 덮는다) · 수동 · 의심 장치. 하한이 이기는 것: VPD·습도 항, 무구배, 환기 무익,
과습 구간의 상한·파킹(열을 빼는 것이 먼저다), '열어도 반응 없음'.

## 쓰는 곳 — 결과를 **읽기만** 한다

    `_cycle_mixin._evaluate_solar_vent`  판단을 부르고 `situation.context['solar_vent']` 에 싣는다
    `coordinator.decide_parking`         하한을 걸 장치(`solar_floor_ids`)
    `coordinator.coordinate`             명령·적분을 하한에 묶는다(근거 51)

⚠ MPC(greybox)는 동결이라 이 하한을 모른다. 영양처럼 `effect_engine: shadow` 인 설치는 레거시 PI
  (`coordinate`)가 명령을 내므로 그대로 적용된다.
⚠ `SolarVentState` 는 재시작을 넘는다(`cycle_memory`) — 버리면 재시작 직후 첫 사이클이 이력 띠
  (150~200 W/m²) 안의 일사를 '해 없음' 으로 읽는다(영양 2026-10-10 14:14, 그 모듈 머리말).

## 실내를 모르는 맑은 낮 — 실외로 세우는 작은 하한 (2026-10-14, 근거 60)

위 하한은 '덥다' 를 **실내** 온도로 정한다. 실내 센서가 모두 끊기면(코디네이터 2.8, 근거 21 = 제자리)
하한도 함께 빠지고, 밤에 닫혀 있던 0 % 가 낮까지 끌려간다. 실측(2026-10-14): 07:29 실내 미러가 모두
끊겼고 김제 육묘장3 은 09:03~12:55 맑음·외기 19 °C·RH 25 % 인데 측창 0 %(근거 21), 구마모토는 일사
656 W/m² 인데 창 0 %. 닫힌 비닐집은 해 아래서 바깥보다 15~20 °C 더워진다 — 실제 온실이면 30~40 °C 다.
'모르니 움직이지 않는다' 가 맑은 낮에는 '닫아 둔다' 는 결정이 된다.

    실내 온도 모름 · 실외 실측 있음(지어낸 값 아님) · 해 있음(위와 같은 문턱 200/150 W/m² — 일사 센서가 없으면
    맑은 하늘 × `BLIND_UNMEASURED_CLOUD`(3/4), 이력은 이 판정의 것)
    · 외기 ≥ `BLIND_T_EXT_MIN_C`
    · 닫힌 집 어림 T_est = 외기 + `BLIND_SOLAR_RISE_C_PER_W`(0.02) × 일사 > 선(위 `temperature_line`, 이력 0.5 °C)
      → 하한 = BLIND_FLOOR_MIN_PCT + (MAX − MIN) × x,  x = (T_est − 선) ÷ (보호 문턱 − 선)  0…1
      → 외기 ≥ 보호 문턱이면 MIN 만(아래 ⚠)

코디네이터는 근거 21 로 제자리에 설 장치만 이 하한까지 **사이클당 `BLIND_STEP_PCT` %p 씩** 올린다(이미
더 열려 있으면 제자리 — 닫지 않는다). 해가 진 뒤(맑은 하늘 < 50 W/m², 근거 58 과 같은 선) 실내를 여전히
모르면 이 하한 이하로 열린 창을 같은 폭으로 0 까지 내린다. 실내가 돌아오면 다음 사이클부터 보통의 판정이다.
위가 이긴다(위 '위가 이긴다' 와 같은 집합 + 안전 게이트 · 강우 단계 · 서리 주의의 '더 열지 않음').

⚠ **외기가 극한 고온 문턱(기본 30 °C) 이상이면 닫지도, 키우지도 않는다 — 최소 하한만.** 근거:
  · 해 아래 닫힌 집은 언제나 바깥보다 덥다(현열 이득 0.02~0.03 °C/(W/m²)) — '바깥이 덥다' 는 닫을 근거가
    못 된다. 보호의 '바깥이 더 덥다'(근거 28)는 **실내를 재서** 분무·차광이 집을 바깥보다 식혀 둔 것을
    확인했을 때의 판정이다. 실내를 모르면 그 확인이 없다.
  · 그렇다고 크게 열 근거도 없다 — 분무·차광이 돌고 있었다면 실내가 바깥보다 시원할 수 있고, 그때 큰
    환기는 뜨거운 공기를 들인다. 최소 하한은 분무가 만든 습기를 빼 증발냉각을 잇는 몫(보호의 하한
    `HP_VENT_FLOOR_PCT` 와 같은 생각)이다.
"""
# @manual ai/env-control#solar-vent
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# 상수 — 재배자가 판단할 값이 아니다(옵션으로 내지 않는다)
# ─────────────────────────────────────────────────────────────────────────────
SV_SOLAR_ON_W = 200.0        # 이 이상이면 일사 열부하가 있다
SV_SOLAR_OFF_W = 150.0       # 있던 것은 이 아래로 와야 풀린다
SV_SOLAR_FULL_W = 800.0      # 이 이상이면 일사 가중 w = 1
SV_SOLAR_W_MIN = 0.7         # 문턱의 일사 가중
# 한 번 서면 해가 있는 동안 이만큼은 유지한다(최소값으로) — 온도로만 풀리게 두면 창이 한 사이클에 집을
# 1~2 °C 식혀 선 − 0.5 °C 아래로 내려가고, 닫히면 해가 다시 데워 다음 사이클에 또 선다(폐루프 김제
# recorded·normal, 10 분 켬/끔 반복). 닫힌 집은 해 아래서 몇 분이면 다시 더워진다 — 그 사이에 닫을 까닭이
# 없다. 해 없음·바깥이 더 덥다·실외 모름은 이 유지보다 앞선다(즉시 풀린다).
SV_MIN_ON_S = 1800.0
SV_EXIT_MARGIN_C = 0.5       # 선 − 이만큼 아래로 와야 하한이 풀린다
SV_HOT_OUTSIDE_C = 1.0       # 실외가 실내 + 이만큼보다 더우면 하한을 걸지 않는다
SV_FLOOR_MIN_PCT = 15.0      # 선 바로 위의 하한(일사 가중 전)
SV_FLOOR_MAX_PCT = 80.0      # 보호 문턱의 하한(일사 가중 전)
# 일사 센서가 없는 시설(김제 육묘장3 — 기상청 실외에 일사 채널이 없다)은 맑은 하늘 일사의 이만큼으로
# 어림한다. 흐린 날에는 과대지만 하한은 실내가 온도 목표 위일 때만 서고(흐린 날 그런 일은 드물다),
# 한낮 맑은 하늘(800~900 W/m²)의 절반이 문턱을 넘는다. 이것 없이는 센서 없는 시설에서 규칙이 영영
# 서지 않는다(폐루프 김제: 하한 0회). 좌표가 없으면(맑은 하늘을 모름) 판단하지 않는다.
SV_UNMEASURED_CLOUD = 0.5
_SPAN_MIN_C = 0.5            # 선과 보호 문턱이 붙어 있을 때 x 의 분모 하한
# 작물 선(`crop_line`) — VPD 직접 모드에서 '덥다' 를 정하는 작물의 온도 의도.
# 단계 온도의 허용오차. 온도 우선 모드의 목표 허용오차(`basis.T_TOL`)·VPD 모드의 온도 목표 허용오차
# (`_run_cycle` 의 T_tol)와 같은 값이다 — 단계가 있으면 어느 모드든 같은 선(단계 온도 + 1 °C)이 된다.
SV_CROP_TOL_C = 1.0
# 단계 온도가 없을 때 유도 범위에서 '덥다' 가 시작되는 자리(아래 끝에서 폭의 2/3). 시설 유도 범위는
# 낮·밤을 다 담는 울타리라(`GUIDE_BAND` 주석) 그 중앙(기본 12~32 → 22 °C)은 낮 작물의 의도로는 낮다 —
# 해 드는 아침 23 °C 에 창을 여는 것은 데우는 중인 집을 식히는 일이다. 위 끝(32 °C)은 보호 문턱(기본
# 30 °C)보다 높아 하한이 영영 서지 않거나 문턱 위에서 한 번에 80 % 로 튄다. 위쪽 1/3 지점(12~32 → 25.3,
# 22~32 → 28.7)은 낮의 따뜻한 쪽이 시작되는 자리이고, 단계 가이드(단계 ± 5)에서는 단계 + 1.7 °C 라
# 단계 선(단계 + 1)과 0.7 °C 안에서 맞는다.
SV_GUIDE_FRAC = 2.0 / 3.0

# ── 실내를 모르는 맑은 낮(근거 60, 머리말 마지막 절) ──────────────────────────────────────────────
# 닫힌 집이 일사로 바깥보다 더워지는 폭 [°C per W/m²]. 단동 비닐집 정상 상태 에너지 수지는 0.033 이다(현열로
# 남는 일사 τ 0.77 × (공기 0.30 + 바닥·작물 0.45 × (1 − 증산 0.45)) ≈ 0.42 ÷ 손실 UA ≈ 13 W/(바닥 m²·K) — 피복
# 6.5 W/m²K × 피복/바닥 1.9 + 누기 0.5 회/h). 그런데 열질량·증산이 오전의 상승을 늦춘다 — 폐루프 시설 모델(김제
# 육묘장3 치수, 맑은 가을 낮 7~20 °C, 창 닫음)에서 (실내 − 외기) ÷ 일사가 09시 0.011 · 12시 0.017 · 14시 0.020
# 이었다. 오후 값 0.02 를 쓴다: 실내가 선을 넘는 시각(모델 11시 26 °C)을 어림도 같은 때 넘는다(외기 15.7 +
# 0.02 × 665 = 29). 0.033 이면 10시(실제 21 °C)에 벌써 '덥다' 가 되어 데워지는 중인 집을 식힌다. 문헌의 닫힌
# 온실 15~25 K(일사 600~800 W/m²) 범위의 아래쪽이다.
BLIND_SOLAR_RISE_C_PER_W = 0.02
# 일사 센서도 구름비도 없으면 맑은 하늘의 이만큼으로 어림한다 — 일사 하한의 0.5(`SV_UNMEASURED_CLOUD`)보다
# 크게 둔다. 여기서는 과소 추정의 대가(맑은 날 닫힌 집 30~40 °C)가 과대 추정의 대가(흐린 날 10 % 환기)보다 크다.
# 김제(일사 채널 없음) 10/14 정오: 19 + 0.02 × 0.75 × 650 = 28.8 °C > 작물 선 — 0.5 면 25.5 라 선에 못 미친다.
BLIND_UNMEASURED_CLOUD = 0.75
# 바깥이 이보다 차면 서지 않는다 — 가지·박과 모종의 저온 장해가 10~12 °C 에서 시작한다. 실내를 모르는 채
# 그보다 찬 바람을 들이지 않는다(겨울 맑은 낮의 해는 닫힌 집을 데우는 몫이기도 하다).
BLIND_T_EXT_MIN_C = 12.0
BLIND_FLOOR_MIN_PCT = 10.0   # 선 바로 위의 하한 — 일사 하한(15 %, 약한 해 10.5 %)보다 작게
BLIND_FLOOR_MAX_PCT = 20.0   # 상한 — 근거 없는 큰 동작은 하지 않는다(일사 하한 80 % 의 1/4)
# 이 하한으로 여닫는 폭 [%p/사이클, `BLIND_REF_CYCLE_S` 기준 — 짧은 주기는 비례해 줄인다]. 두절 제습 닫기
# (`coordinator.OUTAGE_DEHUMID_STEP_PCT`)와 같은 5 %p — 0 → 10 % 가 2 사이클(600 s 주기면 20 분).
BLIND_STEP_PCT = 5.0
BLIND_REF_CYCLE_S = 600.0


@dataclass
class SolarVentState:
    """사이클을 넘는 이력. 재시작을 넘는다(`cycle_memory`)."""
    sun_on: bool = False
    on: bool = False
    on_since: Optional[float] = None   # 이번에 선 시각(epoch) — `SV_MIN_ON_S` 유지
    blind_on: bool = False             # 실내를 모르는 맑은 낮의 하한이 서 있다(근거 60, 이력)


@dataclass
class SolarVentDecision:
    """한 사이클의 결론. 쓰는 곳은 이것만 읽는다."""
    active: bool = False
    floor_pct: float = 0.0
    solar_w: Optional[float] = None
    sun_on: bool = False
    t_line: Optional[float] = None     # 덥다의 선(목표 + 허용오차)
    excess_c: Optional[float] = None   # 실내 − 선
    why_off: Optional[str] = None      # 'no_sun' | 'cool' | 'hot_outside' | 'unknown'
    # 실내를 모르는 사이클(근거 60) — `blind` 는 실내 온도 모름 · 실외 실측 있음. 하한은 `blind_floor_pct`.
    blind: bool = False
    blind_floor_pct: float = 0.0
    t_est: Optional[float] = None      # 닫힌 집 어림 온도(외기 + 일사 × 계수)
    blind_solar_w: Optional[float] = None  # 이 판정이 쓴 일사(센서가 없으면 맑은 하늘 × 3/4)
    blind_why_off: Optional[str] = None  # 'no_sun' | 'cold_outside' | 'cool' | 'unknown'

    def describe_blind(self) -> str:
        """실내를 모르는 사이클의 하한(근거 60) 한 줄."""
        if self.blind_floor_pct > 0.0:
            return ('일사 %.0f W/m² · 외기와 일사로 어림한 닫힌 집 %.1f °C > 선 %.1f °C → 환기 하한 %.0f %%'
                    % (self.blind_solar_w or 0.0, self.t_est or 0.0, self.t_line or 0.0,
                       self.blind_floor_pct))
        return '환기 하한 없음(%s)' % {
            'no_sun': '일사 열부하 없음', 'cold_outside': '바깥이 참',
            'cool': '닫힌 집 어림이 선 아래', 'unknown': '일사·선 중 모르는 값'}.get(
                self.blind_why_off, '실내 측정 있음' if not self.blind else '-')

    def describe(self) -> str:
        if self.active:
            return ('일사 %.0f W/m² · 실내가 선(%.1f °C)보다 %.1f °C 높음 → 환기 하한 %.0f %%'
                    % (self.solar_w or 0.0, self.t_line or 0.0, self.excess_c or 0.0,
                       self.floor_pct))
        return '환기 하한 없음(%s)' % {
            'no_sun': '일사 열부하 없음', 'cool': '목표 안', 'hot_outside': '바깥이 더 덥다',
            'unknown': '실내·실외·일사·목표 중 모르는 값'}.get(self.why_off, '-')


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def solar_load(internal: dict, external: dict, clear_sky_now=None,
               cloud_ratio=None, unmeasured_cloud: float = SV_UNMEASURED_CLOUD) -> Optional[float]:
    """판단용 실외 일사 [W/m²]. 실측(양수) → 맑은 하늘 × 구름비 → 맑은 하늘 × `SV_UNMEASURED_CLOUD`.

    실측 정본은 `heat_protect._outdoor_solar`(차광 판정과 같은 값). 구름비는 `screen_policy` 의
    30 분 EMA — 실측이 잠깐 끊긴 사이를 메운다. 일사 센서가 아예 없으면 맑은 하늘의 절반으로
    어림한다(상수 주석). 맑은 하늘도 모르면(좌표 없음) None — 판단하지 않는다.
    """
    from .heat_protect import _outdoor_solar
    s = _outdoor_solar(internal or {}, external or {})
    if s is not None:
        return s
    cs, cr = _num(clear_sky_now), _num(cloud_ratio)
    if cs is None:
        return None
    if cr is None:
        cr = unmeasured_cloud
    return max(0.0, cs) * max(0.0, cr)


def crop_line(ctx: dict, t_protect=None) -> Optional[float]:
    """작물의 온도 의도로 그은 '덥다' 의 선 — VPD 를 맞추려고 옮긴 온도가 아니다.

    단계의 지금(주·야) 온도(`T_stage`) + `SV_CROP_TOL_C` → 없으면 유도 범위의 위쪽 1/3 지점
    (`T_guide_low` + `SV_GUIDE_FRAC` × 폭) → 아래 끝을 모르면 유도 상한(`T_ceiling`). 보호 문턱
    (`t_protect`)이 있으면 그 − `_SPAN_MIN_C` 를 넘지 않는다 — 문턱에서 하한이 80 % 로 이어지게.
    모르면 None.
    """
    ctx = ctx or {}
    stage = _num(ctx.get('T_stage'))
    lo, hi = _num(ctx.get('T_guide_low')), _num(ctx.get('T_ceiling'))
    if stage is not None:
        line = stage + SV_CROP_TOL_C
    elif lo is not None and hi is not None and hi >= lo:
        line = lo + SV_GUIDE_FRAC * (hi - lo)
    elif hi is not None:
        line = hi
    else:
        return None
    tp = _num(t_protect)
    if tp is not None:
        line = min(line, tp - _SPAN_MIN_C)
    return line


def temperature_line(target: dict, ctx: Optional[dict] = None, t_protect=None) -> Optional[float]:
    """'덥다' 의 선. 모르면 None.

    - 온도가 제어 목표이고 작물의 의도이면(온도 우선 모드의 단계 목표, VPD 목표 없음의 유도 중앙)
      그 목표 + 허용오차 — 종전 그대로.
    - 목표 온도가 다른 것을 좇으면 — VPD 직접 모드의 유도 목표(`_temperature_constraint`), VPD 를
      못 재 물러난 분해 목표(`vpd_fallback`), 온도 우선 모드의 밴드(지금 온도를 따라간다,
      `T_basis_band`) — min(그 목표 + 허용오차, 작물 선(`crop_line`)). 습한 아침의 VPD 분해는 VPD 를
      올리려고 온도 목표를 실내보다 위로 끌어 올리며 같이 오른다(폐루프 김제 푄 이튿날 07:20~08:40,
      26.75 → 32.0 °C) — 그 선은 '덥다' 를 영영 말하지 않는다. 건조해 유도 목표가 낮을 때는 종전과 같다.
    - 목표가 없으면 작물 선.
    """
    target = target or {}
    ctx = ctx or {}
    crop = crop_line(ctx, t_protect)
    tv = target.get('temperature')
    tracking = bool(ctx.get('vpd_fallback') or ctx.get('T_basis_band'))
    if tv is None:
        tv, tracking = target.get('_temperature_constraint'), True
    v = _num(getattr(tv, 'value', None)) if tv is not None else None
    if v is None:
        return crop
    own = v + float(getattr(tv, 'tolerance', 0.0) or 0.0)
    if not tracking or crop is None:
        return own
    return min(own, crop)


def floor_pct(excess_c: float, t_line: float, t_protect: Optional[float],
              solar_w: float) -> float:
    """하한(%) — 초과분과 일사로 연속으로 커진다(모듈 머리말의 식)."""
    span = max(_SPAN_MIN_C, (float(t_protect) - float(t_line))
               if t_protect is not None else 5.0)
    x = min(1.0, max(0.0, float(excess_c) / span))
    s = min(1.0, max(0.0, (float(solar_w) - SV_SOLAR_ON_W) / (SV_SOLAR_FULL_W - SV_SOLAR_ON_W)))
    w = SV_SOLAR_W_MIN + (1.0 - SV_SOLAR_W_MIN) * s
    return (SV_FLOOR_MIN_PCT + (SV_FLOOR_MAX_PCT - SV_FLOOR_MIN_PCT) * x) * w


# @manual ai/env-control#solar-vent
def evaluate_solar_vent(state: SolarVentState, ctx: dict, target: dict, heat_protect=None,
                        clear_sky_now=None, cloud_ratio=None,
                        now: Optional[float] = None) -> SolarVentDecision:
    """이번 사이클의 판단 → `SolarVentDecision`. `state` 를 제자리에서 고친다.

    `ctx` 는 `situation.context`(T_int·T_ext·internal·external·heat_protect·temp_max·T_ceiling),
    `target` 은 `situation.target`. `heat_protect` 는 이번 사이클의 보호 결론(문턱) — 없으면
    `ctx['heat_protect']`. `now`(epoch)를 주면 선 하한은 `SV_MIN_ON_S` 동안 온도로는 풀리지 않는다.
    """
    ctx = ctx or {}
    internal = ctx.get('internal') or {}
    external = ctx.get('external') or {}
    solar = solar_load(internal, external, clear_sky_now, cloud_ratio)
    if solar is None:
        state.sun_on = False
    else:
        state.sun_on = solar >= (SV_SOLAR_OFF_W if state.sun_on else SV_SOLAR_ON_W)
    T_i, T_e = _num(ctx.get('T_int')), _num(ctx.get('T_ext'))
    synthetic = bool(external.get('_ext_synthetic'))
    hp = heat_protect if heat_protect is not None else ctx.get('heat_protect')
    t_protect = (_num(getattr(hp, 'threshold', None))
                 if hp is not None and getattr(hp, 'enabled', False) else None)
    if t_protect is None:
        t_protect = _num(ctx.get('temp_max'))
    line = temperature_line(target, ctx, t_protect)
    out = SolarVentDecision(solar_w=solar, sun_on=state.sun_on, t_line=line)

    if T_i is None and T_e is not None and not synthetic:
        _blind_floor(state, out, solar_load(internal, external, clear_sky_now, cloud_ratio,
                                            unmeasured_cloud=BLIND_UNMEASURED_CLOUD),
                     T_e, line, t_protect)
    else:
        state.blind_on = False
    if not state.sun_on:
        state.on = False
        out.why_off = 'unknown' if solar is None else 'no_sun'
        return out
    if T_i is None or T_e is None or synthetic:
        # 실외를 모르면 창은 제자리(2.6)다 — 하한을 걸지 않는다.
        state.on = False
        out.why_off = 'unknown'
        return out
    if T_e > T_i + SV_HOT_OUTSIDE_C:
        state.on = False
        out.why_off = 'hot_outside'
        return out
    if line is None:
        state.on = False
        out.why_off = 'unknown'
        return out
    excess = T_i - line
    out.excess_c = excess
    was_on = state.on
    held = (was_on and now is not None and state.on_since is not None
            and float(now) - float(state.on_since) < SV_MIN_ON_S)
    state.on = excess > 0.0 or (was_on and (excess > -SV_EXIT_MARGIN_C or held))
    if state.on and not was_on:
        state.on_since = None if now is None else float(now)
    if not state.on:
        out.why_off = 'cool'
        return out
    out.active = True
    out.floor_pct = floor_pct(max(0.0, excess), line, t_protect, solar)
    return out


# @manual ai/env-control#solar-vent-blind
def _blind_floor(state: SolarVentState, out: SolarVentDecision, solar: Optional[float],
                 T_e: float, line: Optional[float], t_protect: Optional[float]) -> None:
    """실내 온도를 모르고 실외 실측이 있는 사이클의 하한(근거 60, 머리말 마지막 절). `out`·`state` 를 고친다.

    해(`solar` ≥ `SV_SOLAR_ON_W`, 서 있으면 `SV_SOLAR_OFF_W` 까지) · 외기 ≥ `BLIND_T_EXT_MIN_C` · 닫힌 집 어림 > 선
    (서 있으면 선 − `SV_EXIT_MARGIN_C` 까지). `solar` 는 일사 센서가 없으면 맑은 하늘 × `BLIND_UNMEASURED_CLOUD` 다.
    """
    out.blind = True
    out.blind_solar_w = solar
    if solar is None or line is None:
        state.blind_on, out.blind_why_off = False, 'unknown'
        return
    t_est = float(T_e) + BLIND_SOLAR_RISE_C_PER_W * max(0.0, float(solar))
    out.t_est = t_est
    if float(solar) < (SV_SOLAR_OFF_W if state.blind_on else SV_SOLAR_ON_W):
        state.blind_on, out.blind_why_off = False, 'no_sun'
        return
    if float(T_e) < BLIND_T_EXT_MIN_C:
        state.blind_on, out.blind_why_off = False, 'cold_outside'
        return
    excess = t_est - float(line)
    state.blind_on = excess > 0.0 or (state.blind_on and excess > -SV_EXIT_MARGIN_C)
    if not state.blind_on:
        out.blind_why_off = 'cool'
        return
    if t_protect is not None and float(T_e) >= float(t_protect):
        # 바깥이 극한 고온 — 닫지도 키우지도 않는다(머리말 ⚠).
        out.blind_floor_pct = BLIND_FLOOR_MIN_PCT
        return
    span = max(_SPAN_MIN_C, (float(t_protect) - float(line)) if t_protect is not None else 5.0)
    x = min(1.0, max(0.0, excess / span))
    out.blind_floor_pct = BLIND_FLOOR_MIN_PCT + (BLIND_FLOOR_MAX_PCT - BLIND_FLOOR_MIN_PCT) * x


def blind_step_pct(cycle_sec) -> float:
    """근거 60 의 사이클당 여닫는 폭 [%p] — `BLIND_REF_CYCLE_S` 보다 짧은 주기는 비례해 줄인다."""
    try:
        c = float(cycle_sec or 0.0)
    except (TypeError, ValueError):
        c = 0.0
    return BLIND_STEP_PCT * (min(1.0, c / BLIND_REF_CYCLE_S) if c > 0.0 else 1.0)


def floor_targets(vent_profiles) -> set:
    """하한을 걸 장치 — 개구부, 개구부가 없으면 팬(`heat_protect` 의 하한과 반대 순서: 그쪽은 습기를
    빼려는 것이라 팬이 먼저고, 이쪽은 일사 열을 빼는 일이라 공짜인 창이 먼저다)."""
    ops = {p.actuator_id for p in vent_profiles if getattr(p, 'kind', '') == 'opening'}
    if ops:
        return ops
    return {p.actuator_id for p in vent_profiles}
