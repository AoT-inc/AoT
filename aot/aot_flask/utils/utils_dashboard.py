# -*- coding: utf-8 -*-
import json
import logging
import subprocess

import sqlalchemy
from flask import current_app, flash, url_for
from flask_babel import gettext

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

logger = logging.getLogger(__name__)

#
# 대시보드
#

def dashboard_add():
    """대시보드를 추가합니다."""
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

        flash(gettext("ID %(id)s의 대시보드가 성공적으로 추가되었습니다.", id=new_dash.id), "success")

    return new_dash.unique_id


def dashboard_mod(form):
    """대시보드를 수정합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    dash_mod = Dashboard.query.filter(
        Dashboard.unique_id == form.dashboard_id.data).first()

    name_exists = Dashboard.query.filter(
        Dashboard.name == form.name.data).first()
    if dash_mod.name != form.name.data and name_exists:
        flash(gettext("대시보드 이름이 이미 사용 중입니다."), 'error')

    dash_mod.name = form.name.data

    if not error:
        db.session.commit()

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def dashboard_lock(dashboard_id, lock):
    """대시보드를 잠급니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['lock']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    try:
        dash_mod = Dashboard.query.filter(
            Dashboard.unique_id == dashboard_id).first()

        dash_mod.locked = lock

        if not error:
            db.session.commit()

    except Exception as msg:
        error.append(msg)
        logger.exception("대시보드 잠금 중 예외 발생")

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def dashboard_copy(form):
    """대시보드와 위젯들을 복제합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['duplicate']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []

    try:
        # 현재 대시보드와 그 위젯들을 가져옵니다.
        dashboard = Dashboard.query.filter(
            Dashboard.unique_id == form.dashboard_id.data).first()
        widgets = Widget.query.filter(
            Widget.dashboard_id == dashboard.unique_id).all()

        # 새로운 고유 ID와 이름으로 대시보드를 복제합니다.
        new_dashboard = clone_model(
            dashboard, unique_id=set_uuid(), name=gettext("새 대시보드"))

        # 모든 위젯을 복제하여 새로운 대시보드에 할당합니다.
        for each_widget in widgets:
            clone_model(each_widget, unique_id=set_uuid(), dashboard_id=new_dashboard.unique_id)
    except Exception as msg:
        error.append(msg)
        logger.exception("대시보드 복제 중 예외 발생")

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


def dashboard_del(form):
    """대시보드를 삭제합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['dashboard']['title'])
    error = []
    create_new_dash = False

    dashboards = Dashboard.query.all()
    if len(dashboards) == 1:
        create_new_dash = True

    widgets = Widget.query.filter(
        Widget.dashboard_id == form.dashboard_id.data).all()
    for each_widget in widgets:
        delete_entry_with_id(Widget, each_widget.unique_id)

    delete_entry_with_id(Dashboard, form.dashboard_id.data)

    if create_new_dash:
        new_dash = Dashboard()
        new_dash.name = gettext("새 대시보드")
        new_dash.save()

    flash_success_errors(
        error, action, url_for('routes_dashboard.page_dashboard_default'))


#
# 위젯
#

def widget_add(form_base, request_form):
    """대시보드에 위젯을 추가합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['add']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    reload_flask = False

    dict_widgets = parse_widget_information()

    if form_base.widget_type.data:
        widget_name = form_base.widget_type.data
    else:
        widget_name = ''
        error.append(gettext("위젯 이름이 누락되었습니다."))

    if current_app.config['TESTING']:
        dep_unmet = False
    else:
        dep_unmet, _, _ = return_dependencies(widget_name)
        if dep_unmet:
            list_unmet_deps = []
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
            error.append(gettext("추가하려는 %(dev)s 장치의 종속성이 충족되지 않았습니다: %(dep)s", dev=widget_name, dep=', '.join(list_unmet_deps)))

    new_widget = Widget()
    new_widget.dashboard_id = form_base.dashboard_id.data
    new_widget.graph_type = widget_name
    new_widget.name = form_base.name.data
    new_widget.font_em_name = form_base.font_em_name.data
    new_widget.enable_drag_handle = form_base.enable_drag_handle.data
    new_widget.refresh_duration = form_base.refresh_duration.data

    # 새로운 위젯의 시작 위치를 결정합니다.
    position_y_start = 0
    for each_widget in Widget.query.filter(
            Widget.dashboard_id == form_base.dashboard_id.data).all():
        highest_position = each_widget.position_y + each_widget.height
        if highest_position > position_y_start:
            position_y_start = highest_position
    new_widget.position_y = position_y_start

    # 위젯 옵션 설정
    if widget_name in dict_widgets:
        def dict_has_value(key):
            if (key in dict_widgets[widget_name] and
                    (dict_widgets[widget_name][key] or dict_widgets[widget_name][key] == 0)):
                return True

        if dict_has_value('widget_width'):
            new_widget.width = dict_widgets[widget_name]['widget_width']
        if dict_has_value('widget_height'):
            new_widget.height = dict_widgets[widget_name]['widget_height']

    # 사용자 지정 옵션을 JSON 문자열로 생성합니다.
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

            # 해당 위젯이 처음 추가된 경우, 플라스크를 재시작합니다.
            if Widget.query.filter(Widget.graph_type == widget_name).count() == 1:
                reload_flask = True

            if not current_app.config['TESTING']:
                # 위젯 설정 새로 고침
                control = DaemonControl()
                control.widget_add_refresh(new_widget.unique_id)

            flash(gettext("%(dev)s (ID %(id)s)가 성공적으로 추가되었습니다.", dev=dict_widgets[form_base.widget_type.data]['widget_name'], id=new_widget.id), "success")
    except sqlalchemy.exc.OperationalError as except_msg:
        error.append(except_msg)
    except sqlalchemy.exc.IntegrityError as except_msg:
        error.append(except_msg)

    for each_error in error:
        flash(each_error, "error")

    return dep_unmet, reload_flask


def widget_mod(form_base, request_form):
    """대시보드 항목의 설정을 수정합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['modify']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    dict_widgets = parse_widget_information()

    mod_widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()
    mod_widget.name = form_base.name.data
    mod_widget.font_em_name = form_base.font_em_name.data
    mod_widget.enable_drag_handle = form_base.enable_drag_handle.data
    mod_widget.refresh_duration = form_base.refresh_duration.data

    try:
        custom_options_json_presave = json.loads(mod_widget.custom_options)
    except:
        logger.error("Malformed JSON")
        custom_options_json_presave = {}

    # 사용자 지정 옵션을 JSON 문자열로 생성합니다.
    error, custom_options_json_postsave = custom_options_return_json(
        error, dict_widgets, request_form, mod_dev=mod_widget, device=mod_widget.graph_type)

    if 'execute_at_modification' in dict_widgets[mod_widget.graph_type]:
        (allow_saving,
         page_refresh,
         mod_widget,
         custom_options) = dict_widgets[mod_widget.graph_type]['execute_at_modification'](
            mod_widget, request_form, custom_options_json_presave, json.loads(custom_options_json_postsave))
        custom_options = json.dumps(custom_options)  # 딕셔너리를 JSON 문자열로 변환
        if not allow_saving:
            error.append(gettext("execute_at_modification()이 위젯 옵션 저장을 허용하지 않습니다."))
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
    """대시보드에서 위젯을 삭제합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['delete']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

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
    """대시보드에서 위젯을 복제합니다."""
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['duplicate']['title'],
        controller=TRANSLATIONS['widget']['title'])
    error = []

    dict_widgets = parse_widget_information()
    orig_widget = Widget.query.filter(
        Widget.unique_id == form_base.widget_id.data).first()

    if not orig_widget:
        error.append(gettext("원본 위젯을 찾을 수 없습니다."))
        flash_success_errors(
            error, action, url_for('routes_dashboard.page_dashboard',
                                   dashboard_id=form_base.dashboard_id.data))
        return

    try:
        # 새 위치: 현 대시보드 최하단(y 최대)
        position_y_start = 0
        for each_widget in Widget.query.filter(
                Widget.dashboard_id == orig_widget.dashboard_id).all():
            highest_position = each_widget.position_y + each_widget.height
            if highest_position > position_y_start:
                position_y_start = highest_position

        # 본체 복제
        new_widget = clone_model(
            orig_widget,
            unique_id=set_uuid(),
            name=f"{orig_widget.name} (copy)",
            position_y=position_y_start,
        )

        # 방어적 초기화: 복제 즉시 자동 갱신/실행 방지 옵션이 있다면 필요 시 끌 수 있음
        # (현재는 원본과 동일 옵션 사용)

        # 저장
        new_widget.save()

        # 프론트엔드에 갱신 알림
        control = DaemonControl()
        control.widget_add_refresh(new_widget.unique_id)

        flash(gettext("%(dev)s 위젯(ID %(id)s)을 복제했습니다.", dev=dict_widgets[orig_widget.graph_type]['widget_name'], id=new_widget.id), "success")

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
    """각 그래프에 사용할 y축을 결정합니다."""
    if not ids_measures:
        return

    y_axes = []

    function = CustomController.query.all()
    device_measurements = DeviceMeasurements.query.all()
    input_dev = Input.query.all()
    output = Output.query.all()
    pid = PID.query.all()

    devices_list = [input_dev, output, pid]

    # 각 기기 테이블을 반복합니다.
    for each_device in devices_list:

        # 대시보드 요소의 각 ID 및 측정값 집합을 반복합니다.
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

                    # 각 기기 항목을 반복합니다.
                    for each_device_entry in each_device:

                        # 대시보드 요소에 저장된 ID가 테이블 항목의 ID와 일치하면
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

                    # 각 기기 항목을 반복합니다.
                    for each_device_entry in each_device:

                        # 대시보드 요소에 저장된 ID가 테이블 항목의 ID와 일치하면
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
    y축 목록을 생성합니다.
    :param all_devices: Input, Output, 및 PID SQL 항목
    :param unique_id: 측정값의 ID
    :param y_axes: 채워질 빈 리스트
    :param measurement: 측정값
    :param dict_measurements: 측정값 딕셔너리
    :param device_measurements: 기기 측정값
    :param input_dev: 입력 장치
    :param output: 출력 장치
    :param function: 함수
    :param unit: 단위 (선택 사항)
    :return: y축 목록
    """
    # 각 기기 항목을 반복합니다.
    for each_device in all_devices:

        # 대시보드 요소에 저장된 ID가 테이블 항목의 ID와 일치하면
        if each_device.unique_id == unique_id:

            use_unit = use_unit_generate(
                device_measurements, input_dev, output, function)

            # 지속 시간 추가
            if measurement == 'duration_time':
                if 'second' not in y_axes:
                    y_axes.append('second')

            # 듀티 사이클 추가
            elif measurement == 'duty_cycle':
                if 'percent' not in y_axes:
                    y_axes.append('percent')

            # 사용자 지정 변환 단위 사용
            elif (unique_id in use_unit and
                  measurement in use_unit[unique_id] and
                  use_unit[unique_id][measurement]):
                measure_short = use_unit[unique_id][measurement]
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # 세트포인트 또는 밴드에 적용되는 y축 찾기
            elif measurement in ['setpoint', 'setpoint_band_min', 'setpoint_band_max']:
                for each_input in input_dev:
                    if each_input.unique_id == each_device.measurement.split(',')[0]:
                        pid_measurement = each_device.measurement.split(',')[1]

                        # PID가 사용자 지정 변환을 사용하는 입력을 사용하는 경우, 사용자 지정 단위를 사용
                        if (each_input.unique_id in use_unit and
                            pid_measurement in use_unit[each_input.unique_id] and
                            use_unit[each_input.unique_id][pid_measurement]):
                            measure_short = use_unit[each_input.unique_id][pid_measurement]
                            if measure_short not in y_axes:
                                y_axes.append(measure_short)
                        # 그렇지 않으면 입력 측정값의 기본 단위를 사용
                        else:
                            if pid_measurement in dict_measurements:
                                measure_short = dict_measurements[pid_measurement]['meas']
                                if measure_short not in y_axes:
                                    y_axes.append(measure_short)

            # 기타 모든 측정값을 추가
            elif measurement in dict_measurements and not unit:
                measure_short = dict_measurements[measurement]['meas']
                if measure_short not in y_axes:
                    y_axes.append(measure_short)

            # 사용자 지정 y축 사용
            elif measurement not in dict_measurements or unit not in dict_measurements[measurement]['units']:
                meas_name = f'{measurement}_{unit}'
                if meas_name not in y_axes and unit:
                    y_axes.append(meas_name)

    return y_axes