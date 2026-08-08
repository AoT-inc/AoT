# 공간-장치 바인딩 — 고정 자산과 유동 자산의 분리

지도·시설(고정 자산)이 장치(유동 자산)의 uuid 를 정체성의 일부로 들고 있는
구조를 뒤집는 정본 설계 문서. 장치 삭제가 고아 도형을 남기고, 장치 교체가
도형 재작도를 요구하고, 장치를 갈면 시계열이 끊기는 문제는 전부 이 소유
방향의 역전에서 나온다 — 개별 버그가 아니라 구조다.

관련 정본: [geo-data-integrity.md](geo-data-integrity.md) (불변식 카탈로그 I1~I12,
소유권 모델 P1~P5). 이 문서의 불변식은 GB-1~ 로 번호를 매기고, DDL 이 실제로
붙는 시점에 I 카탈로그로 흡수한다. **검사가 있다고 적는 것과 검사가 도는 것은
다르다** — 각 단계의 가드는 그 단계 커밋에 실재해야 하며, 문서가 앞서가지
않는다(2026-08-07 `test_write_tools_are_gated` 교훈).

## 배경 — 왜 소유 방향이 거꾸로인가

AoT 초기에는 지도가 없었고 장치 단위가 우선이었다. GIS 가 나중에 얹히면서
공간 요소가 장치를 참조하는 게 아니라 **장치 uuid 를 자기 몸에 새기는** 형태로
자랐다. 디지털트윈을 모방했지만 트윈의 대상이 뒤바뀐 것이다 — 트윈은
농장(공간·구조·기능적 역할)의 트윈이어야 하고, 장치 시리얼넘버의 트윈이
아니다.

수명으로 보면 명백하다: 지형·시설·구역은 수십 년, 장치는 몇 년이다.
장수명 자산이 단수명 자산의 식별자에 묶이면, 단수명 쪽의 모든 수명 이벤트
(삭제·고장·교체)가 장수명 쪽을 훼손한다.

### 현재 참조 인벤토리 — 같은 사실이 6곳에

2026-08-08 로컬 개발 DB 의 `geo_shape.feature` · `geo_facility` JSON 컬럼
전체를 재귀 순회해 "uuid 모양 값을 담은 키"를 전수 수집한 결과다(추정 아님).

| 저장처 | 형태 | 로컬 실측 | 정리하는 삭제 경로 |
|--------|------|-----------|--------------------|
| `GeoShape.device_id` (+`channel_id`) | 컬럼 | 20건 (죽은 참조 3) | Input/Output/탭 삭제만 (아래 표) |
| `feature.properties.device_id` | JSON 사본 | 20건 (죽은 참조 3) | 없음 (행이 함께 지워질 때만) |
| `feature.properties.unique_id` = `device_id` 또는 `device_id::채널` | JSON, **파싱 계약** | 17건 | 없음 |
| `GeoFacility.fittings[].actuator_id` / `.input_id` (+ 짝인 `.measurement_id`) | JSON blob | 26 / 4 / 15건 (actuator 죽은 참조 16) | **없음** |
| `GeoFacility.actuators[].device_uuid` | JSON blob | 1건 | **없음** |
| `GeoFacility.sensors[]` · `weather_bindings[]` (`device_id` / `input_uuid` + `measurement_id`) | **각각 별도 컬럼** | 로컬 미사용(빈 값 1건) | **없음** |

`properties.unique_id` 는 단순 사본이 아니라 **프런트·백엔드가 공유하는 파싱
계약**이다 — 채널 0 은 장치 uuid 그대로, 그 외는 `uuid::N`
(`device_placement._entry_uid`). 이 문자열에서 장치를 되꺼내는 코드가
`geo/widget/maps.py:168`, `utils_geo.py:747`, `utils_geo.py:1311` 에 있다.
GB-5 를 세우려면 이 계약의 이전 경로를 함께 정해야 한다(아래 GB-5 주석).

`fittings[].measurement_id` 는 `kind='sensor'` fitting 에서 `input_id` 와
**쌍으로만** 의미를 갖는다(로컬 4건 모두 쌍, 전부 실존). 바인딩의 `params`
가 이 짝을 함께 옮기지 않으면 센서 연결이 끊긴다.

### 삭제 경로 실태 — 통일된 정책이 없다

