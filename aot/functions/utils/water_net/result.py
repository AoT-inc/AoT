# coding=utf-8
"""water_net.result — 물 결과 계약의 **단일 출처**. 일지·트윈·MCP 가 같은 모양을 읽는다.

    {'target': {'kind': 'plot', 'id'}, 't0', 't1', 'level': 'L0', 'basis': 'design',
     'network_rev': 'a1b2c3…',
     'runs': [{'output_id', 't0', 't1', 'seconds', 'demand_lpm', 'delivered_lpm',
               'design_litres', 'litres', 'delivered_ratio', 'mm', 'basis'}],
     'supply': [{'circuit', 'source': [이름], 'demand_l', 'delivered_l', 'delivered_ratio',
                 'pump': {'kwh', 'hours', 'basis', 'pumps': […]} | None,
                 'tank': {'start_l', 'end_l', 'empty_at', 'inflow_l', 'adjust_l'} | None}],
     'caveats': ['pump-over-demand', …]}

``supply`` 는 **회로마다 한 칸**이다 — 구획 하나가 끊긴 회로 둘에 걸칠 수 있다.

저장된 날을 읽은 결과면 ``runs`` 의 각 칸에 ``stored: True`` 가 붙고 ``supply`` 에는 그날의 회로가
없다(저장하는 것은 실행별 물량과 일 합계다). ``stored_until`` 은 저장값으로 읽은 마지막 끝이고,
``live_from`` 은 **읽을 때 계산한 가장 이른 구간의 시작**이다(저장 안 된 날이 저장된 날 앞에 있으면 그 날).
전부 저장값이면 ``live_from`` 은 None 이다. ``totals`` 는 ``litres``·``design_litres``·``mm``·``seconds``·``runs``·``kwh``·``kwh_basis``
(``measured``/``rated``/None)·``pump_hours``.

## 저장 모양 (측정 ``water_run``·``water_day``)

점 하나는 값 하나라서 필드를 채널 번호로 나눈다. ``device_id`` 는 구획 id 다.

* ``water_run`` (`aot_calc`): 시각 = 켠 시각. 태그 ``output_id``·``network_rev``·``level``·``basis``·
  ``fed``(공급을 푼 회로의 실행이면 ``'1'``). 채널은 ``RUN_FIELDS`` 순서.
* ``water_day`` (`aot_hist`): 시각 = 현지 날짜 0시(UTC epoch). **닫힌 날에만** 쓴다 — 점이 있다는
  것이 '이날은 저장값으로 읽어도 된다' 는 표식이다. 태그 ``network_rev``·``level``·``basis``.
  채널은 ``DAY_FIELDS`` 순서, ``CAVEAT_BASE`` 부터는 표시마다 한 칸(초, 탱크 바닥 시각, 없으면 1).

``network_rev`` 는 계산에 쓴 회로의 해시다. 도면이 바뀌어도 과거 결과를 다시 쓰지 않으려고
남긴다. 저장 순서가 바뀌어도 같아야 하므로 id 는 넣지 않는다 — 지도 배관은 ``node_id`` 가
없으면 순번으로 이름을 짓는다(`adapters._feature_id`).
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, List, Optional, Sequence

from . import parts as part_table

LEVEL_L0 = 'L0'

BASIS_DESIGN = 'design'      # 노즐 정격 × 가동시간
BASIS_RATED = 'rated'        # kW × 가동시간
BASIS_MEASURED = 'measured'  # 전력 측정

# 작동 판정. 알리기만 하고 제어를 막지 않는다.
PUMP_OVER_DEMAND = 'pump-over-demand'
SOURCE_OVER_DEMAND = 'source-over-demand'
VALVE_WITHOUT_PUMP = 'valve-without-pump'
PUMP_DEAD_HEAD = 'pump-dead-head'
TANK_EMPTY = 'tank-empty'
# 계산 근거가 빈 자리. 값을 지어내지 않고 빈 것을 말한다.
SUPPLY_UNKNOWN = 'supply-unknown'
PUMP_STATE_UNKNOWN = 'pump-state-unknown'
TANK_LEVEL_UNKNOWN = 'tank-level-unknown'
PUMP_BEFORE_TANK = 'pump-before-tank'
DRIP_FLOW_UNKNOWN = 'drip-flow-unknown'
SUPPLY_NOT_READ = 'water-supply-not-read'
# 일지 전용 — 전달량과 설계값의 합을 접미사로 싣는다.
SUPPLY_LIMITED = 'water-supply-limited'

# ⚠ 이 순서가 저장 채널 번호다(`water_day` 의 `CAVEAT_BASE` + 순번). **뒤에만 추가하고 순서를 바꾸지 말 것** —
# 바꾸면 이미 저장된 날의 주의 표시가 다른 뜻으로 읽힌다.
CAVEATS = (
    PUMP_OVER_DEMAND, SOURCE_OVER_DEMAND, VALVE_WITHOUT_PUMP, PUMP_DEAD_HEAD, TANK_EMPTY,
    SUPPLY_UNKNOWN, PUMP_STATE_UNKNOWN, TANK_LEVEL_UNKNOWN, PUMP_BEFORE_TANK, DRIP_FLOW_UNKNOWN,
    SUPPLY_NOT_READ, SUPPLY_LIMITED,
)


M_RUN = 'water_run'
M_DAY = 'water_day'
RUN_FIELDS = ('litres', 'design_litres', 'mm', 'delivered_ratio', 'seconds', 'demand_lpm',
              'delivered_lpm')
DAY_FIELDS = ('litres', 'design_litres', 'mm', 'delivered_ratio', 'seconds', 'runs', 'fed_runs',
              'kwh', 'kwh_measured', 'pump_hours')
CAVEAT_BASE = 16
RUN_TAGS = ('output_id', 'network_rev', 'level', 'basis', 'fed')
MIXED_REV = 'mixed'


def run_row(output_id, t0, t1, demand_lpm, design_litres, ratio, area_m2=None, fed=False,
            rev='') -> dict:
    """실행 하나. ``ratio`` 는 설계 대비 전달 비율(0~1), ``fed`` 는 공급을 푼 회로의 실행인지다."""
    litres = design_litres * ratio
    return {'output_id': output_id, 't0': t0, 't1': t1, 'seconds': t1 - t0,
            'demand_lpm': round(demand_lpm, 2), 'delivered_lpm': round(demand_lpm * ratio, 2),
            'design_litres': round(design_litres, 1), 'litres': round(litres, 1),
            'delivered_ratio': round(ratio, 3),
            'mm': round(litres / area_m2, 2) if area_m2 else None,
            'ratio': ratio, 'basis': BASIS_DESIGN, 'fed': bool(fed), 'stored': False,
            'network_rev': rev or ''}


def water_result(kind, target_id, t0, t1, network_rev, runs, supply, caveats,
                 stored_until=None, tally=None, area_m2=None, live_from=None) -> dict:
    runs = list(runs)
    return {'target': {'kind': kind, 'id': target_id}, 't0': t0, 't1': t1,
            'level': LEVEL_L0, 'basis': BASIS_DESIGN, 'network_rev': network_rev,
            'runs': runs, 'supply': list(supply), 'caveats': list(caveats),
            'stored_until': stored_until, 'live_from': live_from, 'totals': totals(runs, tally, area_m2)}


def totals(runs, tally=None, area_m2=None) -> dict:
    """실행들의 합. ``mm`` 은 합친 물량 ÷ 면적이다 — 반올림한 실행별 mm 를 더하면 치우친다. 면적을 모르면 비운다."""
    runs = list(runs)
    litres = sum(r['litres'] for r in runs)
    return {'litres': round(litres, 1),
            'design_litres': round(sum(r['design_litres'] for r in runs), 1),
            'mm': round(litres / area_m2, 2) if runs and area_m2 else None,
            'seconds': round(sum(r['seconds'] for r in runs), 1), 'runs': len(runs),
            'kwh': None if tally is None or tally.kwh is None else round(tally.kwh, 3),
            'kwh_basis': None if tally is None else tally.kwh_basis(),
            'pump_hours': None if tally is None or tally.pump_hours is None
            else round(tally.pump_hours, 3)}


def run_values(row) -> dict:
    """실행 한 칸 → ``{채널: 값}``. 값이 없는 칸(면적을 모르는 ``mm``)은 뺀다."""
    out = {i: float(row[key]) for i, key in enumerate(RUN_FIELDS) if row.get(key) is not None}
    if row.get('ratio') is not None:                 # 전달 비율은 일지 값이 이것으로 곱해지므로 깎지 않는다
        out[RUN_FIELDS.index('delivered_ratio')] = float(row['ratio'])
    return out


def run_tags(row) -> dict:
    return {'output_id': str(row['output_id']), 'network_rev': row.get('network_rev') or '',
            'level': LEVEL_L0, 'basis': row.get('basis') or BASIS_DESIGN,
            'fed': '1' if row.get('fed') else '0'}


def run_from_stored(ts, tags, values) -> dict:
    """저장된 점들 → 실행 한 칸. ``values`` 는 ``{채널: 값}``."""
    row = {key: values.get(i) for i, key in enumerate(RUN_FIELDS)}
    row['ratio'] = row['delivered_ratio'] if row['delivered_ratio'] is not None else 1.0
    row['delivered_ratio'] = round(row['ratio'], 3)
    seconds = row['seconds'] or 0.0
    row.update({'output_id': tags.get('output_id'), 't0': ts, 't1': ts + seconds,
                'basis': tags.get('basis') or BASIS_DESIGN, 'stored': True,
                'fed': tags.get('fed') == '1', 'network_rev': tags.get('network_rev') or ''})
    return row


class Tally:
    """날·구간의 합 — 일지 caveat 가 읽는 것. 계산한 회로 결과와 저장된 일 합계 둘 다 받는다.

    ``seconds`` 는 표시마다 초(``valve-without-pump`` 등), ``empty_at`` 은 가장 이른 탱크 바닥 시각,
    ``codes`` 는 나온 표시 전부다.
    """

    def __init__(self):
        self.design_l = 0.0
        self.delivered_l = 0.0
        self.seconds: dict = {}
        self.codes: set = set()
        self.empty_at: Optional[float] = None
        self.kwh: Optional[float] = None
        self.pump_hours: Optional[float] = None
        self.bases: set = set()

    def kwh_basis(self) -> Optional[str]:
        """전력의 근거 — 하나로 모일 때만 낸다(측정과 정격이 섞이면 None)."""
        return next(iter(self.bases)) if len(self.bases) == 1 else None

    def add_run(self, design, delivered):
        self.design_l += design
        self.delivered_l += delivered

    def add_codes(self, codes):
        self.codes.update(codes)

    def add_solved(self, row):
        """`balance.solve` 가 낸 회로 결과 하나."""
        self.codes.update(row['caveats'])
        for code, sec in row['seconds'].items():
            self.seconds[code] = self.seconds.get(code, 0.0) + sec
        tank = row.get('tank')
        if tank and tank.get('empty_at') is not None:
            self._empty(tank['empty_at'])
        pump = row.get('pump') or {}
        if pump.get('kwh') is not None:
            self.kwh = (self.kwh or 0.0) + pump['kwh']
            self.bases.add(pump.get('basis'))
        if pump.get('hours') is not None:
            self.pump_hours = (self.pump_hours or 0.0) + pump['hours']

    def _empty(self, when):
        self.empty_at = when if self.empty_at is None else min(self.empty_at, when)

    def add_day(self, values):
        """저장된 일 합계의 ``{채널: 값}``."""
        for i, code in enumerate(CAVEATS):
            val = values.get(CAVEAT_BASE + i)
            if val is None:
                continue
            self.codes.add(code)
            if code == TANK_EMPTY:
                self._empty(val)
            elif code in _TIMED:
                self.seconds[code] = self.seconds.get(code, 0.0) + val
        kwh = values.get(DAY_FIELDS.index('kwh'))
        if kwh is not None:
            self.kwh = (self.kwh or 0.0) + kwh
            flag = values.get(DAY_FIELDS.index('kwh_measured'))
            self.bases.add(None if flag is None else BASIS_MEASURED if flag else BASIS_RATED)
        hours = values.get(DAY_FIELDS.index('pump_hours'))
        if hours is not None:
            self.pump_hours = (self.pump_hours or 0.0) + hours

    def day_values(self) -> dict:
        """저장할 표시 칸들 → ``{채널: 값}``."""
        out = {}
        for i, code in enumerate(CAVEATS):
            if code not in self.codes or code == SUPPLY_LIMITED:
                continue
            if code == TANK_EMPTY:
                out[CAVEAT_BASE + i] = float(self.empty_at) if self.empty_at is not None else 1.0
            else:
                out[CAVEAT_BASE + i] = float(self.seconds.get(code) or 1.0)
        return out


# 초로 싣는 표시. 값이 1 초여도 '표시 없음(1.0)' 과 겹치지 않게 따로 안다.
_TIMED = (PUMP_OVER_DEMAND, SOURCE_OVER_DEMAND, VALVE_WITHOUT_PUMP, PUMP_DEAD_HEAD)


def day_values(runs, tally: 'Tally', area_m2=None) -> dict:
    """닫힌 하루의 실행들 + 합 → 저장할 ``{채널: 값}``."""
    sums = totals(runs, tally, area_m2)
    out = {0: sums['litres'], 1: sums['design_litres'], 4: sums['seconds'],
           5: float(len(runs)), 6: float(sum(1 for r in runs if r.get('fed')))}
    if sums['mm'] is not None:
        out[2] = sums['mm']
    if sums['design_litres'] > 0:
        out[3] = round(sums['litres'] / sums['design_litres'], 4)
    if tally.kwh is not None:
        out[7] = round(tally.kwh, 3)
        basis = tally.kwh_basis()
        if basis is not None:
            out[8] = 1.0 if basis == BASIS_MEASURED else 0.0
    if tally.pump_hours is not None:
        out[9] = round(tally.pump_hours, 3)
    out.update(tally.day_values())
    return out


def _place(net, point) -> list:
    if net.frame is not None:
        return net.frame.to_lnglat(point)
    return [round(v, 3) for v in point]


def _ratings(part) -> dict:
    meta = part.meta if isinstance(part.meta, dict) else {}
    keys = [r.key for r in part_table.ratings_for(part.kind)]
    return {key: meta[key] for key in keys if meta.get(key) not in (None, '')}


def _device_of(net, part) -> Optional[str]:
    device = (net.part_devices.get(part.id) or {}).get('device') or {}
    return device.get('device_id')


def network_rev(net, comps: Optional[Iterable[int]] = None) -> str:
    """회로의 해시. ``comps`` 를 주면 그 덩어리만 센다. 줄 방향과 저장 순서는 영향이 없다."""
    wanted = None if comps is None else set(comps)

    def _in(ref):
        return wanted is None or net.component_id(ref) in wanted

    rows: List[list] = []
    for pipe in net.pipes:
        if _in(pipe.id):
            line = [_place(net, p) for p in pipe.line]
            rows.append(['pipe', pipe.sub_type, min(line, line[::-1])])
    for part in net.parts:
        if _in(part.id):
            rows.append(['part', part.kind, _place(net, part.point) if part.point else None,
                         _ratings(part), _device_of(net, part)])
    for em in net.emitters:
        if _in(em.id):
            rows.append(['emitter', em.kind, _place(net, em.point) if em.point else None,
                         em.flow_lph, em.count])
    text = json.dumps(sorted(rows, key=lambda r: json.dumps(r, sort_keys=True)),
                      sort_keys=True, default=str)
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]


def merge_caveats(groups: Iterable[Sequence[str]]) -> List[str]:
    """여러 회로의 표시를 하나로 — `CAVEATS` 순서."""
    seen = {code for group in groups for code in group}
    return [code for code in CAVEATS if code in seen]
