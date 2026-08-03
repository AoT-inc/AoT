# 지도 데이터 무결성 — 불변식 카탈로그와 강제 계층

2026-08-03 지도 데이터 오염 사고(복제 결함 → 도형 이중화 → 시설·zone 연결 단절)의
재발을 **구조적으로** 차단하기 위한 정본 문서. 전수조사(쓰기 48곳 · 읽기 90+곳 ·
링크/복제 12경로 · 프런트 저장 13경로)에서 오염원 24건이 확인됐고, 결론은
"개별 버그가 아니라 구조"였다.

## 설계 원칙

1. **잘못된 상태를 표현 불가능하게 만든다.** 검사해서 거부하는 방어(앱 계층 가드)는
   다음 코드 경로가 우회하면 끝이다. 핵심 불변식은 **DB 계층**(트리거·유니크 인덱스)
   에 둔다 — ORM·원시 SQL·alembic·AI 대량생성·복제, 어떤 경로든 통과하지 못한다.
2. **같은 사실은 한 곳에만 저장한다.** 도형의 종류가 5개 필드(`type`,
   `properties.aot_type`, `level_id`, `category`, `sub_type`)에 중복 저장된 것이
   드리프트의 뿌리다. 정본은 `GeoShape.type` 컬럼 하나. 나머지는 읽기 시 파생.
3. **파생 가능한 링크는 저장하지 않는다.** `map_overlay_id`(장치→zone 소속)는 마커
   좌표에서 완전히 유도된다. 저장하지 않으면 복제·대량생성·재생성이 오염시킬 수 없다.
4. **완성 판정은 주장이 아니라 공격 테스트로 한다.** 각 불변식마다 원시 SQL로 위반을
   시도하는 테스트가 있고, DB가 거부해야 통과한다.
   (`aot/tests/geo/test_geo_invariants_attack.py`)

## 불변식 카탈로그

| ID | 불변식 | 강제 수단 | 단계 |
|----|--------|-----------|------|
| I1 | `geo_shape.type` ∈ 화이트리스트 | 트리거 (INSERT/UPDATE ABORT) | Tier-1 |
| I2 | 장치 위치 마커는 (지도, 장치, 채널)당 정확히 1개 | 부분 유니크 인덱스, `COALESCE(channel_id,'0')` 식 인덱스로 NULL/'0' 비대칭 봉쇄 | Tier-1 |
| I3 | 도형 삭제 시 그 도형에 매달린 GeoFacility·Setpoint·bay 가 함께 삭제 | 트리거 (AFTER DELETE 연쇄) — 삭제 12경로 전부 커버 | Tier-1 |
| I4 | 도형 삭제 시 그 도형을 가리키던 7개 모델의 `map_overlay_id` 는 NULL | 트리거 (ON DELETE SET NULL 에뮬레이션) | Tier-1 |
| I5 | 지도 삭제 시 소속 도형·시설 삭제 + 7개 모델의 `map_config_id` NULL | 트리거 | Tier-1 |
| I6 | 저장된 feature JSON 에 `properties.aot_type` 키가 존재하지 않음 (읽기 시 서버가 주입) | 트리거 (`json_extract` 검사) | Tier-2 |
| I7 | `type` 은 생성 후 불변 (종류 변경 = 삭제 후 생성) | 트리거 (UPDATE OF type ABORT) | Tier-2 |
| I8 | `geo_shape.geo_id` 는 실존하는 `geo_map` 을 가리킴 (유령 지도 금지) | 트리거 | Tier-2 |
| I9 | 삭제는 명시 목록으로만 — "페이로드 누락 = 삭제" 프로토콜 폐지 | 앱 계층 (저장 프로토콜 교정) + CI | S3 |
| I10 | `clone_model` 은 교차참조 컬럼(map_overlay_id·map_config_id·geo_id)을 암묵 복사하지 않음 | 앱 계층 + 단위 테스트 | S3 |
| I11 | 소속(장치↔zone)은 저장하지 않고 마커 좌표에서 파생 | 컬럼 미사용 + `device_membership` 단일 리졸버 | S3 |
| I12 | 지도 데이터 쓰기는 geo 패키지 안에서만 — 밖은 게이트웨이 경유 | `check_geo_writes.py` (AST) + pre-commit + CI | S5 |

