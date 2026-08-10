# coding=utf-8
"""collection of Page endpoints."""
import calendar
import datetime
import glob
import logging
import os
import resource
import socket
import subprocess
import sys
import time
from collections import OrderedDict
import flask_login
from flask import (Response, current_app, flash, jsonify, redirect,
                   render_template, request, send_file, stream_with_context,
                   url_for)
from flask.blueprints import Blueprint
from flask_babel import gettext
_ = gettext
from sqlalchemy import and_

from aot.config import (ALEMBIC_VERSION, BACKUP_LOG_FILE,
                           DAEMON_LOG_FILE,
                           DEPENDENCY_LOG_FILE, DOCKER_CONTAINER,
                           FRONTEND_PID_FILE, HTTP_ACCESS_LOG_FILE,
                           HTTP_ERROR_LOG_FILE, IMPORT_LOG_FILE,
                           INSTALL_DIRECTORY,
                           KEEPUP_LOG_FILE, LOGIN_LOG_FILE, AOT_DB_PATH,
                           AOT_VERSION, RESTORE_LOG_FILE, SQL_DATABASE_AOT,
                           THEMES_DARK, UPGRADE_LOG_FILE)
from aot.config_devices_units import MEASUREMENTS
from aot.databases.models import (PID, AlembicVersion, Camera, Conversion,
                                     CustomController, DeviceMeasurements,
                                     DisplayOrder, EnergyUsage, Input,
                                     Measurement, Misc, Notes, NoteTags,
                                     Output, OutputChannel, Unit, Widget)
from aot.aot_client import DaemonControl, daemon_active
from aot.aot_flask.forms import forms_camera, forms_misc, forms_notes
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import (utils_camera, utils_dashboard,
                                       utils_export, utils_general, utils_misc,
                                       utils_notes)
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.utils.functions import parse_function_information
from aot.utils.inputs import (list_analog_to_digital_converters,
                                 parse_input_information)
from aot.utils.outputs import output_types, parse_output_information
from aot.utils.service_control import reload_frontend, restart_daemon
from aot.utils.system_environment import (THREADS_MAX, THREADS_MIN,
                                          detect as detect_system_environment,
                                          recommended_threads,
                                          resolve_gunicorn_threads)
from aot.utils.system_pi import (
    add_custom_measurements, add_custom_units, csv_to_list_of_str,
    parse_custom_option_values,
    parse_custom_option_values_output_channels_json, return_measurement_info)
from aot.utils.tools import (calc_energy_usage, return_energy_usage,
                                return_output_usage)

logger = logging.getLogger('aot.aot_flask.routes_page')

