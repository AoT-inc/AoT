# coding=utf-8
"""
_profile_loader_mixin.py — ProfileLoaderMixin: _reload_profiles().
"""

import json
from typing import Any, Callable

from aot.databases.models import Actions, Output
from aot.utils.database import db_retrieve_table_daemon

from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.group_expander import expand_group_commands
from aot.functions.utils.env_control.types import (
    ActuatorGroup, ActuatorProfile, CmdConstraints, ManualLockState,
)

from ._function_info import _FACILITY_SLOT_KIND, _KIND_CAPABILITIES

_K_PRIMARY = {
    'opening':      'K_OPENING_T',
    'cooler':       'K_COOLER_T',
    'heater':       'K_HEATER_T',
    'fogger':       'K_FOG_RH',
    'co2_injector': 'K_CO2_INJ',
    'shade':        'K_SHADE_T',
    'curtain':      'K_CURTAIN_T',
    'lighting':     'K_LIGHT_PPFD',
}

# kind 별 전력 소비 기본값 (kW at 100%). 에너지 비용 계산에 사용.
_KIND_RATED_KW = {
    'heater':       5.0,
    'cooler':       2.5,
    'co2_injector': 0.5,
    'fogger':       0.3,
    'lighting':     2.0,
    'exhaust_fan':  0.75,
    'intake_fan':   0.75,
    'circulation_fan': 0.2,
    'opening':      0.1,   # 모터 소비전력
    'shade':        0.1,
    'curtain':      0.1,
}

# kind 별 배기팬 기본 정격 풍량 (m³/h). rated_m3h 미설정 시 fallback.
_KIND_DEFAULT_RATED_M3H = {
    'exhaust_fan':  3000.0,
    'intake_fan':   3000.0,
    'circulation_fan': 1500.0,
}

# kind 별 idle/안전 기본 개도(%). 규약: 100=열림, 0=닫힘.
# 스크린(보온커튼·차광막)은 할 일 없을 때 '걷힘(100=열림)'이 안전 — 닫으면(0)
# 단열/차광이 켜져 더운 낮에 열을 가두거나 빛을 막는다. 능동 배치(보온·차광)는
# 제어 법칙·안전게이트(폭염/한파)가 필요 시 명령한다. 개구부·팬은 0(닫힘/OFF).
_KIND_SAFE_DEFAULT = {
    'curtain': 100.0,
    'shade':   100.0,
}


# 습윤형 분무기 기본 펄스 도징 (육묘장 모드가 꺼져 있을 때).
# 잎을 적시는 분무기를 개도(%)로 연속 변조하면 사이클의 절반을 계속 뿌리게 되어
# 잎이 마를 틈이 없다. 이는 육묘가 아닌 시설에서도 병해 유발 조건이므로 기본값
# 자체를 펄스로 둔다. 육묘장 모드는 여기서 더 조인다(짧게, 더 긴 건조).
_FOG_DEFAULT_MAX_ON_SEC  = 30.0
_FOG_DEFAULT_MIN_OFF_SEC = 180.0


# 실외 센서가 하나라도 연결돼 있으면 있어야 할 채널.
# 없으면 `ext_context_fallback` 이 **실외=실내로 지어낸다** — 그러면 내외 차가
# 0 이라 환기 무익 판정이 서서 창이 닫히고, 풍향은 기본 0°(정북)로 들어가
# 북향이 아닌 측창이 영구 leeward 가 된다. 화면은 "기상대 연결됨" 으로 보이고
# 제어는 지어낸 숫자로 도는데 **아무 경고도 없었다**(2026-08-26 イチゴ: 기상대에
# `light` 채널 하나만 묶여 있었고 온도·습도·풍속·풍향이 전부 null 이었다).
_OUTDOOR_REQUIRED_MTYPES = {
    'temperature':    '실외 온도',
    'humidity':       '실외 습도',
    'wind_speed':     '풍속',
    'wind_direction': '풍향',
}


def _missing_outdoor_channels(sensors_outdoor: list) -> list:
    """실외 센서는 붙었는데 채널이 안 묶인 것들의 한국어 이름.

    실외 센서 자체가 하나도 없으면 빈 목록이다 — 그건 "실외를 안 쓰는 설치" 라
    정상이고, 여기서 경고하면 노이즈가 된다. 경고할 값이 있는 경우는
    **연결해 놓고 반만 묶은** 상태 하나뿐이다.
    """
    if not sensors_outdoor:
        return []
    have = {(s.get('measurement_type') or '').strip()
            for s in sensors_outdoor}
    return [label for mtype, label in _OUTDOOR_REQUIRED_MTYPES.items()
            if mtype not in have]


def _is_wetting_fog(kind: str, capacity_meta: dict, *, conservative=True) -> bool:
    """잎을 적시는 분무기인가 — safety_gates.is_wetting_fogger 와 같은 기준.

    프로필을 만들기 *전에* 판정해야 하므로 ActuatorProfile 대신 kind 와
    capacity_meta 로 본다.

    ## "노즐 정보 없음" 의 뜻은 **부르는 자리에 따라 다르다** (2026-08-26)

    `conservative=True`(기본) 는 **안전 판정용**이다 — 일소 잠금처럼 "모르면
    잠근다" 가 옳은 자리. 잎이 타는 것보다 분무를 못 하는 편이 낫다.

    `conservative=False` 는 **기능을 빼는 판정용**이다. 거기서 "모르면 습윤" 은
    뜻이 정반대가 된다 — 노즐을 모른다는 이유로 가습기를 환경 제어에서 통째로
    빼면, 시설에 가습기가 있는데도 코디네이터가 "이를 조절할 장치가 없습니다"
    라고 보고한다(2026-08-26 영양 육묘장 실측).

    ⚠ 그리고 이 자리에서는 **모르는 것이 아니다.** 관수 계열은 스프링클러가
      하나라도 있어야 'fogger' 로 등록되므로(`_irrigation_actuator_kind`),
      노즐 요약은 반드시 붙어 있다. 노즐이 비어 있는 fogger 는 설비 팔레트로
      놓은 **가습기 그 자체**다 — 관수 노즐이 아니라 습윤 여부를 물을 대상이
      아니다.
    """
    if kind != 'fogger':
        return False
    nozzle = (capacity_meta or {}).get('nozzle')
    if nozzle is None:
        return conservative
    return bool(nozzle.get('wetting'))


