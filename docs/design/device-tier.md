# 복합장치(Device) 티어 설계

작성: 2026-07-28. 기준 문서 — "Device"가 Input/Output/Function과 같은 급의
1급 엔티티로서 어떻게 하위 Input/Output/Function을 자동 생성·소유·연결하는지와,
그 위에 얹힌 설정 모달 UI 구조를 정의한다. 착수 배경·Phase별 진행 기록·라이브
검증 로그는 `.local/plans/device_group_console_plan.md` 참조.

## 1. 개념

Device는 별도 테이블이 아니라 `is_device=True`를 선언한 **Custom Function
모듈**(`CustomController` 행)이다. 시스템 제공 복합장치(예: Modbus PLC)를
추가하면 그 장치를 구동하는 데 필요한 Input/Output이 청사진대로 자동
생성·연결되어 한 자리에서 통합 관리된다.

```
Device (복합장치)          ← CustomController 행. 컨트롤러 역할. 위치·노트 보유
  ├─ Input   (측정)        ← 하위. 청사진에 있으면 자동 생성·연결
  ├─ Output  (제어)        ← 하위. 청사진에 있으면 자동 생성·연결
  └─ (다른 Device)         ← 하위 장치. 항상 참조 관계로만 표현
```

Input/Output/Function 페이지는 그대로 유지된다 — 장치에 소속된 항목도 각자의
목록에서 숨기지 않고, 카드에 소속 장치 배지만 추가로 표시한다.

## 2. 데이터 모델

두 가지 서로 다른 소속 관계가 있고, 컬럼도 분리되어 있다.

| 관계 | 저장 위치 | cascade(활성화/비활성화) 대상 | 다대다 |
|---|---|---|---|
| **소유(primary)** | `Input`/`Output`/`Function`/`CustomController`.`parent_device_id` | O — 유일하게 cascade가 보는 관계 | X (한 항목은 정확히 하나의 primary 소유자만 가짐) |
| **참조(secondary)** | `device_member(device_id, member_type, member_id)` 조인 테이블 | X — 참조만 하는 다른 장치의 활성화 상태에 영향받지 않음 | O |

두 관계를 분리한 이유: 다대다 소속을 `parent_device_id`로도 표현하면 두 장치가
같은 Input을 소유 주장하게 되어 cascade 의미가 깨진다. `device_member`는 이미
다른 장치의 primary(또는 secondary)인 Input/Output/Device를 **참조만** 추가로
연결하는 용도이며, `member_type='device'`로 장치 간 계층(하위 장치)도 같은
테이블로 표현한다. 순환 참조는 조상 체인을 걸어 올라가며 거부한다
(`aot/utils/device_blueprint.py`의 `_device_descendants()`).

`FUNCTION_INFORMATION`에 장치 모듈이 선언하는 키:

| 키 | 의미 |
|---|---|
| `is_device: True` | 이 모듈이 복합장치 티어에 속함(Function 목록과 분리되는 스위치) |
| `device_category` | `controller` / `sensor_node` / `actuator_unit` |
| `device_blueprint` | 자동 생성할 하위 Input/Output 정의(선택) — 3절 |
| `options_disabled` | 이 장치가 직접 측정 채널을 갖지 않으면 `['measurements_select', 'measurements_configure']`로 공용 옵션 fragment의 "측정값 설정" 그룹을 숨김(`aot/functions/backup_rsync.py` 선례와 동일 패턴) |

## 3. 청사진(blueprint) 기반 생성 — 접속정보 1회 입력

```python
'device_blueprint': {
    'inputs': [{'device': 'MODBUS_TCP', 'name': '{device_name} 측정',
                'inherit_options': ['plc_host', 'plc_port', 'unit_id']}],
    'outputs': [{'device': 'MODBUS_TCP_COIL', 'name': '{device_name} 제어',
                 'inherit_options': ['plc_host', 'plc_port', 'unit_id']}],
}
```

- `execute_at_creation`이 청사진대로 Input/Output을 생성하고 각각에
  `parent_device_id = 장치.unique_id`를 기록한다(`aot/utils/device_blueprint.py`의
  `create_blueprint_members()`).
- `inherit_options`로 지정한 옵션은 **장치 설정 저장 시점마다**
  `sync_inherited_options()`가 하위로 재전파한다 — 생성 시점(`execute_at_creation`)이
  아니라 저장 시점인 이유는, 생성 직후엔 그 값들이 아직 드라이버 기본값(빈 문자열
  등)이기 때문이다. 방향은 **부모 → 자식 단방향**으로 고정 — 자식을 직접 고친
  사용자의 의도를 부모가 되덮어쓰지 않기 위함이다.
- 채널까지 자동 생성하지는 않는다(Modbus PLC 모듈: 실제 레지스터 맵은 벤더/모델마다
  달라 가정할 수 없으므로 빈 채널만 만들고, 사용자가 각 Input/Output 정본 페이지에서
  채널을 채운다).

**청사진 없는 장치** — `device_custom_generic.py`는 `device_blueprint` 키 자체를
생략한다. 사용자가 빈 장치를 추가한 뒤, 아래 4절의 연결 UI로 이미 갖고 있는(또는
다른 장치에 이미 속한) 임의의 Input/Output/Device를 자유롭게 붙여 "이 항목들을
한 장치로 묶어서 본다"는 결과를 얻는다 — 새 생성 메커니즘이 아니라 기존 연결 UI의
재사용이다.

## 4. 생명주기

