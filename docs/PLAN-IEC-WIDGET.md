# PLAN — AoT_facility 위젯 진화: Integrated Environment Control (IEC)

대상: **기존 `aot/widgets/AoT_facility.py` 를 그대로 확장** (신규 위젯 추가하지 않음)
작성일: 2026-05-21
선행 자산:
- 위젯 정의 / HEAD / BODY: [aot/widgets/AoT_facility.py](aot/widgets/AoT_facility.py)
- JS 컨트롤러: [aot-facility-widget.js](aot/aot_flask/static/js/widget/AoT_facility/aot-facility-widget.js)
- 3D 빌더: [aot-facility-3d.js](aot/aot_flask/static/js/widget/AoT_facility/aot-facility-3d.js)
- 런타임 API: [routes_geo.py:1257 `api_facility_runtime`](aot/aot_flask/routes_geo.py:1257)
- 적용 API: [routes_geo.py:1501 `api_facility_apply`](aot/aot_flask/routes_geo.py:1501)

> 결정: 새 위젯(`AoT_iec`)을 만들지 않고 **AoT_facility 안에서 섹션을 늘리고 모드를 추가**한다.
> 사용자는 위젯 옵션 `display_mode` 로 `viewer`(현재 동작) / `control`(IEC 모드)을 선택한다.
> `viewer` 가 기본이라 기존 대시보드는 무영향.

---

## 1. 변경 후 위젯 구조

```
§  Top: facility 선택 dropdown + 마지막 sync ts        (기존 유지)
§ 0. Status Strip  ── 신규: 배지 + 활성 액추에이터 카운트 (control 모드에서만)
§ A. 3D Preview    ── 확장: 센서/액추에이터 핫스팟 클릭
§ B. Environment   ── 확장: setpoint 대비 편차 색상
§ C. Setpoints     ── 신규 (control 모드)
§ D. Actuator Grid ── 신규 (control 모드)  + ALL STOP / Restore AUTO
§ E. AI Advice     ── 기존 § C 가 § E 로 이동, 토글 가능
```

`display_mode = viewer` 일 때는 §0/§C/§D 가 렌더되지 않아 현재 모습 그대로다.

---

## 2. 코드 변경 위치 (파일·라인 단위)

### 2.1 `aot/widgets/AoT_facility.py`
- `widget_variables()` (현 [40–79](aot/widgets/AoT_facility.py:40)) 확장
  - 옵션 키 추가 읽기: `display_mode`, `show_setpoints`, `show_controls`, `show_status`.
  - 반환 dict에 `setpoints` (신규 모델에서 조회), `permissions`(`can_control` bool) 추가.
- `WIDGET_HEAD_HTML` ([86–155](aot/widgets/AoT_facility.py:86))
  - 신규 JS 4개 script 태그 추가:
    `aot-facility-status.js`, `aot-facility-setpoints.js`, `aot-facility-control-grid.js`, `aot-facility-hotspot.js`.
  - CSS 블록에 `.iec-*` 클래스 추가 (배지, 슬라이더 행, 강조 outline).
- `WIDGET_BODY_HTML` ([157–245](aot/widgets/AoT_facility.py:157))
  - 기존 `§ A / § B / § C(AI advice)` 사이에 조건부 블록 삽입:
    - `{% if widget_variables.show_status %} § 0 … {% endif %}`
    - `{% if widget_variables.show_setpoints %} § C(setpoints) … {% endif %}`
    - `{% if widget_variables.show_controls %} § D(actuators) … {% endif %}`
  - 기존 AI advice 섹션 라벨을 `§ C` → `§ E` 로 변경.
  - `vars` JSON 에 `displayMode`, `setpoints`, `canControl` 추가.
- `custom_options` ([267–294](aot/widgets/AoT_facility.py:267))
  - 추가 옵션:
    ```
    display_mode: select [viewer|control]  default=viewer
    show_status:     bool  default=true   (control 모드에서만 노출)
    show_setpoints:  bool  default=true
    show_controls:   bool  default=true
    estop_enabled:   bool  default=false  (위험 동작이므로 명시적 활성화)
    ```

### 2.2 `aot/aot_flask/static/js/widget/AoT_facility/aot-facility-widget.js`
- `init()` 에서 `vars.displayMode === 'control'` 이면 신규 모듈 부팅:
  - `AoTFacilityStatus.start(widgetId)` — 5초 폴링.
  - `AoTFacilitySetpoints.bind(widgetId, vars.setpoints)`.
  - `AoTFacilityControlGrid.bind(widgetId, vars.facility)`.
  - `AoTFacilityHotspot.attach(STATE[widgetId].threeCtx, vars.facility)`.
- 기존 `_refreshRuntime` ([85–107](aot/aot_flask/static/js/widget/AoT_facility/aot-facility-widget.js:85))
  성공 후 control 모드면 §D 행 값(슬라이더 percent, 토글) 갱신 호출 추가.
- 기존 AI advice mock 카드(현 [181–200](aot/aot_flask/static/js/widget/AoT_facility/aot-facility-widget.js:181))는 그대로.

### 2.3 신규 JS 파일 (같은 디렉터리)
```
aot/aot_flask/static/js/widget/AoT_facility/
  aot-facility-status.js         # § 0 — status 폴링 + 배지 렌더
  aot-facility-setpoints.js      # § C — 폼 검증/저장
  aot-facility-control-grid.js   # § D — 슬라이더/토글/EStop
  aot-facility-hotspot.js        # § A — Raycaster, 센서·액추에이터 마커
```
각 파일은 IIFE 로 `window.AoTFacilityStatus` 등 단일 네임스페이스만 노출.

### 2.4 `aot/aot_flask/routes_geo.py` — API 추가
기존 `/api/aot/facility/<uuid>/runtime` 와 `/api/geo/facility/<uuid>/apply` 는 변경 없이
**같은 blueprint** 에 4개 엔드포인트 추가 (네이밍은 facility 계열 유지):

```
GET  /api/aot/facility/<uuid>/status      # 배지용 경량 상태
GET  /api/aot/facility/<uuid>/setpoints   # 현재 설정값
POST /api/aot/facility/<uuid>/setpoints   # 저장
POST /api/aot/facility/<uuid>/control     # 단일 액추에이터 직접 제어
POST /api/aot/facility/<uuid>/estop       # 비상 정지
```

`/control` 과 `/estop` 은 내부적으로 `api_facility_apply` 가 사용하는 명령 적용 helper
([facility_integration.py](aot/aot_flask/geo/facility_integration.py))를 재사용하고,
`aot.audit_log` 에 `action_type` 을 다음으로 기록:
- `facility_control` (수동 단일 제어)
- `facility_setpoint` (설정값 변경)
- `facility_estop` (비상 정지, severity=critical)

### 2.5 데이터 모델
신규 테이블 1개 추가 + Alembic 마이그레이션 1건:

```python
# aot/databases/models.py
class GeoFacilitySetpoint(CRUDMixin, db.Model):
    __tablename__   = 'geo_facility_setpoint'
    id              = db.Column(db.Integer, primary_key=True)
    facility_uuid   = db.Column(db.String(36), unique=True, index=True, nullable=False)
    target_temp_c   = db.Column(db.Float)
    temp_band_c     = db.Column(db.Float, default=1.0)
    target_rh_pct   = db.Column(db.Float)
    co2_cap_ppm     = db.Column(db.Float)
    source          = db.Column(db.String(16), default='manual')   # manual|ai|auto
    operator        = db.Column(db.String(64))
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow,
                                onupdate=datetime.utcnow)
```

facility 당 1 row (upsert). 기존 GeoFacility 테이블은 변경하지 않는다.

### 2.6 권한
- 새 권한 `permission_facility_control` 을 `aot/databases/models.py` Role 매핑에 추가.
- 미보유 시 `widget_variables.permissions.can_control = False` → 템플릿이 §C/§D 를 read-only 로 렌더.
- 서버 측 `/control`, `/setpoints` POST, `/estop` 은 `@require_permission(...)` 데코레이터로 보호.

---

## 3. 섹션별 동작 정의

### 3.1 § 0 Status Strip
- 5초 폴링 `GET /status`. 응답:
  `{level: emergency|warn|active|idle, reasons: [...], active_count, total_count, ts}`
- 산정 규칙(서버):
  ```
  emergency  센서 valid 비율 < 50%
             또는 응답 timeout 액추에이터 ≥ 2
             또는 |indoor_temp - target| > 2·band 가 10분 지속
  warn       센서 1개 stale
             또는 |indoor_temp - target| > band
             또는 co2 > co2_cap
  active     최근 60s 내 명령(manual/ai/auto) 존재
  idle       그 외
  ```
