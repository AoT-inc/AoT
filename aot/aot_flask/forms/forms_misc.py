# -*- coding: utf-8 -*-
#
# forms_misc.py - Miscellaneous Flask Forms
#

from flask_babel import lazy_gettext
from flask_wtf import FlaskForm
from wtforms import FileField
from wtforms import HiddenField
from wtforms import SelectField
from wtforms import StringField
from wtforms import SubmitField
from wtforms import widgets

from aot.config_translations import TRANSLATIONS


#
# Energy Usage
#

class EnergyUsageAdd(FlaskForm):
    energy_usage_select = SelectField(lazy_gettext('Measurement: Amp'))
    energy_usage_add = SubmitField(lazy_gettext('Add'))


class EnergyUsageMod(FlaskForm):
    energy_usage_id = StringField(lazy_gettext('Energy Usage ID'), widget=widgets.HiddenInput())
    name = StringField(lazy_gettext('Name'))
    selection_device_measure_ids = StringField(lazy_gettext('Measurement: Amp'))
    energy_usage_date_range = StringField(lazy_gettext('Period (MM/DD/YYYY HH:MM)'))
    energy_usage_range_calc = SubmitField(lazy_gettext('Calculate'))
    energy_usage_mod = SubmitField(lazy_gettext('Save'))
    energy_usage_delete = SubmitField(lazy_gettext('Delete'))


#
# Daemon Control
#

class DaemonControl(FlaskForm):
    stop = SubmitField(lazy_gettext('Stop Daemon'))
    start = SubmitField(lazy_gettext('Start Daemon'))
    restart = SubmitField(lazy_gettext('Restart Daemon'))


#
# Export/Import Options
#

class ExportMeasurements(FlaskForm):
    measurement = StringField(lazy_gettext('Measurement to Export'))
    date_range = StringField(lazy_gettext('Period (MM/DD/YYYY HH:MM)'))
    export_data_csv = SubmitField(lazy_gettext('Export Data to CSV'))


class ExportSettings(FlaskForm):
    export_settings_zip = SubmitField(lazy_gettext('Export Settings'))


class ImportSettings(FlaskForm):
    settings_import_file = FileField()
    settings_import_upload = SubmitField(lazy_gettext('Import Settings'))


class ExportInfluxdb(FlaskForm):
    export_influxdb_zip = SubmitField(lazy_gettext('Export InfluxDB'))


#
# Log viewer
#
# LogView 폼은 제거됐다. /logview 는 POST 폼 제출이 아니라 GET 쿼리 + JSON
# 폴링(/logview/data)으로 동작하며, 필터 상태는 URL 에 실린다(공유·새로고침).
#

#
# Upgrade
#

class Upgrade(FlaskForm):
    upgrade = SubmitField(lazy_gettext('Upgrade AoT'))
    upgrade_next_major_version = SubmitField(lazy_gettext('Upgrade AoT to Next Major Version'))


#
# Backup/Restore
#

class Backup(FlaskForm):
    download = SubmitField(lazy_gettext('Download Backup'))
    backup = SubmitField(lazy_gettext('Create Backup'))
    restore = SubmitField(lazy_gettext('Restore Backup'))
    delete = SubmitField(lazy_gettext('Delete Backup'))
    full_path = HiddenField()
    selected_dir = HiddenField()
