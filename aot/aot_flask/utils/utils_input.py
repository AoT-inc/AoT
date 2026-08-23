# -*- coding: utf-8 -*-
import json
import logging
import os
import re
from datetime import datetime

import sqlalchemy
from flask import current_app
from flask import flash
from flask_babel import gettext
_ = gettext
from sqlalchemy import and_
from sqlalchemy import or_

from aot.config_translations import TRANSLATIONS
from aot.databases import clone_model
from aot.databases import set_uuid
from aot.databases.models import Actions
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import Tab
from aot.databases.models import InputChannel
from aot.databases.models import Misc
from aot.databases.models import PID
from aot.aot_client import DaemonControl
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_measurement
from aot.aot_flask.utils.utils_general import controller_activate_deactivate
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.aot_flask.utils.utils_general import sync_geo_device_name
from aot.utils.inputs import parse_input_information
from aot.utils.system_pi import parse_custom_option_values
from aot.aot_flask.utils.utils_map_config import (
    ensure_map_config,
    clone_map_config,
)

logger = logging.getLogger(__name__)

#
# Input manipulation
#

def input_add(form_add, tab_id=None):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    # 그룹 스코프(A1b) — 만들어 넣을 **탭**으로 판정한다.
    #
    # 새 장치가 어느 탭에 들어가는지가 곧 누가 그것을 조작할 수 있는지다
    # (설계 §4-3). 스코프 밖 탭에 만들 수 있게 두면, 만들기만으로 남의
    # 영역에 장치를 밀어넣을 수 있다.
    from aot.aot_flask.access import scope
    if tab_id and not scope.can_operate('tab', tab_id):
        messages["error"].append(scope.deny_message())
        return messages, dep_name, list_unmet_deps, dep_message, None
    new_input_id = None
    list_unmet_deps = []
    dep_name = None
    dep_message = ''

    dict_inputs = parse_input_information()

    # only one comma should be in the input_type string
    if form_add.input_type.data.count(',') > 1:
        messages["error"].append(
            _("Invalid input module format. It seems that 'input_name_unique' or 'interfaces' contains a comma."))

    if form_add.input_type.data.count(',') == 1:
        input_name = form_add.input_type.data.split(',')[0]
        input_interface = form_add.input_type.data.split(',')[1]
    else:
        input_name = ''
        input_interface = ''
        messages["error"].append(_("Invalid input string (must be a comma-separated string)."))

    if not current_app.config['TESTING']:
        dep_unmet, _unused, dep_message = return_dependencies(input_name)
        if dep_unmet:
            messages["error"].append(
                f"{input_name} " + 
                _("has unmet dependencies. They must be installed before the input can be added."))

            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
                if each_dep[2] == 'pip-pypi':
                    dep_message += _("Python package %(package)s was not found because '%(module)s' could not be imported.") % {'package': each_dep[3], 'module': each_dep[0]}

            if input_name in dict_inputs:
                dep_name = dict_inputs[input_name]['input_name']
            else:
                messages["error"].append(f"Input not found: {input_name}")

            return messages, dep_name, list_unmet_deps, dep_message, None

    if form_add.validate():
        new_input = Input()
        new_input.device = input_name
        max_pos = db.session.query(db.func.max(Input.position_y)).scalar()
        new_input.position_y = (max_pos or 0) + 1

        if input_interface:
            new_input.interface = input_interface

        new_input.i2c_bus = 1

        if 'input_name_short' in dict_inputs[input_name]:
            new_input.name = str(dict_inputs[input_name]['input_name_short'])
        elif 'input_name' in dict_inputs[input_name]:
            new_input.name = str(dict_inputs[input_name]['input_name'])
        else:
            new_input.name = 'Name'

        # Default map location from Misc
        try:
            misc = Misc.query.first()
            if misc:
                new_input.latitude = misc.map_latitude
                new_input.longitude = misc.map_longitude
                if not new_input.latitude and not new_input.longitude and misc.timezone:
                    new_input.timezone = misc.timezone
        except Exception:
            pass

        #
        # Set default values for new input being added
        #

        # input add options
        if input_name in dict_inputs:
            def dict_has_value(key):
                if (key in dict_inputs[input_name] and
                        (dict_inputs[input_name][key] or dict_inputs[input_name][key] == 0)):
                    return True

            #
            # Interfacing options
            #

            if input_interface == 'I2C':
                if dict_has_value('i2c_location'):
                    new_input.i2c_location = dict_inputs[input_name]['i2c_location'][0]  # First entry in list

            if input_interface == 'FTDI':
                if dict_has_value('ftdi_location'):
                    new_input.ftdi_location = dict_inputs[input_name]['ftdi_location']

            if input_interface == 'UART':
                if dict_has_value('uart_location'):
                    new_input.uart_location = dict_inputs[input_name]['uart_location']

            # UART options
            if dict_has_value('uart_baud_rate'):
                new_input.baud_rate = dict_inputs[input_name]['uart_baud_rate']
            if dict_has_value('pin_cs'):
                new_input.pin_cs = dict_inputs[input_name]['pin_cs']
            if dict_has_value('pin_miso'):
                new_input.pin_miso = dict_inputs[input_name]['pin_miso']
            if dict_has_value('pin_mosi'):
                new_input.pin_mosi = dict_inputs[input_name]['pin_mosi']
            if dict_has_value('pin_clock'):
                new_input.pin_clock = dict_inputs[input_name]['pin_clock']

            # Bluetooth (BT) options
            elif input_interface == 'BT':
                if dict_has_value('bt_location'):
                    if not re.match("[0-9a-fA-F]{2}([:]?)[0-9a-fA-F]{2}(\\1[0-9a-fA-F]{2}){4}$",
                                    dict_inputs[input_name]['bt_location']):
                        messages["error"].append("Please specify device MAC-Address in format AA:BB:CC:DD:EE:FF")
                    else:
                        new_input.location = dict_inputs[input_name]['bt_location']
                if dict_has_value('bt_adapter'):
                    new_input.bt_adapter = dict_inputs[input_name]['bt_adapter']

            # GPIO options
            elif input_interface == 'GPIO':
                if dict_has_value('gpio_location'):
                    new_input.gpio_location = dict_inputs[input_name]['gpio_location']

            # Custom location location
            elif dict_has_value('location'):
                new_input.location = dict_inputs[input_name]['location']['options'][0][0]  # First entry in list

            #
            # General options
            #

            if dict_has_value('period'):
                new_input.period = dict_inputs[input_name]['period']

            # Server Ping options
            if dict_has_value('times_check'):
                new_input.times_check = dict_inputs[input_name]['times_check']
            if dict_has_value('deadline'):
                new_input.deadline = dict_inputs[input_name]['deadline']
            if dict_has_value('port'):
                new_input.port = dict_inputs[input_name]['port']

            # Signal options
            if dict_has_value('weighting'):
                new_input.weighting = dict_inputs[input_name]['weighting']
            if dict_has_value('sample_time'):
                new_input.sample_time = dict_inputs[input_name]['sample_time']

            # Analog-to-digital converter options
            if dict_has_value('adc_gain'):
                if len(dict_inputs[input_name]['adc_gain']) == 1:
                    new_input.adc_gain = dict_inputs[input_name]['adc_gain'][0]
                elif len(dict_inputs[input_name]['adc_gain']) > 1:
                    new_input.adc_gain = dict_inputs[input_name]['adc_gain'][0][0]
            if dict_has_value('adc_resolution'):
                if len(dict_inputs[input_name]['adc_resolution']) == 1:
                    new_input.adc_resolution = dict_inputs[input_name]['adc_resolution'][0]
                elif len(dict_inputs[input_name]['adc_resolution']) > 1:
                    new_input.adc_resolution = dict_inputs[input_name]['adc_resolution'][0][0]
            if dict_has_value('adc_sample_speed'):
                if len(dict_inputs[input_name]['adc_sample_speed']) == 1:
                    new_input.adc_sample_speed = dict_inputs[input_name]['adc_sample_speed'][0]
                elif len(dict_inputs[input_name]['adc_sample_speed']) > 1:
                    new_input.adc_sample_speed = dict_inputs[input_name]['adc_sample_speed'][0][0]

            # Linux command
            if dict_has_value('cmd_command'):
                new_input.cmd_command = dict_inputs[input_name]['cmd_command']

            # Misc options
            if dict_has_value('resolution'):
                if len(dict_inputs[input_name]['resolution']) == 1:
                    new_input.resolution = dict_inputs[input_name]['resolution'][0]
                elif len(dict_inputs[input_name]['resolution']) > 1:
                    new_input.resolution = dict_inputs[input_name]['resolution'][0][0]
            if dict_has_value('resolution_2'):
                if len(dict_inputs[input_name]['resolution_2']) == 1:
                    new_input.resolution_2 = dict_inputs[input_name]['resolution_2'][0]
                elif len(dict_inputs[input_name]['resolution_2']) > 1:
                    new_input.resolution_2 = dict_inputs[input_name]['resolution_2'][0][0]
            if dict_has_value('sensitivity'):
                if len(dict_inputs[input_name]['sensitivity']) == 1:
                    new_input.sensitivity = dict_inputs[input_name]['sensitivity'][0]
                elif len(dict_inputs[input_name]['sensitivity']) > 1:
                    new_input.sensitivity = dict_inputs[input_name]['sensitivity'][0][0]
            if dict_has_value('thermocouple_type'):
                if len(dict_inputs[input_name]['thermocouple_type']) == 1:
                    new_input.thermocouple_type = dict_inputs[input_name]['thermocouple_type'][0]
                elif len(dict_inputs[input_name]['thermocouple_type']) > 1:
                    new_input.thermocouple_type = dict_inputs[input_name]['thermocouple_type'][0][0]
            if dict_has_value('sht_voltage'):
                if len(dict_inputs[input_name]['sht_voltage']) == 1:
                    new_input.sht_voltage = dict_inputs[input_name]['sht_voltage'][0]
                elif len(dict_inputs[input_name]['sht_voltage']) > 1:
                    new_input.sht_voltage = dict_inputs[input_name]['sht_voltage'][0][0]
            if dict_has_value('ref_ohm'):
                new_input.ref_ohm = dict_inputs[input_name]['ref_ohm']

        #
        # Custom Options
        #

        # Generate string to save from custom options
        messages["error"], custom_options = custom_options_return_json(
            messages["error"], dict_inputs, device=input_name, use_defaults=True)
        new_input.custom_options = custom_options

        new_input.unique_id = set_uuid()

        # Assign tab_id
        if tab_id:
            new_input.tab_id = tab_id

        if ('execute_at_creation' in dict_inputs[new_input.device] and
                not current_app.config['TESTING']):
            messages["error"], new_input = dict_inputs[new_input.device]['execute_at_creation'](
                messages["error"], new_input, dict_inputs[new_input.device])

        try:
            # [P1] 전용 지도 자동 생성 폐지 — 배치 시 지도에 속한다(원칙 2·4).

            if not messages["error"]:
                new_input.save()
                new_input_id = new_input.unique_id

                # Create measurements and channels
                messages = check_input_channels_exist(
                    dict_inputs, new_input.device, new_input.unique_id, messages)

                messages["success"].append(
                    f"{TRANSLATIONS['add']['title']} {TRANSLATIONS['input']['title']}")
        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(except_msg)
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(except_msg)

    else:
        for field, errors in form_add.errors.items():
            for error in errors:
                messages["error"].append(
                    gettext("Error in the %(field)s field - %(err)s",
                            field=getattr(form_add, field).label.text,
                            err=error))

    return messages, dep_name, list_unmet_deps, dep_message, new_input_id


