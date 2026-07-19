# -*- coding: utf-8 -*-
#
# forms_ai_context.py - AI Context Record Flask Forms
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, SubmitField, widgets
from wtforms.validators import DataRequired


class ContextRecordAdd(FlaskForm):
    """Form to add a new AI Context Record."""
    parameter_name = StringField(
        lazy_gettext('Parameter Name'),
        validators=[DataRequired()]
    )
    source_type = SelectField(
        lazy_gettext('Source Type'),
        choices=[
            ("manual", lazy_gettext("Manual entry")),
            ("free_text", lazy_gettext("Note/Description")),
            ("url", lazy_gettext("External URL")),
        ],
        validators=[DataRequired()]
    )
    raw_input = TextAreaField(
        lazy_gettext('Value / URL / Text'),
        validators=[DataRequired()]
    )
    notes = StringField(
        lazy_gettext('Notes'),
    )
    record_add = SubmitField(lazy_gettext('Add'))


class ContextRecordMod(FlaskForm):
    """Form to modify/action an existing AI Context Record."""
    record_id = StringField(
        lazy_gettext('Record ID'),
        widget=widgets.HiddenInput()
    )
    parameter_name = StringField(
        lazy_gettext('Parameter Name'),
        validators=[DataRequired()]
    )
    raw_input = TextAreaField(
        lazy_gettext('Value'),
        validators=[DataRequired()]
    )
    notes = StringField(
        lazy_gettext('Notes'),
    )
    record_mod = SubmitField(lazy_gettext('Save'))
    record_delete = SubmitField(lazy_gettext('Delete'))
    record_confirm = SubmitField(lazy_gettext('Confirm'))
    record_reject = SubmitField(lazy_gettext('Reject'))
