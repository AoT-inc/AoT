# -*- coding: utf-8 -*-
#
# forms_misc.py - Miscellaneous Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import FileField
from wtforms import HiddenField
from wtforms import IntegerField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import validators
from wtforms import widgets
from wtforms.widgets import NumberInput

from aot.config_translations import TRANSLATIONS


#
# Energy Usage
#

class EnergyUsageAdd(FlaskForm):
    energy_usage_select = SelectField('측정값: Amp')
    energy_usage_add = SubmitField('추가')


class EnergyUsageMod(FlaskForm):
    energy_usage_id = StringField('전력량 ID', widget=widgets.HiddenInput())
    name = StringField('이름')
    selection_device_measure_ids = StringField('측정값: Amp')
    energy_usage_date_range = StringField('기간 (MM/DD/YYYY HH:MM)')
    energy_usage_range_calc = SubmitField('계산')
    energy_usage_mod = SubmitField('저장')
    energy_usage_delete = SubmitField('삭제')


#
# Daemon Control
#

class DaemonControl(FlaskForm):
    stop = SubmitField('데몬 중지')
    start = SubmitField('데몬 시작')
    restart = SubmitField('데몬 재시작')


#
# Export/Import Options
#

class ExportMeasurements(FlaskForm):
    measurement = StringField('내보낼 측정값')
    date_range = StringField('기간 (MM/DD/YYYY HH:MM)')
    export_data_csv = SubmitField('CSV로 데이터 내보내기')


class ExportSettings(FlaskForm):
    export_settings_zip = SubmitField('설정 내보내기')


class ImportSettings(FlaskForm):
    settings_import_file = FileField()
    settings_import_upload = SubmitField('설정 가져오기')


class ExportInfluxdb(FlaskForm):
    export_influxdb_zip = SubmitField('Influxdb 내보내기')


#
# Log viewer
#

class LogView(FlaskForm):
    lines = IntegerField(
        '표시할 로그 줄 수',
        render_kw={'placeholder': '줄 수'},
        validators=[validators.NumberRange(
            min=1,
            message='표시할 줄 수는 0보다 커야 합니다.'
        )],
        widget=NumberInput()
    )
    search = StringField(
        '검색',
        render_kw={'placeholder': '검색'},)
    log = StringField('로그')
    log_view = SubmitField('로그 보기')


#
# Upgrade
#

class Upgrade(FlaskForm):
    upgrade = SubmitField('AoT 업그레이드')
    upgrade_next_major_version = SubmitField('AoT 다음 주요 버전으로 업그레이드')


#
# Backup/Restore
#

class Backup(FlaskForm):
    download = SubmitField('백업 다운로드')
    backup = SubmitField('백업 생성')
    restore = SubmitField('백업 복원')
    delete = SubmitField('백업 삭제')
    full_path = HiddenField()
    selected_dir = HiddenField()
