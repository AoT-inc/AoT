# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime

import sqlalchemy
from flask import current_app
from flask_babel import gettext
_ = gettext

from aot.config_translations import TRANSLATIONS
from aot.databases import set_uuid, clone_model
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Misc
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.databases.models import Tab
from aot.aot_client import DaemonControl
from aot.outputs.paired_actuator_common import PAIRED_ACTUATOR_OUTPUT_TYPES
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_general import delete_entry_with_id
from aot.aot_flask.utils.utils_general import normalize_nullish_value
from aot.aot_flask.utils.utils_general import sanitize_nullish_sequence
from aot.aot_flask.utils.utils_general import return_dependencies
from aot.aot_flask.utils.utils_general import sync_geo_device_name
from aot.utils.outputs import parse_output_information
from aot.aot_flask.utils.utils_map_config import (
    ensure_map_config,
    clone_map_config,
)
from aot.utils.system_pi import is_int

logger = logging.getLogger(__name__)
_DROP = object()
_NULLISH_STRINGS = {'', 'none', 'null', 'false'}


def _prune_nullish(value):
    """Recursively strip nullish placeholders from dict/list values."""
    if isinstance(value, dict):
        cleaned = {}
        for key, val in value.items():
            pruned = _prune_nullish(val)
            if pruned is not _DROP:
                cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            pruned = _prune_nullish(item)
            if pruned is not _DROP:
                cleaned_list.append(pruned)
        return cleaned_list
    if value is None:
        return _DROP
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _NULLISH_STRINGS:
            return _DROP
        return value.strip()
    return value


def _safe_json_string(val):
    """
    Normalize any incoming custom options value to a JSON string.
    - Treat None/"None"/"null"/"false"/"" as {}.
    - If already dict/list, dump to JSON after pruning nullish placeholders.
    - If string but malformed JSON, fall back to {}.
    """
    if val in [None, '', 'None', 'null', 'false', 'False']:
        return "{}"

    parsed = {}
    if isinstance(val, (dict, list)):
        parsed = val
    elif isinstance(val, str):
        try:
            parsed = json.loads(val)
        except Exception:
            return "{}"
    else:
        return "{}"

    cleaned = _prune_nullish(parsed)
    if cleaned is _DROP:
        cleaned = {}
    try:
        return json.dumps(cleaned)
    except Exception:
        return "{}"

#
# Output manipulation
#

