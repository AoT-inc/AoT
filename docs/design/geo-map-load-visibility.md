# geo/design — 로딩 시 표시 상태와 화면 최대화

지도 디자인 화면(`geo/design`)이 **열릴 때** 무엇을 그리고 무엇을 안 그리는지,
그리고 지도를 넓게 쓰는 최대화가 설정 드로어와 어떻게 공존하는지에 대한 정본.

관련: [geo-vegetation-planting.md](geo-vegetation-planting.md)(식생 구획),
[z-index-system.md](z-index-system.md)(겹침 순서 토큰).

---

## 1. 감춘 도형은 **한 번도 그리지 않는다** (구현 확정, 2026-08-14)

### 증상

각 모드에는 "지도에서 보기" 스위치가 있고 그 값은 `theme_config` 의
`vis_shape_<mode>` 로 저장된다. 그런데 페이지를 열면 **꺼 둔 종류가 잠깐
나타났다가 사라졌다**. 결과적으로는 설정대로 정리되지만, 매번 화면이 번쩍이고
"로딩이 두 번 도는" 인상을 준다.

### 원인 — 판정 시점이 그리기보다 늦었다

도형은 만들어지는 즉시 `ui._setLayerStyle → _applyVisibilityToLayer` 로 표시
여부를 판정받는다. 그 판정은 `this._hiddenShapeTypes` 집합을 본다.

그런데 그 집합은 **도면을 다 그린 뒤** `loadMap()` 의 `finally` 에서
`restoreShapeVisibility()` 가 채우고 있었다. 즉 그리는 동안에는 집합이
`undefined` 라 모든 도형이 "보임" 으로 판정됐고, 다 그린 뒤에야 집합이 채워져
다시 훑어 감췄다. 그 사이에 그려진 프레임이 깜빡임의 정체다.

그 뒤처리를 메우려고 `idle` 이벤트마다 전체를 다시 훑는 루프가 붙어 있었는데,
이것이 사용자가 지적한 "불필요한 로딩 반복" 이다. 실측: 도형 82개짜리 지도를
한 번 여는 동안 표시 상태 쓰기가 **3,507회**, 그중 대부분이 이미 같은 값을
다시 쓰는 것이었다.

### 채택한 규약 — "태어날 때 정한다"

**표시 상태는 GL 레이어를 만드는 `addLayer()` 호출에 `layout.visibility` 로
함께 넣는다.** 만들고 나서 `setLayoutProperty` 로 끄는 방식은, 생성과 끄기
사이에 프레임이 그려지면 반드시 깜빡인다 — 순서를 아무리 조여도 구조적으로
남는 틈이다. 만들 때 정하면 그 레이어는 **보이는 상태로 존재한 적이 없다**.

이를 위해 세 가지를 바꿨다:

1. **집합을 생성자에서 채운다.** `AoTGeoDesign.readHiddenShapeTypes()` 는
   `AOT_GEO_CONFIG.theme_config` 만 읽는 순수 함수라 지도도 도형도 필요 없다.
   생성자(`aot-geo-design-v3.js`)에서 부르므로, 첫 도형이 만들어지기 전에
   이미 답이 준비돼 있다.
2. **붙이기 전에 새긴다.** `_processLoadedFeature` 가 `addLayer` 를 부르기
   **전에** `layer._desiredVisibility` 를 채운다. 예전에는 이 값을 정하는
   `_setLayerStyle` 이 `addLayer` 뒤에 있어 항상 한 박자 늦었다.
3. **모든 생성 경로가 그 값을 읽는다.** `_desiredVisibility` 는 원래 코드에
   있었지만 **아무도 쓰지 않는 죽은 필드**였다(읽는 곳만 있고 쓰는 곳이 없었다).
   이제 다음 경로가 전부 `layout.visibility` 로 반영한다:

   | 경로 | 파일 |
   |---|---|
   | 레이어 그룹 `doAdd` (주 로딩 경로) | `aot-geo-layer.js` |
   | 단독 `addTo()` 의 `doAddToMap` | `aot-geo-layer.js` |
   | 폴리곤 테두리 `_ensurePolygonOutline` | `aot-geo-layer.js` |
   | 원(구역·시설) per-instance fill | `aot-geo-layer.js` |
   | DOM 마커 2곳 (GL 아님 → `display`) | `aot-geo-layer.js` |
   | 장치 마커 아이콘 HTML | `aot-geo-devices-v3.js` |
   | 공유 버킷(배관·스프링클러·조인트) | `aot-geo-render-bucket.js` |
   | `loadMap` 의 1초 FAILSAFE | `aot-geo-design-v3.js` |

   버킷은 어느 모드 것인지를 `BUCKET_LAYERS_BY_MODE` 에서 **역참조**한다 —
   목록을 따로 들면 둘이 어긋난다.