| 삭제 대상 | 도형 처리 | 위치 |
|-----------|-----------|------|
| Output | `device_id` 일치 도형 전량 삭제 | `utils_output.py:656` |
| Input | 전량 삭제 | `utils_input.py:801` |
| Function/PID/Trigger/Conditional | 아무 처리 없음 | `utils_function.py` 외 3 |
| CustomController(복합장치) | 아무 처리 없음 | `utils_controller.py` |
| 진단 → 입력/출력/함수 일괄 삭제 | 아무 처리 없음 (raw `db.session.delete`) | `utils_settings.py` ×3 |
| 탭 삭제 연쇄 | Input/Output 만 삭제, 나머지 5종 무처리 | `tab_service.py:549·590` |

**정책은 6갈래지만 코드 진입점은 17곳이다** — `utils_*` 7(`output_del`
`input_del` `function_del` `controller_del` `conditional_del` `pid_del`
`trigger_del`) + `tab_service` 7(`_delete_*_entry`) + 진단 일괄 3. 이행
계획의 작업량은 6이 아니라 17 기준으로 잡아야 한다.

`GeoShape` 를 `device_id` 로 직삭제하는 지점은 **4곳**이다:
`utils_input.py:801`, `utils_output.py:656`, `tab_service.py:549`,
`tab_service.py:590`. (`check_geo_writes.py` 의 GRANDFATHERED 는 파일
기준 3개지만 호출은 4개다.)

`check_geo_integrity.py` 에는 "device_id → 실존 장치" 검사가 없어 위 죽은
참조가 전부 통과한다.

### 선행 화석 — `MapDependency`

`aot/databases/models/map_dependency.py` 에 이미 같은 발상의 테이블이 있다:
`source_id`(GeoShape.id) → `target_type`('overlay'|'sensor'|'output'|
'function') + `target_id`, `relation_type`('contains'|'linked_to').

**도달 불가능한 사문(死文)이다** — 레포 전체(테스트·스크립트 포함) import
0건, 마이그레이션 0건, `models/__init__.py` 미등록(따라서 SQLAlchemy
metadata 에 없고 `db.create_all()` 도 만들지 않는다), 문서 참조 0건, 로컬 DB
에 테이블 없음. 유래는 초기 스쿼시 커밋에 묻혀 확인 불가.

**되살릴 가치가 없다** — 담고 있던 세 축이 전부 무효다:

| 담던 것 | 현재 |
|---------|------|
| `relation_type='contains'` | I11 이 **명시적으로 금지하는 저장**. 좌표에서 완전히 파생되며 `device_membership.py` 가 정본 |
| `target_type='overlay'` (도형↔도형) | `GeoShape.parent_id` 가 담당 |
| `relation_type='linked_to'` (도형↔장치) | `geo_binding` 이 대체. MapDependency 에는 채널·역할·수명이 없어 **우리 요구의 부분집합조차 아니다** — I2 의 (지도, 장치, 채널) 세계와 맞지 않는다 |
| `source_id` = `geo_shape.id` 정수 FK | `map_overlay_id` 가 정확히 이 방식으로 썩었다(재생성이 id 를 바꾸면 참조가 끊긴다). `geo_binding` 은 양쪽 모두 `unique_id`(문자열)로만 가리킨다 |

처분은 **모델 파일 삭제**다. 이 레포는 죽은 코드에 `[P1 이후 사망]` 표시를
달고 부활 방지 테스트로 지키는 관례가 있지만(`utils_map_config.py` 4함수 ↔
`test_geo_map_ownership.py`), 그 관례는 **살아 있는 모듈 안의 함수**처럼
실수로 호출될 수 있는 대상을 위한 것이다. import 0 인 독립 파일은 실수로
쓰일 경로가 없고, 남는 위험은 개념적 혼동뿐이며 그 혼동은 이 절이 흡수한다
— 지식의 보관처로는 죽은 `.py` 보다 설계 문서가 낫다.

**단, Phase A 와 같은 커밋에 넣지 말 것.** 스키마 마이그레이션·백필과
무관한 파일 삭제를 섞으면 리뷰·롤백 단위가 흐려진다. 별도 커밋으로 처리하며,
Phase A 의 게이팅 조건이 아니다(어느 쪽으로 하든 Phase A 를 막지 않는다).

"전량 삭제"도 정답이 아니다 — 도형은 자산(측량·작도 결과)이고 장치는
소모품이다. 같이 지우면 자산이 날아가고, 남기면 고아가 된다. 어느 쪽을
택해도 틀리는 것은 질문 자체가 잘못됐기 때문이다.

## 설계 원칙

기존 원칙(무결성 문서 1~4)에 더해:

