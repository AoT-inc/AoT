import logging
import time
import json
import threading
from datetime import datetime

import pytz

from aot.utils.time_utils import utc_now


from aot.aot_client import DaemonControl
from aot.config import AOT_DB_PATH
from aot.controllers.base_controller import AbstractController
from aot.databases.models import Trigger, Actions, Input, CustomController, InputChannel, DeviceMeasurements, Output, OutputChannel, Misc, SMTP, PID, FunctionRuntimeState
from aot.databases.utils import session_scope
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.actions import parse_action_information, trigger_controller_actions, trigger_action
from aot.utils.system_pi import time_between_range
from aot.utils.influx import get_last_measurement
from aot.utils.device_tz import get_device_tz
from aot.utils.command_origin import TYPE_SEQUENCE as SOURCE_SEQUENCE
from aot.utils.execution_context import set_execution_context, clear_execution_context
from aot.utils.weekly_schedule import (
    DAY_NAMES, active_entry_now, day_action_enabled, day_action_group,
    day_action_duration, from_legacy, is_continuity_boundary, get_today_idx,
    parse_schedule, time_to_minutes, to_legacy, window_bounds_epoch,
    window_start_epoch
)

logger = logging.getLogger(__name__)


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


class SequenceTriggerController(AbstractController, threading.Thread):
    """Sequence trigger controller that executes ordered actions in a timed cycle.

    @phase active
    @stability stable
    @dependency AbstractController, Trigger, Actions, DaemonControl
    @owner foreman
    """

    def _step_output_state(self, opts, states_snapshot=None):
        """Actual device state of a step's target output, or None for non-output
        steps. Reads from a states snapshot (output_states_all) fetched once per
        status build to avoid an RPC per step. Channel-index lookups are cached."""
        try:
            out_ref = opts.get('output')
            if not out_ref:
                return None
            if ',' not in str(out_ref):
                oid = str(out_ref).strip()
                ch_idx = 0
                if not oid:
                    return None
            else:
                oid, cuid = str(out_ref).split(',', 1)
                oid = oid.strip()
                cuid = cuid.strip()
                if cuid in self._chan_idx_cache:
                    ch_idx = self._chan_idx_cache[cuid]
                else:
                    ch_obj = db_retrieve_table_daemon(OutputChannel).filter(
                        OutputChannel.unique_id == cuid).first()
                    ch_idx = ch_obj.channel if ch_obj else 0
                    self._chan_idx_cache[cuid] = ch_idx
            if isinstance(states_snapshot, dict):
                chans = states_snapshot.get(oid)
                if isinstance(chans, dict):
                    # channel keys may be int or str depending on the transport
                    return chans.get(ch_idx, chans.get(str(ch_idx)))
                return None
            # Fallback: single query (used if no snapshot was provided)
            return self.control.output_state(oid, output_channel=ch_idx)
        except Exception:
            return None

    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)
        self.ready = ready
        self.unique_id = unique_id
        
        # Initialize sequence specific vars
        self.control = DaemonControl()
        self.cycle_start_time = None
        self.activation_timestamp = 0
        self.current_schedule = []
        self.active_actions = set()
        self._close_grace_started = None
        self.all_actions_cache = []
        self._chan_idx_cache = {}  # OutputChannel.unique_id -> channel index
        self.logger = logger # Use module-level logger initially
        self.logger_instance = logging.getLogger(f"{__name__}_{unique_id.split('-')[0]}")

    def function_status(self):
        """Returns the status of the controller."""
        steps = []
        cycle_start = self.cycle_start_time
        now = time.time()
        elapsed = now - cycle_start if cycle_start else 0
        
        # Determine status text
        status_text = "Idle"
        if self.is_activated:
            if self.start_latency > 0 and (now - self.activation_timestamp) < self.start_latency:
                 status_text = f"Waiting ({self.start_latency - (now - self.activation_timestamp):.0f}s)"
            elif not active_entry_now(self.schedule, self.device_tz):
                 status_text = "Outside Window"
            elif cycle_start:
                 status_text = "Running"
            else:
                 status_text = "Activated"

        if not hasattr(self, 'all_actions_cache'):
             return {'is_activated': self.is_activated, 'status_text': 'Initializing'}

        # One snapshot of all output states per status build (not per step) so the
        # widget can show each step's actual device state (pending/fault/offline).
        try:
            _states_snapshot = self.control.output_states_all()
        except Exception:
            _states_snapshot = None

        for act in self.all_actions_cache:
             try:
                 opts = json.loads(act.custom_options) if act.custom_options else {}
             except:
                 opts = {}
             
             # Find in schedule to get start/end times if scheduled
             sched_item = next((i for i in self.current_schedule if i['action'].unique_id == act.unique_id), None)
             
             # Get Action Description (ACTION Column)
             action_desc = act.name if hasattr(act, 'name') and act.name else act.action_type
             if act.action_type in self.dict_actions:
                 action_desc = self.dict_actions[act.action_type]['name']

             # Get Device Details (NAME Column)
             target_id = act.do_unique_id or opts.get('output') or opts.get('input')
             device_detail = _resolve_device_detail(target_id)

             # Prepare original duration for display
             display_duration = ""
             try:
                 if 'action_duration' in opts: display_duration = str(opts['action_duration'])
                 elif 'duration' in opts: display_duration = str(opts['duration'])
             except: pass

             steps.append({
                 'unique_id': act.unique_id,
                 'action_id': act.id,
                 'action_name': action_desc,  # Renamed from 'name'
                 'device_detail': device_detail, # New field
                 'type': opts.get('sequence_mode', 'single'),
                 'enabled': opts.get('enabled', True),
                 'start': sched_item['start'] if sched_item else None,
                 'end': sched_item['end'] if sched_item else None,
                 'original_duration': display_duration,
                 'group_name': (opts.get('group_name') or '').strip() or None,
                 'display_name': (opts.get('display_name') or '').strip() or None,
                 'total_lead': _margins(opts)[0],
                 'total_lag': _margins(opts)[1],
                 'is_active': act.unique_id in self.active_actions,
                 # Actual device state of the target output ('on'/'off'/'pending'/
                 # 'fault'/number/None) so the widget shows offline/pending per step
                 # instead of trusting the schedule alone.
                 'output_state': self._step_output_state(opts, _states_snapshot),
             })
             
        today_idx = get_today_idx(self.device_tz)
        active = active_entry_now(self.schedule, self.device_tz)
        today_entry = self.schedule.get('days', {}).get(str(today_idx), {})
        return {
            'is_activated': self.is_activated,
            'status_text': status_text,
            'window_start': today_entry.get('start', self.window_start_time),
            'window_end': today_entry.get('end', self.window_end_time),
            'period': self.sequence_cycle_duration,
            'cycle_start_time': cycle_start if cycle_start else 0,
            'elapsed': elapsed,
            'weekdays': self.timer_weekday,
            'schedule': self.schedule,
            'today': today_idx,
            'today_window': {'start': active[1]['start'], 'end': active[1]['end'], 'period': active[1]['period']} if active else None,
            'steps': steps
        }

    @staticmethod
    def get_static_status(unique_id):
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

        from aot.utils.device_tz import get_device_tz
        tz = get_device_tz(trigger)
        raw_schedule = getattr(trigger, 'timer_schedule', None)
        sched = parse_schedule(raw_schedule) or from_legacy(
            trigger.timer_start_time, trigger.timer_end_time,
            getattr(trigger, 'timer_weekday', None), trigger.period or 3600,
        )
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
                action_desc = dict_action_info[action.action_type]['name']

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
        return {
            'is_activated': trigger.is_activated,
            'status_text': "Standby" if not trigger.is_activated else "Ready",
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

    @staticmethod
    def plan_for_day(unique_id, day_idx):
        """What this sequence actually does on one weekday, as wall-clock slots.

        get_static_status() answers only for *today*, so anyone configuring
        another weekday had no way to check their work — the schedule JSON says
        which steps are enabled and how long they run, but the running order and
        the resulting times come from slot maths that lived only inside the
        controller. Resolving it here lets callers (the AI tools, tests) show
        "Thu 21:00-21:40 v321+v322" instead of a raw map.

        Read-only and DB-derived; safe to call from any process.
        """
        trigger = db_retrieve_table_daemon(Trigger, unique_id=unique_id)
        if not trigger:
            return {"error": f"Trigger {unique_id} not found"}

        sched = parse_schedule(getattr(trigger, 'timer_schedule', None)) or from_legacy(
            trigger.timer_start_time, trigger.timer_end_time,
            getattr(trigger, 'timer_weekday', None), trigger.period or 3600)
        entry = (sched.get('days') or {}).get(str(day_idx), {})
        day_name = DAY_NAMES[day_idx] if 0 <= day_idx <= 6 else str(day_idx)

        out = {
            "day": day_idx,
            "day_name": day_name,
            "runs": bool(entry.get('enabled', True)),
            "window_start": entry.get('start'),
            "window_end": entry.get('end'),
            "period_seconds": entry.get('period'),
            "slots": [],
            "excluded": [],
            "warnings": [],
        }
        if not out["runs"]:
            return out

        actions = db_retrieve_table_daemon(Actions).filter(
            Actions.function_id == unique_id).all()
        try:
            actions = sorted(actions, key=lambda x: x.position)
        except Exception:
            actions = sorted(actions, key=lambda x: x.id)

        def _label(a):
            o = _parse_opts(a)
            return (o.get('display_name') or '').strip() or _resolve_device_detail(
                a.do_unique_id or o.get('output') or o.get('input'))

        on, off = [], []
        for a in actions:
            o = _parse_opts(a)
            (on if day_action_enabled(sched, day_idx, a.unique_id,
                                      o.get('enabled', True)) else off).append(a)
        out["excluded"] = [_label(a) for a in off]

        singles = [a for a in on if _parse_opts(a).get('sequence_mode', 'single') != 'total']
        totals = [a for a in on if _parse_opts(a).get('sequence_mode', 'single') == 'total']

        overlap = float(trigger.output_duration or 0)
        slots = _build_slots(
            singles, lambda a: day_action_group(sched, day_idx, a.unique_id, _group_key(a)))

        try:
            base_min = time_to_minutes(entry.get('start') or '00:00')
        except ValueError:
            base_min = 0

        def _clock(seconds):
            total = int(base_min * 60 + seconds)
            return f"{(total // 3600) % 24:02d}:{(total % 3600) // 60:02d}"

        prev_end = span = 0.0
        for i, (gname, members) in enumerate(slots):
            rep = members[0]
            step = float(day_action_duration(
                sched, day_idx, rep.unique_id,
                float(_parse_opts(rep).get('action_duration', 0) or 0)))
            head = overlap if i > 0 else 0
            tail = overlap if i < len(slots) - 1 else 0
            start_t = max(0.0, prev_end - overlap) if i > 0 else 0.0
            end_t = start_t + head + step + tail
            prev_end = end_t
            span = max(span, end_t)
            out["slots"].append({
                "starts_at": _clock(start_t), "ends_at": _clock(end_t),
                "minutes": round((end_t - start_t) / 60, 1),
                "devices": [_label(a) for a in members],
                "simultaneous": len(members) > 1,
                "group": gname,
            })

        for a in totals:
            s, e = _total_window(_parse_opts(a), span or float(entry.get('period') or 0))
            out["slots"].append({
                "starts_at": _clock(s), "ends_at": _clock(e),
                "minutes": round((e - s) / 60, 1),
                "devices": [_label(a)], "simultaneous": False,
                "group": None, "spans_whole_cycle": True,
            })

        out["one_pass_seconds"] = span
        try:
            window_sec = (time_to_minutes(entry['end']) - time_to_minutes(entry['start'])) * 60
        except (KeyError, ValueError):
            window_sec = None
        period = float(entry.get('period') or 0)
        if not out["slots"]:
            out["warnings"].append("No step runs on this day — the window opens but nothing happens.")
        if window_sec is not None and span > window_sec:
            out["warnings"].append(
                f"One pass takes {span:.0f}s but the window is only {window_sec}s — "
                "it will be cut off before finishing.")
        if period and span > period:
            out["warnings"].append(
                f"One pass takes {span:.0f}s but the cycle restarts every {period:.0f}s — "
                "it will restart before finishing.")
        # Only a genuine repeat is worth flagging. The old guard (period <
        # window) fired even when the window fits exactly one pass, producing
        # "runs about 1 times that day, not once" — self-contradictory, and the
        # caller relays these warnings to the user verbatim.
        repeats = int(window_sec // period) if (window_sec and period) else 0
        out["runs_per_day"] = repeats or (1 if out["slots"] else 0)
        if repeats >= 2 and out["slots"]:
            out["warnings"].append(
                f"The cycle repeats every {period:.0f}s inside a {window_sec}s window, "
                f"so it runs about {repeats} times that day rather than once.")
        return out

    def initialize_variables(self):
        self.trigger = db_retrieve_table_daemon(Trigger, unique_id=self.unique_id)
        if not self.trigger:
            self.running = False
            return

        self.is_activated = self.trigger.is_activated

        # Honor the per-function debug log option: with it off the logger sits at
        # INFO and the demoted debug() operational logs are dropped; turning it on
        # records them.
        self.log_level_debug = self.trigger.log_level_debug
        self.set_log_level_debug(self.log_level_debug)

        # Resolve device timezone so window comparisons use the user's local clock,
        # not the server's UTC clock.  Falls back to UTC if coords/tz are missing.
        self.device_tz = str(get_device_tz(self.trigger))

        # Keep legacy fields for backward compat / static status fallback
        self.window_start_time = self.trigger.timer_start_time or "00:00"
        self.window_end_time = self.trigger.timer_end_time or "00:00"
        self.sequence_cycle_duration = float(self.trigger.period or 3600)
        self.action_overlap_duration = float(self.trigger.output_duration or 0)
        self.start_latency = float(self.trigger.timer_start_offset or 0)
        self.input_validity_duration = float(self.trigger.time_offset_minutes if self.trigger.time_offset_minutes is not None else 300)
        self.timer_weekday = getattr(self.trigger, 'timer_weekday', None) or ''

        # Weekly schedule: parse from timer_schedule JSON, fall back to legacy columns
        raw_schedule = getattr(self.trigger, 'timer_schedule', None)
        self.schedule = parse_schedule(raw_schedule) or from_legacy(
            self.trigger.timer_start_time,
            self.trigger.timer_end_time,
            getattr(self.trigger, 'timer_weekday', None),
            self.trigger.period or 3600,
        )
        # Track which day's window is currently active (for continuity detection)
        self.active_weekday = None
        
        self.dict_actions = parse_action_information()

        # Resume an in-progress cycle across a daemon restart (see
        # _load_runtime_state) instead of always starting fresh at elapsed=0.
        self._load_runtime_state()

        self.ready.set()
        self.running = True

    # ------------------------------------------------------------------ #
    # Runtime-state persistence (resume across daemon restart)
    # ------------------------------------------------------------------ #
    def _load_runtime_state(self):
        """Restore cycle_start_time / active_weekday / active_actions from
        FunctionRuntimeState so a daemon restart resumes the in-progress
        cycle instead of restarting it from elapsed=0 (which would otherwise
        re-issue ON downlinks for outputs that are already running and
        extend their total on-time). Only takes effect if run_finally()
        actually persisted state on the previous shutdown (see below) --
        an ungraceful kill (SIGKILL/crash) leaves no persisted state and
        this simply falls through to the normal fresh-cycle start.
        """
        try:
            with session_scope(AOT_DB_PATH) as sess:
                row = sess.query(FunctionRuntimeState).filter(
                    FunctionRuntimeState.function_id == self.unique_id).first()
                if row is None or not row.last_cycle_ts:
                    return
                ts = float(row.last_cycle_ts)
                active_vars = json.loads(row.active_vars_json or '{}')
                sess.expunge_all()

            # Don't resume a cycle whose scheduled window has already fully
            # elapsed while the daemon was down (e.g. down for days) --
            # starting fresh is the correct/expected behavior there.
            if (time.time() - ts) >= self.sequence_cycle_duration:
                self.logger.debug(
                    f"Sequence {self.unique_id}: persisted cycle from "
                    f"{ts} is stale (older than the cycle period) — starting fresh.")
                return

            self.cycle_start_time = ts
            self.active_weekday = active_vars.get('active_weekday')
            restored_actions = active_vars.get('active_actions') or []
            self.active_actions = set(restored_actions)

            # Rebuild the schedule for the resumed cycle directly (bypassing
            # start_new_cycle(), which would call stop_all_active() and undo
            # the very continuity we're restoring).
            self.build_cycle_schedule()

            # 복원한 믿음을 장치의 실제 상태와 맞춘다.
            self._resync_after_resume()

            self.logger.info(
                f"Sequence {self.unique_id}: resumed cycle from persisted state "
                f"(elapsed={time.time() - ts:.0f}s, {len(restored_actions)} "
                f"action(s) already active) — no re-dispatch on restart.")
        except Exception:
            self.logger.exception(
                f"Sequence {self.unique_id}: runtime state load failed — "
                "starting with a clean cycle.")

    def _save_runtime_state(self):
        """Persist cycle_start_time / active_weekday / active_actions so a
        later restart can resume via _load_runtime_state(). Called on every
        active_actions transition (see turn_on_action/turn_off_action) and
        as a final flush from run_finally() on a process-level stop."""
        try:
            with session_scope(AOT_DB_PATH) as sess:
                row = sess.query(FunctionRuntimeState).filter(
                    FunctionRuntimeState.function_id == self.unique_id).first()
                if row is None:
                    row = FunctionRuntimeState(function_id=self.unique_id)
                    sess.add(row)
                row.last_cycle_ts = float(self.cycle_start_time or 0.0)
                row.active_vars_json = json.dumps({
                    'active_weekday': self.active_weekday,
                    'active_actions': list(self.active_actions),
                })
                row.updated_at = time.time()
                sess.commit()
        except Exception:
            self.logger.exception(
                f"Sequence {self.unique_id}: runtime state save failed — "
                "a restart before the next successful save will start fresh.")

    def get_dynamic_duration(self, source_id):
        if not source_id:
            return None
        
        input_id = source_id
        measurement_id = None

        # Handle comma-separated IDs (InputID, MeasurementID)
        if ',' in source_id:
            parts = source_id.split(',')
            input_id = parts[0]
            if len(parts) > 1 and parts[1].strip():
                measurement_id = parts[1].strip()

        # Check Input
        inp = db_retrieve_table_daemon(Input, unique_id=input_id)
        if inp:
            found_val = None
            
            # Strategy: If specific measurement ID is provided, try that first and exclusively
            if measurement_id:
                val_tuple = get_last_measurement(input_id, measurement_id, max_age=int(self.input_validity_duration))
                if val_tuple and val_tuple[0] is not None and val_tuple[1] is not None:
                     try:
                         val = float(val_tuple[1])
                         age = time.time() - float(val_tuple[0])
                         found_val = abs(val)
                         self.logger.debug(f"Dynamic Duration ACCEPTED (Specific): {found_val} (Raw={val}, Age={age:.1f}s)")
                         return found_val
                     except Exception as e:
                         self.logger.error(f"Error parsing dynamic value tuple {val_tuple}: {e}")
            
            # --- Fallbacks if no measurement ID provided or lookup failed (only if no specific ID was requested?)
            # Actually, if the user requested a specific ID (measurement_id) and it failed, we probably shouldn't guess others.
            # But technically, if the ID was just garbage or old format, falling back *might* be okay, 
            # but in this case (Temperature vs Dewpoint), falling back is EXACTLY what caused the bug (finding the wrong one).
            
            if measurement_id:
                 self.logger.warning(f"Specific dynamic duration ID {measurement_id} yielded no value. Returning None.")
                 return None

            # ... below is for when NO specific measurement ID is provided (legacy or single-value inputs)
            
            # Strategy: Find valid measurement ID from InputChannels
            channels = db_retrieve_table_daemon(InputChannel).filter(InputChannel.input_id == input_id).all()
            meas_ids = [c.unique_id for c in channels]
            
            # Fallback 1: Use Input ID itself as measurement ID (common for single-value inputs)
            if not meas_ids:
                meas_ids.append(input_id)

            # Fallback 2: Check Input object attributes directly (in-memory updates)
            direct_value = None
            for attr in ('last_value', 'value', 'measurement'):
                if hasattr(inp, attr):
                    val = getattr(inp, attr)
                    if val is not None:
                        direct_value = val
                        break
            
            if direct_value is not None:
                 try:
                     final_val = abs(float(direct_value))
                     self.logger.debug(f"Dynamic Duration ACCEPTED (Direct): {final_val}")
                     return final_val
                 except Exception:
                     pass

            # Fallback 3: Check DeviceMeasurements table (for inputs without explicit channels)
            if not meas_ids or meas_ids == [input_id]: # Avoid duplicates if fallback 1 ran
                 if meas_ids == [input_id]: meas_ids = []
                 dev_meas = db_retrieve_table_daemon(DeviceMeasurements).filter(DeviceMeasurements.device_id == input_id).all()
                 for dm in dev_meas:
                     meas_ids.append(dm.unique_id)
            
            # Fallback 4: Use Input ID itself as measurement ID (last resort)
            if not meas_ids:
                meas_ids.append(input_id)

            for meas_id in meas_ids:
                # Pass max_age to let InfluxDB filter by time, matching controller_pid.py logic
                val_tuple = get_last_measurement(input_id, meas_id, max_age=int(self.input_validity_duration))

                if val_tuple and val_tuple[0] is not None and val_tuple[1] is not None:
                    try:
                        ts = float(val_tuple[0])
                        val = float(val_tuple[1])
                        
                        # Age check is sufficiently handled by get_last_measurement (InfluxDB query)
                        # but we can log it for info.
                        age = time.time() - ts
                        
                        found_val = abs(val)
                        self.logger.debug(f"Dynamic Duration ACCEPTED: {found_val} (Raw={val}, Age={age:.1f}s)")
                        return found_val
                    except Exception as e:
                        self.logger.error(f"Error parsing dynamic value tuple {val_tuple}: {e}")
            
            if found_val is None:
                 self.logger.warning(f"No valid measurements found for Input {input_id}")
                
        else:
             self.logger.warning(f"Input object {input_id} not found in DB")

        # Check PID
        pid_obj = db_retrieve_table_daemon(PID, unique_id=input_id)
        if pid_obj:
            if measurement_id:
                meas_ids = [measurement_id]
            else:
                dev_meas = db_retrieve_table_daemon(DeviceMeasurements).filter(DeviceMeasurements.device_id == input_id).all()
                meas_ids = [dm.unique_id for dm in dev_meas]

            for meas_id in meas_ids:
                val_tuple = get_last_measurement(input_id, meas_id, max_age=int(self.input_validity_duration))
                if val_tuple and val_tuple[0] is not None and val_tuple[1] is not None:
                    try:
                        val = float(val_tuple[1])
                        found_val = abs(val)
                        self.logger.debug(f"Dynamic Duration ACCEPTED (PID): {found_val}")
                        return found_val
                    except Exception as e:
                        self.logger.error(f"Error parsing dynamic value tuple {val_tuple}: {e}")

            self.logger.warning(f"No valid measurements found for PID {input_id}")
            return None

        # Check CustomController (Function) - Placeholder for future expansion
        func = db_retrieve_table_daemon(CustomController, unique_id=source_id)
        if func:
             pass

        return None

    def build_cycle_schedule(self):
        """Builds the schedule for the new cycle."""
        actions = db_retrieve_table_daemon(Actions).filter(Actions.function_id == self.unique_id).all()
        
        # Sort actions by GridStack position. Actions.position resolves the
        # drag-reorder key (gridstack_y) with legacy 'position' fallback, so
        # this stays in sync with the modal's visual order.
        try:
            actions = sorted(actions, key=lambda x: x.position)
        except Exception as e:
            self.logger.error(f"Error sorting actions: {e}")
            actions = sorted(actions, key=lambda x: x.id)
            
        self.all_actions_cache = actions

        # Filter Enabled Actions (per-day actions map overrides global flag)
        day_idx = self.active_weekday if self.active_weekday is not None else get_today_idx(self.device_tz)
        enabled_actions = []
        for a in actions:
            try:
                opts = json.loads(a.custom_options) if a.custom_options else {}
            except:
                opts = {}

            if day_action_enabled(self.schedule, day_idx, a.unique_id, opts.get('enabled', True)):
                 enabled_actions.append(a)
            else:
                 self.logger.debug(f"Action {a.unique_id} skipped (Disabled for day {day_idx})")

        schedule = []
        
        # Split actions
        single_actions = [a for a in enabled_actions if (json.loads(a.custom_options).get('sequence_mode', 'single') if a.custom_options else 'single') != 'total']
        total_actions = [a for a in enabled_actions if (json.loads(a.custom_options).get('sequence_mode', 'single') if a.custom_options else 'single') == 'total']
        
        # 1. Process Single Actions to determine total sequence time.
        #    Grouped actions (shared group_name) collapse into one slot so they
        #    fire simultaneously with a single common duration. Group membership
        #    and duration honor per-weekday overrides for the active day.
        prev_end_time = 0.0
        max_end_time = 0.0

        def _group_of(a):
            return day_action_group(self.schedule, day_idx, a.unique_id, _group_key(a))
        def _dur_of(a):
            return day_action_duration(self.schedule, day_idx, a.unique_id,
                                       float(_parse_opts(a).get('action_duration', 0)))

        slots = _build_slots(single_actions, _group_of)
        count = len(slots)
        overlap = self.action_overlap_duration

        for i, (gname, members) in enumerate(slots):
            # A group's duration is common: use the representative (first-seen,
            # lowest-position member) for the slot's base/dynamic duration.
            rep = members[0]
            opts = _parse_opts(rep)

            base_duration = float(_dur_of(rep))
            dyn_source = opts.get('action_duration_id')

            # Step Time (Base Duration)
            step_time = base_duration

            if dyn_source:
                dyn_val = self.get_dynamic_duration(dyn_source)
                self.logger.debug(f"Action {rep.unique_id} Dynamic Source {dyn_source} -> {dyn_val}")
                if dyn_val is not None and dyn_val > 0:
                    step_time = dyn_val
                else:
                    self.logger.debug(f"Action {rep.unique_id} Dynamic Value invalid/none, using base: {base_duration}")

            # [Logic Update] Determine Overlaps based on position (Head/Tail)
            head_overlap = overlap if i > 0 else 0
            tail_overlap = overlap if i < count - 1 else 0

            # Total active duration = Head + Base + Tail
            total_on_duration = head_overlap + step_time + tail_overlap

            # Start Time
            if i == 0:
                start_t = 0.0
            else:
                # Start 'overlap' seconds before the previous one ends
                # This naturally handles the head overlap extension alignment
                start_t = prev_end_time - overlap

            if start_t < 0: start_t = 0.0

            end_t = start_t + total_on_duration

            self.logger.debug(f"Schedule: slot={gname or rep.unique_id} members={len(members)} start={start_t:.1f} end={end_t:.1f} step={step_time} head={head_overlap} tail={tail_overlap}")

            # Update previous end time for next iteration
            prev_end_time = end_t

            if end_t > max_end_time:
                max_end_time = end_t

            # Every member of the slot shares the same on/off window.
            for action in members:
                schedule.append({
                        'action': action,
                        'start': start_t,
                        'end': end_t,
                        'is_output': 'output' in action.action_type,
                        'type': 'single',
                        'group_name': gname
                    })

        # Total Sequence Duration derived from Single actions
        total_mode_duration = max_end_time
        if total_mode_duration == 0:
             # If no single actions, maybe fallback to period? 
             # Or 0? User said "Sum of all single operation times" (actually meant "Span of sequence").
             # If no single actions, this mode is useless or just runs for period?
             # Let's fallback to period if 0, to avoid breaking pure 'total' setups.
             total_mode_duration = self.sequence_cycle_duration

        # 2. Add Total Actions
        for action in total_actions:
             start_t, end_t = _total_window(
                 _parse_opts(action), total_mode_duration,
                 self.logger, action.unique_id)
             schedule.append({
                    'action': action,
                    'start': start_t,
                    'end': end_t,
                    'is_output': 'output' in action.action_type,
                    'type': 'total'
                })
            
        self.current_schedule = schedule

    def loop(self):
        last_log_time = 0
        was_activated = self.is_activated
        
        while self.running:
            if not self.is_activated:
                if was_activated:
                     self.logger.debug(f"Sequence {self.unique_id} DEACTIVATED. Stopping all actions.")
                     self.stop_all_active()
                     was_activated = False
                     self.activation_timestamp = 0

                if time.time() - last_log_time > 10:
                    self.logger.debug(f"Sequence {self.unique_id} loop running but NOT ACTIVATED.")
                    last_log_time = time.time()
                time.sleep(1.0)
                continue
            
            if not was_activated:
                self.logger.debug(f"Sequence {self.unique_id} ACTIVATED. Latency={self.start_latency}s")
                was_activated = True
                self.activation_timestamp = time.time()

            now = time.time()
            
            # Check Start Latency
            if self.start_latency > 0:
                 elapsed_latency = now - self.activation_timestamp
                 if elapsed_latency < self.start_latency:
                     if time.time() - last_log_time > 5:
                         self.logger.debug(f"Waiting for latency... {self.start_latency - elapsed_latency:.1f}s remaining. (Lat={self.start_latency}, Elapsed={elapsed_latency:.1f})")
                         last_log_time = time.time()
                     time.sleep(1.0)
                     continue
            
            # Check schedule: weekday + time window in one call (device-local timezone)
            active = active_entry_now(self.schedule, self.device_tz)

            if time.time() - last_log_time > 300:
                try:
                    _tz_obj = pytz.timezone(self.device_tz) if self.device_tz else pytz.utc
                    _local_str = datetime.now(_tz_obj).strftime('%a %H:%M')
                except Exception:
                    _local_str = utc_now().strftime('%H:%M')
                self.logger.debug(
                    f"Schedule check: active={active is not None}, local={_local_str}, tz={self.device_tz}"
                )
                last_log_time = time.time()

            if not active:
                # 자연 종료가 코앞이면 잠깐 기다린다 — 여기서 바로 끄면 드라이버가
                # 남길 개방 시간 기록을 빼앗는다.
                if self._within_close_grace(now):
                    time.sleep(0.2)
                    continue
                self._close_grace_started = None
                if time.time() - last_log_time > 60:
                    self.logger.debug(f"Sequence {self.unique_id}: outside scheduled window.")
                    last_log_time = time.time()
                self.cycle_start_time = None
                self.active_weekday = None
                self.stop_all_active(reason='예정 시간대(창)가 닫혔습니다')
                time.sleep(1.0)
                continue

            current_day, current_entry = active
            self._close_grace_started = None

            # Detect day transition
            if self.active_weekday is not None and self.active_weekday != current_day:
                if is_continuity_boundary(self.schedule, self.active_weekday, current_day):
                    # Continuity: keep cycle running, just update the day tracker
                    self.logger.debug(
                        f"Continuity boundary: day {self.active_weekday} -> {current_day}, cycle preserved."
                    )
                    self.active_weekday = current_day
                    # New cycles from here will use current_entry's period (set in start_new_cycle)
                else:
                    # Non-continuity day change: reset cycle
                    self.logger.debug(
                        f"Day changed {self.active_weekday} -> {current_day} (no continuity): resetting cycle."
                    )
                    self.active_weekday = current_day
                    self.cycle_start_time = None
                    self.stop_all_active()
            else:
                self.active_weekday = current_day

            # Inside Window
            period = self._entry_period(current_entry)
            next_start = self._next_cycle_start(current_entry, now, period)
            if next_start is not None:
                self.logger.debug(
                    f"Starting new cycle. now={now}, cycle_start={self.cycle_start_time}, "
                    f"grid_start={next_start}, limit={period}")
                self.start_new_cycle(next_start, period=period)
            
            self.process_cycle(now)
            
            time.sleep(0.1)

    # OFF 재시도 정책 (turn_off_action). 루프가 0.1초마다 도므로 간격 없이
    # 재시도하면 장치를 두들기게 된다.
    OFF_RETRY_INTERVAL_SEC = 5.0
    OFF_MAX_ATTEMPTS = 5

    # 창이 닫혔을 때 자연 종료를 기다려 주는 시간 (_within_close_grace).
    WINDOW_CLOSE_GRACE_SEC = 5.0

    def _entry_period(self, entry):
        """이 요일 항목의 사이클 주기. 0/None 은 신뢰하지 않고 컨트롤러 값으로."""
        try:
            period = float((entry or {}).get('period') or 0)
        except (TypeError, ValueError):
            period = 0.0
        return period if period > 0 else float(self.sequence_cycle_duration or 3600)

    def _next_cycle_start(self, entry, now, period):
        """새 사이클을 시작해야 하면 그 **격자 위 시작 시각**을, 아니면 None.

        기준점을 `now` 로 잡지 않는 것이 요점이다. 스텝 전환마다 붙는 지연
        (원격 출력은 동기 HTTP 라 왕복이 0.2초일 수도 60초일 수도 있다)이
        `= now` 에서는 그대로 다음 기준점에 상속돼 영구 누적되고, 그 누적량이
        매번 달라 "설정한 시각과 다르게 들쭉날쭉" 이 된다. 여기서는

          - 첫 사이클: 창 시작 앵커에서 `now` 이전 최근 격자점
          - 이후: 직전 기준점에 `+= period` (지연이 길면 건너뛰되 격자는 유지)

        로 잡는다. 타이머 트리거가 `+= period` / `epoch_of_next_time` 으로
        격자를 지키는 것과 같은 방식이며, 그래서 같은 원격 출력을 써도 타이머만
        시각이 맞았다.
        """
        if self.cycle_start_time is None:
            anchor = window_start_epoch(entry, self.device_tz, now)
            if anchor is None or anchor > now:
                # 창 시작을 계산할 수 없거나(스키마 손상) 아직 이르면 지금부터.
                return now
            # 앵커에서 now 를 넘지 않는 마지막 격자점.
            return self._reject_runt(entry, anchor + (int((now - anchor) // period) * period), now)

        if now - self.cycle_start_time >= period:
            start = self.cycle_start_time
            skipped = 0
            while start + period <= now:
                start += period
                skipped += 1
            if skipped > 1:
                # 격자는 지켰지만 사이클을 통째로 건너뛴 것은 조용히 넘기면 안 된다.
                self.logger.error(
                    f"Sequence {self.unique_id}: {skipped - 1} cycle(s) skipped — "
                    f"a step transition took longer than one period ({period:.0f}s).")
            return self._reject_runt(entry, start, now)

        return None

    def _within_close_grace(self, now):
        """창이 닫혔지만 진행 중 스텝이 **자연 종료를 코앞에 둔** 경우 True.

        창 길이와 한 pass 가 딱 맞아떨어지는 설정 — 문서가 권하는 기본형이다 —
        에서는 마지막 스텝의 duration 만료와 창 종료가 같은 순간에 온다. 창
        판정이 먼저 이기면 드라이버가 스스로 끝내기 전에 바깥에서 OFF 가 들어가고,
        그 세션의 **개방 시간이 기록되지 않는다**. 실측(2026-08-27): 창 07:30 에
        걸린 v12 와 펌프는 ON 마커만 남고 duration 없이 사라진 반면, 06:30 에
        창 안에서 끝난 v11 은 3600.09초로 남았다.

        몇 초만 기다리면 드라이버가 정상 종료하며 기록을 남긴다. 기다리는 것은
        자연 종료가 임박한 경우뿐이고, 유예를 넘기면 기다리지 않는다 —
        밸브를 열어 둔 채로 두는 쪽이 기록을 잃는 것보다 나쁘다.
        """
        if not self.active_actions or self.cycle_start_time is None:
            return False

        elapsed = now - self.cycle_start_time
        pending = [i for i in self.current_schedule
                   if i['action'].unique_id in self.active_actions]
        if not pending:
            return False

        # 아직 한참 남은 스텝이 있으면 그것은 자연 종료가 아니라 진짜 절단이다.
        # 기다려 봐야 창만 넘긴다.
        try:
            if any(float(i['end']) - elapsed > self.WINDOW_CLOSE_GRACE_SEC
                   for i in pending):
                return False
        except (TypeError, ValueError, KeyError):
            return False

        if self._close_grace_started is None:
            self._close_grace_started = now
            return True
        return (now - self._close_grace_started) < self.WINDOW_CLOSE_GRACE_SEC

    def _one_pass_seconds(self):
        """직전에 세운 계획에서 한 pass 가 걸리는 시간."""
        try:
            schedule = getattr(self, 'current_schedule', None) or []
            return max((float(i['end']) for i in schedule), default=0.0)
        except (TypeError, ValueError, KeyError):
            return 0.0

    def _reject_runt(self, entry, start, now):
        """남은 창이 한 pass 를 못 담으면 그 사이클을 아예 시작하지 않는다.

        `창 길이 % 주기` 가 0 이 아니면 창 끝에 반드시 짧은 사이클이 생긴다.
        그때 밸브는 열리자마자 창이 닫혀 강제로 끊기고, 그렇게 끊긴 스텝은
        개방 시간이 기록되지 않아 흔적조차 남지 않는다. 물을 주다 만 것도
        문제지만, 준 적 없다고 보이는 쪽이 더 위험하다.

        한 pass 길이를 모르면(첫 사이클이라 계획이 아직 없음) 판단하지 않고
        그대로 진행한다 — 모른다고 멈추는 것이 더 나쁘다.
        """
        one_pass = self._one_pass_seconds()
        if not one_pass:
            return start
        _, win_end = window_bounds_epoch(entry, self.device_tz, now)
        if win_end is None or start + one_pass <= win_end:
            return start
        self.logger.error(
            f"Sequence {self.unique_id}: 남은 창이 한 번 돌기에 부족해 "
            f"({win_end - start:.0f}초 남음 / {one_pass:.0f}초 필요) "
            "이번 사이클은 건너뜁니다.")
        return None

    def start_new_cycle(self, now, period=None):
        if period is not None:
            self.sequence_cycle_duration = period
        self.cycle_start_time = now
        self.stop_all_active()
        self.build_cycle_schedule()
        self.logger.debug(f"Started new cycle at {now}. Schedule has {len(self.current_schedule)} items.")
        for i, item in enumerate(self.current_schedule):
             self.logger.debug(f" - Item {i}: Action {item['action'].unique_id} [{item['start']} ~ {item['end']}]")


    def _off_order(self, action_ids):
        """Order ids for shutdown: 'total' steps first, then the rest.

        active_actions is a set, so iterating it directly gave an arbitrary
        (hash-dependent) shutdown order -- the pump could be switched off
        before or after the valves it feeds, differing run to run. Stopping
        total steps first drains the line pressure before any valve closes.
        Returns a plain list, safe to iterate while the set is mutated.
        """
        type_of = {item['action'].unique_id: item.get('type')
                   for item in self.current_schedule}
        return sorted(action_ids, key=lambda a: 0 if type_of.get(a) == 'total' else 1)

    def process_cycle(self, now):
        elapsed = now - self.cycle_start_time
        
        desired_active = set()
        
        for item in self.current_schedule:
            if item['start'] <= elapsed < item['end']:
                desired_active.add(item['action'].unique_id)
                # ensure ON
                if item['action'].unique_id not in self.active_actions:
                    self.logger.debug(f"Desired matched: Action {item['action'].unique_id} at elapsed {elapsed}")
                    self.turn_on_action(item['action'], item)
        
        # Turn OFF things that shouldn't be active
        # Create a copy to iterate because we modify the set
        current_active_ids = self._off_order(self.active_actions)
        for act_id in current_active_ids:
            if act_id not in desired_active:
                # Need action object to turn off
                # Find in schedule (or cache)
                # item can be found by ID
                found_item = next((i for i in self.current_schedule if i['action'].unique_id == act_id), None)
                if found_item:
                    self.turn_off_action(found_item['action'], found_item)
                else:
                    # Zombie action? just remove from set
                    self.active_actions.discard(act_id)

    def turn_on_action(self, action, item):
        self.logger.debug(f"Action ON: {action.unique_id}")
        duration = item['end'] - item['start']
        # 출처를 밝히고 명령한다. 안 심으면 `resolve_origin()` 이 판정을 전부
        # 흘려보내 'unknown' 으로 남는다 — 행위자도 IP 도 없는 감사 기록은
        # 정상적인 시퀀스 동작과 진짜 인증 우회를 구별하지 못하게 만든다.
        set_execution_context(source_type=SOURCE_SEQUENCE, source_id=self.unique_id)
        try:
            trigger_action(self.dict_actions, action.unique_id, value={
                'message': f"Sequence {self.unique_id}: ",
                'duration': duration
            })
        finally:
            # 스레드는 재사용된다. 안 지우면 다음 명령이 이 출처를 뒤집어쓴다.
            clear_execution_context()
        self.active_actions.add(action.unique_id)
        self._save_runtime_state()

    def _resolve_output_target(self, action):
        """스텝이 가리키는 `(출력 unique_id, 채널 index)`. 못 구하면 None."""
        target_id = action.do_unique_id
        if not target_id and action.custom_options:
            try:
                target_id = json.loads(action.custom_options).get('output', None)
            except Exception:
                pass
        if not target_id:
            return None

        out_id = target_id
        channel_index = 0
        if ',' in str(target_id):
            parts = str(target_id).split(',')
            out_id = parts[0]
            if len(parts) > 1:
                raw_chan = parts[1]
                try:
                    channel_index = int(raw_chan)
                except (TypeError, ValueError):
                    try:
                        resolved = self.get_output_channel_from_channel_id(raw_chan)
                        if resolved is not None:
                            channel_index = resolved
                        else:
                            self.logger.warning(
                                f"Could not resolve channel index from UUID {raw_chan}")
                    except Exception as e:
                        self.logger.error(f"Error resolving channel: {e}")
        return out_id, channel_index

    def _resync_after_resume(self):
        """재개 직후, 켜져 있다고 복원한 스텝이 **실제로도** 켜져 있는지 맞춘다.

        데몬이 내려갈 때 출력의 `state_shutdown` 이 OFF 면 장치는 꺼진 채로
        올라온다. 그런데 재개는 "이미 돌고 있다" 고 보고 재전송을 하지 않으므로,
        컨트롤러의 믿음과 장치의 실제가 어긋난 채 그 사이클의 남은 시간이 통째로
        사라진다 — 관수라면 그날 물을 덜 준 것이고, 개방 시간 기록도 남지 않아
        아무도 모른다. 실측(2026-08-28): 재시작 시점에 52분째 열려 있던 밸브가
        꺼진 채 올라왔고, 남은 8분은 그대로 증발했다.

        다시 켤 때는 **남은 시간만큼만** 켠다. 원래 지속시간으로 켜면 재시작할
        때마다 그 스텝의 총 개방시간이 늘어난다.

        상태를 못 읽으면(통신 오류) 건드리지 않는다 — 모르는 채로 켜면 이미 열린
        밸브를 연장하게 되고, 그쪽이 더 나쁘다.
        """
        if not self.active_actions or self.cycle_start_time is None:
            return
        elapsed = time.time() - self.cycle_start_time

        for act_id in list(self.active_actions):
            item = next((i for i in self.current_schedule
                         if i['action'].unique_id == act_id), None)
            if item is None or not item.get('is_output'):
                continue

            remaining = float(item['end']) - elapsed
            if remaining <= 0:
                # 데몬이 내려가 있는 사이에 이 스텝의 시간이 다 지났다.
                self.active_actions.discard(act_id)
                continue

            target = self._resolve_output_target(item['action'])
            if not target:
                continue
            out_id, channel_index = target

            try:
                state = self.control.output_state(out_id, channel_index)
            except Exception as err:
                self.logger.error(f"Action {act_id}: 재개 상태 조회 실패 — {err}")
                continue
            if state != 'off':
                continue        # 켜져 있거나 알 수 없다 — 그대로 둔다

            self.logger.error(
                f"Action {act_id}: 재개했으나 출력이 꺼져 있습니다"
                f"(종료 시 state_shutdown 으로 내려간 것으로 보입니다). "
                f"남은 {remaining:.0f}초만큼 다시 켭니다.")
            set_execution_context(source_type=SOURCE_SEQUENCE, source_id=self.unique_id)
            try:
                self.control.output_on(
                    out_id, output_type='sec', amount=remaining,
                    output_channel=channel_index)
            except Exception as err:
                self.logger.error(f"Action {act_id}: 재개 재전송 실패 — {err}")
            finally:
                clear_execution_context()

    def _dispatch_off(self, action, item):
        """실제 OFF 명령을 보내고 **성공했는지** 돌려준다.

        `DaemonControl.output_off` 는 `(code, msg)` 를 준다 — code 1 이 실패이고,
        Pyro5 타임아웃·통신오류도 예외가 아니라 `(1, msg)` 로 돌아온다. 예전에는
        이 반환값을 통째로 버려서, 명령이 나가지 못한 경우에도 호출자가 성공으로
        읽었다.
        """
        if not item.get('is_output'):
            return True

        target = self._resolve_output_target(action)
        if not target:
            # 재시도해도 대상이 생기지 않는다. 되풀이 대신 한 번 크게 남긴다 —
            # 이 경우 출력은 켜진 채로 남아 있을 수 있다.
            self.logger.error(
                f"Action {action.unique_id}: 출력 스텝인데 대상 ID 가 없어 OFF 를 "
                "보내지 못했습니다. 해당 출력이 켜진 채 남아 있을 수 있습니다 — "
                "스텝의 출력 지정을 확인하십시오.")
            return False
        out_id, channel_index = target

        set_execution_context(source_type=SOURCE_SEQUENCE, source_id=self.unique_id)
        try:
            ret = self.control.output_off(out_id, output_channel=channel_index)
        except Exception as err:
            self.logger.error(f"Action {action.unique_id}: OFF 전송 실패 — {err}")
            return False
        finally:
            clear_execution_context()

        # (code, msg): code 0 만 성공. 튜플이 아닌 구현은 성공으로 본다.
        if isinstance(ret, (tuple, list)) and ret and ret[0]:
            self.logger.error(
                f"Action {action.unique_id}: OFF 가 거부되었습니다 — {ret[1] if len(ret) > 1 else ret[0]}")
            return False
        return True

    def turn_off_action(self, action, item):
        """OFF 를 보내고, **성공했을 때만** active 에서 뺀다.

        예전에는 결과와 무관하게 `active_actions.remove()` 를 해서, 명령이 나가지
        못했는데도 컨트롤러는 "껐다" 고 간주했다. 그러면 밸브가 열린 채 남고
        아무도 그것을 모른다. 실패하면 active 로 남겨 다음 주기에 다시 시도한다.

        무한 재시도는 하지 않는다. `process_cycle` 은 0.1초마다 도는데 실패할
        때마다 명령을 쏘면 그 자체가 장치를 두들기는 꼴이라, 재시도는
        `OFF_RETRY_INTERVAL_SEC` 간격으로만 하고 `OFF_MAX_ATTEMPTS` 회에서 멈춘다.
        멈출 때는 조용히 지우지 않고 ERROR 를 남긴다.
        """
        self.logger.debug(f"Action OFF: {action.unique_id}")
        if not hasattr(self, '_off_failures'):
            self._off_failures = {}

        aid = action.unique_id
        fail = self._off_failures.get(aid)
        if fail and (time.time() - fail['last']) < self.OFF_RETRY_INTERVAL_SEC:
            return False       # 백오프 중 — 이번 턴은 건너뛴다

        if self._dispatch_off(action, item):
            self._off_failures.pop(aid, None)
            self.active_actions.discard(aid)
            self._save_runtime_state()
            return True

        attempts = (fail['count'] if fail else 0) + 1
        self._off_failures[aid] = {'count': attempts, 'last': time.time()}
        if attempts >= self.OFF_MAX_ATTEMPTS:
            self.logger.error(
                f"Action {aid}: OFF 를 {attempts}회 시도했으나 모두 실패했습니다. "
                "재시도를 멈춥니다 — 이 출력은 켜진 채 남아 있을 수 있으니 "
                "직접 확인하십시오.")
            self._off_failures.pop(aid, None)
            self.active_actions.discard(aid)
            self._save_runtime_state()
            return False

        self.logger.error(
            f"Action {aid}: OFF 실패({attempts}/{self.OFF_MAX_ATTEMPTS}) — "
            f"{self.OFF_RETRY_INTERVAL_SEC:.0f}초 뒤 다시 시도합니다.")
        return False

    def stop_all_active(self, reason=''):
        """진행 중인 것을 전부 끈다(펌프 먼저 — `_off_order` 참조).

        창이 닫혀서 부를 때는 **아직 끝나지 않은 스텝을 중간에 끊는 것**이다.
        그 사실을 남기지 않으면 아무 기록도 없이 사라진다 — 실제로 창 끝에
        걸린 스텝은 duration 이 기록되지 않아, 얼마나 열려 있었는지가 통째로
        유실된다.
        """
        if self.active_actions and reason:
            self.logger.error(
                f"Sequence {self.unique_id}: {reason} — 진행 중이던 스텝 "
                f"{len(self.active_actions)}개를 중간에 끊습니다. 이 스텝들의 "
                "개방 시간은 기록되지 않습니다.")
        for act_id in self._off_order(self.active_actions):
            # Find action info 
            found_item = next((i for i in self.current_schedule if i['action'].unique_id == act_id), None)
            
            if found_item:
                self.turn_off_action(found_item['action'], found_item)
            else:
                # If not in schedule, we still need to turn it off if it's an output
                # Try to retrieve from DB to know if it's output
                try:
                    action = db_retrieve_table_daemon(Actions, unique_id=act_id)
                    if action and 'output' in action.action_type:
                        # Construct a fake item to pass to turn_off_action
                        fake_item = {'is_output': True}
                        self.turn_off_action(action, fake_item)
                    else:
                        self.active_actions.discard(act_id)
                except Exception:
                     self.logger.warning(f"Could not retrieve action {act_id} for force stop. Removing from active set.")
                     self.active_actions.discard(act_id)

    def run_finally(self):
        # Distinguish a process-level stop (daemon restart, e.g. `systemctl
        # restart aot`) from a genuine deactivation of this trigger. Both
        # reach here via stop_controller(), but controller_deactivate() sets
        # Trigger.is_activated=False in the DB *before* calling
        # stop_controller() -- a daemon-wide restart never touches that flag.
        # On a genuine deactivation we still force everything off (unchanged
        # behavior); on a bare restart we persist the in-progress cycle and
        # deliberately leave outputs as-is so resuming doesn't interrupt
        # already-running irrigation with a needless OFF-then-ON.
        try:
            db_trigger = db_retrieve_table_daemon(Trigger, unique_id=self.unique_id)
            still_activated = bool(db_trigger and db_trigger.is_activated)
        except Exception:
            still_activated = False  # uncertain -> safe default: force off

        if still_activated and self.cycle_start_time is not None:
            self._save_runtime_state()
            self.logger.info(
                f"Sequence {self.unique_id}: process stopping while still "
                "activated -- state persisted for resume, outputs left running.")
        else:
            self.stop_all_active()


    def refresh_settings(self):
        # Preserve the cycle start timestamp so the current cycle isn't disrupted.
        # After reload, re-derive sequence_cycle_duration from the active schedule
        # entry (not from trigger.period, which may differ in per_day mode) so that
        # period changes take effect for the current and next cycle.
        saved_cycle_start = self.cycle_start_time
        self.initialize_variables()
        if saved_cycle_start is not None:
            self.cycle_start_time = saved_cycle_start
            active = active_entry_now(self.schedule, self.device_tz)
            if active:
                _, entry = active
                self.sequence_cycle_duration = float(entry.get('period', self.sequence_cycle_duration))
        # Reload action cache so function_status() immediately reflects any
        # position changes saved by function_save_order (drag-drop reorder).
        try:
            actions = db_retrieve_table_daemon(Actions).filter(
                Actions.function_id == self.unique_id).all()
            actions = sorted(actions, key=lambda x: x.position)
            self.all_actions_cache = actions
        except Exception as e:
            self.logger.warning(f"refresh_settings: could not reload action cache: {e}")
        # Reset active_weekday so next loop re-evaluates the current window
        self.active_weekday = None
        return "Sequence settings refreshed"

