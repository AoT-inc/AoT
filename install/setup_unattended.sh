#!/bin/bash
#
#  setup_unattended.sh - AoT 비대화형(무인) 설치 스크립트
#
#  사용법:
#    sudo /bin/bash /opt/AoT/install/setup_unattended.sh [influx-option] [--target TARGET]
#
#  influx-option:
#    1  - InfluxDB 1.x 설치
#    2  - InfluxDB 2.x 설치 (기본값, arm64/amd64)
#    0  - InfluxDB 설치 안 함
#
#  --target TARGET:
#    raspi   - 라즈베리파이 (GPIO, WiringPi, swap 조정 포함)
#    debian  - 데비안/Ubuntu x86_64 (서버용)
#    docker  - Docker 컨테이너 (systemd/nginx 서비스 생략)
#    (생략 시 자동 감지)
#

INSTALL_DIRECTORY=$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd -P )
INSTALL_CMD="/bin/bash ${INSTALL_DIRECTORY}/aot/scripts/upgrade_commands.sh"
LOG_LOCATION=${INSTALL_DIRECTORY}/install/setup.log

# setup.sh 참고: SETUPTOOLS_USE_DISTUTILS=stdlib 는 Python 3.12+에서
# setuptools.build_meta import 자체를 깨뜨려(stdlib distutils 제거됨)
# sdist 빌드가 전부 실패한다 - 절대 다시 켜지 말 것.

if [ "$EUID" -ne 0 ]; then
    printf "Must be run as root: \"sudo /bin/bash %s/install/setup_unattended.sh [influx-option] [--target TARGET]\"\n" "${INSTALL_DIRECTORY}"
    exit 1
fi

# ------------------------------------------------------------------
# 인자 파싱: [influx-option] [--target TARGET]
# ------------------------------------------------------------------
INFLUX_OPT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            INSTALL_TARGET="$2"
            shift 2
            ;;
        0|1|2)
            INFLUX_OPT="$1"
            shift
            ;;
        *)
            printf "Error: Unrecognized argument: %s\n" "$1"
            printf "Usage: sudo setup_unattended.sh [0|1|2] [--target raspi|debian|docker]\n"
            exit 1
            ;;
    esac
done

# ------------------------------------------------------------------
# 플랫폼 자동 감지 (INSTALL_TARGET, INSTALL_ARCH 설정)
# ------------------------------------------------------------------
# shellcheck source=install/detect_platform.sh
source "${INSTALL_DIRECTORY}/install/detect_platform.sh"

# ------------------------------------------------------------------
# influx-option 기본값: 아키텍처에 따라 자동 선택
# ------------------------------------------------------------------
if [ -z "${INFLUX_OPT}" ]; then
    if [[ "${INSTALL_TARGET}" == "docker" ]]; then
        INFLUX_OPT="0"   # Docker: InfluxDB는 별도 컨테이너
    elif [[ "${INSTALL_ARCH}" == "armhf" ]]; then
        INFLUX_OPT="1"   # 라즈베리파이 32비트: InfluxDB 1.x
    else
        INFLUX_OPT="2"   # arm64/amd64: InfluxDB 2.x
    fi
    printf "#### InfluxDB 옵션 자동 선택: %s (대상: %s, 아키: %s)\n" \
        "${INFLUX_OPT}" "${INSTALL_TARGET}" "${INSTALL_ARCH}"
fi

case "${INFLUX_OPT}" in
    '1') printf "#### AoT 설치 - InfluxDB 1.x\n" ;;
    '2') printf "#### AoT 설치 - InfluxDB 2.x\n" ;;
    '0') printf "#### AoT 설치 - InfluxDB 설치 안 함\n" ;;
    *)
        printf "Error: 알 수 없는 influx-option: %s (0|1|2 사용)\n" "${INFLUX_OPT}"
        exit 1
        ;;
esac

