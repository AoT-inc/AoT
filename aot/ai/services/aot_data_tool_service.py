import json
import logging
import re
from aot.utils.time_utils import utc_now, to_local, serialize_ts
from aot.utils.tz_utils import now_utc, to_utc
from datetime import datetime, timedelta
from sqlalchemy import or_

from aot.aot_flask.extensions import db
from aot.databases.models import Input, Output, Camera, GeoShape, GeoLayer, DeviceMeasurements, Conversion, EnergyUsage, Misc, Notes, AITask, CustomController
from aot.ai.services.ai_context_service import AIContextService
from aot.ai.services.ai_action_service import AIActionService
from aot.utils.command_origin import TYPE_AI
from aot.utils.execution_context import (clear_execution_context,
                                         set_execution_context)
from aot.utils.influx import read_influxdb_list
from aot.utils.tools import return_energy_usage
from aot.utils.system_pi import return_measurement_info

logger = logging.getLogger(__name__)


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def _with_translated_alias(fn):
    """번역된 이름으로 불러도 원문 엔티티를 찾게 한다.

    사용자 지정 이름 번역이 켜져 있으면 화면에는 "1号ハウス" 가 보이는데 DB 에는
    "1번 하우스" 로 저장되어 있다. 사용자는 자기가 보는 이름으로 말하므로, 원문
    매칭이 실패했을 때 번역 사전을 역방향으로 읽어 한 번 더 시도한다.

    원문 매칭을 **먼저** 한다. 저장된 이름으로 부른 것을 번역명으로 오인해
    엉뚱한 엔티티로 보내면 안 되기 때문이다.

    docs/design/user-string-live-translation.md
    """
    import functools

    @functools.wraps(fn)
    def wrapper(target_name):
        result = fn(target_name)
        if result and result[0]:
            return result
        try:
            from aot.ai.services.user_string_translator import reverse_lookup
            source = reverse_lookup(target_name)
        except Exception:
            source = None
        if source and source != target_name:
            return fn(source)
        return result

    return wrapper


def _looks_like_uuid(value):
    """uuid 꼴인가 — 이름 기반 폴백을 건너뛸지 판정한다.

    이름 부분일치는 사람이 말한 이름('1포장')을 위한 것인데, uuid 를 그 자리에
    넣으면 우연한 문자열 포함으로 엉뚱한 도형이 걸린다. uuid 로 물어 못 찾았다면
    "없다" 가 정답이다.
    """
    return bool(_UUID_RE.match(str(value).strip()))


# ---------------------------------------------------------------------------
# @ANCHOR: WEATHER_DEVICE_KINDS
# Input.device values of the drivers that actually observe the weather.
#
# get_weather used to hand the zone uuid straight to get_sensor_detail, which
# takes the FIRST Input that happens to sit inside the polygon. On a real farm
# that is a soil probe: koat's '1포장' answered "No data for device
# '토양온습도_2'" (a soil sensor with no recent rows) and '3포장' answered with a
# plain air-temp/humidity node's readings — LoRaWAN rssi/snr included, and not
# one rain/wind field — while a dedicated KMA input and a SenseCAP weather
# station sat on both plots unused.
#
# A name list is deliberate: "is this a weather station" is a property of the
# DRIVER, not of the readings. Deriving it from measurements alone would let any
# node reporting temperature+humidity pass, which is exactly the wrong answer
# here. _WEATHER_MEASUREMENTS below is only a secondary net for drivers not
# listed here (a generic MQTT/Modbus feed wired to a real weather mast), and it
# asks for a measurement that only a weather station has — wind or rain.
#
# Add new weather drivers here when they are written.
_WEATHER_INPUT_DEVICES = frozenset({
    'KMA_weather_500',
    'KMA_weather_stn',
    'sensecap_weather',
    'ecowitt_weather',
    'OPENWEATHERMAP_CALL_WEATHER',
    'OPENWEATHERMAP_CALL_ONECALL',
})

# Measurements no ordinary sensor node carries. Used only for devices whose
# driver is not in _WEATHER_INPUT_DEVICES. 'temperature'/'humidity'/'pressure'
# are NOT here on purpose — every second sensor in the system has them.
# A bare 'speed' is deliberately NOT here — it is generic enough to match
# non-weather hardware, and every driver that reports wind speed also reports
# wind direction.
_WEATHER_MEASUREMENTS = frozenset({
    'direction',      # wind direction (unit 'bearing')
    'precipitation',
    'rain',
    'snowfall',
})


# get_sensor_detail(sensor_type='weather') 가 남길 측정 이름의 부분문자열.
# 'precipitation'/'snow'/'visibility' 가 명시적으로 들어 있는 이유: 'rain' 은
# 'precipitation' 의 부분문자열이 **아니라서**, 날씨를 묻는 바로 그 질의가 KMA
# 입력의 강수 채널을 통째로 걸러내고 있었다.
_WEATHER_METRIC_KEYWORDS = (
    'temperature', 'humidity', 'pressure', 'wind', 'rain', 'precipitation',
    'snow', 'visibility', 'solar', 'radiation', 'uv', 'dewpoint',
    'speed', 'direction',
)


def _devices_on_map_p2(map_uuid):
    """[P2] 지도에 배치된 장치 uuid 집합. map_config_id 조회의 대체.

    지도 소속의 정본은 배치(마커)다 — device_membership 이 정본이며,
    map_config_id 는 사망 컬럼이다.
    """
    try:
        from aot.aot_flask.geo.device_membership import devices_on_map
        return devices_on_map(map_uuid)
    except Exception:
        return set()


def _map_for_device_p2(device_uuid, prefer=None):
    """[P2] 장치가 배치된 대표 지도 uuid. map_config_id 읽기의 대체."""
    try:
        from aot.aot_flask.geo.device_membership import map_for_device
        return map_for_device(device_uuid, prefer=prefer)
    except Exception:
        return None



def _control_targets_for(controller):
    """이 코디네이터가 따르는 목표 → AI 가 읽는 dict.

    함수 옵션이 아니라 **제어와 같은 계산**을 거친다. 옛 키를 읽으면 AI 는 늘
    "목표 없음" 으로 보고 조언한다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        t = coordinator_plot.control_targets(controller)
        return {'vpd_kpa': (t.get('vpd') or {}).get('value'),
                'vpd_curve': bool((t.get('vpd') or {}).get('method_id')),
                'co2_ppm': (t.get('co2') or {}).get('value'),
                'co2_curve': bool((t.get('co2') or {}).get('method_id')),
                'dli': t.get('dli'), 'gdd_daily': t.get('gdd_daily'),
                'plot': t.get('plot_name'),
                'stage': (t.get('stage') or {}).get('name'),
                'reason': t.get('reason')}
    except Exception:                                       # noqa: BLE001
        return {'reason': 'error'}


def _plot_started_on(controller):
    """이 코디네이터가 따르는 구획의 시작일 → ISO 문자열|None.

    예전에는 함수 옵션(`schedule_start_time`)에 같은 날짜를 또 적게 했다. 그
    칸이 없어진 뒤로 옛 키를 읽으면 AI 는 늘 "작기 시작일 없음" 으로 본다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        d = coordinator_plot.control_targets(controller).get('started_on')
        return d.isoformat() if d else None
    except Exception:                                       # noqa: BLE001
        return None


class AoTDataToolService:
    """
    AoT 내부 데이터를 AI 도구 규격에 맞게 제공하는 서비스 레이어.
    가상 MCP 워커(mcp_aot)가 이를 호출합니다.

    @phase active
    @stability stable
    """

    @staticmethod
    def _check_influxdb_available():
        """InfluxDB 연결 가능 여부를 사전 점검합니다."""
        try:
            settings = Misc.query.first()
            if not settings:
                return False, "System settings (Misc) not found."
            if settings.measurement_db_name != 'influxdb':
                return False, f"Measurement DB is not InfluxDB: {settings.measurement_db_name}"
            if not settings.measurement_db_version:
                return False, "InfluxDB version is not configured. Check the measurement DB in system settings."
            if not settings.measurement_db_host or settings.measurement_db_port in (None, 0, '0', ''):
                return False, "InfluxDB host/port is not configured."

            # 실제 연결 테스트 (compose의 influxdb 사이드카/네이티브 호스트 자동 해석)
            import requests as req
            from aot.config import INFLUXDB_PORT, resolve_measurement_db_host
            _host = resolve_measurement_db_host(settings.measurement_db_host)
            _port = INFLUXDB_PORT or settings.measurement_db_port
            url = f"http://{_host}:{_port}/health"
            resp = req.get(url, timeout=3)
            if resp.status_code != 200:
                return False, f"InfluxDB server response error (HTTP {resp.status_code})"
            return True, "OK"
        except req.exceptions.ConnectionError:
            return False, f"Cannot connect to InfluxDB server ({settings.measurement_db_host}:{settings.measurement_db_port}). Check that the server is running."
        except Exception as e:
            return False, f"Error while checking InfluxDB: {str(e)}"

    @staticmethod
    def _get_last_values_fallback(target_input, device_measurements,
                                  is_function=False):
        """InfluxDB 사용 불가 시 read_influxdb_single(LAST)로 최신 값만 시도합니다."""
        from aot.utils.influx import read_influxdb_single
        results = []
        for m in device_measurements:
            conversion = Conversion.query.filter(Conversion.unique_id == m.conversion_id).first() if m.conversion_id else None
            channel, unit, measurement = return_measurement_info(m, conversion)
            try:
                last = read_influxdb_single(
                    target_input.unique_id, unit, channel,
                    measure=measurement, duration_sec=86400, value='LAST', datetime_obj=True
                )
                if last and last[0] is not None and last[1] is not None:
                    _t = last[0]
                    if hasattr(_t, 'astimezone'):
                        # tz-aware (InfluxDB client) but in UTC — show in this
                        # device's own location time, consistent with the rest
                        # of the location-aware time work.
                        try:
                            from aot.utils.device_tz import resolve_location_tz
                            _t = _t.astimezone(resolve_location_tz(target_input.unique_id))
                        except Exception:
                            pass
                    results.append({
                        "device_name": target_input.name or target_input.unique_id,
                        "device_kind": "function" if is_function else "input",
                        "measurement": measurement or m.measurement,
                        "last_value": round(last[1], 2),
                        "last_time": _t.isoformat() if hasattr(_t, 'isoformat') else str(_t),
                        "unit": unit,
                        "note": "Time-series query failed - only latest value provided"
                    })
            except Exception:
                pass
        return results

    @staticmethod
    def get_sensor_detail(loc_id, sensor_type=None, time_range="24h", limit=None):
        """
        특정 위치/장치의 상세 센서 이력을 조회합니다.
        :param loc_id: 장치(Input) 또는 구역(GeoShape)의 unique_id
        :param sensor_type: 필터링할 센서 타입 (예: temperature, humidity)
        :param time_range: 조회 범위 ("1h", "24h", "7d" 등)
        :param limit: 반환할 최근 readings 수 (기본: 20, 현재 날씨 조회 시 1 권장)
        """
        try:
            # 1. 대상 식별 (Input 우선: unique_id 또는 map_config_id/geo_id 지원)
            target_input = Input.query.filter(
                # [P2] 지도 uuid 로 들어오면 그 지도에 배치된 장치를 찾는다.
                or_(Input.unique_id == loc_id,
                    Input.unique_id.in_(_devices_on_map_p2(loc_id)))
            ).first()

            # 집계 함수(VPD·평균·Equation 등)는 CustomController 로 살지만
            # DeviceMeasurements 와 InfluxDB 기록은 Input 과 같은 규약을 쓴다
            # (write_influxdb_value(self.unique_id, ...)). 아래 측정 조회는
            # unique_id/name 만 보므로 그대로 통한다. 이 분기가 없으면 사람이
            # 화면에서 만들어 둔 함수 값을 AI 가 "그런 장치 없다" 로 답한다.
            is_function = False
            if not target_input:
                target_input = CustomController.query.filter_by(
                    unique_id=loc_id).first()
                is_function = target_input is not None

            if not target_input:
                # 구역인 경우 (unique_id 또는 geo_id 지원)
                target_zone = GeoShape.query.filter(
                    or_(GeoShape.unique_id == loc_id, GeoShape.geo_id == loc_id)
                ).first()
                # [WEATHER_TOOL_UNIFICATION] Name-based fallback: loc_id may be a zone name (e.g. '1포장')
                # not a UUID. Match by feature.properties.name so both get_sensor_detail and
                # get_weather behave consistently regardless of which tool the AI selects.
                # 부분일치가 양방향(`_sname in _loc_lower`)이라 한 글자 구역
                # 이름('2')이 uuid 안에 우연히 들어 있기만 해도 걸린다. 실측에서
                # 함수 uuid 8개 중 7개가 엉뚱한 Zone '2'/'1' 로 해소돼, 묻지도
                # 않은 구역을 답으로 내놓았다. 길이로 막으면 이름이 한 글자인
                # 구역(로컬에 4개 실재)을 이름으로 못 찾으므로, 위 주석이 이미
                # 말하는 전제 — "loc_id 가 uuid 가 아닐 때" — 를 실제로 건다.
                if not target_zone and loc_id and not _looks_like_uuid(loc_id):
                    import json as _json_sd
                    _loc_lower = str(loc_id).strip().lower()
                    for _shape in GeoShape.query.all():
                        try:
                            _feat = _shape.feature if isinstance(_shape.feature, dict) else _json_sd.loads(_shape.feature or '{}')
                            _props = _feat.get('properties') or {}
                            _sname = str(_props.get('name') or _props.get('label') or _props.get('title') or '').lower()
                            if _sname and (_loc_lower in _sname or _sname in _loc_lower):
                                target_zone = _shape
                                break
                        except Exception:
                            continue
                if target_zone:
                    # [S3] 소속은 마커 좌표에서 파생한다. site 폴리곤은 내부
                    # zone 들을 기하학적으로 포함하므로 별도 계층 순회가 필요
                    # 없다 — site 에 대해 호출하면 하위 zone 센서까지 잡힌다.
                    from aot.aot_flask.geo.device_membership import device_ids_in_shape
                    _member_ids = device_ids_in_shape(target_zone)
                    target_input = (Input.query.filter(
                        Input.unique_id.in_(_member_ids)).first()
                        if _member_ids else None)

            if not target_input:
                # If no sensor is directly linked to the zone, return the zone's coordinates
                # so the caller (AI) can use an external weather tool if needed.
                if target_zone and target_zone.feature:
                    props = target_zone.feature.get('properties', {})
                    geom = target_zone.feature.get('geometry', {})
                    return {
                        "message": f"Zone '{props.get('name', 'Unknown')}' has no directly connected sensors.",
                        "zone_name": props.get('name'),
                        "zone_id": target_zone.unique_id,
                        "location": geom.get('coordinates'),
                        "suggestion": "You can use these coordinates to look up weather information."
                    }
                return {"error": f"Device or zone not found: {loc_id}"}

            # 2. 측정값 정보 획득
            device_measurements = DeviceMeasurements.query.filter(DeviceMeasurements.device_id == target_input.unique_id).all()
            if not device_measurements:
                return {"error": f"This device ({target_input.name}) has no defined measurements."}

            # 필터링 적용 (Sensory Keyword Normalization)
            if sensor_type:
                s_type_map = {
                    '온도': 'temperature', 'temp': 'temperature',
                    '습도': 'humidity', 'hum': 'humidity',
                    '조도': 'light', 'lux': 'light',
                    '수분': 'moisture', '토양': 'moisture',
                    '기상': 'weather', '날씨': 'weather', 'atmosphere': 'weather',
                    '배터리': 'battery', 'vbat': 'battery'
                }
                # Normalize search term
                search_term = sensor_type.lower()
                for ko, en in s_type_map.items():
                    if ko in search_term:
                        search_term = en
                        break

                if search_term == 'weather':
                    # Special Case: 'weather' maps to multiple common atmospheric metrics
                    device_measurements = [m for m in device_measurements
                                           if any(wm in (m.measurement or "").lower()
                                                  for wm in _WEATHER_METRIC_KEYWORDS)]
                else:
                    device_measurements = [m for m in device_measurements if search_term in (m.measurement or "").lower()]

            if not device_measurements:
                return {"error": f"No measurements matching type '{sensor_type}'."}

            # 3. InfluxDB 연결 사전 점검
            influx_ok, influx_msg = AoTDataToolService._check_influxdb_available()
            if not influx_ok:
                logger.warning(f"[AoTDataTool] InfluxDB 사용 불가: {influx_msg}")
                # 폴백: 최신 값이라도 반환 시도
                fallback = AoTDataToolService._get_last_values_fallback(
                    target_input, device_measurements, is_function=is_function)
                if fallback:
                    return {
                        "warning": f"InfluxDB unavailable ({influx_msg}). Only the latest value is provided.",
                        "data": fallback
                    }
                # 폴백도 실패 시 장치 메타데이터라도 반환
                meta = []
                for m in device_measurements:
                    conversion = Conversion.query.filter(Conversion.unique_id == m.conversion_id).first() if m.conversion_id else None
                    channel, unit, measurement = return_measurement_info(m, conversion)
                    meta.append({"measurement": measurement or m.measurement, "unit": unit})
                return {
                    "error": f"InfluxDB unavailable: {influx_msg}",
                    "device_name": target_input.name or target_input.unique_id,
                    "device_id": target_input.unique_id,
                    "available_measurements": meta,
                    "suggestion": "Check the InfluxDB server status, or verify the measurement DB configuration in system settings."
                }

            # 4. InfluxDB 시계열 조회
            offset_sec = AoTDataToolService._parse_range(time_range)
            results = []

            for m in device_measurements:
                conversion = Conversion.query.filter(Conversion.unique_id == m.conversion_id).first() if m.conversion_id else None
                channel, unit, measurement = return_measurement_info(m, conversion)

                data = read_influxdb_list(
                    target_input.unique_id,
                    unit,
                    channel,
                    measure=measurement,
                    duration_sec=offset_sec,
                    datetime_obj=True
                )

                if data:
                    # Rows are tz-aware UTC (InfluxDB client) — display in this
                    # device's own location time (resolved once per measurement,
                    # not per row) for the same reason as _get_last_values_fallback above.
                    try:
                        from aot.utils.device_tz import resolve_location_tz
                        _tz = resolve_location_tz(target_input.unique_id)
                        readings = [{"t": row[0].astimezone(_tz).isoformat(), "v": round(row[1], 2), "u": unit} for row in data]
                    except Exception:
                        readings = [{"t": row[0].isoformat(), "v": round(row[1], 2), "u": unit} for row in data]
                    values = [row[1] for row in data]
                    _keep = int(limit) if limit else 20
                    results.append({
                        "device_name": target_input.name or target_input.unique_id,
                        # 함수 값은 계산된 것(예: 센서 여럿의 평균, VPD)이다.
                        # 구분해 내보내지 않으면 직접 잰 값으로 보고된다.
                        "device_kind": "function" if is_function else "input",
                        "measurement": measurement or m.measurement,
                        "readings": readings[-_keep:],  # limit 파라미터로 조절 (기본 20건)
                        "total_readings": len(readings),
                        "stats": {
                            "min": round(min(values), 2),
                            "max": round(max(values), 2),
                            "avg": round(sum(values) / len(values), 2),
                            "count": len(values)
                        }
                    })

            if results:
                return results

            # InfluxDB는 접속됐지만 데이터가 없는 경우
            return {
                "message": f"No data for device '{target_input.name}' in the last {time_range}.",
                "device_id": target_input.unique_id,
                "time_range": time_range
            }

        except Exception as e:
            logger.exception("Error in get_sensor_detail")
            return {"error": f"Error while querying sensor data: {str(e)}"}

    @staticmethod
    def _shape_display_name(shape):
        import json as _json
        feat = shape.feature
        if isinstance(feat, str):
            try:
                feat = _json.loads(feat or '{}')
            except Exception:
                feat = {}
        props = (feat or {}).get('properties') or {} if isinstance(feat, dict) else {}
        return (props.get('name') or props.get('label')
                or props.get('label_name') or props.get('title') or '').strip()

    @staticmethod
    def get_zone_sensor_summary(zone_ids=None, measurement_type=None,
                                time_range="7d", **extra):
        """[읽기전용] 여러 구역의 센서 최신값 + 기간 통계를 한 번에.

        "밭 전체에서 어디가 마른가" 류 질문은 구역마다 get_sensor_detail 을
        반복해야 했다. 이 도구는 그것을 한 호출로 접는다.

        **함수를 만들지 않는다.** 대상도 기간도 질문마다 달라 고정 계산기로는
        답할 수 없으므로, aot/utils/influx.py 의 무상태 헬퍼를 그때그때 조합해
        계산만 하고 아무것도 남기지 않는다(집계 Function 은 제어 입력이나 이력
        보존이 필요할 때 사람이 만든다).

        `measurement_type` 으로 좁히는 것을 권한다 — 안 주면 그 구역의 모든
        측정이 딸려 와 답이 길어진다.

        한 장치가 채널을 여럿 갖고 같은 `measurement` 라벨을 공유할 수 있다
        (예: 토양센서의 대기 채널과 토양 채널이 둘 다 "temperature"). 그래서
        각 항목에 `channel` 을 함께 싣는다 — 라벨만으로는 어느 채널인지
        구분되지 않는다.
        """
        try:
            from aot.utils.influx import read_influxdb_list
            from aot.aot_flask.geo.device_membership import device_ids_in_area

            past_sec = AoTDataToolService._parse_range(time_range)

            if isinstance(zone_ids, str):
                zone_ids = [zone_ids]
            if zone_ids:
                shapes = GeoShape.query.filter(
                    GeoShape.unique_id.in_(list(zone_ids))).all()
                missing = set(zone_ids) - {s.unique_id for s in shapes}
                if missing and not shapes:
                    return {"error": "zone not found: %s" % ', '.join(sorted(missing))}
            else:
                shapes = [s for s in GeoShape.query.filter(
                    GeoShape.type.in_(('site', 'zone'))).order_by(GeoShape.id).all()
                    if AoTDataToolService._shape_display_name(s)]
            if not shapes:
                return {"error": "no zone/site found"}

            wanted = (AoTDataToolService._device_ids_with_measurement(measurement_type)
                      if measurement_type else None)

            # 1) 구역 → 장치. 2) 장치 → 측정 채널. 여기까지가 SQL 이다.
            per_zone, all_ids = [], set()
            for shape in shapes:
                ids = device_ids_in_area(shape.unique_id) or set()
                if wanted is not None:
                    ids = ids & wanted
                if ids:
                    all_ids |= ids
                per_zone.append((shape, ids))

            if not all_ids:
                return {"count": 0, "zones": [],
                        "message": ("No sensor with that measurement was found in "
                                    "the requested area." if measurement_type else
                                    "No sensor was found in the requested area.")}

            mq = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id.in_(list(all_ids)))
            if measurement_type:
                mq = mq.filter(DeviceMeasurements.measurement.like(
                    "%%%s%%" % str(measurement_type).strip()))
            chans = mq.all()

            names = {i.unique_id: i.name for i in Input.query.filter(
                Input.unique_id.in_(list(all_ids))).all()}

            specs, by_device = [], {}
            for m in chans:
                conv = (Conversion.query.filter(
                    Conversion.unique_id == m.conversion_id).first()
                    if m.conversion_id else None)
                channel, unit, meas = return_measurement_info(m, conv)
                if not unit:
                    continue
                specs.append((unit, m.device_id, channel, meas))
                by_device.setdefault(m.device_id, []).append(
                    (unit, channel, meas))

            # 3) 채널마다 한 번씩 읽고 통계는 여기서 센다.
            #
            # **벌크 Flux 로 접지 말 것.** 시리즈를 device_id 집합(`contains`)으로
            # 거르는 쿼리는 인덱스로 내려가지 않아 전량 스캔이 된다 — 실측(센서
            # 5개·7일): query_last_values_bulk 3,612ms · reduce 통계 3,045ms 대
            # 개별 read_influxdb_list 5회 합계 **169ms**. `contains` 벌크가 이기는
            # 것은 장치가 수십 개이고 창이 짧을 때다(query_last_values_bulk
            # docstring 의 지도 위젯 사례). 여기 워크로드는 그 반대다.
            series, degraded = {}, False
            for unit, did, channel, meas in specs:
                rows = read_influxdb_list(did, unit, channel, measure=meas,
                                          duration_sec=past_sec,
                                          datetime_obj=True)
                if rows is None:
                    degraded = True
                    continue
                if not rows:
                    continue
                vals = [r[1] for r in rows if r[1] is not None]
                if not vals:
                    continue
                series[(did, channel, meas)] = {
                    'last': rows[-1], 'unit': unit,
                    'min': min(vals), 'max': max(vals),
                    'avg': sum(vals) / len(vals), 'count': len(vals)}

            zones_out, skipped = [], []
            for shape, ids in per_zone:
                readings = []
                for did in sorted(ids):
                    for unit, channel, meas in by_device.get(did, []):
                        s = series.get((did, channel, meas))
                        if s is None:
                            continue
                        t, v = s['last']
                        readings.append({
                            "device_id": did,
                            "device_name": names.get(did) or did,
                            "channel": channel,
                            "measurement": meas, "unit": unit,
                            "last_value": round(v, 2),
                            "last_time": (t.isoformat() if hasattr(t, 'isoformat')
                                          else str(t)),
                            "stats": {"min": round(s['min'], 2),
                                      "max": round(s['max'], 2),
                                      "avg": round(s['avg'], 2),
                                      "count": s['count']}})
                if not readings:
                    # zone_id/zone_name 을 여기서 담아 둔다 — 개수만 세면 호출자가
                    # 요청 목록과 응답 목록을 직접 대조해야 "어느 구역인지" 알 수
                    # 있고, 센서가 아예 없던 구역은 이름 조회 기회조차 없다.
                    skipped.append({"zone_id": shape.unique_id,
                                    "zone_name": AoTDataToolService._shape_display_name(shape)})
                    continue
                zones_out.append({
                    "zone_id": shape.unique_id,
                    "zone_name": AoTDataToolService._shape_display_name(shape),
                    "zone_type": shape.type,
                    "sensors": readings})

            out = {"count": len(zones_out), "time_range": time_range,
                   "zones": zones_out}
            if measurement_type:
                out["measurement_type"] = measurement_type
            if skipped:
                out["zones_without_data"] = skipped
            if degraded:
                out["warning"] = ("InfluxDB returned nothing for any series — "
                                  "this may be a read failure, not an absence of data.")
            notes = []
            # 같은 측정 이름을 여러 채널이 쓰는 구역이 실제로 있을 때만 말한다
            # (토양 프로브의 대기 채널과 토양 채널이 둘 다 'temperature' 인 식).
            # 그런 구역이 없으면 이 경고는 읽는 사람을 헷갈리게만 한다.
            for z in zones_out:
                seen = {}
                for r in z.get("sensors") or []:
                    key = (r.get("device_id"), r.get("measurement"))
                    if key in seen and seen[key] != r.get("channel"):
                        notes.append(
                            "A device here reports the same measurement on more "
                            "than one channel — 'channel' is what tells them "
                            "apart, not 'measurement'. Name the channel when you "
                            "report one of these.")
                        break
                    seen[key] = r.get("channel")
                if notes:
                    break
            if skipped:
                notes.append(
                    "'zones_without_data' lists the zones that returned nothing, "
                    "by name. Relay WHICH ones, not just how many.")
            if degraded:
                notes.append(
                    "'warning' is present: the readings may be missing because "
                    "InfluxDB could not be read, NOT because there is no data. "
                    "Say that rather than reporting zero.")
            if notes:
                out["_reading"] = notes
            return out
        except Exception as e:
            logger.exception("Error in get_zone_sensor_summary")
            return {"error": str(e)}

    @staticmethod
    def open_drawer(drawer=None, **extra):
        """[읽기전용] 서랍을 열어 그 안 도구들의 정의를 돌려준다.

        매니페스트에는 자주 쓰는 도구만 싣고 나머지는 서랍에 둔다. 이 도구가
        그 서랍을 여는 유일한 수단이다 — 그래서 절대 서랍 안으로 내려가지
        않는다(`never_demote`, 가드가 고정한다).

        모르는 이름이면 **오류가 아니라 목록을 돌려준다.** 서랍 이름을 틀렸을
        때 "없다" 로 끝내면 LLM 이 포기하는데, 목록을 주면 다시 고를 수 있다.
        """
        from aot.ai.services import tool_registry as registry

        known = registry.DRAWERS
        if not drawer or drawer not in known:
            return {
                "error": ("unknown drawer: %s" % drawer) if drawer
                         else "drawer is required",
                "drawers": registry.drawer_index(),
            }

        names = set(registry.tools_in_drawer(drawer))
        tools = [dict(t.manifest) for t in registry.TOOLS
                 if t.manifest and t.name in names]
        return {"drawer": drawer, "description": known[drawer],
                "count": len(tools), "tools": tools}

    @staticmethod
    def get_spatial_tree(depth=2, filter_type=None):
        """
        시스템의 공간 계층 구조를 트리 형태로 반환합니다.
        """
        try:
            full_tree = AIContextService.get_spatial_hierarchy()
            # depth 에 따른 가지치기는 추후 복잡도에 따라 구현 가능
            if filter_type:
                # 모든 노드가 "children" 키를 항상 갖고 있어(빈 리스트라도)
                # 예전 조건 `c.get('type') == filter_type or 'children' in c`
                # 는 뒤쪽 항이 노드마다 항상 True 라 사실상 아무것도 걸러내지
                # 못했다 — filter_type 을 줘도 전체 트리가 그대로 나왔다.
                # 이제 노드 자신이 filter_type 이거나, 그 밑에 filter_type
                # 인 자손이 남아 있을 때만 남긴다(중간 컨테이너는 경로를
                # 잇기 위해 유지하되, 매치가 하나도 없으면 가지째 잘라낸다).
                def filter_node(node):
                    kept_children = [c for c in
                                      (filter_node(child) for child in node.get('children', []))
                                      if c is not None]
                    node = dict(node, children=kept_children)
                    if node.get('type') == filter_type or kept_children:
                        return node
                    return None
                full_tree = [n for n in (filter_node(root) for root in full_tree) if n is not None]

            return {"hierarchy": full_tree}
        except Exception as e:
            return {"error": str(e)}

    # Common English function words that carry no device-search signal on their
    # own — see the filtering note inside search_devices() for why they must be
    # dropped before becoming a `%term%` LIKE clause.
    _SEARCH_STOPWORDS = frozenset({
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'for', 'of', 'to', 'in', 'on', 'at', 'by', 'with', 'and', 'or', 'not',
        'this', 'that', 'these', 'those', 'it', 'its', 'as', 'from',
    })

    @staticmethod
    def _device_parent_map():
        """{Input/Output.unique_id: (parent_device_id, parent_device_name)}.

        복합장치(Device) 티어는 새 테이블이 아니라 is_device=True 를 선언한
        CustomController 행이고, 하위 Input/Output 은 parent_device_id 로
        그 행을 가리킨다(.local/plans/device_group_console_plan.md). AI 쪽
        검색·목록 도구는 지금까지 이 관계를 전혀 몰라서, PLC 하나가 Input과
        Output 으로 흩어져 보이면 이름이 비슷한 것들을 각각 추측해서 찾아야
        했다 — 이 맵을 결과에 섞어 넣으면 "이 Input 은 이 장치 소속"이라는
        사실이 데이터에 명시된다. 새 MCP 도구를 만들지 않고 기존 도구의
        결과에 필드만 얹는다(Phase 5).
        """
        try:
            from aot.databases.models.controller import CustomController
            from aot.utils.functions import device_module_names

            device_names = device_module_names()
            if not device_names:
                return {}

            id_to_name = {
                d.unique_id: d.name
                for d in CustomController.query.filter(
                    CustomController.device.in_(device_names)).all()
            }
            if not id_to_name:
                return {}

            mapping = {}
            for inp in Input.query.filter(Input.parent_device_id.in_(id_to_name)).all():
                mapping[inp.unique_id] = (inp.parent_device_id, id_to_name[inp.parent_device_id])
            for out in Output.query.filter(Output.parent_device_id.in_(id_to_name)).all():
                mapping[out.unique_id] = (out.parent_device_id, id_to_name[out.parent_device_id])
            return mapping
        except Exception:
            return {}

    @staticmethod
    def _annotate_device_membership(results):
        """search_devices()/get_device_list_tool() 결과 리스트에
        parent_device_id/parent_device_name 을 제자리에서 채운다(있는 것만)."""
        parent_map = AoTDataToolService._device_parent_map()
        if not parent_map:
            return results
        for r in results:
            if r.get('type') in ('input', 'output'):
                parent = parent_map.get(r.get('id'))
                if parent:
                    r['parent_device_id'], r['parent_device_name'] = parent
        return results

    @staticmethod
    def _annotate_device_zone(results):
        """결과에 소속 구역 이름을 제자리에서 채운다(있는 것만)."""
        try:
            from aot.ai.services.ai_context_service import AIContextService
            zmap = AIContextService.get_device_zone_map()
        except Exception:
            return results
        for r in results:
            if r.get('type') in ('input', 'output') and zmap.get(r.get('id')):
                r['zone'] = zmap[r['id']]
        return results

    @staticmethod
    def _device_ids_with_measurement(measurement_type):
        """그 측정을 **실제로 가진** 장치 id 집합. 이름은 보지 않는다.

        이름으로 센서를 찾는 것은 믿을 수 없다 — 같은 토양수분 센서가
        '토양온습도_1' 이기도 '온습도_1' 이기도 하다. 그래서 후보를 이름으로
        추려 놓고 장치마다 get_device_measurements 를 불러 채널을 확인하는
        왕복이 생겼다(실측 7회). DeviceMeasurements.measurement 로 한 번에
        거르면 그 왕복 전체가 사라진다.
        """
        like = "%%%s%%" % str(measurement_type).strip()
        rows = DeviceMeasurements.query.with_entities(
            DeviceMeasurements.device_id).filter(
                DeviceMeasurements.measurement.like(like)).all()
        return {r[0] for r in rows if r[0]}

    @staticmethod
    def search_devices(query=None, measurement_type=None):
        """
        이름 또는 타입으로 장치를 검색합니다.
        v2: Multi-token query expansion.
          - Splits query by whitespace and searches each token independently
            (e.g. "1구역 밸브" → searches "1구역" AND "밸브" separately).
          - Loads term aliases from AIDomainGlossary (category='term_alias')
            to handle user-specific terms (e.g. "1포장" → "1구역").
          - Deduplicates results by unique_id.
        v3: measurement_type 필터.
          - 그 측정을 실제로 가진 장치만 남긴다(이름 무관).
          - query 없이 단독으로도 쓴다 — "토양수분 센서 전부" 가 한 번에 온다.
          - query 와 함께 주면 교집합("1포장 안의 토양수분 센서").
        """
        if not query and not measurement_type:
            return {"error": "query or measurement_type is required"}

        try:
            import re

            candidate_ids = None
            if measurement_type:
                candidate_ids = AoTDataToolService._device_ids_with_measurement(
                    measurement_type)
                if not candidate_ids:
                    return {"results": [], "count": 0,
                            "message": ("No device has a measurement matching "
                                        "'%s'." % measurement_type)}

            # 측정 종류만 물은 경우. 이름 검색 경로(토큰 확장·별칭·구역 확장)를
            # 태울 근거가 없으므로 후보를 그대로 낸다.
            if not query:
                results = []
                for item in Input.query.filter(
                        Input.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "input", "device": item.device})
                for item in Output.query.filter(
                        Output.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "output", "device": item.output_type})
                # 집계 함수(VPD·평균 등)도 자기 측정 채널을 갖는다. 빼면
                # measurement_type='vapor_pressure_deficit' 이 0건이 되는데,
                # get_sensor_detail 은 그 값을 읽을 수 있다(찾을 수만 없다).
                for item in CustomController.query.filter(
                        CustomController.unique_id.in_(list(candidate_ids))).all():
                    results.append({"id": item.unique_id, "name": item.name,
                                    "type": "function", "device": item.device})
                results = AoTDataToolService._annotate_device_zone(results)
                results = AoTDataToolService._annotate_device_membership(results)
                return {"results": results, "count": len(results)}

            def _normalize_variants(term):
                """Generate search variants for a term to handle spacing differences.
                e.g. '밸브3' → ['밸브3', '밸브 3']
                     '밸브 3' → ['밸브 3', '밸브3']
                """
                variants = [term]
                # Collapse all whitespace → no-space variant
                no_space = re.sub(r'\s+', '', term)
                if no_space != term:
                    variants.append(no_space)
                # Insert space between Korean (Hangul) block and digit (or vice versa)
                spaced = re.sub(r'([\uAC00-\uD7A3])(\d)', r'\1 \2', term)
                spaced = re.sub(r'(\d)([\uAC00-\uD7A3])', r'\1 \2', spaced)
                if spaced != term:
                    variants.append(spaced)
                return variants

            # Build search token list: individual tokens + full query.
            # Drop single-letter alphabetic tokens and common English stopwords —
            # each becomes a `%term%` LIKE against name/device_type, and a token
            # like "a" or "for" incidentally substring-matches almost every row
            # (confirmed: "a" alone matched 26/26 outputs in a real dev DB via
            # output_type, e.g. names containing a bare "a" letter) rather than
            # actually narrowing the search. Digits are kept (e.g. "3" in "zone 3"
            # is real device-numbering signal, matching "밸브3"/"AoT-C-003").
            tokens = [t.strip() for t in query.split() if t.strip()]
            tokens = [t for t in tokens
                      if t.lower() not in AoTDataToolService._SEARCH_STOPWORDS
                      and not (len(t) == 1 and t.isalpha())]
            _base_terms = [query] + tokens
            # Expand each base term with normalization variants
            _expanded = []
            for t in _base_terms:
                for v in _normalize_variants(t):
                    if v not in _expanded:
                        _expanded.append(v)
            search_terms = _expanded

            # Load term aliases from AIDomainGlossary
            try:
                from aot.databases.models.ai_domain_glossary import AIDomainGlossary
                alias_rows = AIDomainGlossary.query.filter_by(category='term_alias', is_active=True).all()
                alias_map = {a.term.lower(): a.definition for a in alias_rows}
            except Exception:
                alias_map = {}

            # Expand each token with its alias (if any), including normalization variants
            for token in list(tokens):
                canonical = alias_map.get(token.lower())
                if canonical:
                    for v in _normalize_variants(canonical):
                        if v not in search_terms:
                            search_terms.append(v)

            # 번역된 이름으로 검색할 수 있어야 한다. 사용자 지정 이름 번역이
            # 켜져 있으면 화면에는 "1号ハウス" 가 보이는데 DB 에는 "1번 하우스"
            # 로 저장되어 있고, 사용자는 자기가 보는 이름으로 말한다.
            # docs/design/user-string-live-translation.md
            try:
                from aot.ai.services.user_string_translator import reverse_lookup
                for term in [query] + tokens:
                    source = reverse_lookup(term)
                    if source and source not in search_terms:
                        search_terms.append(source)
            except Exception:
                pass

            seen_ids = set()
            results = []

            for term in search_terms:
                q = f"%{term}%"
                for item in Input.query.filter(
                    or_(Input.name.like(q), Input.device.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device})

                for item in Output.query.filter(
                    or_(Output.name.like(q), Output.output_type.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type})

                # 복합장치(Device) — is_device=True 모듈이 만드는 CustomController
                # 행. PLC 처럼 "장치 하나"로 물어보면 그 자체가 검색되고,
                # member_ids 로 하위 Input/Output 을 바로 가리킬 수 있다.
                try:
                    # CustomController 는 모듈 상단에서 임포트한다. 여기서 다시
                    # 지역 임포트하면 그 이름이 함수 전체의 지역변수가 되어,
                    # 이 블록보다 앞에서 쓰는 자리가 UnboundLocalError 로 죽는다.
                    from aot.utils.functions import device_module_names
                    _dev_names = device_module_names()
                    if _dev_names:
                        for item in CustomController.query.filter(
                            CustomController.device.in_(_dev_names),
                            CustomController.name.like(q)
                        ).all():
                            if item.unique_id not in seen_ids:
                                seen_ids.add(item.unique_id)
                                member_ids = (
                                    [i.unique_id for i in Input.query.filter_by(
                                        parent_device_id=item.unique_id).all()] +
                                    [o.unique_id for o in Output.query.filter_by(
                                        parent_device_id=item.unique_id).all()]
                                )
                                results.append({
                                    "id": item.unique_id, "name": item.name,
                                    "type": "device", "device": item.device,
                                    "member_ids": member_ids,
                                })
                except Exception:
                    pass

                for item in Camera.query.filter(
                    or_(Camera.name.like(q), Camera.camera_type.like(q))
                ).all():
                    if item.unique_id not in seen_ids:
                        seen_ids.add(item.unique_id)
                        results.append({"id": item.unique_id, "name": item.name, "type": "camera", "device": item.camera_type})

                # v26.10: Include GeoShapes (Sites/Zones) in search results
                # v26.11: Also check feature.properties.name (GeoJSON standard field)
                for item in GeoShape.query.all():
                    feat = item.feature or {}
                    feat_props = feat.get('properties', {})
                    meta = item.meta_json or {}
                    meta_props = meta.get('properties', {})
                    name = (feat_props.get('name') or feat_props.get('label')
                            or meta_props.get('name') or meta_props.get('label')
                            or item.geo_id)
                    if term.lower() in name.lower() or term.lower() in item.geo_id.lower():
                        if item.unique_id not in seen_ids:
                            seen_ids.add(item.unique_id)
                            results.append({
                                "id": item.unique_id,
                                "geo_id": item.geo_id,
                                "name": name,
                                "type": "zone",
                                "device": item.type
                            })

            # Zone-aware expansion: devices carry a SPATIALLY-derived zone (their geo
            # shape's centroid inside a zone polygon). When the query references a zone
            # (e.g. "1-4구역"), include the devices LOCATED in that zone — otherwise
            # "1포장 1-4구역 밸브 켜줘" finds the zone shape but never the valves in it.
            try:
                from aot.ai.services.ai_context_service import AIContextService
                zmap = AIContextService.get_device_zone_map()  # {device_id: zone_name}
            except Exception:
                zmap = {}
            if zmap:
                # Annotate existing device results with their zone.
                for r in results:
                    if r.get('type') in ('input', 'output') and zmap.get(r['id']):
                        r['zone'] = zmap[r['id']]

                def _add_device_by_id(did, zn):
                    if did in seen_ids:
                        return
                    o = Output.query.filter_by(unique_id=did).first()
                    if o:
                        seen_ids.add(did)
                        results.append({"id": o.unique_id, "name": o.name, "type": "output", "device": o.output_type, "zone": zn})
                        return
                    i = Input.query.filter_by(unique_id=did).first()
                    if i:
                        seen_ids.add(did)
                        results.append({"id": i.unique_id, "name": i.name, "type": "input", "device": i.device, "zone": zn})

                zone_index = {}
                for did, zn in zmap.items():
                    zone_index.setdefault(zn, []).append(did)

                # Determine the location the query scopes to, most-specific first.
                # (1) Zone-level: a specific zone is named (e.g. "1-4구역" → "1-4").
                #     Require length ≥2 so a bare "1" in "1포장" doesn't match.
                # (2) Site-level: only when NO specific zone is named — a whole site
                #     (e.g. "3포장" / "site 3"). Zone names follow the "N-M" convention
                #     where N is the site number, so "3포장" → every zone "3-*". A
                #     specific zone always wins over its site ("1포장 1-4구역" → 1-4).
                referenced = {zn for zn in zone_index if zn and len(zn) >= 2 and zn in query}
                allowed_zones = set(referenced)
                if not referenced:
                    def _shape_display_name(s):
                        feat = s.feature or {}
                        if isinstance(feat, str):
                            import json as _json
                            try:
                                feat = _json.loads(feat)
                            except Exception:
                                feat = {}
                        props = feat.get('properties', {}) if isinstance(feat, dict) else {}
                        return str(props.get('name') or props.get('label') or '').strip()

                    # (a) Geometric: the query names an actual 'site' GeoShape → every
                    # descendant zone/feature is in scope, regardless of naming
                    # convention (a zone need not be named "N-M" to belong to site N).
                    from aot.utils.geo_hierarchy import geo_descendant_shapes
                    for site_shape in GeoShape.query.filter_by(type='site').all():
                        s_name = _shape_display_name(site_shape)
                        if s_name and len(s_name) >= 2 and s_name in query:
                            for child in geo_descendant_shapes(site_shape):
                                c_name = _shape_display_name(child)
                                if c_name and c_name in zone_index:
                                    allowed_zones.add(c_name)

                    # (b) Naming-convention fallback ("N포장"/"site N" → zone "N-*") —
                    # kept for zones that follow this convention but whose polygon
                    # isn't (yet) drawn spatially inside the site's polygon.
                    site_nums = set(re.findall(r'(\d+)\s*포장', query))
                    site_nums |= {m for m in re.findall(r'site\s*(\d+)', query, re.IGNORECASE)}
                    if site_nums:
                        for zn in zone_index:
                            m = re.match(r'\s*(\d+)\s*[-–]', zn or '')
                            if m and m.group(1) in site_nums:
                                allowed_zones.add(zn)

                if allowed_zones:
                    # Include every device located in the scoped zones...
                    for zn in allowed_zones:
                        for did in zone_index.get(zn, []):
                            _add_device_by_id(did, zn)
                    # ...and DROP device results that are outside that location. A
                    # location-scoped command ("1포장 1-4구역 밸브") must not sweep in
                    # broad name matches (밸브1..51) that live nowhere near the zone.
                    results = [r for r in results
                               if r.get('type') not in ('input', 'output')
                               or r.get('zone') in allowed_zones]

            if candidate_ids is not None:
                # 이름 검색이 끝난 뒤에 거른다 — 구역 확장까지 마친 집합에
                # 걸어야 "1포장 안의 토양수분 센서" 가 성립한다. 측정을 갖지
                # 않는 종류(구역·카메라)는 이 질문의 답이 아니므로 함께 빠진다.
                results = [r for r in results if r.get('id') in candidate_ids]

            results = AoTDataToolService._annotate_device_membership(results)
            out = {"results": results, "count": len(results)}
            note = AoTDataToolService._complex_device_note(results)
            if note:
                out["_reading"] = [note]
            return out
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _complex_device_note(results):
        """복합장치(PLC 등)가 **실제로 결과에 있을 때만** 그 규칙을 낸다.

        복합장치는 한 물리 장치의 읽기/쓰기가 Input·Output 으로 쪼개져 있어,
        모르면 하위 항목을 독립 장치로 취급하게 된다. 다만 결과에 복합장치가
        없으면 그 설명은 매번 읽히기만 하고 쓰이지 않는다 — 그래서 도구 설명이
        아니라 결과가 말한다.
        """
        rows = results or []
        if not (any(r.get('type') == 'device' and r.get('member_ids') for r in rows)
                or any(r.get('parent_device_id') for r in rows)):
            return None
        return ("A complex device (e.g. a PLC) is in these results: one physical "
                "unit whose readings/controls are split across separate Input and "
                "Output entries. A 'device' row lists its member_ids, and a member "
                "row carries parent_device_id + parent_device_name. Answer and act "
                "at the parent device level rather than treating a member as "
                "standalone.")

    @staticmethod
    def get_device_list_tool(**kwargs):
        """
        Returns all registered devices (inputs, outputs, cameras, complex
        devices) with id/name/type.
        Used for full device listing queries (no keyword filter).

        @ANCHOR: GET_DEVICE_LIST_TOOL
        """
        try:
            results = []
            seen_ids = set()
            for item in Input.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "input", "device": item.device})
            for item in Output.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "output", "device": item.output_type})
            for item in Camera.query.all():
                if item.unique_id not in seen_ids:
                    seen_ids.add(item.unique_id)
                    results.append({"id": item.unique_id, "name": item.name, "type": "camera", "device": item.camera_type})

            # 복합장치(Device) — search_devices() 와 동일한 이유로 목록에도
            # 포함한다. 여기서는 필터가 없으므로 전수 조회.
            try:
                from aot.databases.models.controller import CustomController
                from aot.utils.functions import device_module_names
                _dev_names = device_module_names()
                if _dev_names:
                    for item in CustomController.query.filter(
                            CustomController.device.in_(_dev_names)).all():
                        if item.unique_id not in seen_ids:
                            seen_ids.add(item.unique_id)
                            member_ids = (
                                [i.unique_id for i in Input.query.filter_by(
                                    parent_device_id=item.unique_id).all()] +
                                [o.unique_id for o in Output.query.filter_by(
                                    parent_device_id=item.unique_id).all()]
                            )
                            results.append({
                                "id": item.unique_id, "name": item.name,
                                "type": "device", "device": item.device,
                                "member_ids": member_ids,
                            })
            except Exception:
                pass

            results = AoTDataToolService._annotate_device_membership(results)
            out = {"results": results, "count": len(results)}
            note = AoTDataToolService._complex_device_note(results)
            if note:
                out["_reading"] = [note]
            return out
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_energy_report(period="daily", zone_id=None):
        """
        에너지 사용량 분석 리포트를 생성합니다.
        """
        try:
            # return_energy_usage() calls .filter() on these, so they must stay
            # live Query objects rather than materialized lists.
            device_measurements_all = DeviceMeasurements.query
            conversion_all = Conversion.query

            if zone_id:
                # Input has no parent_id column — location is via GeoShape
                # (map_overlay_id), same pattern as get_sensor_detail().
                target_zone = GeoShape.query.filter(
                    or_(GeoShape.unique_id == zone_id, GeoShape.geo_id == zone_id)
                ).first()
                if not target_zone:
                    return {"message": f"Zone '{zone_id}' not found."}

                # [S3] 소속은 마커 좌표에서 파생 — site/zone 폴리곤이 하위를
                # 기하학적으로 포함하므로 descendant 순회가 필요 없다.
                from aot.aot_flask.geo.device_membership import device_ids_in_shape
                _member_ids = device_ids_in_shape(target_zone)
                input_ids = ([i.unique_id for i in Input.query.filter(
                    Input.unique_id.in_(_member_ids)).all()]
                    if _member_ids else [])
                if not input_ids:
                    return {"message": "No energy sensors found for this zone/period"}
                energy_usage = EnergyUsage.query.filter(EnergyUsage.device_id.in_(input_ids)).all()
            else:
                energy_usage = EnergyUsage.query.all()

            if not energy_usage:
                return {"message": "No energy sensors found for this zone/period"}

            stats, graph = return_energy_usage(energy_usage, device_measurements_all, conversion_all)
            
            # 리포트 가공
            report_data = []
            for uid, val in stats.items():
                target_usage = next((e for e in energy_usage if e.unique_id == uid), None)
                if target_usage:
                    report_data.append({
                        "sensor_id": uid,
                        "device_id": target_usage.device_id,
                        "usage": val
                    })

            summary = f"Energy analysis for {period}."
            if zone_id:
                summary += f" Filtering by Zone: {zone_id}."

            return {
                "summary": summary,
                "data": report_data,
                "insights": ["Usage is within normal parameters."] # Placeholder for AI logic
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_system_update_status(**kwargs):
        """
        AoT 소프트웨어(시스템)의 업데이트 가용 여부를 확인합니다. 읽기 전용.

        현재 설치된 버전(AOT_VERSION)을, 이 설치가 실제로 업그레이드하는 경로의
        정본과 비교합니다 — 네이티브 설치는 GitHub 릴리스 태그, Docker 배포는
        컨테이너 레지스트리(GHCR)입니다. Docker에서 GitHub 태그를 보면 이미지
        빌드가 끝나기 전 구간에서 "설치할 수 없는 업데이트"를 알리게 됩니다.
        조회 실패/rate-limit 시 DB에 캐시된 Misc.aot_upgrade_available 로 폴백합니다.
        """
        try:
            from aot.config import AOT_VERSION
            from aot.utils.update_availability import (check_upgrade_exists,
                                                       is_docker_install,
                                                       running_image_reference,
                                                       updater_status)

            current_version = AOT_VERSION
            update_available = None
            latest_version = None
            available_releases = []
            errors = []

            # 1. 라이브 조회 (관리자 업그레이드 페이지와 동일 경로)
            try:
                (upgrade_exists,
                 releases,
                 _all_tags,
                 current_latest_tag,
                 check_errors) = check_upgrade_exists()
                update_available = bool(upgrade_exists)
                latest_version = current_latest_tag
                available_releases = releases or []
                errors = list(check_errors or [])
            except Exception as e:
                errors.append(str(e))

            # 2. 라이브 조회 실패 시 DB 캐시 플래그로 폴백
            if update_available is None:
                try:
                    mod_misc = Misc.query.first()
                    if mod_misc is not None:
                        update_available = bool(mod_misc.aot_upgrade_available)
                except Exception as e:
                    errors.append(str(e))

            is_docker = is_docker_install()
            source = "container registry (GHCR)" if is_docker else "GitHub release tags"

            if update_available is None:
                return {
                    "current_version": current_version,
                    "update_available": None,
                    "deployment": "docker" if is_docker else "native",
                    "message": (
                        f"Could not check for updates ({source} unreachable or "
                        "rate-limited). Try again later, or check Admin → Upgrade."
                    ),
                    "errors": errors,
                }

            if update_available:
                message = (
                    f"An update is available. Installed version {current_version}"
                    + (f", latest release {latest_version}." if latest_version else ".")
                    + " You can update from Admin → Upgrade."
                )
            else:
                message = f"You are on the latest version (currently {current_version})."

            result = {
                "current_version": current_version,
                "latest_version": latest_version,
                "update_available": update_available,
                "available_releases": available_releases,
                "deployment": "docker" if is_docker else "native",
                "update_source": source,
                "message": message,
                "errors": errors,
            }

            if is_docker:
                # Docker has no in-app upgrade path yet, so say how it is
                # actually applied instead of leaving the caller to assume the
                # Admin → Upgrade button exists.
                result["image"] = running_image_reference()
                result["one_click_update_available"] = updater_status()['present']
                if update_available and not result["one_click_update_available"]:
                    result["message"] += (
                        " This is a Docker install: the update is applied on the"
                        " host by pulling the new image and recreating the"
                        " containers."
                    )

            return result
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def operate_device_tool(device_id, state, **kwargs):
        """
        [분류 A - 물리 제어 전용 도구]
        장치를 직접 제어합니다. (on, off, open, close, set_value 등)
        """
        try:
            if not device_id or not state:
                return {"error": "Missing device_id or state"}

            # 1. 상태값 검증
            ALLOWED_STATES = ['on', 'off', 'open', 'close', 'set_value']
            state = state.lower()
            if state not in ALLOWED_STATES:
                return {"error": f"Invalid state value: {state}. Allowed values: {ALLOWED_STATES}"}

            # 2. 장치 존재 여부 확인 (UUID 또는 이름)
            target = Output.query.filter(or_(Output.unique_id == device_id, Output.name == device_id)).first()
            if not target:
                return {"error": f"Device (output) to control not found: {device_id}"}

            # 3. 시간/값 파라미터 정규화 (Deep Discovery)
            # duration_seconds, duration_minutes, duration, value 등 다양한 variant 대응
            d_sec = kwargs.get('duration_seconds')
            d_min = kwargs.get('duration_minutes') or kwargs.get('duration')
            val = kwargs.get('value')
            
            # 우선순위: duration_seconds > duration_minutes/duration (*60) > value > 0
            if d_sec is not None:
                duration = float(d_sec)
            elif d_min is not None:
                duration = float(d_min) * 60.0
            else:
                duration = float(val or 0)

            # 4. @ANCHOR: OPERATE_DEVICE_CHANNEL_INJECTION (TASK_17)
            # Resolve physical output_channel from OutputChannel table before daemon call.
            # Eliminates 'output channel doesn't exist: None' — channel=0 is a valid integer.
            resolved_uid = target.unique_id
            output_channel = None
            try:
                from aot.databases.models.output import OutputChannel as _OC
                oc_row = _OC.query.filter_by(output_id=resolved_uid).first()
                if oc_row is not None and oc_row.channel is not None:
                    output_channel = int(oc_row.channel)
                    logger.info(
                        f"[operate_device_tool][CHANNEL_RESOLVED] "
                        f"device='{resolved_uid}' → output_channel={output_channel}"
                    )
                else:
                    # [PC-099-ERROR] DB diagnostic: row exists but channel is NULL, or no row at all
                    _diag = (
                        f"oc_row={oc_row!r}, "
                        f"channel={oc_row.channel if oc_row else 'NO_ROW'}, "
                        f"output_type='{target.output_type}'"
                    )
                    logger.error(
                        f"[PC-099-ERROR][CHANNEL_NULL] output_channel is None for "
                        f"device='{resolved_uid}'. DB diagnostic: {_diag}. "
                        f"Daemon call will proceed with channel=None — expect hardware error."
                    )
            except Exception as _ch_err:
                logger.error(
                    f"[PC-099-ERROR][CHANNEL_LOOKUP_FAILED] OutputChannel query failed "
                    f"for device='{resolved_uid}': {_ch_err}"
                )

            from aot.aot_client import DaemonControl
            daemon = DaemonControl()

            # AI 가 낸 명령임을 명시한다. 이 도구는 웹 요청 문맥 안에서도(사용자가
            # AI 에게 시킨 경우) MCP 서버 프로세스에서도 불린다. 표시가 없으면
            # 앞은 사람이 직접 누른 것과 구분되지 않고, 뒤는 출처 불명(unknown)으로
            # 남아 우회 접근 탐지 신호를 흐린다. override 라 요청 문맥보다 우선한다.
            set_execution_context(
                source_type=TYPE_AI,
                source_id=kwargs.get('agent_id') or 'operate_device')
            try:
                if state in ('on', 'open'):
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'on', output_type='sec', amount=duration,
                        output_channel=output_channel
                    )
                elif state in ('off', 'close'):
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'off', output_type='sec', amount=0,
                        output_channel=output_channel
                    )
                elif state == 'set_value':
                    out_err, out_msg = daemon.output_on_off(
                        resolved_uid, 'on', output_type='value', amount=duration,
                        output_channel=output_channel
                    )
                else:
                    return {"error": f"Unsupported state: {state}"}
            finally:
                clear_execution_context()

            if out_err:
                logger.error(f"[operate_device_tool] Daemon error: {out_msg}")
                return {"error": f"Device control failed: {out_msg}"}
            
            logger.info(f"[operate_device_tool] OK: device={resolved_uid}({target.name}), state={state}, duration={duration}s")
            return {"status": "success", "execution_result": out_msg, "resolved_duration": duration}
        except Exception as e:
            logger.error(f"Error in operate_device_tool: {e}")
            return {"error": f"Error while controlling device: {str(e)}"}

    @staticmethod
    def _extract_spatial_tags(content):
        """내용에서 공간(장소/장치) 이름을 추출하여 태그 형태로 반환합니다."""
        if not content:
            return ""
        
        try:
            # 1. 공간 계층 구조 가져오기
            hierarchy = AIContextService.get_spatial_hierarchy()
            
            # 2. 모든 장소 이름 수집 (재귀적)
            all_names = set()
            def collect_names(nodes):
                for node in nodes:
                    if 'name' in node:
                        all_names.add(node['name'])
                    if 'children' in node:
                        collect_names(node['children'])
            
            collect_names(hierarchy)
            
            # 3. 매칭되는 이름 찾기
            found_tags = []
            for name in all_names:
                if name in content:
                    # 중복 방지를 위해 #를 붙여서 추가
                    tag = f"#{name.replace(' ', '_')}"
                    if tag not in found_tags:
                        found_tags.append(tag)
            
            return ", ".join(found_tags) if found_tags else ""
        except Exception as e:
            logger.error(f"Error in _extract_spatial_tags: {e}")
            return ""

    @staticmethod
    def add_schedule_tool(date, content, worker=None, time="09:00", tags=None,
                          target_name=None, **extra):
        """
        [분류 B - 일정/계획 전용 도구]
        사람의 작업/이벤트 일정(제초·방제·정식·수확·점검·출하 등)을 등록합니다.
        (SchedulerJobMeta 기반, action_type='human')
        Routing: propose_job(action_type='human') -> approve_job(decided_by='AI')
        No APScheduler trigger is created for human-type schedules.

        위치 연결: target_name(구역/시설/장치 이름, 예 '온실', '3-1', '1포장 1-1')을 주면
        _resolve_note_target로 실제 엔티티(target_id)에 붙여 지도·위치별 조회가 성립합니다.
        모호/미해석이면 available_targets를 돌려주니 ask_user로 확인 후 재시도하세요.
        위치를 특정하지 않는 농장 전체 일정이면 target_name 없이 등록합니다(떠 있는 일정).
        """
        try:
            from aot.ai.services.ai_scheduler_service import AISchedulerService

            # LLM aliases for the location name.
            if not target_name:
                target_name = extra.pop('location', None) or extra.pop('zone_name', None) \
                    or extra.pop('place', None) or extra.pop('entity_name', None)

            # 1. Resolve location FIRST — the target's tz is the wall-clock anchor
            #    (device-local is the confirmed policy, timezone-management.md §6).
            #    run_at is computed in step 2 once the anchor is known. Do NOT
            #    silently create a floating (target_id='none') schedule when the user
            #    named a place — same orphan footgun the notes tool guards against.
            target_id = 'none'
            target_type = None
            resolved_name = None
            if target_name:
                _tid, _tt, resolved_name, _lat, _lng = \
                    AoTDataToolService._resolve_note_target(target_name)
                if not _tid:
                    return {
                        "status": "needs_disambiguation",
                        "error": "target_not_found",
                        "message": (f"위치 '{target_name}'를 특정하지 못했습니다. "
                                    f"available_targets에서 정확한 이름을 고르도록 ask_user로 "
                                    f"확인한 뒤 다시 등록하세요."),
                        "available_targets": AoTDataToolService._geoshape_name_candidates(),
                    }
                target_id = _tid
                target_type = _tt

            # 2. Anchor the wall-clock to the target's local tz, then store as UTC.
            _anchor_tz, _anchor_name, _anchor_src = \
                AoTDataToolService._resolve_schedule_anchor(target_id)
            run_at = AoTDataToolService._schedule_wall_to_utc(date, time, anchor_tz=_anchor_tz)

            # 3. Build reasoning + params
            job_name = content if not worker else f"{content} (worker: {worker})"
            spatial_tags = tags or AoTDataToolService._extract_spatial_tags(content)
            tag_label = "ai_scheduled, human_work"
            if spatial_tags:
                tag_label += f", {spatial_tags}"
            reasoning = f"[human_schedule] {job_name}"
            if resolved_name:
                reasoning += f" @ {resolved_name}"
            reasoning += f" | tags: {tag_label}"

            params = {'content': content, 'worker': worker or '', 'tags': tag_label}
            if target_type:
                params['target_type'] = target_type
            if resolved_name:
                params['target_name'] = resolved_name

            # 4. Propose job as DRAFT (source_type='human' marks it as a human work item)
            meta = AISchedulerService.propose_job(
                action_type='human',
                target_id=target_id,
                params=params,
                reasoning=reasoning,
                schedule_time=run_at,
                proposed_by='AI',
                approval_required=False,
                source_type='human',
            )

            # 5. Immediately approve — no APScheduler trigger for human schedules
            AISchedulerService.approve_job(meta.id, decided_by='AI')

            # Persist the tz anchor so display can re-derive device-local time.
            try:
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src
                from aot.databases.models import db as _db
                _db.session.commit()
            except Exception:
                pass

            result = {
                "status": "success",
                "message": f"Schedule registered: {date} {time} ({_anchor_name}) - {content}",
                "job_id": meta.unique_id,
                "tags": tag_label,
            }
            if target_id != 'none':
                result["attached_to"] = resolved_name or target_id
                result["target_id"] = target_id
                result["target_type"] = target_type
            else:
                result["attached"] = False
                result["note_hint"] = ("위치 미지정 — 특정 구역/시설에 표시되지 않는 "
                                       "농장 전체 일정입니다.")
            return result
        except Exception as e:
            logger.error(f"Error in add_schedule_tool: {e}")
            return {"error": f"Error while registering schedule: {str(e)}"}

    @staticmethod
    def _hhmm_to_minutes(hhmm):
        try:
            h, m = str(hhmm).split(':')
            return int(h) * 60 + int(m)
        except Exception:
            return None

    @staticmethod
    def validate_schedule_batch(entries, content=None, window_start=None,
                                window_end=None, duration_minutes=60):
        """
        Pure validation, no writes - shared by the MCP approval gate (so a bad
        batch is caught BEFORE a human ever sees an approval prompt for it,
        not after) and by add_schedule_batch_tool itself (defense in depth for
        any caller that reaches the handler through a path other than the
        gate). Returns None when the batch is fine, or an error dict when not.

        Checks, in order:
          1. entries is a non-empty list.
          2. content is available (shared or per-entry) for every entry.
          3. No target_name repeated within the batch.
          4. LEAF-ONLY: no entry's target_name may resolve to a container
             (a site with child zones). Confirmed 2026-07-26: an advisory
             warning here was not enough - a different model called
             resolve_target, saw the child zones, and used the site name
             anyway. A batch's whole purpose is one entry per leaf unit, so
             this is a hard rejection (nothing created), not a note attached
             to something that still gets approved.
          5. Every entry's time <= window_end, if window_end is given.
          6. CAPACITY: len(entries) * duration_minutes must fit inside
             window_end - window_start, if BOTH are given. This is the check
             that catches "9 zones x 1h each into a 4h window" BEFORE any
             time is assigned per entry - pure arithmetic, not something the
             caller needs to reason through correctly on its own.
        """
        if not entries or not isinstance(entries, list):
            return {"status": "error", "message": "entries must be a non-empty list"}
        if not content and not all(e.get('content') for e in entries):
            return {"status": "error",
                    "message": "content is required (either shared, or set per-entry on every entry)"}

        names = [e.get('target_name') for e in entries]
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        if dupes:
            return {
                "status": "error",
                "error": "duplicate_target",
                "message": f"target_name repeated within the same batch: {dupes}",
            }

        containers = []
        for n in sorted({n for n in names if n}):
            try:
                r = AoTDataToolService.resolve_target_tool(n)
            except Exception:
                continue
            if r.get('children'):
                containers.append({
                    "target_name": n,
                    "target_type": r.get('target_type'),
                    "children": r.get('children'),
                })
        if containers:
            return {
                "status": "error",
                "error": "container_target_in_batch",
                "message": (
                    f"{len(containers)} entr(y/ies) target a container (site), not a "
                    f"single leaf zone: {[c['target_name'] for c in containers]}. Nothing "
                    f"was created. A batch entry must target one leaf unit - expand each "
                    f"container to its 'children' below and add one entry per child "
                    f"instead of one entry for the whole container."),
                "container_entries": containers,
            }

        if window_end:
            bad = [e for e in entries if not e.get('time') or e['time'] > window_end]
            if bad:
                return {
                    "status": "error",
                    "error": "outside_window",
                    "message": f"{len(bad)} entr(y/ies) fall after window_end={window_end}. "
                               f"Nothing was created - fix the times and retry.",
                    "offending_entries": bad,
                }

        if window_start and window_end:
            _start_min = AoTDataToolService._hhmm_to_minutes(window_start)
            _end_min = AoTDataToolService._hhmm_to_minutes(window_end)
            if _start_min is not None and _end_min is not None and _end_min > _start_min:
                _available = _end_min - _start_min
                _required = len(entries) * duration_minutes
                if _required > _available:
                    return {
                        "status": "error",
                        "error": "insufficient_window",
                        "message": (
                            f"{len(entries)} entries x {duration_minutes}min = {_required}min "
                            f"needed, but window {window_start}-{window_end} only has "
                            f"{_available}min. Nothing was created. This does not fit in one "
                            f"day as given - either (a) call this tool once per date, splitting "
                            f"entries across multiple dates so each date's entries fit the "
                            f"window, or (b) ask the user how the work should be compressed or "
                            f"parallelized, then retry with entries/duration_minutes that fit."),
                        "required_minutes": _required,
                        "available_minutes": _available,
                        "entries_count": len(entries),
                        "duration_minutes": duration_minutes,
                    }
        return None

    @staticmethod
    def add_schedule_batch_tool(date, entries, content=None, worker=None,
                                tags=None, window_start=None, window_end=None,
                                duration_minutes=60, **extra):
        """
        [Human task / memo, BATCH] Register MULTIPLE per-entity work schedules
        in ONE call, gated by a SINGLE approval instead of one approval (and
        one rate-limited request slot) per entry.

        Use this instead of N separate add_schedule calls whenever a request
        applies per sub-unit ('각 구역별로', 'each zone') — call resolve_target
        on the container name first to get the exact child names to put in
        `entries`.

        Args:
            date (str): Shared date (YYYY-MM-DD) for every entry.
            entries (list[dict]): [{target_name (required), time (required,
                HH:MM), content (optional, overrides the shared `content`),
                worker (optional, overrides the shared `worker`)}, ...].
                Duplicate target_name within the same batch is rejected.
            content/worker/tags: Shared defaults used by any entry that omits
                its own content/worker. `content` is required unless every
                entry supplies its own.
            window_start/window_end (str, optional): 'HH:MM'. window_end alone
                rejects any entry whose time falls after it. BOTH together
                additionally validate that len(entries) * duration_minutes
                actually fits the window - if not, the whole batch is
                rejected up front (nothing created) instead of silently
                accepting a schedule that cannot physically happen in one day.
            duration_minutes (int, default 60): assumed minutes per entry,
                used only for the capacity check above.
        """
        _err = AoTDataToolService.validate_schedule_batch(
            entries, content=content, window_start=window_start,
            window_end=window_end, duration_minutes=duration_minutes)
        if _err:
            return _err

        results = []
        for e in entries:
            r = AoTDataToolService.add_schedule_tool(
                date=date,
                content=e.get('content') or content,
                worker=e.get('worker') or worker,
                time=e.get('time', '09:00'),
                tags=tags,
                target_name=e.get('target_name'),
            )
            results.append({"target_name": e.get('target_name'), "time": e.get('time'), "result": r})

        failed = [r for r in results if not r['result'].get('job_id')]
        return {
            "status": "success" if not failed else "partial_failure",
            "count": len(results),
            "failed_count": len(failed),
            "results": results,
        }

    @staticmethod
    def search_notes_tool(query=None, category=None, limit=10,
                          target_name=None, target_id=None, **extra):
        """
        [분류 C - 노트/일정 읽기 도구]
        노트(메모, 일정, 작업 기록)를 조회합니다. 두 가지 모드:

        1) 위치/엔티티별 조회 (권장): target_name 또는 target_id를 주면 그 구역·
           장치에 부착된 노트를 모두 반환합니다. "3-1 구역 노트 요약" 같은 요청은
           반드시 이 모드로 — 노트는 target_id로 엔티티에 붙어 있고 본문에 구역명이
           없을 수 있어 키워드 검색으로는 안 잡힙니다.
        2) 키워드 검색: query로 name/tags/note LIKE 검색.

        Args:
            query (str): 검색 키워드. target_name과 함께 주면 그 엔티티 내에서 추가 필터.
            category (str): 카테고리 필터. None이면 전체.
            limit (int): 최대 반환 건수(기본 10).
            target_name (str): 노트가 붙은 위치/장치 이름(예: '3-1', '1포장 1-1', '밸브1').
            target_id (str): 대상 unique_id(이미 아는 경우 target_name 대신).
        """
        try:
            if not target_name:
                target_name = extra.get('location') or extra.get('zone_name') or extra.get('place')

            from aot.databases.models.notes import Notes
            from sqlalchemy import or_

            resolved_name = None
            candidate_ids = []
            # Resolve a location/entity NAME → ALL candidate target_ids. A device
            # exists as an Input/Output row AND as map shape(s) with different
            # unique_ids, and a note may be attached to any of them — so query the
            # union, not just the single most-specific match.
            scope = None
            if target_id:
                candidate_ids = [target_id]
            elif target_name:
                # 대상 안에서 일어나는 일 **전부** — 구역·시설·장치·식생.
                # 예전에는 site 일 때만 자손 도형을 붙였고, 식생은 GeoShape 가
                # 아니라 어느 층위에서도 보이지 않았다(2026-08-18 실측: 구역을
                # 물어도 그 안 식생 노트가 0건).
                candidate_ids, scope = \
                    AoTDataToolService._scope_for_target(target_name)
                resolved_name = scope.get('resolved_name')
                if not candidate_ids:
                    return {
                        "status": "success", "count": 0, "results": [],
                        "scope": scope,
                        "message": f"Location/device '{target_name}' was not found.",
                        "warning": (
                            "The name did not resolve, so this is NOT evidence "
                            "that there are no notes. Ask for the exact name, or "
                            "call resolve_target first."),
                    }

            # The LLM frequently passes an ENTITY NAME in `query` instead of
            # `target_name` (observed: {'query': 'v111'}). A note's text rarely
            # contains the entity's name, so a pure keyword search misses it and
            # wrongly reports "no notes". If `query` resolves to an entity, treat
            # it as a target too (and skip the keyword LIKE that would AND it back
            # to zero). Only when nothing resolves is `query` a real keyword.
            entity_query = False
            if not candidate_ids and query and query.strip():
                _q_ids, _q_name = \
                    AoTDataToolService._resolve_note_target_ids(query.strip())
                if _q_ids:
                    candidate_ids = _q_ids
                    resolved_name = resolved_name or _q_name
                    entity_query = True

            if not candidate_ids and not (query and query.strip()):
                return {"error": "Either 'query' or 'target_name' (a location/device) is required."}

            db_query = Notes.query.filter(Notes.is_archived == False)  # noqa: E712

            if candidate_ids:
                # Per-entity read — matches the web UI /notes/target/<id>, but
                # across every identity the named device/shape resolves to.
                db_query = db_query.filter(Notes.target_id.in_(candidate_ids))
            if query and query.strip() and not entity_query:
                _q = f"%{query.strip()}%"
                db_query = db_query.filter(or_(
                    Notes.name.like(_q), Notes.tags.like(_q), Notes.note.like(_q)))
            if category:
                db_query = db_query.filter(Notes.category == category)

            rows = db_query.order_by(Notes.date_time.desc()).limit(limit).all()

            if not rows:
                _where = (f"location/device '{resolved_name or target_name}'"
                          if (target_name or target_id) else f"query '{query}'")
                out = {
                    "status": "success", "count": 0, "results": [],
                    "message": f"No notes found for {_where}.",
                }
                # 무엇을 훑고 0건인지 말한다 — 그래야 "정말 없다" 와 "못
                # 찾았다" 가 구분된다.
                if scope is not None:
                    out["scope"] = scope
                return out

            # Each note displays in ITS OWN location tz (the device/zone/site it is
            # attached to) — consistent with how that entity's schedules show device
            # tz. A located note "at 3-1 06:00" should read 06:00 there, not in the
            # system clock. Cached per target_id (search is usually one target). §7
            _tz_by_target = {}
            from aot.utils.timekit import to_tz

            def _note_tzname(tid):
                if not tid:
                    return None
                if tid not in _tz_by_target:
                    try:
                        from aot.utils.device_tz import resolve_location_tz
                        _tz_by_target[tid] = str(resolve_location_tz(tid))
                    except Exception:
                        _tz_by_target[tid] = None
                return _tz_by_target[tid]

            # A site query now pulls notes from every descendant zone too (see
            # _resolve_note_target_ids), so a bare target_id is no longer enough
            # for the AI to tell WHICH zone a note belongs to — resolve each
            # note's own entity display name alongside it.
            _name_by_target = {}
            import json as _json

            def _note_target_name(tid):
                if not tid:
                    return None
                if tid not in _name_by_target:
                    _nm = None
                    try:
                        shape = GeoShape.query.filter_by(unique_id=tid).first()
                        if shape:
                            feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                            props = feat.get('properties') or {}
                            _nm = str(props.get('name') or props.get('label') or props.get('title') or '').strip() or None
                    except Exception:
                        _nm = None
                    if not _nm:
                        try:
                            for model in (Input, Output):
                                row = model.query.filter_by(unique_id=tid).first()
                                if row:
                                    _nm = row.name
                                    break
                        except Exception:
                            pass
                    # 식생·시설은 GeoShape 가 아니다. 이름이 없으면 AI 는 "어느
                    # 구획 것인지" 를 구분할 수 없는데, 이 도구는 site 를 물으면
                    # 그 아래 전부를 돌려주므로 구분이 곧 답의 정확도가 된다.
                    if not _nm:
                        try:
                            from aot.databases.models import GeoPlot, GeoFacility
                            pl = GeoPlot.query.filter_by(unique_id=tid).first()
                            if pl is not None:
                                _nm = pl.name or pl.subject
                            else:
                                fac = GeoFacility.query.filter_by(unique_id=tid).first()
                                if fac is not None:
                                    _nm = getattr(fac, 'name', None)
                        except Exception:
                            pass
                    _name_by_target[tid] = _nm
                return _name_by_target[tid]

            results = []
            for r in rows:
                # r.date_time is stored naive-UTC (SQLite). Display in the note's
                # location tz when it has one, else the system tz.
                _ntz = _note_tzname(r.target_id)
                if r.date_time:
                    if _ntz:
                        _date = to_tz(r.date_time, _ntz).strftime("%Y-%m-%d %H:%M")
                    else:
                        _date = to_local(r.date_time).strftime("%Y-%m-%d %H:%M")
                else:
                    _date = None
                results.append({
                    "note_id": r.unique_id,
                    "date": _date,
                    "date_tz": _ntz,
                    "name": r.name,
                    "category": r.category,
                    "tags": r.tags,
                    # Full content (up to 2000 chars) so the AI can SUMMARIZE — a
                    # 300-char cut dropped photos/plans and made summaries wrong.
                    "note": (r.note or "")[:2000],
                    "target_id": r.target_id,
                    "target_type": r.target_type,
                    "target_name": _note_target_name(r.target_id),
                })

            out = {
                "status": "success",
                "count": len(results),
                "results": results,
                "query": query,
                "target": resolved_name or target_name or target_id,
            }
            if scope is not None:
                out["scope"] = scope
            return out
        except Exception as e:
            logger.error(f"Error in search_notes_tool: {e}")
            return {"error": f"Error while querying notes: {str(e)}"}

    @staticmethod
    def get_facility_capacity_tool(facility_name=None, **extra):
        """[분류 C - 설비 성능/용량 읽기 도구]
        geo/design(지도 디자인)에서 그린 시설(온실/축사 등 GeoFacility)의 설계
        산출값을 조회한다 — 냉난방 참조 용량, 체적/바닥/피복 면적, 환기(ACH·
        개구부 면적), 그리고 관수(배관·에미터 수·유량) 요약, 바인딩된 제어장치 수.

        값은 저장된 캐시가 아니라 요청 시 compute_capacity 로 산출되는 공학적
        참조 추정치(±5~10%)다. facility_name 을 주면 부분일치로 찾고, 생략하면
        전체 시설을 반환한다. 읽기 전용.
        """
        try:
            from aot.databases.models import GeoFacility
            from aot.aot_flask.geo.facility_integration import get_facility_integration

            if not facility_name:
                facility_name = extra.get('name') or extra.get('target_name')

            q = GeoFacility.query
            if facility_name and str(facility_name).strip():
                fname = str(facility_name).strip()
                rows = q.filter(GeoFacility.name.ilike(f"%{fname}%")).all()
                if not rows:
                    # facility_name may actually name a SITE (포장), not a facility —
                    # a site has no GeoFacility of its own, but its descendant
                    # zones/buildings might. Expand via the site's geometry.
                    def _shape_display_name(s):
                        feat = s.feature or {}
                        if isinstance(feat, str):
                            import json as _json
                            try:
                                feat = _json.loads(feat)
                            except Exception:
                                feat = {}
                        props = feat.get('properties', {}) if isinstance(feat, dict) else {}
                        return str(props.get('name') or props.get('label') or '').strip()

                    site_shape = None
                    for s in GeoShape.query.filter_by(type='site').all():
                        s_name = _shape_display_name(s)
                        if s_name and (fname.lower() in s_name.lower() or s_name.lower() in fname.lower()):
                            site_shape = s
                            break
                    if site_shape:
                        from aot.utils.geo_hierarchy import geo_descendant_unique_ids
                        descendant_ids = geo_descendant_unique_ids(site_shape)
                        if descendant_ids:
                            rows = q.filter(GeoFacility.shape_uuid.in_(descendant_ids)).all()
                if not rows:
                    return {
                        "status": "success", "count": 0, "results": [],
                        "message": f"Facility '{facility_name}' was not found.",
                        "available_facilities": [f.name for f in q.all()],
                    }
            else:
                rows = q.all()

            def _r(x, n=1):
                try:
                    return round(float(x), n)
                except (TypeError, ValueError):
                    return x

            results = []
            for f in rows:
                res, err = get_facility_integration(f.unique_id)
                if err or not res:
                    results.append({"name": f.name, "error": err or "no integration data"})
                    continue
                comp = res.get('computed') or {}
                cm = res.get('capacity_meta') or {}
                irr = res.get('irrigation_summary') or {}
                irr_tot = irr.get('totals') or {}
                results.append({
                    "name": res.get('name') or f.name,
                    "structure": getattr(f, 'structure', None),
                    "bay_count": getattr(f, 'bay_count', None),
                    "capacity": {
                        "floor_m2": _r(comp.get('floor_m2')),
                        "volume_m3": _r(comp.get('volume_m3')),
                        "glazing_m2": _r(comp.get('glazing_m2')),
                        "heating_kw": _r(comp.get('heating_kw')),
                        "cooling_kw": _r(comp.get('cooling_kw')),
                        "nameplate_heating_kw": _r(comp.get('nameplate_heating_kw')),
                        "nameplate_cooling_kw": _r(comp.get('nameplate_cooling_kw')),
                        "ach_total": _r(comp.get('ach_total')),
                        "vent_open_m2": _r(comp.get('vent_open_m2')),
                        "u_effective": cm.get('u_effective'),
                    },
                    "irrigation": {
                        "total_length_m": _r(irr_tot.get('length_m')),
                        "emitters": irr_tot.get('emitters'),
                        "flow_lpm": _r(irr_tot.get('flow_lpm')),
                        "flow_lph": _r(irr_tot.get('flow_lph')),
                        "layers": [
                            {"name": L.get('name'),
                             "pipe_count": L.get('pipe_count'),
                             "device_count": L.get('device_count')}
                            for L in (irr.get('layers') or [])
                        ],
                    },
                    "bound_actuators": len(res.get('actuators_resolved') or []),
                    "_note": comp.get('_note')
                             or "Engineering reference estimate (±5-10%), not a nameplate rating.",
                })
            return {"status": "success", "count": len(results), "results": results}
        except Exception as e:
            logger.error(f"Error in get_facility_capacity_tool: {e}")
            return {"error": str(e)}

    # geo/design equipment spec fields (KIND_META/SPEC_META in aot-facility-design.js).
    _EQUIP_SPEC_FIELDS = ('flow_lph', 'pressure_kpa', 'capacity_kw', 'airflow_cmh',
                          'power_w', 'stroke_m', 'speed_m_per_min', 'coverage_pct', 'fuel')
    # Discrete named devices worth listing one-by-one (KIND_META allowlist). Pipes
    # and generated emitters are HIGH-COUNT (hundreds) — aggregate, never list each.
    _EQUIP_DISCRETE_SUBTYPES = (
        'irrigation_valve', 'exhaust_fan', 'circulation_fan', 'heater', 'cooler',
        'heat_pump', 'side_window_motor', 'roof_vent_motor', 'thermal_curtain_motor',
        'shade_curtain_motor',
    )
    # The emitter unit geo/design counts as "점적기" IS the sprinkler_coverage
    # feature (each carries radius + flow); the bare 'sprinkler' Points are hidden
    # center dots. Pipes are LineStrings. This mirrors the design-panel algorithm
    # in aot-map-utils.js calculatePolygonStats.
    _EQUIP_MAIN_SUBTYPES = ('pipe_main', 'main')
    _EQUIP_BRANCH_SUBTYPES = ('pipe_branch', 'branch')

    @staticmethod
    def _extract_map_equipment(shapes, area_name=None):
        """Pure classifier — reproduces the geo/design design-info panel numbers
        (면적/주배관/점적기/유량) for map-drawn equipment, per site/zone.

        KEY: equipment is attributed to its zone/site by the ownership link
        already in the data — feature.properties.parent_node_id / zone_id ==
        that shape's node_id — NOT by re-counting via point-in-polygon (that is
        exactly the 'hard way'; the design panel uses the logical link, with a
        spatial fallback only for orphans). Emitters (점적기) are the
        sprinkler_coverage features (each with a `flow`); pipes are summed by
        geodesic length. Separated from DB access so it is unit-testable with
        synthetic features.

        Returns {equipment:[discrete devices], irrigation:[per-area summary]}."""
        import json as _json
        import math as _math
        try:
            from shapely.geometry import shape as _shape
            _have_shapely = True
        except Exception:
            _have_shapely = False

        S = AoTDataToolService
        _aql = (area_name or '').strip().lower()

        # 1) Ownership index: node_id → area name; name → node_ids; polygons (fallback).
        node2name = {}
        name2nodes = {}
        containers = []  # (name, polygon)
        for s in shapes:
            if s.type not in ('site', 'zone'):
                continue
            try:
                feat = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
            except Exception:
                continue
            props = feat.get('properties') or {}
            nm = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
            nid = props.get('node_id')
            if nid:
                node2name[nid] = nm
                name2nodes.setdefault(nm.lower(), set()).add(nid)
            if _have_shapely and feat.get('geometry'):
                try:
                    g = _shape(feat['geometry'])
                    if g.is_valid and g.geom_type in ('Polygon', 'MultiPolygon'):
                        containers.append((nm, g, g.area))
                except Exception:
                    pass
        containers.sort(key=lambda c: c[2])  # smallest (most specific) first
        area_node_ids = name2nodes.get(_aql, set()) if _aql else set()
        area_polys = [g for (nm, g, _a) in containers if nm.lower() == _aql] if _aql else []

        def _spatial_area(geom):
            if not (_have_shapely and geom):
                return None
            try:
                g = _shape(geom)
                pt = g if g.geom_type == 'Point' else g.centroid
                for nm, poly, _a in containers:
                    if poly.contains(pt):
                        return nm
            except Exception:
                return None
            return None

        def _locate(props, geom):
            par = props.get('parent_node_id') or props.get('zone_id')
            if par in node2name:
                return node2name[par]
            return _spatial_area(geom)

        def _in_area(props, geom):
            if not _aql:
                return True
            par = props.get('parent_node_id') or props.get('zone_id')
            if par in area_node_ids:
                return True
            if par in node2name:  # owned by a DIFFERENT named area
                return False
            if area_polys and _have_shapely and geom:  # orphan → spatial fallback
                try:
                    g = _shape(geom)
                    pt = g if g.geom_type == 'Point' else g.centroid
                    return any(poly.contains(pt) for poly in area_polys)
                except Exception:
                    return False
            return False

        def _line_len_m(geom):
            if not geom or geom.get('type') != 'LineString':
                return 0.0
            cs = geom.get('coordinates') or []
            tot, R = 0.0, 6371000.0
            for i in range(1, len(cs)):
                lon1, lat1, lon2, lat2 = cs[i - 1][0], cs[i - 1][1], cs[i][0], cs[i][1]
                p1, p2 = _math.radians(lat1), _math.radians(lat2)
                a = (_math.sin(_math.radians(lat2 - lat1) / 2) ** 2
                     + _math.cos(p1) * _math.cos(p2) * _math.sin(_math.radians(lon2 - lon1) / 2) ** 2)
                tot += 2 * R * _math.asin(min(1.0, _math.sqrt(a)))
            return tot

        # 2) Gather equipment features.
        equip_features = []
        for s in shapes:
            if s.type == 'equipment_collection':
                try:
                    coll = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                    equip_features.extend(coll.get('features') or [])
                except Exception:
                    continue
            elif s.type == 'equipment':
                try:
                    equip_features.append(s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}'))
                except Exception:
                    continue

        # 3) Classify.
        discrete = []
        agg = {}

        def _slot(loc):
            return agg.setdefault(loc, {
                # 스프링클러 (individual sprinkler_coverage features, each with flow)
                "sprinklers": 0, "sprinkler_flow_lph": 0.0,
                # 점적 (drip — derived from is_drip pipes: count = length / interval)
                "drip_emitters": 0, "drip_flow_lph": 0.0,
                "main_pipes": 0, "main_pipe_length_m": 0.0,
                "branch_pipes": 0, "branch_pipe_length_m": 0.0})

        for f in equip_features:
            if not isinstance(f, dict):
                continue
            props = f.get('properties') or {}
            geom = f.get('geometry')
            sub = props.get('sub_type') or props.get('equipment_type')
            if not sub or not _in_area(props, geom):
                continue
            # 스프링클러: sprinkler_coverage is the canonical saved sprinkler (the
            # bare 'sprinkler' point dots are ephemeral/filtered). Mirrors
            # aot-map-utils.js calculatePolygonStats isSprinkler.
            if (sub == 'sprinkler_coverage' or props.get('device_type') == 'sprinkler'
                    or props.get('aot_type') == 'sprinkler'):
                slot = _slot(_locate(props, geom) or '(unassigned)')
                slot['sprinklers'] += 1
                try:
                    slot['sprinkler_flow_lph'] += float(props.get('flow') or props.get('flow_rate') or 0)
                except (TypeError, ValueError):
                    pass
            elif sub in S._EQUIP_MAIN_SUBTYPES or sub in S._EQUIP_BRANCH_SUBTYPES:
                slot = _slot(_locate(props, geom) or '(unassigned)')
                length = _line_len_m(geom)
                if sub in S._EQUIP_MAIN_SUBTYPES:
                    slot['main_pipes'] += 1
                    slot['main_pipe_length_m'] += length
                else:
                    slot['branch_pipes'] += 1
                    slot['branch_pipe_length_m'] += length
                # 점적: a drip pipe carries emitters spaced along it — the design
                # counts them as length / interval (NOT individual features).
                if props.get('is_drip'):
                    dc = props.get('drip_config') or {}
                    try:
                        interval = float(dc.get('interval') or 1.0)
                    except (TypeError, ValueError):
                        interval = 1.0
                    try:
                        dflow = float(dc.get('flow') or 0)
                    except (TypeError, ValueError):
                        dflow = 0.0
                    dcount = int(length / interval) if interval > 0 else 0
                    slot['drip_emitters'] += dcount
                    slot['drip_flow_lph'] += dcount * dflow
            elif sub in S._EQUIP_DISCRETE_SUBTYPES:  # valves/fans/heaters/motors
                specs = {k: props[k] for k in S._EQUIP_SPEC_FIELDS if props.get(k) not in (None, '')}
                discrete.append({
                    "name": props.get('name') or props.get('label') or sub,
                    "sub_type": sub,
                    "location": _locate(props, geom),
                    "specs": specs,
                })
            # else: bare 'sprinkler' center dots / ref_line / unknown → skip

        def _r1(x):
            return round(x, 1) if x else None

        irrigation = []
        for loc, s in agg.items():
            total_flow = s['sprinkler_flow_lph'] + s['drip_flow_lph']
            method = ('sprinkler' if s['sprinklers'] and not s['drip_emitters']
                      else 'drip' if s['drip_emitters'] and not s['sprinklers']
                      else 'mixed' if s['sprinklers'] and s['drip_emitters'] else None)
            irrigation.append({
                "area": loc,
                "method": method,                       # sprinkler | drip | mixed
                "sprinklers": s['sprinklers'],          # 스프링클러 헤드 수
                "sprinkler_flow_lph": _r1(s['sprinkler_flow_lph']),
                "drip_emitters": s['drip_emitters'],    # 점적기 수 (배관 길이 기반)
                "drip_flow_lph": _r1(s['drip_flow_lph']),
                "total_flow_lph": _r1(total_flow),
                "total_flow_lpm": _r1(total_flow / 60.0) if total_flow else None,
                "main_pipes": s['main_pipes'],
                "main_pipe_length_m": _r1(s['main_pipe_length_m']),
                "branch_pipes": s['branch_pipes'],
                "branch_pipe_length_m": _r1(s['branch_pipe_length_m']),
            })
        return {"equipment": discrete, "irrigation": irrigation}

    @staticmethod
    def get_map_equipment_tool(area_name=None, **extra):
        """[분류 C - 지도 설비(equipment) 읽기 도구]
        geo/design(지도 디자인)에서 그린 설비/장비를 조회한다. 제어장치(Output)와
        별개로, site·zone·시설에 배치된 관수밸브·스프링클러/점적·환기팬·난방/냉방기·
        창호/커튼 모터 등이 GeoShape의 equipment_collection 안에 그려져 저장된다.
        각 장비의 종류(sub_type)와 스펙(유량 flow_lph, 압력 pressure_kpa, 용량
        capacity_kw, 풍량 airflow_cmh, 전력 power_w 등), 그리고 어느 구역/사이트에
        있는지를 반환한다. 스프링클러/점적처럼 수백 개인 관수 에미터는 구역별로
        개수·총유량을 집계한다. area_name 을 주면 그 사이트/구역 안의 장비만.

        읽기 전용. (설비의 냉난방 '설계 용량 계산'은 get_facility_capacity 참고 —
        이 도구는 지도에 실제로 그려 배치된 장비 목록/스펙이다.)
        """
        try:
            from aot.databases.models import GeoShape
            if not area_name:
                area_name = extra.get('name') or extra.get('target_name') or extra.get('zone_name')
            shapes = GeoShape.query.all()
            res = AoTDataToolService._extract_map_equipment(shapes, area_name=area_name)
            n = len(res['equipment']) + sum(
                (i.get('sprinklers', 0) + i.get('drip_emitters', 0)
                 + i.get('main_pipes', 0) + i.get('branch_pipes', 0))
                for i in res['irrigation'])
            out = {
                "status": "success",
                "equipment_count": len(res['equipment']),
                "equipment": res['equipment'],
                "irrigation": res['irrigation'],
            }
            if n == 0:
                out["message"] = (f"No equipment drawn on the map"
                                  + (f" in '{area_name}'" if area_name else "") + ".")
            # 두 관수 방식을 한 숫자로 합치지 말라는 규칙은 **둘 다 있을 때만**
            # 실수가 가능하다. 한쪽뿐이면 합칠 것이 없다.
            if any(i.get('sprinklers') for i in res['irrigation']) and \
                    any(i.get('drip_emitters') for i in res['irrigation']):
                out["_reading"] = [
                    "Both irrigation methods are present here. Keep 'sprinklers' "
                    "(spray heads, each with throw radius and flow) and "
                    "'drip_emitters' (derived from drip pipe length / spacing) "
                    "strictly apart — never add them into a single 'emitter' "
                    "figure. Report the two separately."]
            return out
        except Exception as e:
            logger.error(f"Error in get_map_equipment_tool: {e}")
            return {"error": str(e)}

    @staticmethod
    def _area_node_ids_and_polys(shapes, area_name):
        """(node_ids, polygons) for the site/zone(s) named area_name — the two
        ways equipment is attributed (ownership link + spatial fallback)."""
        import json as _json
        try:
            from shapely.geometry import shape as _shape
        except Exception:
            _shape = None
        _aql = (area_name or '').strip().lower()
        node_ids, polys = set(), []
        for s in shapes:
            if s.type not in ('site', 'zone'):
                continue
            try:
                feat = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
            except Exception:
                continue
            props = feat.get('properties') or {}
            nm = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
            if nm.lower() != _aql:
                continue
            if props.get('node_id'):
                node_ids.add(props['node_id'])
            if _shape and feat.get('geometry'):
                try:
                    g = _shape(feat['geometry'])
                    if g.is_valid and g.geom_type in ('Polygon', 'MultiPolygon'):
                        polys.append(g)
                except Exception:
                    pass
        return node_ids, polys

    @staticmethod
    def get_map_equipment_detail_tool(area_name=None, **extra):
        """[분류 C - 지도 설비 상세(지오메트리) 읽기 도구]
        get_map_equipment(개요/디자인정보 요약)보다 한 단계 깊은, 개별 관수장치의
        **위치·간격·개별 배관 지오메트리**를 반환한다. 사용자가 "점적기가 정확히
        어디", "간격이 얼마", "어느 배관" 처럼 구체적 위치/간격을 물을 때 사용.
        먼저 get_map_equipment 로 요약을 본 뒤, 필요할 때만 이걸 호출하는 순서를
        권장. area_name(사이트/구역) 필수. 읽기 전용.

        반환: emitters[{lat,lng,radius_m,flow_lph}], emitter_spacing_m(인접 중심간
        중앙값 간격), pipes[{name,sub_type,length_m,start,end}].
        """
        try:
            import math as _math
            from aot.databases.models import GeoShape
            if not area_name:
                area_name = extra.get('name') or extra.get('target_name') or extra.get('zone_name')
            if not area_name:
                return {"error": "area_name (a site/zone name) is required for equipment detail."}

            shapes = GeoShape.query.all()
            node_ids, polys = AoTDataToolService._area_node_ids_and_polys(shapes, area_name)
            if not node_ids and not polys:
                return {"status": "success", "count": 0,
                        "message": f"Area '{area_name}' was not found."}

            try:
                from shapely.geometry import shape as _shape
            except Exception:
                _shape = None

            def _owned(props, geom):
                par = props.get('parent_node_id') or props.get('zone_id')
                if par in node_ids:
                    return True
                if par:  # owned elsewhere
                    return False
                if polys and _shape and geom:
                    try:
                        g = _shape(geom); pt = g if g.geom_type == 'Point' else g.centroid
                        return any(p.contains(pt) for p in polys)
                    except Exception:
                        return False
                return False

            def _hav(lat1, lon1, lat2, lon2):
                R = 6371000.0
                a = (_math.sin(_math.radians(lat2 - lat1) / 2) ** 2
                     + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2))
                     * _math.sin(_math.radians(lon2 - lon1) / 2) ** 2)
                return 2 * R * _math.asin(min(1.0, _math.sqrt(a)))

            def _line_len_m(coords):
                return sum(_hav(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0])
                           for i in range(1, len(coords)))

            import json as _json
            sprinklers, pipes, drip_pipes = [], [], []
            for s in shapes:
                if s.type not in ('equipment_collection', 'equipment'):
                    continue
                try:
                    coll = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                except Exception:
                    continue
                feats = coll.get('features') if s.type == 'equipment_collection' else [coll]
                for f in (feats or []):
                    if not isinstance(f, dict):
                        continue
                    props = f.get('properties') or {}
                    geom = f.get('geometry') or {}
                    sub = props.get('sub_type')
                    if not sub or not _owned(props, geom):
                        continue
                    if (sub == 'sprinkler_coverage' or props.get('device_type') == 'sprinkler'
                            or props.get('aot_type') == 'sprinkler'):
                        sprinklers.append({
                            "lat": round(props['center_lat'], 7) if props.get('center_lat') is not None else None,
                            "lng": round(props['center_lng'], 7) if props.get('center_lng') is not None else None,
                            "radius_m": props.get('radius'),
                            "flow_lph": props.get('flow'),
                        })
                    elif sub in ('pipe_main', 'main', 'pipe_branch', 'branch'):
                        cs = geom.get('coordinates') or []
                        if len(cs) >= 2:
                            length = round(_line_len_m(cs), 1)
                            pipes.append({
                                "name": props.get('name') or ('주배관' if sub in ('pipe_main', 'main') else '가지관'),
                                "sub_type": sub,
                                "length_m": length,
                                "start": [round(cs[0][1], 7), round(cs[0][0], 7)],
                                "end": [round(cs[-1][1], 7), round(cs[-1][0], 7)],
                            })
                            # 점적: emitters spaced along a drip pipe (length / interval)
                            if props.get('is_drip'):
                                dcfg = props.get('drip_config') or {}
                                try:
                                    interval = float(dcfg.get('interval') or 1.0)
                                except (TypeError, ValueError):
                                    interval = 1.0
                                cnt = int(length / interval) if interval > 0 else 0
                                drip_pipes.append({
                                    "pipe": pipes[-1]["name"], "length_m": length,
                                    "interval_m": interval, "drip_emitters": cnt,
                                    "flow_lph_each": dcfg.get('flow'),
                                })

            # sprinkler spacing = median nearest-neighbour distance between heads
            spacing = None
            pts = [(e['lat'], e['lng']) for e in sprinklers if e['lat'] is not None and e['lng'] is not None]
            if len(pts) >= 2:
                nn = []
                for i, (la, lo) in enumerate(pts):
                    best = None
                    for j, (lb, ob) in enumerate(pts):
                        if i == j:
                            continue
                        d = _hav(la, lo, lb, ob)
                        if best is None or d < best:
                            best = d
                    if best is not None:
                        nn.append(best)
                if nn:
                    nn.sort()
                    spacing = round(nn[len(nn) // 2], 2)

            MAXE = 60
            out = {
                "status": "success",
                "area": area_name,
                # 스프링클러 (individual heads with position/radius/flow)
                "sprinkler_count": len(sprinklers),
                "sprinkler_spacing_m": spacing,
                "sprinklers": sprinklers[:MAXE],
                # 점적 (drip — per drip-pipe, emitters spaced by interval)
                "drip_pipes": drip_pipes,
                "drip_emitter_total": sum(d['drip_emitters'] for d in drip_pipes),
                "pipes": pipes,
            }
            if len(sprinklers) > MAXE:
                out["sprinklers_truncated"] = f"showing first {MAXE} of {len(sprinklers)} sprinklers"
            if not sprinklers and not pipes:
                out["message"] = f"No irrigation equipment geometry found in '{area_name}'."
            return out
        except Exception as e:
            logger.error(f"Error in get_map_equipment_detail_tool: {e}")
            return {"error": str(e)}

    @staticmethod
    def schedule_device_control_tool(device_id, scheduled_time=None, state='on', duration_minutes=None,
                                     delay_seconds=None, duration_seconds=None,
                                     solar_event=None, solar_offset_minutes=0,
                                     solar_date_offset_days=0, **kwargs):
        """
        [시스템 제어 예약 전용]
        밸브, 펌프, 스프링클러 등 시스템 장치의 제어를 특정 시간에 예약합니다.
        AISchedulerService.propose_job()으로 SchedulerJobMeta + APScheduler 등록까지 완료합니다.

        Accepts:
          scheduled_time: ISO 8601 string (absolute time) — preferred
          delay_seconds:  relative delay in seconds from now (alternative to scheduled_time)
          solar_event:    'sunrise'|'sunset'|'solar_noon'|'civil_dawn'|'civil_dusk'
                          — 그 장치 위치의 태양 이벤트 기준으로 시각을 잡는다.
                          solar_offset_minutes(±분)·solar_date_offset_days(N일 뒤)와 함께.
          duration_minutes: run duration in minutes
          duration_seconds: run duration in seconds (alternative to duration_minutes)

        "내일 일몰 30분 전에 밸브 열어줘" 같은 요청에서, 일몰 시각을 사람이나 모델이
        직접 계산해 ISO 로 넘길 필요가 없다 — 계절마다 달라지는 값이라 그렇게 하면
        틀린다. solar_event 를 쓰면 장치 위치의 실제 태양시로 해석한다.
        """
        try:
            from aot.utils.tz_utils import now_utc, to_utc
            from datetime import datetime, timedelta
            from aot.databases.models import Output
            from aot.ai.services.ai_scheduler_service import AISchedulerService

            # 1. 장치 확인 (UUID, 정확한 이름, 부분 이름 순서로 조회)
            output = Output.query.filter(or_(Output.unique_id == device_id, Output.name == device_id)).first()
            if not output:
                # Fuzzy fallback: ILIKE partial match
                output = Output.query.filter(Output.name.ilike(f'%{device_id}%')).first()
            if not output:
                return {"error": f"Device not found: {device_id}"}

            # 2. 시간 파싱 — scheduled_time 또는 delay_seconds 지원
            now = now_utc()
            if solar_event is not None:
                from aot.utils.solar import SUN_EVENTS, next_sun_event
                if solar_event not in SUN_EVENTS:
                    return {"error": (f"Unknown solar_event: {solar_event}. "
                                      f"Use one of: {', '.join(SUN_EVENTS)}")}
                scheduled_dt = next_sun_event(
                    solar_event,
                    target_id=output.unique_id,
                    time_offset_minutes=int(solar_offset_minutes or 0),
                    date_offset_days=int(solar_date_offset_days or 0),
                    now=now)
                if scheduled_dt is None:
                    return {"error": (f"'{solar_event}' does not occur at this device's "
                                      f"location in the coming days (polar day/night), "
                                      f"or the location has no coordinates.")}
            elif delay_seconds is not None:
                scheduled_dt = now + timedelta(seconds=int(delay_seconds))
            elif scheduled_time is not None:
                if isinstance(scheduled_time, str):
                    try:
                        scheduled_dt = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                    except Exception:
                        return {"error": f"Invalid time format: {scheduled_time}. Use ISO 8601 format."}
                else:
                    scheduled_dt = scheduled_time
                if scheduled_dt.tzinfo is None:
                    # No offset given (the model doesn't always include one) —
                    # interpret it as the TARGET DEVICE'S OWN local wall-clock
                    # time (every device resolves its tz from coordinates, see
                    # device_tz.py) rather than rejecting it as ambiguous. This
                    # is what a user means by "4pm" for a specific device — not
                    # a UTC instant, and not necessarily the farm-wide default.
                    from aot.utils.device_tz import resolve_location_tz
                    scheduled_dt = resolve_location_tz(output.unique_id).localize(scheduled_dt)
                scheduled_dt = to_utc(scheduled_dt)  # normalise to UTC-aware
                if scheduled_dt <= now:
                    return {"error": f"Requested schedule time {scheduled_time} is in the past. Please provide a future time."}
            else:
                return {"error": "You must provide one of: scheduled_time, delay_seconds, solar_event."}

            # 3. 시간 변환 — duration_seconds 지원
            if duration_seconds is not None:
                _duration_minutes = max(1, int(duration_seconds) // 60)
            elif duration_minutes is not None:
                _duration_minutes = int(duration_minutes)
            else:
                _duration_minutes = 5  # default

            duration_sec = _duration_minutes * 60

            # scheduled_dt is UTC-aware — display in the DEVICE'S OWN location tz
            # (every Output resolves its tz from coordinates, see device_tz.py),
            # not left as a bare UTC instant: a raw strftime here would report
            # the confirmation time up to 9h off from the device's actual wall
            # clock (KST).
            from aot.utils.device_tz import resolve_location_tz
            _display_dt = scheduled_dt.astimezone(resolve_location_tz(output.unique_id))

            # 3. SchedulerJobMeta 생성 + 자동 승인 (APScheduler 등록)
            #    proposed_by='HUMAN' + approval_required=False → propose_job() 내부에서 approve_job() 자동 호출
            meta = AISchedulerService.propose_job(
                action_type='control_output',
                target_id=output.unique_id,
                params={'state': state, 'duration_minutes': _duration_minutes},
                reasoning=f"User request: {output.name} {state} at {_display_dt.strftime('%H:%M')}",
                schedule_time=scheduled_dt,
                duration_sec=duration_sec,
                proposed_by='HUMAN',    # 사용자가 직접 지시 → 추가 승인 불필요
                approval_required=False  # → propose_job이 approve_job() 자동 호출
            )

            # Persist the device-local tz anchor (already used for interpretation
            # above) so display can re-derive the device wall-clock. §6.
            try:
                meta.anchor_tz = str(resolve_location_tz(output.unique_id))
                meta.anchor_source = 'device'
                from aot.databases.models import db as _db
                _db.session.commit()
            except Exception:
                pass

            logger.info(f"[AI Schedule] Registered APScheduler job: {output.name} {state} at {scheduled_dt} (meta_id={meta.id if hasattr(meta, 'id') else meta})")
            return {
                "status": "success",
                "message": f"Scheduled {output.name} to {state} at {_display_dt.strftime('%Y-%m-%d %H:%M:%S')} (for {_duration_minutes} min)",
                "scheduler_job_id": meta.id if hasattr(meta, 'id') else str(meta),
            }
        except Exception as e:
            logger.error(f"Error in schedule_device_control_tool: {e}")
            return {"error": f"Error while scheduling device control: {str(e)}"}

    # ---------------------------------------------------------------------
    # Schedule CRUD helpers (SchedulerJobMeta is the ledger of record — A안)
    # ---------------------------------------------------------------------
    @staticmethod
    def _resolve_schedule_anchor(target_id):
        """예약 벽시계의 앵커 tz 를 해석한다 (docs/design/timezone-management.md §6).

        확정 정책: 장치 예약은 '장치 현지 시각' 기준. target_id 가 위치를 가진
        엔티티(구역/시설/장치)면 그 위치의 tz 를, 없으면(떠 있는 농장 전체 일정)
        시스템 tz 를 앵커로 쓴다. 반환: (tzinfo, tz_name, source).
        """
        from aot.utils.timekit import system_tz
        if target_id and target_id != 'none':
            try:
                from aot.utils.device_tz import resolve_location_tz
                tz = resolve_location_tz(target_id)
                if tz is not None:
                    return tz, str(tz), 'device'
            except Exception:
                pass
        tz = system_tz()
        return tz, str(tz), 'system'

    @staticmethod
    def _schedule_wall_to_utc(date_str, time_str="09:00", anchor_tz=None):
        """벽시계 날짜/시각(YYYY-MM-DD, HH:MM)을 앵커 tz 로 해석해 저장용
        UTC-aware datetime 으로 변환한다.

        anchor_tz(pytz tzinfo 또는 IANA 문자열)를 주면 그 시계로 해석한다 —
        확정 정책상 장치 예약은 장치 현지 tz 가 앵커. 생략 시 시스템 tz(농장 기본)로
        폴백해 기존 동작을 보존한다. 저장은 UTC-aware, 표시는 앵커 tz 로 되돌린다.
        """
        from aot.utils.timekit import wall_to_utc, system_tz
        tz = anchor_tz if anchor_tz is not None else system_tz()
        return wall_to_utc(f"{date_str} {time_str}", tz)

    @staticmethod
    def _resolve_schedule_job(job_id):
        """일정을 unique_id(우선) 또는 정수 PK로 조회. 없으면 None."""
        from aot.databases.models.scheduler import SchedulerJobMeta
        if job_id is None:
            return None
        key = str(job_id).strip()
        meta = SchedulerJobMeta.query.filter_by(unique_id=key).first()
        if meta:
            return meta
        if key.isdigit():
            return SchedulerJobMeta.query.get(int(key))
        return None

    @staticmethod
    def _schedule_summary(meta):
        """SchedulerJobMeta 한 행을 AI가 읽기 쉬운 요약 dict로 직렬화."""
        import json as _json
        from aot.utils.time_utils import serialize_ts
        try:
            params = _json.loads(meta.params_json) if meta.params_json else {}
        except Exception:
            params = {}
        content = params.get('content')
        if not content and meta.action_type == 'control_output' and params.get('state'):
            # Device-control rows never had a human 'content' string (only
            # {state, duration_minutes}) — falling back to the raw internal
            # `reasoning` log line ("User request: Valve1 on at 16:00") read as
            # a debug message, not a summary, once this became user-facing.
            dur = params.get('duration_minutes')
            content = f"{str(params['state']).capitalize()}" + (f" ({dur}min)" if dur else "")
        content = content or meta.reasoning or meta.action_type

        # Display the wall-clock in the schedule's anchor tz (device-local by
        # policy) so a viewer in another tz still sees the device's own time. §7
        anchor = getattr(meta, 'anchor_tz', None)
        if not anchor and meta.target_id and meta.target_id != 'none':
            try:
                from aot.utils.device_tz import resolve_location_tz
                anchor = str(resolve_location_tz(meta.target_id))
            except Exception:
                anchor = None
        if meta.schedule_time:
            from aot.utils.timekit import to_tz
            when = (to_tz(meta.schedule_time, anchor).isoformat() if anchor
                    else serialize_ts(meta.schedule_time))
        else:
            when = None

        return {
            'job_id': meta.unique_id,
            'when': when,
            'when_tz': anchor,
            'content': content,
            'worker': params.get('worker') or None,
            'location': params.get('target_name') or None,   # resolved entity name
            'target_id': meta.target_id if meta.target_id and meta.target_id != 'none' else None,
            'kind': meta.action_type,          # human / control_output / automated_fire ...
            'state': meta.state,
            'editable': bool(meta.is_editable),
            'deletable': bool(meta.is_deletable),
        }

    @staticmethod
    def get_local_time_tool(target_name=None, target_id=None, **extra):
        """
        [읽기전용] 특정 위치(구역/시설/장치)의 현재 로컬시각·시간대를 반환한다.
        모든 지도 도형/장치는 좌표를 가지며 그로부터 IANA 시간대가 해석된다
        (aot/utils/device_tz.py — timezonefinder 기반, 명시적 설정이 없으면
        좌표→시간대, 그마저 없으면 농장 전체 기본 시간대로 폴백).

        위치에 대해 설명·계획할 때(예: "그 구역은 지금 몇시야?", "야간작업이라
        오늘 말고 내일로 옮기자") 이 도구로 실제 현지시각을 확인한 뒤 답하라
        — 전역 설정을 무조건 가정하지 말 것.
        """
        try:
            from aot.utils.device_tz import resolve_location_tz
            from datetime import datetime as _dt, timezone as _tzinfo

            resolved_name = None
            if not target_id and target_name:
                target_id, _tt, resolved_name, _lat, _lng = \
                    AoTDataToolService._resolve_note_target(target_name)
                if not target_id:
                    return {
                        "status": "success",
                        "message": (f"위치 '{target_name}'를 찾지 못해 농장 기본 시간대로 "
                                    f"응답합니다."),
                        "available_targets": AoTDataToolService._geoshape_name_candidates(),
                        "location": "farm-wide (default)",
                        "timezone": str(resolve_location_tz(None)),
                        "local_time": _dt.now(_tzinfo.utc).astimezone(
                            resolve_location_tz(None)).strftime('%Y-%m-%d %H:%M:%S'),
                        "sun": AoTDataToolService._sun_block(None, resolve_location_tz(None)),
                    }

            tz = resolve_location_tz(target_id)
            now_local = _dt.now(_tzinfo.utc).astimezone(tz)
            return {
                "status": "success",
                "location": resolved_name or target_name or "farm-wide (default)",
                "timezone": str(tz),
                "local_time": now_local.strftime('%Y-%m-%d %H:%M:%S'),
                "utc_offset": now_local.strftime('%z'),
                "sun": AoTDataToolService._sun_block(target_id, tz),
            }
        except Exception as e:
            logger.error(f"Error in get_local_time_tool: {e}")
            return {"error": f"Error while resolving local time: {str(e)}"}

    @staticmethod
    def _sun_block(target_id, tz):
        """그 위치의 오늘 태양시 요약 — get_local_time 응답에 실린다.

        "지금 주간인가", "일몰까지 얼마 남았나"는 농작업 판단의 기본값인데
        (관수·분무·차광·환기는 전부 태양일에 묶인다), 지금까지 AI 는 시각만 알고
        해가 언제 뜨고 지는지는 몰라서 계절을 무시한 조언을 했다.
        좌표를 해석할 수 없으면 None — 호출부는 그대로 실어 보낸다.
        """
        try:
            from aot.utils.solar import STATUS_NORMAL, sun_times, is_daytime, next_sun_event
            from aot.utils.timekit import utc_now

            times = sun_times(target_id=target_id)
            if times is None:
                return None

            now = utc_now()

            def _local(dt):
                return dt.astimezone(tz).strftime('%Y-%m-%d %H:%M') if dt else None

            day = is_daytime(target_id=target_id, at=now)
            # 다음 경계 — 주간이면 일몰, 야간이면 일출.
            next_kind = 'sunset' if day else 'sunrise'
            next_dt = next_sun_event(next_kind, target_id=target_id, now=now)

            block = {
                "sunrise": _local(times.sunrise),
                "sunset": _local(times.sunset),
                "solar_noon": _local(times.solar_noon),
                "civil_dawn": _local(times.civil_dawn),
                "civil_dusk": _local(times.civil_dusk),
                "is_daytime": day,
                "status": times.status,
            }
            if times.day_length_seconds is not None:
                block["day_length_hours"] = round(times.day_length_seconds / 3600.0, 2)
            if next_dt is not None:
                block["next_event"] = {
                    "kind": next_kind,
                    "local_time": _local(next_dt),
                    "in_minutes": max(0, int((next_dt - now).total_seconds() // 60)),
                }
            if times.status != STATUS_NORMAL:
                block["note"] = ("이 위치·날짜에는 일출/일몰이 없습니다 "
                                 "(백야 또는 극야).")
            return block
        except Exception as e:
            logger.debug(f"_sun_block failed for {target_id}: {e}")
            return None

    @staticmethod
    def _geoshape_name_candidates(limit=20):
        """지도 도형(GeoShape) 이름 후보 목록 — 위치 미해석 시 ask_user 제시용."""
        import json as _json
        out = []
        for s in GeoShape.query.limit(40).all():
            try:
                f = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                nm = (f.get('properties') or {}).get('name')
                if nm:
                    out.append(nm)
            except Exception:
                continue
        return out[:limit]

    @staticmethod
    def search_schedule_tool(query=None, target_name=None,
                             include_past=False, include_archived=False,
                             limit=20, **extra):
        """
        [분류 C - 일정 조회 도구]
        농장 운영 일정(작업·이벤트·장치 예약)을 SchedulerJobMeta 원장에서 조회한다.
        기본은 '앞으로 예정된 일정'(schedule_time >= 지금)만. edit/delete_schedule에
        넘길 job_id를 얻으려면 먼저 이 도구로 대상을 찾는다(노트의 search→act 패턴).

        Args:
            query (str): 내용/사유(reasoning·content) 부분 검색 키워드. 없으면 전체.
            target_name (str): 특정 위치/장치에 걸린 일정만 (이름 → unique_id 해석).
            include_past (bool): True면 지난 일정/기록도 포함(기본 False = 예정만).
            include_archived (bool): True면 취소/보관(ARCHIVED)된 것도 포함(기본 False).
            limit (int): 최대 반환 건수(기본 20).
        """
        try:
            from aot.databases.models.scheduler import SchedulerJobMeta
            from sqlalchemy import or_ as _or

            q = SchedulerJobMeta.query

            if not include_archived:
                q = q.filter(SchedulerJobMeta.state != 'ARCHIVED')

            if not include_past:
                now = utc_now()
                # 예정된 것(미래) + 시간이 없는 항목은 포함, 과거는 제외
                q = q.filter(_or(SchedulerJobMeta.schedule_time == None,   # noqa: E711
                                 SchedulerJobMeta.schedule_time >= now))

            if query and query.strip():
                like = f"%{query.strip()}%"
                q = q.filter(_or(SchedulerJobMeta.reasoning.like(like),
                                 SchedulerJobMeta.params_json.like(like)))

            # 대상 안에서 일어나는 일 **전부** 를 본다 — 구역·시설·장치·식생.
            # 정확 일치만 보던 때는 site 를 물으면 0건이 나왔다(_scope_for_target).
            scope = None
            if target_name:
                ids, scope = AoTDataToolService._scope_for_target(target_name)
                if ids:
                    q = q.filter(SchedulerJobMeta.target_id.in_(ids))
                else:
                    # 이름을 못 찾았다. 여기서 필터를 걸지 않으면 **전체 일정**
                    # 이 그 대상의 것인 양 돌아간다.
                    q = q.filter(SchedulerJobMeta.target_id == '\x00none')

            # 예정은 임박한 순, 과거 포함이면 최신순
            if include_past:
                q = q.order_by(SchedulerJobMeta.created_at.desc())
            else:
                q = q.order_by(SchedulerJobMeta.schedule_time.asc())

            rows = q.limit(max(1, int(limit))).all()
            results = [AoTDataToolService._schedule_summary(r) for r in rows]
            out = {
                "status": "success",
                "count": len(results),
                "results": results,
            }
            if scope is not None:
                out["scope"] = scope
                if not scope['resolved']:
                    # 0건을 "예정 없음" 으로 읽으면 "충돌 없습니다" 라는 틀린
                    # 답이 확신에 찬 문장으로 나간다. 못 찾은 것은 없는 것이 아니다.
                    out["warning"] = (
                        "'%s' could not be resolved to any place or device, so "
                        "this is NOT evidence that nothing is scheduled. Ask the "
                        "user for the exact name, or call resolve_target first."
                        % target_name)
            return out
        except Exception as e:
            logger.error(f"Error in search_schedule_tool: {e}")
            return {"error": f"Error while querying schedules: {str(e)}"}

    @staticmethod
    def edit_schedule_tool(job_id, date=None, time=None, content=None,
                           worker=None, target_name=None, duration_minutes=None, **extra):
        """
        [일정 수정 — 변이(승인 필요)]
        기존 일정의 시각/소요시간/내용/담당자/위치를 수정한다. 먼저 search_schedule로 job_id를 얻는다.
        장치 예약(control_output)이 이미 APScheduler에 등록돼 있으면 트리거도 함께 재조정.

        Args:
            job_id (str): search_schedule가 돌려준 job_id(unique_id) 또는 정수 id.
            date (str): 새 날짜 YYYY-MM-DD (시각만 바꾸려면 생략 가능 — 기존 날짜 유지).
            time (str): 새 시각 HH:MM (날짜만 바꾸려면 생략 가능 — 기존 시각 유지).
            content (str): 새 내용/설명.
            worker (str): 새 담당자.
            target_name (str): 새 위치(구역/시설/장치 이름)로 재연결. 미해석이면
                available_targets를 돌려주니 ask_user로 확인 후 재시도.
            duration_minutes (int): 새 소요시간(분). 기존 duration_sec/end_time을 대체한다.
        """
        try:
            import json as _json
            from aot.utils.time_utils import serialize_ts

            meta = AoTDataToolService._resolve_schedule_job(job_id)
            if not meta:
                return {"error": f"Schedule not found: {job_id}"}
            if not meta.is_editable:
                return {"error": f"This schedule is not editable (kind={meta.action_type})."}

            try:
                params = _json.loads(meta.params_json) if meta.params_json else {}
            except Exception:
                params = {}

            # 0. 위치 재연결 (target_name) — 미해석이면 disambiguation 요청
            if target_name:
                _tid, _tt, _rn, _lat, _lng = \
                    AoTDataToolService._resolve_note_target(target_name)
                if not _tid:
                    return {
                        "status": "needs_disambiguation",
                        "error": "target_not_found",
                        "message": (f"위치 '{target_name}'를 특정하지 못했습니다. "
                                    f"available_targets에서 정확한 이름을 고르도록 ask_user로 "
                                    f"확인한 뒤 다시 수정하세요."),
                        "available_targets": AoTDataToolService._geoshape_name_candidates(),
                    }
                meta.target_id = _tid
                params['target_type'] = _tt
                params['target_name'] = _rn

            # 앵커 tz(장치 현지) — 위치가 바뀌었으면 새 위치 기준. §6
            _anchor_tz, _anchor_name, _anchor_src = \
                AoTDataToolService._resolve_schedule_anchor(meta.target_id)
            if target_name:
                # 위치 재연결: 발화 순간(UTC)은 유지하되 표시 앵커를 새 장치로 갱신.
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src

            # 1. 시각 변경 — 앵커 tz 기준 해석. date/time 하나만 와도 기존값과 병합.
            new_dt = None
            if date or time:
                from aot.utils.timekit import to_tz
                base_local = to_tz(meta.schedule_time, _anchor_tz) if meta.schedule_time else None
                new_date = date or (base_local.strftime("%Y-%m-%d") if base_local else None)
                new_time = time or (base_local.strftime("%H:%M") if base_local else "09:00")
                if not new_date:
                    return {"error": "date is required (no existing date to keep)."}
                new_dt = AoTDataToolService._schedule_wall_to_utc(new_date, new_time, anchor_tz=_anchor_tz)
                meta.schedule_time = new_dt
                meta.anchor_tz = _anchor_name
                meta.anchor_source = _anchor_src

            # 2. 내용/담당자 변경
            if content is not None:
                params['content'] = content
            if worker is not None:
                params['worker'] = worker
            # params가 바뀐 경우(위치 재연결 포함) 저장
            if content is not None or worker is not None or target_name:
                meta.params_json = _json.dumps(params)

            # 2b. 소요시간 변경 — end_time은 (변경됐을 수 있는) schedule_time 기준으로
            # 재계산하므로 반드시 시각 변경 처리 다음에 온다. duration_minutes가 없어도
            # 시각만 바뀌었고 기존 duration_sec이 있으면 end_time을 같이 이동시킨다.
            if duration_minutes is not None:
                try:
                    duration_minutes = int(duration_minutes)
                except (TypeError, ValueError):
                    return {"error": "duration_minutes must be a number."}
                if duration_minutes <= 0:
                    return {"error": "duration_minutes must be positive."}
                meta.duration_sec = duration_minutes * 60
            if (new_dt is not None or duration_minutes is not None) and meta.duration_sec and meta.schedule_time:
                meta.end_time = meta.schedule_time + timedelta(seconds=meta.duration_sec)

            # 3. edit 추적
            meta.edit_count = (meta.edit_count or 0) + 1
            meta.last_edited_at = utc_now()
            meta.last_edited_by = 'AI'

            # 4. APScheduler 트리거 재조정 (등록된 장치 예약 한정)
            rescheduled = False
            if new_dt is not None and meta.action_type != 'human' and meta.state == 'PENDING':
                try:
                    from aot.ai.services.ai_scheduler_service import get_scheduler
                    job = get_scheduler().get_job(f'scheduler_meta_{meta.id}')
                    if job is not None:
                        job.modify(next_run_time=new_dt)
                        rescheduled = True
                except Exception as _sch_err:
                    logger.warning(f"[edit_schedule] APScheduler reschedule failed: {_sch_err}")

            db.session.commit()
            return {
                "status": "success",
                "message": "Schedule updated"
                           + (" (device trigger rescheduled)" if rescheduled else ""),
                "schedule": AoTDataToolService._schedule_summary(meta),
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in edit_schedule_tool: {e}")
            return {"error": f"Error while editing schedule: {str(e)}"}

    @staticmethod
    def delete_schedule_tool(job_id, reason=None, **extra):
        """
        [일정 삭제/취소 — 변이(승인 필요)]
        일정을 취소한다. 소프트 삭제(state=ARCHIVED)로 되돌릴 수 있게 보관하며,
        등록된 장치 예약(APScheduler 트리거)은 실제로 제거해 더 이상 발화하지 않게 한다.

        Args:
            job_id (str): search_schedule가 돌려준 job_id(unique_id) 또는 정수 id.
            reason (str): 취소 사유(선택, 감사/학습용).
        """
        try:
            meta = AoTDataToolService._resolve_schedule_job(job_id)
            if not meta:
                return {"error": f"Schedule not found: {job_id}"}
            if not meta.is_deletable:
                return {"error": f"This schedule cannot be deleted (kind={meta.action_type})."}
            if meta.state == 'ARCHIVED':
                return {"status": "success", "message": "Schedule was already cancelled.",
                        "job_id": meta.unique_id}

            # 1. 등록된 APScheduler 트리거 제거 (있으면)
            removed_trigger = False
            try:
                from aot.ai.services.ai_scheduler_service import get_scheduler
                sched = get_scheduler()
                if sched.get_job(f'scheduler_meta_{meta.id}') is not None:
                    sched.remove_job(f'scheduler_meta_{meta.id}')
                    removed_trigger = True
            except Exception as _sch_err:
                logger.warning(f"[delete_schedule] APScheduler remove failed: {_sch_err}")

            # 2. 소프트 삭제 (되돌림 가능하도록 보관)
            meta.state = 'ARCHIVED'
            meta.deletion_reason = reason or 'Cancelled via AI request'
            meta.last_edited_at = utc_now()
            meta.last_edited_by = 'AI'
            db.session.commit()

            return {
                "status": "success",
                "message": "Schedule cancelled"
                           + (" (device trigger removed)" if removed_trigger else ""),
                "job_id": meta.unique_id,
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in delete_schedule_tool: {e}")
            return {"error": f"Error while deleting schedule: {str(e)}"}

    @staticmethod
    def analyze_system_failure_tool(device_id=None, tool_name=None, lookback_minutes=60, **kwargs):
        """
        @ANCHOR: ANALYZE_SYSTEM_FAILURE_TOOL
        [031_STEP_3] Diagnostic RAG — audit AITask failure logs and MCP bridge status.

        Called by the Planner when the user reports a hardware failure or
        when 'operate_device' returns PC-099-ERROR. Provides specific reasons
        instead of generic error codes.

        Args:
            device_id:         (optional) Target device UUID/name to filter logs.
            tool_name:         (optional) MCP tool name that failed (e.g. 'operate_device').
            lookback_minutes:  How far back to search AITask logs (default 60 min).

        Returns:
            dict with 'failure_summary', 'failed_tasks', 'mcp_status', 'recommendation'.
        """
        try:
            from aot.ai.services.mcp_bridge_service import MCPBridgeService
            from aot.utils.time_utils import utc_now

            cutoff = utc_now() - timedelta(minutes=int(lookback_minutes))

            # 1. Query recent failed AITask records
            failed_q = AITask.query.filter(
                AITask.status.in_(['failed', 'error']),
                AITask.created_at >= cutoff
            )
            if device_id:
                failed_q = failed_q.filter(
                    (AITask.target_id == device_id) | (AITask.title.contains(device_id))
                )
            failed_tasks_db = failed_q.order_by(AITask.created_at.desc()).limit(10).all()

            failed_tasks = []
            for t in failed_tasks_db:
                failed_tasks.append({
                    "task_id": t.unique_id,
                    "title": t.title,
                    "action_type": t.action_type,
                    "target_id": t.target_id,
                    "status": t.status,
                    "execution_result": (t.execution_result or '')[:300],
                    "created_at": serialize_ts(t.created_at) if t.created_at else None,
                })

            # 2. Query MCP server status
            mcp_status = []
            try:
                from aot.databases.models import MCPServer
                active_servers = MCPBridgeService.get_active_servers()
                all_servers = MCPServer.query.filter_by(is_activated=True).all()
                active_ids = {s.unique_id for s in active_servers}
                for srv in all_servers:
                    _is_degraded = srv.unique_id not in active_ids
                    mcp_status.append({
                        "name": srv.name,
                        "unique_id": srv.unique_id,
                        "is_degraded": _is_degraded,
                        "has_tool": tool_name in (srv.tool_names or []) if tool_name else None,
                    })
            except Exception as _mcp_err:
                logger.warning(f"[031_STEP_3] Could not query MCP status: {_mcp_err}")
                mcp_status = [{"error": str(_mcp_err)}]

            # 3. Build failure summary
            failure_reasons = []
            if not [s for s in mcp_status if not s.get('is_degraded') and not s.get('error')]:
                failure_reasons.append("All MCP servers are offline or unreachable.")
            elif tool_name:
                tool_server = next((s for s in mcp_status if s.get('has_tool') and not s.get('is_degraded')), None)
                if not tool_server:
                    failure_reasons.append(f"The MCP server providing the '{tool_name}' tool is offline.")

            for t in failed_tasks:
                err_text = t.get('execution_result', '')
                if 'PC-099-ERROR' in err_text:
                    failure_reasons.append(f"[{t['title']}] Physical execution failed: {err_text[:150]}")
                elif 'Safety violation' in err_text:
                    failure_reasons.append(f"[{t['title']}] Blocked by a safety constraint violation.")
                elif err_text:
                    failure_reasons.append(f"[{t['title']}] Error: {err_text[:150]}")

            recommendation = "Check the MCP server status, restart the server, or verify device connectivity."
            if not failure_reasons:
                recommendation = "No recent failure records. Check device power and network connectivity."

            return {
                "failure_summary": failure_reasons if failure_reasons else ["Could not identify a specific error cause."],
                "failed_tasks": failed_tasks,
                "mcp_status": mcp_status,
                "recommendation": recommendation,
                "lookback_minutes": lookback_minutes,
            }

        except Exception as e:
            logger.error(f"[031_STEP_3] analyze_system_failure_tool error: {e}")
            return {"error": f"Error while running diagnostic tool: {str(e)}"}

    @staticmethod
    def _weather_inputs():
        """{unique_id: Input} for every Input that actually observes weather.

        See the _WEATHER_INPUT_DEVICES note above for why the driver name is the
        primary test and the measurement set is only a secondary net.
        """
        rows = {}
        try:
            for i in Input.query.filter(
                    Input.device.in_(sorted(_WEATHER_INPUT_DEVICES))).all():
                rows[i.unique_id] = i
        except Exception:
            logger.exception("[WEATHER_TOOL] weather driver lookup failed")
        try:
            extra = {r[0] for r in DeviceMeasurements.query.with_entities(
                DeviceMeasurements.device_id).filter(
                    DeviceMeasurements.measurement.in_(
                        sorted(_WEATHER_MEASUREMENTS))).all() if r[0]}
            extra -= set(rows)
            if extra:
                for i in Input.query.filter(
                        Input.unique_id.in_(list(extra))).all():
                    rows[i.unique_id] = i
        except Exception:
            logger.debug("[WEATHER_TOOL] wind/rain measurement scan failed",
                         exc_info=True)
        return rows

    @staticmethod
    def _name_affinity(device_name, zone_name):
        """1 when the device name carries the zone's name ('기상청-1포장' ↔ '1포장').

        Placement is the authority, but a KMA/API input often has no marker on
        the map at all — its name is then the only link it has to the plot it
        was created for, and without this tie-break a farm with three KMA
        inputs answers every zone with whichever row the DB returned first.
        """
        try:
            dn = ''.join(str(device_name or '').lower().split())
            zn = ''.join(str(zone_name or '').lower().split())
        except Exception:
            return 0
        if len(zn) < 2 or not dn:
            return 0
        return 1 if (zn in dn or dn in zn) else 0

    @staticmethod
    def _pick_weather_input(target_shape, resolved_name):
        """Choose the weather device for a zone/site.

        Returns (Input|None, scope, others) where scope is 'in_zone' |
        'same_map' | 'elsewhere' and `others` names the weather devices that
        were not chosen (so the caller can say which else exist).
        """
        candidates = AoTDataToolService._weather_inputs()
        if not candidates:
            return None, None, []

        in_shape = []
        try:
            from aot.aot_flask.geo.device_membership import device_ids_in_shape
            for _id in (device_ids_in_shape(target_shape) or set()):
                if _id in candidates:
                    in_shape.append(candidates[_id])
        except Exception:
            logger.debug("[WEATHER_TOOL] shape membership lookup failed",
                         exc_info=True)

        on_map = []
        try:
            _map = getattr(target_shape, 'geo_id', None)
            if _map:
                for _id in (_devices_on_map_p2(_map) or set()):
                    if _id in candidates:
                        on_map.append(candidates[_id])
        except Exception:
            logger.debug("[WEATHER_TOOL] map membership lookup failed",
                         exc_info=True)

        for tier, scope in ((in_shape, 'in_zone'),
                            (on_map, 'same_map'),
                            (list(candidates.values()), 'elsewhere')):
            if not tier:
                continue
            tier = sorted(
                tier,
                key=lambda i: (-AoTDataToolService._name_affinity(i.name,
                                                                 resolved_name),
                               str(i.name or '')))
            chosen = tier[0]
            others = [{"name": i.name, "device_id": i.unique_id,
                       "driver": i.device}
                      for i in tier[1:]]
            return chosen, scope, others
        return None, None, []

    @staticmethod
    def _weather_time_range(device):
        """Lookback for a weather read, as a get_sensor_detail range string.

        Fixed at 1h the window was shorter than some devices' own sampling
        period, so a perfectly healthy hourly input answered "no data". Same
        rule as routes_general._effective_lookback: never narrower than the
        request, widened to 3 sampling periods, capped at 30 days.

        A device that declares its own `max_age_s` (p6_55) widens the window
        too. A LoRaWAN weather node on a 40-minute heartbeat reports every
        2400s but is only *considered late* past its own limit; deriving the
        window from the period alone answers "no data" for a node that is
        working exactly as configured. It only ever widens — see
        `measurement_freshness.widen_window`.
        """
        from aot.utils.measurement_freshness import widen_window
        seconds = widen_window(3600,
                               getattr(device, 'period', None),
                               getattr(device, 'max_age_s', None),
                               factor=3.0, cap=30 * 86400)
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 3600.0
        return "%dh" % max(1, int((seconds + 3599) // 3600))

    @staticmethod
    def get_weather_tool(zone_name=None, zone_id=None, **kwargs):
        """
        포장/구역의 기상 센서 데이터를 InfluxDB에서 조회합니다.
        GeoShape.unique_id → Input(map_overlay_id) → DeviceMeasurements(device_id+channel) → InfluxDB
        외부 API를 직접 호출하지 않습니다. 데이터는 Input 데몬이 수집하여 InfluxDB에 저장합니다.
        @ANCHOR: WEATHER_TOOL_ENTRY
        """
        import json as _json

        try:
            # Step 1: Find GeoShape by zone_name or zone_id
            target_shape = None
            if zone_id:
                target_shape = GeoShape.query.filter_by(unique_id=zone_id).first()
            # uuid 를 이름 자리에 넣으면 부분일치가 엉뚱한 도형을 잡는다 —
            # 여기서는 그 도형의 **좌표**까지 돌려주고 "이 좌표로 날씨를 조회
            # 하라" 고 시키므로, 오답이 다음 단계로 조용히 이어진다.
            # (get_sensor_detail 의 같은 폴백과 같은 이유·같은 가드)
            if not target_shape and zone_name and not _looks_like_uuid(zone_name):
                _zn = zone_name.strip().lower()
                _named_shapes = []
                for shape in GeoShape.query.all():
                    try:
                        feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                        props = feat.get('properties') or {}
                        _name = str(props.get('name') or props.get('label') or props.get('title') or '').lower()
                        # 이름 없는 도형은 매치 대상에서 제외한다. 빈 문자열은
                        # 파이썬에서 모든 문자열의 부분집합이라(`'' in x`),
                        # 이 가드 없이는 이름 없는 도형이 쿼리 순서상 먼저
                        # 나오기만 하면 **어떤 zone_name 을 넣어도** 그리로
                        # 떨어진다 — 실측(koat): 도형 150개 중 52개가 이름이
                        # 비어 있고, '1포장'·'2포장'·'3포장' 전부 같은 고아
                        # 도형 하나로 낙착했다.
                        if _name:
                            _named_shapes.append((shape, _name))
                    except Exception:
                        continue

                # 1차: 완전 일치를 최우선으로 본다 — 결정적이라 충돌이 없다.
                for shape, _name in _named_shapes:
                    if _name == _zn:
                        target_shape = shape
                        break

                # 2차: 완전 일치가 없을 때만 부분일치로 넓힌다. 단 한 글자
                # 이름은 부분일치에서 제외한다 — 실측: 존재하지 않는 이름
                # 'xyz없는이름123'이 그 안의 숫자 '2' 하나 때문에 구역 '2'
                # 와 우연히 매치됐다. 길이 가드를 여기 전체에 걸면 한 글자
                # 구역(로컬에 4개 실재)을 이름으로 못 찾게 되므로, 그 구역은
                # 위 1차(완전 일치)로만 찾을 수 있게 남겨 둔다.
                if not target_shape:
                    for shape, _name in _named_shapes:
                        if len(_name) < 2:
                            continue
                        if _zn in _name or _name in _zn:
                            target_shape = shape
                            break

            # Step 2: Resolve display name; return error if zone not found
            _resolved_name = zone_name or zone_id or "Unknown zone"
            if target_shape:
                try:
                    _f = target_shape.feature if isinstance(target_shape.feature, dict) else _json.loads(target_shape.feature or '{}')
                    _resolved_name = (_f.get('properties') or {}).get('name', _resolved_name)
                except Exception:
                    pass
            else:
                _available = []
                for s in GeoShape.query.limit(20).all():
                    try:
                        f = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                        _n = (f.get('properties') or {}).get('name', s.unique_id)
                        _available.append(_n)
                    except Exception:
                        pass
                return {
                    "error": "zone_not_found",
                    "message": f"Zone '{zone_name or zone_id}' not found.",
                    "available_zones": _available[:10]
                }

            # Step 3: Pick the device to read. A weather question must be
            # answered by a weather station — see _WEATHER_INPUT_DEVICES for
            # what "just take the first Input in the polygon" produced.
            def _read(loc_id, time_range):
                """Weather-filtered read, falling back to unfiltered."""
                res = AoTDataToolService.get_sensor_detail(
                    loc_id=loc_id, time_range=time_range, sensor_type='weather')
                if isinstance(res, dict) and res.get('error'):
                    return AoTDataToolService.get_sensor_detail(
                        loc_id=loc_id, time_range=time_range)
                return res

            def _envelope(res):
                out = dict(res) if isinstance(res, dict) else {"data": res}
                out['zone_name'] = _resolved_name
                return out

            chosen, scope, others = AoTDataToolService._pick_weather_input(
                target_shape, _resolved_name)

            if chosen is not None:
                _range = AoTDataToolService._weather_time_range(chosen)
                logger.info(
                    "[WEATHER_TOOL] zone '%s' → weather device '%s' (%s, %s, %s)",
                    _resolved_name, chosen.name, chosen.device, scope, _range)
                out = _envelope(_read(chosen.unique_id, _range))
                out['weather_source'] = 'weather_station'
                out['weather_device'] = {"name": chosen.name,
                                         "device_id": chosen.unique_id,
                                         "driver": chosen.device}
                out['weather_device_scope'] = scope
                if scope != 'in_zone':
                    out['weather_device_note'] = (
                        "This weather device is not placed inside '%s' — it is the "
                        "closest match available (%s). Say so when reporting."
                        % (_resolved_name, scope))
                if others:
                    out['other_weather_devices'] = others
                return out

            # No weather station anywhere: fall back to whatever sensor the zone
            # has, but never present it as a weather observation.
            logger.info(
                "[WEATHER_TOOL] zone '%s' has no weather station; falling back "
                "to a general-purpose sensor", _resolved_name)
            # 폴백도 주기를 보고 창을 정한다. 예전 고정 '1h' 는 자기 주기가 그보다
            # 긴 장치에서 **정상인데도** "No data for device ... in the last 1h"
            # 로 답했다(koat '1포장' 이 그 응답이었다).
            fallback_dev = None
            try:
                from aot.aot_flask.geo.device_membership import device_ids_in_shape
                _ids = device_ids_in_shape(target_shape) or set()
                if _ids:
                    fallback_dev = Input.query.filter(
                        Input.unique_id.in_(list(_ids))).first()
            except Exception:
                logger.debug("[WEATHER_TOOL] fallback device lookup failed",
                             exc_info=True)
            if fallback_dev is not None:
                out = _envelope(_read(
                    fallback_dev.unique_id,
                    AoTDataToolService._weather_time_range(fallback_dev)))
                out['fallback_device'] = {"name": fallback_dev.name,
                                          "device_id": fallback_dev.unique_id,
                                          "driver": fallback_dev.device}
            else:
                out = _envelope(_read(target_shape.unique_id, '1h'))
            out['weather_source'] = 'nearby_sensor'
            out['weather_device_scope'] = 'in_zone'
            out['weather_source_warning'] = (
                "No dedicated weather station (KMA / SenseCAP / Ecowitt / "
                "OpenWeatherMap or any wind/rain-recording input) is registered for "
                "this farm. The values below come from an ordinary sensor inside "
                "'%s' and are NOT weather observations — there is no wind, rain or "
                "solar data. Report them as a sensor reading, not as the weather."
                % _resolved_name)
            return out

        except Exception as e:
            logger.exception("[WEATHER_TOOL] Unexpected error")
            return {"error": "unexpected_error", "message": f"Error while querying weather data: {str(e)}"}

    # -------------------------------------------------------------------------
    # @ANCHOR: FUNCTION_MANAGEMENT_TOOLS
    # Function management tools — read/activate/deactivate Conditional, Trigger,
    # PID, and CustomController (Function_Custom) entities.
    # Models with is_activated: Conditional, Trigger, PID, CustomController.
    # Function (base container) has no is_activated field — excluded from
    # activate/deactivate operations.
    # -------------------------------------------------------------------------

    @staticmethod
    def get_function_list(function_type=None, active_only=False):
        """
        Returns all registered Function-type controllers with their name, type,
        activation state, and period.

        :param function_type: Filter by type string — one of 'conditional',
                              'trigger', 'pid', 'custom'. Case-insensitive.
                              None returns all types.
        :param active_only:   If True, returns only is_activated=True entries.
        :returns:             {"results": [...], "count": int}
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            results = []

            # Normalize filter
            _type_filter = function_type.lower().strip() if function_type else None

            def _should_include(type_key):
                return _type_filter is None or _type_filter == type_key

            if _should_include('conditional'):
                rows = Conditional.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "conditional",
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('trigger'):
                rows = Trigger.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "trigger",
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('pid'):
                rows = PID.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "pid",
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            if _should_include('custom'):
                rows = CustomController.query.all()
                for r in rows:
                    if active_only and not getattr(r, 'is_activated', False):
                        continue
                    results.append({
                        "function_id": r.unique_id,
                        "name": r.name,
                        "function_type": "custom",
                        "device": getattr(r, 'device', None),
                        "is_activated": bool(getattr(r, 'is_activated', False)),
                        "period": getattr(r, 'period', None),
                    })

            return {"results": results, "count": len(results)}
        except Exception as e:
            logger.exception("Error in get_function_list")
            return {"error": f"Error while querying Function list: {str(e)}"}

    @staticmethod
    def _sequence_detail(trig):
        """Ordered steps + weekly schedule of a trigger_sequence.

        Without this a sequence looks like a name and a period, so the AI can
        neither explain what it does nor tell a valve from the pump. The
        controller already derives the whole picture for the widget
        (get_static_status: per-step start/end, group, duration, mode), so read
        that rather than recomputing the slot maths here. DB-derived and
        read-only — no daemon RPC, so it answers the same from any process.
        """
        try:
            from aot.controllers.controller_trigger_sequence import SequenceTriggerController
            status = SequenceTriggerController.get_static_status(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[_sequence_detail] step read failed: {exc}")
            return {"steps_error": str(exc)}

        if not isinstance(status, dict) or status.get('error'):
            return {"steps_error": str((status or {}).get('error'))}

        steps = []
        for s in status.get('steps') or []:
            step = {
                "action_id": s.get('unique_id'),
                "device": s.get('device_detail'),
                "label": s.get('display_name') or s.get('device_detail'),
                # 'single' takes its turn in the running order; 'total' spans
                # the whole cycle (a field's pump, typically).
                "mode": s.get('type'),
                "group": s.get('group_name'),
                "enabled": s.get('enabled'),
                "duration_seconds": s.get('original_duration'),
                "starts_at_seconds": s.get('start'),
                "ends_at_seconds": s.get('end'),
            }
            if s.get('type') == 'total':
                step["lead_seconds"] = s.get('total_lead')
                step["lag_seconds"] = s.get('total_lag')
            steps.append(step)

        # The resolved plan for EVERY weekday, not just today. Without this a
        # caller configuring Friday from a Thursday session has no way to check
        # what it built — 'steps' above is today's slot maths only.
        weekly_plan = []
        for idx in range(7):
            try:
                plan = SequenceTriggerController.plan_for_day(trig.unique_id, idx)
            except Exception as exc:
                logger.warning(f"[_sequence_detail] plan_for_day({idx}) failed: {exc}")
                continue
            if plan.get('runs'):
                weekly_plan.append(plan)

        return {
            "window_start": status.get('window_start'),
            "window_end": status.get('window_end'),
            "cycle_period_seconds": status.get('period'),
            "weekdays": status.get('weekdays'),
            "schedule": status.get('schedule'),
            "weekly_plan": weekly_plan,
            "steps": steps,
            "step_count": len(steps),
            "steps_note": (
                "'weekly_plan' is what actually happens, per weekday, in wall-clock "
                "time — read that to answer 'when does it water?' and to check any "
                "change you just made. 'steps' below is the raw step list with "
                "today's offsets in seconds. Steps sharing a group run together. A "
                "'total' step spans the whole cycle; its lead/lag hold it inside the "
                "other steps' window (pump starts after the valve opens, stops before "
                "it closes). A weekday can override which steps run, their group and "
                "their duration — so ONE sequence covers different days; never create "
                "a second sequence just because a day differs."
            ),
        }

    @staticmethod
    def get_function_detail(function_id):
        """
        Returns detailed configuration for a specific Function-type controller.
        Searches Conditional, Trigger, PID, and CustomController by unique_id
        or name (exact match).

        :param function_id: unique_id (UUID string) or exact name of the function.
        :returns:           dict with full field set for the matched entity.
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            if not function_id:
                return {"error": "function_id is required."}

            # Search order: Conditional → Trigger → PID → CustomController
            cond = Conditional.query.filter(
                (Conditional.unique_id == function_id) | (Conditional.name == function_id)
            ).first()
            if cond:
                return {
                    "function_id": cond.unique_id,
                    "name": cond.name,
                    "function_type": "conditional",
                    "is_activated": bool(getattr(cond, 'is_activated', False)),
                    "period": getattr(cond, 'period', None),
                    "start_offset": getattr(cond, 'start_offset', None),
                    "use_pylint": getattr(cond, 'use_pylint', None),
                    "log_level_debug": getattr(cond, 'log_level_debug', None),
                    "tab_id": getattr(cond, 'tab_id', None),
                }

            trig = Trigger.query.filter(
                (Trigger.unique_id == function_id) | (Trigger.name == function_id)
            ).first()
            if trig:
                detail = {
                    "function_id": trig.unique_id,
                    "name": trig.name,
                    "function_type": "trigger",
                    "trigger_type": getattr(trig, 'trigger_type', None),
                    "is_activated": bool(getattr(trig, 'is_activated', False)),
                    "period": getattr(trig, 'period', None),
                    "timer_start_time": getattr(trig, 'timer_start_time', None),
                    "timer_end_time": getattr(trig, 'timer_end_time', None),
                    "log_level_debug": getattr(trig, 'log_level_debug', None),
                    "tab_id": getattr(trig, 'tab_id', None),
                }
                if getattr(trig, 'trigger_type', None) == 'trigger_sequence':
                    detail.update(AoTDataToolService._sequence_detail(trig))
                return detail

            pid = PID.query.filter(
                (PID.unique_id == function_id) | (PID.name == function_id)
            ).first()
            if pid:
                return {
                    "function_id": pid.unique_id,
                    "name": pid.name,
                    "function_type": "pid",
                    "is_activated": bool(getattr(pid, 'is_activated', False)),
                    "period": getattr(pid, 'period', None),
                    "setpoint": getattr(pid, 'setpoint', None),
                    "log_level_debug": getattr(pid, 'log_level_debug', None),
                    "tab_id": getattr(pid, 'tab_id', None),
                }

            ctrl = CustomController.query.filter(
                (CustomController.unique_id == function_id) | (CustomController.name == function_id)
            ).first()
            if ctrl:
                return {
                    "function_id": ctrl.unique_id,
                    "name": ctrl.name,
                    "function_type": "custom",
                    "device": getattr(ctrl, 'device', None),
                    "is_activated": bool(getattr(ctrl, 'is_activated', False)),
                    "period": getattr(ctrl, 'period', None),
                    "log_level_debug": getattr(ctrl, 'log_level_debug', None),
                    "tab_id": getattr(ctrl, 'tab_id', None),
                }

            return {"error": f"Function not found: {function_id}"}
        except Exception as e:
            logger.exception("Error in get_function_detail")
            return {"error": f"Error while querying Function details: {str(e)}"}

    @staticmethod
    def get_function_doc(function_type):
        """
        @ANCHOR: GET_FUNCTION_DOC_TOOL
        Returns structured documentation for a function type from docs/ai_docs/functions.json.
        Used by the AI to answer advice/guidance queries about PID, Conditional, VPD, etc.

        :param function_type: e.g. 'pid', 'conditional', 'vpd', 'trigger', 'bangbang'
        :returns: Full doc entry dict including params, use_cases, constraints, examples.
        """
        try:
            from aot.ai.services.ai_doc_service import AiDocService
            if not function_type:
                return {"error": "The function_type parameter is required. e.g. 'pid', 'conditional', 'vpd'"}

            # Normalize: try exact key first, then case-insensitive search
            _key = function_type.strip().upper()
            doc = AiDocService.get_function_doc(_key)
            if doc is None:
                # Fallback: keyword search
                results = AiDocService.search(function_type, doc_type='functions')
                if results:
                    return {
                        "function_type": function_type,
                        "note": f"Exact key '{_key}' not found. Best match returned.",
                        "doc": results[0]
                    }
                return {"error": f"No documentation found for '{function_type}'."}

            return {
                "function_type": _key,
                "doc": doc.raw
            }
        except Exception as e:
            logger.exception("Error in get_function_doc")
            return {"error": f"Error while querying documentation: {str(e)}"}

    @staticmethod
    def get_input_doc(query):
        """
        @ANCHOR: GET_INPUT_DOC_TOOL
        Returns catalog info for input (sensor) device types from docs/ai_docs/inputs.json.
        Searches by device type key or keyword (e.g. 'DHT22', 'temperature', 'BME280').

        :param query: Device type key or keyword string.
        :returns: Matching entries with input_name, measurements_name, interfaces, dependencies.
        """
        try:
            from aot.ai.services.ai_doc_service import AiDocService
            if not query:
                return {"error": "The query parameter is required. e.g. 'DHT22', 'temperature', 'BME280'"}

            # Try exact key first (case-insensitive)
            doc = AiDocService.get_input_doc(query.strip().upper())
            if doc:
                return {"query": query, "results": [doc.raw], "count": 1}

            # Fallback: keyword search across catalogue
            results = AiDocService.search(query, doc_type='inputs')
            if results:
                return {"query": query, "results": results[:5], "count": len(results)}

            return {"query": query, "results": [], "count": 0,
                    "note": f"No input device documentation found for '{query}'. "
                            "The Supported-Inputs.md manual has more detailed information."}
        except Exception as e:
            logger.exception("Error in get_input_doc")
            return {"error": f"Error while querying input device documentation: {str(e)}"}

    @staticmethod
    def get_output_doc(query):
        """
        @ANCHOR: GET_OUTPUT_DOC_TOOL
        Returns catalog info for output device types from docs/ai_docs/outputs.json.
        Searches by output type key or keyword (e.g. 'pwm', 'relay', 'peristaltic_pump').

        :param query: Device type key or keyword string.
        :returns: Matching entries with output_name, interfaces, dependencies.
        """
        try:
            from aot.ai.services.ai_doc_service import AiDocService
            if not query:
                return {"error": "The query parameter is required. e.g. 'pwm', 'relay', 'stepper'"}

            # Try exact key first (case-insensitive)
            doc = AiDocService.get_output_doc(query.strip().lower())
            if doc:
                return {"query": query, "results": [doc.raw], "count": 1}

            # Fallback: keyword search across catalogue
            results = AiDocService.search(query, doc_type='outputs')
            if results:
                return {"query": query, "results": results[:5], "count": len(results)}

            return {"query": query, "results": [], "count": 0,
                    "note": f"No output device documentation found for '{query}'. "
                            "The Supported-Outputs.md manual has more detailed information."}
        except Exception as e:
            logger.exception("Error in get_output_doc")
            return {"error": f"Error while querying output device documentation: {str(e)}"}

    @staticmethod
    def activate_function_tool(function_id):
        """
        Activates a Function-type controller (Conditional, Trigger, PID, or
        CustomController). Updates is_activated=True in DB and signals the daemon.

        NOTE: This tool is in APPROVAL_REQUIRED_TOOLS — the planning service
        will intercept it and request human confirmation before execution.

        :param function_id: unique_id (UUID) or exact name of the function.
        :returns:           {"status": "success", ...} or {"error": "..."}
        """
        return AoTDataToolService._set_function_activation(function_id, activate=True)

    @staticmethod
    def deactivate_function_tool(function_id):
        """
        Deactivates a Function-type controller (Conditional, Trigger, PID, or
        CustomController). Updates is_activated=False in DB and signals the daemon.

        NOTE: This tool is in APPROVAL_REQUIRED_TOOLS — the planning service
        will intercept it and request human confirmation before execution.

        :param function_id: unique_id (UUID) or exact name of the function.
        :returns:           {"status": "success", ...} or {"error": "..."}
        """
        return AoTDataToolService._set_function_activation(function_id, activate=False)

    @staticmethod
    def _set_function_activation(function_id, activate):
        """
        Internal helper shared by activate_function_tool and deactivate_function_tool.
        Resolves function type, updates DB, and calls DaemonControl.
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID
            from aot.aot_flask.extensions import db as _db
            from aot.aot_client import DaemonControl

            if not function_id:
                return {"error": "function_id is required."}

            # Resolve entity and controller_type label used by DaemonControl
            mod = None
            controller_type = None

            cond = Conditional.query.filter(
                (Conditional.unique_id == function_id) | (Conditional.name == function_id)
            ).first()
            if cond:
                mod = cond
                controller_type = 'Conditional'

            if mod is None:
                trig = Trigger.query.filter(
                    (Trigger.unique_id == function_id) | (Trigger.name == function_id)
                ).first()
                if trig:
                    mod = trig
                    controller_type = 'Trigger'

            if mod is None:
                pid = PID.query.filter(
                    (PID.unique_id == function_id) | (PID.name == function_id)
                ).first()
                if pid:
                    mod = pid
                    controller_type = 'PID'

            if mod is None:
                ctrl = CustomController.query.filter(
                    (CustomController.unique_id == function_id) | (CustomController.name == function_id)
                ).first()
                if ctrl:
                    mod = ctrl
                    controller_type = 'Function'  # DaemonControl uses 'Function' for CustomController

            if mod is None:
                return {"error": f"Function not found: {function_id}"}

            # Update DB
            mod.is_activated = activate
            _db.session.commit()

            # Signal daemon
            action_label = 'activate' if activate else 'deactivate'
            try:
                daemon = DaemonControl()
                if activate:
                    ret_err, ret_msg = daemon.controller_activate(mod.unique_id)
                else:
                    ret_err, ret_msg = daemon.controller_deactivate(mod.unique_id)

                if ret_err:
                    logger.warning(
                        f"[_set_function_activation] Daemon warning for {mod.unique_id}: {ret_msg}"
                    )
                    return {
                        "status": "success_with_warning",
                        "function_id": mod.unique_id,
                        "name": mod.name,
                        "function_type": controller_type,
                        "is_activated": activate,
                        "daemon_warning": ret_msg,
                        "message": f"DB update complete. Daemon response: {ret_msg}",
                    }
            except Exception as daemon_err:
                # Daemon may be offline — DB update succeeded, log warning
                logger.warning(
                    f"[_set_function_activation] Daemon call failed for {mod.unique_id}: {daemon_err}"
                )
                return {
                    "status": "success_with_warning",
                    "function_id": mod.unique_id,
                    "name": mod.name,
                    "function_type": controller_type,
                    "is_activated": activate,
                    "daemon_warning": str(daemon_err),
                    "message": "DB update complete. The daemon may be offline.",
                }

            logger.info(
                f"[_set_function_activation] {action_label} OK: "
                f"{controller_type}/{mod.unique_id} ({mod.name})"
            )
            return {
                "status": "success",
                "function_id": mod.unique_id,
                "name": mod.name,
                "function_type": controller_type,
                "is_activated": activate,
                "message": f"'{mod.name}' {'activated' if activate else 'deactivated'}",
            }
        except Exception as e:
            logger.exception("Error in _set_function_activation")
            return {"error": f"Error while {'activating' if activate else 'deactivating'} Function: {str(e)}"}

    # @ANCHOR: ENTITY_ACTIVATION — broader than _set_function_activation: also
    # covers Input. Used by the scheduler's 'activate'/'deactivate' action_types
    # (calendar-schedulable activate/deactivate). daemon.controller_activate is
    # uniform across Input/Conditional/Trigger/PID/CustomController (all have
    # is_activated) — same call the /settings UI's controller_activate_deactivate
    # uses (aot_flask/utils/utils_general.py).
    @staticmethod
    def _set_entity_activation(entity_id, activate):
        """Activate/deactivate an Input or controller (Conditional/Trigger/PID/
        CustomController) by unique_id or name. Sets is_activated + signals the
        daemon. Returns a result dict or {'error': ...}."""
        try:
            from aot.databases.models import Input
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID
            from aot.aot_flask.extensions import db as _db
            from aot.aot_client import DaemonControl

            if not entity_id:
                return {"error": "entity_id is required."}

            resolvers = [
                (Conditional, 'Conditional'), (Trigger, 'Trigger'), (PID, 'PID'),
                (CustomController, 'Function'), (Input, 'Input'),
            ]
            mod = None
            kind = None
            for model, label in resolvers:
                mod = model.query.filter(
                    (model.unique_id == entity_id) | (model.name == entity_id)).first()
                if mod is not None:
                    kind = label
                    break
            if mod is None:
                return {"error": f"Activatable entity not found: {entity_id}"}

            mod.is_activated = bool(activate)
            _db.session.commit()

            try:
                daemon = DaemonControl()
                if activate:
                    ret_err, ret_msg = daemon.controller_activate(mod.unique_id)
                else:
                    ret_err, ret_msg = daemon.controller_deactivate(mod.unique_id)
                if ret_err:
                    return {"status": "success_with_warning", "entity_id": mod.unique_id,
                            "name": mod.name, "type": kind, "is_activated": bool(activate),
                            "daemon_warning": ret_msg}
            except Exception as daemon_err:
                logger.warning("[_set_entity_activation] Daemon call failed for %s: %s", mod.unique_id, daemon_err)
                return {"status": "success_with_warning", "entity_id": mod.unique_id,
                        "name": mod.name, "type": kind, "is_activated": bool(activate),
                        "daemon_warning": str(daemon_err)}

            return {"status": "success", "entity_id": mod.unique_id, "name": mod.name,
                    "type": kind, "is_activated": bool(activate),
                    "message": f"'{mod.name}' {'activated' if activate else 'deactivated'}"}
        except Exception as e:
            logger.exception("Error in _set_entity_activation")
            return {"error": f"Error while {'activating' if activate else 'deactivating'}: {str(e)}"}

    @staticmethod
    def get_active_functions_summary(**kwargs):
        """
        Returns a summary of all currently active Function-type controllers.
        Designed for AI context injection — provides a compact view of what
        automation is currently running.

        :returns: {"active_functions": [...], "count": int}
        """
        try:
            from aot.databases.models.function import Conditional, Trigger
            from aot.databases.models.controller import CustomController
            from aot.databases.models.pid import PID

            active = []

            for r in Conditional.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "conditional",
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in Trigger.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "trigger",
                    "trigger_type": getattr(r, 'trigger_type', None),
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in PID.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "pid",
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            for r in CustomController.query.filter_by(is_activated=True).all():
                active.append({
                    "function_id": r.unique_id,
                    "name": r.name,
                    "function_type": "custom",
                    "device": getattr(r, 'device', None),
                    "is_activated": True,
                    "period": getattr(r, 'period', None),
                })

            return {"active_functions": active, "count": len(active)}
        except Exception as e:
            logger.exception("Error in get_active_functions_summary")
            return {"error": f"Error while querying active Function summary: {str(e)}"}

    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_range(range_str):
        if not range_str: return 86400
        range_str = str(range_str).lower()
        if range_str.endswith('h'):
            return int(range_str[:-1]) * 3600
        if range_str.endswith('d'):
            return int(range_str[:-1]) * 86400
        if range_str.isnumeric():
            return int(range_str)
        return 86400

    # -------------------------------------------------------------------------
    # @ANCHOR: FUNCTION_CREATE_TOOLS
    # Function creation and configuration tools.
    # create_function: create a new function by type with optional initial params.
    # modify_function_options: update custom_options of an existing function.
    # get_device_measurements: list measurement channels of an Input or Function.
    # -------------------------------------------------------------------------

    @staticmethod
    def get_device_measurements(device_id):
        """
        Returns all measurement channels for a given Input or CustomController device_id.
        Also accepts a search_devices result dict — extracts the first device_id automatically.
        Used by the AI to resolve measurement IDs needed for select_measurement options.
        """
        try:
            # Accept search_devices result dict (e.g. {"results": [{"id": "..."}], "count": 1})
            if isinstance(device_id, dict):
                results = device_id.get('results') or device_id.get('result', {}).get('results', [])
                if results and isinstance(results, list):
                    device_id = results[0].get('id') or results[0].get('unique_id') or results[0].get('device_id')
            if not device_id or not isinstance(device_id, str):
                return {"error": "device_id is required (string UUID)"}

            rows = DeviceMeasurements.query.filter_by(device_id=device_id).all()
            if not rows:
                return {"error": f"No measurements found for device_id: {device_id}"}

            measurements = [
                {
                    "measurement_id": r.unique_id,
                    "channel": r.channel,
                    "measurement": r.measurement,
                    "unit": r.unit,
                    "name": getattr(r, 'name', ''),
                    # Ready-to-use value for select_measurement fields: "device_id,measurement_id"
                    "select_value": f"{device_id},{r.unique_id}",
                }
                for r in rows
            ]

            # Convenience map: measurement_type → select_value  (e.g. "temperature" → "uuid,uuid")
            # Makes it easy for the AI to pick the right channel by type name.
            select_by_type = {
                m["measurement"]: m["select_value"]
                for m in measurements
            }

            return {
                "device_id": device_id,
                "measurements": measurements,
                "select_by_type": select_by_type,
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def create_function_tool(function_type=None, name=None, params=None, **extra):
        """
        Creates a new function of the given type.
        function_type: one of the registered FUNCTION_INFO keys, e.g.
                       'trigger_sequence' (sequential device control),
                       'conditional_conditional', 'pid_pid', 'trigger_timer_duration'.
        name: optional display name (falls back to function module default)
        params: dict of custom_options values to override after creation.
                For select_measurement fields, use 'device_id,measurement_id' format.
        Returns: {"function_id": "...", "name": "...", "function_type": "..."}

        Hardened: tolerates unexpected top-level kwargs (e.g. an LLM inventing
        `devices=[...]`) instead of raising TypeError — they are ignored with a
        warning, and an invalid/missing function_type returns the valid list so the
        model can self-correct rather than crash. Device/action wiring (which valves,
        order, timing) is NOT set here — it is configured after creation via the
        function editor / modify_function_options.
        """
        import json as _json
        from aot.aot_flask.utils.utils_function import function_add
        from aot.config import FUNCTION_INFO

        _valid = sorted(FUNCTION_INFO.keys())

        if not function_type:
            return {"error": "function_type is required.", "valid_function_types": _valid}

        if function_type not in FUNCTION_INFO:
            return {
                "error": f"Unknown function_type '{function_type}'. There is no dedicated "
                         f"parameter for a device list — to control several devices in "
                         f"order, create a 'trigger_sequence' function, then configure its "
                         f"steps.",
                "valid_function_types": _valid,
            }

        # An LLM sometimes invents top-level args (e.g. devices=[...]). These cannot be
        # mapped to custom_options blindly, so ignore them (never crash) and report it
        # back so the caller learns the correct shape ({function_type, name, params}).
        ignored_args = list(extra.keys())
        if ignored_args:
            logger.warning(f"[create_function] ignoring unexpected args {ignored_args} "
                           f"(only function_type/name/params are accepted)")

        # Minimal form shim — function_add only reads .function_type.data
        class _FakeForm:
            class _Field:
                def __init__(self, data): self.data = data
            def __init__(self, ft): self.function_type = self._Field(ft)

        try:
            messages, dep_name, unmet_deps, dep_msg, new_function_id = function_add(_FakeForm(function_type))
        except Exception as e:
            logger.error(f"[create_function] function_add raised: {e}")
            return {"error": str(e)}

        if messages.get("error"):
            return {"error": "; ".join(messages["error"]), "unmet_deps": unmet_deps}

        if not new_function_id:
            return {"error": "Function created but unique_id not returned"}

        # Look up the newly created record by unique_id. `Function` MUST stay in this
        # list: function_add() creates a plain Function row for 'function_actions', and
        # while it was missing here new_func stayed None for that type — so `name` and
        # `params` were silently dropped and the result reported name "" while the row
        # kept its 'Function Name' default. Same class of omission as the one that made
        # delete_function() report false-positive deletes. If a new controller table is
        # ever added, add it here too.
        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Function, Trigger
        from aot.databases.models.pid import PID

        unapplied = []
        new_func = None
        for Model in [CustomController, Conditional, PID, Trigger, Function]:
            try:
                row = Model.query.filter_by(unique_id=new_function_id).first()
                if row:
                    new_func = row
                    break
            except Exception:
                continue

        if new_func is None:
            # Never fail silently again: the row exists (function_add returned its id)
            # but no known model matched it, so nothing below can be applied.
            logger.error(f"[create_function] created {new_function_id} but no controller "
                         f"model matched it; name/params not applied")
            if name:
                unapplied.append("name")
            if params:
                unapplied.append("params")

        # Apply display name if provided
        if new_func and name:
            new_func.name = name
            db.session.commit()

        # Apply custom params if provided
        logger.info(f"[create_function] new_func={new_func}, params={params}")
        if new_func and params and isinstance(params, dict):
            # Not every controller table has custom_options — `Function` does not.
            # Assigning to a missing column would set a throwaway Python attribute and
            # commit cleanly, reporting success for options that were never stored.
            if not hasattr(type(new_func), 'custom_options'):
                logger.warning(f"[create_function] {type(new_func).__name__} has no "
                               f"custom_options column; params not applied")
                unapplied.append("params")
            else:
                existing = {}
                try:
                    existing = _json.loads(getattr(new_func, 'custom_options', None) or '{}')
                except Exception:
                    existing = {}
                logger.info(f"[create_function] existing before update: {existing}")
                existing.update(params)
                logger.info(f"[create_function] existing after update: {existing}")
                new_func.custom_options = _json.dumps(existing)
                db.session.commit()
                logger.info(f"[create_function] custom_options committed: {new_func.custom_options[:200]}")

        function_id = new_function_id

        # Never auto-activate on creation — this is an absolute rule, not just a default:
        # a freshly-created function has no device steps/targets configured yet, and
        # activation must always be its own explicit, approval-gated step
        # (activate_function), never bundled into creation. Do not reintroduce an
        # 'activate' bypass parameter here.
        result = {
            "function_id": function_id,
            "name": getattr(new_func, 'name', ''),
            "function_type": function_type,
            "status": "created",
            "activated": False,
            "note": ("Created deactivated — configure its options/steps, then "
                     "activate with activate_function."),
        }
        if ignored_args:
            result["ignored_args"] = ignored_args
            result["note"] = ("Ignored non-schema arg(s): "
                              f"{ignored_args}. The function was created (deactivated & empty); "
                              "configure its device steps, then activate.")
        if unapplied:
            # Say so rather than returning a clean result for settings that never landed.
            result["unapplied"] = sorted(set(unapplied))
            result["note"] = (f"Created, but {sorted(set(unapplied))} could not be applied "
                              f"to a '{function_type}' function — set them via the function "
                              "editor / modify_function_options, then activate.")
        return result

    @staticmethod
    def modify_function_options(function_id, params):
        """
        Updates custom_options fields of an existing function.
        params: dict — keys are custom_option IDs, values are the new settings.
                For select_measurement fields: 'device_id,measurement_id' string.
        Also triggers daemon reload so the change takes effect immediately.
        """
        import json as _json
        if not function_id or not params:
            return {"error": "function_id and params are required"}

        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Function, Trigger
        from aot.databases.models.pid import PID

        func = None
        for Model in [CustomController, Conditional, PID, Trigger, Function]:
            try:
                row = Model.query.filter_by(unique_id=function_id).first()
                if row:
                    func = row
                    break
            except Exception:
                continue

        if func is None:
            return {"error": f"Function not found: {function_id}"}

        # Only CustomController and Conditional have a custom_options column. For
        # PID/Trigger/Function the settings are real columns, so the write below
        # would set an unmapped attribute that commit() silently drops — reporting
        # success while changing nothing. This guard used to name Trigger alone, so
        # PID kept failing silently and Function was not even looked up. Test by
        # column, not by class, so a new controller table cannot reopen the hole.
        if not hasattr(type(func), 'custom_options'):
            kind = type(func).__name__
            hint = ("For a trigger_sequence use modify_sequence_schedule (window, "
                    "period, weekdays). Other trigger types must be edited in the "
                    "web UI." if isinstance(func, Trigger) else
                    "Edit it in the web UI.")
            err = {"error": (f"This function is a {kind}; its settings are columns, "
                             f"not custom_options, so this tool cannot change them. {hint}"),
                   "function_id": function_id,
                   "controller_type": kind}
            if isinstance(func, Trigger):
                err["trigger_type"] = getattr(func, 'trigger_type', None)
            return err

        # Capture BEFORE the edit: a deactivated function must stay deactivated.
        was_activated = bool(getattr(func, 'is_activated', False))

        existing = {}
        try:
            existing = _json.loads(getattr(func, 'custom_options', None) or '{}')
        except Exception:
            existing = {}

        existing.update(params)
        func.custom_options = _json.dumps(existing)
        db.session.commit()

        # Reload in daemon so changes take effect without manual restart — but ONLY
        # if it was already running. daemon.controller_activate() is not a reload
        # primitive: it sets is_activated=True in the database and starts the
        # controller thread (aot_daemon.py). Calling it unconditionally meant that
        # editing the options of a DEACTIVATED function turned it on — and since
        # this tool is config_only (approval-exempt), that handed an unapproved
        # path to real device control, breaking the config_only contract in
        # tool_registry.py ("이 도구만으로는 어떤 장비도 움직이지 않는다").
        # Activation stays where it belongs: activate_function, which needs approval.
        reloaded = False
        if was_activated:
            try:
                from aot.aot_client import DaemonControl
                daemon = DaemonControl()
                daemon.controller_deactivate(function_id)
                daemon.controller_activate(function_id)
                reloaded = True
            except Exception as e:
                logger.warning(f"[modify_function_options] daemon reload failed (non-fatal): {e}")

        result = {"function_id": function_id, "status": "modified",
                  "changed": list(params.keys()),
                  "activated": was_activated, "reloaded": reloaded}
        if not was_activated:
            result["note"] = ("Saved while deactivated — it stays deactivated. "
                              "Activate with activate_function (requires approval).")
        return result

    @staticmethod
    def configure_sequence_day(function_id, day, slots, start=None, end=None,
                               period_seconds=None, repeat=False):
        """Set a whole weekday's run plan on a sequence in ONE call.

        Doing this through modify_sequence_step meant one approval per step per
        field — about twenty gated calls to lay out a single evening's watering,
        which is enough friction that a caller gives up and makes a second
        sequence instead (that is exactly what happened on 2026-08-06). Here a
        caller says what a farmer says — "from 21:00, v321 and v322 together for
        40 minutes, then v331 and v332 together for an hour" — and that is one
        approval.

        slots: ordered list of {devices: [name|action_id, ...], minutes|seconds,
        group?}. Devices in the same slot run simultaneously. Any step of the
        sequence not named here is switched OFF for this weekday only; other
        weekdays keep their own plan.
        """
        import json as _json
        from aot.databases.models.function import Actions, Trigger
        from aot.databases.models.output import Output
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, minutes_to_hhmm, time_to_minutes,
            DAY_NAMES)
        from aot.controllers.controller_trigger_sequence import SequenceTriggerController

        if not function_id:
            return {"error": "function_id is required"}
        if not isinstance(slots, list) or not slots:
            return {"error": "slots must be a non-empty ordered list, e.g. "
                             "[{'devices': ['v321','v322'], 'minutes': 40}, ...]"}
        try:
            day = int(day)
        except (TypeError, ValueError):
            return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
        if not 0 <= day <= 6:
            return {"error": f"day must be 0-6 (0=Mon), got {day}"}

        trig = Trigger.query.filter(
            (Trigger.unique_id == function_id) | (Trigger.name == function_id)).first()
        if not trig:
            return {"error": f"Sequence not found: {function_id}"}
        if trig.trigger_type != 'trigger_sequence':
            return {"error": f"'{trig.name}' is a {trig.trigger_type}, not a sequence."}

        steps = Actions.query.filter(Actions.function_id == trig.unique_id).all()
        if not steps:
            return {"error": f"'{trig.name}' has no steps yet — add devices to it first."}

        out_names = {o.unique_id: o.name for o in Output.query.all()}
        index, catalog = {}, []
        for a in steps:
            try:
                o = _json.loads(a.custom_options) if a.custom_options else {}
            except Exception:
                o = {}
            dev = out_names.get(str(o.get('output') or a.do_unique_id or '').split(',')[0], '')
            label = (o.get('display_name') or '').strip()
            for key in filter(None, (a.unique_id, dev, label)):
                index.setdefault(key.lower(), a.unique_id)
            catalog.append(label and f"{label} ({dev})" or dev)

        resolved, unknown = [], []
        for i, slot in enumerate(slots):
            if not isinstance(slot, dict):
                return {"error": f"slots[{i}] must be an object with 'devices' and a duration"}
            names = slot.get('devices') or slot.get('device')
            names = [names] if isinstance(names, str) else list(names or [])
            if not names:
                return {"error": f"slots[{i}] has no 'devices'"}
            if slot.get('minutes') is not None:
                secs = float(slot['minutes']) * 60
            elif slot.get('seconds') is not None:
                secs = float(slot['seconds'])
            else:
                return {"error": f"slots[{i}] needs 'minutes' (or 'seconds')"}
            if secs <= 0:
                return {"error": f"slots[{i}] duration must be positive"}
            ids = []
            for n in names:
                uid = index.get(str(n).strip().lower())
                (ids.append(uid) if uid else unknown.append(n))
            resolved.append({"ids": ids, "seconds": secs,
                             "group": (slot.get('group') or '').strip()})
        if unknown:
            return {"error": f"Not steps of '{trig.name}': {unknown}",
                    "available_steps": sorted(set(catalog))}

        listed = [uid for s in resolved for uid in s['ids']]
        if len(listed) != len(set(listed)):
            return {"error": "The same step appears in more than one slot."}

        sched = parse_schedule(getattr(trig, 'timer_schedule', None)) or from_legacy(
            trig.timer_start_time, trig.timer_end_time,
            getattr(trig, 'timer_weekday', None), trig.period or 3600)
        sched['mode'] = 'per_day'
        entry = sched['days'].setdefault(str(day), {})

        # Run order is global (there is no per-weekday order map), so only
        # PERMUTE the order values these steps already hold. Steps that run on
        # other days keep their own values and their position relative to this
        # set, which is what stops one day's layout from scrambling another's.
        opts_of = {}
        for a in steps:
            try:
                opts_of[a.unique_id] = _json.loads(a.custom_options) if a.custom_options else {}
            except Exception:
                opts_of[a.unique_id] = {}
        pool = sorted(opts_of[u].get('gridstack_y', opts_of[u].get('position', 0)) or 0
                      for u in listed)
        by_uid = {a.unique_id: a for a in steps}
        for pos, uid in zip(pool, listed):
            opts_of[uid]['gridstack_y'] = pos
            by_uid[uid].custom_options = _json.dumps(opts_of[uid])

        actions_map, groups_map, durations_map = {}, {}, {}
        for i, s in enumerate(resolved):
            gname = s['group'] or (f"g{i + 1}" if len(s['ids']) > 1 else '')
            for uid in s['ids']:
                actions_map[uid] = True
                groups_map[uid] = gname
                durations_map[uid] = s['seconds']
        for a in steps:
            if a.unique_id not in actions_map:
                actions_map[a.unique_id] = False

        entry['actions'] = actions_map
        entry['groups'] = groups_map
        entry['durations'] = durations_map
        entry['enabled'] = True

        span = sum(s['seconds'] for s in resolved)  # overlap=0 assumed for sizing
        overlap = float(trig.output_duration or 0)
        if overlap and len(resolved) > 1:
            span += overlap * (len(resolved) - 1)

        entry['start'] = str(start) if start else entry.get('start') or '00:00'
        if end:
            entry['end'] = '24:00' if str(end) == '00:00' else str(end)
        else:
            try:
                fin = time_to_minutes(entry['start']) + int((span + 59) // 60)
                entry['end'] = minutes_to_hhmm(min(fin, 1440))
            except ValueError:
                return {"error": f"start must be 'HH:MM', got {entry['start']!r}"}
        entry['period'] = int(period_seconds) if period_seconds else (
            int(span) if not repeat else int(entry.get('period') or span))

        errors = validate(sched)
        if errors:
            return {"error": "The resulting schedule is not valid", "details": errors}

        trig.timer_schedule = _json.dumps(sched)
        if any(sched['days'].get(str(i), {}).get('enabled') for i in range(7)):
            trig.timer_weekday = ','.join(
                str(i) for i in range(7) if sched['days'].get(str(i), {}).get('enabled'))
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[configure_sequence_day] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        plan = SequenceTriggerController.plan_for_day(trig.unique_id, day)
        return {
            "function_id": trig.unique_id,
            "name": trig.name,
            "status": "configured",
            "plan": plan,
            "note": (f"{DAY_NAMES[day]} only. Steps not listed are off for this weekday; "
                     "other weekdays are untouched. Read 'plan' back to the user — it is "
                     "the actual wall-clock result, not the request."),
        }

    @staticmethod
    def _modify_sequence_step_for_day(action, opts, day, enabled=None, group_name=None,
                                      duration_seconds=None, global_only=None):
        """Per-weekday override for one step, stored in the trigger's schedule.

        A sequence is one ordered step list, but weekly_schedule v1 lets each
        weekday override which steps run (`actions`), how they are grouped
        (`groups`) and how long they run (`durations`). That is how one sequence
        covers, say, a Thursday-evening pass and a Friday-dawn pass with
        different valves — no second sequence needed. The maps live on the
        Trigger, not on the step, so this writes there.
        """
        import json as _json
        from aot.databases.models.function import Actions, Trigger
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, day_action_group, DAY_NAMES)

        blocked = [k for k, v in (global_only or {}).items() if v is not None]
        if blocked:
            return {"error": f"{', '.join(blocked)} cannot be set per weekday — a "
                             "weekday can override which steps run, their group and "
                             "their duration, nothing else. Call again without 'day' "
                             "to change these for every day."}
        if enabled is None and group_name is None and duration_seconds is None:
            return {"error": "With 'day', pass at least one of enabled, group_name, "
                             "duration_seconds."}
        try:
            day = int(day)
        except (TypeError, ValueError):
            return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
        if not 0 <= day <= 6:
            return {"error": f"day must be 0-6 (0=Mon), got {day}"}

        trig = Trigger.query.filter_by(unique_id=action.function_id).first()
        if not trig:
            return {"error": f"Sequence not found for step {action.unique_id}"}

        sched = parse_schedule(getattr(trig, 'timer_schedule', None)) or from_legacy(
            trig.timer_start_time, trig.timer_end_time,
            getattr(trig, 'timer_weekday', None), trig.period or 3600)
        sched['mode'] = 'per_day'
        entry = sched['days'].setdefault(str(day), {})
        uid = action.unique_id

        if enabled is not None:
            entry.setdefault('actions', {})[uid] = bool(enabled)
        if group_name is not None:
            # '' is meaningful here: "explicitly ungrouped on this day".
            entry.setdefault('groups', {})[uid] = str(group_name).strip()

        propagated = []
        if duration_seconds is not None:
            try:
                dur = float(duration_seconds)
            except (TypeError, ValueError):
                return {"error": f"duration_seconds must be a number, got {duration_seconds!r}"}
            if dur < 0:
                return {"error": f"duration_seconds cannot be negative, got {dur}"}
            entry.setdefault('durations', {})[uid] = dur
            # Same invariant as the global path: a group runs on one duration,
            # so every member sharing this day's effective group follows.
            eff = day_action_group(sched, day, uid, (opts.get('group_name') or '').strip() or None)
            if eff:
                for sib in Actions.query.filter(
                        Actions.function_id == action.function_id,
                        Actions.unique_id != uid).all():
                    try:
                        sopts = _json.loads(sib.custom_options) if sib.custom_options else {}
                    except Exception:
                        sopts = {}
                    sib_eff = day_action_group(
                        sched, day, sib.unique_id,
                        (sopts.get('group_name') or '').strip() or None)
                    if sib_eff == eff:
                        entry['durations'][sib.unique_id] = dur
                        propagated.append(sib.unique_id)

        errors = validate(sched)
        if errors:
            return {"error": "Invalid schedule after the per-day change", "details": errors}

        trig.timer_schedule = _json.dumps(sched)
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_step] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        result = {
            "action_id": uid,
            "function_id": trig.unique_id,
            "status": "modified",
            "scope": f"{DAY_NAMES[day]} only",
            "day": day,
            "runs_this_day": entry.get('actions', {}).get(uid, opts.get('enabled', True)),
            "group_this_day": entry.get('groups', {}).get(
                uid, (opts.get('group_name') or '').strip() or None) or None,
            "duration_this_day": entry.get('durations', {}).get(uid, opts.get('action_duration')),
            "note": ("This overrides the step's global setting on this weekday only; "
                     "other weekdays are untouched."),
        }
        if propagated:
            result["duration_propagated_to"] = propagated
        return result

    @staticmethod
    def modify_sequence_step(action_id, group_name=None, duration_seconds=None,
                             mode=None, enabled=None, display_name=None,
                             lead_seconds=None, lag_seconds=None, order=None,
                             day=None):
        """Configure ONE step of a trigger_sequence.

        create_sequence_function only lays down uniform steps (same duration,
        all 'single', never grouped), so without this the AI can build the
        skeleton of a sequence but not the shape a real irrigation run needs —
        valves opening together, different durations per slot, a pump spanning
        the rest. Those live in the step's custom_options, which
        modify_function_options cannot reach (it is Trigger-blind, and steps
        are Actions rows anyway).

        Mirrors the web routes' rules rather than inventing new ones:
        - a device group has ONE common duration, so setting the duration of a
          grouped step propagates to every member (function_sequence_update_
          action_duration);
        - joining an existing group inherits that group's duration;
        - a 'total' step cannot be grouped, and lead/lag apply only to it
          (function_sequence_update_step).
        """
        import json as _json
        from aot.databases.models.function import Actions

        if not action_id:
            return {"error": "action_id is required (from get_function_detail steps[].action_id)"}
        if all(v is None for v in (group_name, duration_seconds, mode, enabled,
                                   display_name, lead_seconds, lag_seconds, order)):
            return {"error": "Nothing to change: pass at least one of group_name, "
                             "duration_seconds, mode, enabled, display_name, "
                             "lead_seconds, lag_seconds, order."}
        if mode is not None and mode not in ('single', 'total'):
            return {"error": f"mode must be 'single' or 'total', got {mode!r}"}

        action = Actions.query.filter_by(unique_id=action_id).first()
        if not action:
            return {"error": f"Step not found: {action_id}"}

        try:
            opts = _json.loads(action.custom_options) if action.custom_options else {}
        except Exception:
            opts = {}

        if day is not None:
            return AoTDataToolService._modify_sequence_step_for_day(
                action, opts, day, enabled=enabled, group_name=group_name,
                duration_seconds=duration_seconds,
                global_only={'mode': mode, 'display_name': display_name,
                             'lead_seconds': lead_seconds, 'lag_seconds': lag_seconds,
                             'order': order})

        effective_mode = mode or opts.get('sequence_mode', 'single')

        def _members_of(name):
            """Sibling steps sharing group `name` (excludes this one)."""
            out = []
            for m in Actions.query.filter(
                    Actions.function_id == action.function_id,
                    Actions.unique_id != action.unique_id).all():
                try:
                    mo = _json.loads(m.custom_options) if m.custom_options else {}
                except Exception:
                    mo = {}
                if (mo.get('group_name') or '').strip() == name:
                    out.append((m, mo))
            return out

        if display_name is not None:
            if str(display_name).strip():
                opts['display_name'] = str(display_name).strip()
            else:
                opts.pop('display_name', None)

        if order is not None:
            # Run order is by gridstack_y (the key the widget's drag-reorder
            # writes, see routes_function.function_save_order) — steps have no
            # separate ordering column. Without this the AI can group and time a
            # sequence but not decide which slot goes first, which for irrigation
            # is half the meaning of "sequence".
            try:
                opts['gridstack_y'] = int(order)
            except (TypeError, ValueError):
                return {"error": f"order must be an integer, got {order!r}"}

        if enabled is not None:
            opts['enabled'] = bool(enabled)

        if mode is not None:
            opts['sequence_mode'] = effective_mode

        inherited = None
        if effective_mode == 'total':
            # Total steps are never grouped; margins are theirs alone.
            opts.pop('group_name', None)
            for key, val in (('total_lead', lead_seconds), ('total_lag', lag_seconds)):
                if val is None:
                    continue
                try:
                    margin = max(0.0, float(val))
                except (TypeError, ValueError):
                    return {"error": f"{key} must be a number of seconds, got {val!r}"}
                if margin:
                    opts[key] = margin
                else:
                    opts.pop(key, None)
        else:
            opts.pop('total_lead', None)
            opts.pop('total_lag', None)
            if group_name is not None:
                name = str(group_name).strip()
                if not name:
                    opts.pop('group_name', None)
                else:
                    opts['group_name'] = name
                    # Joining an existing group inherits its common duration,
                    # unless this call sets one explicitly.
                    if duration_seconds is None:
                        for _m, mo in _members_of(name):
                            if 'action_duration' in mo:
                                opts['action_duration'] = mo['action_duration']
                                inherited = mo['action_duration']
                                break

        propagated = []
        if duration_seconds is not None:
            try:
                dur = float(duration_seconds)
            except (TypeError, ValueError):
                return {"error": f"duration_seconds must be a number, got {duration_seconds!r}"}
            if dur < 0:
                return {"error": f"duration_seconds cannot be negative, got {dur}"}
            opts['action_duration'] = dur
            # One group, one duration — keep the invariant whichever member was edited.
            current_group = (opts.get('group_name') or '').strip()
            if current_group:
                for m, mo in _members_of(current_group):
                    mo['action_duration'] = dur
                    m.custom_options = _json.dumps(mo)
                    propagated.append(m.unique_id)

        action.custom_options = _json.dumps(opts)
        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(action.function_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_step] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        result = {
            "action_id": action.unique_id,
            "function_id": action.function_id,
            "status": "modified",
            "mode": opts.get('sequence_mode', 'single'),
            "group": opts.get('group_name'),
            "duration_seconds": opts.get('action_duration'),
            "enabled": opts.get('enabled', True),
            "display_name": opts.get('display_name'),
            "order": opts.get('gridstack_y'),
        }
        if opts.get('sequence_mode') == 'total':
            result["lead_seconds"] = opts.get('total_lead', 0)
            result["lag_seconds"] = opts.get('total_lag', 0)
        if inherited is not None:
            result["note"] = (f"Joined group '{opts.get('group_name')}' and inherited its "
                              f"common duration ({inherited}s).")
        if propagated:
            result["duration_propagated_to"] = propagated
            result["note"] = (f"A group shares one duration, so {len(propagated)} other "
                              f"step(s) in '{opts.get('group_name')}' were set to {opts['action_duration']}s too.")
        return result

    @staticmethod
    def modify_sequence_schedule(function_id, start=None, end=None,
                                 period_seconds=None, weekdays=None, day=None):
        """Change when a trigger_sequence runs: window, cycle period, weekdays.

        The schedule of record is Trigger.timer_schedule (weekly_schedule v1);
        the legacy timer_* columns are only a fallback the controller uses when
        that JSON is absent, so writing them alone changes nothing for any
        sequence that has one. This edits the JSON and back-syncs the columns,
        exactly as the web form's /function_sequence_update_schedule does.

        Reload goes through refresh_daemon_trigger_settings, which keeps the
        running cycle — deactivate/activate would force every output off and
        restart the cycle from zero, cutting irrigation short mid-run.

        day: 0=Mon..6=Sun. Given, the window/period apply to that weekday only
        (switching the schedule to per_day mode); omitted, they apply to every
        enabled day. weekdays replaces the set of enabled days.
        """
        import json as _json
        from aot.databases.models.function import Trigger
        from aot.utils.weekly_schedule import (
            parse_schedule, from_legacy, validate, to_legacy, build_warnings,
            get_today_idx)

        if not function_id:
            return {"error": "function_id is required"}
        if start is None and end is None and period_seconds is None and weekdays is None:
            return {"error": "Nothing to change: pass at least one of "
                             "start, end, period_seconds, weekdays."}

        trig = Trigger.query.filter(
            (Trigger.unique_id == function_id) | (Trigger.name == function_id)).first()
        if not trig:
            return {"error": f"Sequence not found: {function_id}"}
        if trig.trigger_type != 'trigger_sequence':
            return {"error": f"'{trig.name}' is a {trig.trigger_type}, not a sequence."}

        sched = parse_schedule(getattr(trig, 'timer_schedule', None)) or from_legacy(
            trig.timer_start_time, trig.timer_end_time,
            getattr(trig, 'timer_weekday', None), trig.period or 3600)

        # "00:00" as an end means end-of-day, stored as "24:00" (a literal
        # 00:00 end would fail validation as start >= end).
        if end is not None and str(end).strip() == '00:00':
            end = '24:00'

        if day is not None:
            try:
                day = int(day)
            except (TypeError, ValueError):
                return {"error": f"day must be 0-6 (0=Mon), got {day!r}"}
            if not 0 <= day <= 6:
                return {"error": f"day must be 0-6 (0=Mon), got {day}"}
            sched['mode'] = 'per_day'
            targets = [str(day)]
        else:
            targets = [k for k in (str(i) for i in range(7))
                       if sched['days'].get(k, {}).get('enabled', True)] or \
                      [str(i) for i in range(7)]

        for key in targets:
            entry = sched['days'].setdefault(key, {})
            if start is not None:
                entry['start'] = str(start)
            if end is not None:
                entry['end'] = str(end)
            if period_seconds is not None:
                entry['period'] = int(float(period_seconds))
        if day is None:
            shared = sched.setdefault('shared', {})
            if start is not None:
                shared['start'] = str(start)
            if end is not None:
                shared['end'] = str(end)
            if period_seconds is not None:
                shared['period'] = int(float(period_seconds))

        if weekdays is not None:
            if isinstance(weekdays, str):
                weekdays = [t.strip() for t in weekdays.split(',') if t.strip()]
            try:
                wanted = {int(w) for w in weekdays}
            except (TypeError, ValueError):
                return {"error": f"weekdays must be numbers 0-6 (0=Mon), got {weekdays!r}"}
            if not wanted or any(not 0 <= w <= 6 for w in wanted):
                return {"error": f"weekdays must be numbers 0-6 (0=Mon), got {weekdays!r}"}
            for i in range(7):
                sched['days'].setdefault(str(i), {})['enabled'] = (i in wanted)

        errors = validate(sched)
        if errors:
            return {"error": "Invalid schedule", "details": errors}

        trig.timer_schedule = _json.dumps(sched)
        leg_start, leg_end, leg_weekday, leg_period = to_legacy(sched)
        trig.timer_start_time = leg_start
        trig.timer_end_time = leg_end
        trig.timer_weekday = leg_weekday or None
        trig.period = leg_period
        if sched.get('mode') == 'per_day':
            # trigger.period is what function_status and the widget read, so
            # point it at the period actually running today.
            try:
                from aot.utils.device_tz import get_device_tz
                today = sched['days'].get(str(get_today_idx(str(get_device_tz(trig)))), {})
                if today.get('period') is not None:
                    trig.period = float(today['period'])
            except Exception as exc:
                logger.warning(f"[modify_sequence_schedule] today's period sync failed: {exc}")

        db.session.commit()

        try:
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(trig.unique_id)
        except Exception as exc:
            logger.warning(f"[modify_sequence_schedule] daemon refresh failed "
                           f"(saved, applies on next start): {exc}")

        # Report the days actually edited, not the legacy columns: to_legacy()
        # summarises the whole week from the FIRST ENABLED day, so after a
        # day-scoped edit those columns describe some other day. Relaying them
        # as "the new window" would tell the user the wrong time.
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        applied = []
        for key in targets:
            entry = sched['days'].get(key, {})
            applied.append({
                "day": int(key),
                "day_name": day_names[int(key)],
                "start": entry.get('start'),
                "end": entry.get('end'),
                "period_seconds": entry.get('period'),
                "runs_on_this_day": bool(entry.get('enabled', True)),
            })

        return {
            "function_id": trig.unique_id,
            "name": trig.name,
            "status": "modified",
            "mode": sched.get('mode'),
            "applied": applied,
            "enabled_weekdays": [
                {"day": i, "day_name": day_names[i]}
                for i in range(7)
                if sched['days'].get(str(i), {}).get('enabled', True)
            ],
            "warnings": build_warnings(sched),
            "note": ("'applied' lists only the weekdays this call changed. Other "
                     "weekdays keep their own window/period — check 'schedule' in "
                     "get_function_detail before telling the user the sequence "
                     "runs at one time every day."),
        }

    # ─────────────────────────────────────────────────────────────────────
    # Entity CRUD (Input / Output / Function) — lets the AI create, configure,
    # and delete devices, reusing the same web-layer utilities the UI uses.
    #
    # Pattern (proven by create_function): CREATE wraps the *_add util via a
    # minimal WTForms shim; MODIFY writes name + custom_options directly + daemon
    # reload (robust — avoids replaying every form field); DELETE wraps *_del.
    # Every tool is HARDENED: unexpected kwargs are ignored (never a TypeError),
    # and an invalid/missing type returns the valid list so the model self-corrects.
    # Mutations are approval-gated (see _VIRTUAL_APPROVAL_TOOLS). "Create then
    # configure" — CREATE makes the device with its type; options are filled via
    # MODIFY afterward.
    # ─────────────────────────────────────────────────────────────────────

    class _FakeForm:
        """Minimal WTForms form/field shim: exposes .<field>.data and validate()."""
        class _Field:
            def __init__(self, data): self.data = data
        def __init__(self, **fields):
            for k, v in fields.items():
                setattr(self, k, AoTDataToolService._FakeForm._Field(v))
        def validate(self):
            return True

    @staticmethod
    def _input_types():
        from aot.aot_flask.utils.utils_input import parse_input_information
        return parse_input_information()

    @staticmethod
    def _output_types():
        from aot.utils.outputs import parse_output_information
        return parse_output_information()

    @staticmethod
    def get_tool_detail_tool(tool_name=None, **extra):
        """@ANCHOR: AGENT_LOOP_GET_TOOL_DETAIL — full description + argument schema
        for ONE tool by name (Phase 1 agent loop, docs/design/ai-agent-loop.md §4).
        The lean catalog shown every step is name + one-line description only, to
        keep prompts small; this expands one entry on demand."""
        if not tool_name:
            return {"error": "tool_name is required"}
        from aot.ai.services.tool_registry import TOOLS
        for t in TOOLS:
            if t.name == tool_name.strip():
                if not t.manifest:
                    return {"tool_name": t.name, "detail": "No extended schema recorded for this tool."}
                return {"tool_name": t.name, "detail": dict(t.manifest)}
        return {"error": f"Unknown tool: {tool_name}"}

    @staticmethod
    def list_device_types(kind=None, **extra):
        """List valid device TYPES available for creation.
        kind: 'input' | 'output' | 'function'. Call this BEFORE create_* so the
        chosen type is real (never invent a type). Returns {kind, types:[{type,name}]}."""
        k = (kind or '').lower().strip()
        try:
            if k == 'function':
                from aot.config import FUNCTION_INFO
                return {"kind": "function", "types": [
                    {"type": t, "name": (FUNCTION_INFO[t].get('name') or t)} for t in sorted(FUNCTION_INFO)]}
            if k == 'input':
                d = AoTDataToolService._input_types()
                return {"kind": "input", "types": [
                    {"type": t, "name": (v.get('input_name') or t), "interfaces": v.get('interfaces')}
                    for t, v in sorted(d.items())]}
            if k == 'output':
                d = AoTDataToolService._output_types()
                return {"kind": "output", "types": [
                    {"type": t, "name": (v.get('output_name') or t), "interfaces": v.get('interfaces')}
                    for t, v in sorted(d.items())]}
            return {"error": "kind must be one of: input, output, function"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_device_type_options(kind=None, device_type=None, **extra):
        """Return the configurable OPTION schema (id/type/name/default) for a device
        type, so the AI knows what to pass to modify_*. kind: 'input'|'output'|'function'."""
        k = (kind or '').lower().strip()
        try:
            if k == 'function':
                from aot.config import FUNCTION_INFO
                info = FUNCTION_INFO.get(device_type)
            elif k == 'input':
                info = AoTDataToolService._input_types().get(device_type)
            elif k == 'output':
                info = AoTDataToolService._output_types().get(device_type)
            else:
                return {"error": "kind must be one of: input, output, function"}
            if not info:
                return {"error": f"Unknown {k}_type '{device_type}'"}
            opts = info.get('custom_options') or info.get('options') or []
            out = []
            for o in (opts if isinstance(opts, list) else []):
                if isinstance(o, dict) and o.get('id'):
                    out.append({"id": o.get('id'), "type": o.get('type'),
                                "name": o.get('name'), "default": o.get('default_value')})
            return {"kind": k, "device_type": device_type, "options": out}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def create_input(input_type=None, name=None, interface=None, params=None, **extra):
        """Create a new Input (sensor / data source) of a registered type. Then use
        modify_input to fill its options. Hardened: unknown/missing type returns the
        valid list; unexpected kwargs are ignored."""
        from aot.aot_flask.utils.utils_input import input_add
        try:
            types = AoTDataToolService._input_types()
        except Exception as e:
            return {"error": f"could not load input types: {e}"}
        if not input_type:
            return {"error": "input_type is required", "valid_input_types": sorted(types.keys())}
        if input_type not in types:
            return {"error": f"Unknown input_type '{input_type}'", "valid_input_types": sorted(types.keys())}
        iface = interface or ''
        if not iface:
            ifaces = types[input_type].get('interfaces') or []
            iface = ifaces[0] if ifaces else ''
        form = AoTDataToolService._FakeForm(input_type=f"{input_type},{iface}")
        try:
            ret = input_add(form)
        except Exception as e:
            logger.error(f"[create_input] input_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        new_id = ret[-1] if isinstance(ret, (list, tuple)) else None
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        if not new_id:
            return {"error": "Input created but unique_id not returned"}
        result = {"input_id": new_id, "input_type": input_type, "status": "created"}
        if name or params:
            AoTDataToolService.modify_input(new_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @staticmethod
    def modify_input(input_id=None, name=None, params=None, **extra):
        """Update an Input's display name and/or custom_options, then reload it in the
        daemon. params: dict of option_id → value. Direct write (no full form replay)."""
        import json as _json
        from aot.databases.models import Input
        if not input_id:
            return {"error": "input_id is required"}
        inp = Input.query.filter_by(unique_id=input_id).first()
        if not inp:
            return {"error": f"Input not found: {input_id}"}
        changed = []
        if name:
            inp.name = name; changed.append("name")
        if params and isinstance(params, dict):
            existing = {}
            try:
                existing = _json.loads(getattr(inp, 'custom_options', None) or '{}')
            except Exception:
                existing = {}
            existing.update(params)
            inp.custom_options = _json.dumps(existing); changed.append("custom_options")
        db.session.commit()
        try:
            # DaemonControl has no input_activate/input_deactivate — Input's daemon
            # reload primitive is the generic controller_activate/deactivate pair
            # (aot/aot_flask/utils/utils_general.py's controller_activate_deactivate
            # uses the same two calls for controller_type='Input'). The previous
            # input_activate/input_deactivate calls didn't exist on DaemonControl at
            # all, so this reload always raised AttributeError and silently no-opped
            # (caught below) — the daemon kept running with the pre-edit config.
            from aot.aot_client import DaemonControl
            d = DaemonControl()
            if getattr(inp, 'is_activated', False):
                d.controller_deactivate(input_id); d.controller_activate(input_id)
        except Exception as e:
            logger.warning(f"[modify_input] daemon reload failed (non-fatal): {e}")
        r = {"input_id": input_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def delete_input(input_id=None, **extra):
        """Delete an Input by unique_id."""
        from aot.aot_flask.utils.utils_input import input_del
        if not input_id:
            return {"error": "input_id is required"}
        try:
            messages = input_del(input_id)
        except Exception as e:
            logger.error(f"[delete_input] input_del raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"input_id": input_id, "status": "deleted"}

    @staticmethod
    def create_output(output_type=None, name=None, interface=None, params=None, **extra):
        """Create a new Output (actuator / relay / valve) of a registered type. Then use
        modify_output to fill its options. Hardened like create_input."""
        from aot.aot_flask.utils.utils_output import output_add
        try:
            types = AoTDataToolService._output_types()
        except Exception as e:
            return {"error": f"could not load output types: {e}"}
        if not output_type:
            return {"error": "output_type is required", "valid_output_types": sorted(types.keys())}
        if output_type not in types:
            return {"error": f"Unknown output_type '{output_type}'", "valid_output_types": sorted(types.keys())}
        iface = interface or ''
        if not iface:
            ifaces = types[output_type].get('interfaces') or []
            iface = ifaces[0] if ifaces else ''
        form = AoTDataToolService._FakeForm(output_type=f"{output_type},{iface}")
        try:
            ret = output_add(form, {})  # empty request_form → defaults applied
        except Exception as e:
            logger.error(f"[create_output] output_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        # output_add returns a 6-tuple (...,output_id,size_y) or a 2-tuple (messages,id)
        new_id = None
        if isinstance(ret, (list, tuple)):
            if len(ret) >= 6:
                new_id = ret[4]
            elif len(ret) == 2:
                new_id = ret[1]
            else:
                new_id = ret[-1]
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        if not new_id:
            return {"error": "Output created but unique_id not returned"}
        result = {"output_id": new_id, "output_type": output_type, "status": "created"}
        if name or params:
            AoTDataToolService.modify_output(new_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @staticmethod
    def modify_output(output_id=None, name=None, params=None, **extra):
        """Update an Output's name and/or custom_options, then reload it in the daemon."""
        import json as _json
        from aot.databases.models import Output
        if not output_id:
            return {"error": "output_id is required"}
        out = Output.query.filter_by(unique_id=output_id).first()
        if not out:
            return {"error": f"Output not found: {output_id}"}
        changed = []
        if name:
            out.name = name; changed.append("name")
        if params and isinstance(params, dict):
            existing = {}
            try:
                existing = _json.loads(getattr(out, 'custom_options', None) or '{}')
            except Exception:
                existing = {}
            existing.update(params)
            out.custom_options = _json.dumps(existing); changed.append("custom_options")
        db.session.commit()
        try:
            # DaemonControl has no output_activate/output_deactivate — Output has no
            # is_activated concept at all (it's always "on the bus"; config reload is
            # done via output_setup, the same primitive the web route's
            # manipulate_output('Modify', output_id) uses after an edit — see
            # aot/aot_flask/utils/utils_output.py). The previous output_deactivate/
            # output_activate calls didn't exist on DaemonControl, so this reload
            # always raised AttributeError and silently no-opped (caught below) — the
            # daemon kept running with the pre-edit config.
            from aot.aot_client import DaemonControl
            d = DaemonControl()
            d.output_setup('Modify', output_id)
        except Exception as e:
            logger.warning(f"[modify_output] daemon reload failed (non-fatal): {e}")
        r = {"output_id": output_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def delete_output(output_id=None, **extra):
        """Delete an Output by unique_id."""
        from aot.aot_flask.utils.utils_output import output_del
        if not output_id:
            return {"error": "output_id is required"}
        form = AoTDataToolService._FakeForm(output_id=output_id)
        try:
            messages = output_del(form)
        except Exception as e:
            logger.error(f"[delete_output] output_del raised: {e}")
            return {"error": str(e)}
        if not isinstance(messages, dict):
            return {"output_id": output_id, "status": "deleted"}
        # 삭제 여부와 뒤처리 실패는 다른 질문이다. error 만 보면 커밋까지 끝난
        # 삭제를 "실패" 로 읽어 같은 삭제를 다시 시도하게 되고, error 가 비었다는
        # 이유로 "deleted" 를 돌려주면 지울 것이 없었던 호출까지 성공이 된다.
        if messages.get("deleted"):
            out = {"output_id": output_id, "status": "deleted"}
            if messages.get("error"):
                # 행은 사라졌지만 데몬이 아직 이 출력을 들고 있을 수 있다 —
                # 삼키면 재시작 전까지 유령 출력이 남는다.
                out["cleanup_error"] = "; ".join(messages["error"])
                out["note"] = ("The output was deleted, but post-delete cleanup "
                               "failed. Do NOT retry the delete; report the "
                               "cleanup_error instead.")
            return out
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"error": f"output not found or not deleted: {output_id}"}

    @staticmethod
    def create_sequence_function(name=None, device_ids=None, state='on',
                                 step_duration=0, pause_seconds=0, **extra):
        """Create a trigger_sequence AND fill its steps — one ordered output action per
        device — so it is actually configured, not an empty shell. This is what "밸브
        순차 제어 시퀀스" means: create the trigger, add an output_on_off action for each
        valve in order. Always created deactivated — this tool is config_only (no human
        approval gate) precisely because activation is a separate, approval-gated step
        (activate_function). Do not add an 'activate' bypass here again: a config_only
        tool that can also flip is_activated would let real device control turn on
        without any approval.

        device_ids: ordered list of Output unique_ids (the valves).
        state: 'on'/'off' applied to every step. step_duration: seconds each step runs
        (0 = until the next step). pause_seconds: delay between steps.
        Returns {function_id, steps:[names], step_count, activated}."""
        import json as _json
        from aot.aot_flask.utils.utils_function import function_add
        from aot.databases.models import Output
        from aot.databases.models.function import Actions, Trigger
        try:
            from aot.databases.models import OutputChannel
        except Exception:
            OutputChannel = None

        if not device_ids or not isinstance(device_ids, (list, tuple)):
            return {"error": "device_ids (ordered list of Output ids) is required"}

        # 1. Create the trigger_sequence. function_add does NOT activate (activation is
        #    a separate step), so actions can be added while it is deactivated.
        form = AoTDataToolService._FakeForm(function_type='trigger_sequence')
        try:
            ret = function_add(form)
        except Exception as e:
            logger.error(f"[create_sequence] function_add raised: {e}")
            return {"error": str(e)}
        messages = ret[0] if isinstance(ret, (list, tuple)) else {}
        new_id = ret[-1] if isinstance(ret, (list, tuple)) else None
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        if not new_id:
            return {"error": "Sequence function created but id not returned"}

        trig = Trigger.query.filter_by(unique_id=new_id).first()
        if name and trig:
            trig.name = name

        # 2. One ordered output_on_off action per device (position sets run order).
        _off = str(state).lower() in ('off', 'false', '0', 'close', 'stop')
        st = 'off' if _off else 'on'
        steps = []
        for i, did in enumerate(device_ids):
            o = Output.query.filter_by(unique_id=did).first()
            if not o:
                continue
            chid = ''
            if OutputChannel is not None:
                ch = OutputChannel.query.filter_by(output_id=did).first()
                chid = ch.unique_id if ch else ''
            co = {
                "output": f"{did},{chid}",
                "state": st,
                "duration": 0.0,
                "action_duration": float(step_duration or 0),
                "sequence_mode": "single",
                "position": i,
            }
            act = Actions(
                function_id=new_id, function_type='trigger',
                action_type='output_on_off', custom_options=_json.dumps(co),
                pause_duration=float(pause_seconds or 0),
            )
            if hasattr(act, 'save'):
                act.save()
            else:
                db.session.add(act)
            steps.append(o.name)
        db.session.commit()

        if not steps:
            return {"error": "None of the given device_ids resolved to Outputs; "
                             "no steps added.", "function_id": new_id}

        # Always created deactivated — this is a config_only (unapproved) tool, so it
        # must never be the thing that turns on real device control. Activation is a
        # separate, approval-gated step via activate_function.
        result = {
            "function_id": new_id, "function_type": "trigger_sequence",
            "name": (trig.name if trig else name), "status": "created",
            "steps": steps, "step_count": len(steps), "activated": False,
            "note": "Created deactivated — activate with activate_function (requires approval).",
        }
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @staticmethod
    def delete_function(function_id=None, **extra):
        """Delete a Function/Controller by unique_id (completes function CRUD)."""
        from aot.aot_flask.utils.utils_misc import determine_controller_type
        if not function_id:
            return {"error": "function_id is required"}

        # function_del() only deletes rows from the plain `Function` table
        # (function_actions type). Conditional/PID/Trigger/CustomController live in
        # their own tables, so calling function_del() on those unique_ids silently
        # no-ops (no matching row to delete) while this tool still reported
        # "status": "deleted" — a false-positive delete. Dispatch by actual
        # controller_type, same as the web route (routes_function.py) and
        # function_duplicate() already do.
        controller_type = determine_controller_type(function_id)
        if not controller_type or controller_type == 'Input':
            return {"error": f"No function/controller found with id '{function_id}'"}

        try:
            if controller_type == "Conditional":
                from aot.aot_flask.utils.utils_conditional import conditional_del
                messages = conditional_del(function_id)
            elif controller_type == "PID":
                from aot.aot_flask.utils.utils_pid import pid_del
                messages = pid_del(function_id)
            elif controller_type == "Trigger":
                from aot.aot_flask.utils.utils_trigger import trigger_del
                messages = trigger_del(function_id)
            elif controller_type == "Function_Custom":
                from aot.aot_flask.utils.utils_controller import controller_del
                messages = controller_del(function_id)
            else:  # "Function"
                from aot.aot_flask.utils.utils_function import function_del
                messages = function_del(function_id)
        except Exception as e:
            logger.error(f"[delete_function] delete raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"function_id": function_id, "status": "deleted"}

    # ─────────────────────────────────────────────────────────────────────
    # GIS placement CRUD — place a device on the map (lat/lng), read/delete geo
    # shapes. SAFE by construction: operates on ONE device/shape by id and writes
    # the authoritative latitude/longitude columns directly. It deliberately does
    # NOT use save_overlays (a bulk delta-sync that can wipe a whole layer on an
    # empty payload — see the documented geo-shape wipe incidents). Polygon zone
    # drawing from coordinates is left to the map UI, not the AI.
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def list_pending_confirmations(**extra):
        """[읽기전용] 지금 사람 승인을 기다리는 쓰기/제어 요청 목록. 이전 도구 호출이
        'pending_approval'을 반환했을 때, confirmation_id를 다시 찾거나 사용자에게
        무엇이 대기 중인지 보여줄 때 쓴다. 승인/거부 자체는 respond_to_confirmation을
        쓴다."""
        try:
            from aot.ai.services import mcp_safety_gate as gate
            return {"pending": gate.list_pending()}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def list_geo_maps(**extra):
        """List available maps (geo_id + name + center). Read-only."""
        try:
            from aot.databases.models import GeoMap
            return {"maps": [{"map_id": m.unique_id, "name": m.name,
                              "lat": getattr(m, 'latitude', None), "lng": getattr(m, 'longitude', None)}
                             for m in GeoMap.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    # --- GIS Input CRUD (@ANCHOR: GIS_INPUT_CRUD_TOOLS, 2026-07-26) ---------------
    # GIS layers (VWorld/Google/OpenWeather/OSM/... tile & data providers overlaid
    # on the map) are registered as GeoLayer rows. They are NOT a separate type
    # registry — parse_input_information() (the same one create_input/
    # list_device_types(kind='input') already use) already includes every
    # 'gis_*' key alongside regular sensor Input types, so no new
    # list/get-type-options tools are needed: call list_device_types(kind='input')
    # and filter for names starting with 'gis_', then get_device_type_options(
    # kind='input', device_type='gis_vworld') for that type's option schema.
    @staticmethod
    def list_gis_inputs(**extra):
        """[읽기전용] 등록된 GIS 입력(레이어) 목록 - VWorld/Google/OpenWeather 등
        지도에 얹는 외부 데이터 제공자. 각 항목의 type이 list_device_types(kind='input')
        결과의 'gis_'로 시작하는 타입과 대응한다."""
        try:
            from aot.databases.models import GeoLayer
            return {"gis_inputs": [
                {"layer_id": l.unique_id, "name": l.name, "type": l.type,
                 "is_activated": bool(l.is_activated)}
                for l in GeoLayer.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def create_gis_input(layer_type=None, name=None, params=None, **extra):
        """Creates a new GIS Input (map layer/provider — e.g. gis_vworld,
        gis_openweather). layer_type must come from list_device_types(kind='input'),
        filtered to 'gis_*' entries. Always created DEACTIVATED (matches the web UI's
        own default) — call activate_gis_input afterward once configured. Then use
        modify_gis_input to fill options (e.g. api_key)."""
        from aot.aot_flask.utils.utils_geo import geo_layer_add
        try:
            types = AoTDataToolService._input_types()
        except Exception as e:
            return {"error": f"could not load input types: {e}"}
        if not layer_type:
            gis_types = sorted(t for t in types if t.startswith('gis_'))
            return {"error": "layer_type is required", "valid_gis_types": gis_types}
        if layer_type not in types:
            gis_types = sorted(t for t in types if t.startswith('gis_'))
            return {"error": f"Unknown layer_type '{layer_type}'", "valid_gis_types": gis_types}
        form = AoTDataToolService._FakeForm(input_type=layer_type)
        try:
            messages = geo_layer_add(form)
        except Exception as e:
            logger.error(f"[create_gis_input] geo_layer_add raised: {e}")
            return {"error": str(e)}
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        from aot.databases.models import GeoLayer
        layer = GeoLayer.query.filter_by(type=layer_type).order_by(GeoLayer.id.desc()).first()
        if not layer:
            return {"error": "GIS Input created but could not be looked back up"}
        result = {"layer_id": layer.unique_id, "layer_type": layer_type,
                  "status": "created", "is_activated": False}
        if name or params:
            AoTDataToolService.modify_gis_input(layer.unique_id, name=name, params=params)
            result["configured"] = True
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @staticmethod
    def modify_gis_input(layer_id=None, name=None, params=None, **extra):
        """Updates a GIS Input's name and/or options (e.g. api_key), direct write —
        same lightweight pattern as modify_input (no full form replay). params:
        dict of option_id -> value (e.g. {'api_key': '...'})."""
        import json as _json
        from aot.databases.models import GeoLayer
        if not layer_id:
            return {"error": "layer_id is required"}
        layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
        if not layer:
            return {"error": f"GIS Input not found: {layer_id}"}
        changed = []
        if name:
            layer.name = name; changed.append("name")
        if params and isinstance(params, dict):
            existing = {}
            try:
                existing = _json.loads(layer.options or '{}')
            except Exception:
                existing = {}
            existing.update(params)
            layer.options = _json.dumps(existing); changed.append("options")
        db.session.commit()
        try:
            from aot.aot_flask.utils.utils_geo import invalidate_geo_config_cache
            invalidate_geo_config_cache()
        except Exception as e:
            logger.warning(f"[modify_gis_input] cache invalidation failed (non-fatal): {e}")
        r = {"layer_id": layer_id, "status": "modified", "changed": changed}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def activate_gis_input(layer_id=None, active=True, **extra):
        """Activates or deactivates a GIS Input. New GIS Inputs are created
        deactivated (create_gis_input) — call this once options are configured."""
        from aot.aot_flask.utils.utils_geo import geo_layer_activate
        if not layer_id:
            return {"error": "layer_id is required"}
        try:
            messages = geo_layer_activate(layer_id, active=bool(active))
        except Exception as e:
            logger.error(f"[activate_gis_input] geo_layer_activate raised: {e}")
            return {"error": str(e)}
        if messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"layer_id": layer_id, "status": "activated" if active else "deactivated"}

    @staticmethod
    def delete_gis_input(layer_id=None, **extra):
        """Deletes a GIS Input by unique_id."""
        from aot.aot_flask.utils.utils_geo import geo_layer_del
        if not layer_id:
            return {"error": "layer_id is required"}
        try:
            messages = geo_layer_del(layer_id)
        except Exception as e:
            logger.error(f"[delete_gis_input] geo_layer_del raised: {e}")
            return {"error": str(e)}
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"layer_id": layer_id, "status": "deleted"}

    @staticmethod
    def _find_placeable_device(device_id):
        """Return (obj, kind) for an Input or Output by unique_id, else (None, None)."""
        from aot.databases.models import Input, Output
        o = Input.query.filter_by(unique_id=device_id).first()
        if o:
            return o, 'input'
        o = Output.query.filter_by(unique_id=device_id).first()
        if o:
            return o, 'output'
        return None, None

    @staticmethod
    def get_device_location(device_id=None, **extra):
        """Read a device's current map location (latitude/longitude). Read-only."""
        if not device_id:
            return {"error": "device_id is required"}
        obj, kind = AoTDataToolService._find_placeable_device(device_id)
        if not obj:
            return {"error": f"Device not found: {device_id}"}
        return {"device_id": device_id, "kind": kind, "name": getattr(obj, 'name', None),
                "lat": getattr(obj, 'latitude', None), "lng": getattr(obj, 'longitude', None),
                # [P2] 배치된 지도는 마커에서 파생한다.
                "map_id": _map_for_device_p2(
                    device_id, prefer=getattr(obj, 'map_config_id', None))}

    @staticmethod
    def _distance_error(err):
        """오류를 응답 dict 로. 모호할 때는 후보를 실은 dict 가 그대로 온다 —
        문구로 뭉개면 되물을 근거(후보 uuid)가 사라진다."""
        return err if isinstance(err, dict) else {"error": err}

    @staticmethod
    def distance_between(target_a=None, target_b=None, **extra):
        """[읽기전용] 지도 위 두 개체 사이의 거리(m). 저장하지 않는다.

        **거리를 직접 계산하지 말 것.** 좌표 산술은 조용히 틀리고, 틀린 거리는
        그대로 배치 결정이 된다. 이 도구가 서버에서 센다.

        이름(사람이 부르는 대로) 또는 unique_id 를 받는다. 이름이 여러 개에
        걸리면 **하나를 고르지 않고** `needs_disambiguation` 과 후보 목록을
        돌려준다 — 검정콩을 다섯 조각에 심었으면 "검정콩까지 거리" 는 답이
        없는 질문이다. 그 후보를 사람에게 보여 되물을 것.
        """
        try:
            from aot.utils import geo_distance
            if not target_a or not target_b:
                return {"error": "target_a and target_b are required "
                                 "(names or unique_ids)"}
            result, err = geo_distance.distance_between(target_a, target_b)
            if err:
                return AoTDataToolService._distance_error(err)
            return result
        except Exception as e:
            logger.exception("Error in distance_between")
            return {"error": str(e)}

    @staticmethod
    def nearest(reference=None, candidates=None, **extra):
        """[읽기전용] 기준 개체에서 가까운 순으로 후보를 정렬한다.

        "관리사무소에서 가까운 순으로 품종을 배정" 같은 요청이 이 도구 하나로
        끝난다 — 후보마다 distance_between 을 부르고 손으로 정렬하지 말 것.

        결과에서 빠진 후보는 `unresolved`(못 찾음) 또는 `ambiguous`(여러 개에
        걸림) 로 실린다. **둘 다 사람에게 그대로 알릴 것** — 목록이 짧아진
        이유는 "멀어서" 가 아니고, 특히 ambiguous 는 답이 있는데 못 고른
        것이라 되물으면 해결된다.
        """
        try:
            from aot.utils import geo_distance
            if not reference:
                return {"error": "reference is required (a name or unique_id)"}
            result, err = geo_distance.nearest(reference, candidates)
            if err:
                return AoTDataToolService._distance_error(err)
            return result
        except Exception as e:
            logger.exception("Error in nearest")
            return {"error": str(e)}

    @staticmethod
    def set_device_location(device_id=None, lat=None, lng=None, map_id=None, **extra):
        """Place / move a device (Input or Output) on the map by writing its
        latitude/longitude columns (the authoritative location). Optional map_id binds
        it to a specific map. This is the GIS 'create/edit' for a device placement."""
        if not device_id:
            return {"error": "device_id is required"}
        if lat in (None, '') or lng in (None, ''):
            return {"error": "lat and lng are required"}
        obj, kind = AoTDataToolService._find_placeable_device(device_id)
        if not obj:
            return {"error": f"Device not found: {device_id}"}
        try:
            if hasattr(obj, 'latitude'):
                obj.latitude = float(lat)
            if hasattr(obj, 'longitude'):
                obj.longitude = float(lng)
            # [P2] map_config_id 는 사망 컬럼이다 — 배치(마커)가 정본이며
            # 지도 소속은 거기서 파생된다. 저장하지 않는다.
            if hasattr(obj, 'location_updated_utc'):
                from datetime import datetime as _dt
                obj.location_updated_utc = _dt.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"device_id": device_id, "kind": kind, "status": "placed",
             "lat": float(lat), "lng": float(lng)}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def _get_vworld_credentials():
        """VWorld GIS Input(GeoLayer type='gis_vworld')에 등록된 api_key/domain을
        읽는다. 없으면 (None, None). routes_geo.py의 동명 헬퍼와 같은 저장 방식
        (GeoLayer.options JSON)을 따르는 서비스 계층 전용 사본 — 서비스가 라우트
        모듈에 의존하지 않도록 분리."""
        import json as _json
        layer = (GeoLayer.query.filter_by(type='gis_vworld', is_activated=True).first()
                 or GeoLayer.query.filter_by(type='gis_vworld').first())
        if not layer:
            return None, None
        try:
            opts = _json.loads(layer.options) if layer.options else {}
        except Exception:
            opts = {}
        return opts.get('api_key') or None, opts.get('vworld_domain', '')

    @staticmethod
    def get_address(target_name=None, target_id=None, lat=None, lng=None, **extra):
        """
        [읽기전용] 좌표 또는 위치 이름(구역/시설/장치)을 사람이 읽는 주소로
        변환한다 (역지오코딩). 등록·활성화된 VWorld GIS Input에 API Key가 설정된
        경우에만 동작하며, 없으면 좌표만 돌려주는 대신 그 사실을 명확히 알린다.

        위치 이름 해석은 get_local_time_tool과 동일한 경로를 쓴다:
        _resolve_note_target으로 target_id를 얻고, resolve_location_coords로
        중심좌표(GeoShape는 centroid, 장치는 자신의 lat/lng)를 구한다.
        """
        try:
            from aot.utils.device_tz import resolve_location_coords

            resolved_name = target_name

            if lat in (None, '') or lng in (None, ''):
                if not target_id and target_name:
                    target_id, _tt, resolved_name, _lat, _lng = \
                        AoTDataToolService._resolve_note_target(target_name)
                    if not target_id:
                        return {
                            "status": "error",
                            "message": f"위치 '{target_name}'를 찾지 못했습니다.",
                            "available_targets": AoTDataToolService._geoshape_name_candidates(),
                        }
                if not target_id:
                    return {"status": "error",
                            "message": "target_name, target_id, 또는 lat/lng 중 하나는 필요합니다."}
                lat, lng = resolve_location_coords(target_id)
                if lat is None or lng is None:
                    return {"status": "error",
                            "message": f"'{resolved_name or target_id}'의 좌표를 확인할 수 없습니다."}

            api_key, domain = AoTDataToolService._get_vworld_credentials()
            if not api_key:
                return {
                    "status": "error",
                    "message": ("VWorld GIS Input이 등록되어 있지 않거나 API Key가 설정되지 "
                                 "않았습니다. 지도 > GIS 입력에서 VWorld를 먼저 등록해 주세요."),
                }

            from aot.inputs_gis.gis_vworld import InputModule as VWorldInput
            result = VWorldInput.reverse_geocode(float(lat), float(lng), api_key, domain)
            result["lat"], result["lng"] = float(lat), float(lng)
            if resolved_name:
                result["location"] = resolved_name
            return result
        except Exception as e:
            logger.error(f"Error in get_address: {e}")
            return {"status": "error", "message": f"주소 변환 중 오류: {str(e)}"}

    @staticmethod
    def delete_geo_shape(shape_id=None, **extra):
        """Delete a SINGLE geo shape (zone / area / marker) by its unique_id. Guarded:
        one shape by id — never a bulk/layer delete."""
        # [S5] 도형 삭제는 geo 게이트웨이로만 — 시설·bay·설정점 연쇄와
        # 장치 소속 해제는 DB 트리거가 처리하므로 여기서 알 필요가 없다.
        from aot.aot_flask.geo.device_placement import delete_shape
        if not shape_id:
            return {"error": "shape_id is required"}
        try:
            stype = delete_shape(shape_id, commit=True)
            if stype is None:
                return {"error": f"Geo shape not found: {shape_id}"}
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        return {"shape_id": shape_id, "shape_type": stype, "status": "deleted"}

    # ─────────────────────────────────────────────────────────────────────
    # 공간-장치 바인딩 — 미배정 자리 조회 / 장치 단위 교체 (Phase D)
    #
    # 쓰기는 반드시 device_binding 게이트웨이를 지난다(GB-7). 여기서 GeoShape
    # 나 geo_binding 을 직접 만지지 않는다 — 마커 충돌 판정·채널 축소 처리·
    # 레거시 컬럼 동기화가 전부 게이트웨이 안에 있고, 그 셋 중 하나라도 빠지면
    # 조용히 깨진다.
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def list_unbound_slots(map_id=None, facility_id=None, kinds=None, **extra):
        """Slots with no device bound — what a deletion or a swap left behind.
        Read-only."""
        from aot.aot_flask.geo import device_binding

        if isinstance(kinds, str):
            kinds = [k.strip() for k in kinds.split(',') if k.strip()]
        try:
            slots = device_binding.unbound_slots(
                facility_uuid=facility_id or None,
                map_uuid=map_id or None,
                kinds=tuple(kinds) if kinds else None)
        except Exception as e:
            return {"error": str(e)}
        return {"slots": slots, "count": len(slots)}

    @staticmethod
    def rebind_device(old_device_id=None, new_device_id=None, **extra):
        """Move every map slot held by one device over to another device.
        Requires human approval — this changes WHICH physical machine a zone
        or marker commands."""
        from aot.aot_flask.geo import device_binding

        if not old_device_id or not new_device_id:
            return {"error": "old_device_id and new_device_id are required"}
        try:
            result = device_binding.rebind_device(
                old_device_id, new_device_id, commit=True)
        except device_binding.BindingConflict as e:
            db.session.rollback()
            return {"error": str(e), "conflict": True}
        except (device_binding.BindingError,
                device_binding.BindingNotFound) as e:
            db.session.rollback()
            return {"error": str(e)}
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}

        result["status"] = "rebound" if result["moved"] else "nothing_moved"
        return result

    # ─────────────────────────────────────────────────────────────────────
    # AI Agent CRUD — create/edit/delete the pipeline agents. Reuses the same model
    # ops as the web routes (routes_ai_agent), minus request.form. An agent must
    # reference an AIEntry (the AI service/model) — list_ai_entries provides these.
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def list_ai_agents(**extra):
        """List AI pipeline agents. Read-only."""
        try:
            from aot.databases.models.ai import AIAgent
            return {"agents": [{"agent_id": a.unique_id, "name": a.name, "role": a.role,
                                "pipeline_role": a.pipeline_role, "specialty": a.specialty,
                                "entry_id": a.entry_id, "is_activated": a.is_activated}
                               for a in AIAgent.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def list_ai_entries(**extra):
        """List AI service entries (models) that an agent can be bound to. Read-only.
        Call before create_ai_agent to get a valid entry_id."""
        try:
            from aot.databases.models.ai import AIEntry
            return {"entries": [{"entry_id": e.unique_id, "name": e.name,
                                 "model_type": e.model_type, "model_name": e.model_name}
                                for e in AIEntry.query.all()]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def create_ai_agent(name=None, entry_id=None, role='worker', specialty='general',
                        system_prompt=None, pipeline_role='worker', model_tier='standard',
                        tool_access='auto', **extra):
        """Create a new AI pipeline agent bound to an AIEntry (AI service). Hardened:
        missing/invalid entry_id returns the available entries so the model can pick one."""
        import json as _json
        from aot.databases.models.ai import AIAgent, AIEntry
        if not name:
            return {"error": "name is required"}
        entries = AIEntry.query.all()
        if not entry_id:
            return {"error": "entry_id is required (the AI service to bind to)",
                    "available_entries": [{"entry_id": e.unique_id, "name": e.name} for e in entries]}
        entry = AIEntry.query.filter_by(unique_id=entry_id).first()
        if not entry:
            return {"error": f"AIEntry not found: {entry_id}",
                    "available_entries": [{"entry_id": e.unique_id, "name": e.name} for e in entries]}
        if not system_prompt:
            system_prompt = 'You are a helpful assistant for the AoT (AI of Things) platform.'
        try:
            agent = AIAgent(
                name=name, entry_id=entry_id, role=role, specialty=specialty,
                system_prompt=system_prompt, pipeline_role=pipeline_role,
                model_tier=model_tier, tool_access=tool_access,
                custom_options_json='{}', is_activated=False,
            )
            if hasattr(agent, 'save'):
                agent.save()
            else:
                db.session.add(agent); db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"[create_ai_agent] failed: {e}")
            return {"error": str(e)}
        r = {"agent_id": agent.unique_id, "name": name, "status": "created"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def modify_ai_agent(agent_id=None, **fields):
        """Update an AI agent's editable fields (name, role, specialty, system_prompt,
        pipeline_role, model_tier, tool_access, model_name). Unknown fields ignored."""
        from aot.databases.models.ai import AIAgent
        if not agent_id:
            return {"error": "agent_id is required"}
        agent = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent:
            return {"error": f"Agent not found: {agent_id}"}
        allowed = {'name', 'role', 'specialty', 'system_prompt', 'pipeline_role',
                   'model_tier', 'tool_access', 'model_name'}
        changed, ignored = [], []
        for k, v in fields.items():
            if k in allowed:
                setattr(agent, k, v); changed.append(k)
            else:
                ignored.append(k)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"agent_id": agent_id, "status": "modified", "changed": changed}
        if ignored:
            r["ignored_args"] = ignored
        return r

    @staticmethod
    def delete_ai_agent(agent_id=None, **extra):
        """Delete an AI agent by unique_id (also clears its MCP access mappings)."""
        from aot.databases.models.ai import AIAgent
        if not agent_id:
            return {"error": "agent_id is required"}
        agent = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent:
            return {"error": f"Agent not found: {agent_id}"}
        try:
            from aot.databases.models.mcp_server import AgentMCPAccess
            AgentMCPAccess.query.filter_by(agent_unique_id=agent_id).delete()
        except Exception as e:
            logger.warning(f"[delete_ai_agent] mapping cleanup failed (non-fatal): {e}")
        try:
            db.session.delete(agent)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        return {"agent_id": agent_id, "status": "deleted"}

    # ─────────────────────────────────────────────────────────────────────
    # Notice board CRUD (2026-07-08) — wraps the same web-route utilities the
    # notice board UI uses (utils_notice.py), via the shared _FakeForm shim.
    # Attachments/polls are UI-only; modify/delete permission (admin or the
    # post's own author) is enforced by utils_notice.can_manage_post() against
    # the ACTUAL calling user's session — not bypassed by going through the AI.
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def list_notices(limit=10, **extra):
        """List notice board posts, most recent first. Read-only."""
        try:
            from aot.databases.models import NoticePost
            posts = (NoticePost.query.order_by(NoticePost.date_time.desc())
                     .limit(int(limit) if limit else 10).all())
            return {"notices": [
                {"notice_id": p.unique_id, "title": p.title, "pinned": bool(p.pinned),
                 "date_time": serialize_ts(p.date_time) if p.date_time else None}
                for p in posts
            ]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def create_notice(title=None, body=None, pinned=False, **extra):
        """Create a notice board post (title + body only — attachments/polls
        require the web UI). Uses the same notice_add() the web route calls."""
        from aot.aot_flask.utils.utils_notice import notice_add
        if not title and not body:
            return {"error": "title or body is required"}
        form = AoTDataToolService._FakeForm(
            title=title, body=body, category=None, files=[],
            publish_now=True, publish_at=None,
            set_expire=False, expire_at=None,
            pinned=bool(pinned),
        )
        try:
            errors, post = notice_add(form)
        except Exception as e:
            logger.error(f"[create_notice] notice_add raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        if not post:
            return {"error": "Notice created but no post returned"}
        r = {"notice_id": post.unique_id, "title": post.title, "status": "created"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def modify_notice(notice_id=None, title=None, body=None, pinned=None, **extra):
        """Update an existing notice post's title/body/pinned state. Requires
        the calling user to be the post's author or an admin (enforced by
        utils_notice.can_manage_post() on the caller's real session)."""
        from aot.aot_flask.utils.utils_notice import notice_mod
        from aot.databases.models import NoticePost
        if not notice_id:
            return {"error": "notice_id is required"}
        existing = NoticePost.query.filter_by(unique_id=notice_id).first()
        if not existing:
            return {"error": f"Notice not found: {notice_id}"}
        form = AoTDataToolService._FakeForm(
            notice_unique_id=notice_id,
            title=title if title is not None else existing.title,
            body=body if body is not None else existing.body,
            category=existing.category,
            files=[],
            publish_now=(existing.publish_at is None), publish_at=existing.publish_at,
            set_expire=(existing.expire_at is not None), expire_at=existing.expire_at,
            pinned=(bool(pinned) if pinned is not None else existing.pinned),
        )
        try:
            errors, post = notice_mod(form)
        except Exception as e:
            logger.error(f"[modify_notice] notice_mod raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        r = {"notice_id": notice_id, "status": "modified"}
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @staticmethod
    def delete_notice(notice_id=None, **extra):
        """Delete a notice post by unique_id. Requires the calling user to be
        the post's author or an admin (enforced by can_manage_post())."""
        from aot.aot_flask.utils.utils_notice import notice_del
        if not notice_id:
            return {"error": "notice_id is required"}
        try:
            errors = notice_del(notice_id)
        except Exception as e:
            logger.error(f"[delete_notice] notice_del raised: {e}")
            return {"error": str(e)}
        if errors:
            return {"error": "; ".join(str(e) for e in errors)}
        return {"notice_id": notice_id, "status": "deleted"}

    # ─────────────────────────────────────────────────────────────────────
    # Notes create (2026-07-08) — a plain, undated memo/journal entry. Direct
    # ORM write to the Notes model (search_notes_tool already covers the read
    # side). Distinct from add_schedule, which registers a DATED human work
    # task through SchedulerJobMeta, not this model.
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    @_with_translated_alias
    def _resolve_note_target(target_name):
        """Resolve a human location/entity name to (target_id, target_type,
        resolved_name, gps_lat, gps_lng). Returns (None, ...) when no match.

        Notes attach to an entity via target_id == that entity's unique_id, and
        the per-entity note view filters by target_id, so an unresolved name must
        NOT silently become a floating (invisible) note.

        Zone names are HIERARCHICAL and short: a user says "1포장 1-1" meaning the
        zone named "1-1" inside the site named "1포장" (the zone row's own name is
        just "1-1"). So resolution: exact full-name match → token-based match that
        prefers the most specific shape (zone/feature over site) and uses a site
        token to disambiguate via parent_id → substring fallback → Input/Output.
        """
        if not target_name or not str(target_name).strip():
            return None, None, None, None, None
        _q = str(target_name).strip()
        _ql = _q.lower()

        # 이름이 있는 도형: 파싱 결과를 공용 인덱스에서 받는다.
        # 예전에는 이 함수와 `_resolve_note_target_ids` 가 각자
        # `GeoShape.query.all()` 을 돌아, 이름 하나 해석에 그 조회가 세 번
        # 났다(실측 23.5ms × 3). 비용은 파싱이 아니라 JSON 컬럼이 실린 행을
        # 읽는 것이다.
        from aot.aot_flask.geo import shape_index
        shapes = shape_index.named_shapes()

        def _ret(shape, name):
            _tt = shape.type if shape.type in ('zone', 'site', 'facility', 'facility_bay', 'equipment') else 'zone'
            return shape.unique_id, _tt, name, None, None

        _ZONE_TYPES = ('zone', 'feature', 'device')

        # 1) Exact full-name match (most reliable). Prefer a more specific type.
        exact = [(s, n) for (s, n, nl) in shapes if nl == _ql]
        if exact:
            exact.sort(key=lambda sn: 0 if sn[0].type in _ZONE_TYPES else 1)
            return _ret(*exact[0])

        # 2) Token-based hierarchical match, e.g. "1포장 1-1" → site "1포장" + zone "1-1".
        tokens = [t for t in _ql.replace(',', ' ').split() if t]
        if len(tokens) >= 2:
            token_set = set(tokens)
            site_ids = {s.id for (s, n, nl) in shapes if s.type == 'site' and nl in token_set}
            zone_hits = [(s, n) for (s, n, nl) in shapes if s.type in _ZONE_TYPES and nl in token_set]
            if zone_hits:
                # Disambiguate by parent site when a site token is present.
                if site_ids:
                    scoped = [(s, n) for (s, n) in zone_hits if s.parent_id in site_ids]
                    if scoped:
                        return _ret(*scoped[0])
                return _ret(*zone_hits[0])
            # Only a site matched a token → attach to the site.
            site_hits = [(s, n) for (s, n, nl) in shapes if s.type == 'site' and nl in token_set]
            if site_hits:
                return _ret(*site_hits[0])

        # 3) Substring fallback, preferring the most specific (zone-like) shape.
        #
        # Both directions need a floor of two characters on the SHORTER side.
        # A one-character shape name ('2' — a real zone here) is contained in
        # any sentence that happens to hold that character: '비닐하우스 2동 옆
        # 창고' resolved to zone '2' with status 'success' and the note "resolves
        # to exactly one entity", so add_schedule/create_note wrote there with
        # nothing in the response to doubt. The mirror case is as bad — a
        # one-character QUERY is contained in half the names on the map.
        #
        # Length is the guard rather than a word-boundary check because Korean
        # particles attach directly to the noun ('1포장에', '3-1에서'): requiring
        # a delimiter after the name would reject most of how people actually
        # write. That leaves a two-character name matching inside a longer word
        # ('25' in '온도 25도'); the map has no such name today, and tightening
        # further would cost more real usage than it buys.
        subs = [(s, n) for (s, n, nl) in shapes
                if (len(_ql) >= 2 and _ql in nl) or (len(nl) >= 2 and nl in _ql)]
        if subs:
            # Several DIFFERENT names matching is a question, not an answer.
            # '포장' hits 1포장·2포장·3포장 and taking the first wrote to 1포장
            # without ever saying it chose. Distinct NAMES, not rows — three
            # shapes all named '육묘장' are one answer, not an ambiguity.
            if len({n for (_s, n) in subs}) > 1:
                subs = []
        if subs:
            subs.sort(key=lambda sn: 0 if sn[0].type in _ZONE_TYPES else 1)
            return _ret(*subs[0])

        # 4) Input / Output devices by name.
        for model, _tt in ((Input, 'input'), (Output, 'output')):
            row = model.query.filter(model.name.ilike(f"%{_q}%")).first()
            if row:
                return row.unique_id, _tt, row.name, None, None

        # 5) Crop-name fallback — growers say what GROWS there, not the map name.
        by_subject = AoTDataToolService._resolve_target_by_subject(_q)
        if by_subject:
            return by_subject

        return None, None, None, None, None

    # Place words people append to a subject name. Longest first so '재배지' is
    # tried before any shorter word that could also match. '포장'/'구역' are in
    # the site/zone naming scheme too, but stripping them is harmless HERE:
    # this runs only after every GeoShape match already failed, so a real
    # '3포장' never reaches it.
    _CROP_PLACE_SUFFIXES = ('재배지', '하우스', '농장', '온실', '포장', '구역', '밭')

    @staticmethod
    def _strip_place_suffix(text):
        """'콩밭' → '콩', '상추 재배지' → '상추'. None when nothing was stripped."""
        t = str(text or '').strip()
        for suf in AoTDataToolService._CROP_PLACE_SUFFIXES:
            if t.endswith(suf) and len(t) > len(suf):
                return t[:-len(suf)].strip() or None
        return None

    @staticmethod
    def _active_subject_plots():
        """Active GeoPlot rows paired with the zone that contains them, as
        [{'subject','variety','name','plot_id','zone_id','zone_type','zone_name'}].

        **A plot IS a write target now.** It was not when this was written —
        notes and schedules only attached to GeoShapes, so a plot outside every
        zone was useless and got dropped. Since 2026-08-18 a note's selected
        span can become a schedule attached to the plot itself, so dropping
        those rows means the resolver cannot reach what the user just created.
        `zone_*` stays (a plot is still reported with the zone it sits in), but
        it is no longer required.
        """
        import json as _json
        from aot.databases.models import GeoMap
        from aot.aot_flask.geo import plot_context, device_membership

        out = []
        try:
            maps = GeoMap.query.all()
        except Exception:
            return out

        for m in maps:
            try:
                rows = plot_context.active_plots(m.unique_id)
            except Exception:
                continue
            if not rows:
                continue
            try:
                containers = device_membership.load_containers(m.unique_id)
            except Exception:
                containers = None
            for row in rows:
                try:
                    zone = plot_context.zone_for_plot(row, containers=containers)
                except Exception:
                    zone = None
                zone_name, zone_id, _zt = '', None, None
                if zone is not None:
                    try:
                        feat = zone.feature if isinstance(zone.feature, dict) else _json.loads(zone.feature or '{}')
                        props = feat.get('properties') or {}
                        zone_name = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
                    except Exception:
                        zone_name = ''
                    zone_id = zone.unique_id
                    _zt = zone.type if zone.type in ('zone', 'site', 'facility', 'facility_bay', 'equipment') else 'zone'
                out.append({
                    'subject': row.subject, 'variety': row.variety, 'name': row.name,
                    'plot_id': row.unique_id,
                    'zone_id': zone_id, 'zone_type': _zt, 'zone_name': zone_name,
                })
        return out

    @staticmethod
    def _resolve_target_by_subject(query):
        """Resolve '콩밭' / '장풍' to the PLOT that subject is in.

        Farm hands name a plot by what is in it, not by the map's zone name
        ('3-1'), so every zone-name pass above misses those words entirely.
        Matching runs against ACTIVE plots only — last year's subject must not
        steer this year's note.

        **It resolves to the plot, not its zone.** It used to return the
        containing zone, because a GeoPlot could not be written against.
        That stopped being true on 2026-08-18: a note's selected span becomes a
        schedule attached to the plot. Returning the zone meant the user asked
        about '장풍', the resolver answered 'zone 3-1', and the two schedules
        sitting on 장풍 itself were unreachable by any name (measured — 0 hits).

        Returns the same 5-tuple as _resolve_note_target(), or None for no match.

        One subject spread over several PLOTS resolves to None on purpose. The
        5-tuple cannot carry 'ambiguous', and this resolver feeds write tools
        (add_schedule, create_note) — picking the first would silently write to
        the wrong plot. No match lets the caller ask.
        """
        try:
            plots = AoTDataToolService._active_subject_plots()
        except Exception as e:
            logger.debug(f"_resolve_target_by_subject: plot lookup failed: {e}")
            return None
        if not plots:
            return None

        ql = str(query or '').strip().lower()
        if not ql:
            return None

        def _fields(p):
            return [str(v).strip().lower()
                    for v in (p['subject'], p['variety'], p['name'])
                    if v and str(v).strip()]

        def _one_zone(hits):
            """이름 하나가 구획 하나로 좁혀질 때만 답한다.

            같은 작물이 두 구획에 있으면 None — 5-tuple 에 '모호함' 을 담을
            자리가 없고, 이 리졸버는 쓰기 도구도 쓰므로 하나를 골라 버리면
            엉뚱한 구획에 조용히 쓰인다.
            """
            plot_ids = {p.get('plot_id') for p in hits if p.get('plot_id')}
            if len(plot_ids) == 1:
                p = next(h for h in hits if h.get('plot_id'))
                label = p.get('name') or p.get('subject')
                return p['plot_id'], 'plot', label, None, None
            # 구획 id 가 없는(옛 데이터) 경우에만 zone 으로 물러선다.
            zone_ids = {p['zone_id'] for p in hits if p.get('zone_id')}
            if len(zone_ids) != 1:
                return None
            p = next(h for h in hits if h.get('zone_id'))
            return p['zone_id'], p['zone_type'], p['zone_name'], None, None

        stems = [ql]
        stripped = AoTDataToolService._strip_place_suffix(ql)
        if stripped:
            stems.append(stripped)

        for stem in stems:
            hits = [p for p in plots if stem in _fields(p)]
            if hits:
                return _one_zone(hits)

        # Partial match, kept tight on both sides: a 1-character subject name ('마')
        # matches inside half the words in the language ('고구마'), so require two
        # characters before either string is allowed to contain the other.
        for stem in stems:
            if len(stem) < 2:
                continue
            hits = [p for p in plots if any(
                stem in f or (len(f) >= 2 and f in stem) for f in _fields(p))]
            if hits:
                return _one_zone(hits)

        return None

    @staticmethod
    def _scope_for_target(target_name):
        """이름 하나를 **그 안에서 일어나는 일 전부**의 target_id 집합으로.

        "3포장의 예정을 요약해" 는 3포장 안에서 일어나는 일을 묻는 것이지 3포장
        도형에 붙은 것만 묻는 것이 아니다. 예전에는 `target_id ==` 정확 일치라
        실측(2026-08-18 김제)에서 `search_schedule('3포장')` 이 0건을 냈다 —
        실제로는 구역에 1건, 그 안 식생에 2건이 있었다.

        `scope` 를 함께 돌려주는 것이 요점이다. 결과가 0건일 때 **"정말 없다"
        와 "못 찾았다" 를 구분할 근거**가 그것뿐이기 때문이다. 이름이 아예
        해석되지 않으면 `scope['resolved']` 가 False 이고, 그때 0건은
        "없음" 이 아니라 "묻는 대상을 못 찾음" 이다.

        Returns (ids: list[str], scope: dict).
        """
        scope = {'requested': target_name, 'resolved': False,
                 'resolved_name': None, 'target_type': None,
                 'expanded': None, 'searched_ids': 0}
        if not target_name or not str(target_name).strip():
            return [], scope

        # 이름이 여러 정체성에 걸릴 수 있다(장치 = Input/Output + 마커 + 폴리곤).
        # 그 합집합은 `_resolve_note_target_ids` 가 계산하고, **그 안에서 이미**
        # `_resolve_note_target` 을 부른다 — 여기서 또 부르면 같은 해석을 두 번
        # 한다(실측 22.6ms 중복).
        try:
            ids, rname = AoTDataToolService._resolve_note_target_ids(target_name)
        except Exception:
            ids, rname = [], None
        if not ids:
            return [], scope

        tid = ids[0]
        try:
            _t, ttype, _r, _la, _ln = \
                AoTDataToolService._resolve_note_target(target_name)
        except Exception:
            ttype = None
        scope.update({'resolved': True, 'resolved_name': rname,
                      'target_type': ttype})
        ids = list(ids)

        # 도형이면 그 아래 전부로 넓힌다(구역·시설·장치·식생).
        try:
            shape = GeoShape.query.filter_by(unique_id=tid).first()
        except Exception:
            shape = None
        if shape is not None:
            from aot.utils.geo_hierarchy import descendant_target_ids
            try:
                more, breakdown = descendant_target_ids(shape)
                ids.extend(more)
                scope['expanded'] = breakdown
            except Exception as _e:
                logger.debug(f"_scope_for_target: 자손 확장 실패: {_e}")

        seen, uniq = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                uniq.append(i)
        scope['searched_ids'] = len(uniq)
        return uniq, scope

    @staticmethod
    def _geo_shape_descendants(root_shape):
        """Return every GeoShape nested under root_shape (e.g. a site's child
        zones and the device markers inside them), as GeoShape rows. See
        aot/utils/geo_hierarchy.py for why this is needed (GeoShape.parent_id
        is unset in production; the real parent signal is spatial
        containment).
        """
        # **경량 레코드**를 돌려준다(ShapeRec: id·unique_id·type·parent_id·
        # device_id·geo_id·name). 자손에서 읽는 것이 그뿐이라 ORM 전체 조회
        # (16.8ms/150행)가 통째로 빠진다 — `_resolve_note_target_ids` 의
        # site 확장 경로 22.6ms 가 거의 전부 그 조회였다.
        #
        # **기하는 없다.** 자손의 폴리곤이 필요하면 `geo_descendant_shapes`
        # 를 직접 쓸 것.
        from aot.utils.geo_hierarchy import geo_descendant_recs
        return geo_descendant_recs(root_shape)

    @staticmethod
    def resolve_target_tool(target_name):
        """
        [Read-only, no approval required] Resolve a place/device name to its
        exact entity BEFORE calling a write tool that takes target_name (e.g.
        add_schedule, create_note, create_notice). Uses the same resolver
        those write tools use internally, so the result is guaranteed
        consistent with what a write call would attach to.

        Write tools sit behind a human-approval gate that only inspects the
        tool NAME, not its arguments — the target-name resolution itself only
        runs after approval is granted, which is too late to catch a wrong
        hierarchy level (e.g. a site name given when the request actually
        means each of its zones). Calling this tool first, before any write,
        surfaces that information while it still costs nothing to correct.

        Returns target_type and, if the entity contains finer-grained
        children (e.g. a site containing zones), their exact names in
        `children`. A write tool call attaches to ONLY the resolved entity —
        it never expands to `children` automatically. When the request
        implies handling each child separately, call the write tool once per
        entry in `children`, using that child's exact name.
        """
        import json as _json
        if not target_name or not str(target_name).strip():
            return {"status": "error", "message": "target_name is empty"}

        target_id, target_type, resolved_name, _lat, _lng = \
            AoTDataToolService._resolve_note_target(target_name)

        if not target_id:
            # A subject name found in two zones resolves to nothing above (a
            # coin-flip zone would be written to). Listing the subjects with their
            # zones turns that dead end into a question the user can answer.
            subject_targets = []
            try:
                seen = set()
                for p in AoTDataToolService._active_subject_plots():
                    key = (p['subject'], p['zone_name'])
                    if p['subject'] and key not in seen:
                        seen.add(key)
                        subject_targets.append({"subject": p['subject'], "zone": p['zone_name']})
            except Exception:
                subject_targets = []
            return {
                "status": "needs_disambiguation",
                "error": "target_not_found",
                "message": (
                    f"'{target_name}' could not be resolved to a known entity. "
                    "A crop name ('콩밭', '상추 재배지') also resolves, to the zone "
                    "it is in — see 'subject_targets'; when one subject appears "
                    "in several zones, ask which one and pass that zone name."
                ),
                "available_targets": AoTDataToolService._geoshape_name_candidates(),
                "subject_targets": subject_targets[:20],
            }

        children = []
        # 구역도 컨테이너다 — 그 안에 식생 구획이 들어 있고, 그 구획이 자기
        # 노트·일정을 갖는다. site 만 펼치던 때는 "3-1 에 무엇이 있나" 에
        # 답할 수 없었고, 작업을 구획별로 나눠 걸어야 할 때 AI 가 그 존재를
        # 몰랐다.
        if target_type in ('site', 'zone'):
            try:
                _root = GeoShape.query.filter_by(unique_id=target_id).first()
                if _root is not None:
                    from aot.utils.geo_hierarchy import _plot_ids_inside
                    from aot.databases.models import GeoPlot
                    _ids = [_root.unique_id] + [
                        c.unique_id for c in
                        AoTDataToolService._geo_shape_descendants(_root)
                        if c.unique_id]
                    for _pid in _plot_ids_inside(
                            _ids, geo_ids={_root.geo_id} if _root.geo_id else None):
                        _pl = GeoPlot.query.filter_by(unique_id=_pid).first()
                        if _pl is None:
                            continue
                        _pn = _pl.name or _pl.subject
                        if _pn:
                            children.append({"name": _pn, "type": "plot"})
            except Exception:
                pass
        if target_type == 'site':
            try:
                site_shape = GeoShape.query.filter_by(unique_id=target_id).first()
                if site_shape:
                    seen_names = set()
                    for c in AoTDataToolService._geo_shape_descendants(site_shape):
                        # geo_descendant_shapes() returns the FULL nested subtree
                        # (zones, device markers, labels, ...) - only the immediate
                        # 'zone' level answers "does this container have sub-zones
                        # to loop over"; devices/labels would just be noise here.
                        if c.type != 'zone':
                            continue
                        c_name = c.name or None
                        if c_name and c_name not in seen_names:
                            seen_names.add(c_name)
                            children.append({"name": c_name, "type": c.type})
            except Exception:
                pass

        note = (
            "This name resolves to exactly one entity. A write tool called with "
            "this target_name attaches ONLY to it."
        ) if not children else (
            "This name resolves to a container whose sub-entities are listed in "
            "'children'. A write tool called with this target_name attaches ONLY "
            "to the container itself - it does NOT automatically apply to each "
            "child. If the request applies to each child separately (e.g. 'each "
            "zone', 'per section'), call the write tool once per entry in "
            "'children', using that child's exact name as target_name."
        )

        return {
            "status": "success",
            "target_id": target_id,
            "target_type": target_type,
            "resolved_name": resolved_name,
            "children": children,
            "note": note,
        }

    @staticmethod
    def _resolve_note_target_ids(target_name):
        """Resolve a name to ALL candidate note target_ids, not just one.

        A single physical device carries MULTIPLE identities that a note may be
        bound to, and they do NOT share a unique_id:
          - the Input/Output row's unique_id (the device panel '노트 작성하기'
            writes the note here, e.g. Output 'v111' → 3acafd0c…),
          - one or more map GeoShapes (a marker + a polygon) whose OWN unique_id
            differs, but whose device_id points back to that Input/Output.
        _resolve_note_target() returns only the single most-specific match (a
        shape), so a note written on the Output is missed. Gathering the union of
        {shape.unique_id, shape.device_id, device.unique_id} for the name finds
        the note wherever it was attached.

        Returns (candidate_ids: list[str], resolved_name: str|None).
        """
        import json as _json
        ids, resolved_name = [], None
        if not target_name or not str(target_name).strip():
            return ids, None
        _q = str(target_name).strip()
        _ql = _q.lower()

        # Primary (hierarchical/zone-aware) resolution first — keeps '1포장 1-1'
        # scoping and substring behaviour intact.
        tid, _tt, rname, _la, _ln = AoTDataToolService._resolve_note_target(target_name)
        if tid:
            ids.append(tid)
            resolved_name = rname

        # A 'site' (포장) is a container: its own notes are rare, but each child
        # zone (구역) carries its own notes (e.g. crop info per zone). A query
        # asked about the site must also surface every descendant zone's notes,
        # not just the site shape's own target_id — otherwise "1포장에서 생산하는
        # 작물" answers "no info" even though "1-1", "1-2" ... each have one.
        if tid and _tt == 'site':
            try:
                site_shape = GeoShape.query.filter_by(unique_id=tid).first()
            except Exception:
                site_shape = None
            if site_shape:
                # 여기서는 ORM 행이 필요하다(기하 파싱 → 자손 판정). 공용
                # 인덱스는 이름 해석용 경량 레코드라 기하를 들지 않는다.
                # A descendant 'device' marker's OWN unique_id is not what a
                # note attaches to — the device panel writes the note against
                # the underlying Input/Output's unique_id (shape.device_id),
                # a distinct identity (same dual-identity issue documented on
                # this method's docstring, above). Missing this union meant a
                # site query silently dropped every note attached to a device
                # placed under it (e.g. valve notes under '1포장').
                for _desc in AoTDataToolService._geo_shape_descendants(site_shape):
                    if _desc.unique_id:
                        ids.append(_desc.unique_id)
                    if _desc.device_id:
                        ids.append(str(_desc.device_id).split('::')[0])

        # GeoShapes whose display name matches EXACTLY → add the shape's own id
        # and the device it represents. 같은 공용 인덱스를 쓴다(위 주석 참조).
        try:
            from aot.aot_flask.geo import shape_index
            for shape, _name, _nl in shape_index.named_shapes():
                if _nl == _ql:
                    if shape.unique_id:
                        ids.append(shape.unique_id)
                    if shape.device_id:
                        ids.append(str(shape.device_id).split('::')[0])
                    resolved_name = resolved_name or _name
        except Exception:
            pass

        # Input/Output/Function rows matching the name → add their unique_id.
        try:
            from aot.databases.models import Function as _Function
        except Exception:
            _Function = None
        for model in (m for m in (Input, Output, _Function) if m is not None):
            try:
                for d in model.query.filter(model.name.ilike(_q)).all():
                    if d.unique_id:
                        ids.append(d.unique_id)
                    resolved_name = resolved_name or d.name
            except Exception:
                continue

        # De-duplicate, preserve order.
        seen, out = set(), []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out, resolved_name

    @staticmethod
    def create_note(name=None, note=None, tags=None, category='general',
                    target_id=None, target_type=None, target_name=None,
                    gps_lat=None, gps_lng=None, priority=None, **extra):
        """Create a plain memo/note. For a dated work task (weeding, inspection)
        use add_schedule instead — that registers a SchedulerJobMeta job, not a
        Notes row.

        Notes in AoT are NOT shown via a widget — every device, land/facility, and
        zone/shape HAS its own notes, viewed PER-ENTITY. A note is visible on an
        entity only when target_id == that entity's unique_id. So when the user
        asks to note something "at 1포장 1-1" / "on 밸브1", pass target_name (the
        location/entity name) — this handler resolves it to the real unique_id and
        target_type. Alternatively pass target_id directly if already known."""
        from aot.databases.models import Notes
        if not name and not note:
            return {"error": "name or note is required"}

        def _to_float(v):
            try:
                return float(v) if v is not None and v != '' else None
            except (TypeError, ValueError):
                return None

        def _to_int(v):
            try:
                return int(v) if v is not None and v != '' else None
            except (TypeError, ValueError):
                return None

        # LLM aliases for the location name.
        if not target_name:
            target_name = extra.pop('location', None) or extra.pop('zone_name', None) \
                or extra.pop('entity_name', None) or extra.pop('place', None)

        gps_lat = _to_float(gps_lat)
        gps_lng = _to_float(gps_lng)
        resolved_name = None

        # Resolve a location NAME → target_id (+ target_type, gps) so the note
        # attaches to the entity and is actually visible.
        if not target_id and target_name:
            _tid, _tt, resolved_name, _lat, _lng = AoTDataToolService._resolve_note_target(target_name)
            if not _tid:
                # Fail LOUD with candidates rather than silently create an
                # invisible floating note (the exact bug the user hit).
                candidates = []
                import json as _json
                for s in GeoShape.query.limit(40).all():
                    try:
                        f = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                        nm = (f.get('properties') or {}).get('name')
                        if nm:
                            candidates.append(nm)
                    except Exception:
                        continue
                return {
                    "error": "target_not_found",
                    "message": (
                        f"Location/device '{target_name}' was not found, so there is "
                        f"nothing to attach the note to. Retry with an exact name from "
                        f"available_targets."
                    ),
                    "available_targets": candidates[:20],
                }
            target_id = _tid
            if not target_type:
                target_type = _tt
            if gps_lat is None:
                gps_lat = _to_float(_lat)
            if gps_lng is None:
                gps_lng = _to_float(_lng)

        # 대상 자신의 태그는 서버가 보장한다 — AI 가 태그를 안 주는 것이 보통이라
        # (실측: 구획 노트 넷이 태그 없이 남았다) 여기서 붙이지 않으면 그 노트는
        # 노트 페이지에서 '태그 없음' 으로 남는다.
        from aot.aot_flask.utils import utils_notes as _un
        _tags = _un.ensure_target_tag(tags or '', target_id)

        n = Notes(
            name=name or (note[:50] if note else 'Note'),
            note=note or '', tags=_tags, category=category or 'general',
            target_id=target_id or None,
            target_type=target_type or None,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
        )
        _prio = _to_int(priority)
        if _prio is not None:
            n.priority = _prio
        # AI-authored, human-requested note.
        n.context_state = 'user_requested'
        try:
            db.session.add(n)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"note_id": n.unique_id, "name": n.name, "status": "created"}
        if target_id:
            r["target_id"] = target_id
            r["target_type"] = target_type
            r["attached_to"] = resolved_name or target_id
        else:
            # Surfaced so the AI can tell the user it's a general (unattached) memo,
            # not claim it's "on 1포장 1-1" when it isn't.
            r["attached"] = False
            r["note_hint"] = ("Saved as a general memo with no location; it will not "
                              "appear on any specific device or zone.")
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    # --- Knowledge search tool (@ANCHOR: KNOWLEDGE_SEARCH_TOOL, Phase 2 2026-07-19) -
    # Thin wrapper so the agent-loop tool catalog can call the read half of the AI
    # library (docs/design/ai-library-redesign.md §4) like any other tool. The
    # underlying search (knowledge_search.search_as_text) already existed and was
    # reachable via the legacy action_type='knowledge_search' branch in
    # execute_action, invoked only through a prompt-text instruction (base_ai.py) —
    # never a real tool_name the agent loop's catalog could offer.
    @staticmethod
    def _known_knowledge_tags():
        """라이브러리에서 실제로 쓰이는 태그. 없는 태그를 필터로 쓰지 않기 위해
        필요하고, 모델에게 무엇이 있는지 알려 줄 때도 쓴다."""
        try:
            from aot.databases.models import AIKnowledgeChunk
            out = set()
            for (tags,) in AIKnowledgeChunk.query.with_entities(
                    AIKnowledgeChunk.tags).filter_by(is_enabled=True).all():
                for t in (tags or '').split(','):
                    t = t.strip().lower()
                    if t:
                        out.add(t)
            return out
        except Exception:
            return set()

    @staticmethod
    def _registered_lookup_briefs():
        """등록된 조회 소스를 **바로 부를 수 있는 형태**로. 표 파일은 읽지 않는다
        — 이 함수는 검색 응답마다 불리므로 DB 한 번으로 끝나야 한다.

        @ANCHOR: LOOKUP_BRIEF
        예전에는 제목만 돌려줬다. 그러면 모델이 조회하기 전에 반드시
        list_lookup_sources 를 한 번 더 불러 id 를 얻어야 했고, 그 한 번이
        판단 지점 하나·단계 하나였다. 실측(2026-08-25)에서 조사 요청이 바로
        거기서 두 번 갈렸다 — 목록까지 열고 조회로 안 넘어가거나, 목록조차
        안 열거나.

        **루프에서 한 단계를 강제하지 않는 이유**(사용자 지적): 조회 소스가
        있다는 이유만으로 단계를 더 돌리면, 조사와 무관한 요청까지 표 쪽으로
        끌려가 엉뚱한 답을 만든다. 그래서 강제하는 대신 **결정을 하나 없앤다**
        — 부를 때 필요한 것을 미리 실어 주면 중간 단계 자체가 사라지고, 다른
        요청의 동작은 아무것도 바뀌지 않는다.
        """
        try:
            from aot.databases.models import AIContextSource
            import json as _json
            out = []
            for src in AIContextSource.query.filter_by(
                    is_active=True, is_enabled=True, source_type='csv_table').all():
                try:
                    cfg = _json.loads(src.config_json or '{}')
                except (ValueError, TypeError):
                    cfg = {}
                out.append({
                    'title': (cfg.get('title') or src.source_name or '').strip(),
                    'call': "query_reference_table(table_id='%s', query=…)" % src.source_id,
                    'answers': (cfg.get('answers') or '').strip(),
                    'name_language': (cfg.get('name_language') or '').strip(),
                })
            try:
                from aot.ai.services import data_source_query_service as dsq
                for a in dsq.describe_all():
                    if not a.get('label'):
                        continue
                    out.append({
                        'title': a['label'],
                        'call': "query_data_source(source_id='%s', operation=…)" % a.get('source_id'),
                        'answers': (a.get('answers') or '').strip(),
                        'name_language': '',
                    })
            except Exception:
                pass
            return [b for b in out if b['title']]
        except Exception:
            return []

    @staticmethod
    def _registered_table_titles():
        """제목만 필요한 오래된 호출부를 위한 얇은 껍데기."""
        return [b['title'] for b in AoTDataToolService._registered_lookup_briefs()]

    @staticmethod
    def knowledge_search_tool(query=None, top_k=3, tags=None, **extra):
        """Free-text search across manuals + synced domain knowledge + AI-curated
        notes. Read-only — the write counterpart is knowledge_shelve."""
        from aot.ai.services import knowledge_search as _ks
        if not query or not str(query).strip():
            return {"error": "query is required"}
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 3
        _tags = [t.strip() for t in str(tags).split(',') if t.strip()] if tags else None

        # @ANCHOR: KNOWLEDGE_SEARCH_UNKNOWN_TAG
        # 없는 태그로 거르면 **전부가 걸러진다.** 태그는 운영자·AI 가 자유롭게
        # 붙이는 값이라 정해진 어휘가 없는데, 모델은 그것을 모르고 그럴듯한 말을
        # 지어 넣는다.
        #
        # 실측(2026-08-25): "가을 무는 어떻게 키워야 되지?" 에 모델이
        # tags='crop' 을 붙여 불렀다. 이 라이브러리의 실제 태그는
        # '무,가을무,김장무,재배' 라 하나도 안 걸렸고, 답을 담은 바로 그 항목이
        # 필터에 잘려 나갔다. 서버가 이미 접지로 같은 내용을 넣어 줬는데도
        # 모델은 자기 빈 검색 결과를 믿고 "정보가 없습니다" 로 끝냈다.
        #
        # 그래서 **하나도 안 맞는 태그는 필터로 쓰지 않는다.** 거르는 대신 무엇이
        # 있는지 알려 준다 — 조용히 빈손을 주는 것보다 스스로 고칠 수 있게 하는
        # 편이 낫다.
        _tag_note = ''
        if _tags:
            known = AoTDataToolService._known_knowledge_tags()
            if known and not (set(t.lower() for t in _tags) & known):
                _tag_note = ("\n\n[NOTE] The tag(s) %s are not used by any item here, so "
                             "they were IGNORED (filtering on them would have hidden "
                             "everything). Tags are free-form, not a fixed vocabulary. "
                             "Tags actually in use: %s."
                             % (', '.join(repr(t) for t in _tags),
                                ', '.join(sorted(known)[:15])))
                _tags = None
        text = _ks.search_as_text(query, top_k=top_k, tags=_tags)

        # 도메인 라이브러리가 비었다는 사실을 응답이 직접 말한다. 예전에는 빈
        # 결과에 "Try different keywords" 만 돌려줬는데, 자료가 하나도 없는
        # 설치에서 그 말은 **검색어가 틀렸다는 뜻으로 읽힌다.** 모델은 키워드만
        # 바꿔 가며 같은 빈손을 반복하고, 끝내 라이브러리가 비었다는 사실을 모른
        # 채 자기 지식으로 넘어간다 — 그리고 그것을 출처처럼 적는다.
        #
        # ⚠ **빈 결과만 보고 판정하면 안 된다.** 검색은 저장소에 늘 있는 AoT
        # 매뉴얼도 함께 뒤지므로, "상추 생육단계" 같은 질문에도 매뉴얼의 엉뚱한
        # 섹션(실측: Security.ko.md)이 느슨하게 걸려 결과가 비지 않는다. 그래서
        # 결과가 **있을 때도** 그것이 매뉴얼뿐이면 그 사실을 함께 말한다.
        # 매니페스트가 아니라 응답이라 고정비가 0이다.
        populated = _ks.library_is_populated()

        # 참조표는 **검색 대상이 아니다** — 등록만 해 두고 물어볼 때 조회한다
        # (reference_table_service 모듈 주석). 그래서 이 검색이 빈손이어도
        # 답이 표 안에 있을 수 있는데, 모델은 표의 존재를 모른 채 "정보가
        # 없습니다" 로 끝낸다(실측 2026-08-24: 오크라 생육 온도 질문에서 그랬다).
        # 여기서 한 줄 가리켜 주는 것이 그 간극을 메우는 가장 싼 방법이다 —
        # 매니페스트가 아니라 응답이라 표가 없는 설치에서는 고정비가 0이다.
        _briefs = AoTDataToolService._registered_lookup_briefs()
        _pointer = ''
        if _briefs:
            # **조건절을 붙이지 않는다.** 예전 문구는 "per-item value 나 실시간
            # 외부 데이터를 묻는 경우" 로 조건을 달았는데, "땅콩 재배 방법을
            # 조사해줘" 는 그 조건에 안 걸린다고 읽혔다 — 재현 2026-08-25 에서
            # 모델이 이 안내를 받고도 조회 없이 "자료를 제공해주시면" 으로
            # 끝냈다. 무엇을 하지 말라(모른다고 답하기·사용자에게 되묻기)를
            # 먼저 말하고, 그 전에 무엇을 하라를 명령형으로 붙인다.
            # 부르는 법을 **여기서 바로** 준다. 제목만 주면 모델이 id 를 얻으려
            # list_lookup_sources 를 한 번 더 불러야 하고, 그 한 번이 판단
            # 지점이자 단계 하나다(LOOKUP_BRIEF 주석 참조).
            _lines = []
            for b in _briefs[:3]:
                _line = "  - %s → %s" % (b['title'], b['call'])
                if b['answers']:
                    _line += "\n      answers: %s" % b['answers'][:150]
                if b['name_language']:
                    _line += ("\n      rows are named in: %s — translate the user's word "
                              "yourself if needed." % b['name_language'][:80])
                _lines.append(_line)
            _more = ("\n  (…%d more — list_lookup_sources for the rest)"
                     % (len(_briefs) - 3)) if len(_briefs) > 3 else ""
            _pointer = ("\n\n[NOTE] This search does NOT cover the %d registered lookup "
                        "source(s). They are queried on demand and can hold exactly what "
                        "was just missing. Call one DIRECTLY — you do not need "
                        "list_lookup_sources first:\n%s%s\nDo NOT say the information is "
                        "unavailable, and do NOT ask the user to supply it, until you "
                        "have queried every source whose 'answers' fits the question."
                        % (len(_briefs), "\n".join(_lines), _more))
        # 두 안내는 서로 다른 것을 말한다 — 하나가 다른 하나를 덮으면 안 된다.
        _pointer = _tag_note + _pointer

        if not text:
            if not populated:
                return {"result": ("The knowledge library is EMPTY — no domain source "
                                   "has been synced, so this returns nothing about "
                                   f"'{query}' no matter how it is worded. Do not "
                                   "retry with other keywords. Either answer from your "
                                   "own general knowledge AND say plainly that it is "
                                   "unverified — never pass it off as a citation in a "
                                   "source_note — or tell the user a source can be "
                                   "added (list_library_source_types shows what is "
                                   "available)." + _pointer),
                        "library_empty": True}
            return {"result": f"No documentation section matched '{query}'. "
                              f"Try different keywords." + _pointer}

        if not populated:
            return {"result": (text + "\n\n---\n[NOTE] The domain knowledge library is "
                               "EMPTY — everything above is the AoT system manual "
                               "(how to operate AoT), not reference material about "
                               "crops, livestock or facilities. If you were asking "
                               "about a subject rather than about AoT, treat this as "
                               "NO SOURCE FOUND: say your answer is your own "
                               "unverified knowledge, and do not cite it as a "
                               "source." + _pointer),
                    "library_empty": True}
        return {"result": text + _pointer}

    # --- Knowledge shelve (@ANCHOR: KNOWLEDGE_SHELVE_TOOL, P4 2026-07-19) --------
    # The write half of the AI library redesign (docs/design/ai-library-redesign.md
    # §4): the AI's own read_manual/knowledge_search calls surface curated
    # knowledge, but nothing let the AI SAVE something it just worked out (an
    # observation from data, a synthesized answer) for next time. NOT
    # approval-gated (same reasoning as create_note): always writes at the
    # lowest trust tier (provenance='ai_curated', unconfirmed) — a low-risk,
    # reversible write, never presented with authority until a human confirms
    # it or it corroborates against a real source (P5, not yet built).
    # @ANCHOR: SHELVE_LOCAL_NAME_GUARD
    # 검색 가능한 이름이 없으면 저장은 성공하고 **나중에 못 찾는다** — 조용한
    # 실패라 아무도 모른다. 사용자 보고(2026-08-25): 땅콩을 조사시켰더니 학명
    # 기준으로 태그가 달려 "나중에 다시 찾지 못할 것 같다".
    #
    # 왜 지시만으로 부족한가: knowledge_search 는 제목(3배)과 본문만 점수화하고
    # 태그는 필터일 뿐이다. 영문 자료(ECOCROP 등)를 조사하면 모델이 그 자료의
    # 어휘로 제목을 다는 것이 자연스럽고, 그러면 사용자의 말로는 0점이 된다.
    #
    # 서버가 아는 결정적 신호는 설치 언어뿐이다. 그 언어가 라틴 문자를 쓰지
    # 않는데 제목에도 태그에도 그 문자가 하나도 없으면, 그 항목은 사용자가
    # 자기 말로 검색해서는 절대 나오지 않는다. 그때만 막는다 — 제목이든
    # 태그든 한 글자라도 있으면 통과시키는 낮은 문턱이라, 영문 고유명사를
    # 다루는 정당한 메모를 막지 않는다.
    _LOCAL_SCRIPTS = {
        'ko': ((0xAC00, 0xD7A3), (0x1100, 0x11FF)),          # 한글
        'ja': ((0x3040, 0x30FF), (0x4E00, 0x9FFF)),          # 가나·한자
        'zh': ((0x4E00, 0x9FFF),),                           # 한자
        'zh_Hant': ((0x4E00, 0x9FFF),),
        'th': ((0x0E00, 0x0E7F),),                           # 타이
        'ru': ((0x0400, 0x04FF),), 'uk': ((0x0400, 0x04FF),),
        'sr': ((0x0400, 0x04FF),), 'bg': ((0x0400, 0x04FF),),
        'el': ((0x0370, 0x03FF),),                           # 그리스
        'he': ((0x0590, 0x05FF),),                           # 히브리
        'ar': ((0x0600, 0x06FF),),                           # 아랍
        'hi': ((0x0900, 0x097F),),                           # 데바나가리
    }

    @staticmethod
    def _missing_local_name(heading, content):
        """설치 언어의 문자가 제목·태그 어디에도 없으면 그 언어 코드를 돌려준다.

        판정할 수 없으면(라틴 문자권, 요청 문맥 밖, 조회 실패) None — 막지
        않는다. 이 검사의 목적은 확실한 실패를 잡는 것이지 의심스러운 것을
        훈계하는 게 아니다.
        """
        try:
            from flask_babel import get_locale
            loc = get_locale()
            if loc is None:
                return None
            code = str(loc)
        except Exception:
            return None

        ranges = (AoTDataToolService._LOCAL_SCRIPTS.get(code)
                  or AoTDataToolService._LOCAL_SCRIPTS.get(code.split('_')[0]))
        if not ranges:
            return None

        # **태그는 보지 않는다.** knowledge_search 는 제목(3배)과 본문만
        # 점수화하고 태그는 필터일 뿐이라, 태그에만 있는 이름으로는 이 항목이
        # 검색에 걸리지 않는다 — 그것을 통과시키면 검사가 목적을 잃는다.
        text = '%s %s' % (heading or '', content or '')
        for ch in text:
            o = ord(ch)
            if any(lo <= o <= hi for lo, hi in ranges):
                return None
        return code

    @staticmethod
    def _missing_source_name(heading, content, source_ref):
        """등록된 **표**에서 옮긴 항목인데 그 표가 쓰는 이름이 제목·태그에
        없으면 표 제목을 돌려준다(없으면 None).

        왜 필요한가. 현지 이름만 달면 반대쪽이 막힌다 — 실측(2026-08-25):
        땅콩 항목이 '땅콩 재배 기준' / 'crop,땅콩' 으로 저장돼 한국어 조회는
        전부 걸렸지만 'peanut' 은 0건이었다. 그 표를 다시 조회하거나, 학명으로
        찾거나, 다른 언어 사용자가 같은 항목에 닿을 길이 없다.

        **표에서 옮긴 것에만 적용한다.** 현장 관찰 메모("3동 관수 밸브가 새는
        중")에는 대응하는 외국어 이름이 애초에 없고, 그런 것까지 영문을
        요구하면 지어내게 된다. API 소스(kind='api')도 제외한다 — 그쪽은
        측정값이라 '이름으로 찾는' 자료가 아니고, 한국 기관 자료에 영문
        이름을 강요할 이유도 없다.
        """
        if not source_ref:
            return None
        try:
            import json as _json
            import re as _re

            from aot.databases.models import AIContextSource

            src = AIContextSource.query.filter_by(
                source_id=str(source_ref), source_type='csv_table').first()
            if src is None:
                return None
            # 학명이든 통용명이든 상관하지 않는다 — 어느 쪽이든 그 표로 되짚어
            # 갈 수 있다. 다만 **태그는 세지 않는다**(위 _missing_local_name 의
            # 같은 이유). 실측에서 태그가 'crop,땅콩' 이었는데, 태그를 세면
            # 범용 분류어 'crop' 이 라틴 낱말이라 그대로 통과했다 — 정작 잡아야
            # 할 바로 그 사례가 빠져나갔다.
            text = '%s %s' % (heading or '', content or '')
            if _re.search(r'[A-Za-z]{3,}', text):
                return None
            try:
                cfg = _json.loads(src.config_json or '{}')
            except (ValueError, TypeError):
                cfg = {}
            return (cfg.get('title') or src.source_name or 'the source table').strip()
        except Exception:
            logger.debug("source-name check skipped", exc_info=True)
            return None

    @staticmethod
    def knowledge_shelve(content=None, tags=None, heading=None, entity_ref=None,
                         attribution=None, content_kind='prose', ttl_hours=None,
                         source_url=None, source_ref=None, **extra):
        """Save a piece of knowledge the AI just derived or was told, so a
        later query can retrieve it. Always shelved as ai_curated/unconfirmed
        — see knowledge_shelve_service.shelve_knowledge for the governance
        (dedup/quota/contradiction-flag) this delegates to."""
        from aot.ai.services.knowledge_shelve_service import shelve_knowledge

        if not content or not str(content).strip():
            return {"error": "content is required"}
        if not tags:
            return {
                "error": "tags is required",
                "message": "Provide at least one scope tag (crop/livestock/structure/"
                           "topic this knowledge is about) — an untagged note would "
                           "surface for every unrelated query.",
            }

        _table = AoTDataToolService._missing_source_name(heading, content, source_ref)
        if _table:
            return {
                "error": "findable in only one language",
                "message": ("This came from %r, whose rows are named in that source's own "
                            "vocabulary — but neither the heading nor the body carries that "
                            "name (tags are not scored by search, so they do not count). "
                            "Someone searching the scientific or English name, or tracing "
                            "this back to the table, will not find it. Keep BOTH names, "
                            "e.g. heading '땅콩(Arachis hypogaea) 재배 기준'. Then call this "
                            "again." % _table),
            }

        _lang = AoTDataToolService._missing_local_name(heading, content)
        if _lang:
            return {
                "error": "not findable later",
                "message": ("This install's language is %r, but neither the heading nor "
                            "the body contains a single character of that language — a "
                            "person searching in their own words will never get this back "
                            "(search scores the heading 3x and the body 1x; TAGS ARE NOT "
                            "SCORED, so a tag does not make it findable). Put the "
                            "subject's name AS THE USER SAYS IT in the heading, and keep "
                            "the source's own name alongside it. Then call this again."
                            % _lang),
            }

        if not attribution:
            attribution = f"AI 대화 비치 ({datetime.utcnow().date()})"

        ttl = None
        try:
            if ttl_hours is not None and float(ttl_hours) > 0:
                ttl = datetime.utcnow() + timedelta(hours=float(ttl_hours))
        except (TypeError, ValueError):
            ttl = None

        result = shelve_knowledge(
            content=str(content), tags=tags, heading=heading,
            entity_ref=entity_ref, attribution=attribution,
            content_kind=content_kind, ttl=ttl, source_url=source_url,
            source_ref=source_ref,
        )
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    # ─────────────────────────────────────────────────────────────────────
    # 참조표 조회 (@ANCHOR: REFERENCE_TABLE_TOOLS, 2026-08-24)
    #
    # 표를 지식으로 적재하지 않고 등록만 해 두고 물어볼 때 조회한다 —
    # 이유는 reference_table_service 모듈 주석에 있다. 도구가 둘인 이유:
    # 등록된 표는 설치마다 다르므로 **정적인 도구 설명에 담을 수 없다.**
    # 무엇이 있는지 먼저 보고(list), 맞으면 조회한다(query).
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def list_lookup_sources(**extra):
        """이 시스템이 **찾아볼 수 있는 것** 전부 — 참조표와 연결된 데이터 API.

        발견 지점을 하나로 둔다. 둘로 나누면 모델이 한쪽만 보고 "없다" 고
        단정한다(실측 2026-08-25: 표가 있는데 knowledge_search 만 보고 끝냈다).
        종류는 kind 로 구분한다 — 조회 방법이 다르기 때문이다."""
        from aot.databases.models import AIContextSource
        from aot.ai.services import reference_table_service as rts
        import json as _json

        out = []
        rows = AIContextSource.query.filter_by(
            is_active=True, is_enabled=True, source_type='csv_table').all()
        for src in rows:
            try:
                cfg = _json.loads(src.config_json or '{}')
            except (ValueError, TypeError):
                cfg = {}
            out.append(rts.describe(src, cfg))
        for t in out:
            t['kind'] = 'table'

        from aot.ai.services import data_source_query_service as dsq
        apis = []
        try:
            for a in dsq.describe_all():
                a['kind'] = 'api'
                apis.append(a)
        except Exception as exc:
            logger.debug("[LookupSources] api listing skipped: %s", exc)

        if not out and not apis:
            return {
                "sources": [],
                "note": "Nothing is registered to look things up in. Do NOT invent values "
                        "— say the operator can add a source on the AI Library page.",
            }
        # @ANCHOR: LOOKUP_SOURCES_NEXT_STEP
        # 이 안내가 서술형이던 동안 실제로 이런 일이 났다(재현 2026-08-25,
        # "땅콩 재배 방법을 조사해서 라이브러리에 정리해줘"): 모델이
        # knowledge_search 로 0건을 받고 → 이 목록을 열어 FAO ECOCROP 을 **보고도**
        # → 조회하지 않고 "자료를 제공해주시면 정리해 드리겠습니다" 로 끝냈다.
        #
        # 목록만 주면 모델은 이것을 자료 사전으로 읽는다. 그래서 **다음 행동**을
        # 명령형으로 못박고, 별칭이 화이트리스트가 아니라는 것을 여기서 말한다 —
        # 별칭 24개에 '땅콩' 이 없다는 사실이 "이 표로는 못 찾는다" 는 정지
        # 신호로 작동했다.
        return {
            "sources": out + apis,
            "note": "This IS the answer to 'how do I research that here' — you are NOT "
                    "done until you have queried the source whose 'answers' text fits. "
                    "kind='table' -> query_reference_table(table_id, query). "
                    "kind='api' -> query_data_source(source_id, operation, params). "
                    "'aliases' are EXAMPLES, not a whitelist: if the user's word is not "
                    "listed, translate it into the table's 'name_language' yourself and "
                    "query anyway — an absent alias is not evidence the row is absent. "
                    "NEVER ask the user to supply material one of these sources can "
                    "answer. Honour any 'caveat' when you cite the numbers.",
        }

    @staticmethod
    def query_data_source(source_id=None, operation=None, params=None,
                          limit=5, columns=None, **extra):
        """등록된 데이터 API 를 지금 조회한다 — 고정 동기화가 아니라 질문할 때."""
        from aot.ai.services import data_source_query_service as dsq
        if not operation:
            return {"error": "operation is required — call list_lookup_sources to see "
                             "which operations this source has."}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (ValueError, TypeError):
                return {"error": "params must be an object, e.g. {\"userId\": \"PF_0000001\"}"}
        payload, err = dsq.query(source_id, operation, params=params,
                                 limit=limit, columns=columns)
        if err:
            return {"error": err}
        return payload

    @staticmethod
    def query_reference_table(table_id=None, query=None, limit=5, columns=None, **extra):
        """참조표에서 이름으로 행을 찾는다."""
        from aot.databases.models import AIContextSource
        from aot.ai.services import reference_table_service as rts
        import json as _json

        if not query or not str(query).strip():
            return {"error": "query is required"}
        q = AIContextSource.query.filter_by(
            is_active=True, is_enabled=True, source_type='csv_table')
        src = q.filter_by(source_id=table_id).first() if table_id else None
        if src is None:
            candidates = q.all()
            if len(candidates) == 1 and not table_id:
                src = candidates[0]      # 표가 하나뿐이면 굳이 고르게 하지 않는다
            else:
                return {"error": "table_id not found — call list_lookup_sources first",
                        "available": [c.source_id for c in candidates]}
        try:
            cfg = _json.loads(src.config_json or '{}')
        except (ValueError, TypeError):
            cfg = {}
        _cols = None
        if columns:
            _cols = ([c.strip() for c in columns.split(',') if c.strip()]
                     if isinstance(columns, str) else list(columns))
        rows, err = rts.query(src, cfg, str(query), limit=limit, columns=_cols)
        if err:
            return {"error": err}
        if not rows:
            # 0건일 때 **무엇을 해야 하는지**를 여기서 말한다. 매니페스트가 아니라
            # 응답이라 고정비가 0이고, 필요한 순간에만 나간다.
            #
            # 왜 별칭표로 안 되는가(사용자 지적, 2026-08-24): 김장무·총각무·
            # 알타리무·달청무가 전부 radish 다. 유의어는 끝이 없어서 표로 다 담을
            # 수 없다 — 유의어를 정규 이름으로 옮기는 일은 **모델이 잘하는 일**이고,
            # 표가 어느 언어로 매겨졌는지는 **데이터가 아는 일**이다. 각자 잘하는
            # 쪽에 맡긴다: 언어는 name_language 로 알려 주고, 옮기는 판단은 모델에게
            # 넘기되 여기서 명시적으로 시킨다.
            hint = ''
            lang = (cfg.get('name_language') or '').strip()
            tried = str(query).strip()
            if lang:
                hint = (" This table is keyed by: %s. '%s' may be a local or colloquial "
                        "name for something listed under a different one — work out the "
                        "canonical name yourself (e.g. a regional variety name maps to its "
                        "species' common or scientific name) and call this tool ONCE more "
                        "with that. Only if that also returns nothing is the row absent."
                        % (lang, tried))
            return {"rows": [], "matched": 0, "query": tried,
                    "name_language": lang or None,
                    "aliases": (cfg.get('aliases') or '').strip() or None,
                    "note": ("No row matched '%s'." % tried) + hint +
                            " Do NOT answer from your own memory as if the table had said it."}
        result = {"rows": rows, "matched": len(rows),
                  "table": (cfg.get('title') or src.source_name),
                  # 이 값을 knowledge_shelve(source_ref=...) 에 그대로 넘기면,
                  # 비친 항목이 "확인할 데가 있는 것" 으로 표시된다.
                  "source_ref": src.source_id}
        # 기본 투영이 걸렸으면 그 사실을 말한다 — 안 그러면 모델은 이 표에 이
        # 컬럼들뿐이라고 읽고, 없는 값을 '없다' 고 단정한다.
        if not _cols and (cfg.get('summary_columns') or '').strip():
            result["columns_shown"] = 'summary'
            result["more_columns"] = ("This table has more columns than shown. "
                                      "Call again with columns='*' or a specific "
                                      "column list if you need them.")
        # 표기를 싣는 것만으로는 부족하다 — "답변에 적으라" 고 말하지 않으면
        # 모델은 이것을 그냥 메타데이터로 읽는다(source_attribution 모듈 주석).
        from aot.ai.services import source_attribution
        source_attribution.apply(result, cfg, cfg.get('preset_key'))
        return result

    # ─────────────────────────────────────────────────────────────────────
    # P5-5: Cumulative Goal Tracker query
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def get_cumulative_status(function_id: str, days: int = 7, **kwargs):
        """최근 N일 DLI·GDD 누적 상태와 부채 보상 제안을 반환한다."""
        if not function_id:
            return {"error": "function_id is required"}

        from aot.functions.utils.env_control.cumulative_tracker import load_recent_state
        rows = load_recent_state(function_id, days=days)

        if not rows:
            return {
                "function_id": function_id,
                "days_requested": days,
                "records": [],
                "summary": "No cumulative data — the function has not run yet or the tracker is disabled.",
            }

        # 요약: 최근 일의 부채 합산
        total_debt_dli = sum(r.get('debt_dli') or 0.0 for r in rows)
        total_debt_gdd = sum(r.get('debt_gdd') or 0.0 for r in rows)

        summary_parts = []
        if abs(total_debt_dli) > 0.01:
            direction = "deficit" if total_debt_dli > 0 else "surplus"
            summary_parts.append(f"DLI {direction} {abs(total_debt_dli):.2f} mol/m² ({days}-day total)")
        if abs(total_debt_gdd) > 0.01:
            direction = "deficit" if total_debt_gdd > 0 else "surplus"
            summary_parts.append(f"GDD {direction} {abs(total_debt_gdd):.2f}°C·day ({days}-day total)")

        return {
            "function_id": function_id,
            "days_requested": days,
            "records": rows,
            "total_debt_dli": total_debt_dli,
            "total_debt_gdd": total_debt_gdd,
            "summary": ", ".join(summary_parts) if summary_parts else f"Targets met well over the last {days} days",
        }

    # ─────────────────────────────────────────────────────────────────────
    # Knowledge-library catalog (2026-07-19) — the AI could describe the
    # SmartFarmKorea setup in detail (its recipe is injected into the tool
    # manifests) but had NO way to enumerate the OTHER source types, so
    # "what knowledge libraries can I add?" was answered with SmartFarmKorea
    # only. This read-only tool returns the full LIBRARY_PRESETS catalog so
    # the AI recommends the whole range: the external public-data APIs AND the
    # custom types (document / web page / REST API / internal query).
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def list_library_source_types_tool(**extra):
        """List every knowledge-library source type the operator can add, so
        the AI recommends the full range (not just SmartFarmKorea). Read-only.
        Reads the LIBRARY_PRESETS catalog (routes_ai_library) — the same list
        the Add-source dropdown shows."""
        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS  # lazy: avoid import cycle
        system, custom = [], []
        for key, p in LIBRARY_PRESETS.items():
            entry = {
                "key": key,
                "label": p.get("label", key),
                "description": p.get("description_ko") or p.get("description", ""),
            }
            entry["region"] = p.get("region", "any")
            entry["topics"] = p.get("topics", ["any"])
            if p.get("is_system"):
                entry["url"] = p.get("url_source", "")
                entry["needs_api_key"] = True
                entry["multi_operation"] = bool(p.get("multi_operation"))
                system.append(entry)
            else:
                entry["source_type"] = p.get("source_type", key)
                custom.append(entry)
        regions = sorted({e["region"] for e in system})
        return {
            "system_presets": system,
            "custom_types": custom,
            # 지역 축을 **결과에서 계산해** 싣는다. 상수로 "한국 전용" 이라고
            # 적어 두면 지역 불가지 프리셋이 하나라도 생기는 순간 거짓말이 된다.
            "system_preset_regions": regions,
            "note": "system_presets are pre-built external public-data APIs — each needs its own API "
                    "key from that provider, and each carries a `region`. IMPORTANT: every built-in "
                    "preset today is region='KR' (Korean public data). If this operation is NOT in "
                    "Korea, say so plainly instead of recommending one — the way anywhere else gets "
                    "covered is custom_types, which ingest the operator's OWN material: a document "
                    "(PDF/text/markdown), a web page, any REST API, or an internal DB query. Those "
                    "work in any country and for any subject (crop, livestock, structure, "
                    "infrastructure). When asked what can be added, present BOTH groups and match "
                    "them to where the operator actually is and what they actually manage.",
        }

    # ─────────────────────────────────────────────────────────────────────
    # SmartFarmKorea AI-driven setup (Phase 2, docs/design/ai-library-redesign.md)
    #
    # The discovery primitive (resolve_farms/resolve_seasons) that Phase 1's
    # cascading pickers use is exposed here as two AI tools so the AI can
    # register a SmartFarmKorea source end-to-end on the user's behalf — the
    # relational drill-down (identity → cropping → codes) is exactly the
    # multi-step code-juggling a human shouldn't do. The RECIPE lives in the
    # tool manifests (usage_hint) — the always-visible injection point — so
    # the model knows the discovery order without a separate knowledge doc.
    # See project_smartfarmkorea_sources memory.
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def smartfarmkorea_lookup_tool(dataset=None, api_key=None, mode='farms',
                                   user_id=None, query=None, crop=None, limit=20, **extra):
        """Discover SmartFarmKorea farms or cropping seasons (read-only) so the
        AI can resolve userId/facilityId/croppingSerlNo without asking the user
        for codes. Wraps resolve_farms/resolve_seasons. `crop` filters to farms/
        seasons of that crop (딸기/토마토/…) — use it so a 딸기 request never
        returns a 토마토 farm. Only 시설/노지 have a discovery chain — 축산
        returns a clear no-op error."""
        from aot.ai.context.ext.smartfarmkorea_client import (
            operations_for_preset, resolve_farms, resolve_seasons,
        )
        if not api_key or not str(api_key).strip():
            return {"error": "api_key is required (the SmartFarmKorea service key)"}
        ops = operations_for_preset(str(dataset or '').strip())
        mode = str(mode or 'farms').strip().lower()
        key = str(api_key).strip()

        if mode == 'farms':
            items, err = resolve_farms(key, operations=ops)
        elif mode == 'seasons':
            if not user_id or not str(user_id).strip():
                return {"error": "user_id is required for mode='seasons' — first look up farms and pick a userId"}
            items, err = resolve_seasons(key, str(user_id).strip(), operations=ops)
        else:
            return {"error": "mode must be 'farms' or 'seasons'"}
        if err:
            return {"error": err}

        items = items or []
        total = len(items)
        # crop filter: match the resolved crop name (or the raw itemCode, so a
        # numeric code still works). Applied separately from `query` so the AI
        # can combine region (query) AND crop precisely.
        if crop:
            c = str(crop).strip().lower()
            items = [it for it in items
                     if c in str(it.get('crop', '')).lower() or c in str(it.get('itemCode', '')).lower()]
        if query:
            q = str(query).strip().lower()
            def _hay(it):
                return ' '.join([str(it.get('label', '')), str(it.get('userId', '')),
                                 str(it.get('croppingSerlNo', '')), str(it.get('itemCode', ''))]).lower()
            items = [it for it in items if q in _hay(it)]
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 20
        shown = items[:lim]
        _filters = ', '.join(f for f in [f"crop='{crop}'" if crop else '', f"query='{query}'" if query else ''] if f)
        if _filters:
            note = f"{total} total; {len(items)} matched ({_filters}), showing {len(shown)}"
        elif total > len(shown):
            note = f"{total} total; showing first {len(shown)} — pass crop and/or query to narrow"
        else:
            note = f"{total} total"
        return {"mode": mode, "total": total, "returned": len(shown), "note": note, "items": shown}

    @staticmethod
    def configure_library_source_tool(preset_key=None, api_key=None, operations=None,
                                      source_id=None, activate=True, sync=True,
                                      farm_label=None, season_label=None, **params):
        """Create or update a SmartFarmKorea library source with resolved
        config, then (default) activate + sync so its measured data enters the
        knowledge layer. Mutating → approval-gated (registers a source and
        fetches external data). `params` carries the per-operation values
        (userId/facilityId/croppingSerlNo/itemCode/measDate/startDate/endDate/
        fldCode/sectCode/fatrCode) — pass whatever the selected operations need
        (resolve IDs via smartfarmkorea_lookup, don't ask the user for codes)."""
        import json as _json
        import uuid as _uuid
        from aot.ai.context.ext.smartfarmkorea_client import operations_for_preset
        from aot.databases.models import AIContextSource, Misc

        _SFK_PRESETS = ('smartfarmkorea', 'smartfarmkorea_outdoor', 'smartfarmkorea_livestock')
        if preset_key not in _SFK_PRESETS:
            return {"error": f"preset_key must be one of {_SFK_PRESETS}"}
        if not api_key or not str(api_key).strip():
            return {"error": "api_key is required"}

        ops_list = operations or []
        if isinstance(ops_list, str):
            ops_list = [o.strip() for o in ops_list.split(',') if o.strip()]
        if not ops_list:
            return {"error": "operations is required (at least one operation key)"}

        dataset_ops = operations_for_preset(preset_key)
        unknown = [o for o in ops_list if o not in dataset_ops]
        if unknown:
            return {"error": f"unknown operations for {preset_key}: {unknown}",
                    "valid_operations": list(dataset_ops.keys())}

        _ALL_PARAMS = ['userId', 'facilityId', 'croppingSerlNo', 'itemCode', 'measDate',
                       'startDate', 'endDate', 'fldCode', 'sectCode', 'fatrCode']
        config = {'preset_key': preset_key, 'api_key': str(api_key).strip(), 'operations': ops_list}
        for p in _ALL_PARAMS:
            if params.get(p) is not None:
                config[p] = str(params.get(p)).strip()
        if farm_label:
            config['_farmLabel'] = str(farm_label)
        if season_label:
            config['_seasonLabel'] = str(season_label)

        # Validate each selected op's required (non-serviceKey) params are present.
        missing_report = []
        for op_key in ops_list:
            op = dataset_ops[op_key]
            miss = [p for p in op['params'] if p != 'serviceKey' and not (config.get(p) or '').strip()]
            if miss:
                missing_report.append({"operation": op['label_ko'], "missing": miss})
        if missing_report:
            return {"error": "missing required params for some operations", "details": missing_report,
                    "hint": "Resolve userId/croppingSerlNo via smartfarmkorea_lookup; ask the user for "
                            "date ranges and any classification codes (fldCode/sectCode/fatrCode)."}

        from aot.aot_flask.routes_ai_library import LIBRARY_PRESETS  # lazy: avoid import cycle
        preset = LIBRARY_PRESETS.get(preset_key, {})

        if source_id:
            source = AIContextSource.query.filter_by(source_id=source_id).first()
            if not source:
                return {"error": f"source_id not found: {source_id}"}
            source.config_json = _json.dumps(config)
            action = 'updated'
        else:
            misc = Misc.query.first()
            fid = (getattr(misc, 'default_facility_id', None) or 'default') if misc else 'default'
            source = AIContextSource(
                facility_id=fid,
                source_name=preset.get('label', preset_key),
                source_type=preset.get('source_type', 'rest_api'),
                parameter_name=f"{preset_key}.{str(_uuid.uuid4())[:8]}",
                config_json=_json.dumps(config),
                sync_interval_min=preset.get('sync_interval_min', 1440),
                is_active=True, is_enabled=False,
            )
            db.session.add(source)
            action = 'created'

        if activate:
            source.is_enabled = True
        db.session.commit()

        result = {"status": action, "source_id": source.source_id,
                  "source_name": source.source_name, "operations": ops_list,
                  "activated": bool(activate)}

        if sync and activate:
            from aot.ai.services.context_source_service import sync_source
            msgs = sync_source(source.source_id)
            result["synced"] = not bool(msgs.get('error'))
            result["sync_error"] = msgs.get('error')
            result["sync_info"] = msgs.get('info')
            result["sync_warning"] = msgs.get('warning')
        return result

    # =========================================================================
    # @ANCHOR: ADVISORY_READ_TOOLS
    # 외부 AI가 "상태를 점검하고 제어를 조언"하려면 읽어야 하는데 도구가 없던
    # 네 가지를 노출한다. 전부 읽기 전용이며, 기존 구현을 감싸는 것이지 새 로직이
    # 아니다. 조언의 근거가 되는 값이므로 신선도/출처/미설정 사유를 함께 반환한다.
    # =========================================================================

    @staticmethod
    def get_control_state(facility_name=None, facility_id=None,
                          include_inactive=False, **extra):
        """[읽기전용] 환경제어 코디네이터의 현재 목표값과 최근 판단 결과.

        무엇이 목표이고(setpoint), 무엇이 제약을 걸었고(limiting factor),
        안전게이트가 열렸는지, 어떤 액추에이터에 왜 명령이 갔는지를 반환한다.
        예보/센서만으로는 알 수 없는 "지금 시스템이 무슨 의도로 움직이는가"에
        해당하므로, 제어 조언 전에 반드시 읽어야 하는 값이다.

        AISummaryService._gather_env_control_context() 와 같은 소스를 읽지만
        의도적으로 다르게 만든 점이 두 가지 있다:
          - function_id 를 포함한다. 코디네이터는 이름이 겹칠 수 있어
            (실환경에 'Env Coordinator' 동명 2개 존재) 이름으로는 키가 안 된다.
          - target_temperature/humidity, tolerance, priority, 스케줄 창을
            추가로 노출한다. 조언에 필요한데 그쪽에는 빠져 있다.
        """
        import json as _json
        try:
            from aot.databases.models import CustomController, FunctionRuntimeState, GeoFacility

            q = CustomController.query.filter_by(device='env_coordinator')
            if not include_inactive:
                q = q.filter_by(is_activated=True)
            controllers = q.all()
            if not controllers:
                return {"status": "success", "count": 0, "coordinators": [],
                        "message": "No environment-control coordinator (env_coordinator) is registered."}

            # 시설 이름 해석용 (geo_facility_id → GeoFacility.unique_id)
            fac_names = {f.unique_id: f.name for f in GeoFacility.query.all()}

            wanted_name = (facility_name or '').strip().lower() or None
            out = []
            for c in controllers:
                try:
                    o = _json.loads(c.custom_options) if c.custom_options else {}
                except (ValueError, TypeError):
                    o = {}

                fid = o.get('geo_facility_id')
                fname = fac_names.get(fid)
                if facility_id and fid != facility_id:
                    continue
                if wanted_name and wanted_name not in (fname or '').lower():
                    continue

                # 이 코디네이터가 **무엇을 기르고 있는가**. 설정값을 판단하려면
                # 목표 온습도만으로는 부족하다 — 같은 25도가 상추에는 높고
                # 토마토에는 적정이다. 작물도 목표도 구획의 프로그램에서 온다
                # (예전에는 함수에서 고른 `crop_preset` 이 실제로 심긴 것과
                # 다를 수 있었다).
                _bay = (o.get('bay_scope') or '').strip() or None
                _plants = []
                if fid:
                    try:
                        from aot.aot_flask.geo import plot_context as _pc
                        _plants = [_pc.plot_brief_for_control(r)
                                   for r in _pc.plots_in_facility(fid, bay_id=_bay)]
                    except Exception as exc:
                        logger.warning(
                            "list_env_coordinators: 식생 조회 실패(%s): %s", fid, exc)

                entry = {
                    "function_id": c.unique_id,
                    "function_name": c.name,
                    "is_activated": bool(c.is_activated),
                    "facility_id": fid,
                    "facility_name": fname,
                    "bay_scope": o.get('bay_scope') or None,
                    "plots": _plants,
                    "effect_engine": o.get('effect_engine', 'legacy'),
                    "targets": {
                        "source": "plot program",
                        **_control_targets_for(c),
                    },
                    "tolerance": {
                        "vpd": o.get('tolerance_vpd'),
                        "temperature_c": o.get('tolerance_temperature'),
                        "humidity_pct": o.get('tolerance_humidity'),
                        "co2_ppm": o.get('tolerance_co2'),
                    },
                    "priority": {
                        "vpd": o.get('priority_vpd'),
                        "temperature": o.get('priority_temperature'),
                        "humidity": o.get('priority_humidity'),
                        "co2": o.get('priority_co2'),
                    },
                    "safety_range": {
                        "temp_c": [o.get('temp_min'), o.get('temp_max')],
                        "humid_pct": [o.get('humid_min'), o.get('humid_max')],
                        "guide_temp_c": [o.get('guide_T_min'), o.get('guide_T_max')],
                        "guide_humid_pct": [o.get('guide_RH_min'), o.get('guide_RH_max')],
                    },
                    "window": {
                        # 시작일은 구획에서 온다 — 함수 옵션에는 없다.
                        "season": [_plot_started_on(c), o.get('schedule_end_time')],
                        "daily_enabled": o.get('time_enable'),
                        "daily": [o.get('time_start'), o.get('time_end')],
                    },
                }

                state = FunctionRuntimeState.query.filter_by(function_id=c.unique_id).first()
                if state and state.summary_json:
                    try:
                        entry["latest_cycle_summary"] = _json.loads(state.summary_json)
                    except (ValueError, TypeError):
                        entry["latest_cycle_summary_error"] = "Failed to parse summary_json"
                else:
                    entry["latest_cycle_summary"] = None
                    entry["latest_cycle_note"] = (
                        "No decision-cycle record yet - the coordinator has never run, "
                        "or summary recording is disabled.")
                out.append(entry)

            return {"status": "success", "count": len(out), "coordinators": out}
        except Exception as e:
            logger.exception("Error in get_control_state")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_output_state(device_id, channel=None, **extra):
        """[읽기전용] 출력장치(밸브/펌프/릴레이 등)의 현재 ON/OFF 상태.

        set_output_state(쓰기)의 짝이 되는 읽기 도구 — 이게 없으면 AI가 장치를
        끄고 켤 수는 있어도 "지금 켜져 있는지"는 확인할 방법이 없었다.
        get_control_state는 env_coordinator에 등록된 액추에이터만 커버해서
        일반 밸브/펌프에는 못 쓴다 (그건 그 나름대로 목적이 다르다).

        세 가지를 합친다:
          - 실시간 on/off 상태: DaemonControl.output_states_all() (데몬 다운 시
            안전하게 빈 dict를 반환하도록 이미 처리되어 있음)
          - 켜진 지속시간(초): DaemonControl.output_sec_currently_on()
          - 정확히 언제 켜졌는지: InfluxDB의 output_started_at (base_output.py가
            켜질 때마다 기록 — LoRaWAN처럼 컨펌이 필요한 장치는 실제 컨펌된
            시점 기준이라 커맨드 전송 시각보다 정확하다). AoT_timer 위젯이 쓰는
            것과 같은 조회 로직(_read_latest_started_at)을 그대로 재사용한다 —
            KST/UTC 오인식 같은 이미 검증된 예외 처리를 중복 구현하지 않기 위해.

        과거 on/off 반복 이력(언제 껐다 켰다 했는지)은 다루지 않는다 — 그건
        InfluxDB를 직접 시계열로 조회해야 하는 별개 질문이다.
        """
        try:
            if isinstance(device_id, dict):
                results = device_id.get('results') or device_id.get('result', {}).get('results', [])
                if results and isinstance(results, list):
                    device_id = results[0].get('id') or results[0].get('unique_id') or results[0].get('device_id')
            if not device_id or not isinstance(device_id, str):
                return {"error": "device_id is required (string UUID)"}

            output = Output.query.filter_by(unique_id=device_id).first()
            if not output:
                return {"error": f"No Output found with unique_id {device_id}"}

            from aot.aot_client import DaemonControl
            from aot.widgets.AoT_timer import _read_latest_started_at

            daemon = DaemonControl()
            all_states = daemon.output_states_all() or {}
            channel_states = all_states.get(device_id, {})

            if not channel_states:
                return {
                    "status": "success",
                    "device_id": device_id,
                    "name": output.name,
                    "channels": {},
                    "message": "No live state available (daemon may be down, or this "
                               "output hasn't been read since it started)."
                }

            wanted_channels = [channel] if channel is not None else sorted(channel_states.keys())
            channels_out = {}
            for ch in wanted_channels:
                if ch not in channel_states:
                    continue
                entry = {"state": channel_states[ch]}
                try:
                    entry["seconds_on"] = daemon.output_sec_currently_on(device_id, ch)
                except Exception:
                    entry["seconds_on"] = None
                try:
                    started = _read_latest_started_at(device_id, ch, lookback_sec=7 * 86400)
                    if started:
                        entry["started_at"] = serialize_ts(
                            datetime.utcfromtimestamp(started["selected_epoch"]))
                except Exception:
                    pass
                channels_out[str(ch)] = entry

            return {
                "status": "success",
                "device_id": device_id,
                "name": output.name,
                "channels": channels_out
            }
        except Exception as e:
            logger.exception("Error in get_output_state")
            return {"error": str(e)}

    @staticmethod
    def _forecast_fallback_hint():
        """등록된 전세계 기상 소스를 가리키는 한 문장.

        등록돼 있을 때만 말한다. 없는 것을 권하면 모델이 부를 수 없는 것을
        부르려 들고, 그 실패가 사용자에게는 그냥 '고장' 으로 보인다.
        """
        try:
            from aot.ai.services import data_source_query_service as _dsq
            for src, cfg in _dsq._sources():
                if cfg.get('preset_key') == 'ext_openmeteo':
                    return (" A global forecast source IS registered — call "
                            "query_data_source(source_id=%r, operation='forecast_daily') "
                            "(or 'forecast_hourly' for the next hours)." % src.source_id)
        except Exception:
            pass
        return (" No global forecast source is registered; the operator can add "
                "Open-Meteo on the AI Library page.")

    @staticmethod
    def get_weather_forecast(hours=24, **extra):
        """[읽기전용] 기상청 단기예보 — 선제 제어 조언의 근거.

        get_weather 는 '현재' 센서값만 다루므로, 예보 없이는 "곧 기온이
        떨어지니 미리 보온하라" 같은 조언이 불가능하다. env_coordinator 의
        feedforward 가 쓰는 것과 같은 forecast.json 을 읽는다.

        예보 파일이 갱신되지 않은 환경이 실제로 존재하므로(발행시각이 수개월
        지난 경우를 확인함), 발행시각과 경과시간·stale 여부를 반드시 함께
        반환한다. 낡은 예보로 조언하는 것을 막기 위한 것이다.
        """
        from datetime import datetime as _dt
        try:
            from aot.functions.utils.env_control.forecast_feedforward import _load_forecast

            data = _load_forecast() or {}
            forecasts = data.get('forecasts') or {}
            if not forecasts:
                # 여기서 끝내면 한국 밖 설치는 예보를 영원히 못 얻는다 — 이
                # 경로는 기상청 단기예보 전용이고, 그런 설치에는 애초에 채워질
                # 일이 없는 파일이다. 대안이 등록돼 있으면 그것을 가리킨다.
                return {"status": "unavailable",
                        "message": ("No KMA forecast data. This path is Korea-only "
                                    "(기상청 단기예보); outside Korea it is never "
                                    "populated." + AoTDataToolService._forecast_fallback_hint()),
                        "checked_source": "forecast.json"}

            pub_raw = data.get('pub_dt')
            published_at, age_hours = None, None
            if pub_raw:
                try:
                    pub = _dt.strptime(str(pub_raw), '%Y%m%d%H%M')
                    published_at = pub.isoformat()
                    age_hours = round((_dt.now() - pub).total_seconds() / 3600.0, 1)
                except ValueError:
                    published_at = str(pub_raw)

            # 키는 현재시각 기준 시간 오프셋(문자열). 음수는 과거이므로 버린다.
            try:
                limit = max(1, int(hours))
            except (TypeError, ValueError):
                limit = 24

            future = []
            for k, v in forecasts.items():
                try:
                    off = int(k)
                except (TypeError, ValueError):
                    continue
                if 0 <= off <= limit:
                    future.append({"hour_offset": off, **(v if isinstance(v, dict) else {})})
            future.sort(key=lambda x: x["hour_offset"])

            stale = age_hours is not None and age_hours > 6
            result = {
                "status": "success",
                "published_at": published_at,
                "age_hours": age_hours,
                "stale": stale,
                "requested_hours": limit,
                "count": len(future),
                "units": data.get('units'),
                "forecasts": future,
            }
            if stale:
                result["warning"] = (
                    f"This forecast was issued {age_hours} hours ago. It is stale: do not "
                    f"recommend pre-emptive control based on it; report that forecast "
                    f"collection needs checking first.")
            if not future:
                result["warning"] = (
                    "No future entries in the requested window (the file holds past hours "
                    "only). " + result.get("warning", ""))
            return result
        except Exception as e:
            logger.exception("Error in get_weather_forecast")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_anomalies(scope_type="system", scope_id=None, **extra):
        """[읽기전용] 지금 이상 상태가 있는지 — 임계 위반·오프라인 비율 등.

        기존에는 이상탐지가 백그라운드 감시 파이프라인으로만 존재해서 AI가
        "지금 이상 있나?"를 물어볼 수단이 없었다. 감시 로직을 그대로 재사용해
        온디맨드 조회로 노출한다. 판정만 하고 알림 발송은 하지 않는다.
        """
        try:
            from aot.ai.services.ai_summary_service import AISummaryService
            from aot.ai.services.ai_anomaly_detector import AIAnomalyDetector

            current = AISummaryService.gather_scope_data(scope_type, scope_id)
            previous = AISummaryService.get_latest_summary(scope_type, scope_id)
            verdict = AIAnomalyDetector.detect_anomalies(current, previous) or {}

            return {
                "status": "success",
                "scope": {"type": scope_type, "id": scope_id},
                "anomaly_detected": verdict.get('anomaly_detected', False),
                "alert_level": verdict.get('alert_level', 'none'),
                "anomalies": verdict.get('anomalies', []),
                "metrics": current.get('metrics', {}),
                # 두 가지를 응답 안에서 못 박는다. 둘 다 실제로 사람을 헷갈리게
                # 한 적이 있다(2026-08-17).
                "metrics_definitions": {
                    "total_devices": ("Inputs (sensors) in this scope ONLY. "
                                      "get_system_brief's devices.device_count is a "
                                      "different number by design — it also counts "
                                      "outputs, cameras and complex devices."),
                    "active_devices": ("Inputs the operator has switched ON. This is "
                                       "intent, not reachability."),
                    "comm_capable_devices": ("Inputs whose driver can observe its own "
                                             "link at all. Most cannot."),
                    "comm_offline_devices": (
                        "Inputs whose driver REPORTS a communication fault "
                        "(comm_is_fault). A device that simply stopped sending data is "
                        "NOT counted here and never will be — silence is not a fault "
                        "signal. To find long-silent devices call get_device_freshness."),
                },
                "compared_with": ("이전 요약 v%s" % previous.version) if previous else None,
                "evaluated_at": current.get('timestamp'),
            }
        except Exception as e:
            logger.exception("Error in get_anomalies")
            return {"status": "error", "message": str(e)}

    # 신선도 판정 상수 — 전역 임계값이 아니라 **장치 주기의 배수**다.
    # Input.period 는 15초부터 86400초(1일)까지라 고정 상수로 판정하면 하루 한 번
    # 재는 센서가 늘 고장으로 보인다(CLAUDE.md "측정값 신선도는 장치 주기 대비로만").
    # 표시 경로(facility_sensors.STALE_PERIOD_FACTOR=2)보다 한 칸 넉넉한 3배를
    # 쓰는 이유는 여기가 "사람에게 이상하다고 알리는" 자리이기 때문이다 —
    # 표본 한 번 유실로 목록이 흔들리면 목록 자체를 안 보게 된다.
    _FRESHNESS_PERIOD_FACTOR = 3
    _FRESHNESS_MIN_AGE_S = 300          # 하한: 주기가 아주 짧은 장치의 지터 흡수
    _FRESHNESS_SCAN_CAP_S = 30 * 86400  # 조회 창 상한(무제한 스캔 방지)
    _FRESHNESS_MAX_CHANNELS = 4         # 장치당 물어볼 채널 수 상한

    @staticmethod
    def _last_seen_seconds(device_id):
        """(age_seconds, last_seen_iso, channel_label) — 없으면 (None, None, None).

        채널을 하나씩 물어 **처음 답하는 채널**에서 멈춘다. 전 채널의 최댓값을
        구하면 정확하지만 장치당 질의가 채널 수만큼 늘고, "이 장치가 최근에
        말을 했는가" 라는 질문에는 한 채널이면 충분하다.
        """
        from aot.utils.influx import read_influxdb_single

        rows = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == device_id).all()
        rows = [m for m in rows if getattr(m, 'is_enabled', True)]
        rows.sort(key=lambda m: (m.channel if m.channel is not None else 9999))

        newest_ts, newest_label = None, None
        for m in rows[:AoTDataToolService._FRESHNESS_MAX_CHANNELS]:
            conversion = (Conversion.query.filter(
                Conversion.unique_id == m.conversion_id).first()
                if m.conversion_id else None)
            channel, unit, measurement = return_measurement_info(m, conversion)
            try:
                last_time, _ = read_influxdb_single(
                    device_id, unit, channel, measure=measurement,
                    duration_sec=AoTDataToolService._FRESHNESS_SCAN_CAP_S,
                    value='LAST')
            except Exception:
                logger.debug("[FRESHNESS] %s ch%s 조회 실패", device_id, channel,
                             exc_info=True)
                continue
            if last_time:
                newest_ts = float(last_time)
                newest_label = "%s (ch%s)" % (measurement or m.measurement, channel)
                break

        if newest_ts is None:
            return None, None, None
        try:
            from datetime import timezone as _tz
            seen = datetime.fromtimestamp(newest_ts, _tz.utc)
            age = (now_utc() - seen).total_seconds()
        except Exception:
            return None, None, None
        return max(0.0, age), seen.isoformat(), newest_label

    @staticmethod
    def get_device_freshness(device_id=None, include_fresh=False, **extra):
        """[읽기전용] 장치마다 마지막으로 값이 들어온 시각과 **정상 주기 대비**
        몇 배나 늦었는지.

        get_anomalies 의 comm_offline_devices 와 **다른 축이다.** 그쪽은 드라이버가
        스스로 통신 실패를 보고한 것만 센다(comm_is_fault). 데이터가 그냥 끊긴
        장치는 거기 절대 안 잡히고, 잡히게 만들어서도 안 된다 — 침묵은 장애 신호가
        아니다(하루 한 번 재는 센서, 겨울에 꺼 둔 장치, 비 올 때만 보내는 노드).
        그래서 이 도구는 **판정하지 않고 사실만 보고한다**: 마지막 수신 시각,
        경과 시간, 그 장치 자신의 주기 대비 배수. 조치 여부는 사람이 정한다.

        판정 기준은 장치 주기다 — 전역 상수가 아니다. period=15s 장치의 45초와
        period=1d 장치의 3일은 같은 무게이고, 300초 같은 고정 임계값을 쓰면
        후자는 정상인데도 항상 목록에 뜬다.
        """
        try:
            q = Input.query
            if device_id:
                q = q.filter(Input.unique_id == device_id)
            devices = q.all()
            if not devices:
                return {"status": "success", "checked": 0, "stale_devices": [],
                        "message": ("No such device." if device_id
                                    else "No inputs are registered.")}

            try:
                from aot.ai.services.ai_context_service import AIContextService
                zone_map = AIContextService.get_device_zone_map() or {}
            except Exception:
                zone_map = {}

            stale, fresh, no_data, inactive = [], [], [], []
            for d in devices:
                try:
                    period = float(d.period) if d.period else None
                except (TypeError, ValueError):
                    period = None
                threshold = AoTDataToolService._FRESHNESS_MIN_AGE_S
                if period:
                    threshold = max(threshold,
                                    period * AoTDataToolService._FRESHNESS_PERIOD_FACTOR)

                age, seen_iso, label = AoTDataToolService._last_seen_seconds(
                    d.unique_id)
                entry = {
                    "name": d.name,
                    "device_id": d.unique_id,
                    "driver": d.device,
                    "zone": zone_map.get(d.unique_id),
                    "is_activated": bool(d.is_activated),
                    "period_seconds": period,
                    "expected_within_seconds": int(threshold),
                    "last_seen": seen_iso,
                    "last_seen_channel": label,
                    "age_seconds": int(age) if age is not None else None,
                    "age_readable": (AoTDataToolService._readable_age(age)
                                     if age is not None else None),
                    "periods_late": (round(age / period, 1)
                                     if (age is not None and period) else None),
                }
                if not d.is_activated:
                    # 사람이 꺼 둔 장치가 말이 없는 것은 당연하다. 섞으면 목록이
                    # 정상 상태로 가득 차 실제 침묵이 묻힌다.
                    inactive.append(entry)
                elif age is None:
                    no_data.append(entry)
                elif age > threshold:
                    stale.append(entry)
                else:
                    fresh.append(entry)

            stale.sort(key=lambda e: -(e["periods_late"] or 0))
            result = {
                "status": "success",
                "checked": len(devices),
                "basis": ("A device is listed as stale when its newest stored value is "
                          "older than %dx its own sampling period (minimum %ds). This is "
                          "an observation, not a fault verdict — see 'caveat'."
                          % (AoTDataToolService._FRESHNESS_PERIOD_FACTOR,
                             AoTDataToolService._FRESHNESS_MIN_AGE_S)),
                "caveat": ("Silence is not proof of failure. Event-driven inputs, "
                           "seasonal equipment and devices whose gateway is simply idle "
                           "look identical here. Report what is late and by how many "
                           "periods; do not call it a fault. A real communication fault "
                           "appears in get_anomalies' comm_offline_devices."),
                "stale_devices": stale,
                "stale_count": len(stale),
                "no_data_devices": no_data,
                "no_data_count": len(no_data),
                "inactive_devices": inactive,
                "inactive_count": len(inactive),
                "fresh_count": len(fresh),
                "scan_window_days": int(AoTDataToolService._FRESHNESS_SCAN_CAP_S / 86400),
            }
            if include_fresh:
                result["fresh_devices"] = fresh
            return result
        except Exception as e:
            logger.exception("Error in get_device_freshness")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _readable_age(seconds):
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            return None
        if seconds < 60:
            return "%ds" % seconds
        if seconds < 3600:
            return "%dm" % (seconds // 60)
        if seconds < 86400:
            return "%dh %dm" % (seconds // 3600, (seconds % 3600) // 60)
        return "%dd %dh" % (seconds // 86400, (seconds % 86400) // 3600)

    @staticmethod
    def get_crop_status(facility_id=None, facility_name=None, **extra):
        """[읽기전용] 시설별 작물과 생육단계 — 재배 조언의 전제.

        작물을 모르면 최적 재배 조언 자체가 성립하지 않는다. 인앱 AI는 도메인
        컨텍스트로 자동 주입받지만 MCP 경로는 그 파이프라인을 타지 않아 알 방법이
        없었다.

        두 소스를 겹쳐 읽는다:
          1) **구획의 프로그램** — 무엇을 언제 심었고 지금 몇 단계인가
             (예전에는 함수에서 고른 `crop_preset` 을 1차 소스로 썼는데, 그것은
             사람이 고른 프리셋이라 실제로 심긴 것과 다를 수 있었다)
          2) 도메인 레지스트리(facility_registry.yaml)의 crop_type+planting_date
             → GrowthStageResolver 로 생육단계·재배일수·단계별 최적범위
        레지스트리가 없는 설치도 실제로 존재하므로(이 저장소의 개발 환경이 그렇다),
        2)가 없으면 1)만 반환하고 무엇이 왜 빠졌는지 명시한다 — 조용히 빈 값을
        주면 AI가 작물이 없는 것으로 오해한다.
        """
        import json as _json
        try:
            from aot.databases.models import CustomController, GeoFacility

            fac_names = {f.unique_id: f.name for f in GeoFacility.query.all()}
            wanted_name = (facility_name or '').strip().lower() or None

            rows = []
            for c in CustomController.query.filter_by(device='env_coordinator',
                                                      is_activated=True).all():
                try:
                    o = _json.loads(c.custom_options) if c.custom_options else {}
                except (ValueError, TypeError):
                    o = {}
                fid = o.get('geo_facility_id')
                fname = fac_names.get(fid)
                if facility_id and fid != facility_id:
                    continue
                if wanted_name and wanted_name not in (fname or '').lower():
                    continue
                rows.append({
                    "facility_id": fid,
                    "facility_name": fname,
                    "crop": _control_targets_for(c).get('plot'),
                    "stage": _control_targets_for(c).get('stage'),
                    "controlled_by": c.unique_id,
                    "season_window": [_plot_started_on(c),
                                      o.get('schedule_end_time')],
                })

            # 도메인 레지스트리로 생육단계 보강 (있을 때만)
            registry_note = None
            for r in rows:
                if not r["facility_id"]:
                    continue
                try:
                    from aot.ai.services.domain_context_loader import DomainContextLoader
                    module = DomainContextLoader.load_active_module(r["facility_id"])
                    state = (module or {}).get('operational_state') or {}
                    if state.get('growth_stage'):
                        r["growth_stage"] = state.get('growth_stage')
                        r["days_after_plot"] = state.get('days_after_plot')
                        r["optimal_ranges"] = state.get('optimal_ranges')
                        r["growth_stage_source"] = state.get('growth_stage_source')
                except Exception as exc:
                    registry_note = (
                        "Growth stage unavailable: could not read the domain registry "
                        f"(facility_registry.yaml) ({type(exc).__name__}). The crop type is "
                        "still available from the plot program, but days-after-plot and "
                        "stage-specific optimal ranges require planting_date/crop_type to be "
                        "registered there.")

            # 노지 구획(GeoPlot) — 시설 밖에 심긴 것은 위 두 소스에 **없다**.
            # env_coordinator 도 facility_registry 도 시설 단위라, 여기를 더하지
            # 않으면 AI 는 노지 구역에 대해 "작물 없음" 으로 답한다.
            plots = []
            try:
                from aot.databases.models import GeoMap
                from aot.aot_flask.geo import plot_context
                for m in GeoMap.query.all():
                    for row in plot_context.active_plots(m.unique_id):
                        d = AoTDataToolService._plot_brief(row)
                        d['map_id'] = m.unique_id
                        plots.append(d)
            except Exception as exc:
                logger.warning("get_crop_status: 식생 구획 조회 실패: %s", exc)

            # 시설 구획은 노지가 아니다 — 이름을 섞으면 AI 가 온실 작물을
            # 노지로 읽는다. 판별 축이 **둘**이라는 것이 함정이다:
            #   - `facility_uuid` — 시설 구역에 직접 매단 구획(p6_39)
            #   - `source_kind='bay_snapshot'` — 옛 `bays[].crop` 백필분
            #     (기하를 복사해 왔을 뿐 부모 참조는 없다)
            # 한쪽만 보면 나머지 절반이 조용히 노지로 분류된다.
            # `bays[].crop` 은 아직 살아 있어(폴백) 같은 작물이 facilities 와
            # 여기 양쪽에 보일 수 있다. 그 사실을 note 로 밝힌다.
            def _in_facility(d):
                return bool(d.get('facility_uuid')) or \
                    d.get('source_kind') == 'bay_snapshot'

            bay_plots = [d for d in plots if _in_facility(d)]
            open_plots = [d for d in plots if not _in_facility(d)]

            result = {"status": "success", "count": len(rows), "facilities": rows,
                      "open_field_plots": open_plots, "plot_count": len(open_plots)}
            if bay_plots:
                result["facility_bay_plots"] = bay_plots
                result["facility_bay_plot_note"] = (
                    "These grow inside facilities (greenhouse bays), not in the open "
                    "field, and each carries its own start date and history. Their "
                    "location is the bay itself, so they have no area or capacity "
                    "estimate — read their notes for the actual layout. The same crop "
                    "may still appear under 'facilities' because the legacy "
                    "bays[].crop field is kept until the migration is verified in "
                    "production — do not count it twice.")
            if not rows and not plots:
                result["message"] = (
                    "No active env_coordinator carries crop information. Check whether an "
                    "environment-control coordinator is configured for the facility.")
            elif not rows and plots:
                result["message"] = (
                    "No greenhouse crop info, but open-field vegetation plots exist — "
                    "see open_field_plots (crop, period, area). Use get_plot_history "
                    "for what grew on the same spot before.")
            if registry_note:
                result["growth_stage_unavailable"] = registry_note
            return result
        except Exception as e:
            logger.exception("Error in get_crop_status")
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # @ANCHOR: ADVICE_LEDGER_TOOLS
    # 다자 AI 의견 원장. 메인 AI·외부 AI·하위 노드 AI가 같은 원장에 의견을 넣고
    # 서로의 의견을 읽는다. 제어를 실행하지 않는다 — 실행은 mcp_safety_gate 의
    # 승인 큐를 타야 하며, 이쪽은 "무엇을 왜 해야 한다고 보는가"만 남긴다.
    # =========================================================================

    @staticmethod
    def submit_advice(title=None, advice=None, rationale=None, proposed_action=None,
                      scope_type='system', scope_id=None, severity='info',
                      confidence=None, agent_id=None, agent_kind='external', **extra):
        """[의견 제출] 관측에 근거한 조언을 원장에 남긴다. 제어는 실행되지 않는다.

        상충하는 의견도 덮어쓰지 않고 나란히 쌓인다 — 사람이 출처와 근거를 보고
        판단하는 것이 목적이다. 제어가 필요하다고 보면 proposed_action 에 무엇을
        왜 해야 하는지 적을 것. 실제 실행은 사람 승인을 거친다.
        """
        from datetime import datetime as _dt
        try:
            from aot.databases.models import AIAdvice

            title = (title or '').strip()
            advice = (advice or '').strip()
            if not advice:
                return {"status": "error",
                        "message": "'advice' is required - state what you are advising."}
            if not title:
                # 제목을 생략하면 본문 첫 문장으로 대신한다 (칩·목록 표시용).
                title = advice.split('.')[0].strip()[:200]

            valid_scopes = ('system', 'farm', 'zone', 'facility', 'device')
            if scope_type not in valid_scopes:
                return {"status": "error",
                        "message": f"scope_type must be one of: {', '.join(valid_scopes)}."}
            valid_sev = ('info', 'advice', 'warning', 'urgent')
            if severity not in valid_sev:
                severity = 'info'

            # 스코프 이름 해석 — 목록에서 사람이 알아볼 수 있게.
            scope_name = None
            if scope_id:
                try:
                    shape = GeoShape.query.filter(
                        or_(GeoShape.unique_id == scope_id, GeoShape.geo_id == scope_id)).first()
                    if shape and shape.feature:
                        scope_name = (shape.feature.get('properties') or {}).get('name')
                    if not scope_name:
                        from aot.databases.models import GeoFacility
                        fac = GeoFacility.query.filter_by(unique_id=scope_id).first()
                        scope_name = fac.name if fac else None
                except Exception:
                    scope_name = None

            try:
                conf = float(confidence) if confidence is not None else None
                if conf is not None:
                    conf = min(max(conf, 0.0), 1.0)
            except (TypeError, ValueError):
                conf = None

            row = AIAdvice(
                agent_id=(agent_id or 'unknown')[:100],
                agent_kind=agent_kind if agent_kind in ('main', 'external', 'subordinate') else 'external',
                scope_type=scope_type,
                scope_id=scope_id,
                scope_name=scope_name,
                title=title[:200],
                advice=advice,
                rationale=(rationale or '').strip(),
                proposed_action=(proposed_action or '').strip(),
                severity=severity,
                confidence=conf,
                status='pending',
                created_at=_dt.utcnow(),
            )
            row.save()

            return {
                "status": "success",
                "advice_id": row.unique_id,
                "submitted_by": row.agent_id,
                "scope": {"type": scope_type, "id": scope_id, "name": scope_name},
                "review_status": "pending",
                "message": ("Advice recorded in the ledger. Nothing was executed; a human "
                            "will review it. Use list_advice to compare with other AI "
                            "opinions on the same target."),
            }
        except Exception as e:
            logger.exception("Error in submit_advice")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_system_brief(**extra):
        """[읽기전용] 이 시스템이 무엇이고 지금 어떤 상태인지 — 단일 진입점.

        도구를 수십 개 열어줘도 외부 AI는 "무엇을 언제 써야 하는가"를 모른다.
        인앱 AI는 시스템 프롬프트와 컨텍스트 자동주입으로 그 문제를 피하지만
        MCP 경로에는 그 파이프라인이 없다. 이 도구가 그 공백을 메운다:
        접속 직후 한 번 호출하면 공간 계층·작물·활성 제어·이상 여부·의견 원장
        현황과 다음에 쓸 도구를 함께 얻는다.

        개별 조회 도구를 대체하지 않는다 — 어디를 파야 할지 알려주는 지도다.
        """
        brief = {"status": "success"}
        S = AoTDataToolService

        def _safe(label, fn):
            """한 구획이 실패해도 브리핑 전체를 잃지 않는다."""
            try:
                return fn()
            except Exception as exc:
                logger.warning("get_system_brief: %s 실패: %s", label, exc)
                return {"error": f"Failed to read {label}: {exc}"}

        brief["spatial"] = _safe("공간 계층", lambda: S.get_spatial_tree(depth=2))
        brief["crops"] = _safe("작물", lambda: S.get_crop_status())
        brief["control"] = _safe("제어 상태", lambda: S.get_control_state())
        brief["anomalies"] = _safe("이상 상태", lambda: S.get_anomalies())
        # 핸들러 이름은 get_device_list_tool 이다(도구명과 다름). _safe 가 예외를
        # 처리하므로 hasattr 류의 방어 가드는 두지 않는다 — 가드를 두면 이름이
        # 틀렸을 때 조용히 빈 값이 되어 오히려 사실을 감춘다.
        # 집계의 정의를 응답에 함께 싣는다. 이 수(63)는 get_anomalies 의
        # metrics.total_devices(32)와 **다른 것을 센다** — 여기는 Input+Output+
        # Camera+복합장치 전부, 저기는 Input 만이다. 정의를 안 적어 두면 둘을
        # 나란히 본 AI 가 "장치 31개가 사라졌다" 로 읽는다(2026-08-17 실제 혼동).
        def _device_summary():
            _res = (S.get_device_list_tool() or {}).get("results") or []
            _by_type = {}
            for _r in _res:
                _t = _r.get("type") or "unknown"
                _by_type[_t] = _by_type.get(_t, 0) + 1
            return {
                "device_count": len(_res),
                "count_by_type": _by_type,
                "counts": ("device_count = every registered entity: inputs + "
                           "outputs + cameras + complex devices. get_anomalies' "
                           "metrics.total_devices counts INPUTS ONLY, so it is "
                           "normally smaller — the two are different definitions, "
                           "not a discrepancy."),
                "note": "Use get_device_list / search_devices for the full list",
            }

        brief["devices"] = _safe("장치 요약", _device_summary)
        pending = _safe("의견 원장", lambda: S.list_advice(status='pending', limit=5))
        brief["advice_ledger"] = {
            "pending_count": pending.get("count") if isinstance(pending, dict) else None,
            "recent": (pending.get("results") if isinstance(pending, dict) else None),
            "contested": (pending.get("multiple_agents_on_same_scope")
                          if isinstance(pending, dict) else None),
        }

        brief["how_to_proceed"] = [
            "1. Use this brief to identify the target (facility/zone) and its crop.",
            "2. To judge control, read get_control_state for current targets, the limiting "
            "factor and safety-gate status.",
            "3. Sensor history: get_sensor_detail. Forecast: get_weather_forecast (always "
            "check the 'stale' flag). If a reading looks missing or frozen, call "
            "get_device_freshness — anomalies.comm_offline_devices only counts drivers "
            "that report a fault themselves and stays 0 for a device that simply went "
            "silent.",
            "4. Look up growing guidance and manual references with knowledge_search.",
            "5. Check search_schedule for already-planned work to avoid duplicate or "
            "conflicting instructions.",
            "6. Submit findings with submit_advice; check list_advice first to see other "
            "AI opinions.",
            "7. Executing control (operate_device etc.) requires human approval. Do not "
            "retry direct execution - state what should be done and why, as advice.",
        ]
        return brief

    @staticmethod
    def list_advice(scope_type=None, scope_id=None, status=None, agent_id=None,
                    severity=None, limit=20, **extra):
        """[읽기전용] 원장에 쌓인 AI 의견 조회 — 자신·타 AI·메인 AI의 의견 전부.

        조언을 내기 전에 이 도구로 같은 대상에 이미 어떤 의견이 있는지 확인할 것.
        중복 제출을 막고, 다른 AI와 판단이 갈리면 그 차이를 근거와 함께 짚을 수 있다.
        """
        try:
            from aot.databases.models import AIAdvice

            q = AIAdvice.query
            if scope_type:
                q = q.filter(AIAdvice.scope_type == scope_type)
            if scope_id:
                q = q.filter(AIAdvice.scope_id == scope_id)
            if status:
                q = q.filter(AIAdvice.status == status)
            if agent_id:
                q = q.filter(AIAdvice.agent_id == agent_id)
            if severity:
                q = q.filter(AIAdvice.severity == severity)
            try:
                lim = min(max(int(limit), 1), 100)
            except (TypeError, ValueError):
                lim = 20

            rows = q.order_by(AIAdvice.created_at.desc()).limit(lim).all()
            results = [{
                "advice_id": r.unique_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "agent_id": r.agent_id,
                "agent_kind": r.agent_kind,
                "scope": {"type": r.scope_type, "id": r.scope_id, "name": r.scope_name},
                "title": r.title,
                "advice": r.advice,
                "rationale": r.rationale,
                "proposed_action": r.proposed_action,
                "severity": r.severity,
                "confidence": r.confidence,
                "status": r.status,
                "review_note": r.review_note,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
            } for r in rows]

            # 같은 대상에 여러 주체가 의견을 냈으면 알려준다 — 상충 가능 신호.
            contested = {}
            for r in results:
                if r["status"] != 'pending':
                    continue
                key = f"{r['scope']['type']}:{r['scope']['id']}"
                contested.setdefault(key, set()).add(r["agent_id"])
            multi = [k for k, v in contested.items() if len(v) > 1]

            out = {"status": "success", "count": len(results), "results": results}
            if multi:
                out["multiple_agents_on_same_scope"] = multi
                out["note"] = ("More than one AI has advised on the same target. Where "
                               "judgements differ, explain the difference using each "
                               "rationale as evidence.")
            return out
        except Exception as e:
            logger.exception("Error in list_advice")
            return {"status": "error", "message": str(e)}

    # -------------------------------------------------------------------------
    # 적응형 문서 스토리지 (Tier 1 Hot / 2 Warm / 3 Cold) — 읽기 전용 조회
    #
    # 이 계층은 오래 "판정만 하고 실행은 안 하는" 상태였다. 아래 도구들은 그
    # 실상을 감추지 않고 그대로 보고한다 — AI 가 티어 숫자를 보고 "문서가 실제로
    # 아카이브에 있다" 고 단정하면 안 되기 때문이다. 실제 이동이 배선되기 전까지
    # tier 값은 **의도**이고, cold_documents 에 행이 있어야 **실물**이다.
    # -------------------------------------------------------------------------

    @staticmethod
    def _cold_storage_service():
        from aot.services.cold_storage_service import ColdStorageService
        return ColdStorageService()

    @staticmethod
    def get_storage_tier_status():
        """문서 스토리지 티어 현황 — 설정 활성 여부, 티어 분포, 아카이브 실물 통계."""
        try:
            from aot.databases.models.tier_adaptive_storage import (
                AdaptiveStorageSettings, TierDecision)
            from aot.databases.models.cold_storage import ColdDocuments

            settings = AdaptiveStorageSettings.query.first()
            enabled = bool(settings and settings.enabled)

            tier_counts = {}
            for tier, count in (db.session.query(Notes.tier, db.func.count(Notes.id))
                                .group_by(Notes.tier).all()):
                tier_counts[str(tier if tier is not None else 2)] = count

            archived_rows = ColdDocuments.query.count()
            decisions = TierDecision.query.count()

            out = {
                "status": "success",
                "adaptive_storage_enabled": enabled,
                "document_tier_counts": tier_counts,
                "archived_document_rows": archived_rows,
                "tier_decision_rows": decisions,
            }

            if not enabled:
                out["note"] = (
                    "Adaptive storage is DISABLED (no AdaptiveStorageSettings row, or "
                    "enabled=false). The hourly reclassification job exits immediately, "
                    "so tier values are not being updated at all.")

            # 가장 중요한 경고. tier 값과 실물 아카이브는 아직 연결돼 있지 않다.
            if archived_rows == 0 and any(t == '3' for t in tier_counts):
                out["warning"] = (
                    "Some documents are marked tier 3 (cold) but cold_documents is empty. "
                    "Tier migration is still a placeholder — the tier value records an "
                    "INTENT, not a completed move. Document content is still in its "
                    "original table. Do not tell the user a document was archived unless "
                    "it appears in search_archives.")
            return out
        except Exception as e:
            logger.exception("Error in get_storage_tier_status")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def search_archives(query=None, limit=50, offset=0):
        """아카이브된 문서를 메타데이터로 검색한다. 실제 아카이브 실물만 조회된다."""
        try:
            try:
                limit = max(1, min(int(limit), 200))
                offset = max(0, int(offset))
            except (TypeError, ValueError):
                limit, offset = 50, 0

            svc = AoTDataToolService._cold_storage_service()
            result = svc.search_archives(query=query or None, limit=limit, offset=offset)
            # 서비스 반환 키는 'results' 다 — 'archives' 로 읽으면 아카이브가
            # 있어도 항상 빈 목록이 되어 "보관된 문서 없음" 으로 보고된다.
            archives = result.get('results', [])
            out = {
                "status": "success",
                "count": len(archives),
                "total": result.get('total', len(archives)),
                "results": archives,
            }
            if not archives:
                out["note"] = ("No archived documents. This is the expected state until "
                               "tier migration is wired — it does not mean a search failed.")
            return out
        except Exception as e:
            logger.exception("Error in search_archives")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_archived_document(document_id=None, include_content=False):
        """아카이브 문서 하나를 조회한다. include_content=True 면 본문까지 해제한다."""
        try:
            if not document_id or not isinstance(document_id, str):
                return {"status": "error", "message": "document_id is required"}

            svc = AoTDataToolService._cold_storage_service()
            result = svc.restore_document(document_id,
                                          decompress=bool(include_content))
            if result is None:
                return {
                    "status": "not_found",
                    "document_id": document_id,
                    "message": ("Not in the archive. If the document is marked tier 3, that "
                                "is an intent flag only — its content is still in the "
                                "original table."),
                }
            return {"status": "success", "document": result}
        except FileNotFoundError as e:
            # DB 행은 있는데 파일이 없다 — 조용히 넘기면 안 되는 불일치다.
            logger.error("Archive file missing for %s: %s", document_id, e)
            return {
                "status": "error",
                "document_id": document_id,
                "message": f"Archive record exists but its file is missing: {e}",
            }
        except Exception as e:
            logger.exception("Error in get_archived_document")
            return {"status": "error", "message": str(e)}

    # -------------------------------------------------------------------------
    # 적응형 문서 스토리지 — 쓰기 (전부 승인 게이트 대상)
    #
    # 아카이브는 **사본을 만들 뿐 원본을 지우지 않는다.** 원본 삭제는 보존정책의
    # 몫이고, 여기서 하면 되돌릴 수 없는 작업이 승인 한 번에 묻어 들어간다.
    # 그래서 archive 는 "복사 + tier 표시", restore 는 "tier 되돌리기"까지만 한다.
    # -------------------------------------------------------------------------

    @staticmethod
    def archive_note(note_id=None, retention_policy='default'):
        """노트 본문을 아카이브에 복사하고 tier 를 3(cold)으로 표시한다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                return {"status": "not_found", "message": f"Note {note_id} not found"}

            content = note.note or ''
            if not content.strip():
                return {"status": "error",
                        "message": "Note has no content to archive"}

            meta = {"name": note.name, "note_tags": note.note_tags}
            svc = AoTDataToolService._cold_storage_service()
            result = svc.archive_document(
                document_id=note_id, content=content, metadata=meta,
                retention_policy=retention_policy, archived_by='ai')

            note.tier = 3
            db.session.commit()

            return {
                "status": "success",
                "document_id": note_id,
                "archive_path": result['archive_path'],
                "compression_ratio": result['compression_ratio'],
                "note": ("A copy was archived and the note was marked tier 3. "
                         "The original note text was NOT deleted — deletion is "
                         "handled by the retention policy, not by archiving."),
            }
        except ValueError as e:      # 이미 아카이브됨
            return {"status": "error", "message": str(e)}
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in archive_note")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def restore_note_from_archive(note_id=None, target_tier=2):
        """아카이브 본문을 확인하고 노트를 지정 티어로 되돌린다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}
            try:
                target_tier = int(target_tier)
            except (TypeError, ValueError):
                target_tier = 2
            if target_tier not in (1, 2, 3):
                return {"status": "error", "message": "target_tier must be 1, 2 or 3"}

            svc = AoTDataToolService._cold_storage_service()
            archived = svc.restore_document(note_id, decompress=True)
            if archived is None:
                return {"status": "not_found",
                        "message": f"{note_id} is not in the archive"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                # 아카이브만 남고 원본이 사라진 경우 — 본문을 돌려주되 상태를 밝힌다.
                return {
                    "status": "orphan_archive",
                    "document_id": note_id,
                    "content": archived.get('content'),
                    "message": ("The archive exists but the original note is gone. "
                                "Returning the archived text; recreating the note is "
                                "a separate action."),
                }

            note.tier = target_tier
            db.session.commit()
            return {
                "status": "success",
                "document_id": note_id,
                "tier": target_tier,
                "content_matches_original": (note.note or '') == archived.get('content'),
            }
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in restore_note_from_archive")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def set_document_tier(note_id=None, tier=None):
        """노트의 티어 값만 바꾼다 — 내용은 옮기지 않는다."""
        try:
            if not note_id or not isinstance(note_id, str):
                return {"status": "error", "message": "note_id is required"}
            try:
                tier = int(tier)
            except (TypeError, ValueError):
                return {"status": "error", "message": "tier must be 1, 2 or 3"}
            if tier not in (1, 2, 3):
                return {"status": "error", "message": "tier must be 1, 2 or 3"}

            note = Notes.query.filter_by(unique_id=note_id).first()
            if note is None:
                return {"status": "not_found", "message": f"Note {note_id} not found"}

            previous, note.tier = note.tier, tier
            db.session.commit()

            out = {"status": "success", "document_id": note_id,
                   "previous_tier": previous, "tier": tier}
            if tier == 3:
                out["note"] = ("Marked cold, but nothing was moved. Use archive_note "
                               "to actually place a copy in the archive.")
            return out
        except Exception as e:
            db.session.rollback()
            logger.exception("Error in set_document_tier")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def delete_archive(document_id=None, reason=''):
        """아카이브 사본을 삭제한다. 원본 노트는 건드리지 않는다."""
        try:
            if not document_id or not isinstance(document_id, str):
                return {"status": "error", "message": "document_id is required"}

            svc = AoTDataToolService._cold_storage_service()
            deleted = svc.delete_archive(document_id, deletion_reason=reason or 'ai request')
            if not deleted:
                return {"status": "not_found",
                        "message": f"{document_id} is not in the archive"}
            return {
                "status": "success",
                "document_id": document_id,
                "note": ("The archived copy was deleted. The original note was not "
                         "touched; its tier value is unchanged and may still read 3."),
            }
        except Exception as e:
            logger.exception("Error in delete_archive")
            return {"status": "error", "message": str(e)}

    # ── 식생 구획(작기) ────────────────────────────────────────────────────
    # 설계 정본: docs/design/geo-vegetation-plot.md
    #
    # "어디에 무엇이 심겨 있는가" 는 재배 조언의 전제다. 시설은 예전부터
    # crop_preset / facility_registry 로 알 수 있었지만 **노지는 알 방법이
    # 아예 없었다** — 그래서 AI 가 노지 구역에 대해서는 작물을 모른 채
    # 답하고 있었다.
    #
    # 쓰기는 게이트웨이(plot_io)를 지나간다. 라우트가 하던 검증(VP-1~VP-6)
    # 을 여기서 다시 구현하지 않는다 — 두 벌이 되면 반드시 갈린다.

    @staticmethod
    def _plot_brief(row, with_sensors=False, row_spacing_cm=None,
                        plant_spacing_cm=None, edge_margin_cm=None,
                        bed_pitch_cm=None, rows_per_bed=None,
                        containers=None, markers=None, with_valves=None):
        from aot.aot_flask.geo import plot_context
        # with_dims=False 로 못 박는다 — 아래에서 `dimensions` 키로 직접 싣기
        # 때문이다(그쪽은 with_sensors 와 무관하게 **항상** 나가야 한다).
        # 기본값에 맡기면 with_sensors=True 일 때 같은 값이 `dims` 로 한 번 더
        # 실려, LLM 컨텍스트에 같은 것을 가리키는 이름이 둘이 된다.
        d = plot_context.to_dict(row, with_sensors=with_sensors,
                                     containers=containers, markers=markers,
                                     with_valves=with_valves, with_dims=False)
        # feature 전체(좌표 수백 개)는 LLM 컨텍스트에 실을 이유가 없다.
        d.pop('feature', None)
        d.pop('derived_feature', None)

        # 시설 구획은 치수도 식재량도 내지 않는다. 근거로 쓸 기하가 **시설
        # 외피**(파생)뿐인데다, 시설은 노지형(땅에 심고 온실만 씌운 것)·베드형·
        # 수직형에 따라 같은 바닥 면적의 재배 규모가 전혀 다르다. 면적에
        # 재식거리를 곱하면 형태에 따라 몇 배씩 틀린 숫자가 나오고, 틀렸다는
        # 표시가 어디에도 없다 — LLM 은 그 숫자를 그대로 사람에게 옮긴다.
        #
        # ⚠ `to_dict` 가 이미 같은 이유로 dims/valves 를 빼지만, 여기서
        # `dimensions`/`capacity_estimate` 를 **직접** 부르므로 그 방어를
        # 우회한다. 새 파생값을 여기 얹을 때도 이 분기를 먼저 볼 것.
        if not row.has_own_geometry():
            # 노지 구획의 `valves` 자리다. 시설 안에서는 밸브 하나가 아니라
            # 코디네이터가 환경을 맡으므로 그쪽을 낸다(읽기 전용).
            try:
                d['facility_control'] = \
                    plot_context.facility_control_for_plot(row)
            except Exception as exc:
                logger.warning("_plot_brief: 시설 제어 조회 실패: %s", exc)
            d['scale_unavailable'] = (
                "This plot lives in a facility, where floor area does not "
                "determine growing capacity (ground beds vs raised beds vs "
                "vertical racks differ several-fold). Read the plot notes for "
                "the actual layout (bed count, rows, tiers) instead of "
                "estimating from area.")
            return d

        # 면적 하나만 남기면 방향이 있는 질문("몇 줄 들어가나")에 답할 수
        # 없다. 좌표를 되살리는 대신 **계산된 요약 두 숫자**를 얹는다.
        dims = plot_context.dimensions(row)
        if dims:
            d['dimensions'] = dims
        # 두둑 배치는 컬럼으로 저장하지 않는다 — 확정된 배치는 구획 노트에
        # 남고(plot_context._FLAT_LAYOUT_ASK 참조), 그 노트가 다음 대화의
        # 컨텍스트에 실려 온다. 여기로는 숫자만 파라미터로 들어온다.
        cap = plot_context.capacity_estimate(
            dims, row_spacing_cm, plant_spacing_cm, edge_margin_cm,
            bed_pitch_cm, rows_per_bed)
        if cap:
            d['capacity_estimate'] = cap
        return d

    @staticmethod
    def list_programs(kind=None, subject=None, crop=None, tab_id=None, **extra):
        """[읽기전용] 관리 프로그램 목록 — 대상의 단계·기간 템플릿.

        `kind` 로 종류를 좁힌다: `vegetation`(식생) · `livestock`(가축) ·
        `facility`(시설물) · `other`. 식생 구획에 붙일 것을 찾는다면
        `kind='vegetation'` 이다.

        `tab_id` 로 Programs 화면의 특정 탭에 있는 것만 볼 수 있다(`list_tabs`
        로 먼저 탭 id를 확인).

        구획에 프로그램을 붙이면 단계·예상 수확일이 따라오므로, `create_plot`
        전에 여기서 골라 `program_uuid` 로 넘긴다. 새로 만들기 전에 **먼저 이
        목록을 본다** — 같은 작물의 프로그램이 이미 있으면 그것을 쓰거나 복제하는
        편이 낫다(지어낸 표가 하나 더 생기는 것을 막는다).
        """
        try:
            from aot.aot_flask.geo import program_io
            from aot.databases.models import GeoProgram

            want = (subject or crop or '').strip() or None
            q = GeoProgram.query
            if kind:
                q = q.filter(GeoProgram.kind == str(kind).strip())
            if want:
                q = q.filter(GeoProgram.subject == want)
            if tab_id:
                q = q.filter(GeoProgram.tab_id == str(tab_id).strip())
            rows = q.order_by(GeoProgram.subject.asc()).all()
            return {"status": "success", "count": len(rows),
                    "programs": [program_io.to_dict(r, with_stages=False)
                                 for r in rows]}
        except Exception as e:
            logger.exception("Error in list_programs")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_program(program_id=None, **extra):
        """[읽기전용] 프로그램 하나 — 단계 목록까지."""
        try:
            from aot.aot_flask.geo import program_io
            from aot.databases.models import GeoProgram

            if not program_id:
                return {"status": "error", "message": "program_id is required"}
            row = GeoProgram.query.filter_by(unique_id=program_id).first()
            if row is None:
                return {"status": "error", "message": "program not found"}
            return {"status": "success", "program": program_io.to_dict(row)}
        except Exception as e:
            logger.exception("Error in get_program")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def create_program(name=None, subject=None, crop=None, stages=None,
                            variety=None, source_note=None, notes=None,
                            kind=None, base_temp_c=None,
                            target_defs=None, resource_defs=None, tab_id=None,
                            **extra):
        """[쓰기] 관리 프로그램을 만든다. 사람 승인 필요.

        `kind` 는 대상 종류다(기본 `vegetation`). 식생만이 아니라 가축·시설물·
        도로도 같은 구조로 관리한다 — AoT 는 농장 전용이 아니다.

        `stages` 는 `[{key, name, days, targets, guidance}]` — `days` 는 **그
        단계의 길이**(누적이 아니다). 마지막 단계만 `days` 를 비울 수 있고
        (=끝까지), 중간에 비우면 그 뒤 단계가 시작되지 않아 서버가 거절한다.

        `targets` 는 `{항목키: 숫자}` 이고, **그 키는 `target_defs` 에 있어야
        한다.** 종류마다 고정 항목이 있고(식생: temp_day·temp_night·rh·co2·
        dli·vpd) 그것은 자동으로 들어가므로, 그 밖의 값을 목표로 삼고 싶을 때만
        `target_defs` 에 `{key, label, unit, measurement}` 를 더한다.
        `measurement` 는 센서가 쓰는 이름이어야 제어·센서와 이어진다(없으면
        표시·조언 전용).

        `guidance` 는 그 단계의 지침(자유 텍스트) — "육묘기엔 상토가 마르지 않게"
        같은 문장이다. **아는 것만 적는다**: 지어낸 지침은 사람이 그대로 따르고,
        틀렸을 때 근거를 되짚을 수 없다.

        ⚠ **목표값과 지침을 비워 두는 것은 정상이다.** 실제 시설이 모든 항목을
        재거나 제어하지 못하는 일이 흔하고, 근거 없는 숫자는 빈 칸보다 나쁘다.

        **`source_note` 에 근거를 적어야 한다**(어떤 재배 지침·자료에서 왔는가).
        단계 기간과 목표는 그럴듯하게 지어낼 수 있는 값이라, 근거가 없으면 나중에
        이 값을 고칠 사람이 판단할 재료가 없다.

        이렇게 만든 프로그램은 `source='ai'` 이고, **사람이 확인하기 전에는 제어에
        쓰이지 않는다**(화면의 "확인함으로 표시"). 표시·조언에는 바로 쓰인다.

        만들기 전에 `list_programs` 로 같은 작물의 프로그램이 있는지 먼저 볼 것.
        """
        try:
            from aot.aot_flask.geo import program_io

            if not (source_note or '').strip():
                return {"status": "error",
                        "message": ("source_note is required: state what this "
                                    "programme is based on (guideline, source, "
                                    "or observed cycle).")}
            payload = {
                'name': name, 'subject': subject or crop, 'variety': variety,
                'kind': kind or 'vegetation',
                'stages': stages, 'source_note': source_note, 'notes': notes,
                'tab_id': tab_id,
            }
            if base_temp_c is not None:
                # 기준온도는 `photosynthesis.T_base` 에 산다(FunctionCropPreset 과
                # 같은 키). AI 에게 그 중첩을 시키지 않고 평평한 이름으로 받는다.
                payload['photosynthesis'] = {'T_base': base_temp_c}
            if target_defs is not None:
                payload['target_defs'] = target_defs
            if resource_defs is not None:
                payload['resource_defs'] = resource_defs
            result, err = program_io.create_program(payload, source='ai')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "program": result,
                    "note": ("Created as an AI programme. It is used for display "
                             "and advice, but NOT for control until a person "
                             "marks it as checked.")}
        except Exception as e:
            logger.exception("Error in create_program")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def modify_program(program_id=None, **fields):
        """[쓰기] 프로그램의 이름·품종·단계·설명을 고치거나, 다른 탭으로 옮긴다.
        사람 승인 필요.

        **내장·외부 프로그램은 서버가 거절한다** — 업그레이드나 외부 갱신이 그
        수정을 덮어써 조용히 되돌아가기 때문이다. 고치려면 사람이 화면에서
        복제한 뒤 그 사본을 고친다. **단, `tab_id` 만 보내는 호출은 예외다** —
        탭 이동은 조직 정보일 뿐 내용이 아니라서, 내장·외부 프로그램도 옮길 수
        있다(`program_io.update_program` 참조).
        """
        try:
            from aot.aot_flask.geo import program_io

            if not program_id:
                return {"status": "error", "message": "program_id is required"}
            payload = {k: v for k, v in fields.items()
                       if k in ('name', 'variety', 'stages', 'notes',
                                'source_note', 'targets_methods', 'kind',
                                'photosynthesis', 'tab_id',
                                # 목표 항목 정의 — 어휘가 프로그램마다 다르므로
                                # AI 도 이것을 읽고 고칠 수 있어야 한다(고정
                                # 항목은 서버가 되돌려 놓으므로 지워지지 않는다).
                                'target_defs',
                                # 자원 역할 선언(P6). **함수 uuid 는 여기 없다** —
                                # 무엇이 그 일을 하는지는 현장이 푼다.
                                'resource_defs')
                       and v is not None}
            # 기준온도는 `photosynthesis.T_base` 에 산다(FunctionCropPreset 과
            # 같은 키). AI 에게 그 중첩을 시키지 않고 평평한 이름으로 받는다.
            if fields.get('base_temp_c') is not None:
                payload['photosynthesis'] = {'T_base': fields['base_temp_c']}
            if not payload:
                return {"status": "error", "message": "nothing to change"}
            # by='ai' — 제어에 닿는 내용(단계·목표 항목·광합성)을 고치면 서버가
            # 그 프로그램을 검토 대기로 되돌린다. 사람이 만든 껍데기를 AI 가
            # 채우는 흐름에서 게이트가 비어 있던 것을 막는다(program_io 참조).
            result, err = program_io.update_program(program_id, payload, by='ai')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "program": result,
                    "note": ("Saved. If stages, target items or the "
                             "photosynthesis constants changed, this programme "
                             "now needs a person to mark it as checked before "
                             "it is used for control again.")}
        except Exception as e:
            logger.exception("Error in modify_program")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def delete_program(program_id=None, **extra):
        """[쓰기] 프로그램을 삭제한다. 사람 승인 필요.

        **오기입 정정용이다.** `program_io.delete_program` 이 참조 무결성을
        지킨다 — 쓰는 구획이 하나라도 있으면 거절하고 몇 건인지 알려 준다.
        쓰던 구획에서 떼려면 `modify_plot` 으로 `program_uuid` 를 비운 뒤
        다시 시도한다.
        """
        try:
            from aot.aot_flask.geo import program_io

            if not program_id:
                return {"status": "error", "message": "program_id is required"}
            result, err = program_io.delete_program(program_id)
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "deleted": program_id}
        except Exception as e:
            logger.exception("Error in delete_program")
            return {"status": "error", "message": str(e)}

    # ── 대시보드 위젯 ────────────────────────────────────────────────────────
    # 위젯은 사람이 보는 화면의 구성 요소다. 여기 있는 도구들은 웹 UI 의
    # utils_dashboard.widget_add/mod/del 과 **같은 일**을 하되 Flask 폼을 거치지
    # 않는다 — 그 함수들은 WTForms 객체(form_base.name.data …)와 flash() 를
    # 전제로 쓰여 있어 폼 없이는 부를 수 없다. 그래서 저장 자체는 여기서 하고,
    # 위젯별 훅(execute_at_creation/modification/deletion)과 데몬 통지,
    # 템플릿 재생성처럼 **빠뜨리면 조용히 어긋나는 단계**만 그대로 따라간다.

    @staticmethod
    def _widget_catalog():
        from aot.utils.widgets import parse_widget_information
        return parse_widget_information()

    @staticmethod
    def _jsonable(value):
        """lazy_gettext 객체가 섞인 값을 JSON 직렬화 가능한 형태로 푼다.

        위젯 정의는 사람이 읽는 문구를 전부 `lazy_gettext` 로 감싸는데, 그
        객체는 `str` 의 하위 타입이 아니라 `json.dumps` 가 통째로 실패한다
        (`Object of type LazyString is not JSON serializable`). 그래서
        **필드마다 `str()` 을 손으로 붙이는 방식은 새 필드가 늘 때마다
        조용히 깨진다** — 실제로 `options_select` 가 그렇게 빠져서
        select 형 옵션을 가진 위젯(AoT_map·AoT_graph 등) 대부분에서
        `get_widget`/`list_widget_types` 가 응답을 만들지 못했다.

        중첩 구조를 그대로 유지한 채 lazy 객체만 문자열로 바꾼다. 튜플은
        JSON 에 없으므로 리스트가 된다.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [AoTDataToolService._jsonable(v) for v in value]
        if isinstance(value, dict):
            return {str(k): AoTDataToolService._jsonable(v)
                    for k, v in value.items()}
        return str(value)

    @staticmethod
    def _widget_option_schema(widget_info):
        """위젯 종류 하나의 옵션 스키마 — 사람이 읽을 수 있는 형태로.

        `name`/`phrase`/`options_select`/`default_value` 는 lazy_gettext
        객체를 담을 수 있어 그대로 JSON 으로 못 나간다 — `_jsonable` 을 지난다.
        """
        out = []
        for opt in (widget_info.get('custom_options') or []):
            if 'id' not in opt:
                continue
            entry = {
                'id': opt['id'],
                'type': opt.get('type'),
                'name': str(opt.get('name') or opt['id']),
            }
            if opt.get('phrase'):
                entry['phrase'] = str(opt['phrase'])
            if 'default_value' in opt:
                entry['default'] = AoTDataToolService._jsonable(
                    opt['default_value'])
            if opt.get('options_select'):
                entry['accepts'] = AoTDataToolService._jsonable(
                    opt['options_select'])
            out.append(entry)
        return out

    @staticmethod
    def _coerce_widget_options(widget_info, options):
        """AI 가 준 옵션을 스키마에 맞춰 거른다 → (정제된 dict, 오류 목록).

        **스키마에 없는 id 는 조용히 무시하지 않고 오류로 돌려준다.** 무시하면
        오타 하나가 "설정했다고 했는데 화면이 안 바뀐다" 로 나타나고, 그때
        원인이 위젯인지 도구인지 알 방법이 없다.

        값의 의미(그 장치가 실제로 있는지 등)까지는 보지 않는다 — 그것은 위젯
        자신의 훅이 판단할 몫이고, 여기서 흉내내면 두 벌이 되어 갈라진다.
        """
        schema = {opt['id']: opt for opt in (widget_info.get('custom_options') or [])
                  if 'id' in opt}
        clean, errors = {}, []
        for key, value in (options or {}).items():
            opt = schema.get(key)
            if opt is None:
                errors.append("unknown option '%s' for this widget type" % key)
                continue
            kind = opt.get('type')
            try:
                if kind == 'integer':
                    clean[key] = int(value)
                elif kind == 'float':
                    clean[key] = float(value)
                elif kind == 'bool':
                    clean[key] = bool(value)
                else:
                    # select_* / text / 그 밖 — 위젯이 문자열이나 목록으로 받는다.
                    clean[key] = value
            except (TypeError, ValueError):
                errors.append("option '%s' expects %s, got %r" % (key, kind, value))
        return clean, errors

    @staticmethod
    def _widget_brief(widget, widget_info=None):
        name = (widget.name or '').strip()
        out = {
            'widget_id': widget.unique_id,
            'name': name or None,
            'widget_type': widget.graph_type,
            'position': {'x': widget.position_x, 'y': widget.position_y,
                         'width': widget.width, 'height': widget.height},
        }
        if widget_info:
            out['type_name'] = str(widget_info.get('widget_name') or widget.graph_type)
        return out

    @staticmethod
    def _notify_daemon_widget(action, widget_id):
        """데몬에 위젯 변경을 알린다. 데몬이 없어도 저장은 유효하다.

        저장은 DB 에 끝났고 이 통지는 실행 중인 데몬의 캐시를 새로 고치는 것뿐
        이라, 실패를 저장 실패로 올리면 **성공한 작업을 실패로 보고**하게 된다.
        대신 무엇이 안 됐는지는 응답에 남긴다.
        """
        try:
            from aot.aot_client import DaemonControl
            control = DaemonControl()
            if action == 'remove':
                control.widget_remove(widget_id)
            else:
                control.widget_add_refresh(widget_id)
            return None
        except Exception as exc:
            logger.warning("[widget] 데몬 통지 실패(%s, %s): %s", action, widget_id, exc)
            return ("saved, but the running daemon could not be notified (%s) — "
                    "the dashboard may need a page reload to pick it up." % exc)

    @staticmethod
    def list_dashboards(tab_id=None, with_options=False, **extra):
        """[읽기전용] 대시보드 탭과 그 안의 위젯들.

        `custom_options` 는 기본으로 싣지 않는다 — 위젯 하나가 지도나 시설처럼
        큰 설정을 들고 있으면 목록 하나가 응답 상한을 넘길 수 있다. 하나를
        자세히 볼 때는 `get_widget` 을 쓴다.
        """
        try:
            import json
            from sqlalchemy import text
            from aot.databases.models import Dashboard, Widget

            catalog = AoTDataToolService._widget_catalog()
            # 대시보드 탭의 정본은 **Dashboard 테이블**이다. Widget.tab_id 의 FK
            # 선언은 tab.unique_id 를 가리키지만 실제로 담기는 값은 Dashboard 의
            # unique_id 이고, 화면(routes_dashboard.page_dashboard)도 Dashboard 를
            # 읽는다. FK 강제가 꺼져 있어 이 어긋남은 아무 에러도 내지 않는다 —
            # TabService.get_tabs_for_page('dashboard') 를 보면 **빈 목록**이
            # 돌아와 "대시보드가 하나도 없다" 로 읽힌다(실제로 겪었다).
            q = Dashboard.query.order_by(text("COALESCE(sort_order, 999999), id"))
            tabs = q.all()
            if tab_id:
                tabs = [t for t in tabs if t.unique_id == tab_id]
                if not tabs:
                    return {"status": "error",
                            "message": "no dashboard with id %s" % tab_id}

            out = []
            for tab in tabs:
                widgets = (Widget.query.filter(Widget.tab_id == tab.unique_id)
                           .order_by(Widget.position_y, Widget.position_x).all())
                entries = []
                for w in widgets:
                    brief = AoTDataToolService._widget_brief(
                        w, catalog.get(w.graph_type))
                    if w.graph_type not in catalog:
                        brief['warning'] = ('this widget type is not installed on '
                                            'this system — it will not render')
                    if with_options:
                        try:
                            brief['options'] = json.loads(w.custom_options or '{}')
                        except Exception:
                            brief['options'] = {}
                    entries.append(brief)
                entry = {'tab_id': tab.unique_id, 'name': tab.name,
                         'position': tab.sort_order,
                         'widget_count': len(entries), 'widgets': entries}
                if tab.locked:
                    entry['locked'] = True
                out.append(entry)
            return {"status": "success", "tabs": out}
        except Exception as e:
            logger.exception("Error in list_dashboards")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def list_widget_types(widget_type=None, **extra):
        """[읽기전용] 이 시스템에 설치된 위젯 종류.

        종류 이름만 아는 것으로는 `create_widget` 을 부를 수 없다 — 어떤 옵션을
        받는지가 종류마다 다르기 때문이다. 그래서 `widget_type` 을 주면 그 종류의
        **옵션 스키마**까지 낸다. 안 주면 목록만 낸다(전 종류의 스키마를 한 번에
        실으면 응답이 통째로 커진다).
        """
        try:
            catalog = AoTDataToolService._widget_catalog()
            if widget_type:
                info = catalog.get(widget_type)
                if not info:
                    return {"status": "error",
                            "message": "unknown widget type '%s'" % widget_type,
                            "available": sorted(catalog)}
                return {"status": "success", "widget_type": widget_type,
                        "name": str(info.get('widget_name') or widget_type),
                        "message": str(info.get('message') or '') or None,
                        "default_size": {"width": info.get('widget_width'),
                                         "height": info.get('widget_height')},
                        "options": AoTDataToolService._widget_option_schema(info)}
            return {"status": "success",
                    "types": [{"widget_type": key,
                               "name": str(info.get('widget_name') or key),
                               "option_count": len(info.get('custom_options') or [])}
                              for key, info in sorted(catalog.items())],
                    "next": ("call again with widget_type=<one of these> to get its "
                             "option schema before creating one")}
        except Exception as e:
            logger.exception("Error in list_widget_types")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_widget(widget_id=None, **extra):
        """[읽기전용] 위젯 하나 — 설정(custom_options) 포함."""
        try:
            import json
            from aot.databases.models import Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}

            catalog = AoTDataToolService._widget_catalog()
            info = catalog.get(w.graph_type)
            out = AoTDataToolService._widget_brief(w, info)
            try:
                out['options'] = json.loads(w.custom_options or '{}')
            except Exception:
                out['options'] = {}
            out['tab_id'] = w.tab_id
            if info:
                out['option_schema'] = AoTDataToolService._widget_option_schema(info)
            else:
                out['warning'] = ('this widget type is not installed on this system '
                                  '— it will not render')
            return {"status": "success", "widget": out}
        except Exception as e:
            logger.exception("Error in get_widget")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def create_widget(tab_id=None, widget_type=None, name=None, options=None,
                      width=None, height=None, **extra):
        """[쓰기] 대시보드 탭에 위젯을 추가한다. 사람 승인 필요."""
        try:
            import json
            from aot.databases.models import Dashboard, Widget
            from aot.aot_flask.utils.utils_general import custom_options_return_json

            if not tab_id or not widget_type:
                return {"status": "error",
                        "message": "tab_id and widget_type are required — call "
                                   "list_dashboards for tabs and list_widget_types "
                                   "for the types"}
            # 위 list_dashboards 주석 참조 — 대시보드 탭은 Dashboard 테이블이다.
            tab = Dashboard.query.filter(Dashboard.unique_id == tab_id).first()
            if not tab:
                return {"status": "error",
                        "message": "no dashboard with id %s" % tab_id}
            if tab.locked:
                return {"status": "error",
                        "message": "the dashboard '%s' is locked — the UI hides the "
                                   "add-widget control on a locked dashboard, so "
                                   "adding one here would bypass a deliberate "
                                   "choice. Ask the user to unlock it first."
                                   % tab.name}

            catalog = AoTDataToolService._widget_catalog()
            info = catalog.get(widget_type)
            if not info:
                return {"status": "error",
                        "message": "unknown widget type '%s'" % widget_type,
                        "available": sorted(catalog)}

            clean, errors = AoTDataToolService._coerce_widget_options(info, options)
            if errors:
                return {"status": "error", "message": "; ".join(errors),
                        "option_schema": AoTDataToolService._widget_option_schema(info)}

            # 기본 옵션은 위젯 자신의 스키마에서 만든다. 폼이 없을 때
            # custom_options_return_json 이 default_value/타입별 기본을 채운다 —
            # 여기서 빈 dict 로 시작하면 위젯이 없는 키를 읽고 렌더에서 죽는다.
            err, defaults_json = custom_options_return_json(
                [], catalog, None, device=widget_type, use_defaults=True)
            try:
                merged = json.loads(defaults_json)
            except Exception:
                merged = {}
            merged.update(clean)

            new_widget = Widget()
            new_widget.tab_id = tab_id
            new_widget.graph_type = widget_type
            new_widget.name = (name or '').strip() or str(
                info.get('widget_name') or widget_type)
            new_widget.width = int(width) if width else (info.get('widget_width') or 6)
            new_widget.height = int(height) if height else (info.get('widget_height') or 6)
            # 새 위젯은 그 탭의 맨 아래에. 기존 위젯 위에 겹쳐 놓으면 사람이
            # 지금 보고 있는 화면이 재배치된다.
            bottom = 0
            for each in Widget.query.filter(Widget.tab_id == tab_id).all():
                bottom = max(bottom, (each.position_y or 0) + (each.height or 0))
            new_widget.position_x = 0
            new_widget.position_y = bottom
            new_widget.custom_options = json.dumps(merged)

            creation_errors = []
            if 'execute_at_creation' in info:
                creation_errors, new_widget = info['execute_at_creation'](
                    creation_errors, new_widget, info)
                if creation_errors:
                    return {"status": "error",
                            "message": "; ".join(str(e) for e in creation_errors)}

            new_widget.save()

            # 그 종류가 이 시스템에 처음 놓인 위젯이면 Flask 가 아직 그 템플릿을
            # 모른다. 웹 UI 는 이때 재시작을 안내한다(reload_flask) — 여기서
            # 마음대로 재시작하면 화면을 보고 있는 사람의 세션이 끊기므로,
            # 사실만 알리고 결정은 사람에게 남긴다.
            first_of_type = Widget.query.filter(
                Widget.graph_type == widget_type).count() == 1

            warnings = []
            try:
                from aot.utils.widget_generate_html import generate_widget_html
                generate_widget_html()
            except Exception as exc:
                logger.warning("[widget] 템플릿 재생성 실패: %s", exc)
                warnings.append("widget template regeneration failed: %s" % exc)

            note = AoTDataToolService._notify_daemon_widget('refresh', new_widget.unique_id)
            if note:
                warnings.append(note)

            out = {"status": "success", "widget_id": new_widget.unique_id,
                   "name": new_widget.name, "widget_type": widget_type,
                   "tab_id": tab_id}
            if first_of_type:
                out["requires_restart"] = True
                out["restart_note"] = (
                    "This is the first widget of this type on this system, so the web "
                    "service must be restarted before it renders. Tell the user; do "
                    "not restart anything yourself.")
            if warnings:
                out["warnings"] = warnings
            return out
        except Exception as e:
            logger.exception("Error in create_widget")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def modify_widget(widget_id=None, name=None, options=None, width=None,
                      height=None, position_x=None, position_y=None,
                      tab_id=None, **extra):
        """[쓰기] 위젯의 이름·크기·위치·탭·설정을 바꾼다. 사람 승인 필요.

        준 것만 바꾼다 — 빠진 인자는 "비우라"가 아니라 "그대로 두라"다.
        """
        try:
            import json
            from aot.databases.models import Dashboard, Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}

            catalog = AoTDataToolService._widget_catalog()
            info = catalog.get(w.graph_type)
            changed = []

            # 잠금은 **레이아웃**을 지킨다 — 잠긴 대시보드에서 UI 는 이동·크기
            # 조정을 막는다(gs-no-move/gs-no-resize). 이름과 설정까지 막지는
            # 않으므로 여기서도 막지 않는다: 통째로 거부하면 잠가 둔 화면의
            # 값을 고치는 정상 작업이 함께 불가능해진다.
            if any(v is not None for v in (width, height, position_x, position_y)):
                board = Dashboard.query.filter(
                    Dashboard.unique_id == w.tab_id).first()
                if board is not None and board.locked:
                    return {"status": "error",
                            "message": "the dashboard '%s' is locked, so this "
                                       "widget's size and position cannot be "
                                       "changed. Its name and settings still can."
                                       % board.name}

            if name is not None:
                w.name = str(name).strip()
                changed.append('name')
            for attr, value in (('width', width), ('height', height),
                                ('position_x', position_x), ('position_y', position_y)):
                if value is not None:
                    try:
                        setattr(w, attr, int(value))
                    except (TypeError, ValueError):
                        return {"status": "error",
                                "message": "%s must be an integer" % attr}
                    changed.append(attr)

            if tab_id is not None and tab_id != w.tab_id:
                # 대시보드 탭은 Dashboard 테이블이다(list_dashboards 주석 참조).
                target = Dashboard.query.filter(Dashboard.unique_id == tab_id).first()
                if not target:
                    return {"status": "error",
                            "message": "no dashboard with id %s" % tab_id}
                if target.locked:
                    return {"status": "error",
                            "message": "the target dashboard '%s' is locked"
                                       % target.name}
                w.tab_id = tab_id
                changed.append('tab_id')

            if options:
                if not info:
                    return {"status": "error",
                            "message": "widget type '%s' is not installed here, so "
                                       "its options cannot be validated" % w.graph_type}
                clean, errors = AoTDataToolService._coerce_widget_options(info, options)
                if errors:
                    return {"status": "error", "message": "; ".join(errors),
                            "option_schema": AoTDataToolService._widget_option_schema(info)}
                try:
                    current = json.loads(w.custom_options or '{}')
                except Exception:
                    current = {}
                new_options = dict(current)
                new_options.update(clean)

                # 위젯이 자기 훅을 갖고 있으면 그것을 지나야 한다 — 웹 UI 의 AJAX
                # 저장 경로(save_widget_custom_options)와 같은 계약이다. 건너뛰면
                # 필드 매핑이나 파생값이 빠진 채 저장돼, 저장은 됐는데 화면은
                # 다르게 나오는 상태가 된다.
                if 'execute_at_modification' in info:
                    (allow, _page_refresh, w, final) = info['execute_at_modification'](
                        w, None, current, new_options)
                    if not allow:
                        return {"status": "error",
                                "message": "the widget rejected this change "
                                           "(execute_at_modification)"}
                    new_options = final
                w.custom_options = json.dumps(new_options)
                changed.append('options')

            if not changed:
                return {"status": "error",
                        "message": "nothing to change — pass at least one of name, "
                                   "options, width, height, position_x, position_y, "
                                   "tab_id"}

            db.session.commit()
            out = {"status": "success", "widget_id": widget_id, "changed": changed}
            note = AoTDataToolService._notify_daemon_widget('refresh', widget_id)
            if note:
                out["warnings"] = [note]
            return out
        except Exception as e:
            logger.exception("Error in modify_widget")
            db.session.rollback()
            return {"status": "error", "message": str(e)}

    @staticmethod
    def delete_widget(widget_id=None, **extra):
        """[쓰기] 위젯을 대시보드에서 지운다. 사람 승인 필요."""
        try:
            from aot.databases.models import Widget

            if not widget_id:
                return {"status": "error", "message": "widget_id is required"}
            w = Widget.query.filter(Widget.unique_id == widget_id).first()
            if not w:
                return {"status": "error", "message": "no widget with id %s" % widget_id}

            removed = AoTDataToolService._widget_brief(w)
            catalog = AoTDataToolService._widget_catalog()
            info = catalog.get(w.graph_type)

            # 위젯이 자기 뒷정리를 갖고 있으면 먼저 부른다(웹 UI 와 같은 순서).
            # 행을 지운 뒤에 부르면 훅이 참조할 대상이 이미 없다.
            warnings = []
            if info and 'execute_at_deletion' in info:
                try:
                    info['execute_at_deletion'](widget_id)
                except Exception as exc:
                    logger.warning("[widget] execute_at_deletion 실패: %s", exc)
                    warnings.append("the widget's own cleanup failed: %s" % exc)

            db.session.delete(w)
            db.session.commit()

            note = AoTDataToolService._notify_daemon_widget('remove', widget_id)
            if note:
                warnings.append(note)
            out = {"status": "success", "deleted": removed}
            if warnings:
                out["warnings"] = warnings
            return out
        except Exception as e:
            logger.exception("Error in delete_widget")
            db.session.rollback()
            return {"status": "error", "message": str(e)}

    @staticmethod
    def list_tabs(page_type=None, **extra):
        """[읽기전용] 탭 목록 — Dashboard/Input/Output/Function/Programs 화면이
        공유하는 같은 탭 인프라(`TabService`)를 그대로 쓴다."""
        try:
            from aot.services.tab_service import TabService, TAB_PAGE_TYPES

            if page_type not in TAB_PAGE_TYPES:
                return {"status": "error",
                        "message": "page_type must be one of %s" % (TAB_PAGE_TYPES,)}
            tabs = TabService.get_tabs_for_page(page_type)
            return {"status": "success",
                    "tabs": [{"unique_id": t.unique_id, "name": t.name,
                             "position": t.position} for t in tabs]}
        except Exception as e:
            logger.exception("Error in list_tabs")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def create_tab(page_type=None, name=None, **extra):
        """[쓰기] 새 탭을 만든다. 사람 승인 필요."""
        try:
            from aot.services.tab_service import TabService, TAB_PAGE_TYPES

            if page_type not in TAB_PAGE_TYPES:
                return {"status": "error",
                        "message": "page_type must be one of %s" % (TAB_PAGE_TYPES,)}
            tab = TabService.create_tab(page_type, name)
            if not tab:
                return {"status": "error", "message": "tab creation failed"}
            return {"status": "success", "tab_id": tab.unique_id, "name": tab.name}
        except Exception as e:
            logger.exception("Error in create_tab")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def modify_tab(tab_id=None, name=None, **extra):
        """[쓰기] 탭 이름을 바꾼다. 사람 승인 필요."""
        try:
            from aot.services.tab_service import TabService

            if not tab_id or not (name or '').strip():
                return {"status": "error",
                        "message": "tab_id and name are required"}
            ok = TabService.rename_tab(tab_id, name)
            if not ok:
                return {"status": "error", "message": "rename failed — tab not found?"}
            return {"status": "success", "tab_id": tab_id, "name": name}
        except Exception as e:
            logger.exception("Error in modify_tab")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def delete_tab(tab_id=None, **extra):
        """[쓰기] 탭을 삭제한다. 사람 승인 필요.

        Input/Output/Function 은 소속 카드까지 함께 삭제된다(UI와 동일). Programs
        는 예외 — 소속 프로그램은 다른 구획이 계속 참조할 수 있어 지우지 않고
        기본 탭으로 옮겨진다. 마지막 남은 탭은 지울 수 없다.
        """
        try:
            from aot.services.tab_service import TabService

            if not tab_id:
                return {"status": "error", "message": "tab_id is required"}
            result = TabService.delete_tab(tab_id)
            if not result.get('success'):
                return {"status": "error", "message": result.get('message')}
            return {"status": "success", "deleted": tab_id}
        except Exception as e:
            logger.exception("Error in delete_tab")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def list_plots(map_id=None, include_ended=False, on=None,
                       with_sensors=False, **extra):
        """[읽기전용] 식생 구획(작기) 목록 — 어디에 무엇이 심겨 있는가.

        기본은 **재배 중인 것만**. `include_ended=True` 면 종료된 작기까지
        준다(연작 판단용). `on='YYYY-MM-DD'` 로 과거 시점을 물을 수 있다.

        `with_sensors=True` 면 구획마다 참조 센서(`in_plot`/`from_zone`/
        `source`)를 함께 낸다. 밸브 교차는 **포함하지 않는다** — 그쪽이 비용의
        대부분이고(실측 구획 8개: 센서 37 쿼리 · 밸브 120 쿼리) 목록에서 필요한
        일이 드물다. 밸브가 필요하면 그 구획 하나만 `get_plot` 으로 본다.
        """
        try:
            from datetime import datetime
            from aot.databases.models import GeoPlot
            from aot.aot_flask.geo import plot_context

            as_of = None
            if on:
                try:
                    as_of = datetime.strptime(str(on)[:10], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    return {"error": "on must be YYYY-MM-DD"}

            if include_ended:
                q = GeoPlot.query
                if map_id:
                    q = q.filter_by(geo_id=map_id)
                rows = q.order_by(GeoPlot.started_on.desc()).all()
            elif map_id:
                rows = plot_context.active_plots(map_id, on=as_of)
            else:
                # 지도를 안 주면 전 지도의 활성 구획을 모은다.
                from aot.databases.models import GeoMap
                rows = []
                for m in GeoMap.query.all():
                    rows.extend(plot_context.active_plots(m.unique_id, on=as_of))

            # 지도 단위 사전 로드. 구획마다 컨테이너·마커를 다시 읽으면 구획
            # 수만큼 전량 스캔이 반복된다 — 센서를 넣기 전부터 있던 N+1 이라,
            # 여기서 캐시하지 않고 with_sensors 만 열면 오히려 더 나빠진다.
            from aot.aot_flask.geo import device_membership as _dm
            _containers, _markers = {}, {}

            def _cached(m_uuid):
                if m_uuid not in _containers:
                    _containers[m_uuid] = _dm.load_containers(m_uuid)
                    _markers[m_uuid] = (_dm.load_markers(m_uuid)
                                        if with_sensors else None)
                return _containers[m_uuid], _markers[m_uuid]

            items = []
            for r in rows:
                _c, _mk = _cached(r.geo_id)
                items.append(AoTDataToolService._plot_brief(
                    r, with_sensors=with_sensors, with_valves=False,
                    containers=_c, markers=_mk))
            out = {"count": len(items), "plots": items,
                   "note": ("Only plots currently growing are listed. "
                            "Pass include_ended=true for history.")
                           if not include_ended else None}
            # get_plot 과 같은 규칙이되, 목록에서 실제로 걸리는 것만 싣는다.
            notes = []
            if with_sensors and any(
                    (p.get('sensors') or {}).get('source') == 'zone' for p in items):
                notes.append(
                    "Some plots here read their ZONE's representative values, not "
                    "sensors inside the plot (sensors.source='zone'). Say so for "
                    "those plots when you report a number.")
            if any((p.get('stage') or {}).get('guidance') for p in items):
                notes.append(
                    "'stage.guidance' is what THAT plot's programme says to do in "
                    "its current stage. Quote it; do not replace it with generic "
                    "crop advice.")
            elif items:
                # 지침이 하나도 없을 때야말로 지어내기 쉽다 — 그 자리에서 말한다.
                notes.append(
                    "No plot here has programme guidance for its current stage "
                    "('stage.guidance' is null throughout). Saying so is the "
                    "honest answer; do not present generic crop advice as if it "
                    "came from the programme.")
            if notes:
                out["_reading"] = notes
            return out
        except Exception as e:
            logger.exception("Error in list_plots")
            return {"error": str(e)}

    @staticmethod
    def get_plot(plot_id=None, row_spacing_cm=None,
                     plant_spacing_cm=None, edge_margin_cm=None,
                     bed_pitch_cm=None, rows_per_bed=None, **extra):
        """[읽기전용] 구획 하나의 상세 — 작물·기간·면적·치수 + 참조 센서 출처.

        간격 두 개를 주면 `capacity_estimate`(줄 수·그루 수)까지 센다.
        `edge_margin_cm` 은 농기계 선회 공간 같은 여백을 추가로 빼고,
        `bed_pitch_cm`(고랑 포함 간격)+`rows_per_bed` 는 두둑 배치로 세게 한다
        (두둑 개수까지 낸다). 배치를 모르면 평평하게 깐 것으로 계산하되 응답의
        `capacity_estimate.ask_user` 가 배치를 확정해 **구획 노트로 남기라고**
        시킨다 — 컬럼으로 저장하지 않는 이유는 plot_context 의 주석 참조.

        조건을 한쪽만 주면 계산이 성립하지 않으므로 조용히 넘기지 않고 오류로
        말한다 — 사용자가 말한 조건이 답에 반영되지 않은 것을 아무도 모르는
        상태가 최악이다.

        ## `stage.guidance` — 실려 있다는 것과 닿는다는 것은 다르다

        응답의 `stage` 는 `plot_context._stage_payload` 가 만들고 그 안에
        `guidance`(이 단계의 지침)가 들어 있다. **payload 에 있는 것만으로는
        LLM 이 쓰지 않는다** — 도구 설명에 없는 필드는 모델이 존재를 모르거나,
        알아도 일반 재배 지식보다 우선할 이유를 모른다.

        2026-08-25: 그래서 규칙을 없앤 것이 아니라 **자리를 옮겼다.** 예전에는
        `tool_registry` 설명 문자열에 있었는데, 그 설명은 `get_plot` 을 부르지
        않는 대화까지 포함해 매번 실린다(core 27개 설명이 고정비의 74%였고 그중
        get_plot 이 가장 컸다 — 1,492자 중 91%가 결과 읽는 법이었다). 이제
        `_plot_reading_notes` 가 이 응답에 해당하는 규칙만 골라 `_reading` 으로
        함께 보낸다.

        위 경고는 여전히 유효하므로 **설명에 한 줄 포인터를 남겼다** — "응답의
        `_reading` 을 따르라". 그 한 줄까지 지우면 이 주석이 적어 둔 실패로
        그대로 돌아간다. 지우지 말 것.
        """
        try:
            from aot.databases.models import GeoPlot
            if not plot_id:
                return {"error": "plot_id is required"}
            row = GeoPlot.query.filter_by(unique_id=plot_id).first()
            if row is None:
                return {"error": f"plot not found: {plot_id}"}
            try:
                brief = AoTDataToolService._plot_brief(
                    row, with_sensors=True,
                    row_spacing_cm=row_spacing_cm,
                    plant_spacing_cm=plant_spacing_cm,
                    edge_margin_cm=edge_margin_cm,
                    bed_pitch_cm=bed_pitch_cm,
                    rows_per_bed=rows_per_bed)
            except ValueError as ve:
                return {"error": str(ve)}
            _check = AoTDataToolService._stage_target_check(brief)
            if _check:
                brief['target_check'] = _check
            return {"plot": brief,
                    "_reading": AoTDataToolService._plot_reading_notes(brief)}
        except Exception as e:
            logger.exception("Error in get_plot")
            return {"error": str(e)}

    # @ANCHOR: STAGE_TARGET_CHECK
    # 프로그램의 **이 단계 목표값**과 구획의 **현재 실측값**을 나란히 놓는다.
    #
    # 왜. "이 구획이 이 작물에 얼마나 적합한가" 는 실사용에서 반복해서 물어본
    # 질문인데(2026-08-26), 답이 늘 현재 센서값 나열이었다 — 목표가 옆에 없으니
    # 모델이 판단할 근거가 없어 값만 읽고 만다. 필요한 것은 둘 다 있었다:
    # 프로그램의 target_defs 가 무엇을 재는지(measurement)를, 단계의 targets 가
    # 그 숫자를 갖고 있다. 이어 붙이지 않았을 뿐이다.
    #
    # **판정을 지어내지 않는다.** targets 는 단일 수치(예: temp_day=26.0)이고
    # 허용폭이 어디에도 없다. '적정/높음' 을 매기려면 폭을 발명해야 하는데,
    # 그러면 근거 없는 숫자가 조언이 된다. 목표·현재·차이만 내고 판단은
    # 사람과 모델에게 남긴다 — "26도 목표에 현재 24.2도, 1.8도 낮음" 이면
    # "얼마나 적합한가" 에 이미 답이 된다.
    #
    # 목표값이 없는 프로그램에서는 조용히 비우지 않고 그 사실을 말한다. 그것은
    # 내부 사정이 아니라 **그 사람의 프로그램에 아직 안 채워진 칸**이고, 채우면
    # 답이 좋아지는 행동 가능한 정보다.
    @staticmethod
    def _stage_target_check(brief):
        stage = (brief or {}).get('stage') or {}
        targets = stage.get('targets')

        # plot_context._effective_targets 가 곡선 → 단계값 → 프로그램 기본값
        # 순으로 이미 해석해 준다. 그 결과를 쓴다(원본 dict 형태도 받아 둔다).
        items = []
        if isinstance(targets, list):
            items = [t for t in targets if isinstance(t, dict)]
        elif isinstance(targets, dict):
            defs = {d.get('key'): d
                    for d in (((brief or {}).get('program') or {}).get('target_defs') or [])
                    if isinstance(d, dict) and d.get('key')}
            for k, v in targets.items():
                d = defs.get(k) or {}
                items.append({'key': k, 'label': d.get('label') or k,
                              'unit': d.get('unit') or '',
                              'measurement': d.get('measurement') or k,
                              'when': d.get('when'), 'value': v, 'source': 'stage'})

        if not items:
            if (brief or {}).get('program'):
                return {'state': 'no_targets',
                        'note': ("This programme has no target values for the current "
                                 "stage, so there is nothing to compare the readings "
                                 "against. Say so plainly and offer that filling them "
                                 "in on the programme would make this answerable.")}
            return None

        # 지금이 낮인가. 주/야 목표를 가르는 데만 쓴다.
        is_day = None
        try:
            from aot.utils.solar import is_daytime
            is_day = is_daytime(target_id=(brief or {}).get('unique_id'))
        except Exception as e:
            logger.debug("[StageTargetCheck] daylight unknown: %s", e)

        sensors = (brief or {}).get('sensors') or {}
        current = AoTDataToolService._latest_by_measurement(
            sensors.get('in_plot') or [], sensors.get('from_zone') or [])

        rows, no_reading, curves, off_period, unmeasurable = [], [], [], [], []
        for t in items:
            label = t.get('label') or t.get('key')
            unit = t.get('unit') or ''

            # 센서로 잴 수 없다고 선언된 항목(CO2·DLI 등)은 대조 대상이 아니다.
            # '측정값 없음' 으로 보고하면 없는 문제를 만든다.
            if t.get('observable') is False:
                unmeasurable.append(label)
                continue

            # 곡선을 따르는 항목은 **숫자가 없다**(plot_context 가 값을 비운다 —
            # 곡선의 '지금 값' 은 메서드마다 계산이 달라 그쪽에서 못 구한다).
            # 조용히 빠뜨리면 목표가 없는 것처럼 보인다. 곡선을 따른다고 말한다.
            if t.get('source') == 'method' or (t.get('value') is None and t.get('method_uuid')):
                curves.append({'label': label,
                               'curve': t.get('method_name') or '(이름 없음)'})
                continue
            if t.get('value') is None:
                continue

            # 주간 목표를 밤에, 야간 목표를 낮에 견주면 없는 문제가 생긴다
            # (실측: 야간 12도 목표를 한낮 실측과 비교해 24도 차이가 났다).
            when = t.get('when')
            if when in ('day', 'night') and is_day is not None:
                if (when == 'day') != bool(is_day):
                    off_period.append({'label': label, 'target': t['value'],
                                       'unit': unit, 'applies': when})
                    continue

            meas = str(t.get('measurement') or t.get('key')).strip().lower()
            got = current.get(meas)
            if got is None:
                no_reading.append(label)
                continue
            row = {'key': t.get('key'), 'label': label, 'target': t['value'],
                   'unit': unit, 'current': got['value'],
                   # **어느 센서인가를 반드시 함께 낸다.** 실측에서 공기 온도
                   # 목표가 토양 센서 값과 비교됐다 — 측정 이름이 둘 다
                   # 'temperature' 라 이름만으로는 갈리지 않는다. 사람이 보고
                   # 판단할 수 있게 출처를 밝힌다.
                   'sensor': got.get('sensor'), 'measured_at': got.get('at')}
            if got.get('others'):
                row['other_sensors'] = got['others']
            try:
                row['delta'] = round(float(got['value']) - float(t['value']), 2)
            except (TypeError, ValueError):
                pass
            rows.append(row)

        out = {'state': 'compared' if rows else 'no_readings',
               'stage': stage.get('name'), 'rows': rows}
        if curves:
            out['follows_curve'] = curves
        if off_period:
            out['not_this_period'] = off_period
            out['now'] = 'day' if is_day else 'night'
        if unmeasurable:
            out['not_measurable_here'] = unmeasurable
        if no_reading:
            out['no_reading_for'] = no_reading
        out['note'] = ("target vs current for THIS stage. 'delta' is current minus "
                       "target. There is no tolerance band in the data — do NOT invent "
                       "one. Check 'sensor' before trusting a row: several sensors can "
                       "report the same measurement (air vs soil temperature), and "
                       "'other_sensors' lists the rest. 'not_this_period' targets do "
                       "not apply right now; 'follows_curve' targets track a curve, "
                       "not a fixed number.")
        return out

    @staticmethod
    def _latest_by_measurement(in_plot_ids, zone_ids=None):
        """측정 종류별 최신값 — {measurement: {'value','at','sensor','others'}}.

        구획 안 센서를 구역 폴백보다 **먼저** 본다(sensors_for_plot 의 우선순위와
        같다). 평균을 내지 않는 이유는 구획 안 센서와 구역 대표 센서가 섞이면
        평균이 어느 쪽도 아닌 값이 되기 때문이고, 같은 측정을 여러 센서가
        재면 나머지를 `others` 로 함께 낸다 — 실측에서 공기 온도 목표가 토양
        센서 값과 비교됐다. 어느 센서인지 보이지 않으면 그것을 알 길이 없다.
        """
        out = {}
        try:
            from aot.databases.models import Conversion, DeviceMeasurements, Input
            from aot.utils.influx import read_influxdb_list
            from aot.utils.system_pi import return_measurement_info

            ordered = list(in_plot_ids or []) + [d for d in (zone_ids or [])
                                                 if d not in set(in_plot_ids or [])]
            if not ordered:
                return out
            rank = {d: n for n, d in enumerate(ordered)}
            names = {i.unique_id: i.name for i in Input.query.filter(
                Input.unique_id.in_(ordered)).all()}

            found = {}
            for m in DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id.in_(ordered)).all():
                conv = (Conversion.query.filter(
                    Conversion.unique_id == m.conversion_id).first()
                    if m.conversion_id else None)
                channel, unit, meas = return_measurement_info(m, conv)
                if not unit or not meas:
                    continue
                rows = read_influxdb_list(m.device_id, unit, channel, measure=meas,
                                          duration_sec=3600, datetime_obj=True)
                if not rows or rows[-1][1] is None:
                    continue
                found.setdefault(str(meas).strip().lower(), []).append({
                    'value': rows[-1][1], 'at': str(rows[-1][0]),
                    'sensor': names.get(m.device_id, m.device_id),
                    '_rank': rank.get(m.device_id, 99)})

            for meas, cands in found.items():
                cands.sort(key=lambda c: c['_rank'])
                best = cands[0]
                out[meas] = {'value': best['value'], 'at': best['at'],
                             'sensor': best['sensor']}
                rest = [{'sensor': c['sensor'], 'value': c['value']} for c in cands[1:]]
                if rest:
                    out[meas]['others'] = rest
        except Exception as e:
            logger.debug("[StageTargetCheck] latest values unavailable: %s", e)
        return out

    @staticmethod
    def _plot_reading_notes(brief):
        """이 응답에 **실제로 해당되는** 읽기 규칙만 고른다.

        규칙 자체는 새로 만든 것이 아니다. 도구 설명에 붙어 있던 것을 이리로
        옮겼다 — 설명에 있으면 `get_plot` 을 부르지 않는 대화까지 전부 그 값을
        치르는데, 규칙이 쓸모 있는 것은 이 응답을 받은 순간뿐이다.

        **조건을 걸어 고르는 것이 요점이다.** 설명은 모든 경우를 한꺼번에
        말해야 하지만(부를지도 모르는 모든 호출을 상대하므로) 여기서는 이번
        응답이 실제로 어떤지 안다. 센서가 구획 안에서 왔으면 구역 대표값
        경고는 실을 이유가 없다. 그래서 옮기는 것만으로 분량이 줄고, 남은
        줄은 전부 이 응답에 해당한다.
        """
        notes = []
        sensors = brief.get('sensors') or {}
        if sensors.get('source') == 'zone':
            notes.append(
                "'sensors' are the zone's representative values, NOT measured "
                "inside this plot (sensors.source='zone'). Say so whenever you "
                "report one of these numbers.")

        # 목표 대조가 실렸으면 그것으로 답하라고 말한다. 실려 있다는 것과
        # 닿는다는 것은 다르다 — stage.guidance 가 같은 이유로 이 자리에 있다.
        _tc = brief.get('target_check') or {}
        if _tc.get('state') == 'compared':
            notes.append(
                "'target_check' already pairs THIS stage's target with the current "
                "reading and gives the gap ('delta'). When asked whether the place "
                "suits the crop, or how it is doing, answer FROM THAT — do not list "
                "raw sensor values instead. There is no tolerance band in the data, "
                "so report the gap; do not invent 'good/bad' thresholds.")
        elif _tc.get('state') == 'no_targets':
            notes.append(
                "'target_check' says this programme has no target values for the "
                "current stage. That is why suitability cannot be judged — say that, "
                "and that filling them in on the programme would make it answerable.")

        stage = brief.get('stage') or {}
        if stage:
            if stage.get('guidance'):
                notes.append(
                    "'stage.guidance' is what THIS programme says to do in the "
                    "current stage. Quote it; do not replace it with generic "
                    "crop advice.")
            else:
                notes.append(
                    "'stage.guidance' is null — nobody wrote guidance for this "
                    "stage. Saying so is the honest answer. Do not present "
                    "generic crop advice as if it came from the programme.")

        cap = brief.get('capacity_estimate') or {}
        if cap:
            # basis·ask_user 는 이미 응답 안에 전문이 있다. 여기서는 그것을
            # 그냥 지나치지 말라고만 한다 — 본문을 되풀이하면 옮긴 의미가 없다.
            line = ("'capacity_estimate' is approximate — read its 'basis' "
                    "and pass the caveat on.")
            if (brief.get('dimensions') or {}).get('shape_note'):
                line += " 'dimensions.shape_note' also applies."
            notes.append(line)
            if cap.get('ask_user'):
                notes.append(
                    "'capacity_estimate.ask_user' is an instruction, not a "
                    "remark. Follow it BEFORE reporting any plant count.")

        if any(v.get('unassigned') for v in (brief.get('valves') or [])):
            notes.append(
                "Some ground in this plot has no irrigation valve assigned "
                "(valves[].unassigned=true) — it cannot be watered yet.")

        if brief.get('scale_unavailable'):
            notes.append(
                "'scale_unavailable' applies — do not estimate capacity from "
                "floor area for this plot.")
        return notes

    @staticmethod
    def get_plot_history(plot_id=None, zone_id=None, map_id=None, **extra):
        """[읽기전용] 이 자리에 무엇이 있었나 — 연작 장해·윤작 판단의 근거.

        기준은 구획(`plot_id`) 또는 구역(`zone_id`)의 기하이고, 그와 면적이
        겹치는 작기를 지난 것까지 전부 돌려준다.
        """
        try:
            from aot.databases.models import GeoPlot, GeoShape
            from aot.aot_flask.geo import plot_context

            geom, geo_id = None, map_id
            if plot_id:
                src = GeoPlot.query.filter_by(unique_id=plot_id).first()
                if src is None:
                    return {"error": f"plot not found: {plot_id}"}
                geom, geo_id = plot_context.geometry_of(src), src.geo_id
            elif zone_id:
                z = GeoShape.query.filter_by(unique_id=zone_id).first()
                if z is None:
                    return {"error": f"zone not found: {zone_id}"}
                geom, geo_id = plot_context.geometry_of(z), z.geo_id
            else:
                return {"error": "plot_id or zone_id is required"}

            pairs = plot_context.plots_overlapping(geo_id, geom)
            items = []
            for row, overlap in pairs:
                d = AoTDataToolService._plot_brief(row)
                d['overlap_m2'] = round(overlap, 1)
                items.append(d)
            return {"count": len(items), "history": items}
        except Exception as e:
            logger.exception("Error in get_plot_history")
            return {"error": str(e)}

    @staticmethod
    def create_plot(map_id=None, geometry=None, zone_id=None, subject=None,
                        started_on=None, variety=None, name=None,
                        expected_end_on=None, color=None,
                        facility_id=None, bay_id=None, program_id=None,
                        kind=None, **extra):
        """[쓰기] 식생 구획을 만든다. 사람 승인 필요.

        위치는 셋 중 하나로 준다.

        - `facility_id`(+`bay_id`) — **온실 안**이다. 기하를 만들지 않는다.
          시설 구획은 위치의 정본이 구역 자체이기 때문이다("3동에 토마토").
          `bay_id` 는 `get_map_equipment`/`get_facility_capacity` 가 내는 구역
          id('bay_3' | 'bay_3_5')를 그대로 쓴다. 단동 시설은 비워 두면 서버가
          채운다. 다동에서 비우면 "시설 전체" 라는 뜻이다.
        - `zone_id` — **그 구역(또는 대지) 전체에 심었다.** 서버가 그 도형의
          기하를 복사한다. 좌표를 하나도 만들 필요가 없다.
        - `geometry` — GeoJSON Polygon/MultiPolygon 을 직접.

        **`zone_id` 를 먼저 쓸 것.** LLM 은 구역이 지도 어디에 있는지 알 방법이
        없다(어떤 도구도 구역 경계 폴리곤을 내주지 않는다). 좌표를 지어내면
        엉뚱한 자리에 저장되고, 그것은 실패했다고 말해주지도 않는다 — 구역
        밖이면 `zone_uuid` 가 null 로 남을 뿐이다.

        구역의 **일부**에만 심는 경우는 여기서 만들지 말 것. 지도 설계 화면에서
        그리거나, 지난 작기가 있으면 `copy_plot` 을 쓴다.

        상위 zone 은 받아도 저장하지 않는다 — 읽을 때 공간 포함으로 파생한다.
        여기서 `zone_id` 는 **기하의 출처**일 뿐 소속이 아니다.

        `program_id` 를 주면 관리 프로그램을 붙인다 — 단계·예상 종료일이 거기서
        따라온다(`list_programs` 로 `kind='vegetation'` 인 것을 먼저 고른다).
        """
        try:
            from aot.aot_flask.geo import plot_io, plot_context
            from aot.databases.models import GeoShape

            if geometry and zone_id:
                return {"status": "error",
                        "message": "give either geometry or zone_id, not both"}
            if facility_id and (geometry or zone_id):
                return {"status": "error",
                        "message": ("give either facility_id or a geometry "
                                    "source (zone_id/geometry), not both. A "
                                    "facility plot's location is the bay itself.")}
            source_kind = 'drawn'
            source_ref = None

            # 시설 구획 — 기하 없이 부모만으로 만든다.
            if facility_id:
                result, err = plot_io.save_plot({
                    'map_uuid': map_id,
                    'facility_uuid': facility_id, 'bay_id': bay_id,
                    'subject': subject, 'variety': variety, 'name': name,
                    'kind': kind or 'vegetation',
                    'started_on': started_on,
                    'expected_end_on': expected_end_on, 'color': color,
                    'program_uuid': program_id,
                })
                if err:
                    return {"status": "error", "message": err}
                result.pop('feature', None)
                result.pop('derived_feature', None)
                return {"status": "success", "plot": result}
            if zone_id:
                shape = GeoShape.query.filter_by(unique_id=zone_id).first()
                if shape is None:
                    return {"status": "error",
                            "message": f"zone/shape not found: {zone_id}"}
                geometry = plot_context.geometry_of(shape)
                if not geometry:
                    return {"status": "error",
                            "message": f"shape {zone_id} has no polygon to copy"}
                map_id = map_id or shape.geo_id
                # bay 스냅샷과 같은 이유로 **복사**다: zone 도형이 나중에 바뀌어도
                # 과거 작기의 기하가 따라가면 "여기 뭐가 있었나" 의 답이 조용히
                # 달라진다. 출처만 남긴다.
                source_kind = 'copied'
                source_ref = zone_id
            if not geometry:
                return {"status": "error",
                        "message": ("facility_id, zone_id or geometry is "
                                    "required. Inside a greenhouse use "
                                    "facility_id; outdoors prefer zone_id — you "
                                    "cannot know where a zone is on the map, so "
                                    "invented coordinates land in the wrong "
                                    "place silently.")}
            result, err = plot_io.save_plot({
                'map_uuid': map_id,
                'feature': {'type': 'Feature', 'properties': {},
                            'geometry': geometry},
                'subject': subject, 'variety': variety, 'name': name,
                'started_on': started_on, 'expected_end_on': expected_end_on,
                'color': color, 'program_uuid': program_id,
                'source_kind': source_kind, 'source_ref': source_ref,
            })
            if err:
                return {"status": "error", "message": err}
            result.pop('feature', None)
            return {"status": "success", "plot": result}
        except Exception as e:
            logger.exception("Error in create_plot")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def modify_plot(plot_id=None, **fields):
        """[쓰기] 구획의 작물·품종·이름·기간·색·두둑 규격을 고친다. 사람 승인 필요.

        기하는 여기서 바꾸지 않는다(도형 편집은 geo/design). 종료된 작기의
        기하 수정은 서버가 거부한다(VP-6).

        `program_uuid` 로 관리 프로그램을 붙이거나 바꿀 수 있다(단계·예상 종료일이
        거기서 따라온다). 빈 문자열을 주면 프로그램을 뗀다.
        """
        try:
            from aot.aot_flask.geo import plot_io
            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            payload = {'unique_id': plot_id}
            # `bay_id` — 시설 안에서 구역을 옮긴다(모종을 다른 동으로 옮겨
            # 심는 경우). 종료된 작기의 이동은 서버가 거부한다(VP-6).
            for k in ('subject', 'kind', 'variety', 'name', 'started_on',
                      'expected_end_on', 'color', 'bay_id', 'program_uuid',
                      'auto_advance'):
                if k in fields and fields[k] is not None:
                    payload[k] = fields[k]
            # **알아듣지 못한 인자를 성공이라 답하지 않는다.** 예전에는
            # `modify_plot(plot_id, crop='...')` 이 아무것도 바꾸지 않은 채
            # `status: success` 를 돌려줬다 — AI 는 바꿨다고 보고하고, 사용자는
            # 반영된 줄 안다. 이 저장소가 반복해서 겪은 "성공이라 답하는데 안 돈
            # 것" 계열이라, 바꿀 것이 없으면 이유와 함께 거절한다.
            if len(payload) <= 1:
                known = ('subject', 'kind', 'variety', 'name', 'started_on',
                         'expected_end_on', 'color', 'bay_id', 'program_uuid',
                         'auto_advance')
                unknown = [k for k in fields if k not in known
                           and not k.startswith('_')]
                msg = 'nothing to change'
                if unknown:
                    msg = ('unknown field(s): %s — allowed: %s'
                           % (', '.join(sorted(unknown)), ', '.join(known)))
                return {"status": "error", "message": msg}
            result, err = plot_io.save_plot(payload)
            if err:
                return {"status": "error", "message": err}
            result.pop('feature', None)
            return {"status": "success", "plot": result}
        except Exception as e:
            logger.exception("Error in modify_plot")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def propose_plot_split(zone_id=None, parts=None, strip_width_cm=None,
                               widths_cm=None, edge_margin_m=0, orientation=None,
                               angle_deg=None, **extra):
        """[읽기전용] 구역/대지를 나눈 제안을 계산한다. 저장하지 않는다.

        **좌표를 만들지 않는 분할 경로다.** 사람이 이미 그려 둔 도형을 서버가
        나눈다 — LLM 은 구역이 지도 어디인지 알 수 없으므로(어떤 도구도 경계
        폴리곤을 안 내준다) 이 길이 없으면 좌표를 지어내게 된다.

        방향은 보통 `orientation` 을 생략하는 편이 낫다 — 서버가 모드로 알아서
        고른다: `strip_width_cm` 를 줬으면(두둑) 고랑 방향이 실제 작업 방향과
        맞아야 하므로 도형의 긴 변을 따르고, `parts` 만 줬으면(작물을 나눠
        심을 때) 두둑 개념이 없으므로 짧은 변을 눕혀 정방형에 가까운 조각을
        낸다. 이 기본값이 마음에 안 들 때만 `orientation='long'|'short'` 로
        직접 뒤집을 것.

        `angle_deg`(0≤값<180)를 주면 그 두 프리셋을 무시하고 임의 각도를 그대로
        쓴다 — 인접 필지의 기존 두둑과 줄을 맞추는 등, 긴 변도 짧은 변도 아닌
        방향이 필요할 때만 쓴다. 지도를 볼 수 없는 LLM 은 스스로 각도를 고를
        근거가 없으므로, 사람이 지도 설계 화면에서 각도를 확인하며 정한 뒤
        불러 준 값을 그대로 전달하는 용도다 — 값을 지어내지 말 것.
        `orientation` 과 동시에 주면 `angle_deg` 가 이긴다(`orientation` 은
        조용히 무시된다).

        `widths_cm`(cm 리스트, 2개 이상)를 주면 `parts`/`strip_width_cm` 는
        무시하고 조각마다 다른 폭으로 순서대로 자른다 — 같은 폭 N개라는 전제가
        안 맞을 때(가장자리 한 줄만 넓게, 작물별로 이랑 폭이 다를 때) 쓴다.
        합이 도형의 짧은 축보다 크면 마지막 조각만 들어가는 만큼 줄어든다
        (`widths_clamped_from_cm` 로 원래 요청값을 알 수 있다).

        폴리곤 자체는 돌려주지 않는다. 조각 수·길이·면적 같은 **요약만** 낸다 —
        좌표 수백 개를 컨텍스트에 실을 이유가 없고, 실제로 만들 때는
        `apply_plot_split` 가 같은 파라미터로 다시 계산한다(결정적이다).
        """
        try:
            from aot.aot_flask.geo import plot_split
            from aot.databases.models import GeoShape
            if not zone_id:
                return {"error": "zone_id is required"}
            shape = GeoShape.query.filter_by(unique_id=zone_id).first()
            if shape is None:
                return {"error": f"zone/shape not found: {zone_id}"}
            strips, info = plot_split.split_shape(
                shape, parts=parts, strip_width_cm=strip_width_cm,
                widths_cm=widths_cm, edge_margin_m=edge_margin_m,
                orientation=orientation, angle_deg=angle_deg)
            if strips is None:
                return {"error": info}
            lengths = [s['length_m'] for s in strips]
            result = {
                "zone_id": zone_id,
                "pieces": info['count'],
                "piece_width_m": info['strip_width_m'],
                "length_m": {"min": min(lengths), "max": max(lengths)},
                "orientation": info['orientation'],
                "orientation_deg": info['orientation_deg'],
                "source_area_m2": info['source_area_m2'],
                "covered_area_m2": info['covered_area_m2'],
                "dropped": info['dropped'],
                "basis": info['note'],
                "next": ("Nothing was created. Show these numbers to the grower "
                         "and tell them they can SEE the proposal on the map "
                         "design page (vegetation mode) before deciding. To "
                         "create them, call apply_plot_split with the SAME "
                         "zone_id and parts/strip_width_cm plus the subject."),
            }
            if info.get('aspect_ratio') is not None:
                result["aspect_ratio"] = info['aspect_ratio']
            return result
        except Exception as e:
            logger.exception("Error in propose_plot_split")
            return {"error": str(e)}

    @staticmethod
    def apply_plot_split(zone_id=None, subject=None, started_on=None,
                             parts=None, strip_width_cm=None, widths_cm=None,
                             edge_margin_m=0, orientation=None, angle_deg=None,
                             variety=None, name=None,
                             expected_end_on=None, color=None, **extra):
        """[쓰기] 분할 제안을 실제 구획으로 만든다. 사람 승인 필요.

        `propose_plot_split` 와 **같은 파라미터로 다시 계산**한다
        (`orientation`/`angle_deg`/`widths_cm` 포함) — 제안을 저장해 두지 않는
        이유는 분할이 결정적이기 때문이다. 도형이 그 사이에 바뀌었으면 새
        모양대로 나뉜다(그게 맞다). `orientation` 을 생략했다면 그때와 똑같이
        생략할 것 — 서버가 모드로 고르는 기본값이 두 호출 사이에서도 같아야
        미리보기에서 본 것과 실제로 만들어지는 것이 갈리지 않는다.

        조각 하나가 구획 하나(GeoPlot 한 행)다. `parts=3` 이면 세 행,
        `strip_width_cm=160` 이면 두둑 수만큼. **개수를 보고 부르라** — 41행이
        생기면 노트도 이력도 41벌이 된다.
        """
        try:
            from aot.aot_flask.geo import plot_split, plot_io
            from aot.databases.models import GeoShape
            if not zone_id:
                return {"status": "error", "message": "zone_id is required"}
            if not (subject or '').strip():
                return {"status": "error", "message": "subject is required"}
            shape = GeoShape.query.filter_by(unique_id=zone_id).first()
            if shape is None:
                return {"status": "error",
                        "message": f"zone/shape not found: {zone_id}"}
            strips, info = plot_split.split_shape(
                shape, parts=parts, strip_width_cm=strip_width_cm,
                widths_cm=widths_cm, edge_margin_m=edge_margin_m,
                orientation=orientation, angle_deg=angle_deg)
            if strips is None:
                return {"status": "error", "message": info}

            created, errors = [], []
            for strip in strips:
                payload = {
                    'map_uuid': shape.geo_id,
                    'feature': {'type': 'Feature', 'properties': {},
                                'geometry': strip['geometry']},
                    'subject': subject, 'variety': variety,
                    'started_on': started_on,
                    'expected_end_on': expected_end_on, 'color': color,
                    'source_kind': 'copied', 'source_ref': shape.unique_id,
                }
                if name:
                    payload['name'] = '%s %d' % (name, strip['index'])
                row, err = plot_io.save_plot(payload)
                if err:
                    errors.append({'index': strip['index'], 'message': err})
                    continue
                row.pop('feature', None)
                created.append(row)

            # 일부만 저장된 것을 성공으로 말하지 않는다.
            return {
                "status": "success" if not errors else "partial",
                "created_count": len(created),
                "failed_count": len(errors),
                "errors": errors or None,
                "plots": created,
            }
        except Exception as e:
            logger.exception("Error in apply_plot_split")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def copy_plot(plot_id=None, subject=None, started_on=None, **extra):
        """[쓰기] 지난 작기의 기하를 그대로 새 작기로. 사람 승인 필요.

        **"작년에 콩 심었던 그 자리에 올해도" 는 실제로 가장 흔한 요청이고,
        좌표가 하나도 필요 없다.** 구현은 이미 있었는데(`plot_io.copy_plot`,
        REST `/api/geo/plot/<uuid>/copy`) AI 도구로만 없어서, 같은 자리를
        다시 심는 것을 말로는 시킬 수 없었다.

        기하만 복사하고 기간은 새로 받는다. 작물을 안 주면 원본과 같은 작물이다
        (같은 자리에 같은 것을 또 심는 것이 연작이고, 그것 자체가 판단 대상이라
        막지는 않는다 — `get_plot_history` 로 확인하고 조언할 것).
        """
        try:
            from aot.aot_flask.geo import plot_io
            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.copy_plot(
                plot_id, started_on=started_on, subject=subject)
            if err:
                return {"status": "error", "message": err}
            result.pop('feature', None)
            return {"status": "success", "plot": result}
        except Exception as e:
            logger.exception("Error in copy_plot")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def end_plot(plot_id=None, ended_on=None, reason='harvested', **extra):
        """[쓰기] 재배를 종료한다. 사람 승인 필요.

        행을 지우지 않는다 — 이력이 남아야 연작 판단이 된다. 지도에서만
        사라진다.
        """
        try:
            from aot.aot_flask.geo import plot_io
            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.end_plot(
                plot_id, ended_on=ended_on, reason=reason or 'harvested')
            if err:
                return {"status": "error", "message": err}
            result.pop('feature', None)
            return {"status": "success", "plot": result}
        except Exception as e:
            logger.exception("Error in end_plot")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def confirm_plot_stage(plot_id=None, stage_key=None, started_on=None,
                           **extra):
        """[쓰기] 단계 전환을 확인해 원장에 남긴다. 사람 승인 필요.

        **이 한 줄이 기준점을 옮긴다** — 이후 단계는 여기 적힌 날부터 계산된다.
        그래서 날짜를 지어내지 말 것: `get_plot` 의 `stage_proposal.started_on`
        이 자료에서 되짚은 날이고, 사람이 다른 날을 말하면 그것을 쓴다.

        무엇을 확인할지는 `stage_proposal` 이 말해 준다. 제안이 없으면(=null)
        확인할 전환이 없다는 뜻이다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            if not stage_key:
                return {"status": "error",
                        "message": ("stage_key is required — read it from "
                                    "get_plot's stage_proposal.stage_key")}
            result, err = plot_io.accept_stage(
                plot_id, stage_key=stage_key, started_on=started_on,
                source='manual', decided_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "event": result,
                    "note": ("The anchor moved — remaining stages are now "
                             "computed from this date.")}
        except Exception as e:
            logger.exception("Error in confirm_plot_stage")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def reschedule_plot_stage(plot_id=None, stage_key=None, started_on=None,
                              shift_days=None, days=None, **extra):
        """[쓰기] 단계 일정을 고친다 — 연기·앞당김. 사람 승인 필요.

        프로그램의 단계 기간은 **표준**이고 구획은 그것을 참조만 한다. "정식이
        비 때문에 일주일 밀렸다" 를 적는 도구가 이것이다.

        - `days` — 그 단계를 **며칠짜리로** 한다("육묘를 20일로"). 프로그램과
          같은 어휘라 사람이 날짜를 계산할 필요가 없다. 마지막 단계에는 쓸 수
          없다(끝내는 날은 재배 종료가 정한다).
        - `shift_days` — 그 단계의 **시작 경계**를 상대로 옮긴다(연기 +, 앞당김 −).
        - `started_on` — 절대 날짜('YYYY-MM-DD'). 사람이 날을 못박은 경우.

        **명시한 경계는 고정되고 뒤가 밀린다.** 한 단계를 미루면 이후 단계가
        통째로 따라 밀린다 — "이 단계만 늘리고 다음은 그대로" 는 다음 경계도
        같이 정하면 된다.

        고칠 수 있는 것은 **아직 오지 않은 경계**뿐이다. 이미 지나간 전환은
        `confirm_plot_stage`/`undo_plot_stage` 가 다루는 사실의 영역이다.
        지금 일정은 `get_plot` 의 `stage_schedule` 이 말해 준다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            if not stage_key:
                return {"status": "error",
                        "message": ("stage_key is required — read it from "
                                    "get_plot's stage_schedule")}
            given = [x for x in (days, shift_days, started_on)
                     if x not in (None, '')]
            if not given:
                return {"status": "error",
                        "message": "give one of days, shift_days or started_on"}
            if len(given) > 1:
                return {"status": "error",
                        "message": ("give only one of days, shift_days or "
                                    "started_on")}

            if days not in (None, ''):
                result, err = plot_io.set_stage_days(
                    plot_id, {stage_key: days}, set_by='AI')
            elif started_on:
                result, err = plot_io.set_stage_plan(
                    plot_id, {stage_key: started_on}, set_by='AI')
            else:
                result, err = plot_io.shift_stage(
                    plot_id, stage_key=stage_key, days=shift_days,
                    set_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success",
                    "stage_schedule": result.get('stage_schedule'),
                    "note": ("Boundaries after this one moved with it. The "
                             "programme itself is unchanged — this plot only "
                             "references it.")}
        except Exception as e:
            logger.exception("Error in reschedule_plot_stage")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def set_plot_stage_guidance(plot_id=None, stage_key=None, guidance=None,
                                **extra):
        """[쓰기] 이 구획의 단계 지침을 적는다. 사람 승인 필요.

        프로그램의 지침은 그 작물의 일반 사항이고, 이것은 **이 자리에서 이 시기에
        무엇을 하나** 다. 카탈로그는 지침을 비운 채로 오는 경우가 대부분이라,
        없어도 적을 수 있다. 빈 글을 주면 지운다(프로그램 지침이 다시 보인다).

        프로그램은 건드리지 않는다 — 같은 프로그램을 쓰는 다른 구획이 함께
        바뀌면 안 된다. 프로그램 자체를 고치려면 `modify_program` 이다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            if not stage_key:
                return {"status": "error",
                        "message": ("stage_key is required — read it from "
                                    "get_plot's stage_schedule")}
            result, err = plot_io.set_stage_guidance(
                plot_id, stage_key=stage_key, text=guidance, set_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "stage_key": result.get('stage_key'),
                    "guidance": result.get('guidance')}
        except Exception as e:
            logger.exception("Error in set_plot_stage_guidance")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def add_plot_stage(plot_id=None, name=None, days=None, after=None,
                       guidance=None, **extra):
        """[쓰기] 이 구획에 단계를 더한다. 사람 승인 필요.

        `after` 는 그 단계 **뒤**에 끼운다는 뜻이다(빈 문자열이면 맨 앞, 생략하면
        맨 뒤). 키는 서버가 짓는다.

        프로그램은 건드리지 않는다 — 이 구획만 한 단계를 더 갖는다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.add_stage(
                plot_id, name=name, days=days, after=after,
                guidance=guidance, set_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "stage_key": result.get('stage_key'),
                    "stage_schedule": result.get('stage_schedule')}
        except Exception as e:
            logger.exception("Error in add_plot_stage")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def remove_plot_stage(plot_id=None, stage_key=None, **extra):
        """[쓰기] 이 구획에서 단계를 뺀다. 사람 승인 필요.

        육묘 없이 바로 정식하는 작기가 있다. **이미 지나간 단계는 뺄 수 없다** —
        확인된 전환이 가리키는 단계를 없애면 그때 무엇을 했는지의 답이 사라진다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            if not stage_key:
                return {"status": "error", "message": "stage_key is required"}
            result, err = plot_io.remove_stage(
                plot_id, stage_key=stage_key, set_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success",
                    "stage_schedule": result.get('stage_schedule')}
        except Exception as e:
            logger.exception("Error in remove_plot_stage")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def save_plot_schedule_as_program(plot_id=None, name=None, **extra):
        """[쓰기] 이 구획의 일정을 **프로그램으로 등록한다**. 사람 승인 필요.

        구획에서 기간을 맞추고 단계를 더하고 지침을 적고 나면 그 지식은 그 구획
        안에만 있다 — 다음 작기·옆 밭이 같은 일을 처음부터 다시 하지 않게 한다.

        담기는 것은 지금 **실제로 따르고 있는** 단계 목록이고, 기간은 표준이
        아니라 경계 사이의 실제 날수다. 목표는 원본 프로그램 것을 그대로 옮긴다.

        **구획을 새 프로그램으로 옮기지는 않는다** — 등록은 복사다. 진행 중인
        작기의 해석이 등록 한 번에 바뀌면 "그때 무엇을 목표로 길렀나" 의 답이
        달라진다. 이 구획에도 쓰려면 `modify_plot(program_uuid=...)` 이 사람의
        결정이다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.save_as_program(
                plot_id, name=name, set_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "program": result.get('program'),
                    "note": ("The plot still follows what it followed before — "
                             "registering is a copy.")}
        except Exception as e:
            logger.exception("Error in save_plot_schedule_as_program")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def undo_plot_stage(plot_id=None, **extra):
        """[쓰기] 마지막으로 확인된 단계 전환을 되돌린다. 사람 승인 필요.

        기록은 지워지지 않는다(`undone` 으로 남는다). **마지막 것만** 무를 수
        있고, 무르면 그 전 전환이 다시 기준점이 되어 이후 단계가 다시 계산된다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.undo_stage(plot_id, decided_by='AI')
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "event": result}
        except Exception as e:
            logger.exception("Error in undo_plot_stage")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def apply_plot_resources(plot_id=None, **extra):
        """[쓰기·물리] 현재 단계에 **선언된** 자원 함수를 켠다. 사람 승인 필요.

        관수를 켜는 것은 물이 나오는 일이다. 프로그램은 함수를 스스로 켜지
        않으므로, 이 도구가 그 유일한 경로다.

        **선언된 것만 건드린다** — 선언에 없는 함수를 끄지 않는다. 무엇이
        선언됐고 지금 어떤 상태인지는 `get_plot` 의 `stage.resources` 가
        말해 준다(`active:false` 인 것만 켜진다).

        응답의 `failed` 를 반드시 볼 것 — 일부만 켜졌을 수 있다.
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.apply_stage_resources(plot_id)
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "result": result}
        except Exception as e:
            logger.exception("Error in apply_plot_resources")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def delete_plot(plot_id=None, **extra):
        """[쓰기] 구획 기록을 삭제한다. 사람 승인 필요.

        **오기입 정정용이다.** 수확이 끝난 것은 `end_plot` 을 쓴다 —
        삭제하면 그 자리의 이력이 사라져 연작 판단이 불가능해진다.
        """
        try:
            from aot.aot_flask.geo import plot_io
            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            result, err = plot_io.delete_plot(plot_id)
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "deleted": plot_id,
                    "note": ("Deleted outright. If this was a harvested subject, "
                             "end_plot would have kept the history.")}
        except Exception as e:
            logger.exception("Error in delete_plot")
            return {"status": "error", "message": str(e)}
