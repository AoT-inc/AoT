# AoT — 통합 시간 관리 설계 (Design Doc v1)

상태: **설계 확정 · Phase 1 구현·검증 완료(무동작변경 리팩터)** · 작성 근거: 현행 시간 처리 코드 실측 + 대화 확정 결정
목표 독자: AoT 개발자 · 이 문서는 [timezone_audit.md](timezone_audit.md)(2026-06-05 시점 점검)를 **계승·확장**한다.
audit는 "무엇이 잘못됐나"를 나열한 점검서이고, 이 문서는 "하나의 구조로 어떻게 통합하나"를 정하는 설계서다.

---

## 1. 왜 재설계인가 (한 문장)

시간대를 해석하는 진입점이 **5개로 흩어져 각자 다른 폴백을 구현**하고, 그 결과
"장치별 시간대"는 저장만 될 뿐 **스케줄 해석에는 시스템 tz 하나로 붕괴**되며,
"사용자 시간대"는 아예 존재하지 않는다. 기능별 땜질(과거 커밋 다수)로는 못 고친다.

### 현행 구조의 구조적 결함 (실측)

| 요구 | 현재 상태 | 근거 |
|---|---|---|
| 장치별 tz로 예약 해석 | 저장은 하나 **예약 해석은 시스템 tz로 붕괴** | `_schedule_wall_to_utc`가 `get_user_tz()`=`Misc.timezone`으로 해석 ([aot_data_tool_service.py:1040](../../aot/ai/services/aot_data_tool_service.py:1040)) |
| 사용자별 tz | **User 모델에 timezone 컬럼 없음.** `get_user_tz()`는 이름만 user, 실제는 시스템값 | [tz_utils.py:16](../../aot/utils/tz_utils.py:16) |
| 단일 해석 진입점 | 5개(`get_device_tz`·`resolve_location_tz`·`get_user_tz`·`get_timezone_name`·`GeoShape/GeoFacility.resolve_timezone`)가 유사하나 미묘히 다른 폴백 각자 구현 | device_tz.py, tz_utils.py, geo.py |
| 표시 단일화 | 서버측 `serialize_ts`(시스템 tz 변환)와 클라이언트 `AoTTz`(뷰어/장치 tz) 두 갈래 공존 | [routes_scheduler.py:453](../../aot/aot_flask/routes_scheduler.py:453) vs [aot-tz.js](../../aot/aot_flask/static/js/common/aot-tz.js) |
| 브라우저 벽시계 해석 | `datetime-local`(브라우저 로컬)을 `get_user_tz()`(시스템 tz)로 해석 → 브라우저≠시스템이면 어긋남 | [routes_scheduler.py:213](../../aot/aot_flask/routes_scheduler.py:213) |

---

## 2. 개념 모델: 시간은 두 종류뿐이다

혼란의 근본 원인은 성격이 다른 두 시간을 한 덩어리로 다룬 것이다. **분리가 핵심.**

| | A. 절대시각 (Instant) | B. 벽시계 의도 (Wall-clock intent) |
|---|---|---|
| 예 | 센서값, 로그, created_at, "밸브 켜진 순간" | "06시에 관수", "매일 새벽 예약" |
| 저장 | UTC 하나면 충분·명확 | UTC로 못 접음 — **어느 시계의 06시인지** 앵커가 필요 |
| 표시 | tz만 골라 변환 | 앵커 tz로 재표시해야 의도 보존 |

**원칙:** 장치 예약은 B(벽시계 의도)이며, 그 벽시계는 원칙적으로 **"장치가 있는 곳의 시계"**다.
관수·조명·환기는 조작자가 아니라 *작물의 태양일(solar day)*에 묶이기 때문이다.

---

## 3. 4계층 tz, 그리고 "시스템 시간"의 분해

시스템에 관여하는 tz 원천은 4개: **장치 · 도형 · 사용자 · 시스템**. 넷은 서로 다를 수 있다.
여기서 "시스템 시간"이 모호함의 씨앗이므로 **두 개로 분해**한다.

