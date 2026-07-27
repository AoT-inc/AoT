# -*- coding: utf-8 -*-
#
# forms_settings.py - Settings Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import BooleanField
from wtforms import DecimalField
from wtforms import FileField
from wtforms import FloatField
from wtforms import IntegerField
from wtforms import PasswordField
from wtforms import SelectMultipleField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import TextAreaField
from wtforms import validators
from wtforms import widgets
from wtforms.fields import EmailField
from wtforms.validators import DataRequired
from wtforms.validators import Optional
from wtforms.widgets import NumberInput
from wtforms.widgets import TextArea

from aot.config_translations import TRANSLATIONS
import json
import os

# Load Theme Defaults from JSON (Single Source of Truth)
THEME_DEFAULTS = {}
try:
    # Use absolute path for reliability
    _theme_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'static', 'json', 'theme_defaults.json')
    if os.path.exists(_theme_json_path):
        with open(_theme_json_path, 'r') as f:
            THEME_DEFAULTS = json.load(f)
except Exception as e:
    print(f"Error loading theme_defaults.json: {e}")

# settings/custom_ui 색상 필드 단일 목록 (Single Source of Truth)
# 폼 정의(SettingsCustomUI)·저장(utils_settings.settings_custom_ui_mod)·
# 프리셋 API(routes_settings.settings_custom_ui_presets)가 공유한다.
#
# 2026-07 필드 통합 (color-system.md §3-2): 이름은 다르지만 실제로는 같은
# 요소(주/보조 버튼 배경)를 가리키던 필드들을 통합했다. bg_btn_on/off 는
# 장치 ON/OFF 상태 표시라 값이 다른 게 자연스러워 통합하지 않고 남겼다.
THEME_COLOR_FIELDS = [
    'brand_primary', 'brand_secondary', 'brand_accent',
    'text_color_primary', 'text_color_secondary', 'text_color_tertiary',
    'bd_primary', 'bd_secondary',
    'bg_active', 'bg_inactive',
    'bg_llm', 'bg_mcp', 'badge_upgrade',
    'btn_primary_bg', 'btn_secondary_bg',
    'bg_btn_on', 'bg_btn_off',
    'bg_btn_pause', 'bg_btn_hold', 'bd_btn_border',
    # 측정 밴드 5색 (--aot-band-1..5) — 게이지/센서 라벨 등
    'band_1', 'band_2', 'band_3', 'band_4', 'band_5',
    # 차트 시리즈 앞 6색 (GRAPH_SERIES_PALETTE 라이트/다크 공통 구간)
    'chart_1', 'chart_2', 'chart_3', 'chart_4', 'chart_5', 'chart_6'
]

# 구 필드명 -> 신규 통합 필드명 (우선순위 순, 먼저 존재하는 값을 채택).
# 구 필드는 전부 새 필드로 흡수되거나(bd_btn_tertiary -> brand_accent 는 값이
# 이미 같아 흡수만 하고 대응 신규 필드 없음) 폐기된다.
LEGACY_THEME_FIELD_MAP = {
    'btn_primary_bg': ['bd_btn_primary', 'bd_tertiary', 'bg_btn_active'],
    'btn_secondary_bg': ['bd_btn_secondary', 'bg_btn_inactive'],
    'badge_upgrade': ['bg_upgrade', 'bg_btn_upgrade'],
}
LEGACY_THEME_FIELDS_DROP = {
    'bd_tertiary', 'bd_btn_primary', 'bg_btn_active',
    'bd_btn_secondary', 'bg_btn_inactive',
    'bd_btn_tertiary', 'bg_upgrade', 'bg_btn_upgrade',
}


