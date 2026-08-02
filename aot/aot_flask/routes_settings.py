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
from aot.databases.models import (APIKey, SMTP, Conversion, Input, Measurement, Misc,
                                     Output, Role, Unit, User)
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


@blueprint.route('/brand-image', methods=['GET'])
@flask_login.login_required
def brand_image():
    """Return brand image from database (JPEG/PNG/GIF/SVG/WebP auto-detected)"""
    misc = Misc.query.first()
    if misc.brand_image:
        # Detect image type from magic bytes (file signature)
        data = misc.brand_image
        if data[:3] == b'\xFF\xD8\xFF':  # JPEG
            mimetype = 'image/jpeg'
        elif data[:4] == b'\x89PNG':  # PNG
            mimetype = 'image/png'
        elif data[:4] == b'GIF8':  # GIF (GIF87a or GIF89a)
            mimetype = 'image/gif'
        elif data[:4] == b'<?xm' or data[:4] == b'<svg':  # SVG (XML or HTML tag)
            mimetype = 'image/svg+xml'
        elif data[:4] == b'RIFF' and len(data) > 12 and data[8:12] == b'WEBP':  # WebP
            mimetype = 'image/webp'
        else:
            # Default to JPEG for backward compatibility
            mimetype = 'image/jpeg'

        return send_file(
            BytesIO(data),
            mimetype=mimetype
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

        return redirect(url_for('routes_settings.settings_general'))

    return render_template('settings/general.html',
                           form_settings_general=form_settings_general,
                           report_path=os.path.normpath(USAGE_REPORTS_PATH))


@blueprint.route('/settings/chirpstack', methods=('GET', 'POST'))
@flask_login.login_required
def settings_chirpstack():
    """Browse ChirpStack devices and register them as AoT Inputs/Outputs."""
    import json as _json
    from flask_babel import gettext
    from aot.aot_flask.utils import utils_chirpstack

    messages = {"success": [], "info": [], "warning": [], "error": []}

    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_chirpstack = forms_settings.SettingsChirpStack()

    api_keys = APIKey.query.order_by(APIKey.name).all()
    form_chirpstack.chirpstack_api_token.choices = (
        [('', gettext('— None —'))] +
        [(k.unique_id, '{}{}'.format(
            k.name or k.unique_id,
            ' ({})'.format(k.provider) if k.provider else ''))
         for k in api_keys])

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            messages["error"].append("Your permissions do not allow this action")
        elif request.form.get('action') == 'onboard':
            euis = request.form.getlist('dev_euis')
            do_input = bool(request.form.get('reg_input'))
            do_output = bool(request.form.get('reg_output'))
            scheduler_id = request.form.get('scheduler_id') or None
            on_payload = request.form.get('on_payload') or None
            off_payload = request.form.get('off_payload') or None
            f_port = request.form.get('f_port') or None
            input_channels = request.form.get('input_channels') or None
            if not euis:
                messages["warning"].append(gettext("Select one or more devices to register."))
            elif not do_input and not do_output and not scheduler_id:
                messages["warning"].append(gettext("Select a registration target (Input/Output) or a scheduler."))
            else:
                n_in, n_out = 0, 0
                jmes = [ln.strip() for ln in (input_channels or '').splitlines() if ln.strip()]
                cs_server, cs_token, _mqtt_host, _mqtt_port = utils_chirpstack.get_chirpstack_conn()
                name_by_eui = {}
                if cs_server and cs_token:
                    cs_devices, _list_error = utils_chirpstack.list_chirpstack_devices(cs_server, cs_token)
                    name_by_eui = {d.get('dev_eui'): d.get('name') for d in cs_devices}
                for eui in euis:
                    dev_name = name_by_eui.get(eui)
                    if do_input:
                        msg, _ = utils_chirpstack.register_device_as_input(
                            eui, channel_jmespaths=jmes, name=dev_name)
                        messages['error'].extend(msg.get('error', []))
                        if not msg.get('error'):
                            n_in += 1
                    if do_output:
                        msg, _ = utils_chirpstack.register_device_as_output(
                            eui, on_payload=on_payload, off_payload=off_payload, f_port=f_port, name=dev_name)
                        messages['error'].extend(msg.get('error', []))
                        if not msg.get('error'):
                            n_out += 1
                messages["success"].append(gettext(
                    "Registration complete — Input %(i)s, Output %(o)s (%(n)s devices)",
                    i=n_in, o=n_out, n=len(euis)))
        elif form_chirpstack.refresh.data:
            pass
        else:
            messages = utils_settings.settings_chirpstack_mod(form_chirpstack)

        for each_error in messages["error"]:
            flash(each_error, "error")
        for each_warn in messages["warning"]:
            flash(each_warn, "warning")
        for each_info in messages["info"]:
            flash(each_info, "info")
        for each_success in messages["success"]:
            flash(each_success, "success")

        return redirect(url_for('routes_settings.settings_chirpstack'))

    # GET: populate connection form + load device list
    server, token, mqtt_host, mqtt_port = utils_chirpstack.get_chirpstack_conn()
    form_chirpstack.chirpstack_grpc_server.data = server
    form_chirpstack.chirpstack_mqtt_host.data = mqtt_host
    form_chirpstack.chirpstack_mqtt_port.data = mqtt_port
    form_chirpstack.chirpstack_api_token.data = next(
        (k.unique_id for k in api_keys if (k.key or '').strip() == (token or '').strip()), '')

    devices = []
    list_error = None
    if server and token:
        devices, list_error = utils_chirpstack.list_chirpstack_devices(server, token)
        devices.sort(key=lambda d: (
            (d.get('tenant_name') or '').lower(),
            (d.get('application_name') or '').lower(),
            (d.get('name') or '').lower(),
        ))

    tenant_names = sorted({d.get('tenant_name') for d in devices if d.get('tenant_name')})
    application_names = sorted({d.get('application_name') for d in devices if d.get('application_name')})

    reg_input, reg_output = set(), set()
    try:
        for inp in Input.query.filter_by(device=utils_chirpstack.INPUT_MODULE).all():
            try:
                eui = (_json.loads(inp.custom_options or '{}').get('device_euis') or '').strip().lower()
                if eui:
                    reg_input.add(eui)
            except Exception:
                pass
        for out in Output.query.filter_by(device=utils_chirpstack.OUTPUT_MODULE).all():
            try:
                eui = (_json.loads(out.custom_options or '{}').get('dev_eui') or '').strip().lower()
                if eui:
                    reg_output.add(eui)
            except Exception:
                pass
    except Exception:
        pass

    return render_template('settings/chirpstack.html',
                           form_chirpstack=form_chirpstack,
                           devices=devices,
                           tenant_names=tenant_names,
                           application_names=application_names,
                           list_error=list_error,
                           grpc_ok=utils_chirpstack.grpc_available(),
                           reg_input=reg_input,
                           reg_output=reg_output,
                           managed_by={},
                           sched_names={},
                           schedulers=[],
                           api_keys=api_keys)


@blueprint.route('/settings/custom_ui', methods=('GET', 'POST'))
@flask_login.login_required
def settings_custom_ui():
    """Display custom UI settings."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    misc = Misc.query.first()
    if request.method == 'GET':
        import json
        try:
            theme_dict = json.loads(misc.custom_theme_json or '{}')
        except Exception:
            theme_dict = {}
        # 2026-07 필드 통합 이전 저장값(bd_tertiary 등 구 필드명) 호환 — DB에
        # 쓰지 않는 조회 시점 변환이라, 다음 저장 전까지는 매 요청마다 계산된다.
        theme_dict = forms_settings.migrate_theme_dict(theme_dict)
        form_settings_custom_ui = forms_settings.SettingsCustomUI(formdata=None, **theme_dict)
    else:
        form_settings_custom_ui = forms_settings.SettingsCustomUI()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            messages["error"].append("Your permissions do not allow this action")

        if not messages["error"]:
            messages = utils_settings.settings_custom_ui_mod(form_settings_custom_ui)

        for each_error in messages["error"]:
            flash(each_error, "error")
        for each_warn in messages["warning"]:
            flash(each_warn, "warning")
        for each_info in messages["info"]:
            flash(each_info, "info")
        for each_success in messages["success"]:
            flash(each_success, "success")

    import json as _json
    try:
        user_presets = _json.loads(misc.custom_theme_presets or '{}')
    except Exception:
        user_presets = {}
    # 프리셋도 구 필드명으로 저장돼 있을 수 있어 표시 전 동일하게 변환한다
    # (실제 DB 갱신은 사용자가 "프리셋 저장"을 다시 누를 때 자연히 이뤄진다).
    user_presets = {
        name: forms_settings.migrate_theme_dict(dict(colors))
        for name, colors in user_presets.items()
    }

    return render_template('settings/custom_ui.html',
                           form_settings_custom_ui=form_settings_custom_ui,
                           theme_defaults=forms_settings.THEME_DEFAULTS,
                           user_presets=user_presets)


@blueprint.route('/settings/custom_ui/presets', methods=['GET', 'POST', 'DELETE'])
@flask_login.login_required
def settings_custom_ui_presets():
    """사용자 테마 색상 프리셋 저장/조회/삭제 (misc.custom_theme_presets JSON)."""
    import json
    import re
    from aot.aot_flask.extensions import db

    if not utils_general.user_has_permission('view_settings'):
        return jsonify(error="Your permissions do not allow this action"), 403

    misc = Misc.query.first()
    try:
        presets = json.loads(misc.custom_theme_presets or '{}')
        if not isinstance(presets, dict):
            presets = {}
    except Exception:
        presets = {}

    if request.method == 'GET':
        presets = {
            name: forms_settings.migrate_theme_dict(dict(colors))
            for name, colors in presets.items()
        }
        return jsonify(presets=presets)

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify(error="Your permissions do not allow this action"), 403

    payload = request.get_json(silent=True) or {}
    name = str(payload.get('name', '')).strip()
    if not name or len(name) > 40:
        return jsonify(error="Preset name must be 1-40 characters"), 400

    if request.method == 'POST':
        colors = payload.get('colors') or {}
        color_re = re.compile(r'^#[0-9a-fA-F]{6}$')
        cleaned = {}
        for field in forms_settings.THEME_COLOR_FIELDS:
            val = str(colors.get(field, '')).strip()
            if val:
                if not color_re.match(val):
                    return jsonify(error=f"Invalid color for {field}: {val}"), 400
                cleaned[field] = val.upper()
        if not cleaned:
            return jsonify(error="No colors to save"), 400
        if len(presets) >= 30 and name not in presets:
            return jsonify(error="Preset limit reached (30)"), 400
        presets[name] = cleaned
    else:  # DELETE
        if name not in presets:
            return jsonify(error="Preset not found"), 404
        del presets[name]

    misc.custom_theme_presets = json.dumps(presets, ensure_ascii=False)
    db.session.commit()
    return jsonify(presets=presets)


@blueprint.route('/settings/custom_ui/global_colors', methods=['POST'])
@flask_login.login_required
def settings_custom_ui_global_colors():
    """위젯 설정 화면에서 지정한 색을 전역 커스텀 색상으로 저장 (역방향).

    body: {"kind": "band"|"chart", "colors": ["#RRGGBB", ...]}
    band 은 band_1..5, chart 는 chart_1..6 필드에 순서대로 기록되어
    custom_theme_json 에 병합된다 (/custom.css·서버 팔레트 즉시 반영).
    """
    import json
    import re
    from aot.aot_flask.extensions import db

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify(error="Your permissions do not allow this action"), 403

    payload = request.get_json(silent=True) or {}
    kind = payload.get('kind')
    limits = {'band': 5, 'chart': 6}
    if kind not in limits:
        return jsonify(error="kind must be 'band' or 'chart'"), 400

    colors = payload.get('colors') or []
    color_re = re.compile(r'^#[0-9a-fA-F]{6}$')
    cleaned = []
    for c in colors[:limits[kind]]:
        c = str(c).strip()
        if not color_re.match(c):
            return jsonify(error=f"Invalid color: {c}"), 400
        cleaned.append(c.upper())
    if not cleaned:
        return jsonify(error="No colors to save"), 400

    misc = Misc.query.first()
    try:
        theme_dict = json.loads(misc.custom_theme_json or '{}')
        if not isinstance(theme_dict, dict):
            theme_dict = {}
    except Exception:
        theme_dict = {}

    saved = {}
    for i, c in enumerate(cleaned):
        key = f'{kind}_{i + 1}'
        theme_dict[key] = c
        saved[key] = c

    misc.custom_theme_json = json.dumps(theme_dict)
    db.session.commit()
    return jsonify(saved=saved)



@blueprint.route('/settings/function', methods=('GET', 'POST'))
@flask_login.login_required
def settings_function():
    """Display function settings."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_import = forms_settings.Controller()
    form_delete = forms_settings.ControllerDel()
    dict_controllers = parse_function_information(custom_only=True)

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
    dict_widgets = parse_widget_information(custom_only=True)

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
    dict_inputs = parse_input_information(custom_only=True)

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
    dict_outputs = parse_output_information(custom_only=True)

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
    dict_actions = parse_action_information(custom_only=True)

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
        elif form_mod_user.user_approve.data:
            user_id = form_mod_user.user_id.data
            messages = utils_settings.user_approve(form_mod_user)
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


def _save_card_order(table, payload):
    """Re-rank dragged cards to sequential ints and persist.

    Same shape as save_input_layout(routes_input.py): the browser reports the
    y each card landed on, which can tie (two cards nudged into one slot, or
    freshly created rows all sitting at 0). Sorting then re-ranking to 0..N-1
    is what makes ORDER BY position_y stable across reloads.
    """
    from aot.aot_flask.extensions import db

    items = [d for d in payload if 'id' in d and 'y' in d]
    items.sort(key=lambda d: (d['y'], d['id']))
    for rank, each_item in enumerate(items):
        row = table.query.filter(table.unique_id == each_item['id']).first()
        if row:
            row.position_y = rank
    db.session.commit()


@blueprint.route('/settings/users/save_order', methods=['POST'])
@flask_login.login_required
def settings_users_save_order():
    """Save the drag order of the user cards."""
    if not utils_general.user_has_permission('edit_users'):
        return '', 403
    _save_card_order(User, request.get_json())
    return "success"


@blueprint.route('/settings/users/save_role_order', methods=['POST'])
@flask_login.login_required
def settings_roles_save_order():
    """Save the drag order of the role cards."""
    if not utils_general.user_has_permission('edit_users'):
        return '', 403
    _save_card_order(Role, request.get_json())
    return "success"


@blueprint.route('/settings/users/detail/<string:unique_id>', methods=['GET'])
@flask_login.login_required
def settings_user_detail(unique_id):
    """Render one user's edit form for the Users-page drawer.

    Served on demand so the list page never carries every user's email,
    role and keys in its HTML.
    """
    if not utils_general.user_has_permission('view_settings'):
        return '', 403

    user = User.query.filter(User.unique_id == unique_id).first()
    if not user:
        return '', 404

    return render_template('settings/user_detail.html',
                           user=user,
                           themes=THEMES,
                           user_roles=Role.query.all(),
                           form_mod_user=forms_settings.UserMod())


@blueprint.route('/settings/users/role_detail/<string:unique_id>', methods=['GET'])
@flask_login.login_required
def settings_role_detail(unique_id):
    """Render one role's edit form for the Users-page drawer."""
    if not utils_general.user_has_permission('view_settings'):
        return '', 403

    each_role = Role.query.filter(Role.unique_id == unique_id).first()
    if not each_role:
        return '', 404

    return render_template('settings/role_detail.html',
                           each_role=each_role,
                           form_user_roles=forms_settings.UserRoles())


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

    # id 를 2차 키로 두는 이유: p6_18 직후에는 모든 행의 position_y 가 0 이라
    # 그것만으로는 순서가 매 조회마다 달라질 수 있다.
    users = User.query.order_by(User.position_y, User.id).all()
    user_roles = Role.query.order_by(Role.position_y, Role.id).all()

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

    # id 를 2차 키로: p6_20 직후에는 모든 행의 position_y 가 0 이라 그것만으로는
    # 순서가 매 조회마다 달라질 수 있다.
    api_keys = APIKey.query.order_by(APIKey.position_y, APIKey.id).all()
    form_add = forms_settings.APIKeyAdd()

    # 목록에는 "쓰이는 곳이 있는가"만 필요하다. 어디에 쓰이는지는 드로어를 열 때
    # 상세 라우트가 계산한다 — 키 하나당 Input/Output/Function/AI 를 전부 훑는
    # 조회라, 목록에서 전 키를 돌면 그만큼 비싸진다.
    usage_map = {
        key.unique_id: bool(utils_settings.get_api_key_usage(key.key))
        for key in api_keys}

    misc = Misc.query.first()

    return render_template('settings/api_key.html',
                           api_keys=api_keys,
                           usage_map=usage_map,
                           form_add=form_add,
                           misc=misc)


@blueprint.route('/settings/api_key/detail/<string:unique_id>', methods=['GET'])
@flask_login.login_required
def settings_api_key_detail(unique_id):
    """Render one key's edit form for the API-key page drawer.

    Served on demand so the list page never carries every stored credential in
    its HTML — the previous layout rendered `value="{{ key.key }}"` for every
    key, handing all of them to anyone who could open the page or view source.
    """
    if not utils_general.user_has_permission('view_settings'):
        return '', 403

    api_key = APIKey.query.filter(APIKey.unique_id == unique_id).first()
    if not api_key:
        return '', 404

    return render_template('settings/api_key_detail.html',
                           key=api_key,
                           usage=utils_settings.get_api_key_usage(api_key.key),
                           form_mod=forms_settings.APIKeyMod())


@blueprint.route('/settings/api_key/save_order', methods=['POST'])
@flask_login.login_required
def settings_api_key_save_order():
    """Save the drag order of the API-key cards."""
    if not utils_general.user_has_permission('edit_settings'):
        return '', 403
    _save_card_order(APIKey, request.get_json())
    return "success"


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
    if not utils_general.user_has_permission('view_settings', silent=True):
        return jsonify([]), 403

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


@blueprint.route('/api/api_key/<unique_id>', methods=['GET'])
@flask_login.login_required
def api_key_resolve(unique_id):
    """Resolve a single stored API key's value on demand for picker UIs.

    Fetched one key at a time (only the key the user actually selects),
    instead of the page embedding every stored key's plaintext up front.

    Gated on edit permission to match the picker's own gate in
    routes_static.inject_variables — a read-only role never needs a
    credential's plaintext.
    """
    if not (utils_general.user_has_permission('edit_settings', silent=True)
            or utils_general.user_has_permission('edit_controllers', silent=True)):
        return jsonify({"status": "error", "message": "Permission denied"}), 403

    key_obj = APIKey.query.filter_by(unique_id=unique_id).first()
    if not key_obj:
        return jsonify({"status": "error", "message": "Not found"}), 404

    return jsonify({"status": "success", "key": key_obj.key})


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


@blueprint.route('/settings/account_self', methods=('POST',))
@flask_login.login_required
def settings_account_self():
    """Self-service account editing (nav-bar 'User Settings' modal) — the
    logged-in user changing their own name/email/password/language. No
    edit_users permission required: scope is inherently limited to the
    caller's own row (see utils_settings.account_self_update)."""
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))

    form_account = forms_settings.AccountSelf()
    logout = False
    if form_account.validate_on_submit() and form_account.user_account_save.data:
        logout = utils_settings.account_self_update(form_account)
    else:
        utils_general.flash_form_errors(form_account)

    if logout:
        return redirect(url_for('routes_authentication.logout'))
    return redirect(request.referrer or url_for('routes_general.home'))
