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

배관망 데이터에는 그래프가 명시돼 있지 않다 — ``irrigation_connection`` 은
좌표만 든 표시용 구슬이라 어느 배관끼리 물렸는지 말해 주지 않는다. 그래서
기하로 다시 세운다: 배관끼리 닿는 자리가 마디다. 끝점이 다른 배관 위에
얹힌 자리(T·엘보)와 두 배관이 가로지르는 자리(십자) 둘 다 — 디자이너가
화면에 티를 꽂아 주는 자리와 같은 규칙이다.
"""

from __future__ import annotations

import math

# 마디를 같은 점으로 볼 거리 [m]. 디자이너의 라이저 스냅이 8cm 이므로
# 그보다 넉넉히 잡는다(_trimBranchAtPoint 의 교차 판정은 1cm).
SNAP_M = 0.12
# 노즐을 배관에 얹을 때 허용하는 수평 거리 [m]. 노즐은 배관에 매달리므로
# 원래 배관 위에 있지만, 손으로 옮긴 것까지 받아 준다.
DEVICE_SNAP_M = 1.0


def _fnum(value, default=0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _key(p):
    """스냅 격자 위의 마디 이름."""
    return (round(p[0] / SNAP_M), round(p[1] / SNAP_M), round(p[2] / SNAP_M))


def _dist_xz(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


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
        elif _dist_xz(pts[-1], a) > SNAP_M:
            pts.append(a)
        pts.append(b)
    return pts


def _project(pts, p):
    """점 p 를 점렬 위에 내린다 → (호길이, 거리). 점렬이 비면 None."""
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
        d = _dist_xz(proj, p)
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


class _LayerNet:
    """레이어 하나의 배관망. 마디 그래프 + 공급점에서 내린 부모 관계."""

    def __init__(self, pipes, valves):
        self.pipes = [p for p in pipes if len(_polyline(p)) >= 2]
        self.lines = {p.get('id'): _polyline(p) for p in self.pipes}
        self.valves = valves
        self.edges = []          # (node_a, node_b, pipe_id, s_a, s_b)
        self.adj = {}            # node → [(other, edge_index)]
        self.valve_at = {}       # node → [valve, ...]
        self.parent = {}         # node → node (공급 쪽)
        self._build()

    # ── 마디 세우기 ────────────────────────────────────────────────────────
    def _build(self):
        # 배관마다 잘라야 할 호길이들을 모은다: 자기 양끝, 다른 배관의 끝점이
        # 얹힌 자리, 그리고 밸브가 선 자리.
        cuts = {}
        for p in self.pipes:
            pid = p.get('id')
            pts = self.lines[pid]
            total = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2])
                        for i in range(len(pts) - 1))
            cuts[pid] = {0.0, total}

        for p in self.pipes:
            pid = p.get('id')
            for q in self.pipes:
                qid = q.get('id')
                if qid == pid:
                    continue
                qpts = self.lines[qid]
                # 다른 배관의 끝점이 이 배관 위에 얹힌 자리 (T·엘보)
                for end in (qpts[0], qpts[-1]):
                    hit = _project(self.lines[pid], end)
                    if hit and hit[2] <= SNAP_M:
                        cuts[pid].add(hit[0])

        # 두 배관이 가로지르는 자리(십자)도 마디다. 화면에서는 디자이너가
        # 거기에 티(mbT/bT/mT)를 꽂아 주므로, 물길에서만 안 이어져 있으면
        # 눈에 보이는 배관망과 계산이 어긋난다 — 가로지르기만 한 주배관이
        # 섬으로 남아 그 위의 구역밸브가 아무것도 못 맡는 식으로.
        for i in range(len(self.pipes)):
            for j in range(i + 1, len(self.pipes)):
                pid = self.pipes[i].get('id')
                qid = self.pipes[j].get('id')
                for hit in _crossings(self.lines[pid], self.lines[qid]):
                    for target in (pid, qid):
                        proj = _project(self.lines[target], hit)
                        if proj and proj[2] <= SNAP_M:
                            cuts[target].add(proj[0])

        for v in self.valves:
            spot = self._valve_spot(v)
            if spot is None:
                continue
            pid, s = spot
            cuts.setdefault(pid, set()).add(s)

        for p in self.pipes:
            pid = p.get('id')
            pts = self.lines[pid]
            ordered = sorted(cuts[pid])
            merged = []
            for s in ordered:
                if not merged or s - merged[-1] > SNAP_M:
                    merged.append(s)
            for i in range(len(merged) - 1):
                a_pt, b_pt = _point_at(pts, merged[i]), _point_at(pts, merged[i + 1])
                if a_pt is None or b_pt is None:
                    continue
                na, nb = _key(a_pt), _key(b_pt)
                if na == nb:
                    continue
                idx = len(self.edges)
                self.edges.append((na, nb, pid, merged[i], merged[i + 1]))
                self.adj.setdefault(na, []).append((nb, idx))
                self.adj.setdefault(nb, []).append((na, idx))

        for v in self.valves:
            spot = self._valve_spot(v)
            if spot is None:
                continue
            pid, s = spot
            node = _key(_point_at(self.lines[pid], s))
            self.valve_at.setdefault(node, []).append(v)

        self._root_from_supply()

    def _valve_spot(self, valve):
        """밸브가 선 자리 → (pipe_id, 호길이). 배관을 못 찾으면 None.

        pipe_id 가 있으면 그 배관 위에, 없으면 좌표에서 가장 가까운 배관에
        얹는다. 좌표조차 없으면 attach_t 로 그 배관의 비율 위치를 쓴다.
        """
        pid = valve.get('pipe_id')
        p = _pos_pt(valve)
        if pid and pid in self.lines:
            pts = self.lines[pid]
            if p is not None:
                hit = _project(pts, p)
                if hit:
                    return pid, hit[0]
            t = valve.get('attach_t')
            if t is not None:
                total = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][2] - pts[i][2])
                            for i in range(len(pts) - 1))
                return pid, max(0.0, min(1.0, _fnum(t, 0.5))) * total
            return pid, 0.0
        if p is None:
            return None
        best = None
        for q in self.pipes:
            hit = _project(self.lines[q.get('id')], p)
            if hit and (best is None or hit[2] < best[2]):
                best = (q.get('id'), hit[0], hit[2])
        if best is None:
            return None
        return best[0], best[1]

    # ── 공급점 ─────────────────────────────────────────────────────────────
    def _root_from_supply(self):
        """물이 들어오는 마디를 정하고 거기서 부모 관계를 내린다.

        수직관(라이저)은 바닥에서 레이어 높이로 올라오는 급수 인입이므로
        그 아래 끝이 공급점이다. 라이저가 없으면 주배관의 시작점, 그것도
        없으면 아무 배관의 시작점을 쓴다 — 어느 쪽을 잡아도 밸브 상하류
        관계는 뒤집히지 않는다(트리 위에서 방향만 정하는 값이다).
        """
        root_pt = None
        risers = [p for p in self.pipes if p.get('is_vertical')]
        if risers:
            cands = []
            for r in risers:
                pts = self.lines[r.get('id')]
                cands.extend([pts[0], pts[-1]])
            root_pt = min(cands, key=lambda pt: pt[1])
        else:
            mains = [p for p in self.pipes if p.get('sub_type') == 'main']
            pool = mains or self.pipes
            if pool:
                root_pt = self.lines[pool[0].get('id')][0]
        if root_pt is None:
            return
        root = _key(root_pt)
        if root not in self.adj:
            if not self.adj:
                return
            root = next(iter(self.adj))

        seen = set()

        def _spread(start):
            # 너비 우선으로 부모를 심는다. 고리(loop)가 있어도 먼저 닿은 쪽이
            # 상류가 되어 무한 순회하지 않는다.
            self.parent[start] = None
            queue = [start]
            seen.add(start)
            while queue:
                node = queue.pop(0)
                for other, _idx in self.adj.get(node, []):
                    if other in seen:
                        continue
                    seen.add(other)
                    self.parent[other] = node
                    queue.append(other)

        _spread(root)

        # 공급점에서 닿지 않는 덩어리 — 배관을 그렸는데 아직 본관에 물리지
        # 않은 상태다. 그냥 두면 그 위의 노즐은 부모가 없어 상류 밸브를 못
        # 찾고 전부 공급 몫으로 조용히 떨어진다. 덩어리마다 가장 낮은 점을
        # 임시 뿌리로 삼아 상하류만이라도 세운다 — 그 안의 밸브는 제대로
        # 동작하고, 진짜 공급과의 연결은 사용자가 배관을 이으면 잡힌다.
        while True:
            rest = [n for n in self.adj if n not in seen]
            if not rest:
                break
            _spread(min(rest, key=lambda n: (n[1], n[0], n[2])))

    # ── 임자 찾기 ──────────────────────────────────────────────────────────
    def owner_of(self, device):
        """노즐의 임자 밸브. 상류에 밸브가 하나도 없으면 None(=레이어 몫)."""
        p = _pos_pt(device)
        if p is None:
            return None
        pid = device.get('pipe_id')
        hit = _project(self.lines[pid], p) if pid in self.lines else None
        if hit is None or hit[2] > DEVICE_SNAP_M:
            best = None
            for q in self.pipes:
                cand = _project(self.lines[q.get('id')], p)
                if cand and (best is None or cand[2] < best[2]):
                    best = (q.get('id'), cand[0], cand[2])
            if best is None:
                return None
            pid, s = best[0], best[1]
        else:
            s = hit[0]

        # 노즐이 얹힌 구간을 찾고, 그 구간의 상류 쪽 마디에서 위로 올라간다.
        upstream = None
        for (na, nb, epid, sa, sb) in self.edges:
            if epid != pid:
                continue
            if sa - SNAP_M <= s <= sb + SNAP_M:
                upstream = na if self._depth(na) <= self._depth(nb) else nb
                break
        if upstream is None:
            return None

        node = upstream
        guard = 0
        while node is not None and guard < 10_000:
            guard += 1
            here = self.valve_at.get(node)
            if here:
                return sorted(here, key=lambda v: str(v.get('id')))[0]
            node = self.parent.get(node)
        return None

    def _depth(self, node):
        d, guard = 0, 0
        while node is not None and guard < 10_000:
            node = self.parent.get(node)
            if node is None:
                return d
            d += 1
            guard += 1
        return d


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

        net = _LayerNet(pipes, valves)
        for dev in devices:
            owner = net.owner_of(dev)
            if owner is None:
                by_layer.setdefault(lid, []).append(dev)
            else:
                by_valve.setdefault(owner.get('id'), []).append(dev)

    return by_valve, by_layer
