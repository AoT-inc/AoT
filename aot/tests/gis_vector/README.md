# GIS Vector Integration Tests

This directory contains comprehensive integration tests for the `gis_vector` branch.

## Test Structure

```
gis_vector/
├── __init__.py                      # Package initialization
├── conftest.py                      # Pytest fixtures and configuration
├── test_gis_vector_integration.py   # Main integration tests
├── test_gis_vector_performance.py   # Performance benchmarks
├── test_browser_compatibility.py    # Browser compatibility tests
├── test_leaflet_vs_vector_comparison.py  # Leaflet vs Vector comparison
├── test_complete_integration.py     # Complete integration tests (NEW)
└── README.md                       # This file
```

## Running Tests

### Run All Tests
```bash
cd /Users/gwansuk/Library/CloudStorage/SynologyDrive-dev/2603_AoT_ai/Build/5_docker
python -m pytest aot/tests/gis_vector/ -v
```

### Run Specific Test Categories
```bash
# Complete integration tests (all 6 categories)
python -m pytest aot/tests/gis_vector/test_complete_integration.py -v

# Integration tests only
python -m pytest aot/tests/gis_vector/test_gis_vector_integration.py -v

# Performance tests only
python -m pytest aot/tests/gis_vector/test_gis_vector_performance.py -v

# Browser compatibility tests only
python -m pytest aot/tests/gis_vector/test_browser_compatibility.py -v

# Leaflet vs Vector comparison tests
python -m pytest aot/tests/gis_vector/test_leaflet_vs_vector_comparison.py -v
```

### Run with Coverage
```bash
python -m pytest aot/tests/gis_vector/ --cov=aot.tests.gis_vector --cov-report=html
```

## Test Categories (from `test_complete_integration.py`)

### 1. Vector Rendering Tests (벡터 렌더링 테스트)
- `TestVectorTileRendering`: Vector tile source creation, layer visibility, style application
- `TestZoomLevelTileLoading`: Tile loading at multiple zoom levels, native zoom handling

### 2. Marker/Popup Tests (마커/팝업 테스트)
- `TestMapLibreMarkerBehavior`: Marker creation, clustering configuration
- `TestPopupDisplayBehavior`: Popup creation, visibility toggle, positioning

### 3. Drawing Tools Tests (그리기 도구 테스트)
- `TestDrawingToolInitialization`: Draw manager initialization, mode activation
- `TestPolylineDrawing`: Polyline creation, editing
- `TestPolygonDrawing`: Polygon creation, save operations
- `TestRectangleDrawing`: Rectangle creation, dimension calculation
- `TestCircleDrawing`: Circle creation (approximated polygon), radius validation
- `TestDrawEditDelete`: Feature selection, edit mode, deletion

### 4. Multi-map Source Tests (다중 지도 소스 테스트)
- `TestBaseMapSwitching`: 4 source switching, source preservation
- `TestLayerOrderManagement`: Layer ordering, visibility toggle
- `TestWMSOverlayIntegration`: WMS layer creation, concurrent with vector

### 5. Performance Benchmark Tests (성능 벤치마크)
- `TestLoadingSpeedComparison`: Vector tile loading, raster vs vector comparison
- `TestMemoryUsage`: Source registry memory, layer style memory
- `TestZoomPanResponse`: Zoom level calculation, pan animation performance

### 6. Regression Tests (회귀 테스트)
- `TestLeafletCompatibility`: Leaflet layer API, GeoJSON conversion
- `TestDatabaseIntegration`: GeoLayer, GeoMap, GeoShape model structure
- `TestBackendGISProviderIntegration`: Provider registration, URL construction, proxy routes
- `TestAPIEndpointCompatibility`: Geo API endpoints, GeoJSON response format

### 7. End-to-End Integration Tests
- `TestCompleteWorkflow`: Full map workflow, drawing-to-save workflow, source switch with overlay preservation

## Test Summary

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_complete_integration.py` | 49 | All 6 categories from directive |
| `test_gis_vector_integration.py` | 43 | Module integration, scenarios |
| `test_gis_vector_performance.py` | 15 | Performance benchmarks |
| `test_browser_compatibility.py` | 25 | Browser compatibility |
| `test_leaflet_vs_vector_comparison.py` | 9 | Leaflet vs Vector comparison |
| **Total** | **141** | **Full coverage** |

## Fixtures

Key fixtures defined in `conftest.py`:

- `mock_maplibre_map`: Mock MapLibre map instance
- `sample_geojson_points`: Sample point features (3 devices)
- `sample_geojson_polygons`: Sample polygon features (2 zones)
- `sample_geojson_lines`: Sample line features
- `gis_provider_configs`: GIS provider configurations (4 sources)
- `performance_metrics`: Performance tracking utility
- `app_config`: Flask application configuration

## Test Completion Criteria

- [x] Vector rendering tests implemented
- [x] Marker/Popup tests implemented
- [x] Drawing tools tests (4 types) implemented
- [x] Multi-map source tests implemented
- [x] Performance benchmarks implemented
- [x] Regression tests implemented
- [x] All 141 tests passing

## Browser Test Page

Interactive browser-based tests are available at:
```
aot/aot_flask/static/js/geo/test_integration.html
```

This HTML file provides a visual test runner for:
- MapLibre-GL vector rendering
- Drawing tools (Polyline, Polygon, Rectangle, Circle)
- Marker/Popup interactions
- Source switching
- Performance metrics
- Regression checks
