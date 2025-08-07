# -*- coding: utf-8 -*-
#
# forms_settings.py - Settings Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import FileField
from wtforms import IntegerField
from wtforms import PasswordField
from wtforms import SelectMultipleField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.fields import EmailField
from wtforms.validators import DataRequired
from wtforms.validators import Optional
from wtforms.widgets import NumberInput
from wtforms.widgets import TextArea

from aot.config_translations import TRANSLATIONS


#
# Settings (Email)
#

class SettingsEmail(FlaskForm):
    smtp_host = StringField(
        lazy_gettext('SMTP 호스트'),
        render_kw={"placeholder": lazy_gettext('SMTP 호스트')},
        validators=[DataRequired()]
    )
    smtp_port = IntegerField(
        lazy_gettext('SMTP 포트'),
        validators=[Optional()]
    )
    smtp_protocol = StringField(
        lazy_gettext('SMTP 프로토콜'),
        validators=[DataRequired()]
    )
    smtp_ssl = BooleanField('SSL 활성화')
    smtp_user = StringField(
        lazy_gettext('SMTP 사용자'),
        render_kw={"placeholder": lazy_gettext('SMTP 사용자')},
        validators=[DataRequired()]
    )
    smtp_password = PasswordField(
        lazy_gettext('SMTP 비밀번호'),
        render_kw={"placeholder": TRANSLATIONS['password']['title']}
    )
    smtp_from_email = EmailField(
        lazy_gettext('보내는 이메일'),
        render_kw={"placeholder": TRANSLATIONS['email']['title']},
        validators=[
            DataRequired(),
            validators.Email()
        ]
    )
    smtp_hourly_max = IntegerField(
        lazy_gettext('최대 이메일 전송 수 (시간당)'),
        render_kw={"placeholder": lazy_gettext('최대 이메일 전송 수 (시간당)')},
        validators=[validators.NumberRange(
            min=1,
            message=lazy_gettext('최소 1개 이상의 이메일을 전송할 수 있어야 합니다.')
        )],
        widget=NumberInput()
    )
    send_test = SubmitField(lazy_gettext('테스트 이메일 전송'))
    send_test_to_email = EmailField(
        lazy_gettext('테스트 이메일 수신자'),
        render_kw={"placeholder": lazy_gettext('수신 이메일 주소')},
        validators=[
            validators.Email(),
            validators.Optional()
        ]
    )
    save = SubmitField('저장')



#
# Settings (General)
#

