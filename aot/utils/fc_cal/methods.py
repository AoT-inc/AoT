# coding=utf-8
"""변수별 보정 방법 — 단순하고 설명할 수 있는 것만 (설계 §4.2).

방법마다 `fit(pairs, now, p, ctx) → 계수(JSON 로 저장되는 사전) | None` 와 `apply(model, pair, ctx) → 보정값` 이 있다.
계수는 층(시각대·계절)별로 세 단계 — `tod|계절` → `tod` → '' — 로 두고, 표본이 모자란 층은 한 단계 거친 층으로
물러난다. 계수는 모두 **원본에서 보정값을 만드는 식**이라, 계수와 L0 가 있으면 L2 를 정확히 다시 만들 수 있다.

| 변수 | 방법 | 계수 |
|---|---|---|
| T · TMAX · TMIN | 가산 편차(지수 가중 평균 + 0 쪽 수축) | `b` (°C) |
| RH | **이슬점** 편차 보정 후 보정 기온으로 RH 재계산 | `b` (°C, 이슬점) |
| WS | 로그 비 평균(곱셈), [0.5, 2] | `g` = ln 배율 |
| SOL | 맑은 하늘 대비 지수 kt 의 비율(낮만), [0.5, 1.5] | `g` = ln 배율 |
| RAIN | ① 발생 확률 단조(isotonic) 보정 ② 비 온 쌍의 양 분위 맞춤(모자라면 곱셈 비율) | `iso`·`amt` |
"""
import math
from typing import Dict, List, Optional

from .common import (KIND_D, KIND_H, Pair, age_weight, clear_sky_ghi, dew_point_c, rh_from_dew)

WS_EPS = 0.5
WS_RANGE = (0.5, 2.0)
SOL_RANGE = (0.5, 1.5)
SOL_MIN_CLEAR = 50.0            # 맑은 하늘 일사가 이보다 낮은 시각(밤·새벽)은 비율에 쓰지 않는다


class _Acc:
    __slots__ = ('n', 'sw', 'sw2', 's1', 's2')

    def __init__(self):
        self.n, self.sw, self.sw2, self.s1, self.s2 = 0, 0.0, 0.0, 0.0, 0.0

    @property
    def n_eff(self):
        return self.sw * self.sw / self.sw2 if self.sw2 > 0 else 0.0


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


class _StrataMethod:
    """층별 '가중 평균 한 값' 계열(가산·로그 비 같은)의 공통 틀."""
    name = ''
    unit_tol = 0.0          # 계수가 이만큼 바뀌어야 새 판으로 본다

    def __init__(self, kind, var):
        self.kind, self.var = kind, var

    # 하위 클래스가 채운다
    def contrib(self, pr: Pair, ctx):                       # → (c1, c2) | None
        raise NotImplementedError

    def finalize(self, acc: _Acc, p):                       # → {'b' 또는 'g': 값}
        raise NotImplementedError

    def apply_coef(self, coef, pr: Pair, ctx, t_cal=None):
        raise NotImplementedError

    coef_key = 'b'

    def eligible(self, pr: Pair, ctx) -> bool:
        return self.contrib(pr, ctx) is not None

    def fit(self, pairs, now, p, ctx) -> Optional[Dict]:
        stats: Dict[str, _Acc] = {}
        for pr in pairs:
            c = self.contrib(pr, ctx)
            if c is None:
                continue
            w = age_weight(now, pr.t, p.half_life_days)
            for key in ctx.stratum(self.kind, pr.t):
                a = stats.get(key)
                if a is None:
                    a = stats[key] = _Acc()
                a.n += 1
                a.sw += w
                a.sw2 += w * w
                a.s1 += w * c[0]
                a.s2 += w * c[1]
        strata = {}
        for key, a in stats.items():
            if a.n < p.min_n(self.kind):
                continue
            coef = self.finalize(a, p)
            coef.update(n=a.n, ne=round(a.n_eff, 2))
            strata[key] = coef
        if '' not in strata:
            return None
        return {'method': self.name, 'strata': strata}

    def apply(self, model, pr: Pair, ctx, t_cal=None):
        st = model['strata']
        for key in ctx.stratum(self.kind, pr.t):
            if key in st:
                return self.apply_coef(st[key], pr, ctx, t_cal)
        return pr.fc

    def material_change(self, a, b) -> bool:
        if not a or not b:
            return a != b
        sa, sb = a['strata'], b['strata']
        if set(sa) != set(sb):
            return True
        return any(abs(sa[k][self.coef_key] - sb[k][self.coef_key]) > self.unit_tol for k in sa)


class Additive(_StrataMethod):
    """기온(시간별·일 최고·최저): 가산 편차."""
    name = 'additive'
    coef_key = 'b'
    unit_tol = 0.15

    def contrib(self, pr, ctx):
        return (pr.ob - pr.fc, 0.0)

    def finalize(self, a, p):
        mean = a.s1 / a.sw
        return {'b': round(mean * a.n_eff / (a.n_eff + p.shrink_k), 4)}

    def apply_coef(self, coef, pr, ctx, t_cal=None):
        return pr.fc + coef['b']


