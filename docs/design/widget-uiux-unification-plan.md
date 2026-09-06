# 위젯 UI/UX 점검 및 통일 계획

상태: **WP0~WP8 전부 시행 완료** (남긴 것은 각 절 끝에 적었다)
작성: 2026-09-06 · 갱신: 2026-09-06
범위: `aot/widgets/*.py`(25종), `aot/aot_flask/static/css/widget/*`,
      위젯 셸(`templates/pages/dashboard_entry.html`), 위젯 설정 모달
선행 문서: [widget_style_cleanup_plan.md](widget_style_cleanup_plan.md)(색·여백 토큰 교체, 부분 시행),
      [widget_typography_plan.md](widget_typography_plan.md)(2026-06-06, 미시행),
      [typography-scale.md](typography-scale.md), [color-system.md](color-system.md)

---

## 0. 어떻게 점검했는가

두 갈래로 확인했고, **모든 수치는 둘 중 하나로 뒷받침된다.**

| 갈래 | 방법 |
|------|------|
| 코드 | `aot/widgets/*.py` 25종 18,905줄 + 위젯 CSS 4개 + 셸 템플릿 정적 분석 |
| 실측 | 로컬 대시보드(김제 — 위젯 11종 16개)에서 `getComputedStyle` 로 실제 렌더 값 계측 |

실측 대상 대시보드가 앱에서 가장 다양하다(11종). 나머지 대시보드는 이 11종의 부분집합이다.

---

## 1. 진단

### 1-1. 뿌리 원인 — 타입 스케일이 **두 벌** 있다

`aot-theme-variables.css` 에 서로 다른 사다리 두 개가 동시에 살아 있다.

| 계열 | 단계 | 값 | 쓰는 곳 |
|------|------|-----|---------|
| `--aot-fs-*` | 3단 | sm .75 / md .875 / **lg 1.5** rem | 위젯 대부분(문서상 "위젯 표준") |
| `--aot-font-size-*` | 6단 | 2xs .7 / xs .75 / **sm .85** / base .95 / **lg 1.05** / xl 1.4 rem | `AoT_plot`, `aot-facility-widget.css`, `aot-sensor-label.css` |

같은 이름(`sm`, `lg`)이 **다른 값**을 가리킨다. 파일 주석은 양쪽 모두 "여기서만 고른다"고 적고 있다.
`--aot-font-size-*` 는 "legacy aliases" 로 주석돼 있으나 실사용은 **61회로 `--aot-fs-*`(46회)보다 많다.**

**실측 결과 — 위젯 본문에 나타난 글자 크기 8가지**

```
10.83px · 11.00px · 11.81px · 12px · 13px · 13.6px · 14px · 16px
```

13.6px = 0.85rem(`--aot-font-size-sm`), 10.83·11.81px = `em` 상대 지정의 산물이다.
3단 사다리를 만들어 놓고 실제 화면엔 8단이 나온다. **"제각각으로 보이는" 인상의 8할이 여기서 나온다.**

### 1-2. 위젯 셸(카드 껍데기) 자체가 규격 밖에 있다

`dashboard_entry.html:13` — 모든 위젯을 감싸는 카드가 인라인 스타일이다.

```html
<div class="grid-stack-item-content widget-outer"
  style="display: flex; flex-flow: column; padding: 0; border: 1px solid #ddd; border-radius: 5px">
```

- 카드 테두리에 값이 **세 개** 돌아다닌다.

  | 출처 | 값 | 결과 |
  |------|-----|------|
  | 인라인(`dashboard_entry.html:13`) | `#ddd` | **이게 이긴다** |
  | `.widget-outer`(`bootstrap-4-themes/aot.css:467`) | `#c9c9c9` | 죽어 있음 |
  | 토큰 `--aot-border-neutral` | 라이트 `#dddddd` / **다크 `#444444`** | 아무도 안 씀 |

  실측 확인: 렌더된 테두리는 `rgb(221,221,221)`.
  라이트에서는 우연히 토큰과 같은 값이라 아무도 눈치채지 못했지만,
  **다크 테마에서는 어두운 카드(`--aot-surface-card: #1e1e1e`) 위에 밝은 `#ddd` 실선이 그대로 남는다.**
  (다크 테마 5종이 `THEMES_DARK` 에 실재한다.)
- `border-radius: 5px` 인라인 ↔ CSS `0.7em !important` 가 서로 싸운다(실측 9.52px — CSS 승).

**셸 CSS 가 세 파일에 흩어져 있고 두 곳은 완전 중복이다.**

| 파일 | `.widget-heading` / `.widget-title` / `.widget-settings` |
|------|--------|
| `aot-base.css:165-198` | 정의 |
| `custom.css:77-113` | **같은 내용 그대로 재정의(복붙)** |
| `dashboard.css:28-38` | `!important` 로 다시 덮음 |

### 1-3. 제목줄에 계약이 없다

25종이 각자 다르게 제목줄을 만든다.

| 형태 | 위젯 |
|------|------|
| `aot-w-title` 사용 | 21종 |
| **클래스 없음** — 크기·굵기가 다름 | `AoT_output_value`, `AoT_output_pwm` |
| 첫 요소가 상태 배지라 제목 클래스가 안 잡힘 | `AoT_PID`, `AoT_timer` |
| 제목줄 정의 자체가 없음 | `AoT_advice`, `AoT_camera` |
| 여분의 `widget-title-bar` 를 더 붙임 | `widget_measurement`, `widget_notice`, `widget_calendar` 등 |

**실측 — 같은 대시보드 안에서 제목 글자가 두 종류로 갈린다.**

| 위젯 | 제목 |
|------|------|
| map / gauge / graph / sequence / notice / plot / function_status … 13개 | **14px · 600** |
| `AoT_timer`, `AoT_output_pwm`, `AoT_output_value` | **13.6px · 400** |

제목줄 오른쪽에 붙는 도구도 규격이 없다 — `AoT_graph` 는 부트스트랩 `btn btn-sm btn-success`,
`AoT_map` 은 자체 `widget-map-ctrl-btn`, 나머지는 아무것도 없다.
`padding-right:0.5em` 인라인이 12곳에 개별로 박혀 있다.

### 1-4. 컨트롤 기하가 제각각 — 토큰이 있는데 안 쓴다

디자인 시스템은 이미 답을 갖고 있다.

```css
--aot-btn-height: 36px;   --aot-btn-height-sm: 32px;
--aot-btn-radius: 18px;   --aot-btn-radius-sm: 16px;
--aot-btn-font-size: 0.85rem;
```

**실측 — 위젯 안 버튼의 실제 높이·모서리**

| 축 | 나온 값 | 토큰과 맞는 것 |
|----|---------|----------------|
| 높이 | 22 · 24 · 29 · 31 · **32** · 34 · 37 px | 32 하나뿐 |
| 모서리 | 0 · 5 · 10 · **16** · 9999 px | 16 하나뿐 |

- `seq-action-btn` = 높이 37 / 반경 10 — 사다리 밖
- `seq-day-btn` = 반경 5 — 사다리 밖
- `widget-map-ctrl-btn` = **12×15px** — 손가락으로 못 짚는다(WCAG 2.5.8 최소 24×24 미달)
- `aot-act-pbtn`(출력 위젯)만 32/16 으로 맞음

여백도 마찬가지다. `--aot-space-1..6`(4px 사다리)이 있는데 위젯에는 `6px`, `9px`, `10px`, `14px`, `20px`
같은 사다리 밖 값이 그대로 있다. 위젯 파일 전체에 인라인 `style="` 이 **101곳**이다.

### 1-5. 색 — 게이지 두 종이 서로 다른 색 언어를 쓴다

