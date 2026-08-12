# AoT 색상 시스템 관리 계획 (Color System)

작성: 2026-07-02. 단일 기준 문서 — 색상 토큰의 정의·오버라이드·소비 규칙과
settings/custom_ui 연동 구조를 정의한다. z-index 는 `z-index-system.md` 참조.

## 1. 아키텍처 (3계층)

```
[1] aot-theme-variables.css   :root 에 --aot-* 실토큰 + 레거시 별칭 정적 정의 (단일 소스)
[2] custom-dark.css / custom-light.css   사용자 테마(다크)일 때 표면·텍스트 토큰 재정의
[3] /custom.css (동적 라우트, routes_general.custom_css)
        Misc.custom_theme_json (settings/custom_ui 저장값) → :root 재발행
        로드 순서상 [1],[2]보다 뒤 → 같은 이름은 사용자 값이 승리
```

- **실토큰**: `--aot-{category}-{variant}` (`color`, `bg`, `btn`, `border`, `surface`,
  `note`, `modal`, `tint`, `band` …). 신규 코드는 반드시 실토큰만 소비한다.
- **레거시 별칭**: `--brand-primary`, `--bg-btn-*`, `--bd-*` 등. 하위호환용 —
  신규 사용 금지, 발견 시 실토큰으로 교체.
- 다크모드는 `data-theme` 속성이 아니라 **서버측 조건부 로드**(`effective_theme in
  dark_themes` → custom-dark.css)로 동작한다. `:root[data-theme="dark"]` 블록은
  현재 어떤 코드도 data-theme 을 설정하지 않으므로 휴면 상태다.

## 2. settings/custom_ui ↔ 토큰 매핑

`/custom.css` 는 각 필드를 **레거시 별칭 + --aot-* 실토큰 양쪽**으로 발행한다
(2026-07 확장 — 이전에는 별칭만 발행해 실토큰 소비처(위젯 등 ~143곳)에
사용자 색이 적용되지 않았다).

| custom_ui 필드 | 레거시 별칭 | --aot-* 실토큰 |
|---|---|---|
| brand_primary/secondary | --brand-* | --aot-color-brand-* |
| brand_accent | --brand-accent | --aot-color-brand-accent, --bd-btn-tertiary |
| text_color_primary/secondary/tertiary | --text-color-* | --aot-color-text-* |
| bd_primary/secondary | --bd-* | (없음 — 페이지 배경층 전용) |
| badge_upgrade | --bg-upgrade, --bg-btn-upgrade | --aot-bg-upgrade, --aot-btn-bg-upgrade |
| bg_active / bg_inactive | --bg-* | --aot-bg-* |
| bg_warning | --bg-pause | --aot-bg-pause |
| bg_on / bg_off | --bg-on/off | --aot-bg-on/off |
| bg_pending | --bg-hold | --aot-bg-hold |
| tint_warning_bg / fg | (없음) | --aot-tint-warning-bg/fg |
| tint_success/warning/danger/info_border | (없음) | --aot-tint-{success,warning,danger,info}-border (2026-08-12 추가, .aot-notice-box 테두리) |
| bg_llm / bg_mcp | --bg-llm/mcp | --aot-color-llm/mcp |
| btn_primary_bg | --bd-tertiary, --bd-btn-primary, --bg-btn-active | --aot-btn-bg-primary, --aot-btn-bg-active |
| btn_secondary_bg | --bd-btn-secondary, --bg-btn-inactive | --aot-btn-bg-secondary, --aot-btn-bg-inactive |
| bg_btn_pause/hold | --bg-btn-* | --aot-btn-bg-* |
| bg_btn_on / bg_btn_off | --bg-btn-on/off | (없음 — active/inactive 토큰과 충돌) |
| bd_btn_border | --bd-btn-border | --aot-btn-border-primary |
| band_1..5 (측정 밴드) | (없음) | --aot-band-1..5 |
| chart_1..6 (차트 시리즈) | (없음) | --aot-chart-1..6 |

**2026-07-27 필드 통합** (아래 §3-2): `bd_tertiary`·`bd_btn_primary`·`bg_btn_active` →
`btn_primary_bg`, `bd_btn_secondary`·`bg_btn_inactive` → `btn_secondary_bg`,
`bg_upgrade`·`bg_btn_upgrade` → `badge_upgrade`, `bd_btn_tertiary` → `brand_accent`
에 흡수(값이 이미 같았음). `/custom.css` 는 통합 후에도 구 레거시 별칭을
전부 그대로 발행하므로(위 표) **소비하는 CSS 파일은 단 한 곳도 수정하지
않았다** — 변경은 오직 관리자 페이지가 몇 개의 DB 필드로 값을 받아
그 별칭들을 채우느냐일 뿐이다.

예외 규칙:
- **다크 사용자**에게는 `--aot-color-brand-accent`, `--aot-color-text-primary`,
  `--aot-color-text-secondary` 발행을 생략한다. custom-dark.css 의 `:root`
  재정의(같은 특이도, 더 이른 로드)를 덮어 어두운 배경에 어두운 글자가 되는
  것을 막기 위함이다. 새 토큰을 매핑에 추가할 때 custom-dark.css 가 재정의하는
  이름이면 반드시 이 생략 목록에도 추가할 것.
- 색상 필드의 단일 목록은 `forms_settings.THEME_COLOR_FIELDS` (폼·저장·프리셋
  API 공유). 필드 추가 시: THEME_COLOR_FIELDS + theme_defaults.json +
  custom_ui.html(PRESETS/CSS_VAR_MAP) + routes_general var_map 네 곳을 갱신.

## 3. 기본값 일치 계약

같은 색의 기본값이 4곳에 존재한다. **항상 동일해야 한다**:
1. `aot-theme-variables.css` 실토큰 값
2. `static/json/theme_defaults.json` (폼 defaults + Reset to Defaults)
3. `custom_ui.html` 의 `PRESETS.aot_default`
4. `forms_settings.py` 필드 fallback (THEME_DEFAULTS.get 2번째 인자)

이력: `--aot-btn-border-primary` 는 #13261B 로 정의돼 있었으나 /custom.css 가
항상 #B6BABA(theme_defaults)를 발행해 실효값과 어긋났다 → 정적 정의를
#B6BABA 로 정정(2026-07). `--bd-primary/secondary/tertiary`, `--bd-border` 는
정적 정의가 아예 없었다 → theme-variables 에 추가.

## 3-1. 미리보기 캔버스 매핑 계약 (settings/custom_ui)

미리보기 요소를 클릭하면 뜨는 팝오버는 `data-color-bg` / `data-color-text` /
`data-color-text-2` / `data-color-border` 에 적힌 필드를 편집한다.
**이 속성은 반드시 그 요소가 실제로 렌더에 쓰는 `--preview-*` 변수와 같은
필드여야 한다.** 어긋나면 세 가지 증상이 동시에 난다:
편집해도 미리보기가 안 변함 / 팝오버가 배경색·문자색을 같은 값으로 보여줌 /
저장하면 엉뚱한 곳 색이 바뀜.

