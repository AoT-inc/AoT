# coding=utf-8
"""복제할 때 **참조를 다시 엮는** 일의 정본.

복제 경로가 두 갈래로 갈라져 있었고, 그중 탭 복제만 모든 안전장치를
우회하고 있었다. 개별 장치 복제(`utils_output.output_duplicate` 등)는
`clone_model` 을 거쳐 교차참조 거부목록([I10])·이름 변경·짝 액추에이터
참조 비우기를 다 했는데, `TabService.duplicate_tab` 은 컬럼을 직접
베껴서 그 방어가 하나도 걸리지 않았다. 그래서 이 모듈이 생겼다 —
**두 경로가 같은 함수를 부르게 해서 다시 갈리지 않게 한다.**

여기서 다루는 참조는 컬럼 하나로 끝나지 않는다. 컬럼 거부목록만으로는
못 막는 것이 셋 있었다.

1. **`Trigger.timer_schedule` 의 요일별 맵.** `days[*].actions/groups/
   durations` 는 **액션 unique_id 를 키로** 쓴다. 사본을 만들면서 액션은
   새 id 로 복제하고 이 JSON 은 문자 그대로 복사하면, 사본의 요일별
   설정이 **원본의 스텝**을 가리킨다. 그리고 조용하다 —
   `weekly_schedule.day_action_enabled()` 는 키가 없으면 오류가 아니라
   전역 기본값으로 떨어지므로, 사본은 "요일별로 꺼둔 스텝이 전부 켜진 채"
   아무 경고 없이 돈다.

2. **Conditional 의 파이썬 코드 안에 박힌 id 문자열.**
   `self.condition("asdf1234")` / `self.run_action("qwer5678")` 처럼
   조건·액션 id 가 코드 리터럴로 들어간다. 게다가
   `base_conditional.run_action()` 은 이 id 를 **전역에서** 찾는다
   (`Actions.unique_id.startswith(...)`). 재배선하지 않으면 사본이
   **원본의 액션을 실행한다** — 사본을 손봤는데 원본 밸브가 움직인다.

3. **출력 채널의 짝 액추에이터 참조.** `output_open_id`/`output_close_id`/
   `selector_output_id` 는 `custom_options` JSON 안에 있어 컬럼 거부목록이
   못 본다. 그대로 복사하면 사본이 **원본의 물리 채널**을 움직인다.

@phase active
@stability stable
@dependency clone_model, weekly_schedule
"""
import json
import logging
import re
from typing import Dict, Iterable, Optional, Tuple

from aot.databases import clone_model, set_uuid
from aot.databases.models import (
    Actions,
    ConditionalConditions,
    DeviceMeasurements,
    FunctionChannel,
    InputChannel,
    OutputChannel,
)

logger = logging.getLogger(__name__)


# `timer_schedule` 의 days[*] 안에서 **액션 unique_id 를 키로 쓰는** 맵.
# 새 맵을 늘릴 때 여기 등록하지 않으면 그 맵만 원본을 가리킨 채 남는다.
# 쓰는 쪽: aot_data_tool_service.py(모두 쓰기), weekly_schedule.day_action_*
# (모두 읽기), widget_trigger_sequence.py(JS 쓰기).
PER_ACTION_SCHEDULE_MAPS = ('actions', 'groups', 'durations')

# Conditional 이 실행하는 사용자 코드 — 여기 조건/액션 id 가 리터럴로 박힌다.
CONDITIONAL_CODE_FIELDS = (
    'conditional_statement',
    'conditional_import',
    'conditional_initialize',
    'conditional_status',
)

# 코드 안에서 id 로 보이는 토큰. 8자 이상이라 우연한 오탐은 사실상 없고,
# `run_action()` 이 접두사 조회를 허용하므로 짧게 적힌 것도 잡아야 한다.
_ID_TOKEN_RE = re.compile(r'[0-9a-fA-F][0-9a-fA-F-]{7,35}')


# ---------------------------------------------------------------------------
# 재배선
# ---------------------------------------------------------------------------