### 같은 값을 다시 쓰지 않는다 — 단, **기억하지 말고 지도에 물어본다**

`_applyVisibilityToLayer` 는 쓰기 전에 지도의 현재 상태를
`getLayoutProperty(id, 'visibility')` 로 읽어, 원하는 값과 같으면 건너뛴다.
이 함수는 모드 전환·강조 갱신·안전망 루프마다 도형마다 불리므로 이 한 줄이
위의 3,507회를 없앤다. `getLayoutProperty` 는 메모리 조회라
`setLayoutProperty`(스타일 재계산 유발)보다 훨씬 싸다.

⚠ **"지난번에 쓴 값" 을 필드에 기억해 두고 비교하면 안 된다.** 처음에 그렇게
구현했다가 회귀를 만들었다: GL 레이어는 모드 전환 등으로 **다시 만들어지는**
일이 있는데(새 레이어는 보임 상태다), 기억한 값은 여전히 `'none'` 이라 교정이
영영 막힌다. 실측으로 장치 도형 16개가 감춰지지 않고 남았다. 지도에 물어보는
방식은 그 상황에서 스스로 교정된다.

마커의 DOM 노드(`display`) 쓰기는 조건 없이 매번 한다 — 아이콘이 새로 만들어질
수 있어 같은 이유로 건너뛰면 안 된다.

### 공유 버킷 레이어는 **주인이 하나**여야 한다

배관·연결부(피팅 점)·스프링클러는 도형마다 GL 레이어를 만들지 않고 수백 개를
합쳐 그리는 **공유 버킷 레이어**다(`aot-geo-render-bucket.js`). 그래서 이
레이어 하나의 `visibility` 를 여러 주체가 각자 썼다:

| 주체 | 판단 근거 | 모드 숨김을 봤나 |
|---|---|---|
| `_applyShapeVisibility` 의 버킷 루프 | 모드 숨김 | ○ |
| `_applyConnectionVisibility` (줌 컬링) | 줌 | **✗** |
| `_toggleSprinklerPoints` | 세부 토글 | **✗** |
| `_toggleConnectionPoints` | 세부 토글 | **✗** |

장비를 감춰 둔 채 지도를 조작하면(줌·모드 전환·배관 편집 후 재구성) 줌 컬링이
연결부 점을 도로 켜고, 다음 표시 반영이 다시 껐다 — **점이 간헐적으로 깜빡이는**
사용자 신고가 이것이다. `zoomend`·모드 전환·`geometry.js` 의 배관 재구성 후
1초 타이머가 각각 이 경로를 탄다.

**고친 방식**: 각 주체는 자기 조건만 **기록**하고, 최종 판단과 GL 쓰기는
`_resolveBucketVisibility()` / `_applyBucketVisibility()` 한 곳이 한다.
조건이 하나라도 "감춤" 이면 감춘다(모드 숨김 > 줌 컬링 > 세부 토글). 버킷을
새로 만들 때도 같은 함수를 읽으므로 **처음부터 제 상태로 태어난다**.

참고: `connection-dot` 버킷은 스펙에 `minzoomFromConfig: 'equipment_cull_zoom'`
가 있어 **줌 컬링은 MapLibre 가 이미 native 로 한다** — JS 로 한 번 더 끄고
켜던 것은 중복이었고, 그 중복이 곧 경합이었다.

실측(장비를 감춘 뒤 모드 전환 4회 + 줌아웃·줌인 + 팬):

| | 고치기 전 | 고친 뒤 |
|---|---|---|
| 버킷 표시 상태가 뒤집힌 횟수 | 조작마다 반복(깜빡임) | **1회**(감추라는 그 한 번뿐) |

