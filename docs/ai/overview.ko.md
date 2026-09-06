# AI 기능 개요

AoT는 MCP(Model Context Protocol) 기반 AI 에이전트를 통해 온실·재배 시설의 환경을 관찰·진단·제어합니다. AI는 시스템을 보조하는 역할로, 장비를 움직이는 동작은 사용자 승인 후 실행됩니다(설정만 바꾸는 편집은 예외 — 아래 시퀀스 절 참고).

---

## 시작하기: 스위치가 두 개입니다 { #enable-and-start }

AI를 쓰려면 서로 다른 자리의 스위치 두 개를 켜야 합니다. 하나로 합치지 않은 이유가 있습니다.

| 스위치 | 자리 | 켜면 생기는 일 |
|--------|------|----------------|
| **AI 서비스 사용** | 설정 > 일반 | AI 메뉴가 내비게이션에 나타나고 AI 페이지에 들어갈 수 있습니다. 채팅·조언 요청이 동작합니다. |
| **AI 서비스 작동** | AI > AI 에이전트 | 사람이 부르지 않아도 도는 작업이 시작됩니다 — 주기 요약, 컨텍스트 브로드캐스트, 날씨 요약, MCP 헬스체크, 실시간 알림. |

순서는 **설정에서 사용 → AI 페이지에서 모델(에이전트) 등록 → 작동 시작**입니다.

- **모델을 하나도 등록하지 않으면 작동을 시작할 수 없습니다.** 물어볼 모델이 없는데 백그라운드 작업만 돌면 매 주기 로그에 오류만 쌓입니다. 작동 스위치는 활성 에이전트가 하나 이상일 때만 눌립니다.
- **마지막 모델을 비활성화하거나 삭제하면 작동도 함께 멈춥니다.** 나중에 모델을 다시 살려도 자율 작동은 저절로 재개되지 않습니다 — AI 페이지에서 다시 켜 주세요.
- **작동을 꺼도 채팅·조언 요청은 그대로 됩니다.** 모델을 막 등록하고 시험해 보는 단계에서 스위치를 켤 필요가 없도록 한 것입니다.

---

## AI 시스템 구조 { #agents }

AoT의 AI는 두 가지 경로로 도구를 사용합니다.

- **인앱 AI 어시스턴트** — 대시보드의 채팅 어시스턴트. 단일 에이전트 루프가 전체 도구 카탈로그를 보고 스스로 도구를 선택·실행합니다. 상태를 바꾸는 동작(장치 제어, 엔티티 생성·수정·삭제 등)은 채팅의 **승인 카드**로 사용자 확인을 받은 뒤 실행됩니다.
- **외부 MCP 서버** — `aot/aot_mcp_server.py` (표준 MCP 프로토콜, stdio/HTTP). Claude Desktop 같은 외부 MCP 클라이언트가 AoT 도구를 직접 호출할 수 있게 노출합니다.

```
사용자 채팅 ─────────────┐            외부 MCP 클라이언트(Claude Desktop 등)
                         ↓                          ↓
              인앱 에이전트 루프          aot_mcp_server.py (stdio/HTTP)
                         └──────────┬───────────────┘
                                    ↓
                    도구 레지스트리 (tool_registry.py, 단일 소스)
                                    ↓
                        AoT 시스템 (Daemon / InfluxDB / SQLite)
```

두 경로 모두 같은 도구 레지스트리(`aot/ai/services/tool_registry.py`)에서 도구를 가져오므로 목록이 서로 어긋나지 않습니다.

---

## MCP 도구 목록

외부 MCP 서버와 내부 `mcp_aot` 엔진이 노출하는 도구입니다. 읽기 도구와 설정 편집 도구는 즉시 실행되고, 제어·일정·활성화 도구는 승인 게이트를 거칩니다 — 인앱 어시스턴트에서는 채팅의 승인 카드로, 외부 MCP 서버에서는 대기열(`pending_approval` + `respond_to_confirmation`)로 처리됩니다(자세한 내용은 아래 "MCP 서버 실행" 참고).

### 관찰·조회 (읽기 — 즉시 실행)