def output_add(form_add, request_form, tab_id=None):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    output_id = None
    list_unmet_deps = []
    dep_name = None
    dep_message = ''
    size_y = None

    dict_outputs = parse_output_information()

    if form_add.output_type.data.count(',') == 1:
        output_type = form_add.output_type.data.split(',')[0]
        output_interface = form_add.output_type.data.split(',')[1]
    else:
        output_type = ''
        output_interface = ''
        messages["error"].append("Invalid output string (must be a comma-separated string)")

    if not current_app.config['TESTING']:
        dep_unmet, _unused, dep_message = return_dependencies(form_add.output_type.data.split(',')[0])
        if dep_unmet:
            messages["error"].append(
                f"{output_type} has unmet dependencies. "
                "They must be installed before the Output can be added.")

            for each_dep in dep_unmet:
                list_unmet_deps.append(each_dep[3])
                if each_dep[2] == 'pip-pypi':
                    dep_message += f" The Python package {each_dep[3]} was not found to be installed because '{each_dep[0]}' could not be imported."

            if output_type in dict_outputs:
                dep_name = dict_outputs[output_type]["output_name"]
            else:
                messages["error"].append("Output not found: {}".format(output_type))

            return messages, dep_name, list_unmet_deps, dep_message, None, None

    if not messages["error"]:
        try:
            new_output = Output()

            try:
                from RPi import GPIO
                if GPIO.RPI_INFO['P1_REVISION'] == 1:
                    new_output.i2c_bus = 0
                else:
                    new_output.i2c_bus = 1
            except:
                logger.error(
                    "RPi.GPIO and Raspberry Pi required for this action")

            new_output.name = "Name"
            new_output.interface = output_interface
            size_y = len(dict_outputs[output_type]['channels_dict']) + 1
            new_output.size_y = len(dict_outputs[output_type]['channels_dict']) + 1
            new_output.output_type = output_type
            max_pos = db.session.query(db.func.max(Output.position_y)).scalar()
            new_output.position_y = (max_pos or 0) + 1

            # Default map location from Misc
            try:
                misc = Misc.query.first()
                if misc:
                    new_output.latitude = misc.map_latitude
                    new_output.longitude = misc.map_longitude
                    if not new_output.latitude and not new_output.longitude and misc.timezone:
                        new_output.timezone = misc.timezone
            except Exception:
                pass

            #
            # Set default values for new input being added
            #

            # input add options
            if output_type in dict_outputs:
                def dict_has_value(key):
                    if (key in dict_outputs[output_type] and
                            dict_outputs[output_type][key] is not None):
                        return True

                #
                # Interfacing options
                #

                if output_interface == 'I2C':
                    if dict_has_value('i2c_address_default'):
                        new_output.i2c_location = dict_outputs[output_type]['i2c_address_default']
                    elif dict_has_value('i2c_location'):
                        new_output.i2c_location = dict_outputs[output_type]['i2c_location'][0]  # First list entry

                if output_interface == 'FTDI':
                    if dict_has_value('ftdi_location'):
                        new_output.ftdi_location = dict_outputs[output_type]['ftdi_location']

                if output_interface == 'UART':
                    if dict_has_value('uart_location'):
                        new_output.uart_location = dict_outputs[output_type]['uart_location']

                # UART options
                if dict_has_value('uart_baud_rate'):
                    new_output.baud_rate = dict_outputs[output_type]['uart_baud_rate']
                if dict_has_value('pin_cs'):
                    new_output.pin_cs = dict_outputs[output_type]['pin_cs']
                if dict_has_value('pin_miso'):
                    new_output.pin_miso = dict_outputs[output_type]['pin_miso']
                if dict_has_value('pin_mosi'):
                    new_output.pin_mosi = dict_outputs[output_type]['pin_mosi']
                if dict_has_value('pin_clock'):
                    new_output.pin_clock = dict_outputs[output_type]['pin_clock']

                # Bluetooth (BT) options
                elif output_interface == 'BT':
                    if dict_has_value('bt_location'):
                        new_output.location = dict_outputs[output_type]['bt_location']
                    if dict_has_value('bt_adapter'):
                        new_output.bt_adapter = dict_outputs[output_type]['bt_adapter']

                # GPIO options
                elif output_interface == 'GPIO':
                    if dict_has_value('gpio_pin'):
                        new_output.pin = dict_outputs[output_type]['gpio_pin']

                # Custom location
                elif dict_has_value('location'):
                    new_output.location = dict_outputs[output_type]['location']['options'][0][0]  # First entry in list

            # Generate string to save from custom options
            messages["error"], custom_options = custom_options_return_json(
                messages["error"], dict_outputs, request_form, device=output_type, use_defaults=True)
            custom_options = _safe_json_string(custom_options)
            new_output.custom_options = custom_options

            # [P1] 전용 지도 자동 생성 폐지 — 배치 시 지도에 속한다(원칙 2·4).

            #
            # Execute at Creation
            #

            new_output.unique_id = set_uuid()
            
            # Assign tab_id
            if tab_id:
                new_output.tab_id = tab_id

            if 'execute_at_creation' in dict_outputs[output_type] and not current_app.config['TESTING']:
                messages["error"], new_output = dict_outputs[output_type]['execute_at_creation'](
                    messages["error"], new_output, dict_outputs[output_type])

            if not messages["error"]:
                new_output.save()
                output_id = new_output.unique_id
                db.session.commit()

                messages["success"].append('{action} {controller}'.format(
                    action=TRANSLATIONS['add']['title'],
                    controller=TRANSLATIONS['output']['title']))

                #
                # If measurements defined in the Output Module
                #

                if ('measurements_dict' in dict_outputs[output_type] and
                        dict_outputs[output_type]['measurements_dict'] != []):
                    for each_measurement in dict_outputs[output_type]['measurements_dict']:
                        measure_info = dict_outputs[output_type]['measurements_dict'][each_measurement]
                        new_measurement = DeviceMeasurements()
                        if 'name' in measure_info:
                            new_measurement.name = str(measure_info['name'])
                        new_measurement.device_id = new_output.unique_id
                        new_measurement.measurement = measure_info['measurement']
                        new_measurement.unit = measure_info['unit']
                        new_measurement.channel = each_measurement
                        new_measurement.save()

                for each_channel, channel_info in dict_outputs[output_type]['channels_dict'].items():
                    new_channel = OutputChannel()
                    new_channel.channel = each_channel
                    new_channel.output_id = new_output.unique_id

                    # Generate string to save from custom options
                    messages["error"], custom_options = custom_channel_options_return_json(
                        messages["error"], dict_outputs, request_form,
                        new_output.unique_id, each_channel,
                        device=output_type, use_defaults=True)
                    custom_options = _safe_json_string(custom_options)
                    new_channel.custom_options = custom_options

                    new_channel.save()

                # Refresh output settings
                if not current_app.config['TESTING']:
                    new_messages = manipulate_output(
                        'Add', new_output.unique_id)
                    messages["error"].extend(new_messages["error"])
                    messages["success"].extend(new_messages["success"])

        except sqlalchemy.exc.OperationalError as except_msg:
            messages["error"].append(str(except_msg))
        except sqlalchemy.exc.IntegrityError as except_msg:
            messages["error"].append(str(except_msg))
        except Exception as except_msg:
            messages["error"].append(str(except_msg))
            logger.exception(1)

    list_unmet_deps = sanitize_nullish_sequence(list_unmet_deps or [])
    return messages, dep_name, list_unmet_deps, dep_message, output_id, size_y


