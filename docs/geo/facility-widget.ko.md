# AoT_facility 위젯

`AoT_facility` 위젯은 대시보드에 시설(건물)의 3D 뷰, 실시간 환경 값, 그리고 통합환경제어(IEC) 함수가 연결돼 있으면 목표값 편집과 액추에이터 제어까지 함께 보여줍니다.

---

## 위젯 추가

1. 대시보드에서 **Add Widget → AoT Facility** 선택
2. 설정에서 **IEC Function** 을 선택합니다 — 시설 자체가 아니라 `env_coordinator` 함수를 고릅니다. 시설은 그 함수의 설정에서 자동으로 찾아집니다.
3. **IEC Function** 을 비워 두면 활성화된 첫 `env_coordinator` 함수를 자동으로 고릅니다. 그런 함수가 하나도 없으면 가장 최근에 수정된 시설로 대체됩니다(이 경우 보기 전용 — 연결된 함수가 없으면 상태 스트립·목표값·제어가 모두 나오지 않습니다).
4. **Save** 클릭

---

## 화면 구성

### 0. 상태 스트립

**Show Status Strip** 이 켜져 있을 때 표시됩니다. `/api/aot/facility/<uuid>/status` 를 5초마다 조회하는 배지입니다.

| 단계 | 의미 |
|------|------|
| `IDLE` | 연결된 IEC 함수가 없거나, 보고할 내용이 없음 |
| `ACTIVE` | 연결된 함수가 최근 제어 사이클을 실행함 |
| `WARN` | 연결된 함수가 비활성 상태이거나, 최근 사이클 보고가 없음(정체) |
| `EMERGENCY` | 센서 상태 저하 — 시설 센서의 절반 미만만 정상 응답 |

배지 옆에는 그 단계의 근거와, 활성/전체 액추에이터 수가 함께 표시된 타임스탬프가 나옵니다.

### A. 3D 뷰

Three.js로 렌더링된 시설 건물 모델입니다. `/geo/facility` 에서 설정한 외피 파라미터(베이 치수, 피복 자재 등)로 자동 생성됩니다.

- **마우스 오른쪽 버튼 드래그**: 회전
- **마우스 왼쪽 버튼 드래그**: 이동
- **스크롤**: 줌
- **Preset 배지**: 시설의 구조 프리셋
- **"connected × N" 배지**: 여러 동이 연결된(연동) 구조일 때 표시
- **"double layer" 배지**: 외피가 2중 피복일 때 표시

### B. 환경

실시간 값이 표시되는 7개 셀입니다. 제어 모드이고 목표값 편집이 켜져 있으며 제어 권한(`edit_settings`)이 있으면, 앞의 4개는 클릭해 목표값 편집창을 열 수 있습니다.

| 셀 | 목표값 설정 가능? |
|----|----|
| VPD | 가능 |
| 실내 온도 | 가능 |
| 실내 습도 | 가능 |
| CO₂ | 가능 |
| 실외 온도 | 불가 — 기상 데이터 또는 외부 센서 |
| 풍속 | 불가 — 기상 데이터 또는 풍속 센서 |
| 일사량 | 불가 — 기상 데이터 또는 일사 센서 |

값이 없으면 `—` 로 표시됩니다. 편집 가능한 셀은 현재 목표값도 함께 보여주는데, 이는 수동 오버라이드가 있으면 그 값, 없으면 연결된 [프로그램](programs.md) 단계가 말하는 값 — 즉 실제로 제어가 따르는 값(effective target) 그대로입니다. 따로 저장된, 제어와 몰래 어긋날 수 있는 숫자가 아닙니다.

### D. 액추에이터 제어

**Show Actuator Grid** 가 켜져 있을 때 표시됩니다. 시설에 연결된 액추에이터의 슬라이더·토글 그리드로, **읽기 전용 표시가 아니라 실제로 작동하는 제어면**입니다. **Show Emergency Stop** 을 켜면 여기에 "ALL STOP" 버튼이 나타납니다.

### E. AI 조언

