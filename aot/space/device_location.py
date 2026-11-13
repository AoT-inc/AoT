# coding=utf-8
"""장치 위치의 단일 리졸버 — `locate()`.

위치는 장치의 속성이 아니라 **배치(geo_binding 자리)의 결과**다
(2026-11-04 확정 "장치 위치 정보의 정본 하나", L1a). 시간대·일출·날씨·구역 소속·
지도·AI·거리 소비자가 전부 이 함수 하나만 읽게 되는 것이 목표다. 이 모듈은
읽기 전용이다 — 쓰기는 `device_binding.bind/unbind/rebind`, `device_placement`.

## 우선순위 (확정 결정 ③)

현재 유효한 바인딩 중 ① 마커 > ② 설비 항목(fitting/actuator) > ③ 구역(shape
폴리곤) > ④ 역할(sensor_role/weather; 시설 중심). 같은 등급이 여럿이면
`valid_from` 최신. `channel_id` 를 주면 그 채널 바인딩을 먼저, 없으면 장치 단위
('0'), 그것도 없으면 아무 채널이나.

바인딩이 **한 번이라도** 있었던 장치는 레거시를 읽지 않는다 — 끝난 연결이
레거시 컬럼으로 되살아나는 것을 막는 `device_binding.VACATED` 와 같은 규칙이다.

## 정밀도

`source='fitting'` 이어도 `point` 는 **시설 중심**이다 — fittings/actuators 항목에는 위경도가 없다(시설 로컈
좌표). 이를 `precision='facility'` 로 표시한다(마커 `point`, 구역 `area`, 대지 `site`).
항목에 `bay_id` 가 있으면 chain 의 bay 는 그 bay 다(시설 중심으로 고르지 않는다).

## tz 순서

앵커 자체 → 앵커의 부모 도형 체인 → 앵커가 속한 시설. 단 앵커가 시설인 경우(설비 항목·역할)는
시설 timezone 이 먼저, 그다음 외곡선 도형·부모 체인이다.

## 폴백

바인딩 이력이 없으면(레거시 마커·장치 행 lat/lng 폴백은 L4 에서 제거) 지도의 site 가 하나뿐일 때 그 중심(`basis='site'`). 농장
`Misc` 좌표·시간대 폴백은 여기서 하지 않는다 — 소비자(timekit)가 자기 자리에서
한다. 좌표→시간대 변환(timezonefinder)도, 장치 행 tz 캐시 읽기도 하지 않는다
(결정 ①: 장치별 tz 컬럼은 공간 상속으로 폐지).

None 은 장치 자체가 없을 때만 돌려준다.

@phase active
@stability experimental
"""
import logging
from datetime import datetime
from typing import Iterable, NamedTuple, Optional

from aot.databases.models import GeoBinding, GeoFacility, GeoMap, GeoShape
from aot.utils.timekit import naive_utc

logger = logging.getLogger(__name__)

# 포함 판정에서 사슬에 오르는 도형 종류 → 사슬 kind.
_CHAIN_SHAPE_KINDS = {'site': 'site', 'zone': 'zone',
                      'facility': 'facility', 'facility_bay': 'bay'}


class PlaceRef(NamedTuple):
    kind: str            # 'site' | 'zone' | 'facility' | 'bay'
    unique_id: str
    name: str


class SlotRef(NamedTuple):
    spatial_kind: str
    spatial_id: str
    role: str
    channel_id: str


class Placement(NamedTuple):
    point: Optional[tuple]          # (lat, lng)
    chain: tuple                    # tuple[PlaceRef, ...] 바깥→안
    tz: Optional[str]               # IANA, 자리에서 상속된 것만
    source: str                     # marker|fitting|area|facility|site|none
    slot: Optional[SlotRef]         # 어느 바인딩에서 왔는가 (레거시·폴백이면 None)
    basis: str                      # 'device' | 'site' | 'none'
    # 점의 정밀도 — source='fitting' 이어도 좌표는 시설 중심이다(항목에는 자체
    # 좌표가 없다). 소비자가 "이 점은 대략"을 표시할 근거.
    precision: str = 'none'         # 'point'|'facility'|'area'|'site'|'none'


