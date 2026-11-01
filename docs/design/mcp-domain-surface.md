# MCP 도메인 표면 — 틀부터 다시 (설계안, 2026-10-13)

상태: **방향 승인(2026-10-13)** — 공통 `target`·`period`·operation 명부·응답 계약.
구현 착수 전 필수 조건 세 가지(§2-3 확장 규칙 분리 · §3-2 명부 계약과 승인 동등성 ·
§9-1 실행 직전 검증과 물리 종료 보장)는 이 문서가 닫는다. 도구·인자 이름 동결은
`test_mcp_surface_freeze.py` 가 지킨다.

## 0. 왜 다시 하는가

지금 표면은 사건이 날 때마다 도구 하나·인자 하나·예외 하나를 덧붙여 자랐다.
2026-10-13 main 실측(관리자 키, 설정 묶음):

| 항목 | 값 |
|---|---|
| 도구 | 136개(읽기 68 · 쓰기 68) |
| 목록 크기 | 43,915 추정 토큰(운영 묶음 21,886) |
| 서로 다른 인자 이름 | **219개** |
| 대상을 가리키는 인자 이름 | **23가지** — `plot_id`·`device_id`·`target_name`·`target_id`·`zone_id`·`zone_ids`·`zone_name`·`scope_id`·`loc_id`·`area_name`·`facility_name`·`facility_id`·`place` … |
| 시간을 가리키는 인자 이름 | **26가지** — `date_from`·`start`·`started_on`·`days`·`time_range`·`period`·`hours`·`lookback_minutes`·`startDate` … |
| 대상 해석 | 도구마다 자기 안에서 따로(공용 해석기를 직접 쓰는 도구는 소수) |

외부 AI 호출 2026-10-12~13: 878건 중 실패 97건, 그중 **49건이 대상 인자 이름을
틀린 것**이다. AI 는 하나의 일관된 이름을 기대하는데 도구마다 다르다. "김제 지도의
농장 요약" 이 열 번 모두 엉뚱한 답이 된 것도 같은 뿌리다 — 지도라는 대상이 해석의
틀 안에 없었고, 도구마다 "이 도구가 받을 질문" 을 미리 정해 두었기 때문이다.

목록 크기도 같은 구조에서 나온다. 기능 하나 = 도구 하나라서, 아무리 설명을 줄여도
기능이 늘면 다시 커진다(10-08 20,903 → 10-13 21,886, 묶음 도구로 줄인 뒤인데도).
응답도 같다 — 크기 상한이 목록에만 있어 예보 응답 하나가 180 → 4,013 이 됐다.

**고칠 것은 개별 사건이 아니라 이 구조다.**

## 1. 틀의 원칙

1. **기능은 도구가 아니라 operation 이다.** 도구 수는 고정한다. 새 기능은 operation
   명부의 한 줄로만 들어간다.
2. **대상 해석은 실행층 한 곳.** 모든 operation 이 같은 `target` 인자를 받고, 실행층이
   도구를 부르기 전에 한 번 푼다. 도구(처리기) 안에서 이름을 해석하지 않는다.
3. **인자 어휘는 하나.** 대상·시간·측정·값·개수는 모든 operation 이 같은 이름을 쓴다.
4. **응답 모양은 하나.** 무엇으로 풀었는지(`target`)를 항상 되돌려준다. 크기 상한은
   operation 마다 있다.
5. **설명은 "언제 쓰나" 에 쓴다.** 인자 나열이 아니라 "이런 질문 → 이 operation" 한 줄.
   자세한 인자는 `help` 와 인자 오류 응답이 준다(지금 `get_tool_detail` 과 같은 방식).
6. **틀은 테스트로 지킨다.** 규칙을 문서에만 두면 다음 사건 때 다시 땜질이 된다(§7).
7. **바꾸기 전에 실제 대화로 잰다.** 지금 표면의 점수보다 나을 때만 기본값을 바꾼다(§8).

## 2. 대상 모델 — `target`

### 2-1. 종류와 포함 관계

```
지도(map) ⊃ 대지(site) ⊃ 구역(zone) ⊃ 시설(facility) ⊃ 동(bay)
                                     ⊃ 구획(plot)        (노지 구획은 구역/대지 안)
장소 ∋ 장치(device: 입력·출력·복합장치)
그 밖: 함수(function) · 프로그램(program) · 노트(note) · 일정(schedule) · 위젯·대시보드
```

포함 판정의 정본은 지금처럼 `device_membership`(PlaceIndex) 하나다. 이 틀은 그 위에
"지도" 를 최상위 그릇으로 올리는 것 말고는 새 규칙을 만들지 않는다.

### 2-2. 해석 규칙(실행층 `resolve_target` 하나)

1. id 정확일치(어느 종류든).
2. 이름 정확일치 — **종류를 가리지 않고** 정확히 맞는 것이 부분일치보다 이긴다.
   ("김제" 는 지도 '김제' 가 정확일치, 기상 장치 '기상청: 김제' 는 부분일치.)
3. 한정 이름 — "김제 3포장", "3포장 콩" 처럼 그릇 이름 + 안의 이름.
4. 부분일치·작물 이름(지금 규칙 그대로).
5. 정확일치가 둘 이상이면 고르지 않고 되묻는다 — 모양은 모든 operation 이 같다
   (`needs_disambiguation` + 후보마다 `where`).

**3단계(낱말 대조)는 문법을 풀지 않는다**(2026-10-14 구현, `targets.py` §2-1).
실제 실패의 대부분은 같은 이름에 숫자·지역이 붙고 다른 지도에 놓인 것들이었다 —
옛 표면은 '김제' 에 이름에 김제가 든 장치 둘을, '영양' 에 '가습기: 영양' 을 내밀었다.

- **경로가 주 경로다.** `target` 에 `"김제 > 밸브"` 를 실으면 `>` 앞은 자리, 뒤는
  이름이다. 응답의 `path` 와 같은 표기라 모델이 받은 경로를 그대로 되넘길 수 있고,
  어느 언어로 말하든 모델이 이 구조로 바꾼다. 그 자리에 그 이름이 없으면 느슨한
  해석으로 넘기지 않고 "없다" 고 말한다(다른 자리의 같은 이름을 집지 않게).
- **자유 문장은 보조다.** 띄어쓰기·조사로 가르면 그 언어에만 맞는다(일본어·중국어는
  띄어 쓰지 않는다). 그래서 후보마다 물음 안에서 그 이름 낱말과 놓인 자리 이름이
  **나타나는 곳**을 지우고, 남은 조각이 이어 주는 말·종류 낱말·측정 낱말·이름의
  일부로만 이루어질 때 그 후보로 본다. 언어 낱말은 `vocab.py` 의 표
  (`GLUE_WORDS`·`FILLER_WORDS`·`KIND_WORDS`) 한 곳이다 — 언어를 늘리는 일은 낱말을
  더하는 것이지 로직을 고치는 것이 아니다.
- 이름 낱말이 물음에 모두 있는 후보가 먼저다("김제 밸브" → '밸브: 김제', 숫자가 더
  붙은 '밸브 1: 김제' 가 아니다). 그 다음이 종류가 바로 맞는 것이다. 그래서 "영양
  시설"·"김제 장치" 는 그 지도(그 안의 시설·장치)가 된다.
- 'AI 판단에 포함' 을 끈 장치만 맞으면 "없다" 가 아니라 "꺼져 있다" 고 말한다.

### 2-3. 해석 뒤에는 operation 의 `accepts` 와 대조한다 — 확장은 읽기만

해석(§2-2)은 종류를 가리지 않고 찾는다. 그래서 해석이 끝나면 **반드시** 그
operation 이 받는 종류(`accepts`)와 대조한다. 정확히 맞는 장치라도 operation 이
장소만 받으면 그대로 넘기지 않는다.

| 경우 | 읽기 | 기록·설정 | 물리 제어·자동화 |
|---|---|---|---|
| 받는 종류가 왔다 | 그대로 | 그대로 | 그대로 |
| 더 큰 그릇이 왔다(지도·대지) | 안의 대상으로 펼쳐 각각 답한다 — operation 의 `max_targets` 안에서, 넘치면 "N곳 중 M곳" | **펼치지 않는다.** 명부에 `expand_write: true` 와 `max_targets` 가 있는 operation 만 대상 목록·개수를 보이고 별도 승인 | **펼치지 않는다.** 단일 대상만. 그릇이 오면 안의 후보를 보이고 하나를 고르라고 되묻는다 |
| 더 작은 것이 왔다(장치 → 장소) | 그 장치가 속한 장소로 올려 답하고 그렇게 했다고 적는다 | 올리지 않는다 — 되묻는다 | 올리지 않는다 — 되묻는다 |
| 대상 없음 | operation 이 "전체" 를 허용하면 전체 | 되묻는다 | 되묻는다 |
| 모호함 | 고르지 않는다(되묻기 또는 후보마다 답) | 고르지 않는다 | 고르지 않는다 |

**모호하지 않은 상위 대상도 쓰기에서는 자동으로 대량 실행하지 않는다.** "김제 지도
장치를 꺼 줘" 는 지도 아래 장치를 모두 끄는 요청으로 읽지 않는다 — 후보를 보이고 고르게 한다.

### 2-4. 해석 결과는 실행 추적에 충분해야 한다

해석 결과(응답의 `target`, 승인 스냅샷)에는 다음을 싣는다:
`kind` · `id`(내부 unique_id) · `name` · `path`(상위 관계 — 지도 > 대지 > 구역 …) ·
`map` · `matched`(정확·표기·한정·부분 중 어느 규칙으로 풀렸는지).
안쪽 도구에는 **이름이 아니라 해석된 id 를** 넘긴다 — 안쪽 도구가 이름을 다시
해석하지 않게(해석은 한 번, 실행층에서).

## 3. 공통 인자 어휘

| 이름 | 뜻 | 받는 모양 |
|---|---|---|
| `op` | operation | 명부의 이름 |
| `target` | 대상(§2) | 이름·id 하나, 또는 목록(최대 10) |
| `period` | 기간 | `"now"`·`"24h"`·`"7d"`·`"today"`·`{from, to}` |
| `at` | 한 시점(예약·되묻기) | ISO 또는 `"내일 06:00"` 류 |
| `measurement` | 측정 종류 | `temperature`·`soil_moisture`… (부분일치) |
| `value` | 쓸 값 | 숫자·문자·켜기/끄기 |
| `query` | 자유 검색어 | 문자 |
| `limit` | 개수 | 정수 |
| `fields` | 더 볼 것(상세·진단) | 목록 |

