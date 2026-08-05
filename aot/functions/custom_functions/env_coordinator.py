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


# 작물 프리셋 속성 → 함수 옵션 매핑.
#   (preset_attr, option_id, sp_type_attr)
# sp_type_attr 이 있고 그 옵션이 'method' 이면 자동/강제 적용 모두 건너뛴다(메서드 우선).
_CROP_PRESET_OPTION_MAP = [
    ('dli_target', 'dli_target',       None),
    ('gdd_daily',  'gdd_target_daily', None),
    ('vpd_target', 'target_vpd',       'vpd_sp_type'),
    ('co2_target', 'target_co2',       'co2_sp_type'),
    ('temp_min',   'temp_min',         None),
    ('temp_max',   'temp_max',         None),
]


# ─────────────────────────────────────────────────────────────────────────────
class CustomModule(
    AbstractFunction,
    ProfileLoaderMixin,
    RuntimeStateMixin,
    CycleMixin,
    HelpersMixin,
):
    """Integrated facility environment control — L1+L2+L3 single Function."""

    def __init__(self, function: CustomController, testing: bool = False) -> None:
        super().__init__(function, testing=testing, name=__name__)

        self.control = DaemonControl()
        self.timer_loop: float = 0.0

        # Basic
        self.update_period  = None
        self.sensor_max_age = None

        # Growth Schedule
        self.schedule_start_time   = None
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

        # Photoperiod Method
        self.photo_method_id_device_id = None
        self.photo_anchor              = None
        self._photo_method_handler     = None
        self._photo_loaded_method_id   = None

        # VPD
        self.sensor_vpd              = None
        self.vpd_sp_type             = None
        self.target_vpd              = None
        self.vpd_method_id_device_id = None
        self.priority_vpd            = None
        self.tolerance_vpd           = None

        # Light
        self.sensor_light = None
        self.light_max    = None
        self.light_min    = None

        # CO₂
        self.sensor_CO2_int          = None
        self.co2_sp_type             = None
        self.target_co2              = None
        self.co2_method_id_device_id = None
        self.priority_co2            = None
        self.tolerance_co2           = None

        # CO₂ Method runtime state
        self._co2_method_handler    = None
        self._co2_last_sp: float    = None
        self._co2_loaded_method_id  = None

        # Temperature (constraints)
        self.sensor_T_int = None
        self.temp_max     = None
        self.temp_min     = None

        # Humidity (constraints)
        self.sensor_RH_int = None
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
        self.crop_preset             = None
        self._priority_ewa_state: dict = {}   # P5-4: {var: ewa_priority}

        # Cumulative Goal Tracker (P5-5)
        self.cumulative_tracker_enabled = None
        self.dli_target                 = None
        self.gdd_target_daily           = None
        self._daily_acc                 = None  # DailyAccumulator (lazy init)

        # VPD Decomposition
        self.vpd_weight_T = None

        # Guide Ranges (T / RH)
        self.guide_T_min  = None
        self.guide_T_max  = None
        self.guide_RH_min = None
        self.guide_RH_max = None

        # Wind
        self.sensor_wind         = None
        self.sensor_wind_dir     = None
        self.gate_wind_threshold = None

        # Forecast Feedforward (P3-4)
        self.forecast_feedforward_enabled = None
        self.forecast_lookahead_h         = None
        self._last_ff_signal              = None   # FeedforwardSignal (last cycle)

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
        if (self.nursery_water_source or 'groundwater') == 'groundwater':
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

        # 작물 프리셋이 바뀌면 DLI/GDD 목표를 자동 갱신(수동 입력은 보존)
        self._sync_crop_targets()

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
        self._sync_crop_targets()
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

    def _sync_crop_targets(self) -> None:
        """작물 프리셋 변경 시 목표 옵션(DLI/GDD/VPD/CO2/온도)을 자동 갱신.

        규칙:
          - 마커(crop_preset_applied)와 현재 crop_preset 이 같으면 no-op.
          - 변수에 메서드를 쓰는 경우(*_sp_type=='method') → 건너뜀(사용자 메서드 우선).
          - 현재값이 '옵션 기본값' 또는 '이전 프리셋 값'과 같으면(=자동값) 새 프리셋 값으로
            갱신, 다르면(=사용자 수동 입력) 보존.
          - 변경은 set_custom_option 으로 영속화되어 저장 후 UI 에 표시된다.
        """
        from aot.functions.utils.env_control.photosynthesis import (
            get_crop_params, CROP_PRESETS,
        )
        try:
            cur_key = self.crop_preset
            applied = self.get_custom_option('crop_preset_applied', None)
            if cur_key == applied:
                return
            new_crop = get_crop_params(cur_key)
            old_crop = get_crop_params(applied) if (applied in CROP_PRESETS) else None
            defaults = self._option_defaults()

            for preset_attr, opt_id, sp_attr in _CROP_PRESET_OPTION_MAP:
                if sp_attr and str(getattr(self, sp_attr, 'static')) == 'method':
                    continue   # 메서드 사용 중 → 사용자 설정 우선
                new_val = float(getattr(new_crop, preset_attr, 0.0) or 0.0)
                if new_val <= 0:
                    continue
                cur = float(getattr(self, opt_id, 0.0) or 0.0)
                opt_def = float(defaults.get(opt_id, 0.0) or 0.0)
                old_val = (float(getattr(old_crop, preset_attr, 0.0) or 0.0)
                           if old_crop else None)
                is_auto = (cur == 0.0
                           or abs(cur - opt_def) < 1e-9
                           or (old_val is not None and abs(cur - old_val) < 1e-9))
                if is_auto:
                    setattr(self, opt_id, new_val)
                    self.set_custom_option(opt_id, new_val)
            self.set_custom_option('crop_preset_applied', cur_key or '')
        except Exception:
            # get_crop_params() 는 dict 조회+기본값이라 던지지 않는다 — 여기서
            # 나는 예외는 사실상 전부 get/set_custom_option 의 DB 오류다. 즉
            # "예상된 실패" 가 아니라 전부 "예상 밖 실패" 이므로 debug 로 묻으면
            # 작물 프리셋 자동 동기화가 조용히 멈춘 채 아무도 모르게 된다.
            self.logger.warning('crop target sync failed', exc_info=True)

    def cmd_apply_crop_targets(self, args_dict: dict) -> str:
        """선택된 작물 프리셋의 권장값을 목표 옵션에 강제로 채워 영속화한다.

        자동 동기화는 수동 입력을 보존하지만, 이 버튼은 현재 값을 무시하고 프리셋
        권장값으로 덮어쓴다(명시적 재적용). 단, 메서드 사용 변수는 여전히 건너뛴다.
        """
        from aot.functions.utils.env_control.photosynthesis import get_crop_params
        crop = get_crop_params(self.crop_preset)
        applied = []
        for preset_attr, opt_id, sp_attr in _CROP_PRESET_OPTION_MAP:
            if sp_attr and str(getattr(self, sp_attr, 'static')) == 'method':
                continue
            val = float(getattr(crop, preset_attr, 0.0) or 0.0)
            if val <= 0:
                continue
            setattr(self, opt_id, val)
            self.set_custom_option(opt_id, val)
            applied.append(f'{opt_id}={val}')
        self.set_custom_option('crop_preset_applied', self.crop_preset or '')
        return (f"Applied {self.crop_preset} preset — " + ', '.join(applied)
                if applied else f"No targets applied (methods in use?) for {self.crop_preset}")

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