_NONE = Placement(None, (), None, 'none', None, 'none', 'none')


def _rank_source(spatial_kind, shape):
    """바인딩 → (등급, source). 등급이 작을수록 대표 자리."""
    from aot.space.device_membership import (_MARKER_TYPES,
                                                      _marker_point)
    if spatial_kind == 'shape':
        if shape is not None and shape.type in _MARKER_TYPES \
                and _marker_point(shape) is not None:
            return 0, 'marker'
        return 2, 'area'
    if spatial_kind in ('fitting', 'actuator'):
        return 1, 'fitting'
    return 3, 'facility'          # sensor_role / weather


def _valid_tz(name):
    """IANA 이름이면 그 이름, 아니면 None (깨진 값은 "없음")."""
    from aot.utils.timekit import _valid_tz_name
    tz = _valid_tz_name(name)
    return tz.zone if tz is not None else None


def _shape_point(shape):
    """도형 → (lat, lng). 점은 그 점, 그 외는 꼭짓점 평균(`get_centroid`)."""
    from aot.space.device_membership import _marker_point
    mp = _marker_point(shape)
    if mp is not None:
        return mp[1], mp[0]
    return shape.get_centroid()


def _q(cx, model):
    return model.query if cx.session is None else cx.session.query(model)


def _chunks(ids, n=500):
    ids = sorted(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _all_in(cx, model, col, ids, *extra):
    """`col IN ids` 를 500개씩 끊어 조회한다(SQLite 변수 상한)."""
    out = []
    for part in _chunks(ids):
        out.extend(_q(cx, model).filter(col.in_(part), *extra).all())
    return out


class _Ctx:
    """한 번의 `locate_many` 가 읽은 것 전부 — 질의는 여기서만 나간다."""

    def __init__(self, session=None):
        self.session = session
        self.rows = {}            # (kind, id) → 장치 행
        self.bindings = {}        # device_id → [GeoBinding] (이력 포함)
        self.shapes = {}          # unique_id → GeoShape
        self.facs = {}            # unique_id → GeoFacility
        self.fac_by_shape = {}    # shape_uuid → GeoFacility
        self.map_shapes = {}      # geo_id → [GeoShape]
        self.by_id = {}           # GeoShape.id → GeoShape
        self.parent = {}          # GeoShape.id → parent id
        self.map_facs = {}        # geo_id → [GeoFacility]
        self._geom = {}
        self.sole_map = None

    def geom(self, shape):
        from aot.utils.geo_hierarchy import _parse_geometry
        if shape.id not in self._geom:
            self._geom[shape.id] = _parse_geometry(shape)
        return self._geom[shape.id]


def _load(pairs, at, session=None):
    from aot.space.device_binding import device_kind_models
    from aot.space.device_membership import _MARKER_TYPES
    from aot.utils.geo_hierarchy import (_parent_map_from_cache,
                                         build_geo_parent_map)

    models = dict(device_kind_models())
    by_kind = {}
    for kind, did in pairs:
        if kind not in models:
            raise ValueError('알 수 없는 device_kind: %r (허용: %s)'
                             % (kind, ', '.join(models)))
        by_kind.setdefault(kind, set()).add(str(did))

    cx = _Ctx(session)
    for kind, ids in by_kind.items():
        m = models[kind]
        for r in _all_in(cx, m, m.unique_id, ids):
            cx.rows[(kind, r.unique_id)] = r
    dev_ids = {did for (_k, did) in cx.rows}
    if not dev_ids:
        return cx

    kinds = {k for (k, _d) in cx.rows}
    for b in _all_in(cx, GeoBinding, GeoBinding.device_id, dev_ids,
                     GeoBinding.device_kind.in_(kinds)):
        if (b.device_kind, b.device_id) in cx.rows:
            cx.bindings.setdefault(b.device_id, []).append(b)

    unbound = dev_ids - set(cx.bindings)

    # 바인딩이 가리키는 도형·시설
    shape_uids = set()
    fac_uids = set()
    for bs in cx.bindings.values():
        for b in bs:
            if b.spatial_kind == 'shape':
                shape_uids.add(b.spatial_id)
            else:
                fac_uids.add(b.spatial_id.split(':', 1)[0])
    if fac_uids:
        for f in _all_in(cx, GeoFacility, GeoFacility.unique_id, fac_uids):
            cx.facs[f.unique_id] = f
            cx.fac_by_shape[f.shape_uuid] = f
            shape_uids.add(f.shape_uuid)
    if shape_uids:
        for s in _all_in(cx, GeoShape, GeoShape.unique_id, shape_uids):
            cx.shapes[s.unique_id] = s

    # 기본 지도: 사슬·부모 맵을 위해 자리가 놓인 지도의 도형·시설을 한 번에.
    maps = {s.geo_id for s in cx.shapes.values()}
    maps |= _site_fallback_maps(cx, unbound)
    if maps:
        all_shapes = _all_in(cx, GeoShape, GeoShape.geo_id, maps)
        for s in all_shapes:
            cx.map_shapes.setdefault(s.geo_id, []).append(s)
            cx.by_id[s.id] = s
        # 읽기 전용 — 캐시는 읽기만 한다(build_geo_parent_map 은 캐시를 쓴다).
        try:
            cached = _parent_map_from_cache(all_shapes)
        except Exception:  # noqa: BLE001 — 컨텍스트 없으면 캐시는 없는 것으로
            cached = None
        cx.parent = cached or build_geo_parent_map(all_shapes, use_cache=False)
        for f in _all_in(cx, GeoFacility, GeoFacility.geo_id, maps):
            cx.map_facs.setdefault(f.geo_id, []).append(f)
            cx.facs.setdefault(f.unique_id, f)
            cx.fac_by_shape.setdefault(f.shape_uuid, f)
    return cx


def _site_fallback_maps(cx, unbound_or_all):
    """대지 폴백이 읽을 지도 — 지도가 하나뿐일 때만."""
    out = set()
    sole = None
    need = [r for (k, d), r in cx.rows.items()]
    if not need:
        return out
    q = (GeoMap.query.with_entities(GeoMap.unique_id) if cx.session is None
         else cx.session.query(GeoMap.unique_id))
    maps = [m for (m,) in q.all()]
    if len(maps) == 1:
        sole = maps[0]
    cx.sole_map = sole
    if sole:
        out.add(sole)
    return out


def _ancestors(cx, shape):
    out, seen, cur = [], {shape.id}, cx.parent.get(shape.id)
    while cur is not None and cur not in seen:
        seen.add(cur)
        s = cx.by_id.get(cur)
        if s is None:
            break
        out.append(s)
        cur = cx.parent.get(cur)
    return out


def _ref(kind, uid, name):
    return PlaceRef(kind, uid, name or '')


def _chain_and_tz(cx, shape, facility_anchor=False, bay_ref=None):
    """도형 하나의 (사슬, tz). 포함 판정은 geo_hierarchy 의 것을 그대로 쓴다."""
    from aot.space.device_membership import place_label
    from aot.utils.geo_hierarchy import containment_point, pick_smallest_container

    ancestors = _ancestors(cx, shape)
    refs = []
    for s in reversed(ancestors):
        if s.type in ('site', 'zone'):
            refs.append(_ref(s.type, s.unique_id, place_label(s)))
    if shape.type in ('site', 'zone'):
        refs.append(_ref(shape.type, shape.unique_id, place_label(shape)))

    fac = None
    bay = shape if shape.type == 'facility_bay' else None
    if shape.type == 'facility':
        fac = cx.fac_by_shape.get(shape.unique_id)
    elif bay is not None and bay.parent_id in cx.by_id \
            and cx.by_id[bay.parent_id].type == 'facility':
        fac = cx.fac_by_shape.get(cx.by_id[bay.parent_id].unique_id)
    if fac is None and shape.type not in ('site', 'zone'):
        g = cx.geom(shape)
        pt = containment_point(g) if g is not None else None
        if pt is not None:
            own = getattr(g, 'area', 0.0) or 0.0
            cands = []
            for f in cx.map_facs.get(shape.geo_id, ()):
                fs = cx.shapes.get(f.shape_uuid) or next(
                    (s for s in cx.map_shapes.get(shape.geo_id, ())
                     if s.unique_id == f.shape_uuid), None)
                fg = cx.geom(fs) if fs is not None else None
                if fg is None or fg.geom_type not in ('Polygon', 'MultiPolygon'):
                    continue
                cands.append((f.unique_id, fg, getattr(fg, 'area', 0.0) or 0.0))
            fuid = pick_smallest_container(pt, cands, own_area=own)
            fac = cx.facs.get(fuid) if fuid else None
    if fac is not None:
        refs.append(_ref('facility', fac.unique_id, fac.name))
        if bay is None and not facility_anchor and shape.type != 'facility':
            fshape = cx.shapes.get(fac.shape_uuid)
            g = cx.geom(shape)
            pt = containment_point(g) if g is not None else None
            if fshape is not None and pt is not None:
                cands = []
                for s in cx.map_shapes.get(shape.geo_id, ()):
                    if s.type == 'facility_bay' and s.parent_id == fshape.id:
                        bg = cx.geom(s)
                        if bg is not None and bg.geom_type in (
                                'Polygon', 'MultiPolygon'):
                            cands.append((s, bg, getattr(bg, 'area', 0.0) or 0.0))
                bay = pick_smallest_container(pt, cands)
        if bay is not None:
            refs.append(_ref('bay', bay.unique_id, place_label(bay)))
        elif bay_ref is not None:
            refs.append(bay_ref)

    # 앵커 자체 → 부모 도형 체인 → 속한 시설. 시설 앵커는 시설이 먼저.
    tz = _valid_tz(fac.timezone) if (facility_anchor and fac is not None) else None
    tz = tz or _valid_tz(shape.timezone)
    for s in ancestors:
        if tz:
            break
        tz = _valid_tz(s.timezone)
    if tz is None and fac is not None:
        tz = _valid_tz(fac.timezone)
    return tuple(refs), tz


def _anchor(cx, b):
    """바인딩 → (shape, point). 해석 못 하면 (None, None)."""
    if b.spatial_kind == 'shape':
        s = cx.shapes.get(b.spatial_id)
    else:
        f = cx.facs.get(b.spatial_id.split(':', 1)[0])
        s = cx.shapes.get(f.shape_uuid) if f is not None else None
    if s is None:
        return None, None
    return s, _shape_point(s)


def _bay_ref(cx, b):
    """fitting/actuator 항목의 `bay_id` → bay PlaceRef (없으면 None)."""
    if b.spatial_kind not in ('fitting', 'actuator') or ':' not in b.spatial_id:
        return None
    fuid, item_id = b.spatial_id.split(':', 1)
    fac = cx.facs.get(fuid)
    if fac is None:
        return None
    # 시설 항목은 레거시 컬럼을 직접 읽지 않고 정본 출구(resolved_refs)로 — 원장이
    # 끊은 연결을 되살리지 않는다. 시설당 한 번만 푼다.
    cache = cx.__dict__.setdefault('_refs', {})
    if fuid not in cache:
        from aot.space.device_binding import resolved_refs
        try:
            cache[fuid] = resolved_refs(fac)
        except Exception:
            cache[fuid] = ([], [])
    fits, acts = cache[fuid]
    entries = fits if b.spatial_kind == 'fitting' else acts
    if isinstance(entries, dict):        # 옛 `{slot_key: uuid}` 형식 — bay 정보 없음
        return None
    for e in entries or ():
        if isinstance(e, dict) and str(e.get('id')) == item_id:
            bay_id = e.get('bay_id')
            if not bay_id:
                return None
            name = bay_id
            for bay in fac.bays or ():
                if isinstance(bay, dict) and str(bay.get('id')) == str(bay_id):
                    name = bay.get('name') or bay_id
            return PlaceRef('bay', '%s:%s' % (fuid, bay_id), str(name))
    return None


_PRECISION = {'marker': 'point', 'fitting': 'facility', 'area': 'area',
              'facility': 'facility'}


def _best(cx, bs):
    best = None
    for b in bs:
        shape, pt = _anchor(cx, b)
        if shape is None or pt is None:
            continue
        rank, source = _rank_source(b.spatial_kind, shape if
                                    b.spatial_kind == 'shape' else None)
        if best is None or rank < best[0] or (
                rank == best[0] and (b.valid_from, b.id or 0)
                > (best[1].valid_from, best[1].id or 0)):
            best = (rank, b, shape, pt, source)
    return best


def _from_bindings(cx, device_id, channel_id, at):
    bs = cx.bindings.get(device_id) or []
    if at is None:
        bs = [b for b in bs if b.valid_to is None]
    else:
        t = naive_utc(at)
        bs = [b for b in bs if b.valid_from <= t
              and (b.valid_to is None or t < b.valid_to)]
    if channel_id is None:
        tiers = [bs]
    else:
        # 지정 채널 → 장치 단위('0') → 아무 채널. 앵커가 해석되는 첫 단계를 쓴다.
        ch = str(channel_id)
        tiers = [[b for b in bs if b.channel_id == ch],
                 [b for b in bs if b.channel_id == '0'], bs]
    best = None
    for tier in tiers:
        best = _best(cx, tier) if tier else None
        if best is not None:
            break
    if best is None:
        return None
    _r, b, shape, pt, source = best
    fac_anchor = b.spatial_kind != 'shape'
    chain, tz = _chain_and_tz(cx, shape, facility_anchor=fac_anchor,
                              bay_ref=_bay_ref(cx, b))
    return Placement(pt, chain, tz, source,
                     SlotRef(b.spatial_kind, b.spatial_id, b.role,
                             b.channel_id), 'device', _PRECISION[source])


def _site_fallback(cx, row):
    gid = getattr(cx, 'sole_map', None)
    sites = [s for s in cx.map_shapes.get(gid, ()) if s.type == 'site']
    if len(sites) != 1:
        return None
    s = sites[0]
    pt = _shape_point(s)
    if pt is None:
        return None
    chain, tz = _chain_and_tz(cx, s)
    return Placement(pt, chain, tz, 'site', None, 'site', 'site')


def _run(pairs, at, channel_id=None, single=False):
    from flask import has_app_context
    if has_app_context():
        return _compute(pairs, at, channel_id, single, None)
    # 앱 컨텍스트 없는 프로세스(데몬): 분리 세션으로 읽고, 결과는 순수 튜플로 나간다.
    from aot.utils.database import session_scope
    from aot.utils.database import AOT_DB_PATH
    with session_scope(AOT_DB_PATH) as sess:
        return _compute(pairs, at, channel_id, single, sess)


def _compute(pairs, at, channel_id, single, session):
    cx = _load(pairs, at, session)
    out = {}
    for kind, did in pairs:
        row = cx.rows.get((kind, did))
        if row is None:
            out[(kind, did)] = None
            continue
        pl = _from_bindings(cx, did, channel_id if single else None, at)
        out[(kind, did)] = pl or _site_fallback(cx, row) or _NONE
    return out


def locate_many(pairs: Iterable[tuple], *, at: Optional[datetime] = None):
    """{(device_kind, device_id): Placement | None} — 일괄 조회(N+1 없음)."""
    return _run([(k, str(d)) for k, d in pairs], at)


def locate(device_kind: str, device_id: str, *, channel_id: Optional[str] = None,
           at: Optional[datetime] = None) -> Optional[Placement]:
    """장치 하나의 배치. 장치가 없으면 None, 있으면 항상 Placement."""
    key = (device_kind, str(device_id))
    return _run([key], at, channel_id, single=True)[key]


def _placement_map_id(device_id):
    try:
        from aot.space.device_membership import map_for_device
        return map_for_device(device_id)
    except Exception:
        return None


def placement_summary(device_id):
    """옵션 모달의 읽기 전용 배치 요약 — locate() 결과를 화면용으로 줄인 dict.

    {'basis': 'device'|'site'|'none', 'source': ..., 'path': '대지 > 구역',
     'tz': IANA|None, 'point': (lat, lng)|None}. 장치가 없으면 None.
    """
    from aot.space import device_binding
    kind = device_binding.resolve_device_kind(device_id)
    if kind is None:
        return None
    pl = locate(kind, device_id)
    if pl is None:
        return None
    return {'basis': pl.basis, 'source': pl.source,
            'path': ' > '.join(p.name for p in pl.chain if p.name),
            'tz': pl.tz, 'point': pl.point,
            'map_id': _placement_map_id(device_id)}