class SettingsGeneral(FlaskForm):
    landing_page = StringField(lazy_gettext('시작 페이지'))
    index_page = StringField(lazy_gettext('인덱스 페이지'))
    language = StringField(lazy_gettext('언어'))
    rpyc_timeout = StringField(lazy_gettext('Pyro 타임아웃'))
    custom_css = StringField(lazy_gettext('사용자 정의 CSS'), widget=TextArea())
    custom_layout = StringField(lazy_gettext('사용자 정의 레이아웃'), widget=TextArea())
    brand_display = StringField(lazy_gettext('브랜드 표시'))
    title_display = StringField(lazy_gettext('제목 표시'))
    hostname_override = StringField(lazy_gettext('브랜드 텍스트'))
    brand_image = FileField(lazy_gettext('브랜드 이미지'))
    brand_image_height = IntegerField(lazy_gettext('브랜드 이미지 높이'))
    favicon_display = StringField(lazy_gettext('파비콘 표시'))
    brand_favicon = FileField(lazy_gettext('파비콘 이미지'))
    daemon_debug_mode = BooleanField(lazy_gettext('데몬 디버그 로깅 활성화'))
    force_https = BooleanField(lazy_gettext('HTTPS 강제 적용'))
    hide_success = BooleanField(lazy_gettext('성공 메시지 숨기기'))
    hide_info = BooleanField(lazy_gettext('정보 메시지 숨기기'))
    hide_warning = BooleanField(lazy_gettext('경고 메시지 숨기기'))
    hide_tooltips = BooleanField(lazy_gettext('툴팁 숨기기'))

    use_database = StringField(lazy_gettext('데이터베이스'))
    measurement_db_retention_policy = StringField(lazy_gettext('데이터 보관 정책'))
    measurement_db_host = StringField(lazy_gettext('데이터베이스 호스트명'))
    measurement_db_port = IntegerField(lazy_gettext('포트'))
    measurement_db_dbname = StringField(lazy_gettext('데이터베이스 이름'))
    measurement_db_user = StringField(lazy_gettext('데이터베이스 사용자 이름'))
    measurement_db_password = PasswordField(lazy_gettext('데이터베이스 비밀번호'))

    grid_cell_height = IntegerField(
        lazy_gettext('그리드 셀 높이 (px)'), widget=NumberInput())
    max_amps = DecimalField(
        lazy_gettext('최대 전류 (A)'), widget=NumberInput(step='any'))
    output_stats_volts = IntegerField(
        lazy_gettext('전압'), widget=NumberInput())
    output_stats_cost = DecimalField(
        lazy_gettext('kWh당 비용'), widget=NumberInput(step='any'))
    output_stats_currency = StringField(lazy_gettext('통화 단위'))
    output_stats_day_month = StringField(lazy_gettext('월별 기준 일'))
    output_usage_report_gen = BooleanField(lazy_gettext('사용량/비용 보고서 생성'))
    output_usage_report_span = StringField(lazy_gettext('보고서 생성 기간'))
    output_usage_report_day = IntegerField(
        lazy_gettext('보고서 생성 요일/월일'), widget=NumberInput())
    output_usage_report_hour = IntegerField(
        lazy_gettext('보고서 생성 시간'),
        validators=[validators.NumberRange(
            min=0,
            max=23,
            message=lazy_gettext("시간 범위: 0-23")
        )],
        widget=NumberInput()
    )
    stats_opt_out = BooleanField(lazy_gettext('통계 수집 거부'))
    enable_upgrade_check = BooleanField(lazy_gettext('업데이트 확인 활성화'))
    net_test_ip = StringField(lazy_gettext('인터넷 테스트 IP 주소'))
    net_test_port = IntegerField(
        lazy_gettext('인터넷 테스트 포트'), widget=NumberInput())
    net_test_timeout = IntegerField(
        lazy_gettext('인터넷 테스트 타임아웃'), widget=NumberInput())

    sample_rate_controller_conditional = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('Conditional')),
        widget=NumberInput(step='any'))
    sample_rate_controller_function = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('Function')),
        widget=NumberInput(step='any'))
    sample_rate_controller_input = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('Input')),
        widget=NumberInput(step='any'))
    sample_rate_controller_output = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('Output')),
        widget=NumberInput(step='any'))
    sample_rate_controller_pid = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('PID')),
        widget=NumberInput(step='any'))
    sample_rate_controller_widget = DecimalField(
        "{} ({}): {}".format(lazy_gettext('Sample Rate'), lazy_gettext('Seconds'), lazy_gettext('Widget')),
        widget=NumberInput(step='any'))

    settings_general_save = SubmitField('저장')


#
# Settings (Controller)
#

class Controller(FlaskForm):
    import_controller_file = FileField()
    import_controller_upload = SubmitField(lazy_gettext('컨트롤러 모듈 가져오기'))


class ControllerDel(FlaskForm):
    controller_id = StringField(widget=widgets.HiddenInput())
    delete_controller = SubmitField('삭제')


#
# Settings (Action)
#

class Action(FlaskForm):
    import_action_file = FileField()
    import_action_upload = SubmitField(lazy_gettext('동작 모듈 가져오기'))


class ActionDel(FlaskForm):
    action_id = StringField(widget=widgets.HiddenInput())
    delete_action = SubmitField('삭제')


#
# Settings (Input)
#

class Input(FlaskForm):
    import_input_file = FileField()
    import_input_upload = SubmitField(lazy_gettext('입력 모듈 가져오기'))


class InputDel(FlaskForm):
    input_id = StringField(widget=widgets.HiddenInput())
    delete_input = SubmitField('삭제')


#
# Settings (Output)
#

class Output(FlaskForm):
    import_output_file = FileField()
    import_output_upload = SubmitField(lazy_gettext('출력 모듈 가져오기'))


class OutputDel(FlaskForm):
    output_id = StringField(widget=widgets.HiddenInput())
    delete_output = SubmitField('삭제')


#
# Settings (Widget)
#

class Widget(FlaskForm):
    import_widget_file = FileField()
    import_widget_upload = SubmitField(lazy_gettext('위젯 모듈 가져오기'))


class WidgetDel(FlaskForm):
    widget_id = StringField(widget=widgets.HiddenInput())
    delete_widget = SubmitField('삭제')


#
# Settings (Measurement)
#

