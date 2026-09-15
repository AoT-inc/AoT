# coding=utf-8
"""구획이 **과거 기간에** 참조할 센서 — 위치 이력 × 바인딩 이력의 조합.

구획은 센서 값을 갖지 않는다. 원데이터는 Influx 에 한 벌만 있고, 조회할 때
**구획 위치 × 기간 × 데이터 ID** 를 조합한다(docs/design/geo-plot-instance.md
§센서 위치 이력).

`plot_context.sensors_for_plot` 은 **지금** 지도만 본다. 그래서 두 가지가
과거 기간을 잃었다.

- 센서를 떼어내면 마커가 지워져 "그때 그 자리에 있던 센서" 가 사라진다.
- 구획 안에 새 센서가 찍히는 순간 규칙이 "구획 안 센서로 확정" 으로 바뀌어,
  그 전 기간을 채우던 구역 센서를 통째로 버린다.

여기서는 기간마다 누가 어디 있었는지를 되짚는다.

- **노지 마커**: `geo_marker_position`(좌표 기간) × `geo_binding` 마커 이력
  (장치 기간). 좌표가 구획 안이면 `plot`, 구획이 속한 구역 안이면 `zone`.
- **시설 설비**: `geo_binding` 설비 이력. 구획의 동이면 `bay`, 아니면 `facility`.
- **대지 기상대**: `geo_binding` weather 이력. 실내 체인과 겨루지 않는다.

그리고 **날짜마다** 값이 있는 것 중 우선순위가 가장 높은 것을 고른다
(`choose`) — `plot` > `bay` > `facility` > `zone`(가까운 순 최대
`ZONE_CANDIDATES` 개). 예전의 "기간 전체를 하나로 확정" 을 날짜 단위로
옮긴 것이다.

⚠ 반환값을 어디에도 저장하지 말 것 — 구획은 참조일 뿐이다(`sensors_for_plot`
과 같은 규칙).

@phase active
@stability experimental
@dependency GeoMarkerPosition, GeoBinding, DeviceMeasurements
"""
import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: 구역 폴백 후보 수(가까운 순). 교체 과정에서 "물리 센서 A → API 센서 →
#: 물리 센서 B" 가 한 기간에 모두 걸리므로 셋이 있어야 그 흐름이 끊기지 않는다.
ZONE_CANDIDATES = 3

#: 실내 출처의 우선순위 — 작을수록 좁고 먼저다.
TIER_ORDER = {'plot': 0, 'bay': 1, 'facility': 2, 'zone': 3}

_FAR_PAST = datetime.min
_FAR_FUTURE = datetime.max


def _naive_utc(dt):
    """바인딩 시각은 tz-aware 로 저장되고 SQLite 에서 naive 로 돌아온다.
    어느 쪽이 와도 naive UTC 로 맞춘다."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _overlap(a_from, a_to, b_from, b_to):
    """두 기간의 교집합 → `(from, to)`(None 은 열린 끝). 없으면 None."""
    lo = max(_naive_utc(a_from) or _FAR_PAST, _naive_utc(b_from) or _FAR_PAST)
    hi = min(_naive_utc(a_to) or _FAR_FUTURE, _naive_utc(b_to) or _FAR_FUTURE)
    if lo >= hi:
        return None
    return (None if lo == _FAR_PAST else lo, None if hi == _FAR_FUTURE else hi)


def _merge(periods):
    """겹치거나 맞닿은 기간을 합친다 — 같은 출처가 조각나 두 번 조회되지 않게."""
    out = []
    for lo, hi in sorted(periods):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _binding_history_start():
    """바인딩 이력이 시작된 순간 — 표 전체에서 가장 이른 `valid_from`. 비면 None."""
    from sqlalchemy import func

    from aot.databases.models import GeoBinding

    return _naive_utc(GeoBinding.query.with_entities(
        func.min(GeoBinding.valid_from)).scalar())


def _since(valid_from, history_start):
    """바인딩 시작 시각 → 출처 기간의 시작.

    **이력이 시작될 때 이미 있던 연결**(바인딩 표를 처음 채운 백필 행)의 시작
    시각은 설치일이 아니라 표가 생긴 날이다 — 실측(2026-09-15): 모든 마커 바인딩이
    8/8 04:29:17 에 시작해, 6/15 에 심은 구획의 GDD 가 8/7 까지를 통째로 잃었다.
    그런 행은 좌표 기록 이전 마커와 같은 원칙으로 "처음부터" 로 읽는다.
    """
    vf = _naive_utc(valid_from)
    if vf is not None and history_start is not None and vf <= history_start:
        return None
    return vf


# ── 노지 마커 ──────────────────────────────────────────────────────────────

def _marker_geometry(geo_id, start, end):
    """`{shape_uuid: [((lng, lat), from, to)]}` — 기간과 겹치는 좌표 기록.

    기록이 없거나 열린 기간이 없는 **지금 마커**는 마지막으로 닫힌 기간 뒤
    (없으면 처음)부터 지금 좌표로 읽는다 — 리스너 이전 마커가 그렇다.
    """
    from sqlalchemy import or_

    from aot.aot_flask.geo import device_membership
    from aot.databases.models import GeoMarkerPosition as P

    out = {}
    open_shapes = set()
    rows = P.query.filter(
        P.geo_id == geo_id,
        or_(P.valid_to.is_(None), P.valid_to > start),
        or_(P.valid_from.is_(None), P.valid_from < end)).all()
    for r in rows:
        out.setdefault(r.shape_uuid, []).append(
            ((r.lng, r.lat), r.valid_from, r.valid_to))
        if r.valid_to is None:
            open_shapes.add(r.shape_uuid)

    current = [(uid, pt) for uid, pt in device_membership.marker_points(geo_id)
               if uid not in open_shapes]
    if current:
        last_closed = {}
        for r in P.query.filter(
                P.shape_uuid.in_([uid for uid, _pt in current]),
                P.valid_to.isnot(None)).all():
            if r.valid_to > last_closed.get(r.shape_uuid, _FAR_PAST):
                last_closed[r.shape_uuid] = r.valid_to
        for uid, pt in current:
            out.setdefault(uid, []).append((pt, last_closed.get(uid), None))
    return out


def _marker_devices(geo_id, shape_uuids):
    """`{shape_uuid: [(device_id, device_kind, from, to)]}` — 마커를 맡은 장치 기간."""
    from aot.aot_flask.geo import device_membership
    from aot.databases.models import GeoBinding

    uuids = list(shape_uuids)
    out = {}
    if not uuids:
        return out
    history_start = _binding_history_start()
    for b in GeoBinding.query.filter(
            GeoBinding.spatial_kind == 'shape',
            GeoBinding.role == 'marker',
            GeoBinding.spatial_id.in_(uuids)).all():
        out.setdefault(b.spatial_id, []).append(
            (b.device_id, b.device_kind, _since(b.valid_from, history_start),
             b.valid_to))
    missing = [u for u in uuids if u not in out]
    if missing:
        legacy = device_membership.legacy_marker_devices(geo_id)
        for uid in missing:
            if uid in legacy:
                out[uid] = [(legacy[uid], None, None, None)]
    return out


def _is_sensor(device_id, device_kind, _cache):
    """센서(Input)인가. 바인딩이 종류를 알면 그것을 믿는다 — 장치가 이미
    지워졌어도 종류는 이력에 남는다. 모르면 지금 Input 표를 본다."""
    if device_kind:
        return device_kind == 'input'
    if device_id not in _cache:
        from aot.databases.models import Input
        _cache[device_id] = Input.query.with_entities(Input.unique_id).filter(
            Input.unique_id == device_id).first() is not None
    return _cache[device_id]


def _open_field_indoor(plot, start, end):
    from shapely.geometry import Point

    from aot.aot_flask.geo import device_membership, plot_context

    geom = plot_context.geometry_of(plot)
    poly = plot_context._shapely(geom)
    zone = plot_context.zone_for_plot(plot)
    zone_poly = (plot_context._shapely(
        device_membership._feature(zone).get('geometry'))
        if zone is not None else None)

    to_m, ref = None, None
    if poly is not None:
        try:
            to_m = plot_context.local_frame(geom)[0]
            rp = poly.representative_point()
            ref = to_m(rp.x, rp.y) if to_m else None
        except Exception:
            to_m, ref = None, None

    geometry = _marker_geometry(plot.geo_id, start, end)
    devices = _marker_devices(plot.geo_id, geometry.keys())

    # (장치, 종류, 좌표, 시작, 끝) — 좌표 기간 × 장치 기간의 교집합.
    occupancy = []
    for uid, spans in geometry.items():
        for pt, g_from, g_to in spans:
            for dev, kind, b_from, b_to in devices.get(uid, []):
                both = _overlap(g_from, g_to, b_from, b_to)
                if both is not None:
                    occupancy.append((dev, kind, pt, both[0], both[1]))
    occupancy.extend(_unrecorded_marker_occupancy(occupancy))

    sensor_cache = {}
    found = {}          # (device_id, tier) -> {'periods': [...], 'distance': d}
    for dev, kind, pt, o_from, o_to in occupancy:
        if not _is_sensor(dev, kind, sensor_cache):
            continue
        span = _overlap(o_from, o_to, start, end)
        if span is None:
            continue
        p = Point(pt[0], pt[1])
        if poly is not None and poly.contains(p):
            tier = 'plot'
        elif zone_poly is not None and zone_poly.contains(p):
            tier = 'zone'
        else:
            continue
        dist = None
        if to_m is not None and ref is not None:
            mx, my = to_m(pt[0], pt[1])
            dist = math.hypot(mx - ref[0], my - ref[1])
        entry = found.setdefault((dev, tier), {'periods': [], 'distance': dist})
        entry['periods'].append(span)
        if dist is not None and (entry['distance'] is None
                                 or dist < entry['distance']):
            entry['distance'] = dist
    return found


def _unrecorded_marker_occupancy(known):
    """좌표 기록 없이 사라진 마커의 기간 → **그 장치의 다음으로 알려진 자리**로 읽는다.

    좌표 기록(`geo_marker_position`)이 생기기 전에 지워진 마커는 어디 있었는지
    알 길이 없다. 그 기간을 버리면 마커를 지웠다 다시 찍은 센서의 과거가 통째로
    빈다 — 실측(2026-09-15): 온습도 센서 셋이 9/12 에 마커가 지워지고 9/13 에
    다시 찍혀, 8/8~9/12 가 조회에서 빠졌다.

    그래서 **좌표를 모르는 기간에만** 옛 동작의 가정("지금 자리가 곧 그때
    자리")을 쓴다. 그 장치가 그 뒤에 처음 놓인 자리를 빌리고, 뒤가 없으면 가장
    최근 자리를 빌린다. 좌표 기록이 조금이라도 남은 마커(리스너 이후의 이동·
    제거)는 **추측하지 않는다** — 기록이 정본이다.

    ⚠ 도형이 지워지면 그 마커가 어느 지도에 있었는지도 모른다. 그 장치가 지금
      이 지도에 있으면 같은 지도였다고 본다(다른 지도에서 옮겨 온 드문 경우는
      틀린다 — 받아들인 한계).
    """
    from aot.databases.models import GeoBinding, GeoShape
    from aot.databases.models import GeoMarkerPosition as P

    by_device = {}
    for dev, _kind, pt, o_from, _o_to in known:
        by_device.setdefault(dev, []).append((pt, o_from))
    if not by_device:
        return []

    rows = GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'shape',
        GeoBinding.role == 'marker',
        GeoBinding.device_id.in_(list(by_device))).all()
    shape_ids = list({b.spatial_id for b in rows})
    if not shape_ids:
        return []
    alive = {r[0] for r in GeoShape.query.with_entities(GeoShape.unique_id)
             .filter(GeoShape.unique_id.in_(shape_ids)).all()}
    recorded = {r[0] for r in P.query.with_entities(P.shape_uuid)
                .filter(P.shape_uuid.in_(shape_ids)).distinct().all()}

    history_start = _binding_history_start()
    out = []
    for b in rows:
        if b.spatial_id in alive or b.spatial_id in recorded:
            continue
        spots = by_device[b.device_id]
        ended = _naive_utc(b.valid_to) or _FAR_FUTURE
        later = [s for s in spots if (_naive_utc(s[1]) or _FAR_PAST) >= ended]
        if later:
            pt = min(later, key=lambda s: _naive_utc(s[1]) or _FAR_PAST)[0]
        else:
            pt = max(spots, key=lambda s: _naive_utc(s[1]) or _FAR_PAST)[0]
        out.append((b.device_id, b.device_kind, pt,
                    _since(b.valid_from, history_start), b.valid_to))
    return out


# ── 시설 설비 ──────────────────────────────────────────────────────────────

def _facility_indoor(plot, start, end):
    from aot.aot_flask.geo.facility_bays import (
        build_fitting_bay_map, compute_bay_slices)
    from aot.aot_flask.geo.facility_io import FacilityManager
    from aot.databases.models import GeoBinding

    facility_uuid = plot.facility_uuid
    bay_id = getattr(plot, 'bay_id', None)
    found = {}
    fac, err = FacilityManager.get_facility(facility_uuid)
    if err or not fac:
        return found
    # 실외 설비 센서는 뺀다 — `facility_sensor_ids` 와 같은 규칙.
    fittings = [f for f in (fac.get('fittings') or [])
                if f.get('kind') == 'sensor' and f.get('id')
                and (f.get('sensor_role') or 'indoor') != 'outdoor']
    if not fittings:
        return found
    bay_of = (build_fitting_bay_map(compute_bay_slices(fac), fittings)
              if bay_id else {})
    history_start = _binding_history_start()
    for fit in fittings:
        slot = '%s:%s' % (facility_uuid, fit['id'])
        spans = [(b.device_id, _since(b.valid_from, history_start), b.valid_to)
                 for b in GeoBinding.query.filter(
                     GeoBinding.spatial_kind == 'fitting',
                     GeoBinding.spatial_id == slot,
                     GeoBinding.role == 'sensor').all()]
        if not spans and fit.get('input_id'):
            spans = [(str(fit['input_id']).split('::')[0], None, None)]
        tier = 'bay' if bay_id and bay_of.get(fit['id']) == bay_id else 'facility'
        for dev, b_from, b_to in spans:
            span = _overlap(b_from, b_to, start, end)
            if span is None:
                continue
            found.setdefault((dev, tier),
                             {'periods': [], 'distance': None})['periods'].append(span)
    return found


# ── 대지 기상대 ────────────────────────────────────────────────────────────

def _outdoor(plot, start, end):
    from aot.aot_flask.geo import plot_context
    from aot.databases.models import GeoBinding

    try:
        ids, _source, target_uuid = plot_context._weather_for_plot(plot)
    except Exception:
        logger.exception('plot_sources: 기상원 조회 실패(%s)',
                         getattr(plot, 'unique_id', None))
        return {}
    found = {}
    rows = []
    if target_uuid:
        rows = GeoBinding.query.filter(
            GeoBinding.spatial_kind == 'weather',
            GeoBinding.spatial_id == target_uuid).all()
    if rows:
        history_start = _binding_history_start()
        spans = [(b.device_id, _since(b.valid_from, history_start), b.valid_to)
                 for b in rows if (b.device_kind or 'input') == 'input']
    else:
        # 사람이 지정한 적이 없으면 추론 결과(지금 장치)를 처음부터로 읽는다.
        spans = [(d, None, None) for d in (ids or [])]
    for dev, b_from, b_to in spans:
        span = _overlap(b_from, b_to, start, end)
        if span is None:
            continue
        found.setdefault(dev, []).append(span)
    return found


# ── 조합 ──────────────────────────────────────────────────────────────────

def resolve(plot, start, end):
    """구획 + 기간 → `{'indoor': [출처], 'outdoor': [출처]}`.

    출처는 `{'device_id', 'tier', 'rank', 'scope', 'periods', 'distance_m'}` —
    `periods` 는 요청 기간 안으로 잘린 `(from, to)` 목록(naive UTC)이다.
    `start`/`end` 도 naive UTC datetime 이다.

    같은 장치가 실외(기상대)로도 잡히면 실내에서 뺀다 — 같은 값이 두 줄로
    나오지 않게(`sensors_for_plot` 소비처들의 기존 규칙).
    """
    start, end = _naive_utc(start), _naive_utc(end)
    own_geom = (plot.has_own_geometry()
                if hasattr(plot, 'has_own_geometry') else True)

    indoor_found = {}
    if getattr(plot, 'facility_uuid', None) and not own_geom:
        indoor_found.update(_facility_indoor(plot, start, end))
        # 시설 구획도 구역 폴백을 가진다. 자기 기하가 없어 거리는 모른다.
        zone_only = {k: v for k, v in _open_field_indoor(plot, start, end).items()
                     if k[1] == 'zone'}
        for key, val in zone_only.items():
            indoor_found.setdefault(key, val)
    else:
        indoor_found.update(_open_field_indoor(plot, start, end))

    outdoor_found = _outdoor(plot, start, end)

    indoor, zone = [], []
    for (dev, tier), val in indoor_found.items():
        if dev in outdoor_found:
            continue
        src = {'device_id': dev, 'tier': tier, 'rank': 0, 'scope': 'indoor',
               'periods': _merge(val['periods']),
               'distance_m': (round(val['distance'], 1)
                              if val['distance'] is not None else None)}
        (zone if tier == 'zone' else indoor).append(src)

    if any(s['distance_m'] is not None for s in zone):
        zone.sort(key=lambda s: (s['distance_m'] is None,
                                 s['distance_m'] or 0.0, s['device_id']))
        zone = zone[:ZONE_CANDIDATES]
        for rank, src in enumerate(zone):
            src['rank'] = rank
    else:
        # 거리를 모르면(시설 구획) 순위를 매길 수 없다 — 전부 나란히 둔다.
        for src in zone:
            src['rank'] = None
    indoor.sort(key=lambda s: (TIER_ORDER[s['tier']], s['device_id']))

    outdoor = [{'device_id': dev, 'tier': 'weather', 'rank': None,
                'scope': 'outdoor', 'periods': _merge(spans),
                'distance_m': None}
               for dev, spans in sorted(outdoor_found.items())]
    return {'indoor': indoor + zone, 'outdoor': outdoor}


def choose(candidates, has_data):
    """한 날짜의 실내 후보 → 쓸 것만. `candidates` 는 `tier`·`rank` 를 가진 dict.

    - 값이 있는 후보 중 **가장 좁은 출처**(`TIER_ORDER`)를 쓴다.
    - 그 출처가 구역이면 **가장 가까운 하나**만 쓴다(순위가 없으면 전부).
    - 그 밖의 출처(구획 안·동·시설)는 그 층의 센서를 **전부** 쓴다 — 서로
      다른 실제 설치를 하나로 접지 않는다(`measured_stage_targets` 의 원칙).
    - 모두 값이 없으면 같은 규칙으로 빈 후보를 남긴다 — 빈 행이 결측의 증거다.
    """
    cands = list(candidates or [])
    if not cands:
        return []
    pool = [c for c in cands if has_data(c)] or cands
    best = min(TIER_ORDER.get(c.get('tier'), 99) for c in pool)
    chosen = [c for c in pool if TIER_ORDER.get(c.get('tier'), 99) == best]
    if chosen and chosen[0].get('tier') == 'zone':
        ranked = [c for c in chosen if c.get('rank') is not None]
        if ranked:
            low = min(c['rank'] for c in ranked)
            chosen = [c for c in ranked if c['rank'] == low]
    return chosen


def pick_rows(rows):
    """한 버킷의 env 행 → 같은 측정값마다 `choose` 로 고른 것만 남긴다.

    `tier` 가 없는 행(구역·대지 일지, 시설 카드처럼 출처를 따지지 않는 경로)과
    실외 행은 손대지 않는다.
    """
    keep, groups = [], {}
    for row in rows or []:
        if row.get('tier') is None or row.get('scope') == 'outdoor':
            keep.append(row)
            continue
        groups.setdefault(row.get('measurement'), []).append(row)
    for cands in groups.values():
        keep.extend(choose(cands, lambda r: (r.get('samples') or 0) > 0))
    return keep


def channels_for(sources, measurements):
    """출처 목록 → `[(출처, DeviceMeasurements 행)]` — 표시 이름이 `measurements` 안인 채널.

    **제거 표시된 측정 정의까지 읽는다** — 떼어낸 센서의 과거 값을 부르려면
    그 정의가 필요하다. 같은 채널에 살아 있는 행과 제거된 행이 함께 있으면
    (채널을 줄였다 다시 늘린 경우) 살아 있는 쪽을 쓴다.
    """
    from aot.databases.models import Conversion, DeviceMeasurements
    from aot.databases.models.measurement import INCLUDE_REMOVED_MEASUREMENTS
    from aot.utils.system_pi import return_measurement_info

    wanted = set(measurements)
    ids = sorted({s['device_id'] for s in sources or []})
    if not ids:
        return []
    by_device = {}
    rows = DeviceMeasurements.query.execution_options(
        **{INCLUDE_REMOVED_MEASUREMENTS: True}).filter(
            DeviceMeasurements.device_id.in_(ids)).all()
    for dm in rows:
        conv = None
        if getattr(dm, 'conversion_id', None):
            conv = Conversion.query.filter(
                Conversion.unique_id == dm.conversion_id).first()
        _ch, _unit, measurement = return_measurement_info(dm, conv)
        if (measurement or dm.measurement) not in wanted:
            continue
        per_channel = by_device.setdefault(dm.device_id, {})
        prev = per_channel.get(dm.channel)
        if prev is None or (prev.removed_at is not None and dm.removed_at is None):
            per_channel[dm.channel] = dm
    out = []
    for src in sources or []:
        for _ch, dm in sorted(by_device.get(src['device_id'], {}).items(),
                              key=lambda kv: (kv[0] is None, kv[0])):
            out.append((src, dm))
    return out
