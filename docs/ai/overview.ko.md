# AI 기능 개요

AoT는 MCP(Model Context Protocol) 기반 AI 에이전트를 통해 현장(온실·노지·공원·건물 등 장치가 공간에 놓인 곳이면 어디든)의 환경을 관찰·진단·제어합니다. AI는 시스템을 보조하는 역할로, 장비를 움직이는 동작은 사용자 승인 후 실행됩니다(설정만 바꾸는 편집은 예외 — 아래 안전·승인 모델 절 참고).

---

## 시작하기: 스위치가 두 개입니다 { #enable-and-start }

AI를 쓰려면 서로 다른 자리의 스위치 두 개를 켜야 합니다. 하나로 합치지 않은 이유가 있습니다.

| 스위치 | 자리 | 켜면 생기는 일 |
|--------|------|----------------|
| **AI 서비스 사용** | 설정 > 일반 | AI 메뉴가 내비게이션에 나타나고 AI 페이지에 들어갈 수 있습니다. 채팅·조언 요청이 동작합니다. |
| **내장 AI 작동** | AI > 연결 > 내장 AI | 사람이 부르지 않아도 도는 작업이 시작됩니다 — 주기 요약, 컨텍스트 브로드캐스트, 날씨 요약, MCP 헬스체크, 실시간 알림. |

순서는 **설정에서 사용 → AI > 연결 페이지에서 모델(에이전트) 등록 → 작동 시작**입니다.

Claude Desktop 같은 **내 AI 앱으로 연결**하는 경로는 이 스위치와 따로 동작합니다. 설정 > 일반의 외부 MCP 접속 허용과 사용자별 접속 키만 있으면 되고, 내장 AI 를 꺼 두어도 됩니다. AI > 연결 페이지 맨 위에서 두 가지 상태를 보고 각 화면으로 이동할 수 있습니다.

이 "외부 MCP 접속 허용" 토글(**설정 > 일반 > 외부 MCP 서버 사용**, `AIGlobalSettings.mcp_http_enabled`)은 캐시되지 않고 MCP 서버로 들어오는 요청마다 매번 새로 확인됩니다 — 끄면 재시작 없이 그 즉시 모든 외부 MCP 호출이 `503`으로 거부되고, 다시 켜면 그만큼 빠르게 되살아납니다.

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
               tool_execution.py — 승인 게이트 + 감사 로그
                                    ↓
      도구 레지스트리 (tool_registry.py) — 도구 선언의 단일 소스.
      이 디스패치 맵이 호출을 실제 핸들러로 연결합니다
                                    ↓
                        AoT 시스템 (Daemon / InfluxDB / SQLite)
