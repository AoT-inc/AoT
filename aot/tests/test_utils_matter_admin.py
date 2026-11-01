# coding=utf-8
"""설정 > Matter 3단계 서비스(aot/aot_flask/utils/utils_matter_admin.py) 검사.

DB·Matter 서버·스레드 없이 가짜 클라이언트로 돈다(잠을 자지 않고 함수를 직접
부른다). 지키는 것:
  - 새 장치(BLE) 네트워크 입력 검증: Wi-Fi 이름 32바이트(한글은 3바이트),
    비밀번호 8~64자, Thread 데이터셋은 짝수 길이 16진수.
  - 시작 단계: 잘못된 코드·서버 꺼짐·블루투스 없음은 작업 파일도 스레드도
    만들지 않는다(단, 'none' 은 블루투스 없이 허용).
  - 비밀(Wi-Fi 비밀번호·Thread 데이터셋)은 작업 파일에 절대 들어가지 않는다.
    서버에는 일회용 id 로 넣었다가 성공·실패·예외와 상관없이 항상 지운다.
    서버 오류 문구에 비밀이 섞여 있어도 작업 파일에서는 가려진다.
  - 작업 상태: 모르는/잘못된 id 는 'unknown', 오래 멈춘 작업은 timeout 실패,
    'commissioned' 는 폴링한 사용자 요청에서 딱 한 번만 AoT 장치로 등록된다.
  - 공유 창: 시간 제한을 [180, 900] 으로 맞추고, 장치가 없거나 닿지 않거나
    Fabric 자리가 가득 차면 서버에 보내지 않는다. 이미 닫힌 창은 성공으로 본다.
  - Fabric 목록·제거: AoT 자신의 연결은 지울 수 없다.
  - 펌웨어: 인증된(main-net DCL) 업데이트만, 사람이 요청한 버전과 같을 때,
    장치가 닿고 한가할 때만 시작한다.
"""
import contextlib
import json
import os
import time

import pytest

flask = pytest.importorskip('flask')
from flask_babel import Babel  # noqa: E402

from aot.aot_flask.utils import utils_matter, utils_matter_admin as admin  # noqa: E402
from aot.devices import matter_clusters  # noqa: E402
from aot.devices.matter_client import (MatterCommandError, MatterCommandTimeout,  # noqa: E402
                                       MatterNotConnected)

SECRET_PW = 'hunter2-secret-pw'
SECRET_DATASET = '0e080000000000010000000300001035060004001fffe0'
WIFI = {'kind': 'wifi', 'ssid': 'FarmNet', 'password': SECRET_PW}
THREAD = {'kind': 'thread', 'dataset': SECRET_DATASET}
CODE = '34970112332'


@pytest.fixture
def app_ctx():
    app = flask.Flask(__name__)
    Babel(app)
    with app.app_context():
        yield


@pytest.fixture(autouse=True)
def jobs_root(tmp_path, monkeypatch):
    """작업 파일은 임시 DATABASE_PATH 아래에만 쓴다."""
    monkeypatch.setattr(admin, 'DATABASE_PATH', str(tmp_path))
    return tmp_path


class FakeClient:
    def __init__(self, nodes=None, connected=True, raise_on=None, results=None, info=None):
        self._nodes = nodes or {}
        self.connected = connected
        self.raise_on = raise_on or {}
        self.results = results or {}
        self.info = info if info is not None else {'bluetooth_enabled': True,
                                                   'fabric_index': 1}
        self.sent = []
        self.started = False
        self.stopped = False

    def ensure_started(self):
        self.started = True

    def stop(self, timeout=5.0):
        self.stopped = True

    def is_connected(self):
        return self.connected

    def wait_ready(self, timeout):
        return self.connected

    def server_info(self):
        return self.info

    def status(self):
        return {'last_error': None if self.connected else 'down'}

    def get_node(self, node_id):
        return self._nodes.get(int(node_id))

    def send_command(self, command, args=None, timeout=5.0):
        self.sent.append((command, args, timeout))
        if command in self.raise_on:
            raise self.raise_on[command]
        return self.results.get(command)

    def commands(self):
        return [c[0] for c in self.sent]

    def calls(self, command):
        return [c for c in self.sent if c[0] == command]


def use_client(monkeypatch, client):
    """utils_matter._open_client 가 항상 이 가짜를 돌려주게."""
    monkeypatch.setattr(utils_matter, '_open_client',
                        lambda: contextlib.nullcontext(client))
    return client


def inject_job_client(monkeypatch, client):
    """_run_new_device 가 만드는 MatterServerClient 를 가짜로 바꾼다."""
    from aot.devices import matter_client
    made = []

    def factory(**kwargs):
        made.append(kwargs)
        return client

    monkeypatch.setattr(matter_client, 'MatterServerClient', factory)
    return made


def make_job(job_id=None, **fields):
    job_id = job_id or 'a' * 32
    job = {'id': job_id, 'state': 'starting', 'user_id': 7, 'network': 'wifi',
           'created': time.time(), 'updated': time.time(),
           'node_id': None, 'error_category': None, 'error_details': None,
           'result': None}
    job.update(fields)
    admin._write_job(job)
    return job['id']


def job_text(job_id):
    with open(admin._job_path(job_id)) as f:
        return f.read()


def node_with(attrs=None, available=True, node_id=5):
    return {'node_id': node_id, 'available': available, 'attributes': attrs or {}}


# --------------------------------------------------------- validate_network

def test_wifi_ok(app_ctx):
    clean, err = admin.validate_network(WIFI)
    assert err is None
    assert clean == {'kind': 'wifi', 'ssid': 'FarmNet', 'password': SECRET_PW}


def test_default_kind_is_wifi_and_missing_ssid_rejected(app_ctx):
    for network in (None, {}, {'password': SECRET_PW}, {'ssid': '', 'password': SECRET_PW},
                    {'ssid': '   ', 'password': SECRET_PW}, {'ssid': 5, 'password': SECRET_PW}):
        clean, err = admin.validate_network(network)
        assert clean is None and err, network


