# -*- coding: utf-8 -*-
import json
import logging
import subprocess

import sqlalchemy
from flask import current_app, flash, url_for
from flask_babel import gettext
_ = gettext

from aot.config import INSTALL_DIRECTORY
from aot.config_translations import TRANSLATIONS
from aot.databases import clone_model, set_uuid
from aot.databases.models import (PID, Conversion, CustomController,
                                        Dashboard, DeviceMeasurements, Input,
                                        Output, Widget)
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import (
    custom_options_return_json, delete_entry_with_id, flash_success_errors,
    return_dependencies, use_unit_generate)
from aot.utils.widgets import parse_widget_information
from aot.utils.widget_generate_html import generate_widget_html

logger = logging.getLogger(__name__)

#
# Dashboard
#

def dashboard_add():
    """Add a dashboard."""
    error = []

    last_dashboard = Dashboard.query.order_by(
        Dashboard.id.desc()).first()

    new_dash = Dashboard()
    new_dash.name = f"{TRANSLATIONS['dashboard']['title']} {last_dashboard.id + 1}"
    try:
        # Put new dashboard at the end by default
        new_dash.sort_order = last_dashboard.id + 1
    except Exception:
        pass

    if not error:
        new_dash.save()

        flash(gettext("Dashboard with ID %(id)s has been successfully added.", id=new_dash.id), "success")

    return new_dash.unique_id


def dashboard_mod(form):
    """Modify a dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []
    # 그룹 스코프(A1b) — 대시보드는 자기 자신이 부여 단위다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form.dashboard_id.data):
        error.append(scope.deny_message())
        return

    dash_mod = Dashboard.query.filter(
        Dashboard.unique_id == form.dashboard_id.data).first()

    name_exists = Dashboard.query.filter(
        Dashboard.name == form.name.data).first()
    if dash_mod.name != form.name.data and name_exists:
        error.append(gettext("Dashboard name is already in use."))
    else:
        dash_mod.name = form.name.data

    if not error:
        db.session.commit()

    # 그룹 부여는 대시보드 이름과 **같은 [저장]** 으로 함께 반영된다.
    #
    # ⚠ **"보내지 않음" 과 "전부 해제" 를 구분해야 한다.** 폼이 그 섹션을
    # 그리지 않았을 때(비관리자·로딩 실패) 빈 목록을 전량 교체로 넘기면
    # 대시보드 이름만 고쳐도 부여가 통째로 지워진다 — 그룹 저장 핸들러에서
    # 이미 한 번 겪은 실패다. 그래서 표식 필드를 본다.
    if not error:
        error.extend(_apply_dashboard_groups(form.dashboard_id.data) or [])

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def _apply_dashboard_groups(dashboard_id):
    """폼이 그룹 섹션을 실어 보냈을 때만 부여를 반영한다. (오류 목록)"""
    from flask import request

    from aot.aot_flask.routes_access import save_grants
    from aot.aot_flask.utils.utils_general import user_has_permission

    if not request.form.get('dashboard_groups_present'):
        return []                        # 섹션이 없었다 — 건드리지 않는다
    if not user_has_permission('edit_users', silent=True):
        # 표식만 흉내내 보내도 통과하면 안 된다 — 부여는 사용자 관리 권한이다.
        logger.warning("[scope] 대시보드 그룹 부여 거부(권한 없음): %s",
                       dashboard_id)
        return []
    failed = save_grants('dashboard', dashboard_id,
                         request.form.getlist('dashboard_groups'))
    return [failed] if failed else []


def dashboard_lock(dashboard_id, lock):
    """Lock a dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['lock']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    # 그룹 스코프(A1b) — 잠금은 그 대시보드를 쓰는 모두의 화면을 바꾼다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', dashboard_id):
        error.append(scope.deny_message())
        flash_success_errors(error, action, url_for(
            'routes_dashboard.page_dashboard', dashboard_id=dashboard_id))
        return

    try:
        dash_mod = Dashboard.query.filter(
            Dashboard.unique_id == dashboard_id).first()

        dash_mod.locked = lock

        if not error:
            db.session.commit()

    except Exception as msg:
        error.append(msg)
        logger.exception("Exception occurred while locking dashboard")

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def dashboard_copy(form):
    """Duplicate dashboard and widgets."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['duplicate']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    # 그룹 스코프(A1b) — **원본**으로 판정한다. 복제본은 부여가 없는 새
    # 대시보드(=전원 공개)가 되므로, 원본을 조작할 수 없는 사람이 복제하면
    # 복제 한 번으로 그 화면이 전원에게 열린다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form.dashboard_id.data):
        error.append(scope.deny_message())
        return

    try:
        # Get current dashboard and its widgets.
        dashboard = Dashboard.query.filter(
            Dashboard.unique_id == form.dashboard_id.data).first()
        widgets = Widget.query.filter(
            Widget.tab_id == dashboard.unique_id).all()

        # Clone dashboard with new unique ID and name.
        new_dashboard = clone_model(
            dashboard, unique_id=set_uuid(), name=gettext("New Dashboard"))

        # Clone all widgets and assign them to the new dashboard.
        for each_widget in widgets:
            clone_model(each_widget, unique_id=set_uuid(), tab_id=new_dashboard.unique_id)
    except Exception as msg:
        error.append(msg)
        logger.exception("Exception occurred while duplicating dashboard")

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def dashboard_del(form):
    """Delete a dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    # 그룹 스코프(A1b) — 부수 효과보다 먼저 막는다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form.dashboard_id.data):
        error.append(scope.deny_message())
        return
    create_new_dash = False

    dashboards = Dashboard.query.all()
    if len(dashboards) == 1:
        create_new_dash = True

    widgets = Widget.query.filter(
        Widget.tab_id == form.dashboard_id.data).all()
    for each_widget in widgets:
        delete_entry_with_id(Widget, each_widget.unique_id)

    delete_entry_with_id(Dashboard, form.dashboard_id.data)

    if create_new_dash:
        new_dash = Dashboard()
        new_dash.name = gettext("New Dashboard")
        new_dash.save()

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


