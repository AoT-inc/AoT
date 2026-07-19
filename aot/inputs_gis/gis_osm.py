# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

# Definition of the Input
INPUT_INFORMATION = {
    'input_name_unique': 'gis_osm',
    'input_manufacturer': 'OpenStreetMap',
    'message': lg('Free map data created collaboratively by users worldwide in Wikipedia-style. Available at no cost with road and building information continuously updated by an active community. Standard web map with global coverage.'),
    'country': ['GL'],
    'input_name': 'OpenStreetMap',
    'input_library': 'gis_osm',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.openstreetmap.org/',
    'attribution': '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    'options_enabled': [],
    'options_disabled': ['period', 'measurements_delay'],
    'dependencies_module': [],
    'default_url': 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    'layer_type': 'xyz',
    'time_enabled': False
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for OpenStreetMap (global coverage).
    Provides free community-driven map tiles with address search via Nominatim.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
        self.attribution = INPUT_INFORMATION['attribution']

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        options.update({
            'maxZoom': 19
        })
        return options

    # Nominatim Search Implementation
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        """
        OpenStreetMap Nominatim API
        """
        url = "https://nominatim.openstreetmap.org/search"
        
        params = {
            'q': query,
            'format': 'json',
            'limit': kwargs.get('limit', 10),
            'addressdetails': 1
        }
        
        # User-Agent is required by Nominatim TOS
        # Policy: "Use a valid User-Agent... Provide a valid email".
        headers = {
            # [Fix] Update User-Agent to avoid 418 Block. Using a more standard identifier.
            'User-Agent': 'AoT-Embedded-System/1.0 (Project: AoT; contact: admin@aotsystem.com)',
            'Referer': 'https://aot-system.local' 
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
