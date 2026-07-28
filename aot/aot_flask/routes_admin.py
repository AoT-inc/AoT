# coding=utf-8
"""collection of Admin endpoints."""
import datetime
import io
import logging
import os
import re
import shlex
import socket
import subprocess
import threading
import zipfile
from collections import OrderedDict

import flask_login
from flask import (Blueprint, flash, jsonify, make_response, redirect,
                   render_template, request, send_file, url_for)
from flask_babel import gettext
# packaging.version.parse — pkg_resources 는 setuptools 81 에서 제거되었고,
# 그 때문에 requirements.txt 가 setuptools<81 에 묶여 알려진 취약점을 고칠 수
# 없었다. 이 파일이 유일한 사용처였고 쓰임은 버전 비교뿐이라 그대로 대체된다
# (AoT 버전 형식 7종으로 두 구현의 비교 결과가 동일함을 확인).
from packaging.version import parse as parse_version

from aot.utils.time_utils import utc_now, to_local
from aot.config import (BACKUP_LOG_FILE, BACKUP_PATH, CAMERA_INFO,
                           DEPENDENCIES_GENERAL, DEPENDENCY_INIT_FILE,
                           DEPENDENCY_LOG_FILE, DOCKER_CONTAINER,
                           FINAL_RELEASES,
                           FORCE_UPGRADE_MASTER, FUNCTION_INFO,
                           INSTALL_DIRECTORY, METHOD_INFO, AOT_VERSION,
                           RESTORE_LOG_FILE, STATS_CSV, UPGRADE_INIT_FILE,
                           UPGRADE_LOG_FILE, UPGRADE_TMP_LOG_FILE)
from aot.databases.models import Misc
from aot.aot_flask.extensions import db
from aot.aot_flask.forms import forms_dependencies, forms_misc
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_general
from aot.utils.actions import parse_action_information
from aot.utils.docker_backup import (docker_backup_create,
                                        docker_backup_delete,
                                        docker_backup_restore,
                                        docker_can_perform_backup)
from aot.utils.functions import parse_function_information
from aot.utils.github_release_info import AoTRelease
from aot.utils.service_control import reload_frontend, restart_daemon
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information
from aot.utils.stats import return_stat_file_dict
from aot.utils.system_pi import (can_perform_backup, cmd_output,
                                    get_directory_size, internet)
from aot.utils.widgets import parse_widget_information

logger = logging.getLogger('aot.aot_flask.admin')

blueprint = Blueprint(
    'routes_admin',
    __name__,
    static_folder='../static',
    template_folder='../templates'
)


@blueprint.context_processor
@flask_login.login_required
def inject_dictionary():
    return inject_variables()