#
# Widget
#

def widget_add(form_base, request_form):
    """Add a widget to the dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []
    # 그룹 스코프(A1b) — 위젯은 자기가 놓인 대시보드로 판정한다.
    #
    # 호출부가 `unmet_dependencies, reload_flask` 로 언패킹하므로 빈 return 을
    # 두면 언패킹에서 죽는다 — 거부가 예외로 나타나면 사용자는 "권한 없음" 이
    # 아니라 "고장" 을 본다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form_base.dashboard_id.data):
        error.append(scope.deny_message())
        flash_success_errors(error, action, url_for(
            'routes_dashboard.page_dashboard',
            dashboard_id=form_base.dashboard_id.data))
        return None, False

    reload_flask = False

    dict_widgets = parse_widget_information()

    if form_base.widget_type.data:
        widget_name = form_base.widget_type.data
    else:
        widget_name = ''
        error.append(gettext("Widget name is missing."))

    if current_app.config['TESTING']:
        dep_unmet = False
    else:
        dep_unmet, _unused, _unmet = return_dependencies(widget_name)
        if dep_unmet:
            list_unmet_deps = []
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
            error.append(gettext("Dependencies not met for %(dev)s: %(dep)s", dev=widget_name, dep=', '.join(list_unmet_deps)))

    new_widget = Widget()
    new_widget.tab_id = form_base.dashboard_id.data
    new_widget.graph_type = widget_name
    new_widget.name = form_base.name.data
    new_widget.font_em_name = form_base.font_em_name.data
    new_widget.enable_drag_handle = form_base.enable_drag_handle.data
    new_widget.refresh_duration = form_base.refresh_duration.data

    # Determine the starting position of the new widget.
    position_y_start = 0
    for each_widget in Widget.query.filter(
            Widget.tab_id == form_base.dashboard_id.data).all():
        highest_position = each_widget.position_y + each_widget.height
        if highest_position > position_y_start:
            position_y_start = highest_position
    new_widget.position_y = position_y_start

    # Set widget options
    if widget_name in dict_widgets:
        def dict_has_value(key):
            if (key in dict_widgets[widget_name] and
                    (dict_widgets[widget_name][key] or dict_widgets[widget_name][key] == 0)):
                return True

        if dict_has_value('widget_width'):
            new_widget.width = dict_widgets[widget_name]['widget_width']
        if dict_has_value('widget_height'):
            new_widget.height = dict_widgets[widget_name]['widget_height']

    # Generate custom options as a JSON string.
    error, custom_options = custom_options_return_json(
        error, dict_widgets, request_form, device=widget_name, use_defaults=True)
    new_widget.custom_options = custom_options

    #
    # 생성 시 실행
    #

    if ('execute_at_creation' in dict_widgets[widget_name] and
            not current_app.config['TESTING']):
        error, new_widget = dict_widgets[widget_name]['execute_at_creation'](
            error, new_widget, dict_widgets[widget_name])

    try:
        if not error:
            new_widget.save()

            # If this widget is added for the first time, restart Flask.
            if Widget.query.filter(Widget.graph_type == widget_name).count() == 1:
                reload_flask = True

            # Ensure latest HTML template when added to dashboard even if widget module already exists.
            try:
                generate_widget_html()
            except Exception as exc:
                logger.warning("Failed to regenerate widget HTML: %s", exc)

            if not current_app.config['TESTING']:
                # Refresh widget settings
                control = DaemonControl()
                control.widget_add_refresh(new_widget.unique_id)

            flash(gettext("%(dev)s (ID %(id)s) has been successfully added.", dev=dict_widgets[form_base.widget_type.data]['widget_name'], id=new_widget.id), "success")
    except sqlalchemy.exc.OperationalError as except_msg:
        error.append(except_msg)
    except sqlalchemy.exc.IntegrityError as except_msg:
        error.append(except_msg)

    for each_error in error:
        flash(each_error, "error")

    return dep_unmet, reload_flask


def widget_mod(form_base, request_form):
    """Modify settings of a dashboard item."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []
    # 그룹 스코프(A1b) — 위젯은 자기가 놓인 대시보드로 판정한다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form_base.dashboard_id.data):
        error.append(scope.deny_message())
        return

    dict_widgets = parse_widget_information()

    mod_widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()
    mod_widget.name = form_base.name.data
    mod_widget.font_em_name = form_base.font_em_name.data
    mod_widget.enable_drag_handle = form_base.enable_drag_handle.data
    mod_widget.refresh_duration = form_base.refresh_duration.data

    # Move widget to another dashboard (tab) if a valid tab_id was submitted.
    new_tab_id = request_form.get('tab_id')
    if new_tab_id and new_tab_id != mod_widget.tab_id:
        if Dashboard.query.filter(Dashboard.unique_id == new_tab_id).first():
            mod_widget.tab_id = new_tab_id

    try:
        custom_options_json_presave = json.loads(mod_widget.custom_options)
    except:
        logger.error("Malformed JSON")
        custom_options_json_presave = {}

    # Generate custom options as a JSON string.
    # Pass presave so null_value logic preserves existing values (e.g. device_selection_*)
    # when those fields are absent from the form (multi-select with no selection omits the field).
    error, custom_options_json_postsave = custom_options_return_json(
        error, dict_widgets, request_form, mod_dev=mod_widget, device=mod_widget.graph_type,
        custom_options=custom_options_json_presave)

    if 'execute_at_modification' in dict_widgets[mod_widget.graph_type]:
        (allow_saving,
         page_refresh,
         mod_widget,
         custom_options) = dict_widgets[mod_widget.graph_type]['execute_at_modification'](
            mod_widget, request_form, custom_options_json_presave, json.loads(custom_options_json_postsave))
        custom_options = json.dumps(custom_options)  # Convert dictionary to JSON string
        if not allow_saving:
            error.append(gettext("execute_at_modification() does not allow saving widget options."))
    else:
        custom_options = custom_options_json_postsave

    mod_widget.custom_options = custom_options

    if not error:
        try:
            db.session.commit()
        except sqlalchemy.exc.OperationalError as except_msg:
            error.append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            error.append(except_msg)

        control = DaemonControl()
        control.widget_add_refresh(mod_widget.unique_id)

    flash_success_errors(error, action, url_for(
        'routes_dashboard.page_dashboard',
        dashboard_id=form_base.dashboard_id.data))


