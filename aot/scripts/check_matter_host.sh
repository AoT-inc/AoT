#!/bin/bash
#
#  check_matter_host.sh - Matter 컨트롤러 사이드카용 호스트 네트워크 사전 점검
#
#  docs/design/matter-controller.md §3-3 의 요구사항을 읽기 전용으로 점검하고,
#  고칠 명령을 출력한다. 시스템 상태는 절대 바꾸지 않는다(sysctl -w, nmcli
#  modify 등은 "출력"만 하고 실행하지 않는다).
#
#  사용법:
#    check_matter_host.sh [--iface <이름>] [--ble] [--json]
#
#    --ble  BLE 커미셔닝(docker-compose.matter-ble.yml)용 Bluetooth 점검을 추가한다.
#           BlueZ 데몬, 어댑터 존재, rfkill 차단, 전원, D-Bus 소켓을 읽기 전용으로
#           본다. BLE 는 선택 기능이라 어댑터가 아예 없을 때만 FAIL, 나머지는 WARN.
#
#  출력(텍스트):
#    OK|WARN|FAIL  <점검>  <상세>
#      → <고치는 명령 또는 설정>          (WARN/FAIL 일 때만)
#  출력(--json): {"check","status","detail","fix"} 객체의 배열
#
#  종료 코드:
#    0  FAIL 없음(WARN 은 통과)
#    1  FAIL 이 하나 이상
#    2  Linux 가 아니거나 인자가 잘못됨
#
#  테스트용 환경변수:
#    MATTER_CHECK_PROC_SYS  /proc/sys 대신 읽을 루트
#    MATTER_CHECK_SKIP_OS=1 Linux 검사와 외부 명령(ip, ss, docker, nmcli,
#                           커널 설정 파일, --ble 의 systemctl/pgrep/rfkill/bluetoothctl)에
#                           의존하는 점검을 모두 건너뛴다.
#    MATTER_CHECK_SYS_BLUETOOTH  --ble: /sys/class/bluetooth 대신 볼 디렉터리
#    MATTER_CHECK_DBUS_SOCKET    --ble: /run/dbus/system_bus_socket 대신 볼 경로

set -u

SYSCTL_ROOT="${MATTER_CHECK_PROC_SYS:-/proc/sys}"
SKIP_CMDS="${MATTER_CHECK_SKIP_OS:-0}"
SYS_BLUETOOTH="${MATTER_CHECK_SYS_BLUETOOTH:-/sys/class/bluetooth}"
DBUS_SOCKET="${MATTER_CHECK_DBUS_SOCKET:-/run/dbus/system_bus_socket}"

# 영속화 안내 문구(고침 힌트에 공통으로 붙인다).
PERSIST_NOTE="persist: /etc/sysctl.d/99-matter.conf, or the NetworkManager/systemd-networkd settings if they manage this interface (sysctl -w alone is lost on reboot or reconnect)"

IFACE=""
JSON=0
BLE=0

R_STATUS=()
R_CHECK=()
R_DETAIL=()
R_FIX=()
FAIL_COUNT=0

usage() {
    printf 'Usage: %s [--iface <name>] [--ble] [--json]\n' "$(basename "$0")" >&2
}

# ---------------------------------------------------------------------------
# 출력 도우미
# ---------------------------------------------------------------------------

# 줄바꿈을 공백으로 바꾸고 인쇄 가능한 ASCII 밖의 바이트(제어문자, 비 UTF-8 프로세스
# 이름 등)를 걷어 한 줄로 만든다. JSON/텍스트 양쪽에서 안전하다.
sanitize() {
    printf '%s' "$1" | tr '\n\r\t' '   ' | LC_ALL=C tr -cd '[:print:]'
}