operation 고유 인자는 명부에 이유를 적어야만 둘 수 있다(§7 테스트). 시간대는
실행층이 대상의 위치로 푼다(`device_tz.location_iso` — 지금 정본 그대로).

**시간은 읽기와 쓰기가 다르다.**
- 읽기: 정해진 상대 문법(`now`·`24h`·`7d`·`today`·`yesterday`·`this_week`)을 받는다.
- 쓰기(예약·제어): 서버가 **대상 위치의 시간대로 절대 시각**을 확정하고, 그 절대 시각이
  승인 스냅샷과 승인 화면과 실행에 같이 쓰인다. 자연어(`"내일 06:00"`)는 받더라도 확정한
  절대 시각을 응답·승인 화면에 그대로 보인다.
- `value` 는 이름을 통일할 뿐 검증을 없애지 않는다 — 타입·범위는 operation 명부의
  `arg_schema` 와 안쪽 도구가 서버에서 강제한다.

### 3-2. operation 명부의 계약

명부 한 줄이 갖는 칸(빠지면 테스트가 막는다):

| 칸 | 뜻 |
|---|---|
| `tool`·`op` | 도메인 도구와 operation 이름 |
| `use` | "언제 쓰나" 한 줄 — 목록에 실린다 |
| `inner` | 실제로 도는 지금 도구(종류별로 다를 수 있다: `{device: get_sensor_reading, zone: get_zone_sensor_summary}`) |
| `accepts` | 받는 대상 종류 |
| `arg_schema` | 필수 인자와 타입·범위(공통 어휘 + 이유를 적은 고유 인자) |
| `effect` | `read` · `record` · `config` · `automation` · `physical` · `permission` |
| `approval` | **안쪽 도구의 승인 요구를 그대로 물려받는다.** 명부가 낮출 수 없다(§7) |
| `preconditions` | 실행 전 확인(예: 함수 끄기 — 그 함수에 매인 진행 중 시퀀스) |
| `target_expansion` | 읽기 `max_targets` · 쓰기 `expand_write`(기본 false) |
| `budget` | 응답 상한(기본 2,500, 큰 조회 6,000) |

쓰기 operation 은 목록에 **필수 인자와 위험(effect·승인 여부)까지** 싣는다 — 세부만
`help` 로. 쓰기에서 인자를 몰라 왕복이 늘면 승인 단계와 겹쳐 대화가 길어진다.

## 4. 도구 구성 — 14개

claude.ai 는 **도구 단위로** 허락을 묻고, 도구 표시(`readOnlyHint`·`destructiveHint`)는 도구에만
붙는다. 그래서 읽기와 쓰기, 그리고 **지우기**는 도구를 나눈다(지우기는 F-7). 승인 여부는 operation 마다 명부에 있고,
도구 설명이 승인이 필요한 operation 을 표시한다.

| 도구 | 성격 | 무엇을 | 지금 도구(대표) |
|---|---|---|---|
| `overview` | 읽기 | 현황·이상·작물·제어·진단 | get_place_overview · get_system_brief · get_anomalies · get_crop_status · get_control_state · analyze_system_failure |
| `measure` | 읽기 | 센서 값·이력·통계·신선도·에너지·누적·출력 상태 | get_sensor_reading · get_sensor_detail · get_zone_sensor_summary · get_device_freshness · get_energy_report · get_output_state |
| `weather` | 읽기 | 지금·지난 구간·예보·현지 시각(`now` 의 `period` 는 끝까지 지킨다, 시간별 예보 입력의 지난 값은 리드 하나를 대상 시각으로) | get_weather · get_weather_forecast · get_local_time |
| `find` | 읽기 | 이름 풀기·목록·검색·위치·거리 | resolve_target · search_devices · get_device_list · get_spatial_tree · list_geo_maps · list_plots · nearest · distance_between |
| `detail` | 읽기 | 대상 하나의 상세 | get_device_detail · get_plot · get_plot_history · get_function_detail · get_program · get_widget |
| `records` | 읽기 | 노트·공지·일지·일정·조언·지식·보관·참고 자료 | search_notes · list_notices · list_plot_journals · search_schedule · list_advice · knowledge_search · query_reference_table |
| `screen_view` | 읽기 | 사용자 화면 보기 | get_screen |
| `help` | 읽기 | operation 의 인자·예시·판단 규칙 | get_tool_detail |
| `control` | 쓰기(물리·승인) | 장치 켜고 끄기·예약·함수 켜고 끄기·운전 설정 | operate_device · schedule_device_control · activate/deactivate_function · modify_sequence_* |
| `record` | 쓰기(기록) | 노트·공지·일지·일정·조언·지식 쓰기 | create_note · create_notice · create_plot_journal · add_schedule · submit_advice · knowledge_shelve |
| `cultivate` | 쓰기(구획) | 구획·단계·프로그램 | create_plot · modify_plot · end_plot · plot_stage · create_program |
| `configure` | 쓰기(설정) | 장치·함수·위젯·탭·지도·AI·도구 묶음 | create_input · create_function · create_widget · set_device_location · set_tool_profile |
| `screen` | 쓰기(화면) | 화면 열기·강조·지도 조작 | screen_action |
| `remove` | 쓰기(지우기) | 공지·일정·보관·구획·단계·프로그램·장치·함수·위젯·탭·지도 도형·AI 지우기 | delete_* · remove_plot_stage |
| (승인 응답) | 쓰기 | 승인 대기에 답하기 | respond_to_confirmation → `record`·`control` 의 `op=confirm` |

136개 전부의 배정은 부록 A. **묶음(lite·운영·설정)은 도구 수가 아니라 켜지는
operation 으로 가른다** — `configure` 는 설정 묶음에서만 operation 이 차므로 운영
목록에는 operation 이 있는 도구만 실린다.

### 크기 목표(설정 묶음 포함, 추정 토큰)

| | 지금 | 상한(2026-10-14 사용자 결정) | 실측 |
|---|---|---|---|
| 운영 | 21,886 | **9,000** | 8,929 |
| 설정 | 42,649 | **15,000** | 14,506 |

처음 목표(운영 6,000·설정 9,000)는 실측 뒤 고쳤다 — 남은 무게가 operation 마다의 "언제 쓰나"
한 줄이라, 깎으면 설명이 부족한 도구가 된다. 상한과 래칫(의도 없이 느는 것)을
`test_mcp_domain_contract.py::DomainSurfaceBudgetTest` 가 지킨다.

**가벼움은 도메인 표면에서 운영과 합쳤다**(2026-10-14 사용자 결정). 새 틀에서는 둘의 차이가
작다(벤치 입력 중앙값 48K 대 52K). 가벼움 키는 운영과 같은 목록을 받는다. 아래 원래 구상은
기록으로 남긴다.

**가벼움은 같은 13개 도구에서 줄이는 곳만 다르다.** 도구를 따로 만들지 않는다.

- 읽기 operation 은 운영과 똑같이 "언제 쓰나" 한 줄을 싣는다 — 대화의 대부분이 읽기이고,
  여기를 깎으면 AI 가 엉뚱한 것을 고른다.
- 쓰기 operation 은 "언제 쓰나" 설명 줄을 빼되 **필수 인자와 위험(effect·승인 여부)은
  남긴다**(§3-2). 판단 규칙·예시 같은 세부만 `help` 로 받는다.
- `configure`·`cultivate` 의 설정용 operation 은 싣지 않는다(지금 가벼움과 같다).

이렇게 하면 약 3,500~4,000 이다(1단계 명부로 다시 잰다). 운영(6,000)과의 차이가 2,500 뿐이라, 검증(§8)에서 운영
6,000 으로도 무료 요금제 대화가 충분히 이어지면 **가벼움을 없애고 운영 하나로 합친다**
— 묶음이 하나 줄면 지킬 것도 하나 준다.

## 5. 응답 모양

```
{status, op, target: {kind, name, path, map}, data, more?, _reading?}
```

- `target` 은 항상 — 무엇으로 풀었는지 보여야 AI 가 다른 곳의 답을 이곳의 답으로 읽지 않는다.
- 시계열·여러 행은 **열 이름·단위를 한 번만**: `{columns: [...], rows: [[...]]}`.
- 정의·해석 문장(지표 정의, 제어 못 하는 축 설명 같은 것)은 응답마다 싣지 않고
  `help` 에 둔다. 응답에는 코드만(`degraded: {T_up: "no_actuator:heater"}`).
- operation 마다 응답 상한(기본 2,500, 큰 조회 6,000). 넘으면 지금 캡처럼 구조를 줄이고
  "N건 중 M건" 과 좁히는 방법을 남긴다.

## 6. 설명 — "언제 쓰나"

도구 설명 = 한 줄 목적 + operation 목록. operation 마다 한 줄:

```
measure — 센서 값. op:
  latest   지금 값(대상의 모든 센서, measurement 로 좁힘)
  history  기간 동안의 값(period 필수)  ← "어제 최고 온도", "지난주 추이"
  summary  여러 장소를 한 번에 비교     ← "어디가 제일 말랐나"
  …
```

이 한 줄이 AI 가 고르는 근거다. 인자 상세는 `help(op)` 와 인자 오류 응답이 준다.
자주 쓰는 operation 은 인자까지 한 줄에 싣는다(가벼움의 `LITE_ARG_HINTS` 가 효과를
보였다 — 상세 조회 4회 → 1회).

## 7. 틀을 지키는 테스트

| 테스트 | 막는 것 |
|---|---|
| 도구 수 고정 | 새 MCP 도구(기능은 operation 으로) |
| 모든 operation 에 명부 행 | 명부 밖 기능 |
| 인자 ⊆ 공통 어휘 ∪ 명부에 이유를 적은 고유 인자 | 인자 이름 늘어나기 |
| 처리기가 이름 해석기를 직접 부르지 않음(AST) | 도구별 해석 |
| 목록 상한(묶음별) · operation 별 응답 상한 | 크기 늘어나기 |
| 대표 질문 회귀(§8 의 일부를 빠르게) | "이런 질문엔 이 operation" 이 깨지기 |
| **operation 의 승인 요구 = 안쪽 도구의 승인 요구**(전수, 부록 A 를 코드에서 생성해 대조) | 통합하며 승인이 낮아지기 |
| **승인 큐·감사에 안쪽 도구 이름과 해석된 id 가 남는다** | 사람이 무엇을 승인하는지 모르게 되기 |
| **쓰기에 그릇이 오면 펼치지 않는다**(`expand_write` 없는 operation 전수) | 지도 하나로 대량 실행 |
| **쓰기의 시간은 절대 시각으로 스냅샷에 고정** | 승인한 시각과 실행 시각이 달라지기 |