이력(2026-07-27 수정): 상태 버튼의 `data-color-text` 가 `bd_btn_primary`·
`bd_btn_secondary`·`bd_btn_tertiary` 로 걸려 있었다. 이 셋은 이름과 달리
문자색이 아니라 **기본/보조 버튼의 배경색**(`--aot-btn-bg-primary/secondary`,
2절 매핑표 참조)이라 위 증상이 전부 발생했다. 실제 앱의 `.aot-btn-on/off` 는
글자색으로 `--text-color-tertiary` 를 쓰므로 `text_color_tertiary`
(밝은 배경인 Hold 만 `text_color_primary`)로 정정했다.
같은 이유로 `.preview-navbar-brand` 도 `--preview-brand-primary`
(= `bd_tertiary` 와 같은 값 → 글자가 배경에 묻힘)에서 `--preview-brand-accent`
로 정정했다.

미리보기 요소를 추가·수정할 때는 `aot-custom-ui-preview.css` 의 해당 규칙과
`custom_ui.html` 의 `data-color-*` 를 한 쌍으로 함께 고칠 것.

## 3-2. 필드 통합 (2026-07-27) — 배경 진단·마이그레이션·결정 근거

**배경**: settings/custom_ui 에 "중복되거나 어디에 적용되는지 알기 어려운
옵션이 많다"는 지적으로 실 소비처를 전수 조사(`var(--토큰)` grep)한 결과,
이름은 다른데 실제로는 같은 요소(주로 "채워진 버튼 배경")를 가리키는 필드가
여럿 있었다. 상세 조사 결과는 `.local/reports/custom_ui_color_field_reorg.md`
참조.

**통합 내용** (UI 색상 필드 25 → 20):
- `btn_primary_bg` ← `bd_tertiary` + `bd_btn_primary` + `bg_btn_active`
  (전부 "채워진 주 버튼 배경". `bd_tertiary`/`bd_btn_primary` 는 이름과 달리
  배경이 아니라 실제로 버튼 배경이었다)
- `btn_secondary_bg` ← `bd_btn_secondary` + `bg_btn_inactive`
- `badge_upgrade` ← `bg_upgrade`(nav 배지) + `bg_btn_upgrade`(버튼)
- `brand_accent` 가 `bd_btn_tertiary` 흡수(값이 이미 동일해 필드 자체를 제거)
- **통합하지 않은 것**: `bg_btn_on`/`bg_btn_off` — 장치 ON/OFF 상태 표시라
  주/보조 버튼과 값이 갈리는 게 자연스러워 별도 필드로 남김(사용자 결정).

**실 데이터 발산 — 결정이 필요했던 이유**: 로컬 운영 DB(`custom_theme_json`)를
읽어보니 통합 대상 필드들의 저장값이 이미 갈라져 있었다.
`bd_tertiary`/`bd_btn_primary`=`#13261B` 인데 `bg_btn_active`=`#64C762`,
`bg_upgrade`=`#FFC800`(노랑) 인데 `bg_btn_upgrade`=`#13261B`. 즉 "다르게 쓰는
실사용 사례가 없다"는 가정이 이 인스턴스 자체에서 깨졌다 — 무작정 통합하면
마이그레이션 우선순위에 따라 조용히 색이 하나로 수렴해버린다. 그래서 통합
전에 사용자에게 확인했고, 다음 우선순위로 확정했다(`forms_settings.
LEGACY_THEME_FIELD_MAP`):
- `btn_primary_bg`: `bd_btn_primary` → `bd_tertiary` → `bg_btn_active`
  (다수결로 `#13261B` 채택, `bg_btn_active` 의 `#64C762` 는 버려짐 — 영향
  범위가 더 작은 쪽을 택함: activate 버튼 2곳만 되돌아가는 게, 저장/전송
  등 다수 버튼이 밝은 초록으로 바뀌는 것보다 낫다고 판단)
- `btn_secondary_bg`: `bd_btn_secondary` → `bg_btn_inactive` (이 인스턴스는
  두 값이 이미 같아 무충돌)
- `badge_upgrade`: `bg_upgrade` → `bg_btn_upgrade` (사용자가 명시적으로
  선택 — 업그레이드 버튼이 기존 어두운 초록 대신 노란 배지색을 따르게 됨)

**마이그레이션 메커니즘**: `forms_settings.migrate_theme_dict()` 가 구
필드명 → 신규 필드로 이관 + 구 키 삭제를 수행하는 순수 함수다. DB 를 직접
고치는 배치 스크립트가 아니라, **읽는 시점마다 계산**하는 방식을 택했다
(3곳에서 호출: `routes_settings.settings_custom_ui()` GET, `routes_general.
custom_css()`, `utils_settings.settings_custom_ui_mod()` 저장 직전). 이렇게
한 이유:
- `custom.css` 는 모든 페이지 로드마다 히트하는 핫 경로라, 설정 페이지를
  한 번도 안 연 인스턴스가 업그레이드 직후 "색이 초기화됐다"고 보이는
  일이 없어야 한다 — 트랜지언트 마이그레이션이면 첫 요청부터 바로 적용됨.
- 실제 DB 갱신(구 키 영구 삭제)은 다음 "저장" 클릭 때 자연히 일어난다
  (self-healing) — 별도 마이그레이션 배치·알렘빅 리비전이 필요 없다.
- 사용자 프리셋(`custom_theme_presets`)에도 동일 함수를 적용한다(표시용
  트랜지언트 변환 — 프리셋을 다시 저장해야 DB 값 자체가 갱신됨).

## 3-3. `bg_warning` — 장치 offline/응답없음 상태색 노출 (2026-07-27)

"상태 색상(State Colors)" 그룹에 세 번째 필드로 추가. 새 토큰을 만든 게
아니라 **이미 앱 전역에서 쓰이던 기존 토큰을 custom_ui에 노출**한 것이다:

- 토큰: `--bg-pause` / `--aot-bg-pause` (기본값 `#989E9E`, 변경 전과 동일 —
  노출만 했을 뿐 기본 렌더는 그대로).
- 실제 소비처: `aot-base.css` `.pause-background`(입력/출력/함수 카드),
  `aot-toggle.css`, `widget_trigger_sequence.py`의 `.seq-offline`/
  `.seq-dev-offline`(시퀀스 위젯 오프라인 표시), PID·AI 스케줄러·지도 위젯 등.
- 트리거: `aot-output-state.js` 의 `fault`/`comm_fault` 상태
  (`classify()`/`classifyComm()`) → CSS 클래스 `pause-background` 적용.
  "unconfirmed/offline — 응답 없음" 이 정확한 의미(js 파일 11~17행 주석).
- **의도적으로 통합하지 않은 인접 토큰**: `--aot-tint-warning-bg/fg`
  (`#fff3e2`/`#94650a`) — 지도 팝업 이름 라벨 강조(`paintNameWarning`)와
  "실행 중이지만 확인 불가"(`paintUnverifiedRunning`) 인라인 틴트에 쓰인다.
  bg+fg 쌍으로 가독성이 맞춰져 있고, 후자는 "오프라인"과 다른 개념(확인 불가
  상태로 켜져 있음)이라 이번 범위에 넣지 않았다. 필요해지면 별도 필드로.

