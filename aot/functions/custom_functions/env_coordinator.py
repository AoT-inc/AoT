# coding=utf-8
"""
env_coordinator.py — Integrated Facility Environment Control Function (L1+L2+L3).

Goal: photosynthesis optimisation.
Primary control: VPD → decomposes to T/RH adjustments.
Secondary: Light (shade / supplemental), CO₂.
Constraints: Temperature and Humidity min/max bounds (prevent VPD bypass).
Safety gates: Wind, Time window.

Actuators are registered via Actions (add env_actuator actions as needed).
On each initialisation / reload the Function queries the Actions table and
builds ActuatorProfiles.

Reference: docs/dev/integrated_env_control_design.md §8, §11, §12, §13
"""

import time

from aot.aot_client import DaemonControl
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.utils.database import db_retrieve_table_daemon

from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.ext_context_fallback import ExtContextCache
from aot.functions.utils.env_control.safety_gates import (
    PreGateConfig, SafetyPreGate, SafetyPostGate,
)
from aot.functions.utils.env_control.situation import TrendState

from aot.functions.custom_functions.env_coordinator_impl._function_info import (
    FUNCTION_INFORMATION,
)
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
    ProfileLoaderMixin,
)
from aot.functions.custom_functions.env_coordinator_impl._runtime_state_mixin import (
    RuntimeStateMixin,
)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin,
)
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin,
)


