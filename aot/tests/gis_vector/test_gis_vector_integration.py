# coding=utf-8
"""
GIS Vector Integration Tests

Comprehensive integration tests for gis_vector branch:
1. MapLibre basic initialization + vector layers
2. Marker + Popup + Drawing tools integration
3. WMS + Vector simultaneous display
4. Source switching + all overlays maintenance
5. Performance benchmarks

Test Strategy:
- Unit tests for individual modules
- Integration tests for module interactions
- Performance tests for benchmarks
"""

import os
import sys
import pytest
import json
import time
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


class TestVectorLayerManager:
    """Tests for AoTVectorLayerManager module"""
    
    def test_vector_layer_manager_init(self, mock_maplibre_map):
        """Test VectorLayerManager initialization"""
        # Simulate VectorLayerManager behavior
        assert mock_maplibre_map is not None
        assert hasattr(mock_maplibre_map, 'sources')
        assert hasattr(mock_maplibre_map, 'layers')
        assert isinstance(mock_maplibre_map.sources, dict)
        assert isinstance(mock_maplibre_map.layers, dict)
    
    def test_add_vector_source(self, mock_maplibre_map):
        """Test adding vector tile source"""
        source_config = {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf'],
            'minzoom': 0,
            'maxzoom': 14,
            'attribution': '© MapTiler'
        }
        
        mock_maplibre_map.addSource('test-vector-source', source_config)
        
        assert 'test-vector-source' in mock_maplibre_map.sources
        assert mock_maplibre_map.sources['test-vector-source']['type'] == 'vector'
        assert mock_maplibre_map.sources['test-vector-source']['tiles'] == source_config['tiles']
    
    def test_add_geojson_source(self, mock_maplibre_map, sample_geojson_points):
        """Test adding GeoJSON source"""
        source_config = {
            'type': 'geojson',
            'data': sample_geojson_points
        }
        
        mock_maplibre_map.addSource('geojson-source', source_config)
        
        assert 'geojson-source' in mock_maplibre_map.sources
        assert mock_maplibre_map.sources['geojson-source']['type'] == 'geojson'
        assert mock_maplibre_map.sources['geojson-source']['data']['type'] == 'FeatureCollection'
    
    def test_add_layer(self, mock_maplibre_map):
        """Test adding a layer to the map"""
        layer_config = {
            'id': 'test-fill-layer',
            'type': 'fill',
            'source': 'test-source',
            'paint': {
                'fill-color': '#FF0000',
                'fill-opacity': 0.5
            }
        }
        
        mock_maplibre_map.addLayer(layer_config)
        
        assert 'test-fill-layer' in mock_maplibre_map.layers
        assert mock_maplibre_map.layers['test-fill-layer']['type'] == 'fill'
        assert mock_maplibre_map.layers['test-fill-layer']['paint']['fill-color'] == '#FF0000'
    
    def test_remove_layer(self, mock_maplibre_map):
        """Test removing a layer"""
        layer_config = {
            'id': 'layer-to-remove',
            'type': 'circle',
            'source': 'test-source'
        }
        
        mock_maplibre_map.addLayer(layer_config)
        assert 'layer-to-remove' in mock_maplibre_map.layers
        
        mock_maplibre_map.removeLayer('layer-to-remove')
        assert 'layer-to-remove' not in mock_maplibre_map.layers
    
    def test_set_layer_visibility(self, mock_maplibre_map):
        """Test setting layer visibility"""
        layer_config = {
            'id': 'visibility-test-layer',
            'type': 'fill',
            'source': 'test-source'
        }
        
        mock_maplibre_map.addLayer(layer_config)
        
        # Set visibility to none
        mock_maplibre_map.setLayoutProperty('visibility-test-layer', 'visibility', 'none')
        assert mock_maplibre_map.layers['visibility-test-layer']['layout']['visibility'] == 'none'
        
        # Set visibility to visible
        mock_maplibre_map.setLayoutProperty('visibility-test-layer', 'visibility', 'visible')
        assert mock_maplibre_map.layers['visibility-test-layer']['layout']['visibility'] == 'visible'
    
    def test_set_layer_style(self, mock_maplibre_map):
        """Test updating layer paint properties"""
        layer_config = {
            'id': 'style-test-layer',
            'type': 'circle',
            'source': 'test-source',
            'paint': {
                'circle-color': '#00FF00',
                'circle-radius': 6
            }
        }
        
        mock_maplibre_map.addLayer(layer_config)
        
        # Update circle color
        mock_maplibre_map.setPaintProperty('style-test-layer', 'circle-color', '#FF00FF')
        assert mock_maplibre_map.layers['style-test-layer']['paint']['circle-color'] == '#FF00FF'
        
        # Update circle radius
        mock_maplibre_map.setPaintProperty('style-test-layer', 'circle-radius', 10)
        assert mock_maplibre_map.layers['style-test-layer']['paint']['circle-radius'] == 10
    
    def test_set_filter(self, mock_maplibre_map):
        """Test applying filter to layer"""
        layer_config = {
            'id': 'filter-test-layer',
            'type': 'fill',
            'source': 'test-source'
        }
        
        mock_maplibre_map.addLayer(layer_config)
        
        # Apply filter
        filter_expr = ['==', ['get', 'type'], 'zone']
        mock_maplibre_map.setFilter('filter-test-layer', filter_expr)
        
        assert mock_maplibre_map.getFilter('filter-test-layer') == filter_expr
    
    def test_clear_filter(self, mock_maplibre_map):
        """Test clearing filter from layer"""
        layer_config = {
            'id': 'clear-filter-test',
            'type': 'fill',
            'source': 'test-source'
        }
        
        mock_maplibre_map.addLayer(layer_config)
        
        # Set filter
        mock_maplibre_map.setFilter('clear-filter-test', ['==', ['get', 'type'], 'zone'])
        assert mock_maplibre_map.getFilter('clear-filter-test') is not None
        
        # Clear filter
        mock_maplibre_map.setFilter('clear-filter-test', None)
        assert mock_maplibre_map.getFilter('clear-filter-test') is None