**B1 — 공간이 정본, 장치는 점유자다.** 공간 요소(도형·시설·fitting·센서
역할)는 장치 없이 완결적으로 존재한다. "온실A 좌측 측창 개폐기"는 공간 측의
영속 정체성(슬롯/역할)이고, 지금 어떤 릴레이가 그 역할을 맡는지는 별개
사실이다.

**B2 — 공간↔장치 연결은 바인딩 테이블 한 곳에만 저장한다.** 도형 컬럼도,
feature JSON 도, 시설 JSON blob 도 연결의 정본이 아니다. 파생 불가능한
진짜 정보(사람의 배정 결정)이므로 I11(좌표 파생)과 달리 저장하되, 저장처는
하나다.

**B3 — 바인딩은 끝나는 것이지 지워지는 것이 아니다.** 장치 삭제·교체는
바인딩의 `valid_to` 기록이다. 이력이 남아야 "이 슬롯을 언제 어떤 장치가
맡았나"에 답할 수 있고, 그 답이 곧 장치 교체를 관통하는 시계열 연속성이다.

**B4 — 삭제 정책은 소멸시킨다.** 장치 삭제 시 "도형을 같이 지울까 남길까"를
묻지 않는다. 바인딩이 종료되고 공간 요소는 미배정 슬롯으로 남는다. 예외는
위치 마커 하나뿐(아래).

## 아키텍처 — 3층 분리

```
[공간 계층]  site → zone → facility → bay → fitting/역할/구역   ← 정본, 장수명
                          ↑
[바인딩]     geo_binding — 유일한 접점, 이력 보존
                          ↓
[장치 계층]  CustomController(복합장치) ⊃ Output / Input          ← 교체 가능
```

관계 테이블 선례는 `DeviceMember`(참조 전용, 소유권 없음, cascade 불관여)다.
`geo_binding` 도 같은 성격이다 — 어느 쪽의 수명도 소유하지 않는다.

### 스키마

```python
class GeoBinding(CRUDMixin, db.Model):
    __tablename__ = 'geo_binding'
    id            = Integer, PK
    unique_id     = String(36), unique, default=set_uuid

    # 공간 측
    spatial_kind  = String(16), NOT NULL
        # 'shape' | 'fitting' | 'actuator' | 'sensor_role' | 'weather'
        # — 인벤토리 6곳 중 저장처가 다른 것마다 하나씩. fitting 과 actuator 는
        #   같은 시설의 다른 JSON 컬럼이며 키 이름도 다르다(합치지 말 것).
    spatial_id    = String(64), NOT NULL, index
        # shape       → GeoShape.unique_id
        # fitting     → GeoFacility.unique_id + ':' + fittings[].id  (예: 'f3ab…:Fms9tpuxf23f')
        # actuator    → GeoFacility.unique_id + ':' + actuators[].id (예: 'f3ab…:Amp9uhyz91pt')
        # sensor_role → GeoFacility.unique_id
        # weather     → GeoFacility.unique_id
        # 양쪽 다 unique_id(문자열)로만 가리킨다 — 정수 PK 참조 금지(MapDependency 교훈)
    role          = String(32), NOT NULL
        # shape: 'marker' | 'area'
        # fitting: 'actuator' | 'sensor'
        # actuator: 'actuator'
        # sensor_role: 'indoor_temp' | 'outdoor_wind' … (sensors[] 의 role 어휘 그대로)
        # weather: 'forecast_temperature' … (weather_bindings[] 의 measurement_type 어휘 그대로)

    # 장치 측
    device_kind   = String(16), NOT NULL
        # 'input' | 'output' | 'device'(CustomController) | 'function' | 'pid'
        # | 'trigger' | 'conditional'
        # — geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종. 마커는 Function·
        #   PID·Trigger 에도 붙는다(`/api/geo/device/location` → place_device).
        #   3종으로 좁히면 백필이 나머지를 조용히 버린다(로컬에 이미
        #   custom_controller 마커 1건 존재).
    device_id     = String(36), NOT NULL, index
    channel_id    = String(8),  NOT NULL, default '0'   # NULL 금지 — I2 교훈
    measurement_id = String(36), nullable
        # DeviceMeasurements.unique_id. "이 장치의 이 측정값"까지가 바인딩
        # 대상이므로 params 가 아니라 1급 컬럼이다 — GB-1 유일성이 이 값을
        # 봐야 하고(아래), 드리프트 대조도 이 값 기준이다.

    # 수명
    valid_from    = DateTime, NOT NULL
    valid_to      = DateTime, nullable      # NULL = 현재 유효
    ended_reason  = String(16), nullable    # 'replaced' | 'device_deleted' | 'unbound' | 'spatial_deleted'

    # 부가 — 역할별 나머지 파라미터 (measurement_id 는 위 컬럼)
    #   sensor_role : weight
    #   weather     : max_age_sec
    params        = JSON, nullable
```

