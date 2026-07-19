# coding=utf-8
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path to find 'aot' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.ai.services.ai_action_service import AIActionService, InvalidToolError
from aot.ai.services.ai_agent_service import AIAgentService

class TestLLMOutputSchema(unittest.TestCase):

    @patch('aot.ai.services.mcp_bridge_service.MCPBridgeService.get_active_servers')
    def test_resolve_mcp_tool(self, mock_get_servers):
        """Verify that an MCP tool is correctly resolved to mcp_tool_call."""
        # Mock active servers
        mock_server = MagicMock()
        mock_server.unique_id = "test_server_1"
        mock_server.tool_names = ["get_weather", "get_forecast"]
        mock_get_servers.return_value = [mock_server]

        # Case 1: Direct tool_name resolution
        resolved = AIActionService.resolve_action("get_weather", {"location": "Seoul"})
        self.assertEqual(resolved['action_type'], 'mcp_tool_call')
        self.assertEqual(resolved['target_id'], 'test_server_1')
        self.assertEqual(resolved['params']['tool_name'], 'get_weather')
        self.assertEqual(resolved['params']['arguments']['location'], 'Seoul')

    def test_resolve_virtual_tool(self):
        """Verify that a virtual tool is correctly resolved to virtual_tool_call."""
        # 'operate_device' is in VIRTUAL_TOOL_REGISTRY
        resolved = AIActionService.resolve_action("operate_device", {"device_id": "val_001", "state": "on"})
        self.assertEqual(resolved['action_type'], 'virtual_tool_call')
        self.assertEqual(resolved['target_id'], 'system_internal')
        self.assertEqual(resolved['params']['tool_name'], 'operate_device')

    def test_resolve_invalid_tool(self):
        """Verify that an unknown tool raises InvalidToolError."""
        with self.assertRaises(InvalidToolError):
            AIActionService.resolve_action("non_existent_tool", {})

    @patch('aot.ai.services.ai_action_service.AIActionService.resolve_action')
    def test_aiactive_service_validation(self, mock_resolve):
        """Verify that AIAgentService validation correctly triggers resolution."""
        mock_resolve.return_value = {
            "action_type": "mcp_tool_call",
            "target_id": "resolved_server",
            "params": {"tool_name": "test_tool", "arguments": {"x": 1}}
        }

        # LLM output style: no action_type, only tool_name in params
        action = {
            "params": {
                "tool_name": "test_tool",
                "x": 1
            }
        }

        valid, msg = AIAgentService._validate_and_normalize_action(action)
        self.assertTrue(valid)
        self.assertEqual(action['action_type'], 'mcp_tool_call')
        self.assertEqual(action['target_id'], 'resolved_server')
        self.assertEqual(action['params']['tool_name'], 'test_tool')

    def test_history_stripping(self):
        """Verify that _strip_action_type_from_history removes action_type field."""
        legacy_message = {
            "role": "assistant",
            "content": '{"insight": "done", "actions": [{"action_type": "mcp_tool_call", "target_id": "srv1", "params": {"tool_name": "read"}}, {"action_type": "virtual_tool_call", "params": {"tool_name": "wait"}}]}'
        }
        
        stripped = AIAgentService._strip_action_type_from_history(legacy_message)
        content = stripped['content']
        
        self.assertNotIn('"action_type": "mcp_tool_call"', content)
        self.assertNotIn('"action_type": "virtual_tool_call"', content)
        self.assertIn('"tool_name": "..."', content)

if __name__ == '__main__':
    unittest.main()
