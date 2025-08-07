# -*- coding: utf-8 -*-
import logging
import threading

import sqlalchemy
from flask import current_app
from flask_babel import gettext

from aot.config import FUNCTION_INFO
from aot.config import PID_INFO
from aot.config_translations import TRANSLATIONS
from aot.databases import set_uuid
from aot.databases.models import Actions
from aot.databases.models import Conditional
from aot.databases.models import ConditionalConditions
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Function
from aot.databases.models import FunctionChannel
from aot.databases.models import PID
from aot.databases.models import Trigger
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.utils.conditional import save_conditional_code
from aot.utils.actions import parse_action_information
from aot.utils.functions import parse_function_information

logger = logging.getLogger(__name__)

#
# Function manipulation
#

def function_add(form_add_func):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    new_function_id = None
    list_unmet_deps = []
    dep_name = None
    dep_message = ''

    function_name = form_add_func.function_type.data

    dict_controllers = parse_function_information()

    if not current_app.config['TESTING']:
        dep_unmet, _, dep_message = return_dependencies(function_name)
        if dep_unmet:
            messages["error"].append(
                f"{function_name} 의 종속성이 충족되지 않았습니다. "
                "기능을 추가하기 전에 반드시 설치되어야 합니다.")
            
            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
                if each_dep[2] == 'pip-pypi':
                    dep_message += f" 파이썬 패키지 {each_dep[3]}가 '{each_dep[0]}'을(를) 가져올 수 없어 설치되어 있지 않습니다."


            if function_name in dict_controllers:
                dep_name = dict_controllers[function_name]['function_name']
            elif function_name in FUNCTION_INFO and 'name' in FUNCTION_INFO[function_name]:
                dep_name = FUNCTION_INFO[function_name]['name']
            else:
                messages["error"].append(f"기능을 찾을 수 없습니다: {function_name}")

            return messages, dep_name, list_unmet_deps, dep_message, None

    new_func = None

    try:
        if function_name == 'conditional_conditional':
            new_func = Conditional()
            new_func.position_y = 999
            new_func.conditional_import = """
from datetime import datetime"""
            new_func.conditional_initialize = """
self.loop_count = 0"""
            new_func.conditional_statement = '''
# 조건부 사용 방법을 학습하기 위한 예제 코드입니다. 자세한 내용은 매뉴얼을 참조하세요.
self.logger.info("이 INFO 로그 항목은 데몬 로그에 표시됩니다")

self.loop_count += 1  # 실행 횟수를 증가시킵니다

measurement = self.condition("asdf1234")  # 조건부 ID를 올바른 것으로 교체하세요
self.logger.info(f"측정값은 {measurement}입니다")

if measurement is not None:  # 측정값이 존재하는 경우
    self.message += "이 메시지는 이메일 알림 및 노트에 표시됩니다.\n"

    if measurement < 23:  # 측정값이 23보다 작으면
        self.message += f"측정값이 너무 낮습니다! 측정값은 {measurement}입니다.\n"
        self.run_all_actions(message=self.message)  # 모든 동작을 순차적으로 실행합니다

    elif measurement > 27:  # 측정값이 27보다 크면
        self.message += f"측정값이 너무 높습니다! 측정값은 {measurement}입니다.\n"
        # "qwer5678"을 적절한 동작 ID로 교체하세요
        self.run_action("qwer5678", message=self.message)  # 특정 동작을 실행합니다'''
            
            new_func.conditional_status = '''
# 다른 컨트롤러 및 위젯에 반환 상태를 제공하는 예제 코드입니다.
status_dict = {
    'string_status': f"컨트롤러가 {self.loop_count}번 루프를 실행하였습니다. 현재 시간: {datetime.now()}",
    'loop_count': self.loop_count,
    'error': []
}
return status_dict'''

            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id
                if not current_app.config['TESTING']:
                    save_conditional_code(
                        messages["error"],
                        new_func.conditional_import,
                        new_func.conditional_initialize,
                        new_func.conditional_statement,
                        new_func.conditional_status,
                        new_func.unique_id,
                        ConditionalConditions.query.all(),
                        Actions.query.all(),
                        test=False)
                    
        elif function_name == 'pid_pid':
            new_func = PID()
            new_func.position_y = 999
            new_func.save()
            new_function_id = new_func.unique_id

            for each_channel, measure_info in PID_INFO['measure'].items():
                new_measurement = DeviceMeasurements()

                if 'name' in measure_info:
                    new_measurement.name = measure_info['name']
                if 'measurement_type' in measure_info:
                    new_measurement.measurement_type = measure_info['measurement_type']

                new_measurement.device_id = new_func.unique_id
                new_measurement.measurement = measure_info['measurement']
                new_measurement.unit = measure_info['unit']
                new_measurement.channel = each_channel
                if not messages["error"]:
                    new_measurement.save()

        elif function_name in ['trigger_edge',
                               'trigger_output',
                               'trigger_output_pwm',
                               'trigger_timer_daily_time_point',
                               'trigger_timer_daily_time_span',
                               'trigger_timer_duration',
                               'trigger_run_pwm_method',
                               'trigger_sunrise_sunset']:
            new_func = Trigger()
            new_func.name = '{}'.format(FUNCTION_INFO[function_name]['name'])
            new_func.trigger_type = function_name
            new_func.position_y = 999

            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name == 'function_actions':
            new_func = Function()
            new_func.position_y = 999
            new_func.function_type = function_name
            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name in dict_controllers:
            # Custom Function Controller
            new_func = CustomController()
            new_func.device = function_name
            new_func.position_y = 999

            if 'function_name_short' in dict_controllers[function_name]:
                new_func.name = dict_controllers[function_name]['function_name_short']
            elif 'function_name' in dict_controllers[function_name]:
                new_func.name = dict_controllers[function_name]['function_name']
            elif function_name in FUNCTION_INFO and 'name' in FUNCTION_INFO[function_name]:
                new_func.name = FUNCTION_INFO[function_name]['name']
            else:
                new_func.name = "기능 이름"


            messages["error"], custom_options = custom_options_return_json(
                messages["error"], dict_controllers, device=function_name, use_defaults=True)
            new_func.custom_options = custom_options

            new_func.unique_id = set_uuid()

            if ('execute_at_creation' in dict_controllers[new_func.device] and
                    not current_app.config['TESTING']):
                messages["error"], new_func = dict_controllers[new_func.device]['execute_at_creation'](
                    messages["error"], new_func, dict_controllers[new_func.device])
                
            if not messages["error"]:
                new_func.save()
                new_function_id = new_func.unique_id

        elif function_name == '':
            messages["error"].append("기능 유형을 선택해야 합니다.")
        else:
            messages["error"].append(f"알 수 없는 기능 유형: '{function_name}'")

        if not messages["error"]:
            if function_name in dict_controllers:

                # Add measurements defined in the Function module


                if ('measurements_dict' in dict_controllers[function_name] and
                        dict_controllers[function_name]['measurements_dict']):
                    for each_channel in dict_controllers[function_name]['measurements_dict']:
                        measure_info = dict_controllers[function_name]['measurements_dict'][each_channel]
                        new_measurement = DeviceMeasurements()
                        new_measurement.device_id = new_func.unique_id
                        if 'name' in measure_info:
                            new_measurement.name = measure_info['name']
                        else:
                            new_measurement.name = ""
                        if 'measurement' in measure_info:
                            new_measurement.measurement = measure_info['measurement']
                        else:
                            new_measurement.measurement = ""
                        if 'unit' in measure_info:
                            new_measurement.unit = measure_info['unit']
                        else:
                            new_measurement.unit = ""
                        new_measurement.channel = each_channel
                        new_measurement.save()


                # If variable measurements exist in the Function module


                elif ('measurements_variable_amount' in dict_controllers[function_name] and
                        dict_controllers[function_name]['measurements_variable_amount']):
                    
                    new_measurement = DeviceMeasurements()
                    new_measurement.name = ""
                    new_measurement.device_id = new_func.unique_id
                    new_measurement.measurement = ""
                    new_measurement.unit = ""
                    new_measurement.channel = 0
                    new_measurement.save()


                # Add channels defined in the Function module


                if 'channels_dict' in dict_controllers[function_name]:
                    for each_channel, channel_info in dict_controllers[function_name]['channels_dict'].items():
                        new_channel = FunctionChannel()
                        new_channel.channel = each_channel
                        new_channel.function_id = new_func.unique_id


                        messages["error"], custom_options = custom_channel_options_return_json(
                            messages["error"], dict_controllers, None,
                            new_func.unique_id, each_channel,
                            device=new_func.device, use_defaults=True)
                        new_channel.custom_options = custom_options

                        new_channel.save()

            messages["success"].append(f"{TRANSLATIONS['add']['title']} {TRANSLATIONS['function']['title']}")

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        logger.exception("Add Function")
        messages["error"].append(str(except_msg))

    return messages, dep_name, list_unmet_deps, dep_message, new_function_id


