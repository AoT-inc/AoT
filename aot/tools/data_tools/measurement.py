import logging

logger = logging.getLogger(__name__)

_RAIN_LABEL_MEAS = frozenset({"length", "depth"})
_RAIN_LABEL_UNITS = frozenset({"mm", "mm_h", "mm/h", "in", "in_h"})


def _is_rain_label(measurement, unit, name):
    """응답 표시용: 저장 measurement 가 length/depth(mm)이고 채널 이름이 강우를
    가리키면 True. 거리 센서(length, mm)는 이름이 달라 그대로 둔다. 표시 전용 —
    강우 게이트·저장 정의와 무관하다."""
    import re
    if str(measurement or "").lower() not in _RAIN_LABEL_MEAS:
        return False
    if str(unit or "").lower() not in _RAIN_LABEL_UNITS:
        return False
    return bool(re.search(r"rain|precip|강수|강우|(?<![a-z])rn\d",
                          str(name or "").lower()))


from aot.tools.aot_data_tool_service import _WEATHER_INPUT_DEVICES
from aot.tools.aot_data_tool_service import _WEATHER_MEASUREMENTS
from aot.tools.aot_data_tool_service import _WEATHER_METRIC_KEYWORDS
from aot.tools.aot_data_tool_service import _WEATHER_SKY_KEYWORDS
from aot.tools.aot_data_tool_service import _devices_on_map_p2
from aot.utils.timekit import iso_at, FARM, parse_utc, tz_of, utc_now
from aot.tools.aot_data_tool_service import _looks_like_uuid
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import EnergyUsage
from aot.databases.models import GeoShape
from aot.databases.models import Input
from aot.databases.models import Misc
from aot.databases.models import Output
from aot.utils.influx import read_influxdb_list
from ._shims import tz_scoped
from aot.utils.system_pi import return_measurement_info
from aot.utils.tools import return_energy_usage
from datetime import datetime
from datetime import timedelta
from datetime import timezone
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
                                  is_function=False, is_output=False):
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
                    # UTC → 이 장치가 놓인 곳의 시각(`location_iso` 한 곳에서).
                    from aot.utils.timekit import iso_at
                    _t = iso_at(last[0], target_input.unique_id)
                    results.append({
                        "device_name": target_input.name or target_input.unique_id,
                        "device_kind": ("function" if is_function else
                                            "output" if is_output else "input"),
                        "measurement": measurement or m.measurement,
                        "last_value": round(last[1], 2),
                        "last_time": _t,
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
        # 소속은 정본(마커 + 바인딩 + 하위 장소)으로 — 마커만 보면 구역에
        # 바인딩으로 맡긴 센서가 빠진다(2026-10-08).
        from aot.space.device_membership import place_members_split
        try:
            split = place_members_split(target_zone.unique_id) or {}
        except Exception:                                   # noqa: BLE001
            logger.debug("[SENSOR_DETAIL] indoor/outdoor split failed",
                         exc_info=True)
            split = {}
        member_ids = split.get('members') or set()
        outdoor_ids = (split.get('outdoor') or set()) & set(member_ids)
        if not member_ids:
            return [], []

        # 'AI 판단에 포함' 을 끈 센서는 후보가 아니다(device_resolver.ai_excluded).
        from aot.services.resolvers.device_resolver import ai_excluded
        rows = [i for i in Input.query.filter(
            Input.unique_id.in_(list(member_ids))).all() if not ai_excluded(i)]
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
        # 실내 센서가 그 측정을 갖고 있으면 실외(기상대)는 맨 뒤로 보낸다. 이름
        # A-Z 만으로 고르면 '미러-기상대' 가 대표가 되어, 습도로 다시 물어도
        # 외기 값이 구역의 답이 됐다(리허설 F7/G2). 실내가 그 측정을 못 가질
        # 때만 실외도 후보 순서를 그대로 따른다.
        for i in rows:
            i._pick_outdoor = i.unique_id in outdoor_ids
        indoor_has = any(i.unique_id in with_measure and not i._pick_outdoor
                         for i in rows)

        # 위치 유형(classify_sensors)으로도 정렬한다: facility/open_field →
        # unplaced → outdoor. 실내 우선 규칙(위)은 그대로 먼저 본다.
        _rank = {'facility': 0, 'open_field': 0, 'unplaced': 1, 'outdoor': 2}
        try:
            from aot.space.device_membership import classify_sensors
            _pl = classify_sensors([i.unique_id for i in rows],
                                   place_uid=target_zone.unique_id)
        except Exception:                                   # noqa: BLE001
            logger.debug("[SENSOR_DETAIL] placement failed", exc_info=True)
            _pl = {}

        def _key(i):
            p = _pl.get(i.unique_id)
            return (1 if (indoor_has and i._pick_outdoor) else 0,
                    0 if i.unique_id in with_measure else 1,
                    _rank.get(p.kind, 1) if p is not None else 1,
                    str(i.name or i.unique_id))
        return sorted(rows, key=_key)

    #: 짧은 `zone_pick` 에 이름으로 싣는 다른 장치 수 — 나머지는 개수만.
    _ZONE_PICK_OTHERS = 5

    @classmethod
    def _zone_pick_slim(cls, chosen, candidates):
        """도메인 표면(brief)의 `zone_pick` — 답한 장치 이름과 "구역 안 N대 중 한 대" 라는 사실만.

        고르는 규칙 문장(`selection_rule`)·읽는 법(`note`)·다른 장치의 id·드라이버는 뺀다 —
        채널마다 같은 것이 되풀이돼 응답의 절반이었다. 값을 읽는 데 꼭 필요한 사실은 남는다:
        이 값이 한 대의 것이라는 것(`answered_by`+`devices_in_zone`), 실외 기준값인지(`answered_by_outdoor`),
        쓰지 않은 실외 장치(`outdoor_not_used`), 읽지 않은 다른 장치 이름."""
        _id = getattr(chosen, 'unique_id', None)
        others = [i.name or i.unique_id for i in candidates if i.unique_id != _id]
        note = {"answered_by": getattr(chosen, 'name', None) or _id,
                "devices_in_zone": len(candidates)}
        if others:
            note["other_devices"] = others[:cls._ZONE_PICK_OTHERS]
            if len(others) > cls._ZONE_PICK_OTHERS:
                note["other_devices_more"] = len(others) - cls._ZONE_PICK_OTHERS
        _out = [i.name or i.unique_id for i in candidates
                if getattr(i, '_pick_outdoor', False)]
        if getattr(chosen, '_pick_outdoor', False):
            note["answered_by_outdoor"] = True
        elif _out:
            note["outdoor_not_used"] = _out
        return note

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
            "answered_by_device_id": _chosen_id,
            "selection_rule": (
                "Indoor devices that record the asked measurement come "
                "first, then other devices that record it, then by name "
                "(A-Z); outdoor (weather station) devices go last when an "
                "indoor one records it. The first with data in the period "
                "answers."),
            "devices_in_zone": len(candidates),
            "other_devices_in_zone": others,
            "note": ("A zone answer comes from ONE device. This is that "
                     "device's reading, not a zone-wide aggregate — the "
                     "others listed here were not read. For every sensor of "
                     "the zone at once, call get_zone_sensor_summary."),
        }
        _out = [i.name or i.unique_id for i in candidates
                if getattr(i, '_pick_outdoor', False)]
        if getattr(chosen, '_pick_outdoor', False):
            note["answered_by_outdoor"] = True
        elif _out:
            note["outdoor_not_used"] = _out
        if searched_all:
            note["note"] = (
                "Every device in this zone was checked, not just the one "
                "named — so this empty result is about the zone, not about "
                "one device being picked. For a zone-wide view of what each "
                "sensor holds, call get_zone_sensor_summary.")
        return note

    @classmethod
    @tz_scoped
    def get_sensor_detail(cls, loc_id=None, sensor_type=None, time_range="24h",
                          limit=None, loc_ids=None, peaks=False, brief=False, wide=False):
        """센서 이력 — 대상 하나(`loc_id`) 또는 여럿(`loc_ids`, 최대
        MAX_READ_TARGETS). 대상은 unique_id 또는 이름(장치·구역·작물)이다.
        여럿이면 {"count", "results": [대상마다 단수 응답 + requested]}.

        `brief` 는 도구 스키마에 없는 처리기 인자다 — 도메인 표면(measure.history)만
        켠다(`registry_data` 의 defaults_by_kind). 켜면 측정 항목(`sensor_type`)도
        `limit` 도 안 준 호출은 채널마다 최소·최대·평균·건수와 최소·최대 시각 한 줄만 낸다(값 목록 없음).
        그 둘 중 하나라도 주면 값 목록이지만 **최근 N 건이 아니라 기간 전체를 N 칸으로 나눈 평균**이다
        (기본 24칸, 채널이 셋 이상이면 6칸; 건수가 N 이하면 원값 그대로). 통계에는 `min_at`·`max_at`.
        '어제 온도' 에 밤 11시대 20건만 가 추이를 답하지 못하던 자리다(2026-11-09 음성 시험). 구역 응답의
        `zone_pick` 은 규칙 문장 없이 짧다. 인앱 AI·날씨·트윈·화면 값 읽기는 이 인자를 안 주므로 응답이
        바뀌지 않는다.

        `wide` 도 스키마에 없다 — `weather.now` 만 켠다. 'weather' 묶음에 구름·일사를 더하고, 줄마다 채널
        이름(`channel`)을, 강수량 줄에 기간 합(`stats.sum`)을 싣는다."""
        tokens, err = cls._targets_arg(loc_id, loc_ids, 'loc_id')
        if err:
            return err
        if len(tokens) == 1:
            return cls._sensor_detail_one(tokens[0], sensor_type=sensor_type,
                                          time_range=time_range, limit=limit, peaks=peaks,
                                          brief=brief, wide=wide)
        out = cls._for_each_target(tokens, lambda t: cls._sensor_detail_one(
            t, sensor_type=sensor_type, time_range=time_range, limit=limit, peaks=peaks,
            brief=brief, wide=wide))
        if brief and isinstance(out, dict):
            # 대상마다 같은 `next` 를 되풀이하지 않는다 — 위로 한 번만.
            nxt = None
            for r in out.get('results') or []:
                if isinstance(r, dict) and isinstance(r.get('next'), dict):
                    got = r.pop('next')
                    nxt = nxt or got
                    r.pop('status', None)
            if nxt:
                out = dict({'status': 'success', 'next': nxt}, **out)
        return out

    @classmethod
    def _sensor_loc_by_name(cls, name):
        """이름 → 장치·구역 unique_id, 모호하면 후보 dict, 못 찾으면 None.

        장치 이름 정확일치가 먼저다(get_device_detail 과 같은 해석 — 센서·
        집계 함수·출력). 장치 표식 도형도 같은 이름을 갖기 때문에, 곳 리졸버를
        먼저 쓰면 센서 이름이 "센서 없는 구역" 으로 풀린다. 장치가 아니면 쓰기
        도구와 같은 곳 리졸버(`_resolve_explain` — 정확일치·한정어·작물 이름).
        그래도 없으면 None — 아래 옛 부분일치(구역 이름)로 넘어간다."""
        row, kind, derr = cls._resolve_device_target(name)
        if row is not None:
            # 출력(천창·측창·커튼·분무)도 duty_cycle·duration_time 기록이 있어 이력을 읽는다.
            return row.unique_id
        if derr and derr.get("needs_disambiguation"):
            derr = dict(derr, status="needs_disambiguation",
                        _reading=[cls._READ_AMBIGUOUS_READING])
            return derr
        from aot.services.resolvers.device_resolver import AI_EXCLUDED
        if derr and derr.get("reason_code") == AI_EXCLUDED:
            return derr
        try:
            detail = cls._resolve_explain(name)
        except Exception as e:                              # noqa: BLE001
            logger.debug("_sensor_loc_by_name resolve failed: %s", e)
            detail = None
        if detail is not None:
            tid, ttype = detail['result'][0], detail['result'][1]
            if ttype == 'ambiguous':
                return cls._read_ambiguity(name, cls._public_places(
                    cls._describe_places(detail['places'], detail['devices'], detail.get('plots', ()))))
            if tid and ttype == 'plot':
                place, _err = cls._read_place(name)
                return place.unique_id if place is not None else None
            if tid:
                return tid
        return None

    @classmethod
    def _sensor_detail_one(cls, loc_id, sensor_type=None, time_range="24h",
                           limit=None, peaks=False, brief=False, wide=False):
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
            # 이름으로 왔으면 먼저 id 로 푼다(3-A). id 모양이면 아래가 직접 본다.
            if loc_id and not _looks_like_uuid(loc_id):
                by_name = cls._sensor_loc_by_name(str(loc_id).strip())
                if isinstance(by_name, dict):
                    return by_name
                if by_name:
                    loc_id = by_name
            # 측정 이름 정규화를 **장치 선택보다 먼저** 한다. 예전에는 장치를
            # 먼저 고르고 나서 걸렀기 때문에, 구역에 습도 센서가 있어도 먼저
            # 뽑힌 장치에 습도가 없으면 "No measurements matching type" 이
            # 나갔다 — 있는 것을 없다고 답하는 자리였다.
            normalized_type = cls._normalize_sensor_type(sensor_type)
            # 도메인 표면에서 측정 항목도 limit 도 안 정했다 — 채널마다 값 몇 건이 아니라
            # 통계 한 줄이면 된다(최근값은 항목을 지정하면 예전 모양으로).
            summarize = bool(brief) and not normalized_type and not limit
            target_zone = None
            _place_err = None
            zone_candidates = []

            # 1. 대상 식별 (Input 우선: unique_id 또는 map_config_id/geo_id 지원)
            # 'AI 판단에 포함' 을 끈 센서는 읽지 않는다 — id 로 지목했으면
            # 이유를 돌려준다(device_resolver.ai_excluded).
            from aot.services.resolvers.device_resolver import (
                AI_EXCLUDED, ai_excluded, ai_excluded_error)
            _inputs = Input.query.filter(
                # [P2] 지도 uuid 로 들어오면 그 지도에 배치된 장치를 찾는다.
                or_(Input.unique_id == loc_id,
                    Input.unique_id.in_(_devices_on_map_p2(loc_id)))
            ).all()
            target_input = next((i for i in _inputs if not ai_excluded(i)), None)
            if target_input is None:
                _named = next((i for i in _inputs if i.unique_id == loc_id), None)
                if _named is not None:
                    return {"error": ai_excluded_error(_named),
                            "reason_code": AI_EXCLUDED}

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

            # 출력 장치 — 센서와 같은 DeviceMeasurements·Influx 규약(duty_cycle·duration_time).
            is_output = False
            if not target_input:
                _out = Output.query.filter_by(unique_id=loc_id).first()
                if _out is not None:
                    if ai_excluded(_out):
                        return {"error": ai_excluded_error(_out),
                                "reason_code": AI_EXCLUDED}
                    target_input, is_output = _out, True

            if not target_input:
                # 구역 — 장소 해석은 정본 헬퍼 하나(`_read_place`)로. 예전에는
                # 여기서 (1) 지도 id 로도 그 지도의 아무 도형을, (2) 이름은 모든
                # 도형을 양방향 부분일치로 훑어 **처음 걸린 것**을 집었다 — 같은
                # 이름의 장소가 여럿이면 어느 것이 나올지 정해져 있지 않았고, 다른
                # 장소 인자와 해석이 달랐다(2026-10-08). 이제 모호하면 후보를,
                # 지도 id 면 "지도다" 를, 장치 이름이면 그렇다고 돌려준다.
                target_zone, _place_err = cls._read_place(loc_id, arg='loc_id')
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
                if _place_err and _place_err.get('reason') == 'map_id_given_for_place':
                    return _place_err
                if _place_err and _place_err.get('candidates'):
                    return _place_err
                return {"error": f"Device or zone not found: {loc_id}",
                        **({k: v for k, v in _place_err.items() if k != 'error'}
                           if _place_err else {})}

            # 2. 측정값 정보 획득
            def _measurements_for(dev):
                """이 장치의 측정 중 물어본 종류만. 없으면 빈 리스트."""
                rows = DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == dev.unique_id).all()
                if not rows or not normalized_type:
                    return rows
                if normalized_type == 'weather':
                    # 'weather' 는 대기 관련 측정 여러 개를 한꺼번에 가리킨다.
                    _words = _WEATHER_METRIC_KEYWORDS + (_WEATHER_SKY_KEYWORDS if wide else ())
                    return [m for m in rows
                            if any(wm in (m.measurement or "").lower() for wm in _words)]
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
                    target_input, device_measurements, is_function=is_function,
                    is_output=is_output)
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
            # 날짜 구간('FROM/TO') — '지금부터 거슬러 N' 으로는 지난주와 이번 주를 나란히
            # 볼 수 없다(2026-10-14 사용자 시험). 그곳 현지 날짜로 푼다. 인자를 따로 두지
            # 않고 time_range 가 받는다 — 도구 목록 크기가 상한에 닿아 있다.
            window = None
            start, end = cls._date_span(time_range)
            if start:
                window, werr = cls._detail_window(
                    start, end, target_zone.unique_id if target_zone is not None
                    else target_input.unique_id)
                if werr:
                    return werr
            if not window and not cls._range_ok(time_range):
                return cls._bad_range(time_range)
            span = window['label'] if window else "the last %s" % time_range

            # 기간의 양 끝(UTC) — 도메인 표면이 값을 기간 전체에 펼칠 때 칸을 나누는 기준.
            if window:
                _span_utc = (parse_utc(window['start_utc']), parse_utc(window['end_utc']))
            else:
                _t1 = utc_now()
                _span_utc = (_t1 - timedelta(seconds=offset_sec), _t1)
            _tzc = {}

            def _read_series(dev, measurements):
                """한 장치의 측정들을 읽어 시계열 목록으로. 데이터 없으면 []."""
                out = []
                # 채널이 여럿이면(sensor_type 을 안 좁혔거나 'weather' 처럼
                # 여러 측정을 한꺼번에 묶는 경우) 채널마다 기본 20건씩 실으면
                # 응답이 채널 수에 비례해 불어난다(실측: 기상 채널 6~8개 ×20건
                # 이 get_weather 응답 6~7천자의 대부분이었다). limit 을 명시하지
                # 않았을 때만 기본을 줄인다 — 하나만 물었으면(가장 흔한 질문)
                # 그대로 20건을 지킨다. `total_readings`/`stats`(최소·최대·평균)
                # 는 잘린 것과 무관하게 **전체 구간** 기준이라 줄여도 통계는
                # 그대로 남는다.
                _default_keep = 20 if len(measurements) <= 2 else 5
                if brief:
                    # 도메인 표면은 기간 전체에 고르게 펼친다 — 한 시간 간격이면 하루가 한눈에 든다.
                    _default_keep = 24 if len(measurements) <= 2 else 6
                for m in measurements:
                    conversion = Conversion.query.filter(Conversion.unique_id == m.conversion_id).first() if m.conversion_id else None
                    channel, unit, measurement = return_measurement_info(m, conversion)

                    data = read_influxdb_list(
                        dev.unique_id,
                        unit,
                        channel,
                        measure=measurement,
                        duration_sec=None if window else offset_sec,
                        start_str=window['start_utc'] if window else None,
                        end_str=window['end_utc'] if window else None,
                        datetime_obj=True
                    )

                    if data and summarize:
                        values = [row[1] for row in data]
                        min_at, max_at = cls._peak_times(data, values, dev.unique_id, _tzc)
                        out.append({
                            "device_name": dev.name or dev.unique_id,
                            "device_kind": ("function" if is_function else
                                            "output" if is_output else "input"),
                            "measurement": measurement or m.measurement,
                            "name": getattr(m, 'name', None) or "",
                            "unit": unit,
                            "min": round(min(values), 2),
                            "min_at": min_at,
                            "max": round(max(values), 2),
                            "max_at": max_at,
                            "avg": round(sum(values) / len(values), 2),
                            "count": len(values)})
                    elif data:
                        # Rows are tz-aware UTC (InfluxDB client) — display in this
                        # device's own location time (resolved once per measurement,
                        # not per row) for the same reason as _get_last_values_fallback above.
                        # 위치를 못 풀어도 UTC 로 떨어지지 않는다(농장 시각).
                        readings = [{"t": iso_at(row[0], dev.unique_id, _tzc),
                                     "v": round(row[1], 2), "u": unit} for row in data]
                        values = [row[1] for row in data]
                        _keep = int(limit) if limit else _default_keep
                        _row = {
                            "device_name": dev.name or dev.unique_id,
                            # 함수 값은 계산된 것(예: 센서 여럿의 평균, VPD)이다.
                            # 구분해 내보내지 않으면 직접 잰 값으로 보고된다.
                            "device_kind": ("function" if is_function else
                                            "output" if is_output else "input"),
                            "measurement": measurement or m.measurement,
                            "readings": readings[-_keep:],  # limit 파라미터로 조절 (기본 20건)
                            "total_readings": len(readings),
                            "stats": {
                                "min": round(min(values), 2),
                                "max": round(max(values), 2),
                                "avg": round(sum(values) / len(values), 2),
                                "count": len(values)
                            }
                        }
                        if brief:
                            # 도메인 표면: 최근 N 건이 아니라 기간 전체를 N 칸으로 나눈 평균.
                            # '어제 온도' 에 밤 11시대 20건만 가던 자리다(2026-11-09 음성 시험).
                            if len(readings) > _keep:
                                _row["readings"], _slot = cls._spread_readings(
                                    data, _keep, _span_utc, unit, dev.unique_id, _tzc)
                                _row["readings_shown"] = (
                                    "%d averages of %s slots across the period; stats cover all "
                                    "%d readings. samples=N sets how many." % (
                                        len(_row["readings"]), _slot, len(readings)))
                            _row["stats"]["min_at"], _row["stats"]["max_at"] = cls._peak_times(
                                data, values, dev.unique_id, _tzc)
                        elif peaks:
                            # 극값의 시각 — 날씨 요약이 "최고기온은 몇 시" 를 답하는 근거.
                            # 전체 구간 기준이고 `peaks` 를 켠 호출에만 싣는다(다른 응답 크기 그대로).
                            _row["stats"]["max_at"] = readings[values.index(max(values))]["t"]
                            _row["stats"]["min_at"] = readings[values.index(min(values))]["t"]
                        if wide:
                            _row["channel"] = getattr(m, 'name', None) or ""
                            _row["stats"].update(cls._rain_sum_stats(dev, m, measurement, unit, data))
                        # 보여 준 것이 전부가 아니면 그렇다고 적는다 — '전체 6건'
                        # 옆에 5건만 있으면 모순으로 읽혔다(2026-10-09 외부 점검).
                        # 통계는 전체 기준이다.
                        if window:
                            _row["period"] = window['period']
                        if len(readings) > _keep and not brief:
                            _row["readings_shown"] = (
                                "latest %d of %d; stats cover all %d. Pass limit "
                                "for more." % (_keep, len(readings), len(readings)))
                        out.append(_row)
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
                if summarize:
                    return cls._history_brief(
                        results, target_input,
                        zone_candidates if len(zone_candidates) > 1 else [],
                        None if window else time_range,
                        window['period'] if window else None)
                if zone_candidates and len(zone_candidates) > 1:
                    _note = (cls._zone_pick_slim(target_input, zone_candidates)
                             if brief else
                             cls._zone_pick_note(target_input, zone_candidates))
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
                        f"No data in {span} from any of the "
                        f"{len(_tried)} device(s) tried in this zone."),
                    "time_range": None if window else time_range,
                    **({"period": window['period']} if window else {}),
                    "zone_pick": cls._zone_pick_note(
                        target_input, zone_candidates, searched_all=True),
                }
            return {
                "message": f"No data for device '{target_input.name}' in {span}.",
                "device_id": target_input.unique_id,
                "time_range": None if window else time_range,
                **({"period": window['period']} if window else {}),
            }

        except Exception as e:
            logger.exception("Error in get_sensor_detail")
            return {"error": f"Error while querying sensor data: {str(e)}"}

    _HISTORY_BRIEF_COLUMNS = ("measurement", "unit", "min", "min_at", "max", "max_at", "avg", "count")

    @staticmethod
    def _minute_iso(dt, where, cache):
        """사람이 읽는 시각 — 그곳 시계, 분까지(초·마이크로초는 뗀다: '2026-11-08T14:05+09:00')."""
        return parse_utc(dt).astimezone(tz_of(where, cache)).isoformat(timespec='minutes')

    @classmethod
    def _peak_times(cls, data, values, where, cache):
        """전체 구간에서 최솟값·최댓값이 처음 나온 시각 — "최고 온도는 몇 시" 의 근거."""
        return (cls._minute_iso(data[values.index(min(values))][0], where, cache),
                cls._minute_iso(data[values.index(max(values))][0], where, cache))

    @classmethod
    def _spread_readings(cls, data, n, span_utc, unit, where, cache):
        """기간을 `n` 칸으로 똑같이 나눠 칸마다 평균 한 점(`t` = 칸 시작). 값 없는 칸은 빠진다(끊김이 보인다).

        최근 N 건으로 자르면 '어제 온도' 가 밤 11시대만 남는다. 칸 길이 문장도 함께 돌려준다."""
        t0, t1 = span_utc
        first, last = parse_utc(data[0][0]), parse_utc(data[-1][0])
        t0, t1 = min(t0, first), max(t1, last)
        width = max((t1 - t0).total_seconds() / max(int(n), 1), 1.0)
        sums = {}
        for t, v in data:
            k = min(int((parse_utc(t) - t0).total_seconds() // width), int(n) - 1)
            acc = sums.setdefault(k, [0.0, 0])
            acc[0] += v
            acc[1] += 1
        points = [{"t": cls._minute_iso(t0 + timedelta(seconds=k * width), where, cache),
                   "v": round(tot / cnt, 2), "u": unit}
                  for k, (tot, cnt) in sorted(sums.items())]
        mins = width / 60.0
        slot = ("%d min" % round(mins) if mins < 90 else
                "%g h" % round(mins / 60.0, 1) if mins < 2880 else
                "%g days" % round(mins / 1440.0, 1))
        return points, slot

    @classmethod
    def _history_brief(cls, rows, device, zone_candidates, time_range, period):
        """항목을 정하지 않은 이력 — 채널마다 최소·최대·평균·건수 한 줄(최근값 없음).

        값은 값 있는 모양과 같은 계산이다(반올림 포함). 더 받는 길은 `next` — 항목을 정하면
        그 채널의 최근값이 예전 모양으로 온다."""
        out = {"status": "success",
               "next": {
                   "call": ("measure(op='history', target=<same target>, "
                            "measurement=<a measurement from channels>) gives that channel's "
                            "readings spread across the period, the trend (samples=N sets how many)"),
                   "why": "no measurement named: channel statistics only, no readings"
                          + ("; one device answered for the zone - "
                             "measure(op='latest', target=<the zone>) reads every sensor of it"
                             if zone_candidates else "")},
               "device_name": rows[0]["device_name"],
               "device_kind": rows[0]["device_kind"]}
        if time_range:
            out["time_range"] = time_range
        if period:
            out["period"] = period
        # 채널마다 한 줄 — 열 이름은 한 번만(채널이 수십 개일 때 키 되풀이가 절반이었다).
        # 같은 측정 이름이 채널 여럿에 있어도(예보의 `rain` 16개) 줄을 알아보게, 이름이 있는 채널이
        # 하나라도 있으면 `name` 열을 더한다.
        cols = list(cls._HISTORY_BRIEF_COLUMNS)
        if any(r["name"] and r["name"] != r["measurement"] for r in rows):
            cols.insert(1, "name")
        out["channels"] = {"columns": cols, "rows": [[r[k] for k in cols] for r in rows]}
        if zone_candidates:
            out["zone_pick"] = cls._zone_pick_slim(device, zone_candidates)
        return out

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

    #: 위치 유형 정렬 — 시설 → 노지 → 실외(참고) → 그 밖.
    _GROUP_KIND_ORDER = {'facility': 0, 'open_field': 1, 'outdoor': 2}
    _GROUP_DEVICE_NAMES = 3

    #: 대지 한 줄에 싣는 대표 측정(저장 이름) — 나머지는 대상을 주면 나온다.
    _SITE_LINE_MEASUREMENTS = ('temperature', 'humidity', 'vapor_pressure_deficit',
                               'volumetric_water_content')

    @classmethod
    def _top_level_places(cls, shapes):
        """대지(site) 전부 + 어느 대지에도 안 든 구역. 구역은 자기 대지의 줄에 들어간다.

        대지 밖 구역을 빼면 그 구역의 센서가 대상 없는 요약에서 통째로 사라진다."""
        from aot.space.device_membership import PlaceIndex
        site_uids = [s.unique_id for s in shapes if s.type == 'site']
        try:
            idx = PlaceIndex()
        except Exception:                                   # noqa: BLE001
            logger.debug("zone summary: place index failed", exc_info=True)
            return [s for s in shapes if s.type == 'site'] or list(shapes)
        out = []
        for s in shapes:
            if s.type == 'site' or not any(
                    idx.within(s.unique_id, su) for su in site_uids):
                out.append(s)
        return out

    @classmethod
    def _site_lines(cls, zones_out, skipped, time_range, degraded=False):
        """대상 없는 요약 → 대지마다 한 줄.

        한 줄 = 대지 이름 + (위치 유형, 매질)별 대표 측정 평균(`avg`, 채널의 최신값 평균 — `groups` 와 같은
        식·같은 반올림) + 멈춘 장치 수. 센서가 없거나 환경 값이 없는 대지는 이름만 `no_environment_data` 에
        모은다 — 빠진 곳이 없어야 한다. 단위는 한 번만(`units`), 다른 단위로 온 것만 그 줄에서 밝힌다."""
        keep = cls._SITE_LINE_MEASUREMENTS
        units, lines, empty = {}, [], [z["zone_name"] for z in skipped]
        for z in zones_out:
            groups = []
            for g in z.get("groups") or []:
                avg, over = {}, {}
                for a in g.get("avg") or []:
                    m = a["measurement"]
                    if m not in keep or m in avg:
                        continue
                    avg[m] = a["avg_last"]
                    if units.setdefault(m, a["unit"]) != a["unit"]:
                        over[m] = a["unit"]
                if not avg:
                    continue
                row = {"placement": g["placement"], "medium": g["medium"],
                       "devices": g["n_devices"], "avg": avg}
                if over:
                    row["units"] = over
                if g.get("reference"):
                    row["reference"] = True
                groups.append(row)
            silent = z.get("stale_excluded_count") or 0
            if not groups and not silent:
                empty.append(z["zone_name"])
                continue
            line = {"site": z["zone_name"]}
            if z.get("zone_type") != "site":
                line["kind"] = z.get("zone_type")
            line["groups"] = groups
            if silent:
                line["silent_devices"] = silent
            lines.append(line)
        total = len(lines) + len(empty)
        out = {
            "status": "success",
            "next": {
                "call": ("measure(op='latest', target=<a site name from sites>) gives that place's zones "
                         "and sensors; measurement=<name> instead compares every zone on one measurement"),
                "why": ("no target: one line per site, %d of %d sites have environment values; "
                        "measure(op='freshness') names the silent devices" % (len(lines), total))},
            "scope": "farm", "time_range": time_range, "count": len(lines),
            "basis": ("avg = mean of each device's latest reading, not a period average; forecast-model, "
                      "inactive, silent and unplaced devices are left out; 'reference' groups (outdoor) "
                      "are never mixed with the site's own"),
            "units": units,
            "sites": lines}
        if empty:
            out["no_environment_data"] = empty
        if degraded:
            out["warning"] = ("InfluxDB returned nothing for any series - this may be a read failure, "
                              "not an absence of data.")
        return out

    @classmethod
    def _zone_groups(cls, readings, placements, chan_medium, inactive, too_old,
                     index, status_of=None, fold_places=False):
        """한 장소의 센서 항목들 → `(groups, excluded, stale_excluded)`.

        그룹 = 같은 위치 유형(placement)·같은 장소·같은 매질(air/soil). 매질은
        장치가 아니라 **채널**로 판정하므로(`channel_medium`) 공기 채널과 토양
        채널을 둘 다 가진 복합 측정장치는 두 그룹에 모두 나온다.

        평균에서 빼는 것: 예보 모델 값(model) · 비활성 장치(inactive) · 위치를
        모르는 센서(unplaced) · 방위값(bearing) · 통신 채널(link_channel) ·
        오래된 값(stale — 정본 신선도). 실외(outdoor) 그룹은 참고값이라
        `reference: true` 로 표시하고 시설/노지 그룹과 섞지 않는다.

        `fold_places` 면 장소(구역·시설)를 가리지 않고 (위치 유형, 매질)로만 묶는다 — 대지 한
        줄용(`_site_lines`). 평균은 같은 식(채널의 최신값 평균)을 합친 채널 전체에 쓴다.
        """
        groups, excluded, seen, stale = {}, [], set(), {}

        def _name_of(uid):
            sh = (index.by_uid.get(uid) if index is not None else None)
            if sh is None:
                sh = GeoShape.query.filter(GeoShape.unique_id == uid).first()
            if sh is None:
                return None
            # PlaceIndex 의 경량 레코드(ShapeRec)는 이름을 `name` 으로 가진다.
            return (getattr(sh, 'name', None) if not hasattr(sh, 'feature')
                    else cls._shape_display_name(sh)) or None

        def _ex(d, reason, channel=None):
            key = (d["device_id"], reason, channel)
            if key in seen:
                return
            seen.add(key)
            row = {"device": d["device_name"], "reason": reason}
            if channel:
                row["channel"] = channel
            excluded.append(row)

        for d in readings:
            did = d["device_id"]
            pl = placements.get(did)
            kind = (pl.kind if pl is not None else
                    ("outdoor" if d.get("location") == "outdoor" else "unknown"))
            if d.get("data_origin"):
                _ex(d, "model")
                continue
            if did in inactive:
                _ex(d, "inactive")
                continue
            if status_of and did in status_of:
                # 수리 중·철거됨·점검 중 — 값이 신뢰 불가라 평균에서 뺀다.
                _ex(d, "device_status:%s" % status_of[did])
                continue
            if kind == "unplaced":
                _ex(d, "unplaced")
                continue
            pid = None
            if pl is not None:
                pid = (pl.facility_uid if kind == "facility" and pl.facility_uid
                       else pl.place_uid)
                if kind == "outdoor" and pid:
                    # 실외는 장소가 아니라 그 대지의 기준값이다 — 기상원과 시설
                    # 외기 설비가 한 그룹이 되도록 대지로 모은다.
                    try:
                        from aot.space.device_membership import (
                            weather_place_for)
                        pid = weather_place_for(pid, index=index) or pid
                    except Exception:                       # noqa: BLE001
                        pass
            for c in d["channels"]:
                med = chan_medium.get((did, c.get("channel")), "air")
                if med == "other":
                    _ex(d, "link_channel", c.get("measurement"))
                    continue
                if c.get("unit") == "bearing":
                    _ex(d, "bearing", c.get("measurement"))
                    continue
                lt = c.get("last_time") or d.get("last_time")
                if too_old(did, lt):
                    stale[did] = {"device": d["device_name"], "last_time": lt,
                                  "device_id": did, "reason": "stale"}
                    continue
                g = groups.setdefault((kind, None if fold_places else pid, med), {
                    "devs": {}, "acc": {}})
                g["devs"][did] = d["device_name"]
                # 채널 단위 — 한 장치가 같은 이름·단위의 채널을 여럿 가지면 모두
                # 평균에 들어간다(예전엔 장치당 첫 값 하나만 반영됐다).
                a = g["acc"].setdefault((c["measurement"], c["unit"]),
                                        {"v": {}, "raw": None})
                a["v"].setdefault((did, c.get("channel")), c["last_value"])
                if c.get("raw_measurement"):
                    a["raw"] = c["raw_measurement"]

        out = []
        for (kind, pid, med), g in groups.items():
            names = sorted(g["devs"].values())
            row = {"placement": kind, "place_id": pid,
                   "place_name": _name_of(pid) if pid else None,
                   "medium": med, "n_devices": len(g["devs"]),
                   "devices": names[:cls._GROUP_DEVICE_NAMES]}
            if len(names) > cls._GROUP_DEVICE_NAMES:
                # 이름은 대표만 — 나머지가 몇인지 밝혀 n_devices 와 맞춘다.
                row["devices_more"] = len(names) - cls._GROUP_DEVICE_NAMES
            avg = []
            for (m, u), a in sorted(g["acc"].items(),
                                    key=lambda kv: str(kv[0])):
                v = a["v"]
                e = {"measurement": m, "unit": u,
                     "avg_last": round(sum(v.values()) / len(v), 2),
                     "n": len(v)}              # n = 채널 수
                nd = len({k[0] for k in v})
                if nd != len(v):
                    e["n_devices"] = nd        # 장치 수 — 채널 수와 다를 때만
                if a["raw"]:
                    e["raw_measurement"] = a["raw"]
                avg.append(e)
            row["avg"] = avg
            if kind == "outdoor":
                row["reference"] = True
            out.append(row)
        out.sort(key=lambda r: (cls._GROUP_KIND_ORDER.get(r["placement"], 3),
                                str(r["place_name"] or ""),
                                r["medium"] != "air"))
        return out, excluded, list(stale.values())

    @classmethod
    @tz_scoped
    def get_zone_sensor_summary(cls, zone_ids=None, measurement_type=None,
                                time_range="7d", detail=False, _detail=False,
                                brief=False, **extra):
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

        **기본 응답은 그룹별 요약(`groups`)이다.** 같은 위치 유형(placement)·
        같은 장소·같은 매질(air/soil)끼리 묶어 평균을 낸다. 한 장치가 공기
        채널과 토양 채널을 둘 다 가지면(복합 측정장치) 두 그룹에 모두 나온다 —
        매질은 장치가 아니라 채널로 판정한다. 개별 센서 목록(`sensors`)과 호환
        키(`indoor`/`outdoor`/`indoor_avg`)는 `detail=true` 일 때만 싣는다.
        `detail` 은 도구 스키마에 없는 메타 인자다(도구 목록 토큰 예산 때문) —
        응답의 `detail_hint` 가 알린다.

        **`brief` 도 스키마에 없는 처리기 인자다 — 도메인 표면(measure.summary, 대상 없음)만 켠다.**
        켜고 `zone_ids`·`measurement_type` 이 둘 다 없으면 곳마다의 평균 대신 **대지마다 한 줄**
        (`_site_lines`)을 낸다 — 대지는 빠짐없이, 25곳에서 자르지 않는다. 대상이나 측정 종류를
        주면 이 인자는 아무 일도 하지 않고 예전 모양 그대로다. 인앱 AI(개요)는 안 켠다.
        """
        detail = bool(detail or _detail) and str(detail or _detail).lower() \
            not in ('false', '0', 'no', 'off', '')
        brief_sites = bool(brief) and not zone_ids and not measurement_type
        try:
            from aot.utils.influx import read_influxdb_list
            from aot.space.device_membership import (
                PlaceIndex, channel_medium, classify_sensors, place_members,
                place_members_split)

            past_sec = cls._parse_range(time_range)

            if isinstance(zone_ids, str):
                zone_ids = [zone_ids]
            unresolved, available = [], None
            if zone_ids:
                # id 가 아니면 이름으로 푼다(3-A). 이름이 여럿에 걸리면 고르지
                # 않는다 — 하나뿐이면 후보를 그대로, 여럿 중 일부면 나머지는
                # 답하고 걸린 이름을 `unresolved` 로 함께 낸다.
                tokens = []
                for z in zone_ids:
                    t = str(z or '').strip()
                    if t and t not in tokens:
                        tokens.append(t)
                if len(tokens) > cls.MAX_READ_TARGETS:
                    return {"error": ("At most %d zones per call (%d given) — "
                                      "split them into several calls."
                                      % (cls.MAX_READ_TARGETS, len(tokens)))}
                shapes = GeoShape.query.filter(
                    GeoShape.unique_id.in_(tokens)).all()
                found = {s.unique_id for s in shapes}
                for tok in tokens:
                    if tok in found:
                        continue
                    place, perr = cls._read_place(tok, arg='zone_ids')
                    if place is not None:
                        if place.unique_id not in found:
                            found.add(place.unique_id)
                            shapes.append(place)
                    else:
                        unresolved.append(dict({"requested": tok}, **perr))
                # 곳 이름 목록(available_targets)은 이름마다 같은 것이 붙는다 —
                # 한 번만 위로 올린다.
                for u in unresolved:
                    av = u.pop("available_targets", None)
                    if av is not None and available is None:
                        available = av
                if unresolved and not shapes:
                    if len(unresolved) == 1:
                        out = dict(unresolved[0])
                    else:
                        out = {"error": "none of the zones could be resolved",
                               "unresolved": unresolved}
                    if available is not None:
                        out["available_targets"] = available
                    return out
            else:
                shapes = [s for s in GeoShape.query.filter(
                    GeoShape.type.in_(('site', 'zone'))).order_by(GeoShape.id).all()
                    if cls._shape_display_name(s)]
                if brief_sites:
                    shapes = cls._top_level_places(shapes)
            if not shapes:
                return {"error": "no zone/site found"}

            # 특정 구역을 안 물으면(전 농장) 기본 상한을 둔다 — 넓은 농장에서
            # zone_ids/measurement_type 둘 다 없는 호출이 응답 크기의 꼬리를
            # 만든다(실측 최대 10,605자). zone_ids 로 좁혀 부르면 이 상한에
            # 걸리지 않는다.
            _ZONE_SUMMARY_DEFAULT_LIMIT = 25
            zones_truncated = False
            # 상한은 장치가 있는 곳을 먼저 채운다(2026-10-09). 예전에는 생성순
            # 앞 25곳이라 장치 없는 공원 구역이 자리를 차지하고 그린하트바이오·
            # 배밭1·구산리 같은 곳이 어느 목록에도 안 나왔다. 측정 종류를 주면
            # 응답이 작아 상한을 걸지 않는다 — 안내문이 그렇게 말해 왔는데
            # 조건은 zone_ids 만 보고 있었다.
            if (not zone_ids and not measurement_type and not brief_sites
                    and len(shapes) > _ZONE_SUMMARY_DEFAULT_LIMIT):
                zones_truncated = len(shapes)
                _has = {}
                for _s in shapes:
                    try:
                        _has[_s.unique_id] = bool(place_members(_s.unique_id))
                    except Exception:                       # noqa: BLE001
                        _has[_s.unique_id] = True
                shapes = sorted(shapes, key=lambda _s: not _has.get(_s.unique_id))
                shapes = shapes[:_ZONE_SUMMARY_DEFAULT_LIMIT]

            wanted = (cls._device_ids_with_measurement(measurement_type)
                      if measurement_type else None)

            # 1) 구역 → 장치. 2) 장치 → 측정 채널. 여기까지가 SQL 이다.
            # 'AI 판단에 포함' 을 끈 장치는 빼고 센다(device_resolver).
            from aot.services.resolvers.device_resolver import ai_excluded_ids
            hidden = ai_excluded_ids()
            #
            # 실내/실외를 가른다(B1). 실외 = 그 장소를 감싸는 대지의 기상원
            # (지정 우선, 없으면 추론). 구역을 콕 집어 물으면 소속이 아니어도
            # 대지 기상대를 실외 기준으로 싣는다. 개요(zone_ids 없음)에서는
            # 구역마다 같은 기상대가 되풀이되지 않게, 구역은 자기 소속인
            # 실외 장치만 싣고 대지 기상대는 대지 항목에 한 번만 둔다.
            try:
                _pidx = PlaceIndex()
            except Exception:                               # noqa: BLE001
                _pidx = None
            per_zone, all_ids = [], set()
            outdoor_of, loc_source_of = {}, {}
            for shape in shapes:
                try:
                    split = place_members_split(shape.unique_id, index=_pidx)
                except Exception:                           # noqa: BLE001
                    logger.debug("zone summary: indoor/outdoor split failed "
                                 "for %s", shape.unique_id, exc_info=True)
                    split = None
                if split is None:
                    members = place_members(shape.unique_id) or set()
                    outdoor, lsrc = set(), 'none'
                else:
                    members = set(split['members'])
                    outdoor, lsrc = set(split['outdoor']), split['source']
                    if zone_ids or brief_sites or getattr(shape, 'type', None) == 'site':
                        members = members | outdoor
                ids = members - hidden
                if wanted is not None:
                    ids = ids & wanted
                per_zone.append((shape, ids))
                outdoor_of[shape.unique_id] = outdoor & ids
                loc_source_of[shape.unique_id] = (
                    'bound' if lsrc == 'bound' else 'inferred')
            # 장소를 지정하지 않은 개요에서는 대지가 자기 구역의 장치를 다시
            # 싣지 않는다 — 소속은 자손을 포함하므로(3포장 = 3-1 + 3-2 + 직속)
            # 같은 장치가 대지와 구역에 두 번 나와 응답이 두 배가 됐다
            # (2026-10-09 실측 20,354토큰). 대지에는 어느 구역에도 안 든 직속
            # 장치만 남긴다. 대지를 콕 집어 물으면 그대로 전부 낸다.
            site_direct_only = False
            folded_away = set()     # 구역으로 다 넘어가 비게 된 대지 — '데이터 없음' 이 아니다
            if not zone_ids and not brief_sites:
                try:
                    from aot.space.device_membership import PlaceIndex
                    _idx = PlaceIndex()
                    _shown = [(sh, ids) for sh, ids in per_zone if ids]
                    _trimmed = []
                    for sh, ids in per_zone:
                        if ids and getattr(sh, 'type', None) == 'site':
                            for other, oids in _shown:
                                if other is not sh and _idx.within(
                                        other.unique_id, sh.unique_id):
                                    ids = ids - oids
                                    site_direct_only = True
                            if not ids:
                                folded_away.add(sh.unique_id)
                        _trimmed.append((sh, ids))
                    per_zone = _trimmed
                except Exception as e:                      # noqa: BLE001
                    logger.debug("zone summary: site de-dup skipped: %s", e)
            for _sh, ids in per_zone:
                all_ids |= ids

            if not all_ids and brief_sites:
                return cls._site_lines(
                    [], [{"zone_name": cls._shape_display_name(sh)} for sh, _ids in per_zone],
                    time_range)
            if not all_ids:
                empty = {"count": 0, "zones": [],
                         "message": ("No sensor with that measurement was found in "
                                     "the requested area." if measurement_type else
                                     "No sensor was found in the requested area.")}
                if unresolved:
                    empty["unresolved"] = unresolved
                if available is not None:
                    empty["available_targets"] = available
                if zone_ids and len(shapes) == 1 and not unresolved:
                    cls._with_target(empty, shapes[0].type, shapes[0].unique_id,
                                     ref=zone_ids[0] if len(zone_ids) == 1 else None)
                return empty

            mq = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id.in_(list(all_ids)))
            if measurement_type:
                mq = mq.filter(DeviceMeasurements.measurement.like(
                    "%%%s%%" % str(measurement_type).strip()))
            chans = mq.all()

            # 입력만 보면 장소에 매인 밸브 같은 출력이 이름 대신 ID 로 나갔다
            # (2026-10-09). 장치 종류를 가리지 않고 실제 이름을 찾는다.
            names = cls._device_names(all_ids)
            # 출력(밸브의 동작 시간 등)은 '센서' 목록에 섞여 나가 측정값으로
            # 읽힌다 — 표시를 붙인다(2026-10-09).
            output_ids = {o.unique_id for o in Output.query.filter(
                Output.unique_id.in_(list(all_ids))).all()}
            # 시뮬레이션 장치 표시(표시 전용 — 평균에서 빼지 않는다).
            from aot.tools.sim_marker import sim_fields as _sim_fields
            sim_of = {}
            for _r in Input.query.filter(
                    Input.unique_id.in_(list(all_ids))).all():
                _f = _sim_fields('input', _r.device, _r.name)
                if _f:
                    sim_of[_r.unique_id] = _f
            for _r in Output.query.filter(
                    Output.unique_id.in_(list(all_ids))).all():
                _f = _sim_fields('output', _r.output_type, _r.name)
                if _f:
                    sim_of[_r.unique_id] = _f
            # 예보 모델 값(Open-Meteo 등)은 실측이 아니다 — 표시한다.
            from aot.utils.inputs import model_input_drivers
            _models = model_input_drivers()
            model_ids = ({i.unique_id for i in Input.query.filter(
                Input.unique_id.in_(list(all_ids)),
                Input.device.in_(list(_models))).all()} if _models else set())

            # 종류를 지정하지 않은 요약에서는 통신 상태 채널(배터리·RSSI·SNR)을
            # 뺀다. 센서마다 온도·습도와 같은 비중으로 실려 채널의 절반 가까이를
            # 차지했고, 장소 없이 부르면 응답 상한(15,000토큰)을 넘어 캡이 모든
            # 구역의 센서 목록을 떼어 냈다 — 구역 이름만 남았다(실측 21,965).
            # 판정은 배지·그래프와 같은 함수(channel_meta_for_dm)로 한다.
            link_omitted = 0
            if not measurement_type:
                from aot.space.facility_sensors import (
                    META_CHANNEL_KEYS, channel_meta_for_dm)

            specs, by_device = [], {}
            soil_chans = set()
            rain_chans = {}
            chan_medium = {}
            for m in chans:
                if not measurement_type:
                    try:
                        if channel_meta_for_dm(m).get('key') in META_CHANNEL_KEYS:
                            link_omitted += 1
                            continue
                    except Exception:                       # noqa: BLE001
                        pass
                conv = (Conversion.query.filter(
                    Conversion.unique_id == m.conversion_id).first()
                    if m.conversion_id else None)
                channel, unit, meas = return_measurement_info(m, conv)
                if not unit:
                    continue
                # return_measurement_info()는 변환(Conversion)이 걸린 채널의
                # measurement를 항상 None으로 돌려준다 — Influx 쓰기 쪽
                # (add_measurements_influxdb_flux)도 그 None을 그대로 받아
                # 이런 채널의 포인트에는 "measure" 태그를 아예 안 붙인다.
                # 그래서 `meas`는 read_influxdb_list(measure=...) 필터에는
                # 그대로(None) 넘겨야 한다 — 채워서 넘기면 태그가 없는
                # 포인트를 걸러 버려 데이터가 통째로 안 잡힌다. 화면에 낼
                # 라벨만 DeviceMeasurements.measurement로 폴백한다
                # (get_sensor_detail의 `measurement or m.measurement`와 같은
                # 이유의 같은 폴백 — 쿼리용 변수는 그대로 두고 표시용만 채운다).
                disp_meas = meas or m.measurement
                try:
                    chan_medium[(m.device_id, channel)] = med = channel_medium(m)
                    if med == 'soil':
                        soil_chans.add((m.device_id, channel))
                except Exception:                           # noqa: BLE001
                    pass
                if _is_rain_label(disp_meas, unit, m.name):
                    rain_chans[(m.device_id, channel)] = disp_meas
                specs.append((unit, m.device_id, channel, meas, disp_meas))
                by_device.setdefault(m.device_id, []).append(
                    (unit, channel, meas, disp_meas))

            # 3) 채널마다 한 번씩 읽고 통계는 여기서 센다.
            #
            # **벌크 Flux 로 접지 말 것.** 시리즈를 device_id 집합(`contains`)으로
            # 거르는 쿼리는 인덱스로 내려가지 않아 전량 스캔이 된다 — 실측(센서
            # 5개·7일): query_last_values_bulk 3,612ms · reduce 통계 3,045ms 대
            # 개별 read_influxdb_list 5회 합계 **169ms**. `contains` 벌크가 이기는
            # 것은 장치가 수십 개이고 창이 짧을 때다(query_last_values_bulk
            # docstring 의 지도 위젯 사례). 여기 워크로드는 그 반대다.
            series, degraded = {}, False
            for unit, did, channel, meas, disp_meas in specs:
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

            # 비활성 장치는 평균에서 뺀다(값이 남아 있어도 더는 읽히지 않는다).
            try:
                inactive = {i.unique_id for i in Input.query.filter(
                    Input.unique_id.in_(list(all_ids)),
                    Input.is_activated.is_(False)).all()}
            except Exception:                               # noqa: BLE001
                inactive = set()
            from aot.services.resolvers.device_resolver import known_status_ids
            _status_of = known_status_ids()

            from aot.utils.timekit import iso_at
            _tzc = {}
            # 평균에 쓸 수 있는 값인가의 정본 기준 — 주기 × STALE_PERIOD_FACTOR
            # (하한 FRESH_MAX_AGE_S), 장치에 Input.max_age_s 가 있으면 그것이 이긴다.
            # 멈춘 센서의 옛값이 평균에 섞여 3-2 는 18.2(정상 21.8), 1-2 는
            # 31.6(정상 24.0)이 됐다(리허설 F2/G1).
            _fresh, _max_age = {}, {}
            try:
                from datetime import datetime as _dt, timezone as _tz
                from aot.aot_flask.geo.site_summary import (
                    FRESH_MAX_AGE_S, STALE_PERIOD_FACTOR)
                from aot.utils.measurement_freshness import (
                    effective_max_age, freshness_by_device, lookup)
                _fresh = freshness_by_device(all_ids)
                _now = _dt.now(_tz.utc)
                for _did in all_ids:
                    _p, _m = lookup(_fresh, _did)
                    _max_age[_did] = effective_max_age(
                        None, _p, _m, floor=FRESH_MAX_AGE_S,
                        factor=STALE_PERIOD_FACTOR)
            except Exception:                               # noqa: BLE001
                logger.debug("zone summary: freshness unavailable", exc_info=True)
                _max_age = {}

            def _too_old(did, iso):
                limit = _max_age.get(did)
                if not limit or not iso:
                    return False
                try:
                    t = _dt.fromisoformat(iso)
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=_tz.utc)
                    return (_now - t).total_seconds() > limit
                except (ValueError, TypeError):
                    return False

            zones_out, skipped = [], []
            any_stale = False
            any_outdoor = any_avg = False
            for shape, ids in per_zone:
                _outdoor = outdoor_of.get(shape.unique_id) or set()
                _lsrc = loc_source_of.get(shape.unique_id, 'inferred')
                # 장치마다 한 항목, 채널은 그 아래에 둔다(2026-10-09). 채널마다
                # 한 줄로 두면 장치 ID·이름·시각이 채널 수만큼 되풀이되어, 장소
                # 없이 부를 때 응답 상한을 넘었다(통신 채널을 빼고도 16,963).
                # 시각은 장치의 채널이 모두 같으면 장치에 한 번, 다르면 채널마다.
                readings, out_readings = [], []
                try:
                    _placements = classify_sensors(
                        ids, place_uid=shape.unique_id, index=_pidx)
                except Exception:                           # noqa: BLE001
                    logger.debug("zone summary: placement failed for %s",
                                 shape.unique_id, exc_info=True)
                    _placements = {}
                for did in sorted(ids):
                    chans_out = []
                    for unit, channel, meas, disp_meas in by_device.get(did, []):
                        s = series.get((did, channel, meas))
                        if s is None:
                            continue
                        t, v = s['last']
                        chans_out.append({
                            "channel": channel,
                            "measurement": disp_meas, "unit": unit,
                            "last_value": round(v, 2),
                            # 예전엔 변환 없이 UTC 그대로였다(2026-10-09).
                            "last_time": iso_at(t, did, _tzc),
                            "min": round(s['min'], 2),
                            "max": round(s['max'], 2),
                            "avg": round(s['avg'], 2)})
                        if (did, channel) in soil_chans:
                            chans_out[-1]["medium"] = "soil"
                        if (did, channel) in rain_chans:
                            # 표시용 라벨만 — 저장 measurement 는 그대로 둔다.
                            chans_out[-1]["measurement"] = "precipitation"
                            chans_out[-1]["raw_measurement"] = \
                                rain_chans[(did, channel)]
                    if not chans_out:
                        continue
                    dev = {"device_id": did,
                           "device_name": names.get(did) or did}
                    dev["location"] = ("outdoor" if did in _outdoor
                                       else "indoor")
                    dev["location_source"] = _lsrc
                    _pl = _placements.get(did)
                    if _pl is not None:
                        # 'indoor' 는 시설 안만이다. 노지·미배치를 indoor 로 두면
                        # 노지 구역 센서가 전부 실내로 읽힌다 — 위치 유형이 정본.
                        if _pl.kind in ("open_field", "unplaced"):
                            dev["location"] = _pl.kind
                        dev["placement"] = _pl.kind
                        if _pl.source:
                            dev["placement_source"] = _pl.source
                        if _pl.conflict:
                            dev["placement_conflict"] = _pl.conflict
                    if did in output_ids:
                        dev["device_kind"] = "output"
                    else:
                        dev["device_kind"] = "input"
                        if did in _status_of:
                            dev["device_status"] = _status_of[did]
                        if did in model_ids:
                            dev["data_origin"] = "model"
                    if did in sim_of:
                        dev.update(sim_of[did])
                    times = {c["last_time"] for c in chans_out}
                    if len(times) == 1:
                        dev["last_time"] = times.pop()
                        for c in chans_out:
                            c.pop("last_time", None)
                    dev["channels"] = chans_out
                    # 출력(측창·천창·밸브 등)은 센서 목록에서 떼어 따로 낸다.
                    (out_readings if did in output_ids else readings).append(dev)
                if not readings and not out_readings and \
                        shape.unique_id in folded_away:
                    continue
                if not readings and not out_readings:
                    # zone_id/zone_name 을 여기서 담아 둔다 — 개수만 세면 호출자가
                    # 요청 목록과 응답 목록을 직접 대조해야 "어느 구역인지" 알 수
                    # 있고, 센서가 아예 없던 구역은 이름 조회 기회조차 없다.
                    skipped.append({"zone_id": shape.unique_id,
                                    "zone_name": cls._shape_display_name(shape)})
                    continue
                _in = [d["device_id"] for d in readings
                       if d["location"] == "indoor"]
                _out = [d["device_id"] for d in readings
                        if d["location"] == "outdoor"]
                any_outdoor = any_outdoor or bool(_out)
                _z = {
                    "zone_id": shape.unique_id,
                    "zone_name": cls._shape_display_name(shape),
                    "zone_type": shape.type}
                # 그룹별 평균 — 기본 응답의 본체. 같은 위치 유형·장소·매질끼리 묶고
                # 평균에서 뺀 것은 사유와 함께 낸다.
                _groups, _excluded, _stale_list = cls._zone_groups(
                    readings, _placements, chan_medium, inactive, _too_old,
                    _pidx, _status_of, fold_places=brief_sites)
                _z["groups"] = _groups
                if _excluded:
                    _z["excluded"] = _excluded
                if _stale_list:
                    # 평균에서 뺀 센서 — 없는 것과 뺀 것은 다르다.
                    _z["stale_excluded"] = _stale_list
                    _z["stale_excluded_count"] = len(_stale_list)
                    any_stale = True
                _own = [g for g in _groups if g["placement"] != "outdoor"]
                if detail:
                    # 호환 키 — 다음 리허설까지 유지한다. `sensors` 는 실내+실외,
                    # 어느 쪽인지는 장치의 `location` 과 `indoor`/`outdoor`.
                    _z.update({"indoor": _in, "outdoor": _out,
                               "sensors": readings})
                    _fld = [d["device_id"] for d in readings
                            if d["location"] == "open_field"]
                    if _fld:
                        _z["open_field"] = _fld
                    # 장소 평균은 그룹에서 가져온다 — 시설(facility) 공기 그룹만
                    # `indoor_avg`, 노지는 `open_field_avg`. 기상대·예보 모델·
                    # 비활성·미배치·멈춘 센서는 그룹이 이미 뺀다(excluded/stale_excluded).
                    for _key, _kind in (("indoor_avg", "facility"),
                                        ("open_field_avg", "open_field")):
                        _gs = [g for g in _groups
                               if g["placement"] == _kind and g["medium"] == "air"]
                        if len(_gs) != 1:
                            continue
                        _avg = [{"measurement": a["measurement"],
                                 "unit": a["unit"], "avg_last": a["avg_last"],
                                 "devices": a.get("n_devices", a["n"])}
                                for a in _gs[0]["avg"] if a["n"] >= 2]
                        if _avg:
                            _z[_key] = _avg
                            any_avg = True
                    if out_readings:
                        _z["outputs"] = out_readings
                else:
                    # 기본 응답: indoor_avg 는 그룹이 하나일 때만 — 여러 그룹이면
                    # 하나의 평균으로 뭉개지 말고 groups 를 보게 한다.
                    if len(_own) == 1:
                        _avg = [{"measurement": a["measurement"],
                                 "unit": a["unit"], "avg_last": a["avg_last"],
                                 "devices": a.get("n_devices", a["n"])}
                                for a in _own[0]["avg"] if a["n"] >= 2]
                        if _avg:
                            _z["indoor_avg"] = _avg
                            any_avg = True
                    elif len(_own) > 1:
                        _z["indoor_avg_note"] = "several groups - see groups"
                    if out_readings:
                        _z["outputs_count"] = len(out_readings)
                zones_out.append(_z)

            if brief_sites:
                return cls._site_lines(zones_out, skipped, time_range, degraded)

            out = {"count": len(zones_out), "time_range": time_range,
                   "zones": zones_out}
            if measurement_type:
                out["measurement_type"] = measurement_type
            if any_stale:
                out["freshness_basis"] = (
                    "averages skip readings older than period x%s "
                    "(min %ss) or the device's max_age_s; see stale_excluded"
                    % (STALE_PERIOD_FACTOR, FRESH_MAX_AGE_S))
            if not detail:
                out["detail_hint"] = "detail=true for the sensor list"
            if zones_truncated:
                out["truncated"] = True
                out["note"] = (
                    "Only %d of %d places were looked at (places with devices "
                    "first). Pass zone_ids (from get_spatial_tree/resolve_target) "
                    "or measurement_type to see the rest."
                    % (_ZONE_SUMMARY_DEFAULT_LIMIT, zones_truncated))
            if skipped:
                out["zones_without_data"] = skipped
            if link_omitted:
                out["link_channels_omitted"] = link_omitted
            if site_direct_only:
                out["sites_list_direct_devices_only"] = True
            if degraded:
                out["warning"] = ("InfluxDB returned nothing for any series — "
                                  "this may be a read failure, not an absence of data.")
            notes = []
            notes.append(
                "'groups' = averages of the latest values per placement "
                "(facility / open_field / outdoor) and medium (air / soil); "
                "avg_last = mean of each channel's LATEST reading (the current value "
                "across sensors, not a period average), n = channels counted "
                "(n_devices = devices). A device with air and soil channels "
                "appears in both groups. 'outdoor' groups are reference only "
                "(reference=true) - never average or compare them with a "
                "facility/open_field group. 'excluded' says why a device or "
                "channel is not averaged (model, inactive, device_status:<repair|"
                "removed|maintenance>, unplaced, bearing, link_channel); 'stale_excluded' lists old readings left out.")
            if detail:
                # 같은 측정 이름을 여러 채널이 쓰는 구역이 실제로 있을 때만 말한다
                # (토양 프로브의 대기 채널과 토양 채널이 둘 다 'temperature' 인 식).
                for z in zones_out:
                    for d in z.get("sensors") or []:
                        ms = [c.get("measurement") for c in d.get("channels") or []]
                        if len(ms) != len(set(ms)):
                            notes.append(
                                "A device here reports the same measurement on "
                                "more than one channel - 'channel' is what tells "
                                "them apart, not 'measurement'. Name the channel "
                                "when you report one of these.")
                            break
                    if len(notes) > 1:
                        break
            if link_omitted:
                notes.append(
                    "Battery, RSSI and SNR channels (%d) were left out of this "
                    "overview - they are link health, not the environment. Pass "
                    "measurement_type (e.g. 'rssi', 'electrical_potential') to "
                    "get them, or use get_device_freshness for silent devices. "
                    "A zone in 'zones_without_data' had no ENVIRONMENT reading in "
                    "the period; its devices may still be sending link values."
                    % link_omitted)
            if site_direct_only:
                notes.append(
                    "A site here lists only the devices that are in none of its "
                    "zones shown here - the zones' devices are under the zones, "
                    "not repeated. Ask for the site by zone_ids to get all of it.")
            if any(e.get("reason") == "model" for z in zones_out
                   for e in z.get("excluded") or []):
                notes.append(
                    "Excluded reason 'model' = FORECAST-model values for those "
                    "coordinates, not measured at the site. Do not compare them "
                    "to the site's sensors as if both were readings.")
            if detail and (any_outdoor or any_avg):
                notes.append(
                    "Each device has 'location': 'outdoor' is the site's weather "
                    "station (set by a person when location_source='bound', "
                    "otherwise inferred from what it measures); 'indoor' is "
                    "everything else in the place. 'indoor'/'outdoor' list the "
                    "device ids of each side. 'indoor_avg' averages the latest "
                    "values of INDOOR sensors only - never average or compare "
                    "an outdoor reading as if it were inside the facility/zone.")
            if any(z.get("outputs") for z in zones_out):
                notes.append(
                    "'outputs' lists actuators (vents, curtains, valves - e.g. a "
                    "valve's run duration or an opening %), kept apart from "
                    "'sensors' on purpose. Do not report them as readings of "
                    "the environment.")
            if skipped:
                notes.append(
                    "'zones_without_data' lists the zones that returned nothing, "
                    "by name. Relay WHICH ones, not just how many.")
            if degraded:
                notes.append(
                    "'warning' is present: the readings may be missing because "
                    "InfluxDB could not be read, NOT because there is no data. "
                    "Say that rather than reporting zero.")
            if unresolved:
                out["unresolved"] = unresolved
                notes.append(
                    "'unresolved' lists requested zones that were NOT included "
                    "(a name that matched several places, or none). Say which, "
                    "and ask about an ambiguous one by its candidates' 'where'.")
            if available is not None:
                out["available_targets"] = available
            if zone_ids and len(shapes) == 1 and not unresolved:
                cls._with_target(out, shapes[0].type, shapes[0].unique_id,
                                 ref=zone_ids[0] if len(zone_ids) == 1 else None)
            if notes:
                out["_reading"] = notes
            # 상한에 걸려도 센서·채널을 떼지 말라고 캡에 알린다 — 떼면 모든
            # 구역에서 값이 사라지고 이름만 남았다(2026-10-09 실측). 지켜
            # 두면 캡이 뒤쪽 구역부터 잘라 앞쪽은 값이 그대로 남는다.
            from aot.tools.tool_execution import CAP_PRIORITY_KEY
            out[CAP_PRIORITY_KEY] = {
                'keep_last': [['*', 'groups'], ['*', 'sensors'],
                              ['*', 'channels']],
                'narrow_with': ("Pass zone_ids for the places you need, or "
                                "measurement_type (e.g. 'temperature')."),
            }
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
            _tag = None         # 풀린 장소 — 결과에 대상 id 로 싣는다

            if zone_id:
                # Input has no parent_id column — location is via GeoShape
                # (map_overlay_id), same pattern as get_sensor_detail().
                # 장소 해석은 정본 헬퍼로 — 지도 id 로 그 지도의 아무 도형을
                # 집던 것과 이름을 못 받던 것을 함께 고친다(2026-10-08).
                target_zone, _place_err = cls._read_place(zone_id)
                if not target_zone:
                    return _place_err or {"message": f"Zone '{zone_id}' not found."}
                _tag = (target_zone.type, target_zone.unique_id)

                # 소속은 정본(마커 + 바인딩 + 하위 장소)으로(2026-10-08).
                from aot.space.device_membership import place_members
                _member_ids = place_members(target_zone.unique_id)
                input_ids = ([i.unique_id for i in Input.query.filter(
                    Input.unique_id.in_(_member_ids)).all()]
                    if _member_ids else [])
                # 아래 두 빈 경우는 원인이 서로 다른데 예전에는 같은 문장
                # ("No energy sensors found for this zone/period")으로 나갔다.
                # 그 문장은 "여기엔 에너지 계측이 없다" 로 읽히지만, 실제로는
                # **이 구역에 놓이거나 매인 장치가 없다** 는 뜻일 수 있다 —
                # 관리상 이 구역 소속이어도 지도에 놓지도 매지도 않았으면 빠진다.
                _total_energy = EnergyUsage.query.count()
                if not input_ids:
                    return cls._with_target({
                        "message": ("No device is placed in or bound to this zone "
                                    "on the map, so nothing could be measured for it."),
                        "cause": "no_device_marker_in_zone",
                        "note": ("A device counts when its map marker falls inside "
                                 "the zone (or a zone below it) or it is bound to a "
                                 "shape there. %d energy record(s) exist "
                                 "system-wide; call without zone_id to see them."
                                 % _total_energy),
                    }, *_tag, ref=zone_id)
                energy_usage = EnergyUsage.query.filter(EnergyUsage.device_id.in_(input_ids)).all()
                if not energy_usage:
                    return cls._with_target({
                        "message": ("The %d device(s) inside this zone have no "
                                    "energy records." % len(input_ids)),
                        "cause": "devices_present_but_no_energy_records",
                        "note": ("%d energy record(s) exist system-wide. This is "
                                 "about these devices, not about the zone having "
                                 "no monitoring." % _total_energy),
                    }, *_tag, ref=zone_id)
            else:
                energy_usage = EnergyUsage.query.all()

            if not energy_usage:
                return {"message": "No energy records exist on this system at all.",
                        "cause": "no_energy_records_configured"}

            stats, graph = return_energy_usage(energy_usage, device_measurements_all, conversion_all)
            
            # 리포트 가공
            report_data = []
            # 장치 이름 — id 만 있으면 어느 장치의 전력인지 알려면 한 번 더 불러야 한다(2026-11-03).
            _ids = {e.device_id for e in energy_usage if e.device_id}
            _names = {i.unique_id: i.name for i in Input.query.filter(Input.unique_id.in_(_ids)).all()} \
                if _ids else {}
            for uid, val in stats.items():
                target_usage = next((e for e in energy_usage if e.unique_id == uid), None)
                if target_usage:
                    row = {"sensor_id": uid,
                           "device_id": target_usage.device_id,
                           "usage": val}
                    if _names.get(target_usage.device_id):
                        row["device_name"] = _names[target_usage.device_id]
                    report_data.append(row)

            # usage 는 지금까지의 hour·day·week·month 네 창이 한꺼번에 들어 있다 — period 는 거르지
            # 않는다(예전 문구 "analysis for monthly" 는 기간을 고른 것처럼 읽혔다, 2026-10-28 점검).
            summary = ("Energy usage over the last hour/day/week/month windows ending now "
                       "(period does not filter).")
            if zone_id:
                summary += f" Filtering by Zone: {zone_id}."
            if report_data and not any(
                    isinstance(r["usage"], dict) and any(r["usage"].values()) for r in report_data):
                summary += (" Every window is 0: the energy sensor(s) recorded no consumption "
                            "(or no recent readings) — a data fact, not a report error.")

            # "Usage is within normal parameters." 라는 문장이 데이터와 무관하게
            # 항상 실려 나갔다. 자리를 채우려고 둔 것이겠지만, 읽는 쪽에서는
            # 서버가 내린 판정으로 읽힌다 — 사용량이 얼마든 "정상" 이라고
            # 답하게 된다. 판정할 근거가 없으면 판정을 싣지 않는다.
            out = {
                "summary": summary,
                "data": report_data,
            }
            if _tag:
                cls._with_target(out, *_tag, ref=zone_id)
            return out
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
        # 'AI 판단에 포함' 을 끈 기상 장치는 후보가 아니다(device_resolver).
        from aot.services.resolvers.device_resolver import ai_excluded
        return {k: v for k, v in rows.items() if not ai_excluded(v)}

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

    #: 이 거리 밖의 기상 장치는 "그곳의 날씨" 로 쓰지 않는다(km). 예전에는
    #: 같은 지도 → 전체 순으로 넘어가며 **이름순** 첫 장치를 골라, 김제
    #: 구역에 이천(OpenWeather 좌표)·일본(Kumamoto) 장치를 답했다(2026-10-09).
    _WEATHER_NEAR_KM = 30.0
    #: 후보의 신선도를 볼 때 되돌아보는 창(초) — 이 안에 값이 없으면 뺀다.
    _WEATHER_FRESH_SCAN_S = 7 * 86400

    @classmethod
    def _pick_weather_input(cls, target_shape, resolved_name, info=None):
        """Choose the weather device for a zone/site.

        Returns (Input|None, scope, others). scope:
          'in_zone' — 그 장소 안에 놓인 기상 장치
          'site'    — 감싸는 대지의 기상원(get_plot 과 **같은 규칙**,
                      device_membership.weather_device_ids — 지정 우선, 없으면 추론)
          'nearby'  — 위 둘이 없을 때 장치 자기 좌표로 _WEATHER_NEAR_KM 이내 최근접
        그보다 먼 장치는 고르지 않는다(None) — 다른 지역의 날씨를 그곳의
        날씨로 답하는 것보다 "없다" 가 낫다. others 에는 거리(km)를 싣는다.

        **도구 응답의 후보 선택만 다룬다**(센서 분류·평균·강우 게이트의 기상원
        판정 device_membership.weather_device_ids 는 그대로). 후보에서 꺼진
        장치·상태가 ok 가 아닌 장치·신선도가 지난 장치를 빼고, 실측을 모델보다
        앞세운다(사람이 대지에 지정한 기상원은 그대로 맨 앞). `info` 딕셔너리를
        주면 `picked_because` · `skipped`(최대 3) · `skipped_more` 를 채운다.
        """
        candidates = cls._weather_inputs()
        if not candidates:
            return None, None, []

        from aot.utils.device_tz import resolve_location_coords
        from aot.utils.geo_distance import distance_m
        try:
            here = resolve_location_coords(target_shape.unique_id)
        except Exception:
            here = None
        dist = {}
        if here and here[0] is not None:
            for _id in candidates:
                try:
                    lat, lng = resolve_location_coords(_id)
                    if lat is not None and lng is not None:
                        dist[_id] = distance_m(here[0], here[1], lat, lng) / 1000.0
                except Exception:
                    continue

        def _order(ids):
            return sorted(
                (candidates[i] for i in ids if i in candidates),
                key=lambda i: (dist.get(i.unique_id, float('inf')),
                               -cls._name_affinity(i.name, resolved_name),
                               str(i.name or '')))

        in_shape = set()
        try:
            from aot.space.device_membership import place_members
            in_shape = set(place_members(target_shape.unique_id) or set())
        except Exception:
            logger.debug("[WEATHER_TOOL] shape membership lookup failed",
                         exc_info=True)

        site_ids, site_kind = set(), None
        try:
            from aot.space import device_membership as dm
            site = target_shape if getattr(target_shape, 'type', None) == 'site' else None
            if site is None:
                feat = target_shape.feature if isinstance(target_shape.feature, dict) else {}
                site = dm.site_for_geometry(target_shape.geo_id,
                                            (feat or {}).get('geometry'))
            anchor = site if site is not None else target_shape
            _ids, site_kind = dm.weather_device_ids(anchor.unique_id)
            site_ids = set(_ids)
        except Exception:
            logger.debug("[WEATHER_TOOL] site weather lookup failed",
                         exc_info=True)

        near = {i for i, d in dist.items() if d <= cls._WEATHER_NEAR_KM}
        # 위치를 모르는 API 입력(지도 마커도 좌표도 없는 기상청 입력이 흔하다)은
        # 이름이 그 장소를 가리킬 때만 쓴다('기상청-3포장' ↔ '3포장'). 거리를
        # 아는데 멀면 이름이 맞아도 쓰지 않는다.
        named = {i for i, row in candidates.items()
                 if i not in dist and cls._name_affinity(row.name, resolved_name)}

        def _brief(i):
            d = {"name": i.name, "device_id": i.unique_id, "driver": i.device}
            if i.unique_id in dist:
                d["distance_km"] = round(dist[i.unique_id], 1)
            return d

        usable = in_shape | site_ids | near | named
        # 범위(scope) 순서 → 같은 범위 안에서는 가까운 순(기존 규칙).
        ordered, seen = [], set()
        for ids, scope in ((in_shape, 'in_zone'), (site_ids, 'site'),
                           (near, 'nearby'), (named, 'named')):
            for i in _order(ids):
                if i.unique_id not in seen:
                    seen.add(i.unique_id)
                    ordered.append((i, scope))

        try:
            from aot.utils.inputs import model_input_drivers
            _models = set(model_input_drivers())
        except Exception:                                   # noqa: BLE001
            _models = set()
        bound_ids = set(site_ids) if site_kind == 'bound' else set()

        def _rank(item):
            row, _scope = item
            if row.unique_id in bound_ids:
                return 0                      # 사람이 지정한 기상원
            return 2 if row.device in _models else 1

        ordered.sort(key=_rank)               # 안정 정렬 — 범위·거리 순 유지

        chosen = None
        skipped, skipped_n, rest = [], 0, []
        for row, scope in ordered:
            # 고른 뒤의 후보는 신선도(Influx 조회)까지 보지 않는다 — 꺼짐·상태는
            # 값싸게 알 수 있으므로 "왜 빠졌나" 를 위해 계속 본다.
            reason = cls._weather_skip_reason(row, fresh=chosen is None)
            if reason:
                skipped_n += 1
                if len(skipped) < 3:
                    skipped.append({"name": row.name, "reason": reason})
                continue
            if chosen is None:
                chosen = (row, scope)
            else:
                rest.append(row)

        if info is not None:
            if skipped:
                info['skipped'] = skipped
                if skipped_n > len(skipped):
                    info['skipped_more'] = skipped_n - len(skipped)
            if chosen is not None:
                row, scope = chosen
                if row.unique_id in bound_ids:
                    info['picked_because'] = 'bound_site'
                elif row.device in _models:
                    info['picked_because'] = 'model_only'
                else:
                    info['picked_because'] = {
                        'in_zone': 'observed_in_zone',
                        'site': 'observed_in_site',
                        'nearby': 'nearest_observed',
                        'named': 'observed_by_name'}.get(scope, 'observed')

        if chosen is None:
            return None, None, []
        row, scope = chosen
        others = [_brief(i) for i in rest]
        return row, scope, others

    @classmethod
    def _weather_skip_reason(cls, row, fresh=True):
        """후보에서 뺄 이유 — 'inactive' | 'device_status' | 'stale' | None.

        꺼진 장치, 수리·철거·점검 중(device_resolver.is_reliable_sensor), 정본
        신선도(measurement_freshness — 장치 max_age_s > 주기×배수)를 넘긴 장치.
        신선도를 못 읽으면(조회 실패) 빼지 않는다 — 모른다고 후보를 지우면
        안 된다. 마지막 값이 아예 없으면(창 안 0건) 오래된 것으로 본다.
        """
        if not getattr(row, 'is_activated', True):
            return 'inactive'
        try:
            from aot.services.resolvers.device_resolver import is_reliable_sensor
            if not is_reliable_sensor(row):
                return 'device_status'
        except Exception:                                   # noqa: BLE001
            pass
        if not fresh:
            return None
        try:
            from aot.utils.measurement_freshness import (
                as_seconds, effective_max_age)
            age, _iso, _label = cls._last_seen_seconds(
                row.unique_id, window_s=cls._WEATHER_FRESH_SCAN_S)
            if age is None:
                return 'stale'
            limit = effective_max_age(
                None, getattr(row, 'period', None),
                as_seconds(getattr(row, 'max_age_s', None)),
                floor=cls._FRESHNESS_MIN_AGE_S,
                factor=cls._FRESHNESS_PERIOD_FACTOR)
            if age > limit:
                return 'stale'
        except Exception:                                   # noqa: BLE001
            logger.debug("[WEATHER_TOOL] freshness check failed for %s",
                         getattr(row, 'unique_id', '?'), exc_info=True)
        return None

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
    def _rain_sum_stats(cls, dev, m, measurement, unit, data):
        """강수량 줄의 기간 합 칸 — 한 값이 덮는 구간을 알 때만 더한다. 강수량이 아니면 빈 dict.

        순간 강우율(mm_h)·구간 모르는 누적(SenseCAP 누적 계기)은 더하면 틀리므로 `sum_why` 만 낸다. 일별 예보 입력은
        채널이 며칠 뒤 값이라 더할 수 없다."""
        from aot.tools.data_tools import weather_summary as ws
        from aot.utils.inputs import forecast_time_input_drivers, rain_accum_seconds
        if not ws.is_rain_amount(measurement or m.measurement, unit):
            return {}
        driver = getattr(dev, 'device', None)
        per = None if driver in forecast_time_input_drivers() else rain_accum_seconds(
            unit, measurement or m.measurement, getattr(m, 'name', None), driver)
        if not per:
            return {"sum_why": "no fixed interval"}
        total, _cells = ws.cell_total([(row[0].timestamp(), row[1]) for row in data], per)
        return {"sum": total}

    @classmethod
    def _weather_lead_read(cls, dev, time_range, leads, place_id, keep=None):
        """시간별 예보 입력을 **그 값이 가리키는 시각**으로 읽는다 — 측정마다 리드가 가장 짧은 채널 하나.

        리드 채널은 받은 시각에 찍혀 있으므로 구간을 리드만큼 앞당겨 읽고 대상 시각으로 옮긴다(`weather_summary.lead_points`).
        리드가 긴 채널·창 집계는 같은 시각을 더 먼 때 예보한 값이라 지나간 날씨의 대표가 아니다(앞으로의 값은 `weather.forecast`).
        끝은 지금을 넘지 않는다 — 아직 오지 않은 시각은 지나간 날씨가 아니다. 리드가 가장 짧은 채널이
        꺼져 비었으면 다음 리드로 넘어간다. 값을 고치지 않는다(보정 계층을 읽지 않는다).
        """
        from aot.tools.data_tools import weather_summary as ws
        from aot.utils.timekit import iso_at
        fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
        now = utc_now().timestamp()
        start, end = cls._date_span(time_range)
        if start:
            window, werr = cls._detail_window(start, end, place_id)
            if werr:
                return werr
            t0, t1 = (datetime.strptime(window[k], fmt).replace(tzinfo=timezone.utc).timestamp()
                      for k in ('start_utc', 'end_utc'))
            span = window['label']
        else:
            window, t0, t1 = None, now - cls._parse_range(time_range), now
            span = "the last %s" % time_range
        t1 = min(t1, now)
        groups = {}
        for m in DeviceMeasurements.query.filter(DeviceMeasurements.device_id == dev.unique_id).all():
            if m.channel in leads and t0 < t1:      # 아직 오지 않은 구간은 읽을 것이 없다
                groups.setdefault(m.measurement, []).append(m)
        rows, tzc = [], {}
        order = sorted(groups.values(), key=lambda g: min(x.channel for x in g))
        for group in order:
            for m in sorted(group, key=lambda x: leads[x.channel][0]):
                lead, kind = leads[m.channel]
                conversion = (Conversion.query.filter(Conversion.unique_id == m.conversion_id).first()
                              if m.conversion_id else None)
                channel, unit, measurement = return_measurement_info(m, conversion)
                stamp = lambda epoch: datetime.fromtimestamp(epoch - lead * 3600, timezone.utc).strftime(fmt)
                data = read_influxdb_list(
                    dev.unique_id, unit, channel, measure=measurement,
                    start_str=stamp(t0), end_str=stamp(t1), datetime_obj=True)
                points = ws.lead_points([(r[0].timestamp(), r[1]) for r in data or []],
                                        lead, kind, t0, t1)
                if not points:
                    continue
                row = ws.lead_row(
                    {"device_name": dev.name or dev.unique_id, "device_kind": "input",
                     "measurement": measurement or m.measurement,
                     "channel": getattr(m, 'name', None) or "", "lead_h": lead},
                    points, unit, lambda e: iso_at(int(e), dev.unique_id, tzc), keep or 5)
                if window:
                    row["period"] = window['period']
                if kind == 'cell' and ws.is_rain_amount(measurement or m.measurement, unit):
                    row["stats"]["sum"] = round(sum(v for _t, v in points), 2)
                    gaps = int(t1 // 3600) - int(t0 // 3600) - len(points)
                    if gaps > 0:
                        row["stats"]["missing_hours"] = gaps    # 수집이 끊긴 칸은 합에 없다
                rows.append(row)
                break
        if rows:
            return rows
        return {"message": "No data for device '%s' in %s." % (dev.name, span),
                "device_id": dev.unique_id, "time_range": None if window else time_range,
                **({"period": window['period']} if window else {})}

    @classmethod
    def _period_ended(cls, time_range, place_id):
        """구간의 끝이 지났는가 — 그러면 마지막 값은 지금 값이 아니다. 날짜 구간이 아니거나 끝이 없으면(지금까지) False."""
        start, end = cls._date_span(time_range)
        if not start or not end:
            return False
        window, werr = cls._detail_window(start, end, place_id)
        if werr:
            return False
        return (datetime.strptime(window['end_utc'], '%Y-%m-%dT%H:%M:%S.%fZ')
                .replace(tzinfo=timezone.utc).timestamp() <= utc_now().timestamp())

    @classmethod
    def get_weather_tool(cls, zone_name=None, zone_id=None, time_range=None,
                         sensor_type=None, detail=None, limit=None, brief=False, **kwargs):
        """[읽기전용] 구역 기상 + (예보 출처가 없을 때만) 예보 입력 안내 한 줄.

        `detail`: None = 예전 모양(항목마다 최근 5건) · False = 요약(항목마다 최저·최고·평균·
        극값 시각, 기본 창 24h) · True = 시계열. `sensor_type`(항목 이름·일상어, 쉼표로 여럿)을 주면 그 항목만. `time_range`
        는 되돌아볼 창('6h'·'2d'·날짜 구간)으로, 장치 주기로 넓어진 창보다 좁아지지 않는다.

        `brief` 는 도구 스키마에 없다 — `weather.now`(`registry_data` 의 defaults_by_kind)만 켠다. 켜면 구름·일사·채널 이름·
        강수 합을 싣고, 시간별 예보 입력은 리드 하나를 대상 시각으로 읽는다(`_weather_lead_read`). 끝난 구간에는
        `period_ended` 가 붙는다. 인앱 AI·개요·점검 스크립트는 이 인자를 안 주므로 응답이 바뀌지 않는다.
        """
        from aot.tools.data_tools import weather_summary as ws
        tokens = ws.field_tokens(sensor_type)
        summary = ws.wants_summary(detail)
        series = ws.wants_full(detail) or (bool(tokens) and not summary)
        out = cls._get_weather_tool(
            zone_name=zone_name, zone_id=zone_id, time_range=time_range, summary=summary,
            series_limit=(limit or ws.DETAIL_READINGS) if series else limit, brief=brief, **kwargs)
        try:
            if isinstance(out, dict) and not out.get('error'):
                if summary:
                    out = ws.summarize_observed(out, tokens)
                elif tokens:
                    out = ws.filter_observed(out, tokens)
                hint = cls.forecast_input_hint()
                if hint:
                    out['forecast_hint'] = hint
        except Exception:                                   # noqa: BLE001
            logger.debug("[WEATHER_TOOL] summary failed", exc_info=True)
        return out

    @classmethod
    def _get_weather_tool(cls, zone_name=None, zone_id=None, time_range=None,
                          summary=False, series_limit=None, brief=False, **kwargs):
        """
        포장/구역의 기상 센서 데이터를 InfluxDB에서 조회합니다.
        GeoShape.unique_id → Input(map_overlay_id) → DeviceMeasurements(device_id+channel) → InfluxDB
        외부 API를 직접 호출하지 않습니다. 데이터는 Input 데몬이 수집하여 InfluxDB에 저장합니다.
        @ANCHOR: WEATHER_TOOL_ENTRY
        """
        import json as _json

        try:
            # Step 1: 장소 찾기 — 다른 읽기 도구와 **같은 리졸버**(_read_place).
            # 예전에는 여기만 자기 이름 매칭을 갖고 있었다(2026-10-09):
            #   · zone_id 에 이름('3-1')을 주면 id 로만 찾아 실패했다.
            #   · 같은 이름이 두 지도에 있으면('1포장') 첫 도형을 조용히 골랐다.
            #   · 못 찾으면 '쓸 수 있는 구역' 으로 이름 없는 도형의 id 를 냈다.
            target_shape = None
            if zone_id:
                target_shape = GeoShape.query.filter_by(unique_id=zone_id).first()
            place_err = None
            if not target_shape:
                for _tok, _arg in ((zone_id, 'zone_id'), (zone_name, 'zone_name')):
                    if not _tok:
                        continue
                    try:
                        target_shape, place_err = cls._read_place(_tok, arg=_arg)
                    except Exception as e:                  # noqa: BLE001
                        logger.debug("get_weather: place lookup failed: %s", e)
                        target_shape, place_err = None, None
                    if target_shape is not None:
                        break
            if place_err and place_err.get('candidates'):
                # 같은 이름이 여러 곳 — 고르지 않는다(다른 읽기 도구와 같다).
                return place_err

            # Step 2: Resolve display name; return error if zone not found
            _resolved_name = zone_name or zone_id or "Unknown zone"
            if target_shape:
                try:
                    _f = target_shape.feature if isinstance(target_shape.feature, dict) else _json.loads(target_shape.feature or '{}')
                    _resolved_name = (_f.get('properties') or {}).get('name', _resolved_name)
                except Exception:
                    pass
            else:
                out = {
                    "error": "zone_not_found",
                    "message": ((place_err or {}).get("error")
                                or f"Zone '{zone_name or zone_id}' not found."),
                }
                # 이름 있는 장소만 — 예전엔 이름 없는 도형의 id 가 섞여 나갔다.
                if (place_err or {}).get("available_targets"):
                    out["available_zones"] = place_err["available_targets"]
                return out

            # Step 3: Pick the device to read. A weather question must be
            # answered by a weather station — see _WEATHER_INPUT_DEVICES for
            # what "just take the first Input in the polygon" produced.
            from aot.tools.data_tools import weather_summary as _ws

            def _window(base):
                """장치 주기로 정한 창(`base`)을 요청·요약 기본으로 넓힌다. 둘 다 없으면 그대로."""
                if not time_range and not summary:
                    return base
                return _ws.window_label(base, time_range, summary)

            _wide = {'wide': True} if brief else {}

            def _read(loc_id, rng):
                """Weather-filtered read, falling back to unfiltered."""
                rng = _window(rng)
                res = cls.get_sensor_detail(
                    loc_id=loc_id, time_range=rng, sensor_type='weather',
                    limit=series_limit, peaks=summary, **_wide)
                if isinstance(res, dict) and res.get('error'):
                    return cls.get_sensor_detail(
                        loc_id=loc_id, time_range=rng, limit=series_limit, peaks=summary, **_wide)
                return res

            def _envelope(res):
                out = dict(res) if isinstance(res, dict) else {"data": res}
                out['zone_name'] = _resolved_name
                return out

            _pick_info = {}
            chosen, scope, others = cls._pick_weather_input(
                target_shape, _resolved_name, info=_pick_info)

            if chosen is not None:
                _range = cls._weather_time_range(chosen)
                logger.info(
                    "[WEATHER_TOOL] zone '%s' → weather device '%s' (%s, %s, %s)",
                    _resolved_name, chosen.name, chosen.device, scope, _range)
                from aot.utils.inputs import hourly_lead_channels
                _leads = hourly_lead_channels(chosen.device) if brief else {}
                if _leads and not cls._check_influxdb_available()[0]:
                    _leads = {}                     # 최신값 폴백이 있는 예전 길로 — 시각 기준은 stored 로 밝힌다
                out = _envelope(cls._weather_lead_read(
                    chosen, _window(_range), _leads, target_shape.unique_id, series_limit)
                    if _leads else _read(chosen.unique_id, _range))
                out['weather_source'] = 'weather_station'
                out['weather_device'] = {"name": chosen.name,
                                         "device_id": chosen.unique_id,
                                         "driver": chosen.device}
                try:
                    from aot.utils.inputs import model_input_drivers
                    if chosen.device in model_input_drivers():
                        out['weather_device']['data_origin'] = 'model'
                        out['weather_model_note'] = (
                            "This weather source is a forecast model for these "
                            "coordinates, not an observation at the site. Say so.")
                        if brief:
                            cls._mark_forecast_times(out, chosen, _leads)
                    elif brief:
                        out['weather_device']['data_origin'] = 'observed'
                except Exception:                           # noqa: BLE001
                    pass
                out['weather_device_scope'] = scope
                if scope == 'site':
                    out['weather_device_note'] = (
                        "This is the weather source of the site that contains "
                        "'%s' (the same one get_plot uses), not a device placed "
                        "inside it. Say so when reporting." % _resolved_name)
                elif scope == 'named':
                    out['weather_device_note'] = (
                        "This weather input has no known location; it was chosen "
                        "because its name refers to '%s'. Say so when reporting."
                        % _resolved_name)
                elif scope == 'nearby':
                    out['weather_device_note'] = (
                        "No weather device is placed in '%s' or its site; this is "
                        "the closest one within %d km. Say so when reporting."
                        % (_resolved_name, int(cls._WEATHER_NEAR_KM)))
                if others:
                    out['other_weather_devices'] = others
                if _pick_info:
                    out['weather_pick'] = _pick_info
                _ended = brief and cls._period_ended(time_range, target_shape.unique_id)
                if _ended:
                    out['period_ended'] = True
                else:                   # 제어 실외 정본은 지금 값이다 — 끝난 구간의 값과 견주면 뜻이 없다
                    _co = cls._control_outdoor(target_shape, chosen.unique_id, out)
                    if _co:
                        out['control_outdoor'] = _co
                _sun = _ws.sun_for(target_id=target_shape.unique_id)
                if _sun:
                    out['sun'] = _sun
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
                from aot.space.device_membership import place_members
                _ids = place_members(target_shape.unique_id) or set()
                # 'AI 판단에 포함' 을 끈 센서는 후보가 아니다(device_resolver).
                from aot.services.resolvers.device_resolver import ai_excluded_ids
                _ids = set(_ids) - ai_excluded_ids()
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
            _sun = _ws.sun_for(target_id=target_shape.unique_id)
            if _sun:
                out['sun'] = _sun
            out['weather_source'] = 'nearby_sensor'
            out['weather_device_scope'] = 'in_zone'
            if _pick_info:
                out['weather_pick'] = _pick_info
            if brief and cls._period_ended(time_range, target_shape.unique_id):
                out['period_ended'] = True
            out['weather_source_warning'] = (
                "No weather station (KMA / SenseCAP / Ecowitt / OpenWeatherMap or "
                "any wind/rain-recording input) is placed in this place, assigned "
                "to its site, or within %d km of it — a station farther away would "
                "be another region's weather. The values below come from an "
                "ordinary sensor inside "
                "'%s' and are NOT weather observations — there is no wind, rain or "
                "solar data. Report them as a sensor reading, not as the weather."
                % (int(cls._WEATHER_NEAR_KM), _resolved_name))
            return out

        except Exception as e:
            logger.exception("[WEATHER_TOOL] Unexpected error")
            return {"error": "unexpected_error", "message": f"Error while querying weather data: {str(e)}"}

    @classmethod
    def _mark_forecast_times(cls, out, chosen, leads):
        """예보 모델 출처의 시각 기준을 밝힌다 — 대상 시각(`target`)으로 옮겼는가, 저장 시각(`stored`) 그대로인가."""
        from aot.utils.inputs import forecast_time_input_drivers
        data = out.get('data') if isinstance(out.get('data'), list) else []
        got = [r['lead_h'] for r in data if isinstance(r, dict) and r.get('lead_h')]
        if got:
            out['weather_device'].update(lead_h=min(got), time_basis='target')
            out['weather_model_note'] = (
                "Values are the +%dh forecast issued then, not observations at the site. "
                "Each time is the time a value was forecast for. Say so." % min(got))
        elif chosen.device in forecast_time_input_drivers():
            out['weather_device']['time_basis'] = 'stored'
            out['weather_model_note'] += " Times are when each forecast was stored, not the time it is for."

    @classmethod
    def _control_outdoor(cls, shape, chosen_id, weather):
        """도구가 고른 날씨 장치가 시설 제어의 실외 정본과 다를 때만 정본을 낸다.

        시설 찾기는 양방향이다: 요청 장소가 시설 도형 안에 있거나(시설 안 장소),
        시설을 포함하면(대지 ⊃ 시설) 그 시설들. 시설도 포함도 아니면 None(구역은
        상위 대지 기준으로 끌어오지 않는다). 정본 = 각 시설 outdoor fitting 의
        주(primary) 장치. 서로 다른 정본이 하나뿐이면 그것, 여럿이면 시설 이름순
        첫 번째를 본문에, 나머지를 control_outdoor_more(최대 3). 도구가 고른
        장치가 정본 중 하나이면 None. 읽기만 한다.
        """
        try:
            from aot.databases.models import GeoFacility
            from aot.space.device_membership import PlaceIndex
            from aot.space.facility_integration import \
                get_facility_integration
            from aot.space.facility_sensors import (
                read_fitting_sensors, read_outdoor_sensors, sensor_priority_of)
            idx = PlaceIndex()
            facs = []
            for f in GeoFacility.query.all():
                sp = getattr(f, 'shape_uuid', None)
                if sp and (idx.within(shape.unique_id, sp)
                           or idx.within(sp, shape.unique_id)):
                    facs.append(f)
            facs.sort(key=lambda f: (f.name or '', f.unique_id))
            ents = []           # 시설별 정본 항목
            for f in facs:
                integ, err = get_facility_integration(f.unique_id)
                outs = [] if err else ((integ or {}).get('sensors_outdoor') or [])
                outs = [o for o in outs if o.get('input_uuid')]
                if not outs:
                    continue
                ents.append(cls._facility_outdoor_entry(
                    f.name, outs, weather, read_outdoor_sensors,
                    read_fitting_sensors, sensor_priority_of))
            if not ents:
                return None
            if any(chosen_id in e['devs'] for e in ents):
                return None
            # 같은 장치 묶음은 하나로, 정렬은 메인 -> 백업 -> 시설 이름순.
            uniq, seen = [], set()
            for e in sorted(ents, key=lambda e: (e['rank'] == 'backup',
                                                 e['facility'] or '')):
                if e['devs'] in seen:
                    continue
                seen.add(e['devs'])
                uniq.append(e)
            res = dict(uniq[0]['out'])
            if len(uniq) > 1:
                res['facility'] = uniq[0]['facility']
                res['control_outdoor_more'] = [
                    {"facility": e['facility'], "name": e['out']['name'],
                     "rank": e['rank']} for e in uniq[1:4]]
            return res
        except Exception:                                   # noqa: BLE001
            logger.debug("[WEATHER_TOOL] control_outdoor failed", exc_info=True)
            return None

    @classmethod
    def _facility_outdoor_entry(cls, facility, outs, weather, read_outdoor,
                                read_fitting, priority_of):
        """한 시설의 제어 실외 정본 — `read_outdoor_sensors` 를 그대로 쓴다.

        제어 규칙(facility_sensors.read_outdoor_sensors, 1172행 근처): 실외 장치가
        여럿이어도 하나를 고르지 않고 값 종류별로 합친다. 순위 표시가 'backup' 인 것만
        백업(없으면 메인). 메인에 신선한 값이 하나라도 있으면 메인만, 메인이 모두
        끊겼을 때만 백업(`backup_keys`), 같은 순위 안은 평균. 여기서는 그 결과의
        기온(T_ext)과 어느 순위에서 왔는지(rank)만 읽어 보인다.
        """
        r = read_outdoor(outs) or {}
        rank = 'backup' if 'T' in (r.get('backup_keys') or []) else 'main'
        tier = 'backup' if rank == 'backup' else 'primary'
        mine = [o for o in outs if priority_of(o) == tier] or outs
        devs = frozenset(o['input_uuid'] for o in mine)
        chans = []
        try:
            for fit in read_fitting(mine):
                for c in fit.get('channels') or []:
                    if c.get('key') == 'T' and c.get('valid'):
                        chans.append(c)
        except Exception:                                   # noqa: BLE001
            chans = []
        names = sorted({o.get('input_name') or o.get('name') or ''
                        for o in mine})
        name = names[0] if len(names) == 1 else "%s 외 %d" % (names[0], len(names) - 1)
        out = {"name": name, "rank": rank}
        t = r.get('T_ext')
        if t is None:
            out.update(value=None, note='no_recent_value')
            return {'facility': facility, 'rank': rank, 'devs': devs, 'out': out}
        unit = next((c.get('unit') for c in chans if c.get('unit')), '°C')
        ats = [c.get('ts') for c in chans if c.get('ts')]
        out.update(value=round(t, 1), unit=unit, at=max(ats) if ats else None,
                   measurement='temperature')
        tool_v = None
        for d in (weather or {}).get('data') or []:
            if str(d.get('measurement') or '').lower() == 'temperature':
                rs = d.get('readings') or []
                if rs:
                    tool_v = rs[-1].get('v')
                break
        if isinstance(tool_v, (int, float)) and 'C' in str(unit):
            out['differs_by'] = round(tool_v - t, 1)
        return {'facility': facility, 'rank': rank, 'devs': devs, 'out': out}

    #: 날짜 구간 조회의 상한 — 점이 많은 센서(1분 주기)는 92일이 13만 점이다.
    _DETAIL_MAX_DAYS = 92

    @classmethod
    def _date_span(cls, text):
        """time_range 가 날짜면 (start, end): 'D' · 'D/D' · 'D/'(지금까지). 아니면 (None, None)."""
        import re
        t = str(text or '').strip()
        m = re.fullmatch(r'(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)'
                         r'(?:\s*/\s*(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)?)?', t)
        if not m:
            return None, None
        if '/' not in t:
            return m.group(1), m.group(1)           # 하루
        return m.group(1), m.group(2)               # 끝이 비면 지금까지

    @classmethod
    def _detail_window(cls, start, end, place_id):
        """start/end('YYYY-MM-DD' 또는 'YYYY-MM-DDTHH:MM') → (구간, 오류).

        그 장치·장소의 현지 시각으로 읽는다(`device_tz.location_window`). 날짜만 주면
        end 는 **그날을 포함**한다. end 를 빼면 지금까지.
        """
        from aot.utils.device_tz import location_window
        if not start:
            return None, {"error": "end needs start — e.g. start='2026-10-01', "
                                   "end='2026-10-07'.", "reason_code": "bad_period"}
        try:
            t0, t1, from_local, to_local = location_window(start, end, place_id)
        except (TypeError, ValueError):
            return None, {"error": "start/end must be YYYY-MM-DD or YYYY-MM-DDTHH:MM.",
                          "reason_code": "bad_period"}
        if t1 <= t0:
            return None, {"error": "end is not after start.", "reason_code": "bad_period"}
        if (t1 - t0).days > cls._DETAIL_MAX_DAYS:
            return None, {"error": "At most %d days per call." % cls._DETAIL_MAX_DAYS,
                          "reason_code": "bad_period"}
        fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
        return {"start_utc": t0.strftime(fmt), "end_utc": t1.strftime(fmt),
                "period": {"from": from_local, "to": to_local},
                "label": "%s to %s" % (from_local, to_local)}, None

    @classmethod
    def _range_ok(cls, text):
        """`_parse_range` 가 뜻대로 읽는 모양인가 — 1h·24h·7d·초 수. 비어 있으면 기본 창이라 괜찮다."""
        import re
        t = str(text or '').strip().lower()
        return not t or re.fullmatch(r'\d+[hd]?', t) is not None

    @classmethod
    def _bad_range(cls, text):
        """모르는 time_range 를 24h 로 바꿔 읽지 않고 허용 모양을 알리는 오류(2026-11-03: 'yesterday' 가 조용히 24h)."""
        return {"error": "time_range %r is not understood. Use 1h, 24h, 7d, a date 'YYYY-MM-DD' "
                         "or 'FROM/TO' dates (both days included)." % (text,),
                "reason_code": "bad_period"}

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
    def _cumulative_function_for(cls, ident):
        """get_cumulative_status 의 대상 — 함수 id 는 그대로, **시설 id** 면 그 시설의 환경제어 함수로 푼다.

        누적 추적(DLI·GDD)은 함수 하나의 것이지만 사람은 "육묘장3 의 DLI" 처럼 시설로 묻는다 — 시설을 주었다고
        거절하면 모델이 id 를 찾으러 다른 도구로 갔다(measure.cumulative, 2026-10-24~11-02 거절 5건).
        돌려주는 값: 함수 id(str) 또는 후보를 담은 오류 dict. 함수도 시설도 아니면 id 그대로(기존 동작)."""
        import json as _json
        ident = str(ident).strip()
        try:
            if CustomController.query.filter_by(unique_id=ident).first() is not None:
                return ident
            from aot.databases.models import GeoFacility
            fac = GeoFacility.query.filter(
                (GeoFacility.unique_id == ident) | (GeoFacility.shape_uuid == ident)).first()
            if fac is None:
                return ident
            forms = {ident, fac.unique_id, fac.shape_uuid}
            found = []
            for r in CustomController.query.filter_by(device='env_coordinator').all():
                try:
                    o = _json.loads(r.custom_options) if r.custom_options else {}
                except (ValueError, TypeError):
                    continue
                if isinstance(o, dict) and str(o.get('geo_facility_id') or '').strip() in forms:
                    found.append((r, o))
        except Exception:                                   # noqa: BLE001
            return ident
        if not found:
            return {"error": "No environment coordinator function is set for facility '%s', so there is no "
                             "cumulative (DLI/GDD) record. Pass a function id." % (fac.name or ident)}
        if len(found) > 1:
            on = [r for r, _o in found if getattr(r, 'is_activated', False)]
            if len(on) == 1:
                return on[0].unique_id
            return {"error": "Facility '%s' has %d environment coordinator functions; pass one function id."
                             % (fac.name or ident, len(found)),
                    "candidates": [{"function_id": r.unique_id, "name": r.name,
                                    "is_activated": bool(getattr(r, 'is_activated', False)),
                                    **({"bay_scope": o['bay_scope']} if o.get('bay_scope') else {})}
                                   for r, o in found]}
        return found[0][0].unique_id

    @classmethod
    def get_cumulative_status(cls, function_id: str, days: int = 7, **kwargs):
        """최근 N일 DLI·GDD 누적 상태와 부채 보상 제안을 반환한다."""
        if not function_id:
            return {"error": "function_id is required"}

        resolved = cls._cumulative_function_for(function_id)
        if isinstance(resolved, dict):
            return resolved
        function_id = resolved

        from aot.functions.utils.env_control.cumulative_tracker import load_recent_state
        rows = load_recent_state(function_id, days=days)

        if not rows:
            # 둘 중 무엇인지 가른다 — '안 돌았거나 꺼짐' 이라고만 하면, 오늘 정상
            # 주기를 돈 코디네이터를 두고 읽는 쪽이 원인을 추측해야 했다
            # (2026-10-09 외부 점검: 육묘장3 은 추적 옵션이 꺼져 있었다).
            tracker_on = None
            try:
                import json as _json
                fn = CustomController.query.filter_by(unique_id=function_id).first()
                if fn is not None:
                    opts = _json.loads(fn.custom_options) if fn.custom_options else {}
                    tracker_on = bool(opts.get('cumulative_tracker_enabled'))
            except Exception:                               # noqa: BLE001
                tracker_on = None
            if tracker_on is False:
                why = ("No cumulative data — DLI/GDD tracking is turned OFF for this "
                       "function (option 'cumulative_tracker_enabled'). It is not a "
                       "fault; turning the option on starts recording from the next "
                       "cycle.")
            elif tracker_on is True:
                why = ("No cumulative data yet — tracking is on but nothing has been "
                       "recorded in the last %d days (the function may not have run)."
                       % days)
            else:
                why = ("No cumulative data — the function has not run yet or the "
                       "tracker is disabled.")
            out = {
                "function_id": function_id,
                "days_requested": days,
                "records": [],
                "summary": why,
            }
            if tracker_on is not None:
                out["tracker_enabled"] = tracker_on
            return out

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

    _NO_FORECAST_HINT = ("예보 입력 없음 — Open-Meteo 예보 입력(OPEN_METEO_FORECAST)을 "
                         "추가하세요(설정 > 입력)")

    @classmethod
    def _open_meteo_forecast_source(cls):
        """등록된 Open-Meteo 예보 소스. 없으면 None.

        1순위는 AI 라이브러리의 데이터 소스(ext_openmeteo), 없으면 좌표를 가진
        OPEN_METEO_FORECAST 입력의 좌표로 직접 조회한다.
        """
        try:
            from aot.tools import providers
            svc = providers.get('data_source_query')
            src = next((a for a in svc.describe_all()
                        if a.get('preset') == 'ext_openmeteo'), None)
            if src:
                return {"kind": "data_source", "svc": svc, "src": src}
        except Exception:                                   # noqa: BLE001
            pass
        try:
            # 좌표는 장치 컬럼이 아니라 리졸버로 본다. OPEN_METEO_FORECAST·
            # OPEN_METEO_HOURLY_FORECAST 의 custom_options(api_key/window_h/model/
            # l0_leads/write_file)에는 조회 좌표 선언이 없다 — 별도 조회 좌표 없음,
            # 장치 배치(자리, 없으면 대지)를 조회 지점으로 쓴다.
            from aot.space.device_location import locate_many
            cands = Input.query.filter(
                Input.device == 'OPEN_METEO_FORECAST').order_by(Input.id).all()
            located = locate_many([('input', c.unique_id) for c in cands])
            inp = next((c for c in cands
                        if (located.get(('input', c.unique_id)) is not None
                            and located[('input', c.unique_id)].point is not None)),
                       None)
            if inp is not None:
                from aot.tools import providers
                return {"kind": "input", "input": inp,
                        "svc": providers.get('data_source_query')}
        except Exception:                                   # noqa: BLE001
            pass
        return None

    @classmethod
    def forecast_input_hint(cls):
        """예보 출처가 하나도 없을 때만 안내 한 줄을, 있으면 None.

        get_weather·get_place_overview 가 응답 필드(`forecast_hint`)로 싣는다 —
        도구 설명을 늘리지 않고 필요한 곳에서만 말한다.
        """
        found = cls._open_meteo_forecast_source()
        if not found:
            return cls._NO_FORECAST_HINT
        # 입력만 있고 꺼져 있으면 수신이 없다 — "입력 없음" 과 다른 문구로 구분한다.
        # (데이터 소스는 호출 때 바로 조회하므로 수신 정지라는 개념이 없다.)
        if found["kind"] == "input" and not found["input"].is_activated:
            return ("예보 입력(OPEN_METEO_FORECAST)은 있으나 꺼져 있어 수신이 "
                    "없습니다(설정 > 입력에서 켜세요)")
        return None

    @staticmethod
    def _rows_from_now(raw_rows, tz_name, step):
        """지난 시간 칸을 빼고, `hour_offset` 0 = 지금이 속한 시간 칸으로 매긴다.

        Open-Meteo 의 `time` 은 요청한 시간대의 지역시각이다(`timezone=auto`).
        시간대를 알면 현재 시각을 그 시간대로 환산해 비교한다 — UTC 서버에서
        지역시각 문자열을 그대로 `now` 와 비교하면 칸이 몇 시간씩 어긋난다.
        시간대를 모르면 행 순서를 믿는다(응답이 지금 칸부터 시작한다).
        """
        from datetime import datetime as _dt
        now_hour = None
        if tz_name:
            try:
                from aot.utils.timekit import tz_of, utc_now as _utc_now
                now_hour = (_utc_now().astimezone(tz_of(tz_name))
                            .replace(tzinfo=None, minute=0, second=0, microsecond=0))
            except Exception:                               # noqa: BLE001
                now_hour = None
        if now_hour is None:
            return [{"hour_offset": i * step, **r} for i, r in enumerate(raw_rows)]
        out = []
        for r in raw_rows:
            try:
                t = _dt.fromisoformat(str(r.get('time')))
            except ValueError:
                continue
            off = int(round((t - now_hour).total_seconds() / 3600.0))
            if off >= 0:
                out.append({"hour_offset": off, **r})
        return out

    _FORECAST_MAX_HOURS = 336
    _FORECAST_DEFAULT_KM = 5.0

    @staticmethod
    def _km_between(lat1, lon1, lat2, lon2):
        """두 점 사이 거리(km, 하버사인)."""
        import math
        p1, p2 = math.radians(lat1), math.radians(lat2)
        a = (math.sin((p2 - p1) / 2) ** 2
             + math.cos(p1) * math.cos(p2)
             * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
        return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))

    @classmethod
    def _forecast_place_at(cls, kind, ident, name, basis, ref=None):
        """풀린 장소 → answered_for dict, 좌표가 없으면 None."""
        from aot.utils.timekit import resolve_coords, tz_of, SOURCE_SYSTEM, SOURCE_UTC
        coords = resolve_coords(target_id=ident)
        lat, lon, src = coords
        if lat is None or lon is None or src in (SOURCE_SYSTEM, SOURCE_UTC):
            return None
        tz = tz_of(ident)
        out = {"name": name, "kind": kind, "id": ident, "lat": lat, "lon": lon,
               "tz": getattr(tz, 'zone', None) or str(tz), "basis": basis,
               "coord_source": src}
        # 장치라면 좌표가 장치 자리인지 대지 기준인지 — 대지 기준 예보도 쓸모는 있다.
        _lb = getattr(coords, 'basis', 'none')
        if _lb in ('device', 'site'):
            out["location_basis"] = _lb
        return out

    @classmethod
    def _forecast_place(cls, place, user_id=None):
        """예보 대상 장소 — 요청 > 화면 > 농장 기본값. 오류면 오류 dict.

        성공: {name, kind, id, lat, lon, tz, basis, coord_source, [match], [note],
        [other_places]}. 요청한 장소를 못 풀면 **기본값으로 떨어지지 않는다**."""
        place = str(place).strip() if place not in (None, '') else ''
        if place:
            shape, err = cls._overview_place(place)
            if shape is not None:
                kind, ident = shape.type or 'place', shape.unique_id
                name = cls._shape_display_name(shape) or place
            elif err and err.get('reason') == 'device_not_place':
                d = cls._resolve_explain(place)
                ident = d['result'][0]
                if not ident:
                    return err
                kind, name = 'device', place
            else:
                return err or {"error": "No place named '%s'." % place}
            at = cls._forecast_place_at(kind, ident, name, 'request')
            if at is None:
                return {"status": "unavailable", "reason": "no_coords",
                        "message": ("'%s' has no map shape or coordinates, so there "
                                    "is nothing to forecast for — draw it on the map "
                                    "or ask for another place." % name)}
            out = cls._with_target(dict(at), kind, ident, ref=place)
            for k in ('target_id', 'target_type'):
                out.pop(k, None)
            return out
        notes = []
        hint, why = cls._screen_place_hint(user_id)
        if hint:
            at = cls._forecast_place_at(hint.get('kind') or 'place', hint['id'],
                                        hint.get('name') or hint['id'], 'screen')
            if at is not None:
                return at
            why = 'screen ambiguous'
        if why:
            notes.append(why)
        return cls._forecast_default(notes)

    @classmethod
    def _forecast_default(cls, notes):
        from aot.utils.timekit import FARM, resolve_coords, tz_of, SOURCE_UTC
        lat, lon, src = resolve_coords()
        if lat is None or lon is None or src == SOURCE_UTC:
            return {"status": "unavailable", "reason": "no_coords",
                    "message": "The farm location is not set, so there is no place "
                               "to forecast for. Pass place."}
        tz = tz_of(FARM)
        near, others = None, []
        try:
            for sh in GeoShape.query.filter_by(type='site').order_by(GeoShape.id).all():
                slat, slon, ssrc = resolve_coords(target_id=sh.unique_id)
                if slat is None or ssrc in ('system', 'utc'):
                    continue
                km = cls._km_between(lat, lon, slat, slon)
                label = cls._shape_display_name(sh) or sh.unique_id
                if km <= cls._FORECAST_DEFAULT_KM:
                    if near is None or km < near[0]:
                        near = (km, label)
                else:
                    others.append(label)
        except Exception:                                   # noqa: BLE001
            logger.debug("forecast default site lookup failed", exc_info=True)
        name = near[1] if near else "farm default"
        out = {"name": name, "kind": "farm", "id": None, "lat": lat, "lon": lon,
               "tz": getattr(tz, 'zone', None) or str(tz), "basis": "default",
               "coord_source": src}
        if others:
            out["other_places"] = others[:8]
            notes.append("Answered for the farm default (%s). Other sites exist — "
                         "ask which, or call again with place." % name)
        if notes:
            out["_notes"] = notes
        return out

    @staticmethod
    def _parse_forecast_start(start, tz_name, now_utc_dt):
        """start → (시작 칸(지역 naive datetime), now 칸, 알림 목록) 또는 오류 str.

        now / today / tomorrow / day_after [+ ' HH:MM'] / 지역 YYYY-MM-DD[THH:MM]
        (오프셋이 있으면 그 지역시각으로 환산). 지난 오늘 시각은 지금 칸으로 당긴다."""
        import re
        from datetime import datetime as _dt, timedelta as _td
        from aot.utils.timekit import tz_of, wall_to_utc
        tz = tz_of(tz_name)
        now_local = now_utc_dt.astimezone(tz).replace(tzinfo=None)
        now_hour = now_local.replace(minute=0, second=0, microsecond=0)
        allowed = ("Use now, today, tomorrow, day_after (optionally + ' HH:MM'), or a "
                   "local date YYYY-MM-DD[THH:MM].")
        s = str(start if start not in (None, '') else 'now').strip()
        low = s.lower()
        notes = []
        if low == 'now':
            return now_hour, now_hour, notes
        m = re.match(r'^(today|tomorrow|day_after)(?:\s+(\d{1,2}):(\d{2}))?$', low)
        if m:
            day = now_hour.replace(hour=0) + _td(days={'today': 0, 'tomorrow': 1,
                                                      'day_after': 2}[m.group(1)])
            hh = int(m.group(2) or 0)
            if hh > 23 or int(m.group(3) or 0) > 59:
                return "Unknown time '%s'. %s" % (s, allowed)
            # 벽시계 → 순간 → 그 장소 칸. 명시 시각 경로와 같은 정책(간극은 한 시간 뒤, 중복은 두 번째)
            st = wall_to_utc(day.replace(hour=hh), tz_name).astimezone(tz).replace(tzinfo=None)
        else:
            try:
                # 오프셋이 있으면 그 순간, 없으면 그 장소의 벽시계 — 어느 쪽이든 장소 현지 칸으로
                dt = wall_to_utc(s, tz_name).astimezone(tz).replace(tzinfo=None)
            except ValueError:
                return "Unknown start '%s'. %s" % (s, allowed)
            st = dt.replace(minute=0, second=0, microsecond=0)
        if st.date() < now_hour.date():
            return "start '%s' is in the past (local today is %s). %s" % (
                s, now_hour.date().isoformat(), allowed)
        if st < now_hour:
            notes.append("start was already past — moved to the current hour")
            st = now_hour
        return st, now_hour, notes

    @classmethod
    def get_weather_forecast(cls, place=None, start='now', hours=24, user_id=None,
                             detail=None, sensor_type=None, **extra):
        """[읽기전용] 장소별 시간·일 단위 예보 — 선제 제어 조언의 근거.

        장소는 요청(place) > 화면(열린 지도 창, 없으면 보이는 지도가 비추는 대지) > 농장 기본 좌표 순으로 풀린다. 장소가 대지에 속하면 그 대지의 예보
        계열(지도 날씨 독·디지털트윈과 같은 출처, `geo/forecast_series`)만 쓴다. 대지가 아닌 장소(또는 대지에 예보
        출처도 지도 날씨 레이어도 없을 때)만 사용자가 등록한 Open-Meteo 출처로 좌표 조회한다. 모델 값이지 실측이 아니다.

        `detail`: None = 예전 모양(시간 행 전부) · False = 요약(시간 행을 항목별 최저·최고·평균과
        극값 시각으로 접는다, 일 행은 그대로) · True = 시간 행. `sensor_type` 을 주면 그 항목만.
        """
        try:
            from datetime import timedelta as _td
            notes = []
            try:
                limit = int(hours)
            except (TypeError, ValueError):
                limit = 24
            if limit < 1:
                return {"status": "error",
                        "message": "hours must be at least 1 (max %d)."
                                   % cls._FORECAST_MAX_HOURS}
            if limit > cls._FORECAST_MAX_HOURS:
                limit = cls._FORECAST_MAX_HOURS
                notes.append("hours cut to %d (the most this tool reads is 14 days)"
                             % limit)
            at = cls._forecast_place(place, user_id)
            if at.get("status") == "unavailable" and not cls._open_meteo_forecast_source():
                # 장소도 못 풀고 좌표 조회 출처도 없다 — 무엇을 등록하면 되는지 알린다
                return {"status": "unavailable",
                        "message": cls._NO_FORECAST_HINT,
                        "forecast_hint": cls._NO_FORECAST_HINT}
            if at.get("error") or at.get("status") in ("unavailable",
                                                       "needs_disambiguation"):
                return at
            notes = list(at.pop("_notes", [])) + notes
            tz_name = at["tz"]

            from aot.utils.timekit import utc_now as _utc_now
            parsed = cls._parse_forecast_start(start, tz_name, _utc_now())
            if isinstance(parsed, str):
                return {"status": "error", "message": parsed}
            start_dt, now_hour, start_notes = parsed
            notes += start_notes

            # 대지에 속한 장소는 그 대지의 예보 계열 하나 — 지도 슬라이더·트윈과 같은 출처. 지정 계열이 요청을 다 덮지
            # 못해도 다른 출처로 메우지 않는다(범위 밖은 자르고 알린다).
            site_fc = cls._site_forecast(at, tz_name)
            attr_cfg = {}
            if site_fc:
                bundle, info, err = site_fc["bundle"], site_fc["info"], None
                label, ref = site_fc["label"], site_fc["ref"]
            else:
                found = cls._open_meteo_forecast_source()
                if not found:
                    return {"status": "unavailable",
                            "message": cls._NO_FORECAST_HINT,
                            "forecast_hint": cls._NO_FORECAST_HINT}
                from aot.tools import providers
                api_key = ''
                if found["kind"] == "data_source":
                    src = found["src"]
                    try:
                        api_key = found["svc"].source_api_key(src['source_id'])
                    except Exception:                       # noqa: BLE001
                        api_key = ''
                    try:
                        got = found["svc"].source_config(src['source_id'])
                        attr_cfg = got if isinstance(got, dict) else {}
                    except Exception:                       # noqa: BLE001
                        attr_cfg = {}
                    label, ref = src.get('label'), src['source_id']
                else:
                    inp = found["input"]
                    label, ref = inp.name, inp.unique_id
                bundle, info, err = providers.get('forecast_bundle')(
                    at["lat"], at["lon"], tz_name, api_key or None)
            what = "The site's forecast series" if site_fc else "Open-Meteo forecast query"
            if err or not bundle:
                return {"status": "unavailable",
                        "message": "%s failed: %s" % (what, err or "no data"),
                        "source_ref": ref, "answered_for": cls._forecast_who(at)}
            meta = bundle.get('meta') or {}
            hourly = bundle.get('hourly') or []
            daily = bundle.get('daily') or []
            times = []
            for r in hourly:
                try:
                    times.append(cls._fc_dt(r.get('time')))
                except ValueError:
                    times.append(None)
            valid = [t for t in times if t is not None]
            day_ends = []
            for r in daily:
                try:
                    day_ends.append(cls._fc_dt(r.get('date') or r.get('time')) + _td(days=1))
                except ValueError:
                    continue
            hourly_until = max(valid) + _td(hours=bundle.get('step_hours') or 1) if valid else None
            available_until = max([d for d in [hourly_until] + day_ends if d is not None], default=None)
            if available_until is None:
                return {"status": "unavailable", "source_ref": ref,
                        "message": "%s returned no rows." % what}
            end_dt = start_dt + _td(hours=limit)
            span_text = ("the site's forecast source" if site_fc else "Open-Meteo (14 days)")
            if start_dt >= available_until:
                return {"status": "unavailable", "source_ref": ref, "source_basis": site_fc and site_fc["basis"],
                        "message": ("That start is beyond the forecast range of %s (until %s)."
                                    % (span_text, available_until.strftime('%Y-%m-%d %H:%M')))}
            truncated = end_dt > available_until
            if truncated:
                notes.append("Beyond the forecast range of %s — cut at %s; nothing after that is filled in."
                             % (span_text, available_until.strftime('%Y-%m-%d %H:%M')))

            period = {"start": start_dt.strftime('%Y-%m-%dT%H:%M'),
                      "end": min(end_dt, available_until).strftime('%Y-%m-%dT%H:%M'),
                      "hours": limit}
            if truncated:
                period["truncated"] = True
            daily_tail = []
            if limit > 72 or not valid or start_dt >= hourly_until:
                rows = cls._forecast_daily_rows(daily, start_dt, now_hour, limit)
                period["daily"] = True
                if start_dt.date() == now_hour.date() and now_hour.hour > 0 and rows:
                    notes.append("Today's daily row covers the whole local day, "
                                 "including hours already past.")
                step = 24
            else:
                step = max(1 if limit <= 24 else 3, int(bundle.get('step_hours') or 1))
                cell_h = bundle.get('step_hours') or 1
                if cell_h > 1:
                    # 여러 시간 칸(지도 레이어 폴백 3 h 등)은 칸 하나가 한 행이다 — 시작 시각이 든 칸부터.
                    window = [r for r, t in zip(hourly, times)
                              if t is not None and t + _td(hours=cell_h) > start_dt and t <= end_dt]
                else:
                    window = [r for r, t in zip(hourly, times)
                              if t is not None and start_dt <= t <= end_dt
                              and int((t - start_dt).total_seconds() // 3600) % step == 0]
                rows = cls._rows_from_now(window, tz_name, step)
                period["step_hours"] = step
                if site_fc and end_dt > hourly_until:
                    # 시간별 지평 뒤는 같은 계열의 일 행으로 잇는다(지도 독이 그 시각에 보이는 값과 같다).
                    after = hourly_until.replace(hour=0, minute=0)
                    span_h = max(1, int((end_dt - after).total_seconds() // 3600))
                    daily_tail = cls._forecast_daily_rows(daily, after, now_hour, span_h)
                    if daily_tail:
                        notes.append("Hourly rows stop at %s (end of the hourly part of this source); "
                                     "`daily_forecasts` continue with local-day rows from the same source."
                                     % hourly_until.strftime('%Y-%m-%d %H:%M'))
            if not rows and not daily_tail:
                return {"status": "unavailable", "source_ref": ref,
                        "message": "%s returned no rows for that period." % what}

            who = cls._forecast_who(at)
            glat, glon = meta.get('grid_latitude'), meta.get('grid_longitude')
            grid = {"lat": glat, "lon": glon, "elevation_m": meta.get('elevation_m')}
            if glat is not None and glon is not None:
                grid["distance_km"] = round(
                    cls._km_between(at["lat"], at["lon"], glat, glon), 1)
            result = {
                "status": "success",
                "source": "site_forecast" if site_fc else "open_meteo",
                "source_name": label,
                "source_ref": ref,
                "latitude": glat,
                "longitude": glon,
                "elevation_m": meta.get('elevation_m'),
                "timezone": meta.get('timezone') or tz_name,
                "requested_hours": limit,
                "step_hours": step,
                "count": len(rows),
                "answered_for": who,
                "grid": grid,
                "period": period,
                "forecasts": rows,
            }
            if daily_tail:
                result["daily_forecasts"] = daily_tail
            result["data"] = cls._forecast_data_info(info, tz_name)
            if site_fc:
                result["source_basis"] = site_fc["basis"]
                result["source_basis_text"] = site_fc["basis_text"]
                result["source_segments"] = site_fc["segments"]
                cal = site_fc["calibration"]
                if cal["applied"]:
                    # 현장 관측으로 고친 값이다 — 원본(모델 값)이 아니라는 것과 무엇을 고쳤는지만 알린다.
                    result["forecast_calibration"] = {"applied": True, "adjusted": cal["variables"],
                                                      "revision": cal["rev"]}
                    notes.append("Values marked by `forecast_calibration` are the model forecast adjusted to this "
                                 "site's own weather-station history (adjusted: %s); other variables are unadjusted."
                                 % ", ".join(cal["variables"]))
                else:
                    result["forecast_calibration"] = {"applied": False}
            else:
                result["source_basis"] = "coordinate_query"
                result["source_basis_text"] = ("this place is not inside a site with a forecast source or map weather "
                                               "layer — the registered Open-Meteo source was queried at its coordinates")
            if at.get("other_places"):
                result["other_places"] = at["other_places"]
            if (at.get("match") or '') == 'partial':
                who["match"] = 'partial'
                notes.append("Matched '%s' only partly — confirm this is the place "
                             "meant." % at["name"])
            if info and info.get("stale"):
                notes.append("Forecast is %d h old (source unreachable) — say so."
                             % max(1, round(info.get("age_min", 0) / 60.0)))
            if site_fc:
                notes.append("Model forecast from '%s' — the same series the map's weather dock and the "
                             "digital twin use for this site; not a measurement." % label)
            else:
                notes.append("Open-Meteo model forecast at the grid point above, not a "
                             "measurement at the site.")
            if not period.get("daily"):
                notes.append("Hourly rain and radiation on a row cover that hour "
                             "(time to time+%dh)." % (bundle.get('step_hours') or 1))
            result["note"] = " ".join(notes)
            # Open-Meteo 출처(CC BY)는 화면(측정값 독·소스 카드)이 표시한다. 응답에 실으면
            # AI 가 매번 답변에 되풀이하므로(2026-10-24 슬라이더 이동 뒤에도) 싣지 않는다.
            # 자료 해석 주의(caveat)는 라이선스가 아니므로 그대로 싣는다.
            if not site_fc:
                from aot.utils import source_attribution
                caveat = source_attribution.apply({}, attr_cfg, 'ext_openmeteo').get('caveat')
                if caveat:
                    result['caveat'] = caveat
            from aot.tools.data_tools import weather_summary as _ws
            # 일출·일몰 — 예보 출처가 아니라 그 장소 좌표의 태양시(어느 예보든 같다).
            _sun = _ws.sun_for(lat=at.get("lat"), lon=at.get("lon"),
                               dates=_ws.period_dates(period.get("start"), period.get("end")))
            if _sun:
                result["sun"] = _sun
            _tokens = _ws.field_tokens(sensor_type)
            if _ws.wants_summary(detail):
                return _ws.summarize_forecast(result, _tokens)
            return _ws.filter_forecast(result, _tokens) if _tokens else result
        except Exception as e:
            logger.exception("Error in get_weather_forecast")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _site_forecast(cls, at, tz_name):
        """장소가 속한 대지의 예보 계열(`forecast_series.read`) → AI 행 묶음, 대지가 아니거나 출처가 없으면 None.

        지정 계열·공통 폴백(지도 날씨 레이어) 모두 여기서 온다 — 지도 독·트윈과 같은 값이다. 요청 구간을 다 덮지
        못해도 None 으로 돌려 다른 출처로 넘기지 않는다(호출한 쪽이 범위 밖을 자르고 알린다)."""
        try:
            import time as _time
            from aot.space import forecast_series as fs
            site = fs.site_of_place(at.get("kind"), at.get("id"))
            if not site:
                return None
            from aot.utils.timekit import utc_now as _utc_now
            data = fs.read(site, now=_utc_now().timestamp(), lat=at.get("lat"), lon=at.get("lon"))
            if not data.get("available"):
                return None
            step_h = max(1, int(round(((data.get("resolution") or {}).get("step_s") or 3600) / 3600.0)))
            rows = fs.ai_hourly_rows(data.get("rows") or [], tz_name)
            days = fs.ai_daily_rows(data.get("daily") or [])
            fetched = data.get("fetched_at")
            age = max(0, int((_time.time() - float(fetched)) // 60)) if fetched else None
            grid = data.get("grid") or {}
            src = data.get("source") or {}
            names = []
            for sg in data.get("segments") or []:
                n = (sg.get("source") or {}).get("name")
                if n and n not in names:
                    names.append(n)
            cal = data.get("calibration") or {}
            return {"calibration": {"applied": bool(data.get("calibrated")), "rev": int(data.get("cal_rev") or 0),
                                    "variables": cls._fc_cal_names(cal.get("variables"))},
                    "bundle": {"meta": {"grid_latitude": grid.get("grid_latitude"),
                                        "grid_longitude": grid.get("grid_longitude"),
                                        "elevation_m": grid.get("elevation"),
                                        "timezone": tz_name},
                               "hourly": rows, "daily": days, "step_hours": step_h},
                    "info": {"from": "input" if data["source_basis"] == "designated" else "map_layer",
                             "fetched_at": fetched, "age_min": age, "stale": False},
                    "label": " + ".join(names) or src.get("name"), "ref": src.get("input_id") or site,
                    "basis": data["source_basis"], "basis_text": data.get("source_basis_text"),
                    "segments": [{"kind": sg["kind"], "source": (sg.get("source") or {}).get("name"),
                                  "start": cls._fc_local(sg["start"], tz_name),
                                  "end": cls._fc_local(sg["end"], tz_name)} for sg in data.get("segments") or []]}
        except Exception:                                   # noqa: BLE001
            logger.debug("site forecast unavailable", exc_info=True)
            return None

    @staticmethod
    def _fc_cal_names(codes):
        """보정 변수 코드 → 영어 이름(중복 없이, 순서 유지) — 응답의 `forecast_calibration.adjusted`."""
        from aot.utils.fc_cal.apply import VAR_NAMES
        out = []
        for c in codes or []:
            n = {"T": "temperature", "TMAX": "daily high", "TMIN": "daily low", "RH": "humidity",
                 "WS": "wind speed", "SOL": "solar radiation", "RAIN": "rain"}.get(c) or VAR_NAMES.get(c, c).lower()
            if n not in out:
                out.append(n)
        return out

    @staticmethod
    def _fc_local(epoch, tz_name):
        from datetime import datetime as _dt
        from aot.utils.timekit import tz_of
        return _dt.fromtimestamp(float(epoch), tz_of(tz_name)).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M')

    @staticmethod
    def _fc_dt(text):
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(text))

    @staticmethod
    def _forecast_who(at):
        who = {k: at[k] for k in ("name", "kind", "lat", "lon", "tz", "basis",
                                  "coord_source") if k in at}
        if at.get("match"):
            who["match"] = at["match"]
        return who

    @staticmethod
    def _forecast_data_info(info, tz_name):
        from datetime import datetime as _dt, timezone as _tzm
        from aot.utils.timekit import tz_of
        info = info or {}
        fetched = info.get("fetched_at")
        try:
            fetched = _dt.fromtimestamp(float(fetched), tz=_tzm.utc) \
                .astimezone(tz_of(tz_name)).isoformat(timespec='minutes')
        except (TypeError, ValueError):
            fetched = None
        return {"from": info.get("from"), "fetched_at": fetched,
                "age_min": info.get("age_min"), "stale": bool(info.get("stale"))}

    @classmethod
    def _forecast_daily_rows(cls, daily, start_dt, now_hour, hours):
        """일별 행 — 시작 날짜부터 ceil(hours/24)일. day_offset 0 = 오늘(지역)."""
        import math
        from datetime import timedelta as _td
        first = start_dt.date()
        count = math.ceil(hours / 24.0)
        last = first + _td(days=count - 1)
        out = []
        for r in daily:
            try:
                d = cls._fc_dt(r.get('date') or r.get('time')).date()
            except ValueError:
                continue
            if first <= d <= last:
                row = {k: v for k, v in r.items() if k != 'time'}
                out.append({"date": d.isoformat(),
                            "day_offset": (d - now_hour.date()).days, **row})
        return out

    @classmethod
    def get_anomalies(cls, scope_type="system", scope_id=None, **extra):
        """[읽기전용] 지금 이상 상태가 있는지 — 임계 위반·오프라인 비율 등.

        기존에는 이상탐지가 백그라운드 감시 파이프라인으로만 존재해서 AI가
        "지금 이상 있나?"를 물어볼 수단이 없었다. 감시 로직을 그대로 재사용해
        온디맨드 조회로 노출한다. 판정만 하고 알림 발송은 하지 않는다.
        """
        try:
            # 범위를 못 찾으면 조용히 '이상 없음' 을 내지 않는다(2026-10-10 외부 AI
            # 5차 점검). 예전에는 모르는 scope_type 은 시스템 전체를 그 이름표로
            # 평가했고, 없는 지도 id(farm)는 장치 0개로 '이상 없음' 이었다.
            scope_type = (scope_type or 'system').strip().lower()
            if scope_type not in ('system', 'farm', 'zone', 'site', 'facility'):
                return {"error": "Unknown scope_type '%s' — use system, farm, "
                                 "zone, site or facility." % scope_type}
            if scope_type != 'system' and not scope_id:
                return {"error": "scope_type '%s' needs scope_id (its id or "
                                 "name). Omit scope_type for the whole system."
                                 % scope_type}
            if scope_type == 'farm':
                from aot.databases.models import GeoMap
                _m = (GeoMap.query.filter_by(unique_id=scope_id).first()
                      or GeoMap.query.filter_by(name=scope_id).first())
                if _m is None:
                    return {"error": "No map '%s' — scope_type 'farm' takes a map "
                                     "id or name (find.tree)." % scope_id}
                scope_id = _m.unique_id
            if scope_type in ('zone', 'site') and scope_id:
                # 이름도 받는다(다른 장소 인자와 같은 규칙). 모호하면 후보를 낸다.
                place, perr = cls._read_place(scope_id, arg='scope_id')
                if perr:
                    return perr
                scope_id = place.unique_id
            elif scope_type == 'facility' and scope_id:
                # 시설 범위는 시설 행 ID 를 기대한다 — 공간 트리의 시설(도형) ID 나
                # 이름으로 부르면 시설을 못 찾아 장치 0개로 '이상 없음' 이 됐다
                # (2026-10-09 외부 점검: 육묘장3 도형 ID → 센서 0, 시설 ID → 2).
                fac = cls._resolve_facility(scope_id)
                if fac is None:
                    return {"error": "No facility '%s' — pass its id from "
                                     "get_spatial_tree / get_control_state, or "
                                     "its exact name." % scope_id}
                scope_id = fac.unique_id
            from aot.tools import providers
            summary = providers.get('anomaly_summary')(scope_type, scope_id)

            out = {
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
                        "signal. To find long-silent devices call get_device_freshness. "
                        "The devices behind this number are listed in "
                        "'comm_offline_list' (id + name)."),
                    "silent_devices": (
                        "A DIFFERENT axis from comm_offline_devices: active inputs "
                        "that sent no value for 3+ of their own periods (or never "
                        "did). count = get_device_freshness' stale_count + "
                        "no_data_count (switched-off inputs are excluded there as "
                        "inactive_count). A device can be in one, both or neither "
                        "list, so the two numbers are not expected to match."),
                },
                "compared_with": ("이전 요약 v%s" % summary['previous_version']
                                 if summary.get('previous_version') is not None else None),
                # 현지시각으로 낸다. 이 값은 get_system_brief 에 그대로 실려
                # 나가는데, 거기서는 **시각처럼 보이는 유일한 필드**라 읽는 쪽이
                # "지금" 으로 집어 든다 — UTC 로 두었더니 한낮 14:10 을 새벽
                # 05:10 으로 읽고 "곧 05:30 관수" 라고 답한 일이 있었다
                # (2026-09-16). 지금 시각 자체는 응답의 `now` 가 따로 싣는다.
                # 구역·대지 범위로 불렀으면 그 장소의 시각이다(시스템 범위는
                # 장소가 없어 농장 시각으로 떨어진다).
                "evaluated_at": (iso_at(summary.get('timestamp'), scope_id)
                                 if scope_id else iso_at(summary.get('timestamp'), FARM)),
            }
            offline = summary.get('comm_offline_list') or []
            if offline:
                try:
                    from aot.space.device_membership import PlaceIndex
                    _paths = {k: v[0] for k, v in PlaceIndex().device_paths(
                        [x.get('device_id') for x in offline]).items()}
                except Exception:                           # noqa: BLE001
                    _paths = {}
                out["comm_offline_list"] = [
                    dict(x, **cls._place_fields(_paths.get(x.get('device_id'))))
                    for x in offline[:20]]
            silent = cls._silent_devices_in_scope(scope_type, scope_id)
            # alert_level 은 그대로 둔다(이메일·푸시·지도 위젯이 쓴다). 침묵 판정은
            # 별도 필드 silent_level(none/info/warning)로만 낸다.
            out["silent_level"] = (silent or {}).get('silent_level', 'none')
            if silent:
                out["silent_devices"] = silent
                if silent.get('severity_hint'):
                    out["severity_hint"] = silent['severity_hint']
                out["_reading"] = [
                    "'silent_devices' are NOT faults and are NOT in alert_level — "
                    "they simply sent no value for 3+ of their own periods (or never "
                    "did). silent_level (none/info/warning) is their own verdict: "
                    "if silent_level is 'warning' you MUST mention it to the user "
                    "(severity_hint 'high' = half or more of active sensors went "
                    "quiet recently). 'dormant' ones (quiet 30+ days) are "
                    "off-season/neglected and are excluded from the ratio. "
                    "get_device_freshness has the detail.",
                    "known_status = devices a person marked repair / maintenance "
                    "/ removed: they are NOT counted as silent (removed is only "
                    "counted in removed_count). Mention them as known, not as news. Other quiet devices "
                    "under repair: set the device status, or is_activated off / "
                    "ai_excluded."]
            return out
        except Exception as e:
            logger.exception("Error in get_anomalies")
            return {"status": "error", "message": str(e)}

    _FRESHNESS_PERIOD_FACTOR = 3

    _FRESHNESS_MIN_AGE_S = 300          # 하한: 주기가 아주 짧은 장치의 지터 흡수

    _FRESHNESS_SCAN_CAP_S = 30 * 86400  # 조회 창 상한(무제한 스캔 방지)

    _FRESHNESS_MAX_CHANNELS = 4         # 장치당 물어볼 채널 수 상한

    @classmethod
    def _freshness_threshold(cls, device):
        """(주기 초|None, 허용 침묵 초) — 주기의 3배, 하한 300초.

        get_device_freshness 와 이상 점검의 침묵 관찰이 **같은 규칙**을 쓰게
        한 곳에 둔다(두 판정자가 갈라지면 느슨한 쪽이 실질 판정이 된다).
        """
        try:
            period = float(device.period) if device.period else None
        except (TypeError, ValueError):
            period = None
        threshold = cls._FRESHNESS_MIN_AGE_S
        if period:
            threshold = max(threshold, period * cls._FRESHNESS_PERIOD_FACTOR)
        return period, threshold

    @classmethod
    def _last_seen_seconds(cls, device_id, window_s=None, max_channels=None):
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
        for m in rows[:(max_channels or cls._FRESHNESS_MAX_CHANNELS)]:
            conversion = (Conversion.query.filter(
                Conversion.unique_id == m.conversion_id).first()
                if m.conversion_id else None)
            channel, unit, measurement = return_measurement_info(m, conversion)
            try:
                last_time, _ = read_influxdb_single(
                    device_id, unit, channel, measure=measurement,
                    duration_sec=int(window_s or cls._FRESHNESS_SCAN_CAP_S),
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
            age = (utc_now() - seen).total_seconds()
            # 장치 자기 위치의 시각으로 낸다. 경과초(age)는 이미 절대시간 차라
            # 영향이 없고, 바뀌는 것은 표시뿐이다 — 그런데 이 표시가 UTC 로
            # 나가면 같은 응답 묶음 안에서 센서값(장치 현지)과 기준이 갈려
            # "마지막 수신 08:39 / 현재값 14:06" 이 나란히 놓인다(9시간 어긋난
            # 것을 9시간 침묵으로 읽는다).
            from aot.utils.timekit import iso_at
            seen_iso = iso_at(seen, device_id)
        except Exception:
            return None, None, None
        return max(0.0, age), seen_iso, newest_label

    @classmethod
    def channel_names(cls, device_id):
        """장치의 켜진 채널 이름(측정 이름) — 채널 번호 순, 중복 없이. DB 만 읽는다."""
        rows = [m for m in DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == device_id).all() if getattr(m, 'is_enabled', True)]
        rows.sort(key=lambda m: (m.channel if m.channel is not None else 9999))
        names = []
        for m in rows:
            conversion = (Conversion.query.filter(Conversion.unique_id == m.conversion_id).first()
                          if m.conversion_id else None)
            _channel, _unit, measurement = return_measurement_info(m, conversion)
            name = measurement or m.measurement
            if name and name not in names:
                names.append(name)
        return names

    @classmethod
    def silent_channels(cls, device_id, within_s):
        """장치의 채널 중 `within_s` 초 안에 값이 없는 것 → [{measurement, last_seen, age_readable}].

        freshness 는 처음 답하는 채널에서 멈춰 "장치가 말했다" 만 알린다 — 온도·습도는 7일째 끊겼는데 배터리만
        들어와도 정상이다(2026-11-03 시험 #3). 분류는 그대로 두고 끊긴 채널만 곁에 적는다. 채널마다 한 번씩
        묻기 때문에 장치 하나를 지목했을 때만 쓴다(전체 목록에서는 질의가 채널 수만큼 는다)."""
        from aot.utils.influx import read_influxdb_single
        from aot.utils.timekit import iso_at
        rows = [m for m in DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == device_id).all() if getattr(m, 'is_enabled', True)]
        rows.sort(key=lambda m: (m.channel if m.channel is not None else 9999))
        out, seen = [], set()
        for m in rows:
            conversion = (Conversion.query.filter(Conversion.unique_id == m.conversion_id).first()
                          if m.conversion_id else None)
            channel, unit, measurement = return_measurement_info(m, conversion)
            name = measurement or m.measurement
            if not name or name in seen:
                continue
            try:
                last_time, _ = read_influxdb_single(
                    device_id, unit, channel, measure=measurement,
                    duration_sec=int(cls._FRESHNESS_SCAN_CAP_S), value='LAST')
            except Exception:
                logger.debug("[FRESHNESS] %s ch%s 조회 실패", device_id, channel, exc_info=True)
                continue
            age = None
            if last_time:
                age = max(0.0, utc_now().timestamp() - float(last_time))
            if age is not None and age <= within_s:
                seen.add(name)                          # 같은 이름의 다른 채널이 최근이면 말한 것으로 본다
                out = [c for c in out if c['measurement'] != name]
                continue
            if name in seen or any(c['measurement'] == name for c in out):
                continue
            out.append({"measurement": name,
                        "last_seen": iso_at(float(last_time), device_id) if last_time else None,
                        "age_readable": cls._readable_age(age) if age is not None else None})
        return out

    @classmethod
    def partial_silent_channels(cls, items, detail=False):
        """정상으로 분류된 장치들 중 **일부 채널만 끊긴** 것 → {device_id: [{measurement, (last_seen, age_readable)}]}.

        `items` = [(Input, 허용 침묵 초)]. 장치마다 `silent_channels` 를 부르면 질의가 채널 수만큼 늘어 목록에서는 못 쓴다 —
        여기서는 허용 시간이 같은 장치끼리 묶어 **Flux 질의 한 묶음에 한 번**(`query_last_values_bulk_status`)으로 전 채널의
        마지막 값을 받고, 각 채널이 그 장치의 허용 시간 안에 있는지만 본다. 묶는 이유: 질의 시간은 창 길이에 비례해(실측 15분 0.06초
        · 1일 2초 · 3일 6초 · 30일 60초 초과) 가장 긴 허용 시간을 모두에게 쓰면 느린 센서 하나가 전부를 느리게 한다.
        같은 이름의 다른 채널이 최근이면 말한 것으로 본다(`silent_channels` 와 같은 규칙).
        `detail` 이면 끊긴 채널이 있는 장치에만 기존 `silent_channels` 를 불러 `last_seen`·`age_readable` 을 채운다(30일 창은
        묶음 질의로 못 한다 — 위 이유). 질의가 실패하면 그 묶음은 싣지 않는다 — 모르는 것을 끊겼다고 하지 않는다.
        장치의 채널이 전부 끊겼으면(정상 분류가 아닌 경우) 싣지 않는다."""
        from aot.utils.influx import bulk_key, query_last_values_bulk_status
        groups = {}                                         # 허용 시간 → (specs, {장치: [(이름, 키)]})
        for d, within_s in items:
            specs, by_dev = groups.setdefault(int(within_s), ([], {}))
            chans = []
            for m in sorted((m for m in DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == d.unique_id).all() if getattr(m, 'is_enabled', True)),
                            key=lambda m: (m.channel if m.channel is not None else 9999)):
                conversion = (Conversion.query.filter(Conversion.unique_id == m.conversion_id).first()
                              if m.conversion_id else None)
                channel, unit, measurement = return_measurement_info(m, conversion)
                name = measurement or m.measurement
                if not name:
                    continue
                specs.append((unit, d.unique_id, channel, measurement))
                chans.append((name, bulk_key(unit, d.unique_id, channel, measurement)))
            by_dev[d.unique_id] = chans
        quiet, now = {}, utc_now().timestamp()
        for within_s, (specs, by_dev) in groups.items():
            if not specs:
                continue
            last, ok = query_last_values_bulk_status(
                specs, past_sec=min(max(within_s, 1), cls._FRESHNESS_SCAN_CAP_S))
            if not ok:
                continue
            for did, chans in by_dev.items():
                alive = {n for n, k in chans if k in last and now - float(last[k][0]) <= within_s}
                names = [n for n in dict.fromkeys(n for n, _k in chans) if n not in alive]
                if alive and names:                          # 말한 채널이 있고 끊긴 채널도 있다 = 일부 끊김
                    quiet[did] = (within_s, names)
        if not detail:
            return {did: [{"measurement": n} for n in names] for did, (_w, names) in quiet.items()}
        return {did: cls.silent_channels(did, within_s) for did, (within_s, _n) in quiet.items()}

    @classmethod
    def _place_fields(cls, path):
        """장소 경로 → 응답 필드. 지도에 놓이지 않은 장치(place 없음)는 null 만 내면
        '어디인지 모름' 인지 '필드 누락' 인지 구분되지 않는다 — 사실을 명시한다."""
        if path:
            return {"place": path}
        return {"place": None, "place_note": "not placed on any map (no location)"}

    @classmethod
    def _silent_devices_in_scope(cls, scope_type, scope_id):
        """범위 안에서 허용 시간보다 오래 조용한 장치 → 요약 dict 또는 None.

        이상 점검은 장치가 스스로 통신 장애를 보고한 것만 센다 — 침묵은 장애가
        아니라는 규칙(CLAUDE.md '데이터 없음은 장애가 아니다')은 그대로다. 그런데
        그 결과만 보면 '이상 없음' 으로 읽혀, 25일째 무응답인 센서가 대화에서
        사라졌다(2026-10-09 외부 점검). 판정이 아니라 **관찰**로 곁에 싣는다.

        get_device_freshness 를 그대로 부르면 장치마다 30일을 거슬러 찾느라
        7~8초가 들었다 — 이 응답은 시스템 요약에도 실린다. 여기서는 "허용 시간
        안에 값이 있는가" 만 묻는다(같은 허용 시간 규칙, `_freshness_threshold`).
        얼마나 오래인지는 get_device_freshness 의 몫이다.
        """
        try:
            from aot.services.resolvers.device_resolver import ai_excluded
            from aot.services.resolvers.device_resolver import (
                device_status_info, is_reliable_sensor)
            devices = [d for d in Input.query.filter_by(is_activated=True).all()
                       if not ai_excluded(d)]
        except Exception:                                   # noqa: BLE001
            return None
        if scope_id and scope_type in ('zone', 'site'):
            from aot.space.device_membership import place_members
            keep = place_members(scope_id) or set()
            devices = [d for d in devices if d.unique_id in keep]
        elif scope_id and scope_type == 'facility':
            fac = cls._resolve_facility(scope_id)
            keep = {x.get('device_id') for x in ((fac.sensors if fac else None) or [])
                    if isinstance(x, dict)}
            devices = [d for d in devices if d.unique_id in keep]
        # 수리 중·철거됨·점검 중은 침묵 판정(비율 분모 포함)에서 뺀다. 철거됨은
        # 아예 접고, 나머지는 '알려진 상태' 로 곁에 싣는다(경보 오탐 방지).
        known = [d for d in devices if not is_reliable_sensor(d)]
        devices = [d for d in devices if is_reliable_sensor(d)]
        # 두 단계로 get_device_freshness 와 **같은 결론**을 낸다. 그 판정은
        # "값이 있는 첫 채널" 의 나이라, 짧은 창으로 아무 채널이나 보면 첫 채널
        # (온도)은 25일째 조용한데 뒤 채널(신호 세기)이 살아 있는 장치를 놓친다
        # (2026-10-09 실측: 온습도_4·_1). 1) 첫 채널만 허용 시간 안에 값이 있는지
        # 묻고(싸다), 2) 없는 것만 freshness 와 같은 조회로 다시 판정한다.
        silent, fresh_items = [], []
        for d in devices:
            _period, threshold = cls._freshness_threshold(d)
            try:
                quick, _i, _l = cls._last_seen_seconds(
                    d.unique_id, window_s=threshold, max_channels=1)
                if quick is not None:
                    fresh_items.append((d, threshold))
                    continue
                age, _iso, _label = cls._last_seen_seconds(d.unique_id)
            except Exception:                               # noqa: BLE001
                continue
            if age is None or age > threshold:
                silent.append((d, age))
            else:
                fresh_items.append((d, threshold))
        # 정상으로 센 장치 중 일부 채널만 끊긴 것의 수 — 침묵 판정(silent_level)에는 영향이 없다. 질의 한 번.
        try:
            partial_n = len(cls.partial_silent_channels(fresh_items)) if fresh_items else 0
        except Exception:                                   # noqa: BLE001
            partial_n = 0
        try:
            from aot.space.device_membership import PlaceIndex
            paths = {k: v[0] for k, v in PlaceIndex().device_paths(
                [d.unique_id for d in devices]).items()}
        except Exception:                                   # noqa: BLE001
            paths = {}
        control_ids = cls._control_input_ids(scope_type, scope_id)
        verdict = cls._silent_verdict(
            [(d.unique_id, d.name, age) for d, age in silent],
            [d.unique_id for d in devices], paths, control_ids)
        if partial_n:
            if verdict is None:
                verdict = {"count": 0, "silent_level": "none"}
            verdict["partial_silent_count"] = partial_n
        if known:
            listed = [dict(device_status_info(d), name=d.name,
                           device_id=d.unique_id)
                      for d in known if d.device_status != 'removed']
            removed = len(known) - len(listed)
            if verdict is None and listed:
                # 침묵은 없지만 알려진 상태가 있다 — 호출부는 truthy 면
                # silent_devices 로 싣는다.
                verdict = {"count": 0, "silent_level": "none"}
            if verdict is not None:
                if listed:
                    verdict["known_status"] = listed
                if removed:
                    verdict["removed_count"] = removed
        return verdict

    _SILENT_RECENT_S = 7 * 86400        # 이 이하면 "최근에 끊긴" 침묵
    _SILENT_DORMANT_S = 30 * 86400      # 이 넘게 조용하면 오프시즌·방치(dormant)
    _SILENT_MIN_COUNT = 2
    _SILENT_WARN_RATIO = 0.25
    _SILENT_HIGH_RATIO = 0.5

    @classmethod
    def _control_input_ids(cls, scope_type, scope_id):
        """환경제어 입력으로 쓰이는 센서 id 집합(시설 센서 목록 fac.sensors)."""
        try:
            from aot.databases.models import GeoFacility
            if scope_type == 'facility' and scope_id:
                fac = cls._resolve_facility(scope_id)
                facs = [fac] if fac else []
            else:
                facs = GeoFacility.query.all()
            return {x.get('device_id') for f in facs
                    for x in (f.sensors or []) if isinstance(x, dict)
                    and x.get('device_id')}
        except Exception:                                   # noqa: BLE001
            return set()

    @classmethod
    def _silent_verdict(cls, silent, active_ids, paths, control_ids):
        """침묵 판정(순수 계산 — 추가 조회 없음). silent = [(id, name, age|None)].

        age None = 30일 안에 값이 없음 → dormant. 구역 단위 판정은 센서가 2개
        이상인 곳에서만(1개짜리 구역의 침묵은 곧 그 센서 하나의 침묵이다).
        """
        if not silent:
            return None
        dormant, recent, lingering = [], [], []
        for row in silent:
            age = row[2]
            if age is None or age > cls._SILENT_DORMANT_S:
                dormant.append(row)
            elif age <= cls._SILENT_RECENT_S:
                recent.append(row)
            else:
                lingering.append(row)
        total = len(active_ids)
        # dormant 는 비율의 분자·분모 모두에서 뺀다.
        dormant_ids = {r[0] for r in dormant}
        base = total - len(dormant_ids)
        ratio = (len(recent) / base) if base > 0 else 0.0

        recent_ids = {r[0] for r in recent}
        place_total, place_silent = {}, {}
        for uid in active_ids:
            if uid in dormant_ids:
                continue
            place_total[paths.get(uid)] = place_total.get(paths.get(uid), 0) + 1
            if uid in recent_ids:
                place_silent[paths.get(uid)] = place_silent.get(paths.get(uid), 0) + 1
        by_place = [{"place": pl, "silent": n, "active": place_total[pl]}
                    for pl, n in place_silent.items()]
        by_place.sort(key=lambda x: -x['silent'])
        whole_place = [b for b in by_place if b['place'] is not None
                       and b['active'] >= cls._SILENT_MIN_COUNT
                       and b['silent'] == b['active']]
        ctrl = [r for r in recent + lingering if r[0] in control_ids]

        level, hint = 'info', None
        if not (recent or lingering or ctrl):
            level = 'none'
        if (len(recent) >= cls._SILENT_MIN_COUNT
                and ratio >= cls._SILENT_WARN_RATIO) or whole_place or ctrl:
            level = 'warning'
            hint = 'high' if ratio >= cls._SILENT_HIGH_RATIO else None
        reasons = []
        if len(recent) >= cls._SILENT_MIN_COUNT and ratio >= cls._SILENT_WARN_RATIO:
            reasons.append('ratio')
        if whole_place:
            reasons.append('whole_place_silent')
        if ctrl:
            reasons.append('control_input_silent')

        def _row(r):
            return dict({"name": r[1], "device_id": r[0],
                         "silent_for": (cls._readable_age(r[2]) if r[2] is not None
                                        else "no value in 30 days")},
                        **cls._place_fields(paths.get(r[0])))

        def _top(rows):
            return [_row(r) for r in sorted(rows, key=lambda x: -(x[2] or 1e12))[:8]]

        out = {
            "silent_level": level,
            "count": len(silent),
            "recent_count": len(recent),
            "dormant_count": len(dormant),
            "active_total": total,
            "ratio": round(ratio, 3),
            "by_place": by_place[:8],
            "control_inputs_silent": [_row(r) for r in ctrl][:8],
            "examples": _top(recent + lingering),
            "detail": "get_device_freshness has the full list with periods.",
        }
        if dormant:
            out["dormant"] = _top(dormant)
        if hint:
            out["severity_hint"] = hint
        if reasons:
            out["warning_reasons"] = reasons
        return out

    @classmethod
    def get_device_freshness(cls, device_id=None, include_fresh=False, brief=False, **extra):
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

        `brief` 는 스키마에 없는 처리기 인자다 — 도메인 표면(measure.freshness)만 켠다. 장치를 지목하지도
        `include_fresh` 도 켜지 않았을 때만 듣는다: 끊긴 장치(stale·no_data)만 이름으로 싣고(필드는 판단에
        쓰는 것만), 꺼 둔 장치·알려진 상태 장치는 개수만 낸다. 판정은 그대로다 — 목록에서 접을 뿐이다.
        """
        try:
            q = Input.query
            if device_id:
                # 이름도 받는다(장치 상세와 같은 해석) — 모호하면 후보를 돌려준다.
                if Input.query.filter(Input.unique_id == device_id).first() is None:
                    row, kind, derr = cls._resolve_device_target(str(device_id))
                    if derr:
                        return derr
                    if kind != 'input':
                        return {"status": "error", "error": (
                            "'%s' is not a sensor input, so it has no report "
                            "freshness." % device_id)}
                    device_id = row.unique_id
                q = q.filter(Input.unique_id == device_id)
            # 'AI 판단에 포함' 을 끈 센서는 보지 않는다 — 지목했으면 이유를 준다.
            from aot.services.resolvers.device_resolver import (
                AI_EXCLUDED, ai_excluded, ai_excluded_error,
                device_status_info)
            devices = q.all()
            if device_id and devices and ai_excluded(devices[0]):
                return {"status": "error", "reason_code": AI_EXCLUDED,
                        "message": ai_excluded_error(devices[0])}
            devices = [d for d in devices if not ai_excluded(d)]
            if not devices:
                return {"status": "success", "checked": 0, "stale_devices": [],
                        "message": ("No such device." if device_id
                                    else "No inputs are registered.")}

            try:
                from aot.space.device_membership import PlaceIndex
                zone_map = {k: v[0] for k, v in PlaceIndex().device_paths(
                    [d.unique_id for d in devices]).items()}
            except Exception:
                zone_map = {}

            stale, fresh, no_data, inactive, known = [], [], [], [], []
            removed_count = 0
            for d in devices:
                period, threshold = cls._freshness_threshold(d)

                age, seen_iso, label = cls._last_seen_seconds(
                    d.unique_id)
                entry = {
                    "name": d.name,
                    "device_id": d.unique_id,
                    "driver": d.device,
                    "place": zone_map.get(d.unique_id),
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
                if not entry["place"]:
                    entry["place_note"] = cls._place_fields(None)["place_note"]
                _st = device_status_info(d)
                if _st:
                    # 수리 중·점검 중·철거됨은 '정지' 가 아니라 사람이 아는 상태다.
                    # 철거됨은 목록에서 접고 개수만 센다.
                    if _st["status"] == "removed":
                        removed_count += 1
                    else:
                        entry["device_status"] = _st
                        known.append(entry)
                elif not d.is_activated:
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
            partial = []
            if fresh and not (device_id and len(devices) == 1):
                # 지목하지 않은 목록: 정상 장치의 일부 채널 끊김을 따로 센다(질의 한 번). 지목하면 아래가 채널별로 본다.
                by_id = {d.unique_id: d for d in devices}
                try:
                    quiet = cls.partial_silent_channels(
                        [(by_id[e["device_id"]], e["expected_within_seconds"]) for e in fresh], detail=True)
                except Exception:                                   # noqa: BLE001
                    logger.debug("[FRESHNESS] partial silent scan failed", exc_info=True)
                    quiet = {}
                for e in fresh:
                    if e["device_id"] in quiet:
                        e["silent_channels"] = quiet[e["device_id"]]
                        partial.append(e)
            result = {
                "status": "success",
                "checked": len(devices),
                "basis": ("A device is listed as stale when its newest stored value is "
                          "older than %dx its own sampling period (minimum %ds). This is "
                          "an observation, not a fault verdict — see 'caveat'."
                          % (cls._FRESHNESS_PERIOD_FACTOR,
                             cls._FRESHNESS_MIN_AGE_S)),
                "counting": ("get_anomalies' silent_devices.count = stale_count + "
                             "no_data_count here; inactive_count (switched off) and "
                             "known_status (repair/maintenance/removed) are "
                             "not included. partial_silent_count = devices counted in fresh_count "
                             "that still lack a recent value on some channel (see silent_channels). comm_offline_devices there is a separate "
                             "axis (driver-reported link faults)."),
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
                "known_status_devices": known,
                "known_status_count": len(known),
                "removed_count": removed_count,
                "fresh_count": len(fresh),
                "partial_silent_count": len(partial),
                "partial_silent_devices": partial,
                "scan_window_days": int(cls._FRESHNESS_SCAN_CAP_S / 86400),
            }
            if include_fresh:
                result["fresh_devices"] = fresh
            if device_id and len(devices) == 1:
                result["device_id"] = devices[0].unique_id      # 풀린 대상(따라가기용)
                # 지목한 장치는 채널별로도 본다 — 어느 채널이 끊겼는지(분류는 위 그대로, 곁에 적을 뿐이다).
                _e = fresh[0] if fresh else None           # 끊긴 장치는 채널 전부가 늦다 — 정상으로 분류된 장치만
                if _e is not None:
                    _quiet = cls.silent_channels(devices[0].unique_id, _e["expected_within_seconds"])
                    if _quiet:
                        _e["silent_channels"] = _quiet
                        result["partial_silent_count"] = 1
                        result["partial_silent_devices"] = [_e]
                        result["silent_channels"] = _quiet
                        result["silent_channels_note"] = (
                            "These channels have no value within the expected interval although the device "
                            "reported on another channel, so it is not listed as stale.")
            if brief and not device_id and not include_fresh:
                result = cls._freshness_brief(result)
            return result
        except Exception as e:
            logger.exception("Error in get_device_freshness")
            return {"status": "error", "message": str(e)}

    #: 끊긴 장치 한 줄에 남기는 필드 — 나머지(드라이버·주기·초 단위 경과)는 장치 상세에 있다.
    _FRESHNESS_BRIEF_KEYS = ("name", "device_id", "place", "last_seen", "last_seen_channel",
                             "age_readable", "periods_late", "place_note")

    @classmethod
    def _freshness_brief(cls, result):
        """전체 freshness 응답 → 끊긴 장치만 이름인 모양. 값은 전체 응답의 것을 그대로 옮긴다."""
        def slim(rows):
            return [{k: r[k] for k in cls._FRESHNESS_BRIEF_KEYS if k in r and r[k] is not None}
                    for r in rows]
        out = {
            "status": result["status"],
            "next": {
                "call": ("measure(op='freshness', include_fresh=true) also names the switched-off, "
                         "known-status and normally reporting devices"),
                "why": "only silent devices are named; the others are counts"},
            "checked": result["checked"],
            "basis": result["basis"],
            "caveat": result["caveat"],
            "stale_count": result["stale_count"],
            "stale_devices": slim(result["stale_devices"]),
            "no_data_count": result["no_data_count"],
            "no_data_devices": slim(result["no_data_devices"]),
            "inactive_count": result["inactive_count"],
            "known_status_count": result["known_status_count"],
            "removed_count": result["removed_count"],
            "fresh_count": result["fresh_count"],
            "partial_silent_count": result["partial_silent_count"],
            "scan_window_days": result["scan_window_days"],
        }
        if result["partial_silent_devices"]:
            out["partial_silent_devices"] = [
                dict(row, silent_channels=[c["measurement"] for c in r["silent_channels"]])
                for row, r in zip(slim(result["partial_silent_devices"]), result["partial_silent_devices"])]
        return out

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

