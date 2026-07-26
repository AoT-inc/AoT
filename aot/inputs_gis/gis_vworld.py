# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _
from flask import current_app
import requests
import base64

# Unified Channels Definition (Background + Overlays)
# IDs 0-9: Background (WMTS/XYZ)
# IDs 10+: Overlays (WMS)
CHANNELS = {
    # --- Background Maps (WMTS) ---
    0: {'name': lg('Base Map'), 'type': 'wmts', 'category': 'base', 'options': {'layer': 'Base'}},
    1: {'name': lg('Satellite'), 'type': 'wmts', 'category': 'base', 'options': {'layer': 'Satellite'}},
    2: {'name': lg('Hybrid'), 'type': 'wmts', 'category': 'overlay', 'options': {'layer': 'Hybrid', 'role': 'overlay'}},
    3: {'name': lg('Gray Map'), 'type': 'wmts', 'category': 'base', 'options': {'layer': 'white', 'maxNativeZoom': 18}},
    4: {'name': lg('Dark Map'), 'type': 'wmts', 'category': 'base', 'options': {'layer': 'midnight', 'maxNativeZoom': 18}},

    # --- Data Overlays (WMS) ---
    10: {'name': lg('Cadastral Map'), 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'lp_pa_cbnd_bubun', 'role': 'overlay', 'type': 'wms', 'min_zoom': 16.5, 'min_native_zoom': 18}},
    11: {'name': lg('Agricultural Promotion Area'), 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'dt_d036', 'role': 'overlay', 'type': 'wms', 'url': 'https://api.vworld.kr/ned/wms/FarmngSpceService', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    12: {'name': lg('Ecological Naturalness'), 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'lt_c_uq111', 'role': 'overlay', 'type': 'wms', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    13: {'name': lg('Development Restriction Zone'), 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'LT_C_UD801', 'role': 'overlay', 'type': 'wms', 'style': 'LT_C_UD801', 'min_zoom': 10.5, 'min_native_zoom': 12}},
    14: {'name': lg('Individual Official Land Price'), 'type': 'wms', 'category': 'overlay', 'options': {'layer': 'dt_d150', 'role': 'overlay', 'type': 'wms', 'style': 'dt_d150', 'url': 'https://api.vworld.kr/ned/wms/getIndvdLandPriceWMS', 'min_zoom': 10.5, 'min_native_zoom': 12}},
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
    'message': lg('Vworld spatial information open platform from Korea Ministry of Land, Infrastructure and Transport. Provides the most precise national high-resolution aerial photography, digital maps, cadastral maps, and real-time traffic data. The most specialized national standard map for domestic business support.'),
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
            'default': '', # Default to empty to avoid localhost mismatch
            'name': 'Registered Domain',
            'required': False,
            'description': 'Domain registered with the VWorld API key (e.g. myapp.com). If left empty, the current access URL is used automatically.'
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
            'name': 'Show Legend',
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
    GIS tile provider for VWorld (Korea).
    Supports both base maps (WMTS) and data overlays (WMS) including cadastral, agricultural, and land price data.

    @phase active
    @stability stable
    @dependency AbstractGisInput
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
        
        current_app.logger.debug(f"[VWORLD DEBUG] Type: {c_type}, Layer: {layer_opts.get('layer')}, Domain: {self.vworld_domain}")

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
                'styles': layer_style, # Back to backup setting (empty allowed)
                'format': 'image/png',
                'transparent': True,
                'version': '1.3.0',  # Revert to 1.3.0 as in backup
                'uppercase': False,  # Revert to False as in backup
                'key': self.api_key
            })
            
            # [Fix] Only send domain if explicitly set and not 'localhost'
            # Sending 'localhost' while accessing via IP causes INCORRECT_KEY
            if self.vworld_domain and self.vworld_domain != 'localhost':
                options['domain'] = self.vworld_domain
            
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
        
        v_domain = self.vworld_domain if self.vworld_domain and self.vworld_domain != 'localhost' else ''
        url = 'https://api.vworld.kr/req/image?service=image&request=GetLegendGraphic&format=png&layer={}&style={}&type=ALL&key={}&domain={}'.format(
            layer_name, layer_style, self.api_key, v_domain
        )
        
        try:
            # [CORS Bypass] Fetch image server-side
            response = requests.get(url, timeout=5, verify=False)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '')
            if 'image' not in content_type:
                error_label = _("Error: API returned")
                return {
                    'type': 'html',
                    'content': '<div style="background:white; padding:5px; border-radius:4px; border:1px solid #ccc; color: red;">'
                               f'<div style="font-size:11px;">{error_label} {{}}</div>'.format(content_type) +
                               f'<div style="font-size:10px; color: #333; margin-top:3px;">{{}}</div>'.format(response.text) +
                               '</div>'
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
             error_label = _("Legend Error")
             return {
                'type': 'html',
                'content': '<div style="background:white; padding:5px; border-radius:4px; border:1px solid #ccc;">'
                           f'<div style="font-size:11px; color:red;">{error_label}</div>'
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

    # -------------------------------------------------------------------------
    # Parcel (필지) Lookup Pipeline
    # -------------------------------------------------------------------------

    @staticmethod
    def parcel_from_address(address, api_key, domain=''):
        """
        3-stage pipeline: address → coordinate → PNU → polygon GeoJSON Feature.

        Stage 1: 순방향 지오코딩 (PARCEL 우선, ROAD 재시도)  → (lng, lat)
        Stage 2: 역지오코딩 getAddress → level4AC(법정동코드 10자리) + detail(지번)
                 → PNU 19자리 직접 생성
        Stage 3: Data API attrFilter=pnu:=:{PNU} → 필지 폴리곤 GeoJSON

        WFS 엔드포인트(ServiceExceptionReport) 및 geomFilter(미지원) 모두 사용하지 않는다.

        Returns:
            {'ok': True, 'feature': <GeoJSON Feature>, 'name': str, 'pnu': str}
            {'ok': False, 'error': str}
        """
        import urllib.parse as _up

        def _dp(d):
            return f'&domain={d}' if d else ''

        def _safe_json(resp, label):
            try:
                return resp.json()
            except Exception:
                preview = resp.text[:300].replace('\n', ' ')
                raise ValueError(f'{label} parsing failed (HTTP {resp.status_code}): {preview}')

        def _build_pnu(level4ac, detail):
            """
            법정동코드(10자리) + 지번 detail → PNU 19자리.
            detail 예: "808", "808-2", "산 12", "산 12-3"
            PNU = level4AC(10) + 산지구분(1) + 본번(4) + 부번(4)
            """
            detail = detail.strip()
            if detail.startswith('산'):
                san = '1'
                nums = detail[1:].strip()
            else:
                san = '0'
                nums = detail
            if '-' in nums:
                bonbun, bubun = nums.split('-', 1)
            else:
                bonbun, bubun = nums, '0'
            try:
                return level4ac + san + str(int(bonbun)).zfill(4) + str(int(bubun)).zfill(4)
            except ValueError:
                return None

        # --- Stage 1: 순방향 지오코딩 ---
        coord = None
        for addr_type in ('PARCEL', 'ROAD'):
            try:
                enc = _up.quote(address)
                url = (
                    f'https://api.vworld.kr/req/address'
                    f'?service=address&request=getcoord&crs=epsg:4326'
                    f'&address={enc}&type={addr_type}&format=json'
                    f'&key={api_key}{_dp(domain)}'
                )
                resp = requests.get(url, timeout=10, verify=False)
                data = _safe_json(resp, 'Geocode')
                point = data.get('response', {}).get('result', {}).get('point', {})
                x, y = point.get('x'), point.get('y')
                if x and y:
                    coord = {'x': float(x), 'y': float(y)}
                    break
            except Exception:
                continue

        # getcoord 실패 시 Search API로 폴백 (부분 주소 허용)
        if not coord:
            for search_type in ('address', 'place'):
                try:
                    params = {
                        'service': 'search', 'request': 'search', 'version': '2.0',
                        'crs': 'EPSG:4326', 'size': 1, 'page': 1,
                        'query': address, 'type': search_type,
                        'format': 'json', 'errorformat': 'json', 'key': api_key,
                    }
                    if search_type == 'address':
                        params['category'] = 'parcel'
                    resp = requests.get('https://api.vworld.kr/req/search',
                                        params=params, timeout=10, verify=False)
                    data = _safe_json(resp, 'Search')
                    items = (data.get('response', {})
                                 .get('result', {})
                                 .get('items', []))
                    if items:
                        pt = items[0].get('point', {})
                        x, y = pt.get('x'), pt.get('y')
                        if x and y:
                            coord = {'x': float(x), 'y': float(y)}
                            break
                except Exception:
                    continue

        if not coord:
            return {'ok': False, 'error': f'Address coordinate lookup failed: {address}'}

        lng, lat = coord['x'], coord['y']

        # --- Stage 2: 역지오코딩 → PNU 생성 ---
        # getAddress 응답 result[].structure.level4LC (법정동코드 10자리, PNU용)
        #                               .detail        (지번: "808", "808-2", "산 12" 등)
        # ※ level4AC(행정동코드)가 아니라 level4LC(법정동코드)를 사용해야 함
        # 도로명 주소 → ROAD 지오코딩 좌표는 도로 중앙에 위치해 detail이 빈 경우가 있음.
        # 이 경우 ±0.0001° 오프셋 4방향을 추가로 시도한다.
        pnu = None
        rev_addr = None
        rev_data = {}

        _last_rev_error = ''
        _last_rev_raw = ''

        def _rev_geocode_at(px, py):
            """단일 좌표에서 역지오코딩 시도.
            Returns (level4LC, detail, text, data) or (None, None, None, {}) on failure.
            실패 시 _last_rev_error / _last_rev_raw에 원인 기록 (nonlocal).
            """
            nonlocal _last_rev_error, _last_rev_raw
            try:
                url = (
                    f'https://api.vworld.kr/req/address'
                    f'?service=address&request=getAddress&crs=epsg:4326'
                    f'&point={px},{py}&type=parcel&zipcode=false&simple=false'
                    f'&format=json&key={api_key}{_dp(domain)}'
                )
                r = requests.get(url, timeout=10, verify=False)
                _last_rev_raw = r.text[:400]
                d = _safe_json(r, 'RevGeocode')
                status = d.get('response', {}).get('status', '')
                results = d.get('response', {}).get('result', [])
                _last_rev_error = f'status={status!r} results={len(results)}'
                for item in results:
                    struct = item.get('structure', {})
                    lc = struct.get('level4LC', '')
                    dt = struct.get('detail', '')
                    if lc and dt:
                        return lc, dt, item.get('text', ''), d
                    # detail 비어있어도 lc가 있으면 기록
                    if lc:
                        _last_rev_error += f' level4LC={lc!r} detail={dt!r}'
            except Exception as e:
                _last_rev_error = f'exception: {type(e).__name__}: {e}'
            return None, None, None, {}

        # 원점 시도
        level4lc, detail, rev_addr, rev_data = _rev_geocode_at(lng, lat)
        if not (level4lc and detail):
            # 도로 위 좌표일 경우를 대비해 ±0.0002° 4방향 추가 시도
            OFFSET = 0.0002
            for dlng, dlat in ((OFFSET, 0), (-OFFSET, 0), (0, OFFSET), (0, -OFFSET)):
                level4lc, detail, rev_addr, rev_data = _rev_geocode_at(lng + dlng, lat + dlat)
                if level4lc and detail:
                    break

        if level4lc and detail:
            pnu = _build_pnu(level4lc, detail)

        # --- Stage 3: 폴리곤 조회 ---
        # 3a: PNU 기반 조회 (역지오코딩 성공 시)
        # 3b: geomFilter=POINT 좌표 기반 조회 (역지오코딩 실패 시 폴백)
        items = []
        stage3_error = ''

        def _data_api_fetch(url_extra):
            """Data API 호출 → features 리스트 반환. 실패 시 [] 반환."""
            try:
                url = (
                    f'https://api.vworld.kr/req/data'
                    f'?service=data&request=GetFeature&data=LP_PA_CBND_BUBUN'
                    f'&format=json&key={api_key}{_dp(domain)}{url_extra}'
                )
                r = requests.get(url, timeout=15, verify=False)
                d = _safe_json(r, 'Data API')
                return (
                    d.get('response', {})
                     .get('result', {})
                     .get('featureCollection', {})
                     .get('features', [])
                ), d
            except Exception as e:
                return [], {'_err': str(e)}

        if pnu:
            items, _d3 = _data_api_fetch(f'&attrFilter=pnu:=:{pnu}')
            if not items:
                stage3_error = f'No results found for PNU({pnu})'

        if not items:
            # 폴백: 좌표 포함 필지 검색 (geomFilter POINT, CRS=EPSG:4326)
            # geomFilter 형식: geometry_type@CRS:WKT
            geom_filter = _up.quote(f'POINT({lng} {lat})')
            items, _d3 = _data_api_fetch(
                f'&geomFilter=POINT({lng}%20{lat})&srsName=EPSG:4326'
            )
            if not items:
                # 한국 좌표계(EPSG:5179)로도 시도
                # 단, 좌표 변환 없이 우선 epsg:4326으로만 시도; 실패하면 에러
                rev_info = f'reverse geocoding={_last_rev_error!r}' if _last_rev_error else ''
                return {
                    'ok': False,
                    'error': f'Parcel polygon not found (coordinates: {lat:.6f},{lng:.6f}). {stage3_error} {rev_info}',
                    'raw_preview': _last_rev_raw,
                }

        raw_feat = items[0]
        props = raw_feat.get('properties') or {}
        name = props.get('addr') or rev_addr or address

        feature = {
            'type': 'Feature',
            'geometry': raw_feat.get('geometry'),
            'properties': dict(props),
        }
        feature['properties']['name'] = name
        if pnu:
            feature['properties']['pnu'] = pnu

        return {'ok': True, 'feature': feature, 'name': name, 'pnu': pnu or ''}

    @staticmethod
    def reverse_geocode(lat, lng, api_key, domain=''):
        """
        좌표 → 사람이 읽는 주소 문자열 (VWorld getAddress, 역지오코딩).

        도로명(road) 주소를 우선 조회하고, 결과가 없으면 지번(parcel) 주소로
        폴백한다. parcel_from_address의 _rev_geocode_at과 달리 PNU/필지폴리곤은
        만들지 않고 주소 문자열만 반환하는 단순 조회다.

        Args:
            lat, lng: WGS84 좌표
            api_key: VWorld API key
            domain: 등록된 도메인 (옵션)

        Returns:
            {'ok': True, 'address': str, 'type': 'road'|'parcel'}
            {'ok': False, 'error': str}
        """
        def _dp(d):
            return f'&domain={d}' if d else ''

        def _safe_json(resp, label):
            try:
                return resp.json()
            except Exception:
                preview = resp.text[:300].replace('\n', ' ')
                raise ValueError(f'{label} parsing failed (HTTP {resp.status_code}): {preview}')

        last_error = 'no attempt made'

        def _query(addr_type):
            nonlocal last_error
            url = (
                f'https://api.vworld.kr/req/address'
                f'?service=address&request=getAddress&crs=epsg:4326'
                f'&point={lng},{lat}&type={addr_type}&zipcode=false&simple=false'
                f'&format=json&key={api_key}{_dp(domain)}'
            )
            try:
                resp = requests.get(url, timeout=10, verify=False)
                data = _safe_json(resp, 'RevGeocode')
            except Exception as e:
                last_error = f'{type(e).__name__}: {e}'
                return None
            results = data.get('response', {}).get('result', [])
            if not results:
                status = data.get('response', {}).get('status', '')
                last_error = f'no result (status={status!r})'
                return None
            text = results[0].get('text', '')
            return text or None

        for addr_type in ('road', 'parcel'):
            text = _query(addr_type)
            if text:
                return {'ok': True, 'address': text, 'type': addr_type}

        return {'ok': False,
                'error': f'Reverse geocoding failed for ({lat:.6f}, {lng:.6f}): {last_error}'}

    @staticmethod
    def parcels_from_addresses(addresses, api_key, domain=''):
        """
        Batch parcel lookup for a list of addresses.

        Args:
            addresses: list of str
            api_key: VWorld API key
            domain: registered domain for the API key (optional)

        Returns:
            {
                'ok': True,
                'features': [GeoJSON Feature, ...],
                'errors': [str, ...],
                'names': [str, ...]
            }
        """
        features = []
        errors = []
        names = []

        for addr in addresses:
            result = InputModule.parcel_from_address(addr, api_key, domain)
            if result.get('ok'):
                features.append(result['feature'])
                names.append(result.get('name', addr))
            else:
                errors.append(f'{addr}: {result.get("error", "unknown")}')

        return {
            'ok': True,
            'features': features,
            'errors': errors,
            'names': names,
        }
