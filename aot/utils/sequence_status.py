# coding=utf-8
"""시퀀스 상태의 순수 계산 — 데몬이 꺼져 있어도 DB 만으로 답하는 부분 (아키텍처 7c).

원래 `controllers/controller_trigger_sequence.py` 에 있었으나, 웹 계층(routes_function)이
"데몬이 죽었을 때의 폴백" 하나를 쓰려고 컨트롤러(데몬 계층)를 import 하고 있었다.
함수 본문은 그대로 옮겼고, 컨트롤러는 같은 이름으로 다시 내보낸다(기존 import·패치 경로 유지).
"""
import json
import logging

from aot.config import AOT_DB_PATH
from aot.databases.models import Trigger, Actions, Input, CustomController, Output, OutputChannel
from aot.databases.utils import session_scope
from aot.utils import sequence_schedule
from aot.utils.actions import parse_action_information
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.timekit import tz_of
from aot.utils.weekly_schedule import (
    active_entry_now, day_action_enabled, day_action_group,
    day_action_duration, get_today_idx,
)

logger = logging.getLogger(__name__)


def _ambiguous_output_tabs(rows):
    """이름이 겹치는 출력만 `{unique_id: 탭 이름}`. 안 겹치면 빈 dict.

    집계 한 번으로 겹치는 이름을 먼저 추리고, 걸린 것이 있을 때만 탭을
    읽는다. 이 함수를 부르는 자리는 시퀀스 위젯이 5초마다 두드리는 경로라
    "혹시 몰라 다 읽는" 조회를 넣으면 안 된다.
    """
    rows = [r for r in (rows or []) if getattr(r, 'name', None)]
    if not rows:
        return {}
    try:
        from sqlalchemy import func
        with session_scope(AOT_DB_PATH) as sess:
            names = {r.name for r in rows}
            dupes = {
                name for (name,) in sess.query(Output.name)
                .filter(Output.name.in_(list(names)))
                .group_by(Output.name)
                .having(func.count(Output.id) > 1).all()}
            if not dupes:
                return {}
            tab_ids = {r.tab_id for r in rows
                       if r.name in dupes and getattr(r, 'tab_id', None)}
            if not tab_ids:
                return {}
            from aot.databases.models import Tab
            tab_names = {t.unique_id: t.name for t in sess.query(Tab).filter(
                Tab.unique_id.in_(list(tab_ids))).all()}
        return {r.unique_id: tab_names.get(r.tab_id)
                for r in rows
                if r.name in dupes and tab_names.get(getattr(r, 'tab_id', None))}
    except Exception as e:
        logger.error(f"_ambiguous_output_tabs failed: {e}")
        return {}


def resolve_device_details(target_ids):
    """여러 target_id → `{target_id: 사람이 읽는 문자열}` 을 **한 번에**.

    낱개 해소(`_resolve_device_detail`)는 대상 하나에 최대 4번 조회한다 —
    Output 에서 못 찾으면 Input, 그다음 CustomController 순으로 훑기 때문이라,
    출력이 아닌 대상일수록 조회가 늘어난다. 스텝마다 부르면 그것이 스텝 수만큼
    곱해진다. `/function_status_activated` 는 시퀀스 위젯이 **5초마다** 부르는데,
    라즈베리파이 실측에서 한 번에 421ms · 쿼리 32건이었고 그중 314ms(75%)가
    이 조회였다. 워커가 하나인 서버에서 5초마다 421ms 면 위젯 하나가 CPU 를
    상시 물고 있는 셈이다.

    표마다 한 번씩(최대 4쿼리) 읽고 메모리에서 맞춘다.
    """
    out = {}
    ids = [t for t in (target_ids or []) if t]
    if not ids:
        return out

    # "uuid" 또는 "uuid,channel_uuid" 두 형태가 섞여 들어온다.
    main_of, chan_of = {}, {}
    for t in ids:
        parts = str(t).split(',')
        main_of[t] = parts[0]
        chan_of[t] = parts[1] if len(parts) > 1 else None

    def _by_uid(model, uids):
        if not uids:
            return {}
        try:
            rows = db_retrieve_table_daemon(model).filter(
                model.unique_id.in_(list(uids))).all()
            return {r.unique_id: r for r in rows}
        except Exception as e:
            logger.error(f"resolve_device_details({model.__name__}) failed: {e}")
            return {}

    main_ids = set(main_of.values())
    outputs = _by_uid(Output, main_ids)
    # 이름이 겹치는 출력만 소속 탭을 덧붙인다. 늘 붙이면 목록이 시끄럽고,
    # 안 붙이면 같은 이름 둘을 구분할 방법이 없다 — 사용자가 v11 두 개 중
    # 꺼져 있는 쪽을 보고 "밸브가 안 열렸다" 고 판단한 것이 그래서였다.
    # 집계 한 번이라 겹치는 이름이 없으면 뒤 조회도 돌지 않는다.
    tab_of = _ambiguous_output_tabs(outputs.values())
    # Output 에서 찾은 것은 나머지 표에서 다시 찾을 필요가 없다.
    rest = {m for m in main_ids if m not in outputs}
    inputs = _by_uid(Input, rest)
    rest = {m for m in rest if m not in inputs}
    funcs = _by_uid(CustomController, rest)
    channels = _by_uid(OutputChannel,
                       {c for c in chan_of.values() if c})

    for t in ids:
        main_id, raw_chan = main_of[t], chan_of[t]
        row = outputs.get(main_id)
        if row is not None:
            detail = row.name
            tab_name = tab_of.get(row.unique_id)
            if tab_name:
                detail += f" ({tab_name})"
            if raw_chan:
                chan_obj = channels.get(raw_chan)
                if chan_obj is not None:
                    detail += f" [CH{chan_obj.channel}]"
                elif len(str(raw_chan)) <= 5:
                    detail += f" [CH{raw_chan}]"
            out[t] = detail
            continue
        row = inputs.get(main_id)
        if row is not None:
            out[t] = f"{row.name} [Input]"
            continue
        row = funcs.get(main_id)
        out[t] = f"{row.name} [Func]" if row is not None else "-"
    return out


