# geo/design 장치 추가·배치 UI — 인계 계약서

별도 세션에서 진행할 작업의 계약. **이 문서 하나만 읽고 착수할 수 있도록** 쓴다.
배경 설계는 [geo-device-binding.md](geo-device-binding.md), 지도 데이터 불변식은
[geo-data-integrity.md](geo-data-integrity.md).

작성 시점(2026-08-08)에 Phase A(바인딩 테이블·불변식·백필·검사)와 Phase B-1
(읽기 리졸버 + 소비처 2곳)이 완료돼 있다. 이 세션은 **쓰기 쪽 첫 소비자**다.

> **✅ 구현 완료 (2026-08-08).** 아래 계약대로 구현했고, 계약이 정하지 않아
> 이 세션이 결정한 것은 「9. 구현 결과와 계약에서 벗어난 판단」에 전부 적었다.
> 남긴 것도 거기 있다 — 특히 **도형 삭제 시 바인딩 종료(GB-4)는 하지 않았다.**

---

## 1. 무엇을 만드는가

| # | 기능 | 현재 상태 |
|---|------|-----------|
| A | ~~지도에서 **장치를 새로 만들기**~~ **철회** → 복합장치(Device) **배치** | 입력·출력·함수만 배치 가능, 복합장치는 불가 |
| B | 그린 **도형(구역)에 장치를 매기** | **없음** — `role='area'` 바인딩을 사람이 만들 수단이 아예 없다 |
| C | **미배정 슬롯** 보기·재배정 | 없음 (개념 자체가 새것) |

**이미 있는 것**: 마커 배치(`placeDeviceOnMap` → `POST /api/geo/device/location`
→ `place_device`). 수동 배치 시 자동 저장된다. 없는 것은 위 3가지다.

## 2. 무엇을 만들지 않는가 (범위 밖)

- **장치 삭제 시 처분 정책 변경**(구역 폴리곤을 미배정 슬롯으로 남기기)과
  **삭제 17경로 통일** — Phase C 다. 이 세션에서 하면 안 된다: 미배정 슬롯을
  보고 재배정할 UI 가 생기기 **전에** 처분만 바꾸면, 장치 없는 폴리곤이 지도에
  남는데 손댈 방법이 없어 지금보다 나빠진다.
- 레거시 저장처(`GeoShape.device_id`, 시설 JSON 키) 제거 — Phase C.
- AI 도구(`rebind_device` 등) — Phase D.

---

## 3. 먼저 만들어야 하는 것 — 쓰기 게이트웨이

`aot/aot_flask/geo/device_binding.py` 에는 지금 **읽기만** 있다. UI 가 쓰려면
아래 함수를 같은 모듈에 추가한다. 시그니처와 의미론을 여기서 고정한다 —
UI 세션이 임의로 정하면 Phase C 가 다시 뜯는다.

```python
def bind(spatial_kind, spatial_id, role, device_kind, device_id,
         channel_id='0', measurement_id=None, params=None, commit=False):
    """새 현재 바인딩을 만든다. 반환: GeoBinding.

    - 같은 슬롯에 이미 현재 바인딩이 있으면 **예외**로 실패한다(단일 점유
      한정). 조용히 덮어쓰면 교체 이력이 사라진다 — 교체는 rebind() 다.
    - commit=False 기본: 호출자의 트랜잭션에 합류(place_device 관례).
    """

def unbind(binding_uid, reason, commit=False):
    """현재 바인딩을 종료한다. valid_to=지금, ended_reason=reason.
    행을 지우지 않는다 — 이력이 시계열 접합의 근거다.
    reason ∈ {'replaced','device_deleted','unbound','spatial_deleted'}
    """

def rebind(spatial_kind, spatial_id, role, device_kind, device_id,
           channel_id='0', measurement_id=None, params=None, commit=False):
    """교체 — 기존 현재 바인딩을 'replaced' 로 종료하고 새것을 만든다.
    **한 트랜잭션**이어야 한다. 중간에 끊기면 슬롯이 빈 채로 남는다.
    """
```

`end_all_for_device()` 는 **만들지 않는다** — 장치 삭제 경로 배선은 Phase C 다.