@pytest.mark.parametrize('ssid, ok', [
    ('a' * 32, True),
    ('a' * 33, False),
    ('가' * 10, True),        # 30 bytes
    ('가' * 11, False),       # 33 bytes, but only 11 characters
    ('가' * 10 + 'ab', True),  # exactly 32 bytes
    ('가' * 10 + 'abc', False),
])
def test_ssid_limit_is_bytes_not_characters(app_ctx, ssid, ok):
    clean, err = admin.validate_network({'kind': 'wifi', 'ssid': ssid, 'password': SECRET_PW})
    assert (err is None) is ok
    assert (clean is not None) is ok


@pytest.mark.parametrize('password, ok', [
    ('1234567', False), ('12345678', True), ('x' * 64, True), ('x' * 65, False),
    ('', False), (None, False), (12345678, False),
])
def test_wifi_password_length(app_ctx, password, ok):
    clean, err = admin.validate_network({'kind': 'wifi', 'ssid': 'Net', 'password': password})
    assert (err is None) is ok


def test_wifi_password_is_not_stripped(app_ctx):
    clean, _ = admin.validate_network({'kind': 'wifi', 'ssid': 'Net', 'password': ' pass word '})
    assert clean['password'] == ' pass word '


def test_thread_dataset_ok_and_spaces_stripped(app_ctx):
    clean, err = admin.validate_network({'kind': 'thread', 'dataset': '  0e08 0000 0000 0001 \n'})
    assert err is None
    assert clean == {'kind': 'thread', 'dataset': '0e08000000000001'}


@pytest.mark.parametrize('dataset', [
    '0e0800000000000',        # 15 chars: odd and too short
    '0e080000000000010',      # 17 chars: odd length
    '0e0800000000',           # even but shorter than 16
    'zz' * 10,                # not hex
    '0e08000000000001gg',
    '', None,
    'ab' * 255,               # 510 chars: over 508
])
def test_thread_dataset_rejected(app_ctx, dataset):
    clean, err = admin.validate_network({'kind': 'thread', 'dataset': dataset})
    assert clean is None and err


def test_thread_dataset_upper_bound_ok(app_ctx):
    clean, err = admin.validate_network({'kind': 'thread', 'dataset': 'AB' * 254})
    assert err is None and len(clean['dataset']) == 508


def test_thread_dataset_non_string_is_a_validation_error_not_a_crash(app_ctx):
    clean, err = admin.validate_network({'kind': 'thread', 'dataset': 1234567890123456})
    assert clean is None and err


def test_network_none_kind(app_ctx):
    # secrets in the request are ignored for 'none'
    assert admin.validate_network({'kind': 'none', 'ssid': 'x', 'password': 'y'}) == \
        ({'kind': 'none'}, None)


def test_unknown_network_kind(app_ctx):
    clean, err = admin.validate_network({'kind': 'zigbee'})
    assert clean is None and err


# -------------------------------------------------------- start_new_device

class ThreadRecorder:
    instances = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}
        self.daemon, self.name, self.started = daemon, name, False
        ThreadRecorder.instances.append(self)

    def start(self):
        self.started = True


@pytest.fixture
def threads(monkeypatch):
    ThreadRecorder.instances = []
    monkeypatch.setattr(admin, 'threading', type('T', (), {'Thread': ThreadRecorder}))
    return ThreadRecorder.instances


def job_files(root):
    d = os.path.join(str(root), 'matter_jobs')
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def test_start_invalid_code_creates_nothing(app_ctx, monkeypatch, threads, jobs_root):
    client = use_client(monkeypatch, FakeClient())
    out = admin.start_new_device('12-34', WIFI)
    assert out['ok'] is False and out['job_id'] is None and out['error']
    assert threads == [] and job_files(jobs_root) == [] and client.sent == []


def test_start_invalid_network_creates_nothing(app_ctx, monkeypatch, threads, jobs_root):
    use_client(monkeypatch, FakeClient())
    out = admin.start_new_device(CODE, {'kind': 'wifi', 'ssid': 'x', 'password': 'short'})
    assert out['ok'] is False and out['error']
    assert threads == [] and job_files(jobs_root) == []


def test_start_server_down(app_ctx, monkeypatch, threads, jobs_root):
    use_client(monkeypatch, FakeClient(connected=False))
    out = admin.start_new_device(CODE, WIFI)
    assert out['ok'] is False and out['job_id'] is None
    assert out['error'] == utils_matter.error_message('not_connected')
    assert threads == [] and job_files(jobs_root) == []


def test_start_without_bluetooth_refuses_wifi_and_thread(app_ctx, monkeypatch, threads,
                                                         jobs_root):
    use_client(monkeypatch, FakeClient(info={'bluetooth_enabled': False}))
    for network in (WIFI, THREAD):
        out = admin.start_new_device(CODE, network)
        assert out['ok'] is False
        assert out['error'] == utils_matter.error_message('ble_unavailable')
    assert threads == [] and job_files(jobs_root) == []


def test_start_without_bluetooth_allows_network_none(app_ctx, monkeypatch, threads):
    use_client(monkeypatch, FakeClient(info={'bluetooth_enabled': False}))
    out = admin.start_new_device(CODE, {'kind': 'none'})
    assert out['ok'] is True and out['job_id']
    assert len(threads) == 1 and threads[0].started


def test_start_success_writes_secret_free_job_and_starts_thread(app_ctx, monkeypatch, threads,
                                                                jobs_root):
    use_client(monkeypatch, FakeClient())
    out = admin.start_new_device('3497-011-2332', WIFI, user_id=42)
    assert out['ok'] is True and out['error'] is None
    job_id = out['job_id']
    assert len(job_id) == 32

    files = job_files(jobs_root)
    assert files == [job_id + '.json']
    assert os.path.dirname(admin._job_path(job_id)) == os.path.join(str(jobs_root), 'matter_jobs')
    raw = job_text(job_id)
    assert SECRET_PW not in raw and 'password' not in raw and 'ssid' not in raw
    job = json.loads(raw)
    assert job['state'] == 'starting' and job['user_id'] == 42 and job['network'] == 'wifi'
    assert job['node_id'] is None and job['result'] is None

    (thread,) = threads
    assert thread.started and thread.daemon is True
    assert thread.target is admin._run_new_device
    assert thread.args[0] == job_id and thread.args[1] == CODE   # normalised code
    assert thread.args[2] == {'kind': 'wifi', 'ssid': 'FarmNet', 'password': SECRET_PW}


