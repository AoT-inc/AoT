# coding=utf-8
"""water_net.adapters — 시설 fitting·지도 feature 를 공용 `Network` 로 바꾼다.

시설은 fitting 이 이미 미터 좌표이고 레이어마다 회로가 따로다. 지도는 위경도라
대지 기준 로컬 미터로 내린 뒤 같은 그래프에 넣는다.

⚠ ``connected_main_id`` 는 읽지 않는다 — 지관의 66% 가 비어 있다. 기하로만 세운다.
⚠ 장치 연결은 부품 자리의 Output·Input 마커를 읽을 때마다 찾는다. 도형에 장치
  uuid 를 새기지 않고 저장하지도 않는다.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

from . import parts as part_table
from .graph import (DEVICE_SNAP_M, SNAP_M, Emitter, Network, Part, Pipe,
                    dist_xz, line_length, _point_at)

# 지도 배관의 끝 틈 허용 [m]. 시설의 SNAP_M(12cm) 은 디자이너가 끝을 붙여 주는 값이고,
# 지도는 위성 화면에 손으로 찍는다. 설비가 있는 6개 지도 실측(2026-11-01): 김해 지관은
# 12cm 로는 하나도 안 이어지고 틈 0.5~2.5m 로 주배관에 닿는다. 그다음 틈은 3.3m 부터인데
# 나란한 지관끼리 벌어진 값이 섞여 들어와(양산 5~14m, 나주 5.9m), 3m 위로 올리면 없는
# 이음이 생긴다. 못 이은 끝은 점검 항목으로 보이므로 짧게 잡는 쪽이 안전하다.
MAP_GAP_M = 3.0
# 부품을 지도 배관에 얹는 상한 [m]. 배관 끝 틈과 같은 눈금이다 — 손으로 찍은 정밀도가 같다.
MAP_PART_SNAP_M = MAP_GAP_M
# 부품 자리에서 Output·Input 마커를 찾는 반경 [m]. 위치가 잡힌 마커끼리는 가장 가까워도
# 9.8m 떨어져 있어(임실 9.8, 김제 11.1, 나주 12.0, 농우 12.3) 반경이 그 절반인 5m 면 멀쩡한
# 배치가 모호 판정으로 빠지지 않고, 김제 마커 33개 중 26개가 배관에서 5m 안이라 실제
# 배치를 받는다.
PART_DEVICE_RADIUS_M = 5.0

_M_PER_DEG = 111_320.0
_MAIN_TYPES = ('pipe_main', 'main')
_BRANCH_TYPES = ('pipe_branch', 'branch')
_EMITTER_SUB_TYPE = 'sprinkler_coverage'
_DEVICE_KINDS = ('output', 'input')


def _fnum(value, default=0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ── 시설 ───────────────────────────────────────────────────────────────────

def _pt(seq):
    """[x, y, z] → (x, y, z) 튜플. 못 읽으면 None."""
    if not isinstance(seq, (list, tuple)) or len(seq) < 3:
        return None
    return (_fnum(seq[0]), _fnum(seq[1]), _fnum(seq[2]))


def _pos_pt(fit):
    """fitting.position → (x, y, z). 못 읽으면 None."""
    pos = fit.get('position')
    if not isinstance(pos, dict):
        return None
    if pos.get('x') is None or pos.get('z') is None:
        return None
    return (_fnum(pos.get('x')), _fnum(pos.get('y')), _fnum(pos.get('z')))


def _polyline(pipe):
    """배관 segments 를 이어 붙인 점렬. 끊긴 구간은 그대로 이어 붙인다."""
    segs = pipe.get('segments')
    if not isinstance(segs, list) or not segs:
        return []
    pts = []
    for s in segs:
        if not isinstance(s, dict):
            continue
        a, b = _pt(s.get('from')), _pt(s.get('to'))
        if a is None or b is None:
            continue
        if not pts:
            pts.append(a)
        elif dist_xz(pts[-1], a) > SNAP_M:
            pts.append(a)
        pts.append(b)
    return pts


def facility_emitter(dev) -> Emitter:
    return Emitter(id=dev.get('id'), point=_pos_pt(dev), pipe_id=dev.get('pipe_id'),
                   kind=dev.get('sub_type') or 'sprinkler',
                   flow_lph=_fnum(dev.get('flow_lph'), None), meta=dev)


def facility_valve(valve) -> Part:
    t = valve.get('attach_t')
    return Part(id=valve.get('id'), kind='valve_inline', point=_pos_pt(valve),
                pipe_id=valve.get('pipe_id'),
                attach_t=None if t is None else _fnum(t, 0.5), meta=valve)


def facility_layer_network(pipes, valves, devices=()) -> Network:
    """시설 레이어 하나. 수직관·주배관 시작이 공급이고 부품 스냅 상한은 없다."""
    return Network(
        pipes=[Pipe(id=p.get('id'), line=_polyline(p), sub_type=p.get('sub_type') or '',
                    vertical=bool(p.get('is_vertical')), name=p.get('name'))
               for p in pipes],
        parts=[facility_valve(v) for v in valves],
        emitters=[facility_emitter(d) for d in devices],
        layer_feed=True)


def from_facility_fittings(fittings) -> Dict[object, Network]:
    """시설 fitting 목록 → {레이어 id: Network}."""
    out = {}
    for layer in (fittings or []):
        if layer.get('kind') != 'irrigation_layer':
            continue
        lid = layer.get('id')
        rows = [f for f in fittings if f.get('layer_id') == lid]
        out[lid] = facility_layer_network(
            [f for f in rows if f.get('kind') == 'irrigation_pipe'],
            [f for f in rows if f.get('kind') == 'irrigation_valve'],
            [f for f in rows if f.get('kind') == 'irrigation_device'])
    return out


# ── 지도 ───────────────────────────────────────────────────────────────────

class LocalFrame:
    """위경도 ↔ 로컬 미터. 대지 하나(수 km)라 등장방형으로 충분하다."""

    def __init__(self, lng0: float, lat0: float):
        self.lng0, self.lat0 = lng0, lat0
        self._kx = _M_PER_DEG * math.cos(math.radians(lat0))

    def to_local(self, lng, lat):
        return ((lng - self.lng0) * self._kx, 0.0, (lat - self.lat0) * _M_PER_DEG)

    def to_lnglat(self, p):
        return [round(self.lng0 + p[0] / self._kx, 7),
                round(self.lat0 + p[2] / _M_PER_DEG, 7)]


def _coords(geom) -> List[list]:
    """도형의 꼭짓점 전부(점·선은 그대로, 면은 바깥 고리)."""
    kind = (geom or {}).get('type')
    cs = (geom or {}).get('coordinates') or []
    if kind == 'Point':
        return [cs]
    if kind == 'LineString':
        return list(cs)
    if kind == 'Polygon':
        return list(cs[0]) if cs else []
    return []


def _feature_id(props, used, fallback):
    """feature 이름. 김제 배관 53개는 node_id 가 없어 다른 칸을 차례로 쓴다."""
    fid = props.get('node_id') or props.get('id') or props.get('_aot_draw_id') or fallback
    if fid in used:
        fid = '%s#%s' % (fid, fallback)
    used.add(fid)
    return fid


def frame_of(features) -> Optional[LocalFrame]:
    """설비 feature 들의 범위 가운데를 원점으로 삼는다. 좌표가 없으면 None."""
    xs, ys = [], []
    for f in features:
        for c in _coords((f or {}).get('geometry')):
            if len(c) >= 2:
                xs.append(c[0])
                ys.append(c[1])
    if not xs:
        return None
    return LocalFrame((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _emitter_lnglat(feature, props):
    """이미터 위치. 원으로 저장한 것은 기하가 아니라 center_lat·center_lng 에 중심을 둔다."""
    if props.get('center_lat') is not None and props.get('center_lng') is not None:
        return _fnum(props['center_lng']), _fnum(props['center_lat'])
    cs = [c for c in _coords((feature or {}).get('geometry')) if len(c) >= 2]
    if not cs:
        return None
    return sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs)


def _pipe_of(feature, props, frame, pid):
    cs = [c for c in _coords(feature.get('geometry')) if len(c) >= 2]
    line = [frame.to_local(c[0], c[1]) for c in cs]
    sub = props.get('sub_type') or props.get('equipment_type')
    return Pipe(id=pid, line=line, sub_type='main' if sub in _MAIN_TYPES else 'branch',
                name=props.get('label') or props.get('name'))


def _drip_emitter(props, pipe):
    """점적 줄 — 줄 하나가 노즐 하나로 든다. 호길이 가운데에 얹고 수량은 길이 ÷ 간격이다.

    줄 중간에 밸브가 서면 줄 전체가 가운데 기준으로 한쪽에 든다. 실데이터에 점적 줄이
    아직 없어 나누지 않았다.

    간격이나 유량이 비면 유량 없음이다. 간격을 지어내면 그 값이 물량에 들어간다.
    """
    cfg = props.get('drip_config') or {}
    length = line_length(pipe.line)
    interval = _fnum(cfg.get('interval'), 0.0)
    count = int(length / interval) if interval > 0 else 0
    flow = _fnum(cfg.get('flow'), 0.0)
    return Emitter(id='drip:%s' % pipe.id, point=_point_at(pipe.line, length / 2.0),
                   pipe_id=pipe.id, kind='drip', count=count,
                   flow_lph=(count * flow) if count and flow > 0 else None, meta=props)


def from_map_features(features, frame=None, gap_m=MAP_GAP_M,
                      part_snap_m=MAP_PART_SNAP_M) -> Optional[Network]:
    """지도 설비 feature 들 → `Network`. 좌표가 하나도 없으면 None.

    노즐은 ``sprinkler_coverage`` 의 중심, 점적은 ``is_drip`` 배관의 ``drip_config``.
    부품은 가장 가까운 배관에 투영한다(W0 는 배관을 나누지 않고 위치만 스냅했다).
    """
    features = [f for f in (features or []) if isinstance(f, dict)]
    frame = frame or frame_of(features)
    if frame is None:
        return None
    pipes, parts, emitters = [], [], []
    used: set = set()
    for i, f in enumerate(features):
        props = f.get('properties') or {}
        sub = props.get('sub_type') or props.get('equipment_type')
        kind = (f.get('geometry') or {}).get('type')
        if sub == _EMITTER_SUB_TYPE:
            at = _emitter_lnglat(f, props)
            if at is None:
                continue
            flow = _fnum(props.get('flow'), 0.0)
            emitters.append(Emitter(id=_feature_id(props, used, 'e%d' % i),
                                    point=frame.to_local(*at),
                                    flow_lph=flow if flow > 0 else None, meta=props))
        elif sub in _MAIN_TYPES + _BRANCH_TYPES and kind == 'LineString':
            pipe = _pipe_of(f, props, frame, _feature_id(props, used, 'p%d' % i))
            pipes.append(pipe)
            if props.get('is_drip'):
                emitters.append(_drip_emitter(props, pipe))
        elif part_table.is_part(sub) and kind == 'Point':
            cs = _coords(f.get('geometry'))
            parts.append(Part(id=_feature_id(props, used, 'k%d' % i), kind=sub,
                              point=frame.to_local(cs[0][0], cs[0][1]),
                              name=props.get('label') or props.get('name'), meta=props))
    net = Network(pipes=pipes, parts=parts, emitters=emitters, gap_m=gap_m,
                  part_snap_m=part_snap_m, emitter_snap_m=DEVICE_SNAP_M)
    net.frame = frame
    return net


def link_part_devices(net: Network, markers: Iterable[dict],
                      radius_m: float = PART_DEVICE_RADIUS_M) -> None:
    """부품 자리의 Output·Input 마커를 찾아 ``net.part_devices`` 에 적는다.

    markers: ``{'device_id', 'device_kind', 'lng', 'lat', 'name'(선택)}``. 반경 안에 하나면
    연결, 둘 이상이면 미연결 + 후보 목록(`part-device-ambiguous`), 없으면 항목을 안 만든다.
    """
    frame = net.frame
    if frame is None:
        return
    spots = []
    for m in markers or ():
        if m.get('device_kind') in _DEVICE_KINDS:
            spots.append((frame.to_local(m['lng'], m['lat']), m))
    for part in net.parts:
        if part.point is None:
            continue
        near = [m for at, m in spots if dist_xz(at, part.point) <= radius_m]
        ids = {m.get('device_id') for m in near}
        if len(ids) == 1:
            net.part_devices[part.id] = {'device': near[0], 'candidates': []}
        elif len(ids) > 1:
            net.part_devices[part.id] = {'device': None, 'candidates': near}
