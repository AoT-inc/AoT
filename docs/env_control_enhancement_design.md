# Integrated Environment Control 고도화 설계서

**문서 버전**: v1.2 (Track 5 결정 사항 확정)
**작성일**: 2026-05-16
**대상 함수**: `aot/functions/custom_functions/env_coordinator.py` + `aot/functions/utils/env_control/`
**상태**: Track 5 결정 완료 — Phase A 구현 착수 가능

## 변경 이력
- v0.1: 초안
- v0.2: 사용자 피드백 반영
  - VPD 목표값을 **AoT 기존 Method 시스템 재활용**으로 변경 (P3-2′)
  - T/RH는 **가이드(권고) 데이터**로 위상 명확화 — primary는 VPD, T/RH는 force-mode 트리거 + 분해 결과 보조목표
  - **P2-4 신규**: 복합 액추에이터 그룹 (좌/우 측창, 상/하 측창, 2중 보온커튼)
  - **P2-5 신규**: 데몬 재시작 안전성·주기 정합성·워치독
- v0.3: Method 편집기 고도화 반영
  - **P3-5 신규**: 인터랙티브 다중점 Method 편집기 + 주별 키프레임 (`DailyMultiPointMethod`)
  - 사용자 결정 반영: 다중 주차 키프레임 선형보간, 끝점 시간 고정/값 변경 가능, 최대 12점, 기존 method-build.html 확장
- v0.4: 결정사항 일부 답변 반영 + **Track 4 (AI/MCP 통합) 신규**
  - §7.3, 7.4, 7.5 확정
  - **P4-1, P4-2, P4-3 신규**: MCP 서버 노출 + AI 에이전트 가이드 + 안전 경계
- v1.0: 모든 결정사항 확정 (§7.1~7.12)
  - 7.1 w_T=0.6, 7.2 InfluxDB, 7.5 CUSTOM_OPTIONS 패턴
  - 7.6~7.12 권장값 채택 (구현 중 조정 가능)
  - **Track 1부터 구현 착수**
- v1.1: **Track 5 (Goal-Oriented Architecture) 신규**
  - 사용자 통찰 반영: ① VPD는 primary가 아닌 광합성의 한 게이트 변수, ② 시설은 제어 능력 한계가 있음, ③ 경제적 진입점은 관수(VPD 영향) — 이게 v1.0의 VPD-primary default를 정당화
  - **P5-1 신규**: Growth Schedule 컨텍스트 (Function 단일 시간축)
  - **P5-2 신규**: Control Authority (시설 제어 권한 자동 도출)
  - **P5-3 신규**: Passive/Natural 전략 + 운전 모드 확장 (degraded/natural/unattainable)
  - **P5-4 신규**: Photosynthesis-oriented Goal (광합성 모델 기반 동적 우선순위)
  - **P5-5 신규**: Cumulative Goal Tracker (DLI·GDD 누적 부채 + 보상 전략)
  - L1 결선: P1-1 (`decompose_vpd_to_T_RH`) → `build_env_target` 통합 (Phase A)
  - §7.14~7.17 결정 사항 신규
- v1.2: **Track 5 결정 사항 확정 + 시간대/중단 처리 명시**
  - §7.14~7.17 모든 항목 권장값 확정
  - **§3.16.7 신규**: 시설 위치 기반 시간대 처리 (`t_sec`은 시설 현지시간 기준)
  - **§3.16.8 신규**: 중단 처리 정책 — **Wall-clock** (중단 시간도 경과로 카운트, 보상은 `schedule_week_offset`으로 사용자가 수동 조정)
  - **§7.18 신규**: 시간대/중단 결정 사항 확정
  - 단순화: 중단 감지 4단계 분기, downtime_log, runtime_only_mode 모두 폐기

---

## 0. 목적 및 범위

현 `env_coordinator` Function은 4계층(L1~L3) + 양측 안전게이트 프레임워크는 완성되었으나, **목표값 자동화·VPD 분해 정밀도·캘리브레이션·관측성·고도 액추에이터 지원**이 미완성 상태이다.

본 문서는 다음을 정의한다:

1. 신규/확장될 모듈 구조와 인터페이스
2. 데이터 모델(스키마) 변경점
3. 알고리즘 사양 (수식 포함)
4. 마이그레이션·롤아웃 계획
5. 테스트 전략

본 문서는 **합의 후 코드 구현(4단계)**의 단일 출처(source of truth)이다.

---

## 1. 기존 시스템 요약 (1단계 조사 반영)

```
[GeoFacility(actuators, computed)]
        │
        ▼ profile 로더 3단계 (facility → paired Output → manual Action)
[ActuatorProfile 리스트]
        │
        ▼
L1 build_env_target()  ─── 정적 VPD/T/RH/Light setpoint
        │
        ▼
L2 assess()             ─── 외부센서 수집, VPD 분해(거친), 제한인자
        │
        ▼
L3 coordinate()         ─── PI + slew + hysteresis + anti-windup
        │
        ▼
[SafetyPreGate]         ─── 강우/강풍/만료/풍향 차등
[SafetyPostGate]        ─── 명령 범위·정합성
        │
        ▼
[DaemonControl.output_on/off()]
```

**완성 항목**: 4계층 분리, PI/슬루/anti-windup, 양측 게이트, GIS 풍향 차등(G4), 면적 가중(G3).

**미완성 항목**: L1 동적 곡선, VPD 가중 분해, 자동 캘리브레이션, fan/ACH, 광합성 모델, 단위테스트, 시계열 로깅, 작물 라이브러리, 예보 피드포워드.

---

## 2. 개선 항목 마스터 리스트

| ID | 이름 | Track | 우선순위 | 회귀 위험 |
|----|------|-------|---------|----------|
| P1-1 | VPD 가중 분해 | 1 | High | Low |
| P1-2 | 단위 테스트 인프라 | 1 | High | None |
| P1-3 | 시계열 로깅 표준화 | 1 | High | Low |
| P2-1 | facility_geo_helpers (G1) | 2 | Mid | Low |
| P2-2 | ext_context fallback 강화 | 2 | Mid | Mid |
| P2-3 | env_coordinator 모듈 분리 | 2 | Mid | Mid |
| P3-1 | fan/ACH 액추에이터 종류 | 3 | Mid | Low |
| P3-2 | 작물 프로필 라이브러리 + 시간곡선 | 3 | High | Mid |
| P3-3 | 효과계수 자동 캘리브레이션 | 3 | Mid | High |
| P3-4 | 예보 기반 피드포워드 | 3 | Low | Mid |
| **P2-4** | **복합 액추에이터 그룹 (좌/우, 상/하, 2중 커튼)** | **2** | **High** | **Mid** |
| **P2-5** | **데몬 재시작 안전·주기 정합·워치독** | **2** | **High** | **Mid** |
| **P2-5b** | **런타임 신뢰성 하드닝 — 저장/Dispatch 실패 가시화** ✅ 2026-05-16 | **2** | **Mid** | **Low** |
| **P3-2′** | **Method 시스템 기반 VPD 목표 곡선 (구 P3-2 대체)** | **3** | **High** | **Low** |
| **P3-5** | **인터랙티브 다중점 Method 편집기 + 주별 키프레임** | **3** | **High** | **Mid** |
| **P4-1** | **MCP 서버 — AoT 도구 노출** | **4** | **High** | **Mid** |
| **P4-2** | **AI 에이전트 가이드 (스킬·매니페스트)** | **4** | **High** | **Low** |
| **P4-3** | **AI 작업 안전 경계 + 감사 로그** | **4** | **Critical** | **Mid** |
| **P5-1** | **Growth Schedule 컨텍스트 (Function 단일 시간축)** | **5** | **High** | **Low** |
| **P5-2** | **Control Authority — 시설 권한 자동 도출** | **5** | **High** | **Mid** |
| **P5-3** | **Passive/Natural 전략 + 운전 모드 확장** | **5** | **Mid** | **Mid** |
| **P5-4** | **Photosynthesis-oriented Goal (광합성 모델 기반)** | **5** | **Mid** | **High** |
| **P5-5** | **Cumulative Goal Tracker (DLI·GDD 누적 부채)** | **5** | **Mid** | **Mid** |

### VPD/T/RH 위상 (사용자 피드백 명시, v1.1 보강)
- **VPD = 보편 진입 default** — 경제적으로 가장 도입 쉬운 자동화(관수)의 주된 환경 효과가 VPD이기 때문. "이론적 primary"가 아니라 "절대다수 사용자가 다룰 수 있는 유일한 변수" → v1.0의 VPD-primary 정책의 실제 근거
- **T, RH = Guide(권고) 데이터** — VPD 분해의 보조목표 + 가이드 범위 이탈 시 force-mode 트리거 (R3 제약)
- 사용자는 T/RH를 강제 setpoint로 두지 않고, **가이드 범위(min/max)만 지정** → VPD 추종 과정에서 위반 시에만 개입
- **고도화 시점 (Track 5)**: VPD는 광합성의 한 게이트 변수에 불과하다는 사실을 인정 → 시설이 추가 액추에이터(보광·CO2·가열·냉방)를 갖추면 광합성-중심 목표 구조로 자동 확장 (P5-4). VPD-primary는 항상 default fallback으로 유지.

---

## 3. 설계 상세

### 3.1 P1-1. VPD 가중 분해

**문제**: 현재 `situation.py:196~240`의 VPD 보조목표 도출은 단순 룩업으로, 외부조건·작물 가중치 무시.

**수식**:
```
VPD = SVP(T) × (1 - RH/100)
SVP(T) = 0.6108 × exp(17.27·T / (T+237.3))   [kPa, Tetens 공식]
```

분해 목표: 현재 (T_int, RH_int)에서 vpd_target에 도달하는 (T_aux, RH_aux) 결정.

**가중 분해 알고리즘**:
1. 사용자 가중치 `w_T ∈ [0,1]`, `w_RH = 1 - w_T` 입력 (기본값 협의 필요 — **§7.1 결정사항** 참조)
2. 비용함수 `J = w_T·(T_aux - T_int)² + w_RH·(RH_aux - RH_int)²`
3. 제약 `VPD(T_aux, RH_aux) = vpd_target` 하에 J 최소화
4. 라그랑주 승수법으로 닫힌 해 도출 (반복 없음)

**인터페이스**:
```python
# situation.py
def decompose_vpd_to_T_RH(
    vpd_target: float,         # kPa
    T_int: float,              # °C
    RH_int: float,             # %
    w_T: float = 0.5,          # T 변경 비용 가중
    constraints: TempRHBounds = None,
) -> tuple[float, float]:      # (T_aux, RH_aux)
    ...
```

**결정 필요**:
- `w_T` 기본값 (§7.1)
- 가중치를 UI에서 노출할지 (function_options에 슬라이더 추가 여부)

---

### 3.2 P1-2. 단위 테스트 인프라

**위치**: `aot/functions/utils/env_control/tests/` (신규)

**테스트 대상**:
- `test_vpd.py`: SVP 공식, 분해 수렴, 경계조건
- `test_coordinator.py`: PI 계산, slew 클램프, anti-windup 작동, hysteresis 진입/해제
- `test_safety_gates.py`: 강우/강풍/만료, 풍향 차등 (G4)
- `test_effect_functions.py`: 각 액추에이터 효과 부호, GIS 가중
- `test_goal.py`: target 우선순위 (VPD primary > Light > constraints)

**프레임워크**: pytest (이미 표준일 것으로 추정). conftest.py에 mock 시계/측정 픽스처.

**커버리지 목표**: env_control 모듈 80% 이상.

**CI 통합**: 별도 결정 (§7.4).

---

### 3.3 P1-3. 시계열 로깅 표준화

**문제**: 현재 매 사이클 상태가 daemon 로그에만 남아 시계열 분석 불가.

**저장 채널** (사이클당 1행):
| 채널명 | 단위 | 의미 |
|--------|------|------|
| `env.T_int`, `env.RH_int`, `env.VPD_int`, `env.CO2_int`, `env.Light_int` | °C, %, kPa, ppm, μmol | 내부 실측 |
| `env.T_ext`, `env.RH_ext`, `env.wind`, `env.wind_dir`, `env.rain` | °C, %, m/s, deg, mm | 외부 실측 |
| `env.target.{vpd,T,RH,Light}` | 동일 | 현재 활성 목표값 |
| `env.residual.{vpd,T,RH}` | 동일 | 목표 - 실측 |
| `env.cmd.{actuator_id}` | % | 명령 값 |
| `env.mode` | enum | normal / forced / safe / manual_lock |
| `env.limiting_factor` | enum | 광/T/RH/CO2/none |

**저장 방식**:
- AoT 표준 `InfluxDB` 측정값 큐 사용 (`utils/influx.py` 추정 — 확인 필요 §7.2)
- Function 종료 시 일괄 flush

