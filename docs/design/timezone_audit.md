# 시스템 전역 시간(Timezone) 처리 로직 점검 보고서

작성일: 2026-06-05
범위: input / output / function / gis-input / controller / pid 등 시간 사용 전 영역
요구사항: 각 장치에 포함되는 **위치(좌표) 기준으로 시간대를 적용**하여 처리

---

## 0. 결론 요약

핵심 인프라(장치별 좌표→타임존 해석)는 **이미 잘 구축되어 있고**, 가장 중요한
시간-임계 백엔드 로직(트리거 스케줄·시퀀스 윈도우·요일·PID 시간대별 설정점)은
**device timezone을 올바르게 사용**한다. 다만 다음 **4개의 일관성 결함**이 존재한다.

| # | 심각도 | 문제 | 영향 |
|---|--------|------|------|
| P1 | 중간 | Conditional / generic Function 생성 시 좌표 자동 할당 누락 | 위치 미지정 시 시스템 tz로 폴백 |
| P2 | 중간 | `epoch_of_next_time()` pytz `.replace()` DST 미보정 | DST 지역 경계에서 1시간 오차 |
| P3 | 중간 | 프론트엔드 `AoTTz.formatDevice` 미사용 | 위젯 시각이 뷰어(브라우저) tz로 표시 |
| P4 | 낮음 | GIS 입력 위성 타일 날짜를 UTC로 선택 | 시설 로컬 날짜와 하루 어긋날 수 있음 |

---

## 1. 현재 아키텍처 (정상 동작 부분)

### 1.1 두 계층의 타임존 시스템
- **장치 단위(per-device)** — `aot/utils/device_tz.py`
  - `resolve_tz_from_coords(lat, lon)` : timezonefinder로 좌표→IANA tz
  - `get_device_tz(device)` : `device.timezone → 좌표 → Misc.timezone → UTC` 우선순위
  - `to_device_tz()`, `device_tz_name()`
- **시스템 단위(fallback)** — `aot/utils/tz_utils.py`, `aot/utils/time_utils.py`
  - `Misc.timezone`(설정 페이지 값) 기반. 좌표가 없을 때의 폴백.

### 1.2 모델 스키마 (정상)
`Input` / `Output` / `Function` / `Conditional` / `Trigger` / `PID` /
`CustomController` 모두 `latitude`, `longitude`, `timezone`(IANA),
`location_source`, `location_updated_utc` 컬럼 보유.
([input.py:47](aot/databases/models/input.py:47), function.py, pid.py 동일)

### 1.3 좌표→tz 자동 채움 리스너 (정상)
[device_tz_listeners.py](aot/databases/device_tz_listeners.py) — `before_insert`/
`before_update`에서 좌표 변경 시 `timezone` 컬럼을 자동 재계산.
Input/Output/PID/Controller/Function/Conditional/Trigger에 부착.

### 1.4 시간-임계 백엔드 로직 (정상 — device tz 사용)
- **트리거** [controller_trigger.py:211-279](aot/controllers/controller_trigger.py:211)
  — `get_device_tz`로 HH:MM·daily window를 장치 로컬 시계 기준 비교.
- **시퀀스** [controller_trigger_sequence.py:267-572](aot/controllers/controller_trigger_sequence.py:267)
  — 요일(weekday)·윈도우를 `device_tz`로 평가. (요일 0=Mon~6=Sun 로컬 기준)
- **PID** [controller_pid.py:387-399](aot/controllers/controller_pid.py:387)
  — `_resolve_facility_tz()`가 `get_device_tz`로 DailyMultiPoint 시간대별 설정점 계산.
- **스케줄 헬퍼** [system_pi.py:487,540](aot/utils/system_pi.py:487)
  — `time_between_range(tz=)`, `epoch_of_next_time(tz=)` 모두 tz 인자 지원.

### 1.5 신규 장치 좌표 자동 할당 (대부분 정상)
생성 시 `misc.map_latitude/longitude`(지도 중심)를 기본 좌표로 부여.
function 계열(Conditional/PID/Trigger/Function/CustomController)의 **실제 생성
경로는 모두 `function_add()`** ([utils_function.py:73](aot/aot_flask/utils/utils_function.py:73))이며,
`utils_controller.py`/`utils_pid.py`는 modify(편집) 전용이다.