# add <OK|WARN|FAIL> <점검> <상세> [고침]
add() {
    local status="$1" check="$2" detail fix=""
    detail=$(sanitize "$3")
    if [ $# -ge 4 ]; then
        fix=$(sanitize "$4")
    fi
    R_STATUS+=("$status")
    R_CHECK+=("$check")
    R_DETAIL+=("$detail")
    R_FIX+=("$fix")
    if [ "$status" = "FAIL" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

emit() {
    local i n="${#R_STATUS[@]}"
    if [ "$JSON" -eq 1 ]; then
        printf '['
        i=0
        while [ "$i" -lt "$n" ]; do
            [ "$i" -gt 0 ] && printf ','
            printf '\n  {"check": "%s", "status": "%s", "detail": "%s", "fix": "%s"}' \
                "$(json_escape "${R_CHECK[$i]}")" \
                "$(json_escape "${R_STATUS[$i]}")" \
                "$(json_escape "${R_DETAIL[$i]}")" \
                "$(json_escape "${R_FIX[$i]}")"
            i=$((i + 1))
        done
        printf '\n]\n'
    else
        i=0
        while [ "$i" -lt "$n" ]; do
            printf '%s  %s  %s\n' "${R_STATUS[$i]}" "${R_CHECK[$i]}" "${R_DETAIL[$i]}"
            if [ "${R_STATUS[$i]}" != "OK" ] && [ -n "${R_FIX[$i]}" ]; then
                printf '  → %s\n' "${R_FIX[$i]}"
            fi
            i=$((i + 1))
        done
    fi
}

# ---------------------------------------------------------------------------
# sysctl 읽기: 모든 /proc/sys 접근은 여기를 거친다(테스트에서 루트를 바꿀 수 있다).
# ---------------------------------------------------------------------------

# sysctl_file <상대경로>  예: net/ipv6/conf/eth0/accept_ra
sysctl_file() {
    printf '%s/%s' "$SYSCTL_ROOT" "$1"
}

# sysctl_read <상대경로>  값을 출력하고, 읽을 수 없으면 1 을 돌려준다.
sysctl_read() {
    local f v=""
    f=$(sysctl_file "$1")
    [ -r "$f" ] || return 1
    { read -r v < "$f"; } 2>/dev/null
    printf '%s' "$v"
}

# 정수 여부(음수 허용 안 함 — 점검 대상 값은 모두 0 이상).
is_uint() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

# sysctl 명령에서 쓰는 이름: 인터페이스 이름의 '.'(VLAN, eth0.100)은 '/' 로 바꾼다.
iface_key() {
    local slash="/"
    printf '%s' "${IFACE//./$slash}"
}

have_cmd() {
    command -v "$1" > /dev/null 2>&1
}

# ---------------------------------------------------------------------------
# 인자 파싱
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --iface)
            if [ $# -lt 2 ]; then
                usage
                exit 2
            fi
            IFACE="$2"
            shift 2
        ;;
        --iface=*)
            IFACE="${1#--iface=}"
            shift
        ;;
        --json)
            JSON=1
            shift
        ;;
        --ble)
            BLE=1
            shift
        ;;
        -h|--help)
            usage
            exit 0
        ;;
        *)
            usage
            exit 2
        ;;
    esac
done

# 인터페이스 이름은 /proc/sys 경로에 그대로 들어가므로 경로 탈출을 막는다.
if [ -n "$IFACE" ]; then
    case "$IFACE" in
        [A-Za-z0-9_]*) ;;
        *) usage; printf 'invalid interface name: %s\n' "$IFACE" >&2; exit 2 ;;
    esac
    case "$IFACE" in
        *[!A-Za-z0-9_.:@-]*) usage; printf 'invalid interface name: %s\n' "$IFACE" >&2; exit 2 ;;
    esac
fi

# ---------------------------------------------------------------------------
# 1. OS
# ---------------------------------------------------------------------------

if [ "$SKIP_CMDS" != "1" ]; then
    if [ "$(uname -s)" != "Linux" ]; then
        add FAIL os "Matter sidecar needs a Linux host with host networking (found $(uname -s)); Docker Desktop on macOS/Windows cannot provide host-network mDNS/IPv6 multicast" \
            "run the Matter sidecar on a Linux host (e.g. Raspberry Pi OS, Ubuntu, Debian) and run this check there"
        emit
        exit 2
    fi
    add OK os "Linux"
fi

# ---------------------------------------------------------------------------
# 2. 인터페이스 선택
# ---------------------------------------------------------------------------

IFACE_SOURCE="--iface"
if [ -z "$IFACE" ] && [ "$SKIP_CMDS" != "1" ] && have_cmd ip; then
    IFACE=$(ip route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)
    IFACE_SOURCE="IPv4 default route"
    if [ -z "$IFACE" ]; then
        IFACE=$(ip -6 route show default 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)
        IFACE_SOURCE="IPv6 default route"
    fi
fi

