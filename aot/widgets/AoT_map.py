# coding=utf-8
#
#  AoT_map.py - Leaflet map widget to place devices on a map
#
import logging
import json
from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements
from flask_babel import lazy_gettext

from aot.aot_flask.geo.widget.maps import generate_page_variables_logic
from aot.aot_flask.utils.utils_geo import get_available_config_options as _get_available_config_options


logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Widget Definition
# ------------------------------------------------------------------------------

def execute_at_modification(mod_widget, request_form, custom_options_presave, custom_options_postsave):
    """
    Standardized storage logic using framework-native custom_options scheme.
    """
    options = {}
    try:
        if mod_widget.custom_options:
            options = json.loads(mod_widget.custom_options) if isinstance(mod_widget.custom_options, str) else dict(mod_widget.custom_options)
    except: pass

    final_options = options.copy()
    
    # 1. Framework Auto-parsed Merge (Highest Reliability)
    if custom_options_postsave:
        for k, v in custom_options_postsave.items():
            final_options[k] = v

    # 2. Manual/Legacy Exception Handling
    if request_form:
        # Resolve 'device_ids' from measurement selectors if needed (Legacy Support)
        manual_logic_keys = ['device_selection_input', 'device_selection_output', 'device_selection_function']
        selected_dev_unique_ids = []
        for key in manual_logic_keys:
            raw_val = final_options.get(key, '')
            if raw_val:
                if isinstance(raw_val, list):
                    ids = [str(x).strip() for x in raw_val if str(x).strip()]
                elif isinstance(raw_val, str):
                    ids = [x.strip() for x in raw_val.split(',') if x.strip()]
                else: ids = []
                selected_dev_unique_ids.extend(ids)
        
        if selected_dev_unique_ids:
            final_options['device_ids'] = selected_dev_unique_ids
            final_options['include_all_devices'] = False
        elif not final_options.get('include_all_devices'):
             final_options['device_ids'] = []
             final_options['include_all_devices'] = False

    # 3. Handle Map Change -> Reset View if Map Changed
    old_map_uuid = str(options.get('map_uuid', '')).strip().lower()
    new_map_uuid = str(final_options.get('map_uuid', '')).strip().lower()

    if old_map_uuid and new_map_uuid and old_map_uuid != new_map_uuid:
        logger.info(f"[AoT Map Save] Map changed from {old_map_uuid} to {new_map_uuid}. Resetting view.")
        for vk in ['fallback_latitude', 'fallback_longitude', 'default_zoom']:
            if vk in final_options: 
                logger.info(f"[AoT Map Save] Deleting {vk} due to map change.")
                del final_options[vk]
    else:
        logger.debug(f"[AoT Map Save] Map unchanged ({new_map_uuid}). Preserving view.")

    return True, True, mod_widget, final_options


def generate_page_variables(widget_unique_id, widget_options):
    """
    Prepare variables for template rendering using modular logic.
    """
    return generate_page_variables_logic(widget_unique_id, widget_options)


# ------------------------------------------------------------------------------
# Widget HTML Templates (Embedded)
# ------------------------------------------------------------------------------