```

두 경로 모두 같은 게이트(`aot/tools/tool_execution.py`)를 거쳐 실행되고 같은
도구 레지스트리(`aot/tools/tool_registry.py`)에서 도구 선언을 가져오므로, 인앱
어시스턴트와 외부 MCP 클라이언트 사이에 승인 규칙도 도구 목록도 절대 어긋나지 않습니다.

---

## MCP 도구 목록

외부 MCP 서버와 내부 `mcp_aot` 엔진이 노출하는 도구입니다. 읽기 도구와 설정 편집 도구는 즉시 실행되고, 제어·일정·활성화 도구는 승인 게이트를 거칩니다 — 인앱 어시스턴트에서는 채팅의 승인 카드로, 외부 MCP 서버에서는 대기열(`pending_approval` + `respond_to_confirmation`)로 처리됩니다(자세한 내용은 아래 "MCP 서버 실행" 참고).

### 두 층: `tools/list` vs. 서랍 { #tool-drawers }

도구 목록은 한 장에 전부 실리지 않습니다. 전량을 그대로 노출하면 대화가 시작되기도 전에 약 2만 토큰이 나가므로, `tools/list`는 두 층만 돌려주고 나머지는 필요할 때 서랍을 열어 꺼내 씁니다.

- **상시 노출(core) — 27개.** 다음 한 걸음을 떼는 데 없어서는 안 되는 좁은 집합입니다 — 이름 해석(`resolve_target`), 장치 조회, 값 읽기, 즉시 제어, 승인 대기열 등(`aot/tools/tool_registry.py`의 `_TIER_ASSIGNMENT` 표).
- **메타 도구 4개, core와 함께 항상 노출:** `open_drawer`(서랍 하나의 도구 목록, 인자 없이 부르면 전체 서랍 인덱스), `get_tool_detail`(도구 하나의 완전한 스키마를 이름으로 조회), `use_tool`(서랍 도구를 이름으로 실제 **실행** — 서랍 도구를 실행하는 유일한 방법이며, `open_drawer`·`get_tool_detail`은 정의만 돌려줍니다), `respond_to_confirmation`(대기 중인 확인을 승인/거부).
- **나머지 101개는 목적별 8개 서랍**에 들어 있고, `open_drawer`를 불러야 비로소 보입니다: `device`(장치 조작·상태), `measurement`(센서·환경·날씨·에너지), `function`(함수·제어기·시퀀스), `schedule`(일정·예약), `record`(노트·공지·지식·조언), `space`(지도·구역·시설·구획), `definition`(장치 정의 CRUD), `system`(AI 설정·시스템 상태·진단·화면).

서랍은 이제 선택 사항입니다. 외부 MCP 연결은 서랍 없이 키의 도구 묶음(다음 절) 전체를 목록으로 받습니다 — 이것이 기본입니다. `AOT_MCP_TOOL_TIERING=1`(또는 `true`·`yes`·`on`) 이면 서랍 구조로 돌아가며, 이때도 키의 묶음 안에서 동작하고 `open_drawer`·`get_tool_detail`·`use_tool` 이 다시 목록에 나옵니다. 앱 안 AI 비서의 내장 도구 목록은 서랍 구조를 그대로 씁니다(`AOT_AI_BUILTIN_MCP_TIERING`, 기본 켬).

### API 키별 도구 묶음 { #tool-profiles }

API 키마다 외부 AI 앱에 보여 줄 도구의 범위, 곧 **도구 묶음**을 고릅니다. 키의 권한과는 다른 설정입니다 — 권한은 그 키로 무엇을 해도 되는지를, 묶음은 무엇을 목록에 싣는지를 정합니다.

- **운영**(새 키의 기본값) — 날마다 하는 일: 장치·센서·날씨·일정·노트·구획 조회, 장치와 함수 제어, 함수 옵션·시퀀스 운전 시간·기존 시퀀스 단계 조정, 일정 등록, 노트·공지·조언·구획 단계 기록.
- **운영 + 설정** — 설정 도구를 더합니다: 장치 정의, 자동화와 시퀀스 단계의 생성·삭제, 구획과 프로그램의 생성·편집, 지도 배치, 대시보드와 탭, AI 설정, 보관 문서와 라이브러리 소스 관리. 대화마다 AI 에 보내는 도구 목록이 훨씬 길어지므로 설정 작업을 하는 키에만 고르세요.

`설정 > 사용자`의 API 키 단락(**AI 도구**)에서 키를 발급할 때 고르고, 나중에 같은 화면에서 키를 다시 발급하지 않고 바꿀 수 있습니다. 바꾸는 데는 키 폐기와 같은 권한(사용자 편집)이 필요하고, 바꾼 기록은 감사 로그에 남습니다. 새 키 발급은 여기에 더해 최근 로그인을 요구합니다. 이미 연결된 앱은 다시 연결해야 새 목록을 볼 수 있습니다. 서랍을 켜 둔 경우 서랍에도 그 키의 묶음에 든 도구만 들어 있습니다.

운영 묶음 키가 설정 도구를 부르면 서버는 호출을 거절하고(`call_state: refused`, `reason_code: tool_profile`), 누가 어디서 바꾸는지 메시지로 알려 줍니다. 승인 대기열에는 들어가지 않습니다. `get_tool_detail` 과 `open_drawer` 도 묶음 밖 도구·서랍을 "모르는 도구"나 빈 서랍으로 답하지 않고 같은 메시지로 답합니다. 키의 권한 때문에 어차피 쓸 수 없는 도구(예: 읽기 전용 키의 쓰기 도구)라면 바꿔도 소용이 없으므로 바꾸라는 안내를 붙이지 않습니다. 다른 거절(조언 전용 모드·키의 역할·승인)에도 묶음 전환을 권하지 않습니다 — 조언 전용 모드는 어떤 묶음으로도 바뀌지 않는 서버 전체 설정입니다. 묶음 밖 도구의 승인 대기 항목은 도구 이름 없이(중립 표시와 분야만) 보이며, 그 키로 거절은 할 수 있지만 승인은 할 수 없습니다. 서버 안내문과 `get_system_brief` 도 AI 에게 지금 묶음을 알려 주므로, AI 는 "할 수 없다" 대신 묶음을 바꾸라고 안내할 수 있습니다.

- 묶음이 생기기 전에 발급된 키는 업그레이드 뒤 처음 기동할 때 한 번 배정됩니다: 최근 90일 안에 키 소유자가 설정 도구를 부른 적이 있으면 운영 + 설정, 나머지는 운영입니다. 감사 로그에는 어느 키로 불렀는지가 남지 않으므로 **사람 단위**로 정합니다 — 한 사람의 키는 모두 같은 값을 받습니다. 필요하면 배정 뒤에 키마다 바꾸세요.
- 앱 안의 AI 비서는 묶음의 제한을 받지 않습니다. 내장 AI 자신의 서비스 계정 키(앱 안의 장치 제어가 이 키를 거칩니다)도 마찬가지이며, 화면은 이 계정의 키에 묶음 선택을 보여 주지 않습니다.
- `knowledge_search` 는 찾아낸 내용을 `knowledge_shelve` 로 보관하라는 안내를 그것을 쓸 수 있는 연결(운영 + 설정 묶음, 또는 앱 안의 AI 비서 — 노트 편집 권한이 있을 때)에만 붙입니다.
- `set_output_state`·`list_available_devices` 는 API 키의 목록에서 빠졌습니다 — 같은 일은 `operate_device`·`get_device_list`·`search_devices` 가 합니다.
- `AOT_MCP_TOOL_PROFILES=0` 이면 묶음을 끕니다(예전처럼 모든 키가 전체 목록을 봅니다). `AOT_MCP_DEFAULT_TOOL_PROFILE` 은 인증 없이 도는 서버의 묶음입니다(기본 `operations`).

### 이름으로 부르기, 여러 대상 한 번에, 인자 먼저 확인 { #tool-arguments }

- **id 대신 이름.** `get_output_state`·`get_device_measurements`·`get_sensor_detail`·`get_sensor_reading` 은 장치 이름을, `get_zone_sensor_summary`·`list_plots` 는 구역·부지 이름을, `get_plot` 은 재배 중인 구획의 이름·작물·품종을 받습니다. id 도 그대로 되고 먼저 확인합니다. 이름이 여러 대상에 걸리면 하나를 고르지 않고 `needs_disambiguation` 과 함께 어디에 있는지로 구분한 후보를 돌려줍니다.
- **여러 대상을 한 번에**(최대 10개): `device_ids`(`get_output_state`·`get_sensor_reading`), `loc_ids`(`get_sensor_detail`), `plot_ids`(`get_plot`), `target_names`(`search_notes`), `zone_ids`(`get_zone_sensor_summary`). 응답은 `{count, results}` 이고, 대상마다 한 번 부른 것과 같은 모양입니다.
- **인자를 먼저 확인합니다.** 쓰기 도구는 권한·승인 단계보다 먼저 인자를 봅니다. 빠진 인자, 맞는 이름의 오타로 보이는 인자, `modify_function_options` 의 없는 옵션 키나 틀린 값은 `reason_code: invalid_arguments` 와 맞는 이름 목록으로 돌아옵니다(`get_function_detail` 이 함수의 옵션 키·지금 값·범위를 미리 보여 줍니다. `temperature` 같은 범위는 키가 아니고 그 아래·위 끝 키를 씁니다) — 조언 전용 모드에서도 같고, 그 키로는 어차피 실행할 수 없는 호출이면 그 사실도 함께 알려 줍니다. 그 밖의 모르는 인자는 무시하고 `_ignored_arguments` 로 알려 줍니다.
- `get_sensor_reading` 의 스키마에 장치 id 목록을 더는 싣지 않습니다. 장치가 늘어도 도구 목록이 커지지 않습니다.
- `search_devices` 는 이름이 같은 장치를 표시합니다(`same_name_count`·`where`·`same_name_groups`).
- `get_spatial_tree` 를 `depth` 없이 부르면 모든 깊이의 부지·구역·시설과 곳마다 장치 수를 줍니다. 장치까지 보려면 `depth` 를 줍니다.
- 구획 단계: 이미 일어난 전환은 `confirm_plot_stage`, 아직 오지 않은 경계를 옮기는 것은 `reschedule_plot_stage` 입니다. `confirm_plot_stage` 는 `get_plot` 이 그 단계를 제안하지 않았으면 날짜(`started_on`)가 필요합니다.
- 도구 설명은 짧게 줄였습니다. 결과를 읽는 법은 응답의 `_reading` 칸에 실리며, AI 는 그것을 따릅니다.

아래 표들은 어느 층에 있는지와 무관하게 도구를 설명합니다 — **서랍** 칸은 `tools/list`에 없어서 먼저 열어야 하는 도구를 표시합니다. 인자까지 포함한 전체 도구 목록(서랍 안 도구 포함)은 AI 에이전트 가이드(`docs/ai_guide.md`)에 있으니 그쪽을 참고하세요 — 이 문서에서는 표를 장황하게 복제하지 않습니다.

### 관찰·조회 (읽기 — 즉시 실행)

| 도구 | 설명 | 서랍 |
|------|------|------|
| `get_spatial_tree` | 모든 부지·구역·시설과 곳마다 장치 수(`depth` 를 주면 장치까지) | — (core) |
| `resolve_target` | 장치/구역 이름을 정확한 엔티티로 해석 — 컨테이너(하위 구역 보유)인지 미리 확인. 같은 이름이 서로 다른 곳·장치 여럿에 있으면 하나를 고르지 않고 후보와 각 위치, 그 하나만 가리키는 이름(있을 때)을 돌려줌 — 없으면 후보의 `target_id` 를 넘긴다(`add_schedule`·`edit_schedule`·`create_note` 가 받음). 안팎으로 겹친 같은 이름은 한 곳으로 보아 바깥을 가리키고, 안쪽은 `also_inside` 로 알림 | — (core) |
| `get_device_list` | 등록된 전체 장치(입력·출력·카메라) 목록 | — (core) |
| `search_devices` | 이름·유형 키워드로 장치 검색 | — (core) |
| `get_sensor_detail` | 센서 시계열 이력 (min/max/avg 통계) | — (core) |
| `get_weather` | 포장·구역의 현재 기상 (기온·습도·풍속·강수) | — (core) |
| `get_energy_report` | 기간·구역별 에너지 사용량 리포트 | `measurement` |
| `get_cumulative_status` | EnvCoordinator DLI(일적산광량)·GDD(누적온도) 상태 | `measurement` |
| `search_notes` | 구역·장치에 부착된 노트/메모/작업기록 조회 | — (core) |
| `get_note_attachment` | 노트에 첨부된 사진을 실제 이미지로 조회 (한 번에 한 장) | `record` |
| `list_notices` | 공지 게시판 글 목록 | `record` |
| `get_system_update_status` | 설치 버전 vs GitHub 최신 릴리스 비교 | `system` |
| `list_available_devices` | AI 판단 대상 장치 목록 (네이티브 브리지) | — (인앱 전용) |
| `get_sensor_reading` | 센서 하나 이상의 최신값, id 또는 이름으로 (네이티브 브리지) | — (core) |

### 기록·작업

| 도구 | 설명 | 승인 | 서랍 |
|------|------|------|------|
| `create_note` | 날짜 없는 메모/노트를 대상 엔티티에 부착해 즉시 저장 | 불필요 | — (core) |
| `add_schedule` | 사람이 수행할 작업 일정(제초·점검·청소 등) 등록 | 불필요 — `config_only`: Draft 상태의 스케줄러 잡만 만들 뿐 장비는 움직이지 않습니다. 사람이 나중에 스케줄러 화면에서 확인하는 것은 이와 별개의 절차입니다. | — (core) |
| `add_schedule_batch` | 여러 대상(구역별 등)의 일정을 한 번의 호출로 일괄 등록 | 불필요 — `add_schedule`과 같은 `config_only` 이유 | `schedule` |

### 제어 (사용자 승인 필요)

| 도구 | 설명 | 서랍 |
|------|------|------|
| `operate_device` | 밸브·펌프·조명 등 즉시 물리 제어 | — (core) |
| `set_output_state` | 출력 장치 on/off (선택적 지속시간, 네이티브 브리지) | `device` |
| `schedule_device_control` | 특정 시각 1회성 장치 제어 예약 | `schedule` |

> 인앱 어시스턴트에서는 위 제어 도구 호출이 승인 카드로 확인을 받은 뒤 실행됩니다. 외부 MCP 서버로 직접 호출할 때도 동일하게 승인을 거칩니다 — 최초 호출은 실행되지 않고 `pending_approval`(대기 중인 confirmation_id)로 응답하며, 사용자가 그 confirmation_id를 채팅에서 명시적으로 승인/거부해야 `respond_to_confirmation` 호출(또는 웹 승인 페이지 클릭)로 처리되고, 그 뒤 같은 인자에 `_confirmation_id`를 붙여 재호출해야 실제로 실행됩니다. 자세한 흐름은 아래 "MCP 서버 실행"을 참고하세요. `add_schedule`·`add_schedule_batch`는 이 게이트를 거치지 않습니다 — 위 기록·작업 표를 참고하세요.

### 시퀀스 (설정 편집은 승인 불필요)

[시퀀스](../Functions.ko.md#trigger-sequence)는 여러 출력 장치를 정해진 순서로 돌리는 기능으로, 밸브가 차례로 열리고 펌프가 전 구간을 도는 관수가 대표적인 형태입니다. 아래 도구로 시퀀스를 읽고 구성합니다. 이 절의 도구 넷(아래 셋과 `create_sequence_function`)은 모두 `function` 서랍에 있습니다.

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

상태를 바꾸는 호출이 **적용되지 않았으면**(`executed`·`already_executed` 가 아닌
모든 경우, 또는 승인 시점 실행이 실패한 경우) 응답에 `performed: false` 와 짧은
`_reading` 이 함께 실립니다. 사용자에게 적용되지 않았다고(`pending_approval` 이면
아직 사람의 승인을 기다린다고) 분명히 말하고, 대상은 id 가 아니라 이름으로
말하라는 내용입니다. 몇몇 도구는 오류 대신 자기 `status` 단어로 "하지 않음" 을
알립니다. 상태를 바꾸는 도구에서는 이것도 적용되지 않은 것으로 봅니다:
`refused`(호출 상태 `refused`), `rejected`·`quota_exceeded`·`not_found`·
`target_not_found`·`orphan_archive`·`needs_disambiguation`·`ambiguous`·
`unavailable`(호출 상태 `failed`). 그래서 호출 품질 지표의 거부율은 권한·정책·
사람의 거부만 셉니다.

장치 명령(`operate_device`·`set_output_state`·`schedule_device_control`)은
예외입니다. 명령이 이미 장치에 닿았을 수 있는 실패 — 시간 초과, 통신 오류,
보낸 뒤의 제어기 오류 — 이면 `performed` 가 `false` 가 아니라 `"unknown"`
입니다. 시간 초과는 호출한 쪽이 기다리기를 그만뒀다는 뜻일 뿐이므로, 다시
부르기 전에 현재 상태를 확인하고(`get_output_state`, 예약이면
`search_schedule`) 확인되기 전에는 됐다고도 안 됐다고도 말하지 않습니다.
아무것도 보내기 전에 멈춘 실패(없는 장치, 잘못된 인자, 거부)는 그대로
`performed: false` 입니다. 앱 안의 AI 도 같은 결과를 같은 뜻으로 읽고, 웹 승인
화면은 단순 실패 대신 "명령을 보냈지만 적용 여부를 확인하지 못했습니다 — 장치
상태를 확인하세요" 를 보여 줍니다.

함수·입력을 켜거나 끄면 설정을 먼저 저장한 뒤 실행 중인 제어기에 알립니다.
제어기가 확인해 주지 않으면(꺼져 있거나 바쁠 수 있음) 응답은 저장된 값을 그대로
싣고 호출 상태도 `executed` 로 남지만 `performed` 는 `"unknown"` 입니다. 지금
켜졌다·꺼졌다고 말하지 말고, 설정은 저장됐지만 실제 동작에 반영됐는지는 아직
확인되지 않았다고 말합니다. `get_active_functions_summary` 는 저장된 설정만
보여 주므로 이것을 확인해 주지 못합니다.

`submit_advice` 응답도 요청한 변경이 아니라 제안만 저장됐다고 밝힙니다. 이름
하나가 여러 곳이나 장치에 걸리면 그 후보마다 `where` 가 있어 id 없이 구분할 수
있습니다(거리 조회의 후보에는 없습니다).

### 인앱 어시스턴트 확장 도구

위 도구 외에 인앱 AI 어시스턴트는(그리고 그중 `core`인 것은 외부 MCP 서버도 직접) 엔티티 조립·자동화·지식까지 다루는 확장 도구를 추가로 사용합니다. 대부분의 상태 변경 도구는 승인이 필요하지만, 아래 `config_only`로 표시한 것은 필요하지 않습니다 — 안전·승인 모델 절 참고.

- **입력/출력 관리**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **함수(자동화)**: `get_function_list`, `get_function_detail`, `create_function`, `create_sequence_function`(`config_only`), `modify_function_options`(`config_only`; 트리거에는 통하지 않음 — 위 시퀀스 절 참고), `activate_function`·`deactivate_function`·`delete_function`, 그리고 시퀀스 도구 `configure_sequence_day`·`modify_sequence_step`·`modify_sequence_schedule`(모두 `config_only`)
- **일정 원장**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **지도(GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`, `list_unbound_slots`(장치가 없는 자리), `rebind_device`(한 장치의 지도 자리 전부를 다른 장치로)
- **GIS 입력(지도 레이어)**: `list_gis_inputs`, `create_gis_input`(`config_only` — 항상 비활성 상태로 생성), `modify_gis_input`·`delete_gis_input`·`activate_gis_input`(승인 필요) — VWorld/Google/OpenWeather 등 지도 레이어 제공자 관리
- **설비/시설 조회**: `get_facility_capacity`(시설 냉난방 용량·체적·환기·관수 설계 요약), `get_map_equipment`(지도에 그린 설비의 구역별 관수 설계 요약, 스프링클러/점적 구분), `get_map_equipment_detail`(개별 스프링클러 위치·간격·반경, 배관별 상세 — 요약으로 부족할 때만)
- **공지 게시판**: `create_notice`·`modify_notice`·`delete_notice`
- **AI 에이전트 관리**: `list_ai_agents` — 이 도구는 `core`라 인앱뿐 아니라 외부 MCP 서버의 `tools/list`에도 이미 실립니다; `list_ai_entries`, `create_ai_agent`(`config_only`), `modify_ai_agent`·`delete_ai_agent`(승인 필요)
- **지식 라이브러리**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **문서 스토리지 티어**: `get_storage_tier_status`, `search_archives`, `get_archived_document`, `archive_note`·`restore_note_from_archive`·`delete_archive`·`set_document_tier` — 오래된 노트를 위한 선택적 콜드 아카이브입니다. `archive_note`는 노트 내용을 압축된 장기 보관소에 복사하고 tier 3로 표시할 뿐, 원본 노트는 그대로 남습니다. `delete_archive`는 그 아카이브 사본만 지우며 노트 자체는 건드리지 않습니다. 이 기능엔 별도 화면이 없습니다 — AI 도구로만 씁니다.
- **진단·기타**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> 도구의 단일 정본은 `aot/tools/tool_registry.py`입니다. 도구가 추가·변경되면 이 문서보다 그 파일이 우선합니다. 인자까지 포함한 전체 도구 목록(서랍 안 도구 포함)은 AI 에이전트 가이드(`docs/ai_guide.md`)를 참고하세요.

