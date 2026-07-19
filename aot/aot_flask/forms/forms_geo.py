# -*- coding: utf-8 -*-
#
# forms_geo.py - GIS Input Flask Forms
#
import logging

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms import SubmitField
from wtforms import SelectField
from wtforms import widgets
from wtforms.validators import DataRequired

from aot.utils.inputs import parse_input_information

logger = logging.getLogger("aot.forms_geo")


class GISInputAdd(FlaskForm):
    """Form to Add a new GIS Input"""
    input_type = SelectField(
        lazy_gettext('Select GIS Service'),
        choices=[],
        validators=[DataRequired()]
    )
    
    def __init__(self, *args, **kwargs):
        super(GISInputAdd, self).__init__(*args, **kwargs)
        # Dynamic Population to catch new modules
        dict_inputs = parse_input_information()
        choices_gis = []
        for key, val in dict_inputs.items():
            if key.startswith('gis_'):
                choices_gis.append((key, val.get('input_name', key)))
        self.input_type.choices = sorted(choices_gis, key=lambda x: x[1])
    input_add = SubmitField(lazy_gettext('Add'))


class GISInputMod(FlaskForm):
    """Form to Modify an existing GIS Input"""
    input_id = StringField(lazy_gettext('Input ID'), widget=widgets.HiddenInput())
    
    # Core fields for GIS
    name = StringField(
        lazy_gettext('Name'),
        validators=[DataRequired()]
    )
    
    # Custom options are handled dynamically in the template/utils

    input_mod = SubmitField(lazy_gettext('Save'))
    input_delete = SubmitField(lazy_gettext('Delete'))
