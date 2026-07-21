# AoT 시간 처리 설명서

이 문서는 AoT 시스템이 **시간과 시간대(timezone)를 어떻게 다루는지**를 설명한다.
설계 배경·의사결정은 저장소의 `docs/design/timezone-management.md`(개발용, 매뉴얼 미발행)에 있고,
이 문서는 "실제로 어떻게 동작하며 개발자는 무엇을 쓰면 되는가"를 다룬다.

---

## 1. 한눈에 — 핵심 3원칙

1. **저장은 항상 UTC.** DB·InfluxDB·로그의 모든 시각은 UTC 기준이다.
2. **표시는 상황에 맞는 시계로.** 장치 예약은 *장치 현지 시각*, 개인 알림은 *보는 사람의 시각*으로 보여준다.
3. **해석 진입점은 하나.** 시간대 관련 계산은 `aot/utils/timekit.py` 한 곳으로 모인다.

---

## 2. 시간은 두 종류다

성격이 다른 두 시간을 구분하는 것이 전부의 출발점이다.

| | A. 절대시각 (Instant) | B. 벽시계 의도 (Wall-clock intent) |
|---|---|---|
| 예 | 센서값, 로그, `created_at`, "밸브 켜진 순간" | "06시에 관수", "매일 새벽 예약" |
| 성격 | 타임라인 위의 한 점 | 사람이 특정 시계로 말한 시각 |
| 저장 | UTC 하나로 충분·명확 | UTC로 바로 못 접음 — **어느 시계의 06시인지**(앵커)가 필요 |
| 표시 | 원하는 tz로 변환만 | 앵커 tz로 되돌려야 의도가 보존됨 |

> **왜 중요한가:** "+6 지역 장치의 06시 관수"는 그 밭이 아침 6시일 때 물을 주는 것이지,
> +9 사무실의 6시가 아니다. 벽시계 의도는 반드시 **어느 곳의 시계인지**를 함께 알아야 한다.

---

## 3. 시간대의 4계층 + 호스트 시계

시스템에 관여하는 시간대 원천은 4개다. 넷은 서로 다를 수 있다.

| 계층 | 무엇 | 어디에 저장 |
|---|---|---|
| **장치 tz** | 각 장치(입력/출력/함수/PID…)의 위치 시간대 | `input.timezone` 등 (좌표/상속에서 산출·캐시) |
| **도형 tz** | 지도 도형(사이트/구역/시설)의 시간대 — tz의 **권위** | `geo_shape.timezone`, `geo_facility.timezone` |
| **사용자 tz** | 개인 표시 선호 | `users.timezone` (미설정 시 시스템으로 폴백) |
| **시스템 tz** | 농장 전역 기본값 (최후 폴백) | `misc.timezone` |

그리고 이와 별개로 **호스트 OS 시계**가 있다.

- **호스트 OS 시계 = "지금"의 유일한 공급원. tz가 아니다.**
  Docker 컨테이너는 항상 UTC로 취급하며 OS의 로컬 tz에 의존하지 않는다.
  역할은 오직 `timekit.utc_now()`로 **현재 UTC 순간**을 주는 것. 스케줄러 발화는
  `fire_utc <= utc_now()` 비교로만 이뤄지며 여기에는 tz가 개입하지 않는다.
- **`misc.timezone`(시스템 tz)은 "농장 기본값" 최후 폴백일 뿐, 의도의 해석기가 아니다.**
  장치/도형이 위치를 가지면 절대 시스템 tz로 떨어지지 않는다. 실제로 시스템 tz가
  쓰이면 그 사실이 기록·라벨된다.

---

## 4. 저장 규약 — 왜 naive datetime이 섞여도 안전한가

- **신규 코드는 tz-aware UTC**(`timekit.utc_now()` = `datetime.now(timezone.utc)`)를 쓴다.
- **레거시 코드에는 naive `datetime.utcnow()`가 다수 남아 있다.** 이는 버그가 아니다 —
  프로젝트 규약상 **naive datetime은 UTC로 간주**하며, `timekit.ensure_utc()`가 읽는 시점에
  `+00:00`을 붙여 정규화하기 때문이다.
