# -*- coding: utf-8 -*-
import logging
import json

import sqlalchemy
from flask import current_app

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.utils.actions import parse_action_information
from aot.utils.actions import which_controller

logger = logging.getLogger(__name__)


def action_add(form, request_form=None):
    """Add an action."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    action_id = None
    list_unmet_deps = []
    dep_name = ""
    page_refresh = False

    if not current_app.config['TESTING']:
        dep_unmet, _, dep_message = return_dependencies(form.action_type.data)
        if dep_unmet:
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
            messages["error"].append(
                f"{form.action_type.data} " + _("has unmet dependencies. They must be installed before the action can be added."))
            dep_name = form.action_type.data

            return messages, dep_name, list_unmet_deps, dep_message, None

    dict_actions = parse_action_information()
    controller_type, controller_table, _ = which_controller(form.device_id.data)

    if controller_type not in ['Conditional', 'Trigger', 'Function', 'Input']:
        messages["error"].append(_("Invalid controller type: {}").format(controller_type))

    if controller_type:
        controller = controller_table.query.filter(
            controller_table.unique_id == form.device_id.data).first()
        try:
            if controller and controller.is_activated:
                messages["error"].append(_("Deactivate controller before adding actions."))
        except:
            pass  # is_activated doesn't exist

    if form.action_type.data == '':
        messages["error"].append(_("An action must be selected."))

    try:
        new_action = Actions()
        new_action.function_id = form.device_id.data
        new_action.function_type = form.function_type.data
        new_action.action_type = form.action_type.data

        #
        # Custom Options
        #

        # Generate string to save from custom options
        messages["error"], custom_options = custom_options_return_json(
            messages["error"], dict_actions, device=form.action_type.data, use_defaults=True)
        
        # Parse time fields if present (for Sequence Actions) from request_form
        try:
            options_dict = json.loads(custom_options) if custom_options else {}
            
            # Handle Sequence Action Fields from request_form
            if request_form:
                for key in ['sequence_mode', 'action_duration', 'action_duration_id']:
                    if key in request_form:
                        value = request_form[key]
                        
                        # Parse action_duration with flexible time parsing
                        if key == 'action_duration' and value:
                            from aot.utils.time_utils import parse_flexible_time
                            parsed = parse_flexible_time(value)
                            if parsed:
                                options_dict[key] = parsed['total_seconds']
                                logger.info(f"DEBUG: action_add parsed action_duration '{value}' -> {parsed['total_seconds']}s")
                            else:
                                logger.warning(f"DEBUG: action_add failed to parse action_duration '{value}', keeping as-is")
                                options_dict[key] = value
                        else:
                            options_dict[key] = value
                
                custom_options = json.dumps(options_dict)
        except Exception as e:
            logger.warning(f"DEBUG: action_add time parsing failed: {e}")
        
        new_action.custom_options = custom_options

        if not messages["error"]:
            new_action.save()
            action_id = new_action.unique_id
            page_refresh = True
            messages["success"].append(f"{TRANSLATIONS['add']['title']} {TRANSLATIONS['actions']['title']}")
            
            # Refresh if it's a Trigger Sequence
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(form.device_id.data)

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, dep_name, list_unmet_deps, action_id, page_refresh


def action_mod(form, request_form):
    """Modify an action."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    mod_action = Actions.query.filter(
        Actions.unique_id == form.action_id.data).first()

    logger.info(f"DEBUG: action_mod action_id={form.action_id.data}")
    try:
        logger.info(f"DEBUG: request_form keys={list(request_form.keys())}")
    except:
        pass

    if not mod_action:
        messages["error"].append(_("Action not found."))
    else:
        # Parse custom options for action
        dict_actions = parse_action_information()
        if mod_action.action_type in dict_actions:
            messages["error"], custom_options = custom_options_return_json(
                messages["error"], dict_actions, request_form, mod_dev=mod_action, device=mod_action.action_type)

            # Handle Sequence Action Fields
            try:
                options_dict = json.loads(custom_options) if custom_options else {}
            except:
                options_dict = {}
            
            updated = False
            for key in ['sequence_mode', 'action_duration', 'action_duration_id']:
                if key in request_form:
                    value = request_form[key]
                    
                    # Parse action_duration with flexible time parsing
                    if key == 'action_duration' and value:
                        from aot.utils.time_utils import parse_flexible_time
                        parsed = parse_flexible_time(value)
                        if parsed:
                            options_dict[key] = parsed['total_seconds']
                            logger.info(f"DEBUG: Parsed action_duration '{value}' -> {parsed['total_seconds']}s")
                        else:
                            logger.warning(f"DEBUG: Failed to parse action_duration '{value}', keeping as-is")
                            options_dict[key] = value
                    else:
                        options_dict[key] = value
                    
                    updated = True
            
            if updated:
                custom_options = json.dumps(options_dict)

            mod_action.custom_options = custom_options

    if not messages["error"]:
        try:
            db.session.commit()
            messages["success"].append(f"{TRANSLATIONS['modify']['title']} {TRANSLATIONS['actions']['title']}")
            
            # Refresh if it's a Trigger Sequence
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(mod_action.function_id)
            
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(str(except_msg))
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(str(except_msg))
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages


def action_del(form):
    """Delete an action."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    controller_type, _, controller_entry = which_controller(form.device_id.data)

    if (controller_type in ['conditional', 'function', 'input'] and  # Note: trigger controller types are not activated
            controller_entry and controller_entry.is_activated):
        messages["error"].append(
            _("Deactivate conditional controller before deleting actions."))

    if not messages["error"]:
        try:
            action_id = Actions.query.filter(
                Actions.unique_id == form.action_id.data).first().unique_id
            delete_entry_with_id(
                Actions, action_id, flash_message=False)
            messages["success"].append(f"{TRANSLATIONS['delete']['title']} {TRANSLATIONS['actions']['title']}")
            
            # Refresh if it's a Trigger Sequence
            from aot.aot_client import DaemonControl
            DaemonControl().refresh_daemon_trigger_settings(form.device_id.data)
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(str(except_msg))
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(str(except_msg))
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages