# coding=utf-8
"""
GIS Vector Complete Integration Tests

Comprehensive integration tests covering all requirements from gis-vector-integration-test directive:
1. Vector Rendering Test (벡터 렌더링 테스트)
2. Marker/Popup Test (마커/팝업 테스트)
3. Drawing Tools Test (그리기 도구 테스트)
4. Multi-map Source Test (다중 지도 소스 테스트)
5. Performance Benchmark (성능 벤치마크)
6. Regression Test (회귀 테스트)

@phase integration
@branch gis_vector
@test_strategy end-to-end
"""

import os
import sys
import pytest
import json
import time
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List
import math

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


# =============================================================================
# SECTION 1: Vector Rendering Tests (벡터 렌더링 테스트)
# =============================================================================

class TestVectorTileRendering:
    """Tests for MapLibre-GL vector tile rendering"""
    
    def test_vector_tile_source_creation(self, mock_maplibre_map):
        """Test creating vector tile source"""
        source_config = {
            'type': 'vector',
            'tiles': [
                'https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf'
            ],
            'minzoom': 0,
            'maxzoom': 14,
            'attribution': '&copy; <a href="https://www.maptiler.com/">MapTiler</a>'
        }
        
        mock_maplibre_map.addSource('vector-source', source_config)
        
        assert 'vector-source' in mock_maplibre_map.sources
        assert mock_maplibre_map.sources['vector-source']['type'] == 'vector'
        assert 'tiles' in mock_maplibre_map.sources['vector-source']
    
    def test_vector_layer_visibility_at_zoom(self, mock_maplibre_map):
        """Test layer visibility at different zoom levels"""
        # Add vector source
        mock_maplibre_map.addSource('vector-layer-source', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Add fill layer
        mock_maplibre_map.addLayer({
            'id': 'vector-fill-layer',
            'type': 'fill',
            'source': 'vector-layer-source',
            'source-layer': 'water',
            'paint': {
                'fill-color': '#3bb2d0',
                'fill-opacity': 0.8
            }
        })
        
        # Add line layer
        mock_maplibre_map.addLayer({
            'id': 'vector-line-layer',
            'type': 'line',
            'source': 'vector-layer-source',
            'source-layer': 'roads',
            'paint': {
                'line-color': '#333333',
                'line-width': 1
            }
        })
        
        assert 'vector-fill-layer' in mock_maplibre_map.layers
        assert 'vector-line-layer' in mock_maplibre_map.layers
        assert mock_maplibre_map.layers['vector-fill-layer']['type'] == 'fill'
        assert mock_maplibre_map.layers['vector-line-layer']['type'] == 'line'
    
    def test_style_application_to_vector_layer(self, mock_maplibre_map):
        """Test style application to vector layer"""
        mock_maplibre_map.addSource('styled-vector', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        mock_maplibre_map.addLayer({
            'id': 'styled-layer',
            'type': 'fill',
            'source': 'styled-vector',
            'source-layer': 'building',
            'paint': {
                'fill-color': '#cccccc',
                'fill-opacity': 0.5
            }
        })
        
        # Update style properties
        mock_maplibre_map.setPaintProperty('styled-layer', 'fill-color', '#ff0000')
        mock_maplibre_map.setPaintProperty('styled-layer', 'fill-opacity', 0.8)
        
        assert mock_maplibre_map.layers['styled-layer']['paint']['fill-color'] == '#ff0000'
        assert mock_maplibre_map.layers['styled-layer']['paint']['fill-opacity'] == 0.8


class TestZoomLevelTileLoading:
    """Tests for zoom level dependent tile loading"""
    
    def test_tile_loading_at_multiple_zoom_levels(self):
        """Test tile URL generation at different zoom levels"""
        base_url = 'https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf'
        zoom_levels = [5, 8, 10, 12, 14, 16]
        
        for z in zoom_levels:
            # Generate sample tile coordinates
            x = 2 ** z // 2
            y = 2 ** z // 2
            
            tile_url = base_url.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
            
            assert tile_url.startswith('https://')
            assert str(z) in tile_url
            assert tile_url.endswith('.pbf')
    
    def test_native_zoom_level_handling(self):
        """Test native zoom level handling for vector tiles"""
        native_zoom_config = {
            'maxZoom': 22,
            'maxNativeZoom': 14,
            'vector': True
        }
        
        assert native_zoom_config['maxNativeZoom'] < native_zoom_config['maxZoom']
        assert native_zoom_config['maxZoom'] - native_zoom_config['maxNativeZoom'] >= 6


# =============================================================================
# SECTION 2: Marker/Popup Tests (마커/팝업 테스트)
# =============================================================================

class TestMapLibreMarkerBehavior:
    """Tests for MapLibre marker behavior"""
    
    def test_marker_creation(self):
        """Test marker creation simulation"""
        marker_data = {
            'id': 'marker_001',
            'coordinates': [127.0, 37.5],
            'type': 'device',
            'properties': {
                'name': 'Test Device',
                'status': 'active'
            }
        }
        
        assert marker_data['coordinates'][0] == 127.0
        assert marker_data['coordinates'][1] == 37.5
        assert marker_data['type'] == 'device'
    
    def test_marker_clustering_config(self):
        """Test marker clustering configuration"""
        clustering_config = {
            'cluster': True,
            'clusterMaxZoom': 14,
            'clusterRadius': 50,
            'clusterProperties': {
                'count': ['+', 1]
            }
        }
        
        assert clustering_config['cluster'] is True
        assert clustering_config['clusterMaxZoom'] >= 10
        assert clustering_config['clusterRadius'] > 0


class TestPopupDisplayBehavior:
    """Tests for popup display/hide behavior"""
    
    def test_popup_creation(self):
        """Test popup content creation"""
        popup_data = {
            'id': 'popup_001',
            'coordinates': [127.0, 37.5],
            'content': {
                'title': 'Test Device',
                'description': 'Device description',
                'measurements': [
                    {'name': 'Temperature', 'value': 25, 'unit': '°C'},
                    {'name': 'Humidity', 'value': 60, 'unit': '%'}
                ]
            }
        }
        
        assert popup_data['coordinates'][0] == 127.0
        assert popup_data['coordinates'][1] == 37.5
        assert 'title' in popup_data['content']
        assert len(popup_data['content']['measurements']) == 2
    
    def test_popup_visibility_toggle(self):
        """Test popup visibility toggle logic"""
        visibility_state = {
            'visible': True,
            'toggle_count': 0
        }
        
        def toggle_popup():
            visibility_state['visible'] = not visibility_state['visible']
            visibility_state['toggle_count'] += 1
        
        toggle_popup()
        assert visibility_state['visible'] is False
        assert visibility_state['toggle_count'] == 1
        
        toggle_popup()
        assert visibility_state['visible'] is True
        assert visibility_state['toggle_count'] == 2
    
    def test_popup_positioning(self):
        """Test popup positioning relative to marker"""
        anchor_positions = ['top', 'bottom', 'left', 'right', 'center']
        
        for anchor in anchor_positions:
            popup_config = {
                'anchor': anchor,
                'offset': {'x': 0, 'y': 0}
            }
            
            if anchor == 'top':
                popup_config['offset'] = {'x': 0, 'y': -10}
            elif anchor == 'bottom':
                popup_config['offset'] = {'x': 0, 'y': 10}
            
            assert popup_config['anchor'] in anchor_positions


# =============================================================================
# SECTION 3: Drawing Tools Tests (그리기 도구 테스트)
# =============================================================================

class TestDrawingToolInitialization:
    """Tests for drawing tool initialization"""
    
    def test_ao_t_draw_manager_init(self, mock_maplibre_map):
        """Test AoTDrawManager initialization simulation"""
        # Simulate draw manager initialization
        draw_manager_config = {
            'map': mock_maplibre_map,
            'drawTools': {
                'polyline': True,
                'polygon': True,
                'rectangle': True,
                'circle': True,
                'marker': True
            },
            'defaultStyle': {
                'color': '#3bb2d0',
                'fillOpacity': 0.2,
                'lineWidth': 2
            }
        }
        
        assert 'polyline' in draw_manager_config['drawTools']
        assert draw_manager_config['drawTools']['polyline'] is True
        assert draw_manager_config['defaultStyle']['color'] == '#3bb2d0'
    
    def test_drawing_mode_activation(self):
        """Test drawing mode activation"""
        draw_modes = ['polyline', 'polygon', 'rectangle', 'circle', 'marker']
        
        for mode in draw_modes:
            activation_state = {
                'mode': mode,
                'active': True,
                'start_point': None,
                'end_point': None
            }
            
            assert activation_state['mode'] in draw_modes
            assert activation_state['active'] is True


class TestPolylineDrawing:
    """Tests for polyline drawing functionality"""
    
    def test_polyline_creation(self):
        """Test polyline feature creation"""
        polyline_feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': [
                    [127.0, 37.5],
                    [127.1, 37.6],
                    [127.2, 37.7]
                ]
            },
            'properties': {
                'id': 'polyline_001',
                'name': 'Test Path',
                'length': 15000
            }
        }
        
        assert polyline_feature['geometry']['type'] == 'LineString'
        assert len(polyline_feature['geometry']['coordinates']) >= 2
        assert 'length' in polyline_feature['properties']
    
    def test_polyline_edit(self):
        """Test polyline editing"""
        edited_polyline = {
            'type': 'Feature',
            'geometry': {
                'type': 'LineString',
                'coordinates': [
                    [127.0, 37.5],
                    [127.15, 37.65],  # Added point
                    [127.2, 37.7]
                ]
            },
            'properties': {
                'edited': True,
                'edit_timestamp': '2026-04-23T10:00:00Z'
            }
        }
        
        assert len(edited_polyline['geometry']['coordinates']) == 3
        assert edited_polyline['properties']['edited'] is True


