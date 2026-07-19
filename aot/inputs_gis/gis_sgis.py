# coding=utf-8
import requests
import time
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

INPUT_INFORMATION = {
    'input_name_unique': 'gis_sgis',
    'input_manufacturer': 'Statistics Korea',
    'country': ['KO'],
    'input_name': 'SGIS (Statistics Korea)',
    'input_library': 'gis_sgis',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'key_field': 'consumer_key',
    'global_key_field': 'sgis_key',
    'requires_key': True,
    'url_manufacturer': 'https://sgis.kostat.go.kr/',
    'url_api_key': 'https://sgis.kostat.go.kr/developer/html/main.html',
    'message': lg('Statistical geographic information service from Statistics Korea (SGIS). Optimal domestic service for spatial analysis and visualization of statistical data including population, households, and businesses by administrative district.'),
    'url_manufacturer': 'https://sgis.kostat.go.kr/',
    'attribution': '&copy; <a href="https://sgis.kostat.go.kr/">Statistics Korea (KOSTAT)</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'consumer_key',
            'type': 'text',
            'default': '',
            'name': 'SGIS Service ID (Consumer Key)',
            'required': True
        },
        {
            'id': 'consumer_secret',
            'type': 'text',
            'default': '',
            'name': 'SGIS Security Key (Consumer Secret)',
            'required': True
        },
        {
            'id': 'data_config_header',
            'type': 'header',
            'name': 'Data Configuration'
        },
        {
            'id': 'stat_subject',
            'type': 'select',
            'name': 'Statistic Subject',
            'default': 'population',
            'options': [
                {'name': 'Total Population (인구)', 'value': 'population'},
                {'name': 'Farm Households (농가)', 'value': 'farm'} # Demo endpoint
            ]
        },
        {
            'id': 'stat_year',
            'type': 'text',
            'name': 'Year (YYYY)',
            'default': '2020'
        },
        {
            'id': 'stat_adm_cd',
            'type': 'text',
            'name': 'Target Admin Code (adm_cd)',
            'default': '11',
            'description': 'e.g., 11 (Seoul), 25 (Daejeon). Use Search to find codes.'
        },
        {
            'id': 'visualization_type',
            'type': 'select',
            'name': 'Visualization',
            'default': 'circle',
            'options': [
                {'name': 'GeoJSON Circle', 'value': 'circle'},
                {'name': 'GeoJSON Marker', 'value': 'marker'},
                {'name': 'None (Hidden)', 'value': 'none'}
            ]
        }
    ],
    'dependencies_module': [],
    # Overlay Mode: No base tiles. Only Data/GeoJSON.
    'default_url': '',
    'layer_type': 'geojson',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 20,
        'maxNativeZoom': 13,
        'tms': False
    }
}