def execute_at_modification(
        messages,
        mod_controller,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """저장하는 그 자리에서 **유도 범위가 하드 임계 밖인지** 알린다.

    유도 범위(`guide_T_min/max`)와 하드 임계(`temp_min/max`)는 서로 다른 섹션에
    있는 두 설정이라 관계가 화면에 안 보인다. 출하 기본값끼리는 모순이 없지만
    (유도 12~32 · 하드 5~35), 사용자가 하드 임계만 좁히면(예: 15~30) 유도가
    임계 **밖으로** 나간다. 그때 코디네이터는 매 사이클 유도 범위를 조용히
    좁혀 돌고, 사용자가 그 사실을 알 수 있는 곳은 **데몬 로그뿐**이었다
    (2026-08-26: 두 시설 모두 그 상태였다).

    ⚠ **판정을 여기서 다시 쓰지 말 것.** 같은 규칙이 두 벌이 되면 갈라지고,
      갈라지면 화면과 실제 동작이 다른 말을 한다 — 이 도메인이 이미 크게 데인
      실패다. `clamp_guide_range_to_hard_limits()` 하나를 부른다.

    ⚠ **막지 않고 알리기만 한다.** 유도 범위가 넓은 것 자체는 유효한 설정이고
      (코디네이터가 좁혀서 정상 동작한다), 저장을 거부하면 하드 임계를 나중에
      넓히려는 정상 작업까지 순서 때문에 막힌다.
    """
    from flask_babel import gettext

    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
        clamp_guide_range_to_hard_limits,
    )

    o = custom_options_dict_postsave or {}
    was = custom_options_dict_presave or {}

    def _f(key, fallback):
        try:
            v = o.get(key)
            return float(fallback if v in (None, '') else v)
        except (TypeError, ValueError):
            return float(fallback)

    def _touched(*keys):
        """이번 저장에서 이 값들 중 하나라도 실제로 바뀌었나.

        ⚠ **이 검사가 없으면 저장할 때마다 뜬다.** 조건(유도가 임계 밖)은 한
          번 만들어지면 계속 참이므로, 야간 파킹 토글 하나를 켜도 온도 경고가
          같이 나온다 — 무관한 행동에 붙은 경고는 "이것 때문에 안 되나" 로
          읽힌다(2026-08-26 실제로 그렇게 읽혔다). 기존 경고들
          (`nursery_evening_fog` 계열)은 자기 설정을 건드릴 때만 뜬다.

        ⚠ 값 비교는 **숫자로** 한다 — 폼에서 온 postsave 는 문자열일 수 있어
          `'30.0' != 30.0` 으로 항상 "바뀜" 이 된다(= 검사가 무력해진다).
        """
        for k in keys:
            a, b = was.get(k), o.get(k)
            try:
                if float(a) != float(b):
                    return True
            except (TypeError, ValueError):
                if a != b:
                    return True
        return False

    # 처음 저장(presave 가 비어 있음)은 "안 바뀌었다" 가 아니라 "비교할 것이
    # 없다" 이므로 알린다 — 새로 만든 설정이 이미 어긋나 있으면 그때 말해야 한다.
    _fresh = not was

    try:
        guide = (_f('guide_T_min', 12.0), _f('guide_T_max', 32.0),
                 _f('guide_RH_min', 40.0), _f('guide_RH_max', 85.0))
        eff, _changed = clamp_guide_range_to_hard_limits(
            guide,
            temp_min=o.get('temp_min'), temp_max=o.get('temp_max'),
            humid_min=o.get('humid_min'), humid_max=o.get('humid_max'))
        # ⚠ **`changed` 의 문자열을 화면에 그대로 쓰지 말 것.** 그것은
        #   `'T상한→30.0'` 처럼 한국어가 박힌 로그용 조각이라, 일본어 화면에
        #   일본어 문장과 한국어가 섞여 나온다. 여기서는 클램프의 **결과**
        #   (eff)와 입력을 비교해 축을 가려내고, 문장은 번역 가능한 msgid
        #   하나로 만든다 — 판정을 다시 하는 것이 아니라 이미 나온 답을 읽는
        #   것이므로 정본은 여전히 하나다.
        for i_lo, i_hi, what, unit, lo_key, hi_key, g_lo, g_hi in (
                (0, 1, gettext('temperature'), '°C', 'temp_min', 'temp_max',
                 'guide_T_min', 'guide_T_max'),
                (2, 3, gettext('humidity'), '%', 'humid_min', 'humid_max',
                 'guide_RH_min', 'guide_RH_max')):
            if guide[i_lo] == eff[i_lo] and guide[i_hi] == eff[i_hi]:
                continue          # 이 축은 안 좁혀졌다
            # 그 축의 네 값 중 하나라도 이번에 손댔을 때만 말한다.
            if not (_fresh or _touched(lo_key, hi_key, g_lo, g_hi)):
                continue
            fmt = (lambda lo, hi: '%g~%g%s' % (lo, hi, unit))
            messages['warning'].append(str(gettext(
                'The guide range for %(what)s (%(guide)s) lies outside your '
                'hard limits (%(hard)s), so targets are only built inside '
                '%(effective)s. Widen the hard limits or narrow the guide '
                'range so the two agree.',
                what=what,
                guide=fmt(guide[i_lo], guide[i_hi]),
                hard=fmt(_f(lo_key, guide[i_lo]), _f(hi_key, guide[i_hi])),
                effective=fmt(eff[i_lo], eff[i_hi]))))
    except Exception:
        pass      # 알림 하나 때문에 저장을 실패시키지 않는다

    # ── 입력했지만 안 쓰이는 값 ──────────────────────────────────────────────
    # 조건이 맞지 않아 조용히 버려지는 값을 그 자리에서 말한다. 여기서 걸러야
    # 그 상태가 애초에 안 생긴다 — 이미 그런 설치는 데몬이 기동 때 한 번 알린다.
    try:
        from aot.functions.custom_functions.env_coordinator_impl._function_info \
            import inert_options
        # ⚠ 바깥 `o`(저장값 dict)를 가리지 않게 이름을 나눈다. 파이썬3 의
        #   컴프리헨션은 자기 스코프라 실제로 새지는 않지만, 읽는 사람이
        #   그것을 매번 확인해야 한다 — 이 레포가 같은 모양으로 데인 적이 있다.
        names = {_opt['id']: _opt.get('name')
                 for _opt in FUNCTION_INFORMATION['custom_options']
                 if _opt.get('id')}
        for opt, cond, need in inert_options(o):
            # ⚠ msgid 에 큰따옴표를 넣지 말 것 — `.po` 의 문자열 구분자라
            #   이스케이프 없이 넣으면 그 카탈로그가 깨진다(2026-08-27 실측).
            messages['warning'].append(str(gettext(
                'The value you set for %(opt)s is not being used: it applies '
                'only when %(cond)s is set to the matching option. Change that '
                'first, or this value has no effect.',
                opt=str(names.get(opt, opt)), cond=str(names.get(cond, cond)))))
    except Exception:
        pass

    return (
        messages,
        mod_controller,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave,
        False,
    )