### 마커 경로도 함께 바인딩을 남긴다

`place_device()` / `unplace_device()` 가 `GeoShape.device_id` 만 쓰고 바인딩을
남기지 않으면, UI 로 배치할 때마다 `binding-drift` 가 늘어난다. 두 함수 안에서
`bind()`/`unbind()` 를 함께 호출하도록 확장한다 — 그 안이 이미 단일 게이트웨이라
확장 지점이 하나뿐이다. **레거시 컬럼 쓰기는 이 단계에서 제거하지 않는다**
(Phase C 의 폴백 제거와 함께 간다).

### REST

```
POST /api/geo/binding            {spatial_kind, spatial_id, role, device_kind,
                                  device_id, channel_id?, measurement_id?}
DELETE /api/geo/binding/<uid>    {reason}
PUT  /api/geo/binding            (rebind — 같은 슬롯, 새 장치)
GET  /api/geo/binding/unbound    ?facility_uuid=  → 미배정 슬롯 목록
```

기존 `POST /api/geo/device/location` 은 **마커 전용으로 유지**한다. 구역 배정을
그 엔드포인트에 얹지 말 것 — 마커는 좌표, 구역은 소속이라 의미가 다르다.

---

## 4. UI 요구사항

### A. 지도에서 장치 만들기 — ❌ 철회 (구현 후 되돌림, §9-5-1 참조)
~~장치 생성 자체는 기존 `input_add`/`output_add` 를 재사용한다. 지도에서 만든
장치는 **만든 직후 그 지점에 배치**돼야 한다 — 만들어 놓고 목록에서 다시 찾아
끌어다 놓게 하면 지도에서 만드는 의미가 없다.~~

만들었다가 들어냈다. 지도에서 만든 장치는 결국 설정 페이지에서 접속정보를
채워야 하는 껍데기라 왕복이 줄지 않고, 장치 생성 경로만 둘이 된다.
**이 자리를 실제로 채운 것은 복합장치(Device) 배치**다 — 입력·출력·함수는
지도에 올릴 수 있었는데 `/device` 페이지의 복합장치만 올릴 수 없었다.
다시 만들지 말 것.

### B. 도형에 장치 매기 (이 세션의 핵심)
그려진 폴리곤(`GeoShape.type='device'`)을 골라 장치를 배정 → `role='area'` 바인딩.
- 한 장치가 **여러 구역**을 담당하는 것은 정상이다(밸브 하나가 두 구역 관수).
- 한 구역에 **채널이 다른 여러 배정**도 정상이다(다채널 릴레이).
- 같은 (구역, role, 채널)에 두 장치는 불가 — GB-1a. UI 는 거부가 아니라
  **교체 플로우**(rebind)로 안내한다.

### C. 미배정 슬롯
`unbound_slots()` 가 이미 있다. 지도·시설 화면에서 "장치가 빠진 자리"로 보이고,
클릭하면 배정할 수 있어야 한다. **이 화면이 없으면 Phase C 를 시작할 수 없다.**

> **⚠ 관할을 섞지 말 것 (2026-08-08 추가).** 지도 화면은 **구역 폴리곤만**
> 보여준다(`kinds=shape`). 시설 설비(천창·팬 등)의 장치 배정은 시설 편집기
> 인스펙터의 액추에이터 드롭다운이 정본 입력 수단이고, 그쪽은
> `fittings[].actuator_id`(JSON)에 쓴다 — 바인딩은 저장 후
> `sync_facility_bindings` 가 그 JSON 에서 파생한다.
>
> 그래서 지도 목록에서 fitting 에 바인딩을 직접 만들면 **다음 시설 저장이
> 그 배정을 지운다**(실측 확인: 배정 직후 True → 시설 저장 후 False).
> 처음엔 두 종류를 한 목록에 담았다가 "천창이 왜 지도에 나오냐"는 지적으로
> 드러났다 — 화면이 이상하게 느껴지면 대개 구조가 이상한 것이다.

