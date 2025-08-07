# -*- coding: utf-8 -*-
#
# forms_action.py - 액션 관리 폼
#

import logging

from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets

logger = logging.getLogger("aot.forms_action")


class Actions(FlaskForm):
    action_type = SelectField("동작 유형")
    device_id = StringField('Device ID', widget=widgets.HiddenInput())
    function_type = StringField('function_type', widget=widgets.HiddenInput())
    action_id = StringField('action_id', widget=widgets.HiddenInput())

    add_action = SubmitField('추가')
    save_action = SubmitField('저장')
    delete_action = SubmitField('삭제')