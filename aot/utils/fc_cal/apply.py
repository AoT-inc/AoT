# coding=utf-8
"""채택된 보정을 예보에 적용 — 소비자(트윈·지도·AI)가 읽는 한 곳 (설계 §4.4, D5).

L0 예보 값 + 쓰는 판의 계수 → 보정값. 계수는 **원본에서 보정값을 만드는 식**이라 같은 계수와 같은 L0 가 있으면 언제나
같은 값이 나온다(`methods.method_for(...).apply`). 이 모듈은 DB·Influx·Flask 를 모른다 — `Calibrator` 에 계수 사전만
넘기면 되고, 읽기·캐시는 `forecast_series`, L2 쓰기는 `l2` 가 맡는다.

적용 규칙
- 층은 (종류, 변수, 리드대)다. 쓰는 항목(`adopted`·`forced` 이고 계수 있음)만 적용한다. 그 밖(후보·되돌림·표본 부족·관측
  없음·끔)은 원본이다.
- 시간별: 순간 값(기온·습도·풍속)은 칸 시작 정시와 그 리드, 칸 값(일사·강수)은 칸 끝 정시와 그 리드로 쌍을 만든다 —
  `fc_hourly` 의 한 행(대상 정시 + `lead_h`)과 같은 뜻이다. 습도는 보정한 기온으로 다시 계산한다.
- 일별: 대상일(현지 날짜 번호)과 발표일의 차이가 리드(일)다. 하루 최고·최저는 서로 뒤집히지 않게 한다.
- 시간별 시간열을 일 값으로 접은 날(일별 입력이 없을 때)은 접기 전에 보정하므로 일 최고·최저·합이 보정한 시간열에서 다시
  나온다.
"""
import math
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .common import (BANDS, DAY_S, HOUR_S, KIND_D, KIND_H, USED_STATES, Ctx, Pair, band_of)
from .methods import method_for

#: 응답 변수 이름 → (보정 변수, 종류) — 시간 칸(`forecast_series.VARIABLES`). inst = 순간 값(칸 시작), cell = 칸 값(칸 끝).
HOURLY_MAP = {
    'temp_c': ('T', 'inst'),
    'rh_pct': ('RH', 'inst'),
    'wind_ms': ('WS', 'inst'),
    'solar_w_m2': ('SOL', 'cell'),
    'precip_mm_h': ('RAIN', 'cell'),
}
#: 일 행 변수 이름 → 일별 보정 변수
DAILY_MAP = {'temp_max_c': 'TMAX', 'temp_min_c': 'TMIN', 'precip_mm': 'RAIN'}

#: 보정 변수 → 사람이 읽는 말(농가용). 번역은 화면이 한다.
VAR_NAMES = {'T': 'Temperature', 'RH': 'Humidity', 'WS': 'Wind speed', 'SOL': 'Sunlight', 'RAIN': 'Rain',
             'TMAX': 'Daily high', 'TMIN': 'Daily low'}

SCOPE_USED = 'used'              # 채택(또는 항상 켬)된 항목만
SCOPE_ALL = 'all'                # 계수가 있는 항목 전부(채택 여부 무관) — 'corrected' 층


def models_of(entries: Mapping, scope: str = SCOPE_USED) -> Dict[Tuple[str, str, str], dict]:
    """판 항목 → 적용할 계수 `{(kind, var, band): 계수}`. `entries` 는 `store.entries_of_rev` 모양."""
    out = {}
    for key, e in (entries or {}).items():
        coef = e.get('coef')
        if not coef:
            continue
        if scope == SCOPE_USED and e.get('status') not in USED_STATES:
            continue
        if e.get('status') == 'off':
            continue
        out[key] = coef
    return out


def _lead(t, base):
    return int(round((t - base) / HOUR_S))