def migrate_theme_dict(theme_dict):
    """구 필드명(bd_tertiary 등, 2026-07 통합 이전)을 신규 필드로 이관하고
    구 키를 제거한다. 저장된 custom_theme_json·프리셋을 읽는 모든 지점
    (routes_settings GET, routes_general.custom_css, settings_custom_ui_mod)
    에서 사용에 앞서 호출할 것 — 매번 계산되는 순수 함수라 DB 기록 없이도
    호출 시점마다 최신 필드셋으로 보여줄 수 있다."""
    if not isinstance(theme_dict, dict):
        return theme_dict
    for new_field, old_fields in LEGACY_THEME_FIELD_MAP.items():
        if new_field not in theme_dict:
            for old in old_fields:
                if old in theme_dict:
                    theme_dict[new_field] = theme_dict[old]
                    break
    for old in LEGACY_THEME_FIELDS_DROP:
        theme_dict.pop(old, None)
    return theme_dict


#
# Settings (Email)
#

class SettingsEmail(FlaskForm):
    smtp_host = StringField(
        lazy_gettext('SMTP Host'),
        render_kw={"placeholder": lazy_gettext('SMTP Host')},
        validators=[DataRequired()]
    )
    smtp_port = IntegerField(
        lazy_gettext('SMTP Port'),
        validators=[Optional()]
    )
    smtp_protocol = StringField(
        lazy_gettext('SMTP Protocol'),
        validators=[DataRequired()]
    )
    smtp_ssl = BooleanField(lazy_gettext('Enable SSL'))
    smtp_user = StringField(
        lazy_gettext('SMTP User'),
        render_kw={"placeholder": lazy_gettext('SMTP User')},
        validators=[DataRequired()]
    )
    smtp_password = PasswordField(
        lazy_gettext('SMTP Password'),
        render_kw={"placeholder": TRANSLATIONS['password']['title']}
    )
    smtp_from_email = EmailField(
        lazy_gettext('From Email'),
        render_kw={"placeholder": TRANSLATIONS['email']['title']},
        validators=[
            DataRequired(),
            validators.Email()
        ]
    )
    smtp_hourly_max = IntegerField(
        lazy_gettext('Max Emails per Hour'),
        render_kw={"placeholder": lazy_gettext('Max Emails per Hour')},
        validators=[validators.NumberRange(
            min=1,
            message=lazy_gettext('Must be able to send at least one email.')
        )],
        widget=NumberInput()
    )
    send_test = SubmitField(lazy_gettext('Send Test Email'))
    send_test_to_email = EmailField(
        lazy_gettext('Test Email Recipient'),
        render_kw={"placeholder": lazy_gettext('Recipient Email Address')},
        validators=[
            validators.Email(),
            validators.Optional()
        ]
    )
    save = SubmitField(lazy_gettext('Save'))



#
# Settings (General)
#

class SettingsGeneral(FlaskForm):
    landing_page = StringField(lazy_gettext('Landing Page'))
    index_page = StringField(lazy_gettext('Index Page'))
    language = StringField(lazy_gettext('Language'))
    rpyc_timeout = StringField(lazy_gettext('Pyro Timeout'))
    daemon_debug_mode = BooleanField(lazy_gettext('Enable Daemon Debug Logging'))
    force_https = BooleanField(lazy_gettext('Force HTTPS'))
    hide_success = BooleanField(lazy_gettext('Hide Success Messages'))
    hide_info = BooleanField(lazy_gettext('Hide Info Messages'))
    hide_warning = BooleanField(lazy_gettext('Hide Warning Messages'))
    hide_tooltips = BooleanField(lazy_gettext('Hide Tooltips'))

    use_database = StringField(lazy_gettext('Database'))
    measurement_db_retention_policy = StringField(lazy_gettext('Data Retention Policy'))
    measurement_db_host = StringField(lazy_gettext('Database Hostname'))
    measurement_db_port = IntegerField(lazy_gettext('Port'))
    measurement_db_dbname = StringField(lazy_gettext('Database Name'))
    measurement_db_user = StringField(lazy_gettext('Database Username'))
    measurement_db_password = PasswordField(lazy_gettext('Database Password'))

    grid_cell_height = IntegerField(
        lazy_gettext('Grid Cell Height (px)'), widget=NumberInput())
    max_amps = DecimalField(
        lazy_gettext('Max Current (A)'), widget=NumberInput(step='any'))
    output_stats_volts = IntegerField(
        lazy_gettext('Voltage'), widget=NumberInput())
    output_stats_cost = DecimalField(
        lazy_gettext('Cost per kWh'), widget=NumberInput(step='any'))
    output_stats_currency = StringField(lazy_gettext('Currency Unit'))
    output_stats_day_month = StringField(lazy_gettext('Base Day of Month'))
    output_usage_report_gen = BooleanField(lazy_gettext('Generate Usage/Cost Report'))
    output_usage_report_span = StringField(lazy_gettext('Report Generation Period'))
    output_usage_report_day = IntegerField(
        lazy_gettext('Report Generation Day of Week/Month'), widget=NumberInput())
    output_usage_report_hour = IntegerField(
        lazy_gettext('Report Generation Hour'),
        validators=[validators.NumberRange(
            min=0,
            max=23,
            message=lazy_gettext("Hour range: 0-23")
        )],
        widget=NumberInput()
    )
    stats_opt_out = BooleanField(lazy_gettext('Opt out of Statistics Collection'))
    enable_upgrade_check = BooleanField(lazy_gettext('Enable Update Check'))
    net_test_ip = StringField(lazy_gettext('Internet Test IP Address'))
    net_test_port = IntegerField(
        lazy_gettext('Internet Test Port'), widget=NumberInput())
    net_test_timeout = IntegerField(
        lazy_gettext('Internet Test Timeout'), widget=NumberInput())

    ai_enabled = BooleanField(lazy_gettext('Enable AI Service'))

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

    settings_general_save = SubmitField(lazy_gettext('Save'))