### D. 장치 교체 (권장 — 실제로 가장 자주 쓸 것)
고장 교체의 정답은 대개 **삭제-재생성이 아니라 접속정보 갱신**이다(DevEUI·주소만
바꾸면 도형·이력·함수 연결이 전부 유지된다). UI 는 이 경로를 1안으로 제시하고,
정말 다른 장치로 옮길 때만 `rebind()` 를 쓰게 한다. 지금 사용자가 "새로 만들고
옛것 삭제"로 가는 것은 이 경로가 화면에 없기 때문이다.

---

## 5. 절대 하지 말 것

각 항목은 실제 사고에서 나왔다. 근거 없이 적힌 금지는 하나도 없다.

**1) `save_overlays` 에 `device_id` 를 실어 구역을 배정하지 말 것.**
그건 레거시 각인 경로다(`GeoShape.device_id` 컬럼에 씀). 구역 배정은 `bind()`.

**2) 빈 페이로드로 저장하지 말 것.**
`save_overlays` 는 **upsert 전용**이다(I9). "페이로드에 없음 = 삭제" 프로토콜은
폐지됐고, 삭제는 `deletes[]` 명시 목록으로만 간다. 과거 이 프로토콜이 도형
전량 유실의 최다 발생원이었다.

**3) `device_blueprint._linked_ids()` / `_device_descendants()` 를 쓰지 말 것.**
둘 다 `parent_device_id`(소유)에 `DeviceMember`(참조)를 합쳐 돌려준다. 참조까지
전개하면 남의 장치 구성에 끼워 넣은 항목이 이 슬롯의 제어 대상이 된다.
복합장치 전개는 `device_binding.expand_device()` 를 쓴다.

**4) geo 패키지 밖에서 `GeoShape`/`GeoFacility`/`GeoBinding` 을 직접 쓰지 말 것.**
`check_geo_writes.py`(pre-commit + CI)가 거부한다. 밖에서는 게이트웨이 경유.

**5) 읽기 경로에서 ORM 의 JSON 을 제자리에서 고치지 말 것.**
`_to_dict` 는 ORM 객체를 참조로 넘긴다. 고치면 같은 세션의 뒤이은 독자가 저장값
대신 해석값을 본다(`check_geo_integrity` 의 dangling-fitting 이 죽은 참조를 살아
있는 것으로 본다). `device_binding._cow()` 패턴을 따를 것.

**6) 테스트에서 JSON 컬럼을 얕은 복사로 오염시키지 말 것.**
`list(f.fittings)` 는 내부 dict 을 공유하므로, 고친 뒤 재할당해도 SQLAlchemy 가
'변경 없음'으로 보아 **저장되지 않는다.** Phase B-1 에서 이 함정 때문에 없는
버그를 있다고 오진했다. 깊은 복사로 오염시킬 것.

---

## 6. DB 불변식이 UI 에 뜻하는 것

DB 트리거·인덱스가 강제하므로 앱에서 우회할 수 없다. 위반하면 저장이 **실패**한다.

| ID | 규칙 | UI 가 지켜야 할 것 |
|----|------|--------------------|
| I1 | `geo_shape.type` 은 화이트리스트 안 | 새 종류를 임의로 만들지 말 것 |
| I2 | 위치 마커는 (지도, 장치, 채널)당 1개 | 같은 장치를 같은 지도에 두 번 찍을 수 없다 — 이동으로 처리 |
| I6 | feature JSON 에 `aot_type` 저장 금지 | 클라이언트가 보내도 서버가 제거한다. 정본은 `type` 컬럼 |
| I7 | `type` 은 생성 후 불변 | 종류 변경 UI 를 만들지 말 것 — 삭제 후 생성 |
| I8 | `geo_id` 는 실존하는 지도 | 지도를 먼저 만들고 도형을 그린다 |
| GB-1a | 단일 점유(shape/fitting/actuator) 슬롯당 현재 1개 | 재배정은 rebind 플로우 |
| GB-1b | 다중 점유(sensor_role/weather)는 (장치,채널,측정값) 중복만 차단 | 같은 role 에 센서 여러 개는 **정상**(가중평균) |
| GB-2 | 수명 정합 + 어휘 | 종료에는 반드시 `ended_reason` |

---

## 7. 완료 판정

주장이 아니라 검사로 판정한다.

