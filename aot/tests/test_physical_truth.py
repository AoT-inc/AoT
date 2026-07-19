import unittest
import json
from unittest.mock import MagicMock, patch
from aot.ai.services.ai_agent_service import AIAgentService

class TestPhysicalTruth(unittest.TestCase):
    def setUp(self):
        from aot.aot_flask.app import create_app
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.service = AIAgentService()

    def tearDown(self):
        self.app_context.pop()

    @patch('aot.databases.models.AIHistory.save', MagicMock())
    @patch('aot.databases.models.AIHistory', MagicMock())
    @patch('aot.ai.services.ai_action_service.AIActionService.execute_action')
    @patch('aot.ai.services.ai_agent_service.AIAgentService._validate_and_normalize_action')
    def test_p2_verification_loop_failure(self, mock_normalize, mock_execute):
        """Verify that _dispatch_actions records the tool result in immediate_results."""
        mock_normalize.return_value = (True, None)
        # Mocking a tool that returns a success result without a proof key
        mock_execute.return_value = {"status": "success", "result": {"message": "Saved (but no ID)"}}

        # Use a tool that doesn't require approval (unlike add_schedule)
        actions = [{"action_type": "virtual_tool_call", "params": {"tool_name": "get_sensor_detail"}}]

        # We need to mock IMMEDIATE_ACTIONS containing 'virtual_tool_call'
        with patch('aot.ai.services.ai_agent_service.IMMEDIATE_ACTIONS', ['virtual_tool_call']):
            # Results is a dict. We need to check immediate_results.
            results_dict = AIAgentService._dispatch_actions("agent_1", "goal", "insight", actions)
            immediate_results = results_dict.get('immediate_results', [])

            # _dispatch_actions must record the tool result as a string entry
            self.assertTrue(len(immediate_results) > 0,
                            f"Expected at least one entry in immediate_results, got: {immediate_results}")
            result_str = immediate_results[0]
            self.assertIsInstance(result_str, str)
            self.assertIn("virtual_tool_call", result_str)
            self.assertIn("success", result_str)


    @patch('aot.databases.models.ai.AIAgent.query')
    @patch('aot.ai.services.ai_agent_service.AIAgentService.get_engine')
    def test_p1_synthesizer_post_processing(self, mock_get_engine, mock_agent_query):
        """Verify that run_synthesizer prepends failure status and strips hallucinations."""
        # 1. Setup Mock Synth Agent
        mock_synth = MagicMock()
        mock_synth.unique_id = "synth_1"
        mock_agent_query.filter_by.return_value.first.return_value = mock_synth
        
        # 2. Setup Mock Engine
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        # Hallucinated success in English
        mock_engine.run_reasoning.return_value = {
            "insight": "I have successfully added the schedule to your calendar. You are all set.",
            "verification": {"passed": True}
        }
        
        # 3. Execution results with NO success (missing proof)
        execution_results = ["Immediate Action 'virtual_tool_call' Failed: Physical Truth Violation..."]
        
        result = AIAgentService.run_synthesizer(
            execution_results=execution_results,
            intent="CONTROL",
            original_command="Add a meeting at 5pm"
        )
        
        # 4. Verify Insight
        insight = result['insight']
        self.assertIn("[ALARM: Execution Failed]", insight)
        self.assertNotIn("I have successfully added", insight)
        self.assertIn("to your calendar", insight.lower()) # Remaining part (case-insensitive check)
        
        # 5. Verify status override
        self.assertFalse(result['verification']['passed'])
        self.assertEqual(result['verification']['reason'], "Physical Verification Failed (Law 3)")


    @patch('aot.databases.models.ai.AIAgent.query')
    @patch('aot.ai.services.ai_agent_service.AIAgentService.get_engine')
    def test_p1_synthesizer_post_processing_korean(self, mock_get_engine, mock_agent_query):
        """Verify Korean hallucination stripping and prefix."""
        mock_synth = MagicMock()
        mock_agent_query.filter_by.return_value.first.return_value = mock_synth
        mock_get_engine.return_value = MagicMock()
        
        # Hallucinated success in Korean
        mock_get_engine.return_value.run_reasoning.return_value = {
            "insight": "성공적으로 일정을 등록했습니다. 확인해 주세요.",
            "verification": {"passed": True}
        }
        
        result = AIAgentService.run_synthesizer(
            execution_results=[], # No results = no success
            intent="CONTROL",
            original_command="일정 등록해줘"
        )
        
        insight = result['insight']
        self.assertIn("[실패: 명령 수행 불가]", insight)
        self.assertNotIn("성공적으로", insight)
        self.assertNotIn("등록했습니다", insight)
        self.assertIn("확인해 주세요", insight)

if __name__ == '__main__':
    unittest.main()