def remap_schedule_action_ids(raw_schedule, action_map: Dict[str, str]) -> Optional[str]:
    """`timer_schedule` JSON 의 요일별 액션 키를 old→new 로 바꾼 문자열.

    `action_map` 에 없는 키는 **버린다.** 사본 입장에서 그런 키는 이미
    고아다 — 자기 스텝이 아닌 것을 가리키고 있으니 남겨 둘 이유가 없고,
    남겨 두는 것이 정확히 지금까지 쓰레기가 쌓인 방식이었다.

    파싱할 수 없으면 원본을 그대로 돌려준다(깨진 JSON 을 여기서 지우면
    사람이 고칠 근거까지 사라진다).
    """
    if not raw_schedule:
        return raw_schedule

    try:
        sched = json.loads(raw_schedule) if isinstance(raw_schedule, str) else dict(raw_schedule)
    except Exception:
        logger.warning("복제: timer_schedule 을 읽을 수 없어 그대로 둡니다.")
        return raw_schedule

    days = sched.get('days')
    if not isinstance(days, dict):
        return json.dumps(sched)

    dropped = 0
    for entry in days.values():
        if not isinstance(entry, dict):
            continue
        for map_key in PER_ACTION_SCHEDULE_MAPS:
            old_map = entry.get(map_key)
            if not isinstance(old_map, dict):
                continue
            new_map = {}
            for uid, value in old_map.items():
                if uid in action_map:
                    new_map[action_map[uid]] = value
                else:
                    dropped += 1
            entry[map_key] = new_map

    if dropped:
        logger.info(
            "복제: 사본의 요일별 설정에서 사본 것이 아닌 키 %s개를 버렸습니다.",
            dropped)

    return json.dumps(sched)


def remap_code_ids(code: Optional[str], id_map: Dict[str, str]) -> Optional[str]:
    """사용자 코드 안의 id 리터럴을 old→new 로 바꾼다.

    전체 uuid 와 접두사 표기를 둘 다 처리한다 —
    `base_conditional.run_action()` / `.condition()` 이 36자 미만이면
    `startswith` 로 찾기 때문에 코드에는 앞 8자만 적혀 있는 경우가 흔하다.

    접두사가 둘 이상의 원본 id 에 걸리면 **바꾸지 않는다.** 어느 쪽인지
    모르는 채로 고르는 것보다 사람이 보게 두는 편이 낫다.
    """
    if not code or not id_map:
        return code

    def _sub(match):
        token = match.group(0)
        lowered = token.lower()
        if lowered in id_map:
            return id_map[lowered]
        candidates = [new for old, new in id_map.items() if old.startswith(lowered)]
        if len(candidates) == 1:
            return candidates[0][:len(token)]
        return token

    return _ID_TOKEN_RE.sub(_sub, code)


def blank_paired_channel_refs(channel) -> bool:
    """짝 액추에이터 채널의 열림/닫힘/셀렉터 참조와 위치 상태를 비운다.

    비우지 않으면 사본이 **원본의 물리 채널**을 움직인다. 사용자가 사본
    쪽에서 다시 지정해야 한다 — 같은 좌표에 있는 서로 다른 물리 장치는
    성립하지 않는다.

    바꿨으면 True. 호출자가 저장한다.
    """
    if not channel or not getattr(channel, 'custom_options', None):
        return False
    try:
        opts = json.loads(channel.custom_options)
    except Exception:
        return False
    if not isinstance(opts, dict):
        return False

    changed = False
    for key in ('output_open_id', 'output_close_id', 'selector_output_id'):
        if key in opts and opts[key]:
            opts[key] = ''
            changed = True
    for key in ('last_position_pct', 'last_target_pct'):
        if key in opts and opts[key]:
            opts[key] = 0.0
            changed = True

    if changed:
        channel.custom_options = json.dumps(opts)
    return changed


# ---------------------------------------------------------------------------
# 이름
# ---------------------------------------------------------------------------

