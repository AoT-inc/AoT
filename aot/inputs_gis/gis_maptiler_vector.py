# coding=utf-8
"""
gis_maptiler_vector.py - MapTiler Vector Tile Provider for AoT
Provides high-performance vector tile rendering with customizable styles.
"""
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

# Vector tile styles available from MapTiler
CHANNELS = {
    0: {'name': 'Streets', 'style': 'streets', 'description': 'Standard road map with labels'},
    1: {'name': 'Outdoor', 'style': 'outdoor', 'description': 'Topographic map with trails'},
    2: {'name': 'Satellite', 'style': 'satellite', 'description': 'Satellite imagery base'},
    3: {'name': 'Hybrid', 'style': 'hybrid', 'description': 'Satellite with roads/labels'},
    4: {'name': 'Ocean', 'style': 'ocean', 'description': 'Bathymetric ocean map'},
    5: {'name': 'Topo', 'style': 'topo', 'description': 'Topographic terrain map'},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_maptiler_vector',
    'input_manufacturer': 'MapTiler',
    'url_manufacturer': 'https://www.maptiler.com/',
    'url_api_key': 'https://cloud.maptiler.com/account/keys/',
    'message': lg('High-performance vector tile map service. Supports multiple styles (streets, light, dark, satellite, etc.) with excellent rendering performance and HD display.'),
    'country': ['GL'],
    'input_name': 'MapTiler Vector',
    'input_library': 'gis_maptiler_vector',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'default_url': 'https://api.maptiler.com/maps/{style}/style.json?key={api_key}',
    'key_field': 'api_key',
    'global_key_field': 'maptiler',
    'requires_key': True,
    'attribution': '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'layer_type': 'vector',  # New type for vector tiles
    'time_enabled': False,
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'MapTiler API Key',
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Map Style',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        },
        {
            'id': 'language',
            'type': 'text',
            'default': 'auto',
            'name': 'Label Language',
            'description': 'Language for map labels (e.g., ko, en, auto)'
        }
    ],
    'leaflet_options': {
        'maxZoom': 22,
        'maxNativeZoom': 14  # Vector tiles typically go up to 14-16 natively
    }
}