@blueprint.route('/admin/backup', methods=('GET', 'POST'))
@flask_login.login_required
def admin_backup():
    """Load the backup management page"""
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    form_backup = forms_misc.Backup()

    backup_dirs_tmp = []
    if DOCKER_CONTAINER:
        # Docker backups are written straight to BACKUP_PATH (see
        # docker_backup.py) — no /var/AoT-backups bare-metal convention here.
        os.makedirs(BACKUP_PATH, exist_ok=True)
        backup_dirs_tmp = sorted(next(os.walk(BACKUP_PATH))[1])
        backup_dirs_tmp.reverse()
    elif not os.path.isdir('/var/AoT-backups'):
        flash(gettext("Error: Backup directory doesn't exist."), "error")
    else:
        backup_dirs_tmp = sorted(next(os.walk(BACKUP_PATH))[1])
        backup_dirs_tmp.reverse()

    backup_dirs = []
    full_paths = []
    for each_dir in backup_dirs_tmp:
        if each_dir.startswith("AoT-backup-"):
            full_path = os.path.join(BACKUP_PATH, each_dir)
            backup_dirs.append((each_dir, get_directory_size(full_path) / 1000000.0))
            full_paths.append(full_path)

    if request.method == 'POST':
        if form_backup.backup.data:
            if DOCKER_CONTAINER:
                # docker_can_perform_backup() mirrors can_perform_backup() but
                # sized against what docker_backup_create() actually copies
                # (DB + uploads, not the whole install directory) and checked
                # against BACKUP_PATH's own filesystem.
                backup_size, free_before, free_after = docker_can_perform_backup()
                if free_after / 1000000 > 50:
                    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                    with open(BACKUP_LOG_FILE, 'a+') as f:
                        f.write(f"\n{now} Backup initiated (Docker)\n")

                    def _run_backup():
                        status, result = docker_backup_create()
                        now2 = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                        with open(BACKUP_LOG_FILE, 'a+') as log_f:
                            if status:
                                log_f.write(f"\n{now2} Backup failed: {result}\n")
                            else:
                                log_f.write(f"\n{now2} Backup completed: {result}\n")

                    threading.Thread(target=_run_backup).start()
                    flash(gettext("Backup in progress"), "success")
                else:
                    flash(
                        gettext(
                            "Not enough free space to perform a backup. A backup "
                            "requires %(size_bu).1f MB but there is only "
                            "%(size_free).1f MB available, which would leave "
                            "%(size_after).1f MB after the backup. If the free space "
                            "after a backup is less than 50 MB, the backup cannot "
                            "proceed. Free up space by deleting current "
                            "backups.",
                            size_bu=backup_size / 1000000,
                            size_free=free_before / 1000000,
                            size_after=free_after / 1000000),
                        'error')
            else:
                backup_size, free_before, free_after = can_perform_backup()
                if free_after / 1000000 > 50:
                    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                    cmd = "{pth}/aot/scripts/aot_wrapper backup-create" \
                          " >> {log} 2>&1".format(pth=INSTALL_DIRECTORY,
                                                  log=BACKUP_LOG_FILE)
                    with open(BACKUP_LOG_FILE, 'a+') as f:
                        f.write(f"\n{now} Backup initiated\n")
                    subprocess.Popen(cmd, shell=True)
                    flash(gettext("Backup in progress"), "success")
                else:
                    flash(
                        gettext(
                            "Not enough free space to perform a backup. A backup "
                            "requires %(size_bu).1f MB but there is only "
                            "%(size_free).1f MB available, which would leave "
                            "%(size_after).1f MB after the backup. If the free space "
                            "after a backup is less than 50 MB, the backup cannot "
                            "proceed. Free up space by deleting current "
                            "backups.",
                            size_bu=backup_size / 1000000,
                            size_free=free_before / 1000000,
                            size_after=free_after / 1000000),
                        'error')

        elif form_backup.download.data:
            def get_all_file_paths(directory):
                file_paths = []
                for root, directories, files in os.walk(directory):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        file_paths.append(filepath)
                return file_paths

            try:
                backup_date_version = form_backup.selected_dir.data
                # Validate: only allow safe date-version strings (e.g. "2024-01-15_12-30-00-v26.05.0")
                if not re.match(r'^[\w.\-]+$', backup_date_version or ''):
                    flash(gettext("Invalid backup directory name."), "error")
                else:
                    download_dir = os.path.join(BACKUP_PATH, 'AoT-backup-{}'.format(backup_date_version))
                    # Resolve symlinks and verify the path stays within BACKUP_PATH
                    real_backup_path = os.path.realpath(BACKUP_PATH)
                    real_download_dir = os.path.realpath(download_dir)
                    if not real_download_dir.startswith(real_backup_path + os.sep):
                        flash(gettext("Invalid backup path."), "error")
                    elif not os.path.isdir(download_dir):
                        flash(gettext("Directory not found: %(dir)s", dir=download_dir), "error")
                    else:
                        save_file = "AoT_Backup_{dv}_{host}_.zip".format(
                            dv=backup_date_version, host=socket.gethostname().replace(' ', ''))
                        file_paths = get_all_file_paths(download_dir)
                        string_remove = "{}".format(os.path.join(BACKUP_PATH, download_dir))

                        # Zip all files in the backup directory
                        data = io.BytesIO()
                        with zipfile.ZipFile(data, 'w') as zipf:
                            for file in file_paths:
                                zipf.write(file, file.replace(string_remove, ""))
                        data.seek(0)

                        return send_file(
                            data,
                            mimetype='application/zip',
                            as_attachment=True,
                            download_name=save_file
                        )
            except Exception as err:
                flash(gettext("Error: %(err)s", err=err), "error")

        elif form_backup.delete.data:
            backup_date_version = form_backup.selected_dir.data
            if not re.match(r'^[\w.\-]+$', backup_date_version or ''):
                flash(gettext("Invalid backup directory name."), "error")
            elif DOCKER_CONTAINER:
                dest_dir = os.path.join(BACKUP_PATH, "AoT-backup-{}".format(backup_date_version))
                real_backup_path = os.path.realpath(BACKUP_PATH)
                real_dest_dir = os.path.realpath(dest_dir)
                if not real_dest_dir.startswith(real_backup_path + os.sep):
                    flash(gettext("Invalid backup path."), "error")
                else:
                    status, result = docker_backup_delete(dest_dir)
                    if status:
                        flash(gettext("Error: %(err)s", err=result), "error")
                    else:
                        flash(gettext("Backup deleted"), "success")
            else:
                cmd = ["{pth}/aot/scripts/aot_wrapper".format(pth=INSTALL_DIRECTORY),
                       "backup-delete",
                       "AoT-backup-{}".format(backup_date_version)]
                with open(os.devnull, 'w') as devnull:
                    subprocess.Popen(cmd, stderr=devnull)
                flash(gettext("Deletion of backup in progress"), "success")

        elif form_backup.restore.data:
            full_path = form_backup.full_path.data
            # Resolve symlinks and ensure path is within BACKUP_PATH
            real_backup_path = os.path.realpath(BACKUP_PATH)
            real_full_path = os.path.realpath(full_path) if full_path else ''
            if not real_full_path.startswith(real_backup_path + os.sep):
                flash(gettext("Invalid restore path."), "error")
            elif not os.path.isdir(full_path):
                flash(gettext("Directory not found: %(dir)s", dir=full_path), "error")
            elif DOCKER_CONTAINER:
                now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                with open(RESTORE_LOG_FILE, 'a+') as f:
                    f.write(f"\n{now} Restore initiated from {full_path} (Docker)\n")

                def _run_restore(src_dir=full_path):
                    status, result = docker_backup_restore(src_dir)
                    now2 = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                    with open(RESTORE_LOG_FILE, 'a+') as log_f:
                        if status:
                            log_f.write(f"\n{now2} Restore failed: {result}\n")
                        else:
                            log_f.write(f"\n{now2} Restore completed: {result}\n")

                threading.Thread(target=_run_restore).start()
                flash(gettext("Restore in progress"), "success")
            else:
                now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                cmd = ["{pth}/aot/scripts/aot_wrapper".format(pth=INSTALL_DIRECTORY),
                       "backup-restore",
                       full_path]
                with open(RESTORE_LOG_FILE, 'a+') as f:
                    f.write(f"\n{now} Restore initiated from {full_path}\n")
                subprocess.Popen(cmd, stdout=open(RESTORE_LOG_FILE, 'a'), stderr=subprocess.STDOUT)
                flash(gettext("Restore in progress"), "success")

    return render_template('admin/backup.html',
                           form_backup=form_backup,
                           backup_dirs=backup_dirs,
                           full_paths=full_paths)


