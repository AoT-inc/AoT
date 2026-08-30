# coding=utf-8
"""장치를 **아직 쓰고 있는 곳**을 찾는다.

장치 삭제는 참조자를 보지 않았다. 그래서 출력을 지우면 그 출력을 가리키던
시퀀스 스텝·위젯·PID 설정이 죽은 id 를 든 채 그대로 남았고, 아무 오류도
나지 않았다. 2026-08-28 로컬 DB 실측: **활성** 시퀀스 '3포장 밸브제어' 의
스텝 8개 전부가 존재하지 않는 출력을 가리키고 있었다 — 그 시퀀스는 매 주기
아무 데도 닿지 않는 명령을 내고 있었다. 위젯도 2개가 사라진 측정 정의
4개를 들고 있었다.

(같은 날 1차 조사에서 "위젯 28개" 라고 적었던 것은 **틀렸다.** 그때 쓴
임시 스캔이 아는 id 목록에 `geo_map`·`geo_shape`·`geo_plot`·`camera` 를
넣지 않아, 살아 있는 지도를 가리키는 위젯까지 전부 죽은 것으로 셌다.
실제로 끊어진 것은 2개다.)

이 모듈은 "지워도 되는가" 를 판정하는 자리다. 판정만 하고 아무것도 지우지
않는다 — 무엇을 포기할지는 사람이 정한다.

## 무엇을 찾는가

장치 id 는 **전용 컬럼과 자유 텍스트(JSON) 양쪽**에 흩어져 있다. 컬럼만
열거하면 새 옵션이 JSON 으로 추가될 때마다 검사에 구멍이 난다. 그래서
"id 를 담을 수 있는 자리" 를 모델·컬럼 단위로 선언해 두고, 그 안에서
**uuid 부분문자열**로 찾는다. uuid 는 36자 난수라 오탐이 사실상 없다.

찾는 대상에는 장치 자신뿐 아니라 **함께 사라질 자식들의 id** 도 넣는다.
시퀀스 스텝은 출력을 `"<output_id>,<channel_id>"` 로 저장하고, 그래프
위젯은 출력이 아니라 그 **측정 정의** id 를 가리킨다 — 장치 id 만 찾으면
둘 다 놓친다.

돌려주는 문자열에는 uuid 를 담지 않는다. 그대로 화면에 나가는 문장이고,
사용자가 찾아가야 할 것은 id 가 아니라 이름이다.

@phase active
@stability stable
"""
import logging
from typing import Dict, Iterable, List, Optional, Set

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


def _sites():
    """(모델, 검사할 컬럼들, 사람이 읽을 종류 이름).

    지연 import — 이 모듈은 삭제 경로에서 불리므로 import 순환을 만들지
    않는다.
    """
    from aot.databases.models import (
        Actions, Conditional, ConditionalConditions, CustomController,
        Function, InputChannel, OutputChannel, PID, Trigger, Widget)

    return (
        (Actions, ('do_unique_id', 'custom_options'), 'Action'),
        (OutputChannel, ('custom_options',), 'Output Channel'),
        (InputChannel, ('custom_options',), 'Input Channel'),
        (Trigger, ('unique_id_1', 'unique_id_2', 'unique_id_3',
                   'measurement', 'timer_schedule'), 'Trigger'),
        (Conditional, ('conditional_statement', 'conditional_import',
                       'conditional_initialize', 'conditional_status',
                       'custom_options'), 'Conditional'),
        (ConditionalConditions, ('measurement', 'output_id', 'controller_id'),
         'Condition'),
        (PID, ('measurement', 'raise_output_id', 'lower_output_id'),
         'PID'),
        (CustomController, ('custom_options',), 'Function'),
        (Function, ('custom_options',), 'Function'),
        (Widget, ('custom_options',), 'Widget'),
    )


