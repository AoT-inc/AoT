# AoT Widget Style Cleanup Plan

**목표:** `aot/widgets/AoT_*.py` 전 위젯에서 하드코딩된 색상·폰트·여백을
전역 CSS 토큰(`aot-theme-variables.css`) 및 공용 클래스(`aot-widget-typography.css`,
`aot-base.css`)로 교체한다.

---

## 현황 요약

### 공용 인프라 (이미 존재)

| 파일 | 역할 |
|------|------|
| `static/css/aot-theme-variables.css` | 전역 CSS 토큰 (색상·여백·타이포·그림자 등) |
| `static/css/widget/aot-widget-typography.css` | `.aot-w-title` · `.aot-w-label` · `.aot-w-value` · `.aot-w-unit` · `.aot-w-caption` · `.aot-w-body` |
| `static/css/aot-base.css` | `.active-background` · `.inactive-background` · `.pause-background` · `.hold-background` |
| `static/css/components/aot-base-ui.css` | `.frame-aot` 입력/버튼 스타일 |

---

## 위젯별 문제 & 교체 목록

### 1. AoT_advice.py — 우선순위: 중

**문제:**
- `.aot-advice--*` 로컬 토큰(`--aot-bg`, `--aot-text`, `--aot-border`)이 다크 테마
  전용 하드코딩 hex를 사용 → 라이트 테마에서도 검은 배경 고정됨
- `color: #ddd`, `color: #888`, `color: #bbb` — 전역 토큰 미사용

**교체 계획:**
```
color: #ddd   →  color: var(--aot-color-text-tertiary)
color: #888   →  color: var(--text-medium-gray)
color: #bbb   →  color: var(--aot-color-text-secondary)
padding: 8px 10px  →  padding: var(--aot-space-2) var(--aot-space-3)
```

`.aot-advice--*` variant 색상은 `aot-theme-variables.css`에
`--aot-advice-*` 토큰으로 신규 등록 후 참조.
다크 테마 override는 `custom-dark.css`에 위임.

---

### 2. AoT_camera.py — 우선순위: 낮

**문제:**
- `background:#000` — 테마 변수에 `--camera-preview-bg: #1a1a1a` 이미 존재
- `color:#fff` → `--text-color-tertiary`
- `font-size:0.8em` → `--aot-fs-sm`

**교체 계획:**
```html
<!-- 현재 -->
<div style="background:#000; ...">
<div style="color:#fff; font-size:0.8em; ...">

<!-- 변경 후 -->
<div style="background:var(--camera-preview-bg); ...">
<div style="color:var(--text-color-tertiary); font-size:var(--aot-fs-sm); ...">
```

---

### 3. AoT_controller.py — 우선순위: 낮

**현황:** `.frame-aot`, `.active-background`, `.inactive-background` CSS 클래스
정상 사용 중. `<style>` 블록 내용 미미.

**추가 확인:** `<style>` 블록 세부 내용 검토 후 필요 시 토큰 교체.

---

### 4. AoT_facility.py — 우선순위: 낮

**현황:** 대부분 CSS 변수 사용 중. 큰 문제 없음.

**소규모 정리:**
- `style="max-width:280px"` → 의미있는 경우 CSS 변수나 클래스로 분리 검토
  (레이아웃 제약 값은 인라인도 허용)

---

### 5. AoT_gauge_angular.py — 우선순위: 중

**문제:**
Python `color_list`가 `--aot-band-*` 토큰과 동일한 hex 값을 중복 정의.

```python
# 현재 (Python hardcode)
color_list = ["#2DB4FF", "#54BCC1", "#64C567", "#FEAE5F", "#CF5C58"]
```

**교체 계획:**
Python에서 CSS 변수를 직접 참조할 수 없으므로, `base_widget.py` 또는
별도 `constants.py`에 **단일 팔레트 상수** 정의:

```python
# aot/widgets/constants.py (신규)
BAND_PALETTE = ["#2DB4FF", "#54BCC1", "#64C567", "#FEAE5F", "#CF5C58"]
```

`AoT_gauge_angular.py`, `AoT_wind_angular.py`에서 import하여 사용.
`aot-theme-variables.css`의 `--aot-band-*` 주석에 Python 상수 위치 명기.

---

### 6. AoT_graph.py — 우선순위: 낮

**현황:** 커스텀 컬러 시스템(사용자 지정 색상)이 별도 로직으로 운영됨.
레이아웃 인라인 스타일(`position:absolute; left:0; top:0; ...`)은 Highcharts
컨테이너 요구사항으로 유지 필요.

**정리 불필요** (레이아웃 인라인은 정당 사유 있음).

---

### 7. AoT_map.py — 우선순위: 높

**문제:** `<style>` 블록 두 곳에 하드코딩 hex 다수.

```css
/* 현재 하드코딩 */
border-color: #ffffff
fill: #333
fill: #ccc
background-color: rgba(153, 90, 255, 0.2)
border: 2px solid #fff
color: #fff
```

**교체 계획:**
`aot-theme-variables.css`에 맵 전용 토큰 추가:
```css
/* Section: GIS / Map */
--aot-map-compass-dark: #333333;
--aot-map-compass-light: #cccccc;
--aot-map-device-bg: rgba(153, 90, 255, 0.2);
--aot-map-device-bg-active: rgba(153, 90, 255, 0.8);
--aot-map-device-border: var(--aot-color-text-tertiary);
```

map `<style>` 블록에서 신규 토큰 참조.
`#ffffff`/`#fff` → `var(--aot-color-text-tertiary)` 또는 `var(--aot-surface-card)`.

---

### 8. AoT_timer.py — 우선순위: 중

