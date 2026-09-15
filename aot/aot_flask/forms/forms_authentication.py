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


def _strip_whitespace(value):
    """모바일 키보드 자동완성이 아이디 끝에 붙이는 공백을 제거한다.

    안드로이드 Gboard 등은 제안 단어를 탭하면 다음 단어를 위해 뒤 공백을
    같이 넣는다. 아이디 필드는 그 공백까지 그대로 값이 되어 로그인 조회가
    "unknown username"으로 실패하는데, 사용자에게는 방금 만든 계정으로
    로그인이 안 되는 것처럼 보인다(2026-09-15 실제 사고, 원격 사용자만
    재현·개발자 PC는 공백 없이 정상).
    """
    return value.strip() if isinstance(value, str) else value


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
        validators=[DataRequired()],
        filters=[_strip_whitespace])
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
        validators=[DataRequired()],
        filters=[_strip_whitespace]
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
        render_kw={"placeholder": lazy_gettext("Username")},
        filters=[_strip_whitespace])
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