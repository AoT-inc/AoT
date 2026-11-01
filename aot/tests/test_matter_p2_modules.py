# coding=utf-8
"""Matter P2 — 디머(MATTER_LEVEL)·커튼(MATTER_COVERING) 출력, 버튼/불리언 엣지 입력,
온보딩 청사진 검사.

실제 Matter 서버·DB 없이 가짜 클라이언트로 돈다. 지키는 것:

  - 디머: AoT 듀티 0-100 % 와 Matter 레벨 1-254 의 환산(0 % 는 레벨 0 이 아니라 1 로
    클램프, 0 은 호출부가 끄기로 처리). 명령은 MoveToLevelWithOnOff(전환 시간 0.1 s
    단위, 없으면 null), 끄기는 OnOff 가 있으면 Off, 없으면 레벨 1. 듀티 없는 on 은
    OnOff On. 실패는 예외가 아니라 (1, 메시지). 상태는 명령의 낙관적 가정이 아니라
    장치 보고(OnOff·CurrentLevel)에서만 온다. 인터뷰 갱신(node_updated, 이미 응답 중)은
    상태를 다시 심지 않고, 오프라인→온라인·재연결만 다시 심는다. InfluxDB 기록은
    듀티가 0.5 이상 바뀔 때만.
  - 커튼: AoT 100 = 열림 ↔ Matter 0 = 열림 환산. 위치 인식(FeatureMap bit2) 장치는
    GoToLiftPercentage, 아니면 50 기준 UpOrOpen/DownOrClose, off 는 StopMotion.
    실패는 (1, msg) 반환이 아니라 **예외** — base_output 의 value 경로가 반환값을
    버리기 때문. 상태는 CurrentPositionLiftPercent100ths 보고, 이동 중에는 10 초에
    한 번만, 멈추면(OperationalStatus 의 lift 비트 0) 마지막 위치를 channel 0 의
    last_position_pct 로 저장한다(리더 스레드가 아니라 작업 스레드에서).
    self_positioning=True 로 코디네이터가 0 % 를 Stop 이 아니라 위치 명령으로 보내게 한다.
  - MATTER_NODE 입력: Switch 이벤트(node_event)로만 버튼 채널을 쓴다 — 모멘터리는
    ShortRelease=1, 멀티프레스는 MultiPressComplete 의 횟수, LongPress=-1. 스냅샷은
    버튼 채널을 절대 다시 쓰지 않는다(새 누름처럼 보이므로). 불리언 채널은 보고된
    변화에서만 rising/falling 엣지 트리거를 발동한다(첫 값·같은 값·스냅샷은 아님).
    _fire_edge 는 방향이 맞는 활성 트리거의 액션만 실행한다.
  - 온보딩: 커튼은 엔드포인트마다 Output 하나(채널 하나), 디머는 한 Output 에 엔드포인트별
    채널. 채널 측정은 duty_cycle/percent.
"""
import logging
import threading
import time
from types import SimpleNamespace

import pytest

from aot.devices import matter_onboarding
from aot.devices.matter_client import (
    MatterCommandError, MatterCommandTimeout, MatterNotConnected)
from aot.devices.matter_output import NodeLink


# --------------------------------------------------------------- 가짜 클라이언트

class FakeClient:
    def __init__(self, nodes=None, connected=True):
        self._nodes = nodes or {}
        self.connected = connected
        self.sent = []
        self.subscribers = {}
        self.fail_with = None
        self.started = False

    def ensure_started(self):
        self.started = True

    def is_connected(self):
        return self.connected

    def get_node(self, node_id):
        return self._nodes.get(int(node_id))

    def get_attribute(self, node_id, path, default=None):
        node = self._nodes.get(int(node_id))
        return (node or {}).get('attributes', {}).get(path, default)

    def subscribe(self, callback, node_id=None):
        handle = len(self.subscribers) + 1
        self.subscribers[handle] = (callback, node_id)
        return handle

    def unsubscribe(self, handle):
        self.subscribers.pop(handle, None)

    def send_command(self, command, args=None, timeout=5.0):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((command, args, timeout))
        return None

    def emit(self, event, data):
        for callback, _node in list(self.subscribers.values()):
            callback(event, data)

    # 테스트 보조: 실제 클라이언트처럼 캐시를 먼저 갱신한 뒤 이벤트를 낸다.
    def report(self, node_id, path, value):
        self._nodes[node_id]['attributes'][path] = value
        self.emit('attribute_updated', [node_id, path, value])


