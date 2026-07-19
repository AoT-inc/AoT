#!/bin/bash
#
# detect_platform.sh - AoT 설치 대상 자동 감지
#
# 사용법: source install/detect_platform.sh
# 결과:
#   INSTALL_TARGET = raspi | debian | docker
#   INSTALL_ARCH   = armhf | arm64 | amd64
#
# 환경변수 INSTALL_TARGET 을 미리 설정하면 자동 감지를 건너뜁니다.
#

_aot_detect_target() {
    # Docker: .dockerenv 또는 cgroup 마커
    if [ -f /.dockerenv ] || grep -qE 'docker|lxc' /proc/1/cgroup 2>/dev/null; then
        echo "docker"
        return
    fi

    # Raspberry Pi: cpuinfo 또는 OS release
    if grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null || \
       [ -f /etc/rpi-issue ] || \
       grep -qi "raspbian\|raspberry" /etc/os-release 2>/dev/null; then
        echo "raspi"
        return
    fi

    # 기본값: Debian/Ubuntu
    echo "debian"
}

# 환경변수로 수동 지정 가능
if [ -z "${INSTALL_TARGET}" ]; then
    INSTALL_TARGET="$(_aot_detect_target)"
fi

# 아키텍처 정규화 (dpkg 형식: amd64 / arm64 / armhf)
if command -v dpkg >/dev/null 2>&1; then
    INSTALL_ARCH="$(dpkg --print-architecture)"
else
    case "$(uname -m)" in
        x86_64)         INSTALL_ARCH="amd64" ;;
        aarch64|arm64)  INSTALL_ARCH="arm64" ;;
        armv7l|armv6l)  INSTALL_ARCH="armhf" ;;
        *)              INSTALL_ARCH="$(uname -m)" ;;
    esac
fi

export INSTALL_TARGET
export INSTALL_ARCH

# MACHINE_TYPE / UNAME_TYPE 호환 별칭 (upgrade_commands.sh와 동일한 변수명)
export MACHINE_TYPE="${INSTALL_ARCH}"
export UNAME_TYPE="$(uname -m)"

printf "#### 설치 대상: %s | 아키텍처: %s\n" "${INSTALL_TARGET}" "${INSTALL_ARCH}"
