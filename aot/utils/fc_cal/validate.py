# coding=utf-8
"""시간순 전진 검증 · 성적 지표 · 채택/되돌림 판정 (설계 §4.3).

미래 정보가 새지 않는다: 검증 시점 d 마다 **d 날 이전 대상 시각의 쌍으로만** 계수를 맞추고, d 날의 쌍을 그 계수로
평가한다. 계수는 시점마다 새로 맞추므로 쓰는 계수의 나이는 `step_days` 안이다(운영에서는 매일 새벽 다시 맞춘다).
보정 전후는 **같은 쌍**에서 비교한다. 쌍을 일(현지 날짜) 단위로 묶어 두면 개선율의 신뢰구간(일 단위 블록
부트스트랩)과 '최근 14일' 판정이 싸다.

지표: 연속 변수 MAE·RMSE·편차(예보 − 관측), 비는 Brier(발생 확률)·POD·FAR(`rain_event_mm` 문턱).
개선율(skill) = 1 − 보정 후 손실 ÷ 보정 전 손실. 손실은 연속 변수 |오차|, 비는 Brier.
"""
import math
import random
import time
import zlib
from typing import Dict, List

from .common import (DAY_S, ST_ADOPTED, ST_CANDIDATE, ST_FEW, ST_FORCED, ST_OFF, ST_REVERTED, USED_STATES,
                     Params)

_SUMS = ('n', 'ae_raw', 'ae_cal', 'se_raw', 'se_cal', 'e_raw', 'e_cal')
_RAIN_SUMS = ('br_raw', 'br_cal', 'hit_raw', 'miss_raw', 'fa_raw', 'hit_cal', 'miss_cal', 'fa_cal', 'wet')


class Timeout(Exception):
    """시간 제한을 넘겼다 — 부르는 쪽이 이 항목을 건너뛰고 이전 상태를 둔다."""


def _acc(is_rain):
    return {k: 0.0 for k in (_SUMS + _RAIN_SUMS if is_rain else _SUMS)}


def _add(acc, pr, cal, is_rain, p, kind, method, model):
    e_raw, e_cal = pr.fc - pr.ob, cal - pr.ob
    acc['n'] += 1
    acc['ae_raw'] += abs(e_raw)
    acc['ae_cal'] += abs(e_cal)
    acc['se_raw'] += e_raw * e_raw
    acc['se_cal'] += e_cal * e_cal
    acc['e_raw'] += e_raw
    acc['e_cal'] += e_cal
    if not is_rain:
        return
    thr = p.rain_thr(kind)
    y = 1.0 if pr.ob >= thr else 0.0
    p_raw = pr.aux if pr.aux is not None else (1.0 if pr.fc >= thr else 0.0)
    p_cal = method.prob(model, pr)
    acc['br_raw'] += (p_raw - y) ** 2
    acc['br_cal'] += (p_cal - y) ** 2
    acc['wet'] += y
    ev = p.rain_event_mm
    o = pr.ob >= ev
    for tag, v in (('raw', pr.fc), ('cal', cal)):
        f = v >= ev
        acc['hit_' + tag] += 1 if (o and f) else 0
        acc['miss_' + tag] += 1 if (o and not f) else 0
        acc['fa_' + tag] += 1 if (f and not o) else 0


def _loss_keys(is_rain):
    return ('br_raw', 'br_cal') if is_rain else ('ae_raw', 'ae_cal')


