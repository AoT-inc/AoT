#!/bin/bash
#
#  setup.sh - AoT install script
#
#  Usage: sudo /bin/bash /opt/AoT/install/setup.sh
#

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd -P )
INSTALL_CMD="/bin/bash ${INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh"
LOG_LOCATION=${INSTALL_DIRECTORY}/install/setup.log
INFLUX_A='NONE'
INFLUX_B='NONE'

# 플랫폼 자동 감지 (INSTALL_TARGET, INSTALL_ARCH, MACHINE_TYPE, UNAME_TYPE 설정)
# shellcheck source=install/detect_platform.sh
source "${INSTALL_DIRECTORY}/install/detect_platform.sh"

# NOTE: everything up to the language-selection dialog below runs before the
# user has chosen a UI language, so these bootstrap messages are English-only
# by design (there is no locale to render them in yet).

if [[ "$INSTALL_DIRECTORY" == "/opt/AoT" ]]; then
  printf "## Installing from /opt/AoT/install/setup.sh.\n"
elif [[ "$INSTALL_DIRECTORY" != "/opt/AoT" && ! -d /opt/AoT ]]; then
  printf "## Install directory (%s) is not /opt/AoT, and /opt/AoT does not exist. Copying there and continuing the install...\n" "${INSTALL_DIRECTORY}"
  sudo cp -Rp "${INSTALL_DIRECTORY}" /opt/AoT
  sudo /opt/AoT/install/setup.sh
  exit 1
elif [[ "$INSTALL_DIRECTORY" != "/opt/AoT" && -d /opt/AoT ]]; then
  printf "## Error: Installation aborted. /opt/AoT already exists, and setup is being run from a different directory (%s). The install cannot proceed while a previous installation is detected. Move or remove the /opt/AoT directory and run this script again, or run /opt/AoT/install/setup.sh directly.\n" "${INSTALL_DIRECTORY}"
  exit 1
fi

# 예전엔 pypa/setuptools#3278(Python 3.10/3.11 시절 setuptools/distutils
# 상호운용 버그) 대응으로 여기서 SETUPTOOLS_USE_DISTUTILS=stdlib 를 강제했다.
# Python 3.12부터 stdlib distutils 자체가 제거돼, 이 변수를 켠 채로는
# setuptools.build_meta import 가 ModuleNotFoundError: No module named
# 'distutils' 로 즉시 죽는다 - sdist(휠 없음)로 빌드되는 패키지 전부의 설치가
# 막히고, pip install -r requirements.txt 가 그 자리에서 중단돼 venv 에
# pip 외 아무것도 안 남는 사고로 이어졌다(2026-08-17 aot-gw-001, Debian 13
# trixie/Python 3.13 재현). 최신 setuptools는 자체 vendored distutils를
# 기본으로 쓰므로 이 변수 없이도 원래 버그가 재발하지 않는다 - 다시 켜지 말 것.


if [ "$EUID" -ne 0 ]; then
    printf "Error: This script must be run as root. Use \"sudo /bin/bash %s/install/setup.sh\".\n" "${INSTALL_DIRECTORY}"
    exit 1
fi

# Docker 환경에서는 대화형 설치 불가 → docker-compose 사용 안내
if [[ "${INSTALL_TARGET}" == "docker" ]]; then
    printf "\nError: A Docker environment was detected.\n"
    printf "For Docker deployments, use docker-compose instead:\n"
    printf "  cd %s/docker && docker compose up -d\n\n" "${INSTALL_DIRECTORY}"
    exit 1
fi

# Ensure upgrade_commands.sh receives consistent service user
export AOT_USER="${AOT_USER:-aot}"
export AOT_GROUP="${AOT_GROUP:-$AOT_USER}"

printf "Checking Python version...\n"
if hash python3 2>/dev/null; then
  if ! python3 "${INSTALL_DIRECTORY}"/aot/scripts/upgrade_check.py --min_python_version "3.8"; then
    printf "\nError: An incompatible Python version was detected. AoT requires Python >= 3.8 to install.\n"
    exit 1
  else
    printf "Python >= 3.6 found.\n"
  fi
else
  printf "\nError: A valid Python version could not be found. Python >= 3.6 must be in PATH to continue.\n"
  exit 1
fi

DIALOG=$(command -v dialog)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    printf "\nError: dialog is not installed. Please install dialog and try the AoT installation again.\n"
    exit 1
fi

# 설치 안내 문구 다국어 카탈로그 로드 (msg()/pmsg() 제공)
# shellcheck source=install/lang/messages.sh
source "${INSTALL_DIRECTORY}/install/lang/messages.sh"

START_A=$(date)
printf "### AoT installation initiated %s\n" "${START_A}" 2>&1 | tee -a "${LOG_LOCATION}"