**확장 위치**: [log_channels.py](aot/functions/utils/env_control/log_channels.py:1) — 현재 채널 정의만, 저장 함수 추가.

---

### 3.4 P2-1. facility_geo_helpers (G1)

**문제**: GeoFacility의 `actuators[slot].azimuth_deg / area_m2`가 사용자 수동 입력. GeoShape feature(GeoJSON)에 도형 정보가 있음에도 미활용.

**신규 모듈**: `aot/aot_flask/utils/facility_geo_helpers.py`

**함수**:
```python
def shape_azimuth_area(geojson_feature: dict) -> tuple[float, float]:
    """
    GeoJSON Polygon/LineString feature에서:
    - azimuth_deg: 도형의 주 법선 방향 (0=북, 90=동) — 외부면 향함
    - area_m2: 평면 투영 면적 (geodesic, pyproj)
    Returns (azimuth_deg, area_m2).
    """

def compute_facility_geometry(facility: GeoFacility) -> dict:
    """
    facility.shape_id로 연결된 GeoShape에서 도형 읽어
    actuators[].azimuth_deg, area_m2 자동 계산하여
    facility.computed에 채움. 기존 값은 덮어쓰지 않음(merge).
    """
```

**호출 지점**:
- facility 저장 시 (geo_facility 라우트 POST)
- 수동 트리거 (UI 버튼 "지오메트리 재계산")

**의존성**: `pyproj` (geodesic 면적 계산). 미설치 시 fallback으로 평면 근사.

---

### 3.5 P2-2. ext_context fallback 강화

**문제**: `ext_context_collector` Function이 정지/장애일 때 env_coordinator는 5분 만료 후 정지만 함. degraded mode 없음.

**새로운 모드**:
- `normal`: 외부센서 정상 (< 1분)
- `degraded`: 외부센서 stale (1~5분) → **보수적 목표값 적용** (VPD 데드밴드 ×2, slew 0.5×)
- `safe_hold`: 외부센서 만료 (> 5분) 또는 결측 → **현재 명령 유지 + 5분 후 점진적 close**

**UI 표시**: function_options에 상태 뱃지(녹/황/적).

**구현 위치**: env_coordinator.py 사이클 진입부 + safety_gates.py.

---

### 3.6 P2-3. env_coordinator 모듈 분리

**문제**: env_coordinator.py 1,150줄 — AbstractFunction 인터페이스, profile 로더, 사이클 실행, 외부센서 수집이 한 파일에 혼재.

**분리 구조**:
```
aot/functions/custom_functions/env_coordinator.py    (얇은 진입점, ~150줄)
    └─ from env_control.module import CustomModule

aot/functions/utils/env_control/
    ├── module.py     (AbstractFunction 인터페이스, 150줄)
    ├── loader.py     (profile 3단계 로더, 400줄)
    ├── runner.py     (사이클 실행 _run_cycle, 350줄)
    ├── ext_context.py(외부센서 수집·만료 판정, 100줄)
    └── (기존 파일 유지)
```

**호환성**: AbstractFunction 등록 경로(`env_coordinator.CustomModule`)는 동일. DB 변경 없음.

**리스크**: import 순환 가능성 — 의존방향 명시 (module → loader/runner/ext_context → 기존 모듈).

---

### 3.7 P3-1. fan/ACH 액추에이터 종류

**ACTUATOR_KINDS 추가** ([types.py](aot/functions/utils/env_control/types.py:1)):
- `circulation_fan`: 내부 순환 (T·RH 균질화, 에너지 ~0)
- `exhaust_fan`: 강제 배기 (ACH 기반 T·RH·CO2 동시 변화)
- `intake_fan`: 강제 흡기 (외기 도입, exhaust와 짝)

**효과 함수** (effect_functions.py 추가):
```python
def exhaust_fan_temp_effect(cmd_pct, ctx, profile) -> float:
    """
    ACH = (rated_cfm × cmd/100 × 60) / volume_m3
    dT/cycle = ACH × (T_ext - T_int) × dt_min / 60 × factor
    """
    ACH = profile.capacity_meta["rated_cfm"] * cmd / 100 * 60 / volume_m3
    return ACH * (T_ext - T_int) * (dt_min / 60.0)
```

**필요한 facility 메타데이터**: `volume_m3` 추가 (computed 또는 사용자 입력).

---

### 3.8 P3-2′. Method 시스템 기반 VPD 목표 곡선 (Phase E, 신규 설계)

**사용자 피드백**: "vpd - 시스템의 method 기능을 활용, 초기/중기/수확 단계별 값을 선택적으로 적용. 온도/습도는 가이드를 위한 데이터."

**원칙**: 자체 YAML 작물 라이브러리를 만들지 않고, AoT 기존 **Method 시스템**([methods/method.py](aot/databases/models/method.py), [utils/method.py](aot/utils/method.py))을 그대로 재활용.

**Method 활용 패턴**:

| 운영 시나리오 | 적합한 Method 종류 | 비고 |
|--------------|------------------|------|
| 매일 같은 일변동 (주/야 VPD) | `DailyMethod`, `DailyBezierMethod`, `DailySineMethod` | 24h 반복 |
| 생육 단계 진행 (초기→중기→수확) | `DurationMethod` | 정식일 기준 경과시간 |
| 단계 + 일변동 동시 | `CascadeMethod` | Daily × Duration 결합 |
| 특정 기간만 적용 | `DateMethod` | 일회성 |

**예시 — 토마토 풀스펙**:
```
Method "tomato_vpd_diurnal" (DailyMethod)
  - 06:00 VPD=0.8
  - 12:00 VPD=1.2
  - 20:00 VPD=0.6

Method "tomato_vpd_stage" (DurationMethod, 정식일=2026-03-01)
  - 0~30일 (초기): scale=0.85
  - 30~90일 (중기): scale=1.00
  - 90~150일 (수확기): scale=1.10

Method "tomato_vpd_final" (CascadeMethod)
  = diurnal × stage
```

**env_coordinator 통합** (custom_options 확장):
```json
{
  "vpd_source": "method",
  "vpd_method_id": "tomato_vpd_final",
  "vpd_method_start_time": "2026-03-01T00:00:00",

  "vpd_source_fallback": 1.0,        // method 없거나 finished일 때

  "guide_T_min": 12,                 // T는 가이드만
  "guide_T_max": 32,
  "guide_RH_min": 40,
  "guide_RH_max": 85,
  "vpd_decompose_weight_T": 0.6      // P1-1 연동
}
```

**L1 인터페이스** (goal.py 확장):
```python
def build_env_target(custom_options, now_dt) -> EnvTarget:
    src = custom_options.get("vpd_source", "static")
    if src == "method":
        handler = load_method_handler(custom_options["vpd_method_id"])
        start = parse_iso(custom_options["vpd_method_start_time"])
        vpd, finished = handler.calculate_setpoint(now_dt, start)
        if finished:
            vpd = custom_options.get("vpd_source_fallback", 1.0)
    else:
        vpd = custom_options["vpd_static"]

    return EnvTarget(
        vpd=vpd,
        T_guide_range=(custom_options["guide_T_min"], custom_options["guide_T_max"]),
        RH_guide_range=(custom_options["guide_RH_min"], custom_options["guide_RH_max"]),
        light_target=...,   # 별도 method도 가능
    )
```

**UI 변경**:
- function_options에 VPD source 선택: `static` / `method`
- `method` 선택 시 Method 드롭다운 (DB의 사용자 Method 목록) + 시작 시각
- T/RH는 단일 값 입력이 아닌 min/max 범위 입력으로 UI 변경

**장점**:
- Method UI([method-build.html](aot/aot_flask/templates/pages/method-build.html))가 이미 완성 — 사용자가 곡선 시각화·편집 가능
- PID 컨트롤러와 동일한 방식([controller_pid.py:228-229](aot/controllers/controller_pid.py:228))이라 학습곡선 없음
- 작물별 Method 프리셋은 향후 export/import 또는 템플릿으로 별도 제공 가능 (필수 아님)

**T/RH 위상 변경 영향**:
- L2 `assess()`: 기존에 T/RH를 강제 setpoint로 다루던 분기 제거 → 분해 결과 또는 가이드 위반 트리거로만 사용
- L3 `coordinate()`: 변수 우선순위에서 T/RH는 normal 모드에서는 vpd 분해 결과 보조목표로만 작동. 가이드 범위 이탈 시 forced 모드로 격상

---

### (구) 3.8 P3-2. 작물 프로필 라이브러리 — 폐기
사용자 피드백에 따라 자체 YAML 라이브러리는 만들지 않음. Method 재활용으로 대체.

---

### (구절 보존) 원본 P3-2 설계 (참고용, 미구현)

**라이브러리 위치**: `aot/data/crop_profiles/*.yaml` (신규)

**스키마**:
```yaml
crop: tomato
stage: vegetative   # seedling / vegetative / flowering / fruiting
description: "토마토 영양생장기"
references: ["KAST 2019", "Wageningen UR"]

# 시간대별 목표 (24h, 1시간 간격, 보간)
diurnal:
  - hour: 0
    T: 18.0
    RH: 70
    VPD: 0.6
    light_target: 0      # 야간
    CO2: 400
  - hour: 6
    T: 20.0
    RH: 65
    VPD: 0.8
    light_target: 300
    CO2: 800
  - hour: 12
    T: 24.0
    RH: 60
    VPD: 1.2
    light_target: 600
    CO2: 1000
  # ... 24개 포인트

# 제약
constraints:
  T_min: 12
  T_max: 32
  RH_min: 40
  RH_max: 85
  VPD_max: 1.8
```

**L1 확장** (goal.py):
```python
def build_env_target(custom_options, now_dt) -> EnvTarget:
    if custom_options.get("use_crop_profile"):
        profile = load_crop_profile(
            custom_options["crop"],
            custom_options["stage"],
        )
        target = interpolate_diurnal(profile, now_dt)  # 선형 보간
    else:
        target = static_target_from_options(custom_options)
    return target
```

**UI**:
- function_options에 작물·생육단계 드롭다운 추가
- 24시간 곡선 그래프 미리보기

**결정 필요**: YAML 스키마 (§7.3), 초기 라이브러리에 포함할 작물 (토마토/딸기/상추?).

---

### 3.9 P3-3. 효과계수 자동 캘리브레이션 (Phase F)

**원리**: 명령 c(t)와 응답 ΔT(t), ΔRH(t)의 시계열로부터 K_temp, K_humid 추정.

**알고리즘**: 재귀 최소제곱(RLS)
```
ΔT(t+1) = K_temp · c(t) · gis_factor + noise
K̂(t+1) = K̂(t) + P(t)·c(t)·(ΔT_obs - K̂(t)·c(t)) / (λ + P(t)·c(t)²)
P(t+1) = (P(t) - P(t)·c(t)²·P(t) / (λ + P(t)·c(t)²)) / λ
λ = 0.95   (망각 인자)
```

**조건**:
- 명령이 유의미하게 변할 때만 갱신 (Δc > 5%)
- 외부 외란 큰 사이클 배제 (rain, wind > 5m/s)
- 24시간 이동평균 후 DB에 K_* 자동 갱신
- 사용자가 학습 on/off, 학습률 조정 가능

**저장 위치**: `Actions.custom_options.k_learned` (k_override와 분리하여 사용자 수동값 보호).

**위험**: 모델 발산 → bound 강제 (K_learned ∈ [0.1×K_default, 5×K_default]).

---

### 3.10a P2-4. 복합 액추에이터 그룹 (신규)

**사용자 피드백**: "액추에이터가 단일로만 되어있어서 복합적인 경우 처리 방안 필요. 예: 연동 시설이 좌우 로 구분 되거나 측창이 상하 분리 되어 있는 경우, 보온커튼이 2중인 경우 등"

**현재 한계 (조사 결과)**:
- `actuator_paired`는 단일 모터의 open/close 한 쌍만 처리 ([outputs/actuator_paired.py](aot/outputs/actuator_paired.py))
- env_coordinator의 `ActuatorProfile`은 단일 슬롯 단위 — 좌/우 측창 = 2개 독립 슬롯
- Group/Composite 개념 미구현

**복합 패턴 분류**:

| 패턴 | 예시 | 제어 모드 |
|------|------|----------|
| **Symmetric Pair (대칭쌍)** | 좌/우 측창 동시 동일 개도 | 단일 명령 → 두 actuator 동기 |
| **Windward-Differential (풍향 차등)** | 좌/우 중 풍상측만 폐쇄 | 단일 명령 + GIS azimuth 기반 분배 |
| **Stacked Layer (상하 적층)** | 상부창 → 하부창 순차 개방 | 단일 명령 → 임계값 기반 단계 |
| **Multi-Stage (다중층 커튼)** | 1차/2차 보온커튼 | 단일 명령 → 우선순위 기반 순차 |

