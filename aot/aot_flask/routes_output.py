# coding=utf-8
"""collection of Page endpoints."""
import json
import logging
import os

import flask_login
from flask import (current_app, jsonify, redirect, render_template, request,
                   url_for)
from flask.blueprints import Blueprint

from aot.config import INSTALL_DIRECTORY

def _load_map_overlays(map_uuid):
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
from aot.databases.models import (PID, Camera, Conditional,
                                     CustomController, DisplayOrder, Input,
                                     Measurement, Method, Misc, Output,
                                     OutputChannel, Trigger, Unit, User,
                                     GeoMap, GeoShape)
from sqlalchemy import or_
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_output
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general, utils_output
from aot.aot_flask.utils.utils_map_config import ensure_map_config
from aot.utils.outputs import output_types, parse_output_information
from aot.utils import runtime
from aot.utils.system_pi import (
    add_custom_measurements, add_custom_units, csv_to_list_of_str,
    parse_custom_option_values_json,
    parse_custom_option_values_output_channels_json)

logger = logging.getLogger('aot.aot_flask.routes_output')

blueprint = Blueprint('routes_output',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/output_submit', methods=['POST'])
@flask_login.login_required
def page_output_submit():
    """Submit form for Output page"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False
    output_id = None
    dep_unmet = ''
    dep_name = ''
    dep_list = []
    dep_message = ''
    size_y = None

    clean_request_form = utils_general.sanitize_form(request.form)

    form_add_output = forms_output.OutputAdd(formdata=clean_request_form)
    form_mod_output = forms_output.OutputMod(formdata=clean_request_form)

    if not utils_general.user_has_permission('edit_controllers'):
        messages["error"].append("Your permissions do not allow this action")

    if not messages["error"]:
        if form_add_output.output_add.data:
            (messages,
             dep_name,
             dep_list,
             dep_message,
             output_id,
             size_y) = utils_output.output_add(
                form_add_output, clean_request_form)
            if dep_list:
                dep_unmet = form_add_output.output_type.data.split(',')[0]
        elif form_mod_output.output_mod.data:
            messages, page_refresh = utils_output.output_mod(
                form_mod_output, clean_request_form)
            output_id = form_mod_output.output_id.data
        elif form_mod_output.output_duplicate.data:
            messages, output_id = utils_output.output_duplicate(form_mod_output)
            page_refresh = True
        elif form_mod_output.output_delete.data:
            messages = utils_output.output_del(form_mod_output)
            output_id = form_mod_output.output_id.data

        # Custom action
        else:
            custom_button = False
            for key in clean_request_form.keys():
                if key.startswith('custom_button_'):
                    custom_button = True
                    break
            if custom_button:
                messages = utils_general.custom_command(
                    "Output",
                    parse_output_information(),
                    form_mod_output.output_id.data,
                    clean_request_form)
            else:
                messages["error"].append("Unknown output directive")

    dep_list = utils_general.sanitize_nullish_sequence(dep_list or [])
    dep_unmet = utils_general.normalize_nullish_value(dep_unmet, '')
    dep_message = utils_general.normalize_nullish_value(dep_message, '')
    return jsonify(data={
        'output_id': output_id,
        'dep_name': dep_name,
        'dep_list': dep_list,
        'dep_unmet': dep_unmet,
        'dep_message': dep_message,
        'size_y': size_y,
        'messages': messages,
        "page_refresh": page_refresh
    })


@blueprint.route('/save_output_layout', methods=['POST'])
def save_output_layout():
    """Save positions of outputs."""
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))
    data = request.get_json()
    keys = ('id', 'y')
    for each_output in data:
        if all(k in each_output for k in keys):
            output_mod = Output.query.filter(
                Output.unique_id == each_output['id']).first()
            if output_mod:
                output_mod.position_y = each_output['y']
    db.session.commit()
    return "success"


@blueprint.route('/output', methods=('GET', 'POST'))
@flask_login.login_required
def page_output():
    """Display Output page options."""
    output_type = request.args.get('output_type', None)
    output_id = request.args.get('output_id', None)
    each_output = None
    if output_type in ['entry', 'options'] and output_id != '0':
        each_output = Output.query.filter(Output.unique_id == output_id).first()

    camera = Camera.query.all()
    function = CustomController.query.all()
    input_dev = Input.query.all()
    method = Method.query.all()
    misc = Misc.query.first()
    output = Output.query.all()
    output_channel = OutputChannel
    pid = PID.query.all()
    user = User.query.all()

    dict_outputs = parse_output_information()

    form_add_output = forms_output.OutputAdd()
    form_mod_output = forms_output.OutputMod()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)
    choices_input_devices = utils_general.choices_input_devices(input_dev)
    choices_method = utils_general.choices_methods(method)
    choices_output = utils_general.choices_outputs(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_channels = utils_general.choices_outputs_channels(
        output, output_channel.query.all(), dict_outputs)
    choices_output_channels_measurements = utils_general.choices_outputs_channels_measurements(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)

    custom_options_values_outputs = parse_custom_option_values_json(
        output, dict_controller=dict_outputs)
    custom_options_values_output_channels = parse_custom_option_values_output_channels_json(
        output_channel.query.all(), dict_controller=dict_outputs, key_name='custom_channel_options')

    custom_commands = {}
    for each_output_dev in output:
        if 'custom_commands' in dict_outputs[each_output_dev.output_type]:
            custom_commands[each_output_dev.output_type] = True

    # Create dict of Input names
    names_output = {}
    all_elements = output
    for each_element in all_elements:
        names_output[each_element.unique_id] = '[{id}] {name}'.format(
            id=each_element.unique_id.split('-')[0], name=each_element.name)

    # Create list of file names from the output_options directory
    # Used in generating the correct options for each output/device
    output_templates = []
    output_path = os.path.join(
        INSTALL_DIRECTORY,
        'aot/aot_flask/templates/pages/output_options')
    for (_, _, file_names) in os.walk(output_path):
        output_templates.extend(file_names)
        break

    display_order_output = csv_to_list_of_str(DisplayOrder.query.first().output)

    output_variables = {}
    for each_output_dev in output:
        output_variables[each_output_dev.unique_id] = {}
        for each_channel in dict_outputs[each_output_dev.output_type]['channels_dict']:
            output_variables[each_output_dev.unique_id][each_channel] = {}
            output_variables[each_output_dev.unique_id][each_channel]['amps'] = None
            output_variables[each_output_dev.unique_id][each_channel]['trigger_startup'] = None

    # Find FTDI devices
    # Cached to improve performance
    from aot.aot_flask.utils.utils_cache_hardware import get_cached_ftdi_devices
    ftdi_devices = get_cached_ftdi_devices()

    # 지도 목록 (출력/옵션 공통)
    map_configs = []
    map_config_id = ''
    try:
        map_configs = GeoMap.query.filter(
            or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
        ).all()
    except Exception:
        map_configs = []

    map_overlays = {"type": "FeatureCollection", "features": []}

    if not output_type:
        return render_template('pages/output.html',
                               camera=camera,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               custom_commands=custom_commands,
                               custom_options_values_outputs=custom_options_values_outputs,
                               custom_options_values_output_channels=custom_options_values_output_channels,
                               dict_outputs=dict_outputs,
                               display_order_output=display_order_output,
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               form_add_output=form_add_output,
                               form_mod_output=form_mod_output,
                               ftdi_devices=ftdi_devices,
                               misc=misc,
                               names_output=names_output,
                               output=output,
                               output_channel=output_channel,
                               output_types=output_types(),
                               output_templates=output_templates,
                               output_variables=output_variables,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               map_overlays=map_overlays)
    elif output_type == 'entry':
        map_configs = []
        try:
            map_configs = GeoMap.query.filter(
                or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
            ).all()
        except Exception:
            map_configs = []
        map_config_id = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_output:
            map_cfg = ensure_map_config(
                each_output.map_config_id,
                each_output.name,
                each_output.latitude,
                each_output.longitude
            )
            if each_output.map_config_id != map_cfg.unique_id:
                each_output.map_config_id = map_cfg.unique_id
                each_output.save()
            map_config_id = map_cfg.unique_id
            map_overlays = _load_map_overlays(map_cfg.unique_id)
        return render_template('pages/output_entry.html',
                               camera=camera,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               custom_commands=custom_commands,
                               custom_options_values_outputs=custom_options_values_outputs,
                               custom_options_values_output_channels=custom_options_values_output_channels,
                               dict_outputs=dict_outputs,
                               display_order_output=display_order_output,
                               each_output=each_output,
                               form_add_output=form_add_output,
                               form_mod_output=form_mod_output,
                               ftdi_devices=ftdi_devices,
                               misc=misc,
                               names_output=names_output,
                               output=output,
                               output_channel=output_channel,
                               output_types=output_types(),
                               output_templates=output_templates,
                               output_variables=output_variables,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               map_overlays=map_overlays)
    elif output_type == 'options':
        map_configs = []
        try:
            map_configs = GeoMap.query.filter(
                or_(GeoMap.is_device_owned.is_(False), GeoMap.is_device_owned.is_(None))
            ).all()
        except Exception:
            map_configs = []
        map_config_id = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_output:
            map_cfg = ensure_map_config(
                each_output.map_config_id,
                each_output.name,
                each_output.latitude,
                each_output.longitude
            )
            if each_output.map_config_id != map_cfg.unique_id:
                each_output.map_config_id = map_cfg.unique_id
                each_output.save()
            map_config_id = map_cfg.unique_id
            map_overlays = _load_map_overlays(map_cfg.unique_id)
            
        return render_template('pages/output_options.html',
                               map_configs=map_configs,
                               camera=camera,
                               choices_function=choices_function,
                               choices_input=choices_input,
                               choices_input_devices=choices_input_devices,
                               choices_method=choices_method,
                               choices_output=choices_output,
                               choices_output_channels=choices_output_channels,
                               choices_output_channels_measurements=choices_output_channels_measurements,
                               choices_pid=choices_pid,
                               custom_commands=custom_commands,
                               custom_options_values_outputs=custom_options_values_outputs,
                               custom_options_values_output_channels=custom_options_values_output_channels,
                               dict_outputs=dict_outputs,
                               display_order_output=display_order_output,
                               each_output=each_output,
                               form_add_output=form_add_output,
                               form_mod_output=form_mod_output,
                               ftdi_devices=ftdi_devices,
                               misc=misc,
                               names_output=names_output,
                               output=output,
                               output_channel=output_channel,
                               output_types=output_types(),
                               output_templates=output_templates,
                               output_variables=output_variables,
                               table_camera=Camera,
                               table_conditional=Conditional,
                               table_function=CustomController,
                               table_input=Input,
                               table_output=Output,
                               table_pid=PID,
                               table_trigger=Trigger,
                               user=user,
                               map_config_id=map_config_id)


# --------------------------------------------------------------------------
# Public Runtime Endpoints (Moved from AoT_timer.py to Core)
# --------------------------------------------------------------------------
from pytz import timezone
import datetime
from aot.utils.runtime import resolve_channel_index, read_latest_started_at_safe

@blueprint.route('/output_started_at_public/<device_unique_id>/<channel_id>', methods=['GET'])
def start_time_public(device_unique_id, channel_id):
    """
    Public Endpoint: returns the most recent ON start timestamp.
    Used by AoT Map Widget and others for timer synchronization.
    """
    try:
        # Look-back window 30 days
        duration_sec = 30 * 24 * 3600

        ch_index = resolve_channel_index(device_unique_id, channel_id)
        if ch_index is None:
            return '', 204

        res = read_latest_started_at_safe(device_unique_id, ch_index, duration_sec, timeout_sec=2.0)
        if res is None:
            return '', 204

        if isinstance(res, int):
            started_ts = int(res)
            point_ts_epoch = None
            source = 'legacy'
        else:
            started_ts = int(res.get('selected_epoch'))
            point_ts_epoch = int(res.get('point_ts_epoch')) if res.get('point_ts_epoch') is not None else None
            source = str(res.get('source') or 'value')

        started_dt = datetime.datetime.utcfromtimestamp(int(started_ts)).replace(tzinfo=timezone('UTC'))
        payload = {
            "started_at_epoch": int(started_ts),
            "started_at_iso": started_dt.isoformat(),
            "point_ts_epoch": int(point_ts_epoch) if point_ts_epoch is not None else None,
            "source": source
        }
        return jsonify(payload)
    except Exception:
        return '', 204

@blueprint.route('/output_last_duration_public/<unique_id>/<channel>', methods=['GET'])
def output_last_duration_public(unique_id, channel):
    """Public endpoint to get the last duration of an output channel"""
    try:
        duration_sec = runtime.get_last_duration(unique_id, channel)
        return jsonify({
            "unique_id": unique_id,
            "channel": channel,
            "last_duration_sec": duration_sec
        })
    except Exception as e:
        logger.error("Error getting last duration for %s/%s: %s", unique_id, channel, e)
        return jsonify({"error": str(e)}), 500