def install_dependencies(dependencies):
    now = to_local(utc_now()).strftime("%Y-%m-%d %H:%M:%S %Z")
    dependency_list = []
    for each_dependency in dependencies:
        if each_dependency[0] not in dependency_list:
            dependency_list.append(each_dependency[0])
    
    # Check if running in Docker container
    IS_DOCKER = os.environ.get('DOCKER_CONTAINER', '').lower() in ('true', '1', 'yes')
    
    with open(DEPENDENCY_LOG_FILE, 'a+') as f:
        if IS_DOCKER:
            f.write("\n[{time}] Docker environment detected - using pip install only\n\n".format(time=now))
        else:
            f.write("\n[{time}] Dependency installation beginning. Installing: {deps}\n\n".format(
                time=now, deps=", ".join(dependency_list)))

    failures = []

    for each_dep in dependencies:
        if each_dep[2] == 'bash-commands':
            # In Docker, skip bash-commands (Raspberry Pi specific scripts)
            if IS_DOCKER:
                with open(DEPENDENCY_LOG_FILE, 'a+') as f:
                    f.write(f"\n[{now}] SKIPPING bash-commands in Docker: {each_dep[0]}\n")
                continue
            for each_command in each_dep[1]:
                try:
                    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
                    command = "{cmd} >> {log} 2>&1".format(
                        cmd=each_command,
                        log=DEPENDENCY_LOG_FILE)
                    
                    with open(DEPENDENCY_LOG_FILE, 'a+') as f:
                        f.write(f"\n{now} Executing command: {each_command}\n")

                    cmd_out, cmd_err, cmd_status = cmd_output(
                        command, user='root', timeout=600, cwd="/tmp")

                    with open(DEPENDENCY_LOG_FILE, 'a+') as f:
                        now = to_local(utc_now()).strftime("%Y-%m-%d %H:%M:%S %Z")
                        f.write(f"\n[{now}] Command returned: out: {cmd_out}, error: {cmd_err}, status: {cmd_status}\n")

                    if cmd_status != 0:
                        failures.append(each_command)
                except:
                    logger.exception("Executing command")
        else:
            now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
            cmd = "{pth}/aot/scripts/aot_wrapper install_dependency {dep}" \
                  " >> {log} 2>&1".format(
                    pth=INSTALL_DIRECTORY,
                    log=DEPENDENCY_LOG_FILE,
                    dep=each_dep[1])
            with open(DEPENDENCY_LOG_FILE, 'a+') as f:
                f.write(f"\n{now} Installing: {each_dep[1]}\n")
            dep = subprocess.Popen(cmd, shell=True)
            dep.wait()
            if dep.returncode:
                failures.append(each_dep[1])
            now = to_local(utc_now()).strftime("%Y-%m-%d %H:%M:%S %Z")
            with open(DEPENDENCY_LOG_FILE, 'a+') as f:
                f.write("\n[{time}] End install of {dep}\n\n".format(
                    time=now, dep=each_dep[0]))

    if failures:
        now = to_local(utc_now()).strftime("%Y-%m-%d %H:%M:%S %Z")
        with open(DEPENDENCY_LOG_FILE, 'a+') as f:
            f.write("\n[{time}] #### Dependency install encountered errors. Failed items: {fails}\n\n".format(
                time=now, fails=", ".join(failures)))
        with open(DEPENDENCY_INIT_FILE, 'w') as f:
            f.write('0')
        return

    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
    
    if IS_DOCKER:
        # In Docker, skip Pi-specific commands (chown, systemctl, etc.)
        with open(DEPENDENCY_LOG_FILE, 'a+') as f:
            f.write(f"\n{now} SKIPPING update_permissions in Docker (not needed)\n")
    else:
        cmd = "{pth}/aot/scripts/aot_wrapper update_permissions" \
              " >> {log}  2>&1".format(
                pth=INSTALL_DIRECTORY,
                log=DEPENDENCY_LOG_FILE)
        with open(DEPENDENCY_LOG_FILE, 'a+') as f:
            f.write(f"\n{now} Updating permissions\n")
        init = subprocess.Popen(cmd, shell=True)
        init.wait()

    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
    with open(DEPENDENCY_LOG_FILE, 'a+') as f:
        f.write(f"\n{now} #### Dependencies installed. Restarting services...\n")

    with open(DEPENDENCY_INIT_FILE, 'w') as f:
        f.write('0')

    for action_func, label in [(restart_daemon, "Restarting daemon"),
                               (reload_frontend, "Reloading frontend")]:
        now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
        with open(DEPENDENCY_LOG_FILE, 'a+') as f:
            f.write(f"\n{now} {label}\n")
        # Frontend reload is deferred so the dependency-install thread can
        # finish writing its log before the web server goes down.
        action_func(delay_sec=3, logger=logger)

    now = to_local(utc_now()).strftime("[%Y-%m-%d %H:%M:%S %Z]")
    with open(DEPENDENCY_LOG_FILE, 'a+') as f:
        f.write(f"\n{now} #### Dependency install complete.\n\n")


