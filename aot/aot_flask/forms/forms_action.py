# -*- coding: utf-8 -*-
#
# forms_action.py - Action Management Form
#

import logging

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets

logger = logging.getLogger("aot.forms_action")


class Actions(FlaskForm):
    action_type = SelectField(lazy_gettext("Action Type"))
    device_id = StringField('Device ID', widget=widgets.HiddenInput())
    function_type = StringField('function_type', widget=widgets.HiddenInput())
    action_id = StringField('action_id', widget=widgets.HiddenInput())

    add_action = SubmitField(lazy_gettext('Add'))
    save_action = SubmitField(lazy_gettext('Save'))
    delete_action = SubmitField(lazy_gettext('Delete'))