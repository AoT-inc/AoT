# coding=utf-8
"""
mcp_server/quality.py — MCP 호출 품질 지표.

감사 기록(`mcp_audit_log`)의 호출 품질 칸(p6_74)으로 평소 호출이 어떤지
계산한다. 따로 저장하는 것은 없다 — 부를 때마다 기록에서 다시 센다(워커별
60초 캐시).

읽지 않는 것: `params_json`(인자 원문, 대상 UUID 가 들어 있다)과 `reason`.
내보내지 않는 것: agent_id(사용자 로그인 이름이 들어 있다)·세션 열쇠·UUID.
agent_id 는 세션 열쇠가 없는 행을 묶는 데만 안에서 쓴다.

용어
  세션      같은 대화의 호출들. 세션 열쇠가 있으면 (agent_id, 전송, 열쇠)로, 없으면
            (agent_id, 전송)으로 묶고 10분 넘게 비면 끊는다.
  호출 묶음  세션 안에서 호출 사이가 90초 넘게 비면 새 묶음. 서버는 질문이
            어디서 끝나는지 모르므로 "질문" 의 근사치일 뿐이다.
  시작 시각  timestamp 는 기록 시점(= 실행이 끝난 시각)이라
            시작 = timestamp − duration_ms.

공개 API:
  compute_quality(days=7, transport=None, max_rows=20000) -> dict
  summarize(rows) -> dict            (DB 없이 도는 순수 계산 — 테스트용)
  category_of(tool_name) -> str
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

#: 호출 묶음을 끊는 간격(초). 세션 안에서 앞 호출이 끝나고 다음 호출이 시작될
#: 때까지 이보다 길면 새 묶음이다.
#:
#: 보정(2026-09-23): 실사용 분석은 "질문당 중앙값 3회, 10회 이상 14%" 였다.
#: 개발 기록 1,967행을 호출 주체별로 같은 방식으로 끊어 보면 10회 이상 묶음이
#: 30초 7.2% · 60초 10.9% · **90초 13.9%** · 120초 16.2% · 180초 18.1% 였고,
#: 중앙값은 90초까지 2회, 180초부터 3회였다. 긴 꼬리(10회 이상)가 맞는 90초로
#: 둔다. 그 기록에는 실행 시간 칸이 없어 끝 시각끼리의 간격으로 쟀다.
BUNDLE_GAP_SECONDS = 90

#: 세션 열쇠가 없는 행을 (agent_id, 전송)으로 묶을 때 세션을 끊는 간격(초).
FALLBACK_SESSION_GAP_SECONDS = 600

#: 결과를 워커마다 다시 쓰는 시간(초).
CACHE_SECONDS = 60

#: 기본 최대 행 수. 넘으면 최근 N건만으로 계산하고 그 사실을 응답에 적는다.
DEFAULT_MAX_ROWS = 20000

TRANSPORTS = ('mcp_stdio', 'mcp_http', 'rest', 'in_app')
ALLOWED_DAYS = (1, 7, 30)

#: 묶음의 첫 호출이 이것이면 "탐색부터 한 묶음".
DISCOVERY_TOOLS = frozenset({'open_drawer', 'get_tool_detail',
                             'resolve_target', 'search_devices'})
#: 서랍을 연 호출. 뒤에 서랍 경유(via_drawer) 호출이 오면 "전환" 이다.
DRAWER_OPEN_TOOLS = frozenset({'open_drawer', 'get_tool_detail'})

_REFUSED_STATES = frozenset({'refused', 'rejected', 'expired'})

#: 결과 요약(result_summary)이 이것이면 "도구가 제대로 답한 것" 이다 — 대상이
#: 없다, 또는 어느 대상인지 되묻는다. 몇몇 도구는 이때 `error` 키도 함께 실어
#: call_state 가 failed 로 적히지만(gate.call_state 는 응답의 일부라 바꾸지
#: 않는다), 오류율에 넣으면 빈 결과·되묻기와 이중으로 센다. 그래서 오류율에서
#: 빼고 빈 결과율·되묻기율에만 넣으며, 지연 표본에는 실행된 호출과 함께 넣는다.
#: (실제 쓰이는 status 는 needs_disambiguation·not_found. target_not_found 는
#: 지금은 `error` 값으로만 쓰이지만 status 로 올 때를 대비해 둔다.)
_DISAMBIGUATION_SUMMARIES = frozenset({'needs_disambiguation'})
_NOT_FOUND_SUMMARIES = frozenset({'not_found', 'target_not_found'})
_ANSWERED_SUMMARIES = _DISAMBIGUATION_SUMMARIES | _NOT_FOUND_SUMMARIES

_cache = {}
_cache_lock = threading.Lock()


# ── 작은 계산 도구 ───────────────────────────────────────────────────────────

def _percentile(values, pct):
    """최근접 순위 백분위. 값이 없으면 None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _ratio(num, den):
    return round(num / den, 4) if den else None


