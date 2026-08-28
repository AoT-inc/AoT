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
from aot.aot_flask.utils.utils_device_catalog import output_add_choices


class OutputAdd(FlaskForm):
    """출력 추가 드롭다운.

    선택지는 utils_device_catalog 가 optgroup + 검색 토큰까지 붙여서 만든다.
    클래스 본문이 아니라 __init__ 에서 채우는 이유는 InputAdd 와 같다(그룹
    라벨이 요청 언어로 번역되어야 하는데 클래스 본문은 import 시점에 한 번만
    돈다).
    """
    output_type = SelectField(
        choices=[],
        validators=[DataRequired()]
    )
    output_add = SubmitField(lazy_gettext('Add'))

    def __init__(self, *args, **kwargs):
        super(OutputAdd, self).__init__(*args, **kwargs)
        self.output_type.choices = output_add_choices()


class OutputMod(FlaskForm):
    output_id = StringField(lazy_gettext('Output ID'), widget=widgets.HiddenInput())
    output_pin = HiddenField(lazy_gettext('Output Pin'))
    name = StringField(lazy_gettext('Name'), validators=[DataRequired()])
    tab_id = StringField(lazy_gettext('Tab'))
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
