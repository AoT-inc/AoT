# coding=utf-8
"""
facility_integration.py — get_facility_integration(): shared IEC integration helper.

Called by:
  - routes_geo.py  → GET /api/geo/facility/<uuid>/integration  (B1 HTTP endpoint)
  - _profile_loader_mixin.py → _reload_profiles() section 1   (B2 profile builder)

Returns the same normalized dict in both contexts so the HTTP route is just a thin
JSON wrapper around this function.

TTL cache (#6): structural config (fittings, actuators, sensors) changes rarely.
A 30-second in-memory cache reduces redundant DB round-trips for rapid status
polling (5-second widget) and concurrent HTTP calls.
Call invalidate_facility_integration_cache(uuid) after any facility write.
"""
import threading
import time as _time

from aot.databases.models import Output, Input, DeviceMeasurements
from .facility_io import FacilityManager
from .facility_calc import compute_capacity
from .facility_bays import compute_bay_slices, build_fitting_bay_map
from .irrigation_nozzles import nozzles_by_actuator, summarize_nozzles

# ── TTL cache ─────────────────────────────────────────────────────────────────
_INTEG_CACHE_TTL  = 30          # seconds
_INTEG_CACHE: dict = {}         # {facility_uuid: (result_dict, ts)}
_INTEG_CACHE_LOCK = threading.Lock()


def invalidate_facility_integration_cache(facility_uuid=None):
    """Evict one or all entries from the integration TTL cache.

    Call after any write that modifies facility structure (fittings, actuators,
    sensors).  Pass facility_uuid=None to clear the entire cache.
    """
    with _INTEG_CACHE_LOCK:
        if facility_uuid is None:
            _INTEG_CACHE.clear()
        else:
            _INTEG_CACHE.pop(facility_uuid, None)

# DeviceMeasurements.measurement 이름 → measurement_type 자동 추론 매핑.
# 사용자가 facility 센서 피팅에서 measurement_type을 명시하지 않아도
# 시스템이 측정 이름 메타데이터를 토대로 자동으로 분류한다.
_DM_NAME_TO_MTYPE = {
    'temperature': 'temperature', 'temp': 'temperature',
    'humidity': 'humidity', 'relative_humidity': 'humidity', 'rh': 'humidity',
    'co2': 'co2', 'carbon_dioxide': 'co2', 'co2_ppm': 'co2',
    # 'vapor_' 는 미국식 철자. Mycodo 의 실제 measurement 값이 이쪽이라
    # 영국식('vapour_')만 있던 동안 VPD 채널은 하나도 매핑되지 않았다.
    'vpd': 'vpd', 'vapour_pressure_deficit': 'vpd',
    'vapor_pressure_deficit': 'vpd', 'auto_vpd': 'vpd',
    'speed': 'wind_speed', 'wind': 'wind_speed', 'wind_speed': 'wind_speed',
    'windspeed': 'wind_speed', 'wind_ms': 'wind_speed',
    'direction': 'wind_direction', 'wind_direction': 'wind_direction',
    'wind_dir': 'wind_direction', 'wind_bearing': 'wind_direction',
    'radiation': 'light', 'solar': 'light', 'lux': 'light', 'light': 'light',
    'par': 'light', 'ppfd': 'light', 'illuminance': 'light',
    'pressure': 'pressure', 'atm': 'pressure', 'atmospheric_pressure': 'pressure',
    'rain': 'rain', 'rainfall': 'rain', 'rainrate': 'rain', 'rain_rate': 'rain',
    'precipitation': 'rain', 'length': 'rain', 'depth': 'rain',
    # 메타 채널(장치 자신의 상태). DB 의 measurement_type 은 거의 항상 비어 있어
    # measurement 이름으로만 잡힌다 — 이 세 줄이 없으면 facility_sensors 의
    # _MTYPE_KEY 에 rssi/snr/battery 를 넣어도 실제 채널이 거기 닿지 않는다.
    'rssi': 'rssi', 'snr': 'snr', 'battery': 'battery',
}


# 장치를 고르면 자동으로 채워도 되는 종류 (환경값만).
# `_DM_NAME_TO_MTYPE` 에는 rssi/snr/battery 같은 **메타 채널**과 pressure 도
# 있는데, 그것들은 사용자가 "센서로 쓴다" 고 고른 대상이 아니다. 자동으로
# 끌어오면 고르지도 않은 채널이 센서 목록에 나타난다.
_AUTO_RESOLVABLE_MTYPES = frozenset({
    'temperature', 'humidity', 'co2', 'vpd',
    'light', 'wind_speed', 'wind_direction', 'rain',
})