def _fog_excluded_from_env(coordinator: Any, kind: str, capacity_meta: dict) -> bool:
    """이 분무기를 환경 제어 대상에서 통째로 뺄지.

    관수와 가습을 한 장치로 처리하는 시설이 있다. 그런 노즐은 관수용으로
    설계돼 있어 1회 살수가 가습에 필요한 양보다 훨씬 많은데, 코디네이터가
    가습용으로 쓰면 짧은 펄스를 하루에도 수십 번 반복하게 된다. 그 얕은
    수막은 흘러내리지 못하고 잎에서 그대로 말라 물에 녹아 있던 성분을
    잎 위에 남긴다(아침에 흠뻑 주면 흘러내리며 오히려 씻긴다).

    이 옵션을 끄면 코디네이터가 해당 액추에이터의 **프로필 자체를 만들지
    않는다.** 명령을 0 으로 보내는 게 아니라 아예 만들지 않는 것이 핵심이다 —
    조율기는 명령을 못 받은 프로필에 safe_default(분무기는 0.0) 를 채워 넣고,
    습윤형 분무기는 펄스 도징 대상이라 디스패치 데드밴드도 면제되므로,
    프로필이 남아 있으면 매 사이클 output_off 가 나가 별도 관수 제어를
    10 분 안에 꺼버린다.

    고압 미세포그(비습윤)와 그 외 액추에이터는 영향받지 않는다.
    """
    # ⚠ **여기서는 보수적 판정을 쓰지 않는다**(위 `_is_wetting_fog` 주석).
    #   기능을 빼는 자리라 "모르면 습윤" 이 곧 "모르면 가습 수단을 없앤다" 가
    #   된다. 노즐이 없는 fogger 는 설비 팔레트의 가습기이지 관수 노즐이 아니다.
    if not _is_wetting_fog(kind, capacity_meta, conservative=False):
        return False
    val = getattr(coordinator, 'use_wetting_fog_for_humidity', True)
    if val is None:
        return False        # 미설정 = 기본값(사용) — 종전 동작 유지
    return not bool(val)


def _fog_pulse_constraints(coordinator: Any, kind: str, capacity_meta: dict) -> dict:
    """습윤형 분무기에 적용할 관수식 펄스 도징 파라미터.

    가습량을 펄스 폭이 아니라 펄스 빈도로 조절한다 — 관수가 일정 간격으로
    정량을 주는 방식과 같다. 드립·고압 미세포그(비습윤)에는 적용하지 않는다.

    Returns:
        CmdConstraints 키워드 dict (미적용이면 빈 dict)
    """
    if not _is_wetting_fog(kind, capacity_meta):
        return {}
    if getattr(coordinator, 'nursery_mode', False):
        return {
            'max_on_sec':  float(
                getattr(coordinator, 'nursery_max_on_sec', 20.0) or 20.0),
            'min_off_sec': float(
                getattr(coordinator, 'nursery_min_off_sec', 600.0) or 600.0),
        }
    return {
        'max_on_sec':  _FOG_DEFAULT_MAX_ON_SEC,
        'min_off_sec': _FOG_DEFAULT_MIN_OFF_SEC,
    }


def _build_cost_fn(
        kind: str, base_cost: float,
        capacity_meta: dict) -> Callable[[dict, float], float]:
    """env·pct 를 실제로 사용하는 cost_fn 생성.

    에너지 비용 = rated_kW × (pct/100) × elec_price_per_kWh (kWh/cycle 근사).
    wear_cost = 명령 변화에 비례 (cycle_sec 없이 pct 비례 근사).
    총 비용 = base_cost + energy_cost. 낮을수록 helpers 정렬에서 우선.
    """
    rated_kw = float(
        capacity_meta.get('rated_kW_thermal')
        or _KIND_RATED_KW.get(kind, 1.0)
    )

    def cost_fn(env: dict, pct: float) -> float:
        elec = float(env.get('elec_price_per_kWh', 1.0) or 1.0)
        energy = rated_kw * (pct / 100.0) * elec
        return base_cost + energy

    return cost_fn


def _bay_capacity_fraction(bay_slices, bay_id):
    """구역 하나가 시설에서 차지하는 **폭 비율** → float|None.

    구역은 bay 범위를 병합해 만들 수 있어 폭이 제각각이다. 개수로 나누면
    (`1 / bay 수`) 병합 구역의 체적·외피·환기 면적이 통째로 틀어진다 —
    4동 중 A(1~3동)·B(4동)라면 실제 3:1 이 1:1 이 된다.

    분모는 **모든 구역 폭의 합**이다. 시설 전폭을 쓰면 단동 연립의 동 사이
    간격(spacing)이 분모에 섞이는데, 나누려는 것은 실내이지 틈이 아니다.
    합을 쓰면 조각들의 비율이 정확히 1.0 으로 닫힌다.

    폭을 알 수 없으면(옛 슬라이스·계산 실패) **None** 을 돌려준다 — 0 이나 1 을
    지어내면 그 구역만 조용히 다른 크기로 제어된다.
    """
    def _w(sl):
        try:
            w = float(sl.get('x_max')) - float(sl.get('x_min'))
        except (TypeError, ValueError):
            return None
        return w if w > 0 else None

    total = 0.0
    mine = None
    for sl in (bay_slices or []):
        w = _w(sl)
        if w is None:
            return None
        total += w
        if sl.get('id') == bay_id:
            mine = w
    if mine is None or total <= 0:
        return None
    return mine / total


