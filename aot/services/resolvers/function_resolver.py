# coding=utf-8
"""이름으로 Function류(Conditional/Trigger/PID/CustomController, 필요하면
Input)를 찾을 때 **겹치면 고르지 않는다**.

`device_resolver.py` 가 Output/Input 에서 고친 것과 같은 문제, 같은 계열의
실제 사고다: 로컬 서버에 이름이 똑같은 "Env Coordinator" 커스텀 컨트롤러가
활성 하나·비활성 하나로 실제로 있었다(2026-09-25 확인). 여러 호출부가

    Conditional.query.filter(
        (Conditional.unique_id == x) | (Conditional.name == x)).first()

식으로 네 테이블(Conditional/Trigger/PID/CustomController)을 따로따로
`.first()` 로 짚었다 — 이름이 겹쳐도 행 순서로 아무거나 하나를 집는다.
"Env Coordinator 꺼" 라고 지시했을 때 이미 꺼져 있는 쪽을 다시 "끄고"
성공을 보고할 수 있고, 실제로 켜져 있는 쪽은 그대로 돈다.

여기서는 같은 원칙(unique_id 정확일치 → 이름 정확일치, 둘 이상이면 거절)을
**네·다섯 테이블에 함께** 적용한다 — `device_resolver.resolve_device` 는
테이블 하나짜리라 그대로 쓸 수 없다. 이름이 다른 종류(Trigger 와 Conditional
등)에 걸쳐 겹쳐도 잡아낸다.

@phase active
@stability stable
"""
import logging
from typing import List, NamedTuple, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 후보 표시 상한 — 넘으면 나머지는 candidates_total 로만 알린다.
_MAX_LISTED = 10


class FunctionMatch(NamedTuple):
    """조회 결과.

    - `row` 가 있으면 확정 — `kind` 는 DaemonControl/응답이 쓰는 레이블
      ('Conditional'|'Trigger'|'PID'|'Function'|'Input').
    - `error` 가 있으면 못 골랐다(이름이 여럿에 걸림). `candidates` 에
      [{'id','name','kind','is_activated','tab'}] 가 실린다 — 호출자는
      `error` 를 그대로 보여도 되고, `candidates` 로 되물어도 된다.
    - 둘 다 없으면 그런 id/이름이 없다.
    """
    row: object = None
    kind: Optional[str] = None
    error: Optional[str] = None
    candidates: Optional[List[dict]] = None
    #: 실제 후보 총수 — `candidates` 는 `_MAX_LISTED` 로 잘려 있을 수 있다.
    candidates_total: Optional[int] = None

    @property
    def ambiguous(self) -> bool:
        return self.error is not None


def _default_models() -> Tuple[Tuple[object, str], ...]:
    """Conditional/Trigger/PID/CustomController — DaemonControl 레이블과 함께.

    지연 임포트다: 이 모듈은 앱 컨텍스트 밖(스케줄 잡·캘린더 동기화)에서도
    불린다.
    """
    from aot.databases.models.function import Conditional, Trigger
    from aot.databases.models.controller import CustomController
    from aot.databases.models.pid import PID
    return (
        (Conditional, 'Conditional'), (Trigger, 'Trigger'), (PID, 'PID'),
        (CustomController, 'Function'),  # DaemonControl 은 CustomController 를 'Function' 이라 부른다.
    )


def _tab_name(row):
    """후보 하나의 소속 탭 이름 — 사람이 구분할 단서(uuid 대신)."""
    tab_id = getattr(row, 'tab_id', None)
    if not tab_id:
        return None
    try:
        from aot.databases.models import Tab
        tab = Tab.query.filter_by(unique_id=tab_id).first()
        return getattr(tab, 'name', None)
    except Exception:
        return None


def _settle(candidates: List[Tuple[object, str]], token: str) -> Optional[FunctionMatch]:
    """후보 0개면 None(다음 단계로), 1개면 확정, 2개 이상이면 거절.

    호출부(정확일치·부분일치)가 같은 판정을 반복하지 않게 공통화한다.
    """
    if not candidates:
        return None
    if len(candidates) > 1:
        logger.warning(
            "[resolve_function] 이름이 겹쳐 고르지 않았습니다: %r (%d건)",
            token, len(candidates))
        listed = candidates[:_MAX_LISTED]
        return FunctionMatch(error=(
            "'%s' matches %d entities — say which one (pass its unique_id)."
            % (token, len(candidates))
        ), candidates=[
            {"id": r.unique_id, "name": r.name, "kind": k,
             "is_activated": bool(getattr(r, 'is_activated', False)),
             "tab": _tab_name(r)}
            for (r, k) in listed
        ], candidates_total=len(candidates))
    row, label = candidates[0]
    return FunctionMatch(row=row, kind=label)


def resolve_function(token: Optional[str],
                     models: Optional[Sequence[Tuple[object, str]]] = None,
                     include_input: bool = False,
                     allow_partial: bool = False) -> FunctionMatch:
    """id 또는 이름 → 확정 행. 이름이 겹치면(다른 종류에 걸쳐서도) 고르지 않는다.

    순서는 좁은 것부터다: unique_id 정확일치(모든 테이블) → 이름 정확일치
    (모든 테이블을 함께 모은다 — Trigger 와 Conditional 이 같은 이름을 쓰는
    경우도 잡아낸다) → (허용 시) 부분 이름. 앞 단계에서 하나로 확정되면
    뒤는 보지 않는다.

    :param models: (모델, 레이블) 목록. 기본은 Conditional/Trigger/PID/
                   CustomController(`_default_models`).
    :param include_input: True 면 Input(센서)도 같이 본다 — 활성/비활성
                          전용 도구는 센서도 켜고 끌 수 있어, 이름이 같은
                          함수와 섞일 수 있다.
    :param allow_partial: True 면 정확일치가 없을 때 `%token%` 부분일치까지
                          본다(캘린더 동기화 등 사람이 줄여 쓰는 경로). 이
                          단계는 겹칠 확률이 훨씬 높으므로, 여기서도 둘
                          이상이면 마찬가지로 거절한다 — `device_resolver.
                          resolve_device` 와 같은 규율.
    """
    token = str(token or '').strip()
    if not token:
        return FunctionMatch(error="entity_id is required (unique_id or name)")

    _models = list(models) if models is not None else list(_default_models())
    if include_input:
        from aot.databases.models import Input
        _models.append((Input, 'Input'))

    # 0) unique_id 정확일치 — 도구 체이닝이 낸 id 를 이름 검색으로 새게
    # 하지 않는다.
    for model, label in _models:
        row = model.query.filter_by(unique_id=token).first()
        if row is not None:
            return FunctionMatch(row=row, kind=label)

    # 1) 이름 정확일치 — 모든 종류를 함께 모은다.
    exact: List[Tuple[object, str]] = []
    for model, label in _models:
        for row in model.query.filter(model.name == token).all():
            exact.append((row, label))
    got = _settle(exact, token)
    if got:
        return got

    if allow_partial:
        # 2) 부분 이름 — 정확일치가 하나도 없을 때만.
        partial: List[Tuple[object, str]] = []
        for model, label in _models:
            for row in model.query.filter(model.name.ilike(f'%{token}%')).all():
                partial.append((row, label))
        got = _settle(partial, token)
        if got:
            return got

    return FunctionMatch()
