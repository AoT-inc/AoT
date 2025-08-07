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
                                   create_settings_export)
from aot.utils.utils import append_to_log
from aot.utils.widget_generate_html import generate_widget_html

logger = logging.getLogger(__name__)

#
# Export
#

def export_measurements(form):
    """
    사용자가 입력한 기간에 따라 InfluxDB에서 타임스탬프와 측정값을 CSV 파일로 내보냅니다.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['export']['title'],
        controller=TRANSLATIONS['measurement']['title'])
    error = []

    if not form.validate():
        flash_form_errors(form)
        return url_for('routes_page.page_export')

    try:
        # 입력 데이터 로그 기록 (디버깅 목적)
        logger.info("date_range: %s, measurement: %s", form.date_range.data, form.measurement.data)

        # 날짜 범위 파싱
        start_time_str, end_time_str = form.date_range.data.split(' - ')
        start_seconds = int(time.mktime(time.strptime(start_time_str, '%m/%d/%Y %H:%M')))
        end_seconds = int(time.mktime(time.strptime(end_time_str, '%m/%d/%Y %H:%M')))

        # 측정 데이터 파싱
        measurement_parts = form.measurement.data.split(',')
        if len(measurement_parts) < 2:
            raise ValueError("측정 데이터 형식이 올바르지 않습니다. (예: id,measurement_id)")
        unique_id, measurement_id = measurement_parts[0], measurement_parts[1]

        # non‑ASCII 문자 문제 해결: URL 인코딩 적용
        unique_id = urllib.parse.quote(unique_id, safe='')
        measurement_id = urllib.parse.quote(measurement_id, safe='')

        # CSV Export를 위한 URL 구성
        url = '/export_data/{id}/{meas}/{start}/{end}'.format(
            id=unique_id,
            meas=measurement_id,
            start=start_seconds,
            end=end_seconds
        )
        return url
    except Exception as err:
        logger.exception("export_measurements() 처리 중 예외 발생")
        error.append(gettext("오류: %(err)s") % {'err': err})
        flash_success_errors(error, action, url_for('routes_page.page_export'))
        return url_for('routes_page.page_export')

def export_settings():
    """
    AoT 설정 데이터베이스(aot.db)를 ZIP 파일로 저장하여 사용자에게 제공합니다.
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
                        dt=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
            )
        else:
            error.append(data)
    except Exception as err:
        error.append(gettext("오류: %(err)s") % {'err': err})

    flash_success_errors(error, action, url_for('routes_page.page_export'))