class ProfileLoaderMixin:
    """Mixin: actuator profile loading from facility, paired outputs, and manual actions."""

    # ── 형제 코디네이터가 이미 맡은 구역 ───────────────────────────────────
    # 같은 시설에 구역을 정한 코디네이터가 따로 돌고 있으면, 구역을 안 정한
    # 이 코디네이터는 그 구역 장치를 건드리면 안 된다. 안 그러면 같은 장치에
    # 두 코디네이터가 다른 명령을 낸다.
    #
    # ⚠ **자기 자신은 뺀다.** 안 빼면 구역을 정한 코디네이터가 자기 구역을
    #   "남이 맡았다" 로 읽는다 — 그런데 이 함수는 구역을 안 정한 쪽에서만
    #   불리므로 실제로는 걸리지 않는다. 그래도 조건을 남겨 둔다: 나중에
    #   호출부가 늘면 그때 조용히 틀린다.
    def _bays_claimed_by_siblings(self, facility_uuid: str) -> set:
        if not facility_uuid:
            return set()
        try:
            from aot.databases.models import CustomController
            rows = db_retrieve_table_daemon(CustomController)
            mine = getattr(self, 'unique_id', None)
            claimed = set()
            for row in (rows.all() if hasattr(rows, 'all') else rows):
                if row.unique_id == mine or not row.is_activated:
                    continue
                if (row.device or '') != 'env_coordinator':
                    continue
                opts = json.loads(row.custom_options or '{}')
                # ⚠ 저장되는 키는 `geo_facility_id` 다. 속성 이름
                #   (`self.geo_facility_id_device_id`)은 select_device 옵션이
                #   붙이는 접미사라 **DB 키와 다르다** — 속성 이름으로 조회하면
                #   언제나 빈 손이라 이 판정이 통째로 죽는데, 증상은 "형제가
                #   없다" 와 구분되지 않는다(2026-08-26 실측).
                linked = (opts.get('geo_facility_id')
                          or opts.get('geo_facility_id_device_id') or '')
                if linked != facility_uuid:
                    continue
                scope = str(opts.get('bay_scope') or '').strip()
                if scope:
                    claimed.add(scope)
            return claimed
        except Exception:
            self.logger.debug('형제 코디네이터 조회 실패', exc_info=True)
            return set()

    def _reload_profiles(self) -> None:
        """Hybrid loader: facility-derived profiles + manual env_actuator action profiles.

        Order:
          1. If geo_facility_id_device_id is set → load GeoFacility, iterate
             facility.actuators and build ActuatorProfile per slot with GIS metadata.
          2. Scan actuator_paired Output devices.
          3. Iterate env_actuator Actions and build/merge profiles.
          4. Parse ActuatorGroup definitions from GeoFacility.groups.
          5. Remove followers from _profiles (coordinator only routes leaders).
        """
        profiles = []
        channel_map = {}
        by_id = {}  # actuator_id → profile
        n_facility = 0
        # D1/D2: 초기화 (통합 데이터 없을 때 빈 상태 유지)
        self._vent_openings            = []
        self._facility_orientation_deg = 0.0
        self._sensors_resolved         = []
        self._sensors_resolved_outdoor = []
        self._sensors_forecast         = []  # facility weather_bindings → forecast Input 장치
        self._bay_scope_active         = None
        # bay_scope 로 제외된 액추에이터 — 섹션 2(자동 발견)가 재등록하지 않도록 차단
        bay_excluded_ids: set = set()
        n_manual_new = 0
        n_manual_merged = 0

        # ── 1. Facility-driven profiles (B2: via get_facility_integration) ─────
        # Uses the same normalized payload as the B1 HTTP endpoint so that
        # G1-accurate vent areas (fittings-authoritative) and fitting-level
        # actuator bindings are automatically reflected here.
        facility_uuid = self.geo_facility_id_device_id or ''
        integ = None  # 섹션 4(그룹 파싱) 에서도 재사용
        if facility_uuid:
            from aot.aot_flask.geo.facility_integration import get_facility_integration
            from aot.aot_flask.geo.facility_geo_helpers import shape_azimuth_area

            try:
                # get_facility_integration 은 Flask-SQLAlchemy Model.query 를 사용한다.
                # 데몬 스레드에서는 앱 컨텍스트가 없을 수 있으므로 기존 앱 참조로 컨텍스트를 열어 호출한다.
                from flask import has_app_context
                if has_app_context():
                    integ, integ_err = get_facility_integration(facility_uuid, bypass_cache=True)
                else:
                    try:
                        from aot.ai.services.ai_scheduler_service import _flask_app as _svc_app
                    except Exception:
                        _svc_app = None
                    if _svc_app:
                        with _svc_app.app_context():
                            integ, integ_err = get_facility_integration(facility_uuid, bypass_cache=True)
                    else:
                        integ, integ_err = None, 'Flask app context unavailable in daemon'
            except Exception as _e:
                integ, integ_err = None, str(_e)

            if integ_err:
                self.logger.warning(
                    '_reload_profiles: integration load failed for "%s": %s',
                    facility_uuid, integ_err)
                integ = None

            if integ:
                # ── Bay(구역) scope 검증 ──────────────────────────────────────
                # bay_scope 설정 시 해당 bay 귀속 센서/액추에이터만 사용한다.
                # integ 는 TTL 캐시 공유 dict 이므로 변형하지 않고 로컬 필터링.
                bay_scope = str(getattr(self, 'bay_scope', '') or '').strip()
                bays_avail = integ.get('bays') or []
                # ── 없는 구역을 가리키면 **시설 전체로 넓히지 않는다** ─────────
                # 예전에는 경고 한 줄만 남기고 `bay_scope = ''` 로 되돌려
                # 시설 전체를 잡았다. 사용자는 "이 구역만 제어한다" 고 믿는데
                # 실제로는 **온 시설의 장치를 건드린다** — 오타 하나나 구역
                # 이름 변경이 제어 범위를 통째로 넓히는 셈이다(2026-08-26).
                # 게다가 컨트롤러 로거는 기본이 ERROR 라 그 경고는 **아무 데도
                # 안 남는다**(`base_controller.py`).
                #
                # 넓히는 대신 **아무것도 맡지 않는다.** 둘 다 사용자가 원한 것이
                # 아니지만, 안 하는 쪽은 눈에 보이고(장치가 안 움직인다) 넓히는
                # 쪽은 안 보인 채 남의 구역을 조작한다.
                self._bay_scope_missing = None
                if bay_scope and not any(
                        b.get('id') == bay_scope for b in bays_avail):
                    self.logger.error(
                        '구역 "%s" 을(를) 시설 "%s" 에서 찾지 못했습니다 '
                        '(있는 구역: %s) — 이 코디네이터는 아무 장치도 맡지 '
                        '않습니다. 구역 이름을 확인하세요.',
                        bay_scope, facility_uuid,
                        [b.get('id') for b in bays_avail])
                    # ⚠ 파생 상태도 함께 비운다 — 하나라도 옛 값이 남으면
                    #   "프로필은 없는데 그룹·어댑터는 있다" 는 어긋난 상태가
                    #   되고, 다음 사이클이 그 위에서 돈다.
                    self._bay_scope_missing = bay_scope
                    self._bay_scope_active  = bay_scope
                    self._profiles     = []
                    self._sensors_resolved = []
                    self._vent_openings    = []
                    self._channel_map  = {}
                    self._actuator_idx = {}
                    self._by_id        = {}
                    self._groups       = []
                    return
                self._bay_scope_active = bay_scope or None

                # D1: 캐시 — 사이클마다 wind_biased_opening() 에 재사용
                self._vent_openings = integ.get('vent_openings') or []
                self._facility_orientation_deg = float(
                    ((integ.get('geometry_3d') or {}).get('orientation_deg')) or 0.0
                )
                # D2: 캐시 — _collect_internal() 에서 위치 가중 측정값 보완
                # bay_scope 시 해당 bay 귀속 실내 센서만 사용 (실외 센서는 시설 공통).
                self._sensors_resolved = [
                    s for s in (integ.get('sensors_resolved') or [])
                    if not bay_scope or s.get('bay_id') == bay_scope
                ]
                # 실외 센서 캐시 — _cycle_mixin 에서 T_ext/RH_ext 직접 판독
                self._sensors_resolved_outdoor = integ.get('sensors_outdoor') or []
                self._outdoor_missing = _missing_outdoor_channels(
                    self._sensors_resolved_outdoor)
                if self._outdoor_missing:
                    # ⚠ ERROR 로 남긴다. 입력·컨트롤러 로거는 log_level_debug 가
                    # 꺼져 있으면 ERROR 로 설정되므로(base_controller), warning 은
                    # 기본 설치에서 **아무 데도 안 남는다**.
                    self.logger.error(
                        '실외 센서가 연결돼 있는데 채널이 비어 있습니다: %s. '
                        '이 값들은 측정되지 않으며 제어기가 "실외=실내" 로 '
                        '지어냅니다 — 환기 판정·풍향 가중치가 그 위에서 돕니다. '
                        '시설 편집기에서 기상 센서의 해당 채널을 함께 선택하세요.',
                        ', '.join(self._outdoor_missing))
                # 기상/예보 바인딩 캐시 — forecast_feedforward 가 KMA 파일 대신 소비
                self._sensors_forecast = integ.get('sensors_forecast') or []

                capacity_meta_base = integ.get('capacity_meta') or {}
                # Stage 2: irrigation_summary → facility 전체 유량 캐시
                # VolumetricAdapter 가 flow_lpm 을 capacity_meta 에서 읽는다.
                irr_summary = integ.get('irrigation_summary') or {}
                irr_totals  = irr_summary.get('totals') or {}
                irr_flow_lpm = float(irr_totals.get('flow_lpm') or 0.0)
                capacity_meta = {
                    'volume_m3':           float(capacity_meta_base.get('volume_m3') or 0.0),
                    'u_effective':         float(capacity_meta_base.get('u_effective') or 0.0),
                    'envelope_m2':         float(capacity_meta_base.get('envelope_m2') or 0.0),
                    'vent_open_m2':        float(capacity_meta_base.get('vent_open_m2') or 0.0),
                    'vent_open_source':    capacity_meta_base.get('vent_open_source') or 'none',
                    # G3 보강: 일사 투과율 (shade/solar 효과 정규화)
                    'transmittance':       float(
                        capacity_meta_base.get('transmittance')
                        or (integ.get('computed') or {}).get('transmittance')
                        or 0.80
                    ),
                    # Stage 2: 시설 전체 관수 총 유량 (VolumetricAdapter / fogger physics)
                    'irrigation_flow_lpm': irr_flow_lpm,
                }
                gis_resolved = 0
                facility_name = integ.get('name') or facility_uuid
                actuators_list = integ.get('actuators_resolved') or []
                vent_source = capacity_meta.get('vent_open_source') or 'none'

                # ── Bay scope: 액추에이터 필터 + 물리량 bay 비례 축소 ──────────
                # 귀속 불가(bay_ids=[]) 액추에이터는 시설 공통으로 보고 제외 —
                # 같은 시설의 bay 코디네이터끼리 명령이 충돌하지 않도록 한다.
                if bay_scope:
                    n_before = len(actuators_list)
                    _all_act_ids = {
                        ar.get('output_uuid') for ar in actuators_list}
                    actuators_list = [
                        ar for ar in actuators_list
                        if bay_scope in (ar.get('bay_ids') or [])
                    ]
                    allowed_act_ids = {
                        ar.get('output_uuid') for ar in actuators_list}
                    bay_excluded_ids = _all_act_ids - allowed_act_ids
                    self._vent_openings = [
                        op for op in self._vent_openings
                        if op.get('actuator_id') in allowed_act_ids
                    ]
                    # ── 배분은 **폭 비율**이다, 개수가 아니다 (2026-08-26) ────
                    # 예전에는 `1 / bay 개수` 였는데, 구역은 bay 범위를 **병합**해
                    # 만들 수 있어 폭이 제각각이다(`compute_bay_slices` 가
                    # bay_start~bay_end 로 x_min/x_max 를 정확히 계산해 둔다).
                    # 4동 중 A(1~3동)·B(4동)로 나누면 실제 3:1 인 체적·외피·환기
                    # 면적이 1:1 로 배분됐다 — 좁은 구역은 열용량을 3배로 보고
                    # 과열을 못 잡고, 넓은 구역은 반대로 과잉 반응한다.
                    #
                    # 분모는 **모든 구역 폭의 합**이다(시설 전폭이 아니다).
                    # 단동 연립은 동 사이 간격(spacing)이 있어 전폭에는 그 틈이
                    # 섞이는데, 나누려는 것은 실내이지 틈이 아니다. 합을 쓰면
                    # 조각들의 비율이 정확히 1.0 으로 닫힌다.
                    bay_frac = _bay_capacity_fraction(bays_avail, bay_scope)
                    if bay_frac is None:
                        # 폭을 모르면 예전처럼 개수로 나눈다 — 근거가 없다고
                        # 배분을 포기하면 시설 전체 용량으로 제어하게 된다.
                        bay_frac = 1.0 / max(1, len(bays_avail))
                        self.logger.warning(
                            '_reload_profiles: bay "%s" 의 폭을 알 수 없어 '
                            '개수로 나눕니다(1/%d) — 구역 폭이 다르면 용량이 '
                            '어긋납니다', bay_scope, max(1, len(bays_avail)))
                    for _k in ('volume_m3', 'envelope_m2', 'vent_open_m2',
                               'irrigation_flow_lpm'):
                        capacity_meta[_k] = capacity_meta[_k] * bay_frac
                    self.logger.info(
                        '_reload_profiles: bay_scope "%s" — %d/%d actuator(s), '
                        '%d indoor sensor(s), capacity x%.3f',
                        bay_scope, len(actuators_list), n_before,
                        len(self._sensors_resolved), bay_frac)
                else:
                    # ── 구역을 안 정한 코디네이터는 **남의 구역을 비켜 간다** ──
                    # 구역 간 충돌 회피는 예전에 "양쪽 다 bay_scope 가 있을 때"
                    # 만 돌았다. 한쪽이 전체 시설이면 그쪽이 남의 구역 장치까지
                    # 그대로 잡아가, 두 코디네이터가 같은 장치에 다른 명령을
                    # 낸다(2026-08-26 지적).
                    #
                    # 구역을 정한 형제가 **있을 때만** 비켜 간다 — 형제가 없으면
                    # 예전과 똑같이 시설 전체를 맡는다. 그래야 구역을 쓰지 않는
                    # 설치가 업그레이드로 조용히 달라지지 않는다.
                    claimed = self._bays_claimed_by_siblings(facility_uuid)
                    if claimed:
                        n_before = len(actuators_list)
                        _all_act_ids = {
                            ar.get('output_uuid') for ar in actuators_list}
                        actuators_list = [
                            ar for ar in actuators_list
                            if not (set(ar.get('bay_ids') or []) & claimed)
                        ]
                        allowed_act_ids = {
                            ar.get('output_uuid') for ar in actuators_list}
                        bay_excluded_ids = _all_act_ids - allowed_act_ids
                        self._vent_openings = [
                            op for op in self._vent_openings
                            if op.get('actuator_id') in allowed_act_ids
                        ]
                        if bay_excluded_ids:
                            self.logger.info(
                                '_reload_profiles: 구역 %s 은(는) 다른 '
                                '코디네이터가 맡고 있어 장치 %d개를 비켜 갑니다 '
                                '(%d/%d 사용)',
                                sorted(claimed), len(bay_excluded_ids),
                                len(actuators_list), n_before)

                # 이슈 B: fittings 권위 모드에서는 vent_open_m2 균등 분할 fallback
                # 을 끈다 (이중 회계 방지). envelope-only 모드일 때만 균등 분할.
                if vent_source != 'fittings':
                    vent_slots = [
                        a for a in actuators_list
                        if a.get('kind') == 'opening' and a.get('slot_key')
                        and 'vent' in (a.get('slot_key') or '')
                    ]
                    vent_fallback_per_slot = (
                        (capacity_meta['vent_open_m2'] / len(vent_slots))
                        if vent_slots else 0.0)
                else:
                    vent_fallback_per_slot = 0.0

                # 이슈 C: GeoShape N+1 → 한 번에 bulk fetch.
                # [GB-6] 조회는 geo_binding 리졸버 경유(사망 컬럼 직접 조회 금지).
                output_uuids_all = [ar.get('output_uuid') for ar in actuators_list
                                    if ar.get('output_uuid')]
                shape_lookup: dict = {}
                try:
                    if output_uuids_all:
                        from aot.aot_flask.geo.device_binding import (
                            shapes_for_devices)
                        for dev, rows in shapes_for_devices(
                                output_uuids_all).items():
                            if rows:
                                shape_lookup[dev] = rows[0]
                except Exception as exc:
                    self.logger.debug(
                        '_reload_profiles: GeoShape bulk fetch failed: %s', exc)

                for ar in actuators_list:
                    output_uuid = ar.get('output_uuid')
                    kind        = ar.get('kind')
                    if not output_uuid or not kind:
                        continue

                    # 관수 겸용 분무기 제외 — 프로필을 만들지 않아야 조율기의
                    # safe_default(0.0) 채움조차 일어나지 않는다. 조용히 빠지면
                    # "왜 가습이 안 되나" 를 추적할 수 없으므로 반드시 남긴다.
                    if _fog_excluded_from_env(self, kind, {'nozzle': ar.get('nozzle')}):
                        # ⚠ **`info` 가 아니라 `error` 다.** 컨트롤러 로거는
                        #   `log_level_debug` 가 꺼져 있으면 레벨이 ERROR 라
                        #   (`base_controller.py`), info 는 **아무 데도 안
                        #   남는다.** 바로 위 주석이 "조용히 빠지면 왜 가습이
                        #   안 되나를 추적할 수 없으므로 반드시 남긴다" 고 적어
                        #   두었는데 실제로는 안 남고 있었다(2026-08-26).
                        #   장치 하나가 환경 제어에서 통째로 빠지는 일이라
                        #   등급을 올릴 근거도 충분하다.
                        self.logger.error(
                            '환경 제어 제외: %s (습윤형 분무 — 관수 전용으로 둠). '
                            '가습은 스크린·개구부·팬으로 처리한다.', output_uuid)
                        continue

                    # G1 area: use per-actuator vent_openings_area_m2 when > 0,
                    # otherwise fall back to envelope-derived estimates.
                    g1_area = float(ar.get('vent_openings_area_m2') or 0.0)
                    slot_key = ar.get('slot_key') or ''
                    if g1_area > 0:
                        area_m2 = g1_area
                    elif 'vent' in slot_key:
                        area_m2 = vent_fallback_per_slot
                    elif slot_key == 'thermal_curtain':
                        area_m2 = capacity_meta['envelope_m2']
                    elif slot_key == 'shade_curtain':
                        area_m2 = float(
                            (integ.get('computed') or {}).get('roof_m2') or 0.0)
                    else:
                        area_m2 = 0.0

                    # GIS azimuth: still resolved from GeoShape (fitting surface_normals
                    # require a coordinate-system convention not yet standardised here).
                    azimuth_deg = None
                    shape = shape_lookup.get(output_uuid)
                    if shape and shape.feature:
                        az_shp, ar_shp = shape_azimuth_area(shape.feature)
                        if az_shp is not None:
                            azimuth_deg = az_shp
                            gis_resolved += 1
                        if ar_shp is not None and ar_shp > 0 and area_m2 == 0.0:
                            # Only override area from GIS when integration produced 0.
                            area_m2 = ar_shp

                    # 액추에이터별 사양 보강 (rated_m3h, rated_kW_thermal)
                    act_capacity_meta = dict(capacity_meta)
                    rated_m3h = float(ar.get('rated_m3h') or 0.0)
                    if rated_m3h <= 0:
                        rated_m3h = _KIND_DEFAULT_RATED_M3H.get(kind, 0.0)
                    if rated_m3h > 0:
                        act_capacity_meta['rated_m3h'] = rated_m3h
                    rated_kw = float(ar.get('rated_kW_thermal') or 0.0)
                    if rated_kw > 0:
                        act_capacity_meta['rated_kW_thermal'] = rated_kw

                    # P3: per-actuator irrigation flow (facility_integration 4c)
                    # irrigation_layer.actuator_id 기반으로 집계된 emitter 유량을
                    # 액추에이터별 capacity_meta 에 주입한다.
                    # VolumetricAdapter 는 이 값을 사용해 on_sec → ml 를 환산한다.
                    per_act_flow_lpm = float(ar.get('flow_lpm') or 0.0)
                    if per_act_flow_lpm > 0.0:
                        act_capacity_meta['irrigation_flow_lpm'] = per_act_flow_lpm
                    # else: falls back to facility-total irrigation_flow_lpm already in
                    # act_capacity_meta (copied from capacity_meta at dict() above)

                    # 노즐 배치에서 산출된 엽면 습윤 특성 (facility_integration 4c).
                    # 육묘 일소 게이트가 이 값으로 습윤형 분무 여부를 판정한다.
                    nozzle_meta = ar.get('nozzle')
                    if nozzle_meta:
                        act_capacity_meta['nozzle'] = nozzle_meta

                    # 증발 효과용 유량 — `irrigation_flow_lpm` 과 **다른 값**이다.
                    #
                    #  * `irrigation_flow_lpm` : 투여량 환산용(VolumetricAdapter).
                    #    드립을 포함한 총 유량이고, 위에서 보듯 액추에이터 값이
                    #    없으면 시설 합계로 폴백한다.
                    #  * `fog_flow_lpm`        : 공기 중으로 나가 증발하는 유량.
                    #    드립은 뿌리로 가므로 제외하고, **폴백도 하지 않는다.**
                    #
                    # 두 값을 하나로 쓰다가 사고가 났다(2026-08-20 로컬 육묘장):
                    # 노즐이 없는 SIM 가습기가 시설 전체 관수 216 L/min(드립
                    # 에미터 324개)을 물려받아, 증발냉각 효과가 9448 m³ 온실에서
                    # **45.6 °C/사이클** 로 나왔다. 그 한 값이 결합 drive 의
                    # 가중치를 20배로 지배해 나머지 축을 전부 무의미하게 만들었다.
                    #
                    # 노즐 정보가 없으면 키를 넣지 않는다 — effect 쪽이 그때
                    # 물리 계산을 포기하고 보수적 K 상수로 떨어진다. 모르는 값을
                    # 남의 값으로 메우지 않는 것이 요점이다.
                    _spr_lph = float((nozzle_meta or {}).get('sprinkler_flow_lph') or 0.0)
                    if _spr_lph > 0.0:
                        act_capacity_meta['fog_flow_lpm'] = _spr_lph / 60.0

                    effect_model = build_effect_model(kind, {})
                    profile = ActuatorProfile(
                        actuator_id=output_uuid,
                        kind=kind,
                        capabilities=ar.get('capabilities') or _KIND_CAPABILITIES.get(kind, []),
                        cost_fn=_build_cost_fn(kind, 5.0, act_capacity_meta),
                        response_sec=60.0,
                        safe_default=_KIND_SAFE_DEFAULT.get(kind, 0.0),
                        manual_lock=ManualLockState(),
                        effect_model=effect_model,
                        cmd_constraints=CmdConstraints(
                            **_fog_pulse_constraints(
                                self, kind, act_capacity_meta)),
                        geo_facility_id=facility_uuid,
                        slot_key=slot_key or None,
                        azimuth_deg=azimuth_deg,
                        area_m2=area_m2,
                        vent_form=ar.get('vent_form'),
                        capacity_meta=act_capacity_meta,
                    )
                    profiles.append(profile)
                    by_id[output_uuid] = profile
                    channel_map[output_uuid] = 0
                    n_facility += 1

                self.logger.debug(
                    '_reload_profiles: %d facility-derived actuator(s) from "%s" '
                    '(gis_resolved=%d/%d, vent_source=%s)',
                    n_facility, facility_name, gis_resolved, n_facility,
                    capacity_meta.get('vent_open_source', 'n/a'))

        # ── 2. paired 액추에이터 Outputs (자동 발견) ──────────────────────────
        # actuator_paired(전용 릴레이) + actuator_paired_bus(공유 버스) 양쪽 모두.
        n_paired = 0
        try:
            from aot.aot_flask.geo.facility_geo_helpers import shape_azimuth_area
            from aot.outputs.paired_actuator_common import (
                KIND_TO_PROFILE_KIND, PAIRED_ACTUATOR_OUTPUT_TYPES)
            paired_outputs = Output.query.filter(
                Output.output_type.in_(PAIRED_ACTUATOR_OUTPUT_TYPES)).all()
        except Exception:
            paired_outputs = []
            KIND_TO_PROFILE_KIND = {}

        for out in paired_outputs:
            out_uuid = out.unique_id
            if out_uuid in by_id:
                continue
            # bay_scope 로 제외된 시설 액추에이터의 자동 재등록 방지
            if out_uuid in bay_excluded_ids:
                continue

            try:
                from aot.databases.models import OutputChannel
                ch = OutputChannel.query.filter_by(output_id=out_uuid, channel=0).first()
                ch_opts = json.loads(ch.custom_options or '{}') if ch else {}
            except Exception:
                ch_opts = {}

            actuator_kind = ch_opts.get('actuator_kind') or 'side_vent'
            profile_kind = KIND_TO_PROFILE_KIND.get(actuator_kind)
            if not profile_kind:
                continue

            azimuth_deg = ch_opts.get('azimuth_deg')
            area_m2     = ch_opts.get('area_m2')
            cost        = float(ch_opts.get('cost', 5.0) or 5.0)
            k_override  = float(ch_opts.get('k_override', 0.0) or 0.0)

            # 유효 구간: actuator_paired 채널 옵션에서 읽어 CmdConstraints 에 반영
            eff_start = float(ch_opts.get('effective_start_pct') or 0.0)
            eff_end   = float(ch_opts.get('effective_end_pct') or 100.0)
            # 최소 작동 조건/양자화 격자 (%). 미설정=기본 5%, 0=비활성. (0 보존 위해 None 만 기본 처리)
            _ms = ch_opts.get('move_step_pct')
            move_step = float(_ms) if _ms not in (None, '') else 5.0
            # full_stroke_sec: 방향별 값의 평균, 하나만 있으면 그 값, 없으면 0 (slew 제한 비활성)
            t_open  = float(ch_opts.get('travel_time_open_sec')  or 0.0)
            t_close = float(ch_opts.get('travel_time_close_sec') or 0.0)
            if t_open > 0 and t_close > 0:
                full_stroke = (t_open + t_close) / 2.0
            else:
                full_stroke = t_open or t_close

            if azimuth_deg is None or area_m2 is None:
                try:
                    # [GB-6] 사망 컬럼 직접 조회 금지 — 리졸버 경유.
                    from aot.aot_flask.geo.device_binding import (
                        shapes_for_device)
                    rows = shapes_for_device(out_uuid)
                    shape = rows[0] if rows else None
                except Exception:
                    shape = None
                if shape and shape.feature:
                    az_shp, ar_shp = shape_azimuth_area(shape.feature)
                    if azimuth_deg is None and az_shp is not None:
                        azimuth_deg = az_shp
                    if area_m2 is None and ar_shp is not None and ar_shp > 0:
                        area_m2 = ar_shp

            k = {}
            if k_override:
                k_key = _K_PRIMARY.get(profile_kind)
                if k_key:
                    k[k_key] = k_override

            paired_cap_meta = {}
            rated_m3h_p = _KIND_DEFAULT_RATED_M3H.get(profile_kind, 0.0)
            if rated_m3h_p > 0:
                paired_cap_meta['rated_m3h'] = rated_m3h_p

            effect_model = build_effect_model(profile_kind, k)
            profile = ActuatorProfile(
                actuator_id=out_uuid,
                kind=profile_kind,
                capabilities=_KIND_CAPABILITIES.get(profile_kind, []),
                cost_fn=_build_cost_fn(profile_kind, cost, paired_cap_meta),
                response_sec=60.0,
                safe_default=_KIND_SAFE_DEFAULT.get(profile_kind, 0.0),
                manual_lock=ManualLockState(),
                effect_model=effect_model,
                cmd_constraints=CmdConstraints(
                    full_stroke_sec=full_stroke,
                    effective_start_pct=eff_start,
                    effective_end_pct=eff_end,
                    move_step_pct=move_step,
                ),
                slot_key='actuator_paired',
                azimuth_deg=azimuth_deg,
                area_m2=area_m2,
                capacity_meta=paired_cap_meta,
            )
            profiles.append(profile)
            by_id[out_uuid] = profile
            channel_map[out_uuid] = 0
            n_paired += 1

        if n_paired:
            self.logger.debug(
                '_reload_profiles: %d paired-actuator output(s) auto-discovered', n_paired)

        # ── 3. Manual env_actuator actions (merge or append) ─────────────────
        actions = db_retrieve_table_daemon(Actions).filter(
            Actions.function_id == self.unique_id,
            Actions.action_type == 'env_actuator',
        ).all()

        for action in actions:
            try:
                opts = json.loads(action.custom_options or '{}')
            except Exception:
                continue

            output_val = opts.get('output', '')
            if not output_val:
                continue
            parts = str(output_val).split(',')
            device_id  = parts[0].strip() if parts else ''
            channel_id = parts[1].strip() if len(parts) > 1 else None

            kind             = opts.get('kind', '') or ''
            cost             = float(opts.get('cost', 5.0) or 5.0)
            k_override       = float(opts.get('k_override', 0.0) or 0.0)
            full_stroke_sec  = float(opts.get('full_stroke_sec', 0.0) or 0.0)
            min_repeat_sec   = float(opts.get('min_repeat_sec', 0.0) or 0.0)
            # P2-3: safe_default_pct — 안전 게이트 발동 또는 E-stop 시 이동할 위치 (0~100%).
            # 0 = OFF. 예: 보온커튼 파킹 위치 50%, 차광막 열림 유지 100%.
            safe_default_pct = float(opts.get('safe_default_pct', 0.0) or 0.0)

            if not device_id or not kind:
                continue

            # 시설 경로와 같은 규칙을 수동 등록에도 적용한다. 여기서 빠뜨리면
            # 도면에서 제외한 분무기를 env_actuator 액션으로 되살릴 수 있어
            # 제외가 반쪽이 된다. 노즐 정보가 없으면 보수적으로 습윤형 취급.
            _prev = by_id.get(device_id)
            if _fog_excluded_from_env(
                    self, kind, (_prev.capacity_meta if _prev else None) or {}):
                self.logger.info(
                    '환경 제어 제외(수동 등록): %s (습윤형 분무 — 관수 전용으로 둠)',
                    device_id)
                continue

            ch_obj = 0
            if channel_id:
                try:
                    ch_obj = self.get_output_channel_from_channel_id(channel_id)
                except Exception:
                    ch_obj = 0

            k = {}
            if k_override:
                k_key = _K_PRIMARY.get(kind)
                if k_key:
                    k[k_key] = k_override

            effect_model = build_effect_model(kind, k)

            manual_cap_meta = {}
            rated_m3h_m = _KIND_DEFAULT_RATED_M3H.get(kind, 0.0)
            if rated_m3h_m > 0:
                manual_cap_meta['rated_m3h'] = rated_m3h_m
            # 차광포 투과율(0~1). 실내 광센서가 없을 때 실외 일사 + 차광막 개도로
            # 실내 광량을 추정하는 데 쓴다. 0 = 미설정(추정 안 함).
            shade_tr = float(opts.get('shade_transmittance', 0.0) or 0.0)
            if kind == 'shade' and 0.0 < shade_tr <= 1.0:
                manual_cap_meta['shade_transmittance'] = shade_tr

            # ── actuator_paired ch_opts 에서 effective range / travel time 읽기 ──
            # action 폼에는 이 값들이 없으므로 출력 채널 옵션에서 직접 조회한다.
            # merge 경우: 자동 발견에서 이미 채워진 값을 우선 사용하고,
            #             full_stroke_sec 는 action 폼 값이 0 이면 자동 발견값 유지.
            # new 경우: 출력이 actuator_paired 이면 ch_opts 에서 읽어 반영한다.
            existing = by_id.get(device_id)
            eff_start = 0.0
            eff_end   = 100.0
            # 최소 작동 조건/양자화 격자 (%). 우선순위: action 폼 > 기존(자동발견) > paired ch_opts > 기본 5%.
            # None = 미지정. 0 은 "비활성"으로 유효한 값이므로 보존한다.
            _ms_opt   = opts.get('move_step_pct')
            move_step = float(_ms_opt) if _ms_opt not in (None, '') else None

            if existing:
                # 자동 발견에서 설정된 effective range 보존
                eff_start = existing.cmd_constraints.effective_start_pct
                eff_end   = existing.cmd_constraints.effective_end_pct
                if move_step is None:
                    move_step = existing.cmd_constraints.move_step_pct
                # action 폼에서 full_stroke_sec 를 명시하지 않았으면 자동 발견값 유지
                if full_stroke_sec <= 0.0:
                    full_stroke_sec = existing.cmd_constraints.full_stroke_sec
            else:
                # 신규 프로필: actuator_paired 이면 ch_opts 에서 직접 읽음
                try:
                    from aot.databases.models import Output as _Output, OutputChannel as _OC
                    from aot.outputs.paired_actuator_common import (
                        PAIRED_ACTUATOR_OUTPUT_TYPES as _PAIRED_TYPES)
                    _out = _Output.query.filter_by(unique_id=device_id).first()
                    if _out and _out.output_type in _PAIRED_TYPES:
                        _ch = _OC.query.filter_by(output_id=device_id, channel=0).first()
                        if _ch:
                            _co = json.loads(_ch.custom_options or '{}')
                            eff_start = float(_co.get('effective_start_pct') or 0.0)
                            eff_end   = float(_co.get('effective_end_pct') or 100.0)
                            if move_step is None:
                                _ms_co = _co.get('move_step_pct')
                                if _ms_co not in (None, ''):
                                    move_step = float(_ms_co)
                            if full_stroke_sec <= 0.0:
                                _t_open  = float(_co.get('travel_time_open_sec')  or 0.0)
                                _t_close = float(_co.get('travel_time_close_sec') or 0.0)
                                if _t_open > 0 and _t_close > 0:
                                    full_stroke_sec = (_t_open + _t_close) / 2.0
                                else:
                                    full_stroke_sec = _t_open or _t_close
                except Exception:
                    pass

            if move_step is None:
                move_step = 5.0

            # 육묘 펄스 도징: 시설 도면에서 이미 노즐 정보를 받은 프로필이면
            # 그 습윤 판정을 그대로 쓰고, 수동 등록만 있으면 보수적으로 적용한다.
            _pulse_meta = (existing.capacity_meta if existing else None) or manual_cap_meta
            cmd_constraints = CmdConstraints(
                full_stroke_sec=full_stroke_sec,
                min_dwell_sec=min_repeat_sec if min_repeat_sec > 0 else 30.0,
                effective_start_pct=eff_start,
                effective_end_pct=eff_end,
                move_step_pct=move_step,
                **_fog_pulse_constraints(self, kind, _pulse_meta),
            )

            if existing:
                existing.cost_fn = _build_cost_fn(kind, cost,
                                                  existing.capacity_meta or manual_cap_meta)
                existing.effect_model = effect_model
                existing.cmd_constraints = cmd_constraints
                existing.safe_default = safe_default_pct   # P2-3: 덮어쓰기
                # 시설 도면에서 자동 발견된 프로필은 capacity_meta 가 이미 채워져
                # 있어 통째로 교체하지 않는다. 다만 action 폼에서만 들어오는 값
                # (차광포 투과율)은 병합해야 유실되지 않는다.
                if 'shade_transmittance' in manual_cap_meta:
                    if existing.capacity_meta is None:
                        existing.capacity_meta = {}
                    existing.capacity_meta['shade_transmittance'] = \
                        manual_cap_meta['shade_transmittance']
                channel_map[device_id] = ch_obj
                n_manual_merged += 1
            else:
                profile = ActuatorProfile(
                    actuator_id=device_id,
                    kind=kind,
                    capabilities=_KIND_CAPABILITIES.get(kind, []),
                    cost_fn=_build_cost_fn(kind, cost, manual_cap_meta),
                    response_sec=60.0,
                    safe_default=safe_default_pct,          # P2-3
                    manual_lock=ManualLockState(),
                    effect_model=effect_model,
                    cmd_constraints=cmd_constraints,
                    capacity_meta=manual_cap_meta,
                )
                profiles.append(profile)
                by_id[device_id] = profile
                channel_map[device_id] = ch_obj
                n_manual_new += 1

        # ── 4. P2-4: 복합 액추에이터 그룹 파싱 ───────────────────────────────────
        # 이슈 D: integ 페이로드의 groups + actuators_slot_map 을 사용하여
        # GeoFacility 재조회를 제거. integ 가 None 이면 그룹도 비어 있음.
        groups: list = []
        if facility_uuid and integ:
            try:
                fac_groups = integ.get('groups') or {}
                raw_acts   = integ.get('actuators_slot_map') or {}
                if isinstance(fac_groups, dict) and fac_groups:
                    for gid, gcfg in fac_groups.items():
                        mode        = gcfg.get('mode', 'symmetric')
                        leader_slot = gcfg.get('leader', '')
                        member_slots = gcfg.get('members', [leader_slot])
                        thr         = float(gcfg.get('threshold_pct', 50.0))
                        # slot_key 조회 실패 시 값 자체를 UUID로 직접 사용 (fallback)
                        leader_id   = raw_acts.get(leader_slot, '') or leader_slot
                        member_ids  = [raw_acts.get(s, '') or s for s in member_slots
                                       if (raw_acts.get(s, '') or s)]
                        if leader_id and len(member_ids) >= 2:
                            groups.append(ActuatorGroup(
                                group_id=gid, mode=mode,
                                leader_id=leader_id, member_ids=member_ids,
                                threshold_pct=thr,
                            ))
                    if groups:
                        self.logger.debug(
                            '_reload_profiles: %d 그룹 로드됨', len(groups))
            except Exception:
                self.logger.exception(
                    '_reload_profiles: 그룹 파싱 실패 — 그룹 없이 계속')

        # bay_scope 시 구성원 전원이 bay 안에 있는 그룹만 유지 — 리더 명령이
        # group_expander 를 통해 bay 밖 팔로워로 확장되는 것을 차단한다.
        if getattr(self, '_bay_scope_active', None) and groups:
            _registered = {p.actuator_id for p in profiles}
            _kept = [g for g in groups
                     if g.leader_id in _registered
                     and all(m in _registered for m in g.member_ids)]
            if len(_kept) != len(groups):
                self.logger.info(
                    '_reload_profiles: bay_scope "%s" — %d/%d group(s) kept '
                    '(groups spanning other bays excluded)',
                    self._bay_scope_active, len(_kept), len(groups))
            groups = _kept

        self._groups = groups

        # ── 5. 팔로워 전용 프로파일 제거 (coordinator 는 리더만 처리) ─────────────
        follower_ids: set = set()
        for grp in groups:
            follower_ids.update(grp.follower_ids())
        leader_profiles = [p for p in profiles if p.actuator_id not in follower_ids]

        self._profiles    = leader_profiles
        self._channel_map = channel_map
        self._actuator_idx = {p.actuator_id: i for i, p in enumerate(leader_profiles)}
        self._by_id       = by_id   # _dispatch deadband 에서 CmdConstraints 참조용

        # ── Stage 0/P0: 어댑터 맵 빌드 (장치 output_types → DispatchAdapter) ──
        # by_id 는 leader + follower 모두 포함 → 팔로워도 직접 dispatch 할 때 필요.
        try:
            from aot.functions.utils.env_control.dispatch_adapters import build_adapter_map
            self._adapter_by_id = build_adapter_map(by_id)
            self.logger.debug(
                '_reload_profiles: adapter map built (%d entries)', len(self._adapter_by_id))
        except Exception as _ae:
            self._adapter_by_id = {}
            self.logger.warning(
                '_reload_profiles: adapter map build failed — value passthrough 사용: %s', _ae)

        self.logger.debug(
            '_reload_profiles: total=%d (facility=%d, paired=%d, '
            'manual_new=%d, manual_merged=%d, groups=%d)',
            len(leader_profiles), n_facility, n_paired,
            n_manual_new, n_manual_merged, len(groups))

        # ── Commissioning bridge: consume pending calibration anchors ─────────
        if facility_uuid:
            self._apply_pending_commissioning_anchors(facility_uuid)

    def _apply_pending_commissioning_anchors(self, facility_uuid: str) -> None:
        """Read unconsumed commissioning_state anchors and inject into calibration.

        Anchors written by the device check wizard (verdict='ok') seed each
        RLSCalibrator's k_hat with the measured value so the CalibrationRegistry
        gains a trusted K baseline immediately. sensor_suspect flags also force
        ActuatorFeedbackRegistry trust_score to its floor.

        Variable naming: the wizard records var='T'|'RH'|'CO2' but the
        RLSCalibrator slots are keyed by 'temperature'|'humidity'|'co2'. We
        translate at read time.
        """
        _VAR_MAP = {'T': 'temperature', 'RH': 'humidity', 'CO2': 'co2'}

        # Build actuator_id → kind map from currently loaded profiles
        kind_by_id = {p.actuator_id: p.kind for p in self._profiles}

        try:
            from aot.databases.models import GeoFacility
            from aot.config import AOT_DB_PATH
            from aot.databases.utils import session_scope
            from sqlalchemy.orm.attributes import flag_modified

            with session_scope(AOT_DB_PATH) as sess:
                facility = sess.query(GeoFacility).filter_by(
                    unique_id=facility_uuid).first()
                if facility is None:
                    return
                state = dict(facility.commissioning_state or {})
                if not state.get('pending_anchors'):
                    # Still apply sensor_suspect flags (idempotent, fast)
                    self._apply_sensor_suspect_flags(state.get('commissioning_flags', {}))
                    return

                anchors = list(state.get('calibration_anchors', []))
                consumed_count = 0
                for anchor in anchors:
                    if anchor.get('consumed'):
                        continue
                    aid    = anchor.get('actuator_id', '')
                    var_in = anchor.get('var', '')
                    k      = anchor.get('k_measured')
                    var_internal = _VAR_MAP.get(var_in, var_in)
                    kind   = kind_by_id.get(aid)

                    if aid and var_internal and kind and k is not None:
                        cal = self._cal_registry.get_or_create(aid, kind)
                        rls = cal._rls.get(var_internal) if cal else None
                        if rls is not None:
                            # Seed k_hat with measured value as trusted anchor
                            rls.k_hat = float(k)
                            rls.n_updates = max(rls.n_updates, 5)
                            rls._P = min(rls._P, 0.1)   # reduce variance → high confidence
                    anchor['consumed'] = True
                    consumed_count += 1

                # Apply sensor_suspect flags
                self._apply_sensor_suspect_flags(state.get('commissioning_flags', {}))

                if consumed_count:
                    state['calibration_anchors'] = anchors
                    state['pending_anchors'] = False
                    facility.commissioning_state = state
                    flag_modified(facility, 'commissioning_state')
                    sess.commit()
                    self.logger.info(
                        'commissioning: applied %d calibration anchor(s) '
                        'from facility %s', consumed_count, facility_uuid)
        except Exception as exc:
            self.logger.debug('commissioning anchor apply failed: %s', exc)

    def _apply_sensor_suspect_flags(self, flags: dict) -> None:
        """Drop trust_score to floor for actuators flagged as sensor_suspect."""
        for aid, flag_val in (flags or {}).items():
            if flag_val == 'sensor_suspect':
                fb = self._feedback_registry._records.get(aid)
                if fb and fb.trust_score > 0.1:
                    fb.trust_score = 0.1
                    fb.mismatch_count += 10
