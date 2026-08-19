#!/bin/bash
#
#  upgrade_commands.sh - AoT commands
#

exec 2>&1

# if [[ "$EUID" -ne 0 ]]; then
#     printf "Must be run as root.\n"
#     exit 1
# fi

# Current AoT major version number, read from the installed version rather than
# hardcoded. It sat at "8" -- the Mycodo 8.x lineage this project came from --
# for the whole 26.x era, so `upgrade-aot` asked GitHub for the newest 8.x
# release, got nothing back, and aborted with "Latest version: None". The
# upgrade looked broken while the release was sitting right there
# (2026-08-13, aot-005, upgrading 26.08.2 -> 26.08.5).
#
# Deliberately no numeric fallback: a default here is exactly what went stale.
# If this cannot be read, 'upgrade-aot' below says so and stops.
_AOT_VERSION_FILE="$(dirname "${BASH_SOURCE[0]}")/../config/__init__.py"
AOT_MAJOR_VERSION="$(sed -n "s/^AOT_VERSION[[:space:]]*=[[:space:]]*'\([0-9][0-9]*\)\..*/\1/p" \
    "${_AOT_VERSION_FILE}" 2>/dev/null | head -1)"

# Runtime service user/group (Mycodo-like default). Can be overridden via environment.
AOT_USER="${AOT_USER:-aot}"
AOT_GROUP="${AOT_GROUP:-${AOT_USER}}"

# 소스 컴파일(numpy 등) 시 코어 여러 개가 한꺼번에 최대클럭까지 치솟으면 전류가
# 급증한다. 현장 전원(배터리/솔라/부실한 어댑터 등, 항상 5V/3A가 보장되지 않는
# 환경)에서는 이게 저전압 브라운아웃→보드 재부팅으로 이어질 수 있다(2026-08-17
# aot-gw-001 실측: numpy 메타데이터 준비 중 재부팅, dmesg에 Undervoltage
# detected 다수 + vcgencmd get_throttled 에 언더볼트 이력 플래그 남음).
# taskset으로 코어 수 자체를 줄이면 nproc()을 참조하는 대부분의 빌드 백엔드
# (ninja/make/meson)가 스스로 job 수를 낮춘다 - 개별 패키지마다 빌드 플래그를
# 맞출 필요가 없다. MAKEFLAGS/NPY_NUM_BUILD_JOBS/CMAKE_BUILD_PARALLEL_LEVEL는
# nproc()을 안 쓰는 소수의 백엔드를 위한 보조 장치.
# INSTALL_TARGET(raspi/debian/docker)이 아니라 MACHINE_TYPE(아키텍처)로 가른다 -
# 전원 부실 위험은 OS 배포판이 아니라 ARM SBC라는 하드웨어 특성에서 온다.
# detect_platform.sh를 거치지 않은 단독 호출(예: aot-commands) 대비 자체 폴백 포함.
if [ -z "${MACHINE_TYPE}" ]; then
    case "$(uname -m)" in
        aarch64|arm64) MACHINE_TYPE="arm64" ;;
        armv7l|armv6l) MACHINE_TYPE="armhf" ;;
        *)             MACHINE_TYPE="$(uname -m)" ;;
    esac
fi
_AOT_NPROC="$(nproc 2>/dev/null || echo 4)"
if [ -z "${AOT_BUILD_JOBS}" ]; then
    if [[ "${MACHINE_TYPE}" == 'arm64' || "${MACHINE_TYPE}" == 'armhf' ]]; then
        # 1코어(완전 직렬)가 가장 안전하지만 빌드 시간이 크게 늘어난다. 절반
        # 코어를 절충값으로 쓴다 - 4코어 기준 피크 전류를 대략 반으로 줄이면서
        # 완전 직렬보다는 빠르다. 전원이 확실하면 AOT_BUILD_JOBS=4 처럼 직접
        # 지정해서 풀 수 있고, 전원이 더 불안하면 1로 낮출 수도 있다.
        AOT_BUILD_JOBS=$(( (_AOT_NPROC + 1) / 2 ))
        [ "${AOT_BUILD_JOBS}" -lt 1 ] && AOT_BUILD_JOBS=1
    else
        AOT_BUILD_JOBS="${_AOT_NPROC}"
    fi
fi
if [ "${AOT_BUILD_JOBS}" -lt "${_AOT_NPROC}" ] 2>/dev/null; then
    AOT_TASKSET_PREFIX=(taskset -c "0-$((AOT_BUILD_JOBS - 1))")
else
    AOT_TASKSET_PREFIX=()
fi
export MAKEFLAGS="-j${AOT_BUILD_JOBS}"
export NPY_NUM_BUILD_JOBS="${AOT_BUILD_JOBS}"
export CMAKE_BUILD_PARALLEL_LEVEL="${AOT_BUILD_JOBS}"

# Dependency versions/URLs
PIGPIO_URL="https://github.com/joan2937/pigpio/archive/v79.tar.gz"
MCB2835_URL="http://www.airspayce.com/mikem/bcm2835/bcm2835-1.50.tar.gz"
WIRINGPI_URL_ARMHF="https://github.com/WiringPi/WiringPi/releases/download/3.10/wiringpi_3.10_armhf.deb"
WIRINGPI_URL_ARM64="https://github.com/WiringPi/WiringPi/releases/download/3.10/wiringpi_3.10_arm64.deb"

INFLUXDB1_VERSION="1.8.10"

# Required apt packages
# build-essential/pkg-config: numpy 등 ARM64용 wheel이 없는 패키지가 소스
# 컴파일로 빠질 때 필요(gcc/g++만으로는 make/dpkg-dev/pkg-config가 안 갖춰짐).
# swig/liblgpio-dev: Adafruit-Blinka가 lgpio 백엔드(Raspberry Pi 5 등 신형
# GPIO칩)로 빌드될 때 필요 - 없으면 MCP23017 등 Blinka 기반 장치 추가 시
# "자동 설치되어야 하는데 계속 실패"로 나타난다(2026-08-16 라즈베리파이 설치 사건).
# libopenblas-dev: numpy/scipy용 BLAS. libatlas-base-dev는 Debian 13(trixie)에서
# 완전히 제거돼(ATLAS 폐기, OpenBLAS로 대체) 패키지명이 목록에 남아있으면 apt가
# 배치 전체를 거부한다 - 이 한 줄 때문에 nginx/gcc/python3-dev 등 APT_PKGS
# 전부가 설치되지 않고, 그 상태에서 numpy 빌드도 실패해 pip install이 통째로
# 중단되는 사고로 이어졌다(2026-08-17 aot-gw-001 재설치 검증에서 재현).
APT_PKGS="build-essential gcc g++ git jq libffi-dev libgeos-dev libheif-dev libi2c-dev liblgpio-dev libopenblas-dev logrotate mawk moreutils netcat-openbsd nginx pkg-config python3 python3-dev python3-pip python3-setuptools python3-venv rng-tools sqlite3 swig unzip wget"

UNAME_TYPE=$(uname -m)
MACHINE_TYPE=$(dpkg --print-architecture)

