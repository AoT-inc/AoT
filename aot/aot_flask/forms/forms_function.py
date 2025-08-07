# -*- coding: utf-8 -*-
#
# forms_function.py - Function Flask Forms
#
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets


class FunctionAdd(FlaskForm):
    function_type = SelectField('함수 유형')
    function_add = SubmitField('추가')


class FunctionMod(FlaskForm):
    function_id = StringField('Function ID', widget=widgets.HiddenInput())
    function_type = StringField('Function Type', widget=widgets.HiddenInput())
    name = StringField('이름')
    log_level_debug = BooleanField('디버그 로그 활성화')

    execute_all_actions = SubmitField('모든 동작 실행')
    function_activate = SubmitField('활성화')
    function_deactivate = SubmitField('비활성화')
    function_mod = SubmitField('저장')
    function_delete = SubmitField('삭제')