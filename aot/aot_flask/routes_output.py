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
                                     GeoMap, GeoShape, GeoFacility)
from aot.services.tab_service import TabService
from sqlalchemy import or_
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_output
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general, utils_output
from aot.aot_flask.geo.device_membership import map_for_device
from aot.aot_flask.utils.utils_map_config import ensure_map_config
from aot.utils.device_blueprint import member_device_map, parent_device_names
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
    context = dict(inject_variables())
    # Output module types that render the 3-way (Open/Stop/Close + position)
    # card instead of an on/off toggle. Injected rather than hardcoded in the
    # template so a new paired-actuator module only registers in one place.
    from aot.outputs.paired_actuator_common import PAIRED_ACTUATOR_OUTPUT_TYPES
    context['three_way_output_types'] = PAIRED_ACTUATOR_OUTPUT_TYPES
    return context


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
            # Get current tab_id from request
            tab_id = request.args.get('tab_id', None)
            if not tab_id:
                # 화면(`page_output`)은 스코프로 걸러진 탭을 보여준다. 제출의 기본값도
                # 같은 기준이어야 한다 — 전역 position 0 을 쓰면 사용자가 보고 있던
                # 탭이 아닌 남의 탭이 대상이 되어, 조작할 수 없다며 거부된다.
                current_tab = (TabService.default_visible_tab('output') or
                               TabService.get_default_tab('output'))
                tab_id = current_tab.unique_id if current_tab else None
            
            (messages,
             dep_name,
             dep_list,
             dep_message,
             output_id,
             size_y) = utils_output.output_add(
                form_add_output, clean_request_form, tab_id)
            if dep_list:
                dep_unmet = form_add_output.output_type.data.split(',')[0]
        elif form_mod_output.output_mod.data:
            messages, page_refresh = utils_output.output_mod(
                form_mod_output, clean_request_form)
            output_id = form_mod_output.output_id.data
            if page_refresh and not messages["error"]:
                ch_count = OutputChannel.query.filter(
                    OutputChannel.output_id == output_id).count()
                size_y = ch_count + 1 if ch_count else 2
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
    # Sort by reported y, then re-rank to sequential ints to eliminate ties.
    # Without this, multiple cards can share the same position_y (especially
    # newly-created ones), making ORDER BY position_y nondeterministic and
    # the rendered card order unstable across reloads.
    items = [d for d in data if 'id' in d and 'y' in d]
    items.sort(key=lambda d: (d['y'], d['id']))
    for rank, each_output in enumerate(items):
        output_mod = Output.query.filter(
            Output.unique_id == each_output['id']).first()
        if output_mod:
            output_mod.position_y = rank
    db.session.commit()
    return "success"