if [ -z "$IFACE" ]; then
    add FAIL interface "no interface selected: no --iface given and no default route found" \
        "re-run with the interface that reaches your devices' LAN: $(basename "$0") --iface <name>   (list: ip -br link)"
    emit
    exit 1
fi
case "$IFACE" in
    [A-Za-z0-9_]*) ;;
    *) add FAIL interface "invalid interface name: $IFACE" "re-run with --iface <name>"; emit; exit 1 ;;
esac
add OK interface "$IFACE (from $IFACE_SOURCE)"

KEY=$(iface_key)

if [ ! -d "$(sysctl_file "net/ipv6/conf/$IFACE")" ]; then
    add FAIL ipv6_enabled "no IPv6 configuration for $IFACE (wrong interface name, or the kernel IPv6 module is disabled)" \
        "check the name with: ip -br link   and that ipv6.disable=1 is not on the kernel command line"
    emit
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. IPv6 활성 + 링크 로컬 주소
# ---------------------------------------------------------------------------

v=$(sysctl_read "net/ipv6/conf/$IFACE/disable_ipv6") || v=""
if [ "$v" = "0" ]; then
    add OK ipv6_enabled "net.ipv6.conf.$KEY.disable_ipv6=0"
else
    add FAIL ipv6_enabled "net.ipv6.conf.$KEY.disable_ipv6=${v:-unreadable}" \
        "sudo sysctl -w net.ipv6.conf.$KEY.disable_ipv6=0   # $PERSIST_NOTE"
fi

if [ "$SKIP_CMDS" != "1" ]; then
    if have_cmd ip; then
        ll=$(ip -6 -o addr show dev "$IFACE" scope link 2>/dev/null | awk '{print $4}' | head -n 1)
        if [ -n "$ll" ]; then
            add OK ipv6_linklocal "$ll"
        else
            add FAIL ipv6_linklocal "no link-local (fe80::/10) address on $IFACE" \
                "ip -6 addr show dev $IFACE   # check the link is up and net.ipv6.conf.$KEY.addr_gen_mode is not 1 (1 = do not generate a link-local address)"
        fi
    else
        add WARN ipv6_linklocal "ip command not found; link-local address not verified" \
            "install iproute2 (e.g. sudo apt-get install iproute2)"
    fi
fi

# ---------------------------------------------------------------------------
# 4. forwarding / accept_ra
# ---------------------------------------------------------------------------

# 실제로 RA 처리에 쓰이는 값은 인터페이스별 forwarding 이다. 읽을 수 있으면 그것을,
# 없으면 all.forwarding 을 쓴다.
fwd_all=$(sysctl_read "net/ipv6/conf/all/forwarding") || fwd_all=""
fwd_if=$(sysctl_read "net/ipv6/conf/$IFACE/forwarding") || fwd_if=""
fwd=""
if is_uint "$fwd_if"; then
    fwd="$fwd_if"
elif is_uint "$fwd_all"; then
    fwd="$fwd_all"
fi

if [ -z "$fwd" ]; then
    add WARN ipv6_forwarding "net.ipv6.conf.all.forwarding unreadable; assuming 0" \
        "sysctl net.ipv6.conf.all.forwarding"
    fwd=0
elif [ -n "$fwd_if" ] && [ -n "$fwd_all" ] && [ "$fwd_if" != "$fwd_all" ]; then
    add OK ipv6_forwarding "all=$fwd_all $KEY=$fwd_if (using $KEY)"
else
    add OK ipv6_forwarding "net.ipv6.conf.all.forwarding=$fwd"
fi

if [ "$fwd" = "0" ]; then
    want_ra="1"
else
    want_ra="2"
fi

ra=$(sysctl_read "net/ipv6/conf/$IFACE/accept_ra") || ra=""
if ! is_uint "$ra"; then
    add FAIL accept_ra "net.ipv6.conf.$KEY.accept_ra unreadable" \
        "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra=$want_ra   # $PERSIST_NOTE"
elif [ "$fwd" = "0" ]; then
    # forwarding=0 이면 1(또는 2)이어야 RA 를 받는다.
    if [ "$ra" -ge 1 ]; then
        add OK accept_ra "net.ipv6.conf.$KEY.accept_ra=$ra (forwarding=0)"
    else
        add FAIL accept_ra "net.ipv6.conf.$KEY.accept_ra=$ra with forwarding=0; Router Advertisements are ignored" \
            "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra=1   # $PERSIST_NOTE"
    fi
