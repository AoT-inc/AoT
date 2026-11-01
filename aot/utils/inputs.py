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

from aot.config import PATH_INPUTS
from aot.config import PATH_INPUTS_CUSTOM
from aot.config import PATH_INPUTS_GIS
from aot.inputs.sensorutils import convert_units
from aot.utils.modules import load_module_from_file
from aot.utils.safe_eval import safe_eval

logger = logging.getLogger("aot.utils.inputs")


def parse_measurement(
        conversion,
        measurement,
        measurements_record,
        each_channel,
        each_measurement,
        timestamp=None):
    """Parse and process a single measurement including scaling and unit conversion.

    @phase active
    @stability stable
    @dependency convert_units
    """
    # Unscaled, unconverted measurement
    measurements_record[each_channel] = {
        'measurement': each_measurement['measurement'],
        'unit': each_measurement['unit'],
        'value': each_measurement['value'],
        'timestamp_utc': timestamp
    }

    # Scaling needs to come before conversion
    # Scale measurement
    if (measurement.rescaled_measurement and
            measurement.rescaled_unit):
        scaled_value = measurements_record[each_channel] = rescale_measurements(
            measurement, measurements_record[each_channel]['value'])
        measurements_record[each_channel] = {
            'measurement': measurement.rescaled_measurement,
            'unit': measurement.rescaled_unit,
            'value': scaled_value,
            'timestamp_utc': timestamp
        }

    # Convert measurement
    if measurement.conversion_id not in ['', None] and 'value' in each_measurement:
        converted_value = convert_units(
            measurement.conversion_id,
            measurements_record[each_channel]['value'])
        measurements_record[each_channel] = {
            'measurement': None,
            'unit': conversion.convert_unit_to,
            'value': converted_value,
            'timestamp_utc': timestamp
        }
    return measurements_record


def rescale_measurements(measurement, measurement_value):
    """Rescale a measurement value using linear or equation-based rescaling.

    @phase active
    @stability stable
    """
    rescaled_measurement = None
    try:
        if measurement.rescale_method == "linear":
            # Get the difference between min and max volts
            diff_voltage = abs(
                float(measurement.scale_from_max) - float(measurement.scale_from_min))

            # Ensure the value stays within the min/max bounds
            if measurement_value < float(measurement.scale_from_min):
                measured_voltage = measurement.scale_from_min
            elif measurement_value > float(measurement.scale_from_max):
                measured_voltage = float(measurement.scale_from_max)
            else:
                measured_voltage = measurement_value

            # Calculate the percentage of the difference
            percent_diff = ((measured_voltage - float(measurement.scale_from_min)) /
                            diff_voltage)

            # Get the units difference between min and max units
            diff_units = abs(float(measurement.scale_to_max) - float(measurement.scale_to_min))

            # Calculate the measured units from the percent difference
            if measurement.invert_scale:
                converted_units = (float(measurement.scale_to_max) -
                                   (diff_units * percent_diff))
            else:
                converted_units = (float(measurement.scale_to_min) +
                                   (diff_units * percent_diff))

            # Ensure the units stay within the min/max bounds
            if converted_units < float(measurement.scale_to_min):
                rescaled_measurement = float(measurement.scale_to_min)
            elif converted_units > float(measurement.scale_to_max):
                rescaled_measurement = float(measurement.scale_to_max)
            else:
                rescaled_measurement = converted_units

        elif measurement.rescale_method == "equation":
            # UnsafeExpressionError propagates to this function's existing
            # `except Exception` below, which logs and returns None — same
            # behaviour a malformed equation already had under eval().
            rescaled_measurement = safe_eval(
                measurement.rescale_equation, {'x': measurement_value})

        if rescaled_measurement:
            return rescaled_measurement

    except Exception as except_msg:
        logger.exception(
            "Error while attempting to rescale measurement: {err}".format(
                err=except_msg))


def list_devices_using_interface(interface):
    """Generate a list of input device names that use a particular interface.

    @phase active
    @stability stable
    @dependency parse_input_information
    """
    def check(check_input, dict_all_inputs, check_interface):
        if ('interfaces' in dict_all_inputs[check_input] and
                check_interface in dict_all_inputs[check_input]['interfaces']):
            return True

    list_devices = []
    dict_inputs = parse_input_information()

    for each_input in dict_inputs:
        if (check(each_input, dict_inputs, interface) and
                each_input not in list_devices):
            list_devices.append(each_input)

    return list_devices


