# coding=utf-8
"""물 회로의 서버 쪽 글루 — DB 에서 재료를 모아 순수 모듈 `water_net` 에 넘긴다.

지도 하나를 **읽을 때마다** 푼다. 결과를 저장하지 않는다 — 도면이 바뀌면 바로 따라오고,
장치 연결은 부품 자리의 마커를 그때그때 찾는다(`GeoBinding` 에 새 항목을 만들지 않는다).

회로는 "어느 공급에 물렸나" 만 답한다. 노즐의 임자는 담당 폴리곤 ∩ 구획
(`mapview._open_field_flow`)이고, 둘이 어긋나면 점검 항목으로만 낸다.

구획의 물량은 `plot_water` 하나로 읽는다. 일지와 구획 [현황]이 같은 값을 낸다.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from aot.functions.utils.water_net import adapters, balance, checks, result
from aot.functions.utils.water_net import parts as part_table

logger = logging.getLogger(__name__)

# find.map_equipment 대상 응답에 싣는 회로 수. 많으면 나머지는 수만 센다.
MCP_MAX_CIRCUITS = 3

# 탱크 수위로 읽는 측정과 리터 환산. 퍼센트는 용량을 곱한다. 길이 단위는 탱크 높이를 몰라 못 쓴다.
LEVEL_MEASUREMENTS = ('volume', 'level', 'water_level')
LEVEL_UNITS = {'l': 1.0, 'ml': 0.001}


def _device_kinds(rows, devices) -> Dict[object, Optional[str]]:
    """도형 → 장치 종류. 바인딩이 없는 옛 도형은 장치 쪽에서 찾는다(농우바이오 마커가 그렇다)."""
    from aot.aot_flask.geo import device_binding

    kinds = dict(device_binding.device_kinds_for_shapes(rows))
    looked: Dict[object, Optional[str]] = {}
    for row in rows:
        device_id = devices.get(row.unique_id)
        if row.unique_id in kinds or not device_id:
            continue
        if device_id not in looked:
            looked[device_id] = device_binding.resolve_device_kind(device_id)
        kinds[row.unique_id] = looked[device_id]
    return kinds


def _map_features(map_uuid) -> List[dict]:
    """지도의 설비 feature 전부. 번들(`equipment_collection`)과 낱개(`equipment`) 둘 다."""
    from aot.databases.models import GeoShape

    out: List[dict] = []
    rows = GeoShape.query.filter(GeoShape.geo_id == map_uuid,
                                 GeoShape.type.in_(['equipment_collection', 'equipment'])).all()
    for row in rows:
        feature = row.feature if isinstance(row.feature, dict) else {}
        if row.type == 'equipment_collection':
            out.extend(f for f in (feature.get('features') or []) if isinstance(f, dict))
        elif feature:
            out.append(feature)
    return out


def _markers(map_uuid) -> List[dict]:
    """지도의 Output·Input 마커. 없어진 장치를 가리키는 마커는 판정에서 빠진다."""
    from aot.aot_flask.geo import device_binding, device_membership
    from aot.databases.models import GeoShape

    rows = GeoShape.query.filter_by(geo_id=map_uuid, type='aot_device').all()
    devices = device_binding.devices_for_shapes(rows)
    kinds = _device_kinds(rows, devices)
    names = device_binding._device_names(devices.values())
    out = []
    for row in rows:
        pt = device_membership._marker_point(row)
        device_id = devices.get(row.unique_id)
        if pt is None or not device_id:
            continue
        out.append({'device_id': device_id, 'device_kind': kinds.get(row.unique_id),
                    'name': names.get(device_id), 'lng': pt[0], 'lat': pt[1]})
    return out


def _emitter_points(net) -> Dict[object, object]:
    from shapely.geometry import Point
    return {em.id: Point(*net.frame.to_lnglat(em.point))
            for em in net.emitters if em.point is not None}


def _covers(map_uuid, points) -> List[checks.Cover]:
    """Output 마다 담당 폴리곤과 그 안의 노즐. 폴리곤은 `mapview` 규칙처럼 합집합이다."""
    from shapely.geometry import shape as shapely_shape
    from shapely.prepared import prep

    from aot.aot_flask.geo import device_binding
    from aot.databases.models import GeoShape

    rows = GeoShape.query.filter_by(geo_id=map_uuid, type='device').all()
    devices = device_binding.devices_for_shapes(rows)
    kinds = _device_kinds(rows, devices)
    names = device_binding._device_names(devices.values())
    regions: Dict[object, object] = {}
    for row in rows:
        device_id = devices.get(row.unique_id)
        if not device_id or kinds.get(row.unique_id) != 'output':
            continue
        try:
            area = shapely_shape((row.feature or {}).get('geometry') or {})
        except Exception:                                   # noqa: BLE001
            continue
        if area.is_empty:
            continue
        regions[device_id] = area if device_id not in regions else regions[device_id].union(area)
    out = []
    for device_id, region in regions.items():
        ready = prep(region)
        inside = [eid for eid, pt in points.items() if ready.contains(pt)]
        out.append(checks.Cover(device_id, names.get(device_id), inside))
    return out


def _zone_flows(net, map_uuid, points) -> Dict[object, float]:
    """유량이 비었지만 구역 기본값이 있는 노즐 → L/h. `mapview._map_sprinklers` 의 backfill 과 같다."""
    from aot.aot_flask.geo.plot_journal import mapview

    missing = [em.id for em in net.emitters if not em.flow_lph and em.id in points]
    if not missing:
        return {}
    defaults = mapview._zone_emitter_defaults(map_uuid)
    flows = {eid: mapview._default_flow_at(points[eid], defaults) for eid in missing}
    return {eid: lph for eid, lph in flows.items() if lph > 0}


def network_for_map(map_uuid, features=None):
    """지도 → 장치 연결까지 마친 `Network`. 설비가 없으면 None."""
    net = adapters.from_map_features(_map_features(map_uuid) if features is None else features)
    if net is not None and net.parts:
        adapters.link_part_devices(net, _markers(map_uuid))
    return net


def _part_row(net, part) -> dict:
    link = net.part_devices.get(part.id) or {}
    device = link.get('device') or {}
    return {'id': part.id, 'kind': part.kind, 'name': part.name,
            'device': device.get('device_id'), 'device_name': device.get('name')}


def _circuits(net, emitter_ids) -> List[dict]:
    """대상 노즐들이 물린 회로마다 공통 상류 경로. 공급이 없는 회로는 경로를 내세우지 않는다."""
    out = []
    for row in net.shared_upstream(emitter_ids):
        comp = row['component']
        fed = comp in net.fed
        out.append({'network': comp, 'supplied': fed,
                    'sources': [_part_row(net, p) for p in row['sources']],
                    'path': row['path'] if fed else []})
    return out


def _area_rows(net, map_uuid, points) -> List[dict]:
    """대지·구역마다 안에 든 노즐의 회로. 소속은 위치로 정한다(대지는 구역까지 포함)."""
    from shapely.geometry import shape as shapely_shape
    from shapely.prepared import prep

    from aot.aot_flask.geo.device_membership import place_label
    from aot.databases.models import GeoShape

    out = []
    rows = GeoShape.query.filter(GeoShape.geo_id == map_uuid,
                                 GeoShape.type.in_(['site', 'zone'])).all()
    for row in rows:
        feature = row.feature if isinstance(row.feature, dict) else {}
        try:
            region = shapely_shape(feature.get('geometry') or {})
        except Exception:                                   # noqa: BLE001
            continue
        if region.is_empty or region.geom_type not in ('Polygon', 'MultiPolygon'):
            continue
        ready = prep(region)
        inside = [eid for eid, pt in points.items() if ready.contains(pt)]
        if inside:
            out.append({'id': row.unique_id, 'type': row.type, 'name': place_label(row),
                        'emitters': len(inside), 'circuits': _circuits(net, inside)})
    return out


def _empty_report(map_uuid) -> dict:
    return {'map_uuid': map_uuid, 'summary': None, 'networks': [], 'areas': [], 'parts': [],
            'checks': [], 'check_counts': {}}


def report_for_map(map_uuid) -> dict:
    """`GET /api/geo/water_net` 응답. 저장 상태 기준이고 쓰기는 없다."""
    started = time.perf_counter()
    net = network_for_map(map_uuid)
    if net is None:
        return _empty_report(map_uuid)
    points = _emitter_points(net)
    issues = checks.find_issues(net, _covers(map_uuid, points),
                                list(_zone_flows(net, map_uuid, points)))
    networks = []
    for comp in range(len(net.components)):
        networks.append({
            'id': comp, 'pipes': len(net.component_pipes(comp)),
            'emitters': len(net.component_emitters(comp)), 'supplied': comp in net.fed,
            'sources': [_part_row(net, p) for p in net.component_sources(comp)],
            'loops': max(0, net.component_loops(comp)),
        })
    flows = _emitter_flows(net, map_uuid, points)
    for row, comp in zip(networks, range(len(net.components))):
        row.update(_budget(net, comp, flows))
    parts = []
    for part in net.parts:
        row = _part_row(net, part)
        row['attached'] = part not in net.loose_parts
        row['path'] = net.upstream_path(part.id) if net.sources_of(part.id) else []
        row['downstream_emitters'] = len(net.downstream_emitters(part.id))
        row['device_kind'] = ((net.part_devices.get(part.id) or {}).get('device') or {}).get(
            'device_kind')
        row['candidates'] = [{'device': c.get('device_id'), 'name': c.get('name'),
                              'kind': c.get('device_kind')}
                             for c in (net.part_devices.get(part.id) or {}).get('candidates') or []]
        parts.append(row)
    return {
        'map_uuid': map_uuid,
        'summary': checks.summarize(net),
        'networks': networks,
        'areas': _area_rows(net, map_uuid, points),
        'parts': parts,
        'checks': issues,
        'check_counts': checks.count_by_code(issues),
        'elapsed_ms': round((time.perf_counter() - started) * 1000.0),
    }


def _budget(net, comp, flows) -> dict:
    """회로 하나의 설계 여유 — 펌프 능력 대비 수요, 탱크가 버티는 시간.

    값을 모르면 비우지 않고 이유를 코드로 준다(`pump_note`·`tank_note`). 수요는 회로 안 노즐 유량의 합이다.
    탱크 시간은 가득 찬 탱크에서 보충 없이 수요만큼 나갈 때다 — 수위 측정은 작동 계산(`water_net.balance`)의 몫이다.
    """
    demand = sum(flows.get(em.id, 0.0) for em in net.component_emitters(comp)) / 60.0
    sources = net.component_sources(comp)
    pumps = [p for p in sources if p.kind == 'pump']
    tanks = [p for p in sources if p.kind == 'tank']
    out: dict = {'demand_lpm': round(demand, 1) if demand else None, 'pump_lpm': None,
                 'pump_ratio': None, 'pump_note': None, 'tank_l': None, 'tank_min': None,
                 'tank_note': None}
    rated = [_number(p.meta, 'rated_lpm') for p in pumps]
    if not pumps:
        out['pump_note'] = 'no-pump'
    elif not all(rated):
        out['pump_note'] = 'no-rating'
    else:
        out['pump_lpm'] = round(sum(rated), 1)
        if demand:
            out['pump_ratio'] = round(sum(rated) / demand, 2)
        else:
            out['pump_note'] = 'no-demand'
    caps = [_number(t.meta, 'capacity_l') for t in tanks]
    if not tanks:
        out['tank_note'] = 'no-tank'
    elif not all(caps):
        out['tank_note'] = 'no-capacity'
    else:
        out['tank_l'] = round(sum(caps), 1)
        if demand:
            out['tank_min'] = round(sum(caps) / demand, 1)
        else:
            out['tank_note'] = 'no-demand'
    return out


def output_paths(map_uuid) -> dict:
    """Output → 그 담당 폴리곤 안 노즐들의 상류 배관·부품 id. 지도 위젯이 켜진 출력의 경로만 굵게 그린다.

    공급이 있는 회로(`fed`)만 낸다 — 물이 어디서 오는지 모르는 회로는 강조할 경로가 없다. 설계 기준이라
    출력이 켜지고 꺼져도 변하지 않으므로 위젯은 한 번만 읽는다.
    """
    net = network_for_map(map_uuid)
    if net is None or not net.fed:
        return {'outputs': {}, 'network_rev': None}
    out: Dict[str, list] = {}
    for cover in _covers(map_uuid, _emitter_points(net)):
        ids = set()
        for eid in cover.emitter_ids:
            if net.component_id(eid) in net.fed:
                ids.update(str(step['id']) for step in net.upstream_path(eid))
        if ids:
            out[cover.output_id] = sorted(ids)
    return {'outputs': out, 'network_rev': result.network_rev(net)}


def _short_path(path) -> List[str]:
    """경로 칸을 글자로 — 부품은 이름 또는 종류, 배관은 종류. 이어진 같은 종류는 한 칸."""
    out: List[str] = []
    for step in path:
        label = step.get('kind') if step.get('type') == 'pipe' else (step.get('name') or step.get('kind'))
        if not out or out[-1] != label:
            out.append(label)
    return out


def area_water_path(map_uuid, shape_uuid) -> Optional[dict]:
    """find.map_equipment 대상 응답에 싣는 짧은 상류 요약. 설비·노즐이 없으면 None."""
    from shapely.geometry import shape as shapely_shape

    from aot.databases.models import GeoShape

    row = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    net = network_for_map(map_uuid)
    if row is None or net is None:
        return None
    region = shapely_shape((row.feature or {}).get('geometry') or {})
    inside = [eid for eid, pt in _emitter_points(net).items() if region.contains(pt)]
    circuits = _circuits(net, inside)
    if not circuits:
        return None
    fed = [c for c in circuits if c['supplied']]
    out: dict = {'circuits': len(circuits),
                 'supplied': [{'sources': [s['name'] or s['kind'] for s in c['sources']],
                               'path': _short_path(c['path'])}
                              for c in fed[:MCP_MAX_CIRCUITS]]}
    if len(circuits) > len(fed):
        out['no_source'] = len(circuits) - len(fed)
    return out


# ── 물 결과 ────────────────────────────────────────────────────────────────

class PlotWater:
    """구획 하나의 물량 읽기 — 일지와 구획 [현황]이 **같은 값**을 읽는 단일 진입점.

    ``flows`` 는 설계 유량(`irrigation_flow_for_plot`), ``ratios`` 는 공급 한계를 풀어 낸
    버킷별 전달 비율이다. 공급 부품이 없거나 회로가 `fed` 가 아니면 ``ratios`` 가 비고 값은
    설계 유량 × 가동시간 그대로다.
    """

    def __init__(self, flows=None):
        self.flows = flows or {}
        self.ratios: Dict[object, Dict[object, List[float]]] = {}  # {출력: {버킷: [초, 전달 초]}}
        self.result: Optional[dict] = None    # `result.water_result`. 공급을 푼 구획만
        self.caveats: List[str] = []          # 일지 caveat 키
        self.supply_outputs: set = set()      # 공급 부품에 연결된 Output
        self.plot_id: Optional[str] = None
        self.area_m2: Optional[float] = None  # 구획 면적 — 공급을 푼 값의 mm 환산에만 쓴다
        self.tally = result.Tally()           # 일지 caveat·일 합계가 읽는 합

    def _book(self, output_id, key, seconds, ratio):
        box = self.ratios.setdefault(output_id, {}).setdefault(key, [0.0, 0.0])
        box[0] += seconds
        box[1] += seconds * ratio

    def _ratio(self, output_id, key) -> Optional[float]:
        box = self.ratios.get(output_id, {}).get(key)
        return box[1] / box[0] if box and box[0] > 0 else None

    def cell(self, output_id, key, secs) -> Optional[dict]:
        """제어 행의 `water` 칸. 유량 근거가 없으면 None.

        ``litres`` 는 공급 한계를 반영한 주 값이고 ``design_litres`` 는 노즐 설계값이다(결정 13-3).
        """
        flow = self.flows.get(output_id)
        if not flow or not flow.get('lph'):
            return None
        design = _design_litres(secs, flow)
        row = {
            'litres': round(design, 1),
            'share': flow.get('share', 1.0),
            'estimated': True,
            # 근거가 배관 도면인지 지도 장비인지 — 나누는 방식이 아예 달라(동의 몫 · 구획 안
            # 노즐) 문서 문장이 갈린다.
            'source': flow.get('source'),
        }
        ratio = self._ratio(output_id, key)
        if ratio is not None:
            row['litres'] = round(design * ratio, 1)
            row['design_litres'] = round(design, 1)
            row['delivered_ratio'] = round(ratio, 3)
            if self.area_m2:
                row['mm'] = round(row['litres'] / self.area_m2, 2)
        return row

    def design(self, output_id, by_key) -> Optional[float]:
        """공급을 푼 장치의 노즐 설계 물량 합. 공급을 풀지 않았으면 None — `litres` 와 같은 값이다."""
        flow = self.flows.get(output_id)
        if not flow or not flow.get('lph') or output_id not in self.ratios:
            return None
        return round(sum(_design_litres(secs, flow) for secs in by_key.values()), 1)

    def litres(self, output_id, by_key) -> Optional[float]:
        """`{버킷: 초}` 의 물량 합. 유량 근거가 없으면 None."""
        flow = self.flows.get(output_id)
        if not flow or not flow.get('lph'):
            return None
        if output_id not in self.ratios:
            return round(_design_litres(float(sum(by_key.values())), flow), 1)
        total = 0.0
        for key, secs in by_key.items():
            ratio = self._ratio(output_id, key)
            total += _design_litres(secs, flow) * (1.0 if ratio is None else ratio)
        return round(total, 1)


def _design_litres(secs, flow) -> float:
    return secs / 3600.0 * float(flow['lph']) * float(flow.get('share', 1.0) or 1.0)


def _has_supply(features) -> bool:
    """공급 부품이 있는 지도인가. 없으면 그래프를 풀지 않는다(나주 180ms)."""
    for feature in features:
        props = feature.get('properties') or {}
        part = part_table.get(props.get('sub_type') or props.get('equipment_type'))
        if part is not None and part.group == 'supply':
            return True
    return False


def _linked_device(net, part, kind) -> Optional[str]:
    """부품 자리에 연결된 장치 id. 종류가 다르면 None."""
    device = (net.part_devices.get(part.id) or {}).get('device') or {}
    return device.get('device_id') if device.get('device_kind') == kind else None


def _supply_outputs(net) -> set:
    """공급 부품에 연결된 Output. 판정은 위치다(`adapters.link_part_devices`)."""
    found = set()
    for part in net.parts:
        rule = part_table.get(part.kind)
        device = _linked_device(net, part, 'output')
        if device and rule is not None and rule.group == 'supply':
            found.add(device)
    return found


def _epoch(text) -> float:
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()


def _utc_text(epoch) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _bucket_key(t, bucket_sec, tz, granularity):
    """켠 시각 → 그 사건이 합쳐지는 버킷. `aggregateWindow` 창과 같은 눈금으로 접는다."""
    from aot.utils.timekit import bucket_local_key

    stop = (int(t) // int(bucket_sec) + 1) * int(bucket_sec)
    return bucket_local_key(datetime.fromtimestamp(stop, timezone.utc), bucket_sec, tz, granularity)


def _emitter_flows(net, map_uuid, points) -> Dict[object, float]:
    """노즐 유량. 비었으면 구역 기본값 — 일지가 물량에 쓰는 것과 같은 값이다."""
    flows = {em.id: em.flow_lph for em in net.emitters if em.flow_lph}
    flows.update(_zone_flows(net, map_uuid, points))
    return flows


def _circuit_demands(net, covers, flows) -> Dict[object, Dict[object, float]]:
    """Output → {회로: L/h}. 담당 폴리곤 전체다 — 구획 밖 노즐도 같은 펌프의 물을 쓴다."""
    out: Dict[object, Dict[object, float]] = {}
    for cover in covers:
        row = out.setdefault(cover.output_id, {})
        for eid in cover.emitter_ids:
            comp = net.component_id(eid)
            row[comp] = row.get(comp, 0.0) + flows.get(eid, 0.0)
    return out


def _plot_weights(net, plot, covers, flows, points, wanted) -> Dict[object, Dict[object, float]]:
    """구획 안 노즐의 회로별 몫 → {Output: {회로: 0~1}}. 노즐의 임자는 담당 폴리곤이 이미 정했다."""
    from shapely.geometry import shape as shapely_shape
    from shapely.prepared import prep

    ready = prep(shapely_shape((getattr(plot, 'feature', None) or {}).get('geometry') or {}))
    out: Dict[object, Dict[object, float]] = {}
    for cover in covers:
        if cover.output_id not in wanted:
            continue
        lph: Dict[object, float] = {}
        for eid in cover.emitter_ids:
            if flows.get(eid) and ready.contains(points[eid]):
                comp = net.component_id(eid)
                lph[comp] = lph.get(comp, 0.0) + flows[eid]
        total = sum(lph.values())
        if total > 0:
            out[cover.output_id] = {comp: value / total for comp, value in lph.items()}
    return out


def _number(meta, key) -> Optional[float]:
    try:
        value = float((meta or {}).get(key))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _read_levels(device_id, capacity, start_str, end_str) -> Optional[list]:
    """수위 측정 → [(epoch, L)]. 리터로 못 바꾸는 측정이면 None."""
    from aot.databases.models import DeviceMeasurements
    from aot.utils.influx import read_influxdb_list

    rows = DeviceMeasurements.query.filter_by(device_id=device_id).order_by(
        DeviceMeasurements.channel).all()
    for dm in rows:
        scale = LEVEL_UNITS.get(dm.unit)
        if dm.unit == 'percent' and capacity:
            scale = capacity / 100.0
        if scale is None or (dm.measurement or '') not in LEVEL_MEASUREMENTS:
            continue
        data = read_influxdb_list(device_id, dm.unit, dm.channel, measure=dm.measurement,
                                  start_str=start_str, end_str=end_str)
        if data:
            return [(float(t), float(v) * scale) for t, v in data if v is not None]
    return None


def _measured_kwh(device_id, start_str, end_str) -> Optional[float]:
    """장치의 전력 측정 → kWh. 측정 채널이 없거나 값이 모자라면 None."""
    from aot.databases.models import DeviceMeasurements
    from aot.utils.influx import read_influxdb_list

    rows = DeviceMeasurements.query.filter(DeviceMeasurements.device_id == device_id,
                                           DeviceMeasurements.unit.in_(('kWh', 'W'))).all()
    for dm in sorted(rows, key=lambda r: r.unit != 'kWh'):
        data = read_influxdb_list(device_id, dm.unit, dm.channel, measure=dm.measurement,
                                  start_str=start_str, end_str=end_str)
        kwh = balance.energy_kwh([(float(t), float(v)) for t, v in data or () if v is not None],
                                 dm.unit)
        if kwh is not None:
            return kwh
    return None


def _circuit_of(net, comp, runs_of, read_from, start_str, end_str) -> balance.Circuit:
    pumps, sources, tanks = [], [], []
    for part in net.component_sources(comp):
        meta = part.meta if isinstance(part.meta, dict) else {}
        if part.kind == 'pump':
            output = _linked_device(net, part, 'output')
            meter = output or _linked_device(net, part, 'input')
            pumps.append(balance.Pump(part.id, _number(meta, 'rated_lpm'),
                                      _number(meta, 'power_kw'),
                                      runs_of[output] if output else None,
                                      _measured_kwh(meter, start_str, end_str) if meter else None))
        elif part.kind == 'tank':
            sensor = _linked_device(net, part, 'input')
            capacity = _number(meta, 'capacity_l')
            tanks.append(balance.Tank(part.id, capacity, _read_levels(
                sensor, capacity, read_from, end_str) if sensor else None))
        else:
            sources.append(balance.Source(part.id, _number(meta, 'max_lpm')))
    return balance.Circuit(comp, pumps, sources, tanks)


def _circuit_outputs(net, comp, demands) -> Dict[object, float]:
    """회로의 Output → L/min. 담당 폴리곤이 없는 밸브 Output 도 '열림' 판단에 들어간다."""
    out = {oid: by_comp[comp] / 60.0 for oid, by_comp in demands.items() if by_comp.get(comp)}
    for part in net.parts:
        rule = part_table.get(part.kind)
        device = _linked_device(net, part, 'output')
        if device and rule is not None and rule.group == 'valve' \
                and net.component_id(part.id) == comp:
            out.setdefault(device, 0.0)
    return out


def _read_runs(net, comps, outputs, read_from, end_str) -> Dict[object, list]:
    """필요한 Output 의 작동 구간. 하나라도 못 읽으면 계산을 접는다 — 빈 것으로 치면 틀린다."""
    from aot.utils.runtime import get_operational_intervals

    wanted = {oid for comp in comps for oid in outputs[comp]}
    for comp in comps:
        for part in net.component_sources(comp):
            device = _linked_device(net, part, 'output')
            if device:
                wanted.add(device)
    runs_of = {}
    for oid in sorted(wanted):
        runs = get_operational_intervals(oid, read_from, end_str)
        if runs is None:
            raise LookupError('작동 구간을 읽지 못했다: %s' % oid)
        runs_of[oid] = runs
    return runs_of


def _source_names(net, comp) -> List[str]:
    return [p.name or p.kind for p in net.component_sources(comp) if p.kind not in ('pump', 'tank')]


def _extra_caveats(net, comps) -> List[str]:
    """회로 모양에서 나오는 표시 — 탱크 앞 펌프, 유량을 모르는 점적 줄."""
    out = []
    for comp in comps:
        found = net.component_sources(comp)
        pumps = {p.id for p in found if p.kind == 'pump'}
        for tank in (p for p in found if p.kind == 'tank'):
            if any(step['id'] in pumps for step in net.upstream_path(tank.id)):
                out.append(result.PUMP_BEFORE_TANK)
        if any(em.kind == 'drip' and not em.flow_lph for em in net.component_emitters(comp)):
            out.append(result.DRIP_FLOW_UNKNOWN)
    return out


def _journal_caveats(tally, tz) -> List[str]:
    """합 → 일지 caveat 키. 시간·시각은 접미사로 싣는다(문장은 `render.caveat_text`)."""
    from aot.utils.timekit import to_tz

    out = []
    if tally.delivered_l < tally.design_l - 0.05:
        out.append('%s:%s:%s' % (result.SUPPLY_LIMITED, round(tally.delivered_l, 1),
                                 round(tally.design_l, 1)))
    for code in result.CAVEATS:
        if code not in tally.codes or code == result.SUPPLY_LIMITED:
            continue
        seconds = tally.seconds.get(code)
        if seconds:
            out.append('%s:%d' % (code, max(1, round(seconds / 60.0))))
        elif code == result.TANK_EMPTY and tally.empty_at is not None:
            local = to_tz(datetime.fromtimestamp(tally.empty_at, timezone.utc), tz)
            out.append('%s:%s' % (code, local.strftime('%m-%d %H:%M')))
        else:
            out.append(code)
    return out


class _Plan:
    """한 번의 읽기에 쓰는 재료 — 구획·지도가 정하는 것이라 구간마다 다시 만들 필요가 없다."""

    def __init__(self, plot, tz, granularity, bucket_sec, full):
        self.plot = plot
        self.tz = tz
        self.granularity = granularity
        self.bucket_sec = bucket_sec
        self.full = full
        self.net = None
        self.comps: List[int] = []
        self.covers: list = []
        self.weights: Dict[object, Dict[object, float]] = {}
        self.demands: Dict[object, Dict[object, float]] = {}
        self.rev = ''
        self.area = None


def _plan(water, plot, map_uuid, features, tz, granularity, bucket_sec, full) -> _Plan:
    """공급 부품이 있는 지도면 회로를 세운다 — 구획의 Output 마다 몫을 정하는 데까지."""
    from aot.aot_flask.geo import plot_context

    plan = _Plan(plot, tz, granularity, bucket_sec, full)
    plan.area = plot_context.area_m2(plot)
    if features is None:
        return plan
    net = network_for_map(map_uuid, features)
    if net is None:
        return plan
    plan.net = net
    water.supply_outputs = _supply_outputs(net)
    points = _emitter_points(net)
    plan.covers = _covers(map_uuid, points)
    flows = _emitter_flows(net, map_uuid, points)
    wanted = {oid for oid, flow in water.flows.items() if flow.get('lph')}
    plan.weights = _plot_weights(net, plot, plan.covers, flows, points, wanted)
    plan.comps = sorted({c for row in plan.weights.values() for c in row if c in net.fed})
    if plan.comps:
        plan.demands = _circuit_demands(net, plan.covers, flows)
        plan.rev = result.network_rev(net, plan.comps)
    return plan


class _Acc:
    """읽은 것의 모음 — 저장값과 계산값을 한 곳에 쌓는다."""

    def __init__(self):
        self.rows: List[dict] = []
        self.supply: List[dict] = []
        self.tally = result.Tally()
        self.stored_until: Optional[float] = None
        self.live_from: Optional[float] = None
        self.revs: set = set()


def _live_span(water, plan, acc, a, b) -> None:
    """``[a, b)`` 를 읽을 때 계산한다 — 켠 시각이 이 구간에 든 실행."""
    from aot.utils.runtime import get_operational_intervals
    from aot.utils.twin_device_state import LOOKBACK_S

    net = plan.net
    start_str, end_str = _utc_text(a), _utc_text(b)
    read_from = _utc_text(a - LOOKBACK_S)
    runs_of: Dict[object, list] = {}
    ratios: Dict[object, float] = {}
    solved = []
    if plan.comps:
        outputs = {comp: _circuit_outputs(net, comp, plan.demands) for comp in plan.comps}
        runs_of = _read_runs(net, plan.comps, outputs, read_from, end_str)
        for comp in plan.comps:
            runs = [balance.Run(oid, x, y) for oid in outputs[comp] for x, y in runs_of[oid]]
            row = balance.solve(
                _circuit_of(net, comp, runs_of, read_from, start_str, end_str),
                outputs[comp], runs, a, b)
            solved.append(row)
            for run in row['runs']:
                ratios[(comp, run['output_id'], run['t0'], run['t1'])] = run['ratio']

    booked = set()
    for oid, by_comp in plan.weights.items():
        flow = water.flows[oid]
        fed = {c: w for c, w in by_comp.items() if c in net.fed}
        if not fed:
            continue
        booked.add(oid)
        for x, y in runs_of.get(oid) or ():
            if not a <= x < b:
                continue
            ratio = sum(w * ratios.get((c, oid, x, y), 1.0) if c in fed else w
                        for c, w in by_comp.items())
            design = _design_litres(y - x, flow)
            water._book(oid, _bucket_key(x, plan.bucket_sec, plan.tz, plan.granularity),
                        y - x, ratio)
            acc.tally.add_run(design, design * ratio)
            acc.rows.append(result.run_row(oid, x, y, float(flow['lph']) / 60.0, design, ratio,
                                           plan.area, fed=True, rev=plan.rev))
    if plan.comps:
        acc.revs.add(plan.rev)
    for row in solved:
        acc.tally.add_solved(row)
    acc.tally.add_codes(_extra_caveats(net, plan.comps) if net is not None else ())
    acc.supply.extend({'circuit': row['id'], 'source': _source_names(net, row['id']),
                       'demand_l': row['demand_l'], 'delivered_l': row['delivered_l'],
                       'delivered_ratio': row['delivered_ratio'], 'pump': row['pump'],
                       'tank': row['tank']} for row in solved)

    if not plan.full:
        return
    # 공급을 풀지 않은 장치도 설계값으로 싣는다 — 트윈이 모든 구획의 일 합계를 읽는다.
    for oid, flow in water.flows.items():
        if oid in booked or not flow.get('lph'):
            continue
        spans = runs_of.get(oid)
        if spans is None:
            spans = get_operational_intervals(oid, start_str, end_str)
            if spans is None:
                raise LookupError('작동 구간을 읽지 못했다: %s' % oid)
        for x, y in spans:
            if a <= x < b:
                acc.rows.append(result.run_row(oid, x, y, float(flow['lph']) / 60.0,
                                               _design_litres(y - x, flow), 1.0, plan.area))


def _stored_rows(water, plan, acc, covered) -> None:
    """닫힌 날은 저장된 실행과 일 합계를 읽는다. 공급을 푼 실행만 일지 장부에 올린다."""
    from aot.utils import water_store

    spans = sorted(water_store.day_bounds(day, plan.tz) for day in covered)
    rows = water_store.read_runs(water.plot_id, spans[0][0], spans[-1][1])
    for row in rows:
        if not any(a <= row['t0'] < b for a, b in spans):
            continue
        if row['fed']:
            water._book(row['output_id'], _bucket_key(row['t0'], plan.bucket_sec, plan.tz,
                                                      plan.granularity),
                        row['seconds'], row['ratio'])
            acc.tally.add_run(row['design_litres'] or 0.0, row['litres'] or 0.0)
            acc.revs.add(row['network_rev'])
        if plan.full or row['fed']:
            acc.rows.append(row)
    for box in covered.values():
        acc.tally.add_day(box['values'])
    acc.stored_until = spans[-1][1]


def _uncovered(t0, t1, tz, covered) -> List[tuple]:
    """저장된 날을 뺀 나머지 구간들 — 이어진 구간은 하나로 묶는다."""
    from aot.utils import water_store

    cuts = sorted(water_store.day_bounds(day, tz) for day in covered)
    out, cursor = [], t0
    for a, b in cuts:
        if a > cursor:
            out.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < t1:
        out.append((cursor, t1))
    return out


def _covered(water, t0, t1, tz) -> Dict[object, dict]:
    """닫혀서 저장된 날. 저장소를 못 읽으면 비어 있는 것으로 친다 — 전부 계산으로 읽는다."""
    from aot.utils import water_store

    try:
        return water_store.covered_days(water.plot_id, t0, t1, tz)
    except Exception:                                       # noqa: BLE001
        logger.debug('물 결과 저장소를 읽지 못했다: %s', water.plot_id, exc_info=True)
        return {}


def _revision(acc) -> str:
    revs = {rev for rev in acc.revs if rev}
    if len(revs) > 1:
        return result.MIXED_REV
    return next(iter(revs)) if revs else ''


def plot_water(plot, start_str, end_str, tz, granularity='day', bucket_sec=3600, full=False,
               stored=True) -> PlotWater:
    """구획의 물량 — 일지·구획 [현황]·MCP 의 단일 진입점.

    저장된 닫힌 날은 저장값(`water_run`·`water_day`)을 읽고, 빈 날과 진행 중인 날만 계산해 합친다.
    계산은 `_live_span` 하나다 — 저장하는 쪽(`water_job`)도 같은 함수로 `stored=False` 로 푼다.

    ``full`` 이면 공급 부품이 없는 구획과 시설 구획도 설계값 실행을 만든다(저장·MCP 용). 일지와
    [현황]은 `full=False` 라 공급 부품이 없는 지도는 그래프도 저장소도 건드리지 않는다.
    공급 계산이 실패해도 설계값은 나간다 — 일지가 안 열리면 안 되고, 실패는 caveat 로 말한다.
    """
    from aot.aot_flask.geo.plot_journal import irrigation_flow_for_plot
    from aot.aot_flask.geo.plot_journal.mapview import _map_of_plot

    water = PlotWater(irrigation_flow_for_plot(plot) or {})
    water.plot_id = getattr(plot, 'unique_id', None)
    if not any(flow.get('lph') for flow in water.flows.values()):
        return water
    facility = bool(getattr(plot, 'facility_uuid', None))
    if facility and not full:
        return water
    features = None
    map_uuid = None
    if not facility:
        map_uuid = getattr(plot, 'geo_id', None) or _map_of_plot(plot)
        features = _map_features(map_uuid)
        if not _has_supply(features) and not full:
            return water
    t0, t1 = _epoch(start_str), _epoch(end_str)
    acc = _Acc()
    try:
        plan = _plan(water, plot, map_uuid, features, tz, granularity, bucket_sec, full)
        water.area_m2 = plan.area
        covered = _covered(water, t0, t1, tz) if stored else {}
        if covered:
            _stored_rows(water, plan, acc, covered)
        for a, b in _uncovered(t0, t1, tz, covered):
            acc.live_from = a if acc.live_from is None else min(acc.live_from, a)
            _live_span(water, plan, acc, a, b)
    except Exception:                                       # noqa: BLE001
        logger.exception('물 회로: 공급 계산 실패 (%s)', water.plot_id)
        water.ratios.clear()
        water.result = None
        water.tally = result.Tally()
        water.caveats = [result.SUPPLY_NOT_READ]
        return water
    water.tally = acc.tally
    if plan.comps or acc.stored_until is not None or full:
        acc.rows.sort(key=lambda r: (r['t0'], str(r['output_id'])))
        codes = result.merge_caveats([sorted(acc.tally.codes)])
        water.result = result.water_result('plot', water.plot_id, t0, t1, _revision(acc),
                                           acc.rows, acc.supply, codes,
                                           stored_until=acc.stored_until, tally=acc.tally,
                                           area_m2=plan.area, live_from=acc.live_from)
        water.caveats = _journal_caveats(acc.tally, tz)
    return water


# ── MCP·API 읽기 ───────────────────────────────────────────────────────────

MCP_MAX_OUTPUTS = 8


def delivered_summary(plot, days) -> dict:
    """구획이 최근 ``days`` 일(오늘 포함, 현지 날짜) 동안 받은 물 — `measure.water_delivered`.

    일지·[현황]과 같은 `plot_water` 를 `full=True` 로 읽는다. 닫힌 날은 저장값, 오늘은 읽을 때 계산한
    값이고 응답이 그 경계를 알린다(``computed_from``). 물량은 노즐 설계값에 공급 한계를 반영한 **추정**이다.
    """
    from aot.databases.models import Output
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils.timekit import as_tz, local_day_bounds_utc, to_tz

    tz = as_tz(resolve_location_tz(getattr(plot, 'unique_id', None)))
    today = to_tz(datetime.now(timezone.utc), tz).date()
    first = today - timedelta(days=max(int(days), 1) - 1)
    start_str, end_str = local_day_bounds_utc(first, today, tz)
    water = plot_water(plot, start_str, end_str, tz, full=True)
    out: dict = {'plot': water.plot_id, 'from': first.isoformat(), 'to': today.isoformat(),
                 'basis': 'estimated'}
    res = water.result
    if res is None:
        out['litres'] = None
        out['caveats'] = water.caveats or ['water-no-flow-basis']
        return out
    names = {o.unique_id: o.name for o in Output.query.filter(
        Output.unique_id.in_({r['output_id'] for r in res['runs']})).all()} if res['runs'] else {}
    sums: Dict[object, dict] = {}
    for run in res['runs']:
        box = sums.setdefault(run['output_id'], {'output': names.get(run['output_id'])
                                                 or str(run['output_id'])[:8],
                                                 'litres': 0.0, 'design_litres': 0.0, 'hours': 0.0})
        box['litres'] += run['litres']
        box['design_litres'] += run['design_litres']
        box['hours'] += run['seconds'] / 3600.0
    totals = res['totals']
    out.update({'litres': totals['litres'], 'design_litres': totals['design_litres'],
                'mm': totals['mm'], 'hours': round(totals['seconds'] / 3600.0, 2),
                'runs': totals['runs'], 'kwh': totals['kwh'], 'kwh_basis': totals['kwh_basis'],
                'pump_hours': totals['pump_hours'], 'network_rev': res['network_rev'] or None})
    live = res['live_from']
    # 읽을 때 계산한 가장 이른 날. 저장 안 된 날이 저장된 날 앞에 있으면 그 날이고, 전부 저장값이면 None.
    out['computed_from'] = (to_tz(datetime.fromtimestamp(live, timezone.utc), tz).date().isoformat()
                            if live is not None else None)
    rows = sorted(sums.values(), key=lambda r: -r['litres'])
    out['outputs'] = [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()}
                      for r in rows[:MCP_MAX_OUTPUTS]]
    if len(rows) > MCP_MAX_OUTPUTS:
        out['outputs_more'] = len(rows) - MCP_MAX_OUTPUTS
    out['caveats'] = water.caveats
    return out


def area_sources(shapes) -> Dict[str, Optional[str]]:
    """대지·구역 이름 → 그 구역 노즐이 물린 공급 원천 이름들(`find.map_equipment` 목록의 한 칸).

    지도마다 회로를 한 번만 푼다. 공급 부품이 없으면 값이 없다. 이름이 같은 구역이 여럿이면 이름을 합친다.
    """
    from shapely.geometry import shape as shapely_shape
    from shapely.prepared import prep

    by_map: Dict[object, list] = {}
    for row in shapes:
        if row.type in ('site', 'zone'):
            by_map.setdefault(row.geo_id, []).append(row)
    found: Dict[str, List[str]] = {}
    for map_uuid, rows in by_map.items():
        net = network_for_map(map_uuid)
        if net is None or not net.parts:
            continue
        points = _emitter_points(net)
        for row in rows:
            feature = row.feature if isinstance(row.feature, dict) else {}
            try:
                region = shapely_shape(feature.get('geometry') or {})
            except Exception:                               # noqa: BLE001
                continue
            if region.is_empty or region.geom_type not in ('Polygon', 'MultiPolygon'):
                continue
            ready = prep(region)
            inside = [eid for eid, pt in points.items() if ready.contains(pt)]
            names = found.setdefault(str(feature.get('properties', {}).get('name') or '').strip(), [])
            for circuit in _circuits(net, inside):
                if circuit['supplied']:
                    names.extend(s['name'] or s['kind'] for s in circuit['sources'])
    return {name: ', '.join(dict.fromkeys(vals)) or None for name, vals in found.items()}


def recent_supply(days=7) -> List[dict]:
    """AI 컨텍스트의 '공급 자원' 한 줄씩 — 구획마다 최근 ``days`` 일의 닫힌 날 합(추정 물량).

    저장된 일 합계만 읽는다. **Influx 는 모든 구획을 한 번의 쿼리로 읽는다**(구획마다 읽으면 컨텍스트를 만들 때마다
    구획 수만큼 쿼리가 나간다). 시간대는 저장된 날이 있는 구획만 푼다. 저장된 날이 하나도 없는 구획은 싣지 않는다 —
    0 으로 적으면 '안 줬다' 와 '아직 저장 전' 이 섞인다.
    """
    from aot.databases.models import GeoPlot
    from aot.utils import influx, water_store
    from aot.utils.device_tz import resolve_location_tz
    from aot.utils.timekit import as_tz, to_tz

    now = datetime.now(timezone.utc).timestamp()
    try:
        points = influx.read_layer_points(result.M_DAY, None, {}, now - (days + 2) * 86400, now)
    except Exception:                                       # noqa: BLE001
        logger.debug('물 결과 일 합계를 읽지 못했다', exc_info=True)
        return []
    by_plot: Dict[str, Dict[int, dict]] = {}
    for ts, value, tags in points:
        try:
            channel = int(tags.get('channel'))
        except (TypeError, ValueError):
            continue
        by_plot.setdefault(tags.get('device_id'), {}).setdefault(round(ts), {})[channel] = value
    if not by_plot:
        return []
    out = []
    for plot in GeoPlot.query.filter(GeoPlot.unique_id.in_(list(by_plot)), GeoPlot.ended_on.is_(None)).all():
        tz = as_tz(resolve_location_tz(plot.unique_id))
        first = to_tz(datetime.fromtimestamp(now, timezone.utc), tz).date() - timedelta(days=days)
        floor = water_store.day_bounds(first, tz)[0]
        marks = {ts: vals for ts, vals in by_plot[plot.unique_id].items() if ts >= floor}
        if not marks:
            continue
        sums: Dict[str, float] = {}
        last = None
        for ts, vals in sorted(marks.items()):
            for i, key in enumerate(result.DAY_FIELDS[:3]):
                if vals.get(i) is not None:
                    sums[key] = sums.get(key, 0.0) + vals[i]
            if (vals.get(0) or 0) > 0:
                last = to_tz(datetime.fromtimestamp(ts, timezone.utc), tz).date().isoformat()
        out.append({'type': 'moisture', 'source': plot.name or plot.unique_id, 'plot_id': plot.unique_id,
                    'value': round(sums.get('litres', 0.0), 1), 'unit': 'L',
                    'mm': round(sums['mm'], 2) if 'mm' in sums else None,
                    'window_days': days, 'basis': 'estimated', 'last_run': last})
    return out
