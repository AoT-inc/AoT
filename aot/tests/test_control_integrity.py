# coding=utf-8
import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os

# Add parent directory to path to find 'aot' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.ai.services.ai_agent_service import AIAgentService
from aot.ai.agents.base_ai import AbstractAI

class TestControlIntegrity(unittest.TestCase):

    def test_p1_phase4_coordinator_guard(self):
        """P1: Verify Synthesizer blocks success if intent is CONTROL but results are empty."""
        mock_agent = MagicMock()
        mock_agent.unique_id = "test_synth"

        mock_engine = MagicMock()
        mock_engine.run_reasoning.return_value = {
            "insight": "The valve has been turned on successfully.",
            "verification": {"passed": True}
        }

        with patch('aot.ai.services.ai_synthesis_service.AIAgent') as mock_ai_agent_model, \
             patch('aot.ai.services.ai_agent_service.AIAgentService.get_engine',
                   return_value=mock_engine):
            mock_ai_agent_model.query.filter_by.return_value.first.return_value = mock_agent

            # Scenario: Intent is CONTROL, but execution_results is empty
            result = AIAgentService.run_synthesizer(
                execution_results=[],
                intent='CONTROL',
                original_command="Turn on the valve"
            )

            # Post-processing must prepend failure prefix and override verification
            self.assertIsNotNone(result)
            self.assertIn("[ALARM: Execution Failed]", result['insight'])
            self.assertFalse(result['verification']['passed'])
            self.assertEqual(result['verification']['reason'], "Physical Verification Failed (Law 3)")

    def test_p2_semantic_guard_hallucination(self):
        """P2: Verify BaseAI catches past-tense completion claims without actions."""
        class ConcreteAI(AbstractAI):
            def __init__(self):
                self.name = "Test AI"
                self.model_tier = "standard"
            def run_reasoning(self, context, goal): pass
            def parse_actions(self, raw_response): pass
            def _extract_json_from_text(self, text):
                if "{" in text:
                    try: return json.loads(text)
                    except: return None
                return None
            def _get_control_keywords(self):
                return ['valve', '밸브']
            def _get_completion_indicators(self):
                return ['done', 'successfully', '켰습니다', '완료']

        ai = ConcreteAI()

        # Scenario 1: Hallucination - claims completion but no action JSON
        raw_text = '{"insight": "밸브 전원을 켰습니다.", "actions": []}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertTrue(result.get("_parse_failed"))

        # Scenario 2: Hallucination - uses "done" but no action JSON
        raw_text = '{"insight": "Operation is done.", "actions": []}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertTrue(result.get("_parse_failed"))

        # Scenario 3: Legitimate - claims completion AND has action
        raw_text = '{"insight": "켰습니다", "actions": [{"action_type": "virtual_tool_call", "params": {"tool_name": "valve_on"}}]}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertFalse(result.get("_parse_failed", False))

    def test_p2_semantic_guard_normal_info(self):
        """P2: Verify normal info (no completion/control) doesn't trigger guard."""
        class ConcreteAI(AbstractAI):
            def __init__(self): self.name = "Test AI"
            def run_reasoning(self, context, goal): pass
            def parse_actions(self, raw_response): pass
            def _extract_json_from_text(self, text): return json.loads(text)
            def _get_control_keywords(self): return ['valve']
            def _get_completion_indicators(self): return ['done']

        ai = ConcreteAI()
        raw_text = '{"insight": "The sun is hot.", "actions": []}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertFalse(result.get("_parse_failed", False))

if __name__ == '__main__':
    unittest.main()
