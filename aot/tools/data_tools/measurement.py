import logging

logger = logging.getLogger(__name__)


from aot.tools.aot_data_tool_service import _WEATHER_INPUT_DEVICES
from aot.tools.aot_data_tool_service import _WEATHER_MEASUREMENTS
from aot.tools.aot_data_tool_service import _WEATHER_METRIC_KEYWORDS
from aot.tools.aot_data_tool_service import _devices_on_map_p2
from aot.tools.aot_data_tool_service import _local_iso
from aot.tools.aot_data_tool_service import _looks_like_uuid
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import EnergyUsage
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Misc
from aot.utils.influx import read_influxdb_list
from aot.utils.system_pi import return_measurement_info
from aot.utils.tools import return_energy_usage
from aot.utils.tz_utils import now_utc
from datetime import datetime
from sqlalchemy import or_


class MeasurementToolsMixin:

    @classmethod
    def _check_influxdb_available(cls):
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

    @classmethod
    def _get_last_values_fallback(cls, target_input, device_measurements,
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

    _SENSOR_TYPE_ALIASES = {
        '온도': 'temperature', 'temp': 'temperature',
        '습도': 'humidity', 'hum': 'humidity',
        '조도': 'light', 'lux': 'light',
        '수분': 'volumetric_water_content',
        '토양': 'volumetric_water_content',
        'moisture': 'volumetric_water_content',
        '기상': 'weather', '날씨': 'weather', 'atmosphere': 'weather',
        '배터리': 'electrical_potential', 'vbat': 'electrical_potential',
        'battery': 'electrical_potential',
    }

    @classmethod
    def _normalize_sensor_type(cls, sensor_type):
        """사용자가 말한 센서 종류 → 저장된 측정 이름 조각. 못 찾으면 원문 그대로."""
        if not sensor_type:
            return None
        term = str(sensor_type).strip().lower()
        for alias, stored in cls._SENSOR_TYPE_ALIASES.items():
            if alias in term:
                return stored
        return term

    @classmethod
    def _pick_zone_inputs(cls, target_zone, normalized_type=None):
        """구역 안에서 **읽을 후보 장치들을 순서대로** 돌려준다.

        `_pick_weather_input` 과 같은 계약이되 기상 전용 드라이버 조건이 없는
        일반판이다. 그쪽은 "첫 Input 을 그냥 집으면 무슨 일이 벌어지는지"를
        이미 겪고 만들어졌는데(그 함수 주석 참조), 그 교훈이 기상 경로에만
        적용돼 있었다 — 일반 경로는 계속 `.first()` 였다.

        묻는 측정을 **실제로 가진** 장치를 앞세운다. 이름이 아니라
        DeviceMeasurements 를 보므로 '온습도_5' 가 토양수분을 갖고 있어도
        정상적으로 걸린다. 나머지 후보도 버리지 않고 뒤에 남긴다 — 앞선
        장치가 침묵해도 구역 전체가 침묵한 것은 아니기 때문이다.
        """
        from aot.aot_flask.geo.device_membership import device_ids_in_shape
        member_ids = device_ids_in_shape(target_zone) or set()
        if not member_ids:
            return [], []

        rows = Input.query.filter(Input.unique_id.in_(list(member_ids))).all()
        if not rows:
            return [], []

        with_measure = set()
        if normalized_type and normalized_type != 'weather':
            try:
                with_measure = cls._device_ids_with_measurement(
                    normalized_type)
            except Exception:
                logger.debug("[SENSOR_DETAIL] measurement lookup failed",
                             exc_info=True)

        # 결정론적으로 정렬한다. 예전엔 정렬 없는 `.first()` 라 SQLite 가
        # 돌려주는 순서(사실상 rowid)에 답이 달려 있었다.
        # `others` 를 여기서 만들지 않는다. 아래 호출부는 첫 후보가 조용하면
        # 다음 후보로 넘어가므로, 여기서 "첫 후보를 뺀 나머지" 를 굳혀 두면
        # 실제로 답한 장치가 '나머지' 목록에 남는다(실제로 그렇게 나왔다).
        # 나머지는 결과가 정해진 뒤 `_zone_pick_note` 가 만든다.
        return sorted(
            rows,
            key=lambda i: (0 if i.unique_id in with_measure else 1,
                           str(i.name or i.unique_id)))

    @classmethod
    def _zone_pick_note(cls, chosen, candidates, searched_all=False):
        """"이 답은 구역 안 N대 중 1대의 값" 이라는 사실을 응답에 실어 보낸다.

        구역으로 물으면 답은 필연적으로 한 대에서 나온다. 그것을 말하지 않으면
        구역에 센서가 하나뿐인 것처럼 읽히고, 그 한 대의 침묵이 구역의 침묵으로
        읽힌다 — 이 도구가 실제로 그렇게 답해 온 자리다.
        """
        _chosen_id = getattr(chosen, 'unique_id', None)
        others = [{"name": i.name, "device_id": i.unique_id, "driver": i.device}
                  for i in candidates if i.unique_id != _chosen_id]
        note = {
            "answered_by": getattr(chosen, 'name', None) or _chosen_id,
            "devices_in_zone": len(candidates),
            "other_devices_in_zone": others,
            "note": ("A zone answer comes from ONE device. This is that "
                     "device's reading, not a zone-wide aggregate — the "
                     "others listed here were not read. For every sensor of "
                     "the zone at once, call get_zone_sensor_summary."),
        }
        if searched_all:
            note["note"] = (
                "Every device in this zone was checked, not just the one "
                "named — so this empty result is about the zone, not about "
                "one device being picked. For a zone-wide view of what each "
                "sensor holds, call get_zone_sensor_summary.")
        return note

    @classmethod
    def get_sensor_detail(cls, loc_id, sensor_type=None, time_range="24h", limit=None):
        """
        특정 위치/장치의 상세 센서 이력을 조회합니다.
        :param loc_id: 장치(Input) 또는 구역(GeoShape)의 unique_id
        :param sensor_type: 필터링할 센서 타입 (예: temperature, humidity)
        :param time_range: 조회 범위 ("1h", "24h", "7d" 등)
        :param limit: 반환할 최근 readings 수 (기본: 20, 현재 날씨 조회 시 1 권장)

        ## 구역(zone/site)으로 물으면 — 한 대가 아니라 **후보 전체**를 본다

        여러 시스템 프롬프트가 이 도구를 "loc_id 에 zone unique_id 를 넣어
        쓰라"고 안내한다. 그런데 구역 분기는 오랫동안 구역 안 장치 중
        `.first()` 하나만 집어 그 한 대의 답을 **구역의 답인 양** 냈다.
        실측(zone 3-1): 장치 4대 중 데이터가 이틀 끊긴 1대가 매번 뽑혀
        "No data ... in the last 24h" 를 반환했다 — 나머지 3대는 정상
        보고 중이었다. 묻는 측정을 가진 장치를 앞세우고, 앞선 후보가
        빈손이면 다음 후보로 넘어간다. 어느 장치가 답했는지와 나머지
        후보는 `zone_pick` 으로 함께 낸다(구역 전체를 한 번에 보려면
        `get_zone_sensor_summary`).
        """
        try:
            # 측정 이름 정규화를 **장치 선택보다 먼저** 한다. 예전에는 장치를
            # 먼저 고르고 나서 걸렀기 때문에, 구역에 습도 센서가 있어도 먼저
            # 뽑힌 장치에 습도가 없으면 "No measurements matching type" 이
            # 나갔다 — 있는 것을 없다고 답하는 자리였다.
            normalized_type = cls._normalize_sensor_type(sensor_type)
            target_zone = None
            zone_candidates = []

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
                    zone_candidates = cls._pick_zone_inputs(
                        target_zone, normalized_type)
                    target_input = zone_candidates[0] if zone_candidates else None

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
            def _measurements_for(dev):
                """이 장치의 측정 중 물어본 종류만. 없으면 빈 리스트."""
                rows = DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == dev.unique_id).all()
                if not rows or not normalized_type:
                    return rows
                if normalized_type == 'weather':
                    # 'weather' 는 대기 관련 측정 여러 개를 한꺼번에 가리킨다.
                    return [m for m in rows
                            if any(wm in (m.measurement or "").lower()
                                   for wm in _WEATHER_METRIC_KEYWORDS)]
                return [m for m in rows
                        if normalized_type in (m.measurement or "").lower()]

            device_measurements = _measurements_for(target_input)

            # 구역으로 물었는데 첫 후보에 그 측정이 없으면 다음 후보로 넘어간다.
            # 구역 안 다른 장치가 갖고 있는 것을 "없다" 고 답하지 않기 위해서다.
            if not device_measurements and zone_candidates:
                for _cand in zone_candidates[1:]:
                    _ms = _measurements_for(_cand)
                    if _ms:
                        target_input, device_measurements = _cand, _ms
                        break

            if not device_measurements:
                if zone_candidates:
                    return {
                        "error": (f"No device in this zone records "
                                  f"'{sensor_type}'." if sensor_type else
                                  f"No device in this zone has any defined "
                                  f"measurement."),
                        "zone_pick": cls._zone_pick_note(
                            target_input, zone_candidates, searched_all=True),
                    }
                if not DeviceMeasurements.query.filter(
                        DeviceMeasurements.device_id ==
                        target_input.unique_id).first():
                    return {"error": f"This device ({target_input.name}) has no defined measurements."}
                return {"error": f"No measurements matching type '{sensor_type}'."}

            # 3. InfluxDB 연결 사전 점검
            influx_ok, influx_msg = cls._check_influxdb_available()
            if not influx_ok:
                logger.warning(f"[AoTDataTool] InfluxDB 사용 불가: {influx_msg}")
                # 폴백: 최신 값이라도 반환 시도
                fallback = cls._get_last_values_fallback(
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
            offset_sec = cls._parse_range(time_range)

            def _read_series(dev, measurements):
                """한 장치의 측정들을 읽어 시계열 목록으로. 데이터 없으면 []."""
                out = []
                for m in measurements:
                    conversion = Conversion.query.filter(Conversion.unique_id == m.conversion_id).first() if m.conversion_id else None
                    channel, unit, measurement = return_measurement_info(m, conversion)

                    data = read_influxdb_list(
                        dev.unique_id,
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
                            _tz = resolve_location_tz(dev.unique_id)
                            readings = [{"t": row[0].astimezone(_tz).isoformat(), "v": round(row[1], 2), "u": unit} for row in data]
                        except Exception:
                            readings = [{"t": row[0].isoformat(), "v": round(row[1], 2), "u": unit} for row in data]
                        values = [row[1] for row in data]
                        _keep = int(limit) if limit else 20
                        out.append({
                            "device_name": dev.name or dev.unique_id,
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
                return out

            results = _read_series(target_input, device_measurements)

            # 고른 장치가 조용하다고 **구역이** 조용한 것은 아니다. 실측(zone
            # 3-1): 이틀 끊긴 장치가 먼저 뽑혀 "No data" 를 냈는데 같은 구역
            # 센서 3대는 정상 보고 중이었다. 다음 후보로 넘어간다.
            _tried = [target_input]
            if not results and zone_candidates:
                for _cand in zone_candidates:
                    if _cand.unique_id == target_input.unique_id:
                        continue
                    _ms = _measurements_for(_cand)
                    if not _ms:
                        continue
                    _tried.append(_cand)
                    results = _read_series(_cand, _ms)
                    if results:
                        target_input = _cand
                        break

            if results:
                if zone_candidates and len(zone_candidates) > 1:
                    _note = cls._zone_pick_note(
                        target_input, zone_candidates)
                    # 성공 응답은 **리스트**다(호출부가 result[0]['readings'] 로
                    # 읽는다 — aot_native_tool_engine). 형태를 바꾸지 않고
                    # 각 항목에 얹는다.
                    for _r in results:
                        _r['zone_pick'] = _note
                return results

            # InfluxDB는 접속됐지만 데이터가 없는 경우
            if zone_candidates:
                return {
                    "message": (
                        f"No data in the last {time_range} from any of the "
                        f"{len(_tried)} device(s) tried in this zone."),
                    "time_range": time_range,
                    "zone_pick": cls._zone_pick_note(
                        target_input, zone_candidates, searched_all=True),
                }
            return {
                "message": f"No data for device '{target_input.name}' in the last {time_range}.",
                "device_id": target_input.unique_id,
                "time_range": time_range
            }

        except Exception as e:
            logger.exception("Error in get_sensor_detail")
            return {"error": f"Error while querying sensor data: {str(e)}"}

    @classmethod
    def _shape_display_name(cls, shape):
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

    @classmethod
    def get_zone_sensor_summary(cls, zone_ids=None, measurement_type=None,
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

            past_sec = cls._parse_range(time_range)

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
                    if cls._shape_display_name(s)]
            if not shapes:
                return {"error": "no zone/site found"}

            wanted = (cls._device_ids_with_measurement(measurement_type)
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
                                    "zone_name": cls._shape_display_name(shape)})
                    continue
                zones_out.append({
                    "zone_id": shape.unique_id,
                    "zone_name": cls._shape_display_name(shape),
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

    @classmethod
    def get_energy_report(cls, period="daily", zone_id=None):
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
                # 아래 두 빈 경우는 원인이 서로 다른데 예전에는 같은 문장
                # ("No energy sensors found for this zone/period")으로 나갔다.
                # 그 문장은 "여기엔 에너지 계측이 없다" 로 읽히지만, 실제로는
                # **지도 마커 좌표가 이 폴리곤 안에 들어오는 장치가 없다** 는
                # 뜻일 수 있다 — 관리상 이 구역 소속이어도 마커가 안 찍혔거나
                # 경계 밖에 찍혔으면 여기서 빠진다.
                _total_energy = EnergyUsage.query.count()
                if not input_ids:
                    return {
                        "message": ("No device is placed inside this zone on the "
                                    "map, so nothing could be measured for it."),
                        "cause": "no_device_marker_in_zone",
                        "note": ("Zone scoping here is geometric: a device counts "
                                 "only if its map marker falls inside the zone "
                                 "polygon. A device assigned to this zone but not "
                                 "placed (or placed just outside) is missed. "
                                 "%d energy record(s) exist system-wide; call "
                                 "without zone_id to see them."
                                 % _total_energy),
                    }
                energy_usage = EnergyUsage.query.filter(EnergyUsage.device_id.in_(input_ids)).all()
                if not energy_usage:
                    return {
                        "message": ("The %d device(s) inside this zone have no "
                                    "energy records." % len(input_ids)),
                        "cause": "devices_present_but_no_energy_records",
                        "note": ("%d energy record(s) exist system-wide. This is "
                                 "about these devices, not about the zone having "
                                 "no monitoring." % _total_energy),
                    }
            else:
                energy_usage = EnergyUsage.query.all()

            if not energy_usage:
                return {"message": "No energy records exist on this system at all.",
                        "cause": "no_energy_records_configured"}

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

            # "Usage is within normal parameters." 라는 문장이 데이터와 무관하게
            # 항상 실려 나갔다. 자리를 채우려고 둔 것이겠지만, 읽는 쪽에서는
            # 서버가 내린 판정으로 읽힌다 — 사용량이 얼마든 "정상" 이라고
            # 답하게 된다. 판정할 근거가 없으면 판정을 싣지 않는다.
            return {
                "summary": summary,
                "data": report_data,
            }
        except Exception as e:
            return {"error": str(e)}

    @classmethod
    def _weather_inputs(cls):
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

    @classmethod
    def _name_affinity(cls, device_name, zone_name):
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

    @classmethod
    def _pick_weather_input(cls, target_shape, resolved_name):
        """Choose the weather device for a zone/site.

        Returns (Input|None, scope, others) where scope is 'in_zone' |
        'same_map' | 'elsewhere' and `others` names the weather devices that
        were not chosen (so the caller can say which else exist).
        """
        candidates = cls._weather_inputs()
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
                key=lambda i: (-cls._name_affinity(i.name,
                                                                 resolved_name),
                               str(i.name or '')))
            chosen = tier[0]
            others = [{"name": i.name, "device_id": i.unique_id,
                       "driver": i.device}
                      for i in tier[1:]]
            return chosen, scope, others
        return None, None, []

    @classmethod
    def _weather_time_range(cls, device):
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

    @classmethod
    def get_weather_tool(cls, zone_name=None, zone_id=None, **kwargs):
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
                res = cls.get_sensor_detail(
                    loc_id=loc_id, time_range=time_range, sensor_type='weather')
                if isinstance(res, dict) and res.get('error'):
                    return cls.get_sensor_detail(
                        loc_id=loc_id, time_range=time_range)
                return res

            def _envelope(res):
                out = dict(res) if isinstance(res, dict) else {"data": res}
                out['zone_name'] = _resolved_name
                return out

            chosen, scope, others = cls._pick_weather_input(
                target_shape, _resolved_name)

            if chosen is not None:
                _range = cls._weather_time_range(chosen)
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
                    cls._weather_time_range(fallback_dev)))
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

    @classmethod
    def _parse_range(cls, range_str):
        if not range_str: return 86400
        range_str = str(range_str).lower()
        if range_str.endswith('h'):
            return int(range_str[:-1]) * 3600
        if range_str.endswith('d'):
            return int(range_str[:-1]) * 86400
        if range_str.isnumeric():
            return int(range_str)
        return 86400

    @classmethod
    def get_cumulative_status(cls, function_id: str, days: int = 7, **kwargs):
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

    @classmethod
    def _forecast_fallback_hint(cls):
        """등록된 전세계 기상 소스를 가리키는 한 문장.

        등록돼 있을 때만 말한다. 없는 것을 권하면 모델이 부를 수 없는 것을
        부르려 들고, 그 실패가 사용자에게는 그냥 '고장' 으로 보인다.
        """
        try:
            from aot.tools import providers
            for a in providers.get('data_source_query').describe_all():
                if a.get('preset') == 'ext_openmeteo':
                    return (" A global forecast source IS registered — call "
                            "query_data_source(source_id=%r, operation='forecast_daily') "
                            "(or 'forecast_hourly' for the next hours)." % a.get('source_id'))
        except Exception:
            pass
        return (" No global forecast source is registered; the operator can add "
                "Open-Meteo on the AI Library page.")

    _FORECAST_STALE_H = 6

    @classmethod
    def get_weather_forecast(cls, hours=24, **extra):
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
                                    "populated." + cls._forecast_fallback_hint()),
                        "checked_source": "forecast.json"}

            pub_raw = data.get('pub_dt')
            published_at, age_hours = None, None
            if pub_raw:
                try:
                    # 기상청 발표시각은 **KST 벽시계**다(이 경로는 한국 전용).
                    # 예전에는 그것을 naive 로 둔 채 `_dt.now()` 와 뺐는데,
                    # 컨테이너 시계는 언제나 UTC 라 그 뺄셈은 서로 다른 두
                    # 시간대를 뺀 것이었다 — 발표 30분 된 예보가 "8.5시간 전"
                    # 으로 나와 stale 판정이 통째로 어긋난다. 오프셋을 붙여
                    # 비교하고, 내보낼 때도 오프셋을 함께 싣는다.
                    from aot.utils.timekit import as_tz, utc_now as _utc_now
                    pub = as_tz('Asia/Seoul').localize(
                        _dt.strptime(str(pub_raw), '%Y%m%d%H%M'))
                    published_at = pub.isoformat()
                    age_hours = round(
                        (_utc_now() - pub).total_seconds() / 3600.0, 1)
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

            # 하루를 넘긴 것은 "낡은 예보" 가 아니라 **수집이 멈춘 것**이다.
            # 그런데도 내용을 실어 보내면 받는 쪽은 그것을 예보로 다루고, 매번
            # 사용자에게 "예보가 오래됐다" 를 보고한다 — 2026-09-16 사용자가
            # 짜증을 낸 것이 정확히 이 경로다(발표 215일 지난 파일이 계속
            # success 로 나갔다). 그런 파일은 데이터로 취급하지 않는다.
            if (age_hours is not None
                    and age_hours > cls._FORECAST_UNUSABLE_H) or not future:
                return {
                    "status": "unavailable",
                    "message": (
                        "Forecast collection is not running on this system — the "
                        "stored file was last issued %s and holds no future hours. "
                        "Treat this as having no forecast at all: do not read values "
                        "out of it, and do not bring this up with the user again "
                        "unless they ask about forecast collection itself."
                        % (published_at or "an unknown time ago")),
                    "published_at": published_at,
                    "age_hours": age_hours,
                    "checked_source": "forecast.json",
                }

            stale = age_hours is not None and age_hours > cls._FORECAST_STALE_H
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
            return result
        except Exception as e:
            logger.exception("Error in get_weather_forecast")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_anomalies(cls, scope_type="system", scope_id=None, **extra):
        """[읽기전용] 지금 이상 상태가 있는지 — 임계 위반·오프라인 비율 등.

        기존에는 이상탐지가 백그라운드 감시 파이프라인으로만 존재해서 AI가
        "지금 이상 있나?"를 물어볼 수단이 없었다. 감시 로직을 그대로 재사용해
        온디맨드 조회로 노출한다. 판정만 하고 알림 발송은 하지 않는다.
        """
        try:
            from aot.tools import providers
            summary = providers.get('anomaly_summary')(scope_type, scope_id)

            return {
                "status": "success",
                "scope": {"type": scope_type, "id": scope_id},
                "anomaly_detected": summary.get('anomaly_detected', False),
                "alert_level": summary.get('alert_level', 'none'),
                "anomalies": summary.get('anomalies', []),
                "metrics": summary.get('metrics', {}),
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
                "compared_with": ("이전 요약 v%s" % summary['previous_version']
                                 if summary.get('previous_version') is not None else None),
                # 현지시각으로 낸다. 이 값은 get_system_brief 에 그대로 실려
                # 나가는데, 거기서는 **시각처럼 보이는 유일한 필드**라 읽는 쪽이
                # "지금" 으로 집어 든다 — UTC 로 두었더니 한낮 14:10 을 새벽
                # 05:10 으로 읽고 "곧 05:30 관수" 라고 답한 일이 있었다
                # (2026-09-16). 지금 시각 자체는 응답의 `now` 가 따로 싣는다.
                "evaluated_at": _local_iso(summary.get('timestamp')),
            }
        except Exception as e:
            logger.exception("Error in get_anomalies")
            return {"status": "error", "message": str(e)}

    _FRESHNESS_PERIOD_FACTOR = 3

    _FRESHNESS_MIN_AGE_S = 300          # 하한: 주기가 아주 짧은 장치의 지터 흡수

    _FRESHNESS_SCAN_CAP_S = 30 * 86400  # 조회 창 상한(무제한 스캔 방지)

    _FRESHNESS_MAX_CHANNELS = 4         # 장치당 물어볼 채널 수 상한

    @classmethod
    def _last_seen_seconds(cls, device_id):
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
        for m in rows[:cls._FRESHNESS_MAX_CHANNELS]:
            conversion = (Conversion.query.filter(
                Conversion.unique_id == m.conversion_id).first()
                if m.conversion_id else None)
            channel, unit, measurement = return_measurement_info(m, conversion)
            try:
                last_time, _ = read_influxdb_single(
                    device_id, unit, channel, measure=measurement,
                    duration_sec=cls._FRESHNESS_SCAN_CAP_S,
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
            # 장치 자기 위치의 시각으로 낸다. 경과초(age)는 이미 절대시간 차라
            # 영향이 없고, 바뀌는 것은 표시뿐이다 — 그런데 이 표시가 UTC 로
            # 나가면 같은 응답 묶음 안에서 센서값(장치 현지)과 기준이 갈려
            # "마지막 수신 08:39 / 현재값 14:06" 이 나란히 놓인다(9시간 어긋난
            # 것을 9시간 침묵으로 읽는다).
            try:
                from aot.utils.device_tz import resolve_location_tz
                seen = seen.astimezone(resolve_location_tz(device_id))
            except Exception:                               # noqa: BLE001
                pass
        except Exception:
            return None, None, None
        return max(0.0, age), seen.isoformat(), newest_label

    @classmethod
    def get_device_freshness(cls, device_id=None, include_fresh=False, **extra):
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
                from aot.tools import providers
                zone_map = providers.get('device_zone_map')() or {}
            except Exception:
                zone_map = {}

            stale, fresh, no_data, inactive = [], [], [], []
            for d in devices:
                try:
                    period = float(d.period) if d.period else None
                except (TypeError, ValueError):
                    period = None
                threshold = cls._FRESHNESS_MIN_AGE_S
                if period:
                    threshold = max(threshold,
                                    period * cls._FRESHNESS_PERIOD_FACTOR)

                age, seen_iso, label = cls._last_seen_seconds(
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
                    "age_readable": (cls._readable_age(age)
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
                          % (cls._FRESHNESS_PERIOD_FACTOR,
                             cls._FRESHNESS_MIN_AGE_S)),
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
                "scan_window_days": int(cls._FRESHNESS_SCAN_CAP_S / 86400),
            }
            if include_fresh:
                result["fresh_devices"] = fresh
            return result
        except Exception as e:
            logger.exception("Error in get_device_freshness")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _readable_age(cls, seconds):
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