## 3-4. `bg_on`/`bg_off`/`bg_pending` — 출력/입력 채널 행 배경 노출 (2026-07-27)

**배경**: "output 카드의 각 채널 배경색은 상태에 따라 바뀌는데 custom_ui에서
설정할 수 없다"는 지적. 조사해보니 §3-3에서 추가한 `bg_active`/`bg_inactive`
가 이 채널 배경을 **전혀 통제하지 못하는** 사실이 드러났다 — 원인은 CSS
특이도다: `aot/aot_flask/templates/pages/output_entry.html` 의 채널 행에는
`.aot-entry-item-channel.active-background`/`.inactive-background` 규칙
(`aot-entry-ui.css:655-661`)이 더 높은 특이도로 붙어 `--bg-on`/`--bg-off` 를
읽는다 — `bg_active`/`bg_inactive` 가 발행하는 `--bg-active`/`--bg-inactive`
(범용 `.active-background`, `aot-base.css:613-618`)와는 **다른 토큰**이다.
`bg_active`/`bg_inactive` 는 여전히 유효하다 — 카드 전체(예: `output_status_*`
의 device-level rollup, IEC 포커스 행) 하이라이트에는 실제로 쓰인다. 다만
사용자가 보는 "채널 한 줄의 배경"은 이 필드가 아니었다.

- `bg_on` ← `--bg-on`/`--aot-bg-on` (기본 `#B5BABA`). 출력/입력 **채널 행**
  켜짐 배경. 또한 시설 위젯(`aot-facility-widget.css`)·센서 라벨
  (`aot-sensor-label.css`)의 범용 "표면색"으로도 널리 재사용된다.
- `bg_off` ← `--bg-off`/`--aot-bg-off` (기본 `#F3F6F5`). 채널 행 꺼짐 배경 +
  동일한 범용 표면색 재사용.
- `bg_pending` ← `--bg-hold`/`--aot-bg-hold` (기본 `#F0AD4E`). 명령 전송 후
  장치 확인 대기 중(`aot-output-state.js` 의 `pending`) 배경 —
  `aot-base.css` `.hold-background`. **`bg_btn_hold`(`--aot-btn-bg-hold`,
  PID 유지 버튼)와는 다른 토큰**이니 혼동 금지 — 같은 함정이 §3-2 의
  `btn_primary_bg` 통합 배경과 동일 유형(이름은 비슷한데 실제 소비처가 다름).
- `fault`(오프라인) 상태는 이미 `bg_warning`(§3-3)이 커버한다 — 채널 행도
  `.aot-entry-item-channel` 이 pause-background 를 오버라이드하지 않아
  범용 `--bg-pause` 로 자연히 폴백되므로 별도 필드 불필요.

**미리보기 캔버스**: "State Colors" 그룹 필드 6개 전부(active/inactive/
warning/on/off/pending)가 실제로 무엇을 바꾸는지 시각적으로 검증할 수 있게
Zone 1 미리보기에 4행짜리 "Output/Input Channel Preview" 블록을 신설했다
(on/off/pending/fault 각 상태 + On/Off 버튼 재사용). `bg_active`/
`bg_inactive` 는 여전히 미리보기 캔버스에 대응 요소가 없다(카드 레벨이라
축소 미리보기로 표현하기 애매함 — 남은 과제).

## 3-5. `tint_warning_bg`/`tint_warning_fg` — "실행 중, 확인 불가" 인라인 틴트 노출 (2026-07-27)

**배경**: §3-4에서 `bg_on`/`bg_off`를 노출한 뒤, "output 카드에 다른 색이
강제 적용된다"는 재확인 요청이 있었다. 조사 결과 `aot-output-state.js`
`paintUnverifiedRunning()`(파일 139~157행)이 원인이었다 —
`comm_capable(output_id) === false`(응답/ACK 확인 경로가 없는 fire-and-
forget 출력) 이면서 채널이 켜져 있을 때, **채널 행 엘리먼트에 인라인
`style.setProperty('background-color', ..., 'important')`** 를 매 폴링(1초)
마다 강제 적용한다(`output.html:184, 234`). 인라인 `!important` 는 시트의
`!important`(`.aot-entry-item-channel.active-background`, §3-4)보다
**항상** 우선하므로, 이 조건에 해당하는 장치는 `bg_on` 값과 무관하게 항상
이 틴트로 보인다 — "다른 색이 강제 적용된다"는 관찰이 정확했다.

- `tint_warning_bg` ← `--aot-tint-warning-bg` (기본 `#FFF3E2`, 연한 주황).
- `tint_warning_fg` ← `--aot-tint-warning-fg` (기본 `#94650A`) — 같은 함수가
  지도 팝업 이름 강조(`paintNameWarning`)에서 배경+글자 둘 다 바꿀 때 쓰는
  글자색. bg/fg 쌍으로 가독성이 맞춰져 있으니 **둘을 함께 바꿀 것**.
- §3-3에서는 이 토큰을 "다른 개념이라 통합하지 않는다"며 노출을 미뤘으나,
  실사용에서 "강제 적용"으로 체감되는 사례가 나와 이번에 노출했다 —
  **일부러 숨겨둔 게 아니라 아직 노출 안 한 하드코딩이었을 뿐**이라는
  원칙(§1 레거시 별칭 확장과 동일 맥락)에 따른 결정.
- 이 틴트는 **끄는 옵션이 아니다** — "확인할 수 없는데 켜져 있다"는 사실을
  안전상 항상 표시해야 하므로, 노출 목적은 "이 색을 안 보이게" 가 아니라
  "이 색을 사용자가 원하는 색으로" 다.

**미리보기**: 채널 미리보기에 5번째 행(CH5, "실행 중 (확인 불가)")을 추가.

## 3-6. 채널 미리보기 On/Off 버튼 — 실제 캐스케이드 재현 (2026-07-27)

첫 구현에서는 CH1(켜짐)·CH2(꺼짐) 두 행 모두 On 버튼을 무조건 `bg_btn_on`
(밝은색)으로 그려, "On 버튼이 모든 행에서 초록색이라 켜짐/꺼짐 구분이
안 된다"는 피드백을 받았다. 실제 앱(`aot-entry-ui.css`)을 보면 애초에
그렇게 동작하지 않는다:

```css
.aot-btn-on { background-color: var(--bg-btn-off, ...); }   /* 기본값: 흐림 */
.aot-entry-item-channel.active-background .aot-btn-on {
  background-color: var(--bg-btn-on, ...);                  /* 켜짐 행일 때만 밝음 */
}
.aot-btn-off { background-color: var(--bg-btn-off, ...); }  /* 항상 흐림 */
```

즉 실제 앱도 On 버튼 자체가 "밝음"인 건 **행이 켜짐 상태일 때뿐**이고,
꺼짐 행에서는 On/Off 버튼이 똑같이 흐리게 보인다 — 상태를 구분하는 신호는
행 배경색이지 버튼색이 아니다. 미리보기를 이 캐스케이드 그대로 재현하도록
전용 클래스(`.preview-channel-btn-on/off`, 상단 독립 버튼 미리보기와는
별개)로 수정했고, 채널명 옆에 상태 텍스트("채널 켜짐"/"채널 꺼짐")도
추가해 이중으로 명확하게 했다.

