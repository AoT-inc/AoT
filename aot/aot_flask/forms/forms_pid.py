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
    function_id = StringField('함수 ID', widget=widgets.HiddenInput())
    function_type = StringField('함수 종류', widget=widgets.HiddenInput())
    name = StringField('이름', validators=[DataRequired()])
    measurement = StringField('측정값', validators=[DataRequired()])
    direction = SelectField(
        '방향',
        choices=[
            ('raise', '상승'),
            ('lower', '하강'),
            ('both', '상승 및 하강')
        ],
        validators=[DataRequired()]
    )
    period = DecimalField(
        '주기 (초)',
        validators=[validators.NumberRange(
            min=1,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    log_level_debug = BooleanField(
        '디버그 로그 활성화')
    start_offset = DecimalField(
        '시작 지연 (초)',
        widget=NumberInput(step='any'))
    max_measure_age = DecimalField(
        '측정값 최대 유효 기간 (초)',
        validators=[validators.NumberRange(
            min=1,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    setpoint = DecimalField(
        '목표값(Setpoint)',
        validators=[validators.NumberRange(
            min=-1000000,
            max=1000000
        )],
        widget=NumberInput(step='any')
    )
    band = DecimalField(
        lazy_gettext('범위 (+/- 목표값)'),
        widget=NumberInput(step='any'))
    send_lower_as_negative = BooleanField(lazy_gettext('하강 동작을 음수로 전송'))
    store_lower_as_negative = BooleanField(lazy_gettext('하강 동작을 음수로 저장'))
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
        '적분기 최대값',
        widget=NumberInput(step='any'))
    integrator_min = DecimalField(
        '적분기 최소값',
        widget=NumberInput(step='any'))
    raise_output_id = StringField('출력 (상승)')
    raise_output_type = StringField('동작 (상승)')
    lower_output_id = StringField('출력 (하강)')
    lower_output_type = StringField('동작 (하강)')
    setpoint_tracking_type = StringField('목표값 추적 유형')
    setpoint_tracking_method_id = StringField('목표값 추적 참조궤적')
    setpoint_tracking_input_math_id = StringField('목표값 추적 입력t')
    setpoint_tracking_max_age = DecimalField('최대 허용 시간 (초)',
        validators=[Optional()],
        widget=NumberInput(step='any'))
    pid_hold = SubmitField('고정')
    pid_pause = SubmitField('일시정지')
    pid_resume = SubmitField('복귀')


class PIDModRelayRaise(FlaskForm):
    raise_min_duration = DecimalField(
        "최소 동작 시간 (상승)",
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_max_duration = DecimalField(
        "최대 동작 시간 (상승)",
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_min_off_duration = DecimalField(
        "최소 정지 시간 (상승)",
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModRelayLower(FlaskForm):
    lower_min_duration = DecimalField(
       '최소 작동 시간 (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_max_duration = DecimalField(
        '최대 작동 시간 (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_min_off_duration = DecimalField(
        '최소 꺼짐 시간 (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModValueRaise(FlaskForm):
    raise_min_amount = DecimalField(
        '최소값 (상향)',
        widget=NumberInput(step='any')
    )
    raise_max_amount = DecimalField(
        '최대값 (상향)',
        widget=NumberInput(step='any')
    )


class PIDModValueLower(FlaskForm):
    lower_min_amount = DecimalField(
        '최소값 (하향)',
        widget=NumberInput(step='any')
    )
    lower_max_amount = DecimalField(
        '최대값 (하향)',
        widget=NumberInput(step='any')
    )


class PIDModVolumeRaise(FlaskForm):
    raise_min_amount = DecimalField(
        '최소 동작량 (상승)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    raise_max_amount = DecimalField(
        '최대 동작량 (상승)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModVolumeLower(FlaskForm):
    lower_min_amount = DecimalField(
        '최소 동작량 (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )
    lower_max_amount = DecimalField(
        '최대 동작량 (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=86400
        )],
        widget=NumberInput(step='any')
    )


class PIDModPWMRaise(FlaskForm):
    raise_min_duty_cycle = DecimalField(
        '최소 듀티 사이클 (%) (상승)',
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    raise_max_duty_cycle = DecimalField(
        '최대 듀티 사이클 (%) (상승)',
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    raise_always_min_pwm = BooleanField('항상 최소 PWM으로 동작 (상승)')


class PIDModPWMLower(FlaskForm):
    lower_min_duty_cycle = DecimalField(
        '최소 듀티 사이클 (%) (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    lower_max_duty_cycle = DecimalField(
        '최대 듀티 사이클 (%) (하강)',
        validators=[validators.NumberRange(
            min=0,
            max=100
        )],
        widget=NumberInput(step='any')
    )
    lower_always_min_pwm = BooleanField('항상 최소 PWM으로 동작 (하강)')

