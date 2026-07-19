# coding=utf-8

from flask_babel import lazy_gettext as lg

AI_INFORMATION = {
    "engine_type": "mcp_iotdb",
    "ai_manufacturer": "MCP",
    "ai_name": "IoTDB Navigator MCP",
    "ai_name_unique": "mcp_iotdb",
    "description": lg("Performs precise analysis of large-scale time-series sensor data stored in Apache IoTDB."),
    "is_mcp": True,
    "default_command": "npx -y @modelcontextprotocol/server-iotdb",
    "auth_methods": ["account"],
    "auth_link": "https://iotdb.apache.org/",
    "models": [
        {"label": "Standard", "value": "default"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "host", "name": "IoTDB Host", "type": "text", "default": "localhost"},
        {"id": "port", "name": "IoTDB Port", "type": "int", "default": 6667}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class IoTDBMCP_AI(BaseMCP_AI):
    """
    IoTDB Navigator MCP agent for time-series sensor data analysis.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "Apache IoTDB Time-series Sensor Data Analysis"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
        pass
