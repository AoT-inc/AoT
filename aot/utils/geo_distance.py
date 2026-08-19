# coding=utf-8
"""지도 위 두 지점 사이의 거리 — 이름 또는 unique_id 로 해석한다.

설계 정본: docs/design/geo-vegetation-plot.md §"거리 조회"

## 왜 필요한가

LLM 은 좌표 산술을 조용히 틀린다. "관리사무소에서 가까운 순으로 품종을
배정해 달라" 같은 요청은 실제로 나왔고, 그때는 임시 스크립트로 중심점과
거리를 계산해 **숫자 목록을 만들어 준 뒤** LLM 이 그것을 읽게 했다. 그
계산을 도구로 고정한 것이 이 모듈이다 — LLM 은 거리를 만들지 않고 받는다.

## 이름 해석을 여기 따로 두는 이유

`_resolve_note_target` 을 쓰지 않는다. 그쪽은 **작물명을 구획이 아니라 소속
zone 으로 치환한다**(`_resolve_target_by_subject._one_zone`). 그래서 한 zone 을
5등분해 서로 다른 품종을 심은 상태에서 품종명 다섯 개를 넘기면 **다섯 개가
전부 같은 zone 중심으로 해석되어 거리가 전부 같게** 나온다. 형식은 멀쩡하고
숫자만 틀리는 종류라 알아채기 어렵다.

그렇다고 그 리졸버를 고칠 수도 없다 — 호출처 17곳 중 `add_schedule`·
`create_note`·`schedule_device_control` 이 **쓰기** 도구이고, "target 은
무언가를 쓸 수 있는 GeoShape 여야 한다"가 설계 정본이다(`_active_subject_plots`
docstring). 거기를 건드리면 예약이 GeoPlot uuid 에 걸린다.

그래서 **읽기전용 리졸버를 여기 따로 둔다**(`resolve_query`). 읽기전용이라
쓰기 리졸버가 못 하는 것을 할 수 있다 — 구획 자신을 가리키고, **모호하면
고르지 않고 후보를 uuid 와 함께 돌려준다.** 5-튜플 계약에는 "모호함" 을 담을
자리가 없어 쓰기 리졸버는 그냥 실패해야 했지만, 여기서는 되물을 수 있다.

검정콩을 다섯 조각에 심었으면 *"검정콩까지 거리"* 는 **답이 없는 질문**이다.
하나를 골라 답하면 그 숫자가 조용히 틀린다 — 그래서 고르지 않는다.

## 대표점 — 개체마다 정본이 하나씩

- **GeoShape**: `get_centroid()`(꼭짓점 평균). 면적 중심이 아니지만 **이미
  `get_address`·`get_local_time` 이 쓰는 정본**이라 그대로 쓴다. 여기서만
  면적 중심으로 바꾸면 "3-1 이 어디냐"에 대한 답이 도구마다 달라진다 —
  이 저장소가 반복해서 데인 형태다.
- **GeoPlot**: 면적 중심(shapely `centroid`). 구획에는 기존 정본이
  없었으므로 옳은 쪽을 고른다. 오목 구획에서 중심이 밖으로 나가면
  `representative_point()` 로 떨어진다.
- **장치(Input/Output/…)**: 자기 `latitude`/`longitude` 컬럼.

## 거리 정의

**중심점 사이의 직선거리**다. 맞닿은 두 구획도 중심이 40m 떨어져 있으면
40m 로 답한다 — 경계 사이 최단거리가 아니다. 응답의 `basis` 가 이것을
매번 말한다(안 적으면 읽는 쪽이 경계 거리로 오해한다).

투영은 새 라이브러리를 들이지 않고 `plot_context`·`facility_calc` 가
쓰는 것과 **같은 평면 근사**를 쓴다 — 같은 지도에서 면적과 거리가 다른
평면에서 재어지면 설명 없이 어긋난다.
"""
import logging
import math

logger = logging.getLogger(__name__)

# 위도 1도 = 111320 m. 이 저장소가 이미 여섯 곳에서 쓰는 상수와 같은 값이다
# (plot_context.py:131, facility_calc.py:117, geo_photo_georef.py 등).
_M_PER_DEG_LAT = 111320.0