WIDGET_HEAD_HTML = """


<!-- MarkerCluster Vendor Assets -->
<link rel="stylesheet" href="/static/css/map/MarkerCluster.css">
<link rel="stylesheet" href="/static/css/map/MarkerCluster.Default.css">
<script src="/static/js/map/leaflet.markercluster.js?v=1.0.0"></script>

<!-- Flattened imports for deployment simplicity -->
<script src="/static/js/geo/aot-map-utils.js"></script>
<script src="/static/js/geo/aot-map-data.js"></script> 
<script src="/static/js/geo/aot-map-custom-controls.js"></script>
<script src="/static/js/geo/aot-map-alignment.js?v=3.0"></script>
<!-- aot-map-loader.js is already in layout.html -->
<script src="/static/js/geo/aot-map-controls.js"></script>
<script src="/static/js/widget/AoT_map/aot-stopwatch-manager.js"></script>
<!-- search components are already in layout.html -->
<script src="/static/js/widget/AoT_map/aot-map-widget-v3.js?v=9.3.13"></script>
<script src="/static/js/geo/aot-map-config.js?v=9.2.6"></script>

<style>
  .aot-map-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
    z-index: 1; 
    overflow: hidden;
  }
  
  /* [Fix] Wobble Prevention during Zoom - Removed forced will-change as it can conflict with Leaflet's internal CSS */
  .leaflet-zoom-animated {
      /* will-change: transform; - Disabled for stability */
  }

  /* Device Status Styles */
  .device-on {
     /* Animation or specific style for active state */
     border-color: #ffffff !important; 
     z-index: 1000 !important;
     /* [Fix] Restrict transition to avoid interfering with Leaflet zoom transform */
     transition: background-color 0.4s ease, border 0.4s ease, box-shadow 0.4s ease;
  }
  .marker-pill.device-on {
      /* scale: 1.05; - Removed to prevent sub-pixel wobble during zoom */
      border-color: #ffffff !important;
      z-index: 1000 !important;
  }
  .geo-label-marker {
      background: none;
      border: none;
      margin: 0 !important; /* [Fix] Override Leaflet default marker margins */
      z-index: 500;
      /* [Fix] Enable hardware acceleration for labels */
      will-change: transform;
  }
  
  /* Custom Marker Cluster Styles (AoT Purple Theme) */
  .marker-cluster-small, .marker-cluster-medium, .marker-cluster-large {
    background-color: rgba(153, 90, 255, 0.2) !important;
  }
  .marker-cluster-small div, .marker-cluster-medium div, .marker-cluster-large div {
    background-color: rgba(153, 90, 255, 0.8) !important;
    border: 2px solid #fff;
    color: #fff !important;
    font-weight: bold;
    font-family: 'Inter', sans-serif;
    border-radius: 50%;
  }
  .marker-cluster span {
      line-height: 28px;
  }
  
  .marker-pill {
      display: inline-block;
      padding: 0.6em 1.2em !important; 
      border-radius: 2em;
      box-shadow: 0 2px 5px rgba(0,0,0,0.4);
      text-align: center;
      white-space: nowrap;
      font-weight: bold;
      transition: background-color 0.2s ease, border 0.2s ease, box-shadow 0.2s ease;
      box-sizing: border-box; 
      border-width: 2px !important;
      border-style: solid !important;
      
      /* [Fix] Restore translate for absolute centering. 
         Wobble will be handled by avoiding transitions on transform and ensuring integral positioning. */
      transform: translate(-50%, -50%) !important;
      position: relative;
  }
  
  .aot-label-inner {
      width: 100%;
      height: 100%;
      display: flex;
      justify-content: center;
      align-items: center;
  }
  /* Leaflet Panes & Controls Z-Index Management */
  .aot-map-container .leaflet-popup-pane {
      z-index: 10000 !important; 
  }
  .aot-map-container .leaflet-control-container {
      z-index: 1800 !important;
  }
  .aot-map-popup {
      z-index: 10000 !important;
  }
  .aot-timer-display {
      font-size: 1.1em;
      font-weight: normal;
      color: #333;
  }
  .aot-map-popup .aot-popup-title {
      font-size: 1.5em;
      font-weight: bold;
      margin-bottom: 0;
  }
  /* Leaflet Popup Border & Style Refinement */
  .aot-map-popup .leaflet-popup-content-wrapper {
      border: 2px solid #fff !important; 
      box-shadow: 0 3px 14px rgba(0,0,0,0.4) !important;
      border-radius: 8px !important;
  }
  .aot-map-popup .leaflet-popup-tip {
      background: #fff !important; 
      box-shadow: none !important;
  }
  .aot-map-popup .leaflet-popup-content {
      margin: 8px 10px !important;
      min-width: 160px;
  }

  /* [Fix] Map Attribution (Copyright) Stacking - Restore horizontal layout by overriding global img display:block */
  .leaflet-control-attribution img {
      display: inline !important;
      vertical-align: middle;
  }
</style>
"""