def widget_del(form_base):
    """Delete a widget from the dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    # 그룹 스코프(A1b) — 부수 효과보다 먼저 막는다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form_base.dashboard_id.data):
        error.append(scope.deny_message())
        return

    dict_widgets = parse_widget_information()
    widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()

    try:
        if 'execute_at_deletion' in dict_widgets[widget.graph_type]:
            dict_widgets[widget.graph_type]['execute_at_deletion'](form_base.widget_id.data)
    except Exception as except_msg:
        error.append(except_msg)

    try:
        delete_entry_with_id(Widget, form_base.widget_id.data)

        control = DaemonControl()
        control.widget_remove(form_base.widget_id.data)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard',
                               dashboard_id=form_base.dashboard_id.data))


# 복제 위젯 함수 추가
def widget_duplicate(form_base):
    """Duplicate a widget from the dashboard."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['duplicate']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    # 그룹 스코프(A1b) — 위젯은 자기가 놓인 대시보드로 판정한다.
    from aot.aot_flask.access import scope
    if not scope.can_operate('dashboard', form_base.dashboard_id.data):
        error.append(scope.deny_message())
        return

    dict_widgets = parse_widget_information()
    orig_widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()

    if not orig_widget:
        error.append(gettext("Original widget not found."))
        flash_success_errors(
            error, action, url_for('routes_dashboard.page_dashboard',
                                   dashboard_id=form_base.dashboard_id.data))
        return

    try:
        # New position: Bottom of current dashboard (max y)
        position_y_start = 0
        for each_widget in Widget.query.filter(
                Widget.tab_id == orig_widget.tab_id).all():
            highest_position = each_widget.position_y + each_widget.height
            if highest_position > position_y_start:
                position_y_start = highest_position

        # Clone body
        new_widget = clone_model(
            orig_widget,
            unique_id=set_uuid(),
            name=f"{orig_widget.name} (copy)",
            position_y=position_y_start,
        )

        # Defensive initialization: can turn off auto-refresh/execution prevention options if needed.
        # (현재는 원본과 동일 옵션 사용)

        # Save
        new_widget.save()

        # Notify frontend of refresh
        control = DaemonControl()
        control.widget_add_refresh(new_widget.unique_id)

        flash(gettext("Duplicated %(dev)s widget (ID %(id)s).", dev=dict_widgets[orig_widget.graph_type]['widget_name'], id=new_widget.id), "success")

    except sqlalchemy.exc.OperationalError as except_msg:
        error.append(except_msg)
    except sqlalchemy.exc.IntegrityError as except_msg:
        error.append(except_msg)
    except Exception as except_msg:
        error.append(except_msg)

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard',
                               dashboard_id=form_base.dashboard_id.data))


