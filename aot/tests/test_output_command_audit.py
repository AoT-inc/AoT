# coding=utf-8
"""Output 명령 감사 게이트 회귀 테스트.

배경: 2026-08-06 aot-005 에서 관수 출력이 43분간 켜졌는데 "누가 켰나"에 답할 수
없었다. 라우트마다 감사로그를 심는 방식은 새 경로가 생길 때마다 조용히 빠지므로,
모든 명령이 지나는 단일 게이트(`OutputController.output_on_off`)에서만 기록한다.

여기서 지키려는 성질 넷:
1. 출처 판정이 호출자 스레드에서 끝난다 (RPC 경계를 넘지 않는다)
2. **오귀속이 없다** — 워커 스레드 재사용으로 남은 컨텍스트가 다음 명령에 붙지 않는다
3. 자동화는 관계형 감사로그를 채우지 않는다 (티어 분리)
4. 감사 실패·큐 포화가 제어를 막지 않는다
"""
import logging
import queue
import threading

import pytest

from aot.controllers.base_controller import AbstractController, _controller_kind
from aot.controllers.controller_output import OutputController
from aot.utils import command_origin, output_audit
from aot.utils.command_origin import (ROLE_DAEMON, resolve_origin,
                                      set_process_role, should_audit)
from aot.utils.execution_context import (clear_execution_context,
                                         clear_thread_default, get_context,
                                         set_execution_context,
                                         set_thread_default)


@pytest.fixture(autouse=True)
def _clean_state():
    """각 테스트는 깨끗한 프로세스 역할·컨텍스트·큐에서 시작한다."""
    clear_execution_context()
    clear_thread_default()
    command_origin._process_role = None
    output_audit._q = queue.Queue(maxsize=output_audit._MAXSIZE)
    output_audit._dropped = 0
    yield
    clear_execution_context()
    clear_thread_default()
    command_origin._process_role = None


class _Driver:
    """드라이버 스텁. 호출 시점의 실행 컨텍스트를 붙잡아 둔다.

    base_output 이 get_extra_tags() 로 읽는 바로 그 시점을 흉내낸다 — 여기서
    컨텍스트가 비어 있으면 InfluxDB source_type 태그도 비어서 나간다.
    """

    def __init__(self, ret=(0, 'ok'), raises=False, options_channels=None):
        self.output_name = '관수: 미니스프링클러'
        self._ret = ret
        self._raises = raises
        self.seen_context = None
        self.calls = 0
        # 드라이버가 기동/종료 때 하드웨어로 내보내는 상태. -1 = 아무것도 안 함,
        # None = suppress_state_transition() 이 억제한 채널.
        self.options_channels = options_channels or {}

    def output_on_off(self, state, **kwargs):
        self.calls += 1
        self.seen_context = get_context()
        if self._raises:
            raise RuntimeError('드라이버 실패')
        return self._ret


class _Gate:
    """OutputController 에서 게이트 부분만 떼어낸 최소 구성."""

    output_on_off = OutputController.output_on_off
    _audit_command = OutputController._audit_command
    _audit_lifecycle = OutputController._audit_lifecycle

    def __init__(self, driver=None):
        self.output = {'out-1': driver} if driver is not None else {}
        self.logger = logging.getLogger('gate-test')


def _drain():
    items = []
    while True:
        try:
            items.append(output_audit._q.get_nowait())
        except queue.Empty:
            return items


# ---------------------------------------------------------------- 출처 판정

def test_daemon_without_context_is_automation_not_unknown():
    """데몬 내부 자동화가 unknown 으로 새면 감사로그가 잠기고 가짜 경보가 난다."""
    set_process_role(ROLE_DAEMON)
    assert resolve_origin()['type'] == 'automation'


def test_explicit_context_wins():
    set_process_role(ROLE_DAEMON)
    set_execution_context(source_type='trigger', source_id='trg-1')
    origin = resolve_origin()
    assert origin['type'] == 'trigger'
    assert origin['id'] == 'trg-1'


def test_no_role_no_context_is_unknown():
    """정체를 못 밝히는 경로는 unknown — 이게 우회 탐지 신호다."""
    assert resolve_origin()['type'] == 'unknown'


@pytest.mark.parametrize('origin_type,expected', [
    ('user', True), ('api', True), ('ai', True), ('unknown', True),
    ('automation', False), ('trigger', False), ('conditional', False),
    ('scheduler', False),
])
def test_audit_tiering(origin_type, expected):
    assert should_audit({'type': origin_type}) is expected


