# coding=utf-8
"""이름으로 장치를 찾을 때 **겹치면 고르지 않는다**.

여러 곳이 이렇게 쓰고 있었다:

    Output.query.filter(or_(Output.unique_id == x, Output.name == x)).first()

`.first()` 는 이름이 겹쳐도 조용히 하나를 집는다. 어느 쪽인지는 행 순서가
정한다. 2026-08-28 실측 상황: 탭 복제가 이름을 그대로 두는 바람에 `v11` 이
두 개(나주 탭·그 사본 탭) 있었고, 사용자는 시퀀스 동작을 확인하다가 꺼져
있는 쪽 `v11` 의 상태를 보고 "밸브가 안 열렸다" 고 판단했다. 밸브는 열려
있었다.

**틀린 장치를 조작하는 것보다 못 찾았다고 말하는 편이 낫다.** 이름이
겹치면 여기서 멈추고, 어느 것인지 되묻는 문장을 돌려준다.

돌려주는 문장에는 uuid 를 담지 않는다 — 사람이 구분할 수 있는 것은 소속
탭이지 36자 난수가 아니다. 호출자(AI 도구)가 정확한 id 가 필요하면 장치
목록 조회 도구를 쓰면 된다.

@phase active
@stability stable
"""
import logging
from typing import NamedTuple, Optional

from flask_babel import gettext

logger = logging.getLogger(__name__)


def _t(message, **kwargs):
    """번역하되, **컨텍스트가 없어도 죽지 않는다**.

    `flask_babel.gettext` 는 요청 컨텍스트를 요구한다. 그런데 이 모듈은
    데몬·백그라운드 잡·MCP 도구처럼 요청 밖에서도 불린다. 번역이 안 되는
    것은 불편이지만, 여기서 예외가 나면 삭제 판정 자체가 깨진다 — 그러면
    아무 검사도 없던 예전으로 돌아간다.
    """
    try:
        return gettext(message, **kwargs)
    except Exception:
        return (message % kwargs) if kwargs else message


class DeviceMatch(NamedTuple):
    """조회 결과.

    - `row` 가 있으면 확정.
    - `error` 가 있으면 **고르지 못했다**(이름이 겹친다). 호출자는 이것을
      그대로 사용자에게 보여도 된다.
    - 둘 다 없으면 그런 이름이 없다 — "못 찾음" 은 호출자가 자기 문구로
      말한다(도구마다 표현이 다르다).
    - `reason` 은 `error` 의 종류다. 지금은 'ai_excluded'(AI 도구에서 뺀
      장치를 지목했다) 하나만 적고, 이름 겹침은 None 이다.
    """
    row: object = None
    error: Optional[str] = None
    reason: Optional[str] = None

    @property
    def ambiguous(self) -> bool:
        return self.error is not None


def _tab_names(rows) -> str:
    """후보들의 소속 탭 이름. 사용자가 화면에서 구분할 수 있는 유일한 단서다."""
    from aot.databases.models import Tab

    names = []
    for row in rows:
        tab_id = getattr(row, 'tab_id', None)
        label = None
        if tab_id:
            tab = Tab.query.filter(Tab.unique_id == tab_id).first()
            label = getattr(tab, 'name', None)
        label = label or _t("no tab")
        if label not in names:
            names.append(label)
    return ', '.join(names)


def _ambiguous(kind: str, token: str, rows) -> str:
    return _t(
        "More than one %(kind)s is named '%(name)s' (tabs: %(tabs)s). "
        "Say which one you mean, or use its exact id.",
        kind=_t(kind), name=token, tabs=_tab_names(rows))


def _found(row) -> DeviceMatch:
    """찾은 장치를 돌려주기 전에 쓰기 시점 그룹 스코프를 묻는다.

    쓰기 도구 호출이 묶여 있을 때만 판정한다(`write_scope.enforce` — 묶인
    사람이 없으면 아무것도 하지 않는다). id·이름·부분 이름 어느 단계로
    찾았든 **찾은 행**으로 묻는다 — 이름으로 지목하면 앞 단계 짐작 검사를
    지나던 구멍이 여기서 닫힌다.
    """
    from aot.aot_flask.access import write_scope
    write_scope.enforce(row)
    return DeviceMatch(row=row)


# ── AI 도구에서 뺀 장치(입력·출력 모달의 'AI 판단에 포함' 끔) ───────────────
#
# 매뉴얼(docs/ai/overview.md#device-ai-toggle): 끈 장치는 AI 판단·제어 도구의
# 조회와 제어 대상에서 빠진다. 예전에는 인앱 컨텍스트 조립만 이것을 봤고, AI
# 도구(aot/tools — 외부 MCP 와 인앱 도구 호출이 함께 쓴다)는 전혀 보지 않아 끈
# 장치를 그대로 찾고 움직였다. AI 도구의 장치 해석·목록은 아래 헬퍼만 쓴다.
# 사람 경로(웹 화면·사람 API·캘린더 동기화)는 `ai=False`(기본)라 영향이 없다.

#: `DeviceMatch.reason`·도구 오류의 `reason_code` 값.
AI_EXCLUDED = 'ai_excluded'

#: 끈 장치를 대상으로 받았을 때 AI 에게 돌려주는 이유. 모델이 읽는 문장이라
#: 번역하지 않는다(UI 문구가 아니다).
AI_EXCLUDED_MESSAGE = (
    "'%s' is excluded from AI: its 'Include in AI judgment' setting is off, "
    "so AI tools may not read or control it. Nothing was done. A person can "
    "turn the setting back on in the device's settings, or operate the device "
    "from the web screen.")


