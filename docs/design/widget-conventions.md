# 새 위젯을 만들 때 지킬 다섯 가지

위젯은 필요할 때마다 하나씩 만들어진다. 그래서 그때그때의 판단이 쌓여
톤앤매너가 갈라지고, 몇 달 뒤에 누군가 그것을 다시 맞춘다
(그 기록: [widget-uiux-unification-plan.md](widget-uiux-unification-plan.md)).

아래 다섯 가지는 취향이 아니라 **실제로 화면이 어긋났던 것들**이다.
`aot/tests/test_widget_ui_conventions.py` 가 지킨다 — 어기면 테스트가 깨진다.

---

## 1. 이름은 셸이 그린다

```python
'widget_dashboard_title_bar': """""",   # 대개는 비워 둔다
```

`dashboard_entry.html` 이 `<span class="aot-w-title">{{each_widget.name}}</span>` 를
항상 그린다. 위젯 조각에는 **이름 옆에 붙는 부가물만** 넣는다.

```python
# 상태 배지
'widget_dashboard_title_bar': """
  <span class="aot-w-caption" id="state-{{each_widget.unique_id}}"></span>
""",
```

도구 버튼은 `.aot-w-tool` 하나를 쓴다(24×24 최소 크기·포커스 표시가 딸려 온다).

> 왜: 예전에는 21종이 각자 이름 span 을 만들었다. 클래스를 빠뜨린 위젯의 제목만
> 13.6px/400 으로, 나머지 13개는 14px/600 으로 렌더됐다. 한 화면 안에서.

## 2. 글자 크기는 사다리에서 고른다

```css
font-size: var(--aot-font-size-sm);   /* 14px — 기준 */
```

| 토큰 | 값 | 쓰임 |
|------|-----|------|
| `--aot-font-size-2xs` | 0.7rem (11.2px) | 조밀한 상세 라벨 |
| `--aot-font-size-xs` | 0.75rem (12px) | 캡션·타임스탬프·배지 |
| `--aot-font-size-sm` | 0.875rem (14px) | **기준** — 제목·라벨·단위·본문 |
| `--aot-font-size-base` | 1rem (16px) | 본문 강조 |
| `--aot-font-size-lg` | 1.125rem (18px) | 값 한 단 아래 |
| `--aot-font-size-xl` | 1.5rem (24px) | 측정값·게이지 중앙 |

역할 이름(`--aot-fs-title`·`--aot-fs-body`·`--aot-fs-value` …)은 위 단들을
가리키기만 한다. 역할 이름 쪽이 읽기 쉬우면 그쪽을 쓴다.

검사 범위는 **위젯 파이썬 파일 + `static/css/widget/*.css`** 둘 다다.
위젯의 화면이 반씩 나뉘어 있어서, 한쪽만 지키면 다른 쪽으로 샌다.

### `em` 은 왜 봐주는가

`em` 은 "사다리에서 고르는 크기" 가 아니라 **담는 상자를 따라가는 장치**다.

`aot-sensor-label.css` 가 그 예다. 팝업 껍데기 하나에 기준을 박고
(데스크탑 `--aot-font-size-sm`, 480px 이하 `--aot-font-size-base`) 안쪽은 전부
`em` 이라, **기준 하나만 바꾸면** 구역·시설·사이트 목록 팝업의 글자가 비율을
유지한 채 함께 커진다. 그 값들을 전역 rem 사다리로 끌어오면 그 되먹임이
끊긴다 — 실제로 그렇게 했다가 "화면마다 비율이 어긋난다" 로 되돌린 기록이
같은 파일 주석에 남아 있다.

그래서 검사는 **체인의 뿌리**(px·rem)만 본다. 뿌리가 사다리에 있으면 가지는
저절로 사다리 위에 선다. 실측으로도 그렇다 — `.aot-act-val`(0.923em)과
`.aot-ov-card-title`(1.05em)은 둘 다 14px 뿌리 위에서 12.9px·14.7px 로 그려진다.

### 벗어나야 할 때 — 이유를 적는다

사다리를 못 쓰는 자리가 실제로 있다. 그럴 땐 **왜인지 적으면 통과**한다:

```css
.aot-link-badge-num {
  /* 사다리 예외: 고정 크기 원형 배지 안에 그리는 SVG 숫자다. 사다리 최소단
     (2xs = 11.2px)이면 원 밖으로 넘친다 — 원을 키우면 지도 위 마커가 커진다.
     본문 글자가 아니라 도형에 갇힌 글자라 도형이 크기를 정한다. */
  font-size: 9px;
}
```

`사다리 예외:` 뒤에 열 글자 이상을 적어야 한다. 빈 표시나 "짧음" 같은 말은
검사가 그대로 막는다(그렇게 동작하는지 테스트로 확인해 두었다).

지금 걸려 있는 예외는 셋뿐이고 **전부 도형 안에 갇힌 글자**다 — 지도 배지
숫자, 시설 카드 모서리의 힌트 칩, 끌기 손잡이 아이콘 글리프.
"본문 글자인데 사다리가 마음에 안 든다" 는 예외 사유가 아니다.

> 왜: 예전에는 사다리가 두 벌이었고 같은 이름이 다른 값을 가리켰다. 3단을
> 선언해 놓고 화면에는 여덟 가지 크기가 나왔다.

## 3. 컨트롤 치수도 사다리에서 고른다

```css
height: var(--aot-btn-height);              /* 32px */
border-radius: var(--aot-btn-pill-radius);  /* 알약 */
padding: 0 var(--aot-btn-padding-x);        /* 12px */
```

글자가 두 줄이 될 수 있는 버튼은 `height` 대신 `min-height` + `inline-flex`
가운데 정렬을 쓴다 — 고정 높이는 좁은 폭에서 글자를 상자 밖으로 밀어낸다.

**아직 사다리가 없는 것**: 타일·카드의 모서리. 위젯 CSS 에 8px·12px·6px·5px·4px
가 흩어져 있다. 새로 정하기 전까지는 가까운 기존 값을 따르고, 왜 그 값인지
주석에 적는다.

## 4. 크기 토큰은 한 곳에서만 정의한다

`aot-theme-variables.css` 가 정본이다. 테마 파일이나 페이지 CSS 에서 같은
이름을 다시 정의하지 않는다.

> 왜: `--aot-btn-height` 는 36px 이라고 적혀 있었지만 뒤에 로드되는 테마 두 곳이
> 32px 로 덮어써서 **36px 은 한 번도 화면에 나온 적이 없었다.** `--aot-btn-font-size`
> 는 한 곳이 자기 자신을 참조하는 무효값으로 덮고 있었다.

## 5. 설정 UI 는 표준 옵션 행을 쓴다

```html
<div class="aot-modal-option-row">
  <label class="aot-modal-option-label" for="...">{{_('...')}}</label>
  <div class="aot-modal-option-control">
    <input class="form-control aot-modern-input" ...>
  </div>
</div>
```

- 부트스트랩 `form-row`/`col-auto`/`control-label` 은 쓰지 않는다.
- **`custom_options` 가 이미 그리는 필드를 위젯이 또 그리지 않는다.** 직접
  그려야 하면 그 옵션을 `type: 'hidden'` 으로 선언해 표준 렌더러가 손을 떼게 한다.
- 옵션이 열 개를 넘으면 `type: 'header'` 로 묶고, 자주 안 쓰는 묶음은
  `collapse_start` / `collapse_end` 로 접는다.
- 색을 고르는 칸은 `pages/form_options/Color_Presets.html` 을 include 한다.

> 왜: 풍향 위젯이 같은 필드를 두 번 그리고 있었다. 같은 `name` 의 입력이 둘이면
> 저장 때 앞의 것만 반영된다 — 뒤엣것을 고친 사용자는 값이 안 바뀌는 것을 본다.

---

## 그 밖에 — 테스트가 잡지 못하는 것들

