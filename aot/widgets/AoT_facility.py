# coding=utf-8
#
#  AoT_facility.py - Dashboard widget for facility operation view
#
#  Renders 3D model + environment summary + setpoints + actuator control + AI advice
#  Pattern follows AoT_map.py (Mycodo widget framework)
#
import logging
import json
from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Widget Definition
# ------------------------------------------------------------------------------

def execute_at_modification(mod_widget, request_form, custom_options_presave, custom_options_postsave):
    """Merge framework-parsed options with values from the custom configure template."""
    options = {}
    try:
        if mod_widget.custom_options:
            options = (json.loads(mod_widget.custom_options)
                       if isinstance(mod_widget.custom_options, str)
                       else dict(mod_widget.custom_options))
    except Exception:
        pass

    final = options.copy()
    if custom_options_postsave:
        for k, v in custom_options_postsave.items():
            final[k] = v
    return True, True, mod_widget, final


def widget_variables(widget_unique_id, widget_options):
    """Resolve template variables: facility data, setpoints, permissions."""
    from aot.databases.models import GeoFacility
    from aot.databases.models.geo_facility_setpoint import GeoFacilitySetpoint
    from aot.databases.models.controller import CustomController
    import flask_login
    from aot.aot_flask.utils.utils_general import user_has_permission

    options = widget_options or {}
    function_uuid = options.get('function_uuid', '') if options else ''

    # ── Resolve linked env_coordinator function ──────────────────────────────
    all_functions = CustomController.query.filter_by(device='env_coordinator').order_by(
        CustomController.name).all()
    function_list = [{'unique_id': f.unique_id, 'name': f.name,
                      'is_activated': f.is_activated} for f in all_functions]

    linked_function = None
    if function_uuid:
        linked_function = CustomController.query.filter_by(
            unique_id=function_uuid, device='env_coordinator').first()
    if not linked_function and all_functions:
        linked_function = next((f for f in all_functions if f.is_activated), all_functions[0])

    function_data = None
    if linked_function:
        function_data = {
            'unique_id':    linked_function.unique_id,
            'name':         linked_function.name,
            'is_activated': linked_function.is_activated,
        }

    # ── Derive facility from function's geo_facility_id ──────────────────────
    facility = None
    if linked_function:
        try:
            fn_opts = (json.loads(linked_function.custom_options)
                       if linked_function.custom_options else {})
            fn_facility_uuid = fn_opts.get('geo_facility_id', '')
            if fn_facility_uuid:
                facility = GeoFacility.query.filter_by(unique_id=fn_facility_uuid).first()
        except Exception:
            pass
    if not facility:
        facility = GeoFacility.query.order_by(GeoFacility.updated_at.desc()).first()

    facility_data = None
    if facility:
        facility_data = {
            'unique_id': facility.unique_id,
            'name': facility.name,
            'preset': facility.preset,
            'structure': facility.structure,
            'bay_count': facility.bay_count or 1,
            'geometry_3d': facility.geometry_3d,
            'envelope': facility.envelope,
            'actuators': facility.actuators,
            'bays': facility.bays,
            'computed': facility.computed,
            'fittings': facility.fittings,
        }

    all_facilities = GeoFacility.query.order_by(GeoFacility.updated_at.desc()).all()
    facility_list = [{'unique_id': f.unique_id, 'name': f.name} for f in all_facilities]

    # Setpoints — wrapped in try/except so missing table (pre-migration) doesn't crash the widget
    setpoints_data = None
    try:
        if facility:
            sp = GeoFacilitySetpoint.query.filter_by(facility_uuid=facility.unique_id).first()
            if sp:
                setpoints_data = {
                    'target_vpd_kpa':   sp.target_vpd_kpa,
                    'guide_t_min_c':    sp.guide_t_min_c,
                    'guide_t_max_c':    sp.guide_t_max_c,
                    'guide_rh_min_pct': sp.guide_rh_min_pct,
                    'guide_rh_max_pct': sp.guide_rh_max_pct,
                    'temp_min_c':       sp.temp_min_c,
                    'temp_max_c':       sp.temp_max_c,
                    'humid_min_pct':    sp.humid_min_pct,
                    'humid_max_pct':    sp.humid_max_pct,
                    'target_co2_ppm':   sp.target_co2_ppm,
                    'source':           sp.source,
                }
    except Exception:
        pass

    # Sensor label color ranges — stored in facility.view_options.sensor_ranges.
    # The design panel (SensorRangesUI) sets the 5-step upper bounds per measurement item.
    sensor_ranges = None
    if facility:
        try:
            vo = facility.view_options or {}
            sensor_ranges = vo.get('sensor_ranges') or None
        except Exception:
            sensor_ranges = None

    # Control permission: reuse edit_settings (admin-level)
    can_control = user_has_permission('edit_settings', silent=True)

    return {
        'facility':       facility_data,
        'facilities':     facility_list,
        'function':       function_data,
        'functions':      function_list,
        'period':         options.get('period', 60),
        'show_ai_advice': options.get('show_ai_advice', False),
        'display_mode':   'control',
        'show_status':    options.get('show_status', True),
        'show_setpoints': options.get('show_setpoints', True),
        'show_controls':  options.get('show_controls', True),
        'estop_enabled':  options.get('estop_enabled', False),
        'can_control':    can_control,
        'setpoints':      setpoints_data,
        'render_mode_3d':    options.get('render_mode_3d', 'default'),
        'sensor_label_opts': {
            'show':         bool(options.get('show_sensor_labels', True)),
            'max_channels': int(options.get('sensor_label_max_channels', 1) or 1),
            'decimals':     int(options.get('sensor_label_decimals', 1) or 0),
            'size_em':      float(options.get('sensor_label_size', 0.85) or 0.85),
            'bg':           options.get('sensor_label_bg', 'rgba(15,23,42,0.78)'),
            'fg':           options.get('sensor_label_fg', '#f8fafc'),
            'offset_y':     float(options.get('sensor_label_offset_y', 0.25) or 0.0),
            'opacity':      float(options.get('sensor_label_opacity', 0.7) or 0.7),
            'popup':        bool(options.get('sensor_popup_enabled', True)),
            'ranges':       sensor_ranges,
        },
    }


