# coding=utf-8
"""트윈 발행의 계보 머리말 (데이터 관리 D3, 계약 §6.3·§10.4 채널 12~14 / 27~29).

- `fc_issue_epoch` : 쓴 예보 발표본의 받은 시각(UTC epoch). 예보를 못 썼으면 칸 자체를 쓰지 않는다.
- `fc_cal_rev`     : 쓴 예보의 보정 판(0 = 원본). 보정(D5) 전에는 항상 0.
- `obs_origin`     : 동기화에 쓴 관측의 출처 코드 — 1 실측 · 2 미러 · 3 가상 · 0 미확인.
                     관측이 하나도 없으면(센서 없는 구획) 칸을 쓰지 않는다. 여러 개가 섞이면 **가장 못 믿을 것**을
                     따른다(미확인이 하나라도 있으면 0, 아니면 큰 코드).
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from .types import Provenance, SeriesRef

ORIGIN_CODE = {Provenance.MEASURED: 1, Provenance.MIRROR: 2, Provenance.VIRTUAL: 3, Provenance.UNKNOWN: 0}


def obs_origin(refs: Iterable[Optional[SeriesRef]]) -> Optional[float]:
    codes = [ORIGIN_CODE.get(r.provenance, 0) for r in refs if r is not None]
    if not codes:
        return None
    return 0.0 if 0 in codes else float(max(codes))


def forecast_meta(fetched_at, cal_rev=0) -> Dict[str, float]:
    """`ForecastSeries.fetched_at`/`cal_rev` → 머리말 항목. 받은 시각이 없으면 빈 dict."""
    if fetched_at is None:
        return {}
    return {"fc_issue_epoch": float(fetched_at), "fc_cal_rev": float(cal_rev or 0)}
