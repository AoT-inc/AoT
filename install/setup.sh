#!/bin/bash
#
#  setup.sh - AoT install script
#
#  Usage: sudo /bin/bash /opt/AoT/install/setup.sh
#

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd -P )
INSTALL_CMD="/bin/bash ${INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh"
LOG_LOCATION=${INSTALL_DIRECTORY}/install/setup.log
UNAME_TYPE=$(uname -m)
MACHINE_TYPE=$(dpkg --print-architecture)
INFLUX_A='NONE'
INFLUX_B='NONE'

if [[ "$INSTALL_DIRECTORY" == "/opt/AoT" ]]; then
  printf "## 현재 /opt/AoT/install/setup.sh에서 설치를 진행 중입니다.\n"
elif [[ "$INSTALL_DIRECTORY" != "/opt/AoT" && ! -d /opt/AoT ]]; then
  printf "## 현재 설치 디렉터리(${INSTALL_DIRECTORY})가 /opt/AoT가 아니고 /opt/AoT가 존재하지 않습니다. 복사 후 설치를 진행합니다...\n"
  sudo cp -Rp "${INSTALL_DIRECTORY}" /opt/AoT
  sudo /opt/AoT/install/setup.sh
  exit 1
elif [[ "$INSTALL_DIRECTORY" != "/opt/AoT" && -d /opt/AoT ]]; then
  printf "## 에러: 설치가 중단되었습니다. /opt/AoT가 이미 존재하고 현재 디렉터리(${INSTALL_DIRECTORY})에서 setup을 실행하고 있습니다. 이전 설치가 감지되면 설치를 진행할 수 없습니다. /opt/AoT 디렉터리를 이동하거나 삭제한 후 이 스크립트를 다시 실행하거나 /opt/AoT/install/setup.sh를 실행하세요.\n"
  exit 1
fi

# Fix for below issue(s)
# https://github.com/pypa/setuptools/issues/3278
# https://github.com/aot-inc/AoT/issues/1149
export SETUPTOOLS_USE_DISTUTILS=stdlib


if [ "$EUID" -ne 0 ]; then
    printf "오류: 이 스크립트는 root 권한으로 실행해야 합니다. \"sudo /bin/bash %s/install/setup.sh\"를 사용하세요.\n" "${INSTALL_DIRECTORY}"
    exit 1
fi

# Ensure upgrade_commands.sh receives consistent service user
export AOT_USER="${AOT_USER:-aot}"
export AOT_GROUP="${AOT_GROUP:-$AOT_USER}"

printf "Python 버전 확인 중...\n"
if hash python3 2>/dev/null; then
  if ! python3 "${INSTALL_DIRECTORY}"/aot/scripts/upgrade_check.py --min_python_version "3.6"; then
    printf "\n오류: 올바르지 않은 Python 버전이 감지되었습니다. AoT 설치를 위해서는 Python >= 3.6이 필요합니다.\n"
    exit 1
  else
    printf "Python >= 3.6 found.\n"
  fi
else
  printf "\n오류: 올바른 Python 버전을 찾을 수 없습니다. 설치를 진행하려면 PATH에 Python >= 3.6이 필요합니다.\n"
  exit 1
fi

DIALOG=$(command -v dialog)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    printf "\n오류: dialog가 설치되어 있지 않습니다. dialog를 설치한 후 AoT 설치를 다시 시도하세요.\n"
    exit 1
fi

START_A=$(date)
printf "### AoT installation initiated %s\n" "${START_A}" 2>&1 | tee -a "${LOG_LOCATION}"

clear
LICENSE=$(dialog --title "AoT Installer: 라이선스 동의" \
                   --backtitle "AoT" \
                   --yesno "AoT는 무료 소프트웨어입니다.\n여러분은 이 소프트웨어를 자유롭게 배포하거나 수정할 수 있으며, 그 조건은 무료 소프트웨어 재단(FSF)이 발표한 GNU 일반 공중 사용 허가서(GPL) 제3판 또는 (원하는 경우) 이후 버전에 따릅니다.\n\nAoT는 유용할 것이라는 희망 아래 배포되지만, 상품성이나 특정 목적에의 적합성에 대한 보증을 포함하여 어떠한 형태의 보증도 제공되지 않습니다. 자세한 내용은 GNU 일반 공중 사용 허가서를 참고하십시오.\n\nAoT와 함께 GNU 일반 공중 사용 허가서 사본을 받으셨을 것입니다. 받지 못하셨다면 gnu.org/licenses를 참조해 주세요.\n\n이 라이선스 조건에 동의하시겠습니까?" \
                   20 68 \
                   3>&1 1>&2 2>&3)

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
    printf "사용자에 의해 AoT 설치가 취소되었습니다\n" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