@blueprint.route('/admin/dependency_install/<device>', methods=('GET', 'POST'))
@flask_login.login_required
def admin_dependency_install(device):
    """Install Dependencies."""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }

    try:
        device_unmet_dependencies, _, _ = utils_general.return_dependencies(device)
        with open(DEPENDENCY_INIT_FILE, 'w') as f:
            f.write('1')
        install_deps = threading.Thread(
            target=install_dependencies,
            args=(device_unmet_dependencies,))
        install_deps.start()
        messages["success"].append("Dependency install initiated")
    except Exception as err:
        messages["error"].append("Error: {}".format(err))

    return jsonify(data={
        'messages': messages
    })


@blueprint.route('/admin/dependencies', methods=('GET', 'POST'))
@flask_login.login_required
def admin_dependencies_main():
    return redirect(url_for('routes_admin.admin_dependencies', device='0'))


@blueprint.route('/admin/dependencies/<device>', methods=('GET', 'POST'))
@flask_login.login_required
def admin_dependencies(device):
    """Display Dependency page"""
    form_dependencies = forms_dependencies.Dependencies()

    if device != '0':
        # Only loading a single dependency page
        device_unmet_dependencies, _, _ = utils_general.return_dependencies(device)
    elif form_dependencies.device.data:
        device_unmet_dependencies, _, _ = utils_general.return_dependencies(form_dependencies.device.data)
    else:
        device_unmet_dependencies = []

    unmet_dependencies = OrderedDict()
    unmet_exist = False
    met_dependencies = []
    met_exist = False
    unmet_list = {}
    install_in_progress = False
    device_name = None
    dependencies_message = ""

    # Read from the dependency status file created by the upgrade script
    # to indicate if the upgrade is running.
    try:
        with open(DEPENDENCY_INIT_FILE) as f:
            dep = int(f.read(1))
    except (IOError, ValueError):
        try:
            with open(DEPENDENCY_INIT_FILE, 'w') as f:
                f.write('0')
        finally:
            dep = 0

    if dep:
        install_in_progress = True

    list_dependencies = [
        parse_function_information(),
        parse_action_information(),
        parse_input_information(),
        parse_output_information(),
        parse_widget_information(),
        CAMERA_INFO,
        FUNCTION_INFO,
        METHOD_INFO,
        DEPENDENCIES_GENERAL
    ]
    for each_section in list_dependencies:
        for each_device in each_section:

            if device in each_section:
                # Determine if a message for the dependencies exists
                if "dependencies_message" in each_section[device]:
                    dependencies_message = each_section[device]["dependencies_message"]

                # Find friendly name for device
                for each_device_, each_val in each_section[device].items():
                    if each_device_ in ['name',
                                        'input_name',
                                        'output_name',
                                        'function_name',
                                        'widget_name']:
                        device_name = each_val
                        break

            # Only get all dependencies when not loading a single dependency page
            if device == '0':
                # Determine if there are any unmet dependencies for every device
                dep_unmet, dep_met, _ = utils_general.return_dependencies(each_device)

                unmet_dependencies.update({
                    each_device: dep_unmet
                })
                if dep_unmet:
                    unmet_exist = True

                # Determine if there are any met dependencies
                if dep_met:
                    if each_device not in met_dependencies:
                        met_dependencies.append(each_device)
                        met_exist = True

                # Find all the devices that use each unmet dependency
                if unmet_dependencies[each_device]:
                    for each_dep in unmet_dependencies[each_device]:
                        # Determine if the second element of a 4-element tuple is a list, convert it to a tuple
                        if (type(each_dep) == tuple and
                                len(each_dep) == 4 and
                                type(each_dep[1]) == list):
                            each_dep = list(each_dep)
                            each_dep[1] = tuple(each_dep[1])
                            each_dep = tuple(each_dep)

                        # Determine if the third element of a 3-element tuple is a list, convert it to a tuple
                        if (type(each_dep) == tuple and
                                len(each_dep) == 3 and
                                type(each_dep[2]) == list):
                            each_dep = list(each_dep)
                            each_dep[2] = tuple(each_dep[2])
                            each_dep = tuple(each_dep)

                        if each_dep not in unmet_list:
                            unmet_list[each_dep] = []
                        if each_device not in unmet_list[each_dep]:
                            unmet_list[each_dep].append(each_device)

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_controllers'):
            return redirect(url_for('routes_admin.admin_dependencies', device=device))

        if form_dependencies.install.data:
            with open(DEPENDENCY_INIT_FILE, 'w') as f:
                f.write('1')
            install_deps = threading.Thread(
                target=install_dependencies,
                args=(device_unmet_dependencies,))
            install_deps.start()

        return redirect(url_for('routes_admin.admin_dependencies', device=device))

    return render_template('admin/dependencies.html',
                           measurements=parse_input_information(),
                           unmet_list=unmet_list,
                           dependencies_message=dependencies_message,
                           device=device,
                           device_name=device_name,
                           install_in_progress=install_in_progress,
                           unmet_dependencies=unmet_dependencies,
                           unmet_exist=unmet_exist,
                           met_dependencies=met_dependencies,
                           met_exist=met_exist,
                           form_dependencies=form_dependencies,
                           device_unmet_dependencies=device_unmet_dependencies)