### 장치도 주인이 하나여야 한다 — 모드 토글 vs 종류별 토글

장치에는 표시 스위치가 **두 겹**이다: 모드 전체("aot device 지도에서 보기")와
종류별(입력/출력/함수/복합). 이 둘이 서로 다른 방식으로 감추고 있었다.

- 모드 토글: `_applyVisibilityToLayer` → GL `visibility` / DOM `display`.
- 종류 토글(`setDeviceTypeVisibility`): 레이어를 그룹에서 **물리적으로 빼내
  곁주머니(`_hiddenLayerBag`)에 보관**하고, 켤 때 되돌리며 opacity/display 를
  되살림.

그래서 겹치면 서로를 덮어썼다:

1. 종류를 감추면 그 레이어가 그룹에서 사라져 **모드 토글이 보지 못한다** —
   상태가 두 곳으로 갈린다.
2. 종류를 다시 켜면 **모드가 꺼져 있는지 보지 않고** 되살려서, 감춰 둔 장치가
   되살아난다.
3. `_isLayerHidden` 은 종류별 상태를 `AOT_GEO_CONFIG.theme_config` **스냅샷**
   에서 읽었다. 그 스냅샷은 페이지를 열 때의 값이라, 화면에서 방금 바꾼 종류
   토글을 반영하지 못하고 다음 반영에서 옛 값으로 되돌렸다.

**고친 방식**: 버킷 레이어와 같은 규칙이다 — 상태는 한 곳
(`_hiddenDeviceKinds`, 생성자에서 설정으로부터 시딩), 감추는 방법도 하나
(GL/DOM). 두 스위치는 **AND** 로 합쳐진다. 곁주머니는 없앴다(MapLibre 에서
`visibility:'none'` 은 렌더 비용이 0이라 물리적 제거의 이유가 사라졌다).

실측(모드↔종류를 8단계로 교차 토글):

| 단계 | 기대 | 결과 |
|---|---|---|
| 모드 끄기 | 전부 숨김 | ○ |
| 모드 끈 채 종류 켜기 | **계속 숨김**(모드가 이긴다) | ○ |
| 모드 다시 켜기 | 처음 상태와 **정확히 동일** | ○ |

### 도형을 지우면 테두리도 함께 지운다

폴리곤은 채움(`<id>`)과 테두리(`<id>-line`)가 별개 GL 레이어인데, 삭제 경로가
`-3d`(시설 압출)만 지우고 `-line` 을 남겨 **도형을 지워도 선이 허공에 남았다**
(새로고침해야 사라짐). 만드는 곳(`_ensurePolygonOutline`)과 지우는 곳이 갈려
있어 생긴 누락이라, 지우는 쪽도 `_removeCompanionLayers(mlMap, layerId)` 한
함수로 모았다 — 짝 레이어를 늘릴 때는 두 함수를 같이 고쳐야 한다.

### 안전망 루프는 수렴하면 스스로 끊는다

GL 레이어가 뒤늦게 붙는 경로가 아직 몇 개 남아 있다(스타일 로딩 전 지연 생성,
버킷 초기화 재시도, `loadMap` 의 1초 FAILSAFE). 그 경우만 `idle` 리스너가
메운다. `_applyActiveModeEmphasis()` 가 **아직 안 생긴 레이어 수**를 돌려주고,
그것이 0인 패스가 연달아 두 번 나오면 리스너를 뗀다. 끝내 안 생기는 레이어가
있어도 40패스에서 끊는다 — 로딩이 끝난 뒤까지 도는 것을 막는 것이 목적이다.

### 실측 (도형 82개, 감춘 종류 7개)

| | 고치기 전 | 고친 뒤 |
|---|---|---|
| 감춰야 하는데 **보이는 상태로 생성**된 레이어 | 74개 | **0개** |
| 로딩 한 번의 표시 상태 쓰기 | 3,507회 | 555회 |
| 로딩 후 지도를 움직일 때(pan·zoom) 표시/스타일 쓰기 | 계속 발생 | **0회** |
| 로딩 끝난 뒤 감춰야 하는데 보이는 레이어 | — | **0개**(37개 전부 `none`) |

토글은 그대로 동작한다(구역 9개: 켜면 9개 `visible`, 끄면 9개 `none`).

