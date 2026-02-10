# -*- coding: utf-8 -*-
#
# forms_function.py - Function Flask Forms
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import DecimalField
from wtforms import BooleanField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.widgets import NumberInput


class FunctionAdd(FlaskForm):
    function_type = SelectField(lazy_gettext('Function Type'))
    function_add = SubmitField(lazy_gettext('Add'))


class FunctionMod(FlaskForm):
    function_id = StringField('Function ID', widget=widgets.HiddenInput())
    function_type = StringField('Function Type', widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'))
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

    execute_all_actions = SubmitField(lazy_gettext('Execute All Actions'))
    function_activate = SubmitField(lazy_gettext('Activate'))
    function_deactivate = SubmitField(lazy_gettext('Deactivate'))
    function_duplicate = SubmitField(lazy_gettext('Duplicate'))
    function_mod = SubmitField(lazy_gettext('Save'))
    function_delete = SubmitField(lazy_gettext('Delete'))