class MeasurementAdd(FlaskForm):
    id = StringField(
        lazy_gettext('측정값 ID'), validators=[DataRequired()])
    name = StringField(
        lazy_gettext('측정값 이름'), validators=[DataRequired()])
    units = SelectMultipleField(lazy_gettext('측정값 단위'))
    add_measurement = SubmitField(lazy_gettext('측정값 추가'))


class MeasurementMod(FlaskForm):
    measurement_id = StringField('측정값 ID', widget=widgets.HiddenInput())
    id = StringField(lazy_gettext('측정값 ID'))
    name = StringField(lazy_gettext('측정값 이름'))
    units = SelectMultipleField(lazy_gettext('측정값 단위'))
    save_measurement = SubmitField('저장')
    delete_measurement = SubmitField('삭제')


class UnitAdd(FlaskForm):
    id = StringField(lazy_gettext('단위 ID'), validators=[DataRequired()])
    name = StringField(
        lazy_gettext('단위 이름'), validators=[DataRequired()])
    unit = StringField(
        lazy_gettext('단위 기호'), validators=[DataRequired()])
    add_unit = SubmitField(lazy_gettext('단위 추가'))


class UnitMod(FlaskForm):
    unit_id = StringField('단위 ID', widget=widgets.HiddenInput())
    id = StringField(lazy_gettext('단위 ID'))
    name = StringField(lazy_gettext('단위 이름'))
    unit = StringField(lazy_gettext('단위 기호'))
    save_unit = SubmitField('저장')
    delete_unit = SubmitField('삭제')


class ConversionAdd(FlaskForm):
    convert_unit_from = StringField(
        lazy_gettext('변환 전 단위'), validators=[DataRequired()])
    convert_unit_to = StringField(
        lazy_gettext('변환 후 단위'), validators=[DataRequired()])
    equation = StringField(
        lazy_gettext('변환식'), validators=[DataRequired()])
    add_conversion = SubmitField(lazy_gettext('변환식 추가'))


class ConversionMod(FlaskForm):
    conversion_id = StringField('변환식 ID', widget=widgets.HiddenInput())
    convert_unit_from = StringField(lazy_gettext('변환 전 단위'))
    convert_unit_to = StringField(lazy_gettext('변환 후 단위'))
    equation = StringField(lazy_gettext('변환식'))
    save_conversion = SubmitField('저장')
    delete_conversion = SubmitField('삭제')


#
# Settings (User)
#

class UserRoles(FlaskForm):
    name = StringField(
        lazy_gettext('역할 이름'), validators=[DataRequired()])
    view_logs = BooleanField(lazy_gettext('로그 보기'))
    view_stats = BooleanField(lazy_gettext('통계 보기'))
    view_camera = BooleanField(lazy_gettext('카메라 보기'))
    view_settings = BooleanField(lazy_gettext('설정 보기'))
    edit_users = BooleanField(lazy_gettext('사용자 수정'))
    edit_controllers = BooleanField(lazy_gettext('컨트롤러 수정'))
    edit_settings = BooleanField(lazy_gettext('설정 수정'))
    reset_password = BooleanField(lazy_gettext('비밀번호 초기화'))
    role_id = StringField('역할 ID', widget=widgets.HiddenInput())
    user_role_add = SubmitField(lazy_gettext('역할 추가'))
    user_role_save = SubmitField('저장')
    user_role_delete = SubmitField('삭제')


class User(FlaskForm):
    default_login_page = StringField(lazy_gettext('기본 로그인 페이지'))
    settings_user_save = SubmitField(lazy_gettext('저장'))


class UserAdd(FlaskForm):
    user_name = StringField(
        TRANSLATIONS['user']['title'], validators=[DataRequired()])
    email = EmailField(
        TRANSLATIONS['email']['title'],
        validators=[
            DataRequired(),
            validators.Email()
        ]
    )
    password_new = PasswordField(
        TRANSLATIONS['password']['title'],
        validators=[
            DataRequired(),
            validators.EqualTo('password_repeat',
                               message=lazy_gettext('비밀번호가 일치해야 합니다.')),
            validators.Length(
                min=6,
                message=lazy_gettext('비밀번호는 6자 이상이어야 합니다.')
            )
        ]
    )
    password_repeat = PasswordField(
        lazy_gettext('비밀번호 확인'), validators=[DataRequired()])
    code = PasswordField("{} ({})".format(
        lazy_gettext('키패드 코드'),
        lazy_gettext('선택 사항')))
    addRole = StringField(
        lazy_gettext('역할'), validators=[DataRequired()])
    theme = StringField(
        lazy_gettext('테마'), validators=[DataRequired()])
    user_add = SubmitField(lazy_gettext('사용자 추가'))