else
    # forwarding=1 이면 2 여야만 RA 를 받는다(1 은 라우터로 간주되어 무시된다).
    if [ "$ra" = "2" ]; then
        add OK accept_ra "net.ipv6.conf.$KEY.accept_ra=2 (forwarding=1)"
    else
        add FAIL accept_ra "net.ipv6.conf.$KEY.accept_ra=$ra with forwarding=1; Router Advertisements are ignored (needs 2)" \
            "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra=2   # $PERSIST_NOTE"
    fi
fi

# ---------------------------------------------------------------------------
# 5. accept_ra_rt_info_max_plen
# ---------------------------------------------------------------------------

plen=$(sysctl_read "net/ipv6/conf/$IFACE/accept_ra_rt_info_max_plen") || plen=""
if [ -z "$plen" ] && [ ! -e "$(sysctl_file "net/ipv6/conf/$IFACE/accept_ra_rt_info_max_plen")" ]; then
    add WARN accept_ra_rt_info_max_plen "net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen is missing; the kernel likely lacks CONFIG_IPV6_ROUTE_INFO, so routes advertised by Thread border routers cannot be learned" \
        "use a kernel built with CONFIG_IPV6_ROUTE_INFO=y"
elif ! is_uint "$plen"; then
    add FAIL accept_ra_rt_info_max_plen "net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen unreadable" \
        "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen=64   # $PERSIST_NOTE"
elif [ "$plen" -ge 64 ]; then
    add OK accept_ra_rt_info_max_plen "net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen=$plen"
else
    add FAIL accept_ra_rt_info_max_plen "net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen=$plen (need >= 64)" \
        "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra_rt_info_max_plen=64   # $PERSIST_NOTE"
fi

# ---------------------------------------------------------------------------
# 5-1. accept_ra_rtr_pref
#   0 이면 커널이 라우터 우선순위·Route Information Option 을 무시하므로
#   accept_ra_rt_info_max_plen 이 통과해도 Thread 경로를 배우지 못한다.
# ---------------------------------------------------------------------------

pref=$(sysctl_read "net/ipv6/conf/$IFACE/accept_ra_rtr_pref") || pref=""
if [ -z "$pref" ] && [ ! -e "$(sysctl_file "net/ipv6/conf/$IFACE/accept_ra_rtr_pref")" ]; then
    add WARN accept_ra_rtr_pref "net.ipv6.conf.$KEY.accept_ra_rtr_pref is missing; the kernel likely lacks CONFIG_IPV6_ROUTER_PREF" \
        "use a kernel built with CONFIG_IPV6_ROUTER_PREF=y"
elif ! is_uint "$pref"; then
    add FAIL accept_ra_rtr_pref "net.ipv6.conf.$KEY.accept_ra_rtr_pref unreadable" \
        "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra_rtr_pref=1   # $PERSIST_NOTE"
elif [ "$pref" -ge 1 ]; then
    add OK accept_ra_rtr_pref "net.ipv6.conf.$KEY.accept_ra_rtr_pref=$pref"
else
    add FAIL accept_ra_rtr_pref "net.ipv6.conf.$KEY.accept_ra_rtr_pref=0; the kernel ignores router preference and Route Information Options, so Thread routes are never learned" \
        "sudo sysctl -w net.ipv6.conf.$KEY.accept_ra_rtr_pref=1   # $PERSIST_NOTE"
fi

# ---------------------------------------------------------------------------
# 6. 커널 옵션 (CONFIG_IPV6_ROUTER_PREF / CONFIG_IPV6_ROUTE_INFO)
# ---------------------------------------------------------------------------

KCONFIG_TEXT=""
KCONFIG_SRC=""
load_kconfig() {
    if [ -r /proc/config.gz ]; then
        if have_cmd zcat; then
            KCONFIG_TEXT=$(zcat /proc/config.gz 2>/dev/null | grep 'CONFIG_IPV6_ROUTE')
            KCONFIG_SRC="/proc/config.gz"
            return 0
        elif have_cmd gzip; then
            KCONFIG_TEXT=$(gzip -dc /proc/config.gz 2>/dev/null | grep 'CONFIG_IPV6_ROUTE')
            KCONFIG_SRC="/proc/config.gz"
            return 0
        fi
    fi
    local f
    f="/boot/config-$(uname -r)"
    if [ -r "$f" ]; then
        KCONFIG_TEXT=$(grep 'CONFIG_IPV6_ROUTE' "$f" 2>/dev/null)
        KCONFIG_SRC="$f"
        return 0
    fi
    return 1
}