def graph_y_axes_async(dict_measurements, ids_measures):
    """Determine the y-axis to use for each graph."""
    if not ids_measures:
        return

    y_axes = []

    function = CustomController.query.all()
    device_measurements = DeviceMeasurements.query.all()
    input_dev = Input.query.all()
    output = Output.query.all()
    pid = PID.query.all()

    devices_list = [input_dev, output, pid]

    # Iterate through each device table.
    for each_device in devices_list:

        # Iterate through each ID and measurement set of the dashboard elements.
        for each_id_measure in ids_measures:

            if ',' in each_id_measure:
                measure_id = each_id_measure.split(',')[1]
                measurement = DeviceMeasurements.query.filter(
                    DeviceMeasurements.unique_id == measure_id).first()

                if not measurement:
                    pass
                elif measurement.conversion_id:
                    conversion = Conversion.query.filter(
                        Conversion.unique_id == measurement.conversion_id).first()
                    if not conversion:
                        pass
                    elif not y_axes:
                        y_axes = [conversion.convert_unit_to]
                    elif y_axes and conversion.convert_unit_to not in y_axes:
                        y_axes.append(conversion.convert_unit_to)
                elif (measurement.rescaled_measurement and
                      measurement.rescaled_unit):
                    if not y_axes:
                        y_axes = [measurement.rescaled_unit]
                    elif y_axes and measurement.rescaled_unit not in y_axes:
                        y_axes.append(measurement.rescaled_unit)
                else:
                    if not y_axes:
                        y_axes = [measurement.unit]
                    elif y_axes and measurement.unit not in y_axes:
                        y_axes.append(measurement.unit)

            if len(each_id_measure.split(',')) > 1 and each_id_measure.split(',')[1].startswith('channel_'):
                unit = each_id_measure.split(',')[1].split('_')[4]

                if not y_axes:
                    y_axes = [unit]
                elif y_axes and unit not in y_axes:
                    y_axes.append(unit)

            else:
                if len(each_id_measure.split(',')) == 2:
                    unique_id = each_id_measure.split(',')[0]
                    measurement = each_id_measure.split(',')[1]

                    # Iterate through each device entry.
                    for each_device_entry in each_device:

                        # If the ID stored in the dashboard element matches the ID of the table entry
                        if each_device_entry.unique_id == unique_id:
                            y_axes = check_func(each_device,
                                                unique_id,
                                                y_axes,
                                                measurement,
                                                dict_measurements,
                                                device_measurements,
                                                input_dev,
                                                output,
                                                function)

                elif len(each_id_measure.split(',')) == 3:
                    unique_id = each_id_measure.split(',')[0]
                    measurement = each_id_measure.split(',')[1]
                    unit = each_id_measure.split(',')[2]

                    # Iterate through each device entry.
                    for each_device_entry in each_device:

                        # If the ID stored in the dashboard element matches the ID of the table entry
                        if each_device_entry.unique_id == unique_id:
                            y_axes = check_func(each_device,
                                                unique_id,
                                                y_axes,
                                                measurement,
                                                dict_measurements,
                                                device_measurements,
                                                input_dev,
                                                output,
                                                function,
                                                unit=unit)

    return y_axes