WIDGET_HEAD_HTML = """\
<link rel="stylesheet" href="/static/css/widget/aot-facility-widget.css?v=25">
<script>
if (!window._aotThreeLoaded) {
  window._aotThreeLoaded = true;
  document.write('<script src="/static/js/widgets/AoT_facility/three.min.js?v=2"><\\/script>');
}
</script>
<script src="/static/js/widgets/AoT_facility/OrbitControls.js?v=1"></script>
<script src="/static/js/widgets/AoT_facility/three-mesh-bvh.js?v=1"></script>
<script src="/static/js/widgets/AoT_facility/GLTFLoader.js?v=1"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" crossorigin="anonymous"></script>
<script>
if (!window._aotFacility3DLoaded) {
  window._aotFacility3DLoaded = true;
  document.write('<script src="/static/js/widgets/AoT_facility/aot-facility-3d.js?v=32"><\\/script>');
}
</script>
<!-- 위젯 비가드 스크립트 9개 → 단일 번들(concat+minify, static/js/tools/bundle.mjs: aot-facility-widget).
     three.min/aot-facility-3d 가드 로드는 위에 그대로 유지(AoT_map 위젯과 공유 가드). 소스 수정 시 npm run build:bundles 후 위젯 재생성. -->
<script src="{{ asset('aot-facility-widget') }}"></script>
<link rel="stylesheet" href="/static/css/widget/aot-sensor-label.css?v=47">
<link rel="stylesheet" href="/static/css/components/aot-toggle.css">
"""

