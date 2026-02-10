# -*- coding: utf-8 -*-
import json
import logging
import os

import sqlalchemy
# 번역 기능 사용하지 않으므로 gettext 대신 한글 문자열을 직접 사용합니다.
# from flask_babel import gettext

from aot.config import PATH_PYTHON_CODE_USER
from aot.config_translations import TRANSLATIONS
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import FunctionChannel
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_measurement
from aot.aot_flask.utils.utils_general import controller_activate_deactivate
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.utils.functions import parse_function_information
from aot.utils.system_pi import parse_custom_option_values
from aot.aot_flask.utils.utils_map_config import (
    ensure_map_config,
    clone_map_config,
    delete_map_config,
)

logger = logging.getLogger(__name__)


def controller_mod(form_mod, request_form):
    """사용자 정의 컨트롤러 수정."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None
    }
    page_refresh = False

    dict_controllers = parse_function_information()

    try:
        channels = FunctionChannel.query.filter(
            FunctionChannel.function_id == form_mod.function_id.data).all()
        mod_controller = CustomController.query.filter(
            CustomController.unique_id == form_mod.function_id.data).first()

        if mod_controller and not getattr(mod_controller, 'map_config_id', None):
            map_cfg = ensure_map_config(
                None,
                mod_controller.name,
                mod_controller.latitude,
                mod_controller.longitude
            )
            mod_controller.map_config_id = map_cfg.unique_id

        mod_without_deactivate = False
        if ('modify_settings_without_deactivating' in dict_controllers[mod_controller.device] and
                dict_controllers[mod_controller.device]['modify_settings_without_deactivating']):
            mod_without_deactivate = True

        if mod_controller.is_activated and not mod_without_deactivate:
            messages["error"].append("컨트롤러를 수정하기 전에 비활성화하세요.")

        mod_controller.name = form_mod.name.data
        messages["name"] = form_mod.name.data
        mod_controller.log_level_debug = form_mod.log_level_debug.data
        mod_controller.latitude = form_mod.latitude.data if form_mod.latitude.data not in [None, ''] else None
        mod_controller.longitude = form_mod.longitude.data if form_mod.longitude.data not in [None, ''] else None
        mod_controller.location_source = form_mod.location_source.data

        # 채널 활성화/비활성화 처리
        measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == form_mod.function_id.data).all()
        if form_mod.measurements_enabled.data:
            for each_measurement in measurements:
                if each_measurement.unique_id in form_mod.measurements_enabled.data:
                    each_measurement.is_enabled = True
                else:
                    each_measurement.is_enabled = False

        # 측정 설정 저장
        messages, page_refresh = utils_measurement.measurement_mod_form(
            messages, page_refresh, request_form)

        # 변수 측정 입력을 위한 채널 추가 또는 삭제
        if ('measurements_variable_amount' in dict_controllers[mod_controller.device] and
                dict_controllers[mod_controller.device]['measurements_variable_amount']):

            measurements = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == form_mod.function_id.data)

            if measurements.count() != form_mod.num_channels.data:
                # 측정값/채널 삭제
                if form_mod.num_channels.data < measurements.count():
                    for index, each_channel in enumerate(measurements.all()):
                        if index + 1 >= measurements.count():
                            delete_entry_with_id(DeviceMeasurements,
                                                 each_channel.unique_id)

                    if ('channel_quantity_same_as_measurements' in dict_controllers[mod_controller.device] and
                            dict_controllers[mod_controller.device]["channel_quantity_same_as_measurements"]):
                        if form_mod.num_channels.data < len(channels):
                            for index, each_channel in enumerate(channels):
                                if index + 1 >= len(channels):
                                    delete_entry_with_id(FunctionChannel,
                                                         each_channel.unique_id)

                # 측정값/채널 추가
                elif form_mod.num_channels.data > measurements.count():
                    start_number = measurements.count()
                    for index in range(start_number, form_mod.num_channels.data):
                        new_measurement = DeviceMeasurements()
                        new_measurement.name = ""
                        new_measurement.device_id = mod_controller.unique_id
                        new_measurement.measurement = ""
                        new_measurement.unit = ""
                        new_measurement.channel = index
                        new_measurement.save()

                        if ('channel_quantity_same_as_measurements' in dict_controllers[mod_controller.device] and
                                dict_controllers[mod_controller.device]["channel_quantity_same_as_measurements"]):
                            new_channel = FunctionChannel()
                            new_channel.name = ""
                            new_channel.function_id = mod_controller.unique_id
                            new_channel.channel = index

                            messages["error"], custom_options = custom_channel_options_return_json(
                                messages["error"], dict_controllers, request_form,
                                mod_controller.unique_id, index,
                                device=mod_controller.device, use_defaults=True)
                            new_channel.custom_options = custom_options

                            new_channel.save()

        # 저장 전 사용자 지정 옵션 파싱
        try:
            custom_options_dict_presave = json.loads(mod_controller.custom_options)
        except:
            logger.error("잘못된 JSON 형식")
            custom_options_dict_presave = {}

        custom_options_channels_dict_presave = {}
        for each_channel in channels:
            if each_channel.custom_options and each_channel.custom_options != "{}":
                custom_options_channels_dict_presave[each_channel.channel] = json.loads(
                    each_channel.custom_options)
            else:
                custom_options_channels_dict_presave[each_channel.channel] = {}

        # 저장 후 함수 및 채널에 대한 사용자 지정 옵션 파싱
        messages["error"], custom_options_json_postsave = custom_options_return_json(
            messages["error"], dict_controllers,
            request_form=request_form,
            mod_dev=mod_controller,
            device=mod_controller.device,
            use_defaults=True,
            custom_options=custom_options_dict_presave)
        custom_options_dict_postsave = json.loads(custom_options_json_postsave)
        # 지도 마커 값 저장(커스텀 컨트롤러는 별도 컬럼이 없으므로 custom_options에 보관)
        marker_icon = request_form.get('marker_icon')
        marker_color = request_form.get('marker_color')
        marker_size = request_form.get('marker_size')
        if marker_icon not in [None, '']:
            custom_options_dict_postsave['marker_icon'] = marker_icon
        if marker_color not in [None, '']:
            custom_options_dict_postsave['marker_color'] = marker_color
        if marker_size not in [None, '']:
            try:
                custom_options_dict_postsave['marker_size'] = int(marker_size)
            except Exception:
                pass

        custom_options_channels_dict_postsave = {}
        for each_channel in channels:
            messages["error"], custom_options_channels_json_postsave_tmp = custom_channel_options_return_json(
                messages["error"], dict_controllers, request_form,
                form_mod.function_id.data, each_channel.channel,
                device=mod_controller.device, use_defaults=False)
            custom_options_channels_dict_postsave[each_channel.channel] = json.loads(
                custom_options_channels_json_postsave_tmp)

        if 'execute_at_modification' in dict_controllers[mod_controller.device]:
            # 데이터베이스에 저장하기 전에 모듈에 사용자 지정 옵션 전달
            (messages,
             mod_controller,
             custom_options_dict,
             custom_options_channels_dict,
             refresh_page) = dict_controllers[mod_controller.device]['execute_at_modification'](
                messages,
                mod_controller,
                request_form,
                custom_options_dict_presave,
                custom_options_channels_dict_presave,
                custom_options_dict_postsave,
                custom_options_channels_dict_postsave)
            custom_options = json.dumps(custom_options_dict)  # 딕셔너리를 JSON 문자열로 변환
            custom_channel_options = custom_options_channels_dict
            if refresh_page:
                page_refresh = True
        else:
            # 모듈에 사용자 지정 옵션 전달하지 않음
            custom_options = json.dumps(custom_options_dict_postsave)
            custom_channel_options = custom_options_channels_dict_postsave

        # 최종적으로 함수 및 채널의 사용자 지정 옵션 저장
        mod_controller.custom_options = custom_options
        for each_channel in channels:
            if 'name' in custom_channel_options[each_channel.channel]:
                each_channel.name = custom_channel_options[each_channel.channel]['name']
            each_channel.custom_options = json.dumps(custom_channel_options[each_channel.channel])

        if not messages["error"]:
            db.session.commit()
            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['modify']['title'],
                controller=TRANSLATIONS['controller']['title']))

    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def controller_del(cond_id):
    """사용자 정의 컨트롤러 삭제."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    cond = CustomController.query.filter(
        CustomController.unique_id == cond_id).first()
    map_config_id = cond.map_config_id if cond else None

    # 활성화된 경우 컨트롤러 비활성화
    if cond.is_activated:
        controller_deactivate(cond_id)

    try:
        if not messages["error"]:
            device_measurements = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == cond_id).all()
            for each_measurement in device_measurements:
                delete_entry_with_id(
                    DeviceMeasurements,
                    each_measurement.unique_id,
                    flash_message=False)

            delete_entry_with_id(
                CustomController, cond_id, flash_message=False)
            if map_config_id:
                delete_map_config(map_config_id)

            channels = FunctionChannel.query.filter(
                FunctionChannel.function_id == cond_id).all()
            for each_channel in channels:
                delete_entry_with_id(
                    FunctionChannel,
                    each_channel.unique_id,
                    flash_message=False)

            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['delete']['title'],
                controller=TRANSLATIONS['controller']['title']))

            try:
                file_path = os.path.join(
                    PATH_PYTHON_CODE_USER, 'conditional_{}.py'.format(
                        cond.unique_id))
                os.remove(file_path)
            except:
                pass

            db.session.commit()
    except sqlalchemy.exc.OperationalError as except_msg:
        messages["error"].append(str(except_msg))
    except sqlalchemy.exc.IntegrityError as except_msg:
        messages["error"].append(str(except_msg))
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def controller_activate(controller_id):
    """사용자 정의 컨트롤러 활성화."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "period_status": None
    }

    function = CustomController.query.filter(
        CustomController.unique_id == controller_id).first()

    if not function:
        messages["error"].append("사용자 정의 컨트롤러를 찾을 수 없습니다.")
    else:
        dict_controllers = parse_function_information()
        custom_options_values_controllers = parse_custom_option_values(
            CustomController.query.all(), dict_controller=dict_controllers)

        if (controller_id in custom_options_values_controllers and
                'period_status' in custom_options_values_controllers[controller_id]):
            messages["period_status"] = custom_options_values_controllers[controller_id]['period_status']

        if ('enable_channel_unit_select' in dict_controllers[function.device] and
                dict_controllers[function.device]['enable_channel_unit_select']):
            device_measurements = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == controller_id).all()
            for each_measure in device_measurements:
                if (None in [each_measure.measurement, each_measure.unit] or
                        "" in [each_measure.measurement, each_measure.unit]):
                    messages["error"].append(
                        "측정값 CH{} ({})의 측정값/단위가 설정되지 않았습니다. 모든 측정값에 대해 측정값과 단위를 설정해야 합니다.".format(
                            each_measure.channel, each_measure.name))

    messages = controller_activate_deactivate(
        messages, 'activate', 'Function', controller_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['activate']['title'],
            controller=TRANSLATIONS['controller']['title']))

    return messages


def controller_deactivate(controller_id):
    """사용자 정의 컨트롤러 비활성화."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    messages = controller_activate_deactivate(
        messages, 'deactivate', 'Function', controller_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['deactivate']['title'],
            controller=TRANSLATIONS['controller']['title']))

    return messages
