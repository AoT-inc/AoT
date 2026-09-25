# coding=utf-8
"""일지 지도 열람과 관수(스프링클러) 흐름 계산 보조."""
from aot.aot_flask.geo import plot_context

from ._shared import logger, resolve_target_row


# ── 문서에 실을 지도 ────────────────────────────────────────────────────────
#
# 일지는 **어디서 있었던 일인지**를 말하지 않고 있었다. 위치는 "3-1" 같은 이름
# 한 줄이 전부였고, 도형·센서 배치는 문서 어디에도 없다. 종이로 넘겨받은
# 사람은 그 이름이 어느 밭인지 알 수 없다.
#
# ⚠ **스냅샷에는 기하가 없다.** 그래서 여기서 하는 일은 전부 **열람 시점
#   계산**이다 — 예전에 만든 일지에도 지도가 붙는다(소급). 대신 도형과 센서
#   위치는 **지금**의 것이지 문서 기간의 것이 아니다. 그 사실을 화면이 한 줄로
#   말한다(`live: True`). 기하를 스냅샷에 굳히지 않는 이유는 §6 계약을 바꾸면
#   기존 일지가 전부 "지도 없음" 이 되기 때문이다.

def _geom_bbox(geom, out=None):
    """GeoJSON 기하 → `[w, s, e, n]`. `out` 을 주면 그것과 합친다."""
    box = out
    stack = [(geom or {}).get('coordinates')]
    while stack:
        item = stack.pop()
        if not isinstance(item, (list, tuple)) or not item:
            continue
        if (len(item) >= 2 and isinstance(item[0], (int, float))
                and isinstance(item[1], (int, float))):
            x, y = float(item[0]), float(item[1])
            box = ([x, y, x, y] if box is None else
                   [min(box[0], x), min(box[1], y),
                    max(box[2], x), max(box[3], y)])
            continue
        stack.extend(item)
    return box


def _shape_geometry(shape):
    """GeoShape → GeoJSON 기하 dict (없으면 None)."""
    feat = getattr(shape, 'feature', None)
    if isinstance(feat, str):
        try:
            import json as _json
            feat = _json.loads(feat)
        except (ValueError, TypeError):
            return None, None
    if not isinstance(feat, dict):
        return None, None
    geom = feat.get('geometry')
    if not geom or not geom.get('coordinates'):
        return None, None
    return geom, (feat.get('properties') or {}).get('color')


