# 환경 제어 자동화

AoT의 `env_coordinator`는 온실 환경(VPD, CO₂, 온도, 습도)을 자동으로 제어하는 3계층 제어 시스템입니다.

---

## VPD (수증기압 포화차)

VPD는 작물의 증산·흡수를 결정하는 핵심 지표입니다.

```
VPD = SVP × (1 - RH/100)
SVP = 0.6108 × exp(17.27T / (T + 237.3))  [kPa]
```

| 범위 | 상태 | 권장 작물 단계 |
|------|------|--------------|
| < 0.4 kPa | 너무 낮음 — 곰팡이 위험 | — |
| 0.4 ~ 0.8 kPa | 적정 | 발아·정식 초기 |
| 0.8 ~ 1.2 kPa | 적정 | 영양생장기 |
| 1.2 ~ 1.8 kPa | 적정 | 개화·착과기 |
| > 1.8 kPa | 너무 높음 — 수분 스트레스 | — |

---

## env_coordinator 제어 계층

### L1 — EnvTarget (목표값 설정)

Method 곡선 또는 고정값에서 VPD / CO₂ 목표를 읽습니다.

- **Method**: 재배 단계에 따른 시간별 목표 곡선 (파종~수확)
- **고정값**: 단순 운영 시 고정 setpoint 사용

### L2 — SituationReport (상황 평가)

현재 편차, 제한 인자, 추세를 평가합니다.

| 평가 항목 | 설명 |
|----------|------|
| 편차 | `현재값 - 목표값` |
| 제한 인자 | 온도·습도·CO₂ 중 VPD 달성을 방해하는 인자 |
| 추세 | 값이 목표 방향으로 이동 중인지 여부 |

### L3 — Coordinator (액추에이터 명령)

PI 제어 + 슬루율 제한 + 적분 와인드업 방지를 적용하여 액추에이터에 명령을 내립니다.

```
e(t) = setpoint - measurement
u(t) = Kp × e(t) + Ki × ∫e dt
slew: |Δu| ≤ slew_rate_per_cycle
output → 난방기 / 환풍팬 / 가습기 / CO₂ 공급기
```

---

## Function 설정

AoT UI에서 `Functions → env_coordinator` 로 이동하여 설정합니다.

### 기본 설정 항목

| 항목 | 설명 |
|------|------|
| Input (온도) | 실내 온도 센서 연결 |
| Input (습도) | 실내 습도 센서 연결 |
| VPD Method | 재배 단계별 VPD 목표 곡선 |
| CO₂ Method | CO₂ 목표 곡선 |
| Output (난방기) | 난방 액추에이터 연결 |
| Output (환풍팬) | 환기 액추에이터 연결 |
| Output (가습기) | 가습 액추에이터 연결 |
| Output (CO₂) | CO₂ 공급 액추에이터 연결 |

---

## Method (제어 곡선)

Method는 시간에 따른 setpoint 변화를 정의합니다.

**재배 단계 예시 (토마토):**

| 날짜 | VPD 목표 | CO₂ 목표 |
|------|---------|---------|
| 파종~7일 | 0.6 kPa | 800 ppm |
| 8~21일 | 0.8 kPa | 900 ppm |
| 22~42일 | 1.0 kPa | 1000 ppm |
| 43일~ | 1.3 kPa | 1000 ppm |

`SEED:` 로 시작하는 Method는 시드 프리셋으로 읽기 전용입니다. 수정이 필요하면 복제 후 편집하세요.

---

## 안전 게이트

제어에는 다중 안전 장치가 적용됩니다.

| 안전 장치 | 설명 |
|----------|------|
| 고온 차단 | 실내 온도 > 임계값 시 난방 강제 OFF |
| CO₂ 상한 | CO₂ > 1500 ppm 시 공급 강제 OFF |
| 센서 이상 | 센서값 `stale` 상태 지속 시 안전 모드 전환 |
| Manual Lock | AI 또는 사용자가 자동제어 일시 정지 가능 |

---

## AI와의 연동

AI 에이전트가 `analyze_control_performance`로 제어 성능을 진단합니다.

```
vpd_rmse         → VPD 목표 추종 오차 (낮을수록 좋음)
oscillation_index → 제어 진동 지수 (낮을수록 안정)
assessment       → "good" / "moderate" / "poor"
```

진단 결과에 따라 `suggest_setpoint_adjustment`로 목표값 조정을 제안하며, 사용자 승인 후 `set_vpd_target`으로 실제 적용됩니다.

---

## 관련 페이지

- [AI 개요](overview.md)
- [Functions 사용법](../Functions.md)
- [Methods 사용법](../Methods.md)
