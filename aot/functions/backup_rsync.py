# coding=utf-8
#
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#
import datetime
import os
import socket
import time

from flask_babel import lazy_gettext

from aot.config import (ALEMBIC_VERSION, AOT_VERSION, PATH_CAMERAS,
                           PATH_MEASUREMENTS_BACKUP, PATH_SETTINGS_BACKUP)
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.scripts.measurement_db import get_influxdb_info
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.system_pi import assure_path_exists, cmd_output
from aot.utils.tools import (create_measurements_export,
                                create_settings_export)

try:
    host_name = socket.gethostname().replace(' ', '_')
except:
    host_name = 'MY_HOST_NAME'

FUNCTION_INFORMATION = {
    'function_name_unique': 'BACKUP_REMOTE_RSYNC',
    'function_name': '원격 백업 (rsync)',

    'options_disabled': [
        'measurements_select',
        'measurements_configure'
    ],

    'message': '이 함수는 rsync를 사용하여 현재 시스템의 데이터를 원격 시스템에 백업합니다. 원격 시스템에는 SSH 서버가 실행 중이어야 하며, rsync가 설치되어 있어야 합니다. 또한, 이 시스템에도 rsync가 설치되어 있어야 하며, SSH 키 파일을 통해 비밀번호 없이 원격 시스템에 접근할 수 있어야 합니다.',

    'dependencies_module': [
        ('apt', 'rsync', 'rsync')
    ],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 1296000,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration between measurements or actions')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 300,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration to wait before the first operation')
        },
        {
            'id': 'local_user',
            'type': 'text',
            'default_value': 'pi',
            'required': True,
            'name': 'Local User',
            'phrase': 'The user on this system that will run rsync'
        },
        {
            'id': 'remote_user',
            'type': 'text',
            'default_value': 'pi',
            'required': True,
            'name': 'Remote User',
            'phrase': 'The user to log in to the remote host'
        },
        {
            'id': 'remote_host',
            'type': 'text',
            'default_value': '192.168.0.50',
            'required': True,
            'name': 'Remote Host',
            'phrase': 'The IP or host address to send the backup to'
        },
        {
            'id': 'remote_backup_path',
            'type': 'text',
            'default_value': '/home/pi/backup_aot',
            'required': True,
            'name': 'Remote Backup Path',
            'phrase': 'The path to backup to on the remote host'
        },
        {
            'id': 'rsync_timeout',
            'type': 'integer',
            'default_value': 3600,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Rsync Timeout (Seconds)',
            'phrase': 'How long to allow rsync to complete'
        },
        {
            'id': 'local_backup_path',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'Local Backup Path',
            'phrase': 'A local path to backup (leave blank to disable)'
        },
        {
            'id': 'do_backup_settings',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': 'Backup Settings Export File',
            'phrase': 'Create and backup exported settings file'
        },
        {
            'id': 'backup_remove_settings_archives',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': 'Remove Local Settings Backups',
            'phrase': 'Remove local settings backups after successful transfer to remote host'
        },
        {
            'id': 'do_backup_measurements',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': 'Backup Measurements',
            'phrase': 'Backup all influxdb measurements'
        },
        {
            'id': 'backup_remove_measurements_archives',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': 'Remove Local Measurements Backups',
            'phrase': 'Remove local measurements backups after successful transfer to remote host'
        },
        {
            'id': 'do_backup_cameras',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': 'Backup Camera Directories',
            'phrase': 'Backup all camera directories'
        },
        {
            'id': 'backup_remove_camera_images',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': 'Remove Local Camera Images',
            'phrase': 'Remove local camera images after successful transfer to remote host'
        },
        {
            'id': 'ssh_port',
            'type': 'integer',
            'default_value': 22,
            'required': False,
            'name': 'SSH Port',
            'phrase': 'Specify a nonstandard SSH port'
        }
    ],

    'custom_commands': [
        {
            'type': 'message',
            'default_value': 'Backup of settings are only created if the AoT version or database versions change. This is due to this Function running periodically- if it created a new backup every Period, there would soon be many identical backups. Therefore, if you want to induce the backup of settings, measurements, or camera directories and sync them to your remote system, use the buttons below.',
        },
        {
            'id': 'create_new_settings_backup',
            'type': 'button',
            'wait_for_return': False,
            'name': 'Backup Settings Now',
            'phrase': 'Backup settings via rsync'
        },
        {
            'id': 'create_new_measurements_backup',
            'type': 'button',
            'wait_for_return': False,
            'name': 'Backup Measurements Now',
            'phrase': 'Backup measurements via rsync'
        },
        {
            'id': 'create_new_camera_backup',
            'type': 'button',
            'wait_for_return': False,
            'name': 'Backup Camera Directories Now',
            'phrase': 'Backup camera directories via rsync'
        }
    ]
}


