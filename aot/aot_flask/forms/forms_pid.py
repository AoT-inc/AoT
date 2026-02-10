# -*- coding: utf-8 -*-
#
# forms_pid.py - PID Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.validators import DataRequired
from wtforms.validators import Optional
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS


class PIDModBase(FlaskForm):
    function_id = StringField(lazy_gettext('Function ID'), widget=widgets.HiddenInput())
    function_type = StringField(lazy_gettext('Function Type'), widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'), validators=[DataRequired()])
    measurement = StringField(lazy_gettext('Measurement'), validators=[DataRequired()])
    direction = SelectField(
        lazy_gettext('Direction'),
        choices=[
            ('raise', lazy_gettext('Raise')),
            ('lower', lazy_gettext('Lower')),
            ('both', lazy_gettext('Both'))
        ],
        validators=[DataRequired()]
    )
    period = DecimalField(
        lazy_gettext('Period (sec)'),
        validators=[validators.NumberRange(
            min=1,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    log_level_debug = BooleanField(
        lazy_gettext('Enable Debug Logging'))
    start_offset = DecimalField(
        lazy_gettext('Start Offset (sec)'),
        widget=NumberInput(step='any'))
    max_measure_age = DecimalField(
        lazy_gettext('Max Measurement Age (sec)'),
        validators=[validators.NumberRange(
            min=1,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    setpoint = DecimalField(
        lazy_gettext('Setpoint'),
        validators=[validators.NumberRange(
            min=-1000000,
            max=1000000
        )],
        widget=NumberInput(step='any')
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
    band = DecimalField(
        lazy_gettext('Band (+/- setpoint)'),
        widget=NumberInput(step='any'))
    send_lower_as_negative = BooleanField(lazy_gettext('Send Lower Actions as Negative'))
    store_lower_as_negative = BooleanField(lazy_gettext('Store Lower Actions as Negative'))
    k_p = DecimalField(
        lazy_gettext('Kp Gain'),
        validators=[validators.NumberRange(
            min=0
        )],
        widget=NumberInput(step='any')
    )
    k_i = DecimalField(
        lazy_gettext('Ki Gain'),
        validators=[validators.NumberRange(
            min=0
        )],
        widget=NumberInput(step='any')
    )
    k_d = DecimalField(
        lazy_gettext('Kd Gain'),
        validators=[validators.NumberRange(
            min=0
        )],
        widget=NumberInput(step='any')
    )
    integrator_max = DecimalField(
        lazy_gettext('Integrator Max'),
        widget=NumberInput(step='any'))
    integrator_min = DecimalField(
        lazy_gettext('Integrator Min'),
        widget=NumberInput(step='any'))
    raise_output_id = StringField(lazy_gettext('Output (Raise)'))
    raise_output_type = StringField(lazy_gettext('Action (Raise)'))
    lower_output_id = StringField(lazy_gettext('Output (Lower)'))
    lower_output_type = StringField(lazy_gettext('Action (Lower)'))
    setpoint_tracking_type = StringField(lazy_gettext('Setpoint Tracking Type'))
    setpoint_tracking_method_id = StringField(lazy_gettext('Setpoint Tracking Reference Trajectory'))
    setpoint_tracking_input_math_id = StringField(lazy_gettext('Setpoint Tracking Input'))
    setpoint_tracking_max_age = DecimalField(lazy_gettext('Max Age (sec)'),
        validators=[Optional()],
        widget=NumberInput(step='any'))
    pid_hold = SubmitField(lazy_gettext('Hold'))
    pid_pause = SubmitField(lazy_gettext('Pause'))
    pid_resume = SubmitField(lazy_gettext('Resume'))


class PIDModRelayRaise(FlaskForm):
    raise_min_duration = DecimalField(
        lazy_gettext("Min Duration (Raise)"),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_max_duration = DecimalField(
        lazy_gettext("Max Duration (Raise)"),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_min_off_duration = DecimalField(
        lazy_gettext("Min Off Duration (Raise)"),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModRelayLower(FlaskForm):
    lower_min_duration = DecimalField(
       lazy_gettext('Min Duration (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_max_duration = DecimalField(
        lazy_gettext('Max Duration (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_min_off_duration = DecimalField(
        lazy_gettext('Min Off Duration (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModValueRaise(FlaskForm):
    raise_min_amount = DecimalField(
        lazy_gettext('Min Value (Raise)'),
        widget=NumberInput(step='any')
    )
    raise_max_amount = DecimalField(
        lazy_gettext('Max Value (Raise)'),
        widget=NumberInput(step='any')
    )


class PIDModValueLower(FlaskForm):
    lower_min_amount = DecimalField(
        lazy_gettext('Min Value (Lower)'),
        widget=NumberInput(step='any')
    )
    lower_max_amount = DecimalField(
        lazy_gettext('Max Value (Lower)'),
        widget=NumberInput(step='any')
    )


class PIDModVolumeRaise(FlaskForm):
    raise_min_amount = DecimalField(
        lazy_gettext('Min Amount (Raise)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_max_amount = DecimalField(
        lazy_gettext('Max Amount (Raise)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModVolumeLower(FlaskForm):
    lower_min_amount = DecimalField(
        lazy_gettext('Min Amount (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_max_amount = DecimalField(
        lazy_gettext('Max Amount (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModPWMRaise(FlaskForm):
    raise_min_duty_cycle = DecimalField(
        lazy_gettext('Min Duty Cycle (%) (Raise)'),
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    raise_max_duty_cycle = DecimalField(
        lazy_gettext('Max Duty Cycle (%) (Raise)'),
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    raise_always_min_pwm = BooleanField(lazy_gettext('Always Operate at Min PWM (Raise)'))


class PIDModPWMLower(FlaskForm):
    lower_min_duty_cycle = DecimalField(
        lazy_gettext('Min Duty Cycle (%) (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    lower_max_duty_cycle = DecimalField(
        lazy_gettext('Max Duty Cycle (%) (Lower)'),
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    lower_always_min_pwm = BooleanField(lazy_gettext('Always Operate at Min PWM (Lower)'))
