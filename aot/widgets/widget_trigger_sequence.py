# coding=utf-8
import logging
import json
from flask_babel import lazy_gettext

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.databases.models import Trigger, Widget
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

def sequence_toggle_details(unique_id, state):
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
    'widget_width': 24,
    'widget_height': 10,
    'execute_at_modification': execute_at_modification,
    
    'endpoints': [
        ("/sequence_activate_toggle/<unique_id>/<state>", "sequence_activate_toggle", sequence_activate_toggle, ["GET"]),
        ("/sequence_toggle_details/<unique_id>/<state>", "sequence_toggle_details", sequence_toggle_details, ["GET"])
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
    <style>
        /* widget_sequence.css embedded */
        /* --- Layout Containers --- */
        .seq-widget-container {
            padding: 10px 12px;
            color: var(--aot-text-main, #333);
            font-family: inherit; /* Ensure default font */
            font-size: 1em;       /* Default base size */
        }

        /* --- Section 1: Header (Timer + Toggle) --- */
        .seq-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .seq-main-timer {
            font-size: 1.2em;
            color: var(--aot-text-title, #222);
        }

        /* --- Section 2: Info Grid --- */
        .seq-info-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px; /* Gap between cards */
            margin-bottom: 15px;
        }

        .seq-info-card {
            background-color: var(--aot-bg-sub, #f8f9fa);
            border: 1px solid var(--aot-border-light, #eee);
            border-radius: 8px;
            padding: 8px 4px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }

        .seq-info-label {
            font-size: 0.75em;
            color: var(--gray-dark, #888);
            text-transform: uppercase;
            margin-bottom: 4px;
            font-weight: 500;
        }

        .seq-info-value {
            font-size: 1.2em;
            font-weight: bold;
            color: var(--aot-text-main, #444);
        }

        /* --- Section 2.5: Expand/Collapse Button --- */
        .seq-expand-btn-container {
            margin-bottom: 15px;
            display: flex;
            justify-content: center;
        }

        .seq-expand-btn {
            width: 100%;
            height: 32px;
            border-radius: 16px; /* Pill shape */
            background-color: transparent;
            border: 1px solid var(--aot-border-light, #ddd);
            color: var(--gray-dark, #666);
            font-size: 1em; /* Reset to 1em */
            font-weight: 500;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .seq-expand-btn:hover {
            background-color: var(--aot-bg-hover, #f0f0f0);
            border-color: var(--gray-dark, #ccc);
            color: var(--aot-text-main, #333);
        }

        .seq-expand-btn:active {
            transform: scale(0.99);
        }

        .seq-expand-icon {
            font-size: 0.8em;
            margin-left: 6px;
            transition: transform 0.3s ease;
        }

        .seq-expand-btn.expanded .seq-expand-icon {
            transform: rotate(180deg);
        }

        /* --- Section 3: Action List --- */
        .seq-details-container {
            display: none; /* Hidden by default, controlled by inline style */
            overflow: hidden;
            transition: max-height 0.3s ease;
        }

        .seq-details-container.expanded {
            display: block;
        }

        /* List Header */
        .seq-list-header {
            display: flex;
            align-items: center;
            padding: 8px 10px;
            background-color: var(--aot-bg-sub, #f9f9f9);
            border-bottom: 1px solid var(--aot-border-light, #eee);
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-size: 0.75em;
            color: var(--gray-dark, #777);
            font-weight: 600;
        }

        /* Columns - Adjusted for new order: Enable | Name | Type | Time */
        .seq-col-enable { 
            width: 40px; 
            text-align: center; 
            flex-shrink: 0;
        }
        .seq-col-name { 
            flex-grow: 1; 
            padding-left: 10px; 
            overflow: hidden; 
            text-overflow: ellipsis; 
            white-space: nowrap; 
        }
        .seq-col-type { 
            width: 80px; 
            text-align: left; 
            flex-shrink: 0; 
        }
        .seq-col-time { 
            width: 80px; 
            text-align: left; 
            padding-right: 5px; 
            flex-shrink: 0; 
        }

        /* List Body */
        .seq-list-body {
            border: 1px solid var(--aot-border-light, #eee);
            border-top: none;
            border-bottom-left-radius: 8px;
            border-bottom-right-radius: 8px;
            background: #fff;
            max-height: 330px;
            overflow-y: auto;
        }

        .seq-list-item {
            display: flex;
            align-items: center;
            padding: 0 10px; /* Vertical padding handled by height/align-items */
            border-bottom: 1px solid var(--aot-border-light, #f0f0f0);
            color: var(--aot-text-main, #444);
            font-size: 1em; /* Reset to 1em */
            height: 40px;
            box-sizing: border-box;
            white-space: nowrap;
            flex-wrap: nowrap;
        }

        .seq-list-item:last-child {
            border-bottom: none;
        }

        .seq-list-item.active {
            background-color: rgba(40, 167, 69, 0.1); /* Green hint */
            border-left: 3px solid #28a745;
            padding-left: 7px;
        }

        .seq-list-item.disabled {
            opacity: 0.6;
            background-color: #fafafa;
        }

        /* Square Toggle Button Style */
        .seq-square-toggle {
            appearance: none;
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            border: 2px solid #28a745; /* Green border by default */
            border-radius: 2px; /* Slightly rounded square */
            background-color: transparent;
            cursor: pointer;
            position: relative;
            vertical-align: middle;
            outline: none;
            transition: all 0.2s ease;
        }

        .seq-square-toggle:checked {
            background-color: #28a745;
            border-color: #28a745;
        }

        /* Optional checkmark for better visibility */
        .seq-square-toggle:checked::after {
            content: '';
            position: absolute;
            top: 1px;
            left: 4px;
            width: 5px;
            height: 9px;
            border: solid white;
            border-width: 0 2px 2px 0;
            transform: rotate(45deg);
        }

        .seq-square-toggle:hover {
            border-color: #218838;
        }

        /* Text styles */
        .seq-text-name {
            font-weight: 500;
        }
        .seq-text-type {
            font-size: 0.85em;
            color: var(--gray-dark, #888);
            text-transform: uppercase;
        }
        .seq-text-time {
            font-weight: 600;
            color: var(--aot-text-main, #555);
        }

        /* Mobile Adjustments */
        @media (max-width: 768px) {
            .seq-col-type { width: 60px; }
            .seq-col-time { width: 60px; }
        }
    </style>
    """,

    'widget_dashboard_title_bar': """<span id="seq-title-{{each_widget.unique_id}}">{{each_widget.name}}</span>""",

    'widget_dashboard_body': """
    {% set show_det = widget_options.get('show_details', 'Show') %}
    <div id="seq-container-{{each_widget.unique_id}}" class="seq-widget-container">
        
        <!-- Section 1: Header (Timer + Toggle) -->
        <div class="seq-header-row">
            <div id="seq-timer-{{each_widget.unique_id}}" class="seq-main-timer">00:00:00 / 00:00:00</div>
            
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
        
        <!-- Section 2: Info Grid -->
        <div class="seq-info-grid">
            <div class="seq-info-card">
                <span class="seq-info-label">{{ _('Start') }}</span>
                <span id="seq-disp-start-{{each_widget.unique_id}}" class="seq-info-value">--:--</span>
            </div>
            <div class="seq-info-card">
                <span class="seq-info-label">{{ _('End') }}</span>
                <span id="seq-disp-end-{{each_widget.unique_id}}" class="seq-info-value">--:--</span>
            </div>
            <div class="seq-info-card">
                <span class="seq-info-label">{{ _('Period') }}</span>
                <span id="seq-disp-period-{{each_widget.unique_id}}" class="seq-info-value">-- s</span>
            </div>
        </div>

        <!-- Section 2.5: Expand Button -->
        <div class="seq-expand-btn-container">
            <button class="seq-expand-btn" onclick="toggle_seq_details('{{each_widget.unique_id}}', this)">
                <span class="seq-btn-text">{{ _('Actions') }}</span>
                <span class="seq-expand-icon">
                    {% if show_det == 'Show' %}▲{% else %}▼{% endif %}
                </span>
            </button>
        </div>

        <!-- Section 3: Action List (Default: visible, respects user preference) -->
        <div id="seq-details-{{each_widget.unique_id}}" class="seq-details-container" 
             style="display: {% if show_det == 'Show' %}block{% else %}none{% endif %} !important;">
            <div class="seq-list-header">
                <div class="seq-col-enable"></div>
                <div class="seq-col-name">{{ _('Name') }}</div>
                <div class="seq-col-type">{{ _('Type') }}</div>
                <div class="seq-col-time">{{ _('Time') }}</div>
            </div>
            <div id="seq-list-{{each_widget.unique_id}}" class="seq-list-body">
                <!-- Populated by JS -->
                <div style="padding: 20px; text-align:center; color: #666;">{{ _('Waiting for data...') }}</div>
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
                safe_toast('error', window._("Failed to toggle action"));
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

    function toggle_seq_details(widget_id, btn) {
        var details = document.getElementById('seq-details-' + widget_id);
        if (!details) return;
        
        var isHidden = (details.style.display === 'none' || getComputedStyle(details).display === 'none');
        
        if (isHidden) {
            details.style.display = 'block';
            $(btn).find('.seq-expand-icon').text('▲');
            // Save state to localStorage
            localStorage.setItem('seq_details_' + widget_id, 'show');
            // Save to server: 1 (Show)
            $.get('/sequence_toggle_details/' + widget_id + '/1');
        } else {
            details.style.display = 'none';
            $(btn).find('.seq-expand-icon').text('▼');
            // Save state to localStorage
            localStorage.setItem('seq_details_' + widget_id, 'hide');
            // Save to server: 0 (Hide)
            $.get('/sequence_toggle_details/' + widget_id + '/0');
        }
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
                        var rowClass = "seq-list-item";
                        
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
                            timeStr = format_seq_time(duration);
                        } else {
                            timeStr = "--";
                        }

                        var checked = s.enabled ? "checked" : "";
                        
                        listHtml += '<div class="' + rowClass + '" ' + rowStyle + '>';
                        
                        // --- Column 1: Enable (Checkbox) ---
                        listHtml += '<div class="seq-col-enable">';
                        listHtml += '<input type="checkbox" ' + checked + ' class="seq-square-toggle" data-id="' + s.unique_id + '" onchange="toggle_seq_action(this.dataset.id, this)">';
                        listHtml += '</div>';
                        
                        // --- Column 2: Name (Prioritize Channel Name > Device Name > Action Name) ---
                        // Backend populates device_name and device_channel_name
                        var nameToUse = s.device_channel_name || s.device_name || s.action_name || window._("Unknown");
                        listHtml += '<div class="seq-col-name" title="' + nameToUse + '"><span class="seq-text-name">' + nameToUse + '</span></div>';
                        
                        // --- Column 3: Type ---
                        listHtml += '<div class="seq-col-type"><span class="seq-text-type">' + (s.type === 'total' ? window._('TOTAL') : window._('SINGLE')) + '</span></div>';
                        
                        // --- Column 4: Time ---
                        listHtml += '<div class="seq-col-time"><span class="seq-text-time">' + timeStr + '</span></div>';
                        
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
