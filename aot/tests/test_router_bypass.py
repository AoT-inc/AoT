# coding=utf-8
import unittest
from unittest.mock import MagicMock, patch
import json
import sys
import os
import logging

# Set up logging for the test
logging.basicConfig(level=logging.INFO)

# Add parent directory to path to find 'aot' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.ai.services.ai_agent_service import AIAgentService
from aot.ai.agents.base_ai import AbstractAI

class TestRouterBypass(unittest.TestCase):

    def test_p1_global_semantic_guard_tool_names(self):
        """P1: Verify guard triggers for tool names in raw text even without intent check."""
        class MockConfig:
            def __init__(self):
                self.unique_id = "test_agent"
                self.name = "Test Agent"
                self.system_prompt = "Test"
                self.temperature = 0.7
                self.entry = MagicMock()
                self.entry.api_endpoint = "http://test"
                self.entry.auth_type = "api_key"
                self.entry.auth_id = "test"
                self.entry.api_key = "test"
                self.entry.model_type = "test"
                self.entry.model_name = "test"

        class ConcreteAI(AbstractAI):
            def __init__(self, cfg):
                super().__init__(cfg)
            def run_reasoning(self, context, goal): pass
            def parse_actions(self, raw_response): pass
            def _extract_json_from_text(self, text):
                try: return json.loads(text)
                except: return None
            def _get_control_keywords(self): return ['turn on']
            def _get_completion_indicators(self): return ['done']
            
        with patch('aot.ai.services.ai_action_service.AIActionService.get_action_manifest') as mock_manifest:
            # Mock manifest with a specific tool name 'valve_301'
            mock_manifest.return_value = {
                'outputs': [{'name': 'valve_301'}],
                'mcp_tools': [{'tool_name': 'query_grafana'}]
            }
            
            ai = ConcreteAI(MockConfig())
            
            # Scenario: Mentioning tool name 'valve_301' + completion claim
            raw_text = '{"insight": "I have successfully opened valve_301. done", "actions": []}'
            result = ai._safe_api_result(raw_text, "TestEngine")
            
            self.assertTrue(result.get("_parse_failed"))
            self.assertTrue(result.get("_semantic_guard_hit"))
            logging.info("P1: Tool-name based semantic guard triggered correctly.")

    def test_p2_fast_path_escalation(self):
        """P2: Verify Fast Path escalates on semantic guard trigger."""
        with patch('aot.ai.services.ai_agent_service.AIAgentService.get_cached_agent') as mock_get_cached, \
             patch('aot.ai.services.ai_agent_service.AIAgentService.get_engine') as mock_get_engine, \
             patch('aot.ai.services.ai_agent_service.AIContextService.get_mini_context') as mock_ctx, \
             patch('aot.ai.services.ai_action_service.AIActionService.get_action_manifest') as mock_man:
            
            # Setup mock agent/engine
            mock_agent = MagicMock()
            mock_agent.unique_id = "fast_worker"
            mock_get_cached.return_value = mock_agent
            
            mock_engine = MagicMock()
            mock_get_engine.return_value = mock_engine
            
            # Mock engine output that triggers semantic guard
            mock_engine.run_reasoning.return_value = {
                "insight": "Valve opened.",
                "actions": [],
                "_parse_failed": True,
                "_semantic_guard_hit": True
            }
            
            # Mock other dependencies
            mock_ctx.return_value = {}
            mock_man.return_value = {}
            
            # Execute Fast Path
            result = AIAgentService.run_fast_path("Open the valve", intent='DATA_QUERY')
            
            # Should return escalate status
            self.assertEqual(result['status'], 'escalate')
            self.assertIn("Semantic guard failure", result['reason'])
            logging.info("P2: Fast Path escalated correctly to full reasoning.")

if __name__ == '__main__':
    unittest.main()
