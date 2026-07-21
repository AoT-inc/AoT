# AoT AI 에이전트 가이드 (한국어)

AoT의 AI 에이전트가 온실·재배 시설을 관찰·진단·제어하는 방법을 설명합니다. AI는 두 경로로 동작합니다: 대시보드의 **인앱 어시스턴트**(에이전트 루프)와, Claude Desktop 등 외부 클라이언트가 붙는 **외부 MCP 서버**(`aot/aot_mcp_server.py`). 두 경로 모두 같은 도구 레지스트리(`aot/ai/services/tool_registry.py`)에서 도구를 가져옵니다.

---

## 1. 도구 카탈로그

### 1.1 MCP 도구 (외부 서버 + `mcp_aot` 엔진)

| 분류 | 도구 | 설명 | 승인 |
|------|------|------|------|
| 관찰 | `get_spatial_tree` | 공간 계층(사이트 > 구역 > 장치) 트리 | 불필요 |
| 관찰 | `get_device_list` | 등록된 전체 장치 목록 | 불필요 |
| 관찰 | `search_devices` | 이름·유형으로 장치 검색 | 불필요 |
| 관찰 | `get_sensor_detail` | 센서 시계열 이력(min/max/avg) | 불필요 |
| 관찰 | `get_weather` | 포장·구역 현재 기상 | 불필요 |
| 관찰 | `get_energy_report` | 기간·구역별 에너지 사용량 | 불필요 |
| 관찰 | `get_cumulative_status` | EnvCoordinator DLI·GDD 누적 상태 | 불필요 |
| 관찰 | `list_available_devices` | AI 판단 대상 장치 목록(네이티브) | 불필요 |
| 관찰 | `get_sensor_reading` | 특정 센서 최신 측정값(네이티브) | 불필요 |
| 노트 | `search_notes` | 구역·장치 노트/작업기록 조회 | 불필요 |
| 노트 | `create_note` | 메모/노트를 대상에 부착해 저장 | 불필요 |
| 공지 | `list_notices` | 공지 게시판 글 목록 | 불필요 |
| 시스템 | `get_system_update_status` | 설치 버전 vs GitHub 최신 비교 | 불필요 |
| 작업 | `add_schedule` | 사람 작업 일정(제초·점검·청소) 등록 | **필요** |
| 제어 | `operate_device` | 밸브·펌프·조명 즉시 제어 | **필요** |
| 제어 | `set_output_state` | 출력 on/off(선택 지속시간, 네이티브) | **필요** |
| 제어 | `schedule_device_control` | 특정 시각 1회성 장치 제어 예약 | **필요** |

### 1.2 인앱 어시스턴트 확장 도구

인앱 어시스턴트는 위 카탈로그 외에 엔티티 조립·자동화·지식 도구를 추가로 사용합니다. 상태를 바꾸는 도구는 모두 승인이 필요합니다.