**문제:**
- `font-size: 0.9em` → `var(--aot-fs-md)`
- `padding: 4px 0 6px 0` → `var(--aot-space-1) 0 6px 0` (부분 적용)

**현황 양호 항목 (유지):**
- `color: var(--aot-text-main, #333)` ✓
- `border: 1px solid var(--border-neutral, #d7d3c4)` ✓
- `background: var(--aot-input-bg, #fff)` ✓
- `var(--color-zone-mode, #2ecc71)` ✓

---

### 9. AoT_weather_fcst_announcement.py — 우선순위: 높

**문제:** JS로 동적 생성되는 HTML 안에 인라인 `style=` 속성 다수.

```javascript
// 현재 JS 내 인라인 스타일
'<span class="aot-w-value" style="font-weight:var(--aot-fw-semibold)">'
'<div class="aot-w-body" style="display:flex;justify-content:space-between;width:100%">'
'<td style="width:33%;padding:0 8px;vertical-align:bottom">'
```

**교체 계획:**
공용 레이아웃 클래스를 `aot-widget-typography.css`에 추가:
```css
.aot-w-row-between { display:flex; justify-content:space-between; width:100%; }
.aot-w-col-third   { width:33%; padding:0 var(--aot-space-2); vertical-align:bottom; }
```

JS 문자열에서 `style=` 제거 → 클래스명만 사용:
```javascript
'<div class="aot-w-body aot-w-row-between">'
'<td class="aot-w-col-third">'
```

`font-weight` 인라인은 `.aot-w-value`가 이미 `font-weight: var(--aot-fw-bold)` 보유
→ 인라인 `font-weight:var(--aot-fw-semibold)` 제거.

---

### 10. AoT_wind_angular.py — 우선순위: 낮

**문제:** Python 기본값 hex 하드코딩.

```python
# 현재
'border_color':    '#D5D5D5'
'direction_color': '#F4D624'
```

**교체 계획:**
5번(AoT_gauge_angular)과 동일하게 `constants.py` 팔레트 활용:
```python
from aot.widgets.constants import BAND_PALETTE
DEFAULT_BORDER_COLOR    = "#D5D5D5"   # --aot-border-neutral 계열
DEFAULT_DIRECTION_COLOR = "#F4D624"   # --aot-color-primary 계열
```

또는 `aot-theme-variables.css`에서 JS getComputedStyle로 읽어 전달하는 방식
고려 (JS canvas 렌더링에 CSS 변수 간접 주입).

---

## 작업 우선순위 & 순서

| 순서 | 위젯 | 우선순위 | 예상 난이도 |
|------|------|----------|------------|
| 1 | AoT_map.py | 높 | 중 — 신규 토큰 추가 후 교체 |
| 2 | AoT_weather_fcst_announcement.py | 높 | 중 — JS 인라인 → 클래스 추출 |
| 3 | AoT_advice.py | 중 | 낮 — 토큰 신규 등록 + 교체 |
| 4 | AoT_gauge_angular.py + AoT_wind_angular.py | 중 | 낮 — constants.py 추출 |
| 5 | AoT_timer.py | 중 | 낮 — 소규모 토큰 교체 |
| 6 | AoT_camera.py | 낮 | 낮 — 3행 교체 |
| 7 | AoT_controller.py / AoT_facility.py / AoT_graph.py | 낮 | 없음 또는 미미 |

---

## 신규 추가가 필요한 CSS 토큰 목록

### aot-theme-variables.css 추가 예정

```css
/* Map/GIS 전용 */
--aot-map-compass-dark:         #333333;
--aot-map-compass-light:        #cccccc;
--aot-map-device-tint:          rgba(153, 90, 255, 0.2);
--aot-map-device-tint-active:   rgba(153, 90, 255, 0.8);

/* Advice 위젯 severity 배경 */
--aot-advice-none-bg:      #1A202C;
--aot-advice-none-text:    #CBD5E0;
--aot-advice-none-border:  #4A5568;
--aot-advice-info-bg:      #1A365D;
--aot-advice-info-text:    #90CDF4;
--aot-advice-info-border:  #3182CE;
--aot-advice-warning-bg:   #2D2A00;
--aot-advice-warning-text: #F6E05E;
--aot-advice-warning-border: #D69E2E;
--aot-advice-critical-bg:  #2D0F0F;
--aot-advice-critical-text: #FEB2B2;
--aot-advice-critical-border: #E53E3E;
```

> advice 변형 색상은 다크-테마 전용 팔레트이므로 `:root[data-theme="dark"]`에만
> 넣거나, advice 위젯 자체 `<style>` 블록에 로컬 토큰으로 유지하는 방식도 허용.

### aot-widget-typography.css 추가 예정

```css
.aot-w-row-between { display:flex; justify-content:space-between; width:100%; }
.aot-w-col-third   { width:33.33%; padding:0 var(--aot-space-2); vertical-align:bottom; }
```

### aot/widgets/constants.py 신규 생성

```python
BAND_PALETTE = ["#2DB4FF", "#54BCC1", "#64C567", "#FEAE5F", "#CF5C58"]
```

---

## 수정하지 않는 항목 (정당 사유)

- `AoT_graph.py` 컨테이너 `position:absolute; left:0; top:0; bottom:0; right:0` —
  Highcharts 컨테이너 크기 계산 필수 요소
- `AoT_map.py` Leaflet 마커 SVG `data:image/svg+xml` 내 fill 색상 —
  SVG 문자열 인코딩 제약으로 CSS 변수 적용 불가, 유지
- `display:none` 인라인 스타일 — JS 동적 표시 제어용, 유지
- `style="position: relative; width: 100%; height: ...px"` — JS로 계산된 동적 픽셀값, 유지