def output_duplicate(form_mod):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    source_output = Output.query.filter(
        Output.unique_id == form_mod.output_id.data).first()

    if not source_output:
        return None, None

    # Duplicate output. Force position_y to max+1 so the clone lands at the
    # bottom of the grid; otherwise it inherits the source's position_y and
    # causes GridStack cards to overlap and ORDER BY to tie.
    max_pos = db.session.query(db.func.max(Output.position_y)).scalar()
    new_output = clone_model(
        source_output, unique_id=set_uuid(),
        name=f"Copy of {source_output.name}",
        position_y=(max_pos or 0) + 1)

    duplicated_output = Output.query.filter(
        Output.unique_id == new_output.unique_id).first()
    
    if duplicated_output:
        # [P1] 복제본은 미배치로 시작한다 — 지도를 복제해 붙이지 않는다.
        # 원본이 공유 디자인 지도에 배치돼 있으면 그 도형 전체가 숨은
        # 사설 지도로 복사되던 경로이기도 했다(원칙 1·2).
        duplicated_output.save()

        # Duplicate measurements
        dev_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == form_mod.output_id.data).all()
        for each_dev in dev_measurements:
            clone_model(each_dev, unique_id=set_uuid(), device_id=duplicated_output.unique_id)

        # Duplicate channels
        dev_channels = OutputChannel.query.filter(
            OutputChannel.output_id == form_mod.output_id.data).all()
        is_paired = source_output.output_type in PAIRED_ACTUATOR_OUTPUT_TYPES
        for each_dev in dev_channels:
            new_ch = clone_model(
                each_dev, unique_id=set_uuid(),
                output_id=duplicated_output.unique_id)
            # For paired actuators, blank out the underlying open/close/selector
            # refs and any position state on the duplicate so it doesn't share
            # physical channels with the source. User must reconfigure on the copy.
            if is_paired and new_ch and new_ch.custom_options:
                try:
                    import json as _json
                    co = _json.loads(new_ch.custom_options)
                    for k in ('output_open_id', 'output_close_id',
                              'selector_output_id', 'last_position_pct'):
                        if k in co:
                            co[k] = '' if k != 'last_position_pct' else 0.0
                    new_ch.custom_options = _json.dumps(co)
                except Exception:
                    pass
            
        # [I10/I12] 복제본은 '미배치'로 시작한다 — 지도 도형을 복사하지 않는다.
        # 과거에는 clone_model 이 geo_id 를 그대로 물려줘, 복제된 밸브의 마커가
        # **원본 지도**에 생겼다(유니크 위반이 아니라 조용한 오염). 게다가
        # 같은 좌표에 있는 서로 다른 물리 장치는 성립하지 않는다 — 복제된
        # 장치는 사용자가 지도에서 새로 배치해야 한다.
        # 배치가 필요하면 geo.device_placement.place_device 를 쓸 것.

    messages["success"].append(
        f"{TRANSLATIONS['duplicate']['title']} {TRANSLATIONS['output']['title']}")
        
    if not current_app.config['TESTING']:
         manipulate_output('Add', duplicated_output.unique_id)

    return messages, new_output.unique_id