def check_func(all_devices,
               unique_id,
               y_axes,
               measurement,
               dict_measurements,
               device_measurements,
               input_dev,
               output,
               function,
               unit=None):
    """
    Generate a list of y-axes.
    :param all_devices: Input, Output, and PID SQL entry
    :param unique_id: ID of the measurement
    :param y_axes: Empty list to be filled
    :param measurement: Measurement
    :param dict_measurements: Measurement dictionary
    :param device_measurements: Device measurements
    :param input_dev: Input device
    :param output: Output device
    :param function: Function
    :param unit: Unit (Optional)
    :return: List of y-axes
    """
    # Iterate through each device entry.
    for each_device in all_devices:

        # If the ID stored in the dashboard element matches the ID of the table entry
        if each_device.unique_id == unique_id:

            use_unit = use_unit_generate(
                device_measurements, input_dev, output, function)

            # Add duration
            if measurement == 'duration_time':
                if 'second' not in y_axes:
                    y_axes.append('second')

            # Add duty cycle
            elif measurement == 'duty_cycle':
                if 'percent' not in y_axes:
                    y_axes.append('percent')

            # Use custom conversion unit
            elif (unique_id in use_unit and
                  measurement in use_unit[unique_id] and
                  use_unit[unique_id][measurement]):
                measure_short = use_unit[unique_id][measurement]
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # Find y-axis applicable to setpoint or band
            elif measurement in ['setpoint', 'setpoint_band_min', 'setpoint_band_max']:
                for each_input in input_dev:
                    if each_input.unique_id == each_device.measurement.split(',')[0]:
                        pid_measurement = each_device.measurement.split(',')[1]

                        # If PID uses an input that uses a custom conversion, use the custom unit
                        if (each_input.unique_id in use_unit and
                            pid_measurement in use_unit[each_input.unique_id] and
                            use_unit[each_input.unique_id][pid_measurement]):
                            measure_short = use_unit[each_input.unique_id][pid_measurement]
                            if measure_short not in y_axes:
                                y_axes.append(measure_short)
                        # Otherwise use the default unit of the input measurement
                        else:
                            if pid_measurement in dict_measurements:
                                measure_short = dict_measurements[pid_measurement]['meas']
                                if measure_short not in y_axes:
                                    y_axes.append(measure_short)

            # Add all other measurements
            elif measurement in dict_measurements and not unit:
                measure_short = dict_measurements[measurement]['meas']
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # Use custom y-axis
            elif measurement not in dict_measurements or unit not in dict_measurements[measurement]['units']:
                meas_name = f'{measurement}_{unit}'
                if meas_name not in y_axes and unit:
                    y_axes.append(meas_name)

    return y_axes
