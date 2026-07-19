# AoT MapLibre Draw Module

## 개요

`aot-maplibre-draw.js`는 MapLibre-GL JS 기반 벡터 그리기를 위한 모듈입니다. Leaflet.Draw API와의 호환성 레이어를 제공하며, Polyline, Polygon, Rectangle, Circle, Marker 그리기를 지원합니다.

## 주요 기능

### Drawing Tools
- **Polyline**: 다중 선분 그리기
- **Polygon**: 다각형 그리기
- **Rectangle**: 사각형 그리기
- **Circle**: 원 그리기 (TerraDraw 사용)
- **Marker**: 점/마커 배치

### Edit/Delete Modes
- 피처 편집 모드
- 피처 삭제 모드
- 피처 선택/복합

### Leaflet.Draw API 호환
- `addLayer()` - FeatureGroup 추가
- `addDrawControl()` - 그리기 컨트롤 추가
- `getLayers()` - 레이어 배열 반환

### GeoJSON 내보내기
- `getGeoJSON()` - 전체 피처를 GeoJSON으로 반환
- `addGeoJSON()` - GeoJSON 데이터 임포트
- `clearAll()` - 전체 피처 삭제

## 사용법

### 1. 의존성 로드
```html
<!-- MapLibre GL -->
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.23.0/dist/maplibre-gl.css" />
<script src="https://unpkg.com/maplibre-gl@5.23.0/dist/maplibre-gl.js"></script>

<!-- Mapbox Draw -->
<link rel="stylesheet" href="https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.4.3/mapbox-gl-draw.css" />
<script src="https://api.mapbox.com/mapbox-gl-js/plugins/mapbox-gl-draw/v1.4.3/mapbox-gl-draw.js"></script>

<!-- AoT Draw Manager -->
<script src="aot-maplibre-draw.js"></script>
```

### 2. 지도 초기화
```javascript
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [128.6, 35.9],
  zoom: 12
});

map.on('load', () => {
  const drawer = AoTDrawManager.init('map1', map, {
    color: '#3bb2d0',
    fillOpacity: 0.2
  });
});
```

### 3. 그리기 모드 활성화
```javascript
// 각 그리기 도구 활성화
drawer.enablePolyline();   // 선 그리기
drawer.enablePolygon();    // 면 그리기
drawer.enableRectangle();  // 사각형 그리기
drawer.enableCircle();    // 원 그리기
drawer.enableMarker();    // 마커 배치

// 편집/삭제 모드
drawer.enableEdit();       // 편집 모드
drawer.enableDelete();     // 삭제 모드

// 그리기 모드 비활성화
drawer.disableDraw();
```

### 4. 이벤트 처리
```javascript
// 피처 생성 이벤트
drawer.on('created', (feature) => {
  console.log('피처 생성됨:', feature);
});

// 피처 편집 이벤트
drawer.on('edited', (feature) => {
  console.log('피처 편집됨:', feature);
});

// 피처 삭제 이벤트
drawer.on('deleted', (feature) => {
  console.log('피처 삭제됨:', feature);
});
```

### 5. GeoJSON 내보내기/가져오기
```javascript
// GeoJSON 가져오기
const geojson = drawer.getGeoJSON();
console.log(JSON.stringify(geojson, null, 2));

// GeoJSON 추가
drawer.addGeoJSON({
  type: 'FeatureCollection',
  features: [myFeature]
});

// GeoJSON 파일로 내보내기
const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/json' });
const url = URL.createObjectURL(blob);
// ... download logic
```

### 6. Leaflet.Draw 호환
```javascript
// FeatureGroup 추가
const featureGroup = new L.FeatureGroup();
map.addLayer(featureGroup);
drawer.addLayer(featureGroup);

// DrawControl 추가
drawer.addDrawControl({
  position: 'topright',
  draw: {
    polyline: true,
    polygon: true,
    rectangle: true,
    marker: true
  },
  edit: {
    featureGroup: featureGroup
  }
});
```

## API Reference

### AoTDrawManager (Static)

| Method | Description |
|--------|-------------|
| `init(container, map, config)` | 새 그리기 인스턴스 생성 |
| `get(id)` | ID로 인스턴스 가져오기 |
| `getDefault(map, config)` | 기본 인스턴스 가져오기/생성 |
| `destroyAll()` | 모든 인스턴스 제거 |
| `createCircle(center, radius, steps)` | 원 GeoJSON 생성 |
| `createRectangle(bounds)` | 사각형 GeoJSON 생성 |
| `fromLeafletLayer(layer)` | Leaflet 레이어를 GeoJSON으로 변환 |

### DrawInstance

#### Drawing Methods
- `enablePolyline()` - 선 그리기 모드
- `enablePolygon()` - 면 그리기 모드
- `enableRectangle()` - 사각형 그리기 모드
- `enableCircle()` - 원 그리기 모드
- `enableMarker()` - 마커 배치 모드
- `enableEdit()` - 편집 모드
- `enableDelete()` - 삭제 모드
- `disableDraw()` - 그리기 모드 비활성화

#### Feature Methods
- `getGeoJSON()` - GeoJSON FeatureCollection 반환
- `getLayers()` - 레이어 배열 반환
- `addGeoJSON(data)` - GeoJSON 추가
- `clearAll()` - 전체 삭제
- `deleteSelected()` - 선택된 피처 삭제
- `selectFeature(id)` - 피처 선택
- `getSelectedIds()` - 선택된 ID 배열

#### Event Methods
- `on(event, callback)` - 이벤트 리스너 등록
- `off(event, callback)` - 이벤트 리스너 제거
- `once(event, callback)` - 일회성 이벤트

#### Utility Methods
- `isReady()` - 초기화 여부
- `isDrawing()` - 그리기 중 여부
- `getMode()` - 현재 모드
- `getCount()` - 피처 수
- `setStyle(style)` - 스타일 설정
- `destroy()` - 인스턴스 제거

## 의존성

```json
{
  "dependencies": {
    "@mapbox/mapbox-gl-draw": "^1.5.1",
    "maplibre-gl": "^5.23.0",
    "terra-draw": "^1.28.8"
  }
}
```

## 라이선스

MIT License
