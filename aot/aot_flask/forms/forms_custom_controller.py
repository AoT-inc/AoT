# -*- coding: utf-8 -*-
#
# forms_custom_controller.py - Custom Controller Form
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, SelectMultipleField, StringField, DecimalField, SelectField, validators, widgets
from wtforms.widgets import NumberInput


class CustomController(FlaskForm):
    function_id = StringField(lazy_gettext('Function ID'), widget=widgets.HiddenInput())
    function_type = StringField(lazy_gettext('Function Type'), widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'))
    num_channels = IntegerField(lazy_gettext('Number of Channels'), widget=NumberInput())
    measurements_enabled = SelectMultipleField(lazy_gettext('Select Measurements to Enable'))
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
