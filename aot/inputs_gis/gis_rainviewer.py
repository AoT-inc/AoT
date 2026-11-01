# coding=utf-8
import logging
import time
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _

# @manual geo/layers#weather-overlays, geo/layers#rainviewer
INPUT_INFORMATION = {
    'input_name_unique': 'gis_rainviewer',
    'input_manufacturer': lg('RainViewer'),
    'message': lg('RainViewer radar precipitation data overlay. Supports real-time rainfall tracking and animation. Compatible with both vector and raster modes.'),
    'country': ['GL'],
    'input_name': 'RainViewer (Radar)',
    'input_library': 'gis_rainviewer',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.rainviewer.com/',
    'url_api_key': 'https://www.rainviewer.com/api.html',
    'requires_key': True,
    'key_field': 'rainviewer',
    'attribution': 'Map Data &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'ambient_role': 'weather.precip',
    'legend': 'dynamic',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'API Key',
            'required': False,
            'description': 'Optional: Required for premium features'
        },
        {
            'id': 'color_scheme',
            'type': 'select',
            'default': '2',
            'options': [
                {'value': '2', 'name': 'Universal Blue'}
            ],
            'name': 'Color Scheme',
            'required': True,
            'description': 'Note: RainViewer API v2 supports only Universal Blue color scheme'
        },
        {
            'id': 'smoothing',
            'type': 'bool',
            'default': True,
            'name': 'Smoothing',
            'required': False
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://tilecache.rainviewer.com/v2/radar/{ts}/256/{z}/{x}/{y}/{color_scheme}/{smoothing}_1.png',
    'layer_type': 'xyz',
    'time_enabled': True,
    'leaflet_options': {
        'maxNativeZoom': 7,
        'maxZoom': 25
    }
}

logger = logging.getLogger(__name__)

# ── 시간 축 ──────────────────────────────────────────────────────────────────
# 프레임 목록(과거 레이더 + 짧은 예측)은 이 모듈이 업스트림 메타에서 직접 받는다. 지도 위젯 시간 슬라이더는
# 표준 메서드(get_time_range / get_time_steps / get_time_params)로만 묻고 이 주소를 모른다.
_META_URL = 'https://api.rainviewer.com/public/weather-maps.json'
_META_TTL_S = 120.0          # 프레임 목록 캐시(슬라이더를 끌 때마다 업스트림을 부르지 않는다)
_META_RETRY_S = 30.0         # 실패 뒤 다시 시도하기까지
_FRAME_MAX_GAP_S = 900.0     # 시각이 가장 가까운 프레임에서 이만큼 넘게 떨어지면 그 시각의 프레임은 없다
_META = {'at': 0.0, 'frames': []}


def _fetch_frames():
    """업스트림 메타 → [{'time': epoch초, 'ts': URL 자리 값, 'nowcast': bool}] (시각순). 실패하면 None."""
    import requests
    resp = requests.get(_META_URL, timeout=(2, 4))
    resp.raise_for_status()
    radar = (resp.json() or {}).get('radar') or {}
    frames = []
    for kind in ('past', 'nowcast'):
        for it in radar.get(kind) or []:
            try:
                tm = float(it.get('time'))
            except (TypeError, ValueError, AttributeError):
                continue
            path = str(it.get('path') or '')
            ts = path.rstrip('/').rsplit('/', 1)[-1] if path else ''
            frames.append({'time': tm, 'ts': ts or str(int(tm)), 'nowcast': kind == 'nowcast'})
    frames.sort(key=lambda f: f['time'])
    return frames