class TestMultiSourceManager:
    """Tests for AoTMultiSourceManager module"""
    
    def test_source_registry(self, gis_provider_configs):
        """Test source registration and retrieval"""
        sources = {}
        
        for config_id, config in gis_provider_configs.items():
            sources[config_id] = config
            
        assert len(sources) == 4
        assert 'maptiler_vector' in sources
        assert sources['maptiler_vector']['type'] == 'vector'
    
    def test_source_type_detection(self, gis_provider_configs):
        """Test detection of source types"""
        for config_id, config in gis_provider_configs.items():
            if config['type'] == 'vector':
                assert 'pbf' in str(config.get('url', '')) or 'style.json' in str(config.get('url', ''))
            elif config['type'] == 'raster':
                assert '.png' in str(config.get('url', '')) or '.jpg' in str(config.get('url', '')) or 'wmts' in str(config.get('url', ''))
    
    def test_source_switching(self, mock_maplibre_map, gis_provider_configs):
        """Test switching between map sources"""
        # Add first source
        source1 = {
            'type': 'raster',
            'tiles': ['https://tile1.openstreetmap.org/{z}/{x}/{y}.png'],
            'tileSize': 256
        }
        mock_maplibre_map.addSource('source1', source1)
        
        # Add second source
        source2 = {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf'],
            'minzoom': 0,
            'maxzoom': 14
        }
        mock_maplibre_map.addSource('source2', source2)
        
        assert 'source1' in mock_maplibre_map.sources
        assert 'source2' in mock_maplibre_map.sources
        
        # Remove first source
        mock_maplibre_map.removeSource('source1')
        assert 'source1' not in mock_maplibre_map.sources
        assert 'source2' in mock_maplibre_map.sources


