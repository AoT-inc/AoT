# coding=utf-8
"""water_net.terrain — 지형(DEM)에서 마디 표고와 구간별 경사 길이를 읽는다 (계획서 15·16절 T2).

``sampler`` 는 ``aot.utils.dem_sampler.Sampler`` 와 같은 모양이면 된다(이 모듈은 그것을 import 하지 않는다):
``elevation(lng, lat, fetch)`` · ``profile(points_lnglat, step_m, fetch)`` · ``suggest_step_m(lat)`` ·
``version`` · ``cell_m(lat)``. ``fetch=False`` 가 기본이라 타일을 받지 않고 캐시만 읽는다 — 요청 스레드에서
부르는 쪽은 그대로 두고, 타일을 데우는 일은 백그라운드(T3)의 몫이다.

**못 읽은 곳은 None 이다.** nodata·해양의 큰 음수는 ``[Z_MIN, Z_MAX]`` 밖이라 None 으로 본다. 이웃 값으로 메우지 않는다.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

from .graph import _point_at

# 유효 고도 범위 [m]. 사해 -430 보다 낮거나 히말라야 위인 값은 nodata 로 본다.
Z_MIN = -430.0
Z_MAX = 9000.0


def valid_z(value) -> Optional[float]:
    try:
        z = float(value)
    except (TypeError, ValueError):
        return None
    if z != z or z < Z_MIN or z > Z_MAX:
        return None
    return z


def _sub_line(pts, s_lo: float, s_hi: float) -> list:
    """점렬을 호길이 [s_lo, s_hi] 로 자른 점렬(수평 호길이 기준, y 는 보간)."""
    out = [_point_at(pts, s_lo)]
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2])
        acc += seg
        if s_lo + 1e-9 < acc < s_hi - 1e-9:
            out.append(pts[i + 1])
    out.append(_point_at(pts, s_hi))
    return out


class Terrain:
    """회로 하나의 지형 읽기 — 마디 표고와 구간(배관 호길이 범위) 경사 길이."""

    def __init__(self, net, frame, sampler, fetch: bool = False):
        self.net, self.frame, self.sampler, self.fetch = net, frame, sampler, bool(fetch)
        self._node_z: Dict[object, Optional[float]] = {}

    @property
    def meta(self) -> dict:
        lat = getattr(self.frame, 'lat0', 0.0)
        try:
            cell = round(float(self.sampler.cell_m(lat)), 2)
        except Exception:                                    # noqa: BLE001
            cell = None
        return {'version': getattr(self.sampler, 'version', None), 'cell_m': cell}

    def _point_z(self, p) -> Optional[float]:
        lng, lat = self.frame.to_lnglat(p)
        return valid_z(self.sampler.elevation(lng, lat, fetch=self.fetch))

    def _position(self, node):
        """마디의 로컬 좌표. 노즐(가상 마디)은 노즐 위치, 없으면 None."""
        if isinstance(node, tuple) and len(node) == 2 and node[0] == 'nozzle':
            em = self.net._emitter_ids.get(node[1])
            return em.point if em is not None else None
        return self.net.node_pos.get(node)

    def node_elevation(self, node) -> Optional[float]:
        if node not in self._node_z:
            p = self._position(node)
            self._node_z[node] = self._point_z(p) if p is not None else None
        return self._node_z[node]

    def slant(self, pipe_id, s_lo: float, s_hi: float) -> Optional[Tuple[float, float]]:
        """배관 호길이 [s_lo, s_hi] 구간 → (수평 길이, 경사 길이). 구간 안에 못 읽은 표본이 있으면 None.

        표본 간격은 지형 해상도에서 정한다(표본기가 구간당 200점을 지킨다). 수평 거리는 표본기의 구면
        거리를 로컬 수평 길이로 맞춰 쓴다 — 지형이 평평하면 경사 길이가 수평 길이와 정확히 같다.
        """
        pts = self.net.lines.get(pipe_id)
        horizontal = s_hi - s_lo
        if not pts or horizontal <= 1e-9:
            return None
        sub = _sub_line(pts, s_lo, s_hi)
        ll = [self.frame.to_lnglat(p) for p in sub]
        step = self.sampler.suggest_step_m(ll[0][1])
        prof = self.sampler.profile(ll, step, fetch=self.fetch)
        if len(prof) < 2:
            return None
        zs = [valid_z(z) for _d, z in prof]
        if any(z is None for z in zs):
            return None
        span = prof[-1][0]
        k = horizontal / span if span > 0 else 1.0
        total = 0.0
        for i in range(len(prof) - 1):
            ds = (prof[i + 1][0] - prof[i][0]) * k
            total += math.hypot(ds, zs[i + 1] - zs[i])
        return horizontal, total


def elevation_for(net, frame, sampler, fetch: bool = False) -> Callable[[object], Optional[float]]:
    """마디 → 고도 [m] 또는 None. 유효 범위 밖(nodata·해양)은 None."""
    return Terrain(net, frame, sampler, fetch).node_elevation


def effective_heights(root, links, raw: Callable[[object], Optional[float]]) -> Tuple[Dict[object, float], int, int]:
    """마디별 정수두 높이. → (높이, 표고를 아는 마디 수, 전체 마디 수).

    구간의 한쪽 끝이라도 표고를 모르면 그 구간은 평지(Δz=0)다. 높이는 뿌리에서 구간마다 Δz 를 누적한다 —
    그래서 일부 마디를 몰라도 아는 마디끼리의 낙차가 엉뚱하게 이웃 값으로 메워지지 않는다.
    """
    cache: Dict[object, Optional[float]] = {}

    def _raw(n):
        if n not in cache:
            cache[n] = raw(n)
        return cache[n]

    height: Dict[object, float] = {root: 0.0}
    for link in links:
        a, b = _raw(link.parent), _raw(link.node)
        dz = (b - a) if (a is not None and b is not None) else 0.0
        height[link.node] = height[link.parent] + dz
    nodes: List[object] = list(height)
    known = sum(1 for n in nodes if _raw(n) is not None)
    return height, known, len(nodes)
