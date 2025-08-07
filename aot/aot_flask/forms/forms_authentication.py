# -*- coding: utf-8 -*-
#
# forms_authentication.py - Authentication Flask Forms
#
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
    language = StringField('언어')


#
# Create Admin
#

class CreateAdmin(FlaskForm):
    username = StringField(
        '사용자 이름',
        render_kw={"placeholder": "사용자 이름"},
        validators=[DataRequired()])
    email = StringField(
        '이메일',
        render_kw={"placeholder": "이메일"},
        validators=[DataRequired()])
    password = PasswordField(
        '비밀번호',
        render_kw={"placeholder": "비밀번호"},
        validators=[DataRequired()])
    password_repeat = PasswordField(
        '비밀번호 확인',
        render_kw={"placeholder": "비밀번호 확인"},
        validators=[DataRequired()])


#
# Login
#

class Login(FlaskForm):
    aot_username = StringField(
        '사용자 이름',
        render_kw={"placeholder": "사용자 이름"},
        validators=[DataRequired()]
    )
    aot_password = PasswordField(
        '비밀번호',
        render_kw={"placeholder": "비밀번호"},
        validators=[DataRequired()]
    )
    remember = BooleanField()


#
# Forgot Password
#

class ForgotPassword(FlaskForm):
    reset_method = SelectField(
        '초기화 방식',
        choices=[
            ('file', '파일로 초기화 코드 저장'),
            ('email', '이메일로 초기화 코드 전송')],
        validators=[DataRequired()]
    )
    username = StringField(
        '사용자 이름',
        render_kw={"placeholder": "사용자 이름"})
    submit = SubmitField('제출')


class ResetPassword(FlaskForm):
    password_reset_code = StringField(
        "비밀번호 초기화 코드",
        render_kw={"placeholder": "초기화 코드"})
    password = PasswordField(
        '새 비밀번호',
        render_kw={"placeholder": "새 비밀번호"})
    password_repeat = PasswordField(
        '새 비밀번호 확인',
        render_kw={"placeholder": "새 비밀번호 확인"})
    submit = SubmitField('비밀번호 변경')


#
# Remote Admin Host Addition
#

class RemoteSetup(FlaskForm):
    remote_id = StringField('Remote Host ID', widget=widgets.HiddenInput())
    host = StringField(
        '도메인 또는 IP 주소',
        validators=[DataRequired()]
    )
    username = StringField(
        '사용자 이름',
        validators=[DataRequired()]
    )
    password = PasswordField(
        '비밀번호',
        validators=[DataRequired()]
    )
    add = SubmitField('호스트 추가')
    delete = SubmitField('호스트 삭제')


class InstallNotice(FlaskForm):
    acknowledge = SubmitField('확인했습니다')