# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로,
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#  This software is a derivative work of the open-source Mycodo project (© Kyle T. Gabriel),
#  modified by AoT for use in its own smart agriculture systems.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015–2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  본 파일은 GNU General Public License, 버전 3 또는 그 이후 버전에 따라 배포됩니다.
#  This file is licensed under the GNU General Public License, version 3 or (at your option) any later version.
#
#  본 소프트웨어는 유용하게 사용될 수 있으리라는 기대 하에 배포되며,
#  상품성이나 특정 목적에의 적합성에 대한 어떠한 보증도 제공하지 않습니다.
#  This software is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
#  이 라이선스 사본은 함께 제공되어야 하며,
#  제공되지 않은 경우, 아래에서 확인할 수 있습니다:
#  You should have received a copy of the GNU General Public License
#  along with this software. If not, see <https://www.gnu.org/licenses/>.
#
#  --------------------------------------------------------------
#  원본 프로젝트 정보 / Original Project Info:
#
#  Project: Mycodo (https://github.com/kizniche/Mycodo)
#  Author:  Kyle T. Gabriel (https://kylegabriel.com)
#  License: GNU GPLv3
#
#  수정자 / Modified by:
#    - Organization: AoT (Agriculture of Things)
#    - Contact: aot.inc.kr@gmail.com
#
#  리포맷 날짜 / Reformatted: 2025-04-21
#  --------------------------------------------------------------
import logging
import os

from aot.config import PATH_FUNCTIONS
from aot.config import PATH_FUNCTIONS_CUSTOM
from aot.utils.modules import load_module_from_file

logger = logging.getLogger("aot.utils.functions")


from functools import lru_cache

@lru_cache(maxsize=4)
def parse_function_information(exclude_custom=False):
    """Parse function module information and return a dictionary of function IDs and metadata.

    @phase active
    @stability stable
    @dependency load_module_from_file
    """
    def dict_has_value(dict_inp, controller_cus, key):
        if (key in controller_cus.FUNCTION_INFORMATION and
                (controller_cus.FUNCTION_INFORMATION[key] or
                 controller_cus.FUNCTION_INFORMATION[key] == 0)):
            dict_inp[controller_cus.FUNCTION_INFORMATION['function_name_unique']][key] = \
                controller_cus.FUNCTION_INFORMATION[key]
        return dict_inp

    excluded_files = [
        '__init__.py', '__pycache__', 'base_function.py',
        'custom_functions', 'examples', 'scripts', 'tmp_functions'
    ]

    function_paths = [PATH_FUNCTIONS]

    if not exclude_custom:
        function_paths.append(PATH_FUNCTIONS_CUSTOM)

    dict_controllers = {}

    for each_path in function_paths:

        real_path = os.path.realpath(each_path)

        for each_file in os.listdir(real_path):
            if each_file in excluded_files:
                continue

            if each_file.startswith('._'):
                continue

            full_path = "{}/{}".format(real_path, each_file)
            function_custom, status = load_module_from_file(full_path, 'functions')

            if not function_custom or not hasattr(function_custom, 'FUNCTION_INFORMATION'):
                continue

            # Populate dictionary of function information
            if function_custom.FUNCTION_INFORMATION['function_name_unique'] in dict_controllers:
                logger.error(
                    "Error: Cannot add controller modules because it does not have a unique name: {name}".format(
                        name=function_custom.FUNCTION_INFORMATION['function_name_unique']))
            else:
                dict_controllers[function_custom.FUNCTION_INFORMATION['function_name_unique']] = {}

            dict_controllers[function_custom.FUNCTION_INFORMATION['function_name_unique']]['file_path'] = full_path

            dict_controllers = dict_has_value(dict_controllers, function_custom, 'function_name')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'function_name_short')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'function_manufacturer')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'measurements_dict')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'channels_dict')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'measurements_variable_amount')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'channel_quantity_same_as_measurements')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'enable_channel_unit_select')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'execute_at_creation')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'execute_at_modification')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'modify_settings_without_deactivating')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'function_status')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'camera_image')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'camera_video')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'camera_stream')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'message')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'options_enabled')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'options_disabled')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'dependencies_module')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'dependencies_message')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'function_actions')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'custom_options')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'custom_channel_options')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'custom_commands_message')
            dict_controllers = dict_has_value(dict_controllers, function_custom, 'custom_commands')

    return dict_controllers