# ------------------------------------------------------------------ 게이트

def test_gate_sets_context_for_driver():
    """드라이버가 실행되는 시점에 컨텍스트가 살아 있어야 InfluxDB 태그가 찍힌다.

    예전에는 호출자 스레드에만 심어서 RPC 를 건너며 유실됐고, 그 결과 30일치
    InfluxDB 에 source_type 태그가 한 건도 없었다.
    """
    driver = _Driver()
    gate = _Gate(driver)
    gate.output_on_off('out-1', 'on', origin={'type': 'user', 'id': 7})

    assert driver.seen_context['source_type'] == 'user'
    assert driver.seen_context['source_id'] == 7


def test_gate_clears_context_after_command():
    driver = _Driver()
    gate = _Gate(driver)
    gate.output_on_off('out-1', 'on', origin={'type': 'user', 'id': 7})
    assert get_context()['source_type'] is None


def test_gate_clears_context_even_when_driver_raises():
    """드라이버가 터져도 컨텍스트는 반드시 지워진다 — 안 그러면 다음 명령이 오염된다."""
    driver = _Driver(raises=True)
    gate = _Gate(driver)
    with pytest.raises(RuntimeError):
        gate.output_on_off('out-1', 'on', origin={'type': 'user', 'id': 7})
    assert get_context()['source_type'] is None


def test_no_misattribution_on_thread_reuse():
    """R5: 워커 스레드가 재사용돼도 이전 명령의 행위자가 다음 명령에 붙으면 안 된다.

    이 테스트가 이 파일에서 제일 중요하다. 틀린 행위자 기록은 기록이 없는 것보다
    나쁘다 — 무고한 사람이 조작 주체로 남기 때문이다.
    """
    driver = _Driver()
    gate = _Gate(driver)
    seen = []

    def worker():
        # 1) 자동화 명령이 먼저 이 스레드를 쓴다
        gate.output_on_off('out-1', 'on', origin={'type': 'trigger', 'id': 'trg-1'})
        seen.append(driver.seen_context['source_type'])
        # 2) 같은 스레드가 곧바로 사용자 명령을 처리한다
        gate.output_on_off('out-1', 'off', origin={'type': 'user', 'id': 42})
        seen.append(driver.seen_context['source_type'])
        # 3) 출처를 안 준 명령 — 이전 값이 새어나오면 안 된다
        gate.output_on_off('out-1', 'off')
        seen.append(driver.seen_context['source_type'])

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert seen == ['trigger', 'user', None]


def test_gate_queues_user_command_only():
    """자동화는 큐에 안 들어간다 (티어 분리). 사람 명령만 들어간다."""
    driver = _Driver()
    gate = _Gate(driver)

    gate.output_on_off('out-1', 'on', origin={'type': 'automation'})
    assert _drain() == []

    gate.output_on_off('out-1', 'on', origin={'type': 'user', 'id': 42,
                                              'name': 'aot', 'ip': '10.0.0.9'})
    entries = _drain()
    assert len(entries) == 1
    assert entries[0]['origin']['name'] == 'aot'
    assert entries[0]['ip_address'] == '10.0.0.9'
    assert entries[0]['output_name'] == '관수: 미니스프링클러'
    assert entries[0]['result'] == 'success'


def test_gate_records_unknown_origin():
    """출처 불명 명령은 반드시 남아야 한다 — 그게 우회 탐지의 전부다."""
    driver = _Driver()
    gate = _Gate(driver)
    gate.output_on_off('out-1', 'on')
    entries = _drain()
    assert len(entries) == 1
    assert entries[0]['origin'] == {}


def test_gate_records_failure_result():
    driver = _Driver(ret=(1, '실패'))
    gate = _Gate(driver)
    gate.output_on_off('out-1', 'on', origin={'type': 'user', 'id': 1})
    assert _drain()[0]['result'] == 'failure'


def test_missing_output_is_audited_as_failure():
    gate = _Gate()  # 등록된 output 없음
    err, _ = gate.output_on_off('nope', 'on', origin={'type': 'user', 'id': 1})
    assert err == 1
    assert _drain()[0]['result'] == 'failure'


# -------------------------------------------------------------------- 큐

def test_queue_overflow_drops_and_counts_instead_of_blocking():
    """큐가 차도 제어는 계속돼야 하고, 버린 건수는 세어져야 한다 (조용한 유실 금지)."""
    output_audit._q = queue.Queue(maxsize=2)
    for _ in range(5):
        output_audit.record({'output_id': 'x'})
    assert output_audit._q.qsize() == 2
    assert output_audit._dropped == 3


