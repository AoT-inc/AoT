# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
from flask import current_app
import requests
import base64

# Unified Channels Definition (Background + Overlays)
# IDs 0-9: Background (WMTS/XYZ)
# IDs 10+: Overlays (WMS)
CHANNELS = {
    # --- Background Maps (WMTS) ---
    0: {'name': '기본지도', 'type': 'wmts', 'category': 'base', 'options': {'layer': 'Base'}},
    1: {'name': '위성지도', 'type': 'wmts', 'category': 'base', 'options': {'layer': 'Satellite'}},
    2: {'name': '하이브리드', 'type': 'wmts', 'category': 'overlay', 'options': {'layer': 'Hybrid', 'role': 'overlay'}},
    3: {'name': '회색지도', 'type': 'wmts', 'category': 'base', 'options': {'layer': 'white', 'maxNativeZoom': 18}},
    4: {'name': '어두운지도', 'type': 'wmts', 'category': 'base', 'options': {'layer': 'midnight', 'maxNativeZoom': 18}},

    # --- Data Overlays (WMS) ---
    10: {'name': '지적도', 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'lp_pa_cbnd_bubun', 'role': 'overlay', 'type': 'wms', 'min_zoom': 16.5, 'min_native_zoom': 18}},
    11: {'name': '농업진흥지역도', 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'dt_d036', 'role': 'overlay', 'type': 'wms', 'url': 'https://api.vworld.kr/ned/wms/FarmngSpceService', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    12: {'name': '생태자연도', 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'lt_c_uq111', 'role': 'overlay', 'type': 'wms', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    13: {'name': '개발제한구역', 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'LT_C_UD801', 'role': 'overlay', 'type': 'wms', 'style': 'LT_C_UD801', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    14: {'name': '개별공시지가', 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'dt_d150', 'role': 'overlay', 'type': 'wms', 'style': 'dt_d150', 'url': 'https://api.vworld.kr/ned/wms/getIndvdLandPriceWMS', 'min_zoom': 10.5, 'min_native_zoom': 12}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_vworld',
    'input_manufacturer': 'Vworld',
    'country': ['KO'],
    'input_name': 'Vworld',
    'input_library': 'gis_vworld',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.vworld.kr/',
    'url_api_key': 'https://www.vworld.kr/dev/v4dv_apikey_s001.do',
    'attribution': '<a href="https://www.vworld.kr/" target="_blank"><img src="https://www.vworld.kr/img/img_opentype01.png" alt="Vworld" style="height:28px;"></a>',
    'key_field': 'api_key',
    'global_key_field': 'vworld', # Reuse VWorld Key
    'message': lg('대한민국 국토교통부의 공간정보 오픈플랫폼 브이월드 서비스입니다. 국내에서 가장 정밀한 국가 고해상도 항공 사진과 수치 지도, 지적도, 실시간 교통량 등을 제공하며 국내 업무 지원에 가장 특화된 국가 국가표준 지도입니다.'),
    'requires_key': True,
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    # Layer role is dynamic, set default here but will be overridden
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'API Key',
            'required': True
        },
        {
            'id': 'vworld_domain',
            'type': 'text',
            'default': 'localhost',
            'name': '등록 도메인',
            'required': True,
            'description': 'Domain registered with the VWorld API Key (e.g., localhost, myapp.com)'
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Map Layer / Style',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        },
        {
            'id': 'show_legend',
            'type': 'bool',
            'default': True,
            'name': '범례 보기',
            'required': False
        }
    ],
    'dependencies_module': [],
    # Default URL template (will be dynamic)
    'default_url': 'https://api.vworld.kr/req/wmts/1.0.0/{api_key}/{layer}/{z}/{y}/{x}.png',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'minZoom': 6,
        'maxNativeZoom': 19,
        'maxZoom': 22
    }
}

