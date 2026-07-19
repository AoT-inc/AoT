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

class MockEngine:
    def run_reasoning(self, context, prompt):
        return {"insight": "test", "actions": []}

class TestActionValidation(unittest.TestCase):
    
    def test_p1_strict_validation_fail(self):
        """P1: Verify validation fails if mandatory metadata is missing for MCP call."""
        # Missing server_id and tool_name
        action = {
            "action_type": "mcp_tool_call",
            "params": {}
        }
        valid, err = AIAgentService._validate_and_normalize_action(action)
        self.assertFalse(valid)
        self.assertIn("Missing mandatory metadata", err)

    def test_p2_normalization_internal_tool(self):
        """P2: Verify internal tools get system_internal server_id."""
        action = {
            "action_type": "virtual_tool_call",
            "params": {
                "tool_name": "add_schedule"
            }
        }
        valid, err = AIAgentService._validate_and_normalize_action(action)
        self.assertTrue(valid)
        self.assertEqual(action['params']['server_id'], 'system_internal')

    def test_p3_control_intent_guard(self):
        """P3: Verify _parse_failed is forced if control keywords found but no actions."""
        # Mocking AbstractAI since it's an abstract class
        class ConcreteAI(AbstractAI):
            def __init__(self):
                # Minimal mock for AbstractAI.__init__
                self.name = "Test AI"
                self.model_tier = "standard"
            def run_reasoning(self, context, goal): pass
            def parse_actions(self, raw_response): pass
            def _extract_json_from_text(self, text):
                # Simple fallback/mock behavior
                if "{" in text:
                    try: return json.loads(text)
                    except: return None
                return None
            def _get_control_keywords(self):
                # Mock keywords for testing (to match Scenario 1 & 2)
                return ['valve', 'turn on', 'turn off', 'switch', 'operate', '켜줘', '꺼줘', '동작', '조절', '밸브', '전등', '에어컨', '티비']

        ai = ConcreteAI()
        
        # Scenario 1: Valid JSON, describes valve but NO actions -> Should trigger _parse_failed
        raw_text = '{"insight": "I will turn on the valve for you.", "actions": []}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertTrue(result.get("_parse_failed"))
        
        # Scenario 2: Valid JSON, normal info, no actions -> Should NOT trigger _parse_failed
        raw_text = '{"insight": "The weather is nice today.", "actions": []}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertFalse(result.get("_parse_failed", False))

        # Scenario 3: Valid JSON, describes valve AND has action -> Should NOT trigger _parse_failed (correct behavior)
        raw_text = '{"insight": "Turning on valve", "actions": [{"action_type": "virtual_tool_call", "params": {"tool_name": "operate_device"}}]}'
        result = ai._safe_api_result(raw_text, "TestEngine")
        self.assertFalse(result.get("_parse_failed", False))
        self.assertEqual(len(result["actions"]), 1)

if __name__ == '__main__':
    unittest.main()
