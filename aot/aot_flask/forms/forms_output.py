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
from wtforms import DecimalField
from wtforms import validators
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
    output_add = SubmitField(lazy_gettext('Add'))


class OutputMod(FlaskForm):
    output_id = StringField(lazy_gettext('Output ID'), widget=widgets.HiddenInput())
    output_pin = HiddenField(lazy_gettext('Output Pin'))
    name = StringField(lazy_gettext('Name'), validators=[DataRequired()])
    log_level_debug = BooleanField(lazy_gettext('Enable Debug Logging'))
    latitude = DecimalField(
        lazy_gettext('Latitude'),
        places=8,
        rounding=None,
        validators=[validators.Optional(),
                    validators.NumberRange(min=-90, max=90)],
        widget=NumberInput(step='any')
    )
    longitude = DecimalField(
        lazy_gettext('Longitude'),
        places=8,
        rounding=None,
        validators=[validators.Optional(),
                    validators.NumberRange(min=-180, max=180)],
        widget=NumberInput(step='any')
    )
    location_source = SelectField(
        lazy_gettext('Location Source'),
        choices=[('manual', lazy_gettext('Manual')), ('device', lazy_gettext('Device')), ('remote', lazy_gettext('Remote'))],
        default='manual'
    )
    marker_icon = SelectField(
        lazy_gettext('Icon'),
        choices=[
            ('', lazy_gettext('Default')),
            ('valve', lazy_gettext('Valve')),
            ('motor', lazy_gettext('Motor')),
            ('switch', lazy_gettext('Switch')),
            ('temp', lazy_gettext('Temperature')),
            ('humidity', lazy_gettext('Humidity')),
            ('ph', lazy_gettext('pH')),
            ('ec', lazy_gettext('EC')),
            ('solar', lazy_gettext('Solar')),
            ('wind', lazy_gettext('Wind')),
            ('arrow', lazy_gettext('Arrow')),
            ('vpd', lazy_gettext('VPD')),
            ('pid', lazy_gettext('PID')),
            ('controller', lazy_gettext('Controller')),
            ('meteo', lazy_gettext('Weather Station')),
        ],
        default=''
    )
    marker_color = SelectField(
        lazy_gettext('Icon Color'),
        choices=[
            ('blue', 'Blue'),
            ('red', 'Red'),
            ('green', 'Green'),
            ('orange', 'Orange'),
            ('gray', 'Gray'),
        ],
        default='blue'
    )
    marker_size = SelectField(
        lazy_gettext('Icon Size'),
        choices=[(str(i), str(i)) for i in range(1, 6)],
        default='3'
    )
    location = StringField(lazy_gettext('Location'))
    ftdi_location = StringField(lazy_gettext('FTDI Location'))
    uart_location = StringField(lazy_gettext('UART Location'))
    baud_rate = IntegerField(lazy_gettext('Baud rate'))
    gpio_location = IntegerField(lazy_gettext('GPIO Location'), widget=NumberInput())
    i2c_location = StringField(lazy_gettext('I2C Location'))
    i2c_bus = IntegerField(lazy_gettext('I2C Bus'))
    output_mod = SubmitField(lazy_gettext('Save'))
    output_duplicate = SubmitField(lazy_gettext('Duplicate'))
    output_delete = SubmitField(lazy_gettext('Delete'))
    on_submit = SubmitField(lazy_gettext('On'))