def test_start_thread_job_never_stores_dataset(app_ctx, monkeypatch, threads, jobs_root):
    use_client(monkeypatch, FakeClient())
    out = admin.start_new_device(CODE, THREAD)
    raw = job_text(out['job_id'])
    assert SECRET_DATASET not in raw and 'dataset' not in raw
    assert json.loads(raw)['network'] == 'thread'


def test_prune_removes_only_old_job_files(app_ctx, jobs_root):
    old = make_job('b' * 32)
    fresh = make_job('c' * 32)
    stale = os.path.getmtime(admin._job_path(old)) - admin.JOB_RETENTION_S - 60
    os.utime(admin._job_path(old), (stale, stale))
    admin._prune_jobs()
    assert job_files(jobs_root) == [fresh + '.json']


# ----------------------------------------------------------- job file edges

@pytest.mark.parametrize('job_id', [None, '', 'abc', '../../etc/passwd', 'A' * 32, 'g' * 32,
                                    'a' * 31, 'a' * 33, 12345])
def test_malformed_job_ids_have_no_path(job_id):
    assert admin._job_path(job_id) is None
    assert admin._read_job(job_id) is None


def test_corrupt_job_file_reads_as_none(app_ctx):
    job_id = make_job()
    with open(admin._job_path(job_id), 'w') as f:
        f.write('{not json')
    assert admin._read_job(job_id) is None
    assert admin.new_device_status(job_id)['state'] == 'unknown'


def test_update_job_of_missing_job_is_a_noop(app_ctx, jobs_root):
    admin._update_job('d' * 32, state='failed')
    assert job_files(jobs_root) == []


# ---------------------------------------------------------- _run_new_device

def run_job(monkeypatch, client, network, code=CODE, job_id=None):
    made = inject_job_client(monkeypatch, client)
    job_id = make_job(job_id)
    admin._run_new_device(job_id, code, network)
    return job_id, made


def read(job_id):
    return admin._read_job(job_id)


def test_wifi_success_sequence(app_ctx, monkeypatch):
    client = FakeClient(results={'commission_with_code': {'node_id': 12}})
    network = dict(WIFI)
    job_id, made = run_job(monkeypatch, client, network)

    cred_id = f'aot-{job_id[:12]}'
    assert [c for c in client.commands() if c != 'set_default_fabric_label'] == [
        'set_wifi_credentials', 'commission_with_code', 'remove_wifi_credentials']
    (_, set_args, _), = client.calls('set_wifi_credentials')
    assert set_args == {'ssid': 'FarmNet', 'credentials': SECRET_PW, 'id': cred_id}
    (_, args, timeout), = client.calls('commission_with_code')
    assert args == {'code': CODE, 'network_only': False, 'wifi_credentials_id': cred_id}
    assert timeout >= 300
    assert client.calls('remove_wifi_credentials')[0][1] == {'id': cred_id}

    job = read(job_id)
    assert job['state'] == 'commissioned' and job['node_id'] == 12
    assert SECRET_PW not in job_text(job_id)
    # the secret is wiped from the caller's dict and the client is stopped
    assert 'password' not in network
    assert client.started and client.stopped
    # keepalive must outlast the long commissioning call
    assert made[0]['ping_timeout'] > admin.NEW_DEVICE_TIMEOUT_S


def test_fabric_label_is_set_before_commissioning(app_ctx, monkeypatch):
    client = FakeClient(results={'commission_with_code': {'node_id': 12}})
    run_job(monkeypatch, client, dict(WIFI))
    cmds = client.commands()
    assert cmds.index('set_default_fabric_label') < cmds.index('commission_with_code')


def test_wifi_failure_still_removes_credentials(app_ctx, monkeypatch):
    err = MatterCommandError('commission_with_code', 1,
                             'Commissionee failed to connect to WiFi network')
    client = FakeClient(raise_on={'commission_with_code': err})
    job_id, _ = run_job(monkeypatch, client, dict(WIFI))
    job = read(job_id)
    assert job['state'] == 'failed' and job['error_category'] == 'wifi_failed'
    assert 'remove_wifi_credentials' in client.commands()
    assert client.commands()[-1] == 'remove_wifi_credentials'
    assert client.stopped


def test_unexpected_exception_still_removes_credentials(app_ctx, monkeypatch):
    client = FakeClient(raise_on={'commission_with_code': RuntimeError(f'boom {SECRET_PW}')})
    job_id, _ = run_job(monkeypatch, client, dict(WIFI))
    job = read(job_id)
    assert job['state'] == 'failed' and job['error_category'] == 'other'
    assert SECRET_PW not in job_text(job_id)       # only the exception type is kept
    assert job['error_details'] == 'RuntimeError'
    assert client.calls('remove_wifi_credentials')
    assert client.stopped


def test_error_details_are_scrubbed_of_password(app_ctx, monkeypatch):
    err = MatterCommandError('commission_with_code', 1,
                             f'WiFi network connect failed, credentials={SECRET_PW}')
    client = FakeClient(raise_on={'commission_with_code': err})
    job_id, _ = run_job(monkeypatch, client, dict(WIFI))
    text = job_text(job_id)
    assert SECRET_PW not in text
    assert '***' in read(job_id)['error_details']


def test_error_details_are_scrubbed_of_dataset(app_ctx, monkeypatch):
    err = MatterCommandError('commission_with_code', 1,
                             f'Thread network add failed for {SECRET_DATASET}')
    client = FakeClient(raise_on={'commission_with_code': err})
    job_id, _ = run_job(monkeypatch, client, dict(THREAD))
    job = read(job_id)
    assert SECRET_DATASET not in job_text(job_id)
    assert job['error_category'] == 'thread_failed'


