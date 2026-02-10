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
from aot.config import PATH_INPUTS_GIS
from aot.aot_flask.utils.utils_general import generate_form_input_list
from aot.utils.inputs import parse_input_information

logger = logging.getLogger("aot.forms_input")


class InputAdd(FlaskForm):
    choices_builtin = []
    choices_inputs = []
    dict_inputs = parse_input_information()
    list_inputs_sorted = generate_form_input_list(dict_inputs)

    for each_input in list_inputs_sorted:
        # Exclude input_gis from the list
        if dict_inputs[each_input].get('file_path', '').startswith(PATH_INPUTS_GIS):
            continue

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
    input_add = SubmitField(lazy_gettext('Add'))


class InputMod(FlaskForm):
    input_id = StringField(lazy_gettext('Input ID'), widget=widgets.HiddenInput())
    input_measurement_id = StringField(widget=widgets.HiddenInput())
    name = StringField(
        lazy_gettext('Name'),
        validators=[DataRequired()]
    )
    unique_id = StringField(
        lazy_gettext('Unique ID'),
        validators=[DataRequired()]
    )
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
    period = DecimalField(
        lazy_gettext('Measurement Period'),
        validators=[DataRequired(),
                    validators.NumberRange(
                        min=5,
                        max=86400
        )],
        widget=NumberInput(step='any')
    )
    start_offset = DecimalField(
        lazy_gettext('Start Offset'),
        validators=[DataRequired(),
                    validators.NumberRange(
                        min=0,
                        max=86400
                    )],
        widget=NumberInput(step='any')
    )
    log_level_debug = BooleanField(lazy_gettext('Enable Debug Logging'))
    num_channels = IntegerField(lazy_gettext('Number of Channels'), widget=NumberInput())
    location = StringField(lazy_gettext('Location'))
    ftdi_location = StringField(lazy_gettext('FTDI Location'))
    uart_location = StringField(lazy_gettext('UART Location'))
    gpio_location = IntegerField(lazy_gettext('GPIO Location'))
    i2c_location = StringField(lazy_gettext('I2C Location'))
    i2c_bus = IntegerField(lazy_gettext('I2C Bus'), widget=NumberInput())
    baud_rate = IntegerField(lazy_gettext('Baud rate'), widget=NumberInput())
    power_output_id = StringField(lazy_gettext('Power Output Device'))
    calibrate_sensor_measure = StringField(lazy_gettext('Sensor Calibration Reference Measurement'))
    resolution = IntegerField(lazy_gettext('Resolution'), widget=NumberInput())
    resolution_2 = IntegerField(lazy_gettext('Secondary Resolution'), widget=NumberInput())
    sensitivity = IntegerField(lazy_gettext('Sensitivity'), widget=NumberInput())
    measurements_enabled = SelectMultipleField(lazy_gettext('Select Measurements to Enable'))


    # Server options
    host = StringField(lazy_gettext('Host Address'))
    port = IntegerField(lazy_gettext('Port'), widget=NumberInput())
    times_check = IntegerField(lazy_gettext('Check Count'), widget=NumberInput())
    deadline = IntegerField(lazy_gettext('Deadline'), widget=NumberInput())

    # Linux command
    cmd_command = StringField(lazy_gettext('Command to Execute'))

    # MAX chip options
    thermocouple_type = StringField(lazy_gettext('Thermocouple Type'))
    ref_ohm = IntegerField(lazy_gettext('Reference Resistance (Ω)'), widget=NumberInput())

    # SPI communication options
    pin_clock = IntegerField(lazy_gettext('SPI Clock Pin'), widget=NumberInput())
    pin_cs = IntegerField(lazy_gettext('SPI Chip Select Pin (CS)'), widget=NumberInput())
    pin_mosi = IntegerField(lazy_gettext('SPI MOSI Pin'), widget=NumberInput())
    pin_miso = IntegerField(lazy_gettext('SPI MISO Pin'), widget=NumberInput())

    # Bluetooth options
    bt_adapter = StringField(lazy_gettext('Bluetooth Adapter'))

    # ADC options
    adc_gain = IntegerField(lazy_gettext('ADC Gain'), widget=NumberInput())
    adc_resolution = IntegerField(lazy_gettext('ADC Resolution'), widget=NumberInput())
    adc_sample_speed = StringField(lazy_gettext('ADC Sample Speed'))

    # Switch options
    switch_edge = StringField(lazy_gettext('Edge Detection'))
    switch_bouncetime = IntegerField(lazy_gettext('Bounce Time (ms)'), widget=NumberInput())
    switch_reset_period = IntegerField(lazy_gettext('Reset Period'), widget=NumberInput())

    # Pre-output options
    pre_output_id = StringField(lazy_gettext('Pre-output Device ID'))
    pre_output_duration = DecimalField(
        lazy_gettext('Pre-output Duration (sec)'),
        validators=[validators.NumberRange(min=0, max=86400)],
        widget=NumberInput(step='any')
    )
    pre_output_during_measure = BooleanField(lazy_gettext('Keep Pre-output During Measurement'))

    # RPM/signal input options
    weighting = DecimalField(lazy_gettext('Weighting'), widget=NumberInput(step='any'))
    rpm_pulses_per_rev = DecimalField(lazy_gettext('Pulses Per Revolution'), widget=NumberInput(step='any'))
    sample_time = DecimalField(lazy_gettext('Sampling Time (sec)'), widget=NumberInput(step='any'))

    # SHT options
    sht_voltage = StringField(lazy_gettext('SHT Sensor Voltage'))

    input_duplicate = SubmitField(lazy_gettext('Duplicate'))
    input_mod = SubmitField(lazy_gettext('Save'))
    input_delete = SubmitField(lazy_gettext('Delete'))
    input_acquire_measurements = SubmitField(lazy_gettext('Measure Now'))
    input_activate = SubmitField(lazy_gettext('Activate'))
    input_deactivate = SubmitField(lazy_gettext('Deactivate'))
