# -*- coding: utf-8 -*-
import logging
import threading
import json

import sqlalchemy
from flask import current_app, request
from flask_babel import gettext

from aot.config import FUNCTION_INFO
from aot.config import PID_INFO
from aot.config_translations import TRANSLATIONS
from aot.databases import set_uuid
from aot.databases.models import Actions
from aot.databases.models import Conditional
from aot.databases.models import ConditionalConditions
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Function, CustomController
from aot.databases.models import FunctionChannel
from aot.databases.models import PID
from aot.databases.models import Trigger
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.utils.conditional import save_conditional_code
from aot.utils.actions import parse_action_information
from aot.utils.functions import parse_function_information
from aot.aot_flask.utils.utils_map_config import (
    ensure_map_config,
    delete_map_config,
)
from aot.aot_flask.utils.utils_misc import determine_controller_type
from aot.databases import clone_model

logger = logging.getLogger(__name__)

#
# Function manipulation
#

def _get_next_position_y():
    """Calculate the next available position_y across all function tables."""
    try:
        max_y = 0
        tables = [Conditional, PID, Trigger, Function, CustomController]
        for table in tables:
            # Use getattr for safety, though models should have it
            if hasattr(table, 'position_y'):
                res = db.session.query(db.func.max(table.position_y)).scalar()
                if res is not None and res > max_y:
                    max_y = res
        return max_y + 1
    except Exception:
        return 999


