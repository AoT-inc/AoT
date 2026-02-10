# -*- coding: utf-8 -*-
#
# forms_authentication.py - Authentication Flask Forms
#
from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import PasswordField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets
from wtforms.validators import DataRequired


#
# Language Select
#

class LanguageSelect(FlaskForm):
    language = StringField(lazy_gettext('Language'))


#
# Create Admin
#

class CreateAdmin(FlaskForm):
    username = StringField(
        lazy_gettext('Username'),
        render_kw={"placeholder": lazy_gettext("Username")},
        validators=[DataRequired()])
    email = StringField(
        lazy_gettext('Email'),
        render_kw={"placeholder": lazy_gettext("Email")},
        validators=[DataRequired()])
    password = PasswordField(
        lazy_gettext('Password'),
        render_kw={"placeholder": lazy_gettext("Password")},
        validators=[DataRequired()])
    password_repeat = PasswordField(
        lazy_gettext('Confirm Password'),
        render_kw={"placeholder": lazy_gettext("Confirm Password")},
        validators=[DataRequired()])


#
# Login
#

class Login(FlaskForm):
    aot_username = StringField(
        lazy_gettext('Username'),
        render_kw={"placeholder": lazy_gettext("Username")},
        validators=[DataRequired()]
    )
    aot_password = PasswordField(
        lazy_gettext('Password'),
        render_kw={"placeholder": lazy_gettext("Password")},
        validators=[DataRequired()]
    )
    remember = BooleanField()


#
# Forgot Password
#

class ForgotPassword(FlaskForm):
    reset_method = SelectField(
        lazy_gettext('Reset Method'),
        choices=[
            ('file', lazy_gettext('Save reset code to file')),
            ('email', lazy_gettext('Send reset code via email'))],
        validators=[DataRequired()]
    )
    username = StringField(
        lazy_gettext('Username'),
        render_kw={"placeholder": lazy_gettext("Username")})
    submit = SubmitField(lazy_gettext('Submit'))


class ResetPassword(FlaskForm):
    password_reset_code = StringField(
        lazy_gettext("Password Reset Code"),
        render_kw={"placeholder": lazy_gettext("Reset Code")})
    password = PasswordField(
        lazy_gettext('New Password'),
        render_kw={"placeholder": lazy_gettext("New Password")})
    password_repeat = PasswordField(
        lazy_gettext('Confirm New Password'),
        render_kw={"placeholder": lazy_gettext("Confirm New Password")})
    submit = SubmitField(lazy_gettext('Change Password'))


#
# Remote Admin Host Addition
#

class RemoteSetup(FlaskForm):
    remote_id = StringField('Remote Host ID', widget=widgets.HiddenInput())
    host = StringField(
        lazy_gettext('Domain or IP Address'),
        validators=[DataRequired()]
    )
    username = StringField(
        lazy_gettext('Username'),
        validators=[DataRequired()]
    )
    password = PasswordField(
        lazy_gettext('Password'),
        validators=[DataRequired()]
    )
    add = SubmitField(lazy_gettext('Add Host'))
    delete = SubmitField(lazy_gettext('Delete Host'))


class Actions(FlaskForm):
    action_type = SelectField(lazy_gettext("Action Type"))
    device_id = StringField('Device ID', widget=widgets.HiddenInput())
    function_type = StringField('function_type', widget=widgets.HiddenInput())
    action_id = StringField('action_id', widget=widgets.HiddenInput())

    add_action = SubmitField(lazy_gettext('Add'))
    save_action = SubmitField(lazy_gettext('Save'))
    delete_action = SubmitField(lazy_gettext('Delete'))


class InstallNotice(FlaskForm):
    acknowledge = SubmitField(lazy_gettext('I Acknowledge'))