# 한 번에 견줄 수 있는 후보 수. 넘으면 잘라내지 않고 **거부한다** — 조용히
# 자르면 호출자는 자기가 본 것이 전부인 줄 안다(plot_split 과 같은 규칙).
_MAX_CANDIDATES = 200


def distance_m(lat1, lng1, lat2, lng2):
    """두 위경도 사이의 직선거리(m). 평면 근사 — 위 모듈 docstring 참조."""
    mid_lat = (float(lat1) + float(lat2)) / 2.0
    m_per_deg_lng = _M_PER_DEG_LAT * math.cos(math.radians(mid_lat))
    dx = (float(lng2) - float(lng1)) * m_per_deg_lng
    dy = (float(lat2) - float(lat1)) * _M_PER_DEG_LAT
    return math.hypot(dx, dy)


def _plot_point(row):
    """GeoPlot → (lat, lng) 또는 None. 면적 중심, 오목이면 대표점."""
    from aot.aot_flask.geo import plot_context

    poly = plot_context._shapely(plot_context.geometry_of(row))
    if poly is None or poly.is_empty:
        return None
    try:
        pt = poly.centroid
        if not poly.contains(pt):
            # 오목 구획에서 면적 중심이 도형 밖으로 나가는 경우. 밖의 점을
            # "이 구획의 위치" 라고 말할 수는 없다.
            pt = poly.representative_point()
        return (pt.y, pt.x)
    except Exception as exc:
        logger.warning('geo_distance: 구획 대표점 실패: %s', exc)
        return None


def _plot_label(row):
    """구획 표시명. 분할로 만든 구획은 `name` 이 비어 있는 것이 정상이라
    (이름 없이 조각만 만들어진다) 작물명이 실질적인 정체성이다."""
    name = (getattr(row, 'name', None) or '').strip()
    if name:
        return name
    subject = (getattr(row, 'subject', None) or '').strip()
    variety = (getattr(row, 'variety', None) or '').strip()
    if subject and variety:
        return '%s (%s)' % (subject, variety)
    if subject:
        return subject
    return str(getattr(row, 'unique_id', ''))[:8]


def _point_from_shape(shape):
    """GeoShape 행 → 대표점 dict 또는 None."""
    centroid = shape.get_centroid()
    if not centroid:
        return None
    from aot.aot_flask.geo import plot_context

    _tt = shape.type if shape.type in (
        'zone', 'site', 'facility', 'facility_bay', 'equipment') else 'zone'
    return {
        'target_id': shape.unique_id,
        'target_type': _tt,
        'resolved_name': plot_context._shape_name(shape) or shape.unique_id[:8],
        'lat': centroid[0],
        'lng': centroid[1],
    }


def _point_from_plot(row):
    """GeoPlot 행 → 대표점 dict 또는 None."""
    point = _plot_point(row)
    if not point:
        return None
    return {
        'target_id': row.unique_id,
        'target_type': 'plot',
        'resolved_name': _plot_label(row),
        'lat': point[0],
        'lng': point[1],
    }


