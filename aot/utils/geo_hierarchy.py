"""Site → zone (and deeper) GeoShape hierarchy resolution.

포함 판정의 기준점은 `containment_point()` 하나다 — 이 도메인은 "읽는 경로마다
기준이 다름"으로 이미 크게 데었고, 포함 판정도 그랬다(2026-08-14 실측: 완전포함
`contains(g)` · 대표점 · 중심점 `centroid` 세 갈래가 동시에 돌고 있었다).


GeoShape.parent_id is the intended parent FK, but in production data it is
left NULL on every site/zone row (checked 2026-07-24) — the only real signal
that a zone belongs to a site is that the zone's polygon is drawn spatially
inside the site's polygon on the map. AIContextService.get_spatial_hierarchy
already has a spatial fallback, but it only tests Point-in-polygon (device
markers), never Polygon-in-polygon (a zone inside a site), so it silently
flattens site/zone into unrelated siblings. This module is the one place
that resolves that relationship properly, so every AI tool/service that
needs "which zones belong to this site" computes it the same way.
"""
import json as _json


def _parse_geometry(shape_row):
    try:
        from shapely.geometry import shape as _shapely_shape
    except Exception:
        return None
    try:
        feat = shape_row.feature if isinstance(shape_row.feature, dict) else _json.loads(shape_row.feature or '{}')
        geometry = feat.get('geometry')
        if not geometry:
            return None
        g = _shapely_shape(geometry)
        return g if g.is_valid else None
    except Exception:
        return None


def containment_point(g):
    """포함 판정에 쓸 대표점. 소속 판정의 단일 기준이다.

    **완전 포함(`contains(g)`)을 쓰지 말 것.** 경계를 조금 넘은 도형이 통째로
    빠져 소속이 한 단계 위로 밀린다 — 실측에서 밸브 담당구역 10개가 자기 zone
    (`1-4` 등)을 못 찾고 site(`1포장`)로 밀렸고, zone 하나는 부모를 아예 잃었다.

    **`centroid` 도 쓰지 말 것.** 오목한 폴리곤(ㄷ자 구역·도넛 필지)에서는
    중심점이 자기 밖으로 나가 남의 구역에 떨어지거나 아무 데도 안 걸린다.
    `representative_point()` 는 반드시 내부에 있음이 보장된다. (현재 데이터에는
    그런 도형이 0개라 아직 증상이 없을 뿐, 구역을 ㄷ자로 그리는 순간 터진다.)

    Point 기하는 그 자신이 대표점이라 마커 판정은 지금과 완전히 동일하다.
    """
    if g is None:
        return None
    try:
        return g if g.geom_type == 'Point' else g.representative_point()
    except Exception:
        return None


def build_geo_parent_map(all_shapes):
    """Map every GeoShape.id -> its parent's id (or None), across the given
    shape rows. parent_id wins when set; otherwise the smallest site/zone
    polygon that spatially contains the shape (Point marker OR Polygon
    zone/site) is used.
    """
    geoms = {s.id: _parse_geometry(s) for s in all_shapes}
    containers = [(s.id, geoms[s.id]) for s in all_shapes
                  if s.type in ('site', 'zone') and geoms.get(s.id) is not None
                  and geoms[s.id].geom_type in ('Polygon', 'MultiPolygon')]
    valid_ids = {s.id for s in all_shapes}

    def _find_parent(s):
        if s.parent_id:
            if s.parent_id in valid_ids:
                return s.parent_id
            # parent_id 가 존재하지 않는 도형을 가리키면(dangling) 그 값을
            # 믿지 않는다 — 그대로 반환하면 이 도형은 루트로도(부모값이
            # None 이 아니므로) 누구의 자식으로도(그 parent_id 를 가진
            # 도형이 실재하지 않으므로) 안 잡혀 트리 어디에도 나타나지
            # 않고 조용히 사라진다. 공간 포함 검사로 재시도하고, 그것도
            # 실패하면 최후에 None(루트)으로 노출한다 — "안 보임"보다
            # "위치가 아리송한 채로라도 보임" 이 낫다.
        g = geoms.get(s.id)
        if g is None or g.geom_type not in ('Point', 'Polygon', 'MultiPolygon'):
            return None
        pt = containment_point(g)
        if pt is None:
            return None
        # 자기보다 작은 도형은 부모가 될 수 없다. 완전 포함 판정은 이것을
        # 암묵적으로 보장했지만(작은 zone 이 큰 site 를 통째로 담을 수는 없다)
        # 대표점으로 바꾸면 그 보호가 사라진다 — 실측에서 site '2포장' 의
        # 대표점이 하필 자기 안의 zone '2-2' 에 떨어져, 자식이 부모로 뒤집혔다.
        own_area = getattr(g, 'area', 0.0) or 0.0
        matches = []
        for cid, cg in containers:
            if cid == s.id:
                continue
            try:
                if cg.area < own_area:
                    continue
                if cg.contains(pt):
                    matches.append((cid, cg.area))
            except Exception:
                continue
        if not matches:
            return None
        # Smallest containing polygon = most specific parent (a zone before
        # the site it sits in).
        matches.sort(key=lambda m: m[1])
        return matches[0][0]

    return {s.id: _find_parent(s) for s in all_shapes}