**설계 — `ActuatorGroup` 신규 타입**:
```python
# types.py 신규
@dataclass
class ActuatorGroup:
    group_id: str
    kind: str                     # opening / thermal_curtain / shade ...
    mode: Literal["symmetric", "windward_diff", "stacked", "multi_stage"]
    members: list[ActuatorProfile]      # 2개 이상

    # 모드별 메타데이터
    stack_thresholds: list[float] = None    # stacked: [50, 80] — 0~50% 1단, 50~80% 2단
    stage_priority: list[int] = None        # multi_stage: [0, 1] — 0번 먼저 닫고 1번
    windward_select: dict = None            # windward_diff: {"azimuth_tol_deg": 60}
```

**조율 로직** (coordinator.py 확장):
- L3는 그룹 단위로 단일 명령 산출 → `expand_group_command(group, total_cmd, ctx)` 로 멤버별 명령 분배
- 분배 함수:
  - `symmetric`: 모든 멤버 = total_cmd
  - `windward_diff`: 풍상측 = clamp(total_cmd, max=safe_pct), 풍하측 = total_cmd (SafetyPreGate G4 이관)
  - `stacked`: 임계값 따라 1단→2단 순차 (예: total=60% → 1단 100%, 2단 (60-50)/(100-50)=20%)
  - `multi_stage`: 우선순위 순서대로 먼저 0% 또는 100%로 완전 명령 후 다음 단계

**Facility 구조 변경** (GeoFacility.actuators JSON):
```json
{
  "actuators": {
    "slot_side_vent_LR": {
      "kind": "opening",
      "group": {
        "mode": "symmetric",      // 또는 "windward_diff"
        "members": [
          {"output_id": "uuid-LEFT",  "channel": 0, "azimuth_deg": 270, "area_m2": 12.5},
          {"output_id": "uuid-RIGHT", "channel": 0, "azimuth_deg": 90,  "area_m2": 12.5}
        ]
      }
    },
    "slot_curtain_double": {
      "kind": "thermal_curtain",
      "group": {
        "mode": "multi_stage",
        "stage_priority": [0, 1],
        "members": [
          {"output_id": "uuid-CURTAIN1", "channel": 0, "u_value": 4.0},
          {"output_id": "uuid-CURTAIN2", "channel": 0, "u_value": 2.5}
        ]
      }
    }
  }
}
```

**하위 호환**: 기존 단일 actuator slot은 `group` 키 없는 형태로 그대로 동작. 로더가 `group` 키 있으면 `ActuatorGroup` 생성, 없으면 기존 `ActuatorProfile`.

**UI 변경**:
- function_options에 슬롯 정의 시 "단일 / 그룹" 선택
- 그룹 모드 선택 + 멤버 추가 UI

**효과 함수**: 그룹 효과 = 멤버 효과의 면적 가중 합 (이미 GIS factor가 면적 사용 중이라 자연 통합).

---

### 3.10b P2-5. 데몬 재시작 안전성·주기 정합성·워치독 (신규)

**사용자 피드백**: "운전에서의 로직의 진행과 데이터 및 제어 처리 주기의 적합성, 데몬이 죽었다 살아난 경우 등 고려 필요"

**현재 한계 (조사 결과)**:
1. **PI 적분항·last_cmd 인메모리** → 재시작 시 분실, 과도응답 가능
2. **K_learned 인메모리** → 학습 결과 휘발 (P3-3 추가 시 더 중요)
3. **actuator_paired 워치독은 프로세스 내부 타이머** → 데몬 죽으면 모터 hang 위험
4. **주기 정합성**: ext_context_collector(60s 권장) vs env_coordinator(60s 권장) — 엇갈리면 stale data 사용
5. **외부센서 만료 처리는 있으나 데몬 재시작 직후 fresh 판정 보장 없음**

**개선 1: 사이클 상태 영속화**

신규 테이블 `function_runtime_state`:
```sql
CREATE TABLE function_runtime_state (
    function_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,        -- {integral_state, last_cmd, last_cycle_ts, ...}
    updated_at TIMESTAMP NOT NULL
);
```

env_coordinator 사이클 끝마다:
```python
def _persist_state(self):
    state = {
        "integral": self._integral_state,           # {var_name: {actuator_id: float}}
        "last_cmd": self._last_cmd,                 # {actuator_id: pct}
        "last_cycle_ts": time.time(),
        "k_learned": self._k_learned,               # P3-3 연동
    }
    db.session.merge(FunctionRuntimeState(
        function_id=self.unique_id,
        state_json=json.dumps(state),
    ))
    db.session.commit()
```

initialize 시 복원:
```python
def initialize(self):
    state = load_state(self.unique_id)
    if state and (time.time() - state["last_cycle_ts"]) < self.update_period * 3:
        # 최근 데이터면 복원
        self._integral_state = state["integral"]
        self._last_cmd = state["last_cmd"]
    else:
        # 오래된 상태는 폐기, conservative initial
        self._integral_state = {}
        self._last_cmd = {a.id: self._safe_initial_cmd(a) for a in self._profiles}
```

**개선 2: 주기 정합성 강제**

- env_coordinator 시작 시 ext_context_collector의 update_period를 읽어 검증
- `env.update_period >= ext.update_period` 보장 (위반 시 UI 경고)
- 또는 env_coordinator가 ext_context fresh를 능동 폴링 (현재 fetch_timestamp 비교 → degraded mode 활용)

**개선 3: Watchdog (액추에이터 hang 방지)**

- actuator_paired에 이미 워치독 존재하나 **프로세스 내부 한정**
- 신규: **DB heartbeat 기반 외부 워치독**
  - env_coordinator 매 사이클 `last_heartbeat = now()` DB 기록
  - 별도 경량 데몬 (또는 cron) 이 5×update_period 동안 heartbeat 없으면 → 해당 function의 actuator 일괄 OFF + 알림
  - 구현 옵션:
    - (a) 기존 alembic_scheduler에 watchdog job 등록
    - (b) `aot_daemon.py`에 separate thread 추가
    - **권장 (a)** — 데몬 자체 죽었을 때도 외부에서 동작

**개선 4: Graceful shutdown**

env_coordinator의 `stop_function()`에:
- 현재 진행 중 명령은 안전값(완전 닫기 또는 정지)으로 수렴
- state persistence 마지막 flush
- 액추에이터에 명시적 stop 명령

**구현 위치**:
- `aot/databases/models/function_runtime_state.py` (신규 모델)
- alembic 마이그레이션 (신규 테이블 — DB 마이그레이션 **필요**)
- env_coordinator: initialize/stop_function/_run_cycle 수정
- 워치독 데몬: 신규 경량 모듈 `aot/controllers/function_watchdog.py`

**테스트**:
- 데몬 강제 kill 후 30초 내 재시작 시 PI 적분항 복원 검증
- 5분간 정지 시 워치독이 액추에이터 OFF 명령 발행 검증
- ext_context 업데이트 정지 → degraded → safe_hold 전이 검증 (P2-2 연동)

---

### 3.10c P2-5b. 런타임 신뢰성 하드닝 — 저장 실패 / Dispatch 실패 가시화 (2026-05-16)

**배경**: P2-5 본체는 `FunctionRuntimeState` 영속화로 PI 적분/이전 명령을 보존하지만, 다음 두 가지 silent failure 경로가 남아 있었다.

1. `_save_runtime_state()` 가 transient SQLite busy 등으로 실패하면 `logger.exception` 만 남기고 다음 사이클 진행 → 재시작 시 적분 손실 원인 추적 불가.
2. `_dispatch()` 가 개별 액추에이터 실패를 `logger.exception` 처리하고 끝 → 실패 패턴(특정 액추에이터 통신 장애 등)을 외부에서 관찰 불가.

심각한 오류라기보다 **장시간 운영 신뢰성**의 문제. 알고리즘 변경 없이 가시화·재시도만 추가.

**개선 1: Runtime state 저장 짧은 재시도 + CRITICAL 가시화**

`_runtime_state_mixin.py:_save_runtime_state()`:
- 최대 3회 (`_SAVE_RETRY_COUNT`), 백오프 0.3·0.6초 (`_SAVE_RETRY_BACKOFF_SEC`).
- 각 실패는 WARNING.
- 최종 실패 시 누적 카운트(`_runtime_state_fail_count`)를 인스턴스에 보관하고 CRITICAL 로그 + `decision_log(CH_RUNTIME_STATE_FAIL=72)` 기록.
- 누적값을 InfluxDB로 흘려보내므로 외부 모니터링에서 rate 산출 가능.

**개선 2: Dispatch 실패 집합 반환 + 채널 기록**

`_helpers_mixin.py:_dispatch()`:
- 반환 타입 `None → set[str]` (실패한 actuator_id 집합).
- 개별 실패는 WARNING (스택트레이스 대신 한 줄 요약 — actuator, val, ch, err).
- 사이클당 실패 수를 `decision_log(CH_DISPATCH_FAIL=71)` 기록.
- 호출자는 현재 반환값을 사용하지 않으나, 향후 P1 작업(`prev_commands` 동기화, 재시도 정책)에서 활용.

**신규 로그 채널** (`log_channels.py`):

| 채널 | 상수 | 의미 |
|---|---|---|
| 71 | `CH_DISPATCH_FAIL` | 한 사이클에서 dispatch 실패한 액추에이터 수 |
| 72 | `CH_RUNTIME_STATE_FAIL` | runtime state DB 저장 최종 실패 누적 카운트 |

**모니터링 지침**:
- `CH_RUNTIME_STATE_FAIL` 이 단조 증가하기 시작하면 DB 락 경쟁/디스크 이슈 의심 — 데몬 재시작 직전 PI 상태 손실 가능성 ↑.
- `CH_DISPATCH_FAIL` 이 특정 사이클대에서 반복되면 해당 액추에이터 통신 점검 (paired actuator watchdog 로그 교차 확인).

**구현 위치 (변경 파일)**:
- `aot/functions/utils/env_control/log_channels.py` — `CH_DISPATCH_FAIL`, `CH_RUNTIME_STATE_FAIL` 상수 추가
- `aot/functions/utils/env_control/__init__.py` — re-export
- `aot/functions/custom_functions/env_coordinator_impl/_runtime_state_mixin.py` — 재시도 + CRITICAL 가시화
- `aot/functions/custom_functions/env_coordinator_impl/_helpers_mixin.py` — `_dispatch` 반환값 + WARNING

**범위 밖 (P1으로 관찰 후 진행)**:
- 단일 `max_age` → 센서별 기대주기(period) 인식. 위성 외부 센서(주기 ~3600s) 같이 본질적으로 긴 주기 데이터는 staleness 위험이 아니므로 즉시 위험은 없음. 외부 센서 `None` 빈도 카운터를 별도 채널로 신호 박은 후 발현 시 대응.
- Profile reload 시 좀비 적분 정리, time window 재진입 bumpless, 히스테리시스 사용자 설정화, cumulative tracker DB 영속화 — 모두 발현 시 패치.

---

### 3.11 P3-5. 인터랙티브 다중점 Method 편집기 + 주별 키프레임 (신규)

**사용자 피드백**: "현재는 선을 그리는 방법이 어렵고 시간에 따라 선이 변화하지는 못함" — 폼 기반 입력 한계 해결 + 작물 생육에 따른 자동 진화 필요.

**신규 Method 타입**: `DailyMultiPointMethod` (기존 Daily/DailyBezier/DailySine 계열 확장)

#### 3.11.1 점 데이터 구조

```python
@dataclass
class CurvePoint:
    point_id: int            # 0..11, 안정 식별자 (드래그 시 순서 변경 가능)
    t_sec: int               # 0..86400 (0h~24h)
    value: float
    smooth: bool = False     # False=corner, True=smooth (Hermite)
    is_endpoint: bool = False  # 0h, 24h 점은 True (시간 고정)

    # 주별 키프레임 (선택적, 비어있으면 정적 점)
    keyframes: list[Keyframe] = []

@dataclass
class Keyframe:
    week: int                # 0 = 기준 주, 양수 = 미래
    t_sec: int               # 끝점은 무시 (0/86400 강제)
    value: float
```

#### 3.11.2 제약 사항 (사용자 결정 반영)

| 제약 | 규칙 |
|------|------|
| 점 개수 | 최대 12개 (기본 2개: 0h/24h) |
| 끝점 시간 | 0h, 24h 고정 — `t_sec` 변경 불가, **`value`는 변경 가능** |
| 중간 점 시간 | `P_{i-1}.t < P_i.t < P_{i+1}.t` 강제 (드래그 시 클램프) |
| 점 추가 | 선 클릭 시 해당 위치에 점 삽입 (12점 한도) |
| 점 삭제 | 컨텍스트 메뉴 또는 길게 누름 (끝점 제외) |
| 키프레임 점 개수 | 점 개수 가변 불가 — 모든 주차에서 같은 점 ID 보유 |

