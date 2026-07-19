# EnvCoordinator 사용 설명서

> **대상 독자**: 시설을 운영하거나 시스템을 통합하는 사용자.
> **범위**: env_coordinator Function 의 설정, 액추에이터 등록, Facility 연동,
> 안전 운영, 로그 정책, 트러블슈팅.
> **버전**: 패치 P0–P3, dispatch_adapters, facility_integration 4c, safe_default, RotatingFileHandler 반영.

---

## 목차

1. [개요](#1-개요)
2. [전제 조건](#2-전제-조건)
3. [Custom Function 등록](#3-custom-function-등록)
4. [GeoFacility 연동](#4-geofacility-연동)
5. [액추에이터 등록과 자동 변환](#5-액추에이터-등록과-자동-변환)
6. [관수 시스템 유량 자동 산출](#6-관수-시스템-유량-자동-산출)
7. [안전 게이트와 긴급 정지](#7-안전-게이트와-긴급-정지)
8. [Method 곡선과 Growth Schedule](#8-method-곡선과-growth-schedule)
9. [그룹 액추에이터](#9-그룹-액추에이터)
10. [기상 예보 연동](#10-기상-예보-연동)
11. [운영 명령](#11-운영-명령)
12. [로그 정책](#12-로그-정책)
13. [트러블슈팅](#13-트러블슈팅)
14. [용어](#14-용어)

---

## 1. 개요

EnvCoordinator 는 시설(온실/식물공장)의 환경을 단일 Function 으로 통합 제어합니다.

```
L1 EnvTarget   → 목표값 결정 (VPD, CO₂, T, RH, Light)
L2 Situation   → 현재 상태 평가 (편차, 제한 인자, 추세)
L3 Coordinator → 액추에이터별 명령 산출 + 안전 게이트 통과
```

핵심 특징:

- **광합성 최적화** 를 1차 목표로 VPD 를 제어 (온/습도 분해).
- **장치 종류 자동 대응**: on/off 릴레이, PWM, DAC, 용량형 펌프를 어댑터가 변환.
- **시설 형상 인지**: GeoFacility 의 면적·체적·환기창 개구·관수 유량을 그대로 활용.
- **안전 우선**: 풍속/시간창/안전 게이트 통과 후에만 출력. E-stop 단일 진입점 제공.

---

## 2. 전제 조건

| 항목 | 필수/선택 | 비고 |
|------|----------|------|
| Input 장치 (T/RH 센서) | 필수 | indoor 역할 |
| Input 장치 (CO₂, 광량) | 선택 | CO₂/Light 제어 시 |
| Output 장치 (액추에이터) | 필수 | 환기창, 팬, 히터, 펌프 등 |
| GeoFacility | 권장 | 면적·체적·관수 자동 산출에 사용 |
| GPS 좌표 또는 GeoFacility 위치 | 권장 | 시간대 결정에 사용 (Growth Schedule) |
| Action: `env_actuator` | 필수 | 각 액추에이터를 Function 에 등록 |

---

## 3. Custom Function 등록

1. **Setup → Function → 추가** 에서 `env_coordinator` 를 선택합니다.
2. 옵션 그룹을 순서대로 설정합니다.

### 3.1 기본

| 옵션 | 권장값 | 설명 |
|------|--------|------|
| `update_period` | 60 s | 사이클 주기. 60–300 s 권장 |
| `sensor_max_age` | 300 s | 센서값 유효 시간 |
| `debug_logging` | OFF | ON 은 사이클별 INFO 로그 증가 |

### 3.2 VPD 제어

| 옵션 | 설명 |
|------|------|
| `sensor_vpd` | (선택) VPD 직접 측정 센서 |
| `vpd_sp_type` | `fixed` 또는 `method` |
| `target_vpd` | fixed 일 때 사용 (kPa) |
| `vpd_method_id_device_id` | method 일 때 Method ID |
| `priority_vpd` | VPD 의 충돌 시 우선도 (0–10) |
| `tolerance_vpd` | 데드밴드 (kPa) |

### 3.3 온/습 가드레일

```
guide_T_min   < 측정 T  < guide_T_max
guide_RH_min  < 측정 RH < guide_RH_max
temp_min      < 측정 T  < temp_max     (절대 한계)
humid_min     < 측정 RH < humid_max    (절대 한계)
```

- **guide**: VPD 분해 결과를 보정 범위로 사용.
- **min/max**: 위반 시 안전 우회(Override) 명령 발동.

### 3.4 CO₂ 와 광량

`co2_sp_type`(fixed/method), `target_co2`, `co2_method_id_device_id`, `light_min/max` 등.

### 3.5 광합성 최적화

`photosynth_mode_enabled = True` 로 켜면 작물별 광합성 모델(`crop_preset`)에 기반해 VPD/CO₂ 우선도를 EWA(Exponentially-Weighted Average) 로 자동 조정합니다.

---

## 4. GeoFacility 연동

### 4.1 연결

`geo_facility_id` 또는 `geo_facility_id_device_id` 에 GeoFacility UUID 를 지정합니다.

연동되면 자동으로 다음이 채워집니다.

| 필드 | 출처 |
|------|------|
| `capacity_meta.volume_m3` | 시설 3D 형상 |
| `capacity_meta.envelope_m2` | 외피 면적 |
| `capacity_meta.transmittance` | 일사 투과율 |
| `capacity_meta.vent_open_m2` | 환기창 G1 fittings 합 |
| `capacity_meta.irrigation_flow_lpm` | 모든 emitter 유량 합 (L/min) |
| `actuators_resolved[*].flow_lpm` | 액추에이터별 emitter 유량 (P3) |
| `sensors_resolved` | indoor 센서 fittings |
| `sensors_outdoor` | outdoor 센서 fittings |

### 4.2 fittings 구조

```
GeoFacility
├─ geometry_3d        (시설 외형)
├─ fittings           (모든 부속물)
│  ├─ vent_opening    → actuator_id (환기창 모터)
│  ├─ irrigation_layer→ actuator_id (밸브/펌프)
│  ├─ irrigation_pipe → layer_id
│  ├─ irrigation_device (emitter) → pipe_id, layer_id, flow_lph
│  └─ sensor          → input_uuid, sensor_role (indoor/outdoor)
├─ weather_bindings   (예보 Input 매핑)
└─ groups             (액추에이터 그룹 정의)
```

### 4.3 시간대

장치 위치(GPS) 또는 GeoFacility 좌표에서 시간대를 1회 결정해 캐시합니다.
좌표가 없으면 Growth Schedule 의 날짜 진행이 부정확할 수 있습니다.

---

## 5. 액추에이터 등록과 자동 변환

### 5.1 Action 추가

**해당 Function → Add Action → `env_actuator`** 로 액추에이터를 등록합니다.

| Action 옵션 | 설명 |
|-------------|------|
| Output | 제어 대상 Output (릴레이, PWM, 펌프 등) |
| `kind` | `vent`, `fan`, `heater`, `pump`, `valve`, `humidifier`, `dehumidifier`, `light`, `co2`, `shade`, `thermal_curtain`, `fogger` 등 |
| `priority` | 충돌 시 우선도 |
| `safe_default_pct` | 안전 게이트 발동/긴급 정지 시 이동 위치 (0–100). 0 이면 OFF |
| `slot_key` | GeoFacility 슬롯과 매핑할 키 (선택) |
| `end_behavior` | Function 비활성화 시 동작 (`off`, `hold`, `safe_default`) |

### 5.2 디바이스 타입별 자동 변환

EnvCoordinator 는 Output 의 출력 타입을 자동 감지해 0–100 % 명령을 장치 형식으로 변환합니다.

| Output 타입 | 어댑터 | 변환 방식 |
|-------------|--------|----------|
| `on_off` 릴레이 | `TimeProportionalAdapter` | `on_sec = cycle_sec × pct/100`, `pct < 5%` 면 OFF |
| `pwm` | `PwmAdapter` | duty=pct (0–100 %) |
| `value` (DAC, 스텝모터) | `ValueAdapter` | 0–100 % 직접 전달 |
| `vol` (용량형 펌프) | `VolumetricAdapter` | `vol_ml = flow_lpm × on_sec / 60 × 1000` |
| `actuator_paired` | `PairedAdapter` | 정/역 페어 모듈 내부 변환 |

> **중요**: 별도 설정 없이 Output 모듈 메타데이터(`OUTPUT_INFORMATION.output_types`) 만으로 결정됩니다.
> 어댑터 맵은 `_reload_profiles()` 시점에 빌드되어 `_adapter_by_id` 에 캐시됩니다.

### 5.3 변환 예시

| 명령 (%) | on/off 릴레이 (cycle 60s) | PWM | 용량형 펌프 (1.5 L/min) |
|---------:|---------------------------|-----|------------------------|
| 0 | OFF | duty 0 | OFF |
| 30 | ON 18 s | duty 30 | 750 ml/cycle |
| 100 | ON 60 s (상시) | duty 100 | 2 500 ml/cycle |

---

## 6. 관수 시스템 유량 자동 산출

GeoFacility 의 `irrigation_layer` fitting 마다 다음이 자동 집계됩니다.

```
irrigation_layer (actuator_id = 펌프/밸브 Output)
   └─ irrigation_pipe (layer_id)
       └─ irrigation_device (layer_id, flow_lph)   ← emitter
```

- 레이어별 emitter 유량 합 → `actuators_resolved[aid].flow_lpm` 로 저장.
- `_profile_loader_mixin` 이 `act_capacity_meta['irrigation_flow_lpm']` 로 주입.
- `VolumetricAdapter`, fogger 효과 모델이 이 값을 그대로 사용.

설정이 없는 경우 fallback 우선순위:

1. 액추에이터별 `flow_lpm`
2. 시설 전체 `irrigation_summary.totals.flow_lpm`
3. 기본값 1.0 L/min

---

## 7. 안전 게이트와 긴급 정지

### 7.1 사전 게이트 (PreGate)

| 항목 | 임계값 | 동작 |
|------|--------|------|
| 풍속 | `gate_wind_threshold` (기본 12 m/s) | 환기창 강제 닫힘 |
| 강우 | 0.5 mm/h | 환기 제한 |
| 극서/극한 | 45 ℃ / -5 ℃ | 적절한 보정 명령 발동 |
| 시간창 | `time_start`/`time_end` | 외부 보정 게이트 |

### 7.2 사후 게이트 (PostGate)

명령을 슬루율, 데드밴드, 안전 범위로 제한합니다.

### 7.3 safe_default

각 액추에이터의 `safe_default_pct` 값으로 다음 상황에서 자동 이동합니다.

- 안전 게이트가 `forced_commands` 를 발동할 때 (보온커튼 파킹 위치 등)
- `cmd_emergency_stop` 호출 시
- `force_safe_state()` 외부 트리거 호출 시
- `end_behavior = safe_default` 인 Function 비활성화 시

`safe_default_pct = 0` 이면 OFF 와 동일.

### 7.4 긴급 정지 호출

| 방법 | 설명 |
|------|------|
| Function Command → `emergency_stop` | UI 버튼 |
| Conditional / Trigger → `force_safe_state` | 외부 자동화에서 즉시 진입 |
| RPC `output_off` | 우회 경로 (개별 Output 만 정지) |

긴급 정지 후 60 초 동안 다음 사이클이 지연됩니다.

---

## 8. Method 곡선과 Growth Schedule

### 8.1 Method

VPD/CO₂/광주기 목표를 시간 기반 곡선으로 정의합니다.

- **Daily**: 시간(HH:MM)별 setpoint
- **Duration**: 시작 후 경과 시간(h)별
- **Daily Bezier**: 부드러운 일주 곡선
- **Repeating**: 반복 패턴

### 8.2 Growth Schedule

`schedule_start_time` 을 시점으로 `schedule_week_offset` 주차를 더해 Method 의 단계 곡선을 자동 선택합니다.

> 24 시간 이상 정전/재부팅이 감지되면 워치독이 경고를 띄웁니다.
> 실 생장 시계와 어긋난 경우 `schedule_week_offset` 으로 수동 보정하세요.

---

## 9. 그룹 액추에이터

GeoFacility 의 `groups` 필드에 정의합니다 (Facility 편집 UI 또는 API).

```json
{
  "vent_array_1": {
    "mode": "multi_stage",
    "leader": "OUTPUT_UUID_A",
    "members": ["OUTPUT_UUID_B", "OUTPUT_UUID_C"],
    "threshold_pct": 50
  }
}
```

| `mode` | 동작 |
|--------|------|
| `multi_stage` | 리더 명령이 임계를 넘으면 멤버 순차 개방 |
| `stacked` | 균등 분배 |
| `windward_diff` | 풍향 기반 차등 개방 |

> 그룹 정의가 비어 있으면 액추에이터들은 각자 독립 제어됩니다.

---

## 10. 기상 예보 연동

GeoFacility 의 `weather_bindings` 에 예보 Input 을 매핑합니다.

```json
[
  {
    "measurement_type": "temperature_forecast",
    "input_uuid": "INPUT_UUID",
    "measurement_id": "MEAS_ID",
    "max_age_sec": 3600
  }
]
```

- `max_age_sec` 가 있으면 해당 소스 전용 유효 수명을 사용합니다 (P2-1).
- 없으면 Function 의 `sensor_max_age` 적용.
- `forecast_feedforward_enabled = True` 일 때 lookahead 시간(`forecast_lookahead_h`) 범위에서 사전 보정 명령에 반영됩니다.

---

## 11. 운영 명령

Function Command 또는 RPC 로 호출:

| 명령 | 설명 |
|------|------|
| `reload` | Action 변경 후 어댑터/프로필 재로드 |
| `run_now` | 다음 사이클을 즉시 실행 |
| `emergency_stop` | 모든 액추에이터를 `safe_default`/OFF 로 이동 + 60 초 지연 |
| `force_safe_state` | 외부 자동화용 E-stop (반환값 없음) |

---

## 12. 로그 정책

### 12.1 기본값

- 일반 모드: **INFO** 이상만 파일 기록.
- 디버그 모드(`daemon_debug_mode = True`): DEBUG 까지 기록.
- 파일 핸들러: `RotatingFileHandler` 50 MB × 5 파일 = 최대 250 MB.

### 12.2 절약 포인트

- InfluxDB `write_success` 콜백은 무음 처리(과거 하루 15 GB 폭증 원인).
- `write_fail` 은 WARNING, 재시도 실패는 ERROR.
- EnvCoordinator authority/feedforward 메시지는 상태 변경 시점에만 INFO,
  사이클별 상세는 `debug_logging = True` 일 때만 DEBUG.

### 12.3 권장

- 평시 운영: `debug_logging = False`, daemon DEBUG OFF.
- 문제 조사 시: 짧게 ON → 분석 후 OFF.

---

## 13. 트러블슈팅

| 증상 | 점검 항목 |
|------|----------|
| 액추에이터가 작동하지 않음 | Action 등록 여부, Output 활성화, 어댑터 맵(`_adapter_by_id`) 빌드 로그 |
| on/off 릴레이가 너무 짧게 켜짐 | 명령값 < 5 % 일 가능성. `priority`/`tolerance` 조정 |
| 펌프가 항상 1.0 L/min 으로 계산됨 | GeoFacility 의 irrigation_device fittings 의 `flow_lph` 가 0 인지, `irrigation_layer.actuator_id` 가 펌프 Output 과 일치하는지 확인 |
| 환기창이 풍속에서 닫히지 않음 | `gate_wind_threshold` 와 풍속 센서(`sensor_wind`) 매핑 확인 |
| 워치독 24 시간 경고 | `schedule_week_offset` 으로 생장 주차 수동 보정 |
| 로그가 빠르게 증가 | `debug_logging`, `daemon_debug_mode` 가 OFF 인지, RotatingFileHandler 가 활성인지 확인 |
| Growth Schedule 날짜가 어긋남 | 장치 GPS 또는 GeoFacility 좌표 설정 여부(시간대 결정) |
| E-stop 후에도 액추에이터가 움직이지 않음 | 의도된 60 초 지연. `timer_loop` 만료까지 대기 |
| facility 변경이 반영되지 않음 | `reload` 명령 호출 또는 Function 비활성화 → 활성화 |

---

## 14. 용어

| 용어 | 정의 |
|------|------|
| VPD | Vapor Pressure Deficit. 포화 수증기압과 실제 수증기압의 차 (kPa) |
| L1 / L2 / L3 | EnvCoordinator 의 목표 / 상황 / 명령 산출 계층 |
| Dispatch Adapter | 0–100 % 명령을 디바이스 타입별 호출 형태로 변환하는 컴포넌트 |
| capacity_meta | 시설 형상·용량 정보 묶음 (체적, 환기 개구, 유량 등) |
| safe_default | 안전 상황으로 자동 이동할 액추에이터 위치 (0–100 %) |
| Forced Command | 안전 게이트가 강제로 발동시키는 명령 |
| Method | 시간 기반 setpoint 곡선 |
| Growth Schedule | 파종일 기준 주차별 단계 곡선 |
| Pre/Post Gate | 명령 산출 전/후 안전 검증 단계 |

---

## 부록 A — 변경 이력 (패치 요약)

| 패치 | 내용 |
|------|------|
| P0 | on/off 릴레이 시간 비례 변환, 센서 fallback |
| Stage 0–1 | `dispatch_adapters.py` 5 어댑터 도입, 자동 매핑 |
| Stage 2 | GeoFacility `groups` 컬럼, irrigation_flow_lpm 캐시 |
| Stage 3 | Fogger 물리 모델(증발잠열 기반) |
| P2-1 | weather_bindings 항목별 `max_age_sec` |
| P2-3 | `safe_default_pct`, `force_safe_state()` 외부 진입점 |
| P3 | 액추에이터별 `flow_lpm` (emitter 합산) |
| 로그 | RotatingFileHandler 250 MB, write_success 무음, authority 버그(`not {}`) 수정 |
