# coding=utf-8
"""collection of Page endpoints."""
import flask_login
import json
import logging
import os
import subprocess
from flask import (redirect, render_template, request, url_for, jsonify,
                   get_flashed_messages)
from flask.blueprints import Blueprint
from sqlalchemy import and_, text

from aot.config import INSTALL_DIRECTORY
from aot.config import PATH_TEMPLATE_USER
from aot.databases.models import (PID, Camera, Conditional, Conversion,
                                     CustomController, Dashboard,
                                     DeviceMeasurements, Input, Measurement,
                                     Method, Misc, NoteTags, Output,
                                     OutputChannel, Trigger, Unit, Widget, GeoMap)
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_dashboard
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_dashboard, utils_general
from aot.utils.outputs import output_types, parse_output_information
from aot.utils.service_control import reload_frontend
from aot.utils.system_pi import (
    add_custom_measurements, add_custom_units, parse_custom_option_values_json,
    parse_custom_option_values_output_channels_json, return_measurement_info)
from aot.utils.widgets import parse_widget_information

logger = logging.getLogger('aot.aot_flask.routes_dashboard')

# # [Temporary Debug] Redirect logs to a local file in the workspace
# try:
#     local_log_path = os.path.join(INSTALL_DIRECTORY, 'aot_map_debug.log')
#     file_handler = logging.FileHandler(local_log_path)
#     file_handler.setLevel(logging.INFO)
#     formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     file_handler.setFormatter(formatter)
#     logger.addHandler(file_handler)
#     # Also add to the widget logger
#     from aot.widgets import AoT_map
#     AoT_map.logger.addHandler(file_handler)
# except Exception as e:
#     print(f"Failed to setup local debug log: {e}")

blueprint = Blueprint('routes_dashboard',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/save_dashboard_layout', methods=['POST'])
@flask_login.login_required
def save_dashboard_layout():
    """Save positions and sizes of widgets of a particular dashboard."""
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))
    data = request.get_json()
    keys = ('id', 'x', 'y', 'w', 'h')
    for index, each_widget in enumerate(data):
        if all(k in each_widget for k in keys):
            widget_mod = Widget.query.filter(
                Widget.unique_id == each_widget['id']).first()
            if widget_mod:
                widget_mod.position_x = each_widget['x']
                widget_mod.position_y = each_widget['y']
                widget_mod.width = each_widget['w']
                widget_mod.height = each_widget['h']
    db.session.commit()
    return "success"