**Tier-1** 은 현재 데이터·현재 앱 코드와 즉시 호환된다. 단 I2 인덱스 생성 전
S2 마이그레이션에서 두 가지 사전 정리가 필수다: ① `aot_device` 마커의
`channel_id NULL → '0'` 정규화 — 장치위치 API 는 `'0'` 으로 조회하므로 NULL
레거시 행을 못 찾아 INSERT 를 시도하고, 인덱스가 이를 거부하면 위치 저장이
막힌다. ② 기존 중복 마커 정리(참조 확인 후 — 검사기 duplicate 절차 준수).
**Tier-2** 는 앱 코드 수정(저장 시 aot_type 제거, 라벨 되먹임 절단)이 선행돼야
켤 수 있다 — 그 전에 켜면 정상 기능이 막힌다.

## 트리거를 택한 이유 (FK 재구축 대신)

- SQLite 에서 기존 테이블에 FK/CHECK 를 추가하려면 테이블 재구축(batch rebuild)이
  필요하다. 운영 3서버에서 위험이 크다.
- `PRAGMA foreign_keys=ON` 은 전역 스위치라, geo 와 무관한 기존 위반
  (widget→tab 유령 48~51건/서버)까지 한꺼번에 터진다.
- 트리거는 `CREATE TRIGGER` 한 번으로 붙고, **geo 불변식만** 선별 강제하며,
  원시 SQL·bulk delete·alembic 까지 전부 잡는다. 우회 수단이 없다.

트리거 본문은 재귀를 피해 평탄화돼 있다(`recursive_triggers` OFF 기본값 하에서
동작). 도형 삭제 트리거가 bay 를 지울 때 bay 의 삭제 트리거는 재발화하지 않지만,
bay 는 시설·하위를 갖지 않으므로 안전하다.

## 잔여 위험 (구조로 소멸 불가 — 탐지 계층 담당)

| 위험 | 이유 | 대책 |
|------|------|------|
| 위젯 `custom_options` 내 `map_uuid`/`device_ids` | JSON 내장 참조 — DB 가 볼 수 없음 | `check_geo_integrity.py` 에 JSON 참조 검사 추가 |
| `equipment_collection` 번들 내부 피처 | DB 행이 없음 | 동일 |
| 좌표 자체가 틀린 마커 | 무결성이 아니라 입력 오류 | 사용자 확인 영역 |

## 단계별 로드맵

```
S1 ✅ 본 문서 + DDL 모듈 + 공격 테스트 16종                   (ffb3930)
S2 ✅ 마커 중복·dangling·채널 사전 정리 → Tier-1 3서버 적용    (p6_22, fa47507)
S3 ✅ map_overlay_id 파생 전환(I11) + upsert 전용(I9) + clone 거부목록(I10)  (dc9032f)
S4 ✅ 저장 시 aot_type 제거 + 되먹임 고리 절단 → Tier-2 적용    (p6_23, d2c4390)
S5 ✅ 단일 배치 게이트웨이 + 소유권 검사(I12) + pre-commit/CI
```

## 남은 일 (구조 아님 — 운영·정리)

- `map_overlay_id` 컬럼 드롭 마이그레이션 — 파생 전환이 운영에서 안정화된 뒤.
  지금은 아무도 읽지 않고 아무도 쓰지 않는 사망 컬럼이다.
- `check_geo_writes.py` 의 `GRANDFATHERED` 3건(장치 삭제 시 자기 마커 정리)을
  `unplace_device` 로 이관 — 예외 목록을 0 으로.
- 유령 지도 도형 처분(phantom-map 보고 대상) — 위젯 참조 확인 후 사람이 판단.
- 미사용 `Copy of` 지도 정리, 잔여 duplicate/orphan-label — 참조 확인 후 수동.

## 새 코드를 쓸 때

지도 데이터를 건드려야 한다면 geo 패키지의 문을 쓴다:

| 하려는 일 | 쓸 것 |
|---|---|
| 장치를 지도에 배치/이동/해제 | `geo.device_placement.place_device` / `unplace_device` |
| 도형 하나 삭제 | `geo.device_placement.delete_shape` (연쇄는 트리거가 처리) |
| 장치가 어느 zone 인지 | `geo.device_membership` (저장 컬럼 조회 금지) |
| 도형 저장 | `geo.geo_overlays.GeoOverlayManager` |

`GeoShape(...)` 를 geo 패키지 밖에서 직접 부르면 pre-commit 과 CI 가 거부한다.

관련: `aot/scripts/check_geo_integrity.py`(탐지), `p6_21`(기존 오염 데이터 복구),
CLAUDE.md "지도 데이터 무결성 검사" 절.