def resolve_point(target_id):
    """unique_id → {'target_id', 'target_type', 'resolved_name', 'lat', 'lng'}
    또는 `(None, 오류문구)` 대신 None.

    디스패치 순서는 `device_tz.resolve_location_coords` 를 따르되 그 사이에
    GeoPlot 을 끼운다 — 그쪽은 구획을 모르고, 그쪽에 넣으면
    `get_address`/`get_local_time` 의 동작까지 함께 바뀐다.
    """
    if not target_id or str(target_id).strip().lower() in ('', 'none'):
        return None
    tid = str(target_id).strip()

    # 1) GeoShape — 좌표는 get_address 와 **같은** 헬퍼에서 나와야 한다.
    try:
        from aot.databases.models.geo import GeoShape
        shape = GeoShape.query.filter_by(unique_id=tid).first()
        if shape is not None:
            point = _point_from_shape(shape)
            if point:
                return point
    except Exception as exc:
        logger.debug('geo_distance: GeoShape 조회 실패 %s: %s', tid, exc)

    # 2) GeoPlot — 여기가 resolve_location_coords 에 없는 층위다.
    try:
        from aot.databases.models import GeoPlot
        row = GeoPlot.query.filter_by(unique_id=tid).first()
        if row is not None:
            point = _point_from_plot(row)
            if point:
                return point
    except Exception as exc:
        logger.debug('geo_distance: GeoPlot 조회 실패 %s: %s', tid, exc)

    # 3) 장치 — 자기 lat/lng 컬럼. 기존 리졸버를 그대로 쓴다.
    try:
        from aot.utils.device_tz import resolve_location_coords
        lat, lng = resolve_location_coords(tid)
        if lat is not None and lng is not None:
            from aot.databases.models import (
                Input, Output, Function, Conditional, Trigger, PID,
                CustomController)
            label, ttype = tid[:8], 'device'
            for model, _tt in ((Input, 'input'), (Output, 'output'),
                               (Function, 'function'), (Conditional, 'conditional'),
                               (Trigger, 'trigger'), (PID, 'pid'),
                               (CustomController, 'custom_controller')):
                dev = model.query.filter_by(unique_id=tid).first()
                if dev is not None:
                    label = (getattr(dev, 'name', None) or tid[:8])
                    ttype = _tt
                    break
            return {'target_id': tid, 'target_type': ttype,
                    'resolved_name': label, 'lat': lat, 'lng': lng}
    except Exception as exc:
        logger.debug('geo_distance: 장치 조회 실패 %s: %s', tid, exc)

    return None


# ---------------------------------------------------------------------------
# 이름 해석
# ---------------------------------------------------------------------------
#
# `_resolve_note_target` 을 쓰지 않고 여기 따로 두는 이유는 모듈 docstring 에
# 적었다 — 그쪽은 작물명을 **소속 zone 으로 치환**하고(쓰기 도구가 GeoShape 에
# 써야 하므로 그게 맞다), 그래서 한 zone 을 나눠 심은 품종들이 전부 같은 좌표가
# 된다. 여기는 읽기전용이라 구획 자신을 가리킬 수 있고, **모호하면 고르지 않고
# 후보를 돌려준다** — 쓰기 리졸버가 못 하는 선택지다(5-튜플에 자리가 없다).

# 모호할 때 응답에 싣는 후보 수. 넘으면 개수만 알린다 — 200개를 나열하면
# 그 자체가 읽히지 않는다.
_MAX_AMBIGUOUS_LISTED = 10


def _named_shapes():
    """이름이 있는 GeoShape 전부 → [(shape, name_lower)]."""
    from aot.databases.models.geo import GeoShape
    from aot.aot_flask.geo import plot_context

    out = []
    for shape in GeoShape.query.all():
        name = plot_context._shape_name(shape)
        if name and str(name).strip():
            out.append((shape, str(name).strip().lower()))
    return out


def _active_plot_rows():
    """재배 중인 GeoPlot 전부.

    **활성만 본다** — 작년 배추가 올해 거리 질문을 끌고 가면 안 된다
    (`_resolve_target_by_subject` 과 같은 규율).
    """
    from aot.databases.models import GeoMap
    from aot.aot_flask.geo import plot_context

    rows = []
    try:
        maps = GeoMap.query.all()
    except Exception:
        return rows
    for m in maps:
        try:
            rows.extend(plot_context.active_plots(m.unique_id))
        except Exception:
            continue
    return rows


def _named_devices():
    """이름이 있는 Input/Output → [(row, type, name_lower)]."""
    from aot.databases.models import Input, Output

    out = []
    for model, _tt in ((Input, 'input'), (Output, 'output')):
        try:
            for row in model.query.all():
                name = (getattr(row, 'name', None) or '').strip()
                if name:
                    out.append((row, _tt, name.lower()))
        except Exception:
            continue
    return out


def _plot_fields(row):
    """구획이 불릴 수 있는 이름들(소문자). 분할 구획은 `name` 이 비어 있고
    작물명이 실질적 정체성이라 subject/variety 도 함께 본다."""
    vals = []
    for attr in ('name', 'subject', 'variety'):
        v = (getattr(row, attr, None) or '').strip()
        if v:
            vals.append(v.lower())
    return vals


