# coding=utf-8
import logging
import json
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.databases.models import Trigger
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

from flask import jsonify, request
from flask_login import current_user
from aot.aot_client import DaemonControl
from aot.aot_flask.utils.utils_general import user_has_permission

def sequence_activate_toggle(unique_id, state):
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

def execute_at_modification(mod_widget, request_form, custom_options_presave, custom_options_postsave):
    """
    Synchronize settings between Widget Options and the Sequence Function (Trigger).
    Smart Sync: 
      - If Function ID changed: PULL all settings from Function.
      - If Function ID same:
        - If User modified value in Form: PUSH to Function.
        - If User did NOT modify value: PULL from Function (Update Widget).
    """
    options = {}
    try:
        if mod_widget.custom_options:
            options = json.loads(mod_widget.custom_options) if isinstance(mod_widget.custom_options, str) else dict(mod_widget.custom_options)
    except: pass

    final_options = options.copy()
    
    # 1. Merge submitted options
    if custom_options_postsave:
        for k, v in custom_options_postsave.items():
            final_options[k] = v

    # 2. Sync Logic
    func_id = final_options.get('function_id')
    old_func_id = options.get('function_id')
    
    if func_id:
        trigger = db_retrieve_table_daemon(Trigger, unique_id=func_id)
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

                smart_sync_field('timer_start_time', 'timer_start_time', str, str)
                smart_sync_field('timer_end_time', 'timer_end_time', str, str)
                smart_sync_field('sequence_period', 'period', float, float)
                smart_sync_field('timer_start_offset', 'timer_start_offset', int, int)
                smart_sync_field('output_duration', 'output_duration', float, float)
                smart_sync_field('time_offset_minutes', 'time_offset_minutes', int, int)
                
                if updates_to_push:
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
    'widget_name': 'Sequence Controller',
    'widget_library': '',
    'no_class': True,
    'message': 'Control and Monitor a Sequence Function.',
    'widget_width': 20,
    'widget_height': 20,
    'execute_at_modification': execute_at_modification,
    
    'endpoints': [
        ("/sequence_activate_toggle/<unique_id>/<state>", "sequence_activate_toggle", sequence_activate_toggle, ["GET"])
    ],

    'custom_options': [
        {
            'id': 'function_id',
            'type': 'select_device',
            'default_value': '',
            'options_select': ['Trigger'],
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
    <style>
        .seq-step-row {
            display: flex;
            align-items: center;
            padding: 8px 5px;
            border-bottom: 1px solid rgba(0,0,0,0.1);
            font-size: 1em; /* Requested 1em */
            color: var(--dark, #333); /* Requested var(--dark) */
        }
        .seq-step-row:last-child {
            border-bottom: none;
        }
        .seq-step-row.active {
            background-color: rgba(40, 167, 69, 0.25) !important;
            border-left: 4px solid #28a745 !important;
            color: #155724 !important;
        }
        .seq-step-row.disabled {
            opacity: 0.5;
            background-color: #f9f9f9;
        }
        
        .seq-col-type {
            width: 60px;
            font-size: 0.8em;
            color: #888;
            font-weight: normal; /* Removed bold */
            text-transform: uppercase;
        }
        .seq-col-action {
            width: 30%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 0 10px;
            font-weight: normal; /* Removed 600 */
        }
        .seq-col-device {
            flex-grow: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 0 10px;
            color: #666;
            font-size: 0.9em;
            font-weight: normal;
        }
        .seq-col-time {
            width: 70px;
            text-align: right;
            font-size: 0.9em;
            color: #555;
            margin-right: 15px;
            font-family: monospace;
            font-weight: normal;
        }
        .seq-col-toggle {
            width: 70px;
            display: flex;
            justify-content: flex-end;
        }

        /* Info Grid */
        .seq-info-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1px;
            margin-bottom: 5px;
            background: rgba(0,0,0,0.1);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid rgba(0,0,0,0.1);
        }
        .seq-info-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 8px 5px;
            background: rgba(255,255,255,0.5);
        }
        .seq-info-label {
            font-size: 0.7em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 3px;
            font-weight: normal;
        }
        .seq-info-val {
            font-size: 1.1em;
            font-weight: normal; /* Removed bold */
            color: var(--dark, #000);
        }
        
        /* Header Toggle Container */
        .seq-header-toggle-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding: 0 5px;
        }
        .seq-header-timer {
            font-weight: normal; /* Removed bold */
            color: var(--dark, #333);
            font-size: 1.2em;
            font-family: monospace;
        }
    </style>
    """,

    'widget_dashboard_title_bar': """<span id="seq-title-{{each_widget.unique_id}}">{{each_widget.name}}</span>""",

    'widget_dashboard_body': """
    <div id="seq-container-{{each_widget.unique_id}}" style="padding: 0 12px;">
        <!-- Header Toggle Row -->
        <div class="seq-header-toggle-row">
            <!-- Timer Display (Real-time) -->
            <span id="seq-timer-{{each_widget.unique_id}}" class="seq-header-timer">00:00:00 / 00:00:00</span>
            
            <label class="btn-toggle">
                <input type="checkbox" 
                       id="seq-main-toggle-{{each_widget.unique_id}}" 
                       class="btn-toggle-input"
                       onchange="toggle_sequence_func('{{widget_options['function_id']}}', this)">
                <span class="btn-toggle-slider">
                    <span class="btn-toggle-thumb"></span>
                </span>
            </label>
        </div>
        
        <!-- Info Grid (Start / End / Period) -->
        <div class="seq-info-grid">
            <div class="seq-info-item">
                <span class="seq-info-label">{{ _('Start') }}</span>
                <span id="seq-disp-start-{{each_widget.unique_id}}" class="seq-info-val">--:--</span>
            </div>
            <div class="seq-info-item">
                <span class="seq-info-label">{{ _('End') }}</span>
                <span id="seq-disp-end-{{each_widget.unique_id}}" class="seq-info-val">--:--</span>
            </div>
            <div class="seq-info-item">
                <span class="seq-info-label">{{ _('Period') }}</span>
                <span id="seq-disp-period-{{each_widget.unique_id}}" class="seq-info-val">-- s</span>
            </div>
        </div>

        <!-- Action List Header -->
        <div style="display:flex; padding: 0 5px 5px 5px; font-size: 0.75em; color: #666; border-bottom: 2px solid #ddd;">
             <div style="width: 60px;">{{ _('TYPE') }}</div>
             <div style="flex-grow:1; padding-left:10px;">{{ _('NAME') }}</div>
             <div style="width: 30%; padding-left:10px;">{{ _('ACTION') }}</div>
             <div style="width: 70px; text-align:right; margin-right:15px;">{{ _('TIME') }}</div>
             <div style="width: 70px; text-align:right;">{{ _('ON/OFF') }}</div>
        </div>

        <!-- Action List -->
        <div id="seq-list-{{each_widget.unique_id}}" style="max-height: 250px; overflow-y: auto;">
            <!-- Populated by JS -->
            <div style="padding: 20px; text-align:center; color: #666;">{{ _('Waiting for data...') }}</div>
        </div>
    </div>
    """,

    'widget_dashboard_js': """
    // Global state for this widget type to handle timers
    // Key: widget_id, Value: { interval: null, elapsed: 0, period: 0, is_active: false, start_ts: 0 }
    if (typeof window.seqWidgetState === 'undefined') {
        window.seqWidgetState = {};
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

    function toggle_seq_action(action_id, checkbox) {
        var enabled = checkbox.checked;
        $.ajax({
            url: '/function_sequence_toggle_action',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ action_id: action_id, enabled: enabled }),
            success: function(resp) {
                console.log("Action toggled");
            },
            error: function(err) {
                toastr.error(window._("Failed to toggle action"));
                checkbox.checked = !enabled; // Revert
            }
        });
    }
    
    function toggle_sequence_func(function_id, checkbox) {
        if (!function_id) return;
        var state = checkbox.checked ? 'activate' : 'deactivate';
        
        $.ajax({
            url: '/sequence_activate_toggle/' + function_id + '/' + state,
            type: 'GET',
            success: function(resp) {
                if(resp.status === 'success') {
                    toastr.success(window._("Sequence") + " " + (checkbox.checked ? window._("Activated") : window._("Deactivated")));
                } else {
                    toastr.error(window._("Error") + ": " + (resp.error || window._("Unknown")));
                    checkbox.checked = !checkbox.checked; // Revert
                }
            },
            error: function(err) {
                toastr.error(window._("Failed to toggle Sequence"));
                checkbox.checked = !checkbox.checked; // Revert
            }
        });
    }

    function update_sequence_widget(function_id, widget_id, default_period) {
        if (!function_id) return;
        
        $.getJSON('/function_status_activated/' + function_id, function(data) {
            // console.log("SeqWidget Data:", data);
            if (data.error) {
                var display = document.getElementById('seq-timer-' + widget_id);
                if (display) {
                    display.innerText = "00:00:00 / " + format_seq_time(default_period || 0);
                }
                return;
            }

            // Update Info Grid
            var startEl = document.getElementById('seq-disp-start-' + widget_id);
            if(startEl) startEl.innerText = data.window_start || "--:--";
            
            var endEl = document.getElementById('seq-disp-end-' + widget_id);
            if(endEl) endEl.innerText = data.window_end || "--:--";
            
            var periodEl = document.getElementById('seq-disp-period-' + widget_id);
            if(periodEl) periodEl.innerText = format_seq_time(data.period);
            
            // --- Update Local State for Timer ---
            if (!window.seqWidgetState[widget_id]) window.seqWidgetState[widget_id] = {};
            var state = window.seqWidgetState[widget_id];
            
            state.period = data.period || 3600;
            state.is_active = data.is_activated;
            
            // Sync Cycle Start Time
            // Backend sends 'cycle_start_time' (timestamp) or we derive it from 'elapsed'
            if (data.cycle_start_time > 0) {
                 state.cycle_start_ts = data.cycle_start_time;
            } else {
                 // Fallback if not provided or 0
                 state.cycle_start_ts = 0; 
            }
            
            // Immediate update of timer
            try {
                update_local_timer(widget_id);
            } catch(e) {
                console.error("Timer update failed", e);
            }


            // Update Main Toggle
            var isActive = data.is_activated;
            var mainToggle = document.getElementById('seq-main-toggle-' + widget_id);
            if (mainToggle && document.activeElement !== mainToggle) {
                mainToggle.checked = isActive;
            }
            
            // Render List
            var listHtml = "";
            try {
                if (data.steps && data.steps.length > 0) {
                    for (var i = 0; i < data.steps.length; i++) {
                        var s = data.steps[i];
                        var rowClass = "seq-step-row";
                        
                        // Debug log
                        console.log("Step[" + i + "]:", s.action_name, 
                                    "Active:", s.is_active, 
                                    "Elapsed:", data.elapsed,
                                    "Start/End:", s.start, s.end);

                        var rowStyle = "";
                        if (s.is_active || s.is_activated) {
                            rowClass += " active";
                            // Force background color via inline style to avoid CSS specificity issues
                            rowStyle = 'style="background-color: rgba(40, 167, 69, 0.25) !important;"';
                        }
                        if (!s.enabled) rowClass += " disabled";

                        var timeStr = "";
                        if (s.start !== null) {
                            var duration = s.original_duration ? s.original_duration : Math.round(s.end - s.start);
                            timeStr = duration + "s";
                        } else {
                            timeStr = "--";
                        }

                        var checked = s.enabled ? "checked" : "";
                        
                        listHtml += '<div class="' + rowClass + '" ' + rowStyle + '>';
                        
                        // Type
                        listHtml += '<div class="seq-col-type">' + (s.type === 'total' ? window._('TOTAL') : window._('SINGLE')) + '</div>';
                        
                        // Name (Device Detail)
                        var devDetail = s.device_detail || ""; 
                        listHtml += '<div class="seq-col-device" title="' + devDetail + '">' + devDetail + '</div>';

                        // Action
                        var actionName = s.action_name || window._("Unknown");
                        listHtml += '<div class="seq-col-action" title="' + actionName + '">' + actionName + '</div>';
                        
                        // Time
                        listHtml += '<div class="seq-col-time">' + timeStr + '</div>';
                        
                        // Toggle
                        listHtml += '<div class="seq-col-toggle">';
                        
                        listHtml += '<label class="btn-toggle" style="margin-bottom:0;">'; 
                        listHtml += '<input type="checkbox" ' + checked + ' class="btn-toggle-input" data-id="' + s.unique_id + '" onchange="toggle_seq_action(this.dataset.id, this)">';
                        listHtml += '<span class="btn-toggle-slider">';
                        listHtml += '<span class="btn-toggle-thumb"></span>';
                        listHtml += '</span>';
                        listHtml += '</label>';

                        listHtml += '</div>';

                        listHtml += '</div>';
                    }
                } else {
                     listHtml = '<div style="padding:10px;text-align:center;color:#666;">' + window._("No actions found") + '</div>';
                }
            } catch(e) {
                console.error("List render failed", e);
                listHtml = "<div>" + window._("JS Error in List") + "</div>";
            }
            
            var listContainer = document.getElementById('seq-list-' + widget_id);
            // Only update innerHTML if it changes significantly or to avoid jitter?
            // For now, Replace All.
            if(listContainer) listContainer.innerHTML = listHtml;
        });
    }

    function repeat_update_seq_widget(function_id, widget_id, period_sec, default_period) {
        if(!period_sec) period_sec = 5;
        update_sequence_widget(function_id, widget_id, default_period);
        
        // Data Refresh Interval
        setInterval(function() {
            update_sequence_widget(function_id, widget_id, default_period);
        }, period_sec * 1000);
        
        // Local Timer Interval (1s)
        setInterval(function() {
             update_local_timer(widget_id);
        }, 1000);
    }
    """,

    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",

    'widget_dashboard_js_ready_end': """
      repeat_update_seq_widget('{{widget_options['function_id']}}', '{{each_widget.unique_id}}', {{widget_options.get('refresh_seconds', 5)}}, {{widget_options.get('sequence_period', 3600)}});
    """
}