def test_scrub_truncates_long_text(app_ctx):
    assert len(admin._scrub('x' * 1000, {})) == 300
    assert admin._scrub(None, {'password': 'abc'}) == ''


def test_thread_dataset_path(app_ctx, monkeypatch):
    client = FakeClient(results={'commission_with_code': {'node_id': 3}})
    network = dict(THREAD)
    job_id, _ = run_job(monkeypatch, client, network)
    cred_id = f'aot-{job_id[:12]}'
    assert [c for c in client.commands() if c != 'set_default_fabric_label'] == [
        'set_thread_dataset', 'commission_with_code', 'remove_thread_dataset']
    assert client.calls('set_thread_dataset')[0][1] == {'dataset': SECRET_DATASET, 'id': cred_id}
    assert client.calls('commission_with_code')[0][1] == {
        'code': CODE, 'network_only': False, 'thread_dataset_id': cred_id}
    assert client.calls('remove_thread_dataset')[0][1] == {'id': cred_id}
    assert not client.calls('set_wifi_credentials') and not client.calls('remove_wifi_credentials')
    assert SECRET_DATASET not in job_text(job_id)
    assert 'dataset' not in network


def test_thread_failure_removes_dataset(app_ctx, monkeypatch):
    client = FakeClient(raise_on={'commission_with_code': MatterCommandTimeout('x')})
    job_id, _ = run_job(monkeypatch, client, dict(THREAD))
    assert read(job_id)['error_category'] == 'timeout'
    assert client.calls('remove_thread_dataset')


def test_network_none_sends_no_credentials(app_ctx, monkeypatch):
    client = FakeClient(results={'commission_with_code': {'node_id': 9}})
    job_id, _ = run_job(monkeypatch, client, {'kind': 'none'})
    (_, args, timeout), = client.calls('commission_with_code')
    assert args == {'code': CODE, 'network_only': True}
    assert timeout >= 300
    assert [c for c in client.commands() if c != 'set_default_fabric_label'] == [
        'commission_with_code']
    assert read(job_id)['state'] == 'commissioned'


def test_server_not_ready_fails_without_commissioning(app_ctx, monkeypatch):
    client = FakeClient(connected=False)
    job_id, _ = run_job(monkeypatch, client, dict(WIFI))
    job = read(job_id)
    assert job['state'] == 'failed' and job['error_category'] == 'not_connected'
    assert client.sent == []          # no secret ever reached the server
    assert client.stopped


def test_no_device_returned_is_a_failure(app_ctx, monkeypatch):
    for result in (None, {}, {'node_id': None}, 'nope'):
        client = FakeClient(results={'commission_with_code': result})
        job_id, _ = run_job(monkeypatch, client, dict(WIFI), job_id='e' * 32)
        job = read(job_id)
        assert job['state'] == 'failed' and job['error_category'] == 'other', result
        assert client.calls('remove_wifi_credentials')


def test_failure_to_remove_credentials_does_not_hide_result_or_skip_stop(app_ctx, monkeypatch):
    client = FakeClient(
        results={'commission_with_code': {'node_id': 4}},
        raise_on={'remove_wifi_credentials': MatterCommandTimeout('x')})
    job_id, _ = run_job(monkeypatch, client, dict(WIFI))
    assert read(job_id)['state'] == 'commissioned'
    assert client.stopped


@pytest.mark.parametrize('network, set_cmd, remove_cmd', [
    (WIFI, 'set_wifi_credentials', 'remove_wifi_credentials'),
    (THREAD, 'set_thread_dataset', 'remove_thread_dataset'),
])
def test_credentials_removed_even_if_the_set_call_fails(app_ctx, monkeypatch, network,
                                                        set_cmd, remove_cmd):
    client = FakeClient(raise_on={set_cmd: MatterCommandTimeout('x')})
    job_id, _ = run_job(monkeypatch, client, dict(network))
    assert read(job_id)['state'] == 'failed'
    assert client.calls(remove_cmd)


# ------------------------------------------------------- new_device_status

def test_status_unknown_and_malformed_ids(app_ctx):
    for job_id in ('f' * 32, 'nope', '../x', None, ''):
        out = admin.new_device_status(job_id)
        assert out['state'] == 'unknown' and out['error']


def test_status_in_progress_has_no_error(app_ctx):
    job_id = make_job(state='commissioning')
    out = admin.new_device_status(job_id)
    assert out == {'state': 'commissioning', 'node_id': None, 'error': None, 'result': None}


def test_status_failed_uses_new_device_text(app_ctx):
    job_id = make_job(state='failed', error_category='timeout')
    out = admin.new_device_status(job_id)
    assert out['state'] == 'failed'
    assert out['error'] == utils_matter.error_message('timeout', '', new_device=True)
    assert out['error'] != utils_matter.error_message('timeout', '', new_device=False)


def test_status_failed_other_includes_details(app_ctx):
    job_id = make_job(state='failed', error_category='other', error_details='odd thing')
    assert 'odd thing' in admin.new_device_status(job_id)['error']


def test_status_failed_without_category_falls_back_to_other(app_ctx):
    job_id = make_job(state='failed', error_category=None)
    assert admin.new_device_status(job_id)['error']


@pytest.mark.parametrize('state', ['starting', 'commissioning'])
def test_stale_unfinished_job_fails_with_timeout(app_ctx, state):
    job_id = make_job(state=state, created=time.time() - admin.JOB_STALE_S - 5)
    out = admin.new_device_status(job_id)
    assert out['state'] == 'failed'
    assert read(job_id)['error_category'] == 'timeout'
    assert out['error'] == utils_matter.error_message('timeout', '', new_device=True)


def test_recent_unfinished_job_is_not_stale(app_ctx):
    job_id = make_job(state='commissioning', created=time.time() - admin.JOB_STALE_S + 60)
    assert admin.new_device_status(job_id)['state'] == 'commissioning'


