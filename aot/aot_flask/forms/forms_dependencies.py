# -*- coding: utf-8 -*-
#
# forms_dependencies.py - 의존성 관리 폼
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets


class Dependencies(FlaskForm):
    device = StringField('장치', widget=widgets.HiddenInput())
    install = SubmitField('모든 의존성 설치하기')