@blueprint.route('/admin/dependency_status', methods=('GET', 'POST'))
@flask_login.login_required
def admin_dependency_status():
    """Return the last 30 lines of the dependency log."""
    if os.path.isfile(DEPENDENCY_LOG_FILE):
        command = 'tail -n 40 {log}'.format(log=DEPENDENCY_LOG_FILE)
        log = subprocess.Popen(
            command, stdout=subprocess.PIPE, shell=True)
        (log_output, _) = log.communicate()
        log.wait()
        log_output = log_output.decode("utf-8")
    else:
        log_output = 'Dependency log not found. If a dependency install was ' \
                     'just initialized, please wait...'
    response = make_response(log_output)
    response.headers["content-type"] = "text/plain"
    return response


@blueprint.route('/admin/statistics', methods=('GET', 'POST'))
@flask_login.login_required
def admin_statistics():
    """Display collected statistics."""
    if not utils_general.user_has_permission('view_stats'):
        return redirect(url_for('routes_general.home'))

    try:
        statistics = return_stat_file_dict(STATS_CSV)
    except IOError:
        statistics = {}
    return render_template('admin/statistics.html',
                           statistics=statistics)


@blueprint.route('/admin/upgrade_status', methods=('GET', 'POST'))
@flask_login.login_required
def admin_upgrade_status():
    """Return the last 30 lines of the upgrade log."""
    if os.path.isfile(UPGRADE_TMP_LOG_FILE):
        command = 'cat {log}'.format(log=UPGRADE_TMP_LOG_FILE)
        log = subprocess.Popen(
            command, stdout=subprocess.PIPE, shell=True)
        (log_output, _) = log.communicate()
        log.wait()
        log_output = log_output.decode("utf-8")
    else:
        log_output = 'Upgrade log not found. If an upgrade was just ' \
                     'initialized, please wait...'
    response = make_response(log_output)
    response.headers["content-type"] = "text/plain"
    return response


