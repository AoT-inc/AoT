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

## 안전·승인 모델

상태를 바꾸지 않는 **읽기 도구**는 즉시 실행됩니다. **상태를 바꾸는 도구**는 어느 경로로 호출되든 승인 게이트를 거칩니다.

- **승인 필요(변이·물리 제어)**: 장치 제어(`operate_device`, `set_output_state`, `schedule_device_control`), 입력/출력/함수/공지/AI 에이전트/GIS 입력의 생성·수정·삭제, 지도 배치 변경(`set_device_location`, `delete_geo_shape`), 장치 교체(`rebind_device`), `add_schedule`·`add_schedule_batch`, `configure_library_source` 등.
- **승인 불필요(저위험 기록)**: `create_note`, `knowledge_shelve` — 되돌릴 수 있는 개인 메모/미확인 지식으로 즉시 저장되며, 확정 전까지 권위 없는 정보로 취급됩니다.

승인이 필요한 동작은 즉시 적용되지 않습니다. **인앱 어시스턴트**에서는 채팅에 **승인 카드**로 제시되어 사용자가 승인해야 실제로 실행됩니다. **외부 MCP 서버**에서는 `pending_approval` 응답(대기열)으로 나가고, 사용자가 그 confirmation_id를 명시적으로 승인/거부해야 처리됩니다 — 어느 경로든 거부하면 아무 변경도 일어나지 않습니다.

웹 승인 페이지(`AI → MCP 서버 목록 → AI 요청 및 조언`)에서 승인하면 **서버가 그 자리에서 실행**합니다. 사람이 승인한 뒤 다시 AI 에게 알려줘야 실행되던 왕복을 없앤 것으로, 실행은 승인 화면에 표시된 인자 그대로만 이루어집니다. 이후 AI 가 같은 confirmation_id 로 재호출하면 재실행 없이 그때의 결과가 돌아옵니다. 밸브·펌프처럼 되돌릴 수 없는 물리 제어만 승인 화면에서 한 번 더 확인을 받습니다.

---

## 지식 라이브러리 (Knowledge Library) { #knowledge-library }

`AI -> 라이브러리`(`/ai/library`) 페이지에서 AI 답변의 근거가 되는 **컨텍스트 소스**를 등록합니다. 문서(PDF·텍스트), 웹 URL, REST API, 내부 쿼리를 소스로 추가할 수 있습니다.

### 지식 다이제스트 파이프라인

문서·웹 URL처럼 긴 산문형 소스는 등록 시 **한 번만** 전처리됩니다.

1. 소스를 여러 **청크(chunk)**로 분할합니다.
2. 각 청크를 LLM으로 **요약(digest) + 키워드 추출**하여 `ai_knowledge_chunk` 테이블에 캐시합니다.
3. 질의 시점에는 LLM 호출 없이 **DB 조회 + 결정론적 검색**만 수행합니다 → 답변이 빠르고 비용이 낮습니다.

각 청크는 컨텍스트 레코드와 동일한 **3단계 신뢰 파이프라인**(`system_generated` → `pending` → `user_confirmed`)을 재사용하므로, 문서형 지식도 같은 검토 UX로 승인·관리합니다.

### 멀티사이트 스코핑 (facility_id)

각 청크는 소스의 `facility_id`(사이트/시설 경계)를 함께 저장합니다. 지식 검색은 이 값으로 필터링됩니다.

- **사이트 A에 업로드한 문서는 사이트 B의 답변에 절대 노출되지 않습니다.**
- `facility_id` 없이 검색하면 라이브러리 지식이 **모두 제외**됩니다(교차-사이트 유출을 막기 위한 의도된 동작이며, 단순 무필터가 아닙니다).

이 스코핑은 여러 시설을 한 시스템에서 운영할 때 각 시설의 매뉴얼·재배 지침이 서로 섞이지 않도록 보장합니다.

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
Action**으로 등록합니다.