!!! warning "실험적 기능 — 운영 환경에서는 꺼 둘 것"
    이 패널은 현재 **하드코딩된 텍스트의 가짜(mock) 데모 카드**를 보여줄 뿐, 실제 조언이 아닙니다. 하지만 **Approve** 버튼은 `/api/geo/facility/<uuid>/apply` 를 통해 실제 액추에이터 명령을 내보냅니다. 실제 조언 백엔드가 연결되기 전까지는 **Show AI Advice** 를 켜지 마세요.

---

## 위젯 설정 옵션

### General

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| Period (seconds) | 실시간 데이터 갱신 주기. `0`이면 자동 갱신을 끕니다. | 60 |
| IEC Function | 연결할 `env_coordinator` 함수. 시설은 여기서 자동으로 따라옵니다. | (자동 선택) |
| Show AI Advice (§ E) — EXPERIMENTAL | 위 경고 참조 — 운영 환경에서는 켜지 마세요. | Off |

### Integrated Environment Control (IEC)

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| Show Status Strip (§ 0) | 긴급/경고/작동중/대기 배지. 제어 모드에서만. | On |
| Show Setpoints (§ B/C) | 클릭해 여는 온도/습도/CO₂/VPD 목표값 편집. 제어 모드에서만. | On |
| Show Actuator Grid (§ D) | 액추에이터 슬라이더·토글. 제어 모드에서만. | On |
| Show Emergency Stop | 액추에이터 그리드의 "ALL STOP" 버튼. | Off |

### 3D Rendering

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| Render Mode | `Default`(반투명 외피) · `Solid`(불투명, 오버드로우 감소) · `Wireframe`(윤곽선만) · `Performance`(모바일용 단순 셰이딩+저해상도) 중 선택. | Default |

### Sensor Labels

3D 화면의 각 센서 옆에 실시간 측정값을 표시하는 라벨입니다.

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| Show Sensor Labels | | On |
| Max Channels Shown | 라벨 하나에 보여줄 값 개수(1~5). 초과분은 "+"로 접힘. | 1 |
| Decimals | 라벨 값의 소수점 자리수(0~3). | 1 |
| Label Size (em) | 글자 크기(0.5~2.0). | 0.85 |
| Label Background | CSS 색상. | `rgba(15,23,42,0.78)` |
| Label Text Color | CSS 색상. | `#f8fafc` |
| Vertical Offset (m) | 센서 위 라벨이 붙는 높이(0.0~2.0). | 0.25 |
| Label Opacity | 0.0~1.0. | 0.7 |
| Enable Sensor Popup | 라벨을 클릭하면 최근 24시간 그래프 팝업이 열립니다. | On |

---

## 데이터 갱신

위젯은 설정된 **Period** 마다 `/api/geo/facility/<uuid>/integration` 를 호출해 환경 데이터를 갱신하고, 상태 스트립이 켜져 있으면 **Period 와 무관하게** `/api/aot/facility/<uuid>/status` 를 5초마다 호출합니다.

- 센서 바인딩이 없는 시설은 `—` 만 표시됩니다.
- 외부 기상 데이터(Open-Meteo)는 시설 위치의 GPS 좌표를 기반으로 자동으로 가져옵니다.

---

## 시설이 없을 때

- **IEC Function은 골랐지만 그 함수에 시설이 설정돼 있지 않거나, 시설이 아예 등록돼 있지 않은 경우**: "No facility selected. Register one at `/geo/facility`."
- **시스템 전체에 등록된 시설이 하나도 없는 경우**: "No facilities registered."

시설 등록 방법:

1. `/geo/design` → Facility 모드 → 건물 폴리곤 그리기 및 저장
2. `/geo/facility` → 해당 시설 선택 → 외피 설정 → Save

---

## 관련 페이지

- [시설 관리](facility.md) — 3D 모델 설정, 센서 바인딩
- [관리 프로그램](programs.md) — effective target이 따르는 단계별 목표
- [지도 위젯](map-widget.md) — 지도 기반 모니터링