blueprint = Blueprint('routes_page',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.context_processor
@flask_login.login_required
def inject_functions():
    def epoch_to_time_string(epoch):
        from aot.utils.time_utils import get_timezone_name
        import pytz
        try:
            tz = pytz.timezone(get_timezone_name())
            return datetime.datetime.fromtimestamp(epoch, tz).strftime(
                "%Y-%m-%d %H:%M:%S")
        except:
            return "EPOCH ERROR"

    return dict(epoch_to_time_string=epoch_to_time_string,
                get_note_tag_from_unique_id=utils_notes.get_note_tag_from_unique_id,
                utc_to_local_time=utils_general.utc_to_local_time)


@blueprint.route('/camera_submit', methods=['POST'])
@flask_login.login_required
def page_camera_submit():
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False
    dep_unmet = None

    form_camera = forms_camera.Camera()

    if not utils_general.user_has_permission('edit_controllers'):
        messages["error"].append("Your permissions do not allow this action")

    if not messages["error"]:
        if form_camera.camera_mod.data:
            messages = utils_camera.camera_mod(form_camera)
        elif form_camera.camera_del.data:
            messages = utils_camera.camera_del(form_camera)
        elif form_camera.timelapse_generate.data:
            messages = utils_camera.camera_timelapse_video(form_camera)
        else:
            messages["error"].append("Unknown camera directive")

    if page_refresh:
        for each_error in messages["error"]:
            flash(each_error, "error")
        for each_warn in messages["warning"]:
            flash(each_warn, "warning")
        for each_info in messages["info"]:
            flash(each_info, "info")
        for each_success in messages["success"]:
            flash(each_success, "success")

    return jsonify(data={
        'camera_id': form_camera.camera_id.data,
        'dep_unmet': dep_unmet,
        'messages': messages,
        'page_refresh': page_refresh
    })


@blueprint.route('/notes', methods=('GET', 'POST'))
@flask_login.login_required
def page_notes():
    """
    Notes page
    """
    form_note_add = forms_notes.NoteAdd()
    form_note_options = forms_notes.NoteOptions()
    form_note_mod = forms_notes.NoteMod()
    form_tag_add = forms_notes.TagAdd()
    form_tag_options = forms_notes.TagOptions()
    form_note_show = forms_notes.NotesShow()

    total_notes = Notes.query.count()

    notes = Notes.query.order_by(Notes.id.desc()).all()
    tags = NoteTags.query.all()

    from aot.utils.time_utils import get_local_now
    current_date_time = get_local_now().strftime("%Y-%m-%d %H:%M:%S")

    # [MODIFIED] Handle Filter & Sort Logic for GET Persistence
    if request.method == 'GET':
        filter_notes = request.args.get('filter_notes')
        filter_tags = request.args.get('filter_tags')
        sort_by = request.args.get('sort_by')
        sort_direction = request.args.get('sort_direction')
        
        # Populate form if params exist to maintain state across page refreshes/scrolls
        if any([filter_notes, filter_tags, sort_by, sort_direction]):
            if filter_notes:
                form_note_show.filter_notes.data = filter_notes
            if filter_tags:
                form_note_show.filter_tags.data = filter_tags
            if sort_by:
                form_note_show.sort_by.data = sort_by
            if sort_direction:
                form_note_show.sort_direction.data = sort_direction
            
            # Apply filter & sort
            notes = utils_notes.show_notes(form_note_show)

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_page.page_notes'))

        if form_note_show.notes_show.data:
            notes = utils_notes.show_notes(form_note_show)
        elif form_note_show.notes_export.data:
            notes, data = utils_notes.export_notes(form_note_show)
            if data:
                # Send zip file to user
                return send_file(
                    data,
                    mimetype='application/zip',
                    as_attachment=True,
                    download_name=
                    'AoT_Notes_{mv}_{host}_{dt}.zip'.format(
                        mv=AOT_VERSION,
                        host=socket.gethostname().replace(' ', ''),
                        dt=get_local_now().strftime("%Y-%m-%d_%H-%M-%S"))
                )
        elif form_note_show.notes_export_pdf.data:
            from aot.aot_flask.utils import utils_notes_report
            buffer, filename = utils_notes_report.export_notes_pdf(form_note_show)
            if buffer:
                return send_file(
                    buffer,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=filename)
        elif form_note_show.notes_import_upload.data:
            utils_notes.import_notes(form_note_show)
        else:
            if form_tag_add.tag_add.data:
                utils_notes.tag_add(form_tag_add)
            elif form_tag_options.tag_rename.data:
                utils_notes.tag_rename(form_tag_options)
            elif form_tag_options.tag_del.data:
                utils_notes.tag_del(form_tag_options)

            elif form_note_add.note_add.data:
                utils_notes.note_add(form_note_add)
            elif form_note_mod.note_save.data:
                utils_notes.note_mod(form_note_mod)
            elif form_note_options.note_del.data:
                utils_notes.note_del(form_note_options)
            elif form_note_options.note_mod.data:
                return redirect(url_for('routes_page.page_note_edit', unique_id=form_note_options.note_unique_id.data))

            return redirect(url_for('routes_page.page_notes'))

    # [PHASE 1] Determine the correct page number
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    page = request.args.get('page', 1, type=int)

    # Force page 1 if searching (unless it is an AJAX scroll request)
    if not is_ajax and (request.args.get('filter_notes') or request.args.get('filter_tags') or request.method == 'POST'):
        page = 1

    if notes:
        # If notes is a query object (most cases)
        if hasattr(notes, 'paginate'):
             # Pagination settings
            per_page = 30
            pagination = notes.paginate(page=page, per_page=per_page, error_out=False)
            notes_items = pagination.items
            has_next = pagination.has_next
            next_num = pagination.next_num
            note_count = pagination.total
        # If notes is a list
        elif isinstance(notes, list):
            per_page = 30
            start = (page - 1) * per_page
            end = start + per_page
            notes_items = notes[start:end]
            has_next = end < len(notes)
            next_num = page + 1 if has_next else None
            note_count = len(notes)
        else:
             notes_items = []
             has_next = False
             next_num = None
             note_count = 0
    else:
        notes_items = []
        has_next = False
        next_num = None
        note_count = 0

    number_displayed_notes = (note_count, total_notes)

    # Handle AJAX request for Infinite Scroll
    if is_ajax:
        html_list = []
        for each_note in notes_items:
            html_list.append(render_template('tools/partials/note_item.html', 
                                             each_note=each_note, 
                                             form_note_options=form_note_options))
        
        return jsonify({
            'html': ''.join(html_list),
            'has_next': has_next,
            'next_page': next_num
        })

    return render_template('tools/notes.html',
                           notes=notes_items,
                           tags=tags,
                           form_note_add=form_note_add,
                           form_note_options=form_note_options,
                           form_note_mod=form_note_mod,
                           form_tag_add=form_tag_add,
                           form_tag_options=form_tag_options,
                           form_note_show=form_note_show,
                           number_displayed_notes=number_displayed_notes,
                           current_date_time=current_date_time,
                           has_next=has_next,
                           next_num=next_num,
                           page=page if 'page' in locals() else 1)


@blueprint.route('/note_edit/<unique_id>', methods=('GET', 'POST'))
@flask_login.login_required
def page_note_edit(unique_id):
    """
    Edit note page
    """
    # Used in software tests to verify function is executing as admin
    if unique_id == '0':
        return 'admin logged in'

    this_note = Notes.query.filter(Notes.unique_id == unique_id).first()

    form_note_mod = forms_notes.NoteMod()

    tags = NoteTags.query.all()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_page.page_notes'))

        if form_note_mod.note_save.data:
            utils_notes.note_mod(form_note_mod)
        if form_note_mod.file_rename.data:
            utils_notes.file_rename(form_note_mod)
        if form_note_mod.file_del.data:
            utils_notes.file_del(form_note_mod)
        if form_note_mod.note_del.data:
            utils_notes.note_del(form_note_mod)
            return redirect(url_for('routes_page.page_notes'))
        if form_note_mod.note_cancel.data:
            return redirect(url_for('routes_page.page_notes'))

        return redirect(url_for('routes_page.page_note_edit', unique_id=this_note.unique_id))

    form_note_mod.note.data = this_note.note

    return render_template('tools/note_edit.html',
                           form_note_mod=form_note_mod,
                           this_note=this_note,
                           tags=tags)


@blueprint.route('/export', methods=('GET', 'POST'))
@flask_login.login_required
def page_export():
    """
    Export/Import measurement and settings data
    """
    form_export_measurements = forms_misc.ExportMeasurements()
    form_export_settings = forms_misc.ExportSettings()
    form_import_settings = forms_misc.ImportSettings()
    form_export_influxdb = forms_misc.ExportInfluxdb()

    function = CustomController.query.all()
    input_dev = Input.query.all()
    output = Output.query.all()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    dict_outputs = parse_output_information()

    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)
    choices_output = utils_general.choices_outputs(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_controllers'):
            return redirect(url_for('routes_general.home'))

        if form_export_measurements.export_data_csv.data:
            url = utils_export.export_measurements(form_export_measurements)
            if url:
                return redirect(url)
        elif form_export_settings.export_settings_zip.data:
            file_send = utils_export.export_settings()
            if file_send:
                return file_send
            else:
                flash('Unknown error creating zipped settings database',
                      'error')
        elif form_import_settings.settings_import_upload.data:
            restore_success = utils_export.import_settings(form_import_settings)
            if restore_success:
                return redirect(url_for('routes_authentication.logout'))
            else:
                flash('An error occurred during the settings import.',
                      'error')
        elif form_export_influxdb.export_influxdb_zip.data:
            file_send = utils_export.export_influxdb()
            if file_send:
                return file_send
            else:
                flash('Unknown error creating zipped influxdb database '
                      'and metastore', 'error')

    # Generate start end end times for date/time picker
    from aot.utils.time_utils import get_local_now
    now = get_local_now()
    end_picker = now.strftime('%m/%d/%Y %H:%M')
    start_picker = now - datetime.timedelta(hours=6)
    start_picker = start_picker.strftime('%m/%d/%Y %H:%M')

    return render_template('tools/export.html',
                           start_picker=start_picker,
                           end_picker=end_picker,
                           form_export_influxdb=form_export_influxdb,
                           form_export_measurements=form_export_measurements,
                           form_export_settings=form_export_settings,
                           form_import_settings=form_import_settings,
                           choices_function=choices_function,
                           choices_input=choices_input,
                           choices_output=choices_output)


def _expand_device_choices(selected):
    """`<uuid>,ALL,device` 선택을 그 장치가 담은 측정값들로 편다.

    복합장치는 값을 재지 않는 그릇이므로 선택 목록에는 하나로 뜨고, 그래프에는
    안에 든 것들이 뜬다. 폈다가 원본을 버리면 안 된다 — 체크박스 상태는 사람이
    실제로 고른 것(`selected_raw`)으로 그려야 하고, 편 결과로 그리면 장치를
    골랐던 사실이 화면에서 사라진다.
    """
    out = []
    for item in selected:
        parts = item.split(',')
        if len(parts) == 3 and parts[1] == 'ALL' and parts[2] == 'device':
            for child_id, meas_id, kind in \
                    utils_general.composite_device_measurements(parts[0]):
                out.append('%s,%s,%s' % (child_id, meas_id, kind))
        else:
            out.append(item)
    return out


def _filter_choices_by_area(choices, allowed_ids):
    """선택지 목록을 구역 안의 장치로 좁힌다. `allowed_ids` 가 None 이면 그대로.

    선택지의 value 는 `<장치 uuid>,<측정 uuid>` 또는 복합장치의 `<uuid>` 다.
    """
    if allowed_ids is None:
        return choices
    return [c for c in choices
            if str(c.get('value', '')).split(',')[0] in allowed_ids]


@blueprint.route('/graph-async', methods=('GET', 'POST'))
@flask_login.login_required
def page_graph_async():
    """Generate graphs using asynchronous data retrieval."""
    if not current_app.config['TESTING']:
        dep_unmet, _unused, _unmet = return_dependencies('highstock')
        if dep_unmet:
            return redirect(url_for('routes_admin.admin_dependencies',
                                    device='highstock'))

    function = CustomController.query.all()
    input_dev = Input.query.all()
    device_measurements = DeviceMeasurements.query.all()
    output = Output.query.all()
    pid = PID.query.all()
    tag = NoteTags.query.all()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    # Get what each measurement uses for a unit
    use_unit = utils_general.use_unit_generate(
        device_measurements, input_dev, output, function)

    dict_outputs = parse_output_information()

    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)
    choices_output = utils_general.choices_outputs(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    # 복합장치는 값을 재지 않는다 — Input/Output 을 담는 그릇이라, 고르면 그
    # 안의 측정값 전부를 뜻한다(선택값 `<uuid>,ALL,device` 를 아래에서 편다).
    choices_device = utils_general.choices_composite_devices()
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)
    choices_tag = utils_general.choices_tags(tag)

    selected_ids_measures = []
    selected_raw = []
    start_time_epoch = 0
    # 구역 필터. 빈 값은 "거르지 않는다" 이고, 고른 구역의 도형이 사라진
    # 경우도 같게 다룬다 — 그때 목록을 비우면 화면이 통째로 사라진다.
    area_filter = ''
    choices_area = []
    try:
        from aot.aot_flask.geo import device_membership
        choices_area = device_membership.area_choices()
    except Exception:
        logger.exception("[graph-async] 구역 목록을 읽지 못했다")

    device_measurements_dict = {}
    for meas in device_measurements:
        device_measurements_dict[meas.unique_id] = meas

    dict_measure_measurements = {}
    dict_measure_units = {}

    for each_measurement in device_measurements:
        conversion = Conversion.query.filter(
            Conversion.unique_id == each_measurement.conversion_id).first()
        _, unit, measurement = return_measurement_info(each_measurement, conversion)
        dict_measure_measurements[each_measurement.unique_id] = measurement
        dict_measure_units[each_measurement.unique_id] = unit

    async_height = 600
    period = 'all'
    # 장치 교체를 관통해 이어 붙일지. 기본은 꺼짐 — 접합은 이력이 있는 자리에서만
    # 의미가 있고, 없는 자리에서는 조용히 단일 장치 조회로 떨어진다.
    stitch_history = False

    if request.method == 'POST':
        stitch_history = bool(request.form.get('stitch_history'))
        if request.form.get('async_height'):
            async_height = request.form['async_height']
        # Period values are locale-independent identifiers (not button labels)
        period = request.form.get('period', 'all')
        seconds = {
            'year': 31556952,
            'month': 2629746,
            'week': 604800,
            'day': 86400
        }.get(period, 0)

        if seconds:
            from aot.utils.time_utils import get_local_now
            now = get_local_now()
            start_time_epoch = (now -
                                datetime.timedelta(seconds=seconds)).timestamp()
        selected_raw = request.form.getlist('selected_measure')
        selected_ids_measures = _expand_device_choices(selected_raw)
        area_filter = (request.form.get('area_filter') or '').strip()

    # Generate a dictionary of lists of y-axes
    # 구역 필터를 선택지에 적용한다. 이미 고른 항목은 거르지 않는다 — 고른
    # 뒤에 구역을 바꿨다고 그래프에서 사라지면 사람은 무엇이 빠졌는지 모른다.
    allowed_ids = None
    if area_filter:
        try:
            from aot.aot_flask.geo import device_membership
            allowed_ids = device_membership.device_ids_in_area(area_filter)
        except Exception:
            logger.exception("[graph-async] 구역 필터 해석 실패")
    if allowed_ids is not None:
        choices_input = _filter_choices_by_area(choices_input, allowed_ids)
        choices_output = _filter_choices_by_area(choices_output, allowed_ids)
        choices_function = _filter_choices_by_area(choices_function, allowed_ids)
        choices_pid = _filter_choices_by_area(choices_pid, allowed_ids)
        choices_device = _filter_choices_by_area(choices_device, allowed_ids)
        # 태그 자체는 구역에 속하지 않는다("관수"는 농장 전체의 어휘다).
        # 구역에 속하는 것은 노트이므로, 그 구역에 노트가 있는 태그만 남긴다.
        try:
            from aot.aot_flask.geo import device_membership
            note_ids = device_membership.note_ids_in_area(
                area_filter, device_ids=allowed_ids)
            tag_ids = device_membership.tag_ids_for_notes(note_ids or set())
            # 태그 선택지의 value 는 `<uuid>,tag` 다(form_tag_choices).
            # uuid 그대로 비교하면 하나도 안 맞는다.
            choices_tag = [c for c in choices_tag
                           if str(c.get('value', '')).split(',')[0] in tag_ids]
        except Exception:
            logger.exception("[graph-async] 노트 태그 필터 실패")

    # 교체 이력이 하나도 없으면 이어 붙일 것이 없다. 그때 이 옵션을 보여주면
    # 지도를 쓰지 않는 사용자가 "장치를 바꾸면 뭔가 달라지나" 로 읽는다.
    has_replacements = False
    try:
        from aot.databases.models import GeoBinding, Notes
        has_replacements = bool(
            GeoBinding.query.filter(GeoBinding.valid_to.isnot(None)).first()
            or Notes.query.filter(Notes.category == 'maintenance').first())
    except Exception:
        logger.exception("[graph-async] 교체 이력 확인 실패")

    y_axes = utils_dashboard.graph_y_axes_async(dict_measurements,
                                                selected_ids_measures)

    return render_template('pages/graph-async.html',
                           conversion=Conversion,
                           async_height=async_height,
                           stitch_history=stitch_history,
                           has_replacements=has_replacements,
                           area_filter=area_filter,
                           choices_area=choices_area,
                           choices_device=choices_device,
                           selected_raw=selected_raw,
                           period=period,
                           start_time_epoch=start_time_epoch,
                           device_measurements_dict=device_measurements_dict,
                           dict_measure_measurements=dict_measure_measurements,
                           dict_measure_units=dict_measure_units,
                           dict_measurements=dict_measurements,
                           dict_units=dict_units,
                           use_unit=use_unit,
                           input=input_dev,
                           function=function,
                           output=output,
                           pid=pid,
                           tag=tag,
                           choices_input=choices_input,
                           choices_function=choices_function,
                           choices_output=choices_output,
                           choices_pid=choices_pid,
                           choices_tag=choices_tag,
                           selected_ids_measures=selected_ids_measures,
                           y_axes=y_axes)


