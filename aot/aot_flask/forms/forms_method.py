# -*- coding: utf-8 -*-
#
# forms_method.py - Method Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import DecimalField
from wtforms import HiddenField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets
from wtforms.validators import DataRequired
from wtforms.widgets import NumberInput

from aot.config import METHODS
from aot.config_translations import TRANSLATIONS


class MethodCreate(FlaskForm):
    name = StringField('이름')
    method_type = SelectField(
        choices=METHODS,
        validators=[DataRequired()]
    )
    controller_type = HiddenField('Controller Type')
    Submit = SubmitField('추가')


class MethodAdd(FlaskForm):
    method_id = StringField(
        'Method ID', widget=widgets.HiddenInput())
    method_type = HiddenField('Method Type')
    daily_time_start = StringField(
        '시작 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"}
    )
    daily_time_end = StringField(
        '종료 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"}
    )
    time_start = StringField(
        '시작 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"}
    )
    time_end = StringField(
        '종료 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"}
    )
    setpoint_start = DecimalField(
        '시작 설정값',
        widget=NumberInput(step='any'))
    setpoint_end = DecimalField(
        '종료 설정값 (선택)',
        widget=NumberInput(step='any'))
    duration = DecimalField(
        '지속 시간 (초)',
        widget=NumberInput(step='any'))
    duration_end = DecimalField(
        '종료까지 지속 시간 (초)',
        widget=NumberInput(step='any'))
    amplitude = DecimalField(
        '진폭',
        widget=NumberInput(step='any'))
    frequency = DecimalField(
        '주파수',
        widget=NumberInput(step='any'))
    shift_angle = DecimalField(
        '위상각 이동 (0~360)',
        widget=NumberInput(step='any'))
    shiftY = DecimalField(
        'Y축 이동',
        widget=NumberInput(step='any'))
    x0 = DecimalField('X0', widget=NumberInput(step='any'))
    y0 = DecimalField('Y0', widget=NumberInput(step='any'))
    x1 = DecimalField('X1', widget=NumberInput(step='any'))
    y1 = DecimalField('Y1', widget=NumberInput(step='any'))
    x2 = DecimalField('X2', widget=NumberInput(step='any'))
    y2 = DecimalField('Y2', widget=NumberInput(step='any'))
    x3 = DecimalField('X3', widget=NumberInput(step='any'))
    y3 = DecimalField('Y3', widget=NumberInput(step='any'))
    output_daily_time = StringField(
        '출력 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"})
    output_time = StringField(
        '출력 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"})
    save = SubmitField('메서드에 추가')
    restart = SubmitField('반복 옵션 설정')
    linked_method_id = StringField('Linked Method Id')


class MethodMod(FlaskForm):
    method_id = StringField('Method ID', widget=widgets.HiddenInput())
    method_data_id = StringField('Method Data ID', widget=widgets.HiddenInput())
    method_type = HiddenField('Method Type')
    name = StringField('이름')
    daily_time_start = StringField(
        '시작 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"})
    daily_time_end = StringField(
        '종료 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"})
    time_start = StringField(
        '시작 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"})
    time_end = StringField(
        '종료 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"})
    output_daily_time = StringField(
        '출력 시간 (HH:MM:SS)',
        render_kw={"placeholder": "HH:MM:SS"})
    output_time = StringField(
        '출력 일시 (YYYY-MM-DD HH:MM:SS)',
        render_kw={"placeholder": "YYYY-MM-DD HH:MM:SS"})
    duration = DecimalField(
        '지속 시간 (초)',
        widget=NumberInput(step='any'))
    duration_end = DecimalField(
        '종료까지 지속 시간 (초)',
        widget=NumberInput(step='any'))
    setpoint_start = DecimalField(
        '시작 설정값',
        widget=NumberInput(step='any'))
    setpoint_end = DecimalField(
        '종료 설정값',
        widget=NumberInput(step='any'))
    rename = SubmitField('이름 변경')
    save = SubmitField('저장')
    delete = SubmitField('삭제')