# coding=utf-8
"""water_net.graph — 배관을 물길 그래프로 푸는 순수 모듈. 지도와 시설이 같이 쓴다.

배관망 데이터에는 그래프가 명시돼 있지 않다 — 시설의 ``irrigation_connection`` 은
표시용 구슬이고, 지도의 ``connected_main_id`` 는 지관의 66% 가 비어 있다. 그래서
기하로 다시 세운다: 배관끼리 닿는 자리가 마디다. 끝점이 다른 배관 위에 얹힌
자리(T·엘보)와 두 배관이 가로지르는 자리(십자) 둘 다 — 디자이너가 화면에 티를
꽂아 주는 자리와 같은 규칙이다.

좌표는 어댑터가 미터 ``(x, y, z)`` 로 넘긴다(y 가 높이). 판정은 xz 평면에서 한다.

이 모듈은 "어디서 어디로 물이 가는가" 만 답한다. 노즐의 임자(어느 Output 몫인가)는
시설은 ``irrigation_topology.resolve_nozzle_owners``, 지도는 담당 폴리곤 ∩ 구획
(``mapview._open_field_flow``)이 정한다. 유량·물량은 여기서 계산하지 않는다.

시설 결과를 고정하기 위한 규칙: ``gap_m=0`` 이면 마디는 격자 이름(``_key``)으로만
맞물린다. 틈 잇기(``gap_m``)와 그에 딸린 마디 찾기는 지도 전용이다.
"""

from __future__ import annotations

import math
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import parts as part_table

# 마디를 같은 점으로 볼 거리 [m]. 디자이너의 라이저 스냅이 8cm 이므로
# 그보다 넉넉히 잡는다(_trimBranchAtPoint 의 교차 판정은 1cm).
SNAP_M = 0.12
# 노즐을 배관에 얹을 때 허용하는 수평 거리 [m]. 노즐은 배관에 매달리므로
# 원래 배관 위에 있지만, 손으로 옮긴 것까지 받아 준다.
DEVICE_SNAP_M = 1.0

# 공급 부품의 뿌리 순서(작을수록 상류). 수원 → 탱크 → 펌프.
_SUPPLY_TIER = {'tank': 1, 'pump': 2}

Point = Tuple[float, float, float]


class Pipe(NamedTuple):
    id: object
    line: Sequence[Point]         # 점렬(이어 붙인 뒤)
    sub_type: str = ''            # 'main' | 'branch'
    vertical: bool = False        # 라이저
    name: Optional[str] = None


class Part(NamedTuple):
    id: object
    kind: str                     # parts.py 의 부품 종류
    point: Optional[Point] = None
    pipe_id: object = None        # 얹힌 배관을 데이터가 아는 경우(시설)
    attach_t: Optional[float] = None
    name: Optional[str] = None
    meta: object = None           # 원본(시설 fitting · 지도 feature 속성)


class Emitter(NamedTuple):
    id: object
    point: Optional[Point] = None
    pipe_id: object = None
    kind: str = 'sprinkler'       # 'sprinkler' | 'drip'
    flow_lph: Optional[float] = None
    count: int = 1                # 점적 줄이면 점적기 수
    meta: object = None


class Edge(NamedTuple):
    a: tuple
    b: tuple
    pipe_id: object
    s_a: float
    s_b: float
    bridge: bool = False          # 틈 잇기 구간(배관이 아니다)


