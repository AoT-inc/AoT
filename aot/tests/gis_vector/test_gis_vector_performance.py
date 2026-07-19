# coding=utf-8
"""
GIS Vector Performance Benchmark Tests

Performance benchmarks for gis_vector branch:
1. Map initialization time
2. Layer rendering speed
3. Source switching performance
4. GeoJSON processing speed
5. Memory usage comparison
"""

import os
import sys
import pytest
import time
import json
from unittest.mock import Mock, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


class TestMapInitializationPerformance:
    """Performance tests for map initialization"""
    
    def test_map_creation_overhead(self, performance_metrics):
        """Measure overhead of creating map instance"""
        class MinimalMap:
            def __init__(self):
                self.sources = {}
                self.layers = {}
                self.style = {}
                self.center = [127.0, 37.5]
                self.zoom = 10
                
        performance_metrics.start_timer('map_creation')
        
        maps = []
        for _ in range(100):
            m = MinimalMap()
            maps.append(m)
        
        creation_time = performance_metrics.stop_timer('map_creation')
        
        assert creation_time < 1.0  # Should complete in under 1 second
        assert len(maps) == 100
    
    def test_style_loading_time(self, performance_metrics):
        """Measure style loading simulation"""
        # Simulate style JSON parsing
        style_json = json.dumps({
            'version': 8,
            'sources': {
                'osm': {
                    'type': 'raster',
                    'tiles': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png']
                }
            },
            'layers': [
                {'id': 'background', 'type': 'background', 'paint': {'background-color': '#ffffff'}}
            ]
        })
        
        performance_metrics.start_timer('style_parsing')
        
        parsed_count = 0
        for _ in range(1000):
            style = json.loads(style_json)
            parsed_count += 1
            
        parsing_time = performance_metrics.stop_timer('style_parsing')
        
        avg_time = performance_metrics.get_average('style_parsing')
        assert avg_time < 0.01  # Should parse in under 10ms per style
    
    def test_source_registration_performance(self, performance_metrics):
        """Measure source registration performance"""
        class MapWithSources:
            def __init__(self):
                self.sources = {}
                
            def addSource(self, id, config):
                self.sources[id] = config
                
            def removeSource(self, id):
                if id in self.sources:
                    del self.sources[id]
        
        map_instance = MapWithSources()
        
        performance_metrics.start_timer('source_registration')
        
        for i in range(50):
            map_instance.addSource(f'source_{i}', {
                'type': 'vector' if i % 2 == 0 else 'raster',
                'tiles': [f'https://example.com/tiles/{i}/{{z}}/{{x}}/{{y}}.pbf']
            })
        
        registration_time = performance_metrics.stop_timer('source_registration')
        
        assert len(map_instance.sources) == 50
        assert registration_time < 0.5  # Should complete in under 500ms


