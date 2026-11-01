# coding=utf-8
"""장치 상태 출처 읽기 어댑터 — actual / duty_log / command (설계서 §5.1, 결정 4).

순수 규칙(우선순위·계단 변환)은 `aot.functions.utils.twin_effects.state`. 여기는 서버 쪽 읽기만 맡는다:

- **어떤 출처가 있는가** `sources()` — 출력 장치의 측정 채널 선언(`DeviceMeasurements`)에서 읽는다. 켜짐 이력은 단위 `s` 의
  `duration_time` 채널, 명령 기록은 단위 `percent` 채널(`duty_cycle`). **피드백(`actual`)은 지금 데이터 모델에 장치별 연결이
  없어 자동으로 찾지 못한다** — 연결이 생기면 `resolve(actual_refs=...)` 에 넘기기만 하면 우선순위가 맞게 돈다.
- **읽기** `read_duty()` — `duration_time` 사건(켠 시각에 찍힌 켜진 초)을 켜짐/꺼짐 계단으로. 명령(`percent`)과 실제 피드백은
  보통 측정 계열이라 기존 읽기 경로(`SeriesRef`)가 그대로 읽는다.

가동 이력 계열은 `SeriesRef.unit == 'duty_log'` 표식으로 나타낸다(트윈 결과 `env_twin*` 이 쓰는 표식 방식과 같다). 내장 통로는
`read_duty` 를, 원격 통로는 `GET /api/twin/state/...` 를 부른다.

@phase active
@stability experimental
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from aot.functions.utils.twin_effects import state as S

logger = logging.getLogger(__name__)

#: 구간 앞에서 켜져 걸쳐 오는 사건을 잡기 위한 여유(가장 긴 연속 가동을 6 시간으로 본다).
LOOKBACK_S = 6 * 3600.0
#: 한 번에 읽는 구간 상한 — 동기화 이력(기본 48 h)보다 넉넉히.
MAX_WINDOW_S = 10 * 86400.0


def sources(output_uuids: Iterable[str]) -> Dict[str, Dict[str, Optional[int]]]:
    """{출력 id: {'duty_log': 채널|None, 'command': 채널|None}} — 측정 채널 선언에서(Influx 를 읽지 않는다)."""
    from aot.databases.models import DeviceMeasurements
    ids = [u for u in output_uuids if u]
    out: Dict[str, Dict[str, Optional[int]]] = {u: {S.DUTY_LOG: None, S.COMMAND: None} for u in ids}
    if not ids:
        return out
    for dm in DeviceMeasurements.query.filter(DeviceMeasurements.device_id.in_(ids)).order_by(
            DeviceMeasurements.channel).all():
        rec = out[dm.device_id]
        ch = int(dm.channel or 0)
        if (dm.unit == 's' and (dm.measurement or 'duration_time') == 'duration_time') and rec[S.DUTY_LOG] is None:
            rec[S.DUTY_LOG] = ch
        elif dm.unit == 'percent' and rec[S.COMMAND] is None:
            rec[S.COMMAND] = ch
    return out


def ref_for(basis: str, uid: str, channel: int) -> Dict[str, object]:
    """상태 출처 → 트윈 설정의 계열 참조(`controls` 한 칸). 출처 표시는 모른다(계보 기록용, 판정에 쓰지 않는다)."""
    unit = S.DUTY_UNIT if basis == S.DUTY_LOG else 'percent'
    return {'unique_id': uid, 'unit': unit, 'channel': int(channel), 'provenance': 'unknown'}


def resolve(kinds: Mapping[str, Optional[str]], actual_refs: Optional[Mapping[str, Mapping]] = None,
            src: Optional[Mapping[str, Mapping]] = None) -> Dict[str, Dict[str, object]]:
    """장치마다 쓸 상태 출처 — `{id: {basis, ref, candidates}}`. `kinds` = {출력 id: 종류}."""
    src = src if src is not None else sources(kinds)
    actual_refs = actual_refs or {}
    out: Dict[str, Dict[str, object]] = {}
    for uid, kind in kinds.items():
        s = src.get(uid) or {}
        act = actual_refs.get(uid)
        basis = S.choose_basis(kind, bool(act), s.get(S.DUTY_LOG) is not None, s.get(S.COMMAND) is not None)
        if basis == S.ACTUAL:
            ref = dict(act)
        elif basis == S.DUTY_LOG:
            ref = ref_for(basis, uid, s[S.DUTY_LOG])
        elif basis == S.COMMAND:
            ref = ref_for(basis, uid, s[S.COMMAND])
        else:
            ref = None
        out[uid] = {'basis': basis, 'ref': ref,
                    'candidates': {S.ACTUAL: bool(act), S.DUTY_LOG: s.get(S.DUTY_LOG) is not None,
                                   S.COMMAND: s.get(S.COMMAND) is not None}}
    return out


def read_duty(uid: str, channel: int, window_s: float, now: Optional[float] = None
              ) -> Tuple[List[float], List[float]]:
    """가동 이력 계단 `(times, values)`(0/100 %). 읽기가 실패하면 빈 계열 — 꺼짐으로 지어내지 않는다."""
    from aot.utils.influx import read_influxdb_list
    now = time.time() if now is None else now
    window_s = min(max(1.0, float(window_s)), MAX_WINDOW_S)
    rows = read_influxdb_list(uid, 's', int(channel), measure='duration_time',
                              duration_sec=int(window_s + LOOKBACK_S))
    if rows is None:
        logger.warning('트윈 가동 이력 읽기 실패 %s ch%s', uid, channel)
        return [], []
    events = [(float(t), float(v)) for t, v in rows if v is not None]
    return S.duty_step_series(events, now - window_s, now)