def _resolve_device_detail(target_id, details=None):
    """낱개 해소. `details`(resolve_device_details 결과)가 있으면 그것을 쓴다.

    대상을 여럿 도는 자리는 `resolve_device_details` 를 한 번 불러 넘길 것 —
    여기서 하나씩 부르면 표 3개를 대상 수만큼 다시 훑는다.
    """
    if not target_id:
        return "-"
    if details is not None and target_id in details:
        return details[target_id]
    return resolve_device_details([target_id]).get(target_id, "-")


def _parse_opts(action):
    """Safely parse an action's custom_options JSON into a dict."""
    try:
        return json.loads(action.custom_options) if action.custom_options else {}
    except Exception:
        return {}


def _group_key(action):
    """Return an action's device-group label, or None if ungrouped."""
    name = (_parse_opts(action).get('group_name') or '').strip()
    return name or None


def _margins(opts):
    """(lead, lag) seconds from a step's custom_options. Bad values read as 0."""
    try:
        return (max(0.0, float(opts.get('total_lead') or 0)),
                max(0.0, float(opts.get('total_lag') or 0)))
    except (TypeError, ValueError):
        return (0.0, 0.0)


def _total_window(opts, span, log=None, label=''):
    """Start/end of a 'total' step inside a cycle of length ``span``.

    A total step (typically the field's pump) runs across the whole sequence
    while the single steps (valves) take their turns. Without margins it turns
    on at elapsed 0.0 -- the same instant as the first valve slot -- and off at
    the same instant as the last one, so nothing guarantees the valve is open
    before the pump pushes against it, or that the pump has stopped before the
    valve closes (water hammer).

    ``total_lead``/``total_lag`` (seconds, per-step custom_options) inset the
    total window inside the single-step envelope: lead delays the start, lag
    brings the end forward. Both default to 0, which is the historical
    behaviour. Margins that would swallow the window are ignored (a pump that
    never runs is worse than one without margins).
    """
    lead, lag = _margins(opts)
    start_t = lead
    end_t = span - lag
    if end_t <= start_t:
        if log:
            log.warning(
                f"Total step {label}: lead({lead}s)+lag({lag}s) leaves no room in "
                f"a {span}s cycle -- running the full span instead.")
        return 0.0, span
    return start_t, end_t


def _build_slots(single_actions, group_of=None):
    """Collapse single-mode actions into ordered scheduling slots.

    A slot is a list of actions that occupy the *same* time window. Actions
    sharing a group name (a device group) become one slot and therefore fire
    simultaneously with a single common duration; ungrouped actions each get
    their own slot. Slot order follows the first-seen position of each action
    (single_actions must already be position-sorted); a later member of an
    already-seen group folds into that group's earlier slot.

    ``group_of(action)`` resolves each action's effective group name (used for
    per-weekday group overrides); it defaults to the action's global
    ``group_name`` (``_group_key``).

    Returns a list of ``(group_name_or_None, [actions])`` tuples.
    """
    if group_of is None:
        group_of = _group_key
    slots = []
    group_index = {}
    for action in single_actions:
        gname = group_of(action)
        if gname:
            if gname in group_index:
                slots[group_index[gname]][1].append(action)
                continue
            group_index[gname] = len(slots)
            slots.append((gname, [action]))
        else:
            slots.append((None, [action]))
    return slots


