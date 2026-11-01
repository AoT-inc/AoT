# coding=utf-8
"""읽는 쪽 규칙 (계약 §7-4, §8) — 머리말을 먼저 읽고, 유효할 때만 곡선을 읽는다.
화면·MCP 가 같은 규칙을 쓰도록 참조 구현을 둔다(시험·왕복 검증에도 쓴다)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .expiry import is_expired
from .interfaces import TwinSource
from .output import META_MEASUREMENT
from .types import SeriesRef, Status, TargetKind


@dataclass
class LatestMeta:
    t0: float
    status: Status
    valid_until: float


def read_latest_meta(source: TwinSource, kind: TargetKind, device_id: str, now: float,
                     window_s: float = 3 * 86400.0) -> Optional[LatestMeta]:
    """가장 최근 머리말 한 점. 없으면 None."""
    meas, table = META_MEASUREMENT[kind]
    ch_status, ch_valid = table["status"], table["valid_until"]
    st = source.read_series(SeriesRef(device_id, meas, ch_status), window_s, now)
    va = source.read_series(SeriesRef(device_id, meas, ch_valid), window_s, now)
    if not len(st) or not len(va):
        return None
    t0 = st.times[-1]
    vmap = dict(zip(va.times, va.values))
    if t0 not in vmap:
        return None
    return LatestMeta(t0, Status(int(st.values[-1])), vmap[t0])


def usable_meta(source: TwinSource, kind: TargetKind, device_id: str, now: float) -> Optional[LatestMeta]:
    """곡선을 읽어도 되는 머리말만 돌려준다. 만료·status ≥ 2 면 None (= 트윈 없음으로 취급)."""
    m = read_latest_meta(source, kind, device_id, now)
    if m is None or is_expired(m.valid_until, now) or int(m.status) >= int(Status.UNSYNCED):
        return None
    return m