- **SQLite 컬럼 왕복도 안전**하다: aware UTC(`00:00+00:00`)를 naive `DateTime` 컬럼에 저장하면
  SQLite/SQLAlchemy가 tzinfo만 벗기고 값(UTC 00:00)은 보존한다. 읽으면 naive `00:00`이 되고
  `ensure_utc`가 다시 `00:00+00:00`으로 복원한다. **SQL 필터**(`schedule_time >= utc_now()`)도
  bind 시 tz가 벗겨져 naive-UTC끼리 비교되므로 정확하다.

> **함정:** naive로 저장되는 컬럼에는 **반드시 UTC-aware(또는 UTC naive) 값만** 넣어야 한다.
> 만약 `Asia/Seoul`-aware 값을 그대로 넣으면 tzinfo가 벗겨지며 서울 벽시계가 UTC로 오인되어
> 9시간 어긋난다. 그래서 저장 전 항상 UTC로 변환한다(`wall_to_utc`, `utc_now`는 이미 UTC).

---

## 5. 단일 해석기 — `aot/utils/timekit.py`

시간대 관련 모든 것은 이 모듈로 모인다. 기존에 흩어져 있던 게이트
(`get_device_tz`·`get_user_tz`·`get_timezone_name`·`resolve_location_tz` 등)는 이제 이 모듈로
위임한다.

| 함수 | 용도 |
|---|---|
| `utc_now()` / `now_utc()` | tz-aware 현재 UTC "지금" |
| `ensure_utc(dt)` | naive→UTC 가정, aware→UTC 변환 (정규화) |
| `to_tz(dt, tz)` | UTC(또는 naive=UTC) → 대상 tz |
| `iso_utc(dt)` | API 직렬화 표준 — 항상 `+00:00` ISO 문자열 |
| `resolve_tz(entity=None, *, user=None) → (tzinfo, source)` | **단일 해석 체인**(아래) |
| `system_tz()` / `system_tz_name()` | 농장 전역 기본 tz (Misc) |
| `current_user_tz()` | 요청 사용자 개인 tz (없으면 시스템). 개인 표시 전용 |
| `wall_to_utc(wall, tz)` | 벽시계 + 앵커 tz → UTC-aware (예약 저장, DST 정확) |
| `utc_to_wall(dt, tz)` | UTC → 앵커 tz 벽시계 (예약 표시) |

### `resolve_tz` 우선순위 체인

```
entity 가 도형(GeoShape/GeoFacility):
    자체 상속-aware 해석기 사용 (저장값 → 부모 → facility → centroid)
entity 가 장치 row:
    1. entity.timezone (물질화 캐시)            → 캐시의 tz_source
    2. 소속 도형 상속(device_id→도형→부모체인)  → inherited
    3. entity 좌표 → timezonefinder             → coords
    4. 시스템(Misc.timezone)                    → system
user:
    User.timezone → 시스템
entity=None:
    시스템 → UTC
```

> **읽기는 O(1):** 장치의 `timezone` 컬럼은 **물질화된 캐시**다. 좌표→시간대 변환
> (`timezonefinder`)은 무겁지만, 이는 도형/장치가 **생성·편집될 때만** 1회 돌고 결과가
> 컬럼에 저장된다. 스케줄러 발화·표시 등 실행 경로는 컬럼만 읽는다.

---

## 6. 예약이 흐르는 과정 (+9 사용자 / +6 장치 예시)

사용자(서울, +9)가 카자흐스탄(다카, +6)의 밸브에 "관수 06:00"을 예약한다고 하자.

```
1. 앵커 결정   : 타겟이 장치이므로 앵커 tz = 장치 현지(Asia/Dhaka, +6)
                 (_resolve_schedule_anchor)
2. 저장        : wall_to_utc("06:00", Asia/Dhaka) = 2026-07-22 00:00Z
                 SchedulerJobMeta.schedule_time=00:00Z, anchor_tz='Asia/Dhaka'
3. 발화        : utc_now()가 00:00Z에 도달하면 실행 (tz 무관)
4. 표시(운영)  : 장치 현지 06:00 (Asia/Dhaka) — _schedule_summary.when
5. 표시(사용자): 같은 순간을 서울로 → 09:00 (Asia/Seoul)
```

