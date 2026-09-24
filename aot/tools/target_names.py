# coding=utf-8
"""대상을 **이름으로** 받는 인자 키 — 처리기와 그룹 스코프 판정의 한 정본.

쓰기 도구 몇 개(`create_note`·`add_schedule`·`edit_schedule`·
`add_schedule_batch`)는 대상을 `target_name` 으로 받고, 처리기가 나중에 id 로
푼다. 모델이 `target_name` 대신 옛 별칭(`location`·`zone_name`…)을 보내도
받아 준다.

그룹 스코프 판정(`tool_execution.scope_arguments`)은 처리기가 읽는 이름 키를
**전부** 알아야 한다 — 처리기만 별칭을 읽고 판정은 `target_name` 만 보면,
별칭으로 주는 것만으로 남의 그룹 장치에 쓰기가 붙는다(2026-09-23 재현:
`add_schedule(location=...)`). 그래서 두 쪽이 이 모듈 하나를 읽는다. 처리기에
새 이름 키를 받게 하려면 **여기에** 넣을 것 — 처리기 안에 따로 적지 말 것.

가벼운 모듈이다(아무것도 import 하지 않는다) — 게이트와 처리기 양쪽이 부담
없이 부를 수 있어야 한다.
"""

#: 정식 이름 키.
TARGET_NAME_KEY = 'target_name'

#: 옛 별칭. `target_name` 이 비었을 때 처리기가 **이 순서로** 읽는다.
TARGET_NAME_ALIASES = ('location', 'zone_name', 'entity_name', 'place')

#: 스코프 판정이 이름으로 풀어 보는 키 전부.
TARGET_NAME_KEYS = (TARGET_NAME_KEY,) + TARGET_NAME_ALIASES


def pop_target_name_alias(extra):
    """`extra`(처리기의 **kwargs)에서 옛 별칭을 꺼낸다. 첫 값, 없으면 None.

    처리기가 받지 않는 키로 남지 않게 **전부** 꺼낸다(pop).
    """
    if not isinstance(extra, dict):
        return None
    found = None
    for key in TARGET_NAME_ALIASES:
        value = extra.pop(key, None)
        if found is None and value:
            found = value
    return found


def get_target_name_alias(extra):
    """읽기 도구용 — `extra` 를 바꾸지 않고 첫 별칭 값을 돌려준다."""
    if not isinstance(extra, dict):
        return None
    for key in TARGET_NAME_ALIASES:
        value = extra.get(key)
        if value:
            return value
    return None