WIDGET_BODY_HTML = """


<div id="aot-map-{{each_widget.unique_id}}" class="aot-map-container" style="position: relative;">
    <div id="aot-map-{{each_widget.unique_id}}-canvas" style="width: 100%; height: 100%;"></div>

    <!-- Search Overlay -->
    <div id="search-overlay-{{ each_widget.unique_id }}" class="map-search-overlay d-none">
        <aot-map-search-fixed id="search-comp-{{ each_widget.unique_id }}" placeholder="{{ _('주소를 입력하세요.') }}"></aot-map-search-fixed>
    </div>
</div>
<script type="application/json" id="aot-map-vars-{{ each_widget.unique_id }}">
{{ {
    'widgetId': each_widget.unique_id,
    'mapId': 'aot-map-' ~ each_widget.unique_id,
    'contentMapUuid': widget_variables.selected_map_uuid or '',
    'refreshSeconds': widget_variables.period | default(5),
    'devices': widget_variables.devices,
    'vars': widget_variables,
    'theme': widget_variables.theme_config,
    'layers': widget_variables.active_layers,
    'geoConfig': widget_variables.geo_config,
    'isLocked': widget_variables.map_locked or False,
    'hideControls': widget_variables.hide_controls or False
} | tojson | safe }}
</script>
<script>
    ;(function() {
        // Initialize Map Widget
        if (typeof window.initAoTMapWidget === 'function') {
            window.initAoTMapWidget('{{each_widget.unique_id}}');
        } else {
            console.error("AoT Map Widget JS not loaded");
        }
    })();
</script>
"""

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_map',
    'widget_name': 'AoT 지도',
    'widget_library': 'Leaflet',
    'no_class': True,
    'head_html': WIDGET_HEAD_HTML,
    'body_html': WIDGET_BODY_HTML,
    'configure_html': None,
    'widget_dashboard_configure_options': None,

    'message': '선택한 장치의 위치를 지도에 표시합니다. 선택한 색상으로 작동 상태를 강조합니다.',

    'widget_width': 26,
    'widget_height': 15,
    'generate_page_variables': generate_page_variables,
    'execute_at_modification': execute_at_modification,

    # Custom options appear in the widget settings form
    'custom_options': [
        # --- Time ---
        {
            'type': 'header',
            'name': lazy_gettext('시간')
        },
        {
            'id': 'period',
            'type': 'integer',
            'default_value': '5',
            'name': lazy_gettext('주기(초)'),
            'phrase': lazy_gettext('N초마다 위젯을 새로고침합니다. 0이면 자동 갱신 없음.'),
            'constraints': {'min': 0, 'max': 86400}
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': '300',

            'name': lazy_gettext('최대 유효 시간(초)'),
            'phrase': lazy_gettext('이 시간보다 오래된 데이터는 표시하지 않습니다. (기본값: 300초)'),
            'constraints': {'min': 10, 'max': 86400}
        },
        {
            'id': 'input_update_interval',
            'type': 'integer',
            'default_value': '300',

            'name': lazy_gettext('입력 업데이트 주기(초)'),
            'phrase': lazy_gettext('측정값을 자동으로 갱신하는 주기입니다. (기본값: 300초)'),
            'constraints': {'min': 5, 'max': 86400}
        },

        # --- Map ---
        {
            'type': 'header',
            'name': lazy_gettext('지도')
        },
        {
            'id': 'map_uuid',
            'type': 'select_device',
            'options_select': ['Map'],
            'default_value': '',

            'name': lazy_gettext('지도 선택'),
            'phrase': lazy_gettext('지도를 선택하세요. 비워두면 최근 수정된 지도를 사용합니다.')
        },
        {
            'id': 'fallback_latitude',
            'type': 'text',
            'default_value': '',

            'name': lazy_gettext('위도'),
            'phrase': lazy_gettext('위도를 설정할 수 있습니다')
        },
        {
            'id': 'fallback_longitude',
            'type': 'text',
            'default_value': '',

            'name': lazy_gettext('경도'),
            'phrase': lazy_gettext('경도를 설정할 수 있습니다')
        },
        {
            'id': 'default_zoom',
            'type': 'text',
            'default_value': '15',

            'name': lazy_gettext('축척'),
            'phrase': lazy_gettext('지도의 확대/축소 값 (1~20)'),
        },
        {
            'id': 'active_layers',
            'type': 'text',
            'default_value': '',
            'name': lazy_gettext('활성 오버레이 레이어'),
            'phrase': lazy_gettext('현재 활성화된 오버레이 지도 목록 (쉼표로 구분)')
        },
        {
            'id': 'selected_base_layer',
            'type': 'text',
            'default_value': '',
            'name': lazy_gettext('선택된 베이스 레이어'),
            'phrase': lazy_gettext('현재 선택된 베이스 지도 이름')
        },

        # --- Device Selection ---
        {
            'type': 'header',
            'name': lazy_gettext('장치 선택')
        },
        {
            'id': 'device_selection_input',
            'type': 'select_multi_device',
            'options_select': ['Input'],
            'default_value': '',

            'name': lazy_gettext('입력'),
            'phrase': lazy_gettext('출력할 입력을 선택하세요.')
        },
        {
            'id': 'device_selection_output',
            'type': 'select_multi_device',
            'options_select': ['Output'],
            'default_value': '',

            'name': lazy_gettext('출력'),
            'phrase': lazy_gettext('출력할 출력을 선택하세요.')
        },
        {
            'id': 'device_selection_function',
            'type': 'select_multi_device',
            'options_select': ['Function'],
            'default_value': '',

            'name': lazy_gettext('함수'),
            'phrase': lazy_gettext('출력할 함수를 선택하세요.')
        },


        # --- Measurement Panel ---
        {
            'type': 'header',
            'name': lazy_gettext('측정값 패널')
        },
        {
            'id': 'measurements_input',
            'type': 'select_multi_measurement',
            'options_select': ['Input'],
            'default_value': '',

            'name': lazy_gettext('입력'),
            'phrase': lazy_gettext('패널에 표시할 입력 측정값을 선택하세요.')
        },
        {
            'id': 'measurements_output',
            'type': 'select_multi_measurement',
            'options_select': ['Output'],
            'default_value': '',

            'name': lazy_gettext('출력'),
            'phrase': lazy_gettext('패널에 표시할 출력 측정값을 선택하세요.')
        },
        {
            'id': 'measurements_function',
            'type': 'select_multi_measurement',
            'options_select': ['Function'],
            'default_value': '',

            'name': lazy_gettext('함수'),
            'phrase': lazy_gettext('패널에 표시할 함수 측정값을 선택하세요.')
        },

        # --- Labels ---
        {
            'type': 'header',
            'name': lazy_gettext('라벨')
        },
        {
            'id': 'show_site_label',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('대지 라벨'),
            'phrase': lazy_gettext('지도에 대지(Site) 이름을 표시합니다.')
        },
        {
            'id': 'show_zone_label',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('구역 라벨'),
            'phrase': lazy_gettext('지도에 구역(Zone) 이름을 표시합니다.')
        },
        {
            'id': 'show_device_labels',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('장치 라벨'),
            'phrase': lazy_gettext('지도에 장치 이름을 표시합니다.')
        },
        {
            'id': 'enable_label_collision',
            'type': 'bool',
            'default_value': True,

            'name': lazy_gettext('라벨 충돌 방지'),
            'phrase': lazy_gettext('활성화 시 겹치는 라벨을 자동으로 숨깁니다.')
        },
        {
            'id': 'label_spacing',
            'type': 'integer',
            'default_value': '10',

            'name': lazy_gettext('라벨 간격 (px)'),
            'phrase': lazy_gettext('라벨 간의 최소 간격을 설정합니다.'),
            'constraints': {'min': 0, 'max': 100}
        },
        {
            'id': 'site_label_size',
            'type': 'float',
            'default_value': '1.2',

            'name': lazy_gettext('대지 라벨 크기'),
            'phrase': lazy_gettext('대지 라벨의 크기를 지정합니다. (단위: em)'),
        },
        {
            'id': 'zone_label_size',
            'type': 'float',
            'default_value': '1.0',

            'name': lazy_gettext('구역 라벨 크기'),
            'phrase': lazy_gettext('구역 라벨의 크기를 지정합니다. (단위: em)'),
        },

        # --- Shapes ---
        {
            'type': 'header',
            'name': lazy_gettext('도형')
        },
        {
            'id': 'show_site_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('대지 도형'),
            'phrase': lazy_gettext('지도에 대지(Site) 폴리곤을 표시합니다.')
        },
        {
            'id': 'show_zone_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('구역 도형'),
            'phrase': lazy_gettext('지도에 구역(Zone) 폴리곤을 표시합니다.')
        },
        {
            'id': 'show_facility_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('시설 도형'),
            'phrase': lazy_gettext('시설(Facility) 폴리곤을 표시합니다.')
        },
        {
            'id': 'show_equipment_shape',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('설비 도형'),
            'phrase': lazy_gettext('설비(Equipment - 파이프 등) 도형을 표시합니다.')
        },
        {
            'id': 'show_device_shapes',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('장치 도형'),
            'phrase': lazy_gettext('장치(Device)에 설정된 도형 영역을 표시합니다.')
        },
        {
            'id': 'show_drawn_shapes',
            'type': 'bool',
            'default_value': False,

            'name': lazy_gettext('기타 그리기 도형'),
            'phrase': lazy_gettext('그리기 도구로 생성한 자율 형태의 도형을 표시합니다.')
        },

        # --- Shapes Style ---
        {
            'type': 'header',
            'name': lazy_gettext('도형 스타일')
        },
        {
            'id': 'device_shape_opacity',
            'type': 'integer',
            'default_value': '50',
            'name': lazy_gettext('장치 도형 투명도'),
            'phrase': lazy_gettext('0 (투명) ~ 100 (불투명)'),
            'constraints': {'min': 0, 'max': 100}
        },
        
        # --- Misc ---
        {
            'id': 'overlay_data_only',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('데이터값만 표시 (지도 숨김)'),
            'phrase': lazy_gettext('오버레이 지도를 숨기고 데이터 패널만 표시합니다.')
        }

    ],

    'widget_dashboard_head': WIDGET_HEAD_HTML,
    
    'widget_dashboard_title_bar': """
    {%- if widget_options['enable_status'] -%}
      <span id="tm_state_{{each_widget.unique_id}}"></span>
    {%- else -%}
      <span style="display:none" id="tm_state_{{each_widget.unique_id}}"></span>
    {%- endif %}

    <span style="padding-right: 0.5em"> {{each_widget.name}}</span>
    """,

    'widget_dashboard_body': WIDGET_BODY_HTML,

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
  ;(function() {
      // 1. Inject Unit Configuration from Dashboard Context
      // This maps Measurement Unique ID -> Unit String (Symbol)
      var aotMapUnits = {};
      
      {% if dict_measure_units is defined %}
          {% for m_id, u_id in dict_measure_units.items() %}
              {% if dict_units is defined and u_id in dict_units %}
                  aotMapUnits['{{ m_id }}'] = '{{ dict_units[u_id].unit }}';
              {% else %}
                  aotMapUnits['{{ m_id }}'] = '{{ u_id }}';
              {% endif %}
          {% endfor %}
      {% endif %}

      // Expose to Global Scope for Map JS to use
      window.aotMapUnits = aotMapUnits;

  })();
"""
}