| 도구 | 설명 |
|------|------|
| `get_spatial_tree` | 공간 계층(사이트 > 구역 > 장치) 트리 |
| `resolve_target` | 장치/구역 이름을 정확한 엔티티로 해석 — 컨테이너(하위 구역 보유)인지 미리 확인 |
| `get_device_list` | 등록된 전체 장치(입력·출력·카메라) 목록 |
| `search_devices` | 이름·유형 키워드로 장치 검색 |
| `get_sensor_detail` | 센서 시계열 이력 (min/max/avg 통계) |
| `get_weather` | 포장·구역의 현재 기상 (기온·습도·풍속·강수) |
| `get_energy_report` | 기간·구역별 에너지 사용량 리포트 |
| `get_cumulative_status` | EnvCoordinator DLI(일적산광량)·GDD(누적온도) 상태 |
| `search_notes` | 구역·장치에 부착된 노트/메모/작업기록 조회 |
| `get_note_attachment` | 노트에 첨부된 사진을 실제 이미지로 조회 (한 번에 한 장) |
| `list_notices` | 공지 게시판 글 목록 |
| `get_system_update_status` | 설치 버전 vs GitHub 최신 릴리스 비교 |
| `list_available_devices` | AI 판단 대상 장치 목록 (네이티브 브리지) |
| `get_sensor_reading` | 특정 센서의 최신 측정값 (네이티브 브리지) |

### 기록·작업

| 도구 | 설명 | 승인 |
|------|------|------|
| `create_note` | 날짜 없는 메모/노트를 대상 엔티티에 부착해 즉시 저장 | 불필요 |
| `add_schedule` | 사람이 수행할 작업 일정(제초·점검·청소 등) 등록 | 필요 |
| `add_schedule_batch` | 여러 대상(구역별 등)의 일정을 단일 승인으로 일괄 등록 | 필요 |

### 제어 (사용자 승인 필요)

| 도구 | 설명 |
|------|------|
| `operate_device` | 밸브·펌프·조명 등 즉시 물리 제어 |
| `set_output_state` | 출력 장치 on/off (선택적 지속시간, 네이티브 브리지) |
| `schedule_device_control` | 특정 시각 1회성 장치 제어 예약 |

> 인앱 어시스턴트에서는 위 제어·`add_schedule` 호출이 승인 카드로 확인을 받은 뒤 실행됩니다. 외부 MCP 서버로 직접 호출할 때도 동일하게 승인을 거칩니다 — 최초 호출은 실행되지 않고 `pending_approval`(대기 중인 confirmation_id)로 응답하며, 사용자가 그 confirmation_id를 채팅에서 명시적으로 승인/거부해야 `respond_to_confirmation` 호출(또는 웹 승인 페이지 클릭)로 처리되고, 그 뒤 같은 인자에 `_confirmation_id`를 붙여 재호출해야 실제로 실행됩니다. 자세한 흐름은 아래 "MCP 서버 실행"을 참고하세요.

### 시퀀스 (설정 편집은 승인 불필요)

