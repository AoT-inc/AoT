# 지도 위젯 — `loadGeoJSONLayers` 분해 설계

`aot-map-widget-vector.js`의 `loadGeoJSONLayers`는 **5,551줄짜리 단일 함수**다.
이름은 레이어 로더인데 그 안에 구역·장치·사이트·시설 모달 기계가 통째로 들어 있다.

이 문서는 그것을 어떻게 가를지 정한다. 2026-09-06에 한 번 실패한 시도의 원인과
그 실패가 알려 준 것을 함께 적는다 — 그 실패가 이 설계의 근거다.

---

## 1. 왜 어려웠나

### 1-1. 처음 시도와 실패

장치 모달 11개(약 400줄)를 "독립적"이라 보고 IIFE 최상위로 끌어올렸다가 되돌렸다.
`_renderDeviceBody`가 부르는 `_wireUpBtn`을 **이름만 보고** 공용 헬퍼로 분류했는데,
실제로는 모든 모달을 잇는 **허브**였다 — 그 안에서 `_openZonePopup`·`_openBayPopup`·
`_openSitePopup`을 부른다. 최상위 함수는 안쪽 스코프를 볼 수 없으니 장치 모달을
여는 순간 ReferenceError다.

그때 통과한 검증: `node --check`, 번들 빌드, `check_js_undefined_calls`,
옛/새 번들을 iframe에 로드해 전역 30개를 비교한 것. **전부 로드 시점만 본다.**
함수 정의는 멀쩡히 실리고 **부를 때** 터지는 결함이라 잡히지 않았다.

그래서 `check_js_scope_reach.py`를 만들어 커밋 훅에 넣었다. 이 설계의 각 단계는
그 검사를 통과해야 한다.

### 1-2. 교훈

**이름으로 소속을 판정하지 말 것.** 호출 그래프를 그려서 정해야 한다.

---

## 2. 실제 구조 (측정값, 2026-09-06)

### 2-1. 기계별 규모

| 기계 | 함수 | 줄 |
|---|---:|---:|
| facility (시설·베이) | 53 | 2,733 |
| zone (구역) | 22 | 976 |
| **hub (모달 사이를 잇는 것)** | 14 | 782 |
| site (사이트) | 14 | 600 |
| device (장치) | 11 | 365 |
| **loader (진짜 레이어 로딩)** | 2 | 90 |

### 2-2. 기계 사이 호출

```
facility ↔ hub      13 + 12 = 25회   ← 가장 강한 결합
site     → zone      5회
facility → zone      5회
zone     ↔ hub       3 +  1
site     → hub       2회
그 밖                각 1회
loader   → 각 기계   각 1회          ← 열쇠
```

**`loader`는 각 기계의 진입점을 한 번씩만 부른다.** 나머지 결합은 전부 기계들
사이에 있다. 즉 **기계들을 통째로 함께 내보내면 그 결합은 그대로 유지되고**,
loader만 안에 남아 밖을 부르면 된다(안쪽에서 바깥은 보인다).

이것이 이 설계의 전부다. 하나씩 빼내려던 첫 시도가 실패한 이유이기도 하다.

---

## 3. 밖으로 나갈 때 걸리는 것

기계들이 `loadGeoJSONLayers`의 지역 이름을 쓴다. 전수로 세면 세 부류뿐이다.

### 3-1. 상태·상수 — 함께 올리면 끝 (조치 불필요)

| 이름 | 성격 |
|---|---|
| `_zonePopupState` · `_devicePopupState` · `_sitePopupState` · `_siteSummaryCache` | **uid로 키잉하는 맵** — 밖에 둬도 위젯끼리 안 섞인다 |
| `_ACT_CATS` · `C` · `_ZONE_HIST_CACHE_MS` · `_ACT_CHIP_PUSH_PX` · `_SENSOR_SUM_PRIORITY` · `_IEC_POLL_MS` · `_IEC_POLL_MAX` · `_HIST_HOURS` · `_HIST_CACHE_MS` · `_OV_REFRESH_MS` | 불변 상수 |

앞서 `_actLabelState`를 같은 근거로 올렸고 문제가 없었다.

### 3-2. loader만 쓰는 것 — 안에 남으므로 무관

`mapUuid`, `_deviceColorExpr`, 그리고 `wOpts`/`vars`의 일부 용례는 전부
`_ensure*ShapeLayer`(=loader) 안에서만 쓰인다. loader는 안에 남는다.

### 3-3. 위젯 문맥 — **함수 4개만 손보면 된다**