### 슬롯 점유 수 — 단일과 다중을 구분한다

`sensors[]` 는 **같은 role 에 여러 장치를 등록해 가중평균**하도록 설계돼 있다
(모델 주석: "Multiple entries per role → weighted-average aggregation").
`weather_bindings[]` 도 마찬가지다. 따라서 "슬롯당 현재 바인딩 1개"를 전
종류에 일괄 적용하면 **정상 기능을 DB 가 거부한다.**

| spatial_kind | 점유 | 현재 바인딩 유일성 키 |
|--------------|------|------------------------|
| `shape` · `fitting` · `actuator` | 단일 — 한 창을 두 모터가 열지 않는다 | (spatial_kind, spatial_id, role, channel_id) |
| `sensor_role` · `weather` | **다중** — 집계가 목적 | (spatial_kind, spatial_id, role, device_id, channel_id, measurement_id) |

다중 쪽도 무제한은 아니다 — **같은 (장치, 채널, 측정값)의 중복 등록**은 막는다.
한 Input 의 서로 다른 측정 채널 둘을 같은 role 에 넣는 것(정상)과 같은 것을
두 번 넣는 것(오류)을 가르는 경계가 `measurement_id` 다.

fittings·actuators 항목은 이미 안정적 `id` 를 갖는다(실측: `Fms9tpuxf23f`,
`Amp9uhyz91pt` 형태). 누락된 항목은 Phase A 백필에서 부여한다.

### 바인딩 단위 — 양쪽 허용, 장치 우선 (확정)

`device_kind` 는 `output`/`input`(실물 단독 운영, 현장 다수)과
`device`(복합장치) 를 모두 허용한다. **생성 시** 대상 Output/Input 이
`parent_device_id` 를 가지면 기본 제안은 장치 단위 바인딩이고, 명시적으로
멤버 단위 바인딩도 가능하다. **해석 시** `device` 바인딩은 리졸버가 멤버
Output/Input 으로 전개한다 — 전개 기준은 소유 관계(`parent_device_id`)뿐이며
`DeviceMember` 참조 관계는 전개하지 않는다. 참조는 소유가 아니고, 참조까지
전개하면 남의 장치 구성에 끼워 넣은 항목이 이쪽 슬롯의 제어 대상이 된다.

> **`device_blueprint._linked_ids()` 를 재사용하지 말 것.** 그 함수는
> `parent_device_id` 조회 결과에 `DeviceMember` 를 `update()` 로 합쳐 한
> 집합으로 돌려준다 — 이름과 위치상 가장 먼저 손이 가지만 위 규칙을 정확히
> 위반한다. 리졸버는 `model.query.filter_by(parent_device_id=…)` 를 자체
> 수행한다. (`_device_descendants()` 도 같은 이유로 부적합 — 장치 계층
> 순회에 참조 간선을 포함한다.)

### 위치 마커의 예외

`aot_device` 점 마커는 유일하게 자산 가치가 없는 도형이다(장치를 놓으려고
찍은 점). 정책:

- **교체(리바인딩)** 시 마커 유지 — 위치는 공간의 사실이다.
- **교체 없는 삭제** 시 마커도 삭제 — 미배정 점은 의미가 없다.
- `device` 구역 폴리곤·fitting·센서 역할은 항상 존속(미배정 슬롯).

### 시계열 연속성

InfluxDB 태그는 `device_id` 그대로 둔다(과거 데이터 재작성 금지). 연속성은
조회 시점 접합이다: `history(spatial_id, role)` 이 돌려주는 (device_id,
channel, 구간) 목록으로 graph-async 가 구간별 질의를 이어 붙인다. "온실A
온도"가 장치 교체를 관통해 한 그래프가 된다. 이것이 바인딩 이력의 최대
실익이며, Phase D 의 명시적 산출물이다.

## 리졸버 계약 — `aot/aot_flask/geo/device_binding.py`

`device_membership.py`(소속)·`device_placement.py`(배치)와 대칭인 세 번째
게이트웨이. 이 모듈이 공간↔장치 연결 판정·변경의 유일한 정본이다.

