# coding=utf-8
import time
from aot.inputs.base_input import AbstractInput
from aot.inputs_gis.ambient_roles import (
    AMBIENT_ABOVE_Z_DEFAULT, AMBIENT_TILE_ALPHA_DEFAULT, TIME_FRAMES_MAX, normalize_ambient_above_z,
    normalize_ambient_role, normalize_ambient_theme, normalize_ambient_tile_alpha,
    normalize_time_params, normalize_time_range, normalize_time_steps)

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

    def _device_local_now(self):
        """이 GIS 입력의 위치 기준 현재 로컬 datetime (tz-aware).

        위성 타일 '오늘/어제' 날짜를 시설 로컬 날짜로 고르기 위함 — UTC 기준이면
        KST 등에서 하루 어긋날 수 있다(audit P4, timezone-management.md §11).
        해석 실패 시 UTC now 로 폴백.
        """
        try:
            from aot.utils.device_tz import resolve_location_tz
            from aot.utils.timekit import to_tz, utc_now
            return to_tz(utc_now(), resolve_location_tz(self.unique_id))
        except Exception:
            import datetime as _dt
            return _dt.datetime.now(_dt.timezone.utc)

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

    def _module_namespace(self):
        """이 입력을 정의한 모듈의 전역(CHANNELS·INPUT_INFORMATION 이 든 곳).

        지도 레이어 목록은 입력 모듈을 파일에서 직접 불러 만들어(load_module_from_file)
        sys.modules 에 없을 수 있다 — 그때는 생성자 함수의 전역으로 간다.
        """
        import sys
        mod = sys.modules.get(self.__module__)
        if mod is not None and hasattr(mod, 'INPUT_INFORMATION'):
            return vars(mod)
        return getattr(type(self).__init__, '__globals__', {}) or {}

    def _active_channel_def(self):
        """모듈 CHANNELS 에서 지금 선택된(첫) 채널 정의. 없으면 {}."""
        channels = self._module_namespace().get('CHANNELS')
        if not isinstance(channels, dict) or not channels:
            return {}
        active = self.get_custom_option('active_channels')
        if isinstance(active, list):
            active = active[0] if active else None
        try:
            ch_id = int(active)
        except (TypeError, ValueError):
            ch_id = 0
        return channels.get(ch_id) or channels.get(0) or {}

    def get_ambient_meta(self):
        """(ambient_role, ambient_theme) — 없으면 각각 None.

        우선순위: 사용자 custom option → 선택 채널 options → 모듈 INPUT_INFORMATION.
        그 아래(키 이름·time_enabled·category 추정)는 프런트 분류기가 맡는다.
        """
        ch = self._active_channel_def()
        ch_opts = ch.get('options') or {}
        info = self._module_namespace().get('INPUT_INFORMATION') or {}
        role = (normalize_ambient_role(self.get_custom_option('ambient_role'))
                or normalize_ambient_role(ch_opts.get('ambient_role'))
                or normalize_ambient_role(info.get('ambient_role')))
        theme = (normalize_ambient_theme(ch_opts.get('ambient_theme'))
                 or normalize_ambient_theme(info.get('ambient_theme')))
        return role, theme

    def get_ambient_above_z(self):
        """unknown 레이어를 도형 위로 올리는 zIndex 문턱 — 이 레이어의 py 가 정한다.

        우선순위: 사용자 custom option → 선택 채널 options → 모듈 INPUT_INFORMATION →
        ``ambient_roles.AMBIENT_ABOVE_Z_DEFAULT``. 프런트는 이 값을 그대로 읽는다.
        """
        ch_opts = (self._active_channel_def() or {}).get('options') or {}
        info = self._module_namespace().get('INPUT_INFORMATION') or {}
        for cand in (self.get_custom_option('ambient_above_z'),
                     ch_opts.get('ambient_above_z'),
                     info.get('ambient_above_z')):
            v = normalize_ambient_above_z(cand)
            if v is not None:
                return v
        return AMBIENT_ABOVE_Z_DEFAULT

    def get_ambient_tile_alpha(self):
        """원천 타일 자체의 평균 알파(0.1~1) — 이 레이어의 py 가 정한다.

        프런트가 정책 불투명도를 이만큼 보정한다(반투명 타일이 정책값보다 더 흐려 보이지 않게).
        우선순위는 get_ambient_above_z 와 같다. 모르면 1(보정 없음).
        """
        ch_opts = (self._active_channel_def() or {}).get('options') or {}
        info = self._module_namespace().get('INPUT_INFORMATION') or {}
        for cand in (self.get_custom_option('ambient_tile_alpha'),
                     ch_opts.get('ambient_tile_alpha'),
                     info.get('ambient_tile_alpha')):
            v = normalize_ambient_tile_alpha(cand)
            if v is not None:
                return v
        return AMBIENT_TILE_ALPHA_DEFAULT

    def apply_ambient_meta(self, options):
        """options 딕셔너리에 ambient_role / ambient_theme / ambient_above_z / ambient_tile_alpha 를 넣는다."""
        try:
            role, theme = self.get_ambient_meta()
            above_z = self.get_ambient_above_z()
            tile_alpha = self.get_ambient_tile_alpha()
        except Exception:
            return options
        if role:
            options['ambient_role'] = role
        if theme:
            options['ambient_theme'] = theme
        options['ambient_above_z'] = above_z
        options['ambient_tile_alpha'] = tile_alpha
        return options

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
        # 지도 위젯 기상 표현용 역할 — get_leaflet_options() 에 싣는다. 위젯이 받는 레이어
        # 목록(utils_geo.get_active_geo_layers)이 이 옵션을 그대로 옮기기 때문이다.
        self.apply_ambient_meta(options)
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

    def get_ambient_values(self, lat, lng):
        """
        지도 위젯 기상 표현이 쓰는 현재 기상 값 — 기상 값을 줄 수 있는 모듈만 덮어쓴다(기본 None).

        표준 키·단위(``ambient_roles.AMBIENT_ITEM_UNITS``)로 돌려준다:
        precip mm/h · wind_speed m/s · wind_dir ° · cloud % · visibility km · temp °C.
        선택 키: precip_type(강수 종류 코드 1 비·2 눈·3 진눈깨비·4 우박) · lightning(최근 낙뢰 수) ·
        lightning_km(가장 가까운 낙뢰 거리 km). 제공하는 모듈만 채운다 — 없으면 그 표현도 없다.

        Returns:
            dict or None: ``{'values': {key: number}, 'at': 관측 epoch 초 | None}``.
            값이 없는 키는 빼고, 환산·제공자별 결측 처리는 이 모듈 안에서 끝낸다.
            ``at`` 를 모르면 None(= 방금 받은 값으로 본다).
        """
        return None

    def get_ambient_forecast_range(self):
        """예보 값을 줄 수 있는 구간 — 예보를 주는 모듈만 덮어쓴다(기본 None).

        Returns:
            dict or None: ``{'start': epoch초, 'end': epoch초, 'step_s': 눈금 간격(초)}``.
            외부 호출 없이 모듈이 아는 값(예보 지평선)으로 답한다 — 슬라이더가 범위를 정할 때마다 불린다.
        """
        return None

    def get_ambient_forecast(self, lat, lng, t):
        """시각 ``t``(epoch 초, 미래)의 예보 값 — 예보를 주는 모듈만 덮어쓴다(기본 None).

        ``get_ambient_values`` 와 같은 표준 키·단위로 돌려준다:
        ``{'values': {key: number}, 'at': 예보 시각 epoch초, 'confidence': 0~1(선택)}``.
        예보 간격 사이의 시각은 모듈이 보간하거나 가까운 값을 고른다. 범위 밖이거나 값이 없으면 None.
        """
        return None

    def get_ambient_history_range(self):
        """관측 이력을 줄 수 있는 구간 — 이력을 주는 모듈만 덮어쓴다(기본 None). 모양은 예보 범위와 같다."""
        return None

    def get_ambient_history(self, lat, lng, t):
        """시각 ``t``(epoch 초, 과거)의 관측 값 — 이력을 주는 모듈만 덮어쓴다(기본 None). 모양은 ``get_ambient_values`` 와 같다."""
        return None

    # ── 시간 축(지도 위젯 시간 슬라이더) ─────────────────────────────────────
    # ``time_enabled`` 타일 레이어가 과거·예보 프레임을 슬라이더 시각으로 바꿀 수 있게 하는 표준 메서드.
    # 제공자(프레임 목록을 어디서 받는지, URL 의 어느 자리를 바꾸는지)는 각 모듈 py 안에서만 안다.

    def get_time_range(self):
        """프레임이 있는 구간 ``{'start': epoch초, 'end': epoch초}`` — 시간을 지원하는 모듈만 덮어쓴다(기본 None)."""
        return None

    def get_time_steps(self):
        """눈금 — epoch 초 목록 또는 ``{'every_s': 간격}``. 슬라이더는 가장 촘촘한 레이어를 따른다(기본 None)."""
        return None

    def get_time_params(self, t):
        """시각 ``t``(epoch 초)에 해당하는 프레임의 URL 자리 값 ``{자리표시자: 값}`` (예: ``{'ts': '1730000000'}``).

        슬라이더는 레이어 URL 템플릿의 ``{이름}`` 자리를 이 값으로 바꾼다. 그 시각의 프레임이 없으면 None.
        """
        return None

    def get_time_info(self):
        """슬라이더가 한 번에 읽는 시간 정보 — 서버 경로(``/api/geo/layer_time/<id>``)가 그대로 내보낸다.

        ``time_enabled`` 가 아니거나 범위·눈금·프레임이 하나도 없으면 None. 시각은 모두 epoch 밀리초:
        ``{'range': {'start_ms', 'end_ms'}, 'frames': [{'t', 'params'}, …]}``.
        """
        if not self.time_enabled:
            return None
        rng = normalize_time_range(self.get_time_range())
        if not rng:
            return None
        steps = normalize_time_steps(self.get_time_steps(), rng)
        if not steps:
            return None
        frames = []
        for s in steps[:TIME_FRAMES_MAX]:
            params = normalize_time_params(self.get_time_params(s))
            if params is not None:
                frames.append({'t': int(s * 1000), 'params': params})
        if not frames:
            return None
        return {'range': {'start_ms': int(rng['start'] * 1000), 'end_ms': int(rng['end'] * 1000)},
                'frames': frames}

    def get_ambient_max_age(self):
        """관측 시각이 이보다 오래된 값은 쓰지 않는다(초) — 이 모듈의 관측 주기를 아는 py 가 정한다.

        위젯 옵션 ``max_measure_age`` 가 더 크면 그쪽이 이긴다. 기본 0(= 위젯 옵션만).
        """
        return 0

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