## 3-7. Actuator Paired 자가구동 행 배경색 미반영 버그 (2026-07-27, output.html)

색상 노출과는 별개로, 색상을 검증하는 과정에서 발견한 **진짜 상태-반영 버그**.
Actuator Paired 출력이 작동 중인데도 행 배경(`active-background`/`bg_on`)이
전혀 바뀌지 않는다는 신고 — 재현해보니 색상 설정 문제가 아니라
`output.html`의 폴링 로직(`gpioState()`) 버그였다.

- 페어링 행의 `anyActive`(→ active/inactive-background 결정)는 오직
  `data[openId][openCh]`/`data[closeId][closeCh]`(설정된 open/close 대상
  출력의 상태)만 본다.
- 그런데 `output_channel.custom_options`에 `travel_time_open_sec` 등
  자체 이동시간을 갖는 **자가구동형** 설정(`output_open_id`/
  `output_close_id` 미설정, 이 인스턴스의 "천창1"이 이 케이스)은 별도
  open/close 대상 출력이 없다 — `openId`/`closeId` 가 항상 빈 문자열이라
  `anyActive` 가 **영원히 false** 로 고정된다.
- 반면 위치(%) 라벨(`posEl`)은 같은 파일 바로 아래에서 `data[oid][ch]`
  (페어링 출력 자신의 상태, `actuator_paired.py` 의
  `output_states[channel] = position%`)를 이미 읽고 있었다 — 즉 위치
  텍스트는 정확히 갱신되는데 배경색만 이 신호를 안 쓰고 있었다.
- 수정: `anyActive` 계산에 자기 자신의 상태(`ownSt`/`ownActive`)를
  fallback으로 추가(`output.html` 208행 부근). open/close 대상이 설정된
  기존 방식에는 영향 없음(OR 조건 추가일 뿐).
- 로컬에서 `$.getJSON` 몽키패치로 `/outputstate` 응답에 위치값을 주입해
  수정 전/후 행동을 모두 확인(활성→배경 변경, 해제→원복).

## 3-8. Actuator Paired 자가구동 Open/Close 버튼 강조 미반영 (2026-07-27, 후속)

§3-7 수정으로 행 배경은 정상화됐지만, Open/Close **버튼** 강조는 별개
문제로 남아있었다 — 신고: "열기/닫기 상태가 되면 버튼도 On 과 같은 색이
적용돼야 함".

- 버튼 강조는 `openActive`/`closeActive`(§3-7과 같은 변수)로 결정되는데,
  자가구동 액추에이터는 `openId`/`closeId` 가 항상 빈 문자열이라 이 둘이
  **항상 false** — 행은 `active-background` 로 정상 전환돼도 Open/Close
  버튼 둘 다 `aot-paired-inactive`(흐림)에 갇혀 있었다.
- 근본 이유: 폴링 데이터(`data[oid][ch]`)는 현재 **위치**(%) 만 담고 있고
  **방향**(여는 중/닫는 중)은 없다 — 서버가 방향을 별도로 노출하지 않는다.
- 수정: 사용자가 마지막으로 누른 버튼(Open/Close/Stop)을 클라이언트 측
  `pairedLastDirection` 맵에 기억해두고(`actuator_paired_cmd()`), 자가구동
  케이스(`!openId && !closeId`)에서만 이를 `openActive`/`closeActive` 의
  대체 신호로 사용. open/close 대상이 설정된 기존(위임형) 방식은 그대로
  실제 상태를 쓰므로 영향 없음.
- **알려진 한계**: 이 기억은 브라우저 세션에 한정된다 — 페이지를 새로
  불러온 시점에 이미 다른 세션/사용자가 눌러 작동 중이던 액추에이터는
  행 배경(active-background)은 정확히 뜨지만 어느 버튼인지는(방향 정보
  자체가 폴링 데이터에 없어) 알 수 없어 강조되지 않는다. 서버가 방향을
  노출하기 전까지는 구조적 한계.
- 로컬에서 실제 Open/Close 버튼을 클릭 + `/outputstate` 위치값 주입으로
  양방향(Open 강조/Close 흐림, 그 반대) 모두 확인.

## 3-9. 로딩 시 ON 상태 색 순간 반짝임 — commCapable 레이스 (2026-07-27)

신고: "on 상태 배경색 — 실행중 확인불가 색이 로딩할 때는 맞다가 바로
다른 색이 됨". 실 데이터가 실시간으로 계속 바뀌던 중이라 직접 재현은
못 했지만, 코드에서 정확히 이 증상을 만드는 레이스를 확인했다.

`$(function () { loadCommCapable(); gpioState(); setInterval(...); })` —
`loadCommCapable()`(comm_capable 여부, 1회성)과 `gpioState()`(1초 주기
상태 폴링)가 순서 보장 없이 동시에 발사된다. `commCapable` 는 fetch
완료 전까지 `{}`이고, 가드 주석이 명시하듯 "정말 확인 불가로 확정됐을
때만 true, 아직 응답이 안 왔다고 true가 되면 안 됨" — 그런데 이 가드는
**반대 방향**(틴트가 잘못 켜지는 것)만 막고, `gpioState()`의 첫 틱이
`loadCommCapable()`보다 먼저 도착하는 경우 그 한 틱 동안은
`commCapable[output_id] === false` 가 `false`(아직 모름 = 확인 가능
취급)로 읽혀 **원래 켜져야 할 틴트 없이** `bg_on` 으로 그려지고, 다음
틱(1초 후)에 `commCapable` 가 채워지며 틴트로 바뀐다 — "로딩 때 색 →
곧 다른 색" 그 자체.

수정: `loadCommCapable()` 이 `$.getJSON`(jqXHR/Deferred)을 반환하도록
하고, `gpioState()`·`setInterval` 시작을 `.always(...)` 콜백 안으로
옮겨 **1회성 capability 조회가 끝날 때까지 첫 상태 폴링을 미룸**.
이후 1초 주기 폴링(steady state)은 그대로 — 최초 페인트 시점만
지역 네트워크 왕복 1회만큼(로컬 기준 수십 ms) 늦춰진다.

## 3-10. 위젯 색상 토큰 전수 조사 및 수정 (2026-07-27)

"이번 세션에서 바뀐/노출한 색상 토큰이 위젯에도 제대로 적용되는가"를
27개 위젯 전수 조사했다. 결과: `AoT_controller`/`AoT_timer`/
`widget_output_pwm_slider`/`widget_trigger_sequence`/`widget_notice`
등 대부분의 상태색 위젯은 이미 공유 클래스(`.active-background` 등)를
통해 정상 연동돼 있었다 — 특히 `widget_trigger_sequence.py` 는 이번
세션에 노출한 `bg_pending`(`--bg-hold`)까지 이미 정상 소비 중이었다.
아래 3건은 실제로 문제였다.