printf "Checking Python version...\n"
if hash python3 2>/dev/null; then
  if ! python3 "${INSTALL_DIRECTORY}"/aot/scripts/upgrade_check.py --min_python_version "3.8"; then
    printf "Error: Incorrect Python version found. AoT requires Python >= 3.8.\n"
    exit 1
  else
    printf "Python >= 3.8 found. Continuing with the install.\n"
  fi
else
  printf "\nError: python3 binary required in PATH to proceed with the install.\n"
  exit 1
fi

NOW=$(date)
printf "### AoT installation initiated %s\n\n" "${NOW}" 2>&1 | tee -a "${LOG_LOCATION}"

abort()
{
    printf "
**********************************
** ERROR During AoT Install! **
**********************************

An error occurred that may have prevented AoT from
being installed properly!

Open to the end of the setup log to view the full error:
%s/install/setup.log

Please contact the developer by submitting a bug report
at https://github.com/AoT-inc/AoT/issues with the
pertinent excerpts from the setup log located at:
%s/install/setup.log
" "${INSTALL_DIRECTORY}" "${INSTALL_DIRECTORY}" 2>&1 | tee -a "${LOG_LOCATION}"
    exit 1
}

trap 'abort' 0
set -e

SECONDS=0
NOW=$(date)
printf "#### AoT installation began %s\n" "${NOW}" 2>&1 | tee -a "${LOG_LOCATION}"

# ------------------------------------------------------------------
# 공통 설치 단계
# ------------------------------------------------------------------
${INSTALL_CMD} create-user 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-apt 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} uninstall-apt-pip 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-packages 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} setup-virtualenv 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-pip3-packages 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} pip-clear-cache 2>&1 | tee -a "${LOG_LOCATION}"

# ------------------------------------------------------------------
# 라즈베리파이 전용: swap 크기 조정, GPIO 라이브러리
# ------------------------------------------------------------------
if [[ "${INSTALL_TARGET}" == "raspi" ]]; then
    printf "#### [raspi] swap 크기 조정 중...\n" | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-swap-size 2>&1 | tee -a "${LOG_LOCATION}"
fi

# WiringPi: ARM 아키텍처에서만 설치 (upgrade_commands.sh 내부에서도 체크하지만 명시)
if [[ "${INSTALL_TARGET}" == "raspi" || "${INSTALL_ARCH}" == "armhf" || "${INSTALL_ARCH}" == "arm64" ]]; then
    ${INSTALL_CMD} install-wiringpi 2>&1 | tee -a "${LOG_LOCATION}"
else
    printf "#### [%s] WiringPi 생략 (비-ARM 플랫폼)\n" "${INSTALL_TARGET}" | tee -a "${LOG_LOCATION}"
fi

# ------------------------------------------------------------------
# Mosquitto MQTT 브로커 (Docker 제외)
# ------------------------------------------------------------------
if [[ "${INSTALL_TARGET}" != "docker" ]]; then
    echo "#### 설치 중: mosquitto MQTT broker" | tee -a "${LOG_LOCATION}"
    if ! dpkg -s mosquitto >/dev/null 2>&1; then
        apt-get install -y mosquitto mosquitto-clients >> "${LOG_LOCATION}" 2>&1
    else
        echo "#### mosquitto 이미 설치됨 - 건너뜀" | tee -a "${LOG_LOCATION}"
    fi

    echo "#### mosquitto 외부 연결 허용 설정 중" | tee -a "${LOG_LOCATION}"
    MOSQUITTO_CONF="/etc/mosquitto/conf.d/aot.conf"
    if [ ! -f "$MOSQUITTO_CONF" ]; then
        cat <<EOF > "$MOSQUITTO_CONF"