@blueprint.route('/info', methods=('GET', 'POST'))
@flask_login.login_required
def page_info():
    """Display page with system information from command line tools."""
    if not utils_general.user_has_permission('view_stats'):
        return redirect(url_for('routes_general.home'))

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            flash(_('Insufficient permissions'), 'error')
        elif request.form.get('action') == 'save_gunicorn_threads':
            raw = (request.form.get('gunicorn_threads') or '').strip()
            mod_misc = Misc.query.first()
            try:
                if raw == '':
                    mod_misc.gunicorn_threads = None
                    mod_misc.save()
                    flash(_('Web server threads set to automatic. Applied after web server restart.'), 'success')
                else:
                    value = int(raw)
                    if not THREADS_MIN <= value <= THREADS_MAX * 2:
                        raise ValueError
                    mod_misc.gunicorn_threads = value
                    mod_misc.save()
                    flash(_('Web server threads set to %(num)s. Applied after web server restart.', num=value), 'success')
            except ValueError:
                flash(_('Enter an integer between %(min)s and %(max)s, or leave empty for automatic.',
                        min=THREADS_MIN, max=THREADS_MAX * 2), 'error')
        elif request.form.get('action') == 'restart_frontend':
            ok, message = reload_frontend(delay_sec=1, logger=logger)
            flash(message, 'success' if ok else 'error')
        elif request.form.get('action') == 'restart_daemon':
            ok, message = restart_daemon(delay_sec=1, logger=logger)
            flash(message, 'success' if ok else 'error')
        return redirect(url_for('routes_page.page_info'))

    virtualenv_flask = False
    virtualenv_daemon = False
    top_daemon_output = None
    frontend_pid = None
    pstree_frontend_output = None
    top_frontend_output = None

    def run_cmd(cmd):
        """Run a shell command; return decoded output or None."""
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            (out, _) = proc.communicate()
            proc.wait()
            return out.decode("latin1") if out else None
        except Exception:
            return None

    database_version = AlembicVersion.query.first().version_num
    correct_database_version = ALEMBIC_VERSION

    if hasattr(sys, 'real_prefix') or sys.base_prefix != sys.prefix:
        virtualenv_flask = True

    if not current_app.config['TESTING']:
        daemon_up = daemon_active()
    else:
        daemon_up = False

    if daemon_up is True:
        control = DaemonControl()
        ram_use_daemon = control.ram_use()
        virtualenv_daemon = control.is_in_virtualenv()
    else:
        ram_use_daemon = 0

    # Runtime environment summary card: prefer the daemon's startup snapshot
    # (the daemon runs as root and sees the host); fall back to local detection.
    # Command gating below always uses the LOCAL environment — in Docker the
    # web server and daemon run in different containers, so the daemon's
    # capabilities don't describe what this process can execute.
    local_env = detect_system_environment()
    system_env = None
    if daemon_up:
        try:
            system_env = DaemonControl().system_environment()
        except Exception:
            system_env = None
    if not system_env:
        system_env = local_env
    caps = local_env.get('capabilities', {})
    is_docker_env = local_env.get('platform_type') == 'docker'

    uptime_output = run_cmd("uptime")
    uname_output = run_cmd("uname -a")

    # GPIO pin map: Raspberry Pi only (gpio binary present)
    gpio_output = None
    if not current_app.config['TESTING'] and caps.get('gpio'):
        gpio_output = run_cmd("gpio readall")

    # Search for /dev/i2c- devices and compile a sorted dictionary of each
    # device's integer device number and the corresponding 'i2cdetect -y ID'
    # output for display on the info page
    i2c_devices_sorted = OrderedDict()
    if not current_app.config['TESTING'] and caps.get('i2c'):
        try:
            i2c_devices = glob.glob("/dev/i2c-*")
            for each_dev in i2c_devices:
                device_int = int(each_dev.replace("/dev/i2c-", ""))
                if device_int in [20, 21]:
                    continue
                i2cdetect_out = run_cmd(f"i2cdetect -y {device_int}")
                if i2cdetect_out:
                    i2c_devices_sorted[device_int] = i2cdetect_out
        except Exception as er:
            flash("Error detecting I2C devices: {er}".format(er=er), "error")
        finally:
            i2c_devices_sorted = OrderedDict(sorted(i2c_devices_sorted.items()))

    df_output = run_cmd("df -h")
    free_output = run_cmd("free -h")

    # Kernel log: not accessible (or not meaningful) inside a container
    dmesg_output = None
    if not is_docker_env and caps.get('dmesg'):
        dmesg_output = run_cmd("dmesg | tail -n 20")

    if caps.get('ifconfig'):
        ifconfig_output = run_cmd("ifconfig -a")
        network_cmd = 'ifconfig -a'
    else:
        ifconfig_output = run_cmd("ip addr")
        network_cmd = 'ip addr'

    if os.path.exists(FRONTEND_PID_FILE):
        with open(FRONTEND_PID_FILE, 'r') as pid_file:
            frontend_pid = int(pid_file.read())

    if frontend_pid:
        pstree_frontend_output, top_frontend_output = output_pstree_top(frontend_pid)

    ram_use_flask = resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / float(1000)

    python_version = sys.version

    # Web server (gunicorn) thread settings card. Uses a local detection
    # (not the daemon snapshot): the resolution must match what
    # install/gunicorn_conf.py computes for this web server process.
    effective_threads, threads_source = resolve_gunicorn_threads(
        database_path=SQL_DATABASE_AOT)
    misc_settings = Misc.query.first()
    gunicorn_info = {
        'effective': effective_threads,
        'source': threads_source,
        'recommended': recommended_threads(),
        'manual': misc_settings.gunicorn_threads if misc_settings else None,
        'env_override': os.environ.get('GUNICORN_THREADS'),
        'min': THREADS_MIN,
        'max': THREADS_MAX * 2,
        'can_edit': utils_general.user_has_permission('edit_settings'),
        'is_docker': DOCKER_CONTAINER,
    }

    return render_template('pages/info.html',
                           daemon_up=daemon_up,
                           system_env=system_env,
                           network_cmd=network_cmd,
                           gunicorn_info=gunicorn_info,
                           gpio_readall=gpio_output,
                           database_version=database_version,
                           correct_database_version=correct_database_version,
                           database_url=AOT_DB_PATH,
                           df=df_output,
                           dmesg_output=dmesg_output,
                           free=free_output,
                           frontend_pid=frontend_pid,
                           i2c_devices_sorted=i2c_devices_sorted,
                           ifconfig=ifconfig_output,
                           pstree_frontend=pstree_frontend_output,
                           python_version=python_version,
                           ram_use_daemon=ram_use_daemon,
                           ram_use_flask=ram_use_flask,
                           top_daemon=top_daemon_output,
                           top_frontend=top_frontend_output,
                           uname=uname_output,
                           uptime=uptime_output,
                           virtualenv_daemon=virtualenv_daemon,
                           virtualenv_flask=virtualenv_flask)