WIDGET_BODY_HTML = """\
{% set display_mode   = widget_variables.display_mode   or 'viewer' %}
{% set show_status    = widget_variables.show_status    if widget_variables.show_status    is not none else true %}
{% set show_setpoints = widget_variables.show_setpoints if widget_variables.show_setpoints is not none else true %}
{% set show_controls  = widget_variables.show_controls  if widget_variables.show_controls  is not none else true %}
{% set estop_enabled  = widget_variables.estop_enabled  if widget_variables.estop_enabled  is not none else false %}
{% set can_control    = widget_variables.can_control    if widget_variables.can_control    is not none else false %}
{% set is_control     = display_mode == 'control' %}
{% set sp             = widget_variables.setpoints %}

<div id="aot-facility-{{each_widget.unique_id}}" class="aot-facility-container"
     data-ai-facility-id="{{ widget_variables.facility.unique_id if widget_variables.facility else '' }}">

  {% if widget_variables.facility %}

  {# § 0. Status Strip #}
  {% if is_control and show_status %}
  <div class="iec-status-strip" id="iec-status-strip-{{each_widget.unique_id}}">
    <span class="iec-badge idle" id="iec-badge-{{each_widget.unique_id}}">IDLE</span>
    <span class="iec-status-reasons" id="iec-reasons-{{each_widget.unique_id}}"></span>
    <span class="iec-status-ts" id="iec-ts-{{each_widget.unique_id}}"></span>
  </div>
  {% endif %}

  {# § A. 3D View #}
  <div class="aot-fac-section">
    <h6 class="aot-fac-3d-hdr">{{ _('Facility 3D View') }}
      <span class="preset-badge">{{ widget_variables.facility.preset }}</span>
      {% if widget_variables.facility.structure == 'connected' %}
        <span class="preset-badge">{{ _('connected') }} x{{ widget_variables.facility.bay_count }}</span>
      {% endif %}
      {% if widget_variables.facility.envelope and widget_variables.facility.envelope.layer_count == 2 %}
        <span class="preset-badge">{{ _('double layer') }}</span>
      {% endif %}
      <small class="aot-fac-ts" id="aot-facility-status-{{each_widget.unique_id}}">—</small>
    </h6>
    <div class="aot-facility-3d-wrap" id="aot-facility-3d-wrap-{{each_widget.unique_id}}">
      <canvas id="aot-facility-canvas-{{each_widget.unique_id}}"></canvas>
      <div class="aot-sensor-labels-overlay" id="aot-sensor-labels-{{each_widget.unique_id}}"></div>
      <div class="aot-facility-3d-hint">{{ _('Right-click: rotate') }} · {{ _('Left-click: pan') }} · {{ _('Scroll: zoom') }}</div>
    </div>
    <div class="aot-fac-3d-rh" id="aot-fac-3d-rh-{{each_widget.unique_id}}" title="{{ _('Drag to resize') }}"></div>
  </div>

  {# § B. Environment — clicking a cell opens the setpoint popup in control mode #}
  <div class="aot-fac-section">
    <h6>{{ _('Environment') }}</h6>
    <div class="aot-facility-env" id="aot-facility-env-{{each_widget.unique_id}}">

      <div class="env-cell{% if is_control and show_setpoints and can_control %} env-clickable{% endif %}"
           data-key="indoor_vpd"
           {% if is_control and show_setpoints and can_control %}data-sp-key="vpd" data-wid="{{each_widget.unique_id}}" data-facility="{{widget_variables.facility.unique_id}}"{% endif %}>
        <div class="env-label">{{ _('VPD') }}</div>
        <div class="env-value">— kPa</div>
        {% if is_control %}<span class="env-setpoint" id="iec-sp-lbl-vpd-{{each_widget.unique_id}}"></span>{% endif %}
        {% if is_control and show_setpoints and can_control %}<span class="env-sp-hint">{{ _('set') }}</span>{% endif %}
      </div>

      <div class="env-cell{% if is_control and show_setpoints and can_control %} env-clickable{% endif %}"
           data-key="indoor_temp"
           {% if is_control and show_setpoints and can_control %}data-sp-key="temp" data-wid="{{each_widget.unique_id}}" data-facility="{{widget_variables.facility.unique_id}}"{% endif %}>
        <div class="env-label">{{ _('Indoor temp') }}</div>
        <div class="env-value">— °C</div>
        {% if is_control %}<span class="env-setpoint" id="iec-sp-lbl-tguide-{{each_widget.unique_id}}"></span>{% endif %}
        {% if is_control and show_setpoints and can_control %}<span class="env-sp-hint">{{ _('set') }}</span>{% endif %}
      </div>

      <div class="env-cell{% if is_control and show_setpoints and can_control %} env-clickable{% endif %}"
           data-key="indoor_humidity"
           {% if is_control and show_setpoints and can_control %}data-sp-key="rh" data-wid="{{each_widget.unique_id}}" data-facility="{{widget_variables.facility.unique_id}}"{% endif %}>
        <div class="env-label">{{ _('Indoor humidity') }}</div>
        <div class="env-value">— %</div>
        {% if is_control %}<span class="env-setpoint" id="iec-sp-lbl-rhguide-{{each_widget.unique_id}}"></span>{% endif %}
        {% if is_control and show_setpoints and can_control %}<span class="env-sp-hint">{{ _('set') }}</span>{% endif %}
      </div>

      <div class="env-cell{% if is_control and show_setpoints and can_control %} env-clickable{% endif %}"
           data-key="indoor_co2"
           {% if is_control and show_setpoints and can_control %}data-sp-key="co2" data-wid="{{each_widget.unique_id}}" data-facility="{{widget_variables.facility.unique_id}}"{% endif %}>
        <div class="env-label">CO&#8322;</div>
        <div class="env-value">— ppm</div>
        {% if is_control %}<span class="env-setpoint" id="iec-sp-lbl-co2-{{each_widget.unique_id}}"></span>{% endif %}
        {% if is_control and show_setpoints and can_control %}<span class="env-sp-hint">{{ _('set') }}</span>{% endif %}
      </div>

      <div class="env-cell" data-key="outdoor_temp">
        <div class="env-label">{{ _('Outdoor temp') }}</div>
        <div class="env-value">— °C</div>
      </div>
      <div class="env-cell" data-key="wind">
        <div class="env-label">{{ _('Wind') }}</div>
        <div class="env-value">— m/s</div>
      </div>
      <div class="env-cell" data-key="solar">
        <div class="env-label">{{ _('Solar') }}</div>
        <div class="env-value">— W/m2</div>
      </div>
    </div>
  </div>

  {# § D. Actuator Group Panel #}
  {% if show_controls %}
  <div class="aot-fac-section" id="aot-act-panel-section-{{each_widget.unique_id}}">
    <h6>{{ _('Actuator Control') }}</h6>
    <div class="aot-act-panel" id="aot-act-panel-{{each_widget.unique_id}}">
      <div class="aot-act-empty">{{ _('Loading...') }}</div>
    </div>
  </div>
  {% endif %}

  {# § E. AI Advice #}
  {% if widget_variables.show_ai_advice %}
  <div class="aot-fac-section">
    <h6>{{ _('AI Advice') }}</h6>
    <div id="aot-facility-advice-{{each_widget.unique_id}}">
      <div style="font-size:var(--aot-fs-caption);color:var(--aot-color-text-secondary)">{{ _('Loading...') }}</div>
    </div>
  </div>
  {% endif %}

  {% else %}
  <div class="alert alert-warning">
    {{ _('No facility selected. Register one at') }} <a href="/geo/facility">/geo/facility</a>.
  </div>
  {% endif %}

  {# Setpoint popup — shared singleton, hidden by default #}
  {% if is_control and show_setpoints and can_control %}
  <div id="iec-sp-popup-{{each_widget.unique_id}}" class="iec-sp-popup" style="display:none">
    <div class="iec-sp-popup-title" id="iec-sp-popup-title-{{each_widget.unique_id}}"></div>
    <div id="iec-sp-popup-rows-{{each_widget.unique_id}}"></div>
    <div class="iec-sp-popup-footer">
      <span class="iec-sp-popup-msg" id="iec-sp-popup-msg-{{each_widget.unique_id}}"></span>
      <span class="iec-sp-popup-close" id="iec-sp-popup-close-{{each_widget.unique_id}}">{{ _('Close') }}</span>
    </div>
  </div>
  {% endif %}

</div>

<script type="application/json" id="aot-facility-vars-{{each_widget.unique_id}}">
{{ {
    'widgetId':      each_widget.unique_id,
    'facility':      widget_variables.facility,
    'period':        widget_variables.period or 60,
    'showAiAdvice':  widget_variables.show_ai_advice or false,
    'displayMode':   display_mode,
    'showStatus':    show_status,
    'showSetpoints': show_setpoints,
    'showControls':  show_controls,
    'estopEnabled':  estop_enabled,
    'canControl':    can_control,
    'setpoints':     widget_variables.setpoints,
    'functionUuid':  widget_variables.function.unique_id if widget_variables.function else '',
    'functionName':  widget_variables.function.name if widget_variables.function else '',
    'sensorLabelOpts': widget_variables.sensor_label_opts,
    'renderMode3d':    widget_variables.render_mode_3d or 'default'
} | tojson | safe }}
</script>

<script>
;(function(){
  if(typeof window.initAoTFacilityWidget==='function'){
    window.initAoTFacilityWidget('{{each_widget.unique_id}}');
  }else{
    document.addEventListener('DOMContentLoaded',function(){
      if(typeof window.initAoTFacilityWidget==='function')
        window.initAoTFacilityWidget('{{each_widget.unique_id}}');
    });
  }
})();
</script>
"""

