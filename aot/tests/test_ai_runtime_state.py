# coding=utf-8
"""AI 활성화 ↔ 작동 시작 분리의 회귀 테스트.

지키는 계약은 둘이다.

1. `ai_enabled` 만으로는 백그라운드 AI 가 돌지 않는다.
   예전에는 설정에서 AI 를 켜는 순간 스케줄러 잡이 전부 돌기 시작했고, 모델을
   하나도 등록하지 않은 서버에서는 매 주기 로그에
   `No suitable AI agent found for summary generation.` 만 쌓였다.

2. 활성 에이전트가 0 이면 모델을 부르는 잡은 돌지 않는다.
   "작동 시작" 을 켜 뒀더라도 물어볼 모델이 없으면 할 일이 없다.

사용자가 직접 부르는 채팅/조언/명령 경로(`ai_agent_service.py`,
`routes_ai_api.py`)도 `ai_autonomy_enabled()`(ai_enabled AND ai_running)를
거친다 — "작동 시작" 이 꺼져 있으면 채팅도 동작하지 않는다. 그쪽 진입점의
회귀는 이 파일이 아니라 각 서비스의 테스트가 맡는다.

Context Layer 레지스트리 파일 부재도 함께 고정한다: 파일이 없는 것은 고장이
아니라 "등록된 도메인 시설 없음" 이다.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.ai.services import ai_runtime_state
from aot.ai.services.ai_scheduler_service import _context_broadcast_job
from aot.tests.ai_scheduler_test_utils import ai_enabled, ai_scheduler_job_env


def _settings(**kwargs):
    s = MagicMock()
    s.ai_enabled = kwargs.get('ai_enabled', True)
    s.ai_running = kwargs.get('ai_running', True)
    return s


class TestRuntimeGates(unittest.TestCase):
    """ai_runtime_state 의 판정 자체."""

    def test_enabled_but_not_started_is_not_autonomous(self):
        self.assertFalse(ai_runtime_state.ai_autonomy_enabled(
            _settings(ai_enabled=True, ai_running=False)))

    def test_started_but_disabled_is_not_autonomous(self):
        """설정에서 AI 를 꺼 두면 작동 스위치가 켜져 있어도 돌면 안 된다."""
        self.assertFalse(ai_runtime_state.ai_autonomy_enabled(
            _settings(ai_enabled=False, ai_running=True)))

    def test_enabled_and_started_is_autonomous(self):
        self.assertTrue(ai_runtime_state.ai_autonomy_enabled(
            _settings(ai_enabled=True, ai_running=True)))

    def test_background_needs_an_activated_agent(self):
        """모델이 0 개면 LLM 잡은 돌지 않는다 — 이게 로그 스팸의 원인이었다."""
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=0):
            self.assertFalse(ai_runtime_state.ai_background_active(_settings()))
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=1):
            self.assertTrue(ai_runtime_state.ai_background_active(_settings()))

    def test_skip_reason_names_the_actual_gate(self):
        """로그를 읽는 사람이 어느 스위치를 켜야 하는지 알 수 있어야 한다."""
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=1):
            self.assertIn('비활성', ai_runtime_state.background_skip_reason(
                _settings(ai_enabled=False)))
            self.assertIn('작동 시작', ai_runtime_state.background_skip_reason(
                _settings(ai_running=False)))
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=0):
            self.assertIn('모델', ai_runtime_state.background_skip_reason(_settings()))

    def test_missing_settings_row_is_not_running(self):
        """설정 레코드 자체가 없으면 안전한 쪽(작동 안 함)으로 떨어진다."""
        with patch.object(ai_runtime_state, 'get_settings', return_value=None):
            self.assertFalse(ai_runtime_state.ai_autonomy_enabled())
            self.assertFalse(ai_runtime_state.ai_background_active())

    def test_can_start_is_false_without_a_model(self):
        """화면의 시작 버튼은 모델이 없으면 눌릴 수 없어야 한다."""
        with patch.object(ai_runtime_state, 'get_settings', return_value=_settings()), \
                patch.object(ai_runtime_state, 'active_agent_count', return_value=0):
            self.assertFalse(ai_runtime_state.runtime_status()['can_start'])
        with patch.object(ai_runtime_state, 'get_settings', return_value=_settings()), \
                patch.object(ai_runtime_state, 'active_agent_count', return_value=2):
            status = ai_runtime_state.runtime_status()
        self.assertTrue(status['can_start'])
        self.assertEqual(status['agent_count'], 2)


class TestAutoStopWhenLastModelGoes(unittest.TestCase):
    """마지막 모델이 내려가면 작동 스위치도 내려간다.

    안 내리면 화면은 "작동 중" 인데 실제로는 아무것도 안 돌고, 나중에 모델을
    하나 되살리는 순간 사람이 아무 결정도 안 했는데 자율 작동이 재개된다.
    """

    def test_stops_when_no_agent_remains(self):
        settings = _settings(ai_running=True)
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=0), \
                patch.object(ai_runtime_state, 'get_settings', return_value=settings), \
                patch('aot.aot_flask.extensions.db') as mock_db:
            self.assertTrue(ai_runtime_state.stop_if_no_models())
        self.assertFalse(settings.ai_running)
        mock_db.session.commit.assert_called_once()

    def test_keeps_running_while_a_model_remains(self):
        settings = _settings(ai_running=True)
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=1), \
                patch.object(ai_runtime_state, 'get_settings', return_value=settings):
            self.assertFalse(ai_runtime_state.stop_if_no_models())
        self.assertTrue(settings.ai_running)

    def test_no_write_when_already_stopped(self):
        """이미 꺼져 있으면 커밋하지 않는다 — 무의미한 쓰기와 로그를 남기지 않는다."""
        settings = _settings(ai_running=False)
        with patch.object(ai_runtime_state, 'active_agent_count', return_value=0), \
                patch.object(ai_runtime_state, 'get_settings', return_value=settings), \
                patch('aot.aot_flask.extensions.db') as mock_db:
            self.assertFalse(ai_runtime_state.stop_if_no_models())
        mock_db.session.commit.assert_not_called()


class TestContextBroadcastRespectsRunningSwitch(unittest.TestCase):
    """잡 본문이 실제로 게이트를 지키는지 — 판정 함수만 맞으면 소용없다."""

    def _run_and_capture(self, **env):
        with ai_scheduler_job_env(**env), \
                patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                      '.get_all_active_facilities', return_value=['g_a']) as mock_step1, \
                patch('aot.ai.services.ai_context_service.AIContextService'
                      '.get_master_context', return_value={}, create=True), \
                patch('aot.ai.services.ai_summary_service.AISummaryService'
                      '.get_summary_history', return_value=[], create=True), \
                patch('aot.ai.services.ai_summary_service.AISummaryService'
                      '.generate_system_summary', return_value=None,
                      create=True) as mock_summary:
            _context_broadcast_job()
        return mock_step1, mock_summary

    def test_not_started_skips_everything(self):
        step1, summary = self._run_and_capture(ai_running=False)
        step1.assert_not_called()
        summary.assert_not_called()

    def test_no_activated_agent_skips_everything(self):
        """이 경로가 예전에 매 주기 ERROR 를 뱉던 자리다."""
        with ai_enabled(agent_count=0), \
                patch('aot.ai.services.ai_scheduler_service._flask_app') as app:
            app.app_context.return_value.__enter__ = MagicMock(return_value=None)
            app.app_context.return_value.__exit__ = MagicMock(return_value=False)
            with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                       '.get_all_active_facilities') as step1:
                _context_broadcast_job()
        step1.assert_not_called()

    def test_started_with_a_model_runs(self):
        step1, summary = self._run_and_capture()
        step1.assert_called_once()
        summary.assert_called_once()


class TestMissingFacilityRegistry(unittest.TestCase):
    """레지스트리 YAML 부재는 고장이 아니다."""

    def test_absent_registry_yields_no_facilities(self):
        from aot.ai.services.domain_context_loader import DomainContextLoader
        with tempfile.TemporaryDirectory() as empty_dir:
            with patch('aot.ai.services.domain_context_loader.CONTEXT_LAYER_ROOT',
                       empty_dir):
                DomainContextLoader.invalidate_cache()
                self.assertEqual(DomainContextLoader.get_all_active_facilities(), [])
                self.assertIsNone(DomainContextLoader.load_active_module('g_a'))
        DomainContextLoader.invalidate_cache()


if __name__ == '__main__':
    unittest.main()