def output_mod(form_output, request_form):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": [],
        "name": None,
        "return_text": []
    }
    page_refresh = False

    dict_outputs = parse_output_information()

    try:
        channels = OutputChannel.query.filter(
            OutputChannel.output_id == form_output.output_id.data).all()
        mod_output = Output.query.filter(
            Output.unique_id == form_output.output_id.data).first()

        if not mod_output:
            messages["error"].append("Invalid output ID")
            return messages, page_refresh

        # [P1] 수정 시 지도 자동 생성 폐지(원칙 4).

        if (form_output.uart_location.data and
                not os.path.exists(form_output.uart_location.data)):
            messages["warning"].append(gettext(
                "Invalid device or improper permissions to read device"))

        if form_output.name.data not in [None, '']:
            mod_output.name = form_output.name.data
            messages["name"] = form_output.name.data

        new_tab_id = request_form.get('tab_id')
        if new_tab_id and new_tab_id != mod_output.tab_id:
            if Tab.query.filter(Tab.unique_id == new_tab_id).first():
                mod_output.tab_id = new_tab_id
                messages["tab_id"] = new_tab_id

        if form_output.location.data:
            mod_output.location = form_output.location.data
        lat_val = form_output.latitude.data
        lng_val = form_output.longitude.data
        if lat_val not in [None, ''] and lng_val not in [None, '']:
            mod_output.latitude = float(lat_val)
            mod_output.longitude = float(lng_val)
            mod_output.location_updated_utc = datetime.utcnow()
        elif (lat_val in [None, '']) and (lng_val in [None, '']):
            # Leave existing coords untouched to avoid unintended clearing
            pass
        else:
            messages["warning"].append(gettext("Latitude and longitude must be entered together."))
        if form_output.location_source.data:
            mod_output.location_source = form_output.location_source.data
        if ('marker_icon' in request_form) and hasattr(form_output, 'marker_icon') and form_output.marker_icon.data not in [None, '', 'None', 'null']:
            mod_output.marker_icon = form_output.marker_icon.data
        if ('marker_color' in request_form) and hasattr(form_output, 'marker_color') and form_output.marker_color.data not in [None, '', 'None', 'null']:
            mod_output.marker_color = form_output.marker_color.data
        if ('marker_size' in request_form) and hasattr(form_output, 'marker_size') and form_output.marker_size.data not in [None, '', 'None', 'null']:
            try:
                mod_output.marker_size = int(form_output.marker_size.data)
            except Exception:
                pass
        if form_output.i2c_location.data:
            mod_output.i2c_location = form_output.i2c_location.data
        if form_output.ftdi_location.data:
            mod_output.ftdi_location = form_output.ftdi_location.data
        if form_output.uart_location.data:
            mod_output.uart_location = form_output.uart_location.data
        if form_output.gpio_location.data:
            if not is_int(form_output.gpio_location.data):
                messages["error"].append("BCM GPIO Pin must be an integer")
            else:
                mod_output.pin = form_output.gpio_location.data

        if form_output.i2c_bus.data is not None:
            mod_output.i2c_bus = form_output.i2c_bus.data
        if form_output.baud_rate.data:
            mod_output.baud_rate = form_output.baud_rate.data

        mod_output.log_level_debug = form_output.log_level_debug.data

        # Parse pre-save custom options for output device and its channels
        try:
            custom_options_dict_presave = json.loads(mod_output.custom_options) if mod_output.custom_options else {}
        except Exception:
            logger.error("Malformed JSON in custom_options for output %s; defaulting to {}", mod_output.output_type)
            custom_options_dict_presave = {}

        custom_options_channels_dict_presave = {}
        for each_channel in channels:
            try:
                if each_channel.custom_options and each_channel.custom_options not in [None, "{}", "null", "None"]:
                    custom_options_channels_dict_presave[each_channel.channel] = json.loads(
                        each_channel.custom_options)
                else:
                    custom_options_channels_dict_presave[each_channel.channel] = {}
            except Exception:
                logger.error("Malformed JSON in custom_channel_options for output %s channel %s; defaulting to {}", mod_output.output_type, each_channel.channel)
                custom_options_channels_dict_presave[each_channel.channel] = {}

        # Parse post-save custom options for output device and its channels
        messages["error"], custom_options_json_postsave = custom_options_return_json(
            messages["error"], dict_outputs, request_form,
            mod_dev=mod_output,
            device=mod_output.output_type,
            custom_options=custom_options_dict_presave)
        custom_options_json_postsave = _safe_json_string(custom_options_json_postsave)
        try:
            custom_options_dict_postsave = json.loads(custom_options_json_postsave)
        except Exception:
            logger.warning("custom_options_return_json produced invalid JSON for output %s (mod), defaulting to {}", mod_output.output_type)
            custom_options_dict_postsave = {}

        custom_options_channels_dict_postsave = {}
        # DEBUG: log form keys related to paired channel options when modifying actuator_paired
        if mod_output.output_type in PAIRED_ACTUATOR_OUTPUT_TYPES:
            _paired_keys = [k for k in request_form.keys()
                            if k.startswith(form_output.output_id.data)]
            logger.info("[paired-save] output_id=%s form-keys for this output: %s",
                        form_output.output_id.data, _paired_keys)
            for _k in _paired_keys:
                logger.info("[paired-save]   %s = %r", _k, request_form.get(_k))
        for each_channel in channels:
            messages["error"], custom_options_channels_json_postsave_tmp = custom_channel_options_return_json(
                messages["error"], dict_outputs, request_form,
                form_output.output_id.data, each_channel.channel,
                device=mod_output.output_type, use_defaults=False,
                custom_options=custom_options_channels_dict_presave.get(each_channel.channel, {}))
            custom_options_channels_json_postsave_tmp = _safe_json_string(custom_options_channels_json_postsave_tmp)
            try:
                custom_options_channels_dict_postsave[each_channel.channel] = json.loads(
                    custom_options_channels_json_postsave_tmp)
            except Exception:
                logger.warning("custom_channel_options_return_json produced invalid JSON for output %s channel %s (mod), defaulting to {}", mod_output.output_type, each_channel.channel)
                custom_options_channels_dict_postsave[each_channel.channel] = {}
            # final sanitize to ensure dict
            if not isinstance(custom_options_channels_dict_postsave[each_channel.channel], dict):
                logger.warning("custom_channel_options_return_json returned non-dict for output %s channel %s (mod), forcing {}", mod_output.output_type, each_channel.channel)
                custom_options_channels_dict_postsave[each_channel.channel] = {}

        if 'execute_at_modification' in dict_outputs[mod_output.output_type]:
            # pass custom options to module prior to saving to database
            (messages,
             mod_output,
             custom_options_dict,
             custom_options_channels_dict) = dict_outputs[mod_output.output_type]['execute_at_modification'](
                messages,
                mod_output,
                request_form,
                custom_options_dict_presave,
                custom_options_channels_dict_presave,
                custom_options_dict_postsave,
                custom_options_channels_dict_postsave)
            custom_options = json.dumps(custom_options_dict)  # Convert from dict to JSON string
            custom_channel_options = custom_options_channels_dict
        else:
            # Don't pass custom options to module
            custom_options = json.dumps(custom_options_dict_postsave)
            custom_channel_options = custom_options_channels_dict_postsave

        # [Fix] Manually persist shape color options
        # Since these are not in dict_outputs schema, custom_options_return_json ignores them.
        try:
            co_dict = json.loads(custom_options) if custom_options else {}
        except:
            co_dict = {}

        for shape_key in ['shape_on_color', 'shape_off_color', 'shape_border_color']:
            if shape_key in request_form:
                val = request_form.get(shape_key)
                # Only update if value is not None/Empty, OR valid color format
                # If transparent/reset is needed, we might need to handle empty string differently
                if val:
                    co_dict[shape_key] = val
        
        custom_options = json.dumps(co_dict)

        # Finally, save custom options for both output and channels
        # final sanitize: ensure strings persisted
        custom_options = _safe_json_string(custom_options)
        mod_output.custom_options = custom_options
        channel_names_to_sync = {}
        for each_channel in channels:
            channel_opts = custom_channel_options.get(each_channel.channel, {})
            if isinstance(channel_opts, str):
                try:
                    channel_opts = json.loads(channel_opts)
                except Exception:
                    channel_opts = {}
            safe_channel_opts = _safe_json_string(channel_opts)
            try:
                parsed_channel_opts = json.loads(safe_channel_opts) if safe_channel_opts else {}
            except Exception:
                parsed_channel_opts = {}
            if isinstance(parsed_channel_opts, dict) and 'name' in parsed_channel_opts:
                each_channel.name = parsed_channel_opts['name']
                channel_names_to_sync[str(each_channel.channel)] = parsed_channel_opts['name']
            each_channel.custom_options = safe_channel_opts

        if not messages["error"]:
            db.session.commit()
            messages["success"].append('{action} {controller}'.format(
                action=TRANSLATIONS['modify']['title'],
                controller=TRANSLATIONS['output']['title']))
            # 메인 출력 이름 변경 → 채널0이 별도 관리되지 않는 경우만 geo sync
            if messages.get("name") and '0' not in channel_names_to_sync:
                sync_geo_device_name(mod_output.unique_id, mod_output.name, channel_id='0')
            # 채널별 이름이 실제로 변경된 것만 sync
            for ch_id, ch_name in channel_names_to_sync.items():
                sync_geo_device_name(mod_output.unique_id, ch_name, channel_id=ch_id)

            if not current_app.config['TESTING']:
                new_messages = manipulate_output(
                    'Modify', form_output.output_id.data)
                messages["error"].extend(new_messages["error"])
                messages["success"].extend(new_messages["success"])
            page_refresh = False
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages, page_refresh