# kconfig_check <옵션> <미설정일 때 상태> <미설정 힌트>
kconfig_check() {
    local opt="$1" miss_status="$2" fixmsg="$3" val
    local check
    check=$(printf '%s' "$opt" | tr 'A-Z' 'a-z')
    if [ -z "$KCONFIG_SRC" ]; then
        add WARN "$check" "$opt: unknown (neither /proc/config.gz nor /boot/config-$(uname -r) is readable)" \
            "load the configs module (sudo modprobe configs) or check your distribution's kernel config for $opt=y"
        return
    fi
    val=$(printf '%s\n' "$KCONFIG_TEXT" | sed -n "s/^$opt=\(.*\)$/\1/p" | head -n 1)
    case "$val" in
        y|m) add OK "$check" "$opt=$val ($KCONFIG_SRC)" ;;
        *)   add "$miss_status" "$check" "$opt is not enabled ($KCONFIG_SRC)" "$fixmsg" ;;
    esac
}

if [ "$SKIP_CMDS" != "1" ]; then
    load_kconfig
    kconfig_check CONFIG_IPV6_ROUTER_PREF FAIL "use a kernel built with CONFIG_IPV6_ROUTER_PREF=y"
    kconfig_check CONFIG_IPV6_ROUTE_INFO WARN "use a kernel built with CONFIG_IPV6_ROUTE_INFO=y (required for the accept_ra_rt_info_max_plen sysctl)"
fi

# ---------------------------------------------------------------------------
# 7. NetworkManager
# ---------------------------------------------------------------------------

