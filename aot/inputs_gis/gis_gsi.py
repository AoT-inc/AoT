# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'Standard', 'options': {'layer': 'std'}},
    1: {'name': 'Pale', 'options': {'layer': 'pale'}},
    2: {'name': 'English', 'options': {'layer': 'english'}},
    3: {'name': 'Photo', 'options': {'layer': 'ort', 'ext': 'jpg'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_gsi',
    'input_manufacturer': 'GSI',
    'message': lg('High-precision public map service from Japan Geospatial Information Authority (GSI). Contains detailed terrain and place name information across Japan, with professional layers including standard maps, pale maps, and aerial photography.'),
    'country': ['JP'],
    'input_name': 'GSI Maps',
    'input_library': 'gis_gsi',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://maps.gsi.go.jp/',
    'attribution': '&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">Geospatial Information Authority of Japan</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
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
    'default_url': 'https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png',
    'default_center': [139.6917, 35.6895],
    'default_zoom': 6,
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'minZoom': 5,
        'maxNativeZoom': 18,
        'maxZoom': 18
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Japan GSI (Geospatial Information Authority) maps.
    Provides standard, pale, English, and aerial photo tile layers for Japan.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png'
        self.attribution = INPUT_INFORMATION['attribution']

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
        
        from aot.inputs_gis.gis_gsi import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options'].get('layer', 'std')
        return 'std'

    def get_url(self):
        layer = self._get_active_layer_type()
        
        # 'ort' (Photo) is JPG, others are PNG
        ext = 'jpg' if layer == 'ort' else 'png'
        
        return f'https://cyberjapandata.gsi.go.jp/xyz/{layer}/{{z}}/{{x}}/{{y}}.{ext}'

    # Search Implementation (Nominatim Fallback)
    # GSI does not provide a simple public Geocoding API for global usage.
    # We rely on Nominatim (OSM) which has good Japan coverage.
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        """
        Nominatim Search (Fallback for GSI)
        """
        url = "https://nominatim.openstreetmap.org/search"
        
        params = {
            'q': query,
            'format': 'json',
            'limit': kwargs.get('limit', 10),
            'addressdetails': 1,
            'countrycodes': 'jp' # Focus on Japan for GSI Maps
        }
        
        # User-Agent is required by Nominatim TOS.
        headers = {
            'User-Agent': 'AoT-GIS-Client/1.0 (contact: gwansuk@aot-dev.com)',
            'Referer': 'https://aot-dev.internal' 
        }

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            
            if resp.status_code != 200:
                # Include reason if text is empty
                msg = resp.text if resp.text else resp.reason
                if resp.status_code in [403, 418]:
                    return {'error': f"Nominatim API Error ({resp.status_code}): Access Blocked (TOS violation or IP Ban). {msg[:100]}"}
                return {'error': f"Nominatim API Error ({resp.status_code}): {msg[:100]}"}

            try:
                data = resp.json()
            except Exception:
                # If HTML returned (e.g. rate limit page)
                return {'error': f"Nominatim API Response Invalid: {resp.text[:50]}"}
            
            results = []
            for item in data:
                res_obj = {
                    'name': item.get('display_name', ''),
                    'lat': float(item.get('lat', 0)),
                    'lng': float(item.get('lon', 0)),
                    'address': item.get('display_name', ''),
                    'meta': item
                }
                results.append(res_obj)
            
            return results

        except Exception as e:
            return {'error': str(e)}