def test_record_never_raises():
    output_audit._q = None  # 큐 자체를 망가뜨려도
    output_audit.record({'output_id': 'x'})  # 예외가 새면 제어가 막힌다


# --------------------------------- 자동화 세부 귀속 (스레드 기본값)

def test_thread_default_fills_origin_when_no_override():
    """컨트롤러 스레드가 자기 정체를 등록하면 그 스레드 명령이 이를 물려받는다."""
    set_process_role(ROLE_DAEMON)
    set_thread_default(source_type='pid', source_id='pid-1')
    origin = resolve_origin()
    assert origin['type'] == 'pid'
    assert origin['id'] == 'pid-1'


def test_override_beats_thread_default():
    set_thread_default(source_type='function', source_id='fn-1')
    set_execution_context(source_type='ai', source_id='agent-9')
    assert resolve_origin()['type'] == 'ai'


def test_clear_execution_context_keeps_thread_default():
    """override 만 지워야 한다.

    기본값까지 지우면 Trigger 가 한 번 발화한 뒤로 그 스레드의 후속 명령이
    주인을 잃는다 — 컨트롤러 스레드는 계속 살아 있기 때문이다.
    """
    set_thread_default(source_type='trigger', source_id='trg-1')
    set_execution_context(source_type='ai', source_id='agent-9')
    clear_execution_context()
    assert resolve_origin()['type'] == 'trigger'
    assert resolve_origin()['id'] == 'trg-1'


@pytest.mark.parametrize('class_name,expected', [
    ('PIDController', 'pid'),
    ('FunctionController', 'function'),
    ('ConditionalController', 'conditional'),
    ('OutputController', 'output'),
    ('TriggerSequenceController', 'triggersequence'),
    ('Weird', 'weird'),
])
def test_controller_kind_naming(class_name, expected):
    assert _controller_kind(class_name) == expected


def test_controller_run_registers_its_identity():
    """AbstractController.run() 한 곳이 44개 컨트롤러·Function 을 전부 덮는다."""
    seen = {}

    class PIDController(AbstractController):  # 실제 클래스명 그대로 (밑줄 없음)
        def __init__(self):
            pass  # 기반 __init__ 은 DB 를 건드리므로 건너뛴다

        def initialize_variables(self):
            seen.update(get_context())

        def loop(self):
            pass

        def run_finally(self):
            pass

    ctrl = PIDController()
    ctrl.unique_id = 'pid-1'
    ctrl.running = False
    ctrl.thread_startup_timer = 0
    ctrl.thread_shutdown_timer = 0
    ctrl.logger = logging.getLogger('run-test')
    ctrl.run()

    assert seen['source_type'] == 'pid'
    assert seen['source_id'] == 'pid-1'


def test_automation_kinds_stay_out_of_audit_log():
    """세부 귀속이 생겨도 자동화는 여전히 관계형 감사로그를 채우지 않는다."""
    for kind in ('pid', 'function', 'input', 'output', 'widget',
                 'triggersequence', 'automation'):
        assert should_audit({'type': kind}) is False


# ------------------------------------------------------------ AI / MCP

def test_ai_origin_is_audited():
    """AI 명령은 사람 명령과 구분돼 남아야 한다 — unknown 으로 섞이면 안 된다."""
    set_execution_context(source_type='ai', source_id='agent-9')
    origin = resolve_origin()
    assert origin['type'] == 'ai'
    assert origin['id'] == 'agent-9'
    assert should_audit(origin) is True


def test_mcp_process_is_ai_not_unknown():
    """MCP 서버는 flask_login 이 없어 사용자를 못 뽑는다.

    표시하지 않으면 외부 AI 명령이 전부 unknown 으로 남아 진짜 우회와 섞인다.
    """
    set_process_role(command_origin.ROLE_MCP)
    origin = resolve_origin()
    assert origin['type'] == 'ai'
    assert should_audit(origin) is True


# ------------------------------------------- 드라이버 생명주기 (게이트 밖 경로)