def category_of(tool_name):
    """도구 → 서랍 범주. 화면은 도구 이름 대신 이 범주만 보여 준다."""
    name = tool_name or ''
    if name in DRAWER_OPEN_TOOLS:
        return 'drawer'
    try:
        from aot.tools import tool_registry as reg
        # tier_of 는 배정이 없는 도구에 'system' 을 기본으로 준다 — 그러면 모르는
        # 도구가 전부 시스템으로 몰린다. 배정된 도구만 서랍을 쓴다.
        if name in getattr(reg, '_TIER_ASSIGNMENT', {}):
            return reg.tier_of(name)[0]
    except Exception:
        pass
    return 'other'


# ── 세션·묶음 ────────────────────────────────────────────────────────────────

def _start(row):
    return row['timestamp'] - timedelta(milliseconds=row.get('duration_ms') or 0)


def _sessions(rows):
    """측정된 행 → 세션 목록(각 세션은 시작 시각 순 행 목록)."""
    keyed = {}
    for r in rows:
        if r.get('session_key'):
            # agent_id 도 넣는다 — 다른 호출 주체의 열쇠가 우연히 겹쳐도 한
            # 세션으로 섞이지 않게. (안에서만 쓰고 내보내지 않는다.)
            key = ('k', r.get('agent_id'), r.get('transport'), r['session_key'])
        else:
            key = ('a', r.get('agent_id'), r.get('transport'))
        keyed.setdefault(key, []).append(r)

    out = []
    for key, group in keyed.items():
        group.sort(key=_start)
        if key[0] == 'k':
            out.append(group)
            continue
        # 열쇠 없는 행: 10분 넘게 비면 다른 대화로 본다.
        cur = [group[0]]
        for prev, r in zip(group, group[1:]):
            gap = (_start(r) - prev['timestamp']).total_seconds()
            if gap > FALLBACK_SESSION_GAP_SECONDS:
                out.append(cur)
                cur = []
            cur.append(r)
        out.append(cur)
    return out


def _bundles(session):
    """세션 → (묶음 목록, 묶음 안 호출 사이 간격(ms) 목록)."""
    bundles = [[session[0]]]
    gaps = []
    for prev, r in zip(session, session[1:]):
        gap = (_start(r) - prev['timestamp']).total_seconds()
        if gap > BUNDLE_GAP_SECONDS:
            bundles.append([r])
        else:
            bundles[-1].append(r)
            # 겹쳐 돈 호출(일괄 요청)은 간격 0 으로 센다.
            gaps.append(max(0, int(round(gap * 1000))))
    return bundles, gaps


# ── 지표 ─────────────────────────────────────────────────────────────────────

