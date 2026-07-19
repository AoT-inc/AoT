# AoT z-index 체계 가이드

UI를 올릴 때 "무슨 값을 줘야 위에 뜨나"를 매번 추측하지 않도록, z-index를
**단일 시맨틱 사다리**로 관리한다. 값의 단일 소스는
`aot/aot_flask/static/css/aot-theme-variables.css` §1.13 이며, 모든 전역 레이어는
아래 `--aot-z-*` 토큰만 참조한다.

## 핵심 원칙

1. **먼저 물어라: "이 요소가 자기 컨테이너를 탈출해 화면 최상위로 떠야 하는가?"**
   - **아니오** → 전역 토큰을 쓰지 마라. 부모의 스택 컨텍스트 안에서 로컬 소정수
     (`1`~`99`)로 충분하다. 예: 지도 pane, gridstack 리사이즈 핸들, 위젯 내부 배지,
     카드 위 겹침.
   - **예** → 아래 사다리에서 **역할에 맞는 가장 낮은 토큰**을 고른다.
2. **하드코딩 숫자 금지.** 새 z-index는 반드시 `var(--aot-z-…)` 로 쓴다.
3. **극단값 금지.** `9999`, `99999`, `2147483647`, `50000` 같은 "일단 최대로" 값은
   스택 전쟁을 만든다. 사다리 최상단(`--aot-z-tooltip`, `7000`)보다 높은 값은 없다.
4. **`!important` 는 벤더(부트스트랩/leaflet/datatables) 규칙을 이길 때만.** 우리 토큰
   끼리는 값 차이로 순서가 정해지므로 불필요하다.

## 사다리 (전역 토큰)

| 토큰 | 값 | 용도 | 대표 사용처 |
|------|----|------|-------------|
| `--aot-z-base` | 0 | 기본 흐름 콘텐츠 | 일반 카드/위젯 본문 |
| `--aot-z-raised` | 10 | 살짝 띄운 콘텐츠·배지 | 겹치는 라벨, 상태 배지 |
| `--aot-z-sticky` | 100 | sticky 서브헤더, 페이지 내 고정 바 | `#dash-sticky`, widget-add-bar |
| `--aot-z-map-overlay` | 400 | 지도/캔버스 위 떠있는 컨트롤·패널 | 지도 툴 버튼, 커스텀 컨트롤 |
| `--aot-z-dropdown` | 1000 | 메뉴·selectpicker·자동완성 | bootstrap-select, 컬러피커 |
| `--aot-z-drawer` | 1500 | 슬라이드 사이드바·드로어 | geo 헤더/사이드 |
| `--aot-z-fixed-panel` | 2000 | 고정 떠있는 툴 팔레트 | geo 디자인 툴 패널 |
| `--aot-z-navbar` | 3000 | 상단 내비게이션 바 | `.navbar.main-navbar` |
| `--aot-z-overlay` | 4000 | 전체화면 오버레이 | 지도 풀스크린, 노트 갤러리, 로딩 |
| `--aot-z-modal-backdrop` | 5000 | 모달 배경 | `.modal-backdrop` |
| `--aot-z-modal` | 5100 | 다이얼로그 | `.modal`, 센서값 모달 |
| `--aot-z-modal-nested` | 5200 | 모달 안에서 밖으로 튀어나오는 드롭다운/select | 모달 내 selectpicker, gridstack fs |
| `--aot-z-popover` | 5300 | 모달 콘텐츠에 앵커된 팝오버 | 모달 내 팝오버 |
| `--aot-z-confirm-backdrop` | 5900 | 전역 confirm 배경(일반 모달 위) | `#aotConfirmBackdrop` |
| `--aot-z-confirm` | 6000 | 전역 confirm 다이얼로그 | `#aotConfirmModal` |
| `--aot-z-toast` | 6500 | 토스트·알림 (모달 위) | `#toast-container` |
| `--aot-z-tooltip` | 7000 | 툴팁 — 항상 최상위 | `.tooltip` |

값 사이 간격이 넓은 것은 의도적이다. 같은 계층에서 미세하게 순서를 조정해야 하면
`calc(var(--aot-z-modal) + 1)` 처럼 토큰 기준 상대값을 쓴다(하드코딩 금지).

## 지도-로컬 스케일 (0~99)

지도(leaflet/maplibre) 위젯은 자체 스택 컨텍스트를 만든다. 그 **안쪽** 레이어
(타일/라벨/툴/팝업)는 전역 토큰이 아니라 지도-로컬 소정수를 쓴다. 지도 컨테이너
전체가 화면에 뜨는 순위는 위젯이 배치된 위치(대개 `--aot-z-base`)로 정해지고,
풀스크린 시에만 `--aot-z-overlay` 로 승격한다.

- 지도 내부 레이어: `5`(라벨 최하) → `10` → `20`(툴) → `25` → `30` → `40`(패널) → `60`
- 로컬 토큰(`--z-map-popup`, `--z-map-popup-act`, `--z-facility-panel`,
  `--advice-panel-z-index`)도 이 0~99 범위를 유지한다.
- **규칙: 지도 UI(툴/패널/팝업)는 100을 넘지 않는다.** 100 이상이 필요하면 그것은
  지도 밖으로 떠야 하는 UI이므로 전역 사다리를 써야 한다는 신호다.
- **예외 — leaflet 마커 레이어:** leaflet은 마커마다 위도 기반으로 z-index를 수백
  단위로 자동 계산한다. 따라서 마커 hover/active 상태(예 `AoT_map` 위젯의
  `.aot-vector-marker:hover`, `.device-on` = `z-index:1000`)는 같은 markerPane 안의
  다른 마커를 이기기 위해 ~1000을 쓴다. 이 값은 위젯의 `isolation:isolate` 스택
  컨텍스트에 갇혀 밖으로 새지 않으므로(대시보드 다른 위젯과 무관) 전역 토큰이 아니라
  **마커-로컬 값**으로 둔다. 그 외 지도 UI에는 이 예외를 적용하지 말 것.

## 신규 레이어 추가 절차

1. 기존 토큰으로 표현 가능한가? 가능하면 그것을 재사용한다(새 토큰 만들지 말 것).
2. 정말 새 계층이 필요하면 **먼저** §1.13에 토큰을 추가하고(인접 계층 사이 여유 간격),
   이 표를 갱신한 뒤 CSS/HTML/JS에서 `var()`로 참조한다.
3. 리뷰 체크: 하드코딩 숫자·극단값·불필요한 `!important` 가 없는가.

## 자동 점검

정적 참조/잔존 하드코딩 점검:

```bash
# 정적 참조 무결성
python3 aot/scripts/check_static_refs.py

# AoT 자체 파일에 4자리 이상 하드코딩 z-index 잔존 여부(벤더 제외 → 0건이어야 함)
grep -rn "z-index" aot/aot_flask/static/css aot/aot_flask/templates aot/widgets \
  --include="*.css" --include="*.html" --include="*.py" \
  | grep -viE "bootstrap|datatables|daterangepicker|toastr|bootstrap-4-themes|node_modules" \
  | grep -E "z-index:[^;]*[0-9]{4,}"
```