@blueprint.route('/ram')
@flask_login.login_required
def ram():
    """Return how much ram the frontend has used.

    Was reachable anonymously, disclosing the web process's memory footprint to
    anyone who could reach the host. Nothing in the frontend calls it, so
    gating it costs nothing.
    """
    return f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / float(1000)}"


def output_pstree_top(pid):
    """pid comes from FRONTEND_PID_FILE (the app's own pidfile, int-cast by
    the caller), not request input — but shell=True + string interpolation
    is still a needless foot-gun (and a guaranteed static-scanner flag), so
    this uses list args + no shell. int(pid) is a hard belt on top of the
    caller's cast: subprocess with a list never passes through a shell
    regardless, but a non-numeric pid would still fail the command cleanly
    instead of doing anything unexpected.

    pstree/top aren't installed in every environment (e.g. this repo's own
    Docker image has neither) — shell=True silently produced empty output
    in that case (the shell's own "command not found" swallowed by
    communicate()); a direct exec instead raises FileNotFoundError, so that
    has to be caught explicitly to keep the same graceful-empty behavior
    run_cmd() above already gives every other command on this page."""
    pid = str(int(pid))

    pstree_output = None
    try:
        pstree = subprocess.Popen(
            ["pstree", "-p", pid], stdout=subprocess.PIPE)
        (pstree_output, _) = pstree.communicate()
        pstree.wait()
        if pstree_output:
            pstree_output = pstree_output.decode("latin1")
    except OSError:
        pstree_output = None

    top_output = None
    try:
        top = subprocess.Popen(
            ["top", "-bH", "-n", "1", "-p", pid], stdout=subprocess.PIPE)
        (top_output, _) = top.communicate()
        top.wait()
        if top_output:
            top_output = top_output.decode("latin1")
    except OSError:
        top_output = None

    return pstree_output, top_output