def unique_copy_name(base_name: str, taken: Iterable[str], style: str = 'suffix') -> str:
    """겹치지 않는 사본 이름.

    `style` 은 **개별 복제가 이미 쓰는 규칙**을 그대로 따른다 — 새 규칙을
    만들면 같은 화면에서 두 가지 이름이 나온다.
      - 'prefix': `Copy of X`  (input_duplicate / output_duplicate)
      - 'suffix': `X (Copy)`   (function_duplicate)

    이미 있으면 뒤에 번호를 붙인다. 이름만 보이는 화면에서 똑같은 이름이
    셋씩 생기는 것을 막는 것이 이 함수의 존재 이유다.
    """
    base_name = (base_name or '').strip() or 'Unnamed'
    taken = set(taken or ())

    def _candidate(n):
        if style == 'prefix':
            return f"Copy of {base_name}" if n == 1 else f"Copy of {base_name} ({n})"
        return f"{base_name} (Copy)" if n == 1 else f"{base_name} (Copy {n})"

    n = 1
    while _candidate(n) in taken:
        n += 1
        if n > 999:  # 방어: 무한 루프보다 겹치는 이름이 낫다
            break
    return _candidate(n)


# ---------------------------------------------------------------------------
# 복제
# ---------------------------------------------------------------------------

def _clone_overrides(**kwargs) -> dict:
    """`clone_model` 에 넘길 kwargs. None 인 항목은 원본 값을 그대로 둔다."""
    overrides = {'unique_id': set_uuid()}
    for key, value in kwargs.items():
        if value is not None:
            overrides[key] = value
    return overrides


def _fill_timezone_fallback(clone):
    """좌표가 없어 `device_tz_listeners` 가 tz 를 못 채운 경우의 보정.

    tz 가 비면 `get_device_tz()` 가 UTC 로 떨어져 시퀀스 창이 아홉 시간
    어긋난다. 좌표가 있으면 리스너가 채우므로 손대지 않는다.
    """
    if not hasattr(clone, 'timezone'):
        return
    if getattr(clone, 'timezone', None) or getattr(clone, 'latitude', None):
        return
    try:
        from aot.databases.models import Misc
        misc = Misc.query.first()
        if misc and misc.timezone:
            clone.timezone = misc.timezone
            # 출처를 같이 남긴다 — tz_source 가 비면 나중에 이 값이 좌표에서
            # 나온 것인지 사람이 지정한 것인지 판정할 수 없다.
            # (docs/design/timezone-management.md)
            if hasattr(clone, 'tz_source') and not getattr(clone, 'tz_source', None):
                clone.tz_source = 'inherited'
    except Exception:
        logger.debug("복제: timezone 폴백을 적용하지 못했습니다.", exc_info=True)


def clone_device_entry(entry, channel_model, channel_fk: str,
                       tab_id: Optional[str] = None,
                       name: Optional[str] = None,
                       position_y: Optional[int] = None,
                       deactivate: bool = True,
                       paired: bool = False):
    """Input/Output 한 건과 그 자식(측정·채널·액션)을 복제한다.

    `clone_model` 을 거치므로 교차참조 거부목록([I10])이 그대로 적용된다 —
    사본은 지도에 **미배치**로 시작한다. 배치가 필요하면
    `geo.device_placement.place_device` 를 쓸 것.
    """
    clone = clone_model(entry, **_clone_overrides(
        tab_id=tab_id, name=name, position_y=position_y))
    if clone is None:
        logger.error("복제 실패: %s", getattr(entry, 'unique_id', '?'))
        return None

    old_id, new_id = entry.unique_id, clone.unique_id

    if deactivate and getattr(clone, 'is_activated', False):
        clone.is_activated = False
    _fill_timezone_fallback(clone)
    clone.save()

    # 측정 정의. 이것이 없으면 사본은 채널만 있고 아무것도 기록하지 않는다.
    for meas in DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == old_id).all():
        clone_model(meas, unique_id=set_uuid(), device_id=new_id)

    for channel in channel_model.query.filter(
            getattr(channel_model, channel_fk) == old_id).all():
        new_channel = clone_model(
            channel, unique_id=set_uuid(), **{channel_fk: new_id})
        if paired and new_channel and blank_paired_channel_refs(new_channel):
            new_channel.save()

    # 장치에 붙은 액션(삭제 경로가 지우는 것과 같은 집합).
    for action in Actions.query.filter(Actions.function_id == old_id).all():
        clone_model(action, unique_id=set_uuid(), function_id=new_id)

    return clone