def input_duplicate(form_mod):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    # 그룹 스코프(A1b) — **원본**으로 판정한다. 복제는 그 장치의 설정을
    # 통째로 읽어 새 행을 만드는 일이라, 원본을 조작할 수 없는 사람이
    # 복제할 수 있으면 스코프가 복제 한 번으로 뚫린다.
    from aot.aot_flask.access import scope
    if not scope.can_operate_device(form_mod.input_id.data):
        messages["error"].append(scope.deny_message())
        return messages, None

    source_input = Input.query.filter(
        Input.unique_id == form_mod.input_id.data).first()

    if not source_input:
        return None, None

    # Duplicate dashboard with new unique_id and name. Force position_y to
    # max+1 so the clone lands at the bottom of the grid; otherwise it
    # inherits the source's position_y and causes overlap + tied ORDER BY.
    max_pos = db.session.query(db.func.max(Input.position_y)).scalar()
    new_input = clone_model(
        source_input, unique_id=set_uuid(),
        name=f"Copy of {source_input.name}",
        position_y=(max_pos or 0) + 1)

    duplicated_input = Input.query.filter(
        Input.unique_id == new_input.unique_id).first()
    if duplicated_input:
        # [P1] 복제본은 미배치로 시작한다 — 지도를 복제해 붙이지 않는다.
        # 원본이 공유 디자인 지도에 배치돼 있으면 그 도형 전체가 숨은
        # 사설 지도로 복사되던 경로이기도 했다(원칙 1·2).
        duplicated_input.is_activated = False
        duplicated_input.save()

        dev_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == form_mod.input_id.data).all()
        for each_dev in dev_measurements:
            clone_model(each_dev, unique_id=set_uuid(), device_id=duplicated_input.unique_id)

        dev_channels = InputChannel.query.filter(
            InputChannel.input_id == form_mod.input_id.data).all()
        for each_dev in dev_channels:
            clone_model(each_dev, unique_id=set_uuid(), input_id=duplicated_input.unique_id)

    messages["success"].append(
        f"{TRANSLATIONS['duplicate']['title']} {TRANSLATIONS['input']['title']}")

    return messages, new_input.unique_id