else
    echo "${LANGUAGE}" > "${INSTALL_DIRECTORY}/.language"
fi

clear
INSTALL=$(dialog --title "AoT Installer: Install" \
                   --backtitle "AoT" \
                   --yesno "AoT는 현재 사용자의 홈 디렉터리에 설치됩니다. 이 과정에서 nginx 웹 서버를 포함한 여러 소프트웨어 패키지가 apt를 통해 설치됩니다. 설치를 진행하시겠습니까?" \
                   20 68 \
                   3>&1 1>&2 2>&3)
exitstatus=$?
if [ $exitstatus != 0 ]; then
    printf "사용자에 의해 AoT 설치가 취소되었습니다\n" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
fi

clear
if [[ ${MACHINE_TYPE} == 'armhf' ]]; then
    INFLUX_A=$(dialog --title "AoT Installer: Measurement Database" \
                        --backtitle "AoT" \
                        --menu "InfluxDB를 설치하시겠습니까?\n\n지금 InfluxDB를 설치하지 않으면, AoT 설치 후 설정 메뉴에서 InfluxDB 서버 정보와 인증 정보를 수동으로 입력하셔야 합니다." 20 68 4 \
                        "0)" "Influxdb 1.x (기본값)" \
                        "1)" "Influxdb 설치하지 않음" \
                        3>&1 1>&2 2>&3)
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        printf "사용자에 의해 AoT 설치가 취소되었습니다\n" 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
elif [[ ${MACHINE_TYPE} == 'arm64' || ${UNAME_TYPE} == 'x86_64' ]]; then
    INFLUX_B=$(dialog --title "AoT Installer: Measurement Database" \
                        --backtitle "AoT" \
                        --menu "InfluxDB를 설치하시겠습니까?\n\n지금 InfluxDB를 설치하지 않으면, AoT 설치 후 설정 메뉴에서 InfluxDB 서버 정보와 인증 정보를 수동으로 입력하셔야 합니다." 20 68 4 \
                        "0)" "Influxdb 2.x 설치(추천)" \
                        "1)" "Influxdb 1.x 설치(32비트용 구버전)" \
                        "2)" "Influxdb 설치하지 않음" \
                        3>&1 1>&2 2>&3)
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        printf "사용자에 의해 AoT 설치가 취소되었습니다\n" 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
else
    printf "\n오류: 시스템 아키텍처를 감지할 수 없습니다\n"
    exit 1
fi

if [[ ${INFLUX_A} == '1)' || ${INFLUX_B} == '2)' ]]; then
    clear
    INSTALL=$(dialog --title "AoT Installer: Measurement Database" \
                       --backtitle "AoT" \
                       --yesno "InfluxDB를 설치하지 않도록 선택하셨습니다. 이는 외부 InfluxDB 서버를 사용하려는 경우에 해당됩니다. 설치 후 AoT 설정 메뉴에서 InfluxDB 클라이언트 옵션을 반드시 수정해 주셔야 정상적인 데이터 저장 및 조회가 가능합니다. InfluxDB를 설치하려면 취소를 선택한 후 설치를 다시 시작해 주세요." \
                       20 68 \
                       3>&1 1>&2 2>&3)
    exitstatus=$?
    if [ $exitstatus != 0 ]; then
        printf "사용자에 의해 AoT 설치가 취소되었습니다\n" 2>&1 | tee -a "${LOG_LOCATION}"
        exit 1
    fi
fi

if [[ ${INFLUX_A} == 'NONE' && ${INFLUX_B} == 'NONE' ]]; then
    printf "\n오류: Influx 설치 옵션이 선택되지 않았습니다\n"
    exit 1
fi

abort()
{
    printf "
****************************************
** AoT 설치 중 오류 발생! **
****************************************

AoT가 정상적으로 설치되지 않았을 수 있습니다!

문제의 전체 내용을 확인하려면 setup 로그의 마지막 부분을 확인하세요:
%s/install/setup.log

설치 중 문제가 발생했다면, 아래의 링크로 버그 리포트를 제출해 주세요:
https://github.com/AoT-inc/AoT/issues

버그 리포트에는 아래 경로의 setup 로그에서 관련된 부분을 첨부해 주세요:
%s/install/setup.log
" "${INSTALL_DIRECTORY}" "${INSTALL_DIRECTORY}" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
}

trap 'abort' 0

set -e

clear
SECONDS=0
START_B=$(date)
printf "#### AoT 설치가 시작됩니다. %s\n" "${START_B}" 2>&1 | tee -a "${LOG_LOCATION}"

${INSTALL_CMD} create-user 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-swap-size 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-apt 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} uninstall-apt-pip 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-packages 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} setup-virtualenv 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3-packages 2>&1 | tee -a "${LOG_LOCATION}"