def function_mod(form):
    """Modify a Function."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None,
        "return_text": []
    }

    try:
        func_mod = Function.query.filter(
            Function.unique_id == form.function_id.data).first()
        
        func_mod.name = form.name.data
        messages["name"] = form.name.data
        func_mod.log_level_debug = form.log_level_debug.data

        if not messages["error"]:
            db.session.commit()
            messages["success"].append(f"{TRANSLATIONS['modify']['title']} {TRANSLATIONS['function']['title']}")

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def function_del(function_id):
    """Delete a Function."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        actions = Actions.query.filter(
            Actions.function_id == function_id).all()
        for each_action in actions:
            delete_entry_with_id(
                Actions, each_action.unique_id, flash_message=False)
            
        device_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == function_id).all()
        for each_measurement in device_measurements:
            delete_entry_with_id(
                DeviceMeasurements,
                each_measurement.unique_id,
                flash_message=False)
            
        delete_entry_with_id(Function, function_id, flash_message=False)

        messages["success"].append(f"{TRANSLATIONS['delete']['title']} {TRANSLATIONS['function']['title']}")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def action_execute_all(form):
    """Execute All Actions."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    function_type = None
    func = None

    if form.function_type.data == 'conditional':
        function_type = TRANSLATIONS['conditional']['title']
        func = Conditional.query.filter(
            Conditional.unique_id == form.function_id.data).first()
    elif form.function_type.data == 'trigger':
        function_type = TRANSLATIONS['trigger']['title']
        func = Trigger.query.filter(
            Trigger.unique_id == form.function_id.data).first()
    elif form.function_type.data in ['function', 'function_actions']:
        function_type = TRANSLATIONS['function']['title']
        func = Function.query.filter(
            Function.unique_id == form.function_id.data).first()
    else:
        messages["error"].append(f"알 수 없는 기능 유형: '{form.function_type.data}'")

    if not messages["error"]:
        try:
            control = DaemonControl()
            trigger_all_actions = threading.Thread(
                target=control.trigger_all_actions,
                args=(form.function_id.data,),
                kwargs={
                    'message': f"Executing all actions of {function_type} ({func.name}, ID {form.function_id.data}).",
                    'debug': func.log_level_debug
                }
            )
            trigger_all_actions.start()
            messages["success"].append(f"{gettext('Execute All')} {function_type} {TRANSLATIONS['actions']['title']}")
        except Exception as except_msg:
            messages["error"].append(str(except_msg))

    return messages