class InputModule(AbstractGisInput):
    """
    GIS vector tile provider using MapTiler Cloud.
    Delivers high-performance vector tiles with customizable styles.
    
    @phase active
    @stability stable
    @dependency AbstractGisInput
    @requires maplibre-gl (frontend)
    """
    
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'vector'  # Critical: marks this as vector tile
        self.layer_category = 'base'
        self.api_key = self.get_custom_option('api_key') or ''
        
        # MapTiler Cloud API base
        self._base_url = 'https://api.maptiler.com'
    
    def _get_active_style(self):
        """Get the active style from channel selection."""
        active_channels = self.get_custom_option('active_channels')
        layer_id = 0
        if isinstance(active_channels, list) and len(active_channels) > 0:
            try:
                layer_id = int(active_channels[0])
            except:
                pass
        elif active_channels is not None:
            try:
                layer_id = int(active_channels)
            except:
                pass
        
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]
        return CHANNELS[0]
    
    def get_url(self):
        """Get the vector tile URL (for MapLibre-GL)."""
        self.api_key = self.get_custom_option('api_key') or ''
        style_info = self._get_active_style()
        style = style_info.get('style', 'streets')
        
        # MapTiler Cloud style URL (used by MapLibre)
        # MapTiler API v2: /maps/ not /styles/
        if self.api_key:
            return f'{self._base_url}/maps/{style}/style.json?key={self.api_key}'
        return f'{self._base_url}/maps/{style}/style.json'
    
    def get_tile_url(self):
        """Get the raw vector tile URL (xyz pattern for tile preloading)."""
        self.api_key = self.get_custom_option('api_key') or ''
        style_info = self._get_active_style()
        style = style_info.get('style', 'streets')
        
        # MapTiler API v2: /tiles/ path
        if self.api_key:
            return f'{self._base_url}/tiles/{style}/v2/{{z}}/{{x}}/{{y}}.pbf?key={self.api_key}'
        return f'{self._base_url}/tiles/{style}/v2/{{z}}/{{x}}/{{y}}.pbf'
    
    def get_leaflet_options(self):
        """Return options for vector tile rendering."""
        options = super(InputModule, self).get_leaflet_options()
        style_info = self._get_active_style()
        
        options.update({
            'maxZoom': 22,
            'maxNativeZoom': 14,
            # Vector tile specific options
            'style': self.get_url(),  # Style JSON URL
            'tileSize': 512,
            'language': self.get_custom_option('language', 'auto'),
        })
        
        return options
    
    def get_layer_config(self):
        """
        Override to provide vector-specific configuration.
        Returns config with type='vector' for frontend recognition.
        """
        self.api_key = self.get_custom_option('api_key') or ''
        style_info = self._get_active_style()
        
        config = {
            'unique_id': self.unique_id,
            'name': self.input_dev.name,
            'category': self.layer_category,
            'type': 'vector',  # Critical: marks as vector tile
            'url': self.get_url(),
            'tileUrl': self.get_tile_url(),  # Raw tile URL
            'attribution': self.attribution,
            'options': self.get_leaflet_options(),
            'legend': None,
            'time_enabled': self.time_enabled,
            'style_name': style_info.get('name', 'Streets'),
            'api_key': self.api_key,
            'language': self.get_custom_option('language', 'auto'),
            # [GIS Vector Migration] 3D Terrain support
            'terrain': {
                'enabled': True,
                'source': 'mapbox-dem',
                'url': f'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key={self.api_key}',
                'exaggeration': 1.5
            }
        }

        return config

    def get_terrain_config(self):
        """
        Get terrain configuration for 3D visualization.
        Returns config for MapLibre terrain source.
        """
        self.api_key = self.get_custom_option('api_key') or ''

        return {
            'source_id': 'mapbox-dem',
            'type': 'raster-dem',
            'url': f'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key={self.api_key}',
            'tileSize': 256,
            'maxzoom': 14,
            'exaggeration': 1.5
        }

    def get_ai_reading(self, bounds=None, zoom=None, feature_types=None):
        """
        Extract AI-analysis-ready vector tile data for the given viewport bounds.

        Fetches raw vector tiles for the specified bounding box and zoom level,
        then parses the PBF protobuf tiles and extracts structured feature data
        suitable for AI overlay analysis (e.g., building footprints, road segments,
        land-use polygons).

        @param bounds - Optional [minLng, minLat, maxLng, maxLat] viewport bounds.
                        Defaults to current map viewport or full tile extent.
        @param zoom - Optional zoom level (0-14). Defaults to current zoom or 12.
        @param feature_types - Optional list of MapTiler layer names to filter
                               (e.g., ['building', 'road', 'water']). Defaults to all.
        @returns {dict} Structured AI reading payload:
            {
                "source": "MapTiler Vector",
                "zoom": int,
                "bounds": [minLng, minLat, maxLng, maxLat],
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {...},
                        "properties": {
                            "layer": "building",
                            "tags": {...},   # OSM tags from tile
                            "area": float,   # polygon area in sq meters (if polygon)
                            "length": float, # line length in meters (if line)
                        }
                    },
                    ...
                ],
                "layer_counts": {"building": 142, "road": 87, ...},
                "total_features": int,
                "attribution": str
            }
        """
        import math
        import json

        # Resolve bounds
        if bounds is None:
            # Default to full tile extent for Korea region
            bounds = [124.0, 33.0, 132.0, 39.0]

        min_lng, min_lat, max_lng, max_lat = bounds

        # Resolve zoom
        if zoom is None:
            zoom = 12
        zoom = max(0, min(14, int(zoom)))

        # Target layers
        target_layers = set(feature_types) if feature_types else None

        # Collect all tiles in the bounding box at the given zoom
        tiles = self._get_tiles_for_bounds(min_lng, min_lat, max_lng, max_lat, zoom)

        all_features = []
        layer_counts = {}
        errors = []

        for tile_key in tiles:
            try:
                tile_data = self._fetch_tile(tile_key, zoom)
                if tile_data:
                    parsed = self._parse_pbf_tile(tile_data, target_layers)
                    for feat in parsed:
                        all_features.append(feat)
                        layer = feat.get('properties', {}).get('layer', 'unknown')
                        layer_counts[layer] = layer_counts.get(layer, 0) + 1
            except Exception as e:
                errors.append({'tile': tile_key, 'error': str(e)})

        # Compute geometric properties (area, length)
        for feat in all_features:
            geom_type = feat.get('geometry', {}).get('type', '')
            coords = feat.get('geometry', {}).get('coordinates', [])
            props = feat.setdefault('properties', {})

            if geom_type == 'Polygon':
                props['area'] = self._calculate_polygon_area(coords)
            elif geom_type in ('LineString', 'MultiLineString'):
                props['length'] = self._calculate_line_length(coords)

        result = {
            'source': 'MapTiler Vector',
            'zoom': zoom,
            'bounds': bounds,
            'features': all_features,
            'layer_counts': layer_counts,
            'total_features': len(all_features),
            'tiles_queried': len(tiles),
            'errors': errors if errors else None,
            'attribution': self.attribution
        }

        return result

    def _get_tiles_for_bounds(self, min_lng, min_lat, max_lng, max_lat, zoom):
        """
        Compute tile x/y indices for a bounding box at a given zoom level.
        Uses the standard Google/OSM tile scheme (z/x/y).
        Returns list of 'x,y' strings.
        """
        import math

        def lat_lon_to_tile(lat, lon, z):
            lat_r = math.radians(lat)
            n = 2 ** z
            x = int((lon + 180.0) / 360.0 * n)
            y = int((1.0 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2.0 * n)
            return x, y

        x_min, y_max = lat_lon_to_tile(min_lat, min_lng, zoom)
        x_max, y_min = lat_lon_to_tile(max_lat, max_lng, zoom)

        tiles = []
        for x in range(min(x_min, x_max), max(x_min, x_max) + 1):
            for y in range(min(y_min, y_max), max(y_min, y_max) + 1):
                tiles.append(f'{x},{y}')
        return tiles

    def _fetch_tile(self, tile_key, zoom):
        """
        Fetch a single vector tile from MapTiler Cloud API.
        Returns raw bytes of the .pbf tile.
        """
        import urllib.request

        x, y = tile_key.split(',')
        tile_url = (
            f'https://api.maptiler.com/tiles/{self._get_active_style().get("style", "streets")}'
            f'/v2/{zoom}/{x}/{y}.pbf?key={self.api_key}'
        )

        try:
            req = urllib.request.Request(
                tile_url,
                headers={'User-Agent': 'AoT-GIS-Client/1.0'}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        except Exception:
            return None

    def _parse_pbf_tile(self, raw_bytes, target_layers=None):
        """
        Parse MapTiler vector tile (Protobuf PBF format).
        Uses the vector_tile library (mapbox-vector-tile or vt2).
        Falls back to returning raw feature hints if library unavailable.

        @param raw_bytes - Raw .pbf bytes
        @param target_layers - Optional set of layer names to filter
        @returns list of GeoJSON Feature dicts
        """
        features = []

        try:
            # Primary: use 'mapbox-vector-tile' if available
            import mapbox_vector_tile
            decoded = mapbox_vector_tile.decode(raw_bytes)
            for layer_name, layer_data in decoded.items():
                if target_layers and layer_name not in target_layers:
                    continue
                for i, feature_geom in enumerate(layer_data.get('features', [])):
                    props = dict(layer_data.get('name', []))
                    # Mapbox vector tile decode returns (geometry, properties) tuples
                    if isinstance(feature_geom, tuple) and len(feature_geom) == 2:
                        geom, prop_dict = feature_geom
                        props.update(prop_dict)
                    else:
                        geom = feature_geom
                    features.append({
                        'type': 'Feature',
                        'geometry': geom,
                        'properties': {
                            'layer': layer_name,
                            'tags': props
                        }
                    })
            return features
        except ImportError:
            pass

        try:
            # Secondary: use 'vt2' (vector_tile) if available
            import vt2
            import json
            decoded = vt2.decode(raw_bytes)
            for layer_name, layer_obj in decoded.items():
                if target_layers and layer_name not in target_layers:
                    continue
                for feat in layer_obj.features:
                    props = dict(feat.props) if hasattr(feat, 'props') else {}
                    features.append({
                        'type': 'Feature',
                        'geometry': json.loads(feat.geometry.GeoJSON()) if hasattr(feat.geometry, 'GeoJSON') else None,
                        'properties': {
                            'layer': layer_name,
                            'tags': props
                        }
                    })
            return features
        except ImportError:
            pass

        # Fallback: return empty (protobuf parsing without library is non-trivial)
        return features

    def _calculate_polygon_area(self, coords):
        """
        Calculate the area of a polygon in square meters using the Shoelace formula
        projected onto a local tangent plane at the centroid.
        coords: array of [lng, lat] rings
        """
        import math

        if not coords or not coords[0]:
            return 0.0

        ring = coords[0]  # outer ring
        if len(ring) < 3:
            return 0.0

        # Compute centroid
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)

        # Convert to meters at centroid (Mercator scale factor)
        lat_rad = math.radians(cy)
        k = 6378137.0 * math.pi / 180.0

        # Shoelace formula in meters
        n = len(ring)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            xi = ring[i][0] * k * math.cos(lat_rad)
            yi = ring[i][1] * k
            xj = ring[j][0] * k * math.cos(lat_rad)
            yj = ring[j][1] * k
            area += xi * yj
            area -= xj * yi

        return abs(area) / 2.0

    def _calculate_line_length(self, coords):
        """
        Calculate the length of a line or multi-line in meters.
        coords: array of [lng, lat] points or array of rings
        """
        import math

        if not coords:
            return 0.0

        # Flatten if multi-line
        if isinstance(coords[0][0], list) and not isinstance(coords[0], float):
            points = []
            for ring in coords:
                points.extend(ring)
        else:
            points = coords

        total = 0.0
        k = 6378137.0 * math.pi / 180.0
        lat_rad_ref = math.radians(points[0][1])

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            dx = (p2[0] - p1[0]) * k * math.cos(lat_rad_ref)
            dy = (p2[1] - p1[1]) * k
            total += math.sqrt(dx * dx + dy * dy)

        return total