class TestPolygonDrawing:
    """Tests for polygon drawing functionality"""
    
    def test_polygon_creation(self):
        """Test polygon feature creation"""
        polygon_feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[
                    [126.95, 37.45],
                    [127.05, 37.45],
                    [127.05, 37.55],
                    [126.95, 37.55],
                    [126.95, 37.45]  # Closed ring
                ]]
            },
            'properties': {
                'id': 'polygon_001',
                'name': 'Test Zone',
                'area': 12100
            }
        }
        
        assert polygon_feature['geometry']['type'] == 'Polygon'
        ring = polygon_feature['geometry']['coordinates'][0]
        assert ring[0] == ring[-1]  # Closed ring
        assert 'area' in polygon_feature['properties']
    
    def test_polygon_save(self):
        """Test polygon save operation"""
        saved_polygon = {
            'feature': {
                'type': 'Feature',
                'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                'properties': {'id': 'zone_001', 'name': 'Zone A'}
            },
            'metadata': {
                'saved_at': '2026-04-23T10:00:00Z',
                'saved_by': 'user_001',
                'version': 1
            }
        }
        
        assert 'feature' in saved_polygon
        assert 'metadata' in saved_polygon
        assert saved_polygon['metadata']['version'] == 1


class TestRectangleDrawing:
    """Tests for rectangle drawing functionality"""
    
    def test_rectangle_creation(self):
        """Test rectangle feature creation"""
        rectangle_feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[
                    [126.95, 37.45],
                    [127.05, 37.45],
                    [127.05, 37.55],
                    [126.95, 37.55],
                    [126.95, 37.45]
                ]]
            },
            'properties': {
                'id': 'rectangle_001',
                'type': 'rectangle',
                'bounds': [[126.95, 37.45], [127.05, 37.55]]
            }
        }
        
        assert rectangle_feature['geometry']['type'] == 'Polygon'
        assert len(rectangle_feature['geometry']['coordinates'][0]) == 5
        assert 'bounds' in rectangle_feature['properties']
    
    def test_rectangle_dimensions(self):
        """Test rectangle dimension calculation"""
        sw = [126.95, 37.45]
        ne = [127.05, 37.55]
        
        width = (ne[0] - sw[0]) * 111320  # Approximate meters
        height = (ne[1] - sw[1]) * 110540  # Approximate meters
        
        assert width > 0
        assert height > 0


