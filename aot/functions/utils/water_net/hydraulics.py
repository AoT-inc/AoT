# coding=utf-8
"""water_net.hydraulics — L1 압력 계산. 회로 하나의 작동점을 푼다.

    관 손실  Hazen-Williams   hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)   (Q m³/s, D m)
    노즐     q = k · √P       k = 기준 유량 / √기준 압력   (P 는 수두 m, 1 bar = 10.197 m)
    펌프     H(Q) = H0 − a·Q²  정격점 (Qr, Hr) 하나만 알아서 H0 = 1.33·Hr 로 가정한다

회로는 나무 구조다(고리는 L0). 펌프 출구가 뿌리이고, 노즐이 앉은 자리마다 배관을 쪼개서 노즐 사이
손실도 센다 — 지관 하나에 노즐이 수십 개 달리므로 쪼개지 않으면 끝 노즐 압력이 부풀려진다.

**모르는 값은 지어내지 않는다.** 흐르는 배관 하나라도 관경이 없으면 회로 전체가 L0 로 남고 이유를
코드로 준다(`L0_REASONS`). L1 은 모든 근거가 갖춰졌을 때만 낸다. 알려진 가정은 ``assumptions`` 에 적는다.

이 모듈은 Flask·DB 를 모른다. 부르는 쪽(`water_net_link`)이 재료를 모은다.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .graph import Network, project
from .terrain import Terrain, effective_heights

LEVEL_L0 = 'L0'
LEVEL_L1 = 'L1'
# 일부 배관의 관경이 비어 그 구간을 손실 0 으로 두고 푼 값. L1 이 아니다 — 펌프 유량은 실제보다 높거나 같은 상한이고,
# 빈 배관 아래 노즐의 압력도 대체로 높게 나온다. 다만 펌프 양정이 유량 증가로 내려가므로 다른 노즐의 압력은 오히려 조금 낮아질 수 있다.
LEVEL_PARTIAL = 'L1-partial'

# L0 로 남는 이유. 화면·결과가 이 코드를 그대로 읽는다.
NOT_SUPPLIED = 'not-supplied'                 # 공급에 물리지 않은 회로
NETWORK_LOOP = 'network-loop'                 # 고리 배관 — 나무 풀이가 못 푼다
NO_PUMP = 'no-pump'                           # 압력을 주는 부품이 없다
MULTIPLE_PUMPS = 'multiple-pumps'             # 병렬·직렬 펌프는 풀지 않는다
PUMP_CURVE_UNKNOWN = 'pump-curve-unknown'     # 정격 유량·양정 중 하나가 없다
PIPE_DIAMETER_UNKNOWN = 'pipe-diameter-unknown'
NOZZLE_FLOW_UNKNOWN = 'nozzle-flow-unknown'
NOZZLE_PRESSURE_UNKNOWN = 'nozzle-pressure-unknown'
NO_OPEN_NOZZLE = 'no-open-nozzle'
L0_REASONS = (NOT_SUPPLIED, NETWORK_LOOP, NO_PUMP, MULTIPLE_PUMPS, PUMP_CURVE_UNKNOWN,
              PIPE_DIAMETER_UNKNOWN, NOZZLE_FLOW_UNKNOWN, NOZZLE_PRESSURE_UNKNOWN,
              NO_OPEN_NOZZLE)

# 계산에 깔린 가정 — 결과의 ``assumptions`` 에 적힌다.
A_PUMP_SHUTOFF = 'pump-shutoff-1.33'          # 정격점만 알아 차단 양정을 정격의 1.33배로 쳤다
A_ELEVATION_FLAT = 'elevation-flat'           # 표고 입력이 없어 평지로 쳤다
A_SUCTION_IGNORED = 'suction-ignored'         # 수원 수위·흡입 손실은 펌프 양정에 든 것으로 쳤다
A_HW_C_DEFAULT = 'hw-c-default'               # 재질을 몰라 C 를 기본값으로 쳤다
A_MINOR_IGNORED = 'minor-losses-ignored'      # 이음·밸브·필터 국부 손실은 세지 않았다
A_GAP_LOSSLESS = 'gap-joins-lossless'         # 틈 잇기 구간은 손실 없는 연결로 쳤다
A_DIAMETER_EXCLUDED = 'diameter-excluded'     # 관경이 빈 배관은 손실 0 으로 뺐다(`excluded` 에 목록)
A_FLOW_UPPER_BOUND = 'flow-upper-bound'       # 그래서 펌프 유량은 실제보다 높거나 같다 — 상한값(압력은 노즐마다 방향이 다르다)
A_DRIP_LATERAL = 'drip-lateral-ignored'       # 점적 줄 안의 손실은 세지 않았다
A_ELEVATION_PARTIAL = 'elevation-partial'     # 일부 마디의 표고를 못 읽어, 그 마디가 낀 구간의 낙차는 평지(0)로 쳤다
A_LENGTH_HORIZONTAL = 'length-horizontal'     # 지형을 못 읽은 구간은 수평 길이로 손실을 셌다

# L1 수치는 그대로 두고 알리기만 하는 경고. `result.SOURCE_OVER_DEMAND` 와 같은 이름·같은 뜻이다.
W_SOURCE_OVER_DEMAND = 'source-over-demand'   # 작동점 유량이 수원 허용 유량을 넘는다

M_PER_BAR = 10.1972
PUMP_SHUTOFF_RATIO = 1.33
DEFAULT_C = 150.0
# 재질별 Hazen-Williams C. 재질 칸이 생기기 전까지는 대부분 기본값이 쓰인다.
MATERIAL_C = {'pe': 150.0, 'hdpe': 150.0, 'pvc': 150.0, 'steel': 120.0, 'iron': 100.0,
              'copper': 140.0}


def hazen_williams_m(q_lpm: float, dia_mm: float, length_m: float, c: float = DEFAULT_C) -> float:
    """관 손실 [m]. 유량·관경·길이가 0 이하면 0."""
    if q_lpm <= 0 or dia_mm <= 0 or length_m <= 0:
        return 0.0
    q = q_lpm / 60000.0
    d = dia_mm / 1000.0
    return 10.67 * length_m * q ** 1.852 / (c ** 1.852 * d ** 4.87)


def velocity_ms(q_lpm: float, dia_mm: float) -> float:
    d = dia_mm / 1000.0
    return (q_lpm / 60000.0) / (math.pi * d * d / 4.0) if d > 0 else 0.0


class Pump(NamedTuple):
    rated_lpm: float
    rated_head_m: float

    @property
    def shutoff_m(self) -> float:
        return PUMP_SHUTOFF_RATIO * self.rated_head_m

    def head_m(self, q_lpm: float) -> float:
        """양정 [m]. 곡선 끝(양정 0) 너머는 0."""
        a = (self.shutoff_m - self.rated_head_m) / (self.rated_lpm ** 2)
        return max(0.0, self.shutoff_m - a * q_lpm * q_lpm)


class Nozzle(NamedTuple):
    id: object
    node: object              # 앉은 마디
    q_ref_lpm: float
    p_ref_bar: float

    @property
    def k(self) -> float:
        return self.q_ref_lpm / math.sqrt(self.p_ref_bar * M_PER_BAR)

    def flow_lpm(self, head_m: float) -> float:
        return self.k * math.sqrt(head_m) if head_m > 0 else 0.0


class Link(NamedTuple):
    node: object
    parent: object
    length_m: float
    dia_mm: Optional[float]
    c: float
    pipe_id: object = None
    # 지형(T2) — 모두 기본값이라 없으면 예전과 같다. ``length_m`` 은 언제나 수평 길이다.
    s_lo: Optional[float] = None      # 배관 호길이 범위(작은 쪽 → 큰 쪽)
    s_hi: Optional[float] = None
    slant_m: Optional[float] = None   # 경사 길이. 지형을 못 읽었거나 지형이 없으면 None

    @property
    def loss_length_m(self) -> float:
        """관 손실에 쓰는 길이 — 경사 길이를 알면 그것, 아니면 수평 길이."""
        return self.length_m if self.slant_m is None else self.slant_m


class Tree(NamedTuple):
    root: object
    links: Sequence[Link]     # 부모가 앞에 오는 순서
    nozzles: Sequence[Nozzle]
    assumptions: Tuple[str, ...] = ()
    heights: Optional[Dict[object, float]] = None   # 마디별 정수두 높이 [m](뿌리 기준 누적 Δz). 지형이 있을 때만
    terrain: Optional[dict] = None                  # 쓴 지형 {version, cell_m}


def _carrying(tree: Tree) -> Dict[object, bool]:
    """노즐이 하나라도 아래에 달린 마디."""
    has = {nz.node: True for nz in tree.nozzles}
    for link in reversed(tree.links):
        if has.get(link.node):
            has[link.parent] = True
    return has


def missing_diameters(tree: Tree) -> List[dict]:
    """물이 흐르는 배관 중 관경이 없는 것 → ``[{'pipe', 'length_m'}]`` (배관별 합)."""
    has = _carrying(tree)
    out: Dict[object, float] = {}
    for link in tree.links:
        if has.get(link.node) and not link.dia_mm and link.pipe_id is not None:
            out[link.pipe_id] = out.get(link.pipe_id, 0.0) + link.length_m
    return [{'pipe': pid, 'length_m': round(length, 1)} for pid, length in out.items()]


def coverage(tree: Tree) -> dict:
    """흐르는 배관 길이 중 관경이 입력된 비율 — 화면이 '관경 입력률' 로 읽는다."""
    has = _carrying(tree)
    pipes = [link for link in tree.links if has.get(link.node) and link.pipe_id is not None]
    total = sum(link.length_m for link in pipes)
    known = sum(link.length_m for link in pipes if link.dia_mm)
    return {'known_m': round(known, 1), 'total_m': round(total, 1),
            'ratio': round(known / total, 3) if total > 0 else None}


def _flows(tree: Tree, q: Dict[object, float]) -> Dict[object, float]:
    flow: Dict[object, float] = {}
    for nz in tree.nozzles:
        flow[nz.node] = flow.get(nz.node, 0.0) + q[nz.id]
    for link in reversed(tree.links):
        flow[link.parent] = flow.get(link.parent, 0.0) + flow.get(link.node, 0.0)
    return flow


def _grade(tree: Tree, root_head: float, flow, z) -> Dict[object, float]:
    grade = {tree.root: root_head + z(tree.root)}
    for link in tree.links:
        loss = hazen_williams_m(flow.get(link.node, 0.0), link.dia_mm or 0.0, link.loss_length_m, link.c)
        grade[link.node] = grade[link.parent] - loss
    return grade


def _settle(tree: Tree, root_head: float, q: Dict[object, float], z, tol=1e-9, limit=2000):
    """루트 압력 수두가 정해졌을 때 노즐 유량을 수렴시킨다(제자리 갱신). → (유량, 수두선).

    관 손실이 유량에 가파르게 걸리면(가는 관·센 유량) 단순 되먹임이 진동한다 — 잔차가 줄지 않으면
    완화 계수를 절반으로 줄인다.
    """
    omega, prev = 0.5, float('inf')
    for _ in range(limit):
        flow = _flows(tree, q)
        grade = _grade(tree, root_head, flow, z)
        worst = 0.0
        new = {}
        for nz in tree.nozzles:
            new[nz.id] = nz.flow_lpm(grade[nz.node] - z(nz.node))
            worst = max(worst, abs(new[nz.id] - q[nz.id]) / max(nz.q_ref_lpm, 1e-9))
        if worst >= prev * 0.999:
            omega = max(omega * 0.5, 0.01)
        prev = worst
        for nz in tree.nozzles:
            q[nz.id] = (1.0 - omega) * q[nz.id] + omega * new[nz.id]
        if worst < tol:
            break
    flow = _flows(tree, q)
    return flow, _grade(tree, root_head, flow, z)


def operating_point(tree: Tree, pump: Pump, elevation: Optional[Callable[[object], float]] = None) -> dict:
    """펌프 곡선과 회로가 만나는 작동점. 관경이 모두 있어야 한다(호출 전에 확인).

    → ``{'pump': {lpm, head_m}, 'nozzles': [{id, bar, lpm, ratio}], 'links': [{pipe, node, lpm, velocity, loss_m}]}``
    """
    if tree.heights is not None:
        z = lambda n: tree.heights.get(n, 0.0)          # noqa: E731 — 지형이 이기고, 예전 ``elevation`` 인자는 무시된다
    else:
        z = elevation or (lambda _n: 0.0)
    q = {nz.id: nz.q_ref_lpm for nz in tree.nozzles}

    def _mismatch(head):
        flow, _g = _settle(tree, head, q, z, tol=1e-7)
        return pump.head_m(flow.get(tree.root, 0.0)) - head

    lo, hi = 0.0, pump.shutoff_m
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _mismatch(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6:
            break
    head = (lo + hi) / 2.0
    flow, grade = _settle(tree, head, q, z, tol=1e-10)
    total = flow.get(tree.root, 0.0)
    nozzles = []
    for nz in tree.nozzles:
        p_m = max(0.0, grade[nz.node] - z(nz.node))
        nozzles.append({'id': nz.id, 'bar': p_m / M_PER_BAR, 'lpm': q[nz.id],
                        'ratio': q[nz.id] / nz.q_ref_lpm if nz.q_ref_lpm else 0.0})
    links = []
    for link in tree.links:
        lpm = flow.get(link.node, 0.0)
        if lpm <= 0 or not link.dia_mm:
            continue
        row = {'pipe': link.pipe_id, 'node': link.node, 'lpm': lpm,
               'velocity': velocity_ms(lpm, link.dia_mm),
               'loss_m': hazen_williams_m(lpm, link.dia_mm, link.loss_length_m, link.c)}
        if tree.terrain is not None:
            row.update(s_a=link.s_lo, s_b=link.s_hi, horizontal_m=link.length_m, slant_m=link.slant_m,
                       dz_m=(tree.heights.get(link.node, 0.0) - tree.heights.get(link.parent, 0.0)))
        links.append(row)
    return {'pump': {'lpm': total, 'head_m': pump.head_m(total), 'delivered_head_m': head},
            'nozzles': nozzles, 'links': links}


def summarize(point: dict, tree: Tree) -> dict:
    """작동점 → 화면·MCP 가 읽는 짧은 모양. 압력은 bar, 유량은 L/min."""
    nz = point['nozzles']
    bars = [n['bar'] for n in nz]
    ratios = [n['ratio'] for n in nz]
    design = sum(n.q_ref_lpm for n in tree.nozzles)
    fast = max(point['links'], key=lambda l: l['velocity'], default=None)
    worst = min(nz, key=lambda n: n['bar'], default=None)
    return {
        'pump_lpm': round(point['pump']['lpm'], 1),
        'pump_head_m': round(point['pump']['head_m'], 1),
        'design_lpm': round(design, 1),
        'nozzles': len(nz),
        'bar_min': round(min(bars), 2) if bars else None,
        'bar_mean': round(sum(bars) / len(bars), 2) if bars else None,
        'bar_max': round(max(bars), 2) if bars else None,
        'flow_ratio_min': round(min(ratios), 3) if ratios else None,
        'flow_ratio_mean': round(sum(ratios) / len(ratios), 3) if ratios else None,
        'worst_nozzle': worst['id'] if worst else None,
        'max_velocity_ms': round(fast['velocity'], 2) if fast else None,
        'max_velocity_pipe': fast['pipe'] if fast else None,
    }


# ── 그래프 → 나무 ───────────────────────────────────────────────────────────

def _material_c(material) -> Tuple[float, bool]:
    """(C, 기본값을 썼는가)."""
    key = str(material or '').strip().lower()
    if key in MATERIAL_C:
        return MATERIAL_C[key], False
    return DEFAULT_C, True


def _emitter_distance(net: Network, idx: int, child, emitter) -> float:
    """구간의 부모 쪽 끝에서 노즐까지 배관을 따라간 거리 [m]."""
    edge = net.edges[idx]
    hit = project(net.lines[edge.pipe_id], emitter.point)
    s = edge.s_a if hit is None else min(max(hit[0], edge.s_a), edge.s_b)
    return (s - edge.s_a) if child == edge.b else (edge.s_b - s)


def build_tree(net: Network, pump_id, emitters: Sequence, specs: Dict[object, Tuple[float, float]],
               terrain: Optional[Terrain] = None) -> Tuple[Tree, List[object]]:
    """펌프 출구를 뿌리로 하는 나무. ``specs`` 는 노즐 id → (L/min, bar).

    ``terrain`` 이 있으면 구간마다 경사 길이를, 마디마다 정수두 높이를 단다. 없으면 예전과 똑같다.

    → (나무, 나무에 못 올린 노즐 id). 펌프 위쪽(수원 쪽)에 앉은 노즐은 못 올린 쪽이다.
    """
    root = net.part_node(pump_id)
    below = net.below([root])
    on_edge: Dict[int, list] = {}
    for em in emitters:
        spot = net.emitter_spot(em.id)
        if spot is not None and em.id in specs:
            on_edge.setdefault(spot[0], []).append(em)

    assumptions = set()
    links: List[Link] = []
    nozzles: List[Nozzle] = []
    used = set()
    order = sorted((n for n in below if n != root), key=lambda n: net.depth[n])
    for node in order:
        idx = net.parent_edge[node]
        edge = net.edges[idx]
        parent = net.parent[node]
        if edge.bridge:
            assumptions.add(A_GAP_LOSSLESS)
            links.append(Link(node, parent, 0.0, None, DEFAULT_C, None))
            continue
        pipe = net._pipe_ids[edge.pipe_id]
        c, defaulted = _material_c(pipe.material)
        if defaulted:
            assumptions.add(A_HW_C_DEFAULT)
        dia = pipe.diameter_mm or None
        length = edge.s_b - edge.s_a
        here = sorted(on_edge.get(idx, ()), key=lambda e: _emitter_distance(net, idx, node, e))
        prev, travelled = parent, 0.0
        down = node == edge.b        # 구간의 부모 쪽 끝이 호길이 s_a 쪽인가

        def _span(t0, t1):
            return (edge.s_a + t0, edge.s_a + t1) if down else (edge.s_b - t1, edge.s_b - t0)

        for em in here:
            dist = min(_emitter_distance(net, idx, node, em), length)
            virtual = ('nozzle', em.id)
            lo, hi = _span(travelled, max(travelled, dist))
            links.append(Link(virtual, prev, max(0.0, dist - travelled), dia, c, edge.pipe_id, lo, hi))
            q_lpm, bar = specs[em.id]
            nozzles.append(Nozzle(em.id, virtual, q_lpm, bar))
            used.add(em.id)
            if getattr(em, 'kind', '') == 'drip':
                assumptions.add(A_DRIP_LATERAL)
            prev, travelled = virtual, dist
        lo, hi = _span(travelled, max(travelled, length))
        links.append(Link(node, prev, max(0.0, length - travelled), dia, c, edge.pipe_id, lo, hi))
    left = [em.id for em in emitters if em.id in specs and em.id not in used]
    heights = meta = None
    if terrain is not None:
        links, heights, meta = _apply_terrain(links, root, terrain, assumptions)
    return Tree(root, links, nozzles, tuple(sorted(assumptions)), heights, meta), left


def _apply_terrain(links, root, terrain: Terrain, assumptions: set):
    """구간마다 경사 길이를 달고 마디 높이를 푼다 → (링크, 높이, 지형 메타). 가정 표지는 ``assumptions`` 에 더한다."""
    out, horizontal = [], False
    for link in links:
        if link.pipe_id is None or link.s_lo is None or link.length_m <= 1e-9:
            out.append(link)
            continue
        got = terrain.slant(link.pipe_id, link.s_lo, link.s_hi)
        if got is None:
            horizontal = True
            out.append(link)
        else:
            out.append(link._replace(slant_m=got[1]))
    heights, known, total = effective_heights(root, out, terrain.node_elevation)
    if horizontal:
        assumptions.add(A_LENGTH_HORIZONTAL)
    if known == 0:
        assumptions.add(A_ELEVATION_FLAT)
    elif known < total:
        assumptions.add(A_ELEVATION_PARTIAL)
    return out, heights, terrain.meta


def evaluate(net: Network, comp: int, emitters: Sequence, flows_lph: Dict[object, float],
             pressures_bar: Dict[object, float], elevation: Optional[Callable] = None,
             terrain: Optional[Terrain] = None) -> dict:
    """회로 하나의 L1 평가. ``emitters`` 는 열려 있다고 보는 노즐들.

    관경 등 근거가 갖춰지면 ``level='L1'`` 과 작동점 요약을, 아니면 ``level='L0'`` 과 ``reasons`` 를 준다.
    L0 라도 관경 입력률(``coverage``)과 빠진 배관(``missing``)은 낸다 — 무엇을 입력하면 L1 이 되는지 알려 준다.
    """
    out: dict = {'level': LEVEL_L0, 'reasons': [], 'missing': [], 'coverage': None,
                 'assumptions': [], 'summary': None, 'nozzles': 0, 'warnings': [], 'source': None}
    reasons = out['reasons']
    if comp not in net.fed:
        reasons.append(NOT_SUPPLIED)
    if net.component_loops(comp) > 0:
        reasons.append(NETWORK_LOOP)
    pumps = [p for p in net.component_sources(comp) if p.kind == 'pump']
    if not pumps:
        reasons.append(NO_PUMP)
    elif len(pumps) > 1:
        reasons.append(MULTIPLE_PUMPS)
    pump = None
    if len(pumps) == 1:
        meta = pumps[0].meta if isinstance(pumps[0].meta, dict) else {}
        rated, head = _num(meta.get('rated_lpm')), _num(meta.get('head_m'))
        if rated and head:
            pump = Pump(rated, head)
        else:
            reasons.append(PUMP_CURVE_UNKNOWN)
    mine = [e for e in emitters if net.component_id(e.id) == comp]
    out['nozzles'] = len(mine)
    if not mine:
        reasons.append(NO_OPEN_NOZZLE)
    specs: Dict[object, Tuple[float, float]] = {}
    no_flow = [e.id for e in mine if not flows_lph.get(e.id)]
    no_bar = [e.id for e in mine if flows_lph.get(e.id) and not pressures_bar.get(e.id)]
    if no_flow:
        reasons.append(NOZZLE_FLOW_UNKNOWN)
        out['nozzle_flow_unknown'] = len(no_flow)
    if no_bar:
        reasons.append(NOZZLE_PRESSURE_UNKNOWN)
        out['nozzle_pressure_unknown'] = len(no_bar)
    for e in mine:
        if flows_lph.get(e.id) and pressures_bar.get(e.id):
            specs[e.id] = (flows_lph[e.id] / 60.0, float(pressures_bar[e.id]))

    if len(pumps) == 1 and specs:
        tree, left = build_tree(net, pumps[0].id, mine, specs, terrain)
        out['coverage'] = coverage(tree)
        out['missing'] = missing_diameters(tree)
        if left:
            out['above_pump'] = len(left)        # 펌프 위쪽 노즐 — 이 펌프가 물을 대지 않는다
        # 관경이 일부만 비었으면 그 배관을 손실 0 으로 두고 푼다(부분 계산). 하나도 없으면(입력률 0)
        # 근거가 전혀 없는 값이라 L0 로 둔다 — 지어낸 관경은 넣지 않는다.
        partial = bool(out['missing']) and (out['coverage']['ratio'] or 0.0) > 0.0
        if out['missing'] and not partial:
            reasons.append(PIPE_DIAMETER_UNKNOWN)
        out['assumptions'] = list(tree.assumptions)
        if not reasons:
            z = elevation
            assumptions = list(tree.assumptions) + [A_PUMP_SHUTOFF, A_SUCTION_IGNORED, A_MINOR_IGNORED]
            if partial:
                assumptions += [A_DIAMETER_EXCLUDED, A_FLOW_UPPER_BOUND]
                total = out['coverage']['total_m']
                out['excluded'] = out['missing']
                out['excluded_ratio'] = round(1.0 - out['coverage']['ratio'], 3)
                out['excluded_m'] = round(total - out['coverage']['known_m'], 1)
            if tree.heights is None and z is None:
                assumptions.append(A_ELEVATION_FLAT)
            point = operating_point(tree, pump, z)
            out.update(level=LEVEL_PARTIAL if partial else LEVEL_L1, summary=summarize(point, tree),
                       assumptions=sorted(set(assumptions)), nozzles=len(tree.nozzles))
            if tree.terrain is not None:
                out.update(terrain=tree.terrain, **segment_tables(point))
            out['source'] = source_check(net, comp, point['pump']['lpm'])
            if out['source']['over']:
                out['warnings'].append(W_SOURCE_OVER_DEMAND)
    return out


def segment_tables(point: dict) -> dict:
    """작동점의 구간 → ``segments`` 표와 배관별 합 ``pipe_lengths``.

    구간표는 물이 흐르는 구간(관경이 있는 것)만 담는다. 관경이 빈 배관은 손실을 세지 않은 구간이라 뺀다.
    """
    segments, lengths = [], {}
    for l in point['links']:
        if l.get('pipe') is None:
            continue
        h, sl = l['horizontal_m'], l['slant_m']
        eff = h if sl is None else sl
        segments.append({'pipe': l['pipe'], 's_a': round(l['s_a'], 6), 's_b': round(l['s_b'], 6),
                         'flow_lpm': round(l['lpm'], 2), 'horizontal_m': round(h, 6),
                         'slant_m': None if sl is None else round(sl, 6),
                         'grade_pct': round(100.0 * l['dz_m'] / h, 2) if h > 1e-9 else None,
                         'loss_m': round(l['loss_m'], 4)})
        acc = lengths.setdefault(l['pipe'], {'horizontal_m': 0.0, 'slant_m': 0.0})
        acc['horizontal_m'] += h
        acc['slant_m'] += eff
    for acc in lengths.values():
        acc['horizontal_m'] = round(acc['horizontal_m'], 6)
        acc['slant_m'] = round(acc['slant_m'], 6)
    return {'segments': segments, 'pipe_lengths': lengths}


def source_check(net: Network, comp: int, pump_lpm: float) -> dict:
    """펌프 작동점 유량을 수원 허용 유량(`max_lpm` 합)과 견준다.

    ``balance`` 와 같은 규칙이다: 탱크가 있으면 수원은 한계가 아니고(탱크가 완충한다), 수원 하나라도
    ``max_lpm`` 이 비면 모른다 — 이때 ``max_lpm`` 은 None 이고 ``over`` 는 False 로 두며 경고를 내지 않는다.
    수치는 다시 풀지 않는다: 수원이 못 대는 만큼 줄여 풀려면 흡입 쪽 모형이 필요한데 L1 은 그것을 갖지 않는다
    (``suction-ignored``). 대신 ``ratio``(수원 허용 / 작동점 유량)로 얼마나 모자란지 말한다.
    """
    sources = [p for p in net.component_sources(comp) if p.kind.startswith('source_')]
    tanks = [p for p in net.component_sources(comp) if p.kind == 'tank']
    caps = [_num((p.meta or {}).get('max_lpm')) if isinstance(p.meta, dict) else None for p in sources]
    out = {'max_lpm': None, 'over': False, 'ratio': None}
    if tanks or not sources or not all(caps):
        return out
    limit = sum(caps)
    out['max_lpm'] = round(limit, 1)
    if pump_lpm > limit + 1e-9:
        out['over'] = True
        out['ratio'] = round(limit / pump_lpm, 3)
    return out


def _num(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None
