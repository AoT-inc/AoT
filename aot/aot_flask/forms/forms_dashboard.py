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
    choices_widgets.append(('', lazy_gettext('Add Widget')))

    for each_widget in list_widgets_sorted:
        choices_widgets.append((each_widget, dict_widgets[each_widget]['widget_name']))

    widget_type = SelectField(
        lazy_gettext('Dashboard Widget Type'),
        choices=choices_widgets,
        validators=[DataRequired()]
    )

    dashboard_id = StringField('Dashboard ID', widget=widgets.HiddenInput())
    widget_id = StringField('Widget ID', widget=widgets.HiddenInput())

    name = StringField(
        lazy_gettext('Name'),
        validators=[DataRequired()]
    )
    font_em_name = DecimalField(lazy_gettext('Font Size (em)'))
    refresh_duration = IntegerField(
        lazy_gettext('Refresh Duration (sec)'),
        validators=[validators.NumberRange(
            min=1,
            message=lazy_gettext('Refresh duration must be at least 1 second.')
        )],
        widget=NumberInput()
    )
    enable_drag_handle = BooleanField(lazy_gettext('Enable Drag Handle'))
    widget_add = SubmitField(lazy_gettext('Add'))
    widget_mod = SubmitField(lazy_gettext('Save'))
    widget_delete = SubmitField(lazy_gettext('Delete'))
    widget_duplicate = SubmitField(lazy_gettext('Duplicate'))

class DashboardConfig(FlaskForm):
    dashboard_id = StringField('Dashboard ID', widget=widgets.HiddenInput())
    name = StringField(
        lazy_gettext('Name'),
        validators=[DataRequired()]
    )
    lock = SubmitField(lazy_gettext('Lock'))
    unlock = SubmitField(lazy_gettext('Unlock'))
    dash_modify = SubmitField(lazy_gettext('Save'))
    dash_delete = SubmitField(lazy_gettext('Delete'))
    dash_duplicate = SubmitField(lazy_gettext('Duplicate'))
