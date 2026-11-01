# coding=utf-8
"""설정 > Matter 서비스 계층(aot/aot_flask/utils/utils_matter.py) 검사.

DB·Matter 서버 없이 가짜 클라이언트로 돈다. 지키는 것:
  - 페어링 코드: 사람이 붙여 넣는 구분자(공백·하이픈)를 지우고, 11·21자리
    숫자나 MT: 코드만 받는다. 아니면 서버에 보내지 않는다.
  - 커미셔닝은 network_only 로, 넉넉한 시간 제한으로 보낸다.
  - 서버 오류를 설계 §5-4 의 안내로 바꾼다(코드 만료·발견 실패·자리 없음·
    인증 실패·서버 미응답).
  - 노드 제거: 장치가 응답하지 않던 경우에는 성공이되 "장치에 AoT 가 남아
    있다"는 경고를 준다. 이미 없는 노드는 성공으로 본다.
  - 장치 삭제 훅은 서버가 없어도 삭제를 막지 않는다(경고만).
"""
import contextlib
from types import SimpleNamespace

import pytest

flask = pytest.importorskip('flask')
from flask_babel import Babel  # noqa: E402

from aot.aot_flask.utils import utils_matter  # noqa: E402
from aot.devices.matter_client import (MatterCommandError, MatterCommandTimeout,  # noqa: E402
                                       MatterNotConnected)


@pytest.fixture
def app_ctx():
    app = flask.Flask(__name__)
    Babel(app)
    with app.app_context():
        yield


class FakeClient:
    def __init__(self, nodes=None, connected=True, raise_on=None, result=None):
        self._nodes = nodes or {}
        self.connected = connected
        self.raise_on = raise_on or {}
        self.result = result
        self.sent = []

    def ensure_started(self):
        pass

    def is_connected(self):
        return self.connected

    def wait_ready(self, timeout):
        return self.connected

    def status(self):
        return {'last_error': None if self.connected else 'down'}

    def get_node(self, node_id):
        return self._nodes.get(int(node_id))

    def nodes(self):
        return dict(self._nodes)

    def send_command(self, command, args=None, timeout=5.0):
        self.sent.append((command, args, timeout))
        if command in self.raise_on:
            raise self.raise_on[command]
        return self.result


@pytest.mark.parametrize('raw, expected', [
    ('3497-011-2332', '34970112332'),
    (' 3497 0112 332 ', '34970112332'),
    ('749701123365521327694', '749701123365521327694'),
    ('MT:Y.K9042C00KA0648G00', 'MT:Y.K9042C00KA0648G00'),
    ('mt:y.k9042c00ka0648g00', 'MT:Y.K9042C00KA0648G00'),
    ('1234', None),
    ('3497011233a', None),
    ('', None),
    (None, None),
])
def test_normalize_code(raw, expected):
    assert utils_matter.normalize_code(raw) == expected