def function_add(form_add_func):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    new_function_id = None
    list_unmet_deps = []
    dep_name = None
    dep_message = ''

    function_name = form_add_func.function_type.data

    dict_controllers = parse_function_information()

    if not current_app.config['TESTING']:
        dep_unmet, _, dep_message = return_dependencies(function_name)
        if dep_unmet:
            messages["error"].append(
                f"{function_name} " + _("has unmet dependencies. They must be installed before the function can be added."))
            
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
                if each_dep[2] == 'pip-pypi':
                    dep_message += _("Python package %(package)s was not found because '%(module)s' could not be imported.") % {'package': each_dep[3], 'module': each_dep[0]}


            if function_name in dict_controllers:
                dep_name = dict_controllers[function_name]['function_name']
            elif function_name in FUNCTION_INFO and 'name' in FUNCTION_INFO[function_name]:
                dep_name = FUNCTION_INFO[function_name]['name']
            else:
                messages["error"].append(_("Function not found: {}").format(function_name))

            return messages, dep_name, list_unmet_deps, dep_message, None

    new_func = None

    try:
        if function_name == 'conditional_conditional':
            new_func = Conditional()
            new_func.position_y = _get_next_position_y()
            new_func.conditional_import = """
from datetime import datetime"""
            new_func.conditional_initialize = """
self.loop_count = 0"""
            new_func.conditional_statement = '''
# Example code for learning how to use conditionals. Refer to the manual for details.
self.logger.info("This INFO log entry will be displayed in the daemon log")

self.loop_count += 1  # Increment execution count

measurement = self.condition("asdf1234")  # Replace ID with correct one
self.logger.info(f"Measurement is {measurement}")

if measurement is not None:  # If measurement exists
    self.message += "This message will be shown in email notifications and notes.\n"

    if measurement < 23:  # If measurement is less than 23
        self.message += f"Measurement is too low! Value: {measurement}.\n"
        self.run_all_actions(message=self.message)  # Execute all actions in sequence

    elif measurement > 27:  # If measurement is greater than 27
        self.message += f"Measurement is too high! Value: {measurement}.\n"
        # Replace "qwer5678" with the appropriate action ID
        self.run_action("qwer5678", message=self.message)  # Execute specific action'''
            
            new_func.conditional_status = '''
# Example code to provide return status to other controllers and widgets.
status_dict = {
    'string_status': _("Controller has executed {} loops. Current time: {}").format(self.loop_count, datetime.now()),
    'loop_count': self.loop_count,
    'error': []
}
return status_dict'''

            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id
                if not current_app.config['TESTING']:
                    save_conditional_code(
                        messages["error"],
                        new_func.conditional_import,
                        new_func.conditional_initialize,
                        new_func.conditional_statement,
                        new_func.conditional_status,
                        new_func.unique_id,
                        ConditionalConditions.query.all(),
                        Actions.query.all(),
                        test=False)
                    
        elif function_name == 'pid_pid':
            new_func = PID()
            new_func.position_y = _get_next_position_y()
            new_func.save()
            new_function_id = new_func.unique_id

            for each_channel, measure_info in PID_INFO['measure'].items():
                new_measurement = DeviceMeasurements()

                if 'name' in measure_info:
                    new_measurement.name = measure_info['name']
                if 'measurement_type' in measure_info:
                    new_measurement.measurement_type = measure_info['measurement_type']

                new_measurement.device_id = new_func.unique_id
                new_measurement.measurement = measure_info['measurement']
                new_measurement.unit = measure_info['unit']
                new_measurement.channel = each_channel
                if not messages["error"]:
                    new_measurement.save()

        elif function_name in ['trigger_edge',
                               'trigger_output',
                               'trigger_output_pwm',
                               'trigger_timer_daily_time_point',
                               'trigger_timer_daily_time_span',
                               'trigger_timer_duration',
                               'trigger_run_pwm_method',
                               'trigger_sunrise_sunset',
                               'trigger_sequence']:
            new_func = Trigger()
            new_func.name = '{}'.format(FUNCTION_INFO[function_name]['name'])
            new_func.trigger_type = function_name
            new_func.position_y = _get_next_position_y()

            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name == 'function_actions':
            new_func = Function()
            new_func.position_y = _get_next_position_y()
            new_func.function_type = function_name
            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name in dict_controllers:
            # Custom Function Controller
            new_func = CustomController()
            new_func.device = function_name
            new_func.position_y = _get_next_position_y()

            if 'function_name_short' in dict_controllers[function_name]:
                new_func.name = dict_controllers[function_name]['function_name_short']
            elif 'function_name' in dict_controllers[function_name]:
                new_func.name = dict_controllers[function_name]['function_name']
            elif function_name in FUNCTION_INFO and 'name' in FUNCTION_INFO[function_name]:
                new_func.name = FUNCTION_INFO[function_name]['name']
            else:
                new_func.name = _("Function Name")


            messages["error"], custom_options = custom_options_return_json(
                messages["error"], dict_controllers, device=function_name, use_defaults=True)
            new_func.custom_options = custom_options

            map_cfg = ensure_map_config(
                None,
                new_func.name,
                new_func.latitude,
                new_func.longitude
            )
            new_func.map_config_id = map_cfg.unique_id

            new_func.unique_id = set_uuid()

            if ('execute_at_creation' in dict_controllers[new_func.device] and
                    not current_app.config['TESTING']):
                messages["error"], new_func = dict_controllers[new_func.device]['execute_at_creation'](
                    messages["error"], new_func, dict_controllers[new_func.device])
                
            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name == '':
            messages["error"].append(_("A function type must be selected."))
        else:
            messages["error"].append(_("Unknown function type: '{}'").format(function_name))

        if not messages["error"]:
            if function_name in dict_controllers:

                # Add measurements defined in the Function module


                if ('measurements_dict' in dict_controllers[function_name] and
                        dict_controllers[function_name]['measurements_dict']):
                    for each_channel in dict_controllers[function_name]['measurements_dict']:
                        measure_info = dict_controllers[function_name]['measurements_dict'][each_channel]
                        new_measurement = DeviceMeasurements()
                        new_measurement.device_id = new_func.unique_id
                        if 'name' in measure_info:
                            new_measurement.name = measure_info['name']
                        else:
                            new_measurement.name = ""
                        if 'measurement' in measure_info:
                            new_measurement.measurement = measure_info['measurement']
                        else:
                            new_measurement.measurement = ""
                        if 'unit' in measure_info:
                            new_measurement.unit = measure_info['unit']
                        else:
                            new_measurement.unit = ""
                        new_measurement.channel = each_channel
                        new_measurement.save()


                # If variable measurements exist in the Function module


                elif ('measurements_variable_amount' in dict_controllers[function_name] and
                        dict_controllers[function_name]['measurements_variable_amount']):
                    
                    new_measurement = DeviceMeasurements()
                    new_measurement.name = ""
                    new_measurement.device_id = new_func.unique_id
                    new_measurement.measurement = ""
                    new_measurement.unit = ""
                    new_measurement.channel = 0
                    new_measurement.save()


                # Add channels defined in the Function module


                if 'channels_dict' in dict_controllers[function_name]:
                    for each_channel, channel_info in dict_controllers[function_name]['channels_dict'].items():
                        new_channel = FunctionChannel()
                        new_channel.channel = each_channel
                        new_channel.function_id = new_func.unique_id


                        messages["error"], custom_options = custom_channel_options_return_json(
                            messages["error"], dict_controllers, None,
                            new_func.unique_id, each_channel,
                            device=new_func.device, use_defaults=True)
                        new_channel.custom_options = custom_options

                        new_channel.save()

            messages["success"].append(f"{TRANSLATIONS['add']['title']} {TRANSLATIONS['function']['title']}")

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        logger.exception("Add Function")
        messages["error"].append(str(except_msg))

    return messages, dep_name, list_unmet_deps, dep_message, new_function_id