def journal_map_view(journal_data):
    """이 일지의 대상을 그린 지도 한 장 → dict | None.

    담는 것은 — **구획 도형과 이름**, 그 구획이 든 **대지(site)·구역(zone)의
    도형과 이름**, **센서 자리**, 그리고 **바탕 지도 후보들**이다. 편집 지도를
    옮겨 놓는 것이 아니라 "이 문서가 말하는 자리" 를 한 장으로 보이는 것이
    목적이라, 그리기 도구·장치 조작은 싣지 않는다. 대신 확대/축소·회전·바탕
    전환·저작권 표시는 있어야 한다 — 항공사진과 일반도가 서로 다른 것을
    보여 주고, 저작권은 뺄 수 없다.

    색은 **정하지 않는다** — 도형이 자기 색을 가졌으면 그것을, 아니면 종류별
    테마색(`AOT_GEO_CONFIG.theme_config`)을 화면이 붙인다. 같은 밭이 편집
    지도와 일지에서 다른 색이면 사용자가 두 번 배워야 한다.

    대상이 사라졌거나(구획 삭제) 기하가 없으면 `None` — 그 경우 문서는 지도
    없이 그대로 나온다. 지도가 없다고 일지가 안 열리면 안 된다.
    """
    target = (journal_data or {}).get('target') or {}
    ttype, tid = target.get('type'), target.get('unique_id')
    if not ttype or not tid:
        return None
    try:
        row = resolve_target_row(ttype, tid)
    except ValueError:
        return None                      # 대상이 삭제됐다 — 지도 없이 낸다.
    except Exception:
        logger.debug('일지 지도: 대상 조회 실패', exc_info=True)
        return None

    try:
        geom = plot_context.geometry_of(row)
    except Exception:
        logger.debug('일지 지도: 기하를 읽지 못했다', exc_info=True)
        geom = None
    if not geom or not geom.get('coordinates'):
        return None

    bbox = _geom_bbox(geom)
    if bbox is None:
        return None

    out = {
        'name': target.get('name') or getattr(row, 'name', None) or '',
        'geometry': geom,
        'color': getattr(row, 'color', None),
        # 끝난 작기는 편집 지도에서 점선으로 그린다 — 같은 약속을 지킨다.
        'ended': bool(getattr(row, 'ended_on', None)),
        'containers': [],
        'sensors': [],
        'sensor_source': None,
        'bbox': bbox,
        # 시설에 매단 구획의 기하는 **시설 외피에서 파생한 값**이다 — 그 사실을
        # 말하지 않으면 사용자는 직접 그린 경계로 읽는다(§ plot_context 경고).
        'derived_geometry': bool(
            hasattr(row, 'has_own_geometry') and not row.has_own_geometry()),
    }

    # ── 감싸는 대지·구역 ────────────────────────────────────────────────
    #   ⚠ **둘 다 낸다.** `container_for_geometry` 는 zone 이 site 를 이기므로
    #     그 결과 하나만 쓰면 구역 안의 구획에서는 대지가 영영 안 나온다
    #     (`site_for_geometry` 가 이 때문에 따로 있다). 문서를 받는 사람이
    #     먼저 묻는 것은 "어느 농장(대지)의 어느 구역인가" 다.
    #   ⚠ 구획을 화면에 맞출 때 이 도형들은 **넣지 않는다** — 대지가 구획보다
    #     훨씬 크면 정작 주인공이 점만 하게 나온다(실측: 2,222m² 구획).
    if ttype == 'plot':
        try:
            from aot.aot_flask.geo import device_membership
            containers = device_membership.load_containers(row.geo_id)
            site = device_membership.site_for_geometry(
                row.geo_id, geom, containers=containers)
            zone = plot_context.zone_for_plot(row, containers=containers)
        except Exception:
            logger.debug('일지 지도: 상위 도형 조회 실패', exc_info=True)
            site = zone = None
        for shape, kind in ((site, 'site'), (zone, None)):
            if shape is None:
                continue
            kind = kind or (getattr(shape, 'type', None) or 'zone')
            if any(cc['kind'] == kind for cc in out['containers']):
                continue          # site 가 zone 자리에도 잡히는 지도가 있다.
            cgeom, ccolor = _shape_geometry(shape)
            if not cgeom:
                continue
            out['containers'].append({
                'kind': kind,
                'name': plot_context._shape_name(shape) or '',
                'geometry': cgeom,
                'color': ccolor,
            })

    # ── 센서 자리 ───────────────────────────────────────────────────────
    #   이 문서의 숫자가 **어디서 나온 값인지**를 그림으로 말한다.
    try:
        from aot.aot_flask.geo import device_membership
        if ttype == 'plot':
            found = plot_context.sensors_for_plot(row)
            ids = list(found.get('in_plot') or [])
            source = found.get('source')
            if not ids:
                ids = list(found.get('from_zone') or [])
        else:
            ids = sorted(device_membership.device_ids_in_shape(row))
            source = 'zone'
        wanted = set(ids)
        if wanted:
            seen = set()
            for dev_id, (lng, lat) in device_membership.load_markers(row.geo_id):
                if dev_id not in wanted or dev_id in seen:
                    continue
                seen.add(dev_id)
                name, _kind = device_membership._device_display_name(dev_id)
                out['sensors'].append({
                    'name': name or dev_id[:8], 'lng': lng, 'lat': lat})
                out['bbox'] = [min(out['bbox'][0], lng), min(out['bbox'][1], lat),
                               max(out['bbox'][2], lng), max(out['bbox'][3], lat)]
            out['sensor_source'] = source
    except Exception:
        logger.debug('일지 지도: 센서 위치를 읽지 못했다', exc_info=True)

    return out


# ── 관수량 ───────────────────────────────────────────────────────────────

