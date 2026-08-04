# coding=utf-8
"""collection of Page endpoints."""
import json
import logging
import os
import re
import subprocess

import flask_login
from flask import (current_app, jsonify, redirect, render_template, request,
                   url_for)
from flask.blueprints import Blueprint
from sqlalchemy import and_, or_

from aot.config import INSTALL_DIRECTORY, PATH_1WIRE
from aot.databases.models import (PID, Actions, Camera, Conditional,
                                     Conversion, CustomController,
                                     DeviceMeasurements, DisplayOrder, Input,
                                     InputChannel, Measurement, Method, Misc,
                                     Output, OutputChannel, Trigger, Unit,
                                     User, GeoMap, GeoShape)
from aot.services.tab_service import TabService
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_action, forms_input
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_action, utils_general, utils_input
from aot.aot_flask.utils.utils_map_config import ensure_map_config
from aot.aot_flask.utils.utils_general import generate_form_action_list
from aot.utils.actions import parse_action_information
from aot.utils.device_blueprint import member_device_map, parent_device_names
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import output_types, parse_output_information
from aot.utils.system_pi import (
    add_custom_measurements, add_custom_units, csv_to_list_of_str,
    dpkg_package_exists, parse_custom_option_values,
    parse_custom_option_values_input_channels_json, return_measurement_info)

logger = logging.getLogger('aot.aot_flask.routes_input')