### 3.1 호스트 OS 시계 = "지금"의 유일한 공급원 (tz 아님)
Docker 컨테이너는 항상 UTC로 취급, OS tz 의존 금지([tz_utils.py:8](../../aot/utils/tz_utils.py:8)). OS 시계의
유일한 역할은 `utc_now()`로 **현재 절대순간(UTC)**을 주는 것. 스케줄러는 `fire_utc <= utc_now()`로
발화만 판정하며 **여기엔 tz가 개입하지 않는다.**

### 3.2 `Misc.timezone` = 농장 전역 기본 시간대 (최후 폴백, 해석기 아님)
과거 버그는 이 값을 벽시계 **의도의 해석기**로 써서 모든 예약을 하나로 붕괴시킨 것.
재설계에서 역할을 **엄격히 축소**한다:
- `resolve_tz` 체인의 **맨 마지막 단계**로만 사용.
- 장치/도형이 **위치를 가지면 절대 시스템 tz로 떨어지지 않는다.**
- 실제로 시스템 tz가 답이 되면 `anchor_source='system'`으로 **기록·라벨**한다(조용한 폴백 금지).

### 3.3 다시 붕괴하지 않게 막는 3규칙
1. **위치가 있으면 시스템 tz로 떨어지지 않는다.** 예약은 항상 장치/도형을 먼저 통과시켜 해석.
2. **시스템 tz 사용은 항상 기록·라벨된다** (`anchor_source`).
3. **`Misc.timezone`의 이중 역할을 끊는다.** 사용자 tz는 `User.timezone`으로 분리, 시스템 tz는 순수 폴백.

---

## 4. 상속 계층 모델 (스케일·경계의 공통 해답)

장치가 수천 개로 늘 때 장치마다 tz를 연산하는 것은 불합리하다. 그래서 **tz를 "장치의 속성"이
아니라 "위치 그룹(사이트/구역/시설)의 속성"으로 올린다.** 이 하나로 연산 폭증과 경계 분열이
동시에 해결된다.

### 4.1 이미 존재하는 뼈대
- **계층 트리**: `GeoShape.parent_id`(자기참조 FK, [geo.py:202](../../aot/databases/models/geo.py:202)) +
  `type` ∈ {site, zone, device, feature}, 레벨 `site:1 → zone:2 → device/feature:3`([geo.py:206](../../aot/databases/models/geo.py:206)).
- **장치→도형 연결**: 장치 쪽 구역 FK는 **없음**. `GeoShape.device_id`([geo.py:197](../../aot/databases/models/geo.py:197))가
  물리 장치를 가리킨다. 장치는 "나를 device_id로 가리키는 도형"을 찾아 `parent_id`를 타고 소속을 안다.
- **write-time 물질화 리스너**: [device_tz_listeners.py](../../aot/databases/device_tz_listeners.py)가
  좌표 변경 시 `timezone` 컬럼을 자동 재계산(before_insert/before_update). 상속 모델은 이 리스너의
  **출처를 "좌표"에서 "부모 도형 상속"으로 확장**해 얹는다.

### 4.2 권위는 도형 트리, 장치는 캐시
```
site  shape : tz = 명시 override | centroid 1회 해석        → 물질화(문자열)
 └ zone shape: tz = 자기 override | 부모(site) 상속          → 물질화
     └ device/feature shape : 부모 상속
```
물리 장치(Input/Output row)는 결과를 **캐시**한다:
```
device.timezone  ← 캐시. 읽기 O(1).
 채우는 출처(우선순위):
   1. tz_source='explicit' → 핀. 배치 갱신이 안 건드림
   2. 연결된 GeoShape(device_id) → parent_id 체인의 최근접 tz   ← 일반 경로
   3. (트리 밖 단독 장치) 자기 lat/lng → 좌표 해석
   4. 시스템(Misc.tz) → UTC   (anchor_source=system, 라벨)
```
장치 500개가 한 구역에 있어도 **tz 연산은 구역 1회**, 장치는 상속 캐시만 읽는다.