# Install mosquitto MQTT broker and configure for external connections
echo "#### 설치중: mosquitto MQTT broker" | tee -a "${LOG_LOCATION}"
if ! dpkg -s mosquitto >/dev/null 2>&1; then
  apt-get install -y mosquitto mosquitto-clients >> "${LOG_LOCATION}" 2>&1
else
  echo "#### mosquitto 이미 설치됨 - 설치 단계 건너뜀" | tee -a "${LOG_LOCATION}"
fi

echo "#### mosquitto를 외부 연결 허용으로 설정 중" | tee -a "${LOG_LOCATION}"
echo "#### mosquitto 설정 파일 생성/검증 중" | tee -a "${LOG_LOCATION}"
MOSQUITTO_CONF="/etc/mosquitto/conf.d/aot.conf"

# 기존 파일이 있으면 덮어쓰지 않음(사용자 설정 보존)
if [ ! -f "$MOSQUITTO_CONF" ]; then
  cat <<EOF > "$MOSQUITTO_CONF"
listener 1883
allow_anonymous true
EOF
  echo "#### ${MOSQUITTO_CONF} 생성 완료" | tee -a "${LOG_LOCATION}"
else
  echo "#### ${MOSQUITTO_CONF} 이미 존재 - 덮어쓰지 않음" | tee -a "${LOG_LOCATION}"
fi

# Ensure main config includes conf.d
if ! grep -q '^include_dir /etc/mosquitto/conf.d' /etc/mosquitto/mosquitto.conf 2>/dev/null; then
  echo "include_dir /etc/mosquitto/conf.d" >> /etc/mosquitto/mosquitto.conf
  echo "#### /etc/mosquitto/mosquitto.conf 에 include_dir 추가" | tee -a "${LOG_LOCATION}"
fi

# 서비스 활성화/재시작 - 실패해도 설치를 중단하지 않음
set +e
systemctl enable mosquitto >> "${LOG_LOCATION}" 2>&1
systemctl restart mosquitto >> "${LOG_LOCATION}" 2>&1
MOSQ_STATUS=$?
set -e

if [ $MOSQ_STATUS -ne 0 ]; then
  echo "#### 경고: mosquitto 재시작 실패. 설치는 계속 진행합니다." | tee -a "${LOG_LOCATION}"
  echo "#### 진단: systemctl status mosquitto --no-pager -l ; journalctl -u mosquitto -n 200 --no-pager" | tee -a "${LOG_LOCATION}"
fi

${INSTALL_CMD} install-wiringpi 2>&1 | tee -a "${LOG_LOCATION}"
if [[ ${INFLUX_B} == '0)' ]]; then
    ${INSTALL_CMD} update-influxdb-2 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-2-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ ${INFLUX_A} == '0)' || ${INFLUX_B} == '1)' ]]; then
    ${INSTALL_CMD} update-influxdb-1 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-1-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ ${INFLUX_A} == '1)' || ${INFLUX_B} == '2)' ]]; then
    printf "Instructed to not install InfluxDB/n"
fi
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-logrotate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} ssl-certs-generate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-aot-startup-script 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} compile-translations 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} generate-widget-html 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} web-server-update 2>&1 | tee -a "${LOG_LOCATION}"
printf "\n#### Starting aotflask manually to complete setup\n"
systemctl start aotflask
sleep 5
${INSTALL_CMD} web-server-restart 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} web-server-connect 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-permissions 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} restart-daemon 2>&1 | tee -a "${LOG_LOCATION}"

trap : 0

IP=$(ip addr | grep 'state UP' -A2 | tail -n1 | awk '{print $2}' | cut -f1  -d'/')

if [[ -z ${IP} ]]; then
  IP="your.IP.address.here"
fi

END=$(date)
printf "#### AoT 설치 완료 %s\n" "${END}" 2>&1 | tee -a "${LOG_LOCATION}"

DURATION=$SECONDS
printf "#### 전체 설치 시간: %d minutes and %d seconds\n" "$((DURATION / 60))" "$((DURATION % 60))" 2>&1 | tee -a "${LOG_LOCATION}"

printf "
***************************************
** AoT 설치가 완료되었습니다! **
***************************************

모든 설치가 완료되었습니다. 하지만 모든 설정이 완료된 것을 의미하지는 않습니다.
만약 어떠한 문제가 발생했다면, 아래의 로그를 확인해주세요:
%s/install/setup.log

다음 주소: https://${IP}/, 또는 무엇이든 장치의 IP 주소를 입력하여 
웹 브라우저에 입력하면 AoT의 홈페이지로 이동할 수 있습니다.
관리자 계정을 생성하고 설정을 진행해주세요.
" "${INSTALL_DIRECTORY}" "${IP}" 2>&1 | tee -a "${LOG_LOCATION}"