@blueprint.route('/live', methods=('GET', 'POST'))
@flask_login.login_required
def page_live():
    """Page of recent and updating input data."""
    # Get what each measurement uses for a unit
    function = CustomController.query.all()
    device_measurements = DeviceMeasurements.query.all()
    input_dev = Input.query.all()
    output = Output.query.all()

    activated_inputs = Input.query.filter(Input.is_activated).count()
    activated_functions = CustomController.query.filter(CustomController.is_activated).count()

    use_unit = utils_general.use_unit_generate(
        device_measurements, input_dev, output, function)

    # Display orders
    display_order_input = csv_to_list_of_str(DisplayOrder.query.first().inputs)
    display_order_function = csv_to_list_of_str(DisplayOrder.query.first().function)

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    dict_controllers = parse_function_information()
    dict_inputs = parse_input_information()

    custom_options_values_controllers = parse_custom_option_values(
        function, dict_controller=dict_controllers)

    dict_measure_measurements = {}
    dict_measure_units = {}

    for each_measurement in device_measurements:
        conversion = Conversion.query.filter(
            Conversion.unique_id == each_measurement.conversion_id).first()
        _, unit, measurement = return_measurement_info(each_measurement, conversion)
        dict_measure_measurements[each_measurement.unique_id] = measurement
        dict_measure_units[each_measurement.unique_id] = unit

    live_inputs_list = Input.query.filter(Input.is_activated, ~Input.device.startswith('gis_')).order_by(Input.position_y.asc()).all()

    return render_template('pages/live.html',
                           and_=and_,
                           activated_inputs=activated_inputs,
                           activated_functions=activated_functions,
                           custom_options_values_controllers=custom_options_values_controllers,
                           table_device_measurements=DeviceMeasurements,
                           table_input=Input,
                           live_inputs_list=live_inputs_list,
                           table_function=CustomController,
                           dict_inputs=dict_inputs,
                           dict_measurements=dict_measurements,
                           dict_units=dict_units,
                           dict_measure_measurements=dict_measure_measurements,
                           dict_measure_units=dict_measure_units,
                           display_order_input=display_order_input,
                           display_order_function=display_order_function,
                           list_devices_adc=list_analog_to_digital_converters(),
                           measurement_units=MEASUREMENTS,
                           use_unit=use_unit)