**핵심:** 저장은 UTC 하나(`00:00Z`)뿐이고, `06:00`(장치)과 `09:00`(사용자)은 그 순간의
서로 다른 표현이다. 신규 작업 폼은 이 셋을 **실시간 이중시계**로 함께 보여준다:

```
관수 · [밸브6(+6)] · 06:00
  Device-local: 2026-07-22 06:00 (Asia/Dhaka)   ← 실제 적용
  Your time:    2026-07-22 09:00 (Asia/Seoul)   ← 당신 화면
  UTC:          2026-07-22 00:00
```

> **확정 정책:** 장치 예약의 벽시계는 **기본적으로 장치 현지 시각**으로 해석한다
> (작물의 태양일 기준). 편집 화면의 `datetime-local` seed도 장치 현지로 표시되어 저장 해석과
> 일치하므로 왕복에서 어긋나지 않는다.

---

## 7. 표시 규칙

문맥이 tz를 결정한다. **서버에 특정 tz를 굽지 않는다.**

| 문맥 | 시계 | 방법 |
|---|---|---|
| 운영(스케줄러·장치 로그·"언제 발화") | **장치 tz** + 라벨 | 프론트 `AoTTz.formatDevice(iso, deviceTz)` |
| 개인(사용자 알림·"네가 방금 한 일") | **뷰어/사용자 tz** | `AoTTz.formatViewer(iso)` |
| 여러 tz를 겹치는 달력 축 | **뷰어 tz** | FullCalendar `timeZone:'local'` |

- 서버 API는 **UTC ISO**(`iso_utc`)만 내려주고, 표시 tz는 클라이언트 `AoTTz`가 고른다.
- 프론트 단일 유틸: `aot/aot_flask/static/js/common/aot-tz.js`(`window.AoTTz`).
  - `formatDevice(iso, tz)` — 장치 현지
  - `formatViewer(iso)` — 뷰어(개인 tz 우선 → 브라우저 → 시스템)
  - `wallToInstant(wall, tz)` — 벽시계를 tz 시계로 해석해 절대순간 반환(이중시계용)
  - 뷰어 tz는 `<meta name="aot-user-tz">`(User.timezone) > 브라우저 tz > `aot-fallback-tz`(시스템).

---

## 8. 시간대 상속 (도형 트리)

장치가 수천 개로 늘어도 장치마다 시간대를 연산하지 않는다. **tz는 위치 그룹의 속성**이다.

```
Site (GeoShape)      → tz 권위. 명시 override | centroid 1회 해석 → 물질화
 └ Zone (GeoShape)   → Site 상속. 필요 시 override → 물질화
     └ Device        → 소속 Zone/Site 상속(캐시)
```

- 도형 트리는 `geo_shape.parent_id`(자기참조), 물리 장치 연결은 `geo_shape.device_id`.
- `tz_source`(`explicit` | `inherited` | `coords`)가 값의 출처를 표시한다. `explicit`(수동 override /
  경계 그룹 선택)은 **핀**으로 취급되어 자동 갱신이 덮어쓰지 않는다.
- **물질화·전파:** 지도 저장(`save_overlays`/`save_delta`) 커밋 후
  `GeoOverlayManager.materialize_timezones(map_uuid)`가 site→zone→device 순으로 tz를 계산해
  캐시하고 연결 장치에 전파한다. 부모 도형의 tz override는 자식·장치로 흘러내린다.

---

## 9. 시간대 경계 / 날짜변경선

운영 그룹이 걸쳐 있어도 **분열하지 않는다.**

- 밭이 tz 경계에 걸쳐도 **사이트가 단일 tz를 정하고 서브트리 전체가 상속** → "한 밭 = 한 시계".
- 경계 감지는 **편집 시 1회**: 도형 저장 시 `GeoShape.detect_tz_boundary()`가 bbox 4모서리의
  tz를 조회해 서로 다르면 `tz_boundary=True`로 표시한다.
- `timezonefinder`는 **법정(정치) 경계** 기준이라 중국 전역 +8, 스페인 +1, 카자흐 Almaty +5 등
  "태양시와 다른 법정시"를 이미 정확히 반환한다.

---

## 10. 개발자 빠른 참조 — "언제 무엇을 쓰나"

| 하고 싶은 것 | 쓸 것 |
|---|---|
| "지금" (UTC) | `timekit.utc_now()` |
| 저장된 naive/aware datetime을 UTC로 정규화 | `timekit.ensure_utc(dt)` |
| API 응답에 시각 직렬화 | `timekit.iso_utc(dt)` → 프론트 `AoTTz` |
| 어떤 엔티티의 시간대 알기 | `timekit.resolve_tz(entity)` (또는 `device_tz.get_device_tz`) |
| 위치 id로 현지 시간대 | `device_tz.resolve_location_tz(target_id)` |
| 예약 벽시계 → 저장 | `timekit.wall_to_utc(wall, anchor_tz)` |
| 예약 UTC → 표시 | `timekit.utc_to_wall(dt, tz)` 또는 `to_tz` |
| 개인 표시 tz (요청) | `timekit.current_user_tz()` |
| 프론트에서 장치 시각 표시 | `AoTTz.formatDevice(iso, deviceTz)` |
| 프론트에서 내 시각 표시 | `AoTTz.formatViewer(iso)` |

---

## 11. 함정 모음

- **naive 컬럼에는 UTC 값만.** 비-UTC aware를 넣으면 tzinfo가 벗겨지며 오인된다(§4).
- **벽시계 해석은 앵커 tz로.** 사용자 브라우저 tz나 시스템 tz로 해석하면 다른 tz 장치에서 어긋난다.
  예약은 `wall_to_utc(wall, device_anchor)`.
- **`get_user_tz()`는 실제로 시스템 tz다.** 이름과 달리 개인 tz가 아니다(벽시계 해석·daemon 호환용).
  개인 표시는 `current_user_tz()`.
- **`serialize_ts()`는 시스템 tz로 서버 변환한다.** 장치 관련 표시에는 쓰지 말고 `iso_utc` + `AoTTz`.
  (스케줄러 `_serialize_job`의 `decided_at`/`executed_at`/`created_at`은 감사 메타라 아직 `serialize_ts`
  잔존 — 알려진 경미한 갭.)
- **`datetime.now()`(시스템 로컬)를 "UTC now"로 쓰지 말 것.** Docker에선 우연히 같지만 non-UTC
  호스트에서 어긋난다. `utc_now()`를 쓴다. (단, 경과시간 측정·offset 계산 목적의 `datetime.now()`는
  의도적이며 그대로 둔다.)
- **장치 `timezone` 캐시는 위치 편집 이벤트에서만 갱신된다.** 좌표를 바꿨는데 tz가 안 바뀌면
  물질화(`materialize_timezones`)나 좌표 리스너 경로를 확인한다.

---

## 12. 관련 파일

- 백엔드 단일 진입점: `aot/utils/timekit.py`
- 좌표→tz·위치 해석: `aot/utils/device_tz.py`
- 도형 tz/상속/경계: `aot/databases/models/geo.py`, `aot/aot_flask/geo/geo_overlays.py`
- 좌표→tz 자동 물질화 리스너: `aot/databases/device_tz_listeners.py`
- 예약 앵커·표시: `aot/ai/services/aot_data_tool_service.py`, `aot/aot_flask/routes_scheduler.py`
- 프론트 표시 유틸: `aot/aot_flask/static/js/common/aot-tz.js`
- 설계·의사결정: `docs/design/timezone-management.md` (개발용, 매뉴얼 미발행)
- 이전 점검 보고서: `docs/design/timezone_audit.md` (개발용, 매뉴얼 미발행)
