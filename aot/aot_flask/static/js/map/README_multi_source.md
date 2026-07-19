# AoT Multi-Source Manager

다중 지도 소스 연동을 위한 모듈로, VWorld, MapTiler, OSM, Google Maps 등 다양한 지도 소스를 통합 관리합니다.

## 파일 구조

```
static/js/map/
├── aot-multi-source-manager.js      # 메인 모듈
├── aot-multi-source-manager.d.ts     # TypeScript 정의
└── aot-multi-source-integration.js   # AoT 시스템 연동 헬퍼
```

## 기능

### 지원 지도 소스

| Provider | Type | 설명 |
|----------|------|------|
| VWorld | Raster | 한국국토정보플랫폼 기본/위성 |
| MapTiler | Vector/Raster | 벡터/위성 타일 |
| OSM | Raster | OpenStreetMap 표준/후원방식 |
| Google | Raster | Streets/Satellite/Hybrid |

### 주요 API

#### 초기화
```javascript
// Leaflet 맵 인스턴스에 연결
var manager = Object.create(AoTMultiSourceManager);
manager.init(leafletMapInstance);
```

#### 소스 등록/해제
```javascript
// 새 소스 등록
manager.registerSource({
    id: 'my_source',
    name: '내 지도',
    provider: 'custom',
    type: 'raster',
    url: 'https://example.com/{z}/{x}/{y}.png',
    options: { maxZoom: 18 }
});

// 소스 해제
manager.unregisterSource('my_source');
```

#### 소스 전환
```javascript
// 애니메이션과 함께 전환
manager.switchSource('osm_standard', {
    animate: true,
    preserveView: true,
    onComplete: function(source) {
        console.log('전환 완료:', source.name);
    }
});

// Promise 기반
manager.switchSource('maptiler_vector').then(function(source) {
    console.log('벡터 타일 로드 완료');
}).catch(function(err) {
    console.error('전환 실패:', err);
});
```

#### 이벤트 핸들링
```javascript
// 소스 전환 이벤트
manager.on('sourcechange', function(data) {
    console.log('전환:', data.previous, '->', data.current);
});

// 소스 등록/해제 이벤트
manager.on('sourceregister', function(source) {
    console.log('새 소스:', source.name);
});
```

#### 베이스맵 컨트롤 생성
```javascript
// 컨트롤 추가
var control = manager.createSwitcherControl({
    position: 'topright',
    maxHeight: '300px'
});
control.addTo(leafletMapInstance);
```

### AoTMultiSourceIntegration 사용

기존 AoT 맵 시스템과 자동 연동:

```javascript
// 자동 초기화
AoTMultiSourceIntegration.init('map-container-id', {
    addControl: true,
    defaultSource: 'osm_standard',
    controlPosition: 'topright'
});

// 커스텀 레이어에서 소스 추가
var sourceId = AoTMultiSourceIntegration.addSourceFromLayer('map-container-id', {
    id: 'custom_layer',
    name: '사용자 정의',
    url: 'https://...',
    type: 'raster'
});
```

## 설정

### API 키 설정

```javascript
// 소스별 API 키 설정
manager.setApiKey('vworld_base', 'your-vworld-key');
manager.setApiKey('maptiler_vector', 'your-maptiler-key');
manager.setApiKey('google_street', 'your-google-key');
```

### 전환 애니메이션

```javascript
// 애니메이션 시간 설정 (ms)
manager.setTransitionDuration(500); // 0.5초
```

## 이벤트 목록

| 이벤트 | 데이터 | 설명 |
|--------|--------|------|
| `sourcechange` | `{previous, current, source}` | 소스 전환 완료 |
| `sourceregister` | `source` | 소스 등록됨 |
| `sourceunregister` | `{id}` | 소스 해제됨 |
| `sourceload` | `source` | 소스 로드 완료 |
| `sourceerror` | `{sourceId, error}` | 소스 오류 |

## 제한사항

- 벡터 타일 사용 시 MapLibre-GL 라이브러리가 필요합니다 (자동 로드)
- Google Maps 사용 시 Google Maps API 키가 필요합니다
- WMTS 소스는 leaflet-tilelayer-wmts.js가 로드되어 있어야 합니다

## 브라우저 호환성

- IE11 미지원 (ES6 코드 사용)
- 최신 Chrome, Firefox, Safari, Edge 권장

---

# AoTVectorLayerManager

벡터 소스와 레이어를 관리하는 모듈로, MapLibre-GL 기반 벡터 타일과 GeoJSON 레이어를 통합 관리합니다.

## 파일 구조

```
static/js/map/
├── aot-vector-layer-manager.js      # 벡터 레이어 관리자
├── aot-vector-layer-manager.d.ts    # TypeScript 정의
└── test-vector-layer-manager.html   # 테스트 HTML
```

## 기능

### 주요 기능

| 기능 | 설명 |
|------|------|
| 벡터 소스 추가 | MapTiler, OSM 등 벡터 타일 소스 관리 |
| GeoJSON 소스 추가 | GeoJSON 데이터 소스 (클러스터링 지원) |
| 레이어 추가/제거 | fill, line, circle, symbol, heatmap 레이어 |
| 레이어 스타일 변경 | paint/layout 속성 동적 변경 |
| 레이어 필터링 | MapLibre 필터 표현식 지원 |
| 클릭 이벤트 처리 | 피처 클릭/호버 이벤트 핸들링 |

### 주요 API