안전 항목은 **평균 점수로 상쇄하지 않는다** — 하나라도 실패하면 기본값 전환을 막는다.

## 8. 검증 — 실제 대화로

- **데이터:** ① 2026-10-12~13 외부 호출 실패 97건 재생 ② 시나리오 약 40개 — 일상
  조회·제어(승인)·기록·구획·여러 장소 비교·지도 단위 요약·묶음 밖 요청, 다른 세션의
  리허설 시나리오 포함.
- **지표:**
  - 일반: 답 성공률 · 인자 오류율 · 거짓 "못 한다" · 왕복 수 · 대화당 토큰.
  - 대상: 잘못된 대상 선택 · 모호할 때 고르지 않았는가 · 그릇 펼치기가 맞았는가.
  - 안전(차단 조건, 평균에 넣지 않음): 승인 누락 · 승인한 것과 실행한 것의 불일치 ·
    허가되지 않은 대량 쓰기 · 쓰기 대상을 위로 올리거나 펼친 경우.
  - 호환: 지금 136개 도구와 새 operation 의 기능·권한 동등성(부록 A 전수).
  - 크기: 목록·응답 상한 준수와 잘린 뒤에도 쓸 만한가.
- **방법:** 같은 DB 사본·같은 모델로 지금 표면과 새 표면을 번갈아 돌린다. 대화 루프는
  `.local/bench` 하네스를 쓰고, claude.ai 는 마지막에 사람 손으로 확인한다.
- **바꾸는 조건:** 성공률이 지금보다 높고, 인자 오류가 0 에 가깝고, 크기가 §4 상한 안.

## 9. 옮기는 순서

| 단계 | 내용 | 끝나는 조건 |
|---|---|---|
| 0 | 도구 수 동결 ✅ · 검증 장치 · 지금 표면 기준 점수 | 기준 점수가 나온다 |
| 1 | **안전 계약** — 명부 스키마(§3-2), 부록 A 를 코드에서 생성해 **operation 마다 안쪽 도구의 승인·effect** 를 싣고 동등성 테스트, 확장 규칙(§2-3), 쓰기 시간 규칙(§3) | 동등성·확장 테스트가 돈다 |
| 2 | **읽기 수직 슬라이스** — `find`·`measure` 부터: 대상 해석·응답 모양·크기 상한, 스위치(`AOT_MCP_SURFACE=domain`) 뒤 | 검증에서 그 범위가 지금보다 낫다 |
| 3 | 나머지 읽기 6개 | 읽기 시나리오 전체 |
| 4 | **단일 대상 기록**(`record`) — 승인·권한·감사가 그대로인지 | 안전 항목 0건 |
| 5 | 설정·구획·물리 제어·자동화(`configure`·`cultivate`·`control`) — §9-1 을 갖춘 뒤 | 안전 항목 0건 + 물리 시나리오 |
| 6 | 기본값 전환. 옛 이름은 목록에서 빼고 관측 기간 동안 호출만 받는다(별칭) | 실제 대화 확인 |

### 9-1. 쓰기 실행의 보장 — 지금 있는 것과 더할 것

지금 실행층이 이미 지키는 것(새 틀은 이것을 **우회하지 않고 지난다**):
- 승인은 **정규화한 인자 스냅샷**(`params_json`)에 묶이고, 서버는 저장된 인자로만
  실행한다(`mcp_safety_gate.execute_approved`) — 승인한 것과 다른 것이 돌 수 없다.
- 승인은 **사람이 웹에서** 한다(LLM 재호출과 별개). 승인자 신원이 없거나 지금 없는
  계정이면 실행하지 않는다. 승인자의 그룹 밖 대상이면 거절하고 대기로 되돌린다.
- 유효시간(`_CONFIRM_TTL_SEC`)이 지나면 만료, 실행은 선점(`approved → executing`)으로
  한 번만 — 두 번 누른 승인이 두 번 실행되지 않는다.
- 시간 지정 출력은 앱 재시작 너머로도 끝난다(E2E `test_control_sequence_timer` c4).

새 틀이 더할 것:
- 안쪽 도구에 해석된 **id** 를 넘기므로 스냅샷에 이름이 아니라 대상 자체가 묶인다.
  승인 화면에 해석 결과(§2-4)의 `path` 를 함께 보인다.
- **실행 직전 재검증**: 승인 뒤 대상이 지워졌거나 종류가 바뀌었으면 돌리지 않는다.
- `preconditions`(§3-2): 삭제·끄기 전에 그 대상을 참조하는 **활성 자동화**를 찾아 승인
  화면에 보인다. 위험도는 operation 이름만이 아니라 지금 상태로 정한다.
- 물리 제어의 종료 보장(데몬 타이머·재시작 복구·종료 실패 감사)은 지금 구현을 그대로
  쓰고, 5단계 전에 그 경로마다 E2E 가 있는지 확인한다(없으면 그것부터).

### 9-2. 1단계(안전 계약) 완료 기준 — 2차 검토 반영

1단계는 명부 파일을 만드는 단계가 아니라, **지금 승인 정책 → 명부 → 실제 실행의 연결을
기계적으로 확인하고, 확인이 실패하면 새 쓰기 경로가 켜지지 않게(fail-closed)** 만드는
단계다.

| 항목 | 통과 기준 | 어떻게 |
|---|---|---|
| 매핑 완전성 | 지금 쓰기 도구마다 **정확히 한 번** 매핑 · 미매핑·중복·없는 도구 참조 0 | 카탈로그·`tool_registry` 에서 명부를 대조하는 테스트 |
| 승인 동등성 | 설명되지 않은 완화 0 | 정책 칸을 따로 비교하지 않는다 — 새 틀은 승인 판정을 **새로 하지 않고** 안쪽 도구 이름·인자로 지금 게이트(`_execute_tool` → `gate`)를 그대로 부른다. 테스트는 쓰기 operation 마다 "게이트가 **안쪽 도구 이름**으로, **해석된 id 가 든 인자**로 한 번 불렸다" 를 확인한다(같은 코드 경로 = 같은 승인 방식·승인자 요건·만료·재사용 방지) |
| 빠져나가는 길 없음 | 공개된 쓰기 operation 이 명부 밖 실행 경로로 가지 않는다 | 도메인 도구의 실행 진입점이 `_execute_tool` 재귀 하나뿐임을 소스로 고정 |
| 승인 스냅샷 | 승인 내용과 실행 내용 불일치 0 | 지금 불변식(저장된 인자로만 실행) 회귀 + 도메인 경유 호출로 같은 시험 |
| 다중 대상 쓰기 | 의도하지 않은 다중 대상 0 | `expand_write` 없는 operation 에 후보 여럿·목록·그릇이 오면 **게이트 앞에서** 거절. 허용된 배치(`add_schedule_batch`·`apply_plot_resources` 등)는 대상 목록·개수가 인자에 들어가 스냅샷에 고정된다 |
| fail-closed | 위 검사 중 하나라도 실패하면 도메인 쓰기 operation 이 목록·실행에서 빠진다 | 기동 시 명부 검사, 실패 시 읽기만 노출 |
| 실행 시 대상 재검증 | 승인 뒤 해석된 대상이 지워졌거나 종류·이름·상위 경로가 바뀌었으면 **실행하지 않고 재승인**을 요구한다 | 스냅샷에 해석 결과(§2-4)를 싣고, 승인 실행 직전에 같은 id 로 다시 풀어 비교 |
| 제어 경로 회귀 | MCP 변경이 데몬 제어 보장을 바꾸지 않았다 | 단계마다 기존 E2E(`test_control_loop`·`test_control_sequence_timer`)와 단위 스위트를 나스 CI 로 돌린다 |

**차단 조건 — 하나라도 나오면 그 단계는 통과 실패다(평균·비율로 상쇄하지 않는다):**
승인 정책 완화 · 승인 스냅샷과 실행의 불일치 · 무단 다중 대상 쓰기 · 불완전한 매핑(미매핑·
중복·없는 도구) · 승인 뒤 바뀐 대상의 실행.

**1단계 밖으로 둔 것(뒤 단계의 전제):**
- **의존 상태(관련 자동화·연결)까지 스냅샷에 싣고 바뀌면 재승인** — 대상 자체의 재검증은
  1단계에 있다(위 표). 의존 상태는 지금 승인 체계 전체(모든 도구)를 바꾸는 일이라 5단계
  (설정·물리) 전에 따로 한다. 그때도 원칙은 같다 — 바뀌었거나 확인하지 못했으면 계속 실행하지
  않고 재승인을 요구한다.
- **활성 자동화 의존성 표시** — 참조는 id 컬럼·JSON 옵션 문자열·시퀀스/함수/일정 간 간접
  참조로 흩어져 있어 완전성을 증명하기 어렵다. 그래서 **위험을 낮추는 근거로 쓰지 않는다**:
  "의존 없음" 으로 판정해 승인을 생략하는 일은 없고, 조회 실패·불확실은 "확인 못 함" 으로
  표시한다. 삭제·끄기는 지금도 승인 대상이다.
- **시간 지정 출력의 종료 보장 강화**(서버 재시작·중복 작업자·종료 직전 장애·시간대·
  예약 수정·시계 이상, 영속 watchdog, 복구 불가 시 안전 상태) — MCP 틀이 바꾸지 않는
  데몬 제어의 문제다. 별도 점검으로 추적하고(책임 경계를 나눈다), 5단계(물리 제어
  operation)는 그 결과를 전제로 한다. MCP 변경이 기존 보장을 훼손하지 않았는지는 위 표의
  제어 경로 회귀가 단계마다 확인한다.

결정론적 서버 테스트(위 표)와 실제 모델 벤치마크(§8)는 섞지 않는다. 0건은 "테스트에서
발견되지 않았다" 는 뜻이다.

## 10. 결정할 것

1. 도구 14개 구성(§4)과 그 배정(부록 A). (13개로 시작해 F-7 에서 `remove` 를 더했다.)
2. 크기 상한(가벼움 3,500 · 운영 6,000 · 설정 9,000), 그리고 검증 뒤 가벼움을 운영에 합칠지.
3. 검증 통과 조건(§8)과 쓸 모델.
4. 옛 도구 이름을 받아 주는 기간.
5. 0단계의 **도구 수 동결을 지금 바로 걸지.**

**보류된 다음 단계** — 이름 사전·호출 기록 활용(자주 나는 오탐·유의어·자주 쓰는 조합):
`mcp-name-dictionary-plan.md`. 도메인 틀을 기본으로 켜고 안정화한 뒤 착수한다(2026-10-14 사용자 결정).

## 부록 A. 지금 도구 → 새 도구