- **입력/출력**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **함수(자동화)**: `get_function_list`, `create_function`, `create_sequence_function`, `modify_function_options`, `activate_function`·`deactivate_function`·`delete_function`
- **일정 원장**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **지도(GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`
- **공지**: `create_notice`·`modify_notice`·`delete_notice`
- **AI 에이전트**: `list_ai_agents`, `list_ai_entries`, `create_ai_agent`·`modify_ai_agent`·`delete_ai_agent`
- **지식 라이브러리**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **진단·기타**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> 도구의 단일 정본은 `aot/ai/services/tool_registry.py`입니다. 도구가 추가·변경되면 이 문서보다 그 파일이 우선합니다.

---

## 2. 안전·승인 정책

- **읽기 도구**는 즉시 실행됩니다.
- **상태를 바꾸는 도구**(변이·물리 제어·일정)는 인앱 어시스턴트에서 호출될 때 승인 게이트를 거칩니다. 즉시 적용되지 않고 채팅에 **승인 카드**로 제시되며, 사용자가 승인해야 실행됩니다.
- 예외적으로 `create_note`·`knowledge_shelve`는 되돌릴 수 있는 저위험 기록이라 승인 없이 즉시 저장되며, 확정 전까지 권위 없는 정보로 취급됩니다.
- **장치별 AI 판단 포함 토글**: `설정 -> 입력/출력`의 각 장치 모달에서 끄면, 그 장치는 AI 도구의 조회·제어 대상에서 제외됩니다(`is_ai_enabled`).
- **외부 MCP 서버**(`aot_mcp_server.py`)는 자체 승인 게이트가 없어 도구를 호출된 대로 실행합니다. 제어 도구까지 노출되므로 신뢰할 수 있는 클라이언트에만 연결하세요.

---

## 3. 권장 워크플로

### 상태 점검 → 제어

```
1. get_spatial_tree
   → 사이트 > 구역 > 장치 계층과 대상 장치의 unique_id 확인

2. search_devices(query='밸브')  또는  get_device_list
   → 제어할 출력 장치의 unique_id 확보

3. get_sensor_detail(loc_id, sensor_type='temperature', time_range='24h')
   → 최근 추세 확인 (이상하면 원인 먼저 진단)

4. operate_device(device_id, state='on', value=...)
   → 승인 카드 제시 → 사용자가 승인해야 실제 동작
```

### 노트 조회 → 요약

```
1. (컨텍스트) 각 엔티티의 노트 다이제스트(초기+최근)는 시스템 상태로 미리 주입됨
   → "각 장치의 노트 확인" 같은 넓은 질문은 도구 없이 바로 답변 가능

2. search_notes(target_name='v111')
   → 특정 장치/구역의 전체·과거 노트로 드릴다운
```

### 자동화 만들기 (반복/조건 제어)

```
1. list_device_types(kind='function')
   → 유효한 함수 유형 확인 (유형을 지어내지 말 것)

2. create_function(function_type='trigger_timer_daily_time_point', name=..., params={...})
   → 승인 후 생성. 반복 관수는 schedule_device_control이 아니라 함수로.

3. get_function_list  /  activate_function(function_id)
   → 생성 확인 및 활성화(승인)
```

---

## 4. 도메인 지식

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

`get_cumulative_status`로 DLI(일적산광량)·GDD(누적온도)의 일별 누적과 목표 달성/부채 현황을 확인할 수 있습니다. 자세한 내용은 [환경 제어 자동화](ai/env-control.md)를 참고하세요.

---

## 5. Claude Desktop 설정

`claude_desktop_config.json`(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

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

원격 클라이언트는 HTTP 모드로 실행할 수 있습니다:

```bash
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

---

## 6. 금지 사항

AI 에이전트는 다음을 해서는 안 됩니다.

- 도구로 확보하지 않은 데이터(센서·날씨 등)를 **지어내기**. 모르면 "모른다/확인 필요"로 답하고 도구를 호출하거나 되물어야 합니다.
- 사용자 승인 없이 제어·변이 도구 실행.
- 유효 목록(`list_device_types` 등)을 확인하지 않고 장치/함수 유형을 **임의로 생성**.
- AI 판단에서 제외된(`is_ai_enabled=False`) 장치를 제어.
- 안전 관련 함수·설정을 사용자 확인 없이 비활성화.

---

## 7. 자주 하는 실수

| 증상 | 원인 | 해결 |
|------|------|------|
| 도구가 노트를 못 찾음 | `target_name`을 안 넘겨 키워드 검색만 함 | 구역/장치 이름을 `target_name`으로 전달 |
| 장치가 AI에 안 보임 | `is_ai_enabled=False` | 장치 설정 모달에서 AI 판단 포함 켜기 |
| 반복 제어가 스케줄로 안 됨 | 1회성 예약과 혼동 | 반복/조건 제어는 `create_function` 사용 |
| 외부 MCP 호출이 승인 없이 실행됨 | 외부 서버엔 승인 게이트 없음 | 제어 노출 서버는 신뢰 클라이언트에만 연결 |
| 유형 오류로 생성 실패 | 존재하지 않는 유형을 지어냄 | `list_device_types`로 유효 유형 먼저 확인 |