def forward_validate(method, pairs, now, p: Params, ctx, deadline=None):
    """전진 검증 → `{'days': {현지 날짜 번호: 합계 사전}, 'n': 평가한 쌍 수}`.

    `deadline` 은 `time.monotonic()` 기준 마감. 넘기면 `Timeout`."""
    kind = method.kind
    is_rain = method.var == 'RAIN'
    by_day: Dict[int, List] = {}
    for pr in pairs:
        by_day.setdefault(ctx.day_key(kind, pr.t), []).append(pr)
    if not by_day:
        return {'days': {}, 'n': 0}
    order = sorted(by_day)
    first = order[0]
    train: List = []
    model = None
    days: Dict[int, Dict[str, float]] = {}
    n_total = 0
    for d in order:
        off = d - first
        if off >= p.train_min_days:
            if (off - p.train_min_days) % p.step_days == 0:
                if deadline is not None and time.monotonic() > deadline:
                    raise Timeout()
                origin = min(pr.t for pr in by_day[d])
                model = method.fit(train, origin, p, ctx)
            if model is not None:
                acc = _acc(is_rain)
                for pr in by_day[d]:
                    if not method.eligible(pr, ctx):
                        continue
                    _add(acc, pr, method.apply(model, pr, ctx), is_rain, p, kind, method, model)
                if acc['n']:
                    days[d] = acc
                    n_total += int(acc['n'])
        train.extend(by_day[d])
    return {'days': days, 'n': n_total}


def _total(accs, is_rain):
    out = _acc(is_rain)
    for a in accs:
        for k in out:
            out[k] += a[k]
    return out


def _skill(raw, cal):
    return None if raw <= 0 else 1.0 - cal / raw


def metrics(acc, is_rain):
    """합계 → 성적 지표 사전(없는 값은 None)."""
    n = acc['n']
    if not n:
        return {'n': 0}
    out = {'n': int(n), 'mae_raw': acc['ae_raw'] / n, 'mae_cal': acc['ae_cal'] / n,
           'rmse_raw': math.sqrt(acc['se_raw'] / n), 'rmse_cal': math.sqrt(acc['se_cal'] / n),
           'bias_raw': acc['e_raw'] / n, 'bias_cal': acc['e_cal'] / n}
    lr, lc = _loss_keys(is_rain)
    out['skill'] = _skill(acc[lr], acc[lc])
    if is_rain:
        out['brier_raw'], out['brier_cal'] = acc['br_raw'] / n, acc['br_cal'] / n
        for tag in ('raw', 'cal'):
            h, m, f = acc['hit_' + tag], acc['miss_' + tag], acc['fa_' + tag]
            out['pod_' + tag] = h / (h + m) if h + m else None
            out['far_' + tag] = f / (h + f) if h + f else None
        out['pod'], out['far'] = out['pod_cal'], out['far_cal']
        out['wet'] = int(acc['wet'])
    return out