# 언어 선택을 가장 먼저 묻는다 - 이후의 모든 dialog/진행 메시지가 이 선택을
# 따라간다. 이 대화상자 자체는 아직 언어가 정해지지 않은 상태에서 보여줘야
# 하므로, 각 옵션을 해당 언어의 자기 이름으로 표기해 둔다.
clear
LANGUAGE=$(dialog --title "AoT Installer" \
                  --backtitle "AoT" \
                  --menu "User Interface Language" 23 68 14 \
                  "ko": "한국어 (Korean)" \
                  "en": "English" \
                  "de": "Deutsche (German)" \
                  "es": "Español (Spanish)" \
                  "fr": "Français (French)" \
                  "it": "Italiano (Italian)" \
                  "nl": "Nederlands (Dutch)" \
                  "nn": "Norsk (Norwegian)" \
                  "pl": "Polski (Polish)" \
                  "pt": "Português (Portuguese)" \
                  "ru": "русский язык (Russian)" \
                  "sr": "српски (Serbian)" \
                  "sv": "Svenska (Swedish)" \
                  "tr": "Türkçe (Turkish)" \
                  "zh": "中文 (Chinese)" \
                  3>&1 1>&2 2>&3)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    printf "AoT installation was cancelled by the user\n" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
else
    echo "${LANGUAGE}" > "${INSTALL_DIRECTORY}/.language"
    _msg_load_lang "${LANGUAGE}"
fi

clear
LICENSE=$(dialog --title "$(msg license_title)" \
                   --backtitle "AoT" \
                   --yesno "$(msg license_body)" \
                   20 68 \
                   3>&1 1>&2 2>&3)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    pmsg cancelled 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
fi

clear
INSTALL=$(dialog --title "$(msg install_confirm_title)" \
                   --backtitle "AoT" \
                   --yesno "$(msg install_confirm_body)" \
                   20 68 \
                   3>&1 1>&2 2>&3)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    pmsg cancelled 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
fi

clear
if [[ ${INSTALL_ARCH} == 'armhf' ]]; then
    INFLUX_A=$(dialog --title "$(msg influx_db_title)" \
                        --backtitle "AoT" \
                        --menu "$(msg influx_ask_body)" 20 68 4 \
                        "0)" "$(msg influx_opt_v1_default)" \
                        "1)" "$(msg influx_opt_skip)" \
                        3>&1 1>&2 2>&3)
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        pmsg cancelled 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
elif [[ ${INSTALL_ARCH} == 'arm64' || ${INSTALL_ARCH} == 'amd64' ]]; then
    # Check if InfluxDB is already installed
    INFLUX_INSTALLED=false
    CURRENT_INFLUX_MSG=""
    if dpkg -s influxdb2 >/dev/null 2>&1; then
        INFLUX_INSTALLED=true
        CURRENT_INFLUX_MSG="$(msg influx_installed_v2)"
    elif dpkg -s influxdb >/dev/null 2>&1; then
        INFLUX_INSTALLED=true
        CURRENT_INFLUX_MSG="$(msg influx_installed_v1)"
    fi

    if [ "$INFLUX_INSTALLED" = true ]; then
        INFLUX_B=$(dialog --title "$(msg influx_db_title)" \
                            --backtitle "AoT" \
                            --menu "${CURRENT_INFLUX_MSG}\n\n$(msg influx_installed_question)" 20 68 4 \
                            "KEEP)" "$(msg influx_opt_keep)" \
                            "REINSTALL)" "$(msg influx_opt_reinstall)" \
                            "SKIP)" "$(msg influx_opt_skip_related)" \
                            3>&1 1>&2 2>&3)
    else
        INFLUX_B=$(dialog --title "$(msg influx_db_title)" \
                            --backtitle "AoT" \
                            --menu "$(msg influx_ask_body)" 20 68 4 \
                            "0)" "$(msg influx_opt_v2_recommended)" \
                            "1)" "$(msg influx_opt_v1_legacy)" \
                            "2)" "$(msg influx_opt_skip)" \
                            3>&1 1>&2 2>&3)
    fi

    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        pmsg cancelled 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
else
    pmsg arch_detect_error
    exit 1
fi

if [[ ${INFLUX_A} == '1)' || ${INFLUX_B} == '2)' || ${INFLUX_B} == 'SKIP)' ]]; then
    clear
    INSTALL=$(dialog --title "$(msg influx_db_title)" \
                       --backtitle "AoT" \
                       --yesno "$(msg influx_skip_confirm_body)" \
                       20 68 \
                       3>&1 1>&2 2>&3)
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        pmsg cancelled 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
fi

if [[ ${INFLUX_A} == 'NONE' && ${INFLUX_B} == 'NONE' ]]; then
    pmsg influx_option_missing_error
    exit 1
fi

abort()
{
    pmsg abort_banner "${INSTALL_DIRECTORY}" "${INSTALL_DIRECTORY}" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
}

trap 'abort' 0

set -e