class SettingsMap(FlaskForm):
    map_name = StringField(
        lazy_gettext('Map Name'),
        validators=[Optional()]
    )
    map_use_satellite = BooleanField(
        lazy_gettext('Use Satellite Map'),
        default=False
    )
    map_api_key = StringField(
        lazy_gettext('Map API Key'),
        validators=[Optional()]
    )
    map_latitude = FloatField(
        lazy_gettext('Default Latitude'),
        validators=[Optional()]
    )
    map_longitude = FloatField(
        lazy_gettext('Default Longitude'),
        validators=[Optional()]
    )
    map_location_label = StringField(
        lazy_gettext('Location Label/Address'),
        validators=[Optional()]
    )
    map_locked = BooleanField(
        lazy_gettext('Lock Map'),
        default=False
    )
    save = SubmitField(lazy_gettext('Save'))


#
# Settings (Controller)
#

class Controller(FlaskForm):
    import_controller_file = FileField()
    import_controller_upload = SubmitField(lazy_gettext('Import Controller Module'))


class ControllerDel(FlaskForm):
    controller_id = StringField(widget=widgets.HiddenInput())
    delete_controller = SubmitField(lazy_gettext('Delete'))


#
# Settings (Action)
#

class Action(FlaskForm):
    import_action_file = FileField()
    import_action_upload = SubmitField(lazy_gettext('Import Action Module'))


class ActionDel(FlaskForm):
    action_id = StringField(widget=widgets.HiddenInput())
    delete_action = SubmitField(lazy_gettext('Delete'))


#
# Settings (Input)
#

class Input(FlaskForm):
    import_input_file = FileField()
    import_input_upload = SubmitField(lazy_gettext('Import Input Module'))


class InputDel(FlaskForm):
    input_id = StringField(widget=widgets.HiddenInput())
    delete_input = SubmitField(lazy_gettext('Delete'))


#
# Settings (Output)
#

class Output(FlaskForm):
    import_output_file = FileField()
    import_output_upload = SubmitField(lazy_gettext('Import Output Module'))


class OutputDel(FlaskForm):
    output_id = StringField(widget=widgets.HiddenInput())
    delete_output = SubmitField(lazy_gettext('Delete'))


#
# Settings (Widget)
#

class Widget(FlaskForm):
    import_widget_file = FileField()
    import_widget_upload = SubmitField(lazy_gettext('Import Widget Module'))