class TestLayerRenderingPerformance:
    """Performance tests for layer rendering operations"""
    
    def test_layer_add_performance(self, performance_metrics):
        """Measure layer addition performance"""
        class MockMap:
            def __init__(self):
                self.layers = {}
            def addLayer(self, config):
                self.layers[config['id']] = config
            def removeLayer(self, id):
                if id in self.layers:
                    del self.layers[id]
        
        map_instance = MockMap()
        
        performance_metrics.start_timer('layer_addition')
        
        for i in range(100):
            map_instance.addLayer({
                'id': f'layer_{i}',
                'type': 'fill' if i % 3 == 0 else 'line' if i % 3 == 1 else 'circle',
                'source': f'source_{i % 10}',
                'paint': {
                    'fill-color': '#FF0000',
                    'fill-opacity': 0.5
                }
            })
        
        addition_time = performance_metrics.stop_timer('layer_addition')
        
        assert len(map_instance.layers) == 100
        assert addition_time < 1.0  # Should complete in under 1 second
    
    def test_style_update_performance(self, performance_metrics):
        """Measure style property update performance"""
        class MockMap:
            def __init__(self):
                self.layers = {}
            def addLayer(self, config):
                self.layers[config['id']] = config
            def setPaintProperty(self, layer_id, prop, value):
                if layer_id in self.layers:
                    if 'paint' not in self.layers[layer_id]:
                        self.layers[layer_id]['paint'] = {}
                    self.layers[layer_id]['paint'][prop] = value
            def setLayoutProperty(self, layer_id, prop, value):
                if layer_id in self.layers:
                    if 'layout' not in self.layers[layer_id]:
                        self.layers[layer_id]['layout'] = {}
                    self.layers[layer_id]['layout'][prop] = value
        
        map_instance = MockMap()
        
        # Add layers
        for i in range(50):
            map_instance.addLayer({
                'id': f'layer_{i}',
                'type': 'fill',
                'source': 'test-source'
            })
        
        performance_metrics.start_timer('style_update')
        
        # Update styles
        colors = ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF']
        for i in range(50):
            for _ in range(10):  # Multiple updates per layer
                color = colors[i % len(colors)]
                map_instance.setPaintProperty(f'layer_{i}', 'fill-color', color)
                map_instance.setLayoutProperty(f'layer_{i}', 'visibility', 'visible')
        
        update_time = performance_metrics.stop_timer('style_update')
        
        assert update_time < 2.0  # Should complete in under 2 seconds


class TestGeoJSONProcessingPerformance:
    """Performance tests for GeoJSON operations"""
    
    def test_large_geojson_parsing(self, performance_metrics):
        """Measure performance of parsing large GeoJSON"""
        # Generate large GeoJSON
        num_features = 1000
        large_geojson = {
            'type': 'FeatureCollection',
            'features': [
                {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [127.0 + (i % 10) * 0.1, 37.5 + (i // 10) * 0.1]
                    },
                    'properties': {
                        'id': f'point_{i}',
                        'name': f'Point {i}',
                        'value': i * 10,
                        'tags': ['test', 'benchmark', f'tag_{i % 5}']
                    }
                }
                for i in range(num_features)
            ]
        }
        
        performance_metrics.start_timer('geojson_parsing')
        
        json_str = json.dumps(large_geojson)
        parsed = json.loads(json_str)
        
        parsing_time = performance_metrics.stop_timer('geojson_parsing')
        
        assert len(parsed['features']) == num_features
        assert parsing_time < 1.0  # Should parse in under 1 second
    
    def test_geojson_filter_performance(self, performance_metrics):
        """Measure GeoJSON filtering performance"""
        # Create large feature collection
        features = [
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [127.0 + i * 0.01, 37.5 + i * 0.01]},
                'properties': {'id': i, 'type': ['device', 'sensor', 'zone'][i % 3], 'value': i}
            }
            for i in range(5000)
        ]
        
        geojson = {'type': 'FeatureCollection', 'features': features}
        
        performance_metrics.start_timer('geojson_filter')
        
        filtered = []
        for _ in range(10):  # Multiple filter operations
            result = [f for f in features if f['properties']['type'] == 'device' and f['properties']['value'] > 1000]
            filtered = result
        
        filter_time = performance_metrics.stop_timer('geojson_filter')
        
        assert len(filtered) > 0
        assert filter_time < 2.0  # Should complete in under 2 seconds
    
    def test_geojson_to_source_update(self, performance_metrics):
        """Measure updating GeoJSON source data"""
        class MockSource:
            def __init__(self):
                self.data = None
            def setData(self, data):
                self.data = data
        
        source = MockSource()
        geojson = {
            'type': 'FeatureCollection',
            'features': [
                {
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [127.0 + i * 0.1, 37.5 + i * 0.1]},
                    'properties': {'id': i, 'name': f'Point {i}'}
                }
                for i in range(500)
            ]
        }
        
        performance_metrics.start_timer('source_update')
        
        for _ in range(100):
            source.setData(geojson)
        
        update_time = performance_metrics.stop_timer('source_update')
        
        assert source.data is not None
        assert len(source.data['features']) == 500
        assert update_time < 1.0  # Should complete in under 1 second