### 4.3 갱신·무효화 (이벤트 구동, 서브트리 한정)
- **읽기**: 항상 `device.timezone` 캐시 직독. timezonefinder 안 탐.
- **연산 시점**: 도형 지오메트리 생성/편집 때만.
- **무효화**: site/zone tz 변경 → 그 노드의 **서브트리(parent_id 자손) + 그 도형들의 device_id 장치**만
  배치 갱신. `explicit` 핀은 보존. 전역 재작성 없음.

---

## 5. `resolve_tz` — 단일 해석 체인

5개 게이트를 **하나의 함수**로 흡수한다. 모든 "여기 tz 뭐야?"는 이걸 부른다.

```
resolve_tz(entity=None, *, user=None) -> (ZoneInfo/pytz, source)

  entity(장치/도형):
    1. entity.timezone (tz_source='explicit')          → source=explicit
    2. 연결 도형 → parent_id 체인 최근접 tz             → source=inherited
    3. entity 좌표 → timezonefinder                     → source=coords
    4. 시스템(Misc.timezone)                            → source=system
  user:
    1. User.timezone (신설) if set                      → source=user
    2. 시스템                                            → source=system
  system:
    Misc.timezone → 'UTC'                               → source=system
```
> **Phase 1 주의**: Phase 1의 `resolve_tz`는 위 체인 중 **현행 동작과 동일한 부분만**(explicit→coords→system)
> 구현한다. 상속(2번)·User.timezone은 각각 Phase 3·4에서 편입한다. Phase 1은 순수 통합(무동작변경).

---

## 6. 스케줄 앵커링 (+9 사용자 / +6 장치 시나리오)

예약 한 건은 **세 가지를 함께** 저장한다:
1. `fire_utc` — 실제 발화 절대시각(UTC) *또는* 반복 규칙(cron)
2. `anchor_tz` — 그 벽시계가 어느 IANA 시계로 작성됐는지 (예 `Asia/Almaty`)
3. `anchor_source` — 그 tz의 출처 (`device`/`shape`/`user`/`system`)

사용자가 "관수 06:00" 지시 → UI는 암묵적으로 넘어가지 않고 **이중시계 확인**:
```
관수 · 매일 06:00
  현지(장치)   Asia/Almaty  +06   ← 실제 적용 (기본*)
  내 시각      Asia/Seoul   +09   → 09:00 로 보임
  UTC          2026-07-22 00:00Z
```
- **장치 적용 시각** = 앵커 tz(장치, +6)의 06:00 → `fire_utc=00:00Z`.
- **사용자 표시 시각** = 같은 `fire_utc`를 뷰어/사용자 tz로 재표시 → "당신 시각 09:00".
- 두 값은 같은 순간의 다른 표현. 저장은 UTC 하나. 라벨을 항상 붙여 +6/+9 혼동 차단.
- 반복 규칙은 `cron + anchor_tz`로 저장 → 앵커 tz에서 재평가되어 **DST까지 현지 기준**.

> \* **기본 앵커 정책(장치 현지 vs 사용자 vs 매번 확인)은 미확정** — §12 결정 항목. 개별 예약에서 항상 변경 가능.

---

## 7. 표시 규칙 (통일)

문맥이 tz를 결정하며, **서버에 굽지 않는다**:
- **운영 문맥**(스케줄러 그리드, 장치 로그, "언제 발화") → **장치 tz** 표시 + 라벨. `AoTTz.formatDevice(iso, deviceTz)`
- **개인 문맥**(사용자 알림, "네가 방금 한 일") → **뷰어/사용자 tz**.
- 장치 tz ≠ 뷰어 tz면 **항상 tz 라벨**.

핵심 변경: **API 응답은 UTC ISO만**(`iso_utc`, 기존 `api_iso`) 내려주고, 표시 tz는 클라이언트 `AoTTz`가
문맥별로 선택. `serialize_ts`(서버측 시스템 tz 변환)는 시스템 전역 표시에만 한정(장치 관련 응답에서 제거).

---

## 8. 시간대 경계 / 날짜변경선