def clone_input_entry(entry, **kwargs):
    """Input 복제. `input_duplicate()` 와 같은 자식 집합을 옮긴다."""
    return clone_device_entry(entry, InputChannel, 'input_id', **kwargs)


def clone_output_entry(entry, **kwargs):
    """Output 복제. 짝 액추에이터면 물리 채널 참조를 비운다."""
    from aot.outputs.paired_actuator_common import PAIRED_ACTUATOR_OUTPUT_TYPES
    kwargs.setdefault(
        'paired', getattr(entry, 'output_type', None) in PAIRED_ACTUATOR_OUTPUT_TYPES)
    return clone_device_entry(entry, OutputChannel, 'output_id', **kwargs)


def clone_function_entry(entry,
                         tab_id: Optional[str] = None,
                         name: Optional[str] = None,
                         position_y: Optional[int] = None,
                         deactivate: bool = True) -> Tuple[object, dict]:
    """Trigger/Conditional/PID/CustomController/Function 한 건을 **참조까지** 복제.

    자식(액션·조건·측정·채널)을 새 id 로 복제한 뒤, 그 id 를 가리키던
    곳을 전부 다시 엮는다:
      - `timer_schedule` 의 요일별 액션 맵
      - Conditional 코드 안의 조건/액션 id 리터럴

    돌려주는 것: (사본, {'actions': old→new, 'conditions': old→new})
    """
    clone = clone_model(entry, **_clone_overrides(
        tab_id=tab_id, name=name, position_y=position_y))
    if clone is None:
        logger.error("복제 실패: %s", getattr(entry, 'unique_id', '?'))
        return None, {'actions': {}, 'conditions': {}}

    old_id, new_id = entry.unique_id, clone.unique_id

    # 사본은 사용자가 다시 켜기 전까지 비활성이다. Function 처럼 이 필드가
    # 없는 모델도 있어 getattr 로 방어한다.
    if deactivate and getattr(clone, 'is_activated', False):
        clone.is_activated = False
    _fill_timezone_fallback(clone)

    action_map = {}
    for action in Actions.query.filter(Actions.function_id == old_id).all():
        new_action = clone_model(action, unique_id=set_uuid(), function_id=new_id)
        if new_action:
            action_map[action.unique_id] = new_action.unique_id

    condition_map = {}
    for cond in ConditionalConditions.query.filter(
            ConditionalConditions.conditional_id == old_id).all():
        new_cond = clone_model(cond, unique_id=set_uuid(), conditional_id=new_id)
        if new_cond:
            condition_map[cond.unique_id] = new_cond.unique_id

    for meas in DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == old_id).all():
        clone_model(meas, unique_id=set_uuid(), device_id=new_id)

    for channel in FunctionChannel.query.filter(
            FunctionChannel.function_id == old_id).all():
        clone_model(channel, unique_id=set_uuid(), function_id=new_id)

    # --- 재배선 ---
    if hasattr(clone, 'timer_schedule'):
        clone.timer_schedule = remap_schedule_action_ids(
            clone.timer_schedule, action_map)

    id_map = dict(action_map)
    id_map.update(condition_map)
    if id_map:
        for field in CONDITIONAL_CODE_FIELDS:
            if hasattr(clone, field):
                setattr(clone, field, remap_code_ids(getattr(clone, field), id_map))

    clone.save()
    return clone, {'actions': action_map, 'conditions': condition_map}
