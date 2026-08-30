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
            'button_label': lazy_gettext('Execute'),
            'name': lazy_gettext('Reload Actuators'),
            'phrase': lazy_gettext(
                'Re-read the Actions table and rebuild actuator profiles.'
            ),
        },
        {
            'id': 'cmd_run_now',
            'type': 'button',
            'wait_for_return': False,
            'button_label': lazy_gettext('Execute'),
            'name': lazy_gettext('Run Now'),
            'phrase': lazy_gettext(
                'Execute one coordination cycle immediately using current sensor readings.'
            ),
        },
        {
            'id': 'cmd_emergency_stop',
            'type': 'button',
            'wait_for_return': True,
            'button_label': lazy_gettext('Stop'),
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
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Max Sensor Age (seconds)'),
            # ⚠ **기본값을 다시 숫자로 만들지 말 것.** 120 초였는데, 그보다
            #   느린 센서는 전부 만료로 걸려 그 축이 통째로 죽었다 — 기상청
            #   300초·OpenWeather 600초라 실외 데이터원은 사실상 전부다.
            #   육묘장3 은 이 기본값 그대로였고, 측창 둘이 24시간 내내
            #   '실외 값 없음' 으로 서 있었다(2026-08-28). 영양·쿠마모토가
            #   1200 인 것은 누군가 같은 일을 겪고 손으로 고쳤다는 뜻이다.
            # 0 = "안 정했다" 로 읽는다(`Input.max_age_s` 와 같은 판단).
            #   '제한 없음' 이 아니다 — 센서마다 자기 주기로 판정한다.
            'phrase': lazy_gettext(
                'Reject sensor readings older than this. Leave at 0 to let '
                'each sensor decide from its own update interval.'
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
            'advanced_only': True,
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
            'advanced_only': True,
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
        'advanced_only': True,
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Close Vents When Ventilation Cannot Help'),
            'phrase': lazy_gettext(
                'Opening helps only when the outdoor air is on the target side. When it is not, wider vents drag the reading further away.'
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
            'name': lazy_gettext('Close at Night'),
            'phrase': lazy_gettext(
                'Keep the vents closed overnight and let heating, cooling and drying carry the load.'
            ),
        },
        {
            'id': 'night_vent_basis',
        'advanced_only': True,
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
        'advanced_only': True,
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
        'advanced_only': True,
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
        'advanced_only': True,
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
        'advanced_only': True,
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Rest Heating and Cooling When Venting Can Reach the Target'),
            'phrase': lazy_gettext(
                'No point burning fuel for what an open vent already does.'
            ),
        },
        {
            'id': 'hvac_interlock',
            'advanced_only': True,
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Keep Vents Closed While Heating or Cooling Runs'),
            'phrase': lazy_gettext(
                'Venting against a running unit throws that heat or cold straight outside.'
            ),
        },
        {
            'id': 'hvac_interlock_signal',
        'advanced_only': True,
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
                'Only for units this coordinator does not switch itself — it already knows about the ones it commands. Not an indoor temperature: something that reports the unit running, such as a power reading or a relay state.'
            ),
        },
        {
            'id': 'hvac_interlock_on_value',
        'advanced_only': True,
            'depends_on': 'hvac_interlock',
            'type': 'float',
            'default_value': 0.5,
            'required': False,
            'name': lazy_gettext('Running Signal Threshold'),
            'phrase': lazy_gettext(
                'Read on the signal chosen above, in whatever unit that signal uses. For an on/off signal (0 or 1) leave it at 0.5.'
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
                'Control stops for good after this date. Leave blank to keep running.'
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
                'Outside this window the coordinator stops entirely — heating and cooling included. Safety limits still act.'
            ),
        },
        {
            'id': 'time_start',
            'depends_on': 'time_enable',
            'type': 'text',
            'default_value': '06:00',
            'required': False,
            'name': lazy_gettext('Start Time (HH:MM)'),
            'phrase': lazy_gettext(
                'When the coordinator starts working each day.'
            ),
        },
        {
            'id': 'time_end',
            'depends_on': 'time_enable',
            'type': 'text',
            'default_value': '20:00',
            'required': False,
            'name': lazy_gettext('End Time (HH:MM)'),
            'phrase': lazy_gettext(
                'When it stops. What each device does at that moment is set in its Action.'
            ),
        },
        {
            'id': 'photo_method_id',
            'depends_on': 'time_enable',
            'type': 'select_device',
            'default_value': '',
            'required': False,
            'options_select': ['Method'],
            'name': lazy_gettext('Photoperiod Method'),
            'phrase': lazy_gettext(
                'Sets the window above from a day-length curve instead of fixed times. '
                'Careful: a short day length means the coordinator runs for '
                'only those hours, so nothing is heated overnight.'
            ),
        },
        {
            'id': 'photo_anchor',
            'depends_on': 'time_enable',
            'type': 'text',
            'default_value': '12:00',
            'required': False,
            'name': lazy_gettext('Photoperiod Anchor (HH:MM)'),
            'phrase': lazy_gettext(
                'The window is centred on this time.'
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
            'advanced_only': True,
            'type': 'float',
            'default_value': 800.0,
            'required': False,
            'name': lazy_gettext('Max Light Threshold'),
            'phrase': lazy_gettext(
                'Close the shade screen above this light level. 0 = never shade. This is a shading choice only — how much light the crop can use comes from its program.'
            ),
        },
        {
            'id': 'light_min',
        'advanced_only': True,
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Min Light Threshold (Supplemental)'),
            'phrase': lazy_gettext(
                'Switch supplemental lighting on below this light level. '
                '0 = no supplemental lighting, which is most facilities.'
            ),
        },

        # ── CO₂ ───────────────────────────────────────────────────────────────
        {
            'type': 'header',
            'name': lazy_gettext('CO₂'),
        },
        {
            'id': 'priority_co2',
        'advanced_only': True,
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
            'name': lazy_gettext('Use Micro Sprinklers to Raise Humidity'),
            'phrase': lazy_gettext(
                'Use the micro sprinklers for humidity too. Turn off when they are your irrigation.'
            ),
        },

        # ── 습윤형 분무 일소 보호 (육묘 모드 전용) ─────────────────────────────
        # 두 필드는 `depends_on: nursery_mode` 라 육묘 모드를 꺼면 보이지 않는다.
        # 2026-08-25~08-30 사이에는 **화면만 그랬고 로직은 전원에게 적용**됐다 —
        # 화면이 "육묘 전용"이라 말하면서 동작은 아니었다. 되돌린 근거는
        # `safety_gates._eval_nursery_lock` 주석에 있다.
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
            'advanced_only': True,
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
        'advanced_only': True,
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
        'advanced_only': True,
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
        'advanced_only': True,
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
                'automatically. When more than one is growing, pick it from the summary under the linked facility above.'
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
        # 도메인은 환기가 맞지만 온당한 기본값이 있는 숫자다 — [고급] 에서만.
        'advanced_only': True,
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
        # ⚠ 뒤 둘은 **단계가 정하지 않는다.** 같은 축의 미세 조정이라 자리만
        #   여기이고(핵심의 [고급] 을 열면 바로 나온다), 단계를 눌러도 안
        #   바뀐다. `actuation_period_sec` 는 프로파일이 '직접 지정' 일 때만
        #   쓰이므로 그 옆이 아니면 찾을 수가 없다.
        'members': ['update_period', 'actuation_profile', 'tolerance_vpd',
                    'emergency_deviation_mult', 'emergency_rate_c_per_10min',
                    'actuation_period_sec', 'emergency_period_sec'],
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
    # ⚠ **"육묘장 모드" 를 이 축이 흡수했다** (2026-08-27 사용자 지적:
    #   *"육묘장 모드와 분무 조심도가 모두 있어야 해? 조심모드 켜면
    #   육묘장 모드인 것 같은데..."*). 맞다 — 코드가 스스로 그렇게 말한다:
    #   *"육묘 모드는 이 게이트를 켜는 스위치가 아니라 **더 조이는 축**"*
    #   (`safety_gates.py`). 켜는 스위치와 그 세기를 따로 물으면, 세기를
    #   정해 놓고 스위치를 안 켠 사람이 자기 설정이 도는 줄 안다.
    #
    # ⚠ **일소 잠금은 육묘 모드에서만 돈다** (2026-08-30 되돌림). 물방울이
    #   렌즈가 되는 물리 자체는 작물과 무관하지만, 이미 자란 개체에서는
    #   강일사가 곧 증산이 가장 심한 때라 그때 분무를 끊는 것이 오히려
    #   건조 스트레스를 만든다. 2026-08-25 에 이 잠금을 육묘 밖으로 꺼냈다가
    #   되돌렸다 — 그 사이 영양 육묘장에서 분무 허용 창이 하루 한 시간
    #   남짓으로 좁혀졌고 가습이 필요한 사이클 전부에서 요청이 버려졌다.
    #   육묘 모드를 끈 채 두상 살수를 쓰는 설치(딸기)는 모드를 켜서 보호를
    #   받는다 — 보호의 유무를 사람이 정한다.
    # ⚠ **토글 셋을 한 축으로 묶었다** (2026-08-27 사용자 지적: *"환기부터는
    #   여전히 예전 방식이야. 일일이 사용자가 옵션을 설정해야 함."*).
    #
    # 셋은 따로 생각할 정책이 아니라 **같은 질문의 세기**다 — "밖의 공기를
    # 얼마나 믿고 냉난방을 얼마나 아낄 것인가."
    #
    #   무익 판정   소용없는 환기를 안 한다      (창만 아낀다)
    #   환기 우선   환기로 되면 냉난방을 쉰다    (에너지를 아낀다)
    #   냉난방 연동 냉난방 중에는 창을 닫는다    (버리는 에너지를 막는다)
    #
    # 기본값(True/False/False)이 곧 "표준" 칸이라, 업그레이드로 동작이 바뀌지
    # 않는다.
    #
    # ⚠ **`hvac_interlock` 은 감지 신호가 없어도 작동한다.** 코디네이터가
    #   냉난방을 직접 명령하면 그 명령으로 판단한다(`_hvac_running` 경로 1).
    #   신호는 **손으로 켜는 기계** 전용이다 — 그래서 [고급] 에 있다.
    {
        'id': 'vent_economy',
        'name': lazy_gettext('Ventilation and HVAC Teamwork'),
        # ⚠ **"바깥 공기를 얼마나 믿을지" 로 쓰지 말 것** — 센서를 못 믿는다는
        #   뜻으로 읽힌다(2026-08-28 사용자 지적). 이 축은 신뢰가 아니라
        #   **둘이 서로를 방해하지 않게 하는 정도**다.
        # ⚠ **방향을 화면과 맞출 것.** "높일수록 에너지를 아낀다" 는 왼쪽이
        #   고성능인 지금 배치와 반대로 읽힌다. 단계 이름으로 말한다.
        'phrase': lazy_gettext(
            'Keeps venting and HVAC from working against each other. At '
            '[Energy saving] the HVAC rests when venting alone can reach the '
            'target, and the vents close while it runs. At [High performance] '
            'both act freely so the target is reached sooner.'
        ),
        'axis_low':  lazy_gettext('Reaches the target sooner'),
        'axis_high': lazy_gettext('Wastes less'),
        'members': ['vent_futility_gate', 'vent_first', 'hvac_interlock'],
        # ⚠ **속도로 이름 붙이지 말 것**(빠르게·보통·천천히). 바로 위 [제어 성향]
        #   이 이미 속도 축이다(느긋하게·표준·민감하게) — 한 화면에 속도 축이
        #   둘이면 무엇이 다른지 알 수 없다. 이 축은 **에너지**다.
        # ⚠ 왼쪽 끝 이름이 축 라벨과 맞아야 한다. 예전에는 가장 왼쪽이 '표준'
        #   인데 축은 "목표를 바짝 쫓음" 이라고 써 있어, 없는 선택지를 약속했다.
        'steps': [
            (lazy_gettext('High performance'), {
                'vent_futility_gate': True, 'vent_first': False,
                'hvac_interlock': False}),
            (lazy_gettext('Standard'), {
                'vent_futility_gate': True, 'vent_first': True,
                'hvac_interlock': False}),
            (lazy_gettext('Energy saving'), {
                'vent_futility_gate': True, 'vent_first': True,
                'hvac_interlock': True}),
        ],
    },
    {
        'id': 'misting_care',
        # ⚠ **id 는 그대로 둔다** — `_LAYOUT` 의 `@group:misting_care` 가 이
        #   이름으로 자리를 잡는다. 화면에 나가는 것은 `name` 뿐이다.
        'name': lazy_gettext('Misting Frequency'),
        # '조심도' → '세기' → **'빈도'** 로 두 번 고쳤다.
        #
        # ⚠ **'세기' 도 틀렸다.** 관수·분무 밸브는 거의 전부 on/off 제어라 PWM 이
        #   안 된다 — 물살을 줄일 방법이 없다(사용자 지적, 2026-08-28). 조절할
        #   수 있는 것은 **한 번에 몇 초 켜느냐**와 **얼마나 자주 켜느냐** 뿐이고,
        #   그것이 곧 빈도다. `nursery_max_on_sec` 의 설명이 이미 그렇게 적혀
        #   있었는데("regulated by how often it sprays, not by how long")
        #   그룹 이름만 어긋나 있었다.
        # 일소 방지는 육묘 모드에 함께 딸려 온다(2026-08-30 되돌림) — 옛
        # 이름('조심도')은 그 세기까지 이 옵션의 일인 것처럼 읽히게 했다.
        # ⚠ **짧게 유지할 것.** 설명이 길면 폰에서 한 화면을 통째로 먹는다
        #   (2026-08-28 사용자 지적). on/off 라는 사실은 옵션 이름('빈도')이
        #   이미 말하고, 자세한 것은 아래 두 세부 옵션의 설명이 맡는다.
        'phrase': lazy_gettext(
            'How often the misting runs — the run time and the gap until the '
            'next run.'
        ),
        'axis_low':  lazy_gettext('Drier'),
        'axis_high': lazy_gettext('Moister'),
        'members': ['nursery_mode',
                    'nursery_max_on_sec', 'nursery_min_off_sec'],
        # ⚠ 축 방향이 뒤집혔다(순함 → 셈). **기존 설치는 안전하다** — 단계는
        #   순서가 아니라 **값으로** 되짚는다(안 맞으면 '사용자 지정').
        'steps': [
            # 첫 칸은 **육묘 보호를 끄는 칸**이다. 펄스 두 값은 싣지 않는다 —
            # 실으면 "안 함" 을 골랐다가 되돌릴 때 그 값이 덮어써진다.
            # (그 두 값은 이제 `nursery_mode` 와 무관하게 늘 쓰이므로, 이 칸을
            #  골라도 직전에 고른 리듬은 그대로 유지된다.)
            (lazy_gettext('Not used'), {'nursery_mode': False}),
            # ⚠ **`Standard`·`Strong` 같은 흔한 낱말을 쓰지 말 것.** 카탈로그에
            #   이미 다른 문맥의 번역이 있어(표준·강함) 이 사다리만 어휘가
            #   어긋난다 — 실제로 `약하게 · 표준 · 강함 · 아주 강하게` 가 나왔다.
            #   한 사다리는 말투가 하나여야 읽힌다.
            # ⚠ **`nursery_mode` 가 서는 칸은 여기 하나뿐이다** (2026-08-30).
            #
            # 육묘 모드는 더 이상 독립 옵션이 아니다 — 이 축으로 접혔고
            # `advanced_only` 라 일반 화면에 안 보인다. 그래서 "육묘장이다"
            # 를 묻는 자리가 사라졌는데, 예전 배선은 **활성 네 칸 전부**에
            # True 를 심어 "분무를 조금이라도 쓰면 육묘" 가 돼 있었다.
            # 그 위에 일소 잠금·저녁 차단·지하수 임계 하향이 얹히니, 성체
            # 작물을 기르는 시설이 강일사마다 분무를 잃었다.
            #
            # 가장 드물고 짧게 주는 이 칸이 **사실상 육묘 설정**이다(사용자
            # 판단, 2026-08-30). 보통 이상은 이미 자란 개체를 기르는 쪽이라
            # 육묘 보호를 얹지 않는다.
            (lazy_gettext('Infrequent'), {
                'nursery_mode': True,
                'nursery_max_on_sec': 5.0, 'nursery_min_off_sec': 1200.0}),
            (lazy_gettext('Moderate'), {
                'nursery_mode': False,
                'nursery_max_on_sec': 10.0, 'nursery_min_off_sec': 900.0}),
            (lazy_gettext('Frequent'), {
                'nursery_mode': False,
                'nursery_max_on_sec': 20.0, 'nursery_min_off_sec': 600.0}),
            (lazy_gettext('Very frequent'), {
                'nursery_mode': False,
                'nursery_max_on_sec': 30.0, 'nursery_min_off_sec': 450.0}),
        ],
    },
]

_RANGE_BANDS = [
    {
        'id': 'temperature',
        'name': lazy_gettext('Temperature Range'),
        'phrase': lazy_gettext(
            'Aims to stay inside this range. Past a limit it stops whatever pushes the wrong way — too warm: heating off and the shade screen drawn; too cold: cooling off, vents and thermal curtain closed. It does not slam anything to full.'
        ),
        'hard_label': lazy_gettext('never past'),
        'unit': '°C', 'axis_min': 0.0, 'axis_max': 45.0, 'step': 0.5,
        'margin': 5.0,
        'guide_min': 'guide_T_min', 'guide_max': 'guide_T_max',
        'hard_min': 'temp_min', 'hard_max': 'temp_max',
    },
    # 일사가 셀수록 젖은 잎이 탄다. 두 값(해제·잠금)은 **한 구간의 양 끝**
    # 이지 따로 생각할 값이 아니다 — 사이에서 선형으로 줄어들고, 둘 사이를
    # 벌려 두는 이유는 구름이 지날 때 분무가 켜졌다 꺼졌다 하지 않게 하려는
    # 것뿐이다. 그래서 손잡이 둘인 구간으로 묻는다(사용자 지적: *"분무
    # 잠금/해제도 하나로 만들 수 있잖아. 밴드 슬라이더로 설정"*).
    #
    # ⚠ 하드 임계가 없다 — 파생할 것이 없으므로 `margin` 은 0 이다.
    {
        'id': 'misting_light',
        'name': lazy_gettext('Misting by Sunlight Level'),
        # 두 손잡이가 **해제**와 **잠금**인데 화면이 그것을 말하지 않았다 —
        # 숫자 둘만 보이니 무엇이 무엇인지 알 수 없다.
        # ⚠ **대상은 잎을 적시는 분무(미니스프링클러)뿐이다.** 안개형은 강한
        #   햇빛에도 돌아야 맞고, 실제로 `is_wetting_fogger` 가 그렇게 가른다
        #   — 화면이 그 사실을 말하지 않아 모든 분무에 걸리는 것처럼 보였다
        #   (2026-08-28 사용자 지적).
        'phrase': lazy_gettext(
            'Applies to leaf-wetting misting only — fog-type misting runs in '
            'strong sun too. Darker than the range it runs freely; brighter '
            'than the range it stops; inside the range it tapers off.'
        ),
        'unit': ' W/m\u00b2', 'axis_min': 0.0, 'axis_max': 800.0, 'step': 10.0,
        'margin': 0.0,
        'guide_min': 'nursery_solar_release',
        'guide_max': 'nursery_solar_lockout',
    },
    {
        'id': 'humidity',
        'name': lazy_gettext('Humidity Range'),
        'phrase': lazy_gettext(
            'Aims to stay inside this range. Past a limit it stops whatever pushes the wrong way — too damp: misting off; too dry: exhaust fans off. It does not slam anything to full.'
        ),
        'hard_label': lazy_gettext('never past'),
        'unit': '%', 'axis_min': 10.0, 'axis_max': 100.0, 'step': 1.0,
        'margin': 5.0,
        'guide_min': 'guide_RH_min', 'guide_max': 'guide_RH_max',
        'hard_min': 'humid_min', 'hard_max': 'humid_max',
    },
    # 빛도 한 구간이다 — 아래로 내려가면 보광, 위로 올라가면 차광.
    # ⚠ **0 은 "안 함" 이고, 두 끝에서 뜻이 반대다.** `light_min=0` 은 축의
    #   맨 아래라 자연스럽지만, `light_max=0` 은 "차광 안 함" 이라 축의 맨
    #   **위**에 놓여야 한다. 그래서 위쪽 끝에 그 표식이 따로 있다 —
    #   `off_at_max`. 없이 그리면 상한을 끝까지 올린 사람이 "항상 차광" 을
    #   설정한 줄 알고, 실제로는 그 값이 0(끔)으로 저장되지 않아 조용히
    #   다르게 돈다.
    {
        'id': 'light',
        'name': lazy_gettext('Shading and Supplemental Light'),
        # ⚠ **이것은 "이 안에 머물러라" 가 아니라 기준선 둘이다.** 이름이
        #   '광량 범위' 였을 때 사용자가 그렇게 읽었고, 벗어나면 무엇을 하는지
        #   화면 어디에도 없었다(*"기본값도 0~1200 인데 어떻게 한다는 건지
        #   나도 모르겠다"*). 0~1200 은 기본값이 아니라 **슬라이더 축의 끝**
        #   이라는 오해까지 겹쳤다.
        'phrase': lazy_gettext(
            'Darker than the range: the supplemental lights come on and the '
            'shade screen opens. Brighter than the range: the shade screen '
            'closes. Inside the range nothing happens. Either end can be '
            'turned off.'
        ),
        'unit': ' W/m\u00b2', 'axis_min': 0.0, 'axis_max': 1200.0,
        'step': 10.0, 'margin': 0.0,
        'off_at_min': True, 'off_at_max': True,
        'off_min_label': lazy_gettext('no supplemental light'),
        'off_max_label': lazy_gettext('no shading'),
        # 이 손잡이가 실제로 무엇을 움직이는가. 그 종류가 이 시설에 등록돼
        # 있지 않으면 화면이 그렇게 말한다 — 없으면 무엇을 넣어도 아무 일이
        # 안 일어나는데, 예전에는 그 칸이 똑같이 보였다.
        'requires_min': 'lighting',
        'requires_max': 'shade',
        'guide_min': 'light_min', 'guide_max': 'light_max',
    },
]

_RANGE_MEMBERS = {v for b in _RANGE_BANDS
                  for k, v in b.items()
                  if k in ('guide_min', 'guide_max', 'hard_min', 'hard_max')}

_GROUP_MEMBERS = {m for g in _SCALE_GROUPS for m in g['members']}

#   (접힘?, 제목, [(소제목|None, [옵션 id …]) …])
# ─────────────────────────────────────────────────────────────────────────────
# 화면의 도메인 묶음 → `env_control/types.py` 의 도메인
# ─────────────────────────────────────────────────────────────────────────────
# ⚠ **화면은 도메인을 정의하지 않는다. 따르기만 한다.** 정본은 그 파일의
#   `ACTUATOR_DOMAIN` 이고, 주석이 "여기가 정본이다 — 어휘를 두 벌 두면
#   갈라지고, 갈라지면 한쪽만 고쳐진 채로 굴러간다" 고 못박고 있다.
#
# 이 표가 있는 이유는 화면 제목이 **번역되기 때문**이다. 제목 문자열로는
# 어느 도메인인지 알 수 없으므로, 여기서 한 번 이어 두고 검사가 그것을
# 정본과 대조한다(`test_env_coordinator_layout.py`).
#
# 제목은 도메인 이름 그대로가 아니다 — `screen` 을 "빛과 차광" 으로 부르는
# 것은 `light_min` 이 보광등과 차광막을 함께 움직이기 때문이고, `aux` 를
# 통째로 내지 않고 "CO₂" 만 내는 것은 나머지(보광등·유동팬)에 이 화면이
# 물을 설정이 없기 때문이다. **그 어긋남을 표가 드러낸다.**
#
# ⚠ **`aux` 에는 묶음이 없다.** 이 화면이 CO₂ 주입기에 대해 묻는 것은 허용
#   오차 하나뿐이고, 그것은 "얼마나 바짝 쫓을 것인가" 라 **목표** 쪽에 있다.
#   보광등은 빛 구간이 함께 정하고, 유동팬에는 설정이 없다. 항목 하나를 위해
#   묶음을 만들면 껍데기가 내용보다 크다 — 그렇다고 이 표에 없는 도메인을
#   "빠뜨렸다" 고 읽으면 안 되므로 여기 적어 둔다.
_DOMAIN_GROUPS = {
    'Ventilation':                  'vent',
    'Heating, Cooling and Misting': 'hvac',
    'Light and Shading':            'screen',
}

_LAYOUT = [
    # ═══════════════════════════════════════════════════════════════════════
    # 축은 **도메인**이다 — 옵션 종류가 아니라 (2026-08-27 재구성)
    # ═══════════════════════════════════════════════════════════════════════
    # 사용자 지적: *"각 도메인을 제어하기 위해 사용자에게 설정을 확인하기 위한
    # 것이 이 설정의 목표 아니었나?"* 맞다. 그런데 화면은 **옵션 종류**로
    # 묶여 있었다(범위 / 전략 / 주기 / 광량과 CO₂ / 모델). 그래서 "환기를
    # 어떻게 쓸 것인가" 에 답하려면 세 묶음을 오가야 했다 — 무익 판정은
    # 전략에, 구동 프로파일은 성향 안에, 풍속 임계는 주기에 있었다.
    #
    # 도메인 어휘의 정본은 `env_control/types.py` 의 `ACTUATOR_DOMAIN` 이다.
    # 가르는 기준은 장치가 비슷한가가 아니라 **종착점이 같은가** 다:
    #
    #   vent    개구부·배기팬·흡기팬 — 실내를 실외 쪽으로만 민다
    #   hvac    난방기·냉방기·포그  — 외기와 무관하게 직접 넣고 뺀다
    #   screen  차광막·보온커튼      — 들고 나는 복사를 막는다
    #   aux     CO₂·보광등·유동팬    — 각자 자기 축, 겨룰 상대 없음
    #
    # ⚠ **여기서 도메인을 새로 정의하지 말 것.** 그 표를 두 벌 두면 갈라지고,
    #   갈라지면 한쪽만 고쳐진 채 굴러간다(그 파일 주석의 경고 그대로).
    #   화면이 그 표를 **따르기만** 한다.
    #
    # ⚠ `screen` 은 화면에서 **"빛"** 으로 묶는다. `light_min` 이 보광등과
    #   차광막을 **함께** 움직이므로(보광 시 차광막 강제 개방 —
    #   `_cycle_mixin.apply_light_threshold_overrides`) 둘을 갈라 두면 한쪽만
    #   고친 사람이 다른 쪽이 함께 움직인 것을 이해할 수 없다.

    # ⚠ 상태 한 줄은 **여기**다 — 시설을 고른 그 자리에서 확인한다
    #   (2026-08-27 사용자 지적: *"시설을 연동하면 연동한 시설 정보가 그 아래에
    #   나오는게 더 자연스러워. 설정하고 그 위치에서 확인."*).
    (False, lazy_gettext('Facility Settings'), [
        (None, ['geo_facility_id', 'bay_scope', '@status']),
    ]),

    # ⚠ **접지 않고, 시설 바로 뒤다** (2026-08-27 사용자 지적: *"옵션이 달랑
    #   하나인데 접어야 해? … 자주 사용하는 건 아닌데, 전체 의미를 봤을 때
    #   특정 시간대에 시스템을 중지시키는 상당한 위력의 옵션임"*).
    #
    #   맞다. 창 밖 시간에는 **난방·냉방을 포함해 제어가 통째로 멈춘다**
    #   (`_run_cycle` 의 시간창 게이트). 접어 두면 "안 쓰는 사람에게 안 보인다"
    #   는 이득보다, **켜 놓고 잊은 사람이 왜 밤새 난방이 안 됐는지 모르는**
    #   손해가 크다. 자리는 빈도가 아니라 **결과의 크기**로 정한다.
    #
    # ⚠ 이름도 "시간 제어" 가 아니다 — 그렇게 부르면 시간대별로 다르게
    #   제어한다는 말로 읽히는데, 실제로는 **켜고 끄는 스위치**다.
    #
    # ⚠ 보이는 것은 토글 하나뿐이다 — 나머지 넷은 `depends_on` 이라 켜야 나온다.
    #   `schedule_end_time` 은 여기 없다: 날짜(제어를 영영 멈추는 날)라 시각과
    #   섞이면 묶음 이름이 무엇이든 애매해진다.
    (False, lazy_gettext('Working Hours'), [
        (None, ['time_enable', 'time_start', 'time_end',
                'photo_method_id', 'photo_anchor']),
    ]),

    # ── 목표 ─────────────────────────────────────────────────────────────
    # ⚠ **온·습도는 이 함수의 목표가 아니다.** 목표는 광합성이고 1차 제어
    #   변수는 VPD 다(`FUNCTION_INFORMATION['message']`). 온·습도는 VPD 를
    #   풀어낼 범위이자 넘지 말아야 할 선이다 — `situation._decompose_vpd`
    #   가 VPD 를 쓸 수 있을 때 둘을 `_..._constraint` 로 강등한다.
    #   그래서 이름이 "재배 온도" 가 아니라 **"온도 범위"** 다(2026-08-27
    #   사용자 지적: *"재배 범위가 맞은 어휘인지 모르겠음"*).
    #
    # 손잡이는 둘(권장 하한·상한)이고 넘으면 안 되는 선은 ∓여유로 따라온다.
    # ⚠ 그래서 **하드가 유도보다 좁을 수 없다.** "12~32 에서 기르되 30 은
    #   넘기지 마라" 는 표현할 수 없고, 그것은 의도한 대가다 — 그 설정이
    #   난방기와 냉방기를 동시에 100% 로 맞서게 한 원인이었다
    #   (`clamp_guide_range_to_hard_limits` 주석의 温室環境制御 실측).
    (False, lazy_gettext('Target and Temperament'), [
        (None, ['@range:temperature', '@range:humidity',
                'tolerance_co2', '@group:responsiveness']),
    ]),

    # ── 도메인 1: 환기 (vent) ─────────────────────────────────────────────
    # ⚠ **토글만 보이고 하위 설정은 켜야 나온다**(`depends_on`). 야간 닫기를
    #   쓰지 않는 사람에게 기준·오프셋·시각 4개가 늘 보이면, 자기가 안 쓰는
    #   것까지 정해야 하는 줄 안다. 하위 설정을 다른 곳으로 빼지 않는다 —
    #   토글 바로 아래가 그 값의 자리다(설계문서 §3-2).
    #
    # ⚠ `hvac_interlock` 은 이름이 hvac 지만 **움직이는 것은 창**이다
    #   (냉·난방이 도는 동안 창을 닫아 둔다). 도메인은 이름이 아니라
    #   **무엇이 움직이는가** 로 가른다.
    (False, lazy_gettext('Ventilation'), [
        (None, ['@group:vent_economy', 'hvac_interlock_signal',
                'hvac_interlock_on_value']),
        (None, ['night_vent_park', 'night_vent_basis',
                'night_vent_sunset_offset_min', 'night_vent_start',
                'night_vent_end']),
        (None, ['gate_wind_threshold']),
    ]),

    # ── 도메인 2: 냉난방·가습 (hvac) ──────────────────────────────────────
    (False, lazy_gettext('Heating, Cooling and Misting'), [
        (None, ['@group:misting_care', '@range:misting_light',
                'nursery_water_source', 'nursery_evening_fog',
                'nursery_evening_cutoff_min',
                'use_wetting_fog_for_humidity']),
    ]),

    # ── 도메인 3: 빛 (screen + 보광) ──────────────────────────────────────
    # ⚠ **접지 않는다.** 항목이 둘뿐인데 접으면 여는 수고가 내용보다 크다
    #   (2026-08-27 사용자 지적: *"이거 옵션도 몇 개 안되는데 아코디언 해야
    #   되나?"*).
    # ⚠ `shade_transmittance` 는 **시설로 갔다**(D9, 2026-08-27). 차광막은
    #   시설의 물건이고 그 성질은 시설이 안다 — 자리는 시설 편집기의
    #   [차광 커튼] 아래이고, 저장은 `envelope.curtain.shade.transmittance` 다.
    #   함수는 `_facility_shade_transmittance()` 로 읽는다.
    #   같은 값을 시설의 냉방부하 계산이 **0.50 으로 하드코딩**하고 있었으므로,
    #   옮기면서 그 상수도 함께 사라졌다.
    (False, lazy_gettext('Light and Shading'), [
        (None, ['@range:light']),
    ]),

    # ── 도메인 4: CO₂ (aux) ───────────────────────────────────────────────
    # ⚠ **묶음을 없앴다.** 남는 것이 허용 오차 하나인데 접힘 제목까지 붙으면
    #   내용보다 껍데기가 크다. 허용 오차는 "얼마나 바짝 쫓을 것인가" 라
    #   목표 쪽으로 갔고(사용자 지적: *"CO2 사용하는 시설이면 목표에 있어야
    #   함"*), 처리 순서 가중치는 VPD 쪽 짝과 같은 자리로 갔다 — 하나만 따로
    #   보이면 *"CO₂ 에만 중요도가 있다는 게 이상함"* 이 된다. 맞는 지적이고,
    #   답은 **둘 다 [고급]** 이다: 1.2 대 0.8 은 재배자가 판단할 값이 아니다.

    # ── 도메인을 가리지 않는 것 ───────────────────────────────────────────
    # 아래는 특정 장치가 아니라 **판단 방식**에 걸린다. 도메인으로 나눌 수
    # 없으므로 나누지 않는다 — 억지로 배정하면 그 도메인만의 설정인 줄 안다.
    # ⚠ **"감지와 주기" 묶음을 없앴다.** 구동 주기 둘은 제어 성향이 정하는
    #   축이라 그 아래로 갔고, 남은 `sensor_max_age` 하나를 위해 접힘 제목을
    #   두면 껍데기가 내용보다 크다.
    # ⚠ **이 묶음은 엔지니어용이다** (2026-08-27 사용자 지적: *"모델과 보정
    #   옵션들은 엔지니어용 고급 옵션임. 그룹 자체가 '고급 설정' 이 맞아
    #   보임"*). 효과 모델·RLS 보정·능동 프로빙·예보 선행은 재배자가 판단할
    #   값이 아니라 이 함수를 시험하는 사람이 만지는 값이다. 이름이 그것을
    #   말하면 나머지 사람이 열어 보고 지나갈 수 있다.
    #
    # `schedule_end_time` 도 여기 있다 — 자주 쓰는 값이 아니고, 임박하면
    # 화면 위 상태 줄이 알아서 말한다.
    (True, lazy_gettext('Advanced Settings'), [
        (None, ['schedule_end_time', 'sensor_max_age',
                'photosynth_mode_enabled', 'source_plot_id', 'vpd_weight_T',
                'priority_vpd', 'priority_co2', 'cumulative_tracker_enabled']),
        (lazy_gettext('Effect Calibration'),
         ['effect_engine', 'calibration_enabled',
          'enable_active_probing', 'probe_interval_sec']),
        (lazy_gettext('Forecast Feedforward'),
         ['forecast_feedforward_enabled', 'forecast_lookahead_h']),
    ]),
    # ⚠ **"진단" 묶음을 없앴다** (2026-08-27). 안에 있던 `debug_logging` 은
    #   화면 위쪽 [고급 설정] 의 `log_level_debug` 와 **같은 스위치가 둘**인
    #   상태였다 — 게다가 `debug_logging` 이 감싸던 것은 거의 전부
    #   `logger.debug(...)` 라, 프레임워크 쪽을 켜지 않으면 **혼자서는 아무
    #   것도 출력하지 않았다**(기본 로거 레벨이 ERROR 다). 이제 프레임워크
    #   스위치 하나가 둘 다 한다.
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
                if oid == '@status':
                    # ⚠ **자리는 배치가 정한다.** 예전에는 무조건 맨 위였다 —
                    #   설정을 시작하기 전에 열 줄을 읽어야 했고, 정작 시설을
                    #   고르는 칸은 그 아래 있었다. 지금은 [연동 시설] 바로
                    #   뒤다: 고르고, 그 자리에서 확인한다.
                    out.append({'type': 'env_status'})
                    continue
                if oid.startswith('@range:'):
                    rid = oid.split(':', 1)[1]
                    for bnd in _RANGE_BANDS:
                        if bnd['id'] == rid:
                            item = dict(bnd)
                            item['type'] = 'range_band'
                            # 손잡이의 읽어 주는 이름(aria)은 **그 옵션의
                            # 이름**이다. 여기서 잇지 않으면 화면 낭독기가
                            # "손잡이" 라고만 읽어, 둘 중 어느 쪽인지 알 수
                            # 없다 — 눈으로 보는 사람에게는 안 보이는 결함이다.
                            for _k in ('guide_min', 'guide_max'):
                                _o = by_id.get(bnd.get(_k))
                                if _o:
                                    item['name_' + _k] = _o.get('name')
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