class WidgetDel(FlaskForm):
    widget_id = StringField(widget=widgets.HiddenInput())
    delete_widget = SubmitField(lazy_gettext('Delete'))


#
# Settings (Measurement)
#

class MeasurementAdd(FlaskForm):
    id = StringField(
        lazy_gettext('Measurement ID'), validators=[DataRequired()])
    name = StringField(
        lazy_gettext('Measurement Name'), validators=[DataRequired()])
    units = SelectMultipleField(lazy_gettext('Measurement Units'))
    add_measurement = SubmitField(lazy_gettext('Add Measurement'))


class MeasurementMod(FlaskForm):
    measurement_id = StringField(lazy_gettext('Measurement ID'), widget=widgets.HiddenInput())
    id = StringField(lazy_gettext('Measurement ID'))
    name = StringField(lazy_gettext('Measurement Name'))
    units = SelectMultipleField(lazy_gettext('Measurement Units'))
    save_measurement = SubmitField(lazy_gettext('Save'))
    delete_measurement = SubmitField(lazy_gettext('Delete'))


class UnitAdd(FlaskForm):
    id = StringField(lazy_gettext('Unit ID'), validators=[DataRequired()])
    name = StringField(
        lazy_gettext('Unit Name'), validators=[DataRequired()])
    unit = StringField(
        lazy_gettext('Unit Symbol'), validators=[DataRequired()])
    add_unit = SubmitField(lazy_gettext('Add Unit'))


class UnitMod(FlaskForm):
    unit_id = StringField(lazy_gettext('Unit ID'), widget=widgets.HiddenInput())
    id = StringField(lazy_gettext('Unit ID'))
    name = StringField(lazy_gettext('Unit Name'))
    unit = StringField(lazy_gettext('Unit Symbol'))
    save_unit = SubmitField(lazy_gettext('Save'))
    delete_unit = SubmitField(lazy_gettext('Delete'))


class ConversionAdd(FlaskForm):
    convert_unit_from = StringField(
        lazy_gettext('Convert Unit From'), validators=[DataRequired()])
    convert_unit_to = StringField(
        lazy_gettext('Convert Unit To'), validators=[DataRequired()])
    equation = StringField(
        lazy_gettext('Equation'), validators=[DataRequired()])
    add_conversion = SubmitField(lazy_gettext('Add Equation'))


class ConversionMod(FlaskForm):
    conversion_id = StringField(lazy_gettext('Equation ID'), widget=widgets.HiddenInput())
    convert_unit_from = StringField(lazy_gettext('Convert Unit From'))
    convert_unit_to = StringField(lazy_gettext('Convert Unit To'))
    equation = StringField(lazy_gettext('Equation'))
    save_conversion = SubmitField(lazy_gettext('Save'))
    delete_conversion = SubmitField(lazy_gettext('Delete'))


#
# Settings (User)
#

class UserRoles(FlaskForm):
    name = StringField(
        lazy_gettext('Role Name'), validators=[DataRequired()])
    view_logs = BooleanField(lazy_gettext('View Logs'))
    view_stats = BooleanField(lazy_gettext('View Statistics'))
    view_camera = BooleanField(lazy_gettext('View Camera'))
    view_settings = BooleanField(lazy_gettext('View Settings'))
    edit_users = BooleanField(lazy_gettext('Edit Users'))
    edit_controllers = BooleanField(lazy_gettext('Edit Controllers'))
    edit_settings = BooleanField(lazy_gettext('Edit Settings'))
    reset_password = BooleanField(lazy_gettext('Reset Password'))
    role_id = StringField(lazy_gettext('Role ID'), widget=widgets.HiddenInput())
    user_role_add = SubmitField(lazy_gettext('Add Role'))
    user_role_save = SubmitField(lazy_gettext('Save'))
    user_role_delete = SubmitField(lazy_gettext('Delete'))