def output_del(form_output):
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        output_id_raw = form_output.output_id.data
    except Exception:
        output_id_raw = None
    output_id = normalize_nullish_value(output_id_raw, '')
    if output_id in ['', None]:
        messages["error"].append("Invalid output ID")
        return messages

    try:
        target_output = Output.query.filter(Output.unique_id == output_id).first()
        map_config_id = target_output.map_config_id if target_output else None

        device_measurements = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id == output_id).all()

        for each_measurement in device_measurements:
            delete_entry_with_id(
                DeviceMeasurements,
                each_measurement.unique_id,
                flash_message=False)

        # [Phase C] 장치가 사라지면 바인딩을 끝낸다 — 도형은 미배정
        # 슬롯으로 남는다(위치 마커만 예외). 삭제 경로 17곳이 전부
        # 이 게이트웨이를 지나간다.
        from aot.aot_flask.geo.device_binding import end_all_for_device
        end_all_for_device(output_id)
        deleted_output = delete_entry_with_id(
            Output,
            output_id,
            flash_message=False)
        # [P3] 원칙 1 — 지도는 장치의 소유물이 아니다. 장치를 지워도 지도는
        # 남는다. 과거 이 호출이 장치 삭제로 공유 디자인 지도를 통째로
        # 지웠다(임실군 62도형). 지도 삭제는 geo/design 에서 명시적으로만.


        channels = OutputChannel.query.filter(
            OutputChannel.output_id == output_id).all()
        for each_channel in channels:
            delete_entry_with_id(
                OutputChannel,
                each_channel.unique_id,
                flash_message=False)

        db.session.commit()
        messages["success"].append('{action} {controller}'.format(
            action=TRANSLATIONS['delete']['title'],
            controller=TRANSLATIONS['output']['title']))

        if deleted_output and not current_app.config['TESTING']:
            new_messages = manipulate_output(
                'Delete', form_output.output_id.data)
            messages["error"].extend(new_messages["error"])
            messages["success"].extend(new_messages["success"])

        # 사용자 코드 파일은 데몬이 이 출력을 놓은 **뒤에** 지운다 — 위
        # manipulate_output('Delete') 가 컨트롤러를 내리면서 off 코드를
        # 실행할 수 있으므로, 그 앞에서 파일을 지우면 정지 경로가 깨진다.
        from aot.utils.code_verification import delete_python_file
        delete_python_file('output', output_id)
    except Exception as except_msg:
        messages["error"].append(str(except_msg))

    return messages