```python
# 읽기
current(spatial_id, role) -> Binding | None          # 현재 바인딩
bindings_for_device(device_id, at=None) -> [Binding] # 장치의 (해당 시점) 바인딩 전부
history(spatial_id, role) -> [Binding]               # 시계열 접합용, valid_from 순
unbound_slots(map_uuid=None) -> [...]                # 미배정 슬롯 목록

# 쓰기 (트랜잭션 합류, commit=False 기본 — place_device 관례)
bind(spatial_kind, spatial_id, role, device_kind, device_id, channel_id='0')
unbind(binding_uid, reason)                          # valid_to 기록
rebind(old_device_id, new_device_id, scope=None)     # 종료+생성 원자 실행
end_all_for_device(device_id, reason)                # 장치 삭제 경로 전용
```

`check_geo_writes.py` 의 ALLOWED_PREFIXES 안(geo 패키지)이므로 소유권 검사와
정합한다. 밖의 모듈(장치 삭제 6경로·AI 도구)은 이 함수들만 부른다.

## 불변식

| ID | 불변식 | 강제 수단 | 단계 |
|----|--------|-----------|------|
| GB-1 | 현재 바인딩(`valid_to IS NULL`)은 슬롯당 1개 — 단일/다중 점유별로 키가 다르다(위 표) | 부분 유니크 인덱스 2개 | Phase A |
| GB-2 | `valid_to IS NOT NULL` 이면 `ended_reason` 존재, `valid_to >= valid_from`, `spatial_kind`·`device_kind`·`ended_reason` 은 어휘 안 | 트리거 (INSERT/UPDATE ABORT) | Phase A |
| GB-3 | 장치(Output/Input/CustomController) 삭제 → 그 장치의 현재 바인딩 전부 종료(`device_deleted`) | 트리거 (AFTER DELETE) | Phase C |
| GB-4 | GeoShape 삭제 → `spatial_kind='shape'` 현재 바인딩 종료(`spatial_deleted`); GeoFacility 삭제 → fitting/sensor_role/weather 종료 | 트리거 (I3 연쇄에 합류) | Phase C |
| GB-5 | 저장된 feature JSON 에 `properties.device_id`/`channel_id` 키 부재 (읽기 시 리졸버가 주입) | 트리거 (I6 과 동형) | Phase C |
| GB-5b | `properties.unique_id` 는 도형 자신의 `GeoShape.unique_id` — 장치 uuid/`uuid::채널` 을 담지 않음 | 트리거 + 프런트 계약 이전 | Phase C 이후 (별도 게이팅) |
| GB-6 | `GeoShape.device_id`/`channel_id` 컬럼, fittings/sensors 의 장치 참조 키는 사망 — 신규 읽기/쓰기 금지 | `check_geo_writes.py` 확장 + CI | Phase C |
| GB-7 | 바인딩 쓰기는 `device_binding.py` 게이트웨이 경유만 | `check_geo_writes.py` (AST) | Phase A부터 |

**GB-5b 를 GB-5 에서 분리한 이유**: `properties.unique_id` 는 사본이 아니라
프런트가 엔트리를 식별하는 계약이다(채널 0 = 장치 uuid, 그 외 `uuid::N`).
서버가 이 키를 조용히 비우면 지도·위젯의 엔트리 식별이 통째로 깨진다.
프런트가 도형 자신의 `unique_id` + 별도 필드(리졸버 주입)로 옮겨간 것을
확인한 뒤에만 켠다. Phase C 에 묶지 말 것 — 묶으면 Phase C 전체가 프런트
작업에 인질로 잡힌다.

트리거를 택하는 이유는 무결성 문서와 동일하다 — 원시 SQL·bulk delete·AI
대량생성 어떤 경로든 통과하지 못하고, `PRAGMA foreign_keys` 전역 스위치의
부작용(무관한 위반 폭발)을 피한다. 각 불변식은
`test_geo_invariants_attack.py` 에 공격 테스트를 추가해 원시 SQL 위반이
DB 에서 거부되는 것으로 완성 판정한다(주장이 아니라 공격으로).

## 이행 단계

각 단계는 독립 배포 가능하고, 다음 단계의 게이팅 조건이 충족돼야 진행한다.
마이그레이션 추가 시 `ALEMBIC_VERSION` 상수를 **같은 커밋에서** 올린다
(`check_alembic_head.py --staged` 가 pre-commit 에서 강제).

### Phase A — 테이블 + 백필 + 검출 (비파괴) ✅ 구현 완료 (2026-08-08)

