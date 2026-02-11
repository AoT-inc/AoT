# coding=utf-8
"""collection of Function endpoints."""
import json
import logging

import flask_login
from aot.functions.schema_sync import (
    read_ns, write_ns,
    read_ns_channels, write_ns_channels,
    get_namespace_schema, set_namespace_schema,
    ConflictError
)
from flask import (current_app, jsonify, redirect, render_template, request,
                   url_for, flash)
from flask_babel import gettext as _
from flask.blueprints import Blueprint
from sqlalchemy import and_, or_

from aot.config import INSTALL_DIRECTORY, CONDITIONAL_CONDITIONS, FUNCTION_INFO, FUNCTIONS

def _load_map_overlays_from_db(map_uuid):
    collection = {"type": "FeatureCollection", "features": []}
    if not map_uuid:
        return collection
    try:
        db_overlays = GeoShape.query.filter_by(geo_id=map_uuid).all()
        feats = []
        for ov in db_overlays:
            if not ov or not ov.feature:
                continue
            feat = ov.feature
            props = feat.get('properties', {}) or {}
            # Inject hierarchy metadata
            if 'level_id' not in props:
                props['level_id'] = ov.level_id
            if 'channel_id' not in props:
                props['channel_id'] = ov.channel_id
            feat['properties'] = props
            feats.append(feat)

        if feats:
            collection['features'] = feats
    except Exception:
        pass
    return collection
from aot.config_devices_units import MEASUREMENTS
from aot.databases.models import (PID, Actions, Camera, Conditional,
                                     ConditionalConditions, Conversion,
                                     CustomController, DeviceMeasurements,
                                     DisplayOrder, Function, FunctionChannel,
                                     Input, GeoMap, GeoShape, Measurement, Method, Misc,
                                     NoteTags, Output, OutputChannel, Trigger,
                                     Unit, User)
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import (forms_action, forms_conditional,
                                       forms_custom_controller, forms_function,
                                       forms_pid, forms_trigger)
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import (utils_action, utils_conditional,
                                       utils_controller, utils_function,
                                       utils_general, utils_pid, utils_trigger)
from aot.aot_flask.utils.utils_map_config import ensure_map_config
from aot.aot_flask.utils.utils_general import generate_form_action_list
from aot.aot_flask.utils.utils_misc import determine_controller_type
from aot.utils.actions import parse_action_information
from aot.utils.functions import parse_function_information
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import output_types, parse_output_information
from aot.utils.sunriseset import suntime_calculate_next_sunrise_sunset_epoch
from aot.utils.system_pi import (
    add_custom_measurements, add_custom_units, csv_to_list_of_str,
    parse_custom_option_values,
    parse_custom_option_values_function_channels_json)

logger = logging.getLogger('aot.aot_flask.routes_function')