def list_analog_to_digital_converters():
    """Generate a list of input devices that are analog-to-digital converters.

    @phase active
    @stability stable
    @dependency parse_input_information
    """
    list_adc = []
    dict_inputs = parse_input_information()
    for each_input in dict_inputs:
        if ('analog_to_digital_converter' in dict_inputs[each_input] and
                dict_inputs[each_input]['analog_to_digital_converter'] and
                each_input not in list_adc):
            list_adc.append(each_input)
    return list_adc



def parse_input_information(exclude_custom=False, custom_only=False):
    """Parse input module information and return a dictionary of input IDs and metadata.

    @phase active
    @stability stable
    @dependency load_module_from_file
    """
    def dict_has_value(dict_inp, input_cus, key, force_type=None):
        if (key in input_cus.INPUT_INFORMATION and
                (input_cus.INPUT_INFORMATION[key] or
                 input_cus.INPUT_INFORMATION[key] == 0)):
            if force_type == 'list':
                if isinstance(input_cus.INPUT_INFORMATION[key], list):
                    dict_inp[input_cus.INPUT_INFORMATION['input_name_unique']][key] = \
                        input_cus.INPUT_INFORMATION[key]
                else:
                    dict_inp[input_cus.INPUT_INFORMATION['input_name_unique']][key] = \
                        [input_cus.INPUT_INFORMATION[key]]
            else:
                dict_inp[input_cus.INPUT_INFORMATION['input_name_unique']][key] = \
                    input_cus.INPUT_INFORMATION[key]
        return dict_inp

    excluded_files = [
        '__init__.py', '__pycache__', 'base_input.py', 'custom_inputs',
        'examples', 'scripts', 'tmp_inputs', 'sensorutils.py'
    ]

    if custom_only:
        input_paths = [PATH_INPUTS_CUSTOM]
    else:
        input_paths = [PATH_INPUTS, PATH_INPUTS_GIS]
        if not exclude_custom:
            input_paths.append(PATH_INPUTS_CUSTOM)

    dict_inputs = {}

    for each_path in input_paths:

        real_path = os.path.realpath(each_path)

        for each_file in os.listdir(real_path):
            if each_file in excluded_files:
                continue

            if each_file.startswith('._'):
                continue

            full_path = "{}/{}".format(real_path, each_file)
            input_custom, status = load_module_from_file(full_path, 'inputs')

            if not input_custom or not hasattr(input_custom, 'INPUT_INFORMATION'):
                continue

            # Case for SATELLITE_ANALYSIS: Force module discovery to ensure UI dropdown is populated
            if hasattr(input_custom, 'discover_analysis_modules'):
                try:
                    input_custom.discover_analysis_modules()
                except Exception as e:
                    logger.error(f"Error calling discover_analysis_modules for {each_file}: {e}")

            # Populate dictionary of input information
            if input_custom.INPUT_INFORMATION['input_name_unique'] in dict_inputs:
                logger.error("Error: Cannot add input modules because it does not have a unique name: {name}".format(
                    name=input_custom.INPUT_INFORMATION['input_name_unique']))
            else:
                dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']] = {}

            dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']]['file_path'] = full_path

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'input_manufacturer')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'input_name')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'country', force_type='list')
            
            # Prepend Country Code to Input Name if available
            if 'country' in dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']]:
                countries = dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']]['country']
                if countries and len(countries) > 0:
                    country_code = countries[0]
                    original_name = dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']].get('input_name', '')
                    dict_inputs[input_custom.INPUT_INFORMATION['input_name_unique']]['input_name'] = f"{country_code}: {original_name}"

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'input_name_short')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'data_origin')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'data_time')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'input_library')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'interfaces', force_type='list')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'measurements_name')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'measurements_dict')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'channels_dict')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'measurements_variable_amount')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'channel_quantity_same_as_measurements')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'measurements_use_same_timestamp')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'measurements_rescale')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'do_not_run_periodically')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'edge_input')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'message')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'url_datasheet', force_type='list')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'url_manufacturer', force_type='list')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'url_product_purchase', force_type='list')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'url_additional', force_type='list')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'url_api_key', force_type='list')

            # Dependencies
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'dependencies_module')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'dependencies_message')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'enable_channel_unit_select')

            # Interfaces
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'interfaces')

            # Nonstandard (I2C, UART, etc.) location
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'location')

            # I2C
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'i2c_location')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'i2c_address_editable')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'i2c_address_default')

            # FTDI
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'ftdi_location')

            # UART
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'uart_location')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'uart_baud_rate')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'pin_cs')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'pin_miso')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'pin_mosi')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'pin_clock')

            # Bluetooth (BT)
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'bt_location')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'bt_adapter')

            # Which form options to display and whether each option is enabled
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'options_enabled')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'options_disabled')

            # Host options
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'times_check')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'deadline')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'port')

            # Signal options
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'weighting')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'sample_time')

            # Analog-to-digital converter
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'adc_gain')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'adc_resolution')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'adc_sample_speed')

            # Misc
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'period')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'sht_voltage')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'cmd_command')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'resolution')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'resolution_2')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'sensitivity')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'thermocouple_type')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'ref_ohm')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'execute_at_creation')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'execute_at_modification')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'custom_options_message')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'custom_options')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'custom_channel_options')

            dict_inputs = dict_has_value(dict_inputs, input_custom, 'custom_commands_message')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'custom_commands')

            # GIS Options
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'default_url')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'attribution')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'layer_type')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'layer_role')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'time_enabled')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'leaflet_options')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'legend')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'key_field')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'global_key_field')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'requires_key')
            # Per-input center/zoom override (e.g. gis_gsi.py centers on Tokyo instead
            # of the global default) — without these two, the settings-modal preview
            # always falls back to AOT_GEO_CONFIG's global center, which is out of
            # coverage for region-locked tile providers and renders nothing.
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'default_center')
            dict_inputs = dict_has_value(dict_inputs, input_custom, 'default_zoom')

    return dict_inputs