산출물: `aot/databases/models/geo_binding.py` ·
`alembic_db/alembic/versions/p6_27_geo_binding_20260808.py` ·
`geo_integrity_ddl.BINDING_STATEMENTS`/`apply_binding()` ·
`aot/scripts/backfill_geo_binding.py` · `check_geo_integrity` 3검사 ·
`check_geo_writes` GB-7 · `test_geo_invariants_attack.TestBindingAttacks` 15종.

로컬 실측(2026-08-08): 백필 대상 32건(shape/marker 17 · fitting/actuator 10 ·
fitting/sensor 4 · actuator/actuator 1), device_kind 분포 input 19 · output 12 ·
**device 1**(어휘를 3종으로 좁혔다면 이 1건이 조용히 빠졌다), 죽은 참조
19건(도형 3 + fitting 16)은 바인딩 미생성. DB 사본에 실제 INSERT 해
**GB 불변식의 거부 0건**을 확인했다 — 불변식이 실데이터와 충돌하지 않는다.

공격 테스트는 음성 대조로 검증했다: `apply_binding()` 을 끄면 차단 테스트
10종이 전부 실패하고, 나머지 5종(정상 동작 허용 = 과차단 회귀 방지)은
양쪽에서 통과한다. 통과 자체가 아니라 **가드가 실제로 무는 것**을 확인한
것이다.


- `geo_binding` 테이블 마이그레이션. GB-1·GB-2 인덱스/제약 즉시.
  마이그레이션 추가 시 `aot/config/__init__.py` 의 `ALEMBIC_VERSION`
  (현재 `p6_26_mcp_confirmation_result_20260807`)을 같은 커밋에서 올린다.
- 백필 **5원(源)** — 인벤토리 6곳 중 `properties.device_id` 는 컬럼의 사본이라
  제외:
  ① `GeoShape.device_id`+`channel_id` (마커 `aot_device`→role='marker',
  폴리곤 `device`→'area')
  ② `fittings[].actuator_id` (kind: window·curtain 등)
  ③ `fittings[].input_id` + 짝인 `measurement_id`→`params` (kind='sensor')
  ④ `actuators[].device_uuid`
  ⑤ `sensors[]` · `weather_bindings[]` (별도 컬럼 2개)
- **`valid_from` = 백필 실행 시각** (확정 — 과거 교체사가 존재하지 않으므로
  소급하지 않는다). `device_kind` 는 uuid 가 실존하는 테이블로 판별하고,
  `parent_device_id` 가 있어도 백필은 실물 단위 그대로 기록한다(장치 우선은
  신규 생성 규칙이지 과거 재해석이 아니다).
- 존재하지 않는 장치를 가리키는 참조(로컬 실측: 도형 3건 + fitting
  `actuator_id` 16건)는 바인딩을 만들지 않고 보고서로 남긴다.
- **검증 공백 고지**: 로컬 개발 DB 에는 살아 있는 `device`(구역) 폴리곤이
  0건이다 — `device_id` 보유 도형은 `aot_device` 마커 17건(전부 채널 '0')과
  죽은 폴리곤 3건뿐. 따라서 백필 ①의 role='area' 분기와 채널 비-0 처리는
  로컬에서 실행 검증할 수 없다. 운영 서버 DB 사본으로 dry-run 하고 그
  결과를 근거로 판정할 것(운영 서버 직접 실행 금지 — 읽기 전용 진단만).
- `check_geo_integrity.py` 에 3검사 추가: `orphan-device-shape`(도형이 실존하지
  않는 장치를 가리킴), `dangling-fitting`(시설 JSON 이 실존하지 않는 장치를
  가리킴), `binding-drift`(레거시 저장처 ↔ 바인딩 불일치 — Phase C 전까지
  이중 저장 기간의 감시자).
- `check_geo_writes.py` 에 GB-7(GeoBinding 쓰기 소유권) 추가.
- 기존 읽기/쓰기 경로는 그대로 — 이 단계에서 앱 동작 변화는 없다.

### Phase B-1 — 리졸버 + 첫 소비처 ✅ 구현 완료 (2026-08-08)

`aot/aot_flask/geo/device_binding.py` 신설. 조회(`current`·`current_one`·
`bindings_for_device`·`history`·`unbound_slots`) · 해석(`device_for_shape`·
`devices_for_shapes`·`expand_device`) · 투영(`resolve_facility_payload`·
`build_facility_index`).