def export_influxdb():
    """
    AoT InfluxDB 데이터베이스를 Enterprise 호환 형식으로 백업하여 ZIP 파일로 압축한 후 사용자에게 제공합니다.
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
                        dt=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
                )
            else:
                error.append(data)
        else:
            error.append(gettext("Influxdb 호스트/버전을 확인할 수 없습니다."))
    except Exception as err:
        error.append(gettext("오류: %(err)s") % {'err': err})

    flash_success_errors(error, action, url_for('routes_page.page_export'))


#
# Import
#

def thread_import_settings(tmp_folder):
    logger.info("thread_import_settings()를 사용하여 설정 가져오기를 마무리합니다.")

    try:
        # 초기화
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper initialize | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # 데이터베이스 업그레이드
        append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 데이터베이스 업그레이드\n")
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper upgrade_database | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # 패키지 설치/업데이트 (시간이 걸릴 수 있음)
        append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 패키지 설치 중 (잠시만 기다려 주세요)...\n")
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper update_dependencies | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # 위젯 HTML 생성
        generate_widget_html()

        # 초기화 재실행
        cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper initialize | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
        _, _, _ = cmd_output(cmd, user="root")

        # AoT 데몬(백엔드) 재시작
        append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 백엔드 재시작")
        if DOCKER_CONTAINER:
            subprocess.Popen('docker start aot_daemon 2>&1', shell=True)
        else:
            cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper daemon_restart | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
            a, b, c = cmd_output(cmd, user="root")

        # tmp 디렉터리가 존재하면 삭제
        if os.path.isdir(tmp_folder):
            shutil.rmtree(tmp_folder)

        # AoT Flask(프론트엔드) 재로딩
        append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 프론트엔드 재로딩")
        if DOCKER_CONTAINER:
            subprocess.Popen('docker start aot_flask 2>&1', shell=True)
        else:
            cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper frontend_reload | ts '[%Y-%m-%d %H:%M:%S]' >> {IMPORT_LOG_FILE} 2>&1"
            _, _, _ = cmd_output(cmd, user="root")
    except:
        logger.exception("thread_import_settings()에서 예외 발생")

    append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 설정 가져오기 완료")
    logger.info("설정 가져오기가 완료되었습니다.")


def import_settings(form):
    """
    export_settings()로 내보낸 AoT 설정 데이터베이스가 포함된 ZIP 파일을 받아,
    현재 AoT 설정 데이터베이스를 백업한 후 ZIP 파일의 것으로 대체합니다.
    """
    action = '{action} {controller}'.format(
        action=TRANSLATIONS['import']['title'],
        controller=TRANSLATIONS['settings']['title'])
    error = []

    try:
        logger.info("설정 가져오기를 시작합니다.")
        append_to_log(IMPORT_LOG_FILE, f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 설정 가져오기 시작됨")
        correct_format = 'AoT_AOTVERSION_Settings_DBVERSION_HOST_DATETIME.zip'
        upload_folder = os.path.join(INSTALL_DIRECTORY, 'upload')
        tmp_folder = os.path.join(upload_folder, 'aot_db_tmp')
        full_path = None

        if not form.settings_import_file.data:
            error.append(gettext("파일이 업로드되지 않았습니다."))
        elif form.settings_import_file.data.filename == '':
            error.append(gettext("파일 이름이 없습니다."))
        else:
            # 업로드된 파일 이름 분리
            file_name = form.settings_import_file.data.filename
            name = file_name.rsplit('.', 1)[0]
            extension = file_name.rsplit('.', 1)[1].lower()
            name_split = name.split('_')

            # 올바른 형식의 파일 이름을 분리
            correct_name = correct_format.rsplit('.', 1)[0]
            correct_name_1 = correct_name.split('_')[0]
            correct_name_2 = correct_name.split('_')[2]
            correct_extension = correct_format.rsplit('.', 1)[1].lower()

            # 업로드된 파일 이름과 올바른 형식 비교
            try:
                if name_split[0] != correct_name_1:
                    error.append(gettext("잘못된 파일 이름: %(filename)s: %(part)s != %(correct)s.", filename=file_name, part=name_split[0], correct=correct_name_1))
                    error.append(gettext("올바른 형식은: %(format)s", format=correct_format))
                elif name_split[2] != correct_name_2:
                    error.append(gettext("잘못된 파일 이름: %(filename)s: %(part)s != %(correct)s", filename=file_name, part=name_split[2], correct=correct_name_2))
                    error.append(gettext("올바른 형식은: %(format)s", format=correct_format))
                elif extension != correct_extension:
                    error.append(gettext("확장자가 'zip'이 아닙니다."))
                elif parse(name_split[1]) > parse(AOT_VERSION):
                    error.append(gettext("잘못된 AoT 버전: %(version)s > %(current)s. %(msg)s", version=name_split[1], current=AOT_VERSION, msg=gettext("현재 버전 이하의 데이터베이스만 가져올 수 있습니다.")))
            except Exception as err:
                error.append(gettext("파일 이름 검증 중 예외 발생: %(err)s", err=err))

        if not error:
            logger.info("가져올 파일 저장 중")
            append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 가져올 파일 저장 중")
            # 업로드 디렉터리에 파일 저장
            filename = secure_filename(form.settings_import_file.data.filename)
            full_path = os.path.join(tmp_folder, filename)
            assure_path_exists(upload_folder)
            assure_path_exists(tmp_folder)
            append_to_log(IMPORT_LOG_FILE, f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {filename}을(를) {tmp_folder}에 저장 중")
            form.settings_import_file.data.save(os.path.join(tmp_folder, filename))

            # zip 파일 내용 확인
            try:
                file_list = zipfile.ZipFile(full_path, 'r').namelist()
                if DATABASE_NAME not in file_list:
                    error.append(gettext("%(db)s 파일이 zip에 포함되어 있지 않습니다: %(list)s", db=DATABASE_NAME, list=', '.join(file_list)))
            except Exception as err:
                error.append(gettext("zip 파일 검사 중 예외 발생: %(err)s", err=err))

        if not error:
            logger.info("가져온 파일 압축 해제 중")
            append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 가져온 파일 압축 해제 중")
            # zip 파일 압축 해제
            try:
                assure_path_exists(tmp_folder)
                zip_ref = zipfile.ZipFile(full_path, 'r')
                append_to_log(IMPORT_LOG_FILE, f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {full_path}을(를) {tmp_folder}로 압축 해제 중")
                zip_ref.extractall(tmp_folder)
                zip_ref.close()
            except Exception as err:
                error.append(gettext("zip 파일 추출 중 예외 발생: %(err)s", err=err))

        if not error:
            logger.info("데몬 중지 및 파일 복사 중")
            append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 데몬 중지 및 파일 복사 중")
            try:
                if DOCKER_CONTAINER:
                    subprocess.Popen('docker stop aot_daemon 2>&1', shell=True)
                else:
                    # AoT 데몬(백엔드) 중지
                    cmd = f"{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper daemon_stop"
                    _, _, _ = cmd_output(cmd, user="root")

                # 현재 데이터베이스 백업 및 가져온 aot.db로 교체
                imported_database = os.path.join(tmp_folder, DATABASE_NAME)
                backup_name = f"{SQL_DATABASE_AOT}.backup_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
                full_path_backup = os.path.join(DATABASE_PATH, backup_name)

                append_to_log(IMPORT_LOG_FILE,
                              f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {SQL_DATABASE_AOT}을(를) {full_path_backup}로 이름 변경 중")
                os.rename(SQL_DATABASE_AOT, full_path_backup)  # 현재 데이터베이스 백업
                append_to_log(IMPORT_LOG_FILE,
                              f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {imported_database}을(를) {SQL_DATABASE_AOT}로 이동 중")
                shutil.move(imported_database, SQL_DATABASE_AOT)  # 가져온 데이터베이스로 교체

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

                # 사용자 지정 함수/입력/출력/위젯 및 생성된 HTML/Python 코드 삭제
                for each_dir in delete_directories:
                    append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 디렉터리 삭제 중: {each_dir}")
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

                # 압축된 사용자 지정 함수/입력/출력/위젯 복원
                for each_dir in restore_directories:
                    append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {each_dir[1]} 디렉터리 복원 중: {each_dir[0]}")
                    extract_dir = os.path.join(tmp_folder, each_dir[1])
                    if not os.path.exists(extract_dir):
                        continue
                    for folder_name, sub_folders, filenames in os.walk(extract_dir):
                        for filename in filenames:
                            file_path = os.path.join(folder_name, filename)
                            new_path = os.path.join(each_dir[0], filename)
                            append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {new_path} 복원 중")
                            try:
                                shutil.move(file_path, new_path)
                            except:
                                append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 오류: {filename} 복원 실패")
                                logger.exception("파일 이동 중 예외 발생")

                logger.info("가져오기 마무리 중")
                import_settings_db = threading.Thread(
                    target=thread_import_settings,
                    args=(tmp_folder,))
                import_settings_db.start()

                return True
            except Exception as err:
                logger.exception("설정 가져오기 중 예외 발생")
                error.append(gettext("데이터베이스 교체 중 예외 발생: %(err)s", err=err))
                return

    except Exception as err:
        error.append(gettext("예외 발생: %(err)s", err=err))

    if error:
        append_to_log(IMPORT_LOG_FILE, f"\n\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 설정 가져오기를 완료하지 못했습니다. 오류:")
    for each_err in error:
        append_to_log(IMPORT_LOG_FILE, f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 오류: {each_err}")

    flash_success_errors(error, action, url_for('routes_page.page_export'))