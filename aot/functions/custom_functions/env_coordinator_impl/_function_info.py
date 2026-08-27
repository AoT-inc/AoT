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
            'advanced_only': True,
            'type': 'select_scale',
            'unit': 's',
            'axis_low': lazy_gettext('Fewer decisions'),
            'axis_high': lazy_gettext('Faster response'),
            'steps': [(600.0, lazy_gettext('Relaxed')), (300.0, lazy_gettext('Slow')), (120.0, lazy_gettext('Standard')), (60.0, lazy_gettext('Responsive'))],
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
            'advanced_only': True,
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
                'How often the vents may move. Emergencies and safety gates ignore this.'
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
            'advanced_only': True,
            'type': 'select_scale',
            'unit': '×',
            'axis_low': lazy_gettext('Reacts later'),
            'axis_high': lazy_gettext('Reacts sooner'),
            'steps': [(5.0, lazy_gettext('Late')), (4.0, lazy_gettext('Relaxed')), (3.0, lazy_gettext('Standard')), (2.0, lazy_gettext('Early'))],
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
            'advanced_only': True,
            'type': 'select_scale',
            'unit': '°C/10min',
            'axis_low': lazy_gettext('Reacts later'),
            'axis_high': lazy_gettext('Reacts sooner'),
            'steps': [(3.0, lazy_gettext('Late')), (2.0, lazy_gettext('Standard')), (1.5, lazy_gettext('Early'))],
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
                'Close the vents when the outdoor air cannot move the reading toward the target.'
            ),
        },

        # ── Night Vent Parking ────────────────────────────────────────────────
        # ⚠ 이것은 `time_enable`(시간창)의 확장이 **아니다.** 시간창은 창밖
        #   시간에 제어를 통째로 멈추는데(`_apply_end_behaviors()` 후 return),
        #   여기서 원하는 것은 **수단의 제한**이다 — 창만 닫고 냉난방·제습은
        #   계속 돈다. 섞으면 밤에 난방까지 멈춘다.
        {
            'type': 'header',
            'name': lazy_gettext('Night Vent Parking'),
        },
        {
            'id': 'night_vent_park',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Keep Vents Closed at Night'),
            'phrase': lazy_gettext(
                'Keep the vents closed overnight and let heating, cooling and drying carry the load.'
            ),
        },
        {
            'id': 'night_vent_basis',
            'depends_on': 'night_vent_park',
            'type': 'select',
            'default_value': 'sun',
            'required': False,
            'options_select': [
                ('sun',   lazy_gettext('Sunset to sunrise')),
                ('clock', lazy_gettext('Fixed clock times')),
            ],
            'name': lazy_gettext('Night Starts At'),
            'phrase': lazy_gettext(
                'Whether night is measured from sunset to sunrise, or by fixed clock times.'
            ),
        },
        {
            'id': 'night_vent_sunset_offset_min',
            'depends_on': 'night_vent_park',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Close Before Sunset (min)'),
            'phrase': lazy_gettext(
                'Start closing this many minutes before sunset.'
            ),
        },
        {
            'id': 'night_vent_start',
            'depends_on': 'night_vent_park',
            'type': 'text',
            'default_value': '18:00',
            'required': False,
            'name': lazy_gettext('Night Start (HH:MM)'),
            'phrase': lazy_gettext(
                'When night starts, if you chose fixed clock times.'
            ),
        },
        {
            'id': 'night_vent_end',
            'depends_on': 'night_vent_park',
            'type': 'text',
            'default_value': '06:00',
            'required': False,
            'name': lazy_gettext('Night End (HH:MM)'),
            'phrase': lazy_gettext(
                'When night ends, if you chose fixed clock times.'
            ),
        },

        # ── Heating / Cooling Interlock ───────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Heating / Cooling Interlock'),
        },
        {
            'id': 'vent_first',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Rest Heating and Cooling When Venting Can Reach the Target'),
            'phrase': lazy_gettext(
                'Rest heating and cooling while the outdoor air alone can reach the target.'
            ),
        },
        {
            'id': 'hvac_interlock',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Keep Vents Closed While Heating or Cooling Runs'),
            'phrase': lazy_gettext(
                'Close the vents while heating or cooling is running.'
            ),
        },
        {
            'id': 'hvac_interlock_signal',
            'depends_on': 'hvac_interlock',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': [
                'Input',
                'Function',
            ],
            'name': lazy_gettext('Heating / Cooling Running Signal'),
            'phrase': lazy_gettext(
                'A measurement that rises when a hand-operated unit runs, so the system can tell.'
            ),
        },
        {
            'id': 'hvac_interlock_on_value',
            'depends_on': 'hvac_interlock',
            'type': 'float',
            'default_value': 0.5,
            'required': False,
            'name': lazy_gettext('Running Signal Threshold'),
            'phrase': lazy_gettext(
                'Above this value the unit counts as running.'
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
                'A safety stop: control halts after this date. Leave blank to run indefinitely.'
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
                'Which facility this coordinator runs. Actuators and sensors come from it.'
            ),
        },
        {
            'id': 'bay_scope',
            # ⚠ 자유 텍스트가 아니다 (2026-08-26). 오타 하나가 "이 구역만
            #   제어한다" 를 무너뜨리는데, 화면에는 아무 표시도 안 났다.
            #   `select_bay` 는 연결된 시설의 구역을 그 자리에서 불러 채운다
            #   (`/api/aot/facility/<uuid>/bays`). 시설 선택을 바꾸면 목록도
            #   따라 바뀐다.
            'type': 'select_bay',
            'default_value': '',
            'required': False,
            # 목록을 어느 시설에서 가져올지 — 같은 폼의 옵션 id 를 가리킨다.
            'bay_source_option': 'geo_facility_id',
            'name': lazy_gettext('Bay Scope (optional)'),
            'phrase': lazy_gettext(
                'Limit this coordinator to one bay. Leave blank for the whole facility.'
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
            'advanced_only': True,
            'type': 'select_scale',
            'unit': 'kPa',
            'axis_low': lazy_gettext('Moves equipment less'),
            'axis_high': lazy_gettext('Tracks the target closely'),
            'steps': [(0.2, lazy_gettext('Loose')), (0.15, lazy_gettext('Relaxed')), (0.1, lazy_gettext('Standard')), (0.05, lazy_gettext('Tight'))],
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
                'How much light the closed shade cloth lets through. Only used without an indoor light sensor.'
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
            'advanced_only': True,
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
            'advanced_only': True,
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
            'advanced_only': True,
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
            'advanced_only': True,
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
                'Use the misting nozzles for humidity too. Turn off when they are your irrigation.'
            ),
        },

        # ── 습윤형 분무 일소 보호 (육묘 여부와 무관) ───────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Misting Sunburn Protection'),
        },
        {
            'id': 'nursery_solar_lockout',
            'advanced_only': True,
            'depends_on': 'nursery_mode',
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
            'advanced_only': True,
            'depends_on': 'nursery_mode',
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
                'Tighter misting limits for seedlings, which scorch more easily than grown leaves.'
            ),
        },
        {
            'id': 'nursery_max_on_sec',
            'advanced_only': True,
            'depends_on': 'nursery_mode',
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
            'advanced_only': True,
            'depends_on': 'nursery_mode',
            'type': 'select_scale',
            'unit': 's',
            'axis_low': lazy_gettext('Humidity rises faster'),
            'axis_high': lazy_gettext('More time for leaves to dry'),
            'steps': [(300.0, lazy_gettext('Short')), (600.0, lazy_gettext('Standard')), (900.0, lazy_gettext('Long')), (1800.0, lazy_gettext('Very long'))],
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
            'depends_on': 'nursery_mode',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Allow Misting Before Sunset'),
            'phrase': lazy_gettext(
                'Allow misting near sunset. Turn off to leave the leaves dry overnight.'
            ),
        },
        {
            'id': 'nursery_evening_cutoff_min',
            'depends_on': 'nursery_mode',
            'type': 'float',
            'default_value': 120.0,
            'required': False,
            'name': lazy_gettext('Stop Misting Before Sunset (min)'),
            'phrase': lazy_gettext(
                'How long before sunset misting stops.'
            ),
        },
        {
            'id': 'nursery_water_source',
            'depends_on': 'nursery_mode',
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
                'Harder or colder water needs a lower sunburn threshold, which this sets for you.'
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
                'Let the model decide which of light, CO₂, temperature or VPD is limiting right now.'
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
            'advanced_only': True,
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
            'advanced_only': True,
            'type': 'float',
            'default_value': 32.0,
            'required': False,
            'name': lazy_gettext('Guide T Max (°C)'),
            'phrase': lazy_gettext('Advisory upper bound for temperature.'),
        },
        {
            'id': 'guide_RH_min',
            'advanced_only': True,
            'type': 'float',
            'default_value': 40.0,
            'required': False,
            'name': lazy_gettext('Guide RH Min (%)'),
            'phrase': lazy_gettext('Advisory lower bound for relative humidity.'),
        },
        {
            'id': 'guide_RH_max',
            'advanced_only': True,
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
                'Which model computes the effect of each actuator. Change only while testing.'
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
            'type': 'select_scale',
            'unit': 's',
            'axis_low': lazy_gettext('Probes more often'),
            'axis_high': lazy_gettext('Probes rarely'),
            'steps': [(1800.0, lazy_gettext('Often')), (3600.0, lazy_gettext('Standard')), (10800.0, lazy_gettext('Rare'))],
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
            'type': 'select_scale',
            'unit': 'h',
            'axis_low': lazy_gettext('Reacts to what is here now'),
            'axis_high': lazy_gettext('Prepares further ahead'),
            'steps': [(1.0, lazy_gettext('Short')), (3.0, lazy_gettext('Standard')), (6.0, lazy_gettext('Long'))],
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
                'Record every cycle decision. Turn on while diagnosing, off afterwards.'
            ),
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 화면 배치 — 위 목록의 **순서를 여기서 다시 정한다** (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 옵션이 62개인데 순서가 "필요한 순서" 가 아니라 **"추가된 순서"** 였다. 그래서
# 스크롤만 하다 지치고, 관계 있는 것끼리 멀리 떨어져 있었다:
#
#   · 시설 연결이 6번째 — 센서·액추에이터·구역이 전부 여기 딸려 있어서 이것을
#     안 고르면 나머지가 의미가 없다.
#   · 온습도 하드 임계(11·12번)와 유도 범위(17번)가 다섯 섹션 떨어져 있었다.
#     **둘은 서로 간섭한다** — 저장 시 경고(`execute_at_modification`)가 필요했던
#     이유가 정확히 그 거리다.
#   · `vent_futility_gate` 가 "구동 주기" 안에 있었다. 환기 전략인데 모터 주기
#     설정에 숨어 있어 찾을 수가 없다.
#
# **목록 자체는 건드리지 않는다.** 여기서 순서만 바꾸므로 옵션 정의와 배치가
# 한 파일 안에서 분리돼, 배치를 고칠 때 정의를 실수로 망가뜨릴 일이 없다.
#
# ⚠ **옵션 id 는 그대로다** — 저장된 값도 동작도 바뀌지 않는다. 되돌리려면 이
#   블록만 지우면 원래 순서로 돌아간다.
#
# ⚠ 이 화면은 "무엇을 목표로 할지" 가 아니라 **"어떻게 제어할지"** 를 정하는
#   곳이다. 목표 곡선은 구획의 프로그램(`GeoProgram.targets_methods`)이 갖는다
#   — 옛 `vpd_sp_type`/`vpd_method_id` 가 하던 일이 그리로 옮겨갔다.

# ─────────────────────────────────────────────────────────────────────────────
# 핵심 옵션 — **한 질문이 여러 값을 움직인다** (로봇 청소기의 운전모드)
# ─────────────────────────────────────────────────────────────────────────────
# 로봇 청소기는 "조용히 / 중간 / 강하게" 하나로 모터 회전수·이동 속도·걸레
# 작동·회피 알고리즘을 함께 정한다. 사용자가 답할 수 있는 질문은 **세기**
# 하나이고, 모터 rpm 을 몇으로 할지는 답할 수 없는 질문이다.
#
# 여기도 같다. `emergency_deviation_mult` 에 3.0 을 넣을지 4.0 을 넣을지는
# 답할 수 없지만, "느긋하게 ↔ 민감하게" 는 답할 수 있다.
#
#   핵심 옵션(항상 보임)   제어 성향  ○──●──○
#   세부 옵션([고급])       update_period · actuation_profile · tolerance_vpd
#                          emergency_deviation_mult · emergency_rate_c_per_10min
#
# ⚠ **그룹 선택을 저장하지 않는다.** 저장되는 것은 멤버 값 N개뿐이고, 핵심
#   옵션이 어느 단계인지는 **그 값들에서 되짚는다**. 모드 문자열을 따로 저장한
#   `actuation_profile` 이 정확히 그 실수를 했다 — 모드와 숫자가 어긋나
#   쿠마모토의 1200 은 코드가 안 보는 죽은 값이었다.
#   되짚기라서, 어느 단계와도 안 맞으면 **'직접 지정'** 으로 보인다.
#
# ⚠ 멤버는 `advanced_only` 로 표시한다 — [고급] 을 켜야 나온다. 핵심 옵션만으로
#   끝나야 정리가 된 것이고, 세부가 늘 보이면 옵션 62개 시절과 같다.
_SCALE_GROUPS = [
    {
        'id': 'responsiveness',
        'name': lazy_gettext('Control Temperament'),
        'phrase': lazy_gettext(
            'How hard the system chases the target. Sets the cycle, how often '
            'vents may move, the dead-band and the emergency thresholds together.'
        ),
        'axis_low':  lazy_gettext('Moves equipment less'),
        'axis_high': lazy_gettext('Tracks the target closely'),
        'members': ['update_period', 'actuation_profile', 'tolerance_vpd',
                    'emergency_deviation_mult', 'emergency_rate_c_per_10min'],
        'steps': [
            (lazy_gettext('Relaxed'), {
                'update_period': 600.0, 'actuation_profile': 'gentle',
                'tolerance_vpd': 0.15, 'emergency_deviation_mult': 4.0,
                'emergency_rate_c_per_10min': 3.0}),
            (lazy_gettext('Standard'), {
                'update_period': 120.0, 'actuation_profile': 'standard',
                'tolerance_vpd': 0.1, 'emergency_deviation_mult': 3.0,
                'emergency_rate_c_per_10min': 2.0}),
            (lazy_gettext('Responsive'), {
                'update_period': 60.0, 'actuation_profile': 'responsive',
                'tolerance_vpd': 0.05, 'emergency_deviation_mult': 2.0,
                'emergency_rate_c_per_10min': 1.5}),
        ],
    },
    {
        'id': 'misting_care',
        'depends_on': 'nursery_mode',
        'name': lazy_gettext('Misting Caution'),
        'phrase': lazy_gettext(
            'How careful misting is with the leaves. Sets spray length, drying '
            'interval and the sunburn thresholds together.'
        ),
        'axis_low':  lazy_gettext('Humidity rises faster'),
        'axis_high': lazy_gettext('Gentler on the leaves'),
        'members': ['nursery_max_on_sec', 'nursery_min_off_sec',
                    'nursery_solar_lockout', 'nursery_solar_release'],
        'steps': [
            (lazy_gettext('Bold'), {
                'nursery_max_on_sec': 30.0, 'nursery_min_off_sec': 300.0,
                'nursery_solar_lockout': 400.0, 'nursery_solar_release': 250.0}),
            (lazy_gettext('Standard'), {
                'nursery_max_on_sec': 20.0, 'nursery_min_off_sec': 600.0,
                'nursery_solar_lockout': 250.0, 'nursery_solar_release': 150.0}),
            (lazy_gettext('Careful'), {
                'nursery_max_on_sec': 10.0, 'nursery_min_off_sec': 900.0,
                'nursery_solar_lockout': 150.0, 'nursery_solar_release': 80.0}),
        ],
    },
]

_RANGE_BANDS = [
    {
        'id': 'temperature',
        'name': lazy_gettext('Growing Temperature'),
        'hard_label': lazy_gettext('never past'),
        'unit': '°C', 'axis_min': 0.0, 'axis_max': 45.0, 'step': 0.5,
        'margin': 5.0,
        'guide_min': 'guide_T_min', 'guide_max': 'guide_T_max',
        'hard_min': 'temp_min', 'hard_max': 'temp_max',
    },
    {
        'id': 'humidity',
        'name': lazy_gettext('Growing Humidity'),
        'hard_label': lazy_gettext('never past'),
        'unit': '%', 'axis_min': 10.0, 'axis_max': 100.0, 'step': 1.0,
        'margin': 5.0,
        'guide_min': 'guide_RH_min', 'guide_max': 'guide_RH_max',
        'hard_min': 'humid_min', 'hard_max': 'humid_max',
    },
]

_RANGE_MEMBERS = {v for b in _RANGE_BANDS
                  for k, v in b.items()
                  if k in ('guide_min', 'guide_max', 'hard_min', 'hard_max')}

_GROUP_MEMBERS = {m for g in _SCALE_GROUPS for m in g['members']}

#   (접힘?, 제목, [(소제목|None, [옵션 id …]) …])
_LAYOUT = [
    # ── 층 1·2: 항상 보인다 — 이것만 정하면 돈다 ─────────────────────────────
    (False, lazy_gettext('Facility'), [
        (None, ['geo_facility_id', 'bay_scope']),
    ]),
    # 하드 임계는 "목표" 가 아니라 **넘지 말아야 할 선**이다. 제목이 그것을
    # 말해야 유도 범위와 헷갈리지 않는다. VPD 허용오차를 같이 두는 이유도
    # 같다 — 셋 다 "내가 지켜야 할 선" 이다.
    # 사용자가 답할 수 있는 질문은 **"몇 도에서 몇 도로 기를 것인가"** 하나다.
    # 넘으면 안 되는 선은 그 범위에서 여유를 둔 값이지 따로 생각해서 넣는 값이
    # 아니다 — 슬라이더 손잡이는 둘이고 하드 임계는 ∓여유로 따라온다.
    (False, lazy_gettext('Growing Range'), [
        (None, ['@range:temperature', '@range:humidity']),
    ]),
    # ⚠ **유도 범위는 하드 임계 바로 뒤다.** 둘이 어긋나면 목표가 조용히
    #   좁혀지므로(저장 시 경고가 필요했던 이유가 그 거리다), 하나를 고칠 때
    #   다른 하나가 손 닿는 곳에 있어야 한다. 접혀 있지만 **바로 다음 줄**이다.

    # ── 층 3: 전략 — 이해하고 고르는 정책 ────────────────────────────────────
    # ⚠ **토글만 보이고 하위 설정은 켜야 나온다**(`depends_on`). 야간 파킹을
    #   쓰지 않는 사람에게 기준·오프셋·시각 4개가 늘 보이면, 자기가 안 쓰는
    #   것까지 정해야 하는 줄 안다.
    # ⚠ 하위 설정을 **다른 곳으로 빼지 않는다** — 토글 바로 아래가 그 값의
    #   자리다(설계문서 §3-2).
    (False, lazy_gettext('Control Strategy'), [
        # 핵심 옵션 — 이것만 정하면 세부 5개가 따라온다.
        (None, ['@group:responsiveness']),
        (None, ['vent_futility_gate', 'vent_first']),
        (None, ['hvac_interlock', 'hvac_interlock_signal',
                'hvac_interlock_on_value']),
        (None, ['night_vent_park', 'night_vent_basis',
                'night_vent_sunset_offset_min', 'night_vent_start',
                'night_vent_end']),
        (None, ['nursery_mode', '@group:misting_care',                'nursery_water_source', 'nursery_evening_fog',
                'nursery_evening_cutoff_min',                'use_wetting_fog_for_humidity']),
    ]),

    # ── 층 4: 튜닝 — 안 건드리는 게 정상 ─────────────────────────────────────
    # 유도 범위는 하드 임계와 **서로 간섭**하므로 맨 앞에 둔다(둘이 어긋나면
    # 목표가 조용히 좁혀진다 — 저장 시 경고가 필요했던 이유가 그 거리다).
    (True, lazy_gettext('Schedule and Time'), [
        (lazy_gettext('Growth Schedule'),
         ['schedule_end_time', 'schedule_week_offset']),
        (lazy_gettext('Time Control'),
         ['time_enable', 'time_start', 'time_end',
          'photo_method_id', 'photo_anchor']),
    ]),
    (True, lazy_gettext('Cycle and Response'), [
        (None, [                'sensor_max_age',                'actuation_period_sec', 'emergency_period_sec',
                'gate_wind_threshold']),
    ]),
    (True, lazy_gettext('Light and CO₂'), [
        (None, ['light_max', 'light_min', 'shade_transmittance',
                'priority_co2', 'tolerance_co2']),
    ]),
    (True, lazy_gettext('Model and Calibration'), [
        (None, ['photosynth_mode_enabled', 'source_plot_id', 'vpd_weight_T',
                'priority_vpd', 'cumulative_tracker_enabled']),
        (lazy_gettext('Effect Calibration'),
         ['effect_engine', 'calibration_enabled',
          'enable_active_probing', 'probe_interval_sec']),
        (lazy_gettext('Forecast Feedforward'),
         ['forecast_feedforward_enabled', 'forecast_lookahead_h']),
    ]),
    (True, lazy_gettext('Diagnostics'), [
        (None, ['debug_logging']),
    ]),
]


def _emit_members(out, used, by_id, member_ids):
    """핵심 옵션 **바로 뒤에** 그 세부를 놓는다(그리고 원래 자리에서 뺀다).

    ⚠ **같은 값을 두 곳에서 확인하게 두지 말 것.** 예전에는 핵심 옵션이 첫
      화면에 있고 그 세부는 저 아래 접힌 묶음에 흩어져 있었다. 온도는 실제로
      **세 곳**에 나왔다 — 슬라이더 · `guide_T_min/max` · `temp_min/max`.
      같은 숫자를 세 번 확인해야 하고, 어느 것이 정본인지 알 수 없다
      (2026-08-27 사용자 신고: "심지어 온도는 반복되어 여러 곳에서 확인함").

    ⚠ 그리고 **[고급] 이 열어 줄 것이 그 자리에 없었다.** 핵심 옵션의 [고급]
      을 눌러도 세부가 화면 저편에 있으면 눌러도 아무 일이 안 일어난 것처럼
      보인다 — "고급을 눌러서 따라다니던 그 하위 옵션들은 어디에 있는거야?"
      가 그 말이다.

    `used` 에 넣으므로 뒤에서 다시 나오지 않는다. 배치에 안 적힌 세부도 여기서
    나오므로 `leftover` 로 밀려나지 않는다.
    """
    for mid in member_ids:
        if not mid or mid in used or mid not in by_id:
            continue
        out.append(by_id[mid])
        used.add(mid)


def _apply_layout(options, layout):
    """선언한 배치대로 옵션을 다시 늘어놓는다 → 새 목록.

    ⚠ **배치에서 빠진 옵션을 버리지 않는다.** 옵션을 추가하고 배치에 안 넣으면
      화면에서 조용히 사라지는데, 그러면 저장 폼에도 없어 그 설정을 영영 못
      바꾼다 — 무에러다. 빠진 것은 맨 끝에 모아 두고
      `test_option_layout.py` 가 그 사실을 잡는다.
    """
    # ⚠ 배치 표식도 `id` 를 갖는다(접힘 앵커) — **옵션으로 세면 안 된다.**
    #   두 번 적용될 때 그 표식이 '분류 안 됨' 으로 밀려나 화면에 새 묶음이
    #   생긴다. 값을 싣는 종류만 본다.
    # ⚠ **값을 싣지 않는 종류는 전부 여기 있어야 한다.** `range_band` 는 `id`
    #   를 갖는데(어느 밴드인지) 옵션이 아니다 — 빠뜨렸더니 두 번째 적용에서
    #   '분류 안 됨' 으로 밀려나 화면 끝에 유령 항목이 생겼다
    #   (`test_applying_twice_is_stable` 가 잡았다).
    _MARKERS = ('collapse_start', 'collapse_end', 'header',
                'env_status', 'scale_group', 'range_band')
    real = [o for o in options if o.get('id') and o.get('type') not in _MARKERS]
    by_id = {o['id']: o for o in real}
    out, used = [], set()
    # ── 머리말 — 설정이 아니라 **답**이다 (단계 A) ───────────────────────────
    # "지금 뭘 하고 있나" 와 "목표는 어디서 정하나" 에 화면이 답한다. 설정 62개
    # 위에 놓이는 이유: 결과를 확인할 수 없으면 설정이 맞는지 알 수 없고,
    # **확인할 수 없는 것은 믿을 수 없다**(설계문서 §2-2).
    #
    # ⚠ **옵션이 아니라 표식이다.** 값을 싣지 않으므로 `header` 와 같은 부류이고,
    #   파서의 표시 전용 목록에 함께 있어야 한다 — 빠지면 "Unknown option type"
    #   으로 파싱이 통째로 멈춘다(2026-08-27 collapse 표식이 실제로 그랬다).
    # ⚠ `message` 로는 안 된다 — 그쪽은 import 시점에 고정된 문자열이라 모든
    #   코디네이터가 같은 것을 보게 된다. 자리만 깔고 JS 가 채운다.
    out.append({'type': 'env_status'})
    for folded, title, blocks in layout:
        if folded:
            # ⚠ **접힘마다 고유한 id 가 있어야 한다.** 템플릿이 DOM 앵커를
            #   `name_prefix ~ (id or 'advanced')` 로 만들므로, id 가 없으면
            #   모든 접힘이 같은 `…_advanced` 를 가리켜 **어느 버튼을 눌러도
            #   맨 위 것만 펼쳐진다**(2026-08-27 사용자 신고).
            #
            # ⚠ 제목에서 만들면 안 된다 — 제목은 번역되므로 언어를 바꾸면
            #   앵커가 달라진다. 그 묶음의 **첫 옵션 id** 를 쓴다: 유일하고,
            #   ASCII 이고, 번역과 무관하며, 옵션을 옮기면 자연히 따라간다.
            first_id = next((i for _s, ids in blocks for i in ids), 'advanced')
            # ⚠ 앵커가 **옵션 id 로 끝나면 안 된다.** `[id$="_update_period"]`
            #   같은 접미사 선택자가 접힘 div 를 옵션 입력으로 잘못 집는다
            #   (2026-08-27 실측). 뒤에 표식을 붙여 그 겹침을 없앤다.
            out.append({'type': 'collapse_start',
                        'id': 'grp_%s_fold' % first_id, 'name': title})
        else:
            out.append({'type': 'header', 'name': title})
        for subtitle, ids in blocks:
            # ⚠ **소제목 없는 블록에 그룹 제목을 다시 내지 말 것.** 예전에는
            #   블록마다 제목을 반복했는데, 열린 그룹에서는 같은 제목이 네 번
            #   찍혔다(2026-08-27 화면 실측: "Control Strategy" ×4). 블록은
            #   묶음의 구분일 뿐 제목이 필요한 단위가 아니다.
            if subtitle is not None:
                out.append({'type': 'header', 'name': subtitle})
            for oid in ids:
                # ⚠ **핵심 옵션의 자리는 레이아웃이 정한다.** 예전에는 첫 멤버
                #   옆에 자동으로 놓았는데, 멤버가 전부 접힘(튜닝) 안에 있어서
                #   **핵심 옵션까지 접혀 버렸다**(2026-08-27 화면 실측). 핵심은
                #   항상 보이는 층에 있어야 그것만으로 끝낼 수 있다.
                if oid.startswith('@range:'):
                    rid = oid.split(':', 1)[1]
                    for bnd in _RANGE_BANDS:
                        if bnd['id'] == rid:
                            item = dict(bnd)
                            item['type'] = 'range_band'
                            out.append(item)
                            _emit_members(
                                out, used, by_id,
                                [bnd.get(k) for k in ('guide_min', 'guide_max',
                                                      'hard_min', 'hard_max')])
                    continue
                if oid.startswith('@group:'):
                    gid = oid.split(':', 1)[1]
                    for g in _SCALE_GROUPS:
                        if g['id'] == gid:
                            item = {'type': 'scale_group', 'group': g}
                            if g.get('depends_on'):
                                item['depends_on'] = g['depends_on']
                            out.append(item)
                            _emit_members(out, used, by_id, g['members'])
                    continue
                if oid not in by_id or oid in used:
                    continue
                out.append(by_id[oid])
                used.add(oid)
        if folded:
            out.append({'type': 'collapse_end'})
    leftover = [o for o in real if o['id'] not in used]
    if leftover:
        out.append({'type': 'collapse_start',
                    'name': lazy_gettext('Not Yet Categorised')})
        out.extend(leftover)
        out.append({'type': 'collapse_end'})
    return out


FUNCTION_INFORMATION['custom_options'] = _apply_layout(
    FUNCTION_INFORMATION['custom_options'], _LAYOUT)


# ─────────────────────────────────────────────────────────────────────────────
# 조건부로 **안 쓰이는** 옵션 — "내가 정한 값이 무시되는데 알 방법이 없다"
# ─────────────────────────────────────────────────────────────────────────────
# 어떤 옵션은 다른 옵션이 특정 값일 때만 읽힌다. 그 조건이 아니면 사용자가
# 입력한 값이 **조용히 버려진다** — 화면에는 그대로 남아 있으므로 자기가 정한
# 대로 돌고 있다고 믿는다.
#
# 실측(2026-08-27 쿠마모토 イチゴ):
#
#     저장된 actuation_profile      'gentle'
#     저장된 actuation_period_sec   1200      ← 화면에 이 값이 보인다
#     실제로 쓰이는 주기            600       ← gentle 의 값
#
# `profile != 'custom'` 이면 코드가 숫자 칸을 아예 보지 않는다. 20분마다
# 움직이라고 적어 뒀는데 10분마다 움직이고, 그 사실이 어디에도 안 드러난다.
#
# ⚠ **한 건이 아니라 부류다.** `night_vent_basis` 도 같은 모양이라
#   (일몰 기준이면 시각 칸이, 시각 기준이면 오프셋이 안 쓰인다) 명부로 둔다.
#   조건부 옵션을 새로 만들면 **여기 등록할 것** — 등록하지 않으면 그 옵션은
#   같은 방식으로 조용히 무시된다.
#
#   (값 옵션, 조건 옵션, 조건이 이 값일 때만 쓰임, 이 기능 토글이 켜졌을 때만 따짐)
_INERT_UNLESS = (
    ('actuation_period_sec',         'actuation_profile', 'custom', None),
    ('night_vent_sunset_offset_min', 'night_vent_basis',  'sun',   'night_vent_park'),
    ('night_vent_start',             'night_vent_basis',  'clock', 'night_vent_park'),
    ('night_vent_end',               'night_vent_basis',  'clock', 'night_vent_park'),
)


def inert_options(values):
    """지금 설정에서 **입력됐지만 안 쓰이는** 옵션 → [(값 옵션, 조건 옵션, 필요값)].

    `values` 는 저장된 custom_options dict.

    ⚠ **기본값은 보고하지 않는다.** 사용자가 정한 적 없는 값이 안 쓰이는 것은
      알릴 일이 아니다 — 그것까지 말하면 매번 네 줄이 뜨고 아무도 안 읽는다.
    ⚠ **기능 토글이 꺼져 있으면 보고하지 않는다.** 야간 파킹을 안 쓰는 사람에게
      그 하위 설정이 안 쓰인다고 말하는 것은 당연한 소리다.
    """
    defaults = {o['id']: o.get('default_value')
                for o in FUNCTION_INFORMATION['custom_options'] if o.get('id')}
    values = values or {}
    out = []
    for opt, cond, need, gate in _INERT_UNLESS:
        if gate is not None and not values.get(gate):
            continue
        if str(values.get(cond, defaults.get(cond)) or '') == need:
            continue                       # 조건이 맞다 — 이 값은 쓰인다
        if opt not in values:
            continue
        cur, dflt = values.get(opt), defaults.get(opt)
        try:
            same = float(cur) == float(dflt)
        except (TypeError, ValueError):
            same = str(cur or '') == str(dflt or '')
        if same:
            continue                       # 손댄 적 없는 값이다
        out.append((opt, cond, need))
    return out
