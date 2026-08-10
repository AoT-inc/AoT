# coding=utf-8
"""
AI 런타임 상태 판정 — "지금 AI 가 스스로 돌아도 되는가" 의 유일한 정본.

세 축이 따로 논다. 하나로 뭉뜽그리면 안 되는 이유가 축마다 다르다.

1. ai_enabled   (Settings > General)
   기능 자체의 노출. 꺼지면 메뉴도 페이지도 사라진다.

2. ai_running   (AI 페이지)
   사람이 부르지 않아도 도는 백그라운드 작동. 켜는 자리를 AI 페이지에 둔 건,
   모델을 등록하는 화면에서 "이제 돌려라" 를 누르는 것이 자연스럽고 등록된
   모델이 없으면 켜지 못하게 막을 수 있는 자리이기 때문이다.

3. 활성 AIAgent 유무
   LLM 을 부르는 잡은 에이전트가 하나도 없으면 할 수 있는 일이 없다. 예전에는
   이걸 아무도 안 보고 잡을 돌려서, 매 주기마다
   `No suitable AI agent found for summary generation.` 만 로그에 쌓였다.
   그건 에러가 아니라 "아직 모델을 안 붙였다" 는 설정 상태다.

그래서 게이트가 둘이다:

- `ai_autonomy_enabled()`  = 1 AND 2
  모델이 없어도 할 일이 있는 백그라운드 작동(규칙 기반 실시간 알림 등).
- `ai_background_active()` = 1 AND 2 AND 3
  LLM 을 부르는 백그라운드 작동(주기 요약, 컨텍스트 브로드캐스트, 날씨 요약,
  MCP 헬스체크).

사용자가 직접 보내는 채팅/조언 요청은 **어느 쪽도 거치지 않는다** — 1 만 보고
동작한다. 모델을 막 등록한 사람이 스위치를 켜기 전에 시험해 볼 수 있어야 한다.

모든 함수는 Flask app context 안에서 불러야 하고, 판정에 실패하면 안전한 쪽
(작동 안 함)으로 떨어진다.
"""
import logging

logger = logging.getLogger(__name__)


def get_settings():
    """AIGlobalSettings 싱글톤을 돌려준다. 없으면 None."""
    try:
        from aot.databases.models import AIGlobalSettings
        return AIGlobalSettings.query.first()
    except Exception:
        logger.debug("[AIRuntime] AIGlobalSettings 조회 실패", exc_info=True)
        return None


def active_agent_count() -> int:
    """활성화된 AIAgent 수. 조회 실패는 0 으로 본다(안전한 쪽)."""
    try:
        from aot.databases.models import AIAgent
        return AIAgent.query.filter_by(is_activated=True).count()
    except Exception:
        logger.debug("[AIRuntime] AIAgent 조회 실패", exc_info=True)
        return 0


def ai_autonomy_enabled(settings=None) -> bool:
    """
    자율 작동 스위치가 켜져 있는가 (ai_enabled AND ai_running).

    모델이 없어도 의미가 있는 백그라운드 작동 — 규칙 기반 실시간 알림처럼
    LLM 을 부르지 않는 잡 — 이 쓰는 게이트다.
    """
    if settings is None:
        settings = get_settings()
    if settings is None or not settings.ai_enabled:
        return False
    return bool(getattr(settings, 'ai_running', False))


def ai_background_active(settings=None) -> bool:
    """
    LLM 을 부르는 백그라운드 작동이 돌아도 되는가
    (ai_enabled AND ai_running AND 활성 에이전트 ≥ 1).

    에이전트가 0 이면 False — 이 상태로 잡을 돌리면 매 주기 에러 로그만 남는다.
    """
    if not ai_autonomy_enabled(settings):
        return False
    return active_agent_count() > 0


def background_skip_reason(settings=None) -> str:
    """
    `ai_background_active()` 가 False 인 이유를 로그용 짧은 문자열로 돌려준다.
    돌아도 되는 상태면 빈 문자열.
    """
    if settings is None:
        settings = get_settings()
    if settings is None:
        return "AI 설정 레코드 없음"
    if not settings.ai_enabled:
        return "AI 서비스 비활성"
    if not getattr(settings, 'ai_running', False):
        return "AI 작동 시작 안 됨"
    if active_agent_count() <= 0:
        return "활성 AI 모델 없음"
    return ""


def stop_if_no_models() -> bool:
    """
    마지막 활성 모델이 사라졌으면 "작동 시작" 도 함께 끈다. 껐으면 True.

    끄지 않으면 스위치는 켜진 채로 남고 실제로는 아무것도 안 돈다 — 화면이
    거짓말을 하는 상태다. 게다가 나중에 모델을 하나 되살리는 순간 사람이 아무
    결정도 하지 않았는데 자율 작동이 조용히 재개된다. 다시 켜는 것은 사람이
    명시적으로 할 일이다.

    호출은 에이전트 비활성화/삭제를 커밋한 **뒤**에 둘 것 — 앞에 두면 방금
    내린 에이전트가 아직 활성으로 세어져 판정이 한 박자 늦는다.
    """
    if active_agent_count() > 0:
        return False
    settings = get_settings()
    if settings is None or not getattr(settings, 'ai_running', False):
        return False
    try:
        from aot.aot_flask.extensions import db
        settings.ai_running = False
        db.session.commit()
        logger.info("[AIRuntime] 활성 AI 모델이 없어 AI 자율 작동을 중지했습니다.")
        return True
    except Exception:
        logger.exception("[AIRuntime] ai_running 자동 중지 실패")
        return False


def runtime_status(settings=None) -> dict:
    """
    화면/API 가 그대로 쓰는 상태 묶음.

    can_start 는 "지금 작동 시작 버튼을 눌러도 되는가" 다 — 모델이 하나도 없으면
    켜 봐야 할 일이 없으므로 False.
    """
    if settings is None:
        settings = get_settings()
    enabled = bool(settings is not None and settings.ai_enabled)
    running = bool(settings is not None and getattr(settings, 'ai_running', False))
    agents = active_agent_count()
    return {
        'ai_enabled': enabled,
        'ai_running': running,
        'agent_count': agents,
        'can_start': enabled and agents > 0,
        'background_active': enabled and running and agents > 0,
        'skip_reason': background_skip_reason(settings),
    }