#### 3.11.3 보간 알고리즘

**시간축 (curve evaluation, 실시간 사용)**:
```
def eval_curve(points: list[CurvePoint], t_sec: int) -> float:
    # 1. t_sec이 속한 세그먼트 찾기 (P_i, P_{i+1})
    # 2. 두 점의 smooth 플래그로 보간 방식 결정:
    #    - 둘 다 corner → 선형 보간
    #    - 하나라도 smooth → monotonic cubic Hermite (오버슈트 방지)
    # 3. 반환
```

**Monotonic Cubic Hermite** 선택 이유:
- VPD/setpoint는 물리적 하한(VPD ≥ 0) 존재 → 오버슈트 위험 차단
- Catmull-Rom보다 안전, 자연 cubic spline보다 단순

**주축 (weekly interpolation, init 또는 주차 변경 시)**:
```
def resolve_points_at(now_dt, method_start_dt) -> list[CurvePoint]:
    weeks_elapsed = (now_dt - method_start_dt).days / 7.0
    resolved = []
    for p in points:
        if not p.keyframes:
            resolved.append(p)  # 정적
        else:
            # 주차 키프레임 선형 보간
            kfs = sorted([Keyframe(0, p.t_sec, p.value)] + p.keyframes, key=lambda k: k.week)
            t_now, v_now = interpolate_keyframes(kfs, weeks_elapsed)
            resolved.append(CurvePoint(p.point_id, t_now, v_now, p.smooth, p.is_endpoint))
    return resolved
```

**호출 빈도**:
- 사이클당 1회 — `calculate_setpoint(now, method_start_time)`
- 주차가 변하지 않으면 캐시된 `resolved` 재사용

#### 3.11.4 데이터 저장 — 신규 컬럼

**옵션 A 선택** (사용자 결정 반영 — 깔끔, JSON 컬럼 신규):

```sql
ALTER TABLE method_data ADD COLUMN points_json TEXT DEFAULT NULL;
```

`DailyMultiPointMethod`는 method당 `MethodData` 1행만 사용, `points_json`에 전체 점 + 키프레임 저장:

```json
{
  "version": 1,
  "points": [
    {
      "point_id": 0, "t_sec": 0, "value": 0.6,
      "smooth": false, "is_endpoint": true,
      "keyframes": [
        {"week": 0, "t_sec": 0, "value": 0.6},
        {"week": 4, "t_sec": 0, "value": 0.8}
      ]
    },
    {
      "point_id": 1, "t_sec": 43200, "value": 1.2,
      "smooth": true, "is_endpoint": false,
      "keyframes": [
        {"week": 0, "t_sec": 43200, "value": 1.2},
        {"week": 4, "t_sec": 45000, "value": 1.4}
      ]
    },
    {
      "point_id": 2, "t_sec": 86400, "value": 0.6,
      "smooth": false, "is_endpoint": true,
      "keyframes": []
    }
  ]
}
```

기존 컬럼(`x0~x3, y0~y3` 등)은 다른 Method 타입에서 계속 사용 — 변경 없음.

#### 3.11.5 UI 설계 (method-build.html 확장)

**위치**: `aot/aot_flask/templates/pages/method_options/build_daily_multipoint.html` (신규)

**컴포넌트**:
1. **타임축 SVG 차트** (가로축 0~24h, 세로축 setpoint 범위 자동)
2. **점**: 빨간 원(corner) / 파란 원(smooth) — 클릭 토글, 드래그 이동
3. **선 클릭** → 그 위치에 점 추가 (smooth는 양옆 점 평균값으로)
4. **컨텍스트 메뉴** (점 우클릭): 삭제, smooth 토글, 키프레임 편집
5. **주차 슬라이더** (상단): W0 ~ W12 — 현재 주의 곡선 미리보기
6. **키프레임 패널** (사이드): 선택한 점의 주차별 (t, v) 테이블 편집

**라이브러리**: 의존성 없는 vanilla SVG + JS (또는 기존 차트 라이브러리 — `method-build.html`에서 사용 중인 것 확인 후 일치)

**파일 분리**:
- `build_daily_multipoint.html` — Jinja 템플릿 (래퍼)
- `aot/aot_flask/static/js/method_multipoint_editor.js` — 편집기 로직
- `aot/aot_flask/static/css/method_multipoint_editor.css`

#### 3.11.6 백엔드 통합

**클래스 추가** ([utils/method.py](aot/utils/method.py)):
```python
class DailyMultiPointMethod(AbstractMethod):
    def __init__(self, method_id):
        super().__init__(method_id)
        self.points_data = json.loads(self.method_data_first.points_json)

    def calculate_setpoint(self, now, method_start_time=None):
        start_dt = method_start_time or datetime.datetime(1900, 1, 1)
        resolved = resolve_points_at(now, start_dt, self.points_data["points"])
        t_sec = now.hour * 3600 + now.minute * 60 + now.second
        value = eval_curve(resolved, t_sec)
        return value, False

    def get_plot(self, max_points_x=700):
        # 차트용 샘플링
        ...

    def ignore_date(self):
        return True
```

**팩토리 등록** ([utils/method.py:431-461](aot/utils/method.py:431) 확장):
```python
METHOD_TYPES = {
    ...
    "daily_multipoint": DailyMultiPointMethod,
}
```

#### 3.11.7 env_coordinator 연동

P3-2′와 자연 통합 — `vpd_method_id`가 `DailyMultiPointMethod`를 가리키면 자동 인식. **추가 코드 불필요**. Method 시스템의 다형성이 이 통합을 자연스럽게 처리.

#### 3.11.8 마이그레이션

```
alembic revision -m "add points_json to method_data for multipoint method"
```

`points_json` 컬럼 추가 (NULLABLE). 기존 데이터 영향 없음.

#### 3.11.9 검증·테스트

- **단위 테스트** (Track 1 P1-2 인프라 활용):
  - 끝점 시간 고정 검증
  - 중간점 인접 시간 추월 방지
  - smooth/corner 혼합 보간
  - monotonic Hermite 오버슈트 차단 (음수값 입력 → 음수값 출력만 허용)
  - 키프레임 보간: W=0, W=4 사이 W=2 시점 정확히 중간값
  - 12점 한계 검증
- **E2E**: 사용자가 편집기에서 곡선 그림 → 저장 → env_coordinator가 정확한 VPD 추종

#### 3.11.10 마이그레이션 헬퍼 (선택)

기존 `DailyMethod` 사용자가 `DailyMultiPointMethod`로 변환:
```python
def convert_daily_to_multipoint(daily_method_id) -> dict:
    # MethodData 행들의 (time_start, setpoint_start, time_end, setpoint_end)을
    # CurvePoint 리스트로 변환 (smooth=False, keyframes=[])
    ...
```

UI에 "이 메서드를 다중점으로 변환" 버튼 제공.

---

### 3.12 P3-4. 예보 기반 피드포워드

**입력**: 기상청 API 또는 OpenWeatherMap → 1~6시간 후 T_ext, 일사 예측.

**룰**:
- 일출 1시간 전: 강제 환기 예열 (실내 결로 방지)
- T_ext_forecast > 35°C 1시간 전: 차광 사전 전개
- 야간 → 주간 전환: VPD 목표 점진 변화 (slew 사용)

**구현**: `ext_context_collector`에 forecast 필드 추가, L3 `coordinate()`에 피드포워드 항 추가.

```
cmd_total = cmd_PI + α · cmd_feedforward
α = 0.3   (보수적 비중)
```

**의존성**: 외부 API 키 설정, 호출 빈도 제한(시간당 ≤ 60회).

---

### 3.13 P4-1. MCP 서버 — AoT 도구 노출 (신규, Track 4)

**사용자 요구사항**: "AoT 에는 AI 가 포함될 수 있습니다. AI 가 mcp 서버를 통해서 적절하게 사용할 수 있도록 가이드가 제공되어야 합니다."

**목적**: AI 에이전트(Claude/GPT 등)가 AoT 시스템을 **안전하게 관찰·진단·조정**할 수 있도록 표준 MCP(Model Context Protocol) 서버 제공.

**구조**:
```
[AI Agent (Claude Desktop / 외부)]
        │ MCP (stdio or HTTP)
        ▼
[AoT MCP Server]  ← 신규 (aot/mcp_server/)
        │ Python API
        ▼
[AoT 내부: DB, Daemon, Functions, Methods, Outputs]
```

**위치**: `aot/mcp_server/` (신규 패키지)
- `server.py` — MCP 서버 엔트리포인트 (FastMCP 권장)
- `tools/` — 도구 카테고리별 모듈
  - `tools/observe.py` — 읽기 전용 (센서, 상태, 로그)
  - `tools/diagnose.py` — 분석 (이상 감지, 추세, 비교)
  - `tools/control.py` — 쓰기 (setpoint, method, actuator) — **승인 필수**
- `safety.py` — 권한·경계 체크 (P4-3)
- `audit.py` — 감사 로그
- `manifest.py` — AI 가이드 (P4-2)

**노출 도구 목록 (초기)**:

| 카테고리 | 도구 | 권한 | 설명 |
|---------|------|------|------|
| **observe** | `list_facilities` | read | 시설 목록 |
| observe | `get_facility_state` | read | 시설 현재 환경값 (T, RH, VPD, CO2, Light) |
| observe | `get_sensor_history` | read | 센서 시계열 (1h/24h/7d) |
| observe | `list_functions` | read | 활성 Function 목록·상태 |
| observe | `get_function_state` | read | env_coordinator 등 사이클 상태 |
| observe | `list_methods` | read | Method 목록 + 곡선 데이터 |
| observe | `list_outputs` | read | 액추에이터 현재 명령값 |
| observe | `get_recent_events` | read | 최근 알림·이상 |
| **diagnose** | `analyze_control_performance` | read | 목표 추종 오차·진동 분석 |
| diagnose | `detect_sensor_anomaly` | read | 센서 이상치/드리프트 |
| diagnose | `suggest_setpoint_adjustment` | read | 현 상태 기반 권장값 (제안만, 미적용) |
| diagnose | `compare_periods` | read | 두 기간 비교 (e.g., "지난주 vs 이번주") |
| **control** | `update_method_point` | write/confirm | Method 점 1개 수정 |
| control | `set_vpd_target_static` | write/confirm | 정적 VPD setpoint 변경 |
| control | `acknowledge_alert` | write | 알림 확인 |
| control | `request_manual_lock` | write/confirm | 특정 액추에이터 수동 잠금 |

**도구 정의 표준 (FastMCP 사용)**:
```python
@mcp.tool()
async def get_facility_state(facility_id: str) -> dict:
    """
    Get current environmental state of a facility.

    Returns dict with: T_int, RH_int, VPD, CO2, Light, mode,
    last_update_iso, sensors_health.
    """
    return AoT_api.get_facility_state(facility_id)

@mcp.tool(requires_confirmation=True)
async def update_method_point(
    method_id: str,
    point_id: int,
    new_t_sec: int,
    new_value: float,
    reason: str,    # AI가 변경 이유 명시 — 감사 로그에 저장
) -> dict:
    """
    Update a single control point in a DailyMultiPointMethod.

    SAFETY: This changes setpoint behavior. Used must approve.
    Bounds-checked against method.value_min/max.
    """
    safety.check_method_write(method_id, new_value)
    audit.log("update_method_point", ...)
    return AoT_api.update_method_point(...)
```

**전송 방식**:
- **stdio** (로컬 데스크탑 AI 통합 — Claude Desktop, Cursor 등)
- **HTTP/SSE** (원격 AI 에이전트 — 인증 토큰 기반)

**의존성**: `mcp` (Anthropic Python SDK) 또는 `fastmcp`

---

### 3.14 P4-2. AI 에이전트 가이드 (스킬·매니페스트) (신규)

**목적**: AI가 AoT를 처음 접할 때 시스템 구조·정책·도구 사용법을 자체적으로 이해할 수 있도록 가이드 제공.

**구성 요소**:

#### A. AoT MCP 매니페스트 (`manifest.py` → `manifest.json` 동적 생성)

```json
{
  "system": "AoT - AI based Greenhouse Control",
  "version": "0.x",
  "description": "...",
  "capabilities": ["read sensors", "diagnose", "suggest", "modify with confirmation"],
  "domain_knowledge": {
    "primary_target": "VPD (Vapor Pressure Deficit)",
    "guide_variables": ["T", "RH"],
    "critical_variables": ["VPD", "Light", "CO2"],
    "safety_zones": "T 5~40°C, RH 20~95%, VPD 0~3 kPa"
  },
  "policies": {
    "write_requires_confirmation": true,
    "max_changes_per_session": 10,
    "rate_limit": "1 write per 30s",
    "forbidden": ["disable_safety_gate", "remove_method", "delete_facility"]
  },
  "best_practices_uri": "aot://docs/ai_guide.md"
}
```