def _row_metrics(rows):
    """행 단위 지표 — 묶음과 무관한 것."""
    n = len(rows)
    def _summary(r):
        return r.get('result_summary') or ''

    failed = sum(1 for r in rows if r.get('call_state') == 'failed'
                 and _summary(r) not in _ANSWERED_SUMMARIES)
    refused = sum(1 for r in rows if r.get('call_state') in _REFUSED_STATES)
    pending = sum(1 for r in rows if r.get('call_state') == 'pending_approval')
    empty = sum(1 for r in rows
                if r.get('result_items') == 0
                or _summary(r) in _NOT_FOUND_SUMMARIES)
    disamb = sum(1 for r in rows if _summary(r) in _DISAMBIGUATION_SUMMARIES)
    truncated = sum(1 for r in rows if r.get('truncated'))
    # 지연은 **실제로 답한 읽기 호출만** — 실행된 것과, 대상이 없다·되묻는다로
    # 답한 것. 승인 대기·거부는 실행 시간이 아니고, 쓰기는 장치 응답을 기다리는
    # 시간이 섞여 도구의 빠르기를 말해 주지 못한다.
    lat = [r['duration_ms'] for r in rows
           if r.get('permission') == 'read' and r.get('duration_ms') is not None
           and (r.get('call_state') == 'executed'
                or (r.get('call_state') == 'failed'
                    and _summary(r) in _ANSWERED_SUMMARIES))]
    return {
        'calls': n,
        'error_rate': _ratio(failed, n),
        'refused_rate': _ratio(refused, n),
        'pending_rate': _ratio(pending, n),
        'empty_rate': _ratio(empty, n),
        'disambiguation_rate': _ratio(disamb, n),
        'truncated_rate': _ratio(truncated, n),
        'latency_p50_ms': _percentile(lat, 50),
        'latency_p90_ms': _percentile(lat, 90),
        'latency_samples': len(lat),
    }


def _flow_metrics(rows):
    """묶음 단위 지표 — 호출이 어떻게 이어졌는가."""
    bundles, gaps = [], []
    for s in _sessions(rows):
        b, g = _bundles(s)
        bundles.extend(b)
        gaps.extend(g)

    sizes = [len(b) for b in bundles]
    repeats = 0
    pairs = 0
    longest = 0
    discovery_first = 0
    opens = 0
    converted = 0
    for b in bundles:
        if b[0].get('tool_name') in DISCOVERY_TOOLS:
            discovery_first += 1
        run = 1
        longest = max(longest, 1)
        for prev, r in zip(b, b[1:]):
            pairs += 1
            if r.get('tool_name') == prev.get('tool_name'):
                repeats += 1
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        # 서랍 열기 하나에 뒤따르는 서랍 경유 호출 **하나**만 짝짓는다 — 다음
        # 서랍 열기가 오기 전까지. 열기 둘 뒤에 경유 호출 하나면 전환 1건이다.
        waiting = False
        for r in b:
            if r.get('tool_name') in DRAWER_OPEN_TOOLS:
                opens += 1
                waiting = True
            elif waiting and r.get('via_drawer'):
                converted += 1
                waiting = False

    return {
        'bundles': len(bundles),
        'calls_per_bundle_p50': _percentile(sizes, 50),
        'calls_per_bundle_p90': _percentile(sizes, 90),
        'bundles_10_plus_rate': _ratio(sum(1 for s in sizes if s >= 10), len(sizes)),
        'same_tool_repeat_rate': _ratio(repeats, pairs),
        'longest_same_tool_run': longest or None,
        'discovery_first_rate': _ratio(discovery_first, len(bundles)),
        'drawer_follow_through_rate': _ratio(converted, opens),
        'gap_p50_ms': _percentile(gaps, 50),
        'gap_p90_ms': _percentile(gaps, 90),
    }


def _metrics(rows):
    m = _row_metrics(rows)
    m.update(_flow_metrics(rows) if rows else {
        'bundles': 0, 'calls_per_bundle_p50': None, 'calls_per_bundle_p90': None,
        'bundles_10_plus_rate': None, 'same_tool_repeat_rate': None,
        'longest_same_tool_run': None, 'discovery_first_rate': None,
        'drawer_follow_through_rate': None, 'gap_p50_ms': None, 'gap_p90_ms': None,
    })
    return m


