# -*- coding: utf-8 -*-
import datetime
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import zipfile
import urllib.parse

from flask import send_file, url_for
from flask_babel import gettext
from packaging.version import parse
from werkzeug.utils import secure_filename

from aot.utils.service_control import reload_frontend, restart_daemon
from aot.utils.time_utils import utc_now, to_local
from aot.config import (ALEMBIC_VERSION, DATABASE_NAME, DOCKER_CONTAINER, IMPORT_LOG_FILE,
                              INSTALL_DIRECTORY, AOT_VERSION,
                              PATH_ACTIONS_CUSTOM, PATH_FUNCTIONS_CUSTOM,
                              PATH_TEMPLATE_USER, PATH_INPUTS_CUSTOM,
                              PATH_OUTPUTS_CUSTOM, PATH_PYTHON_CODE_USER,
                              PATH_USER_SCRIPTS, PATH_WIDGETS_CUSTOM,
                              SQL_DATABASE_AOT, DATABASE_PATH)
from aot.config_translations import TRANSLATIONS
from aot.aot_flask.utils.utils_general import (flash_form_errors,
                                                          flash_success_errors)
from aot.scripts.measurement_db import get_influxdb_info
from aot.utils.system_pi import assure_path_exists, cmd_output
from aot.utils.tools import (create_measurements_export,
                                   create_settings_export,
                                   UPLOAD_DIRECTORIES)
from aot.utils.utils import append_to_log
from aot.utils.widget_generate_html import generate_widget_html

logger = logging.getLogger(__name__)

#
# Export
#

def export_measurements(form):
    """
    Exports timestamps and measurements from InfluxDB to a CSV file according to the period entered by the user.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['export']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []

    if not form.validate():
        flash_form_errors(form)
        return url_for('routes_page.page_export')

    try:
        # Log input data (for debugging purposes)
        logger.info("date_range: %s, measurement: %s", form.date_range.data, form.measurement.data)

        # Parse date range
        start_time_str, end_time_str = form.date_range.data.split(' - ')
        start_seconds = int(time.mktime(time.strptime(start_time_str, '%m/%d/%Y %H:%M')))
        end_seconds = int(time.mktime(time.strptime(end_time_str, '%m/%d/%Y %H:%M')))

        # Parse measurement data
        measurement_parts = form.measurement.data.split(',')
        if len(measurement_parts) < 2:
            raise ValueError(gettext("Incorrect measurement data format. (e.g. id,measurement_id)"))
        unique_id, measurement_id = measurement_parts[0], measurement_parts[1]

        # Fix non-ASCII characters issue: apply URL encoding
        unique_id = urllib.parse.quote(unique_id, safe='')
        measurement_id = urllib.parse.quote(measurement_id, safe='')

        # Construct URL for CSV Export
        url = '/export_data/{id}/{meas}/{start}/{end}'.format(
            id=unique_id,
            meas=measurement_id,
            start=start_seconds,
            end=end_seconds
        )
        return url
    except Exception as err:
        logger.exception("Exception occurred in export_measurements()")
        error.append(gettext("Error: %(err)s") % {'err': err})
        flash_success_errors(error, action, url_for('routes_page.page_export'))
        return url_for('routes_page.page_export')

def export_settings():
    """
    Saves the AoT settings database (aot.db) as a ZIP file and provides it to the user.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['export']['title'],
        controller=TRANSLATIONS['settings']['title'])
    error = []

    try:
        status, data = create_settings_export()
        if not status:
            return send_file(
                data,
                mimetype='application/zip',
                as_attachment=True,
                download_name=
                    'AoT_{mver}_setup_{aver}_{host}_{dt}.zip'.format(
                        mver=AOT_VERSION, aver=ALEMBIC_VERSION,
                        host=socket.gethostname().replace(' ', ''),
                        dt=to_local(utc_now()).strftime("%Y-%m-%d_%H-%M-%S"))
            )
        else:
            error.append(data)
    except Exception as err:
        error.append(gettext("Error: %(err)s") % {'err': err})

    flash_success_errors(error, action, url_for('routes_page.page_export'))


