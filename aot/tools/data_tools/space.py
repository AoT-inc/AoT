import logging
from ._shims import tz_scoped

logger = logging.getLogger(__name__)


from aot.tools import providers
from aot.tools.aot_data_tool_service import _control_targets_for
from aot.tools.aot_data_tool_service import _map_for_device_p2
from aot.tools.aot_data_tool_service import _plot_ended_on
from aot.tools.aot_data_tool_service import _plot_started_on
from aot.aot_flask.extensions import db
from aot.databases.models import GeoLayer
from aot.databases.models import GeoShape
from sqlalchemy import or_
from aot.functions.utils.water_net import parts as _water_parts
import json
from aot.utils.timekit import iso_at, naive_utc, utc_now
from aot.databases.geo_marker_kinds import MARKER_TYPES


class SpaceToolsMixin:

    @classmethod
    def _prune_depth(cls, nodes, depth):
        """`depth` 단계까지만 남기고, 잘라낸 자리에 무엇이 있었는지 적는다.

        빈 `children` 만 남기면 "이 구역에는 아무것도 없다" 로 읽힌다 — 잘린
        것과 없는 것은 다르고, 그 차이를 응답이 말하지 않으면 모델이 대신
        지어낸다. 그래서 자손을 **종류별로 세어** 남긴다: "이 구역 아래
        장치 5개" 를 알면 더 파야 할지 스스로 판단할 수 있다.
        """
        def descendants_by_type(node):
            counts = {}
            for child in node.get('children') or []:
                t = child.get('type') or 'unknown'
                counts[t] = counts.get(t, 0) + 1
                for t2, n in descendants_by_type(child).items():
                    counts[t2] = counts.get(t2, 0) + n
            return counts

        def cut(node, level):
            children = node.get('children') or []
            if level >= depth:
                if not children:
                    return node
                out = dict(node, children=[])
                out['children_omitted'] = descendants_by_type(node)
                return out
            return dict(node, children=[cut(c, level + 1) for c in children])

        return [cut(n, 1) for n in nodes]

    #: 공간 트리에서 장치로 치는 노드 종류 — 기본 보기에서 개수로 접는다.
    _TREE_DEVICE_TYPES = MARKER_TYPES

    @classmethod
    def _fold_devices(cls, nodes):
        """곳(대지·구역·시설…)은 **모든 깊이**에서 남기고, 장치 노드는 그 곳의
        `devices` 개수로 접는다. 노드에는 이름·종류·unique_id 만 남긴다."""
        def fold(node):
            kids = node.get('children') or []
            places = [fold(c) for c in kids
                      if c.get('type') not in cls._TREE_DEVICE_TYPES]
            ndev = sum(1 for c in kids
                       if c.get('type') in cls._TREE_DEVICE_TYPES)
            out = {k: node.get(k) for k in ('name', 'type', 'unique_id')
                   if node.get(k) is not None}
            # 맨 위에 놓인 장치 노드(어느 장소에도 안 든 것)는 접히지 않고 남는다.
            # 전체 보기(_compact_nodes)와 같이 실제 장치 ID 를 싣는다 — 보기마다
            # 같은 장치의 ID 가 달랐다(2026-10-09 외부 점검: OpenWeather 가
            # 기본 보기에서는 마커 번호, depth=0 에서는 장치 ID).
            if node.get('type') in cls._TREE_DEVICE_TYPES and node.get('device_id'):
                out['unique_id'] = node['device_id']
            if places:
                out['children'] = places
            if ndev:
                out['devices'] = ndev
            return out
        return [fold(n) for n in nodes]

    @classmethod
    def _merge_device_nodes(cls, nodes):
        """한 장소 안의 장치 노드를 장치 하나에 한 줄로 합치고 실제 이름을 단다.

        트리는 지도 **도형**을 그대로 내보낸다. 그래서 마커와 영역이 둘 다
        그려진 장치(밸브 대부분)는 두 줄이 되고, 이름도 장치가 아니라 도형의
        것이었다 — 영역은 'Device 526' 같은 기본 이름, 장치 이름을 바꾼 뒤의
        마커는 옛 이름(2026-10-09 로컬 27건). 장치 수도 도형을 세어 3-2 가
        12(실제 8)로 나와, 같은 질문에 search_devices 와 다른 답을 했다.

        새 dict 를 만든다 — 공급자가 캐시된 트리를 돌려줄 수 있어서, 제자리에서
        고치면 다음 호출이 이미 합쳐진 트리를 받는다.
        """
        dev_ids = []

        def collect(ns):
            for n in ns or []:
                if n.get('type') in cls._TREE_DEVICE_TYPES and n.get('device_id'):
                    dev_ids.append(n['device_id'])
                collect(n.get('children'))
        collect(nodes)
        names = cls._device_names(dev_ids)

        def merge(ns):
            out, seen = [], {}
            for n in ns or []:
                kids = merge(n.get('children'))
                dev = n.get('device_id') if n.get('type') in cls._TREE_DEVICE_TYPES else None
                if dev and dev in seen:
                    first = seen[dev]
                    if kids:
                        first['children'] = (first.get('children') or []) + kids
                    continue
                node = dict(n, children=kids)
                if dev:
                    if names.get(dev):
                        node['name'] = names[dev]
                    seen[dev] = node
                out.append(node)
            return out
        return merge(nodes)

    @classmethod
    def _compact_nodes(cls, nodes):
        """장치까지 펼친 트리(depth·filter_type)의 노드를 줄인다 — 빈 값은
        빼고 `properties` 는 펼친다(area → area_m2 정수, device_type 그대로).

        depth=0(전부)이 응답 상한(20,000 토큰)을 넘어 **매번** 잘렸다
        (2026-10-08 실측 20,493, 3회 모두). 잘리면 루트 목록이 줄어 어떤
        곳이 어디 아래에 있는지 확인할 수 없게 되는데, 그 크기의 상당 부분이
        곳 노드의 `device_id: null` 과 `properties` 껍데기였다."""
        def compact(node):
            out = {}
            for k, v in node.items():
                if k == 'children' or v is None:
                    continue
                if k == 'properties' and isinstance(v, dict):
                    for pk, pv in v.items():
                        if pv is None:
                            continue
                        if pk == 'area':
                            try:
                                out['area_m2'] = int(round(float(pv)))
                            except (TypeError, ValueError):
                                pass
                        else:
                            out.setdefault(pk, pv)
                    continue
                out[k] = v
            # 같은 것을 가리키는 ID 를 둘 싣지 않는다(2026-10-09 실측: depth=0 이
            # 17,516토큰으로 상한 15,000 을 넘어, 캡이 모든 항목의 children 을
            # 떼어 계층이 통째로 사라졌다). 장치 노드는 지도 마커 번호 대신
            # 실제 장치 ID 를 unique_id 로 싣고, 곳 노드의 device_id(장치가
            # 아니라 도형 내부 번호)는 뺀다 — 둘이 합쳐 약 4,800토큰이었다.
            dev_id = out.pop('device_id', None)
            if node.get('type') in cls._TREE_DEVICE_TYPES and dev_id:
                out['unique_id'] = dev_id
            kids = node.get('children') or []
            if kids:
                out['children'] = [compact(c) for c in kids]
            return out
        return [compact(n) for n in nodes]

    _DEVICE_NODE_ID_READING = (
        "On device nodes ('aot_device'/'device'), 'unique_id' is the DEVICE's "
        "id — pass it to get_device_detail and other device tools. ")

    _REPEATED_NAME_READING = (
        "A place whose name is also used on another map carries 'use_name' "
        "(e.g. '김제 1포장') — pass that as target_name; the bare name would "
        "be refused as ambiguous. If it has 'map' instead, no name points at "
        "only that one, so use its unique_id. A facility also carries "
        "'facility_id' (the id get_control_state/get_crop_status show); "
        "facility tools accept either.")

    @classmethod
    def _qualify_repeated_names(cls, nodes):
        """이름이 다른 지도에도 있는 곳에만 지도 이름을 붙인다(2026-10-09).

        '1포장' 이 김제와 그린하트바이오 두 지도에 있는데 트리에는 맨 이름만
        나가, 모델이 둘을 같은 곳으로 읽거나 그 이름으로 쓰기 도구를 불러
        모호함 거절을 받았다. 장소 경로와 같은 규칙이다 — 겹칠 때만 붙이고,
        겹치지 않는 곳은 그대로 둔다(전부 붙이면 트리가 그만큼 커진다).

        `use_name` 은 리졸버로 되짚어 그 곳 하나를 가리키는 것만 싣는다. 그런
        이름이 없으면 `map` 으로 지도 이름만 적는다."""
        places = []

        def walk(ns):
            for n in ns or []:
                if n.get('type') in cls._TREE_DEVICE_TYPES:
                    continue
                if n.get('name') and n.get('unique_id'):
                    places.append(n)
                walk(n.get('children'))
        walk(nodes)
        if not places:
            return nodes
        try:
            from aot.databases.models import GeoMap, GeoFacility
            pmap, by_id = cls._shape_parent_lookup()
            recs = {r.unique_id: r for r in by_id.values()}
            map_names = {m.unique_id: (m.name or '').strip() for m in GeoMap.query.all()}
            maps_lower = cls._map_names_by_lower()
            fac_geo = {f.unique_id: f.geo_id for f in GeoFacility.query.with_entities(
                GeoFacility.unique_id, GeoFacility.geo_id).all()}
        except Exception as e:                              # noqa: BLE001
            logger.debug("_qualify_repeated_names: %s", e)
            return nodes

        def geo_of(n):
            rec = recs.get(n['unique_id'])
            return rec.geo_id if rec is not None else fac_geo.get(n['unique_id'])

        maps_by_name = {}
        for n in places:
            g = geo_of(n)
            if g:
                maps_by_name.setdefault(n['name'].strip().lower(), set()).add(g)
        for n in places:
            g = geo_of(n)
            if not g or len(maps_by_name.get(n['name'].strip().lower(), ())) < 2:
                continue
            un = None
            rec = recs.get(n['unique_id'])
            try:
                if rec is not None:
                    un = cls._qualified_name(rec, n['name'], n['unique_id'], pmap,
                                             by_id, maps_lower, map_names)
                elif map_names.get(g):
                    q = '%s %s' % (map_names[g], n['name'])
                    if cls._resolve_note_target(q)[0] == n['unique_id']:
                        un = q
            except Exception:
                un = None
            if un:
                cls._put_after_name(n, 'use_name', un)
            elif map_names.get(g):
                cls._put_after_name(n, 'map', map_names[g])
        return nodes

    @staticmethod
    def _put_after_name(node, key, value):
        """`key` 를 이름 바로 뒤에 넣는다. 끝에 붙이면 긴 children 뒤로 밀려
        읽는 쪽이 놓친다(2026-10-09 외부 점검: 하위 구역 다섯 개 뒤에 붙은
        '김제 1포장' 을 "없다" 고 보고했다)."""
        items = [(k, v) for k, v in node.items() if k != key]
        node.clear()
        for k, v in items:
            node[k] = v
            if k == 'name':
                node[key] = value
        if key not in node:
            node[key] = value

    @staticmethod
    def _attach_facility_ids(nodes):
        """시설 노드에 시설 행 ID(`facility_id`)를 함께 싣는다.

        트리의 시설 노드 unique_id 는 시설 **도형**의 ID 인데, 제어 상태·작물
        현황·이상 점검은 시설 **행**의 ID 를 쓴다. 트리에서 본 ID 하나로는 다른
        도구와 대조할 수 없었다(2026-10-09 외부 점검). 도구들은 이제 어느 쪽이든
        받지만, 트리가 둘 다 보여 줘야 같은 시설이라는 것이 응답에서 보인다.
        """
        try:
            from aot.databases.models import GeoFacility
            by_shape = {f.shape_uuid: f.unique_id for f in GeoFacility.query.with_entities(
                GeoFacility.unique_id, GeoFacility.shape_uuid).all() if f.shape_uuid}
        except Exception:                                   # noqa: BLE001
            return nodes

        def walk(ns):
            for n in ns or []:
                if n.get('type') == 'facility':
                    fid = by_shape.get(n.get('unique_id'))
                    if fid and fid != n.get('unique_id'):
                        n['facility_id'] = fid
                walk(n.get('children'))
        walk(nodes)
        return nodes

    @staticmethod
    def _keep_tree_structure(out):
        """응답 상한에 걸려도 children 을 떼지 말라고 캡에 알린다.

        캡은 가장 무거운 열부터 모든 항목에서 뺀다. 트리에서 그것은 children
        이고, 빠지면 장소 58개가 평평한 목록으로만 남았다(2026-10-09 실측).
        지켜 두면 캡이 뒤쪽 루트부터 잘라 앞쪽은 계층이 그대로 남는다.
        """
        from aot.tools.tool_execution import CAP_PRIORITY_KEY
        out[CAP_PRIORITY_KEY] = {
            'keep_last': [['*', 'children']],
            'narrow_with': ("Call get_spatial_tree without depth (places only), "
                            "or resolve_target / search_devices for one place."),
        }

    # ── 장소 현황 한 번에 (가벼움 묶음의 첫 도구, 2026-10-10) ───────────────────
    # "3포장 어때?" 에 답하려면 resolve_target → get_zone_sensor_summary →
    # get_control_state → list_plots → get_anomalies 로 4~6번을 불렀다. 무료 요금제
    # 에서는 부를 때마다 도구 목록 전체가 다시 실려 그 왕복이 곧 사용 한도다. 그래서
    # 기존 도구를 **서버에서** 불러 짧게 줄여 한 번에 낸다 — 판정 규칙은 새로
    # 만들지 않는다(소속·신선도·시각 변환은 각 도구가 이미 한다).
    _OVERVIEW_STALE_S = 2 * 3600
    _OVERVIEW_MAX_SITES = 10
    _OVERVIEW_MAX_PLOTS = 10
    _OVERVIEW_MAX_NAMED = 40       # 그 너머는 이름만(행 대신)
    _OVERVIEW_BRIEF_MEAS = ('temperature', 'humidity', 'volumetric_water_content',
                            'co2', 'electrical_conductivity')

    @classmethod
    @tz_scoped
    def get_place_overview(cls, place=None, **extra):
        """[읽기전용] 장소 하나(또는 농장 전체)의 현황 요약 — 센서·제어·구획·날씨·알림."""
        place = place or extra.get('target_name') or extra.get('zone_id') \
            or extra.get('name')
        try:
            if not place:
                return cls._farm_overview()
            shape, err = cls._overview_place(place)
            if err:
                return err
            out = {"status": "success"}
            out.update(cls._place_overview(shape, brief=False))
            cls._with_target(out, shape.type, shape.unique_id, ref=place)
            geo = cls._place_geo(shape.type, shape.unique_id)
            if geo:
                out["place"].update(geo)
            else:
                out["place"]["geo"] = "no drawn shape on the map"
            out["_more"] = (
                "Detail: get_zone_sensor_summary (each sensor), "
                "get_plot (one plot's schedule and targets), get_control_state "
                "(control detail), get_device_freshness (silent sensors).")
            return out
        except Exception as e:                              # noqa: BLE001
            logger.exception("Error in get_place_overview")
            return {"error": str(e)}

    @classmethod
    def _overview_place(cls, place):
        """이름·id → 장소 도형. 시설 이름이면 그 시설의 도형."""
        shape, err = cls._read_place(place, arg='place')
        if shape is not None:
            return shape, None
        fac = cls._resolve_facility(place)
        if fac is not None and fac.shape_uuid:
            row = GeoShape.query.filter(GeoShape.unique_id == fac.shape_uuid).first()
            if row is not None:
                return row, None
        return None, err

    @classmethod
    def _farm_overview(cls):
        sites = (GeoShape.query.filter(GeoShape.type == 'site')
                 .order_by(GeoShape.id).all())
        total = len(sites)
        if total > cls._OVERVIEW_MAX_SITES:
            sites = cls._sites_by_content(sites)
        # 제어 상태는 농장 전체를 한 번에 계산하는 읽기라 대지마다 다시 부르면 같은 계산을 대지 수만큼
        # 한다(2026-11-07 실측: 10곳 × 0.4~1.0초). 한 번 읽어 모든 대지가 나눠 쓴다.
        control = cls._overview_coordinators()
        rows = [cls._place_overview(s, brief=True, coordinators=control)
                for s in sites[:cls._OVERVIEW_MAX_SITES]]
        out = {"status": "success", "scope": "farm", "sites": rows,
               "sites_total": total}
        if rows and rows[0].get("weather") is None:
            w = cls._overview_weather(sites[0])
            if w:
                out["weather"] = w
        if total > cls._OVERVIEW_MAX_SITES:
            out["note"] = ("Showing %d of %d sites — call with place for one."
                           % (cls._OVERVIEW_MAX_SITES, total))
        out["_more"] = "Call get_place_overview(place) for one site or zone in detail."
        return out

    @classmethod
    def _sites_by_content(cls, sites):
        """장치가 많은 대지부터 — 10개만 보일 때 빈 대지가 자리를 차지하지 않게.

        만든 순서로 자르면 장치·구획이 있는 대지가 빠진다(2026-10-10 파일럿:
        대지 34개 중 앞의 10개에 '3포장' 이 없어 "농장 상태" 답에서 사라졌다).
        보통 설치(대지 1~5개)는 상한 아래라 이 계산을 하지 않는다. 같으면 만든
        순서를 지킨다(정렬은 안정적이다)."""
        from aot.space.device_membership import place_members

        def weight(shape):
            try:
                devs = place_members(shape.unique_id, include_references=False)
            except Exception:                               # noqa: BLE001
                devs = None
            return len(devs or ())
        return sorted(sites, key=weight, reverse=True)

    @classmethod
    def _place_overview(cls, shape, brief, coordinators=None):
        from aot.space.device_membership import PlaceIndex, place_label
        idx = PlaceIndex()
        out = {"place": {"name": place_label(shape), "kind": shape.type,
                         "path": idx.path(shape)}}
        if brief:                       # 목록은 center 만 — 응답이 커지지 않게
            out["place"].update(cls._place_geo(shape.type, shape.unique_id, full=False))
        sensors, stale = cls._overview_sensors(shape, brief)
        if sensors:
            out["sensors"] = sensors
        if stale:
            out["stale_sensors"] = stale
        ctl = cls._overview_control(shape, idx, brief, coordinators)
        if ctl:
            out["control"] = ctl
        plots = cls._overview_plots(shape, brief)
        if plots:
            out["plots"] = plots
        if not brief:
            w = cls._overview_weather(shape)
            if w:
                out["weather"] = w
        alert = cls._overview_alert(shape)
        if alert:
            out["alert"] = alert
        return out

    @classmethod
    def _overview_sensors(cls, shape, brief):
        """측정 종류별 현재값(최소·평균·최대) — 예보 모델값은 섞지 않는다."""
        from datetime import datetime, timezone
        try:
            # 개요는 센서별 최소·최대가 필요해 detail=True 로 부른다(기본 응답은
            # 그룹 평균뿐). 위치 유형·매질·제외 사유는 요약의 판정을 그대로 따른다.
            z = cls.get_zone_sensor_summary(zone_ids=[shape.unique_id],
                                            time_range='6h', detail=True)
        except Exception:                                   # noqa: BLE001
            logger.debug('overview: sensor summary failed', exc_info=True)
            return {}, None
        agg, stale, outdoor_agg, soil_agg = {}, [], {}, {}
        now = utc_now()
        for zone in (z or {}).get('zones') or []:
            # 구역 요약이 정본 신선도(주기×배수·max_age_s)로 거른 센서 — 같은
            # 기준을 쓰도록 여기서도 뺀다(2시간 상수는 정보 없을 때의 상한).
            _stale_ids = {e.get('device_id') for e in zone.get('stale_excluded') or []}
            for dev in zone.get('sensors') or []:
                # 예보 모델값·출력 장치(밸브 개도·듀티비)는 현장 측정이 아니다.
                if dev.get('data_origin') == 'model' or \
                        dev.get('device_kind') == 'output':
                    continue
                # 위치를 모르는 센서(참조로만 들어온 것)는 시설·노지 평균에 섞지
                # 않는다(센서 위치 유형 PR2).
                if dev.get('placement') == 'unplaced':
                    continue
                # 수리 중·철거됨·점검 중(Input.device_status)은 값이 신뢰 불가.
                if dev.get('device_status'):
                    continue
                t = dev.get('last_time')
                try:
                    age = (now - datetime.fromisoformat(t)).total_seconds() if t else None
                except ValueError:
                    age = None
                if (age is not None and age > cls._OVERVIEW_STALE_S) or \
                        dev.get('device_id') in _stale_ids:
                    stale.append(dev.get('device_name'))
                    continue
                # 실외(기상대)는 시설·구역 평균에 섞지 않고 따로 낸다(F1).
                _is_out = (dev.get('location') == 'outdoor'
                           or dev.get('placement') == 'outdoor')
                for ch in dev.get('channels') or []:
                    v = ch.get('last_value')
                    m = ch.get('measurement')
                    # 방위(풍향)는 평균을 내면 뜻이 없다(350° 와 10° 의 평균은 180°).
                    if v is None or not m or ch.get('unit') == 'bearing':
                        continue
                    # 토양 채널은 같은 이름(temperature)의 공기 값에 섞지 않는다.
                    if ch.get('medium') == 'soil' and not _is_out:
                        _tgt = soil_agg
                    else:
                        _tgt = outdoor_agg if _is_out else agg
                    a = _tgt.setdefault(
                        m, {"unit": ch.get('unit'), "values": [], "latest": None,
                            "sim": 0})
                    a["values"].append(v)
                    if dev.get('simulated'):
                        a["sim"] += 1       # 표시만 — 평균에서 빼지 않는다
                    if t and (a["latest"] is None or t > a["latest"]):
                        a["latest"] = t
        out = {}
        order = sorted(agg, key=lambda m: (m not in cls._OVERVIEW_BRIEF_MEAS,
                                           cls._OVERVIEW_BRIEF_MEAS.index(m)
                                           if m in cls._OVERVIEW_BRIEF_MEAS else 99, m))
        if brief:   # 농장 전체에서는 대표 측정만
            order = [m for m in order if m in cls._OVERVIEW_BRIEF_MEAS]
        for m in order[:(3 if brief else 8)]:
            vals = agg[m]["values"]
            row = {"avg": round(sum(vals) / len(vals), 1), "unit": agg[m]["unit"],
                   "n": len(vals)}
            if agg[m].get("sim"):
                row["sim_n"] = agg[m]["sim"]
            if len(vals) > 1:
                row["min"], row["max"] = round(min(vals), 1), round(max(vals), 1)
            if not brief:
                row["latest"] = agg[m]["latest"]
            out[m] = row
        # 실외는 대표 측정만 평균 하나로 — 실내 평균과 구분되는 별도 키.
        o_out = {}
        for m in cls._OVERVIEW_BRIEF_MEAS:
            vals = (outdoor_agg.get(m) or {}).get("values")
            if vals:
                o_out[m] = {"avg": round(sum(vals) / len(vals), 1),
                            "unit": outdoor_agg[m]["unit"], "n": len(vals)}
                if outdoor_agg[m].get("sim"):
                    o_out[m]["sim_n"] = outdoor_agg[m]["sim"]
        if o_out:
            out["outdoor"] = o_out
        s_out = {}
        for m in sorted(soil_agg)[:3]:
            vals = soil_agg[m]["values"]
            s_out[m] = {"avg": round(sum(vals) / len(vals), 1),
                        "unit": soil_agg[m]["unit"], "n": len(vals)}
            if soil_agg[m].get("sim"):
                s_out[m]["sim_n"] = soil_agg[m]["sim"]
        if s_out:
            out["soil"] = s_out
        stale_out = None
        if stale:
            stale_out = {"count": len(stale), "names": stale[:3]}
        return out, stale_out

    @classmethod
    def _overview_coordinators(cls):
        """제어 상태의 코디네이터 목록. 못 읽으면 None (개요는 그 칸만 빠진다)."""
        try:
            return cls.get_control_state().get('coordinators') or []
        except Exception:                                   # noqa: BLE001
            return None

    @classmethod
    def _overview_control(cls, shape, idx, brief, coordinators=None):
        """이 장소 안 시설의 환경 제어 — 모드·제한 요인·구동기 개도와 근거 이름.

        `coordinators` 는 호출부가 이미 읽어 둔 목록(농장 개요가 대지 사이에 나눠 쓴다).
        안 주면(None) 직접 읽는다."""
        cs = coordinators if coordinators is not None else cls._overview_coordinators()
        if cs is None:
            return None
        rows = []
        for c in cs:
            fp = c.get('facility_place_id')
            if not fp or not (fp == shape.unique_id or idx.within(fp, shape.unique_id)):
                continue
            s = c.get('latest_cycle_summary') or {}
            row = {"facility": c.get('facility_name'), "modes": s.get('modes'),
                   "limiting": s.get('limiting_factor')}
            if s.get('degraded_reasons'):
                row["degraded_reasons"] = s.get('degraded_reasons')
            if not brief:
                row["actuators"] = [
                    {"kind": x.get('kind'), "pct": x.get('pct'),
                     "why": x.get('reason_name')}
                    for x in (s.get('commands') or [])][:8]
                if s.get('deviation'):
                    row["deviation"] = s.get('deviation')
            rows.append(row)
        return rows or None

    @classmethod
    def _overview_plots(cls, shape, brief):
        try:
            p = cls.list_plots(zone_id=shape.unique_id, limit=cls._OVERVIEW_MAX_NAMED)
        except Exception:                                   # noqa: BLE001
            return None
        items = (p or {}).get('plots') or []
        total = (p or {}).get('total_matched') or (p or {}).get('count') or len(items)
        if not items:
            return None
        if brief:
            return {"count": total}
        rows = []
        # 행은 앞의 몇 개만, 나머지는 이름·자리만 — 잘린 목록이 무엇을 뺐는지 말하지 않으면
        # 모델은 "나머지는 원하면" 으로 멈춘다(2026-10-14 웹 시험: 3포장 13개 중 10개만 답).
        rest = items[cls._OVERVIEW_MAX_PLOTS:]
        items = items[:cls._OVERVIEW_MAX_PLOTS]
        for it in items:
            st = it.get('stage') or {}
            row = {"subject": it.get('subject')}
            if it.get('zone_name'):
                row["where"] = it.get('zone_name')
            if st.get('name'):
                row["stage"] = st.get('name')
                if st.get('days_left') is not None:
                    row["days_left"] = st.get('days_left')
            rows.append(row)
        out = {"count": total, "items": rows}
        if rest:
            out["others"] = ["%s (%s)" % (it.get('subject'), it.get('zone_name'))
                             if it.get('zone_name') else str(it.get('subject'))
                             for it in rest]
        if total > len(rows) + len(rest):
            out["not_listed"] = total - len(rows) - len(rest)
        return out

    @classmethod
    def _overview_weather(cls, shape):
        try:
            w = cls.get_weather_tool(zone_id=shape.unique_id)
        except Exception:                                   # noqa: BLE001
            return None
        pick = (w or {}).get('weather_pick') or {}
        data = (w or {}).get('data') or []
        if pick.get('skipped') and (w or {}).get('weather_source') != 'weather_station':
            # 쓸 수 있는 기상 장치가 하나도 남지 않았다(꺼짐·상태·오래됨으로 모두 제외).
            # 일반 센서값을 날씨로 내지 않고 이유만 낸다.
            none = {"source_none": "no_active_fresh_weather_device",
                    "skipped": pick['skipped']}
            if pick.get('skipped_more'):
                none["skipped_more"] = pick['skipped_more']
            return none
        if not data:
            return None
        src = data[0].get('device_name')
        out = {"source": cls._overview_weather_source(shape, w, src)}
        for k in ('picked_because', 'skipped', 'skipped_more'):
            if pick.get(k):
                out["source"][k] = pick[k]
        if (w or {}).get('control_outdoor'):
            out["source"]["control_outdoor"] = w['control_outdoor']
        for d in data:
            if d.get('device_name') != src:
                continue
            r = (d.get('readings') or [])[-1:] or []
            if r:
                out[d.get('measurement')] = r[0].get('v')
                out.setdefault("at", r[0].get('t'))
        return out if len(out) > 1 else None

    @classmethod
    def _overview_weather_source(cls, shape, w, name):
        """날씨 요약의 출처 표기 — get_weather 가 이미 낸 필드를 그대로 쓴다.

        {kind, name, scope, data_origin, placement_source?, lat/lng/distance_km
        또는 coords:'unknown'}. 선택 규칙은 바꾸지 않고 보이기만 한다."""
        wd = (w or {}).get('weather_device') or {}
        model = wd.get('data_origin') == 'model'
        src = {"kind": "model" if model else "device",
               "name": name,
               "scope": (w or {}).get('weather_device_scope') or 'unplaced',
               "data_origin": "model" if model else "observed"}
        from aot.tools.sim_marker import sim_fields
        src.update(sim_fields('input', wd.get('driver'), wd.get('name') or name))
        try:
            from aot.utils.device_tz import resolve_location_coords
            from aot.utils.geo_distance import distance_m
            lat = lng = None
            if wd.get('device_id'):
                lat, lng = resolve_location_coords(wd['device_id'])
            if lat is None or lng is None:
                src["coords"] = "unknown"
            else:
                src["lat"], src["lng"] = round(lat, 4), round(lng, 4)
                here = resolve_location_coords(shape.unique_id)
                if here and here[0] is not None:
                    src["distance_km"] = round(
                        distance_m(here[0], here[1], lat, lng) / 1000.0, 1)
            if src["scope"] == 'site':
                from aot.space import device_membership as dm
                site = shape if getattr(shape, 'type', None) == 'site' else None
                if site is None:
                    feat = shape.feature if isinstance(shape.feature, dict) else {}
                    site = dm.site_for_geometry(shape.geo_id, (feat or {}).get('geometry'))
                if site is not None:
                    kind = dm.weather_device_ids(site.unique_id)[1]
                    src["placement_source"] = ('weather_bound' if kind == 'bound'
                                               else kind)
        except Exception:                                   # noqa: BLE001
            src.setdefault("coords", "unknown")
        return src

    @classmethod
    def _overview_alert(cls, shape):
        st = 'site' if shape.type == 'site' else 'zone'
        if shape.type not in ('site', 'zone'):
            return None
        try:
            a = cls.get_anomalies(scope_type=st, scope_id=shape.unique_id)
        except Exception:                                   # noqa: BLE001
            return None
        # alert_level 표시는 불변. 침묵 판정(silent_level)은 warning 일 때만 덧붙인다.
        silent_warn = (a or {}).get('silent_level') == 'warning'
        if (a or {}).get('alert_level') in (None, 'none') and not silent_warn:
            return None
        out = {}
        if (a or {}).get('alert_level') not in (None, 'none'):
            out = {"level": a.get('alert_level'),
                   "anomalies": [x.get('type') or x
                                 for x in a.get('anomalies') or []][:5]}
        if silent_warn:
            sd = a.get('silent_devices') or {}
            out["silent_level"] = 'warning'
            out["silent"] = {k: sd[k] for k in
                             ('recent_count', 'active_total', 'ratio')
                             if k in sd}
        return out

    @classmethod
    def get_spatial_tree(cls, depth=None, filter_type=None, map=None,
                         brief=False, place_id=None, detail=False, **extra):
        """[읽기전용] 공간 계층(대지 > 구역 > 장치) 트리.

        `brief`·`place_id`·`detail` 은 도구 스키마에 없는 처리기 인자다 — 도메인 표면(find.tree)만 쓴다(2026-10-31).
        - `brief`: 지도·곳·깊이·종류를 하나도 안 정했으면 지도별 맨 위 곳의 이름과 개수만(`_tree_brief`).
          지도(`map`)나 곳(`place_id`)을 주면 그 트리를 예전 모양 그대로 낸다. `detail` 이면 brief 를 끄고 예전 기본 모양.
        - `place_id`: 그 곳(대지·구역·시설, 시설 행 id 도 됨) 아래의 트리만.
        안 주면(인앱 AI·화면·개요) 예전과 같다.

        **기본(depth 없음)은 곳만 전부다** — 대지·구역·시설을 모든 깊이에서
        싣고, 장치는 곳마다 `devices` 개수로 접는다(2026-09-24).

        예전 기본은 depth=2 였다. 대지 안에 구역이 두 겹(3포장 > 1구역 > 3-1)
        이면 3-1 이 `children_omitted` 의 숫자로만 남아, 모델이 "3-1 구역은
        없다" 고 답했다(재측정 lat_21). 게다가 깊이 2 까지의 장치 노드와 속성
        때문에 응답이 오히려 컸다 — 벤치 DB 실측: depth 2 약 14.3k 추정 토큰,
        곳만 약 6.3k. 곳을 다 싣는 쪽이 작고 빠짐이 없다.

        `depth` 를 주면 예전처럼 **최대 깊이**(루트가 1)로 자르고 장치도
        싣는다 — 장치까지 펴려면 3 이상, 전부 보려면 0.

        기본값을 얕게 두는 이유. 이 트리는 농장이 커질수록 장치 노드가
        대부분을 차지한다(실측 2026-08-26: 노드 154개 중 68개가 장치, 전체
        13,978 토큰 중 6,859). 그런데 장치를 이름·종류로 찾는 일은
        `get_device_list`/`search_devices` 가 더 잘한다 — 이 도구가 답하는
        질문은 "이 농장이 어떻게 나뉘어 있나" 다. 깊이를 다 펴서 응답 상한을
        넘기면 캡이 트리를 잘라 **루트 47개 중 2개**만 나가고, 그러면 구조
        자체를 못 본다.

        `filter_type` 을 주면 깊이로 자르지 않는다. 특정 종류를 찾아 달라는
        요청인데 깊이에서 먼저 끊으면 찾을 것이 사라진다.
        """
        try:
            full_tree = providers.get('spatial_hierarchy')()
            # `map` 을 주면 그 지도의 곳만 — 지도가 여럿이면 "지도 1 의 대지" 를
            # 답할 수 없었다(2026-10-11). 지도 이름은 다른 지도에도 있는 이름에만
            # 붙인다는 규칙(_qualify_repeated_names)은 그대로다 — 지도마다의
            # 대지 목록은 list_geo_maps 가 낸다.
            full_tree, map_error = cls._filter_map(full_tree, map)
            if map_error:
                return map_error
            late_pick = None
            if place_id:
                sub = cls._find_place_node(full_tree, place_id)
                if sub is None:
                    return {"status": "not_found",
                            "message": "No place with that id in the spatial tree."}
                if (depth is None or depth == '') and not filter_type:
                    # 기본 보기는 전체 트리를 다 다듬은 뒤 그 곳만 고른다 — 다른 지도에도 있는 이름의 `use_name`
                    # 이 그 곳만 남기면 사라진다.
                    late_pick = sub.get('unique_id')
                else:
                    full_tree = [sub]
            if (brief and not detail and not map and not place_id and not filter_type
                    and depth in (None, '')):
                return cls._tree_brief(cls._merge_device_nodes(full_tree))
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

            full_tree = cls._merge_device_nodes(full_tree)

            if not ((depth is None or depth == '') and not filter_type):
                full_tree = cls._compact_nodes(full_tree)
            out = {"hierarchy": full_tree}
            if (depth is None or depth == '') and not filter_type:
                roots, loose = cls._place_roots(cls._fold_devices(full_tree))
                out["hierarchy"] = cls._attach_facility_ids(cls._qualify_repeated_names(roots))
                if loose:
                    out["devices_outside_any_place"] = loose
                out["_reading"] = (
                    "Places only: every site, zone and facility at every level. "
                    "'devices' is how many devices sit directly in that place — "
                    "call again with depth (0 = everything) to list them, or "
                    "use search_devices / get_device_list by name. "
                    + cls._REPEATED_NAME_READING)
                if late_pick:
                    out["hierarchy"] = [cls._find_place_node(out["hierarchy"], late_pick)]
                cls._keep_tree_structure(out)
                cls._add_map_hint(out, map or place_id)
                return out
            try:
                lvl = int(depth)
            except (TypeError, ValueError):
                lvl = 2
            # 0(과 음수)은 "제한 없음". `if depth:` 로 쓰면 0 이 falsy 라
            # 기본값으로 되살아나 끄는 수단이 조용히 사라진다.
            if lvl > 0 and not filter_type:
                full_tree = cls._prune_depth(full_tree, lvl)
                out["hierarchy"] = full_tree
                if any('children_omitted' in n or
                       any('children_omitted' in c
                           for c in (n.get('children') or []))
                       for n in full_tree):
                    out["depth"] = lvl
                    out["_reading"] = (
                        "This tree is cut at depth %d. A node's "
                        "'children_omitted' counts what sits below it by type — "
                        "those entries exist, they are just not expanded here. "
                        "Call get_spatial_tree with a larger depth (0 = no "
                        "limit) for the rest, or get_device_list / "
                        "search_devices to find devices by name." % lvl)
            out["hierarchy"] = cls._attach_facility_ids(
                cls._qualify_repeated_names(out["hierarchy"]))
            cls._keep_tree_structure(out)
            out["_reading"] = (cls._DEVICE_NODE_ID_READING
                               + cls._REPEATED_NAME_READING
                               + (" " + out["_reading"] if out.get("_reading") else ""))
            cls._add_map_hint(out, map or place_id)
            return out
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _find_place_node(nodes, place_id):
        """트리에서 곳 하나의 노드 — 도형 id 로, 시설이면 시설 행 id 로도. 없으면 None."""
        want = str(place_id)
        try:
            from aot.databases.models import GeoFacility
            fac = GeoFacility.query.filter_by(unique_id=want).first()
            if fac is not None and getattr(fac, 'shape_uuid', None):
                want = fac.shape_uuid
        except Exception:                                   # noqa: BLE001
            pass

        def walk(ns):
            for n in ns or []:
                if not isinstance(n, dict):
                    continue
                if n.get('unique_id') == want and n.get('type') not in MARKER_TYPES:
                    return n
                hit = walk(n.get('children'))
                if hit is not None:
                    return hit
            return None
        return walk(nodes)

    @classmethod
    def _place_roots(cls, nodes):
        """'곳만' 보기의 맨 위 — 곳(대지·구역·시설)만 남기고, 어느 곳에도 안 든 장치는 개수로 돌린다.

        곳 밖에 그린 지도 도형(참조선·이름 없는 설비 묶음 …)과 곳 밖 장치가 맨 위 줄로 끼어, 한 지도에
        "Reference Line" 네 줄, 지도마다 "Equipment_collection 123" 이 나왔다 — 구분도 안 되고 쓸모도 없고,
        "Places only" 라는 이 보기의 말과도 어긋났다(2026-11-09 claude.ai 점검 7번·재점검). 요약과 상세가 같은
        규칙을 쓴다(요약의 other_top_level 이 상세의 맨 위와 맞게)."""
        from aot.space.device_membership import PLACE_TYPES
        kept, loose = [], 0
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if n.get('type') in cls._TREE_DEVICE_TYPES:
                loose += 1
            elif n.get('type') in PLACE_TYPES:
                kept.append(n)
        return kept, loose

    @classmethod
    def _tree_brief(cls, merged):
        """find.tree 대상 없음 — 지도마다 맨 위 곳의 이름·종류·아래 곳 수·장치 수 한 줄. id·`use_name` 없음.

        47곳 전체를 id 와 함께 싣던 응답(7천 토큰)이 "지도 11개·대지 31곳" 을 보는 질문에는 과했다. 지도를 주면
        그 지도의 트리를, 곳을 주면 그 곳의 트리를 예전 모양 그대로 받는다(`next`). 같은 이름이 다른 지도에도
        있으면 지도 밑에 묶여 있어 헷갈리지 않는다(대상은 '지도 > 곳')."""
        folded = cls._fold_devices(merged)
        uids = [n.get('unique_id') for n in folded if isinstance(n, dict) and n.get('unique_id')]
        geo_of, map_names = {}, {}
        try:
            from aot.databases.models import GeoMap
            map_names = {m.unique_id: (m.name or '').strip() for m in GeoMap.query.all()}
            if uids:
                geo_of = {sh.unique_id: sh.geo_id for sh in GeoShape.query.filter(
                    GeoShape.unique_id.in_(uids)).all()}
        except Exception:                                   # noqa: BLE001
            pass

        def below(node):
            places = devices = 0
            for c in node.get('children') or []:
                p, d = below(c)
                places += 1 + p
                devices += d
            return places, devices + int(node.get('devices') or 0)

        groups, order = {}, []
        folded, loose = cls._place_roots(folded)
        for n in folded:
            name = map_names.get(geo_of.get(n.get('unique_id'))) or '(no map)'
            if name not in groups:
                groups[name] = []
                order.append(name)
            places, devices = below(n)
            groups[name].append([n.get('name'), n.get('type'), places, devices])
        out = {
            "status": "success",
            "next": {"call": "find(op='tree', target=<map> or '<map> > <place>')",
                     "why": "that map's or place's tree with ids; detail=true gives every map's tree at once"},
            "counts": {"maps": len(order),
                       "sites": sum(1 for v in groups.values() for r in v if r[1] == 'site'),
                       "other_top_level": sum(1 for v in groups.values() for r in v if r[1] != 'site')},
            "columns": ["place", "type", "places_below", "devices"],
            "maps": [{"map": m, "rows": groups[m]} for m in order],
        }
        if loose:
            out["counts"]["devices_outside_any_place"] = loose
        return out

    @staticmethod
    def _add_map_hint(out, map_ref):
        """지도가 둘 이상인데 map 을 안 줬으면, 다른 지도의 대지까지 섞여 나갔다는
        사실과 지도 목록을 싣는다(2026-10-11 리허설 C4: 지도 구분 없이 타 지도
        사이트가 전부 나왔다). 지도가 하나이거나 map 을 줬으면 아무것도 안 한다."""
        if map_ref:
            return
        try:
            from aot.databases.models import GeoMap
            names = sorted({m.name for m in GeoMap.query.all() if m.name})
        except Exception:
            return
        if len(names) < 2:
            return
        out["maps"] = names
        out["_map_hint"] = (
            "This tree mixes the places of %d maps (%s) because 'map' was not "
            "given. If the user means one map, call again for that map only — "
            "otherwise sites of other maps will be read as part of this one."
            % (len(names), ", ".join(names)))

    @staticmethod
    def _filter_map(tree, map_ref):
        """map_ref 가 있으면 그 지도의 맨 위 곳만 남긴다(이름 또는 id)."""
        if not map_ref:
            return tree, None
        from aot.databases.models import GeoMap
        maps = {m.unique_id: m.name for m in GeoMap.query.all()}
        uids = [n.get('unique_id') for n in tree if isinstance(n, dict)]
        geo_of = {}
        if uids:
            geo_of = {s.unique_id: s.geo_id for s in GeoShape.query.filter(
                GeoShape.unique_id.in_([u for u in uids if u])).all()}
        wanted = None
        if map_ref:
            ref = str(map_ref).strip()
            wanted = {mid for mid, name in maps.items()
                      if ref == mid or ref.lower() == (name or '').lower()}
            if not wanted:
                return tree, {"status": "error", "error": (
                    "No map '%s'. Maps: %s." % (ref, ", ".join(
                        sorted({n for n in maps.values() if n}))))}
        out = []
        for node in tree:
            if not isinstance(node, dict):
                continue
            mid = geo_of.get(node.get('unique_id'))
            if wanted is not None and mid not in wanted:
                continue
            out.append(node)
        return out, None

    @classmethod
    def get_facility_capacity_tool(cls, facility_name=None, **extra):
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
            from aot.space.facility_integration import get_facility_integration

            if not facility_name:
                facility_name = (extra.get('facility_id') or extra.get('name')
                                 or extra.get('target_name'))

            q = GeoFacility.query
            _tfac = None        # 이름·id 가 시설 하나로 정확히 풀렸을 때만(대상 id 를 싣는다)
            if facility_name and str(facility_name).strip():
                fname = str(facility_name).strip()
                # 시설 ID(시설 행·도형 어느 쪽이든)로 불러도 그 시설이다.
                _fr = cls._resolve_facility(fname)
                _tfac = _fr
                rows = ([_fr] if _fr is not None else
                        q.filter(GeoFacility.name.ilike(f"%{fname}%")).all())
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
            out = {"status": "success", "count": len(results), "results": results}
            if _tfac is not None:
                cls._with_target(out, 'facility', _tfac.shape_uuid,
                                 ref=facility_name, exact=True)
            return out
        except Exception as e:
            logger.error(f"Error in get_facility_capacity_tool: {e}")
            return {"error": str(e)}

    # 물 회로 부품(수원·탱크·펌프·필터·밸브·연결구)의 종류와 정격 키는 부품 표가 정본이다.
    # 배관 관경(diameter_mm)은 개별 항목이 아니라 배관 집계라 제외한다.
    _EQUIP_SPEC_FIELDS = ('flow_lph', 'pressure_kpa', 'capacity_kw', 'airflow_cmh',
                          'power_w', 'stroke_m', 'speed_m_per_min', 'coverage_pct', 'fuel'
                          ) + _water_parts.rating_keys(include_pipes=False)

    _EQUIP_DISCRETE_SUBTYPES = (
        'irrigation_valve', 'exhaust_fan', 'circulation_fan', 'heater', 'cooler',
        'heat_pump', 'side_window_motor', 'roof_vent_motor', 'thermal_curtain_motor',
        'shade_curtain_motor',
    ) + _water_parts.kinds()

    _EQUIP_MAIN_SUBTYPES = ('pipe_main', 'main')

    _EQUIP_BRANCH_SUBTYPES = ('pipe_branch', 'branch')

    @classmethod
    def _descendant_place_node_ids(cls, area_name):
        """이름이 area_name 인 장소들의 **하위 장소** node_id 집합.

        설비는 소유 링크(parent_node_id == 장소의 node_id)로 장소에 붙는다.
        그 링크는 가장 가까운 장소 하나만 가리키므로, 대지를 물으면 하위 구역이
        소유한 설비가 "다른 곳 소유" 로 빠졌다 — 밸브가 8개 있는 3포장이 장비
        0개로 나왔다(2026-10-08). 하위 판정은 정본(device_membership.PlaceIndex).
        """
        _aql = (area_name or '').strip().lower()
        if not _aql:
            return set()
        try:
            from aot.space.device_membership import PlaceIndex, place_label
            idx = PlaceIndex()
        except Exception:
            logger.debug('map equipment: 장소 색인 실패', exc_info=True)
            return set()
        roots = {s.unique_id for s in idx.shapes
                 if s.type in ('site', 'zone') and place_label(s).lower() == _aql}
        out = set()
        if not roots:
            return out
        kids = [s.unique_id for s in idx.shapes
                if s.type in ('site', 'zone') and s.unique_id not in roots
                and idx.chain_uids(s) & roots]
        if not kids:
            return out
        # 색인은 경량 레코드라 feature 가 없다 — node_id 는 그 도형들만 읽는다.
        from aot.databases.models import GeoShape as _GS
        for row in _GS.query.filter(_GS.unique_id.in_(kids)).all():
            feat = row.feature if isinstance(row.feature, dict) else {}
            nid = (feat.get('properties') or {}).get('node_id')
            if nid:
                out.add(nid)
        return out

    @classmethod
    def _extract_map_equipment(cls, shapes, area_name=None, extra_area_node_ids=None):
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

        S = cls
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
                        containers.append((nm, g, g.area, getattr(s, 'geo_id', None)))
                except Exception:
                    pass
        containers.sort(key=lambda c: c[2])  # smallest (most specific) first
        area_node_ids = set(name2nodes.get(_aql, set())) if _aql else set()
        if _aql and extra_area_node_ids:
            # 하위 장소가 소유한 설비도 이 장소의 것이다(_descendant_place_node_ids).
            area_node_ids |= set(extra_area_node_ids)
        area_polys = ([(g, gid) for (nm, g, _a, gid) in containers if nm.lower() == _aql]
                      if _aql else [])

        def _rep_point(geom):
            # 기준점은 정본(containment_point) — centroid 는 오목한 도형에서
            # 밖으로 나간다.
            from aot.utils.geo_hierarchy import containment_point
            g = _shape(geom)
            return g if g.geom_type == 'Point' else containment_point(g)

        def _spatial_area(geom, gid):
            # 고아 설비의 소속은 **같은 지도**의 장소 중 가장 작은 것(정본 동점
            # 규칙). 예전에는 지도를 가리지 않고 centroid 로 첫 컨테이너를 골라,
            # 겹쳐 그린 다른 지도의 구역 이름이 붙었다(2026-10-08).
            if not (_have_shapely and geom):
                return None
            try:
                from aot.utils.geo_hierarchy import pick_smallest_container
                pt = _rep_point(geom)
                if pt is None:
                    return None
                return pick_smallest_container(
                    pt, [(nm, poly, a) for nm, poly, a, cg in containers if cg == gid])
            except Exception:
                return None

        def _owner(props):
            # 설계 화면(aot-geo-stats.js)과 같은 규칙: 설비가 들어 있는 구역(zone_id)이
            # 알려진 장소면 그 구역이 소유자다. 대지가 소유자(parent_node_id)로 적힌
            # 노즐도 구역 안에 있으면 구역 행에 센다(대지 행에서 빠져 구역 합 = 대지 합).
            zid = props.get('zone_id')
            if zid and zid in node2name:
                return zid
            return props.get('parent_node_id') or zid

        def _locate(props, geom, gid=None):
            par = _owner(props)
            if par in node2name:
                return node2name[par]
            return _spatial_area(geom, gid)

        def _in_area(props, geom, gid=None):
            if not _aql:
                return True
            par = _owner(props)
            if par in area_node_ids:
                return True
            if par in node2name:  # owned by a DIFFERENT named area
                return False
            if area_polys and _have_shapely and geom:  # orphan → spatial fallback
                try:
                    pt = _rep_point(geom)
                    return pt is not None and any(
                        poly.contains(pt) for poly, pg in area_polys if pg == gid)
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
                    equip_features.extend((f, getattr(s, 'geo_id', None))
                                          for f in (coll.get('features') or []))
                except Exception:
                    continue
            elif s.type == 'equipment':
                try:
                    equip_features.append((s.feature if isinstance(s.feature, dict)
                                           else _json.loads(s.feature or '{}'),
                                           getattr(s, 'geo_id', None)))
                except Exception:
                    continue

        # 3) Classify.
        discrete = []
        agg = {}
        _slant_cache, _terrain = {}, None
        _dup = {}
        for f, _gid in equip_features:
            if isinstance(f, dict):
                _k = cls._pipe_ref_ids(f.get('properties') or {})
                if _k:
                    _d = _dup.setdefault(_gid, {})
                    _d[_k] = _d.get(_k, 0) + 1

        def _slot(loc):
            return agg.setdefault(loc, {
                # 스프링클러 (individual sprinkler_coverage features, each with flow)
                "sprinklers": 0, "sprinkler_flow_lph": 0.0,
                # 점적 (drip — derived from is_drip pipes: count = length / interval)
                "drip_emitters": 0, "drip_flow_lph": 0.0,
                "main_pipes": 0, "main_pipe_length_m": 0.0,
                "branch_pipes": 0, "branch_pipe_length_m": 0.0,
                "main_3d": None, "branch_3d": None, "slant_unknown": 0})

        for f, _gid in equip_features:
            if not isinstance(f, dict):
                continue
            props = f.get('properties') or {}
            geom = f.get('geometry')
            sub = props.get('sub_type') or props.get('equipment_type')
            if not sub or not _in_area(props, geom, _gid):
                continue
            # 스프링클러: sprinkler_coverage is the canonical saved sprinkler (the
            # bare 'sprinkler' point dots are ephemeral/filtered). Mirrors
            # aot-map-utils.js calculatePolygonStats isSprinkler.
            if (sub == 'sprinkler_coverage' or props.get('device_type') == 'sprinkler'
                    or props.get('aot_type') == 'sprinkler'):
                slot = _slot(_locate(props, geom, _gid) or '(unassigned)')
                slot['sprinklers'] += 1
                try:
                    slot['sprinkler_flow_lph'] += float(props.get('flow') or props.get('flow_rate') or 0)
                except (TypeError, ValueError):
                    pass
            elif sub in S._EQUIP_MAIN_SUBTYPES or sub in S._EQUIP_BRANCH_SUBTYPES:
                slot = _slot(_locate(props, geom, _gid) or '(unassigned)')
                length = _line_len_m(geom)
                if sub in S._EQUIP_MAIN_SUBTYPES:
                    slot['main_pipes'] += 1
                    slot['main_pipe_length_m'] += length
                else:
                    slot['branch_pipes'] += 1
                    slot['branch_pipe_length_m'] += length
                _ref = cls._slant_ref(_slant_cache, _gid)
                if _ref:
                    _terrain = _terrain or cls._terrain_mark(_ref)
                    _hit, _sl = cls._slant_of(_ref, props, _dup.get(_gid, {}))
                    if _hit and _sl is None:
                        slot['slant_unknown'] += 1
                    elif _hit:
                        _key = 'main_3d' if sub in S._EQUIP_MAIN_SUBTYPES else 'branch_3d'
                        slot[_key] = (slot[_key] or 0.0) + _sl
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
                    "location": _locate(props, geom, _gid),
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
                "length_basis": "horizontal",           # 지도 평면 길이(경사 길이 아님)
            })
            # 경사 길이는 있을 때만 — 기존 키는 그대로다.
            if s['main_3d'] is not None:
                irrigation[-1]["main_pipe_length_3d_m"] = _r1(s['main_3d'])
            if s['branch_3d'] is not None:
                irrigation[-1]["branch_pipe_length_3d_m"] = _r1(s['branch_3d'])
            if s['slant_unknown'] and (s['main_3d'] is not None or s['branch_3d'] is not None):
                irrigation[-1]["pipes_without_3d"] = s['slant_unknown']
        out = {"equipment": discrete, "irrigation": irrigation}
        if _terrain:
            out["terrain"] = _terrain
        return out

    @classmethod
    def get_map_equipment_tool(cls, area_name=None, brief=False, detail=False, **extra):
        """[분류 C - 지도 설비(equipment) 읽기 도구]

        `brief`·`detail` 은 도구 스키마에 없는 처리기 인자다 — 도메인 표면(find.map_equipment)만 쓴다(2026-10-31).
        `brief` 이고 `area_name`(대상)도 `detail` 도 없으면 구역마다 **한 줄**(`_equipment_lines`)만 낸다 — 27구역 관수 수치가
        3.9천 토큰이었다. 대상을 주면 예전 모양 그대로. 안 주면(인앱 AI) 예전과 같다.

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
            miss = cls._map_area_miss(shapes, area_name)
            if miss is not None:
                return miss
            res = cls._extract_map_equipment(
                shapes, area_name=area_name,
                extra_area_node_ids=cls._descendant_place_node_ids(area_name))
            n = len(res['equipment']) + sum(
                (i.get('sprinklers', 0) + i.get('drip_emitters', 0)
                 + i.get('main_pipes', 0) + i.get('branch_pipes', 0))
                for i in res['irrigation'])
            if brief and not detail and not area_name and n:
                return cls._equipment_lines(res, cls._area_sources(shapes))
            out = {
                "status": "success",
                "equipment_count": len(res['equipment']),
                "equipment": res['equipment'],
                "irrigation": res['irrigation'],
            }
            if res.get('terrain'):
                out["terrain"] = res['terrain']
            _tgt = cls._exact_area_target(area_name)
            if _tgt:
                cls._with_target(out, *_tgt, ref=area_name, exact=True)
                _path = cls._area_water_path(shapes, _tgt[1])
                if _path:
                    out["water_path"] = _path
            if n == 0:
                out["message"] = (f"No equipment drawn on the map"
                                  + (f" in '{area_name}'" if area_name else "") + ".")
            # 행은 **그 설비를 소유한 장소** 단위다 — 대지 행에는 대지에 직접
            # 그린 것만 있다. '3포장 행은 스프링클러 1개' 를 3포장 전체로 읽은
            # 일이 있어(2026-10-08 외부 MCP 점검), 물은 장소 전체의 합계를 따로
            # 싣는다. 두 관수 방식은 합계에서도 따로 센다(아래 규칙과 같다).
            rows = res['irrigation']
            if area_name and rows:
                def _sum(k):
                    vals = [r.get(k) for r in rows if r.get(k)]
                    return round(sum(vals), 1) if vals else None
                _tf = _sum('total_flow_lph')
                out["irrigation_total"] = {
                    "area": area_name,
                    "rows_summed": len(rows),
                    "sprinklers": sum(r.get('sprinklers') or 0 for r in rows),
                    "sprinkler_flow_lph": _sum('sprinkler_flow_lph'),
                    "drip_emitters": sum(r.get('drip_emitters') or 0 for r in rows),
                    "drip_flow_lph": _sum('drip_flow_lph'),
                    "total_flow_lph": _tf,
                    "total_flow_lpm": round(_tf / 60.0, 1) if _tf else None,
                    "main_pipes": sum(r.get('main_pipes') or 0 for r in rows),
                    "branch_pipes": sum(r.get('branch_pipes') or 0 for r in rows),
                }
                for _k3 in ('main_pipe_length_3d_m', 'branch_pipe_length_3d_m', 'pipes_without_3d'):
                    _v3 = [r[_k3] for r in rows if r.get(_k3) is not None]
                    if _v3:
                        out["irrigation_total"][_k3] = round(sum(_v3), 1)
                out.setdefault("_reading", []).append(
                    "Each 'irrigation' row is the equipment OWNED by that place — a "
                    "site's row holds only what is drawn directly on the site, not "
                    "its zones. For the whole of '%s' (its sub-zones included) use "
                    "'irrigation_total'." % area_name)
            # 두 관수 방식을 한 숫자로 합치지 말라는 규칙은 **둘 다 있을 때만**
            # 실수가 가능하다. 한쪽뿐이면 합칠 것이 없다.
            if any(i.get('sprinklers') for i in res['irrigation']) and \
                    any(i.get('drip_emitters') for i in res['irrigation']):
                out.setdefault("_reading", []).append(
                    "Both irrigation methods are present here. Keep 'sprinklers' "
                    "(spray heads, each with throw radius and flow) and "
                    "'drip_emitters' (derived from drip pipe length / spacing) "
                    "strictly apart — never add them into a single 'emitter' "
                    "figure. Report the two separately.")
            return out
        except Exception as e:
            logger.error(f"Error in get_map_equipment_tool: {e}")
            return {"error": str(e)}

    @staticmethod
    def _area_water_path(shapes, shape_uuid):
        """대상 구역의 상류 경로 요약. 회로 해석이 실패해도 설비 응답은 그대로 낸다."""
        try:
            from aot.utils import water_net_link
            row = next((s for s in shapes if s.unique_id == shape_uuid), None)
            return water_net_link.area_water_path(row.geo_id, shape_uuid) if row else None
        except Exception:                                   # noqa: BLE001
            logger.exception('map equipment: 물 회로 해석 실패')
            return None

    @staticmethod
    def _area_sources(shapes):
        """구역 이름 → 공급 원천 이름들. 회로 해석이 실패해도 목록은 그대로 낸다."""
        try:
            from aot.utils import water_net_link
            return water_net_link.area_sources(shapes)
        except Exception:                                   # noqa: BLE001
            logger.exception('map equipment: 공급 원천 해석 실패')
            return {}

    @staticmethod
    def _equipment_lines(res, sources=None):
        """find.map_equipment 대상 없음 — 구역마다 한 줄: 관수 방식·스프링클러·점적기·총 유량(L/h)·배관 수·그 구역의 개별
        설비(밸브·팬 …)를 종류별 개수로, 공급 원천(`water_source`, 펌프·수원 이름)은 있을 때만 한 칸. 숫자는 전체 응답의 구역 행 그대로다(반올림 없음). 구역 행은 **그 구역이 직접 가진**
        설비라 하위 구역은 따로 줄이다 — 하위까지 합친 값은 구역을 대상으로 부르면 `irrigation_total` 로 온다."""
        order, rows = [], {}

        def _row(area):
            if area not in rows:
                rows[area] = {"irr": None, "kinds": {}}
                order.append(area)
            return rows[area]
        for i in res['irrigation']:
            _row(i.get('area'))["irr"] = i
        for e in res['equipment']:
            kinds = _row(e.get('location'))["kinds"]
            kinds[e.get('sub_type')] = kinds.get(e.get('sub_type'), 0) + 1
        table = []
        for area in order:
            i, kinds = rows[area]["irr"] or {}, rows[area]["kinds"]
            table.append([area, i.get('method'), i.get('sprinklers'), i.get('drip_emitters'),
                          i.get('total_flow_lph'), i.get('main_pipes'), i.get('branch_pipes'),
                          ", ".join("%s x%d" % (k, v) for k, v in kinds.items()) or None])
        columns = ["area", "method", "sprinklers", "drip_emitters", "total_flow_lph",
                   "main_pipes", "branch_pipes", "other_equipment"]
        if any((sources or {}).values()):
            columns.append("water_source")
            for row in table:
                row.append((sources or {}).get(str(row[0] or '').strip()))
        return {
            "status": "success",
            "next": {"call": "find(op='map_equipment', target=<zone or site name>)",
                     "why": "that place's equipment with specs and its irrigation_total (sub-zones included); "
                            "detail=true gives every zone in full"},
            "equipment_count": len(res['equipment']),
            "columns": columns,
            "areas": table,
        }

    @classmethod
    def _exact_area_target(cls, area_name):
        """area_name 이 이름 그대로 가리키는 대지·구역이 **하나뿐**이면 (종류, id)."""
        aql = (area_name or '').strip().lower()
        if not aql:
            return None
        try:
            from aot.space.device_membership import PlaceIndex, place_label
            hits = [s for s in PlaceIndex().shapes
                    if s.type in ('site', 'zone') and place_label(s).lower() == aql]
        except Exception:                                   # noqa: BLE001
            logger.debug('map equipment: 대상 id 조회 실패', exc_info=True)
            return None
        return (hits[0].type, hits[0].unique_id) if len(hits) == 1 else None

    @classmethod
    def _map_area_miss(cls, shapes, area_name):
        """area_name 이 대지·구역이 아니면 그 사실을 말하는 응답, 맞으면 None.

        예전에는 시설 이름("육묘장3")을 주면 대지·구역 판정에서 아무것도 안
        걸려 "지도에 그린 설비 없음" 으로 답했다 — 같은 시설을
        get_facility_capacity 는 관수 56개로 답하는데(2026-10-10 외부 AI 5차
        점검). 둘은 저장소가 다르다: 이 도구는 지도에 그린 설비, 시설의 관수는
        시설 편집기의 설계(fittings)다. 틀린 이름도 "설비 없음" 으로 성공하면
        안 된다 — 없는 장소와 빈 장소를 구분해 답한다."""
        if not area_name:
            return None
        node_ids, polys = cls._area_node_ids_and_polys(shapes, area_name)
        if node_ids or polys or cls._descendant_place_node_ids(area_name):
            return None
        fac = cls._resolve_facility(area_name)
        if fac is not None:
            return cls._with_target({
                "status": "success", "equipment_count": 0, "equipment": [],
                "irrigation": [], "area_kind": "facility",
                "facility_name": fac.name, "facility_id": fac.unique_id,
                "message": (
                    "'%s' is a facility, not a site or zone. Its irrigation "
                    "(pipes, emitters, flow) and climate equipment are in the "
                    "facility design, not drawn on the map — call "
                    "get_facility_capacity(facility_name='%s') for them."
                    % (area_name, fac.name)),
            }, 'facility', fac.shape_uuid, ref=area_name, exact=True)
        return {"status": "error", "error": (
            "No site or zone named '%s' on any map — call resolve_target with "
            "the name to find the place, then pass its exact name." % area_name)}

    @classmethod
    def _area_node_ids_and_polys(cls, shapes, area_name):
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
    def _slant_ref(cache, gid):
        """지도 gid 의 경사 길이(`water_terrain.pipe_lengths_for`). 지형이 없거나 못 읽으면 None."""
        if gid in cache:
            return cache[gid]
        ref = None
        try:
            from aot.utils import water_terrain
            r = water_terrain.pipe_lengths_for(gid) if gid else None
            if r and r.get('state') not in (None, 'none'):
                ref = r
        except Exception:                                   # noqa: BLE001
            logger.exception('map equipment: 경사 길이 조회 실패')
        cache[gid] = ref
        return ref

    @staticmethod
    def _pipe_ref_ids(props):
        """물 회로 어댑터(`_feature_id`)가 배관 이름으로 쓰는 칸. 순번 이름은 여기서 알 수 없다."""
        v = props.get('node_id') or props.get('id') or props.get('_aot_draw_id')
        return str(v) if v else None

    @classmethod
    def _slant_of(cls, ref, props, dup):
        """(대응 여부, slant_m). 같은 이름이 둘 이상이면 어느 쪽인지 못 가리므로 대응하지 않는다."""
        pid = cls._pipe_ref_ids(props)
        if not ref or not pid or dup.get(pid, 0) > 1:
            return False, None
        row = (ref.get('pipes') or {}).get(pid)
        if row is None:
            return False, None
        return True, row.get('slant_m')

    @staticmethod
    def _terrain_mark(ref):
        st = ref.get('state')
        return {"state": st} if st == 'warming' else {"state": st, "version": ref.get('version')}

    @classmethod
    def _area_owner_test(cls, shapes, area_name):
        """area_name 의 대지·구역이 설비 피처를 소유하는지 가리는 함수 ``(props, geom) -> bool``.

        소유 링크(parent_node_id/zone_id)가 이 장소나 하위 장소를 가리키면 소유, 다른 곳을
        가리키면 아니고, 링크가 없으면 다각형 포함으로 가린다. 이름에 맞는 장소가 없으면 None.
        설비 상세 읽기와 배관 관경 쓰기가 같은 판정을 쓴다 — 두 벌이면 읽은 것과 고친 것이 갈린다.
        """
        node_ids, polys = cls._area_node_ids_and_polys(shapes, area_name)
        if node_ids or polys:
            node_ids = set(node_ids) | cls._descendant_place_node_ids(area_name)
        if not node_ids and not polys:
            return None
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
        return _owned

    @classmethod
    def get_map_equipment_detail_tool(cls, area_name=None, **extra):
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
            _owned = cls._area_owner_test(shapes, area_name)
            if _owned is None:
                return cls._map_area_miss(shapes, area_name) or {
                    "status": "error",
                    "error": "Area '%s' was not found." % area_name}

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
            _slant_cache, _terrain, _dup = {}, None, {}
            for s in shapes:
                if s.type not in ('equipment_collection', 'equipment'):
                    continue
                try:
                    _c = s.feature if isinstance(s.feature, dict) else _json.loads(s.feature or '{}')
                except Exception:
                    continue
                for f in ((_c.get('features') if s.type == 'equipment_collection' else [_c]) or []):
                    _k = cls._pipe_ref_ids((f or {}).get('properties') or {}) if isinstance(f, dict) else None
                    if _k:
                        _d = _dup.setdefault(s.geo_id, {})
                        _d[_k] = _d.get(_k, 0) + 1
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
                            _ref = cls._slant_ref(_slant_cache, s.geo_id)
                            if _ref:
                                _terrain = _terrain or cls._terrain_mark(_ref)
                                _hit, _sl = cls._slant_of(_ref, props, _dup.get(s.geo_id, {}))
                                if _hit and _sl is not None:
                                    pipes[-1]["length_3d_m"] = round(_sl, 1)
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
                "sprinkler_total_flow_lph": round(sum(
                    float(e['flow_lph']) for e in sprinklers
                    if isinstance(e.get('flow_lph'), (int, float))), 1) or None,
                # 점적 (drip — per drip-pipe, emitters spaced by interval)
                "drip_pipes": drip_pipes,
                "drip_emitter_total": sum(d['drip_emitters'] for d in drip_pipes),
                "pipes": pipes,
                "length_basis": "horizontal",           # length_m 은 지도 평면 길이(경사 길이 아님)
            }
            # 머리가 모두 같은 규격이면 규격은 한 번만, 위치는 [lat, lng] 쌍으로 — 머리마다
            # 같은 radius·flow 를 되풀이하던 응답을 줄인다(2026-10-28 점검).
            _specs = {(e.get('radius_m'), e.get('flow_lph')) for e in sprinklers}
            if len(sprinklers) > 1 and len(_specs) == 1:
                _r, _f = next(iter(_specs))
                out["sprinkler_spec"] = {"radius_m": _r, "flow_lph": _f}
                out["sprinklers"] = [[e['lat'], e['lng']] for e in sprinklers[:MAXE]]
                out["sprinklers_format"] = "[lat, lng] per head; every head has sprinkler_spec"
            if _terrain:
                out["terrain"] = _terrain
            if len(sprinklers) > MAXE:
                out["sprinklers_truncated"] = f"showing first {MAXE} of {len(sprinklers)} sprinklers"
            if not out.get("sprinkler_total_flow_lph"):
                out.pop("sprinkler_total_flow_lph", None)
            if not sprinklers and not pipes:
                out["message"] = f"No irrigation equipment geometry found in '{area_name}'."
            _tgt = cls._exact_area_target(area_name)
            if _tgt:
                cls._with_target(out, *_tgt, ref=area_name, exact=True)
            return out
        except Exception as e:
            logger.error(f"Error in get_map_equipment_detail_tool: {e}")
            return {"error": str(e)}

    @classmethod
    def _find_placeable_device(cls, device_id):
        """Return (obj, kind) for an Input or Output by unique_id, else (None, None)."""
        from aot.databases.models import Input, Output
        o = Input.query.filter_by(unique_id=device_id).first()
        if o:
            return o, 'input'
        o = Output.query.filter_by(unique_id=device_id).first()
        if o:
            return o, 'output'
        return None, None

    @classmethod
    def get_device_location(cls, device_id=None, **extra):
        """Read a device's current map location (latitude/longitude). Read-only."""
        if not device_id:
            return {"error": "device_id is required"}
        obj, kind = cls._find_placeable_device(device_id)
        if not obj:
            return {"error": f"Device not found: {device_id}"}
        # 'AI 판단에 포함' 을 끈 장치는 AI 조회 대상이 아니다(device_resolver).
        from aot.services.resolvers.device_resolver import (
            AI_EXCLUDED, ai_excluded_error)
        refusal = ai_excluded_error(obj)
        if refusal:
            return {"error": refusal, "reason_code": AI_EXCLUDED}
        # 위치의 정본은 리졸버 하나(device_location.locate) — 장치 컬럼을 직접 읽지 않는다.
        lat = lng = None
        basis = 'none'
        try:
            from aot.space.device_location import locate
            pl = locate(kind, device_id)
            if pl is not None and pl.point is not None:
                lat, lng = pl.point
                basis = pl.basis
        except Exception:
            logger.debug('get_device_location: 리졸버 실패', exc_info=True)
        out = {"device_id": device_id, "kind": kind, "name": getattr(obj, 'name', None),
               "lat": lat, "lng": lng,
               # 'device' 장치 자리 | 'site' 대지 기준(장치는 아직 배치 전) | 'none'
               "location_basis": basis,
               # [P2] 배치된 지도는 마커에서 파생한다.
               "map_id": _map_for_device_p2(device_id)}
        # 소속 장소('3포장 > 3-1') — 좌표만으로는 어느 구역인지 알 수 없어
        # 모델이 다른 도구로 다시 물었다(2026-10-08). 정본 경로로 낸다.
        try:
            from aot.space.device_membership import annotate_places
            annotate_places([out], id_key='device_id')
        except Exception:
            logger.debug('get_device_location: 장소 경로 조회 실패', exc_info=True)
        return out

    @classmethod
    def _distance_error(cls, err):
        """오류를 응답 dict 로. 모호할 때는 후보를 실은 dict 가 그대로 온다 —
        문구로 뭉개면 되물을 근거(후보 uuid)가 사라진다."""
        return err if isinstance(err, dict) else {"error": err}

    @classmethod
    def nearest(cls, reference=None, candidates=None, **extra):
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
                return cls._distance_error(err)
            return result
        except Exception as e:
            logger.exception("Error in nearest")
            return {"error": str(e)}

    @classmethod
    def set_device_location(cls, device_id=None, lat=None, lng=None, map_id=None, **extra):
        """Place / move a device on a map (marker + placement binding). Works for
        Input, Output, Function-type controllers (PID, Trigger, Conditional,
        Custom Controller, Function). The device row's lat/lng columns are NOT
        written: the placement (marker) is the source of truth and every
        reader derives the position from it.

        map_id picks the map. Without it the device's current map is used, else
        the only map when exactly one exists; otherwise an error asks for map_id.
        Response carries `location_basis` ('device' once placed) and `source`.
        """
        if not device_id:
            return {"error": "device_id is required"}
        if lat in (None, '') or lng in (None, ''):
            return {"error": "lat and lng are required"}
        try:
            lat_f, lng_f = float(lat), float(lng)
        except (TypeError, ValueError):
            return {"error": "lat and lng must be numbers"}
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
            return {"error": "lat/lng out of range"}
        from aot.space import device_binding
        kind = device_binding.resolve_device_kind(device_id)
        if kind is None:
            return {"error": f"Device not found: {device_id}"}
        obj = dict(device_binding.device_kind_models())[kind].query.filter_by(
            unique_id=device_id).first()
        if not obj:
            return {"error": f"Device not found: {device_id}"}
        # 쓰기 시점 그룹 스코프 — 옮길 장치로 묻는다.
        from aot.aot_flask.access import write_scope
        write_scope.enforce(obj)
        try:
            from aot.databases.models import GeoMap
            map_uuid = map_id or _map_for_device_p2(device_id)
            if not map_uuid:
                maps = GeoMap.query.all()
                if len(maps) == 1:
                    map_uuid = maps[0].unique_id
                elif not maps:
                    return {"error": "No map exists; create a map first."}
                else:
                    return {"error": "map_id is required (several maps exist and "
                                     "the device is not placed on any)."}
            elif map_id and not GeoMap.query.filter_by(unique_id=map_id).first():
                return {"error": f"Map not found: {map_id}"}
            # 지도에 대한 스코프 — REST(/api/geo/device/location)와 같은 판정.
            from aot.aot_flask.access import scope as _scope
            if not _scope.can_operate('geo_map', map_uuid):
                return {"error": _scope.deny_message()}
            from aot.aot_flask.geo.device_placement import place_device, unplace_device
            # 이동 의도: 다른 지도의 마커는 내리고(사유 'unbound') 이 지도에만 둔다.
            from aot.space.device_membership import maps_for_device
            for other in maps_for_device(device_id):
                if other != map_uuid:
                    unplace_device(device_id, other, 0)
            # 지도 UI 어휘: 'function'=CustomController, 'generic_function'=Function.
            geo_type = {'device': 'function', 'function': 'generic_function'}.get(kind, kind)
            place_device(device_id, map_uuid, lat_f, lng_f,
                         device_type=geo_type, name=getattr(obj, 'name', None))
            db.session.commit()
            try:
                from aot.space import containment_cache
                containment_cache.invalidate()
            except Exception:
                pass
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        r = {"device_id": device_id, "kind": kind, "status": "placed",
             "lat": lat_f, "lng": lng_f, "map_id": map_uuid,
             "location_basis": "none", "source": "none"}
        try:
            from aot.space.device_location import locate
            pl = locate(kind, device_id)
            if pl is not None:
                r["location_basis"] = pl.basis
                r["source"] = pl.source
        except Exception:
            logger.debug('set_device_location: 리졸버 실패', exc_info=True)
        if extra:
            r["ignored_args"] = list(extra.keys())
        return r

    @classmethod
    def get_address(cls, target_name=None, target_id=None, lat=None, lng=None, **extra):
        """
        [읽기전용] 좌표 또는 위치 이름(구역/시설/장치)을 사람이 읽는 주소로
        변환한다 (역지오코딩). 위치 조회 문(`aot_flask/geo/geo_lookup.py`)이 좌표→주소를
        지원하는 GIS Input 을 골라 부른다. 쓸 수 없으면 좌표만 돌려주고 그 이유를 알린다.

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
                        cls._resolve_note_target(target_name)
                    if not target_id and _tt == 'ambiguous':
                        # 여러 곳에 걸린 이름을 "못 찾음" 이라 하면 사용자가
                        # 이름을 고치려 든다. 고를 것은 이름이 아니라 곳이다.
                        amb = cls._ambiguous_places(target_name) or []
                        return {
                            "status": "needs_disambiguation",
                            "error": "ambiguous_name",
                            "message": (f"'{target_name}' names {len(amb)} different "
                                        "places. Ask which one, then retry with that "
                                        "candidate's 'use_name' as target_name or its "
                                        "'target_id' as target_id."),
                            "candidates": amb,
                        }
                    if not target_id:
                        return {
                            "status": "error",
                            "message": f"위치 '{target_name}'를 찾지 못했습니다.",
                            "available_targets": cls._geoshape_name_candidates(),
                        }
                if not target_id:
                    return {"status": "error",
                            "message": "target_name, target_id, 또는 lat/lng 중 하나는 필요합니다."}
                lat, lng = resolve_location_coords(target_id)
                if lat is None or lng is None:
                    return {"status": "error",
                            "message": f"'{resolved_name or target_id}'의 좌표를 확인할 수 없습니다."}

            from aot.aot_flask.geo import geo_lookup
            found = geo_lookup.find_address(float(lat), float(lng), provider=extra.get('provider') or None)
            if found.get("status") != "ok":
                # 좌표는 이미 있다 — 버리지 않고 주소 부분만 unavailable 로 알린다.
                out = {
                    "status": "partial",
                    "lat": float(lat), "lng": float(lng),
                    "address": "unavailable",
                    "reason": found.get("code"),
                    "message": ("좌표는 확인했지만 주소는 변환할 수 없습니다: %s "
                                "(지도 > GIS 입력에서 좌표→주소를 지원하는 입력을 등록하고 키를 설정하세요)."
                                % (found.get("error") or "no provider")),
                }
                if resolved_name:
                    out["location"] = resolved_name
                return out
            result = {"status": "ok", "address": found["address"], "type": found.get("type"),
                      "provider": found["provider"]["type"],
                      "lat": float(lat), "lng": float(lng)}
            if resolved_name:
                result["location"] = resolved_name
            return result
        except Exception as e:
            logger.error(f"Error in get_address: {e}")
            return {"status": "error", "message": f"주소 변환 중 오류: {str(e)}"}

    @classmethod
    def find_location(cls, query=None, provider=None, limit=None, **extra):
        """[읽기전용] 주소·장소 이름 → 좌표 후보 (정지오코딩). 등록된 GIS 입력의 검색 API 를
        위치 조회 문(`aot_flask/geo/geo_lookup.py`)으로 부른다 — 공급자 선택·키 읽기는 거기서만 한다."""
        from aot.aot_flask.geo import geo_lookup
        kwargs = {} if limit in (None, '') else {'limit': limit}
        return geo_lookup.find_location(query, provider=provider or None, **kwargs)

    @classmethod
    def find_favorites(cls, query=None, limit=None, **extra):
        """[읽기전용] 지도 즐겨찾기(사용자가 시트에 담아 둔 장소) 목록. 농장 전체 공유인 것만 돌려준다 —
        개인용은 AI 에게 보이지 않는다. query 는 이름·주소에 든 글자."""
        from aot.aot_flask.geo import geo_favorites
        try:
            n = max(1, min(int(limit), 50)) if limit not in (None, '') else 20
        except (TypeError, ValueError):
            n = 20
        rows = geo_favorites.search(query, limit=n, user=None)
        return {"status": "ok", "count": len(rows),
                "favorites": [{"name": r["name"], "address": r["address"], "lat": r["lat"], "lng": r["lng"]}
                              for r in rows]}

    # ── 배관 관경 일괄 입력 (set_pipe_diameters) ────────────────────────────
    # 웹 설계 화면(aot-geo-pipe-diameters.js)과 같은 자리에 같은 값을 쓴다:
    # equipment_collection 의 피처 properties.diameter_mm. 웹 저장은 묶음 통째 교체라
    # 개정번호가 없다 — 그래서 여기서는 쓰기 직전에 행을 다시 읽어 diameter_mm 만 고친다.

    @staticmethod
    def _parse_diameter_mm(raw, name):
        """웹 parseDiameter 와 같은 규칙: 1 이상의 유한한 수. (값|None, 오류|None)."""
        import math as _m
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None, None
        if isinstance(raw, bool):
            return None, "%s must be a number >= 1 (mm)" % name
        try:
            n = float(str(raw).strip()) if isinstance(raw, str) else float(raw)
        except (TypeError, ValueError):
            return None, "%s must be a number >= 1 (mm)" % name
        if not _m.isfinite(n) or n < 1:
            return None, "%s must be a number >= 1 (mm)" % name
        return (int(n) if n == int(n) else n), None

    @classmethod
    def _pipe_diameter_plan(cls, area_name, main_mm, branch_mm, only_empty=True):
        """읽기 전용 계획. (오류 응답|None, 계획 dict). 계획의 rows 는 쓰기 때 다시 읽는다."""
        import json as _json
        import math as _math
        from aot.databases.models import GeoShape
        area_name = (area_name or '').strip()
        if not area_name:
            return {"status": "error", "error": "area_name (a site/zone name) is required."}, None
        mv, err = cls._parse_diameter_mm(main_mm, 'main_mm')
        if err:
            return {"status": "error", "error": err}, None
        bv, err = cls._parse_diameter_mm(branch_mm, 'branch_mm')
        if err:
            return {"status": "error", "error": err}, None
        if mv is None and bv is None:
            return {"status": "error", "error": "Give main_mm and/or branch_mm."}, None
        shapes = GeoShape.query.all()
        # id 로 불러도 이름으로 푼다
        for sh in shapes:
            if sh.type in ('site', 'zone') and sh.unique_id == area_name:
                from aot.space.device_membership import place_label
                area_name = place_label(sh) or area_name
                break
        owned = cls._area_owner_test(shapes, area_name)
        if owned is None:
            return cls._map_area_miss(shapes, area_name) or {
                "status": "error", "error": "Area '%s' was not found." % area_name}, None

        def _len(cs):
            tot = 0.0
            for i in range(1, len(cs)):
                la1, lo1, la2, lo2 = cs[i - 1][1], cs[i - 1][0], cs[i][1], cs[i][0]
                a = (_math.sin(_math.radians(la2 - la1) / 2) ** 2 + _math.cos(_math.radians(la1))
                     * _math.cos(_math.radians(la2)) * _math.sin(_math.radians(lo2 - lo1) / 2) ** 2)
                tot += 2 * 6371000.0 * _math.asin(min(1.0, _math.sqrt(a)))
            return tot

        plan = {"area": area_name, "main_mm": mv, "branch_mm": bv, "only_empty": bool(only_empty),
                "main": 0, "branch": 0, "main_m": 0.0, "branch_m": 0.0,
                "overwrite": 0, "kept_filled": 0, "drip_excluded": 0, "rows": {}}
        for row in shapes:
            if row.type not in ('equipment_collection', 'equipment'):
                continue
            try:
                coll = row.feature if isinstance(row.feature, dict) else _json.loads(row.feature or '{}')
            except Exception:
                continue
            feats = coll.get('features') if row.type == 'equipment_collection' else [coll]
            for idx, f in enumerate(feats or []):
                if not isinstance(f, dict):
                    continue
                props = f.get('properties') or {}
                geom = f.get('geometry') or {}
                sub = props.get('sub_type')
                kind = ('main' if sub in cls._EQUIP_MAIN_SUBTYPES else
                        'branch' if sub in cls._EQUIP_BRANCH_SUBTYPES else None)
                val = mv if kind == 'main' else bv
                if kind is None or val is None or not owned(props, geom):
                    continue
                cs = geom.get('coordinates') or []
                if len(cs) < 2:
                    continue
                if props.get('is_drip'):
                    plan["drip_excluded"] += 1
                    continue
                cur = props.get('diameter_mm')
                filled = cur not in (None, '')
                if filled and only_empty:
                    plan["kept_filled"] += 1
                    continue
                plan[kind] += 1
                plan[kind + '_m'] += _len(cs)
                if filled and cur != val:
                    plan["overwrite"] += 1
                plan["rows"].setdefault(row.unique_id, []).append((idx, kind))
        return None, plan

    @classmethod
    def pipe_diameters_brief(cls, area_name=None, main_mm=None, branch_mm=None,
                             only_empty=True, **extra):
        """승인 되읽기 문구 — 서버가 풀어낸 영역과 건수. 실패해도 승인 흐름은 깨지 않는다."""
        try:
            err, p = cls._pipe_diameter_plan(area_name, main_mm, branch_mm,
                                             cls._as_bool(only_empty, True))
        except Exception:                                   # noqa: BLE001
            logger.debug('pipe diameters brief failed', exc_info=True)
            return ''
        if err:
            return ' (%s)' % (err.get('error') or err.get('message') or 'cannot resolve')
        parts = []
        if p['main_mm'] is not None:
            parts.append('main %d pipes (%.0f m horizontal) -> %s mm' % (p['main'], p['main_m'], p['main_mm']))
        if p['branch_mm'] is not None:
            parts.append('branch %d pipes (%.0f m horizontal) -> %s mm' % (p['branch'], p['branch_m'], p['branch_mm']))
        parts.append('overwrites %d existing values' % p['overwrite'])
        if p['kept_filled']:
            parts.append('keeps %d already set' % p['kept_filled'])
        parts.append('skips %d drip lines' % p['drip_excluded'])
        return " [%s: %s]" % (p['area'], '; '.join(parts))

    @staticmethod
    def _as_bool(v, default=True):
        if v is None or v == '':
            return default
        if isinstance(v, str):
            return v.strip().lower() not in ('false', '0', 'no', 'off')
        return bool(v)

    @classmethod
    def set_pipe_diameters(cls, area_name=None, main_mm=None, branch_mm=None,
                           only_empty=True, **extra):
        """Set diameter_mm on the main/branch pipes of a site/zone (drip lines skipped)."""
        import copy as _copy
        from aot.databases.models import GeoShape
        from aot.aot_flask.access import write_scope
        if not area_name:
            area_name = extra.get('name') or extra.get('target_name') or extra.get('zone_name')
        only_empty = cls._as_bool(only_empty, True)
        err, plan = cls._pipe_diameter_plan(area_name, main_mm, branch_mm, only_empty)
        if err:
            return err
        try:
            db.session.expire_all()           # 쓰기 직전에 다시 읽는다(웹 저장과의 간격 최소화)
            err, plan = cls._pipe_diameter_plan(area_name, main_mm, branch_mm, only_empty)
            if err:
                return err
            changed = 0
            for uid, items in plan["rows"].items():
                row = GeoShape.query.filter_by(unique_id=uid).first()
                if row is None:
                    continue
                write_scope.enforce(row)
                coll = _copy.deepcopy(row.feature if isinstance(row.feature, dict) else {})
                feats = coll.get('features') if row.type == 'equipment_collection' else [coll]
                for idx, kind in items:
                    props = feats[idx].setdefault('properties', {})
                    props['diameter_mm'] = plan['main_mm'] if kind == 'main' else plan['branch_mm']
                    changed += 1
                row.feature = coll
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            if type(e).__name__ == 'WriteScopeDenied':
                raise
            return {"status": "error", "error": str(e)}
        try:
            from aot.aot_flask.geo.geo_overlays import _drop_containment_cache
            _drop_containment_cache()
        except Exception:                                   # noqa: BLE001
            pass
        out = {"status": "success", "area": plan["area"], "pipes_set": changed,
               "main": plan["main"], "branch": plan["branch"],
               "overwritten": plan["overwrite"], "kept_filled": plan["kept_filled"],
               "drip_excluded": plan["drip_excluded"]}
        try:
            tgt = cls._exact_area_target(plan["area"])
            if tgt:
                from aot.utils import water_net_link as _wnl
                shp = GeoShape.query.filter_by(unique_id=tgt[1]).first()
                pr = _wnl.pressure_for_area(shp.geo_id, tgt[1]) if shp else None
                if pr:
                    out["water"] = [
                        {k: v for k, v in _wnl.pressure_brief(r).items()
                         if k in ('level', 'diameter_ratio', 'missing_pipes', 'bar_min', 'bar_max')}
                        for r in pr["circuits"]]
        except Exception:                                   # noqa: BLE001
            logger.debug('pipe diameters: water level readback failed', exc_info=True)
        return out

    @classmethod
    def delete_geo_shape(cls, shape_id=None, **extra):
        """Delete a SINGLE geo shape (zone / area / marker) by its unique_id. Guarded:
        one shape by id — never a bulk/layer delete."""
        # [S5] 도형 삭제는 geo 게이트웨이로만 — 시설·bay·설정점 연쇄와
        # 장치 소속 해제는 DB 트리거가 처리하므로 여기서 알 필요가 없다.
        from aot.aot_flask.geo.device_placement import delete_shape
        if not shape_id:
            return {"error": "shape_id is required"}
        # 쓰기 시점 그룹 스코프 — 도형에 연결된 장치·시설로 묻는다(도형 자체의
        # 지도 단위 스코프는 구역 스코프와 함께 따로 다룬다 — write_scope).
        from aot.aot_flask.access import write_scope
        _shape = GeoShape.query.filter(
            GeoShape.unique_id == str(shape_id).strip()).first()
        if _shape is not None:
            write_scope.enforce(_shape)
        try:
            stype = delete_shape(shape_id, commit=True)
            if stype is None:
                return {"error": f"Geo shape not found: {shape_id}"}
        except Exception as e:
            db.session.rollback()
            return {"error": str(e)}
        return {"shape_id": shape_id, "shape_type": stype, "status": "deleted"}

    @classmethod
    @tz_scoped
    def get_crop_status(cls, facility_id=None, facility_name=None, limit=None,
                            detail=None, **extra):
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

        `open_field_plots`/`facility_bay_plots` 는 `limit`(기본 10, 목록 하나당)
        을 넘으면 앞에서부터 그만큼만 낸다 — 벤치 실측(2026-09-24): 노지 구획
        44건을 필터 없이 다 실어 이 도구 하나가 중앙값 22,904자였다(상한 4,000자
        목표엔 10건 안팎이라야 닿는다 — 30건은 한 자리 감소율에 그쳤다).
        `facilities`(env_coordinator 시설)는 대개 몇 개뿐이라 자르지 않는다.

        `detail`: None/True = 예전 모양 · False = 구역·작물·경과일수·id 만(기본 상한 40).
        도메인 틀(`overview.crops`)이 False 를 넣는다.
        """
        import json as _json
        from aot.tools.data_tools import crop_compact as _cc
        _compact = _cc.wants_compact(detail)
        try:
            from aot.databases.models import CustomController, GeoFacility

            _facs = GeoFacility.query.all()
            fac_names = {f.unique_id: f.name for f in _facs}
            fac_shape = {f.unique_id: f.shape_uuid for f in _facs}
            wanted_name = (facility_name or '').strip().lower() or None
            # 공간 트리의 시설 ID(도형)로 불러도 같은 시설을 찾는다.
            if facility_id:
                _fr = cls._resolve_facility(facility_id)
                if _fr is None:
                    return {"status": "error", "error": (
                        "No facility '%s' — pass its id from get_spatial_tree "
                        "(facility_id or the facility node's unique_id) or its "
                        "name." % facility_id)}
                facility_id = _fr.unique_id
            # 시설 필터가 걸리면 구획 목록도 그 시설 것만 낸다(2026-10-10 외부 AI
            # 5차 점검): 예전에는 facilities 만 걸러지고 노지 구획 44건과 다른
            # 시설의 구획이 그대로 실려, 호출자가 그것을 요청한 시설의 구획으로
            # 읽었다. 이름이 정확히 맞으면 그 시설 하나, 아니면 부분 일치 전부.
            wanted_facs = None
            _tfac = None        # 정확히 풀린 시설 하나 — 결과에 대상 id 로 싣는다
            if facility_id:
                wanted_facs = {facility_id}
                _tfac = _fr
            elif wanted_name:
                _fr = cls._resolve_facility(facility_name.strip())
                _tfac = _fr
                wanted_facs = ({_fr.unique_id} if _fr is not None else
                               {u for u, n in fac_names.items()
                                if wanted_name in (n or '').lower()})
                if not wanted_facs:
                    return {"status": "error", "error": (
                        "No facility named '%s'. Facilities: %s." % (
                            facility_name, ", ".join(sorted(
                                n for n in fac_names.values() if n)) or "none"))}

            rows = []
            for c in CustomController.query.filter_by(device='env_coordinator',
                                                      is_activated=True).all():
                try:
                    o = _json.loads(c.custom_options) if c.custom_options else {}
                except (ValueError, TypeError):
                    o = {}
                fid = o.get('geo_facility_id')
                fname = fac_names.get(fid)
                if wanted_facs is not None and fid not in wanted_facs:
                    continue
                rows.append({
                    "facility_id": fid,
                    "facility_place_id": fac_shape.get(fid),
                    "facility_name": fname,
                    "crop": _control_targets_for(c).get('plot'),
                    "stage": _control_targets_for(c).get('stage'),
                    "controlled_by": c.unique_id,
                    "season_window": [_plot_started_on(c),
                                      _plot_ended_on(c)[0]],
                })

            # 도메인 레지스트리로 생육단계 보강 (있을 때만)
            registry_note = None
            for r in rows:
                if not r["facility_id"]:
                    continue
                try:
                    module = providers.get('domain_module')(r["facility_id"])
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
            # 시설 구획은 노지가 아니다 — 이름을 섞으면 AI 가 온실 작물을
            # 노지로 읽는다. 판별 축이 **둘**이라는 것이 함정이다:
            #   - `facility_uuid` — 시설 구역에 직접 매단 구획(p6_39)
            #   - `source_kind='bay_snapshot'` — 옛 `bays[].crop` 백필분
            #     (기하를 복사해 왔을 뿐 부모 참조는 없다)
            # 한쪽만 보면 나머지 절반이 조용히 노지로 분류된다.
            # `bays[].crop` 은 아직 살아 있어(폴백) 같은 작물이 facilities 와
            # 여기 양쪽에 보일 수 있다. 그 사실을 note 로 밝힌다.
            #
            # 판정은 **행**으로 한다. 예전에는 `_plot_brief` 결과 dict 의
            # `facility_uuid`/`source_kind` 를 봤는데, 그 둘은 화면 배선이라
            # 목록용 요약 뷰에 실리지 않는다 — dict 를 보면 시설 구획이 통째로
            # 노지로 넘어간다. 같은 값이 행에 그대로 있으므로 거기서 읽는다.
            def _in_facility(row):
                return bool(row.facility_uuid) or \
                    row.source_kind == 'bay_snapshot'

            wanted_fac_names = ({fac_names.get(u) for u in wanted_facs}
                                if wanted_facs is not None else None)

            def _in_wanted(row, brief):
                """시설 필터가 걸렸을 때 이 시설 구획이 그 시설 것인가.
                bay_snapshot 행은 부모 참조가 없어 브리프의 시설 이름으로 본다."""
                if row.facility_uuid:
                    return row.facility_uuid in wanted_facs
                return brief.get('facility_name') in wanted_fac_names

            open_plots, bay_plots = [], []
            farm_open_count = 0     # 시설 필터가 걸려도 농장 전체 노지 구획 수는 센다
            try:
                from aot.databases.models import GeoMap
                from aot.space import plot_context
                for m in GeoMap.query.all():
                    for row in plot_context.active_plots(m.unique_id):
                        # 브리프는 어디를 팔지 고르는 지도다 — 구획 상세는
                        # get_plot 이 낸다. 상세를 행마다 실으면 상한을 넘고,
                        # 넘으면 캡이 목록을 잘라 "31건 중 1건" 이 나간다.
                        d = cls._plot_brief(row, summary=True)
                        # `map_id`(raw uuid)는 안 싣는다 — zone_name/zone_kind
                        # 로 이미 어디인지 이름으로 답하고, 아무 코드도 이
                        # 값을 읽지 않는다(2026-09-29 실측: 유일한 참조가
                        # 이 줄 자신이었다).
                        if wanted_facs is not None:
                            # 시설 필터 — 노지 구획은 시설 안에 없다.
                            if _in_facility(row) and _in_wanted(row, d):
                                bay_plots.append(d)
                            elif not _in_facility(row):
                                farm_open_count += 1
                            continue
                        (bay_plots if _in_facility(row) else
                         open_plots).append(d)
            except Exception as exc:
                logger.warning("get_crop_status: 식생 구획 조회 실패: %s", exc)

            # 목록 하나마다(노지·시설 베이 각각) 상한을 둔다 — `plot_count`/
            # `facility_bay_plot_count` 는 자르기 **전** 참값이라 get_system_brief
            # 의 합산이 잘려도 어긋나지 않는다.
            total_open, total_bay = len(open_plots), len(bay_plots)
            _lim = int(limit) if limit else (
                _cc.COMPACT_LIMIT if _compact else cls._PLOT_LIST_DEFAULT_LIMIT)
            open_truncated = total_open > _lim
            bay_truncated = total_bay > _lim
            open_rest = []
            if open_truncated:
                # 잘려 나간 구획도 이름은 남긴다 — 앞 10건만 본 AI 가 나머지를
                # "없다" 로 읽거나 구역마다 다시 부르지 않게(2026-10-19 리허설).
                open_rest = [cls._plot_rest_label(p) for p in open_plots[_lim:]]
                _more = len(open_rest) - cls._PLOT_REST_NAMES_MAX
                if _more > 0:
                    open_rest = open_rest[:cls._PLOT_REST_NAMES_MAX] + [
                        "... +%d more" % _more]
                open_plots = open_plots[:_lim]
            if bay_truncated:
                bay_plots = bay_plots[:_lim]

            result = {"status": "success", "count": len(rows), "facilities": rows}
            if wanted_facs is None:
                result["open_field_plots"] = open_plots
                result["plot_count"] = total_open
            else:
                # 시설을 지정하면 노지 구획은 이 응답의 대상이 아니다. 빈 목록
                # (`open_field_plots: []`, `plot_count: 0`)을 싣던 때는 "노지에 구획이
                # 없다" 로 읽혔다 — 키를 빼고 어디서 보는지 말한다.
                result["facility_filter"] = sorted(
                    n for n in (wanted_fac_names or ()) if n)
                result["facility_filter_note"] = (
                    "Filtered to the facility asked for: facility_bay_plots are "
                    "only that facility's plots. Open-field plots are NOT in this "
                    "response (they are not inside a facility) - this is not "
                    "'none': %d are growing elsewhere on the farm. See them with "
                    "find.plots (target = a site or zone) or without a target." % farm_open_count)
                result["open_field_plots_elsewhere"] = farm_open_count
            if open_rest:
                result["open_field_rest"] = open_rest
                result["open_field_rest_note"] = (
                    "Names of the open-field plots NOT listed in open_field_plots "
                    "(crop @ zone). For their stages: find.plots with target = the "
                    "zone/site, or raise limit.")
            if open_truncated or bay_truncated:
                result["truncated"] = True
                result["truncated_note"] = (
                    "Showing the first %d of %d open-field plot(s) and the "
                    "first %d of %d facility-bay plot(s). Call again with a "
                    "higher limit for the rest." % (
                        len(open_plots), total_open, len(bay_plots), total_bay))
            if open_plots or bay_plots:
                # 요약이라는 사실을 응답이 직접 말한다. 이것이 없으면 모델은
                # 목록에 없는 필드를 "없는 값" 으로 읽고 — 단계 일정도 치수도
                # 여기서는 빠져 있다 — 상세를 부르지 않은 채 그렇게 답한다.
                result["plot_detail"] = (
                    "Plots here are summaries: crop, place, period and current "
                    "stage only. Stage schedule, timeline, dimensions, planting "
                    "capacity and the target-vs-reading comparison "
                    "('target_check') are NOT in this response — call get_plot "
                    "with the plot's unique_id for those. Absence of a field "
                    "here does not mean the plot lacks it.")
            if bay_plots:
                result["facility_bay_plots"] = bay_plots
                result["facility_bay_plot_count"] = total_bay
                result["facility_bay_plot_note"] = (
                    "These grow inside facilities (greenhouse bays), not in the open "
                    "field, and each carries its own start date and history. Their "
                    "location is the bay itself, so they have no area or capacity "
                    "estimate — read their notes for the actual layout. The same crop "
                    "may still appear under 'facilities' because the legacy "
                    "bays[].crop field is kept until the migration is verified in "
                    "production — do not count it twice.")
            if not rows and not open_plots and not bay_plots:
                result["message"] = (
                    "No active env_coordinator carries crop information. Check whether an "
                    "environment-control coordinator is configured for the facility.")
            elif not rows:
                result["message"] = (
                    "No greenhouse crop info, but open-field vegetation plots exist — "
                    "see open_field_plots (crop, period, area). Use get_plot_history "
                    "for what grew on the same spot before.")
            if registry_note:
                result["growth_stage_unavailable"] = registry_note
            # 도구 설명에 있던 읽는 법을 응답으로 옮겼다(B′) — 구획이 있을 때만.
            plots = list(open_plots) + list(bay_plots)
            if plots:
                has_guidance = any((p.get('stage') or {}).get('guidance')
                                   for p in plots)
                result["_reading"] = [
                    ("'stage.guidance' is what THAT plot's programme says to do "
                     "in its current stage — quote it instead of generic crop "
                     "advice." if has_guidance else
                     "No plot here has programme guidance for its current stage "
                     "('stage.guidance' is null) — say so; do not present generic "
                     "crop advice as if it came from the programme."),
                    "'facilities[].stage' is a stage NAME only; guidance is on the "
                    "plots.",
                ]
            if _tfac is not None and getattr(_tfac, 'shape_uuid', None):
                cls._with_target(result, 'facility', _tfac.shape_uuid,
                                 ref=facility_id or facility_name, exact=True)
            return _cc.compact_status(result) if _compact else result
        except Exception as e:
            logger.exception("Error in get_crop_status")
            return {"status": "error", "message": str(e)}

    #: get_crop_status 가 잘려 나간 노지 구획을 이름으로만 남길 때의 최대 개수.
    _PLOT_REST_NAMES_MAX = 40

    @classmethod
    def _plot_rest_label(cls, p):
        """'콩 4구 @ 3-2' — 목록에서 잘린 구획을 한 줄로."""
        subj = p.get('subject') or p.get('name') or '?'
        zone = p.get('zone_name')
        return "%s @ %s" % (subj, zone) if zone else str(subj)

    _PLOT_SUMMARY_KEYS = (
        # 상세로 넘어가는 열쇠. 이것만은 뺄 수 없다(get_plot 의 plot_id).
        'unique_id',
        'name', 'kind', 'subject', 'variety',
        # 위치. uuid 가 아니라 이름으로 낸다 — 사람에게 그대로 옮길 수 있고,
        # 도구로 넘길 id 가 필요하면 resolve_target 이 이름에서 찾아 준다.
        'zone_name', 'zone_kind', 'facility_name', 'bay_name', 'allocation',
        'area_m2',
        # 기간. 달력만 보는 값이라 목록에서도 항상 답에 쓰인다.
        'started_on', 'days_since_planted', 'planned', 'days_until_start',
        'expected_end_on', 'days_to_expected_end',
        # 종료일의 출처와 단계 일정과의 어긋남. 이름이 비슷한 stage.days_left
        # (단계 끝까지)와 구분해 읽게 하는 값이다. 어긋남·열린 단계·프로그램
        # 없음은 해당할 때만 실린다.
        'expected_end_source', 'end_check', 'expected_end_unknown', 'no_program',
        'active', 'ended_on', 'ended_reason',
        # 센서는 부른 쪽이 with_sensors 로 **명시적으로 요청했을 때만** 실린다.
        # 요약이라고 지우면 list_plots 의 sensors.source 안내가 거짓이 된다.
        'sensors',
    )

    _PLOT_SUMMARY_STAGE_KEYS = ('name', 'index', 'total', 'day_in_stage',
                                'days_left', 'days_left_in_stage', 'days_past',
                                'guidance')

    @classmethod
    def _plot_summary(cls, d):
        """`_plot_brief` 결과 → 목록용 얇은 dict. 원본은 건드리지 않는다."""
        out = {k: d[k] for k in cls._PLOT_SUMMARY_KEYS
               if d.get(k) is not None}
        # 접힌 zone(site 와 같은 땅의 유일한 기본 이름 zone)은 이름을 싣지 않는다 —
        # 같은 이름이 `place` 와 겹친다. zone_kind 는 사실 그대로 둔다.
        if d.get('zone_collapsed'):
            out.pop('zone_name', None)
        chk = out.get('end_check')
        if isinstance(chk, dict):
            if chk.get('state') == 'aligned':
                out.pop('end_check')          # 맞는 것은 싣지 않는다(크기)
            else:
                out['end_check'] = {k: v for k, v in chk.items()
                                    if k != 'note'}
        st = d.get('stage')
        if isinstance(st, dict):
            thin = {k: st[k] for k in cls._PLOT_SUMMARY_STAGE_KEYS
                    if st.get(k) is not None}
            # 진행 중이 아닌 상태(past_end 등)만 싣는다 — running 은 대부분이라
            # 구획마다 실으면 그만큼 커진다. past_end 를 빼면 "1일 지남" 이
            # 진행 중처럼 읽힌다.
            if st.get('state') and st.get('state') != 'running':
                thin['state'] = st['state']
            if thin:
                out['stage'] = thin
        # 프로그램은 이름만. 버전·단계수·usable_for_control 은 프로그램을
        # 고르는 화면의 값이지, 구획 목록을 읽는 값이 아니다.
        prog = d.get('program')
        if isinstance(prog, dict) and prog.get('name'):
            out['program_name'] = prog['name']
        return out

    @classmethod
    def _plot_brief(cls, row, with_sensors=False, row_spacing_cm=None,
                        plant_spacing_cm=None, edge_margin_cm=None,
                        bed_pitch_cm=None, rows_per_bed=None,
                        containers=None, markers=None, with_valves=None,
                        summary=False):
        from aot.space import plot_context
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
            # 목록은 여기서 끝낸다. 아래 둘은 **구획마다** 붙는데, 하나는
            # 조회를 한 번씩 더 하고(facility_control) 하나는 같은 문장을
            # 행 수만큼 복사한다(scale_unavailable, 건당 60여 토큰). 목록의
            # 안내는 항목이 아니라 리스트에 한 번 붙어야 한다 — 그 자리는
            # get_crop_status 의 facility_bay_plot_note 다.
            if summary:
                return cls._plot_summary(d)
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

        # 목록에서는 치수도 식재량도 세지 않는다. 치수는 구획마다 최소회전
        # 외접사각형을 구하는 기하 계산이고(to_dict 가 with_dims 를 목록에서
        # 끄는 것과 같은 이유), 식재량은 사용자가 간격을 준 조회 — 곧
        # get_plot — 에서만 성립한다.
        if summary:
            return cls._plot_summary(d)

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

    @classmethod
    def _thin_plot_detail(cls, brief):
        """get_plot 응답에서 반복되는 큰 열 둘을 줄인다. 제자리에서 고친다.

        벤치 실측(2026-09-29, get_plot 단건, 6단계 프로그램): `stage_schedule`
        이 최대 4,946자 — 단계마다 `guidance` 문장(현재 단계 것은 이미
        `stage.guidance` 에 있다)과 목표 4개짜리 `targets` 배열(현재 단계
        것은 이미 `stage.targets` 에 있다)을 **6단계 전부** 실은 탓이다.
        날짜·상태(`starts_on`/`ends_on`/`state`)는 그대로 둔다 — 프로그램
        조회 도구(`get_program`/`list_programs`)는 운영 키의 도구 묶음
        밖(설정 전용)이라, 여기서마저 빼면 그 키로는 전체 일정을 **어디서도
        다시 볼 수 없다**(2026-09-29 리뷰: 처음엔 개수만 남기려 했다가,
        `get_program` 을 가리키는 문구가 운영 도구 응답에 설정 전용 도구를
        가리켜서는 안 된다는 검사에 걸려 되돌렸다 — 되찾을 데가 없는 값은
        가볍게라도 남겨야 한다). `timeline.stages`(1,071자, 6단계의 시작일·
        진행률)는 `stage_schedule` 의 날짜와 겹치므로 그대로 뺀다 —
        get_control_state 의 구획 요약과 같은 규칙(`_plot_ctl_brief`).

        뺀 것은 **뺐다는 사실**을 응답에 남긴다 — 없는 값처럼 보이면 안 된다.
        """
        if not isinstance(brief, dict):
            return brief
        sched = brief.get('stage_schedule')
        if isinstance(sched, list) and sched:
            brief['stage_schedule'] = [
                {k: v for k, v in st.items() if k not in ('guidance', 'targets')}
                for st in sched if isinstance(st, dict)]
            brief['stage_schedule_note'] = (
                "Per-stage guidance text and target values are not repeated "
                "here (only dates/state) — 'stage.guidance'/'stage.targets' "
                "already carry the CURRENT stage's in full.")
        tl = brief.get('timeline')
        if isinstance(tl, dict) and 'stages' in tl:
            brief['timeline'] = {k: v for k, v in tl.items() if k != 'stages'}
            brief['timeline_note'] = (
                "'timeline' here is summary scalars only (today_pct, "
                "elapsed_days, total_days...) — the full per-stage start "
                "dates are in 'stage_schedule' and current position in "
                "'stage.index'/'stage.total'; a stage-by-stage percentage "
                "breakdown is not repeated a third time.")
        return brief

    @classmethod
    def list_programs(cls, kind=None, subject=None, crop=None, tab_id=None, **extra):
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
            from aot.space import program_io
            from aot.databases.models import GeoProgram

            want = (subject or crop or '').strip() or None
            q = GeoProgram.query
            if kind:
                q = q.filter(GeoProgram.kind == str(kind).strip())
            if want:
                # 부분일치로, **subject 와 name 양쪽**을 본다.
                #
                # 예전에는 `subject` 완전일치(`==`)였다. 두 가지가 겹쳐 깨졌다.
                # (1) `subject` 는 만들 때 적은 자유 텍스트라 정규화가 없다 —
                #     '상추' 로 물으면 '적상추' 가 0건이 된다.
                # (2) 그보다 나쁜 것은 `subject` 가 **믿을 수 없다**는 점이다.
                #     실측(로컬): name='무' 인 프로그램의 subject 가 'cucumber'
                #     이고, name='콩' 은 subject='custom', 그 밖에 '미지정'·
                #     '새 프로그램' 같은 자리표시자도 있다. 사람이 아는 작물
                #     이름은 사실상 `name` 에 있다(name='노지 가을오이 …').
                # 그래서 '콩'·'오이' 로 물으면 그 프로그램이 실재하는데도 0건이
                # 나왔고, 이 도구가 막으려던 **중복 생성**을 오히려 부추겼다.
                _like = '%%%s%%' % want
                q = q.filter(or_(GeoProgram.subject.ilike(_like),
                                 GeoProgram.name.ilike(_like)))
            if tab_id:
                q = q.filter(GeoProgram.tab_id == str(tab_id).strip())
            rows = q.order_by(GeoProgram.subject.asc()).all()
            out = {"status": "success", "count": len(rows),
                   "programs": [program_io.to_dict(r, with_stages=False)
                                for r in rows]}
            if want:
                _exact = [r for r in rows
                          if (r.subject or '').strip().lower() == want.lower()]
                if rows and not _exact:
                    out["note"] = (
                        "Matched by containment on the programme's subject OR "
                        "its name — no subject is exactly '%s'. Subject is free "
                        "text and is often a placeholder or another language "
                        "(a programme named '노지 가을오이' carries "
                        "subject='cucumber'), so judge these by name. Reuse or "
                        "copy one rather than creating a near-duplicate." % want)
                elif not rows:
                    out["note"] = (
                        "No programme's subject or name contains '%s'. Both are "
                        "free text and may be in another language — try the "
                        "other language or a shorter word before concluding none "
                        "exists and creating a new one." % want)
            return out
        except Exception as e:
            logger.exception("Error in list_programs")
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_program(cls, program_id=None, **extra):
        """[읽기전용] 프로그램 하나 — 단계 목록까지."""
        try:
            from aot.space import program_io
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

    @classmethod
    def create_program(cls, name=None, subject=None, crop=None, stages=None,
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
            from aot.space import program_io

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

    @classmethod
    def modify_program(cls, program_id=None, **fields):
        """[쓰기] 프로그램의 이름·품종·단계·설명을 고치거나, 다른 탭으로 옮긴다.
        사람 승인 필요.

        **내장·외부 프로그램은 서버가 거절한다** — 업그레이드나 외부 갱신이 그
        수정을 덮어써 조용히 되돌아가기 때문이다. 고치려면 사람이 화면에서
        복제한 뒤 그 사본을 고친다. **단, `tab_id` 만 보내는 호출은 예외다** —
        탭 이동은 조직 정보일 뿐 내용이 아니라서, 내장·외부 프로그램도 옮길 수
        있다(`program_io.update_program` 참조).
        """
        try:
            from aot.space import program_io

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

    @classmethod
    def delete_program(cls, program_id=None, **extra):
        """[쓰기] 프로그램을 삭제한다. 사람 승인 필요.

        **오기입 정정용이다.** `program_io.delete_program` 이 참조 무결성을
        지킨다 — 쓰는 구획이 하나라도 있으면 거절하고 몇 건인지 알려 준다.
        쓰던 구획에서 떼려면 `modify_plot` 으로 `program_uuid` 를 비운 뒤
        다시 시도한다.
        """
        try:
            from aot.space import program_io

            if not program_id:
                return {"status": "error", "message": "program_id is required"}
            result, err = program_io.delete_program(program_id)
            if err:
                return {"status": "error", "message": err}
            return {"status": "success", "deleted": program_id}
        except Exception as e:
            logger.exception("Error in delete_program")
            return {"status": "error", "message": str(e)}

    #: list_plots/get_crop_status 공용 기본 상한. 필터 없이 부르면 활성
    #: 구획 전부가 나가는데, 큰 농장은 그것만으로 응답이 벤치 실측 중앙값
    #: 18~22K자까지 갔다(요약 필드로 줄여도 개수 자체가 크면 소용없다) —
    #: 개수 상한이 없었기 때문. 30으로는 실측 감소율이 30~40%에 그쳐(목표
    #: 4,000자·70% 미달) 10으로 낮췄다 — "한눈에 보는" 크기다.
    _PLOT_LIST_DEFAULT_LIMIT = 10

    @classmethod
    def list_plots(cls, map_id=None, zone_id=None, include_ended=False, on=None,
                       with_sensors=False, limit=None, offset=None, query=None,
                       detail=None, **extra):
        """[읽기전용] 식생 구획(작기) 목록 — 어디에 무엇이 심겨 있는가.

        기본은 **재배 중인 것만**. `include_ended=True` 면 종료된 작기까지
        준다(연작 판단용). `on='YYYY-MM-DD'` 로 과거 시점을 물을 수 있다.

        `limit`(기본 10)이 상한이다 — 넘으면 앞에서부터 그만큼만 내고
        `truncated`를 켠다. 정렬은 재배 중 먼저(종료는 뒤) → 장소 → 이름순이라
        잘려도 어느 것이 빠졌는지 예측되고, `offset` 으로 다음 쪽을 이어 본다
        (응답에 `next_offset`). 잘리면 `summary` 문장에 경고와 다음 조회 방법이
        실린다. 기본값은 응답 크기 벤치(10) 때문에 올리지 않았다. `zone_id`/`map_id` 로 좁히거나 `limit` 을 올려
        나머지를 본다. 항목 자체를 요약해도(2026-09-24) 큰 농장은 구획
        **개수**가 응답을 키운다 — 이 상한은 그 축을 막는다.

        `with_sensors=True` 면 구획마다 참조 센서(`in_plot`/`from_zone`/
        `source`)를 함께 낸다. 밸브 교차는 **포함하지 않는다** — 그쪽이 비용의
        대부분이고(실측 구획 8개: 센서 37 쿼리 · 밸브 120 쿼리) 목록에서 필요한
        일이 드물다. 밸브가 필요하면 그 구획 하나만 `get_plot` 으로 본다.

        `zone_id` 는 그 zone/site 안에서 자란(자라는) 구획만 남긴다 —
        `map_id`(지도 전체)보다 한 단계 좁은, zone 하나짜리 스코프다. `search_devices`
        로 어떤 zone에 장치가 있는지 찾아본 것과 "그 zone에 작물이 있는가"는
        다른 질문이다 — 구획은 zone 이름이 아니라 품종명으로 등록돼 이름 검색
        으로는 절대 안 잡힌다("이 zone엔 이름 매칭이 없으니 작물도 없다"고
        결론 내지 말 것, .local/plans/mcp_tool_audit_tracker.md 8번 항목 실측
        사례). 구획-zone 소속은 **저장된 값이 아니라 공간 포함으로 그때그때
        판정**한다(구획 하나가 여러 zone에 걸치면 가장 좁게 감싸는 도형 하나로
        정해진다) — `get_spatial_tree`/`resolve_target`으로 zone id를 먼저 얻을 것.

        대지(site)를 주면 **하위 구역의 구획까지** 낸다(2026-10-08). 항목마다
        `place`('3포장 > 3-1')가 실려 어느 층인지 구분된다.

        `query` 는 무엇을 기르는가로 거른다 — 작물·품종·구획 이름의 일부(띄어쓰기 무시).
        "장미 구획" 은 장소 이름이 아니라 작물이다(2026-10-14 사용자 시험: 이름 해석이
        '장미' 를 밸브 영역 도형으로 풀었다).

        `detail`: None = 예전 모양 · False = 구역·작물·경과일수·id 만(기본 상한 40, 센서를
        청하면 접지 않는다) · True = 예전 모양. 도메인 틀(`overview.crops`)이 False 를 넣는다.
        """
        try:
            from datetime import datetime
            from aot.databases.models import GeoPlot
            from aot.tools.data_tools import crop_compact as _cc
            _compact = _cc.wants_compact(detail) and not with_sensors
            from aot.space import plot_context

            as_of = None
            if on:
                try:
                    as_of = datetime.strptime(str(on)[:10], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    return {"error": "on must be YYYY-MM-DD"}

            _tgt = None
            _zref = zone_id
            if zone_id:
                # unique_id 또는 이름(3-A) — 모호하면 후보를 돌려준다.
                place, perr = cls._read_place(zone_id)
                if perr:
                    return perr
                zone_id = place.unique_id
                _tgt = (place.type, place.unique_id)

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
            from aot.space import device_membership as _dm
            _containers, _markers = {}, {}

            def _cached(m_uuid):
                if m_uuid not in _containers:
                    _containers[m_uuid] = _dm.load_containers(m_uuid)
                    _markers[m_uuid] = (_dm.load_markers(m_uuid)
                                        if with_sensors else None)
                return _containers[m_uuid], _markers[m_uuid]

            # 소속은 정본(device_membership.PlaceIndex)으로 — 대지를 물으면
            # 하위 구역의 구획까지 낸다. 예전에는 "가장 안쪽 소속이 물은 곳과
            # 같은가" 로 걸러, 대지 '3포장' 이 하위 구역 3-1·3-2 의 구획 12건을
            # 빼고 2건만 냈다(2026-10-08).
            _places = _dm.PlaceIndex()
            items = []
            _in_facility = False
            from aot.tools.name_key import name_key
            _q = name_key(query) if query else None
            for r in rows:
                if _q and not any(_q in name_key(v) for v in (
                        r.subject, r.name, getattr(r, 'variety', None)) if v):
                    continue
                _c, _mk = _cached(r.geo_id)
                if zone_id and not _places.plot_within(r, zone_id):
                    continue
                if zone_id and getattr(r, 'facility_uuid', None):
                    _in_facility = True
                item = cls._plot_brief(
                    r, with_sensors=with_sensors, with_valves=False,
                    containers=_c, markers=_mk, summary=True)
                _path = _places.plot_path(r)
                if _path and isinstance(item, dict):
                    item['place'] = _path
                items.append(item)
            # 잘릴 때 무엇이 남는지 예측되도록 정렬을 고정한다: 재배 중 먼저,
            # 그다음 장소·이름순. (종료 작기는 뒤로.)
            items.sort(key=lambda it: (
                0 if not (isinstance(it, dict) and it.get('ended_on')) else 1,
                str((it or {}).get('place') or ''),
                str((it or {}).get('subject') or '')))
            total_matched = len(items)
            _lim = int(limit) if limit else (
                _cc.COMPACT_LIMIT if _compact else cls._PLOT_LIST_DEFAULT_LIMIT)
            try:
                _off = max(0, int(offset or 0))
            except (TypeError, ValueError):
                _off = 0
            truncated = total_matched > _off + _lim
            items = items[_off:_off + _lim]
            out = {"count": len(items), "plots": items,
                   "note": ("Only plots currently growing are listed. "
                            "Pass include_ended=true for history.")
                           if not include_ended else None}
            if with_sensors:
                shared = cls._hoist_shared_sensors(items)
                out.update(shared)
            if truncated:
                out["truncated"] = True
                out["total_matched"] = total_matched
                out["next_offset"] = _off + _lim
                out["truncated_note"] = (
                    "Showing %d of %d matching plots (offset %d). Narrow with "
                    "zone_id/map_id, or call again with a higher limit or "
                    "offset=%d, for the rest." % (
                        len(items), total_matched, _off, _off + _lim))
                out["summary"] = (
                    "WARNING: list is INCOMPLETE - %d of %d plots shown "
                    "(sorted growing first, then place, then name). Do not "
                    "state totals or say a crop is absent from this list. Call "
                    "list_plots again with offset=%d (or a higher limit, or "
                    "zone_id/map_id) before summarizing."
                    % (len(items), total_matched, _off + _lim))
            elif _off:
                out["total_matched"] = total_matched
                out["summary"] = "%d plots shown (offset %d) of %d; this is the last page." % (
                    len(items), _off, total_matched)
            else:
                out["summary"] = "%d plots, complete list." % len(items)
            _zshape = _places.by_uid.get(zone_id) if zone_id else None
            if _in_facility and _zshape is not None \
                    and _zshape.type != 'facility':
                # 구획이 시설 이름으로도 조회된다는 안내(2026-10-13). 위치 도형이
                # 없는 시설 구획은 시설을 품은 장소로만 잡힌다.
                _fnote = "시설 아래 구획은 시설 이름으로도 조회"
                out["note"] = (out["note"] + " " + _fnote) if out["note"] \
                    else _fnote
            if query:
                out["query"] = query
            if query and not items:
                # 재배 중인 것만 없을 수 있다 — 예정(시작 전)·종료 구획이 맞으면 그렇다고
                # 말한다. "없다" 로만 답하면 내년 3월에 심을 장미가 사라진다(2026-10-14).
                other = 0
                if not include_ended:
                    other = sum(1 for p in GeoPlot.query.all() if any(
                        _q in name_key(v) for v in (p.subject, p.name,
                                                    getattr(p, 'variety', None)) if v))
                out["note"] = (
                    "No %splot's crop, variety or name contains '%s'." % (
                        "" if include_ended else "growing ", query)
                    + (" %d planned or finished plot(s) match — pass "
                       "include_ended=true to list them." % other if other else ""))
            elif zone_id and not items:
                out["note"] = (
                    "0 plots matched zone_id (checked by spatial containment "
                    "against every plot on its map, not by name — this is not "
                    "a search-string miss). "
                    + ("This zone has no plot growing there right now."
                       if not include_ended else
                       "This zone has no plot at all, past or present."))
            # get_plot 과 같은 규칙이되, 목록에서 실제로 걸리는 것만 싣는다.
            notes = []
            if items:
                # 안내는 응답과 함께 대화에 남아 이후 요청마다 다시 실린다 —
                # 뜻을 줄이지 말고 문장만 짧게 둔다(2026-10-10).
                notes.append(
                    "Summaries only (crop, place, period, current stage). Stage "
                    "schedule, timeline, size and capacity: get_plot. A field "
                    "missing here does not mean the plot lacks it.")
            if with_sensors and any(
                    (p.get('sensors') or {}).get('source') == 'zone' for p in items):
                notes.append(
                    "Some plots here read their ZONE's representative values, not "
                    "sensors inside the plot (sensors.source='zone'). Say so for "
                    "those plots when you report a number.")
            if any((p.get('stage') or {}).get('guidance') for p in items):
                notes.append(
                    "'stage.guidance' is THAT plot's programme instruction for its "
                    "current stage. Quote it; do not swap in generic crop advice. "
                    "It is the PLAN, not the status — whether targets are met is "
                    "get_plot's 'target_check'. Do not call a plot fine from "
                    "guidance alone.")
            elif items:
                # 지침이 하나도 없을 때야말로 지어내기 쉽다 — 그 자리에서 말한다.
                notes.append(
                    "No plot here has programme guidance for its current stage "
                    "('stage.guidance' is null throughout). Saying so is the "
                    "honest answer; do not present generic crop advice as if it "
                    "came from the programme.")
            if notes:
                out["_reading"] = notes
            if _tgt:
                cls._with_target(out, *_tgt, ref=_zref)
            return _cc.compact_list(out) if _compact else out
        except Exception as e:
            logger.exception("Error in list_plots")
            return {"error": str(e)}

    @staticmethod
    def _hoist_shared_sensors(items):
        """구획마다 반복되는 구역·기상 센서 목록을 응답 위쪽에 한 번만 싣는다.

        같은 구역의 구획은 같은 구역 센서 목록을, 같은 대지의 구획은 같은
        기상 센서 목록을 받는다. 그대로 두면 uuid 목록이 구획 수만큼 되풀이된다
        — 실측(2026-10-10, 3포장 구획 12개): 응답 6,641 토큰 중 센서가 구획당
        265, 합계 약 3,200 토큰이었고 대부분 같은 목록의 사본이었다. 응답은
        대화에 남아 이후 모든 요청에 다시 실리므로(claude.ai 파일럿: 이 응답이
        뒤 8턴 내내 실렸다) 한 번 커지면 대화 전체가 커진다.

        구획에는 참조(`zone_uuid`·`weather_site_uuid`)와 판정에 쓰는 `source`·
        `in_plot` 만 남긴다. **목록이 같을 때만** 올린다 — 같은 구역인데 목록이
        다르면(있어서는 안 되지만) 그 구획은 그대로 둔다. 조용히 한쪽으로
        합치면 어느 구획이 어떤 센서를 읽는지가 틀린다."""
        zones, weather = {}, {}
        for item in items:
            s = item.get('sensors') if isinstance(item, dict) else None
            if not isinstance(s, dict):
                continue
            z = s.get('zone_uuid')
            if z and s.get('from_zone') is not None:
                entry = {'name': s.get('zone_name'), 'kind': s.get('zone_kind'),
                         'sensors': s.get('from_zone')}
                if zones.setdefault(z, entry) == entry:
                    for k in ('from_zone', 'zone_name', 'zone_kind'):
                        s.pop(k, None)
            w = s.get('weather_site_uuid')
            if w and s.get('from_weather') is not None:
                entry = {'sensors': s.get('from_weather'),
                         'source': s.get('weather_source')}
                if weather.setdefault(w, entry) == entry:
                    for k in ('from_weather', 'weather_source'):
                        s.pop(k, None)
        out = {}
        if zones:
            out['zone_sensors'] = zones
        if weather:
            out['weather_sensors'] = weather
        if out:
            out['sensors_note'] = (
                "A plot's sensors.zone_uuid / weather_site_uuid point into "
                "zone_sensors / weather_sensors above — shared lists are given "
                "once, not per plot.")
        return out

    @classmethod
    def get_plot(cls, plot_id=None, row_spacing_cm=None,
                     plant_spacing_cm=None, edge_margin_cm=None,
                     bed_pitch_cm=None, rows_per_bed=None,
                     recent_days=None, plot_ids=None, detail=None,
                     fields=None, brief=False, device_ids=None,
                     duration_seconds=None, duration_minutes=None, **extra):
        """[읽기전용] 구획 하나의 상세 — 작물·기간·면적·치수 + 참조 센서 출처.

        `brief`·`fields` 는 도구 스키마에 없는 처리기 인자다 — 도메인 표면(detail.plot)만 쓴다(2026-10-31).
        `brief` 면 기본은 요약이다: 이름·작물·날짜·면적·현재 단계(지침·목표 포함)·`target_summary`(목표 대조의 건수).
        단계 일정·목표 대조·센서·밸브 같은 무거운 갈래는 `fields` 로 청한다(`_PLOT_MORE`, 'all' 은 예전 전체 응답).
        응답의 `_reading` 도 실린 칸에 해당하는 문장만 남는다. 안 주면(인앱 AI·측정 `soil_forecast` 아님) 예전과 같다.

        간격 두 개를 주면 `capacity_estimate`(줄 수·그루 수)까지 센다.
        `edge_margin_cm` 은 농기계 선회 공간 같은 여백을 추가로 빼고,
        `bed_pitch_cm`(고랑 포함 간격)+`rows_per_bed` 는 두둑 배치로 세게 한다
        (두둑 개수까지 낸다). 배치를 모르면 평평하게 깐 것으로 계산하되 응답의
        `capacity_estimate.ask_user` 가 배치를 확정해 **구획 노트로 남기라고**
        시킨다 — 컬럼으로 저장하지 않는 이유는 plot_context 의 주석 참조.

        조건을 한쪽만 주면 계산이 성립하지 않으므로 조용히 넘기지 않고 오류로
        말한다 — 사용자가 말한 조건이 답에 반영되지 않은 것을 아무도 모르는
        상태가 최악이다.

        ## `recent_days` — 목표가 **계속** 벗어나는가

        `target_check` 는 오랫동안 한 시점만 봤다. 그래서 "이 목표가 이 현장에
        안 맞는다" 는 사실이 이 응답에 나타난 적이 없다 — 실측(김제 3-1)에서
        야간온도가 잰 날 전부 목표를 넘겼는데, 낮에 물으면 그 항목은 아예
        목록에서 빠지기까지 했다. 기본 14일을 되돌아본다.

        **InfluxDB 를 그 기간만큼 읽는다**(실측: 0.3초 → 첫 호출 1.3초). 같은
        구획을 다시 물으면 10분 캐시로 다시 0.3초다. 정말 빠른 응답만 필요하면
        `recent_days=0` 으로 끈다 — 기본을 켜 두는 이유는, 끄면 모델이 그것을
        물어볼 이유를 알 수 없기 때문이다(없는 것은 없는 줄도 모른다).

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

        대상은 unique_id 또는 이름(재배 중인 구획의 이름·작물·품종, 3-A).
        여럿이면 `plot_ids`(최대 MAX_READ_TARGETS, 3-F).

        `detail='twin_soil'`(시범): 상세 대신 디지털트윈의 토양 수분 예측만 낸다 — 노지 구획 한 변수.
        새 도구·새 인자 이름을 늘리지 않으려고 기존 이름 `detail` 에 값 하나를 더했다(`utils/twin_soil.py`).

        `detail='water_delivered'`: 최근 `recent_days`(기본 7)일 동안 구획이 받은 물 — 일지·[현황]과 같은 숫자
        (`water_net_link.delivered_summary`). 닫힌 날은 저장값, 오늘은 읽을 때 계산한 값이다.

        `detail='water_estimate'`: 켜기 전 사전 계산(`utils/water_estimate.py`). `device_ids`(켤 Output)를 지금부터
        `duration_seconds`/`duration_minutes` 켜면 구획이 받을 물. 구획을 안 주면 Output 이 물을 대는 구획을 위치로 푼다.
        읽기 전용이다 — 장치를 움직이지 않는다. 계산이 실패하면 오류로 답한다(설계값으로 내려앉지 않는다).
        """
        if detail == 'water_estimate':
            return cls._water_estimate(plot_id, plot_ids, device_ids, duration_seconds, duration_minutes)
        tokens, err = cls._targets_arg(plot_id, plot_ids, 'plot_id')
        if err:
            return err
        if detail == 'water_delivered':
            days = recent_days if isinstance(recent_days, int) and recent_days > 0 else 7
            return cls._water_delivered_one(tokens[0], days) if len(tokens) == 1 else \
                cls._for_each_target(tokens, lambda t: cls._water_delivered_one(t, days))
        if detail == 'twin_soil':
            return cls._twin_soil_one(tokens[0]) if len(tokens) == 1 else \
                cls._for_each_target(tokens, cls._twin_soil_one)
        kw = dict(row_spacing_cm=row_spacing_cm,
                  plant_spacing_cm=plant_spacing_cm,
                  edge_margin_cm=edge_margin_cm, bed_pitch_cm=bed_pitch_cm,
                  rows_per_bed=rows_per_bed, recent_days=recent_days)
        if brief:
            kw['lean'] = fields if isinstance(fields, (list, tuple)) else ([fields] if fields else [])
        if len(tokens) == 1:
            return cls._plot_one(tokens[0], **kw)
        out = cls._for_each_target(tokens, lambda t: cls._plot_one(t, **kw))
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
    def _water_delivered_one(cls, plot_id, days):
        """구획 하나가 최근 `days` 일 받은 물(`get_plot(detail='water_delivered')`)."""
        try:
            row, perr = cls._read_plot(plot_id)
            if perr:
                return perr
            from aot.utils import water_net_link
            return dict({"status": "success"}, **water_net_link.delivered_summary(row, days))
        except Exception as e:
            logger.exception("Error in get_plot water_delivered")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _water_estimate(cls, plot_id, plot_ids, device_ids, duration_seconds, duration_minutes):
        """`get_plot(detail='water_estimate')` — 켜기 전 물량 사전 계산(읽기 전용)."""
        from aot.utils import water_estimate as WE
        try:
            seconds = float(duration_seconds or 0) or float(duration_minutes or 0) * 60
            if seconds <= 0:
                return {"status": "error", "reason_code": "missing_argument",
                        "message": "A run time is needed: duration_minutes (e.g. 10) or duration_seconds."}
            outs, ids = [], []
            if device_ids or not (plot_id or plot_ids):
                tokens, err = cls._targets_arg(None, device_ids, 'device_ids')
                if err:
                    return err
                for token in tokens:
                    row, _kind, derr = cls._read_device(token, kinds=('output',))
                    if derr:
                        return derr
                    outs.append(row)
                ids = [o.unique_id for o in outs]
            if plot_id or plot_ids:
                tokens, err = cls._targets_arg(plot_id, plot_ids, 'plot_id')
                if err:
                    return err
                pairs = []
                for token in tokens:
                    plot, perr = cls._read_plot(token)
                    if perr:
                        return perr
                    own = ids or list(WE.watering_outputs(plot))
                    if not ids and len(own) > 1:
                        return {"status": "error", "plot": plot.unique_id,
                                "message": "Several outputs water this plot; name the ones to run in device_ids.",
                                "outputs": own[:8]}
                    pairs.append((plot, own))
            else:
                pairs = WE.plots_for_outputs(ids)
                if not pairs:
                    return {"status": "error", "message": "No plot is watered by these outputs."}
            results = [WE.estimate_or_error(plot, own, seconds) for plot, own in pairs]
            return results[0] if len(results) == 1 else {"count": len(results), "results": results}
        except WE.EstimateError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.exception("Error in get_plot water_estimate")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _twin_soil_one(cls, plot_id):
        """구획 하나의 트윈 토양 수분 예측(`get_plot(detail='twin_soil')`)."""
        try:
            row, perr = cls._read_plot(plot_id)
            if perr:
                return perr
            from aot.utils import twin_soil
            return twin_soil.soil_moisture(row)
        except Exception as e:
            logger.exception("Error in get_plot twin_soil")
            return {"status": "error", "message": str(e)}

    @classmethod
    def _plot_one(cls, plot_id, row_spacing_cm=None, plant_spacing_cm=None,
                  edge_margin_cm=None, bed_pitch_cm=None, rows_per_bed=None,
                  recent_days=None, lean=None):
        """구획 하나. `lean` 이 None 이면 예전 전체 응답, 목록(청한 갈래, 비어도 됨)이면 요약 + 그 갈래."""
        try:
            row, perr = cls._read_plot(plot_id)
            if perr:
                return perr
            try:
                brief = cls._plot_brief(
                    row, with_sensors=True,
                    row_spacing_cm=row_spacing_cm,
                    plant_spacing_cm=plant_spacing_cm,
                    edge_margin_cm=edge_margin_cm,
                    bed_pitch_cm=bed_pitch_cm,
                    rows_per_bed=rows_per_bed)
            except ValueError as ve:
                return {"error": str(ve)}
            cls._thin_plot_detail(brief)
            cls._drop_ai_excluded_sensors(brief)
            _check = cls._stage_target_check(
                brief, plot_row=row, recent_days=recent_days)
            if _check:
                brief['target_check'] = _check
            if lean is not None:
                got = cls._plot_lean(brief, lean)
                if got is not None:
                    return got
            return {"plot": brief,
                    "_reading": cls._plot_reading_notes(brief)}
        except Exception as e:
            logger.exception("Error in get_plot")
            return {"error": str(e)}

    #: `fields` 로 더 청할 수 있는 갈래 → 전체 응답의 칸. 요약은 이 칸들을 싣지 않는다(#384 `detail.device` 와 같은 방식).
    _PLOT_MORE = {
        'target_check': ('target_check',),
        'stage_schedule': ('stage_schedule', 'stage_schedule_note'),
        'stage_history': ('stage_history',),
        'sensors': ('sensors',),
        'valves': ('valves',),
        'timeline': ('timeline', 'timeline_note'),
        'facility_control': ('facility_control',),
    }

    @staticmethod
    def _target_summary(check):
        """목표 대조 → 건수만. 허용 폭이 데이터에 없으므로 '벗어났다/괜찮다' 를 매기지 않는다 —
        대조한 항목 수, 잰 값이 없는 항목 수, 최근 며칠 내내 같은 쪽으로 빗나간(`one_way`) 항목 수."""
        if not isinstance(check, dict):
            return None
        out = {"state": check.get('state'), "compared": len(check.get('rows') or [])}
        if check.get('no_reading_for'):
            out["no_reading"] = len(check['no_reading_for'])
        one_way = [d for d in ((check.get('recent') or {}).get('drift') or [])
                   if isinstance(d, dict) and d.get('one_way')]
        if one_way:
            out["one_way_misses"] = len(one_way)
        return out

    @classmethod
    def _plot_lean(cls, brief, fields):
        """get_plot 요약 — 전체 응답에서 무거운 갈래(`_PLOT_MORE`)를 빼고 `fields` 로 청한 것만 되돌린다.

        'all' 이면 None(= 예전 전체 응답). 값은 전체 응답과 같은 것을 옮길 뿐이다. 칸을 지우는 쪽이라
        새로 생긴 칸은 요약에도 실린다(빠짐보다 낫다). `_reading` 은 **실린 칸에 해당하는 문장만**(`_plot_reading_notes` 가
        칸의 있고 없음으로 고르므로 요약에서는 목표 대조·센서·단계 일정 문장이 빠진다)."""
        want = [str(f).strip().lower() for f in (fields or []) if f not in (None, '')]
        if 'all' in want:
            return None
        unknown = [w for w in want if w not in cls._PLOT_MORE and w != 'summary']
        view = dict(brief)
        for name, cols in cls._PLOT_MORE.items():
            if name not in want:
                for col in cols:
                    view.pop(col, None)
        if view.get('stage_proposal') is None:
            view.pop('stage_proposal', None)
        if 'target_check' not in want and brief.get('target_check') is not None:
            view = dict(view, target_summary=cls._target_summary(brief['target_check']))
        left = [n for n, cols in cls._PLOT_MORE.items()
                if n not in want and cols[0] in brief and brief.get(cols[0]) not in (None, [], {})]
        nxt = {}
        if left:
            nxt["more"] = "fields=[%s] adds them (all = the full answer)" % ", ".join(left)
        if unknown:
            nxt["unknown_fields"] = unknown
        out = {"status": "success"}
        if nxt:
            out["next"] = nxt
        out["plot"] = view
        out["_reading"] = cls._plot_reading_notes(view)
        return out

    @staticmethod
    def _drop_ai_excluded_sensors(brief):
        """'AI 판단에 포함' 을 끈 장치를 구획의 센서·기상원 목록에서 뺀다.

        `sensors_for_plot`·`weather_device_ids` 는 지도 화면도 쓰므로 거기서
        거르지 않는다(사람에게는 보여야 한다). AI 쪽에서는 그 장치를 읽을 수도
        없는데 목록에만 있어, 모델이 이름을 대고 값을 물으면 거절이 돌아왔다
        (2026-10-09: 기상청 장치가 from_weather 에 표시 없이 실렸다). 뺀 수는
        `ai_excluded` 로 남긴다 — 없는 것과 뺀 것은 다르다."""
        sensors = (brief or {}).get('sensors')
        if not isinstance(sensors, dict):
            return
        try:
            from aot.services.resolvers.device_resolver import ai_excluded_ids
            hidden = ai_excluded_ids()
        except Exception:                                   # noqa: BLE001
            return
        if not hidden:
            return
        dropped = 0
        for key, val in list(sensors.items()):
            if isinstance(val, list) and val and all(isinstance(x, str) for x in val):
                kept = [x for x in val if x not in hidden]
                dropped += len(val) - len(kept)
                sensors[key] = kept
        if dropped:
            sensors['ai_excluded'] = dropped

    @classmethod
    def _stage_target_check(cls, brief, plot_row=None, recent_days=None):
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
                              'shape': d.get('shape'),
                              'when': d.get('when'), 'value': v, 'source': 'stage'})

        if not items:
            # 진행 중이 아닌 단계(끝을 지남·아직 시작 전)는 목표를 일부러 싣지
            # 않는다 — 지난 단계의 목표를 지금 목표로 읽으면 제어가 엉뚱한 값을
            # 따른다. 그때 "프로그램에 목표가 없다" 고 말하면 거짓이다(2026-10-09
            # 실측: 콩 프로그램의 '성숙' 은 목표 4개를 갖고 있었다).
            st = stage.get('state')
            if st and st != 'running':
                return {'state': 'not_compared', 'stage_state': st,
                        'note': (
                            "The plot is past the programme's last stage, so its "
                            "targets are no longer compared — the programme does "
                            "have them. Say that the planned season has ended, "
                            "not that targets are missing."
                            if st == 'past_end' else
                            "The plot has not reached its first stage yet, so no "
                            "stage targets apply. Do not say the programme lacks "
                            "targets.")}
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
        # sensors_for_plot 의 우선순위(구획 → bay → 시설 → zone)와 같은 순서로
        # 좁은 스코프를 고른다 — 시설 구획은 'in_plot' 이 항상 비어 있어 이
        # 없이는 bay/시설 센서의 현재값이 대조에서 통째로 빠진다.
        narrow = (sensors.get('in_plot') or sensors.get('in_bay')
                  or sensors.get('from_facility') or [])
        # 대조에 실제로 쓰이는 measurement 만 읽는다. 예전에는 이 구획의
        # **모든 채널**을 하나씩 읽어(실측 25회) `rssi`·`snr`·전위처럼 목표와
        # 무관한 값까지 InfluxDB 를 왕복했다.
        #
        # ⚠ **채널이 아니라 measurement 기준으로 좁힌다.** 같은 측정을 재는
        #   다른 센서를 `others` 로 내보내는 계약이 있으므로, 쓰는 measurement
        #   는 **모든 센서에서** 읽어야 한다.
        wanted_meas = set()
        for t in items:
            if t.get('observable') is False:
                continue
            _m = str(t.get('measurement') or t.get('key') or '').strip().lower()
            if _m:
                wanted_meas.add(_m)
        current = cls._latest_by_measurement(
            narrow, sensors.get('from_zone') or [], wanted=wanted_meas or None)

        rows, no_reading, curves, off_period, unmeasurable = [], [], [], [], []
        not_comparable = []
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
                    # `measurement` 를 함께 남긴다 — 아래에서 "직전 그
                    # 시간대의 값" 을 찾는 열쇠가 이것이다.
                    off_period.append({
                        'label': label, 'target': t['value'], 'unit': unit,
                        'applies': when,
                        'measurement': t.get('measurement') or t.get('key')})
                    continue

            # 하루 적산 목표(DLI 등, shape='daily')는 순간 채널 값과 견주지 않는다.
            # 22 mol 목표를 순간 일사 0.0 과 빼면 차원이 다른 뺄셈이라 delta -22
            # 같은 틀린 숫자가 나온다(일지도 같은 이유로 'daily-shape' 로 막는다).
            if t.get('shape') == 'daily':
                not_comparable.append({
                    'key': t.get('key'), 'label': label,
                    'target': t['value'], 'unit': unit,
                    'status': 'not_comparable_instant',
                    'reason': ('daily cumulative target; cannot be compared with '
                               'an instantaneous reading, so no delta is given')})
                continue

            meas = str(t.get('measurement') or t.get('key')).strip().lower()
            # 흙 목표(사용자가 만든 '지온' 항목 등)만 흙 채널과 견준다. 고정
            # 항목(주·야간 온도·습도·VPD)은 전부 공기다.
            if cls._is_soil_text(t.get('key'), t.get('label')):
                meas = 'soil:' + meas
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
            if got.get('channel'):
                row['channel'] = got['channel']
            if got.get('others'):
                # 다른 센서들의 값 전체(이름·값·채널)는 안 싣는다 — 실측:
                # 구획 하나의 target_check 가 4,657자였고 이 열이 그중 큰
                # 몫이었다. "여럿이 있다/갈린다" 는 사실만 남기고, 실제
                # 값이 필요하면 get_zone_sensor_summary/get_sensor_detail 로
                # 그 구역·센서를 짚어 보게 한다.
                row['other_sensors_count'] = len(got['others'])
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
        if not_comparable:
            out['not_comparable_instant'] = not_comparable
        if unmeasurable:
            out['not_measurable_here'] = unmeasurable
        if no_reading:
            out['no_reading_for'] = no_reading

        # ── 최근 며칠은 어땠나 ───────────────────────────────────────────
        #
        # 위까지는 전부 **한 시점**이다. 그래서 "이 목표가 이 현장에서 계속
        # 안 맞는다" 는 사실이 이 응답에 나타난 적이 없었다 — 실측(김제 3-1):
        # 야간온도가 잰 날 전부 목표를 넘겼는데, 낮에 물으면 그 항목은
        # `not_this_period` 로 빠져 **목록에서 사라지기까지 했다.**
        #
        # 일지와 **같은 함수로** 센다(`plot_journal.recent_target_drift` →
        # `target_drift`). 여기서 따로 세면 같은 구획을 두고 화면과 AI 가
        # 다른 숫자를 말한다.
        recent = cls._recent_drift(plot_row, recent_days)
        if recent:
            # 화면이 쓰는 필드를 그대로 넘기지 않고 **말할 것만** 남긴다 —
            # 응답에 실리는 글자가 곧 매 호출의 비용이다(극값·on_target 은
            # 문장으로 옮길 일이 없다).
            # 항목마다(day/night 온도 등) 그 안의 센서별 내역(`sensors`)은
            # 뺀다 — 실측: 구획 하나의 target_check 4,657자 중 큰 몫이 이
            # 열이었다. 몇 센서가 갈렸는지는 `agree`('mixed'면 갈림)로 이미
            # 말하므로 뜻은 남는다 — 어느 센서가 어떻게 갈렸는지는
            # get_zone_sensor_summary/get_sensor_detail 로 그 구역·기간을
            # 다시 짚어 본다.
            drift = [{
                'label': d['label'], 'when': d.get('when'),
                'unit': d.get('unit_label') or d.get('unit'),
                'days': d['days'], 'days_hi': d['days_hi'],
                'above': d['above'], 'above_hi': d['above_hi'],
                'below': d['below'], 'below_hi': d['below_hi'],
                'mean': d['mean'], 'mean_hi': d['mean_hi'],
                'one_way': d['one_way'], 'agree': d.get('agree'),
                'sensor_count': len(d.get('sensors') or []),
            } for d in (recent.get('drift') or [])]
            out['recent'] = {
                'days': recent['days'], 'from': recent['from'],
                'to': recent['to'], 'drift': drift}
            # 지금은 해당 없는 항목에 **직전 그 시간대의 값**을 붙인다.
            # 붙이지 않으면 "지금은 해당 없음" 이 "모른다" 로 읽힌다.
            for item in off_period:
                key = '%s|%s' % (str(item.get('measurement') or '').strip().lower(),
                                 item.get('applies') or '')
                seen = (recent.get('latest') or {}).get(key)
                if not seen:
                    continue
                item['last_seen'] = dict(seen)
                try:
                    item['last_seen']['delta'] = round(
                        float(seen['value']) - float(item['target']), 2)
                except (TypeError, ValueError):
                    pass

        # 규칙(허용 폭 지어내지 않기·one_way·mixed·not_this_period)은 `_plot_reading_notes` 가 이미 말한다 —
        # 여기는 이 표를 읽는 법만(같은 말을 두 번 싣던 문단을 줄였다, 2026-10-28 점검).
        out['note'] = ("'delta' = current minus target; there is no tolerance band in the data — "
                       "do NOT invent one. Check 'sensor' and 'channel' per row (air vs soil can "
                       "share a measurement; 'other_sensors_count' = others not shown, read them "
                       "with get_zone_sensor_summary/get_sensor_detail). 'recent' counts the last N "
                       "days per sensor: 'days'..'mean' = LOW end of the sensor range, '*_hi' = "
                       "high end; rows can differ only by 'when' (day/night); it does NOT separate "
                       "soil channels; 'follows_curve' targets are counted too; 'sensor_count' "
                       "replaces the per-sensor breakdown. 'one_way' = every sensor missed the same "
                       "way on every day, still no tolerance band: report the counts, do not grade.")
        return out

    RECENT_DRIFT_DEFAULT_DAYS = 14

    @classmethod
    def _recent_drift(cls, plot_row, recent_days=None):
        """구획 → 최근 N일 목표 이탈 요약. 못 내거나 꺼져 있으면 None."""
        if plot_row is None:
            return None
        try:
            days = (cls.RECENT_DRIFT_DEFAULT_DAYS
                    if recent_days is None else int(recent_days))
        except (TypeError, ValueError):
            days = cls.RECENT_DRIFT_DEFAULT_DAYS
        if days <= 0:
            return None
        try:
            from aot.aot_flask.geo import plot_journal as PJ
            return PJ.recent_target_drift(plot_row, days=days)
        except Exception as e:                                  # noqa: BLE001
            logger.debug('[StageTargetCheck] recent drift unavailable: %s', e)
            return None

    # 채널 이름에 이 낱말이 있으면 **흙(배지) 속을 재는 채널**로 본다. 측정
    # 이름만으로는 못 가른다 — 토양 노드는 공기 온·습도 채널과 토양온도 채널을
    # 함께 갖고, 둘 다 'temperature' 다(`auto_vpd` 가 같은 이유로 채널 순서에
    # 기댄다). 채널 이름은 사람이 붙인 것이라 언어가 섞인다: 화면이 지원하는
    # 23개 언어(+영어)의 흙·땅·근권 낱말과 배지 재료 이름을 **한 목록**에 둔다.
    # 배터리 채널을 이름으로 알아보는 `facility_sensors._BATTERY_NAME_TOKENS`
    # 와 같은 방식이다.
    #
    # 표기 규칙(`_soil_word_patterns`):
    #   - 띄어쓰기가 있는 문자(라틴·키릴)는 **낱말 단위**로만 맞춘다 — 'sol'
    #     (프랑스어 흙)이 'solar' 에, 'jord'(노르웨이어)가 'jordbær'(딸기)에
    #     걸리면 안 된다. 경계는 **글자**로 판정한다('soil_temp' 의 '_' 는 경계).
    #   - 끝에 '*' 를 붙인 것은 **낱말 앞머리**로 맞춘다 — 합성어·굴절이 붙는
    #     말('Bodentemperatur', 'почвы', 'talajhő…').
    #   - 띄어쓰기가 없는 문자(한·중·일·태국·데바나가리)는 부분 문자열로
    #     맞춘다('토양온도', '地温'). 한 글자짜리 '土' 처럼 다른 낱말('土曜')
    #     안에 흔한 것은 넣지 않는다.
    _SOIL_CHANNEL_WORDS = (
        # en
        'soil*', 'ground', 'root zone', 'rootzone', 'root-zone', 'substrate*',
        'rockwool', 'stonewool', 'coir', 'cocopeat', 'coco peat', 'growing medium',
        # de
        'boden*', 'erde', 'substrat*', 'wurzelraum*', 'steinwolle', 'kokos*',
        # es / pt / it
        'suelo', 'sustrato', 'tierra', 'lana de roca', 'fibra de coco',
        'zona radicular', 'solo', 'lã de rocha', 'suolo', 'terreno',
        'substrato', 'lana di roccia', 'fibra di cocco', 'zona radicale',
        # fr
        'sol', 'terre', 'laine de roche', 'fibre de coco', 'zone racinaire',
        # nl / sv / nn
        'bodem*', 'grond*', 'substraat', 'steenwol', 'jord', 'jordtemp*',
        'jordfukt*', 'stenull', 'steinull',
        # pl / lt / hu / tr / id / vi
        'gleb*', 'podłoż*', 'grunt*', 'wełna mineralna', 'dirvožem*',
        'talaj*', 'kőzetgyapot', 'toprak*', 'toprağ*', 'taş yünü',
        'tanah', 'media tanam', 'sabut kelapa', 'đất', 'giá thể', 'vùng rễ',
        # ru / uk / sr
        'почв*', 'грунт*', 'ґрунт*', 'субстрат*', 'минват*', 'мінват*',
        'земљишт*', 'тло', 'zemljišt*', 'tlo', 'supstrat*',
        # ko / ja / zh / zh_Hant
        '토양', '지온', '배지', '근권', '흙', '암면', '코코피트', '상토',
        '土壌', '地温', '培地', '根域', 'ロックウール', 'ココピート',
        '土壤', '基质', '根区', '岩棉', '椰糠', '地溫', '基質', '根區',
        # th / hi
        'ดิน', 'วัสดุปลูก', 'मिट्टी', 'मृदा',
    )

    _soil_regex = None

    @classmethod
    def _soil_word_patterns(cls):
        if cls._soil_regex is None:
            import re
            parts = []
            for w in cls._SOIL_CHANNEL_WORDS:
                prefix = w.endswith('*')
                word = w.rstrip('*').lower()
                # 라틴(베트남어 확장 포함)·키릴 = 띄어 쓰는 문자.
                spaced = all(ch.isspace() or ord(ch) < 0x0590
                             or 0x1E00 <= ord(ch) <= 0x1EFF for ch in word)
                body = re.escape(word)
                if not spaced:
                    parts.append(body)
                elif prefix:
                    parts.append(r'(?<![^\W\d_])' + body)
                else:
                    parts.append(r'(?<![^\W\d_])' + body + r'(?![^\W\d_])')
            cls._soil_regex = re.compile('|'.join(parts))
        return cls._soil_regex

    @classmethod
    def _is_soil_text(cls, *texts):
        low = ' '.join(str(t or '') for t in texts).lower()
        return bool(low.strip()) and bool(cls._soil_word_patterns().search(low))

    _module_channel_names_cache = {}

    @classmethod
    def _module_channel_name(cls, input_row, channel):
        """사용자가 채널 이름을 비워 둔 경우 **모듈이 정한 채널 이름**
        (`measurements_dict[ch]['name']`, 예: 'Soil Temperature'). 없으면 ''."""
        dev = getattr(input_row, 'device', None) if input_row is not None else None
        if not dev:
            return ''
        cache = cls._module_channel_names_cache
        if dev not in cache:
            names = {}
            try:
                from aot.utils.inputs import parse_input_information
                info = (parse_input_information() or {}).get(dev) or {}
                for ch, meta in (info.get('measurements_dict') or {}).items():
                    nm = (meta or {}).get('name')
                    if nm:
                        names[str(ch)] = nm
            except Exception:
                names = {}
            cache[dev] = names
        nm = cache[dev].get(str(channel))
        return str(nm).strip() if nm else ''

    @classmethod
    def _latest_by_measurement(cls, in_plot_ids, zone_ids=None, wanted=None):
        """측정 종류별 최신값 — {measurement: {'value','at','sensor','others'}}.

        `wanted` 를 주면 그 measurement 만 읽는다(없으면 전부 — 다른 호출부의
        동작을 바꾸지 않는다). 채널이 아니라 **measurement** 로 좁히는 것이
        핵심이다: 같은 측정을 여러 센서가 재면 나머지를 `others` 로 내보내야
        하므로, 쓰는 measurement 는 모든 센서에서 읽어야 한다.

        구획 안 센서를 구역 폴백보다 **먼저** 본다(sensors_for_plot 의 우선순위와
        같다). 평균을 내지 않는 이유는 구획 안 센서와 구역 대표 센서가 섞이면
        평균이 어느 쪽도 아닌 값이 되기 때문이고, 같은 측정을 여러 센서가
        재면 나머지를 `others` 로 함께 낸다 — 실측에서 공기 온도 목표가 토양
        센서 값과 비교됐다. 어느 센서인지 보이지 않으면 그것을 알 길이 없다.

        **흙 속을 재는 채널은 따로 둔다**(`soil:<measurement>` 키). 채널 이름이
        토양·지온 등을 말하면(`_is_soil_text`) 공기 쪽 후보에 섞지 않는다 —
        벤치(26-09-23)에서 토양온도 채널이 공기 온도 행에 장치 이름만 달고
        끼어 있었다. 버리지 않고 따로 두는 것은 흙 목표를 둔 프로그램이 그
        값을 써야 하기 때문이다. 각 후보에 **채널 이름**(`channel`)을 싣는다:
        같은 장치가 두 번 나오면 그것 말고는 무엇이 무엇인지 알 길이 없다.
        """
        out = {}
        try:
            from datetime import datetime, timezone

            from aot.databases.models import Conversion, DeviceMeasurements, Input
            from aot.utils.influx import (bulk_key, query_last_values_bulk_status,
                                          read_influxdb_list)
            from aot.utils.system_pi import return_measurement_info

            ordered = list(in_plot_ids or []) + [d for d in (zone_ids or [])
                                                 if d not in set(in_plot_ids or [])]
            if not ordered:
                return out
            rank = {d: n for n, d in enumerate(ordered)}
            inputs = {i.unique_id: i for i in Input.query.filter(
                Input.unique_id.in_(ordered)).all()}
            names = {k: i.name for k, i in inputs.items()}

            dms = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id.in_(ordered)).all()

            # 변환 정의를 **한 번에** 읽는다. 예전에는 채널마다 조회해
            # 채널 수만큼 DB 를 왕복했다(N+1).
            conv_ids = {m.conversion_id for m in dms if m.conversion_id}
            convs = {}
            if conv_ids:
                convs = {c.unique_id: c for c in Conversion.query.filter(
                    Conversion.unique_id.in_(conv_ids)).all()}

            want = {str(w).strip().lower() for w in (wanted or [])} or None

            # 읽을 채널을 먼저 정하고 **한 번에** 묻는다. 예전에는 채널마다
            # 왕복해, 대조 하나에 InfluxDB 를 13번 갔다(4-A 로 25 → 13 이 된
            # 뒤의 수치다). `query_last_values_bulk` 가 device+unit 합집합으로
            # 한 번 물어 계열마다 `last()` 를 내주므로 **1회**면 된다 —
            # 지도 위젯이 같은 이유로 이미 쓰고 있다.
            picks = []
            ch_label = {}
            for m in dms:
                conv = convs.get(m.conversion_id) if m.conversion_id else None
                channel, unit, meas = return_measurement_info(m, conv)
                # 변환(conversion)이 걸린 채널은 meas 가 None 이다 — 센서 요약처럼
                # 원래 측정 종류(m.measurement)를 목록 키로 쓰고, Influx 질의에는
                # 원래 meas(None 허용)를 넘긴다. 예전엔 이 채널이 통째로 사라져
                # 온도만 읽기 불가가 됐다(리허설 F9).
                disp_meas = meas or m.measurement
                if not unit or not disp_meas:
                    continue
                # 대조에 안 쓰이는 채널은 InfluxDB 까지 가지 않는다 — 좁히면
                # 묻는 unit·device 집합도 함께 작아진다.
                if want is not None and str(disp_meas).strip().lower() not in want:
                    continue
                picks.append((m.device_id, unit, channel, meas, disp_meas))
                # 사용자가 채널 이름을 비워 두면 모듈이 정한 이름으로 본다 —
                # 토양 노드의 흙 채널이 이름 없이 공기 목표에 끼는 것을 막는다.
                ch_label[(m.device_id, channel, disp_meas)] = (
                    (m.name or '').strip()
                    or cls._module_channel_name(inputs.get(m.device_id), m.channel))

            # `ok` 가 False 면 **쿼리가 못 돌았다**는 뜻이다. 그것과 "돌았는데
            # 그 계열에 값이 없다" 를 가르지 않으면, 값이 없는 정상 상태에서
            # 채널마다 다시 묻는 옛 경로로 통째로 되돌아간다.
            bulk, ok = query_last_values_bulk_status(
                [(u, d, c, ms) for d, u, c, ms, _dm in picks], past_sec=3600)

            def _latest(dev, unit, channel, meas):
                # (시각, 값) 또는 None.
                if ok:
                    hit = bulk.get(bulk_key(unit, dev, channel, meas))
                    if not hit or hit[1] is None:
                        return None
                    return datetime.fromtimestamp(hit[0], tz=timezone.utc), hit[1]
                rows = read_influxdb_list(dev, unit, channel, measure=meas,
                                          duration_sec=3600, datetime_obj=True)
                if not rows or rows[-1][1] is None:
                    return None
                return rows[-1][0], rows[-1][1]

            from aot.utils.timekit import iso_at
            _tzc = {}
            found = {}
            for dev, unit, channel, meas, disp_meas in picks:
                got = _latest(dev, unit, channel, meas)
                if got is None:
                    continue
                at, value = got
                label = ch_label.get((dev, channel, disp_meas)) or ''
                key = str(disp_meas).strip().lower()
                if cls._is_soil_text(label):
                    key = 'soil:' + key
                # 장치 위치 시각 ISO. 예전엔 str(UTC datetime) 이라 '…+00:00'
                # 에 공백 구분이었고, 같은 응답의 다른 날짜(구획 현지)와 기준이
                # 갈렸다(2026-10-09).
                cand = {'value': value, 'at': iso_at(at, dev, _tzc),
                        'sensor': names.get(dev, dev),
                        '_rank': rank.get(dev, 99)}
                if label:
                    cand['channel'] = label
                found.setdefault(key, []).append(cand)

            def _pub(c, *fields):
                d = {f: c[f] for f in fields}
                if c.get('channel'):
                    d['channel'] = c['channel']
                return d

            for meas, cands in found.items():
                cands.sort(key=lambda c: c['_rank'])
                best = cands[0]
                out[meas] = _pub(best, 'value', 'at', 'sensor')
                rest = [_pub(c, 'sensor', 'value') for c in cands[1:]]
                if rest:
                    out[meas]['others'] = rest
        except Exception as e:
            logger.debug("[StageTargetCheck] latest values unavailable: %s", e)
        return out

    #: confirm_plot_stage 와 reschedule_plot_stage 중 무엇을 쓰나 — 둘의 설명이
    #: stage_proposal 이 null 일 때 서로 어긋나 모델이 골라내지 못했다(재측정
    #: lat_20). 기준은 **이미 일어났는가** 하나다. 도구 설명·응답이 이 문장을 쓴다.
    STAGE_TOOL_RULE = (
        "Stage tools: a change that ALREADY happened (the grower says so, or "
        "'stage_proposal' suggests it) -> confirm_plot_stage, stage_key from "
        "'stage_proposal' or 'stage_schedule', started_on = the day it happened. "
        "A boundary still AHEAD (delay, bring forward, 'raise seedlings 20 days') "
        "-> reschedule_plot_stage.")

    @classmethod
    def _plot_reading_notes(cls, brief):
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
        if (brief.get('sensors') or {}).get('ai_excluded'):
            notes.append(
                "sensors.ai_excluded devices were left out because their 'include "
                "in AI' setting is off — they exist but you cannot read them. Do "
                "not say the plot has no such sensor.")

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
        # 습도 목표는 **공기** 상대습도다. 벤치(26-09-23)에서 이 행의 토양
        # 노드 습도 채널(62%)을 흙 수분으로 읽은 답이 나왔다 — 실제 흙 수분은
        # 22~25% 였다. 흙 수분은 목표 대조에 없으니 어디서 읽는지 말한다.
        if any(str(r.get('key') or '') == 'rh'
               or str(r.get('label') or '').lower() == 'humidity'
               for r in (_tc.get('rows') or [])):
            notes.append(
                "The 'Humidity' row in 'target_check' is AIR relative humidity, "
                "even when the sensor's name mentions soil — it is NOT soil "
                "moisture. Soil moisture is measurement "
                "'volumetric_water_content' and is not in target_check: read it "
                "with get_zone_sensor_summary(measurement_type="
                "'volumetric_water_content').")
        # 한 시점만 보면 "오늘 좀 높네" 로 끝난다. 며칠째 같은 쪽으로 벗어나고
        # 있다는 것은 **그 사람이 받아야 할 발견**이다 — 문헌 기준의 목표가 이
        # 현장에서 성립하지 않는다는 뜻일 수 있고, 그러면 고칠 것은 현장이
        # 아니라 목표 쪽이다.
        _recent = _tc.get('recent') or {}
        if _recent.get('drift'):
            notes.append(
                "'target_check.recent' counts the last %d days. A row with "
                "'one_way' missed the same way on EVERY day every sensor "
                "measured — say that out loud with the counts; it may mean the "
                "programme's target does not hold at this site, which is the "
                "grower's call to make, not yours. Where agree='mixed' the "
                "sensors disagree: name both, never average them or pick one. "
                "'not_this_period' rows carry 'last_seen' from the window they "
                "do apply to — use it instead of saying you cannot tell."
                % _recent.get('days', 0))
        elif _tc.get('state') == 'no_targets':
            notes.append(
                "'target_check' says this programme has no target values for the "
                "current stage. That is why suitability cannot be judged — say that, "
                "and that filling them in on the programme would make it answerable.")

        _chk = brief.get('end_check') or {}
        if _chk.get('state') in ('schedule_earlier', 'schedule_later') or _chk.get('note'):
            notes.append(
                "'end_check' compares the grower-entered expected_end_on with the "
                "stage schedule's last day. The entered date wins; if state is not "
                "'aligned' (or 'note' is present) mention the gap once. "
                "stage.days_left_in_stage counts to the END OF THAT STAGE, not to "
                "expected_end_on (use days_to_expected_end).")
        if brief.get('expected_end_unknown'):
            notes.append(
                "expected_end_unknown: the last stage has no length, so no end date "
                "can be derived - do not invent one; ask the grower.")
        if brief.get('no_program'):
            notes.append("'no_program': no programme is assigned, so there is no "
                         "stage. Say so; do not guess a stage.")
        stage = brief.get('stage') or {}
        if stage and stage.get('state') == 'past_end':
            notes.append(
                "stage.state is 'past_end': the programme's LAST stage ('%s') ended "
                "%s ago, but the plot itself has not been ended. The guidance shown "
                "is that last stage's. Say both — e.g. it is past the planned "
                "harvest window — and do not call it a new stage."
                % (stage.get('name'),
                   ('%s day(s)' % stage['days_past']) if stage.get('days_past') is not None
                   else ('%s GDD' % stage.get('gdd_past'))))
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

        # 단계 사건 도구 두 개의 경계(P3). 설명에도 같은 규칙을 한 줄로 둔다.
        if 'stage_schedule' in brief or 'stage_proposal' in brief:
            notes.append(cls.STAGE_TOOL_RULE + (
                " 'stage_proposal' is null here — nothing is suggested, so "
                "confirm only a change the grower says happened."
                if brief.get('stage_proposal') is None and 'stage_proposal' in brief
                else ""))

        if any(v.get('unassigned') for v in (brief.get('valves') or [])):
            notes.append(
                "Some ground in this plot has no irrigation valve assigned "
                "(valves[].unassigned=true) — it cannot be watered yet.")

        if brief.get('scale_unavailable'):
            notes.append(
                "'scale_unavailable' applies — do not estimate capacity from "
                "floor area for this plot.")
        return notes

    @classmethod
    def get_plot_history(cls, plot_id=None, zone_id=None, map_id=None, **extra):
        """[읽기전용] 이 자리에 무엇이 있었나 — 연작 장해·윤작 판단의 근거.

        기준은 구획(`plot_id`) 또는 구역(`zone_id`)의 기하이고, 그와 면적이
        겹치는 작기를 지난 것까지 전부 돌려준다.
        """
        try:
            from aot.databases.models import GeoPlot, GeoShape
            from aot.space import plot_context

            geom, geo_id = None, map_id
            if plot_id:
                src = GeoPlot.query.filter_by(unique_id=plot_id).first()
                if src is None:
                    return {"error": f"plot not found: {plot_id}"}
                geom, geo_id = plot_context.geometry_of(src), src.geo_id
            elif zone_id:
                z = GeoShape.query.filter_by(unique_id=zone_id).first()
                if z is None:
                    # 이름도 받는다 — get_energy_report·get_anomalies 는 받는데 여기만 id 뿐이었다(2026-11-03).
                    z, _perr = cls._read_place(zone_id)
                    if z is None:
                        return _perr or {"error": f"zone not found: {zone_id}"}
                geom, geo_id = plot_context.geometry_of(z), z.geo_id
            else:
                return {"error": "plot_id or zone_id is required"}

            pairs = plot_context.plots_overlapping(geo_id, geom)
            items = []
            for row, overlap in pairs:
                d = cls._plot_brief(row, summary=True)
                d['overlap_m2'] = round(overlap, 1)
                items.append(d)
            return {"count": len(items), "history": items}
        except Exception as e:
            logger.exception("Error in get_plot_history")
            return {"error": str(e)}

    @classmethod
    def list_plot_journals(cls, target_type=None, target_id=None, limit=None,
                           **extra):
        """[읽기전용] 저장된 일지 목록 — 제목·기간만, 본문은 뺀다.

        **대상은 선택이다.** 비우면 전체 목록이다 — "저장된 일지 보여줘" 에
        답하려고 먼저 구획 uuid 를 알아내야 했다(화면의 허브는 전체를 보여
        주는데 도구만 못 봤다).

        일지는 생성 시점의 사실을 뜬 스냅샷이다(재계산하지 않는다). `journal_id`
        는 이 목록에서 얻어 `get_plot_journal` 에 그대로 넘기는 **내부 연결용
        값**이지, 사람에게 읽어 줄 정보가 아니다 — 응답할 때는 제목·기간으로
        말하고 id 를 대화에 그대로 옮기지 않는다.
        """
        try:
            from aot.databases.models import GeoJournal

            if target_type is not None and target_type not in (
                    'plot', 'zone', 'site'):
                return {"error": "target_type must be plot, zone, or site"}
            if target_id and not target_type:
                return {"error": "target_type is required with target_id"}

            q = GeoJournal.query
            if target_type:
                q = q.filter_by(target_type=target_type)
            if target_id:
                q = q.filter_by(target_id=target_id)
            q = q.order_by(GeoJournal.created_at.desc())
            try:
                q = q.limit(max(1, min(int(limit), 200))) if limit else q.limit(50)
            except (TypeError, ValueError):
                q = q.limit(50)
            rows = q.all()
            _tzc = {}
            items = [{
                "journal_id": r.unique_id,
                "title": r.title,
                # DB naive UTC — 일지 대상(구획·구역·대지)의 시계로 오프셋을 붙인다(못 풀면 농장).
                "created_at": iso_at(r.created_at, r.target_id, _tzc) if getattr(r, 'created_at', None) else None,
                "period_start": r.period_start.isoformat() if r.period_start else None,
                "period_end": r.period_end.isoformat() if r.period_end else None,
                "status": r.status,
                "target_type": r.target_type,
                "target_id": r.target_id,
            } for r in rows]
            return {"count": len(items), "journals": items}
        except Exception as e:
            logger.exception("Error in list_plot_journals")
            return {"error": str(e)}

    @classmethod
    def get_plot_journal(cls, journal_id=None, granularity=None,
                         date_from=None, date_to=None, **extra):
        """[읽기전용] 저장된 일지 한 건 — 스냅샷 그대로, 재계산하지 않는다.

        `status` 가 `'done'` 이 아니면 아직 완성되지 않았거나 생성에 실패한
        것이다(`error_message` 참조) — 그때는 `data` 가 비어 있다.

        ## 왜 단위·기간 인자가 필요한가

        일지 하나는 MCP 응답 상한을 쉽게 넘는다. 그러면 캡이 가장 큰 필드를
        떨어뜨리는데 그것이 하필 `env`(측정값)라, **6일짜리 일지도 측정값이
        0개인 채로 나갔다**(실측: 20,153토큰 → 잘린 뒤 2,168토큰, 버킷 6개
        전부 `env` 없음). 캡의 안내는 "필요하면 하나씩 물어봐라" 인데 좁힐
        인자가 없었다.

        `granularity` 는 **화면이 쓰는 그 접기**다(`fold_buckets`) — 저장된
        스냅샷은 그대로 두고 열람 시점에 접는 순수 계산이라, 스냅샷 불변
        계약을 깨지 않는다. 저장 단위보다 잘게는 못 간다.

        ## 스냅샷 위에 얹어 주는 것 (열람 시점 계산)

        스냅샷은 원문 그대로다 — 단위는 `C`·`percent` 같은 키이고, 목표에서
        얼마나 벗어났는지는 버킷마다 흩어진 `delta` 뿐이다. 화면은 그 위에서
        판단 재료를 만드는데 여기에는 없어서, 읽는 쪽이 같은 계산을 다시
        해야 했다. 아래 필드가 그것이다(전부 파생이라 스냅샷을 바꾸지 않고,
        이 기능 이전에 만든 일지에도 붙는다).

        - `units` — 원문 단위 키 → 사람이 읽는 기호(`°C`·`%`·`m/s`).
        - `caveat_texts` — 주의사항 키 → 문장.
        - `derived_measurements` — **결과 지표**의 키(DLI·적산온도·VPD).
          일사·기온·습도는 센서가 잰 원 데이터이고, 판단에 쓰는 것은 그것
          으로 만든 이쪽이다.
        - `target_drift` — 목표 항목마다 **며칠 중 며칠을 어느 쪽으로**
          벗어났는지, 평균·범위. `one_way` 는 한 방향 100% 일 때만 붙는다.
          ⚠ **세기만 한 것이지 판정이 아니다.** 이 데이터에는 허용 범위가
            없고 그것은 의도된 선택이다 — "이 목표는 여기서 안 맞는다" 고
            말하려면 사람이 정한 기준이 있어야 한다. 숫자를 그대로 옮기고
            임계값을 지어내지 말 것.
          ⚠ 접기 **전** 날짜별 버킷으로 센다 — `granularity` 를 바꿔도
            분모가 흔들리지 않는다.
          ⚠ **센서마다 따로 센 것이다.** `sensors` 에 센서별 수치가 들어
            있고, 바깥의 `days`/`above`/`below`/`mean` 은 그 **범위의
            아래끝**이며 `*_hi` 가 위끝이다(센서가 하나면 둘이 같다).
            `agree='mixed'` 는 **센서에 따라 결론이 갈린다**는 뜻이다 —
            실측(김제 3-1, 51일)에서 VPD 가 한 센서는 48일 중 42일 미달,
            다른 센서는 25일 중 15일 초과였다. 그럴 때 한쪽을 골라 말하거나
            평균으로 접지 말 것 — 어느 쪽도 사실이 아니다. 센서 이름을
            들어 양쪽을 그대로 전하라.
        - `stage_summaries` — 단계마다 이 기간에 **실제로 어떻게 됐는가**
          (`stages` 는 계획이다): 겹친 날 수, 적산온도 합계와 끝 시점 누적,
          그 단계의 `target_drift`, 못 재는 목표(`no_sensor_for`).
        """
        try:
            from datetime import date as _date

            from aot.databases.models import GeoJournal
            from aot.aot_flask.geo import plot_journal as PJ

            if not journal_id:
                return {"error": "journal_id is required"}

            row = GeoJournal.query.filter_by(unique_id=journal_id).first()
            if row is None:
                return {"error": f"journal not found: {journal_id}"}
            if row.status != 'done' or row.data is None:
                return {"status": row.status, "error_message": row.error_message}

            # 곡선 목표의 주야 목표·Δ 는 **열람 시점 계산**이다(저장 스냅샷은
            # 불변). 화면에만 태우고 여기서 빠뜨리면 같은 일지·같은 날인데 두
            # 경로의 답이 갈린다 — 실측(2026-09-04): 화면은 "주간 0.81 · 야간
            # 0.46", MCP 는 `target: null, delta: null, delta_skipped: method`
            # 였고 `target_drift` 에도 VPD 가 통째로 없었다. MCP 는 AI 가 읽는
            # 경로라, 사용자가 "이 구획 VPD 어때?" 라고 물으면 화면에는 보이는
            # 답을 AI 만 못 내는 상태가 된다.
            data = dict(PJ.with_curve_deltas(row.data))
            stored = data.get('granularity') or 'day'
            buckets = list(data.get('buckets') or [])

            def _parse(v):
                if not v:
                    return None
                try:
                    return _date(*[int(x) for x in str(v)[:10].split('-')])
                except (TypeError, ValueError):
                    return None

            lo, hi = _parse(date_from), _parse(date_to)
            if lo or hi:
                kept = []
                for b in buckets:
                    d = _parse(b.get('key'))
                    if d is None:
                        continue
                    if lo and d < lo:
                        continue
                    if hi and d > hi:
                        continue
                    kept.append(b)
                buckets = kept
                data['period_filter'] = {
                    'from': lo.isoformat() if lo else None,
                    'to': hi.isoformat() if hi else None,
                    'kept': len(kept),
                    'of': len(data.get('buckets') or []),
                }

                # 날짜를 좁혔으면 **단계도 그 기간에 맞춰** 줄인다. 그러지
                # 않으면 하루를 요청해도 6단계의 목표·지침이 통째로 실려
                # (실측 2,495토큰) 정작 그 하루의 측정값을 밀어낸다.
                #
                # 지우지는 않는다 — 앞뒤에 무엇이 있었는지는 문서의 값이다.
                # 기간 밖 단계는 **이름과 기간만** 남기고 `targets`·`guidance`
                # 를 뺀 뒤 그 사실을 표식으로 말한다(빈 값과 구분되어야 한다).
                stages = data.get('stages') or []
                if stages:
                    trimmed, dropped = [], 0
                    for st in stages:
                        s0, s1 = _parse(st.get('starts_on')), _parse(st.get('ends_on'))
                        overlaps = not ((hi and s0 and s0 > hi)
                                        or (lo and s1 and s1 < lo))
                        if overlaps:
                            trimmed.append(st)
                            continue
                        thin = {k: v for k, v in st.items()
                                if k not in ('targets', 'guidance')}
                        thin['outside_period'] = True
                        trimmed.append(thin)
                        dropped += 1
                    data['stages'] = trimmed
                    if dropped:
                        data['stages_note'] = (
                            "%d of %d stages fall outside the requested dates — "
                            "their targets and guidance are omitted here (call "
                            "without date_from/date_to to see the whole plan)."
                            % (dropped, len(stages)))

            # 접기 **전**의 날짜별 버킷. 이탈을 셀 때 쓴다 — 접힌 버킷으로
            # 세면 "78일 중 78일" 의 분모가 보는 단위에 따라 달라진다.
            raw_buckets = list(buckets)

            # 좁히지도 접지도 않은 긴 조회는 **기본으로 접는다.** 예전에는
            # 51일치를 그대로 만들어 캡이 버킷을 3개로 잘랐다 — 남은 것은
            # "51건 중 3건" 이라 그 문서로는 아무것도 답할 수 없다.
            #
            # 도구 설명이 이미 "사흘을 넘으면 granularity 를 쓰라" 고 안내한다.
            # **기본값이 그 안내를 따르게** 한 것이고, 무엇으로 접었는지는
            # `granularity_view` 가 말한다. 일별이 필요하면 명시하면 된다.
            # 한 단계만 접어서는 모자랄 수 있다. 51일을 주간으로 접으면 8개인데
            # 버킷 하나가 2,400 토큰이라 여전히 상한을 넘어, 캡이 "8건 중 3건"
            # 으로 잘랐다. **들어갈 때까지** 접는다 — 굵게 보는 것과 잘려 나가는
            # 것 중에는 전자가 낫다(잘린 문서는 몇 건인지조차 답하지 못한다).
            auto_folded = False
            if not granularity and stored == 'day' and len(buckets) > 3:
                order = ['week', 'month', 'all']
                # 상한은 캡이 쓰는 값을 그대로 본다(두 벌로 두면 갈라진다).
                # 고정비(단계·요약·캐비어트·안내)를 뺀 나머지가 버킷 예산이다.
                # ⚠ **실측으로 잡을 것.** 처음에 4,000 으로 어림했다가 실제
                #   고정비가 8,303 인 것을 보고 고쳤다 — 예산을 크게 잡으면
                #   접기가 통과시킨 응답을 캡이 다시 잘라, 지켜야 할 `env` 가
                #   빠진 채 나간다(그렇게 만들어 보고 알았다).
                #   아래 `auto_folded` 분기가 단계별 이탈을 생략하므로 접어서
                #   보는 조회의 고정비는 4,000 안팎이다.
                #
                # 접기는 **대략 맞추는 것**이고 정밀 조정은 캡이 한다. 예산을
                # 빡빡하게 잡으면 한 단계 더 접혀 51일이 한 덩어리가 된다 —
                # 굵게 보는 것보다 나쁜 것은 **너무 굵게** 보는 것이다.
                from aot.tools.tool_execution import _MAX_RESPONSE_TOKENS
                budget = max(1, _MAX_RESPONSE_TOKENS - 4000)
                for g in order:
                    folded = PJ.fold_buckets(buckets, to=g, granularity=stored)
                    size = len(json.dumps(folded, ensure_ascii=False,
                                          default=str)) / 3.0
                    granularity, auto_folded = g, True
                    if size <= budget:
                        break

            if granularity:
                if granularity not in PJ.VIEW_GRANULARITIES:
                    return {"error": "granularity must be one of %s"
                                     % ', '.join(PJ.VIEW_GRANULARITIES)}
                order = {'day': 0, 'week': 1, 'month': 2, 'all': 3}
                if order.get(granularity, 0) < order.get(stored, 0):
                    # 없는 정보를 지어내지 않는다 — 저장 단위가 무엇인지
                    # 말해 주어야 호출자가 다시 부를 수 있다.
                    return {"error": "this journal is stored by '%s'; it cannot "
                                     "be shown by '%s'" % (stored, granularity)}
                buckets = PJ.fold_buckets(buckets, to=granularity,
                                          granularity=stored)
                data['granularity_view'] = granularity

            data['buckets'] = buckets

            # 좁히지 않고 부른 긴 일지는 응답 캡에 걸려 `env`(측정값)가
            # 통째로 빠진다. 캡의 안내는 "하나씩 물어봐라" 인데 **무엇으로
            # 좁히는지**는 그 자리에서 알 수 없다 — 여기서 말해 준다.
            # 이 힌트는 최상위 문자열이라 캡이 리스트 필드를 떨어뜨려도 남는다.
            if auto_folded:
                data['hint'] = (
                    "No granularity was given and this journal has many periods, "
                    "so it was folded to '%s' to fit the response limit. Call "
                    "again with granularity='day' (narrow the range with "
                    "date_from/date_to first) for day-by-day detail."
                    % granularity)
            elif not granularity and not (lo or hi) and len(buckets) > 3:
                data['hint'] = (
                    "This journal has %d periods and may be trimmed to fit the "
                    "response limit — the measurements (env) are dropped first. "
                    "Call again with granularity='week'|'month'|'all' to fold "
                    "them, or date_from/date_to to narrow the range."
                    % len(buckets))

            # ── 화면이 아는 것을 AI 도 알게 한다 ────────────────────────────
            #
            # 저장된 스냅샷은 `unit` 을 **원문 키**(`C`·`percent`·`m_s`·
            # `none`)로, `caveats` 를 **키 문자열**로 들고 있다. 화면은 열람
            # 시점에 그것을 기호(`°C`)와 문장으로 바꿔 내는데, MCP 로 읽는
            # 쪽에는 그 두 가지가 없어 AI 가 "0.26 m_s" 를 그대로 사용자에게
            # 옮기거나 `measurements-excluded:rssi,snr` 를 스스로 해독해야
            # 했다(실사용 점검, 2026-09-04).
            #
            # ⚠ **원본 필드는 건드리지 않는다.** 행마다 라벨을 끼워 넣으면
            #   응답이 그만큼 커지는데, 이 도구는 이미 캡에 걸려 `env` 를
            #   먼저 버린다 — 그래서 **문서 전체에 실제로 쓰인 단위만** 작은
            #   대응표 하나로 덧붙인다(`granularity_view`·`hint` 와 같은
            #   파생 필드다).
            units = {}
            for bucket in buckets:
                for env_row in (bucket.get('env') or []):
                    raw_unit = env_row.get('unit')
                    if raw_unit and raw_unit not in units:
                        units[raw_unit] = PJ.unit_label(raw_unit)
            if units:
                data['units'] = units
            caveat_keys = data.get('caveats') or []
            if caveat_keys:
                data['caveat_texts'] = {k: PJ.caveat_text(k)
                                        for k in caveat_keys}

            # ── 화면이 **판단하는 것**도 함께 준다 ──────────────────────────
            #
            # 여기까지가 "화면이 아는 것"(단위·주의문)이었다. 그런데 화면은
            # 그 위에서 **판단 재료**를 더 만든다 — 무엇이 결과 지표인지,
            # 목표에서 어느 쪽으로 얼마나 벗어났는지, 단계마다 얼마나
            # 쌓았는지. 그것이 전부 열람 시점 계산이라 MCP 로 읽는 쪽에는
            # 없었다: 사람이 보는 화면은 "무엇이 중요한가" 를 말해 주는데
            # AI 가 받는 응답은 원 스냅샷 그대로였다(2026-09-04 점검).
            #
            # ⚠ **작은 것만 싣는다.** 이 도구는 이미 응답 캡에 걸려 `env` 를
            #   먼저 버린다 — 아래 셋은 단계 수·목표 항목 수만큼이라 길이가
            #   기간에 비례하지 않는다. 버킷을 늘리는 필드는 넣지 않는다.
            #
            # ⚠ **이탈은 접기 전 원 버킷으로 센다.** 접힌 버킷으로 세면
            #   "78일 중 78일" 의 분모가 보는 단위에 따라 달라진다.
            drift_source = [b for b in raw_buckets if not b.get('gap_count')]
            drift = PJ.target_drift(drift_source)
            if drift:
                data['target_drift'] = drift

            # 결과 지표(원 데이터로 만든 값)와 원 데이터를 가른다 — 사람이
            # 보고 판단하는 것은 뒤쪽이 아니라 이쪽이다.
            data['derived_measurements'] = list(PJ.DERIVED_MEASUREMENTS)

            # 단계별 요약. 스냅샷의 `stages` 는 **계획**이고, 이것은 그 계획이
            # 이 기간에 어떻게 됐는가다(적산온도·이탈·못 재는 항목).
            try:
                summaries = []
                for sec in PJ.stage_sections(row.data):
                    stage = sec.get('stage') or {}
                    summaries.append({
                        'key': stage.get('key'), 'name': stage.get('name'),
                        'in_period': sec.get('in_period'),
                        # ⚠ `stage_sections` 의 `when` 은 기간과 겹치면
                        #   `'current'` 다 — 화면에서는 "이 문서의 단계" 라는
                        #   뜻이지만, 읽는 쪽에는 "지금 진행 중인 단계" 로
                        #   읽힌다(겹치는 단계가 다섯이면 다섯이 '현재' 다).
                        'when': ('in_period' if sec.get('in_period')
                                 else sec.get('when')),
                        'days': sec.get('days'),
                        'starts_on': sec.get('starts_on'),
                        'ends_on': sec.get('ends_on'),
                        'gdd': sec.get('gdd'),
                        'gdd_cumulative': sec.get('gdd_cumulative'),
                        'target_drift': sec.get('drift') or [],
                        'no_sensor_for': [t.get('label') for t
                                          in (sec.get('unobservable') or [])],
                    })
                # 날짜를 좁혔으면 요약도 그 기간 것만 상세를 싣는다 —
                # `stages` 와 같은 원칙이다. 하루를 물었는데 6단계의 이탈
                # 통계가 통째로 실리면(실측 4,192토큰) 그 하루의 측정값을
                # 밀어낸다. 기간 밖 단계는 이름·기간·적산온도만 남긴다.
                if (lo or hi) and summaries:
                    thinned = []
                    for sm in summaries:
                        s0, s1 = _parse(sm.get('starts_on')), _parse(sm.get('ends_on'))
                        overlaps = not ((hi and s0 and s0 > hi)
                                        or (lo and s1 and s1 < lo))
                        if overlaps:
                            thinned.append(sm)
                            continue
                        thinned.append({k: v for k, v in sm.items()
                                        if k not in ('target_drift', 'no_sensor_for')})
                    summaries = thinned
                # 접어서 보는 조회는 **개괄을 원한다는 뜻**이다. 단계마다 센서별
                # 이탈 통계까지 실으면(실측 4,192토큰, 고정비의 절반) 그만큼
                # 버킷이 잘려 나간다 — 문서 단위 `target_drift` 가 같은 것을
                # 요약해 싣고 있으므로 거기를 보면 된다.
                if auto_folded and summaries:
                    summaries = [{k: v for k, v in sm.items()
                                  if k != 'target_drift'} for sm in summaries]
                    data['stage_summaries_note'] = (
                        "Per-stage target drift is omitted because this journal "
                        "was folded to '%s' — see the document-level "
                        "'target_drift', or narrow the range with "
                        "date_from/date_to for per-stage detail." % granularity)
                if summaries:
                    data['stage_summaries'] = summaries
            except Exception:
                logger.exception('get_plot_journal: stage summary failed')

            # ── 목표 정의의 반복 필드를 머리로 올린다 ──────────────────
            #
            # 목표 하나가 열한 개 필드를 갖는데 `label`·`unit`·`measurement`·
            # `shape`·`fixed`·`when` 은 `key` 로 정해지는 값이다. 6단계 × 5목표
            # = 30번 반복되어 2,288 토큰이었다(주간 조회 전체의 7%).
            #
            # 정의는 `target_defs` 에 한 벌만 싣고 단계에는 그 단계에서만
            # 달라지는 것(`value`·`source`·곡선 정보)을 남긴다.
            _DEF_KEYS = ('label', 'unit', 'measurement', 'shape', 'fixed', 'when')
            target_defs = {}
            for st in (data.get('stages') or []):
                slim = []
                for t in (st.get('targets') or []):
                    k = t.get('key')
                    if not k:
                        slim.append(t)
                        continue
                    if k not in target_defs:
                        target_defs[k] = {d: t[d] for d in _DEF_KEYS if d in t}
                    slim.append({d: v for d, v in t.items()
                                 if d not in _DEF_KEYS})
                if slim:
                    st['targets'] = slim
            if target_defs:
                data['target_defs'] = target_defs
                data['target_defs_note'] = (
                    "Each stage's targets carry only what differs there; the "
                    "shared fields (label, unit, measurement, shape, when) are "
                    "here, keyed by 'key'.")

            # ── 캡이 무엇부터 버릴지 이 도구가 정한다 ──────────────────
            #
            # 캡은 무게로 고른다. 그러면 **호출자가 달라고 한 것**이 가장
            # 크다는 이유로 먼저 잘린다 — 하루로 좁혀 불러도 그 하루의 측정값
            # (`buckets.env`)이 빠지고, 날짜와 무관하게 늘 실리는 단계 요약이
            # 남았다(실측 2026-09-05).
            #
            # 순서를 뒤집는다. 단계 계획의 산문·이탈 통계는 다른 도구
            # (`get_plot`)로도 볼 수 있지만, **그 기간의 측정값과 노트는 이
            # 도구에만 있다.**
            out = PJ.journal_to_jsonable(data)
            if isinstance(out, dict):
                from aot.tools.tool_execution import CAP_PRIORITY_KEY
                out[CAP_PRIORITY_KEY] = {
                    'drop_first': [['stages', 'guidance'],
                                   ['stage_summaries', 'target_drift'],
                                   ['stages', 'targets']],
                    'keep_last': [['buckets', 'env'], ['buckets', 'notes']],
                    # 캡의 안내는 "좁혀서 다시 부르라" 까지밖에 못 말한다 —
                    # **무엇으로** 좁히는지는 이 도구만 안다. 인자 이름을
                    # 적어 두지 않으면 모델이 같은 조회를 되풀이한다.
                    'narrow_with': (
                        "To see the rest, call get_plot_journal again on the "
                        "same journal_id with date_from/date_to for a shorter "
                        "range, or granularity='week'|'month'|'all' to fold the "
                        "periods together."),
                }
            return out
        except Exception as e:
            logger.exception("Error in get_plot_journal")
            return {"error": str(e)}

    @classmethod
    def create_plot_journal(cls, target_type=None, target_id=None, start=None,
                            end=None, granularity=None, **extra):
        """일지를 만든다 — 그 기간의 사실을 뜬 **스냅샷**을 남긴다.

        생성은 InfluxDB 를 크게 읽으므로(채널 수 × 기간) 승인 대상이다.
        화면의 생성 경로(`routes_geo_journal.geo_journal_create`)와 **같은
        게이트를 지난다** — 여기서 따로 세면 통과해 놓고 다른 규모로 돈다.

        집계는 백그라운드에서 돈다. 이 도구는 `journal_id` 와 `status`
        (`pending`)를 즉시 돌려주므로, 잠시 뒤 `get_plot_journal` 로 다시
        물어 `status == 'done'` 을 확인해야 한다.
        """
        try:
            from datetime import date as _date

            from aot.aot_flask.extensions import db
            from aot.aot_flask.geo import plot_journal as PJ
            from aot.databases.models import GeoJournal

            if target_type not in ('plot', 'zone', 'site'):
                return {"error": "target_type must be plot, zone, or site"}
            if not target_id:
                return {"error": "target_id is required"}

            def _parse(v):
                try:
                    return _date(*[int(x) for x in str(v)[:10].split('-')])
                except (TypeError, ValueError, AttributeError):
                    return None

            s_date, e_date = _parse(start), _parse(end)
            if s_date is None or e_date is None:
                return {"error": "start and end are required (YYYY-MM-DD)"}
            if s_date > e_date:
                return {"error": "start is after end"}
            if granularity is not None and granularity not in (
                    'day', 'week', 'month'):
                return {"error": "granularity must be day, week or month"}

            # ── 승인 게이트보다 앞에 오는 것은 없다. 비용 게이트는 화면과
            #    같은 함수다 — 통과하지 못하면 집계를 **시작조차 하지 않는다**.
            try:
                cost = PJ.estimate_journal_cost(target_type, target_id,
                                                s_date, e_date)
            except ValueError as exc:
                return {"error": "could not resolve that target: %s" % exc}
            if not cost.get('ok'):
                return {"error": "that selection is too large to build",
                        "reason": cost.get('reason'),
                        "days": cost.get('days'),
                        "channels": (cost.get('env_channels', 0)
                                     + cost.get('control_channels', 0)),
                        "advice": ("Try a shorter period, a single plot instead "
                                   "of a zone, or granularity='week'.")}

            row = GeoJournal(target_type=target_type, target_id=target_id,
                             period_start=s_date, period_end=e_date,
                             title='', status='pending')
            db.session.add(row)
            db.session.commit()

            # ⚠ **여기서 끝까지 돌린다(`wait=True`).** 백그라운드로 띄우면
            #   MCP stdio 연결이 끊기는 순간 프로세스와 함께 스레드가 죽고,
            #   행은 영영 'running' 으로 남는다(실측: 5분 뒤에도 버킷 0).
            #   비용 게이트가 규모를 이미 막고 있어 여기서 기다려도 된다.
            PJ.start_journal_build(row.unique_id, granularity=granularity,
                                   wait=True)

            # ⚠ **세션을 비우고 다시 읽는다.** 빌드는 자기 app context 에서
            #   따로 커밋하므로, 바깥 세션의 identity map 에는 아직 'pending'
            #   인 옛 행이 남아 있다 — 그대로 읽으면 다 만들어 놓고 "아직
            #   만드는 중" 이라고 답한다(실측으로 그랬다).
            db.session.expire_all()
            row = GeoJournal.query.filter_by(unique_id=row.unique_id).first()
            if row is None:
                return {"error": "journal disappeared while building"}
            if row.status != 'done':
                return {"status": row.status, "journal_id": row.unique_id,
                        "error_message": row.error_message}
            return {"status": "done", "journal_id": row.unique_id,
                    "title": row.title,
                    "period": {"start": s_date.isoformat(),
                               "end": e_date.isoformat()},
                    "note": ("Built. Read it with get_plot_journal — pass "
                             "granularity for a long period so the "
                             "measurements survive the response limit.")}
        except Exception as e:
            logger.exception("Error in create_plot_journal")
            return {"error": str(e)}

    @classmethod
    def create_plot(cls, map_id=None, geometry=None, zone_id=None, subject=None,
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
            from aot.aot_flask.geo import plot_io
            from aot.space import plot_context
            from aot.databases.models import GeoShape

            if geometry and zone_id:
                return {"status": "error",
                        "message": "give either geometry or zone_id, not both"}
            # 쓰기 시점 그룹 스코프 — 구획을 놓을 지도·시설로 묻는다(스코프
            # 대상인 지도·시설이 아니면 그냥 지나간다). 구획 자체는 웹에서도
            # 그룹 밖이지만, 남의 지도·시설 안에 행을 만드는 것은 그 자원에
            # 쓰는 일이다.
            from aot.aot_flask.access import write_scope
            write_scope.enforce([v for v in (map_id, facility_id)
                                 if isinstance(v, str) and v.strip()])
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
                if not map_id and shape.geo_id:
                    map_id = shape.geo_id
                    write_scope.enforce(map_id)
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

    @classmethod
    def modify_plot(cls, plot_id=None, **fields):
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

    @classmethod
    def propose_plot_split(cls, zone_id=None, parts=None, strip_width_cm=None,
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

    @classmethod
    def apply_plot_split(cls, zone_id=None, subject=None, started_on=None,
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

    @classmethod
    def copy_plot(cls, plot_id=None, subject=None, started_on=None, **extra):
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

    @classmethod
    def end_plot(cls, plot_id=None, ended_on=None, reason='harvested', **extra):
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

    @classmethod
    def confirm_plot_stage(cls, plot_id=None, stage_key=None, started_on=None,
                           **extra):
        """[쓰기] 단계 전환을 확인해 원장에 남긴다. 사람 승인 필요.

        **이 한 줄이 기준점을 옮긴다** — 이후 단계는 여기 적힌 날부터 계산된다.
        그래서 날짜를 지어내지 말 것: `get_plot` 의 `stage_proposal.started_on`
        이 자료에서 되짚은 날이고, 사람이 다른 날을 말하면 그것을 쓴다.

        무엇을 확인할지는 `stage_proposal` 이 말해 준다. 제안이 없어도(=null)
        사람이 "이미 넘어갔다" 고 말하면 확인한다 — 단계 키는 `stage_schedule`
        에서, 날짜는 그 사람이 말한 날. 아직 오지 않은 경계를 옮기는 것은
        `reschedule_plot_stage` 다(STAGE_TOOL_RULE).
        """
        try:
            from aot.aot_flask.geo import plot_io

            if not plot_id:
                return {"status": "error", "message": "plot_id is required"}
            if not stage_key:
                return {"status": "error",
                        "message": ("stage_key is required — read it from "
                                    "get_plot's stage_proposal.stage_key, or "
                                    "stage_schedule for a change the grower "
                                    "reports")}
            started_on, derr = cls._confirm_stage_date(plot_id, stage_key,
                                                       started_on)
            if derr:
                return {"status": "error", "message": derr}
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

    _STAGE_DATE_REQUIRED = (
        "started_on is required: get_plot has no pending stage_proposal for "
        "this stage, so there is no date on record. Ask the grower which day "
        "it happened ('YYYY-MM-DD') — do not assume today.")

    @classmethod
    def _confirm_stage_date(cls, plot_id, stage_key, started_on):
        """confirm_plot_stage 의 전환일 → (날짜|None, 오류|None).

        날짜를 주면 그대로. 없으면 그 단계에 대한 제안(stage_proposal)이 자료에서
        되짚은 날을 쓰고, 제안이 없거나 다른 단계면 **묻는다** — 예전에는
        처리기 아래(accept_stage)가 오늘로 채워, 재배자가 "지난주에 넘어갔다"
        고 한 전환이 오늘 날짜로 기준점을 옮겼다(리뷰 26-09-24).
        구획이 없거나 프로그램이 없으면 판단하지 않는다(처리기가 그 오류를 낸다)."""
        if started_on and str(started_on).strip():
            return started_on, None
        try:
            from aot.databases.models import GeoPlot
            from aot.space import plot_context
            row = GeoPlot.query.filter_by(unique_id=plot_id).first()
            if row is None or not row.program_uuid:
                return None, None
            # stage_proposal 은 프로그램 **요약 dict**(program_brief)를 받는다 — 모델 행을
            # 넘기면 .get 에서 터지고, 그 예외가 삼켜져 늘 날짜를 되묻게 된다(26-09-24).
            prop = plot_context.stage_proposal(
                row, program=plot_context.program_brief(row))
        except Exception as e:                              # noqa: BLE001
            logger.debug("_confirm_stage_date proposal failed: %s", e)
            prop = None
        if prop and prop.get('stage_key') == stage_key and prop.get('started_on'):
            return prop['started_on'], None
        return None, cls._STAGE_DATE_REQUIRED

    @classmethod
    def validate_confirm_plot_stage(cls, plot_id=None, stage_key=None,
                                    started_on=None, **_extra):
        """승인 앞 검사(tool_execution._PRE_GATE_VALIDATORS) — 날짜가 없고
        제안에도 없으면 승인을 받기 전에 묻게 한다(승인 뒤에 실패하면 사람의
        승인이 헛걸음이 된다)."""
        if not plot_id or not stage_key:
            return None
        _d, err = cls._confirm_stage_date(plot_id, stage_key, started_on)
        return {"error": err} if err else None

    @classmethod
    def reschedule_plot_stage(cls, plot_id=None, stage_key=None, started_on=None,
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
            # 일정 표는 날짜 칸만 — 단계마다 지침·목표값까지 싣던 응답이 연기 한 번에 길었다
            # (2026-10-28 점검). 지침·목표는 detail.plot 이 준다.
            _keep = ('index', 'key', 'name', 'days', 'starts_on', 'ends_on', 'source', 'state')
            sched = [{k: r[k] for k in _keep if k in r}
                     for r in (result.get('stage_schedule') or []) if isinstance(r, dict)]
            return {"status": "success",
                    "stage_schedule": sched,
                    "note": ("Later boundaries moved with it; the programme itself is "
                             "unchanged. Guidance and targets: get_plot.")}
        except Exception as e:
            logger.exception("Error in reschedule_plot_stage")
            return {"status": "error", "message": str(e)}

    @classmethod
    def set_plot_stage_guidance(cls, plot_id=None, stage_key=None, guidance=None,
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

    @classmethod
    def add_plot_stage(cls, plot_id=None, name=None, days=None, after=None,
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

    @classmethod
    def remove_plot_stage(cls, plot_id=None, stage_key=None, **extra):
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

    @classmethod
    def save_plot_schedule_as_program(cls, plot_id=None, name=None,
                                      adopt_targets=False, **extra):
        """[쓰기] 이 구획의 일정을 **프로그램으로 등록한다**. 사람 승인 필요.

        구획에서 기간을 맞추고 단계를 더하고 지침을 적고 나면 그 지식은 그 구획
        안에만 있다 — 다음 작기·옆 밭이 같은 일을 처음부터 다시 하지 않게 한다.

        담기는 것은 지금 **실제로 따르고 있는** 단계 목록이고, 기간은 표준이
        아니라 경계 사이의 실제 날수다.

        ## 목표는 되먹임이 한쪽만 열려 있었다

        단계 일수는 위처럼 실측으로 갱신되는데 목표값은 아무리 어긋나도 갱신할
        길이 없었다 — 문헌 기준이 이 현장에서 안 맞게 되는 상황이 정확히 여기서
        막힌다. 이제 등록할 때마다 `target_review` 로 **단계마다 목표 옆에 이
        구획이 실제로 잰 분포**를 함께 낸다. 보여 주기만 한다.

        `adopt_targets=True` 면 애매하지 않은 항목만 실측 중앙값으로 바꿔
        담는다. 센서가 둘 이상이라 값이 갈리거나, 그 단계에 잰 것이 없거나,
        곡선이 걸렸거나, 항목 정의의 범위를 벗어나면 **원본을 지키고 이유를
        낸다**(`targets_kept`) — 지어낸 숫자가 다음 작기의 목표가 되는 일이
        이 게이트의 반대편이다.

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
                plot_id, name=name, set_by='AI',
                adopt_targets=bool(adopt_targets))
            if err:
                return {"status": "error", "message": err}
            out = {"status": "success", "program": result.get('program'),
                   "note": ("The plot still follows what it followed before — "
                            "registering is a copy. 'target_review' puts each "
                            "stage's target next to what this plot actually "
                            "measured over that stage ('median' with p25-p75, "
                            "per sensor, never averaged across sensors). A "
                            "target the site never met is a finding: say it "
                            "with the numbers and offer "
                            "adopt_targets=true, which rewrites only the "
                            "unambiguous ones. 'targets_kept' says why the "
                            "rest were left alone — do not fill those in "
                            "yourself.")}
            for key in ('target_review', 'targets_adopted', 'targets_kept'):
                if result.get(key):
                    out[key] = result[key]
            return out
        except Exception as e:
            logger.exception("Error in save_plot_schedule_as_program")
            return {"status": "error", "message": str(e)}

    @classmethod
    def undo_plot_stage(cls, plot_id=None, **extra):
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

    @classmethod
    def apply_plot_resources(cls, plot_id=None, **extra):
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
            out = {"status": "success", "result": result}
            # 결과 읽는 법 — 도구 설명에서 옮겼다(B′). 해당하는 것만.
            r = result if isinstance(result, dict) else {}
            notes = []
            if r.get('failed'):
                notes.append("'failed' functions did NOT start — name them; "
                             "only 'activated' ones are running.")
            if r.get('unresolved'):
                notes.append("'unresolved': this site has no device for that "
                             "role, so nothing started for it — placing one is "
                             "a human job.")
            if r.get('ambiguous'):
                notes.append("'ambiguous': several functions fit that role, so "
                             "none was picked — ask which one.")
            if not any(r.values()):
                # 상태는 success 인데 결과가 모두 비면 "켠 것 없음" 의 이유를 말한다
                # (2026-10-28 점검: 이유 없는 빈 배열).
                notes.append("Nothing was started: the current stage declares no resource "
                             "function (see get_plot stage.resources), or all of them are "
                             "already running.")
            if notes:
                out["_reading"] = notes
            return out
        except Exception as e:
            logger.exception("Error in apply_plot_resources")
            return {"status": "error", "message": str(e)}

    @classmethod
    def delete_plot(cls, plot_id=None, **extra):
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