@blueprint.route('/logview', methods=('GET', 'POST'))
@flask_login.login_required
def page_logview():
    """Display the last (n) lines from a log file."""
    if not utils_general.user_has_permission('view_logs'):
        return redirect(url_for('routes_general.home'))

    form_log_view = forms_misc.LogView()
    log_output = None
    lines = 30
    search = ''
    logfile = ''
    log_field = None
    command = None

    if form_log_view.lines.data:
        lines = form_log_view.lines.data

    if form_log_view.search.data:
        search = form_log_view.search.data

    if form_log_view.log.data:
        log_field = form_log_view.log.data

    # Find which log file was requested, generate command to execute
    if form_log_view.log.data == 'log_nginx':
        if DOCKER_CONTAINER:
            command = f'docker logs -n {lines} aot_nginx'
            if search:
                command += f' 2>&1 | grep "{search}"'
        else:
            command = f'journalctl -u nginx -n {lines} --no-pager'
            if search:
                command += f' | grep "{search}"'
    elif form_log_view.log.data == 'log_flask':
        if DOCKER_CONTAINER:
            command = f'docker logs -n {lines} aot_flask'
            if search:
                command += f' 2>&1 | grep "{search}"'
        else:
            command = f'journalctl -u aotflask -n {lines} --no-pager'
            if search:
                command += f' | grep "{search}"'
    elif form_log_view.log.data == 'log_pid_settings':
        logfile = DAEMON_LOG_FILE
        logrotate_file = logfile + '.1'
        if (logrotate_file and os.path.exists(logrotate_file) and
                logfile and os.path.isfile(logfile)):
            command = f'cat {logrotate_file} {logfile} | grep -a "PID Settings" | tail -n {lines}'
        else:
            command = f'grep -a "PID Settings" {logfile} | tail -n {lines}'
    else:
        if form_log_view.log.data == 'log_login':
            logfile = LOGIN_LOG_FILE
        elif form_log_view.log.data == 'log_http_access':
            logfile = HTTP_ACCESS_LOG_FILE
        elif form_log_view.log.data == 'log_http_error':
            logfile = HTTP_ERROR_LOG_FILE
        elif form_log_view.log.data == 'log_daemon':
            logfile = DAEMON_LOG_FILE
        elif form_log_view.log.data == 'log_dependency':
            logfile = DEPENDENCY_LOG_FILE
        elif form_log_view.log.data == 'log_import':
            logfile = IMPORT_LOG_FILE
        elif form_log_view.log.data == 'log_keepup':
            logfile = KEEPUP_LOG_FILE
        elif form_log_view.log.data == 'log_backup':
            logfile = BACKUP_LOG_FILE
        elif form_log_view.log.data == 'log_restore':
            logfile = RESTORE_LOG_FILE
        elif form_log_view.log.data == 'log_upgrade':
            logfile = UPGRADE_LOG_FILE
        else:
            logfile = DAEMON_LOG_FILE  # Default

        logrotate_file = logfile + '.1'
        if (logrotate_file and os.path.exists(logrotate_file) and
                logfile and os.path.isfile(logfile)):
            command = f'cat {logrotate_file} {logfile} | tail -n {lines}'
            if search:
                command += f' | grep "{search}"'
        elif os.path.isfile(logfile):
            command = f'tail -n {lines} {logfile}'
            if search:
                command += f' | grep "{search}"'

    # Execute command and generate the output to display to the user
    if command:
        log = subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
        (log_output, _) = log.communicate()
        log.wait()
        log_output = str(log_output, 'utf-8', errors='replace')
    else:
        log_output = 404

    return render_template('tools/logview.html',
                           form_log_view=form_log_view,
                           lines=lines,
                           log_field=log_field,
                           logfile=logfile,
                           log_output=log_output,
                           search=search)


# Audit log actions offered in the filter dropdown. Kept in sync with the
# constants in aot/utils/audit.py.
AUDIT_ACTION_CHOICES = [
    'login.success', 'login.failure', 'login.locked', 'logout',
    'password.reset', 'user.create', 'user.modify', 'user.delete',
    'settings.change', 'output.control', 'data.export', 'data.import',
    'apikey.issue', 'remote.token_issue',
]


def _audit_log_query():
    """Build the AuditLog query from the request's filter arguments."""
    from aot.databases.models import AuditLog

    query = AuditLog.query

    action = request.args.get('action') or ''
    username = request.args.get('username') or ''
    result = request.args.get('result') or ''

    if action:
        query = query.filter(AuditLog.action == action)
    if username:
        query = query.filter(AuditLog.username.ilike('%{}%'.format(username)))
    if result:
        query = query.filter(AuditLog.result == result)

    return query.order_by(AuditLog.timestamp.desc()), action, username, result


@blueprint.route('/audit_log', methods=('GET',))
@flask_login.login_required
def page_audit_log():
    """Audit trail of user actions (logins, settings changes, device control).

    Gated on view_logs, the same permission the log viewer uses.
    """
    if not utils_general.user_has_permission('view_logs'):
        return redirect(url_for('routes_general.home'))

    query, action, username, result = _audit_log_query()

    try:
        limit = min(int(request.args.get('limit', 200)), 1000)
    except (TypeError, ValueError):
        limit = 200

    entries = query.limit(limit).all()

    # Stored UTC, displayed in the viewer's local zone — the project's single
    # source of truth for this is aot.utils.time_utils (docs/design/timezone-management.md).
    from aot.utils.time_utils import to_local
    for entry in entries:
        try:
            entry.local_timestamp = to_local(entry.timestamp).strftime(
                '%Y-%m-%d %H:%M:%S')
        except Exception:
            entry.local_timestamp = entry.timestamp

    return render_template('tools/audit_log.html',
                           entries=entries,
                           action_choices=AUDIT_ACTION_CHOICES,
                           filter_action=action,
                           filter_username=username,
                           filter_result=result,
                           limit=limit)