class InputModule(AbstractGisInput):
    """
    Unified VWorld Input Module.
    Supports both Base Maps (WMTS) and Data Overlays (WMS) dynamically.
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.attribution = INPUT_INFORMATION['attribution']
        self.api_key = self.get_custom_option('api_key') or ''
        self.vworld_domain = self.get_custom_option('vworld_domain') or 'localhost'
        
        # Initialize dynamic properties based on current channel
        self._update_layer_properties()

    def _get_active_channel_id(self):
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
        return layer_id

    def _get_active_channel_info(self):
        layer_id = self._get_active_channel_id()
        from aot.inputs_gis.gis_vworld import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]
        return CHANNELS[0]

    def _update_layer_properties(self):
        """Update self.layer_category and self.layer_type based on active channel."""
        channel_info = self._get_active_channel_info()
        self.layer_category = channel_info.get('category', 'base')
        
        # Internal type mapping to Leaflet types
        c_type = channel_info.get('type', 'wmts')
        if c_type == 'wms':
            self.layer_type = 'wms'
        else:
            self.layer_type = 'tile' # Default to tile for WMTS/XYZ

    def get_layer_config(self):
        """Override to ensure dynamic properties are reflected in config."""
        self._update_layer_properties()
        return super(InputModule, self).get_layer_config()

    def get_url(self):
        """Dispatch URL generation based on channel type."""
        channel_info = self._get_active_channel_info()
        c_type = channel_info.get('type', 'wmts')
        layer_opts = channel_info.get('options', {})
        
        # Refresh credentials
        self.api_key = self.get_custom_option('api_key') or ''
        
        if c_type == 'wms':
            # WMS Logic (from gis_vworld_wms.py)
            return layer_opts.get('url', 'https://api.vworld.kr/req/wms')
            
        else:
            # WMTS Logic (from gis_vworld.py)
            layer = layer_opts.get('layer', 'Base')
            
            # Direct HTTPS Optimization
            if layer == 'Satellite':
                return f'https://api.vworld.kr/req/wmts/1.0.0/{self.api_key}/Satellite/{{z}}/{{y}}/{{x}}.jpeg'
            elif layer == 'Hybrid':
                return f'https://api.vworld.kr/req/wmts/1.0.0/{self.api_key}/Hybrid/{{z}}/{{y}}/{{x}}.png'
            
            return f'https://api.vworld.kr/req/wmts/1.0.0/{self.api_key}/{layer}/{{z}}/{{y}}/{{x}}.png'

    def get_leaflet_options(self):
        """Dispatch options based on channel type."""
        channel_info = self._get_active_channel_info()
        c_type = channel_info.get('type', 'wmts')
        layer_opts = channel_info.get('options', {})
        
        # Debug Print to Console
        current_app.logger.info(f"[VWORLD DEBUG] Type: {c_type}, Layer: {layer_opts.get('layer')}, Domain: {self.vworld_domain}")

        options = super(InputModule, self).get_leaflet_options()
        
        # [Fix] Refresh Credentials (Critical for WMS/WMTS)
        self.api_key = self.get_custom_option('api_key') or ''
        self.vworld_domain = self.get_custom_option('vworld_domain') or 'localhost'
        
        if c_type == 'wms':
            # Remove WMTS specific defaults that might interfere with WMS
            options.pop('maxNativeZoom', None)
            options.pop('maxZoom', None)
            options.pop('minZoom', None)

            # WMS Options
            layer_name = layer_opts.get('layer', '')
            # [Fix] Default style should be empty, not layer name (causes errors if style doesn't exist)
            layer_style = layer_opts.get('style', '')
            
            # WMS Specifics
            options.update({
                'layers': layer_name,
                'styles': layer_style,
                'format': 'image/png',
                'transparent': True,
                'version': '1.3.0',
                'uppercase': False,
                # 'crs': L.CRS.EPSG3857, # REMOVED: L is not defined in backend
                'key': self.api_key,
                'domain': self.vworld_domain or 'localhost'
            })
            
            # Zoom Strategies
            if 'min_zoom' in layer_opts:
                options['minZoom'] = layer_opts['min_zoom']
            if 'min_native_zoom' in layer_opts:
                options['minNativeZoom'] = layer_opts['min_native_zoom']
                
        else:
            # WMTS Options
            defaults = {
                'minZoom': 6,
                'maxNativeZoom': 19,
                'maxZoom': 22
            }
            # Only apply defaults if not overridden by channel options
            for k, v in defaults.items():
                if k not in layer_opts:
                    options[k] = v
                else:
                    options[k] = layer_opts[k]
            
        return options

    def get_legend(self):
        """Return legend only for WMS overlay channels."""
        if not self.get_custom_option('show_legend'):
            return None
            
        # [Fix] Refresh Credentials for Legend
        self.api_key = self.get_custom_option('api_key') or ''
        self.vworld_domain = self.get_custom_option('vworld_domain') or 'localhost'
            
        channel_info = self._get_active_channel_info()
        if channel_info.get('category') != 'overlay' or channel_info.get('type') != 'wms':
            return None
            
        layer_opts = channel_info.get('options', {})
        layer_name = layer_opts.get('layer', '')
        layer_style = layer_opts.get('style', layer_name)
        
        url = 'https://api.vworld.kr/req/image?service=image&request=GetLegendGraphic&format=png&layer={}&style={}&type=ALL&key={}&domain={}'.format(
            layer_name, layer_style, self.api_key, self.vworld_domain or 'localhost'
        )
        
        try:
            # [CORS Bypass] Fetch image server-side
            response = requests.get(url, timeout=5, verify=False)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type:
                return {
                    'type': 'html',
                    'content': '<div style="background:white; padding:5px; border-radius:4px; border:1px solid #ccc; color: red;">'
                               '<div style="font-size:11px;">Error: API returned {}</div>'
                               '<div style="font-size:10px; color: #333; margin-top:3px;">{}</div>'
                               '</div>'.format(content_type, response.text)
                }

            img_b64 = base64.b64encode(response.content).decode('utf-8')
            img_src = "data:image/png;base64,{}".format(img_b64)
            
            return {
                'type': 'html',
                'content': '<div style="background:white; padding:5px; border-radius:4px; border:1px solid #ccc;">'
                           '<img src="{}" alt="Legend">'
                           '</div>'.format(img_src)
            }
        except Exception:
             return {
                'type': 'html',
                'content': '<div style="background:white; padding:5px; border-radius:4px; border:1px solid #ccc;">'
                           '<div style="font-size:11px; color:red;">Legend Error</div>'
                           '</div>'
            }

    # VWorld Search Implementation (Shared)
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        """
        VWorld Search API (2.0) - Improved Context Version
        """
        self.api_key = self.get_custom_option('api_key') or ''
        
        if not self.api_key:
            return {'error': 'API Key Missing'}

        url = "https://api.vworld.kr/req/search"
        limit = kwargs.get('limit', 10)
        
        search_stages = [
            {'type': 'place', 'category': None},
            {'type': 'address', 'category': 'road'},
            {'type': 'address', 'category': 'parcel'}
        ]
        
        all_results = []
        seen_coords = set()
        seen_names = set()
        errors = []

        for stage in search_stages:
            if len(all_results) >= limit:
                break

            params = {
                'service': 'search',
                'request': 'search',
                'version': '2.0',
                'crs': 'EPSG:4326',
                'size': limit,
                'page': 1,
                'query': query,
                'type': stage['type'],
                'format': 'json',
                'errorformat': 'json',
                'key': self.api_key
            }
            if stage['category']:
                params['category'] = stage['category']

            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                response_obj = data.get('response', {})
                status = response_obj.get('status')
                
                if status != 'OK':
                    if status != 'NOT_FOUND':
                        err_msg = response_obj.get('error', {}).get('text', status)
                        errors.append(f"{stage['type']}: {err_msg}")
                    continue

                items = response_obj.get('result', {}).get('items', [])
                for item in items:
                    point = item.get('point', {})
                    lng = float(point.get('x', 0))
                    lat = float(point.get('y', 0))
                    
                    if lng == 0 and lat == 0:
                        continue

                    title = item.get('title', '').replace('<b>', '').replace('</b>', '')
                    address_obj = item.get('address', {})
                    addr_road = address_obj.get('road', '')
                    addr_parcel = address_obj.get('parcel', '')
                    
                    coord_key = (round(lat, 5), round(lng, 5))
                    name_key = (title + (addr_road or addr_parcel)).strip()
                    
                    if coord_key in seen_coords or name_key in seen_names:
                        continue
                    
                    seen_coords.add(coord_key)
                    seen_names.add(name_key)

                    # [Context Logic]
                    full_address = addr_parcel or addr_road
                    display_name = title
                    
                    if full_address:
                         if not display_name or (display_name in full_address):
                             display_name = full_address
                         elif display_name != full_address:
                             display_name = f"{title} ({full_address})"
                    
                    if not display_name:
                        display_name = "Unknown Location"

                    all_results.append({
                        'name': display_name,
                        'address': full_address,
                        'address_road': addr_road,
                        'address_parcel': addr_parcel,
                        'lat': lat,
                        'lng': lng,
                        'provider': 'vworld'
                    })
            except Exception as e:
                errors.append(f"{stage['type']}: {str(e)}")
                continue

        if not all_results and errors:
            return {'error': " | ".join(errors)}

        return all_results[:limit]