_MODEL_DRIVERS = None
_FORECAST_TIME_DRIVERS = None


def _parsed_input_information():
    """드라이버 목록 파싱 — 요청 밖이면 로캘을 고정해 한 번 더. 실패하면 None.

    앱 컨텍스트는 있는데 요청이 없는 자리(리플레이·스크립트)에서는 `lazy_gettext`
    가 로캘을 요청에서 찾다 터진다. 이 판정들은 강우 게이트(예보 강수를 실측처럼
    다루지 않는다)와 오용 가드도 쓰므로 조용히 비면 안 된다.
    """
    try:
        return parse_input_information()
    except Exception:                                       # noqa: BLE001
        try:
            from flask_babel import force_locale
            with force_locale('en'):
                return parse_input_information()
        except Exception:                                   # noqa: BLE001
            return None


def model_input_drivers():
    """값이 실측이 아니라 **모델(예보·재분석)** 인 입력 드라이버 이름들.

    드라이버가 INPUT_INFORMATION 에 `'data_origin': 'model'` 로 선언한다. 예전에는
    그 사실이 사람용 `message` 문장에만 있어, Open-Meteo 예보가 구역 센서
    목록에 실측처럼 섞여 같은 구역 실측과 8°C 차이 나는 값이 그대로 읽혔다
    (2026-10-09 외부 AI 점검). 판정은 이 함수 하나에서 한다.

    성공한 결과만 기억한다. 드라이버 목록 파싱은 요청 밖(app context 만 있는
    스크립트·백그라운드 잡)에서 번역 문자열 때문에 실패할 수 있는데, 그 빈 결과를
    `lru_cache` 로 기억하면 그 프로세스가 끝날 때까지 예보가 실측처럼 나간다.
    """
    global _MODEL_DRIVERS
    if _MODEL_DRIVERS is not None:
        return _MODEL_DRIVERS
    info = _parsed_input_information()
    if info is None:
        return frozenset()
    _MODEL_DRIVERS = frozenset(k for k, v in info.items()
                               if isinstance(v, dict) and v.get('data_origin') == 'model')
    return _MODEL_DRIVERS