- 클릭 시 `reasons` 드롭다운으로 펼침.

### 3.2 § A 3D 핫스팟 — `aot-facility-hotspot.js`
- `AoTFacility3D.buildScene` 가 만든 `ctx.scene` 에 마커 추가:
  - 센서: `THREE.Mesh(SphereGeometry(0.15), MeshBasicMaterial({color: …}))`
    색상 = `valid` 초록 / `stale` 노랑 / `degraded` 빨강.
    위치 산정 규칙:
    - `indoor_temp` → 각 bay 중앙, eave×0.6 높이
    - `indoor_humidity` → bay 중앙, 바닥+0.5m
    - `indoor_co2` → bay 중앙, 천장-0.5m
    - `outdoor_*` → 시설 외부 측면 +2m
  - 액추에이터: `kind` 별 고정 위치 + percent 애니메이션.
    - `side_window` 측면, 0–100% → 0–60° 개방 회전
    - `roof_vent` 용마루, 개폐각 표현
    - `thermal_curtain` / `shade_curtain` eave 라인, 전개율 = percent
    - `fan_*` 회전 (rpm 표시)
- 좌클릭 = `THREE.Raycaster` hit-test → 대상 행에 `.iec-focus` 클래스 부여 (§B/§D).

### 3.3 § B Environment (확장)
- 기존 6셀 유지. 셀에 setpoint 대비 편차 색상 추가:
  - `|val - target| ≤ band` 정상(흰색)
  - `≤ 2·band` 주의(노랑)
  - 그 외 경고(빨강)
- 셀 우상단에 setpoint 작은 텍스트 (`목표 22.0°C`).

### 3.4 § C Setpoints
- 입력 4개: `target_temp_c`, `temp_band_c`, `target_rh_pct`, `co2_cap_ppm`.
- 클라 검증 범위: 온도 5–45°C, band 0.2–5°C, RH 20–95%, CO2 300–2000 ppm.
- 변경 시 [Save] 활성화, 미저장 상태면 옅은 노란 배경.
- 저장: `POST /setpoints` → 성공 시 §B 색상 즉시 재계산.

### 3.5 § D Actuator Control Grid
- 행 = `runtime.actuator_states` 의 한 슬롯.
- 컬럼: `name | 슬라이더(또는 토글) | 현재값 | 마지막 src | 액션버튼`.
  - PWM/모터류는 슬라이더 (0–100%), debounce 500ms → `POST /control { action:'set', percent }`.
  - relay 류는 ON/OFF 토글 → `POST /control { action:'on'|'off' }`.
- `src` 컬럼: `MANUAL` / `AI` / `AUTO` / `EXT` — `audit_log` 의 최근 entry 기반.
- **안전 가드**(클라이언트 + 서버 이중):
  - `roof_vent` 100% + `thermal_curtain` 100% 동시 → 확인 모달.
  - 외기 온도 < 0°C 에서 `side_window` > 50% → 경고 모달.
  - 서버는 `facility_integration.validate_command()` 헬퍼에서 동일 룰 적용.
- **EStop / Restore AUTO** (`estop_enabled=True` 일 때만 노출):
  - `[ALL STOP]` → 영향 받는 액추에이터 목록 모달 → "STOP" 타이핑 후 확정 → `POST /estop`.
  - 서버는 preset 별 safe-state 매핑으로 일괄 명령 (greenhouse 기본:
    heater off / vent close / curtain open / fan off).
  - `[Restore AUTO]` → manual override 플래그 해제, method/PID 가 다시 제어권 가짐.

### 3.6 § E AI Advice (현 § C → § E 로 이동)
- 기존 mock 카드 유지.
- 차이: 현재 화면이 control 모드이고 `permissions.can_control=true` 이면
  카드의 `[승인하고 적용]` 버튼이 §D 의 src 컬럼을 잠시 `AI` 로 마킹.

---

## 4. 옵션 매트릭스 (`custom_options`)