---

## 2. 최대화는 **브라우저 뷰포트 기준**이다 — 네이티브 전체화면 API 를 쓰지 않는다 (구현 확정, 2026-08-14)

### 왜 바꿨나

전체화면 버튼은 `#geo-design-wrapper.requestFullscreen()` 이었다. 두 가지가
깨진다:

1. **드로어와 지도 컨트롤이 공존하지 못한다.** 전체화면은 wrapper 를 브라우저
   top layer 로 올린다. 드로어가 그 화면에 남으려면 wrapper 의 **자손**이어야
   하는데, 그러면 드로어가 지도 오른쪽 컨트롤 위를 덮는다. wrapper 를 좁혀
   피하려 해도 드로어가 자손이라 같이 딸려 들어와 소용이 없다.
2. **임베드 환경에서 아예 안 켜진다.** iframe 에 `allow="fullscreen"` 이 없으면
   `requestFullscreen()` 이 `TypeError: Permissions check failed` 로 거부된다
   (실측). AoT 를 엣지 프록시 뒤에서 임베드해 여는 것은 정상 사용 경로다.

### 채택한 안

`body.aot-geo-maximized` 클래스 하나로 wrapper 를 `position: fixed; inset: 0;
z-index: var(--aot-z-overlay)` 로 만든다(규칙은 `geo_design.html`). top layer 를
쓰지 않으므로 드로어는 평소와 완전히 같은 일반 요소로 남고, 규칙 하나로 지도
오른쪽을 드로어 폭만큼 비운다:

```css
@media (min-width: 768px) {
  body.aot-geo-maximized.aot-widget-drawer-open #geo-design-wrapper {
      right: var(--aot-wdrawer-w) !important;
  }
}
```

겹치지 않으므로 지도 오른쪽 컨트롤과 드로어가 **동시에 보인다**(실측: 뷰포트
1280 → 지도 760 + 드로어 520, 컨트롤 오른쪽 끝 750).

대시보드 지도 위젯이 iOS 에서 쓰는 `.aot-map-pseudo-fullscreen`(`map.css`) 과
같은 발상이다. 다만 그쪽은 grid-stack 안에 있어 `<body>` 로 재부모화가 필요한
반면, 여기는 wrapper 가 이미 최상위라 클래스만으로 된다.

브라우저가 ESC 를 대신 처리해 주지 않으므로 `_toggleMaximize` 가 직접 받는다.
버튼 아이콘(`fa-expand`↔`fa-compress`)과 툴팁도 함께 바뀐다.

**트레이드오프**: 브라우저 탭·주소창은 그대로 남는다. 화면 전체를 덮는 것보다
드로어와의 공존이 이 화면에서는 더 중요하다는 판단이다(사용자 요청).

`_bindFullscreenModalFix`(전체화면 top layer 안으로 모달을 재부모화하는 처리)는
남겨 두었다 — 이 화면은 더 이상 네이티브 전체화면을 쓰지 않지만,
`document.fullscreenElement` 가 있을 때만 동작하므로 평소에는 아무 일도 하지
않는 안전망이다.

---

## 3. 정적 파일 캐시 무효화 — 손으로 적지 않는다

이 화면의 개별 스크립트는 `<script src="/static/js/geo/aot-geo-layer.js?v=20260814a">`
처럼 **버전을 손으로 적고** 있었다. 파일을 고쳐도 그 문자열이 그대로라 브라우저는
옛 파일을 계속 실행한다 — 이번 작업에서도 `aot-geo-layer.js` 수정이 반영되지
않아 원인을 오판할 뻔했다(스택 추적에 `?v=20260814a` 가 찍혀 발견).

`app.py` 에 이미 **내용 해시 기반 자동 버전**이 있다(`@app.url_defaults` 가
`url_for('static', …)` 에 `?v=<해시>` 를 붙인다). 그래서 이 화면의 리터럴
`/static/...` 참조 9건을 전부 `url_for('static', filename=…)` 로 바꿨다.
`aot/scripts/check_static_cache_busting.py` 가 리터럴 참조를 막는 검사기다 —
새 `<script>`/`<link>` 를 넣을 때는 반드시 `url_for` 를 쓸 것.