def export_influxdb():
    """
    Backs up the AoT InfluxDB database in Enterprise compatible format, compresses it into a ZIP file, and provides it to the user.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['export']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []

    try:
        influxdb_info = get_influxdb_info()
        if influxdb_info['influxdb_host'] and influxdb_info['influxdb_version']:
            status, data = create_measurements_export(influxdb_info['influxdb_version'])
            if not status:
                return send_file(
                    data,
                    mimetype='application/zip',
                    as_attachment=True,
                    download_name=
                    'AoT_{mv}_Influxdb_{iv}_{host}_{dt}.zip'.format(
                        mv=AOT_VERSION, iv=influxdb_info['influxdb_version'],
                        host=socket.gethostname().replace(' ', ''),
                        dt=to_local(utc_now()).strftime("%Y-%m-%d_%H-%M-%S"))
                )
            else:
                error.append(data)
        else:
            error.append(gettext("Cannot verify InfluxDB host/version."))
    except Exception as err:
        error.append(gettext("Error: %(err)s") % {'err': err})

    flash_success_errors(error, action, url_for('routes_page.page_export'))


#
# Import
#

def thread_import_settings(tmp_folder):
    logger.info("Finishing import settings using thread_import_settings().")

    try:
        # Initialize
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper initialize | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # Upgrade database
        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Database Upgrade\n")
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper upgrade_database | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # Update dependencies (may take time)
        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Updating dependencies (please wait)...\n")
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper update_dependencies | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # Generate widget HTML
        generate_widget_html()

        # Re-initialize
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper initialize | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # Restart backend daemon
        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Restarting backend")
        restart_daemon(logger=logger)

        # Cleanup tmp directory
        if os.path.isdir(tmp_folder):
            shutil.rmtree(tmp_folder)

        # Reload frontend
        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Reloading frontend")
        # Small delay so this import thread finishes logging before the
        # web server goes down for the reload.
        reload_frontend(delay_sec=3, logger=logger)
    except:
        logger.exception("Exception occurred in thread_import_settings()")

    append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Import settings completed")
    logger.info("Import settings finished.")


def import_settings(form):
    """
    Receives a ZIP file containing the AoT settings database exported by export_settings(),
    backs up the current settings database, and replaces it with the one in the ZIP file.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['import']['title'],
        controller=TRANSLATIONS['settings']['title'])
    error = []

    try:
        logger.info("Starting settings import.")
        append_to_log(IMPORT_LOG_FILE, f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Settings import started")
        correct_format = 'AoT_AOTVERSION_Settings_DBVERSION_HOST_DATETIME.zip'
        upload_folder = os.path.join(INSTALL_DIRECTORY, 'upload')
        tmp_folder = os.path.join(upload_folder, 'aot_db_tmp')
        full_path = None

        if not form.settings_import_file.data:
            error.append(gettext("No file uploaded."))
        elif form.settings_import_file.data.filename == '':
            error.append(gettext("No filename provided."))
        else:
            # Parse uploaded filename
            file_name = form.settings_import_file.data.filename
            name = file_name.rsplit('.', 1)[0]
            extension = file_name.rsplit('.', 1)[1].lower()
            name_split = name.split('_')

            # Parse correct format
            correct_name = correct_format.rsplit('.', 1)[0]
            correct_name_1 = correct_name.split('_')[0]
            correct_name_2 = correct_name.split('_')[2]
            correct_extension = correct_format.rsplit('.', 1)[1].lower()

            # Validate filename parts
            try:
                if name_split[0] != correct_name_1:
                    error.append(gettext("Invalid filename: %(filename)s: %(part)s != %(correct)s.", filename=file_name, part=name_split[0], correct=correct_name_1))
                    error.append(gettext("Correct format is: %(format)s", format=correct_format))
                elif name_split[2] != correct_name_2:
                    error.append(gettext("Invalid filename: %(filename)s: %(part)s != %(correct)s", filename=file_name, part=name_split[2], correct=correct_name_2))
                    error.append(gettext("Correct format is: %(format)s", format=correct_format))
                elif extension != correct_extension:
                    error.append(gettext("Extension is not 'zip'."))
                elif parse(name_split[1]) > parse(AOT_VERSION):
                    error.append(gettext("Invalid AoT version: %(version)s > %(current)s. %(msg)s", version=name_split[1], current=AOT_VERSION, msg=gettext("Only databases from current or older versions can be imported.")))
            except Exception as err:
                error.append(gettext("Exception during filename validation: %(err)s", err=err))

        if not error:
            logger.info("Saving file to import")
            append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Saving file to import")
            # Save file to upload directory
            filename = secure_filename(form.settings_import_file.data.filename)
            full_path = os.path.join(tmp_folder, filename)
            assure_path_exists(upload_folder)
            assure_path_exists(tmp_folder)
            append_to_log(IMPORT_LOG_FILE, f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Saving {filename} to {tmp_folder}")
            form.settings_import_file.data.save(os.path.join(tmp_folder, filename))

            # Inspect zip content
            try:
                file_list = zipfile.ZipFile(full_path, 'r').namelist()
                if DATABASE_NAME not in file_list:
                    error.append(gettext("%(db)s file is not included in zip: %(list)s", db=DATABASE_NAME, list=', '.join(file_list)))
            except Exception as err:
                error.append(gettext("Exception during zip file inspection: %(err)s", err=err))

        if not error:
            logger.info("Extracting imported file")
            append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Extracting imported file")
            # Extract zip
            try:
                assure_path_exists(tmp_folder)
                zip_ref = zipfile.ZipFile(full_path, 'r')
                append_to_log(IMPORT_LOG_FILE, f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Extracting {full_path} to {tmp_folder}")
                zip_ref.extractall(tmp_folder)
                zip_ref.close()
            except Exception as err:
                error.append(gettext("Exception during zip file extraction: %(err)s", err=err))

        if not error:
            logger.info("Stopping daemon and copying files")
            append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Stopping daemon and copying files")
            try:
                if DOCKER_CONTAINER:
                    subprocess.Popen('docker stop aot_daemon 2>&1', shell=True)
                else:
                    # Stop backend daemon
                    cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper daemon_stop"
                    _, _, _ = cmd_output(cmd, user="root")

                # Rename current database and replace with imported one
                imported_database = os.path.join(tmp_folder, DATABASE_NAME)
                backup_name = f"{SQL_DATABASE_AOT}.backup_{to_local(utc_now()).strftime('%Y-%m-%d_%H-%M-%S')}"
                full_path_backup = os.path.join(DATABASE_PATH, backup_name)

                append_to_log(IMPORT_LOG_FILE,
                              f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Renaming {SQL_DATABASE_AOT} to {full_path_backup}")
                os.rename(SQL_DATABASE_AOT, full_path_backup)  # Current database backup
                append_to_log(IMPORT_LOG_FILE,
                              f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Moving {imported_database} to {SQL_DATABASE_AOT}")
                shutil.move(imported_database, SQL_DATABASE_AOT)  # Replace with imported database

                delete_directories = [
                    PATH_FUNCTIONS_CUSTOM,
                    PATH_ACTIONS_CUSTOM,
                    PATH_INPUTS_CUSTOM,
                    PATH_OUTPUTS_CUSTOM,
                    PATH_WIDGETS_CUSTOM,
                    PATH_USER_SCRIPTS,
                    PATH_TEMPLATE_USER,
                    PATH_PYTHON_CODE_USER
                ]

                # Delete custom items and generated code
                for each_dir in delete_directories:
                    append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Deleting directory: {each_dir}")
                    if not os.path.exists(each_dir):
                        continue
                    for folder_name, sub_folders, filenames in os.walk(each_dir):
                        for filename in filenames:
                            if filename == "__init__.py":
                                continue
                            file_path = os.path.join(folder_name, filename)
                            try:
                                os.remove(file_path)
                            except:
                                pass

                restore_directories = [
                    (PATH_FUNCTIONS_CUSTOM, "custom_functions"),
                    (PATH_ACTIONS_CUSTOM, "custom_actions"),
                    (PATH_INPUTS_CUSTOM, "custom_inputs"),
                    (PATH_OUTPUTS_CUSTOM, "custom_outputs"),
                    (PATH_WIDGETS_CUSTOM, "custom_widgets"),
                    (PATH_USER_SCRIPTS, "user_scripts"),
                    (PATH_TEMPLATE_USER, "user_html"),
                    (PATH_PYTHON_CODE_USER, "user_python_code")
                ]

                # Restore custom items from zip
                for each_dir in restore_directories:
                    append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Restoring {each_dir[1]} directory: {each_dir[0]}")
                    extract_dir = os.path.join(tmp_folder, each_dir[1])
                    if not os.path.exists(extract_dir):
                        continue
                    for folder_name, sub_folders, filenames in os.walk(extract_dir):
                        for filename in filenames:
                            file_path = os.path.join(folder_name, filename)
                            new_path = os.path.join(each_dir[0], filename)
                            append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Restoring {new_path}")
                            try:
                                shutil.move(file_path, new_path)
                            except:
                                append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Error: Failed to restore {filename}")
                                logger.exception("Exception during file move")

                # User-uploaded files (notes/notice attachments, facility &
                # zone photos, and facility 3D model assets). Unlike the
                # custom-code directories above, these can't be regenerated,
                # so — unlike delete_directories — each is only touched if
                # the imported zip actually contains that folder. An older
                # export (made before uploads were included) has none of
                # these folders, and importing it must not wipe out uploads
                # already on this server.
                for target_dir, zip_subfolder in UPLOAD_DIRECTORIES:
                    extract_dir = os.path.join(tmp_folder, zip_subfolder)
                    if not os.path.isdir(extract_dir):
                        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Zip has no {zip_subfolder} folder, leaving existing {target_dir} untouched")
                        continue

                    append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Deleting directory: {target_dir}")
                    if os.path.exists(target_dir):
                        for folder_name, sub_folders, filenames in os.walk(target_dir):
                            for filename in filenames:
                                file_path = os.path.join(folder_name, filename)
                                try:
                                    os.remove(file_path)
                                except:
                                    pass

                    append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Restoring {zip_subfolder} directory: {target_dir}")
                    for folder_name, sub_folders, filenames in os.walk(extract_dir):
                        for filename in filenames:
                            file_path = os.path.join(folder_name, filename)
                            rel_path = os.path.relpath(file_path, extract_dir)
                            new_path = os.path.join(target_dir, rel_path)
                            os.makedirs(os.path.dirname(new_path), exist_ok=True)
                            append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Restoring {new_path}")
                            try:
                                shutil.move(file_path, new_path)
                            except:
                                append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Error: Failed to restore {filename}")
                                logger.exception("Exception during file move")

                logger.info("Finishing import")
                import_settings_db = threading.Thread(
                    target=thread_import_settings,
                    args=(tmp_folder,))
                import_settings_db.start()

                return True
            except Exception as err:
                logger.exception("Exception during settings import")
                error.append(gettext("Exception during database replacement: %(err)s", err=err))
                return

    except Exception as err:
        error.append(gettext("Exception occurred: %(err)s", err=err))

    if error:
        append_to_log(IMPORT_LOG_FILE, f"\n\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Failed to complete settings import. Errors:")
    for each_err in error:
        append_to_log(IMPORT_LOG_FILE, f"\n[{to_local(utc_now()).strftime('%Y-%m-%d %H:%M:%S %Z')}] Error: {each_err}")

    flash_success_errors(error, action, url_for('routes_page.page_export'))