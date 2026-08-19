# coding=utf-8
"""
_function_info.py — FUNCTION_INFORMATION 및 액추에이터 종류 상수.

env_coordinator.py 에서 `from ._function_info import *` 로 임포트.
"""

from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value

# ─────────────────────────────────────────────────────────────────────────────
# 액추에이터 종류 상수 (env_coordinator.py 전역 참조)
# ─────────────────────────────────────────────────────────────────────────────

_KIND_CAPABILITIES = {
    'opening':          ['ventilation', 'cooling_passive', 'co2_dilution'],
    'cooler':           ['cooling'],
    'heater':           ['heating'],
    'fogger':           ['humidify', 'cooling_passive'],
    'co2_injector':     ['co2_enrich'],
    'shade':            ['shading', 'cooling_passive'],
    'curtain':          ['insulation'],
    'lighting':         ['light_enrich'],
    'circulation_fan':  ['ventilation'],                            # P3-1
    'exhaust_fan':      ['ventilation', 'cooling_passive', 'co2_dilution'],  # P3-1
    'intake_fan':       ['ventilation', 'cooling_passive'],          # P3-1
}

# GeoFacility.actuators 슬롯 → ActuatorProfile.kind 매핑.
_FACILITY_SLOT_KIND = {
    'outer_side_vent_motor': 'opening',
    'outer_roof_vent_motor': 'opening',
    'inner_side_vent_motor': 'opening',
    'inner_roof_vent_motor': 'opening',
    'thermal_curtain':       'curtain',
    'shade_curtain':         'shade',
    'circulation_fan':       'circulation_fan',   # P3-1
    'exhaust_fan':           'exhaust_fan',        # P3-1
    'intake_fan':            'intake_fan',         # P3-1
}

# GeoFacility.actuators 리스트형(ActuatorUI 인스턴스) kind → ActuatorProfile.kind 매핑.
# facility 디자이너(aot-facility-design.js)의 ActuatorUI 는 actuators 를
# [{kind, device_uuid, specs, mount}, ...] 리스트로 저장한다. 그 kind 는
# 모터/장비 단위(side_window_motor, exhaust_fan ...)라 env_control 의
# ActuatorProfile.kind(opening, exhaust_fan ...)로 한 번 더 정규화해야 한다.
# None 매핑(irrigation_valve)은 별도 관수 파이프라인이 처리하므로 env 등록에서 제외.
_ACTUATOR_UI_KIND_TO_KIND = {
    'side_window_motor':     'opening',
    'roof_vent_motor':       'opening',
    'thermal_curtain_motor': 'curtain',
    'shade_curtain_motor':   'shade',
    'exhaust_fan':           'exhaust_fan',
    'circulation_fan':       'circulation_fan',
    'intake_fan':            'intake_fan',
    'heater':                'heater',
    'cooler':                'cooler',
    'heat_pump':             'cooler',
    'irrigation_valve':      None,
}

# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION_INFORMATION
# ─────────────────────────────────────────────────────────────────────────────