class DewPoint(_StrataMethod):
    """습도: 이슬점 편차를 보정하고 보정 기온으로 RH 를 다시 계산한다(RH·VPD 가 물리적으로 맞는다)."""
    name = 'dew_point'
    coef_key = 'b'
    unit_tol = 0.15

    @staticmethod
    def _temps(pr):
        aux = pr.aux
        if not aux or aux[0] is None or aux[1] is None:
            return None
        return aux

    def contrib(self, pr, ctx):
        aux = self._temps(pr)
        if aux is None:
            return None
        return (dew_point_c(aux[1], pr.ob) - dew_point_c(aux[0], pr.fc), 0.0)

    def finalize(self, a, p):
        mean = a.s1 / a.sw
        return {'b': round(mean * a.n_eff / (a.n_eff + p.shrink_k), 4)}

    def apply_coef(self, coef, pr, ctx, t_cal=None):
        aux = self._temps(pr)
        if aux is None:
            return pr.fc
        td = dew_point_c(aux[0], pr.fc) + coef['b']
        return rh_from_dew(aux[0] if t_cal is None else t_cal, td)


class LogRatio(_StrataMethod):
    """풍속: 로그 비 평균(곱셈). 0 근처 값은 `WS_EPS` 를 더해 다룬다."""
    name = 'log_ratio'
    coef_key = 'g'
    unit_tol = 0.03

    def contrib(self, pr, ctx):
        return (math.log((pr.ob + WS_EPS) / (pr.fc + WS_EPS)), 0.0)

    def finalize(self, a, p):
        g = a.s1 / a.sw * a.n_eff / (a.n_eff + p.shrink_k)
        return {'g': round(_clamp(g, math.log(WS_RANGE[0]), math.log(WS_RANGE[1])), 4)}

    def apply_coef(self, coef, pr, ctx, t_cal=None):
        return max(0.0, (pr.fc + WS_EPS) * math.exp(coef['g']) - WS_EPS)


class ClearSkyRatio(_StrataMethod):
    """일사: 맑은 하늘 대비 지수 kt 의 비율(낮만). 일사계가 없으면 부르지 않는다(원본)."""
    name = 'kt_ratio'
    coef_key = 'g'
    unit_tol = 0.03

    @staticmethod
    def _cs(pr, ctx):
        if ctx.lat is None or ctx.lon is None:
            return 0.0
        return clear_sky_ghi(ctx.lat, ctx.lon, pr.t - 1800.0)      # 칸 값은 끝나는 정시 — 구간 한가운데

    def contrib(self, pr, ctx):
        cs = self._cs(pr, ctx)
        if cs < SOL_MIN_CLEAR:
            return None
        return (pr.ob / cs, pr.fc / cs)

    def finalize(self, a, p):
        if a.s2 <= 0 or a.s1 <= 0:
            return {'g': 0.0}
        g = math.log(a.s1 / a.s2) * a.n_eff / (a.n_eff + p.shrink_k)
        return {'g': round(_clamp(g, math.log(SOL_RANGE[0]), math.log(SOL_RANGE[1])), 4)}

    def apply_coef(self, coef, pr, ctx, t_cal=None):
        if pr.fc <= 0:
            return 0.0
        out = pr.fc * math.exp(coef['g'])
        cs = self._cs(pr, ctx)
        return min(out, max(pr.fc, cs * 1.05)) if cs > 0 else out


# ── 비 ────────────────────────────────────────────────────────────────────

def _rain_score(fc, pop, thr):
    """발생 점수 0~1 — 예보 양과 강수확률에 단조 증가."""
    s = min(1.0, max(0.0, fc) / (4.0 * thr))
    return s if pop is None else max(s, min(1.0, max(0.0, pop)))


def _pav(points):
    """가중 단조 회귀(PAV). points = [(점수, 발생 0/1, 가중)] → [[점수 상한, 확률], …] 오름차순.
    같은 점수는 먼저 하나로 묶는다."""
    merged: Dict[float, List[float]] = {}
    for s, y, w in points:
        m = merged.setdefault(s, [0.0, 0.0])
        m[0] += w * y
        m[1] += w
    blocks = []
    for s in sorted(merged):
        swy, sw = merged[s]
        blocks.append([swy, sw, s])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b = blocks.pop()
            blocks[-1][0] += b[0]
            blocks[-1][1] += b[1]
            blocks[-1][2] = b[2]
    return [[round(b[2], 4), round(b[0] / b[1], 4)] for b in blocks]


def _iso_at(iso, s):
    for upper, p in iso:
        if s <= upper:
            return p
    return iso[-1][1]