def manipulate_output(action, output_id):
    """
    Add, delete, and modify output settings while the daemon is active

    :param output_id: output ID in the SQL database
    :type output_id: str
    :param action: "Add", "Delete", or "Modify"
    :type action: str
    """
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        # Add/Modify can re-apply a channel's startup state, which for some
        # output types (e.g. chirpstack_downlink) sends a real network
        # command with its own multi-second timeout/fallback chain — give
        # those extra room over the default RPC timeout.
        control = DaemonControl(extended_timeout=(action in ('Add', 'Modify')))
        return_values = control.output_setup(action, output_id)
        if return_values and len(return_values) > 1:
            if return_values[0]:
                messages["error"].append(gettext("%(err)s",
                    err='{action} Output: Daemon response: {msg}'.format(
                        action=action,
                        msg=return_values[1])))
            else:
                messages["success"].append(gettext("%(err)s",
                    err='{action} Output: Daemon response: {msg}'.format(
                        action=gettext(action),
                        msg=return_values[1])))
    except Exception as msg:
        messages["error"].append(gettext("%(err)s",
            err='{action} Output: Could not connect to Daemon: {error}'.format(
                action=action, error=msg)))

    return messages


def get_all_output_states():
    daemon_control = DaemonControl()
    return daemon_control.output_states_all()