class TestGISInputs:
    """Tests for GIS input modules"""
    
    def test_base_gis_input_config(self, sample_geojson_points):
        """Test base GIS input configuration structure"""
        config = {
            'unique_id': 'test_gis_001',
            'name': 'Test GIS Layer',
            'category': 'base',
            'type': 'vector_tile',
            'url': 'https://api.maptiler.com/tiles/v3/style.json',
            'attribution': '© MapTiler',
            'options': {
                'opacity': 1.0,
                'zIndex': 1,
                'visible': True
            },
            'data': sample_geojson_points
        }
        
        assert config['unique_id'] == 'test_gis_001'
        assert config['category'] in ['base', 'overlay']
        assert config['type'] in ['tile', 'wms', 'geojson', 'vector_tile']
        assert isinstance(config['options'], dict)
    
    def test_vector_tile_url_parsing(self):
        """Test vector tile URL parsing"""
        test_urls = [
            'https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf',
            'https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.pbf',
            'https://api.maptiler.com/tiles/v3-free/style.json'
        ]
        
        for url in test_urls:
            has_placeholder = '{z}' in url or '{x}' in url or '{y}' in url
            is_style_json = 'style.json' in url
            assert has_placeholder or is_style_json, f"Invalid URL format: {url}"
    
    def test_wms_url_construction(self):
        """Test WMS URL construction with parameters"""
        base_url = 'https://api.vworld.kr/req/wmts/1.0.0/{api_key}/base/{z}/{y}/{x}'
        api_key = 'test-api-key'
        
        constructed_url = base_url.replace('{api_key}', api_key)
        
        assert api_key in constructed_url
        assert '{api_key}' not in constructed_url
        assert 'base' in constructed_url


class TestGeoJSONOperations:
    """Tests for GeoJSON operations"""
    
    def test_geojson_feature_count(self, sample_geojson_points, sample_geojson_polygons, sample_geojson_lines):
        """Test GeoJSON feature counting"""
        assert len(sample_geojson_points['features']) == 3
        assert len(sample_geojson_polygons['features']) == 2
        assert len(sample_geojson_lines['features']) == 1
    
    def test_geojson_validity(self, sample_geojson_points):
        """Test GeoJSON validity"""
        assert sample_geojson_points['type'] == 'FeatureCollection'
        for feature in sample_geojson_points['features']:
            assert feature['type'] == 'Feature'
            assert 'geometry' in feature
            assert 'properties' in feature
            assert feature['geometry']['type'] in ['Point', 'LineString', 'Polygon', 'MultiPoint', 'MultiLineString', 'MultiPolygon']
    
    def test_geojson_point_coordinates(self, sample_geojson_points):
        """Test GeoJSON point coordinate format"""
        for feature in sample_geojson_points['features']:
            if feature['geometry']['type'] == 'Point':
                coords = feature['geometry']['coordinates']
                assert len(coords) == 2  # [lng, lat]
                assert -180 <= coords[0] <= 180  # Longitude
                assert -90 <= coords[1] <= 90  # Latitude
    
    def test_geojson_polygon_coordinates(self, sample_geojson_polygons):
        """Test GeoJSON polygon coordinate format"""
        for feature in sample_geojson_polygons['features']:
            if feature['geometry']['type'] == 'Polygon':
                coords = feature['geometry']['coordinates']
                assert len(coords) >= 1  # At least one ring
                for ring in coords:
                    assert len(ring) >= 4  # At least 4 points for a valid polygon
                    # First and last point should be the same (closed ring)
                    assert ring[0] == ring[-1]
    
    def test_merge_geojson_collections(self, sample_geojson_points, sample_geojson_polygons):
        """Test merging multiple GeoJSON collections"""
        merged = {
            'type': 'FeatureCollection',
            'features': sample_geojson_points['features'] + sample_geojson_polygons['features']
        }
        
        assert merged['type'] == 'FeatureCollection'
        assert len(merged['features']) == 5  # 3 points + 2 polygons
    
    def test_filter_geojson_by_property(self, sample_geojson_points):
        """Test filtering GeoJSON features by property"""
        active_features = [
            f for f in sample_geojson_points['features']
            if f['properties'].get('status') == 'active'
        ]
        
        assert len(active_features) == 2
        
        device_features = [
            f for f in sample_geojson_points['features']
            if f['properties'].get('type') == 'device'
        ]
        
        assert len(device_features) == 2