class InputModule(AbstractGisInput):
    """
    GIS overlay provider for Statistics Korea (SGIS).
    Provides statistical data layers including population and farm household statistics as GeoJSON.

    @phase active
    @stability experimental
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'geojson' # Strictly GeoJSON
        self.layer_category = 'overlay'
        self.default_url = INPUT_INFORMATION['default_url']

        self.attribution = INPUT_INFORMATION['attribution']
        
        self.consumer_key = self.get_custom_option('consumer_key') or ''
        self.consumer_secret = self.get_custom_option('consumer_secret') or ''
        
        self.access_token = None
        self.token_expiry = 0

    def get_data_content(self):
        """
        Returns GeoJSON data if visualization is enabled.
        Always returns a valid FeatureCollection to ensure Layer Control visibility.
        """
        vis_type = self.get_custom_option('visualization_type')
        # Even if 'none' or no data, we return empty structure to populate Layer Control
        
        features = []
        subject = self.get_custom_option('stat_subject') or 'population'
        year = self.get_custom_option('stat_year') or '2020'

        if vis_type != 'none':
            # Fetch Data based on options
            adm_cd = self.get_custom_option('stat_adm_cd') or '11'
            
            raw_data = self.get_statistics(adm_cd, year, subject)
            
            if isinstance(raw_data, list) and len(raw_data) > 0:
                for item in raw_data:
                    # Construct Property Dict
                    props = {k: v for k, v in item.items()}
                    
                    val = item.get('dt', 'N/A')
                    if subject == 'population':
                        val = item.get('tot_ppltn', val)
                    elif subject == 'farm':
                        val = item.get('farm_cnt', val)

                    props['popupContent'] = f"{item.get('adm_nm', 'Region')}: {val} ({item.get('region_nm', '')})"
                    
                    # Create Feature
                    # Note: Defaulting to Null Geometry if x/y missing.
                    # Ideally we need x/y from search or metadata.
                    # SGIS stats endpoint often returns just data.
                    # To map it, we need geometry.
                    # For V1, if x/y absent, we can't show it.
                    # We rely on user searching first? No.
                    # We rely on specific SGIS endpoints that include location?
                    # 'searchPopulation' result usually lacks x/y unless joined with boundary.
                    # Workaround for Demo: If no x/y, we can't render.
                    # BUT, 'search' endpoint gives x/y. 'get_statistics' might not.
                    # If 'get_statistics' return lacks x/y, we return Empty Features.
                    
                    geometry = None 
                    
                    features.append({
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": props
                    })
        
        # Always return FeatureCollection so LayerFunc is created
        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {"subject": subject, "year": year}
        }

    def _fetch_token(self):
        """
        Fetches a new access token from SGIS API using Key/Secret.
        Tokens are valid for 4 hours.
        """
        if not self.consumer_key or not self.consumer_secret:
            return None
            
        url = "https://sgisapi.kostat.go.kr/OpenAPI3/auth/authentication.json"
        params = {
            'consumer_key': self.consumer_key,
            'consumer_secret': self.consumer_secret
        }
        
        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errCd') == 0:
                    result = data.get('result', {})
                    token = result.get('accessToken')
                    # Set expiry (safety buffer of 10 mins)
                    # Access timeout is typically 4 hours (14400 sec)
                    self.access_token = token
                    self.token_expiry = time.time() + 14000
                    return token
        except:
            pass
        return None

    def get_url(self):
        # Refresh token if needed
        if not self.access_token or time.time() > self.token_expiry:
            self._fetch_token()
            
        token = self.access_token or ''
        return self.default_url.replace('{accessToken}', token)

    # Search: SGIS Geocoding
    search_capabilities = ['address']

    # Statistics: Example - Fetch Population
    def get_statistics(self, adm_cd, year='2020', subject='population'):
        """
        Fetch statistical data for a specific Administrative Code (adm_cd).
        Supports: 'population' (Human), 'farm' (Farm Households)
        """
        # Ensure token
        if not self.access_token or time.time() > self.token_expiry:
            self._fetch_token()
            
        if not self.access_token:
            return {'error': 'SGIS Auth Failed'}
            
        # Select Endpoint
        endpoint = "searchPopulation"
        if subject == 'farm':
            endpoint = "searchFarmHousehold"
            
        url = f"https://sgisapi.kostat.go.kr/OpenAPI3/stats/{endpoint}.json"
        
        params = {
            'accessToken': self.access_token,
            'year': year,
            'adm_cd': adm_cd,
            'low_search': '0' # Searching only this level
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errCd') == 0:
                    # Return the raw result list
                    return data.get('result', [])
                return {'error': f"SGIS Stat Error: {data.get('errMsg')}"}
            return {'error': 'SGIS API Error'}
        except Exception as e:
            return {'error': str(e)}

    def search(self, query, search_type='address', **kwargs):
        # Ensure token
        if not self.access_token or time.time() > self.token_expiry:
            self._fetch_token()
            
        if not self.access_token:
            return {'error': 'SGIS Authentication Failed'}

        url = "https://sgisapi.kostat.go.kr/OpenAPI3/addr/geocode.json"
        params = {
            'accessToken': self.access_token,
            'address': query
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('errCd') == 0:
                    result = data.get('result', {})
                    items = result.get('resultdata', [])
                    
                    parsed_results = []
                    for item in items:
                        # Parse Administrative Code (adm_cd) for stats
                        adm_cd = item.get('adm_cd', '')
                        
                        parsed_results.append({
                            'name': f"{query} (Code: {adm_cd})",
                            'lat': float(item.get('y', 0)),
                            'lng': float(item.get('x', 0)),
                            'address': item.get('road_address', query),
                            'provider': 'sgis',
                            'meta': {
                                'adm_cd': adm_cd,
                                'x': item.get('x'),
                                'y': item.get('y')
                            }
                        })
                    return parsed_results
                    
                return {'error': f"SGIS Error: {data.get('errMsg')}"}
            return {'error': 'SGIS API Error'}
        except Exception as e:
            return {'error': str(e)}