def _open_field_flow(plot):
    """노지 구획 → `{output_id: {'lph', 'share', 'source'}}`.

    ## 밸브는 자기가 맡은 구역을 **이미 알고 있다**

    지도에 놓인 출력은 `GeoShape(type='device')` — **담당 폴리곤**을 갖는다
    (`device_binding.SHAPE_TYPE_ROLES` 의 `'area'`). "이 밸브가 어디에 물을
    주는가" 는 그 도형이 답한다. 노즐 임자를 정하려고 별도의 지정을 만들
    이유가 없다 — 담당 폴리곤 안에 있는 노즐이 그 밸브 것이다.

    ⚠ **두 번째 판정자를 만들지 말 것.** 한때 구역 도형에 밸브를 매는 별도
      지정을 만들었다가 걷어냈다. 담당 폴리곤이 이미 있는데 구역 단위로
      묶었더니 **틀린 값**이 나왔다 — 나주 배밭은 v11·v12 가 각각 절반
      (510,000 / 512,900 L/h)을 맡는데, 구역으로 묶으면 2,205개가 통째로
      한 밸브에 얹혀 918,750 L/h 가 됐다.

    ## 몫으로 나누지 않는다 — 구획과 겹치는 만큼만 센다

    노지 구획은 폴리곤을 갖는다. **담당 폴리곤 ∩ 구획** 안의 노즐만 세면
    "그 밸브의 물 중 이 구획에 떨어진 몫" 이 곧 나온다 — 면적 비율로 어림할
    필요가 없다(구획 한쪽에 노즐이 몰린 배치가 흔하다).
    """
    from aot.aot_flask.geo import device_binding
    from aot.databases.models import GeoShape

    feature = getattr(plot, 'feature', None) or {}
    geom = feature.get('geometry') or {}
    if not geom:
        return {}
    try:
        from shapely.geometry import shape as _shape
        poly = _shape(geom)
        if poly.is_empty:
            return {}
    except Exception:
        logger.exception('journal: 구획 기하 해석 실패')
        return {}

    # 이 구획을 맡는 출력들 — 일지가 가동시간을 내는 것과 **같은 목록**이다.
    # 여기서 따로 찾으면 두 목록이 갈라져, 표에 있는 장치의 물량이 비거나
    # 없는 장치의 물량이 생긴다.
    try:
        actuators, _unassigned = plot_context.actuators_for_plot(plot)
    except Exception:
        logger.exception('journal: 구획 액추에이터 조회 실패')
        return {}
    output_ids = [a.get('output_id') for a in actuators if a.get('output_id')]
    if not output_ids:
        return {}

    sprinklers = _map_sprinklers(getattr(plot, 'geo_id', None)
                                 or _map_of_plot(plot))
    if not sprinklers:
        return {}

    out = {}
    for oid in output_ids:
        region = None
        for sh in _device_area_shapes(oid):
            try:
                area = _shape((sh.feature or {}).get('geometry') or {})
            except Exception:
                continue
            if area.is_empty:
                continue
            # 한 밸브가 담당 도형을 여럿 가질 수 있다(구역이 나뉜 배치).
            # 합집합으로 모아야 겹치는 노즐을 두 번 세지 않는다.
            region = area if region is None else region.union(area)
        if region is None:
            continue
        region = region.intersection(poly)
        if region.is_empty:
            continue
        lph = sum(flow for pt, flow in sprinklers if region.contains(pt))
        # ⚠ **0 도 기록한다.** 담당 폴리곤은 이 구획과 겹치는데 그 겹친 자리에
        #   이미터가 하나도 없는 배치가 실제로 있다(김제 실측: v341 은 이미터
        #   15개를 갖지만 '평안' 안에는 0개 — 그 밸브의 물은 다른 구획에
        #   떨어진다). 이 항목을 빼 버리면 화면은 그것을 **"유량을 모르는
        #   장치"** 와 구분하지 못하는데, 둘은 사람이 할 일이 다르다:
        #   앞은 "이 구획엔 안 떨어진다"(정상일 수 있다) 이고 뒤는 "이미터를
        #   아직 안 그렸다"(그리면 된다) 이다.
        #
        #   물량 계산에는 영향이 없다 — 쓰는 쪽이 전부 `flow.get('lph')` 로
        #   참을 확인한다(0 은 거짓이라 그대로 건너뛴다).
        out[oid] = {'lph': round(lph, 1), 'share': 1.0,
                    'source': 'map-equipment'}
    return out


def _device_area_shapes(output_id):
    """출력이 맡는 **담당 폴리곤** 도형들 → [GeoShape].

    마커(`aot_device`, 점)는 뺀다 — 위치일 뿐 담당 구역이 아니다.
    """
    from aot.aot_flask.geo import device_binding
    from aot.databases.models import GeoShape

    out = []
    try:
        found = device_binding.shapes_for_device(output_id) or []
    except Exception:
        logger.exception('journal: 담당 도형 조회 실패 (%s)', output_id)
        return out
    for item in found:
        row = item
        if not hasattr(row, 'feature'):
            row = GeoShape.query.filter_by(unique_id=str(item)).first()
        if row is None or row.type != 'device':
            continue
        out.append(row)
    return out