def build_catalog():
    """이름 검색이 훑는 세 목록을 **한 번만** 만든다.

    `nearest` 는 후보마다 `resolve_query` 를 부르므로, 이것을 안 넘기면 후보
    200개에 대해 전체 도형·구획·장치 스캔이 200번 돈다.
    """
    try:
        return {'shapes': _named_shapes(),
                'plots': _active_plot_rows(),
                'devices': _named_devices()}
    except Exception as exc:
        logger.debug('geo_distance: 이름 카탈로그 준비 실패: %s', exc)
        return {'shapes': [], 'plots': [], 'devices': []}


def resolve_query(query, catalog=None):
    """이름 또는 unique_id → `(point, candidates)`.

    - `(point, [])`        — 정확히 하나로 해석됐다
    - `(None, [후보…])`    — 모호하다. **고르지 않는다**
    - `(None, [])`         — 못 찾았다

    층위 순서(위에서 하나라도 걸리면 아래로 안 내려간다):
      0. unique_id
      1. GeoShape 이름 정확일치 — 지도의 정식 어휘가 항상 이긴다.
         구획 이름이 우연히 '3-1' 이어도 구역 '3-1' 이 먼저다.
      2. 활성 구획의 name / subject / variety 정확일치
      3. 장치 이름 정확일치
      4. 부분일치 — 위 셋을 한꺼번에 본다. **양쪽 다 두 글자 이상**일 때만
         허용한다(한 글자 작물명 '마' 가 '고구마' 에 걸리는 것을 막는다 —
         `_resolve_note_target` 이 같은 가드를 쓴다).

    정확일치 층에서 여러 개가 나오면 그것은 **진짜 모호**다. 검정콩을 다섯
    조각에 심었으면 "검정콩까지 거리" 는 답이 없는 질문이고, 하나를 골라
    답하면 그 숫자가 조용히 틀린다.
    """
    if query is None:
        return None, []
    q = str(query).strip()
    if not q or q.lower() == 'none':
        return None, []
    ql = q.lower()

    # 0) unique_id 가 먼저다 — 도구 체이닝(앞선 호출이 낸 uuid)이 이름 검색을
    #    거치면 안 된다.
    point = resolve_point(q)
    if point is not None:
        return point, []

    def _finish(points):
        points = [p for p in points if p]
        if len(points) == 1:
            return points[0], []
        if len(points) > 1:
            return None, points
        return None, None      # 이 층에서 없음 — 다음 층으로

    cat = catalog if catalog is not None else build_catalog()
    shapes = cat.get('shapes') or []
    plots = cat.get('plots') or []
    devices = cat.get('devices') or []

    # 1) GeoShape 정확일치
    got, cands = _finish([_point_from_shape(s)
                          for (s, nl) in shapes if nl == ql])
    if got or cands:
        return got, cands

    # 2) 활성 구획 정확일치
    got, cands = _finish([_point_from_plot(r)
                          for r in plots if ql in _plot_fields(r)])
    if got or cands:
        return got, cands

    # 3) 장치 정확일치
    got, cands = _finish([resolve_point(r.unique_id)
                          for (r, _tt, nl) in devices if nl == ql])
    if got or cands:
        return got, cands

    # 4) 부분일치 — 세 종류를 한꺼번에. 한 글자는 통째로 건너뛴다.
    if len(ql) < 2:
        return None, []
    def _loose(hay):
        return len(hay) >= 2 and (ql in hay or hay in ql)

    loose = [_point_from_shape(s) for (s, nl) in shapes if _loose(nl)]
    loose += [_point_from_plot(r) for r in plots
              if any(_loose(f) for f in _plot_fields(r))]
    loose += [resolve_point(r.unique_id) for (r, _tt, nl) in devices if _loose(nl)]
    got, cands = _finish(loose)
    return got, (cands or [])