| 새 도구 | 지금 도구 |
|---|---|
| `overview` | get_place_overview · get_system_brief · get_anomalies · get_crop_status · get_control_state · get_active_functions_summary · get_facility_capacity · analyze_system_failure · get_system_update_status · get_storage_tier_status · list_pending_confirmations |
| `measure` | get_sensor_reading · get_sensor_detail · get_device_measurements · get_zone_sensor_summary · get_device_freshness · get_energy_report · get_cumulative_status · get_output_state |
| `weather` | get_weather · get_weather_forecast · get_local_time |
| `find` | resolve_target · search_devices · get_device_list · get_spatial_tree · list_geo_maps · list_plots · get_map_equipment · get_device_location · nearest · distance_between · get_address · get_function_list · list_programs · list_dashboards · list_tabs · list_widget_types · list_device_types · list_ai_agents · list_gis_inputs · list_lookup_sources · list_library_source_types |
| `detail` | get_device_detail · get_plot · get_plot_history · get_function_detail · get_program · get_widget · get_map_equipment_detail · get_device_type_options · propose_plot_split(미리보기) |
| `records` | search_notes · get_note_attachment · list_notices · list_plot_journals · get_plot_journal · search_schedule · list_advice · knowledge_search · search_archives · get_archived_document · list_ai_entries · query_data_source · query_reference_table · smartfarmkorea_lookup |
| `screen_view` | get_screen |
| `help` | get_tool_detail |
| `control` | operate_device · schedule_device_control · activate_function · deactivate_function · modify_function_options · modify_sequence_schedule · modify_sequence_step · configure_sequence_day · respond_to_confirmation(승인 응답) |
| `record` | create_note · modify_note · create_notice · modify_notice · delete_notice · create_plot_journal · add_schedule · add_schedule_batch · edit_schedule · delete_schedule · submit_advice · knowledge_shelve · archive_note · restore_note_from_archive · set_document_tier · delete_archive |
| `cultivate` | create_plot · modify_plot · end_plot · delete_plot · copy_plot · apply_plot_split · add/remove/reschedule/confirm/undo_plot_stage · set_plot_stage_guidance · apply_plot_resources · save_plot_schedule_as_program · create_program · modify_program · delete_program |
| `configure` | create/modify/delete_input · create/modify/delete_output · create_function · delete_function · create_sequence_function · create/modify/delete_gis_input · activate_gis_input · create/modify/delete_widget · create/modify/delete_tab · create/modify/delete_ai_agent · set_device_location · delete_geo_shape · configure_library_source · set_tool_profile |
| `screen` | screen_action |

## 부록 B. 진행 중이던 MCP 작업의 자리 (2026-10-13 다른 세션 회신)

틀이 들어올 때까지 따로 고치지 않고, 아래 자리로 옮긴다.

| 작업 | 새 틀의 자리 |
|---|---|
| 예보가 시설 예보 파일을 먼저 쓰게(Open-Meteo PR 5) | `weather(op=forecast)` 의 자료 출처 — 새 operation 안에서 |
| 비슷한 이름 퍼지 매칭(리허설 D) | 실행층 대상 해석(§2-2 4단계) — 도구별로 하지 않는다 |
| `list_plots` 응답 토큰 한도 | operation 별 응답 상한(§5) |
| `measurement_type` 의 강수 라벨 | 공통 어휘 `measurement`(§3) |
| 운영 상한 +110(`FORECAST_PLACE_ALLOWANCE`) 상쇄 — PR #195(미병합, 인자 설명 축약) | 새 상한(§4)으로 대체. #195 는 지금 표면의 임시 축약이라 병합 여부는 사용자 판단 |
| OAuth 거절 문구 · 웹 UI 언어 안내 · 시뮬레이션 설정 칸(E8-2 2단계) · Open-Meteo PR 2~4·6 | MCP 표면 밖 — 그대로 진행 |

## 부록 C. 검증 시나리오 후보 — 리허설에서 고치지 않고 남긴 결함 (2026-10-13 리허설 세션)

§8 검증의 질문 목록에 넣는다. 새 틀에서 각 줄이 **구조로** 풀려야 한다(도구별 예외 없이).

| # | 결함 | 새 틀에서 풀리는 곳 |
|---|---|---|
| 1 | 모르는 대상 인자가 무시돼 농장 전체가 돌아옴 · `get_weather` 가 `place` 를 안 받음 | 공통 `target` + 실행층 해석(§2·§3) |
| 2 | 이름 퍼지(영향→영양, 육류장3→육묘장3, 서량→설향, 산포장→3포장)·일본어 혼합 표기 | 대상 해석 4단계(§2-2) — 한 곳에서 |
| 3 | `measurement_type` 표시 라벨(precipitation)로 저장명(length) 채널을 못 찾음 | 공통 어휘 `measurement`(§3) |
| 4 | 구획 33개에서 `list_plots` 가 6,000 을 넘어 단계·종료 점검이 잘림 · 구역 요약은 62곳 중 25곳만 | operation 별 응답 상한 + 그릇 펼치기 상한(§2-3·§5) |
| 5 | 꺼진 모듈 거절 문구가 OAuth 연결에서도 "API key" 로 시작 | 공통 응답 모양의 거절(§5) |
| 6 | 시뮬레이션 장치를 이름·드라이버로 구분 못 함 | 대상 속성(장치 종류) — 해석 결과에 싣는다 |
| 7 | 숨은 탭의 오래된 화면 상태 · 사용자 연결 없는 외부 연결에서 `get_screen` 거부 | `screen_view` operation 의 응답 계약 |
| 8 | 도구가 고른 날씨 장치와 제어 실외 정본이 다름 · 대지 날씨원 지정 없음 · 예보가 Open-Meteo 하나 | `weather` operation 의 출처 규칙(하나로) |
| 9 | 지연 로딩·tool_search 부정확 | AoT 밖(Claude 앱) — 도구 수가 줄면 영향도 준다 |
| 10 | `modify_note` 가 남의 노트·작성자 불명 노트를 승인 대기로 | `record` operation 의 승인 선언 |