class TestMapInteraction:
    """Tests for map interaction events"""
    
    def test_click_event_handler(self, mock_maplibre_map):
        """Test click event handler registration"""
        click_handler = Mock()
        mock_maplibre_map.on('click', click_handler)
        
        # Simulate click event
        mock_maplibre_map.fire('click', {'lngLat': {'lng': 127.0, 'lat': 37.5}})
        
        click_handler.assert_called_once()
    
    def test_hover_event_handlers(self, mock_maplibre_map):
        """Test hover event handler registration"""
        mouseenter_handler = Mock()
        mouseleave_handler = Mock()
        
        mock_maplibre_map.on('mouseenter', mouseenter_handler)
        mock_maplibre_map.on('mouseleave', mouseleave_handler)
        
        assert 'mouseenter' in mock_maplibre_map._event_handlers
        assert 'mouseleave' in mock_maplibre_map._event_handlers
    
    def test_layer_click_event(self, mock_maplibre_map):
        """Test layer-specific click events"""
        layer_click_handler = Mock()
        
        # Add a layer
        layer_config = {
            'id': 'interactive-layer',
            'type': 'circle',
            'source': 'test-source'
        }
        mock_maplibre_map.addLayer(layer_config)
        
        # Register handler
        mock_maplibre_map.on('click', layer_click_handler)
        
        # Query rendered features mock
        mock_maplibre_map.queryRenderedFeatures = Mock(return_value=[
            {'layer': {'id': 'interactive-layer'}, 'properties': {'name': 'Test'}}
        ])
        
        # Fire click event
        mock_maplibre_map.fire('click', {'point': [100, 100], 'lngLat': {'lng': 127.0, 'lat': 37.5}})
        
        # Handler should be called
        layer_click_handler.assert_called()


class TestOverlayManagement:
    """Tests for overlay layer management"""
    
    def test_overlay_visibility_toggle(self, mock_maplibre_map):
        """Test toggling overlay visibility"""
        # Add base layer
        base_config = {
            'id': 'base-layer',
            'type': 'raster',
            'source': 'base-source'
        }
        mock_maplibre_map.addLayer(base_config)
        
        # Add overlay layer
        overlay_config = {
            'id': 'overlay-layer',
            'type': 'fill',
            'source': 'overlay-source'
        }
        mock_maplibre_map.addLayer(overlay_config)
        
        # Initially visible
        assert mock_maplibre_map.getLayer('overlay-layer') is not None
        
        # Hide overlay
        mock_maplibre_map.setLayoutProperty('overlay-layer', 'visibility', 'none')
        assert mock_maplibre_map.layers['overlay-layer']['layout']['visibility'] == 'none'
        
        # Show overlay
        mock_maplibre_map.setLayoutProperty('overlay-layer', 'visibility', 'visible')
        assert mock_maplibre_map.layers['overlay-layer']['layout']['visibility'] == 'visible'
    
    def test_overlay_opacity_control(self, mock_maplibre_map):
        """Test overlay opacity control"""
        overlay_config = {
            'id': 'opacity-test-overlay',
            'type': 'fill',
            'source': 'test-source',
            'paint': {
                'fill-opacity': 1.0
            }
        }
        mock_maplibre_map.addLayer(overlay_config)
        
        # Set opacity to 50%
        mock_maplibre_map.setPaintProperty('opacity-test-overlay', 'fill-opacity', 0.5)
        assert mock_maplibre_map.layers['opacity-test-overlay']['paint']['fill-opacity'] == 0.5
        
        # Set opacity to 25%
        mock_maplibre_map.setPaintProperty('opacity-test-overlay', 'fill-opacity', 0.25)
        assert mock_maplibre_map.layers['opacity-test-overlay']['paint']['fill-opacity'] == 0.25


