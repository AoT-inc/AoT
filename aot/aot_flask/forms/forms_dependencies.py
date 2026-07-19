# -*- coding: utf-8 -*-
#
# forms_dependencies.py - Dependency Management Form
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets


class Dependencies(FlaskForm):
    device = StringField(lazy_gettext('Device'), widget=widgets.HiddenInput())
    install = SubmitField(lazy_gettext('Install All Dependencies'))