@blueprint.route('/output', methods=('GET', 'POST'))
@flask_login.login_required
def page_output():
    """Display Output page options."""
    output_type = request.args.get('output_type', None)
    output_id = request.args.get('output_id', None)

    # ===== TAB SYSTEM INTEGRATION =====
    tab_id = request.args.get('tab_id', None)
    # 조작할 수 없는 탭은 목록에서 뺀다(그룹 스코프).
    # ⚠ 정보 격리가 아니다 — 그 장치들의 값은 대시보드·지도로 여전히 보인다.
    tabs = TabService.visible_tabs_for_page('output')

    if tab_id:
        current_tab = TabService.get_tab_by_id(tab_id)
        # URL 로 스코프 밖 탭을 직접 지정하면 보이는 탭으로 되돌린다 — 여기서
        # 그대로 열면 목록에 없는 탭이 열려 있는 모순된 화면이 된다.
        if not current_tab or current_tab not in tabs:
            current_tab = TabService.default_visible_tab('output')
    else:
        current_tab = TabService.default_visible_tab('output')

    if not current_tab:
        # Fallback: Tab 테이블이 비어있는 경우
        logger.warning("No default tab found for output page")
        output = Output.query.order_by(Output.position_y, Output.id).all()
    else:
        # Migrate legacy NULL tab_id entries to the default tab (runs only while nulls exist)
        null_count = Output.query.filter(Output.tab_id.is_(None)).count()
        if null_count:
            default_tab = TabService.get_default_tab('output')
            Output.query.filter(Output.tab_id.is_(None)).update({'tab_id': default_tab.unique_id})
            db.session.commit()

        output = Output.query.filter(
            Output.tab_id == current_tab.unique_id
        ).order_by(Output.position_y, Output.id).all()

    each_output = None
    if output_type in ['entry', 'options'] and output_id != '0':
        each_output = Output.query.filter(Output.unique_id == output_id).first()

    camera = Camera.query.all()
    function = CustomController.query.all()
    input_dev = Input.query.all()
    method = Method.query.all()
    misc = Misc.query.first()
    output_channel = OutputChannel
    pid = PID.query.all()
    user = User.query.all()

    dict_outputs = parse_output_information()

    # 소속 장치 배지(설계 6.3/8/9) — input.html 과 동일한 이유로 전체를 한 번에
    # 읽는다. primary + secondary 를 합쳐 카드마다 배지가 0개 이상 나올 수 있다.
    dict_device_names = parent_device_names()
    dict_member_devices = member_device_map('output')

    form_add_output = forms_output.OutputAdd()
    form_mod_output = forms_output.OutputMod()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    # Generate choices for dropdowns (Cross-tab enabled)
    all_inputs = Input.query.all()
    all_outputs = Output.query.all()
    all_functions = CustomController.query.all()

    choices_function = utils_general.choices_functions(
        all_functions, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        all_inputs, dict_units, dict_measurements)
    choices_input_devices = utils_general.choices_input_devices(all_inputs)
    choices_method = utils_general.choices_methods(method)
    choices_output = utils_general.choices_outputs(
        all_outputs, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_channels = utils_general.choices_outputs_channels(
        all_outputs, output_channel.query.all(), dict_outputs)
    choices_output_channels_measurements = utils_general.choices_outputs_channels_measurements(
        all_outputs, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)

    # Generate custom options for ALL outputs (not just filtered by tab)
    # This is needed because templates may reference outputs from other tabs
    all_outputs = Output.query.all()
    custom_options_values_outputs = parse_custom_option_values_json(
        all_outputs, dict_controller=dict_outputs)
    custom_options_values_output_channels = parse_custom_option_values_output_channels_json(
        output_channel.query.all(), dict_controller=dict_outputs, key_name='custom_channel_options')
    
    # Initialize empty dicts for all outputs to prevent template KeyError
    # NOTE: 루프 변수로 each_output 을 쓰면 안 된다. 위 215행에서 요청된
    # output_id 로 조회해 둔 each_output 를 덮어써, entry/options 응답이
    # 항상 all_outputs 의 마지막 카드 내용을 반환하는 버그를 유발한다.
    for _init_output in all_outputs:
        if _init_output.unique_id not in custom_options_values_output_channels:
            custom_options_values_output_channels[_init_output.unique_id] = {}

    # channel_unique_id -> channel_number map for fast lookup in templates
    # (used by actuator_paired card to resolve its underlying open/close channels)
    output_channels_by_uid = {
        c.unique_id: c.channel for c in output_channel.query.all()
    }

    custom_commands = {}
    for each_output_dev in output:
        if 'custom_commands' in dict_outputs[each_output_dev.output_type]:
            custom_commands[each_output_dev.output_type] = True

    # Create dict of Output names for ALL outputs (not just filtered by tab)
    # This is needed because templates may reference outputs from other tabs
    names_output = {}
    for each_element in all_outputs:
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

    # Generate output_variables for ALL outputs (not just filtered by tab)
    # This is needed because templates may reference outputs from other tabs
    output_variables = {}
    for each_output_dev in all_outputs:
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
        # [P3] 모든 지도가 동등하다 — is_device_owned 분기 폐기.
        map_configs = GeoMap.query.all()
    except Exception:
        map_configs = []

    map_overlays = {"type": "FeatureCollection", "features": []}

    if not output_type:
        return render_template('pages/output.html',
                               # ===== TAB PARAMETERS =====
                               tabs=tabs,
                               current_tab=current_tab,
                               # ==========================
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
                               output_channels_by_uid=output_channels_by_uid,
                               dict_device_names=dict_device_names,
                               dict_member_devices=dict_member_devices,
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
                               table_geomap=GeoMap,
                               table_geofacility=GeoFacility,
                               user=user,
                               map_overlays=map_overlays)
    elif output_type == 'entry':
        map_configs = []
        try:
            # [P3] 모든 지도가 동등하다 — is_device_owned 분기 폐기.
            map_configs = GeoMap.query.all()
        except Exception:
            map_configs = []
        map_config_id = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_output:
            # [P1] GET 은 지도를 만들지도 저장하지도 않는다. 읽기 요청이
            # DB 를 바꾸던 경로가 빈 지도 91% 의 원인이었다(원칙 4).
            # 배치된 지도가 있으면 그 지도를 읽고, 없으면 빈 상태로 둔다.
            # [P2] 배치된 지도는 마커에서 파생한다 — map_config_id 는
            # 사망 컬럼이다(device_membership 이 정본).
            map_config_id = map_for_device(each_output.unique_id,
                                            prefer=each_output.map_config_id) or ''
            if map_config_id:
                map_overlays = _load_map_overlays(map_config_id)
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
                               output_channels_by_uid=output_channels_by_uid,
                               dict_device_names=dict_device_names,
                               dict_member_devices=dict_member_devices,
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
                               table_geomap=GeoMap,
                               table_geofacility=GeoFacility,
                               user=user,
                               tabs=tabs,
                               current_tab=current_tab,
                               map_configs=map_configs,
                               map_config_id=map_config_id,
                               map_overlays=map_overlays)
    elif output_type == 'options':
        map_configs = []
        try:
            # [P3] 모든 지도가 동등하다 — is_device_owned 분기 폐기.
            map_configs = GeoMap.query.all()
        except Exception:
            map_configs = []
        map_config_id = ''
        map_overlays = {"type": "FeatureCollection", "features": []}
        if each_output:
            # [P1] GET 은 지도를 만들지도 저장하지도 않는다. 읽기 요청이
            # DB 를 바꾸던 경로가 빈 지도 91% 의 원인이었다(원칙 4).
            # 배치된 지도가 있으면 그 지도를 읽고, 없으면 빈 상태로 둔다.
            # [P2] 배치된 지도는 마커에서 파생한다 — map_config_id 는
            # 사망 컬럼이다(device_membership 이 정본).
            map_config_id = map_for_device(each_output.unique_id,
                                            prefer=each_output.map_config_id) or ''
            if map_config_id:
                map_overlays = _load_map_overlays(map_config_id)
            
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
                               output_channels_by_uid=output_channels_by_uid,
                               dict_device_names=dict_device_names,
                               dict_member_devices=dict_member_devices,
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
                               table_geomap=GeoMap,
                               table_geofacility=GeoFacility,
                               user=user,
                               map_config_id=map_config_id,
                               tabs=tabs,
                               current_tab=current_tab)


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

