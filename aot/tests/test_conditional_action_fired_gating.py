# coding=utf-8
"""conditional_fired 는 "체크 주기가 돌았다"가 아니라 "액션이 실제로 실행됐다"일
때만 나가야 한다.

`ConditionalController.loop()`가 활성 Conditional의 매 period 틱마다
(condition 이 실제로 참이었는지와 무관하게) 무조건 `conditional_fired` 를
보냈고, `_handle_fired_event`(ai_scheduler_service.py)가 이를 받아
`scheduler_jobs_meta` 에 영구 행을 남겼다. period=60초인 Conditional 2개가
2026-07-19부터 계속 돌며 aot-005 한 대에서만 41,000행 이상을 쌓았고,
`/scheduler` 페이지 타임라인(created_at desc LIMIT 200)이 이 노이즈로
채워져 실제 일정이 화면에서 밀려났다. (project_scheduler_conditional_flood_incident
메모리 참고)

수정은 `AbstractConditional.run_action()`/`run_all_actions()` — 사용자가
편집하는 conditional_statement 가 아니라 그 코드가 액션을 실행할 때 반드시
거치는 **베이스 클래스** 메서드 — 에 `action_fired` 플래그를 심고,
`ConditionalController`가 매 체크 직전 리셋 + 액션이 실제로 실행됐을 때만
신호를 보내도록 게이팅한다. 실제 장치 제어 RPC(DaemonControl)는 이 테스트가
전혀 건드리지 않는다 — 그쪽을 손대지 않은 것이 이 수정을 안전하게 만드는
핵심이었다.

DB·데몬·무선을 쓰지 않는다(FakeControl로 RPC 대체, __new__로 threading.Thread
초기화 우회, db_retrieve_table_daemon 패치).
"""
import time
from unittest.mock import Mock, patch

from aot.controllers.base_conditional import AbstractConditional
from aot.controllers.controller_conditional import ConditionalController


class _FakeControl:
    """DaemonControl 대역 — 실제 Pyro RPC를 전혀 만들지 않는다."""

    def __init__(self):
        self.trigger_action_calls = []
        self.trigger_all_actions_calls = []

    def trigger_action(self, action_id, value=None, debug=False):
        self.trigger_action_calls.append((action_id, value))
        return {}

    def trigger_all_actions(self, function_id, message='', debug=False):
        self.trigger_all_actions_calls.append((function_id, message))
        return message

    def get_condition_measurement(self, condition_id):
        return 1.0


def _make_conditional():
    cond = AbstractConditional(
        logger=Mock(), function_id='11111111-1111-1111-1111-111111111111',
        message='')
    cond.control = _FakeControl()
    return cond


class TestActionFiredFlag:
    """AbstractConditional — action_fired는 사용자 코드가 액션 함수를 실제로
    부를 때만 True가 된다."""

    def test_fresh_instance_starts_false(self):
        assert _make_conditional().action_fired is False

    def test_run_action_sets_flag_and_still_calls_control(self):
        cond = _make_conditional()
        cond.run_action('22222222-2222-2222-2222-222222222222')
        assert cond.action_fired is True
        assert cond.control.trigger_action_calls, \
            "행동 변화 없이 플래그만 세우면 안 된다 — 실제 RPC 호출은 그대로 유지"

    def test_run_all_actions_sets_flag_and_still_calls_control(self):
        cond = _make_conditional()
        cond.run_all_actions()
        assert cond.action_fired is True
        assert cond.control.trigger_all_actions_calls

    def test_reading_a_condition_alone_does_not_set_flag(self):
        """조건만 읽고 액션을 안 부른 사이클(=아무 일도 안 일어난 흔한 경우)은
        플래그를 세우면 안 된다 — 이게 세워지면 원래 버그가 그대로 재발한다."""
        cond = _make_conditional()
        cond.condition('33333333-3333-3333-3333-333333333333')
        assert cond.action_fired is False