def _child_ids(device_id: str) -> Set[str]:
    """장치와 **함께 사라질** 행들의 id — 채널과 측정 정의.

    이것을 빼면 시퀀스 스텝("출력id,채널id")과 그래프 위젯(측정 id 를
    가리킨다)을 놓친다.
    """
    from aot.databases.models import (
        DeviceMeasurements, InputChannel, OutputChannel)

    ids = set()
    for model, column in ((OutputChannel, 'output_id'),
                          (InputChannel, 'input_id'),
                          (DeviceMeasurements, 'device_id')):
        try:
            rows = model.query.filter(
                getattr(model, column) == device_id).with_entities(
                model.unique_id).all()
            ids.update(r[0] for r in rows if r[0])
        except Exception:
            logger.debug("자식 id 수집 실패: %s", model.__name__, exc_info=True)
    return ids


def _owner_id(row):
    """이 행이 매달려 있는 부모의 id. 없으면 None."""
    for attr in ('function_id', 'output_id', 'input_id', 'conditional_id'):
        value = getattr(row, attr, None)
        if value:
            return value
    return None


def _owner_label(row, kind) -> str:
    """참조자를 사람이 알아볼 이름으로.

    동작(스텝)과 채널은 그 자체로는 이름이 없다 — 어느 함수·어느 장치의
    것인지 말해야 사용자가 화면에서 찾아갈 수 있다.
    """
    from aot.databases.models import (
        Conditional, CustomController, Function, Input, Output, Trigger)

    kind = _t(kind)
    name = getattr(row, 'name', None)
    if name:
        return _t("%(kind)s '%(name)s'", kind=kind, name=name)

    parent_id = _owner_id(row)
    if parent_id:
        for model in (Trigger, Conditional, CustomController, Function,
                      Output, Input):
            try:
                parent = model.query.filter(
                    model.unique_id == parent_id).first()
            except Exception:
                continue
            if parent is not None and getattr(parent, 'name', None):
                return _t("%(kind)s of '%(parent)s'",
                          kind=kind, parent=parent.name)
    return str(kind)


def find_device_referrers(device_ids: Iterable[str],
                          ignore_ids: Optional[Iterable[str]] = None
                          ) -> Dict[str, List[str]]:
    """장치별로 그것을 아직 쓰고 있는 곳의 이름 목록.

    `ignore_ids` 에는 **같은 작업에서 함께 지워질** 장치의 id 를 넣는다.
    탭을 통째로 지울 때 그 안의 장치끼리 서로를 가리키는 것까지 막으면
    아무것도 지울 수 없다.

    돌려주는 것: {장치 id: ["시퀀스 '3포장 밸브제어' 의 동작", ...]}.
    참조가 없는 장치는 키가 아예 없다.
    """
    device_ids = [d for d in dict.fromkeys(device_ids or ()) if d]
    if not device_ids:
        return {}
    # 장치는 자식(채널·측정 정의)의 id 로도 가리켜진다.
    tokens = {did: {did} | _child_ids(did) for did in device_ids}
    return _find_referrers(tokens, ignore_ids)


def find_referrers(ids: Iterable[str],
                   ignore_ids: Optional[Iterable[str]] = None
                   ) -> Dict[str, List[str]]:
    """장치가 아닌 것(지도 등)을 아직 쓰고 있는 곳.

    장치와 달리 자식 id 로 넓히지 않는다 — 지도의 도형은 지도와 함께
    사라지고, 도형 id 를 JSON 에 들고 있는 곳은 따로 없다.
    """
    ids = [i for i in dict.fromkeys(ids or ()) if i]
    if not ids:
        return {}
    return _find_referrers({i: {i} for i in ids}, ignore_ids)