#### 초기화
```javascript
// MapLibre 맵 인스턴스에 연결
var layerManager = new AoTVectorLayerManager(mapInstance, {
    cursorOnHover: true,
    defaultLanguage: 'ko'
});
```

#### 벡터 소스 추가
```javascript
// OSM 벡터 소스 추가
layerManager.addOSMVectorSource('osm-vector');

// MapTiler 소스 설정
layerManager.addMapTilerSource('your-api-key', 'streets');

// 커스텀 벡터 소스
layerManager.addVectorSource('my-vector', {
    tiles: ['https://example.com/{z}/{x}/{y}.pbf'],
    minzoom: 0,
    maxzoom: 14,
    attribution: '© Custom'
});
```

#### GeoJSON 소스 추가
```javascript
// 기본 GeoJSON 소스
layerManager.addGeoJSONSource('my-geojson', {
    type: 'FeatureCollection',
    features: [...]
});

// 클러스터링 지원
layerManager.addGeoJSONSource('clustered-points', geoJsonData, {
    cluster: true,
    clusterRadius: 50,
    clusterMaxZoom: 14
});

// 데이터 업데이트
layerManager.updateGeoJSONData('my-geojson', newGeoJsonData);
```

#### 레이어 추가
```javascript
// 원(Circle) 레이어
layerManager.addCircleLayer('devices', 'my-geojson', {
    color: '#007bff',
    radius: 8,
    interactive: true
});

// 폴리곤 레이어 (fill + outline)
layerManager.addPolygonLayer('zones', 'zones-source', {
    fillColor: '#28a745',
    fillOpacity: 0.3,
    strokeColor: '#1e7e34',
    strokeWidth: 2
});

// 라인 레이어
layerManager.addLineLayer('roads', 'roads-source', {
    color: '#007bff',
    width: 4,
    dashArray: [2, 1]
});

// 심볼/라벨 레이어
layerManager.addSymbolLayer('labels', 'labels-source', {
    textField: 'name',
    color: '#333',
    size: 12
});
```

#### 레이어 제거
```javascript
// 단일 레이어 제거
layerManager.removeLayer('my-layer');

// 소스와 연관된 모든 레이어 제거
layerManager.removeSource('my-source');
```

#### 레이어 스타일 변경
```javascript
// paint/layout 속성 변경
layerManager.setLayerStyle('my-layer', {
    paint: {
        'fill-color': '#ff0000',
        'fill-opacity': 0.5
    },
    layout: {
        'visibility': 'visible'
    }
});

// 가시성 토글
layerManager.setLayerVisibility('my-layer', false);

// 투명도 변경
layerManager.setLayerOpacity('my-layer', 0.7);
```

#### 레이어 필터링
```javascript
// 필터 적용
layerManager.setFilter('my-layer', ['==', ['get', 'type'], 'device']);

// 다중 조건 필터
layerManager.setFilter('my-layer', [
    'all',
    ['>=', ['get', 'value'], 100],
    ['==', ['get', 'category'], 'A']
]);

// 필터 해제
layerManager.clearFilter('my-layer');

// 현재 필터 조회
var filter = layerManager.getFilter('my-layer');
```

#### 클릭 이벤트 처리
```javascript
// 피처 클릭 핸들러 등록
var unsubscribe = layerManager.onLayerClick(function(feature, lngLat, layerId) {
    console.log('클릭된 피처:', feature.properties);
    console.log('위치:', lngLat.lat, lngLat.lng);
    console.log('레이어:', layerId);
});

// 핸들러 해제
unsubscribe();

// 호버 이벤트
var unsubHover = layerManager.onLayerHover(function(feature, lngLat, layerId, type) {
    if (type === 'enter') {
        console.log('호버 시작:', feature.properties.name);
    } else {
        console.log('호버 종료');
    }
});
```

#### 유틸리티
```javascript
// 특정 포인트의 피처 조회
var features = layerManager.getFeaturesAtPoint(['layer1', 'layer2'], [100, 200]);

// 범위 내 피처 조회
var features = layerManager.getFeaturesInBounds(bounds, ['layer1']);

// 레이어 범위로 지도 이동
layerManager.fitToSource('my-source', { padding: 50 });

// 모든 레이어 목록
var layers = layerManager.getAllLayers();

// 레이어 존재 확인
if (layerManager.hasLayer('my-layer')) {
    // ...
}
```

#### 정리
```javascript
// 모든 리소스 정리
layerManager.destroy();
```

## 프리셋 스타일

기본으로 제공되는 레이어 스타일:

| 스타일 | 설명 | 색상 |
|--------|------|------|
| `device` | 디바이스 마커 | #007bff |
| `facility` | 시설물 영역 | #82898f |
| `zone` | 존 경계 | #28a745 |
| `site` | 사이트 경계 | #DF5353 |
| `equipment` | 장비 영역 | #007bff |
| `reference` | 참조 레이어 | #ff00ff |

## 테스트

`test-vector-layer-manager.html` 파일을 브라우저에서 열어 테스트할 수 있습니다:

1. 포인트, 폴리곤, 라인 레이어 추가
2. 필터 적용/해제
3. 색상/투명도 변경
4. 클릭 이벤트 확인

## 제한사항

- MapLibre-GL 라이브러리가 필요합니다
- 벡터 타일 소스는 MVT/PBF 형식을 지원해야 합니다
- GeoJSON은 유효한 RFC 7946 형식이어야 합니다

## 브라우저 호환성

- IE11 미지원 (ES6 코드 사용)
- 최신 Chrome, Firefox, Safari, Edge 권장