def test_stale_window_outlasts_the_commission_timeout():
    assert admin.JOB_STALE_S > admin.NEW_DEVICE_TIMEOUT_S


def register_env(monkeypatch, node=None, reg=None, ready=True):
    """_register 가 쓰는 서버·등록 함수를 가짜로."""
    node = node if node is not None else {'node_id': 12, 'available': True, 'attributes': {}}
    client = FakeClient(nodes={12: node} if node else {}, connected=ready)
    use_client(monkeypatch, client)
    monkeypatch.setattr(matter_clusters, 'discover_channels',
                        lambda n: (['in1', 'in2'], ['out1']))
    calls = []

    def fake_register(n):
        calls.append(n)
        return reg or {'device_id': 'dev-1', 'rebound': False, 'error': None, 'warnings': ['w']}

    monkeypatch.setattr(utils_matter, 'register_node', fake_register)
    return client, calls


def test_commissioned_job_is_registered_and_done(app_ctx, monkeypatch, jobs_root):
    _, calls = register_env(monkeypatch)
    job_id = make_job(state='commissioned', node_id=12)
    out = admin.new_device_status(job_id)
    assert out['state'] == 'done' and out['error'] is None and out['node_id'] == 12
    assert out['result'] == {'device_id': 'dev-1', 'rebound': False, 'sensor_count': 2,
                             'switch_count': 1, 'warnings': ['w']}
    assert len(calls) == 1 and calls[0]['node_id'] == 12
    # 잠금 파일은 지우지 않는다(지웠다 다시 만들면 두 요청이 함께 잡을 수 있다).
    assert sorted(job_files(jobs_root)) == [job_id + '.json', job_id + '.json.lock']


def test_registration_happens_only_once(app_ctx, monkeypatch):
    _, calls = register_env(monkeypatch)
    job_id = make_job(state='commissioned', node_id=12)
    first = admin.new_device_status(job_id)
    second = admin.new_device_status(job_id)
    assert first['state'] == second['state'] == 'done'
    assert second['result'] == first['result']
    assert len(calls) == 1


def test_already_done_job_is_never_registered_again(app_ctx, monkeypatch):
    _, calls = register_env(monkeypatch)
    job_id = make_job(state='done', node_id=12, result={'device_id': 'x'})
    assert admin.new_device_status(job_id)['state'] == 'done'
    assert calls == []


def test_register_error_marks_job_failed(app_ctx, monkeypatch):
    register_env(monkeypatch, reg={'device_id': None, 'rebound': False,
                                   'error': 'db locked', 'warnings': []})
    job_id = make_job(state='commissioned', node_id=12)
    out = admin.new_device_status(job_id)
    assert out['state'] == 'failed' and 'db locked' in out['error']
    assert out['result']['sensor_count'] == 2
    assert read(job_id)['error_category'] == 'other'


def test_register_with_server_down_retries_on_next_poll(app_ctx, monkeypatch):
    client, calls = register_env(monkeypatch, ready=False)
    job_id = make_job(state='commissioned', node_id=12)
    assert admin.new_device_status(job_id)['state'] == 'commissioned'
    assert calls == []
    client.connected = True
    assert admin.new_device_status(job_id)['state'] == 'done'
    assert len(calls) == 1


def test_register_with_node_missing_fails(app_ctx, monkeypatch):
    client = FakeClient(nodes={})
    use_client(monkeypatch, client)
    calls = []
    monkeypatch.setattr(utils_matter, 'register_node', lambda n: calls.append(n))
    job_id = make_job(state='commissioned', node_id=12)
    out = admin.new_device_status(job_id)
    assert out['state'] == 'failed' and calls == []


# -------------------------------------------------------- open_share_window

FABRIC_OK = {'0/62/2': 5, '0/62/3': 2}


def share_client(monkeypatch, node, **kw):
    results = {'open_commissioning_window': {
        'setup_manual_code': '36217551633', 'setup_qr_code': 'MT:ABC'}}
    return use_client(monkeypatch, FakeClient(
        nodes={5: node} if node is not None else {}, results=results, **kw))


@pytest.mark.parametrize('asked, sent', [
    (60, 180), (179, 180), (180, 180), (600, 600), (900, 900), (5000, 900),
    ('300', 300), ('x', 900), (None, 900), (-5, 180),
])
def test_share_timeout_is_clamped(app_ctx, monkeypatch, asked, sent):
    client = share_client(monkeypatch, node_with(FABRIC_OK))
    out = admin.open_share_window(5, asked)
    assert out['ok'] is True and out['expires_in'] == sent
    (_, args, _), = client.calls('open_commissioning_window')
    assert args == {'node_id': 5, 'timeout': sent}


def test_share_default_timeout(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK))
    assert admin.open_share_window(5)['expires_in'] == 900
    assert client.sent[0][1]['timeout'] == 900


def test_share_success_returns_codes(app_ctx, monkeypatch):
    share_client(monkeypatch, node_with(FABRIC_OK))
    out = admin.open_share_window('5', 300)
    assert out == {'ok': True, 'error': None, 'manual_code': '36217551633',
                   'qr_code': 'MT:ABC', 'expires_in': 300}


def test_share_success_without_codes_in_reply(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK))
    client.results['open_commissioning_window'] = None
    out = admin.open_share_window(5)
    assert out['ok'] is True and out['manual_code'] is None and out['qr_code'] is None


def test_share_server_down(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK), connected=False)
    out = admin.open_share_window(5)
    assert out['ok'] is False and out['error'] == utils_matter.error_message('not_connected')
    assert client.sent == []


def test_share_missing_node(app_ctx, monkeypatch):
    client = share_client(monkeypatch, None)
    out = admin.open_share_window(5)
    assert out['ok'] is False and out['error'] and client.sent == []


def test_share_unavailable_node(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK, available=False))
    out = admin.open_share_window(5)
    assert out['ok'] is False and 'not reachable' in out['error'] and client.sent == []


