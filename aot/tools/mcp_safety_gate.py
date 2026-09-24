# coding=utf-8
"""
mcp_safety_gate.py — 외부 MCP 경로(aot_mcp_server.py)의 안전·감사 게이트.

외부 AI가 MCP로 접속해 상태를 점검하고 제어를 조언하는 경로에서,
"누가(agent_id) 무엇을 왜(reason) 호출했는지"를 남기고 쓰기 도구는
사람 승인을 거치게 만드는 계층이다.

`aot/mcp_server/safety.py`(FastMCP 트랙)를 대체한다. 그 구현을 그대로
쓸 수 없는 이유가 두 가지 있고, 여기서 둘 다 바로잡는다:

  1. WRITE_TOOLS 가 그 트랙 전용 소수 도구(update_method_point 등)로 하드코딩돼
     있어, 활성 서버의 실제 쓰기 도구(operate_device, set_output_state,
     설비 CRUD …)는 검사를 그냥 통과한다 — 있는 척하는 무동작이 된다.
     → 여기서는 tool_registry(SSOT)의 approval_required_tools() 에서 파생한다.
     레지스트리에 도구를 mutating/physical(또는 기록 쓰기 record_write)로 선언하면
     자동으로 게이트에 걸린다.

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
META_KEYS = frozenset({'_reason', '_agent_id', '_confirmation_id', '_title'})

# tool_name → 사람이 읽는 동작 설명. 승인 화면은 절대 tool_name 원문을 보여주지
# 않는다("operate_device" 같은 내부 식별자를 일반 사용자가 볼 이유가 없다) —
# LLM 이 _title 을 안 보내는 경우의 서버 쪽 최종 폴백이 이 표다.
_TOOL_ACTION_LABELS = {
    'operate_device': '장치 제어',
    'set_output_state': '장치 상태 변경',
    'schedule_device_control': '장치 제어 예약',
    'add_schedule_batch': '작업 일정 등록',
    'modify_sequence_step': '시퀀스 단계 수정',
    'modify_sequence_schedule': '시퀀스 일정 수정',
    'modify_function_options': '함수 설정 변경',
    'create_notice': '공지 작성',
    'modify_notice': '공지 수정',
    'delete_notice': '공지 삭제',
    'edit_schedule': '일정 수정',
    'delete_schedule': '일정 삭제',
    'create_function': '함수 생성',
    'delete_function': '함수 삭제',
    'create_sequence_function': '시퀀스 함수 생성',
}


def _resolve_device_display_name(device_id):
    """장치 unique_id → 사람이 읽는 이름. Output/Input 어느 쪽에도 없으면 None —
    실패해도 제목 합성 전체를 막지 않기 위해 예외를 삼킨다."""
    if not device_id:
        return None
    try:
        from aot.databases.models import Output, Input
        for model in (Output, Input):
            row = model.query.filter_by(unique_id=device_id).first()
            if row is not None and getattr(row, 'name', None):
                return row.name
    except Exception:
        logger.exception('[MCPGate] 장치 이름 조회 실패 (device_id=%s) — id 그대로 사용', device_id)
    return None


def synthesize_title(tool_name, params):
    """LLM 이 _title 을 안 보냈을 때 서버가 대신 만드는 제목.

    우선순위: (1) 도구 자체가 이미 사람이 쓴 제목을 담고 있는 필드
    (create_notice/modify_notice 의 'title')를 그대로 재사용 — 이중으로
    지어낼 필요가 없다. (2) device_id + state 조합이면 "장치명 켜기/끄기"
    처럼 실제 동작을 서술. (3) 그 외엔 도구 이름을 사람이 읽는 동작
    설명으로 치환한 표를 쓴다. 절대 tool_name 원문을 그대로 반환하지
    않는다 — 표에 없는 새 도구가 추가되면 여기도 같이 채울 것.
    """
    params = params or {}
    existing_title = params.get('title')
    if isinstance(existing_title, str) and existing_title.strip():
        return existing_title.strip()

    label = _TOOL_ACTION_LABELS.get(tool_name, tool_name)
    device_id = params.get('device_id')
    state = params.get('state')
    if device_id and state in ('on', 'off'):
        name = _resolve_device_display_name(device_id) or device_id
        verb = '켜기' if state == 'on' else '끄기'
        # "지금 실행"(operate_device/set_output_state)과 "나중에 실행되도록
        # 예약"(schedule_device_control)은 승인자 입장에서 완전히 다른
        # 동작이다 — 둘 다 "{장치명} 켜기"로만 나오면 예약인 줄 모르고
        # 즉시 실행으로 오인할 수 있다(2026-09-09 로컬 검증 중 실제로
        # 구분이 안 되는 걸 확인).
        if tool_name == 'schedule_device_control':
            return f"{name} {verb} 예약"
        return f"{name} {verb}"
    if device_id:
        name = _resolve_device_display_name(device_id) or device_id
        return f"{name} {label}"
    return label

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
        from aot.tools.tool_registry import write_tools as _reg_write
        return frozenset(_reg_write()) | _NATIVE_WRITE_TOOLS
    except Exception:
        # 레지스트리를 못 읽으면 게이트가 조용히 열리는 대신 네이티브 목록만이라도 막는다.
        logger.exception('[MCPGate] tool_registry 로드 실패 — 네이티브 쓰기 목록만 적용')
        return _NATIVE_WRITE_TOOLS


def approval_tools() -> frozenset:
    """사람 승인이 필요한 도구 이름 집합 (레지스트리 SSOT + 네이티브 물리 도구)."""
    try:
        from aot.tools.tool_registry import approval_required_tools
        return frozenset(approval_required_tools()) | _NATIVE_WRITE_TOOLS
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 네이티브 쓰기 목록만 적용')
        return _NATIVE_WRITE_TOOLS


def config_only_tools() -> frozenset:
    """쓰기지만 승인이 면제된 설정 편집 도구 — tool_registry 의 _CONFIG_ONLY 주석 참고.

    레지스트리를 못 읽으면 **빈 집합**을 돌려준다. 여기서 실패가 면제 쪽으로
    기울면 게이트가 통째로 열린다 — 모르면 승인을 요구하는 쪽이 맞다."""
    try:
        from aot.tools.tool_registry import config_only_tools as _reg_config
        return frozenset(_reg_config())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 승인 면제 없음으로 처리')
        return frozenset()


# 레지스트리를 못 읽을 때의 폴백. 여기서 실패가 '읽기' 쪽으로 기울면 노트·지식
# 쓰기가 누구에게나 열린다(2026-09-23 고친 구멍 그대로) — 이름이라도 고정해 둔다.
_RECORD_WRITE_FALLBACK = frozenset({'create_note', 'knowledge_shelve', 'note'})
_ADVISORY_WRITE_FALLBACK = frozenset({'submit_advice'})


def record_write_tools() -> frozenset:
    """기록만 저장하는 쓰기(노트·지식) — tool_registry 의 _RECORD_WRITE 주석 참고.

    write_tools() 의 부분집합이다(역할·읽기 전용 키·그룹 스코프가 그대로 적용).
    승인은 면제되지만, 필요 역할은 제어 권한이 아니라 웹과 같은 edit_settings 다."""
    try:
        from aot.tools.tool_registry import record_write_tools as _reg_record
        return frozenset(_reg_record())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 기록 쓰기 폴백 목록 적용')
        return _RECORD_WRITE_FALLBACK


def plot_write_tools() -> frozenset:
    """작기 운영 쓰기(구획·단계·자원·작기 프로그램·구획 일지) — tool_registry.
    plot_write_tools 참고. 필요 역할은 웹과 같은 `edit_plots`.

    레지스트리를 못 읽으면 **빈 집합** — 그러면 제어 권한을 요구하는 쪽으로
    기운다(모르면 좁게)."""
    try:
        from aot.tools.tool_registry import plot_write_tools as _reg_plot
        return frozenset(_reg_plot())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 작기 쓰기 없음으로 처리')
        return frozenset()


def required_write_permission(tool_name) -> str:
    """이 쓰기 도구에 필요한 역할 권한 이름 — 웹의 같은 동작과 같은 것.

      - 기록 쓰기(노트·지식)            → `edit_settings` (웹 노트·지식 화면)
      - 작기 운영(구획·프로그램 등)      → `edit_plots`    (웹 구획 화면)
      - 그 밖의 쓰기(제어·설정 편집)    → `edit_controllers`

    외부 MCP 게이트·인앱 요청자 판정·채팅 제안 승인이 모두 이 표를 쓴다."""
    if tool_name in record_write_tools():
        return 'edit_settings'
    if tool_name in map_edit_tools():
        return 'edit_settings'
    if tool_name in plot_write_tools():
        return 'edit_plots'
    return 'edit_controllers'


def map_edit_tools() -> frozenset:
    """지도 편집 쓰기(도형 삭제·장치 배치) — 웹 지도 편집(`routes_geo_shape`)과
    같은 `edit_settings` 가 필요하다. tool_registry._SPACE_NON_PLOT_WRITES 참고.

    레지스트리를 못 읽으면 고정 이름 — 모르면 좁게(설정 편집을 요구)."""
    try:
        from aot.tools.tool_registry import map_edit_tools as _reg_map
        return frozenset(_reg_map())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 지도 편집 폴백 목록')
        return frozenset({'delete_geo_shape', 'set_device_location'})


def role_allows_tool(role, tool_name) -> bool:
    """MCP 키 역할(RoleInfo) 또는 DB `Role` 행이 이 쓰기 도구를 해도 되는가.

    표는 `required_write_permission` 하나다. RoleInfo 는 읽기 전용 키가 이미
    쓰기 칸을 꺼 두었으므로 그 칸으로, DB 행은 웹과 같은 함의 규칙
    (`mcp_auth.role_row_allows`)으로 본다."""
    from aot.tools import mcp_auth
    perm = required_write_permission(tool_name)
    if role is None:
        return False
    if hasattr(role, 'can_write'):           # RoleInfo 스냅샷
        if perm == 'edit_settings':
            return mcp_auth.role_can_record(role)
        if perm == 'edit_plots':
            return mcp_auth.role_can_edit_plots(role)
        return mcp_auth.role_can_write(role)
    return mcp_auth.role_row_allows(role, perm)


def role_can_decide_any(role) -> bool:
    """승인 대기 항목 중 하나라도 결정할 수 있는 역할인가 — 제어·작기 운영·
    설정 편집 중 하나(작기 운영은 설정 편집이 함의)."""
    from aot.tools import mcp_auth
    if role is None:
        return False
    if hasattr(role, 'can_write'):
        return (mcp_auth.role_can_write(role) or mcp_auth.role_can_edit_plots(role)
                or mcp_auth.role_can_record(role))
    return (mcp_auth.role_row_allows(role, 'edit_controllers')
            or mcp_auth.role_row_allows(role, 'edit_plots'))


def advisory_write_tools() -> frozenset:
    """조언 원장(submit_advice). 감사에는 쓰기로 남지만 write_tools() 밖이다 —
    읽기 전용 키와 조언 전용 모드에서도 낼 수 있어야 하기 때문이다."""
    try:
        from aot.tools.tool_registry import advisory_write_tools as _reg_adv
        return frozenset(_reg_adv())
    except Exception:
        logger.exception('[MCPGate] tool_registry 로드 실패 — 조언 폴백 목록 적용')
        return _ADVISORY_WRITE_FALLBACK


def approval_exempt_writes() -> frozenset:
    """쓰기지만 승인을 받지 않는 도구 전부 — 감사 로그에 'not_required' 로 남는다."""
    return config_only_tools() | record_write_tools() | advisory_write_tools()


def classify_permission(tool_name: str) -> str:
    """'write' (무언가를 저장·변경) 또는 'read'. 승인 필요 여부와는 별개다.

    조언 제출도 행을 저장하므로 'write' 다 — 감사 로그가 그것을 조회로 적으면
    안 된다. 조언이 읽기 전용 키에 열려 있는 것은 gate() 가 따로 다룬다."""
    if tool_name in write_tools() or tool_name in advisory_write_tools():
        return 'write'
    return 'read'


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
        from aot.tools.aot_data_tool_service import AoTDataToolService

        target_name = args.get('target_name')
        if target_name:
            r = AoTDataToolService.resolve_target_tool(target_name)
            if r.get('error') == 'ambiguous_name':
                cands = r.get('candidates') or []
                lines.append(f"'{target_name}' names {len(cands)} different places/devices "
                             f"- nothing will be picked; the request must say which one:")
                for c in cands[:10]:
                    lines.append(f"  - {c.get('type')} '{c.get('name')}' at "
                                 f"{c.get('where') or '?'}"
                                 + (f" (name it '{c['use_name']}')" if c.get('use_name') else ''))
            elif r.get('status') == 'needs_disambiguation':
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


#: 처리기가 target_name 을 `_resolve_note_target` 으로 풀고, 모호하면 거절하는
#: 승인 대상 쓰기 도구. (add_schedule 은 승인 면제라 게이트를 먼저 빠져나간다 —
#: 처리기가 직접 거절한다.)
_TARGET_NAME_WRITE_TOOLS = frozenset({'create_note', 'edit_schedule', 'add_schedule'})


def _ambiguous_target_refusal(tool_name, arguments):
    """모호한 target_name 이면 처리기와 같은 거절 응답, 아니면 None."""
    args = arguments or {}
    if tool_name not in _TARGET_NAME_WRITE_TOOLS:
        return None
    target_name = args.get('target_name')
    if not target_name or args.get('target_id'):
        return None
    try:
        from aot.tools.aot_data_tool_service import AoTDataToolService
        amb = AoTDataToolService._ambiguous_places(target_name)
        if not amb:
            return None
        out = AoTDataToolService._ambiguity_refusal(target_name, amb)
    except Exception:
        logger.exception('[MCPGate] 모호한 이름 사전검사 실패 (검사 없이 진행)')
        return None
    out = dict(out, reason_code="ambiguous_target", tool_name=tool_name)
    out["message"] += " No approval was requested."
    return out


#: 조언 전용 모드 거절에 붙는 한 문장 — 이 모드는 **서버 전체** 설정이라 키의
#: 권한·도구 묶음과 무관하다. 프로필 벤치마크(26-09-24, 432회) lat_24 운영
#: 키에서 모델이 이 거절을 보고 "키를 설정 묶음으로 바꾸라" 고 안내했다 —
#: 서버 안내문의 묶음 전환 안내를 끌어다 썼다. 전환 안내는 reason_code
#: 'tool_profile' 에만 붙고(tool_execution._profile_refusal_body), 여기서는
#: 그 안내가 이 거절에 맞지 않는다고 말한다.
WRITE_DISABLED_SCOPE = (
    "This is a server-wide setting, not this key's permissions or tool "
    "profile - switching the key or its tool profile would not change it, so "
    "do not suggest that.")


def role_refusal(tool_name, role):
    """게이트가 **역할·조언 전용 모드**로 거절할 때의 본문. 아니면 None.

    부작용이 없다(승인 큐·레이트 리밋을 건드리지 않는다). 게이트가 맨 앞에서
    쓰고, 인자 사전 검증(tool_execution._pre_gate_validation)이 "인자를 고쳐도
    어차피 거절된다" 를 같은 메시지에 싣는 데 쓴다 — 고쳐 다시 부르는 헛걸음을
    막는다."""
    from aot.tools.mcp_auth import (role_can_advise, role_can_edit_plots,
                                    role_can_record, role_can_write)

    # 조언 제출 — 쓰기 거부 안내가 권하는 통로라 읽기 전용 키와 조언 전용
    # 모드에도 열려 있다. AI 자체를 쓸 수 없는 역할(use_ai_chat 없음)만 막는다.
    # 승인·레이트 리밋은 붙이지 않는다(예전과 같다).
    if tool_name in advisory_write_tools():
        if not role_can_advise(role):
            return {
                "status": "refused",
                "reason_code": "insufficient_role",
                "message": ("Your MCP key's role is not allowed to use the AI "
                            "assistant, so it cannot submit advice. Do not retry."),
                "tool_name": tool_name,
            }
        return None

    if classify_permission(tool_name) == 'read':
        return None

    # 기록 쓰기(노트·지식) — 승인은 없지만 쓰기다. 역할 기준은 웹과 같은
    # edit_settings, 조언 전용 모드에서는 거부한다. 그룹 스코프는 호출자
    # (_execute_tool)가 이 게이트보다 먼저 write_tools() 기준으로 본다.
    if tool_name in record_write_tools():
        if not role_can_record(role):
            return {
                "status": "refused",
                "reason_code": "insufficient_role",
                "message": ("Your MCP key's role cannot save notes or knowledge "
                            "entries here — that needs the same settings-edit "
                            "permission as the web notes page (read-only keys "
                            "never have it). Do not retry; if the point matters, "
                            "record it with submit_advice instead."),
                "tool_name": tool_name,
            }
        if not is_write_enabled():
            return {
                "status": "refused",
                "reason_code": "write_disabled",
                "message": ("This server is in advice-only mode "
                            "(AOT_MCP_WRITE_ENABLED=0). Notes and knowledge "
                            "entries cannot be saved - record the point with "
                            "submit_advice instead. " + WRITE_DISABLED_SCOPE),
                "tool_name": tool_name,
            }
        return None

    # 작기 운영 쓰기(구획·단계·자원·작기 프로그램) — 웹 구획 화면과 같은
    # edit_plots(설정 편집이 함의). 제어 권한을 요구하면 웹과 갈라진다: 작기만
    # 맡은 사람은 막히고, 제어만 가진 사람은 웹에서 못 하는 구획 편집을 AI 로
    # 하게 된다. 역할만 다르고 나머지(조언 전용 모드·승인)는 다른 쓰기와 같다.
    if tool_name in map_edit_tools():
        # 지도 편집(도형 삭제·장치 배치) — 웹 지도 편집과 같은 설정 편집 권한.
        if not role_can_record(role):
            return {
                "status": "refused",
                "reason_code": "insufficient_role",
                "message": ("Your MCP key's role cannot edit the map (delete "
                            "shapes or place devices) — that needs the same "
                            "settings-edit permission as the web map editor "
                            "(read-only keys never have it). Do not retry; state "
                            "what should be done and why as advice instead."),
                "tool_name": tool_name,
            }
    elif tool_name in plot_write_tools():
        if not role_can_edit_plots(role):
            return {
                "status": "refused",
                "reason_code": "insufficient_role",
                "message": ("Your MCP key's role cannot change plots, crop "
                            "programmes or stage records — that needs the same "
                            "plot-edit permission as the web plot pages "
                            "(read-only keys never have it). Do not retry; state "
                            "what should be done and why as advice instead."),
                "tool_name": tool_name,
            }
    elif not role_can_write(role):
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
                "as advice instead. " + WRITE_DISABLED_SCOPE),
            "tool_name": tool_name,
        }

    return None


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
    refused = role_refusal(tool_name, role)
    if refused is not None:
        return refused
    # 역할 검사를 지난 조언 제출·읽기·기록 쓰기는 승인 없이 통과한다.
    if (tool_name in advisory_write_tools()
            or classify_permission(tool_name) == 'read'
            or tool_name in record_write_tools()):
        return None

    # 설정 편집 도구는 여기서 통과시킨다 — 역할 검사와 write_enabled 검사를
    # 지난 **뒤**여야 한다. 앞에 두면 읽기 전용 키가 설정을 고칠 수 있고,
    # 조언 전용 모드(AOT_MCP_WRITE_ENABLED=0)도 뚫린다.
    # 승인만 면제될 뿐 쓰기는 쓰기다: 호출자는 위에서 이미 걸러졌고,
    # 감사 로그에는 호출자 순서상 write 로 남는다.
    if tool_name in config_only_tools():
        return None

    from aot.databases.models import MCPConfirmation

    confirmation_id = (arguments or {}).get('_confirmation_id')

    # 이름이 여러 곳에 걸린 쓰기는 사람에게 승인을 묻기 **전에** 돌려보낸다.
    # 처리기가 어차피 거절하므로(`_ambiguity_refusal`), 승인을 받아 봐야 실행
    # 단계에서 실패한다 — 사람은 이미 승인 버튼을 누른 뒤다.
    if not confirmation_id:
        _amb = _ambiguous_target_refusal(tool_name, arguments)
        if _amb:
            return _amb

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
                title=(arguments or {}).get('_title') or synthesize_title(tool_name, arguments),
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
                title=(arguments or {}).get('_title') or synthesize_title(tool_name, arguments),
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
            from aot.tools.aot_data_tool_service import AoTDataToolService
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
        title=(arguments or {}).get('_title') or synthesize_title(tool_name, arguments),
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
            from aot.tools.aot_data_tool_service import AoTDataToolService
            _resolved = AoTDataToolService.resolve_target_tool(_target_name)
            if _resolved.get('status') == 'needs_disambiguation':
                response['resolved_scope'] = {
                    "status": "needs_disambiguation",
                    "message": _resolved.get('message'),
                }
                if _resolved.get('candidates'):
                    response['resolved_scope']['candidates'] = _resolved['candidates']
                else:
                    response['resolved_scope']['available_targets'] = \
                        _resolved.get('available_targets')
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

def list_pending(limit=50, viewer=None):
    """승인 대기 목록 (만료된 항목은 조회 시점에 정리).

    viewer: 보는 사람의 역할(RoleInfo 또는 DB `Role` 행). 주면 항목마다
        `can_decide` 를 싣는다 — 그 역할이 이 항목을 승인·거부할 수 있는가
        (`role_allows_tool`, 승인 경로와 같은 표). 작기 운영만 맡은 사람에게는
        구획 요청에만 버튼이 보이게 하려는 것이고, 막는 것은 `_decide` 다."""
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
        params = json.loads(r.params_json or '{}')
        out.append({
            "confirmation_id": r.unique_id,
            # title 은 화면에 보일 유일한 헤드라인이다 — tool_name 원문은 절대
            # 프런트에 안 보낸다(내부 식별자 노출 금지). 마이그레이션 이전에
            # 만들어진 행 등 title 이 비어 있는 경우를 대비해 그때그때 합성한다.
            "title": r.title or synthesize_title(r.tool_name, params),
            "tool_name": r.tool_name,
            "params": params,
            "reason": r.reason,
            "agent_id": r.agent_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_in_sec": max(0, int((r.expires_at - datetime.utcnow()).total_seconds())),
        })
        if viewer is not None:
            out[-1]["can_decide"] = role_allows_tool(viewer, r.tool_name)
    return out


def validate_modified_params(original_params: dict, modified_params: dict):
    """승인 전 수정이 안전한 범위인지 검사한다.

    화면에 보인 값 = 실제 실행값 원칙(execute_approved 참고)은 지키면서,
    그 "보인 값" 자체를 사람이 고칠 수 있게 하는 게 이 함수의 목적이다. 그래서
    의도적으로 딱 두 가지만 본다:

      1. 키 집합이 원본과 정확히 같아야 한다. 위젯 UI가 원본의 모든 키를
         프리필한 편집 폼을 보여주므로 정상 흐름에선 항상 일치한다 — 다르면
         승인 화면에 없던 필드가 몰래 끼어든 것(예: 안전장치 우회 플래그)이라
         의심하고 막는다. 새 키 추가도, 기존 키 누락도 모두 거부.
      2. 각 값의 타입이 원본과 같아야 한다(bool 은 int 의 서브클래스라 별도 처리).
         원본이 None 이면 원래 타입을 알 수 없으니 통과시킨다 — 그 경우는
         실행층(도구 핸들러)이 타입 오류를 내면 status='failed' 로 정상 기록된다.

    도구별 의미 검증(장치 id 실존 여부, 열거값 범위 등)은 하지 않는다 — 그건
    이미 execute_approved() 가 위임하는 실행층의 몫이다.

    Returns: (ok: bool, error_message: str|None, cleaned: dict|None)
    """
    orig = strip_meta(original_params or {})
    mod = strip_meta(modified_params or {})

    if set(mod.keys()) != set(orig.keys()):
        extra = sorted(set(mod.keys()) - set(orig.keys()))
        missing = sorted(set(orig.keys()) - set(mod.keys()))
        return False, (
            f"Modified params must have exactly the original keys. "
            f"Unexpected: {extra}, missing: {missing}"), None

    for key, orig_val in orig.items():
        new_val = mod[key]
        if orig_val is None:
            continue  # 원래 타입을 몰라 판단 불가 — 실행층 실패로 위임
        if isinstance(orig_val, bool) or isinstance(new_val, bool):
            if isinstance(orig_val, bool) != isinstance(new_val, bool):
                return False, f"Field '{key}' type mismatch (expected bool).", None
            continue
        if isinstance(orig_val, (int, float)) and not isinstance(new_val, (int, float)):
            return False, f"Field '{key}' must be a number.", None
        if isinstance(orig_val, str) and not isinstance(new_val, str):
            return False, f"Field '{key}' must be a string.", None
        if isinstance(orig_val, list) and not isinstance(new_val, list):
            return False, f"Field '{key}' must be an array.", None
        if isinstance(orig_val, dict) and not isinstance(new_val, dict):
            return False, f"Field '{key}' must be an object.", None

    try:
        json.dumps(mod, ensure_ascii=False)
    except Exception:
        return False, "Modified params are not JSON-serializable.", None

    return True, None, mod


def _normalize_device_id_for_scope(tool_name, params):
    """PHYSICAL_TOOLS 의 `device_id` 가 이름이면 uuid 로 바꾼 복사본을 돌려준다.

    아래 `_approval_scope_denial()`이 쓰는 `scope.can_operate_tool_call()`은
    인자 **값**만 훑어 uuid 모양을 찾는다(`docs/design/access-scope-groups.md`
    §6-2 — 도구 59개의 인자 이름이 제각각이라 이름으로 찾으면 새 도구가 다른
    이름을 쓰는 순간 조용히 샌다). 그런데 `device_id`는 이름도 받는다 —
    실행층(operate_device_tool·schedule_device_control_tool)이 `resolve_output`
    으로 해석하는 것과 같다 — 이름 그대로면 uuid 모양이 아니라서 그 스캔에
    아예 안 걸린다. 여기서 미리 풀어 스캔이 보게 만든다.

    해석 실패(없음·이름 겹침)면 원래 값 그대로 둔다 — 스코프가 아니라 실행
    단계가 이미 "그런 장치 없음" 으로 막으므로 여기서 막을 이유가 없다.
    """
    if tool_name not in PHYSICAL_TOOLS or not isinstance(params, dict):
        return params
    device_id = params.get('device_id')
    if not device_id:
        return params
    from aot.services.resolvers.device_resolver import resolve_output
    # `allow_partial=True` — `schedule_device_control_tool` 이 실행 시점에
    # 부분 이름까지 허용한다(`aot_data_tool_service.py`). 여기서 `False` 로
    # 좁히면 부분 일치로만 찾아지는 이름은 스코프 검사에서 "장치 없음"이 되어
    # 통과해 버리고, 곧이어 실행층은 그 이름을 찾아내 그대로 돌려버린다 —
    # 승인 시점과 실행 시점이 다른 장치를 보는 구멍이 생긴다.
    match = resolve_output(device_id, allow_partial=True)
    if match.row is None:
        return params
    normalized = dict(params)
    normalized['device_id'] = match.row.unique_id
    return normalized


def _approval_scope_denial(tool_name, params, user=None):
    """승인자가 이 요청의 대상(들)을 조작할 그룹 스코프 권한이 있는가.

    호출 시점 검사(`tool_execution._scope_refusal` → `scope.can_operate_tool_call`)
    와 **같은 정본**을 쓴다 — 승인 경로만 따로 인자 이름(예: `device_id`)을
    하드코딩해 판정하면, 새 물리 도구가 다른 이름을 쓰거나 스코프 대상이
    장치가 아닌 탭·대시보드·지도일 때 조용히 새고, 그 사실은 남의 자원이
    움직인 뒤에야 드러난다.

    직접 제어 경로(`routes_general.output_mod`)는 역할 검사 뒤에 항상
    `scope.can_operate_device()` 로 "이 장치를" 다룰 수 있는지도 본다. 승인
    경로는 2026-09-18에 역할 검사(`edit_controllers`)만 추가됐을 뿐 그룹은
    보지 않아서, 편집자 역할이지만 다른 그룹 소속인 사람이 승인 화면에서
    남의 그룹 자원의 쓰기 요청을 승인하면 그대로 실행됐다. 이 함수가 그
    구멍을 막는다.

    `user` 는 **승인자**여야 한다(`_decide`가 `user_id`로 조회한 행) — 넘기지
    않으면 `scope.can_operate_tool_call`이 `flask_login.current_user`로
    암묵적으로 찾는데, 그건 웹 승인 화면에만 맞고 MCP `respond_to_confirmation`
    처럼 실제 로그인 세션이 없는 호출자에게는 아무도 아닌 사람이 되어 늘
    거부로 샌다.

    거부해도 `MCPConfirmation` 상태는 바꾸지 않는다 — 호출자(`_decide`)가
    저장하기 전에 이 결과로 그냥 반환해 pending 을 유지하고, 권한 있는
    다른 승인자가 다시 볼 수 있게 한다.

    Returns: None(통과) 또는 (denied_uuid, message) — 거부.
    """
    from aot.aot_flask.access import scope
    normalized = _normalize_device_id_for_scope(tool_name, params)
    # 이름(target_name·옛 별칭)으로 준 대상도 호출 시점 판정과 같이 풀어 본다
    # — 승인자 판정만 uuid 를 훑으면 이름으로 준 요청은 남의 그룹 대상이어도
    # 승인 단계에서 통과한다.
    from aot.tools.tool_execution import scope_arguments
    allowed, denied_uuid = scope.can_operate_tool_call(
        tool_name, scope_arguments(tool_name, normalized), user=user)
    if allowed:
        return None
    return denied_uuid, scope.deny_message()


def _approver_role_denial(tool_name, user_id=None, role=None):
    """결정하는 사람의 역할이 이 도구의 쓰기 권한을 갖는가. 막으면 문구.

    승인은 "대신 눌러 주는 것" 이라 직접 할 자격보다 넓을 수 없다. 예전에는
    무엇이든 `edit_controllers` 하나로 봤다 — 제어만 가진 사람이 구획 편집을
    승인하고, 작기 운영만 맡은 사람은 자기 구획 요청도 못 결정했다. 이제 도구
    별 권한(`required_write_permission` — 노트·지식·지도 편집 `edit_settings`,
    작기 운영 `edit_plots`, 나머지 `edit_controllers`)을 본다.

      - role: MCP `respond_to_confirmation` 의 키 역할(RoleInfo — 읽기 전용
        키는 쓰기 칸이 꺼져 있다).
      - user_id: 결정한 사람(웹 승인·MCP 키 소유자). DB 역할로 본다.

    둘 다 없으면(인증을 끈 설치의 옛 호출) 판정 근거가 없어 막지 않는다.
    """
    perm = required_write_permission(tool_name)
    if role is not None and not role_allows_tool(role, tool_name):
        return 'Insufficient permission: %s' % perm
    if user_id:
        from aot.databases.models import Role, User
        user = User.query.filter(User.unique_id == user_id).first()
        row = (Role.query.filter(Role.id == user.role_id).first()
               if user is not None else None)
        if not role_allows_tool(row, tool_name):
            return 'Insufficient permission: %s' % perm
    return None


def _decide(confirmation_id, status, user_id=None, modified_params=None,
            role=None):
    from aot.databases.models import MCPConfirmation

    row = MCPConfirmation.query.filter_by(unique_id=confirmation_id).first()
    if row is None:
        return {"status": "error", "message": "No such confirmation."}
    # 역할 — 승인·거부 모두. 상태를 바꾸지 않고 돌려준다(권한 있는 다른
    # 사람이 그대로 결정할 수 있게).
    _role_denial = _approver_role_denial(row.tool_name, user_id=user_id,
                                         role=role)
    if _role_denial:
        return {"status": "error", "reason_code": "insufficient_role",
                "message": _role_denial}
    if row.status in ('consumed', 'rejected'):
        return {"status": "error", "message": f"Already handled (status={row.status})."}
    if row.is_expired():
        row.status = 'expired'
        row.save()
        return {"status": "error", "message": "The confirmation expired."}

    cleaned = None
    if status == 'approved' and modified_params is not None:
        original = json.loads(row.params_json or '{}')
        ok, err, cleaned = validate_modified_params(original, modified_params)
        if not ok:
            # 검증 실패는 "거부"가 아니라 "요청 자체가 무효" — 상태를 바꾸지
            # 않고 pending 그대로 둬서 다른 값으로 다시 시도할 수 있게 한다.
            return {"status": "error", "message": err}
        row.modified_params_json = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)

    if status == 'approved':
        # 승인자 신원 — `user_id` 가 있으면 **반드시** 그 사람으로 판정한다.
        # `scope.can_operate_tool_call()` 의 암묵적 `flask_login.current_user`
        # 폴백에 맡기면, 실제 로그인 세션이 없는 MCP `respond_to_confirmation`
        # 경로(`user_id` 는 있지만 요청 컨텍스트의 current_user 는 미인증)에서
        # 그룹 소속과 무관하게 항상 거부로 샌다.
        approving_user = None
        if user_id:
            from aot.databases.models import User
            approving_user = User.query.filter(
                User.unique_id == user_id).first()

        # 승인 직전, 실행될 최종 인자(수정됐으면 그 값)를 기준으로 그룹
        # 스코프를 본다 — execute_approved() 가 고르는 것과 같은 우선순위.
        # `cleaned` 가 이미 파싱된 dict 라 있으면 그걸 쓰고, 없으면(수정 없이
        # 승인) 저장된 원본을 새로 읽는다 — 방금 만든 값을 직렬화했다가
        # 곧바로 다시 파싱하지 않는다.
        if cleaned is not None:
            effective_params = cleaned
        else:
            try:
                effective_params = json.loads(row.params_json or '{}')
            except Exception:
                # 저장된 인자 자체를 못 읽으면 무엇을 승인하는지 확인할 수
                # 없다 — 통과시키지 않는다(그 밖의 실패는 전부 pending 유지·
                # 거부로 처리하는 이 함수의 다른 분기들과 같은 방향).
                logger.error(
                    '[MCPGate] 승인 대상 인자 파싱 실패, 안전하게 거부 '
                    'confirmation=%s', confirmation_id)
                return {"status": "error",
                        "message": "Stored confirmation parameters are "
                                   "corrupted.",
                        "reason_code": "group_scope_denied"}

        try:
            denial = _approval_scope_denial(row.tool_name, effective_params,
                                            user=approving_user)
        except Exception:
            # 판정이 깨지면 승인하지 않는다(pending 유지).
            logger.exception('[MCPGate] 승인자 스코프 판정 실패 — 거부로 닫는다')
            denial = (None, 'permission check failed')
        if denial is not None:
            denied_uuid, message = denial
            # `target_type='Output'` 은 PHYSICAL_TOOLS(이 구멍의 원래 대상)
            # 기준이다 — `can_operate_tool_call` 이 이제 탭·대시보드·지도까지
            # 훑으므로 이론적으로는 다른 종류도 거부될 수 있지만, 그 경우도
            # `audit.OUTPUT_CONTROL` 이 "그룹 스코프가 뭔가를 막았다"는 감사
            # 기록 자체는 정확히 남긴다(분류만 근사치).
            from aot.utils import audit
            from aot.utils.audit import audit_log
            audit_log(audit.OUTPUT_CONTROL, target_type='Output',
                      target_id=denied_uuid, result='failure',
                      detail='denied by group scope')
            return {"status": "error", "message": message,
                    "reason_code": "group_scope_denied"}

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


#: 쓰기가 **일어나지 않은** 응답에 붙이는 해석 규칙(2026-09-23 재측정 P1·P6).
#:
#: 거부 응답의 `message` 는 "왜 거부됐나·다음에 무엇을 하라" 만 말했다. 그러자
#: 모델이 거부 뒤 submit_advice 를 부르고 "완료했습니다" 라고 보고했고(lat_20·22,
#: 4건), 거부된 변경을 조언으로 풀어 쓰면서 앞 조회에서 본 id 를 그대로
#: 옮겼다(UUID 노출 14건 중 13건이 거부 직후 답). 모델마다 message 를 다르게
#: 읽으므로, 사람에게 무엇을 말해야 하는지를 한 곳에서 기계 칸(`performed`)과
#: 짧은 규칙으로 함께 싣는다. 도구 설명이 아니라 응답에 싣는다 — 이 규칙은
#: 거부됐을 때만 필요하다.
NOT_PERFORMED_READING = (
    "The requested change was NOT made. Tell the user plainly that it was not "
    "applied and why; do not describe it as done.")
#: 도구가 오류로 끝난 쓰기 — 인자를 고쳐 다시 부를 수 있으니 재시도를 막지 않는다.
FAILED_READING = (
    "The requested change was NOT made. Fix and retry, or tell the user "
    "plainly that it was not applied and why; do not describe it as done.")
PENDING_READING = (
    "Not done yet - it is waiting for a person to approve it. Say so; do not "
    "describe it as done.")
DISAMBIGUATION_READING = "Nothing was changed. Ask the user which one they meant."
#: 후보를 되물을 때 — target_id 는 다음 호출용이지 사람에게 보일 값이 아니다.
#: (UUID 노출이 id 를 그대로 되물은 답에서 나왔다.) 읽기·쓰기 모두에 붙는다.
CANDIDATES_NO_IDS = (
    "Tell the candidates apart by 'where', type or 'use_name' - never show "
    "ids to the user.")
#: 거부된 변경을 사람에게 풀어 말할 때 — 앞선 조회가 준 id 를 옮기지 않게.
NO_IDS_READING = (
    "When you describe what should be done instead, use names, places and "
    "times - never ids or tool-call syntax.")

#: 물리 도구가 명령을 **보냈는데** 결과를 확인하지 못한 경우(시간 초과·통신
#: 오류·데몬 오류). 시간 초과는 호출자가 기다리기를 그만뒀다는 뜻일 뿐이다 —
#: 데몬·원격 출력·LoRa 하향 링크는 이미 움직였을 수 있다. "NOT made" 라고
#: 말하면 모델이 다시 부르고, 밸브가 두 번 열린다.
UNCONFIRMED_READING = (
    "The device command may or may not have taken effect. Check the current "
    "state with get_output_state before retrying; do not say it was done or "
    "not done until confirmed.")
UNCONFIRMED_SCHEDULE_READING = (
    "The schedule may or may not have been saved. Check with search_schedule "
    "before retrying; do not say it was done or not done until confirmed.")
#: `performed` 의 세 번째 값 — 됐는지 모른다.
PERFORMED_UNKNOWN = 'unknown'
#: 설정은 저장됐는데 실행 중인 데몬이 받았는지 모르는 경우(함수·입력 켜기/끄기의
#: `daemon_warning`). 저장은 사실이므로 call_state 는 executed 그대로 두고,
#: 실제로 돌고 있는지(멈췄는지)만 "모름" 이다. get_active_functions_summary 는
#: 저장된 값만 읽으므로 그것으로 "확인됐다" 고 말하면 안 된다.
RUNTIME_UNCONFIRMED_READING = (
    "The setting was saved, but the running controller did not confirm it. "
    "Say it is saved but not yet confirmed live; do not say it is now on or off.")

_NOT_PERFORMED_STATES = frozenset({
    'pending_approval', 'approval_rejected', 'approval_expired', 'refused',
    'failed'})

#: 쓰기 도구가 "하지 않았다" 를 `status` 로 말하는 어휘 → call_state.
#:
#: 실패의 관행은 {"status": "error"}·{"error": ...} 둘이 주류지만, 처리기
#: 몇이 자기 단어를 쓴다 — 노트 보관(not_found·orphan_archive), 승인 응답
#: (refused), 지식 적재(rejected·quota_exceeded), 이름 해석(needs_disambiguation).
#: 이 단어들은 오류 키 없이 오므로 예전에는 executed 로 판정돼 "완료" 로 읽혔고
#: 장부(1-F)에도 실행으로 남았다. 어휘를 여기 한 곳에 둔다 — 새 단어를 쓰는
#: 처리기는 여기에 더한다. 읽기 도구에는 적용하지 않는다(읽기의 not_found 는
#: "없다" 는 정상 답이다).
#:
#: 지식 적재의 rejected(입력 검증: 내용·태그 없음)·quota_exceeded(하루 한도)는
#: 권한·정책 거부가 아니라 요청이 성립하지 않은 것이라 failed 로 센다 — 호출
#: 품질의 거부율은 권한·정책·사람의 거부만 뜻해야 한다.
NOT_PERFORMED_STATUSES = {
    'refused': 'refused',
    'rejected': 'failed',
    'quota_exceeded': 'failed',
    'not_found': 'failed',
    'target_not_found': 'failed',
    'orphan_archive': 'failed',
    'needs_disambiguation': 'failed',
    'ambiguous': 'failed',
    'unavailable': 'failed',
}


def _status_not_performed(result):
    return isinstance(result, dict) and \
        result.get('status') in NOT_PERFORMED_STATUSES


def _replay_failed(result):
    """승인 시점 실행의 결과 재생인데 그 실행이 실패한 경우."""
    inner = result.get('result') if isinstance(result, dict) else None
    return isinstance(inner, dict) and (
        inner.get('status') == 'error' or bool(inner.get('error'))
        or _status_not_performed(inner))


def _dispatch_flag(result):
    """물리 도구 결과의 `dispatched` 표시 — 감싼 `result` 안까지 본다.

    True = 명령을 보냈다(또는 보내다 끊겼다), False = 보내기 전에 확정 거부.
    표시가 없으면 None(모름). 요청자 권한·승인 토큰으로 막힌 응답
    (`blocked`·`performed: false`)은 보내기 전이다.
    """
    for _ in range(4):
        if not isinstance(result, dict):
            return None
        if 'dispatched' in result:
            return result['dispatched']
        if result.get('performed') is False or result.get('blocked') is True:
            return False
        result = result.get('result')
    return None


def _outcome_unconfirmed(tool_name, state, result):
    """물리 도구가 실패했는데 그것이 **보내기 전의 확정 거부**가 아닌가.

    게이트·스코프·역할·쓰기 비활성 거부는 call_state 가 refused 계열이라 여기
    오지 않는다. failed 중에서도 대상이 없거나 되묻는 응답, 처리기가 보내기
    전에 멈췄다고 표시한 것(`dispatched: false`)은 확정이다. 나머지 — 시간
    초과·통신 오류·데몬 오류·처리기 예외 — 는 됐는지 모른다.
    """
    if tool_name not in PHYSICAL_TOOLS:
        return False
    if state == 'failed':
        body = result
    elif state == 'already_executed' and _replay_failed(result):
        body = result.get('result')
    else:
        return False
    if _is_disambiguation(body) or _status_not_performed(body):
        return False
    return _dispatch_flag(body) is not False


def mark_unconfirmed(result, tool_name=None):
    """물리 명령의 결과를 모를 때 — `performed: "unknown"` 과 확인 규칙."""
    if not isinstance(result, dict):
        return result
    rule = (UNCONFIRMED_SCHEDULE_READING if tool_name == 'schedule_device_control'
            else UNCONFIRMED_READING)
    rules = [rule, NO_IDS_READING]
    result['performed'] = PERFORMED_UNKNOWN
    prev = result.get('_reading')
    if isinstance(prev, str):
        prev = [prev]
    result['_reading'] = rules + [r for r in (prev or []) if r not in rules]
    return result


def mark_runtime_unconfirmed(result):
    """설정은 저장됐지만 데몬이 받았는지 모를 때 — `performed: "unknown"`.

    저장된 사실(`is_activated` 등)은 그대로 둔다. 쓰기 자체는 일어났으므로
    call_state 는 executed 로 남는다(호출 품질 장부도 실행으로 센다) — 모르는
    것은 실행 중인 제어기가 그 설정을 따르는가이다.
    """
    if not isinstance(result, dict):
        return result
    result['performed'] = PERFORMED_UNKNOWN
    prev = result.get('_reading')
    if isinstance(prev, str):
        prev = [prev]
    result['_reading'] = [RUNTIME_UNCONFIRMED_READING] + [
        r for r in (prev or []) if r != RUNTIME_UNCONFIRMED_READING]
    return result


def unconfirmed_after_dispatch(tool_name, result):
    """보낸 뒤 결과를 모르는 물리 명령인가 — 승인 실행 기록·화면이 쓴다."""
    return _outcome_unconfirmed(tool_name, 'failed', result)


def mark_not_performed(result, state=None):
    """쓰기가 일어나지 않은 응답에 `performed: false` 와 해석 규칙을 붙인다.

    기존 칸은 그대로 두고 더하기만 한다. `_reading` 이 이미 있으면(문자열이든
    목록이든) 규칙을 **앞에** 붙인다 — 가장 먼저 읽혀야 하는 내용이다.
    같은 응답에 두 번 불려도 한 번만 붙는다. 이미 "모름" 으로 표시된 응답은
    "안 됨" 으로 낮추지 않는다.
    """
    if not isinstance(result, dict) or \
            result.get('performed') in (False, PERFORMED_UNKNOWN):
        return result
    if state == 'pending_approval' or result.get('status') == 'pending_approval':
        rules = [PENDING_READING]
    elif _is_disambiguation(result):
        rules = [DISAMBIGUATION_READING, CANDIDATES_NO_IDS]
    elif state == 'failed':
        rules = [FAILED_READING, NO_IDS_READING]
    else:
        rules = [NOT_PERFORMED_READING, NO_IDS_READING]
    result['performed'] = False
    prev = result.get('_reading')
    if isinstance(prev, str):
        prev = [prev]
    result['_reading'] = rules + [r for r in (prev or []) if r not in rules]
    return result


def _is_disambiguation(result):
    return (result.get('status') == 'needs_disambiguation'
            or result.get('needs_disambiguation') is True)


def _add_reading(result, rule):
    prev = result.get('_reading')
    if isinstance(prev, str):
        prev = [prev]
    prev = list(prev or [])
    if rule not in prev:
        prev.append(rule)
    result['_reading'] = prev


def annotate_write_outcome(tool_name, state, result):
    """실행층이 모든 응답에 한 번 부른다 — 쓰기 도구가 실제로 돌지 않았으면 표시.

    읽기 도구는 건드리지 않는다. 승인 시점 실행을 재생하는
    `already_executed` 는 그 실행이 실패했을 때만 표시한다. 물리 도구
    (PHYSICAL_TOOLS)가 보낸 뒤 실패했으면 `performed: "unknown"` 이다.
    """
    if not isinstance(result, dict):
        return result
    if classify_permission(tool_name) == 'write':
        if _outcome_unconfirmed(tool_name, state, result):
            # 물리 명령이 나갔을 수 있다 — "안 됨" 이라고 하면 재시도로 두 번 움직인다.
            mark_unconfirmed(result, tool_name)
        elif (state in _NOT_PERFORMED_STATES or _status_not_performed(result)
                or (state == 'already_executed' and _replay_failed(result))):
            mark_not_performed(result, state)
    # 되묻는 응답은 도구와 무관하게(읽기 포함) 후보를 id 로 말하지 않게 한다.
    if _is_disambiguation(result):
        _add_reading(result, CANDIDATES_NO_IDS)
    return result


def call_state(blocked, result=None, error_text='', tool_name=None):
    """(blocked, result) → CALL_STATES 중 하나.

    blocked 는 gate() 의 반환값(None 이면 게이트를 통과해 실제로 실행된 것).
    tool_name 이 쓰기 도구면 NOT_PERFORMED_STATUSES 의 status 도 실행이 아니다.
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
        if tool_name and _status_not_performed(result) and \
                classify_permission(tool_name) == 'write':
            return NOT_PERFORMED_STATUSES[result['status']]
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

    저장해둔 인자로만 실행하므로 승인 화면에 표시된 것과 실제 실행되는 것이
    어긋날 수 없다. 인자 대조 단계가 아예 필요 없어진다. modified_params_json 이
    있으면(위젯에서 수정 후 승인한 경우) 그게 "화면에 보인 최종값"이므로 그걸
    쓰고, 없으면 원본 params_json 을 쓴다 — 어느 쪽이든 "저장된 것 = 실행되는
    것" 이라는 불변식은 그대로 유지된다.

    Returns: (status, result_dict) — status 는 'executed'·'failed'·'refused'.

    'refused' 는 **승인자의 그룹 밖 대상**이라 쓰기 시점 강제가 막은 경우다.
    그때 행은 `pending` 으로 되돌린다(승인자·수정 인자는 지운다) — 요청 자체가
    틀린 것이 아니라 이 승인자에게 권한이 없는 것이므로, 권한 있는 다른 사람이
    대기 목록에서 그대로 결정할 수 있어야 한다. `failed` 로 적으면 목록에서
    사라지고(목록은 pending 만 보인다), AI 가 확인 번호로 다시 부르면 "이미
    실행됨" 이라는 거짓 재생을 받는다. 되돌려도 유효시간은 처음 마감 그대로다
    (`_return_to_pending`).

    'refused'(reason_code `not_approved`)는 행이 `approved` 가 아니거나 승인자가
    기록되지 않은(또는 지워진) 경우다 — 실행 신원이 없으므로 돌리지 않는다.
    """
    import json as _json
    from aot.databases.models import MCPConfirmation

    row = MCPConfirmation.query.filter_by(unique_id=confirmation_id).first()
    if row is None:
        return 'failed', {"status": "error", "message": "confirmation not found"}

    # 승인된 행만, 그리고 **승인한 사람이 기록된** 행만 실행한다. 실행 신원은
    # 승인자다(`acting_as(row.user_id)`) — 승인자가 비어 있거나 지금 없는
    # 계정이면 묶을 사람이 없어 쓰기 시점 판정이 "사람이 없는 호출" 로
    # 면제된다. 대기(pending) 행을 곧바로 넘겨도 실행되던 구멍이다.
    if row.status != 'approved' or not row.user_id:
        logger.warning('[MCPGate] 승인되지 않았거나 승인자가 없는 요청은 실행하지 '
                       '않는다 tool=%s status=%s', row.tool_name, row.status)
        return 'refused', mark_not_performed(
            {"status": "error", "reason_code": "not_approved",
             "message": "This request has not been approved by a "
                        "person, so it was not run."})
    try:
        from aot.databases.models import User as _User
        _approver_exists = _User.query.filter(
            _User.unique_id == row.user_id).first() is not None
    except Exception:
        logger.exception('[MCPGate] 승인자 확인 실패 — 실행하지 않는다')
        _approver_exists = False
    if not _approver_exists:
        return 'refused', mark_not_performed(
            {"status": "error", "reason_code": "not_approved",
             "message": "The approving account no longer exists, "
                        "so the request was not run."})

    try:
        params = _json.loads(row.modified_params_json or row.params_json or '{}')
    except Exception:
        params = {}

    try:
        # 실행 자체는 **실행층**의 디스패치를 그대로 쓴다. 여기서 같은 로직을 다시
        # 구현하면(핸들러 시그니처에 맞춘 메타키 제거 등) 두 벌이 서로 어긋난다.
        #
        # 정본은 `tool_execution` 이다 — MCP 서버가 아니다. 2026-08-22 실행층을
        # MCP 서버에서 분리(`896d4595`)하면서 이 두 이름이 옮겨갔는데 여기 import
        # 는 옛 위치를 그대로 가리키고 있었다. 그 결과 **승인된 쓰기 도구가 하나도
        # 실행되지 않았다** — 승인은 정상으로 보이고 그다음 즉시실행이 ImportError
        # 로 죽어, 사용자에게는 "승인했는데 아무 일도 안 일어남" 으로 나타났다.
        from aot.tools.tool_execution import (
            _dispatch_virtual_tool, _NATIVE_TOOLS)

        call_args = inject_agent(row.tool_name, strip_meta(params), row.agent_id)
        # 쓰기 시점 그룹 스코프 — 승인자로 판정한다(설계 §6-2a). 승인 단계의
        # `_approval_scope_denial` 은 인자를 훑어 짐작할 뿐이고, 처리기가
        # 이름·일정 id 등으로 실제 대상을 풀 때 여기서 다시 묻는다.
        from aot.aot_flask.access import write_scope
        with write_scope.acting_as(row.user_id, tool=row.tool_name) as _principal:
            try:
                if row.tool_name in _NATIVE_TOOLS:
                    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine
                    result = AoTNativeToolEngine.execute(row.tool_name, call_args)
                else:
                    result = _dispatch_virtual_tool(row.tool_name, call_args)
            except write_scope.WriteScopeDenied as exc:
                result = write_scope.refusal(exc)
            if write_scope.was_denied(_principal):
                try:
                    from aot.aot_flask.extensions import db
                    db.session.rollback()
                except Exception:
                    logger.exception('[MCPGate] 세션 되돌리기 실패')
                result = dict(write_scope.refusal(), status="error",
                              reason_code="group_scope_denied")
        status = 'executed'
    except Exception as exc:
        logger.exception('[MCPGate] 승인 즉시 실행 실패 tool=%s confirmation=%s',
                         row.tool_name, confirmation_id)
        result = {"status": "error", "message": str(exc)}
        status = 'failed'

    if not isinstance(result, dict):
        result = {"result": result}

    if (status == 'executed'
            and result.get('reason_code') in ('group_scope_denied', 'group_scope')
            and result.get('status') in ('error', 'refused')):
        return _return_to_pending(row, confirmation_id, result)

    # 도구는 내부 실패를 예외가 아니라 {"status": "error"} 나 {"error": ...} 로
    # 돌려주기도 한다. 예외만 보고 'executed' 를 적으면 감사 기록이 거짓말을 한다 —
    # 2026-08-09 koat 밸브 건이 정확히 이 모양이었다(status='executed' 인데
    # result_json 안에는 SQL 에러, 밸브는 열리지 않음). 재호출 경로는 'executed' 와
    # 'failed' 를 이미 같이 처리하므로(2단계 replay 분기) 값이 늘어도 안전하다.
    if status == 'executed' and (result.get('status') == 'error' or result.get('error')):
        status = 'failed'
        logger.warning('[MCPGate] 도구가 오류를 반환해 failed 로 기록 tool=%s confirmation=%s',
                       row.tool_name, confirmation_id)
    # 물리 명령을 보낸 뒤 실패(시간 초과·통신 오류)면 됐는지 모른다. 행 상태는
    # 'failed' 그대로 두고(상태 어휘를 늘리면 소비처가 깨진다) 결과에
    # performed:"unknown" 을 싣는다 — 승인 화면은 이 표시로 "적용 여부 미확인"
    # 을 보여준다.
    if status == 'failed' and unconfirmed_after_dispatch(row.tool_name, result):
        mark_unconfirmed(result, row.tool_name)

    row.status = status
    try:
        row.result_json = _json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        row.result_json = _json.dumps({"status": status})
    row.save()

    logger.info('[MCPGate] 승인 즉시 실행 tool=%s confirmation=%s -> %s',
                row.tool_name, confirmation_id, status)
    return status, result


def _return_to_pending(row, confirmation_id, result):
    """승인자의 그룹 밖이라 실행하지 않은 요청을 대기로 되돌린다.

    - 거부당한 승인자가 누구였는지 감사 기록(`audit_log`)에 남긴다 — 행의
      `user_id` 는 다음 승인자를 위해 비우므로 여기 말고는 남는 곳이 없다.
    - 유효시간은 **처음 만든 때의 마감**(`created_at + _CONFIRM_TTL_SEC`)을
      그대로 쓴다. 되돌릴 때마다 새로 세면 승인→거부→대기를 되풀이해
      요청을 끝없이 살려 둘 수 있다. 마감이 이미 지났으면 대기로 돌리지 않고
      만료로 닫는다.

    물리 동작은 되돌릴 수 없다 — 이 되돌림은 **처리기가 쓰기 전에** 거부한
    경우에만 온다(쓰기 시점 판정이 디스패치보다 앞선다). 여러 대상을 한 번에
    움직이는 도구는 모든 대상을 먼저 판정하고 나서 움직여야 하며, 중간에
    막히면 이미 움직인 것은 그대로 남는다(설계 §6-2a).
    """
    result = dict(result, status="error", reason_code="group_scope_denied")
    denied_approver = row.user_id
    deadline = (row.created_at or datetime.utcnow()) + timedelta(
        seconds=_CONFIRM_TTL_SEC)
    expired = datetime.utcnow() >= deadline
    row.status = 'expired' if expired else 'pending'
    row.user_id = None
    row.modified_params_json = None
    row.expires_at = deadline
    row.save()
    result['returned_to_queue'] = not expired
    mark_not_performed(result, None if expired else 'pending_approval')
    try:
        from aot.databases.models import User
        from aot.utils.audit import audit_log
        who = (User.query.filter(User.unique_id == denied_approver).first()
               if denied_approver else None)
        audit_log('mcp.approval_returned', target_type='MCPConfirmation',
                  target_id=confirmation_id, target_name=row.tool_name,
                  result='failure',
                  detail=('approver outside group scope; request %s'
                          % ('expired' if expired else 'returned to queue')),
                  user_id=getattr(who, 'id', None),
                  username=getattr(who, 'name', None))
    except Exception:
        logger.exception('[MCPGate] 거부된 승인자 감사 기록 실패')
    try:
        from aot.databases.models import MCPAuditLog
        log = (MCPAuditLog.query
               .filter_by(confirmation_id=confirmation_id)
               .order_by(MCPAuditLog.timestamp.desc()).first())
        if log:
            log.confirmation_status = row.status
            log.save()
    except Exception:
        logger.exception('[MCPGate] 감사 로그 상태 되돌리기 실패')
    logger.warning('[MCPGate] 승인자 그룹 밖 — 실행하지 않고 대기로 되돌림 '
                   'tool=%s', row.tool_name)
    return 'refused', result


def approve(confirmation_id, user_id=None, modified_params=None, role=None):
    return _decide(confirmation_id, 'approved', user_id,
                   modified_params=modified_params, role=role)


def reject(confirmation_id, user_id=None, role=None):
    return _decide(confirmation_id, 'rejected', user_id, role=role)
