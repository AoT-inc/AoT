# coding=utf-8
"""water_net.checks — 회로 점검 항목. 값만 내고 데이터를 고치지 않는다.

폴리곤과 배관이 어긋나도 판정은 담당 폴리곤이 이긴다(``mapview._open_field_flow``).
여기서는 어긋났다는 사실만 알린다.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

from . import parts as part_table
from .graph import Network

CODES = (
    'network-disconnected', 'no-source', 'area-pipe-mismatch', 'emitter-no-flow',
    'part-unattached', 'part-device-ambiguous', 'network-loop',
)


class Cover(NamedTuple):
    """Output 하나의 담당 폴리곤과 그 안의 노즐. 포함 판정은 글루가 한다."""
    output_id: object
    name: Optional[str]
    emitter_ids: Sequence


def _lnglat(net, point):
    frame = net.frame
    return frame.to_lnglat(point) if frame is not None and point is not None else None


def _component_at(net, comp):
    pipes = net.component_pipes(comp)
    if pipes:
        return _lnglat(net, net.lines[pipes[0]][0])
    return None


def _component_row(net, code, comp):
    return {'code': code, 'network': comp, 'pipes': len(net.component_pipes(comp)),
            'emitters': len(net.component_emitters(comp)), 'at': _component_at(net, comp)}


def _disconnected(net) -> List[dict]:
    """본 회로에서 떨어진 덩어리 + 어느 배관에도 못 얹은 노즐.

    공급이 있는 덩어리가 본 회로다. 공급이 하나도 없으면(부품을 안 놓은 지도) 노즐이
    가장 많은 덩어리를 본 회로로 친다.
    """
    comps = range(len(net.components))
    main = set(net.fed)
    if not main and net.components:
        main = {max(comps, key=lambda c: (len(net.component_emitters(c)),
                                          len(net.component_pipes(c))))}
    out = [_component_row(net, 'network-disconnected', c) for c in comps if c not in main]
    if net.loose_emitters:
        out.append({'code': 'network-disconnected', 'network': None, 'pipes': 0,
                    'emitters': len(net.loose_emitters),
                    'at': _lnglat(net, net.loose_emitters[0].point)})
    return out


def _no_source(net) -> List[dict]:
    return [_component_row(net, 'no-source', c)
            for c in range(len(net.components)) if c not in net.fed]


def _area_mismatch(net, covers: Iterable[Cover]) -> List[dict]:
    """담당 폴리곤과 배관이 어긋난 자리.

    ``split`` 은 한 Output 의 폴리곤 안 노즐이 끊긴 회로 둘 이상에 걸친 것이고,
    ``valve`` 는 그 Output 이 물린 밸브의 하류가 아닌 노즐이 폴리곤 안에 있는 것이다.
    """
    valves: Dict[object, object] = {}
    for part in net.parts:
        rule = part_table.get(part.kind)
        link = net.part_devices.get(part.id) or {}
        device = link.get('device') or {}
        if rule is not None and rule.group == 'valve' and device.get('device_id'):
            valves[device['device_id']] = part

    out = []
    for cover in covers:
        comps = {net.component_id(eid) for eid in cover.emitter_ids}
        comps.discard(None)
        if len(comps) > 1:
            out.append({'code': 'area-pipe-mismatch', 'reason': 'split',
                        'output': cover.output_id, 'name': cover.name,
                        'networks': len(comps), 'emitters': len(cover.emitter_ids)})
        part = valves.get(cover.output_id)
        if part is None or net.component_id(part.id) not in net.fed:
            continue
        below = {em.id for em in net.downstream_emitters(part.id)}
        outside = [eid for eid in cover.emitter_ids if eid not in below]
        if outside:
            out.append({'code': 'area-pipe-mismatch', 'reason': 'valve',
                        'output': cover.output_id, 'name': cover.name, 'part': part.id,
                        'emitters': len(outside)})
    return out


def _no_flow(net, defaulted) -> List[dict]:
    """유량이 없는 노즐. 구역 기본값으로 채워 쓰는 것은 ``zone_default`` 로 따로 센다."""
    missing = [em for em in net.emitters if not em.flow_lph]
    if not missing:
        return []
    return [{'code': 'emitter-no-flow', 'emitters': len(missing),
             'zone_default': sum(1 for em in missing if em.id in defaulted),
             'at': _lnglat(net, missing[0].point)}]


def _part_row(net, code, part):
    return {'code': code, 'part': part.id, 'kind': part.kind, 'name': part.name,
            'at': _lnglat(net, part.point)}


def find_issues(net: Network, covers: Iterable[Cover] = (), defaulted=()) -> List[dict]:
    """점검 항목 목록. `CODES` 순서로 나온다."""
    if net is None:
        return []
    defaulted = set(defaulted)
    out = _disconnected(net) + _no_source(net) + _area_mismatch(net, covers)
    out += _no_flow(net, defaulted)
    out += [_part_row(net, 'part-unattached', part) for part in net.loose_parts]
    for part in net.parts:
        link = net.part_devices.get(part.id)
        if link and link.get('candidates'):
            row = _part_row(net, 'part-device-ambiguous', part)
            row['candidates'] = [m.get('name') or m.get('device_id')
                                 for m in link['candidates']]
            out.append(row)
    for comp in range(len(net.components)):
        loops = net.component_loops(comp)
        if loops > 0:
            row = _component_row(net, 'network-loop', comp)
            row['loops'] = loops
            out.append(row)
    return out


def count_by_code(issues: Iterable[dict]) -> Dict[str, int]:
    """코드별 건수. 노즐 묶음 항목도 한 건이다."""
    counts: Dict[str, int] = {}
    for row in issues:
        counts[row['code']] = counts.get(row['code'], 0) + 1
    return counts


def summarize(net: Network) -> dict:
    """연결 비율. 지관은 다른 배관과 마디를 나눈 것, 노즐은 배관에 얹힌 것을 센다."""
    branches = [p for p in net.pipes if p.sub_type != 'main']
    joined = net.joined_pipes()
    n_joined = sum(1 for p in branches if p.id in joined)
    n_attached = len(net.emitters) - len(net.loose_emitters)

    def _pct(part, whole):
        return round(100.0 * part / whole, 1) if whole else None

    return {
        'pipes': len(net.pipes), 'branches': len(branches), 'branches_joined': n_joined,
        'branch_joined_pct': _pct(n_joined, len(branches)),
        'emitters': len(net.emitters), 'emitters_attached': n_attached,
        'emitter_attached_pct': _pct(n_attached, len(net.emitters)),
        'parts': len(net.parts), 'parts_attached': len(net.parts) - len(net.loose_parts),
        'networks': len(net.components), 'gap_joins': len(net.gap_joins),
    }
