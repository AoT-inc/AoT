# -*- coding: utf-8 -*-
#
# forms_custom_controller.py - 사용자 정의 컨트롤러 폼
#

from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import IntegerField
from wtforms import SelectMultipleField
from wtforms import StringField
from wtforms import widgets
from wtforms.widgets import NumberInput


class CustomController(FlaskForm):
    function_id = StringField('함수 ID', widget=widgets.HiddenInput())
    function_type = StringField('함수 유형', widget=widgets.HiddenInput())
    name = StringField('이름')
    num_channels = IntegerField('측정값 개수', widget=NumberInput())
    measurements_enabled = SelectMultipleField('활성화할 측정값 선택')
    log_level_debug = BooleanField('디버그 로그 활성화')