clear
SECONDS=0
START_B=$(date)
pmsg install_begin "${START_B}" 2>&1 | tee -a "${LOG_LOCATION}"

${INSTALL_CMD} create-user 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-swap-size 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-apt 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} uninstall-apt-pip 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-packages 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} setup-virtualenv 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3-packages 2>&1 | tee -a "${LOG_LOCATION}"

# Install mosquitto MQTT broker and configure for external connections
pmsg mosquitto_installing | tee -a "${LOG_LOCATION}"
if ! dpkg -s mosquitto >/dev/null 2>&1; then
  apt-get install -y mosquitto mosquitto-clients >> "${LOG_LOCATION}" 2>&1
else
  pmsg mosquitto_already_installed | tee -a "${LOG_LOCATION}"
fi

pmsg mosquitto_configuring | tee -a "${LOG_LOCATION}"
pmsg mosquitto_conf_checking | tee -a "${LOG_LOCATION}"
MOSQUITTO_CONF="/etc/mosquitto/conf.d/aot.conf"

# 기존 파일이 있으면 덮어쓰지 않음(사용자 설정 보존)
if [ ! -f "$MOSQUITTO_CONF" ]; then
  cat <<EOF > "$MOSQUITTO_CONF"
listener 1883
allow_anonymous true
EOF
  pmsg mosquitto_conf_created "${MOSQUITTO_CONF}" | tee -a "${LOG_LOCATION}"
else
  pmsg mosquitto_conf_exists "${MOSQUITTO_CONF}" | tee -a "${LOG_LOCATION}"
fi

# Ensure main config includes conf.d
if ! grep -q '^include_dir /etc/mosquitto/conf.d' /etc/mosquitto/mosquitto.conf 2>/dev/null; then
  echo "include_dir /etc/mosquitto/conf.d" >> /etc/mosquitto/mosquitto.conf
  pmsg mosquitto_include_added | tee -a "${LOG_LOCATION}"
fi

# 서비스 활성화/재시작 - 실패해도 설치를 중단하지 않음
set +e
systemctl enable mosquitto >> "${LOG_LOCATION}" 2>&1
systemctl restart mosquitto >> "${LOG_LOCATION}" 2>&1
MOSQ_STATUS=$?
set -e

if [ $MOSQ_STATUS -ne 0 ]; then
  pmsg mosquitto_restart_warning | tee -a "${LOG_LOCATION}"
  pmsg mosquitto_diag_hint "systemctl status mosquitto --no-pager -l ; journalctl -u mosquitto -n 200 --no-pager" | tee -a "${LOG_LOCATION}"
fi

${INSTALL_CMD} install-wiringpi 2>&1 | tee -a "${LOG_LOCATION}"
if [[ ${INFLUX_B} == 'REINSTALL)' ]]; then
    pmsg influx_cleanup | tee -a "${LOG_LOCATION}"
    systemctl stop influxdb 2>/dev/null || true
    apt-get remove --purge -y influxdb influxdb2 influxdb-client 2>/dev/null || true
    rm -rf /var/lib/influxdb /var/lib/influxdb2 /etc/influxdb /etc/influxdb2 /root/.influxdbv2
fi

if [[ ${INFLUX_B} == '0)' || ${INFLUX_B} == 'REINSTALL)' ]]; then
    ${INSTALL_CMD} update-influxdb-2 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-2-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ ${INFLUX_B} == 'KEEP)' ]]; then
    pmsg influx_skip_keep | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-2-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ ${INFLUX_A} == '0)' || ${INFLUX_B} == '1)' ]]; then
    ${INSTALL_CMD} update-influxdb-1 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-1-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ ${INFLUX_A} == '1)' || ${INFLUX_B} == '2)' || ${INFLUX_B} == 'SKIP)' ]]; then
    pmsg influx_not_installing
fi
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-logrotate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} ssl-certs-generate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-aot-startup-script 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} compile-translations 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} generate-widget-html 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} build-notes-widget 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} web-server-update 2>&1 | tee -a "${LOG_LOCATION}"
pmsg starting_aotflask
systemctl start aotflask
sleep 5
${INSTALL_CMD} web-server-restart 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} web-server-connect 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-permissions 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} restart-daemon 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} install-aotmcp 2>&1 | tee -a "${LOG_LOCATION}"

trap : 0

IP=$(ip addr | grep 'state UP' -A2 | tail -n1 | awk '{print $2}' | cut -f1  -d'/')

if [[ -z ${IP} ]]; then
  IP="your.IP.address.here"
fi

END=$(date)
pmsg install_complete_log "${END}" 2>&1 | tee -a "${LOG_LOCATION}"

DURATION=$SECONDS
pmsg install_duration "$((DURATION / 60))" "$((DURATION % 60))" 2>&1 | tee -a "${LOG_LOCATION}"

pmsg completion_banner "${INSTALL_DIRECTORY}" "${IP}" 2>&1 | tee -a "${LOG_LOCATION}"
