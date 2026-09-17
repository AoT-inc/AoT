# AoT AI 에이전트 가이드 (한국어)

AoT의 AI가 시설·포장을 관찰·진단·제어하는 방법을 설명합니다. AI는 두 경로로 동작합니다: 대시보드의 **인앱 어시스턴트**(에이전트 루프)와, Claude Desktop·ChatGPT 등 외부 클라이언트가 붙는 **외부 MCP 서버**(`aot/aot_mcp_server.py`). 두 경로 모두 같은 도구 레지스트리(`aot/ai/services/tool_registry.py`)에서 도구를 가져옵니다.

---

## 1. 도구 표면 — 상시 노출 + 서랍

도구는 146개이고, 그중 128개가 외부 MCP에 노출됩니다. 전부를 `tools/list`에 한 번에 싣으면 응답만 2만 토큰이 넘어가기 때문에, 표면은 두 층으로 나뉩니다.

- **상시 노출(core)** — 매 `tools/list`에 실리는 27개. 일상 질문 대부분이 여기서 끝납니다.
- **서랍(drawer)** — 나머지 101개. 목적별 8개 서랍에 들어 있고, 열어야 스키마가 보입니다.

서랍을 다루는 메타 도구 4개는 항상 노출됩니다.

| 도구 | 하는 일 |
|------|---------|
| `open_drawer` | 인자 없이 부르면 서랍 목록, `{drawer:'space'}`면 그 서랍 도구들의 전체 정의 |
| `get_tool_detail` | `{tool_name}` 하나의 전체 정의 |
| `use_tool` | `{tool_name, arguments}`로 서랍 안 도구를 실행. 승인·권한·감사는 직접 호출과 동일 |
| `respond_to_confirmation` | 대기 중인 승인 건을 승인/거부(§3) |

> **없다고 단정하기 전에 서랍을 열 것.** "그건 이 시스템에서 안 됩니다"라고 답하거나, 어중간하게 맞는 상시 도구로 우회하기 전에 목적에 맞는 서랍을 먼저 여세요. 서랍 도구도 보통 도구와 똑같이 동작합니다.

환경변수 `AOT_MCP_TOOL_TIERING=0`을 주면 서랍 없이 128개를 전량 노출합니다(기본은 켜짐).

### 1.1 상시 노출 도구 (27)

| 분류 | 도구 | 설명 | 승인 |
|------|------|------|------|
| 시작점 | `get_system_brief` | 시스템 한눈 요약 — 여기서 시작 | 불필요 |
| 해소 | `resolve_target` | 이름→엔티티 해석, 컨테이너(하위 구역 보유) 여부 | 불필요 |
| 공간 | `get_spatial_tree` | 사이트 > 구역 > 장치 계층 | 불필요 |
| 공간 | `get_map_equipment` | 지도에 놓인 설비·장치 | 불필요 |
| 장치 | `get_device_list` / `search_devices` | 전체 목록 / 이름·유형·측정종류 검색 | 불필요 |
| 장치 | `get_device_measurements` | 장치의 측정 채널 목록 | 불필요 |
| 장치 | `get_output_state` | 출력(밸브·펌프·조명) 현재 상태 | 불필요 |
| 측정 | `get_sensor_detail` | 센서 이력(min/max/avg), Function 집계값 포함 | 불필요 |
| 측정 | `get_zone_sensor_summary` | 구역 전체 최신값+기간 통계를 한 번에 | 불필요 |
| 측정 | `get_weather` / `get_weather_forecast` | 현재 기상 / 예보 | 불필요 |
| 구획 | `list_plots` / `get_plot` | 작물 구획 목록 / 구획 상세 | 불필요 |
| 함수 | `get_function_list` / `get_active_functions_summary` | 함수 목록 / 작동 중 요약 | 불필요 |
| 함수 | `activate_function` / `deactivate_function` | 함수 켜기/끄기 | **필요** |
| 제어 | `operate_device` | 밸브·펌프·조명 즉시 제어 | **필요** |
| 일정 | `search_schedule` | 일정 조회 | 불필요 |
| 일정 | `add_schedule` | 사람 작업 일정·메모 등록 | 불필요(§3) |
| 기록 | `search_notes` / `create_note` | 노트 조회 / 작성 | 불필요 |
| 지식 | `knowledge_search` | 매뉴얼·지식 라이브러리 자유문 검색 | 불필요 |
| 정의 | `list_device_types` | 유효한 장치·함수 유형 목록 | 불필요 |
| 시스템 | `list_ai_agents` | 등록된 AI 에이전트 | 불필요 |
| 승인 | `list_pending_confirmations` | 대기 중인 승인 건 | 불필요 |

