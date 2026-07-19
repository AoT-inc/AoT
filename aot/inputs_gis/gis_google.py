# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'Roadmap', 'options': {'layer': 'm'}},
    1: {'name': 'Satellite', 'options': {'layer': 's'}},
    2: {'name': 'Hybrid', 'options': {'layer': 'y'}},
    3: {'name': 'Terrain', 'options': {'layer': 'p'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_google',
    'input_manufacturer': 'Google',
    'input_name': 'Google Maps',
    'input_library': 'gis_google',
    'country': ['GL'],
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'key_field': 'api_key',
    'global_key_field': 'google_maps',
    'requires_key': True,
    'url_manufacturer': 'https://www.google.com/maps',
    'url_api_key': 'https://developers.google.com/maps/documentation/javascript/get-api-key',
    'message': lg('Most widely used Google web map service. Supports Road, Satellite, Hybrid, and Terrain modes based on vast geographic information. Terrain mode excels at showing contours and hillshading. Also supports Geocoding API for address-to-coordinate conversion. API key available from Google Developer Console.'),
    'attribution': '&copy; <a href="https://www.google.com/maps">Google Maps</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'Google Maps API Key',
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Map Style',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://mt1.google.com/vt/lyrs={layer}&x={x}&y={y}&z={z}',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'minZoom': 0,
        'maxNativeZoom': 20,
        'maxZoom': 22
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Google Maps.
    Provides Roadmap, Satellite, Hybrid, and Terrain tile layers with Geocoding API.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://mt1.google.com/vt/lyrs={layer}&x={x}&y={y}&z={z}'
        self.attribution = INPUT_INFORMATION['attribution']
        
        self.api_key = self.get_custom_option('api_key') or ''

    def _get_active_layer_type(self):
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
        
        # Access global CHANNELS directly
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options'].get('layer', 'm')
        return 'm'

    def get_url(self):
        layer_type = self._get_active_layer_type()
        
        # Refetch API Key
        self.api_key = self.get_custom_option('api_key') or ''
        
        # Google Maps Tile URL pattern (Standard XYZ)
        url = self.default_url.replace('{layer}', layer_type)
        if self.api_key:
             url += f"&key={self.api_key}"
             
        return url

    # Google Search Implementation
    search_capabilities = ['address', 'place']


    def search(self, query, search_type='address', **kwargs):
        """
        Google Maps Hybrid Search: Geocoding + Places Text Search
        """
        self.api_key = self.get_custom_option('api_key') or ''
        
        if not self.api_key:
            return {'error': 'Google API Key Missing. Please configure it in the Input Settings.'}

        limit = kwargs.get('limit', 10)
        results = []
        seen_coords = set()
        seen_addresses = set()

        # 1. Geocoding API (Best for specific addresses)
        geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
        # 2. Places API - Text Search (Best for POIs, businesses, landmarks)
        places_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

        # Sequential calls to aggregate results
        apis = [
            {'url': geocode_url, 'query_param': 'address', 'name': 'Geocoding'},
            {'url': places_url, 'query_param': 'query', 'name': 'Places'}
        ]

        for api in apis:
            if len(results) >= limit:
                break

            params = {
                api['query_param']: query,
                'key': self.api_key
            }
            
            try:
                resp = requests.get(api['url'], params=params, timeout=10)
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                status = data.get('status')
                
                if status != 'OK':
                    continue

                items = data.get('results', [])
                for item in items:
                    geo = item.get('geometry', {})
                    loc = geo.get('location', {})
                    lat = float(loc.get('lat', 0))
                    lng = float(loc.get('lng', 0))
                    
                    if lat == 0 and lng == 0:
                        continue

                    addr = item.get('formatted_address', '')
                    name = item.get('name', addr) # Places results have 'name', Geocoding usually uses formatted_address
                    
                    # Deduplication Logic
                    coord_key = (round(lat, 5), round(lng, 5))
                    if coord_key in seen_coords or addr in seen_addresses:
                        continue
                    
                    seen_coords.add(coord_key)
                    seen_addresses.add(addr)

                    res_obj = {
                        'name': name,
                        'lat': lat,
                        'lng': lng,
                        'address': addr,
                        'provider': 'google'
                    }
                    results.append(res_obj)

            except Exception:
                continue

        if not results:
            return {'error': 'Google Error: ZERO_RESULTS'}
            
        return results[:limit]
