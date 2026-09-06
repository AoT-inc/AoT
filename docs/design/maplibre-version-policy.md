# MapLibre 버전 정책 — 4 와 5 를 나란히 받아들이기

AoT 는 MapLibre GL JS 를 **반입(vendoring)** 해서 쓴다. 이 문서는 그 버전을
누가 정하고, 버전에 따라 무엇이 달라지는지를 적는다.

정본 코드: `aot/utils/maplibre.py`(서버), `geo/aot-maplibre-patches.js` 안의
`AoTMapLibreCaps`(브라우저), 계약 테스트 `aot/tests/test_maplibre_version.py`.

---

## 1. 버전은 반입 디렉터리가 정한다

`aot/aot_flask/static/vendor/maplibre-gl-<버전>/` 을 훑어 **가장 높은 것**을
고른다. `maplibre-gl.js` 가 실제로 들어 있는 디렉터리만 센다(껍데기 디렉터리가
버전을 가로채면 404 만 서빙하게 된다).

```
static/vendor/maplibre-gl-4.1.2/   ← 지금
static/vendor/maplibre-gl-5.6.0/   ← 떨어뜨려 놓으면 이쪽이 쓰인다
```

**5 로 올리는 절차는 디렉터리 하나를 더 놓는 것이 전부다.** 지우면 4 로 돌아온다.

### 왜 이렇게 했나

버전 문자열 `4.1.2` 가 여섯 자리에 손으로 박혀 있었다 — layout 의 로컬/CDN 두
갈래(`layout_default.html`·`layout.html`)와 `map-loader.js` 의 네 자리. 그 중
하나만 놓치면 **CSS 는 4 인데 JS 는 5** 같은 상태가 조용히 만들어진다. 로드는
되고, 깨지는 것은 한참 뒤 어느 화면 하나다.

지금은 서버가 한 번 정해 `window.AOT_MAPLIBRE` 로 내려보내고, 템플릿과 로더가
그것만 쓴다. 손으로 고칠 자리는 없다 — `test_maplibre_version.py` 가 새 하드코딩을
막는다.

---

## 2. 능력으로 묻는다

부르는 쪽이 알고 싶은 것은 번호가 아니라 **"이 기능을 켜도 되는가"** 다.

```js
if (window.AoTMapLibreCaps.supportsTerrain()) { ... }
```
```python
from aot.utils import maplibre
if maplibre.supports_terrain(): ...
```

브라우저 쪽은 **실제로 실린 것을 우선**한다: `maplibregl.getVersion()` 이
있으면 그것, 없을 때만 서버가 준 값. 둘이 어긋날 수 있기 때문이다(CDN 서빙으로
바꿨는데 CDN 이 다른 것을 주는 경우).

같은 판정을 두 언어가 되풀이하므로, 규칙을 바꿀 땐 **두 곳을 함께** 본다.

---

## 3. 지금 버전별로 갈리는 것 — 3D 지형

| | MapLibre 4 | MapLibre 5 |
|---|---|---|
| `enable_3d_terrain` 옵션 | 설정 화면에 **안 나온다** | 나온다 |
| 저장된 값이 켜져 있으면 | 지도가 **무시한다** | 적용된다 |
| 저장된 값 자체 | **그대로 남는다** | 되살아난다 |

옵션을 지우는 대신 감추기만 하는 이유: 값을 지우면 5 를 반입한 뒤 사용자가
다시 켜야 한다. 저장 경로 둘(`custom_options_return_json`,
`coerce_custom_option_values`)은 **선언에 없는 키를 건드리지 않고 통과시키므로**
값은 그대로 남는다.

### 왜 4 에서 막았나 (2026-09-06 실측, 김제 지도)

지형을 켜면 구획 외곽선에서 아래로 늘어지는 세로선이 그려진다.

- 구획 외곽선 레이어(`aot-plot-line-*`) 하나만 숨기면 세로선이 전부 사라진다.
- 그 픽셀에서 `queryRenderedFeatures` 는 **아무것도 잡지 못한다** — 도형이 아니라
  그리기 단계의 찌꺼기다. 원본 좌표에도 z 성분은 없다(전부 2차원).
- 줌·베어링을 바꾸면 나타났다 사라진다.
- 외곽선을 `fill-outline-color` 로 바꾸면 사라진다(대신 선 굵기와 예정 구획의
  점선을 잃는다 — 그래서 이 우회는 쓰지 않았다).
- **고도 데이터를 제대로 넣어도 그대로다.** 전 지구 DEM 으로 바꿔 실제 고도
  (0 / 0.4 / 4.95m)를 받게 해도 같은 세로선이 나왔다. 즉 데이터가 아니라 4 의
  line+terrain 렌더 결함이다.

---

## 4. ⚠ 5 를 반입하기 전에 반드시 할 것 — DEM 소스 교체

지금 코드가 가리키는 DEM 은 **쓸 수 없는 것**이다.

```
https://demotiles.maplibre.org/terrain-tiles/tiles.json
```

이 tiles.json 의 이름은 `jaxa_terrainrgb_N047E011` — **알프스 한 구역짜리 데모
데이터**다. `bounds` 는 전 지구로 적혀 있지만 실제 타일은 그 구역뿐이다.

| 위치 | z2~z12 타일 |
|---|---|
| 김제 (35.8N 126.9E) | 전부 **404** |
| 영양 (36.7N 129.1E) | 전부 404 |
| 알프스 (47.2N 11.4E) | 200 |

`queryTerrainElevation` 을 z3·6·9·12·14·16 에서 재면 국내는 **전부 0m** 다.
즉 지금 이 옵션을 켜면 고도는 1cm 도 생기지 않으면서, 쓰지도 않은 데이터에 대한
"AW3D30 (JAXA)" 저작권 표시와 지형 렌더 비용만 붙는다.

AoT 는 한국 전용이 아니다(22개 언어). 알프스 밖 **모든** 설치가 같은 상태다.

그러므로 5 를 반입해 `supports_terrain()` 이 True 를 돌려주기 시작하는 순간,
이 옵션은 "동작하지 않는 스위치" 가 된다. **DEM 을 먼저 정하고 나서** 올려야
한다. 후보를 고를 때 함께 볼 것:

- 전 지구 커버리지 (국내·일본·동남아 포함)
- 라이선스와 저작권 표시 의무
- 키 없이 쓸 수 있는가 (폐쇄망 설치에서 무엇을 할 것인가)
- 트래픽이 어디로 나가는가

교체 대상은 네 자리다 — `aot-map-widget-vector.js`,
`dashboard-widget-live-preview.js`(둘 다 위 데모 URL),
`aot-maplibre-loader.js`, `aot-vector-layer-manager.js`(둘 다 MapTiler 키 URL).

---

## 5. `setTerrain` 을 켜는 자리

네 곳이고 **전부** 능력 질의 뒤에 있다. 새로 추가하면
`test_every_setTerrain_call_site_is_gated` 가 잡는다.

| 파일 | 켜는 조건 |
|---|---|
| `widgets/AoT_map/aot-map-widget-vector.js` | 위젯 옵션 `enable_3d_terrain` |
| `app/dashboard-widget-live-preview.js` | 설정 드로어의 라이브 반영 |
| `geo/aot-maplibre-loader.js` | `AOT_GEO_CONFIG.enable_terrain` |
| `geo/aot-vector-layer-manager.js` | `addTerrain()` 직접 호출 |

(`setTerrain(null)` 은 끄는 쪽이라 게이트가 없다.)
