# -*- coding: utf-8 -*-
#
# forms_input.py - Input Flask Forms
#
import logging

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import SelectMultipleField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.validators import DataRequired
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS
from aot.aot_flask.utils.utils_general import generate_form_input_list
from aot.utils.inputs import parse_input_information

logger = logging.getLogger("aot.forms_input")


class InputAdd(FlaskForm):
    choices_builtin = []
    choices_inputs = []
    dict_inputs = parse_input_information()
    list_inputs_sorted = generate_form_input_list(dict_inputs)

    for each_input in list_inputs_sorted:
        is_aot = False
        value = '{inp},'.format(inp=each_input)
        if 'input_manufacturer' in dict_inputs[each_input] and dict_inputs[each_input]['input_manufacturer']:
            name = '{manuf}: {name}'.format(
                manuf=dict_inputs[each_input]['input_manufacturer'],
                name=dict_inputs[each_input]['input_name'])
            if dict_inputs[each_input]['input_manufacturer'] == "AoT":
                is_aot = True
        else:
            name = dict_inputs[each_input]['input_name']

        if ('measurements_name' in dict_inputs[each_input] and
                dict_inputs[each_input]['measurements_name']):
            name += ': {meas}'.format(meas=dict_inputs[each_input]['measurements_name'])

        if ('input_library' in dict_inputs[each_input] and
                dict_inputs[each_input]['input_library']):
            name += ' ({lib})'.format(lib=dict_inputs[each_input]['input_library'])

        if 'interfaces' in dict_inputs[each_input] and dict_inputs[each_input]['interfaces']:
            for each_interface in dict_inputs[each_input]['interfaces']:
                tmp_value = '{val}{int}'.format(val=value, int=each_interface)
                tmp_name = '{name} [{int}]'.format(name=name, int=each_interface)
                if is_aot:
                    choices_builtin.append((tmp_value, tmp_name))
                else:
                    choices_inputs.append((tmp_value, tmp_name))
        else:
            if is_aot:
                choices_builtin.append((value, name))
            else:
                choices_inputs.append((value, name))

    input_type = SelectField(
        choices=choices_builtin + choices_inputs,
        validators=[DataRequired()]
    )
    input_add = SubmitField('추가')


class InputMod(FlaskForm):
    input_id = StringField('입력 ID', widget=widgets.HiddenInput())
    input_measurement_id = StringField(widget=widgets.HiddenInput())
    name = StringField(
        '이름',
        validators=[DataRequired()]
    )
    unique_id = StringField(
        '고유 ID',
        validators=[DataRequired()]
    )
    period = DecimalField(
        '측정주기',
        validators=[DataRequired(),
                    validators.NumberRange(
                        min=5,
                        max=86400
        )],
        widget=NumberInput(step='any')
    )
    start_offset = DecimalField(
        '시작 지연',
        validators=[DataRequired(),
                    validators.NumberRange(
                        min=0,
                        max=86400
                    )],
        widget=NumberInput(step='any')
    )
    log_level_debug = BooleanField('디버그 로그 활성화')
    num_channels = IntegerField('측정값 개수', widget=NumberInput())
    location = StringField('위치')
    ftdi_location = StringField('FTDI 위치')
    uart_location = StringField('UART 위치')
    gpio_location = IntegerField('GPIO 위치')
    i2c_location = StringField('I2C 위치')
    i2c_bus = IntegerField('I2C 버스', widget=NumberInput())
    baud_rate = IntegerField('통신 속도 (Baud rate)', widget=NumberInput())
    power_output_id = StringField('전원 출력 장치')
    calibrate_sensor_measure = StringField('센서 교정 기준 측정값')
    resolution = IntegerField('해상도', widget=NumberInput())
    resolution_2 = IntegerField('보조 해상도', widget=NumberInput())
    sensitivity = IntegerField('민감도', widget=NumberInput())
    measurements_enabled = SelectMultipleField('활성화할 측정값')


    # 서버 옵션
    host = StringField('호스트 주소')
    port = IntegerField('포트', widget=NumberInput())
    times_check = IntegerField('체크 횟수', widget=NumberInput())
    deadline = IntegerField('제한 시간', widget=NumberInput())

    # Linux 명령어
    cmd_command = StringField('실행 명령어')

    # MAX 칩 옵션
    thermocouple_type = StringField('열전대 유형')
    ref_ohm = IntegerField('기준 저항값 (Ω)', widget=NumberInput())

    # SPI 통신 옵션
    pin_clock = IntegerField('SPI 클럭 핀', widget=NumberInput())
    pin_cs = IntegerField('SPI 칩 선택 핀 (CS)', widget=NumberInput())
    pin_mosi = IntegerField('SPI MOSI 핀', widget=NumberInput())
    pin_miso = IntegerField('SPI MISO 핀', widget=NumberInput())

    # Bluetooth 옵션
    bt_adapter = StringField('블루투스 어댑터')

    # ADC 옵션
    adc_gain = IntegerField('ADC 게인', widget=NumberInput())
    adc_resolution = IntegerField('ADC 해상도', widget=NumberInput())
    adc_sample_speed = StringField('ADC 샘플 속도')

    # Switch 옵션
    switch_edge = StringField('에지 감지')
    switch_bouncetime = IntegerField('바운스 타임 (ms)', widget=NumberInput())
    switch_reset_period = IntegerField('리셋 주기', widget=NumberInput())

    # 사전 출력 옵션
    pre_output_id = StringField('사전 출력 장치 ID')
    pre_output_duration = DecimalField(
        '사전 출력 지속 시간 (초)',
        validators=[validators.NumberRange(min=0, max=86400)],
        widget=NumberInput(step='any')
    )
    pre_output_during_measure = BooleanField('측정 중 사전 출력 유지')

    # RPM/신호 입력 옵션
    weighting = DecimalField('가중치', widget=NumberInput(step='any'))
    rpm_pulses_per_rev = DecimalField('회전당 펄스 수', widget=NumberInput(step='any'))
    sample_time = DecimalField('샘플링 시간 (초)', widget=NumberInput(step='any'))

    # SHT 옵션
    sht_voltage = StringField('SHT 센서 전압')

    input_duplicate = SubmitField('복제')
    input_mod = SubmitField('저장')
    input_delete = SubmitField('삭제')
    input_acquire_measurements = SubmitField('즉시 측정')
    input_activate = SubmitField('활성화')
    input_deactivate = SubmitField('비활성화')
