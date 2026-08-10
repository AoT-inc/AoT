# coding=utf-8
"""자동 VPD(수증기압차) 서비스.

입력별 옵트인(Input.auto_vpd_enabled)이 켜진 입력에 대해, 온도+습도를 함께
측정하면 측정 저장 시점에 VPD 를 계산해 그 입력의 **마지막 채널 다음 번호**에
vapor_pressure_deficit 측정값으로 같이 기록한다. 원하는 입력에서만 켤 수 있다.

측정 저장 공통 후크인 run_input_actions(aot/utils/actions.py) 끝에서 호출되며,
주입된 값은 호출자의 add_measurements_influxdb 가 온습도와 동일 타임스탬프로 기록한다.

- 온도 기준: 엽온 = 기온 - 1.5°C (AoT_VPD 기본값과 동일)
- 채널: **최초 생성 시 1회만** 그 입력의 실제(auto 제외) 채널 중 최댓값 + 1 로
  배치(예: 0=온도,1=습도,2=배터리 → 3=VPD). 이후에는 그 채널 번호를 절대 바꾸지
  않는다 — InfluxDB 는 채널 번호 단위로 기록되므로, 번호가 바뀌면 같은 측정의
  신·구 이력이 서로 다른 채널로 갈라져 뒤섞인다. 가변채널 입력에서 사용자가
  채널을 추가해 번호가 겹치게 되면, 기존 채널(auto 포함)을 옮기는 대신 새로
  추가되는 채널이 비어 있는 다음 번호를 골라 피해간다(input_mod 참고).
  measurement_type='auto_vpd' 마커로 식별하며, 가변채널 재조정과 설정 토글 OFF
  정리 로직이 이 마커를 사용한다.
- 물리센서가 이미 vapor_pressure_deficit 채널을 내장한 경우 이중 계산을 피하기 위해 skip.
"""
import logging
import time

logger = logging.getLogger(__name__)

AUTO_VPD_TYPE = 'auto_vpd'
AUTO_VPD_MEASUREMENT = 'vapor_pressure_deficit'
AUTO_VPD_UNIT = 'kPa'
LEAF_TEMP_OFFSET = -1.5  # 엽온 = 기온 + offset

_ENABLED_CACHE_TTL = 30.0  # 초 — 측정 저장마다 호출되므로 입력별 토글 집합을 캐시
_enabled_cache = {'ids': None, 'ts': 0.0}


def _enabled_input_ids():
    """auto_vpd_enabled=True 인 Input unique_id 집합을 TTL 캐시로 조회.

    측정 저장마다 호출되므로, 비활성 입력(대다수)이 DB 조회 없이 걸러지도록
    활성 입력 ID 집합만 캐시한다.
    """
    now = time.time()
    if (_enabled_cache['ids'] is not None and
            (now - _enabled_cache['ts']) < _ENABLED_CACHE_TTL):
        return _enabled_cache['ids']
    ids = set()
    try:
        from aot.config import AOT_DB_PATH
        from aot.databases.models import Input
        from aot.databases.utils import session_scope
        with session_scope(AOT_DB_PATH) as session:
            rows = session.query(Input.unique_id).filter(
                Input.auto_vpd_enabled.is_(True)).all()
            ids = {r[0] for r in rows}
    except Exception:
        logger.exception("자동 VPD 활성 입력 조회 실패")
        ids = set()
    _enabled_cache['ids'] = ids
    _enabled_cache['ts'] = now
    return ids


def invalidate_enabled_cache():
    """입력 토글 변경 후 캐시를 즉시 무효화하고 싶을 때 사용(선택)."""
    _enabled_cache['ids'] = None
    _enabled_cache['ts'] = 0.0


def _classify_channels(session, device_id):
    """device_id 의 DeviceMeasurements 를 분류.

    반환: (temp_row, hum_row, native_vpd_row, auto_row, max_channel)
    - temp_row/hum_row: 첫 번째 temperature/humidity 채널
    - native_vpd_row: 서비스가 만들지 않은 vapor_pressure_deficit 채널 (없으면 None)
    - auto_row: 서비스가 만든 auto_vpd 채널
    - max_channel: 이 입력의 **실제(auto 제외) 채널** 중 최댓값. "마지막 채널
      다음 번호"(= max_channel + 1)를 정하는 기준.
    """
    from aot.databases.models import DeviceMeasurements
    # 채널 번호 순으로 본다 — "첫 번째 temperature" 가 조회 순서에 따라 달라지면
    # 기온 대신 토양온도가 뽑혀 엉뚱한 VPD 가 나온다(둘 다 measurement 는
    # 'temperature' 다).
    rows = session.query(DeviceMeasurements).filter(
        DeviceMeasurements.device_id == device_id).order_by(
        DeviceMeasurements.channel).all()
    temp_row = hum_row = auto_row = native_vpd_row = None
    max_channel = -1
    for r in rows:
        if r.measurement_type == AUTO_VPD_TYPE:
            auto_row = r
            continue
        if r.channel is not None and r.channel > max_channel:
            max_channel = r.channel
        meas = (r.measurement or '').strip()
        if meas == 'temperature' and temp_row is None:
            temp_row = r
        elif meas == 'humidity' and hum_row is None:
            hum_row = r
        elif meas == AUTO_VPD_MEASUREMENT and native_vpd_row is None:
            native_vpd_row = r
    return temp_row, hum_row, native_vpd_row, auto_row, max_channel