#### B. AI 가이드 문서 (`docs/ai_guide.md`, 신규)

내용:
1. **시스템 개요** — 4계층 제어, Method, Facility, env_coordinator
2. **VPD 우선 정책** — T/RH는 가이드, VPD가 primary
3. **조정 시 고려 사항** — 작물·생육단계·시간대·외부날씨
4. **Method 수정 가이드라인** — 점진적 변화(2주에 걸쳐), 한 번에 다중 점 수정 금지
5. **이상 감지 시 워크플로** — 1) 데이터 확인 → 2) 진단 도구 → 3) 권장값 제시 → 4) 사용자 승인 요청
6. **금지 사항** — 안전게이트 비활성화, 액추에이터 수동 잠금 임의 해제, 학습 K_* 직접 수정
7. **예시 시나리오** — "VPD가 1.5 넘게 추종 실패 → 진단 → 환기 부족 의심 → 사용자에게 측창 점검 권장"

#### C. Claude Code 스킬 (`SKILL.md`, 옵션)

설치 시 AoT 디렉터리에 두면 Claude Code가 자동 인식:
```markdown
# AoT 온실 제어 시스템

## When to use
사용자가 온실 환경, 제어, 센서, 작물 관련 질문을 할 때.

## How to use
1. MCP 도구 `list_facilities`로 시작
2. `get_facility_state`로 현재 상태 확인
3. 진단 도구 활용
4. 변경 권장 시 사용자 승인 요청
...
```

#### D. 도구별 docstring 표준

모든 MCP 도구는:
- **명확한 한 줄 설명**
- **반환값 구조**
- **안전 경고** (write 도구)
- **예시 사용 패턴** (복잡한 도구)

---

### 3.15 P4-3. AI 작업 안전 경계 + 감사 로그 (신규, Critical)

**근거**: AI 오작동은 작물 손실로 직결. 사용자 피드백의 "작물 프로필은 민감한 부분"과 동일 맥락.

**3계층 안전 모델**:

| 계층 | 방어선 | 내용 |
|------|--------|------|
| 1. **권한** | 도구 단위 read/write 분리 | observe·diagnose는 자유, control은 confirmation 토큰 필요 |
| 2. **경계** | 값 범위 검증 | VPD 0~3, T 5~40, Method 점 일일 변동 ≤ 20% |
| 3. **사용자 승인** | write 작업 사전 승인 | UI 푸시 알림 + 만료 60s |

**구현 — `safety.py`**:

```python
@dataclass
class WriteBounds:
    field: str
    min_val: float
    max_val: float
    max_delta_per_call: float
    max_calls_per_hour: int

BOUNDS = {
    "method_point_value": WriteBounds("value", 0.0, 3.0, 0.3, 10),
    "vpd_target_static": WriteBounds("vpd", 0.3, 2.5, 0.5, 5),
    "manual_lock": WriteBounds(None, None, None, None, 3),
}

def check_write(tool_name, params, user_session) -> ConfirmationToken:
    bounds = BOUNDS[tool_name]
    if not bounds.in_range(params):
        raise SafetyViolation(...)
    if user_session.calls_this_hour(tool_name) >= bounds.max_calls_per_hour:
        raise RateLimitExceeded(...)
    return create_pending_confirmation(tool_name, params, ttl=60)
```

**감사 로그 — `audit.py`**:

신규 테이블 `mcp_audit_log`:
```sql
CREATE TABLE mcp_audit_log (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    agent_id TEXT,           -- AI 식별 (Claude/GPT/custom)
    tool_name TEXT NOT NULL,
    params_json TEXT,
    reason TEXT,             -- AI가 명시한 변경 이유
    confirmation_status TEXT, -- pending/approved/rejected/expired
    user_id TEXT,            -- 승인한 사용자
    result_json TEXT
);
```

**UI 통합**:
- 알림 페이지에 "AI 변경 요청 큐" 섹션 (대기 중인 confirmation 표시)
- 감사 로그 조회 페이지 (`/audit/mcp`)
- 사용자가 AI 권한을 일시 정지(`pause_mcp_writes`) 가능 — 비상시

**작물 프리셋 보호 (사용자 피드백 반영)**:
- AI는 시드 프리셋(`is_seed=True`)을 **수정 불가**
- 사용자가 복제한 Method만 수정 가능
- 프리셋 자체 변경은 사용자 UI에서만

**테스트 시나리오**:
- AI가 VPD 0.1로 변경 시도 → 경계 위반, 거부
- AI가 10초 내 5회 write 시도 → 레이트 리밋 차단
- 사용자 승인 60s 무응답 → 자동 만료
- AI가 작물 시드 프리셋 수정 시도 → 거부 + 감사 로그
- 시뮬레이션 모드(`dry_run=True`)에서는 모든 도구가 미적용으로 응답

> **표기 안내 (v1.1)**: Track 5의 Phase A~H는 본 Track의 **내부 순서**를 가리킨다. §3.8(P3-2′, 구 Phase E)·§3.9(P3-3, 구 Phase F)에 등장하는 Phase E/F는 Track 3의 단일 단계 표기로, Track 5와는 별개의 개념이다. Track 5에서는 충돌 회피를 위해 **Phase E′ / F′** (prime 표기)를 사용한다.

### 3.16 P5-1. Growth Schedule 컨텍스트 (Phase A·B 통합)

**사용자 통찰**: 시스템 도입 시점이 재배 사이클 중간(예: 3주차)일 수 있음. 또한 시간 진화는 VPD뿐 아니라 모든 환경 파라미터(CO2·광주기 등)에 적용되어야 하며, **시간축은 Function 한 곳에서 단일 관리**되어야 함.

#### 3.16.1 현재 결함

`_helpers_mixin.py`의 `_get_vpd_setpoint()`만이 `method_start_time`을 DB에서 읽어 `weeks_elapsed`를 계산. 다른 파라미터(CO2, 광주기, 광량)는 시간 진화 미지원. `_cycle_mixin.py:107-125`에 `T_target=24.0`, `RH_target=65.0` 하드코딩 잔존 (P1-1 미결선).

#### 3.16.2 Phase A — P1-1 L1 결선

**즉시 결함 제거** (Phase A는 P5와 독립이며 Phase B의 전제):

```python
# _cycle_mixin.py — 변경 후
vpd_target = self._get_vpd_setpoint()

T_aux, RH_aux = decompose_vpd_to_T_RH(
    vpd_target=vpd_target,
    T_int=internal['T'],
    RH_int=internal['RH'],
    w_T=self.vpd_decompose_weight_T or 0.6,
    constraints=TempRHBounds(
        T_min=self.guide_T_min, T_max=self.guide_T_max,
        RH_min=self.guide_RH_min, RH_max=self.guide_RH_max,
    ),
)

env_target = build_env_target(
    T_target=T_aux,         # 분해 결과 (하드코딩 제거)
    RH_target=RH_aux,       # 분해 결과 (하드코딩 제거)
    VPD_target=vpd_target,
    ...
)
```

신규 옵션 (`_function_info.py`):
- `vpd_decompose_weight_T` (float, default 0.6)
- `guide_T_min`, `guide_T_max`, `guide_RH_min`, `guide_RH_max`

#### 3.16.3 Phase B — Schedule 컨텍스트

**Function 단일 시간축**:

```python
# _helpers_mixin.py 신설
def _get_weeks_elapsed(self) -> float:
    """모든 Method가 공유하는 단일 weeks_elapsed."""
    start = self._load_or_init_schedule_start()  # DB 영속
    offset = float(self.schedule_week_offset or 0.0)
    elapsed = (utc_now() - start).total_seconds() / (7 * 86400)
    return max(0.0, elapsed + offset)
```

**Method API 확장**:

```python
# utils/method.py — calculate_setpoint 시그니처 확장
def calculate_setpoint(self, now, method_start_time=None, weeks_elapsed=None):
    # weeks_elapsed가 외부 주입되면 사용, 없으면 self.method_start_time 기반 계산 (하위 호환)
    if weeks_elapsed is None:
        weeks_elapsed = _compute_weeks(now, method_start_time)
    ...
```

신규 옵션:
- `schedule_start_time` (TEXT, ISO 8601, default NULL → 최초 실행 시 자동 저장)
- `schedule_week_offset` (FLOAT, default 0.0)

#### 3.16.4 Phase C — CO2 Method

```python
# _helpers_mixin.py 신설
def _get_co2_setpoint(self):
    method_id = self.co2_method_id_device_id
    if method_id:
        weeks = self._get_weeks_elapsed()
        sp, _ = self._co2_method_handler.calculate_setpoint(
            time.time(), weeks_elapsed=weeks)
        return sp
    return self.target_co2 or None  # 정적값 fallback
```

신규 옵션: `co2_method_id` (select_device → Method).

#### 3.16.5 Phase D — Photoperiod Method

**Method 반환값 = 광시간(h)**, Function이 `time_start`/`time_end`로 변환:

```python
def _get_time_window(self):
    method_id = self.photo_method_id_device_id
    if not method_id:
        return self.time_start or '06:00', self.time_end or '20:00'

    weeks = self._get_weeks_elapsed()
    hours, _ = self._photo_method_handler.calculate_setpoint(
        time.time(), weeks_elapsed=weeks)

    # 일출 중심 대칭 분배 (또는 사용자 설정 anchor)
    anchor = self.photo_anchor or '12:00'
    start_h = _hours_to_hhmm(anchor, -hours/2)
    end_h   = _hours_to_hhmm(anchor, +hours/2)
    return start_h, end_h
```

신규 옵션: `photo_method_id`, `photo_anchor` (default '12:00').

#### 3.16.6 하위 호환 매트릭스

| 상황 | 동작 |
|------|------|
| `schedule_start_time` 없음 | 최초 사이클에서 `utc_now()` 저장 (현재 동작 보존) |
| `schedule_week_offset` 없음 | 0.0 적용 → 동작 변화 없음 |
| `co2_method_id` 없음 | `target_co2` 정적값 사용 (현재와 동일) |
| `photo_method_id` 없음 | `time_start`/`time_end` 정적 문자열 사용 (현재와 동일) |
| `guide_T_*` 없음 | 12~32°C, 40~85% 기본 가이드 적용 |

#### 3.16.7 시설 위치 기반 시간대 처리 (v1.2 신규)

**원칙**: 변수별로 기준 시간대를 분리한다.

| 변수 | 기준 시간대 | 이유 |
|------|----------|------|
| `schedule_start_time` 저장 | **UTC (ISO 8601)** | 위치 이전·변경 대비, 시간대 무관 보관 |
| `weeks_elapsed` 계산 | **경과 초만** | 시간대 무관 |
| `t_sec` (하루 중 위치) | **시설 현지시간** | 광·VPD 일변동 곡선은 현지 기준 |
| UI 표시 | **시설 현지시간** | 사용자 직관 |

**현재 결함**: `method.py`의 `calculate_setpoint()`는 `datetime.utcfromtimestamp(now)`로 naive UTC를 사용해 `t_sec`을 계산. 한국(UTC+9) 시설에서는 일변동 곡선이 9시간 어긋남.

**해결**:

```python
# GeoFacility 모델 (필드 보강)
class GeoFacility(db.Model):
    ...
    timezone = db.Column(db.Text, default=None)   # 신규, IANA name (예: "Asia/Seoul")
    # lat/lon은 이미 보유 → fallback으로 자동 도출 가능

# utils/method.py — calculate_setpoint 시그니처 확장
def calculate_setpoint(self, now, method_start_time=None,
                       weeks_elapsed=None, facility_tz=None):
    if facility_tz:
        now_local = datetime.fromtimestamp(now, tz=facility_tz)
    else:
        now_local = datetime.utcfromtimestamp(now)   # 하위 호환
    t_sec = now_local.hour * 3600 + now_local.minute * 60 + now_local.second
    ...

# env_coordinator _helpers_mixin.py
def _get_facility_tz(self):
    fac = self._geo_facility
    if fac and fac.timezone:
        return ZoneInfo(fac.timezone)
    if fac and fac.latitude and fac.longitude:
        return ZoneInfo(_tz_from_latlon(fac.latitude, fac.longitude))  # timezonefinder
    return ZoneInfo('UTC')
```

**의존성**: `timezonefinder` 라이브러리 신규 추가 (lat/lon → IANA tz).

**하위 호환**: `facility_tz=None`이면 기존 UTC 동작 유지.

#### 3.16.8 시스템 중단·복구 처리 (v1.2 신규)

**정책**: **Wall-clock** — 중단 시간도 경과로 카운트한다.

**근거**: 시스템이 멈춰도 식물은 자연 환경에서 계속 생장한다. 사이클을 멈출 이유가 없다.

**동작**:

```python
def _get_weeks_elapsed(self):
    elapsed_sec = (utc_now() - self._schedule_start).total_seconds()
    return max(0.0, elapsed_sec / (7 * 86400) + self.schedule_week_offset)
```

- 중단 감지 로직 **없음**
- 자동 보상 **없음**
- `downtime_log`, `runtime_only_mode`, 4단계 임계값 분기 **모두 폐기**

**사용자 책임**:
- 장기 중단 후 사이클을 늦추고 싶으면 `schedule_week_offset`을 **음수**로 설정 (예: 1주 중단 → `-1.0`)
- 또는 `schedule_start_time`을 직접 미래로 옮겨 재시작
- UI는 최근 중단 시간을 **정보용으로만** 표시 (action 강제 없음)

**알림 (선택적)**:
- 24시간 이상 중단 후 재개 시 UI 배너에 "X일 중단 후 재개됨 — 필요 시 schedule_week_offset으로 조정" 표시
- 강제 모달·운전 보류 없음

---

### 3.17 P5-2. Control Authority — 시설 제어 권한 자동 도출

**사용자 통찰**: 모든 시설이 모든 환경 변수를 능동 제어하지 못함. setpoint를 줘도 도달 불가능한 변수가 있고, 이를 인식하지 않으면 적분 windup·잘못된 알림·무의미한 제어가 발생.

#### 3.17.1 권한 등급

| 등급 | 의미 | 도출 조건 |
|------|------|----------|
| **ACTIVE** | 능동 제어 가능 (액추에이터 보유) | 해당 변수에 직접 영향 액추에이터 등록 |
| **PASSIVE** | 수동/간접 제어 (외부 조건부) | 환기·차광·커튼 등 외부 의존 액추에이터 |
| **NATURAL** | 자연 의존, 제어 불가 | 영향 액추에이터 없음 |

#### 3.17.2 자동 도출 알고리즘

`_profiles` (등록 액추에이터)와 `effect_functions`의 부호 분석으로 변수별 권한 결정:

```python
# functions/utils/env_control/authority.py (신규)
def derive_authority(profiles: list[ActuatorProfile]) -> dict[str, str]:
    """변수 → ACTIVE/PASSIVE/NATURAL 매핑."""
    result = {'T_up': 'NATURAL', 'T_down': 'NATURAL',
              'RH_up': 'NATURAL', 'RH_down': 'NATURAL',
              'CO2_up': 'NATURAL', 'CO2_down': 'NATURAL',
              'Light_up': 'NATURAL', 'Light_down': 'NATURAL'}

    for p in profiles:
        if p.kind == 'heater':           result['T_up']    = 'ACTIVE'
        elif p.kind == 'cooler':          result['T_down']  = 'ACTIVE'
        elif p.kind == 'fogger':          result['RH_up']   = 'ACTIVE'
                                          result['T_down']  = max(result['T_down'], 'PASSIVE')
        elif p.kind == 'dehumidifier':    result['RH_down'] = 'ACTIVE'
        elif p.kind == 'co2_generator':   result['CO2_up']  = 'ACTIVE'
        elif p.kind == 'supplement_light':result['Light_up'] = 'ACTIVE'
        elif p.kind == 'shade':           result['Light_down'] = 'PASSIVE'
        elif p.kind == 'opening':         result['T_down']  = max(result['T_down'], 'PASSIVE')
                                          result['RH_down'] = max(result['RH_down'], 'PASSIVE')
                                          result['CO2_down'] = max(result['CO2_down'], 'PASSIVE')
        elif p.kind == 'thermal_curtain': result['T_up']    = max(result['T_up'], 'PASSIVE')
    return result
```

**관수 단독 시설** (사용자 통찰의 default 케이스):
- 관수 → `RH_up = ACTIVE` (증발로 RH 상승) → VPD 하강 가능
- 다른 모든 변수 → NATURAL
- 결과: VPD만 사실상 제어 가능 → v1.0 VPD-primary default가 자동으로 적용

#### 3.17.3 SituationReport 확장

```python
@dataclass
class SituationReport:
    ...
    authority: dict[str, str]   # 신규: 변수별 권한
    mode: str                   # 확장: normal/forced/safe/manual_lock
                                #       + degraded/natural/unattainable
```

#### 3.17.4 Anti-Windup 보강

권한 없는 변수는 PI 적분기 freeze:

```python
# coordinator.py
for var in env_target:
    if authority.get(f'{var}_up') == 'NATURAL' and authority.get(f'{var}_down') == 'NATURAL':
        state.integral[var] = 0.0   # 적분 freeze
        continue
    # 권한 있는 경우만 PI 갱신
```

#### 3.17.5 운전 모드 확장

| 모드 | 발동 조건 | 동작 |
|------|---------|------|
| `degraded` | 일부 변수 NATURAL | best-effort, 도달가능 변수만 PI |
| `natural` | 모든 능동 변수 NATURAL | 외기 추적만, 명령 산출 안 함 |
| `unattainable` | 목표 도달 불가 (외기 한계) | 자동 완화 + 사용자 알림 |

---

### 3.18 P5-3. Passive/Natural 전략 + 사전 동작

#### 3.18.1 PASSIVE 변수의 예보 기반 사전 동작

```python
# coordinator.py 확장
# 가열기 없는 시설 + 한파 예보
if authority['T_up'] == 'PASSIVE' and forecast.T_ext_min < 5:
    pre_action = {
        'thermal_curtain': 1.0,   # 완전 폐쇄
        'side_opening':    0.0,   # 환기 차단
    }
```

P3-4 (예보 기반 피드포워드)와 결합되어 동작.

#### 3.18.2 목표 자동 완화 정책

```python
# unattainable 모드 진입 시
def degrade_target(env_target, authority, external):
    if authority['T_up'] == 'NATURAL':
        env_target['T'].value = max(env_target['T'].value, external['T_ext'])
        env_target['T'].degraded = True
    # ... 다른 변수도 동일
    return env_target
```

#### 3.18.3 사용자 알림

| 상황 | 채널 | 메시지 |
|------|------|--------|
| 변수 NATURAL 진입 | UI 배너 | "광량 제어 불가 — 자연광 의존" |
| Unattainable | UI 알림 + 이메일 | "T 목표 22°C 달성 불가 (외기 28°C, 냉방 미보유)" |
| Authority 변경 | 감사 로그 | 액추에이터 등록 변경 시 권한 재산출 기록 |
| MCP 도구 | `report_unattainable_goals()` | AI가 자동 인지하고 사용자에게 보고 |

---

### 3.19 P5-4. Photosynthesis-oriented Goal (광합성 모델)

**사용자 통찰**: VPD는 광합성의 한 게이트 변수일 뿐. 실제 목표는 광합성(또는 생장). 시설이 능동 제어 가능한 변수가 늘어나면 광합성 모델 기반 우선순위 결정이 필요.

#### 3.19.1 광합성 모델 (단순화 Big-Leaf)

```python
# functions/utils/env_control/photosynthesis.py (신규)
def estimate_net_photosynthesis(
    L: float,       # PPFD μmol/m²/s
    CO2: float,     # ppm
    T: float,       # °C
    VPD: float,     # kPa
    crop_params: CropParams,
) -> float:
    """A_n (μmol CO2/m²/s) 추정."""
    # 1. 광 응답 (rectangular hyperbola)
    A_light = (crop_params.A_max * L) / (L + crop_params.K_L)

    # 2. CO2 응답 (Michaelis-Menten 형)
    A_co2 = A_light * (CO2 / (CO2 + crop_params.K_C))

    # 3. T 응답 (Q10 + 최적 온도)
    T_factor = exp(-((T - crop_params.T_opt) ** 2) / (2 * crop_params.T_sigma ** 2))

    # 4. VPD 응답 (기공 전도 감소)
    g_stomata = 1.0 / (1.0 + (VPD / crop_params.VPD_half) ** 2)

    return A_co2 * T_factor * g_stomata
```

작물 파라미터는 P3-2′ 작물 프리셋과 연동 (시드 5종 부터).

#### 3.19.2 제한인자 자동 식별

```python
def find_limiting_factor(L, CO2, T, VPD, params):
    base = estimate_net_photosynthesis(L, CO2, T, VPD, params)
    sensitivities = {
        'Light': estimate_net_photosynthesis(L * 1.1, CO2, T, VPD, params) - base,
        'CO2':   estimate_net_photosynthesis(L, CO2 * 1.1, T, VPD, params) - base,
        'T':     estimate_net_photosynthesis(L, CO2, T + 1, VPD, params) - base,
        'VPD':   estimate_net_photosynthesis(L, CO2, T, VPD * 0.9, params) - base,
    }
    return max(sensitivities, key=sensitivities.get)
```

**Authority 결합** (P5-2):
- 제한인자가 ACTIVE이면 → 그 변수 priority 격상
- 제한인자가 NATURAL이면 → 외기 변수로 받아들이고 다음 후보 검토

#### 3.19.3 build_env_target 동적 우선순위

```python
# goal.py 확장
def build_env_target(..., photosynth_mode=False, internal=None, authority=None):
    if not photosynth_mode:
        return _legacy_static_priorities(...)   # v1.0 default

    limiting = find_limiting_factor(...)
    if authority.get(f'{limiting}_up') in ('ACTIVE', 'PASSIVE'):
        # 제한인자 priority 일시 격상
        priorities[limiting] *= 1.5
    return EnvTarget(..., priorities=priorities)
```

#### 3.19.4 안정성 분석

순환 의존성(limiting → priority → control → environment → limiting) 발생 가능:
- **완화책**: 우선순위 변경은 사이클당 최대 ±20%, 이력 평활화 (지수가중평균 α=0.3)
- **상한**: 어느 변수도 priority가 기본값의 2배 초과 불가

---

### 3.20 P5-5. Cumulative Goal Tracker (DLI·GDD 누적 부채)

**사용자 통찰**: 순시 setpoint 추종이 완벽해도 누적 성과(DLI·GDD·생장량)는 부족할 수 있음. 흐린 일주일, 한파 등 외란이 누적되면 보상 또는 목표 재조정이 필요.

#### 3.20.1 누적 메트릭

| 메트릭 | 단위 | 정의 |
|--------|------|------|
| **DLI** | mol/m²/day | 일적산광량 = ∫ PPFD dt (일 단위) |
| **GDD** | °C·day | 누적온도 = Σ max(0, T_mean - T_base) |
| **VPD-hours** | kPa·h | VPD 노출 누적 |
| **CO2-hours** | ppm·h | CO2 노출 누적 |

#### 3.20.2 DB 스키마

```python
# aot/databases/models/function_cumulative.py (신규)
class FunctionCumulativeState(db.Model):
    __tablename__ = 'function_cumulative_state'
    function_id = db.Column(db.Text, primary_key=True)
    date        = db.Column(db.Date, primary_key=True)
    dli_actual  = db.Column(db.Float)     # mol/m²
    dli_target  = db.Column(db.Float)
    gdd_actual  = db.Column(db.Float)
    gdd_target  = db.Column(db.Float)
    debt_dli    = db.Column(db.Float)     # target - actual (양수면 부족)
    debt_gdd    = db.Column(db.Float)
    compensation_attempted = db.Column(db.Text)  # JSON
    updated_at  = db.Column(db.Float)
```

#### 3.20.3 보상 전략 룰

| 부채 | ACTIVE 보상 | PASSIVE 보상 | 불가 시 |
|------|---------|---------|---------|
| DLI 부족 | 보광등 시간/강도 증가 | 차광 축소, 환기 최소화 | 사용자 알림 + 목표 완화 |
| GDD 부족 | 야간 T 상향 (보상 범위 내) | 보온커튼 사전 폐쇄 | 사이클 연장 권고 |
| GDD 과잉 | 냉방·환기 증가 | 차광 증대, 환기 증대 | 야간 환기 강화 |

#### 3.20.4 보상 한계와 안전장치

- 일 단위 누적은 24:00에 마감, 다음 날 00:00에 새 누적 시작
- 부채 보상은 **다음 1~3일 평균**으로 분산 (당일 무리한 보상 금지)
- 보상량은 정상 목표의 ±15% 이내 (예: T_target 22°C → 보상 시 최대 22 × 1.15 = 25.3°C)
- 작물 단계 전환 시(예: 영양생장 → 개화) 부채는 reset (단계별 독립 회계)

#### 3.20.5 사용자 가시화

- UI 대시보드: DLI/GDD 일별 추이 차트 + 부채 누적 그래프
- MCP 도구 `get_cumulative_status()`: AI가 부채 인지하고 사용자와 협의
- 주간 보고: 매주 일요일 누적 vs 목표 요약

---

### 4.1 GeoFacility 컬럼 (변경 없음, JSON 필드 확장)