def input_mod(form_mod, request_form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None,
        "return_text": []
    }

    # 그룹 스코프(A1b) — 대상이 정해진 **뒤에** 묻는다.
    #
    # 역할 게이트는 submit 핸들러 맨 위에 있어 어떤 장치인지 모른 채 통과한다
    # (설계 §1-A 표). 그래서 여기서 한 번 더 묻는다 — 옮기지 않고 여기에
    # 더하는 이유는, 옮기다 분기를 하나 빠뜨리면 **통과하는 게이트**가 되기
    # 때문이다(막혔다고 믿는 상태가 가장 나쁘다).
    from aot.aot_flask.access import scope
    if not scope.can_operate_device(form_mod.input_id.data):
        messages["error"].append(scope.deny_message())
        return messages, False
    page_refresh = False

    dict_inputs = parse_input_information()

    try:
        input_id = form_mod.input_id.data
        logger.debug(f"input_mod called with input_id: {input_id}")
        
        if not input_id:
            logger.error("input_mod called with input_id=None. Form data may be corrupted. Please refresh the page.")
            messages["error"].append("Input ID is missing. Please refresh the page and try again.")
            return messages, page_refresh
        
        mod_input = Input.query.filter(
            Input.unique_id == input_id).first()

        if not mod_input:
            logger.error(f"Input not found for ID: {input_id}")
            messages["error"].append(f"Input not found (ID: {input_id})")
            return messages, page_refresh

        if mod_input.is_activated:
            messages["error"].append(gettext(
                "Deactivate controller before modifying its settings"))

        if (mod_input.device == 'AM2315' and
                form_mod.period.data < 7):
            messages["error"].append(gettext(
                "Choose a Read Period equal to or greater than 7. The "
                "AM2315 may become unresponsive if the period is "
                "below 7."))

        if (form_mod.period.data and
                form_mod.pre_output_duration.data and
                form_mod.pre_output_id.data and
                form_mod.period.data < form_mod.pre_output_duration.data):
            messages["error"].append(gettext(
                "The Read Period cannot be less than the Pre Output Duration"))

        if (form_mod.uart_location.data and
                not os.path.exists(form_mod.uart_location.data)):
            messages["warning"].append(gettext(
                "Invalid device or improper permissions to read device"))

        if ('options_enabled' in dict_inputs[mod_input.device] and
                'gpio_location' in dict_inputs[mod_input.device]['options_enabled'] and
                form_mod.gpio_location.data is None):
            messages["error"].append(gettext("Pin (GPIO) must be set"))

        if form_mod.name.data not in [None, '']:
            mod_input.name = form_mod.name.data
            messages["name"] = form_mod.name.data

        new_tab_id = request_form.get('tab_id')
        if new_tab_id and new_tab_id != mod_input.tab_id:
            if Tab.query.filter(Tab.unique_id == new_tab_id).first():
                mod_input.tab_id = new_tab_id
                messages["tab_id"] = new_tab_id

        # Only attempt to change the ID if a new value is provided
        if form_mod.unique_id.data:
            if mod_input.unique_id != form_mod.unique_id.data:
                test_unique_id = Input.query.filter(Input.unique_id == form_mod.unique_id.data).first()
                if test_unique_id:
                    messages["error"].append(
                        f"Input ID must be unique. "
                        f"ID already exists: '{form_mod.unique_id.data}'")
                else:
                    mod_input.unique_id = form_mod.unique_id.data

        if form_mod.location.data:
            mod_input.location = form_mod.location.data

        lat_val = form_mod.latitude.data
        if lat_val in [None, '']:
            raw_lats = request_form.getlist('latitude')
            for val in raw_lats:
                if val and val not in ['None', '']:
                    lat_val = val
                    break

        lng_val = form_mod.longitude.data
        if lng_val in [None, '']:
            raw_lngs = request_form.getlist('longitude')
            for val in raw_lngs:
                if val and val not in ['None', '']:
                    lng_val = val
                    break
            
        if lat_val not in [None, ''] and lng_val not in [None, '']:
            mod_input.latitude = float(lat_val)
            mod_input.longitude = float(lng_val)
            mod_input.location_updated_utc = datetime.utcnow()
        elif (lat_val in [None, '']) and (lng_val in [None, '']):
            # Leave existing coords untouched to avoid unintended clearing
            pass
        else:
            messages["warning"].append(gettext("Latitude and longitude must be entered together."))
        if form_mod.location_source.data:
            mod_input.location_source = form_mod.location_source.data
        if ('marker_icon' in request_form) and hasattr(form_mod, 'marker_icon') and form_mod.marker_icon.data not in [None, '', 'None', 'null']:
            mod_input.marker_icon = form_mod.marker_icon.data
        if ('marker_color' in request_form) and hasattr(form_mod, 'marker_color') and form_mod.marker_color.data not in [None, '', 'None', 'null']:
            mod_input.marker_color = form_mod.marker_color.data
        if ('marker_size' in request_form) and hasattr(form_mod, 'marker_size') and form_mod.marker_size.data not in [None, '', 'None', 'null']:
            try:
                mod_input.marker_size = int(form_mod.marker_size.data)
            except Exception:
                pass
        if form_mod.i2c_location.data:
            mod_input.i2c_location = form_mod.i2c_location.data
        if form_mod.ftdi_location.data:
            mod_input.ftdi_location = form_mod.ftdi_location.data
        if form_mod.uart_location.data:
            mod_input.uart_location = form_mod.uart_location.data
        if form_mod.gpio_location.data and form_mod.gpio_location.data is not None:
            mod_input.gpio_location = form_mod.gpio_location.data

        if form_mod.power_output_id.data:
            mod_input.power_output_id = form_mod.power_output_id.data
        else:
            mod_input.power_output_id = None

        if form_mod.pre_output_id.data:
            mod_input.pre_output_id = form_mod.pre_output_id.data
        else:
            mod_input.pre_output_id = None

        # Enable/disable Channels
        measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == form_mod.input_id.data).all()
        if form_mod.measurements_enabled.data:
            for each_measurement in measurements:
                if each_measurement.unique_id in form_mod.measurements_enabled.data:
                    each_measurement.is_enabled = True
                else:
                    each_measurement.is_enabled = False

        mod_input.log_level_debug = form_mod.log_level_debug.data
        # 자동 VPD 를 이 입력에서 끈 경우, 서비스가 만든 VPD 채널을 정리한다.
        auto_vpd_turned_off = (bool(mod_input.auto_vpd_enabled) and
                               not form_mod.auto_vpd_enabled.data)
        mod_input.auto_vpd_enabled = form_mod.auto_vpd_enabled.data
        if auto_vpd_turned_off:
            for each_channel in DeviceMeasurements.query.filter(
                    DeviceMeasurements.device_id == mod_input.unique_id,
                    DeviceMeasurements.measurement_type == 'auto_vpd').all():
                delete_entry_with_id(
                    DeviceMeasurements,
                    each_channel.unique_id,
                    flash_message=False)
        mod_input.i2c_bus = form_mod.i2c_bus.data
        mod_input.baud_rate = form_mod.baud_rate.data
        mod_input.pre_output_duration = form_mod.pre_output_duration.data
        mod_input.pre_output_during_measure = form_mod.pre_output_during_measure.data

        if form_mod.period.data:
            mod_input.period = form_mod.period.data
        if form_mod.start_offset.data:
            mod_input.start_offset = form_mod.start_offset.data

        mod_input.resolution = form_mod.resolution.data
        mod_input.resolution_2 = form_mod.resolution_2.data
        mod_input.sensitivity = form_mod.sensitivity.data
        mod_input.calibrate_sensor_measure = form_mod.calibrate_sensor_measure.data
        mod_input.cmd_command = form_mod.cmd_command.data
        mod_input.thermocouple_type = form_mod.thermocouple_type.data
        mod_input.ref_ohm = form_mod.ref_ohm.data
        # Serial options
        mod_input.pin_clock = form_mod.pin_clock.data
        mod_input.pin_cs = form_mod.pin_cs.data
        mod_input.pin_mosi = form_mod.pin_mosi.data
        mod_input.pin_miso = form_mod.pin_miso.data
        # Bluetooth options
        mod_input.bt_adapter = form_mod.bt_adapter.data

        mod_input.adc_gain = form_mod.adc_gain.data
        mod_input.adc_resolution = form_mod.adc_resolution.data
        mod_input.adc_sample_speed = form_mod.adc_sample_speed.data

        # Switch options
        mod_input.switch_edge = form_mod.switch_edge.data
        mod_input.switch_bouncetime = form_mod.switch_bouncetime.data
        mod_input.switch_reset_period = form_mod.switch_reset_period.data
        # PWM and RPM options
        mod_input.weighting = form_mod.weighting.data
        mod_input.rpm_pulses_per_rev = form_mod.rpm_pulses_per_rev.data
        mod_input.sample_time = form_mod.sample_time.data
        # Server options
        mod_input.port = form_mod.port.data
        mod_input.times_check = form_mod.times_check.data
        mod_input.deadline = form_mod.deadline.data
        # SHT sensor options
        if form_mod.sht_voltage.data:
            mod_input.sht_voltage = form_mod.sht_voltage.data

        channels = InputChannel.query.filter(
            InputChannel.input_id == form_mod.input_id.data)

        # Ensure all required measurements and channels exist
        messages = check_input_channels_exist(
            dict_inputs, mod_input.device, mod_input.unique_id, messages)

        # Save Measurement settings
        messages, page_refresh = utils_measurement.measurement_mod_form(
            messages, page_refresh, request_form)

        # Add or delete channels for variable measurement Inputs
        if ('measurements_variable_amount' in dict_inputs[mod_input.device] and
                dict_inputs[mod_input.device]['measurements_variable_amount']):
            # 자동 VPD 서비스가 만든 채널(measurement_type='auto_vpd', 이 입력의
            # 마지막 채널 다음 번호에 위치)은 사용자 채널 수 재조정 대상에서 제외한다.
            # 포함하면 num_channels 비교가 어긋나 auto VPD 채널이 삭제되거나 사용자
            # 채널이 잘못 추가된다.
            measurements = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == form_mod.input_id.data).filter(
                or_(DeviceMeasurements.measurement_type.is_(None),
                    DeviceMeasurements.measurement_type != 'auto_vpd'))

            if measurements.count() != form_mod.num_channels.data:
                page_refresh = True

                # Delete measurements/channels
                if form_mod.num_channels.data < measurements.count():
                    for index, each_channel in enumerate(measurements.all()):
                        if index + 1 > form_mod.num_channels.data:
                            delete_entry_with_id(
                                DeviceMeasurements,
                                each_channel.unique_id,
                                flash_message=False)

                    if ('channel_quantity_same_as_measurements' in dict_inputs[mod_input.device] and
                            dict_inputs[mod_input.device]["channel_quantity_same_as_measurements"]):
                        if form_mod.num_channels.data < channels.count():
                            for index, each_channel in enumerate(channels.all()):
                                if index + 1 > form_mod.num_channels.data:
                                    delete_entry_with_id(
                                        InputChannel,
                                        each_channel.unique_id,
                                        flash_message=False)

                # Add measurements/channels
                elif form_mod.num_channels.data > measurements.count():
                    start_number = measurements.count()

                    # 채널 번호는 한 번 부여되면 절대 바꾸지 않는다(InfluxDB 는 채널
                    # 단위로 기록되므로, 번호가 바뀌면 같은 측정의 신·구 이력이 서로
                    # 다른 채널로 갈라져 뒤섞인다). 자동 VPD 채널이 이미 이 번호대를
                    # 점유하고 있다면 그 채널은 그대로 두고, 새로 추가되는 채널이
                    # 비어 있는 다음 번호를 찾아 피해간다.
                    used_channels = {
                        r.channel for r in DeviceMeasurements.query.filter(
                            DeviceMeasurements.device_id == form_mod.input_id.data).all()
                        if r.channel is not None}

                    needed = form_mod.num_channels.data - start_number
                    added = 0
                    candidate = start_number
                    while added < needed:
                        if candidate in used_channels:
                            candidate += 1
                            continue

                        new_measurement = DeviceMeasurements()
                        new_measurement.name = ""
                        new_measurement.device_id = mod_input.unique_id
                        new_measurement.measurement = ""
                        new_measurement.unit = ""
                        new_measurement.channel = candidate
                        new_measurement.save()
                        used_channels.add(candidate)

                        if ('channel_quantity_same_as_measurements' in dict_inputs[mod_input.device] and
                                dict_inputs[mod_input.device]["channel_quantity_same_as_measurements"]):
                            new_channel = InputChannel()
                            new_channel.name = ""
                            new_channel.input_id = mod_input.unique_id
                            new_channel.channel = candidate

                            messages["error"], custom_options = custom_channel_options_return_json(
                                messages["error"], dict_inputs, request_form,
                                mod_input.unique_id, candidate,
                                device=mod_input.device, use_defaults=True)
                            new_channel.custom_options = custom_options

                            new_channel.save()

                        added += 1
                        candidate += 1

        # Parse pre-save custom options for output device and its channels
        try:
            custom_options_dict_presave = json.loads(mod_input.custom_options)
        except:
            logger.error("Malformed JSON")
            custom_options_dict_presave = {}

        custom_options_channels_dict_presave = {}
        for each_channel in channels.all():
            if each_channel.custom_options and each_channel.custom_options != "{}":
                custom_options_channels_dict_presave[each_channel.channel] = json.loads(
                    each_channel.custom_options)
            else:
                custom_options_channels_dict_presave[each_channel.channel] = {}

        # Parse post-save custom options for output device and its channels
        messages["error"], custom_options_json_postsave = custom_options_return_json(
            messages["error"], dict_inputs, request_form,
            mod_dev=mod_input,
            device=mod_input.device,
            custom_options=custom_options_dict_presave)
        custom_options_dict_postsave = json.loads(custom_options_json_postsave)

        custom_options_channels_dict_postsave = {}
        for each_channel in channels.all():
            messages["error"], custom_options_channels_json_postsave_tmp = custom_channel_options_return_json(
                messages["error"], dict_inputs, request_form,
                form_mod.input_id.data, each_channel.channel,
                device=mod_input.device, use_defaults=False,
                custom_options=custom_options_channels_dict_presave.get(each_channel.channel, {}))
            custom_options_channels_dict_postsave[each_channel.channel] = json.loads(
                custom_options_channels_json_postsave_tmp)

        if 'execute_at_modification' in dict_inputs[mod_input.device]:
            # pass custom options to module prior to saving to database
            (messages,
             mod_input,
             custom_options_dict,
             custom_options_channels_dict) = dict_inputs[mod_input.device]['execute_at_modification'](
                messages,
                mod_input,
                request_form,
                custom_options_dict_presave,
                custom_options_channels_dict_presave,
                custom_options_dict_postsave,
                custom_options_channels_dict_postsave)
            custom_options = json.dumps(custom_options_dict)  # Convert from dict to JSON string
            custom_channel_options = custom_options_channels_dict
            if custom_options_dict_presave != custom_options_dict_postsave:
                logger.warning(f" [Input Mod] Custom options changed for {mod_input.device}. Forcing refresh.")
                page_refresh = True
            
            if mod_input.device == 'SATELLITE_ANALYSIS':
                logger.warning(" [Input Mod] Satellite Analysis saved. Ensuring refresh.")
                page_refresh = True
        else:
            # Don't pass custom options to module
            custom_options = json.dumps(custom_options_dict_postsave)
            custom_channel_options = custom_options_channels_dict_postsave

        # [Fix] Manually persist shape color options
        try:
            co_dict = json.loads(custom_options) if custom_options else {}
        except:
            co_dict = {}

        for shape_key in ['shape_on_color', 'shape_off_color', 'shape_border_color']:
            if shape_key in request_form:
                val = request_form.get(shape_key)
                if val:
                    co_dict[shape_key] = val
        
        custom_options = json.dumps(co_dict)

        # Finally, save custom options for both output and channels
        mod_input.custom_options = custom_options
        logger.warning(f" [Input Mod] Saving Input {mod_input.unique_id} ({mod_input.device}). Custom Options: {custom_options}")
        for each_channel in channels:
            # Use .get() to avoid KeyError if the channel was dynamically added and isn't in our pre-save dict
            chan_opts = custom_channel_options.get(each_channel.channel)
            if chan_opts:
                if 'name' in chan_opts:
                    each_channel.name = chan_opts['name']
                each_channel.custom_options = json.dumps(chan_opts)
            else:
                # If no options found, ensure it has at least an empty JSON object if none exists
                if not each_channel.custom_options:
                    each_channel.custom_options = "{}"

        if not messages["error"]:
            db.session.commit()
            messages["success"].append(
                f"{TRANSLATIONS['modify']['title']} {TRANSLATIONS['input']['title']}")
            if messages.get("name"):
                sync_geo_device_name(mod_input.unique_id, mod_input.name)

    except Exception as except_msg:
        logger.exception("input_mod")
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def input_del(input_id):
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
    if not scope.can_operate_device(input_id):
        messages["error"].append(scope.deny_message())
        return messages

    try:
        input_dev = Input.query.filter(
            Input.unique_id == input_id).first()
        map_config_id = input_dev.map_config_id if input_dev else None

        if input_dev.is_activated:
            # messages = input_deactivate_associated_controllers(
            #     messages, input_id)
            messages = controller_activate_deactivate(
                messages, 'deactivate', 'Input', input_id)

        actions = Actions.query.filter(
            Actions.function_id == input_id).all()
        for each_action in actions:
            delete_entry_with_id(
                Actions, each_action.unique_id, flash_message=False)

        device_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == input_id).all()
        for each_measurement in device_measurements:
            delete_entry_with_id(
                DeviceMeasurements,
                each_measurement.unique_id,
                flash_message=False)

        channels = InputChannel.query.filter(
            InputChannel.input_id == input_id).all()
        for each_channel in channels:
            delete_entry_with_id(
                InputChannel,
                each_channel.unique_id,
                flash_message=False)

        # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정
        # 슬롯으로 남는다(위치 마커만 예외). 삭제 경로 17곳이 전부
        # 이 게이트웨이를 지나간다.
        from aot.aot_flask.geo.device_binding import end_all_for_device
        end_all_for_device(input_id)
        delete_entry_with_id(Input, input_id, flash_message=False)
        # [P3] 원칙 1 — 지도는 장치의 소유물이 아니다. 장치를 지워도 지도는
        # 남는다. 과거 이 호출이 장치 삭제로 공유 디자인 지도를 통째로
        # 지웠다(임실군 62도형). 지도 삭제는 geo/design 에서 명시적으로만.


        from aot.utils.code_verification import delete_python_file
        delete_python_file('input', input_dev.unique_id)

        db.session.commit()
        messages["success"].append(
            f"{TRANSLATIONS['delete']['title']} {TRANSLATIONS['input']['title']}")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def input_activate(form_mod):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    dict_inputs = parse_input_information()
    input_id = form_mod.input_id.data
    input_dev = Input.query.filter(Input.unique_id == input_id).first()
    device_measurements = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id == input_dev.unique_id)

    custom_options_values_inputs = parse_custom_option_values(
        input_dev, dict_controller=dict_inputs)

    #
    # General Input checks
    #
    if not input_dev.period:
        messages["error"].append("Period must be set")

    if (input_dev.pre_output_id and
            len(input_dev.pre_output_id) > 1 and
            not input_dev.pre_output_duration):
        messages["error"].append("Pre Output Duration must be > 0 if Pre Output is enabled")

    if not device_measurements.filter(DeviceMeasurements.is_enabled.is_(True)).count():
        messages["error"].append("At least one measurement must be enabled")

    #
    # Check if required custom options are set
    #
    if 'custom_options' in dict_inputs[input_dev.device]:
        for each_option in dict_inputs[input_dev.device]['custom_options']:
            if 'id' not in each_option:
                continue

            if each_option['id'] not in custom_options_values_inputs[input_dev.unique_id]:
                if 'required' in each_option and each_option['required']:
                    messages["error"].append(
                        f"{each_option['name']} not found and is required to be set. "
                        "Set option and save Input.")
            else:
                value = custom_options_values_inputs[input_dev.unique_id][each_option['id']]
                if ('required' in each_option and
                        each_option['required'] and
                        value != 0 and
                        not value):
                    messages["error"].append(
                        f"Error: {each_option['name']} is required to be set. "
                        f"Current value: '{value}'")

    #
    # Input-specific checks
    #
    if input_dev.device == 'LinuxCommand' and not input_dev.cmd_command:
        messages["error"].append("Cannot activate Command Input without a Command set")

    elif ('measurements_variable_amount' in dict_inputs[input_dev.device] and
            dict_inputs[input_dev.device]['measurements_variable_amount']):
        measure_set = True
        for each_channel in device_measurements.all():
            if (not each_channel.name or
                    not each_channel.measurement or
                    not each_channel.unit):
                measure_set = False
        if not measure_set:
            messages["error"].append("All measurements must have a name and unit/measurement set")


    messages = controller_activate_deactivate(
        messages, 'activate', 'Input',  input_id, flash_message=False)

    if not messages["error"]:
        messages["success"].append(
            f"{TRANSLATIONS['activate']['title']} {TRANSLATIONS['input']['title']}")

    return messages