| 장치 | 생성 경로 | 좌표 자동 할당 |
|------|-----------|:---:|
| Input | [utils_input.py:115](aot/aot_flask/utils/utils_input.py:115) | O |
| Output | [utils_output.py:167](aot/aot_flask/utils/utils_output.py:167) | O |
| PID | [utils_function.py:191](aot/aot_flask/utils/utils_function.py:191) | O |
| Trigger | [utils_function.py:241](aot/aot_flask/utils/utils_function.py:241) | O |
| CustomController | [utils_function.py:292](aot/aot_flask/utils/utils_function.py:292) | O |
| **Conditional** | [utils_function.py:114-160](aot/aot_flask/utils/utils_function.py:114) | **X 누락** |
| **Function(actions)** | [utils_function.py:251-266](aot/aot_flask/utils/utils_function.py:251) | **X 누락** |

---

## 2. 발견된 문제점 및 개선 제안

### P1. Conditional / generic Function 생성 시 좌표 자동 할당 누락 (심각도: 중간)

**정정 사항**
이전 초안에서 "Controller·PID 누락"으로 기재한 것은 오류였다. 실제 생성은
`utils_controller.py`/`utils_pid.py`(편집 전용)가 아니라 `function_add()`에서
처리되며, 거기서 **PID·Trigger·CustomController는 모두 좌표를 정상 부여**한다.

**현상**
`function_add()`의 분기 중 **Conditional**([utils_function.py:114-160](aot/aot_flask/utils/utils_function.py:114))과
**generic Function(`function_actions`)**([utils_function.py:251-266](aot/aot_flask/utils/utils_function.py:251))
분기에만 `misc.map_latitude/longitude` 부여 코드가 빠져 있다. (다른 분기엔 존재)

**영향**
- Conditional: 좌표 미부여 → `latitude/longitude = None` → `get_device_tz`가
  `Misc.timezone`(시스템 tz)으로 폴백. Conditional 사용자 코드에서 시간 기반
  조건(예: 기본 템플릿의 `datetime.now()`)을 쓰면 장치 위치가 아닌 **시스템
  로컬 시계** 기준으로 평가된다.
- generic Function: 독립적인 시간 스케줄 주체는 아니나, 일관성 측면에서 동일 누락.

요구사항("장치 위치 기준 시간대")과 부분 충돌(주로 Conditional).

**개선 제안**
다른 분기와 동일하게 두 분기에도 좌표 부여 추가(리스너가 tz 자동 산출):
```python
# Conditional 분기(save 직전), Function 분기(save 직전)에 추가
try:
    misc = Misc.query.first()
    if misc:
        new_func.latitude = misc.map_latitude
        new_func.longitude = misc.map_longitude
except Exception:
    pass
```

### P2. `epoch_of_next_time()` pytz `.replace()` DST 미보정 (심각도: 중간)

**현상** [system_pi.py:553-559](aot/utils/system_pi.py:553)
```python
now_local = datetime.datetime.now(local_tz)
target = now_local.replace(hour=h, minute=m, second=s, microsecond=0)
```
pytz aware datetime에 `.replace()`를 쓰면 "지금" 시점의 고정 offset이 유지되어,
DST 경계를 넘는 목표 시각에서 offset이 어긋난다. `time_between_range`의
`datetime.now(local_tz)`는 정상이지만, 미래 시각 산출만 취약.

**영향**
한국(Asia/Seoul, DST 없음)에서는 무해. 그러나 **DST가 있는 지역에 위치한
장치**의 일일 예약 시각이 봄·가을 전환 경계 ±1일 구간에서 1시간 오차.

**개선 제안**
naive datetime을 만든 뒤 `localize(..., is_dst=None)`로 보정:
```python
naive = datetime.datetime.now(local_tz).replace(tzinfo=None).replace(
    hour=h, minute=m, second=s, microsecond=0)
target = local_tz.localize(naive)   # pytz가 올바른 DST offset 적용
```