**값이 없을 때 빈 칸을 남기지 않는다.** 빈 칸은 "값이 0" 인지 "센서가 죽었" 는지
"아직 안 왔" 는지를 구분해 주지 않는다. 값 자리에는 `—`, 문장을 넣을 자리가
있으면 `_('NO DATA')`. 더 나쁜 것은 **없는 값을 있는 것처럼 그리는 것**이다 —
풍향 게이지가 값이 없을 때 바늘을 0°(북)로 돌려 멀쩡한 측정값처럼 보였다.

**색은 토큰에서.** 측정 구간색은 `utils_theme.get_band_palette()`(사용자 설정이
얹힌다), 차트 시리즈는 `get_graph_series_palette()`. 위젯 파일에 같은 색을 다시
적으면 사용자가 색을 바꿔도 그 위젯만 안 따라온다.

**SVG 글자색은 `fill` 이다.** 텍스트 색 토큰이 자동으로 따라오지 않는다. CSS 의
`fill` 선언은 표현속성보다 세므로 클래스로 정한다. 다크 테마에서 검은 글자가
검은 배경에 묻히는 사고가 여기서 난다.

**Highcharts 는 색을 SVG 표현속성으로 넣는다.** `var(--…)` 가 풀리지 않으므로
JS 에서 `getComputedStyle` 로 한 번 읽어 문자열로 넘긴다(`aotThemeColor()`).

**짚는 자리를 넓힐 때는 바깥으로 넓힌다.** 카드 오른쪽 끝에 매달린 도구줄
(`.widget-map-controls` 등)에서 버튼 상자를 24px 로 키우면, 기준선은 그대로인 채
아이콘만 안쪽·아래로 밀린다 — 기준선은 예전의 맨몸 아이콘 크기에 맞춰 잡힌
값이기 때문이다. 늘어난 만큼 음수 마진으로 되돌려 배치에는 아이콘 크기만
내놓는다(지도 위젯 잠금 아이콘이 실제로 14.3px 왼쪽·3.7px 아래로 밀렸다).

**`outline: none` 은 혼자 쓰지 않는다.** 지웠으면 `--aot-focus-outline` 으로 다시
그려 준다. 키보드로 쓰는 사람은 그것 말고 자기 위치를 알 방법이 없다.

**아이콘만 있는 조작기에는 이름을 준다.** 슬라이더·체크박스처럼 눈에 보이는
라벨이 없는 자리는 `aria-label` 이 유일한 이름이다. 글자가 보이는 버튼은
그 글자가 곧 이름이라 따로 줄 필요가 없다.

**문구는 새로 만들기 전에 찾아본다.** 22개 언어로 나가는 앱이다. `NO DATA`·
`Loading...`·`Value` 같은 것은 이미 번역돼 있다. 같은 뜻의 msgid 를 새로 만들면
그만큼 번역되지 않은 문구가 는다.

**계산된 스타일을 잴 때 트랜지션을 먼저 끝낸다.** 브라우저가 화면을 그리지
않는 동안(패널이 숨겨졌거나 탭이 뒤에 있을 때)에는 CSS 트랜지션이
`playState: "running"` 인 채 `currentTime: 0` 으로 멈춘다 — 그러면
`getComputedStyle` 이 **전환 전 값**을 돌려준다. 어떤 CSS 규칙과도 맞지 않는
색이 나오면 이것을 의심할 것:

```js
document.getAnimations().filter(a => a.playState === 'running').forEach(a => a.finish());
```

실제로 이 함정에 한 번 걸렸다. `AoT_plot` 의 구획 선택 상자가 `#999999` 로
읽혀 대비 위반(2.85:1)으로 보고했는데, 그것은 bootstrap-select 의
`.bs-placeholder` **시작색**이었고 0.15초 뒤 `#5E6B64`(5.13:1)로 가는
중간값이었다. 시트를 다 꺼도 색이 안 바뀌고 **같은 마크업의 복제본은 정상색**
이 나오면 CSS 가 아니라 애니메이션이다.

**설정 모달 본문의 `<script>` 는 실행되지 않는다.** 본문이 `<template>` 에 담겼다가
`cloneNode` 로 복제되기 때문이다(`dashboard.js: hydrateLazyModalBodies`).
동작이 필요하면 속성 핸들러를 쓰거나 `app/dashboard.js` 에 넣는다.