상속 모델이 결정적: **운영 그룹이 단일 권위 tz를 정하므로 경계에 걸쳐도 분열하지 않는다.**
- 밭이 tz 경계에 걸쳐도 **사이트가 tz 하나를 정하고 서브트리 전체가 상속** → "한 밭 = 한 시계".
- **경계 감지는 편집 시 1회**(읽기 때 아님): site/zone 폴리곤 저장 시 **bbox 4모서리** tz 조회.
  전부 같으면 자동 확정. 다르면 `tz_boundary=true` + UI가 그룹 tz 명시 선택 강제.
- timezonefinder는 **법정(정치) 경계** 기준 → 중국 전역 +8, 스페인 +1 등 "태양시≠법정시"를 이미 정확 반환.
  180° 자오선 근처도 동일 메커니즘(모서리 tz 불일치 → 그룹 tz 선택).

---

## 9. 통합 API 표면

### 9.1 백엔드 — `aot/utils/timekit.py` (신설, 단일 모듈)
```
utc_now() / now_utc()          # tz-aware UTC "지금"
ensure_utc(dt)                 # naive→UTC 가정, aware→UTC 변환
to_tz(dt, tz)                  # UTC(또는 naive=UTC) → 대상 tz
iso_utc(dt)                    # API 직렬화 = 항상 UTC+offset ISO
resolve_tz(entity=None, *, user=None) -> (tzinfo, source)   # §5 단일 체인
system_tz()                    # Misc.timezone → tzinfo (농장 전역 폴백)
wall_to_utc(wall, tz)          # 벽시계 문자열/naive + tz → UTC-aware (예약 저장)
utc_to_wall(dt, tz)            # UTC → 대상 tz 벽시계 (예약 표시)
```
기존 `device_tz.py`·`tz_utils.py`·`time_utils`의 tz 함수, `GeoShape/GeoFacility.resolve_timezone`은
**얇은 wrapper로 전환 → 호출부 이관 → 삭제**의 3단계로 정리한다.

### 9.2 프론트 — `AoTTz` 단일 표시 모듈
위젯에서 즉석 `new Date().toLocaleString()` 포맷 금지(audit P3). 서버는 UTC ISO만, 표시는 `AoTTz`.

---

## 10. 스키마 변경 (실제 테이블 기준)

| 테이블 | 추가/변경 |
|---|---|
| `User` | `timezone`(String, nullable, IANA) **신설** — "사용자 tz" 실체화 |
| `GeoShape` | `timezone`(String, nullable) · `tz_source`('explicit'\|'inherited'\|'coords') · `tz_boundary`(bool) |
| `GeoFacility` | `timezone` 이미 있음([geo.py:411](../../aot/databases/models/geo.py:411)) — `tz_source` 추가 |
| Input/Output/Function/PID/… | `timezone`·`latitude`·`longitude` 이미 있음 — `tz_source` 추가. 개별 좌표는 **트리 밖 단독 배치일 때만** 유효 |
| `SchedulerJobMeta` | `anchor_tz`(String) · `anchor_source`(String) 추가. 시간 컬럼은 후반 단계에서 `DateTime(timezone=True)`로 |
| (선택) 장치·도형 | `tz_origin_id` — 상속 출처 조상(감사·"상속: 3-1 구역" 표시) |

---

## 11. 이행 단계

