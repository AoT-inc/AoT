# 측정값 안전/위험 범위 — 설계 계획서

상태: 계획 (구현 전)
작성: 2026-05-30
결정 사항: 적용 단위 = 측정 유형 기본 + 센서 채널 오버라이드 / 탭 = 기존 Tab 시스템 재사용 / 이번 단계 = 계획 문서만

---

## 1. 목표

측정값(온도, 습도, CO2 등)마다 안전/위험 구간을 사용자가 정의하고, 그 결과를 위젯과 function이
일관되게 불러와 색상 표시 또는 로직 판단에 활용할 수 있게 한다.

요구 사항 정리:

1. 하나의 페이지에서 측정값을 단독 또는 멀티 선택하여 범위를 지정.
2. input tab 기능을 적용해 여러 탭을 생성/관리.
3. 예: 온도 — 낮음 < 5 (파랑), 안전 10~25 (녹색), 높음 > 35 (빨강).
4. 안전과 낮음/높음 사이 빈 구간(5~10, 25~35)은 "중간 위험 감지" 구간으로 자동 처리,
   색상은 양쪽 기준색의 중간색을 자동 산출(사용자 오버라이드 가능).
5. 색상은 기본값 제공 + 사용자 변경 가능.
6. 위젯/function이 측정값을 불러올 때 범위 정보가 함께 제공되어 처리 가능.

---

## 2. 기존 자산 (재사용 대상)

| 자산 | 위치 | 역할 |
|------|------|------|
| `Tab` 모델 | `aot/databases/models/tab.py` | `page_type` 기반 통합 탭. 신규 `page_type='measurement_range'` 추가 |
| `routes_tab.py` | `aot/aot_flask/routes_tab.py` | 탭 생성/이름변경/복제/삭제 CRUD (whitelist만 확장) |
| `aot-tabs.js` | `aot/aot_flask/static/js/components/aot-tabs.js` | 탭 UI(드래그/스크롤/sticky) |
| `aot-color-picker.js` | `aot/aot_flask/static/js/components/aot-color-picker.js` | 색상 선택 웹 컴포넌트. 프리셋이 이미 안전→위험 톤 |
| `Measurement` / `Unit` | `aot/databases/models/measurement.py` | 측정 유형/단위 마스터 (유형 단위 적용에 사용) |
| `DeviceMeasurements` | `aot/databases/models/measurement.py` | 센서별 채널 측정 바인딩 (채널 오버라이드 대상) |
| `/last/<...>` | `aot/aot_flask/routes_general.py:423` | 위젯의 라이브 측정값 엔드포인트 (범위 메타 주입 지점) |
| `TabService` | `aot/services/tab_service.py` | 탭 비즈니스 로직 |

색상 프리셋(`aot-color-picker.js`): `#008dde`(파랑), `#DAF2E6`, `#F4D624`, `#FEA60B`, `#DF5353`(빨강) — 기본 색상 출처로 활용.

---

## 3. 데이터 모델

신규 모델 2종. 적용 단위 = "유형 기본 + 채널 오버라이드" 결정을 그대로 반영한다.

### 3.1 `MeasurementRange` (범위 프로파일 — 유형 기본 또는 채널 오버라이드)

```
__tablename__ = "measurement_range"

id            Integer PK
unique_id     String(36) unique (set_uuid)
tab_id        String(36) FK -> tab.unique_id (ondelete CASCADE)   # 어느 탭에 속하는지
name          Text                                                # 사용자 라벨 (예: "온실 온도 기준")

# 적용 대상 (scope)
scope         String(16)  default 'measurement'                   # 'measurement' | 'channel'
measurement   Text                                                # 측정 유형 키 (예: 'temperature') — 유형 기본일 때
unit          Text                                                # 표시 단위 (예: 'C')
device_measurement_id String(36) nullable                         # 채널 오버라이드일 때 DeviceMeasurements.unique_id

# 구간 임계값 (오름차순: low_max <= safe_min <= safe_max <= high_min)
low_max       Float    # 이 값 미만 = 낮음          (예: 5)
safe_min      Float    # 안전 구간 시작            (예: 10)
safe_max      Float    # 안전 구간 끝              (예: 25)
high_min      Float    # 이 값 초과 = 높음          (예: 35)

# 기본 색상 (3종 — 낮음/안전/높음)
color_low     String(9) default '#008dde'
color_safe    String(9) default '#2ecc71'
color_high    String(9) default '#DF5353'

# 중간 구간 색상 오버라이드 (NULL이면 양쪽 중간색 자동 산출)
color_warn_low  String(9) nullable   # low_max ~ safe_min 구간
color_warn_high String(9) nullable   # safe_max ~ high_min 구간

is_enabled    Boolean default True
position      Integer default 0       # 탭 내 정렬
created_at / updated_at DateTime
```

설계 노트:
- `scope='measurement'` 행은 해당 측정 유형의 **기본 기준**. 동일 측정 유형은 탭 내 1개를 권장(유니크 제약 후보: `tab_id`+`measurement`+`scope`).
- `scope='channel'` 행은 특정 `DeviceMeasurements`에만 적용되는 **오버라이드**. 조회 시 채널 오버라이드가 있으면 우선, 없으면 유형 기본으로 폴백.
- 멀티 선택 입력은 UI에서 선택된 측정 유형/채널마다 `MeasurementRange` 행을 생성(동일 임계값을 한 번에 여러 대상에 적용).

### 3.2 구간 분류 규칙 (5구간)

임계값 4개로 5개 구간이 자동 정의된다:

| 구간 | 조건 | 색상 |
|------|------|------|
| 낮음 (low) | value < low_max | color_low |
| 경계-하 (warn_low) | low_max ≤ value < safe_min | color_warn_low 또는 mix(color_low, color_safe) |
| 안전 (safe) | safe_min ≤ value ≤ safe_max | color_safe |
| 경계-상 (warn_high) | safe_max < value ≤ high_min | color_warn_high 또는 mix(color_safe, color_high) |
| 높음 (high) | value > high_min | color_high |

중간색 자동 산출 = 두 끝 색의 RGB 선형 평균(`mixHex(a, b)` 50%). 동일 로직을 Python/JS 양쪽에 구현.

---

## 4. 백엔드 (Flask)

### 4.1 모델/마이그레이션
- `aot/databases/models/measurement_range.py` 신규: `MeasurementRange` + `MeasurementRangeSchema`.
- `aot/databases/models/__init__.py`에 export 등록.
- Alembic 마이그레이션으로 `measurement_range` 테이블 생성.

### 4.2 탭 통합
- `routes_tab.py`의 `page_type` whitelist에 `'measurement_range'` 추가 (create/rename/duplicate/delete 4곳).
- `TabService.get_default_tab` 등의 기본 탭 이름 맵에 `'measurement_range': 'Range'` 추가.

### 4.3 라우트 — `routes_measurement_range.py` (신규 블루프린트)
- `GET  /measurement_range` — 페이지 렌더(탭 목록 + 현재 탭의 범위 프로파일).
- `POST /measurement_range/save` — 프로파일 생성/수정(멀티 대상 일괄 처리).
- `POST /measurement_range/delete` — 삭제(헌법 5조: 엔티티명 확인 후).
- `GET  /api/measurement_range/resolve?measurement=temperature&device_measurement_id=...`
  — 채널 오버라이드 우선 → 유형 기본 폴백으로 적용될 범위 1건 반환(위젯/function 공용).
- `app.py`에 블루프린트 등록.

### 4.4 측정값 조회에 범위 메타 주입
- 공유 헬퍼 `aot/utils/measurement_range_util.py`:
  - `resolve_range(measurement, device_measurement_id=None) -> dict | None`
  - `classify_value(value, range_dict) -> {zone, color}`
  - `mix_hex(a, b) -> str`
- `routes_general.py`의 `/last`·`/past` 응답에 옵션 플래그(`?with_range=1`)로 범위 메타 동봉(기존 응답 형식 비파괴, 가산만).

---

## 5. 프런트엔드 (UI)

### 5.1 페이지 `templates/pages/measurement_range.html`
- 상단: `aot-tabs.js` 기반 탭 바(생성/이름변경/복제/삭제) — input/function 페이지와 동일 패턴.
- 본문: 탭 내 범위 프로파일 카드 목록.
- "범위 추가" 폼:
  - 측정 대상 선택: 측정 유형(드롭다운, 멀티 선택) + 선택적 특정 센서 채널(오버라이드).
  - 임계값 4개 입력(low_max / safe_min / safe_max / high_min) — 오름차순 유효성 검사.
  - 색상 3개: `aot-color-picker` (낮음/안전/높음, 기본값 프리셋).
  - 중간 구간 색상: 기본 "자동(중간색)" 표시 + 펼치면 오버라이드 색상 지정.
  - 실시간 미리보기 바: 5구간 색상 그라데이션 + 임계값 눈금.

### 5.2 공유 JS 유틸 `static/js/components/aot-measurement-range.js`
- `AoTRange.classify(value, range)` → `{zone, color}` (백엔드 `classify_value`와 동일 규칙).
- `AoTRange.mixHex(a, b)`.
- `AoTRange.applyTo(element, value, range)` → 배경/테두리 색 적용 헬퍼.
- 위젯·function UI에서 공통 import.

---

## 6. 사용처 연동

### 6.1 위젯
- 측정값 표시 위젯(예: `aot-map-sensor-labels.js`, facility status)이 값 표시 시
  `AoTRange.classify`로 색상 결정. 범위 메타는 `/last?with_range=1` 또는
  `/api/measurement_range/resolve`에서 취득(채널 오버라이드 자동 반영).

### 6.2 function / 시스템 로직
- `aot/utils/measurement_range_util.resolve_range` + `classify_value`를 custom_functions에서 호출.
- 예: env_coordinator가 현재 측정값의 zone이 `high`/`low`면 안전 제약 트리거에 참고.
- 로직 레벨 참고이므로 zone 문자열(`low/warn_low/safe/warn_high/high`)을 반환 계약으로 고정.

---

## 7. 작업 분해 (구현 단계 — 승인 후 진행)

1. 모델 `measurement_range.py` + `__init__` export + Alembic 마이그레이션.
2. 공유 유틸: Python `measurement_range_util.py`, JS `aot-measurement-range.js` (분류/중간색 동일 규칙, 단위 테스트).
3. `routes_tab.py` / `TabService` whitelist에 `measurement_range` 추가.
4. 블루프린트 `routes_measurement_range.py` (페이지 + save/delete + resolve API) + `app.py` 등록.
5. `measurement_range.html` 페이지 + 폼 + 미리보기.
6. `/last`·`/past`에 `with_range` 가산 + 위젯 1곳 시범 연동.
7. function 연동 예제(env_coordinator) + 문서화.

---

## 8. 미해결/확인 필요

- 측정 유형 키의 정규화: `Measurement.name_safe` vs `DeviceMeasurements.measurement` 중 매칭 키 확정 필요.
- 동일 측정 유형에 탭이 여러 개일 때 우선순위(현재는 "채널 오버라이드 > 유형 기본"만 정의; 탭 간 충돌은 활성 탭 기준으로 한정 제안).
- 임계값 미설정(부분 구간만 정의) 허용 여부 — 초기엔 4개 필수로 단순화 제안.