@blueprint.route('/audit_log/export', methods=('GET',))
@flask_login.login_required
def page_audit_log_export():
    """Export the filtered audit trail as CSV (for procurement/audit review).

    Streams rather than building one string: an audit trail kept for a year can
    be large, and materialising it would spike memory on the single worker.
    """
    if not utils_general.user_has_permission('view_logs'):
        return redirect(url_for('routes_general.home'))

    query, _, _, _ = _audit_log_query()

    def generate():
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def flush():
            buffer.seek(0)
            chunk = buffer.read()
            buffer.seek(0)
            buffer.truncate(0)
            return chunk

        writer.writerow(['timestamp_utc', 'action', 'result', 'username',
                         'user_id', 'ip_address', 'target_type', 'target_id',
                         'target_name', 'detail', 'before', 'after'])
        yield flush()

        for row in query.yield_per(500):
            writer.writerow([
                row.timestamp.isoformat() if row.timestamp else '',
                row.action, row.result, row.username or '',
                row.user_id if row.user_id is not None else '',
                row.ip_address or '', row.target_type or '',
                row.target_id or '', row.target_name or '',
                row.detail or '', row.before_json or '', row.after_json or '',
            ])
            yield flush()

    from aot.utils.audit import DATA_EXPORT, audit_log
    audit_log(DATA_EXPORT, target_type='AuditLog', detail='CSV export')

    # stream_with_context is required, not cosmetic: a bare generator is
    # consumed *after* the view returns, by which point the request/app
    # context is gone and every DB access inside generate() raises
    # "Working outside of application context".
    return Response(
        stream_with_context(generate()),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=aot_audit_log.csv'})


@blueprint.route('/energy_usage_input_amp', methods=('GET', 'POST'))
@flask_login.login_required
def page_energy_usage_input_amps():
    """Display output usage (duration and energy usage/cost)"""
    if not utils_general.user_has_permission('view_stats'):
        return redirect(url_for('routes_general.home'))

    calculate_pass = False

    form_energy_usage_add = forms_misc.EnergyUsageAdd()
    form_energy_usage_mod = forms_misc.EnergyUsageMod()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_controllers'):
            return redirect(url_for('routes_page.page_usage'))

        if form_energy_usage_add.energy_usage_add.data:
            dep_unmet, _unused, _unmet = return_dependencies('highstock')
            if dep_unmet:
                return redirect(url_for('routes_admin.admin_dependencies',
                                        device='highstock'))
            utils_misc.energy_usage_add(form_energy_usage_add)
        elif form_energy_usage_mod.energy_usage_mod.data:
            utils_misc.energy_usage_mod(form_energy_usage_mod)
        elif form_energy_usage_mod.energy_usage_delete.data:
            utils_misc.energy_usage_delete(
                form_energy_usage_mod.energy_usage_id.data)
        elif form_energy_usage_mod.energy_usage_range_calc.data:
            calculate_pass = True

        if not calculate_pass:
            return redirect(url_for('routes_page.page_energy_usage_input_amps'))

    energy_usage = EnergyUsage.query.all()
    input_dev = Input.query.all()
    function = CustomController.query.all()
    misc = Misc.query.first()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)

    energy_usage_stats, graph_info = return_energy_usage(
        energy_usage, DeviceMeasurements.query, Conversion.query)

    if calculate_pass:
        start_string = form_energy_usage_mod.energy_usage_date_range.data.split(' - ')[0]
        end_string = form_energy_usage_mod.energy_usage_date_range.data.split(' - ')[1]
        (calculate_usage,
         graph_info,
         picker_start,
         picker_end) = calc_energy_usage(
            form_energy_usage_mod.energy_usage_id.data,
            graph_info,
            start_string,
            end_string,
            EnergyUsage.query,
            DeviceMeasurements.query,
            Conversion.query,
            misc.output_usage_volts)
    else:
        calculate_usage = {}
        picker_start = {}
        picker_end = {}

    from aot.utils.time_utils import utc_now, to_local
    _local_now = to_local(utc_now())
    picker_end['default'] = _local_now.strftime('%m/%d/%Y %H:%M')
    picker_start['default'] = (_local_now - datetime.timedelta(hours=6)).strftime('%m/%d/%Y %H:%M')

    return render_template('pages/energy_usage_input_amps.html',
                           calculate_usage=calculate_usage,
                           choices_function=choices_function,
                           choices_input=choices_input,
                           energy_usage=energy_usage,
                           energy_usage_stats=energy_usage_stats,
                           form_energy_usage_add=form_energy_usage_add,
                           form_energy_usage_mod=form_energy_usage_mod,
                           graph_info=graph_info,
                           misc=misc,
                           picker_end=picker_end,
                           picker_start=picker_start)


@blueprint.route('/energy_usage_outputs', methods=('GET', 'POST'))
@flask_login.login_required
def page_energy_usage_outputs():
    """Display output usage (duration and energy usage/cost)"""
    if not utils_general.user_has_permission('view_stats'):
        return redirect(url_for('routes_general.home'))

    energy_usage = EnergyUsage.query.all()
    misc = Misc.query.first()
    output = Output.query.all()
    output_channel = OutputChannel.query.all()

    dict_outputs = parse_output_information()

    custom_options_values_output_channels = parse_custom_option_values_output_channels_json(
        output_channel, dict_controller=dict_outputs, key_name='custom_channel_options')

    output_stats = return_output_usage(
        dict_outputs, misc, output, OutputChannel, custom_options_values_output_channels)

    day = misc.output_usage_dayofmonth
    if 4 <= day <= 20 or 24 <= day <= 30:
        date_suffix = 'th'
    else:
        date_suffix = ['st', 'nd', 'rd'][day % 10 - 1]

    # Generate the order to display Outputs
    display_order = []
    for each_output in Output.query.order_by(Output.position_y).all():
        display_order.append(each_output.unique_id)

    return render_template('pages/energy_usage_outputs.html',
                           custom_options_values_output_channels=custom_options_values_output_channels,
                           date_suffix=date_suffix,
                           dict_outputs=dict_outputs,
                           display_order=display_order,
                           misc=misc,
                           output=output,
                           output_stats=output_stats,
                           output_types=output_types(),
                           table_output_channel=OutputChannel,
                           timestamp=time.strftime("%c"))