class User(FlaskForm):
    default_login_page = StringField(lazy_gettext('Default Login Page'))
    settings_user_save = SubmitField(lazy_gettext('Save'))


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
                               message=lazy_gettext('Passwords must match.')),
            validators.Length(
                min=6,
                message=lazy_gettext('Password must be at least 6 characters.')
            )
        ]
    )
    password_repeat = PasswordField(
        lazy_gettext('Confirm Password'), validators=[DataRequired()])
    code = PasswordField("{} ({})".format(
        lazy_gettext('Keypad Code'),
        lazy_gettext('Optional')))
    addRole = StringField(
        lazy_gettext('Role'), validators=[DataRequired()])
    theme = StringField(
        lazy_gettext('Theme'), validators=[DataRequired()])
    user_add = SubmitField(lazy_gettext('Add User'))



class UserPreferences(FlaskForm):
    theme = StringField(lazy_gettext('Theme'))
    language = StringField(lazy_gettext('Language'))
    timezone = StringField(lazy_gettext('Timezone'))  # IANA tz for personal display; empty = system default
    user_preferences_save = SubmitField(lazy_gettext('Save'))


class AccountSelf(FlaskForm):
    """Self-service account editing (nav-bar 'User Settings' modal) — a
    logged-in user editing their own name/email/password/language. Unlike
    UserMod (admin editing any user), no role/permission fields — those stay
    admin-only in Settings > Users."""
    name = StringField(TRANSLATIONS['user']['title'], validators=[DataRequired()])
    email = EmailField(
        TRANSLATIONS['email']['title'],
        validators=[DataRequired(), validators.Email()])
    password_new = PasswordField(
        lazy_gettext('New Password'),
        validators=[
            validators.Optional(),
            validators.EqualTo('password_repeat', message=lazy_gettext('Passwords must match.'))
        ])
    password_repeat = PasswordField(lazy_gettext('Confirm Password'))
    language = StringField(lazy_gettext('Language'))
    timezone = StringField(lazy_gettext('Timezone'))  # IANA tz for personal display; empty = system default
    user_account_save = SubmitField(lazy_gettext('Save'))


class UserMod(FlaskForm):
    user_id = StringField(lazy_gettext('User ID'), widget=widgets.HiddenInput())
    email = EmailField(
        TRANSLATIONS['email']['title'],
        render_kw={"placeholder": TRANSLATIONS['email']['title']},
        validators=[
            DataRequired(),
            validators.Email()])
    password_new = PasswordField(
        TRANSLATIONS['password']['title'],
        render_kw={"placeholder": lazy_gettext("New Password")},
        validators=[
            validators.Optional(),
            validators.EqualTo(
                'password_repeat',
                message=lazy_gettext('Passwords must match.')
            ),
            validators.Length(
                min=6,
                message=lazy_gettext('Password must be at least 6 characters.')
            )
        ]
    )
    password_repeat = PasswordField(
        lazy_gettext('Confirm Password'),
        render_kw={"placeholder": lazy_gettext("Confirm Password")})
    code = PasswordField(
        lazy_gettext('Keypad Code'),
        render_kw={"placeholder": lazy_gettext("Keypad Code")})
    api_key = StringField(lazy_gettext('API Key'), render_kw={"placeholder": lazy_gettext("API Key (Base64)")})
    role_id = IntegerField(
        lazy_gettext('Role ID'),
        validators=[DataRequired()],
        widget=NumberInput()
    )
    theme = StringField(lazy_gettext('Theme'))
    user_generate_api_key = SubmitField(lazy_gettext("Generate API Key"))
    user_save = SubmitField(lazy_gettext('Save'))
    user_approve = SubmitField(lazy_gettext('Approve'))
    user_delete = SubmitField(lazy_gettext('Delete'))


class APIKeyAdd(FlaskForm):
    name = StringField(lazy_gettext('Name'), validators=[DataRequired()], render_kw={"placeholder": lazy_gettext("Key Alias (e.g. OpenWeather)")})
    provider = StringField(lazy_gettext('Provider/Manufacturer'), render_kw={"placeholder": lazy_gettext("Manufacturer or Service Name")})
    key = StringField(lazy_gettext('API Key'), validators=[DataRequired()], render_kw={"placeholder": lazy_gettext("API Key Body")})
    url = StringField(lazy_gettext('Related URL'), render_kw={"placeholder": lazy_gettext("Supplier Website Address")})
    tag = StringField(lazy_gettext('Tag'), render_kw={"placeholder": lazy_gettext("Classification tags (comma separated)")})
    description = TextAreaField(lazy_gettext('Description'), render_kw={"placeholder": lazy_gettext("Detailed information about the key")})
    api_key_add_submit = SubmitField(lazy_gettext("Add"))