FUNCTION_INFORMATION['execute_at_modification'] = execute_at_modification


# 작물 프리셋 속성 → 함수 옵션 매핑.
#   (preset_attr, option_id, sp_type_attr)
# sp_type_attr 이 있고 그 옵션이 'method' 이면 자동/강제 적용 모두 건너뛴다(메서드 우선).


# ─────────────────────────────────────────────────────────────────────────────
class CustomModule(
    AbstractFunction,
    ProfileLoaderMixin,
    RuntimeStateMixin,
    CycleMixin,
    HelpersMixin,
):
    """Integrated facility environment control — L1+L2+L3 single Function."""

    # ⚠ **여기 있는 이름은 옵션 스키마(`_function_info.py`)에 있어야 한다.**
    #
    # `setup_custom_options_json` 은 **스키마를 순회**하지 저장된 JSON 키를
    # 순회하지 않는다. 그래서 스키마에 없는 이름은 아무것도 설정하지 않고
    # 영원히 None 인데, 선언은 남아 있어 **읽는 사람에게는 설정처럼 보인다.**
    #
    # 2026-08-26 에 그 함정을 실제로 밟았다. `sensor_T_int`·`sensor_RH_int`·
    # `sensor_vpd`·`sensor_light`·`sensor_CO2_int`·`sensor_wind`·
    # `sensor_wind_dir` 7개가 스키마 없이 선언만 남아 있었고, DB 의
    # `custom_options` 에도 옛 값(OpenWeather 를 가리키는)이 남아 있었다.
    # 화면에 나오지도, 읽히지도 않는 값인데 그것을 보고 "코디네이터가 실내
    # 센서로 기상 API 를 쓰고 있다" 고 오진했다. 실제 실내값은 시설 바인딩
    # (`_collect_internal` → `sensors_resolved`)에서 정상적으로 온다.
    #
    # 회귀는 `aot/tests/test_env_coordinator_dead_options.py` 가 고정한다 —
    # 스키마에 없고 코드도 안 읽는 이름을 여기 새로 만들면 그때 깨진다.
    def __init__(self, function: CustomController, testing: bool = False) -> None:
        super().__init__(function, testing=testing, name=__name__)

        self.control = DaemonControl()
        self.timer_loop: float = 0.0

        # Basic
        self.update_period  = None
        self.sensor_max_age = None

        # Growth Schedule
        self.schedule_end_time     = None
        self.schedule_week_offset  = None
        self._schedule_ended_logged = False

        # Facility link (optional)
        self.geo_facility_id           = None
        self.geo_facility_id_device_id = None
        # Bay(구역) scope — 빈 값이면 시설 전체 (현행 동작)
        self.bay_scope                 = None

        # Time Control
        self.time_enable = None
        self.time_start  = None
        self.time_end    = None

        # Night Vent Parking — 시간창(위)과 **다른 축**이다. 시간창은 제어를
        # 통째로 멈추고, 이것은 개구부만 닫는다(냉난방·제습은 계속 돈다).
        self.night_vent_park             = None
        self.night_vent_basis            = None
        self.night_vent_sunset_offset_min = None
        self.night_vent_start            = None
        self.night_vent_end              = None

        # Photoperiod Method
        self.photo_method_id_device_id = None
        self.photo_anchor              = None
        self._photo_method_handler     = None
        self._photo_loaded_method_id   = None

        # VPD
        self.priority_vpd            = None
        self.tolerance_vpd           = None

        # Light
        self.light_max    = None
        self.light_min    = None

        # CO₂
        self.priority_co2            = None
        self.tolerance_co2           = None

        # CO₂ Method runtime state
        self._co2_method_handler    = None
        self._co2_last_sp: float    = None
        self._co2_loaded_method_id  = None

        # Temperature (constraints)
        self.temp_max     = None
        self.temp_min     = None

        # Humidity (constraints)
        self.humid_max     = None
        self.humid_min     = None
        # 관수 겸용 분무기를 환경 제어에서 빼는 스위치 (기본 True = 종전 동작).
        self.use_wetting_fog_for_humidity = None

        # Nursery (seedling protection) — 2026-07-31 aot-005 일소 사건 대응
        self.nursery_mode           = None
        self.nursery_solar_lockout  = None
        self.nursery_solar_release  = None
        self.nursery_max_on_sec     = None
        self.nursery_min_off_sec    = None
        self.nursery_water_source   = None
        self.nursery_evening_fog        = None
        self.nursery_evening_cutoff_min = None

        # Photosynthesis Model
        self.photosynth_mode_enabled = None
        self._priority_ewa_state: dict = {}   # P5-4: {var: ewa_priority}

        # Cumulative Goal Tracker (P5-5)
        self.cumulative_tracker_enabled = None
        self._daily_acc                 = None  # DailyAccumulator (lazy init)

        # VPD Decomposition
        self.vpd_weight_T = None

        # Guide Ranges (T / RH)
        self.guide_T_min  = None
        self.guide_T_max  = None
        self.guide_RH_min = None
        self.guide_RH_max = None

        # Wind
        self.gate_wind_threshold = None

        # Forecast Feedforward (P3-4)
        self.forecast_feedforward_enabled = None
        self.forecast_lookahead_h         = None
        self._last_ff_signal              = None   # FeedforwardSignal (last cycle)

        # 냉·난방 연동 — 가동 중 개구부 잠금. 수동 조작 장치를 위해 감지 신호를
        # 따로 받는다(_helpers_mixin 상단 주석 참조). select_measurement 는
        # 프레임워크가 <id>_device_id / <id>_measurement_id 로 풀어 넣는다.
        self.vent_first                                  = None
        self.hvac_interlock                              = None
        self.hvac_interlock_signal_device_id             = None
        self.hvac_interlock_signal_measurement_id        = None
        self.hvac_interlock_on_value                     = None

        # Diagnostics — gates per-cycle INFO/DEBUG noise
        self.debug_logging                = None

        # Internal state
        self._vpd_method_handler = None
        self._vpd_method_start   = None
        self._vpd_last_sp        = None

        self._coord_state  = CoordinatorState()
        self._trend_state  = TrendState()
        self._profiles     = []
        # 구동주기: setpoint 변경 직후 1회 개구부 정상 구동주기를 우회(즉시 반영)하는
        # 플래그. cmd_reload/cmd_run_now 가 설정, CycleMixin._classify_emergency 가 소비.
        self._force_immediate = False
        # 긴급정지 후 조율기가 다시 명령을 내지 않는 보류 종료 시각(epoch).
        # timer_loop 만으로 지연을 표현하면 cmd_run_now 가 그것을 0 으로 되돌려
        # 보류가 통째로 우회된다 — 긴급정지가 액추에이터를 안전값으로 보낸 직후
        # 조율기가 즉시 재개해 다시 움직이는 셈이다. 보류를 별도 상태로 두고
        # loop() 와 cmd_run_now 양쪽에서 지킨다.
        self._emergency_hold_until = 0.0
        self._emergency_now    = False
        self._emergency_reason = ''
        self._unattainable_state: dict = {}   # P5-3: {var: 연속 초과 사이클 수}
        # 하드 임계 위반 래치(히스테리시스). 사이클마다 WARN 이 도배되지 않도록
        # 상태 전이 때만 로그를 남기는 데 쓴다. _run_cycle 안에서 lazy 하게
        # 만들면 그 상태를 먼저 읽는 경로가 생겼을 때 AttributeError 가 난다.
        self._constraint_breach_state: dict = {
            'T_max': False, 'T_min': False, 'RH_max': False, 'RH_min': False,
            # 습윤형 분무 습도 상한 래치 — 목표가 사이클마다 달라질 수 있어
            # (프로그램·VPD 분해) 정적 임계와 달리 assess 뒤에 판정한다.
            'fog_RH': False,
        }
        self._light_breach_state: dict = {'max': False, 'min': False}
        self._groups: list = []
        self._channel_map  = {}
        self._actuator_idx = {}
        self._pre_gate: SafetyPreGate   = None
        self._post_gate: SafetyPostGate = SafetyPostGate()
        self._last_cycle_ts: float      = 0.0
        self._ext_cache = ExtContextCache()
        self._cached_tz = self._CACHED_TZ_SENTINEL  # initialize()에서 1회 결정, 이후 재사용

        if not testing:
            custom_function = db_retrieve_table_daemon(
                CustomController, unique_id=self.unique_id)
            self.setup_custom_options(
                FUNCTION_INFORMATION['custom_options'], custom_function)
            self.try_initialize()

    # ─────────────────────────────────────────────────────────────────────────
    def initialize(self) -> None:
        # 육묘장 모드: 지하수처럼 경도·철분이 높고 수온이 낮은 원수를 쓰면
        # 물방울 렌즈 집광 외에 염류 잔류·저온 충격까지 겹쳐 피해가 커진다.
        # 그래서 원수가 지하수면 잠금 임계를 자동으로 더 보수적으로 내린다.
        _lockout = float(self.nursery_solar_lockout or 250.0)
        _release = float(self.nursery_solar_release or 150.0)
        # 일소 잠금 자체는 습윤형 분무기가 있으면 늘 선다(육묘 모드 무관).
        # 지하수 원수의 추가 하향은 **육묘 모드에서만** 적용한다 — 근거가
        # 어린 모종(염류 잔류·저온 충격)이라 성체 작물까지 150 W/m² 로 묶으면
        # 흐린 아침부터 분무가 막힌다.
        if (bool(self.nursery_mode)
                and (self.nursery_water_source or 'groundwater') == 'groundwater'):
            _lockout = min(_lockout, 150.0)
            _release = min(_release, 100.0)
        cfg = PreGateConfig(
            wind_threshold=self.gate_wind_threshold or 12.0,
            rain_threshold=0.5,
            heat_ext_threshold=45.0,
            cold_ext_threshold=-5.0,
            nursery_mode=bool(self.nursery_mode),
            nursery_solar_lockout=_lockout,
            nursery_solar_release=_release,
            nursery_evening_fog=(True if self.nursery_evening_fog is None
                                 else bool(self.nursery_evening_fog)),
        )
        self._pre_gate = SafetyPreGate(cfg)
        # 감쇠 구간(_cycle_mixin.apply_nursery_fog_derate)도 같은 값을 봐야
        # 하드 잠금과 감쇠가 어긋나지 않는다.
        self.nursery_solar_lockout = _lockout
        self.nursery_solar_release = _release
        self._normalize_select_device_options()
        # Load persisted state FIRST so CalibrationRegistry is restored from DB.
        # _reload_profiles() then merges pending commissioning anchors on top of
        # the restored registry — rather than overwriting it.
        self._load_runtime_state()
        self._reload_profiles()

        # 시간대: 장치 위치 좌표 기반으로 1회 결정 후 캐시
        self._cached_tz = self._get_facility_tz()
        if self._cached_tz:
            self.logger.info('EnvCoordinator timezone: %s', self._cached_tz)
        else:
            self.logger.warning(
                'EnvCoordinator: no device location coordinates — '
                'timezone cannot be determined for Growth Schedule date entry. '
                'Set location coordinates on the device or link a GeoFacility.')

        self.logger.info(
            'EnvCoordinator initialised — %d actuator(s), period=%.0fs',
            len(self._profiles), self.update_period or 60)

    # ─────────────────────────────────────────────────────────────────────────
    def stop_function(self) -> None:
        """비활성화 시 각 액추에이터를 end_behavior 설정에 따라 복귀시킨다.

        FunctionController.run_finally() → stop_function() 순서로 호출된다.
        output_off() 는 Pyro5 RPC → Output 컨트롤러(독립 스레드)에 즉시 전달된다.
        """
        self._apply_end_behaviors()
        super().stop_function()

    # ─────────────────────────────────────────────────────────────────────────
    def cmd_reload(self, args_dict: dict) -> str:
        """실행 중 custom_options 변경(예: AI set_vpd_target)을 다음 사이클에 반영.

        setup_custom_options() 를 재호출해 target_vpd 등 정적 옵션 속성을 DB 에서
        다시 읽는다. _load_runtime_state() (PI 적분·캘리브레이션 상태)는 여기서
        재실행하지 않으므로 런타임 상태는 보존된다.
        """
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)
        self._reload_profiles()
        self._cached_tz = self._CACHED_TZ_SENTINEL  # 위치 변경 시 tz 재결정
        # setpoint(목표값) 등이 바뀌었을 수 있으므로 다음 사이클은 개구부 정상
        # 구동주기를 우회해 즉시 반영한다 (예: AI set_vpd_target).
        self._force_immediate = True
        return f'Reloaded — {len(self._profiles)} actuator(s)'

    def cmd_run_now(self, args_dict: dict) -> str:
        """다음 사이클을 즉시 실행. 단, 긴급정지 보류 중에는 거부한다."""
        now = time.time()
        if now < self._emergency_hold_until:
            remain = self._emergency_hold_until - now
            msg = (f'긴급정지 보류 중 — 즉시 실행 요청을 무시한다 '
                   f'(남은 {remain:.0f}초)')
            self.logger.warning(msg)
            return msg
        self.timer_loop = 0.0
        self._force_immediate = True
        return 'Next cycle will run immediately'

    def _normalize_select_device_options(self) -> None:
        """select_device 옵션의 값을 내부 규약인 `<id>_device_id` 한 곳으로 모은다.

        프레임워크는 select_device 를 만나면 `<id>_id` 에 값을 넣는다
        (abstract_base_controller.setup_custom_options_csv). 저장 형식이나 과거
        데이터에 따라 `<id>` 자체에 들어 있는 경우도 있다. 반면 내부 코드는
        `<id>_device_id` 하나만 참조하므로, 세 이름을 여기서 하나로 정규화한다.

        옵션 id 가 이미 `_id` 로 끝나면(`geo_facility_id`) 프레임워크 규칙과
        겹쳐 `geo_facility_id_id` 라는 이상해 보이는 이름이 나온다 — 오타가
        아니라 규칙의 산물이다.

        **대상을 하드코딩하지 않고 FUNCTION_INFORMATION 에서 뽑는다.** 예전에는
        geo_facility_id 와 method 3종을 손으로 나열했는데, 그러면 새 select_device
        옵션을 추가할 때 이 목록에 넣는 것을 잊기 쉽다. 빠뜨리면 그 옵션은 항상
        빈값이 되고 아무 에러도 나지 않는다 — 실제로 method 3종이 누락됐을 때
        setpoint 가 조용히 None 으로 떨어져 Method 곡선이 한 번도 평가되지 않았다.
        """
        for opt in FUNCTION_INFORMATION.get('custom_options', []):
            if not isinstance(opt, dict) or opt.get('type') != 'select_device':
                continue
            oid = opt.get('id')
            if not oid:
                continue
            target = f'{oid}_device_id'
            if getattr(self, target, None):
                continue
            value = (getattr(self, f'{oid}_id', None) or
                     getattr(self, oid, None) or '')
            setattr(self, target, value or None)

    def _option_defaults(self) -> dict:
        """custom_options 의 기본값 사전 — '미수정' 판정에 사용."""
        out = {}
        for o in FUNCTION_INFORMATION.get('custom_options', []):
            if isinstance(o, dict) and 'id' in o and 'default_value' in o:
                out[o['id']] = o['default_value']
        return out

    def cmd_emergency_stop(self, args_dict: dict) -> str:
        """긴급정지: 모든 액추에이터를 safe_default 또는 OFF로 즉시 이동 + 60s 지연.

        safe_default > 0 인 액추에이터(예: 보온커튼 파킹 위치)는 해당 값으로,
        safe_default = 0 이면 output_off 로 처리한다.

        call_module_function() → threading.Thread 로 실행되므로
        현재 돌아가는 loop()와 무관하게 즉시 Output 컨트롤러에 전달된다.
        """
        failed = 0
        for p in self._profiles:
            ch = self._channel_map.get(p.actuator_id, 0)
            try:
                safe_val = float(getattr(p, 'safe_default', 0.0) or 0.0)
                adapter = getattr(self, '_adapter_by_id', {}).get(p.actuator_id)
                if safe_val > 0.0 and adapter is not None:
                    adapter.send(self.control, p.actuator_id, safe_val, ch,
                                 cycle_sec=float(self.update_period or 60.0))
                else:
                    self.control.output_off(p.actuator_id, output_channel=ch)
            except Exception as exc:
                failed += 1
                self.logger.error(
                    'EnvCoordinator emergency_stop: %s failed — %s',
                    p.actuator_id, exc)

        self._emergency_hold_until = time.time() + 60.0
        self.timer_loop = self._emergency_hold_until
        msg = (f'Emergency stop: safe_default/off sent for {len(self._profiles)} '
               f'actuator(s) ({failed} failed), next cycle delayed 60s')
        self.logger.warning(msg)
        return msg

    def force_safe_state(self) -> None:
        """외부 트리거(Conditional, Trigger) 에서 직접 호출하는 E-stop 진입점.

        cmd_emergency_stop 과 동일하지만 반환값 없이 조용히 실행한다.
        """
        self.cmd_emergency_stop({})

    # ─────────────────────────────────────────────────────────────────────────
    def loop(self) -> None:
        now = time.time()
        # 긴급정지 보류는 timer_loop 와 별개로 지킨다 — timer_loop 를 0 으로
        # 되돌리는 경로가 생겨도 보류가 뚫리지 않게 하기 위함이다.
        if now < self._emergency_hold_until:
            return
        if now < self.timer_loop:
            return
        period = self.update_period or 60.0
        self.timer_loop = now + period

        # Watchdog: 마지막 사이클로부터 3×period 이상 경과 시 경고
        if self._last_cycle_ts > 0 and (now - self._last_cycle_ts) > period * 3:
            gap = now - self._last_cycle_ts
            self.logger.warning(
                'EnvCoordinator watchdog: no cycle for %.0fs (expected %.0fs)',
                gap, period)
            # Alert when gap exceeds 24h — Growth Schedule may need manual correction
            if gap > 86400:
                gap_h = gap / 3600
                self.logger.warning(
                    'EnvCoordinator: %.1fh outage detected — plants continued growing. '
                    'Correct growth week via schedule_week_offset.',
                    gap_h)

        try:
            self._run_cycle(period)
        except Exception:
            self.logger.exception('EnvCoordinator cycle error')