```bash
python3 aot/scripts/check_geo_writes.py                 # 0 = 소유권 위반 없음
python3 -m aot.scripts.check_geo_integrity              # binding-drift 확인
docker exec -i <컨테이너> sh -c "cd /app && python -m pytest aot/tests/geo/ -q"
```

- **`binding-drift` 가 늘지 않을 것.** UI 로 만든 배정이 바인딩에만 있고 레거시에
  없는 것은 정상(드리프트는 그 반대 방향을 센다). 마커 배치 후 드리프트가 늘면
  `place_device` 확장이 빠진 것이다.
- **폴백 로그**(`[GeoBinding] 레거시 폴백 사용`)가 UI 로 새로 만든 배정에서
  뜨지 않을 것.
- 새 불변식·게이트웨이를 추가했다면 `test_geo_invariants_attack.py` 에 **원시
  SQL 공격**을 추가한다. 통과가 아니라 **가드를 꺼서 실패하는 것**까지 확인할 것
  (음성 대조) — Phase A·B-1 에서 이 절차가 실제로 두 번 오진을 잡았다.

## 8. 손댈 파일

| 영역 | 파일 |
|------|------|
| 쓰기 게이트웨이 | `aot/aot_flask/geo/device_binding.py` (읽기는 이미 있음) |
| 마커 경로 확장 | `aot/aot_flask/geo/device_placement.py` |
| REST | `aot/aot_flask/api/geo.py` |
| 지도 UI | `static/js/geo/design/aot-geo-devices-v3.js`(장치 레이어) · `aot-geo-events.js`(선택·클릭) · `aot-geo-ui.js`(패널) |
| 장치 목록 | `GET /api/geo/devices` (`routes_geo.py:1202`) |

**UI 문구는 i18n 래핑 + ko/ja 번역까지** 넣을 것. 아이콘·이모지는 쓰지 않는다.
CSS 는 `aot-*` 공용 클래스를 재사용한다(신규 커스텀 CSS 금지).

---

## 9. 구현 결과와 계약에서 벗어난 판단 (2026-08-08)

계약이 정해 준 것(§3 시그니처·§5 금지·§6 불변식)은 그대로 따랐다. 여기 적는
것은 **계약이 정하지 않아 이 세션이 결정한 것**과 **하지 않은 것**이다.

### 만든 것

| 영역 | 파일 |
|------|------|
| 쓰기 게이트웨이 `bind`/`unbind`/`rebind` | `aot/aot_flask/geo/device_binding.py` |
| 마커 경로 확장 | `aot/aot_flask/geo/device_placement.py` |
| REST | `aot/aot_flask/api/geo.py` |
| 배정 UI | `aot/aot_flask/static/js/geo/design/aot-geo-binding-ui.js` (신설) |
| 복합장치 배치 | `utils_geo.collect_devices`(종류 분리) · `aot-geo-panel.js`(장치 탭) |
| 진입점 | `aot-geo-panel.js`(버튼) · `aot-geo-design-v3.js`(인스턴스) · `aot-geo-modules.js`(작도) |
| 테스트 | `aot/tests/geo/test_device_binding_gateway.py` (27종) |

### 계약에 없어서 이 세션이 정한 것

**1) `rebind()` 는 다중 점유 슬롯을 거부한다.** 계약의 시그니처는 슬롯 키
(spatial_kind, spatial_id, role, channel_id)로 교체 대상을 지목하는데,
`sensor_role`/`weather` 는 같은 role 에 여러 장치가 정상이라 그 키로 교체하면
**나머지 장치까지 함께 종료된다**(가중평균 구성이 통째로 날아간다). 그쪽은
`unbind()` + `bind()` 로 대상을 명시하게 하고, `rebind` 는 예외를 던진다.

**2) 도형의 `role` 은 서버가 정한다.** 클라이언트는 `spatial_id` 만 보내고
서버가 `GeoShape.type` 에서 `role_for_shape_type()` 으로 뽑는다. 프런트의
`aot_type` 은 `get_overlays` 가 `'device'` → `'aot_device'` 로 정규화해
내보내므로, 그 값을 role 로 쓰면 **구역 배정이 마커 배정으로 저장된다.**
`device_kind` 도 같은 이유로 서버가 실제 테이블에서 판별한다
(`resolve_device_kind`) — 지도 UI 의 `'function'` 은 CustomController 이고
`'generic_function'` 이 Function 이라 어휘가 다르다.

