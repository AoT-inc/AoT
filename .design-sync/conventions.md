# AoT 디자인 시스템 — 이 시스템으로 화면을 만드는 법

**AoT 는 서버 렌더(Flask/Jinja) 앱이다. React 컴포넌트 라이브러리가 아니다.**
그래서 이 번들에는 불러 쓸 컴포넌트가 없다 — 대신 **토큰과 클래스**가 있다.
마크업은 직접 쓰고 아래 클래스를 붙인다.

## 설치·감싸기

감쌀 프로바이더는 없다. `styles.css` 하나면 된다. 그 안에 **부트스트랩 4** 가
먼저 들어 있고(AoT CSS 는 그것을 *확장*한다 — 빼면 `.btn`·`.form-control`·
`.modal`·그리드가 통째로 죽는다), 토큰과 AoT 클래스가 그 위에 얹힌다.

본문 글꼴은 **Gothic A1**(Google Fonts). 못 받아도 폴백 스택이 한글을 받친다.
어두운 테마 값은 앱에서 사용자 설정으로 갈아 끼우는데, 여기서는 스위치가 없어
`prefers-color-scheme: dark` 에 걸어 뒀다. 값 자체는 앱과 같다.

## 색 — 반드시 지킬 것

| 쓰임 | 토큰 | 값 |
|---|---|---|
| 브랜드 | `--aot-color-brand-primary` | `#13261B` 딥그린 |
| **버튼·활성** | `--aot-btn-bg-primary` | `#13261B` |
| 보조 버튼 | `--aot-btn-bg-secondary` | `#5E6B64` |
| 성공·경고·위험·정보 | `--aot-color-{success,warning,danger,info}` | `#96C064` `#FEA60B` `#DF5353` `#029ACF` |
| 틴트 배경 | `--aot-tint-{success,warning,danger,info}-bg` | 위 색의 옅은 판 |
| 표면 | `--aot-surface-{card,modal,dropdown,input}` `--aot-surface-body` | `#ffffff` / `#F3F6F5` |
| 테두리 | `--aot-border-neutral` | `#dddddd` |

⚠ **`--aot-color-primary`(`#F2D524`, 노랑)를 버튼이나 액션에 쓰지 말 것.**
이름이 primary 라 헷갈리지만 브랜드 색이 아니다. 채워진 버튼은 딥그린이다.

## 사다리 — 값을 지어내지 말고 여기서 고른다

```
--aot-font-size-2xs .7rem · xs .75rem · sm .875rem(기준) · base 1rem · lg 1.125rem · xl 1.5rem
--aot-radius-xs 4px · sm 8px · md 12px · lg 16px · xl 20px      (알약은 --aot-btn-pill-radius)
--aot-space-1 4px · 2 8px · 3 12px · 4 16px · 5 24px · 6 32px
--aot-gray-950 #111 · 800 #333 · 600 #666 · 500 #888 · 300 #ccc · 200 #eee · 100 #f8f9fa
```

사다리 밖 값은 검사(`aot/tests/test_css_conventions.py`)가 막는다. 그림자는
`--aot-shadow-*`, 겹침 순서는 `--aot-z-*` 를 쓴다.

## 클래스 어휘

| 계열 | 대표 클래스 |
|---|---|
| 버튼 | `.aot-pill-btn` `+ -primary` `-secondary` `-danger` `-sm` (부트스트랩 `.btn` 과 함께) |
| 입력 | `.aot-modern-input` `.aot-modern-select` (`.form-control` 과 함께) |
| 설정 행 | `.aot-modal-option-row` > `.aot-modal-option-label` + `.aot-modal-option-control` |
| 제목 | `.aot-modal-section-title`(구획) `.aot-modal-group-title`(묶음) |
| 안내 상자 | `.aot-notice-box` **기본이 경고 톤**, 변형 `-success` `-danger` `-info` `-plain` (`-warning` 은 없다) |
| 모달 | `.modal.aot-option-modal`(설정용) `.aot-center-modal`(위젯 팝업) |
| 목록 행 | `.aot-entry-item` + `.aot-col-*` |
| 상태 배경 | `.active-background` `.inactive-background` `.pause-background` `.hold-background` `.unknown-background` `.fault-background` |
| 탭 | `.aot-tabs-wrapper` > `.aot-tab-item` |
| 설정 화면 | `.aot-settings-row` `.aot-settings-label` `.aot-settings-control` |

## 이 시스템의 규칙

- **아이콘·이모지를 쓰지 않는다.** 요청이 있을 때만 넣는다.
- **스크롤바는 보이지 않게** 한다(스크롤은 동작하되 막대는 숨김).
- **한 열에는 한 정보만.** 이름 옆에 배지를 이어 붙이지 않는다.
- 새 `!important` 를 붙이지 않는다. 이기려는 상대가 우리 CSS 면 선택자를 고친다.
- 옛 변수 이름(`--text-color-primary`, `--bd-primary` …)은 쓰지 않는다.
  다크에서 값이 갈린다 — 정본 `--aot-*` 만 쓴다.

## 진짜 정의는 파일에 있다

요약보다 원문이 낫다. `tokens/aot-tokens.css`(토큰 정본),
`css/aot-base-ui.css`(공용 컴포넌트), `css/aot-modal-modern.css`(모달·설정 행),
`css/aot-entry-ui.css`(목록 행), `css/aot-settings.css`(설정 화면).

## 예시

```html
<div class="aot-modal-option-row">
  <label class="aot-modal-option-label">이름</label>
  <div class="aot-modal-option-control">
    <input class="form-control aot-modern-input" value="온실 1동">
  </div>
</div>

<div class="aot-notice-box aot-notice-box-info">
  <p>관수는 06:00 에 시작합니다.</p>
</div>

<div style="display:flex; gap:var(--aot-space-2); margin-top:var(--aot-space-4)">
  <button class="btn aot-pill-btn aot-pill-btn-secondary">취소</button>
  <button class="btn btn-primary aot-pill-btn">저장</button>
</div>
```