def geo_descendant_shapes(root_shape, all_shapes=None):
    """Every GeoShape nested under root_shape (e.g. a site's child zones),
    breadth-first, deepest levels included. Returns GeoShape rows.
    """
    if all_shapes is None:
        from aot.databases.models import GeoShape
        all_shapes = GeoShape.query.all()

    parent_map = build_geo_parent_map(all_shapes)
    children_map = {}
    for s in all_shapes:
        pid = parent_map.get(s.id)
        if pid is not None:
            children_map.setdefault(pid, []).append(s)

    out, seen, frontier = [], {root_shape.id}, [root_shape.id]
    while frontier:
        nxt = []
        for pid in frontier:
            for child in children_map.get(pid, []):
                if child.id in seen:
                    continue
                seen.add(child.id)
                nxt.append(child.id)
                out.append(child)
        frontier = nxt
    return out


def geo_descendant_unique_ids(root_shape, all_shapes=None):
    """Convenience wrapper: unique_ids of geo_descendant_shapes()."""
    return [s.unique_id for s in geo_descendant_shapes(root_shape, all_shapes=all_shapes) if s.unique_id]


# ─── 노트·일정이 붙을 수 있는 자리 전부 ────────────────────────────────────
#
# "3포장의 예정을 요약해" 는 3포장 **안에서 일어나는 일** 을 묻는 것이지 3포장
# 도형 자체에 붙은 것만 묻는 것이 아니다. 그런데 조회는 `target_id ==` 정확
# 일치였다 — 실측(2026-08-18, 김제): `search_schedule('3포장')` 이 0건을 돌려
# 주는데 실제로는 구역에 1건, 그 안 식생에 2건이 있었다.
#
# 더 나쁜 것은 **에러가 아니라 0건** 이라는 점이다. AI 는 그것을 "예정 없음"
# 으로 읽고 "충돌 없습니다" 라고 답한다. 없는 것과 못 찾는 것이 같은 응답이라
# 틀린 답이 확신에 찬 문장으로 나온다.
#
# 한 대상 아래에는 **정체성이 여러 벌** 있어서 도형 uuid 만으로는 부족하다:
#   - 시설: `GeoFacility.unique_id` ≠ 그 시설 도형의 `unique_id`.
#     노트·일정은 GeoFacility 쪽에 붙는데 기하는 도형 쪽이다.
#   - 장치 마커: 노트는 마커가 아니라 그 Input/Output 의 uuid 에 붙는다
#     (`shape.device_id`).
#   - 식생: `GeoPlanting` 은 GeoShape 가 **아니라서** 자손 순회에 아예 안
#     들어간다. 소속 컬럼도 없어 기하로 판정해야 한다.
# 하나라도 빠뜨리면 그 종류에 붙은 것만 조용히 사라진다.