def _find_referrers(tokens: Dict[str, Set[str]],
                    ignore_ids: Optional[Iterable[str]] = None
                    ) -> Dict[str, List[str]]:
    """선언된 자리를 훑어 토큰을 들고 있는 행을 찾는다."""
    # 함께 사라질 것은 그 자식까지 통째로 무시 대상이다.
    ignore: Set[str] = set(ignore_ids or ())
    for did in list(ignore):
        ignore |= tokens.get(did) or _child_ids(did)

    found: Dict[str, List[str]] = {}

    for model, columns, kind in _sites():
        try:
            rows = model.query.all()
        except Exception:
            logger.debug("참조 검사 건너뜀: %s", model.__name__, exc_info=True)
            continue

        for row in rows:
            row_id = getattr(row, 'unique_id', None)
            if row_id and row_id in ignore:
                continue
            # 동작·채널은 부모가 함께 지워지면 그것도 함께 사라진다.
            owner_id = _owner_id(row)
            if owner_id and owner_id in ignore:
                continue

            blob = ' '.join(str(getattr(row, c, '') or '') for c in columns)
            if not blob.strip():
                continue

            for did, toks in tokens.items():
                if did == row_id or did == owner_id:
                    continue  # 자기 자신은 참조자가 아니다
                if any(tok in blob for tok in toks):
                    label = _owner_label(row, kind)
                    bucket = found.setdefault(did, [])
                    if label not in bucket:
                        bucket.append(label)

    return found


def describe_referrers(labels: List[str], limit: int = 5) -> str:
    """참조자 목록을 한 줄로. 너무 길면 뒤를 접는다."""
    if not labels:
        return ''
    text = ', '.join(labels[:limit])
    if len(labels) > limit:
        text = _t("%(list)s and %(count)d more",
                  list=text, count=len(labels) - limit)
    return text


def deletion_blocked_message(device_name: str, labels: List[str]) -> str:
    """삭제를 막을 때 사용자에게 보일 문장.

    무엇이 막혔는지·어디를 고쳐야 하는지 둘 다 말한다. "삭제할 수 없습니다"
    만 있으면 사용자는 어디를 봐야 하는지 모른다.
    """
    return _t(
        "Cannot delete '%(device)s' — it is still used by: %(referrers)s. "
        "Remove or repoint those references first.",
        device=device_name, referrers=describe_referrers(labels))


# ---------------------------------------------------------------------------
# 화면에서 구분하기
# ---------------------------------------------------------------------------

def _dup_name_cache():
    """요청 하나 안에서 "이름이 겹치는 모델·이름" 집합을 한 번만 만든다.

    옵션 하나마다 조회하면 픽커를 한 번 여는 데 수백 번 질의한다.
    """
    try:
        from flask import g
    except Exception:
        return {}
    cache = getattr(g, '_aot_dup_names', None)
    if cache is None:
        cache = {}
        setattr(g, '_aot_dup_names', cache)
    return cache


def name_is_ambiguous(row) -> bool:
    """같은 종류에 이 이름을 쓰는 것이 둘 이상인가."""
    model = type(row)
    name = getattr(row, 'name', None)
    if not name:
        return False

    cache = _dup_name_cache()
    key = model.__name__
    if key not in cache:
        try:
            from aot.aot_flask.extensions import db
            rows = db.session.query(model.name).all()
        except Exception:
            logger.debug("중복 이름 수집 실패: %s", key, exc_info=True)
            cache[key] = set()
            return False
        seen, dupes = set(), set()
        for (value,) in rows:
            if not value:
                continue
            if value in seen:
                dupes.add(value)
            seen.add(value)
        cache[key] = dupes
    return name in cache[key]


def disambiguated_name(row) -> str:
    """화면에 쓸 이름. **겹칠 때만** 소속 탭을 덧붙인다.

    늘 붙이면 목록이 시끄러워지고, 안 붙이면 겹쳤을 때 구분할 방법이 없다.
    구분이 필요한 순간에만 나오는 것이 맞다 — 사용자가 v11 두 개 중 꺼져
    있는 쪽을 보고 "밸브가 안 열렸다" 고 판단한 것이 이 정보가 없어서였다.

    소속 탭이 곧 그 장치가 어느 현장·어느 계통의 것인지를 말한다. uuid 를
    붙이는 것은 사람에게 아무 도움이 안 된다.
    """
    name = getattr(row, 'name', None) or ''
    if not name or not name_is_ambiguous(row):
        return name

    from aot.databases.models import Tab
    tab_id = getattr(row, 'tab_id', None)
    tab = Tab.query.filter(Tab.unique_id == tab_id).first() if tab_id else None
    tab_name = getattr(tab, 'name', None)
    if not tab_name:
        return name
    return f"{name} ({tab_name})"
