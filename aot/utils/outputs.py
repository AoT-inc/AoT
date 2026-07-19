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

from aot.config import PATH_OUTPUTS
from aot.config import PATH_OUTPUTS_CUSTOM
from aot.utils.modules import load_module_from_file

logger = logging.getLogger("aot.utils.outputs")


from functools import lru_cache

@lru_cache(maxsize=4)
def parse_output_information(exclude_custom=False):
    """Parse all output modules and return a dictionary of output IDs and their metadata.

    @phase active
    @stability stable
    @dependency load_module_from_file
    """
    def dict_has_value(dict_inp, output_cus, key, force_type=None):
        if (key in output_cus.OUTPUT_INFORMATION and
                (output_cus.OUTPUT_INFORMATION[key] is not None)):
            if force_type == 'list':
                if isinstance(output_cus.OUTPUT_INFORMATION[key], list):
                    dict_inp[output_cus.OUTPUT_INFORMATION['output_name_unique']][key] = \
                        output_cus.OUTPUT_INFORMATION[key]
                else:
                    dict_inp[output_cus.OUTPUT_INFORMATION['output_name_unique']][key] = \
                        [output_cus.OUTPUT_INFORMATION[key]]
            else:
                dict_inp[output_cus.OUTPUT_INFORMATION['output_name_unique']][key] = \
                    output_cus.OUTPUT_INFORMATION[key]
        return dict_inp

    excluded_files = [
        '__init__.py', '__pycache__', 'base_output.py', 'custom_outputs',
        'examples', 'scripts', 'tmp_outputs'
    ]

    output_paths = [PATH_OUTPUTS]

    if not exclude_custom:
        output_paths.append(PATH_OUTPUTS_CUSTOM)

    dict_outputs = {}

    for each_path in output_paths:

        real_path = os.path.realpath(each_path)

        for each_file in os.listdir(real_path):
            if each_file in excluded_files:
                continue

            if each_file.startswith('._'):
                continue

            full_path = "{}/{}".format(real_path, each_file)
            output_custom, status = load_module_from_file(full_path, 'outputs')

            if not output_custom or not hasattr(output_custom, 'OUTPUT_INFORMATION'):
                continue

            # Populate dictionary of output information
            if output_custom.OUTPUT_INFORMATION['output_name_unique'] in dict_outputs:
                logger.error("Error: Cannot add output modules because it does not have a unique name: {name}".format(
                    name=output_custom.OUTPUT_INFORMATION['output_name_unique']))
            else:
                dict_outputs[output_custom.OUTPUT_INFORMATION['output_name_unique']] = {}

            dict_outputs[output_custom.OUTPUT_INFORMATION['output_name_unique']]['file_path'] = full_path

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'output_name')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'output_manufacturer')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'output_library')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'measurements_dict')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'channels_dict')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'on_state_internally_handled')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'no_run')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'output_types')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'execute_at_creation')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'execute_at_modification')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'message')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'url_datasheet', force_type='list')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'url_manufacturer', force_type='list')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'url_product_purchase', force_type='list')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'url_additional', force_type='list')

            # Dependencies
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'dependencies_module')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'dependencies_message')

            # Interface
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'interfaces')

            # Nonstandard (I2C, UART, etc.) location
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'location')

            # I2C
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'i2c_location')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'i2c_address_editable')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'i2c_address_default')

            # FTDI
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'ftdi_location')

            # UART
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'uart_location')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'uart_baud_rate')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'pin_cs')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'pin_miso')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'pin_mosi')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'pin_clock')

            # Bluetooth (BT)
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'bt_location')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'bt_adapter')

            # Which form options to display and whether each option is enabled
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'options_enabled')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'options_disabled')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_options_message')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_options')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_channel_options_message')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_channel_options')

            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_commands_message')
            dict_outputs = dict_has_value(dict_outputs, output_custom, 'custom_commands')

    return dict_outputs


def outputs_on_off():
    outputs = []
    for each_output_type, output_data in parse_output_information().items():
        if 'output_types' in output_data and 'on_off' in output_data['output_types']:
            outputs.append(each_output_type)
    return outputs


def outputs_pwm():
    outputs = []
    for each_output_type, output_data in parse_output_information().items():
        if 'output_types' in output_data and 'pwm' in output_data['output_types']:
            outputs.append(each_output_type)
    return outputs


def outputs_value():
    outputs = []
    for each_output_type, output_data in parse_output_information().items():
        if 'output_types' in output_data and 'value' in output_data['output_types']:
            outputs.append(each_output_type)
    return outputs


def outputs_volume():
    outputs = []
    for each_output_type, output_data in parse_output_information().items():
        if 'output_types' in output_data and 'volume' in output_data['output_types']:
            outputs.append(each_output_type)
    return outputs


def output_types():
    return {
        'on_off': outputs_on_off(),
        'pwm': outputs_pwm(),
        'value': outputs_value(),
        'volume': outputs_volume()
    }
