# coding=utf-8
"""collection of Page endpoints."""
import logging
import os
import flask_login
import threading
from io import BytesIO
from flask import flash, jsonify, send_file, redirect, render_template, request, url_for
from flask.blueprints import Blueprint

from aot.config import (PATH_ACTIONS_CUSTOM, PATH_FUNCTIONS_CUSTOM,
                           PATH_INPUTS_CUSTOM, PATH_OUTPUTS_CUSTOM,
                           PATH_WIDGETS_CUSTOM, THEMES, USAGE_REPORTS_PATH)
from aot.databases.models import (APIKey, SMTP, Conversion, Measurement, Misc, Role,
                                     Unit, User)
from aot.aot_flask.forms import forms_settings
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general, utils_settings
from aot.utils.modules import load_module_from_file
from aot.utils.functions import parse_function_information
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information
from aot.utils.widgets import parse_widget_information
from aot.utils.actions import parse_action_information
from aot.utils.system_pi import (add_custom_measurements, add_custom_units,
                                    base64_encode_bytes, cmd_output)

logger = logging.getLogger('aot.aot_flask.settings')

blueprint = Blueprint('routes_settings',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.context_processor
@flask_login.login_required
def api_key_tools():
    return dict(base64_encode_bytes=base64_encode_bytes)


@blueprint.route('/settings/alerts', methods=('GET', 'POST'))
@flask_login.login_required
def settings_alerts():
    """Display alert settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    smtp = SMTP.query.first()
    form_email_alert = forms_settings.SettingsEmail()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        form_name = request.form['form-name']
        if form_name == 'EmailAlert':
            utils_settings.settings_alert_mod(form_email_alert)
        return redirect(url_for('routes_settings.settings_alerts'))

    return render_template('settings/alerts.html',
                           smtp=smtp,
                           form_email_alert=form_email_alert)


@blueprint.route('/logo.jpg', methods=['GET'])
@flask_login.login_required
def brand_logo():
    """Return logo from database"""
    misc = Misc.query.first()
    if misc.brand_image:
        return send_file(
            BytesIO(misc.brand_image),
            mimetype='image/jpg'
        )


@blueprint.route('/settings/general', methods=('GET', 'POST'))
@flask_login.login_required
def settings_general():
    """Display general settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_settings_general = forms_settings.SettingsGeneral()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            messages["error"].append("Your permissions do not allow this action")

        if not messages["error"]:
            messages = utils_settings.settings_general_mod(form_settings_general)

        for each_error in messages["error"]:
            flash(each_error, "error")
        for each_warn in messages["warning"]:
            flash(each_warn, "warning")
        for each_info in messages["info"]:
            flash(each_info, "info")
        for each_success in messages["success"]:
            flash(each_success, "success")

    return render_template('settings/general.html',
                           form_settings_general=form_settings_general,
                           report_path=os.path.normpath(USAGE_REPORTS_PATH))


@blueprint.route('/settings/function', methods=('GET', 'POST'))
@flask_login.login_required
def settings_function():
    """Display function settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Controller()
    form_delete = forms_settings.ControllerDel()
    dict_controllers = parse_function_information()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_import.import_function_upload.data:
            utils_settings.function_import(form_import)
        if form_delete.delete_function.data:
            utils_settings.function_del(form_delete)
        return redirect(url_for('routes_settings.settings_function'))

    return render_template('settings/function.html',
                           form_controller=form_import,
                           form_controller_delete=form_delete,
                           dict_controllers=dict_controllers)


@blueprint.route('/settings/widget', methods=('GET', 'POST'))
@flask_login.login_required
def settings_widget():
    """Display widget settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Widget()
    form_delete = forms_settings.WidgetDel()
    dict_widgets = parse_widget_information()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_import.import_widget_upload.data:
            utils_settings.settings_widget_import(form_import)
        if form_delete.delete_widget.data:
            utils_settings.settings_widget_delete(form_delete)
        return redirect(url_for('routes_settings.settings_widget'))

    return render_template('settings/widget.html',
                           form_widget=form_import,
                           form_widget_delete=form_delete,
                           dict_widgets=dict_widgets)


@blueprint.route('/settings/input', methods=('GET', 'POST'))
@flask_login.login_required
def settings_input():
    """Display input settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Input()
    form_delete = forms_settings.InputDel()
    dict_inputs = parse_input_information()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_import.import_input_upload.data:
            utils_settings.input_import(form_import)
        if form_delete.delete_input.data:
            utils_settings.input_del(form_delete)
        return redirect(url_for('routes_settings.settings_input'))

    return render_template('settings/input.html',
                           form_input=form_import,
                           form_input_delete=form_delete,
                           dict_inputs=dict_inputs)


@blueprint.route('/settings/output', methods=('GET', 'POST'))
@flask_login.login_required
def settings_output():
    """Display output settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Output()
    form_delete = forms_settings.OutputDel()
    dict_outputs = parse_output_information()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_import.import_output_upload.data:
            utils_settings.output_import(form_import)
        if form_delete.delete_output.data:
            utils_settings.output_del(form_delete)
        return redirect(url_for('routes_settings.settings_output'))

    return render_template('settings/output.html',
                           form_output=form_import,
                           form_output_delete=form_delete,
                           dict_outputs=dict_outputs)


@blueprint.route('/settings/action', methods=('GET', 'POST'))
@flask_login.login_required
def settings_action():
    """Display action settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Action()
    form_delete = forms_settings.ActionDel()
    dict_actions = parse_action_information()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_import.import_action_upload.data:
            utils_settings.action_import(form_import)
        if form_delete.delete_action.data:
            utils_settings.action_del(form_delete)
        return redirect(url_for('routes_settings.settings_action'))

    return render_template('settings/action.html',
                           form_action=form_import,
                           form_action_delete=form_delete,
                           dict_actions=dict_actions)


@blueprint.route('/settings/measurement', methods=('GET', 'POST'))
@flask_login.login_required
def settings_measurement():
    """Display measurement settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    measurement = Measurement.query.all()
    unit = Unit.query.all()
    conversion = Conversion.query.all()
    form_add = forms_settings.MeasurementAdd()
    form_mod = forms_settings.MeasurementMod()
    form_add_unit = forms_settings.UnitAdd()
    form_mod_unit = forms_settings.UnitMod()
    form_add_conversion = forms_settings.ConversionAdd()
    form_mod_conversion = forms_settings.ConversionMod()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_add.validate_on_submit():
            utils_settings.settings_measurement_add(form_add)
        if form_add_unit.add_unit.data:
            utils_settings.settings_unit_add(form_add_unit)
        if form_mod_unit.delete_unit.data or form_mod_unit.save_unit.data:
            utils_settings.settings_unit_mod(form_mod_unit, request.form)
        if form_add_conversion.add_conversion.data:
            utils_settings.settings_conversion_add(form_add_conversion)
        if form_mod_conversion.delete_conversion.data or form_mod_conversion.save_conversion.data:
            utils_settings.settings_conversion_mod(form_mod_conversion, request.form)
        return redirect(url_for('routes_settings.settings_measurement'))

    choices_units = utils_settings.choices_units(unit)
    choices_measurements = utils_settings.choices_measurements(measurement)
    choices_conversions = utils_settings.choices_conversions(conversion, unit)
    dict_measurements = add_custom_measurements(measurement)
    dict_units = add_custom_units(unit)

    return render_template('settings/measurement.html',
                           dict_measurements=dict_measurements,
                           dict_units=dict_units,
                           measurement=measurement,
                           unit=unit,
                           conversion=conversion,
                           form_add_measurement=form_add,
                           form_mod_measurement=form_mod,
                           form_add_unit=form_add_unit,
                           form_mod_unit=form_mod_unit,
                           form_add_conversion=form_add_conversion,
                           form_mod_conversion=form_mod_conversion,
                           choices_units=choices_units,
                           choices_measurements=choices_measurements,
                           choices_conversions=choices_conversions,
                           form_mod_measurement_data=[],
                           form_del_measurement=form_mod)


@blueprint.route('/settings/users_submit', methods=['POST'])
@flask_login.login_required
def settings_users_submit():
    """Submit form for User Settings page"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    page_refresh = False
    logout = False
    user_id = None
    role_id = None
    generated_api_key = None

    if not utils_general.user_has_permission('edit_users'):
        messages["error"].append("Your permissions do not allow this action")

    form_user = forms_settings.User()
    form_mod_user = forms_settings.UserMod()
    form_user_roles = forms_settings.UserRoles()

    if not messages["error"]:
        if form_user.settings_user_save.data:
            messages = utils_settings.user(form_user)
        elif form_mod_user.user_generate_api_key.data:
            (messages,
             generated_api_key) = utils_settings.generate_api_key(
                form_mod_user)
            user_id = form_mod_user.user_id.data
        elif form_mod_user.user_delete.data:
            user_id = form_mod_user.user_id.data
            messages = utils_settings.user_del(form_mod_user)
        elif form_mod_user.user_save.data:
            messages, logout = utils_settings.user_mod(form_mod_user)
            if logout:
                page_refresh = True
        elif (form_user_roles.user_role_save.data or
              form_user_roles.user_role_delete.data):
            role_id = form_user_roles.role_id.data
            messages, page_refresh = utils_settings.user_roles(form_user_roles)

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
        'generated_api_key': generated_api_key,
        'user_id': user_id,
        'role_id': role_id,
        'messages': messages,
        'logout': logout
    })


@blueprint.route('/settings/users', methods=('GET', 'POST'))
@flask_login.login_required
def settings_users():
    """Display user settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    misc = Misc.query.first()
    form_user = forms_settings.User()
    form_add_user = forms_settings.UserAdd()
    form_mod_user = forms_settings.UserMod()
    form_user_roles = forms_settings.UserRoles()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_users'):
            return redirect(url_for('routes_general.home'))

        if form_add_user.user_add.data:
            utils_settings.user_add(form_add_user)
        elif form_user_roles.user_role_add.data:
            messages, page_refresh = utils_settings.user_roles(form_user_roles)

    for each_error in messages["error"]:
        flash(each_error, "error")
    for each_warn in messages["warning"]:
        flash(each_warn, "warning")
    for each_info in messages["info"]:
        flash(each_info, "info")
    for each_success in messages["success"]:
        flash(each_success, "success")

    users = User.query.all()
    user_roles = Role.query.all()

    return render_template('settings/users.html',
                           misc=misc,
                           themes=THEMES,
                           users=users,
                           user_roles=user_roles,
                           form_add_user=form_add_user,
                           form_mod_user=form_mod_user,
                           form_user=form_user,
                           form_user_roles=form_user_roles)


@blueprint.route('/settings/pi', methods=('GET', 'POST'))
@flask_login.login_required
def settings_pi():
    """Display Raspberry Pi settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    # Form class name in forms_settings is SettingsPi (not SettingsRaspPi)
    form_settings_misc = forms_settings.SettingsPi()

    cmd = "pigs"
    _, _, status = cmd_output(cmd)
    pi_gpio_daemon_running = (status == 0)

    # Collect current Pi config/settings for the template
    try:
        from aot.utils.system_pi import get_raspi_config_settings
        pi_settings = get_raspi_config_settings()
    except Exception:
        pi_settings = {}

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        form_name = request.form['form-name']
        if form_name == "PiSettings":
            messages = utils_settings.settings_pi_mod(form_settings_misc)
        if form_name == "InitPigpiod":
            cmd = "echo \" $(</proc/sys/kernel/hostname): " \
                  "$(sudo systemctl start pigpiod && echo OK)\""
            cmd_output(cmd)
        if form_name == "FinalPigpiod":
            cmd = "echo \" $(</proc/sys/kernel/hostname): " \
                  "$(sudo systemctl stop pigpiod && echo OK)\""
            cmd_output(cmd)
        if form_name == "RestartPigpiod":
            cmd = "echo \" $(</proc/sys/kernel/hostname): " \
                  "$(sudo systemctl restart pigpiod && echo OK)\""
            cmd_output(cmd)

        for each_error in messages["error"]:
            flash(each_error, "error")
        for each_warn in messages["warning"]:
            flash(each_warn, "warning")
        for each_info in messages["info"]:
            flash(each_info, "info")
        for each_success in messages["success"]:
            flash(each_success, "success")

        return redirect(url_for('routes_settings.settings_pi'))

    return render_template('settings/pi.html',
                           form_settings_pi=form_settings_misc,
                           sudo=utils_general.sudo_present(),
                           pi_settings=pi_settings,
                           pi_gpio_daemon_running=pi_gpio_daemon_running)


@blueprint.route('/settings/diagnostic', methods=('GET', 'POST'))
@flask_login.login_required
def settings_diagnostic():
    """Display diagnostic settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_settings_general = forms_settings.SettingsDiagnostic()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return redirect(url_for('routes_general.home'))

        if form_settings_general.validate_on_submit():
            utils_settings.settings_diagnostic_mod(form_settings_general)
        else:
            utils_general.flash_form_errors(form_settings_general)
        return redirect(url_for('routes_settings.settings_diagnostic'))

    return render_template('settings/diagnostic.html',
                           form_settings_diagnostic=form_settings_general)


@blueprint.route('/settings/api_key', methods=('GET', 'POST'))
@flask_login.login_required
def settings_api_key():
    """Display API Key management settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    api_keys = APIKey.query.all()
    form_add = forms_settings.APIKeyAdd()
    form_mod = forms_settings.APIKeyMod()

    # Pre-calculate usage for each key
    usage_map = {}
    for key in api_keys:
        usage_map[key.unique_id] = utils_settings.get_api_key_usage(key.key)

    misc = Misc.query.first()

    return render_template('settings/api_key.html',
                           api_keys=api_keys,
                           usage_map=usage_map,
                           form_add=form_add,
                           form_mod=form_mod,
                           misc=misc)


@blueprint.route('/settings/api_key_submit', methods=['POST'])
@flask_login.login_required
def settings_api_key_submit():
    """Submit form for API Key management page"""
    messages = {
        "success": [], "info": [], "warning": [], "error": []
    }
    key_id = None

    if not utils_general.user_has_permission('edit_settings'):
        messages["error"].append("Your permissions do not allow this action")

    form_add = forms_settings.APIKeyAdd()
    form_mod = forms_settings.APIKeyMod()

    if not messages["error"]:
        if form_add.api_key_add_submit.data:
            messages = utils_settings.api_key_add(form_add)
        elif form_mod.api_key_mod_submit.data:
            messages = utils_settings.api_key_mod(form_mod)
            key_id = form_mod.api_key_id.data
        elif form_mod.api_key_delete.data:
            key_id = form_mod.api_key_id.data
            messages = utils_settings.api_key_del(form_mod)

    return jsonify(data={
        'key_id': key_id,
        'messages': messages
    })


@blueprint.route('/api/api_keys', methods=['GET'])
@flask_login.login_required
def api_keys_list():
    """Return all API keys as JSON for intelligent matching."""
    api_keys = APIKey.query.all()
    keys_list = []
    for key in api_keys:
        keys_list.append({
            'unique_id': key.unique_id,
            'name': key.name,
            'provider': key.provider,
            'key': key.key,
            'tag': key.tag,
            'description': key.description
        })
    return jsonify(keys_list)


@blueprint.route('/change_preferences', methods=('POST',))
@flask_login.login_required
def change_preferences():
    """Handle user preference changes (theme/language)."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_prefs = forms_settings.UserPreferences()
    if form_prefs.validate_on_submit() and form_prefs.user_preferences_save.data:
        utils_settings.change_preferences(form_prefs)

    # Redirect back to the page that opened the modal, or home
    return redirect(request.referrer or url_for('routes_general.home'))
