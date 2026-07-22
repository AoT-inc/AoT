import logging
import time
import json
import threading
from datetime import datetime

import pytz

from aot.utils.time_utils import utc_now


from aot.aot_client import DaemonControl
from aot.controllers.base_controller import AbstractController
from aot.databases.models import Trigger, Actions, Input, CustomController, InputChannel, DeviceMeasurements, Output, OutputChannel, Misc, SMTP, PID
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.actions import parse_action_information, trigger_controller_actions, trigger_action
from aot.utils.system_pi import time_between_range
from aot.utils.influx import get_last_measurement
from aot.utils.device_tz import get_device_tz
from aot.utils.weekly_schedule import (
    active_entry_now, day_action_enabled, day_action_group, day_action_duration,
    from_legacy, is_continuity_boundary, get_today_idx, parse_schedule, to_legacy
)

logger = logging.getLogger(__name__)


def _resolve_device_detail(target_id):
    """Resolve a target_id (output/input/function UUID, optionally with channel) to a human-readable string."""
    if not target_id:
        return "-"
    try:
        parts = str(target_id).split(',')
        main_id = parts[0]
        raw_chan = parts[1] if len(parts) > 1 else None

        out = db_retrieve_table_daemon(Output, unique_id=main_id)
        if out:
            detail = out.name
            if raw_chan:
                try:
                    chan_obj = db_retrieve_table_daemon(OutputChannel, unique_id=raw_chan)
                    if chan_obj:
                        detail += f" [CH{chan_obj.channel}]"
                    elif len(str(raw_chan)) <= 5:
                        detail += f" [CH{raw_chan}]"
                except Exception:
                    if len(str(raw_chan)) <= 5:
                        detail += f" [CH{raw_chan}]"
            return detail

        inp = db_retrieve_table_daemon(Input, unique_id=main_id)
        if inp:
            return f"{inp.name} [Input]"

        func = db_retrieve_table_daemon(CustomController, unique_id=main_id)
        if func:
            return f"{func.name} [Func]"

        return "-"
    except Exception as e:
        logger.error(f"Error resolving device detail for {target_id}: {e}")
        return "-"


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
            device_detail = _resolve_device_detail(target_id)

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
        
        self.ready.set()
        self.running = True

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
             schedule.append({
                    'action': action,
                    'start': 0.0,
                    'end': total_mode_duration,
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
                if time.time() - last_log_time > 60:
                    self.logger.debug(f"Sequence {self.unique_id}: outside scheduled window.")
                    last_log_time = time.time()
                self.cycle_start_time = None
                self.active_weekday = None
                self.stop_all_active()
                time.sleep(1.0)
                continue

            current_day, current_entry = active

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
            if self.cycle_start_time is None or (now - self.cycle_start_time >= self.sequence_cycle_duration):
                self.logger.debug(f"Starting new cycle. now={now}, cycle_start={self.cycle_start_time}, limit={self.sequence_cycle_duration}")
                self.start_new_cycle(now, period=float(current_entry.get('period', self.sequence_cycle_duration)))
            
            self.process_cycle(now)
            
            time.sleep(0.1)

    def start_new_cycle(self, now, period=None):
        if period is not None:
            self.sequence_cycle_duration = period
        self.cycle_start_time = now
        self.stop_all_active()
        self.build_cycle_schedule()
        self.logger.debug(f"Started new cycle at {now}. Schedule has {len(self.current_schedule)} items.")
        for i, item in enumerate(self.current_schedule):
             self.logger.debug(f" - Item {i}: Action {item['action'].unique_id} [{item['start']} ~ {item['end']}]")


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
        current_active_ids = list(self.active_actions)
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
                    self.active_actions.remove(act_id)

    def turn_on_action(self, action, item):
        self.logger.debug(f"Action ON: {action.unique_id}")
        duration = item['end'] - item['start']
        trigger_action(self.dict_actions, action.unique_id, value={
            'message': f"Sequence {self.unique_id}: ",
            'duration': duration
        })
        self.active_actions.add(action.unique_id)

    def turn_off_action(self, action, item):
        self.logger.debug(f"Action OFF: {action.unique_id}")
        if item['is_output']:
            target_id = action.do_unique_id
            if not target_id and action.custom_options:
                 try:
                     opts = json.loads(action.custom_options)
                     target_id = opts.get('output', None)
                 except Exception:
                     pass
            
            if target_id:
                out_id = target_id
                channel_index = 0
                
                if ',' in str(target_id):
                    parts = str(target_id).split(',')
                    out_id = parts[0]
                    if len(parts) > 1:
                        raw_chan = parts[1]
                        try:
                            # Check if it's already an integer index
                            channel_index = int(raw_chan)
                        except:
                            # Assume it's a UUID and try to resolve
                            try:
                                resolved = self.get_output_channel_from_channel_id(raw_chan)
                                if resolved is not None:
                                    channel_index = resolved
                                else:
                                    self.logger.warning(f"Could not resolve channel index from UUID {raw_chan}")
                            except Exception as e:
                                self.logger.error(f"Error resolving channel: {e}")

                self.control.output_off(out_id, output_channel=channel_index)
            else:
                 self.logger.warning(f"Action {action.unique_id} marked as output but no target ID found for OFF.")
                 
        self.active_actions.remove(action.unique_id)

    def stop_all_active(self):
        # Force stop all
        # Create list copy to avoid modification during iteration
        for act_id in list(self.active_actions):
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
                        self.active_actions.remove(act_id)
                except:
                     self.logger.warning(f"Could not retrieve action {act_id} for force stop. Removing from active set.")
                     self.active_actions.remove(act_id)

    def run_finally(self):
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