def forecast_time_input_drivers():
    """값이 **미래 시각에 대한 것**(몇 시간 뒤 예보)인 입력 드라이버 이름들.

    드라이버가 INPUT_INFORMATION 에 `'data_time': 'forecast'` 로 선언한다. 표식이
    없으면 '현재' 다 — `OPEN_METEO_FORECAST` 처럼 모델값이라도 "지금 칸" 을 내는
    입력은 여기 들지 않는다(`data_origin` 과 다른 축이다: 출처는 모델이어도 시각은
    지금일 수 있다).

    오용 가드가 쓴다 — "+6h 강수" 를 실외 강우("지금 값") 자리에 묶으면 지금 오지
    않는 비로 창이 닫힌다. 캐시·로캘 처리는 `model_input_drivers()` 와 같다(성공한
    결과만 기억, 파싱 실패는 빈 집합 = "현재" 로 본다 — 기존 입력을 거부하지 않는다).
    """
    global _FORECAST_TIME_DRIVERS
    if _FORECAST_TIME_DRIVERS is not None:
        return _FORECAST_TIME_DRIVERS
    info = _parsed_input_information()
    if info is None:
        return frozenset()
    _FORECAST_TIME_DRIVERS = frozenset(
        k for k, v in info.items()
        if isinstance(v, dict) and v.get('data_time') == 'forecast')
    return _FORECAST_TIME_DRIVERS


_DAILY_FORECAST_DRIVERS = None


def daily_forecast_drivers():
    """채널이 **며칠 뒤의 일 값**(채널 메타 ``forecast_lead_d``·``daily_stat``)인 예보 입력 드라이버 →
    그 드라이버의 ``measurements_dict``.

    대지 예보 출처(`geo.forecast_series`)가 시간별 입력과 일별 입력을 가를 때 쓴다 — 제공자 이름을 보지 않는다.
    캐시는 `forecast_time_input_drivers()` 와 같다(성공한 결과만 기억)."""
    global _DAILY_FORECAST_DRIVERS
    if _DAILY_FORECAST_DRIVERS is not None:
        return _DAILY_FORECAST_DRIVERS
    info = _parsed_input_information()
    if info is None:
        return {}
    out = {}
    for k, v in info.items():
        md = (v or {}).get('measurements_dict') if isinstance(v, dict) else None
        if isinstance(md, dict) and any(isinstance(m, dict) and m.get('forecast_lead_d') is not None
                                        for m in md.values()):
            out[k] = md
    _DAILY_FORECAST_DRIVERS = out
    return out


def hourly_lead_channels(driver):
    """드라이버의 시간별 예보 리드 채널 → {채널: (리드 시간, 'instant'|'cell')}. 없으면 빈 dict.

    채널 메타 ``forecast_lead_h``·``forecast_kind`` 를 드라이버가 밝힌다(제공자 이름을 보지 않는다).
    저장 시각 + 리드가 그 값이 가리키는 시각이다 — 창 집계 채널은 한 시각을 가리키지 않아 여기 없다."""
    info = _parsed_input_information()
    md = ((info or {}).get(driver) or {}).get('measurements_dict')
    if not isinstance(md, dict):
        return {}
    return {ch: (m['forecast_lead_h'], m.get('forecast_kind') or 'instant')
            for ch, m in md.items() if isinstance(m, dict) and m.get('forecast_lead_h') is not None}


def _input_devices(ids):
    """[(unique_id, device)] — 데몬 안전 접근자 먼저, 안 되면 Flask 세션. 실패하면 None."""
    rows = None
    try:
        from aot.databases.models import Input
        from aot.utils.database import db_retrieve_table_daemon
        table = db_retrieve_table_daemon(Input)
        if table is not None and not isinstance(table, list):
            rows = [(r.unique_id, r.device)
                    for r in table.filter(Input.unique_id.in_(ids)).all()]
    except Exception:                                       # noqa: BLE001
        rows = None
    if not rows:
        try:
            from aot.databases.models import Input
            rows = Input.query.filter(Input.unique_id.in_(ids)).with_entities(
                Input.unique_id, Input.device).all()
        except Exception:                                   # noqa: BLE001
            return None
    return rows


def model_origin_device_ids(device_ids):
    """주어진 Input 중 값이 **모델(예보·재분석)** 인 장치의 unique_id 집합.

    판정은 `model_input_drivers()`(드라이버의 `'data_origin': 'model'`) 하나다 —
    장치 이름이나 측정 이름으로 어림하지 않는다. 같은 드라이버를 이름만 바꿔
    등록해도 예보는 예보다.

    제어(env_coordinator 강우 게이트)가 데몬에서 부르므로 데몬 안전 접근자를
    먼저 쓴다(`measurement_freshness.freshness_by_device` 와 같은 이유 — 데몬에는
    Flask 앱 컨텍스트가 없어 `Input.query` 가 조용히 실패한다).

    **모르면 빈 집합이다** — 호출자는 그것을 "실측" 으로 읽는다. 실측 쪽이 더
    엄격하므로(강우 게이트가 개구부를 전부 닫는다) 판정 실패가 보호를 줄이지
    않는다.
    """
    ids = sorted({i for i in (device_ids or []) if i})
    if not ids:
        return set()
    models = model_input_drivers()
    if not models:
        return set()
    rows = _input_devices(ids)
    if not rows:
        return set()
    return {uid for uid, dev in rows if dev in models}


