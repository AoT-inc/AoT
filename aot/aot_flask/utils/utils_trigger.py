# -*- coding: utf-8 -*-
import logging

import sqlalchemy
from flask_babel import gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.databases.models import Trigger
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import controller_activate_deactivate
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.utils.system_pi import epoch_of_next_time
from aot.utils.time_utils import parse_flexible_time

logger = logging.getLogger(__name__)


def trigger_mod(form):
    """Modify a Trigger."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None
    }
    page_refresh = False

    try:
        trigger = Trigger.query.filter(
            Trigger.unique_id == form.function_id.data).first()
        logger.info(f"DEBUG: trigger_mod called for {trigger.unique_id}, type={trigger.trigger_type}")
        trigger.name = form.name.data
        trigger.action_type = form.action_type.data
        messages["name"] = form.name.data
        trigger.log_level_debug = form.log_level_debug.data
        trigger.latitude = form.latitude.data if form.latitude.data not in [None, ''] else trigger.latitude
        trigger.longitude = form.longitude.data if form.longitude.data not in [None, ''] else trigger.longitude
        if hasattr(trigger, 'location_source'):
            trigger.location_source = form.location_source.data

        if trigger.trigger_type == 'trigger_edge':
            if not form.measurement.data or form.measurement.data == '':
                messages["error"].append("{meas} must be set".format(
                    meas=form.measurement.label.text))
            trigger.measurement = form.measurement.data
            trigger.edge_detected = form.edge_detected.data

        elif trigger.trigger_type == 'trigger_output':
            if not form.unique_id_1.data:
                messages["error"].append("{id} must be set".format(
                    id=form.unique_id_1.label.text))
            if not form.output_state.data:
                messages["error"].append("{id} must be set".format(
                    id=form.output_state.label.text))
            trigger.unique_id_1 = form.unique_id_1.data.split(",")[0]
            trigger.unique_id_2 = form.unique_id_1.data.split(",")[1]
            trigger.output_state = form.output_state.data
            trigger.output_duration = form.output_duration.data

        elif trigger.trigger_type == 'trigger_output_pwm':
            if not form.unique_id_1.data:
                messages["error"].append("{id} must be set".format(
                    id=form.unique_id_1.label.text))
            if not form.output_state or form.output_state == '':
                messages["error"].append("State must be set".format(
                    dir=form.output_state))
            if not 0 <= form.output_duty_cycle.data <= 100:
                messages["error"].append("{id} must >= 0 and <= 100".format(
                    id=form.output_duty_cycle.label.text))
            trigger.unique_id_1 = form.unique_id_1.data.split(",")[0]
            trigger.unique_id_2 = form.unique_id_1.data.split(",")[1]
            trigger.output_state = form.output_state.data
            trigger.output_duty_cycle = form.output_duty_cycle.data

        elif trigger.trigger_type == 'trigger_run_pwm_method':
            if not form.period.data or form.period.data <= 0:
                messages["error"].append("Period must be greater than 0")
            if not form.unique_id_1.data:
                messages["error"].append("{id} must be set".format(
                    id=form.unique_id_1.label.text))
            if not form.unique_id_2.data:
                messages["error"].append("{id} must be set".format(
                    id=form.unique_id_2.label.text))
            trigger.unique_id_1 = form.unique_id_1.data
            trigger.unique_id_2 = form.unique_id_2.data.split(",")[0]
            trigger.unique_id_3 = form.unique_id_2.data.split(",")[1]
            trigger.period = form.period.data
            trigger.trigger_actions_at_start = form.trigger_actions_at_start.data
            trigger.trigger_actions_at_period = form.trigger_actions_at_period.data

        elif trigger.trigger_type == 'trigger_sunrise_sunset':
            page_refresh = True
            if form.rise_or_set.data not in ['sunrise', 'sunset']:
                messages["error"].append("{id} must be set to 'sunrise' or 'sunset'".format(
                    id=form.rise_or_set.label.text))
            if -90 > form.latitude.data > 90:
                messages["error"].append("{id} must be >= -90 and <= 90".format(
                    id=form.latitude.label.text))
            if -180 > form.longitude.data > 180:
                messages["error"].append("{id} must be >= -180 and <= 180".format(
                    id=form.longitude.label.text))
            if form.date_offset_days.data is None:
                messages["error"].append("{id} must be set".format(
                    id=form.date_offset_days.label.text))
            if form.time_offset_minutes.data is None:
                messages["error"].append("{id} must be set".format(
                    id=form.time_offset_minutes.label.text))
            trigger.rise_or_set = form.rise_or_set.data
            trigger.latitude = form.latitude.data
            trigger.longitude = form.longitude.data
            trigger.date_offset_days = form.date_offset_days.data
            trigger.time_offset_minutes = form.time_offset_minutes.data

        elif trigger.trigger_type == 'trigger_timer_daily_time_point':
            if not epoch_of_next_time('{hm}:00'.format(hm=form.timer_start_time.data)):
                messages["error"].append("{id} must be a valid HH:MM time format".format(
                    id=form.timer_start_time.label.text))
            trigger.timer_start_time = form.timer_start_time.data

        elif trigger.trigger_type == 'trigger_timer_daily_time_span':
            if not epoch_of_next_time('{hm}:00'.format(hm=form.timer_start_time.data)):
                messages["error"].append("{id} must be a valid HH:MM time format".format(
                    id=form.timer_start_time.label.text))
            if not epoch_of_next_time('{hm}:00'.format(hm=form.timer_end_time.data)):
                messages["error"].append("{id} must be a valid HH:MM time format".format(
                    id=form.timer_end_time.label.text))
            trigger.period = form.period.data
            trigger.timer_start_time = form.timer_start_time.data
            trigger.timer_end_time = form.timer_end_time.data

        elif trigger.trigger_type == 'trigger_timer_duration':
            if form.period.data <= 0:
                messages["error"].append("{id} must be > 0".format(
                    id=form.period.label.text))
            if form.timer_start_offset.data < 0:
                messages["error"].append("{id} must be >= 0".format(
                    id=form.timer_start_offset.label.text))
            trigger.period = form.period.data
            trigger.timer_start_offset = form.timer_start_offset.data

        elif trigger.trigger_type == 'trigger_sequence':
            logger.info(f"DEBUG: trigger_sequence mod. Data: start={form.timer_start_time.data}, end={form.timer_end_time.data}, period={form.period.data}, dur={form.output_duration.data}, latency={form.timer_start_offset.data}, validity={form.time_offset_minutes.data}")
            
            trigger.timer_start_time = form.timer_start_time.data
            trigger.timer_end_time = form.timer_end_time.data
            
            # Use flexible parsing for numeric/time fields
            # If parsing fails or value is empty, keep the existing value
            if form.period.data:
                p_res = parse_flexible_time(form.period.data)
                if p_res:
                    trigger.period = p_res['total_seconds']
                else:
                    logger.warning(f"Failed to parse period '{form.period.data}', keeping existing value {trigger.period}")
            
            if form.output_duration.data:
                d_res = parse_flexible_time(form.output_duration.data)
                if d_res:
                    trigger.output_duration = d_res['total_seconds']
                else:
                    logger.warning(f"Failed to parse output_duration '{form.output_duration.data}', keeping existing value {trigger.output_duration}")
            
            if form.timer_start_offset.data:
                l_res = parse_flexible_time(form.timer_start_offset.data)
                if l_res:
                    trigger.timer_start_offset = l_res['total_seconds']
                else:
                    logger.warning(f"Failed to parse timer_start_offset '{form.timer_start_offset.data}', keeping existing value {trigger.timer_start_offset}")
            
            if form.time_offset_minutes.data:
                v_res = parse_flexible_time(form.time_offset_minutes.data)
                if v_res:
                    trigger.time_offset_minutes = v_res['total_seconds']
                else:
                    logger.warning(f"Failed to parse time_offset_minutes '{form.time_offset_minutes.data}', keeping existing value {trigger.time_offset_minutes}")
            
            logger.info(f"DEBUG: Trigger obj updated: {trigger.timer_start_time}, {trigger.period}, latency={trigger.timer_start_offset}, val={trigger.time_offset_minutes}")

        if not messages["error"]:
            logger.info("DEBUG: Attempting DB commit...")
            try:
                db.session.commit()
                logger.info("DEBUG: DB commit successful.")

                # Verify persistence
                if trigger.trigger_type == 'trigger_sequence':
                    try:
                        check = Trigger.query.filter(Trigger.unique_id == form.function_id.data).first()
                        logger.info(f"DEBUG: Post-commit check: start={check.timer_start_time}, end={check.timer_end_time}, period={check.period}, dur={check.output_duration}")
                    except Exception as e:
                        logger.error(f"DEBUG: Post-commit verification failed: {e}")

                messages["success"].append('{action} {controller}'.format(
                    action=TRANSLATIONS['modify']['title'],
                    controller=TRANSLATIONS['trigger']['title']))

                # Refresh Daemon if activated
                if trigger.is_activated:
                    try:
                        control = DaemonControl()
                        return_value = control.refresh_daemon_trigger_settings(form.function_id.data)
                        messages["success"].append(gettext("Daemon response: %(resp)s", resp=return_value))
                    except Exception as e:
                        logger.error(f"Failed to refresh daemon: {e}")

                # Sync Widgets (Smart Sync)
                if trigger.trigger_type == 'trigger_sequence':
                    try:
                        from aot.databases.models.dashboard import Widget
                        import json
                        
                        # Find all Sequence Controller widgets
                        widgets = Widget.query.filter(Widget.name == 'Sequence Controller').all() # Name might vary, safer to check custom_options
                        # Actually, name is default, but safer to query all or check specific type if possible. 
                        # Since we don't have a standardized 'widget_type' column (it's in widget code), 
                        # we rely on checking if custom_options contains 'function_id' matching our trigger config.
                        
                        all_widgets = Widget.query.all()
                        sys_updated = 0
                        
                        for w in all_widgets:
                            try:
                                if not w.custom_options: continue
                                opts = json.loads(w.custom_options)
                                
                                # Check if this widget is controlling THIS trigger
                                if opts.get('function_id') == form.function_id.data:
                                    # Update specific fields
                                    opts['timer_start_time'] = trigger.timer_start_time or "00:00"
                                    opts['timer_end_time'] = trigger.timer_end_time or "23:59"
                                    opts['sequence_period'] = float(trigger.period or 3600)
                                    opts['timer_start_offset'] = int(trigger.timer_start_offset or 0)
                                    opts['output_duration'] = float(trigger.output_duration or 0)
                                    opts['time_offset_minutes'] = int(trigger.time_offset_minutes or 300)
                                    
                                    w.custom_options = json.dumps(opts)
                                    sys_updated += 1
                                    logger.info(f"Synced Widget {w.unique_id} with Trigger {trigger.unique_id}")
                            except Exception as we:
                                logger.debug(f"Skipping widget {w.unique_id} sync: {we}")
                        
                        if sys_updated > 0:
                            db.session.commit()
                            logger.info(f"Updated {sys_updated} widgets with new Trigger settings.")
                            
                    except Exception as e:
                        logger.error(f"Failed to sync widgets: {e}")

            except Exception as e:
                logger.error(f"DEBUG: DB commit FAILED: {e}")
                messages["error"].append(f"Database commit failed: {e}")
        else:
            logger.warning(f"DEBUG: Skipping commit due to errors: {messages['error']}")

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def trigger_del(trigger_id):
    """Delete a Trigger."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    trigger = Trigger.query.filter(
        Trigger.unique_id == trigger_id).first()

    # Deactivate trigger if active
    if trigger.is_activated:
        trigger_deactivate(trigger_id)

    try:
        if not messages["error"]:
            # Delete Actions
            actions = Actions.query.filter(
                Actions.function_id == trigger_id).all()
            for each_action in actions:
                delete_entry_with_id(
                    Actions,
                    each_action.unique_id,
                    flash_message=False)

            delete_entry_with_id(
                Trigger, trigger_id, flash_message=False)

            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['delete']['title'],
                controller=TRANSLATIONS['trigger']['title']))
    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def trigger_activate(trigger_id):
    """Activate a Trigger."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    mod_trigger = Trigger.query.filter(
        Trigger.unique_id == trigger_id).first()

    # Check for errors in the Trigger settings
    if mod_trigger.trigger_type == 'edge':
        messages["error"] = check_cond_edge(mod_trigger, messages["error"])
    elif mod_trigger.trigger_type == 'output':
        messages["error"] = check_cond_output(mod_trigger, messages["error"])

    actions = Actions.query.filter(
        Actions.function_id == trigger_id)

    if not actions.count() and mod_trigger.trigger_type != 'trigger_run_pwm_method':
        messages["error"].append(
            "No Actions found: Add at least one Action before activating.")

    messages = controller_activate_deactivate(
        messages, 'activate', 'Trigger', trigger_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['activate']['title'],
            controller=TRANSLATIONS['trigger']['title']))

    return messages


def trigger_deactivate(trigger_id):
    """Deactivate a Trigger."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    messages = controller_activate_deactivate(
        messages, 'deactivate', 'Trigger', trigger_id, flash_message=False)

    if not messages["error"]:
        trigger = Trigger.query.filter(
            Trigger.unique_id == trigger_id).first()
        trigger.method_start_time = None
        trigger.method_end_time = None
        db.session.commit()

        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['deactivate']['title'],
            controller=TRANSLATIONS['trigger']['title']))

    return messages


def check_cond_edge(form, error):
    """Checks if the saved variables have any errors."""
    if not form.measurement or form.measurement == '':
        error.append("Measurement must be set")
    return error


def check_form_output_duration(form, error):
    """Checks if the submitted form has any errors."""
    if not form.unique_id_1.data:
        error.append("{id} must be set".format(
            id=form.unique_id_1.label.text))
    if not form.output_state.data:
        error.append("{id} must be set".format(
            id=form.output_state.label.text))
    if not form.output_duration.data:
        error.append("{id} must be set".format(
            id=form.output_duration.label.text))
    return error


def check_cond_output(form, error):
    """Checks if the saved variables have any errors."""
    if not form.unique_id_1 or form.unique_id_1 == '':
        error.append("An Output must be set")
    if not form.output_state or form.output_state == '':
        error.append("A State must be set")
    return error
