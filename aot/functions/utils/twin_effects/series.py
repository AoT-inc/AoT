# coding=utf-8
"""장치별 상태 계열 → 효과 채널 계열 (동기화 입력, 설계서 §5.1).

각 장치의 계열은 `(times, values)`(값은 이미 0~100 % 개도·가동률, 노지 관수는 mm). 채널의 장치들 계열을 시각 합집합 위에서
**마지막 값 유지**로 맞춘 뒤 `aggregate.merge` 로 합친다. 첫 표본이 오기 전의 장치는 0 으로 본다.
연결 안 된(계열이 없는) 장치는 `unwired` 에 남는다 — 가동률 0 으로 조용히 합치지 않고 호출자가 표시한다.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence, Tuple

from . import catalog as C
from .aggregate import Device, merge

Series = Tuple[Sequence[float], Sequence[float]]


@dataclass
class ChannelSeries:
    channels: Dict[str, Series] = field(default_factory=dict)
    unmodeled: List[Dict[str, object]] = field(default_factory=list)
    assumed: List[str] = field(default_factory=list)
    unwired: List[str] = field(default_factory=list)
    members: Dict[str, List[str]] = field(default_factory=dict)


def _hold(times: Sequence[float], values: Sequence[float], t: float) -> float:
    i = bisect.bisect_right(times, t) - 1
    return float(values[i]) if i >= 0 else 0.0


def channelize(devices: Sequence[Device], series: Mapping[str, Series], domain: str = C.FACILITY) -> ChannelSeries:
    out = ChannelSeries()
    base = merge(devices, {}, domain)                    # 분류만 쓴다(미반영·가정·소속)
    out.unmodeled, out.assumed, out.members = base.unmodeled, list(base.assumed), base.members
    out.unwired = [d.actuator_id for d in devices
                   if C.row_for(d.kind, domain).channel and not (series.get(d.actuator_id) and len(series[d.actuator_id][0]))]
    by_id = {d.actuator_id: d for d in devices}
    for ch, ids in base.members.items():
        wired = [a for a in ids if series.get(a) and len(series[a][0])]
        if not wired:
            continue
        times = sorted({t for a in wired for t in series[a][0]})
        devs = [by_id[a] for a in ids]
        vals = []
        for t in times:
            pct = {a: _hold(series[a][0], series[a][1], t) for a in wired}
            vals.append(merge(devs, pct, domain).values[ch])
        out.channels[ch] = (times, vals)
    return out