def inject_auto_vpd(unique_id, measurements_dict):
    """온습도 입력이면 VPD 를 계산해 measurements_dict 에 주입.

    실패해도 입력 측정 저장에는 영향이 없도록 전체를 try/except 로 감싼다.
    """
    try:
        if not measurements_dict or unique_id not in _enabled_input_ids():
            return measurements_dict
        return _inject(unique_id, measurements_dict)
    except Exception:
        logger.exception("자동 VPD 주입 실패 (device_id=%s)", unique_id)
        return measurements_dict


def _inject(unique_id, measurements_dict):
    from aot.config import AOT_DB_PATH
    from aot.databases.models import DeviceMeasurements
    from aot.databases.utils import session_scope
    from aot.inputs.sensorutils import (
        calculate_vapor_pressure_deficit, convert_from_x_to_y_unit)

    with session_scope(AOT_DB_PATH) as session:
        temp_row, hum_row, native_vpd_row, auto_row, max_channel = _classify_channels(
            session, unique_id)

        # 물리센서가 자체 VPD 를 계산하면 이중처리 방지. 단 판정 기준은
        # "vapor_pressure_deficit 채널이 있다"가 아니라 **이번 사이클에 그
        # 채널로 값이 실제로 들어왔다**이다. 채널만 있고 값을 넣는 주체가
        # 없으면(사용자가 채널 목록에 VPD 칸을 직접 만든 경우) 예전 판정은
        # "센서가 자체 계산한다"고 오인해 자동 VPD 를 영구히 꺼 버렸고, 그
        # 칸은 아무도 채우지 않아 영원히 비어 있었다.
        if auto_row is None and native_vpd_row is not None:
            if native_vpd_row.channel in measurements_dict:
                return measurements_dict  # 센서가 직접 낸 값 — 손대지 않는다
            # 빈 껍데기 칸이면 그 칸을 그대로 채운다. 새 채널을 만들면
            # 화면에 빈 VPD 칸이 하나 더 늘어나고 채널 번호도 흔들린다.
            auto_row = native_vpd_row

        if temp_row is None or hum_row is None:
            return measurements_dict

        temp_entry = measurements_dict.get(temp_row.channel)
        hum_entry = measurements_dict.get(hum_row.channel)
        # 이번 사이클에 온·습도 값이 둘 다 있을 때만 계산
        if not isinstance(temp_entry, dict) or not isinstance(hum_entry, dict):
            return measurements_dict
        temp_val = temp_entry.get('value')
        hum_val = hum_entry.get('value')
        if temp_val is None or hum_val is None:
            return measurements_dict

        # dict 의 unit 이 실제 값의 단위(변환 후). 없으면 채널 정의 단위로 폴백.
        temp_unit = temp_entry.get('unit') or temp_row.unit or 'C'
        hum_unit = hum_entry.get('unit') or hum_row.unit or 'percent'
        temp_c = convert_from_x_to_y_unit(temp_unit, 'C', temp_val)
        hum_percent = convert_from_x_to_y_unit(hum_unit, 'percent', hum_val)
        if temp_c is None or hum_percent is None:
            return measurements_dict

        leaf_c = temp_c + LEAF_TEMP_OFFSET
        vpd_pa = calculate_vapor_pressure_deficit(leaf_c, hum_percent)
        if vpd_pa is None:
            return measurements_dict
        vpd_kpa = convert_from_x_to_y_unit('Pa', AUTO_VPD_UNIT, vpd_pa)
        if vpd_kpa is None:
            return measurements_dict

        # auto VPD 채널 지연 생성. auto_row 유무를 매 호출 DB 조회로 판단하므로
        # 비활성화→재활성화(채널 삭제 후 재생성)에도 스스로 복구된다.
        # 채널 번호는 최초 생성 시 이 입력의 실제 채널 중 최댓값 + 1 로 정하고,
        # 이후에는 절대 바꾸지 않는다(채널 번호 변경 시 InfluxDB 이력이 갈라짐).
        if auto_row is None:
            auto_channel = max_channel + 1
            new_row = DeviceMeasurements()
            new_row.device_id = unique_id
            new_row.name = 'VPD'
            new_row.measurement = AUTO_VPD_MEASUREMENT
            new_row.measurement_type = AUTO_VPD_TYPE
            new_row.unit = AUTO_VPD_UNIT
            new_row.channel = auto_channel
            new_row.is_enabled = True
            session.add(new_row)
        else:
            auto_channel = auto_row.channel

        injected = {
            'measurement': AUTO_VPD_MEASUREMENT,
            'unit': AUTO_VPD_UNIT,
            'value': vpd_kpa,
        }
        # use_same_timestamp=False(MQTT 등) 경로는 timestamp_utc 를 직접 참조하므로
        # 소스 온도 측정의 타임스탬프를 그대로 복사한다.
        ts = temp_entry.get('timestamp_utc')
        if ts is None:
            ts = hum_entry.get('timestamp_utc')
        if ts is not None:
            injected['timestamp_utc'] = ts
        measurements_dict[auto_channel] = injected

    return measurements_dict
