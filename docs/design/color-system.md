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
| brand_primary/secondary/accent | --brand-* | --aot-color-brand-* |
| text_color_primary/secondary/tertiary | --text-color-* | --aot-color-text-* |
| bd_primary/secondary/tertiary | --bd-* | (없음 — 페이지 배경층 전용) |
| bg_upgrade / bg_active / bg_inactive | --bg-* | --aot-bg-* |
| bg_llm / bg_mcp | --bg-llm/mcp | --aot-color-llm/mcp |
| bd_btn_primary/secondary | --bd-btn-* | --aot-btn-bg-primary/secondary |
| bd_btn_tertiary | --bd-btn-tertiary | (없음) |
| bg_btn_upgrade/active/inactive/pause/hold | --bg-btn-* | --aot-btn-bg-* |
| bg_btn_on / bg_btn_off | --bg-btn-on/off | (없음 — active/inactive 토큰과 충돌) |
| bd_btn_border | --bd-btn-border | --aot-btn-border-primary |
| band_1..5 (측정 밴드) | (없음) | --aot-band-1..5 |
| chart_1..6 (차트 시리즈) | (없음) | --aot-chart-1..6 |

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
