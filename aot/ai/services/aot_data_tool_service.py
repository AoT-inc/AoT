import logging
from aot.utils.time_utils import utc_now, to_local, serialize_ts
from aot.utils.tz_utils import now_utc, to_utc
from datetime import datetime, timedelta
from sqlalchemy import or_

from aot.aot_flask.extensions import db
from aot.databases.models import Input, Output, Camera, GeoShape, GeoLayer, DeviceMeasurements, Conversion, EnergyUsage, Misc, Notes, AITask
from aot.ai.services.ai_context_service import AIContextService
from aot.ai.services.ai_action_service import AIActionService
from aot.utils.influx import read_influxdb_list
from aot.utils.tools import return_energy_usage
from aot.utils.system_pi import return_measurement_info

logger = logging.getLogger(__name__)


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
    def _get_last_values_fallback(target_input, device_measurements):
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

            if not target_input:
                # 구역인 경우 (unique_id 또는 geo_id 지원)
                target_zone = GeoShape.query.filter(
                    or_(GeoShape.unique_id == loc_id, GeoShape.geo_id == loc_id)
                ).first()
                # [WEATHER_TOOL_UNIFICATION] Name-based fallback: loc_id may be a zone name (e.g. '1포장')
                # not a UUID. Match by feature.properties.name so both get_sensor_detail and
                # get_weather behave consistently regardless of which tool the AI selects.
                if not target_zone and loc_id:
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
                    weather_metrics = ['temperature', 'humidity', 'pressure', 'wind', 'rain', 'solar', 'uv', 'dewpoint', 'speed', 'direction']
                    device_measurements = [m for m in device_measurements if any(wm in (m.measurement or "").lower() for wm in weather_metrics)]
                else:
                    device_measurements = [m for m in device_measurements if search_term in (m.measurement or "").lower()]

            if not device_measurements:
                return {"error": f"No measurements matching type '{sensor_type}'."}

            # 3. InfluxDB 연결 사전 점검
            influx_ok, influx_msg = AoTDataToolService._check_influxdb_available()
            if not influx_ok:
                logger.warning(f"[AoTDataTool] InfluxDB 사용 불가: {influx_msg}")
                # 폴백: 최신 값이라도 반환 시도
                fallback = AoTDataToolService._get_last_values_fallback(target_input, device_measurements)
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
    def get_spatial_tree(depth=2, filter_type=None):
        """
        시스템의 공간 계층 구조를 트리 형태로 반환합니다.
        """
        try:
            full_tree = AIContextService.get_spatial_hierarchy()
            # depth 및 filter_type에 따른 가지치기는 추후 복잡도에 따라 구현 가능
            # 현재는 전체 트리를 반환하거나 기본적인 필터링만 수행
            if filter_type:
                # 간단한 타입 필터링 예시
                def filter_node(node):
                    if 'children' in node:
                        node['children'] = [filter_node(c) for c in node['children'] if c.get('type') == filter_type or 'children' in c]
                    return node
                full_tree = [filter_node(n) for n in full_tree]
                
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
    def search_devices(query):
        """
        이름 또는 타입으로 장치를 검색합니다.
        v2: Multi-token query expansion.
          - Splits query by whitespace and searches each token independently
            (e.g. "1구역 밸브" → searches "1구역" AND "밸브" separately).
          - Loads term aliases from AIDomainGlossary (category='term_alias')
            to handle user-specific terms (e.g. "1포장" → "1구역").
          - Deduplicates results by unique_id.
        """
        if not query:
            return {"error": "Query string is empty"}

        try:
            import re

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
                    from aot.databases.models.controller import CustomController
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

            results = AoTDataToolService._annotate_device_membership(results)
            return {"results": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

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
            return {"results": results, "count": len(results)}
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

        현재 설치된 버전(AOT_VERSION)을 GitHub 릴리스 태그와 비교합니다
        (admin/upgrade 페이지와 동일한 AoTRelease().github_upgrade_exists() 사용).
        GitHub 조회 실패/rate-limit 시 DB에 캐시된 Misc.aot_upgrade_available 로 폴백합니다.
        """
        try:
            from aot.config import AOT_VERSION
            from aot.utils.github_release_info import AoTRelease

            current_version = AOT_VERSION
            update_available = None
            latest_version = None
            available_releases = []
            errors = []

            # 1. 라이브 조회 (관리자 업그레이드 페이지와 동일 경로)
            try:
                (upgrade_exists,
                 releases,
                 _aot_tags,
                 current_latest_tag,
                 check_errors) = AoTRelease().github_upgrade_exists()
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

            if update_available is None:
                return {
                    "current_version": current_version,
                    "update_available": None,
                    "message": (
                        "Could not check for updates (GitHub unreachable or rate-limited). "
                        "Try again later, or check Admin → Upgrade."
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

            return {
                "current_version": current_version,
                "latest_version": latest_version,
                "update_available": update_available,
                "available_releases": available_releases,
                "message": message,
                "errors": errors,
            }
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
            if target_id:
                candidate_ids = [target_id]
            elif target_name:
                candidate_ids, resolved_name = \
                    AoTDataToolService._resolve_note_target_ids(target_name)
                if not candidate_ids:
                    return {
                        "status": "success", "count": 0, "results": [],
                        "message": f"Location/device '{target_name}' was not found.",
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
                return {
                    "status": "success", "count": 0, "results": [],
                    "message": f"No notes found for {_where}.",
                }

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

            return {
                "status": "success",
                "count": len(results),
                "results": results,
                "query": query,
                "target": resolved_name or target_name or target_id,
            }
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

            if target_name:
                target_id, _tt, _rn, _lat, _lng = \
                    AoTDataToolService._resolve_note_target(target_name)
                if target_id:
                    q = q.filter(SchedulerJobMeta.target_id == target_id)

            # 예정은 임박한 순, 과거 포함이면 최신순
            if include_past:
                q = q.order_by(SchedulerJobMeta.created_at.desc())
            else:
                q = q.order_by(SchedulerJobMeta.schedule_time.asc())

            rows = q.limit(max(1, int(limit))).all()
            results = [AoTDataToolService._schedule_summary(r) for r in rows]
            return {
                "status": "success",
                "count": len(results),
                "results": results,
            }
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
            if not target_shape and zone_name:
                _zn = zone_name.strip().lower()
                for shape in GeoShape.query.all():
                    try:
                        feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                        props = feat.get('properties') or {}
                        _name = str(props.get('name') or props.get('label') or props.get('title') or '').lower()
                        if _zn in _name or _name in _zn:
                            target_shape = shape
                            break
                    except Exception:
                        continue

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

            # Step 3: Delegate to get_sensor_detail via zone unique_id.
            # get_sensor_detail resolves: GeoShape.unique_id → Input(map_overlay_id)
            #   → DeviceMeasurements(device_id + channel) → InfluxDB read.
            # No external HTTP calls are made here.
            logger.info(f"[WEATHER_TOOL] Querying InfluxDB for zone '{_resolved_name}' (id={target_shape.unique_id})")
            _result = AoTDataToolService.get_sensor_detail(loc_id=target_shape.unique_id, time_range='1h')

            # Step 4: Attach zone context and return
            if isinstance(_result, list):
                return {"zone_name": _resolved_name, "data": _result}
            if isinstance(_result, dict):
                _result['zone_name'] = _resolved_name
                return _result
            return {"zone_name": _resolved_name, "data": _result}

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
                return {
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
    def create_function_tool(function_type=None, name=None, params=None, activate=False, **extra):
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

        # Look up the newly created record by unique_id
        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import Conditional, Trigger
        from aot.databases.models.pid import PID

        new_func = None
        for Model in [CustomController, Conditional, PID, Trigger]:
            try:
                row = Model.query.filter_by(unique_id=new_function_id).first()
                if row:
                    new_func = row
                    break
            except Exception:
                continue

        # Apply display name if provided
        if new_func and name:
            new_func.name = name
            db.session.commit()

        # Apply custom params if provided
        logger.info(f"[create_function] new_func={new_func}, params={params}")
        if new_func and params and isinstance(params, dict):
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

        # Do NOT auto-activate. A freshly-created function has no device steps/targets
        # configured yet; activating an empty function is wrong (it does nothing and
        # confused users — "빈 함수를 활성화 시킴"). Configure it first (modify_function_options
        # / editor / create_sequence_function for sequences), then activate explicitly
        # via activate_function. Callers wanting the old behavior pass activate=True.
        activated = False
        if activate:
            try:
                from aot.aot_client import DaemonControl
                DaemonControl().controller_activate(function_id)
                activated = True
            except Exception as e:
                logger.warning(f"[create_function] daemon activate failed (non-fatal): {e}")

        result = {
            "function_id": function_id,
            "name": getattr(new_func, 'name', ''),
            "function_type": function_type,
            "status": "created",
            "activated": activated,
        }
        if not activated:
            result["note"] = ("Created deactivated — configure its options/steps, then "
                              "activate with activate_function.")
        if ignored_args:
            result["ignored_args"] = ignored_args
            result["note"] = ("Ignored non-schema arg(s): "
                              f"{ignored_args}. The function was created (deactivated & empty); "
                              "configure its device steps, then activate.")
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
        from aot.databases.models.function import Conditional, Trigger
        from aot.databases.models.pid import PID

        func = None
        for Model in [CustomController, Conditional, PID, Trigger]:
            try:
                row = Model.query.filter_by(unique_id=function_id).first()
                if row:
                    func = row
                    break
            except Exception:
                continue

        if func is None:
            return {"error": f"Function not found: {function_id}"}

        existing = {}
        try:
            existing = _json.loads(getattr(func, 'custom_options', None) or '{}')
        except Exception:
            existing = {}

        existing.update(params)
        func.custom_options = _json.dumps(existing)
        db.session.commit()

        # Reload in daemon so changes take effect without manual restart
        try:
            from aot.aot_client import DaemonControl
            daemon = DaemonControl()
            daemon.controller_deactivate(function_id)
            daemon.controller_activate(function_id)
        except Exception as e:
            logger.warning(f"[modify_function_options] daemon reload failed (non-fatal): {e}")

        return {"function_id": function_id, "status": "modified",
                "changed": list(params.keys())}

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
        if isinstance(messages, dict) and messages.get("error"):
            return {"error": "; ".join(messages["error"])}
        return {"output_id": output_id, "status": "deleted"}

    @staticmethod
    def create_sequence_function(name=None, device_ids=None, state='on',
                                 step_duration=0, pause_seconds=0, activate=True, **extra):
        """Create a trigger_sequence AND fill its steps — one ordered output action per
        device — so it is actually configured, not an empty shell. This is what "밸브
        순차 제어 시퀀스" means: create the trigger, add an output_on_off action for each
        valve in order, THEN activate (empty functions are never auto-activated).

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

        # 3. Activate only now that it has steps.
        activated = False
        if activate:
            try:
                from aot.aot_client import DaemonControl
                DaemonControl().controller_activate(new_id)
                activated = True
            except Exception as e:
                logger.warning(f"[create_sequence] activate failed (non-fatal): {e}")

        result = {
            "function_id": new_id, "function_type": "trigger_sequence",
            "name": (trig.name if trig else name), "status": "created",
            "steps": steps, "step_count": len(steps), "activated": activated,
        }
        if extra:
            result["ignored_args"] = list(extra.keys())
        return result

    @staticmethod
    def delete_function(function_id=None, **extra):
        """Delete a Function/Controller by unique_id (completes function CRUD)."""
        from aot.aot_flask.utils.utils_function import function_del
        if not function_id:
            return {"error": "function_id is required"}
        try:
            messages = function_del(function_id)
        except Exception as e:
            logger.error(f"[delete_function] function_del raised: {e}")
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
        import json as _json
        if not target_name or not str(target_name).strip():
            return None, None, None, None, None
        _q = str(target_name).strip()
        _ql = _q.lower()

        # Parse every named GeoShape once: (shape, name, name_lower).
        shapes = []
        for shape in GeoShape.query.all():
            try:
                feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                props = feat.get('properties') or {}
                _name = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
                if _name:
                    shapes.append((shape, _name, _name.lower()))
            except Exception:
                continue

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
        subs = [(s, n) for (s, n, nl) in shapes if _ql in nl or nl in _ql]
        if subs:
            subs.sort(key=lambda sn: 0 if sn[0].type in _ZONE_TYPES else 1)
            return _ret(*subs[0])

        # 4) Input / Output devices by name.
        for model, _tt in ((Input, 'input'), (Output, 'output')):
            row = model.query.filter(model.name.ilike(f"%{_q}%")).first()
            if row:
                return row.unique_id, _tt, row.name, None, None

        return None, None, None, None, None

    @staticmethod
    def _geo_shape_descendant_unique_ids(root_shape):
        """Return unique_ids of every GeoShape nested under root_shape (e.g. a
        site's child zones). See aot/utils/geo_hierarchy.py for why this is
        needed (GeoShape.parent_id is unset in production; the real parent
        signal is spatial containment).
        """
        from aot.utils.geo_hierarchy import geo_descendant_unique_ids
        return geo_descendant_unique_ids(root_shape)

    @staticmethod
    def _geo_shape_descendants(root_shape):
        """Same as _geo_shape_descendant_unique_ids but returns the GeoShape
        rows themselves (needed when callers must read the child's own name/
        type, not just its unique_id)."""
        from aot.utils.geo_hierarchy import geo_descendant_shapes
        return geo_descendant_shapes(root_shape)

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
            return {
                "status": "needs_disambiguation",
                "error": "target_not_found",
                "message": f"'{target_name}' could not be resolved to a known entity.",
                "available_targets": AoTDataToolService._geoshape_name_candidates(),
            }

        children = []
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
                        try:
                            feat = c.feature if isinstance(c.feature, dict) else _json.loads(c.feature or '{}')
                            props = feat.get('properties') or {}
                            c_name = props.get('name') or props.get('label') or props.get('title')
                        except Exception:
                            c_name = None
                        if c_name and c_name not in seen_names:
                            seen_names.add(c_name)
                            children.append({"name": c_name, "type": c.type})
            except Exception:
                children = []

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
                ids.extend(AoTDataToolService._geo_shape_descendant_unique_ids(site_shape))

        # GeoShapes whose display name matches EXACTLY → add the shape's own id
        # and the device it represents.
        try:
            for shape in GeoShape.query.all():
                try:
                    feat = shape.feature if isinstance(shape.feature, dict) else _json.loads(shape.feature or '{}')
                    props = feat.get('properties') or {}
                    _name = str(props.get('name') or props.get('label') or props.get('title') or '').strip()
                except Exception:
                    continue
                if _name and _name.lower() == _ql:
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

        n = Notes(
            name=name or (note[:50] if note else 'Note'),
            note=note or '', tags=tags or '', category=category or 'general',
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
        text = _ks.search_as_text(query, top_k=top_k, tags=_tags)
        if not text:
            return {"result": f"No documentation section matched '{query}'. Try different keywords."}
        return {"result": text}

    # --- Knowledge shelve (@ANCHOR: KNOWLEDGE_SHELVE_TOOL, P4 2026-07-19) --------
    # The write half of the AI library redesign (docs/design/ai-library-redesign.md
    # §4): the AI's own read_manual/knowledge_search calls surface curated
    # knowledge, but nothing let the AI SAVE something it just worked out (an
    # observation from data, a synthesized answer) for next time. NOT
    # approval-gated (same reasoning as create_note): always writes at the
    # lowest trust tier (provenance='ai_curated', unconfirmed) — a low-risk,
    # reversible write, never presented with authority until a human confirms
    # it or it corroborates against a real source (P5, not yet built).
    @staticmethod
    def knowledge_shelve(content=None, tags=None, heading=None, entity_ref=None,
                         attribution=None, content_kind='prose', ttl_hours=None, **extra):
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
            content_kind=content_kind, ttl=ttl,
        )
        if extra:
            result["ignored_args"] = list(extra.keys())
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
            if p.get("is_system"):
                entry["url"] = p.get("url_source", "")
                entry["needs_api_key"] = True
                entry["multi_operation"] = bool(p.get("multi_operation"))
                system.append(entry)
            else:
                entry["source_type"] = p.get("source_type", key)
                custom.append(entry)
        return {
            "system_presets": system,
            "custom_types": custom,
            "note": "system_presets are pre-built external public-data APIs — each needs its own API "
                    "key from that provider. custom_types let the operator ingest their OWN data: a "
                    "document (PDF/text/markdown), a web page, any REST API, or an internal DB query. "
                    "When the user asks what knowledge libraries they can add (or for a recommendation), "
                    "present BOTH groups — never mention only one source.",
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

                entry = {
                    "function_id": c.unique_id,
                    "function_name": c.name,
                    "is_activated": bool(c.is_activated),
                    "facility_id": fid,
                    "facility_name": fname,
                    "bay_scope": o.get('bay_scope') or None,
                    "effect_engine": o.get('effect_engine', 'legacy'),
                    "crop_preset": o.get('crop_preset'),
                    "targets": {
                        "vpd_kpa": o.get('target_vpd'),
                        "vpd_source": o.get('vpd_sp_type'),
                        "temperature_c": o.get('target_temperature'),
                        "humidity_pct": o.get('target_humidity'),
                        "co2_ppm": o.get('target_co2'),
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
                        "season": [o.get('schedule_start_time'), o.get('schedule_end_time')],
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
                return {"status": "unavailable",
                        "message": ("No forecast data. KMA forecast collection may not "
                                    "be configured."),
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
                "compared_with": ("이전 요약 v%s" % previous.version) if previous else None,
                "evaluated_at": current.get('timestamp'),
            }
        except Exception as e:
            logger.exception("Error in get_anomalies")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_crop_status(facility_id=None, facility_name=None, **extra):
        """[읽기전용] 시설별 작물과 생육단계 — 재배 조언의 전제.

        작물을 모르면 최적 재배 조언 자체가 성립하지 않는다. 인앱 AI는 도메인
        컨텍스트로 자동 주입받지만 MCP 경로는 그 파이프라인을 타지 않아 알 방법이
        없었다.

        두 소스를 겹쳐 읽는다:
          1) env_coordinator 의 crop_preset — 항상 사용 가능한 1차 소스
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
                    "crop_preset": o.get('crop_preset'),
                    "controlled_by": c.unique_id,
                    "season_window": [o.get('schedule_start_time'),
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
                        r["days_after_planting"] = state.get('days_after_planting')
                        r["optimal_ranges"] = state.get('optimal_ranges')
                        r["growth_stage_source"] = state.get('growth_stage_source')
                except Exception as exc:
                    registry_note = (
                        "Growth stage unavailable: could not read the domain registry "
                        f"(facility_registry.yaml) ({type(exc).__name__}). The crop type is "
                        "still available via crop_preset, but days-after-planting and "
                        "stage-specific optimal ranges require planting_date/crop_type to be "
                        "registered there.")

            result = {"status": "success", "count": len(rows), "facilities": rows}
            if not rows:
                result["message"] = (
                    "No active env_coordinator carries crop information. Check whether an "
                    "environment-control coordinator is configured for the facility.")
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
        brief["devices"] = _safe("장치 요약", lambda: {
            "device_count": (S.get_device_list_tool() or {}).get("count"),
            "note": "Use get_device_list / search_devices for the full list",
        })
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
            "check the 'stale' flag).",
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
