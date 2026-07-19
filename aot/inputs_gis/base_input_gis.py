# coding=utf-8
import time
from aot.inputs.base_input import AbstractInput

class AbstractGisInput(AbstractInput):
    """
    Abstract GIS Input Class that provides a base for all GIS map tile providers.
    Supports Tile layers, WMS, and GeoJSON with secure API key handling
    and category management (Base vs Overlay).

    @phase active
    @stability stable
    @dependency AbstractInput
    """
    def __init__(self, input_dev, testing=False, name=__name__):
        super(AbstractGisInput, self).__init__(input_dev, testing=testing, name=name)
        
        # 1. Core GIS Attributes
        self.layer_type = 'tile'     # tile, wms, geojson, vector_tile
        self.layer_category = 'base' # base (배경), overlay (데이터)
        self.default_url = ''
        self.api_key = ''            # API 키가 필요한 경우 설정
        self.attribution = ''
        
        # 2. Visualization Options
        self.opacity = 1.0
        self.z_index = 1
        self.is_visible = True
        
        # 3. Time & Interaction
        self.time_enabled = False
        self.refresh_interval = 0  # seconds; 0 = no auto-refresh
        
        # 4. Global API Keys (Injected by parent context if applicable)
        self.global_api_keys = {}

    def get_custom_option(self, option, default_return=None):
        """
        Extends default option retrieval with global API key fallback.
        """
        # 1. Check local attribute cache first (Injected by SatelliteAnalysis)
        val = None
        if hasattr(self, 'custom_options') and self.custom_options:
            if isinstance(self.custom_options, dict):
                val = self.custom_options.get(option)
            elif isinstance(self.custom_options, str) and self.custom_options.startswith('{'):
                try:
                    import json
                    opts = json.loads(self.custom_options)
                    val = opts.get(option)
                except:
                    pass
        
        # 2. Fallback to DB query if still not found
        if val is None:
            val = super(AbstractGisInput, self).get_custom_option(option, default_return=default_return)
        
        # 3. If no local value, and it's an API key field, try Global Keys
        if (not val or val == '') and hasattr(self, 'global_api_keys') and self.global_api_keys:
            try:
                import sys
                module = sys.modules[self.__module__]
                if hasattr(module, 'INPUT_INFORMATION'):
                    info = module.INPUT_INFORMATION
                    kf = info.get('key_field')
                    gkf = info.get('global_key_field', kf)
                    
                    if option == kf and gkf in self.global_api_keys:
                        val = self.global_api_keys[gkf]
            except:
                pass
        
        return val
        
    def get_layer_config(self):
        """
        Returns the full configuration for the frontend Leaflet layer.
        """
        config = {
            'unique_id': self.unique_id,
            'name': self.input_dev.name,
            'category': self.layer_category,
            'type': self.layer_type,
            'url': self.get_url(),
            'attribution': self.attribution,
            'options': self.get_leaflet_options(),
            'legend': self.get_legend(),  # 범례 정보 (URL, HTML 문자열, 또는 데이터 객체)
            'time_enabled': self.time_enabled,
            'refresh_interval': self.refresh_interval,
        }
        
        # GeoJSON 같은 데이터 타입은 URL 대신 data 필드에 내용을 담을 수 있음
        data_content = self.get_data_content()
        if data_content:
            config['data'] = data_content
            
        return config

    def get_url(self):
        """
        Returns the formatted URL. Automatically injects API key if present.
        """
        url = self.default_url
        if self.api_key and '{api_key}' in url:
            return url.replace('{api_key}', self.api_key)
        return url

    def get_leaflet_options(self):
        """
        Standard Leaflet options plus WMS specific params.
        """
        options = {
            'opacity': self.opacity,
            'zIndex': self.z_index,
            'visible': self.is_visible
        }
        # WMS 등의 추가 파라미터 병합
        options.update(self.get_extra_params())
        return options

    def get_extra_params(self):
        """
        Hook for adding WMS params (layers, format, transparent) or style objects.
        """
        return {}

    def get_data_content(self):
        """
        Used for Vector layers (GeoJSON) to return raw data instead of a tile URL.
        """
        return None

    def get_legend(self):
        """
        Returns legend information.
        Can be:
        - None (no legend)
        - String (URL to image)
        - Dictionary (Structured data for gradient/discrete legend)
          e.g. {'type': 'gradient', 'colors': [...], 'min': 0, 'max': 100}
        """
        return None

    def get_ai_reading(self, lat, lng):
        """
        Returns a human-readable AI summary of this GIS layer's data at the given coordinates.
        Each GIS module should override this to provide its own data.
        
        Returns:
            list[dict] or None: List of readings, each with:
                - 'label': Human-readable name (e.g. 'Soil pH (0-5cm)')
                - 'value': Numeric or text value
                - 'unit': Unit string (e.g. 'pH', '°C', '%')
            Returns None if data is unavailable or the module doesn't support AI reading.
        """
        return None

    def get_measurement(self):
        """
        Returns status.
        """
        return {
            'value': 1 if self.is_visible else 0,
            'unit': 'status',
            'measurement': 'layer_active'
        }

    def get_tile_data(self, z, x, y):
        """
        [Generic Proxy Support]
        Returns raw tile data (bytes) and mimetype for backend proxying.
        Used to solve Mixed Content (HTTP tiles on HTTPS) or Auth headers.
        
        Returns:
            (bytes, mimetype) tuple or None if failed/not supported.
        """
        return None

    # 4. Search Services
    search_capabilities = [] # e.g. ['address', 'place', 'latlng']

    def search(self, query, search_type='address', **kwargs):
        """
        Execute a search query using this GIS provider.
        
        Args:
            query (str): The search term (e.g., 'Seoul', 'Gangnam-gu')
            search_type (str): Type of search ('address', 'place', etc.)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            list: A list of result dictionaries. Each result should ideally have:
                  {
                      'name': 'Display Name',
                      'lat': 37.123,
                      'lng': 127.123,
                      'address': 'Full Address',
                      'meta': { ...raw data... }
                  }
            Or None if not supported/failed.
        """
        return None