class Calibrator:
    """한 대지의 계수 묶음으로 값을 고친다. 변하지 않는 객체 — 같은 입력이면 같은 출력."""

    def __init__(self, models: Mapping, ctx: Ctx, rev: int = 0):
        self.models = dict(models or {})
        self.ctx = ctx
        self.rev = int(rev or 0)

    def __bool__(self):
        return bool(self.models)

    def uses(self, kind, var) -> bool:
        return any(k[0] == kind and k[1] == var for k in self.models)

    def variables(self, kind=None) -> List[str]:
        """계수가 하나라도 있는 변수(순서 고정)."""
        seen = []
        for k in self.models:
            if (kind is None or k[0] == kind) and k[1] not in seen:
                seen.append(k[1])
        order = ['T', 'RH', 'WS', 'SOL', 'RAIN', 'TMAX', 'TMIN']
        return sorted(seen, key=lambda v: order.index(v) if v in order else 99)

    def value(self, kind, var, t, lead, fc, aux=None, t_cal=None):
        """예보 값 하나 → 보정값. 해당 리드대에 쓰는 계수가 없으면 원본 그대로."""
        model = self.models.get((kind, var, band_of(kind, lead)))
        if model is None or fc is None:
            return fc
        out = method_for(kind, var).apply(model, Pair(t, lead, fc, None, aux), self.ctx, t_cal)
        if out is None or not math.isfinite(out):
            return fc
        return out

    # ── 시간별 ────────────────────────────────────────────────────────────

    def hourly_cells(self, cells: Iterable[Mapping], base: float):
        """시간 칸 목록 → (보정한 칸 목록, 바뀐 변수 집합). 칸마다 바뀐 변수의 원본은 `raw` 에 둔다.

        `base` = 발표 기준 정시(epoch). 바뀐 칸이 없으면 같은 칸을 그대로 돌려준다(복사하지 않는다)."""
        out, changed = [], set()
        for c in cells:
            raw = {}
            new = None
            t_cal = None
            for name in ('temp_c', 'rh_pct', 'wind_ms', 'solar_w_m2', 'precip_mm_h'):
                var, mode = HOURLY_MAP[name]
                v = c.get(name)
                if v is None or not self.uses(KIND_H, var):
                    continue
                t = c['time'] if mode == 'inst' else c['end']
                lead = _lead(t, base)
                aux = None
                tc = None
                if var == 'RH':
                    ft = c.get('temp_c')                       # 적용에는 예보 기온만 쓴다(둘째 칸은 관측용 자리)
                    aux = (ft, ft)
                    tc = t_cal
                elif var == 'RAIN':
                    pop = c.get('pop_pct')
                    aux = None if pop is None else max(0.0, min(1.0, pop / 100.0))
                nv = self.value(KIND_H, var, t, lead, v, aux, tc)
                if var == 'T':
                    t_cal = nv
                if var in ('RH', 'WS'):
                    nv = max(0.0, nv)
                if nv is not None and abs(nv - v) > 1e-9:
                    new = new if new is not None else dict(c)
                    new[name] = nv
                    raw[name] = v
                    changed.add(var)
            if new is None:
                out.append(c)
            else:
                new['raw'] = raw
                out.append(new)
        return out, changed

    # ── 일별 ──────────────────────────────────────────────────────────────

    def daily_days(self, days: Mapping[int, Mapping], issue_day: int):
        """일 행 `{일 번호: {변수: 값}}` → (보정한 일 행, `{일 번호: {변수: 원본}}`, 바뀐 변수 집합).

        `issue_day` = 발표일의 일 번호(대지 현지 날짜). 리드(일) = 일 번호 − 발표일."""
        out, raws, changed = {}, {}, set()
        for d, row in days.items():
            lead = int(d) - int(issue_day)
            t = float(d) * DAY_S
            new = dict(row)
            raw = {}
            pop = row.get('pop_pct')
            for name, var in DAILY_MAP.items():
                v = row.get(name)
                if v is None or not self.uses(KIND_D, var):
                    continue
                aux = None
                if var == 'RAIN':
                    aux = None if pop is None else max(0.0, min(1.0, pop / 100.0))
                nv = self.value(KIND_D, var, t, lead, v, aux)
                if nv is not None and abs(nv - v) > 1e-9:
                    new[name] = nv
                    raw[name] = v
                    changed.add(var)
            hi, lo = new.get('temp_max_c'), new.get('temp_min_c')
            if hi is not None and lo is not None and hi < lo:
                mid = 0.5 * (hi + lo)                     # 최고가 최저 아래로 내려가지 않게
                for name in ('temp_max_c', 'temp_min_c'):
                    if abs(mid - row[name]) > 1e-9:
                        raw.setdefault(name, row[name])
                    new[name] = mid
            out[d] = new
            if raw:
                raws[d] = raw
        return out, raws, changed


def band_summary(models: Mapping, kind: str, var: str) -> List[str]:
    """변수에서 보정을 쓰는 리드대(순서 고정)."""
    return [b for b in BANDS[kind] if (kind, var, b) in models]