class APIKeyMod(APIKeyAdd):
    api_key_id = StringField(lazy_gettext('API Key ID'), validators=[DataRequired()])
    api_key_mod_submit = SubmitField(lazy_gettext("Modify"))
    api_key_delete = SubmitField(lazy_gettext("Delete"))
    user_delete = SubmitField(lazy_gettext('Delete'))


#
# Settings (Pi)
#

class SettingsPi(FlaskForm):
    pigpiod_state = StringField(lazy_gettext('pigpiod Status'), widget=widgets.HiddenInput())
    enable_i2c = SubmitField(lazy_gettext('Enable I2C'))
    disable_i2c = SubmitField(lazy_gettext('Disable I2C'))
    enable_one_wire = SubmitField(lazy_gettext('Enable 1-Wire'))
    disable_one_wire = SubmitField(lazy_gettext('Disable 1-Wire'))
    enable_serial = SubmitField(lazy_gettext('Enable Serial Communication'))
    disable_serial = SubmitField(lazy_gettext('Disable Serial Communication'))
    enable_spi = SubmitField(lazy_gettext('Enable SPI'))
    disable_spi = SubmitField(lazy_gettext('Disable SPI'))
    enable_ssh = SubmitField(lazy_gettext('Enable SSH'))
    disable_ssh = SubmitField(lazy_gettext('Disable SSH'))
    hostname = StringField(lazy_gettext('Hostname'))
    change_hostname = SubmitField(lazy_gettext('Change Hostname'))
    pigpiod_sample_rate = StringField(lazy_gettext('pigpiod Sample Rate Settings'))
    change_pigpiod_sample_rate = SubmitField(lazy_gettext('Reset'))


#
# Settings (Diagnostic)
#

class SettingsDiagnostic(FlaskForm):
    delete_dashboard_elements = SubmitField(lazy_gettext('Delete All Dashboard Elements'))
    delete_inputs = SubmitField(lazy_gettext('Delete All Inputs'))
    delete_notes_tags = SubmitField(lazy_gettext('Delete All Notes and Note Tags'))
    delete_outputs = SubmitField(lazy_gettext('Delete All Outputs'))
    delete_functions = SubmitField(lazy_gettext('Delete All Functions'))
    delete_settings_database = SubmitField(lazy_gettext('Delete Settings Database'))
    delete_file_dependency = SubmitField(lazy_gettext('Delete File') + ': .dependency')
    delete_file_upgrade = SubmitField(lazy_gettext('Delete File') + ': .upgrade')
    recreate_influxdb_db_1 = SubmitField(lazy_gettext('Recreate InfluxDB 1.x Database'))
    recreate_influxdb_db_2 = SubmitField(lazy_gettext('Recreate InfluxDB 2.x Database'))
    reset_email_counter = SubmitField(lazy_gettext('Reset Email Counter'))
    install_dependencies = SubmitField(lazy_gettext('Install Required Packages'))
    regenerate_widget_html = SubmitField(lazy_gettext('Regenerate Widget HTML'))
    upgrade_master = SubmitField(lazy_gettext('Master Upgrade Settings'))

#
# Settings (Custom UI)
#

