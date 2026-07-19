# AoT_timer ↔ AoT_on_off_counter 통합 계획

작성일: 2026-06-05 · 방향: **AoT_on_off_counter 를 AoT_timer 로 통합** + 예약 시작 기능 추가

---

## 1. 현황 분석

| 항목 | AoT_timer | AoT_on_off_counter |
|------|-----------|--------------------|
| 동작 | 단일 ON/OFF, 지속시간(hh:mm:ss), `0`=무한(정지까지) | 주기 ON/OFF(run/rest × cycles) |
| 제어 모델 | **클라이언트 구동** (`/output_mod` → 데몬 output_on(duration) 자동 off) | **서버 워커 스레드**(`_counter_cycle_worker`) — 브라우저 닫혀도 진행, 상태 파일 저장 |
| 시간 입력 | hh:mm:ss 숫자칸 3개 | 공용 드럼휠(`components/aot-time-wheel`) |
| 시간 표시 | 경과시간(Influx `output_started_at` 동기) | 전체시간 + 단계 카운트다운 |
| 세션 복원 | last-session 파일 | 상태/프리셋 파일(`/tmp/aot_timer_sessions`) |
| 타임존 | `tz_offset` 옵션(도시 목록) | (제거됨 — 장치 위치 기준 방침) |
| 엔드포인트 | `aot_timer_*` (6) | 무접두 `output_*`/`output_cycle_*` (9) |

**관계:** Counter ⊇ Timer. 타이머 = `run=duration, rest=0, cycles=1` 의 특수형. 단 타이머의 **무한 실행(`0`)** 은 카운터 워커에 없음.

---

## 2. 통합 방향 (→ AoT_timer 단일 위젯)

`AoT_timer` 를 통합 위젯으로. **동작 모드 3종:**
- **simple-once**: 지속시간 1회 실행 후 off.
- **simple-hold**: `0` → 정지까지 무한 ON.
- **cycle**: run/rest × cycles 주기 실행.

**제어 모델: 카운터의 서버 워커 채택** (견고성 — 새로고침/브라우저 종료에도 진행 유지). 단순 모드는 워커의 `cycles=1, rest=0` 경로로 표현, 무한 모드는 워커가 `output_on(0)` 후 stop 까지 대기.

---

## 3. 신규 기능: 예약 시작 (hh:mm)

- custom_option **`start_at`** (type=text, hh:mm, **기본값 `00:00`**).
- **`00:00` → 즉시 실행.** 그 외 → **다음 해당 벽시계 시각까지 대기 후 시작.**
- 타임존: **Output 장치의 `timezone`**(IANA, 좌표 기반 — `output.py:36`) 사용, 없으면 **`Misc.timezone`**(전역, `misc.py:78`) fallback. → 제거된 `tz_offset` 옵션 불필요.
- 구현 지점: `_counter_cycle_worker` 진입부에 **cancellable wait**(`_sleep_with_cancel`) 삽입. 목표 epoch = 장치 타임존 기준 오늘/내일의 hh:mm.
- 상태 확장: `phase='scheduled'`, `scheduled_until_ms` → UI에 "예약: hh:mm 까지 대기" 표시. 정지로 취소 가능.
- `output_cycle_start` payload + 검증에 `start_at`(`00:00`~`23:59`) 추가.

---

## 4. custom_options 병합 (중복 제거)

**공통 1벌 유지:** output, refresh_seconds, enable_status, status_font_em, enable_timestamp, widget_name_font_em, enable_output_controls, font_em_time_input.

**추가/정리:**
- `operation_mode` (select: simple / cycle) — 신규.
- `default_run_seconds`, `default_rest_seconds`, `default_cycles` — 카운터에서 이관.
- `start_at` — 신규(§3).
- `tz_offset` — **제거**(장치 위치 기반 자동 타임존으로 대체). 타이머의 기존 옵션도 deprecate.

---

## 5. 엔드포인트 병합 / 네이밍

`aot_timer_*` 접두로 통일(타 위젯의 무접두 `output_*` 충돌 회피, 직전 수정한 "전체 등록" 로직과 정합).

- **유지:** `aot_timer_output_started_at(_public)`, `_last_duration(_public)`, `_last_session_public/set`
- **추가(카운터→타이머):** `aot_timer_cycle_status_public`, `_cycle_start`, `_cycle_stop`, `_cycle_presets`
- **제거:** 카운터의 무접두 `output_*`/`output_cycle_*` (위젯 자체가 마이그레이션으로 사라짐).

---

## 6. JS / HTML 통합

- **공용 드럼휠 모듈 재사용** — 타이머 hh:mm:ss 입력도 휠로 통일(숫자칸 3개 폐기).
- **모드별 입력 UI 토글:** cycle → run/rest/cycles 행; simple → 단일 지속시간 행. 공통으로 **예약(hh:mm) 행** 추가.
- **첫 행 레이아웃**(직전 정리분 채택): `[N/All N 상태] · [전체 시간] · [토글]`. simple 모드는 N/All 숨김. 전역 `.prt-text-inline`·`.col-aot-2(60px)` 공용 스타일 유지.
- 상태 렌더 통합: 전체시간 + 단계 카운트다운 + `scheduled` 표시.