def _planting_ids_inside(shape_ids, geo_ids=None):
    """주어진 도형들 안에 있는 활성 GeoPlanting 의 unique_id.

    식생은 소속 컬럼이 없다(설계상 소속은 저장하지 않고 파생한다 —
    docs/design/geo-vegetation-planting.md). 쓰기(장치 소속)에는 맞는 원칙이지만
    읽기에서는 "식생만 안 보인다" 로 나타나므로, 조회 시점에 기하로 판정한다.
    """
    from shapely.geometry import shape as _shapely_shape
    from aot.databases.models import GeoShape, GeoPlanting
    from aot.aot_flask.geo import planting_context

    if not shape_ids:
        return []

    polys = []
    for row in GeoShape.query.filter(GeoShape.unique_id.in_(list(shape_ids))).all():
        try:
            g = _parse_geometry(row)
            if g is not None and not g.is_empty:
                polys.append(g)
        except Exception:
            continue
    if not polys:
        return []

    q = GeoPlanting.query.filter(GeoPlanting.ended_on.is_(None))
    if geo_ids:
        q = q.filter(GeoPlanting.geo_id.in_(list(geo_ids)))

    out = []
    for pl in q.all():
        try:
            geom = planting_context.geometry_of(pl)
            pt = containment_point(_shapely_shape(geom))
            if pt is None:
                continue
            if any(poly.contains(pt) for poly in polys):
                out.append(pl.unique_id)
        except Exception:
            continue
    return out


def descendant_target_ids(root_shape, all_shapes=None, include_self=True):
    """이 대상 아래에서 노트·일정이 붙을 수 있는 target_id 전부.

    돌려주는 것은 `(ids, breakdown)` — `breakdown` 은 무엇을 얼마나 훑었는지를
    사람과 AI 에게 말하기 위한 것이다. **개수를 함께 돌려주는 이유**: 결과가
    0건일 때 "정말 없다" 와 "못 찾았다" 를 구분할 근거가 그것뿐이다.
    """
    from aot.databases.models import GeoFacility

    ids, breakdown = [], {'self': 0, 'shapes': 0, 'facilities': 0,
                          'devices': 0, 'plantings': 0}
    if root_shape is None:
        return ids, breakdown

    shape_ids = []
    if include_self and root_shape.unique_id:
        ids.append(root_shape.unique_id)
        shape_ids.append(root_shape.unique_id)
        breakdown['self'] = 1

    kids = geo_descendant_shapes(root_shape, all_shapes=all_shapes)
    for k in kids:
        if k.unique_id:
            ids.append(k.unique_id)
            shape_ids.append(k.unique_id)
            breakdown['shapes'] += 1
        # 장치 마커의 노트는 마커가 아니라 그 Input/Output 에 붙는다.
        if k.device_id:
            ids.append(str(k.device_id).split('::')[0])
            breakdown['devices'] += 1

    # 시설은 정체성이 둘이다 — 노트·일정은 GeoFacility uuid 쪽에 붙는다.
    fac_shape_ids = [s.unique_id for s in ([root_shape] + list(kids))
                     if s.type == 'facility' and s.unique_id]
    if fac_shape_ids:
        try:
            for f in GeoFacility.query.filter(
                    GeoFacility.shape_uuid.in_(fac_shape_ids)).all():
                if f.unique_id:
                    ids.append(f.unique_id)
                    breakdown['facilities'] += 1
        except Exception:
            pass

    geo_ids = {s.geo_id for s in ([root_shape] + list(kids)) if getattr(s, 'geo_id', None)}
    try:
        for pid in _planting_ids_inside(shape_ids, geo_ids=geo_ids):
            ids.append(pid)
            breakdown['plantings'] += 1
    except Exception:
        pass

    # 순서를 지키며 중복 제거 — 첫 항목이 root 자신이어야 호출자가 "자기 것"
    # 을 먼저 보여줄 수 있다.
    seen, uniq = set(), []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq, breakdown