```json
{
  "actuators": {
    "slot_1": {
      "kind": "opening",
      "output_id": "...",
      "channel": 0,
      "azimuth_deg": 90,       // 자동 채움 (P2-1)
      "area_m2": 12.5,         // 자동 채움 (P2-1)
      "...": "..."
    }
  },
  "computed": {
    "vent_open_m2": 25.0,
    "u_effective": 4.5,
    "envelope_m2": 200.0,
    "volume_m3": 600.0         // 신규 (P3-1)
  },
  "timezone": "Asia/Seoul"     // 신규 (P5-1, v1.2) — IANA name, NULL이면 lat/lon에서 자동 도출
}
```

### 4.2 CustomController.custom_options 확장 (v0.2 갱신)

```json
{
  // VPD 목표값 — Method 시스템 활용 (P3-2′)
  "vpd_source": "method",               // "static" | "method"
  "vpd_method_id": "uuid-tomato-vpd",
  "vpd_method_start_time": "2026-03-01T00:00:00",
  "vpd_static": 1.0,                    // vpd_source=static 또는 method finished fallback
  "vpd_decompose_weight_T": 0.6,        // P1-1

  // T/RH는 가이드(권고)만 — 강제 setpoint 아님
  "guide_T_min": 12,
  "guide_T_max": 32,
  "guide_RH_min": 40,
  "guide_RH_max": 85,

  // 기타
  "auto_calibration_enabled": false,    // P3-3
  "forecast_enabled": false,            // P3-4
  "ext_context_function_id": "...",     // P2-2 명시적 참조
  "degraded_mode_after_sec": 90,        // P2-2 (60s 주기의 1.5배)

  // Track 5 — Growth Schedule (P5-1, v1.2)
  "schedule_start_time": "2026-03-01T00:00:00Z",  // ISO 8601 UTC, NULL → 자동 저장
  "schedule_week_offset": 0.0,                    // 주 단위 (직접 입력)
                                                  //   양수: 도입 시점 보정 (예: 3.0 = 3주차부터)
                                                  //   음수: 중단·지연 보상 (예: -1.0 = 1주 차감)

  // Track 5 — 파라미터별 Method 연결 (P5-1)
  "co2_method_id": "",                  // 선택, 없으면 target_co2 정적값
  "target_co2": 1000.0,                 // CO2 정적 fallback
  "photo_method_id": "",                // 선택, 없으면 time_start/end 정적값
  "photo_anchor": "12:00",              // 광주기 중심 시각

  // Track 5 — Authority (P5-2, 자동 도출, 사용자 미설정)
  // 런타임 산출 결과만 SituationReport에 노출

  // Track 5 — Photosynthesis Goal (P5-4, opt-in)
  "photosynth_mode_enabled": false,     // ACTIVE 액추에이터 ≥ 3종일 때 권장
  "crop_params_id": "",                 // 작물 프리셋 참조 (P3-2′ 시드 5종)

  // Track 5 — Cumulative Tracker (P5-5, opt-in)
  "cumulative_tracker_enabled": false,
  "dli_target_daily": 18.0,             // mol/m²/day (작물별 권장값 자동 채움)
  "gdd_base_temp": 10.0,                // °C (작물별)
  "compensation_max_pct": 15.0          // 부채 보상 한계 (±15%)
}
```

### 4.3 GeoFacility.actuators 확장 — 그룹 지원 (P2-4)

```json
{
  "actuators": {
    "slot_LR_sidewindow": {
      "kind": "opening",
      "group": {
        "mode": "windward_diff",
        "windward_select": {"azimuth_tol_deg": 60},
        "members": [
          {"output_id": "uuid-L", "channel": 0, "azimuth_deg": 270, "area_m2": 12.5},
          {"output_id": "uuid-R", "channel": 0, "azimuth_deg": 90,  "area_m2": 12.5}
        ]
      }
    },
    "slot_double_curtain": {
      "kind": "thermal_curtain",
      "group": {
        "mode": "multi_stage",
        "stage_priority": [0, 1],
        "members": [
          {"output_id": "uuid-C1", "channel": 0, "u_value": 4.0},
          {"output_id": "uuid-C2", "channel": 0, "u_value": 2.5}
        ]
      }
    },
    "slot_single_legacy": {              // 하위 호환 (group 없음)
      "kind": "opening",
      "output_id": "uuid-X",
      "channel": 0
    }
  },
  "computed": {
    "volume_m3": 600.0                   // P3-1 (fan ACH 계산용)
  }
}
```

### 4.4 Actions.custom_options 확장

```json
{
  "kind": "exhaust_fan",                // P3-1 신규 종류
  "k_override": {...},
  "k_learned": {                        // P3-3
    "temp": 0.42, "humid": -0.15,
    "updated_at": "2026-05-16T10:00:00Z",
    "samples": 1024, "variance": 0.003
  }
}
```

### 4.5 신규 테이블 — function_runtime_state (P2-5)

```sql
CREATE TABLE function_runtime_state (
    function_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    last_heartbeat TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
CREATE INDEX idx_frs_heartbeat ON function_runtime_state(last_heartbeat);
```

**저장 내용**: PI 적분항, last_cmd, k_learned, last_cycle_ts.
**용도**: 데몬 재시작 시 복원 + 외부 워치독이 last_heartbeat로 hang 감지.

### 4.6 신규 테이블 — function_cumulative_state (P5-5)

```sql
CREATE TABLE function_cumulative_state (
    function_id TEXT NOT NULL,
    date DATE NOT NULL,
    dli_actual REAL,
    dli_target REAL,
    gdd_actual REAL,
    gdd_target REAL,
    debt_dli REAL,
    debt_gdd REAL,
    compensation_attempted TEXT,      -- JSON: {"dli": "extend_photoperiod_2h", ...}
    growth_stage TEXT,                -- "seedling"/"vegetative"/...
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (function_id, date)
);
CREATE INDEX idx_fcs_function_date ON function_cumulative_state(function_id, date);
```

**저장 내용**: 일별 누적 메트릭, 부채, 보상 시도 이력.
**용도**: DLI·GDD 부채 추적, 보상 전략 결정, 사용자 대시보드.

### 4.7 DB 마이그레이션

- JSON 필드 확장 (4.2~4.4): Alembic 마이그레이션 **불필요**
- `function_runtime_state` 신규 테이블 (4.5): Alembic 마이그레이션 **필요 (1개)**
- `function_cumulative_state` 신규 테이블 (4.6): Alembic 마이그레이션 **필요 (1개)** — Track 5 P5-5 단계에서

---

## 5. 마이그레이션·롤아웃 계획

| 단계 | 작업 | 위험 | 롤백 |
|------|------|------|------|
| 0 | 설계 문서 합의 (현재) | None | - |
| 1 | Track 1 (P1-1~3) — 안전 개선, 비파괴 | Low | 코드 revert |
| 2 | Track 2 (P2-1~3) — 구조 개선, 회귀 가능 | Mid | env_coordinator.py 원본 보존 |
| 3 | Track 3 (P3-1~5) — 신기능, opt-in | Low (기본 off) | 옵션 비활성화 |
| 4 | Track 4 (P4-1~3) — AI/MCP, opt-in | Mid (write 기본 off로 완화) | MCP 서버 비활성화 |
| 5a | Track 5 Phase A (L1 결선) — 결함 제거 | Low | 코드 revert (T/RH 하드코딩 복원) |
| 5b | Track 5 Phase B~D (Schedule + Method 확장) | Low | schedule_* 옵션 무시 시 기존 동작 |
| 5c | Track 5 Phase E′~F′ (Authority + Passive) | Mid | 자동 도출 disable 플래그 |
| 5d | Track 5 Phase G (Photosynthesis, opt-in) | High | `photosynth_mode_enabled=false` |
| 5e | Track 5 Phase H (Cumulative, opt-in) | Mid | `cumulative_tracker_enabled=false`, 테이블 보존 |

**각 Track 완료 기준**:
- Track 1: 모든 신규 단위 테스트 통과, 기존 동작 회귀 없음
- Track 2: facility 저장→사이클 실행 E2E 정상, degraded 모드 수동 트리거 검증
- Track 3: 작물 프로필로 24시간 운전, 명령 곡선 합리적, 자동 캘리브레이션 1주 안정

---

## 6. 테스트 전략

### 6.1 단위 테스트 (P1-2)
- pytest, env_control 80%+ 커버리지
- mock 시계, mock InfluxDB 클라이언트

### 6.2 통합 테스트
- 신규 `tests/integration/test_env_coordinator_e2e.py`
- in-memory SQLite facility + mock actuators + 가짜 외부센서로 1시간 사이클 실행 시뮬레이션

### 6.3 검증 시나리오 (수동)
1. **VPD 목표 추종**: T=22, RH=60에서 VPD=1.0 → 1.5 목표 변경 시 액추에이터 조합 합리적인가
2. **풍향 차등**: wind_dir=90°(동풍) 시 동쪽 천창만 닫히는가
3. **degraded 모드**: 외부센서 강제 정지 시 데드밴드 확장 + UI 경고
4. **작물 프로필**: 토마토 영양생장기 24시간 곡선 따라 setpoint 변화
5. **자동 캘리브레이션**: 24시간 실데이터로 K_learned 수렴

---

## 7. 결정 사항 (사용자 확인 필요, v1.1 갱신)

### 7.1 VPD 분해 가중치 기본값 — **결정 완료** ✅
- **옵션 A 채택**: `w_T = 0.6` (환기·차광 가능 범위가 RH 조절보다 넓음)
- UI에서 사용자 슬라이더로 0.0~1.0 조정 가능

### 7.2 시계열 저장 백엔드 — **결정 완료** ✅
- **InfluxDB 사용** — AoT 기존 측정값 인프라 활용
- env_control 채널 키 명명 규약 (§3.3 P1-3):
  - measurement: `env_control`
  - tag: `function_id`, `facility_id`, `actuator_id`(선택)
  - field: `T_int`, `RH_int`, `VPD_int`, `cmd`, `residual`, `mode`, `limiting_factor` 등
- 사이클당 1개 point 일괄 write

### 7.3 작물 Method 프리셋 — **결정 완료** ✅
- **시드 작물 5종**: 토마토, 딸기, 상추, 파프리카, 고추
- 단계별 (초기/중기/수확) Method 시드 제공
- **민감한 영역** — 사용자 피드백 반영:
  - 모든 프리셋은 **보수적 기본값** (극단 회피)
  - 한국 농가 일반 권장 범위 우선, 출처 명시(농촌진흥청/시설원예연구소 등 검증된 문헌)
  - UI에 "프리셋은 시작점일 뿐, 본 농가 환경에 맞게 조정 필요" 경고
  - 프리셋 수정 시 원본 유지(읽기전용), 사용자 복제본만 수정 가능
- 저장 위치: `aot/data/method_presets/<crop>_<stage>.json` (시드 파일)
- 설치/업데이트 시 DB에 자동 import (덮어쓰지 않음 — 신규만 추가)

### 7.4 CI 통합 — **결정 완료** ✅
- 현 단계: 로컬 pytest로만 실행 (`pytest aot/functions/utils/env_control/tests/`)
- **장기 계획**: GitHub 업로드 시 CI(Actions) 통합 — 별도 후속 작업으로 분리, 본 설계서에서는 테스트 코드만 준비
- 테스트 구조는 CI 통합 시 즉시 활용 가능하도록 표준 pytest 구조로 작성

### 7.5 VPD source UI 위치 — **결정 완료** ✅
- `function_options/custom_function_options.html`의 기존 `custom_options` 자동 렌더링 메커니즘 활용
- **AoT 표준 패턴**: Function 클래스에 `CUSTOM_OPTIONS` 스키마(dict) 선언 → UI 자동 생성 (`custom_function_options.html:226 {% for each_option in dict_options['custom_options'] %}`)
- env_coordinator의 `CUSTOM_OPTIONS`에 다음 항목 **추가만** 하면 됨 (HTML 직접 수정 최소화):
  ```python
  CUSTOM_OPTIONS = [
      ...
      {"id": "vpd_source", "type": "select",
       "options_select": [("static", "정적"), ("method", "Method"), ("crop_preset", "작물 프리셋")],
       "default": "static", "name": "VPD 소스"},
      {"id": "vpd_method_id", "type": "select_measurement",  # method 선택기
       "name": "Method", "phrase": "Daily/MultiPoint Method 선택"},
      {"id": "crop_preset_id", "type": "select",
       "options_select": [("tomato_initial", "토마토 초기"), ...],
       "name": "작물 프리셋"},
      {"id": "guide_T_min", "type": "float", "default": 12.0, "name": "T 가이드 최저"},
      {"id": "guide_T_max", "type": "float", "default": 32.0, "name": "T 가이드 최고"},
      {"id": "guide_RH_min", "type": "float", "default": 40.0, "name": "RH 가이드 최저"},
      {"id": "guide_RH_max", "type": "float", "default": 85.0, "name": "RH 가이드 최고"},
      {"id": "vpd_weight_T", "type": "float", "default": 0.6,
       "constraints_pass": lambda v: 0.0 <= v <= 1.0, "name": "VPD 분해 T 가중치"},
  ]
  ```