def auto_channels_for_device(dm_rows, explicit_types):
    """고른 장치에서 아직 안 묶인 종류 중, 후보가 **하나뿐인** 것들.

    사용자는 화면에서 "이 장치를 실내/실외 센서로 쓴다" 를 고른다. 그런데
    백엔드가 체크된 채널만 읽으면, 기상대를 실외 센서로 지정해도 그때 체크된
    채널 하나만 살고 나머지는 없는 셈이 된다 — 그리고 없으면 조용히 지어냈다.
    장치 이름이 무엇이든 uuid + 채널로 해석할 수 있는 정보다.

    ⚠ **모호하면 채우지 않는다.** 같은 종류의 채널이 둘 이상인 장치(예:
    temp1f~temp6f 를 한꺼번에 내보내는 기상 콘솔)에서 전부 끌어오면 서로 다른
    자리의 값이 한 평균으로 섞인다. 그건 사용자가 골라야 할 판단이다.

    Args:
        dm_rows:        그 장치의 DeviceMeasurements 행들
        explicit_types: 사용자가 이미 명시한 measurement_type 집합 (이쪽이 이긴다)

    Returns:
        [{measurement_id, measurement_type, auto: True}, …]
    """
    by_type = {}
    for r in dm_rows or []:
        mt = _infer_mtype_from_dm(r)
        if (mt and mt in _AUTO_RESOLVABLE_MTYPES
                and mt not in (explicit_types or set())):
            by_type.setdefault(mt, []).append(r)
    return [{'measurement_id': rows[0].unique_id,
             'measurement_type': mt, 'auto': True}
            for mt, rows in sorted(by_type.items()) if len(rows) == 1]


def _infer_mtype_from_dm(dm_row):
    """DeviceMeasurements 행에서 measurement_type을 자동 추론한다."""
    if dm_row is None:
        return None
    name_key = (dm_row.measurement or '').lower().strip()
    return _DM_NAME_TO_MTYPE.get(name_key)


# Fitting.kind → ActuatorProfile.kind 추론 (slot_key 미설정 시 fallback).
# 모호한 케이스(fan: circulation/exhaust/intake)는 None 으로 두어
# 로더가 slot 또는 명시 actuator_kind 를 사용하도록 한다.
# 관수 계열(irrigation_layer/irrigation_valve)은 노즐 구성에 따라 fogger 가
# 되기도 하고 env 대상이 아니기도 하므로 표에 두지 않고 동적으로 해석한다
# (_irrigation_actuator_kind 참조).
_FITTING_KIND_TO_ACTUATOR_KIND = {
    'window':            'opening',
    'side_window':       'opening',
    'door':              'opening',
    'curtain':           'curtain',
    'shade_curtain':     'shade',
    # 설비(Fixtures) 팔레트로 배치하는 실내 장치. 디자이너는 이 종류들을
    # 배치하고 Output 까지 물릴 수 있는데(geo_facility.html 배치 버튼 + 인스펙터
    # 종류 드롭다운) 이 표에 없으면 _fitting_actuator_kind 가 None 을 돌려줘
    # 통합환경제어가 조용히 버린다 — 사용자는 가습기를 붙여 놨는데 등록이 안 된다
    # (2026-07-31 aot-005 육묘장: '관수: 미니스프링클러'가 fogger 피팅으로
    #  바인딩돼 있었으나 등록되지 않아, VPD 를 낮출 액추에이터가 하나도 없었다).
    'fogger':            'fogger',
    'heater':            'heater',
    'cooler':            'cooler',
    'co2_injector':      'co2_injector',
    'lighting':          'lighting',
}

# 관수 계열 피팅/ActuatorUI kind — 노즐 구성으로 env 등록 여부를 판정한다.
_IRRIGATION_KINDS = frozenset({'irrigation_layer', 'irrigation_valve'})

# 제너릭 'fan' 피팅의 세부 역할(순환/배기/흡기) 후보.
_FAN_ROLE_KINDS = frozenset({'circulation_fan', 'exhaust_fan', 'intake_fan'})