#: 정본 이미터. `aot-geo-stats.js` 의 규칙 그대로다 —
#:   "sprinkler_coverage is the canonical emitter;
#:    sprinkler dot markers are ephemeral"
#: 디자인 개요가 이 규칙으로 수량을 세고 그 값이 맞다.
_EMITTER_SUB_TYPE = 'sprinkler_coverage'


def _map_sprinklers(map_uuid):
    """지도의 **이미터** → `[(Point, L/h)]`.

    ⚠ **`sub_type='sprinkler'` 를 세지 말 것.** 그것은 그리기 도중의 점
      마커라 같은 자리에 여러 벌이 쌓인다 — 실측(나주)에서 이미터 274개짜리
      과수원에 마커가 2,466개였고, 그것을 세는 바람에 일지가 513,630 L 를
      냈다(사람이 셈한 값은 19,180 L). 정본은 `sprinkler_coverage` 하나이고,
      그 규칙은 `aot-geo-stats.js` 에 이미 적혀 있다(디자인 개요가 그것으로
      센다). **두 번째 계수 규칙을 만들지 말 것.**

    유량이 비어 있는 옛 이미터는 그 이미터가 든 구역의 기본값
    (`gen_config_sprinkler.flow`)으로 채운다 — 디자인 개요가 하는 backfill
    과 같다.
    """
    from shapely.geometry import Point

    from aot.databases.models import GeoShape

    q = GeoShape.query.filter_by(type='equipment_collection')
    if map_uuid:
        q = q.filter(GeoShape.geo_id == map_uuid)

    out = []
    zone_default = None          # 필요할 때만 만든다(대부분 flow 가 있다)
    for coll in q.all():
        for f in ((coll.feature or {}).get('features') or []):
            pr = f.get('properties') or {}
            if pr.get('sub_type') != _EMITTER_SUB_TYPE:
                continue
            pt = _sprinkler_point(f, pr)
            if pt is None:
                continue
            try:
                flow = float(pr.get('flow') or 0)
            except (TypeError, ValueError):
                flow = 0.0
            if flow <= 0:
                if zone_default is None:
                    zone_default = _zone_emitter_defaults(map_uuid)
                flow = _default_flow_at(pt, zone_default)
            if flow > 0:
                out.append((pt, flow))
    return out


def _zone_emitter_defaults(map_uuid):
    """구역 도형 → `[(polygon, 기본 유량)]`. 옛 이미터의 폴백용이다."""
    from shapely.geometry import shape as _shape

    from aot.databases.models import GeoShape

    q = GeoShape.query.filter_by(type='zone')
    if map_uuid:
        q = q.filter(GeoShape.geo_id == map_uuid)
    out = []
    for z in q.all():
        pr = ((z.feature or {}).get('properties') or {})
        cfg = pr.get('gen_config_sprinkler') or {}
        try:
            flow = float(cfg.get('flow') or 0)
        except (TypeError, ValueError):
            continue
        if flow <= 0:
            continue
        try:
            poly = _shape((z.feature or {}).get('geometry') or {})
        except Exception:
            continue
        if not poly.is_empty:
            out.append((poly, flow))
    return out


def _default_flow_at(pt, zone_defaults):
    for poly, flow in (zone_defaults or []):
        if poly.contains(pt):
            return flow
    return 0.0


def _sprinkler_point(feature, props):
    """스프링클러 하나의 위치 → shapely Point. 못 얻으면 None.

    그리기 도구가 원(circle)으로 저장한 것은 기하가 아니라
    `center_lat`/`center_lng` 에 중심을 둔다 — 그것을 먼저 본다.
    """
    from shapely.geometry import Point, shape as _shape
    try:
        if props.get('center_lat') is not None:
            return Point(float(props['center_lng']), float(props['center_lat']))
        geom = feature.get('geometry') or {}
        if geom.get('type') == 'Point':
            return Point(*geom['coordinates'][:2])
        if geom:
            return _shape(geom).centroid
    except Exception:
        return None
    return None