@pytest.mark.parametrize('supported, used', [(62, 62), (3, 4), (2, 2)])
def test_share_fabric_full(app_ctx, monkeypatch, supported, used):
    client = share_client(monkeypatch, node_with({'0/62/2': supported, '0/62/3': used}))
    out = admin.open_share_window(5)
    assert out['ok'] is False
    assert out['error'] == utils_matter.error_message('fabric_full')
    assert client.sent == []


def test_share_fabric_numbers_unknown_still_tries(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with({}))
    assert admin.open_share_window(5)['ok'] is True
    assert client.calls('open_commissioning_window')


def test_share_command_error(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK))
    client.raise_on['open_commissioning_window'] = MatterCommandError(
        'open_commissioning_window', 1, 'Busy')
    out = admin.open_share_window(5)
    assert out['ok'] is False and 'Busy' in out['error']
    assert out['manual_code'] is None and out['qr_code'] is None


def test_share_timeout_error(app_ctx, monkeypatch):
    client = share_client(monkeypatch, node_with(FABRIC_OK))
    client.raise_on['open_commissioning_window'] = MatterCommandTimeout('slow')
    out = admin.open_share_window(5)
    assert out['ok'] is False and out['error']


# ------------------------------------------------------ close_share_window

def test_close_share_window_sends_revoke(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient())
    assert admin.close_share_window('5') == {'ok': True, 'error': None}
    (_, args, _), = client.sent
    assert client.sent[0][0] == 'device_command'
    assert args == {'node_id': 5, 'endpoint_id': 0, 'cluster_id': 60,
                    'command_name': 'RevokeCommissioning', 'payload': {}}


@pytest.mark.parametrize('details', ['WindowNotOpen', 'Command failed: Window Not Open (4)',
                                     'status=windownotopen'])
def test_close_window_not_open_counts_as_ok(app_ctx, monkeypatch, details):
    use_client(monkeypatch, FakeClient(
        raise_on={'device_command': MatterCommandError('device_command', 1, details)}))
    assert admin.close_share_window(5) == {'ok': True, 'error': None}


def test_close_other_error_is_reported(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(
        raise_on={'device_command': MatterCommandError('device_command', 1, 'Busy')}))
    out = admin.close_share_window(5)
    assert out['ok'] is False and 'Busy' in out['error']


def test_close_server_down(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(connected=False))
    out = admin.close_share_window(5)
    assert out['ok'] is False and client.sent == []


# ------------------------------------------------------------ list_fabrics

ROWS = [
    {'fabric_index': 1, 'fabric_label': 'AoT', 'vendor_id': 65521, 'vendor_name': 'AoT'},
    {'fabric_index': 2, 'fabric_label': None, 'vendor_id': 4874, 'vendor_name': None},
]


def test_list_fabrics_marks_own_and_maps_fields(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(
        # AoT 의 자리는 장치가 매긴 CurrentFabricIndex(0/62/5) — 서버의
        # fabric_index(서버 표의 자리, 보통 1)가 아니다.
        nodes={5: node_with({'0/62/2': 5, '0/62/3': 2, '0/62/5': 2})},
        results={'get_matter_fabrics': ROWS}, info={'fabric_index': 1}))
    out = admin.list_fabrics(5)
    assert out['ok'] is True and out['error'] is None
    assert out['supported'] == 5 and out['used'] == 2
    assert out['fabrics'] == [
        {'fabric_index': 1, 'label': 'AoT', 'vendor_id': 65521, 'vendor_name': 'AoT',
         'own': False},
        {'fabric_index': 2, 'label': '', 'vendor_id': 4874, 'vendor_name': '', 'own': True},
    ]
    assert client.calls('get_matter_fabrics')[0][1] == {'node_id': 5}


def test_list_fabrics_unknown_own_index_marks_none_own(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(nodes={5: node_with()},
                                       results={'get_matter_fabrics': ROWS}, info={}))
    out = admin.list_fabrics(5)
    assert [f['own'] for f in out['fabrics']] == [False, False]
    assert out['supported'] is None and out['used'] is None


def test_list_fabrics_empty_or_odd_reply(app_ctx, monkeypatch):
    for reply in (None, [], {'x': 1}):
        use_client(monkeypatch, FakeClient(nodes={5: node_with()},
                                           results={'get_matter_fabrics': reply}))
        out = admin.list_fabrics(5)
        assert out['ok'] is True and out['fabrics'] == []


def test_list_fabrics_node_missing_from_cache_still_lists(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(nodes={}, results={'get_matter_fabrics': ROWS}))
    out = admin.list_fabrics(5)
    assert out['ok'] is True and len(out['fabrics']) == 2 and out['supported'] is None


def test_list_fabrics_error(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(
        raise_on={'get_matter_fabrics': MatterCommandError('c', 1, 'Unreachable')}))
    out = admin.list_fabrics(5)
    assert out['ok'] is False and 'Unreachable' in out['error'] and out['fabrics'] == []


def test_list_fabrics_server_down(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(connected=False))
    out = admin.list_fabrics(5)
    assert out['ok'] is False and client.sent == []


# ------------------------------------------------------ remove_other_fabric

def test_remove_other_fabric_success(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(nodes={5: node_with({'0/62/5': 1})},
                                                info={'fabric_index': 1}, results={
        'get_matter_fabrics': [{'fabric_index': 1, 'fabric_label': 'AoT'}]}))
    assert admin.remove_other_fabric('5', '2') == {'ok': True, 'error': None}
    assert client.sent[0] == ('remove_matter_fabric', {'node_id': 5, 'fabric_index': 2}, 20.0)
    assert client.sent[1][0] == 'get_matter_fabrics'


def test_remove_other_fabric_verifies_the_device_list(app_ctx, monkeypatch):
    """서버는 지우지 못해도 {} 를 돌려준다(실측) — 장치 목록으로 확인한다."""
    use_client(monkeypatch, FakeClient(nodes={5: node_with({'0/62/5': 1})},
                                       info={'fabric_index': 1}, results={
        'get_matter_fabrics': [{'fabric_index': 1}, {'fabric_index': 2}]}))
    out = admin.remove_other_fabric(5, 2)
    assert out['ok'] is False and 'did not remove' in out['error']


