# coding=utf-8
import logging
import json
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.databases.models import Trigger, Widget
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

from flask import jsonify, request
from flask_login import current_user
from aot.aot_client import DaemonControl
from aot.aot_flask.utils.utils_general import user_has_permission

def sequence_func_activate_toggle(unique_id, state):
    """Toggle the activation state of a sequence function.

    @phase active
    @stability stable
    @dependency DaemonControl
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'Auth Required'}), 401
    
    # Check permissions if needed
    if not user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission Denied'}), 403

    daemon = DaemonControl()
    if state == 'activate':
        daemon.controller_activate(unique_id)
    elif state == 'deactivate':
        daemon.controller_deactivate(unique_id)
    else:
        return jsonify({'error': 'Invalid State'}), 400
        
    return jsonify({'status': 'success'})

def sequence_func_toggle_details(unique_id, state):
    """Toggle the visibility of sequence action details in the widget.

    @phase active
    @stability stable
    @dependency Widget
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'Auth Required'}), 401

    widget = db.session.query(Widget).filter_by(unique_id=unique_id).first()
    if not widget:
        return jsonify({'error': 'Widget not found'}), 404
        
    try:
        options = {}
        if widget.custom_options:
            options = json.loads(widget.custom_options) if isinstance(widget.custom_options, str) else dict(widget.custom_options)
        
        # Update state
        new_val = 'Show' if str(state) == '1' else 'Hide'
        options['show_details'] = new_val
        
        widget.custom_options = json.dumps(options)
        db.session.commit()
        
        return jsonify({'status': 'success', 'state': new_val})
    except Exception as e:
        logger.error(f"Error toggling details: {e}")
        return jsonify({'error': str(e)}), 500

