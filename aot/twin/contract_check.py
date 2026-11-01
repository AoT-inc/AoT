# coding=utf-8
"""트윈 출력 계약 검사기 (계약 docs/design/digital-twin.md §6·§7·§10.4).

노드가 내는 점들이 계약(측정 이름·채널·태그·값·발행 유효기한)에 맞는지 거른다. 원래는 서버 수신 API
(`POST /api/twin/ingest`, `aot/utils/twin_ingest.py`)의 검증이었다. 옛 NAS→개발서버 경로와 함께 수신 API 를
걷어 낸 뒤(2026-10-24, 계획서 §9.19) 지금은 노드 출력의 계약 시험과 원격 싱크의 가짜 서버(`tests/fakes.FakeAoT`)가
쓴다. 원격 노드를 다시 설계할 때(배포 제안 §2, S6) 받는 쪽 검증으로 다시 쓸 수 있게 패키지에 둔다. 순수 함수라
flask·DB·Influx 를 모른다. 채널 번호표는 `aot.twin.output` 이 정본이다.

거르는 것
1. **측정 이름**: `env_twin*` 일곱 개만. 그 밖은 거부(트윈 키로 다른 계열을 덮어쓰지 못하게).
2. **채널·태그**: 측정마다 계약 표에 있는 채널만, 태그는 `facility`·`target`·`lead_h`·`lead_d`
   만(값도 표 안에서). 모르는 태그는 계열 수를 늘리므로 거부한다.
3. **값·시각**: 유한한 수, 확률 채널은 0~1, `status` 는 정해진 코드. 시각은 지금 기준 앞뒤 창 안.
4. **발행(publication) 단위의 유효기한**(원칙 1, 계약 §7): 곡선 점은 같은 대상의 발행 머리말
   (`pubs` 또는 같은 요청의 `*_meta` 점)과 짝이 맞아야 한다.
   - `valid_until < t0` 이거나 `valid_until − t0` 이 계약 상한을 넘으면 그 발행 전체를 거부.
   - `status < 2` 인데 이미 `now > valid_until` 이면 **늦게 도착한 발행**이다. `env_twin`
     곡선은 같은 대상 시각을 덮어쓰므로(계약 §6.1) 늦은 발행이 새 곡선을 덮지 않게 통째로 거부.
   - `status ≥ 2` 발행은 곡선이 없어야 한다(계약 §7-3). 머리말만 받는다(즉시 만료가 정상).
   - 곡선 시각은 `t0` ~ `t0 + 지평` 안, 머리말 시각은 `t0` 와 같아야 한다.

원격 노드의 쓰기는 2,000 점 단위로 쪼개 보내므로 머리말이 마지막 조각에만 있다(머리말은 곡선이
다 쓰인 뒤에 보여야 한다, `aot.twin.output.flatten`). 그래서 노드는 요청마다 `pubs` 요약을
함께 싣는다 — 검증에만 쓰고 Influx 에는 쓰지 않는다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from aot.twin import output as O
from aot.twin.types import Status

MAX_POINTS_PER_REQUEST = 5000

#: 측정 → (가족, 역할). 가족은 발행 머리말을 공유하는 묶음이다.
_FAC, _FLD = 'facility', 'field'
MEASUREMENTS: Dict[str, Tuple[str, str]] = {
    O.M_FAC: (_FAC, 'curve'), O.M_FAC_LEAD: (_FAC, 'lead'), O.M_FAC_META: (_FAC, 'meta'),
    O.M_FLD: (_FLD, 'curve'), O.M_FLD_H: (_FLD, 'curve_h'), O.M_FLD_LEAD: (_FLD, 'lead'),
    O.M_FLD_META: (_FLD, 'meta'),
}
META_OF = {_FAC: O.M_FAC_META, _FLD: O.M_FLD_META}

#: 유효기한 상한(`valid_until − t0`). 시설은 `2 × 주기`(주기 최대 12 h), 노지 일 격자는 36 h·
#: 시 격자는 `3 × 주기`(최대 6 h) — 계약 §7·§10.3. 여유를 조금 둔다.
MAX_VALID_S = {_FAC: 24 * 3600.0, _FLD: 48 * 3600.0}
#: 곡선 시각 상한(`ts − t0`). 시설 +48 h, 노지 일 격자 +14 일·시 격자 +72 h.
MAX_HORIZON_S = {(_FAC, 'curve'): 48 * 3600.0, (_FAC, 'lead'): 48 * 3600.0,
                 (_FLD, 'curve'): 14 * 86400.0, (_FLD, 'lead'): 14 * 86400.0,
                 (_FLD, 'curve_h'): 72 * 3600.0}
#: 발행 시각 `t0` 창: 너무 옛날(재전송 사고)·미래(시계 어긋남)는 거부.
T0_PAST_S = 3 * 86400.0
T0_FUTURE_S = 600.0

STATUS_CODES = frozenset(int(s) for s in Status)
_UNSYNCED = int(Status.UNSYNCED)

_ID_RE = re.compile(r'^[A-Za-z0-9_.:\-]{1,64}$')
_FACILITY_RE = re.compile(r'^[0-9a-fA-F\-]{1,36}$')


def _trio(bases: Iterable[int]) -> set:
    return {b + i for b in bases for i in (0, 1, 2)}


def _channels() -> Dict[str, Tuple[frozenset, frozenset]]:
    """측정 → (허용 채널, 확률 채널)."""
    fac_ev = set(O.FACILITY_EVENTS.values())
    fac = _trio(O.FACILITY_Q.values()) | fac_ev
    fld_ev = set(O.FIELD_DAILY_EVENTS.values())
    fld = _trio(O.FIELD_DAILY_Q.values()) | set(O.FIELD_DAILY_P50_ONLY.values()) | fld_ev
    fld_h_ev = set(O.FIELD_HOURLY_EVENTS.values())
    fld_h = _trio(O.FIELD_HOURLY_Q.values()) | set(O.FIELD_HOURLY_P50_ONLY.values()) | fld_h_ev
    fld_lead = _trio(O.FIELD_LEAD_Q_BASES) | fld_ev
    return {
        O.M_FAC: (frozenset(fac), frozenset(fac_ev)),
        O.M_FAC_LEAD: (frozenset(fac), frozenset(fac_ev)),
        O.M_FAC_META: (frozenset(O.FACILITY_META.values()), frozenset()),
        O.M_FLD: (frozenset(fld), frozenset(fld_ev)),
        O.M_FLD_H: (frozenset(fld_h), frozenset(fld_h_ev)),
        O.M_FLD_LEAD: (frozenset(fld_lead), frozenset(fld_ev)),
        O.M_FLD_META: (frozenset(O.FIELD_META.values()), frozenset()),
    }


CHANNELS = _channels()
META_CH = {_FAC: O.FACILITY_META, _FLD: O.FIELD_META}

#: 측정 → 허용 태그 → 값 검사.
_LEAD_H = frozenset(str(x) for x in O.FACILITY_LEAD_H)
_LEAD_D = frozenset(str(x) for x in O.FIELD_LEAD_D)


def _tag_ok(meas: str, key: str, val: str) -> bool:
    fam, role = MEASUREMENTS[meas]
    if key == 'facility':
        return fam == _FAC and bool(_FACILITY_RE.match(val))
    if key == 'target':
        return val == fam
    if key == 'lead_h':
        return fam == _FAC and role == 'lead' and val in _LEAD_H
    if key == 'lead_d':
        return fam == _FLD and role == 'lead' and val in _LEAD_D
    return False


def _required_tags(meas: str) -> Tuple[str, ...]:
    fam, role = MEASUREMENTS[meas]
    if role == 'lead':
        return ('lead_h',) if fam == _FAC else ('lead_d',)
    return ()


@dataclass(frozen=True)
class IngestPoint:
    """Influx 에 쓸 점 하나(검증 통과분)."""
    measurement: str
    device_id: str
    channel: int
    timestamp: float
    value: float
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Publication:
    family: str
    device_id: str
    t0: float
    status: int
    valid_until: float


@dataclass
class IngestResult:
    accepted: List[IngestPoint] = field(default_factory=list)
    rejected: int = 0
    reasons: Counter = field(default_factory=Counter)

    def reject(self, reason: str, n: int = 1) -> None:
        if n <= 0:
            return
        self.rejected += n
        self.reasons[reason] += n


class IngestError(ValueError):
    """요청 전체가 받을 수 없는 모양(400) 또는 너무 큼(413)."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _num(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pubs_from_body(body: Mapping, raw_points: List[Mapping]) -> Dict[Tuple[str, str], Optional[Publication]]:
    """(가족, device_id) → 발행. 값이 None 이면 머리말이 망가진 발행(그 대상 전체 거부)."""
    found: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    for p in body.get('pubs') or []:
        if not isinstance(p, Mapping):
            continue
        fam, dev = p.get('family'), p.get('id')
        if fam in META_OF and isinstance(dev, str):
            found[(fam, dev)] = {'t0': _num(p.get('t0')), 'status': _num(p.get('status')),
                                 'valid_until': _num(p.get('valid_until'))}
    # `pubs` 에 없는 대상은 같은 요청의 머리말 점에서 만든다(작은 발행은 한 조각에 다 들어간다)
    derived: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    for rp in raw_points:
        meas = rp.get('m')
        if meas not in MEASUREMENTS or MEASUREMENTS[meas][1] != 'meta':
            continue
        fam = MEASUREMENTS[meas][0]
        key = (fam, rp.get('id'))
        if key in found:
            continue
        rec = derived.setdefault(key, {'t0': _num(rp.get('ts'))})
        ch, v = rp.get('ch'), _num(rp.get('v'))
        if ch == META_CH[fam]['status']:
            rec['status'] = v
        elif ch == META_CH[fam]['valid_until']:
            rec['valid_until'] = v
    found.update(derived)
    out: Dict[Tuple[str, str], Optional[Publication]] = {}
    for key, rec in found.items():
        t0, st, vu = rec.get('t0'), rec.get('status'), rec.get('valid_until')
        if t0 is None or st is None or vu is None or int(st) not in STATUS_CODES:
            out[key] = None
            continue
        out[key] = Publication(key[0], key[1], t0, int(st), vu)
    return out