### 1.2 서랍 8개 (101)

| 서랍 | 내용 | 도구 |
|------|------|------|
| `device` | 장치 조작·상태 | `get_control_state`, `set_output_state`\* |
| `measurement` | 센서·환경·에너지 | `get_anomalies`, `get_cumulative_status`, `get_device_freshness`, `get_energy_report` |
| `function` | 함수·제어기·시퀀스 | `get_function_detail`, `create_function`\*, `delete_function`\*, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day` |
| `schedule` | 일정·예약 | `schedule_device_control`\*, `edit_schedule`\*, `delete_schedule`\*, `add_schedule_batch` |
| `record` | 노트·공지·지식·조언 | `list_notices`, `get_note_attachment`, `search_archives`, `get_archived_document`, `knowledge_shelve`, `list_advice`, `submit_advice`, `list_lookup_sources`, `query_data_source`, `query_reference_table`, `list_library_source_types`, `smartfarmkorea_lookup`, `create_notice`\*, `modify_notice`\*, `delete_notice`\*, `archive_note`\*, `restore_note_from_archive`\*, `delete_archive`\*, `set_document_tier`\*, `configure_library_source`\* |
| `space` | 지도·구역·시설·구획 | `list_geo_maps`, `get_crop_status`, `get_device_location`, `get_map_equipment_detail`, `get_facility_capacity`, `get_address`, `distance_between`, `nearest`, `get_plot_history`, `list_plot_journals`, `get_plot_journal`, `list_programs`, `get_program`, `propose_plot_split`, 구획 원장 쓰기 18종\*(`create_plot`, `modify_plot`, `end_plot`, `copy_plot`, `delete_plot`, `apply_plot_split`, `confirm_plot_stage`, `reschedule_plot_stage`, `add_plot_stage`, `remove_plot_stage`, `undo_plot_stage`, `set_plot_stage_guidance`, `apply_plot_resources`, `save_plot_schedule_as_program`, `create_plot_journal`, `delete_program`, `set_device_location`, `delete_geo_shape`), `create_program`, `modify_program` |
| `definition` | 장치 정의 CRUD | `get_device_type_options`, `list_gis_inputs`, `create_input`\*, `modify_input`\*, `delete_input`\*, `create_output`\*, `modify_output`\*, `delete_output`\*, `modify_gis_input`\*, `delete_gis_input`\*, `activate_gis_input`\*, `create_gis_input` |
| `system` | AI 설정·상태·진단·화면 | `get_local_time`, `get_system_update_status`, `get_storage_tier_status`, `analyze_system_failure`, `list_ai_entries`, `list_dashboards`, `list_tabs`, `list_widget_types`, `get_widget`, 위젯·탭·에이전트 쓰기 8종\*, `create_ai_agent` |

\* 표시 = 승인 필요. 그 외 쓰기 도구는 §3의 "설정만 바꾸는 쓰기"라 승인 없이 즉시 저장됩니다.

### 1.3 인앱 어시스턴트 전용

인앱 어시스턴트는 위에 더해 `read_manual`(매뉴얼을 파일명+섹션으로 읽기), `get_detailed_manifest`, `ask_user`, `get_sensor_reading`, `list_available_devices`, `set_output_state`, `list_unbound_slots`, `rebind_device`, `get_function_doc`·`get_input_doc`·`get_output_doc`를 씁니다. 외부 MCP에서 매뉴얼을 찾을 때는 `read_manual` 대신 `knowledge_search`를 쓰세요 — 파일명을 몰라도 매뉴얼 전체에서 해당 섹션을 찾아 줍니다.

> 도구의 단일 정본은 `aot/ai/services/tool_registry.py`입니다. 이 문서와 어긋나면 그 파일이 맞습니다.

---

## 2. 시간 — 데이터에서 '지금'을 추론하지 말 것

모든 응답에 `now` = {`farm_local`, `tz`}가 실립니다. **그것만이 현재 시각입니다.** 데이터 속 타임스탬프는 과거 사건이고, `evaluated_at`·`last_seen` 같은 필드는 "측정된 시점"이지 지금이 아닙니다.

- 타임스탬프는 ISO 8601이고 **전부 같은 시간대가 아닙니다** — 센서 값은 그 장치의 현지 시각으로 돌아옵니다. 각 값의 오프셋을 그대로 읽으세요.
- 장치가 농장 기본 시간대와 다른 곳에 있을 수 있습니다. 특정 장소의 낮/밤·예약 시각·"지금 할 때인가"를 따지기 전에 `get_local_time`(system 서랍)으로 그 위치의 시각을 확인하세요.

---

## 3. 안전·승인

도구는 세 갈래입니다.

1. **읽기** — 즉시 실행.
2. **설정만 바꾸는 쓰기(승인 면제)** — `add_schedule`, `add_schedule_batch`, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day`, `create_program`·`modify_program`, `create_gis_input`, `create_ai_agent`. 장비를 움직이지 않고 항상 비활성 상태로 만들어지기 때문에 즉시 저장됩니다. 실제로 작동하려면 사람이 따로 활성화해야 하고, 그 활성화(`activate_function`, `activate_gis_input`)는 승인 대상입니다. 함수를 새로 만들거나 지우는 `create_function`·`delete_function`은 여기 들지 않습니다 — 승인이 필요합니다.
   `create_note`·`knowledge_shelve`는 아예 쓰기 도구로 치지 않는 저위험 기록이라 즉시 저장되며, 사람이 확정하기 전까지 권위 없는 정보로 다룹니다.