def dict_custom_colors():
    """
    Generate a dictionary of custom colors from CSV strings saved in the
    database. If custom colors aren't already saved, fill in with a default
    palette.

    :return: dictionary of graph_ids and lists of custom colors
    """
    if flask_login.current_user.theme in THEMES_DARK:
        default_palette = [
            '#2b908f', '#90ee7e', '#f45b5b', '#7798BF', '#aaeeee', '#ff0066',
            '#eeaaee', '#55BF3B', '#DF5353', '#7798BF', '#aaeeee'
        ]
    else:
        default_palette = [
            '#7cb5ec', '#434348', '#90ed7d', '#f7a35c', '#8085e9', '#f15c80',
            '#e4d354', '#2b908f', '#f45b5b', '#91e8e1'
        ]

    color_count = OrderedDict()
    graph = Widget.query.all()
    for each_graph in graph:
        # Only process graph widget types
        if each_graph.graph_type != 'graph':
            continue

        try:
            # Get current saved colors
            if each_graph.custom_colors:  # Split into list
                colors = each_graph.custom_colors.split(',')
            else:  # Create empty list
                colors = []
            # Fill end of list with empty strings
            while len(colors) < len(default_palette):
                colors.append('')

            # Populate empty strings with default colors
            for x, _ in enumerate(default_palette):
                if colors[x] == '':
                    colors[x] = default_palette[x]

            index = 0
            index_sum = 0
            total = []

            if each_graph.input_ids_measurements:
                for each_set in each_graph.input_ids_measurements.split(';'):
                    input_unique_id = each_set.split(',')[0]
                    input_measure_id = each_set.split(',')[1]

                    device_measurement = DeviceMeasurements.query.filter(
                        DeviceMeasurements.unique_id == input_measure_id).first()
                    if device_measurement:
                        measurement_name = device_measurement.name
                        conversion = Conversion.query.filter(
                            Conversion.unique_id == device_measurement.conversion_id).first()
                    else:
                        measurement_name = None
                        conversion = None
                    channel, unit, measurement = return_measurement_info(
                        device_measurement, conversion)

                    input_dev = Input.query.filter_by(
                        unique_id=input_unique_id).first()

                    # Custom colors
                    if (index < len(each_graph.input_ids_measurements.split(';')) and
                            len(colors) > index):
                        color = colors[index]
                    else:
                        color = '#FF00AA'

                    # Data grouping
                    disable_data_grouping = False
                    if input_measure_id in each_graph.disable_data_grouping:
                        disable_data_grouping = True

                    if None not in [input_dev, device_measurement]:
                        total.append({
                            'unique_id': input_unique_id,
                            'measure_id': input_measure_id,
                            'type': 'Input',
                            'name': input_dev.name,
                            'channel': channel,
                            'unit': unit,
                            'measure': measurement,
                            'measure_name': measurement_name,
                            'color': color,
                            'disable_data_grouping': disable_data_grouping})
                        index += 1
                index_sum += index

            if each_graph.output_ids:
                index = 0
                for each_set in each_graph.output_ids.split(';'):
                    output_unique_id = each_set.split(',')[0]
                    output_measure_id = each_set.split(',')[1]

                    device_measurement = DeviceMeasurements.query.filter(
                        DeviceMeasurements.unique_id == output_measure_id).first()
                    if device_measurement:
                        measurement_name = device_measurement.name
                        conversion = Conversion.query.filter(
                            Conversion.unique_id == device_measurement.conversion_id).first()
                    else:
                        measurement_name = None
                        conversion = None
                    channel, unit, measurement = return_measurement_info(
                        device_measurement, conversion)

                    output = Output.query.filter_by(
                        unique_id=output_unique_id).first()

                    if (index < len(each_graph.output_ids.split(';')) and
                            len(colors) > index_sum + index):
                        color = colors[index_sum + index]
                    else:
                        color = '#FF00AA'

                    # Data grouping
                    disable_data_grouping = False
                    if output_measure_id in each_graph.disable_data_grouping:
                        disable_data_grouping = True

                    if output is not None:
                        total.append({
                            'unique_id': output_unique_id,
                            'measure_id': output_measure_id,
                            'type': 'Output',
                            'name': output.name,
                            'channel': channel,
                            'unit': unit,
                            'measure': measurement,
                            'measure_name': measurement_name,
                            'color': color,
                            'disable_data_grouping': disable_data_grouping})
                        index += 1
                index_sum += index

            if each_graph.pid_ids:
                index = 0
                for each_set in each_graph.pid_ids.split(';'):
                    pid_unique_id = each_set.split(',')[0]
                    pid_measure_id = each_set.split(',')[1]

                    device_measurement = DeviceMeasurements.query.filter(
                        DeviceMeasurements.unique_id == pid_measure_id).first()
                    if device_measurement:
                        measurement_name = device_measurement.name
                        conversion = Conversion.query.filter(
                            Conversion.unique_id == device_measurement.conversion_id).first()
                    else:
                        measurement_name = None
                        conversion = None
                    channel, unit, measurement = return_measurement_info(
                        device_measurement, conversion)

                    pid = PID.query.filter_by(
                        unique_id=pid_unique_id).first()

                    # Custom colors
                    if (index < len(each_graph.pid_ids.split(';')) and
                            len(colors) > index_sum + index):
                        color = colors[index_sum + index]
                    else:
                        color = '#FF00AA'

                    # Data grouping
                    disable_data_grouping = False
                    if pid_measure_id in each_graph.disable_data_grouping:
                        disable_data_grouping = True

                    if pid is not None:
                        total.append({
                            'unique_id': pid_unique_id,
                            'measure_id': pid_measure_id,
                            'type': 'PID',
                            'name': pid.name,
                            'channel': channel,
                            'unit': unit,
                            'measure': measurement,
                            'measure_name': measurement_name,
                            'color': color,
                            'disable_data_grouping': disable_data_grouping})
                        index += 1
                index_sum += index

            if each_graph.note_tag_ids:
                index = 0
                for each_set in each_graph.note_tag_ids.split(';'):
                    tag_unique_id = each_set.split(',')[0]

                    device_measurement = NoteTags.query.filter_by(
                        unique_id=tag_unique_id).first()

                    if (index < len(each_graph.note_tag_ids.split(',')) and
                            len(colors) > index_sum + index):
                        color = colors[index_sum + index]
                    else:
                        color = '#FF00AA'
                    if device_measurement is not None:
                        total.append({
                            'unique_id': tag_unique_id,
                            'measure_id': None,
                            'type': 'Tag',
                            'name': device_measurement.name,
                            'channel': None,
                            'unit': None,
                            'measure': None,
                            'measure_name': None,
                            'color': color,
                            'disable_data_grouping': None
                        })
                        index += 1
                index_sum += index

            color_count.update({each_graph.unique_id: total})
        except IndexError:
            logger.exception("Index")
        except Exception:
            logger.exception("Exception")

    return color_count


def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