소비처는 **두 이음매만** 걸었다. 하위 소비처(`facility_integration` ·
`irrigation_nozzles` · `facility_wind` · `facility_calc` · 3D 위젯)는 JSON 을
인자로 받는 순수 함수라, 각각을 고치면 같은 규칙을 다섯 벌 구현하게 된다:

| 이음매 | 위치 | 덮는 범위 |
|--------|------|-----------|
| 시설 JSON 의 유일한 출구 | `facility_io.FacilityManager._to_dict` | fittings·actuators 의 장치 참조 전부 |
| 지도 도형의 device_id 주입 | `geo_overlays.get_overlays` | 마커·구역 도형 |

둘 다 핫패스라 일괄 조회다. 시설 목록은 `build_facility_index()` 로
**쿼리 11회 → 1회**(실측, 시설 11개). 도형은 기존 N+1 회피 지점 옆에서
`devices_for_shapes()` 한 번.

폴백은 종류별 1회만 로그한다 — 핫패스에서 항목마다 찍으면 로그가 쓸모없어
지고, 건수는 `binding-drift` 가 정확히 센다. **이 로그가 0 이 되는 것이
Phase C 의 게이팅 조건이다.**

**죽은 참조는 폴백으로 세지 않는다.** 백필이 실존하지 않는 장치의 참조에
바인딩을 만들지 않으므로(고아를 정본으로 승격시키지 않는 정책), 죽은 참조는
"바인딩 없음 + 레거시 값 있음"이 되어 폴백과 모양이 같다. 그대로 두면 백필을
다 끝내도 경고가 영원히 켜진 채 남고, 게이팅 신호로 쓸 수 없게 된다 — 켜져
있는 게 정상인 경고는 아무도 보지 않는다(CI 13연속 실패와 같은 실패 모드).
그래서 로그를 남기기 직전에 참조 대상이 실존하는지 한 번 확인한다. 죽은
참조는 `orphan-device-shape`/`dangling-fitting` 이 담당한다.
2026-08-08 로컬 백필 직후 실제로 이 증상이 나와(죽은 참조 19건이 경고를
계속 띄웠다) 그 자리에서 고쳤다.

리졸버는 **ORM 이 들고 있는 JSON 을 고치지 않는다**(copy-on-write). 고치면
같은 세션의 뒤이은 독자가 저장값 대신 해석값을 보고, 특히
`check_geo_integrity` 의 dangling-fitting 이 죽은 참조를 살아 있는 것으로
본다. `test_device_binding_resolver.py` 가 이를 지킨다.

> 구현 중 이 지점을 **DB 되써넣기로 오진**했다가 통제 실험으로 바로잡았다.
> `db.Column(JSON)` 은 Mutable 래퍼가 없어 제자리 변경이 DB 까지 가지
> 않는다. 오진의 원인은 검증 코드 쪽이었다 — 얕은 복사 `list(f.fittings)` 로
> 내부 dict 을 공유한 채 고치면 ORM 이 '변경 없음'으로 보아 오염이 저장되지
> 않는데, 그 결과를 "폴백이 옛 값을 안 돌려준다"로 읽었다. **JSON 컬럼을
> 테스트에서 오염시킬 때는 반드시 깊은 복사로 할 것.**

### Phase B — 읽기 전환 (폴백 유지)

- `device_binding.py` 리졸버 신설. 소비처를 순차 전환:
  `collect_devices`/지도 위젯, facility runtime(`facility_sensors.py`,
  `irrigation_nozzles.py`), AI 도구(`get_sensor_detail` 의
  GeoShape→Input 해석 등), `sensor-label.js` 로 가는 API 응답.
- `properties.device_id` 는 저장값 대신 읽기 시 리졸버 주입으로 전환
  (aot_type 의 S4 정규화와 동형 — 프런트 계약은 불변).
- 레거시 컬럼은 폴백으로 읽되, 폴백이 실제로 쓰인 경우 로그를 남긴다
  (침묵 폴백은 이 도메인의 고질병).
- 게이팅: `binding-drift` 0건이 며칠 유지될 것.

### Phase B-2 — geo/design 장치 추가·배치 UI (별도 세션)

**Phase C 보다 먼저 온다.** UI 를 `device_binding` 게이트웨이 위에 지으면 쓰기
전환이 UI 개발에 흡수된다 — 반대 순서면 아직 없는 UI 를 위해 레거시 경로를
정리하는 셈이라 두 번 일한다. 또 미배정 슬롯 화면이 생기기 전에 Phase C 의
처분 정책을 바꾸면 장치 없는 폴리곤을 손댈 방법이 없어 지금보다 나빠진다.

