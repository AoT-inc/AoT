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
    """
    row: object = None
    error: Optional[str] = None

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


def resolve_device(model, token: Optional[str], kind: Optional[str] = None,
                   allow_partial: bool = False) -> DeviceMatch:
    """id 또는 이름으로 장치 한 건. 이름이 겹치면 고르지 않는다.

    순서는 좁은 것부터다: 정확한 unique_id → 정확한 이름 → (허용 시)
    부분 이름. 앞 단계에서 하나로 확정되면 뒤는 보지 않는다 — id 로 정확히
    지목한 요청이 동명이인 때문에 막히면 안 된다.

    `allow_partial` 은 `%token%` 부분일치까지 본다. 이 단계는 겹칠 확률이
    훨씬 높으므로, 여기서도 둘 이상이면 마찬가지로 멈춘다.
    """
    if not token:
        return DeviceMatch()

    kind = kind or getattr(model, '__name__', 'device')

    exact_id = model.query.filter(model.unique_id == token).first()
    if exact_id is not None:
        return DeviceMatch(row=exact_id)

    by_name = model.query.filter(model.name == token).all()
    if len(by_name) == 1:
        return DeviceMatch(row=by_name[0])
    if len(by_name) > 1:
        logger.warning(
            "[resolve_device] 이름이 겹쳐 고르지 않았습니다: %s %r (%d건)",
            kind, token, len(by_name))
        return DeviceMatch(error=_ambiguous(kind, token, by_name))

    if allow_partial:
        partial = model.query.filter(model.name.ilike(f'%{token}%')).all()
        if len(partial) == 1:
            return DeviceMatch(row=partial[0])
        if len(partial) > 1:
            logger.warning(
                "[resolve_device] 부분 이름이 겹쳐 고르지 않았습니다: %s %r (%d건)",
                kind, token, len(partial))
            return DeviceMatch(error=_ambiguous(kind, token, partial))

    return DeviceMatch()


def resolve_output(token, allow_partial: bool = False) -> DeviceMatch:
    from aot.databases.models import Output
    return resolve_device(Output, token, kind='output',
                          allow_partial=allow_partial)


def resolve_input(token, allow_partial: bool = False) -> DeviceMatch:
    from aot.databases.models import Input
    return resolve_device(Input, token, kind='input',
                          allow_partial=allow_partial)