---

## 장치별 AI 판단 포함 여부 { #device-ai-toggle }

`설정 -> 입력` / `설정 -> 출력`의 각 장치 설정 모달에는 **AI 판단 포함**(Include in AI Judgment) 토글이 있습니다.

- 켜짐(기본값): 해당 입력/출력이 AI 판단·제어 도구(공간 트리, 장치 조회, 센서·제어 도구 등)에 노출됩니다.
- 꺼짐: 해당 장치는 위 도구들의 조회·제어 대상에서 제외됩니다. 민감한 장치나 AI가 다루면 안 되는 장치를 개별적으로 숨길 때 사용하세요.

신규 입력/출력은 기본적으로 켜진 상태(`is_ai_enabled=True`)로 생성됩니다.

---

## 안전·승인 모델 { #safety-approval-model }

상태를 바꾸지 않는 **읽기 도구**는 즉시 실행됩니다. 쓰기 도구는 둘로 나뉩니다.

- **승인 필요(변이·물리 제어)**: 장치 제어(`operate_device`, `set_output_state`, `schedule_device_control`), 입력/출력/함수/공지의 생성·수정·삭제, `modify_gis_input`·`delete_gis_input`·`activate_gis_input`, `modify_ai_agent`·`delete_ai_agent`, 지도 배치 변경(`set_device_location`, `delete_geo_shape`), 장치 교체(`rebind_device`), `configure_library_source` 등.
- **config-only 쓰기(승인 면제)**: `add_schedule`, `add_schedule_batch`, `create_gis_input`, `create_ai_agent`, `create_program`, `modify_program`, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day`. 이들은 그 자체로는 장비를 움직이지 않으므로 승인 없이 즉시 저장됩니다 — 대부분(`create_gis_input`, `create_ai_agent`, 시퀀스 도구 등)은 만들어진 결과물이 항상 **비활성 상태**이고, 그 결과물을 실제로 켜는 별도의 활성화 단계가 따로 있으며 그 단계는 여전히 승인 대상입니다. 예를 들어 `create_gis_input`은 즉시 저장되지만 `activate_gis_input`(승인 필요)을 거쳐야 켜지고, 시퀀스의 시간표는 자유롭게 편집할 수 있지만 실제로 도는 것은 `activate_function`(승인 필요)을 지난 뒤입니다. `create_note`·`knowledge_shelve`는 **기록 쓰기**입니다 — 역시 승인 없이 저장되고 활성화 단계가 없으며, 지식은 사람이 확인하기 전까지 미확인·비권위 정보로 다룹니다(아래 AI 지식 절 참고). 그래도 쓰기이므로 웹 노트 화면과 같은 설정 편집 권한이 필요하고, 읽기 전용 키와 조언 전용 모드에서는 거부되며, 그룹 범위를 따릅니다. 승인 면제가 권한 면제는 아닙니다. 인앱 어시스턴트와 MCP 모두, config-only 를 포함한 모든 쓰기는 요청한 사람에게 그 권한이 있을 때만 실행되고(노트·지식과 지도 편집 — 지도 도형 삭제·장치 배치, 웹 지도 편집과 같음 — 은 설정 편집 권한, 구획·단계 기록·구획 자원·작기 프로그램·구획 일지는 웹 구획 화면과 같은 작기 편집 권한, 나머지는 제어 권한 — 기본 역할로는 Monitor·Guest·Kiosk 는 불가), 대상을 id 로 주든 이름으로 주든 그 사람의 그룹 범위 안에서만 실행됩니다. 그룹 판정은 인자만이 아니라 도구가 **실제로 바꾸는 대상**(찾아낸 장치·함수·일정·단계)에서 하므로, 이름으로 지목하거나 일정·단계 id 를 주거나 다른 그룹 자원을 글 속에 적는 것으로는 피할 수 없습니다. 대기 중인 요청을 승인하려면 그 요청과 같은 권한이 필요합니다(구획 요청은 작기 편집, 지도 편집은 설정 편집, 나머지는 제어 — 웹과 `respond_to_confirmation` 모두). 승인자가 대상 그룹 밖이면 요청은 실행되지 않고, 결정할 수 있는 다른 사람을 위해 대기 목록으로 돌아갑니다. 예약 작업은 실행될 때마다 그 책임자(만든 사람, AI 가 제안한 예약은 승인한 사람)의 권한과 그룹으로 다시 확인합니다 — 그사이 권한이나 그룹을 잃었으면 실행하지 않고 실패로 기록합니다. 뒤에 사람이 없는 백그라운드 AI 작업(주기 요약 등)은 예외입니다.

승인이 필요한 동작은 즉시 적용되지 않습니다. **인앱 어시스턴트**에서는 채팅에 **승인 카드**로 제시되어 사용자가 승인해야 실제로 실행됩니다. **외부 MCP 서버**에서는 `pending_approval` 응답(대기열)으로 나가고, 사용자가 그 confirmation_id를 명시적으로 승인/거부해야 처리됩니다 — 어느 경로든 거부하면 아무 변경도 일어나지 않습니다.

웹 요청 화면(`AI → 요청`)에서 승인하면 **서버가 그 자리에서 실행**합니다. 사람이 승인한 뒤 다시 AI 에게 알려줘야 실행되던 왕복을 없앤 것으로, 실행은 승인 화면에 표시된 인자 그대로만 이루어집니다. 이후 AI 가 같은 confirmation_id 로 재호출하면 재실행 없이 그때의 결과가 돌아옵니다. 밸브·펌프처럼 되돌릴 수 없는 물리 제어만 승인 화면에서 한 번 더 확인을 받습니다.

**대시보드 위젯**(`aot/widgets/widget_mcp_review.py`, `js/common/aot-mcp-approval.js`)에서도 같은 승인 대기열을 다룰 수 있습니다. 단건 또는 여러 건을 한 번에 승인·거부할 수 있고, **수정 후 승인**(저장된 인자를 고쳐서 실행)도 지원합니다. 물리 제어는 여기서도 한 번 더 확인을 받습니다.

---

## AI 기록 { #ai-records }

**AI → 기록**(`/ai/manage`)은 AI 가 한 일을 되돌아보는 곳입니다. 탭은 **도구 호출**, **대화**, **오류 보고**, **호출 품질** 네 개입니다.

### 호출 품질 { #call-quality }

**호출 품질** 탭은 연결된 AI 가 도구를 어떻게 써 왔는지 요약합니다. 도구 호출 탭과 같은 기록으로 계산하므로 따로 저장하는 것이 없고, 이 시스템 밖으로 나가는 것도 없습니다.

기간(24시간·7일·30일)과, 필요하면 연결 방식(HTTP MCP, 이 컴퓨터의 MCP, REST API, 내장 AI)을 고릅니다. 한 줄에 숫자 하나씩 보입니다.

- **호출 묶음** — 한 대화에서 90초 안쪽 간격으로 이어진 호출들입니다. 서버는 질문이 어디서 끝나는지 모르므로 묶음은 질문의 근사치일 뿐입니다. 묶음당 호출 수(중앙값·90%)와 10회 이상인 묶음의 비율을 함께 보여 줍니다.
- **같은 도구를 바로 다시 부른 비율**과 가장 긴 연속 — 도구가 AI 에게 필요한 것을 주지 못했다는 신호입니다.
- **도구나 대상을 먼저 찾아본 묶음**, **도구 목록을 열고 실제로 쓴 비율**.
- **호출 사이 간격**(중앙값·90%) — AI 가 호출 사이에 생각하는 시간의 대략입니다.
- **조회 시간**(중앙값·90%) — 실제로 실행된 읽기 호출만 셉니다.
- **실패**·**거부**·**승인 대기** 호출, **빈 결과**(추정), **대상을 되물은 호출**, **크기 제한에 맞춰 줄인 응답**. "찾는 대상이 없다"고 답하거나 어느 대상인지 되물은 호출은 실패가 아니라 빈 결과·되물음으로 세고, 그 시간은 조회 시간에 넣습니다.

아래 표는 같은 숫자를 도구 서랍별로 나눠 보여 줍니다. 이 화면에는 도구 이름을 싣지 않습니다.

알아 둘 한계:

- 사람이 승인한 뒤 서버가 실행한 변경은 포함하지 않습니다.
- 응답 크기에서 이미지는 뺍니다.
- 이 측정을 넣기 전에 기록된 호출은 빠집니다. 측정된 호출의 비율을 함께 보여 주므로 확인할 수 있습니다.

같은 숫자는 도구별 내역까지 `GET /api/v1/mcp/quality?days=1|7|30&transport=`(*로그 보기* 권한 필요)로도 받을 수 있습니다. 응답에는 사용자 이름·대화 열쇠·인자가 없습니다.

`AOT_MCP_QUALITY_LEDGER=0` 으로 두면 측정 칸을 채우지 않습니다. 도구 호출 기록 자체는 예전처럼 남습니다.

---

## AI 지식 (Knowledge) { #knowledge-library }

`AI -> 지식`(`/ai/library`) 페이지는 AI 답변의 근거를 모아 두는 곳이고, 탭이
둘입니다. **지식** 탭은 AI 가 인용할 수 있는 항목 전부를, **소스** 탭은 그 지식을
들여오는 곳 — 문서(PDF·텍스트), 웹 URL, REST API, 내부 쿼리, 공공데이터 피드 — 을
보여 줍니다. 소스 행의 둘째 칸은 동기화 상태(동기화됨 · 동기화 실패 · 동기화 전,
그때그때 조회하는 소스라면 "실시간 조회")이고, 마지막 동기화 시각은 그 칸에 마우스를
올리거나 소스 설정 창에서 봅니다. 지금 동기화도 설정 창에 있습니다.

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

AI 가 쓴 메모 가운데 확인을 기다리는 것이 있으면 지식 탭 맨 위에 한 줄 알림이
뜹니다. **그 메모만 보기**를 누르면 목록이 '확인이 필요한 것'으로 걸러집니다.
항목을 눌러 상세 창을 열고, 원문 링크가 있으면 열어 확인한 뒤 **저장하고 확인**
(틀린 곳이 있으면 고친 다음) 또는 **폐기**를 누르세요. '확인'이 곧 미확인 상태에서
벗어나는 승격입니다. 원문 주소가 없는 항목은 링크가 뜨지 않습니다 — 대조할
원문이 없다는 뜻입니다.

지식 탭 아래 **지식 설정 → 확인한 지식만 인용**(기본 꺼짐)을 켜면 AI 가 자기가 쓴
미확인 메모를 인용하지 못합니다. 권위·사용자 지식은 영향을 받지 않습니다.

### 열람하고 직접 넣기

**지식** 탭 목록은 한 줄에 한 항목씩(제목·신뢰) 보여 주며, 기본으로는 사람과 AI 가
쓴 것만 싣습니다. 소스에서 동기화한 자료는 제목이 전부 소스 이름이라 섞으면 가려
읽을 수 없으므로, 출처 필터에서 따로 고르거나 소스 탭에서 관리합니다. 태그는 항목
상세 창에서 봅니다. 검색하고, 출처·상태·태그로 거르고, 낡은 것은 항목 상세 창에서
치우세요(치우기는 행을 남깁니다 — AI 손이 닿지 않게 할 뿐이며, 상태 필터에서 치운
항목까지 보이게 한 뒤 되돌릴 수 있습니다).

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

- **AI 지식 화면** — 소스 탭의 목록 아래 "자료 출처" 줄. 켜 둔 소스만 실립니다.
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
   쓰기 도구 호출(노트·지식 포함) 자체가 서버에서 거부되어, Custom GPT 설정 실수로 장치를
   잘못 건드릴 위험이 원천 차단됩니다. 여러 사람이 쓴다면 각자 이름으로
   따로 발급하세요 — 감사 로그에 누가 호출했는지 남고, 유출됐을 때 그
   키 하나만 폐기하면 됩니다. 이 GPT 가 설정 작업을 하지 않는다면 **AI 도구**는
   운영으로 두세요([도구 묶음](#tool-profiles)).
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
   Custom GPT 안에서 자동 재승인은 없습니다. 승인은 **AI → 요청**(`/ai`)
   화면 맨 위 "승인 대기 중인 제어 요청"에서 합니다. AI 가 올린 일정 제안과
   조언도 같은 화면에서 결정합니다.

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

> 상태를 바꾸는 도구 호출은 이 서버에서도 곧장 실행되지 않습니다(`aot/tools/mcp_safety_gate.py`). 최초 호출은 `pending_approval` + `confirmation_id`로 응답하고, 사용자가 그 대화 또는 **AI → 요청** 화면(`/ai`)에서 명시적으로 승인/거부해야 `respond_to_confirmation` 호출로 처리됩니다(`/api/v1/mcp/review_page`는 지금도 존재하지만 `/ai`로 넘겨주는 리다이렉트일 뿐입니다 — 북마크 호환용입니다. 감사 로그 자체는 **AI → 기록**(`/ai/manage`)의 "도구 호출" 탭으로 옮겨졌고, "대화"·"오류 보고"·"호출 품질" 탭과 나란히 있습니다). 승인 후 같은 인자에 `_confirmation_id`를 붙여 재호출해야 실제로 실행됩니다 — 호출한 AI가 스스로 승인 여부를 판단하거나 대신 답할 수 없습니다. `AOT_MCP_WRITE_ENABLED=0`이면 쓰기 도구 자체(노트·지식 포함)가 조언 전용으로 거부됩니다(`submit_advice`는 그대로 동작). 유효시간은 두 구간으로 나뉩니다 — 사람이 승인할 때까지 기본 15분(`AOT_MCP_CONFIRM_TTL_SEC`), 승인 이후 실행할 때까지 승인 시점부터 다시 기본 5분(`AOT_MCP_APPROVED_TTL_SEC`). 그래도 제어 도구가 노출되는 서버이므로 신뢰할 수 있는 클라이언트에만 연결하세요.

---

## 관련 페이지

- [환경 제어 자동화](env-control.md)
- [스케줄러](scheduler.md)
- AI 가이드 (전체) — 저장소의 `docs/ai_guide.ko.md`(이 매뉴얼에는 발행되지 않습니다): 서랍 안 도구를 포함한 전체 도구 목록과 인자