@blueprint.route('/admin/upgrade', methods=('GET', 'POST'))
@flask_login.login_required
def admin_upgrade():
    """Display any available upgrades and option to upgrade"""
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    # The in-app upgrade replaces the on-disk install (move /opt/AoT, stop
    # systemd services, etc.). In Docker the code is a bind mount, there is no
    # /var/aot-root or /opt/AoT, and there is no systemd — the upgrade scripts
    # cannot run and would fail partway. Block it and point to the host workflow.
    if DOCKER_CONTAINER:
        if request.method == 'POST':
            flash(gettext(
                "In-app upgrade is not available in Docker. On the host, update "
                "the code (git pull) and rebuild/restart the containers "
                "(docker compose up -d --build) instead."), "error")
            return redirect(url_for('routes_admin.admin_upgrade'))
        return render_template('admin/upgrade.html',
                               current_release=AOT_VERSION,
                               is_internet=True,
                               is_docker=True)

    misc = Misc.query.first()
    if not internet(host=misc.net_test_ip,
                    port=misc.net_test_port,
                    timeout=misc.net_test_timeout):
        return render_template('admin/upgrade.html',
                               is_internet=False)

    is_internet = True

    # Read from the upgrade status file created by the upgrade script
    # to indicate if the upgrade is running.
    try:
        with open(UPGRADE_INIT_FILE) as f:
            upgrade = int(f.read(1))
    except Exception:
        try:
            with open(UPGRADE_INIT_FILE, 'w') as f:
                f.write('0')
        finally:
            upgrade = 0

    if upgrade:
        if upgrade == 2:
            flash(gettext("There was an error encountered during the upgrade"
                          " process. Check the upgrade log for details."),
                  "error")
        return render_template('admin/upgrade.html',
                               current_release=AOT_VERSION,
                               is_internet=is_internet,
                               upgrade=upgrade)

    form_backup = forms_misc.Backup()
    form_upgrade = forms_misc.Upgrade()

    upgrade_available = False

    # Check for any new AoT releases on github
    aot_releases_check = AoTRelease()
    (upgrade_exists,
     releases,
     aot_releases,
     current_latest_release,
     errors) = aot_releases_check.github_upgrade_exists()

    if errors:
        for each_error in errors:
            flash(each_error, 'error')

    if releases and current_latest_release and "." in current_latest_release:
        current_latest_major_version = current_latest_release.split('.')[0]
        current_major_release = releases[0]
        current_releases = []
        releases_behind = None
        for index, each_release in enumerate(releases):
            if parse_version(each_release) >= parse_version(AOT_VERSION):
                current_releases.append(each_release)
            if parse_version(each_release) == parse_version(AOT_VERSION):
                releases_behind = index
        if upgrade_exists:
            upgrade_available = True
    else:
        current_releases = []
        current_latest_major_version = '0'
        current_major_release = '0.0.0'
        releases_behind = 0

    # Update database to reflect the current upgrade status
    mod_misc = Misc.query.first()
    if mod_misc.aot_upgrade_available != upgrade_available:
        mod_misc.aot_upgrade_available = upgrade_available
        db.session.commit()

    def not_enough_space_upgrade():
        backup_size, free_before, free_after = can_perform_backup()
        if free_after / 1000000 < 50:
            flash(
                gettext(
                    "A backup must be performed during an upgrade and there is "
                    "not enough free space to perform a backup. A backup "
                    "requires %(size_bu).1f MB but there is only %(size_free).1f "
                    "MB available, which would leave %(size_after).1f MB after "
                    "the backup. If the free space after a backup is less than 50"
                    " MB, the backup cannot proceed. Free up space by deleting "
                    "current backups.",
                    size_bu=backup_size / 1000000,
                    size_free=free_before / 1000000,
                    size_after=free_after / 1000000),
                'error')
            return True
        else:
            return False

    if request.method == 'POST':
        if (form_upgrade.upgrade.data and
                (upgrade_available or FORCE_UPGRADE_MASTER)):
            if not_enough_space_upgrade():
                pass
            elif FORCE_UPGRADE_MASTER:
                try:
                    os.remove(UPGRADE_TMP_LOG_FILE)
                except FileNotFoundError:
                    pass
                cmd = "{pth}/aot/scripts/aot_wrapper upgrade-master" \
                      " | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) 2>&1 | tee -a {log} {tmp_log}".format(
                    pth=INSTALL_DIRECTORY,
                    log=UPGRADE_LOG_FILE,
                    tmp_log=UPGRADE_TMP_LOG_FILE)
                subprocess.Popen(cmd, shell=True)

                upgrade = 1
                flash(gettext("The upgrade (from master branch) has started"), "success")
            else:
                try:
                    os.remove(UPGRADE_TMP_LOG_FILE)
                except FileNotFoundError:
                    pass
                cmd = "{pth}/aot/scripts/aot_wrapper upgrade-release-major {current_maj_version}" \
                      " | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) 2>&1 | tee -a {log} {tmp_log}".format(
                    current_maj_version=AOT_VERSION.split('.')[0],
                    pth=INSTALL_DIRECTORY,
                    log=UPGRADE_LOG_FILE,
                    tmp_log=UPGRADE_TMP_LOG_FILE)
                subprocess.Popen(cmd, shell=True)

                upgrade = 1
                mod_misc = Misc.query.first()
                mod_misc.aot_upgrade_available = False
                db.session.commit()
                flash(gettext("The upgrade has started"), "success")
        elif (form_upgrade.upgrade_next_major_version.data and
                upgrade_available):
            if not not_enough_space_upgrade():
                try:
                    os.remove(UPGRADE_TMP_LOG_FILE)
                except FileNotFoundError:
                    pass
                cmd = "{pth}/aot/scripts/aot_wrapper upgrade-release-wipe {ver}" \
                      " | ( command -v ts >/dev/null 2>&1 && ts '[%Y-%m-%d %H:%M:%S]' || cat ) 2>&1 | tee -a {log} {tmp_log}".format(
                    pth=INSTALL_DIRECTORY,
                    ver=current_latest_major_version,
                    log=UPGRADE_LOG_FILE,
                    tmp_log=UPGRADE_TMP_LOG_FILE)
                subprocess.Popen(cmd, shell=True)

                upgrade = 1
                mod_misc = Misc.query.first()
                mod_misc.aot_upgrade_available = False
                db.session.commit()
                flash(gettext(
                    "The major version upgrade has started"), "success")
        else:
            flash(gettext(
                "You cannot upgrade if an upgrade is not available"),
                "error")

    return render_template('admin/upgrade.html',
                           final_releases=FINAL_RELEASES,
                           force_upgrade_master=FORCE_UPGRADE_MASTER,
                           form_backup=form_backup,
                           form_upgrade=form_upgrade,
                           current_release=AOT_VERSION,
                           current_releases=current_releases,
                           current_major_release=current_major_release,
                           current_latest_release=current_latest_release,
                           current_latest_major_version=current_latest_major_version,
                           releases_behind=releases_behind,
                           upgrade_available=upgrade_available,
                           upgrade=upgrade,
                           is_internet=is_internet)