def _irrigation_actuator_kind(nozzle_summary):
    """관수 액추에이터의 노즐 요약 → env_control ActuatorProfile.kind.

    분무 노즐(sprinkler)이 하나라도 달려 있으면 그 밸브·펌프는 실내 습도를
    직접 올릴 수 있으므로 'fogger' 로 등록한다. 드립 전용이면 잎·공기에 물이
    닿지 않아 환경 액추에이터가 아니므로 None(등록 제외).

    2026-07-31 이전에는 관수 밸브가 무조건 등록 제외였다. 그래서 통합환경제어
    쪽에 VPD 를 낮출 수 있는 액추에이터가 하나도 잡히지 않았고, VPD 관리를
    별도 PID Function 으로 분리해 운영할 수밖에 없었다.
    """
    if not nozzle_summary:
        return None
    return 'fogger' if nozzle_summary.get('sprinkler_count') else None


def _fitting_actuator_kind(fitting, nozzle_map=None):
    """피팅(fitting) → env_control ActuatorProfile.kind 추론.

    제너릭 'fan' 피팅은 자체로 순환/배기/흡기를 구분하지 못하므로 인스펙터에서
    지정한 fitting.fan_role 을 사용한다 (미지정 시 circulation_fan 으로 안전 기본).
    관수 계열은 nozzle_map(액추에이터별 노즐 요약)으로 판정한다.
    그 외 종류는 _FITTING_KIND_TO_ACTUATOR_KIND 표를 따른다.
    """
    fk = fitting.get('kind')
    if fk == 'fan':
        role = fitting.get('fan_role') or 'circulation_fan'
        return role if role in _FAN_ROLE_KINDS else 'circulation_fan'
    if fk in _IRRIGATION_KINDS:
        return _irrigation_actuator_kind(
            (nozzle_map or {}).get(fitting.get('actuator_id')))
    return _FITTING_KIND_TO_ACTUATOR_KIND.get(fk)