**① `AoT_PID.py` — 토큰 뒤바뀜(진짜 버그)**: `.active-background`(PID
작동 중)가 `--bg-inactive` 를, `.inactive-background`/`.pause-
background`/`.hold-background`(꺼짐·일시정지·유지)가 전부 `--bg-active`
를 쓰고 있었다 — custom_ui.html 의 `bg_inactive` 도움말 문구
("PID container background")와도 모순되는, 관리자가 설정한 색과
정반대로 보이는 버그. `active→bg_active`, `inactive→bg_inactive`,
`pause→bg_pause`(=bg_warning), `hold→bg_hold`(=bg_pending, 현재 JS는
paused/held 를 모두 pause-background 로만 보내 hold 분기는 아직
미사용이지만 관례에 맞춰 정정)로 수정. 실제 PID 위젯(유일하게 1개
존재)으로 inactive 상태가 `#F3F6F5`(bg_inactive)로 정확히 렌더되는지
확인.

**② `map.css` `.device-label.device-on` — 가짜 var() (§5-3 유형)**:
`var(--device-label-color, #32c85a)` 를 쓰는데 `--device-label-color`
는 CSS·JS 어디에도 정의된 적이 없는 죽은 참조라 **항상 폴백
`#32c85a` 로만 렌더** — custom_ui 와 완전히 무관했다. 실제 켜짐 표시
개념과 일치하는 `--bg-on` 으로 교체. (조사 중 `AoT_map.py` 의
`WIDGET_HEAD_HTML_RASTER`/`_VECTOR` 상수 안에도 같은 유형의 하드코딩
`.marker-pill.device-on{background:#28a745}` 이 있었으나, 두 상수 모두
`WIDGET_INFORMATION` 어디에서도 참조되지 않는 **완전한 죽은 코드**임을
확인 — 실수로 먼저 고쳤다가 되돌리고 실제 라이브 경로인 map.css 만
수정했다. 위젯 .py 안의 문자열이라고 무조건 라이브 코드가 아니다 —
`WIDGET_INFORMATION` 딕셔너리에서 실제로 참조되는지 항상 확인할 것.)

**③ 위젯 카드(`​.widget-outer`) 배경 — 지금까지 완전히 투명**:
`aot-modal-modern.css` 자체 주석이 "위젯 카드는 원래 투명해서 대시보드
배경을 그대로 비침"이라고 명시할 만큼 의도된 설계였다 — `bd_primary`/
`bd_secondary` 를 아무리 바꿔도 위젯 카드에는 영향이 없었다. 사용자
확인 후 `bootstrap-4-themes/aot.css` `.widget-outer` 에
`background-color: var(--bd-primary, #FFFFFF)` 추가로 테마화.
**중요 발견**: `bd_primary` 는 이미 `--primary: var(--bd-primary, #fff)`
로 Bootstrap 코어 변수와 연결돼 있어 **네비게이션 바 배경
(`.navbar.main-navbar { background-color: var(--primary); }`) 을
포함해 이미 광범위하게 쓰이고 있었다** — 위젯 카드 배경 부재는
그 넓은 반경 안의 "안 뚫린 구멍" 하나였을 뿐, `bd_primary` 자체가
고립된 토큰은 아니었다. `bd_primary` 를 바꾸면 네비게이션 바와
위젯 카드가 동시에 바뀐다는 점을 UI 문구에도 반영할 필요가 있다
(후속 과제).

## 4. 사용자 프리셋

- 저장소: `Misc.custom_theme_presets` (JSON, `{"이름": {필드: "#RRGGBB"}}`,
  마이그레이션 `p5_28_add_custom_theme_presets`).
- API: `GET/POST/DELETE /settings/custom_ui/presets` (JSON body `{name, colors}`,
  X-CSRFToken 헤더, edit_settings 권한, 최대 30개, 이름 40자).
- UI: custom_ui 페이지 프리셋 셀렉트의 "My Presets" optgroup(값 접두사 `user:`)
  + 이름 입력 + Save Preset/Delete. 프리셋 적용은 폼 값만 바꾸므로
  **폼 Save 를 눌러야 실제 테마에 반영**된다(내장 프리셋과 동일 동작).

## 4-1. 역방향 저장 (위젯 → 전역)

위젯 설정 모달에서 지정한 색을 전역 커스텀 색으로 승격할 수 있다:
- API: `POST /settings/custom_ui/global_colors` `{"kind": "band"|"chart",
  "colors": ["#RRGGBB", …]}` (edit_settings 권한). band 는 band_1..5,
  chart 는 chart_1..6 에 순서대로 기록 → custom_theme_json 병합 →
  /custom.css·서버 팔레트에 즉시 반영.
- 버튼 위치: AoT_gauge_angular 설정(구간색 앞 5개 → 전역 밴드),
  AoT_graph 설정(시리즈색 앞 6개 → 전역 차트).
- 주의: 이미 생성된 게이지/그래프 위젯의 **개별 저장색**(custom_options)은
  바뀌지 않는다 — 전역값은 신규 위젯 기본값·센서 라벨·시리즈 기본색에 적용.

## 5. 하드코딩 금지 규칙 (신규 개발)

1. CSS: 색은 `var(--aot-…)` 로만. 새 색이 필요하면 theme-variables 에 토큰
   추가 후 사용. `var(--토큰, #폴백)` 의 폴백 리터럴은 허용(토큰 기본값과
   동일 값일 것).
2. 위젯 `.py` 인라인 CSS(widget_dashboard_head/body): DOM 에 꽂히므로 `var()`
   사용 가능 — 사용할 것. 변경 시 위젯 템플릿 재생성 필요(CLAUDE.md 참조).
3. JS/canvas/Three.js/Highcharts 등 리터럴이 불가피한 곳:
   `getComputedStyle(document.documentElement).getPropertyValue('--aot-…')` 로
   읽거나, 불가하면 토큰 값과 동일한 리터럴 + 토큰명 주석.