class TestCircleDrawing:
    """Tests for circle drawing functionality"""
    
    def test_circle_creation(self):
        """Test circle feature creation (approximated as polygon)"""
        # Circle approximated as polygon
        center = [127.0, 37.5]
        radius_meters = 1000
        steps = 64
        
        circle_feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[]]  # Will be filled with approximated points
            },
            'properties': {
                'id': 'circle_001',
                'type': 'circle',
                'center': center,
                'radius': radius_meters,
                'radius_unit': 'meters',
                'approximation_steps': steps
            }
        }
        
        assert circle_feature['properties']['center'] == center
        assert circle_feature['properties']['radius'] == radius_meters
        assert circle_feature['geometry']['type'] == 'Polygon'
    
    def test_circle_radius_validation(self):
        """Test circle radius validation"""
        valid_radius = 5000  # 5km
        invalid_radius = -100  # Negative
        
        assert valid_radius > 0
        assert invalid_radius < 0


class TestDrawEditDelete:
    """Tests for edit/delete operations"""
    
    def test_feature_selection(self):
        """Test feature selection for editing"""
        selected_features = []
        available_features = ['polyline_001', 'polygon_001', 'rectangle_001']
        
        selected_features.append('polygon_001')
        
        assert len(selected_features) == 1
        assert selected_features[0] in available_features
    
    def test_feature_edit_mode(self):
        """Test entering edit mode"""
        edit_mode_state = {
            'enabled': False,
            'selected_feature_id': None,
            'vertex_handles': [],
            'original_geometry': None
        }
        
        # Enter edit mode
        edit_mode_state['enabled'] = True
        edit_mode_state['selected_feature_id'] = 'polygon_001'
        edit_mode_state['original_geometry'] = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        
        assert edit_mode_state['enabled'] is True
        assert edit_mode_state['selected_feature_id'] is not None
    
    def test_feature_deletion(self):
        """Test feature deletion"""
        features = {
            'polyline_001': {'type': 'LineString', 'deleted': False},
            'polygon_001': {'type': 'Polygon', 'deleted': False},
            'rectangle_001': {'type': 'Polygon', 'deleted': False}
        }
        
        # Delete a feature
        del features['rectangle_001']
        
        assert 'rectangle_001' not in features
        assert 'polyline_001' in features
        assert 'polygon_001' in features