| 시점 | 동작 |
|---|---|
| 장치 추가 | 청사진이 있으면 하위 Input/Output 생성(3절), 없으면 빈 컨테이너 |
| 장치 활성화 | 장치 자신 + **primary 소유 하위 Input/Output 자동 활성화**(cascade). secondary 참조는 영향받지 않음 |
| 장치 비활성화 | 위와 대칭 |
| 장치 삭제 | 하위 엔티티까지 함께 삭제(확인 UI, `device.html`) |
| 하위 개별 삭제 | 허용 — `parent_device_id`가 가리키던 항목이 사라질 뿐 장치는 정상 동작 |

**알려진 gap**: `Input`/`Output`/`CustomController` 표준 삭제 경로가
`ensure_map_config`가 만든 GeoMap을 정리하지 않아 장치(또는 그 하위) 삭제 시
GeoMap 고아가 남는다. 장치 삭제 UI 자체가 이번 범위에서 만들어졌으나 이 gap은
아직 해소되지 않았다 — 별도 후속 필요(`.local/plans/device_group_console_plan.md`
Phase 2/7~9 실행 결과 참조).

## 5. UI

### 5.1 배치

Settings 드롭다운에서 Input 위에 "Device"(`장치`)가 있다
(`layout_default.html` — `layout.html`은 기동 시 덮어써지므로 직접 수정 금지).

### 5.2 장치 설정 모달 — 섹션 순서와 그 이유

`device.html`의 톱니바퀴 → 우측 드로어(데스크톱)/전체화면(모바일) 모달은
input/output/function과 같은 `aot-modal-modern.css` 골격(`aot-modal-group-title`/
`aot-modal-container`/`aot-modal-option-row`)을 쓰며, 위→아래 순서는 다음과 같다.

1. **기본 설정** — 이름/탭/노트·AI 바로가기(공용 옵션 fragment)
2. **Advanced Settings** — 장치별 접속정보 등 커스텀 옵션(공용 옵션 fragment).
   측정 채널을 직접 갖지 않는 장치는 2절의 `options_disabled`로 "측정값 설정"
   그룹이 여기 끼어들지 않는다.
3. **측정 채널 / 제어 채널** — `buildTree()`가 그리는 순수 읽기 전용 값/상태
   표시. 조작 버튼이나 "설정 →" 딥링크를 두지 않는다 — 링크로 연결하는 기존
   Output은 on_off/`actuator_paired`(개폐+위치%)/조건부 버튼 등 채널 타입이
   다양해, 여기서 하나의 조작 UI를 고정하면 타입이 안 맞는 조작을 붙이게
   된다. 실제 조작·설정 진입은 4절 목록의 이름 링크 하나로 모은다.
4. **입력 / 출력** — 드롭다운+"링크" 버튼(연결 조작) → `aot-modal-subgroup-title`
   "연결됨" → 연결된 Input/Output 목록(이름이 그 정본 페이지로 가는 링크,
   secondary 항목엔 "(참조)" 태그) 순서로 배치한다. **조작이 먼저, 그 결과가
   바로 아래**라는 순서 자체가 "이걸 누르면 저게 생긴다"는 관계를 보여준다.
   후보가 수십~수백 개(Output 실물 기준 50+)까지 늘 수 있어 목록이 아니라
   검색 가능한 드롭다운(`_buildCandidateDropdown`/`_wireCandidateDropdown`,
   bootstrap-select 재사용) 하나 + 버튼 하나로 처리한다.
5. **하위 장치** — 4절과 동일한 순서(드롭다운+링크 → 연결됨 → 목록)의 별도
   그룹. `member_type='device'`인 secondary 연결만 대상.

노트 개수 등 다른 위젯이 이미 보여주는 정보는 이 콘솔에서 중복 표시하지 않는다
("메모 관리" 버튼이 노트 위젯으로 안내).

### 5.3 데이터 경로

신규 엔드포인트는 `/device/<id>/summary`(구성 조립, 폴링 대상 아님)와
`/device/<id>/candidates`(연결 후보) 둘뿐이다. 실시간 값·상태는 기존 경로를
그대로 폴링한다 — `POST /data_batch`, `GET /inputstate`, `/outputstate`.

## 6. 대가(trade-off)

- Device는 `CustomController` 행이므로 `is_device` 필터를 빠뜨린 화면이 생기면
  Function 목록에 그대로 섞여 보일 수 있다.
- 청사진이 코드에 하드코딩된다 — 장치 종류가 늘 때마다 모듈 파일이 하나씩 는다.
- 자동 생성물의 소유권이 모호해질 수 있다 — "부모→자식 단방향, 저장 시점에만"
  규칙(3절)을 어기는 화면이 생기면 사용자가 직접 고친 하위 설정을 덮어쓸 위험.
- `OrchDevice`(`aot/databases/models/orch_device.py`, 작업 실행 주체를 뜻하는
  별개 개념)와 이름이 겹친다 — 코드·UI 문구에서 혼동되지 않게 유의.

## 7. 관련 파일

| 파일 | 역할 |
|---|---|
| `aot/utils/device_blueprint.py` | `create_blueprint_members()`(생성)·`sync_inherited_options()`(접속정보 재전파)·`linkable_members()`/`link_member()`(연결 후보·연결/해제, 순환참조 거부) |
| `aot/databases/models/device_member.py` | secondary 소속 조인 테이블 |
| `aot/aot_flask/routes_device.py` | `/device/<id>/summary`, `/device/<id>/candidates`, `/device/<id>/link`, `/device/<id>/unlink` |
| `aot/aot_flask/templates/pages/device.html` | 장치 목록/카드 + 설정 모달(5.2) |
| `aot/functions/custom_functions/device_modbus_plc_generic.py` | 청사진형 실물 장치 1호(Modbus TCP PLC) |
| `aot/functions/custom_functions/device_custom_generic.py` | 청사진 없는 사용자 정의 복합장치 |
| `aot/functions/custom_functions/device_aot_c.py` | ChirpStack 연동 태양광 12V 릴레이/밸브 노드 |