3. **승인이 필요한 쓰기** — 물리 제어와 원장 변경 전부.

### 인앱 어시스턴트

채팅에 **승인 카드**로 제시되고, 사용자가 승인해야 실행됩니다.

### 외부 MCP (`aot/ai/services/mcp_safety_gate.py`)

1. 쓰기 도구 최초 호출 → 실행되지 않고 `pending_approval` + `confirmation_id` 응답.
2. 사람이 승인 — 대시보드의 **MCP 승인 위젯**, AI 화면, 또는 사용자가 이 대화에서 명시적으로 승인하라고 말했을 때만 `respond_to_confirmation`.
3. 승인되면 서버가 저장해 둔 인자로 **그 자리에서 실행**합니다. AI가 나중에 같은 인자 + `_confirmation_id`로 재호출하면 재실행이 아니라 저장된 결과를 돌려줍니다(`already_executed`).

지켜야 할 규칙:

- **승인 여부를 AI가 판단하거나 대신 답할 수 없습니다.** 원래 작업 지시("이 일정들 만들어줘")는 그 자체로 "confirmation_id X를 실행하라"가 아닙니다. 일괄 처리도 같습니다 — "대기 중인 거 정리해줘"는 이름을 대지 않은 집합에 대한 승인이 아닙니다.
- 승인 시점과 **인자가 완전히 같아야** 통과합니다(승인 바꿔치기 방지).
- 만료: 승인 대기 **15분**(`AOT_MCP_CONFIRM_TTL_SEC=900`), 승인 후 실행 유효 **5분**(`AOT_MCP_APPROVED_TTL_SEC=300`, 승인 시점부터 다시 셈).
- 호출 상한: `operate_device`·`set_output_state`·`schedule_device_control` 시간당 20회, `modify_sequence_step` 60회, 그 외 기본 10회. 승인 요청과 재호출이 각각 카운트되므로 실제 완료 가능한 작업 수는 그 절반입니다.
- `AOT_MCP_WRITE_ENABLED=0`이면 쓰기 도구는 승인 큐조차 만들지 않고 조언 전용으로 거부됩니다.
- 읽기 전용 API 키로 접속하면 쓰기 권한이 강제로 꺼지고, `respond_to_confirmation`은 Admin/Editor 키에서만 동작합니다.