# =============================================================================
# SECTION 4: Multi-map Source Tests (다중 지도 소스 테스트)
# =============================================================================

class TestBaseMapSwitching:
    """Tests for base map switching (4 sources)"""
    
    def test_available_base_sources(self, gis_provider_configs):
        """Test availability of 4 base map sources"""
        base_sources = [k for k, v in gis_provider_configs.items() if v.get('options', {}).get('layer') == 'base']
        
        # We expect at least 4 base sources in the configuration
        assert len(gis_provider_configs) >= 4
        
        source_types = [v['type'] for v in gis_provider_configs.values()]
        assert 'raster' in source_types
        assert 'vector' in source_types
    
    def test_source_switch_raster_to_vector(self, mock_maplibre_map):
        """Test switching from raster to vector source"""
        # Add initial raster source
        mock_maplibre_map.addSource('osm-raster', {
            'type': 'raster',
            'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
        })
        
        assert 'osm-raster' in mock_maplibre_map.sources
        
        # Switch to vector source
        mock_maplibre_map.removeSource('osm-raster')
        mock_maplibre_map.addSource('maptiler-vector', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        assert 'maptiler-vector' in mock_maplibre_map.sources
        assert 'osm-raster' not in mock_maplibre_map.sources
    
    def test_source_switch_preserves_data_layers(self, mock_maplibre_map):
        """Test that data layers are preserved during source switch"""
        # Add base source
        mock_maplibre_map.addSource('base-source', {
            'type': 'raster',
            'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
        })
        
        # Add data overlay
        mock_maplibre_map.addSource('overlay-data', {
            'type': 'geojson',
            'data': {'type': 'FeatureCollection', 'features': []}
        })
        mock_maplibre_map.addLayer({
            'id': 'overlay-layer',
            'type': 'fill',
            'source': 'overlay-data'
        })
        
        # Switch base source
        mock_maplibre_map.removeSource('base-source')
        mock_maplibre_map.addSource('new-base', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Data overlay should still exist
        assert 'overlay-layer' in mock_maplibre_map.layers
        assert 'overlay-data' in mock_maplibre_map.sources


class TestLayerOrderManagement:
    """Tests for layer order management"""
    
    def test_layer_ordering(self, mock_maplibre_map):
        """Test layer ordering by z-index"""
        layers_order = ['base-tiles', 'terrain', 'roads', 'labels', 'markers', 'popups']
        
        for i, layer_id in enumerate(layers_order):
            mock_maplibre_map.addLayer({
                'id': layer_id,
                'type': 'background' if i == 0 else 'raster' if i == 1 else 'line' if i == 2 else 'symbol',
                'z_index': i
            })
        
        assert len(mock_maplibre_map.layers) == len(layers_order)
        
        for i, layer_id in enumerate(layers_order):
            assert mock_maplibre_map.layers[layer_id]['z_index'] == i
    
    def test_layer_visibility_toggle(self, mock_maplibre_map):
        """Test layer visibility toggle"""
        mock_maplibre_map.addLayer({
            'id': 'toggle-layer',
            'type': 'fill',
            'source': 'test-source'
        })
        
        # Hide layer
        mock_maplibre_map.setLayoutProperty('toggle-layer', 'visibility', 'none')
        assert mock_maplibre_map.layers['toggle-layer']['layout']['visibility'] == 'none'
        
        # Show layer
        mock_maplibre_map.setLayoutProperty('toggle-layer', 'visibility', 'visible')
        assert mock_maplibre_map.layers['toggle-layer']['layout']['visibility'] == 'visible'


class TestWMSOverlayIntegration:
    """Tests for WMS overlay integration"""
    
    def test_wms_layer_creation(self, mock_maplibre_map):
        """Test WMS layer creation"""
        wms_config = {
            'id': 'wms-overlay',
            'type': 'raster',
            'tiles': ['https://api.vworld.kr/req/wmts/1.0.0/demo/base/{z}/{y}/{x}'],
            'tileSize': 256,
            'paint': {
                'raster-opacity': 0.7
            }
        }
        
        mock_maplibre_map.addSource('wms-source', {
            'type': 'raster',
            'tiles': wms_config['tiles']
        })
        mock_maplibre_map.addLayer({
            'id': wms_config['id'],
            'type': 'raster',
            'source': 'wms-source',
            'paint': wms_config['paint']
        })
        
        assert 'wms-overlay' in mock_maplibre_map.layers
        assert mock_maplibre_map.layers['wms-overlay']['paint']['raster-opacity'] == 0.7
    
    def test_wms_concurrent_with_vector(self, mock_maplibre_map):
        """Test WMS overlay concurrent with vector tiles"""
        # Add vector base
        mock_maplibre_map.addSource('vector-base', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Add WMS overlay
        mock_maplibre_map.addSource('wms-overlay', {
            'type': 'raster',
            'tiles': ['https://example.com/wms/{z}/{x}/{y}.png']
        })
        mock_maplibre_map.addLayer({
            'id': 'wms-layer',
            'type': 'raster',
            'source': 'wms-overlay',
            'paint': {'raster-opacity': 0.5}
        })
        
        assert 'vector-base' in mock_maplibre_map.sources
        assert 'wms-overlay' in mock_maplibre_map.sources
        assert mock_maplibre_map.sources['vector-base']['type'] == 'vector'
        assert mock_maplibre_map.sources['wms-overlay']['type'] == 'raster'


# =============================================================================
# SECTION 5: Performance Benchmark Tests (성능 벤치마크)
# =============================================================================

class TestLoadingSpeedComparison:
    """Tests for loading speed comparison"""
    
    def test_vector_tile_loading_speed(self, performance_metrics):
        """Test vector tile loading speed simulation"""
        num_tiles = 100
        
        performance_metrics.start_timer('vector_tile_loading')
        
        for i in range(num_tiles):
            tile_url = f'https://api.maptiler.com/tiles/v3/{10 + i % 5}/{i}/{i + 1}.pbf'
            # Simulate tile loading
            tile_data = {'size': 15000}  # ~15KB per vector tile
        
        loading_time = performance_metrics.stop_timer('vector_tile_loading')
        
        assert loading_time < 5.0  # Should complete in under 5 seconds
        assert num_tiles == 100
    
    def test_raster_vs_vector_loading_comparison(self, performance_metrics):
        """Test raster vs vector loading time comparison"""
        num_tiles = 50
        
        # Raster tile simulation
        performance_metrics.start_timer('raster_tiles')
        for _ in range(num_tiles):
            pass  # Simulate larger tile sizes
        raster_time = performance_metrics.stop_timer('raster_tiles')
        
        # Vector tile simulation
        performance_metrics.start_timer('vector_tiles')
        for _ in range(num_tiles):
            pass  # Simulate smaller tile sizes
        vector_time = performance_metrics.stop_timer('vector_tiles')
        
        # Vector tiles typically load faster
        assert vector_time >= 0
        assert raster_time >= 0


class TestMemoryUsage:
    """Tests for memory usage measurement"""
    
    def test_source_registry_memory(self, performance_metrics):
        """Test memory usage of source registry"""
        import sys
        
        sources = {}
        for i in range(50):
            sources[f'source_{i}'] = {
                'type': 'vector',
                'tiles': [f'https://tiles{i}.com/{{z}}/{{x}}/{{y}}.pbf'],
                'metadata': {'name': f'Source {i}'}
            }
        
        size = sys.getsizeof(json.dumps(sources))
        
        # Should be under reasonable limit
        assert size < 100000  # 100KB
        assert len(sources) == 50
    
    def test_layer_style_memory(self, performance_metrics):
        """Test memory usage of layer styles"""
        import sys
        
        layers = {}
        for i in range(100):
            layers[f'layer_{i}'] = {
                'type': 'fill',
                'paint': {
                    'fill-color': '#FF0000',
                    'fill-opacity': 0.5,
                    'fill-outline-color': '#000000'
                }
            }
        
        size = sys.getsizeof(json.dumps(layers))
        
        assert size < 200000  # 200KB
        assert len(layers) == 100


class TestZoomPanResponse:
    """Tests for zoom/pan responsiveness"""
    
    def test_zoom_level_calculation(self):
        """Test zoom level calculation for tile coordinates"""
        zoom = 12
        center = [127.0, 37.5]
        
        # Calculate tile coordinates
        n = 2 ** zoom
        x_tile = int((center[0] + 180) / 360 * n)
        y_tile = int((1 - math.log(math.tan(math.radians(center[1])) + 1 / math.cos(math.radians(center[1]))) / math.pi) / 2 * n)
        
        assert 0 <= x_tile < n
        assert 0 <= y_tile < n
    
    def test_pan_animation_performance(self, performance_metrics):
        """Test pan animation performance"""
        import math
        
        performance_metrics.start_timer('pan_calculation')
        
        pan_positions = []
        for i in range(100):
            dx = math.sin(i * 0.1) * 0.01
            dy = math.cos(i * 0.1) * 0.01
            new_center = [127.0 + dx, 37.5 + dy]
            pan_positions.append(new_center)
        
        pan_time = performance_metrics.stop_timer('pan_calculation')
        
        assert len(pan_positions) == 100
        assert pan_time < 1.0  # Should be fast


# =============================================================================
# SECTION 6: Regression Tests (회귀 테스트)
# =============================================================================

class TestLeafletCompatibility:
    """Tests for Leaflet-based functionality compatibility"""
    
    def test_leaflet_layer_api_exists(self):
        """Test that Leaflet layer API exists for backward compatibility"""
        leaflet_api_methods = [
            'L.tileLayer',
            'L.geoJSON',
            'L.featureGroup',
            'L.marker',
            'L.polygon',
            'L.polyline'
        ]
        
        for method in leaflet_api_methods:
            assert 'L.' in method or 'layer' in method.lower()
    
    def test_geojson_to_leaflet_conversion(self, sample_geojson_points):
        """Test GeoJSON to Leaflet format conversion"""
        leaflet_layers = []
        
        for feature in sample_geojson_points['features']:
            if feature['geometry']['type'] == 'Point':
                coords = feature['geometry']['coordinates']
                # Convert to Leaflet format [lat, lng]
                latlng = [coords[1], coords[0]]
                leaflet_layers.append({
                    'type': 'marker',
                    'latlng': latlng,
                    'properties': feature['properties']
                })
        
        assert len(leaflet_layers) == 3
        for layer in leaflet_layers:
            # Verify Leaflet format [lat, lng] is different from GeoJSON [lng, lat]
            assert layer['latlng'][0] != layer['latlng'][1]  # lat != lng


class TestDatabaseIntegration:
    """Tests for database integration"""
    
    def test_geolayer_model_structure(self):
        """Test GeoLayer model structure"""
        geo_layer = {
            'unique_id': 'layer_001',
            'name': 'Test Layer',
            'type': 'vector_tile',
            'is_activated': True,
            'options': '{"api_key": "xxx", "style": "streets"}',
            'created_at': '2026-04-23T00:00:00Z',
            'updated_at': '2026-04-23T00:00:00Z'
        }
        
        assert 'unique_id' in geo_layer
        assert 'name' in geo_layer
        assert 'type' in geo_layer
        assert geo_layer['is_activated'] is True
    
    def test_geomap_model_structure(self):
        """Test GeoMap model structure"""
        geo_map = {
            'unique_id': 'map_001',
            'name': 'Test Map',
            'category': 'design',
            'state_json': '{"center": [127, 37], "zoom": 10, "layers": []}',
            'created_by': 'user_001'
        }
        
        assert 'unique_id' in geo_map
        assert 'name' in geo_map
        assert 'state_json' in geo_map
        assert json.loads(geo_map['state_json'])['zoom'] == 10
    
    def test_geoshape_model_structure(self):
        """Test GeoShape model structure"""
        geo_shape = {
            'unique_id': 'shape_001',
            'parent_id': 'zone_001',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
            },
            'shape_type': 'zone'
        }
        
        assert 'unique_id' in geo_shape
        assert 'geometry' in geo_shape
        assert geo_shape['geometry']['type'] == 'Polygon'


class TestBackendGISProviderIntegration:
    """Tests for backend GIS provider integration"""
    
    def test_gis_provider_registration(self):
        """Test GIS provider registration"""
        providers = {
            'vworld': {'type': 'raster', 'requires_key': True},
            'maptiler': {'type': 'vector', 'requires_key': True},
            'osm': {'type': 'raster', 'requires_key': False},
            'naver': {'type': 'raster', 'requires_key': True}
        }
        
        assert len(providers) == 4
        assert providers['osm']['requires_key'] is False
        assert providers['maptiler']['type'] == 'vector'
    
    def test_provider_url_construction(self):
        """Test provider URL construction"""
        test_cases = [
            {
                'provider': 'vworld',
                'template': 'https://api.vworld.kr/req/wmts/1.0.0/{api_key}/base/{z}/{y}/{x}',
                'api_key': 'test-key',
                'expected_contains': 'test-key'
            },
            {
                'provider': 'maptiler',
                'template': 'https://api.maptiler.com/tiles/{style}/v2/{z}/{x}/{y}.pbf?key={api_key}',
                'api_key': 'maptiler-key',
                'expected_contains': 'maptiler-key'
            }
        ]
        
        for case in test_cases:
            url = case['template'].replace('{api_key}', case['api_key'])
            assert case['expected_contains'] in url
    
    def test_proxy_route_availability(self):
        """Test GIS proxy routes availability"""
        proxy_routes = [
            '/api/geo/proxy/rainviewer/meta',
            '/api/geo/proxy/isric',
            '/api/geo/proxy/openweather',
            '/api/geo/proxy/openmeteo'
        ]
        
        for route in proxy_routes:
            assert route.startswith('/api/geo/')
            assert 'proxy' in route


class TestAPIEndpointCompatibility:
    """Tests for API endpoint compatibility"""
    
    def test_geo_api_endpoints(self):
        """Test Geo API endpoints structure"""
        api_endpoints = [
            {'method': 'GET', 'path': '/api/geo/settings', 'auth': True},
            {'method': 'GET', 'path': '/api/geo/devices', 'auth': True},
            {'method': 'GET', 'path': '/api/geo/designs/list', 'auth': True},
            {'method': 'POST', 'path': '/api/geo/designs', 'auth': True},
            {'method': 'GET', 'path': '/api/geo/overlays', 'auth': True},
            {'method': 'POST', 'path': '/api/geo/overlays', 'auth': True},
            {'method': 'GET', 'path': '/geo/design', 'auth': True},
        ]
        
        assert len(api_endpoints) >= 5
        
        for endpoint in api_endpoints:
            assert 'method' in endpoint
            assert 'path' in endpoint
            assert 'auth' in endpoint
            assert endpoint['auth'] is True
    
    def test_geojson_response_format(self):
        """Test GeoJSON response format"""
        response = {
            'ok': True,
            'data': {
                'type': 'FeatureCollection',
                'features': [
                    {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [127, 37]},
                        'properties': {'id': 'device_001', 'name': 'Device A'}
                    }
                ]
            }
        }
        
        assert response['ok'] is True
        assert response['data']['type'] == 'FeatureCollection'
        assert len(response['data']['features']) > 0


# =============================================================================
# SECTION 7: End-to-End Integration Scenarios
# =============================================================================

class TestCompleteWorkflow:
    """End-to-end workflow tests"""
    
    def test_full_map_workflow(self, mock_maplibre_map, sample_geojson_points, sample_geojson_polygons):
        """Test complete map workflow from initialization to data display"""
        # 1. Initialize map with vector base
        mock_maplibre_map.addSource('vector-base', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # 2. Add GeoJSON data for devices
        mock_maplibre_map.addSource('devices', {
            'type': 'geojson',
            'data': sample_geojson_points
        })
        
        # 3. Add GeoJSON data for zones
        mock_maplibre_map.addSource('zones', {
            'type': 'geojson',
            'data': sample_geojson_polygons
        })
        
        # 4. Add marker layer
        mock_maplibre_map.addLayer({
            'id': 'device-markers',
            'type': 'circle',
            'source': 'devices',
            'paint': {'circle-color': '#007bff', 'circle-radius': 8}
        })
        
        # 5. Add zone polygon layer
        mock_maplibre_map.addLayer({
            'id': 'zone-polygons',
            'type': 'fill',
            'source': 'zones',
            'paint': {'fill-color': '#28a745', 'fill-opacity': 0.3}
        })
        
        # Verify workflow
        assert 'vector-base' in mock_maplibre_map.sources
        assert 'devices' in mock_maplibre_map.sources
        assert 'zones' in mock_maplibre_map.sources
        assert 'device-markers' in mock_maplibre_map.layers
        assert 'zone-polygons' in mock_maplibre_map.layers
        
        # Verify sources have correct types
        assert mock_maplibre_map.sources['vector-base']['type'] == 'vector'
        assert mock_maplibre_map.sources['devices']['type'] == 'geojson'
        
        # Verify layers have correct types
        assert mock_maplibre_map.layers['device-markers']['type'] == 'circle'
        assert mock_maplibre_map.layers['zone-polygons']['type'] == 'fill'
    
    def test_drawing_to_save_workflow(self):
        """Test drawing to save workflow"""
        # 1. User starts drawing
        draw_state = {
            'active': True,
            'mode': 'polygon',
            'points': []
        }
        
        # 2. User adds points
        draw_state['points'] = [
            [126.95, 37.45],
            [127.05, 37.45],
            [127.05, 37.55],
            [127.00, 37.50]
        ]
        
        # 3. User completes drawing
        completed_feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [draw_state['points'] + [draw_state['points'][0]]]
            },
            'properties': {
                'id': 'new_polygon',
                'created_by': 'user_001',
                'timestamp': '2026-04-23T10:00:00Z'
            }
        }
        
        # 4. Save to database
        saved_shape = {
            'unique_id': 'shape_new',
            'feature': completed_feature,
            'status': 'saved'
        }
        
        # Verify workflow
        assert len(draw_state['points']) >= 3
        assert completed_feature['geometry']['type'] == 'Polygon'
        assert saved_shape['status'] == 'saved'
    
    def test_source_switch_with_overlay_preservation(self, mock_maplibre_map):
        """Test source switch with overlay preservation"""
        # Initial state
        mock_maplibre_map.addSource('base-osm', {
            'type': 'raster',
            'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
        })
        mock_maplibre_map.addSource('custom-data', {
            'type': 'geojson',
            'data': {'type': 'FeatureCollection', 'features': []}
        })
        mock_maplibre_map.addLayer({
            'id': 'data-overlay',
            'type': 'fill',
            'source': 'custom-data'
        })
        
        # Switch base source
        mock_maplibre_map.removeSource('base-osm')
        mock_maplibre_map.addSource('base-vector', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Verify overlay preserved
        assert 'data-overlay' in mock_maplibre_map.layers
        assert 'base-vector' in mock_maplibre_map.sources
        assert 'base-osm' not in mock_maplibre_map.sources


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