@blueprint.route('/save_widget_custom_options', methods=['POST'])
@flask_login.login_required
def save_widget_custom_options():
    """Update custom_options for a specific widget via AJAX."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({"status": "forbidden"}), 403

    try:
        import json
        data = request.get_json()
        widget_id = data.get('widget_id')
        new_options = data.get('options', {})
        
        logger.debug(f"[AoT Map Debug] AJAX Save Order - Widget: {widget_id}, Options: {new_options}")

        if not widget_id:
            return jsonify({"status": "error", "message": "Missing widget_id"}), 400

        widget = Widget.query.filter(Widget.unique_id == widget_id).first()
        if not widget:
            return jsonify({"status": "error", "message": "Widget not found"}), 404

        # [Refactor] Use execute_at_modification if available to ensure logic consistency (e.g. field mapping)
        try:
            current_options = json.loads(widget.custom_options) if widget.custom_options else {}
        except Exception:
            current_options = {}

        dict_widgets = parse_widget_information()
        if widget.graph_type in dict_widgets and 'execute_at_modification' in dict_widgets[widget.graph_type]:
             # Call widget-specific modification logic (haromizes AJAX and Form save paths)
             logger.debug(f"[AoT Map Debug] Calling execute_at_modification for {widget.unique_id}")
             (allow_saving, 
              page_refresh, 
              widget, 
              final_options) = dict_widgets[widget.graph_type]['execute_at_modification'](
                 widget, None, current_options, new_options)
             
             if not allow_saving:
                 logger.warning(f"[AoT Map Debug] Modification rejected for {widget.unique_id}")
                 return jsonify({"status": "error", "message": "Modification rejected by widget"}), 400
             
             logger.debug(f"[AoT Map Debug] Final Options to be saved: {final_options}")
             widget.custom_options = json.dumps(final_options)
        else:
            # Fallback simple merge
            logger.debug(f"[AoT Map Debug] No execute_at_modification found, performing simple merge.")
            current_options.update(new_options)
            widget.custom_options = json.dumps(current_options)

        logger.debug(f"[AoT Map Debug] Committing to DB for {widget.unique_id}")
        db.session.commit()
        logger.debug(f"[AoT Map Debug] Save successful for {widget.unique_id}")

        return jsonify({"status": "success"})
    except Exception as e:
        logger.exception("Error saving widget custom options")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/get_widget_custom_options/<widget_id>', methods=['GET'])
@flask_login.login_required
def get_widget_custom_options(widget_id):
    """Return a widget's CURRENT saved custom_options as JSON.

    Settings-modal option values are baked into the page HTML once, at page
    load (the modal body ships inert inside a <template> and is only cloned
    into the live DOM on first open — see dashboard_entry.html). A widget
    like AoT_map can also be changed from its own in-map controls (shape/
    layer/label toggles all call /save_widget_custom_options directly), so
    a modal opened later in the same page session can show stale values.
    This lets the modal-open handler re-sync form fields to the DB's current
    state right before showing, instead of the page-load snapshot.

    Gated to match its write-side twin /save_widget_custom_options: a widget's
    custom_options can hold credentials (API-key fields fill in here via the
    key picker), so a read-only role must not be able to read them back out.
    Only ever called when a settings modal opens, which is already an edit
    action, so the gate costs nothing in normal use.
    """
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({"status": "error", "message": "Permission denied"}), 403

    try:
        widget = Widget.query.filter(Widget.unique_id == widget_id).first()
        if not widget:
            return jsonify({"status": "error", "message": "Widget not found"}), 404
        try:
            options = json.loads(widget.custom_options) if widget.custom_options else {}
        except Exception:
            options = {}
        return jsonify({"status": "success", "custom_options": options})
    except Exception as e:
        logger.exception("Error fetching widget custom options")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/api/widget/aot_map/<widget_id>/measurements_panel', methods=['POST'])
@flask_login.login_required
def get_aot_map_measurements_panel(widget_id):
    """Resolve the AoT Map 'Measurement Panel' selection (measurements_input/
    output/function) into the same measurements_map the page render uses.

    Device markers already have a live-refresh path (/api/geo/devices takes
    device_ids straight from the client, no DB round-trip needed to interpret
    them). The measurement panel doesn't: measurements_input/output/function
    are raw 'device_id::measurement_id' pairs, and turning them into display-
    ready rows (name, channel, unit, current value placeholder) requires the
    same DeviceMeasurements/Conversion lookups generate_page_variables_logic
    already does at page render. Reusing that function here — instead of
    duplicating its measurement-resolution logic client-side — is what lets
    the Measurement Panel selects auto-save and update live instead of only
    taking effect after a full page reload.

    Takes the selection straight from the request body (not read back from
    the DB): the auto-save POST to /save_widget_custom_options and this call
    fire back-to-back from the same debounced change handler with no
    ordering guarantee between them, so reading widget.custom_options here
    could race the save and resolve against the pre-change selection.
    """
    try:
        widget = Widget.query.filter(Widget.unique_id == widget_id).first()
        if not widget:
            return jsonify({"status": "error", "message": "Widget not found"}), 404
        try:
            options = json.loads(widget.custom_options) if widget.custom_options else {}
        except Exception:
            options = {}
        body = request.get_json(silent=True) or {}
        for key in ('measurements_input', 'measurements_output', 'measurements_function'):
            if key in body:
                options[key] = body[key]
        from aot.aot_flask.geo.widget.maps import generate_page_variables_logic
        result = generate_page_variables_logic(widget_id, options)
        return jsonify({"status": "success", "measurements_map": result.get('measurements_map', {})})
    except Exception as e:
        logger.exception("Error resolving AoT Map measurements panel")
        return jsonify({"status": "error", "message": str(e)}), 500


# Route for saving dashboard tab order (after blueprint and imports)
@blueprint.route('/save_dashboard_order', methods=['POST'])
@flask_login.login_required
def save_dashboard_order():
    """Persist user-defined dashboard ordering and return server order."""
    try:
        if not utils_general.user_has_permission('edit_controllers'):
            return jsonify({"status": "forbidden"}), 403

        try:
            order_list = request.get_json(force=True)
        except Exception as e:
            return jsonify({"status": "bad_request", "error": str(e)}), 400

        if not isinstance(order_list, list):
            return jsonify({"status": "bad_request", "error": "expected list"}), 400

        # Normalize using raw SQL to avoid any ORM attribute dependency
        updated = 0

        # fetch current full order from DB (portable NULLS LAST)
        result = db.session.execute(text(
            "SELECT unique_id FROM dashboard ORDER BY COALESCE(sort_order, 999999), id"
        ))
        all_uids = [row[0] for row in result]

        # build final order: payload first (dedup), then remaining
        seen = set()
        ordered_uids = []
        for uid in order_list:
            if uid not in seen:
                ordered_uids.append(uid)
                seen.add(uid)
        for uid in all_uids:
            if uid not in seen:
                ordered_uids.append(uid)
                seen.add(uid)

        # apply contiguous sort_order via raw UPDATEs
        pos = 0
        for uid in ordered_uids:
            res = db.session.execute(
                text("UPDATE dashboard SET sort_order = :pos WHERE unique_id = :uid"),
                {"pos": pos, "uid": uid}
            )
            if res.rowcount:
                updated += res.rowcount
            pos += 1

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"status": "db_error", "error": str(e)}), 500

        # Compute server-side order using raw SQL (portable across dialects)
        result = db.session.execute(text(
            "SELECT unique_id FROM dashboard ORDER BY COALESCE(sort_order, 999999), id"
        ))
        ordered = [row[0] for row in result]

        return jsonify({"status": "ok", "updated": updated, "server_order": ordered}), 200
    except Exception as e:
        # Catch-all to avoid 500 with HTML; return JSON so frontend can display
        return jsonify({"status": "error", "error": str(e)}), 500
    finally:
        # Ensure no stale identity map within this worker
        try:
            db.session.remove()
        except Exception:
            pass


@blueprint.route('/dashboard', methods=('GET', 'POST'))
@flask_login.login_required
def page_dashboard_default():
    """Load default dashboard according to sort_order."""
    dashboard = Dashboard.query.order_by(text("COALESCE(sort_order, 999999), id")).first()
    if dashboard:
        return redirect(url_for(
            'routes_dashboard.page_dashboard', dashboard_id=dashboard.unique_id))
    return redirect(url_for('routes_general.home'))


@blueprint.route('/dashboard-add', methods=('GET', 'POST'))
@flask_login.login_required
def page_dashboard_add():
    """Add a dashboard."""
    if not utils_general.user_has_permission('edit_controllers'):
        return redirect(url_for('routes_general.home'))
    dashboard_id = utils_dashboard.dashboard_add()
    return redirect(url_for(
        'routes_dashboard.page_dashboard', dashboard_id=dashboard_id))


@blueprint.route('/dashboard/<dashboard_id>', methods=('GET', 'POST'))
@flask_login.login_required
def page_dashboard(dashboard_id):
    logger.info(f"\n[DASHBOARD TRACE] Loading dashboard: {dashboard_id}\n")
    """Generate custom dashboard with various data."""
    this_dashboard = Dashboard.query.filter(
        Dashboard.unique_id == dashboard_id).first()
    if not this_dashboard:
        return redirect(url_for('routes_dashboard.page_dashboard_default'))

    # Create form objects
    form_base = forms_dashboard.DashboardBase()
    form_dashboard = forms_dashboard.DashboardConfig()

    if request.method == 'POST':

        unmet_dependencies = None
        if not utils_general.user_has_permission('edit_controllers'):
            return redirect(url_for('routes_general.home'))

        # Dashboard
        if form_dashboard.dash_modify.data:
            utils_dashboard.dashboard_mod(form_dashboard)
        elif form_dashboard.dash_duplicate.data:
            utils_dashboard.dashboard_copy(form_dashboard)
        elif form_dashboard.lock.data:
            utils_dashboard.dashboard_lock(form_dashboard.dashboard_id.data, True)
        elif form_dashboard.unlock.data:
            utils_dashboard.dashboard_lock(form_dashboard.dashboard_id.data, False)
        elif form_dashboard.dash_delete.data:
            utils_dashboard.dashboard_del(form_dashboard)
            return redirect(url_for('routes_dashboard.page_dashboard_default'))

        # Widget
        elif form_base.widget_add.data:
            unmet_dependencies, reload_flask = utils_dashboard.widget_add(form_base, request.form)
            if not unmet_dependencies and reload_flask:
                return redirect(url_for(
                    'routes_dashboard.restart_flask_auto_advance_page',
                    dashboard_id=this_dashboard.unique_id))
        elif form_base.widget_mod.data:
            utils_dashboard.widget_mod(form_base, request.form)
            # Live save: return the freshly-rendered widget body instead of a full
            # page redirect so the dashboard reflects the saved options in place.
            if request.form.get('ajax_live') == '1':
                # Drain flashes queued by widget_mod so they don't surface stale on
                # the next full page load.
                get_flashed_messages()
                widget = Widget.query.filter(
                    Widget.unique_id == form_base.widget_id.data).first()
                if widget:
                    dict_widgets = parse_widget_information()
                    options_values = parse_custom_option_values_json(
                        [widget], dict_controller=dict_widgets).get(widget.unique_id, {})
                    html, js_ready_end = _render_widget_fragments(
                        this_dashboard, this_dashboard.unique_id, widget,
                        options_values, dict_widgets, form_base, form_dashboard)
                    return jsonify({'html': html, 'js_ready_end': js_ready_end,
                                    'name': widget.name})
                return jsonify({'html': None, 'error': 'widget not found'}), 404
        elif form_base.widget_duplicate.data:
            utils_dashboard.widget_duplicate(form_base)
        elif form_base.widget_delete.data:
            utils_dashboard.widget_del(form_base)

        if unmet_dependencies:
            return redirect(url_for('routes_admin.admin_dependencies',
                                    device=form_base.widget_type.data))

        return redirect(url_for(
            'routes_dashboard.page_dashboard', dashboard_id=this_dashboard.unique_id))

    context = _build_dashboard_render_context(
        this_dashboard, dashboard_id, form_base, form_dashboard)
    return render_template('pages/dashboard.html', **context)


def _build_dashboard_render_context(this_dashboard, dashboard_id, form_base, form_dashboard):
    """Build the full render context for the dashboard page.

    Shared by page_dashboard (full page) and the live-preview / AJAX-save widget
    body fragment renders, so a widget body rendered for preview never drifts
    from how the same body renders on a full page load. Returns a dict of
    template kwargs.
    """
    # Retrieve tables from SQL database
    camera = Camera.query.all()
    conditional = Conditional.query.all()
    function = CustomController.query.all()
    widget = Widget.query.all()
    input_dev = Input.query.all()
    device_measurements = DeviceMeasurements.query.all()
    method = Method.query.all()
    misc = Misc.query.first()
    output = Output.query.all()
    output_channel = OutputChannel.query.all()
    pid = PID.query.all()
    tags = NoteTags.query.all()

    # Generate all measurement and units used
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())

    # Generate dictionary of each measurement ID with the correct measurement/unit used with it
    dict_measure_measurements = {}
    dict_measure_units = {}

    # 사전 조회 dict 로 루프 내 건별 쿼리(N+1) 제거
    pid_by_id = {p.unique_id: p for p in pid}
    measurement_by_id = {m.unique_id: m for m in device_measurements}
    conversion_by_id = {c.unique_id: c for c in Conversion.query.all()}

    for each_measurement in device_measurements:
        # If the measurement is a PID setpoint, set unit to PID measurement.
        measurement = None
        unit = None
        if each_measurement.measurement_type == 'setpoint':
            setpoint_pid = pid_by_id.get(each_measurement.device_id)
            if setpoint_pid and ',' in setpoint_pid.measurement:
                pid_measurement = setpoint_pid.measurement.split(',')[1]
                setpoint_measurement = measurement_by_id.get(pid_measurement)
                if setpoint_measurement:
                    conversion = conversion_by_id.get(setpoint_measurement.conversion_id)
                    _, unit, measurement = return_measurement_info(setpoint_measurement, conversion)
        else:
            conversion = conversion_by_id.get(each_measurement.conversion_id)
            _, unit, measurement = return_measurement_info(each_measurement, conversion)
        if unit:
            dict_measure_measurements[each_measurement.unique_id] = measurement
            dict_measure_units[each_measurement.unique_id] = unit

    dict_outputs = parse_output_information()
    dict_widgets = parse_widget_information()

    custom_options_values_widgets = parse_custom_option_values_json(
        widget, dict_controller=dict_widgets)

    custom_options_values_output_channels = parse_custom_option_values_output_channels_json(
        output_channel, dict_controller=dict_outputs, key_name='custom_channel_options')

    widget_types_on_dashboard = []
    custom_widget_variables = {}
    widgets_dash = Widget.query.filter(Widget.tab_id == dashboard_id).all()
    logger.info(f"[DASHBOARD] Loading widgets for dashboard_id={dashboard_id}, found {len(widgets_dash)} widgets")
    for each_dash_widget in widgets_dash:
        # Make list of widget types on this particular dashboard
        meta = dict_widgets.get(each_dash_widget.graph_type)
        if not meta:
            logger.warning("Dashboard widget type not found: %s (widget id=%s)", each_dash_widget.graph_type, each_dash_widget.unique_id)
            continue
        if each_dash_widget.graph_type not in widget_types_on_dashboard:
            widget_types_on_dashboard.append(each_dash_widget.graph_type)

        # Generate dictionary of returned values from widget modules on this particular dashboard
        if 'generate_page_variables' in meta:
            custom_widget_variables[each_dash_widget.unique_id] = meta['generate_page_variables'](
                each_dash_widget.unique_id, custom_options_values_widgets[each_dash_widget.unique_id])

    # generate lists of html files to include in dashboard template
    list_html_files_body = {}
    list_html_files_title_bar = {}
    list_html_files_head = {}
    list_html_files_configure_options = {}
    list_html_files_js = {}
    list_html_files_js_ready = {}
    list_html_files_js_ready_end = {}

    for each_widget_type in widget_types_on_dashboard:
        file_html_head = "widget_template_{}_head.html".format(each_widget_type)
        path_html_head = os.path.join(PATH_TEMPLATE_USER, file_html_head)
        if os.path.exists(path_html_head):
            list_html_files_head[each_widget_type] = file_html_head

        file_html_title_bar = "widget_template_{}_title_bar.html".format(each_widget_type)
        path_html_title_bar = os.path.join(PATH_TEMPLATE_USER, file_html_title_bar)
        if os.path.exists(path_html_title_bar):
            list_html_files_title_bar[each_widget_type] = file_html_title_bar

        file_html_body = "widget_template_{}_body.html".format(each_widget_type)
        path_html_body = os.path.join(PATH_TEMPLATE_USER, file_html_body)
        if os.path.exists(path_html_body):
            list_html_files_body[each_widget_type] = file_html_body

        file_html_configure_options = "widget_template_{}_configure_options.html".format(each_widget_type)
        path_html_configure_options = os.path.join(PATH_TEMPLATE_USER, file_html_configure_options)
        if os.path.exists(path_html_configure_options):
            list_html_files_configure_options[each_widget_type] = file_html_configure_options

        file_html_js = "widget_template_{}_js.html".format(each_widget_type)
        path_html_js = os.path.join(PATH_TEMPLATE_USER, file_html_js)
        if os.path.exists(path_html_js):
            list_html_files_js[each_widget_type] = file_html_js

        file_html_js_ready = "widget_template_{}_js_ready.html".format(each_widget_type)
        path_html_js_ready = os.path.join(PATH_TEMPLATE_USER, file_html_js_ready)
        if os.path.exists(path_html_js_ready):
            list_html_files_js_ready[each_widget_type] = file_html_js_ready

        file_html_js_ready_end = "widget_template_{}_js_ready_end.html".format(each_widget_type)
        path_html_js_ready_end = os.path.join(PATH_TEMPLATE_USER, file_html_js_ready_end)
        if os.path.exists(path_html_js_ready_end):
            list_html_files_js_ready_end[each_widget_type] = file_html_js_ready_end

    # Retrieve all choices to populate form drop-down menu
    choices_camera = utils_general.choices_id_name(camera)
    choices_function = utils_general.choices_functions(
        function, dict_units, dict_measurements)
    choices_input = utils_general.choices_inputs(
        input_dev, dict_units, dict_measurements)
    choices_method = utils_general.choices_methods(method)
    choices_output = utils_general.choices_outputs(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_channels = utils_general.choices_outputs_channels(
        output, output_channel, dict_outputs)
    choices_output_channels_measurements = utils_general.choices_outputs_channels_measurements(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_output_pwm = utils_general.choices_outputs_pwm(
        output, OutputChannel, dict_outputs, dict_units, dict_measurements)
    choices_pid = utils_general.choices_pids(
        pid, dict_units, dict_measurements)
    choices_pid_devices = utils_general.choices_pids_devices(pid)
    choices_tag = utils_general.choices_tags(tags)

    device_measurements_dict = {}
    for meas in device_measurements:
        device_measurements_dict[meas.unique_id] = meas

    # Get what each measurement uses for a unit
    use_unit = utils_general.use_unit_generate(
        device_measurements, input_dev, output, function)

    return dict(
                           and_=and_,
                           conditional=conditional,
                           custom_options_values_output_channels=custom_options_values_output_channels,
                           custom_options_values_widgets=custom_options_values_widgets,
                           custom_widget_variables=custom_widget_variables,
                           table_conversion=Conversion,
                           table_function=CustomController,
                           table_widget=Widget,
                           table_input=Input,
                           table_output=Output,
                           table_output_channel=OutputChannel,
                           table_pid=PID,
                           table_device_measurements=DeviceMeasurements,
                           table_camera=Camera,
                           table_conditional=Conditional,
                           table_trigger=Trigger,
                           table_geomap=GeoMap,
                           choices_camera=choices_camera,
                           choices_function=choices_function,
                           choices_input=choices_input,
                           choices_method=choices_method,
                           choices_output=choices_output,
                           choices_output_channels=choices_output_channels,
                           choices_output_channels_measurements=choices_output_channels_measurements,
                           choices_output_pwm=choices_output_pwm,
                           choices_pid=choices_pid,
                           choices_pid_devices=choices_pid_devices,
                           choices_tag=choices_tag,
                           dashboard_id=this_dashboard.unique_id,
                           device_measurements_dict=device_measurements_dict,
                           dict_measure_measurements=dict_measure_measurements,
                           dict_measure_units=dict_measure_units,
                           dict_measurements=dict_measurements,
                           dict_outputs=dict_outputs,
                           dict_units=dict_units,
                           dict_widgets=dict_widgets,
                           list_html_files_head=list_html_files_head,
                           list_html_files_title_bar=list_html_files_title_bar,
                           list_html_files_body=list_html_files_body,
                           list_html_files_configure_options=list_html_files_configure_options,
                           list_html_files_js=list_html_files_js,
                           list_html_files_js_ready=list_html_files_js_ready,
                           list_html_files_js_ready_end=list_html_files_js_ready_end,
                           camera=camera,
                           function=function,
                           misc=misc,
                           pid=pid,
                           output=output,
                           output_types=output_types(),
                           input=input_dev,
                           tags=tags,
                           this_dashboard=this_dashboard,
                           use_unit=use_unit,
                           widgets_dash=widgets_dash,
                           widget_types_on_dashboard=widget_types_on_dashboard,
                           form_base=form_base,
                           form_dashboard=form_dashboard,
                           widget=widget)


def _render_widget_fragments(this_dashboard, dashboard_id, widget,
                             options_values, dict_widgets,
                             form_base, form_dashboard):
    """Render a single widget's body markup and its js_ready_end init script for
    ``options_values`` (which may be unsaved), reusing the shared page context so
    a previewed/re-initialised widget renders exactly as on a full page load.

    Returns ``(body_html, js_ready_end_html)``. ``body_html`` is the content of
    #container-graph-<id>; ``js_ready_end_html`` re-creates chart-type widgets
    (Highcharts) — the client re-executes it for those widget types so option
    changes take effect without a page reload. Text-only widgets (e.g.
    widget_measurement) ignore the script and just swap the body.
    """
    context = _build_dashboard_render_context(
        this_dashboard, dashboard_id, form_base, form_dashboard)
    context['custom_options_values_widgets'][widget.unique_id] = options_values
    meta = dict_widgets.get(widget.graph_type, {})
    if 'generate_page_variables' in meta:
        context['custom_widget_variables'][widget.unique_id] = \
            meta['generate_page_variables'](widget.unique_id, options_values)
    body_html = render_template(
        'pages/dashboard_widget_body_fragment.html',
        each_widget=widget, **context)
    js_ready_end_html = render_template(
        'pages/dashboard_widget_js_ready_end_fragment.html',
        each_widget=widget, **context)
    return body_html, js_ready_end_html


@blueprint.route('/dashboard/<dashboard_id>/widget/<widget_id>/preview',
                 methods=('POST',))
@flask_login.login_required
def preview_widget_options(dashboard_id, widget_id):
    """Render a widget body from posted (unsaved) option values for live preview.

    Never writes to the database — the session is rolled back before returning,
    so toggling options in the settings modal updates the on-dashboard widget
    without persisting anything until the user explicitly saves.
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'error': 'permission denied'}), 403
    this_dashboard = Dashboard.query.filter(
        Dashboard.unique_id == dashboard_id).first()
    if not this_dashboard:
        return jsonify({'error': 'dashboard not found'}), 404
    widget = Widget.query.filter(Widget.unique_id == widget_id).first()
    if not widget:
        return jsonify({'error': 'widget not found'}), 404

    dict_widgets = parse_widget_information()
    try:
        presave = json.loads(widget.custom_options) if widget.custom_options else {}
    except Exception:
        presave = {}

    error = []
    _, postsave_json = utils_general.custom_options_return_json(
        error, dict_widgets, request.form, mod_dev=widget,
        device=widget.graph_type, custom_options=presave)

    # Mirror a real save's derived-value logic (execute_at_modification) so the
    # preview matches what saving would produce, then merge defaults via the same
    # path the page uses. Nothing is committed.
    meta = dict_widgets.get(widget.graph_type, {})
    if 'execute_at_modification' in meta:
        try:
            (_allow, _refresh, widget, custom_opts) = meta['execute_at_modification'](
                widget, request.form, presave, json.loads(postsave_json))
            postsave_json = json.dumps(custom_opts)
        except Exception as exc:
            logger.warning("preview execute_at_modification failed: %s", exc)

    saved_options = widget.custom_options
    try:
        widget.custom_options = postsave_json
        options_values = parse_custom_option_values_json(
            [widget], dict_controller=dict_widgets).get(widget.unique_id, {})
    finally:
        widget.custom_options = saved_options
        db.session.rollback()

    form_base = forms_dashboard.DashboardBase()
    form_dashboard = forms_dashboard.DashboardConfig()
    html, js_ready_end = _render_widget_fragments(
        this_dashboard, this_dashboard.unique_id, widget,
        options_values, dict_widgets, form_base, form_dashboard)
    return jsonify({'html': html, 'js_ready_end': js_ready_end})


@blueprint.route('/reload_flask/<dashboard_id>')
@flask_login.login_required
def restart_flask_auto_advance_page(dashboard_id=""):
    """Wait then automatically load next page"""
    logger.info("Reloading frontend in 10 seconds")
    reload_frontend(delay_sec=10, logger=logger)

    return render_template('pages/wait_and_autoload.html',
                           dashboard_id=dashboard_id)