blueprint = Blueprint('routes_input',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')

def _load_map_overlays(map_uuid):
    collection = {'type': 'FeatureCollection', 'features': []}
    if not map_uuid:
        return collection
    try:
        overlays = GeoShape.query.filter_by(geo_id=map_uuid).all()
        features = []
        for ov in overlays:
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
            features.append(feat)
            
        if features:
            collection['features'] = features
    except Exception:
        pass
    return collection


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/input_submit', methods=['POST'])
@flask_login.login_required
def page_input_submit():
    """Submit form for Data page"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False
    action_id = None
    input_id = None
    duplicated_input_id = ''
    dep_unmet = ''
    dep_name = ''
    dep_list = []
    dep_message = ''

    try:
        clean_request_form = utils_general.sanitize_form(request.form)
        logger.debug("Received formdata keys: %s", list(clean_request_form.keys()))

        form_actions = forms_action.Actions(formdata=clean_request_form)
        form_add_input = forms_input.InputAdd(formdata=clean_request_form)
        form_mod_input = forms_input.InputMod(formdata=clean_request_form)

        if not utils_general.user_has_permission('edit_controllers'):
            messages["error"].append("Your permissions do not allow this action")

        if not messages["error"]:
            if form_add_input.input_add.data:
                # Get current tab_id from request
                tab_id = request.args.get('tab_id', None)
                if not tab_id:
                    current_tab = TabService.get_default_tab('input')
                    tab_id = current_tab.unique_id if current_tab else None

                (messages,
                 dep_name,
                 dep_list,
                 dep_message,
                 input_id) = utils_input.input_add(form_add_input, tab_id)
                if dep_list:
                    dep_unmet = form_add_input.input_type.data.split(',')[0]
            elif form_mod_input.input_duplicate.data:
                messages, input_id = utils_input.input_duplicate(
                    form_mod_input)
                duplicated_input_id = form_mod_input.input_id.data
            else:
                input_id = form_mod_input.input_id.data
                if form_mod_input.input_mod.data:
                    messages, page_refresh = utils_input.input_mod(
                        form_mod_input, clean_request_form)
                elif form_mod_input.input_delete.data:
                    messages = utils_input.input_del(
                        form_mod_input.input_id.data)
                elif form_mod_input.input_activate.data:
                    messages = utils_input.input_activate(form_mod_input)
                elif form_mod_input.input_deactivate.data:
                    messages = utils_input.input_deactivate(form_mod_input)
                elif form_mod_input.input_acquire_measurements.data:
                    messages = utils_input.force_acquire_measurements(
                        form_mod_input.input_id.data)

                # Actions
                elif form_actions.add_action.data:
                    (messages,
                     dep_name,
                     dep_list,
                     action_id,
                     page_refresh) = utils_action.action_add(form_actions)
                    if dep_list:
                        dep_unmet = form_actions.action_type.data
                    input_id = form_actions.device_id.data
                elif form_actions.save_action.data:
                    messages = utils_action.action_mod(
                        form_actions, clean_request_form)
                    input_id = form_actions.device_id.data
                elif form_actions.delete_action.data:
                    messages = utils_action.action_del(form_actions)
                    page_refresh = True
                    input_id = form_actions.device_id.data
                    action_id = form_actions.action_id.data

                # Custom action
                else:
                    custom_button = False
                    for key in clean_request_form.keys():
                        if key.startswith('custom_button_'):
                            custom_button = True
                            break
                    if custom_button:
                        messages = utils_general.custom_command(
                            "Input",
                            parse_input_information(),
                            form_mod_input.input_id.data,
                            clean_request_form)
                    else:
                        messages["error"].append("Unknown function directive")
    except Exception as e:
        logger.exception("page_input_submit unexpected error")
        messages["error"].append(str(e))

    return jsonify(data={
        'action_id': action_id,
        'input_id': input_id,
        'duplicated_input_id': duplicated_input_id,
        'dep_name': dep_name,
        'dep_list': dep_list,
        'dep_unmet': dep_unmet,
        'dep_message': dep_message,
        'messages': messages,
        "page_refresh": page_refresh
    })


@blueprint.route('/save_input_layout', methods=['POST'])
def save_input_layout():
    """Save positions of inputs."""
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))
    data = request.get_json()
    # Sort by reported y, then re-rank to sequential ints to eliminate ties.
    # Without this, multiple cards can share the same position_y (especially
    # newly-created ones), making ORDER BY position_y nondeterministic and
    # the rendered card order unstable across reloads.
    items = [d for d in data if 'id' in d and 'y' in d]
    items.sort(key=lambda d: (d['y'], d['id']))
    for rank, each_input in enumerate(items):
        input_mod = Input.query.filter(
            Input.unique_id == each_input['id']).first()
        if input_mod:
            input_mod.position_y = rank
    db.session.commit()
    return "success"


@blueprint.route('/input', methods=('GET', 'POST'))
@flask_login.login_required
def page_input():
    """Display Data page options."""
    input_type = request.args.get('input_type', None)
    input_id = request.args.get('input_id', None)
    action_id = request.args.get('action_id', None)

    # ===== TAB SYSTEM INTEGRATION =====
    tab_id = request.args.get('tab_id', None)
    tabs = TabService.get_tabs_for_page('input')

    if tab_id:
        current_tab = TabService.get_tab_by_id(tab_id)
        if not current_tab:
            current_tab = TabService.get_default_tab('input')
    else:
        current_tab = TabService.get_default_tab('input')

    if not current_tab:
        # Fallback: Tab 테이블이 비어있는 경우
        logger.warning("No default tab found for input page")
        input_dev = Input.query.order_by(Input.position_y, Input.id).all()
    else:
        # Migrate legacy NULL tab_id entries to the default tab (runs only while nulls exist)
        null_count = Input.query.filter(Input.tab_id.is_(None)).count()
        if null_count:
            default_tab = TabService.get_default_tab('input')
            Input.query.filter(Input.tab_id.is_(None)).update({'tab_id': default_tab.unique_id})
            db.session.commit()

        input_dev = Input.query.filter(
            Input.tab_id == current_tab.unique_id
        ).order_by(Input.position_y, Input.id).all()

    each_input = None
    each_action = None

    if input_type in ['entry', 'options', 'actions']:
        each_input = Input.query.filter(Input.unique_id == input_id).first()

        # Fragment templates dereference each_input (e.g. render_device_map uses
        # custom_options_values_inputs[each_input.unique_id]); a missing/invalid
        # input_id must return a clean 404 rather than a Jinja 500.
        if not each_input:
            return "Input not found", 404

        if input_type == 'actions' and action_id:
            each_action = Actions.query.filter(
                Actions.unique_id == action_id).first()

    action = Actions.query.all()
    function = CustomController.query.all()
    input_channel = InputChannel.query.all()
    method = Method.query.all()
    measurement = Measurement.query.all()
    misc = Misc.query.first()
    output = Output.query.all()
    output_channel = OutputChannel.query.all()
    pid = PID.query.all()
    user = User.query.all()
    unit = Unit.query.all()

    display_order_input = csv_to_list_of_str(DisplayOrder.query.first().inputs)

    form_add_input = forms_input.InputAdd()
    form_mod_input = forms_input.InputMod()
    form_actions = forms_action.Actions()

    dict_inputs = parse_input_information()
    dict_actions = parse_action_information()

    # 소속 장치 배지(설계 6.3/8/9) — primary(parent_device_id) + secondary
    # (DeviceMember) 를 합쳐 카드마다 배지가 0개 이상 나올 수 있다. 장치
    # 개수가 적어 전체를 한 번에 읽어 두는 편이 N+1보다 싸다.
    dict_device_names = parent_device_names()
    dict_member_devices = member_device_map('input')

    # Generate custom options for ALL inputs (not just filtered by tab)
    # This is needed because templates may reference inputs from other tabs
    all_inputs = Input.query.all()
    custom_options_values_inputs = parse_custom_option_values(
        all_inputs, dict_controller=dict_inputs)
    custom_options_values_input_channels = parse_custom_option_values_input_channels_json(
        input_channel, dict_controller=dict_inputs, key_name='custom_channel_options')
    
    # Initialize empty dicts for all inputs to prevent template KeyError
    # NOTE: use a distinct loop variable — reusing `each_input` here would
    # clobber the device selected at line ~252 (for entry/options/actions
    # fragment requests), causing the wrong device's settings to render.
    for each_input_init in all_inputs:
        if each_input_init.unique_id not in custom_options_values_input_channels:
            custom_options_values_input_channels[each_input_init.unique_id] = {}

    custom_options_values_actions = {}
    for each_action_dev in action:
        try:
            custom_options_values_actions[each_action_dev.unique_id] = json.loads(each_action_dev.custom_options)
        except:
            custom_options_values_actions[each_action_dev.unique_id] = {}

    custom_commands = {}
    for each_input_dev in input_dev:
        if each_input_dev.device in dict_inputs and 'custom_commands' in dict_inputs[each_input_dev.device]:
            custom_commands[each_input_dev.device] = True

    # Generate dict that incorporate user-added measurements/units
    dict_outputs = parse_output_information()
    dict_units = add_custom_units(unit)
    dict_measurements = add_custom_measurements(measurement)

    # Map each device measurement -> its effective unit key (accounting for
    # conversion/rescale). Lets the entry card render the live measurement's
    # unit symbol, mirroring the live-measurements page.
    dict_measure_units = {}
    for each_measurement in DeviceMeasurements.query.all():
        conversion = Conversion.query.filter(
            Conversion.unique_id == each_measurement.conversion_id).first()
        _, m_unit, _ = return_measurement_info(each_measurement, conversion)
        dict_measure_units[each_measurement.unique_id] = m_unit

    # Generate Action dropdown for use with Inputs
    choices_actions = []
    list_actions_sorted = generate_form_action_list(dict_actions, application=["inputs"])
    for name in list_actions_sorted:
        choices_actions.append((name, dict_actions[name]['name']))

    # Generate choices for dropdowns (Cross-tab enabled)
    all_inputs = Input.query.all()
    all_outputs = Output.query.all()
    all_functions = CustomController.query.all()

    choices_function = utils_general.choices_functions(
        all_functions, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        all_inputs, dict_units, dict_measurements)
    choices_method = utils_general.choices_methods(method)
    choices_output = utils_general.choices_outputs(
        all_outputs, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_channels = utils_general.choices_outputs_channels(
        output, output_channel, dict_outputs)
    choices_output_channels_measurements = utils_general.choices_outputs_channels_measurements(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)
    choices_pid_devices = utils_general.choices_pids_devices(pid)
    choices_unit = utils_general.choices_units(unit)
    choices_measurement = utils_general.choices_measurements(measurement)
    choices_measurements_units = utils_general.choices_measurements_units(measurement, unit)

    # Create dict of Input names for ALL inputs (not just filtered by tab)
    # This is needed because templates may reference inputs from other tabs
    names_input = {}
    for each_element in all_inputs:
        names_input[each_element.unique_id] = '[{id:02d}] ({uid}) {name}'.format(
            id=each_element.id,
            uid=each_element.unique_id.split('-')[0],
            name=each_element.name)

    # Create list of file names from the input_options directory
    # Used in generating the correct options for each input controller
    input_templates = []
    input_path = os.path.join(
        INSTALL_DIRECTORY,
        'aot/aot_flask/templates/pages/data_options/input_options')
    for (_, _, file_names) in os.walk(input_path):
        input_templates.extend(file_names)
        break

    # Compile a list of 1-wire devices
    devices_1wire = []
    if os.path.isdir(PATH_1WIRE):
        for each_name in os.listdir(PATH_1WIRE):
            if 'bus' not in each_name and '-' in each_name:
                devices_1wire.append(
                    {'name': each_name, 'value': each_name.split('-')[1]}
                )

    # Compile a list of 1-wire devices (using ow-shell)
    # Cached to improve performance
    from aot.aot_flask.utils.utils_cache_hardware import get_cached_1wire_devices
    devices_1wire_ow_shell = []
    if Input.query.filter(Input.device == "DS18B20_OWS").count():
        devices_1wire_ow_shell = get_cached_1wire_devices()

    # Find FTDI devices
    # Cached to improve performance
    from aot.aot_flask.utils.utils_cache_hardware import get_cached_ftdi_devices
    ftdi_devices = get_cached_ftdi_devices()

    # 지도 목록 (입력/옵션 공통)
    map_configs = []
    map_config_id = ''
    try:
        map_configs = GeoMap.query.filter(
            or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
        ).all()
    except Exception:
        map_configs = []

    map_overlays = {"type": "FeatureCollection", "features": []}

    if not input_type:
        return render_template('pages/input.html',
                               # ===== TAB PARAMETERS =====
                               tabs=tabs,
                               current_tab=current_tab,
                               # ==========================
                               and_=and_,
                               action=action,
                               choices_actions=choices_actions,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_output=choices_output,
                               choices_measurement=choices_measurement,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_pid_devices=choices_pid_devices,
                               choices_unit=choices_unit,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_inputs=custom_options_values_inputs,
                               custom_options_values_input_channels=custom_options_values_input_channels,
                               dict_actions=dict_actions,
                               dict_device_names=dict_device_names,
                               dict_member_devices=dict_member_devices,
                               dict_inputs=dict_inputs,
                               dict_measurements=dict_measurements,
                               dict_measure_units=dict_measure_units,
                               dict_units=dict_units,
                               display_order_input=display_order_input,
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               form_actions=form_actions,
                               form_add_input=form_add_input,
                               form_mod_input=form_mod_input,
                               ftdi_devices=ftdi_devices,
                               input_channel=input_channel,
                               input_templates=input_templates,
                               misc=misc,
                               names_input=names_input,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               devices_1wire_ow_shell=devices_1wire_ow_shell,
                               devices_1wire=devices_1wire,
                               input_dev=input_dev,
                               map_overlays=map_overlays)
    elif input_type == 'entry':
        if not each_input:
            return "Input not found", 404

        map_configs = []
        map_config_id = ''
        try:
            map_configs = GeoMap.query.filter(
                or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
            ).all()
        except Exception:
            map_configs = []
        return render_template('pages/data_options/input_entry.html',
                               # ===== TAB PARAMETERS =====
                               tabs=tabs,
                               current_tab=current_tab,
                               # ==========================
                               and_=and_,
                               action=action,
                               choices_actions=choices_actions,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_output=choices_output,
                               choices_measurement=choices_measurement,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_pid_devices=choices_pid_devices,
                               choices_unit=choices_unit,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_inputs=custom_options_values_inputs,
                               custom_options_values_input_channels=custom_options_values_input_channels,
                               dict_actions=dict_actions,
                               dict_device_names=dict_device_names,
                               dict_member_devices=dict_member_devices,
                               dict_inputs=dict_inputs,
                               dict_measurements=dict_measurements,
                               dict_measure_units=dict_measure_units,
                               dict_units=dict_units,
                               display_order_input=display_order_input,
                               each_input=each_input,
                               form_actions=form_actions,
                               form_add_input=form_add_input,
                               form_mod_input=form_mod_input,
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               ftdi_devices=ftdi_devices,
                               input_channel=input_channel,
                               input_templates=input_templates,
                               misc=misc,
                               names_input=names_input,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               devices_1wire_ow_shell=devices_1wire_ow_shell,
                               devices_1wire=devices_1wire,
                               map_overlays=map_overlays)
    elif input_type == 'options':
        map_configs = []
        try:
            map_configs = GeoMap.query.filter(
                or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
            ).all()
        except Exception:
            map_configs = []
        map_config_id = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_input:
            # [P1] GET 은 지도를 만들지도 저장하지도 않는다. 읽기 요청이
            # DB 를 바꾸던 경로가 빈 지도 91% 의 원인이었다(원칙 4).
            # 배치된 지도가 있으면 그 지도를 읽고, 없으면 빈 상태로 둔다.
            map_config_id = each_input.map_config_id or ''
            if map_config_id:
                map_overlays = _load_map_overlays(map_config_id)

        return render_template('pages/data_options/input_options.html',
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               and_=and_,
                               action=action,
                               choices_actions=choices_actions,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_output=choices_output,
                               choices_measurement=choices_measurement,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_pid_devices=choices_pid_devices,
                               choices_unit=choices_unit,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_inputs=custom_options_values_inputs,
                               custom_options_values_input_channels=custom_options_values_input_channels,
                               dict_actions=dict_actions,
                               dict_inputs=dict_inputs,
                               dict_measurements=dict_measurements,
                               dict_measure_units=dict_measure_units,
                               dict_units=dict_units,
                               display_order_input=display_order_input,
                               each_input=each_input,
                               form_actions=form_actions,
                               form_add_input=form_add_input,
                               form_mod_input=form_mod_input,
                               ftdi_devices=ftdi_devices,
                               input_channel=input_channel,
                               input_templates=input_templates,
                               misc=misc,
                               names_input=names_input,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               devices_1wire_ow_shell=devices_1wire_ow_shell,
                               devices_1wire=devices_1wire,
                               map_overlays=map_overlays,
                               tabs=tabs,
                               current_tab=current_tab)
    elif input_type == 'actions':
        return render_template('pages/actions.html',
                               and_=and_,
                               action=action,
                               choices_actions=choices_actions,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_output=choices_output,
                               choices_measurement=choices_measurement,
                               choices_measurements_units=choices_measurements_units,
                               choices_method=choices_method,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               choices_pid_devices=choices_pid_devices,
                               choices_unit=choices_unit,
                               custom_commands=custom_commands,
                               custom_options_values_actions=custom_options_values_actions,
                               custom_options_values_inputs=custom_options_values_inputs,
                               custom_options_values_input_channels=custom_options_values_input_channels,
                               dict_actions=dict_actions,
                               dict_inputs=dict_inputs,
                               dict_measurements=dict_measurements,
                               dict_measure_units=dict_measure_units,
                               dict_units=dict_units,
                               display_order_input=display_order_input,
                               each_action=each_action,
                               each_input=each_input,
                               form_actions=form_actions,
                               form_add_input=form_add_input,
                               form_mod_input=form_mod_input,
                               ftdi_devices=ftdi_devices,
                               input_channel=input_channel,
                               input_templates=input_templates,
                               misc=misc,
                               names_input=names_input,
                               output=output,
                               output_types=output_types(),
                               pid=pid,
                               table_conversion=Conversion,
                               table_device_measurements=DeviceMeasurements,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               devices_1wire_ow_shell=devices_1wire_ow_shell,
                               devices_1wire=devices_1wire)