def dist_xz(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def line_length(pts) -> float:
    return sum(dist_xz(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _key(p):
    """스냅 격자 위의 마디 이름."""
    return (round(p[0] / SNAP_M), round(p[1] / SNAP_M), round(p[2] / SNAP_M))


def project(pts, p):
    """점 p 를 점렬 위에 내린다 → (호길이, 내린 점, 거리). 점렬이 비면 None."""
    if len(pts) < 2:
        return None
    best = None
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dx, dz = b[0] - a[0], b[2] - a[2]
        seg_len = math.hypot(dx, dz)
        if seg_len < 1e-9:
            continue
        t = ((p[0] - a[0]) * dx + (p[2] - a[2]) * dz) / (seg_len * seg_len)
        t = max(0.0, min(1.0, t))
        proj = (a[0] + t * dx, a[1] + t * (b[1] - a[1]), a[2] + t * dz)
        d = dist_xz(proj, p)
        if best is None or d < best[2]:
            best = (acc + t * seg_len, proj, d)
        acc += seg_len
    if best is None:
        return None
    return best[0], best[1], best[2]


def _seg_cross_xz(a1, a2, b1, b2):
    """xz 평면에서 두 선분이 실제로 만나는 점. 안 만나면 None.

    끝점끼리만 맞닿은 경우도 만난 것으로 본다 — 디자이너의
    ``_segIntersectXZ`` 는 그 경우를 폴리라인 꼭짓점으로 보고 걸러 내지만,
    여기서는 물길을 세우는 것이 목적이라 맞닿았으면 마디다.
    """
    x1, z1, x2, z2 = a1[0], a1[2], a2[0], a2[2]
    x3, z3, x4, z4 = b1[0], b1[2], b2[0], b2[2]
    denom = (x1 - x2) * (z3 - z4) - (z1 - z2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None                     # 평행 — 겹침은 끝점 규칙이 잡는다
    t = ((x1 - x3) * (z3 - z4) - (z1 - z3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (z1 - z3) - (z1 - z2) * (x1 - x3)) / denom
    eps = 1e-6
    if not (-eps <= t <= 1 + eps and -eps <= u <= 1 + eps):
        return None
    return (x1 + t * (x2 - x1),
            a1[1] + t * (a2[1] - a1[1]),
            z1 + t * (z2 - z1))


def _crossings(pts_a, pts_b):
    """두 점렬이 xz 평면에서 만나는 점들."""
    out = []
    for i in range(len(pts_a) - 1):
        for j in range(len(pts_b) - 1):
            hit = _seg_cross_xz(pts_a[i], pts_a[i + 1], pts_b[j], pts_b[j + 1])
            if hit is not None:
                out.append(hit)
    return out


def _point_at(pts, s):
    """점렬에서 호길이 s 인 지점."""
    if not pts:
        return None
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg_len = math.hypot(b[0] - a[0], b[2] - a[2])
        if seg_len < 1e-9:
            continue
        if acc + seg_len >= s:
            t = (s - acc) / seg_len
            return (a[0] + t * (b[0] - a[0]),
                    a[1] + t * (b[1] - a[1]),
                    a[2] + t * (b[2] - a[2]))
        acc += seg_len
    return pts[-1]


class Network:
    """배관망 하나. 마디 그래프 + 공급점에서 내린 부모 관계.

    Args:
        pipes, parts, emitters: `Pipe`·`Part`·`Emitter`.
        gap_m: 배관 끝이 이만큼 떨어져도 가장 가까운 배관에 잇는다(0 이면 잇지 않음).
        part_snap_m, emitter_snap_m: 부품·노즐을 배관에 얹는 상한. None 이면 제한 없이
            가장 가까운 배관에 얹는다(시설 — 배관이 바로 곁에 있다는 전제다).
        layer_feed: 부품이 없어도 라이저·주배관 시작점을 공급으로 친다(시설 레이어).
    """

    def __init__(self, pipes=(), parts=(), emitters=(), gap_m=0.0,
                 part_snap_m=None, emitter_snap_m=None, layer_feed=False):
        self.pipes = [p for p in pipes if len(p.line) >= 2]
        self.lines = {p.id: p.line for p in self.pipes}
        self.parts = list(parts)
        self.emitters = list(emitters)
        self.gap_m = gap_m
        self.part_snap_m = part_snap_m
        self.emitter_snap_m = emitter_snap_m
        self.layer_feed = layer_feed
        self.frame = None                     # 지도: adapters.LocalFrame

        self.edges: List[Edge] = []
        self.adj: Dict[tuple, list] = {}      # node → [(other, edge_index)]
        self.part_at: Dict[tuple, list] = {}  # node → [Part, ...]
        self.parent: Dict[tuple, Optional[tuple]] = {}   # node → node (공급 쪽)
        self.parent_edge: Dict[tuple, int] = {}
        self.depth: Dict[tuple, int] = {}
        self.part_devices: Dict[object, dict] = {}       # adapters.link_part_devices

        self.components: List[list] = []      # [[node, ...], ...]
        self.component_of: Dict[tuple, int] = {}
        self.fed: set = set()                 # 진짜 공급에서 닿은 덩어리 번호
        self.gap_joins: List[tuple] = []      # (배관, 배관, 틈 m)
        self.loose_parts: List[Part] = []     # 배관에 못 얹은 부품
        self.loose_emitters: List[Emitter] = []

        self._by_pipe: Dict[object, list] = {}   # pipe_id → 그 배관의 Edge 번호
        self._cut_nodes: Dict[object, list] = {}  # pipe_id → [(호길이, node)]
        self._joins: List[tuple] = []             # (pipe, s, pipe, s)
        self._part_node: Dict[object, tuple] = {}
        self._emitter_spot: Dict[object, tuple] = {}  # id → (edge 번호, 상류 node)
        self._children: Optional[dict] = None
        self._emitters_at: Dict[tuple, list] = {}
        self._part_ids = {p.id: p for p in self.parts}
        self._emitter_ids = {e.id: e for e in self.emitters}
        self._pipe_ids = {p.id: p for p in self.pipes}
        self._build()

    # ── 마디 세우기 ────────────────────────────────────────────────────────
    def _build(self):
        # 배관마다 잘라야 할 호길이들을 모은다: 자기 양끝, 다른 배관의 끝점이
        # 얹힌 자리, 그리고 밸브가 선 자리.
        cuts = {}
        for p in self.pipes:
            cuts[p.id] = {0.0, line_length(self.lines[p.id])}

        for p in self.pipes:
            pid = p.id
            for q in self.pipes:
                qid = q.id
                if qid == pid:
                    continue
                qpts = self.lines[qid]
                # 다른 배관의 끝점이 이 배관 위에 얹힌 자리 (T·엘보)
                for end in (qpts[0], qpts[-1]):
                    hit = project(self.lines[pid], end)
                    if hit and hit[2] <= SNAP_M:
                        cuts[pid].add(hit[0])

        # 두 배관이 가로지르는 자리(십자)도 마디다. 화면에서는 디자이너가
        # 거기에 티(mbT/bT/mT)를 꽂아 주므로, 물길에서만 안 이어져 있으면
        # 눈에 보이는 배관망과 계산이 어긋난다 — 가로지르기만 한 주배관이
        # 섬으로 남아 그 위의 구역밸브가 아무것도 못 맡는 식으로.
        for i in range(len(self.pipes)):
            for j in range(i + 1, len(self.pipes)):
                pid = self.pipes[i].id
                qid = self.pipes[j].id
                for hit in _crossings(self.lines[pid], self.lines[qid]):
                    ss = {}
                    for target in (pid, qid):
                        proj = project(self.lines[target], hit)
                        if proj and proj[2] <= SNAP_M:
                            cuts[target].add(proj[0])
                            ss[target] = proj[0]
                    if self.gap_m and len(ss) == 2:
                        self._joins.append((pid, ss[pid], qid, ss[qid], 0.0))

        if self.gap_m:
            self._collect_gaps(cuts)

        spots = []
        for part in self.parts:
            spot = self._part_spot(part)
            if spot is None:
                self.loose_parts.append(part)
                continue
            pid, s = spot
            cuts.setdefault(pid, set()).add(s)
            spots.append((part, pid, s))

        for p in self.pipes:
            pid = p.id
            pts = self.lines[pid]
            merged = []
            for s in sorted(cuts[pid]):
                if not merged or s - merged[-1] > SNAP_M:
                    merged.append(s)
            nodes = self._cut_nodes.setdefault(pid, [])
            for s in merged:
                node = _key(_point_at(pts, s))
                nodes.append((s, node))
            for i in range(len(merged) - 1):
                a_pt, b_pt = _point_at(pts, merged[i]), _point_at(pts, merged[i + 1])
                if a_pt is None or b_pt is None:
                    continue
                na, nb = _key(a_pt), _key(b_pt)
                if na == nb:
                    continue
                self._add_edge(Edge(na, nb, pid, merged[i], merged[i + 1]))

        self._weld_joins()

        for part, pid, s in spots:
            node = self._node_on(pid, s)
            self._part_node[part.id] = node
            self.part_at.setdefault(node, []).append(part)

        self._root_from_supply()

        for em in self.emitters:
            spot = self._emitter_upstream(em)
            if spot is None:
                self.loose_emitters.append(em)
                continue
            self._emitter_spot[em.id] = spot
            self._emitters_at.setdefault(spot[1], []).append(em)

    def _add_edge(self, edge):
        idx = len(self.edges)
        self.edges.append(edge)
        self.adj.setdefault(edge.a, []).append((edge.b, idx))
        self.adj.setdefault(edge.b, []).append((edge.a, idx))
        if not edge.bridge:
            self._by_pipe.setdefault(edge.pipe_id, []).append(idx)

    def _collect_gaps(self, cuts):
        """배관 끝마다 가장 가까운 다른 배관 하나를 찾아 ``gap_m`` 안이면 잇는다.

        가까운 배관 **하나만** 잇는다 — 나란한 지관들이 틈 잇기로 서로 물리면
        없는 회로가 생긴다.
        """
        for q in self.pipes:
            qpts = self.lines[q.id]
            for end_s, end in ((0.0, qpts[0]), (line_length(qpts), qpts[-1])):
                best = None
                for p in self.pipes:
                    if p.id == q.id:
                        continue
                    hit = project(self.lines[p.id], end)
                    if hit and (best is None or hit[2] < best[2]):
                        best = (p.id, hit[0], hit[2])
                if best is None or best[2] > self.gap_m:
                    continue
                cuts[best[0]].add(best[1])
                self._joins.append((q.id, end_s, best[0], best[1], best[2]))

    def _weld_joins(self):
        """닿은 자리의 두 마디가 격자에서 갈렸으면 잇고, 틈은 짧은 것부터 잇는다.

        틈 잇기는 **서로 다른 덩어리끼리만** 한다. 이미 이어진 두 배관을 틈으로 또
        이으면 없는 고리가 생긴다 — 나주는 틈 3m 에서 고리가 0 → 10 이 됐다.
        """
        root: Dict[tuple, tuple] = {}

        def _find(node):
            while root.setdefault(node, node) != node:
                root[node] = root[root[node]]
                node = root[node]
            return node

        for edge in self.edges:
            root[_find(edge.a)] = _find(edge.b)

        done = set()
        for pid, s, qid, t, gap in sorted(self._joins, key=lambda j: j[4]):
            na, nb = self._node_on(pid, s), self._node_on(qid, t)
            if na == nb or (na, nb) in done or (nb, na) in done:
                continue
            if gap > SNAP_M and _find(na) == _find(nb):
                continue
            done.add((na, nb))
            root[_find(na)] = _find(nb)
            self._add_edge(Edge(na, nb, None, 0.0, 0.0, bridge=True))
            if gap > SNAP_M:
                self.gap_joins.append((pid, qid, round(gap, 2)))

    def _node_on(self, pid, s):
        """배관 pid 의 호길이 s 자리 마디."""
        if not self.gap_m:
            return _key(_point_at(self.lines[pid], s))
        # 잘린 자리는 스냅 거리 안에서 하나로 합쳐졌으니 가장 가까운 자리를 쓴다.
        return min(self._cut_nodes[pid], key=lambda c: abs(c[0] - s))[1]

    def _part_spot(self, part):
        """부품이 선 자리 → (pipe_id, 호길이). 배관을 못 찾으면 None.

        pipe_id 가 있으면 그 배관 위에, 없으면 좌표에서 가장 가까운 배관에
        얹는다. 좌표조차 없으면 attach_t 로 그 배관의 비율 위치를 쓴다.
        """
        pid, p = part.pipe_id, part.point
        if pid and pid in self.lines:
            pts = self.lines[pid]
            if p is not None:
                hit = project(pts, p)
                if hit:
                    return pid, hit[0]
            if part.attach_t is not None:
                return pid, max(0.0, min(1.0, part.attach_t)) * line_length(pts)
            return pid, 0.0
        if p is None:
            return None
        best = self._nearest_pipe(p)
        if best is None:
            return None
        if self.part_snap_m is not None and best[2] > self.part_snap_m:
            return None
        return best[0], best[1]

    def _nearest_pipe(self, p):
        best = None
        for q in self.pipes:
            hit = project(self.lines[q.id], p)
            if hit and (best is None or hit[2] < best[2]):
                best = (q.id, hit[0], hit[2])
        return best

    # ── 공급점 ─────────────────────────────────────────────────────────────
    def _layer_root(self):
        """시설 레이어의 공급 마디.

        수직관(라이저)은 바닥에서 레이어 높이로 올라오는 급수 인입이므로
        그 아래 끝이 공급점이다. 라이저가 없으면 주배관의 시작점, 그것도
        없으면 아무 배관의 시작점을 쓴다 — 어느 쪽을 잡아도 밸브 상하류
        관계는 뒤집히지 않는다(트리 위에서 방향만 정하는 값이다).
        """
        root_pt = None
        risers = [p for p in self.pipes if p.vertical]
        if risers:
            cands = []
            for r in risers:
                pts = self.lines[r.id]
                cands.extend([pts[0], pts[-1]])
            root_pt = min(cands, key=lambda pt: pt[1])
        else:
            mains = [p for p in self.pipes if p.sub_type == 'main']
            pool = mains or self.pipes
            if pool:
                root_pt = self.lines[pool[0].id][0]
        if root_pt is None:
            return None
        root = _key(root_pt)
        if root not in self.adj:
            if not self.adj:
                return None
            root = next(iter(self.adj))
        return root

    def _feed_ranks(self):
        """공급 부품이 선 마디 → 뿌리 순서(작을수록 상류)."""
        ranks = {}
        for node, here in self.part_at.items():
            tiers = [supply_tier(part.kind) for part in here]
            tiers = [t for t in tiers if t is not None]
            if tiers:
                ranks[node] = min(tiers)
        return ranks

    def _split_components(self):
        seen = set()
        for start in self.adj:
            if start in seen:
                continue
            comp, stack = [], [start]
            seen.add(start)
            while stack:
                node = stack.pop()
                comp.append(node)
                for other, _idx in self.adj.get(node, []):
                    if other not in seen:
                        seen.add(other)
                        stack.append(other)
            idx = len(self.components)
            self.components.append(comp)
            for node in comp:
                self.component_of[node] = idx

    def _root_from_supply(self):
        """덩어리마다 물이 들어오는 마디를 정하고 거기서 부모 관계를 내린다.

        공급에서 닿지 않는 덩어리 — 배관을 그렸는데 아직 본관에 물리지
        않은 상태다. 그냥 두면 그 위의 노즐은 부모가 없어 상류 밸브를 못
        찾고 전부 공급 몫으로 조용히 떨어진다. 덩어리마다 가장 낮은 점을
        임시 뿌리로 삼아 상하류만이라도 세운다 — 그 안의 밸브는 제대로
        동작하고, 진짜 공급과의 연결은 사용자가 배관을 이으면 잡힌다.
        ``fed`` 에 없는 덩어리의 방향은 임시이므로 공급 경로로 내세우지 않는다.
        """
        self._split_components()
        ranks = self._feed_ranks()
        layer_root = self._layer_root() if self.layer_feed else None
        for idx, comp in enumerate(self.components):
            here = [n for n in comp if n in ranks]
            if here:
                best = min(ranks[n] for n in here)
                self._spread([n for n in here if ranks[n] == best])
                self.fed.add(idx)
            elif layer_root is not None and self.component_of.get(layer_root) == idx:
                self._spread([layer_root])
                self.fed.add(idx)
            else:
                self._spread([min(comp, key=lambda n: (n[1], n[0], n[2]))])

    def _spread(self, starts):
        # 너비 우선으로 부모를 심는다. 고리(loop)가 있어도 먼저 닿은 쪽이
        # 상류가 되어 무한 순회하지 않는다.
        queue = list(starts)
        for start in starts:
            self.parent[start] = None
            self.depth[start] = 0
        head = 0
        while head < len(queue):
            node = queue[head]
            head += 1
            for other, idx in self.adj.get(node, []):
                if other in self.parent:
                    continue
                self.parent[other] = node
                self.parent_edge[other] = idx
                self.depth[other] = self.depth[node] + 1
                queue.append(other)

    # ── 얹기 ───────────────────────────────────────────────────────────────
    def _emitter_upstream(self, em):
        """노즐이 얹힌 구간과 그 상류 쪽 마디 → (edge 번호, node). 못 얹으면 None."""
        p = em.point
        if p is None:
            return None
        pid = em.pipe_id
        hit = project(self.lines[pid], p) if pid in self.lines else None
        if hit is None or hit[2] > DEVICE_SNAP_M:
            best = self._nearest_pipe(p)
            if best is None:
                return None
            if self.emitter_snap_m is not None and best[2] > self.emitter_snap_m:
                return None
            pid, s = best[0], best[1]
        else:
            s = hit[0]

        for idx in self._by_pipe.get(pid, ()):
            edge = self.edges[idx]
            if edge.s_a - SNAP_M <= s <= edge.s_b + SNAP_M:
                node = edge.a if self.depth[edge.a] <= self.depth[edge.b] else edge.b
                return idx, node
        return None

    # ── 물길 읽기 ──────────────────────────────────────────────────────────
    def owner_of(self, em):
        """노즐의 임자 부품(가장 가까운 상류 부품). 없으면 None(=레이어 몫)."""
        spot = self._emitter_upstream(em)
        if spot is None:
            return None
        node = spot[1]
        while node is not None:
            here = self.part_at.get(node)
            if here:
                return sorted(here, key=lambda part: str(part.id))[0]
            node = self.parent.get(node)
        return None

    def _start_of(self, ref):
        """대상 → (시작 마디, 그 대상이 얹힌 배관). 그래프 밖이면 None."""
        if ref in self._part_ids:
            node = self._part_node.get(ref)
            return None if node is None else (node, None)
        if ref in self._emitter_ids:
            spot = self._emitter_spot.get(ref)
            return None if spot is None else (spot[1], self.edges[spot[0]].pipe_id)
        idxs = self._by_pipe.get(ref)
        if idxs:
            nodes = [n for i in idxs for n in (self.edges[i].a, self.edges[i].b)]
            return min(nodes, key=lambda n: self.depth[n]), ref
        return None

    def upstream_path(self, ref) -> List[dict]:
        """대상의 상류 경로 — **수원 쪽부터** 차례로.

        각 칸은 ``{'type': 'part'|'pipe', 'id', 'kind', 'name'}``. 대상 자신은 빼되
        대상이 얹힌 배관은 넣는다. 같은 배관이 이어지면 한 칸이다. 공급이 없는
        덩어리에서는 임시 뿌리까지 올라가므로 부르는 쪽이 ``sources_of`` 를 함께 본다.
        """
        start = self._start_of(ref)
        if start is None:
            return []
        node, pid = start
        rows: list = []

        def _pipe(pipe_id):
            if not rows or rows[-1] != ('pipe', pipe_id):
                rows.append(('pipe', pipe_id))

        if pid is not None:
            _pipe(pid)
        while node is not None:
            for part in sorted(self.part_at.get(node, ()), key=lambda x: str(x.id)):
                if part.id != ref:
                    rows.append(('part', part.id))
            idx = self.parent_edge.get(node)
            if idx is None:
                break
            if not self.edges[idx].bridge:
                _pipe(self.edges[idx].pipe_id)
            node = self.parent.get(node)
        rows.reverse()
        return [self._step(kind, item) for kind, item in rows]

    def _step(self, kind, item):
        if kind == 'part':
            part = self._part_ids[item]
            return {'type': 'part', 'id': item, 'kind': part.kind, 'name': part.name}
        pipe = self._pipe_ids[item]
        return {'type': 'pipe', 'id': item, 'kind': pipe.sub_type, 'name': pipe.name}

    def _child_map(self):
        if self._children is None:
            self._children = {}
            for node, up in self.parent.items():
                if up is not None:
                    self._children.setdefault(up, []).append(node)
        return self._children

    def _below(self, nodes):
        """마디들과 그 아래 마디 전부."""
        children = self._child_map()
        out, stack = set(nodes), list(nodes)
        while stack:
            for child in children.get(stack.pop(), ()):
                if child not in out:
                    out.add(child)
                    stack.append(child)
        return out

    def downstream_emitters(self, ref) -> List[Emitter]:
        """부품·배관에서 하류로 가는 노즐 전부. 더 아래 밸브가 맡은 노즐도 든다."""
        if ref in self._part_ids:
            node = self._part_node.get(ref)
            nodes = [] if node is None else [node]
            direct = []
        else:
            idxs = self._by_pipe.get(ref, ())
            lows = [(self.edges[i].a, self.edges[i].b) for i in idxs]
            nodes = [a if self.depth[a] > self.depth[b] else b for a, b in lows]
            direct = [em for em in self.emitters
                      if em.id in self._emitter_spot
                      and self.edges[self._emitter_spot[em.id][0]].pipe_id == ref]
        out = {em.id: em for em in direct}
        for node in self._below(nodes):
            for em in self._emitters_at.get(node, ()):
                out[em.id] = em
        return list(out.values())

    def component_id(self, ref) -> Optional[int]:
        """대상이 든 덩어리 번호. 그래프 밖이면 None."""
        start = self._start_of(ref)
        return None if start is None else self.component_of.get(start[0])

    def sources_of(self, ref) -> List[Part]:
        """대상이 물린 덩어리의 공급 부품들 — 상류 순서(수원 → 탱크 → 펌프)."""
        comp = self.component_id(ref)
        return [] if comp is None else self.component_sources(comp)

    def component_sources(self, comp) -> List[Part]:
        found = [part for node in self.components[comp]
                 for part in self.part_at.get(node, ())
                 if supply_tier(part.kind) is not None]
        return sorted(found, key=lambda part: (supply_tier(part.kind), str(part.id)))

    def component_pipes(self, comp) -> List[object]:
        """덩어리에 든 배관 id (그린 순서)."""
        nodes = set(self.components[comp])
        return [p.id for p in self.pipes
                if any(self.edges[i].a in nodes for i in self._by_pipe.get(p.id, ()))]

    def component_emitters(self, comp) -> List[Emitter]:
        nodes = set(self.components[comp])
        return [em for em in self.emitters
                if em.id in self._emitter_spot and self._emitter_spot[em.id][1] in nodes]

    def component_loops(self, comp) -> int:
        """덩어리의 독립 고리 수(구간 - 마디 + 1)."""
        nodes = set(self.components[comp])
        return sum(1 for e in self.edges if e.a in nodes) - len(nodes) + 1

    def joined_pipes(self) -> set:
        """다른 배관과 마디를 나눠 가진 배관 id."""
        at: Dict[tuple, set] = {}
        for edge in self.edges:
            if not edge.bridge:
                at.setdefault(edge.a, set()).add(edge.pipe_id)
                at.setdefault(edge.b, set()).add(edge.pipe_id)
        out: set = set()
        for pipes in at.values():
            if len(pipes) > 1:
                out |= pipes
        # 틈 잇기는 마디를 나누지 않고 구간으로 잇는다.
        for edge in self.edges:
            if edge.bridge:
                out |= at.get(edge.a, set()) | at.get(edge.b, set())
        return out

    def shared_upstream(self, refs) -> List[dict]:
        """대상 여럿의 공통 상류 — 덩어리마다 ``{'component', 'path', 'sources'}``.

        구역 하나의 노즐들이 공통으로 지나는 칸만 남긴다(수원 쪽부터 같은 데까지).
        """
        groups: Dict[int, list] = {}
        for ref in refs:
            comp = self.component_id(ref)
            if comp is not None:
                groups.setdefault(comp, []).append(ref)
        out = []
        for comp, members in sorted(groups.items()):
            common = None
            for ref in members:
                path = self.upstream_path(ref)
                if common is None:
                    common = path
                    continue
                n = 0
                while n < min(len(common), len(path)) and common[n]['id'] == path[n]['id']:
                    n += 1
                common = common[:n]
                if not common:
                    break
            out.append({'component': comp, 'path': common or [],
                        'sources': self.component_sources(comp)})
        return out


def supply_tier(kind) -> Optional[int]:
    """공급 부품의 뿌리 순서. 공급 부품이 아니면 None."""
    part = part_table.get(kind)
    if part is None or part.group != 'supply':
        return None
    return _SUPPLY_TIER.get(kind, 0)