4. 측정 5단계 밴드 팔레트는 `--aot-band-1..5` 가 기준이며 custom_ui `band_1..5`
   로 사용자 정의된다. 소비 규칙 (2026-07 전환):
   - Python: `utils_theme.get_band_palette()` (오버레이 적용) — 상수
     `aot.config.BAND_PALETTE` 직접 사용은 폴백 경로만.
   - JS: `aot-map-sensor-labels.js` / `aot-facility-sensor-labels.js` /
     `geo_facility.html`(SensorRangesUI) 는 `--aot-band-*` 를
     getComputedStyle 로 읽는다(리터럴은 폴백).
   - `AoT_gauge_angular.py` 의 기본 stop 문자열(#32c85a)은 값 동기 유지.
   - **프리셋 게이지는 밴드 팔레트를 실시간 추종**: preset_config 가
     temperature/humidity/vpd 인 게이지는 렌더 시(generate_page_variables)
     저장된 구간색 대신 현재 밴드 팔레트를 적용(humidity 는 역순,
     구간 수가 5가 아니면 저장색 유지). 개별 색을 쓰려면 Custom 프리셋.
5. 상태색은 Bootstrap 기본(#28a745/#dc3545/#ffc107/#17a2b8) 대신
   `--aot-color-success/danger/warning/info` (소프트 배지엔 `--aot-tint-*`).
5-1. 그래프류 위젯의 Highcharts 시리즈 기본색은 `aot.config` 의
   `GRAPH_SERIES_PALETTE` / `GRAPH_SERIES_PALETTE_DARK` 단일 소스 +
   custom_ui `chart_1..6` 오버레이. 코드에서는
   `utils_theme.get_graph_series_palette(dark=…)` 로 읽을 것
   (AoT_graph·widget_graph_synchronous 는 Python 호출, AoT_PID 템플릿은
   inject_variables 가 주입하는 `graph_series_palette(_dark)`).
   새 차트 위젯도 이 경로를 쓸 것 — 팔레트 재하드코딩 금지.
   `utils_theme._theme_dict` 는 ORM 이 아닌 Core SELECT 로 misc 를 읽는다
   (세션 identity map 의 stale Misc 회피 — /custom.css 의 expire_all 과 동일 취지).
5-2. **정당한 리터럴** (치환 대상 아님): ① 사용자 설정 색상 옵션의
   default_value (color input 은 구체 hex 필요 — wind/facility/gauge 등),
   ② Highcharts/SVG 속성 등 CSS var 가 닿지 않는 차트 크롬(눈금·다이얼),
   ③ `var(--토큰, #폴백)` 의 폴백값,
   ④ **고정 다크 패널/글래스 컴포넌트**(AI 드로어 액션 카드, AoT_advice 위젯,
   widget_ai_insight, 사진 갤러리 라이트박스) — 배경이 항상 어두워 라이트모드
   전역 텍스트 토큰(어두운 색)을 쓰면 텍스트가 안 보임. 흰색/밝은 회색
   리터럴을 유지하고 주석으로 사유를 남긴다,
   ⑤ **영상/3D 오버레이 HUD**(카메라 위젯 상태 텍스트, 시설 3D 힌트) —
   임의의 동적 배경(영상 프레임, 3D 렌더) 위에 얹혀 항상 보여야 하므로
   테마 텍스트색 대신 흰색+그림자 또는 반투명 흑색 고정,
   ⑥ **글자색=배경색이 같아야 하는 트릭**(예: info.html `.hide` 스포일러
   가림 효과) — 토큰화 시 둘이 어긋나면 효과가 깨짐,
   ⑦ **로그/콘솔 출력 박스**(admin/upgrade.html `#upgrade_status`) — 항상
   어두운 터미널 스타일 유지,
   ⑧ **파스텔 알림 배지 bg+fg 쌍**은 `--aot-tint-{success,warning,danger,info}-{bg,fg}`
   로 변환(Bootstrap `#d4edda`/`#fff3cd`/`#f8d7da` 계열이 이 토큰의 명시적
   대체 대상 — aot-theme-variables.css 1.2a 절 주석 참조),
   ⑨ **독립 마이크로 팔레트**(간트 상태 배지 4색, AI 컨텍스트 칩 인디고 등)
   — 기존 시맨틱 토큰과 정확히 겹치지 않는 자체 완결적 배색 세트는
   재하드코딩 확산 방지를 위해 리터럴 유지 + 주석 백로그.
6. 브랜드: 딥그린 #13261B(=brand-primary). 노란 `--aot-color-primary`(#F2D524)는
   버튼/액션에 사용 금지.

## 5-3. 텍스트 색상 시스템 전역 점검 이력 (2026-07)

layout.html이 로드하는 전역 CSS부터 시작해 static/css 전체(약 33개 자사
파일), templates 전체(약 19개 페이지), widgets 전체(27개)의 `color:`
(텍스트 전경색) 속성을 전수 조사·토큰화했다. 매핑 규칙(5절 3-bucket:
어두운 회색군 → `--aot-color-text-primary`, 중간 회색군 →
`--aot-color-text-secondary`, 흰색/on-colored-bg → `--text-color-tertiary`,
Bootstrap 상태색 → `--aot-color-{success,warning,danger,info}`)을 일괄
적용했고, 5-2절의 9개 예외 카테고리에 해당하는 항목만 리터럴로 남기고
전부 파일 내 주석으로 사유를 표시했다. 향후 새 하드코딩이 추가되면 이
9개 카테고리 중 하나에 해당하는지 먼저 판단할 것 — 해당 없으면 토큰화.

## 5-4. `body` 기본 텍스트색 연결 (2026-07, 중요)

`bootstrap-4-themes/aot.css` 의 `body { color: #212529; }` (Bootstrap 기본값)이
토큰 시스템과 완전히 무관하게 하드코딩되어 있었다. 결과: settings/custom_ui
의 "텍스트 기본"(text_color_primary)을 바꿔도 `--text-primary` 를 명시적으로
소비하는 극소수 요소(사이드바 메뉴 등, 이 파일 437/452/484/508행)만 반영되고,
제목·본문 등 **색 지정이 없어 body 로부터 상속받는 대다수 텍스트는 계속
Bootstrap 기본 검정으로 남아 "일부만 바뀌고 나머지는 검정"으로 보이는 사고**가
있었다. `body { color: var(--text-primary, #212529); }` 로 수정해 사이트
기본 텍스트색이 실제로 text_color_primary 를 따르도록 연결했다(2026-07-02).

이 수정은 `bootstrap-4-themes/aot.css`(라이트/기본 AoT 테마) 에만 적용했다.
다크 Bootswatch 스킨(cyborg/darkly/slate/solar/superhero.css)은 `--text-primary`
변수 자체가 정의되어 있지 않은 별개 테마 파일이라 대상에서 제외했다 —
해당 스킨을 쓰는 경우 여전히 자체 팔레트를 따른다(별도 이슈, 미해결).

**교훈**: 하드코딩 색상 조사 시 `body`/`html` 같은 최상위 선택자에 리터럴이
있으면 그 값이 사실상 "사이트 기본색"이 되어, 파일별 grep 스캔에서 한 파일씩
훑어도 "가장 근본적인 상속 지점"은 놓치기 쉽다. 새 텍스트 토큰 배선 후에는
반드시 실제로 값을 바꿔보고(예: 눈에 띄는 색으로 임시 설정) 페이지 전반에
퍼지는지 브라우저로 확인할 것 — 개별 파일의 `var()` 치환 개수만으로는
"전역 기본값이 실제로 통제되는가"를 보장하지 못한다.

**2차 조사(같은 날, 사용자가 "아직도 전체 적용 안 됨" 재확인 후) 추가 발견**:
`body` 하나만으로는 부족했다. Bootstrap 은 `.dropdown-item`(#212529),
`.form-control`(#495057, input/select/textarea 전체), `.navbar .nav-link`,
`.close`(모달 × 버튼) 등 **클래스 선택자 단위로 개별 하드코딩 색을 수십 곳에
박아두며, 클래스 선택자는 element 선택자(`body`)보다 특이도가 항상 높아
`body` 색 지정을 무시하고 이긴다.** 각각을 `!important` 로 오버라이드해야
했다(`bootstrap-4-themes/aot.css`). 또한 `custom-light.css`/`custom-dark.css`
가 `--aot-modal-title-text/body-text/group-title` 를 **리터럴로 재고정**해
theme-variables.css 쪽 토큰 체인화를 무효화하고 있던 것도 발견 — 이 파일들
자체가 "surface 토큰 중 라이트/다크가 실제로 다른 값만 재정의" 규칙을 어기고
동일 값을 redundant 하게 재선언한 상태였다(제거로 해결).

**함정(캐시)**: `custom-light.css`/`custom-dark.css`처럼 `?v=` 캐시버스팅
파라미터가 아예 없던 파일은 서버 파일을 고쳐도 브라우저가 계속 옛 버전을
쓴다 — `location.reload(true)`도 강제 무효화가 안 된다(구식 API, 최신
Chrome에서 사실상 무시됨). CSS 파일을 고칠 때마다 해당 `<link>`에 `?v=`가
있는지 먼저 확인하고, 없으면 하나 추가할 것.

**최종 검증 방법**: 브라우저에서 `document.querySelectorAll('body *')`를
순회해 leaf 요소의 `getComputedStyle(...).color` 분포를 집계하는 스크립트로
"실제 몇 개 요소가 어떤 색인지"를 정량 확인했다(주관적 스크린샷 판단보다
신뢰도 높음). 최종 상태: 테스트 색(빨강) 191개(대다수: nav/dropdown/폼/제목/
라벨), secondary(청록) 15개(그룹타이틀류, 의도적 구분), tertiary(흰색)
16개(색배경 버튼), 기타 소수 예외.

**3차 조사(같은 날, "검정/회색이 도처에 남아있음" 재확인 후) — 두 가지 새 버그 유형**:

1. **"가짜 var()" — 존재하지 않는 변수 참조**: `var(--panel-text, #333)`
   (map.css 9곳), `var(--aot-text-muted, ...)`, `var(--aot-accent, ...)`
   (aot-modal-modern.css) 처럼 `var()` 문법은 있지만 그 변수가 **어디에도
   정의되어 있지 않아** 항상 폴백 리터럴로 렌더링되는 죽은 참조가 존재했다.
   1·2차 조사의 grep 필터(`grep -v "var(--"`)가 "이미 토큰화됨"으로 오판해
   건너뛴 지점 — 실제로는 100% 하드코딩과 동일한 효과. 전용 스크립트로
   "color: 에서 참조되는 모든 `--변수`" 집합과 "CSS 전체에서 실제 정의된
   `--변수`" 집합을 비교(`comm -23`)해 찾아냈다. → `--aot-color-text-primary`
   /`--aot-color-text-secondary`/`--aot-color-info`로 교체.
2. **Bootstrap 클래스 단위 하드코딩이 훨씬 더 많았다**: `body`/`.nav-link`/
   `.dropdown-item`/`.close` 외에도 `.form-control`(모든 input/select/
   textarea, #495057), **`.table`**(모든 데이터 테이블 셀, #212529 — 측정값
   설정 페이지 한 곳에서만 944개 요소), **`.text-dark`/`.text-body`/
   `.text-muted`/`.text-secondary`**(Bootstrap 유틸리티 클래스, `!important`,
   템플릿 26개 파일에 광범위 사용), `.popover-body`, `.dropdown-item-text`,
   `.dropdown-header` 가 전부 별도로 하드코딩되어 있었다. `bootstrap-4-themes/
   aot.css` 에 각각 `var(--text-primary/secondary, 원래값) !important` 오버라이드
   추가로 해결.
3. **이중 새도잉(재발)**: `--gray-dark` 가 aot-theme-variables.css 에서
   `--aot-color-text-secondary` 로 체인되게 고쳤는데도 반영이 안 됨 →
   `bootstrap-4-themes/aot.css` **자체의 `:root` 블록**(Bootstrap 색상 팔레트
   재선언 구획, `--blue`/`--red`/`--gray-dark` 등)이 나중에 로드되며 다시
   리터럴(`#888888`)로 덮어쓰고 있었다. `.aot-modal-group-title` 의
   `color: var(--gray-dark)` 처럼 **클래스명과 변수명이 비슷해 보여도 실제
   참조 변수가 다른 경우**를 항상 실제 CSSOM(`document.styleSheets`)으로
   확인할 것 — 클래스명만 보고 어떤 토큰을 쓸지 추정하면 틀린다.
4. **JS 인라인 스타일 하드코딩**: CSS 파일과 무관하게 `element.style.cssText`
   /`element.style.color = '#666'` 로 **JavaScript 가 직접 문자열 리터럴을
   주입**하는 곳(`geo/aot-map-custom-controls.js` 의 지도 측정값/단위/이름
   라벨, 거리 툴팁, 취소 안내문 등)이 다수 있었다. 다행히 인라인
   `style` 속성도 `var(--토큰)` 을 정상 지원하므로 문자열을
   `'var(--aot-color-text-primary, #333)'` 형태로 바꾸면 그대로 작동한다.
   **단, Highcharts `dataLabels.style.color` 처럼 차트 라이브러리가 자체
   기본값으로 인라인 색을 주입하는 경우**(게이지/그래프 위젯의 숫자
   표시값, 예: "72.0", "25.0°C")는 위젯 Python 템플릿의 Highcharts 설정
   자체에 `color` 를 명시해야 하는 별개의 작업이며, 이번 조사에서는
   존재를 확인만 하고 미해결로 남김(백로그 9번 참조).
5. **캐시 함정 재확인 + 위젯 템플릿 재생성 누락**: `AoT_map.py` 소스(임베디드
   HTML 문자열)의 `map.css?v=` 를 올려도, **실제 서빙되는 것은
   `user_templates/widget_template_AoT_map_head.html` 사전생성 파일**이라
   `generate_widget_html()` 재실행 전까지 반영되지 않는다(CLAUDE.md에 이미
   명시된 규칙인데도 재발 — CSS 파일 자체를 고칠 때는 습관이 됐지만 위젯
   .py 안의 링크 태그를 고칠 때는 깜빡하기 쉬움). 또한 `geo/aot-map-custom-
   controls.js` 처럼 **JS 소스 수정은 `npm run build:bundles` 로 번들 재빌드
   필수**(dist/aot-map-widget.bundle.js 등) — 소스만 고치면 대시보드에
   반영 안 됨. CSS 파일과 달리 이 프론트엔드 빌드는 콘텐츠 해시 기반
   버전이라 브라우저 캐시 문제는 없지만, "재빌드 자체를 안 하면" 여전히
   구버전이 나간다.

**최종 상태(대시보드 페이지 재검증)**: 회색/검정 요소 31→18개로 감소.
잔여 18개는 ① MapLibre 벤더 축척 컨트롤(서드파티, 논터치) ②
SVG `<text>` 축 라벨(별도 렌더링 경로) ③ Highcharts 게이지 dataLabel
(위 4번 항목, 미해결 백로그)로 전부 원인이 특정됨 — "정체불명의 잔여
검정"은 남지 않음.

## 5-5. 지도 도형 색은 별도 계통이다 — 정본은 `GeoSetting.theme_config` (2026-08-05)

여기까지의 토큰 체계(`--aot-*`, custom_ui)는 **앱 UI** 색이다. 지도 위 도형·
마커·라벨의 색은 그와 무관한 별도 계통으로, 정본은 `GeoSetting.theme_config`
(전역 싱글톤 JSON) 하나다. geo/design 하단 모드탭의 원형 피커가 여기에 쓴다.
키: `site` `zone` `facility` `equipment` `device` 와 장치 종류별 `input`
`output` `function` `device_unit`. custom_ui 는 이 값을 읽지도 쓰지도 않는다.

⚠ **`device` 와 `device_unit` 은 다르다.** `device` 는 종류별 색이 미설정일
때 수렴하는 **장치 공통색**이고, `device_unit` 은 복합장치(Device 탭)의 색이다.
복합장치 색을 `device` 에 쓰면 그것을 바꾼 순간 나머지 종류의 폴백까지 바뀐다.

⚠ **새 키를 추가하면 `routes_geo.py` 의 `theme_keys` 화이트리스트에도 넣을 것.**
거기 없는 키는 **조용히 버려진다** — 피커는 색이 바뀐 것처럼 보이고 새로고침하면
되돌아온다(2026-08-08 `theme_vis_device_unit` 이 빠져 복합장치 표시 토글이
저장되지 않았다).

**해석은 반드시 `static/js/common/aot-geo-theme-colors.js`(`window.AoTGeoTheme`)
를 거친다.** 기본값도 이 파일 `DEFAULTS` 한 벌뿐이다. 장치 종류별 색이
미설정이면 장치 공통색(`device`)으로 수렴한다 — 종류마다 다른 폴백을 두지
않는다.

```js
AoTGeoTheme.color('site')            // site/zone/facility/equipment/device
AoTGeoTheme.deviceColor(devType)     // input/output/function + 세부 타입(trigger/pid/…)
AoTGeoTheme.deviceColor(t, theme)    // 위젯처럼 서버가 넘긴 theme 을 쓸 때
```

**왜 한 곳으로 모았나** — 같은 질문("이 도형은 무슨 색인가")에 네 곳이 제각기
답하고 있었고, 그래서 같은 도형이 geo/design 화면과 AoT_map 위젯에서 서로 다른
색으로 그려졌다:

| 갈래 | 정체 | 처리 |
|------|------|------|
| `GeoSetting.theme_config` | 정본 | 유지 |
| `GeoMap.state_json.theme_config` | 지도별 override. 색을 고른 세션에서 만진 키만 담긴 부분 dict 가 지도 저장에 함께 실렸고, 위젯이 이를 전역 위에 덮어써 그 지도만 옛 색으로 굳었다 | 저장·읽기 양쪽 제거 |
| `GeoShape.feature.properties.color` | 도형에 각인된 색. 렌더할 때마다 계산값을 되써 넣던 sync-back 의 산물로, 테마를 바꿔도 그 도형만 옛 색. 위젯은 이 값을 아예 안 읽어 불일치가 고정 | 제거 |
| `localStorage.aot_config_color_*` | 브라우저별 잔재. 미러가 "값이 있을 때만" 덮어써서 설정에서 빠진 키는 옛 값이 계속 이겼다 | 제거(페이지 로드 시 자가 삭제) |

폴백도 갈라져 있었다 — 위젯은 output `#dd4444`/function `#28a745`, geo/design 은
`#995aff`. 미설정 종류의 색이 화면마다 달랐던 두 번째 원인이다.

DB 에 남은 잔재 정리는 `python3 -m aot.scripts.fix_geo_theme_drift`
(기본 dry-run, 반영은 `--apply`).

## 6. 남은 부채 (백로그, 우선순위순)

1. `ai/ai_scheduler.css`(66), `map/map.css`(148), `pages/mcp_servers.css`(39),
   `ai/aot-ai-global.css`(33) 등 비브랜드 하드코딩 잔여 — 표면/보더/텍스트
   토큰으로 단계 치환 (대부분 var() 폴백이 아닌 순수 리터럴).
2. ~~Highcharts 시리즈 팔레트 중복~~ → 완료(2026-07, GRAPH_SERIES_PALETTE 통합.
   주의: widget_graph_synchronous 는 구 Highcharts 기본 팔레트에서 AoT 팔레트로
   변경되어 기본 시리즈색이 달라짐 — 미설치 레거시 위젯이라 영향 없음).
3. `widget_gauge_solid.py` 는 독자 4단계 팔레트(#33CCFF…) — 5단계 밴드 토큰
   통일 여부 결정 필요(위젯 동작 변화라 사용자 결정 사안).
4. `widget_ai_insight.py` 의 #007bff/#28a745 그라데이션 등 Bootstrap 색 —
   AoT 상태색으로 교체(시각 변화 수반).
5. 폴백 전용 미정의 변수 정리: `--aot-accent`, `--aot-color-border`,
   `--aot-text-muted` 등 — 실토큰으로 개명 또는 정식 정의.
6. `:root[data-theme="dark"]` 휴면 블록 — 서버측 다크 로드 방식과 통합하거나 제거.
7. 레거시 별칭 소비처를 실토큰으로 점진 이관 → 별칭 제거.
8. 다크 Bootswatch 스킨(cyborg/darkly/slate/solar/superhero)은 5-4절 body 연결
   대상에서 제외됨 — 그 스킨을 쓰는 사용자는 custom_ui 텍스트색 설정이 여전히
   전혀 반영되지 않는다. 필요시 각 스킨 파일에 상응하는 배선 추가.
9. ~~Highcharts 위젯 데이터 라벨/축 텍스트색 하드코딩~~ → 2026-07 해결.
   `AoT_gauge_angular`(dataLabels + yAxis.labels), `AoT_graph`/`AoT_PID`/
   `widget_graph_synchronous`(xAxis.labels, yAxis 공용 헬퍼 `AoTChart.
   unitYAxis`, rangeSelector 버튼/라벨 각 상태)에 `style.color: 'var(--aot-
   color-text-primary/secondary)'` 를 명시. `widget_gauge_solid` 는 애초
   `format` HTML 문자열에 이미 var() 를 쓰고 있어 손댈 것 없었음.
   `AoT_wind_angular` 는 Highcharts 를 아예 안 쓰는 순수 SVG/HTML 위젯이라
   대상 아님. **남은 한계**: `useHTML:true` 라벨(대부분의 dataLabels)은
   `style.color` 가 실제 CSS `color` 로 적용돼 정상 작동하지만, `useHTML`
   이 아닌 **SVG 렌더링 축 타이틀 일부**는 Highcharts 가 내부적으로
   `fill`(SVG 전용 속성, `color` 와 별개)로 그려 우리가 설정한 `style.color`
   가 반영되지 않는 사례가 하나 남음(`widget_graph_synchronous` 의 y축
   단위 타이틀 "°C" 등, 발생 위젯·빈도 낮음) — SVG `fill` vs CSS `color`
   불일치는 Highcharts 렌더 모드에 따라 갈리므로 필요시 개별 확인 요망.
