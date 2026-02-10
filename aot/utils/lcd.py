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

from aot.databases.models import Conversion
from aot.databases.models import Function
from aot.databases.models import Input
from aot.databases.models import Output
from aot.databases.models import PID
from aot.databases.models import Unit
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.system_pi import add_custom_units
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

logger = logging.getLogger("aot.utils.lcd")


def format_measurement_line(device_id, measure_id, val_rounded, lcd_x_characters, display_unit=True, label=None):
    unit_display, unit_length, name = get_measurement_info(device_id, measure_id)

    if unit_length:
        value_length = len(str(val_rounded))
        name_length = lcd_x_characters - value_length - unit_length - 2
        if label:
            name_cropped = label.ljust(name_length)[:name_length]
        else:
            name_cropped = name.ljust(name_length)[:name_length]
        if display_unit:
            line_display = '{name} {value} {unit}'.format(
                name=name_cropped,
                value=val_rounded,
                unit=unit_display.replace('°', u''))
        else:
            line_display = '{name} {value}'.format(
                name=name_cropped,
                value=val_rounded)
    else:
        value_length = len(str(val_rounded))
        name_length = lcd_x_characters - value_length - 1
        name_cropped = name[:name_length]
        if name_cropped:
            line_str = '{name} {value}'.format(
                name=name_cropped,
                value=val_rounded)
        else:
            line_str = val_rounded
        line_display = line_str

    return line_display

def get_measurement_info(device_id, measurement_id):
    unit_display = ""
    name = ""

    device_measurement = get_measurement(measurement_id)
    conversion = db_retrieve_table_daemon(
        Conversion, unique_id=device_measurement.conversion_id)
    channel, unit, measurement = return_measurement_info(
        device_measurement, conversion)

    dict_units = add_custom_units(
        db_retrieve_table_daemon(Unit, entry='all'))
    if unit in dict_units:
        unit_display = dict_units[unit]['unit']
    if unit_display:
        unit_length = len(unit_display.replace('°', u''))
    else:
        unit_length = 0

    controllers = [
        Output,
        PID,
        Input,
        Function
    ]
    for each_controller in controllers:
        controller_found = db_retrieve_table_daemon(
            each_controller, unique_id=device_id)
        if controller_found:
            name = controller_found.name
            break

    return unit_display, unit_length, name
