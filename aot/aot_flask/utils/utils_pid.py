# -*- coding: utf-8 -*-
import logging
import time

from flask import flash, request
from flask_babel import gettext

from aot.config import PID_INFO
from aot.config_translations import TRANSLATIONS
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import Output
from aot.databases.models import PID
from aot.databases.models import Tab
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import controller_activate_deactivate
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import form_error_messages
from aot.utils.outputs import parse_output_information
from aot.utils.system_pi import get_measurement

logger = logging.getLogger(__name__)

#
# PID manipulation
#

def pid_mod(form_mod_pid_base,
            form_mod_pid_pwm_raise,
            form_mod_pid_pwm_lower,
            form_mod_pid_output_raise,
            form_mod_pid_output_lower,
            form_mod_pid_value_raise,
            form_mod_pid_value_lower,
            form_mod_pid_volume_raise,
            form_mod_pid_volume_lower):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None
    }
    page_refresh = False

    # 그룹 스코프(A1b) — 대상이 정해진 뒤에 묻는다(설계 §1-A).
    from aot.aot_flask.access import scope
    if not scope.can_operate_device(form_mod_pid_base.function_id.data):
        messages["error"].append(scope.deny_message())
        return messages, page_refresh

    dict_outputs = parse_output_information()

    if not form_mod_pid_base.validate():
        messages["error"] = form_error_messages(
            form_mod_pid_base, messages["error"])

    mod_pid = PID.query.filter(
        PID.unique_id == form_mod_pid_base.function_id.data).first()

    mod_pid.name = form_mod_pid_base.name.data
    messages["name"] = form_mod_pid_base.name.data
    new_tab_id = request.form.get('tab_id')
    if new_tab_id and new_tab_id != mod_pid.tab_id:
        if Tab.query.filter(Tab.unique_id == new_tab_id).first():
            mod_pid.tab_id = new_tab_id
            messages["tab_id"] = new_tab_id
    mod_pid.measurement = form_mod_pid_base.measurement.data
    mod_pid.direction = form_mod_pid_base.direction.data
    mod_pid.period = form_mod_pid_base.period.data
    mod_pid.log_level_debug = form_mod_pid_base.log_level_debug.data
    mod_pid.latitude = form_mod_pid_base.latitude.data if form_mod_pid_base.latitude.data not in [None, ''] else None
    mod_pid.longitude = form_mod_pid_base.longitude.data if form_mod_pid_base.longitude.data not in [None, ''] else None
    mod_pid.location_source = form_mod_pid_base.location_source.data
    mod_pid.start_offset = form_mod_pid_base.start_offset.data
    mod_pid.max_measure_age = form_mod_pid_base.max_measure_age.data
    mod_pid.setpoint = form_mod_pid_base.setpoint.data
    mod_pid.band = abs(form_mod_pid_base.band.data)
    mod_pid.send_lower_as_negative = form_mod_pid_base.send_lower_as_negative.data
    mod_pid.store_lower_as_negative = form_mod_pid_base.store_lower_as_negative.data
    mod_pid.p = form_mod_pid_base.k_p.data
    mod_pid.i = form_mod_pid_base.k_i.data
    mod_pid.d = form_mod_pid_base.k_d.data
    mod_pid.integrator_min = form_mod_pid_base.integrator_min.data
    mod_pid.integrator_max = form_mod_pid_base.integrator_max.data
    mod_pid.setpoint_tracking_type = form_mod_pid_base.setpoint_tracking_type.data

    raw_sst = (form_mod_pid_base.schedule_start_time.data or '').strip()
    mod_pid.schedule_start_time = raw_sst if raw_sst else None
    swo = form_mod_pid_base.schedule_week_offset.data
    mod_pid.schedule_week_offset = float(swo) if swo is not None else 0.0

    if form_mod_pid_base.setpoint_tracking_type.data == 'method':
        new_method_id = form_mod_pid_base.setpoint_tracking_method_id.data
        if mod_pid.setpoint_tracking_id != new_method_id:
            # Method changed — reset start time so next activation begins fresh
            mod_pid.method_start_time = None
            mod_pid.method_end_time = None
        mod_pid.setpoint_tracking_id = new_method_id
    elif form_mod_pid_base.setpoint_tracking_type.data == 'input-math':
        mod_pid.setpoint_tracking_id = form_mod_pid_base.setpoint_tracking_input_math_id.data
        if form_mod_pid_base.setpoint_tracking_max_age.data:
            mod_pid.setpoint_tracking_max_age = form_mod_pid_base.setpoint_tracking_max_age.data
        else:
            mod_pid.setpoint_tracking_max_age = 120
    else:
        mod_pid.setpoint_tracking_id = ''
        mod_pid.method_start_time = None
        mod_pid.method_end_time = None

    # Change measurement information
    if ',' in form_mod_pid_base.measurement.data:
        measurement_id = form_mod_pid_base.measurement.data.split(',')[1]
        selected_measurement = get_measurement(measurement_id)

        measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == form_mod_pid_base.function_id.data).all()
        if selected_measurement:
            for each_measurement in measurements:
                # Only set channels 0, 1, 2
                if each_measurement.channel in [0, 1, 2]:
                    each_measurement.measurement = selected_measurement.measurement
                    each_measurement.unit = selected_measurement.unit

        #
        # Handle Raise Output Settings
        #
        if form_mod_pid_base.raise_output_id.data:
            output_id = form_mod_pid_base.raise_output_id.data.split(",")[0]
            channel_id = form_mod_pid_base.raise_output_id.data.split(",")[1]
            raise_output_type = Output.query.filter(
                Output.unique_id == output_id).first().output_type

            def default_raise_output_settings(mod):
                if mod.raise_output_type == 'on_off':
                    mod.raise_min_duration = 0
                    mod.raise_max_duration = 0
                    mod.raise_min_off_duration = 0
                elif mod.raise_output_type == 'pwm':
                    mod.raise_min_duration = 2
                    mod.raise_max_duration = 98
                elif mod.raise_output_type == 'value':
                    mod.raise_min_duration = 0
                    mod.raise_max_duration = 0
                elif mod.raise_output_type == 'volume':
                    mod.raise_min_duration = 0
                    mod.raise_max_duration = 0
                return mod

            raise_output_id_changed = False
            if mod_pid.raise_output_id != form_mod_pid_base.raise_output_id.data:
                mod_pid.raise_output_id = form_mod_pid_base.raise_output_id.data
                raise_output_id_changed = True
                page_refresh = True

            # Output ID changed
            if ('output_types' in dict_outputs[raise_output_type] and
                    mod_pid.raise_output_id and
                    raise_output_id_changed):

                if len(dict_outputs[raise_output_type]['output_types']) == 1:
                    mod_pid.raise_output_type = dict_outputs[raise_output_type]['output_types'][0]
                else:
                    mod_pid.raise_output_type = None

                mod_pid = default_raise_output_settings(mod_pid)

            # Output ID unchanged
            elif ('output_types' in dict_outputs[raise_output_type] and
                  mod_pid.raise_output_id and
                  not raise_output_id_changed):

                if (not mod_pid.raise_output_type or
                        mod_pid.raise_output_type != form_mod_pid_base.raise_output_type.data):
                    if len(dict_outputs[raise_output_type]['output_types']) > 1:
                        mod_pid.raise_output_type = form_mod_pid_base.raise_output_type.data
                    mod_pid = default_raise_output_settings(mod_pid)
                elif mod_pid.raise_output_type == 'on_off':
                    if not form_mod_pid_output_raise.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_output_raise, messages["error"])
                    else:
                        mod_pid.raise_min_duration = form_mod_pid_output_raise.raise_min_duration.data
                        mod_pid.raise_max_duration = form_mod_pid_output_raise.raise_max_duration.data
                        mod_pid.raise_min_off_duration = form_mod_pid_output_raise.raise_min_off_duration.data
                elif mod_pid.raise_output_type == 'pwm':
                    if not form_mod_pid_pwm_raise.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_pwm_raise, messages["error"])
                    else:
                        mod_pid.raise_min_duration = form_mod_pid_pwm_raise.raise_min_duty_cycle.data
                        mod_pid.raise_max_duration = form_mod_pid_pwm_raise.raise_max_duty_cycle.data
                        mod_pid.raise_always_min_pwm = form_mod_pid_pwm_raise.raise_always_min_pwm.data
                elif mod_pid.raise_output_type == 'value':
                    if not form_mod_pid_value_raise.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_value_raise, messages["error"])
                    else:
                        mod_pid.raise_min_duration = form_mod_pid_value_raise.raise_min_amount.data
                        mod_pid.raise_max_duration = form_mod_pid_value_raise.raise_max_amount.data
                elif mod_pid.raise_output_type == 'volume':
                    if not form_mod_pid_volume_raise.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_volume_raise, messages["error"])
                    else:
                        mod_pid.raise_min_duration = form_mod_pid_volume_raise.raise_min_amount.data
                        mod_pid.raise_max_duration = form_mod_pid_volume_raise.raise_max_amount.data
        else:
            if mod_pid.raise_output_id is not None:
                page_refresh = True
            mod_pid.raise_output_id = None

        #
        # Handle Lower Output Settings
        #
        if form_mod_pid_base.lower_output_id.data:
            output_id = form_mod_pid_base.lower_output_id.data.split(",")[0]
            channel_id = form_mod_pid_base.lower_output_id.data.split(",")[1]
            lower_output_type = Output.query.filter(
                Output.unique_id == output_id).first().output_type

            def default_lower_output_settings(mod):
                if mod.lower_output_type == 'on_off':
                    mod.lower_min_duration = 0
                    mod.lower_max_duration = 0
                    mod.lower_min_off_duration = 0
                elif mod.lower_output_type == 'pwm':
                    mod.lower_min_duration = 2
                    mod.lower_max_duration = 98
                elif mod.lower_output_type == 'value':
                    mod.lower_min_duration = 0
                    mod.lower_max_duration = 0
                elif mod.lower_output_type == 'volume':
                    mod.lower_min_duration = 0
                    mod.lower_max_duration = 0
                return mod

            lower_output_id_changed = False
            if mod_pid.lower_output_id != form_mod_pid_base.lower_output_id.data:
                mod_pid.lower_output_id = form_mod_pid_base.lower_output_id.data
                lower_output_id_changed = True
                page_refresh = True

            # Output ID changed
            if ('output_types' in dict_outputs[lower_output_type] and
                    mod_pid.lower_output_id and
                    lower_output_id_changed):

                if len(dict_outputs[lower_output_type]['output_types']) == 1:
                    mod_pid.lower_output_type = dict_outputs[lower_output_type]['output_types'][0]
                else:
                    mod_pid.lower_output_type = None

                mod_pid = default_lower_output_settings(mod_pid)

            # Output ID unchanged
            elif ('output_types' in dict_outputs[lower_output_type] and
                    mod_pid.lower_output_id and
                    not lower_output_id_changed):

                if (not mod_pid.lower_output_type or
                        mod_pid.lower_output_type != form_mod_pid_base.lower_output_type.data):
                    if len(dict_outputs[lower_output_type]['output_types']) > 1:
                        mod_pid.lower_output_type = form_mod_pid_base.lower_output_type.data
                    mod_pid = default_lower_output_settings(mod_pid)
                elif mod_pid.lower_output_type == 'on_off':
                    if not form_mod_pid_output_lower.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_output_lower, messages["error"])
                    else:
                        mod_pid.lower_min_duration = form_mod_pid_output_lower.lower_min_duration.data
                        mod_pid.lower_max_duration = form_mod_pid_output_lower.lower_max_duration.data
                        mod_pid.lower_min_off_duration = form_mod_pid_output_lower.lower_min_off_duration.data
                elif mod_pid.lower_output_type == 'pwm':
                    if not form_mod_pid_pwm_lower.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_pwm_lower, messages["error"])
                    else:
                        mod_pid.lower_min_duration = form_mod_pid_pwm_lower.lower_min_duty_cycle.data
                        mod_pid.lower_max_duration = form_mod_pid_pwm_lower.lower_max_duty_cycle.data
                        mod_pid.lower_always_min_pwm = form_mod_pid_pwm_lower.lower_always_min_pwm.data
                elif mod_pid.lower_output_type == 'value':
                    if not form_mod_pid_value_lower.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_value_lower, messages["error"])
                    else:
                        mod_pid.lower_min_duration = form_mod_pid_value_lower.lower_min_amount.data
                        mod_pid.lower_max_duration = form_mod_pid_value_lower.lower_max_amount.data
                elif mod_pid.lower_output_type == 'volume':
                    if not form_mod_pid_volume_lower.validate():
                        messages["error"] = form_error_messages(
                            form_mod_pid_volume_lower, messages["error"])
                    else:
                        mod_pid.lower_min_duration = form_mod_pid_volume_lower.lower_min_amount.data
                        mod_pid.lower_max_duration = form_mod_pid_volume_lower.lower_max_amount.data
        else:
            if mod_pid.lower_output_id is not None:
                page_refresh = True
            mod_pid.lower_output_id = None

    if (mod_pid.raise_output_id and mod_pid.lower_output_id and
            mod_pid.raise_output_id == mod_pid.lower_output_id):
        messages["error"].append(gettext("Raise and lower outputs cannot be the same"))

    try:
        if not messages["error"]:
            db.session.commit()
            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['modify']['title'],
                controller=TRANSLATIONS['pid']['title']))

            # If the controller is active or paused, refresh variables in thread
            if mod_pid.is_activated:
                control = DaemonControl()
                return_value = control.pid_mod(form_mod_pid_base.function_id.data)
                flash(gettext("PID Controller settings refresh response: ") +
                      "{resp}".format(resp=return_value), "success")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def pid_del(pid_id):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    # 그룹 스코프(A1b) — **부수 효과보다 먼저 막는다.**
    #
    # `delete_entry_with_id()` 의 초크포인트만으로는 부족하다는 것을 실측으로
    # 확인했다(2026-08-22): `output_del` 은 그 함수를 부르기 전에 측정값을
    # 지우고 바인딩을 끊으며, 반환값 0(거부)을 보지 않고 "삭제 성공" 을
    # 보고했다. 결과는 **출력은 남았는데 그 측정값·채널은 사라진** 부분 변경
    # 이고, 사용자는 성공 메시지를 봤다.
    #
    # 그래서 초크포인트는 **뒤를 받치는 것**이고 실제 경계는 여기다.
    from aot.aot_flask.access import scope
    if not scope.can_operate_device(pid_id):
        messages["error"].append(scope.deny_message())
        return messages

    try:
        pid = PID.query.filter(
            PID.unique_id == pid_id).first()
        
        if not pid:
            messages["error"].append("PID not found")
            return messages
        
        if pid.is_activated:
            pid_deactivate(pid_id)

        device_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == pid_id).all()

        for each_measurement in device_measurements:
            delete_entry_with_id(
                DeviceMeasurements,
                each_measurement.unique_id,
                flash_message=False)

        # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정 슬롯으로
        # 남는다(위치 마커만 예외). 예전에는 이 경로가 도형을 아무것도
        # 정리하지 않아 고아 도형을 만들었다.
        from aot.aot_flask.geo.device_binding import end_all_for_device
        end_all_for_device(pid_id)
        delete_entry_with_id(
            PID, pid_id, flash_message=False)

        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['delete']['title'],
            controller=TRANSLATIONS['pid']['title']))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def has_required_pid_values(pid_id, messages):
    pid = PID.query.filter(
        PID.unique_id == pid_id).first()

    if not pid.measurement:
        messages["error"].append("A valid Measurement is required")
    else:
        device_unique_id = pid.measurement.split(',')[0]
        input_dev = Input.query.filter(
            Input.unique_id == device_unique_id).first()
        function = CustomController.query.filter(
            CustomController.unique_id == device_unique_id).first()
        if not input_dev and not function:
            messages["error"].append("A valid controller/measurement is required")

    if not pid.raise_output_id and not pid.lower_output_id:
        messages["warning"].append(
            "No output selected. PID will run in calculation-only mode "
            "(control variable written to measurement channel 9).")

    return messages