if [ "$SKIP_CMDS" != "1" ] && have_cmd nmcli && have_cmd systemctl \
        && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    nm_ver=$(nmcli --version 2>/dev/null | sed -n 's/.*version \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1)
    nm_major="${nm_ver%%.*}"
    nm_minor="${nm_ver#*.}"
    if ! is_uint "$nm_major" || ! is_uint "$nm_minor"; then
        add WARN networkmanager "NetworkManager is active but its version could not be determined" \
            "nmcli --version   # NetworkManager >= 1.42 is required; $PERSIST_NOTE"
    elif [ "$nm_major" -gt 1 ] || { [ "$nm_major" -eq 1 ] && [ "$nm_minor" -ge 42 ]; }; then
        add OK networkmanager "NetworkManager $nm_ver is active; values set with sysctl -w may be overwritten on reconnect, so persist them in NetworkManager or /etc/sysctl.d/99-matter.conf (if this interface is unmanaged) and re-run this check after a reconnect"
    else
        add WARN networkmanager "NetworkManager $nm_ver is older than 1.42" \
            "upgrade NetworkManager to >= 1.42 (or manage this interface with systemd-networkd); $PERSIST_NOTE"
    fi
fi

# ---------------------------------------------------------------------------
# 8. conntrack UDP 타임아웃
# ---------------------------------------------------------------------------

ct_rel="net/netfilter/nf_conntrack_udp_timeout_stream"
if [ ! -e "$(sysctl_file "$ct_rel")" ]; then
    add OK conntrack_udp_timeout "conntrack not loaded"
else
    ct=$(sysctl_read "$ct_rel") || ct=""
    if ! is_uint "$ct"; then
        add WARN conntrack_udp_timeout "net.netfilter.nf_conntrack_udp_timeout_stream unreadable" \
            "sysctl net.netfilter.nf_conntrack_udp_timeout_stream"
    elif [ "$ct" -ge 3600 ]; then
        add OK conntrack_udp_timeout "net.netfilter.nf_conntrack_udp_timeout_stream=$ct"
    elif [ "$ct" -ge 1800 ]; then
        add OK conntrack_udp_timeout "net.netfilter.nf_conntrack_udp_timeout_stream=$ct (>= 1800; 3600 recommended)"
    else
        add WARN conntrack_udp_timeout "net.netfilter.nf_conntrack_udp_timeout_stream=$ct (< 1800); sleepy devices may drop their report subscriptions" \
            "sudo sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=3600   # persist: /etc/sysctl.d/99-matter.conf; do not filter by destination port 5540 in the firewall"
    fi
fi

# ---------------------------------------------------------------------------
# 9. 멀티캐스트 플래그 / mDNS / RA 경로 / Docker  (외부 명령 필요)
# ---------------------------------------------------------------------------

if [ "$SKIP_CMDS" != "1" ]; then
    # 멀티캐스트 플래그
    if have_cmd ip; then
        flags=$(ip -o link show dev "$IFACE" 2>/dev/null | sed -n 's/.*<\([^>]*\)>.*/\1/p' | head -n 1)
        if [ -z "$flags" ]; then
            add FAIL multicast "cannot read link flags of $IFACE" "ip -br link   # check the interface name"
        else
            case ",$flags," in
                *,MULTICAST,*) add OK multicast "$IFACE flags: $flags" ;;
                *) add FAIL multicast "$IFACE has no MULTICAST flag ($flags); mDNS and IPv6 neighbor discovery need it" \
                    "sudo ip link set dev $IFACE multicast on   # persist in the NetworkManager/systemd-networkd settings for this interface" ;;
            esac
        fi
    else
        add WARN multicast "ip command not found; MULTICAST flag not verified" \
            "install iproute2 (e.g. sudo apt-get install iproute2)"
    fi

    # UDP 5353 점유(정보용 — 사이드카가 자체 mDNS 를 쓰므로 실패 사유가 아니다)
    if have_cmd ss; then
        ss_lines=$(ss -ulpn 2>/dev/null | grep -E ':5353([[:space:]]|$)')
        if [ -z "$ss_lines" ]; then
            add OK mdns_5353 "nothing else is bound to UDP 5353 on this host (info only)"
        else
            procs=$(printf '%s\n' "$ss_lines" | LC_ALL=C sed -n 's/.*users:(("\([^"]*\)".*/\1/p' | sort -u | paste -sd, -)
            if [ -n "$procs" ]; then
                add OK mdns_5353 "UDP 5353 is bound by: $procs (info only; the sidecar does its own mDNS)"
            else
                add OK mdns_5353 "UDP 5353 is bound (process names hidden; run as root to see them) (info only; the sidecar does its own mDNS)"
            fi
        fi
    else
        add WARN mdns_5353 "ss command not found; UDP 5353 usage not checked (info only)" \
            "install iproute2 (e.g. sudo apt-get install iproute2)"
    fi

    # RA 로 배운 경로
    if have_cmd ip; then
        ra_routes=$(ip -6 route show proto ra dev "$IFACE" 2>/dev/null | grep -c .)
        if [ "${ra_routes:-0}" -gt 0 ]; then
            add OK ra_routes "$ra_routes IPv6 route(s) learned from Router Advertisements on $IFACE"
        else
            add WARN ra_routes "no RA-learned routes yet; Thread devices behind a border router will be unreachable until a border router advertises a route (normal on a host without Thread border routers)" \
                "power on a Thread border router on this LAN (HomePod, Apple TV, Nest Hub, ...) then check: ip -6 route show proto ra"
        fi
    fi

    # Docker
    if have_cmd docker; then
        add OK docker "docker found ($(command -v docker))"
    else
        add WARN docker "docker not found; the Matter sidecar runs as a host-network container" \
            "install Docker Engine: https://docs.docker.com/engine/install/"
    fi
fi

# ---------------------------------------------------------------------------
# 10. Bluetooth (--ble)
#   BLE 커미셔닝(docker/docker-compose.matter-ble.yml, NOBLE_BINDINGS=dbus)의
#   호스트 조건. BLE 는 선택 기능이라 어댑터가 아예 없을 때만 FAIL 이고 나머지는
#   WARN 이다. 전부 읽기 전용이다(rfkill unblock, bluetoothctl power on 은 출력만).
# ---------------------------------------------------------------------------