`aot/config/__init__.py:723` 에 5단 밴드 팔레트가 **단일 소스**로 있고,
`utils_theme.get_band_palette()` 가 사용자 `custom_ui` 설정까지 얹어 준다.

| 위젯 | 밴드 색 |
|------|---------|
| `AoT_gauge_angular` | `get_band_palette()` ✓ — 사용자 설정 반영됨 |
| **`widget_gauge_solid`** | `["#33CCFF","#55BF3B","#DDDF0D","#DF5353"]` **하드코딩 4단** — Highcharts 기본색. 사용자 설정 무시 |

같은 "낮음→높음"인데 한쪽은 AoT 5단 색, 한쪽은 Highcharts 4단 색이다. 나란히 놓으면 다른 제품처럼 보인다.

그 밖에:

- `AoT_wind_angular` — SVG 글자색 `#111`, `#333`, `#9aa0a6` 하드코딩(토큰 2회 vs 하드코딩 31회).
  **다크 테마에서 검은 배경에 검은 글자가 된다.**
- `AoT_gauge_angular:639` — `{% if current_user.theme in dark_themes %}#e3e4f4{% else %}#3e3f46{% endif %}`.
  테마 분기를 CSS 토큰이 아니라 서버 템플릿에서 한다. 테마가 늘면 여기도 같이 고쳐야 한다.