def test_close_share_window_when_none_open_is_ok(app_ctx, monkeypatch):
    """열린 창이 없으면 서버는 'cluster code 4' 로 답한다(실측) — 실패가 아니다."""
    from aot.devices.matter_client import MatterCommandError
    use_client(monkeypatch, FakeClient(raise_on={'device_command': MatterCommandError(
        'device_command', 0, 'Failure (code 1; cluster code 4)')}))
    assert admin.close_share_window(5) == {'ok': True, 'error': None}


def test_remove_own_fabric_is_refused(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(nodes={5: node_with({'0/62/5': 1})},
                                                info={'fabric_index': 1}))
    for index in (1, '1'):
        out = admin.remove_other_fabric(5, index)
        assert out['ok'] is False and 'own connection' in out['error']
    assert client.sent == []


def test_remove_fabric_refused_when_own_index_unknown(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(nodes={5: node_with()}, info={'fabric_index': 3}))
    out = admin.remove_other_fabric(5, 2)
    assert out['ok'] is False and client.sent == []


@pytest.mark.parametrize('index', ['x', None, '', [], {}])
def test_remove_fabric_non_int_index(app_ctx, monkeypatch, index):
    client = use_client(monkeypatch, FakeClient())
    out = admin.remove_other_fabric(5, index)
    assert out['ok'] is False and out['error'] and client.sent == []


def test_remove_fabric_command_error(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(
        nodes={5: node_with({'0/62/5': 1})},
        raise_on={'remove_matter_fabric': MatterCommandError('c', 1, 'Nope')}))
    out = admin.remove_other_fabric(5, 2)
    assert out['ok'] is False and 'Nope' in out['error']


def test_remove_fabric_server_down(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(connected=False))
    assert admin.remove_other_fabric(5, 2)['ok'] is False
    assert client.sent == []


# ------------------------------------------------------------ update_state

def test_update_state_maps_attributes():
    node = node_with({'0/42/2': 4, '0/42/3': 37, '0/40/10': '1.2.3'})
    assert admin.update_state(node) == {'version': '1.2.3', 'state': 'downloading',
                                        'progress': 37}


@pytest.mark.parametrize('code, name', list(admin.OTA_STATE_NAMES.items()))
def test_update_state_names(code, name):
    assert admin.update_state(node_with({'0/42/2': code}))['state'] == name


def test_update_state_missing_attributes():
    expected = {'version': '', 'state': None, 'progress': None}
    assert admin.update_state(node_with({})) == expected
    assert admin.update_state({'node_id': 1}) == expected
    assert admin.update_state(None) == expected


def test_update_state_unknown_or_non_int_state():
    assert admin.update_state(node_with({'0/42/2': 99}))['state'] is None
    assert admin.update_state(node_with({'0/42/2': 'idle'}))['state'] is None


# ------------------------------------------------------------ check_update

def update_client(monkeypatch, result=None, **kw):
    return use_client(monkeypatch, FakeClient(
        nodes={5: node_with({'0/42/2': 1})}, results={'check_node_update': result}, **kw))


def test_check_update_none_result(app_ctx, monkeypatch):
    client = update_client(monkeypatch, None)
    assert admin.check_update('5') == {'ok': True, 'error': None, 'update': None}
    assert client.calls('check_node_update')[0][1] == {'node_id': 5}


@pytest.mark.parametrize('source, certified', [
    ('main-net-dcl', True), ('test-net-dcl', False), ('local', False), ('', False), (None, False)])
def test_check_update_certified_only_from_main_net(app_ctx, monkeypatch, source, certified):
    update_client(monkeypatch, {
        'software_version': 7, 'software_version_string': '2.0.0',
        'release_notes_url': 'https://x/notes', 'update_source': source})
    out = admin.check_update(5)
    assert out['ok'] is True
    assert out['update'] == {'version': 7, 'version_string': '2.0.0',
                             'release_notes_url': 'https://x/notes',
                             'source': source or '', 'certified': certified}


def test_check_update_version_string_falls_back_to_number(app_ctx, monkeypatch):
    update_client(monkeypatch, {'software_version': 7, 'update_source': 'main-net-dcl'})
    update = admin.check_update(5)['update']
    assert update['version_string'] == '7' and update['release_notes_url'] == ''


def test_check_update_ota_disabled(app_ctx, monkeypatch):
    err = MatterCommandError('check_node_update', admin.ERR_OTA_DISABLED, 'OTA disabled')
    use_client(monkeypatch, FakeClient(raise_on={'check_node_update': err}))
    out = admin.check_update(5)
    assert out['ok'] is False and out['update'] is None
    assert 'turned off' in out['error']


def test_check_update_other_command_error(app_ctx, monkeypatch):
    use_client(monkeypatch, FakeClient(raise_on={
        'check_node_update': MatterCommandError('c', 1, 'Node unreachable')}))
    out = admin.check_update(5)
    assert out['ok'] is False and 'Node unreachable' in out['error']


def test_check_update_timeout_and_not_connected_errors(app_ctx, monkeypatch):
    for err, category in ((MatterCommandTimeout('x'), 'timeout'),
                          (MatterNotConnected('x'), 'not_connected')):
        use_client(monkeypatch, FakeClient(raise_on={'check_node_update': err}))
        out = admin.check_update(5)
        assert out['ok'] is False and out['update'] is None
        assert out['error'] == utils_matter.error_message(category)


def test_check_update_server_down(app_ctx, monkeypatch):
    client = update_client(monkeypatch, None, connected=False)
    out = admin.check_update(5)
    assert out['ok'] is False and out['update'] is None and client.sent == []


# ------------------------------------------------------------ start_update

CERTIFIED = {'software_version': 7, 'software_version_string': '2.0.0',
             'update_source': 'main-net-dcl'}


def start_client(monkeypatch, check=CERTIFIED, node=None, **kw):
    node = node if node is not None else node_with({'0/42/2': 1})
    return use_client(monkeypatch, FakeClient(
        nodes={5: node} if node else {}, results={'check_node_update': check}, **kw))


def sent_update(client):
    return client.calls('update_node')


def test_start_update_success(app_ctx, monkeypatch):
    client = start_client(monkeypatch)
    assert admin.start_update('5', '7') == {'ok': True, 'error': None}
    assert [c[:2] for c in sent_update(client)] == [
        ('update_node', {'node_id': 5, 'software_version': 7})]


def test_start_update_unknown_ota_state_is_allowed(app_ctx, monkeypatch):
    # cache has no OTA state yet: nothing says the device is busy
    client = start_client(monkeypatch, node=node_with({}))
    assert admin.start_update(5, 7)['ok'] is True
    assert sent_update(client)


def test_start_update_refuses_when_no_update(app_ctx, monkeypatch):
    client = start_client(monkeypatch, check=None)
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'No update' in out['error'] and not sent_update(client)


def test_start_update_refuses_uncertified(app_ctx, monkeypatch):
    client = start_client(monkeypatch, check=dict(CERTIFIED, update_source='test-net-dcl'))
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'certified' in out['error'] and not sent_update(client)


def test_start_update_refuses_version_mismatch(app_ctx, monkeypatch):
    client = start_client(monkeypatch)
    out = admin.start_update(5, 6)
    assert out['ok'] is False and 'changed' in out['error'] and not sent_update(client)


def test_start_update_refuses_unavailable_node(app_ctx, monkeypatch):
    client = start_client(monkeypatch, node=node_with({'0/42/2': 1}, available=False))
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'not reachable' in out['error'] and not sent_update(client)


def test_start_update_refuses_missing_node(app_ctx, monkeypatch):
    client = start_client(monkeypatch, node=False)
    out = admin.start_update(5, 7)
    assert out['ok'] is False and not sent_update(client)


@pytest.mark.parametrize('state', [2, 3, 4, 5, 6, 7, 8])
def test_start_update_refuses_non_idle_ota_state(app_ctx, monkeypatch, state):
    client = start_client(monkeypatch, node=node_with({'0/42/2': state}))
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'busy' in out['error'] and not sent_update(client)


def test_start_update_passes_through_check_error(app_ctx, monkeypatch):
    client = use_client(monkeypatch, FakeClient(raise_on={
        'check_node_update': MatterCommandError('c', admin.ERR_OTA_DISABLED, 'off')}))
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'turned off' in out['error'] and not sent_update(client)


def test_start_update_command_error(app_ctx, monkeypatch):
    start_client(monkeypatch, raise_on={'update_node': MatterCommandError('c', 1, 'Rejected')})
    out = admin.start_update(5, 7)
    assert out['ok'] is False and 'Rejected' in out['error']


def test_start_update_timeout_error(app_ctx, monkeypatch):
    start_client(monkeypatch, raise_on={'update_node': MatterCommandTimeout('x')})
    out = admin.start_update(5, 7)
    assert out['ok'] is False and out['error'] == utils_matter.error_message('timeout')


def test_start_update_server_down_after_check(app_ctx, monkeypatch):
    # check_update already fails on the dead server, so nothing is sent
    client = start_client(monkeypatch, connected=False)
    out = admin.start_update(5, 7)
    assert out['ok'] is False and not sent_update(client)



def test_network_must_be_an_object(app_ctx):
    clean, err = admin.validate_network(['wifi'])
    assert clean is None and err


def test_start_update_refuses_unreadable_version(app_ctx, monkeypatch):
    """사람이 확인한 버전이 아니면 '지금 있는 것'으로 대신 설치하지 않는다."""
    monkeypatch.setattr(admin, 'check_update', lambda node_id: {
        'ok': True, 'error': None, 'update': {'version': 7, 'version_string': '1.7',
                                              'release_notes_url': '', 'source': 'main-net-dcl',
                                              'certified': True}})
    called = []
    monkeypatch.setattr(admin.utils_matter, '_open_client', lambda: called.append(1))
    out = admin.start_update(5, 'latest')
    assert not out['ok'] and called == []



def test_own_fabric_is_the_devices_current_fabric_index_not_the_servers(app_ctx, monkeypatch):
    """구글에서 공유받은 장치: 구글이 1, AoT 가 2. 서버의 fabric_index(1)를 쓰면
    구글을 'AoT' 로 표시하고 AoT 자신을 지우게 된다(검토에서 확인한 결함)."""
    client = use_client(monkeypatch, FakeClient(
        nodes={5: node_with({'0/62/5': 2})}, info={'fabric_index': 1},
        results={'get_matter_fabrics': [{'fabric_index': 2}]}))   # 해제 뒤 남은 목록
    out = admin.remove_other_fabric(5, 2)          # AoT 자신
    assert out['ok'] is False and 'own connection' in out['error']
    assert client.sent == [] or client.sent[0][0] != 'remove_matter_fabric'
    out = admin.remove_other_fabric(5, 1)          # 구글
    assert out['ok'] is True


def test_sweep_removes_leftover_credentials_but_not_live_ones(app_ctx, monkeypatch, jobs_root):
    """작업 스레드가 죽어 남긴 aot-… 자격증명(서버에 평문)을 지운다. 살아 있는
    작업의 것과 aot- 가 아닌 것은 건드리지 않는다."""
    live = make_job(state='commissioning')
    admin._update_job(live, cred_id=admin._cred_id(live))
    client = FakeClient(results={'get_all_credentials': {
        'wifi': [{'id': 'default'}, {'id': 'aot-deadbeef0000'}, {'id': admin._cred_id(live)}],
        'thread': [{'id': 'aot-cafebabe0000'}]}})
    assert admin.sweep_stale_credentials(client) == 2
    removed = [(c, a['id']) for c, a, _t in client.sent if c.startswith('remove_')]
    assert removed == [('remove_wifi_credentials', 'aot-deadbeef0000'),
                       ('remove_thread_dataset', 'aot-cafebabe0000')]
