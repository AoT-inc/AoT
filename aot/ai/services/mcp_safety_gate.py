# coding=utf-8
"""
mcp_safety_gate.py — 외부 MCP 경로(aot_mcp_server.py)의 안전·감사 게이트.

외부 AI가 MCP로 접속해 상태를 점검하고 제어를 조언하는 경로에서,
"누가(agent_id) 무엇을 왜(reason) 호출했는지"를 남기고 쓰기 도구는
사람 승인을 거치게 만드는 계층이다.

`aot/mcp_server/safety.py`(FastMCP 트랙)를 대체한다. 그 구현을 그대로
쓸 수 없는 이유가 두 가지 있고, 여기서 둘 다 바로잡는다:

  1. WRITE_TOOLS 가 그 트랙 전용 4개 도구(set_vpd_target 등)로 하드코딩돼
     있어, 활성 서버의 실제 쓰기 도구(operate_device, set_output_state,
     설비 CRUD …)는 검사를 그냥 통과한다 — 있는 척하는 무동작이 된다.
     → 여기서는 tool_registry(SSOT)의 approval_required_tools() 에서 파생한다.
     레지스트리에 도구를 mutating/physical 로 선언하면 자동으로 게이트에 걸린다.

  2. 승인 대기 큐가 프로세스 인메모리(dict)였다. MCP 서버는 gunicorn 웹앱과
     별도 프로세스라, 인메모리 토큰은 웹 UI에서 승인할 수단이 없다.
     → 여기서는 MCPConfirmation 테이블(이미 마이그레이션됨)을 사용해
     프로세스 간 승인 핸드셰이크가 성립한다.

승인 흐름 (외부 AI ↔ 사람):
  1. 외부 AI가 쓰기 도구 호출 → 게이트가 MCPConfirmation(pending) 생성 후
     confirmation_id 를 담은 "승인 필요" 응답 반환 (실행되지 않음)
  2. 사람이 웹에서 승인/거부 (routes_mcp_api 의 /confirmations/* 엔드포인트)
  3. 외부 AI가 같은 도구를 `_confirmation_id` 와 함께 재호출 → 실행

재호출 시 인자가 승인 시점과 다르면 거부한다(승인 바꿔치기 방지). 승인은
1회용이며 소비되면 status='consumed' 로 표시해 재사용(replay)을 막는다.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 호출자가 전달하는 메타 키 — 핸들러 시그니처엔 없으므로 디스패치 전에 제거된다.
META_KEYS = frozenset({'_reason', '_agent_id', '_confirmation_id'})

# 레지스트리에 없는 네이티브 도구 중 물리 제어에 해당하는 것.
# (AoTNativeToolEngine 은 tool_registry.TOOLS 에 선언돼 있지 않다.)
_NATIVE_WRITE_TOOLS = frozenset({'set_output_state'})

# 유효시간은 두 구간으로 나뉜다. 전에는 하나(5분)로 둘 다 덮었는데, 그러면
# 두 요구가 충돌한다: 사람이 판단할 시간은 길어야 하고, 승인이 살아있는 시간은
# 짧아야 한다(승인해 둔 물리 제어가 한참 뒤에 실행되면 안 된다).
#
# 한 값으로 묶여 있을 때 실제로 생기던 문제: 4분 50초 만에 승인을 누르면 실행
# 가능 시간이 10초밖에 안 남아, 사람은 분명히 승인했는데 AI 가 재호출하는 사이
# confirmation_expired 가 났다. 만료까지 남은 시간이 승인 시점에 따라 달라지는
# 셈이라 예측이 불가능했다.
#
#   1) 생성 → 승인   : 사람이 판단할 시간. 넉넉해야 한다.
_CONFIRM_TTL_SEC = int(os.environ.get('AOT_MCP_CONFIRM_TTL_SEC', '900'))
#   2) 승인 → 실행   : 승인이 살아있는 시간. 승인 시점부터 새로 시작한다.
_APPROVED_TTL_SEC = int(os.environ.get('AOT_MCP_APPROVED_TTL_SEC', '300'))

# 도구별 시간당 호출 상한.
_DEFAULT_CALLS_PER_HOUR = 10
# 주의: 이 상한은 "작업 횟수"가 아니라 "호출 횟수"다. 승인이 필요한 도구는
# 승인 요청 호출과 승인 후 실행 호출이 각각 하나씩 세어지므로(아래
# _check_rate_limit 이 승인 분기보다 먼저 돈다), 실제로 끝까지 수행되는
# 작업 수는 상한의 절반이다. 값을 정할 때 이 점을 감안할 것.
_RATE_LIMITS = {
    'operate_device': 20,
    'set_output_state': 20,
    'schedule_device_control': 20,
    # 시퀀스 구성 도구는 본질적으로 "스텝 수만큼" 반복 호출된다. 8스텝짜리
    # 관수 시퀀스 하나를 세팅하는 데만 승인 왕복 포함 16회가 필요해서,
    # 기본값 10 으로는 한 시퀀스도 못 채우고 중간에 refused 로 끊긴다
    # (2026-08-06 실제로 겪음 — 4스텝째에서 막혀 그룹 설정이 통째로 유실됐다).
    # 장치를 직접 구동하지 않는 설정 변경이므로 폭주 방지 목적만 남기고 넉넉히 준다.
    'modify_sequence_step': 60,
    'modify_sequence_schedule': 20,
}

_RATE_WINDOW_SEC = 3600.0

# DB 를 못 읽을 때만 쓰는 프로세스 로컬 폴백 카운터.
# {agent_id: {tool_name: [timestamp, ...]}}
_call_log = {}


class RateLimitExceeded(Exception):
    """시간당 호출 횟수 초과."""


def is_write_enabled() -> bool:
    """쓰기 도구 허용 여부.

    '0' 이면 조언 전용 모드 — 쓰기 도구는 승인 대기조차 만들지 않고 거부된다.
    기본값은 허용이지만, 허용이라도 모든 쓰기는 사람 승인을 거친다.
    """
    return os.environ.get('AOT_MCP_WRITE_ENABLED', '1') not in ('0', 'false', 'False')


def write_tools() -> frozenset:
    """상태를 바꾸는 도구 전부 — 승인이 면제된 설정 편집 도구도 포함한다.

    '쓰기인가'와 '승인이 필요한가'는 다른 질문이다. 설정 편집 도구는 승인은
    면제돼도 읽기 전용 키에는 여전히 거부돼야 하고 감사 로그에도 write 로
    남아야 한다. 그래서 두 집합을 분리해 둔다."""
    try:
        from aot.ai.services.tool_registry import write_tools as _reg_write
        return frozenset(_reg_write()) | _NATIVE_WRITE_TOOLS
    except Exception:
        # 레지스트리를 못 읽으면 게이트가 조용히 열리는 대신 네이티브 목록만이라도 막는다.
        logger.exception('[MCPGate] tool_registry 로드 실패 — 네이티브 쓰기 목록만 적용')
        return _NATIVE_WRITE_TOOLS


def approval_tools() -> frozenset:
    """사람 승인이 필요한 도구 이름 집합 (레지스트리 SSOT + 네이티브 물리 도구)."""
    try:
        from aot.ai.services.tool_registry import approval_required_tools
        return frozenset(approval_required_tools()) | _NATIVE_WRITE_TOOLS
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 네이티브 쓰기 목록만 적용')
        return _NATIVE_WRITE_TOOLS


def config_only_tools() -> frozenset:
    """쓰기지만 승인이 면제된 설정 편집 도구 — tool_registry 의 _CONFIG_ONLY 주석 참고.

    레지스트리를 못 읽으면 **빈 집합**을 돌려준다. 여기서 실패가 면제 쪽으로
    기울면 게이트가 통째로 열린다 — 모르면 승인을 요구하는 쪽이 맞다."""
    try:
        from aot.ai.services.tool_registry import config_only_tools as _reg_config
        return frozenset(_reg_config())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 승인 면제 없음으로 처리')
        return frozenset()


def classify_permission(tool_name: str) -> str:
    """'write' (상태 변경) 또는 'read'. 승인 필요 여부와는 별개다."""
    return 'write' if tool_name in write_tools() else 'read'


def strip_meta(arguments: dict) -> dict:
    """게이트 메타 키를 제거한 인자 사본 — 핸들러에 넘길 값."""
    return {k: v for k, v in (arguments or {}).items() if k not in META_KEYS}


# 호출자 신원을 핸들러 인자로 받아야 하는 도구.
# 의견 원장은 "누가 낸 의견인지"가 핵심이라, 호출자가 agent_id 를 스스로 적어
# 보내주기를 기대하면 안 된다(대개 비워서 보낸다 → 전부 unknown 이 되어 귀속이
# 무너진다). 전송 계층에서 확인된 신원을 서버가 주입한다.
_AGENT_ATTRIBUTED_TOOLS = frozenset({'submit_advice'})


def inject_agent(tool_name: str, call_args: dict, agent_id: str) -> dict:
    """신원 귀속이 필요한 도구에 확인된 agent_id 를 채워 넣는다.

    호출자가 명시적으로 다른 값을 넣었더라도 전송 계층에서 확인된 신원으로
    덮어쓴다 — 남의 이름으로 의견을 제출하는 것을 막기 위한 것이다.
    """
    if tool_name in _AGENT_ATTRIBUTED_TOOLS and agent_id and agent_id != 'unknown':
        call_args = dict(call_args)
        call_args['agent_id'] = agent_id
    return call_args


def _canonical_params(arguments: dict) -> str:
    """승인 시점과 재호출 시점의 인자 동일성 비교용 정규화 문자열."""
    return json.dumps(strip_meta(arguments), ensure_ascii=False, sort_keys=True)


def _check_rate_limit_in_process(agent_id: str, tool_name: str, limit: int) -> None:
    """DB 를 못 읽을 때의 폴백 — 이 프로세스에서 센 횟수만 본다."""
    now = time.time()
    calls = _call_log.setdefault(agent_id, {}).setdefault(tool_name, [])
    calls[:] = [t for t in calls if now - t < _RATE_WINDOW_SEC]
    if len(calls) >= limit:
        raise RateLimitExceeded(
            f"Rate limit exceeded for '{tool_name}': {limit} calls/hour (agent={agent_id}).")
    calls.append(now)


def _check_rate_limit(agent_id: str, tool_name: str) -> None:
    """시간당 호출 상한. 카운트 기준은 MCPConfirmation 행(= 프로세스 공유).

    인메모리 dict 로 세면 안 되는 이유: 이 게이트를 import 하는 프로세스가
    최소 둘이다 — 웹앱(gunicorn)이 직접 띄우는 stdio 브릿지 경로와, 별도
    컨테이너/유닛으로 도는 HTTP 서버(`aot_mcp_server.py --http`). 각자 제
    dict 를 들고 있어서, 같은 키가 양쪽을 번갈아 치면 상한이 프로세스 수만큼
    곱해졌다(operate_device 20회/시간 → 실질 40회). 재시작하면 그마저 0으로
    돌아갔다.

    쓰기 시도는 예외 없이 MCPConfirmation 행을 하나 남긴다 — 승인 대기(pending)
    든, elicitation 즉답(consumed/rejected)이든. 그래서 그 행을 세면 새 테이블
    없이 프로세스 간 공유되고 재시작에도 살아남는 카운터가 된다. 부수효과로
    elicitation 경로도 이제 상한에 포함된다(전에는 `_check_rate_limit` 를 아예
    거치지 않아 무제한이었다).

    원자적 카운터는 아니다 — 두 프로세스가 동시에 세면 둘 다 통과할 수 있다.
    상한은 폭주 방지용 best-effort 이고, 모든 쓰기는 그 뒤에 사람 승인을 한 번
    더 거친다.
    """
    limit = _RATE_LIMITS.get(tool_name, _DEFAULT_CALLS_PER_HOUR)

    try:
        from aot.databases.models import MCPConfirmation
        since = datetime.utcnow() - timedelta(seconds=_RATE_WINDOW_SEC)
        used = (MCPConfirmation.query
                .filter(MCPConfirmation.agent_id == agent_id)
                .filter(MCPConfirmation.tool_name == tool_name)
                .filter(MCPConfirmation.created_at >= since)
                .count())
    except Exception:
        # 앱 컨텍스트 밖이거나 DB 가 죽은 경우 — 상한을 통째로 열어주는 대신
        # 프로세스 로컬 카운터로라도 막는다.
        logger.exception('[MCPGate] 레이트 리밋 DB 조회 실패 — 프로세스 로컬 폴백')
        _check_rate_limit_in_process(agent_id, tool_name, limit)
        return

    if used >= limit:
        raise RateLimitExceeded(
            f"Rate limit exceeded for '{tool_name}': {limit} calls/hour (agent={agent_id}).")


def _build_human_briefing(tool_name, arguments):
    """Plain-language plan summary for the human web-approval page
    (mcp_review.html renders `reason` above the raw params dump). Returns ''
    when there's nothing worth adding beyond the raw params (most tools -
    e.g. operate_device's {device_id, state} is already short and clear).

    Covers the two shapes that motivated this: a single add_schedule/
    create_note-style call with target_name (site vs. zone confusion), and
    an add_schedule_batch call (a human should see the actual entry list,
    not a JSON blob, before clicking Approve on N writes at once).
    """
    args = arguments or {}
    lines = []
    try:
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        target_name = args.get('target_name')
        if target_name:
            r = AoTDataToolService.resolve_target_tool(target_name)
            if r.get('status') == 'needs_disambiguation':
                lines.append(f"'{target_name}' could not be matched to a known place/device.")
            elif r.get('target_type'):
                line = f"Target: '{target_name}' -> {r.get('target_type')} '{r.get('resolved_name')}'"
                children = r.get('children') or []
                if children:
                    line += f" (contains {len(children)} sub-zone(s): {', '.join(c['name'] for c in children)} - this call attaches to ONLY the named target, not to each of these)"
                lines.append(line)

        if tool_name == 'add_schedule_batch':
            entries = args.get('entries') or []
            lines.append(f"Batch of {len(entries)} schedule entr(y/ies) on {args.get('date', '?')}:")
            for e in entries:
                c = e.get('content') or args.get('content') or ''
                lines.append(f"  - {e.get('target_name', '?')} @ {e.get('time', '?')}: {c}")
            if args.get('window_start') or args.get('window_end'):
                lines.append(f"Work window: {args.get('window_start', '?')}-{args.get('window_end', '?')} "
                             f"(duration_minutes={args.get('duration_minutes', 60)} per entry)")
        elif tool_name == 'add_schedule':
            lines.append(f"Schedule: {args.get('date', '?')} {args.get('time', '?')} - {args.get('content', '')}")
    except Exception:
        logger.exception('[MCPGate] briefing 생성 실패 (건너뜀)')

    return '\n'.join(lines)


def gate(tool_name, arguments, agent_id='unknown', role=None, reason='', elicit_fn=None):
    """쓰기 도구를 사람 승인 뒤로 보낸다.

    Flask 앱 컨텍스트 안에서 호출해야 한다 (MCPConfirmation 조회/생성).

    role 은 mcp_auth.authenticate_http/authenticate_stdio 가 돌려주는 Role 행(또는
    None)이다. tools/list 단계에서 이미 role 기준으로 쓰기 도구를 숨기지만
    (aot_mcp_server._get_all_tools), 그건 클라이언트를 신뢰하는 안내일 뿐이라 — 도구
    이름을 미리 아는 클라이언트가 목록을 건너뛰고 직접 호출할 수 있다. 여기서 서버
    쪽에서 다시 한 번 확정적으로 막는다(방어의 두 번째 층).

    Returns:
        None  — 통과(읽기 도구이거나, 승인된 confirmation 을 소비함). 호출자는 실행을 진행한다.
        dict  — 실행하면 안 되는 경우의 응답 본문(승인 대기/거부). 호출자는 이 값을 그대로 반환한다.
    """
    if classify_permission(tool_name) == 'read':
        return None

    from aot.ai.services.mcp_auth import role_can_write
    if not role_can_write(role):
        return {
            "status": "refused",
            "reason_code": "insufficient_role",
            "message": ("Your MCP key's role does not have write access — only "
                        "Admin/Editor role keys can run mutating or physical-control "
                        "tools. Do not retry; state what should be done and why as "
                        "advice instead."),
            "tool_name": tool_name,
        }

    if not is_write_enabled():
        return {
            "status": "refused",
            "reason_code": "write_disabled",
            "message": (
                "This server is in advice-only mode (AOT_MCP_WRITE_ENABLED=0). "
                "Control cannot be executed - state what should be done and why "
                "as advice instead."),
            "tool_name": tool_name,
        }

    # 설정 편집 도구는 여기서 통과시킨다 — 역할 검사와 write_enabled 검사를
    # 지난 **뒤**여야 한다. 앞에 두면 읽기 전용 키가 설정을 고칠 수 있고,
    # 조언 전용 모드(AOT_MCP_WRITE_ENABLED=0)도 뚫린다.
    # 승인만 면제될 뿐 쓰기는 쓰기다: 호출자는 위에서 이미 걸러졌고,
    # 감사 로그에는 호출자 순서상 write 로 남는다.
    if tool_name in config_only_tools():
        return None

    from aot.databases.models import MCPConfirmation

    confirmation_id = (arguments or {}).get('_confirmation_id')

    # ── 0단계: 실시간 elicitation (stdio, 클라이언트가 지원할 때만) ────────────
    # MCP 표준 elicitation을 지원하는 클라이언트(예: Claude Code)로 붙은 경우,
    # 비동기 승인 큐(생성 → LLM이 사람에게 채팅으로 전달 → respond_to_confirmation
    # 재호출)를 거치지 않고, 이 tools/call 처리 도중 클라이언트에게 직접
    # 'elicitation/create' 요청을 보내 사람이 그 자리에서 답하게 한다. 응답은
    # 클라이언트의 네이티브 UI를 통해서만 오므로, 호출한 LLM이 스스로 승인
    # 여부를 판단하거나 대신 답할 수 없다 — respond_to_confirmation 자가승인
    # 사고(2026-07-26)가 구조적으로 불가능해진다. confirmation_id 가 이미 있는
    # 재시도 호출이면 이 단계는 건너뛰고 기존 큐 조회로 간다.
    if not confirmation_id and elicit_fn:
        briefing = _build_human_briefing(tool_name, arguments)
        try:
            decision = elicit_fn(tool_name, briefing, arguments)
        except Exception:
            logger.exception('[MCPGate] elicitation 호출 실패 (큐 방식으로 폴백)')
            decision = None

        if decision is True:
            row = MCPConfirmation(
                expires_at=datetime.utcnow() + timedelta(seconds=_CONFIRM_TTL_SEC),
                tool_name=tool_name,
                params_json=_canonical_params(arguments),
                reason=(briefing or reason or ''),
                agent_id=agent_id,
                status='consumed',
            )
            row.save()
            logger.info("[MCPGate] elicitation 승인 tool=%s agent=%s confirmation=%s",
                        tool_name, agent_id, row.unique_id)
            return None  # 통과 — 호출자가 바로 실행 진행
        elif decision is False:
            row = MCPConfirmation(
                expires_at=datetime.utcnow() + timedelta(seconds=_CONFIRM_TTL_SEC),
                tool_name=tool_name,
                params_json=_canonical_params(arguments),
                reason=(briefing or reason or ''),
                agent_id=agent_id,
                status='rejected',
            )
            row.save()
            return {
                "status": "refused",
                "reason_code": "user_declined",
                "message": (
                    "The user declined this exact action when asked directly just now. "
                    "Do not silently retry it. If the user then explicitly says they've "
                    "changed their mind and to proceed anyway, you may call this tool "
                    "again (it will ask them once more, fresh) - do not reuse this "
                    "response or assume the earlier decline still applies without that "
                    "new, explicit go-ahead. Otherwise, state what should be done and "
                    "why as advice instead."),
            }
        # decision is None → elicitation을 못 했거나 실패 — 기존 비동기 큐로 폴백

    # ── 2단계: 승인된 confirmation 을 들고 재호출한 경우 ──────────────────────
    if confirmation_id:
        row = MCPConfirmation.query.filter_by(unique_id=confirmation_id).first()
        if row is None:
            return {
                "status": "refused",
                "reason_code": "confirmation_not_found",
                "message": f"No such confirmation: {confirmation_id}",
            }
        if row.tool_name != tool_name:
            return {
                "status": "refused",
                "reason_code": "confirmation_tool_mismatch",
                "message": (f"This confirmation was issued for '{row.tool_name}' and "
                            f"cannot be used to run '{tool_name}'."),
            }
        # 승인 시점에 서버가 이미 실행을 끝낸 건(p6_26). 재실행하지 않고 그때의
        # 결과를 그대로 돌려준다 — 사람이 승인 버튼을 누른 것으로 이미 끝났고,
        # 여기서 한 번 더 돌리면 밸브가 두 번 열린다. 이 재생 경로 덕분에 예전
        # 방식대로 재호출하는 클라이언트도 고치지 않고 계속 동작한다.
        if row.status in ('executed', 'failed'):
            try:
                stored = json.loads(row.result_json or '{}')
            except Exception:
                stored = {}
            return {
                "status": "already_executed",
                "reason_code": "executed_on_approval",
                "confirmation_id": row.unique_id,
                "executed_at_approval": True,
                "result": stored,
                "message": ("This was already carried out when the user approved it. "
                            "The result is included here — report it as the outcome "
                            "and do NOT call the tool again."),
            }
        if row.status == 'consumed':
            return {
                "status": "refused",
                "reason_code": "confirmation_already_used",
                "message": "This confirmation was already used. Request a new one if needed.",
            }
        if row.status == 'rejected':
            return {
                "status": "refused",
                "reason_code": "confirmation_rejected",
                "message": ("The user rejected this request. Do not execute it; "
                            "switch to giving advice instead."),
            }
        if row.is_expired():
            if row.status != 'expired':
                row.status = 'expired'
                row.save()
            return {
                "status": "refused",
                "reason_code": "confirmation_expired",
                "message": "The confirmation expired. Request approval again.",
            }
        if row.status != 'approved':
            return {
                "status": "pending_approval",
                "reason_code": "awaiting_user",
                "confirmation_id": row.unique_id,
                "message": "Still waiting for user approval.",
            }
        # 승인 바꿔치기 방지 — 승인받은 인자와 동일해야 한다.
        if (row.params_json or '{}') != _canonical_params(arguments):
            return {
                "status": "refused",
                "reason_code": "confirmation_params_mismatch",
                "message": ("Arguments differ from the approved ones. "
                            "Changing arguments requires a new approval."),
                "approved_params": json.loads(row.params_json or '{}'),
            }
        # 1회용 소비
        row.status = 'consumed'
        row.save()
        logger.info("[MCPGate] 승인 소비 tool=%s agent=%s confirmation=%s",
                    tool_name, agent_id, row.unique_id)
        return None

    # ── 1단계: 최초 호출 — 승인 대기 생성 후 실행 보류 ────────────────────────

    # Batch-specific pure validation (no writes) — run BEFORE creating an
    # approval and BEFORE spending a rate-limit slot, so a batch that cannot
    # possibly work (duplicate target, time outside the stated window, or
    # more entries than the window has room for at duration_minutes each)
    # never reaches a human as something to approve. The handler
    # (add_schedule_batch_tool) never runs before approval, so without this
    # the same arithmetic mistake that motivated this whole change would just
    # move from "wrong site vs. zone" to "wrong time allocation" and still
    # only surface AFTER a human already clicked approve.
    if tool_name == 'add_schedule_batch':
        try:
            from aot.ai.services.aot_data_tool_service import AoTDataToolService
            _batch_err = AoTDataToolService.validate_schedule_batch(
                entries=(arguments or {}).get('entries'),
                content=(arguments or {}).get('content'),
                window_start=(arguments or {}).get('window_start'),
                window_end=(arguments or {}).get('window_end'),
                duration_minutes=(arguments or {}).get('duration_minutes', 60),
            )
            if _batch_err:
                return _batch_err
        except Exception:
            logger.exception('[MCPGate] add_schedule_batch 사전검증 실패 (검증 없이 진행)')

    try:
        _check_rate_limit(agent_id, tool_name)
    except RateLimitExceeded as exc:
        return {
            "status": "refused",
            "reason_code": "rate_limited",
            "message": str(exc),
        }

    # A human reviewing this on the web approval page (mcp_review.html) only
    # ever sees `reason` and a raw JSON dump of `params` — they do NOT see
    # whatever the calling LLM said in chat, and until now they did not see
    # the spatial/capacity checks below either (those were only returned in
    # the API response handed back to the LLM). That means "approval" so far
    # has effectively meant "trust the LLM's paraphrase" rather than an
    # independent human review. Folding a plain-language briefing into
    # `reason` — the one field the web page already renders prominently —
    # makes the actual plan visible on the button-click page itself, with no
    # dependency on the calling LLM relaying it accurately.
    briefing = _build_human_briefing(tool_name, arguments)
    full_reason = (reason or '').strip()
    if briefing:
        full_reason = (full_reason + '\n\n' + briefing).strip() if full_reason else briefing

    row = MCPConfirmation(
        expires_at=datetime.utcnow() + timedelta(seconds=_CONFIRM_TTL_SEC),
        tool_name=tool_name,
        params_json=_canonical_params(arguments),
        reason=full_reason,
        agent_id=agent_id,
        status='pending',
    )
    row.save()
    logger.info("[MCPGate] 승인 대기 생성 tool=%s agent=%s confirmation=%s",
                tool_name, agent_id, row.unique_id)

    response = {
        "status": "pending_approval",
        "reason_code": "awaiting_user",
        "confirmation_id": row.unique_id,
        "tool_name": tool_name,
        "expires_in_sec": _CONFIRM_TTL_SEC,
        "execute_within_sec": _APPROVED_TTL_SEC,
        "message": (
            "This tool changes system state, so it needs user approval. It was NOT "
            "executed. Show the user the plan (see the briefing above, if any) and wait "
            "for them to explicitly approve or reject THIS confirmation_id in this "
            "conversation - do not infer approval from their original task request "
            "alone. Once they do, call respond_to_confirmation with this "
            "confirmation_id and their decision (or they can click Approve/Reject on "
            "the web review page themselves). After an approval, call the same tool "
            "again with the same arguments plus '_confirmation_id' to execute it - "
            "promptly, within 'execute_within_sec' of the approval, after which the "
            "approval lapses and must be requested again. There is no way to bypass "
            "approval."),
    }

    # Spatial pre-check — surfaced here, not left to the caller to remember.
    # A write tool's own handler never runs before approval (this function
    # short-circuits on tool NAME alone), so a prose reminder inside the
    # tool's description ("call resolve_target first") is easy to miss or
    # ignore — confirmed 2026-07-26: a different model saw that exact
    # instruction and still misfired on a site vs. zone target. Running the
    # SAME read-only resolver here, before the human ever sees the approval,
    # makes the warning unmissable instead of optional.
    _target_name = (arguments or {}).get('target_name')
    if _target_name:
        try:
            from aot.ai.services.aot_data_tool_service import AoTDataToolService
            _resolved = AoTDataToolService.resolve_target_tool(_target_name)
            if _resolved.get('status') == 'needs_disambiguation':
                response['resolved_scope'] = {
                    "status": "needs_disambiguation",
                    "message": _resolved.get('message'),
                    "available_targets": _resolved.get('available_targets'),
                }
            elif _resolved.get('children'):
                response['resolved_scope'] = {
                    "target_type": _resolved.get('target_type'),
                    "children": _resolved.get('children'),
                    "note": _resolved.get('note'),
                }
        except Exception:
            logger.exception('[MCPGate] target_name 사전조회 실패 (경고 없이 진행)')

    return response


# ─────────────────────────────────────────────────────────────────────────────
# 사람이 쓰는 승인 API (웹앱 프로세스에서 호출 — routes_mcp_api)
# ─────────────────────────────────────────────────────────────────────────────

def list_pending(limit=50):
    """승인 대기 목록 (만료된 항목은 조회 시점에 정리)."""
    from aot.databases.models import MCPConfirmation

    rows = (MCPConfirmation.query
            .filter_by(status='pending')
            .order_by(MCPConfirmation.created_at.desc())
            .limit(limit).all())
    out = []
    for r in rows:
        if r.is_expired():
            r.status = 'expired'
            r.save()
            continue
        out.append({
            "confirmation_id": r.unique_id,
            "tool_name": r.tool_name,
            "params": json.loads(r.params_json or '{}'),
            "reason": r.reason,
            "agent_id": r.agent_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_in_sec": max(0, int((r.expires_at - datetime.utcnow()).total_seconds())),
        })
    return out


def _decide(confirmation_id, status, user_id=None):
    from aot.databases.models import MCPConfirmation

    row = MCPConfirmation.query.filter_by(unique_id=confirmation_id).first()
    if row is None:
        return {"status": "error", "message": "No such confirmation."}
    if row.status in ('consumed', 'rejected'):
        return {"status": "error", "message": f"Already handled (status={row.status})."}
    if row.is_expired():
        row.status = 'expired'
        row.save()
        return {"status": "error", "message": "The confirmation expired."}

    row.status = status
    if user_id:
        row.user_id = user_id
    if status == 'approved':
        # 승인 시점부터 실행 유효시간을 새로 센다 — 남은 판단 시간이 얼마였든
        # 승인 후 실행 창은 항상 같은 길이다. 같은 컬럼을 재사용해 승인 이후
        # 만료 판정(gate() 2단계의 row.is_expired())이 그대로 동작한다.
        row.expires_at = datetime.utcnow() + timedelta(seconds=_APPROVED_TTL_SEC)
    row.save()

    # 감사 로그의 해당 호출 상태도 갱신 (confirmation_id 로 연결돼 있다)
    try:
        from aot.databases.models import MCPAuditLog
        log = (MCPAuditLog.query
               .filter_by(confirmation_id=confirmation_id)
               .order_by(MCPAuditLog.timestamp.desc()).first())
        if log:
            log.confirmation_status = status
            if user_id:
                log.user_id = user_id
            log.save()
    except Exception:
        logger.exception('[MCPGate] 감사 로그 상태 갱신 실패')

    return {"status": "success", "confirmation_id": confirmation_id, "new_status": status}


#: tools/call 이 항상 함께 실어 보내는 호출 상태. 이 도구가 실제로 돌았는지를
#: 클라이언트가 도구별 어휘를 몰라도 판정할 수 있게 하는 단일 축이다.
#:
#: 기존 `status` 키에는 두 어휘가 섞여 있다 — 게이트의 승인 상태
#: (pending_approval/refused)와 각 도구의 결과(modified/created/deleted/
#: configured/placed/success… 12종). 그래서 "실행됐는가"를 알려면 도구마다 다른
#: 단어를 알아야 했다. `status` 를 통일하는 쪽은 이미 그 값으로 분기하는 코드
#: 46곳과 배포된 프롬프트를 깨므로, 축을 하나 더 두고 기존 값은 그대로 둔다.
CALL_STATES = (
    'executed',            # 이번 호출에서 실제로 실행됨 (읽기 도구 포함)
    'already_executed',    # 승인 시점에 서버가 이미 실행함 — 결과 재생
    'pending_approval',    # 실행 안 됨, 사람 승인 대기
    'approval_rejected',   # 사람이 거부함
    'approval_expired',    # 승인 대기가 만료됨
    'refused',             # 그 밖의 거부 (레이트 리밋, 인자 불일치, 쓰기 비활성 등)
    'failed',              # 도구가 예외/오류로 끝남
)

_REFUSAL_STATE = {
    'confirmation_rejected': 'approval_rejected',
    'confirmation_expired': 'approval_expired',
}


def call_state(blocked, result=None, error_text=''):
    """(blocked, result) → CALL_STATES 중 하나.

    blocked 는 gate() 의 반환값(None 이면 게이트를 통과해 실제로 실행된 것).
    """
    if blocked:
        status = blocked.get('status')
        if status == 'pending_approval':
            return 'pending_approval'
        if status == 'already_executed':
            return 'already_executed'
        return _REFUSAL_STATE.get(blocked.get('reason_code'), 'refused')
    if error_text:
        return 'failed'
    if isinstance(result, dict):
        # 실패를 알리는 관행이 두 가지다 — {"status": "error"} 38곳,
        # {"error": "..."} 217곳. 뒤쪽이 주류라 이걸 빠뜨리면 "없는 id 조회"
        # 같은 명백한 실패가 executed 로 보고된다.
        if result.get('status') == 'error' or result.get('error'):
            return 'failed'
    return 'executed'


#: 승인 화면에서 한 번 더 확인을 받는 도구 — 되돌릴 수 없는 물리 동작.
#: 설정 변경은 승인 한 번으로 끝내고, 밸브·펌프가 실제로 움직이는 것만 재확인한다.
PHYSICAL_TOOLS = frozenset({'operate_device', 'set_output_state', 'schedule_device_control'})


def execute_approved(confirmation_id, role=None):
    """승인된 요청을 서버가 직접 실행하고 결과를 레코드에 남긴다.

    승인이 "실행 허가증"이던 시절에는 사람이 승인 버튼을 눌러도 아무 일이
    없었고, 그 사람이 채팅으로 돌아가 AI 에게 알려줘야 AI 가 재호출해서 비로소
    실행됐다. 챗 모델은 사람이 말을 걸어야만 움직이므로 그 왕복은 설계상
    피할 수 없었다 — 그래서 실행 주체를 서버로 옮긴다.

    저장해둔 인자(params_json)로만 실행하므로 승인 화면에 표시된 것과 실제
    실행되는 것이 어긋날 수 없다. 인자 대조 단계가 아예 필요 없어진다.

    Returns: (status, result_dict) — status 는 'executed' 또는 'failed'.
    """
    import json as _json
    from aot.databases.models import MCPConfirmation

    row = MCPConfirmation.query.filter_by(unique_id=confirmation_id).first()
    if row is None:
        return 'failed', {"status": "error", "message": "confirmation not found"}

    try:
        params = _json.loads(row.params_json or '{}')
    except Exception:
        params = {}

    try:
        # 실행 자체는 MCP 서버의 디스패치를 그대로 쓴다. 여기서 같은 로직을 다시
        # 구현하면(핸들러 시그니처에 맞춘 메타키 제거 등) 두 벌이 서로 어긋난다.
        from aot.aot_mcp_server import _dispatch_virtual_tool, _NATIVE_TOOLS

        call_args = inject_agent(row.tool_name, strip_meta(params), row.agent_id)
        if row.tool_name in _NATIVE_TOOLS:
            from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
            result = AoTNativeToolEngine.execute(row.tool_name, call_args)
        else:
            result = _dispatch_virtual_tool(row.tool_name, call_args)
        status = 'executed'
    except Exception as exc:
        logger.exception('[MCPGate] 승인 즉시 실행 실패 tool=%s confirmation=%s',
                         row.tool_name, confirmation_id)
        result = {"status": "error", "message": str(exc)}
        status = 'failed'

    if not isinstance(result, dict):
        result = {"result": result}

    # 도구는 내부 실패를 예외가 아니라 {"status": "error"} 나 {"error": ...} 로
    # 돌려주기도 한다. 예외만 보고 'executed' 를 적으면 감사 기록이 거짓말을 한다 —
    # 2026-08-09 koat 밸브 건이 정확히 이 모양이었다(status='executed' 인데
    # result_json 안에는 SQL 에러, 밸브는 열리지 않음). 재호출 경로는 'executed' 와
    # 'failed' 를 이미 같이 처리하므로(2단계 replay 분기) 값이 늘어도 안전하다.
    if status == 'executed' and (result.get('status') == 'error' or result.get('error')):
        status = 'failed'
        logger.warning('[MCPGate] 도구가 오류를 반환해 failed 로 기록 tool=%s confirmation=%s',
                       row.tool_name, confirmation_id)

    row.status = status
    try:
        row.result_json = _json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        row.result_json = _json.dumps({"status": status})
    row.save()

    logger.info('[MCPGate] 승인 즉시 실행 tool=%s confirmation=%s -> %s',
                row.tool_name, confirmation_id, status)
    return status, result


def approve(confirmation_id, user_id=None):
    return _decide(confirmation_id, 'approved', user_id)


def reject(confirmation_id, user_id=None):
    return _decide(confirmation_id, 'rejected', user_id)