- ~~`AoT_wind_angular` 기본 방향색 `#F4D624` 가 브랜드 노랑과 한 끗 다르다~~ →
  **정정(2026-09-06):** `#F4D624` 는 차트 팔레트의 `--aot-chart-4` 와 정확히 같은 값이다.
  브랜드 `--aot-color-primary`(#F2D524)와 다른 것은 맞지만, 그 둘이 다른 것은
  색 체계의 설계이지 이 위젯의 실수가 아니다. 손대지 않는다.

**대비(WCAG AA) 실측 위반 2건**

| 대상 | 색 | 대비 | 필요 |
|------|-----|------|------|
| `seq-day-label-text`(토요일) | `--aot-color-danger` #DF5353 on #fff | **3.51:1** | 4.5:1 |
| `aot-notice-widget-category-badge` | #5E6B64 on #f1f3f5, 10.88px | **4.41:1** | 4.5:1 |

토요일 건은 답이 이미 같은 파일에 있다 — `widget_trigger_sequence.py:752` 주석이
"danger 틴트 배경은 밝아서 안 보인다 — fg 토큰과 쌍으로 쓴다"고 적어 두고
`--aot-tint-danger-fg`(#b23b3b, 대비 5.87:1)를 쓰는데, 요일 라벨만 그 규칙에서 빠졌다.

### 1-6. 로딩·빈 상태·오류 표현이 없다

25종 중 **로딩 표시가 있는 위젯 8종, 빈 상태 문구가 있는 위젯 7종**(키워드 기준 근사).
나머지는 데이터가 없거나 늦으면 **빈 칸**을 보여준다. 사용자는 "고장인지 로딩인지" 구분할 수 없다.
표준 패턴(스켈레톤/문구/재시도)이 없어서 있는 것들끼리도 생김새가 다르다.

또 하나 — ~~위젯 본문에 overflow 정책이 없어 내용이 카드 밖으로 삐져나간다~~
→ **정정(2026-09-06, WP5 에서 확인):** 삐져나가지 않는다. gridstack 자체 CSS 가
`.grid-stack>.grid-stack-item>.grid-stack-item-content` 에
`overflow-x: hidden; overflow-y: auto` 를 이미 걸어 두고 있고, 그 요소가 바로
`.widget-outer` 다(같은 요소에 두 클래스가 붙는다). AoT_plot 주석의
"위젯 카드가 `overflow:auto` 라" 는 이 규칙을 가리킨 말이었다.

대신 **진짜 문제는 그 스크롤바가 보인다는 것**이었다 — 이 저장소는 "스크롤은
되되 스크롤바는 보이지 않는다" 를 규칙으로 삼는다. 실측하면 이 대시보드의
위젯 카드 16개 중 **6개가 실제로 세로 스크롤 중**이다.

### 1-7. 설정 UI — 죽은 노브와 부트스트랩 잔재

**(a) 아무 일도 안 하는 설정이 모든 위젯에 노출된다.**

`TEMPLATE_OPTIONS_WIDGET_MOD.html:22` 의 **"Font Size (em)"**(`font_em_name`)은
위젯 추가·수정 폼 **전체**에 뜨지만, 실제로 읽는 위젯은 `widget_function_status` **한 종뿐**이다.
나머지 24종에서는 값을 바꿔도 화면이 그대로다.

원인은 계보에 있다. `widget_typography_plan.md`(2026-06-06)는
"사용자 `font_em_*` 옵션은 배수로 보존"을 결정 사항으로 적었는데,
실제로 만들어진 `aot-widget-typography.css` 는 첫 줄에
"Font SIZE is set here only — never via inline style" 로 **고정 크기**를 택했다.
계획과 구현이 갈라지면서 노브만 남았다.

**(b) 현대화 모달 안에 부트스트랩 마크업이 섞여 있다.**

| 위젯 | 설정 UI 마크업 |
|------|----------------|
| `widget_notice`, `AoT_graph`, `AoT_map` | `aot-modal-option-row` 등 규격 준수 ✓ |
| **`AoT_gauge_angular`, `widget_gauge_solid`, `AoT_wind_angular`** | `form-row` / `col-auto` / `control-label` / `form-control` — 부트스트랩 원본 |

같은 모달 안에서 행 높이·라벨 정렬·입력칸 모양이 위아래로 달라진다.

**(c) 같은 일을 하는 UI 가 두 벌 있다.**
색 고르기가 `components/aot-color-picker.css` 로 공용화돼 있는데,
`AoT_wind_angular:296-313` 은 `.aot-color-preset` 스와치를 **인라인 `onclick` 으로 자체 구현**하고,
`AoT_gauge_angular:384` 는 맨 `<input type="color">` 를 쓴다. 셋 다 다르게 생겼다.

**(d) 옵션 개수 편차가 크다.** `AoT_map` 40개 · `AoT_graph` 22개 · `AoT_facility` 17개 vs
`AoT_output_*` 2개. 그룹 제목만 있고 접기/고급 구분이 없어서 긴 쪽은 스크롤로 훑어야 한다.

### 1-8. 접근성 — 사실상 백지

25종 전체를 통틀어 `aria-label` 12회, `role` 10회, `tabindex` 5회.
**17종은 접근성 속성이 하나도 없다.**
`widget_trigger_sequence` 에는 키보드로 못 닿는 `<div onclick>` 이 2곳,
`AoT_wind_angular` 에는 `<span onclick>` 이 2곳 있다.

### 1-9. 부수 — 중복 로드

한 대시보드 head 에 스타일시트 44개, 그중 **7개가 중복**이다.
`aot-toggle.css` 4회, `aot-sensor-label.css`·`aot-facility-widget.css`·`aot-time-wheel.css` 각 3회.
`layout.html` 이 이미 넣은 파일을 위젯 `widget_dashboard_head` 가 다시 넣는다(타입별 1회씩).

---

## 2. 개선 계획

원칙 세 가지로 간다.

1. **없는 것을 새로 만들지 않는다.** 토큰·공용 클래스·팔레트 단일 소스는 이미 다 있다.
   문제는 "안 쓴다"이지 "없다"가 아니다.
2. **셸부터 고친다.** 25종을 각자 고치기 전에, 모든 위젯이 공유하는 껍데기를 규격화하면
   한 번의 수정이 25번 반영된다.
3. **되돌아가지 못하게 막는다.** 고쳐 놓고 다음 위젯이 또 벗어나면 3개월 뒤 같은 문서를 쓴다.

### WP0 — 타입 스케일 한 벌로 ✅ 완료

두 사다리를 **한 벌 6단**으로 합쳤다. 이름이 여섯 개 남았고, 각 이름은 값 하나만 가리킨다.
`--aot-font-size-*` 가 크기 사다리이고, `--aot-fs-*` 는 그 단들을 가리키는 **역할 이름**이다.

| 단 | 값 | 바뀐 것 | 역할 이름 |
|----|-----|---------|-----------|
| 2xs | 0.7rem (11.2px) | — | |
| xs | 0.75rem (12px) | — | `--aot-fs-sm` · `--aot-fs-caption` |
| sm | **0.875rem (14px)** | 0.85 → 0.875 (+0.4px) | `--aot-fs-md/label/body/unit/title` · `--aot-btn-font-size` |
| base | **1rem (16px)** | 0.95 → 1 (+0.8px) | |
| lg | **1.125rem (18px)** | 1.05 → 1.125 (+1.2px) | `--aot-fs-value-sm` |
| xl | **1.5rem (24px)** | 1.4 → 1.5 (+1.6px) | `--aot-fs-lg` · `--aot-fs-value` · `--aot-fs-value-lg` |

이것이 **미결 질문 3번의 답**이다: `--aot-font-size-lg`(1.05rem)는 이미 존재하던
`--aot-fs-value-sm`(1.125rem) 단으로 올려 흡수했다. 가장 많이 쓰이는 `sm`(139곳)은
0.85 ↔ 0.875 의 0.4px 차이라 사실상 무변화이고, 나머지 셋은 사용처가 각각
13·6·2곳(모달·일지·시설 카드)이라 영향이 좁다.

`--aot-btn-font-size` 는 `bootstrap-4-themes/aot.css` 가 `1em` 으로, `aot.css` 가
**자기 자신을 참조하는 무효값**으로 각각 덮고 있었다 — 둘 다 제거해 사다리가 실제로 다스리게 했다.

산출물: `aot-theme-variables.css` · `aot.css` · `bootstrap-4-themes/aot.css` ·
`aot-widget-typography.css` 머리주석 · 옛 값이 박힌 주석 2곳(`geo-facility.css`, `aot-dataviz.css`)

**검증(브라우저 실측, 워크트리 CSS 를 실제 페이지에 주입해 계산값 측정):**
사다리가 순환·미정의 없이 `11.2 · 12 · 14 · 16 · 18 · 24px` 여섯 값으로만 풀린다.
역할 이름 11개가 전부 그 여섯 중 하나에 떨어진다. `--aot-btn-font-size` = 14px.

### WP1 — 위젯 셸 규격화 ✅ 완료 (overflow 정책만 보류)

셸 모양이 흩어져 있던 네 곳을 `aot-base.css` 의 "위젯 셸" 절 **한 곳**으로 모았다.

- `dashboard_entry.html` 의 인라인 `style=`(카드·본문·아이콘) 전부 제거
- 테두리 값 세 개(인라인 `#ddd` · 테마 `#c9c9c9` · 토큰) → `var(--aot-border-neutral)` 하나로.
  **다크 테마에서 `#444444` 로 따라온다**(실측 확인)
- `.widget-outer` 를 테마 파일에서 `aot-base.css` 로 이관 —
  테마 파일에 있으면 cyborg·darkly 등에서는 카드가 아예 안 그려졌다
- `custom.css` 의 복붙본 15규칙(97줄) 삭제(`aot-base.css` 와 글자까지 동일함을 규칙 단위로 대조 후 제거)
- `dashboard.css` 의 `!important` 5개 제거 — 정본이 하나뿐이라 특정도만으로 이긴다
- 본문 컨테이너에 `.widget-body` 클래스 신설(`position:relative` · `flex:1 1 auto` · `min-height:0`)
- "알 수 없는 위젯" 오류 카드의 인라인 스타일도 클래스로

**보류했던 `overflow` 정책 — WP5 에서 결론.** 여기서 넣지 않은 판단은 맞았지만
이유는 틀렸다. 실제로는 gridstack 이 이미 `overflow-x:hidden; overflow-y:auto` 를
걸어 두고 있어서 **넣을 것이 없었다.** 남은 일은 스크롤바를 감추는 것이었고
WP5 에서 처리했다.

산출물: `dashboard_entry.html` · `aot-base.css` · `custom.css` · `dashboard.css` ·
`bootstrap-4-themes/aot.css`

**검증(브라우저 실측, 인라인 style 이 없는 깨끗한 요소로 셸 규칙만 측정):**
`.widget-outer` → `display:flex` / `column` / `1px #dddddd`(토큰) / radius 9.8px / 카드배경 / 그림자.
같은 토큰이 다크 값 스코프에서는 `#444444` 로 풀린다.
`.widget-body` → `relative` / `1 1 auto` / `min-height:0`.

### WP2 — 제목줄 계약 ✅ 완료

**이름은 셸이 렌더한다.** 위젯의 `widget_dashboard_title_bar` 는 이름 옆 부가물만 담는다.

```
[제목 — 셸이 그림, 항상 .aot-w-title] [상태·시각 .aot-w-caption] [도구 .aot-w-tool]
```

새 슬롯 키를 만들지 않고 **셸이 이름을 그리고 위젯 조각은 부가물만 남기는** 방식을 택했다 —
생성기(`widget_generate_html.py`)·라우트·25개 파일을 동시에 바꾸지 않고도 같은 결과가 난다.

- 위젯이 직접 그리던 제목 span **21종 → 0종**
- `padding-right:0.5em` 인라인 **12곳 → 0곳** (셸의 `.aot-w-title + .aot-w-caption` 간격으로 대체)
- 클래스 누락 2종(`AoT_output_value`·`AoT_output_pwm`)과 상태 배지가 제목 자리를 차지하던
  2종(`AoT_PID`·`AoT_timer`) 자동 해소 — 상태 배지는 `.aot-w-caption` 으로 내리고 이름 뒤로 옮겼다
- 제목줄이 아예 없던 2종(`AoT_advice`·`AoT_camera`)에 이름이 생겼다
- `AoT_weather_fcst_announcement` 는 예보 시각이 `aot-w-title` 이라 **제목 행세**를 하고 있었다
  (그래서 이 위젯만 이름이 안 보였다). 캡션으로 내리고, 그 값을 다시 쓰던 JS 도
  `innerHTML` 로 제목 클래스를 덧씌우지 않게 `textContent` 로 바꿨다
- `AoT_controller` 의 "이름이 비면 대체 이름" 은 제거 — 제목 span 이 둘이 되어
  라이브 미리보기가 빈 쪽에 이름을 써 넣으면 두 이름이 겹쳤다
- 도구 버튼 규격 하나(`.aot-w-tool`) 신설 — `AoT_graph` 의 부트스트랩
  `btn btn-sm btn-success`(초록 그라디언트)와 `btn btn-sm menu`, `AoT_map`·`widget_notice` 의
  `widget-map-ctrl-btn` 을 모두 흡수. **12×15px 이던 지도 버튼이 24×24px** 이 되어
  WCAG 2.5.8 최소 크기를 넘겼고, 키보드 포커스 표시(`:focus-visible`)가 생겼다
- `AoT_graph` 의 모바일 메뉴는 자기 제목 div 대신 셸의 `#widget-title-<uid>` 를 토글한다.
  `className` 통째 교체 → `classList.toggle` 로 바꿔 다른 클래스를 지우지 않는다

> ⚠ `AoT_map` 의 lock/hide 버튼 **이름표는 `title` 로 두었다.**
> 그 값은 눌릴 때마다 `aot-map-widget-vector.js` 가 다시 쓰기 때문에, 템플릿에서
> `aria-label` 을 따로 주면 누른 뒤 값이 어긋난다. 이름표 일원화는 그 JS(번들 재빌드)와
> 함께 WP7 에서 다룬다.

산출물: `dashboard_entry.html` · `aot-base.css` · 위젯 25종

**검증(Jinja 실렌더):** 셸 + 각 위젯 제목줄을 조립해 렌더한 결과,
제목줄을 정의한 23종 모두 `.aot-w-title` 이 **정확히 1개**. 나머지 2종은 셸 것만 나온다.
`.aot-w-tool` 은 브라우저 실측으로 24×24px · radius 16px · 14px 확인.

### WP3 — 컨트롤 기하 통일 ✅ 완료

**먼저 토큰이 거짓말을 하고 있었다.** 사다리를 쓰라고 해 놓고 정작 사다리가
화면과 달랐다:

| 토큰 | 적혀 있던 값 | 실제로 그려지던 값 | 왜 |
|------|-------------|------------------|-----|
| `--aot-btn-height` | 36px | **32px** | 뒤에 로드되는 `aot.css`·`bootstrap-4-themes/aot.css` 가 둘 다 32px 로 덮어썼다 |
| `--aot-btn-height-sm` | 32px | 32px | 위와 같은 값 — "두 단"이라던 사다리가 실제로는 한 단이었다 |
| `--aot-btn-font-size` | 0.85rem | `1em`(부모 따라감) | 테마가 `1em` 으로, `aot.css` 는 **자기 자신을 참조**하는 무효값으로 덮었다(WP0 에서 처리) |

덮어쓰던 곳을 지우고 정본을 **실제 값**으로 맞췄다. 값은 그대로이고 정의만
한 곳으로 모였으므로 화면은 변하지 않는다.

**정본 버튼이 토큰을 안 쓰고 있었다.** `.btn.aot-pill-btn` — 앱의 기준 컨트롤 —
이 `height: 32px; border-radius: 9999px` 처럼 숫자를 직접 적고 있었다.
기준이 숫자를 적고 있으면 아래 어느 위젯도 토큰을 쓸 이유가 없다.
이미 있던 `--aot-btn-height`·`--aot-btn-pill-radius` 를 읽게 했다(값 동일).

**위젯 안 컨트롤을 사다리에 맞췄다.**

| 대상 | 전 | 후 |
|------|-----|-----|
| `btn-aot-pid-sm` · `btn-aot-pid-resume` (PID) | 34px · `0 0.4em` | 32px · `--aot-space-1` |
| `aot-cnt-time-trigger` · `aot-cnt-cycles` (타이머) | 34px · `0 1em` | 32px · `--aot-btn-padding-x` |
| `seq-action-btn` (시퀀스) | `padding 5px 4px` → 37px · 반경 10px | 최소높이 32px · 알약 반경 |
| `seq-group-new-input` · `seq-step-newrow input` | 36px · 반경 18px | 32px · 알약 반경 |
| `seq-expand-btn` | 32px · 16px (리터럴) | 같은 값, 토큰으로 |
| `notice-widget-poll-remove-btn` | 인라인 `height:26px; font-size:0.72rem` | 인라인 제거 — 공용 알약 그대로 |

`seq-action-btn` 은 `height` 가 아니라 **`min-height`** 로 두고 정본 알약과 같은
`inline-flex` 짜임을 줬다. 고정 높이로 못 박으면 좁은 폭에서 글자가 두 줄이 될 때
상자 밖으로 삐져나온다.

**일부러 안 건드린 것**

- `seq-day-btn`(반경 5px) — 낱개 버튼이 아니라 일곱 칸이 붙은 격자의 한 칸이다.
  알약이 되면 칸끼리 떨어져 보여 "한 주"로 안 읽힌다. 여백 `6/2/7` 도 두 줄
  (요일·날짜)을 눈으로 맞춘 값이라, 보지 않고 사다리에 스냅하면 정렬이 어긋난다.
  **타일용 반경 사다리가 아직 없다** — 위젯 CSS 에 8px 12곳 · 12px 3곳 · 6px 3곳 ·
  5px · 4px 가 흩어져 있다. WP8 의 규약에서 함께 정한다.
- 시퀀스 단계 편집 시트의 입력칸(44px · 40px) — 폰에서 손가락으로 짚는 시트라
  일부러 키운 것으로 보인다. **실제 폰 화면을 보지 않고 줄이지 않는다**(WP5).
- 알약 버튼의 좌우 여백 — 정본은 14px, 센서라벨 계열은 12px(`--aot-btn-padding-x`).
  어느 쪽으로 맞출지는 두 화면을 나란히 놓고 정할 일이라 그대로 뒀다.

**새로 확인한 결함(고치지 않음)** — `aot-pill-btn-sm` 은 geo 페이지·구획 위젯·
프로그램 설정 등 **10곳 넘게 마크업에 쓰이는데 CSS 정의가 어디에도 없다.**
작성자는 작은 버튼을 요청했지만 전부 기본 크기(32px)로 그려진다. 지금 정의하면
위젯 밖 여러 화면의 버튼이 한꺼번에 작아지는데 그 화면들을 확인할 수 없어
**보고만 하고 두었다.**

산출물: `aot-theme-variables.css` · `aot-modal-modern.css` · `aot.css` ·
`bootstrap-4-themes/aot.css` · 위젯 4개

**검증**
- 브라우저 실측: 토큰이 한 곳에서만 정의되고(`--aot-btn-height`·
  `--aot-btn-padding-x`·`--aot-btn-font-size` 각 1회), 정본 알약 버튼의
  높이·반경이 토큰화 전후로 **동일**함(32px / 9999px) — 값 변경 없는 정리임을 확인.
- 위젯 안 컨트롤은 위젯 자체 `<style>` 에 있어 주입 검사로는 안 잡힌다.
  소스 대조로 34px·36px·37px 이 남아 있지 않음을 확인했다.

### WP4 — 색 정합 ✅ 완료

**게이지 두 종이 같은 색 언어를 쓴다.** `widget_gauge_solid` 이 자체 하드코딩하던
Highcharts 기본 4색을 버리고 두 게이지 모두 `_band_palette()`(= `get_band_palette()`,
사용자 `custom_ui` 오버레이 포함) 하나만 읽는다. `AoT_gauge_angular` 의
`gauge_reformat_stops` 도 팔레트를 다시 적어 두고 있어 같이 정리했다.

기존 위젯 처리는 **사용자 저장값 우선**(2026-09-06 결정):

| 상황 | 동작 |
|------|------|
| 저장된 구간색이 있다 | **그대로 둔다** — 팔레트로 덮지 않는다 |
| 새로 추가한다 | 5단 팔레트 기본값 |
| 구간을 늘린다 | 늘어난 칸은 팔레트 마지막 단(가장 높음)으로 |

`widget_gauge_solid` 의 구간 수 기본값도 4 → 5 로 올렸다(팔레트와 같은 단수,
각도 게이지와 동일). 기본값이라 **이미 만들어 둔 위젯에는 영향이 없다.**

**다크 테마에서 안 보이던 것들**

- `AoT_wind_angular` 의 SVG 글자(`#111`·`#333`·`#9aa0a6`)를 CSS 클래스로 옮겼다.
  SVG 글자색은 `fill` 이라 텍스트 토큰이 자동으로 따라오지 않는데, CSS 의 `fill`
  선언은 표현속성보다 세므로 클래스 세 개로 한 번만 정한다
  (`.aot-windw-value/-sub/-rose`).
- `AoT_gauge_angular` 의 서버측 테마 분기(`{{ '{% if current_user.theme in dark_themes %}' }}`)를
  없앴다. 새 토큰 `--aot-gauge-dial`·`--aot-gauge-tick` 을 위젯 JS 가
  `aotThemeColor()` 로 읽는다 — Highcharts 는 이 색을 SVG 표현속성으로 넣기 때문에
  `var()` 가 풀리지 않아 한 번 계산해 문자열로 넘겨야 한다.
  덤으로 **다크에서 바늘만 밝아지고 축(minColor/maxColor)은 어두운 채 묻히던 것**도
  같은 토큰을 쓰면서 함께 고쳐졌다.

**대비 위반 2건 수정** — 사용자의 실제 테마 설정에서 실측:

| 대상 | 전 | 후 | 기준 |
|------|-----|-----|------|
| 시퀀스 주말 라벨 (`--aot-color-danger` → `--aot-tint-danger-fg`) | 3.51:1 | **5.39:1** | 4.5:1 |
| 공지 분류 배지 (보조색 → 본문색) | 4.41:1 | **12.57:1** | 4.5:1 |

배지는 기본 토큰(`--aot-surface-body: #F3F6F5`)에서는 5.13:1 로 아슬하게 통과하는데,
이 설치본은 사용자가 그 색을 `#e0e6e3` 로 바꿔 두어 **4.41:1 로 떨어져 있었다.**
문턱에 걸쳐 있던 값이라 사용자의 색 선택 하나로 넘어간 것이다 —
본문색으로 올리면 어느 설정에서도 넉넉하다. 크기도 `0.68rem` 이라는 사다리 밖
값이어서 `--aot-font-size-2xs`(0.7rem)로 맞췄다.

**선행 계획(widget_style_cleanup_plan.md) 미시행분 흡수**

- `AoT_advice` — 지역 변수 이름이 `--aot-bg`/`--aot-text`/`--aot-border` 였다.
  **전역 이름공간의 아주 흔한 이름**이라 위쪽 어느 요소가 같은 이름을 정의하면
  이 위젯이 조용히 그 값을 물려받는다. `--aot-advice-*` 로 격리했다.
  (어두운 배경 고정은 주석에 적힌 **의도된 선택**이므로 그대로 둔다 —
  선행 계획이 이것을 버그로 본 것은 잘못이다.)
- `AoT_camera` — 영상 바탕 `#000` → `--camera-preview-bg`(앱의 다른 카메라
  미리보기와 같은 토큰). HUD 오버레이의 흰 글자+그림자는 **임의의 영상 위**에
  얹히므로 테마를 따르지 않는 것이 맞다 — 유지하고 크기만 사다리에서 골랐다.
  인라인 `style=` 3곳 → 0곳.
- `AoT_weather_fcst_announcement` — JS 문자열 안의 인라인 배치
  (`display:flex;justify-content:space-between;width:100%` 8곳, 표 칸 6곳)를
  공용 `.aot-w-row-between`·`.aot-w-cell` 로 옮겼다. 행 간격 `10px`·칸 여백 `8px`
  같은 사다리 밖 값도 `--aot-space-*` 로. `.aot-w-value` 가 이미 정하는
  굵기를 인라인으로 다시 덮던 것도 제거.
- `AoT_map` — 선행 계획이 적어 둔 하드코딩(`#333`·`#ccc`·보라 틴트)은 **현재 파일에
  없다**(그 사이 정리됐거나 JS 번들로 옮겨갔다). 남은 것은 그림자·모달 스크림의
  `rgba(0,0,0,…)` 뿐이라 손대지 않는다.

산출물: 위젯 7개 + `aot-theme-variables.css` · `custom-dark.css` · `aot-base.css`

**검증**
- 게이지: 저장값이 있으면 **원본과 완전 동일**하게 유지되고, 없을 때만 5단 팔레트가
  나오는 것을 두 위젯 모두에서 확인(파이썬 직접 호출).
- 대비: 사용자의 실제 테마가 적용된 페이지에서 새 선언을 얹어 재측정 —
  위젯 안 텍스트의 AA 위반이 3건 → **1건**(아래 미해결).

> **미해결 1건.** `AoT_plot` 의 구획 선택 상자(`bootstrap-select`)의 선택값이
> `#999999` 로 그려져 흰 바탕에서 2.85:1 이다. `bs-placeholder` 클래스는 붙어
> 있지 않고, 그 요소·버튼에 `color` 를 정하는 CSS 규칙을 브라우저에서 찾지 못했다
> (`.btn-white` 는 `--aot-color-text-secondary`=#5E6B64 를 준다).
> **원인을 확인하지 못해 고치지 않았다** — 짐작으로 덮으면 다른 곳이 어긋난다.
> 벤더 컴포넌트와의 상호작용이라 WP6(설정 UI)에서 선택 상자를 손볼 때 함께 본다.

### WP5 — 상태 표현 표준 ✅ 완료(핵심) / 일부 남김

**먼저 `overflow` 부터 결론.** 계획이 전제한 "내용이 카드 밖으로 삐져나간다" 는
**사실이 아니었다.** gridstack 이 이미 `.grid-stack-item-content`(= `.widget-outer`)에
`overflow-x: hidden; overflow-y: auto` 를 걸어 둔다. 넣을 정책이 없었다.

대신 실측에서 나온 것은 **그 스크롤바가 보인다**는 것이다 — 저장소 규칙은
"스크롤은 되되 스크롤바는 절대 안 보이게" 이고, 대시보드 탭 줄은 이미 그렇게
되어 있는데 위젯 카드만 빠져 있었다. 이 대시보드에서 카드 16개 중 **6개가 실제로
세로 스크롤 중**이다. 동작은 그대로 두고 막대만 감췄다.

**값이 없을 때 무엇을 보여줄지 — 위젯마다 답이 달랐다.**

| 위젯 | 값이 없을 때 (전) |
|------|------------------|
| `widget_measurement` · `_multi` · `widget_indicator` | `NO DATA` |
| `AoT_advice` | 한 문장 안내(`aria-live` 까지 붙어 있다 — 가장 잘 된 예) |
| `AoT_facility` | "Loading..." |
| **`AoT_gauge_angular` · `widget_gauge_solid`** | **아무것도 안 그림 — 값 자리가 빈 칸** |
| **`AoT_wind_angular`** | **빈 칸 + 바늘이 0°(북)** |

빈 칸은 "값이 0" 인지 "센서가 죽었" 는지 "아직 로딩 중" 인지를 구분해 주지 않는다.
풍향은 더 나쁘다 — 값이 없는데 **바늘이 북쪽을 가리켜 멀쩡한 측정값처럼 보였다**
(204 응답과 통신 실패 둘 다 `aotWindUpdateNeedle(widget_id, 0)` 을 불렀다).

고친 것:

- 값 자리에는 `—`(em dash). 단위는 붙이지 않는다 — "— °C" 는 값을 찾게 만든다.
- 풍향은 값이 없으면 **바늘을 감추고** 방향 글자도 대시로.
- solid 게이지는 `format` 문자열로는 null 을 구분할 수 없어(Highcharts 가 라벨을
  아예 안 그린다) `formatter` 함수로 바꿨다.
- 공용 클래스 `.aot-w-state` / `.aot-w-state-text` / `.aot-w-state-error` /
  `.aot-w-nodata` 를 `aot-base.css` 에 뒀다. **문구는 새로 만들지 않았다** —
  `NO DATA` · `Loading...` 같은 기존 msgid 가 이미 22개 언어로 번역돼 있다.

산출물: `aot-base.css` + 게이지 3종

**검증(브라우저 실측)**: 스크롤바가 `auto` → **`none`** 으로 바뀌고 스크롤 동작은
그대로임을 확인(스크롤 중인 카드 6개). 공용 클래스가 풀리는 것도 확인.
게이지 formatter 는 Jinja 를 벗겨 `node --check` 로 구문 확인.

**남긴 것**

- **"로딩 중" 과 "데이터 없음" 의 구분.** 지금은 첫 응답 전에도 대시가 뜬다.
  구분하려면 위젯마다 fetch 상태를 들고 있어야 해서, 반쯤 만들기보다 남긴다.
  통신 실패(오류)와 204(값 없음)의 구분도 같다 — `.aot-w-state-error` 는 준비돼 있다.
- **스크롤 여지 표시.** 막대를 감췄으니 "아래에 더 있다" 는 신호도 함께 사라졌다
  (맥은 원래 겹침 스크롤바라 쉬던 중엔 안 보였지만, 윈도·리눅스는 늘 보였다).
  보통은 아래쪽에 옅은 그라데이션을 깔아 대신한다 — 카드 배경과 겹치는 모양이라
  25종에 한 번에 넣기 전에 실제로 보고 정해야 한다.
- **시퀀스 단계 편집 시트의 입력칸(44px · 40px).** WP3 에서 미뤘던 것을 다시 봤다.
  이력상 44px 은 2026-07-15 에 들어갔고 손가락 화면 115% 규칙은 2026-08-20 이라
  "그 규칙 이전의 수동 조정" 으로 읽힌다. 그런데 **줄이는 것이 맞다고 보기 어렵다** —
  WCAG 2.5.5 는 손가락 표적으로 44×44 를 권한다(2.5.8 의 최소는 24×24).
  오히려 앱 표준 32px 쪽이 권고보다 작다. 위젯 하나가 아니라 **앱 전체 컨트롤
  높이의 문제**라 여기서 건드리지 않는다.

### WP6 — 설정 UI 정리 ✅ 완료

**(a) `font_em_name` 제거** (2026-09-06, 사용자 결정)
  - 위젯 추가·수정 폼에서 "Font Size (em)" 칸 삭제
  - `utils_dashboard.py` 의 저장 두 곳에서 이 필드 읽기 제거 —
    폼에 없는 필드를 읽으면 `None` 이 Float 열을 덮는다. 모델 기본값 1.0 이 유지된다
  - 유일한 소비자였던 `widget_function_status` 는 공용 `.aot-w-body` 크기를 쓴다
  - DB 열(`widget.font_em_name`)과 폼 필드 선언은 **기존 행 호환을 위해 남겼다** —
    어느 템플릿도 그리지 않고 어느 저장 경로도 읽지 않는다(주석으로 명시)

**(b) 부트스트랩 잔재 → 표준 옵션 행.** `AoT_gauge_angular`·`widget_gauge_solid`·
`AoT_wind_angular` 의 `form-row`/`col-auto`/`control-label` 을 전부
`aot-modal-option-row` + `aot-modern-input` 으로 바꿨다. 각자 만들던 절 제목도
`aot-modal-section-title` + `aot-modal-container` (다른 위젯이 이미 쓰는 형태)로.
`widget_gauge_solid` 의 라벨 "Stop"·"Color" 는 **번역 함수 없이 영어로 박혀**
있어서 함께 감쌌다(22개 언어로 나가는 앱이다).

> **덤으로 나온 실제 버그.** `AoT_wind_angular` 는 `direction_dot_px` 와
> `text_y_offset` 을 **한 모달에 두 번** 그리고 있었다 — 한 번은 표준 렌더러가
> (custom_options 에 선언돼 있으므로), 한 번은 손으로 만든 블록이. 같은 `name`
> 의 입력이 둘이라 저장 때는 앞의 것만 반영되고, 뒤엣것을 고친 사용자는 값이
> 안 바뀌는 것을 봤다. 실제 화면의 모달 마크업을 읽어 확인했다. 손으로 만든
> 쪽을 지웠다(표준 렌더러 쪽이 원래 이기던 값이라 저장 동작은 그대로다).

**(c) 색 고르는 자리 하나로.** 계획은 `components/aot-color-picker.js` 웹컴포넌트로
모으는 것이었는데, **그 파일은 어디에서도 로드되지 않는 죽은 코드**다
(`aot/scripts/publish/gen_exclude.py` 가 이미 DEAD 목록에 올려 두었다).
살아 있는 규격은 `aot-modal-option-row` 안의 `input[type=color]` 이므로 그쪽으로
모았다. 미리 고르는 칩은 `pages/form_options/Color_Presets.html` 부품 하나로
빼고, 스타일은 `aot-modal-modern.css` 의 `.aot-color-presets`/`.aot-color-preset`
한 곳에 뒀다(예전에는 풍향 위젯이 자기 `<style>` 에 `#bbb` 테두리·`#666`
외곽선으로 따로 정의했다).

> ⚠ 칩의 동작은 인라인 `onclick` 으로 남겼다. 위젯 설정 모달의 본문은
> `<template class="aot-lazy-modal-body">` 에 담겼다가 처음 열 때 `cloneNode`
> 로 복제되는데, **복제된 조각의 `<script>` 는 실행되지 않는다.** 위임 리스너로
> 바꾸려면 `app/dashboard.js` 에 넣고 번들을 다시 빌드해야 하므로 WP8 에서
> 번들 손볼 때 함께. 대신 문구가 위젯마다 흩어지지 않도록 부품 파일 한 곳에만 적었다.

**(d) 기본/고급 접기.** `AoT_map`(40개)은 **이미 6개 그룹으로 접혀 있었다** —
계획에서 대상으로 적은 것은 잘못이다. 실제로 손볼 것은 그룹이 아예 없던
게이지들이었다. 모달을 열었을 때 바로 보이는 옵션 수(실측):

| 위젯 | 전 | 후 |
|------|-----|-----|
| `AoT_gauge_angular` | 12 | **8** (구간 4개를 그룹으로 + [모양] 접기) |
| `AoT_wind_angular` | 12 | **7** (범위 그룹 + [모양] 접기) |
| `AoT_graph` | 23 | **19** ([글자 크기] 4개 접기) |
| `AoT_map` | 6 | 6 (이미 되어 있었음) |

산출물: 위젯 4개 + `pages/form_options/Color_Presets.html`(신규) + `aot-modal-modern.css`

**검증**
- 설정 UI 를 Jinja 로 실제 렌더해 마크업 확인 — 색 칩의 현재값 표시(`is-picked`)까지.
- 정적 검사로 25종 전체에서 **부트스트랩 잔재 0 · 중복 필드 0** 확인
  (표준 렌더러가 그리는 옵션 id 와 위젯이 직접 그리는 `name=` 의 교집합).
- 옵션 목록을 파싱해 `collapse_start`/`collapse_end` 짝이 맞는지, 접힌 뒤 몇 개가
  남는지 확인.

> **미해결(WP4 에서 넘어온 1건) — 원인 못 찾음.** `AoT_plot` 의 구획 선택 상자
> 선택값이 `#999999` 로 그려져 2.85:1 이다. 추가로 확인한 것:
> 서버가 내려주는 CSS 전체에서 `color:#999` 를 선언하는 곳은
> `bootstrap-select.min.css` 의 `.bs-placeholder` **한 곳뿐인데**, 그 버튼에는
> `bs-placeholder` 클래스가 붙어 있지 않다(자리막이가 아니라 실제 선택값이
> 표시돼 있다). 브라우저에서 그 요소·버튼에 매치되면서 `color` 를 정하는 규칙을
> 열거해도 나오지 않는다. **원인을 못 짚었으므로 고치지 않는다.**

### WP7 — 접근성 최소선 ✅ 완료(위젯 범위)

**키보드로 못 닿던 자리.** 시퀀스 목록의 [이름]·[시간] 칸은 눌러서 편집하는
자리인데 `<div onclick>` 이라 탭으로 닿을 수 없었다. `role="button"`·`tabindex="0"`
을 주고 Enter·Space 를 클릭과 같게 처리하는 **위임 리스너**를 위젯 JS 에 뒀다
(목록이 다시 그려져도 살아 있고, 위젯 종류당 한 번만 등록된다).
이제 위젯 25종에 `<div onclick>` 은 **0개**다.

**포커스 표시를 지우기만 한 자리.** `outline: none` 으로 지우고 대신 아무것도
주지 않으면 키보드로 쓰는 사람은 자기가 어디에 있는지 볼 수 없다.

| 대상 | 전 | 후 |
|------|-----|-----|
| `seq-day-btn`(요일) | `outline:none`, 대체 없음 | `:focus-visible` 링 |
| `seq-square-toggle`(스텝 켜기) | `outline:none`, 대체 없음 | `:focus-visible` 링 |
| `aot-cnt-time-trigger`·`aot-cnt-cycles`(타이머) | 테두리 색만 1px 바뀜 | 링 추가(색만으로 알리지 않는다) |
| `aot-notice-textarea` | `outline:none` | **이미 box-shadow 링이 있었다** — 손대지 않음 |

링은 새 토큰 `--aot-focus-outline`(2px solid 브랜드 보조색)로 한 곳에서 정한다.
이미 있던 `.aot-w-tool`(WP2)·`.aot-color-preset`(WP6)의 링도 이 토큰으로 돌렸다 —
그러지 않으면 링 모양이 또 세 벌이 된다. 흰 카드 위 대비 **5.58:1**
(WCAG 2.4.11 은 3:1 을 요구한다).

**이름 없는 컨트롤.** 실제 화면의 위젯 본문에서 접근 이름이 없는 컨트롤을
찾았다(글자가 보이는 버튼은 그 글자가 곧 이름이므로 제외):

| 위젯 | 대상 | 조치 |
|------|------|------|
| `AoT_output_pwm` | 듀티 슬라이더 | `aria-label="Duty Cycle"` |
| `AoT_output_value` | 값 슬라이더 | `aria-label="Value"` |
| `widget_trigger_sequence` | 스텝 켜기 체크박스 | `aria-label="Enabled"` |

슬라이더는 눈에 보이는 라벨이 아예 없는 자리라 `aria-label` 이 유일한 이름이다.
**문구는 셋 다 기존 msgid** 라 번역이 이미 22개 언어에 있다.

산출물: `aot-theme-variables.css` · `aot-base.css` · `aot-modal-modern.css` ·
위젯 4개(`widget_trigger_sequence` · `AoT_timer` · `AoT_output_pwm` · `AoT_output_value`)

**검증**: 포커스 토큰이 실제로 `2px solid rgb(94,107,100)` / offset 1px 로 풀리는
것을 브라우저에서 확인. 시퀀스 위젯 JS 는 파이썬 문자열을 평가한 뒤
`node --check` 로 구문 확인. 위젯 본문의 이름 없는 컨트롤을 실제 DOM 에서
다시 세어 남은 것이 벤더 마크업뿐임을 확인.

**남긴 것**

- **`AoT_graph` 의 기간 선택기** — 이름 없는 `<select>` 와 날짜 입력 두 개가
  Highcharts 가 만든 마크업이다. 위젯 파일이 아니라 Highcharts 의 접근성 설정
  (`rangeSelector`/`accessibility` 모듈)으로 다뤄야 한다.
- **지도 도구 버튼의 이름표** — `aot-map-widget-vector.js` 가 누를 때마다 `title`
  을 다시 쓰기 때문에 템플릿에서 `aria-label` 을 주면 값이 어긋난다(WP2 기록).
  그 JS 와 번들 재빌드가 함께 필요하다 → WP8.
- 이번 작업은 **위젯 범위**다. 화면 전체의 키보드 순회·랜드마크·대비 감사는
  별개 작업이다.

### WP8 — 되돌아가지 않게 ✅ 완료

**회귀 가드** — `aot/tests/test_widget_ui_conventions.py` (검사 13개).
앱/DB 없이 소스 정적 분석만으로 돈다(기존 `test_aot_map_options_forwarding.py`
와 같은 방식). 지키는 것은 **실제로 화면이 어긋났던 것들**뿐이다:

| 검사 | 막는 것 |
|------|---------|
| 제목 span 직접 그리기 | 위젯마다 제목 크기가 갈리는 것 |
| 리터럴 글자 크기(위젯 py **+ 위젯 CSS**) | 사다리 밖 크기가 새로 생기는 것 |
| 컨트롤 높이 리터럴 | 32px 아닌 버튼이 새로 생기는 것 |
| 크기 토큰 중복 정의(5개) | 뒤 파일이 덮어써 앞의 값이 죽는 것 |
| 설정 UI 중복 필드 | 같은 `name` 이 둘이라 뒤엣것이 저장 안 되는 것 |
| 설정 UI 부트스트랩 격자 | 모달 안에서 행 모양이 갈리는 것 |
| 키보드로 못 닿는 클릭 대상 | `<div onclick>` 이 새로 생기는 것 |
| 전역 CSS 재링크 · 가드 없는 중복 링크 | 같은 파일이 head 에 여러 번 내려가는 것 |

**가드가 곧바로 잡아낸 것들** — 앞선 WP 들이 놓친 것을 이 검사가 찾았다:

- 리터럴 글자 크기 **12곳**(`AoT_PID` 2 · `AoT_timer` 2 · `widget_notice` 8).
  사다리로 옮겼다 — 1rem·1.5rem 은 값이 같고, 0.85/0.9rem 은 sm(0.875)로,
  0.7/0.72rem 은 2xs 로, 0.76rem 은 xs 로 (모두 0.5px 이내).
- 키보드로 못 닿는 조작 대상 **6곳**을 더 찾았다. WP7 의 한 줄 grep 은
  한 줄짜리만 잡았는데, 여러 줄에 걸친 것들이 남아 있었다:
  `AoT_advice` 의 [새로 고침]·[AI 에게 알려주기]·[취소](글자처럼 보이는 `<span onclick>`)와
  `widget_trigger_sequence` 의 정보 카드 3개(시작·종료·주기).
  advice 쪽은 `<button>` 으로 바꾸고 브라우저 기본 버튼 껍데기를 벗겼다.

**중복 로드 정리.** `aot-toggle.css` 는 layout.html 이 이미 모든 페이지에서
싣는데 위젯 6곳이 또 걸고 있었다(한 대시보드 head 에 4번). 그중
`widget_function_status` 는 그것을 **본문**에 걸어서 위젯 인스턴스마다 한 번씩
더 내려갔다. 전부 지웠다. 여러 위젯이 함께 쓰는 나머지 셋
(`aot-sensor-label` · `aot-facility-widget` · `aot-time-wheel`)은
`dashboard_dict` 가드로 한 번만 걸리게 했다(`highstock` 이 예전부터 쓰던 방식).
렌더 검증: 위젯이 거는 CSS가 **전부 1회씩**.

**가드 범위 확장과 예외 규칙** (2026-09-06 후속). 처음 만든 검사는
`aot/widgets/*.py` 안의 CSS 만 봤다. 그런데 위젯의 화면은 파이썬 파일과
`static/css/widget/*.css` 에 **반씩 나뉘어** 있어서, 한쪽만 지키면 다른 쪽으로
샌다. 실제로 병합 후 실측에서 본문 글자 크기가 12가지로 나왔고 그중 셋이
그 디렉터리에서 왔다.

범위를 넓히면서 규칙도 정확하게 다듬었다:

- **절대 크기(px·rem)만** 본다. `em` 은 "사다리에서 고르는 크기" 가 아니라
  **담는 상자를 따라가는 장치**다. `aot-sensor-label.css` 는 팝업 껍데기 하나에
  기준을 박고 안쪽을 전부 `em` 으로 두어, 기준 하나만 바꾸면 팝업 셋의 글자가
  비율을 유지한 채 함께 커진다 — 그것을 전역 rem 으로 끌어오면 되먹임이
  끊긴다(같은 파일 주석에 그렇게 했다가 되돌린 기록이 있다).
  그래서 **체인의 뿌리만** 본다. 실측으로 확인: `.aot-act-val`(0.923em)과
  `.aot-ov-card-title`(1.05em)의 뿌리가 둘 다 14px(`--aot-font-size-sm`)이다.
- **벗어나야 하면 이유를 적는다** — `/* 사다리 예외: <이유> */`.
  열 글자 미만이거나 비어 있으면 그대로 막힌다(네 가지 경우로 역검증했다:
  리터럴 추가·빈 예외·짧은 이유는 실패, 제대로 된 이유는 통과).

그 결과 위젯 CSS 19곳 중 **16곳을 토큰으로** 옮겼고(11곳은 값이 같고 7곳은
0.8px 이내), 남은 셋에 이유를 적었다 — 전부 **도형 안에 갇힌 글자**다:
지도 배지 숫자(9px, 원 밖으로 넘침) · 시설 카드 모서리 힌트 칩(9px, 아래 줄과
겹침) · 끌기 손잡이 아이콘 글리프(13px, 옆 제목보다 커 보임).

> 렌더되는 크기의 **가짓수 자체는 줄지 않았다**(12가지 그대로). 남은 소수점
> 값들은 벤더 마크업(MapLibre 축척 10px · Highcharts 눈금 11·13.2px),
> 게이지 크기에 비례하는 SVG(15px), 그리고 사다리 뿌리 위의 `em` 가지
> (12.9·14.7px)다. 바뀐 것은 **고르는 방식**이지 픽셀 히스토그램이 아니다.

**작성 규약 문서** — [widget-conventions.md](widget-conventions.md).
"새 위젯은 이 다섯 가지만 지키면 된다" + 테스트가 못 잡는 것들
(빈 값 표현 · 색 토큰 · SVG `fill` · Highcharts 색 · 포커스 표시 ·
접근 이름 · 문구 재사용 · 모달 본문의 `<script>` 가 실행되지 않는 것).

**남긴 것 — 번들 재빌드가 필요한 두 가지**

`app/dashboard.js` 나 지도 위젯 JS 를 고치려면 `npm ci` 후
`npm run build:bundles` 가 필요하고, 그러면 **내 변경과 무관한 다른 소스의
미빌드분까지 함께 산출물에 들어간다.** 그 책임을 이 작업에서 지지 않는다:

- 색 칩의 위임 리스너(WP6c) — 지금은 인라인 `onclick`.
- 지도 도구 버튼의 `aria-label`(WP2/WP7) — 그 JS 가 `title` 을 다시 쓴다.

**아직 사다리가 없는 것**

- **타일·카드 모서리.** 위젯 CSS 에 8px 12곳 · 12px 3곳 · 6px 3곳 · 5px · 4px.
  버튼 사다리로는 담을 수 없다(시퀀스 요일 타일이 알약이 되면 "한 주"로
  안 읽힌다). 규약 문서에 "가까운 기존 값을 따르고 이유를 적으라" 고만 해 뒀다.
- **알약 버튼 좌우 여백** — 정본 14px vs 센서라벨 계열 12px.
- **`aot-pill-btn-sm`** — 10곳 넘게 쓰이는데 CSS 정의가 없다(WP3 기록).

## 3. 순서와 우선순위

WP0 → WP1 → WP2 는 **순서 의존**이었다(스케일 → 셸 → 제목줄).
2026-09-06 에 WP0~WP8 을 순서대로 시행했다. 각 절 끝의 "남긴 것" 이 다음 할 일이다.

| 순 | WP | 효과 | 위험 | 비고 |
|----|-----|------|------|------|
| ✅ | **WP0** 타입 스케일 | 매우 큼 | 중 | 완료 — 9단 → 6단, 이름 충돌 해소 |
| ✅ | **WP1** 셸 | 큼 | 낮 | 완료 — overflow 정책만 WP5 로 |
| ✅ | **WP2** 제목줄 | 큼 | 낮 | 완료 — 제목 span 21종 → 셸 1곳 |
| ✅ | **WP4** 색 정합 | 중 | 낮 | 완료 — 대비 2건 수정, 선택상자 1건 미해결 |
| ✅ | **WP6** 설정 UI | 중 | 낮 | 완료 — 중복 필드 버그 1건 함께 수정 |
| ✅ | **WP3** 기하 | 중 | 중 | 완료 — 토큰이 실제 값과 어긋나던 것부터 |
| ✅ | **WP5** 상태 표현 | 중 | 중 | 완료 — overflow 는 이미 있었고, 스크롤바가 문제였다 |
| ✅ | **WP7** 접근성 | 중 | 낮 | 완료 — 지도 도구 이름표만 WP8 로 |
| ✅ | **WP8** 재발 방지 | 장기 | 낮 | 완료 — 검사 13개가 잡아낸 18곳도 함께 수정 |

---

## 4. 결정

1. ✅ **`font_em_name`(Font Size 노브) — 제거**(2026-09-06, 사용자 결정). WP6(a)에서 시행.
2. ✅ **`widget_gauge_solid` 밴드 4단 → 5단** — **사용자 저장값이 있으면 그대로,
   없을 때만 5단 기본값**(2026-09-06, 사용자 결정). WP4 에서 시행·검증.
3. ✅ **`--aot-font-size-lg`(1.05rem) 흡수처 — `--aot-fs-value-sm`(1.125rem) 로 올림**.
   사용처가 6곳(모달 2 · 시설 2 · 센서라벨 카드 2)뿐이고, 그 6곳은 모달·카드 텍스트라
   +1.2px 이 레이아웃을 흔들지 않는다. 지도 위 라벨은 이 토큰을 쓰지 않는다(별도 px 계열).

### 남은 확인거리 — 시행분에서 생긴 것

- **`overflow` 정책**(WP1 보류분) — 카드 밖으로 나가야 하는 팝업이 실재해
  일괄 `hidden` 을 넣지 않았다. WP5 에서 위젯별로 정한다.
- **지도 도구 이름표**(WP2 보류분) — `aot-map-widget-vector.js` 가 `title` 을 다시 쓰므로
  `aria-label` 일원화는 번들 재빌드와 함께 WP7 에서.

---

## 5. 이 계획이 하지 않는 것

- 위젯 **기능** 변경 없음. 배치·데이터·제어 로직은 손대지 않는다.
- 위젯 **추가/삭제** 없음.
- `AoT_map` / `AoT_facility` 의 캔버스 내부(MapLibre·three.js 렌더링) 스타일은 범위 밖.
  카드 껍데기와 컨트롤만 다룬다.
- `AoT_weather_fcst_announcement` 가 기상청(KMA) 한국어 응답값(`"맑음"`, `"구름많음"`)에
  직접 의존하는 문제는 **UI 가 아니라 데이터 소스 범위**라 별건으로 남긴다.