def _table(rows, key_fn, key_name):
    groups = {}
    for r in rows:
        groups.setdefault(key_fn(r), []).append(r)
    table = []
    for key, grp in groups.items():
        m = _row_metrics(grp)
        table.append({
            key_name: key,
            'calls': m['calls'],
            'latency_p50_ms': m['latency_p50_ms'],
            'latency_p90_ms': m['latency_p90_ms'],
            'error_rate': m['error_rate'],
            'empty_rate': m['empty_rate'],
            'truncated_rate': m['truncated_rate'],
        })
    table.sort(key=lambda e: (-e['calls'], str(e[key_name])))
    return table


def summarize(rows):
    """행 목록 → 지표. 행은 dict — timestamp(naive UTC datetime), agent_id,
    tool_name, permission, result_summary 와 p6_74 칸들.

    새 칸이 비어 있는 행(p6_74 이전 기록, 또는 기록 스위치를 끈 동안)은
    측정 비율에만 들어가고 다른 모든 지표에서 빠진다.
    """
    measured = [r for r in rows if r.get('call_state') is not None]
    by_transport = {}
    for t in TRANSPORTS:
        sub = [r for r in measured if r.get('transport') == t]
        if sub:
            by_transport[t] = _metrics(sub)
    return {
        'rows_total': len(rows),
        'rows_measured': len(measured),
        'measured_ratio': _ratio(len(measured), len(rows)),
        'overall': _metrics(measured),
        'by_transport': by_transport,
        'by_category': _table(measured, lambda r: category_of(r.get('tool_name')),
                              'category'),
        'by_tool': [dict(e, category=category_of(e['tool']))
                    for e in _table(measured, lambda r: r.get('tool_name') or '',
                                    'tool')],
    }


# ── DB ───────────────────────────────────────────────────────────────────────

def _load_rows(days, transport, max_rows):
    """기간 안 최근 행을 최대 max_rows 개. (행 목록, 잘렸는가)."""
    from aot.databases.models import MCPAuditLog as M
    from aot.config import AOT_DB_PATH
    from aot.databases.utils import session_scope

    since = datetime.utcnow() - timedelta(days=days)
    cols = (M.timestamp, M.agent_id, M.tool_name, M.permission, M.result_summary,
            M.duration_ms, M.session_key, M.transport, M.via_drawer,
            M.response_tokens, M.response_bytes, M.truncated, M.call_state,
            M.result_items)
    names = [c.key for c in cols]
    with session_scope(AOT_DB_PATH) as sess:
        q = sess.query(*cols).filter(M.timestamp >= since)
        if transport:
            q = q.filter(M.transport == transport)
        got = q.order_by(M.timestamp.desc()).limit(max_rows + 1).all()
    limited = len(got) > max_rows
    rows = [dict(zip(names, r)) for r in got[:max_rows]]
    return rows, limited


def compute_quality(days=7, transport=None, max_rows=DEFAULT_MAX_ROWS):
    """기간(1·7·30일)과 전송으로 좁힌 호출 품질 지표. 워커별 60초 캐시."""
    if days not in ALLOWED_DAYS:
        days = 7
    if transport not in TRANSPORTS:
        transport = None
    key = (days, transport, max_rows)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    rows, limited = _load_rows(days, transport, max_rows)
    result = summarize(rows)
    result.update({
        'days': days,
        'transport': transport,
        'limited': limited,
        'max_rows': max_rows,
        'bundle_gap_seconds': BUNDLE_GAP_SECONDS,
        'fallback_session_gap_seconds': FALLBACK_SESSION_GAP_SECONDS,
        'generated_at': datetime.utcnow().isoformat() + 'Z',
    })
    with _cache_lock:
        _cache[key] = (now + CACHE_SECONDS, result)
    return result


def clear_cache():
    with _cache_lock:
        _cache.clear()
