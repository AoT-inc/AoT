# -*- coding: utf-8 -*-
#
# forms_dashboard.py - Dashboard Flask Forms
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.validators import DataRequired
from wtforms.widgets import NumberInput

from aot.aot_flask.utils.utils_general import generate_form_widget_list
from aot.utils.widgets import parse_widget_information


class DashboardBase(FlaskForm):
    choices_widgets = []
    dict_widgets = parse_widget_information()
    list_widgets_sorted = generate_form_widget_list(dict_widgets)
    choices_widgets.append(('', lazy_gettext('위젯 추가')))

    for each_widget in list_widgets_sorted:
        choices_widgets.append((each_widget, dict_widgets[each_widget]['widget_name']))

    widget_type = SelectField(
        '대시보드 위젯 유형',
        choices=choices_widgets,
        validators=[DataRequired()]
    )

    dashboard_id = StringField('Dashboard ID', widget=widgets.HiddenInput())
    widget_id = StringField('Widget ID', widget=widgets.HiddenInput())

    name = StringField(
        '이름',
        validators=[DataRequired()]
    )
    font_em_name = DecimalField('글꼴 크기(em)')
    refresh_duration = IntegerField(
        '새로고침 간격 (초)',
        validators=[validators.NumberRange(
            min=1,
            message='새로고침 간격은 최소 1초 이상이어야 합니다.'
        )],
        widget=NumberInput()
    )
    enable_drag_handle = BooleanField('드래그 핸들 활성화')
    widget_add = SubmitField('추가')
    widget_mod = SubmitField('저장')
    widget_delete = SubmitField('삭제')


class DashboardConfig(FlaskForm):
    dashboard_id = StringField('Dashboard ID', widget=widgets.HiddenInput())
    name = StringField(
        '이름',
        validators=[DataRequired()]
    )
    lock = SubmitField('잠금')
    unlock = SubmitField('잠금 해제')
    dash_modify = SubmitField('저장')
    dash_delete = SubmitField('삭제')
    dash_duplicate = SubmitField('복제')
