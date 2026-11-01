# coding=utf-8
"""
geo/irrigation_topology.py — 관수 배관망을 물길로 풀어 노즐의 임자를 정한다.

레이어와 밸브가 **둘 다** Output 을 가질 수 있다. 지금까지는 그 둘이 같은
노즐을 각자 차지했다: ``nozzles_by_actuator`` 가 레이어 액추에이터에 그
레이어 노즐 전체를 붙이고, 밸브 액추에이터에도 (붙은 배관에 노즐이 없으면)
레이어 노즐 전체를 붙였다. 물리적으로 같은 물인데 통합환경제어에는 fogger
액추에이터가 둘로 등록됐고, 사용자에게는 "어느 쪽이 진짜 여는 놈인가"가
보이지 않았다.

정본 규칙은 하나다.

  **레이어 Output = 회로 공급**(펌프·주밸브). 어떤 밸브도 맡지 않은 노즐이
  그 몫이다.
  **밸브 Output = 그 밸브가 선 자리에서 하류로 뻗은 구간.** 노즐은 자기보다
  상류에 있는 밸브 중 **가장 가까운** 하나에만 속한다.

가장 가까운 상류 밸브가 임자라는 한 줄이 중첩을 그냥 만들어 낸다. 주배관
초입의 메인밸브와 지관의 구역밸브가 같이 있으면, 그 지관의 노즐은 구역밸브
몫이고 나머지가 메인밸브 몫이다. 단수 제한 없이 몇 겹이든 쌓인다.

물길을 세우는 기하 규칙(마디·스냅·공급점)은 지도와 함께 쓰려고
``aot.functions.utils.water_net.graph`` 로 옮겼다. 여기 남은 것은 임자 규칙뿐이다.
"""

from __future__ import annotations

from aot.functions.utils.water_net.adapters import (facility_emitter,
                                                    facility_layer_network)


def resolve_nozzle_owners(fittings):
    """노즐을 임자별로 가른다.

    Returns:
        (by_valve, by_layer) — 둘 다 {fitting_id: [device, ...]}.
        ``by_valve`` 는 밸브 id, ``by_layer`` 는 레이어 id 로 묶인다.
        레이어 몫은 "어떤 밸브도 맡지 않은 노즐"이다.
    """
    by_valve, by_layer = {}, {}
    if not fittings:
        return by_valve, by_layer

    layers = [f for f in fittings if f.get('kind') == 'irrigation_layer']
    for layer in layers:
        lid = layer.get('id')
        pipes = [f for f in fittings
                 if f.get('kind') == 'irrigation_pipe' and f.get('layer_id') == lid]
        valves = [f for f in fittings
                  if f.get('kind') == 'irrigation_valve' and f.get('layer_id') == lid]
        devices = [f for f in fittings
                   if f.get('kind') == 'irrigation_device' and f.get('layer_id') == lid]
        if not devices:
            continue
        if not valves or not pipes:
            # 밸브가 없으면 회로 전체가 레이어 몫이다. 배관이 없으면 물길을
            # 세울 수 없으니 같은 결론으로 떨어진다 — 밸브가 무엇을 맡는지
            # 알 수 없는 상태에서 노즐을 임의로 나눠 주지 않는다.
            by_layer.setdefault(lid, []).extend(devices)
            continue

        net = facility_layer_network(pipes, valves)
        for dev in devices:
            owner = net.owner_of(facility_emitter(dev))
            if owner is None:
                by_layer.setdefault(lid, []).append(dev)
            else:
                by_valve.setdefault(owner.id, []).append(dev)

    return by_valve, by_layer