def input_deactivate(form_mod):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        input_id = form_mod.input_id.data
        # messages = input_deactivate_associated_controllers(messages, input_id)
        messages = controller_activate_deactivate(
            messages, 'deactivate', 'Input', input_id, flash_message=False)
        messages["success"].append(
            f"{TRANSLATIONS['deactivate']['title']} {TRANSLATIONS['input']['title']}")
    except Exception as err:
        messages["error"].append(f"Error deactivating Input: {err}")

    return messages


# Deactivate any active PID controllers using this Input
def input_deactivate_associated_controllers(messages, input_id):
    # Deactivate any activated PIDs using this input
    sensor_unique_id = Input.query.filter(
        Input.unique_id == input_id).first().unique_id
    pid = PID.query.filter(PID.is_activated.is_(True)).all()
    for each_pid in pid:
        if sensor_unique_id in each_pid.measurement:
            messages = controller_activate_deactivate(
                messages, 'deactivate', 'PID', each_pid.unique_id)
    return messages


def check_input_channels_exist(dict_inputs, device, unique_id, messages):
    """Ensure all measurements and channels exist for Input"""
    try:
        #
        # If there are a variable number of measurements
        #
        if ('measurements_variable_amount' in dict_inputs[device] and
                dict_inputs[device]['measurements_variable_amount']):
            # Add first default measurement with empty unit and measurement
            measure_exists = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == unique_id).count()

            if not measure_exists:
                new_measurement = DeviceMeasurements()
                new_measurement.name = ""
                new_measurement.device_id = unique_id
                new_measurement.measurement = ""
                new_measurement.unit = ""
                new_measurement.channel = 0
                new_measurement.save()

        #
        # If measurements defined in the Input Module
        #

        elif ('measurements_dict' in dict_inputs[device] and
              dict_inputs[device]['measurements_dict']):
            for each_channel in dict_inputs[device]['measurements_dict']:

                measure_exists = DeviceMeasurements.query.filter(
                    and_(DeviceMeasurements.device_id == unique_id,
                         DeviceMeasurements.channel == each_channel)).count()

                if measure_exists:
                    continue

                measure_info = dict_inputs[device]['measurements_dict'][each_channel]
                new_measurement = DeviceMeasurements()
                if 'name' in measure_info:
                    # str() required: lazy_gettext names cannot be bound to SQLite
                    new_measurement.name = str(measure_info['name'])
                new_measurement.device_id = unique_id
                new_measurement.measurement = measure_info['measurement']
                new_measurement.unit = measure_info['unit']
                new_measurement.channel = each_channel
                new_measurement.save()

        if 'channels_dict' in dict_inputs[device]:
            for each_channel, channel_info in dict_inputs[device]['channels_dict'].items():
                channel_exists = InputChannel.query.filter(
                    and_(InputChannel.input_id == unique_id,
                         InputChannel.channel == each_channel)).count()

                if channel_exists:
                    continue

                new_channel = InputChannel()
                new_channel.channel = each_channel
                new_channel.input_id = unique_id

                # Generate string to save from custom options
                messages["error"], custom_options = custom_channel_options_return_json(
                    messages["error"], dict_inputs, None,
                    unique_id, each_channel,
                    device=device, use_defaults=True)
                new_channel.custom_options = custom_options

                new_channel.save()
    except:
        logger.exception("check_input_channels_exist()")

    return messages

def force_acquire_measurements(unique_id):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        mod_input = Input.query.filter(
            Input.unique_id == unique_id).first()

        if not mod_input:
            messages["error"].append("Input not found")
            return messages, False

        if not mod_input.is_activated:
            messages["error"].append(gettext(
                "Activate controller before attempting to force the acquisition of measurements"))

        if not messages["error"]:
            control = DaemonControl()
            status = control.input_force_measurements(unique_id)
            if status[0]:
                messages["error"].append(f"Force Input Measurement: {status[1]}")
            else:
                messages["success"].append(
                    f"{gettext('Force Measurements')}, {TRANSLATIONS['input']['title']}")
                flash(gettext("Force Input Measurement: %(status)s", status=status[1]), "success")
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages
