# -*- coding: utf-8 -*-
#
# forms_conditional.py - Miscellaneous Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets
from wtforms.widgets import NumberInput

from aot.config import CONDITIONAL_CONDITIONS


#
# Conditionals
#

class Conditional(FlaskForm):
    function_id = StringField('Function ID', widget=widgets.HiddenInput())
    function_type = StringField('Function Type', widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'))
    conditional_import = StringField(lazy_gettext('Import Python Code'))
    conditional_initialize = StringField(lazy_gettext('Initialize Python Code'))
    conditional_statement = StringField(lazy_gettext('Python Code to Execute'))
    conditional_status = StringField(lazy_gettext('Python Code to Check Status'))
    period = DecimalField(
        lazy_gettext("Period (sec)"),
        widget=NumberInput(step='any'))
    log_level_debug = BooleanField(lazy_gettext('Enable Debug Logging'))
    use_pylint = BooleanField(lazy_gettext('Use Pylint'))
    message_include_code = BooleanField(lazy_gettext('Include Code in Messages'))
    refractory_period = DecimalField(
        lazy_gettext("Refractory Period (sec)"),
        widget=NumberInput(step='any'))
    start_offset = DecimalField(
        lazy_gettext("Start Offset (sec)"),
        widget=NumberInput(step='any'))
    pyro_timeout = DecimalField(
        lazy_gettext("Timeout (sec)"),
        widget=NumberInput(step='any'))
    condition_type = SelectField(
        lazy_gettext('Condition Type'),
        choices=[('', lazy_gettext('Please select'))] + CONDITIONAL_CONDITIONS)
    add_condition = SubmitField(lazy_gettext('Add'))


class ConditionalConditions(FlaskForm):
    conditional_id = StringField(
        'Conditional ID', widget=widgets.HiddenInput())
    conditional_condition_id = StringField(
        'Conditional Condition ID', widget=widgets.HiddenInput())

    # Measurement
    input_id = StringField('Input ID', widget=widgets.HiddenInput())
    measurement = StringField(lazy_gettext('Measurement'))
    max_age = IntegerField(
        lazy_gettext('Max Age (sec)'),
        widget=NumberInput())

    # GPIO Status
    gpio_pin = IntegerField(
        lazy_gettext("Pin Number: GPIO (BCM)"),
        widget=NumberInput())

    output_id = StringField(lazy_gettext('Output Device'))
    controller_id = StringField(lazy_gettext('Controller'))

    save_condition = SubmitField(lazy_gettext('Save'))
    delete_condition = SubmitField(lazy_gettext('Delete'))