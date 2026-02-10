# -*- coding: utf-8 -*-
#
# forms_trigger.py - Function Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import StringField
from wtforms import SelectField
from wtforms import validators
from wtforms import widgets
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS


class Trigger(FlaskForm):
    function_id = StringField(lazy_gettext('Function ID'), widget=widgets.HiddenInput())
    function_type = StringField(lazy_gettext('Function Type'), widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'))
    action_type = StringField(lazy_gettext('Action'))
    log_level_debug = BooleanField(lazy_gettext('Enable Debug Logging'))

    # Edge detection
    measurement = StringField(lazy_gettext('Measurement'))
    edge_detected = StringField(lazy_gettext('On Edge Detected'))

    # Sunrise/Sunset
    rise_or_set = StringField(lazy_gettext('Sunrise or Sunset'))
    latitude = DecimalField(lazy_gettext('Latitude (Decimal)'), widget=NumberInput(step='any'))
    longitude = DecimalField(lazy_gettext('Longitude (Decimal)'), widget=NumberInput(step='any'))
    location_source = SelectField(
        lazy_gettext('Location Source'),
        choices=[('manual', lazy_gettext('Manual')), ('device', lazy_gettext('Device')), ('remote', lazy_gettext('Remote'))],
        default='manual'
    )
    zenith = DecimalField(lazy_gettext('Zenith Angle'), widget=NumberInput(step='any'))
    date_offset_days = IntegerField(lazy_gettext('Date Offset (days)'), widget=NumberInput())
    time_offset_minutes = StringField(lazy_gettext('Time Offset (minutes)'))

    # Remote IR receive
    program = StringField(lazy_gettext('Program'))
    word = StringField(lazy_gettext('Command'))

    # Timer
    period = StringField(lazy_gettext('Period (sec)'))
    timer_start_offset = StringField(lazy_gettext('Start Offset (sec)'))
    timer_start_time = StringField(lazy_gettext('Start Time (HH:MM)'))
    timer_end_time = StringField(lazy_gettext('End Time (HH:MM)'))

    # Method
    trigger_actions_at_period = BooleanField(lazy_gettext('Execute Actions at Each Period'))
    trigger_actions_at_start = BooleanField(lazy_gettext('Execute Actions at Activation'))

    # Output
    unique_id_1 = StringField(lazy_gettext('Condition ID 1'))
    unique_id_2 = StringField(lazy_gettext('Condition ID 2'))
    output_state = StringField(lazy_gettext('State Condition'))
    output_duration = StringField(lazy_gettext('Condition Duration (sec)'))
    output_duty_cycle = StringField(lazy_gettext('Condition Duty Cycle (%)'))