def forecast_time_device_ids(device_ids):
    """주어진 Input 중 값이 **미래 시각에 대한 것**(드라이버 `data_time='forecast'`)인
    장치의 unique_id 집합.

    **모르면 빈 집합이다** — 호출자(오용 가드)는 그것을 "현재 값 입력" 으로 읽고
    막지 않는다. 판정 실패로 기존 입력(예: 구마모토 일사 센서에 묶인
    `OPEN_METEO_FORECAST`)이 저장 거부되면 안 된다.
    """
    ids = sorted({i for i in (device_ids or []) if i})
    if not ids:
        return set()
    drivers = forecast_time_input_drivers()
    if not drivers:
        return set()
    rows = _input_devices(ids)
    if not rows:
        return set()
    return {uid for uid, dev in rows if dev in drivers}


def forecast_time_selection_problem(selector):
    """'지금 값' 칸(실외 센서·수집기 항목)에 고른 값이 예보 입력이면 한국어 이유, 아니면 None.

    `selector` 는 장치 id 또는 'device_id,measurement_id'. 빈 값·Function·Output 은
    통과한다(드라이버 표식이 있는 Input 만 본다).
    """
    dev = str(selector or '').split(',')[0].strip()
    if not dev:
        return None
    try:
        hit = forecast_time_device_ids([dev])
    except Exception:                                       # noqa: BLE001
        return None
    if dev not in hit:
        return None
    return FORECAST_TIME_MISUSE_MESSAGE


#: 오용 가드의 거부 문구(한국어). 화면·도구가 같은 문장을 쓴다.
FORECAST_TIME_MISUSE_MESSAGE = (
    '몇 시간 뒤 예보 입력(Open-Meteo 시간별 예보)은 "지금 값" 자리에 쓸 수 없습니다 — '
    '예보 강수가 지금 오는 비로 읽혀 창이 닫힙니다. 예보는 시설 편집기 기상 탭의 '
    '예보 바인딩(forecast_*)에 연결하세요.')


RAIN_ORIGIN_MODEL = 'model'
RAIN_ORIGIN_MEASURED = 'measured'


def rain_origin_of(device_ids) -> str:
    """강우 값을 낸 장치들 → 'model' | 'measured'.

    **전부** 모델(예보·재분석 — 드라이버의 `data_origin`)일 때만 'model' 이다. 실측이
    하나라도 섞였거나 판정을 못 하면 'measured' — 강우 게이트는 실측 쪽이 더
    엄격하다(개구부 전부 닫음, `safety_gates.classify_rain`). 모름이 보호를 줄이면
    안 된다.

    2026-10-10 구마모토: 실외 강우의 유일한 근거가 Open-Meteo 예보(0.3~1.0 mm)였는데
    실측 강우계와 같은 대우를 받아 실내 30 °C 에서 창을 네 시간 넘게 전부 닫았다.
    """
    ids = [d for d in (device_ids or []) if d]
    if not ids:
        return RAIN_ORIGIN_MEASURED
    try:
        models = model_origin_device_ids(ids)
    except Exception:                                       # noqa: BLE001
        return RAIN_ORIGIN_MEASURED
    return RAIN_ORIGIN_MODEL if all(d in models for d in ids) else RAIN_ORIGIN_MEASURED