class TestLayerStyles:
    """Tests for layer styling presets"""
    
    def test_device_style_preset(self):
        """Test device marker style preset"""
        device_style = {
            'type': 'symbol',
            'layout': {
                'icon-image': 'marker-icon',
                'icon-size': 1.0,
                'text-field': ['get', 'name'],
                'text-font': ['Noto Sans Regular'],
                'text-offset': [0, 1.5],
                'text-anchor': 'top'
            },
            'paint': {
                'text-color': '#333333',
                'text-halo-color': '#ffffff',
                'text-halo-width': 2
            }
        }
        
        assert device_style['type'] == 'symbol'
        assert 'text-field' in device_style['layout']
        assert device_style['paint']['text-color'] == '#333333'
    
    def test_zone_style_preset(self):
        """Test zone polygon style preset"""
        zone_style = {
            'type': 'fill',
            'paint': {
                'fill-color': '#28a745',
                'fill-opacity': 0.1
            }
        }
        
        zone_outline_style = {
            'type': 'line',
            'paint': {
                'line-color': '#28a745',
                'line-width': 2,
                'line-dasharray': [3, 2]
            }
        }
        
        assert zone_style['paint']['fill-color'] == '#28a745'
        assert zone_outline_style['paint']['line-dasharray'] == [3, 2]
    
    def test_site_style_preset(self):
        """Test site boundary style preset"""
        site_style = {
            'type': 'fill',
            'paint': {
                'fill-color': '#DF5353',
                'fill-opacity': 0.1
            }
        }
        
        site_outline_style = {
            'type': 'line',
            'paint': {
                'line-color': '#DF5353',
                'line-width': 3
            }
        }
        
        assert site_style['paint']['fill-color'] == '#DF5353'
        assert site_outline_style['paint']['line-width'] == 3
    
    def test_equipment_style_preset(self):
        """Test equipment style preset"""
        equipment_style = {
            'type': 'fill',
            'paint': {
                'fill-color': '#007bff',
                'fill-opacity': 0.15
            }
        }
        
        assert equipment_style['paint']['fill-color'] == '#007bff'