def test_invalid_code_never_reaches_server(app_ctx, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    result = utils_matter.commission('12-34')
    assert not result['ok'] and result['error']
    assert client.sent == []


def test_commission_is_network_only_with_long_timeout(app_ctx, monkeypatch):
    client = FakeClient(raise_on={'commission_with_code': MatterCommandError(
        'commission_with_code', 1, 'PASE session establishment timed out')})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    result = utils_matter.commission('3497-011-2332')
    command, args, timeout = client.sent[-1]
    assert command == 'commission_with_code'
    assert args == {'code': '34970112332', 'network_only': True}
    assert timeout >= 60
    assert not result['ok'] and 'share it again' in result['error']


def test_commission_server_down(app_ctx, monkeypatch):
    client = FakeClient(connected=False)
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    result = utils_matter.commission('34970112332')
    assert not result['ok'] and 'not reachable' in result['error']
    assert client.sent == []


@pytest.mark.parametrize('err, phrase', [
    (MatterNotConnected('x'), 'not reachable'),
    (MatterCommandTimeout('x'), 'did not finish joining'),
    (MatterCommandError('c', 8, 'bad code'), 'not valid'),
    (MatterCommandError('c', 1, 'Fabric table full (NoSpace)'), 'no free slot'),
    (MatterCommandError('c', 1, 'Device attestation failed'), 'certified'),
    (MatterCommandError('c', 1, 'No device discovered for discriminator'), 'not found on the network'),
    (MatterCommandError('c', 1, 'something odd'), 'something odd'),
])
def test_friendly_errors(app_ctx, err, phrase):
    assert phrase in utils_matter._friendly_error(err)


def test_remove_reachable_node(app_ctx, monkeypatch):
    client = FakeClient(nodes={5: {'node_id': 5, 'available': True}})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    assert utils_matter.remove_node(5) == (True, None)
    assert client.sent[0][:2] == ('remove_node', {'node_id': 5})


def test_remove_unreachable_node_warns_fabric_left_on_device(app_ctx, monkeypatch):
    client = FakeClient(nodes={5: {'node_id': 5, 'available': False}})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    ok, warning = utils_matter.remove_node(5)
    assert ok and 'still lists AoT' in warning


def test_remove_missing_node_is_success(app_ctx, monkeypatch):
    client = FakeClient(raise_on={'remove_node': MatterCommandError('remove_node', 5, 'no node')})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    assert utils_matter.remove_node(9) == (True, None)


def test_delete_hook_never_blocks_and_warns(app_ctx, monkeypatch):
    client = FakeClient(connected=False)
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    deleted = []
    monkeypatch.setattr(utils_matter, '_delete_children',
                        lambda device_id, messages: deleted.append(device_id))
    monkeypatch.setattr(utils_matter, '_children_in_use', lambda device_id: [])
    row = SimpleNamespace(device='device_matter_node', unique_id='dev-1',
                          custom_options='{"node_id": 5}')
    messages = {'warning': [], 'error': []}
    utils_matter.on_device_delete(row, messages)
    assert messages['error'] == []
    assert messages['warning'] and 'Settings > Matter' in messages['warning'][0]
    assert deleted == ['dev-1']


def test_delete_hook_ignores_other_devices(app_ctx, monkeypatch):
    called = []
    monkeypatch.setattr(utils_matter, 'remove_node', lambda n: called.append(n))
    monkeypatch.setattr(utils_matter, '_delete_children', lambda *a: called.append(a))
    utils_matter.on_device_delete(
        SimpleNamespace(device='device_modbus_plc_generic', unique_id='x', custom_options='{}'),
        {'warning': []})
    assert called == []


# --- E2E 에서 나온 회귀 (2026-10-09, 가상 장치 + 전체 스택) -----------------

@pytest.mark.parametrize('details', [
    'Commission failed: Invalid checksum',
    'Invalid pairing code',
])
def test_bad_code_from_server_gets_friendly_text(app_ctx, details):
    """서버는 체크섬 오류를 error_code 1 로 돌려준다(8 이 아니다)."""
    text = utils_matter._friendly_error(MatterCommandError('commission_with_code', 1, details))
    assert 'not valid' in text


def test_fabric_label_set_before_commissioning(app_ctx, monkeypatch):
    """안 하면 다른 생태계 앱에 AoT 연결이 'HomeAssistant' 로 보인다."""
    client = FakeClient(raise_on={'commission_with_code': MatterCommandError('c', 1, 'x')})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    utils_matter.commission('34970112332')
    assert [c[0] for c in client.sent] == ['set_default_fabric_label', 'commission_with_code']
    assert client.sent[0][1] == {'label': 'AoT'}


def test_fabric_label_failure_does_not_stop_commissioning(app_ctx, monkeypatch):
    client = FakeClient(raise_on={
        'set_default_fabric_label': MatterCommandError('set_default_fabric_label', 9, 'unknown'),
        'commission_with_code': MatterCommandError('c', 1, 'x')})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    utils_matter.commission('34970112332')
    assert client.sent[-1][0] == 'commission_with_code'


def test_new_outputs_are_reloaded_in_daemon_after_creation(app_ctx, monkeypatch):
    """output_add() 가 node_id·채널이 쓰이기 전에 데몬에 등록해 'Node ID must be
    set' 으로 스위치가 안 되던 버그. 만든 뒤 Modify 로 다시 읽혀야 한다."""
    import contextlib
    from aot.aot_flask.utils import utils_function, utils_output, utils_controller

    @contextlib.contextmanager
    def fake_pending(node):
        yield {'inputs': [], 'outputs': ['out-1']}

    reloaded, activated = [], []
    monkeypatch.setattr(utils_matter.matter_onboarding, 'pending_node', fake_pending)
    monkeypatch.setattr(utils_function, 'function_add',
                        lambda form, tab_id=None: ({'error': []}, None, [], '', 'dev-1'))
    monkeypatch.setattr(utils_output, 'manipulate_output',
                        lambda action, oid: reloaded.append((action, oid)) or {'error': []})
    monkeypatch.setattr(utils_controller, 'controller_activate',
                        lambda did: activated.append(did) or {'error': []})
    monkeypatch.setattr(utils_matter, '_device_tab_id', lambda: None)

    class _Q:
        def filter_by(self, **k):
            return self

        def first(self):
            return None

    monkeypatch.setattr(utils_matter.Output, 'query', _Q(), raising=False)
    plug = {'node_id': 5, 'attributes': {'1/29/1': [6, 29], '1/6/0': False}}
    out = utils_matter._create_device(plug)
    assert out['device_id'] == 'dev-1' and out['error'] is None
    assert reloaded == [('Modify', 'out-1')]
    assert activated == ['dev-1']       # switch-only devices are activated too


def test_devices_whose_node_vanished_are_listed(app_ctx, monkeypatch):
    client = FakeClient(nodes={5: {'node_id': 5, 'available': True, 'attributes': {}}})
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    dev5 = SimpleNamespace(unique_id='d5', name='Plug', custom_options='{"node_id": 5}')
    dev9 = SimpleNamespace(unique_id='d9', name='Sensor',
                           custom_options='{"node_id": 9, "product_name": "Combo"}')
    monkeypatch.setattr(utils_matter, '_matter_devices', lambda: {5: dev5, 9: dev9})
    rows = {r['node_id']: r for r in utils_matter.list_nodes()}
    assert rows[5]['missing'] is False and rows[5]['device_id'] == 'd5'
    assert rows[9]['missing'] is True and rows[9]['device_id'] == 'd9'
    assert rows[9]['product_name'] == 'Combo' and rows[9]['available'] is False


# --- 검토(Opus) 지적 회귀 ---------------------------------------------------

def test_delete_refused_while_children_are_in_use(app_ctx, monkeypatch):
    """Fabric 을 떠나는 것은 되돌릴 수 없다 — 하위가 시퀀스 등에 쓰이면 아무것도
    하지 않고 거절한다(노드 제거도, 하위 삭제도 없이)."""
    called = []
    monkeypatch.setattr(utils_matter, '_children_in_use',
                        lambda device_id: ["'Plug Switch' is used by sequence 'Irrigation'"])
    monkeypatch.setattr(utils_matter, 'remove_node', lambda n: called.append(('remove', n)))
    monkeypatch.setattr(utils_matter, '_delete_children', lambda *a: called.append('children'))
    messages = {'warning': [], 'error': []}
    utils_matter.on_device_delete(
        SimpleNamespace(device='device_matter_node', unique_id='dev-1',
                        custom_options='{"node_id": 5}'), messages)
    assert messages['error'] and called == []


def test_failed_creation_discards_half_made_children(app_ctx, monkeypatch):
    import contextlib as _cl
    from aot.aot_flask.utils import utils_function

    @_cl.contextmanager
    def fake_pending(node):
        yield {'inputs': ['in-1'], 'outputs': []}

    discarded = []
    monkeypatch.setattr(utils_matter.matter_onboarding, 'pending_node', fake_pending)
    monkeypatch.setattr(utils_function, 'function_add',
                        lambda form, tab_id=None: ({'error': ['output driver failed']},
                                                   None, [], '', None))
    monkeypatch.setattr(utils_matter, '_discard_created', lambda created: discarded.append(created))
    monkeypatch.setattr(utils_matter, '_device_tab_id', lambda: None)
    out = utils_matter._create_device({'node_id': 5, 'attributes': {}})
    assert out['error'] and discarded == [{'inputs': ['in-1'], 'outputs': []}]


def test_function_add_exception_also_discards(app_ctx, monkeypatch):
    import contextlib as _cl
    from aot.aot_flask.utils import utils_function

    @_cl.contextmanager
    def fake_pending(node):
        yield {'inputs': ['in-1'], 'outputs': ['out-1']}

    def boom(form, tab_id=None):
        raise RuntimeError('db locked')

    discarded = []
    monkeypatch.setattr(utils_matter.matter_onboarding, 'pending_node', fake_pending)
    monkeypatch.setattr(utils_function, 'function_add', boom)
    monkeypatch.setattr(utils_matter, '_discard_created', lambda created: discarded.append(created))
    monkeypatch.setattr(utils_matter, '_device_tab_id', lambda: None)
    out = utils_matter._create_device({'node_id': 5, 'attributes': {}})
    assert 'db locked' in out['error'] and discarded


def test_list_nodes_refuses_to_guess_when_server_down(app_ctx, monkeypatch):
    """서버 없이는 고아·사라진 노드를 가릴 수 없다 — 모두 '사라짐'으로 잘못 보이지 않게."""
    client = FakeClient(connected=False)
    monkeypatch.setattr(utils_matter, '_open_client', lambda: contextlib.nullcontext(client))
    monkeypatch.setattr(utils_matter, '_matter_devices', lambda: {5: SimpleNamespace(
        unique_id='d5', name='Plug', custom_options='{"node_id": 5}')})
    with pytest.raises(MatterNotConnected):
        utils_matter.list_nodes()


def test_web_client_is_per_request_with_relaxed_keepalive(monkeypatch):
    """웹 프로세스는 연결을 붙잡아 두지 않는다. 실패하는 커미셔닝 동안 서버가
    ping 에 답하지 않으므로 keepalive 는 여유 있게."""
    from aot.devices import matter_client
    made = []

    class Spy(matter_client.MatterServerClient):
        def __init__(self, **kw):
            super().__init__(**kw)
            made.append(self)

        def ensure_started(self):
            self.started = True

        def stop(self, timeout=5.0):
            self.stopped = True

    monkeypatch.setattr(matter_client, 'MatterServerClient', Spy)
    with utils_matter._open_client() as c:
        assert c.ping_timeout > utils_matter.COMMISSION_TIMEOUT_S
    assert made and made[0].stopped
    assert matter_client.PING_TIMEOUT_S <= 30   # daemon keeps a fast keepalive
