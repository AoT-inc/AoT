# geo/design 장치 추가·배치 UI — 인계 계약서

별도 세션에서 진행할 작업의 계약. **이 문서 하나만 읽고 착수할 수 있도록** 쓴다.
배경 설계는 [geo-device-binding.md](geo-device-binding.md), 지도 데이터 불변식은
[geo-data-integrity.md](geo-data-integrity.md).

작성 시점(2026-08-08)에 Phase A(바인딩 테이블·불변식·백필·검사)와 Phase B-1
(읽기 리졸버 + 소비처 2곳)이 완료돼 있다. 이 세션은 **쓰기 쪽 첫 소비자**다.

---

## 1. 무엇을 만드는가

| # | 기능 | 현재 상태 |
|---|------|-----------|
| A | 지도에서 **장치를 새로 만들기** | 없음 — 장치는 Input/Output 페이지에서만 생성 |
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

### A. 지도에서 장치 만들기
장치 생성 자체는 기존 `input_add`/`output_add` 를 재사용한다. 지도에서 만든
장치는 **만든 직후 그 지점에 배치**돼야 한다 — 만들어 놓고 목록에서 다시 찾아
끌어다 놓게 하면 지도에서 만드는 의미가 없다.

### B. 도형에 장치 매기 (이 세션의 핵심)
그려진 폴리곤(`GeoShape.type='device'`)을 골라 장치를 배정 → `role='area'` 바인딩.
- 한 장치가 **여러 구역**을 담당하는 것은 정상이다(밸브 하나가 두 구역 관수).
- 한 구역에 **채널이 다른 여러 배정**도 정상이다(다채널 릴레이).
- 같은 (구역, role, 채널)에 두 장치는 불가 — GB-1a. UI 는 거부가 아니라
  **교체 플로우**(rebind)로 안내한다.

### C. 미배정 슬롯
`unbound_slots()` 가 이미 있다. 지도·시설 화면에서 "장치가 빠진 자리"로 보이고,
클릭하면 배정할 수 있어야 한다. **이 화면이 없으면 Phase C 를 시작할 수 없다.**

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