def _format_plan_warning_en(warning_code):
    """English text for one plan_for_day() warning code.

    This is the wording the AI tools (get_function_detail,
    configure_sequence_day) have always shown, kept exactly as it was.
    The web UI translates the same ``warning_code`` dicts instead of
    re-deriving them — see aot.aot_flask.utils.utils_trigger.
    sequence_schedule_day_warnings().
    """
    code = warning_code["code"]
    if code == "empty":
        return "No step runs on this day — the window opens but nothing happens."
    if code == "window_cutoff":
        return (f"One pass takes {warning_code['span']:.0f}s but the window is only "
                f"{warning_code['window_sec']}s — it will be cut off before finishing.")
    if code == "period_restart":
        return (f"One pass takes {warning_code['span']:.0f}s but the cycle restarts every "
                f"{warning_code['period']:.0f}s — it will restart before finishing.")
    if code == "repeats_per_day":
        return (f"The cycle repeats every {warning_code['period']:.0f}s inside a "
                f"{warning_code['window_sec']}s window, so it runs about "
                f"{warning_code['repeats']} times that day rather than once.")
    return ""


def build_sequence_status_facts(status, state, wait_s=None):
    """시퀀스 상태 dict → 함수 상태 위젯이 읽을 **사실 묶음**.

    이 컨트롤러의 상태 dict 는 `status_text`·`steps` 같은 **구조**로 되어 있고
    시퀀스 위젯은 그것을 표로 그린다. 그런데 공용 "함수 상태" 위젯의 JS 는
    `string_status` 와 `error` **두 키만** 읽으므로, 구조만 있고 그 키가 없으면
    폴링이 정상 200 을 받는데도 화면에는 **아무것도 안 뜬다**(에러도 없다).

    ⚠ **문장은 여기서 만들지 않는다.** 데몬에는 요청 컨텍스트가 없어 `gettext`
      가 뷰어의 언어로 풀리지 않는다 — 사실만 내보내고 문장은 Flask 쪽
      (`aot_flask/utils/utils_function_status.py`)이 만든다.

    ⚠ **`function_status()`(데몬 살아 있음)와 `get_static_status()`(데몬 정지)가
      같은 함수를 쓴다.** 두 벌로 적으면 갈라지고, 그러면 같은 시퀀스가 데몬
      상태에 따라 다른 말을 한다 — 사용자는 그것을 시퀀스가 바뀐 것으로 읽는다.

    ⚠ 스텝 수는 여기서 세지 않는다. 라우트가 데몬 응답에 정적 스텝을 나중에
      합쳐 넣는 경로가 있어(`function_status_activated`), 여기서 세면 합쳐진
      뒤와 어긋난다 — 렌더러가 응답의 `steps` 를 직접 센다.
    """
    return {
        'kind': 'sequence',
        'state': state,
        'wait_s': wait_s,
        'window_start': status.get('window_start'),
        'window_end': status.get('window_end'),
        'period_s': status.get('period'),
        'in_cycle': bool(status.get('cycle_start_time')),
        'elapsed_s': status.get('elapsed'),
    }