[시퀀스](../Functions.ko.md#trigger-sequence)는 여러 출력 장치를 정해진 순서로 돌리는 기능으로, 밸브가 차례로 열리고 펌프가 전 구간을 도는 관수가 대표적인 형태입니다. 아래 도구로 시퀀스를 읽고 구성합니다.

| 도구 | 설명 |
|------|------|
| `configure_sequence_day` | 한 요일의 실행 계획 전체를 한 번에 설정 — 어떤 장치가, 어떤 순서로, 얼마나, 무엇과 함께 도는지 |
| `modify_sequence_step` | 스텝 하나의 그룹·지속시간·단일/전체 모드·전체 모드 리드/래그·실행 순서·활성 여부·라벨 (전체 적용 또는 특정 요일만) |
| `modify_sequence_schedule` | 하루 실행 창, 사이클 주기, 운영 요일 |

> **시퀀스 설정 편집은 승인 없이 바로 반영됩니다.** 위 세 도구와
> `create_sequence_function`·`modify_function_options` 는 설정만 바꿀 뿐
> 어떤 장비도 움직이지 않습니다 — 편집한 내용이 실제로 도는 시점은
> `activate_function` 을 지나야 하고, 그 활성화는 계속 승인 대상입니다.
> 대신 **이미 활성 상태인 시퀀스의 시간표를 고치면 승인 없이 다음 실행
> 시각이 바뀝니다.** 알고 받아들인 절충입니다(2026-08-07).

`get_function_detail`은 시퀀스의 스텝 목록과 함께 `weekly_plan`을 돌려줍니다 — 요일별로 실제 몇 시부터 몇 시까지 무엇이 도는지를 벽시계 시각으로 해결한 결과입니다. 변경한 뒤에는 요청을 되풀이하지 말고 이걸 읽어서 확인하세요.

쓰기 전에 알아둘 것 두 가지입니다.

- **같은 슬롯에 넣은 장치는 동시에 작동하고**, 슬롯 하나는 지속시간을 공유합니다. "이 밸브 두 개를 같이 40분" 이 이렇게 표현됩니다.
- **요일마다 어떤 스텝이 돌지, 그룹과 지속시간을 따로 덮어쓸 수 있습니다.** 그래서 시퀀스 하나가 목요일 저녁 관수와 금요일 새벽 관수를 함께 담습니다. 요일이 다르다고 시퀀스를 새로 만들지 마세요.

`modify_function_options`는 시퀀스(및 모든 트리거)에 통하지 않습니다 — 트리거의 설정은 `custom_options`가 아니라 DB 컬럼입니다. 호출하면 위 도구를 안내하며 거부합니다.

### 호출 상태 (`call_state`) { #call-state }

`tools/call` 응답에는 항상 `call_state` 가 함께 실립니다. 도구마다 다른 `status`
어휘(`modified`·`created`·`deleted`·`configured`·`success` …)를 몰라도 **이 호출이
실제로 돌았는지** 한 키로 판정할 수 있습니다.

| 값 | 뜻 | 클라이언트가 할 일 |
|------|------|------|
| `executed` | 이번 호출에서 실행됨 (읽기 도구 포함) | 결과를 전달 |
| `already_executed` | 사람이 승인할 때 서버가 이미 실행함 | 동봉된 `result` 를 결과로 전달, 재호출 금지 |
| `pending_approval` | 실행 안 됨, 사람 승인 대기 | 승인 화면을 안내하고 대기 |
| `approval_rejected` | 사람이 거부함 | 실행하지 말고 자문으로 전환 |
| `approval_expired` | 승인 대기가 만료됨 | 다시 요청 |
| `refused` | 그 밖의 거부 (레이트 리밋, 인자 불일치 등) | `reason_code` 를 보고 안내 |
| `failed` | 도구가 오류로 끝남 | 오류 내용을 전달 |

기존 `status` 값은 그대로 둡니다 — 이미 그 값으로 분기하는 코드와 배포된 설정이
있어서, 통일하는 대신 축을 하나 더 두었습니다.

### 인앱 어시스턴트 확장 도구

인앱 AI 어시스턴트는 위 MCP 카탈로그 외에 엔티티 조립·자동화·지식까지 다루는 확장 도구를 추가로 사용합니다. 장비를 움직이거나 함수를 활성화·삭제하는 도구는 승인이 필요합니다.

- **입력/출력 관리**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **함수(자동화)**: `get_function_list`, `get_function_detail`, `create_function`, `create_sequence_function`, `modify_function_options`(트리거에는 통하지 않음 — 위 시퀀스 절 참고), `activate_function`·`deactivate_function`·`delete_function`, 그리고 시퀀스 도구 `configure_sequence_day`·`modify_sequence_step`·`modify_sequence_schedule`
- **일정 원장**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **지도(GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`, `list_unbound_slots`(장치가 없는 자리), `rebind_device`(한 장치의 지도 자리 전부를 다른 장치로)
- **GIS 입력(지도 레이어)**: `list_gis_inputs`, `create_gis_input`·`modify_gis_input`·`delete_gis_input`, `activate_gis_input`(VWorld/Google/OpenWeather 등 지도 레이어 제공자 관리)
- **설비/시설 조회**: `get_facility_capacity`(시설 냉난방 용량·체적·환기·관수 설계 요약), `get_map_equipment`(지도에 그린 설비의 구역별 관수 설계 요약, 스프링클러/점적 구분), `get_map_equipment_detail`(개별 스프링클러 위치·간격·반경, 배관별 상세 — 요약으로 부족할 때만)
- **공지 게시판**: `create_notice`·`modify_notice`·`delete_notice`
- **AI 에이전트 관리**: `list_ai_agents`, `list_ai_entries`, `create_ai_agent`·`modify_ai_agent`·`delete_ai_agent`
- **지식 라이브러리**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **진단·기타**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> 도구의 단일 정본은 `aot/ai/services/tool_registry.py`입니다. 도구가 추가·변경되면 이 문서보다 그 파일이 우선합니다.

---

## 장치별 AI 판단 포함 여부 { #device-ai-toggle }

`설정 -> 입력` / `설정 -> 출력`의 각 장치 설정 모달에는 **AI 판단 포함**(Include in AI Judgment) 토글이 있습니다.

- 켜짐(기본값): 해당 입력/출력이 AI 판단·제어 도구(공간 트리, 장치 조회, 센서·제어 도구 등)에 노출됩니다.
- 꺼짐: 해당 장치는 위 도구들의 조회·제어 대상에서 제외됩니다. 민감한 장치나 AI가 다루면 안 되는 장치를 개별적으로 숨길 때 사용하세요.

신규 입력/출력은 기본적으로 켜진 상태(`is_ai_enabled=True`)로 생성됩니다.

---

## 안전·승인 모델 { #safety-approval-model }

상태를 바꾸지 않는 **읽기 도구**는 즉시 실행됩니다. **상태를 바꾸는 도구**는 어느 경로로 호출되든 승인 게이트를 거칩니다.

- **승인 필요(변이·물리 제어)**: 장치 제어(`operate_device`, `set_output_state`, `schedule_device_control`), 입력/출력/함수/공지/AI 에이전트/GIS 입력의 생성·수정·삭제, 지도 배치 변경(`set_device_location`, `delete_geo_shape`), 장치 교체(`rebind_device`), `add_schedule`·`add_schedule_batch`, `configure_library_source` 등.
- **승인 불필요(저위험 기록)**: `create_note`, `knowledge_shelve` — 되돌릴 수 있는 개인 메모/미확인 지식으로 즉시 저장되며, 확정 전까지 권위 없는 정보로 취급됩니다.

승인이 필요한 동작은 즉시 적용되지 않습니다. **인앱 어시스턴트**에서는 채팅에 **승인 카드**로 제시되어 사용자가 승인해야 실제로 실행됩니다. **외부 MCP 서버**에서는 `pending_approval` 응답(대기열)으로 나가고, 사용자가 그 confirmation_id를 명시적으로 승인/거부해야 처리됩니다 — 어느 경로든 거부하면 아무 변경도 일어나지 않습니다.

웹 승인 페이지(`AI → MCP 서버 목록 → AI 요청 및 조언`)에서 승인하면 **서버가 그 자리에서 실행**합니다. 사람이 승인한 뒤 다시 AI 에게 알려줘야 실행되던 왕복을 없앤 것으로, 실행은 승인 화면에 표시된 인자 그대로만 이루어집니다. 이후 AI 가 같은 confirmation_id 로 재호출하면 재실행 없이 그때의 결과가 돌아옵니다. 밸브·펌프처럼 되돌릴 수 없는 물리 제어만 승인 화면에서 한 번 더 확인을 받습니다.

---

## 지식 라이브러리 (Knowledge Library) { #knowledge-library }

`AI -> 라이브러리`(`/ai/library`) 페이지에서 AI 답변의 근거가 되는 **컨텍스트 소스**를 등록합니다. 문서(PDF·텍스트), 웹 URL, REST API, 내부 쿼리를 소스로 추가할 수 있습니다.

### 지식은 어디서 오는가

라이브러리에는 네 부류가 들어 있고, AI 는 각각을 다르게 인용합니다.

| 출처 | 무엇인가 | 인용 방식 |
|---|---|---|
| 권위 | 동기화된 공공데이터 피드(RDA·농사로 등) | 사실로 말하고 출처를 밝힙니다 |
| 사용자 | 직접 입력했거나 업로드한 문서 | 신뢰합니다 — 사용자가 곧 출처입니다 |
| 관측 | 이 시스템의 측정에서 도출한 것 | 일반 법칙이 아니라 이 현장의 관측으로 제시합니다 |
| AI 정리 | AI 가 조사하거나 알아내어 저장한 것 | **미확인 메모임을 밝히고** 인용합니다 |

AI 는 라이브러리에 직접 쓸 수 있습니다. 무언가를 조사하면 요약을 저장해 두어
다음 질문이 처음부터 다시 조사하지 않게 합니다. 그렇게 들어온 항목은 **항상
미확인으로 시작**하고, 인용될 때 그 사실이 함께 밝혀집니다 — 모델이 잊더라도
서버가 고지 문구를 붙입니다.

### AI 가 쓴 것을 검토하기

**AI-Curated Knowledge Review** 섹션에 AI 자신의 메모가 모입니다. 원문 링크를
열어 확인한 뒤 확인·수정·폐기하세요. '확인'이 곧 미확인 상태에서 벗어나는
승격입니다. 원문 주소가 없는 항목은 확인할 방법이 없으므로 링크도 뜨지 않고
미확인으로 남습니다.

**검토된 지식만**(기본 꺼짐)을 켜면 AI 가 자기가 쓴 미검토 메모를 인용하지
못합니다. 권위·사용자 지식은 영향을 받지 않습니다.

### 열람하고 직접 넣기

**지식 항목** 섹션은 AI 가 인용할 수 있는 전부를 보여줍니다. 검색하고, 태그나
출처로 거르고, 낡은 것은 치우세요(치우기는 행을 남깁니다 — AI 손이 닿지 않게 할
뿐입니다).

**지식 추가**는 이미 알고 있는 것을 AI 턴이나 소스 등록 없이 바로 적는 자리입니다.
여기 적은 것은 확인된 것으로 취급합니다. 사용자가 출처이기 때문입니다.

### 지식 다이제스트 파이프라인

문서·웹 URL처럼 긴 산문형 소스는 등록 시 **한 번만** 전처리됩니다.

1. 소스를 여러 **청크(chunk)**로 분할합니다.
2. 각 청크를 LLM으로 **요약(digest) + 키워드 추출**하여 `ai_knowledge_chunk` 테이블에 캐시합니다.
3. 질의 시점에는 LLM 호출 없이 **DB 조회 + 결정론적 검색**만 수행합니다 → 답변이 빠르고 비용이 낮습니다.

### 스코프는 시설이 아니라 태그입니다

!!! warning "바뀌었습니다 — 라이브러리는 농장 전체 공용입니다"
    예전에는 지식이 `facility_id` 로 걸러졌고, 이 문서의 이전 판은 한 사이트에
    등록한 문서가 다른 사이트 답변에 절대 안 나온다고 적었습니다. **지금은
    그렇지 않습니다.** 라이브러리는 평면적인 농장 전체 목록이며, 어떤 항목이든
    어떤 질문에나 검색될 수 있고 관련도는 태그와 키워드 점수로 정해집니다.

    라이브러리를 기밀 경계로 쓰지 마세요. 이 AI 를 쓰는 모든 사람에게 보이면 안
    되는 내용이라면 라이브러리에 넣지 마십시오.

대신 **태그**가 스코프 역할을 합니다 — `무`, `북쪽구획`, `교량-a` 처럼 실제로
관리하는 대상을 자유롭게 적습니다. AoT 는 농업 전용이 아니므로 정해진 어휘가
없습니다. 질의를 알맞은 주제로 좁히는 것이 태그입니다.

### 지역을 가리지 않는 내장 소스 { #global-sources }

내장 소스 대부분은 한국 공공데이터(RDA·농사로·NCPMS·스마트팜코리아)이고 각각
해당 기관의 API 키가 필요합니다. 그 밖의 지역에서는 다음 둘로 시작할 수
있습니다 — **키가 필요 없고 어디서나 됩니다.**

| 소스 | 무엇에 답하나 |
|---|---|
| FAO ECOCROP (EXT-GL-01) | 2,500종 이상의 생육 온도·강수·토양 pH·고도 한계 |
| Open-Meteo (EXT-GL-02) | 전세계 예보, 토양 깊이별 온도·수분, 기준증발산량 ET₀, 과거 기후 |

Open-Meteo 는 특히 **AoT 의 날씨 도구가 닿지 않는 자리**를 메웁니다. `get_weather`
는 이 설치에 꽂힌 기상 센서만 읽고, `get_weather_forecast` 는 한국 기상청 전용
입니다 — 센서가 없거나 한국 밖이면 이것이 유일한 기상 근거이고, 토양값과 ET₀ 는
센서 유무와 무관하게 여기서만 나옵니다.

나머지는 반대 방향으로 채웁니다 — 자기 문서·웹 페이지·REST API, 그리고 AI 가
일하면서 조사해 비치하는 것들입니다.

### 자료 출처 표시 { #data-credits }

내장 전역 소스 둘은 **CC BY 4.0** 자료입니다. 이 라이선스는 자료를 보여 주는
자리에 출처를 밝히도록 요구하므로, AoT 는 두 곳에서 밝힙니다.

- **AI 라이브러리 화면** — 소스 목록 아래 "자료 출처" 줄. 켜 둔 소스만 실립니다.
- **AI 답변** — 조회 응답이 출처 문구를 함께 실어 보내므로, AI 가 그 값을 인용할
  때 출처도 함께 적습니다.

| 소스 | 라이선스 | 표기 |
|---|---|---|
| Open-Meteo | CC BY 4.0 (무료 이용은 비상업 목적) | Weather data by [Open-Meteo.com](https://open-meteo.com/) |
| FAO ECOCROP | CC BY 4.0 | FAO ECOCROP |

!!! warning "상업적으로 쓰신다면"
    Open-Meteo 무료 엔드포인트는 약관상 **비상업 목적으로 한정**됩니다(구독·광고가
    있는 서비스, 상업 제품 통합 등은 상업 이용에 해당). 상업 농가·서비스는
    [Open-Meteo 유료 키](https://open-meteo.com/en/pricing)를 발급받아 소스 설정에
    넣으십시오 — 키가 있으면 AoT 가 상업용 엔드포인트로 조회합니다.

표기 문구는 소스 설정(톱니)의 **출처** 칸에서 고칠 수 있습니다. 비워 두면 내장
기본값이 쓰입니다.

---

## MCP 서버 실행

외부 MCP 클라이언트용 표준 MCP 서버입니다. 앱 시작 시 자동으로 warm-start되며, 수동 실행도 가능합니다.

```bash
# stdio 모드 (기본) — 같은 machine 의 로컬 클라이언트
python3 /opt/AoT/aot/aot_mcp_server.py

# HTTP 모드 — 원격 클라이언트 (기본 포트 5700)
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

HTTP 모드는 두 가지를 함께 제공합니다.

| 경로 | 무엇 | 쓰는 곳 |
|------|------|------|
| `POST /mcp` | **MCP Streamable HTTP** (표준 전송) | Claude Desktop·Code, Cursor 등 MCP 클라이언트 |
| `GET /mcp/info`, `GET /mcp/tools/list`, `POST /mcp/tools/call` | 자체 REST | ChatGPT Custom GPT(OpenAPI Actions), curl 점검 |

표준 클라이언트는 URL 과 API 키만 있으면 됩니다 — 중계 스크립트가 필요 없습니다.

```bash
claude mcp add --transport http aot https://<호스트>/aotmcp/mcp \
  --header "X-API-KEY: <base64 API 키>"
```

`GET /mcp` 는 405 를 돌려줍니다. 서버→클라이언트 SSE 스트림은 제공하지 않습니다
(waitress 를 4스레드로 돌리는 서버라 접속 하나가 스레드를 붙잡으면 도구 호출이
밀립니다). 스펙이 허용하는 동작이며, 서버발 알림이 필요해지면 그때 여는 자리입니다.

REST 를 남겨두는 이유는 일반 요금제의 ChatGPT Custom GPT 가 MCP 서버를 직접
등록할 수 없고 OpenAPI Actions 로만 붙기 때문입니다.

### ChatGPT Custom GPT 연결 { #chatgpt-setup }

위 REST 세 경로(`/mcp/info`, `/mcp/tools/list`, `/mcp/tools/call`)를 **OpenAPI
Action**으로 등록합니다. Custom GPT 생성·Actions 기능은 ChatGPT 유료
요금제(Plus/Team/Enterprise/Pro)에서만 됩니다 — 무료 계정은 이 경로 자체를
쓸 수 없습니다.

1. **API 키 발급** — `설정 > 사용자`에서 본인 계정의 API 키를 새로 만듭니다
   (이름을 "ChatGPT"처럼 구분되게 붙여 두면 나중에 이 연결만 따로 폐기하기
   편합니다). 조회만 시킬 계획이면 발급 시 스코프를 `readonly`로 선택하세요 —
   쓰기 도구 호출 자체가 서버에서 거부되어, Custom GPT 설정 실수로 장치를
   잘못 건드릴 위험이 원천 차단됩니다. 여러 사람이 쓴다면 각자 이름으로
   따로 발급하세요 — 감사 로그에 누가 호출했는지 남고, 유출됐을 때 그
   키 하나만 폐기하면 됩니다.
2. **HTTP 모드가 켜져 있고 외부에서 닿는지 확인** — 서버가
   `--http --port 5700`으로 떠 있어야 하고, ChatGPT 가 그 포트(또는 리버스
   프록시 경로)에 접속할 수 있어야 합니다. 인증 없이 아래를 먼저 열어
   확인하세요(버전·도구 수만 나옵니다):
   ```bash
   curl https://<호스트>:5700/mcp/info
   ```
3. **새 GPT 만들기**: ChatGPT에서 **탐색(Explore GPTs) → 만들기(Create) →
   구성(Configure)** 탭으로 들어갑니다. 이름·설명을 원하는 대로 채우고,
   **지침(Instructions)**에는 최소한 아래 내용을 넣으세요 — 그대로 복사해도
   되고, 농장·현장에 맞게 다듬어도 됩니다:

   ```
   당신은 이 AoT 시스템의 상태를 조회하고, 자문하고, 필요하면 장치 제어
   요청을 등록하는 도우미입니다.

   - listTools 를 습관적으로 호출하지 마세요. 도구 전체 목록은 응답이 커서
     대화 용량을 많이 잡아먹습니다. 처음 한 번만 불러 도구 이름과 인자를
     파악하고, 이후에는 필요한 도구만 바로 호출하세요.
   - 좁은 도구를 먼저 쓰세요. 장치 하나·구역 하나를 물으면 전체 요약형
     도구보다 그 대상만 짚는 도구를 먼저 씁니다.
   - callTool 을 부를 때 arguments 는 항상 JSON 오브젝트를 **문자열로
     인코딩**해서 넣으세요. 예: {"zone_name": "1포장"} 이 아니라
     "{\"zone_name\": \"1포장\"}". 인자가 없으면 "{}".
   - 모든 도구 응답에는 call_state 가 들어 있습니다. 이 값으로만
     성공/실패를 판단하세요(도구별 status 값은 제각각입니다):
       executed / already_executed → 실행됨, 결과를 그대로 전달
       pending_approval            → 아직 미실행, 사람의 승인 대기 안내
       approval_rejected           → 거부됨, 실행하지 말고 자문으로 전환
       approval_expired            → 승인 대기 만료, 다시 요청
       refused / failed            → 거부·오류, 사유를 그대로 전달
   - 상태를 바꾸는 요청이 pending_approval 로 돌아오면, 직접 재시도하지
     말고 사용자에게 웹 승인 화면에서 승인하라고 안내하세요.
   - 답변은 전문 용어 없이 알기 쉽게 요약해서 답하세요.
   ```

4. **액션(Actions) 추가**: 같은 화면 아래 **액션 → 새 액션 만들기**에서
   아래 OpenAPI 스키마를 붙여넣습니다(`<호스트>`를 실제 주소로 바꾸세요):

   ```yaml
   openapi: 3.1.0
   info:
     title: AoT MCP
     version: "1.0.0"
   servers:
     - url: https://<호스트>:5700
   paths:
     /mcp/tools/list:
       get:
         operationId: listTools
         summary: 사용 가능한 도구 목록과 각 도구의 인자 스키마를 받는다.
         responses:
           "200": { description: OK }
     /mcp/tools/call:
       post:
         operationId: callTool
         summary: 도구 하나를 이름과 인자로 호출한다.
         requestBody:
           required: true
           content:
             application/json:
               schema:
                 type: object
                 required: [name]
                 properties:
                   name:
                     type: string
                     description: listTools 가 돌려준 도구 이름
                   arguments:
                     type: string
                     description: >-
                       도구 인자를 JSON 오브젝트로 직렬화한 문자열.
                       예 "{\"zone_name\": \"3포장\"}". 인자가 없으면 "{}".
         responses:
           "200": { description: OK }
   ```

5. **인증 등록**: Authentication → API Key → Auth Type `Custom` → Header name
   `X-API-KEY` → 값에 1번에서 발급한 API 키(base64)를 넣습니다.
6. **⚠️ `arguments`는 반드시 문자열(`string`)로 선언할 것 — object 로 두지
   마세요.** 도구가 100종 넘게 있어 인자 스키마를 OpenAPI 에 전부 선언할 수
   없습니다. `arguments`를 자유형 object 로 두면 ChatGPT Actions 가 값을
   채우지 못하고 **그 키를 통째로 빠뜨립니다**(실사례 2026-08-09:
   `list_devices_in_area` 호출이 `area_name`은 필수인데 요청 바디에
   `arguments` 키 자체가 없어 실패했습니다). 위 스키마처럼 문자열로 선언했다면
   이미 안전하고, 3번의 Instructions 예시도 같은 이유로 그 규칙을 반복합니다.
7. **저장하고 확인**: 공개 범위는 **나만 보기(Only me)**로 두는 것을
   권장합니다. 대화창에서 "지금 상태 브리핑해줘" 처럼 물어봐서 도구 호출과
   응답이 오면 정상입니다.
8. **상태를 바꾸는 도구는 이 경로에서도 즉시 실행되지 않습니다.** 최초 호출은
   `pending_approval` + `confirmation_id`를 반환합니다 — ChatGPT 는 그 값을
   사람에게 보여주고, 사람이 웹 승인 화면에서 승인한 뒤 같은 인자에
   `_confirmation_id`를 채워 **같은 도구를 다시** 호출해야 실제로 실행됩니다.
   Custom GPT 안에서 자동 재승인은 없습니다. 승인 화면은 두 곳에서 볼 수
   있습니다 — 평소에는 스케줄러 페이지(`/scheduler`)를 그대로 쓰면 됩니다
   (맨 위 "승인 대기 중인 제어 요청"). 감사 로그·조언 이력까지 함께 보려면
   전용 페이지(`/api/v1/mcp/review_page`, 메뉴: **AI → MCP 서버 목록 → AI
   요청 및 조언**)로 갑니다 — 승인 목록 자체는 같습니다.

**연결이 안 될 때**

| 증상 | 확인할 것 |
|---|---|
| "unauthorized" / API key 오류 | 5번에서 넣은 키 값에 앞뒤 공백이 섞이지 않았는지, 키가 폐기되지 않았는지 |
| 액션 저장이 안 됨 | 4번 스키마를 한 번에 전체 복사했는지 — 중괄호가 잘리면 저장이 거부됩니다 |
| 매번 "도구를 못 찾겠다"는 식으로 답함 | GPT 가 listTools 를 안 부르고 바로 답하려는 경우 — "먼저 도구 목록부터 확인해줘"로 유도 |
| 조회는 되는데 제어가 안 됨 | 정상입니다 — 쓰기는 항상 사람 승인을 거칩니다(8번) |
| 이름으로 물으면 계속 이상한 답 | `get_system_update_status` 로 버전 확인 — 아래 버전 안내 참고 |

> 이 페이지가 다루는 지도 관련 버그 수정(`get_weather` 이름 조회가 항상
> 같은 도형으로 떨어지던 것, `get_spatial_tree` 필터 무동작, 구역이 계층
> 조회에서 사라지던 것)은 **AoT 앱 v26.08.8 이상**부터 적용됩니다. 연결
> 직후 `get_system_update_status` 도구를 한 번 호출해 설치 버전을 확인하세요
> — 그보다 낮은 버전이면 포장·구역 이름으로 묻는 질문에서 예전처럼 엉뚱한
> 응답이 나올 수 있습니다.

### Claude Desktop 연결

`claude_desktop_config.json`에 추가합니다:

```json
{
  "mcpServers": {
    "aot": {
      "command": "python3",
      "args": ["/opt/AoT/aot/aot_mcp_server.py"]
    }
  }
}
```

> 상태를 바꾸는 도구 호출은 이 서버에서도 곧장 실행되지 않습니다(`aot/ai/services/mcp_safety_gate.py`). 최초 호출은 `pending_approval` + `confirmation_id`로 응답하고, 사용자가 그 대화(또는 스케줄러 페이지 `/scheduler`, 감사 로그까지 보려면 `/api/v1/mcp/review_page`)에서 명시적으로 승인/거부해야 `respond_to_confirmation` 호출로 처리됩니다. 승인 후 같은 인자에 `_confirmation_id`를 붙여 재호출해야 실제로 실행됩니다 — 호출한 AI가 스스로 승인 여부를 판단하거나 대신 답할 수 없습니다. `AOT_MCP_WRITE_ENABLED=0`이면 쓰기 도구 자체가 조언 전용으로 거부됩니다. 유효시간은 두 구간으로 나뉩니다 — 사람이 승인할 때까지 기본 15분(`AOT_MCP_CONFIRM_TTL_SEC`), 승인 이후 실행할 때까지 승인 시점부터 다시 기본 5분(`AOT_MCP_APPROVED_TTL_SEC`). 그래도 제어 도구가 노출되는 서버이므로 신뢰할 수 있는 클라이언트에만 연결하세요.

---

## 관련 페이지

- [환경 제어 자동화](env-control.md)
- [스케줄러](scheduler.md)
- AI 가이드 (전체)