# Get the AoT root directory
SOURCE="${BASH_SOURCE[0]}"

while [[ -h "$SOURCE" ]]; do # resolve $SOURCE until the file is no longer a symlink
    DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE" # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done

AOT_PATH="$( cd -P "$( dirname "${SOURCE}" )/../.." && pwd )"

cd "${AOT_PATH}" || return

HELP_OPTIONS="upgrade_commands.sh [option] - Program to execute various aot commands

Options:
  backup-create                 Create a backup of the /opt/AoT directory
  backup-restore [backup]       Restore [backup] location, which must be the full path to the backup.
                                Ex.: '/var/AoT-backups/AoT-backup-2018-03-11_21-19-15-5.6.4/'
  compile-aot-wrapper        Compile aot_wrapper.c
  compile-translations          Compile language translations for web interface
  create-files-directories      Create required directories
  create-symlinks               Create required symlinks
  create-user                   Create 'aot' user and add to appropriate groups
  initialize                    Issues several commands to set up directories/files/permissions
  generate-widget-html          Generate HTML templates for all widgets
  build-notes-widget            Build the React notes widget
  restart-daemon                Restart the AoT daemon
  setup-virtualenv              Create a Python virtual environment
  setup-virtualenv-full         Create a Python virtual environment and install dependencies
  ssl-certs-generate            Generate SSL certificates for the web user interface
  ssl-certs-regenerate          Regenerate SSL certificates
  stamp-alembic                 Stamp aot.db alembic version without running DDL (fresh installs)
  uninstall-apt-pip             Uninstall the apt version of pip
  update-alembic                Use alembic to upgrade the aot.db settings database
  update-alembic-post           Execute script following all alembic upgrades
  update-apt                    Update apt sources
  update-dependencies           Check for updates to dependencies and update
  install-bcm2835               Install bcm2835
  install-wiringpi              Install wiringpi
  install-pigpiod               Install pigpiod
  uninstall-pigpiod             Uninstall pigpiod
  disable-pigpiod               Disable pigpiod
  enable-pigpiod-low            Enable pigpiod with 1 ms sample rate
  enable-pigpiod-high           Enable pigpiod with 5 ms sample rate
  enable-pigpiod-disabled       Create empty service to indicate pigpiod is disabled
  uninstall                     Disable AoT services (frontend/backend)
  update-pigpiod                Update to latest version of pigpiod service file
  update-influxdb-1             Update influxdb 1.x to the latest version
  update-influxdb-2             Update influxdb 2.x to the latest version
  update-influxdb-1-db-user     Create the influxdb 1.x database and user
  update-influxdb-2-db-user     Create the influxdb 2.x database and user
  update-logrotate              Install logrotate script
  update-aot-service-disable Disable the AoT daemon startup script
  update-aot-service-enable  Enable the AoT daemon startup script
  update-aot-startup-script  Update the AoT daemon startup script
  install-aotmcp             Install and enable the AoT MCP Server service
  update-aotmcp-service-enable  Enable and start the AoT MCP Server service
  update-aotmcp-service-disable Disable and stop the AoT MCP Server service
  restart-aotmcp                Restart the AoT MCP Server service if enabled (run on every upgrade)
  update-packages               Ensure required apt packages are installed/up-to-date
  update-permissions            Set permissions for AoT directories/files
  update-pip3                   Update pip
  update-pip3-packages          Update required pip packages
  update-swap-size              Ensure swap size is sufficiently large (512 MB)
  upgrade-aot                Upgrade AoT to latest compatible release and preserve database and virtualenv
  upgrade-release-major {ver}   Upgrade AoT to a major version release {ver} and preserve database and virtualenv
  upgrade-release-wipe {ver}    Upgrade AoT to a major version release {ver} and wipe database and virtualenv
  upgrade-master                Upgrade AoT to the main branch at https://github.com/AoT-inc/AoT
  upgrade-post                  Execute post-upgrade script
  web-server-connect            Attempt to connect to the web server
  web-server-restart            Restart the web server
  web-server-disable            Disable the web server service
  web-server-enable             Enable the web server service
  web-server-update             Update the web server configuration files
  reset-influxdb-config         Reset InfluxDB configuration in SQLite to defaults

Docker-specific Commands:
  docker-update-pip             Update pip
  docker-update-pip-packages    Update required pip packages
  install-docker-ce-cli         Install Docker Client
"

case "${1:-''}" in
    'backup-create')
        /bin/bash "${AOT_PATH}"/aot/scripts/aot_backup_create.sh
    ;;
    'backup-restore')
        /bin/bash "${AOT_PATH}"/aot/scripts/aot_backup_restore.sh "${2}"
    ;;
    'compile-aot-wrapper')
        printf "\n#### Compiling aot_wrapper\n"
        gcc "${AOT_PATH}"/aot/scripts/aot_wrapper.c -o "${AOT_PATH}"/aot/scripts/aot_wrapper
        chown root:${AOT_USER} "${AOT_PATH}"/aot/scripts/aot_wrapper
        chmod 4770 "${AOT_PATH}"/aot/scripts/aot_wrapper
    ;;
    'compile-translations')
        printf "\n#### Compiling Translations\n"
        cd "${AOT_PATH}"/aot || return
        # Hybrid Optimization: Use local venv if AOT_LOCAL_DIR is set
        PYBABEL_BIN="${AOT_PATH}/env/bin/pybabel"
        [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/pybabel" ] && PYBABEL_BIN="${AOT_LOCAL_DIR}/env/bin/pybabel"
        # 'python -m pybabel' 는 항상 "No module named pybabel" 로 실패한다 -
        # 배포되는 것은 babel 패키지고, pybabel 은 그 콘솔스크립트 진입점
        # (babel.messages.frontend:main) 이지 모듈이 아니다. 스크립트를 직접
        # 불러야 한다(docker-compile-translations 와 동일 방식, 2026-08-17
        # aot-gw-001 네이티브 설치에서 매번 조용히 실패하던 것 확인 후 수정).
        "${PYBABEL_BIN}" compile -d aot_flask/translations
    ;;
    'create-files-directories')
        printf "\n#### Creating files and directories\n"
        mkdir -p /var/log/aot
        mkdir -p /var/AoT-backups
        mkdir -p /usr/local/aot

        mkdir -p "${AOT_PATH}"/install
        mkdir -p "${AOT_PATH}"/aot
        mkdir -p "${AOT_PATH}"/aot/databases
        mkdir -p "${AOT_PATH}"/aot/databases/kma
        mkdir -p "${AOT_PATH}"/note_attachments
        mkdir -p "${AOT_PATH}"/aot/scripts
        mkdir -p "${AOT_PATH}"/aot/aot_flask/ssl_certs
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/js/user_js
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/css/user_css
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/fonts/user_fonts

        if [[ ! -e /var/log/aot/aot.log ]]; then
            touch /var/log/aot/aot.log
        fi
        if [[ ! -e /var/log/aot/aotbackup.log ]]; then
            touch /var/log/aot/aotbackup.log
        fi
        if [[ ! -e /var/log/aot/aotkeepup.log ]]; then
            touch /var/log/aot/aotkeepup.log
        fi
        if [[ ! -e /var/log/aot/aotdependency.log ]]; then
            touch /var/log/aot/aotdependency.log
        fi
        if [[ ! -e /var/log/aot/aotimport.log ]]; then
            touch /var/log/aot/aotimport.log
        fi
        if [[ ! -e /var/log/aot/aotupgrade.log ]]; then
            touch /var/log/aot/aotupgrade.log
        fi
        if [[ ! -e /var/log/aot/aotrestore.log ]]; then
            touch /var/log/aot/aotrestore.log
        fi
        if [[ ! -e /var/log/aot/login.log ]]; then
            touch /var/log/aot/login.log
        fi

        # Create empty aot database file if it doesn't exist
        if [[ ! -e ${AOT_PATH}/aot/databases/aot.db ]]; then
            touch "${AOT_PATH}"/aot/databases/aot.db
        fi

        chown -R "${AOT_USER}:${AOT_GROUP}" /var/log/aot /var/AoT-backups || true
        chown -R "${AOT_USER}:${AOT_GROUP}" "${AOT_PATH}" || true
        
    ;;
    'create-symlinks')
        printf "\n#### Creating symlinks to AoT executables\n"
        ln -sfn "${AOT_PATH}" /var/aot-root
        ln -sfn "${AOT_PATH}"/aot/aot_daemon.py /usr/bin/aot-daemon
        ln -sfn "${AOT_PATH}"/aot/aot_client.py /usr/bin/aot-client
        ln -sfn "${AOT_PATH}"/aot/scripts/upgrade_commands.sh /usr/bin/aot-commands
        ln -sfn "${AOT_PATH}"/aot/scripts/aot_backup_create.sh /usr/bin/aot-backup
        ln -sfn "${AOT_PATH}"/aot/scripts/aot_backup_restore.sh /usr/bin/aot-restore
        ln -sfn "${AOT_PATH}"/aot/scripts/aot_wrapper /usr/bin/aot-wrapper
        # Hybrid Optimization: Link to local venv if AOT_LOCAL_DIR is set
        PYTHON_BIN="${AOT_PATH}/env/bin/python"
        PIP_BIN="${AOT_PATH}/env/bin/pip3"
        if [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/python3" ]; then
            PYTHON_BIN="${AOT_LOCAL_DIR}/env/bin/python3"
            PIP_BIN="${AOT_LOCAL_DIR}/env/bin/pip3"
        fi
        ln -sfn "${PIP_BIN}" /usr/bin/aot-pip
        ln -sfn "${PYTHON_BIN}" /usr/bin/aot-python
    ;;
    'create-user')
        printf "\n#### Creating/ensuring ${AOT_USER} service user\n"
        if ! id -u "${AOT_USER}" >/dev/null 2>&1; then
            # system user with home; no interactive shell
            useradd --system --create-home --shell /usr/sbin/nologin "${AOT_USER}"
        fi

        for g in adm dialout i2c kmem video; do
            adduser "${AOT_USER}" "$g" 2>/dev/null || true
        done
        if getent group gpio >/dev/null 2>&1; then
            adduser "${AOT_USER}" gpio 2>/dev/null || true
        fi

        # Do NOT mix current $USER with the service account (avoid cross-ownership)
    ;;
    'generate-widget-html')
        printf "\n#### Generating widget HTML files\n"
        # Hybrid Optimization: Use local venv if AOT_LOCAL_DIR is set
        PYTHON_BIN="${AOT_PATH}/env/bin/python"
        [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/python3" ] && PYTHON_BIN="${AOT_LOCAL_DIR}/env/bin/python3"
        "${PYTHON_BIN}" "${AOT_PATH}"/aot/utils/widget_generate_html.py
    ;;
    'build-notes-widget')
        printf "\n#### Building React Notes Widget\n"
        # Ensure npm and node are available
        if ! command -v npm &> /dev/null; then
            printf "#### npm not found. Skipping build.\n"
        else
            cd "${AOT_PATH}"/aot/aot_flask/static/apps/notes-widget || return
            printf "#### Installing node dependencies...\n"
            rm -rf node_modules package-lock.json
            "${AOT_TASKSET_PREFIX[@]}" npm install --no-audit --no-fund
            printf "#### Building bundle...\n"
            "${AOT_TASKSET_PREFIX[@]}" npm run build
            # Correct permissions if needed
            chown -R "${AOT_USER}:${AOT_GROUP}" dist/ 2>/dev/null || true
            chown -R "${AOT_USER}:${AOT_GROUP}" ../../js/notes/ 2>/dev/null || true
        fi
    ;;
    'initialize')
        printf "\n#### Running initialization\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh create-user
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh compile-aot-wrapper
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh create-symlinks
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh create-files-directories
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-permissions
        systemctl daemon-reload
    ;;
    'restart-daemon')
        printf "\n#### Restarting the AoT daemon\n"
        service aot restart
    ;;
    'setup-virtualenv')
        printf "\n#### Checking Python 3 virtual environment\n"
        if [[ ! -e ${AOT_PATH}/env/bin/python ]]; then
            printf "#### Creating virtual environment at ${AOT_PATH}/env\n"
            rm -rf "${AOT_PATH}"/env
            python3 -m venv "${AOT_PATH}"/env
        fi
    ;;
    'setup-virtualenv-full')
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh setup-virtualenv
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-pip3
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-pip3-packages
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-dependencies
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-permissions
    ;;
    'ssl-certs-generate')
        printf "\n#### Generating SSL certificates at %s/aot/aot_flask/ssl_certs (replace with your own if desired)\n" "${AOT_PATH}"
        mkdir -p "${AOT_PATH}"/aot/aot_flask/ssl_certs
        cd "${AOT_PATH}"/aot/aot_flask/ssl_certs/ || return
        rm -f ./*.pem ./*.csr ./*.crt ./*.key

        openssl genrsa -out server.pass.key 4096
        openssl rsa -in server.pass.key -out server.key
        rm -f server.pass.key
        openssl req -new -key server.key -out server.csr \
            -subj "/O=aot/OU=aot/CN=aot"
        openssl x509 -req \
            -days 3653 \
            -in server.csr \
            -signkey server.key \
            -out server.crt
    ;;
    'ssl-certs-regenerate')
        printf "\n#### Regenerating SSL certificates at %s/aot/aot_flask/ssl_certs\n" "${AOT_PATH}"
        rm -rf "${AOT_PATH}"/aot/aot_flask/ssl_certs/*.pem
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh ssl-certs-generate
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh initialize
        sudo service nginx restart
        sudo service aotflask restart
    ;;
    'uninstall-apt-pip')
        printf "\n#### Uninstalling apt version of pip (if installed)\n"
        apt purge -y python-pip
    ;;
    'update-alembic')
        printf "\n#### Upgrading AoT database with alembic (if needed)\n"
        cd "${AOT_PATH}"/alembic_db || return
        # Resolve alembic binary: prefer venv bin, fall back to PATH
        ALEMBIC_BIN="${AOT_PATH}/env/bin/alembic"
        [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/alembic" ] && ALEMBIC_BIN="${AOT_LOCAL_DIR}/env/bin/alembic"
        [ ! -f "${ALEMBIC_BIN}" ] && ALEMBIC_BIN="$(command -v alembic 2>/dev/null || true)"
        if [ -z "${ALEMBIC_BIN}" ]; then
            printf "ERROR: alembic binary not found\n"
            exit 1
        fi
        # 목표 리비전을 인자로 받는다 (기본값 head — 기존 호출 호환).
        # 'head' 를 쓸 수 없는 이유: 26.06.0 스키마 재베이스라인에서 p6_00 이
        # down_revision=None 으로 새 계보를 시작했기 때문에, 폐기된 구 계보의
        # 마지막 리비전(p5_52)이 영구적으로 두 번째 head 로 남아 있다. 그 상태에서
        # 'upgrade head' 는 "Multiple head revisions are present" 로 실패하므로
        # 신규 마이그레이션을 추가하는 순간 기동 시 업그레이드가 깨진다.
        # 호출자(alembic_upgrade_db)가 ALEMBIC_VERSION 을 넘겨 목표를 특정한다.
        "${ALEMBIC_BIN}" upgrade "${2:-head}"
    ;;
    'stamp-alembic')
        printf "\n#### Stamping AoT database alembic version (no DDL)\n"
        cd "${AOT_PATH}"/alembic_db || return
        # Resolve alembic binary: prefer venv bin, fall back to PATH
        ALEMBIC_BIN="${AOT_PATH}/env/bin/alembic"
        [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/alembic" ] && ALEMBIC_BIN="${AOT_LOCAL_DIR}/env/bin/alembic"
        [ ! -f "${ALEMBIC_BIN}" ] && ALEMBIC_BIN="$(command -v alembic 2>/dev/null || true)"
        if [ -z "${ALEMBIC_BIN}" ]; then
            printf "ERROR: alembic binary not found\n"
            exit 1
        fi
        # 신규 설치 전용. db.create_all() 이 현재 모델 기준 최종 스키마를 이미
        # 만든 뒤 호출된다 — 'upgrade' 로 전체 리비전을 재생하면 그 테이블들과
        # 부딪혀 "already exists" 로 실패한다(alembic_upgrade_db() 참조). 그래서
        # DDL 을 다시 실행하지 않고 버전 포인터만 목표로 찍는다.
        "${ALEMBIC_BIN}" stamp "${2:-head}"
    ;;
    'update-alembic-post')
        printf "\n#### Executing post-alembic script\n"
        "${AOT_PATH}"/env/bin/python "${AOT_PATH}"/alembic_db/alembic_post.py
    ;;
    'update-apt')
        printf "\n#### Updating apt repositories\n"
        apt update -y
    ;;
    'update-dependencies')
        printf "\n#### Checking for updates to dependencies\n"
        "${AOT_PATH}"/env/bin/python "${AOT_PATH}"/aot/utils/update_dependencies.py
    ;;
    'reset-influxdb-config')
        printf "\n#### Resetting InfluxDB configuration in SQLite to defaults\n"
        # Ensure we use the virtualenv python
        "${AOT_PATH}"/env/bin/python "${AOT_PATH}"/aot/scripts/reset_influxdb_config.py
    ;;
    'install-bcm2835')
        printf "\n#### Installing bcm2835\n"
        cd "${AOT_PATH}"/install || return
        apt install -y automake libtool
        wget ${MCB2835_URL} -O bcm2835.tar.gz
        mkdir bcm2835
        tar xzf bcm2835.tar.gz -C bcm2835 --strip-components=1
        cd bcm2835 || return
        autoreconf -vfi
        ./configure
        make
        sudo make check
        sudo make install
        cd "${AOT_PATH}"/install || return
        rm -rf ./bcm2835
    ;;
    'install-wiringpi')
        if [[ ${MACHINE_TYPE} == 'armhf' ]]; then
            wget ${WIRINGPI_URL_ARMHF} -O wiringpi-latest.deb
            dpkg -i wiringpi-latest.deb
            rm -rf wiringpi-latest.deb
        elif [[ ${MACHINE_TYPE} == 'arm64' ]]; then
            wget ${WIRINGPI_URL_ARM64} -O wiringpi-latest.deb
            dpkg -i wiringpi-latest.deb
            rm -rf wiringpi-latest.deb
        else
            printf "\n#### WiringPi not supported on this architecture, skipping.\n"
        fi
    ;;
    'build-pigpiod')
        apt install -y python3-pigpio
        cd "${AOT_PATH}"/install || return
        # wget --quiet -P "${AOT_PATH}"/install abyz.co.uk/rpi/pigpio/pigpio.zip
        wget ${PIGPIO_URL} -O pigpio.tar.gz
        mkdir PIGPIO
        tar xzf pigpio.tar.gz -C PIGPIO --strip-components=1
        cd "${AOT_PATH}"/install/PIGPIO || return
        make -j4
        make install
        cd "${AOT_PATH}"/install || return
        rm -rf ./PIGPIO
        rm -rf pigpio.tar.gz
    ;;
    'install-pigpiod')
        printf "\n#### Installing pigpiod\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh build-pigpiod
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh disable-pigpiod
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh enable-pigpiod-high
        mkdir -p /opt/AoT
        touch /opt/AoT/pigpio_installed
    ;;
    'uninstall-pigpiod')
        printf "\n#### Uninstalling pigpiod\n"
        apt remove -y python3-pigpio
        apt install -y jq
        cd "${AOT_PATH}"/install || return
        # wget --quiet -P "${AOT_PATH}"/install abyz.co.uk/rpi/pigpio/pigpio.zip
        wget ${PIGPIO_URL} -O pigpio.tar.gz
        mkdir PIGPIO
        tar xzf pigpio.tar.gz -C PIGPIO --strip-components=1
        cd "${AOT_PATH}"/install/PIGPIO || return
        make uninstall
        cd "${AOT_PATH}"/install || return
        rm -rf ./PIGPIO
        rm -rf pigpio.tar.gz
        touch /etc/systemd/system/pigpiod_uninstalled.service
        rm -f /opt/AoT/pigpio_installed
    ;;
    'disable-pigpiod')
        printf "\n#### Disabling installed pigpiod startup script\n"
        service pigpiod stop
        systemctl disable pigpiod.service
        rm -rf /etc/systemd/system/pigpiod.service
        systemctl disable pigpiod_low.service
        rm -rf /etc/systemd/system/pigpiod_low.service
        systemctl disable pigpiod_high.service
        rm -rf /etc/systemd/system/pigpiod_high.service
        rm -rf /etc/systemd/system/pigpiod_disabled.service
        rm -rf /etc/systemd/system/pigpiod_uninstalled.service
    ;;
    'enable-pigpiod-low')
        printf "\n#### Enabling pigpiod startup script (1 ms sample rate)\n"
        systemctl enable "${AOT_PATH}"/install/pigpiod_low.service
        service pigpiod restart
    ;;
    'enable-pigpiod-high')
        printf "\n#### Enabling pigpiod startup script (5 ms sample rate)\n"
        systemctl enable "${AOT_PATH}"/install/pigpiod_high.service
        service pigpiod restart
    ;;
    'enable-pigpiod-disabled')
        printf "\n#### pigpiod has been disabled. It can be enabled in the web UI configuration\n"
        touch /etc/systemd/system/pigpiod_disabled.service
    ;;
    'uninstall')
        printf "\n#### Uninstalling: Stopping and disabling AoT services (frontend/backend)\n"
        service aotflask stop
        service aot stop
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh web-server-disable
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-aot-service-disable
    ;;
    'update-pigpiod')
        printf "\n#### Checking which pigpiod startup script is being used\n"
        GPIOD_SAMPLE_RATE=99
        if [[ -e /etc/systemd/system/pigpiod_low.service ]]; then
            GPIOD_SAMPLE_RATE=1
        elif [[ -e /etc/systemd/system/pigpiod_high.service ]]; then
            GPIOD_SAMPLE_RATE=5
        elif [[ -e /etc/systemd/system/pigpiod_disabled.service ]]; then
            GPIOD_SAMPLE_RATE=100
        fi

        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh disable-pigpiod

        if [[ "$GPIOD_SAMPLE_RATE" -eq "1" ]]; then
            /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh enable-pigpiod-low
        elif [[ "$GPIOD_SAMPLE_RATE" -eq "5" ]]; then
            /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh enable-pigpiod-high
        elif [[ "$GPIOD_SAMPLE_RATE" -eq "100" ]]; then
            /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh enable-pigpiod-disabled
        else
            printf "#### Could not determine pigpiod sample rate. Setting up pigpiod with 1 ms sample rate\n"
            /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh enable-pigpiod-low
        fi
    ;;
    'update-influxdb-1')
        printf "\n#### Ensuring compatible version of influxdb 1.x is installed ####\n"
        INSTALL_ADDRESS="https://dl.influxdata.com/influxdb/releases/"
        INSTALL_FILE="influxdb_${INFLUXDB1_VERSION}_${MACHINE_TYPE}.deb"
        CORRECT_VERSION="${INFLUXDB1_VERSION}-1"
        CURRENT_VERSION=$(apt-cache policy influxdb | grep 'Installed' | awk '{print $2}')

        if [[ "${CURRENT_VERSION}" != "${CORRECT_VERSION}" ]]; then
            printf "#### Incorrect InfluxDB version (v${CURRENT_VERSION}) installed. Should be v${CORRECT_VERSION}\n"

            printf "#### Stopping influxdb 2.x (if installed)...\n"
            service influxd stop

            printf "#### Uninstalling influxdb 2.x (if installed)...\n"
            DEBIAN_FRONTEND=noninteractive apt remove -y influxdb2 influxdb2-cli

            printf "#### Installing InfluxDB v${CORRECT_VERSION}...\n"

            wget --quiet "${INSTALL_ADDRESS}${INSTALL_FILE}"
            dpkg -i "${INSTALL_FILE}"
            rm -rf "${INSTALL_FILE}"

            service influxdb restart
        else
            printf "Correct version of InfluxDB currently installed\n"
        fi

        if [[ $(grep "# flux-enabled = true" /etc/influxdb/influxdb.conf) || $(grep "flux-enabled = false" /etc/influxdb/influxdb.conf) ]]; then   
            printf "#### Flux found to not be enabled. Enabling and restarting InfluxDB.\n"
            sed -i 's/.*flux-enabled.*/flux-enabled = true/' /etc/influxdb/influxdb.conf
            service influxdb restart
        else
            printf "Flux is already enabled.\n"
        fi
    ;;
    'update-influxdb-2')
        printf "\n#### Ensuring compatible version of influxdb 2.x is installed ####\n"
        if [[ ${UNAME_TYPE} == 'x86_64' || ${MACHINE_TYPE} == 'arm64' ]]; then
            INSTALL_ADDRESS="https://dl.influxdata.com/influxdb/releases/"
            AMD64_INSTALL_FILE="influxdb2_2.7.8-1_amd64.deb"
            ARM64_INSTALL_FILE="influxdb2_2.7.8-1_arm64.deb"
            CORRECT_VERSION_INSTALL="2.7.8-1"
            AMD64_CLIENT_FILE="influxdb2-client-2.7.5-amd64.deb"
            ARM64_CLIENT_FILE="influxdb2-client-2.7.5-arm64.deb"
            CORRECT_VERSION_CLI="2.7.5-1"

            if [[ ${UNAME_TYPE} == 'x86_64' ]]; then
                printf "#### Detected x86_64 architecture\n"
                INSTALL_FILE=$AMD64_INSTALL_FILE
                CLIENT_FILE=$AMD64_CLIENT_FILE
            elif [[ ${MACHINE_TYPE} == 'arm64' ]]; then
                printf "#### Detected arm64 architecture\n"
                INSTALL_FILE=$ARM64_INSTALL_FILE
                CLIENT_FILE=$ARM64_CLIENT_FILE
            fi

            printf "#### Influxdb server file location: ${INSTALL_ADDRESS}${INSTALL_FILE}\n"

            CURRENT_VERSION=$(apt-cache policy influxdb2 | grep 'Installed' | awk '{print $2}')

            if [[ "${CURRENT_VERSION}" != "${CORRECT_VERSION_INSTALL}" ]]; then
                printf "#### Incorrect InfluxDB version (v${CURRENT_VERSION}) installed. Should be v${CORRECT_VERSION_INSTALL}\n"

                printf "#### Stopping influxdb 1.x (if installed)...\n"
                service influxdb stop

                printf "#### Uninstalling influxdb 1.x (if installed)...\n"
                DEBIAN_FRONTEND=noninteractive apt remove -y influxdb

                printf "#### Installing InfluxDB v${CORRECT_VERSION_INSTALL}...\n"

                wget --quiet "${INSTALL_ADDRESS}${INSTALL_FILE}"
                dpkg -i "${INSTALL_FILE}"
                rm -rf "${INSTALL_FILE}"

                service influxd restart
            else
                printf "Correct version of InfluxDB currently installed (v${CORRECT_VERSION_INSTALL}).\n"
            fi

            printf "#### Influxdb client file location: ${INSTALL_ADDRESS}${CLIENT_FILE}\n"

            CURRENT_VERSION=$(apt-cache policy influxdb2-cli | grep 'Installed' | awk '{print $2}')

            if [[ "${CURRENT_VERSION}" != "${CORRECT_VERSION_CLI}" ]]; then
                printf "#### Incorrect InfluxDB-Client version (v${CURRENT_VERSION}) installed. Should be v${CORRECT_VERSION_CLI}\n"

                printf "#### Installing InfluxDB-Client v${CORRECT_VERSION_CLI}...\n"

                wget --quiet "${INSTALL_ADDRESS}${CLIENT_FILE}"
                dpkg -i "${CLIENT_FILE}"
                rm -rf "${CLIENT_FILE}"

                service influxd restart
            else
                printf "Correct version of InfluxDB-Client currently installed (v${CORRECT_VERSION_CLI}).\n"
            fi
        else
            printf "ERROR: Could not detect 64-bit architecture (x86_64/arm64) to install Influxdb 2.x (found ${UNAME_TYPE}/${MACHINE_TYPE}).\n"
        fi
    ;;
    'update-influxdb-1-db-user')
        printf "\n#### Creating InfluxDB 1.x database and user\n"
        # Attempt to connect to influxdb 10 times, sleeping 60 seconds every fail
        for _ in {1..10}; do
            # Check if influxdb has successfully started and be connected to
            printf "#### Attempting to connect...\n" &&
            curl -sL -I localhost:8086/ping > /dev/null &&
            printf "#### Attempting to create database...\n" &&
            influx -execute "CREATE DATABASE aot_db" &&
            printf "#### Attempting to set up user...\n" &&
            influx -database aot_db -execute "CREATE USER aot WITH PASSWORD 'mmdu77sj3nIoiajjs'" &&
            printf "#### Influxdb database and user successfully created\n" &&
            break ||
            # Else wait 60 seconds if the influxd port is not accepting connections
            # Everything below will begin executing if an error occurs before the break
            printf "#### Could not connect to Influxdb. Waiting 60 seconds then trying again...\n" &&
            sleep 60
        done
    ;;
    'update-influxdb-2-db-user')
        printf "\n#### Configuring InfluxDB 2.x (Idempotent)\n"
        
        # Check if influx command exists
        if ! command -v influx &> /dev/null; then
            printf "#### Error: 'influx' command not found. Cannot configure InfluxDB.\n"
            exit 1
        fi

        # Wait for InfluxDB to start
        printf "#### Waiting for InfluxDB to start...\n"
        for _ in {1..10}; do
            if curl -sL -I localhost:8086/ping >/dev/null; then
                break
            fi
            sleep 5
        done

        # 1. Try initial setup (will fail if already set up, which is fine)
        if influx ping >/dev/null 2>&1 && influx org list >/dev/null 2>&1; then
            printf "#### InfluxDB v2.x already initialized.\n"
        else
            printf "#### Attempting to initialize InfluxDB v2.x...\n"
            influx setup \
                   --org aot \
                   --bucket aot_db \
                   --username aot \
                   --password mmdu77sj3nIoiajjs \
                   --token mmdu77sj3nIoiajjs \
                   --force || printf "#### Setup skipped (likely already set up).\n"
        fi

        # 2. Ensure Org 'aot' exists
        # jq로 파싱한다 - influx CLI가 pretty-print("name": "aot", 콜론 뒤 공백)로
        # 내보내는데 예전엔 grep '"name":"aot"'(공백 없음)라 절대 매치되지 않았다.
        # 그 결과 매번 "이미 있음"을 "없음"으로 오판해 influx setup 직후에도 org
        # create를 다시 시도해 "already exists" 에러가 항상 찍혔다(기능은 무해).
        if influx org list --json | jq -e '.[] | select(.name=="aot")' >/dev/null 2>&1; then
            printf "#### Organization 'aot' already exists.\n"
        else
            printf "#### Creating Organization 'aot'...\n"
            influx org create -n aot || printf "#### Warning: Could not create Org 'aot' (check permissions/token).\n"
        fi

        # 3. Ensure Bucket 'aot_db' exists
        if influx bucket list --org aot --json | jq -e '.[] | select(.name=="aot_db")' >/dev/null 2>&1; then
            printf "#### Bucket 'aot_db' already exists.\n"
        else
            printf "#### Creating Bucket 'aot_db'...\n"
            influx bucket create -n aot_db -o aot -r 0 || printf "#### Warning: Could not create Bucket 'aot_db' (check permissions/token).\n"
        fi

        # 4. Reset SQLite config to match these defaults (Fix for reinstall scenario)
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh reset-influxdb-config

        printf "#### InfluxDB 2.x configuration check complete.\n"
    ;;
    'fix-influx-perms')
        printf "\n#### Fixing InfluxDB directories ownership to match service account\n"
        INFLUXD_USER="$(systemctl show -p User --value influxdb)"; [ -z "$INFLUXD_USER" ] && INFLUXD_USER=influxdb
        for d in /var/lib/influxdb /var/lib/influxdb2 /etc/influxdb /etc/influxdb2 /var/log/influxdb; do
            [ -d "$d" ] && chown -R "$INFLUXD_USER:$INFLUXD_USER" "$d"
        done
    ;;
    'recreate-influxdb-1-db')
        printf "\n#### Recreating InfluxDB 1.x database (deletes all measurement data!)\n"
        # Attempt to connect to influxdb 10 times, sleeping 60 seconds every fail
        for _ in {1..10}; do
            # Check if influxdb has successfully started and be connected to
            printf "#### Attempting to connect...\n" &&
            curl -sL -I localhost:8086/ping > /dev/null &&
            printf "#### Attempting to recreate database...\n" &&
            influx -execute "DROP DATABASE aot_db" &&
            influx -execute "CREATE DATABASE aot_db" &&
            printf "#### Influxdb database successfully recreated\n" &&
            break ||
            # Else wait 60 seconds if the influxd port is not accepting connections
            # Everything below will begin executing if an error occurs before the break
            printf "#### Could not connect to Influxdb. Waiting 60 seconds then trying again...\n" &&
            sleep 60
        done
    ;;
    'recreate-influxdb-2-db')
        printf "\n#### Recreating InfluxDB 2.x database (deletes all measurement data!)\n"
        # Attempt to connect to influxdb 10 times, sleeping 60 seconds every fail
        for _ in {1..10}; do
            # Check if influxdb has successfully started and be connected to
            printf "#### Attempting to connect...\n" &&
            curl -sL -I localhost:8086/ping > /dev/null &&
            printf "#### Attempting to recreate database...\n" &&
            influx bucket delete -n aot_db -o aot &&
            influx bucket create -n aot_db -o aot &&
            printf "#### Influxdb database successfully recreated\n" &&
            break ||
            # Else wait 60 seconds if the influxd port is not accepting connections
            # Everything below will begin executing if an error occurs before the break
            printf "#### Could not connect to Influxdb. Waiting 60 seconds then trying again...\n" &&
            sleep 60
        done
    ;;
    'update-logrotate')
        printf "\n#### Installing logrotate scripts\n"
        if [[ -e /etc/cron.daily/logrotate ]]; then
            printf "logrotate execution moved from cron.daily to cron.hourly\n"
            mv -f /etc/cron.daily/logrotate /etc/cron.hourly/
        fi
        cp -f "${AOT_PATH}"/install/logrotate_aot /etc/logrotate.d/aot
        printf "AoT logrotate script installed\n"
    ;;
    'update-aot-service-disable')
        printf "\n#### Disabling aot startup script\n"
        systemctl disable aot.service || true
        rm -rf /etc/systemd/system/aot.service || true
    ;;
    'update-aot-service-enable')
        printf "#### Enabling aot startup script\n"
        systemctl enable "${AOT_PATH}"/install/aot.service
    ;;
    'update-aot-startup-script')
        printf "\n#### Updating aot startup script\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-aot-service-disable
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-aot-service-enable
    ;;
    'install-aotmcp')
        printf "\n#### Installing AoT MCP Server service\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-aotmcp-service-disable
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh update-aotmcp-service-enable
        printf "#### AoT MCP Server installed and enabled on port 5700\n"
    ;;
    'update-aotmcp-service-enable')
        printf "#### Enabling AoT MCP Server startup script\n"
        systemctl enable "${AOT_PATH}"/install/aotmcp.service
        systemctl start aotmcp || true
    ;;
    'update-aotmcp-service-disable')
        printf "\n#### Disabling AoT MCP Server startup script\n"
        systemctl stop aotmcp || true
        systemctl disable aotmcp.service || true
        rm -rf /etc/systemd/system/aotmcp.service || true
        systemctl daemon-reload || true
    ;;
    'restart-aotmcp')
        # install-aotmcp only runs once, at initial setup (setup.sh) — a plain
        # upgrade (git pull + restart-daemon + web-server-restart) never touched
        # this service, so it kept running whatever code was on disk when it was
        # first installed, potentially for months. Call this alongside
        # restart-daemon/web-server-restart on every upgrade, same as aot/aotflask.
        printf "\n#### Restarting AoT MCP Server\n"
        if systemctl is-enabled --quiet aotmcp 2>/dev/null; then
            systemctl restart aotmcp || true
        fi
    ;;
    'update-packages')
        printf "\n#### Installing prerequisite apt packages and update pip\n"
        apt remove -y apache2 || true
        apt install -y ${APT_PKGS}
        
        if [[ ! -f /etc/nginx/nginx.conf ]]; then
            printf "#### WARNING: /etc/nginx/nginx.conf missing. Reinstalling nginx-common to restore defaults...\n"
            apt-get install -o Dpkg::Options::='--force-confmiss' --reinstall -y nginx-common
        fi
        
        # [Fix] Node.js 20 Installation (Separate from main apt packages to prevent conflicts)
        if ! command -v node &> /dev/null || [[ $(node -v | cut -d'.' -f1) != "v20" ]]; then
            printf "#### Installing Node.js 20 from Nodesource...\n"
            curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
            apt-get install -y nodejs
        else
            printf "#### Node.js 20 already installed ($(node -v))\n"
        fi

        apt clean
    ;;
    'update-permissions')
        chown -LR "${AOT_USER}:${AOT_GROUP}" "${AOT_PATH}"
        chown -R  "${AOT_USER}:${AOT_GROUP}" /var/log/aot
        chown -R  "${AOT_USER}:${AOT_GROUP}" /var/AoT-backups
        chown -R  "${AOT_USER}:${AOT_GROUP}" /opt/AoT

        find "${AOT_PATH}" -type d -exec chmod u+wx,g+wx {} +
        # g+r 없이 g+w 만 추가하면, 소스 트리에 이미 그룹-읽기가 빠진 파일(예:
        # 특이한 체크아웃/umask 로 700 근처 권한이 남은 파일)은 이 단계를 거치고도
        # 계속 그룹에서 못 읽는다 - nginx 워커(www-data, aot 그룹)가 정적 파일을
        # 403 으로 못 읽는 사고로 이어진다(2026-08-17 aot-gw-001, logo.svg 등
        # nav_bar 브랜드 아이콘 + 로그인 페이지 로고가 깨져 있던 원인).
        find "${AOT_PATH}" -type f -exec chmod u+w,g+rw,o+r {} +
        chmod 770 /opt/AoT  # Exclude other users from viewing files

        chown root:"${AOT_USER}" "${AOT_PATH}"/aot/scripts/aot_wrapper
        chmod 4770 "${AOT_PATH}"/aot/scripts/aot_wrapper
    ;;
    'update-pip3')
        printf "\n#### Updating pip\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh setup-virtualenv
        if [[ ! -d ${AOT_PATH}/env ]]; then
            printf "\n## Error: Virtualenv doesn't exist. Create with %s setup-virtualenv\n" "${0}"
        else
            "${AOT_PATH}"/env/bin/python -m pip install --upgrade pip
        fi
    ;;
    'update-pip3-packages')
        printf "\n#### Installing pip requirements\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh setup-virtualenv
        if [[ ! -d ${AOT_PATH}/env ]]; then
            printf "\n## Error: Virtualenv doesn't exist. Create with %s setup-virtualenv\n" "${0}"
        else
            "${AOT_TASKSET_PREFIX[@]}" "${AOT_PATH}"/env/bin/python -m pip install --upgrade -r "${AOT_PATH}"/install/requirements.txt
            if [[ -f "${AOT_PATH}"/install/requirements-testing.txt ]]; then
                "${AOT_TASKSET_PREFIX[@]}" "${AOT_PATH}"/env/bin/python -m pip install --upgrade -r "${AOT_PATH}"/install/requirements-testing.txt
            fi
        fi
    ;;
    'pip-clear-cache')
      "${AOT_PATH}"/env/bin/python -m pip cache remove *
    ;;
    'update-swap-size')
        printf "\n#### Checking if swap size is 100 MB and needs to be changed to 512 MB\n"
        if grep -q -s "CONF_SWAPSIZE=100" "/etc/dphys-swapfile"; then
            printf "#### Swap currently set to 100 MB. Changing to 512 MB and restarting\n"
            sed -i 's/CONF_SWAPSIZE=100/CONF_SWAPSIZE=512/g' /etc/dphys-swapfile
            /etc/init.d/dphys-swapfile stop
            /etc/init.d/dphys-swapfile start
        else
            printf "#### Swap not currently set to 100 MB. Not changing.\n"
        fi
    ;;
    'upgrade-aot')
        if [ -z "${AOT_MAJOR_VERSION}" ]; then
            printf "\n#### ERROR: could not read AOT_VERSION from %s\n" "${_AOT_VERSION_FILE}"
            printf "Cannot determine which major release line to upgrade to.\n"
            printf "Pass it explicitly instead: %s upgrade-release-major <major>\n" "${0}"
            exit 1
        fi
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_download.sh upgrade-release-major "${AOT_MAJOR_VERSION}"
    ;;
    'upgrade-release-major')
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_download.sh upgrade-release-major "${2}"
    ;;
    'upgrade-release-wipe')
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_download.sh upgrade-release-wipe "${2}"
    ;;
    'upgrade-master')
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_download.sh force-upgrade-master
    ;;
    'upgrade-post')
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_post.sh
    ;;
    'web-server-connect')
        printf "\n#### Connecting to http://localhost (creates AoT database if it doesn't exist)\n"
        
        # First, check if nginx is running
        if ! systemctl is-active --quiet nginx; then
            printf "#### WARNING: nginx is not running. Attempting to start...\n"
            systemctl start nginx || {
                printf "#### ERROR: Failed to start nginx. Diagnostics:\n"
                nginx -t || true
                systemctl status nginx --no-pager -l || true
            }
            sleep 3
        fi
        
        # Check if aotflask is running
        if ! systemctl is-active --quiet aotflask; then
            printf "#### WARNING: aotflask is not running. Attempting to start...\n"
            systemctl start aotflask || {
                printf "#### ERROR: Failed to start aotflask. Diagnostics:\n"
                systemctl status aotflask --no-pager -l || true
            }
            sleep 3
        fi
        
        # Attempt to connect to localhost 10 times, sleeping 60 seconds every fail
        for i in {1..10}; do
            # Try curl first
            if curl -sf --max-time 10 http://localhost/ > /dev/null 2>&1; then
                printf "#### Successfully connected to http://localhost\n"
                break
            else
                # If we're on the last attempt, provide diagnostics
                if [ $i -eq 10 ]; then
                    printf "#### ERROR: Could not connect after 10 attempts\n"
                    printf "#### Nginx status: "
                    systemctl is-active nginx || printf "NOT RUNNING\n"
                    printf "#### AoTFlask status: "
                    systemctl is-active aotflask || printf "NOT RUNNING\n"
                    printf "#### Recent Nginx errors:\n"
                    tail -n 20 /var/log/nginx/error.log 2>/dev/null || printf "Could not read /var/log/nginx/error.log\n"
                    printf "#### Recent AoTFlask logs (journalctl):\n"
                    journalctl -u aotflask -n 20 --no-pager || true
                else
                    printf "#### Could not connect to http://localhost (attempt $i/10). Waiting 60 seconds...\n"
                    sleep 60
                    printf "#### Trying again...\n"
                fi
            fi
        done
    ;;
    'web-server-restart')
        printf "\n#### Restarting nginx\n"
        service nginx restart
        sleep 5
        printf "#### Reloading aotflask\n"
        service aotflask reload
        sleep 5
    ;;
    'web-server-disable')
        printf "\n#### Disabling services for fronted\n"
        systemctl disable aotflask.service || true
        rm -rf /etc/systemd/system/aotflask.service || true
    ;;
    'web-server-enable')
        printf "\n#### Enabling services for fronted\n"
        mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled /etc/nginx/conf.d
        # 이 map 은 sites-available/aot 이 참조하는 변수를 정의한다. 없으면 변수가
        # 빈 값이 되어 정적 자산에 Cache-Control 이 아예 안 붙으므로, 반드시 먼저 둔다.
        cp -f "${AOT_PATH}"/install/aotflask_static_cache.conf /etc/nginx/conf.d/aotflask_static_cache.conf
        cp -f "${AOT_PATH}"/install/aotflask_nginx.conf /etc/nginx/sites-available/aot
        rm -f /etc/nginx/sites-enabled/default
        ln -sf /etc/nginx/sites-available/aot /etc/nginx/sites-enabled/aot

        # nginx 워커(www-data)가 /opt/AoT(0770 aot:aot)를 순회할 수 있어야
        # location /static/ 이 403 없이 서빙된다. 근거는 aotflask_nginx.conf
        # 상단 주석 - 예전엔 그 주석만 있고 실제 명령이 배선돼 있지 않아
        # 화면은 뜨는데 CSS가 전혀 적용되지 않는 사고로 이어졌다.
        if getent passwd www-data >/dev/null 2>&1; then
            usermod -aG "${AOT_GROUP}" www-data 2>/dev/null || true
        fi

        systemctl enable nginx || true
        systemctl enable "${AOT_PATH}"/install/aotflask.service || true
    ;;
    'web-server-update')
        printf "\n#### Reconfiguring fronted\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh web-server-disable
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh web-server-enable
    ;;


    #
    # Docker-specific commands
    #

    'docker-create-files-directories-symlinks')
        printf "\n#### Creating files and directories\n"
        mkdir -p /var/log/aot
        mkdir -p /var/AoT-backups
        mkdir -p /usr/local/aot

        mkdir -p "${AOT_PATH}"/install
        mkdir -p "${AOT_PATH}"/aot
        # SQLite DBs live under AOT_LOCAL_DIR when set (Docker named volume),
        # otherwise under the source tree. This mirrors config.DATABASE_PATH,
        # which the app also self-creates at runtime.
        AOT_DB_DIR="${AOT_LOCAL_DIR:-${AOT_PATH}/aot}/databases"
        mkdir -p "${AOT_DB_DIR}"
        mkdir -p "${AOT_DB_DIR}"/kma
        mkdir -p "${AOT_PATH}"/note_attachments
        mkdir -p "${AOT_PATH}"/aot/scripts
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/js/user_js
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/css/user_css
        mkdir -p "${AOT_PATH}"/aot/aot_flask/static/fonts/user_fonts

        if [[ ! -e /var/log/aot/aot.log ]]; then
            touch /var/log/aot/aot.log
        fi
        if [[ ! -e /var/log/aot/aotbackup.log ]]; then
            touch /var/log/aot/aotbackup.log
        fi
        if [[ ! -e /var/log/aot/aotkeepup.log ]]; then
            touch /var/log/aot/aotkeepup.log
        fi
        if [[ ! -e /var/log/aot/aotdependency.log ]]; then
            touch /var/log/aot/aotdependency.log
        fi
        if [[ ! -e /var/log/aot/aotimport.log ]]; then
            touch /var/log/aot/aotimport.log
        fi
        if [[ ! -e /var/log/aot/aotupgrade.log ]]; then
            touch /var/log/aot/aotupgrade.log
        fi
        if [[ ! -e /var/log/aot/aotrestore.log ]]; then
            touch /var/log/aot/aotrestore.log
        fi
        if [[ ! -e /var/log/aot/login.log ]]; then
            touch /var/log/aot/login.log
        fi

        # Create empty aot database file if it doesn't exist
        if [[ ! -e "${AOT_DB_DIR}"/aot.db ]]; then
            touch "${AOT_DB_DIR}"/aot.db
        fi

        ln -sfn "${AOT_PATH}" /var/aot-root
    ;;
    'docker-compile-translations')
        printf "\n#### Compiling Translations\n"
        cd "${AOT_PATH}"/aot || exit
        "${AOT_PATH}"/env/bin/pybabel compile -d aot_flask/translations
    ;;
    'docker-update-pip')
        printf "\n#### Updating pip\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh setup-virtualenv
        if [[ ! -d ${AOT_PATH}/env ]]; then
            printf "\n## Error: Virtualenv doesn't exist. Create with %s setup-virtualenv\n" "${0}"
        else
            "${AOT_PATH}"/env/bin/python -m pip install --upgrade pip
        fi
    ;;
    'docker-update-pip-packages')
        printf "\n#### Installing pip requirements\n"
        /bin/bash "${AOT_PATH}"/aot/scripts/upgrade_commands.sh setup-virtualenv
        if [[ ! -d ${AOT_PATH}/env ]]; then
            printf "\n## Error: Virtualenv doesn't exist. Create with %s setup-virtualenv\n" "${0}"
        else
            "${AOT_TASKSET_PREFIX[@]}" "${AOT_PATH}"/env/bin/python -m pip install --no-cache-dir -r "${AOT_PATH}"/install/requirements.txt
        fi
    ;;
    'install-docker')
        printf "\n#### Installing Docker Client\n"
        apt install -y curl
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
    ;;
    *)
        printf "Error: Unrecognized command: %s\n%s" "${1}" "${HELP_OPTIONS}"
    ;;
esac