def static_status(unique_id):
    """Returns the status of the sequence from DB (for inactive controllers)."""
    trigger = db_retrieve_table_daemon(Trigger, unique_id=unique_id)
    if not trigger:
        return {'error': [f"Trigger {unique_id} not found"]}

    actions = db_retrieve_table_daemon(Actions).filter(Actions.function_id == unique_id).all()
    try:
        actions = sorted(actions, key=lambda x: (x.position if x.position is not None else 999))
    except:
        actions = sorted(actions, key=lambda x: x.id)

    dict_action_info = parse_action_information()
    overlap = float(trigger.output_duration or 0)

    from aot.utils.timekit import tz_of
    tz = tz_of(trigger)
    sched = sequence_schedule.load(trigger)
    today_idx = get_today_idx(tz)

    # Determine steps/schedule (per-day actions map overrides global flag)
    enabled_actions = []
    for a in actions:
        try:
            opts = json.loads(a.custom_options) if a.custom_options else {}
        except:
            opts = {}
        if day_action_enabled(sched, today_idx, a.unique_id, opts.get('enabled', True)):
            enabled_actions.append((a, opts))

    single_actions = [item for item in enabled_actions if item[1].get('sequence_mode', 'single') != 'total']
    total_actions = [item for item in enabled_actions if item[1].get('sequence_mode', 'single') == 'total']

    schedule = []
    prev_end_time = 0.0
    max_end_time = 0.0

    # Grouped actions (shared group_name) collapse into one slot and share a
    # single common duration, mirroring build_cycle_schedule (live). Group
    # and duration honor per-weekday overrides for today.
    def _sgroup_of(a):
        return day_action_group(sched, today_idx, a.unique_id, _group_key(a))
    def _sdur_of(a):
        return day_action_duration(sched, today_idx, a.unique_id,
                                   float(_parse_opts(a).get('action_duration', 0)))
    slots = _build_slots([item[0] for item in single_actions], _sgroup_of)
    count = len(slots)
    for i, (gname, members) in enumerate(slots):
        rep = members[0]
        ropts = _parse_opts(rep)
        base_duration = float(_sdur_of(rep))
        # Dynamic duration fallback to base for static view
        step_time = base_duration

        head_overlap = overlap if i > 0 else 0
        tail_overlap = overlap if i < count - 1 else 0
        total_on_duration = head_overlap + step_time + tail_overlap

        start_t = (prev_end_time - overlap) if i > 0 else 0.0
        if start_t < 0: start_t = 0.0
        end_t = start_t + total_on_duration
        prev_end_time = end_t
        if end_t > max_end_time: max_end_time = end_t

        for action in members:
            schedule.append({'action_uid': action.unique_id, 'start': start_t, 'end': end_t})

    total_mode_duration = max_end_time if max_end_time > 0 else float(trigger.period or 3600)

    # Total steps were previously left out of the static schedule, so a
    # deactivated sequence showed its pump row with no start/end at all.
    # Mirror the live path (build_cycle_schedule) so the widget renders the
    # same window whether or not the controller is running.
    for action, aopts in total_actions:
        start_t, end_t = _total_window(aopts, total_mode_duration)
        schedule.append({'action_uid': action.unique_id, 'start': start_t, 'end': end_t})

    # 대상 이름은 **한 번에** 해소한다 — 스텝마다 부르면 표 3개를 스텝 수만큼
    # 훑는다(이 엔드포인트는 5초마다 폴링된다).
    _targets = []
    for _a in actions:
        _o = _parse_opts(_a)
        _t = _a.do_unique_id or _o.get('output') or _o.get('input')
        if _t:
            _targets.append(_t)
    details = resolve_device_details(_targets)

    steps = []
    for action in actions:
        try:
            opts = json.loads(action.custom_options) if action.custom_options else {}
        except:
            opts = {}

        sched_item = next((i for i in schedule if i['action_uid'] == action.unique_id), None)

        # Action Desc
        action_desc = action.name if hasattr(action, 'name') and action.name else action.action_type
        if action.action_type in dict_action_info:
            action_desc = str(dict_action_info[action.action_type]['name'])

        # Name / Device Detail
        target_id = action.do_unique_id or opts.get('output') or opts.get('input')
        device_detail = _resolve_device_detail(target_id, details=details)

        # Prepare original duration for display
        display_duration = ""
        try:
            if 'action_duration' in opts: display_duration = str(opts['action_duration'])
            elif 'duration' in opts: display_duration = str(opts['duration'])
        except: pass

        steps.append({
            'unique_id': action.unique_id,
            'action_id': action.id,
            'action_name': action_desc,
            'device_detail': device_detail,
            'type': opts.get('sequence_mode', 'single'),
            'enabled': opts.get('enabled', True),
            'start': sched_item['start'] if sched_item else None,
            'end': sched_item['end'] if sched_item else None,
            'original_duration': display_duration,
            'group_name': (opts.get('group_name') or '').strip() or None,
            'display_name': (opts.get('display_name') or '').strip() or None,
            'total_lead': _margins(opts)[0],
            'total_lag': _margins(opts)[1],
            'is_active': False
        })

    today_entry = sched.get('days', {}).get(str(today_idx), {})
    active = active_entry_now(sched, tz)
    status_code = 'ready' if trigger.is_activated else 'standby'
    status = {
        'is_activated': trigger.is_activated,
        'status_text': "Ready" if trigger.is_activated else "Standby",
        'status_code': status_code,
        'window_start': today_entry.get('start', trigger.timer_start_time or "00:00"),
        'window_end': today_entry.get('end', trigger.timer_end_time or "00:00"),
        'period': float(today_entry.get('period', trigger.period or 3600)),
        'cycle_start_time': 0,
        'elapsed': 0,
        'weekdays': getattr(trigger, 'timer_weekday', None) or '',
        'schedule': sched,
        'today': today_idx,
        'today_window': {'start': active[1]['start'], 'end': active[1]['end'], 'period': active[1]['period']} if active else None,
        'steps': steps
    }
    status['status_facts'] = build_sequence_status_facts(status, status_code)
    return status
