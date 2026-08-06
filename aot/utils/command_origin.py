# coding=utf-8
"""Output 명령의 출처(origin) 판정.

`DaemonControl.output_on/output_off` 가 **RPC 를 타기 직전에** 이 모듈로 출처를
확정해서 인자로 실어 보낸다. 왜 하필 그 시점이냐가 이 모듈의 존재 이유다.

## thread-local 을 RPC 너머로 읽으면 안 되는 이유

`aot/utils/execution_context.py` 는 thread-local 에 `source_type`/`source_id` 를
심고, `outputs/base_output.py` 가 `get_extra_tags()` 로 읽어 InfluxDB 태그에 붙이게
설계돼 있었다. 그런데 그 태그는 **한 번도 기록된 적이 없다** (aot-005 실측: 30일치
`schema.tagKeys()` 에 `source_type` 자체가 없음).

원인은 스레드가 바뀌기 때문이다. 컨트롤러는 자기 스레드에서 컨텍스트를 심지만,
명령은 `DaemonControl()` → Pyro5 RPC 로 프로세스를 나갔다가 데몬의 **Pyro5 워커
스레드**로 되돌아온다. `get_extra_tags()` 는 그 워커 스레드에서 돌아 항상 빈 dict 를
본다. 같은 프로세스 안에서 자기 자신을 호출해도 마찬가지다.

그래서 이 모듈은 **호출자 스레드에서(=RPC 이전에)** 출처를 확정한다. 확정된 값은
평범한 인자로 전달되므로 스레드 경계와 무관하다. 워커 스레드 풀이 재사용되며 남은
찌꺼기 컨텍스트가 엉뚱한 사람에게 명령을 뒤집어씌우는 사고(오귀속)도 원천 차단된다 —
**틀린 행위자 기록은 없는 것보다 나쁘다.**

## 판정 순서

1. 명시적 실행 컨텍스트(trigger/conditional/scheduler) — 있으면 그대로 신뢰
2. Flask 요청 문맥 — 로그인 사용자면 `user`, 아니면 `unknown`(미인증 명령)
3. 데몬 프로세스 — `automation` (PID·bang_bang·env_coordinator·기동/종료 등)
4. 그 외 — `unknown`

`unknown` 은 버그가 아니라 **탐지 신호**다. 어떤 경로가 출처를 못 밝히면 감사로그에
`unknown` 으로 남아 눈에 띈다. 조용히 묻히는 것보다 시끄러운 편이 낫다.
"""
import logging

from aot.utils.execution_context import get_context

logger = logging.getLogger(__name__)

# 감사로그(관계형)에 남길 출처. 나머지(자동화)는 InfluxDB 태그로만 남는다 —
# PID/PWM/env_coordinator 는 주기마다 명령해서 관계형 테이블을 잠기게 만든다.
# "누가"는 저빈도라 audit_log 에, "무엇이 언제"는 고빈도라 시계열에.
#
# `lifecycle` 이 여기 들어있는 이유: 데몬 기동/종료와 Output 삭제는 드라이버의
# initialize()/stop_output() 이 하드웨어를 **직접** 건드려서 제어 게이트를 지나지
# 않는다(예: on_off_gpio 는 initialize() 안에서 GPIO.output() 을 그냥 호출한다).
# 빈도는 낮은데 물리 상태를 바꾸므로, 안 남기면 "아무도 안 켰는데 켜져 있다" 가
# 그대로 재현된다.
AUDITED_TYPES = frozenset({'user', 'api', 'ai', 'unknown', 'lifecycle'})

TYPE_UNKNOWN = 'unknown'
TYPE_AUTOMATION = 'automation'
TYPE_USER = 'user'
TYPE_LIFECYCLE = 'lifecycle'
TYPE_AI = 'ai'

ROLE_DAEMON = 'daemon'
ROLE_WEB = 'web'
ROLE_MCP = 'mcp'

_process_role = None


def set_process_role(role):
    """프로세스 정체를 등록한다. `aot_daemon.py` 가 기동 시 'daemon' 으로 부른다.

    이게 없으면 데몬 내부의 자동화 명령(PID 등, 실행 컨텍스트를 안 심는 경로)이
    `unknown` 으로 분류돼 감사로그를 채우고 가짜 우회 경보를 낸다.
    """
    global _process_role
    _process_role = role


def get_process_role():
    return _process_role


def _from_request_context():
    """Flask 요청 문맥에서 행위자 추출. 문맥이 없으면 None."""
    try:
        from flask import has_request_context, request
        import flask_login

        if not has_request_context():
            return None

        ip = (request.environ.get('HTTP_X_FORWARDED_FOR')
              or request.remote_addr
              or None)
        # X-Forwarded-For 는 프록시 체인이라 여러 개일 수 있다 — 첫 값만.
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        user = getattr(flask_login, 'current_user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            return {
                'type': TYPE_USER,
                'id': getattr(user, 'id', None),
                'name': getattr(user, 'name', None),
                'ip': ip,
            }
        # 요청 문맥은 있는데 인증이 없다 — 정상 경로라면 나올 수 없는 조합이라
        # unknown 으로 남겨 눈에 띄게 한다.
        return {'type': TYPE_UNKNOWN, 'id': None, 'name': None, 'ip': ip}
    except Exception:
        # flask 미설치(데몬 단독 실행 등)나 문맥 오류로 제어가 막히면 안 된다.
        return None


def resolve_origin():
    """호출자 스레드에서 출처를 확정해 dict 로 반환한다. 절대 예외를 올리지 않는다."""
    try:
        ctx = get_context()
        if ctx.get('source_type'):
            return {
                'type': ctx['source_type'],
                'id': ctx.get('source_id'),
                'name': None,
            }

        from_request = _from_request_context()
        if from_request is not None:
            return from_request

        if _process_role == ROLE_DAEMON:
            return {'type': TYPE_AUTOMATION, 'id': None, 'name': None}

        if _process_role == ROLE_MCP:
            # MCP 서버는 외부 AI 전용 프로세스다. 자체 Flask 앱이지만
            # flask_login 이 없어 사용자를 못 뽑으므로, 여기서 표시하지 않으면
            # AI 명령이 전부 unknown 으로 남아 진짜 우회와 섞인다.
            return {'type': TYPE_AI, 'id': None, 'name': 'mcp'}

        return {'type': TYPE_UNKNOWN, 'id': None, 'name': None}
    except Exception:
        logger.exception("출처 판정 실패 — unknown 으로 기록합니다")
        return {'type': TYPE_UNKNOWN, 'id': None, 'name': None}


def should_audit(origin):
    """이 출처를 관계형 감사로그에 남길 것인가."""
    try:
        return (origin or {}).get('type', TYPE_UNKNOWN) in AUDITED_TYPES
    except Exception:
        return True  # 판단이 안 서면 남기는 쪽 (누락보다 과잉이 낫다)