def update_location_marker(function_id, request_form):
    """Update location/marker fields for any function or custom controller if provided."""
    func_mod = Function.query.filter(Function.unique_id == function_id).first()
    if not func_mod:
        func_mod = CustomController.query.filter(CustomController.unique_id == function_id).first()
    if not func_mod:
        return

    if hasattr(func_mod, 'map_config_id'):
        map_cfg = ensure_map_config(
            getattr(func_mod, 'map_config_id', None),
            getattr(func_mod, 'name', None),
            getattr(func_mod, 'latitude', None),
            getattr(func_mod, 'longitude', None)
        )
        if getattr(func_mod, 'map_config_id', None) != map_cfg.unique_id:
            func_mod.map_config_id = map_cfg.unique_id

    lat_val = request_form.get('latitude')
    lng_val = request_form.get('longitude')
    if lat_val not in [None, ''] and lng_val not in [None, '']:
        try:
            func_mod.latitude = float(lat_val)
            func_mod.longitude = float(lng_val)
        except Exception:
            pass

    loc_src = request_form.get('location_source')
    if loc_src not in [None, '']:
        func_mod.location_source = loc_src

    icon_val = request_form.get('marker_icon')
    color_val = request_form.get('marker_color')
    size_val = request_form.get('marker_size')
    if hasattr(func_mod, 'marker_icon') and icon_val not in [None, '']:
        func_mod.marker_icon = icon_val
    if hasattr(func_mod, 'marker_color') and color_val not in [None, '']:
        func_mod.marker_color = color_val
    if hasattr(func_mod, 'marker_size') and size_val not in [None, '']:
        try:
            func_mod.marker_size = int(size_val)
        except Exception:
            pass
    # CustomController는 marker_* 컬럼이 없으므로 custom_options에도 넣어 둔다
    if isinstance(func_mod, CustomController):
        try:
            opts = json.loads(func_mod.custom_options) if func_mod.custom_options else {}
        except Exception:
            opts = {}
        if icon_val not in [None, '']:
            opts['marker_icon'] = icon_val
        if color_val not in [None, '']:
            opts['marker_color'] = color_val
        if size_val not in [None, '']:
            try:
                opts['marker_size'] = int(size_val)
            except Exception:
                pass
        func_mod.custom_options = json.dumps(opts)

    db.session.commit()