| Phase | 내용 | 동작변경 | audit 대응 |
|---|---|---|---|
| **1** | `timekit.py` 신설 + 기존 5게이트 wrapper화. 현행 동작 그대로 통합. | 없음(순수 리팩터) | 구조 통합 |
| **2** | 표시 통일: 장치 관련 응답 `iso_utc`화, `serialize_ts` 서버변환 제거, 위젯 `AoTTz.formatDevice` 교체. | 표시 tz 정정 | **P3** |
| **2 진행상태** | ✅ 스케줄러 `/timeline` offset 버그 수정(naive→`iso_utc`)·`_job_target_tz_name`(mcp_tool_call은 params.device_id 추적)·FullCalendar 클릭/툴팁에 장치현지+tz 라벨(AoTTz 최초 실사용). ⏸ **스케줄러 `schedule_time` 리스트/편집은 Phase 4로 이관**(아래 결합주의). ⏳ 위젯 타임스탬프(sensor-label 등)·serialize_ts 22곳 광범위 sweep 미착수. | | |
| **3** | 상속 계층: 도형 트리 tz 권위 + `tz_source` + 리스너를 부모상속으로 확장 + 경계 감지. | 장치 tz 출처 변경 | **P1** |
| **3a 완료** | ✅ 스키마: 장치7종 `tz_source`, `geo_shape`(timezone/tz_source/tz_boundary), `geo_facility` tz_source — 마이그레이션 `p6_05`(멱등, 단일 head). ✅ `GeoShape.resolve_timezone` 상속체인(저장값→parent_id→facility→centroid, cycle-guard). ✅ `timekit.resolve_tz` 장치 상속 폴백(device_id→도형→부모). 복사본에서 end-to-end 검증(좌표없는 장치가 site의 Asia/Dhaka 상속, source=inherited). | | |
| **3b 완료** | ✅ 물질화/전파: `GeoShape.compute_effective_tz`(부모→facility→centroid, self캐시 무시)·`detect_tz_boundary`(bbox 4모서리). `GeoOverlayManager.materialize_timezones(map_uuid)`가 저장(save_overlays/save_delta) 커밋 후 site→zone→device 순 물질화 + 연결장치 전파, `tz_source='explicit'` 핀 보존. device 리스너는 coords 물질화 시 `tz_source='coords'` 라벨·explicit 핀 스킵. 복사본 검증(site=Dhaka/coords→zone·device=Dhaka/inherited; zone을 Tokyo/explicit 고정 시 유지+device가 Tokyo 상속; Dhaka~Delhi 폴리곤 boundary=True). | | |
| **3b 후속** | ⏳ 경계 `tz_boundary=True` 시 UI가 그룹 tz 명시선택 강제(현재는 플래그만). ⏳ 시설/도형 tz override 설정 UI 엔드포인트. | | |
| **4** | 스케줄 앵커화: `anchor_tz/source` 컬럼 + 이중시계 UI + wall↔utc를 장치 tz 기준으로. `User.timezone` 편입. | 예약 해석 정정 | — |
| **4a 완료(AI 경로)** | ✅ `SchedulerJobMeta.anchor_tz/anchor_source` 컬럼(마이그레이션 `p6_06`). `_resolve_schedule_anchor`(target→장치현지 tz, 없으면 시스템). `_schedule_wall_to_utc(anchor_tz=)`. `add_schedule_tool`(타겟 먼저→앵커→UTC→meta 앵커저장)·`schedule_device_control_tool`(이미 장치앵커, 앵커저장 추가)·`edit_schedule_tool`(재앵커). `_schedule_summary` 장치현지 표시+`when_tz`. 복사본 검증(+6장치 06:00→00:00Z, when=06:00+06:00/Asia/Dhaka; target없음→시스템). | 예약 해석 정정 | — |
| **4b 완료(수동/UI)** | ✅ `api_propose_job`: schedule_time을 타겟 장치 앵커 tz로 해석+앵커 저장(기존 get_user_tz=시스템 대체). `_enrich_job_display`: 모달 datetime-local seed를 장치 앵커 tz로(편집저장 `edit_schedule_tool` 해석과 일치→왕복 무드리프트)+`display_tz`. `_serialize_job`: `schedule_time_local`(장치현지 ISO)+`anchor_tz` 추가(레거시 schedule_time 유지). scheduler.html 편집 모달에 "Device-local time · <tz>" 라벨. 복사본 검증(+6 06:00→00:00Z, seed 06:00/Asia/Dhaka, 왕복 CONSISTENT). | 예약 해석 정정 | — |
| **4b 후속** | ✅ `User.timezone` 신설(마이그레이션 `p6_07`): 개인 표시 tz. `resolve_tz(user=)`가 User.timezone→시스템. `timekit.current_user_tz()`(요청 안전, 개인표시 전용; get_user_tz=시스템/벽시계해석은 불변). 설정 UI=AccountSelf 폼+account_self_update 저장(유효 IANA만, blank/무효→None)+nav 모달 datalist. 소비=`aot-user-tz` meta(context_processor `system_timezone`도 주입) + AoTTz `viewerTz()`가 개인 tz 우선(없으면 브라우저→시스템). 복사본 검증(컬럼·resolve_tz user/system·current_user_tz 폴백·저장검증). | 개인 표시 tz | — |
| **4b 후속2 완료** | ✅ 신규작업 폼 동적 이중시계: page_scheduler가 타겟별 앵커 tz를 배열에 실음(materialized column, O(1)). `AoTTz.wallToInstant(wall,tz)` 신설(naive 벽시계를 tz 시계로 해석→절대순간, DST refine). 타겟/시각 변경 시 장치현지/내시각/UTC 실시간 표시(장치=뷰어면 내시각 생략). node 검증(Dhaka 06:00→UTC 00:00·장치06:00·Seoul09:00; NY EDT/EST DST 정확) — 서버 저장과 동일 순간. scheduler-batch.js(레거시)는 미변경. UI 브라우저 미검증(라이브 미배포). | | |
| **5** | 정리: naive `datetime.utcnow()` 퇴치, DST 보정(P2), GIS 로컬 날짜(P4), wrapper 삭제, DB 컬럼 tz-aware. | 정확도 개선 | **P2·P4** |
| **5a 완료** | ✅ P2: `epoch_of_next_time`의 pytz `.replace()` DST 버그 → `timekit.wall_to_utc`로 벽시계 재현(검증: NY EDT −04:00·Almaty +5·Seoul 정확). ✅ P4: `AbstractGisInput._device_local_now`(장치 위치 로컬 날짜)로 gis_esa·gis_nasa_gibs의 `utcnow` 타일 날짜 대체(폴백=UTC). | 정확도 개선 | **P2·P4** |
| **5b 조사·결론(sweep 안 함)** | ✅ 조사 완료 → **의도적으로 sweep/컬럼전환 안 함**. 근거: (1) aware-UTC를 naive DateTime 컬럼에 저장해도 SQLite/SQLAlchemy가 tzinfo만 벗겨 값(UTC)은 보존, `ensure_utc`가 읽기 시 복원 → **왕복 안전**(복사본 실측: `00:00+00:00`→저장 naive `00:00`→ensure_utc `00:00+00:00`). (2) SQL 필터 `schedule_time >= utc_now()`도 bind 시 tz 벗겨 naive-UTC 비교 → 안전. (3) Python aware↔naive 직접 비교 크래시 없음(grep). (4) 인프라 `datetime.now()` 94/48곳은 대부분 **의도적**(경과시간·offset계산 `utcnow()-now()`·로컬 폴백)이라 전환 시 오히려 버그. (5) 컬럼 default 47곳·측정 hot path(base_input:233)는 aware 전환 시 파손 위험·무이득. → naive-UTC 규약+`ensure_utc` 흡수는 **유효한 설계로 유지**. wrapper도 컴팻으로 유지. | 무변경(안전 확인) | **P0(해당없음)** |