**3) 장치를 고르지 않고 그린 구역 폴리곤도 `type='device'` 로 저장한다.**
(`aot-geo-modules.js` 의 `onShapeCreated`) 예전에는 `type='aot_device'` 로
남았는데 그건 위치 마커의 종류이고, I7 에 따라 생성 후 바뀌지 않으므로 **한번
그렇게 저장되면 나중에 장치를 배정할 수단이 영영 없다**(role 이 'marker' 로
잡힌다). 반대로 `type='device'` + 배정 없음 은 그 자체로 뜻이 성립한다 —
"장치가 아직 안 정해진 구역", 곧 §4-C 가 요구한 미배정 슬롯이다. 점(마커)은
작도로 만들지 않으므로 이 분기에 오지 않는다.
**이미 `type='aot_device'` 로 저장된 옛 폴리곤은 구제되지 않는다**(I7).

**4) `unbound_slots()` 가 구역 폴리곤도 센다**(+ `map_uuid` 인자).
Phase B-1 의 주석은 "도형의 미배정은 그냥 그려둔 도형과 구별할 수 없다"였지만,
위 3) 로 `type='device'` 가 "장치가 담당하는 구역"이라는 선언이 되면서 구별이
선다. §4-C 가 요구한 화면은 이 목록 없이는 만들 수 없다.

**5) REST 를 하나 더 뒀다.** §3 의 4개 외에:
- `GET /api/geo/binding?spatial_kind&spatial_id[&role]` — 현재 배정 + 교체 이력.
  UI 가 해제하려면 바인딩의 `unique_id` 가 필요하고, 이력은 §4-D 화면의 내용이다.
**5-1) §4-A(지도에서 장치 만들기)는 철회했다.** 한 번 만들었다가 들어냈다.

이유는 만들고 나서 드러났다. 지도에서 만든 장치는 이름과 타입만 정해진
껍데기라 DevEUI·주소·측정 채널을 채우러 **결국 Input/Output 페이지로
가야 한다.** 왕복을 줄이는 게 아니라 늘린다. 계약이 든 근거("만든 직후 그
지점에 배치")도 성립하지 않았다 — 클릭 지점을 받는 배선이 없어 지도 중앙에
놓였다. 게다가 장치 생성 경로가 둘이 되어, 이 레포가 반복해서 당한 "같은
일을 두 벌 구현해 한쪽만 자란다"에 그대로 들어간다.

**대신 §4-A 자리를 채운 것은 복합장치(Device) 배치다.** 지도 패널의
장치 탭이 입력·출력·함수 셋뿐이라 `/device` 페이지의 복합장치는 지도에
올릴 수가 없었다. 원인은 `collect_devices` 가 CustomController 를 전부
`type='function'` 으로 내보내 Function 과 구분이 안 됐던 것이고,
`device_module_names()`(is_device 판정의 유일한 정본)로 갈라 `'device'`
종류를 따로 내보내고 패널에 네 번째 탭을 뒀다. 이쪽이 바인딩 설계와도
맞는다 — `device_kind='device'` 는 설계가 정한 **선호 바인딩 단위**이고
(멤버 Input/Output 보다 장치 우선), 이제 그 단위를 사람이 지도에서 직접
올릴 수 있다.

곁들여 고쳐야 했던 것 둘:
- `/api/geo/device/location` 의 `model_map` 에 `'device'` 가 없어 복합장치
  마커 저장이 400 으로 튕겼다.
- 패널 티어 id 는 `'device'` 가 아니라 `'device_unit'` 이다. `'device'` 는
  Equipment > Device Categories 가 이미 쓰는 티어 id 이고 `_getTierContent`
  는 티어 id 만 보므로, 같은 이름을 쓰면 두 화면이 서로를 덮는다. 장치
  종류를 다루는 자리에서는 `_deviceTypeOfTier()` 로 `'device'` 로 되돌린다.

복합장치 탭에는 **색 피커를 두지 않았다.** 복합장치의 색은 장치 공통색
(`theme_config.device`)인데 그 키는 input/output/function 이 미설정일 때
수렴하는 폴백이기도 하다 — 여기 피커를 달면 복합장치 색을 바꾼 것이 나머지
종류의 폴백까지 바꾼다.

**6) 마커 배치 해제의 종료 사유는 `'unbound'` 다**(`'spatial_deleted'` 아님).
사람이 "이 지도에서 이 장치를 내린다"고 한 것이고, 마커 삭제는 그 결정의
귀결이다(미배정 마커는 의미가 없다 — 설계의 마커 예외).

