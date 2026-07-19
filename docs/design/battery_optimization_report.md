# 모바일 배터리 최적화 작업 보고서

**브랜치**: `perf/battery-opt-3`
**작업일**: 2026-06-08
**담당**: AoT-inc

---

## 배경

모바일 기기에서 AoT 대시보드 접속 시 배터리 소모량이 급격히 증가하는 현상 보고.
이전 세션에서 1차 개선 진행 후에도 체감 차이가 없어 2차 심층 분석 및 추가 최적화 세션 진행.

---

## 원인 분석

### 측정 기준

| 항목 | 측정 방법 |
|---|---|
| JS 번들 크기 | `curl -s -o /dev/null -w "%{size_download}"` |
| FA 빌드 방식 | `grep -r "fontawesome-all.min.js"` 로 SVG-JS 여부 확인 |
| 폴링 중복 | `layout_default.html` setInterval 호출 수 확인 |
| 렌더 루프 | `requestAnimationFrame` 무조건/온디맨드 여부 코드 분석 |

### 확인된 주요 원인

| 우선순위 | 원인 | 소모 유형 |
|---|---|---|
| 1 | FontAwesome SVG-JS 빌드: 모든 DOM 변경 시 `MutationObserver` 실행 | CPU (메인스레드 상주) |
| 2 | `setInterval` 폴링이 탭 비활성/화면잠금 시에도 계속 실행 | CPU + 셀룰러 라디오 |
| 3 | `layout_default.html` 에서 `check_daemon_status` 60초 타이머 중복 등록 | 네트워크 |
| 4 | facility 3D 뷰어: `requestAnimationFrame` 무조건 60fps 루프 | GPU |
| 5 | 비지도 페이지에서도 maplibre-gl(775KB) + turf(563KB) 전부 로드 | 파싱/메모리 |
| 6 | 저전력/데이터절약 모드에서도 폴링 간격 미조정 | CPU + 셀룰러 |
| 7 | 탭 비활성 시 `.fa-spin` 등 CSS 무한 애니메이션 계속 실행 | GPU |

---

## 적용된 최적화

### Step 1 — FontAwesome SVG-JS → Webfont 전환

**커밋**: `d2b7efb`

**변경 파일**:
- `aot/aot_flask/templates/layout_default.html`
- `aot/aot_flask/templates/layout.html`
- `aot/aot_flask/templates/layout-remote.html`
- `aot/aot_flask/static/vendor/fontawesome-5.11.2/` (신규 디렉토리)

**내용**:

| 이전 | 이후 |
|---|---|
| `fontawesome-all.min.js` (SVG-JS 빌드, 1.14MB) | `all.min.css` + webfont 파일들 (CSS 방식) |
| 모든 DOM 변경 시 MutationObserver 실행 | MutationObserver 없음 |
| FA4 `.fa-*` 기본 지원 | `v4-shims.min.css` + `fa-compat.css` 로 호환 유지 |

`fa-compat.css` 는 FA4 bare `.fa` 클래스(font-weight:900 미설정)를 FA5 solid 체로 매핑하기 위해 신규 작성:
```css
i.fa:not(.fas):not(.far):not(.fab):not(.fal):not(.fad),
.fa:not(.fas):not(.far):not(.fab):not(.fal):not(.fad) {
  font-family: "Font Awesome 5 Free";
  font-weight: 900;
}
```

**효과**: 페이지당 JS 파싱 약 1.1MB 감소, MutationObserver 상주 제거

---

### Step 2-A — 폴링 가시성 일시정지 + 데몬 폴링 중복 제거

**커밋**: `e67fbbd`

**변경 파일**:
- `aot/aot_flask/static/js/common/aot-poll-visibility.js` (신규)
- `aot/aot_flask/templates/layout_default.html` (중복 타이머 제거)

**내용**:

`aot-poll-visibility.js` — `setInterval` / `clearInterval` 전역 래핑:
- `document.hidden` 시 모든 추적 인터벌 일괄 정지 (`nativeClear`)
- 포그라운드 복귀 시 자동 재개 (`nativeSet`)
- 호출자에 반환하는 handle은 pause/resume 후에도 안정 유지 (위젯 코드 무수정)
- 문자열/비함수 콜백은 추적 제외, 네이티브 그대로 통과

`layout_default.html` — 중복 `setInterval(check_daemon_status, 60000)` 제거 (body 하단에 1개 중복 있었음)

반드시 다른 모든 스크립트보다 먼저 로드 (head 최상단):
```html
<script src="/static/js/common/aot-poll-visibility.js?v=20260608"></script>
```

**효과**: 탭 전환·화면잠금 시 네트워크 폴링 0건. 셀룰러 라디오 깨우기 0

---

### Step 3 — Facility 3D 뷰어 온디맨드 렌더 전환

**커밋**: `145acec`

**변경 파일**:
- `aot/aot_flask/static/js/widgets/AoT_facility/aot-facility-3d.js`
- `aot/widgets/AoT_facility.py` (캐시 버전 v29→v30)
- `aot/widgets/AoT_map.py` (동일)

**내용**:

`_buildAssetScene()` 함수 내 렌더 패턴 변경:

| 이전 | 이후 |
|---|---|
| `function animate() { requestAnimationFrame(animate); renderer.render(...); }` — 무조건 60fps | `requestRender()` 호출 시에만 1프레임 렌더 (온디맨드) |

신규 함수:
- `_renderOnce()`: 즉시 1프레임 렌더
- `_loop()`: OrbitControls damping 수렴 시까지만 루프 후 자동 정지
- `_scheduleRender()`: 중복 rAF 방지용 guard flag
- `requestRender()`: 외부 진입점

