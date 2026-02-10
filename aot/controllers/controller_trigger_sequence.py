import logging
import time
import json
import threading
from datetime import datetime

from aot.aot_client import DaemonControl
from aot.controllers.base_controller import AbstractController
from aot.databases.models import Trigger, Actions, Input, CustomController, InputChannel, DeviceMeasurements, Output, OutputChannel, Misc, SMTP
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.actions import parse_action_information, trigger_controller_actions, trigger_action
from aot.utils.system_pi import time_between_range
from aot.utils.influx import get_last_measurement

logger = logging.getLogger(__name__)

# ... (inside class, method function_status)

class SequenceTriggerController(AbstractController, threading.Thread):

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
            elif not time_between_range(self.window_start_time, self.window_end_time):
                 status_text = "Outside Window"
            elif cycle_start:
                 status_text = "Running"
            else:
                 status_text = "Activated"

        if not hasattr(self, 'all_actions_cache'):
             return {'is_activated': self.is_activated, 'status_text': 'Initializing'}
             
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
             # Format: Name [Channel, Type, ID]
             device_detail = ""
             target_id = act.do_unique_id
             if not target_id:
                 target_id = opts.get('output', None)
             if not target_id:
                 target_id = opts.get('input', None)

             # DEBUG LOGGING (Temporary)
             self.logger.info(f"[SEQ DEBUG] Act: {act.unique_id}, Type: {act.do_unique_id}, Opts: {opts}, Target: {target_id}")
             
             if target_id:
                 try:
                     parts = str(target_id).split(',')
                     main_id = parts[0]
                     raw_chan = parts[1] if len(parts) > 1 else "0"
                     
                     # Check Output
                     out = db_retrieve_table_daemon(Output, unique_id=main_id)
                     if out:
                         chan_idx = raw_chan
                         # Try to resolve channel if it looks like UUID
                         if len(raw_chan) > 10: 
                             chan_obj = db_retrieve_table_daemon(OutputChannel, unique_id=raw_chan)
                             if chan_obj:
                                 chan_idx = chan_obj.channel
                         
                         device_detail = f"{out.name} [CH{chan_idx}]"
                     else:
                         # Check Input
                         inp = db_retrieve_table_daemon(Input, unique_id=main_id)
                         if inp:
                             device_detail = f"{inp.name} [Input]"
                         else:
                             # Check Function
                             func = db_retrieve_table_daemon(CustomController, unique_id=main_id)
                             if func:
                                  device_detail = f"{func.name} [Func]"
                             else:
                                  device_detail = f"Unknown ID: {main_id}"
                 except Exception as e:
                     self.logger.error(f"Error resolving device detail for action {act.unique_id}: {e}")
                     device_detail = f"Error: {target_id}"
             else:
                 device_detail = "-"

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
                 'is_active': act.unique_id in self.active_actions
             })
             
        # DEBUG: To trace "Active: false" issues
        if len(self.active_actions) > 0:
            self.logger.info(f"[SEQ STATUS {self.unique_id}] Active Set: {self.active_actions}")

        return {
            'is_activated': self.is_activated,
            'status_text': status_text,
            'window_start': self.window_start_time,
            'window_end': self.window_end_time,
            'period': self.sequence_cycle_duration,
            'cycle_start_time': cycle_start if cycle_start else 0,
            'elapsed': elapsed,
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
        
        # Determine steps/schedule
        enabled_actions = []
        for a in actions:
            try:
                opts = json.loads(a.custom_options) if a.custom_options else {}
            except:
                opts = {}
            if opts.get('enabled', True):
                enabled_actions.append((a, opts))

        single_actions = [item for item in enabled_actions if item[1].get('sequence_mode', 'single') != 'total']
        total_actions = [item for item in enabled_actions if item[1].get('sequence_mode', 'single') == 'total']

        schedule = []
        prev_end_time = 0.0
        max_end_time = 0.0
        
        for i, (action, opts) in enumerate(single_actions):
            base_duration = float(opts.get('action_duration', 0))
            # Dynamic duration fallback to base for static view
            step_time = base_duration
            
            head_overlap = overlap if i > 0 else 0
            tail_overlap = overlap if i < len(single_actions) - 1 else 0
            total_on_duration = head_overlap + step_time + tail_overlap
            
            start_t = (prev_end_time - overlap) if i > 0 else 0.0
            if start_t < 0: start_t = 0.0
            end_t = start_t + total_on_duration
            prev_end_time = end_t
            if end_t > max_end_time: max_end_time = end_t
            
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
            device_detail = "-"
            target_id = action.do_unique_id or opts.get('output') or opts.get('input')
            if target_id:
                try:
                    parts = str(target_id).split(',')
                    main_id = parts[0]
                    raw_chan = parts[1] if len(parts) > 1 else "0"
                    
                    out = db_retrieve_table_daemon(Output, unique_id=main_id)
                    if out:
                        device_detail = f"{out.name}"
                        if len(parts) > 1:
                            # Try to resolve channel index
                            try:
                                chan_obj = db_retrieve_table_daemon(OutputChannel, unique_id=raw_chan)
                                if chan_obj:
                                    device_detail += f" [CH{chan_obj.channel}]"
                                else:
                                    device_detail += f" [CH{raw_chan}]"
                            except:
                                device_detail += f" [CH{raw_chan}]"
                    else:
                        inp = db_retrieve_table_daemon(Input, unique_id=main_id)
                        if inp:
                            device_detail = f"{inp.name} [Input]"
                        else:
                            func = db_retrieve_table_daemon(CustomController, unique_id=main_id)
                            if func:
                                device_detail = f"{func.name} [Func]"
                except:
                    pass

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
                'is_active': False
            })

        return {
            'is_activated': trigger.is_activated,
            'status_text': "Standby" if not trigger.is_activated else "Ready",
            'window_start': trigger.timer_start_time or "00:00",
            'window_end': trigger.timer_end_time or "00:00",
            'period': float(trigger.period or 3600),
            'cycle_start_time': 0,
            'elapsed': 0,
            'steps': steps
        }

    def initialize_variables(self):
        self.trigger = db_retrieve_table_daemon(Trigger, unique_id=self.unique_id)
        if not self.trigger:
            self.running = False
            return

        self.is_activated = self.trigger.is_activated
        
        self.window_start_time = self.trigger.timer_start_time or "00:00"
        self.window_end_time = self.trigger.timer_end_time or "00:00"
        self.sequence_cycle_duration = float(self.trigger.period or 3600)
        self.action_overlap_duration = float(self.trigger.output_duration or 0)
        self.start_latency = float(self.trigger.timer_start_offset or 0)
        # Using time_offset_minutes for validity duration (seconds) as per user preference
        self.input_validity_duration = float(self.trigger.time_offset_minutes if self.trigger.time_offset_minutes is not None else 300)
        
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
                         self.logger.info(f"Dynamic Duration ACCEPTED (Specific): {found_val} (Raw={val}, Age={age:.1f}s)")
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
                     self.logger.info(f"Dynamic Duration ACCEPTED (Direct): {final_val}")
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
                        self.logger.info(f"Dynamic Duration ACCEPTED: {found_val} (Raw={val}, Age={age:.1f}s)")
                        return found_val
                    except Exception as e:
                        self.logger.error(f"Error parsing dynamic value tuple {val_tuple}: {e}")
            
            if found_val is None:
                 self.logger.warning(f"No valid measurements found for Input {input_id}")
                
        else:
             self.logger.warning(f"Input object {input_id} not found in DB")
        
        # Check CustomController (Function) - Placeholder for future expansion
        func = db_retrieve_table_daemon(CustomController, unique_id=source_id)
        if func:
             pass
             
        return None

    def build_cycle_schedule(self):
        """Builds the schedule for the new cycle."""
        actions = db_retrieve_table_daemon(Actions).filter(Actions.function_id == self.unique_id).all()
        
        # Debug Logging for Sort
        debug_list = []
        for a in actions:
            try:
                debug_list.append(f"{a.unique_id}: {a.position} (custom_opts: {a.custom_options})")
            except Exception as e:
                debug_list.append(f"{a.unique_id}: Error {e}")
        self.logger.debug(f"Actions before sort: {debug_list}")

        # Sort actions by GridStack position
        def get_pos(x):
            try:
                opts = json.loads(x.custom_options) if x.custom_options else {}
                pos = opts.get('position')
                return int(pos) if pos is not None else 9999
            except:
                return 9999

        try:
            actions = sorted(actions, key=get_pos)
        except Exception as e:
            self.logger.error(f"Error sorting actions: {e}")
            actions = sorted(actions, key=lambda x: x.id)
            
        self.logger.debug(f"Actions after sort: {[a.unique_id for a in actions]}")
        
        self.all_actions_cache = actions # Update cache
        
        # DEBUG: Log final sorted order
        for idx, act in enumerate(actions):
            try:
                opts = json.loads(act.custom_options) if act.custom_options else {}
                self.logger.info(f"SEQUENCE ORDER [{idx}]: ID={act.unique_id}, Pos={act.position}, Name={act.name or act.action_type}, Enabled={opts.get('enabled')}")
            except:
                pass
        
        # Filter Enabled Actions
        enabled_actions = []
        for a in actions:
            try:
                opts = json.loads(a.custom_options) if a.custom_options else {}
            except:
                opts = {}
            
            if opts.get('enabled', True):
                 enabled_actions.append(a)
            else:
                 self.logger.debug(f"Action {a.unique_id} skipped (Disabled)")

        schedule = []
        
        # Split actions
        single_actions = [a for a in enabled_actions if (json.loads(a.custom_options).get('sequence_mode', 'single') if a.custom_options else 'single') != 'total']
        total_actions = [a for a in enabled_actions if (json.loads(a.custom_options).get('sequence_mode', 'single') if a.custom_options else 'single') == 'total']
        
        # 1. Process Single Actions to determine total sequence time
        prev_end_time = 0.0
        max_end_time = 0.0
        
        count = len(single_actions)
        overlap = self.action_overlap_duration

        for i, action in enumerate(single_actions):
            try:
                opts = json.loads(action.custom_options) if action.custom_options else {}
            except:
                opts = {}
            
            base_duration = float(opts.get('action_duration', 0))
            dyn_source = opts.get('action_duration_id')
            
            # Step Time (Base Duration)
            step_time = base_duration
            
            if dyn_source:
                dyn_val = self.get_dynamic_duration(dyn_source)
                self.logger.debug(f"Action {action.unique_id} Dynamic Source {dyn_source} -> {dyn_val}")
                if dyn_val is not None and dyn_val > 0:
                    step_time = dyn_val
                else:
                    self.logger.debug(f"Action {action.unique_id} Dynamic Value invalid/none, using base: {base_duration}")

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
            
            self.logger.info(f"[SCHEDULE DEBUG] Act {action.unique_id}: Start={start_t:.1f}, End={end_t:.1f}, Base={step_time}, Head={head_overlap}, Tail={tail_overlap}, PrevEnd={prev_end_time:.1f}, OverlapCfg={overlap}")

            # Update previous end time for next iteration
            prev_end_time = end_t
            
            if end_t > max_end_time:
                max_end_time = end_t
            
            schedule.append({
                    'action': action,
                    'start': start_t,
                    'end': end_t,
                    'is_output': 'output' in action.action_type,
                    'type': 'single'
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
                     self.logger.info(f"Sequence {self.unique_id} DEACTIVATED. Stopping all actions.")
                     self.stop_all_active()
                     was_activated = False
                     self.activation_timestamp = 0

                if time.time() - last_log_time > 10:
                    self.logger.debug(f"Sequence {self.unique_id} loop running but NOT ACTIVATED.")
                    last_log_time = time.time()
                time.sleep(1.0)
                continue
            
            if not was_activated:
                self.logger.info(f"Sequence {self.unique_id} ACTIVATED. Latency={self.start_latency}s")
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
            
            # Check Window
            # using time_between_range from system_pi
            in_window = time_between_range(self.window_start_time, self.window_end_time)
            # Log window check result occasionally
            if time.time() - last_log_time > 300: # Log every 5 mins
                self.logger.info(f"Window Check: In={in_window}, Range={self.window_start_time}-{self.window_end_time}, Now={datetime.now().strftime('%H:%M')}")
                last_log_time = time.time()

            if not in_window:
                if time.time() - last_log_time > 60:
                     self.logger.debug(f"Sequence {self.unique_id} loop running. Outside Window ({self.window_start_time}-{self.window_end_time}). Now: {datetime.now().strftime('%H:%M')}")
                     last_log_time = time.time()

                # Outside window. Reset cycle.
                self.cycle_start_time = None
                self.stop_all_active()
                time.sleep(1.0)
                continue
            
            # Inside Window
            if self.cycle_start_time is None or (now - self.cycle_start_time >= self.sequence_cycle_duration):
                self.logger.info(f"Starting new cycle. now={now}, cycle_start={self.cycle_start_time}, limit={self.sequence_cycle_duration}")
                self.start_new_cycle(now)
            
            self.process_cycle(now)
            
            time.sleep(0.1)

    def start_new_cycle(self, now):
        self.cycle_start_time = now
        self.stop_all_active() # Ensure clean slate
        self.build_cycle_schedule()
        self.logger.info(f"Started new cycle at {now}. Schedule has {len(self.current_schedule)} items.")
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
                    self.logger.info(f"Desired matched: Action {item['action'].unique_id} at elapsed {elapsed}")
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
                     import json
                     opts = json.loads(action.custom_options)
                     target_id = opts.get('output', None)
                 except:
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
         self.initialize_variables()
         return "Sequence settings refreshed"