def test_lifecycle_startup_state_is_recorded():
    """데몬 기동 시 드라이버가 하드웨어를 직접 켜는 것도 기록돼야 한다.

    이 경로는 output_on_off 를 지나지 않는다(on_off_gpio 는 initialize() 안에서
    GPIO.output() 을 그냥 호출한다). 안 남기면 "아무도 안 켰는데 켜져 있다" 가 된다.
    """
    driver = _Driver(options_channels={'state_startup': {0: 1, 1: 0}})
    gate = _Gate(driver)
    gate._audit_lifecycle('out-1', 'state_startup', 'daemon_startup')

    entries = sorted(_drain(), key=lambda e: e['channel'])
    assert [e['state'] for e in entries] == ['on', 'off']
    assert all(e['origin']['type'] == 'lifecycle' for e in entries)
    assert all(e['origin']['id'] == 'daemon_startup' for e in entries)
    assert entries[0]['output_name'] == '관수: 미니스프링클러'


def test_lifecycle_skips_do_nothing_and_suppressed_channels():
    """-1(아무것도 안 함)과 None(억제됨)은 실제 전송이 없으니 기록도 없어야 한다.

    없는 전송을 남기면 감사로그가 거짓말을 하게 된다.
    """
    driver = _Driver(options_channels={'state_shutdown': {0: -1, 1: None, 2: 0}})
    gate = _Gate(driver)
    gate._audit_lifecycle('out-1', 'state_shutdown', 'daemon_shutdown')

    entries = _drain()
    assert len(entries) == 1
    assert entries[0]['channel'] == 2
    assert entries[0]['state'] == 'off'


def test_lifecycle_is_silent_when_module_lacks_the_option():
    driver = _Driver(options_channels={})
    gate = _Gate(driver)
    gate._audit_lifecycle('out-1', 'state_startup', 'daemon_startup')
    assert _drain() == []


def test_lifecycle_origin_is_audited():
    """생명주기 전송은 저빈도이고 물리 상태를 바꾸므로 관계형 감사로그 대상이다."""
    assert should_audit({'type': 'lifecycle'}) is True


# ------------------------------------------------------- 버전 스큐 (R3)

class _OldProxy:
    """origin 인자를 모르는 구버전 데몬 흉내."""

    def __init__(self):
        self.calls = []

    def output_on(self, output_id, **kwargs):
        if 'origin' in kwargs:
            raise TypeError("output_on() got an unexpected keyword argument 'origin'")
        self.calls.append(kwargs)
        return 0, 'ok'

    def output_off(self, output_id, **kwargs):
        if 'origin' in kwargs:
            raise TypeError("output_off() got an unexpected keyword argument 'origin'")
        self.calls.append(kwargs)
        return 0, 'ok'


@pytest.mark.parametrize('method', ['output_on', 'output_off'])
def test_old_daemon_without_origin_still_controls(method):
    """업그레이드 중 aotflask 만 먼저 올라온 창에서도 제어가 막히면 안 된다.

    구버전 데몬은 origin kwarg 에 TypeError 를 낸다. 그때 출처를 포기하더라도
    장치 제어 자체는 성공해야 한다 — 감사 기능 때문에 관수가 멈추면 본말전도다.
    """
    from aot.aot_client import DaemonControl

    control = DaemonControl(pyro_timeout=5)  # DB 조회 경로를 피한다
    old = _OldProxy()
    control.proxy = lambda *a, **k: old

    err, msg = getattr(control, method)('out-1')
    assert err == 0
    assert len(old.calls) == 1
    assert 'origin' not in old.calls[0]


# ---- origin 정규화: 어떤 형태가 와도 기록은 남긴다 ----

def test_normalize_origin_passes_dicts_through():
    src = {'type': 'user', 'id': 3, 'name': 'aot'}
    assert command_origin.normalize_origin(src) is src


def test_normalize_origin_treats_none_as_empty():
    assert command_origin.normalize_origin(None) == {}


def test_normalize_origin_coerces_a_non_dict_instead_of_raising():
    """dict 가 아닌 출처가 실제로 들어온다(2026-08 관측).

    예전에는 `_flush_one` 이 여기서 터져 그 항목이 통째로 버려졌다.
    """
    got = command_origin.normalize_origin('not-a-dict')
    # 출처 불명은 unknown 이 담당한다 — 문자열을 그대로 type 에 넣으면
    # AUDITED_TYPES 에 없어 should_audit 이 걸러 버린다.
    assert got['type'] == command_origin.TYPE_UNKNOWN
    assert got['_coerced'] is True
    assert got['_raw'] == 'not-a-dict'


def test_should_audit_survives_a_non_dict_origin():
    # 판단이 안 서면 남기는 쪽 — 누락보다 과잉이 낫다.
    assert command_origin.should_audit('not-a-dict')
    assert command_origin.should_audit(None)