**7) 마커 경로의 바인딩 쓰기는 SAVEPOINT 안에서 한다.** 실패해도 배치 자체는
막지 않되(마커는 이미 레거시 컬럼에 저장됐고 백필이 나중에 같은 행을 만들 수
있다), 그냥 삼키면 실패한 flush 가 세션을 오염시킨 채 남아 **뒤이은 커밋이
무관한 자리에서 죽는다.**

### 하지 않은 것 (Phase C 로 남김)

- **도형·시설이 삭제될 때 바인딩을 종료하지 않는다(GB-4).** 구역 폴리곤을
  지우면 그 폴리곤을 가리키는 현재 바인딩이 남는다. `spatial_id` 는 재사용되지
  않으므로 그 행은 무해하게 떠 있을 뿐이지만, 정리는 Phase C 의 DB 트리거
  몫이다 — 도형 삭제 경로가 여럿이라 앱 계층에서 일부만 고치면 정확히
  "4곳만 고치고 13곳이 조용히 남는" 그 모양이 된다.
- 레거시 저장처 쓰기 제거, 장치 삭제 17경로 통일, `end_all_for_device()`.
- AI 도구(`rebind_device`·`list_unbound_slots`) — Phase D.

### 완료 판정 실측 (2026-08-08, 로컬)

- `check_geo_writes.py` → 0 (위반 없음)
- `check_js_bundles.py --rebuild` → 0 (산출물 8건 바이트 일치)
- `pytest aot/tests/geo/` → 203 passed
- `check_geo_integrity` → **binding-drift 0건**, 나머지 항목은 작업 전 기준선과
  동일(duplicate 2 · orphan-device-shape 3 · dangling-fitting 16 — 전부 기존 것)
- 브라우저 실증(로컬 8084): 배정 → 중복 배정 409 → 교체 → 해제 → 미배정 목록
  복귀, 이력에 `replaced`·`unbound` 남음. 복합장치를 장치 탭에서 배치하면
  마커가 생기고 `device_kind='device'`·`role='marker'` 바인딩이 자동으로
  기록되며, 배치를 해제하면 `unbound` 로 종료되는 것까지 확인.
- **폴백 로그 0건** — 새로 만든 배정에서 `[GeoBinding] 레거시 폴백 사용` 이
  뜨지 않았다.
- 게이트웨이 가드는 **음성 대조**로 확인했다: 점유 검사와 다중 점유 거부를
  끄면 해당 테스트 2종이 실패하고, 마커 경로의 바인딩 기록을 빼면 3종이
  실패한다. 반면 `rebind` 의 명시 `flush()` 는 빼도 통과했다 — SQLAlchemy 가
  같은 테이블에서 UPDATE 를 INSERT 보다 먼저 emit 하기 때문이며, 그 사실을
  코드 주석과 테스트 docstring 에 적었다(근거 없는 "이 flush 가 막아준다"는
  설명을 남기지 않으려고).

### 새 불변식은 추가하지 않았다

GB-1·GB-2 는 Phase A 에서 이미 걸려 있고 `test_geo_invariants_attack.py` 의
`TestBindingAttacks` 15종이 원시 SQL 로 지킨다. 이 세션은 그 위에 게이트웨이를
얹었을 뿐이라 새 공격 테스트를 더하지 않았다 — 대신 게이트웨이 테스트가
**인덱스가 실제로 걸린 DB**에서 돈다(`apply_binding`).
