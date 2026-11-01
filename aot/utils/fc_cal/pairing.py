# coding=utf-8
"""짝짓기 — (예보 L0, 리드·대상 시각) ↔ (현장 관측, 같은 시각) (설계 §4.1). 순수 계산.

시각 규칙은 L0·L1 과 같다.

- 순간값 변수(T·RH·WS): 대상 정시의 값. 관측은 시간 평균(창 = 직전 1시간, 끝 시각 표기)이라 정시 `t` 의 순간값을
  `t` 앞뒤 두 창 평균의 평균으로 어림한다(창 중심이 `t - 30분`·`t + 30분` 이라 가운데가 `t`).
- 칸 값 변수(SOL·RAIN): 칸 끝 정시. 관측은 같은 끝 시각의 창 값(평균 W/m², 비는 mm/h 의 시간 평균 = 그 시간 mm).
- 일별: 대상일(현지 날짜) 하루. 관측은 시간 값에서 현지 날짜별로 모은다(최고·최저·합). 빠진 시간이 많은 날은 쓰지 않는다.
"""
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .common import HOUR_S, Pair

MIN_HOURS_PER_DAY = 20


def inst_at(end_means: Mapping[float, float], t: float) -> Optional[float]:
    """창 평균(끝 시각 표기) → 정시 `t` 의 순간값 어림. 앞뒤 창이 모두 있어야 한다."""
    a, b = end_means.get(t), end_means.get(t + HOUR_S)
    if a is None or b is None:
        return None
    return 0.5 * (a + b)


def hourly_pairs(var, fc_rows: Iterable[Tuple[float, int, float]], obs: Mapping[float, float],
                 aux_fc: Optional[Mapping[Tuple[float, int], float]] = None,
                 obs_aux: Optional[Mapping[float, float]] = None) -> List[Pair]:
    """시간별 한 변수의 쌍.

    fc_rows : [(대상 정시 epoch, 리드 시간, 예보값)]    obs : {창 끝 정시 epoch: 창 평균}
    aux_fc  : RH → {(대상, 리드): 예보 기온} · RAIN → {(대상, 리드): 강수확률 0~1}
    obs_aux : RH → {창 끝 정시: 관측 기온 창 평균}
    """
    inst = var in ('T', 'RH', 'WS')
    out = []
    for t, lead, v in fc_rows:
        ob = inst_at(obs, t) if inst else obs.get(t)
        if ob is None:
            continue
        if var == 'RH':
            ob_t = inst_at(obs_aux or {}, t)
            fc_t = (aux_fc or {}).get((t, lead))
            out.append(Pair(t, lead, v, ob, (fc_t, ob_t)))
        elif var == 'RAIN':
            out.append(Pair(t, lead, v, ob, (aux_fc or {}).get((t, lead))))
        else:
            out.append(Pair(t, lead, v, ob, None))
    return out


def _day_epoch(ordinal):
    d = date.fromordinal(ordinal)
    return float(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()))


def daily_from_hourly(end_values: Mapping[float, float], fn, ctx, min_hours=MIN_HOURS_PER_DAY) -> Dict[float, float]:
    """시간 값(창 끝 시각 표기) → {대상일 00:00 UTC epoch: 하루 값}. 현지 날짜로 묶고 시간이 모자란 날은 뺀다.

    fn : max · min · sum"""
    by_day: Dict[int, List[float]] = {}
    for t, v in end_values.items():
        by_day.setdefault(ctx.local_end(t)[0], []).append(v)
    return {_day_epoch(o): fn(vals) for o, vals in by_day.items() if len(vals) >= min_hours}


def daily_pairs(var, fc_rows: Iterable[Tuple[float, int, float]], obs: Mapping[float, float],
                aux_fc: Optional[Mapping[Tuple[float, int], float]] = None) -> List[Pair]:
    """일별 한 변수의 쌍.  fc_rows : [(대상일 00:00 UTC epoch, 리드 일, 예보값)]  obs : {대상일 epoch: 하루 값}"""
    out = []
    for t, lead, v in fc_rows:
        ob = obs.get(t)
        if ob is None:
            continue
        out.append(Pair(t, lead, v, ob, (aux_fc or {}).get((t, lead)) if var == 'RAIN' else None))
    return out


def split_bands(kind, pairs: Iterable[Pair]) -> Dict[str, List[Pair]]:
    from .common import band_of
    out: Dict[str, List[Pair]] = {}
    for pr in pairs:
        out.setdefault(band_of(kind, pr.lead), []).append(pr)
    return out