---

## 11.1 표시↔편집 결합 주의 (Phase 2 조사에서 발견)

스케줄러의 `schedule_time`은 **표시이자 편집 입력 시드**다. 리스트/모달의
`<input type="datetime-local">` 값이 이 필드로 채워지고([scheduler.html:306](../../aot/aot_flask/templates/pages/ai/scheduler.html:306),
[scheduler-batch.js:150](../../aot/aot_flask/static/js/ai/scheduler-batch.js:150)의 `.slice(0,16)`),
저장 시 `wall_to_utc(..., get_user_tz())`(시스템 tz)로 재해석된다. **표시 tz만 장치 현지로
바꾸고 저장 해석을 그대로 두면 저장 시점에 9시간 밀림**(고치려던 바로 그 버그)이 재발한다.

→ 결론: 스케줄러의 `schedule_time` 표시는 저장 왕복과 분리 불가. **표시(장치현지)+편집 입력(이중시계)+
저장 해석(앵커 tz)을 Phase 4에서 end-to-end 한 번에** 처리한다. Phase 2는 저장 왕복과 무관한
읽기전용 표시(`/timeline` 이벤트)와 명백한 offset 버그만 처리했다.

## 11.2 소비(사용) 측 점검·수정 (2026-07-21)

시간을 **소비하는** 경로를 점검한 결과, 제어 로직(트리거·시퀀스·PID)은 이미 장치/시설 tz를
올바르게 쓰고 일출몰은 장치 좌표로 절대 epoch를 계산해 정확했다. 다음 실사용 갭을 수정:

- **반복(cron) 예약이 장치 앵커 tz 무시 + DST 미대응** ([ai_scheduler_service.py](../../aot/ai/services/ai_scheduler_service.py) 등록부):
  `get_user_tz()`(시스템)로 해석하고 local→고정 UTC hour로 변환해 등록하던 것을,
  **앵커 tz(anchor_tz→target 장치현지→시스템)를 APScheduler `CronTrigger(timezone=)`로 전달**하도록
  수정. 이제 "매일 06:00"이 장치 현지 06:00에 발화하고 DST를 추종한다(라이브러리 검증: Dhaka 06:00→00:00Z,
  NY 02:00 여름 06:00Z·겨울 07:00Z). 일회성(fire_utc)은 Phase 4에서 이미 처리됨.
- **`_serialize_job`의 decided_at/executed_at/created_at**을 `serialize_ts`(시스템 tz)→`iso_utc`(UTC ISO)로
  정합화(클라 렌더 규약 일치, raw-slice 소비처 없음 확인).
- **`sunriseset.SunriseSet.get_current_uct`** docstring(UTC)과 구현 불일치(`now()`→`utcnow()`) 수정.

- **노트 시각을 위치 tz로 표시**: AI 도구 `search_notes_tool`이 노트를 `to_local`(시스템 tz)로 보여주던 것을
  **노트의 위치(target_id) tz**로 표시(노트별 캐시, `date_tz` 병기). 웹 노트 API `/notes/target/<id>`에도
  `date_tz`(위치 tz) 추가(응답에 실어 프론트가 채택 가능). 조사: `datetime_time_to_utc`의 호출처(웹폼 노트·
  CSV import·리포트 범위·공지)는 **위치가 없어 시스템 tz가 맞음**(웹폼 노트는 target 미지정), CSV는 export의
  `to_local`과 왕복 일치라 유지. `create_note`는 date_time을 생성 instant로 기록(벽시계 해석 없음).
  검증: 노트 naive-UTC 00:00 → Asia/Dhaka 06:00.

미수정(후속): 웹 노트 위젯 렌더(notes-widget·AoT_map 등)는 전부 **번들**이라 `date_tz` 채택엔 소스+재빌드
필요 — 현재 브라우저(뷰어) tz 렌더는 개인 조회 문맥으로 수용 가능.
그래프/달력 축은 브라우저 tz(useUTC:false) — §12 뷰어 tz 결정과 일치.

## 12. 결정 항목

1. **기본 앵커 정책** (§6) — **확정: 장치 현지 기준.** 장치 예약 벽시계("06:00")는 기본적으로
   그 장치/도형이 있는 곳의 시계로 해석한다(작물의 태양일 기준). 개별 예약에서 사용자 시각으로
   변경 가능하고, UI는 항상 이중시계(현지/내 시각/UTC)를 표시한다. (2026-07-21 확정)
2. **`User.timezone` 도입 시점**: Phase 4 일괄 vs 조기 분리. (미확정)
3. **다중 tz 달력 축** — **확정: 뷰어 tz.** FullCalendar 축을 `timeZone: 'local'`(브라우저 로컬=뷰어 시각)로,
   이벤트는 UTC+offset(iso_utc)으로 보내 올바른 순간에 배치. 이벤트 클릭/툴팁은 장치 현지 시각+tz 표시.
   축 tz 라벨 부착. (named per-user tz 축은 FullCalendar tz 플러그인 필요 — 미로드, 후속). (2026-07-21 확정)