- 별도 HTML 작성 불필요 — base function options 패턴 그대로 활용

### 7.6 복합 액추에이터 그룹 — **결정 완료** ✅ (권장값 채택)
- **옵션 A 채택**: 1단계 — `symmetric` + `windward_diff` 우선 구현
- `stacked`, `multi_stage`는 2단계 (필요 시 추가)

### 7.7 데몬 재시작 워치독 — **결정 완료** ✅ (권장값 채택)
- **옵션 A 채택**: Alembic scheduler에 watchdog job 등록
- 데몬 자체 다운 시에도 외부 감지 가능

### 7.8 PI 상태 영속화 주기 — **결정 완료** ✅ (권장값 채택)
- **옵션 A 채택**: 매 사이클 끝 (60s 주기, 분당 1회 DB write)
- 재시작 시 stale 윈도우 < 60s

### 7.9 Method 편집기 — 결정 완료 (P3-5)
사용자 답변 반영 완료:
- ✅ 키프레임 해석: **여러 주차 키프레임 보간** (W0, W4, W8... 선형 보간)
- ✅ 끝점 제약: **시간 고정(0h/24h), 값 변경 가능**
- ✅ 최대 점: **12개**
- ✅ UI 위치: **method-build.html 확장** (신규 타입 `daily_multipoint`)

### 7.10 Method 편집기 — **결정 완료** ✅ (권장값 채택)
- 차트 라이브러리: P3-5 구현 직전에 기존 method-build.html 확인 후 통일
- 기존 DailyMethod 변환 도구: 제공 (선택적 버튼)
- 주차 슬라이더 범위: **W0~W26 (6개월)**

### 7.11 MCP 서버 — **결정 완료** ✅ (권장값 채택)
- 전송 방식: **stdio 우선** (Claude Desktop·Cursor 등 데스크탑 통합), HTTP 후속
- 초기 노출 도구: **observe + diagnose만 (read-only)** — 1차 릴리스
- control 도구는 P4-3 안전 경계 통과 후 단계적 활성화

### 7.12 AI 안전 경계 — **결정 완료** ✅ (권장값 채택)
- 사용자 승인 방식: **웹 UI 알림 + 60s 만료**
- AI 권한 기본 상태: **write 기본 OFF**, 사용자가 명시 활성화
- 감사 로그 보존 기간: **90일**

### 7.13 AI 가이드 문서 — **결정 완료** ✅
- 작성 언어: **한국어 + 영어 병기**
- 위치: `docs/ai_guide.ko.md`, `docs/ai_guide.md`

### 7.14 Growth Schedule — **결정 완료** ✅ (P5-1)
- ✅ **schedule_start_time 기본 동작**: 최초 사이클에서 `utc_now()` 자동 저장 (UTC 기준)
- ✅ **schedule_week_offset UI**: **주 단위 직접 입력**, default 0.0 (양수=시작 보정, 음수=중단 보상)
- ✅ **Method API 하위 호환**: `calculate_setpoint(weeks_elapsed=None)` 추가, 기존 호출 보존
- ✅ **Method 단독 사용 시나리오**: 기존 `method_start_time` 동작 보존 (PID 등)
- ✅ **시간대 처리**: 시설 위치 기반 (§3.16.7 참조)

### 7.15 Control Authority — **결정 완료** ✅ (P5-2)
- ✅ **권한 도출 방식**: 자동 도출 (`_profiles` + `effect_functions` 부호 분석)
- ✅ **사용자 override**: 자동 도출 결과 UI 표시, 수동 등급 변경 가능
- ✅ **Anti-windup 적용 시점**: Phase E′ 도입과 동시 — NATURAL 변수 적분 freeze
- ✅ **권한 변경 감사**: `_profiles` 변경 시 권한 재산출 + 감사 로그

### 7.16 Passive/Natural 전략 — **결정 완료** ✅ (P5-3)
- ✅ **목표 자동 완화 정책**: 시스템 제안 → 사용자 승인 후 완화
- ✅ **알림 채널**: UI 배너(즉시) + 이메일(1일 1회 요약) + MCP 도구(AI 인지)
- ✅ **Degraded 모드 setpoint 표시**: 원 목표 + 도달가능 목표 **둘 다 표시**
- ✅ **예보 기반 사전 동작**: P3-4(예보 피드포워드)와 결합, opt-in (기본 OFF)

### 7.17 광합성 모델 + 누적 트래커 — **결정 완료** ✅ (P5-4, P5-5)
- ✅ **광합성 모델 수준**: **Big-Leaf 단순** — 4변수 (L·CO2·T·VPD), 작물별 파라미터 5~7개
- ✅ **누적 메트릭 범위 (Phase 1)**: DLI + GDD (VPD-hours·CO2-hours·수분·EC는 Phase 2)
- ✅ **보상 자동화 수준 (단계적)**: 1단계 제안만 → 2단계 사용자 활성화 시 자동 실행
- ✅ **에너지 예산 추적**: Phase H에서 보류, **별도 Track 6**로 분리

### 7.18 시간대 + 시스템 중단 처리 — **결정 완료** ✅ (v1.2 신규, P5-1)
- ✅ **시간대 처리**: 시설 위치(`GeoFacility.timezone` 또는 lat/lon)에서 자동 도출, `t_sec`은 현지시간 기준 — `schedule_start_time`은 UTC 보관
- ✅ **시스템 중단 정책**: **Wall-clock** — 중단 시간도 경과로 카운트
  - 근거: 시스템이 멈춰도 식물은 자연 환경에서 계속 생장
  - 자동 감지 분기·운전 보류·downtime_log·runtime_only_mode 모두 폐기
- ✅ **사용자 보상 수단**: `schedule_week_offset`을 음수로 직접 조정 (예: 1주 중단 → `-1.0`)
- ✅ **재개 알림**: 24시간 이상 중단 후 재개 시 UI 배너에 정보 표시 (action 강제 없음)
- ✅ **신규 의존성**: `timezonefinder` 라이브러리 (lat/lon → IANA tz, 후속 추가 §9.C)

---

## 8. 작업 순서 (v1.1 갱신, Track 5 추가)

```
Track 1 (안정성·정확도, ~2일) — 완료
  P1-2 → P1-1 → P1-3
  (테스트 인프라 먼저, 그 위에 알고리즘 변경, 마지막 로깅)

Track 2 (시스템 연계 + 신규 항목, ~5~7일)
  P2-3 → P2-5 → P2-2 → P2-4 → P2-1
  (모듈 분리 → 재시작 안전성 인프라(DB 테이블) → fallback → 그룹 액추에이터 → 헬퍼)
  주의: P2-4(그룹)는 P2-3(모듈분리) 위에 얹기, P2-5(상태영속)는 신규 테이블 마이그레이션 포함

Track 3 (고도화, ~3주)
  P3-5 (Method 편집기 — 단독 모듈, UI 비중 큼, 단위 테스트 쉬움) ← UI 작업 선행
  P3-2′ (Method 시스템 활용 VPD 곡선 + 작물 프리셋 시드 5종 — P3-5 위에 자연 통합)
  P3-1 (fan/ACH)
  P3-3 (자동 캘리브레이션 — P2-5 위에 얹기, k_learned 영속화)
  P3-4 (예보 피드포워드)
  (P3-5 → P3-2′ 순서 권장: 편집기 먼저 만들면 P3-2′ 검증이 쉬움)

Track 4 (AI/MCP 통합, ~2주)
  P4-3 (안전 경계 인프라 — 가장 먼저, 다른 P4 항목 의존)
  P4-1 (MCP 서버 + observe/diagnose 도구) ← read-only 우선
  P4-2 (AI 가이드 문서·매니페스트)
  P4-1+ (control 도구는 P4-3 안전 검증 통과 후 단계적 활성화)
  (Track 4는 Track 3와 일부 병행 가능 — 데이터 모델은 독립)

Track 5 (Goal-Oriented Architecture, ~3~4주) — v1.1 신규
  Phase A: P1-1 L1 결선                          (~0.5일, 위험 Low)
    • _cycle_mixin.py 하드코딩 제거
    • decompose_vpd_to_T_RH() 호출 통합
    • guide_T_min/max, guide_RH_min/max 옵션
    • 회귀 테스트: 기존 정적 24°C/65% 동작 보존 확인

  Phase B: P5-1 Growth Schedule 컨텍스트         (~2일, 위험 Low)
    • schedule_start_time (UTC), schedule_week_offset (주 단위) 옵션
    • _get_weeks_elapsed() Function 단일화 (Wall-clock)
    • GeoFacility.timezone 필드 + lat/lon fallback (timezonefinder)
    • Method.calculate_setpoint(weeks_elapsed=, facility_tz=) 시그니처 확장
    • 중단 후 재개 알림 (24h 이상 시 UI 배너, action 강제 없음)
    • 하위 호환: 기존 method_start_time 동작 보존
    • 단위 테스트: 오프셋 적용 / 미적용 / 음수 / 큰 값

  Phase C: P5-1 CO2 Method 연결                  (~0.5일, 위험 Low)
    • co2_method_id 옵션
    • _get_co2_setpoint() (B의 패턴 복제)

  Phase D: P5-1 Photoperiod Method 연결          (~1일, 위험 Low)
    • photo_method_id, photo_anchor 옵션
    • Method float(시간) → time_start/end HH:MM 변환
    • _in_time_window() 리팩터

  Phase E′: P5-2 Control Authority 자동 도출     (~2일, 위험 Mid)
    • authority.py 신설 (변수×액추에이터 매핑)
    • SituationReport.authority 필드 추가
    • Anti-windup 보강 (NATURAL 변수 적분 freeze)
    • 운전 모드 확장: degraded / natural / unattainable
    • 단위 테스트: 시설 조합별 권한 도출

  Phase F′: P5-3 Passive/Natural 전략            (~2일, 위험 Mid)
    • PASSIVE 변수 예보 기반 사전 동작 (P3-4 결합)
    • 목표 자동 완화 정책 (사용자 승인 모드)
    • UI 배너 + 이메일 알림
    • Degraded 모드 setpoint 표시 (원 / 도달가능 둘 다)

  Phase G: P5-4 Photosynthesis Goal (opt-in)     (~5일, 위험 High)
    • photosynthesis.py 신설 (Big-Leaf 모델)
    • find_limiting_factor() 구현
    • build_env_target 동적 우선순위 모드 추가
    • 작물 파라미터 시드 5종 (P3-2′ 연동)
    • 안정성 검증: 우선순위 진동 방지 (평활화 α=0.3)

  Phase H: P5-5 Cumulative Goal Tracker          (~3일, 위험 Mid)
    • function_cumulative_state 테이블 + Alembic 마이그레이션
    • 일별 DLI/GDD 누적 + 부채 계산
    • 보상 전략 룰 (Phase 1: 제안만)
    • 사용자 대시보드 + MCP get_cumulative_status() 도구
    • 주간 보고 (일요일 자동)

  순서 의존성:
    Phase A → B → (C ∥ D ∥ E′)
    E′ → F′
    E′ → G (Authority가 광합성 모델 입력 결정)
    B → H (Schedule이 누적 기간 결정)
    G + H 병행 가능 (데이터 모델 독립)
```

각 작업 항목은 **독립 커밋 + 회귀 테스트 + done 보고**로 마무리.

---

## 9. 부록

### A. 참고 코드 위치 (현재)
- `env_coordinator.py:552-846` 프로필 로더
- `env_coordinator.py:976-999` 사이클 본체
- `coordinator.py:66-150` 조율 메인 루프
- `effect_functions.py:45-200` GIS 가중·기본 효과
- `safety_gates.py:1020-1038` 풍향 차등(G4)

### B. 용어
- **VPD**: Vapor Pressure Deficit (포차)
- **ACH**: Air Changes per Hour
- **DLI**: Daily Light Integral
- **PI**: Proportional-Integral
- **RLS**: Recursive Least Squares
- **MPC**: Model Predictive Control (본 설계는 룰베이스 피드포워드 수준까지만 포함)
- **G1~G4**: GIS 통합 Phase 하위 항목

### C. 의존성 신규 추가
- `pyproj` (P2-1, geodesic 면적)
- `pyyaml` (P3-2, 작물 프로필 — 이미 있을 가능성 높음)
- `timezonefinder` (P5-1, v1.2 — lat/lon → IANA tz name; GeoFacility.timezone 미설정 시 fallback)
- (외부 API 클라이언트는 P3-4 단계에서 결정)

---

**검토 후 §7의 5개 결정사항에 답을 주시면 본 문서를 v1.0으로 확정하고 4단계 구현에 들어갑니다.**
