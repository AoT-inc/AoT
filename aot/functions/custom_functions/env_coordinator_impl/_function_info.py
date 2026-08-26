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
                'At night humidity climbs and dew forms, and an opening that '
                'looked useful at dusk can leave the crop wet until morning. '
                'With this on, vents and exhaust/intake fans park closed '
                'overnight and heating, cooling and dehumidifying carry the '
                'load instead. Heating and cooling are not stopped — only the '
                'vents are. Safety gates (wind, rain, heat, cold) still '
                'override this, and the vents also reopen on their own if the '
                'inside crosses the temperature or humidity limits you set, so '
                'a closed house cannot cook or drown. Off by default: some '
                'houses need night venting to dehumidify.'
            ),
        },
        {
            'id': 'night_vent_basis',
            'type': 'select',
            'default_value': 'sun',
            'required': False,
            'options_select': [
                ('sun',   lazy_gettext('Sunset to sunrise')),
                ('clock', lazy_gettext('Fixed clock times')),
            ],
            'name': lazy_gettext('Night Starts At'),
            'phrase': lazy_gettext(
                'Sunset/sunrise follows the season on its own and needs the '
                'facility coordinates to be set; if they are missing, vents are '
                'left alone rather than guessed at. Fixed times are steady all '
                'year and are the right choice for a house with supplementary '
                'lighting, where the crop day is not the solar day.'
            ),
        },
        {
            'id': 'night_vent_sunset_offset_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Close Before Sunset (min)'),
            'phrase': lazy_gettext(
                'How long before sunset the vents start parking, when the basis '
                'above is sunset/sunrise. Closing a little early lets the house '
                'hold the day\'s warmth instead of venting it away as the sun '
                'drops. Parking lifts at sunrise. Only positive values — a '
                'negative one would park after sunset, which is the delay this '
                'option exists to avoid.'
            ),
        },
        {
            'id': 'night_vent_start',
            'type': 'text',
            'default_value': '18:00',
            'required': False,
            'name': lazy_gettext('Night Start (HH:MM)'),
            'phrase': lazy_gettext(
                'When the basis above is fixed clock times. Crossing midnight '
                'is normal — 18:00 to 06:00 is one night.'
            ),
        },
        {
            'id': 'night_vent_end',
            'type': 'text',
            'default_value': '06:00',
            'required': False,
            'name': lazy_gettext('Night End (HH:MM)'),
            'phrase': lazy_gettext(
                'When the basis above is fixed clock times.'
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
                'When the outdoor air is already past your target, venting '
                'alone gets you there and running a heater or cooler at the '
                'same time pays for what the weather does for free. With this '
                'on, heating, cooling and misting park whenever three things '
                'hold at once: the outdoor reading is past the target with '
                'margin, every controlled variable is reachable that way, and '
                'the vents still have room to open further. If the vents are '
                'already wide open and the gap remains, heating and cooling '
                'keep working — this never leaves the greenhouse with nothing '
                'running. Safety gates and your temperature and humidity '
                'limits still override it. Leave this off if your vents are '
                'undersized or the outdoor reading is not trustworthy.'
            ),
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
                'Restrict this coordinator to one bay of the linked facility. '
                'Pick a bay of the linked facility. '
                'Only sensors and actuators placed inside that bay are used, and '
                'facility volume/area are scaled to that bay\'s share of the width. '
                'If the ID does not match any bay, this coordinator controls '
                'nothing and logs an error — it will not fall back to the whole '
                'facility. Leave empty to control the entire facility; when other '
                'coordinators already scope bays here, those bays are left to them. '
                'Create one coordinator per bay to control multiple bays '
                'independently.'
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

        # ── 습윤형 분무 일소 보호 (육묘 여부와 무관) ───────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('Misting Sunburn Protection'),
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
                'Tightens the sunburn protection above for newly emerged '
                'seedlings. Droplets left on a cotyledon under strong sun focus '
                'light onto the leaf and concentrate dissolved minerals as they '
                'evaporate, and the seedling has no cuticle yet to resist either. '
                'The lockout itself is always active for wetting-type nozzles — '
                'this adds a lower threshold on groundwater, shorter sprays with '
                'a longer drying interval, and an evening cut-off.'
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

#   (접힘?, 제목, [(소제목|None, [옵션 id …]) …])
_LAYOUT = [
    # ── 항상 보이는 것 — 이것만 채우면 돈다 ──────────────────────────────────
    (False, lazy_gettext('Facility'), [
        (None, ['geo_facility_id', 'bay_scope']),
    ]),
    (False, lazy_gettext('Basic'), [
        (None, ['update_period', 'sensor_max_age']),
    ]),
    # 하드 임계는 "목표" 가 아니라 **넘지 말아야 할 선**이다. 제목이 그것을
    # 말해야 유도 범위와 헷갈리지 않는다.
    (False, lazy_gettext('Limits Never to Cross'), [
        (None, ['temp_max', 'temp_min', 'humid_max', 'humid_min']),
    ]),
    (False, lazy_gettext('VPD'), [
        (None, ['tolerance_vpd']),
    ]),

    # ── 접어 두는 것 ─────────────────────────────────────────────────────────
    # 유도 범위는 하드 임계 **바로 다음**이다 — 둘이 어긋나면 목표가 조용히
    # 좁혀지므로, 하나를 고칠 때 다른 하나가 눈에 보여야 한다.
    (True, lazy_gettext('Guide Ranges (T / RH)'), [
        (None, ['guide_T_min', 'guide_T_max', 'guide_RH_min', 'guide_RH_max']),
    ]),
    (True, lazy_gettext('Ventilation Strategy'), [
        (None, ['vent_futility_gate', 'vent_first']),
        (lazy_gettext('Heating / Cooling Interlock'),
         ['hvac_interlock', 'hvac_interlock_signal', 'hvac_interlock_on_value']),
        (lazy_gettext('Night Vent Parking'),
         ['night_vent_park', 'night_vent_basis',
          'night_vent_sunset_offset_min', 'night_vent_start', 'night_vent_end']),
    ]),
    (True, lazy_gettext('Schedule and Time'), [
        (lazy_gettext('Growth Schedule'),
         ['schedule_end_time', 'schedule_week_offset']),
        (lazy_gettext('Time Control'),
         ['time_enable', 'time_start', 'time_end',
          'photo_method_id', 'photo_anchor']),
    ]),
    (True, lazy_gettext('Nursery'), [
        (None, ['nursery_mode', 'nursery_max_on_sec', 'nursery_min_off_sec',
                'nursery_water_source', 'use_wetting_fog_for_humidity']),
        (lazy_gettext('Misting Sunburn Protection'),
         ['nursery_solar_lockout', 'nursery_solar_release',
          'nursery_evening_fog', 'nursery_evening_cutoff_min']),
    ]),
    (True, lazy_gettext('Light and CO₂'), [
        (None, ['light_max', 'light_min', 'shade_transmittance',
                'priority_co2', 'tolerance_co2']),
    ]),
    (True, lazy_gettext('Actuation Rate'), [
        (None, ['actuation_profile', 'actuation_period_sec',
                'emergency_period_sec', 'emergency_deviation_mult',
                'emergency_rate_c_per_10min', 'gate_wind_threshold']),
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
    _MARKERS = ('collapse_start', 'collapse_end', 'header')
    real = [o for o in options if o.get('id') and o.get('type') not in _MARKERS]
    by_id = {o['id']: o for o in real}
    out, used = [], set()
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
            out.append({'type': 'collapse_start',
                        'id': 'grp_%s' % first_id, 'name': title})
        else:
            out.append({'type': 'header', 'name': title})
        first = True
        for subtitle, ids in blocks:
            if subtitle is not None:
                out.append({'type': 'header', 'name': subtitle})
            elif not first:
                out.append({'type': 'header', 'name': title})
            first = False
            for oid in ids:
                if oid in by_id and oid not in used:
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