# ─────────────────────────────────────────────────────────────────────────────
# 강우 단위 — 강우 게이트는 **mm/h** 로 본다 (2026-10-10)
# ─────────────────────────────────────────────────────────────────────────────
# 실외 강우 채널은 단위가 제각각이다:
#   KMA_weather_500 채널 6   'precipitation' mm   = 직전 15 분 누적(rn_15m)
#   KMA_weather_500 채널 5   'precipitation' none = 감우기 0/1(rn_ox)
#   Open-Meteo `precipitation` mm                 = 직전 1 시간 합(= mm/h)
#   ecowitt·SenseCAP          mm_h                = 강우율
# 예전에는 이 값들을 그대로 `rain_threshold`(0.5) 와 비교했다 — 15 분에 0.4 mm(1.6 mm/h)
# 오는 비는 "비 없음" 이었고, 15 분 누적과 시간 합을 같은 칸에서 평균했다.
#
# 규칙(`rain_mm_h`):
#   - 강우율(mm_h·in_h)           → mm/h 그대로(in 은 25.4 배)
#   - 누적(mm·in) + 구간을 안다    → 3600/구간 배. 구간은 드라이버 표(아래) > 채널 이름
#                                   ('rain_15m'·'rn15m'·'강수15분'·'rain_1h')
#   - 감우기(단위 none·bool)       → 0/1 그대로(게이트에서 1 은 "비" — 약한 비가 아니다)
#   - 모르면 **바꾸지 않는다**      — 추측으로 곱하면 맞던 값까지 틀어진다
# ⚠ **실측은 줄이지 않는다.** 구간이 1 시간보다 긴 실측 누적(24 시간 합 등)을 나누면 지금
#   쏟아지는 비가 하루 평균으로 묽어진다 — 그대로 두면 닫는 쪽으로만 틀린다. 줄이는 것은
#   구간이 확실한 모델 값(NASA POWER 일 합계)뿐이다.
RAIN_KIND_RATE = 'rate'          # mm/h 로 맞춘 값
RAIN_KIND_SWITCH = 'switch'      # 감우기 0/1
RAIN_KIND_UNKNOWN = 'unknown'    # 단위·구간을 모름 — 값을 그대로 둔다

# 드라이버가 저장하는 강수 **누적 구간**(초) — {드라이버: {단위: 초}}. 드라이버를 고치면 여기도.
_RAIN_ACCUM_BY_DRIVER = {
    'KMA_weather_500':     {'mm': 900},     # rn_15m (kma_weather_500.py 채널 6)
    'OPEN_METEO_FORECAST': {'mm': 3600},    # hourly precipitation(직전 1 시간 합)
    'OPEN_METEO_HOURLY_FORECAST': {'mm': 3600},  # 모든 강수 채널이 1 시간 합 mm (+N h 칸 / 창 최대)
    'OPEN_METEO_DAILY_FORECAST': {'mm': 86400},  # 강수 채널이 일 합 mm (open_meteo_daily_forecast.py)
    'KMA_forecast':        {'mm': 3600},    # RN1(1 시간 강수량)
    'NASA_POWER_DAILY':    {'mm': 86400},   # PRECTOTCORR(일 합계)
}
_RAIN_SWITCH_UNITS = frozenset({'none', 'bool', 'boolean', ''})
_RAIN_RATE_UNITS = {'mm_h': 1.0, 'mm/h': 1.0, 'mm_hr': 1.0, 'in_h': 25.4, 'in/h': 25.4}
_RAIN_ACCUM_UNITS = {'mm': 1.0, 'in': 25.4}
_RAIN_NAME_PERIOD_RE = None


def _rain_period_from_name(*texts):
    """채널 이름에서 누적 구간(초) — 'rain_15m'·'rn15m'·'15-min'·'강수15분' → 900,
    'rain_1h'·'1시간' → 3600. 못 찾으면 None."""
    global _RAIN_NAME_PERIOD_RE
    import re
    if _RAIN_NAME_PERIOD_RE is None:
        _RAIN_NAME_PERIOD_RE = (
            re.compile(r'(?<!\d)(\d{1,3})[\s_-]*(?:minutes?|mins?|m|분)(?![a-z])'),
            re.compile(r'(?<!\d)(\d{1,2})[\s_-]*(?:hours?|hrs?|h|시간)(?![a-z])'))
    rx_min, rx_h = _RAIN_NAME_PERIOD_RE
    for t in texts:
        t = (str(t or '')).lower()
        if not t:
            continue
        m = rx_min.search(t)
        if m and int(m.group(1)) > 0:
            return int(m.group(1)) * 60
        m = rx_h.search(t)
        if m and int(m.group(1)) > 0:
            return int(m.group(1)) * 3600
    return None


def rain_accum_seconds(unit, measurement='', name='', driver=None):
    """누적 강수 채널 한 값이 덮는 구간(초) — 드라이버 표 > 채널 이름. 누적 단위가 아니거나 모르면 None."""
    u = (str(unit or '')).strip().lower()
    if u not in _RAIN_ACCUM_UNITS:
        return None
    return ((_RAIN_ACCUM_BY_DRIVER.get(driver or '') or {}).get(u)
            or _rain_period_from_name(measurement, name))