def _ambiguous_error(query, candidates):
    """모호할 때의 응답 — 후보를 **uuid 와 함께** 낸다. 그래야 다음 호출이
    바로 uuid 로 되물을 수 있다(이름으로 되물으면 같은 자리에 다시 걸린다)."""
    listed = candidates[:_MAX_AMBIGUOUS_LISTED]
    return {
        'error': ('%r matches %d things — say which one (pass its unique_id). '
                  'A subject placed in several plots is the usual cause.'
                  % (query, len(candidates))),
        'needs_disambiguation': True,
        'query': query,
        'candidates': [_brief(c) for c in listed],
        'candidates_shown': len(listed),
        'candidates_total': len(candidates),
    }


BASIS = ('Straight-line distance between the entities\' centre points, NOT the '
         'shortest gap between their edges — two plots that touch can still be '
         'tens of metres apart by this measure.')


_NOT_FOUND = ('could not locate %r — pass its name as the grower says it, or a '
              'unique_id from list_plots / get_spatial_tree / search_devices')


def distance_between(a_query, b_query):
    """두 개체(이름 또는 uuid) 사이의 거리 → (결과, None) 또는 (None, 오류).

    오류는 문구(str)이거나, 모호할 때는 후보를 실은 dict 다 — 호출자는 그것을
    사람에게 그대로 보여 되물어야 한다.
    """
    catalog = build_catalog()
    resolved = {}
    for key, q in (('a', a_query), ('b', b_query)):
        point, candidates = resolve_query(q, catalog=catalog)
        if point is None:
            if candidates:
                return None, _ambiguous_error(q, candidates)
            return None, _NOT_FOUND % q
        resolved[key] = point

    a, b = resolved['a'], resolved['b']
    d = distance_m(a['lat'], a['lng'], b['lat'], b['lng'])
    return {'a': _brief(a), 'b': _brief(b),
            'distance_m': round(d, 1), 'basis': BASIS}, None


def nearest(reference_query, candidate_queries):
    """기준 하나 + 후보 목록(이름 또는 uuid) → 가까운 순 정렬.

    **조용히 줄이지 않는다.** 못 찾은 것은 `unresolved`, 여러 개에 걸린 것은
    `ambiguous` 로 따로 낸다 — 목록이 짧아진 것을 두고 "그건 멀어서 빠졌나"
    라고 읽으면 안 된다. 특히 모호한 쪽은 **답이 있는데 못 고른 것**이라
    없는 것과 완전히 다르다.
    """
    catalog = build_catalog()
    ref, ref_cands = resolve_query(reference_query, catalog=catalog)
    if ref is None:
        if ref_cands:
            return None, _ambiguous_error(reference_query, ref_cands)
        return None, _NOT_FOUND % reference_query

    queries = [str(c).strip() for c in (candidate_queries or [])
               if str(c or '').strip()]
    if not queries:
        return None, 'candidates is required (names or unique_ids)'
    if len(queries) > _MAX_CANDIDATES:
        return None, ('that is %d candidates, more than this tool compares '
                      '(%d). Narrow the list.' % (len(queries), _MAX_CANDIDATES))

    results, unresolved, ambiguous = [], [], []
    for q in queries:
        item, cands = resolve_query(q, catalog=catalog)
        if item is None:
            if cands:
                listed = cands[:_MAX_AMBIGUOUS_LISTED]
                ambiguous.append({'query': q,
                                  'candidates': [_brief(c) for c in listed],
                                  'candidates_total': len(cands)})
            else:
                unresolved.append(q)
            continue
        entry = _brief(item)
        entry['distance_m'] = round(
            distance_m(ref['lat'], ref['lng'], item['lat'], item['lng']), 1)
        results.append(entry)

    results.sort(key=lambda r: r['distance_m'])
    return {'reference': _brief(ref), 'results': results,
            'count': len(results),
            'unresolved': unresolved or None,
            'ambiguous': ambiguous or None,
            'basis': BASIS}, None


def _brief(point):
    """좌표를 응답에 싣지 않는다 — 호출자가 좌표로 다시 계산하기 시작하면
    이 도구를 만든 이유가 사라진다(거리는 서버가 낸다)."""
    return {'target_id': point['target_id'],
            'target_type': point['target_type'],
            'resolved_name': point['resolved_name']}