if [ "$BLE" -eq 1 ]; then
    # BlueZ 데몬
    if [ "$SKIP_CMDS" != "1" ]; then
        bluez_fix="sudo apt-get install bluez && sudo systemctl enable --now bluetooth"
        if have_cmd systemctl; then
            if systemctl is-active --quiet bluetooth 2>/dev/null; then
                BLUEZ_UP=1; add OK ble_bluez "bluetooth.service is active"
            else
                add WARN ble_bluez "bluetooth.service is not active; NOBLE_BINDINGS=dbus talks to the host BlueZ" \
                    "$bluez_fix"
            fi
        elif have_cmd pgrep; then
            if pgrep -x bluetoothd > /dev/null 2>&1; then
                BLUEZ_UP=1; add OK ble_bluez "bluetoothd is running"
            else
                add WARN ble_bluez "bluetoothd is not running; NOBLE_BINDINGS=dbus talks to the host BlueZ" \
                    "install and start BlueZ (e.g. $bluez_fix)"
            fi
        else
            add WARN ble_bluez "neither systemctl nor pgrep found; BlueZ daemon not verified" \
                "check manually that bluetoothd is running"
        fi
    fi

    # 어댑터 존재 (hci0, hci1, ...)
    hci_names=""
    if [ -d "$SYS_BLUETOOTH" ]; then
        for d in "$SYS_BLUETOOTH"/hci*; do
            [ -e "$d" ] || continue
            hci_names="${hci_names:+$hci_names }${d##*/}"
        done
    fi
    if [ -n "$hci_names" ]; then
        add OK ble_adapter "Bluetooth adapter(s): $hci_names (MATTER_BLUETOOTH_ADAPTER is the number after hci)"
    else
        add FAIL ble_adapter "no Bluetooth adapter found in $SYS_BLUETOOTH" \
            "attach a BLE-capable USB dongle or enable the on-board one (ls /sys/class/bluetooth; dmesg | grep -i bluetooth); without an adapter, commission over IP only (omit docker-compose.matter-ble.yml)"
    fi

    # rfkill 차단 / 전원 / D-Bus 소켓: 외부 명령은 SKIP_CMDS 로 건너뛴다.
    if [ "$SKIP_CMDS" != "1" ]; then
        if have_cmd rfkill; then
            rf=$(rfkill list bluetooth 2>/dev/null)
            if [ -z "$rf" ]; then
                add OK ble_rfkill "no rfkill entry for bluetooth (nothing to unblock)"
            elif printf '%s\n' "$rf" | grep -Eqi 'Soft blocked: yes|Hard blocked: yes'; then
                if printf '%s\n' "$rf" | grep -qi 'Hard blocked: yes'; then
                    add WARN ble_rfkill "Bluetooth is hard blocked (physical switch or firmware)" \
                        "turn the hardware radio switch on (rfkill list bluetooth), then: sudo rfkill unblock bluetooth"
                else
                    add WARN ble_rfkill "Bluetooth is soft blocked by rfkill" \
                        "sudo rfkill unblock bluetooth"
                fi
            else
                add OK ble_rfkill "Bluetooth is not blocked by rfkill"
            fi
        else
            add OK ble_rfkill "rfkill not installed; cannot check for blocks"
        fi

        if [ "${BLUEZ_UP:-0}" != "1" ]; then
            # bluetoothctl blocks ("Waiting to connect to bluetoothd...") when
            # the daemon is down; the ble_bluez line above already says so.
            add OK ble_powered "power not checked: BlueZ daemon is not running"
        elif have_cmd bluetoothctl; then
            if have_cmd timeout; then
                bt_show=$(timeout 5 bluetoothctl show 2>/dev/null)
            else
                bt_show=$(bluetoothctl show 2>/dev/null)
            fi
            if printf '%s\n' "$bt_show" | grep -q 'Powered: yes'; then
                add OK ble_powered "adapter is powered on"
            else
                add WARN ble_powered "adapter is not powered (or no default controller); matterjs-server only logs 'noble state is not poweredOn' and commissioning times out" \
                    "bluetoothctl power on   # persist: AutoEnable=true in the [Policy] section of /etc/bluetooth/main.conf, then sudo systemctl restart bluetooth"
            fi
        else
            add OK ble_powered "bluetoothctl not installed; cannot check power"
        fi
    fi

    # D-Bus 시스템 소켓(NOBLE_BINDINGS=dbus 가 /run/dbus 마운트로 쓴다)
    if [ -S "$DBUS_SOCKET" ] || [ -e "$DBUS_SOCKET" ]; then
        add OK ble_dbus_socket "$DBUS_SOCKET exists"
    else
        add WARN ble_dbus_socket "$DBUS_SOCKET not found; the container mounts /run/dbus read-only to reach BlueZ" \
            "sudo apt-get install dbus && sudo systemctl enable --now dbus"
    fi
fi

emit
if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