| 옵션 | 기본 | viewer 모드 동작 | control 모드 동작 |
|---|---|---|---|
| `display_mode` | `viewer` | 기존 그대로 | §0/§C/§D 활성 |
| `period` | 60 | runtime 폴링 주기 | 동일 |
| `facility_uuid` | "" | 동일 | 동일 |
| `show_ai_advice` | true | §E 노출 | §E 노출 |
| `show_status` | true | (무시) | §0 노출 |
| `show_setpoints` | true | (무시) | §C 노출 |
| `show_controls` | true | (무시) | §D 노출 |
| `estop_enabled` | false | (무시) | §D 에 EStop 버튼 노출 |

---

## 5. 마이그레이션 안전성

- 기존 대시보드: `display_mode` 가 없으므로 옵션 미설정 → 기본 `viewer` → **무영향**.
- DB: 신규 테이블만 추가, 기존 컬럼 변경 없음 → 롤백 시 drop 한 번으로 회수.
- 신규 API: 새 URL 만 추가, 기존 endpoint 변경 없음.
- 신규 JS: 동일 디렉터리, 기존 `aot-facility-widget.js` 는 dispatcher 역할만 추가.
- 권한: `permission_facility_control` 부여 전까지 read-only 라 운영 사고 차단.

---

## 6. 마일스톤

| 단계 | 산출물 | 예상 | 검증 |
|---|---|---|---|
| M1 | `display_mode` 옵션 + 템플릿 조건 블록 + 빈 §0/§C/§D 자리만 렌더 | 0.5d | 옵션 토글 시 자리 확보 |
| M2 | `GeoFacilitySetpoint` 모델 + Alembic + `/setpoints` GET·POST + §C UI | 0.5d | 값 영속화 |
| M3 | `/status` + `aot-facility-status.js` + §0 배지 | 0.5d | 4단계 분기 수동 시나리오 |
| M4 | `/control` + `aot-facility-control-grid.js` + §D + 서버측 가드 | 1.5d | 슬라이더 → output 변화, 가드 모달 |
| M5 | `aot-facility-hotspot.js` + 센서/액추에이터 마커 + Raycaster 클릭 | 1d | 마커 클릭 → §B/§D 강조 |
| M6 | `/estop` + safe-state 매핑(`facility_presets/*.yaml`) + EStop 모달 | 0.5d | 두 번 호출 멱등 |
| M7 | 권한 데코레이터 + read-only 렌더 + 단위/통합 테스트 | 0.5d | 권한 매트릭스 통과 |

총 약 5 영업일.

---

## 7. 테스트

### 7.1 단위 (`tests/widgets/facility/`)
- `test_facility_status_levels.py` — 산정 규칙 4분기.
- `test_facility_control_guards.py` — 외기<0°C 측창>50% 차단, 권한 거부.
- `test_facility_setpoints_validation.py` — 범위/upsert.
- `test_facility_estop_safe_state.py` — preset별 safe-state.

### 7.2 통합 (Flask test client)
- 권한 매트릭스 (3 역할 × 5 엔드포인트).
- `audit_log` 기록 검증 (`facility_control`, `facility_setpoint`, `facility_estop`).
- EStop 멱등성, Restore AUTO 후 method/PID 제어권 복귀.

### 7.3 수동 UI
- viewer 모드: 기존 대시보드 회귀 0건.
- control 모드: 슬라이더 debounce 1회 호출, 핫스팟 클릭 동기화, 모바일 ≤768px 스택.

---

## 8. 사전 결정 필요

1. **`permission_facility_control`** 권한 신설 vs 기존 admin 권한 재사용. 권고: 신설.
2. **preset 별 safe-state 정의** 위치 — `aot/aot_flask/geo/facility_presets/*.yaml` 에
   `safe_state:` 섹션 추가 (greenhouse / nursery / livestock 3종 우선).
3. **PWM/Relay 슬롯 매핑** — facility.actuators 의 `kind` 만으로는 PWM 여부 판단 불가.
   `Output.output_type` 조인으로 결정 (M4 진입 시 helper 추가).
4. **audit_log 컬럼** — 기존 스키마에 `severity` 가 있는지 확인 후 `facility_estop` 에 사용.
   없으면 마이그레이션 함께 추가.

---

## 9. 비대상 (MVP 제외)

- 시계열 트렌드 차트 (기존 graph 위젯 사용).
- 알람 룰 편집기 (별도 alert 페이지 영역).
- 다중 시설 동시 운용 — MVP 는 단일 facility 선택만.
- AI 모델 재훈련/스케줄러 트리거.
- 모바일 푸시 알림.
