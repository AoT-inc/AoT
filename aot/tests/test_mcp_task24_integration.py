import os
import unittest
from unittest.mock import patch, MagicMock
from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models.mcp_server import MCPServer, AgentMCPAccess
from aot.databases.models.ai import AIAgent
from aot.ai.services.mcp_bridge_service import MCPBridgeService
from aot.ai.services.ai_action_service import AIActionService

class TestMCPTask24Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        # Clean up DB before each test
        AgentMCPAccess.query.delete()
        MCPServer.query.delete()
        AIAgent.query.delete()
        db.session.commit()
        # Reset Bridge caches
        MCPBridgeService._instances = {}
        MCPBridgeService._initialized = {}
        MCPBridgeService._failed_servers = {}

    def test_acl_deny(self):
        """Scenario 1: Verify 'Access Denied' when unauthorized tool called."""
        server_id = "test_server"
        agent_uid = "test_agent"
        
        # 1. Create mapping with restricted tool list
        mapping = AgentMCPAccess(
            agent_unique_id=agent_uid,
            mcp_unique_id=server_id,
            allowed_tools='["tool_a"]'
        )
        mapping.save()

        # 2. Mock Bridge to skip actual execution
        with patch.object(MCPBridgeService, 'get_server_process', return_value=MagicMock()):
            MCPBridgeService._initialized[server_id] = True
            
            # 3. Call unauthorized tool
            res = AIActionService.execute_action(
                action_type='mcp_tool_call',
                target_id=server_id,
                params={'tool_name': 'tool_b', 'agent_unique_id': agent_uid}
            )
            
            # 4. Verify Deny
            self.assertEqual(res['status'], 'error')
            self.assertIn("Access denied", res['message'])

    def test_mcp_resources_in_manifest(self):
        """Scenario 2: Confirm mcp_resources visible in get_action_manifest()."""
        server_id = "res_server"
        agent_uid = "test_agent"
        
        # 1. Create AIAgent
        agent = AIAgent(unique_id=agent_uid, name="Test Agent", tool_access='assigned', is_activated=True)
        agent.save()
        
        # 2. Create MCPServer
        server = MCPServer(unique_id=server_id, name="Resource Server", command="test", is_activated=True)
        server.save()
        
        # Mock get_resources
        mock_resources = [
            {'uri': 'test://res1', 'name': 'Resource 1', 'description': 'Test resource', 'mimeType': 'text/plain'}
        ]
        
        with patch.object(MCPBridgeService, 'get_resources', return_value=mock_resources):
            # 3. Create mapping
            mapping = AgentMCPAccess(agent_unique_id=agent_uid, mcp_unique_id=server_id)
            mapping.save()
            
            manifest = AIActionService.get_action_manifest(agent_unique_id=agent_uid)
            
            self.assertIn('mcp_resources', manifest)
            self.assertTrue(len(manifest['mcp_resources']) > 0)
            res_entry = manifest['mcp_resources'][0]
            self.assertEqual(res_entry['uri'], 'test://res1')
            self.assertEqual(res_entry['action_type'], 'mcp_resource_read')

    @patch('time.time')
    def test_cooldown_env_var(self, mock_time):
        """Scenario 3: Verify MCP_FAILURE_COOLDOWN env var is respected."""
        # 1. Mock config value (it's already loaded at import, so we patch the service's use)
        # However, MCPBridgeService uses the imported constant.
        
        with patch('aot.ai.services.mcp_bridge_service.MCP_FAILURE_COOLDOWN_SECONDS', 10):
            server_id = "fail_server"
            
            # Simulate failure at t=0
            mock_time.return_value = 1000.0
            MCPBridgeService._failed_servers[server_id] = 1000.0
            
            # At t=1005 (5s elapsed < 10s cooldown), should return None
            mock_time.return_value = 1005.0
            proc = MCPBridgeService.get_server_process(server_id)
            self.assertIsNone(proc)
            
            # At t=1011 (11s elapsed > 10s cooldown), should attempt to start (fail because server doesn't exist in DB)
            mock_time.return_value = 1011.0
            proc = MCPBridgeService.get_server_process(server_id)
            # It returns None because it fails to start, but the important thing is 
            # it's no longer in _failed_servers
            self.assertNotIn(server_id, MCPBridgeService._failed_servers)

if __name__ == '__main__':
    unittest.main()