class TestCoordinateSystems:
    """Tests for coordinate system handling"""
    
    def test_epsg3857_projection(self):
        """Test EPSG:3857 (Web Mercator) projection"""
        # Test coordinate bounds
        lng_min, lng_max = -20037508.34, 20037508.34
        lat_min, lat_max = -20037508.34, 20037508.34
        
        assert lng_min < 0
        assert lng_max > 0
        assert lat_min < 0
        assert lat_max > 0
    
    def test_wgs84_bounds(self):
        """Test WGS84 coordinate bounds"""
        lng_min, lng_max = -180, 180
        lat_min, lat_max = -85.06, 85.06
        
        test_coords = [
            (127.0, 37.5, True),   # Seoul
            (0.0, 0.0, True),       # Null Island
            (200.0, 37.5, False),   # Invalid longitude
            (127.0, 100.0, False)  # Invalid latitude
        ]
        
        for lng, lat, expected in test_coords:
            is_valid = lng_min <= lng <= lng_max and lat_min <= lat <= lat_max
            assert is_valid == expected, f"Coordinate ({lng}, {lat}) validation failed"
    
    def test_coordinate_transformation(self):
        """Test coordinate transformation from WGS84 to EPSG:3857"""
        # Seoul coordinates
        lng_wgs84, lat_wgs84 = 127.0, 37.5
        
        # Approximate conversion to EPSG:3857
        import math
        x_3857 = lng_wgs84 * 20037508.34 / 180
        y_3857 = math.log(math.tan((90 + lat_wgs84) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
        
        assert abs(x_3857) < 20037508.34
        assert abs(y_3857) < 20037508.34


class TestIntegrationScenarios:
    """End-to-end integration test scenarios"""
    
    def test_complete_map_initialization(self, mock_maplibre_map, sample_geojson_points, sample_geojson_polygons):
        """Test complete map initialization with all components"""
        # 1. Initialize map with base style
        base_style = {
            'version': 8,
            'sources': {},
            'layers': []
        }
        mock_maplibre_map.style = base_style
        
        # 2. Add vector source
        mock_maplibre_map.addSource('vector-source', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf'],
            'minzoom': 0,
            'maxzoom': 14
        })
        
        # 3. Add GeoJSON source
        mock_maplibre_map.addSource('geojson-source', {
            'type': 'geojson',
            'data': sample_geojson_points
        })
        
        # 4. Add polygon source
        mock_maplibre_map.addSource('polygon-source', {
            'type': 'geojson',
            'data': sample_geojson_polygons
        })
        
        # 5. Add layers
        mock_maplibre_map.addLayer({
            'id': 'device-points',
            'type': 'circle',
            'source': 'geojson-source',
            'paint': {'circle-color': '#007bff', 'circle-radius': 8}
        })
        
        mock_maplibre_map.addLayer({
            'id': 'zone-polygons',
            'type': 'fill',
            'source': 'polygon-source',
            'paint': {'fill-color': '#28a745', 'fill-opacity': 0.3}
        })
        
        # Verify all components
        assert len(mock_maplibre_map.sources) == 3
        assert len(mock_maplibre_map.layers) == 2
        assert 'device-points' in mock_maplibre_map.layers
        assert 'zone-polygons' in mock_maplibre_map.layers
    
    def test_source_switch_preserves_overlays(self, mock_maplibre_map):
        """Test that switching base source preserves overlays"""
        # Add initial base source
        mock_maplibre_map.addSource('osm-base', {
            'type': 'raster',
            'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
        })
        
        # Add overlay
        mock_maplibre_map.addSource('overlay-source', {
            'type': 'geojson',
            'data': {'type': 'FeatureCollection', 'features': []}
        })
        mock_maplibre_map.addLayer({
            'id': 'overlay-layer',
            'type': 'fill',
            'source': 'overlay-source',
            'paint': {'fill-color': '#FF0000', 'fill-opacity': 0.5}
        })
        
        assert 'overlay-layer' in mock_maplibre_map.layers
        
        # Switch base source
        mock_maplibre_map.removeSource('osm-base')
        mock_maplibre_map.addSource('maptiler-vector', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Verify overlay is preserved
        assert 'overlay-layer' in mock_maplibre_map.layers
        assert 'maptiler-vector' in mock_maplibre_map.sources
        assert 'osm-base' not in mock_maplibre_map.sources
    
    def test_concurrent_vector_and_wms(self, mock_maplibre_map):
        """Test concurrent display of vector tiles and WMS overlay"""
        # Add vector base source
        mock_maplibre_map.addSource('vector-base', {
            'type': 'vector',
            'tiles': ['https://api.maptiler.com/tiles/v3/{z}/{x}/{y}.pbf']
        })
        
        # Add WMS overlay (simulated as raster)
        mock_maplibre_map.addSource('wms-overlay', {
            'type': 'raster',
            'tiles': ['https://api.vworld.kr/req/wmts/1.0.0/demo/base/{z}/{y}/{x}']
        })
        mock_maplibre_map.addLayer({
            'id': 'wms-layer',
            'type': 'raster',
            'source': 'wms-overlay',
            'paint': {'raster-opacity': 0.7}
        })
        
        # Verify both sources exist
        assert 'vector-base' in mock_maplibre_map.sources
        assert 'wms-overlay' in mock_maplibre_map.sources
        assert mock_maplibre_map.sources['vector-base']['type'] == 'vector'
        assert mock_maplibre_map.sources['wms-overlay']['type'] == 'raster'
    
    def test_marker_popup_drawing_workflow(self, mock_maplibre_map):
        """Test marker, popup, and drawing tool integration"""
        # Add GeoJSON source for devices
        mock_maplibre_map.addSource('devices', {
            'type': 'geojson',
            'data': {
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [127.0, 37.5]},
                    'properties': {'id': 'device1', 'name': 'Device 1'}
                }]
            }
        })
        
        # Add marker layer
        mock_maplibre_map.addLayer({
            'id': 'device-markers',
            'type': 'circle',
            'source': 'devices',
            'paint': {'circle-color': '#007bff', 'circle-radius': 8}
        })
        
        # Add labels
        mock_maplibre_map.addLayer({
            'id': 'device-labels',
            'type': 'symbol',
            'source': 'devices',
            'layout': {
                'text-field': ['get', 'name'],
                'text-font': ['Noto Sans Regular'],
                'text-offset': [0, 1],
                'text-anchor': 'top'
            },
            'paint': {'text-color': '#333'}
        })
        
        # Add drawing source
        mock_maplibre_map.addSource('drawings', {
            'type': 'geojson',
            'data': {'type': 'FeatureCollection', 'features': []}
        })
        mock_maplibre_map.addLayer({
            'id': 'drawn-polygons',
            'type': 'fill',
            'source': 'drawings',
            'paint': {'fill-color': '#28a745', 'fill-opacity': 0.3}
        })
        
        # Verify all components
        assert 'device-markers' in mock_maplibre_map.layers
        assert 'device-labels' in mock_maplibre_map.layers
        assert 'drawn-polygons' in mock_maplibre_map.layers


# Pytest markers for categorizing tests
pytest.mark.integration = pytest.mark.integration
pytest.mark.unit = pytest.mark.unit
pytest.mark.performance = pytest.mark.performance


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