class InputModule(AbstractGisInput):
    """
    GIS overlay provider for RainViewer radar data.
    Supports both Leaflet (raster mode) and MapLibre (vector mode).
    Uses RainViewer API v2 for radar tile access.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'overlay'
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']
        self.requires_key = True
        self.key_field = 'rainviewer'
        self.time_enabled = True

    def get_url(self):
        # Replace options first
        color = self.get_custom_option('color_scheme')
        if not color: color = '2'
        
        smooth = '1' if self.get_custom_option('smoothing') else '0'
        
        # Get base URL (which already has {api_key} logic if needed)
        base = super().get_url()
        
        # The frontend will need to inject {ts}
        return base.replace('{color_scheme}', color).replace('{smoothing}', smooth)

    def _frames(self):
        """프레임 목록(2분 캐시). 받지 못하면 마지막으로 받은 목록, 그것도 없으면 []."""
        now = time.time()
        if _META['frames'] and now - _META['at'] < _META_TTL_S:
            return _META['frames']
        if not _META['frames'] and now - _META['at'] < _META_RETRY_S:
            return []
        try:
            frames = _fetch_frames()
            _META.update(at=now, frames=frames or [])
        except Exception as exc:                               # noqa: BLE001
            logger.debug('[RainViewer] 프레임 목록 실패: %s', type(exc).__name__)
            # 목록이 있으면 낡은 것을 잠시 더 쓰고, 없으면 잠시 쉰다 — 어느 쪽이든 RETRY 뒤에 다시 시도한다.
            _META['at'] = now - _META_TTL_S + _META_RETRY_S if _META['frames'] else now
        return _META['frames']

    # ── 시간 축 표준 메서드 ──
    def get_time_range(self):
        frames = self._frames()
        if not frames:
            return None
        return {'start': frames[0]['time'], 'end': frames[-1]['time']}

    def get_time_steps(self):
        return [f['time'] for f in self._frames()] or None

    def get_time_params(self, t):
        """시각 ``t`` 에 가장 가까운 레이더 프레임의 ``{ts}`` — 프레임에서 15분 넘게 떨어지면 None."""
        try:
            t = float(t)
        except (TypeError, ValueError):
            return None
        best = None
        for f in self._frames():
            if best is None or abs(f['time'] - t) < abs(best['time'] - t):
                best = f
        if best is None or abs(best['time'] - t) > _FRAME_MAX_GAP_S:
            return None
        return {'ts': best['ts']}

    def get_leaflet_options(self):
        options = super(InputModule, self).get_leaflet_options()
        options.update(INPUT_INFORMATION.get('leaflet_options', {}))
        return options

    # @manual geo/layers#rainviewer
    def get_layer_config(self):
        """
        Override to provide RainViewer-specific configuration for frontend.
        Returns config compatible with MapLibre-GL (raster tile source).
        """
        color_scheme = self.get_custom_option('color_scheme', '2')
        smoothing = '1' if self.get_custom_option('smoothing') else '0'

        # RainViewer API v2 URL pattern (timestamp placeholder for animation)
        # Note: API key is optional for tile access, but recommended
        api_key = self.get_custom_option('api_key', '')

        # Base tile URL with placeholder for timestamp (frontend will inject)
        base_url = (
            f'https://tilecache.rainviewer.com/v2/radar/'
            f'{{ts}}/256/{{z}}/{{x}}/{{y}}/{color_scheme}/{smoothing}_1.png'
        )
        if api_key:
            base_url += f'?key={api_key}'

        config = {
            'unique_id': self.unique_id,
            'name': self.input_dev.name,
            'category': 'overlay',
            'type': 'raster',  # RainViewer is raster tile
            'provider': 'rainviewer',  # Provider identifier
            'url': base_url,
            'attribution': self.attribution,
            'options': {
                'opacity': self.opacity,
                'zIndex': self.z_index,
                'visible': self.is_visible,
                'maxNativeZoom': 7,
                'maxZoom': 25,
                'tileSize': 256,
                'colorScheme': color_scheme,
                'smoothing': smoothing == '1',
                # Animation settings
                'frameInterval': 600,  # 10 minutes between frames
                'totalFrames': 12,     # 2 hours of data
            },
            'legend': self.get_legend(),
            'time_enabled': True,  # RainViewer supports time-based animation
            'api_key': api_key,
            # [GIS Vector Migration] MapLibre-specific source config
            'maplibre': {
                'sourceType': 'raster',
                'tileSize': 256,
                'minzoom': 0,
                'maxzoom': 7,
                'bounds': [-180, -85.0511, 180, 85.0511],
                'animate': True
            }
        }

        return config

    def get_legend(self):
        """
        Returns Legend HTML based on color scheme.
        """
        try:
            scheme = int(self.get_custom_option('color_scheme', 2))
        except:
            scheme = 2

        # Gradients Approximation
        gradients = {
            1: "linear-gradient(to right, #ffffff, #ababab, #575757, #000000)", # Original (Greyscale?) - Actually 'Original' is usually colored. Let's use 2 as default Blue.
            2: "linear-gradient(to right, #d1e5f0, #92c5de, #4393c3, #2166ac, #053061)", # Universal Blue
            3: "linear-gradient(to right, #ffffcc, #a1dab4, #41b6c4, #2c7fb8, #253494)", # TITAN
            4: "linear-gradient(to right, #f7fcf0, #e0f3db, #ccebc5, #a8ddb5, #7bccc4, #4eb3d3, #2b8cbe, #0868ac, #084081)", # TWC
            5: "linear-gradient(to right, #fff5f0, #fee0d2, #fcbba1, #fc9272, #fb6a4a, #ef3b2c, #cb181d, #99000d)", # Meteored
            6: "linear-gradient(to right, #00ff00, #ffff00, #ff0000, #ff00ff)", # NEXRAD
            7: "linear-gradient(to right, #00e600, #ffff00, #ff0000, #ff00ff)", # RAINBOW
            8: "linear-gradient(to right, #f7fbff, #deebf7, #c6dbef, #9ecae1, #6baed6, #4292c6, #2171b5, #08519c, #08306b)" # Dark Sky
        }

        # Fallback for 1 (Original) - often multi-colored
        if scheme == 1:
            grad = "linear-gradient(to right, #cce5ff, #00cd00, #ffff00, #ff0000, #8b008b)" 
        else:
            grad = gradients.get(scheme, gradients[2])

        title = _("Rain/Snow Intensity")
        light = _("Light")
        heavy = _("Heavy")
        snow = _("Snow")
        rain = _("Rain")
        storm = _("Storm")
        html = f"""
        <div class="aot-legend-wrapper">
            <div class="aot-legend-content">
                <div class="aot-legend-title">{title}</div>
                <div class="aot-legend-bar" style="background:{grad};"></div>
                <div class="aot-legend-labels"><span>{light}</span><span>{heavy}</span></div>

                <div style="margin-top:5px; padding-top:4px; border-top:1px solid #eee; display:flex; justify-content:space-between; font-size:9px; color:#555;">
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#ff00ff; display:inline-block; border-radius:50%; margin-right:3px;"></span> {snow}
                   </div>
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#2166ac; display:inline-block; border-radius:50%; margin-right:3px;"></span> {rain}
                   </div>
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#ff0000; display:inline-block; border-radius:50%; margin-right:3px;"></span> {storm}
                   </div>
                </div>
            </div>
            <div class="aot-legend-value-box" 
                 data-api-url="/api/geo/proxy/openmeteo?latitude={{lat}}&longitude={{lon}}&current=precipitation&forecast_days=1" 
                 data-api-param="current.precipitation" 
                 data-unit="mm/h">
                <div class="aot-legend-value-text">--</div>
                <div class="aot-legend-value-unit">mm/h</div>
            </div>
        </div>
        """
        
        return {
            'type': 'html',
            'content': html
        }