### 그 밖의 차단

- **장치별 AI 판단 포함 토글**: `설정 → 입력/출력`의 각 장치 모달에서 끄면 그 장치는 AI 도구의 조회·제어 대상에서 빠집니다(`is_ai_enabled`).
- 외부 MCP 서버는 제어 도구가 노출되는 서버입니다. 신뢰할 수 있는 클라이언트에만 연결하세요.

---

## 4. 권장 워크플로

### 상태 점검 → 제어

```
1. get_system_brief
   → 무엇이 있고 지금 무엇이 도는지 한 번에

2. resolve_target(name='3번 하우스')
   → 이름을 엔티티로 확정. children이 있으면 컨테이너이므로 자녀를 대상으로

3. search_devices(query='밸브', zone='3번 하우스')  또는  get_device_list
   → 제어할 출력 장치 확보

4. get_sensor_detail(sensor_type='temperature', time_range='24h')
   → 추세 확인. 이상하면 원인부터 진단

5. operate_device(device_id, state='on', value=...)
   → 승인 요청 → 사람이 승인해야 실제 동작
```

### 매뉴얼·지식 찾기

```
knowledge_search(query='구획 단계 확정')
   → 매뉴얼 전체에서 해당 섹션 본문을 바로 반환. 어느 쪽인지 몰라도 됩니다.

인앱 어시스턴트라면 쪽을 지정해 읽을 수도 있습니다. 컨텍스트에는 쪽 이름 목록
(manual_index_files)만 실리므로 두 단계입니다.

1. read_manual(target_id='geo/plots.md')
   → 그 쪽의 목차. 절이 없는 짧은 쪽은 본문이 통째로 옵니다.
2. read_manual(target_id='geo/plots.md', params={'section': '<목차의 제목>'})
   → 그 절의 본문
```

### 노트 조회 → 요약

```
1. (컨텍스트) 각 엔티티의 노트 다이제스트는 시스템 상태로 미리 주입됨
   → "각 장치의 노트 확인" 같은 넓은 질문은 도구 없이 답변 가능

2. search_notes(target_name='v111')
   → 특정 장치·구역의 전체·과거 노트로 드릴다운
```

### 자동화 만들기 (반복·조건 제어)

```
1. list_device_types(kind='function')
   → 유효한 함수 유형 확인 (유형을 지어내지 말 것)

2. use_tool('create_function', {function_type='trigger_timer_daily_time_point', ...})
   → 반복 관수는 schedule_device_control이 아니라 함수로

3. get_function_list  →  activate_function(function_id)
   → 생성 확인 후 활성화(승인 필요)
```

---

## 5. 도메인 지식

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)  
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| 범위 | 상태 | 권장 작물 단계 |
|------|------|--------------|
| < 0.4 kPa | 너무 낮음 — 증산 억제, 곰팡이 위험 | — |
| 0.4 ~ 0.8 kPa | 적정 (유묘기) | 발아·정식 초기 |
| 0.8 ~ 1.2 kPa | 적정 (영양생장기) | 성장기 |
| 1.2 ~ 1.8 kPa | 적정 (생식생장기) | 개화·착과기 |
| > 1.8 kPa | 너무 높음 — 수분 스트레스 위험 | — |

### 환경 제어 3계층 (EnvCoordinator)

- **L1 EnvTarget**: Method 곡선 또는 고정값에서 VPD·CO₂·광량 목표를 읽음
- **L2 SituationReport**: 편차·제한인자·추세 평가
- **L3 Coordinator**: 위치형 PI + 슬루율 제한 + 적분 와인드업 방지 → 액추에이터 명령