def execute_at_modification(mod_widget, request_form, custom_options_presave, custom_options_postsave):
    """Synchronize settings between Widget Options and the Sequence Function (Trigger).

    @phase active
    @stability stable
    @dependency Trigger, db.session
    """
    options = {}
    try:
        if mod_widget.custom_options:
            options = json.loads(mod_widget.custom_options) if isinstance(mod_widget.custom_options, str) else dict(mod_widget.custom_options)
    except: pass

    final_options = options.copy()
    

    # 1. Merge submitted options
    for k, v in custom_options_postsave.items():
        final_options[k] = v

    # Normalize show_details if needed (Handling legacy S/H/1/0/True/False)
    sd = final_options.get('show_details')
    if sd in ['S', '1', 'True', True]:
        final_options['show_details'] = 'Show'
    elif sd in ['H', '0', 'False', False]:
        final_options['show_details'] = 'Hide'

    # 2. Sync Logic
    func_id = final_options.get('function_id')
    old_func_id = options.get('function_id')
    
    if func_id:
        trigger = db.session.query(Trigger).filter_by(unique_id=func_id).first()
        if trigger:
            if func_id != old_func_id:
                # Case A: Function Changed (or Init) -> Pull ALL from Function
                final_options['timer_start_time'] = trigger.timer_start_time or "00:00"
                final_options['timer_end_time'] = trigger.timer_end_time or "23:59"
                final_options['sequence_period'] = float(trigger.period or 3600)
                final_options['timer_start_offset'] = int(trigger.timer_start_offset or 0)
                final_options['output_duration'] = float(trigger.output_duration or 0)
                # Using time_offset_minutes for validity
                final_options['time_offset_minutes'] = int(trigger.time_offset_minutes or 300)
                
                logger.info(f"Widget {mod_widget.unique_id}: Initialised/Pulled settings from Function {func_id}")
            else:
                # Case B: Smart Sync
                # We need to detect if the user changed the value in the form
                # compared to what was previously stored in the widget.
                
                updates_to_push = False
                
                def smart_sync_field(field_key, attr_name, cast_func=str, db_cast=str):
                    nonlocal updates_to_push
                    
                    val_submitted = final_options.get(field_key)
                    val_stored = options.get(field_key)
                    val_func = getattr(trigger, attr_name)
                    
                    # Normalize function value to widget's format
                    try:
                        val_func_norm = db_cast(val_func) if val_func is not None else (0 if db_cast in [int, float] else "")
                    except:
                        val_func_norm = val_func

                    # Normalize submitted and stored for comparison (as strings usually safe for equality)
                    s_sub = str(val_submitted) if val_submitted is not None else ""
                    s_stored = str(val_stored) if val_stored is not None else ""
                    
                    if s_sub != s_stored:
                        # User Changed Value -> PUSH to Function
                        try:
                            setattr(trigger, attr_name, cast_func(val_submitted))
                            updates_to_push = True
                            logger.info(f"User updated {field_key}: {val_stored} -> {val_submitted}. Pushing to Trigger.")
                        except Exception as e:
                            logger.error(f"Error setting {attr_name}: {e}")
                    else:
                        # User did not change -> PULL from Function
                        # Update final_options to match reality
                        final_options[field_key] = val_func_norm

                # Only sync legacy time fields in shared mode; per_day lives in timer_schedule
                raw_sched = getattr(trigger, 'timer_schedule', None)
                sched_mode = 'shared'
                if raw_sched:
                    try:
                        import json as _j
                        sched_mode = _j.loads(raw_sched).get('mode', 'shared')
                    except Exception:
                        pass

                if sched_mode == 'shared':
                    smart_sync_field('timer_start_time', 'timer_start_time', str, str)
                    smart_sync_field('timer_end_time', 'timer_end_time', str, str)
                    smart_sync_field('sequence_period', 'period', float, float)
                else:
                    # per_day: start/end are per-day, pull only (don't push global values).
                    # period is synced via trigger.period which now tracks today's per-day
                    # period (updated by /function_sequence_update_schedule).
                    final_options['timer_start_time'] = trigger.timer_start_time or "00:00"
                    final_options['timer_end_time']   = trigger.timer_end_time or "23:59"
                    smart_sync_field('sequence_period', 'period', float, float)

                smart_sync_field('timer_start_offset', 'timer_start_offset', int, int)
                smart_sync_field('output_duration', 'output_duration', float, float)
                smart_sync_field('time_offset_minutes', 'time_offset_minutes', int, int)
                
                if updates_to_push:
                    # Sync timer_schedule JSON so the daemon picks up new shared-mode values
                    try:
                        import json as _j
                        from aot.utils.weekly_schedule import parse_schedule, from_legacy
                        raw_sched = getattr(trigger, 'timer_schedule', None)
                        sched = parse_schedule(raw_sched) or from_legacy(
                            trigger.timer_start_time, trigger.timer_end_time,
                            getattr(trigger, 'timer_weekday', None), trigger.period or 3600,
                        )
                        if sched.get('mode') == 'shared':
                            new_start  = trigger.timer_start_time or '00:00'
                            new_end    = trigger.timer_end_time or '23:59'
                            new_period = int(float(trigger.period or 3600))
                            sched['shared']['start']  = new_start
                            sched['shared']['end']    = new_end
                            sched['shared']['period'] = new_period
                            for i in range(7):
                                sched['days'][str(i)]['start']  = new_start
                                sched['days'][str(i)]['end']    = new_end
                                sched['days'][str(i)]['period'] = new_period
                            trigger.timer_schedule = _j.dumps(sched)
                        elif sched.get('mode') == 'per_day':
                            # Only propagate period to all days (preserve per-day start/end)
                            new_period = int(float(trigger.period or 3600))
                            sched['shared']['period'] = new_period
                            for i in range(7):
                                sched['days'][str(i)]['period'] = new_period
                            trigger.timer_schedule = _j.dumps(sched)
                    except Exception as _e:
                        logger.error(f"execute_at_modification: timer_schedule sync failed: {_e}")
                    db.session.commit()
                    # Refresh Controller if we pushed changes
                    from aot.aot_client import DaemonControl
                    DaemonControl().refresh_daemon_trigger_settings(func_id)
                    logger.info("Trigger settings refreshed after push.")
                else:
                    logger.info("No user changes detected. Widget synced from Trigger.")

    return True, True, mod_widget, final_options


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_trigger_sequence',
    'widget_name': lazy_gettext('Sequence Controller'),
    # On mobile (<=768px), place only one widget per row (full width). If False/unset, allow two per row.
    'mobile_full_width': True,
    'widget_library': '',
    'no_class': True,
    'message': lazy_gettext('Control and Monitor a Sequence Function.'),
    'widget_width': 24,
    'widget_height': 10,
    'execute_at_modification': execute_at_modification,
    
    'endpoints': [
        ("/sequence_func_activate_toggle/<unique_id>/<state>", "sequence_func_activate_toggle", sequence_func_activate_toggle, ["GET"]),
        ("/sequence_func_toggle_details/<unique_id>/<state>", "sequence_func_toggle_details", sequence_func_toggle_details, ["GET"])
    ],

    'custom_options': [
        {
            'id': 'function_id',
            'type': 'select_device',
            'default_value': '',
            'options_select': ['Trigger'],
            'filter': {'key': 'trigger_type', 'value': 'trigger_sequence'},
            'name': lazy_gettext('Sequence Function'),
            'phrase': lazy_gettext('Select the Sequence to control')
        },
        {
            'id': 'refresh_seconds',
            'type': 'float',
            'default_value': 5.0,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Refresh (Seconds)'),
            'phrase': lazy_gettext('The period of time between refreshing the widget')
        },
        {
            'id': 'show_details',
            'type': 'select',
            'options_select': [
                ('Show', lazy_gettext('Show')),
                ('Hide', lazy_gettext('Hide'))
            ],
            'default_value': 'Show',
            'name': lazy_gettext('Show Actions List'),
            'phrase': lazy_gettext('Toggle the visibility of the action list by default.')
        },
        
        # --- Sequence Settings (Synced) ---
        {
            'type': 'header',
            'name': lazy_gettext('Sequence Settings (Synced)')
        },
        {
            'id': 'timer_start_time',
            'type': 'text',
            'default_value': '00:00',
            'name': lazy_gettext('Start Time'),
            'phrase': lazy_gettext('HH:MM format')
        },
        {
            'id': 'timer_end_time',
            'type': 'text',
            'default_value': '23:59',
            'name': lazy_gettext('End Time'),
            'phrase': lazy_gettext('HH:MM format')
        },
        {
            'id': 'sequence_period',
            'type': 'float',
            'default_value': 3600,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Period (Seconds)'),
            'phrase': lazy_gettext('Total duration of one cycle')
        },
        {
            'id': 'timer_start_offset',
            'type': 'integer',
            'default_value': 0,
            'name': lazy_gettext('Startup Delay (s)'),
            'phrase': lazy_gettext('Startup delay after activation')
        },
        {
            'id': 'output_duration',
            'type': 'float',
            'default_value': 0,
            'name': lazy_gettext('Crossing Time (s)'),
            'phrase': lazy_gettext('Crossing time between steps')
        },
        {
            'id': 'time_offset_minutes',
            'type': 'integer',
            'default_value': 300,
            'name': lazy_gettext('Input Validity (s)'),
            'phrase': lazy_gettext('Input value validity duration')
        }
    ],

    'widget_dashboard_head': """
    <link rel="stylesheet" href="/static/css/components/aot-toggle.css">
    <link rel="stylesheet" href="/static/css/components/aot-time-wheel.css">
    <script src="/static/js/components/aot-time-wheel.js?v=20260722a"></script>
    <script src="/static/js/common/aot-output-state.js?v=9"></script>
    <style>
        /* --- Layout --- */
        .seq-widget-container {
            padding: 10px 12px;
            color: var(--aot-text-main, #333);
            font-family: var(--aot-font-family);
            font-size: var(--aot-fs-body);
            /* Fill the tile width (list layout stays balanced: name grows, time right) */
            width: 100%;
            box-sizing: border-box;
        }

        /* --- Section 1: Header --- */
        .seq-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .seq-main-timer {
            font-size: var(--aot-fs-value-sm);
            font-weight: var(--aot-fw-bold);
            font-variant-numeric: tabular-nums;
            color: var(--aot-text-title, #222);
        }

        /* --- Section 2: Weekday Row (TOP) --- */
        .seq-weekday-row {
            display: flex;
            justify-content: space-around;
            align-items: stretch;
            margin-bottom: 10px;
            padding: 8px 6px;
            background-color: var(--bg-off);
            border: 1px solid var(--aot-border-light);
            border-radius: 8px;
            gap: 3px;
        }

        .seq-day-cell {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
            min-width: 0;
            max-width: 90px;
            gap: 6px;
        }

        /* Enabled checkbox */
        .seq-day-check {
            width: 18px;
            height: 18px;
            cursor: pointer;
            accent-color: var(--aot-color-brand-secondary);
            flex-shrink: 0;
        }

        /* Day button: tap to select for editing */
        .seq-day-btn {
            width: 100%;
            padding: 6px 2px 7px;
            border: 2px solid transparent;
            border-radius: 5px;
            background: transparent;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 1px;
            transition: background 0.15s, border-color 0.15s;
            outline: none;
        }
        .seq-day-btn:hover {
            background: var(--bg-btn-hover-light);
        }

        /* Today: secondary border only */
        .seq-day-btn.is-today {
            border-color: var(--aot-color-brand-secondary);
        }
        /* Selected (editing): filled secondary background */
        .seq-day-btn.is-selected {
            border-color: var(--aot-color-brand-secondary);
            background: var(--aot-color-brand-secondary);
        }
        .seq-day-btn.is-selected .seq-day-label-text {
            color: var(--aot-color-text-tertiary);
        }
        /* Today AND selected: filled secondary + inner ring */
        .seq-day-btn.is-today.is-selected {
            border-color: var(--aot-color-brand-secondary);
            background: var(--aot-color-brand-secondary);
            box-shadow: inset 0 0 0 1px rgba(255,255,255,0.4);
        }

        .seq-day-label-text {
            font-size: var(--aot-fs-label);
            font-weight: var(--aot-fw-semibold);
            color: var(--aot-text-main);
            user-select: none;
            line-height: 1.1;
        }
        .seq-day-weekend .seq-day-label-text {
            color: var(--aot-color-danger);
        }
        /* Disabled (unchecked) day: dim text */
        .seq-day-cell.is-disabled .seq-day-label-text {
            opacity: 0.4;
        }

        /* Action row — 3 evenly distributed buttons below info grid */
        .seq-action-row {
            display: flex;
            gap: 6px;
            margin-bottom: 10px;
        }
        .seq-action-btn {
            flex: 1;
            padding: 5px 4px;
            border-radius: 10px;
            border: 1px solid var(--aot-border-light);
            background: transparent;
            font-size: var(--aot-fs-label);
            color: var(--gray-dark);
            cursor: pointer;
            transition: all 0.15s;
        }
        .seq-action-btn:hover {
            background: var(--bg-btn-hover-light);
        }
        .seq-action-btn.active {
            background: var(--aot-color-brand-secondary);
            border-color: var(--aot-color-brand-secondary);
            color: var(--text-color-tertiary);
        }

        /* --- Section 3: Info Grid (BOTTOM) --- */
        .seq-info-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 10px;
        }
        .seq-info-card {
            background-color: var(--bg-off);
            border: 1px solid var(--aot-border-light);
            border-radius: 8px;
            padding: 8px 4px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .seq-info-label {
            font-size: var(--aot-fs-label);
            color: var(--gray-dark);
            text-transform: uppercase;
            margin-bottom: 4px;
            font-weight: var(--aot-fw-medium);
        }
        .seq-info-value {
            font-size: var(--aot-fs-value-sm);
            font-weight: var(--aot-fw-bold);
            font-variant-numeric: tabular-nums;
            color: var(--aot-text-main);
        }
        .seq-card-editable { cursor: pointer; transition: border-color 0.15s; }
        .seq-card-editable:hover { border-color: var(--aot-color-brand-secondary); }

        /* --- Expand Button --- */
        .seq-expand-btn-container { margin-bottom: 10px; display: flex; justify-content: center; }
        .seq-expand-btn {
            width: 100%; height: 32px; border-radius: 16px;
            background-color: transparent; border: 1px solid var(--aot-border-light, #ddd);
            color: var(--gray-dark, #666); font-size: var(--aot-fs-body); font-weight: var(--aot-fw-medium);
            display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s ease;
        }
        .seq-expand-btn:hover { background-color: var(--aot-color-brand-secondary); border-color: var(--aot-color-brand-secondary); color: var(--text-color-tertiary); }
        .seq-expand-btn:active { transform: scale(0.99); }
        .seq-expand-icon { font-size: var(--aot-fs-caption); margin-left: 6px; transition: transform 0.3s ease; }
        .seq-expand-btn.expanded .seq-expand-icon { transform: rotate(180deg); }

        /* --- Action List --- */
        .seq-details-container { display: none; overflow: hidden; }
        .seq-details-container.expanded { display: block; }
        .seq-list-header {
            display: flex; align-items: center; padding: 8px 10px;
            background-color: var(--bg-off); border-bottom: 1px solid var(--aot-border-light);
            border-top-left-radius: 8px; border-top-right-radius: 8px;
            font-size: var(--aot-fs-caption); color: var(--gray-dark, #777); font-weight: var(--aot-fw-semibold);
        }
        .seq-col-enable { width: 36px; text-align: center; flex-shrink: 0; }
        /* justify-content:space-between pins the device-status label to this column's
           right edge (name text left, badge right) — the column's width is fixed by the
           flex layout (same leftover space every row), so the badge lines up vertically
           across rows instead of trailing the variable-length name text or drifting with
           the time column. */
        .seq-col-name { flex: 1 1 auto; min-width: 0; padding-left: 8px; padding-right: 8px; margin-right: 12px; overflow: hidden; align-self: stretch; display: flex; align-items: center; justify-content: space-between; }
        /* min-width fits the time value (e.g. "00:00:10" ~60px) so it's never clipped
           in a narrow widget cell AND the header/value columns share a width (so the
           left-aligned "Time" header lines up with the column instead of hugging the
           right edge); the name column yields space instead. */
        .seq-col-time { width: auto; min-width: 70px; text-align: right; padding-right: 9px; flex-shrink: 0; }
        /* Header label left-aligned; the padding above makes the value's right gap
           match the checkbox's left gap (row pad + (enable-width - checkbox)/2). */
        .seq-list-header .seq-col-time { text-align: left; }
        /* border-box so the declared column widths INCLUDE their padding — otherwise
           padding adds to width and, in a narrow widget cell, pushes the time value
           past the row edge where grid-stack's overflow-x:hidden clips its margin. */
        .seq-col-enable, .seq-col-name, .seq-col-time { box-sizing: border-box; }
        .seq-list-body {
            border: 1px solid var(--aot-border-light); border-top: none;
            border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;
            background: var(--bg-off); max-height: 330px; overflow-y: auto;
        }
        .seq-list-item {
            display: flex; align-items: center; padding: 0 10px;
            border-bottom: 1px solid var(--aot-border-light, #f0f0f0);
            color: var(--aot-text-main, #444); font-size: var(--aot-fs-body);
            height: 40px; box-sizing: border-box; white-space: nowrap; flex-wrap: nowrap;
        }
        .seq-list-item:last-child { border-bottom: none; }
        .seq-list-item.active { background-color: var(--bg-active); border-left: 3px solid var(--aot-color-brand-secondary); padding-left: 7px; }
        .seq-list-item.disabled { opacity: 0.6; background-color: var(--bg-off); }
        /* Device state (Model A): offline/unconfirmed target output.
           2026-08-04: --bg-pause(일시정지) 에서 danger 틴트로 이관 — 무응답은
           사용자가 멈춘 것이 아니라 고장이다. 배지 글자색이 #fff 고정이었는데
           danger 틴트 배경은 밝아서 안 보인다 — fg 토큰과 쌍으로 쓴다. */
        .seq-list-item.seq-offline { border-left: 3px solid var(--aot-tint-danger-fg, #b23b3b); padding-left: 7px; }
        .seq-dev-badge { margin-left: 6px; flex-shrink: 0; font-size: var(--aot-fs-caption, 0.72em); padding: 0 5px; border-radius: 8px; white-space: nowrap; vertical-align: middle; }
        .seq-dev-offline { background: var(--aot-tint-danger-bg, #fbe7e7); color: var(--aot-tint-danger-fg, #b23b3b); opacity: 0.85; }
        .seq-dev-pending { background: var(--bg-hold, #f0ad4e); color: #fff; }

        /* --- Drag to reorder --- */
        /* Rows are picked up by pressing and dragging (touch: press and hold).
           The grab cursor is the desktop affordance; there is no handle column
           because the row is only ~160px wide on a phone. */
        .seq-list-item { cursor: grab; }
        /* While a drag is running, no text selection anywhere in the list. */
        .seq-list-body.seq-dnd-on { user-select: none; -webkit-user-select: none; }
        .seq-list-body.seq-dnd-on .seq-list-item { cursor: grabbing; }
        /* The lifted block floats above its neighbours. pointer-events:none is
           what lets elementFromPoint see the row UNDERNEATH the dragged rows,
           which is how the drop position is resolved. */
        .seq-list-item.seq-row-drag {
            position: relative; z-index: 3;
            background: var(--aot-surface-modal, #fff);
            box-shadow: 0 3px 10px rgba(0,0,0,0.18);
            pointer-events: none;
        }

        /* Square Toggle */
        .seq-square-toggle {
            appearance: none; -webkit-appearance: none;
            width: 18px; height: 18px;
            border: 2px solid var(--aot-color-brand-secondary); border-radius: 2px;
            background-color: transparent; cursor: pointer; position: relative;
            vertical-align: middle; outline: none; transition: all 0.2s ease;
        }
        .seq-square-toggle:checked { background-color: var(--aot-color-brand-secondary); border-color: var(--aot-color-brand-secondary); }
        .seq-square-toggle:checked::after {
            content: ''; position: absolute; top: 1px; left: 4px;
            width: 5px; height: 9px; border: solid white; border-width: 0 2px 2px 0; transform: rotate(45deg);
        }
        .seq-square-toggle:hover { border-color: var(--aot-color-brand-secondary); opacity: 0.8; }

        /* Text */
        .seq-text-name { font-weight: var(--aot-fw-medium); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex-shrink: 1; }
        .seq-text-time { font-weight: var(--aot-fw-semibold); font-variant-numeric: tabular-nums; color: var(--aot-text-main, #555); }
        .seq-col-time.seq-time-editable { cursor: pointer; }
        .seq-col-time.seq-time-editable:hover .seq-text-time { color: var(--bd-btn-primary); text-decoration: underline; }
        /* Group tint fills the whole NAME cell (full row height) so contiguous
           group members' backgrounds connect into ONE continuous block; only the
           block's top (first member) and bottom (last member) are rounded.
           --gc = a system chart-palette token, set inline on the cell. */
        .seq-col-name.seq-grp { background: color-mix(in srgb, var(--gc, var(--aot-color-brand-secondary)) 22%, transparent); }
        .seq-col-name.seq-gm-first  { border-top-left-radius: 12px; border-top-right-radius: 12px; }
        .seq-col-name.seq-gm-last   { border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }
        .seq-col-name.seq-gm-single { border-radius: 12px; }
        /* Remove the row divider between members of the same group so the tint is seamless */
        .seq-list-item.seq-group-cont { border-bottom-color: transparent; }
        /* Total step: bold name (single steps get no extra marker) */
        .seq-name-total { font-weight: var(--aot-fw-bold, 700); }
        /* Color dot in the group option buttons (settings modal) */
        .seq-group-opt-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px; vertical-align: middle; }
        /* Group picker modal (wider, modern, one group per line) */
        .seq-group-modal .seq-type-panel {
            width: min(360px, 92vw);
            box-sizing: border-box;
            padding: var(--aot-space-4, 16px);
        }
        .seq-group-modal .seq-type-panel-title {
            text-align: left;
            margin-bottom: var(--aot-space-3, 12px);
        }
        /* Groups stack vertically, one full-width button per line */
        .seq-group-modal .seq-type-options {
            flex-direction: column;
            gap: var(--aot-space-2, 8px);
            max-height: 44vh;
            overflow-y: auto;
            margin-bottom: var(--aot-space-3, 12px);
        }
        .seq-group-modal .seq-type-options .btn.aot-pill-btn {
            flex: 0 0 auto;
            width: 100%;
            text-align: center;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        /* Name input + save button sit inside the panel, no overflow */
        .seq-group-new-row {
            display: flex;
            gap: var(--aot-space-2, 8px);
            width: 100%;
            box-sizing: border-box;
            margin-bottom: var(--aot-space-3, 12px);
        }
        .seq-group-new-row .seq-group-new-input {
            flex: 1 1 auto;
            min-width: 0;
            height: 36px;
            border-radius: 18px;
            border: 1px solid var(--aot-border-light);
            padding: 0 12px;
            background: var(--aot-input-bg);
            color: var(--aot-text-main, #444);
            font-size: var(--aot-fs-body);
            box-sizing: border-box;
        }
        .seq-group-new-row .seq-group-new-btn {
            flex: 0 0 auto;
            white-space: nowrap;
        }

        /* Combined step settings modal (time on top, group below) */
        .seq-step-modal .seq-type-panel { width: min(360px, 92vw); box-sizing: border-box; padding: var(--aot-space-4, 16px); max-height: 92vh; overflow-y: auto; }
        .seq-step-time-body .aot-wheel-cols { margin: 2px 0 4px; }
        .seq-step-modal .seq-type-panel-title { text-align: left; margin-bottom: var(--aot-space-3, 12px); }
        .seq-step-section { margin-bottom: var(--aot-space-4, 16px); }
        .seq-step-label { font-weight: var(--aot-fw-semibold, 600); font-size: var(--aot-fs-label); color: var(--gray-dark, #888); text-transform: uppercase; margin-bottom: 6px; }
        .seq-step-time-input {
            width: 100%; height: 44px; border-radius: 22px; border: 1px solid var(--aot-border-light);
            padding: 0 14px; background: var(--aot-input-bg); color: var(--aot-text-main, #444);
            font-size: var(--aot-fs-body); box-sizing: border-box; text-align: center; font-variant-numeric: tabular-nums;
            cursor: pointer; font-weight: var(--aot-fw-semibold, 600);
        }
        .seq-step-time-input:hover { border-color: var(--aot-color-brand-secondary); }
        .seq-step-note { color: var(--gray-dark, #888); font-size: var(--aot-fs-body); padding: 4px 2px; }
        .seq-step-group-body { display: flex; flex-direction: column; gap: var(--aot-space-2, 8px); max-height: 34vh; overflow-y: auto; }
        .seq-step-group-body .btn.aot-pill-btn { width: 100%; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .seq-step-newrow { display: flex; gap: var(--aot-space-2, 8px); width: 100%; box-sizing: border-box; margin-top: var(--aot-space-2, 8px); }
        .seq-step-newrow input { flex: 1 1 auto; min-width: 0; height: 36px; border-radius: 18px; border: 1px solid var(--aot-border-light); padding: 0 12px; background: var(--aot-input-bg); color: var(--aot-text-main, #444); font-size: var(--aot-fs-body); box-sizing: border-box; }
        .seq-step-newrow button { flex: 0 0 auto; white-space: nowrap; }
        .seq-step-modal .seq-type-cancel-row { display: flex; gap: var(--aot-space-2, 8px); }
        .seq-step-modal .seq-type-cancel-row .btn.aot-pill-btn { flex: 1; }
        /* Name modal: editable name cell, name input, type toggle */
        .seq-name-editable { cursor: pointer; }
        .seq-name-editable:hover .seq-text-name { text-decoration: underline; }
        .seq-step-name-input { width: 100%; height: 40px; border-radius: 20px; border: 1px solid var(--aot-border-light); padding: 0 14px; background: var(--aot-input-bg); color: var(--aot-text-main, #444); font-size: var(--aot-fs-body); box-sizing: border-box; }
        .seq-step-type-body { display: flex; gap: var(--aot-space-2, 8px); }
        .seq-step-type-body .btn.aot-pill-btn { flex: 1; }

        /* Type Picker Modal */
        .seq-type-backdrop {
            position: fixed; inset: 0; z-index: var(--aot-z-modal-backdrop, 5000);
            display: none; align-items: center; justify-content: center;
            background: var(--aot-modal-backdrop, rgba(0,0,0,0.5));
        }
        .seq-type-backdrop.is-open { display: flex; }
        .seq-type-panel {
            background: var(--aot-surface-modal, #fff); border-radius: var(--aot-btn-radius, 18px);
            box-shadow: var(--aot-shadow-modal, 0 5px 20px rgba(0,0,0,0.15));
            padding: var(--aot-space-4, 16px) var(--aot-space-4, 16px) var(--aot-space-3, 12px);
            width: min(220px, 85vw); user-select: none;
        }
        .seq-type-panel-title { text-align: center; font-weight: var(--aot-fw-bold, 700); font-size: var(--aot-fs-body, 0.875rem); color: var(--aot-text-title, #222); margin-bottom: var(--aot-space-3, 12px); }
        .seq-type-options { display: flex; gap: var(--aot-space-2, 8px); margin-bottom: var(--aot-space-3, 12px); }
        .seq-type-options .btn.aot-pill-btn { flex: 1; }
        .seq-type-cancel-row { display: flex; }
        .seq-type-cancel-row .btn.aot-pill-btn { flex: 1; }

        @media (max-width: 768px) {
            .seq-list-item, .seq-list-header { padding-left: 6px; padding-right: 6px; }
            .seq-col-enable { width: 30px; }
            .seq-col-name { min-width: 0; padding-left: 6px; }
            .seq-col-time { padding-right: 6px; }
        }
    </style>
    """,

    'widget_dashboard_title_bar': """<span class="aot-w-title" id="seq-title-{{each_widget.unique_id}}">{{each_widget.name}}</span>""",

    'widget_dashboard_body': """
    {% set show_det = widget_options.get('show_details', 'Show') %}
    {% set fid = widget_options['function_id'] %}
    {% set wid = each_widget.unique_id %}
    <div id="seq-container-{{wid}}" class="seq-widget-container"
         data-fid="{{fid}}" data-wid="{{wid}}">

        <!-- Section 1: Header -->
        <div class="seq-header-row">
            <div id="seq-timer-{{wid}}" class="seq-main-timer">00:00:00 / 00:00:00</div>
            <label class="btn-toggle" data-toggle="tooltip" data-placement="top"
                   title="{{ _('Activate or deactivate this sequence') }}">
                <input type="checkbox" id="seq-main-toggle-{{wid}}" class="btn-toggle-input"
                       onchange="toggle_sequence_func('{{fid}}', this)">
                <span class="btn-toggle-slider"><span class="btn-toggle-thumb"></span></span>
            </label>
        </div>

        <!-- Section 2: Weekday Row (TOP) -->
        <div id="seq-weekday-{{wid}}" class="seq-weekday-row" data-fid="{{fid}}" data-wid="{{wid}}">
            {% for day_label, day_idx in [(_('Mon'),'0'),(_('Tue'),'1'),(_('Wed'),'2'),(_('Thu'),'3'),(_('Fri'),'4'),(_('Sat'),'5'),(_('Sun'),'6')] %}
            <div class="seq-day-cell{% if day_idx in ['5','6'] %} seq-day-weekend{% endif %}"
                 id="seq-day-cell-{{wid}}-{{day_idx}}" data-day="{{day_idx}}">
                <input type="checkbox" class="seq-day-check" data-day="{{day_idx}}" checked
                       onchange="seq_handle_enabled_change(this, '{{wid}}')"
                       data-toggle="tooltip" data-placement="top"
                       title="{{ _('Run the sequence on this weekday. Unchecked days are skipped.') }}">
                <button type="button" class="seq-day-btn" data-day="{{day_idx}}"
                        onclick="seq_select_day({{day_idx}}, '{{wid}}')"
                        data-toggle="tooltip" data-placement="top"
                        title="{{ _('Select this weekday to view and edit its times and actions') }}">
                    <span class="seq-day-label-text">{{day_label}}</span>
                </button>
            </div>
            {% endfor %}
        </div>

        <!-- Section 3: Info Grid (BOTTOM) — shows selected day's values -->
        <div class="seq-info-grid">
            <div class="seq-info-card seq-card-editable"
                 data-field="start_time" data-fid="{{fid}}" data-wid="{{wid}}"
                 onclick="seq_open_setting_wheel(this)"
                 data-toggle="tooltip" data-placement="top"
                 title="{{ _('Set the time of day the sequence starts for the selected day') }}">
                <span class="seq-info-label">{{ _('Start') }}</span>
                <span id="seq-disp-start-{{wid}}" class="seq-info-value">--:--</span>
            </div>
            <div class="seq-info-card seq-card-editable"
                 data-field="end_time" data-fid="{{fid}}" data-wid="{{wid}}"
                 onclick="seq_open_setting_wheel(this)"
                 data-toggle="tooltip" data-placement="top"
                 title="{{ _('Set the time of day the sequence stops. Select 00:00 for 24:00 (end of day).') }}">
                <span class="seq-info-label">{{ _('End') }}</span>
                <span id="seq-disp-end-{{wid}}" class="seq-info-value">--:--</span>
            </div>
            <div class="seq-info-card seq-card-editable"
                 data-field="period" data-fid="{{fid}}" data-wid="{{wid}}"
                 onclick="seq_open_setting_wheel(this)"
                 data-toggle="tooltip" data-placement="top"
                 title="{{ _('Set the duration of one cycle. Cycles repeat until the end time.') }}">
                <span class="seq-info-label">{{ _('Period') }}</span>
                <span id="seq-disp-period-{{wid}}" class="seq-info-value">-- s</span>
            </div>
        </div>

        <!-- Action row: mode + copy buttons -->
        <div class="seq-action-row">
            <button type="button" class="seq-action-btn active"
                    id="seq-mode-shared-{{wid}}"
                    onclick="seq_set_mode('shared', '{{wid}}', '{{fid}}')"
                    data-toggle="tooltip" data-placement="top"
                    title="{{ _('All weekdays share the same start, end, and period') }}">{{ _('Shared') }}</button>
            <button type="button" class="seq-action-btn"
                    id="seq-mode-perday-{{wid}}"
                    onclick="seq_set_mode('per_day', '{{wid}}', '{{fid}}')"
                    data-toggle="tooltip" data-placement="top"
                    title="{{ _('Set a different start, end, and period for each weekday') }}">{{ _('Per Day') }}</button>
            <button type="button" class="seq-action-btn"
                    id="seq-copy-btn-{{wid}}"
                    onclick="seq_copy_to_all('{{wid}}', '{{fid}}')"
                    data-toggle="tooltip" data-placement="top"
                    title="{{ _("Copy the selected day's settings to all weekdays") }}">{{ _('Copy to All') }}</button>
        </div>

        <!-- Expand Button -->
        <div class="seq-expand-btn-container">
            <button class="seq-expand-btn" onclick="sequence_func_toggle_details('{{wid}}', this)"
                    data-toggle="tooltip" data-placement="top"
                    title="{{ _('Show or hide the action list') }}">
                <span class="seq-btn-text">{{ _('Actions') }}</span>
                <span class="seq-expand-icon">{% if show_det == 'Show' %}▲{% else %}▼{% endif %}</span>
            </button>
        </div>

        <!-- Action List -->
        <div id="seq-details-{{wid}}" class="seq-details-container"
             style="display: {% if show_det == 'Show' %}block{% else %}none{% endif %} !important;">
            <div class="seq-list-header">
                <div class="seq-col-enable"></div>
                <div class="seq-col-name">{{ _('Name') }}</div>
                <div class="seq-col-time">{{ _('Time') }}</div>
            </div>
            <div id="seq-list-{{wid}}" class="seq-list-body">
                <div style="padding:20px;text-align:center;color:var(--text-medium-gray, #666);">{{ _('Waiting for data...') }}</div>
            </div>
        </div>
    </div>
    """,

    'widget_dashboard_js': """
    // Global state for this widget type to handle timers
    // Key: widget_id, Value: { interval: null, elapsed: 0, period: 0, is_active: false, start_ts: 0 }
    if (typeof window.seqWidgetState === 'undefined') {
        window.seqWidgetState = {};
    }

    // Distinct colors per device group, assigned by first-appearance order so
    // different groups never share a color. Uses the system chart palette
    // (var(--aot-chart-1..6), user-customizable in Settings > custom UI),
    // cycling through the 6 tokens if there are more groups.
    var SEQ_GROUP_COLORS = ['var(--aot-chart-1)','var(--aot-chart-2)','var(--aot-chart-3)','var(--aot-chart-4)','var(--aot-chart-5)','var(--aot-chart-6)'];
    // Assign a STABLE color per group name: once a name gets a color it keeps it,
    // so a group's color never changes when other groups appear or disappear.
    // (A dynamic index into the current group list made surviving groups shift
    // colors when one was emptied, which looked like a device "moving" groups.)
    function seq_group_color(name, groupList) {
        if (!name) return '';
        if (!window.__seqGroupColorIdx) window.__seqGroupColorIdx = {};
        var map = window.__seqGroupColorIdx;
        if (!Object.prototype.hasOwnProperty.call(map, name)) {
            map[name] = Object.keys(map).length;
        }
        return SEQ_GROUP_COLORS[map[name] % SEQ_GROUP_COLORS.length];
    }

    function format_seq_time(seconds) {
        if (seconds < 0) seconds = 0;
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = Math.floor(seconds % 60);
        return (h < 10 ? "0" + h : h) + ":" + (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
    }

    function update_local_timer(widget_id) {
        var state = window.seqWidgetState[widget_id];
        if (!state) return;

        var display = document.getElementById('seq-timer-' + widget_id);
        if (!display) return;

        var currentElapsed = 0;
        if (state.is_active && state.cycle_start_ts > 0) {
            // Calculate real elapsed time
            var now = Date.now() / 1000;
            currentElapsed = now - state.cycle_start_ts;
            if (currentElapsed < 0) currentElapsed = 0;
            if (currentElapsed > state.period) currentElapsed = state.period; // Cap at period
        } else {
             currentElapsed = 0;
        }

        display.innerText = format_seq_time(currentElapsed) + " / " + format_seq_time(state.period);
    }

    function safe_toast(type, msg) {
        if (typeof window.showToast === 'function') {
            window.showToast(msg, type);
            return;
        }
        var settings = window.AoTGlobalSettings || {};
        if (type === 'success' && settings.hide_success) return;
        if (type === 'info' && settings.hide_info) return;
        if ((type === 'warning' || type === 'error') && settings.hide_warning) return;
        
        if (typeof toastr !== 'undefined' && toastr[type]) {
            toastr[type](msg);
        } else {
             console.log("[Toast " + type + "] " + msg);
        }
    }

    // Effective enabled state of an action for the selected day:
    // per-day actions map overrides the global flag.
    function seq_action_enabled_for_day(ss, action_uid, globalEnabled) {
        if (ss.schedule && ss.schedule.days) {
            var entry = ss.schedule.days[String(ss.selectedDay)];
            if (entry && entry.actions && Object.prototype.hasOwnProperty.call(entry.actions, action_uid)) {
                return !!entry.actions[action_uid];
            }
        }
        return globalEnabled !== false;
    }

    // Only per_day mode uses the weekday overrides; shared mode is global.
    function seq_is_per_day(ss) {
        return !!(ss.schedule && ss.schedule.mode === 'per_day');
    }
    function seq_day_entry(ss) {
        if (!(ss.schedule && ss.schedule.days)) return null;
        return ss.schedule.days[String(ss.selectedDay)] || null;
    }
    // Effective group name for the selected day (per-day override → global fallback).
    function seq_action_group_for_day(ss, action_uid, globalGroup) {
        if (seq_is_per_day(ss)) {
            var e = seq_day_entry(ss);
            if (e && e.groups && Object.prototype.hasOwnProperty.call(e.groups, action_uid)) {
                var v = (e.groups[action_uid] || '').trim();
                return v || null;
            }
        }
        return globalGroup || null;
    }
    // Effective duration (seconds) for the selected day (per-day override → global fallback).
    function seq_action_duration_for_day(ss, action_uid, globalDur) {
        if (seq_is_per_day(ss)) {
            var e = seq_day_entry(ss);
            if (e && e.durations && Object.prototype.hasOwnProperty.call(e.durations, action_uid)) {
                var d = parseInt(e.durations[action_uid], 10);
                if (!isNaN(d)) return d;
            }
        }
        return globalDur;
    }

    // Ensure the selected day's entry has groups/durations maps; returns the entry.
    function seq_ensure_day_maps(ss) {
        if (!ss.schedule) return null;
        if (!ss.schedule.days) ss.schedule.days = {};
        var day = String(ss.selectedDay);
        if (!ss.schedule.days[day]) ss.schedule.days[day] = {};
        var e = ss.schedule.days[day];
        if (!e.groups) e.groups = {};
        if (!e.durations) e.durations = {};
        return e;
    }

    // Set a step's group for the selected day. Joining a group inherits that
    // group's common duration (from an existing member on this day) — this is
    // how a group's duration survives when its "leader" changes group.
    function seq_set_day_group(ss, uid, groupName, steps) {
        var e = seq_ensure_day_maps(ss); if (!e) return;
        e.groups[uid] = groupName || '';
        if (groupName) {
            for (var i = 0; i < steps.length; i++) {
                var st = steps[i]; if (st.unique_id === uid) continue;
                if (seq_action_group_for_day(ss, st.unique_id, st.group_name) === groupName) {
                    e.durations[uid] = seq_action_duration_for_day(ss, st.unique_id, parseInt(st.original_duration, 10) || 0);
                    break;
                }
            }
        }
    }

    // Set a step's duration for the selected day, propagating to same-day group
    // members so the group keeps one common duration.
    function seq_set_day_duration(ss, uid, sec, groupName, steps) {
        var e = seq_ensure_day_maps(ss); if (!e) return;
        e.durations[uid] = sec;
        if (groupName) {
            for (var i = 0; i < steps.length; i++) {
                var st = steps[i]; if (st.unique_id === uid) continue;
                if (seq_action_group_for_day(ss, st.unique_id, st.group_name) === groupName) {
                    e.durations[st.unique_id] = sec;
                }
            }
        }
    }

    // Toggle an action for the SELECTED DAY (stored in schedule JSON).
    // Falls back to the global toggle when no schedule is loaded.
    function toggle_seq_action(action_id, checkbox, widget_id, function_id) {
        var enabled = checkbox.checked;
        var ss = widget_id ? seq_get_sched_state(widget_id) : null;

        if (ss && ss.schedule && ss.schedule.days && ss.schedule.days[String(ss.selectedDay)]) {
            var entry = ss.schedule.days[String(ss.selectedDay)];
            if (!entry.actions) entry.actions = {};
            entry.actions[action_id] = enabled;
            seq_sync_schedule_to_server(widget_id, function_id, function() {
                seq_refresh_action_checks(widget_id);
            });
            return;
        }

        // Fallback: global toggle (no schedule loaded)
        $.ajax({
            url: '/function_sequence_toggle_action',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ action_id: action_id, enabled: enabled }),
            success: function(resp) {
                console.log("Action toggled");
            },
            error: function(err) {
                safe_toast('error', window._("Failed to toggle action"));
                checkbox.checked = !enabled; // Revert
            }
        });
    }

    // Re-apply selected-day checkbox states to the rendered action list
    function seq_refresh_action_checks(widget_id) {
        var ss = seq_get_sched_state(widget_id);
        var list = document.getElementById('seq-list-' + widget_id);
        if (!list || !ss.steps) return;
        for (var i = 0; i < ss.steps.length; i++) {
            var s = ss.steps[i];
            var check = list.querySelector('.seq-square-toggle[data-id="' + s.unique_id + '"]');
            if (!check) continue;
            var eff = seq_action_enabled_for_day(ss, s.unique_id, s.enabled);
            if (document.activeElement !== check) check.checked = eff;
            var row = check.closest('.seq-list-item');
            if (row) row.classList.toggle('disabled', !eff);
        }
    }
    
    function toggle_sequence_func(function_id, checkbox) {
        if (!function_id) return;
        var state = checkbox.checked ? 'activate' : 'deactivate';
        
        $.ajax({
            url: '/sequence_func_activate_toggle/' + function_id + '/' + state,
            type: 'GET',
            success: function(resp) {
                if(resp.status === 'success') {
                    safe_toast('success', window._("Sequence") + " " + (checkbox.checked ? window._("Activated") : window._("Deactivated")));
                } else {
                    safe_toast('error', window._("Error") + ": " + (resp.error || window._("Unknown")));
                    checkbox.checked = !checkbox.checked; // Revert
                }
            },
            error: function(err) {
                safe_toast('error', window._("Failed to toggle Sequence"));
                checkbox.checked = !checkbox.checked; // Revert
            }
        });
    }

    function sequence_func_toggle_details(widget_id, btn) {
        var details = document.getElementById('seq-details-' + widget_id);
        if (!details) return;

        var isHidden = (details.style.display === 'none' || getComputedStyle(details).display === 'none');

        if (isHidden) {
            details.style.display = 'block';
            $(btn).addClass('expanded').find('.seq-expand-icon').text('▲');
            localStorage.setItem('seq_details_' + widget_id, 'show');
            $.get('/sequence_func_toggle_details/' + widget_id + '/1');
        } else {
            details.style.display = 'none';
            $(btn).removeClass('expanded').find('.seq-expand-icon').text('▼');
            localStorage.setItem('seq_details_' + widget_id, 'hide');
            $.get('/sequence_func_toggle_details/' + widget_id + '/0');
        }
    }

    // --- Per-widget schedule state ---
    // Key: widget_id → { schedule: {...}, selectedDay: int, today: int }
    if (typeof window.seqScheduleState === 'undefined') {
        window.seqScheduleState = {};
    }

    function seq_get_sched_state(widget_id) {
        if (!window.seqScheduleState[widget_id]) {
            window.seqScheduleState[widget_id] = { schedule: null, selectedDay: 0, today: 0 };
        }
        return window.seqScheduleState[widget_id];
    }

    function seq_select_day(day_idx, widget_id) {
        var ss = seq_get_sched_state(widget_id);
        ss.selectedDay = day_idx;
        seq_refresh_day_ui(widget_id);
        seq_update_cards_for_selected_day(widget_id);
        // Re-render the list immediately so group colors + durations reflect the
        // newly selected day (not just the enable checkboxes).
        seq_render_action_list(widget_id, ss.fid);
    }

    function seq_refresh_day_ui(widget_id) {
        var ss = seq_get_sched_state(widget_id);
        var sched = ss.schedule;
        var today = ss.today;
        var selected = ss.selectedDay;

        for (var d = 0; d < 7; d++) {
            var btn = document.getElementById('seq-day-btn-' + widget_id + '-' + d);
            // btn may not exist by id — find via cell
            var cell = document.getElementById('seq-day-cell-' + widget_id + '-' + d);
            if (!cell) continue;
            btn = cell.querySelector('.seq-day-btn');
            if (!btn) continue;

            btn.classList.toggle('is-today',    d === today);
            btn.classList.toggle('is-selected', d === selected);

            // Update disabled state on cell
            var entry = sched && sched.days ? sched.days[String(d)] : null;
            var enabled = entry ? entry.enabled !== false : true;
            cell.classList.toggle('is-disabled', !enabled);
            var check = cell.querySelector('.seq-day-check');
            if (check && document.activeElement !== check) check.checked = enabled;
        }
    }

    function seq_update_cards_for_selected_day(widget_id) {
        var ss = seq_get_sched_state(widget_id);
        var sched = ss.schedule;
        if (!sched) return;

        var entry;
        if (sched.mode === 'per_day') {
            entry = sched.days[String(ss.selectedDay)];
        } else {
            entry = sched.shared;
        }
        if (!entry) return;

        var startEl = document.getElementById('seq-disp-start-' + widget_id);
        var endEl   = document.getElementById('seq-disp-end-' + widget_id);
        var perEl   = document.getElementById('seq-disp-period-' + widget_id);
        if (startEl) startEl.innerText = entry.start || '--:--';
        if (endEl)   endEl.innerText   = entry.end   || '--:--';
        if (perEl)   perEl.innerText   = format_seq_time(entry.period || 3600);
    }

    function seq_set_mode(mode, widget_id, function_id) {
        var ss = seq_get_sched_state(widget_id);
        if (!ss.schedule) return;

        // Convert shared → per_day: copy shared into all days
        if (mode === 'per_day' && ss.schedule.mode === 'shared') {
            var s = ss.schedule.shared;
            for (var d = 0; d < 7; d++) {
                ss.schedule.days[String(d)].start  = s.start;
                ss.schedule.days[String(d)].end    = s.end;
                ss.schedule.days[String(d)].period = s.period;
            }
        }
        // Convert per_day → shared: pick first enabled day as representative
        if (mode === 'shared' && ss.schedule.mode === 'per_day') {
            for (var d2 = 0; d2 < 7; d2++) {
                var e = ss.schedule.days[String(d2)];
                if (e && e.enabled !== false) {
                    ss.schedule.shared.start  = e.start;
                    ss.schedule.shared.end    = e.end;
                    ss.schedule.shared.period = e.period;
                    break;
                }
            }
        }
        ss.schedule.mode = mode;
        seq_sync_schedule_to_server(widget_id, function_id, function() {
            seq_refresh_day_ui(widget_id);
            seq_update_cards_for_selected_day(widget_id);
        });

        // Toggle mode buttons
        var sharedBtn = document.getElementById('seq-mode-shared-' + widget_id);
        var perdayBtn = document.getElementById('seq-mode-perday-' + widget_id);
        if (sharedBtn) sharedBtn.classList.toggle('active', mode === 'shared');
        if (perdayBtn) perdayBtn.classList.toggle('active', mode === 'per_day');
    }

    function seq_copy_to_all(widget_id, function_id) {
        var ss = seq_get_sched_state(widget_id);
        if (!ss.schedule) return;
        var src = ss.schedule.days[String(ss.selectedDay)];
        if (!src) return;
        for (var d = 0; d < 7; d++) {
            var e = ss.schedule.days[String(d)];
            if (e) { e.start = src.start; e.end = src.end; e.period = src.period; }
        }
        seq_sync_schedule_to_server(widget_id, function_id, function() {
            seq_refresh_day_ui(widget_id);
            seq_update_cards_for_selected_day(widget_id);
            safe_toast('success', window._('Copied to all days'));
        });
    }

    function seq_sync_schedule_to_server(widget_id, function_id, onSuccess) {
        var ss = seq_get_sched_state(widget_id);
        if (!ss.schedule || !function_id) return;
        $.ajax({
            url: '/function_sequence_update_schedule',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ function_id: function_id, schedule: ss.schedule }),
            success: function(resp) {
                if (resp.status === 'success') {
                    if (resp.warnings && resp.warnings.length) {
                        safe_toast('warning', resp.warnings[0]);
                    }
                    if (onSuccess) onSuccess();
                } else {
                    var err = Array.isArray(resp.error) ? resp.error.join('; ') : (resp.error || window._('Update failed'));
                    safe_toast('error', err);
                }
            },
            error: function() { safe_toast('error', window._('Failed to save schedule')); }
        });
    }

    function seq_handle_enabled_change(checkbox, widget_id) {
        var day = parseInt(checkbox.getAttribute('data-day'), 10);
        var row = checkbox.closest('.seq-weekday-row');
        if (!row) return;
        var fid = row.getAttribute('data-fid');

        var ss = seq_get_sched_state(widget_id);
        if (ss.schedule && ss.schedule.days && ss.schedule.days[String(day)]) {
            ss.schedule.days[String(day)].enabled = checkbox.checked;
        }

        // Collect enabled days for legacy sync
        var enabledDays = [];
        for (var d = 0; d < 7; d++) {
            var entry = ss.schedule && ss.schedule.days ? ss.schedule.days[String(d)] : null;
            if (!entry || entry.enabled !== false) enabledDays.push(String(d));
        }

        $.ajax({
            url: '/sequence_update_weekday',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ function_id: fid, weekdays: enabledDays.join(',') }),
            success: function(resp) {
                if (!resp || resp.error) {
                    safe_toast('error', window._('Failed to update'));
                    // Revert
                    if (ss.schedule && ss.schedule.days && ss.schedule.days[String(day)]) {
                        ss.schedule.days[String(day)].enabled = !checkbox.checked;
                    }
                    checkbox.checked = !checkbox.checked;
                }
                seq_refresh_day_ui(widget_id);
            },
            error: function() {
                safe_toast('error', window._('Failed to update'));
                checkbox.checked = !checkbox.checked;
            }
        });
    }

    // Render the action list from cached steps for the SELECTED day. Extracted so a
    // day switch re-renders immediately (group colors + durations depend on the
    // selected day) instead of waiting for the next poll.
    function seq_render_action_list(widget_id, function_id) {
        var ss = seq_get_sched_state(widget_id);
        // A reorder drag owns the rows right now — re-rendering would wipe them
        // mid-gesture (the poll keeps running while the user drags).
        if (ss.dndActive) return;
        var steps = ss.steps || [];
        var listHtml = "";
        try {
            if (steps.length > 0) {
                var effGroupOf = function(st) {
                    return (st.type !== 'total') ? seq_action_group_for_day(ss, st.unique_id, st.group_name) : null;
                };

                // Distinct group names on the selected day (colors are stable per name).
                var groupNames = [];
                for (var gi = 0; gi < steps.length; gi++) {
                    var gn = effGroupOf(steps[gi]);
                    if (gn && groupNames.indexOf(gn) === -1) groupNames.push(gn);
                }
                ss.groupNames = groupNames;

                // Reorder so group members sit together as one contiguous block.
                var ordered = [];
                var emittedGroup = {};
                for (var oi = 0; oi < steps.length; oi++) {
                    var os = steps[oi];
                    var ogk = effGroupOf(os);
                    if (ogk) {
                        if (emittedGroup[ogk]) continue;
                        emittedGroup[ogk] = true;
                        for (var oj = oi; oj < steps.length; oj++) {
                            if (effGroupOf(steps[oj]) === ogk) ordered.push(steps[oj]);
                        }
                    } else {
                        ordered.push(os);
                    }
                }

                for (var i = 0; i < ordered.length; i++) {
                    var s = ordered[i];
                    var effEnabled = seq_action_enabled_for_day(ss, s.unique_id, s.enabled);
                    var effGroup = effGroupOf(s);
                    var inGroup = !!effGroup;
                    var groupColor = inGroup ? seq_group_color(effGroup, groupNames) : '';

                    // Position within the contiguous group block → connected background.
                    var samePrev = inGroup && i > 0 && effGroupOf(ordered[i-1]) === effGroup;
                    var sameNext = inGroup && i < ordered.length - 1 && effGroupOf(ordered[i+1]) === effGroup;
                    var grpCellCls = '';
                    if (inGroup) {
                        grpCellCls = ' seq-grp ' + ((samePrev && sameNext) ? 'seq-gm-mid'
                                        : (!samePrev && sameNext) ? 'seq-gm-first'
                                        : (samePrev && !sameNext) ? 'seq-gm-last' : 'seq-gm-single');
                    }

                    var rowClass = "seq-list-item";
                    if (s.is_active || s.is_activated) rowClass += " active";
                    if (!effEnabled) rowClass += " disabled";
                    if (sameNext) rowClass += " seq-group-cont";

                    // Device state (Model A): reflect the target output's actual
                    // state so an offline/unconfirmed device is shown as such,
                    // instead of trusting the schedule alone.
                    var devCls = (window.AoTOutputState && s.output_state !== undefined && s.output_state !== null)
                        ? window.AoTOutputState.classify(s.output_state) : null;
                    var devBadge = '';
                    if (devCls && devCls.isFault) {
                        rowClass += " seq-offline";
                        devBadge = '<span class="seq-dev-badge seq-dev-offline" title="' + window._('No response') + '">' + window._('Offline') + '</span>';
                    } else if (devCls && devCls.isPending) {
                        rowClass += " seq-pending";
                        devBadge = '<span class="seq-dev-badge seq-dev-pending" title="' + window._('Confirming') + '">' + window._('Confirming') + '</span>';
                    }

                    // Duration for the selected day (per-day override → global).
                    var baseDur = s.original_duration ? (parseInt(s.original_duration, 10) || 0)
                                 : ((s.start !== null && s.start !== undefined) ? Math.round(s.end - s.start) : 0);
                    var durationSec = seq_action_duration_for_day(ss, s.unique_id, baseDur);
                    var timeStr = format_seq_time(durationSec);

                    var isTotal = (s.type === 'total');
                    var checked = effEnabled ? "checked" : "";
                    // Reorder unit: a group is ONE block (all members move together),
                    // a standalone step is a block of its own. encodeURIComponent keeps
                    // quotes/spaces in a group name from breaking the attribute.
                    var blockKey = inGroup ? ('g:' + encodeURIComponent(effGroup)) : ('u:' + s.unique_id);
                    listHtml += '<div class="' + rowClass + '" data-uid="' + s.unique_id + '" data-block="' + blockKey + '" title="' + window._('Press and hold to reorder') + '">';
                    listHtml += '<div class="seq-col-enable"><input type="checkbox" ' + checked + ' class="seq-square-toggle" data-id="' + s.unique_id + '" onchange="toggle_seq_action(this.dataset.id, this, \\'' + widget_id + '\\', \\'' + function_id + '\\')"></div>';

                    var deviceDetail = s.device_detail || s.action_name || window._("Unknown");
                    var displayName = s.display_name || deviceDetail;
                    var nameCls = 'seq-text-name';
                    if (isTotal) nameCls += ' seq-name-total';
                    // Group tint + connection classes go on the name CELL; --gc set inline.
                    var nameCellStyle = inGroup ? ' style="--gc:' + groupColor + '"' : '';
                    listHtml += '<div class="seq-col-name seq-name-editable' + grpCellCls + '"' + nameCellStyle + ' title="' + displayName + '" data-uid="' + s.unique_id + '" data-name="' + displayName + '" data-device="' + deviceDetail + '" data-group="' + (effGroup || '') + '" data-type="' + s.type + '" data-lead="' + (s.total_lead || 0) + '" data-lag="' + (s.total_lag || 0) + '" data-wid="' + widget_id + '" data-fid="' + function_id + '" onclick="seq_open_name_modal(this)"><span class="' + nameCls + '">' + displayName + '</span>' + devBadge + '</div>';

                    var timeShown = isTotal ? window._('Total') : timeStr;
                    listHtml += '<div class="seq-col-time seq-time-editable" data-uid="' + s.unique_id + '" data-dur="' + durationSec + '" data-type="' + s.type + '" data-group="' + (effGroup || '') + '" data-name="' + displayName + '" data-wid="' + widget_id + '" data-fid="' + function_id + '" onclick="seq_open_time_modal(this)"><span class="seq-text-time">' + timeShown + '</span></div>';
                    listHtml += '</div>';
                }
            } else {
                listHtml = '<div style="padding:10px;text-align:center;color:var(--text-medium-gray, #666);">' + window._("No actions found") + '</div>';
            }
        } catch(e) {
            console.error("List render failed", e);
            listHtml = "<div>" + window._("JS Error in List") + "</div>";
        }
        var listContainer = document.getElementById('seq-list-' + widget_id);
        if (listContainer) {
            listContainer.innerHTML = listHtml;
            // The drag handler reads these at gesture time (it is bound once).
            listContainer.setAttribute('data-wid', widget_id);
            listContainer.setAttribute('data-fid', function_id || '');
            seq_attach_dnd(listContainer);
        }
    }

    // --- Drag to reorder ---------------------------------------------------
    // A step is moved by pressing its row and dragging it. A device group is
    // ONE block: grabbing any member moves every member, and a block is always
    // dropped before or after another WHOLE block, so a reorder can never split
    // a group or drop a standalone step inside one.
    //
    // The new order is persisted through /function_save_order (custom_options
    // .gridstack_y) — the same key the function options page writes, which is
    // what Actions.position, and therefore the controller's run order, reads.
    var SEQ_DND_HOLD_MS = 180;    // touch: hold this long before the row lifts
    var SEQ_DND_START_PX = 5;     // mouse: travel that turns a press into a drag
    var SEQ_DND_CANCEL_PX = 10;   // touch: travel before the hold fires = scrolling, not reordering

    // --- TEMPORARY diagnostics for the Samsung Internet drag-to-reorder bug ---
    // Add ?seqdnd_debug=1 to the dashboard URL to show a live event log at the
    // bottom of the screen while attempting the drag. Remove this block once
    // the root cause is confirmed and fixed.
    var SEQ_DND_DEBUG = (function() {
        try { return /(^|[?&])seqdnd_debug=1(&|$)/.test(window.location.search); } catch (e) { return false; }
    })();

    function seq_dnd_log(msg) {
        if (!SEQ_DND_DEBUG) return;
        var box = document.getElementById('seq-dnd-debug-box');
        if (!box) {
            box = document.createElement('div');
            box.id = 'seq-dnd-debug-box';
            box.style.cssText = 'position:fixed;left:0;right:0;bottom:0;max-height:45vh;overflow:auto;' +
                'background:rgba(0,0,0,0.88);color:#7CFC00;font:11px/1.4 monospace;padding:6px 8px;' +
                'z-index:2147483647;white-space:pre-wrap;';
            document.body.appendChild(box);
        }
        var t = new Date();
        var ts = ('0' + t.getMinutes()).slice(-2) + ':' + ('0' + t.getSeconds()).slice(-2) + '.' + ('00' + t.getMilliseconds()).slice(-3);
        var line = document.createElement('div');
        line.textContent = ts + '  ' + msg;
        box.appendChild(line);
        box.scrollTop = box.scrollHeight;
        while (box.children.length > 200) box.removeChild(box.firstChild);
    }

    if (SEQ_DND_DEBUG) {
        // Raw arrival log, independent of our own gesture logic — shows whether
        // events reach the page at all, in what order, even if seq_dnd_down /
        // seq_dnd_pointermove never run (e.g. something upstream swallows them).
        ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'touchstart', 'touchmove', 'touchend'].forEach(function(type) {
            document.addEventListener(type, function(ev) {
                var onRow = ev.target && ev.target.closest && ev.target.closest('.seq-list-item');
                seq_dnd_log('[raw] ' + type + ' ptrType=' + (ev.pointerType || '-') +
                    ' cancelable=' + ev.cancelable + ' defaultPrevented=' + ev.defaultPrevented +
                    ' onRow=' + !!onRow);
            }, true);
        });
    }

    function seq_dnd_state() {
        if (!window.__seqDnd) window.__seqDnd = { pending: null };
        return window.__seqDnd;
    }

    function seq_dnd_rows(list) {
        return Array.prototype.slice.call(list.children).filter(function(el) {
            return el.classList && el.classList.contains('seq-list-item');
        });
    }

    function seq_dnd_block_rows(list, key) {
        return seq_dnd_rows(list).filter(function(r) { return r.getAttribute('data-block') === key; });
    }

    // Bound once per list element; every render just refreshes the rows inside it.
    function seq_attach_dnd(list) {
        if (list.__seqDndBound) return;
        list.__seqDndBound = true;
        seq_dnd_log('seq_attach_dnd bound, wid=' + list.getAttribute('data-wid'));
        list.addEventListener('pointerdown', function(e) { seq_dnd_down(e, list); });
    }

    function seq_dnd_down(e, list) {
        if (e.button !== undefined && e.button !== 0) { seq_dnd_log('down: ignored, button=' + e.button); return; }
        if (!e.target || !e.target.closest) { seq_dnd_log('down: ignored, no e.target.closest'); return; }
        var row = e.target.closest('.seq-list-item');
        if (!row || !list.contains(row)) { seq_dnd_log('down: ignored, no row under target'); return; }
        // The enable checkbox keeps its own gesture.
        if (e.target.closest('input, button, select, textarea')) { seq_dnd_log('down: ignored, form control target'); return; }
        if (seq_dnd_rows(list).length < 2) { seq_dnd_log('down: ignored, <2 rows'); return; }

        seq_dnd_log('down: accepted ptrType=' + e.pointerType + ' x=' + Math.round(e.clientX) + ' y=' + Math.round(e.clientY));

        var st = seq_dnd_state();
        seq_dnd_cleanup(st);  // never keep two gestures alive at once

        var p = {
            list: list,
            row: row,
            wid: list.getAttribute('data-wid'),
            fid: list.getAttribute('data-fid'),
            key: row.getAttribute('data-block'),
            x0: e.clientX, y0: e.clientY, lastY: e.clientY,
            touch: (e.pointerType === 'touch'),
            holdTimer: null, active: false, dy: 0
        };
        st.pending = p;
        seq_dnd_log('down: p.touch=' + p.touch);

        p.onMove = function(ev) { seq_dnd_pointermove(ev); };
        p.onUp = function(ev) { seq_dnd_pointerup(ev); };
        document.addEventListener('pointermove', p.onMove, true);
        document.addEventListener('pointerup', p.onUp, true);
        document.addEventListener('pointercancel', p.onUp, true);

        if (p.touch) {
            // Suppress the native scroll from the very first touchmove, not just
            // once the hold fires: Samsung Internet commits to a scroll gesture
            // faster than Safari/Chrome do, before our hold timer below gets a
            // chance to run, so waiting until activation to preventDefault is
            // too late on that browser. seq_dnd_pointermove cancels the pending
            // drag (and removes this listener via seq_dnd_cleanup) as soon as
            // the finger travels past SEQ_DND_CANCEL_PX, so a genuine swipe
            // still scrolls normally once that happens.
            p.onTouchMove = function(ev) {
                seq_dnd_log('touchmove(early) cancelable=' + ev.cancelable + ' active=' + p.active);
                if (ev.cancelable) ev.preventDefault();
            };
            document.addEventListener('touchmove', p.onTouchMove, { passive: false });
            seq_dnd_log('down: hold timer armed, ' + SEQ_DND_HOLD_MS + 'ms');
            p.holdTimer = setTimeout(function() {
                seq_dnd_log('hold timer fired -> activate');
                seq_dnd_activate(p);
            }, SEQ_DND_HOLD_MS);
        } else {
            seq_dnd_log('down: not touch -> no hold timer armed, no scroll suppression');
        }
    }

    function seq_dnd_activate(p) {
        if (p.active) return;
        seq_dnd_log('activate: rows lifted, key=' + p.key);
        p.active = true;
        p.startY = p.lastY;
        p.rows = seq_dnd_block_rows(p.list, p.key);
        if (!p.rows.length) p.rows = [p.row];
        p.order0 = seq_dnd_rows(p.list).map(function(r) { return r.getAttribute('data-uid'); });
        p.list.classList.add('seq-dnd-on');
        for (var i = 0; i < p.rows.length; i++) p.rows[i].classList.add('seq-row-drag');
        // Freeze the list: a poll landing mid-drag must not re-render the rows.
        seq_get_sched_state(p.wid).dndActive = true;
        // Touch's non-passive scroll suppression is already attached in
        // seq_dnd_down; mouse drags never trigger native touch scrolling.
    }

    function seq_dnd_pointermove(ev) {
        var p = seq_dnd_state().pending;
        if (!p) return;
        p.lastY = ev.clientY;
        if (!p.active) {
            var dist = Math.abs(ev.clientY - p.y0) + Math.abs(ev.clientX - p.x0);
            seq_dnd_log('move(pending) dist=' + Math.round(dist) + ' touch=' + p.touch);
            if (p.touch) {
                // Moved before the hold fired → the user is scrolling the list.
                if (dist > SEQ_DND_CANCEL_PX) { seq_dnd_log('CANCEL_PX exceeded before hold -> cleanup'); seq_dnd_cleanup(seq_dnd_state()); }
            } else if (dist > SEQ_DND_START_PX) {
                seq_dnd_activate(p);
            }
            return;
        }
        if (ev.cancelable) ev.preventDefault();
        seq_dnd_apply_offset(p, ev.clientY - p.startY);
        seq_dnd_autoscroll(p, ev.clientY);
        seq_dnd_maybe_move(p, ev.clientX, ev.clientY);
    }

    function seq_dnd_apply_offset(p, dy) {
        p.dy = dy;
        for (var i = 0; i < p.rows.length; i++) p.rows[i].style.transform = 'translateY(' + dy + 'px)';
    }

    function seq_dnd_autoscroll(p, y) {
        var r = p.list.getBoundingClientRect();
        if (y < r.top + 28) p.list.scrollTop -= 10;
        else if (y > r.bottom - 28) p.list.scrollTop += 10;
    }

    function seq_dnd_maybe_move(p, x, y) {
        // The dragged rows are pointer-events:none, so this is the row beneath them.
        var el = document.elementFromPoint(x, y);
        var over = el && el.closest ? el.closest('.seq-list-item') : null;
        if (!over || !p.list.contains(over)) return;
        if (over.getAttribute('data-block') === p.key) return;
        var rect = over.getBoundingClientRect();
        seq_dnd_place(p, over, y > rect.top + rect.height / 2);
    }

    function seq_dnd_place(p, targetRow, after) {
        var tRows = seq_dnd_block_rows(p.list, targetRow.getAttribute('data-block'));
        if (!tRows.length) return;
        // Always land before or after the WHOLE target block, never inside it.
        var anchor = after ? tRows[tRows.length - 1].nextSibling : tRows[0];
        if (anchor === p.rows[0]) return;  // already in that slot
        var top0 = p.rows[0].getBoundingClientRect().top;
        for (var i = 0; i < p.rows.length; i++) p.list.insertBefore(p.rows[i], anchor);
        var shift = p.rows[0].getBoundingClientRect().top - top0;
        // Keep the block visually still across the swap: the layout shift it just
        // took is subtracted from the drag offset, so it does not jump under the finger.
        p.startY += shift;
        seq_dnd_apply_offset(p, p.dy - shift);
    }

    function seq_dnd_cleanup(st) {
        var p = st.pending;
        if (!p) return;
        seq_dnd_log('cleanup, wasActive=' + p.active);
        if (p.holdTimer) clearTimeout(p.holdTimer);
        document.removeEventListener('pointermove', p.onMove, true);
        document.removeEventListener('pointerup', p.onUp, true);
        document.removeEventListener('pointercancel', p.onUp, true);
        if (p.onTouchMove) document.removeEventListener('touchmove', p.onTouchMove, { passive: false });
        if (p.rows) {
            for (var i = 0; i < p.rows.length; i++) {
                p.rows[i].classList.remove('seq-row-drag');
                p.rows[i].style.transform = '';
            }
        }
        p.list.classList.remove('seq-dnd-on');
        seq_get_sched_state(p.wid).dndActive = false;
        st.pending = null;
    }

    function seq_dnd_pointerup(ev) {
        var st = seq_dnd_state();
        var p = st.pending;
        if (!p) return;
        seq_dnd_log('up/cancel: type=' + (ev && ev.type) + ' wasActive=' + p.active);
        var wasActive = p.active;
        var wid = p.wid, fid = p.fid, order0 = p.order0 || [];
        var order = wasActive ? seq_dnd_rows(p.list).map(function(r) { return r.getAttribute('data-uid'); }) : null;
        seq_dnd_cleanup(st);
        if (!wasActive) return;
        // A drag must not also open the name/time modal of the cell it ended on.
        seq_dnd_swallow_click();
        if (order.join(',') === order0.join(',')) {
            seq_render_action_list(wid, fid);  // unchanged: just redraw clean rows
            return;
        }
        seq_dnd_save_order(wid, fid, order);
    }

    function seq_dnd_swallow_click() {
        var kill = function(ev) { ev.stopPropagation(); ev.preventDefault(); };
        document.addEventListener('click', kill, true);
        setTimeout(function() { document.removeEventListener('click', kill, true); }, 0);
    }

    function seq_dnd_save_order(widget_id, function_id, order) {
        var ss = seq_get_sched_state(widget_id);
        var map = {};
        for (var i = 0; i < order.length; i++) map[order[i]] = i;
        // Hold the new order locally for a few seconds: a poll answered before the
        // daemon has picked up the change would otherwise snap the list back.
        ss.localOrder = order.slice();
        ss.localOrderUntil = Date.now() + 15000;
        seq_apply_local_order(ss);
        $.ajax({
            url: '/function_save_order', type: 'POST', contentType: 'application/json',
            data: JSON.stringify({ function_id: function_id, order: map }),
            success: function(resp) {
                if (resp && resp.status === 'success') {
                    safe_toast('success', window._('Updated'));
                } else {
                    ss.localOrder = null;
                    safe_toast('error', window._('Update failed'));
                }
                update_sequence_widget(function_id, widget_id, null);
            },
            error: function() {
                ss.localOrder = null;
                safe_toast('error', window._('Update failed'));
                update_sequence_widget(function_id, widget_id, null);
            }
        });
    }

    // Apply the order just saved from a drag to freshly polled steps, until the
    // server's own order catches up (or the step set changes, which means the
    // sequence was edited elsewhere and the server is the authority again).
    function seq_apply_local_order(ss) {
        var lo = ss.localOrder;
        if (!lo || !lo.length) return;
        if (Date.now() > (ss.localOrderUntil || 0)) { ss.localOrder = null; return; }
        var steps = ss.steps || [];
        if (steps.length !== lo.length) { ss.localOrder = null; return; }
        var idx = {};
        for (var i = 0; i < lo.length; i++) idx[lo[i]] = i;
        for (var j = 0; j < steps.length; j++) {
            if (!Object.prototype.hasOwnProperty.call(idx, steps[j].unique_id)) { ss.localOrder = null; return; }
        }
        steps.sort(function(a, b) { return idx[a.unique_id] - idx[b.unique_id]; });
    }

    function update_sequence_widget(function_id, widget_id, default_period) {
        if (!function_id) return;

        $.getJSON('/function_status_activated/' + function_id, function(data) {
            if (data.error) {
                var display = document.getElementById('seq-timer-' + widget_id);
                if (display) display.innerText = "00:00:00 / " + format_seq_time(default_period || 0);
                return;
            }

            // Store / update schedule state
            var ss = seq_get_sched_state(widget_id);
            var serverToday = (data.today !== undefined && data.today !== null) ? parseInt(data.today, 10) : 0;
            ss.today = serverToday;

            if (data.schedule) {
                ss.schedule = data.schedule;
                // On first load, default selection to today (from server, device tz)
                if (!ss._initDone) {
                    ss.selectedDay = serverToday;
                    ss._initDone = true;
                }
            }

            // Sync mode buttons
            if (data.schedule) {
                var mode = data.schedule.mode || 'shared';
                var sharedBtn = document.getElementById('seq-mode-shared-' + widget_id);
                var perdayBtn = document.getElementById('seq-mode-perday-' + widget_id);
                if (sharedBtn) sharedBtn.classList.toggle('active', mode === 'shared');
                if (perdayBtn) perdayBtn.classList.toggle('active', mode === 'per_day');
            }

            // Refresh day buttons + hints
            seq_refresh_day_ui(widget_id);

            // Update time cards for selected day
            seq_update_cards_for_selected_day(widget_id);

            // Timer state
            if (!window.seqWidgetState[widget_id]) window.seqWidgetState[widget_id] = {};
            var state = window.seqWidgetState[widget_id];
            state.period = data.period || 3600;
            state.is_active = data.is_activated;
            state.cycle_start_ts = (data.cycle_start_time > 0) ? data.cycle_start_time : 0;
            try { update_local_timer(widget_id); } catch(e) {}

            // Toggle
            var mainToggle = document.getElementById('seq-main-toggle-' + widget_id);
            if (mainToggle && document.activeElement !== mainToggle) mainToggle.checked = data.is_activated;

            // Cache steps + fid, then render the list for the selected day.
            ss.steps = data.steps || [];
            ss.fid = function_id;
            seq_apply_local_order(ss);  // keep a just-dragged order until the server agrees
            seq_render_action_list(widget_id, function_id);
        });
    }

    function seq_open_setting_wheel(card) {
        if (typeof window.AoTTimeWheel === 'undefined') {
            safe_toast('error', window._('Time wheel not loaded'));
            return;
        }
        var field = card.getAttribute('data-field');
        var fid   = card.getAttribute('data-fid');
        var wid   = card.getAttribute('data-wid');
        var valueEl = card.querySelector('.seq-info-value');
        var currentText = valueEl ? valueEl.innerText : '0';

        var isHm = (field === 'start_time' || field === 'end_time');
        var currentSec = AoTTimeWheel.toSeconds(currentText);
        // The wheel's hour drum is 0-23, so 24:00 cannot be picked directly.
        // For end time, 00:00 on the wheel means 24:00 (end of day).
        if (field === 'end_time' && currentSec >= 86400) currentSec = 0;
        var maxSec = isHm ? 86340 : 86399;
        var titles = { start_time: window._('Start'), end_time: window._('End'), period: window._('Period') };

        AoTTimeWheel.open({
            title: titles[field] || field,
            value: currentSec,
            max: maxSec,
            fields: isHm ? 'hm' : 'hms',
            onConfirm: function(totalSeconds, display) {
                if (field === 'end_time' && totalSeconds === 0) {
                    totalSeconds = 86400;
                    display = '24:00';
                }
                var ss = seq_get_sched_state(wid);
                var sched = ss.schedule;

                if (sched && sched.mode === 'per_day') {
                    // per_day: update selected day in schedule and push full schedule
                    var dayKey = String(ss.selectedDay);
                    if (!sched.days[dayKey]) return;
                    if (field === 'start_time')      sched.days[dayKey].start  = display;
                    else if (field === 'end_time')   sched.days[dayKey].end    = display;
                    else                             sched.days[dayKey].period = totalSeconds;
                    seq_sync_schedule_to_server(wid, fid, function() {
                        safe_toast('success', window._('Updated'));
                        update_sequence_widget(fid, wid, null);
                    });
                } else {
                    // shared mode: use legacy endpoint (also syncs schedule JSON server-side)
                    var payload = { function_id: fid };
                    if (field === 'start_time')      payload.start_time = display;
                    else if (field === 'end_time')   payload.end_time = display;
                    else                             payload.period = totalSeconds;

                    $.ajax({
                        url: '/function_sequence_update_settings',
                        type: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify(payload),
                        success: function(resp) {
                            if (resp.status === 'success') {
                                safe_toast('success', window._('Updated'));
                                update_sequence_widget(fid, wid, null);
                            } else {
                                safe_toast('error', resp.error || window._('Update failed'));
                            }
                        },
                        error: function() { safe_toast('error', window._('Failed to update')); }
                    });
                }
            }
        });
    }

    function seq_open_duration_wheel(action_id, current_seconds, widget_id, function_id) {
        if (typeof window.AoTTimeWheel === 'undefined') {
            safe_toast('error', window._('Time wheel not loaded'));
            return;
        }
        AoTTimeWheel.open({
            title: window._('Duration'),
            value: current_seconds || 0,
            max: 86399,
            fields: 'hms',
            onConfirm: function(totalSeconds) {
                $.ajax({
                    url: '/function_sequence_update_action_duration',
                    type: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ action_id: action_id, duration: totalSeconds }),
                    success: function(resp) {
                        if (resp.status === 'success') {
                            safe_toast('success', window._('Duration updated'));
                            update_sequence_widget(function_id, widget_id, null);
                        } else {
                            safe_toast('error', resp.error || window._('Update failed'));
                        }
                    },
                    error: function() {
                        safe_toast('error', window._('Failed to update duration'));
                    }
                });
            }
        });
    }

    // --- Type Picker (same backdrop pattern as time-wheel) ---
    // The backdrop is a singleton: created once and reused
    var _seqTypeBackdrop = null;

    function seq_ensure_type_backdrop() {
        if (_seqTypeBackdrop && document.body.contains(_seqTypeBackdrop)) {
            return _seqTypeBackdrop;
        }
        var bd = document.createElement('div');
        bd.className = 'seq-type-backdrop';
        bd.innerHTML =
            '<div class="seq-type-panel">' +
                '<div class="seq-type-panel-title"></div>' +
                '<div class="seq-type-options"></div>' +
                '<div class="seq-type-cancel-row">' +
                    '<button type="button" class="btn aot-pill-btn seq-type-cancel-btn"></button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(bd);
        bd.addEventListener('click', function(e) {
            if (e.target === bd) { seq_close_type_picker(); }
        });
        bd.querySelector('.seq-type-cancel-btn').addEventListener('click', function() {
            seq_close_type_picker();
        });
        _seqTypeBackdrop = bd;
        return bd;
    }

    function seq_close_type_picker() {
        if (_seqTypeBackdrop) {
            _seqTypeBackdrop.classList.remove('is-open');
        }
    }

    function seq_open_type_picker(event, cell) {
        event.stopPropagation();

        var uid = cell.getAttribute('data-uid');
        var currentType = cell.getAttribute('data-type') || 'single';
        var wid = cell.getAttribute('data-wid');
        var fid = cell.getAttribute('data-fid');

        var bd = seq_ensure_type_backdrop();
        var title = bd.querySelector('.seq-type-panel-title');
        var optionsBox = bd.querySelector('.seq-type-options');
        var cancelBtn = bd.querySelector('.seq-type-cancel-btn');

        title.textContent = window._('Output Type');
        cancelBtn.textContent = window._('Cancel');

        // Regenerate option buttons
        optionsBox.innerHTML = '';
        var types = [
            { value: 'single', label: window._('SINGLE') },
            { value: 'total',  label: window._('TOTAL') }
        ];
        for (var i = 0; i < types.length; i++) {
            (function(t) {
                var btn = document.createElement('button');
                btn.type = 'button';
                var isSelected = (t.value === currentType);
                btn.className = 'btn aot-pill-btn' + (isSelected ? ' aot-pill-btn-primary' : '');
                btn.textContent = t.label;
                btn.addEventListener('click', function() {
                    if (t.value === currentType) {
                        seq_close_type_picker();
                        return;
                    }
                    $.ajax({
                        url: '/function_sequence_update_action_type',
                        type: 'POST',
                        contentType: 'application/json',
                        data: JSON.stringify({ action_id: uid, seq_type: t.value }),
                        success: function(resp) {
                            if (resp.status === 'success') {
                                safe_toast('success', window._('Updated'));
                                update_sequence_widget(fid, wid, null);
                            } else {
                                safe_toast('error', resp.error || window._('Update failed'));
                            }
                        },
                        error: function() {
                            safe_toast('error', window._('Failed to update'));
                        }
                    });
                    seq_close_type_picker();
                });
                optionsBox.appendChild(btn);
            })(types[i]);
        }

        bd.classList.add('is-open');
    }

    // --- Group Picker (assign / change / clear a step's device group) ---
    var _seqGroupBackdrop = null;

    function seq_ensure_group_backdrop() {
        if (_seqGroupBackdrop && document.body.contains(_seqGroupBackdrop)) {
            return _seqGroupBackdrop;
        }
        var bd = document.createElement('div');
        bd.className = 'seq-type-backdrop seq-group-modal';
        bd.innerHTML =
            '<div class="seq-type-panel">' +
                '<div class="seq-type-panel-title"></div>' +
                '<div class="seq-type-options"></div>' +
                '<div class="seq-group-new-row">' +
                    '<input type="text" class="seq-group-new-input" maxlength="24">' +
                    '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary seq-group-new-btn"></button>' +
                '</div>' +
                '<div class="seq-type-cancel-row">' +
                    '<button type="button" class="btn aot-pill-btn seq-type-cancel-btn"></button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(bd);
        bd.addEventListener('click', function(e) {
            if (e.target === bd) { seq_close_group_picker(); }
        });
        bd.querySelector('.seq-type-cancel-btn').addEventListener('click', function() {
            seq_close_group_picker();
        });
        _seqGroupBackdrop = bd;
        return bd;
    }

    function seq_close_group_picker() {
        if (_seqGroupBackdrop) {
            _seqGroupBackdrop.classList.remove('is-open');
        }
    }

    function seq_set_action_group(uid, groupName, wid, fid) {
        $.ajax({
            url: '/function_sequence_set_group',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ action_id: uid, group_name: groupName }),
            success: function(resp) {
                if (resp.status === 'success') {
                    safe_toast('success', window._('Updated'));
                    seq_close_group_picker();
                    update_sequence_widget(fid, wid, null);
                } else {
                    safe_toast('error', resp.error || window._('Update failed'));
                }
            },
            error: function() { safe_toast('error', window._('Update failed')); }
        });
    }

    function seq_open_group_picker(event, cell) {
        event.stopPropagation();

        var uid = cell.getAttribute('data-uid');
        var currentGroup = cell.getAttribute('data-group') || '';
        var wid = cell.getAttribute('data-wid');
        var fid = cell.getAttribute('data-fid');
        var ss = seq_get_sched_state(wid);
        var groups = ss.groupNames || [];

        var bd = seq_ensure_group_backdrop();
        var title = bd.querySelector('.seq-type-panel-title');
        var optionsBox = bd.querySelector('.seq-type-options');
        var newInput = bd.querySelector('.seq-group-new-input');
        var newBtn = bd.querySelector('.seq-group-new-btn');
        var cancelBtn = bd.querySelector('.seq-type-cancel-btn');

        title.textContent = window._('Select Group');
        cancelBtn.textContent = window._('Cancel');
        newBtn.textContent = window._('Create group');
        newInput.value = '';
        newInput.placeholder = window._('New group name');

        optionsBox.innerHTML = '';

        // "No group" option (release from any group)
        var noneBtn = document.createElement('button');
        noneBtn.type = 'button';
        noneBtn.className = 'btn aot-pill-btn' + (!currentGroup ? ' aot-pill-btn-primary' : '');
        noneBtn.textContent = window._('No group');
        noneBtn.addEventListener('click', function() {
            if (!currentGroup) { seq_close_group_picker(); return; }
            seq_set_action_group(uid, '', wid, fid);
        });
        optionsBox.appendChild(noneBtn);

        // Existing groups in this sequence (each prefixed with its color dot)
        for (var i = 0; i < groups.length; i++) {
            (function(name) {
                var btn = document.createElement('button');
                btn.type = 'button';
                var isSel = (name === currentGroup);
                btn.className = 'btn aot-pill-btn' + (isSel ? ' aot-pill-btn-primary' : '');
                var dot = document.createElement('span');
                dot.className = 'seq-group-opt-dot';
                dot.style.background = seq_group_color(name, groups);
                btn.appendChild(dot);
                btn.appendChild(document.createTextNode(name));
                btn.addEventListener('click', function() {
                    if (isSel) { seq_close_group_picker(); return; }
                    seq_set_action_group(uid, name, wid, fid);
                });
                optionsBox.appendChild(btn);
            })(groups[i]);
        }

        // Create a new group from the text input
        var doCreate = function() {
            var val = (newInput.value || '').trim();
            if (!val) { newInput.focus(); return; }
            seq_set_action_group(uid, val, wid, fid);
        };
        newBtn.onclick = doCreate;
        newInput.onkeydown = function(e) { if (e.key === 'Enter') { e.preventDefault(); doCreate(); } };

        bd.classList.add('is-open');
    }

    // --- Step settings modals (name/group/type, and time) share one backdrop ---
    var _seqStepBackdrop = null;

    function seq_ensure_step_backdrop() {
        if (_seqStepBackdrop && document.body.contains(_seqStepBackdrop)) return _seqStepBackdrop;
        var bd = document.createElement('div');
        bd.className = 'seq-type-backdrop seq-step-modal';
        bd.innerHTML =
            '<div class="seq-type-panel">' +
                '<div class="seq-type-panel-title"></div>' +
                '<div class="seq-step-content"></div>' +
                '<div class="seq-type-cancel-row">' +
                    '<button type="button" class="btn aot-pill-btn seq-step-cancel"></button>' +
                    '<button type="button" class="btn aot-pill-btn aot-pill-btn-primary seq-step-save"></button>' +
                '</div>' +
            '</div>';
        document.body.appendChild(bd);
        bd.addEventListener('click', function(e){ if (e.target === bd) seq_close_step_modal(); });
        bd.querySelector('.seq-step-cancel').addEventListener('click', seq_close_step_modal);
        _seqStepBackdrop = bd;
        return bd;
    }

    function seq_close_step_modal() { if (_seqStepBackdrop) _seqStepBackdrop.classList.remove('is-open'); }

    // Time cell → a modal with only the operation-duration wheel.
    function seq_open_time_modal(cell) {
        var uid = cell.getAttribute('data-uid');
        var origDur = parseInt(cell.getAttribute('data-dur'), 10) || 0;
        var isTotal = (cell.getAttribute('data-type') === 'total');
        var name = cell.getAttribute('data-name') || '';
        var effGroup = cell.getAttribute('data-group') || '';
        var wid = cell.getAttribute('data-wid'), fid = cell.getAttribute('data-fid');

        var bd = seq_ensure_step_backdrop();
        bd.querySelector('.seq-type-panel-title').textContent = name || window._('Time');
        bd.querySelector('.seq-step-cancel').textContent = window._('Cancel');
        var saveBtn = bd.querySelector('.seq-step-save');
        saveBtn.textContent = window._('Save');
        var content = bd.querySelector('.seq-step-content');
        content.innerHTML = '<div class="seq-step-section"><div class="seq-step-label">' + window._('Time') + '</div><div class="seq-step-time-body"></div></div>';
        var timeBody = content.querySelector('.seq-step-time-body');

        var wheel = null;
        if (isTotal) {
            timeBody.innerHTML = '<div class="seq-step-note">' + window._('Runs the whole sequence') + '</div>';
        } else if (typeof window.AoTTimeWheel !== 'undefined' && AoTTimeWheel.mount) {
            wheel = AoTTimeWheel.mount(timeBody, { value: origDur, max: 86399, fields: 'hms' });
        } else {
            timeBody.innerHTML = '<div class="seq-step-note">' + window._('Time wheel not loaded') + '</div>';
        }

        saveBtn.onclick = function() {
            if (isTotal || !wheel) { seq_close_step_modal(); return; }
            var newDur = wheel.read();
            if (newDur === origDur) { seq_close_step_modal(); return; }
            var ss = seq_get_sched_state(wid);
            if (seq_is_per_day(ss)) {
                // per_day mode: write the selected day's duration override + group sync
                seq_set_day_duration(ss, uid, newDur, effGroup, ss.steps || []);
                seq_sync_schedule_to_server(wid, fid, function(){ safe_toast('success', window._('Updated')); seq_close_step_modal(); update_sequence_widget(fid, wid, null); });
            } else {
                $.ajax({ url: '/function_sequence_update_action_duration', type: 'POST', contentType: 'application/json',
                    data: JSON.stringify({ action_id: uid, duration: newDur }),
                    success: function(){ safe_toast('success', window._('Updated')); seq_close_step_modal(); update_sequence_widget(fid, wid, null); },
                    error: function(){ safe_toast('error', window._('Update failed')); } });
            }
        };
        bd.classList.add('is-open');
    }

    // Name cell → a modal with display name + type + group.
    function seq_open_name_modal(cell) {
        var uid = cell.getAttribute('data-uid');
        var origName = cell.getAttribute('data-name') || '';
        var deviceDetail = cell.getAttribute('data-device') || '';
        var origGroup = cell.getAttribute('data-group') || '';
        var origType = cell.getAttribute('data-type') || 'single';
        var wid = cell.getAttribute('data-wid'), fid = cell.getAttribute('data-fid');
        var ss = seq_get_sched_state(wid);
        var groups = ss.groupNames || [];

        var bd = seq_ensure_step_backdrop();
        bd.querySelector('.seq-type-panel-title').textContent = window._('Settings');
        bd.querySelector('.seq-step-cancel').textContent = window._('Cancel');
        var saveBtn = bd.querySelector('.seq-step-save');
        saveBtn.textContent = window._('Save');
        var content = bd.querySelector('.seq-step-content');
        content.innerHTML =
            '<div class="seq-step-section"><div class="seq-step-label">' + window._('Name') + '</div>' +
                '<div class="seq-step-name-body"><input type="text" class="seq-step-name-input" maxlength="40"></div></div>' +
            '<div class="seq-step-section"><div class="seq-step-label">' + window._('Type') + '</div>' +
                '<div class="seq-step-type-body"></div></div>' +
            '<div class="seq-step-section seq-step-group-sec"><div class="seq-step-label">' + window._('Group') + '</div>' +
                '<div class="seq-step-group-body"></div>' +
                '<div class="seq-step-newrow"><input type="text" class="seq-step-new-input" maxlength="24"></div></div>' +
            '<div class="seq-step-section seq-step-margin-sec"><div class="seq-step-label">' + window._('Margins (seconds)') + '</div>' +
                '<div class="seq-step-newrow"><input type="number" min="0" class="seq-step-lead-input" placeholder="' + window._('Lead') + '" title="' + window._('Start this many seconds after the sequence begins') + '">' +
                '<input type="number" min="0" class="seq-step-lag-input" placeholder="' + window._('Lag') + '" title="' + window._('Stop this many seconds before the sequence ends') + '"></div></div>';

        // Name (display name; blank falls back to the device name)
        var nameInput = content.querySelector('.seq-step-name-input');
        nameInput.value = (origName && origName !== deviceDetail) ? origName : '';
        nameInput.placeholder = deviceDetail || window._('Name');

        var groupSec = content.querySelector('.seq-step-group-sec');
        // Margins are the mirror of the group section: they only mean something
        // for a total step (a pump held inside its valves' window).
        var marginSec = content.querySelector('.seq-step-margin-sec');
        var leadInput = content.querySelector('.seq-step-lead-input');
        var lagInput = content.querySelector('.seq-step-lag-input');
        leadInput.value = parseFloat(cell.getAttribute('data-lead') || 0) || '';
        lagInput.value = parseFloat(cell.getAttribute('data-lag') || 0) || '';

        // Type toggle (single / total); total hides the group section
        var typeBody = content.querySelector('.seq-step-type-body');
        var selectedType = (origType === 'total') ? 'total' : 'single';
        var syncTypeSections = function() {
            groupSec.style.display = (selectedType === 'total') ? 'none' : '';
            marginSec.style.display = (selectedType === 'total') ? '' : 'none';
        };
        var renderType = function() {
            typeBody.innerHTML = '';
            [['single', window._('Single')], ['total', window._('Total')]].forEach(function(pair) {
                var btn = document.createElement('button'); btn.type = 'button';
                btn.className = 'btn aot-pill-btn' + (pair[0] === selectedType ? ' aot-pill-btn-primary' : '');
                btn.textContent = pair[1];
                btn.addEventListener('click', function(){ selectedType = pair[0]; renderType(); syncTypeSections(); });
                typeBody.appendChild(btn);
            });
        };
        renderType();

        // Group options
        var groupBody = content.querySelector('.seq-step-group-body');
        var newInput = content.querySelector('.seq-step-new-input');
        newInput.placeholder = window._('New group name');
        var selectedGroup = origGroup;
        var renderGroups = function() {
            groupBody.innerHTML = '';
            var typing = !!newInput.value.trim();
            var mk = function(label, val, color) {
                var btn = document.createElement('button'); btn.type = 'button';
                var sel = (val === selectedGroup) && !typing;
                btn.className = 'btn aot-pill-btn' + (sel ? ' aot-pill-btn-primary' : '');
                if (color) { var dot = document.createElement('span'); dot.className = 'seq-group-opt-dot'; dot.style.background = color; btn.appendChild(dot); }
                btn.appendChild(document.createTextNode(label));
                btn.addEventListener('click', function(){ selectedGroup = val; newInput.value = ''; renderGroups(); });
                groupBody.appendChild(btn);
            };
            mk(window._('No group'), '', null);
            for (var i = 0; i < groups.length; i++) mk(groups[i], groups[i], seq_group_color(groups[i], groups));
        };
        renderGroups();
        newInput.oninput = renderGroups;
        syncTypeSections();

        saveBtn.onclick = function() {
            var displayName = nameInput.value.trim();
            var finalGroup = (selectedType === 'total') ? '' : (newInput.value.trim() || selectedGroup);
            var ss = seq_get_sched_state(wid);
            var perDay = seq_is_per_day(ss);
            // display_name + type are always global; group is global in shared mode,
            // per-day in per_day mode (so it's omitted from update_step there).
            var payload = { action_id: uid, display_name: displayName, sequence_mode: selectedType };
            if (!perDay) payload.group_name = finalGroup;
            if (selectedType === 'total') {
                payload.total_lead = parseFloat(leadInput.value) || 0;
                payload.total_lag = parseFloat(lagInput.value) || 0;
            }
            $.ajax({ url: '/function_sequence_update_step', type: 'POST', contentType: 'application/json',
                data: JSON.stringify(payload),
                success: function(){
                    if (perDay) {
                        seq_set_day_group(ss, uid, (selectedType === 'total') ? '' : finalGroup, ss.steps || []);
                        seq_sync_schedule_to_server(wid, fid, function(){ safe_toast('success', window._('Updated')); seq_close_step_modal(); update_sequence_widget(fid, wid, null); });
                    } else {
                        safe_toast('success', window._('Updated')); seq_close_step_modal(); update_sequence_widget(fid, wid, null);
                    }
                },
                error: function(){ safe_toast('error', window._('Update failed')); } });
        };
        bd.classList.add('is-open');
    }

    function repeat_update_seq_widget(function_id, widget_id, period_sec, default_period) {
        if(!period_sec) period_sec = 5;
        update_sequence_widget(function_id, widget_id, default_period);

        // Store intervals per widget and clear any previous ones so a live-preview
        // re-init doesn't stack duplicate data-refresh / 1s-timer intervals.
        window._seq_intervals = window._seq_intervals || {};
        var _kData = widget_id + '_data', _kTick = widget_id + '_tick';
        if (window._seq_intervals[_kData]) { clearInterval(window._seq_intervals[_kData]); }
        if (window._seq_intervals[_kTick]) { clearInterval(window._seq_intervals[_kTick]); }

        // Data Refresh Interval
        window._seq_intervals[_kData] = setInterval(function() {
            update_sequence_widget(function_id, widget_id, default_period);
        }, period_sec * 1000);

        // Local Timer Interval (1s)
        window._seq_intervals[_kTick] = setInterval(function() {
             update_local_timer(widget_id);
        }, 1000);
    }
    """,

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
      repeat_update_seq_widget('{{widget_options['function_id']}}', '{{each_widget.unique_id}}', {{widget_options.get('refresh_seconds', 5)}}, {{widget_options.get('sequence_period', 3600)}});
    """
}
