"""
Pytest configuration and fixtures for GIS Vector Integration Tests

This module provides:
- Test fixtures for GIS inputs
- Flask test client configuration
- Mock data generators
- Performance measurement utilities
"""

import os
import sys
import pytest
import json
from typing import Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope='session')
def app_config():
    """Flask application configuration for testing"""
    return {
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key',
        'GIS_VECTOR_MODE': True,
        'MAPLIBRE_ENABLED': True
    }


@pytest.fixture(scope='session')
def sample_geojson_points():
    """Sample GeoJSON Point features for testing"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [127.0, 37.5]
                },
                "properties": {
                    "id": "device_001",
                    "name": "Test Device A",
                    "type": "device",
                    "status": "active"
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [127.1, 37.6]
                },
                "properties": {
                    "id": "device_002",
                    "name": "Test Device B",
                    "type": "device",
                    "status": "inactive"
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [126.9, 37.4]
                },
                "properties": {
                    "id": "sensor_001",
                    "name": "Temperature Sensor",
                    "type": "sensor",
                    "status": "active"
                }
            }
        ]
    }


@pytest.fixture(scope='session')
def sample_geojson_polygons():
    """Sample GeoJSON Polygon features for testing"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [126.95, 37.45],
                        [127.05, 37.45],
                        [127.05, 37.55],
                        [126.95, 37.55],
                        [126.95, 37.45]
                    ]]
                },
                "properties": {
                    "id": "zone_001",
                    "name": "Test Zone A",
                    "type": "zone",
                    "area": 10000
                }
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [127.0, 37.5],
                        [127.1, 37.5],
                        [127.1, 37.6],
                        [127.0, 37.6],
                        [127.0, 37.5]
                    ]]
                },
                "properties": {
                    "id": "site_001",
                    "name": "Test Site B",
                    "type": "site",
                    "area": 15000
                }
            }
        ]
    }