`get_cumulative_status`(measurement 서랍)로 DLI(일적산광량)·GDD(누적온도)의 일별 누적과 목표 달성·부채 현황을 확인할 수 있습니다. 자세한 내용은 [환경 제어 자동화](ai/env-control.md)를 참고하세요.

---

## 6. 연결 설정

### stdio (Claude Desktop 등)

`claude_desktop_config.json`(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aot": {
      "command": "python3",
      "args": ["/opt/AoT/aot/aot_mcp_server.py"],
      "env": { "AOT_MCP_API_KEY": "<발급받은 API 키>" }
    }
  }
}
```

### HTTP (원격 클라이언트)

```bash
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

- 엔드포인트: `POST/GET/DELETE /mcp` (Streamable HTTP). 호환용 REST로 `GET /mcp/info`, `GET /mcp/tools/list`, `POST /mcp/tools/call`.
- 인증: `X-API-KEY` 헤더에 API 키(base64). `Authorization: Basic`/`Bearer`도 받습니다. 키는 사용자 설정에서 발급하며, **키 소유자가 곧 호출자 신원**이고 그 사용자의 권한을 그대로 따릅니다.
- `AOT_MCP_REQUIRE_AUTH=0`으로 인증을 끄면 권한이 없는 것으로 취급되어 조회 전용이 됩니다.
- `설정 → 일반`의 MCP HTTP 서버 토글을 끄면 재시작 없이 503을 반환합니다.

---

## 7. 금지 사항

- 도구로 확보하지 않은 데이터(센서·날씨 등)를 **지어내기**. 모르면 "모른다/확인 필요"로 답하고 도구를 호출하거나 되물으세요.
- 사용자 승인 없이 제어·변이 도구 실행, 또는 승인 여부를 스스로 판단하기.
- 유효 목록(`list_device_types` 등)을 확인하지 않고 장치·함수 유형을 **임의로 생성**.
- AI 판단에서 제외된(`is_ai_enabled=False`) 장치를 제어.
- 안전 관련 함수·설정을 사용자 확인 없이 비활성화.
- 사용자에게 `unique_id`·`note_id` 같은 UUID를 그대로 보여주기 — 이름으로 부르세요. 사용자가 id를 직접 물었을 때만 예외입니다.

---

## 8. 자주 하는 실수

| 증상 | 원인 | 해결 |
|------|------|------|
| 도구가 없어서 못 한다고 답함 | 상시 노출 27개만 보고 판단 | `open_drawer`로 목적에 맞는 서랍을 먼저 열 것 |
| 시각 계산이 하루씩 어긋남 | 데이터 타임스탬프에서 '지금'을 추론 | `now.farm_local`을 쓰고, 장소별 판단은 `get_local_time` |
| 도구가 노트를 못 찾음 | `target_name`을 안 넘겨 키워드 검색만 함 | 구역·장치 이름을 `target_name`으로 전달 |
| 장치가 AI에 안 보임 | `is_ai_enabled=False` | 장치 설정 모달에서 AI 판단 포함 켜기 |
| 반복 제어가 예약으로 안 됨 | 1회성 예약과 혼동 | 반복·조건 제어는 `create_function` |
| 쓰기 호출이 `pending_approval`에서 안 넘어감 | 사용자의 명시적 승인 없이 진행하려 함 | 사용자가 그 대화에서 confirmation_id를 승인한 뒤에만 `respond_to_confirmation` |
| 승인했는데 거부됨 | 인자가 승인 시점과 다르거나 5분이 지남 | 같은 인자로 재호출, 늦었으면 승인부터 다시 |
| 구역별 일정이 사이트 하나에 붙음 | `add_schedule`에 컨테이너 이름을 그대로 씀 | `resolve_target`으로 확인 후, `children`이 있으면 자녀 이름들로 `add_schedule_batch` |
| 유형 오류로 생성 실패 | 존재하지 않는 유형을 지어냄 | `list_device_types`로 유효 유형 먼저 확인 |