# @manual ai/env-control#safety-gates
def rain_unit_scale(unit, measurement='', name='', driver=None, model=False):
    """강우 채널 → (mm/h 로 바꾸는 배수, 종류). 순수 함수 — 규칙은 위 주석.

    unit: **저장 단위**(변환이 걸렸으면 변환 단위). model: 값이 예보·재분석 모델인가
    (구간이 1 시간보다 긴 누적을 줄여도 되는가).
    """
    u = (str(unit or '')).strip().lower()
    if u in _RAIN_RATE_UNITS:
        return _RAIN_RATE_UNITS[u], RAIN_KIND_RATE
    if u in _RAIN_ACCUM_UNITS:
        per = rain_accum_seconds(u, measurement, name, driver)
        if not per:
            return _RAIN_ACCUM_UNITS[u], RAIN_KIND_UNKNOWN
        factor = 3600.0 / float(per)
        if not model:
            factor = max(1.0, factor)        # 실측은 줄이지 않는다
        return _RAIN_ACCUM_UNITS[u] * factor, RAIN_KIND_RATE
    if u in _RAIN_SWITCH_UNITS:
        return 1.0, RAIN_KIND_SWITCH
    return 1.0, RAIN_KIND_UNKNOWN


def rain_mm_h(value, unit, measurement='', name='', driver=None, model=False):
    """강우 판독 하나를 게이트 단위(mm/h, 감우기는 0/1)로. None 은 None."""
    if value is None:
        return None
    factor, _kind = rain_unit_scale(unit, measurement, name, driver, model)
    return float(value) * factor


def input_driver_of(device_id):
    """Input.unique_id → 드라이버 이름(Input.device). 모르면 None. 데몬 안전 접근자 먼저."""
    if not device_id:
        return None
    try:
        from aot.databases.models import Input
        from aot.utils.database import db_retrieve_table_daemon
        row = db_retrieve_table_daemon(Input, unique_id=device_id)
        if row is not None and not isinstance(row, list):
            return getattr(row, 'device', None)
    except Exception:                                       # noqa: BLE001
        pass
    return None


def rain_channel_mm_h(value, dm, unit=None):
    """DeviceMeasurements 행의 강우 판독 → mm/h(감우기는 0/1).

    unit: 저장 단위(변환이 걸렸으면 변환 단위 — `facility_sensors._effective_raw_unit`).
    주지 않으면 행의 단위를 쓴다. 드라이버·출처는 행의 장치로 찾는다. 행이 없거나 무엇이든
    실패하면 값을 **그대로** 돌려준다(모르면 바꾸지 않는다).
    """
    if value is None or dm is None:
        return value
    try:
        if unit is None:
            unit = getattr(dm, 'unit', '') or ''
            cid = (getattr(dm, 'conversion_id', '') or '').strip()
            if cid:
                # `facility_sensors._effective_raw_unit` 과 같은 규칙 — 변환이 걸렸으면 저장 단위는
                # 변환 단위다(그 함수는 Flask 패키지 안이라 데몬 모듈에서 여기로 부른다).
                from aot.databases.models import Conversion
                from aot.utils.database import db_retrieve_table_daemon
                conv = db_retrieve_table_daemon(Conversion, unique_id=cid)
                unit = (getattr(conv, 'convert_unit_to', '') or '').strip() or unit
        driver = input_driver_of(getattr(dm, 'device_id', None))
        model = bool(driver) and driver in model_input_drivers()
        return rain_mm_h(value, unit if unit is not None else getattr(dm, 'unit', ''),
                         getattr(dm, 'measurement', '') or '', getattr(dm, 'name', '') or '',
                         driver, model)
    except Exception:                                       # noqa: BLE001
        return value


def rain_measurement_mm_h(value, measurement_id):
    """measurement_id(DeviceMeasurements.unique_id) 의 강우 판독 → mm/h(감우기는 0/1).
    채널을 못 찾으면 값을 그대로 돌려준다. 실외값 수집기(ext_context_collector)가 쓴다."""
    if value is None or not measurement_id:
        return value
    try:
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.utils.database import db_retrieve_table_daemon
        dm = db_retrieve_table_daemon(DeviceMeasurements, unique_id=measurement_id)
    except Exception:                                       # noqa: BLE001
        return value
    if dm is None or isinstance(dm, list):
        return value
    return rain_channel_mm_h(value, dm)