def _pub_problem(pub: Optional[Publication], now: float) -> Optional[str]:
    if pub is None:
        return 'bad_publication'
    if pub.t0 < now - T0_PAST_S or pub.t0 > now + T0_FUTURE_S:
        return 't0_out_of_window'
    if pub.valid_until < pub.t0 or pub.valid_until - pub.t0 > MAX_VALID_S[pub.family]:
        return 'bad_valid_until'
    if pub.status < _UNSYNCED and now > pub.valid_until:
        return 'expired'
    return None


def validate(body, now: float,
             known_target: Optional[Callable[[str, str], bool]] = None) -> IngestResult:
    """요청 본문 → 통과한 점과 거부 사유. 모양이 틀리면 IngestError.

    known_target(family, device_id): 서버에 있는 대상인지(시설 = 코디네이터 함수, 노지 = 구획).
    None 이면 검사하지 않는다(단위 시험·내장 경로).
    """
    if not isinstance(body, Mapping):
        raise IngestError('본문은 JSON 객체여야 한다')
    raw = body.get('points')
    if not isinstance(raw, list):
        raise IngestError('points 목록이 필요하다')
    if len(raw) > MAX_POINTS_PER_REQUEST:
        raise IngestError('한 요청은 %d 점까지' % MAX_POINTS_PER_REQUEST, 413)
    raw = [p for p in raw if isinstance(p, Mapping)]
    res = IngestResult()
    res.reject('malformed', len(body['points']) - len(raw))

    pubs = _pubs_from_body(body, raw)
    pub_bad = {k: _pub_problem(p, now) for k, p in pubs.items()}
    target_ok: Dict[Tuple[str, str], bool] = {}

    for rp in raw:
        meas, dev = rp.get('m'), rp.get('id')
        if meas not in MEASUREMENTS:
            res.reject('measurement')
            continue
        fam, role = MEASUREMENTS[meas]
        if not isinstance(dev, str) or not _ID_RE.match(dev):
            res.reject('device_id')
            continue
        ch, ts, v = rp.get('ch'), _num(rp.get('ts')), _num(rp.get('v'))
        if isinstance(ch, bool) or not isinstance(ch, int):
            res.reject('channel')
            continue
        allowed, prob = CHANNELS[meas]
        if ch not in allowed:
            res.reject('channel')
            continue
        if ts is None or v is None:
            res.reject('value')
            continue
        if ch in prob and not (0.0 <= v <= 1.0):
            res.reject('value')
            continue
        tags = rp.get('tags') or {}
        if not isinstance(tags, Mapping) or not all(
                isinstance(k, str) and isinstance(t, str) and _tag_ok(meas, k, t)
                for k, t in tags.items()):
            res.reject('tags')
            continue
        if any(t not in tags for t in _required_tags(meas)):
            res.reject('tags')
            continue

        key = (fam, dev)
        if key not in pubs:
            res.reject('no_publication')
            continue
        problem = pub_bad[key]
        if problem:
            res.reject(problem)
            continue
        pub = pubs[key]
        if known_target is not None:
            if key not in target_ok:
                target_ok[key] = bool(known_target(fam, dev))
            if not target_ok[key]:
                res.reject('unknown_target')
                continue
        if role == 'meta':
            if abs(ts - pub.t0) > 1.0:
                res.reject('meta_ts')
                continue
            if ch == META_CH[fam]['status'] and int(v) not in STATUS_CODES:
                res.reject('value')
                continue
        else:
            if pub.status >= _UNSYNCED:
                res.reject('curve_on_unusable_status')
                continue
            if ts < pub.t0 - 1.0 or ts - pub.t0 > MAX_HORIZON_S[(fam, role)]:
                res.reject('ts_out_of_horizon')
                continue
        res.accepted.append(IngestPoint(meas, dev, int(ch), float(ts), float(v),
                                        {str(k): str(t) for k, t in tags.items()}))
    return res