def pid_activate(pid_id):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    messages = has_required_pid_values(pid_id, messages)

    # Check if associated sensor is activated
    pid = PID.query.filter(
        PID.unique_id == pid_id).first()

    device_unique_id = pid.measurement.split(',')[0]
    input_dev = Input.query.filter(
        Input.unique_id == device_unique_id).first()

    if input_dev and not input_dev.is_activated:
        messages["error"].append(gettext(
            "Cannot activate PID controller if the associated Input "
            "controller is inactive"))

    if ((pid.direction == 'both' and not (pid.lower_output_id and pid.raise_output_id)) or
            (pid.direction == 'lower' and not pid.lower_output_id) or
            (pid.direction == 'raise' and not pid.raise_output_id)):
        if pid.raise_output_id or pid.lower_output_id:
            # One side is missing for the selected direction
            messages["error"].append(gettext(
                "Cannot activate PID controller if raise and/or lower output IDs "
                "are not selected"))
        # else: both are unset → calculation-only mode, already warned above

    # DeviceMeasurements 채널이 없으면 PID_INFO 기반으로 자동 생성.
    # 구버전 DB에서 마이그레이션된 PID는 채널 레코드 자체가 없을 수 있음.
    if not messages["error"]:
        try:
            existing_channels = {m.channel for m in DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == pid_id).all()}
            if not existing_channels:
                for ch, info in PID_INFO['measure'].items():
                    new_m = DeviceMeasurements()
                    new_m.device_id = pid_id
                    new_m.channel = int(ch)
                    new_m.name = info.get('name', '')
                    new_m.measurement = info.get('measurement', '')
                    new_m.unit = info.get('unit', '')
                    if info.get('measurement_type'):
                        new_m.measurement_type = info['measurement_type']
                    new_m.save()
                existing_channels = set(PID_INFO['measure'].keys())
        except Exception:
            pass

    # setpoint 채널(0-2)에 측정값의 단위를 채움.
    if not messages["error"] and pid.measurement and ',' in pid.measurement:
        try:
            measurement_id = pid.measurement.split(',')[1]
            selected_measurement = get_measurement(measurement_id)
            if selected_measurement and selected_measurement.unit:
                setpoint_channels = DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == pid_id).all()
                needs_commit = False
                for m in setpoint_channels:
                    if m.channel in [0, 1, 2] and not m.unit:
                        m.measurement = selected_measurement.measurement
                        m.unit = selected_measurement.unit
                        needs_commit = True
                if needs_commit:
                    db.session.commit()
        except Exception:
            pass

    time.sleep(1)
    messages = controller_activate_deactivate(
        messages, 'activate', 'PID', pid_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['activate']['title'],
            controller=TRANSLATIONS['pid']['title']))

    return messages