def _wait(cond, timeout=3.0):
    """상한 있는 폴링 — 무조건 sleep 하지 않는다."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class _EmptyQuery:
    def filter(self, *a, **k):
        return self

    def all(self):
        return []


NODE = 5


def _quiet_output_infra(monkeypatch, module_obj):
    monkeypatch.setattr(module_obj, 'db_retrieve_table_daemon', lambda *a, **k: _EmptyQuery())

    def _plain_logger(self, testing=False, name=None, output_dev=None):
        self.logger = logging.getLogger('test.matter_p2_output')

    monkeypatch.setattr('aot.outputs.base_output.AbstractOutput.setup_logger', _plain_logger)
    monkeypatch.setattr('aot.outputs.base_output.write_influxdb_value', lambda *a, **k: None)


# ================================================================ 디머 (MATTER_LEVEL)

def _dimmer_node(on=True, level=254, with_on_off=True, available=True):
    attrs = {'0/40/3': 'Dimmer', '0/40/18': 'U-5',
             '1/29/1': [6, 8, 29] if with_on_off else [8, 29]}
    if with_on_off:
        attrs['1/6/0'] = on
    if level is not None:
        attrs['1/8/0'] = level
    return {'node_id': NODE, 'available': available, 'attributes': attrs}


class DimmerCtx:
    def __init__(self, module, client, influx):
        self.module = module
        self.client = client
        self.influx = influx            # add_measurements_influxdb 호출 [(uid, measure)]


@pytest.fixture
def make_dimmer(monkeypatch):
    from aot.outputs import pwm_matter_level as mod

    def _make(node=None, node_id=NODE, transition=0.0):
        _quiet_output_infra(monkeypatch, mod)
        influx = []
        monkeypatch.setattr(mod, 'add_measurements_influxdb',
                            lambda uid, measure, *a, **k: influx.append((uid, measure)))
        output = SimpleNamespace(
            unique_id='dim-1-xxxxxxxx', name='dim', output_type='MATTER_LEVEL',
            latitude=None, longitude=None, location_source='manual', log_level_debug=False,
            custom_options='{"node_id": %d}' % node_id)
        module = mod.OutputModule(output, testing=True)
        module.unique_id = output.unique_id
        module.options_channels = {'endpoint': {0: 1}, 'transition_s': {0: transition}}
        # base_output sets these only outside testing; output_on_off() needs them.
        module.output_type = 'MATTER_LEVEL'
        module.output_name = 'dim'
        module.output_types = {'on_off': [], 'pwm': ['MATTER_LEVEL'], 'value': [], 'volume': []}
        client = FakeClient({NODE: node or _dimmer_node()})
        monkeypatch.setattr('aot.devices.matter_client.get_client', lambda: client)
        module.initialize()
        return DimmerCtx(module, client, influx)

    return _make


@pytest.fixture
def dimmer(make_dimmer):
    return make_dimmer()


def test_dimmer_duty_level_mapping():
    from aot.outputs.pwm_matter_level import duty_to_level, level_to_duty
    assert duty_to_level(0) == 1            # 0 은 호출부가 끄기로 처리, 여기서는 1 로 클램프
    assert duty_to_level(0.2) == 1
    assert duty_to_level(50) == 127
    assert duty_to_level(100) == 254
    assert duty_to_level(150) == 254        # 범위 밖은 클램프
    assert level_to_duty(254) == 100.0
    assert level_to_duty(127) == 50.0
    assert level_to_duty(0) == 0.0
    assert level_to_duty(300) == 100.0


def test_dimmer_output_information_is_a_pwm_output():
    from aot.outputs import pwm_matter_level as mod
    info = mod.OUTPUT_INFORMATION
    assert info['output_name_unique'] == 'MATTER_LEVEL'
    assert info['output_types'] == ['pwm']
    assert info['channels_dict'][0]['types'] == ['pwm']
    assert not info.get('self_positioning')


def test_dimmer_pwm_sends_move_to_level_with_on_off(dimmer):
    assert dimmer.module.output_switch('on', 'pwm', amount=50) == (0, "")
    command, args, timeout = dimmer.client.sent[-1]
    assert command == 'device_command'
    assert args == {
        'node_id': NODE, 'endpoint_id': 1, 'cluster_id': 8,
        'command_name': 'MoveToLevelWithOnOff',
        'payload': {'level': 127, 'transitionTime': None,
                    'optionsMask': 0, 'optionsOverride': 0},
    }
    assert timeout < 8      # Pyro 예산(C3) 안


def test_dimmer_transition_is_in_tenths_of_a_second(make_dimmer):
    ctx = make_dimmer(transition=1.5)
    ctx.module.output_switch('on', 'pwm', amount=100)
    payload = ctx.client.sent[-1][1]['payload']
    assert payload['level'] == 254 and payload['transitionTime'] == 15


def test_dimmer_small_duty_turns_on_at_level_one_not_off(dimmer):
    dimmer.module.output_switch('on', 'pwm', amount=0.2)
    args = dimmer.client.sent[-1][1]
    assert args['command_name'] == 'MoveToLevelWithOnOff' and args['payload']['level'] == 1


@pytest.mark.parametrize('kwargs', [
    {'state': 'off'},
    {'state': 'off', 'amount': 50},            # off 가 듀티보다 우선
    {'state': 'on', 'amount': 0},
    {'state': 'on', 'output_type': 'pwm', 'amount': 0.0},
])
def test_dimmer_zero_or_off_sends_on_off_off_when_endpoint_has_on_off(dimmer, kwargs):
    assert dimmer.module.output_switch(**kwargs) == (0, "")
    _command, args, _timeout = dimmer.client.sent[-1]
    assert (args['cluster_id'], args['command_name'], args['payload']) == (6, 'Off', {})
    assert args['endpoint_id'] == 1


def test_dimmer_off_without_on_off_sends_level_one(make_dimmer):
    ctx = make_dimmer(node=_dimmer_node(with_on_off=False))
    assert '1/6/0' not in ctx.client._nodes[NODE]['attributes']
    ctx.module.output_switch('off')
    args = ctx.client.sent[-1][1]
    assert args['cluster_id'] == 8 and args['command_name'] == 'MoveToLevelWithOnOff'
    assert args['payload']['level'] == 1
    ctx.module.output_switch('on', 'pwm', amount=0)
    assert ctx.client.sent[-1][1]['payload']['level'] == 1


def test_dimmer_module_on_without_duty_sends_on_off_on(dimmer):
    """모듈 자체의 의미(직접 호출). base_output.output_on_off 는 amount=None 을 0 으로
    바꿔 넘기므로 그 경로는 아래 테스트가 따로 고정한다."""
    assert dimmer.module.output_switch('on') == (0, "")
    args = dimmer.client.sent[-1][1]
    assert (args['cluster_id'], args['command_name'], args['payload']) == (6, 'On', {})


def test_dimmer_through_output_on_off_pwm_command(dimmer):
    ret = dimmer.module.output_on_off('on', output_type='pwm', amount=40, output_channel=0,
                                      trigger_conditionals=False)
    assert ret[0] == 0
    args = dimmer.client.sent[-1][1]
    assert args['command_name'] == 'MoveToLevelWithOnOff' and args['payload']['level'] == 102


def test_dimmer_through_output_on_off_without_amount_is_off(dimmer):
    """base_output 은 amount=None 을 0 으로 바꾼다 — 듀티 없는 'on' 은 이 경로에서
    OnOff On 이 아니라 Off 가 된다(0 % = 끄기). '켜기' 를 뜻하는 호출자는 듀티를 보낸다."""
    ret = dimmer.module.output_on_off('on', output_type='pwm', amount=None, output_channel=0,
                                      trigger_conditionals=False)
    assert ret[0] == 0
    args = dimmer.client.sent[-1][1]
    assert (args['cluster_id'], args['command_name']) == (6, 'Off')


def test_dimmer_through_output_on_off_failure_is_reported(dimmer):
    dimmer.client.fail_with = MatterCommandError('device_command', 1, 'node not reachable')
    code, msg = dimmer.module.output_on_off('on', output_type='pwm', amount=40,
                                            output_channel=0, trigger_conditionals=False)
    assert code == 1 and 'node not reachable' in msg


def test_dimmer_shows_the_commanded_duty_while_the_device_sits_at_that_level(dimmer, monkeypatch):
    """40 % → 레벨 102 → 되읽으면 40.2 %. 명령한 레벨에 머무는 동안은 40.0 을 보인다."""
    from aot.outputs import pwm_matter_level as mod
    from aot.outputs.pwm_matter_level import duty_to_level, level_to_duty
    clock = {'t': 100.0}
    monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: clock['t']))
    assert duty_to_level(40) == 102 and level_to_duty(102) == 40.2
    dimmer.module.output_switch('on', 'pwm', amount=40)
    clock['t'] += mod.SETTLE_S + 1          # 명령 직후의 정착 창은 지났다
    dimmer.client.report(NODE, '1/8/0', 102)
    assert dimmer.module.output_states[0] == 40.0
    assert dimmer.module.is_on(0) == 40.0
    dimmer.client.report(NODE, '1/6/0', True)               # 다른 보고가 와도 유지
    assert dimmer.module.output_states[0] == 40.0
    # 장치가 다른 레벨로 가면(다른 앱에서 조절) 명령값이 아니라 보고된 레벨을 따른다
    dimmer.client.report(NODE, '1/8/0', 127)
    assert dimmer.module.output_states[0] == 50.0
    # 한 번 다른 레벨로 갔으면 옛 명령은 잊는다 — 우연히 같은 레벨로 돌아와도
    # 옛 명령값이 되살아나지 않고 보고된 레벨을 보인다.
    dimmer.client.report(NODE, '1/8/0', 102)
    assert dimmer.module.output_states[0] == 40.2


def test_dimmer_without_a_command_shows_the_level_as_reported(make_dimmer):
    ctx = make_dimmer(node=_dimmer_node(level=102))
    assert ctx.module.output_states[0] == 40.2


def test_dimmer_commanded_duty_does_not_hide_off(dimmer):
    dimmer.module.output_switch('on', 'pwm', amount=40)
    dimmer.client.report(NODE, '1/8/0', 102)
    dimmer.client.report(NODE, '1/6/0', False)
    assert dimmer.module.output_states[0] == 0.0 and dimmer.module.is_on(0) is False


@pytest.mark.parametrize('error', [
    MatterCommandError('device_command', 1, 'node not reachable'),
    MatterCommandTimeout('device_command'),
    MatterNotConnected('no server'),
])
def test_dimmer_matter_failure_is_returned_not_raised(dimmer, error):
    dimmer.client.fail_with = error
    code, msg = dimmer.module.output_switch('on', 'pwm', amount=40)
    assert code == 1 and msg


def test_dimmer_failure_message_names_the_cause(dimmer):
    dimmer.client.fail_with = MatterCommandError('device_command', 1, 'node not reachable')
    code, msg = dimmer.module.output_switch('off')
    assert code == 1 and 'node not reachable' in msg


def test_dimmer_failure_does_not_invent_state(dimmer):
    before = dimmer.module.output_states[0]
    dimmer.client.fail_with = MatterCommandError('device_command', 1, 'x')
    dimmer.module.output_switch('on', 'pwm', amount=10)
    assert dimmer.module.output_states[0] == before


def test_dimmer_bad_inputs_are_errors(dimmer):
    assert dimmer.module.output_switch('on', 'pwm', amount='abc')[0] == 1
    assert dimmer.module.output_switch('on', 'pwm', amount=10, output_channel=3)[0] == 1
    assert dimmer.client.sent == []


def test_dimmer_before_node_id_is_configured(make_dimmer):
    ctx = make_dimmer(node_id=0)
    assert ctx.module.client is None
    assert ctx.module.is_on(0) is None
    code, msg = ctx.module.output_switch('on')
    assert code == 1 and 'not set up' in msg


def test_dimmer_state_from_cache_at_start(make_dimmer):
    assert make_dimmer(node=_dimmer_node(on=True, level=254)).module.is_on(0) == 100.0
    ctx = make_dimmer(node=_dimmer_node(on=True, level=127))
    assert ctx.module.is_on(0) == 50.0
    ctx = make_dimmer(node=_dimmer_node(on=False, level=127))
    assert ctx.module.output_states[0] == 0.0           # 꺼짐이면 레벨은 무시
    assert ctx.module.is_on(0) is False


def test_dimmer_on_off_without_level_reports_full_or_zero(make_dimmer):
    assert make_dimmer(node=_dimmer_node(on=True, level=None)).module.is_on(0) == 100.0
    assert make_dimmer(node=_dimmer_node(on=False, level=None)).module.is_on(0) is False


def test_dimmer_level_without_on_off_is_used(make_dimmer):
    ctx = make_dimmer(node=_dimmer_node(with_on_off=False, level=127))
    assert ctx.module.is_on(0) == 50.0


def test_dimmer_unknown_state_is_none_not_off(make_dimmer):
    ctx = make_dimmer(node=_dimmer_node(on=None, level=None))
    assert ctx.module.output_states[0] is None
    assert ctx.module.is_on(0) is None


def test_dimmer_state_follows_device_reports(dimmer):
    client, module = dimmer.client, dimmer.module
    client.report(NODE, '1/8/0', 127)
    assert module.is_on(0) == 50.0
    client.report(NODE, '1/6/0', False)
    assert module.output_states[0] == 0.0 and module.is_on(0) is False
    client.report(NODE, '1/6/0', True)
    assert module.is_on(0) == 50.0
    # 우리 경로가 아닌 보고·깨진 데이터는 무시
    client.emit('attribute_updated', [NODE, '9/9/9', 1])
    client.emit('attribute_updated', None)
    assert module.is_on(0) == 50.0


def test_dimmer_node_updated_while_online_does_not_reseed(dimmer):
    """인터뷰 갱신의 캐시는 방금 명령의 보고보다 옛것일 수 있다(P1 결정)."""
    client, module = dimmer.client, dimmer.module
    assert module._was_available is True
    client._nodes[NODE]['attributes']['1/8/0'] = 127          # 보고 없이 캐시만 바뀜
    client.emit('node_updated', {'node_id': NODE, 'available': True})
    assert module.is_on(0) == 100.0


def test_dimmer_reseeds_only_when_node_comes_back(dimmer):
    client, module = dimmer.client, dimmer.module
    node = client._nodes[NODE]
    node['available'] = False
    client.emit('node_updated', {'node_id': NODE, 'available': False})
    node['attributes']['1/8/0'] = 127
    node['available'] = True
    client.emit('node_updated', {'node_id': NODE, 'available': True})
    assert module.is_on(0) == 50.0


def test_dimmer_reseeds_on_reconnect(dimmer):
    client, module = dimmer.client, dimmer.module
    client._nodes[NODE]['attributes']['1/8/0'] = 64
    client.emit('connected', None)
    assert module.output_states[0] == pytest.approx(25.2)


def test_dimmer_does_not_reseed_from_an_unavailable_node(dimmer):
    client, module = dimmer.client, dimmer.module
    client._nodes[NODE]['available'] = False
    client._nodes[NODE]['attributes']['1/8/0'] = 64
    client.emit('connected', None)
    assert module.is_on(0) == 100.0


def test_dimmer_records_only_when_duty_changes_by_half_a_percent(dimmer):
    client, influx = dimmer.client, dimmer.influx
    assert len(influx) == 1                       # 시작 시 심은 값(100 %)
    assert influx[0][1][0]['value'] == 100.0
    assert influx[0][1][0]['measurement'] == 'duty_cycle'
    assert influx[0][1][0]['unit'] == 'percent'

    client.report(NODE, '1/6/0', True)            # 같은 값의 보고
    assert len(influx) == 1
    client.report(NODE, '1/8/0', 253)             # 99.6 (0.4 차이)
    assert len(influx) == 1
    client.report(NODE, '1/8/0', 127)             # 50.0
    assert len(influx) == 2 and influx[-1][1][0]['value'] == 50.0
    client.report(NODE, '1/8/0', 126)             # 49.6 (0.4 차이)
    assert len(influx) == 2
    client.report(NODE, '1/6/0', False)           # 0.0
    assert len(influx) == 3 and influx[-1][1][0]['value'] == 0.0
    assert influx[-1][0] == 'dim-1-xxxxxxxx'


def test_dimmer_stop_output_unsubscribes(dimmer):
    assert dimmer.client.subscribers
    dimmer.module.stop_output()
    assert not dimmer.client.subscribers
    assert dimmer.module.running is False


def test_node_link_health():
    client = FakeClient({NODE: _dimmer_node()})
    link = NodeLink(client, NODE)
    assert link.is_healthy()
    client._nodes[NODE]['available'] = False
    assert not link.is_healthy()
    client._nodes[NODE]['available'] = True
    client.connected = False
    assert not link.is_healthy()
    assert not NodeLink(FakeClient({}), 99).is_healthy()


# ================================================================ 커튼 (MATTER_COVERING)

FEATURE_LIFT_ONLY = 0b001
FEATURE_LIFT_POSITION_AWARE = 0b101


def _covering_node(feature_map=FEATURE_LIFT_POSITION_AWARE, lift=None, status=None,
                   target=None):
    attrs = {'0/40/3': 'Curtain', '0/40/18': 'U-5', '1/29/1': [258, 29]}
    if feature_map is not None:
        attrs['1/258/65532'] = feature_map
    if lift is not None:
        attrs['1/258/14'] = lift
    if status is not None:
        attrs['1/258/10'] = status
    if target is not None:
        attrs['1/258/11'] = target
    return {'node_id': NODE, 'available': True, 'attributes': attrs}


class CoveringCtx:
    def __init__(self, module, client, persists, influx, threads, clock):
        self.module = module
        self.client = client
        self.persists = persists        # [(channel, option, value, thread)]
        self.influx = influx
        self.threads = threads
        self.clock = clock

    def flush(self, timeout=5.0):
        """작업 스레드가 끝날 때까지 기다린다(결정적: join)."""
        for thread in list(self.threads):
            thread.join(timeout)
            assert not thread.is_alive()

    def report(self, path, value, at=None):
        if at is not None:
            self.clock['t'] = at
        self.client.report(NODE, path, value)
        self.flush()

    def saved(self):
        return [(ch, opt, val) for ch, opt, val, _t in self.persists]


@pytest.fixture
def make_covering(monkeypatch):
    from aot.outputs import value_matter_covering as mod

    made = []

    def _make(node=None):
        _quiet_output_infra(monkeypatch, mod)
        influx, persists, threads = [], [], []
        clock = {'t': 1000.0}
        monkeypatch.setattr(mod, 'add_measurements_influxdb',
                            lambda uid, measure, *a, **k: influx.append((uid, measure)))
        # 스로틀 판정은 time.monotonic() 하나만 쓴다.
        monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: clock['t']))

        class RecordingThread(threading.Thread):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                threads.append(self)

        monkeypatch.setattr(mod, 'threading', SimpleNamespace(Thread=RecordingThread, Lock=threading.Lock))

        output = SimpleNamespace(
            unique_id='cov-1-xxxxxxxx', name='cov', output_type='MATTER_COVERING',
            latitude=None, longitude=None, location_source='manual', log_level_debug=False,
            custom_options='{"node_id": %d}' % NODE)
        module = mod.OutputModule(output, testing=True)
        module.unique_id = output.unique_id
        module.options_channels = {'endpoint': {0: 1}}
        module.output_type = 'MATTER_COVERING'
        module.output_name = 'cov'
        module.output_types = {'on_off': [], 'pwm': [], 'value': ['MATTER_COVERING'],
                               'volume': []}

        def _save(ch, opt, val):
            # 실제 setter 처럼 성공하면 저장한 값을 돌려준다(None/문자열 = 실패).
            persists.append((ch, opt, val, threading.current_thread()))
            return val

        monkeypatch.setattr(module, 'set_custom_channel_option', _save)
        client = FakeClient({NODE: node or _covering_node()})
        monkeypatch.setattr('aot.devices.matter_client.get_client', lambda: client)
        module.initialize()
        ctx = CoveringCtx(module, client, persists, influx, threads, clock)
        made.append(ctx)
        return ctx

    yield _make
    for ctx in made:
        ctx.flush()


@pytest.fixture
def covering(make_covering):
    return make_covering()


def test_covering_unit_conversion():
    from aot.outputs.value_matter_covering import aot_to_matter_100ths, matter_100ths_to_aot
    assert aot_to_matter_100ths(100) == 0           # AoT 100 = 열림 = Matter 0
    assert aot_to_matter_100ths(0) == 10000
    assert aot_to_matter_100ths(30) == 7000
    assert aot_to_matter_100ths(-5) == 10000        # 범위 밖은 클램프
    assert aot_to_matter_100ths(250) == 0
    assert matter_100ths_to_aot(0) == 100.0
    assert matter_100ths_to_aot(10000) == 0.0
    assert matter_100ths_to_aot(7000) == 30.0
    assert matter_100ths_to_aot(20000) == 0.0
    assert matter_100ths_to_aot(-1) == 100.0


def test_covering_output_information_is_self_positioning_value():
    from aot.outputs import value_matter_covering as mod
    info = mod.OUTPUT_INFORMATION
    assert info['output_name_unique'] == 'MATTER_COVERING'
    assert info['self_positioning'] is True
    assert info['output_types'] == ['value']
    assert info['channels_dict'][0]['types'] == ['value']


@pytest.mark.parametrize('pct, expected', [(100, 0), (0, 10000), (30, 7000), (62.5, 3750)])
def test_covering_position_aware_goes_to_lift_percentage(covering, pct, expected):
    assert covering.module.output_switch('on', 'value', amount=pct) == (0, "")
    command, args, timeout = covering.client.sent[-1]
    assert command == 'device_command'
    assert args == {'node_id': NODE, 'endpoint_id': 1, 'cluster_id': 258,
                    'command_name': 'GoToLiftPercentage',
                    'payload': {'liftPercent100thsValue': expected}}
    assert timeout < 8


def test_covering_zero_percent_is_a_position_not_stop(covering):
    """self_positioning: 0 % 는 value 명령으로 온다 — 닫힘 위치(10000)."""
    covering.module.output_switch('on', 'value', amount=0)
    assert covering.client.sent[-1][1]['command_name'] == 'GoToLiftPercentage'
    assert covering.client.sent[-1][1]['payload'] == {'liftPercent100thsValue': 10000}


def test_covering_through_output_on_off_without_amount_closes(covering, make_covering):
    """base_output 은 amount=None 을 0 으로 바꿔 모듈에 넘긴다 — 값 없는 'on' 은 닫힘.
    열려는 호출자는 100 을 보낸다(모듈 docstring)."""
    ret = covering.module.output_on_off('on', output_type='value', amount=None,
                                        output_channel=0, trigger_conditionals=False)
    assert ret[0] == 0
    assert covering.client.sent[-1][1]['command_name'] == 'GoToLiftPercentage'
    assert covering.client.sent[-1][1]['payload'] == {'liftPercent100thsValue': 10000}
    plain = make_covering(node=_covering_node(feature_map=FEATURE_LIFT_ONLY))
    plain.module.output_on_off('on', output_type='value', amount=None, output_channel=0,
                               trigger_conditionals=False)
    assert plain.client.sent[-1][1]['command_name'] == 'DownOrClose'


def test_covering_through_output_on_off_success(covering):
    ret = covering.module.output_on_off('on', output_type='value', amount=40,
                                        output_channel=0, trigger_conditionals=False)
    assert ret[0] == 0
    args = covering.client.sent[-1][1]
    assert args['command_name'] == 'GoToLiftPercentage'
    assert args['payload'] == {'liftPercent100thsValue': 6000}
    covering.module.output_on_off('on', output_type='value', amount=100, output_channel=0,
                                  trigger_conditionals=False)
    assert covering.client.sent[-1][1]['payload'] == {'liftPercent100thsValue': 0}


def test_covering_through_output_on_off_failure_returns_code_and_message(covering):
    """value 경로가 (1, msg) 를 존중한다(_switch_failed) — 예외로 새지 않는다."""
    covering.client.fail_with = MatterCommandError('device_command', 1, 'node not reachable')
    code, msg = covering.module.output_on_off(
        'on', output_type='value', amount=40, output_channel=0, trigger_conditionals=False)
    assert code == 1 and 'node not reachable' in msg
    assert covering.client.sent == []


@pytest.mark.parametrize('feature_map', [FEATURE_LIFT_ONLY, None])
@pytest.mark.parametrize('pct, command', [
    (100, 'UpOrOpen'), (50, 'UpOrOpen'), (49.9, 'DownOrClose'), (0, 'DownOrClose')])
def test_covering_without_position_awareness_opens_or_closes(
        make_covering, feature_map, pct, command):
    ctx = make_covering(node=_covering_node(feature_map=feature_map))
    assert ctx.module.output_switch('on', 'value', amount=pct) == (0, "")
    args = ctx.client.sent[-1][1]
    assert (args['cluster_id'], args['command_name'], args['payload']) == (258, command, {})


@pytest.mark.parametrize('feature_map', [FEATURE_LIFT_POSITION_AWARE, FEATURE_LIFT_ONLY])
def test_covering_off_is_stop_motion(make_covering, feature_map):
    ctx = make_covering(node=_covering_node(feature_map=feature_map))
    assert ctx.module.output_switch('off') == (0, "")
    args = ctx.client.sent[-1][1]
    assert (args['cluster_id'], args['command_name'], args['payload']) == (258, 'StopMotion', {})


@pytest.mark.parametrize('error', [
    MatterCommandError('device_command', 1, 'node not reachable'),
    MatterCommandTimeout('device_command'),
    MatterNotConnected('no server'),
])
def test_covering_failure_is_returned_not_raised(covering, error):
    covering.client.fail_with = error
    code, msg = covering.module.output_switch('on', 'value', amount=40)
    assert code == 1 and msg
    code, msg = covering.module.output_switch('off')
    assert code == 1 and msg


def test_covering_failure_message_names_the_cause(covering):
    covering.client.fail_with = MatterCommandError('device_command', 1, 'node not reachable')
    code, msg = covering.module.output_switch('on', 'value', amount=40)
    assert code == 1 and 'node not reachable' in msg


def test_covering_unknown_channel_and_not_set_up_are_errors(covering):
    code, _msg = covering.module.output_switch('on', 'value', amount=40, output_channel=2)
    assert code == 1
    covering.module.client = None
    code, msg = covering.module.output_switch('on', 'value', amount=40)
    assert code == 1 and 'not set up' in msg
    assert covering.client.sent == []


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf'), 'abc', object()])
def test_covering_rejects_invalid_position(covering, bad):
    code, msg = covering.module.output_switch('on', 'value', amount=bad)
    assert code == 1 and 'Invalid position' in msg
    assert covering.client.sent == []


def test_covering_state_from_position_reports(covering):
    module = covering.module
    assert module.is_on(0) is None                      # 아직 모름 — 닫힘으로 지어내지 않음
    covering.report('1/258/14', 3000)
    assert module.output_states[0] == 70.0 and module.is_on(0) == 70.0
    covering.report('1/258/14', 10000)
    assert module.output_states[0] == 0.0
    assert module.is_on(0) is False                     # 완전히 닫힘
    covering.report('1/258/14', 0)
    assert module.is_on(0) == 100.0


def test_covering_state_is_seeded_from_cache(make_covering):
    ctx = make_covering(node=_covering_node(lift=2500))
    assert ctx.module.is_on(0) == 75.0


def test_covering_target_pct_from_target_attribute(make_covering):
    ctx = make_covering(node=_covering_node(target=2000))
    assert ctx.module.output_target_pct(0) == (80.0, 'system')
    assert make_covering().module.output_target_pct(0) is None       # 목표 보고 없음
    assert ctx.module.output_target_pct(3) is None                   # 엔드포인트 없는 채널


def test_covering_persists_when_stopped(covering):
    covering.report('1/258/10', 0)
    covering.report('1/258/14', 3000)
    assert covering.saved() == [(0, 'last_position_pct', 70.0)]
    # 같은 위치의 다른 보고(OperationalStatus)는 다시 저장하지 않는다
    covering.report('1/258/10', 0)
    assert covering.saved() == [(0, 'last_position_pct', 70.0)]
    covering.report('1/258/14', 0)
    assert covering.saved()[-1] == (0, 'last_position_pct', 100.0)
    assert len(covering.saved()) == 2
    assert [m[1][0]['value'] for m in covering.influx] == [70.0, 100.0]


def test_covering_persist_runs_off_the_reporting_thread(covering):
    """리더 스레드에서 DB 를 쓰면 이 프로세스의 모든 Matter 응답이 멈춘다."""
    covering.client._nodes[NODE]['attributes']['1/258/10'] = 0
    covering.client.report(NODE, '1/258/14', 3000)
    assert _wait(lambda: covering.persists)
    assert covering.persists[0][3] is not threading.current_thread()
    assert covering.persists[0][3].name.startswith('matter-cover-persist-')


def test_covering_throttles_persist_while_moving(covering):
    # 열리는 중(lift 비트 = 0b0100): 첫 보고는 저장, 10 초 안의 보고는 건너뜀
    covering.report('1/258/10', 0b0100, at=1000.0)
    covering.report('1/258/14', 9000, at=1000.0)
    assert covering.saved() == [(0, 'last_position_pct', 10.0)]
    covering.report('1/258/14', 8000, at=1002.0)
    covering.report('1/258/14', 7000, at=1005.0)
    covering.report('1/258/14', 6500, at=1009.9)
    assert covering.saved() == [(0, 'last_position_pct', 10.0)]
    # 멈춘 보고는 시간과 무관하게 마지막 위치를 저장
    covering.report('1/258/10', 0, at=1010.0)
    assert covering.saved() == [(0, 'last_position_pct', 10.0), (0, 'last_position_pct', 35.0)]


def test_covering_stop_report_persists_final_position_even_if_last_move_report_was_throttled(
        covering):
    covering.report('1/258/10', 0b1000, at=2000.0)         # 닫히는 중
    covering.report('1/258/14', 5000, at=2000.0)
    covering.report('1/258/14', 9800, at=2001.0)           # 억제됨
    assert covering.saved() == [(0, 'last_position_pct', 50.0)]
    covering.report('1/258/10', 0, at=2002.0)              # 정지
    assert covering.saved()[-1] == (0, 'last_position_pct', 2.0)


def test_covering_persists_again_after_throttle_window_while_moving(covering):
    covering.report('1/258/10', 0b0100, at=3000.0)
    covering.report('1/258/14', 9000, at=3000.0)
    covering.report('1/258/14', 8000, at=3009.0)           # 9 초 — 억제
    covering.report('1/258/14', 7000, at=3010.0)           # 10 초 — 저장
    assert covering.saved() == [(0, 'last_position_pct', 10.0), (0, 'last_position_pct', 30.0)]


def test_covering_sub_half_percent_change_is_not_persisted(covering):
    covering.report('1/258/10', 0, at=4000.0)
    covering.report('1/258/14', 5000, at=4000.0)
    covering.report('1/258/14', 4980, at=4001.0)           # 0.2 % 차이
    assert covering.saved() == [(0, 'last_position_pct', 50.0)]


def test_covering_stop_output_unsubscribes(covering):
    assert covering.client.subscribers
    covering.module.stop_output()
    assert not covering.client.subscribers and covering.module.running is False


# ================================================================ MATTER_NODE 입력

BUTTON_CH, BOOL_CH, TEMP_CH = 0, 1, 2
FMAP_MOMENTARY = 0b00010            # MomentarySwitch 만 — Release 기능 없음(InitialPress 만 보냄)
FMAP_MOMENTARY_RELEASE = 0b00110    # + MomentarySwitchRelease: ShortRelease 를 보냄
FMAP_MULTI_PRESS = 0b10010


def _input_node(fmap=FMAP_MOMENTARY_RELEASE, contact=False, temp=2150, available=True):
    attrs = {
        '1/59/1': 0,
        '2/69/0': contact,
        '3/1026/0': temp,
    }
    if fmap is not None:
        attrs['1/59/65532'] = fmap
    return {'node_id': 7, 'available': available, 'attributes': attrs}


class InputCtx:
    def __init__(self, module, client, writes, edges):
        self.module = module
        self.client = client
        self.writes = writes
        self.edges = edges          # _fire_edge(direction, what) 호출

    def event(self, event_id, data=None, endpoint=1, cluster=59):
        self.module._on_event('node_event', {
            'node_id': 7, 'endpoint_id': endpoint, 'cluster_id': cluster,
            'event_id': event_id, 'data': data})
        self.module._drain_changes()

    def change(self, path, value):
        self.module._on_event('attribute_updated', [7, path, value])
        self.module._drain_changes()


@pytest.fixture
def make_input(monkeypatch):
    from aot.inputs import matter_node

    def _make(node=None):
        writes, edges = [], []
        monkeypatch.setattr(matter_node, 'add_measurements_influxdb',
                            lambda uid, m, use_same_timestamp=False: writes.append(m))
        monkeypatch.setattr(matter_node, 'run_input_actions',
                            lambda uid, msg, m, debug: ('', m))

        def _plain_logger(self, *a, **k):
            self.logger = logging.getLogger('test.matter_p2_input')

        monkeypatch.setattr('aot.inputs.base_input.AbstractInput.setup_logger', _plain_logger,
                            raising=False)
        input_dev = SimpleNamespace(
            unique_id='in-1', name='in', device='MATTER_NODE', log_level_debug=False,
            latitude=None, longitude=None, location_source='manual')
        try:
            module = matter_node.InputModule(input_dev, testing=True)
        except Exception as err:  # pragma: no cover - environment specific
            pytest.skip(f'cannot build Input without DB: {err}')
        module.logger = logging.getLogger('test.matter_p2_input')
        module.unique_id = 'in-1'
        module.node_id = 7
        module.sample_interval_s = 60
        module.channels_measurement = {
            BUTTON_CH: SimpleNamespace(measurement='unitless', unit='none',
                                       conversion_id=None, name='Button'),
            BOOL_CH: SimpleNamespace(measurement='boolean', unit='bool',
                                     conversion_id=None, name='Contact'),
            TEMP_CH: SimpleNamespace(measurement='temperature', unit='C',
                                     conversion_id=None, name='Temp'),
        }
        module.channels_conversion = {BUTTON_CH: None, BOOL_CH: None, TEMP_CH: None}
        module.options_channels = {
            'matter_kind': {BUTTON_CH: 'button', BOOL_CH: 'boolean_state',
                            TEMP_CH: 'temperature'},
            'endpoint': {BUTTON_CH: 1, BOOL_CH: 2, TEMP_CH: 3},
            'cluster_id': {BUTTON_CH: 59, BOOL_CH: 69, TEMP_CH: 1026},
            'attribute_id': {BUTTON_CH: 1, BOOL_CH: 0, TEMP_CH: 0},
        }
        module._paths = {'1/59/1': [BUTTON_CH], '2/69/0': [BOOL_CH], '3/1026/0': [TEMP_CH]}
        client = FakeClient({7: node or _input_node()})
        module.client = client
        monkeypatch.setattr(module, '_fire_edge', lambda d, w: edges.append((d, w)))
        return InputCtx(module, client, writes, edges)

    return _make


@pytest.fixture
def inp(make_input):
    return make_input()


def test_button_short_release_without_multipress_is_one_press(inp):
    inp.event(3)                                # ShortRelease (Release 기능 있는 단순 버튼)
    assert len(inp.writes) == 1
    assert set(inp.writes[0]) == {BUTTON_CH}
    assert inp.writes[0][BUTTON_CH]['value'] == 1.0
    assert [d for d, _ in inp.edges] == ['rising']
    assert 'endpoint 1' in inp.edges[0][1] and '1 press' in inp.edges[0][1]


def test_button_other_events_of_a_release_button_do_nothing(inp):
    for event_id in (1, 4, 5, 6):               # InitialPress, LongRelease, MultiPressOngoing...
        inp.event(event_id, {'totalNumberOfPressesCounted': 3})
    assert inp.writes == [] and inp.edges == []


def test_button_without_release_feature_counts_initial_press(make_input):
    """FeatureMap = MomentarySwitch 만(0b10): 장치는 InitialPress 만 보낸다."""
    ctx = make_input(node=_input_node(fmap=FMAP_MOMENTARY))
    ctx.event(1)                                # InitialPress
    assert len(ctx.writes) == 1 and ctx.writes[0][BUTTON_CH]['value'] == 1.0
    assert [d for d, _ in ctx.edges] == ['rising']
    ctx.event(3)                                # 보내지 않을 ShortRelease 는 무시
    ctx.event(4)
    ctx.event(6, {'totalNumberOfPressesCounted': 2})
    assert len(ctx.writes) == 1 and len(ctx.edges) == 1
    ctx.event(2)                                # LongPress 는 그대로 -1
    assert ctx.writes[-1][BUTTON_CH]['value'] == -1.0


def test_button_with_unknown_feature_map_assumes_release(make_input):
    ctx = make_input(node=_input_node(fmap=None))
    ctx.event(1)                                # InitialPress 는 세지 않는다
    assert ctx.writes == []
    ctx.event(3)
    assert ctx.writes[0][BUTTON_CH]['value'] == 1.0


def test_button_value_pure_function_contract():
    from aot.devices import matter_clusters as mc
    assert mc.button_value(3, None, False) == 1.0                       # release=True 기본
    assert mc.button_value(1, None, False) is None
    assert mc.button_value(1, None, False, release=False) == 1.0
    assert mc.button_value(3, None, False, release=False) is None
    assert mc.button_value(2, None, False, release=False) == -1.0       # LongPress
    assert mc.button_value(2, None, False) == -1.0
    # 멀티프레스는 release 와 무관하게 MultiPressComplete 의 횟수
    assert mc.button_value(6, {'totalNumberOfPressesCounted': 3}, True, release=False) == 3.0
    assert mc.button_value(1, None, True, release=False) is None


def test_button_long_press_records_minus_one(inp):
    inp.event(2)
    assert inp.writes[0][BUTTON_CH]['value'] == -1.0
    assert inp.edges[0][0] == 'rising' and 'long press' in inp.edges[0][1]


def test_multipress_button_counts_from_multi_press_complete(make_input):
    ctx = make_input(node=_input_node(fmap=FMAP_MULTI_PRESS))
    ctx.event(3)                                # ShortRelease 는 제스처의 일부일 뿐
    assert ctx.writes == [] and ctx.edges == []
    ctx.event(6, {'totalNumberOfPressesCounted': 2})
    assert len(ctx.writes) == 1 and ctx.writes[0][BUTTON_CH]['value'] == 2.0
    assert ctx.edges and ctx.edges[-1][0] == 'rising' and '2 presses' in ctx.edges[-1][1]
    ctx.event(2)                                # LongPress
    assert ctx.writes[-1][BUTTON_CH]['value'] == -1.0


@pytest.mark.parametrize('data', [None, {}, {'totalNumberOfPressesCounted': 0},
                                  {'totalNumberOfPressesCounted': 'x'}])
def test_multipress_complete_without_a_usable_count_is_ignored(make_input, data):
    ctx = make_input(node=_input_node(fmap=FMAP_MULTI_PRESS))
    ctx.event(6, data)
    assert ctx.writes == [] and ctx.edges == []


def test_button_events_for_other_endpoints_or_clusters_are_ignored(inp):
    inp.event(3, endpoint=9)
    inp.event(3, cluster=69)
    assert inp.writes == [] and inp.edges == []


def test_button_current_position_report_is_not_a_press(inp):
    """CurrentPosition 은 채널의 키일 뿐 — 그 속성 보고는 값을 쓰지 않는다."""
    inp.change('1/59/1', 1)
    assert inp.writes == [] and inp.edges == []


def test_snapshot_never_writes_the_button_channel(inp):
    inp.module._write_snapshot('sample')
    assert len(inp.writes) == 1
    assert set(inp.writes[0]) == {BOOL_CH, TEMP_CH}
    inp.module._write_snapshot('startup')
    assert all(BUTTON_CH not in w for w in inp.writes)


def test_boolean_edges_fire_only_on_reported_flips(inp):
    inp.change('2/69/0', False)                 # 첫 값 — 엣지 없음
    assert inp.edges == []
    inp.change('2/69/0', True)
    assert [d for d, _ in inp.edges] == ['rising']
    assert 'Contact' in inp.edges[0][1] and 'on' in inp.edges[0][1]
    inp.change('2/69/0', True)                  # 같은 값 반복 — 엣지 없음
    assert [d for d, _ in inp.edges] == ['rising']
    inp.change('2/69/0', False)
    assert [d for d, _ in inp.edges] == ['rising', 'falling']
    assert 'off' in inp.edges[1][1]
    assert len(inp.writes) == 4                 # 엣지와 무관하게 값은 매번 기록


def test_boolean_first_report_after_start_has_no_edge_even_if_true(inp):
    inp.change('2/69/0', True)
    assert inp.edges == []


def test_snapshot_writes_never_fire_edges_but_track_the_value(inp):
    inp.change('2/69/0', False)
    inp.client._nodes[7]['attributes']['2/69/0'] = True
    inp.module._write_snapshot('sample')        # 샘플로 True 가 기록됨
    assert inp.edges == []
    inp.change('2/69/0', False)                 # 샘플 값(True) 기준의 변화
    assert [d for d, _ in inp.edges] == ['falling']
    inp.change('2/69/0', False)
    assert [d for d, _ in inp.edges] == ['falling']


def test_non_boolean_channels_never_fire_edges(inp):
    inp.change('3/1026/0', 2000)
    inp.change('3/1026/0', 2500)
    assert inp.edges == []


def test_reported_changes_are_written_even_if_availability_lags(make_input):
    """보고된 변화는 구독이 살아 있다는 증거 — 가용성 표시가 아직 False 여도 버리지 않는다."""
    ctx = make_input(node=_input_node(available=False))
    ctx.change('3/1026/0', 2300)
    assert [list(w.values())[0]['value'] for w in ctx.writes] == [23.0]
    ctx.event(3)                                # 누름도 마찬가지
    assert [list(w.values())[0]['value'] for w in ctx.writes] == [23.0, 1.0]
    assert [e[0] for e in ctx.edges] == ['rising']


def test_bool_change_after_an_outage_is_written_and_fires_its_edge(make_input):
    """장애 뒤 available 이 아직 False 일 때 보고된 접점 변화가 엣지까지 살아남는다
    (버리면 다음 스냅샷이 새 상태만 기록해 엣지는 영영 사라진다)."""
    ctx = make_input()
    ctx.change('2/69/0', False)                 # 기준값
    ctx.client._nodes[7]['available'] = False   # 장애 — 표시는 아직 따라오지 않음
    ctx.change('2/69/0', True)
    assert [list(w.values())[0]['value'] for w in ctx.writes] == [0.0, 1.0]
    assert [d for d, _ in ctx.edges] == ['rising']


def test_snapshot_still_skips_an_unavailable_node(make_input):
    ctx = make_input(node=_input_node(available=False))
    ctx.module._write_snapshot('sample')
    assert ctx.writes == []


# ---------------------------------------------------------------- _fire_edge

class _TriggerQuery:
    def __init__(self, triggers):
        self.triggers = triggers

    def filter(self, *a, **k):
        return self

    def all(self):
        return list(self.triggers)


class _FakeControl:
    def __init__(self, fail_for=()):
        self.calls = []
        self.fail_for = set(fail_for)

    def trigger_all_actions(self, unique_id, message=None):
        self.calls.append((unique_id, message))
        if unique_id in self.fail_for:
            raise RuntimeError('boom')


def _trigger(n, edge):
    return SimpleNamespace(id=n, unique_id=f'trg-{n}', name=f'T{n}', edge_detected=edge)


@pytest.fixture
def real_fire_edge(monkeypatch):
    """_fire_edge 자체를 검사한다(다른 테스트는 기록용으로 바꿔 둠)."""
    from aot.inputs import matter_node

    def _make(triggers, control=None):
        module = matter_node.InputModule(
            SimpleNamespace(unique_id='in-1', name='in', device='MATTER_NODE',
                            log_level_debug=False, latitude=None, longitude=None,
                            location_source='manual'),
            testing=True)
        module.logger = logging.getLogger('test.matter_p2_input')
        module.unique_id = 'in-1'
        module.control = control or _FakeControl()
        monkeypatch.setattr(matter_node, 'db_retrieve_table_daemon',
                            lambda *a, **k: _TriggerQuery(triggers))
        return module

    return _make


@pytest.fixture(autouse=True)
def _plain_input_logger(monkeypatch):
    def _plain_logger(self, *a, **k):
        self.logger = logging.getLogger('test.matter_p2_input')

    monkeypatch.setattr('aot.inputs.base_input.AbstractInput.setup_logger', _plain_logger,
                        raising=False)


@pytest.mark.parametrize('direction, expected', [
    ('rising', {'trg-1', 'trg-2'}),
    ('falling', {'trg-1', 'trg-3'}),
])
def test_fire_edge_runs_only_matching_triggers(real_fire_edge, direction, expected):
    module = real_fire_edge([_trigger(1, 'both'), _trigger(2, 'rising'), _trigger(3, 'falling')])
    module._fire_edge(direction, 'Contact on')
    assert {uid for uid, _msg in module.control.calls} == expected
    for _uid, message in module.control.calls:
        assert direction in message and 'Contact on' in message and 'in-1' in message


def test_fire_edge_one_failing_trigger_does_not_stop_the_rest(real_fire_edge):
    control = _FakeControl(fail_for={'trg-1'})
    module = real_fire_edge([_trigger(1, 'both'), _trigger(2, 'both')], control)
    module._fire_edge('rising', 'x')
    assert [uid for uid, _ in control.calls] == ['trg-1', 'trg-2']


def test_fire_edge_without_triggers_does_nothing(real_fire_edge):
    module = real_fire_edge([])
    module._fire_edge('rising', 'x')
    assert module.control.calls == []


def test_fire_edge_trigger_lookup_failure_is_swallowed(real_fire_edge, monkeypatch):
    from aot.inputs import matter_node
    module = real_fire_edge([_trigger(1, 'both')])

    def boom(*a, **k):
        raise RuntimeError('db down')

    monkeypatch.setattr(matter_node, 'db_retrieve_table_daemon', boom)
    module._fire_edge('rising', 'x')
    assert module.control.calls == []


# ================================================================ 온보딩 청사진

def _blueprint_node(coverings=(1, 2), dimmers=(3,), covering_feature=FEATURE_LIFT_POSITION_AWARE):
    attrs = {'0/40/3': 'Hub', '0/40/18': 'U-9'}
    for ep in coverings:
        attrs[f'{ep}/29/1'] = [258, 29]
        attrs[f'{ep}/258/65532'] = covering_feature
        attrs[f'{ep}/258/14'] = 5000
    for ep in dimmers:
        attrs[f'{ep}/29/1'] = [3, 4, 6, 8, 29]
        attrs[f'{ep}/29/0'] = [{'0': 257, '1': 3}]        # Dimmable Light
        attrs[f'{ep}/6/0'] = True
        attrs[f'{ep}/8/0'] = 100
    return {'node_id': 9, 'available': True, 'attributes': attrs}


@pytest.fixture
def static_blueprint():
    from aot.functions.custom_functions.device_matter_node import FUNCTION_INFORMATION
    return FUNCTION_INFORMATION['device_blueprint']


def _by_driver(blueprint):
    result = {}
    for spec in blueprint['outputs']:
        result.setdefault(spec['device'], []).append(spec)
    return result


def test_blueprint_one_covering_output_per_endpoint_and_one_dimmer(static_blueprint):
    blueprint = matter_onboarding.build_blueprint(static_blueprint, _blueprint_node())
    outputs = _by_driver(blueprint)
    # 디머 엔드포인트의 OnOff 는 디머가 대신하므로 별도 스위치 없음
    assert set(outputs) == {'MATTER_LEVEL', 'MATTER_COVERING'}

    (level,) = outputs['MATTER_LEVEL']
    assert level['inherit_options'] == ['node_id']
    assert level['channels'] == [{'name': 'Dimmer', 'measurement': 'duty_cycle',
                                  'unit': 'percent', 'endpoint': 3}]

    covers = outputs['MATTER_COVERING']
    assert len(covers) == 2
    assert [len(c['channels']) for c in covers] == [1, 1]
    assert [c['channels'][0]['endpoint'] for c in covers] == [1, 2]
    assert all(c['channels'][0]['measurement'] == 'duty_cycle'
               and c['channels'][0]['unit'] == 'percent' for c in covers)
    assert all(c['inherit_options'] == ['node_id'] for c in covers)
    assert len({c['name'] for c in covers}) == 2
    assert len({c['channels'][0]['name'] for c in covers}) == 2
    assert all(c['name'].startswith('{device_name}') for c in covers)
    assert blueprint['inputs'] == []


def test_blueprint_single_covering_keeps_the_plain_name(static_blueprint):
    blueprint = matter_onboarding.build_blueprint(
        static_blueprint, _blueprint_node(coverings=(1,), dimmers=()))
    (cover,) = blueprint['outputs']
    assert cover['device'] == 'MATTER_COVERING' and cover['name'] == '{device_name}'
    assert cover['channels'] == [{'name': 'Curtain', 'measurement': 'duty_cycle',
                                  'unit': 'percent', 'endpoint': 1}]


def test_blueprint_dimmers_share_one_output_with_a_channel_each(static_blueprint):
    blueprint = matter_onboarding.build_blueprint(
        static_blueprint, _blueprint_node(coverings=(), dimmers=(1, 2)))
    (level,) = blueprint['outputs']
    assert [c['endpoint'] for c in level['channels']] == [1, 2]
    assert level['name'] == '{device_name}'


def test_blueprint_covering_without_lift_feature_is_not_offered(static_blueprint):
    node = _blueprint_node(coverings=(1,), dimmers=(), covering_feature=0b10)   # tilt 만
    assert matter_onboarding.build_blueprint(static_blueprint, node)['outputs'] == []


def test_blueprint_does_not_mutate_the_static_blueprint(static_blueprint):
    matter_onboarding.build_blueprint(static_blueprint, _blueprint_node())
    assert all('channels' not in spec for spec in static_blueprint['outputs'])


# --- 테스트 작성 중 드러난 모호한 동작을 고친 회귀 ---------------------------------

def test_dimmer_detects_on_off_from_cluster_list_not_cached_value(make_dimmer):
    """OnOff 값이 아직 없거나 null 이어도 클러스터가 있으면 끄기는 OnOff Off 다."""
    node = _dimmer_node()
    node['attributes']['1/6/0'] = None
    ctx = make_dimmer(node=node)
    assert ctx.module.output_switch('off') == (0, "")
    assert ctx.client.sent[-1][1]['cluster_id'] == 6
    assert ctx.client.sent[-1][1]['command_name'] == 'Off'


def test_dimmer_records_slow_drift(make_dimmer):
    """0.4 %씩 움직여도, 마지막으로 기록한 값에서 0.5 % 넘게 멀어지면 기록한다."""
    ctx = make_dimmer(node=_dimmer_node(level=100))
    start = len(ctx.influx)
    for level in (101, 102):            # 0.4 %씩
        ctx.client.report(NODE, '1/8/0', level)
    assert len(ctx.influx) == start + 1   # 102 는 기록 시점(100)에서 0.8 % 떨어짐


def test_covering_stale_persist_is_dropped(covering):
    """늦게 도착한 이동 중 기록이 정지 기록 뒤에 써지지 않는다."""
    module = covering.module
    module._last_persist[0] = (0.0, 40.0)    # 최신은 40 %
    module._persist(0, 70.0)                 # 이전 이동 중 값 — 버려야 한다
    covering.flush()
    assert all(val != 70.0 for _ch, _opt, val in covering.saved())
    module._persist(0, 40.0)
    assert (0, 'last_position_pct', 40.0) in covering.saved()



def test_blueprint_relay_plug_with_level_control_gets_a_switch_not_a_dimmer(static_blueprint):
    node = _blueprint_node(coverings=(), dimmers=(3,))
    node['attributes']['3/29/0'] = [{'0': 0x010A, '1': 3}]          # On/Off Plug-in Unit
    outputs = _by_driver(matter_onboarding.build_blueprint(static_blueprint, node))
    assert set(outputs) == {'MATTER_ON_OFF'}
    assert outputs['MATTER_ON_OFF'][0]['channels'][0]['endpoint'] == 3
    del node['attributes']['3/29/0']                                  # DeviceTypeList 없음
    assert set(_by_driver(matter_onboarding.build_blueprint(static_blueprint, node))) == {
        'MATTER_ON_OFF'}


# --- 커튼 저장 실패 재시도 ---------------------------------------------------------

def test_covering_failed_save_is_forgotten_so_the_next_report_retries(covering, monkeypatch):
    """set_custom_channel_option 은 성공할 때만 저장한 값을 돌려준다. 실패(None)면
    _last_persist 를 지워, 같은 위치의 다음 보고가 다시 저장을 시도하게 한다."""
    saved = []
    ok = {'value': False}

    def setter(ch, opt, val):
        saved.append((ch, opt, val))
        return val if ok['value'] else None

    monkeypatch.setattr(covering.module, 'set_custom_channel_option', setter)
    covering.report('1/258/10', 0, at=5000.0)
    covering.report('1/258/14', 3000)                                 # 70.0 — 저장 실패
    assert saved == [(0, 'last_position_pct', 70.0)]
    assert 0 not in covering.module._last_persist
    covering.report('1/258/10', 0)                                    # 같은 위치의 다른 보고
    assert saved == [(0, 'last_position_pct', 70.0)] * 2             # 다시 시도됨
    ok['value'] = True
    covering.report('1/258/10', 0)
    assert len(saved) == 3
    assert 0 in covering.module._last_persist
    covering.report('1/258/10', 0)                                    # 성공한 뒤엔 조용
    assert len(saved) == 3


def test_covering_save_returning_a_message_string_counts_as_failure(covering, monkeypatch):
    calls = []
    monkeypatch.setattr(covering.module, 'set_custom_channel_option',
                        lambda ch, opt, val: calls.append(val) or "Error: no row")
    covering.report('1/258/10', 0, at=6000.0)
    covering.report('1/258/14', 5000)
    assert calls == [50.0] and 0 not in covering.module._last_persist



def test_dimmer_on_report_ahead_of_level_is_not_a_spike(dimmer, monkeypatch):
    """끈 상태에서 30 % 로 켜면 장치는 OnOff=true 를 새 레벨보다 몇 ms 먼저 보낸다
    (E2E 실측). 그 사이 옛 레벨(예: 70 %)을 상태·기록으로 남기지 않는다."""
    from aot.outputs import pwm_matter_level as mod
    clock = {'t': 100.0}
    monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: clock['t']))
    dimmer.client.report(NODE, '1/8/0', 178)          # 옛 레벨 ≈ 70 %
    dimmer.client.report(NODE, '1/6/0', False)
    recorded_before = len(dimmer.influx)
    dimmer.module.output_switch('on', 'pwm', amount=30)
    dimmer.client.report(NODE, '1/6/0', True)         # 레벨보다 먼저 온 켜짐
    assert dimmer.module.output_states[0] == 30.0
    dimmer.client.report(NODE, '1/8/0', mod.duty_to_level(30))
    assert dimmer.module.output_states[0] == 30.0
    values = [list(m.values())[0]['value'] for _uid, m in dimmer.influx[recorded_before:]]
    assert all(abs(v - 30.0) < 0.5 for v in values), values


def test_covering_target_source_follows_our_last_command(covering):
    covering.module.output_switch('on', 'value', amount=30,
                                  additional_options={'source': 'manual'})
    covering.client.report(NODE, '1/258/11', 7000)
    assert covering.module.output_target_pct(0) == (30.0, 'manual')
    covering.client.report(NODE, '1/258/11', 2000)    # 다른 앱이 옮겼다
    assert covering.module.output_target_pct(0) == (80.0, 'system')


def test_dimmer_forgets_old_command_after_off_or_failure(dimmer, monkeypatch):
    """70 % 명령 → 끔 → 30 % 명령이 시간초과로 실패한 뒤, 늦게 온 옛 레벨(70 %)
    보고를 옛 명령값으로 '맞춰' 보이지 않는다(E2E 에서 본 70 % 스파이크)."""
    from aot.devices.matter_client import MatterCommandTimeout
    from aot.outputs import pwm_matter_level as mod
    clock = {'t': 100.0}
    monkeypatch.setattr(mod, 'time', SimpleNamespace(monotonic=lambda: clock['t']))
    dimmer.module.output_switch('on', 'pwm', amount=70)
    assert dimmer.module.output_switch('off') == (0, "")
    assert 0 not in dimmer.module._commanded
    dimmer.module.output_switch('on', 'pwm', amount=70)
    dimmer.client.fail_with = MatterCommandTimeout('device_command: no answer in 5s')
    code, _msg = dimmer.module.output_switch('on', 'pwm', amount=30)
    assert code == 1 and 0 not in dimmer.module._commanded
    clock['t'] += mod.SETTLE_S + 1
    dimmer.client.report(NODE, '1/6/0', True)
    dimmer.client.report(NODE, '1/8/0', mod.duty_to_level(70))
    assert dimmer.module.output_states[0] == mod.level_to_duty(mod.duty_to_level(70))