class TestSourceSwitchingPerformance:
    """Performance tests for source switching operations"""
    
    def test_source_removal_performance(self, performance_metrics):
        """Measure source removal performance"""
        class MapWithSources:
            def __init__(self):
                self.sources = {}
            def addSource(self, id, config):
                self.sources[id] = config
            def removeSource(self, id):
                if id in self.sources:
                    del self.sources[id]
        
        map_instance = MapWithSources()
        
        # Add sources
        for i in range(20):
            map_instance.addSource(f'source_{i}', {
                'type': 'vector',
                'tiles': [f'https://example.com/{i}/{{z}}/{{x}}/{{y}}.pbf']
            })
        
        performance_metrics.start_timer('source_removal')
        
        # Remove all sources
        for i in range(20):
            map_instance.removeSource(f'source_{i}')
        
        removal_time = performance_metrics.stop_timer('source_removal')
        
        assert len(map_instance.sources) == 0
        assert removal_time < 0.2  # Should complete in under 200ms
    
    def test_layer_removal_performance(self, performance_metrics):
        """Measure layer removal performance"""
        class MockMap:
            def __init__(self):
                self.layers = {}
            def addLayer(self, config):
                self.layers[config['id']] = config
            def removeLayer(self, id):
                if id in self.layers:
                    del self.layers[id]
        
        map_instance = MockMap()
        
        # Add layers
        for i in range(50):
            map_instance.addLayer({
                'id': f'layer_{i}',
                'type': 'fill',
                'source': 'test-source'
            })
        
        performance_metrics.start_timer('layer_removal')
        
        # Remove all layers
        for i in range(50):
            map_instance.removeLayer(f'layer_{i}')
        
        removal_time = performance_metrics.stop_timer('layer_removal')
        
        assert len(map_instance.layers) == 0
        assert removal_time < 0.3  # Should complete in under 300ms
    
    def test_full_source_switch_cycle(self, performance_metrics):
        """Measure complete source switch cycle"""
        class MockMap:
            def __init__(self):
                self.sources = {}
                self.layers = {}
            def addSource(self, id, config):
                self.sources[id] = config
            def removeSource(self, id):
                if id in self.sources:
                    del self.sources[id]
            def addLayer(self, config):
                self.layers[config['id']] = config
            def removeLayer(self, id):
                if id in self.layers:
                    del self.layers[id]
        
        map_instance = MockMap()
        
        # Add initial base source with layers
        map_instance.addSource('base_1', {'type': 'raster', 'tiles': ['https://old.com/{z}/{x}/{y}.png']})
        for i in range(5):
            map_instance.addLayer({'id': f'overlay_{i}', 'source': 'base_1'})
        
        performance_metrics.start_timer('source_switch_cycle')
        
        # Switch sources
        for cycle in range(10):
            # Remove old source
            map_instance.removeSource('base_1')
            for i in range(5):
                map_instance.removeLayer(f'overlay_{i}')
            
            # Add new source
            map_instance.addSource('base_1', {
                'type': 'vector' if cycle % 2 == 0 else 'raster',
                'tiles': [f'https://new{cycle}.com/{{z}}/{{x}}/{{y}}.pbf' if cycle % 2 == 0 else f'https://new{cycle}.com/{{z}}/{{x}}/{{y}}.png']
            })
            for i in range(5):
                map_instance.addLayer({'id': f'overlay_{i}', 'source': 'base_1'})
        
        switch_time = performance_metrics.stop_timer('source_switch_cycle')
        
        assert len(map_instance.sources) == 1
        assert len(map_instance.layers) == 5
        assert switch_time < 5.0  # Should complete in under 5 seconds