### P3. 프론트엔드 device-tz 표시 유틸 미사용 (심각도: 중간)

**현상**
[aot-tz.js](aot/aot_flask/static/js/common/aot-tz.js)에 `AoTTz.formatDevice(iso, deviceTz)`가
구현되어 layout에 로드되지만, **실제 위젯은 거의 사용하지 않는다.**
타임스탬프 렌더링이 브라우저 로컬(viewer) tz의 raw `toLocaleString`으로 처리됨:
- [aot-facility-status.js:54](aot/aot_flask/static/js/widgets/AoT_facility/aot-facility-status.js:54) — `new Date().toLocaleTimeString()`
- [sensor-label.js:160](aot/aot_flask/static/js/common/sensor-label.js:160) — `d.toLocaleString()`

`AoTTz` 사용처는 layout 로드 + 정의 파일뿐(grep 결과 위젯 JS에 호출 없음).

**영향**
장치와 다른 시간대에서 접속한 사용자는 **장치 위치 로컬 시각이 아닌 본인 브라우저
시각**으로 본다. 요구사항("장치 위치 기준")과 표시 계층이 어긋남.

**개선 제안**
1. 백엔드는 장치 관련 타임스탬프를 항상 UTC+offset ISO로 내려보냄
   (`time_utils.api_iso`). 표시 가공 금지.
2. 프론트엔드는 `data-aot-ts` + `data-aot-tz="<device tz>"` 또는
   `AoTTz.formatDevice(iso, deviceTz)`로 렌더링. 장치 tz는
   `/api/timezone/device/<unique_id>` ([api/timezone.py:42](aot/aot_flask/api/timezone.py:42))로 조회.
3. 위젯의 `toLocaleString`/`toLocaleTimeString` 직접 호출을 점진 교체.

### P4. GIS 입력 위성 타일 날짜를 UTC로 선택 (심각도: 낮음)

**현상**
[gis_esa.py:91,110](aot/inputs_gis/gis_esa.py:91), [gis_nasa_gibs.py:254,284](aot/inputs_gis/gis_nasa_gibs.py:254)
가 `datetime.utcnow()`로 "오늘/어제" 타일 날짜를 산출.

**영향**
원격탐사 자료는 본래 UTC 기준이라 치명적이진 않으나, 시설 로컬 날짜가 UTC와
다른 시간대(예: KST는 UTC+9)에서 "오늘 영상" 선택이 하루 어긋날 수 있다.

**개선 제안**
gis-input도 장치 좌표를 갖고 있으므로, 날짜 롤오버를 `get_device_tz` 기준
로컬 날짜로 계산 (`to_device_tz(utc_now(), device).date()`).

---

## 3. 일관성 권고 (구조)

1. **단일 진실 공급원 표준화**
   - 저장/연산: 항상 UTC aware (`utc_now()`). 코드 전반에 혼재된
     `datetime.utcnow()`(naive) / `datetime.now()`(시스템 로컬)를 `utc_now()`로 수렴.
   - 직렬화: 장치 관련 응답은 `api_iso()`(UTC+offset)로 통일.
     `serialize_ts()`(시스템 tz 변환)는 시스템 전역 표시에만 한정.
2. **장치 시각 변환 단일 함수**: 백엔드 `to_device_tz`, 프론트 `AoTTz.formatDevice`만
   사용. 그 외 직접 `astimezone`/`toLocaleString`은 점진 제거.
3. **좌표 누락 폴백 가시화**: 좌표 없는 장치가 시스템 tz로 폴백할 때 UI에
   "위치 미지정(시스템 시간대 사용)" 배지 노출 권장.

---

## 4. 권장 작업 우선순위

1. (P1) Conditional·generic Function 신규 생성 좌표 자동 할당 — 즉시, 소규모 패치
2. (P3) 프론트엔드 위젯 타임스탬프를 `AoTTz.formatDevice`로 교체 — 영향도 높음
3. (P2) `epoch_of_next_time` DST 보정 — DST 지역 대비
4. (P4) GIS 타일 날짜 로컬화 — 정확도 개선
5. (구조) UTC 저장 / api_iso 직렬화 표준화 점진 적용
