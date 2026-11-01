# coding=utf-8
"""대지의 지정 예보 시계열(`ForecastSeries`) → 트윈 모델이 쓰는 전망 외기 `t → {T_ext, RH_ext, wind, solar, …}`.

시설 모델의 전망 외기는 예보 입력이 붙기 전에는 "24 h 전 같은 시각 반복"(일주기 지속)이었다. 예보 시계열이 있으면 그 구간은
예보를 쓰고, 예보가 없거나(지정 없음·낡음) 지평 밖이거나 그 변수가 없는 곳은 **폴백(일주기 지속)** 으로 메운다 —
0 으로 채우지 않는다. 얼마나 예보로 메웠는지는 `coverage()` 가 센다(상태 코드·머리말에 쓴다).

시각 의미(서버 계약): 순간 값(temp_c·rh_pct·wind_ms·wind_dir_deg)은 행 `time`(정시) 값 — 사이는 직선 보간,
칸 값(precip_mm_h·solar_w_m2·cloud_pct·pop_pct)은 `[time, end)` 칸의 값 — 계단. 마지막 칸의 끝이 지평(`horizon`)이다.
"""
from __future__ import annotations

import bisect
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from .types import ForecastSeries

#: 모델 외기 키 ← (예보 변수, 종류). 종류 'i'=순간(보간), 'c'=칸(계단)
MAPPING: Dict[str, Tuple[str, str]] = {
    "T_ext": ("temp_c", "i"),
    "RH_ext": ("rh_pct", "i"),
    "wind": ("wind_ms", "i"),
    "solar": ("solar_w_m2", "c"),
}
REQUEST_VARIABLES = tuple(v for v, _ in MAPPING.values())


class SeriesExt:
    """`__call__(t)` → 외기 dict. 예보로 채운 항목 수를 센다."""

    def __init__(self, fs: Optional[ForecastSeries], fallback: Callable[[float], Dict[str, float]]):
        self._fb = fallback
        self.fs = fs if fs is not None and fs.available and fs.rows else None
        self._rows: List[Mapping[str, float]] = list(self.fs.rows) if self.fs else []
        self._times = [r["time"] for r in self._rows]
        self.used: Dict[str, int] = {k: 0 for k in MAPPING}
        self.calls = 0

    @property
    def horizon(self) -> Optional[float]:
        if not self._rows:
            return None
        return self.fs.horizon if self.fs.horizon is not None else self._rows[-1]["end"]

    def _instant(self, var: str, t: float) -> Optional[float]:
        i = bisect.bisect_right(self._times, t) - 1
        if i < 0:
            return None
        a = self._rows[i]
        if t >= a["end"] and i == len(self._rows) - 1:
            return None                                   # 마지막 칸의 끝 이후 = 지평 밖
        va = a.get(var)
        if va is None:
            return None
        if i + 1 < len(self._rows):
            b = self._rows[i + 1]
            vb = b.get(var)
            if vb is not None and b["time"] > a["time"]:
                w = min(1.0, max(0.0, (t - a["time"]) / (b["time"] - a["time"])))
                return va + (vb - va) * w
        return va

    def _cell(self, var: str, t: float) -> Optional[float]:
        i = bisect.bisect_right(self._times, t) - 1
        if i < 0:
            return None
        r = self._rows[i]
        if not (r["time"] <= t < r["end"]):
            return None
        return r.get(var)

    def __call__(self, t: float) -> Dict[str, float]:
        out = dict(self._fb(t))
        self.calls += 1
        if not self._rows:
            return out
        for key, (var, kind) in MAPPING.items():
            v = self._instant(var, t) if kind == "i" else self._cell(var, t)
            if v is not None:
                out[key] = v
                self.used[key] += 1
        return out

    def coverage(self) -> Dict[str, float]:
        """항목별로 호출 중 예보로 채운 비율(0~1). 호출이 없으면 빈 값."""
        if not self.calls:
            return {}
        return {k: n / self.calls for k, n in self.used.items()}