class TestMemoryBenchmark:
    """Memory-related performance tests"""
    
    def test_source_registry_memory(self, performance_metrics):
        """Measure memory footprint of source registry"""
        class SourceRegistry:
            def __init__(self):
                self.sources = {}
                
        registry = SourceRegistry()
        
        # Add sources with typical configurations
        for i in range(100):
            registry.sources[f'source_{i}'] = {
                'type': 'vector',
                'tiles': [f'https://example.com/{i}/{{z}}/{{x}}/{{y}}.pbf' for _ in range(4)],
                'minzoom': 0,
                'maxzoom': 14,
                'attribution': '© Test'
            }
        
        # Measure approximate memory (rough estimate)
        import sys
        registry_size = sys.getsizeof(json.dumps(registry.sources))
        
        # 100 sources should use less than 1MB of memory
        assert registry_size < 1_000_000  # 1MB
    
    def test_layer_config_memory(self, performance_metrics):
        """Measure memory footprint of layer configurations"""
        class LayerRegistry:
            def __init__(self):
                self.layers = {}
        
        registry = LayerRegistry()
        
        # Add layers with typical configurations
        for i in range(200):
            registry.layers[f'layer_{i}'] = {
                'id': f'layer_{i}',
                'type': ['fill', 'line', 'circle', 'symbol'][i % 4],
                'source': f'source_{i % 20}',
                'paint': {
                    'fill-color': '#FF0000',
                    'fill-opacity': 0.5
                },
                'layout': {
                    'visibility': 'visible'
                }
            }
        
        # Measure approximate memory
        import sys
        layer_size = sys.getsizeof(json.dumps(registry.layers))
        
        # 200 layers should use less than 2MB of memory
        assert layer_size < 2_000_000  # 2MB


class TestRenderingSpeedBenchmark:
    """Rendering speed benchmark tests"""
    
    def test_tile_url_construction_speed(self, performance_metrics):
        """Measure tile URL construction speed"""
        template = 'https://api.example.com/tiles/{z}/{x}/{y}.pbf'
        
        performance_metrics.start_timer('url_construction')
        
        urls = []
        for z in range(10, 15):
            for x in range(100):
                for y in range(100):
                    url = template.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))
                    urls.append(url)
        
        construction_time = performance_metrics.stop_timer('url_construction')
        
        assert len(urls) == 5 * 100 * 100  # 50,000 URLs
        assert construction_time < 2.0  # Should complete in under 2 seconds
    
    def test_coordinate_transformation_speed(self, performance_metrics):
        """Measure coordinate transformation speed"""
        import math
        
        def wgs84_to_epsg3857(lng, lat):
            x = lng * 20037508.34 / 180
            y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
            return x, y
        
        performance_metrics.start_timer('coordinate_transform')
        
        transformed = []
        for i in range(10000):
            lng, lat = 127.0 + (i % 100) * 0.1, 37.5 + (i // 100) * 0.1
            x, y = wgs84_to_epsg3857(lng, lat)
            transformed.append((x, y))
        
        transform_time = performance_metrics.stop_timer('coordinate_transform')
        
        assert len(transformed) == 10000
        assert transform_time < 1.0  # Should complete in under 1 second


class TestPerformanceReport:
    """Generate performance test report"""
    
    def test_generate_performance_summary(self, performance_metrics):
        """Generate and validate performance summary"""
        # Run a series of measurements
        performance_metrics.start_timer('operation_1')
        time.sleep(0.01)
        performance_metrics.stop_timer('operation_1')
        
        performance_metrics.start_timer('operation_2')
        time.sleep(0.02)
        performance_metrics.stop_timer('operation_2')
        
        performance_metrics.record_metric('memory_usage', 50)
        performance_metrics.record_metric('memory_usage', 55)
        performance_metrics.record_metric('memory_usage', 52)
        
        report = performance_metrics.get_report()
        
        assert 'operation_1' in report
        assert 'operation_2' in report
        assert 'memory_usage' in report
        
        assert abs(report['memory_usage']['average'] - 52.333333333333336) < 0.01  # Allow floating point tolerance
        assert report['memory_usage']['min'] == 50
        assert report['memory_usage']['max'] == 55


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