class CustomModule(AbstractFunction):
    """
    Class to operate custom controller
    """

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.is_setup = False
        self.timer_loop = time.time()
        self.control = DaemonControl()

        # Initialize custom options
        self.period = None
        self.start_offset = None
        self.local_user = None
        self.remote_user = None
        self.remote_host = None
        self.remote_backup_path = None
        self.rsync_timeout = None
        self.local_backup_path = None
        self.do_backup_settings = None
        self.backup_remove_settings_archives = None
        self.do_backup_measurements = None
        self.backup_remove_measurements_archives = None
        self.do_backup_cameras = None
        self.backup_remove_camera_images = None
        self.ssh_port = None

        # Set custom options
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.timer_loop = time.time() + self.start_offset

        self.logger.debug(
            "Custom controller started with options: {}, {}, {}, {}, {}".format(
                self.remote_host,
                self.remote_user,
                self.ssh_port,
                self.remote_backup_path,
                self.backup_settings))

        if self.remote_host and self.remote_user and self.remote_backup_path and self.ssh_port:
            self.is_setup = True

    def loop(self):
        if self.timer_loop > time.time():
            return

        while self.timer_loop < time.time():
            self.timer_loop += self.period

        if not self.is_setup:
            self.logger.error("Cannot run: Not all options are set")
            return

        if self.local_backup_path:
            self.local_backup()

        if self.do_backup_settings:
            self.backup_settings()

        if self.do_backup_measurements:
            self.backup_measurements()

        if self.do_backup_cameras:
            self.backup_camera()

    def local_backup(self):
        rsync_cmd = "rsync -avz -e 'ssh -p {port}' {path_local} {user}@{host}:{remote_path}".format(
            port=self.ssh_port,
            path_local=self.local_backup_path,
            user=self.remote_user,
            host=self.remote_host,
            remote_path=self.remote_backup_path)

        self.logger.debug("rsync command: {}".format(rsync_cmd))
        cmd_out, cmd_err, cmd_status = cmd_output(
            rsync_cmd, timeout=self.rsync_timeout, user=self.local_user)
        self.logger.debug("rsync returned:\nOut: {}\nError: {}\nStatus: {}".format(
            cmd_out.decode(), cmd_err.decode(), cmd_status))

    def backup_settings(self):
        filename = 'AoT_{mver}_Settings_{aver}_{host}_{dt}.zip'.format(
            mver=AOT_VERSION, aver=ALEMBIC_VERSION,
            host=socket.gethostname().replace(' ', ''),
            dt=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
        path_save = os.path.join(PATH_SETTINGS_BACKUP, filename)
        assure_path_exists(PATH_SETTINGS_BACKUP)
        if os.path.exists(path_save):
            self.logger.debug(
                "Skipping backup of settings: "
                "File already exists: {}".format(path_save))
        else:
            status, saved_path = create_settings_export(save_path=path_save)
            if not status:
                self.logger.debug("Saved settings file: "
                                  "{}".format(saved_path))
            else:
                self.logger.debug("Could not create settings file: "
                                  "{}".format(saved_path))

        if self.backup_remove_settings_archives:
            remove_files = "--remove-source-files "
        else:
            remove_files = ""
        rsync_cmd = "rsync {rem}-avz -e 'ssh -p {port}' {path_local} {user}@{host}:{remote_path}".format(
            rem=remove_files,
            port=self.ssh_port,
            path_local=PATH_SETTINGS_BACKUP,
            user=self.remote_user,
            host=self.remote_host,
            remote_path=self.remote_backup_path)
        self.logger.debug("rsync command: {}".format(rsync_cmd))
        cmd_out, cmd_err, cmd_status = cmd_output(
            rsync_cmd, timeout=self.rsync_timeout, user=self.local_user)
        self.logger.debug("rsync returned:\nOut: {}\nError: {}\nStatus: {}".format(
            cmd_out.decode(), cmd_err.decode(), cmd_status))

    def backup_measurements(self):
        influxd_version_out, _, _ = cmd_output(
            '/usr/bin/influxd version')
        if influxd_version_out:
            influxd_version = influxd_version_out.decode('utf-8').split(' ')[1]
        else:
            influxd_version = "UNKNOWN"
        filename = 'AoT_{mv}_Influxdb_{iv}_{host}_{dt}.zip'.format(
            mv=AOT_VERSION, iv=influxd_version,
            host=socket.gethostname().replace(' ', ''),
            dt=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
        path_save = os.path.join(PATH_MEASUREMENTS_BACKUP, filename)
        assure_path_exists(PATH_MEASUREMENTS_BACKUP)

        influxdb_info = get_influxdb_info()
        status, saved_path = create_measurements_export(
            influxdb_info['influxdb_version'], save_path=path_save)

        if not status:
            self.logger.debug("Saved measurements file: "
                              "{}".format(saved_path))
        else:
            self.logger.debug("Could not create measurements file: "
                              "{}".format(saved_path))

        if self.backup_remove_measurements_archives:
            remove_files = "--remove-source-files "
        else:
            remove_files = ""
        rsync_cmd = "rsync {rem}-avz -e 'ssh -p {port}' {path_local} {user}@{host}:{remote_path}".format(
            rem=remove_files,
            port=self.ssh_port,
            path_local=PATH_MEASUREMENTS_BACKUP,
            user=self.remote_user,
            host=self.remote_host,
            remote_path=self.remote_backup_path)
        self.logger.debug("rsync command: {}".format(rsync_cmd))
        cmd_out, cmd_err, cmd_status = cmd_output(
            rsync_cmd, timeout=self.rsync_timeout, user=self.local_user)
        self.logger.debug("rsync returned:\nOut: {}\nError: {}\nStatus: {}".format(
            cmd_out.decode(), cmd_err.decode(), cmd_status))

    def backup_camera(self):
        if self.backup_remove_camera_images:
            remove_files = "--remove-source-files "
        else:
            remove_files = ""
        rsync_cmd = "rsync {rem}-avz -e 'ssh -p {port}' {path_local} {user}@{host}:{remote_path}".format(
            rem=remove_files,
            port=self.ssh_port,
            path_local=PATH_CAMERAS,
            user=self.remote_user,
            host=self.remote_host,
            remote_path=self.remote_backup_path)

        self.logger.debug("rsync command: {}".format(rsync_cmd))
        cmd_out, cmd_err, cmd_status = cmd_output(
            rsync_cmd, timeout=self.rsync_timeout, user=self.local_user)
        self.logger.debug("rsync returned:\nOut: {}\nError: {}\nStatus: {}".format(
            cmd_out.decode(), cmd_err.decode(), cmd_status))

    def create_new_settings_backup(self, args_dict):
        self.backup_settings()

    def create_new_measurements_backup(self, args_dict):
        self.backup_measurements()

    def create_new_camera_backup(self, args_dict):
        self.backup_camera()