blueprint = Blueprint('routes_function',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/function_save_order', methods=['POST'])
@flask_login.login_required
def function_save_order():
    try:
        data = request.get_json()
        function_id = data.get('function_id')
        order_map = data.get('order')  # {action_id: y_pos, ...}
        
        if not function_id or order_map is None:
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400

        # Update each action
        for action_unique_id, y_pos in order_map.items():
            action = Actions.query.filter_by(unique_id=action_unique_id).first()
            if action:
                try:
                    opts = json.loads(action.custom_options) if action.custom_options else {}
                except:
                    opts = {}
                
                opts['position'] = int(y_pos)
                action.custom_options = json.dumps(opts)
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error saving function order: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@blueprint.route('/function_submit', methods=['POST'])
@flask_login.login_required
def page_function_submit():
    """Submit form for Data page"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False
    action_id = None
    condition_id = None
    function_id = None
    dep_unmet = ''
    dep_name = ''
    dep_list = []
    dep_message = ''

    if not utils_general.user_has_permission('edit_controllers'):
        messages["error"].append("Your permissions do not allow this action")

    form_actions = forms_action.Actions()
    form_add_function = forms_function.FunctionAdd()
    form_conditional = forms_conditional.Conditional()
    form_conditional_conditions = forms_conditional.ConditionalConditions()
    form_function = forms_custom_controller.CustomController()
    form_function_base = forms_function.FunctionMod()
    form_mod_pid_base = forms_pid.PIDModBase()
    form_mod_pid_output_raise = forms_pid.PIDModRelayRaise()
    form_mod_pid_output_lower = forms_pid.PIDModRelayLower()
    form_mod_pid_pwm_raise = forms_pid.PIDModPWMRaise()
    form_mod_pid_pwm_lower = forms_pid.PIDModPWMLower()
    form_mod_pid_value_raise = forms_pid.PIDModValueRaise()
    form_mod_pid_value_lower = forms_pid.PIDModValueLower()
    form_mod_pid_volume_raise = forms_pid.PIDModVolumeRaise()
    form_mod_pid_volume_lower = forms_pid.PIDModVolumeLower()
    form_trigger = forms_trigger.Trigger()

    if not messages["error"]:
        if form_add_function.function_add.data:
            (messages,
             dep_name,
             dep_list,
             dep_message,
             function_id) = utils_function.function_add(
                form_add_function)
            if dep_list:
                dep_unmet = form_add_function.function_type.data
        else:
            function_id = form_function_base.function_id.data
            controller_type = determine_controller_type(function_id)
            if form_function_base.function_mod.data:
                if controller_type == "Conditional":
                    messages = utils_conditional.conditional_mod(
                        form_conditional)
                    if not messages["error"]:
                        utils_function.update_location_marker(function_id, request.form)
                        page_refresh = True
                elif controller_type == "PID":
                    messages, page_refresh = utils_pid.pid_mod(
                        form_mod_pid_base,
                        form_mod_pid_pwm_raise,
                        form_mod_pid_pwm_lower,
                        form_mod_pid_output_raise,
                        form_mod_pid_output_lower,
                        form_mod_pid_value_raise,
                        form_mod_pid_value_lower,
                        form_mod_pid_volume_raise,
                        form_mod_pid_volume_lower)
                elif controller_type == "Trigger":
                    messages, page_refresh = utils_trigger.trigger_mod(form_trigger)
                    if not messages["error"]:
                        utils_function.update_location_marker(function_id, request.form)
                        page_refresh = True
                elif controller_type == "Function":
                    messages, page_refresh = utils_function.function_mod(form_function_base)
                elif controller_type == "Function_Custom":
                    messages, page_refresh = utils_controller.controller_mod(
                        form_function, request.form)
                    if not messages["error"]:
                        utils_function.update_location_marker(function_id, request.form)
                        page_refresh = True
            elif form_function_base.function_duplicate.data:
                messages, function_id = utils_function.function_duplicate(form_function_base)
            elif form_function_base.function_delete.data:
                if controller_type == "Conditional":
                    messages = utils_conditional.conditional_del(function_id)
                elif controller_type == "PID":
                    messages = utils_pid.pid_del(function_id)
                elif controller_type == "Trigger":
                    messages = utils_trigger.trigger_del(function_id)
                elif controller_type == "Function":
                    messages = utils_function.function_del(function_id)
                elif controller_type == "Function_Custom":
                    messages = utils_controller.controller_del(function_id)
            elif form_function_base.function_activate.data:
                if controller_type == "Conditional":
                    messages = utils_conditional.conditional_activate(
                        function_id)
                elif controller_type == "PID":
                    messages = utils_pid.pid_activate(function_id)
                elif controller_type == "Trigger":
                    messages = utils_trigger.trigger_activate(function_id)
                elif controller_type == "Function_Custom":
                    messages = utils_controller.controller_activate(
                        function_id)
            elif form_function_base.function_deactivate.data:
                if controller_type == "Conditional":
                    messages = utils_conditional.conditional_deactivate(
                        function_id)
                elif controller_type == "PID":
                    messages = utils_pid.pid_deactivate(function_id)
                elif controller_type == "Trigger":
                    messages = utils_trigger.trigger_deactivate(function_id)
                elif controller_type == "Function_Custom":
                    messages = utils_controller.controller_deactivate(
                        function_id)
            elif form_function_base.execute_all_actions.data:
                if controller_type == "Conditional":
                    messages = utils_function.action_execute_all(
                        form_conditional)
                elif controller_type == "Trigger":
                    messages = utils_function.action_execute_all(
                        form_conditional)
                elif controller_type == "Function":
                    messages = utils_function.action_execute_all(
                        form_conditional)

            # PID
            elif form_mod_pid_base.pid_hold.data:
                messages = utils_pid.pid_manipulate(
                    form_mod_pid_base.function_id.data, 'Hold')
            elif form_mod_pid_base.pid_pause.data:
                messages = utils_pid.pid_manipulate(
                    form_mod_pid_base.function_id.data, 'Pause')
            elif form_mod_pid_base.pid_resume.data:
                messages = utils_pid.pid_manipulate(
                    form_mod_pid_base.function_id.data, 'Resume')

            # Actions
            elif form_actions.add_action.data:
                (messages,
                 dep_name,
                 dep_list,
                 action_id,
                 page_refresh) = utils_action.action_add(form_actions, request.form)
                if dep_list:
                    dep_unmet = form_actions.action_type.data
                function_id = form_actions.device_id.data
            elif form_actions.save_action.data:
                messages = utils_action.action_mod(
                    form_actions, request.form)
                function_id = form_actions.device_id.data
            elif form_actions.delete_action.data:
                messages = utils_action.action_del(form_actions)
                page_refresh = True
                function_id = form_actions.device_id.data
                action_id = form_actions.action_id.data

            # Conditions
            elif form_conditional.add_condition.data:
                (messages,
                 condition_id) = utils_conditional.conditional_condition_add(
                    form_conditional)
                page_refresh = True
            elif form_conditional_conditions.save_condition.data:
                messages = utils_conditional.conditional_condition_mod(
                    form_conditional_conditions)
            elif form_conditional_conditions.delete_condition.data:
                messages = utils_conditional.conditional_condition_del(
                    form_conditional_conditions)
                page_refresh = True
                condition_id = form_conditional_conditions.conditional_condition_id.data

            # Custom action
            else:
                custom_button = False
                for key in request.form.keys():
                    if key.startswith('custom_button_'):
                        custom_button = True
                        break
                if custom_button:
                    messages = utils_general.custom_command(
                        "Function_Custom",
                        parse_function_information(),
                        form_function.function_id.data,
                        request.form)
                else:
                    messages["error"].append("Unknown function directive")

    # Force screen refresh if location/marker fields are included
    marker_keys = ['latitude', 'longitude', 'location_source', 'marker_icon', 'marker_color', 'marker_size']
    if any(k in request.form for k in marker_keys):
        page_refresh = True

    return jsonify(data={
        'action_id': action_id,
        'condition_id': condition_id,
        'function_id': function_id,
        'dep_name': dep_name,
        'dep_list': dep_list,
        'dep_unmet': dep_unmet,
        'dep_message': dep_message,
        'messages': messages,
        "page_refresh": page_refresh
    })


@blueprint.route('/save_function_layout', methods=['POST'])
def save_function_layout():
    """Save positions of functions."""
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))
    data = request.get_json()
    keys = ('id', 'y')
    for each_function in data:
        if all(k in each_function for k in keys):
            controller_type = determine_controller_type(each_function['id'])

            if controller_type == "Conditional":
                mod_device = Conditional.query.filter(
                    Conditional.unique_id == each_function['id']).first()
            elif controller_type == "PID":
                mod_device = PID.query.filter(
                    PID.unique_id == each_function['id']).first()
            elif controller_type == "Trigger":
                mod_device = Trigger.query.filter(
                    Trigger.unique_id == each_function['id']).first()
            elif controller_type == "Function":
                mod_device = Function.query.filter(
                    Function.unique_id == each_function['id']).first()
            elif controller_type == "Function_Custom":
                mod_device = CustomController.query.filter(
                    CustomController.unique_id == each_function['id']).first()
            else:
                logger.info("Could not find controller with ID {}".format(
                    each_function['id']))
                return "error"
            if mod_device:
                mod_device.position_y = each_function['y']
    db.session.commit()
    return "success"


# ---------------------------
# Generic namespaced config API (controller + channels)
# ---------------------------

@blueprint.route('/aot/config/<controller_id>/<ns>', methods=['GET'])
@flask_login.login_required
def api_get_namespace_schema(controller_id, ns):
    """Return combined schema for a namespace: {'cfg_rev', 'global', 'channels'}."""
    try:
        schema = get_namespace_schema(controller_id, ns)
        return jsonify(schema), 200
    except Exception as e:
        logger.exception(f"[config:get] controller_id={controller_id}, ns={ns}, err={e}")
        return jsonify({"error": "internal_error"}), 500


@blueprint.route('/aot/config/<controller_id>/<ns>', methods=['POST'])
@flask_login.login_required
def api_set_namespace_schema(controller_id, ns):
    """Save global(+channels) atomically with optimistic lock on cfg_rev."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({"error": "permission_denied"}), 403
    data = request.get_json(force=True, silent=True) or {}
    try:
        expect_rev = data.get("cfg_rev", None)
        global_payload = data.get("global", {}) or {}
        channels_payload = data.get("channels", None)  # may be None

        new_rev = set_namespace_schema(
            controller_id=controller_id,
            ns=ns,
            global_payload=global_payload,
            channels_payload=channels_payload,
            expect_rev=expect_rev
        )
        schema = get_namespace_schema(controller_id, ns)
        return jsonify(schema), 200
    except ConflictError:
        return jsonify({"error": "cfg_rev_conflict"}), 409
    except Exception as e:
        logger.exception(f"[config:set] controller_id={controller_id}, ns={ns}, err={e}")
        return jsonify({"error": "internal_error"}), 500


@blueprint.route('/aot/config/<controller_id>/<ns>', methods=['PATCH'])
@flask_login.login_required
def api_patch_namespace_global(controller_id, ns):
    """Patch only the global(controller-level) payload for a namespace."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({"error": "permission_denied"}), 403
    payload = request.get_json(force=True, silent=True) or {}
    try:
        expect_rev = payload.pop("cfg_rev", None)
        current = read_ns(controller_id, ns)
        # merge incoming keys into current, excluding None that are not intended deletions
        for k, v in list(payload.items()):
            if k == "cfg_rev":
                continue
            current[k] = v
        new_rev = write_ns(controller_id, ns, current, expect_rev=expect_rev)
        schema = get_namespace_schema(controller_id, ns)
        return jsonify(schema), 200
    except ConflictError:
        return jsonify({"error": "cfg_rev_conflict"}), 409
    except Exception as e:
        logger.exception(f"[config:patch-global] controller_id={controller_id}, ns={ns}, err={e}")
        return jsonify({"error": "internal_error"}), 500


@blueprint.route('/aot/config/<controller_id>/<ns>/channels', methods=['POST'])
@flask_login.login_required
def api_set_namespace_channels(controller_id, ns):
    """Save only channel-level payloads for a namespace."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({"error": "permission_denied"}), 403
    data = request.get_json(force=True, silent=True) or {}
    try:
        items = data.get("channels", [])
        write_ns_channels(controller_id, ns, items)
        chans = read_ns_channels(controller_id, ns)
        return jsonify({"channels": chans}), 200
    except Exception as e:
        logger.exception(f"[config:set-channels] controller_id={controller_id}, ns={ns}, err={e}")
        return jsonify({"error": "internal_error"}), 500


@blueprint.route('/aot/config/<controller_id>/<ns>/rev', methods=['GET'])
@flask_login.login_required
def api_get_namespace_rev(controller_id, ns):
    """Lightweight rev endpoint for widgets to poll."""
    try:
        glob = read_ns(controller_id, ns)
        return jsonify({"cfg_rev": int(glob.get("cfg_rev", 0) or 0)}), 200
    except Exception as e:
        logger.exception(f"[config:get-rev] controller_id={controller_id}, ns={ns}, err={e}")
        return jsonify({"error": "internal_error"}), 500


@blueprint.route('/function', methods=('GET', 'POST'))
@flask_login.login_required
def page_function():
    """Display Function page options."""
    function_type = request.args.get('function_type', None)
    function_id = request.args.get('function_id', None)
    action_id = request.args.get('action_id', None)
    condition_id = request.args.get('condition_id', None)

    each_function = None
    each_action = None
    each_condition = None
    function_page_entry = None
    function_page_options = None
    controller_type = None
    trigger_sequence_options = {}

    if function_type in ['entry', 'options', 'conditions', 'actions'] and function_id != '0':
        controller_type = determine_controller_type(function_id)
        if not controller_type:
            flash(_("Function not found or deleted."), "error")
            return redirect(url_for('.page_function'))

        if controller_type == "Conditional":
            each_function = Conditional.query.filter(
                Conditional.unique_id == function_id).first()
            function_page_entry = 'pages/function_options/conditional_entry.html'
            function_page_options = 'pages/function_options/conditional_options.html'
        elif controller_type == "PID":
            each_function = PID.query.filter(
                PID.unique_id == function_id).first()
            function_page_entry = 'pages/function_options/pid_entry.html'
            function_page_options = 'pages/function_options/pid_options.html'
        elif controller_type == "Trigger":
            each_function = Trigger.query.filter(
                Trigger.unique_id == function_id).first()
            if each_function:
                 current_app.logger.info(f"DEBUG: page_function Trigger found: {each_function.unique_id}, type={each_function.trigger_type}")

            if each_function and each_function.trigger_type == 'trigger_sequence':
                current_app.logger.info(f"DEBUG: page_function LOAD trigger_sequence {each_function.unique_id}: start={each_function.timer_start_time}, limit={each_function.timer_end_time}, period={each_function.period}")
                function_page_entry = 'pages/function_options/trigger_sequence_entry.html'
                function_page_options = 'pages/function_options/trigger_sequence_options.html'
            else:
                function_page_entry = 'pages/function_options/trigger_entry.html'
                function_page_options = 'pages/function_options/trigger_options.html'
        elif controller_type == "Function":
            each_function = Function.query.filter(
                Function.unique_id == function_id).first()
            function_page_entry = 'pages/function_options/function_entry.html'
            function_page_options = 'pages/function_options/function_options.html'
        elif controller_type == "Function_Custom":
            each_function = CustomController.query.filter(
                CustomController.unique_id == function_id).first()
            function_page_entry = 'pages/function_options/custom_function_entry.html'
            function_page_options = 'pages/function_options/custom_function_options.html'

        if function_type == 'actions' and action_id:
            each_action = Actions.query.filter(
                Actions.unique_id == action_id).first()
            if each_action:
                controller_type = determine_controller_type(each_action.function_id)

        if function_type == 'conditions'and  condition_id:
            each_condition = ConditionalConditions.query.filter(
                ConditionalConditions.unique_id == condition_id).first()

    action = Actions.query.all()
    camera = Camera.query.all()
    conditional = Conditional.query.all()
    conditional_conditions = ConditionalConditions.query.all()
    function = CustomController.query.all()
    map_cfg_committed = False
    for func in function:
        if not getattr(func, 'map_config_id', None):
            map_cfg = ensure_map_config(
                None,
                func.name,
                func.latitude,
                func.longitude
            )
            func.map_config_id = map_cfg.unique_id
            map_cfg_committed = True
    if map_cfg_committed:
        db.session.commit()
    function_channel = FunctionChannel.query.all()
    function_dev = Function.query.all()
    input_dev = Input.query.all()
    measurement = Measurement.query.all()
    method = Method.query.all()
    misc = Misc.query.first()
    tags = NoteTags.query.all()
    output = Output.query.all()
    output_channel = OutputChannel.query.all()
    pid = PID.query.all()
    trigger = Trigger.query.all()
    unit = Unit.query.all()
    user = User.query.all()

    display_order_function = csv_to_list_of_str(
        DisplayOrder.query.first().function)

    form_add_function = forms_function.FunctionAdd()
    form_mod_pid_base = forms_pid.PIDModBase()
    form_mod_pid_output_raise = forms_pid.PIDModRelayRaise()
    form_mod_pid_output_lower = forms_pid.PIDModRelayLower()
    form_mod_pid_pwm_raise = forms_pid.PIDModPWMRaise()
    form_mod_pid_pwm_lower = forms_pid.PIDModPWMLower()
    form_mod_pid_value_raise = forms_pid.PIDModValueRaise()
    form_mod_pid_value_lower = forms_pid.PIDModValueLower()
    form_mod_pid_volume_raise = forms_pid.PIDModVolumeRaise()
    form_mod_pid_volume_lower = forms_pid.PIDModVolumeLower()
    form_function_base = forms_function.FunctionMod()
    form_trigger = forms_trigger.Trigger()
    form_conditional = forms_conditional.Conditional()
    form_conditional_conditions = forms_conditional.ConditionalConditions()
    form_function = forms_custom_controller.CustomController()
    form_actions = forms_action.Actions()

    dict_controllers = parse_function_information()
    dict_actions = parse_action_information()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    dict_inputs = parse_input_information()
    dict_outputs = parse_output_information()

    custom_options_values_controllers = parse_custom_option_values(
        function, dict_controller=dict_controllers)
    custom_options_values_function_channels = parse_custom_option_values_function_channels_json(
        function_channel, dict_controller=function, key_name='custom_channel_options')

    custom_options_values_actions = {}
    for each_action_dev in action:
        try:
            custom_options_values_actions[each_action_dev.unique_id] = json.loads(each_action_dev.custom_options)
        except:
            custom_options_values_actions[each_action_dev.unique_id] = {}

    # Sequence Options
    trigger_sequence_options = {}
    if each_function and getattr(each_function, 'trigger_type', '') == 'trigger_sequence':
        try:
            trigger_sequence_options = json.loads(each_function.custom_options)
        except:
            pass

    # Create lists of built-in and custom functions
    choices_functions = []
    for choice_function in FUNCTIONS:
        choices_functions.append({'value': choice_function[0], 'item': choice_function[1]})
    choices_custom_functions = utils_general.choices_custom_functions()
    # Combine function lists
    choices_functions_add = choices_functions + choices_custom_functions
    # Add Sequence
    choices_functions_add.append({'value': 'trigger_sequence', 'item': _('Sequence')})
    # Sort combined list
    choices_functions_add = sorted(choices_functions_add, key=lambda i: i['item'])

    custom_commands = {}
    for choice_function in function:
        if 'custom_commands' in dict_controllers[choice_function.device]:
            custom_commands[choice_function.device] = True

    # Generate Action dropdown for use with Inputs
    choices_actions = []
    list_actions_sorted = generate_form_action_list(dict_actions, application=["functions"])
    for name in list_actions_sorted:
        choices_actions.append((name, dict_actions[name]['name']))

    # Create list of choices to be used in dropdown menus
    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)
    choices_input_devices = utils_general.choices_input_devices(input_dev)
    choices_method = utils_general.choices_methods(method)
    choices_output = utils_general.choices_outputs(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_channels = utils_general.choices_outputs_channels(
        output, output_channel, dict_outputs)
    choices_output_channels_measurements = utils_general.choices_outputs_channels_measurements(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)
    choices_tag = utils_general.choices_tags(tags)
    choices_measurements_units = utils_general.choices_measurements_units(
        measurement, unit)

    choices_controller_ids = utils_general.choices_controller_ids()

    actions_dict = {
        'conditional': {},
        'trigger': {}
    }
    for each_action_dev in action:
        if (each_action_dev.function_type == 'conditional' and
                each_action_dev.unique_id not in actions_dict['conditional']):
            actions_dict['conditional'][each_action_dev.function_id] = True
        if (each_action_dev.function_type == 'trigger' and
                each_action_dev.unique_id not in actions_dict['trigger']):
            actions_dict['trigger'][each_action_dev.function_id] = True

    conditions_dict = {}
    for each_cond in conditional_conditions:
        if each_cond.unique_id not in conditions_dict:
            conditions_dict[each_cond.conditional_id] = True

    controllers = []
    controllers_all = [('Input', input_dev),
                       ('Conditional', conditional),
                       ('Function', function),
                       ('PID', pid),
                       ('Trigger', trigger)]
    for each_controller in controllers_all:
        for each_cont in each_controller[1]:
            controllers.append((each_controller[0],
                                each_cont.unique_id,
                                each_cont.id,
                                each_cont.name))

    # Create dict of Function names
    names_function = {}
    all_elements = [conditional, pid, trigger, function_dev, function]
    for each_element in all_elements:
        for each_func_name in each_element:
            names_function[each_func_name.unique_id] = '[{id}] {name}'.format(
                id=each_func_name.unique_id.split('-')[0], name=each_func_name.name)

    # Calculate sunrise/sunset times if set up properly
    sunrise_set_calc = {}
    for each_trigger in trigger:
        if each_trigger.trigger_type == 'trigger_sunrise_sunset':
            sunrise_set_calc[each_trigger.unique_id] = {}
            if not current_app.config['TESTING']:
                try:
                    sunrise = suntime_calculate_next_sunrise_sunset_epoch(
                        each_trigger.latitude, each_trigger.longitude, 0, 0, "sunrise", return_dt=True)
                    sunset = suntime_calculate_next_sunrise_sunset_epoch(
                        each_trigger.latitude, each_trigger.longitude, 0, 0, "sunset", return_dt=True)

                    # Adjust for date offset
                    offset_rise = suntime_calculate_next_sunrise_sunset_epoch(
                        each_trigger.latitude, each_trigger.longitude, each_trigger.date_offset_days,
                        each_trigger.time_offset_minutes, "sunrise", return_dt=True)
                    offset_set = suntime_calculate_next_sunrise_sunset_epoch(
                        each_trigger.latitude, each_trigger.longitude, each_trigger.date_offset_days,
                        each_trigger.time_offset_minutes, "sunset", return_dt=True)

                    sunrise_set_calc[each_trigger.unique_id]['sunrise'] = (
                        sunrise.strftime("%Y-%m-%d %H:%M"))
                    sunrise_set_calc[each_trigger.unique_id]['sunset'] = (
                        sunset.strftime("%Y-%m-%d %H:%M"))
                    sunrise_set_calc[each_trigger.unique_id]['offset_sunrise'] = (
                        offset_rise.strftime("%Y-%m-%d %H:%M"))
                    sunrise_set_calc[each_trigger.unique_id]['offset_sunset'] = (
                        offset_set.strftime("%Y-%m-%d %H:%M"))
                except:
                    logger.exception(1)
                    sunrise_set_calc[each_trigger.unique_id]['sunrise'] = "ERROR"
                    sunrise_set_calc[each_trigger.unique_id]['sunrise'] = "ERROR"
                    sunrise_set_calc[each_trigger.unique_id]['offset_sunrise'] = "ERROR"
                    sunrise_set_calc[each_trigger.unique_id]['offset_sunset'] = "ERROR"

    # Map list (common for function/options)
    map_configs = []
    try:
        map_configs = GeoMap.query.filter(
            or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
        ).all()
    except Exception:
        map_configs = []

    map_config_uuid = ''
    map_overlays = {"type": "FeatureCollection", "features": []}

    if not function_type:
        # Create integrated list to guarantee GridStack order
        # 1. Type tagging for each object
        for item in conditional:
            item._controller_type = 'Conditional'
        for item in pid:
            item._controller_type = 'PID'
        for item in trigger:
            item._controller_type = 'Trigger'
        for item in function_dev:
            item._controller_type = 'Function'
        for item in function:
            item._controller_type = 'Function_Custom'

        # 2. List integration and sorting (position_y priority, unique_id secondary)
        all_functions_sorted = conditional + pid + trigger + function_dev + function
        all_functions_sorted.sort(key=lambda x: (getattr(x, 'position_y', 0) or 0, getattr(x, 'unique_id', '')))

        return render_template('pages/function.html',
                               and_=and_,
                               action=action,
                               actions_dict=actions_dict,
                               camera=camera,
                               choices_actions=choices_actions,
                               choices_controller_ids=choices_controller_ids,
                               choices_custom_functions=choices_custom_functions,
                               choices_function=choices_function,
                               choices_functions=choices_functions,
                               choices_functions_add=choices_functions_add,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_tag=choices_tag,
                               conditional_conditions_list=CONDITIONAL_CONDITIONS,
                               conditional=conditional,
                               conditional_conditions=conditional_conditions,
                               conditions_dict=conditions_dict,
                               controllers=controllers,
                               controller_type=controller_type,
                               function=function,
                               function_channel=function_channel,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_controllers=custom_options_values_controllers,
                               custom_options_values_function_channels=custom_options_values_function_channels,
                               dict_actions=dict_actions,
                               dict_controllers=dict_controllers,
                               dict_inputs=dict_inputs,
                               dict_measurements=dict_measurements,
                               dict_outputs=dict_outputs,
                               dict_units=dict_units,
                               display_order_function=display_order_function,
                               form_conditional=form_conditional,
                               form_conditional_conditions=form_conditional_conditions,
                               form_function=form_function,
                               form_actions=form_actions,
                               form_add_function=form_add_function,
                               form_function_base=form_function_base,
                               form_mod_pid_base=form_mod_pid_base,
                               form_mod_pid_pwm_raise=form_mod_pid_pwm_raise,
                               form_mod_pid_pwm_lower=form_mod_pid_pwm_lower,
                               form_mod_pid_output_raise=form_mod_pid_output_raise,
                               form_mod_pid_output_lower=form_mod_pid_output_lower,
                               form_mod_pid_value_raise=form_mod_pid_value_raise,
                               form_mod_pid_value_lower=form_mod_pid_value_lower,
                               form_mod_pid_volume_raise=form_mod_pid_volume_raise,
                               form_mod_pid_volume_lower=form_mod_pid_volume_lower,
                               form_trigger=form_trigger,
                               function_dev=function_dev,
                               function_info=FUNCTION_INFO,
                               function_types=FUNCTIONS,
                               input=input_dev,
                               method=method,
                               misc=misc,
                               names_function=names_function,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               map_configs=map_configs,
                               map_config_uuid=map_config_uuid,
                               map_config_id=map_config_uuid, # Legacy
                               sunrise_set_calc=sunrise_set_calc,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               tags=tags,
                               trigger=trigger,
                               units=MEASUREMENTS,
                               user=user,
                               map_overlays=map_overlays,
                               all_functions_sorted=all_functions_sorted)
    elif function_type == 'entry':
        map_configs = GeoMap.query.filter(
            or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
        ).all()
        map_config_uuid = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_function and isinstance(each_function, (CustomController, Trigger, Conditional, PID, Function)):
            map_cfg = ensure_map_config(
                each_function.map_config_id,
                each_function.name,
                each_function.latitude,
                each_function.longitude
            )
            if each_function.map_config_id != map_cfg.unique_id:
                each_function.map_config_id = map_cfg.unique_id
                db.session.commit()
            map_config_uuid = map_cfg.unique_id
            map_overlays = _load_map_overlays_from_db(map_cfg.unique_id)
        return render_template(function_page_entry,
                               and_=and_,
                               action=action,
                               actions_dict=actions_dict,
                               camera=camera,
                               choices_actions=choices_actions,
                               choices_controller_ids=choices_controller_ids,
                               choices_custom_functions=choices_custom_functions,
                               choices_function=choices_function,
                               choices_functions=choices_functions,
                               choices_functions_add=choices_functions_add,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_tag=choices_tag,
                               conditional_conditions_list=CONDITIONAL_CONDITIONS,
                               conditional=conditional,
                               conditional_conditions=conditional_conditions,
                               conditions_dict=conditions_dict,
                               controllers=controllers,
                               controller_type=controller_type,
                               function=function,
                               function_channel=function_channel,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_controllers=custom_options_values_controllers,
                               custom_options_values_function_channels=custom_options_values_function_channels,
                               dict_actions=dict_actions,
                               dict_controllers=dict_controllers,
                               dict_measurements=dict_measurements,
                               dict_outputs=dict_outputs,
                               dict_units=dict_units,
                               display_order_function=display_order_function,
                               each_function=each_function,
                               form_conditional=form_conditional,
                               form_conditional_conditions=form_conditional_conditions,
                               form_function=form_function,
                               form_actions=form_actions,
                               form_add_function=form_add_function,
                               form_function_base=form_function_base,
                               form_mod_pid_base=form_mod_pid_base,
                               form_mod_pid_pwm_raise=form_mod_pid_pwm_raise,
                               form_mod_pid_pwm_lower=form_mod_pid_pwm_lower,
                               form_mod_pid_output_raise=form_mod_pid_output_raise,
                               form_mod_pid_output_lower=form_mod_pid_output_lower,
                               form_mod_pid_value_raise=form_mod_pid_value_raise,
                               form_mod_pid_value_lower=form_mod_pid_value_lower,
                               form_mod_pid_volume_raise=form_mod_pid_volume_raise,
                               form_mod_pid_volume_lower=form_mod_pid_volume_lower,
                               form_trigger=form_trigger,
                               function_dev=function_dev,
                               function_info=FUNCTION_INFO,
                               function_types=FUNCTIONS,
                               input=input_dev,
                               method=method,
                               misc=misc,
                               names_function=names_function,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               sunrise_set_calc=sunrise_set_calc,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               tags=tags,
                               trigger=trigger,
                               units=MEASUREMENTS,
                               user=user,
                               map_configs=map_configs,
                               map_config_uuid=map_config_uuid,
                               map_config_id=map_config_uuid,
                               map_overlays=map_overlays)
    elif function_type == 'options':
        map_configs = GeoMap.query.filter(
            or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
        ).all()
        map_config_uuid = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_function and isinstance(each_function, (CustomController, Trigger, Conditional, PID, Function)):
            map_cfg = ensure_map_config(
                each_function.map_config_id,
                each_function.name,
                each_function.latitude,
                each_function.longitude
            )
            if each_function.map_config_id != map_cfg.unique_id:
                each_function.map_config_id = map_cfg.unique_id
                db.session.commit()
            map_config_uuid = map_cfg.unique_id
            map_overlays = _load_map_overlays_from_db(map_cfg.unique_id)
        return render_template(function_page_options,
                               and_=and_,
                               action=action,
                               actions_dict=actions_dict,
                               camera=camera,
                               choices_actions=choices_actions,
                               choices_controller_ids=choices_controller_ids,
                               choices_custom_functions=choices_custom_functions,
                               choices_function=choices_function,
                               choices_functions=choices_functions,
                               choices_functions_add=choices_functions_add,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_tag=choices_tag,
                               conditional_conditions_list=CONDITIONAL_CONDITIONS,
                               conditional=conditional,
                               conditional_conditions=conditional_conditions,
                               conditions_dict=conditions_dict,
                               controllers=controllers,
                               controller_type=controller_type,
                               each_function=each_function,
                               function=function,
                               function_channel=function_channel,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_controllers=custom_options_values_controllers,
                               custom_options_values_function_channels=custom_options_values_function_channels,
                               dict_actions=dict_actions,
                               dict_controllers=dict_controllers,
                               dict_measurements=dict_measurements,
                               dict_outputs=dict_outputs,
                               dict_units=dict_units,
                               display_order_function=display_order_function,
                               map_config_id=map_config_uuid,
                               map_configs=map_configs,
                               form_conditional=form_conditional,
                               form_conditional_conditions=form_conditional_conditions,
                               form_function=form_function,
                               form_actions=form_actions,
                               form_add_function=form_add_function,
                               form_function_base=form_function_base,
                               form_mod_pid_base=form_mod_pid_base,
                               form_mod_pid_pwm_raise=form_mod_pid_pwm_raise,
                               form_mod_pid_pwm_lower=form_mod_pid_pwm_lower,
                               form_mod_pid_output_raise=form_mod_pid_output_raise,
                               form_mod_pid_output_lower=form_mod_pid_output_lower,
                               form_mod_pid_value_raise=form_mod_pid_value_raise,
                               form_mod_pid_value_lower=form_mod_pid_value_lower,
                               form_mod_pid_volume_raise=form_mod_pid_volume_raise,
                               form_mod_pid_volume_lower=form_mod_pid_volume_lower,
                               form_trigger=form_trigger,
                               function_dev=function_dev,
                               function_info=FUNCTION_INFO,
                               function_types=FUNCTIONS,
                               input=input_dev,
                               method=method,
                               misc=misc,
                               names_function=names_function,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               sunrise_set_calc=sunrise_set_calc,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               tags=tags,
                               trigger=trigger,
                               units=MEASUREMENTS,
                               user=user,
                               map_overlays=map_overlays,
                               trigger_sequence_options=trigger_sequence_options)
    elif function_type == 'actions':
        if isinstance(each_function, Trigger) and each_function.trigger_type == 'trigger_sequence':
            template = 'pages/function_options/trigger_sequence_actions.html'
        elif (isinstance(each_function, Trigger) or 
              (isinstance(each_function, (CustomController, Trigger, Conditional, PID, Function)) and each_function.function_type == 'function_actions')):
            template = 'pages/function_options/trigger_actions.html'
        else:
            template = 'pages/actions.html'
            
        return render_template(template,
                               and_=and_,
                               action=action,
                               actions_dict=actions_dict,
                               camera=camera,
                               choices_actions=choices_actions,
                               choices_controller_ids=choices_controller_ids,
                               choices_custom_functions=choices_custom_functions,
                               choices_function=choices_function,
                               choices_functions=choices_functions,
                               choices_functions_add=choices_functions_add,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_tag=choices_tag,
                               conditional_conditions_list=CONDITIONAL_CONDITIONS,
                               conditional=conditional,
                               conditional_conditions=conditional_conditions,
                               conditions_dict=conditions_dict,
                               controllers=controllers,
                               controller_type=controller_type,
                               each_action=each_action,
                               each_function=each_function,
                               function=function,
                               function_channel=function_channel,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_controllers=custom_options_values_controllers,
                               custom_options_values_function_channels=custom_options_values_function_channels,
                               dict_actions=dict_actions,
                               dict_controllers=dict_controllers,
                               dict_measurements=dict_measurements,
                               dict_outputs=dict_outputs,
                               dict_units=dict_units,
                               display_order_function=display_order_function,
                               form_conditional=form_conditional,
                               form_conditional_conditions=form_conditional_conditions,
                               form_function=form_function,
                               form_actions=form_actions,
                               form_add_function=form_add_function,
                               form_function_base=form_function_base,
                               form_mod_pid_base=form_mod_pid_base,
                               form_mod_pid_pwm_raise=form_mod_pid_pwm_raise,
                               form_mod_pid_pwm_lower=form_mod_pid_pwm_lower,
                               form_mod_pid_output_raise=form_mod_pid_output_raise,
                               form_mod_pid_output_lower=form_mod_pid_output_lower,
                               form_mod_pid_value_raise=form_mod_pid_value_raise,
                               form_mod_pid_value_lower=form_mod_pid_value_lower,
                               form_mod_pid_volume_raise=form_mod_pid_volume_raise,
                               form_mod_pid_volume_lower=form_mod_pid_volume_lower,
                               form_trigger=form_trigger,
                               function_dev=function_dev,
                               function_info=FUNCTION_INFO,
                               function_types=FUNCTIONS,
                               input=input_dev,
                               method=method,
                               misc=misc,
                               names_function=names_function,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               sunrise_set_calc=sunrise_set_calc,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               tags=tags,
                               trigger=trigger,
                               units=MEASUREMENTS,
                               user=user,
                               map_overlays=map_overlays)
    elif function_type == 'conditions':
        return render_template('pages/function_options/conditional_condition.html',
                               and_=and_,
                               action=action,
                               actions_dict=actions_dict,
                               camera=camera,
                               choices_controller_ids=choices_controller_ids,
                               choices_custom_functions=choices_custom_functions,
                               choices_function=choices_function,
                               choices_functions=choices_functions,
                               choices_functions_add=choices_functions_add,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_tag=choices_tag,
                               conditional_conditions_list=CONDITIONAL_CONDITIONS,
                               conditional=conditional,
                               conditional_conditions=conditional_conditions,
                               conditions_dict=conditions_dict,
                               controllers=controllers,
                               controller_type=controller_type,
                               each_condition=each_condition,
                               each_function=each_function,
                               function=function,
                               function_channel=function_channel,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_controllers=custom_options_values_controllers,
                               custom_options_values_function_channels=custom_options_values_function_channels,
                               dict_actions=dict_actions,
                               dict_controllers=dict_controllers,
                               dict_measurements=dict_measurements,
                               dict_outputs=dict_outputs,
                               dict_units=dict_units,
                               display_order_function=display_order_function,
                               form_conditional=form_conditional,
                               form_conditional_conditions=form_conditional_conditions,
                               form_function=form_function,
                               form_actions=form_actions,
                               form_add_function=form_add_function,
                               form_function_base=form_function_base,
                               form_mod_pid_base=form_mod_pid_base,
                               form_mod_pid_pwm_raise=form_mod_pid_pwm_raise,
                               form_mod_pid_pwm_lower=form_mod_pid_pwm_lower,
                               form_mod_pid_output_raise=form_mod_pid_output_raise,
                               form_mod_pid_output_lower=form_mod_pid_output_lower,
                               form_mod_pid_value_raise=form_mod_pid_value_raise,
                               form_mod_pid_value_lower=form_mod_pid_value_lower,
                               form_mod_pid_volume_raise=form_mod_pid_volume_raise,
                               form_mod_pid_volume_lower=form_mod_pid_volume_lower,
                               form_trigger=form_trigger,
                               function_dev=function_dev,
                               function_types=FUNCTIONS,
                               input=input_dev,
                               method=method,
                               misc=misc,
                               names_function=names_function,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               sunrise_set_calc=sunrise_set_calc,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               tags=tags,
                               trigger=trigger,
                               units=MEASUREMENTS,
                               user=user)
    else:
        return "Could not determine template"


@blueprint.route('/function_status_activated/<unique_id>', methods=('GET', 'POST'))
@flask_login.login_required
def function_status_activated(unique_id):
    try:
        control = DaemonControl()
        data = control.function_status(unique_id)

        # Fallback for Sequence Trigger if daemon is off, unreachable, OR returns no steps
        if not data or 'error' in data or not data.get('steps'):
            from aot.controllers.controller_trigger_sequence import SequenceTriggerController
            fallback_data = SequenceTriggerController.get_static_status(unique_id)
            if fallback_data and 'error' not in fallback_data:
                # If we have data (e.g. from daemon but empty steps), merge to keep status info
                if data and 'error' not in data:
                     # Copy static steps to data
                     data['steps'] = fallback_data.get('steps', [])
                else:
                     data = fallback_data

        # Polyfill/Augment device details
        if data and 'steps' in data:
            try:
                for step in data['steps']:
                    # Always resolve names if missing or to ensure freshness
                    act_id = step.get('unique_id')
                    
                    # Optimization: If the step already has what we need, maybe skip? 
                    # But we need fresh names if user renamed them.
                    # We'll just fast-resolve.
                    
                    act = Actions.query.filter_by(unique_id=act_id).first()
                    if act:
                        opts = {}
                        if act.custom_options:
                            try:
                                opts = json.loads(act.custom_options)
                            except: pass
                        
                        target_id = act.do_unique_id
                        if not target_id: target_id = opts.get('output')
                        if not target_id: target_id = opts.get('input')
                        
                        d_name = ""
                        d_ch_name = ""
                        detail = step.get('device_detail', '-')

                        if target_id:
                            parts = str(target_id).split(',')
                            main_id = parts[0]
                            raw_chan = parts[1] if len(parts) > 1 else "0"
                            
                            out = Output.query.filter_by(unique_id=main_id).first()
                            if out:
                                d_name = out.name
                                chan_idx = raw_chan
                                # Resolve Channel UUID if needed
                                if len(str(raw_chan)) > 5:
                                    chan_obj = OutputChannel.query.filter_by(unique_id=raw_chan).first()
                                    if chan_obj: 
                                        chan_idx = chan_obj.channel
                                        d_ch_name = chan_obj.name
                                detail = f"{out.name} [CH{chan_idx}]"
                            else:
                                inp = Input.query.filter_by(unique_id=main_id).first()
                                if inp:
                                    d_name = inp.name
                                    detail = f"{inp.name} [Input]"
                                else:
                                    func = CustomController.query.filter_by(unique_id=main_id).first()
                                    if func:
                                        d_name = func.name
                                        detail = f"{func.name} [Func]"
                        
                        # Inject into step
                        step['device_name'] = d_name
                        step['device_channel_name'] = d_ch_name
                        
                        # Only overwrite detail if it was missing/placeholder
                        if not step.get('device_detail') or step.get('device_detail') in ['-', '']:
                             step['device_detail'] = detail
            except Exception as e:
                logger.error(f"Error polyfilling device details: {e}")

        return jsonify(data)
    except Exception as err:
        logger.error("Function Status Error: {}".format(err))
        return jsonify({'error': [str(err)]})


@blueprint.route('/function_status_always/<unique_id>', methods=('GET', 'POST'))
@flask_login.login_required
def function_status_always(unique_id):
    try:
        function = CustomController.query.filter(
            CustomController.unique_id == unique_id).first()
        if function:
            dict_controllers = parse_function_information()
            if function.device in dict_controllers and 'function_status' in dict_controllers[function.device]:
                return jsonify(dict_controllers[function.device]['function_status'](unique_id))
    except Exception as err:
        logger.error("Function Status Error: {}".format(err))
        return jsonify({'error': [str(err)]})
    return jsonify({'error': ["Could not get status from Function."]})


@blueprint.route('/function_sequence_update_settings', methods=['POST'])
@flask_login.login_required
def function_sequence_update_settings():
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403
    
    try:
        data = request.get_json()
        function_id = data.get('function_id')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        period = data.get('period')
        
        trigger = Trigger.query.filter_by(unique_id=function_id).first()
        if not trigger:
            return jsonify({'error': 'Function not found'}), 404
            
        if start_time: trigger.timer_start_time = start_time
        if end_time: trigger.timer_end_time = end_time
        if period is not None: trigger.period = float(period)
        
        db.session.commit()
        
        # Refresh Controller
        control = DaemonControl()
        control.refresh_daemon_trigger_settings(function_id)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Sequence Update Error: {e}")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/function_sequence_toggle_action', methods=['POST'])
@flask_login.login_required
def function_sequence_toggle_action():
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403
        
    try:
        data = request.get_json()
        action_unique_id = data.get('action_id')
        enabled = data.get('enabled') # boolean
        
        action = Actions.query.filter_by(unique_id=action_unique_id).first()
        if not action:
            return jsonify({'error': 'Action not found'}), 404
            
        try:
            opts = json.loads(action.custom_options) if action.custom_options else {}
        except:
            opts = {}
            
        opts['enabled'] = bool(enabled)
        action.custom_options = json.dumps(opts)
        
        db.session.commit()
        
        # Refresh Controller
        control = DaemonControl()
        control.refresh_daemon_trigger_settings(action.function_id)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Sequence Action Toggle Error: {e}")
        return jsonify({'error': str(e)}), 500

@blueprint.route('/sequence_activate_toggle/<function_id>/<state>', methods=['GET'])
@flask_login.login_required
def sequence_activate_toggle(function_id, state):
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'Permission denied'}), 403

    try:
        trigger = Trigger.query.filter_by(unique_id=function_id).first()
        if not trigger:
            return jsonify({'error': 'Trigger not found'}), 404
        
        if state == 'activate':
            trigger.is_activated = True
        else:
            trigger.is_activated = False
            
        db.session.commit()
        
        # Refresh Daemon
        control = DaemonControl()
        control.refresh_daemon_trigger_settings(function_id)
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Sequence Toggle Error: {e}")
        return jsonify({'error': str(e)}), 500
