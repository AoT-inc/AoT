# coding=utf-8
"""7c: gRPC 장치 열거가 flask 없이 import 되고, 기존 이름도 그대로 닿는다."""
import subprocess
import sys


def test_pure_module_has_no_flask():
    code = ("import sys, aot.utils.chirpstack_grpc as m; "
            "assert 'flask' not in sys.modules, 'flask 가 딸려 왔다'; "
            "assert m._normalize_server('http://cs.local/x') == 'cs.local:8080'; "
            "assert m._normalize_token('Bearer abc') == 'abc'")
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_old_import_path_is_same_object():
    from aot.aot_flask.utils import utils_chirpstack as old
    from aot.utils import chirpstack_grpc as new
    assert old.list_chirpstack_devices is new.list_chirpstack_devices
    assert old.grpc_available is new.grpc_available


def test_no_devices_without_credentials():
    from aot.utils.chirpstack_grpc import list_chirpstack_devices
    devices, err = list_chirpstack_devices('', '')
    assert devices == [] and err
