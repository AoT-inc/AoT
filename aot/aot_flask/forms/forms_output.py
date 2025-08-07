# -*- coding: utf-8 -*-
#
# forms_output.py - Output Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import HiddenField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets
from wtforms.validators import DataRequired
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS
from aot.aot_flask.utils.utils_general import generate_form_output_list
from aot.utils.outputs import parse_output_information
from aot.utils.utils import sort_tuple


class OutputAdd(FlaskForm):
    choices_outputs = []
    dict_outputs = parse_output_information()
    list_outputs_sorted = generate_form_output_list(dict_outputs)
    for each_output in list_outputs_sorted:
        value = '{inp},'.format(inp=each_output)
        name = '{name}'.format(name=dict_outputs[each_output]['output_name'])

        if 'output_library' in dict_outputs[each_output]:
            name += ' ({lib})'.format(lib=dict_outputs[each_output]['output_library'])

        if 'interfaces' in dict_outputs[each_output] and dict_outputs[each_output]['interfaces']:
            for each_interface in dict_outputs[each_output]['interfaces']:
                tmp_value = '{val}{int}'.format(val=value, int=each_interface)
                tmp_name = '{name} [{int}]'.format(name=name, int=each_interface)
                choices_outputs.append((tmp_value, tmp_name))
        else:
            choices_outputs.append((value, name))

    choices_outputs = sort_tuple(choices_outputs)

    output_type = SelectField(
        choices=choices_outputs,
        validators=[DataRequired()]
    )
    output_add = SubmitField('추가')


class OutputMod(FlaskForm):
    output_id = StringField('출력 ID', widget=widgets.HiddenInput())
    output_pin = HiddenField('출력 Pin')
    name = StringField('이름', validators=[DataRequired()])
    log_level_debug = BooleanField('디버그 로그 활성화')
    location = StringField('위치')
    ftdi_location = StringField('FTDI 위치')
    uart_location = StringField('UART 위치')
    baud_rate = IntegerField('통신 속도 (Baud rate)')
    gpio_location = IntegerField('GPIO 위치', widget=NumberInput())
    i2c_location = StringField('I2C 위치')
    i2c_bus = IntegerField('I2C 버스')
    output_mod = SubmitField('저장')
    output_delete = SubmitField('삭제')
    on_submit = SubmitField('켜기')