def function_mod(form):
    """Modify a Function."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None,
        "return_text": []
    }
    page_refresh = False

    try:
        func_mod = Function.query.filter(
            Function.unique_id == form.function_id.data).first()
        
        func_mod.name = form.name.data
        messages["name"] = form.name.data
        func_mod.log_level_debug = form.log_level_debug.data

        lat_val = getattr(form, 'latitude', None).data if hasattr(form, 'latitude') else request.form.get('latitude')
        lng_val = getattr(form, 'longitude', None).data if hasattr(form, 'longitude') else request.form.get('longitude')
        if lat_val not in [None, ''] and lng_val not in [None, '']:
            try:
                func_mod.latitude = float(lat_val)
                func_mod.longitude = float(lng_val)
            except Exception:
                pass  # keep previous coords on parse failure
        # if 둘 중 하나라도 비어 있으면 기존 값을 유지하여 덮어쓰지 않음

        loc_src = getattr(form, 'location_source', None).data if hasattr(form, 'location_source') else request.form.get('location_source')
        if loc_src not in [None, '']:
            func_mod.location_source = loc_src

        icon_val = getattr(form, 'marker_icon', None).data if hasattr(form, 'marker_icon') else request.form.get('marker_icon')
        color_val = getattr(form, 'marker_color', None).data if hasattr(form, 'marker_color') else request.form.get('marker_color')
        size_val = getattr(form, 'marker_size', None).data if hasattr(form, 'marker_size') else request.form.get('marker_size')
        if icon_val not in [None, '']:
            func_mod.marker_icon = icon_val or None
        if color_val not in [None, '']:
            func_mod.marker_color = color_val or None
        if size_val not in [None, '']:
            try:
                func_mod.marker_size = int(size_val)
            except Exception:
                pass

        if not messages["error"]:
            db.session.commit()
            messages["success"].append(f"{TRANSLATIONS['modify']['title']} {TRANSLATIONS['function']['title']}")
            page_refresh = True

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def function_del(function_id):
    """Delete a Function."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        actions = Actions.query.filter(
            Actions.function_id == function_id).all()
        for each_action in actions:
            delete_entry_with_id(
                Actions, each_action.unique_id, flash_message=False)
            
        device_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == function_id).all()
        for each_measurement in device_measurements:
            delete_entry_with_id(
                DeviceMeasurements,
                each_measurement.unique_id,
                flash_message=False)
            
        delete_entry_with_id(Function, function_id, flash_message=False)

        messages["success"].append(f"{TRANSLATIONS['delete']['title']} {TRANSLATIONS['function']['title']}")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def action_execute_all(form):
    """Execute All Actions."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    function_type = None
    func = None

    if form.function_type.data == 'conditional':
        function_type = TRANSLATIONS['conditional']['title']
        func = Conditional.query.filter(
            Conditional.unique_id == form.function_id.data).first()
    elif form.function_type.data == 'trigger':
        function_type = TRANSLATIONS['trigger']['title']
        func = Trigger.query.filter(
            Trigger.unique_id == form.function_id.data).first()
    elif form.function_type.data in ['function', 'function_actions']:
        function_type = TRANSLATIONS['function']['title']
        func = Function.query.filter(
            Function.unique_id == form.function_id.data).first()
    else:
        messages["error"].append(_("Unknown function type: '{}'").format(form.function_type.data))

    if not messages["error"]:
        try:
            control = DaemonControl()
            trigger_all_actions = threading.Thread(
                target=control.trigger_all_actions,
                args=(form.function_id.data,),
                kwargs={
                    'message': f"Executing all actions of {function_type} ({func.name}, ID {form.function_id.data}).",
                    'debug': func.log_level_debug
                }
            )
            trigger_all_actions.start()
            messages["success"].append(f"{gettext('Execute All')} {function_type} {TRANSLATIONS['actions']['title']}")
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages
