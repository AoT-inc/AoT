#!/bin/bash
# cleanup_aot.sh - AoT 및 관련 종속성 완전 삭제 스크립트

if [[ "$EUID" -ne 0 ]]; then
    echo "이 스크립트는 root 권한(sudo)으로 실행해야 합니다."
    exit 1
fi

echo "!!! 주의: 이 스크립트는 AoT 서비스, 모든 데이터, 로그 및 관련 설정을 완전히 삭제합니다 !!!"
read -p "계속 진행하시겠습니까? (y/N): " confirm
if [[ $confirm != [yY] ]]; then
    echo "취소되었습니다."
    exit 0
fi

AOT_PATH="/opt/AoT"

# 1. 서비스 중지 및 비활성화
echo "#### AoT 관련 서비스 중지 및 비활성화 중..."
systemctl stop aotflask aot aotmcp 2>/dev/null
systemctl disable aotflask aot aotmcp 2>/dev/null

echo "#### 관련 서비스 중지 중 (nginx, mosquitto, influxdb)..."
systemctl stop mosquitto nginx influxdb influxdb2 2>/dev/null
systemctl disable mosquitto nginx influxdb influxdb2 2>/dev/null

# 2. 서비스 파일 삭제
echo "#### systemd 서비스 파일 삭제 중..."
rm -f /etc/systemd/system/aotflask.service
rm -f /etc/systemd/system/aot.service
rm -f /etc/systemd/system/aotmcp.service
rm -f /etc/systemd/system/pigpiod.service
rm -f /etc/systemd/system/pigpiod_low.service
rm -f /etc/systemd/system/pigpiod_high.service
# GPIO 백엔드 상태에 따라 남는 빈 마커 파일(실제 유닛 아님)
rm -f /etc/systemd/system/pigpiod_disabled.service
rm -f /etc/systemd/system/pigpiod_uninstalled.service
systemctl daemon-reload

# 3. 설정 파일 삭제
echo "#### 설정 파일 삭제 중 (nginx, mosquitto, logrotate)..."
rm -f /etc/mosquitto/conf.d/aot.conf
rm -f /etc/nginx/sites-available/aot
rm -f /etc/nginx/sites-enabled/aot
rm -f /etc/nginx/conf.d/aotflask_static_cache.conf
rm -f /etc/logrotate.d/aot
# 예전 방식(apt 저장소)으로 설치된 InfluxDB의 잔여물. 현재 설치 스크립트는
# .deb 파일을 직접 받아 dpkg -i로 설치하므로 이 경로는 더 이상 생성되지
# 않지만, 오래된 설치를 정리할 때를 대비해 남겨둔다.
rm -f /etc/apt/sources.list.d/influxdata.list 2>/dev/null
rm -f /etc/apt/trusted.gpg.d/influxdata-archive_compat.gpg 2>/dev/null

echo "#### Node.js(NodeSource) apt 저장소 등록 정보 삭제 중..."
rm -f /etc/apt/sources.list.d/nodesource.list
rm -f /etc/apt/keyrings/nodesource.gpg
rm -f /usr/share/keyrings/nodesource.gpg
rm -f /etc/apt/trusted.gpg.d/nodesource.gpg

# 4. 심볼릭 링크 삭제
echo "#### /usr/bin 심볼릭 링크 삭제 중..."
rm -f /usr/bin/aot-daemon
rm -f /usr/bin/aot-client
rm -f /usr/bin/aot-commands
rm -f /usr/bin/aot-backup
rm -f /usr/bin/aot-restore
rm -f /usr/bin/aot-wrapper
rm -f /usr/bin/aot-pip
rm -f /usr/bin/aot-python
rm -f /var/aot-root

# 5. 디렉터리 삭제
echo "#### AoT 설치 경로 및 로그, 백업 디렉터리 삭제 중..."
rm -rf "$AOT_PATH"
rm -rf /var/log/aot
rm -rf /var/AoT-backups
rm -rf /var/lib/influxdb
rm -rf /var/lib/influxdb2
rm -rf /etc/influxdb
rm -rf /etc/influxdb2
rm -rf /root/.influxdbv2
rm -rf /home/*/.influxdbv2 2>/dev/null

# 6. 사용자 및 그룹 삭제
echo "#### 'aot' 계정 및 그룹 삭제 중..."
userdel -r aot 2>/dev/null
groupdel aot 2>/dev/null

# 7. 패키지 삭제
echo "#### 관련 패키지 삭제 중 (nodejs, npm, mosquitto, influxdb, nginx)..."
echo "!!! 경고: Node.js를 삭제하면 Zigbee2MQTT 등 다른 Node 기반 서비스가 중단될 수 있습니다 !!!"
# 설치되지 않은 패키지를 purge 대상에 넣어도 apt가 조용히 건너뛰므로,
# 예전 설치 방식(libatlas-base-dev, gawk)과 현재 방식(libopenblas-dev,
# liblgpio-dev, mawk 등)의 의존 패키지를 모두 나열해 둔다.
apt purge -y nodejs npm mosquitto mosquitto-clients influxdb influxdb2 influxdb-client nginx-common \
    build-essential gcc g++ jq logrotate mawk gawk pkg-config swig sqlite3 unzip \
    libatlas-base-dev libopenblas-dev liblgpio-dev \
    libffi-dev libgeos-dev libheif-dev libi2c-dev moreutils netcat-openbsd rng-tools
apt autoremove -y
apt clean

echo "#### AoT 완전 삭제가 완료되었습니다."