FUNCTION_INFORMATION = {
    'function_name_unique': 'env_coordinator',
    'function_name': lazy_gettext('Integrated Environment Control'),
    'function_name_short': 'Env Coordinator',

    'message': lazy_gettext(
        'Coordinates registered Output actuators to optimise photosynthesis. '
        'VPD is the primary control target; temperature and humidity act as '
        'safety constraints. Add "Environment Control: Register Actuator" actions '
        'to register devices. External environment data (outdoor temperature, '
        'humidity, wind, rain, solar, CO₂) comes from the linked facility\'s '
        'outdoor sensors, or optionally from the ext_context_collector function.'
    ),

    'options_enabled': ['custom_options', 'enable_actions'],
    'options_disabled': ['measurements_select', 'measurements_configure'],

    'custom_commands_message': lazy_gettext(
        'Trigger an immediate cycle, reload actuators, or issue an emergency stop.'
    ),
    'custom_commands': [
        {
            'id': 'cmd_reload',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Reload Actuators'),
            'phrase': lazy_gettext(
                'Re-read the Actions table and rebuild actuator profiles.'
            ),
        },
        {
            'id': 'cmd_run_now',
            'type': 'button',
            'wait_for_return': False,
            'name': lazy_gettext('Run Now'),
            'phrase': lazy_gettext(
                'Execute one coordination cycle immediately using current sensor readings.'
            ),
        },
        {
            'id': 'cmd_emergency_stop',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Emergency Stop'),
            'phrase': lazy_gettext(
                'Immediately set all actuators to safe_default and pause control for 60 s.'
            ),
        },
    ],

    'custom_options': [

        # ── Basic ─────────────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Basic'),
        },
        {
            'id': 'update_period',
            'type': 'float',
            'default_value': 60.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Period (seconds)'),
            'phrase': lazy_gettext(
                'Coordination cycle interval. Recommended: slowest actuator response time × 1.5.'
            ),
        },
        {
            'id': 'sensor_max_age',
            'type': 'float',
            'default_value': 120.0,
            'required': False,
            'name': lazy_gettext('Max Sensor Age (seconds)'),
            'phrase': lazy_gettext(
                'Reject sensor readings older than this value. 0 = no limit.'
            ),
        },

        # ── Actuation Rate (opening vents only) ──────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Actuation Rate'),
        },
        {
            'id': 'actuation_profile',
            'type': 'select',
            'default_value': 'standard',
            'required': False,
            'options_select': [
                ('responsive', lazy_gettext('Responsive (60s)')),
                ('standard',   lazy_gettext('Standard (180s)')),
                ('gentle',     lazy_gettext('Gentle — extend vent motor life (600s)')),
                ('custom',     lazy_gettext('Custom (set seconds below)')),
            ],
            'name': lazy_gettext('Vent Actuation Profile'),
            'phrase': lazy_gettext(
                'How often side/roof vents are allowed to move under normal '
                'conditions. Does not affect sensing/computation (still runs '
                'every Period above) or emergency response — sudden weather '
                'changes and safety gates (wind/rain/heat/cold) always move '
                'vents immediately regardless of this setting. Curtains/shades '
                'are unaffected (they open/close in one fully-open-or-closed step).'
            ),
        },
        {
            'id': 'actuation_period_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Custom Actuation Period (seconds)'),
            'phrase': lazy_gettext(
                'Used only when Vent Actuation Profile = Custom. 0 = fall back '
                'to the selected profile default.'
            ),
        },
        {
            'id': 'emergency_period_sec',
            'type': 'float',
            'default_value': 60.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Emergency Minimum Interval (seconds)'),
            'phrase': lazy_gettext(
                'Even during an emergency, vents will not be re-commanded more '
                'often than this — prevents rapid back-to-back moves.'
            ),
        },
        {
            'id': 'emergency_deviation_mult',
            'type': 'float',
            'default_value': 3.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Emergency Deviation Threshold (× tolerance)'),
            'phrase': lazy_gettext(
                'If a variable deviates from its target by more than this many '
                'times its tolerance, treat the cycle as an emergency and move '
                'vents immediately (ignore the actuation period above).'
            ),
        },
        {
            'id': 'emergency_rate_c_per_10min',
            'type': 'float',
            'default_value': 2.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Emergency Rate Threshold (°C / 10min)'),
            'phrase': lazy_gettext(
                'If indoor temperature is changing faster than this rate, '
                'treat the cycle as an emergency and move vents immediately.'
            ),
        },
        {
            'id': 'vent_futility_gate',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Close Vents When Ventilation Cannot Help'),
            'phrase': lazy_gettext(
                'Ventilation can only pull the inside toward the outside. When '
                'the target lies on the far side of the outdoor air, opening '
                'moves away from it no matter how wide — the classic case is '
                'dehumidifying at night, when outdoor air is wetter than indoor '
                'and every opening makes it worse. With this on, vents and '
                'exhaust/intake fans park closed in that situation instead of '
                'holding a partial opening all night. Safety gates (wind, rain, '
                'heat, cold) still override this and move vents as needed. Turn '
                'it off if you want vents to keep tracking the target even when '
                'the outdoor air cannot deliver it.'
            ),
        },

        # ── Heating / Cooling Interlock ───────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Heating / Cooling Interlock'),
        },
        {
            'id': 'hvac_interlock',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Keep Vents Closed While Heating or Cooling Runs'),
            'phrase': lazy_gettext(
                'Venting against a running heater or cooler throws the energy '
                'straight back outside. With this on, vents and exhaust/intake '
                'fans park closed whenever heating or cooling is detected as '
                'running. Detection needs evidence: either this coordinator '
                'commands the heater/cooler itself, or you point the signal '
                'field below at a measurement that rises when the unit runs. '
                'Indoor temperature is NOT used to guess — a ventilated or '
                'shaded greenhouse is often cooler than the outdoor weather '
                'station even with nothing running, so guessing would lock the '
                'vents shut on a hot afternoon. Your temperature and humidity '
                'limits and the safety gates still override this and open the '
                'vents when they must.'
            ),
        },
        {
            'id': 'hvac_interlock_signal',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': [
                'Input',
                'Function',
            ],
            'name': lazy_gettext('Heating / Cooling Running Signal'),
            'phrase': lazy_gettext(
                'For a unit switched on by hand, which this system does not '
                'control. Pick any measurement that goes up when the unit runs '
                '— a smart plug reporting watts, a clamp meter reporting amps, '
                'or an auxiliary contact reported as on/off. Leave empty if '
                'this coordinator commands the unit directly. With neither, the '
                'interlock has no evidence and never engages. If the signal '
                'goes stale past the sensor max age, it is treated as not '
                'running (a dead sensor must not seal the greenhouse).'
            ),
        },
        {
            'id': 'hvac_interlock_on_value',
            'type': 'float',
            'default_value': 0.5,
            'required': False,
            'name': lazy_gettext('Running Signal Threshold'),
            'phrase': lazy_gettext(
                'The signal counts as running at or above this value. Leave 0.5 '
                'for an on/off contact. For watts or amps, set it above the '
                'unit\'s standby draw so idle current does not read as running.'
            ),
        },

        # ── Growth Schedule ───────────────────────────────────────────────────
        # 시작일은 여기 없다 — 구획의 시작일이 정본이다. 남은 둘은 일정이
        # 아니라 **운영 결정**이다: 언제 제어를 멈출 것인가, 경과 주차를
        # 얼마나 보정할 것인가.
        {
            'type': 'header',
            'name': lazy_gettext('Growth Schedule'),
        },
        {
            'id': 'schedule_end_time',
            'type': 'text',
            'html_type': 'date',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Stop Control On'),
            'phrase': lazy_gettext(
                'A safety stop, not a harvest date: once this date passes, every '
                'actuator returns to its configured end-behavior and coordination '
                'cycles halt. The date is read in the device/facility local '
                'timezone. Leave empty for no stop date — the plot ending does '
                'not stop control on its own, because an empty house still needs '
                'its safety limits held.'
            ),
        },
        {
            'id': 'schedule_week_offset',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Week Offset'),
            'phrase': lazy_gettext(
                'Adjustment applied on top of the weeks elapsed since the plot '
                'started. Positive fast-forwards (the system was installed '
                'mid-cycle), negative compensates for downtime. Default 0.'
            ),
        },

        # ── Facility (optional) ──────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Facility (optional)'),
        },
        {
            'id': 'geo_facility_id',
            'type': 'select_device',
            'default_value': '',
            'required': False,
            'options_select': ['GeoFacility'],
            'name': lazy_gettext('Linked Facility'),
            'phrase': lazy_gettext(
                'When set, actuators are auto-discovered from this facility (envelope, '
                'side/roof vents, curtains, fans). GIS metadata (azimuth, area, U-value) '
                'is attached to each actuator profile so wind direction and facility '
                'geometry can be considered. Manual "Environment Control" actions below '
                'still apply and are merged with the facility-derived list. '
                'Leave empty to use manual actions only.'
            ),
        },
        {
            'id': 'bay_scope',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Bay Scope (optional)'),
            'phrase': lazy_gettext(
                'Restrict this coordinator to one bay of the linked facility. '
                'Enter the bay ID (see the facility editor bay list; e.g. "bay_1"). '
                'Only sensors and actuators placed inside that bay are used, and '
                'facility volume/area are scaled to the bay share. Leave empty to '
                'control the entire facility. Create one coordinator per bay to '
                'control multiple bays independently.'
            ),
        },

        # ── Time Control ──────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Time Control'),
        },
        {
            'id': 'time_enable',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Time Window'),
            'phrase': lazy_gettext(
                'When enabled, control only runs between Start and End times.'
            ),
        },
        {
            'id': 'time_start',
            'type': 'text',
            'default_value': '06:00',
            'required': False,
            'name': lazy_gettext('Start Time (HH:MM)'),
            'phrase': lazy_gettext(
                'Control period start time (24-hour format). '
                'Only active when Enable Time Window is turned on.'
            ),
        },
        {
            'id': 'time_end',
            'type': 'text',
            'default_value': '20:00',
            'required': False,
            'name': lazy_gettext('End Time (HH:MM)'),
            'phrase': lazy_gettext(
                'On-end behavior per actuator is configured in each Action. '
                'Ignored when Photoperiod Method is set.'
            ),
        },
        {
            'id': 'photo_method_id',
            'type': 'select_device',
            'default_value': '',
            'required': False,
            'options_select': ['Method'],
            'name': lazy_gettext('Photoperiod Method'),
            'phrase': lazy_gettext(
                'Optional. Select an AoT Method that returns photoperiod length in hours '
                '(e.g. 14.0 = 14 h light). The function computes time_start/end '
                'symmetrically around the Anchor time. '
                'When set, the static Start/End times above are overridden.'
            ),
        },
        {
            'id': 'photo_anchor',
            'type': 'text',
            'default_value': '12:00',
            'required': False,
            'name': lazy_gettext('Photoperiod Anchor (HH:MM)'),
            'phrase': lazy_gettext(
                'Solar-noon equivalent. The photoperiod window is centred on this time. '
                'Default 12:00. Adjust for your latitude / season if needed.'
            ),
        },

        # ── VPD (Primary control target) ──────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('VPD'),
        },
        {
            'id': 'priority_vpd',
            'type': 'float',
            'default_value': 1.2,
            'required': False,
            'name': lazy_gettext('VPD Priority'),
            'phrase': lazy_gettext('Higher value = processed first. Default 1.2.'),
        },
        {
            'id': 'tolerance_vpd',
            'type': 'float',
            'default_value': 0.1,
            'required': False,
            'name': lazy_gettext('VPD Tolerance (kPa)'),
            'phrase': lazy_gettext(
                'Dead-band half-width around the VPD setpoint. '
                'Adjustments are skipped when the deviation is within this range, '
                'reducing unnecessary actuator cycling. Typical value: 0.05–0.15 kPa.'
            ),
        },

        # ── Light ─────────────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Light Intensity'),
        },
        {
            'id': 'light_max',
            'type': 'float',
            'default_value': 800.0,
            'required': False,
            'name': lazy_gettext('Max Light Threshold'),
            'phrase': lazy_gettext(
                'Activate shade screen when light exceeds this value. 0 = disabled.'
            ),
        },
        {
            'id': 'light_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Min Light Threshold (Supplemental)'),
            'phrase': lazy_gettext(
                'Activate supplemental lighting when light falls below this value. '
                '0 = disabled (most facilities — natural light only).'
            ),
        },
        {
            'id': 'shade_transmittance',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Shade Cloth Transmittance (0-1)'),
            'phrase': lazy_gettext(
                'Fraction of light that passes through the shade cloth when fully '
                'closed. 0.30 = 70% shading. Used only when there is NO indoor light '
                'sensor: the indoor light level is then estimated from outdoor '
                'irradiance and the shade position, so the light thresholds can see '
                'the shading the screen itself creates. Applies to every shade '
                'actuator; a per-actuator value set on an Env Actuator action wins. '
                '0 = disabled (indoor light is assumed equal to outdoor irradiance).'
            ),
        },

        # ── CO₂ ───────────────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('CO₂'),
        },
        {
            'id': 'priority_co2',
            'type': 'float',
            'default_value': 0.8,
            'required': False,
            'name': lazy_gettext('CO₂ Priority'),
            'phrase': lazy_gettext(
                'Processing order weight for CO₂ relative to other control variables. '
                'Higher value = processed earlier in each cycle. '
                'Default 0.8 (lower than VPD 1.2, since CO₂ enrichment is secondary).'
            ),
        },
        {
            'id': 'tolerance_co2',
            'type': 'float',
            'default_value': 100.0,
            'required': False,
            'name': lazy_gettext('CO₂ Tolerance (ppm)'),
            'phrase': lazy_gettext(
                'Dead-band half-width around the CO₂ setpoint. '
                'Adjustments are skipped when the deviation is within this range. '
                'Typical value: 50–150 ppm.'
            ),
        },

        # ── Temperature (Constraints — not a primary target) ──────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Temperature'),
        },
        {
            'id': 'temp_max',
            'type': 'float',
            'default_value': 35.0,
            'required': False,
            'name': lazy_gettext('Max Temperature (°C)'),
            'phrase': lazy_gettext(
                'Hard upper limit. Forces cooling when exceeded, regardless of VPD target.'
            ),
        },
        {
            'id': 'temp_min',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Min Temperature (°C)'),
            'phrase': lazy_gettext(
                'Hard lower limit. Forces heating when below, regardless of VPD target.'
            ),
        },

        # ── Humidity (Constraints — not a primary target) ─────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Humidity'),
        },
        {
            'id': 'humid_max',
            'type': 'float',
            'default_value': 90.0,
            'required': False,
            'name': lazy_gettext('Max Humidity (%)'),
            'phrase': lazy_gettext(
                'Hard upper limit. Prevents VPD bypass via extreme humidity.'
            ),
        },
        {
            'id': 'humid_min',
            'type': 'float',
            'default_value': 30.0,
            'required': False,
            'name': lazy_gettext('Min Humidity (%)'),
            'phrase': lazy_gettext(
                'Hard lower limit. Prevents VPD bypass via extreme dryness.'
            ),
        },

        {
            'id': 'use_wetting_fog_for_humidity',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Use Wetting Misting to Raise Humidity'),
            'phrase': lazy_gettext(
                'Turn this off when the same nozzles are also your irrigation '
                'system. Sprinklers sized for watering put out far more water '
                'than humidity control needs, so each short burst leaves a film '
                'on the leaf that dries in place and concentrates whatever the '
                'water carries — a heavy morning watering runs off and rinses '
                'instead. With this off the coordinator never commands those '
                'nozzles at all, leaving them entirely to your irrigation '
                'schedule, and manages humidity with the screens, vents and '
                'fans instead. True high-pressure fog is unaffected either way; '
                'so are humidifiers, drip lines and every other actuator.'
            ),
        },

        # ── Nursery (Seedling Protection) ─────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Nursery Mode'),
        },
        {
            'id': 'nursery_mode',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Nursery (Seedling) Mode'),
            'phrase': lazy_gettext(
                'Protects newly emerged seedlings from leaf scorch. Droplets '
                'left on a cotyledon under strong sun focus light onto the leaf '
                'and concentrate dissolved minerals as they evaporate, and the '
                'seedling has no cuticle yet to resist either. When enabled, '
                'wetting-type misting is locked out above the irradiance '
                'threshold, tapered below it, and always broken into short '
                'pulses with an enforced drying interval. '
                'Whether a nozzle counts as wetting type is decided by the '
                'nozzle layout in the facility design (flow rate, spray radius, '
                'spray direction) — drip lines and true high-pressure fog are '
                'left alone.'
            ),
        },
        {
            'id': 'nursery_solar_lockout',
            'type': 'float',
            'default_value': 250.0,
            'required': False,
            'name': lazy_gettext('Misting Lockout Irradiance (W/m²)'),
            'phrase': lazy_gettext(
                'Wetting-type misting is blocked outright at or above this '
                'indoor light level. The estimated indoor level is used, so '
                'closing the shade screen relaxes the lockout.'
            ),
        },
        {
            'id': 'nursery_solar_release',
            'type': 'float',
            'default_value': 150.0,
            'required': False,
            'name': lazy_gettext('Misting Release Irradiance (W/m²)'),
            'phrase': lazy_gettext(
                'Misting is released again once the light falls below this '
                'level, and is tapered linearly between here and the lockout '
                'threshold. The gap between the two prevents the mist from '
                'switching on and off as clouds pass.'
            ),
        },
        {
            'id': 'nursery_max_on_sec',
            'type': 'float',
            'default_value': 20.0,
            'required': False,
            'name': lazy_gettext('Max Spray Duration (s)'),
            'phrase': lazy_gettext(
                'Longest single spray. Humidification is regulated by how often '
                'it sprays, not by how long — the same way irrigation doses a '
                'fixed amount at intervals.'
            ),
        },
        {
            'id': 'nursery_min_off_sec',
            'type': 'float',
            'default_value': 600.0,
            'required': False,
            'name': lazy_gettext('Enforced Drying Interval (s)'),
            'phrase': lazy_gettext(
                'No spraying at all for this long after one finishes, so the '
                'leaves get a chance to dry.'
            ),
        },
        {
            'id': 'nursery_evening_fog',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Allow Misting Before Sunset'),
            'phrase': lazy_gettext(
                'Watering usually happens around sunrise and sunset, but an '
                'evening misting leaves the foliage wet through the night. The '
                'longer the leaves stay wet, the higher the risk of grey mould '
                'and downy mildew, and a nursery is planted densely enough for '
                'it to spread fast. Turn this off to stop misting before sunset '
                'and leave the leaves dry overnight; some crops still need the '
                'evening watering, so the choice is yours. '
                'This only governs misting for humidity control — a separate '
                'irrigation schedule on the same valve is unaffected.'
            ),
        },
        {
            'id': 'nursery_evening_cutoff_min',
            'type': 'float',
            'default_value': 120.0,
            'required': False,
            'name': lazy_gettext('Stop Misting Before Sunset (min)'),
            'phrase': lazy_gettext(
                'How long before sunset misting stops, when the option above is '
                'off. Misting stays blocked until the next sunrise. Two hours is '
                'usually enough for the leaves to dry before dark. Ignored when '
                'evening misting is allowed, or when the facility has no '
                'coordinates to compute sunset from.'
            ),
        },
        {
            'id': 'nursery_water_source',
            'type': 'select',
            'default_value': 'groundwater',
            'required': False,
            'options_select': [
                ('groundwater', lazy_gettext('Groundwater (untreated)')),
                ('treated',     lazy_gettext('Treated (RO, softened, filtered)')),
                ('rainwater',   lazy_gettext('Rainwater')),
            ],
            'name': lazy_gettext('Misting Water Source'),
            'phrase': lazy_gettext(
                'Untreated groundwater is usually hard and cold, so droplets '
                'leave concentrated mineral deposits as they dry and can cold-'
                'shock a sunlit leaf. Selecting it lowers the lockout threshold '
                'automatically. Have the water tested for EC, hardness, iron '
                'and manganese — iron staining looks almost identical to sun '
                'scorch, and no control setting can fix bad water.'
            ),
        },

        # ── VPD Decomposition ─────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('VPD Decomposition'),
        },
        {
            'id': 'vpd_weight_T',
            'type': 'float',
            'default_value': 0.6,
            'required': False,
            'name': lazy_gettext('T Weight (0-1)'),
            'phrase': lazy_gettext(
                'VPD decomposition: fraction of adjustment via temperature (rest via humidity). '
                '0.6 = favour temperature adjustment. Range 0.0~1.0.'
            ),
        },

        # ── Photosynthesis Model (optional) ──────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Photosynthesis Model'),
        },
        {
            'id': 'photosynth_mode_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Photosynthesis-Oriented Control'),
            'phrase': lazy_gettext(
                'When enabled, the Big-Leaf photosynthesis model identifies the current '
                'limiting factor (Light / CO₂ / Temperature / VPD) each cycle and '
                'dynamically raises that variable\'s priority. Requires a light sensor. '
                'The crop parameters come from the program of the plot growing here — '
                'with no plot the model falls back to generic values, since there is no '
                'crop to optimise for.'
            ),
        },

        {
            'id': 'source_plot_id',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Reference Plot (optional)'),
            'phrase': lazy_gettext(
                'Which plot this coordinator follows, when more than one is growing '
                'in its scope. Leave empty when there is only one — it is picked '
                'automatically. Set from the comparison card at the top of this page.'
            ),
        },

        # ── Guide Ranges (T/RH) ───────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Guide Ranges (T / RH)'),
        },
        {
            'id': 'guide_T_min',
            'type': 'float',
            'default_value': 12.0,
            'required': False,
            'name': lazy_gettext('Guide T Min (°C)'),
            'phrase': lazy_gettext(
                'Advisory lower bound for temperature. '
                'Triggers forced heating when exceeded (replaces Min Temperature setting '
                'when using crop-preset-derived guide ranges).'
            ),
        },
        {
            'id': 'guide_T_max',
            'type': 'float',
            'default_value': 32.0,
            'required': False,
            'name': lazy_gettext('Guide T Max (°C)'),
            'phrase': lazy_gettext('Advisory upper bound for temperature.'),
        },
        {
            'id': 'guide_RH_min',
            'type': 'float',
            'default_value': 40.0,
            'required': False,
            'name': lazy_gettext('Guide RH Min (%)'),
            'phrase': lazy_gettext('Advisory lower bound for relative humidity.'),
        },
        {
            'id': 'guide_RH_max',
            'type': 'float',
            'default_value': 85.0,
            'required': False,
            'name': lazy_gettext('Guide RH Max (%)'),
            'phrase': lazy_gettext('Advisory upper bound for relative humidity.'),
        },

        # ── Cumulative Goal Tracker ───────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Cumulative Goal Tracker'),
        },
        {
            'id': 'cumulative_tracker_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable DLI / GDD Tracker'),
            'phrase': lazy_gettext(
                'Tracks daily light integral (DLI) and growing degree-days (GDD), '
                'rolling over at the facility-local midnight (device timezone). '
                'Light is converted to PPFD by sensor unit (W/m² assumed if unknown). '
                'Generates compensation suggestions when debt accumulates. '
                'Requires a Light sensor for DLI tracking.'
            ),
        },

        # ── Wind ──────────────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Wind'),
        },
        {
            'id': 'gate_wind_threshold',
            'type': 'float',
            'default_value': 12.0,
            'required': False,
            'name': lazy_gettext('Strong Wind Threshold (m/s)'),
            'phrase': lazy_gettext(
                'Openings (vents, side walls) are forced closed above this wind speed.'
            ),
        },

        # ── Calibration (Stage 1) ─────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Effect Calibration'),
        },
        {
            'id': 'effect_engine',
            'type': 'select',
            'default_value': 'legacy',
            'required': False,
            'options_select': [
                ('legacy',   lazy_gettext('Legacy (built-in K constants)')),
                ('shadow',   lazy_gettext('Shadow (grey-box logged, legacy controls)')),
                ('greybox',  lazy_gettext('Grey-box (physics model controls)')),
            ],
            'name': lazy_gettext('Effect Engine'),
            'phrase': lazy_gettext(
                'Legacy: uses built-in K_* constants (default, safe). '
                'Shadow: runs grey-box model in parallel for KPI logging only — no control change. '
                'Grey-box: physics-model control (effect magnitudes from the grey-box model, '
                'with MPC look-ahead when a forecast is available). '
                'Grey-box activates ONLY after the shadow KPI passes and parameters have '
                'converged; until then it automatically falls back to Legacy control. '
                'Recommended flow: run Shadow first, then switch to Grey-box.'
            ),
        },
        {
            'id': 'calibration_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable RLS Calibration'),
            'phrase': lazy_gettext(
                'Learn per-actuator effect coefficients (K_*) from sensor response. '
                'Requires several days of data to converge. '
                'Falls back to built-in defaults until convergence.'
            ),
        },
        {
            'id': 'enable_active_probing',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Active Probing'),
            'phrase': lazy_gettext(
                'Periodically perturb one actuator by ±10 %% to improve calibration '
                'identifiability. Only triggers when load is low and no safety gate is active. '
                'Requires RLS Calibration to be enabled.'
            ),
        },
        {
            'id': 'probe_interval_sec',
            'type': 'float',
            'default_value': 3600.0,
            'required': False,
            'name': lazy_gettext('Probe Interval (seconds)'),
            'phrase': lazy_gettext(
                'Minimum time between active probing events. Default 3600 s (1 hour).'
            ),
        },

        # ── Forecast Feedforward (P3-4) ───────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Forecast Feedforward'),
        },
        {
            'id': 'forecast_feedforward_enabled',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Forecast Feedforward'),
            'phrase': lazy_gettext(
                'Use KMA short-term weather forecast (forecast.json) to proactively '
                'shift temperature/humidity setpoints and inhibit ventilation '
                'before adverse weather arrives.'
            ),
        },
        {
            'id': 'forecast_lookahead_h',
            'type': 'float',
            'default_value': 3.0,
            'required': False,
            'name': lazy_gettext('Forecast Lookahead (hours)'),
            'phrase': lazy_gettext(
                'How many hours ahead to check for incoming adverse weather (1–6 h). '
                'Longer lookahead gives earlier warning but may over-correct.'
            ),
        },

        # ── Diagnostics ───────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Diagnostics'),
        },
        {
            'id': 'debug_logging',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Debug Logging'),
            'phrase': lazy_gettext(
                'Write per-cycle decision data to InfluxDB (goal targets, deviations, '
                'mode, cycle metrics, actuator mismatch count, learning hygiene). '
                'Also emits per-cycle DEBUG log lines (constraint violations, '
                'feedforward decisions, deadband skips). Leave OFF for production — '
                'critical events (safety gate, dispatch failure, runtime state error) '
                'are always recorded regardless of this flag.'
            ),
        },
    ],
}
