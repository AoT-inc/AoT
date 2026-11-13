# coding=utf-8
"""표본 통계 — 중앙값·사분위 범위. 표준 라이브러리만 쓴다(numpy 불필요)."""


def quantile(values, q):
    """선형 보간 분위수(0~1). 빈 목록은 None."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def summarize(values):
    """{n, median, q1, q3, iqr, min, max}. 값이 하나도 없으면 n=0 에 나머지 None."""
    xs = [v for v in values if v is not None]
    if not xs:
        return dict(n=0, median=None, q1=None, q3=None, iqr=None, min=None, max=None)
    q1, q3 = quantile(xs, 0.25), quantile(xs, 0.75)
    return dict(n=len(xs), median=quantile(xs, 0.5), q1=q1, q3=q3,
                iqr=q3 - q1, min=min(xs), max=max(xs))


def summarize_runs(runs, keys):
    """실행 결과(dict) 목록에서 keys 각각의 요약을 낸다."""
    return {k: summarize([r.get(k) for r in runs]) for k in keys}