OrbitControls 이벤트(`change`, `start`, `end`) 및 GLTF 로드 완료 시 `requestRender()` 호출.

참고: 현재 배포된 facility 인스턴스 3개 모두 `parametric` 모드(GLTF 미사용)라 즉각 효과는 없으나, 향후 asset 모드 전환 시 자동 적용.

---

### WMS 프록시 500 수정 (부가 버그픽스)

**변경 파일**: `aot/aot_flask/routes_geo.py`

`maps.isric.org` 타임아웃 시 `500 Internal Server Error` 반환하던 것을 투명 1×1 PNG(200)로 교체:
```python
except Exception as e:
    return Response(
        _TRANSPARENT_1X1_PNG, status=200,
        content_type='image/png',
        headers={'Cache-Control': 'no-cache'}
    )
```

**효과**: MapLibre의 실패한 타일 무한 재시도 제거

---

### Step 6 — 적응형 폴링 간격

**커밋**: `a8bdb92`

**변경 파일**: `aot/aot_flask/static/js/common/aot-poll-visibility.js`

`navigator.connection` API 를 통해 저전력/저속 연결 감지:

```js
function calcDelayMult() {
  var conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (!conn) return 1;
  if (conn.saveData) return 2;              // 데이터 절약 모드
  if (conn.effectiveType === '2g' || conn.effectiveType === 'slow-2g') return 2;
  return 1;
}
```

- `delayMult` 가 2일 때 `realSet(rec)` 에서 `delay * 2` 로 등록
- `connection.change` 이벤트로 배율 변경 시 실행 중인 모든 인터벌 즉시 재스케줄
- 포그라운드 복귀(resumeAll) 시에도 최신 배율 적용

**효과**: 데이터절약 모드 또는 2G 연결 시 폴링 빈도 50% 감소

---

### Step 4 — Highcharts 애니메이션 비활성화

**커밋**: `a8bdb92`

**변경 파일**:
- `aot/widgets/AoT_graph.py`
- `aot/widgets/widget_graph_synchronous.py`
- `aot/widgets/AoT_gauge_angular.py`
- `aot/widgets/widget_gauge_angular.py`
- `aot/widgets/widget_gauge_solid.py`

그래프 위젯 `Highcharts.setOptions()` 에 전역 옵션 추가:
```js
chart: { animation: false },
plotOptions: { series: { animation: false } }
```

게이지 위젯 각 `Highcharts.chart({ chart: { ... } })` 에 개별 추가:
```js
chart: {
  type: 'gauge',   // or 'solidgauge'
  animation: false,
  ...
}
```

**효과**: 차트 초기 드로우 및 데이터 업데이트 시 GPU 애니메이션 제거. 값 즉시 반영.

---

### Step 7 — 백그라운드 CSS 애니메이션 일시정지

**커밋**: `a8bdb92`

**변경 파일**: `aot/aot_flask/static/js/common/aot-poll-visibility.js`

`visibilitychange` 핸들러에서 `<html>` 요소에 CSS 클래스 토글:

```js
function setHiddenClass(hidden) {
  if (hidden) document.documentElement.classList.add('aot-hidden');
  else        document.documentElement.classList.remove('aot-hidden');
}
```

페이지 로드 시 인라인 스타일 주입:
```css
.aot-hidden .fa-spin,
.aot-hidden [class*="fa-spin"],
.aot-hidden .spinner-border,
.aot-hidden .spinner-grow {
  animation-play-state: paused !important;
}
```

**효과**: 탭 비활성·화면잠금 시 무한 회전 스피너 등 CSS 애니메이션 즉시 정지

---

## 미적용 항목 (검토 후 보류)

| Step | 내용 | 보류 이유 |
|---|---|---|
| Step 5 | maplibre/turf 조건부 로드 | output/input/function 페이지에서 위치 선택용 지도 모달(`AoTMapModalController`)이 maplibre 의존. 단순 스킵 시 해당 기능 무음 실패. Lazy 로드 방식으로 별도 구현 필요. |

---

## 최종 변경 파일 목록

```
aot/aot_flask/static/js/common/aot-poll-visibility.js      신규+확장
aot/aot_flask/static/vendor/fontawesome-5.11.2/            신규 디렉토리
aot/aot_flask/templates/layout_default.html                FA교체, 중복타이머제거
aot/aot_flask/templates/layout.html                        동일(자동생성 소스 동기화)
aot/aot_flask/templates/layout-remote.html                 FA교체
aot/aot_flask/static/js/widgets/AoT_facility/aot-facility-3d.js  온디맨드렌더
aot/aot_flask/routes_geo.py                                WMS 프록시 수정
aot/widgets/AoT_facility.py                                캐시버전 v30
aot/widgets/AoT_map.py                                     캐시버전 v30
aot/widgets/AoT_graph.py                                   animation:false
aot/widgets/widget_graph_synchronous.py                    animation:false
aot/widgets/AoT_gauge_angular.py                           animation:false
aot/widgets/widget_gauge_angular.py                        animation:false
aot/widgets/widget_gauge_solid.py                          animation:false
```

## 커밋 이력

| 해시 | 내용 |
|---|---|
| `d2b7efb` | perf(battery): FontAwesome SVG-JS → 5.11.2 webfont 전환 |
| `e67fbbd` | perf(battery): Step 2-A 폴링 가시성 일시정지 + 중복 데몬 폴링 제거 |
| `145acec` | perf(battery): Step 3 facility GLTF asset 뷰어 온디맨드 렌더 전환 |
| `a8bdb92` | perf(battery): Step 6/4/7 적응형폴링·Highcharts애니·스피너CSS 최적화 |