응답을 키운 리허설 필드(#141~#191: 날씨 `source` 세부, 구역 요약 `placement` 계열, 구획 `end_check` 계열, `get_screen` 동기화 표시, `get_anomalies` 목록, 장치 `simulated`, 화면 조작 응답 등)는 §5 응답 규칙으로 옮길 때 **값은 남기고 설명 문장은 `help` 로** 보낸다.

## 부록 D. 벤치 결과 (2026-10-14, 구현 브랜치 `claude/mcp-domain-frame`)

조건: 같은 DB 사본을 두 서버에 바이트 동일하게(지금 표면 main `ca7fd1a2e` · 새 틀
`c6e11b2c7`), `claude -p` Sonnet, 도구 검색 끔, 쓰기 꺼진 서버, 질문 32개 × 2회 × 운영·가벼움.
네 실행 모두 같은 규칙으로 채점. 질문·채점: `.local/plans/2610_mcp_frame_scenarios_v1.yaml`,
장치: `.local/bench/bench6_env.sh`·`run_bench6_*.sh`·`score6.py`.

| (64회씩) | 성공 | 입력 중앙값 | 입력 평균 | 호출 평균 |
|---|---|---|---|---|
| 지금 표면 · 운영 | 64 | 83,724 | 87,922 | 2.77 |
| 새 틀 · 운영 | 62 | 51,580 (−38%) | 59,145 (−33%) | 2.67 |
| 지금 표면 · 가벼움 | 62 | 45,828 | 71,765 | 4.48 |
| 새 틀 · 가벼움 | 62 | 48,214 | 63,313 (−12%) | 3.14 |

- 새 틀 운영의 실패 2건(f15·f32)은 고쳤다(아래 7). 고친 판 `008787053` 으로 해당 4문항 × 2회
  × 두 키 = 16회 중 15회 성공(남은 1건은 "수확 일정" 을 구획 단계로 해석 — 모델 해석).
- 목록 크기(관리자, 카탈로그): 가벼움 6,835 · 운영 7,596 · 설정 12,277 — 래칫 테스트로 고정.
- **이 하네스에서는 지금 표면도 거의 다 성공한다** — 사용자의 실패는 claude.ai 에서 났다.
  그래서 아래 재생을 함께 본다.

**claude.ai 실제 실패 재생**(2026-10-12~13 읽기 61건 — 옛 호출을 같은 안쪽 도구의 operation 으로,
대상 인자는 `target` 하나로): 성공 45 + 올바른 되묻기 2(지금 표면에서는 61건 모두 실패).
남은 14건 중 7건은 대상 없이 부른 호출.

**벤치가 찾아 고친 틀 결함**(전부 틀 규칙으로, 도구별 예외 없이):
1. HTTP 서버에서 dispatch 가 앱 컨텍스트 밖 — 이름 해석이 전부 실패.
2. 이름을 `query` 에 넣는 습관 → 대상을 받고 검색어가 없는 op 에서는 query 가 대상.
3. 기간을 못 받는 안쪽 도구(일정) → 명부 `period_field` 로 틀이 거른다.
4. 펼치는 깊이 — 목록 인자면 구역까지 한 번에, 아니면 대지로 따로.
5. 측정 일상어 → 저장 이름(`domain/vocab.py` 한 곳).
6. 트리거·조건·PID 함수를 대상으로 못 찾던 퇴행 → 공용 함수 해석기 연결.
7. 이름만 받는 안쪽 인자에 id 를 넣자 다른 구역(3-1 → 1-3)이 풀렸다 → 같은 대상으로
   되돌아오는 이름만 넘기고, 없으면 실행하지 않는다.
8. 작은 것 → 감싸는 장소, 장소 → 안의 장치·구획, 목록 op → 장소로 거르기, 이스케이프된 한글·
   앞부분 일치 이름.

**결정(2026-10-14)**: 크기 상한 운영 8,000·설정 13,000 · 가벼움은 운영과 합침 · 구현 브랜치 머지.
**남았던 결정**: ① 크기 상한 — 목표(운영 6,000·설정 9,000)에 못 미치고 남은 무게는 op 마다의
"언제 쓰나" 한 줄이라 지금 값(7,596·12,277)을 상한으로 할지 ② 가벼움을 운영에 합칠지(새 틀에서
차이가 작다) ③ 다음 단계 — 읽기 응답 모양(§5), 기록 쓰기의 실제 승인 흐름 확인, claude.ai 에서
사람 손 확인, 그 뒤 기본값 전환.

## 부록 E. claude.ai 웹 시험 (2026-10-14, Sonnet 5.5, 대화 2개)

개발 서버(main = #199·#200) + `AOT_MCP_SURFACE=domain`. 기록 원문은 리허설 세션의
시험지(`AoT_dev/plans/2026-10-14_mcp_domain_surface_test.md`). 어제 1시간 실패한
"우리 농장 지금 어때?" 는 30초 안에 통과했고, 이름 해석(띄어쓰기·붙여쓰기·일본어·경로·
지도 이름·같은 이름 구분·없는 이름)은 대체로 통과했다.

부분 실패와 처리(호출 기록 `mcp_audit_log` 로 원인 확인):

| 시험 | 증상 | 원인 | 처리 |
|---|---|---|---|
| A4 | "내일 낮 이후는 모른다" | `period` 가 안쪽 인자로 그대로(`hours='tomorrow'`) | 명부 `period_form` + `vocab.period_to` 변환, 모양 없는 기간은 명부 검사가 막는다 |
| B4 | 밸브 상태 19개 중 5개 | 장치마다 따로 펼침(상한 5), 안쪽은 `device_ids` 10개씩 받는다 | 목록 인자로 10개씩 나눠 전부(상한 40). `output_state` 의 잘못된 'none'(대상 없이 부르면 오류) 제거 |
| A2 | 구획 13개 중 10개, "나머지는 원하면" | 안쪽 개요가 10개만 싣고 나머지를 말하지 않음. 안내는 옛 이름(`use_tool: get_plot`) | 개요가 나머지 이름(`others`)을 싣는다. 안내 칸을 도메인 operation 이름으로 바꾼다 |
| A3 | 어느 육묘장인지 안 밝힘 | 안쪽 경로에 지도 이름 없음 | 응답에 `read_as`(해석한 대상 — 경로 맨 앞은 지도 이름 — 과 읽은 기간). 장치 경로에도 지도 이름 |
| B3 | (통과했지만 이름 검색 우회) | '온습도_7' 의 `_` 를 낱말 구분으로 안 봄 | `_` 를 구분 문자로(`-` 는 아니다 — '3-1' 과 '1-3') |
| B8 | 기상청 → 다른 출처로 대신 | 모델이 해석을 안 부름. 옛 리졸버 후보는 모양이 달라 비어 있었고 'AI 판단 제외' 장치도 내밀었다 | 옛 리졸버 후보를 틀의 모양으로 바꾸고 제외 장치를 뺀다. 한 덩이 물음이 제외 장치에만 맞으면 "꺼져 있다" 고 말한다 |

고치지 않은 것:
- B4 의 "밸브" 를 장치 종류로 거르기 — 데이터에 종류가 없다(밸브 출력이 `virtual_on_off_single`,
  이름 `v311`). 모델이 이름 첫 글자로 추측한 것은 데이터의 한계다.
- A3 의 답에 `**` 가 보임 — 클라이언트 표시 문제(서버 응답과 무관).
- B7 상세 22.5초 — 재현 안 됨(다시 재면 1.5초, 두 번째 0.2초). 데몬 재시작 직후였다.
  호출 기록의 `duration_ms` 로 지켜본다.
- 미러 계열 센서가 08:03 에 멈춤 — ChirpStack MQTT "Network is unreachable"(환경). 이 틀과 무관.
- MCP 컨테이너의 `AOT_MCP_SURFACE=domain` 은 임시 override 로 넣었다 — compose 로 다시 만들면
  빠진다. 기본값을 켤 때 함께 정한다.

## 부록 F. 사용자 직접 시험 (2026-10-14, 아이폰 Safari, 영양 대시보드)

같은 모양의 결함이 셋 연달아 나왔다 — **안쪽 도구는 대상 칸 이름(`dashboard`·`widget`)으로
넘기라고 안내하는데 틀이 그 이름을 받지 않았다.** 틀은 대상을 `target` 하나로 받고 종류별 안쪽
칸(`target_arg`)에 채우는데, 그 칸 이름이 입력 허용 목록에 없었다. 안쪽 도구의 안내문은 안쪽
이름을 쓰므로 안내와 입력이 서로 모순됐다. 대상 해석기도 대시보드·탭·위젯을 몰라서 '영양' 은
늘 지도, '환경'(위젯) 은 센서 '환경센서:meteo' 로 풀렸다.

처리(사건별이 아니라 틀 규칙으로):
- **안쪽 대상 칸 이름도 대상으로 받는다** — 그 칸이 받는 종류로만 좁혀서(`dashboard='영양'` 은
  대시보드). `target` 과 함께 주면 거절. `help` 가 칸 목록(`target_slots`)을 보인다.
- **대시보드·탭·위젯은 그 종류를 받는 operation 에서만 찾는다** — 늘 찾으면 모든 읽기에서 '영양'
  이 모호해진다. 위젯은 이름·전체 id·화면이 보이는 짧은 id(`#fe10a462`), 경로는
  `dashboard > 영양 > 환경`.
- **호출에 적힌 종류로 좁힌다** — `page='dashboard'`, `kind='widget'`(안쪽 `kind` 는 지도 대상용이라
  떼어 낸다). 쓰기는 펼치지 않으므로 그 operation 이 받지 못하는 종류는 후보에서 뺀다.
- **장소를 받는 읽기는 지도를 안의 장소로 펼친다** — 장치마다(예보) 또는 '대상 없음 = 농장 전체'
  (개요) 로 빠지지 않는다. 펼칠 때 목록 인자는 10개씩 나눠 전부(상한 40).
- **틀이 거절한 호출도 호출 기록에 남긴다**(`tool_name='screen.act'`, `call_state='refused'`) —
  이번 모순은 기록에 없어 대화 쪽에서만 보였다.

고치지 않은 것:
- `measure.history` 의 날짜 구간(지난주 대 이번 주) — 안쪽 도구가 '지금부터 거슬러 N' 만 받는다.
  구간을 받으려면 안쪽 도구에 인자를 더해야 하고, 인자 이름을 늘리는 일은 사용자 결정이다.
- 도구 호출이 "진행 중" 으로 멈춤·읽기 도구 허락 30초 시간 초과 — 서버 기록에는 그 호출들이 수
  밀리초에 끝나 있다. claude.ai 쪽(허락 창·연결)의 일로 보인다. "전체 허용" 이 안 먹는 것도
  클라이언트 설정이다(도메인 읽기 도구에는 `readOnlyHint` 가 붙어 있다).
- 시설 경로로 하이라이트하면 지도 위젯 전체가 강조된다 — 지도 위의 대상은 지도 위젯을 가리키는
  것이 지금 설계다(그래프를 원하면 위젯 이름으로).

### F-2. 같은 시험의 둘째 묶음(응답이 실제로 한 일을 말하는가)

| 증상 | 원인 | 처리 |
|---|---|---|
| `queued`·`sent` 인데 `call_state: executed` | 화면 조작 상태 → call_state 표에 두 상태(`needs_confirmation`·`expired`)뿐 | `CALL_STATES` 에 `queued`(화면에 넘겼으나 실행 확인 전), `sent`·`queued`→queued, `rejected`→approval_rejected, `error`→failed |
| `navigate` 에 준 대상이 조용히 버려짐 | 페이지 이동은 `item` 을 쓰지 않는다 | 이동은 하되 `ignored: {args, note}` 로 쓰지 않은 인자를 밝힌다(대상을 보이려면 open_map_item) |
| 핀이 없어 지도 위젯 전체를 강조하고 `success` | 화면이 대체 동작을 했는데 서버가 그대로 성공으로 | `status: partial` + `done: "highlighted the whole map widget instead"` |
| `find.plots` '장미' 에 밸브 8개 | 읽기 후보를 종류로 거르지 않았다 | 바로 받는 종류가 후보에 있으면 그것만. 없고 후보가 전부 같은 장소 하나 안이면 그 장소를 읽는다(`read_as.why`) |
| 오류 응답에 엉뚱한 `read_as` | 안쪽이 거절한(쓰이지 않은) 대상을 실었다 | 안쪽이 실패·거절하면 `read_as` 를 싣지 않는다 |
| 기간 FROM/TO 설명이 목록과 도움말에서 다름 | 도움말이 안쪽 인자 설명('1h, 24h, 7d')을 그대로 | 공통 낱말은 목록과 같은 설명 + 이 operation 이 읽는 방식(`here`: "a date or FROM/TO reads from that start up to now") |

남은 것: '장미' 의 밸브 영역 도형 8개 중 하나(`v장미08`)가 지도상 대지 밖이라 "전부 한 곳 안" 이 성립하지
않아 되묻는다(데이터). 옛 리졸버의 후보 위치는 '장미원' 이라 말하는데 장소 색인은 그 도형을 대지
'붕어섬생태공원' 아래로 본다 — 위치를 말하는 기준이 둘이다. 구획 목록에 작물 이름 검색은 없다(안쪽 인자
추가 = 사용자 결정).

### F-3. 사용자 결정으로 더한 두 기능 (2026-10-14)

- **구획 목록의 작물 이름 검색** — `list_plots(query=…)`: 작물·품종·구획 이름의 일부(띄어쓰기 무시).
  도메인 `find.plots` 의 `query` 가 그대로 간다(대상으로 바꾸지 않는다). 재배 중인 것이 없으면
  예정(시작 전)·종료 구획 중 맞는 수를 말한다 — 로컬 '장미' 구획 둘은 2027-03-15 시작 예정이었다.
- **이력의 날짜 구간** — `get_sensor_detail(time_range='FROM/TO')`: 새 인자를 두지 않고 기존
  `time_range` 가 날짜도 받는다(옛 목록 운영 상한이 9토큰 남아 있었다 — 인자 둘은 +80).
  그곳 현지 날짜로 읽고 끝 날짜를 포함, 92일 상한, 응답에 읽은 구간(`period`). 도메인
  `measure.history` 의 `period` 는 새 모양 `range` 로 바뀐다(날짜·어제·이번 주·FROM/TO →
  구간, 24h·7d → 지금까지). 시간대 해석은 `device_tz.location_window` 한 곳.
  지난주와 이번 주는 두 번 부른다(실측: 육묘장3 온도 10/1~7 평균 16.75 · 10/8~13 평균 17.62).

### F-4. 스키마에 없는 인자는 없는 것이다 (2026-10-14 사용자 시험)

화면 이동이 "action must be one of …" 로 끝내 안 됐다. 호출 기록(틀의 거절 기록 포함)을 보니 모델은
**스키마에 있는 인자만** 썼다 — `op`·`map_op`·`target`·`value`. 틀은 고유 인자 중 필수인 것만 스키마에
싣고 나머지를 `help` 로 넘겼는데, 화면 조작의 `action`·`page`·`confirm_token` 은 필수로 적혀 있지 않았다.
모델은 `action` 을 `map_op`·`value` 에 JSON 으로 넣어 보다가 멈췄다(같은 날 앞선 대화의 다른 모델은
스키마 밖 인자도 넣었다 — 모델마다 다르니 기대지 않는다).

- 명부에 **`shown`** — 필수는 아니지만 동작에 꼭 필요한 고유 인자. 스키마에 싣는다(설명 포함).
  화면 조작(action·page·confirm_token), 고치기의 바꿀 내용(note_edit 의 note, input/output/gis
  edit 의 params, widget_edit 의 options …), 시간·길이(output_timed·device_schedule·sequence_*).
- 고유 인자 이름을 전부 실으면 운영 8,357 로 상한을 넘는다 — 그래서 고른다.
- `map_op` 설명을 "지도 조작일 때만, action 이 아니다" 로.
- 목록 크기: 운영 7,910 · 설정 12,793(상한 8,000 · 13,000 안, 래칫을 일부러 올림).

### F-5. 화면 따라가기는 틀이 푼 대상으로 (2026-10-14)

"지도 위젯에서라고 해도 텍스트로만 설명한다" — 원인 둘.
1. 자동 따라가기가 **안쪽 도구 이름 목록**(`FOLLOW_TOOLS`)에 묶여 있었다. 도메인 읽기의 상당수(이력·날씨·
   장치 위치, 작물 이름으로 찾은 구획)는 안쪽 도구가 목록에 없거나 대상 인자가 달라 따라가지 않았다.
   → 틀이 **푼 대상 하나**(장소·구획·장치)를 어떤 읽기 operation 이든 연다(`dispatch._follow` →
   `screen_follow.follow_resolved`). 펼쳐 읽으면 사용자가 말한 그릇을, 대상 없이 찾은 결과가 하나뿐이면
   그것을. 안쪽 호출에는 `_show_on_screen='off'` 를 실어 창이 두 번 열리지 않게 한다. 막는 겹(화면 조작
   허용·확인·기기별 따라가기)은 그대로.
2. 앞서 받은 데이터가 대화에 남아 있으면 모델은 도구를 부르지 않는다 — 서버가 끼어들 자리가 없다.
   → `screen.act` 에 **대상만 주면** 종류로 동작을 정한다(`defaults_by_kind` — 장소·구획·장치=지도 창,
   위젯=강조, 대시보드=이동). 도구 머리에 "보여 달라고 하면 답을 알아도 부를 것" 한 줄.

비용: 자동 따라가기는 왕복을 늘리지 않는다(같은 호출 안, 화면 실행을 기다리지 않음). 응답에 붙는
`screen` 칸의 설명(`_WHY`)을 330자 → 80자로 줄였다 — 따라갈 때마다 대화에 남아 이후 요청마다 다시 실린다.
명시적 보여 주기(`screen.act`)는 왕복 1회.

### F-6. 크기 상한 9,000 · 15,000 (2026-10-14 사용자 결정)

"너무 압축된 설명으로 AI 들이 혼란스러워 한다 — 옛 20,000 · 40,000 에 비하면 아직 적절하다." 상한을
운영 9,000 · 설정 15,000 으로 올렸다. 늘어난 여유는 설명 문장보다 **스키마에 동작에 꼭 필요한 고유 인자를
싣는 데** 썼다 — 오늘 시험의 혼란은 모두 "스키마에 없는 인자는 모델이 쓰지 않는다" 였다.

- 넣은 것(그 인자 없이는 본래 일을 못 하거나 자주 쓰는 필터): 메모·일정·공지 쓰기·고치기의 내용 칸,
  일지 만들기 단위, 시퀀스 요일, 승인 여러 건, 단계 일정 옮기기(`days`·`shift_days`)·확정 날짜, 구획 종료
  사유, 구획 목록 `include_ended`·`with_sensors`, 일지 조회 날짜, 일정 조회 `include_past`, 신선도
  `include_fresh`, 구획·프로그램·장치·함수·위젯·탭·시퀀스 만들기의 핵심 필드, 장치 위치 지도.
- 뺀 것(드문 세부 — `help` 로): 구획 나누기 폭·각도, 외부 자료원 설정 12개 인자, 지식 보관의 출처 칸, AI
  에이전트 세부, 위젯 위치·크기, 시퀀스 스텝 세부, 조언 제출 세부.
- 고유 인자를 전부 실으면 운영 10,405 · 설정 17,555 — 새 상한으로도 다 못 싣는다.
- 결과: 운영 8,709 · 설정 14,224.

### F-7. 지우기는 따로 — '항상 허용' 이 먹게 (2026-10-14 사용자 결정)

현장 작업자는 음성으로 쓰므로 허락 버튼을 누르기 어렵다. 그런데 claude.ai 커넥터에서 모든 도구를
'항상 허용' 해도 새 대화마다 다시 물었다.

근거(추측 아님):
- Anthropic 커넥터 심사 기준 — 도구 표시가 Claude 의 자동 허가를 정한다. 읽기 전용은 매번 묻지 않고
  파괴적인 도구는 늘 묻는다. MCP 규격에서 `destructiveHint` 가 없으면 기본값은 true(파괴적)다.
  쓰기 도구 5개에는 표시가 아예 없었다 — 화면만 바꾸는 `screen` 도 파괴적으로 읽혔다.
- 사용자 보고(claude-ai-mcp #1032, 공식 답 없음): '항상 허용' 은 도구 설명과 최상위 인자 이름·설명에
  묶인다 — 한 글자만 바뀌어도 그 도구의 허가가 풀린다. 오늘 #199~#210 이 설명을 여러 번 바꿨다.
  표시(annotations)·`title` 은 묶이지 않는다고 한다. 우리 설명은 해시 시드가 달라도 바이트 동일했다.
- 프로젝트 안 대화는 새 대화마다 허가가 풀린다는 보고(claude-code #19731, 수정 안 됨)도 있다.

처리:
- 지우는 operation 14개(안쪽 `delete_*`·`remove_plot_stage`)를 새 도구 `remove` 로 옮겼다. operation
  이름은 그대로다. `remove` 만 `destructiveHint: true`, 나머지 쓰기 도구 5개는 `destructiveHint: false`
  를 **명시**한다(빠지면 기본값이 파괴적). 읽기는 `readOnlyHint: true`. 모두 `title` 이 있다.
  `control`(장치 작동)도 파괴적이지 않음으로 둔다 — 사용자 결정 "허용하면 자동 승인" 을 따랐다.
- 끝내기(`plot_end`)·보관(`note_archive`)·되돌리기(`stage_undo`)는 자료를 남기므로 지우기가 아니다.
- 계약 검사: 지우는 안쪽 도구(`delete_`·`remove_` 로 시작)는 `remove` 에만 있어야 한다. 섞이면 그
  도구의 표시가 거짓이 되므로 쓰기 operation 이 켜지지 않는다(fail-closed).
- AoT 안의 승인(안쪽 도구의 승인 요구)은 바뀌지 않는다 — 음성으로 승인하면 AoT 가 처리한다.
- 목록 크기 운영 8,929 · 설정 14,506(상한 9,000 · 15,000). 운영 여유가 71 로 줄었다.
- **설명을 바꿀 때마다 그 도구의 '항상 허용' 이 풀린다.** 설명 수정은 모아서 한 번에 반영한다.


### F-8. 화면 조작은 action 이 대상 종류를 정한다 (2026-10-14 사용자 시험)

"대시보드 상단 탭(김제·영양 …)을 바꿔 달라" 에서 모델이 `screen.act(action=modal_tab, target='영양')`
를 불렀다. '영양' 은 대시보드와 입력 탭 둘이라 되묻기가 돌아왔고(후보에 종류·경로는 있었다), 모델이 입력 탭을
골라 그 id 가 `tab` 칸에 들어갔다. 그런데 `modal_tab` 의 `tab` 은 **열린 지도 창의 탭 이름**(현황·환경 …)이지
페이지 탭이 아니다 — 틀이 안쪽 칸 이름 하나(`tab`)를 action 과 무관하게 같은 종류로 풀었다.

- 명부 `kinds_by_arg` — 인자 값이 받는 대상 종류를 정한다. 화면 조작: navigate = 대시보드·페이지 탭,
  open_map_item·open_notes = 지도 위의 것, highlight = 위젯·지도 위의 것, open_widget_settings·map_control =
  위젯, modal_tab·close_modal·toast·reload = 대상 없음.
- 대상 없음인 값에 `target` 을 주면 실행하지 않고 어느 action 이 무엇을 받는지 말한다. 그 값에서 대상 칸
  이름(`tab='환경'`)은 풀지 않고 글자 그대로 넘긴다.
- 되묻기 문장에 후보의 경로를 싣는다("'영양' names 2 different things (dashboard > 영양; input tabs > 영양)").
- `find.dashboards` 의 한 줄을 "대시보드 = 대시보드 페이지 위쪽의 탭" 으로. 대시보드·탭 목록 조회
  (`find.dashboards`·`find.tabs`)는 이미 있었다 — 모델이 찾지 못한 것이다.

같은 시험의 둘째 보고("자동 승인인데 공지 작성에서 승인을 물었고 30초 안에 못 눌러 취소")는 서버에 호출이
**한 번도 오지 않았다**(호출 기록에 `create_notice`·`record.notice_add` 없음) — claude.ai 의 허락 창에서
멈췄다. 직전 #212 가 `record` 의 설명을 바꿨으므로(지우기를 떼어 냄) 그 도구의 '항상 허용' 이 풀렸거나,
커넥터를 다시 연결하기 전이라 표시 없는 옛 목록을 쓰고 있었던 것으로 본다. 다시 연결하고 '항상 허용' 을
한 번 더 지정해야 한다.

### F-9. 승인 흐름 — 사용자가 "승인" 하면 LLM 이 처리한다 (2026-10-14 사용자 시험)

예전 표면에서는 사용자가 "승인" 이라고 하면 LLM 이 `respond_to_confirmation` 으로 AoT 승인을 처리했다.
도메인 표면에서는 공지 작성이 승인 대기만 두 번 쌓이고 끝났다(호출 기록: `create_notice` 대기 →
`list_pending_confirmations` → `create_notice` 다시 대기). 원인 셋, 전부 틀:

1. 게이트의 안내문이 옛 이름(`respond_to_confirmation`, "같은 도구를 다시")이었다 → 승인 대기 응답에 이
   표면의 다음 단계 `next` 를 싣는다 — `control(op='confirm', target=<번호>, decision=…)`, 그다음 같은
   operation + 같은 인자 + `_confirmation_id`. 사용자 대신 승인하지 말라는 말은 그대로.
2. `control.confirm` 의 대상(승인 번호)을 해석기가 몰랐다 — 메모·공지·일정·일지·보관·승인·프로그램·
   도형·GIS 층·AI 에이전트(`ID_ONLY_KINDS`)를 받는 22개 operation 이 같은 상태였다 → 해석기가 못 찾은
   id 모양 값을, 그 종류를 하나만 받는 operation 에서는 그 종류의 id 로 넘긴다. 있는지는 안쪽 도구가
   본다. 승인 뒤 대상 재확인(`changed`)도 이 종류는 안쪽 도구에 맡긴다.
3. 다시 부른 호출의 `_confirmation_id` 를 틀이 버렸다(밑줄 인자는 넘기지 않았다) → 게이트 메타 인자
   (`_confirmation_id`·`_reason`·`_title`)를 넘긴다. `_agent_id` 는 서버가 정하므로 넘기지 않는다.

`test_mcp_domain_approval.py` 가 실제 게이트·승인 큐·처리기를 지나 끝까지 본다(대기 → 승인 → 실행,
승인 대기 1건).

### F-10. 처음 붙은 모델이 걸린 자리 (2026-10-14 리허설)

- **장소의 작물** — `overview.crops` 가 시설·농장 전체만 받아 '3포장 작물' 이 농장 전체의 앞 10건(39건 중)으로
  빠졌고, 모델은 3-1·3-2 구역마다 구획 목록을 다시 불렀다. 지도·대지·구역 대상은 그 자리의 구획 목록
  (`list_plots`)으로 보낸다(대지로 물으면 안의 구역 구획까지 나온다).
- **노트 사진** — 사진 파일 이름(`filename`)이 스키마에 없어 모델이 `query` 에 넣었다. 필수 인자로 스키마에 싣는다.
- **도구 스키마를 먼저 불러와야 한다** — claude.ai 가 도구 정의를 필요할 때 불러오는 방식이라 서버가 바꿀 수 없다.

### F-11. 거절 응답이 다음 호출을 알려 준다 (2026-10-14 무료 AI 시험 · #222 · #223)

무료 AI 로 시험한 두 세션(호출 27·34건, 질문 4~5개)이 한도에 일찍 닿았다. 호출 기록으로 본 원인은 응답
크기가 아니라 **호출 횟수**다 — 호출당 응답은 평균 750 토큰(10/10~14 중 최저), 응답 합계 25,714·17,468
토큰이었다. 호출마다 대화 전체와 도구 목록(약 9,000)을 다시 읽으므로 횟수가 소모를 정한다. 두 세션의 거절
8건 중 7건이 같은 모양이었다 — 지도 위 대상(장소·구획·기기)을 `action=navigate` 로 보냈다
(`navigate` 는 대시보드·페이지 탭 이동이다, F-8). 거절 문구가 "무엇이 아니다" 만 말해 모델이 다시 헤맸다.

처리(응답 쪽만 — 도구 설명·스키마·크기 불변이라 '항상 허용' 이 풀리지 않는다):
- **#222** — 그 거절에 `next` 를 싣는다. `why`("A site goes with action=open_map_item, not
  action=navigate.") 와 `resend`(`screen(op='act', action='open_map_item', target='김제 > 3포장')`).
  자동으로 고쳐 실행하지는 않는다(응답이 실제로 한 일을 말한다는 원칙).
- **#223 A** — 화면이 둘 이상 열려 있으면 안쪽 `screen_action` 이 화면을 정하지 못해 `failed` 가 난다.
  틀은 어느 화면인지 모르므로 `resend` 에 값을 넣지 못한다. 대신 `why` 끝에 "화면이 둘 이상이면
  `screen_view op=current` 의 `screen` 값을 더한다" 한 줄(`screen` 인자가 있는 operation 만).
- **#223 B** — 되묻기가 후보를 `dashboard > 영양` 경로로 보여 주는데 그 경로를 그대로 보내면
  `Nothing named '영양' in 'dashboard'` 로 거절됐다(표시 ≠ 입력). 후보로 보여 준 경로는 입력으로도
  받는다(`targets._screen_by_path`, 대소문자·공백 무시). 새 형식(한글 접두어 등)은 만들지 않았다.

claude.ai 시험 결과(같은 프롬프트, 7호출, 스키마 밖 인자 없음): 장소·기기 거절 안내, `screen` 안내 줄,
안내만 보고 한 번에 성공(`executed`), 되묻기 회귀 없음, `dashboard > 영양` 이동 — 모두 통과.

고치지 않은 것(알려진 한계):
- **입력 탭 후보로 이동 못 함** — `navigate` 에 `input tabs > 영양`(id 가 입력 탭의 것)을 보내면 경로는
  하나로 풀리지만 `No tab named '<id>'. Tabs here: …` 로 `failed`. 대시보드 탭 목록에서 찾는 것으로
  보인다(추정 — 코드로 확인하지 않았다). 입력 탭을 열려면 페이지가 따로 정해져야 한다. 고치려면 이동에 쓸
  페이지를 자동으로 채워 실행하거나(자동 교정) 안내를 하나 더 만들어야 하는데 둘 다 사용자 결정이다.
  '영양탭' 은 대개 대시보드를 뜻하므로 같은 증상이 호출 기록에 반복해서 나타날 때 다룬다.
- **호출 기록에 클라이언트·모델 칸이 없다** — `agent_id`·`transport`·`session_key` 뿐이라 무료 AI 세션과
  유료 클라이언트 세션을 가를 수 없고, 사용이 늘어 학습하려 해도 모델별로 모을 수 없다(2026-10-19 예약
  조사에서 확인).
- 성공한 도메인 호출은 안쪽 도구 이름으로만 남는다 — 틀이 거절한 호출만 바깥 이름(`screen.act`)으로 남아,
  자동 따라가기가 작동했는지 기록으로 가르기 어렵다.

### F-12. modal_tab 안내가 노트 서랍을 안다 (2026-10-19 예약 · #226 후속)

#226 으로 노트 서랍이 맨 위일 때 지도 창의 탭 이름이 `dialog_tabs` 가 아니라 `underlying_dialog.tabs` 로
옮겨졌다. 코드를 찾아보니 이를 안내하는 곳은 도구·operation·인자 설명이 아니라 거절 응답에 싣는 한 줄
(`dispatch._kinds_by_arg_hint`, "screen_view lists them") 뿐이었다(`tab` 인자 설명은 "window tab" 으로 탭 이름 출처를
말하지 않는다). 그 줄을 "screen_view: dialog_tabs, or underlying_dialog.tabs under a notes drawer" 로 고쳤다.
응답 쪽만 바뀌어 도구 목록 크기(운영·설정)는 그대로이고 도구 설명·스키마가 불변이라 claude.ai '항상 허용' 도
풀리지 않는다. 미뤄 둔 다른 설명 수정은 찾지 못했다.

### F-13. 화면 따라가기 개선 — 기록·중복·합치기·대시보드 이동 (2026-10-20 · 조사 `.local/reports/screen_follow_investigation_20261019.md`)

10/18 두 대화의 증거 표로 원인을 가렸다. 옛 표면 기준 해석 하나는 바로잡는다: 도메인 표면에서는 안쪽 도구
이름 목록(`FOLLOW_TOOLS`)이 따라가기를 막지 않는다(F-5 로 이미 풀었다). 날씨 예보 4곳은 도구가 목록 밖이라서가
아니라 **대상이 여럿이라 열지 않은** 것이다(원칙 유지). 서버 기록에 남는 것은 틀이 부른 안쪽 도구 이름이다.

**고친 것** (도구·인자 이름은 늘리지 않았다 — 서버 판정과 응답의 짧은 문구만):
1. **결과를 기록한다.** 읽기 응답의 `screen` 칸 요약(`screen:opened|queued|asked|not_opened` + 이유)과, 아무것도
   돌려주지 않은 조용한 건너뜀(`screen:skipped <이유>`)을 그 호출의 `mcp_audit_log.result_summary` 에 덧붙인다
   (`screen_follow.audit_note`; 새 행·새 칸 없음 — 호출 수 지표가 안 부푼다). 안쪽 호출이 먼저 쓴 행에 붙이려고
   `tool_execution.AUDIT_UIDS`(contextvar)가 이 호출의 감사 행 id 를 모은다. 화면이 끝낸 명령의 감사 기록
   (`audit_log` `screen.command`)에는 `[follow]`/`[explicit]` 출처가 붙는다(`command.source`).
2. **중복은 "지금 화면에 실제로 열린 것"으로 판정한다.** 명령 이력 90초(`recently_sent`·`last_opened_item`)를
   그만두고, 화면이 동기화로 알려 온 열린 창(`client_state.dialog` → `_screen_open_item`)과 아직 끝나지 않은
   명령(`pending_open_item`)과 비교한다. 화면이 이미 다른 창으로 바뀌었으면 다시 연다. 감싸는 장소로 되돌리지
   않는 규칙(`_shows_inside`)은 그대로다.
3. **합치기.** 전달 전(`proposed`/`queued`/`held`)인 따라가기 명령은 같은 화면의 새 열기·강조·이동 명령이 대체한다
   (`superseded`). AI 가 직접 부른 명령은 대체되지 않는다(호출자가 결과를 기다린다). 연달아 읽으면 마지막 대상이
   화면에 남는다. 대체된 것은 분당 명령 한도에 세지 않는다.
4. **글자로 온 목록.** `target='["1포장","2포장"]'` 은 대상 해석 앞(`targets.listify`)에서 목록이 된다 — 모든
   operation 공통. 문자열만 든 대괄호 목록일 때만 푼다.
5. **조용히 건너뛰지 않는다.** 화면이 대시보드가 아니면(입력·출력 페이지 등) 아래 B 규칙으로 옮기거나, 옮길 수
   없으면 `not_opened` 에 이유를 싣는다.

**사용자 결정 (2026-10-20)**
- **A. 허용을 켠 기기는 [허용] 카드를 생략한다.** 따라가기와 `screen_action` 모두 `web_presence.auto_confirmed`
  가 참이면(그 기기에서 "AI 화면 조작 허용" 켬 + 최근 30분 안에 동기화) 확인 없이 바로 실행한다.
  안전 근거: 허용 자체가 화면 앞의 사람이 고른 허락이고 localStorage 에서 동기화마다 서버에 다시 실려, 끄면
  남은 명령까지 즉시 거둔다(`sync`의 `not allowed` 분기). 켠 채로 닫힌 브라우저(30분 넘게 동기화 없음)의 행은 예전처럼
  확인을 받는다 — 한참 뒤 누가 그 브라우저를 열 때 쌓인 명령이 실행되면 안 된다. 기기별 따라가기 '묻기'는 사용자가
  고른 것이라 그대로 [허용] 카드를 띄운다. 화면이 여럿이면 `screen` 을 고르게 하는 규칙도 그대로다.
- **B. 다른 대시보드에 있는 대상은 묻지 않고 옮겨 연다 — 단 하나로 정해질 때만.** 서버가 그 대상의 지도(geo)를
  보여 주는 지도 위젯이 있는 대시보드를 찾는다(`system._screen_map_widgets_for`; 위젯 설정의 `map_uuid`). 사용자가
  열 수 없는 대시보드(그룹 스코프)는 후보에서 뺀다. 후보가 하나면 `navigate` 를 넣고, 열기 명령은 **붙잡아
  둔다**(`held`, `hold_for=<대시보드 id>`) — 화면이 명령 여럿을 한 번에 받아 동시에 돌리는데 이동이 페이지를 다시 읽어
  뒤 명령이 사라지기 때문이다. 새 페이지가 동기화로 그 대시보드에 있다고 알릴 때(`sync` → `_release_held`) 풀려 같은
  응답으로 나가고, 화면 JS 는 지도 위젯이 준비될 때까지 기다린 뒤 연다(`waitForMapInstance`). 이미 그 페이지에 와
  있는데 받아 가지 않은 같은 곳으로의 이동은 끝낸 것으로 친다(백그라운드였던 화면이 링크로 돌아온 경우). 이동을
  거절([허용] 카드)하면 붙잡은 열기도 접는다. 후보가 여럿이거나 아무 대시보드도 못 보여 주면 옮기지 않고
  `not_opened`(+ 후보 대시보드 이름)로 AI 가 사용자에게 묻게 한다. 새 페이지가 뜨는 중에 또 읽으면 다시 옮기지 않고
  열기만 붙잡아 마지막 것을 남긴다(`pending_dashboard`).
- **C. 날씨·노트 검색도 따라간다.** 날씨는 대상 장소가 하나로 풀리면 도메인 `_follow` 가 이미 그 장소를 연다(F-5).
  노트 검색(`records.notes`)은 결과 행의 `target_id` 가 하나뿐이면 그것을 연다(`dispatch._single_result`).
  여럿이면 열지 않는다. 이름 목록(`FOLLOW_TOOLS`)에는 기대지 않는다.

**남은 것**: 명령은 12시간 뒤 지워진다(`KEEP_S`) — 이제 호출 기록에 결과가 남으므로 `mcp_audit_log` 의 `screen:`
요약을 세면 열림률·건너뛴 이유를 측정할 수 있다. 입력·출력·함수 페이지의 카드(지도가 아닌 대상)는 여전히 따라가지
않는다.

### F-14. 센서 조회는 쏟아내지 않는다 — 요약이 기본, 지정하면 값 (2026-10-31 · 조사 `plans/mcp_response_size_20261031.md`)

사용자 지적: "AI 센서 조회 때 모든 데이터가 쏟아진다". 실측(토큰): `measure.summary` 대상 없음 5,779(62곳 중 25곳에서 잘림),
`measure.history` 40채널 12,310·구역 4,810, `measure.channels` 5,312, `detail.device fields=measurements` 6,326,
`measure.freshness` 2,442. 네 곳을 줄였다. **도구·인자·op 이름은 늘리지 않았다** — 안쪽 도구의 스키마에 없는 처리기 인자
`brief` 하나를 도메인 명부의 `defaults_by_kind` 가 켠다. 그래서 같은 안쪽 도구를 부르는 인앱 AI·날씨·트윈·화면 값 읽기는
응답이 그대로다(`brief` 기본 꺼짐).

| op | 기본(지정 없음) | 더 받는 길(응답의 `next`) |
|---|---|---|
| `measure.history` | 채널마다 `columns`+`rows` 한 줄(최소·최대·평균·건수, 최근값 없음; 이름 있는 채널이 있으면 `name` 열). 구역이면 `zone_pick` 은 답한 장치 이름·`devices_in_zone`·다른 장치 이름만 | `measurement` 또는 `limit` → 예전 모양(값 목록). 구역 응답의 `zone_pick` 만 규칙 문장 없이 짧다 |
| `measure.summary` 대상 없음 | 대지(+대지 밖 구역)마다 한 줄 — (위치 유형, 매질)별 대표 4종 평균·멈춘 장치 수. 빠짐없이, 값 없는 곳은 `no_environment_data` 이름 | 대상 → 곳별 예전 모양 · `measurement` → 구역별 예전 모양 |
| `measure.channels` | 이름·단위 표, 같은 계열(`… +0d`~`+15d`)은 한 줄(`n`), id 없음 | `measurement=<낱말>` → 그 채널만 `measurement_id`·`select_value` 와 예전 모양 |
| `measure.freshness` | 끊긴 장치(stale·no_data)만 이름. 꺼 둔·알려진 상태 장치는 개수 | `include_fresh=true` → 예전 전체. 장치를 지목해도 그 장치 줄이 있다 |
| `detail.device` | 기본 `channels` 가 같은 계열 묶음. `fields=measurements` 는 id 가 필요한 설정 경로라 그대로 두고, `channels` 와 같은 표를 두 번 싣지 않는다 | |

**설정 흐름**: 위젯·함수 설정의 `select_value`·`measurement_id` 는 `measure.channels measurement=<낱말>` 또는
`detail.device fields=measurements` 로 받는다. 안쪽 `get_device_measurements` 는 `brief` 없이 부르면 예전 전체 응답이다
(`get_device_detail` 이 `fields=measurements` 에서, 인앱 계획기가 `select_by_type` 에서 쓴다).

**남은 것(범위 밖)**: `measure.freshness` 가 배터리 수신만으로 정상 판정하는 문제, `measure.summary measurement=…`(대상 없음)의
구역별 응답 크기, `_reading` 반복 안내문.

### F-15. 목록·상세 조회도 쏟아내지 않는다 — 대상이 없으면 한 줄씩 (2026-10-31 · F-14 의 B 묶음 · 조사 `plans/mcp_response_size_20261031.md`)

F-14 와 같은 방식이다: 안쪽 도구에 스키마 밖 처리기 인자 `brief`(기본 꺼짐)를 두고 도메인 명부의 `defaults_by_kind` 가 이 표면에서만
켠다. 도구·op·인자 이름은 늘리지 않았고(`detail` 은 이 표면의 고유 인자로 이미 여러 op 에 있던 이름), 인앱 AI·개요·화면·트윈은
`brief` 를 안 주므로 응답이 그대로다. 8084 실측(토큰): `find.controllable` 9,334 · `find.tree` 7,088 · `find.dashboards` 6,899 ·
`detail.plot` 5,776 · `overview.control_state` 4,937 · `find.map_equipment` 3,883.

| op | 기본 | 더 받는 길(응답의 `next`) | 다른 소비자 |
|---|---|---|---|
| `find.controllable` | 이름·종류·형식 표 40건(출력 먼저, 켜진 입력(센서)이 뒤), `total`·`counts`, 이름이 겹치는 장치에만 id | `offset`(다음 쪽 호출이 `next.call`) · `query` · `kind` · 장소 대상 · `detail=true`(예전 칸 `device_id`·`interface`, 쪽은 그대로) | 인앱 AI 의 `list_available_devices` 전체 목록 |
| `find.tree` | 대상 없음: 지도마다 맨 위 곳의 이름·종류·아래 곳 수·장치 수, id 없음 | 지도·대지·구역·시설을 대상으로 → 그 트리 예전 모양(`use_name`·`facility_id` 유지) · `detail=true` 전체 | 개요(`get_system_brief`)·`get_place_overview`·`check_mcp_contract` |
| `find.dashboards` | 대상 없음: 탭 이름·위젯 수. 탭 지정: 위젯(`widget_id` 있음, 좌표 없음) | 탭을 대상으로 · 좌표는 `detail.widget` 또는 `detail=true` | 인앱 AI 의 `list_dashboards`(위젯 만들기·고치기가 `tab_id` 를 거기서 받는다) |
| `detail.plot` | 요약: 작물·날짜·면적·프로그램·현재 단계(지침·목표 포함)·`target_summary`(대조 수·값 없는 수·내내 한쪽으로 빗나간 수) | `fields=[target_check, stage_schedule, stage_history, sensors, valves, timeline, facility_control]`(청한 갈래는 예전 값 그대로), `all` 은 예전 전체 응답. `_reading` 은 실린 칸의 문장만 | 인앱 AI 의 `get_plot`, `measure.soil_forecast`(`detail=twin_soil`, brief 없음) |
| `overview.control_state` | 대상 없음: 제어기마다 이름·시설·켜짐·제한 요인·게이트·편차·움직이는 명령 한 줄 | 시설을 대상으로 → 줄인 형태(예전 기본) · `detail=true` 전부 | 개요·장소 현황의 `get_control_state()` |
| `find.map_equipment` | 대상 없음: 구역마다 관수 방식·스프링클러·점적기·총 유량·배관 수·개별 설비 종류별 개수 | 구역·대지를 대상으로 → `irrigation_total` 이 있는 예전 모양 · `detail=true` 전체 | 인앱 AI 의 `get_map_equipment`, 화면 따라가기(`area_name` 인자로 판단) |

**`find.controllable` 의 입력(센서) 27건**: 센서 켜기·끄기 때문이 아니라 이 목록이 "AI 판단에 쓸 수 있는 장치"(켜진 입력 + 모든 출력)이기
때문이다(`AoTNativeToolEngine._get_ai_devices`). 꺼진 입력은 목록에 없어 켜기 용도로는 못 쓴다. 건수를 바꾸지 않고 `kind` 로 가르게 했다.
쓰기 흐름(`control.*`)은 이름을 `targets.resolve` 로 풀고 이 응답의 칸을 읽지 않는다.

**계약 검사**: 처리기 인자는 스키마가 아니라 `AoTNativeToolEngine.HANDLER_PARAMS`(네이티브) 또는 처리기 서명에서 맞는 이름으로 인정한다
(`contract.problems` 의 `args`·`extra_args`·`target_arg` 모두). 도구 목록 크기는 오히려 조금 줄었다(운영 9,258 → 9,256 · 설정 14,814 → 14,812 — `use` 줄을 바뀐 뜻에 맞추며 상쇄).

**남은 것(범위 밖)**: `_reading` 반복 안내문 전역 정리, `budget` 강제, `weather.forecast` 표 모양, 그 밖의 `find.*`.