def get_facility_integration(facility_uuid, bypass_cache=False):
    """Build the unified IEC payload for *facility_uuid*.

    Returns ``(result_dict, error_str)``.  On success ``error_str`` is None.

    result_dict keys
    ----------------
    facility_uuid, name, geometry_3d, envelope, fittings,
    actuators_resolved, sensors_resolved, vent_openings, capacity_meta, computed.

    actuators_resolved
    ------------------
    One entry per Output uuid (union of slot_map + fitting.actuator_id bindings):
      output_uuid, output_name, output_type, slot_key, kind, capabilities,
      fitting_ids[], vent_openings_area_m2, vent_openings_count.

    G1 policy: vent area in vent_openings_area_m2 is derived from fittings when
    fittings are present; computed.vent_open_source indicates the authority.

    bypass_cache=True forces a fresh DB read (used by cmd_reload path).
    """
    # ── TTL cache check ───────────────────────────────────────────────────────
    if not bypass_cache:
        with _INTEG_CACHE_LOCK:
            entry = _INTEG_CACHE.get(facility_uuid)
            if entry is not None:
                cached_result, ts = entry
                if _time.time() - ts < _INTEG_CACHE_TTL:
                    return cached_result, None

    # Lazy import to avoid circular dependency at module load time.
    from aot.functions.custom_functions.env_coordinator_impl._function_info import (
        _FACILITY_SLOT_KIND, _KIND_CAPABILITIES, _ACTUATOR_UI_KIND_TO_KIND,
    )

    facility, error = FacilityManager.get_facility(facility_uuid)
    if error:
        return None, error

    fittings_raw = facility.get('fittings') or []
    fittings = fittings_raw if isinstance(fittings_raw, list) else []

    # 관수 노즐 배치 → 액추에이터별 엽면 습윤 특성. 액추에이터 해석(3단계)보다
    # 먼저 계산해야 관수 밸브의 kind(fogger 여부)를 판정할 수 있다.
    nozzle_map = nozzles_by_actuator(fittings)

    # facility['actuators'] 는 두 가지 형태로 저장된다:
    #   - 레거시 dict {slot_key: output_uuid}            → slot_map 경로
    #   - 현행 list  [{kind, device_uuid, specs, ...}]   → actuator_list 경로 (ActuatorUI)
    # 과거에는 dict 만 처리해 list 형(현행 디자이너 저장본)이 통째로 무시됐고,
    # 그 결과 ActuatorUI 로 등록한 팬 등 액추에이터가 env_coordinator 에 전달되지 않았다.
    actuators_raw = facility.get('actuators')
    if isinstance(actuators_raw, list):
        actuator_list = actuators_raw
        slot_map = {}
    elif isinstance(actuators_raw, dict):
        actuator_list = []
        slot_map = actuators_raw
    else:
        actuator_list = []
        slot_map = {}

    # --- 1. Compute capacity (authoritative numbers + vent_openings per G1) ---
    spec_for_calc = {
        'outer_geometry': (facility.get('outer_feature') or {}).get('geometry'),
        'bay_count':   facility.get('bay_count') or 1,
        'structure':   facility.get('structure') or 'single',
        'geometry_3d': facility.get('geometry_3d') or {},
        'envelope':    facility.get('envelope') or {},
        # compute_capacity()/_aggregate_actuators() 는 list·dict 양형을 모두 처리하므로
        # 원본을 그대로 넘긴다 (list 형도 풍량·용량 집계에 반영되도록).
        'actuators':   actuators_raw if isinstance(actuators_raw, (list, dict)) else {},
        'fittings':    fittings,
    }
    try:
        computed = compute_capacity(spec_for_calc)
    except Exception:
        computed = {}

    # --- 2. Resolve Output devices (single bulk query) ---
    output_uuids = set()
    for u in slot_map.values():
        if u:
            output_uuids.add(u)
    for act in actuator_list:
        if act.get('device_uuid'):
            output_uuids.add(act['device_uuid'])
    for f in fittings:
        if f.get('actuator_id'):
            output_uuids.add(f['actuator_id'])

    out_rows = (Output.query.filter(Output.unique_id.in_(output_uuids)).all()
                if output_uuids else [])
    out_lookup = {r.unique_id: r for r in out_rows}

    # --- 3. Build actuators_resolved ---
    # First pass: slot_map entries carry the authoritative slot_key → kind mapping.
    actuators_resolved = {}
    for slot_key, output_uuid in slot_map.items():
        if not output_uuid:
            continue
        kind = _FACILITY_SLOT_KIND.get(slot_key)
        row = out_lookup.get(output_uuid)
        actuators_resolved[output_uuid] = {
            'output_uuid':           output_uuid,
            'output_name':           (row.name if row else None) or 'Output',
            'output_type':           (row.output_type if row else ''),
            'slot_key':              slot_key,
            'kind':                  kind,
            'capabilities':          _KIND_CAPABILITIES.get(kind, []) if kind else [],
            'fitting_ids':           [],
            'vent_openings_area_m2': 0.0,
            'vent_openings_count':   0,
        }

    # List-form actuators (ActuatorUI 인스턴스). 장비 단위 kind 를 env_control
    # ActuatorProfile.kind 로 정규화하고, specs.airflow_cmh 를 rated_m3h(팬 풍량)로
    # 전달한다. dict slot 으로도 등록된 동일 output 이 있으면 list 쪽을 우선한다
    # (디자이너 현행 저장본이 권위).
    for act in actuator_list:
        output_uuid = act.get('device_uuid')
        if not output_uuid:
            continue
        ui_kind = act.get('kind')
        if ui_kind in _IRRIGATION_KINDS:
            # 관수 밸브·펌프: 노즐 구성이 분무면 fogger, 드립 전용이면 제외.
            kind = _irrigation_actuator_kind(nozzle_map.get(output_uuid))
        else:
            kind = _ACTUATOR_UI_KIND_TO_KIND.get(ui_kind, ui_kind)
        if not kind:
            continue   # 드립 전용 관수 밸브 등 — env 액추에이터 아님
        row = out_lookup.get(output_uuid)
        specs = act.get('specs') or {}
        entry = {
            'output_uuid':           output_uuid,
            'output_name':           (row.name if row else None) or 'Output',
            'output_type':           (row.output_type if row else ''),
            'slot_key':              ui_kind,
            'kind':                  kind,
            'capabilities':          _KIND_CAPABILITIES.get(kind, []),
            'fitting_ids':           [],
            'vent_openings_area_m2': 0.0,
            'vent_openings_count':   0,
        }
        airflow_cmh = specs.get('airflow_cmh')
        if airflow_cmh not in (None, ''):
            try:
                entry['rated_m3h'] = float(airflow_cmh)
            except (TypeError, ValueError):
                pass
        actuators_resolved[output_uuid] = entry

    # Index vent_openings by actuator_id for fast area aggregation.
    vent_openings = computed.get('vent_openings') or []
    openings_by_actuator = {}
    for op in vent_openings:
        aid = op.get('actuator_id')
        if aid:
            openings_by_actuator.setdefault(aid, []).append(op)

    # Second pass: attach fitting ids; synthesize slot-less Output entries.
    # G1 정책: slot_key 가 없어도 fitting.kind 로부터 ActuatorProfile.kind 를
    # 추론할 수 있으면 채워서 로더가 등록할 수 있도록 한다.
    for f in fittings:
        aid = f.get('actuator_id')
        if not aid:
            continue
        if aid not in actuators_resolved:
            row = out_lookup.get(aid)
            inferred_kind = _fitting_actuator_kind(f, nozzle_map)
            actuators_resolved[aid] = {
                'output_uuid':           aid,
                'output_name':           (row.name if row else None) or 'Output',
                'output_type':           (row.output_type if row else ''),
                'slot_key':              None,
                'kind':                  inferred_kind,
                'capabilities':          (_KIND_CAPABILITIES.get(inferred_kind, [])
                                          if inferred_kind else []),
                'fitting_ids':           [],
                'vent_openings_area_m2': 0.0,
                'vent_openings_count':   0,
            }
        else:
            # 이미 slot 으로 등록된 액추에이터에 추가 fitting 이 붙은 경우 —
            # kind 가 None 이면 fitting kind 로 보강.
            entry = actuators_resolved[aid]
            if not entry.get('kind'):
                inferred = _fitting_actuator_kind(f, nozzle_map)
                if inferred:
                    entry['kind'] = inferred
                    entry['capabilities'] = _KIND_CAPABILITIES.get(inferred, [])
        actuators_resolved[aid]['fitting_ids'].append(f.get('id'))

    # Third pass: aggregate vent area per actuator from G1-resolved vent_openings.
    for aid, ops in openings_by_actuator.items():
        if aid in actuators_resolved:
            actuators_resolved[aid]['vent_openings_area_m2'] = round(
                sum(o['area_m2'] for o in ops), 3)
            actuators_resolved[aid]['vent_openings_count'] = len(ops)

    # --- 4. Resolve sensors (indoor / outdoor split by sensor_role) ---
    # sensor_role 미설정 fitting은 'indoor'로 간주 (하위 호환).
    sensor_fittings = [f for f in fittings if f.get('kind') == 'sensor']
    input_uuids = {f['input_id'] for f in sensor_fittings if f.get('input_id')}
    inp_rows = (Input.query.filter(Input.unique_id.in_(input_uuids)).all()
                if input_uuids else [])
    inp_lookup = {r.unique_id: r for r in inp_rows}

    # measurement_id 전체 수집 → DeviceMeasurements 배치 조회 (measurement_type 자동 추론용)
    all_meas_ids = set()
    for f in sensor_fittings:
        for ch in (f.get('channel_measurements') or []):
            mid = ch.get('measurement_id')
            if mid:
                all_meas_ids.add(mid)
        if f.get('measurement_id'):
            all_meas_ids.add(f['measurement_id'])
    dm_lookup = {}
    if all_meas_ids:
        dm_rows = DeviceMeasurements.query.filter(
            DeviceMeasurements.unique_id.in_(all_meas_ids)).all()
        dm_lookup = {r.unique_id: r for r in dm_rows}

    # ── 고른 장치의 나머지 채널을 자동 해석한다 (2026-08-26) ────────────────────
    # 사용자는 화면에서 **"이 장치를 실내/실외 센서로 쓴다"** 를 고른다. 그런데
    # 백엔드는 체크된 채널만 읽었다 — 기상대를 실외 센서로 지정해도 그때 체크된
    # 채널 하나만 살고 나머지는 없는 셈이 됐다. 그리고 없으면 조용히 지어냈다
    # (`ext_context_fallback` 이 실외=실내로 채운다). 실측(2026-08-26 イチゴ):
    # 기상대에 `light` 만 묶여 온도·습도·풍속·풍향이 전부 null 이었고, 그 위에서
    # 환기 무익 판정이 서서 창이 닫히고 풍향 0°(정북)로 측창이 영구 leeward 였다.
    # 장치 이름이 무엇이든 uuid + 채널로 해석할 수 있는 정보였다.
    #
    # ⚠ **모호하면 자동 해석하지 않는다.** 같은 종류의 채널이 둘 이상인 장치
    # (예: temp1f~temp6f 를 한꺼번에 내보내는 기상 콘솔)에서 전부 끌어오면 서로
    # 다른 자리의 값이 한 평균으로 섞인다. 그건 사용자가 골라야 할 판단이라
    # 정확히 하나일 때만 채운다. 명시 선택은 언제나 이긴다.
    dm_by_device = {}
    if input_uuids:
        for r in DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id.in_(input_uuids)).all():
            dm_by_device.setdefault(r.device_id, []).append(r)

    def _auto_channels(iid, explicit_types):
        if not iid:
            return []
        return auto_channels_for_device(dm_by_device.get(iid, []), explicit_types)

    def _explicit_list(f):
        """이 fitting 에서 사용자가 **직접 고른** 채널 목록."""
        ch_list = f.get('channel_measurements') or []
        if not ch_list and f.get('measurement_id'):
            ch_list = [{'measurement_id': f['measurement_id'],
                        'measurement_type': f.get('measurement_type') or None}]
        return list(ch_list)

    def _types_of(ch_list):
        out = set()
        for ch in ch_list:
            mt = ch.get('measurement_type') or _infer_mtype_from_dm(
                dm_lookup.get(ch.get('measurement_id')))
            if mt:
                out.add(mt)
        return out

    # ── 명시 선택은 **역할 전체에서** 이긴다 (2026-08-26) ──────────────────────
    # 처음에는 fitting 하나 안에서만 "이미 고른 종류" 를 셌는데, 그러면 센서를
    # 둘로 나눠 단 설치에서 자동 해석이 남의 몫까지 끌어온다. 실측(イチゴ):
    #
    #   気象台1  [temperature, humidity, wind_speed, wind_direction]  ← 직접 선택
    #   気象台2  [light, rain]                                        ← 직접 선택
    #
    # 여기서 気象台2 의 자동 해석이 온도·습도·바람을 또 올려, read_outdoor_sensors
    # 가 두 장치를 **평균**했다 — 풍속 7.2 와 1.92 가 4.56 이 되고, 사용자가
    # 직접 고른 값이 조용히 희석된다. 여러 센서를 일부러 평균하는 것은 정상
    # 기능이지만(가중평균), 그것은 **사용자가 그렇게 고를 때**의 이야기다.
    _explicit_by_fitting = {id(f): _explicit_list(f) for f in sensor_fittings}
    _explicit_by_role = {}
    for f in sensor_fittings:
        r = f.get('sensor_role') or 'indoor'
        _explicit_by_role.setdefault(r, set()).update(
            _types_of(_explicit_by_fitting[id(f)]))

    sensors_resolved = []   # 실내 (공간 평균 계산, env_coordinator 내부 센서 보완)
    sensors_outdoor  = []   # 실외 (T_ext / RH_ext / 풍속·풍향·일사)
    sensors_forecast = []   # 기상 예보 Input 장치 바인딩 (weather_bindings 컬럼에서 로드)
    _auto_taken = {}        # 역할별로 자동 해석이 이미 채운 종류 (중복 방지)
    for f in sensor_fittings:
        iid  = f.get('input_id')
        row  = inp_lookup.get(iid) if iid else None
        role = f.get('sensor_role') or 'indoor'

        ch_list = _explicit_by_fitting[id(f)]
        # 같은 역할에서 누가 직접 고른 종류, 그리고 앞선 fitting 이 자동으로
        # 채운 종류는 다시 채우지 않는다. 장치가 여럿이어도 자동 해석은 한 번만.
        _taken = _explicit_by_role.get(role, set()) | _auto_taken.setdefault(role, set())
        _auto = _auto_channels(iid, _taken)
        _auto_taken[role].update(
            c['measurement_type'] for c in _auto if c.get('measurement_type'))
        ch_list = ch_list + _auto

        for ch in ch_list:
            mid   = ch.get('measurement_id') or None
            mtype = ch.get('measurement_type') or None
            # measurement_type 미설정 시 DeviceMeasurements.measurement 이름으로 자동 추론
            if not mtype and mid:
                mtype = _infer_mtype_from_dm(dm_lookup.get(mid))
            entry = {
                'fitting_id':       f.get('id'),
                'name':             f.get('name') or '',
                'position':         f.get('position'),
                'sensor_role':      role,
                'measurement_type': mtype,
                'input_uuid':       iid,
                'measurement_id':   mid,
                'input_name':       (row.name if row else None),
                'input_device':     (row.device if row else None),
                # 사용자가 직접 고른 채널인가, 장치에서 자동으로 해석한 것인가.
                # 화면이 "자동" 을 표시할 수 있어야 사용자가 무엇이 어떻게 읽히는지
                # 안다 — 자동 해석을 조용히 하면 지어내던 것과 같은 문제가 된다.
                'auto':             bool(ch.get('auto')),
            }
            if role == 'outdoor':
                sensors_outdoor.append(entry)
            else:
                sensors_resolved.append(entry)

    # --- 4b. Weather / forecast bindings (weather_bindings 컬럼) ---
    # 사용자가 Facility > 기상탭에서 연결한 예보 Input 장치들.
    # measurement_type 으로 어떤 예보 채널인지 식별. read_forecast_sensors() 가 소비.
    for wb in (facility.get('weather_bindings') or []):
        mtype   = (wb.get('measurement_type') or '').strip()
        iid     = (wb.get('input_uuid') or '').strip()
        meas_id = (wb.get('measurement_id') or '').strip()
        if not mtype or not iid or not meas_id:
            continue
        sensors_forecast.append({
            'measurement_type': mtype,
            'input_uuid':       iid,
            'measurement_id':   meas_id,
            'name':             wb.get('name') or mtype,
        })

    # --- 5a. Irrigation summary (관수 시스템 유량 집계) ---
    # fittings 안의 irrigation_layer / irrigation_pipe / irrigation_device 를
    # 레이어별로 묶어 IEC 통합 데이터에 포함시킨다. 압력/유량 제어 알고리즘이
    # 이 집계값을 받아 펌프 토출량 / 노즐 사이클을 계산할 수 있다.
    import math as _math
    irr_layers = [f for f in fittings if f.get('kind') == 'irrigation_layer']
    irr_pipes  = [f for f in fittings if f.get('kind') == 'irrigation_pipe']
    irr_devs   = [f for f in fittings if f.get('kind') == 'irrigation_device']

    def _seg_xz_len(seg):
        try:
            fr, to = seg.get('from') or [0,0,0], seg.get('to') or [0,0,0]
            return _math.sqrt((to[0]-fr[0])**2 + (to[2]-fr[2])**2)
        except Exception:
            return 0.0

    irrigation_summary = {'layers': [], 'totals': {'length_m':0.0,'emitters':0,'flow_lph':0.0,'flow_lpm':0.0}}
    for L in irr_layers:
        lid = L.get('id')
        layer_pipes = [p for p in irr_pipes if p.get('layer_id') == lid and not p.get('is_vertical')]
        layer_devs  = [d for d in irr_devs  if d.get('layer_id') == lid]
        pipes_out = []
        layer_total_len = 0.0
        layer_total_emt = 0
        layer_total_lph = 0.0
        for idx, p in enumerate(layer_pipes):
            segs = p.get('segments') or []
            length = round(sum(_seg_xz_len(s) for s in segs), 2)
            connected_devs = [d for d in layer_devs if d.get('pipe_id') == p.get('id')]
            emt = len(connected_devs)
            lph = round(sum(float(d.get('flow_lph') or 0) for d in connected_devs), 1)
            pipes_out.append({
                'no': idx + 1, 'pipe_id': p.get('id'),
                'name': p.get('name') or f'Branch {idx+1}',
                'sub_type': p.get('sub_type') or 'branch',
                'length_m': length,
                'emitters': emt,
                'flow_lph': lph,
                'flow_lpm': round(lph / 60.0, 2),
            })
            layer_total_len += length
            layer_total_emt += emt
            layer_total_lph += lph
        irrigation_summary['layers'].append({
            'layer_id': lid,
            'name': L.get('name') or 'Irrigation Layer',
            'height_m': L.get('height_m'),
            'pipe_count': len(pipes_out),
            'device_count': len(layer_devs),
            'pipes': pipes_out,
            # 엽면 습윤 위험 — 노즐 유량·반경·분사방향·좌표에서 산출.
            'nozzle': summarize_nozzles(layer_devs, layer_height=L.get('height_m')),
            'totals': {
                'length_m': round(layer_total_len, 2),
                'emitters': layer_total_emt,
                'flow_lph': round(layer_total_lph, 1),
                'flow_lpm': round(layer_total_lph / 60.0, 2),
            }
        })
        irrigation_summary['totals']['length_m'] += layer_total_len
        irrigation_summary['totals']['emitters'] += layer_total_emt
        irrigation_summary['totals']['flow_lph'] += layer_total_lph
    irrigation_summary['totals']['length_m'] = round(irrigation_summary['totals']['length_m'], 2)
    irrigation_summary['totals']['flow_lph'] = round(irrigation_summary['totals']['flow_lph'], 1)
    irrigation_summary['totals']['flow_lpm'] = round(irrigation_summary['totals']['flow_lph'] / 60.0, 2)

    # --- 4c. Per-actuator irrigation flow + 엽면 습윤 특성 (P3) ---
    # 관수 액추에이터(레이어 펌프·밸브 Output UUID) 별로 연결된 emitter 유량
    # 합계와 노즐 습윤 지표를 actuators_resolved 에 붙인다.
    # VolumetricAdapter 는 flow_lpm 으로 on_sec → mL 를 환산하고,
    # env_coordinator 육묘장 게이트는 nozzle 로 분무 잠금 여부를 판정한다.
    irrigation_summary['by_actuator'] = {}
    for aid, nozzle in nozzle_map.items():
        irrigation_summary['by_actuator'][aid] = nozzle
        entry = actuators_resolved.get(aid)
        if entry is None:
            continue
        flow_lph = float(nozzle.get('total_flow_lph') or 0.0)
        if flow_lph > 0.0:
            entry['flow_lpm'] = round(flow_lph / 60.0, 3)
        entry['nozzle'] = nozzle

    # --- 4d. Bay(구역) 귀속 ---
    # bay 2개 이상 시설에서 fitting position(로컬 x) → bay 슬라이스 매핑.
    # 센서는 bay_id(단일), 액추에이터는 fitting 들이 걸친 bay_ids(복수)를 갖는다.
    # 귀속 불가 항목은 bay_id=None / bay_ids=[] (= 시설 공통) 으로 남는다.
    bay_slices    = compute_bay_slices(facility)
    fitting_bay   = build_fitting_bay_map(bay_slices, fittings)
    bay_names     = {b['id']: b.get('name') for b in bay_slices}
    facility_name = facility.get('name')
    for entry in sensors_resolved:
        bay_id = fitting_bay.get(entry.get('fitting_id'))
        entry['bay_id'] = bay_id
        entry['bay_name'] = bay_names.get(bay_id)
        entry['facility_name'] = facility_name
    for entry in sensors_outdoor:
        bay_id = fitting_bay.get(entry.get('fitting_id'))
        entry['bay_id'] = bay_id
        entry['bay_name'] = bay_names.get(bay_id)
        entry['facility_name'] = facility_name
    for act in actuators_resolved.values():
        act['bay_ids'] = sorted({
            fitting_bay[fid] for fid in (act.get('fitting_ids') or [])
            if fid in fitting_bay
        })

    # --- 5. Capacity-meta summary ---
    capacity_meta = {
        'volume_m3':             computed.get('volume_m3'),
        'envelope_m2':           computed.get('envelope_m2'),
        'u_effective':           computed.get('u_effective'),
        'transmittance':         computed.get('transmittance'),
        # With an opaque cover these two are the entire solar load — leaving
        # them out would show a cooling figure with nothing to explain it.
        'absorptance':           computed.get('absorptance'),
        'solar_absorbed_kw':     computed.get('solar_absorbed_kw'),
        'vent_open_m2':          computed.get('vent_open_m2'),
        'vent_open_source':      computed.get('vent_open_source'),
        'vent_open_fittings_m2': computed.get('vent_open_fittings_m2'),
        'vent_open_envelope_m2': computed.get('vent_open_envelope_m2'),
    }

    # actuators_slot_map / groups: 그룹 파서가 두 번 DB 를 치지 않도록
    # raw 슬롯 매핑과 그룹 정의를 같이 실어 보낸다.
    groups_raw = facility.get('groups')
    result = {
        'facility_uuid':       facility_uuid,
        'name':                facility.get('name'),
        'geometry_3d':         facility.get('geometry_3d'),
        'envelope':            facility.get('envelope'),
        'fittings':            fittings,
        'actuators_resolved':  list(actuators_resolved.values()),
        'actuators_slot_map':  dict(slot_map),
        'sensors_resolved':    sensors_resolved,
        'sensors_outdoor':     sensors_outdoor,
        'sensors_forecast':    sensors_forecast,
        'vent_openings':       vent_openings,
        'bays':                bay_slices,
        'capacity_meta':       capacity_meta,
        'irrigation_summary':  irrigation_summary,
        'groups':              groups_raw if isinstance(groups_raw, dict) else {},
        'computed':            computed,
    }

    # ── TTL cache store ───────────────────────────────────────────────────────
    with _INTEG_CACHE_LOCK:
        _INTEG_CACHE[facility_uuid] = (result, _time.time())

    return result, None
