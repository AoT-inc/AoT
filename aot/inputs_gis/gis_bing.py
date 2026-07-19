# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'Aerial', 'options': {'style': 'a', 'ext': 'jpeg'}},
    1: {'name': 'Aerial with Labels', 'options': {'style': 'h', 'ext': 'jpeg'}},
    2: {'name': 'Road', 'options': {'style': 'r', 'ext': 'png'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_bing',
    'input_manufacturer': 'Microsoft',
    'url_manufacturer': 'https://www.bing.com/maps',
    'url_api_key': 'https://www.microsoft.com/maps/create-a-bing-maps-key.aspx',
    'message': lg('Microsoft global map service providing high-resolution aerial imagery (Aerial) and aerial with labels (Hybrid), with clean and precise road maps.'),
    'country': ['GL'],
    'input_name': 'Bing Maps',
    'input_library': 'gis_bing',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.bing.com/maps',
    'attribution': '&copy; <a href="https://www.bing.com/maps">Microsoft Bing Maps</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': lg('Bing Maps API Key'),
            'required': False
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
    # Using {q} for QuadKey (Standard Virtual Earth URL pattern)
    # Subdomains: t0, t1, t2, t3
    # g=1 is generation/version for tiles
    'default_url': 'https://ecn.t1.tiles.virtualearth.net/tiles/{style}{q}.{ext}?g=12986',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 19,
        'maxNativeZoom': 19
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Bing Maps (Microsoft).
    Provides Aerial, Aerial with Labels, and Road tile styles.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://ecn.t1.tiles.virtualearth.net/tiles/{style}{q}.{ext}?g=12986'
        self.attribution = INPUT_INFORMATION['attribution']

    def _get_active_options(self):
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
        
        from aot.inputs_gis.gis_bing import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options']
        return CHANNELS[0]['options']

    def get_url(self):
        opts = self._get_active_options()
        style = opts.get('style', 'a')
        ext = opts.get('ext', 'jpeg')
        api_key = self.get_custom_option('api_key')
        
        url = self.default_url.replace('{style}', style).replace('{ext}', ext)
        if api_key:
            url += f"&key={api_key}"
            
        # Return URL template with {q} placeholder
        return url

    # Search: Using Nominatim as fallback since Bing Search API requires Key we don't force users to have
    # (unless we add API Key field - user requested recommendation, kept it simple without mandatory key if possible)
    # Actually, Bing Maps usually requires Key, but Tile service often works without one on public endpoints for 'a' style.
    # However, for search, let's use Nominatim for free access.
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        # Fallback to Nominatim
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'limit': kwargs.get('limit', 10),
            'addressdetails': 1
        }
        headers = {
            'User-Agent': 'AoT-GIS-Client/1.0',
            'Referer': 'https://aot-dev.internal'
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data:
                    results.append({
                        'name': item.get('display_name'),
                        'lat': float(item.get('lat')),
                        'lng': float(item.get('lon')),
                        'address': item.get('display_name'),
                        'provider': 'nominatim-fallback'
                    })
                return results
            return {'error': 'Bing Search Unavailable (Using Nominatim Fallback failed)'}
        except Exception as e:
            return {'error': str(e)}
