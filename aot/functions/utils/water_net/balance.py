# coding=utf-8
"""water_net.balance — L0 유량 수지. 회로 하나의 작동 구간을 시간순으로 푼다.

    수요 Qd = 열린 Output 들의 정격 합
    공급 Qs = min(펌프 정격, 수원 허용)
    전달 Q  = min(Qd, Qs). 열린 Output 끼리는 수요 비례로 나눈다.

일 합계 초가 아니라 **작동 구간**으로 계산한다 — 펌프 하나를 밸브 둘이 나눠 쓰면 겹친
시간에만 한계가 걸리기 때문이다. 시각은 epoch 초, 유량은 L/min 이다.

수요의 임자는 여기서 정하지 않는다. 부르는 쪽이 담당 폴리곤으로 정한 ``demands`` 를 넘긴다.

탱크가 있으면 물은 탱크에서 나간다. 물이 남아 있는 동안 수원은 한계가 아니고(펌프만 한계다),
바닥나면 ``min(펌프, 유입)`` 으로 내려간다. 유입은 가동 중에만 센다 — 쉬는 동안 얼마나 찼는지는
다음 수위 측정이 다시 맞춘다. 시작량은 수위 측정이 있을 때만 쓴다(가득 찼다고 치지 않는다).
수위가 없으면 수지를 생략하고, 수원이 펌프로 바로 물린 것이 아니므로 수원 한계도 걸지 않는다.

한 회로에 펌프가 여럿이면 병렬로 친다(켜진 것의 정격 합). 직렬 가압은 L0 가 구분하지 못한다.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from . import result as R

INF = float('inf')
_EPS = 1e-9

Span = Tuple[float, float]


class Run(NamedTuple):
    output_id: object
    t0: float
    t1: float


class Pump(NamedTuple):
    id: object
    rated_lpm: Optional[float] = None
    power_kw: Optional[float] = None
    runs: Optional[Sequence[Span]] = None    # None = Output 에 연결되지 않아 켜짐·꺼짐을 모른다
    measured_kwh: Optional[float] = None


class Source(NamedTuple):
    id: object
    max_lpm: Optional[float] = None


class Tank(NamedTuple):
    id: object
    capacity_l: Optional[float] = None
    levels: Optional[Sequence[Tuple[float, float]]] = None  # [(시각, L)] 수위 측정


class Circuit(NamedTuple):
    id: object
    pumps: Sequence[Pump] = ()
    sources: Sequence[Source] = ()
    tanks: Sequence[Tank] = ()


def source_limit(sources: Sequence[Source]) -> float:
    """수원 허용 합. 하나라도 비었으면 제한 없음이다."""
    if not sources or any(not s.max_lpm for s in sources):
        return INF
    return sum(s.max_lpm for s in sources)


def _merged(spans: Iterable[Span]) -> List[List[float]]:
    out: List[List[float]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class _Cursor:
    """켜짐 구간을 앞으로만 훑는다. 시각은 늘 늘어나는 순서로 묻는다."""

    def __init__(self, spans):
        self.spans = _merged(spans)
        self.i = 0

    def on_at(self, t) -> bool:
        while self.i < len(self.spans) and self.spans[self.i][1] <= t:
            self.i += 1
        return self.i < len(self.spans) and self.spans[self.i][0] <= t


def pool_levels(tanks: Sequence[Tank]) -> Optional[List[Tuple[float, float]]]:
    """회로의 탱크들을 한 덩어리 수위로. 모든 탱크의 첫 측정 뒤부터만 낸다. 없으면 None."""
    if not tanks or any(not t.levels for t in tanks):
        return None
    if len(tanks) == 1:
        return sorted(tanks[0].levels)
    series = [sorted(t.levels) for t in tanks]
    start = max(s[0][0] for s in series)
    out = []
    for now in sorted({t for s in series for t, _v in s if t >= start}):
        out.append((now, sum([v for t, v in s if t <= now][-1] for s in series)))
    return out


class _TankState:
    def __init__(self, levels, capacity):
        self.levels = levels
        self.capacity = capacity
        self.i = 0
        self.v: Optional[float] = None
        self.start_l: Optional[float] = None
        self.inflow_l = 0.0
        self.adjust_l = 0.0
        self.empty_at: Optional[float] = None
        self.counting = False

    def sync(self, t):
        """t 까지의 측정으로 다시 맞춘다."""
        while self.i < len(self.levels) and self.levels[self.i][0] <= t:
            measured = self.levels[self.i][1]
            if self.counting:
                if self.v is None:
                    self.start_l = measured
                else:
                    self.adjust_l += measured - self.v
            self.v = measured
            self.i += 1

    def begin(self):
        if not self.counting:
            self.counting = True
            self.start_l = self.v


class _NoLevel:
    """수위를 모르는 탱크. `_advance` 가 수원 한계를 걸지 않게 하는 표식이다."""
    v = None


_NO_LEVEL = _NoLevel()


def _pump_cap(pumps, cursors, demand_on) -> Tuple[float, list]:
    """지금 펌프가 낼 수 있는 유량과 돌고 있는 펌프. 펌프가 없으면 제한 없음."""
    if not pumps:
        return INF, []
    running = [p for p in pumps
               if (demand_on if cursors[p.id] is None else cursors[p.id])]
    if not running:
        return 0.0, []
    if any(not p.rated_lpm for p in running):
        return INF, running
    return sum(p.rated_lpm for p in running), running


class _Book:
    """실행 하나의 장부."""

    __slots__ = ('run', 'design', 'delivered')

    def __init__(self, run):
        self.run = run
        self.design = 0.0
        self.delivered = 0.0


def _advance(qd, cap, src, tank, inflow, a, dt, books, demands, on_count):
    """구간 하나를 흘린다 → 전달 L. 탱크가 비거나 차는 순간에는 쪼갠다."""
    delivered = 0.0
    t, left = a, dt
    while left > _EPS:
        if tank is None or tank.v is None:
            limit = cap if tank is not None else min(cap, src)
            q, i, step = min(qd, limit), 0.0, left
        else:
            q = min(qd, cap) if tank.v > _EPS else min(qd, cap, inflow)
            i = q if inflow == INF else inflow
            if tank.capacity and tank.v >= tank.capacity - _EPS:
                i = min(i, q)
            net = i - q
            step = left
            if net < 0 and tank.v > _EPS:
                step = min(left, tank.v / -net * 60.0)
            elif net > 0 and tank.capacity:
                step = min(left, (tank.capacity - tank.v) / net * 60.0)
            tank.v = max(0.0, tank.v + net * step / 60.0)
            if tank.capacity:
                tank.v = min(tank.v, tank.capacity)
            if on_count:
                tank.inflow_l += i * step / 60.0
                if tank.v <= _EPS and tank.empty_at is None and qd > q + _EPS:
                    tank.empty_at = t + step if net < 0 else t
        ratio = q / qd if qd > 0 else 0.0
        for book in books:
            book.delivered += demands.get(book.run.output_id, 0.0) * ratio * step / 60.0
        delivered += q * step / 60.0
        t += step
        left -= step
    return delivered


def energy_kwh(samples: Sequence[Tuple[float, float]], unit: str) -> Optional[float]:
    """전력 측정 → kWh. 'kWh' 는 누적계(나중 − 처음), 'W' 는 사다리꼴 적분. 못 내면 None.

    누적계가 뒤집혔으면(교체·리셋) 지어내지 않는다(`usage_from_stats` 와 같은 규칙).
    """
    rows = sorted(samples or ())
    if len(rows) < 2:
        return None
    if unit == 'kWh':
        used = rows[-1][1] - rows[0][1]
        return used if used >= 0 else None
    joules = sum((b[0] - a[0]) * (a[1] + b[1]) / 2.0 for a, b in zip(rows, rows[1:]))
    return joules / 3600000.0


def _pump_rows(pumps, hours) -> Optional[dict]:
    if not pumps:
        return None
    rows = []
    for p in pumps:
        spent = hours.get(p.id, 0.0)
        kwh = p.measured_kwh
        basis = R.BASIS_MEASURED
        if kwh is None:
            basis = R.BASIS_RATED
            kwh = p.power_kw * spent if p.power_kw else None
        rows.append({'id': p.id, 'rated_lpm': p.rated_lpm, 'hours': round(spent, 3),
                     'kwh': None if kwh is None else round(kwh, 3), 'basis': basis})
    known = [r['kwh'] for r in rows if r['kwh'] is not None]
    bases = {r['basis'] for r in rows if r['kwh'] is not None}
    return {'kwh': round(sum(known), 3) if known else None,
            'hours': round(sum(r['hours'] for r in rows), 3),
            'basis': bases.pop() if len(bases) == 1 else None, 'pumps': rows}


def solve(circuit: Circuit, demands: Dict[object, float], runs: Sequence[Run], t0: float,
          t1: float) -> dict:
    """회로 하나 + 작동 구간 → 회로 결과.

    ``runs`` 는 이 회로의 Output 전부다 — 구획 밖 Output 도 같은 펌프를 나눠 쓴다. ``t0`` 앞에서
    켜져 걸쳐 오는 실행도 넘긴다. 장부에는 ``t0 <= 켠 시각 < t1`` 인 실행만 적는다(일지가 사건을
    켠 시각의 날짜에 싣는 것과 같다). 그 실행이 ``t1`` 을 넘겨 돌면 끝까지 푼다.

    Returns: ``{'id', 'runs': [{…, 'ratio'}], 'demand_l', 'delivered_l', 'delivered_ratio',
    'pump', 'tank', 'caveats', 'seconds': {표시: 초}}``. 표시는 알리기만 한다.
    """
    pumps, sources, tanks = list(circuit.pumps), list(circuit.sources), list(circuit.tanks)
    runs = sorted((r for r in runs if r.t1 > r.t0), key=lambda r: r.t0)
    levels = pool_levels(tanks)
    capacity = None
    if tanks and all(t.capacity_l for t in tanks):
        capacity = sum(t.capacity_l for t in tanks)
    tank = _TankState(levels, capacity) if levels else None
    # 수위를 모르면 탱크가 있어도 수지를 세지 않는다. 표식만 남겨 수원 한계를 걸지 않는다.
    tank_now = tank or (_NO_LEVEL if tanks else None)
    src = source_limit(sources)
    inflow = src if sources else 0.0
    state_known = bool(pumps) and all(p.runs is not None for p in pumps)

    cursors = {p.id: None if p.runs is None else _Cursor(p.runs) for p in pumps}
    pump_spans = [s for p in pumps for s in (p.runs or ())]
    edges = {t0}
    edges.update(t for r in runs for t in (r.t0, r.t1))
    edges.update(t for s in pump_spans for t in s)
    if tank is not None:
        edges.update(t for t, _v in levels)
    start = min([r.t0 for r in runs] + [s[0] for s in pump_spans] + [t0])
    stop = max([r.t1 for r in runs] + [s[1] for s in pump_spans] + [t0])
    order = sorted(t for t in edges if start <= t <= stop)

    books = [_Book(r) for r in runs]
    active: List[_Book] = []
    next_book = 0
    demand_l = delivered_l = 0.0
    seconds: Dict[str, float] = {}
    hours: Dict[object, float] = {}

    def _mark(code, dt):
        seconds[code] = seconds.get(code, 0.0) + dt

    for a, b in zip(order, order[1:]):
        while next_book < len(books) and books[next_book].run.t0 <= a:
            active.append(books[next_book])
            next_book += 1
        active = [book for book in active if book.run.t1 > a]
        if tank is not None:
            tank.sync(a)
        dt = b - a
        on_count = a >= t0
        open_ids = {book.run.output_id for book in active}
        qd = sum(demands.get(o, 0.0) for o in open_ids)
        cursors_now = {pid: (None if c is None else c.on_at(a)) for pid, c in cursors.items()}
        cap, running = _pump_cap(pumps, cursors_now, qd > 0)
        if on_count:
            if tank is not None:
                tank.begin()
            for pump in running:
                hours[pump.id] = hours.get(pump.id, 0.0) + dt / 3600.0
            if state_known and running and not open_ids:
                _mark(R.PUMP_DEAD_HEAD, dt)
        for book in active:
            book.design += demands.get(book.run.output_id, 0.0) * dt / 60.0
        if qd <= 0:
            continue
        if on_count:
            if state_known and not running:
                _mark(R.VALVE_WITHOUT_PUMP, dt)
            elif running and cap != INF and qd > cap + _EPS:
                _mark(R.PUMP_OVER_DEMAND, dt)
            if not tanks and src < cap and qd > src + _EPS:
                _mark(R.SOURCE_OVER_DEMAND, dt)
        delivered = _advance(qd, cap, src, tank_now, inflow, a, dt, active, demands, on_count)
        if on_count:
            demand_l += qd * dt / 60.0
            delivered_l += delivered

    booked = [book for book in books if t0 <= book.run.t0 < t1]
    caveats = sorted(seconds, key=R.CAVEATS.index)
    tank_row = None
    if tank is not None:
        tank_row = {'start_l': tank.start_l, 'end_l': None if tank.v is None else round(tank.v, 3),
                    'empty_at': tank.empty_at, 'inflow_l': round(tank.inflow_l, 3),
                    'adjust_l': round(tank.adjust_l, 3)}
        if tank.empty_at is not None:
            caveats.append(R.TANK_EMPTY)
    if booked:
        unrated = any(not p.rated_lpm for p in pumps)
        if unrated or (not pumps and (tanks or src == INF)):
            caveats.append(R.SUPPLY_UNKNOWN)
        if pumps and not state_known:
            caveats.append(R.PUMP_STATE_UNKNOWN)
        if tanks and tank is None:
            caveats.append(R.TANK_LEVEL_UNKNOWN)
    return {
        'id': circuit.id,
        'runs': [{'output_id': b.run.output_id, 't0': b.run.t0, 't1': b.run.t1,
                  'design_l': b.design, 'delivered_l': b.delivered,
                  'ratio': (b.delivered / b.design) if b.design > 0 else 1.0}
                 for b in booked],
        'demand_l': round(demand_l, 3), 'delivered_l': round(delivered_l, 3),
        'delivered_ratio': round(delivered_l / demand_l, 3) if demand_l > 0 else None,
        'pump': _pump_rows(pumps, hours),
        'tank': tank_row,
        'caveats': R.merge_caveats([caveats]),
        'seconds': seconds,
    }
