# design-sync 메모

## 이 저장소는 표준 모양이 아니다 (2026-09-07)

`/design-sync` 는 **컴파일된 React 컴포넌트(`dist/`)** 를 Claude Design 이
`window.<전역>.*` 로 렌더할 수 있게 옮기는 스킬이다. AoT 는 그 모양이 아니다:

- UI 는 **Jinja 템플릿 438개** + 부트스트랩 4 + 자작 CSS. 서버 렌더다.
- `static/js/dist/*.bundle.js` 54개는 **페이지 스크립트**(IIFE)다 — 내보내는
  컴포넌트 모듈이 아니다.
- React 는 `static/apps/notes-widget` 하나뿐이고 그것도 **앱**이다
  (`NotesDrawer`·`NotesList` … react-query 로 AoT API 를 부른다). 디자인 도구에서
  단독으로 렌더할 부품이 아니다.

컴포넌트를 만들려면 `.aot-*` 클래스 658종을 React 로 **다시 써야** 하는데,
스킬의 원칙("고객이 이미 만든 것을 올린다 — 재구현은 아니다")에 어긋나고
Jinja 정본과 갈라지는 부채가 된다. **그래서 토큰·스타일만 올린다**(사용자 결정).

## 번들 조립 절차

원본: `aot/aot_flask/static/css/`. 손대지 않고 복사만 한다.

| 번들 경로 | 원본 |
|---|---|
| `tokens/aot-tokens.css` | `aot-theme-variables.css` |
| `tokens/theme-light.css` / `theme-dark.css` | `custom-light.css` / `custom-dark.css` |
| `vendor/bootstrap.min.css` | `bootstrap.min.css` |
| `css/aot-theme.css` | `bootstrap-4-themes/aot.css` |
| `css/aot-widget-typography.css` | `widget/aot-widget-typography.css` |
| `css/aot-base-ui.css` 등 10개 | `components/*.css` |
| 나머지 | 같은 이름의 `css/*.css` |

`styles.css` 의 `@import` 순서 = 앱 `<link>` 순서. 바꾸지 말 것.

**뺀 것**: 페이지 전용 CSS(map·dashboard·widget·ai·pages) — 각자의 JS 가 있어야
뜻이 있다. `/custom.css` — 서버가 사용자 색으로 그때그때 만드는 동적 파일.

## 검증 방법

번들을 `static/_dscheck/` 로 복사하고 `probe.html`(버튼·입력·안내상자·제목 +
토큰 덤프)을 열어 브라우저에서 확인했다. 확인된 것: 미로드 CSS 0, 버튼 딥그린
`#13261B`·알약 9999px·Gothic A1, 안내상자 세 톤, 토큰 8종 해석.
**확인이 끝나면 `_dscheck/` 와 `.git/info/exclude` 줄을 지울 것.**

## 규약 문서 검증

`conventions.md` 가 이름을 댄 토큰 31종·클래스 24종을 번들 CSS 에 전부 대조했다.
⚠ 그 과정에서 `.aot-notice-box-warning` 이 **없다**는 것을 잡았다 — 안내 상자는
**기본형이 경고 톤**이고 변형은 `-success` `-danger` `-info` `-plain` 뿐이다.

## 남은 일

- Claude Design 인증이 없어 업로드는 못 했다. `/design-login` 을 대화형
  세션에서 한 번 돌린 뒤 다시 시도하면 된다. 그때 프로젝트를 새로 만들고
  `projectId` 를 `config.json` 에 적는다.