인계 계약서: **[geo-device-placement-ui-contract.md](geo-device-placement-ui-contract.md)**
(쓰기 게이트웨이 `bind`/`unbind`/`rebind` 시그니처, REST, 금지 사항 6종,
불변식이 UI 에 뜻하는 것, 완료 판정).

### Phase C — 쓰기 전환 + 사망 선고

- 쓰기 경로 전환: `place_device`/`unplace_device` 가 바인딩 기록,
  `save_overlays` 의 `device_id` 각인 제거, facility 저장이 fitting 의
  장치 키 대신 바인딩 기록.
- 장치 삭제 **17경로**(utils 7 + tab_service 7 + 진단 일괄 3)가 전부
  `end_all_for_device()` 경유로 통일. 지금 도형을 건드리는 4곳만 고치면
  나머지 13곳이 조용히 남는다 — 그 13곳이야말로 지금 고아를 만드는 쪽이다.
  `GeoShape.query.filter(device_id==…).delete()` 직삭제 **4곳**(`utils_input`
  :801, `utils_output`:656, `tab_service`:549·590) 제거 —
  `check_geo_writes.py` 의 GRANDFATHERED 3파일을 이 시점에 비운다(원래
  목표가 게이트웨이 이관이었다).
  마커 예외 정책(교체 없는 삭제 시 마커 삭제)은 게이트웨이 안에서 처리.
- GB-3~GB-6 트리거·검사 활성화. `GeoShape.device_id` 는 `map_overlay_id` 와
  같은 사망 컬럼 절차(신규 참조 금지 → 후속 마이그레이션에서 제거).
- 게이팅: Phase B 폴백 로그 0건, 공격 테스트 전부 통과.

### Phase D — 교체 UX + AI + 시계열 접합

- **"장치 교체" 플로우**: 접속정보(DevEUI·주소)만 갈아끼우는 경로를 1안으로
  제시(도형·이력·함수 연결 전부 무변 — 사실 고장 교체의 정답), 새 장치로의
  리바인딩을 2안으로. 지금 사용자가 "새로 만들고 옛것 삭제"로 가는 것은 이
  경로가 UI에 없기 때문이다.
- 미배정 슬롯 뷰(지도·시설 페이지) — 삭제로 남은 슬롯이 보여야 재배정된다.
- AI 도구: `rebind_device`·`list_unbound_slots`. `rebind_device` 는
  `mutating=True` + 승인 필수 — **`config_only` 면제 절대 금지**(물리 제어
  대상이 바뀌는 결정이다). `test_tool_registry_ssot.py` 스냅샷을 같은
  커밋에서 갱신.
- graph-async 에 `history()` 기반 구간 접합 — 역할 기준 연속 그래프.

## 확정된 결정

| 결정 | 내용 |
|------|------|
| 바인딩 단위 | Output/Input/복합장치 양쪽 허용, 생성 시 복합장치가 있으면 장치 우선 |
| 이력 소급 | 없음 — 백필 `valid_from` = 백필 시점 |
| 문서 우선 | 이 문서가 구현에 선행하며, 각 단계 가드는 해당 단계 커밋에 실재해야 함 |

## 미결 — 구현 전 결정 필요

1. **채널 축소 교체**: 8채널 → 4채널 장치로 리바인딩할 때 5~8번 채널 바인딩
   처리 (거부 / 채널 재매핑 UI / 미배정 전환). 초안: 매핑 불가 채널은 미배정
   전환 + 경고.
2. **마커 충돌**: 리바인딩 대상 장치가 같은 지도에 이미 마커를 가진 경우.
   초안: 거부(사람이 먼저 기존 마커를 정리) — I2 유일성과 정합.
3. **이름 동기화**: `sync_geo_device_name`(`utils_general.py:44`)이 도형 이름을
   장치 이름으로 덮어쓴다. 리바인딩 후 새 장치 이름으로 갱신할지, 사람이 지은
   슬롯 이름을 보존할지. 초안: 슬롯 이름 보존(공간이 정본이라는 B1 의 귀결)
   — 단, 마커('marker' role)는 장치 이름 추종.
4. **Phase A 마이그레이션 배포 시점**: 운영 3서버 토폴로지에서 백필 보고서
   확인 절차(업그레이드 전후 `check_geo_integrity` 실행 관례에 합류).
`MapDependency` 처분은 미결이 아니다 — 「선행 화석」 절에서 결론(파일 삭제,
별도 커밋)까지 정리했고 어느 단계의 게이팅 조건도 아니다.
