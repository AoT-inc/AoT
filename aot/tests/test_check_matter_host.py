# coding=utf-8
"""Matter 호스트 사전 점검 스크립트(check_matter_host.sh)의 sysctl 기반 점검을 지키는 가드.

실제 /proc/sys 대신 임시 폴더에 가짜 트리를 만들고 MATTER_CHECK_PROC_SYS 로 가리킨다.
MATTER_CHECK_SKIP_OS=1 로 Linux 검사와 ip/ss/docker 등 외부 명령 점검을 건너뛰므로
어느 OS 에서도 같은 결과가 나온다. 스크립트는 읽기 전용이어야 한다.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

BASH = shutil.which("bash")
if BASH is None:
    pytest.skip("bash 가 없다", allow_module_level=True)

SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "scripts", "check_matter_host.sh"
)
SCRIPT = os.path.normpath(SCRIPT)

IFACE = "eth0"


def _write(root, rel, value):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("%s\n" % value)


def make_tree(root, iface=IFACE, forwarding=0, accept_ra=None, plen=64,
              conntrack=3600, disable_ipv6=0, iface_forwarding=None, rtr_pref=1):
    """정상 호스트를 흉내 낸 /proc/sys 트리를 만든다. None 인 항목은 파일을 만들지 않는다."""
    conf = "net/ipv6/conf"
    _write(root, "%s/all/forwarding" % conf, forwarding)
    if iface_forwarding is not None:
        _write(root, "%s/%s/forwarding" % (conf, iface), iface_forwarding)
    _write(root, "%s/%s/disable_ipv6" % (conf, iface), disable_ipv6)
    if accept_ra is None:
        accept_ra = 2 if forwarding else 1
    _write(root, "%s/%s/accept_ra" % (conf, iface), accept_ra)
    if plen is not None:
        _write(root, "%s/%s/accept_ra_rt_info_max_plen" % (conf, iface), plen)
    if rtr_pref is not None:
        _write(root, "%s/%s/accept_ra_rtr_pref" % (conf, iface), rtr_pref)
    if conntrack is not None:
        _write(root, "net/netfilter/nf_conntrack_udp_timeout_stream", conntrack)
    return root


def run(root, *args, env_extra=None):
    env = dict(os.environ)
    env["MATTER_CHECK_SKIP_OS"] = "1"
    env["MATTER_CHECK_PROC_SYS"] = str(root)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [BASH, SCRIPT] + list(args), env=env, capture_output=True, text=True, timeout=30
    )


def run_json(root, *extra):
    proc = run(root, "--iface", IFACE, "--json", *extra)
    return proc, {r["check"]: r for r in json.loads(proc.stdout)}


def test_all_good_exits_zero(tmp_path):
    make_tree(tmp_path)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert {r["status"] for r in res.values()} == {"OK"}
    for name in ("interface", "ipv6_enabled", "ipv6_forwarding", "accept_ra",
                 "accept_ra_rt_info_max_plen", "accept_ra_rtr_pref", "conntrack_udp_timeout"):
        assert name in res
    # 외부 명령 점검은 SKIP_OS 에서 아무것도 출력하지 않는다.
    for name in ("os", "ipv6_linklocal", "multicast", "mdns_5353", "ra_routes", "docker",
                 "networkmanager", "config_ipv6_router_pref"):
        assert name not in res


def test_json_objects_have_all_keys(tmp_path):
    make_tree(tmp_path, accept_ra=0)
    proc, res = run_json(tmp_path)
    for r in json.loads(proc.stdout):
        assert set(r) == {"check", "status", "detail", "fix"}
    assert res["accept_ra"]["fix"]
    assert res["interface"]["fix"] == ""


def test_accept_ra_zero_without_forwarding_fails(tmp_path):
    make_tree(tmp_path, forwarding=0, accept_ra=0)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["accept_ra"]["status"] == "FAIL"
    assert "sysctl -w net.ipv6.conf.eth0.accept_ra=1" in res["accept_ra"]["fix"]


def test_forwarding_requires_accept_ra_two(tmp_path):
    make_tree(tmp_path, forwarding=1, accept_ra=1)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["accept_ra"]["status"] == "FAIL"
    assert "accept_ra=2" in res["accept_ra"]["fix"]

    ok_root = tmp_path / "ok"
    make_tree(ok_root, forwarding=1, accept_ra=2)
    proc, res = run_json(ok_root)
    assert proc.returncode == 0
    assert res["accept_ra"]["status"] == "OK"


def test_interface_forwarding_overrides_all(tmp_path):
    # all=0 이어도 인터페이스 값이 1 이면 라우터로 동작하므로 accept_ra=2 가 필요하다.
    make_tree(tmp_path, forwarding=0, iface_forwarding=1, accept_ra=1)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["accept_ra"]["status"] == "FAIL"


def test_missing_rt_info_max_plen_is_warn(tmp_path):
    make_tree(tmp_path, plen=None)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0
    assert res["accept_ra_rt_info_max_plen"]["status"] == "WARN"
    assert "CONFIG_IPV6_ROUTE_INFO" in res["accept_ra_rt_info_max_plen"]["detail"]


def test_low_rt_info_max_plen_fails(tmp_path):
    make_tree(tmp_path, plen=0)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["accept_ra_rt_info_max_plen"]["status"] == "FAIL"


def test_rtr_pref_zero_fails(tmp_path):
    # rt_info_max_plen 이 64 여도 rtr_pref=0 이면 Thread 경로를 배우지 못한다.
    make_tree(tmp_path, plen=64, rtr_pref=0)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["accept_ra_rt_info_max_plen"]["status"] == "OK"
    assert res["accept_ra_rtr_pref"]["status"] == "FAIL"
    assert "sysctl -w net.ipv6.conf.eth0.accept_ra_rtr_pref=1" in res["accept_ra_rtr_pref"]["fix"]
    assert "persist" in res["accept_ra_rtr_pref"]["fix"]


def test_rtr_pref_one_is_ok(tmp_path):
    make_tree(tmp_path, rtr_pref=1)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0
    assert res["accept_ra_rtr_pref"]["status"] == "OK"


def test_missing_rtr_pref_is_warn(tmp_path):
    make_tree(tmp_path, rtr_pref=None)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0
    assert res["accept_ra_rtr_pref"]["status"] == "WARN"
    assert "CONFIG_IPV6_ROUTER_PREF" in res["accept_ra_rtr_pref"]["detail"]


def test_conntrack_timeout_too_low_is_warn(tmp_path):
    make_tree(tmp_path, conntrack=600)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0  # WARN 만으로는 실패하지 않는다.
    assert res["conntrack_udp_timeout"]["status"] == "WARN"
    assert "=3600" in res["conntrack_udp_timeout"]["fix"]


def test_conntrack_boundary_1800_is_ok(tmp_path):
    make_tree(tmp_path, conntrack=1800)
    _proc, res = run_json(tmp_path)
    assert res["conntrack_udp_timeout"]["status"] == "OK"


def test_conntrack_absent_is_ok(tmp_path):
    make_tree(tmp_path, conntrack=None)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 0
    assert res["conntrack_udp_timeout"]["status"] == "OK"
    assert "conntrack not loaded" in res["conntrack_udp_timeout"]["detail"]


def test_ipv6_disabled_fails(tmp_path):
    make_tree(tmp_path, disable_ipv6=1)
    proc, res = run_json(tmp_path)
    assert proc.returncode == 1
    assert res["ipv6_enabled"]["status"] == "FAIL"


def test_unknown_interface_fails(tmp_path):
    make_tree(tmp_path, iface="wlan0")
    proc = run(tmp_path, "--iface", "eth0", "--json")
    assert proc.returncode == 1
    res = {r["check"]: r for r in json.loads(proc.stdout)}
    assert res["ipv6_enabled"]["status"] == "FAIL"


def test_vlan_iface_uses_slash_in_sysctl_key(tmp_path):
    make_tree(tmp_path, iface="eth0.100", accept_ra=0)
    proc = run(tmp_path, "--iface", "eth0.100", "--json")
    res = {r["check"]: r for r in json.loads(proc.stdout)}
    assert "net.ipv6.conf.eth0/100.accept_ra=1" in res["accept_ra"]["fix"]


def test_no_iface_without_commands_fails(tmp_path):
    make_tree(tmp_path)
    proc = run(tmp_path, "--json")
    assert proc.returncode == 1
    res = {r["check"]: r for r in json.loads(proc.stdout)}
    assert res["interface"]["status"] == "FAIL"


@pytest.mark.parametrize("bad", ["../etc", "a/b", "-x", ".", "eth0 ", "a\"b"])
def test_rejects_unsafe_iface_names(tmp_path, bad):
    make_tree(tmp_path)
    proc = run(tmp_path, "--iface", bad)
    assert proc.returncode == 2


def test_unknown_argument_is_usage_error(tmp_path):
    proc = run(tmp_path, "--nope")
    assert proc.returncode == 2


def test_text_output_format(tmp_path):
    make_tree(tmp_path, accept_ra=0)
    proc = run(tmp_path, "--iface", IFACE)
    lines = proc.stdout.splitlines()
    assert any(l.startswith("OK  interface  ") for l in lines)
    idx = next(i for i, l in enumerate(lines) if l.startswith("FAIL  accept_ra  "))
    assert lines[idx + 1].startswith("  → sudo sysctl -w ")
    # OK 줄 뒤에는 고침 줄이 없다.
    idx_ok = next(i for i, l in enumerate(lines) if l.startswith("OK  interface  "))
    assert not lines[idx_ok + 1].startswith("  →")


def _snapshot(root):
    snap = {}
    for dirpath, _dirs, files in os.walk(str(root)):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p) as fh:
                snap[p] = (fh.read(), os.stat(p).st_mtime_ns)
    return snap


def test_script_is_read_only(tmp_path):
    make_tree(tmp_path, accept_ra=0, plen=0, conntrack=600)
    before = _snapshot(tmp_path)
    run(tmp_path, "--iface", IFACE)
    run(tmp_path, "--iface", IFACE, "--json")
    assert _snapshot(tmp_path) == before


# --- --ble (Bluetooth 점검) ---------------------------------------------------

def make_ble(root, adapters=("hci0",), dbus_socket=True):
    """가짜 /sys/class/bluetooth 와 D-Bus 소켓 자리를 만든다. (sys_dir, socket_path) 반환."""
    sys_dir = root / "sys_bluetooth"
    sys_dir.mkdir()
    for name in adapters:
        (sys_dir / name).mkdir()
    sock = root / "dbus" / "system_bus_socket"
    sock.parent.mkdir()
    if dbus_socket:
        sock.write_text("")
    return sys_dir, sock


def run_ble(tmp_path, sys_dir, sock, *extra):
    proc_sys = tmp_path / "proc_sys"
    make_tree(proc_sys)
    env = {"MATTER_CHECK_SYS_BLUETOOTH": str(sys_dir), "MATTER_CHECK_DBUS_SOCKET": str(sock)}
    proc = run(proc_sys, "--iface", IFACE, "--ble", "--json", *extra, env_extra=env)
    return proc, {r["check"]: r for r in json.loads(proc.stdout)}


def test_ble_adapter_and_dbus_socket_ok(tmp_path):
    sys_dir, sock = make_ble(tmp_path, adapters=("hci0", "hci1"))
    proc, res = run_ble(tmp_path, sys_dir, sock)
    assert proc.returncode == 0, proc.stdout
    assert res["ble_adapter"]["status"] == "OK"
    assert "hci0" in res["ble_adapter"]["detail"] and "hci1" in res["ble_adapter"]["detail"]
    assert res["ble_dbus_socket"]["status"] == "OK"
    # 외부 명령 기반 점검은 SKIP_OS 에서 출력하지 않는다.
    for name in ("ble_bluez", "ble_rfkill", "ble_powered"):
        assert name not in res


def test_ble_no_adapter_fails(tmp_path):
    sys_dir, sock = make_ble(tmp_path, adapters=())
    proc, res = run_ble(tmp_path, sys_dir, sock)
    assert proc.returncode == 1
    assert res["ble_adapter"]["status"] == "FAIL"
    assert res["ble_adapter"]["fix"]


def test_ble_missing_sysfs_dir_fails(tmp_path):
    sys_dir, sock = make_ble(tmp_path)
    proc, res = run_ble(tmp_path, tmp_path / "nope", sock)
    assert proc.returncode == 1
    assert res["ble_adapter"]["status"] == "FAIL"


def test_ble_missing_dbus_socket_is_warn(tmp_path):
    sys_dir, sock = make_ble(tmp_path, dbus_socket=False)
    proc, res = run_ble(tmp_path, sys_dir, sock)
    assert proc.returncode == 0  # WARN 만으로는 실패하지 않는다.
    assert res["ble_adapter"]["status"] == "OK"
    assert res["ble_dbus_socket"]["status"] == "WARN"
    assert "dbus" in res["ble_dbus_socket"]["fix"]


def test_no_ble_checks_without_flag(tmp_path):
    sys_dir, sock = make_ble(tmp_path)
    proc_sys = tmp_path / "proc_sys"
    make_tree(proc_sys)
    env = {"MATTER_CHECK_SYS_BLUETOOTH": str(sys_dir), "MATTER_CHECK_DBUS_SOCKET": str(sock)}
    proc = run(proc_sys, "--iface", IFACE, "--json", env_extra=env)
    assert proc.returncode == 0
    assert not [r for r in json.loads(proc.stdout) if r["check"].startswith("ble_")]


def test_ble_text_output_and_read_only(tmp_path):
    sys_dir, sock = make_ble(tmp_path, adapters=(), dbus_socket=False)
    proc_sys = tmp_path / "proc_sys"
    make_tree(proc_sys)
    before = _snapshot(tmp_path)
    env = {"MATTER_CHECK_SYS_BLUETOOTH": str(sys_dir), "MATTER_CHECK_DBUS_SOCKET": str(sock)}
    proc = run(proc_sys, "--iface", IFACE, "--ble", env_extra=env)
    assert proc.returncode == 1
    lines = proc.stdout.splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("FAIL  ble_adapter  "))
    assert lines[idx + 1].startswith("  → ")
    assert any(l.startswith("WARN  ble_dbus_socket  ") for l in lines)
    assert _snapshot(tmp_path) == before
    assert sorted(p.name for p in sys_dir.iterdir()) == []


def test_script_is_executable_and_parses():
    assert os.access(SCRIPT, os.X_OK)
    proc = subprocess.run([BASH, "-n", SCRIPT], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="비 Linux 호스트에서만 의미가 있다")
def test_non_linux_host_prints_single_fail_and_exits_two(tmp_path):
    env = dict(os.environ)
    env.pop("MATTER_CHECK_SKIP_OS", None)
    proc = subprocess.run([BASH, SCRIPT], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    lines = proc.stdout.splitlines()
    assert lines[0].startswith("FAIL  os  ")
    assert "Linux" in lines[0]
    assert len([l for l in lines if l.startswith(("OK", "WARN", "FAIL"))]) == 1

    proc = subprocess.run([BASH, SCRIPT, "--json"], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    data = json.loads(proc.stdout)
    assert [r["check"] for r in data] == ["os"]
    assert data[0]["status"] == "FAIL"