def _make_controller():
    """threading.Thread.__init__ 등 무거운 생성자를 건너뛰고 loop()/
    check_conditionals()가 실제로 쓰는 속성만 채운 컨트롤러."""
    ctrl = ConditionalController.__new__(ConditionalController)
    ctrl.pause_loop = False
    ctrl.is_activated = True
    ctrl.period = 60
    ctrl.timer_period = time.time() - 1  # 이미 도래
    ctrl.unique_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    ctrl.logger = Mock()
    ctrl.message_include_code = False
    return ctrl


class TestLoopGatesOnActionFired:
    """loop() 은 conditional_run.action_fired 가 True 일 때만 신호를 보낸다."""

    @patch('aot.controllers.controller_conditional.db_retrieve_table_daemon')
    @patch('aot.controllers.controller_conditional.conditional_fired')
    def test_signal_sent_when_action_fired(self, mock_signal, mock_db):
        cond_row = Mock()
        cond_row.name = 'Test Conditional'
        mock_db.return_value = cond_row

        ctrl = _make_controller()
        ctrl.conditional_run = Mock(action_fired=True)
        ctrl.check_conditionals = Mock()  # 실행 결과로 이미 True가 됐다고 가정

        ctrl.loop()

        assert mock_signal.send.called

    @patch('aot.controllers.controller_conditional.db_retrieve_table_daemon')
    @patch('aot.controllers.controller_conditional.conditional_fired')
    def test_signal_not_sent_when_nothing_fired(self, mock_signal, mock_db):
        """이게 이번 수정의 핵심 회귀 방지 지점 — 이 assert가 없으면 원래
        버그(매 틱 무조건 발신)가 조용히 재발해도 안 잡힌다."""
        ctrl = _make_controller()
        ctrl.conditional_run = Mock(action_fired=False)
        ctrl.check_conditionals = Mock()

        ctrl.loop()

        assert not mock_signal.send.called
        assert not mock_db.called, \
            "신호를 안 보낼 거면 이름 조회(DB 접근)도 할 필요 없다"

    @patch('aot.controllers.controller_conditional.db_retrieve_table_daemon')
    @patch('aot.controllers.controller_conditional.conditional_fired')
    def test_not_activated_skips_entirely(self, mock_signal, mock_db):
        ctrl = _make_controller()
        ctrl.is_activated = False
        ctrl.conditional_run = Mock(action_fired=True)
        ctrl.check_conditionals = Mock()

        ctrl.loop()

        assert not ctrl.check_conditionals.called
        assert not mock_signal.send.called


class TestCheckConditionalsResetsFlagEveryCycle:
    """check_conditionals() 는 매 호출 시작에서 무조건 리셋한다 — 이전 사이클의
    True가 이번 사이클로 새어 들어오면 안 된다(정상 경로·조기 반환 경로 둘 다)."""

    @patch('aot.controllers.controller_conditional.db_retrieve_table_daemon')
    def test_reset_before_running_user_code(self, mock_db):
        cond_row = Mock()
        cond_row.name = 'Test Conditional'
        mock_db.return_value = cond_row

        ctrl = _make_controller()
        ctrl.time_conditional = time.time()
        # 이전 사이클에서 True로 남아있던 상태를 흉내
        ctrl.conditional_run = Mock(action_fired=True)

        ctrl.check_conditionals()

        # conditional_code_run()은 Mock이라 아무것도 다시 세우지 않으므로,
        # 여기서 False라는 것은 곧 진입 시점에 리셋이 실제로 일어났다는 뜻이다.
        assert ctrl.conditional_run.action_fired is False
        assert ctrl.conditional_run.conditional_code_run.called

    @patch('aot.controllers.controller_conditional.db_retrieve_table_daemon')
    def test_reset_even_on_early_return(self, mock_db):
        mock_db.return_value = None  # Conditional 행을 못 읽는 경로

        ctrl = _make_controller()
        ctrl.time_conditional = time.time()
        ctrl.conditional_run = Mock(action_fired=True)

        ctrl.check_conditionals()

        assert ctrl.conditional_run.action_fired is False
        assert not ctrl.conditional_run.conditional_code_run.called