class UserPreferences(FlaskForm):
    theme = StringField(lazy_gettext('테마'))
    language = StringField(lazy_gettext('언어'))
    user_preferences_save = SubmitField('저장')


class UserMod(FlaskForm):
    user_id = StringField('사용자 ID', widget=widgets.HiddenInput())
    email = EmailField(
        TRANSLATIONS['email']['title'],
        render_kw={"placeholder": TRANSLATIONS['email']['title']},
        validators=[
            DataRequired(),
            validators.Email()])
    password_new = PasswordField(
        TRANSLATIONS['password']['title'],
        render_kw={"placeholder": lazy_gettext("새 비밀번호")},
        validators=[
            validators.Optional(),
            validators.EqualTo(
                'password_repeat',
                message=lazy_gettext('비밀번호가 일치해야 합니다.')
            ),
            validators.Length(
                min=6,
                message=lazy_gettext('비밀번호는 6자 이상이어야 합니다.')
            )
        ]
    )
    password_repeat = PasswordField(
        lazy_gettext('비밀번호 확인'),
        render_kw={"placeholder": lazy_gettext("비밀번호 확인")})
    code = PasswordField(
        lazy_gettext('키패드 코드'),
        render_kw={"placeholder": lazy_gettext("키패드 코드")})
    api_key = StringField('API 키', render_kw={"placeholder": "API 키 (Base64)"})
    role_id = IntegerField(
        lazy_gettext('역할 ID'),
        validators=[DataRequired()],
        widget=NumberInput()
    )
    theme = StringField(lazy_gettext('테마'))
    user_generate_api_key = SubmitField("API 키 생성")
    user_save = SubmitField('저장')
    user_delete = SubmitField('삭제')


#
# Settings (Pi)
#

class SettingsPi(FlaskForm):
    pigpiod_state = StringField('pigpiod 상태', widget=widgets.HiddenInput())
    enable_i2c = SubmitField(lazy_gettext('I2C 활성화'))
    disable_i2c = SubmitField(lazy_gettext('I2C 비활성화'))
    enable_one_wire = SubmitField(lazy_gettext('1-Wire 활성화'))
    disable_one_wire = SubmitField(lazy_gettext('1-Wire 비활성화'))
    enable_serial = SubmitField(lazy_gettext('시리얼 통신 활성화'))
    disable_serial = SubmitField(lazy_gettext('시리얼 통신 비활성화'))
    enable_spi = SubmitField(lazy_gettext('SPI 활성화'))
    disable_spi = SubmitField(lazy_gettext('SPI 비활성화'))
    enable_ssh = SubmitField(lazy_gettext('SSH 활성화'))
    disable_ssh = SubmitField(lazy_gettext('SSH 비활성화'))
    hostname = StringField(lazy_gettext('호스트 이름'))
    change_hostname = SubmitField(lazy_gettext('호스트 이름 변경'))
    pigpiod_sample_rate = StringField(lazy_gettext('pigpiod 샘플링 속도 설정'))
    change_pigpiod_sample_rate = SubmitField(lazy_gettext('재설정'))


#
# 설정 (진단)
#

class SettingsDiagnostic(FlaskForm):
    delete_dashboard_elements = SubmitField(lazy_gettext('모든 대시보드 삭제'))
    delete_inputs = SubmitField(lazy_gettext('모든 입력 삭제'))
    delete_notes_tags = SubmitField(lazy_gettext('모든 메모 및 메모 태그 삭제'))
    delete_outputs = SubmitField(lazy_gettext('모든 출력 삭제'))
    delete_settings_database = SubmitField(lazy_gettext('설정 데이터베이스 삭제'))
    delete_file_dependency = SubmitField(lazy_gettext('파일 삭제') + ': .dependency')
    delete_file_upgrade = SubmitField(lazy_gettext('파일 삭제') + ': .upgrade')
    recreate_influxdb_db_1 = SubmitField('InfluxDB 1.x 데이터베이스 재생성')
    recreate_influxdb_db_2 = SubmitField('InfluxDB 2.x 데이터베이스 재생성')
    reset_email_counter = SubmitField(lazy_gettext('이메일 카운터 초기화'))
    install_dependencies = SubmitField(lazy_gettext('필수 패키지 설치'))
    regenerate_widget_html = SubmitField(lazy_gettext('위젯 HTML 재생성'))
    upgrade_master = SubmitField(lazy_gettext('마스터 업그레이드 설정'))