def skill_interval(accs: List[Dict[str, float]], is_rain, p: Params, seed=0):
    """일 단위 블록으로 본 개선율의 (하한, 상한). 일 수가 2 미만이면 (None, None).

    `p.bootstrap > 0` 이면 일을 복원 추출하는 부트스트랩, 아니면 일 군집 표준오차(저사양, `z_strict` 로 더 엄격)."""
    lr, lc = _loss_keys(is_rain)
    raw = [a[lr] for a in accs]
    cal = [a[lc] for a in accs]
    k = len(accs)
    tot_raw = sum(raw)
    if k < 2 or tot_raw <= 0:
        return None, None
    if p.bootstrap > 0:
        rng = random.Random(seed)
        vals = []
        for _ in range(p.bootstrap):
            idx = [rng.randrange(k) for _ in range(k)]
            r = sum(raw[i] for i in idx)
            c = sum(cal[i] for i in idx)
            if r > 0:
                vals.append(1.0 - c / r)
        if len(vals) < max(10, p.bootstrap // 2):
            return None, None
        vals.sort()
        lo = vals[int(len(vals) * p.ci_pct / 100.0)]
        hi = vals[min(len(vals) - 1, int(len(vals) * (100.0 - p.ci_pct) / 100.0))]
        return lo, hi
    r_hat = 1.0 - sum(cal) / tot_raw
    # 비율 추정량의 군집(일) 선형화 표준오차
    resid = [(r - c) - r_hat * r for r, c in zip(raw, cal)]
    var = sum(x * x for x in resid) * k / (k - 1) / (tot_raw * tot_raw)
    se = math.sqrt(max(var, 0.0))
    return r_hat - p.z_strict * se, r_hat + p.z_strict * se


def summarize(vres, kind, var, p: Params, seed=0):
    """전진 검증 결과 → 요약. `recent` 는 마지막 `revert_days` 일의 성적(되돌림 판정에 쓴다)."""
    is_rain = var == 'RAIN'
    days = vres['days']
    out = {'days': len(days), 'n': vres['n'], 'is_rain': is_rain}
    if not days:
        out.update(metrics={'n': 0}, ci_lo=None, ci_hi=None, recent={'n': 0, 'days': 0, 'skill': None})
        return out
    accs = [days[d] for d in sorted(days)]
    out['metrics'] = metrics(_total(accs, is_rain), is_rain)
    out['ci_lo'], out['ci_hi'] = skill_interval(accs, is_rain, p, seed)
    last = max(days)
    rec = [days[d] for d in days if d > last - p.revert_days]
    rm = metrics(_total(rec, is_rain), is_rain)
    out['recent'] = {'n': rm.get('n', 0), 'days': len(rec), 'skill': rm.get('skill'),
                     'bias_raw': rm.get('bias_raw'), 'bias_cal': rm.get('bias_cal')}
    return out


def seed_of(*parts):
    return zlib.crc32(':'.join(str(x) for x in parts).encode('utf-8'))


def decide(summ, prev_status, prev_meta, now, p: Params, kind, mode='auto', has_model=True):
    """채택 규칙 → `(상태, 이유)`. 설계 §4.3:

    - 채택: 평가 일수·표본 수 충족 + 개선율 신뢰구간 하한 > 0 (비는 사건 수와 부피 편차 조건 추가).
    - 되돌림: 쓰던 중 최근 `revert_days` 일의 개선율이 0 보다 낮으면 원본으로. 되돌린 뒤 `cooldown_days` 안에는 다시 안 쓴다.
    - 쓰던 계수는 근거가 잠시 얇아졌다는 이유만으로 내리지 않는다(최근 성적이 나쁠 때만).
    `mode`: 'auto' | 'on'(항상 켬) | 'off'(끔)."""
    if mode == 'off':
        return ST_OFF, 'mode_off'
    if not has_model:
        return ST_FEW, 'no_model'
    if mode == 'on':
        return ST_FORCED, 'mode_on'
    rec = summ['recent']
    rec_ok = rec['n'] >= max(10, p.min_eval_n(kind) // 2) and rec['days'] >= min(7, p.revert_days)
    rec_bad = rec_ok and rec['skill'] is not None and rec['skill'] < 0
    if prev_status in USED_STATES:
        return (ST_REVERTED, 'recent_worse') if rec_bad else (ST_ADOPTED, 'kept')
    enough = summ['n'] >= p.min_eval_n(kind) and summ['days'] >= p.min_days
    if summ['is_rain']:
        wet = (summ['metrics'] or {}).get('wet', 0)
        if wet < p.min_rain_events(kind):
            return ST_FEW, 'rain_events'
    if not enough:
        return ST_FEW, 'eval_samples'
    lo = summ['ci_lo']
    m = summ['metrics']
    passes = lo is not None and lo > 0 and not rec_bad
    if passes and summ['is_rain']:
        passes = abs(m['bias_cal']) <= abs(m['bias_raw']) * 1.1 + 1e-9        # 부피가 더 틀어지면 안 쓴다
    if prev_status == ST_REVERTED and passes:
        since = (prev_meta or {}).get('reverted_at')
        if since is not None and now - since < p.cooldown_days * DAY_S:
            return ST_REVERTED, 'cooldown'
    return (ST_ADOPTED, 'pass') if passes else (ST_CANDIDATE, 'not_better')