listener 1883
allow_anonymous true
EOF
        echo "#### ${MOSQUITTO_CONF} 생성 완료" | tee -a "${LOG_LOCATION}"
    else
        echo "#### ${MOSQUITTO_CONF} 이미 존재 - 덮어쓰지 않음" | tee -a "${LOG_LOCATION}"
    fi

    if ! grep -q '^include_dir /etc/mosquitto/conf.d' /etc/mosquitto/mosquitto.conf 2>/dev/null; then
        echo "include_dir /etc/mosquitto/conf.d" >> /etc/mosquitto/mosquitto.conf
    fi

    set +e
    systemctl enable mosquitto >> "${LOG_LOCATION}" 2>&1
    systemctl restart mosquitto >> "${LOG_LOCATION}" 2>&1
    MOSQ_STATUS=$?
    set -e
    if [ $MOSQ_STATUS -ne 0 ]; then
        echo "#### 경고: mosquitto 재시작 실패. 설치는 계속 진행합니다." | tee -a "${LOG_LOCATION}"
    fi
else
    printf "#### [docker] Mosquitto 생략 (별도 컨테이너로 운영 권장)\n" | tee -a "${LOG_LOCATION}"
fi

# ------------------------------------------------------------------
# InfluxDB 설치
# ------------------------------------------------------------------
if [[ "${INFLUX_OPT}" == '1' ]]; then
    ${INSTALL_CMD} update-influxdb-1 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-1-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ "${INFLUX_OPT}" == '2' ]]; then
    ${INSTALL_CMD} update-influxdb-2 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-influxdb-2-db-user 2>&1 | tee -a "${LOG_LOCATION}"
elif [[ "${INFLUX_OPT}" == '0' ]]; then
    printf "#### InfluxDB 설치 생략 (외부 서버 사용)\n"
fi

# ------------------------------------------------------------------
# 공통 초기화
# ------------------------------------------------------------------
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} update-logrotate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} ssl-certs-generate 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} compile-translations 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} generate-widget-html 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} build-notes-widget 2>&1 | tee -a "${LOG_LOCATION}"
${INSTALL_CMD} initialize 2>&1 | tee -a "${LOG_LOCATION}"

# ------------------------------------------------------------------
# 웹 서버 및 서비스 등록 (Docker 제외: systemd 없음)
# ------------------------------------------------------------------
if [[ "${INSTALL_TARGET}" != "docker" ]]; then
    ${INSTALL_CMD} update-aot-startup-script 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} web-server-update 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} web-server-restart 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} web-server-connect 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-permissions 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} restart-daemon 2>&1 | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} install-aotmcp 2>&1 | tee -a "${LOG_LOCATION}"
else
    printf "#### [docker] systemd 서비스 등록 생략 (컨테이너 엔트리포인트가 직접 실행)\n" | tee -a "${LOG_LOCATION}"
    ${INSTALL_CMD} update-permissions 2>&1 | tee -a "${LOG_LOCATION}"
fi

trap : 0

IP=$(ip addr 2>/dev/null | grep 'state UP' -A2 | tail -n1 | awk '{print $2}' | cut -f1 -d'/')
if [[ -z "${IP}" ]]; then
  IP="your.IP.address.here"
fi

CURRENT_DATE=$(date)
printf "#### AoT Installer finished %s\n" "${CURRENT_DATE}" 2>&1 | tee -a "${LOG_LOCATION}"

DURATION=$SECONDS
printf "#### Total install time: %d minutes and %d seconds\n" "$((DURATION / 60))" "$((DURATION % 60))" 2>&1 | tee -a "${LOG_LOCATION}"

printf "
*********************************
** AoT finished installing! **
*********************************

Target: %s | Arch: %s

Although the install finished, it doesn't necessarily mean it installed correctly.
If you experience issues, review the full install log located at:
%s/install/setup.log

Go to https://%s/, or whatever your device's
IP address is, to create an admin user and log in.
" "${INSTALL_TARGET}" "${INSTALL_ARCH}" "${INSTALL_DIRECTORY}" "${IP}" 2>&1 | tee -a "${LOG_LOCATION}"