1. **API 키 발급** — `설정 > 사용자`에서 본인 계정의 API 키를 새로 만듭니다
   (이름을 "ChatGPT"처럼 구분되게 붙여 두면 나중에 이 연결만 따로 폐기하기
   편합니다). 조회만 시킬 계획이면 발급 시 스코프를 `readonly`로 선택하세요 —
   쓰기 도구 호출 자체가 서버에서 거부되어, Custom GPT 설정 실수로 장치를
   잘못 건드릴 위험이 원천 차단됩니다.
2. **HTTP 모드가 켜져 있고 외부에서 닿는지 확인** — 서버가
   `--http --port 5700`으로 떠 있어야 하고, ChatGPT 가 그 포트(또는 리버스
   프록시 경로)에 접속할 수 있어야 합니다. 인증 없이 아래를 먼저 열어
   확인하세요(버전·도구 수만 나옵니다):
   ```bash
   curl https://<호스트>:5700/mcp/info
   ```
3. ChatGPT에서 **Explore GPTs → Create → Configure → Actions → Create new
   action**으로 들어가 아래 OpenAPI 스키마를 붙여넣습니다(`<호스트>`를 실제
   주소로 바꾸세요):

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

4. **인증 등록**: Authentication → API Key → Auth Type `Custom` → Header name
   `X-API-KEY` → 값에 1번에서 발급한 API 키(base64)를 넣습니다.
5. **⚠️ `arguments`는 반드시 문자열(`string`)로 선언할 것 — object 로 두지
   마세요.** 도구가 100종 넘게 있어 인자 스키마를 OpenAPI 에 전부 선언할 수
   없습니다. `arguments`를 자유형 object 로 두면 ChatGPT Actions 가 값을
   채우지 못하고 **그 키를 통째로 빠뜨립니다**(실사례 2026-08-09:
   `list_devices_in_area` 호출이 `area_name`은 필수인데 요청 바디에
   `arguments` 키 자체가 없어 실패했습니다). 위 스키마처럼 문자열로 선언하고,
   Custom GPT 의 Instructions 에 "callTool 을 부를 때 arguments 는 항상 JSON을
   문자열로 인코딩해서 보내라"를 명시하세요.
6. **상태를 바꾸는 도구는 이 경로에서도 즉시 실행되지 않습니다.** 최초 호출은
   `pending_approval` + `confirmation_id`를 반환합니다 — ChatGPT 는 그 값을
   사람에게 보여주고, 사람이 웹 승인 페이지(`/ai/mcp_review`)에서 승인한 뒤
   같은 인자에 `_confirmation_id`를 채워 **같은 도구를 다시** 호출해야
   실제로 실행됩니다. Custom GPT 안에서 자동 재승인은 없습니다.

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

> 상태를 바꾸는 도구 호출은 이 서버에서도 곧장 실행되지 않습니다(`aot/ai/services/mcp_safety_gate.py`). 최초 호출은 `pending_approval` + `confirmation_id`로 응답하고, 사용자가 그 대화(또는 웹 승인 페이지 `/ai/mcp_review`)에서 명시적으로 승인/거부해야 `respond_to_confirmation` 호출로 처리됩니다. 승인 후 같은 인자에 `_confirmation_id`를 붙여 재호출해야 실제로 실행됩니다 — 호출한 AI가 스스로 승인 여부를 판단하거나 대신 답할 수 없습니다. `AOT_MCP_WRITE_ENABLED=0`이면 쓰기 도구 자체가 조언 전용으로 거부됩니다. 유효시간은 두 구간으로 나뉩니다 — 사람이 승인할 때까지 기본 15분(`AOT_MCP_CONFIRM_TTL_SEC`), 승인 이후 실행할 때까지 승인 시점부터 다시 기본 5분(`AOT_MCP_APPROVED_TTL_SEC`). 그래도 제어 도구가 노출되는 서버이므로 신뢰할 수 있는 클라이언트에만 연결하세요.

---

## 관련 페이지

- [환경 제어 자동화](env-control.md)
- [스케줄러](scheduler.md)
- [AI 가이드 (전체)](../ai_guide.ko.md)