def _map_of_plot(plot):
    """구획이 놓인 지도 uuid → str 또는 None.

    구획은 지도를 직접 들지 않는다 — 감싸는 도형이 든다.
    """
    from aot.databases.models import GeoShape
    uid = getattr(plot, 'zone_uuid', None)
    if not uid:
        return None
    row = GeoShape.query.filter_by(unique_id=uid).first()
    return row.geo_id if row is not None else None


def irrigation_flow_for_plot(plot):
    """구획 → `{output_id: {'lph', 'share', 'source'}}`.

    ## 왜 설계 유량으로 추정하는가

    유량계(`measurement='volume'`)가 있으면 그 실측이 이긴다 — 이미
    `usage_from_stats()` 가 낸다. 그런데 **대부분의 밸브에는 유량계가 없다.**
    그렇다고 가동시간만 내놓으면 "물을 얼마나 줬나" 라는 농사의 기본 질문에
    이 문서가 답하지 못한다.

    시설 설계도가 그 답을 이미 갖고 있다. `irrigation_nozzles.nozzles_by_actuator()`
    가 **배관 물길로** 밸브별 노즐을 갈라(노즐 하나는 정확히 한 액추에이터에만
    속한다) 시간당 토출량(`total_flow_lph`)을 낸다. 가동시간을 곱하면 물량이다.

    ## 몫으로 나눈다

    시설 구획이 동의 일부만 차지하면(`allocation`) 그 밸브의 물이 전부 이
    구획 것이 아니다. 구획의 몫만큼 나누고 **그 사실을 표시한다**(`share`).
    구획이 자기 기하를 갖지 않는 것이 시설 구획의 정상이라, "구획 안 노즐만
    센다" 는 애초에 성립하지 않는다.

    ⚠ 이것은 **추정치다.** 노즐이 설계대로 달려 있고 막히지 않았다는 전제 위에
      서 있다 — 화면이 실측과 구분해 말해야 한다.
    """
    from aot.aot_flask.geo import irrigation_nozzles
    from aot.databases.models import GeoFacility

    facility_uuid = getattr(plot, 'facility_uuid', None)
    if not facility_uuid:
        # 노지 — 배관 도면은 없지만 지도에 그린 스프링클러가 유량을 갖고 있다.
        return _open_field_flow(plot)
    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if facility is None:
        return {}

    try:
        from aot.aot_flask.geo.device_binding import resolved_refs
        by_actuator = irrigation_nozzles.nozzles_by_actuator(
            resolved_refs(facility)[0])
    except Exception:
        logger.exception('journal: 노즐 유량 조회 실패 (%s)', facility_uuid)
        return {}
    if not by_actuator:
        return {}

    share = _allocation_share(plot)
    out = {}
    for output_id, summary in by_actuator.items():
        lph = summary.get('total_flow_lph')
        if not output_id or not lph:
            continue
        out[output_id] = {'lph': float(lph), 'share': share, 'source': 'design'}
    return out


def _allocation_share(plot):
    """구획이 그 동에서 차지하는 몫(0~1). 모르면 1.0.

    ⚠ **비율을 직접 계산하지 않는다.** 저장된 것은 `{"amount": 4}` 같은 절대
      값이고 비율은 동의 총량에서 **파생**한다 — `plot_context.allocation_view()`
      가 그 정본이다. 여기서 다시 나누면 총량이 바뀔 때 두 값이 조용히 갈린다
      (그 함수가 비율을 저장하지 않는 이유가 정확히 그것이다).

    ⚠ **모를 때 1.0 이다.** 0 으로 두면 물량이 통째로 0 이 되어 "관수를 안
      했다" 로 읽히는데, 실제로는 몫을 안 적었을 뿐이다.
    """
    facility_uuid = getattr(plot, 'facility_uuid', None)
    if not facility_uuid:
        return 1.0
    try:
        brief = plot_context.facility_brief(facility_uuid)
        view = plot_context.allocation_view(
            getattr(plot, 'allocation', None),
            (brief.get('bay_capacities') or {}).get(
                getattr(plot, 'bay_id', None)))
    except Exception:
        logger.exception('journal: 몫 산출 실패')
        return 1.0
    if not view or view.get('percent') in (None, ''):
        return 1.0
    try:
        pct = float(view['percent'])
    except (TypeError, ValueError):
        return 1.0
    return pct / 100.0 if 0.0 < pct <= 100.0 else 1.0