class SettingsCustomUI(FlaskForm):
    brand_display = StringField(lazy_gettext('Brand Display'))
    title_display = StringField(lazy_gettext('Title Display'))
    hostname_override = StringField(lazy_gettext('Brand Text'))
    brand_image = FileField(lazy_gettext('Brand Image'))
    brand_image_height = IntegerField(lazy_gettext('Brand Image Height'))
    favicon_display = StringField(lazy_gettext('Favicon Display'))
    brand_favicon = FileField(lazy_gettext('Favicon Image'))
    custom_css = StringField(lazy_gettext('Custom CSS'), widget=TextArea())
    custom_layout = StringField(lazy_gettext('Custom Layout'), widget=TextArea())

    brand_primary = StringField(lazy_gettext('Brand Primary'), default=THEME_DEFAULTS.get('brand_primary', '#13261B'), render_kw={"type": "color"})
    brand_secondary = StringField(lazy_gettext('Brand Secondary'), default=THEME_DEFAULTS.get('brand_secondary', '#5E6B64'), render_kw={"type": "color"})
    brand_accent = StringField(lazy_gettext('Brand Accent'), default=THEME_DEFAULTS.get('brand_accent', '#F3F6F5'), render_kw={"type": "color"})
    text_color_primary = StringField(lazy_gettext('Text Color Primary'), default=THEME_DEFAULTS.get('text_color_primary', '#13261B'), render_kw={"type": "color"})
    text_color_secondary = StringField(lazy_gettext('Text Color Secondary'), default=THEME_DEFAULTS.get('text_color_secondary', '#5E6B64'), render_kw={"type": "color"})
    text_color_tertiary = StringField(lazy_gettext('Text Color Tertiary'), default=THEME_DEFAULTS.get('text_color_tertiary', '#FFFFFF'), render_kw={"type": "color"})
    bd_primary = StringField(lazy_gettext('BG Primary'), default=THEME_DEFAULTS.get('bd_primary', '#FFFFFF'), render_kw={"type": "color"})
    bd_secondary = StringField(lazy_gettext('BG Secondary'), default=THEME_DEFAULTS.get('bd_secondary', '#F3F6F5'), render_kw={"type": "color"})
    bg_active = StringField(lazy_gettext('BG Active'), default=THEME_DEFAULTS.get('bg_active', '#D1D5D5'), render_kw={"type": "color"})
    bg_inactive = StringField(lazy_gettext('BG Inactive'), default=THEME_DEFAULTS.get('bg_inactive', '#F3F6F5'), render_kw={"type": "color"})
    bg_llm = StringField(lazy_gettext('BG LLM Badge'), default=THEME_DEFAULTS.get('bg_llm', '#6277C7'), render_kw={"type": "color"})
    bg_mcp = StringField(lazy_gettext('BG MCP Badge'), default=THEME_DEFAULTS.get('bg_mcp', '#64C762'), render_kw={"type": "color"})
    # 2026-07 통합: bg_upgrade(nav 배지) + bg_btn_upgrade(버튼) — 둘 다 같은
    # '업그레이드 알림' 개념이라 하나로. color-system.md §3-2 참조.
    badge_upgrade = StringField(lazy_gettext('Upgrade Badge'), default=THEME_DEFAULTS.get('badge_upgrade', '#13261B'), render_kw={"type": "color"})
    # 2026-07 통합: bd_tertiary + bd_btn_primary + bg_btn_active — 전부
    # '채워진 주 버튼 배경'을 가리키던 별개 필드였다(color-system.md §3-2).
    btn_primary_bg = StringField(lazy_gettext('Primary Button Background'), default=THEME_DEFAULTS.get('btn_primary_bg', '#13261B'), render_kw={"type": "color"})
    # 2026-07 통합: bd_btn_secondary + bg_btn_inactive.
    btn_secondary_bg = StringField(lazy_gettext('Secondary Button Background'), default=THEME_DEFAULTS.get('btn_secondary_bg', '#5E6B64'), render_kw={"type": "color"})
    # ON/OFF 는 장치 상태 표시라 주/보조 버튼과 값이 달라지는 게 자연스러워
    # 통합하지 않고 별도 필드로 남겼다.
    bg_btn_on = StringField(lazy_gettext('Btn BG On'), default=THEME_DEFAULTS.get('bg_btn_on', '#13261B'), render_kw={"type": "color"})
    bg_btn_off = StringField(lazy_gettext('Btn BG Off'), default=THEME_DEFAULTS.get('bg_btn_off', '#5E6B64'), render_kw={"type": "color"})
    bg_btn_pause = StringField(lazy_gettext('Btn BG Pause'), default=THEME_DEFAULTS.get('bg_btn_pause', '#989E9E'), render_kw={"type": "color"})
    bg_btn_hold = StringField(lazy_gettext('Btn BG Hold'), default=THEME_DEFAULTS.get('bg_btn_hold', '#D1D5D5'), render_kw={"type": "color"})
    bd_btn_border = StringField(lazy_gettext('Btn Border Base'), default=THEME_DEFAULTS.get('bd_btn_border', '#B6BABA'), render_kw={"type": "color"})
    # 측정 밴드 5색 (--aot-band-1..5, 차가움→적정→뜨거움)
    band_1 = StringField(lazy_gettext('Band 1 (Very Low)'), default=THEME_DEFAULTS.get('band_1', '#2DB4FF'), render_kw={"type": "color"})
    band_2 = StringField(lazy_gettext('Band 2 (Low)'), default=THEME_DEFAULTS.get('band_2', '#54BCC1'), render_kw={"type": "color"})
    band_3 = StringField(lazy_gettext('Band 3 (Optimal)'), default=THEME_DEFAULTS.get('band_3', '#32c85a'), render_kw={"type": "color"})
    band_4 = StringField(lazy_gettext('Band 4 (High)'), default=THEME_DEFAULTS.get('band_4', '#FEAE5F'), render_kw={"type": "color"})
    band_5 = StringField(lazy_gettext('Band 5 (Very High)'), default=THEME_DEFAULTS.get('band_5', '#CF5C58'), render_kw={"type": "color"})
    # 차트 시리즈 앞 6색 (GRAPH_SERIES_PALETTE 공통 구간)
    chart_1 = StringField(lazy_gettext('Chart Series 1'), default=THEME_DEFAULTS.get('chart_1', '#FEA60B'), render_kw={"type": "color"})
    chart_2 = StringField(lazy_gettext('Chart Series 2'), default=THEME_DEFAULTS.get('chart_2', '#8BC1C1'), render_kw={"type": "color"})
    chart_3 = StringField(lazy_gettext('Chart Series 3'), default=THEME_DEFAULTS.get('chart_3', '#93B261'), render_kw={"type": "color"})
    chart_4 = StringField(lazy_gettext('Chart Series 4'), default=THEME_DEFAULTS.get('chart_4', '#F4D624'), render_kw={"type": "color"})
    chart_5 = StringField(lazy_gettext('Chart Series 5'), default=THEME_DEFAULTS.get('chart_5', '#DF5353'), render_kw={"type": "color"})
    chart_6 = StringField(lazy_gettext('Chart Series 6'), default=THEME_DEFAULTS.get('chart_6', '#008DDE'), render_kw={"type": "color"})

    settings_custom_ui_save = SubmitField(lazy_gettext('Save'))


class SettingsChirpStack(FlaskForm):
    """ChirpStack LNS connection + device registration actions."""
    chirpstack_grpc_server = StringField(lazy_gettext('ChirpStack gRPC Server'))
    # API token is selected from the system API Keys store (Settings > API Keys),
    # not pasted here. choices are populated in the route from APIKey records.
    chirpstack_api_token = SelectField(lazy_gettext('API Token'), choices=[], validators=[Optional()])
    chirpstack_mqtt_host = StringField(lazy_gettext('MQTT Broker Host'))
    chirpstack_mqtt_port = IntegerField(lazy_gettext('MQTT Broker Port'))
    save_conn = SubmitField(lazy_gettext('Save Connection'))
    refresh = SubmitField(lazy_gettext('Refresh Devices'))
    # Hidden fields populated by the per-device register buttons
    action = StringField()      # 'add_input' | 'add_output' | 'assign_scheduler'
    dev_eui = StringField()
    dev_name = StringField()
    scheduler_id = StringField()  # target scheduler unique_id ('' = unassign)