def ai_excluded(row) -> bool:
    """이 행이 AI 도구에서 빠진 장치인가. 칸이 없는 행(함수·카메라)은 아니다.

    값이 명시적으로 거짓일 때만 뺀다 — 칸이 없거나 비어 있으면(NULL) 기본값
    (켜짐)으로 본다."""
    value = getattr(row, 'is_ai_enabled', None)
    return value is not None and not bool(value)


def ai_excluded_error(row) -> Optional[str]:
    """빠진 장치면 AI 에게 줄 이유 문장, 아니면 None."""
    if row is None or not ai_excluded(row):
        return None
    return AI_EXCLUDED_MESSAGE % (getattr(row, 'name', None)
                                  or getattr(row, 'unique_id', None) or '?')


def ai_excluded_ids() -> set:
    """AI 도구에서 빠진 입력·출력의 unique_id 집합(목록 도구가 거를 때)."""
    from aot.databases.models import Input, Output
    out = set()
    for model in (Input, Output):
        try:
            out.update(uid for (uid,) in model.query.with_entities(
                model.unique_id).filter(model.is_ai_enabled == False).all())  # noqa: E712
        except Exception as exc:                            # noqa: BLE001
            logger.warning("[ai_excluded_ids] %s 조회 실패: %s",
                           getattr(model, '__name__', model), exc)
    return out


def _pick(rows, ai):
    """AI 해석이면 빠진 장치를 후보에서 덜어 낸다. (남은 후보, 덜어 낸 후보)."""
    if not ai:
        return rows, []
    kept = [r for r in rows if not ai_excluded(r)]
    return kept, [r for r in rows if ai_excluded(r)]


def _match(model, token, kind, allow_partial, ai) -> DeviceMatch:
    """`resolve_device` 의 판정만 — 찾은 행에 스코프를 묻지 않는다."""
    exact_id = model.query.filter(model.unique_id == token).first()
    if exact_id is not None:
        if ai and ai_excluded(exact_id):
            return DeviceMatch(error=ai_excluded_error(exact_id),
                               reason=AI_EXCLUDED)
        return DeviceMatch(row=exact_id)

    by_name, hidden = _pick(model.query.filter(model.name == token).all(), ai)
    if len(by_name) == 1:
        return DeviceMatch(row=by_name[0])
    if len(by_name) > 1:
        logger.warning(
            "[resolve_device] 이름이 겹쳐 고르지 않았습니다: %s %r (%d건)",
            kind, token, len(by_name))
        return DeviceMatch(error=_ambiguous(kind, token, by_name))
    if hidden:
        return DeviceMatch(error=ai_excluded_error(hidden[0]),
                           reason=AI_EXCLUDED)

    if allow_partial:
        partial, hidden = _pick(
            model.query.filter(model.name.ilike(f'%{token}%')).all(), ai)
        if len(partial) == 1:
            return DeviceMatch(row=partial[0])
        if len(partial) > 1:
            logger.warning(
                "[resolve_device] 부분 이름이 겹쳐 고르지 않았습니다: %s %r (%d건)",
                kind, token, len(partial))
            return DeviceMatch(error=_ambiguous(kind, token, partial))
        if hidden:
            return DeviceMatch(error=ai_excluded_error(hidden[0]),
                               reason=AI_EXCLUDED)

    return DeviceMatch()


def resolve_device(model, token: Optional[str], kind: Optional[str] = None,
                   allow_partial: bool = False, ai: bool = False) -> DeviceMatch:
    """id 또는 이름으로 장치 한 건. 이름이 겹치면 고르지 않는다.

    순서는 좁은 것부터다: 정확한 unique_id → 정확한 이름 → (허용 시)
    부분 이름. 앞 단계에서 하나로 확정되면 뒤는 보지 않는다 — id 로 정확히
    지목한 요청이 동명이인 때문에 막히면 안 된다.

    `allow_partial` 은 `%token%` 부분일치까지 본다. 이 단계는 겹칠 확률이
    훨씬 높으므로, 여기서도 둘 이상이면 마찬가지로 멈춘다.

    `ai=True`(AI 도구 경로)면 'AI 판단에 포함' 을 끈 장치는 후보가 아니다 —
    id 로 지목했거나 그 이름에 걸리는 것이 그런 장치뿐이면 이유를 담은
    `error`(reason='ai_excluded')를 돌려준다(못 찾았다고 하지 않는다).
    """
    if not token:
        return DeviceMatch()
    kind = kind or getattr(model, '__name__', 'device')
    match = _match(model, token, kind, allow_partial, ai)
    return _found(match.row) if match.row is not None else match


def ai_control_refusal(token, allow_partial: bool = True) -> Optional[str]:
    """AI 제어 도구의 출력 인자가 AI 에서 뺀 장치를 가리키면 그 이유, 아니면 None.

    승인 큐에 넣기 전에 묻는 자리(`tool_execution._pre_gate_validation`)가
    쓴다 — 어차피 실행에서 거절될 요청이 사람의 승인을 기다리지 않게. 찾은
    행에 스코프를 묻지 않는다(판정만 한다). 부분 이름까지 보는 것은 승인
    게이트의 스코프 정규화와 같다(`mcp_safety_gate._normalize_device_id_for_scope`).
    """
    from aot.databases.models import Output
    if not isinstance(token, str) or not token.strip():
        return None
    match = _match(Output, token.strip(), 'output', allow_partial, True)
    return match.error if match.reason == AI_EXCLUDED else None


def resolve_output(token, allow_partial: bool = False,
                   ai: bool = False) -> DeviceMatch:
    from aot.databases.models import Output
    return resolve_device(Output, token, kind='output',
                          allow_partial=allow_partial, ai=ai)


def resolve_input(token, allow_partial: bool = False) -> DeviceMatch:
    from aot.databases.models import Input
    return resolve_device(Input, token, kind='input',
                          allow_partial=allow_partial)