---

## 7. 상태 모델 확장

`_counter_state_default` 에 `mode`, `start_at`, `scheduled_until_ms` 추가. 파일 저장 포맷 하위호환(키 추가만). 세션 키는 `device::channel` 동일 → 기존 데이터 호환.

---

## 8. 마이그레이션 (Alembic — `ALEMBIC_VERSION` 체계, `config/__init__.py:20`)

- 신규 revision: `graph_type='AoT_on_off_counter'` Widget 행 → `'AoT_timer'` 변환 + custom_options 매핑(`operation_mode='cycle'`, run/rest/cycles 이전, output 유지).
- `AoT_on_off_counter.py` 위젯 정의: **deprecated shim**(1 릴리스 유예, 생성 목록에서 숨김) 또는 제거.
- `/tmp/aot_timer_sessions` 의 `*__counter.json`/`*__presets.json` 은 키 동일 → 그대로 재사용.

---

## 9. 구현 단계 (승인 후)

1. AoT_timer: `operation_mode` + 주기 옵션 + `start_at` 옵션 추가.
2. 서버: 카운터 워커/엔드포인트를 `aot_timer_*` 로 이관, **예약 대기** + **무한 모드** 로직 추가.
3. JS: 드럼휠 통합, 모드별 UI, 상태 렌더 통합.
4. Alembic 마이그레이션 + 카운터 위젯 deprecate.
5. 위젯 HTML 재생성, 엔드포인트 등록 확인(전체 등록 로직).
6. 검증: simple-once / simple-hold / cycle / 예약 4경로 + 새로고침 지속성 + `check_static_refs.py`.

---

## 10. 확정된 결정 (2026-06-05)

1. **무한 실행(`0`)** → **서버 워커로 통일.** 모든 모드를 서버 워커 스레드로 일관 처리(무한 = `output_on(0)` 후 stop 까지 대기).
2. **예약 "다음 발생"** → **오늘 hh:mm 이 이미 지났으면 내일** 그 시각.
3. **마이그레이션** → **즉시 변환(Alembic).** 머지 시 `graph_type='AoT_on_off_counter'` → `'AoT_timer'` 변환 + 옵션 매핑, 카운터 위젯 정의 제거.
4. **`tz_offset`** → 제거. 예약 타임존은 Output `timezone`(좌표 기반) → `Misc.timezone` fallback.

## 11. 구현 진행 로그

- [x] (1) AoT_timer 옵션: operation_mode + 주기 옵션 + start_at, tz_offset 제거 — 완료/검증(parse OK)
- [x] (2) 서버: 통합 워커(무한/예약 포함) + aot_timer_cycle_* 엔드포인트 — 완료/검증
      (worker 포팅 + scheduled wait + infinite hold, 엔드포인트 4종 등록,
       validate/schedule 단위테스트 통과, generate_widget_html OK)
- [x] (3) JS/HTML: 드럼휠 통합, 모드별 UI, 상태 렌더 — 완료/검증
      (카운터 UI 이식[aot_tm_*/aot_timer_* 엔드포인트], operation_mode 기반 입력 토글,
       start_at 행[wheel hm 모드], generate OK, JS node-check OK, 구 타이머 JS 잔존 0)
- [~] (4) Alembic 마이그레이션 작성 + 로컬 dry-run — 완료/검증
      (p5_14_merge_counter_into_timer: graph_type 변환 + operation_mode/start_at +
       tz_offset 제거 + _migrated_from 마커, ALEMBIC_VERSION 범프, 단일 head.
       로컬 aot.db 복사본 dry-run: 2→AoT_timer(cycle) 변환, 네이티브 타이머 무변경,
       downgrade 정확 복원 확인.)
      남은 것: AoT_on_off_counter.py 제거(인스턴스는 마이그레이션으로 전환되므로
      제거 안 해도 무해 — 정리 단계에서 수행)
- [x] (5) 카운터 위젯 정의 제거 + 엔드포인트 등록 확인 + 4모드 검증 — 완료/검증
      (AoT_on_off_counter.py + 생성 템플릿 7종 제거. parse: 카운터 없음/타이머 있음,
       aot_timer_cycle_* 등록·구 output_cycle_* 미등록 확인, check_static_refs 0 missing,
       워커 상태머신 4모드[무한/주기/예약취소/예약실행] 기능 테스트 통과.)

## 통합 완료 — 후속(배포 시)
- 배포 후 app 시작 시 Alembic p5_14 자동 실행 → 기존 카운터 위젯이 AoT_timer(cycle)로 전환.
- 브라우저 동작 검증(4모드 UI)은 로컬/배포 서버 가동 후 수행.