| 함수 | 쓰는 것 | 조치 |
|---|---|---|
| `_boolOpt(key)` | `wOpts` | 호출부를 `_boolOptOf(uid, key)`로 (이미 최상위에 있음) |
| `_upFromMap(uuid)` | `uniqueId`, `map` | `_upFromMap(uid, uuid)`로 인자 추가 |
| `_computeChipPos(ring, centroid, qLng, qLat, map)` | `map` | 이미 인자에 있다 — 지역 참조만 제거 |
| `_sensorLabelOpts(_vars)` | `uniqueId`,`map`,`wOpts`,`vars` | `_sensorLabelOpts(uid, _vars)`로 |

나머지 위젯 문맥 사용처(`_attachPlotControl`, `_facilityBaySlices`,
`_attachActuatorLabels`, `_detachActuatorLabels`)는 **이미 `uid`를 첫 인자로 받는다.**

조회는 파일 안에서 이미 여러 곳이 쓰는 경로를 그대로 쓴다:

```js
function _ctx(uid) {
    var inst = (window.AoTWidgetInstances || {})[uid] || {};
    return { instance: inst, map: inst.map,
             wOpts: (inst.vars && inst.vars.vars) || {}, vars: inst.vars };
}
```

---

## 4. 단계

각 단계는 그것만으로 커밋 가능하고, 다음 단계 없이도 정상 동작해야 한다.

### 1단계 — 상태·상수를 최상위로

3-1의 14개를 올린다. 의미가 변하지 않으므로(uid 키잉 맵·불변 상수) 위험이 가장 낮다.

**검증**: 스코프 검사 0건, 전역 비교 동일, 전체 테스트.

### 2단계 — 위젯 문맥 의존 4개 정리

3-3의 시그니처를 바꾸고 호출부를 맞춘다. 이 단계까지 마치면 기계들은
`loadGeoJSONLayers`의 지역 이름을 **하나도** 쓰지 않는다.

**검증**: 위와 같음. 여기서 "지역 이름 사용 0건"을 스크립트로 확인한다.

### 3단계 — 네 기계와 허브를 통째로 최상위로

5,456줄을 한 번에 옮긴다. **쪼개서 옮기면 안 된다** — 2-2의 결합 때문에 중간
상태가 깨진다. 옮기는 동안 파일은 컴파일되지 않는 상태를 지나므로, 한 번의
편집으로 끝내고 즉시 검증한다.

`loadGeoJSONLayers`는 loader 2개와 진입 배선만 남아 **수백 줄**이 된다.

**검증**: 스코프 검사, 전역 비교, 전체 테스트, 그리고 **브라우저에서 네 모달을
실제로 열어 본다** — 1-1의 실패가 로드 검증만으로는 안 잡혔기 때문이다.

### 4단계 (선택) — 파일 분리

3단계까지 마치면 기계들이 IIFE 최상위의 형제가 되므로, 그때 비로소 파일로
나눌 수 있다. 다만 파일을 나누면 IIFE가 갈라져 서로를 못 보므로, 그 시점에
전역 노출이나 등록소가 **처음으로** 필요해진다. 3단계까지의 이득(거대 함수 해소)
만으로 충분하면 여기서 멈춰도 된다.

---

## 5. 하지 않기로 한 것

**등록소(registry)로 상호 참조 끊기.** 진입점을 `window.AoTMapModals.zone.open`
같은 레지스트리로 바꾸면 파일을 자유롭게 나눌 수 있다. 하지만 지금 문제는 파일이
아니라 **한 함수가 5,551줄**인 것이고, 3단계는 그것을 레지스트리 없이 해결한다.
레지스트리는 4단계를 실제로 할 때 도입하는 것이 순서다 — 필요해지기 전에 넣으면
호출 한 번마다 간접층이 하나 더 생길 뿐이다.

---

## 6. 검증 도구

| 도구 | 무엇을 보나 |
|---|---|
| `aot/scripts/check_js_scope_reach.py` | 바깥이 안쪽 스코프의 이름을 부르는가 (커밋 훅) |
| `aot/scripts/check_js_undefined_calls.py` | 정의가 아예 없는 호출 (커밋 훅) |
| 번들 빌드 + iframe 전역 비교 | 로드 시점의 전역 집합·API 크기 |
| **브라우저에서 각 모달 열기** | 호출 시점 — 위 셋이 못 보는 것 |

마지막 줄이 이 작업의 필수 항목이다. 앞선 실패는 앞의 셋을 전부 통과했다.