@pytest.fixture(scope='session')
def sample_geojson_lines():
    """Sample GeoJSON LineString features for testing"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [126.8, 37.3],
                        [126.9, 37.4],
                        [127.0, 37.5],
                        [127.1, 37.6]
                    ]
                },
                "properties": {
                    "id": "path_001",
                    "name": "Test Path A",
                    "type": "road",
                    "length": 5000
                }
            }
        ]
    }


@pytest.fixture
def mock_maplibre_map():
    """Mock MapLibre map instance for unit testing"""
    class MockMap:
        def __init__(self):
            self.sources = {}
            self.layers = {}
            self.style = {"version": 8, "sources": {}, "layers": []}
            self.center = [127.0, 37.5]
            self.zoom = 10
            self.bearing = 0
            self.pitch = 0
            self._event_handlers = {}
            
        def addSource(self, id, source_config):
            self.sources[id] = source_config
            
        def removeSource(self, id):
            if id in self.sources:
                del self.sources[id]
                
        def getSource(self, id):
            return self.sources.get(id)
            
        def addLayer(self, layer_config, before_id=None):
            self.layers[layer_config['id']] = layer_config
            
        def removeLayer(self, id):
            if id in self.layers:
                del self.layers[id]
                
        def getLayer(self, id):
            return self.layers.get(id)
            
        def setLayoutProperty(self, layer_id, property_name, value):
            if layer_id in self.layers:
                if 'layout' not in self.layers[layer_id]:
                    self.layers[layer_id]['layout'] = {}
                self.layers[layer_id]['layout'][property_name] = value
                
        def setPaintProperty(self, layer_id, property_name, value):
            if layer_id in self.layers:
                if 'paint' not in self.layers[layer_id]:
                    self.layers[layer_id]['paint'] = {}
                self.layers[layer_id]['paint'][property_name] = value
                
        def setFilter(self, layer_id, filter_expr):
            if layer_id in self.layers:
                self.layers[layer_id]['filter'] = filter_expr
                
        def getFilter(self, layer_id):
            layer = self.layers.get(layer_id)
            return layer.get('filter') if layer else None
                
        def queryRenderedFeatures(self, point, options=None):
            return []
            
        def querySourceFeatures(self, source_id):
            return []
            
        def fitBounds(self, bounds, options=None):
            pass
            
        def on(self, event, callback):
            if event not in self._event_handlers:
                self._event_handlers[event] = []
            self._event_handlers[event].append(callback)
            
        def off(self, event, callback):
            if event in self._event_handlers:
                self._event_handlers[event] = [h for h in self._event_handlers[event] if h != callback]
                
        def fire(self, event, data):
            if event in self._event_handlers:
                for handler in self._event_handlers[event]:
                    handler(data)
            
        def getCanvas(self):
            class MockCanvas:
                style = {"cursor": ""}
            return MockCanvas()
            
        def getCenter(self):
            class MockCenter:
                lng = self.center[0]
                lat = self.center[1]
            return MockCenter()
            
        def getZoom(self):
            return self.zoom
            
        def remove(self):
            self.sources.clear()
            self.layers.clear()
            self._event_handlers.clear()
            
    return MockMap()


@pytest.fixture
def gis_provider_configs():
    """Configuration for various GIS providers"""
    return {
        'vworld_base': {
            'id': 'vworld_base',
            'name': 'VWorld 기본',
            'provider': 'vworld',
            'type': 'raster',
            'url': 'https://api.vworld.kr/req/wmts/1.0.0/{api_key}/base/{z}/{y}/{x}',
            'options': {
                'layer': 'base',
                'maxZoom': 19,
                'maxNativeZoom': 18
            }
        },
        'vworld_satellite': {
            'id': 'vworld_satellite',
            'name': 'VWorld 위성',
            'provider': 'vworld',
            'type': 'raster',
            'url': 'https://api.vworld.kr/req/wmts/1.0.0/{api_key}/satellite/{z}/{y}/{x}',
            'options': {
                'layer': 'satellite',
                'maxZoom': 19,
                'maxNativeZoom': 17
            }
        },
        'maptiler_vector': {
            'id': 'maptiler_vector',
            'name': 'MapTiler 벡터',
            'provider': 'maptiler',
            'type': 'vector',
            'url': 'https://api.maptiler.com/tiles/v3-free/style.json',
            'options': {
                'maxZoom': 22,
                'maxNativeZoom': 14
            }
        },
        'osm_standard': {
            'id': 'osm_standard',
            'name': 'OpenStreetMap',
            'provider': 'osm',
            'type': 'raster',
            'url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            'options': {
                'maxZoom': 19,
                'maxNativeZoom': 19
            }
        }
    }


@pytest.fixture
def performance_metrics():
    """Track performance metrics during tests"""
    import time
    
    class PerformanceTracker:
        def __init__(self):
            self.metrics = {}
            self.timers = {}
            
        def start_timer(self, name):
            self.timers[name] = time.perf_counter()
            
        def stop_timer(self, name):
            if name in self.timers:
                elapsed = time.perf_counter() - self.timers[name]
                if name not in self.metrics:
                    self.metrics[name] = []
                self.metrics[name].append(elapsed)
                del self.timers[name]
                return elapsed
            return None
            
        def record_metric(self, name, value):
            if name not in self.metrics:
                self.metrics[name] = []
            self.metrics[name].append(value)
            
        def get_average(self, name):
            if name in self.metrics and self.metrics[name]:
                return sum(self.metrics[name]) / len(self.metrics[name])
            return None
            
        def get_total(self, name):
            if name in self.metrics:
                return sum(self.metrics[name])
            return 0
            
        def get_report(self):
            report = {}
            for name, values in self.metrics.items():
                if values:
                    report[name] = {
                        'count': len(values),
                        'total': sum(values),
                        'average': sum(values) / len(values),
                        'min': min(values),
                        'max': max(values)
                    }
            return report
            
    return PerformanceTracker()