def _wquantile(values, weights, q):
    pairs = sorted(zip(values, weights))
    total = sum(w for _v, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


class Rain:
    """비: ① 발생 확률(isotonic) ② 양(비 온 쌍의 분위 맞춤, 모자라면 곱셈 비율).

    보정값 = 예보 양이 문턱 이상인데 보정 발생 확률이 `rain_p_cut` 보다 낮으면 0, 아니면 양을 맞춘 값.
    문턱 아래 예보(비 없음)는 건드리지 않는다 — 없던 비를 만들어 내지 않는다.
    """
    name = 'rain'
    QS = (0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9)

    def __init__(self, kind, var='RAIN'):
        self.kind, self.var = kind, var

    def eligible(self, pr, ctx):
        return True

    def fit(self, pairs, now, p, ctx) -> Optional[Dict]:
        thr = p.rain_thr(self.kind)
        pts, wet_fc, wet_ob, wet_w = [], [], [], []
        events = 0
        for pr in pairs:
            w = age_weight(now, pr.t, p.half_life_days)
            pop = pr.aux
            y = 1.0 if pr.ob >= thr else 0.0
            events += int(y)
            pts.append((_rain_score(pr.fc, pop, thr), y, w))
            if pr.fc >= thr and pr.ob >= thr:
                wet_fc.append(pr.fc)
                wet_ob.append(pr.ob)
                wet_w.append(w)
        if len(pts) < p.min_n(self.kind) or events < 3:
            return None
        iso = _pav(pts)
        n_wet = len(wet_fc)
        if n_wet >= p.rain_wet_min:
            q_pts, last = [], None
            for q in self.QS:
                x, y = _wquantile(wet_fc, wet_w, q), _wquantile(wet_ob, wet_w, q)
                if last is None or x > last:
                    q_pts.append([round(x, 4), round(y, 4)])
                    last = x
            sh = n_wet / (n_wet + p.rain_shrink_k)
            amt = {'q': q_pts, 'sh': round(sh, 3)}
        elif n_wet:
            sw = sum(wet_w)
            sw2 = sum(w * w for w in wet_w)
            ne = sw * sw / sw2
            r = sum(w * o for w, o in zip(wet_w, wet_ob)) / max(1e-9, sum(w * f for w, f in zip(wet_w, wet_fc)))
            g = math.log(max(1e-6, r)) * ne / (ne + p.rain_shrink_k)
            amt = {'ratio': round(math.exp(_clamp(g, math.log(0.5), math.log(2.0))), 4)}
        else:
            amt = {'ratio': 1.0}
        return {'method': self.name, 'thr': thr, 'p_cut': p.rain_p_cut, 'iso': iso, 'amt': amt,
                'n': len(pts), 'n_wet': n_wet, 'events': events}

    @staticmethod
    def _amount(amt, fc):
        if 'ratio' in amt:
            return fc * amt['ratio']
        q = amt['q']
        if fc <= q[0][0]:
            mapped = fc * (q[0][1] / q[0][0]) if q[0][0] > 0 else fc
        elif fc >= q[-1][0]:
            mapped = fc * (q[-1][1] / q[-1][0]) if q[-1][0] > 0 else fc
        else:
            mapped = fc
            for (x0, y0), (x1, y1) in zip(q, q[1:]):
                if x0 <= fc <= x1:
                    mapped = y0 + (y1 - y0) * (fc - x0) / (x1 - x0)
                    break
        return fc + amt.get('sh', 1.0) * (mapped - fc)

    def prob(self, model, pr: Pair):
        """보정한 발생 확률(문턱 이상 비가 올 확률)."""
        return _iso_at(model['iso'], _rain_score(pr.fc, pr.aux, model['thr']))

    def apply(self, model, pr: Pair, ctx, t_cal=None):
        thr = model['thr']
        if pr.fc < thr:
            return pr.fc
        if self.prob(model, pr) < model['p_cut']:
            return 0.0
        return max(0.0, self._amount(model['amt'], pr.fc))

    def material_change(self, a, b) -> bool:
        if not a or not b:
            return a != b
        if any(abs(_iso_at(a['iso'], s / 10.0) - _iso_at(b['iso'], s / 10.0)) > 0.1 for s in range(11)):
            return True
        thr = a['thr']
        for k in (1, 3, 10, 30):
            x = thr * k
            ya, yb = self._amount(a['amt'], x), self._amount(b['amt'], x)
            if abs(ya - yb) > 0.1 * max(ya, yb, 1e-9):
                return True
        return False


def method_for(kind, var):
    """(종류, 변수) → 방법 객체."""
    if var == 'RAIN':
        return Rain(kind)
    if kind == KIND_H:
        if var == 'T':
            return Additive(kind, var)
        if var == 'RH':
            return DewPoint(kind, var)
        if var == 'WS':
            return LogRatio(kind, var)
        if var == 'SOL':
            return ClearSkyRatio(kind, var)
    if kind == KIND_D and var in ('TMAX', 'TMIN'):
        return Additive(kind, var)
    raise KeyError('보정하지 않는 변수: %s/%s' % (kind, var))