def pid_deactivate(pid_id):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    pid = PID.query.filter(
        PID.unique_id == pid_id).first()
    if not pid:
        messages["error"].append("PID Controller not found")

    if not pid.is_activated:
        messages["error"].append("PID Controller not active")

    if not messages["error"]:
        pid.is_activated = False
        pid.is_held = False
        pid.is_paused = False
        pid.method_start_time = None
        pid.method_end_time = None
        db.session.commit()

        time.sleep(1)
        messages = controller_activate_deactivate(
            messages, 'deactivate', 'PID', pid_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['deactivate']['title'],
            controller=TRANSLATIONS['pid']['title']))

    return messages


def pid_manipulate(pid_id, action):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    if action not in ['Hold', 'Pause', 'Resume']:
        messages["error"].append(
            '{}: {}'.format(TRANSLATIONS['invalid']['title'], action))
        return messages

    try:
        control = DaemonControl()
        return_value = None
        if action == 'Hold':
            return_value = control.pid_hold(pid_id)
        elif action == 'Pause':
            return_value = control.pid_pause(pid_id)
        elif action == 'Resume':
            return_value = control.pid_resume(pid_id)
        if return_value:
            messages["success"].append(
                '{}: {}: {}: {}'.format(
                    TRANSLATIONS['controller']['title'],
                    TRANSLATIONS['pid']['title'],
                    action,
                    return_value))
    except Exception as err:
        messages["error"].append(
            "{}: {}: {}".format(
                TRANSLATIONS['Error']['title'],
                TRANSLATIONS['PID']['title'], err))

    return messages