WIDGET_INFORMATION = {
    'widget_name_unique': 'AoT_facility',
    'widget_name': lazy_gettext('AoT Facility'),
    # On mobile (<=768px), place only one per row (full width). When False/unset, allow two per row.
    'mobile_full_width': True,
    'widget_library': 'Three.js 3D + IEC control',
    'no_class': True,
    'head_html': WIDGET_HEAD_HTML,
    'body_html': WIDGET_BODY_HTML,
    'configure_html': None,
    'widget_dashboard_configure_options': None,

    'message': lazy_gettext(
        'Facility 3D view, environment summary, setpoint editor, '
        'actuator control grid, and AI advice.'
    ),

    'widget_width': 20,
    'widget_height': 20,
    'generate_page_variables': widget_variables,
    'execute_at_modification': execute_at_modification,

    'custom_options': [
        {
            'type': 'header',
            'name': lazy_gettext('General')
        },
        {
            'id': 'period',
            'type': 'integer',
            'default_value': 60,
            'name': lazy_gettext('Period (seconds)'),
            'phrase': lazy_gettext('Refresh interval for runtime data. 0 to disable.'),
            'constraints': {'min': 0, 'max': 3600}
        },
        {
            'id': 'function_uuid',
            'type': 'select_device',
            'default_value': '',
            'options_select': ['Function'],
            'filter': {'key': 'device', 'value': 'env_coordinator'},
            'name': lazy_gettext('IEC Function'),
            'phrase': lazy_gettext(
                'Select the Integrated Environment Control function. '
                'The linked facility is auto-discovered from the function configuration. '
                'Leave blank to auto-select the first activated env_coordinator.'
            )
        },
        {
            'id': 'show_ai_advice',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show AI Advice (§ E) — EXPERIMENTAL'),
            'phrase': lazy_gettext(
                'Display AI recommendation cards. WARNING: currently shows MOCK '
                'demo cards with hardcoded text. The Approve button still '
                'dispatches real actuator commands via /api/geo/facility/<uuid>/apply, '
                'so do NOT enable in production until a real advisor backend is wired up.'
            )
        },
        {
            'type': 'header',
            'name': lazy_gettext('Integrated Environment Control (IEC)')
        },
        {
            'id': 'show_status',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Status Strip (§ 0)'),
            'phrase': lazy_gettext('Show emergency/warn/active/idle badge. Control mode only.')
        },
        {
            'id': 'show_setpoints',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Setpoints (§ C)'),
            'phrase': lazy_gettext('Show target temp/RH/CO2 editor. Control mode only.')
        },
        {
            'id': 'show_controls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Actuator Grid (§ D)'),
            'phrase': lazy_gettext('Show actuator sliders and toggles. Control mode only.')
        },
        {
            'id': 'estop_enabled',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Show Emergency Stop'),
            'phrase': lazy_gettext('Show ALL STOP button in actuator grid. Requires explicit activation.')
        },

        # --- 3D Rendering ---
        {
            'type': 'header',
            'name': lazy_gettext('3D Rendering')
        },
        {
            'id': 'render_mode_3d',
            'type': 'select',
            'default_value': 'default',
            'options_select': [
                ('default',     lazy_gettext('Default (transparent)')),
                ('solid',       lazy_gettext('Solid (opaque)')),
                ('wireframe',   lazy_gettext('Wireframe')),
                ('performance', lazy_gettext('Performance (mobile)')),
            ],
            'name': lazy_gettext('Render Mode'),
            'phrase': lazy_gettext(
                'Default: semi-transparent cover. '
                'Solid: opaque, lower overdraw. '
                'Wireframe: outlines only. '
                'Performance: simplified shading + reduced resolution for mobile.'
            )
        },

        # --- Sensor Labels (sensor measurement labels over the 3D scene) ---
        {
            'type': 'header',
            'name': lazy_gettext('Sensor Labels')
        },
        {
            'id': 'show_sensor_labels',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Show Sensor Labels'),
            'phrase': lazy_gettext('Display realtime measurement values next to each sensor in the 3D scene.')
        },
        {
            'id': 'sensor_label_max_channels',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Max Channels Shown'),
            'phrase': lazy_gettext('Number of measurement values shown per label. Extra channels collapse to "+".'),
            'constraints': {'min': 1, 'max': 5}
        },
        {
            'id': 'sensor_label_decimals',
            'type': 'integer',
            'default_value': 1,
            'name': lazy_gettext('Decimals'),
            'phrase': lazy_gettext('Decimal places for label values.'),
            'constraints': {'min': 0, 'max': 3}
        },
        {
            'id': 'sensor_label_size',
            'type': 'float',
            'default_value': 0.85,
            'name': lazy_gettext('Label Size (em)'),
            'phrase': lazy_gettext('Font size of sensor labels in em units.'),
            'constraints': {'min': 0.5, 'max': 2.0}
        },
        {
            'id': 'sensor_label_bg',
            'type': 'text',
            'default_value': 'rgba(15,23,42,0.78)',
            'name': lazy_gettext('Label Background'),
            'phrase': lazy_gettext('CSS color for label background.')
        },
        {
            'id': 'sensor_label_fg',
            'type': 'text',
            'default_value': '#f8fafc',
            'name': lazy_gettext('Label Text Color'),
            'phrase': lazy_gettext('CSS color for label text.')
        },
        {
            'id': 'sensor_label_offset_y',
            'type': 'float',
            'default_value': 0.25,
            'name': lazy_gettext('Vertical Offset (m)'),
            'phrase': lazy_gettext('Distance above the sensor (in meters) where the label is anchored.'),
            'constraints': {'min': 0.0, 'max': 2.0}
        },
        {
            'id': 'sensor_label_opacity',
            'type': 'float',
            'default_value': 0.7,
            'name': lazy_gettext('Label Opacity'),
            'phrase': lazy_gettext('Opacity of sensor value labels (0.0–1.0).'),
            'constraints': {'min': 0.0, 'max': 1.0}
        },
        {
            'id': 'sensor_popup_enabled',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Enable Sensor Popup'),
            'phrase': lazy_gettext('Click a sensor label to open a detail popup with the last 24h chart.')
        },
    ],

    'widget_dashboard_head': WIDGET_HEAD_HTML,
    'widget_dashboard_title_bar': """
    <span class="aot-w-title" style="padding-right:0.5em">{{each_widget.name}}</span>
    """,
    'widget_dashboard_body': WIDGET_BODY_HTML,
    'widget_dashboard_js_ready': '',
    'widget_dashboard_js_ready_end': '',
}
