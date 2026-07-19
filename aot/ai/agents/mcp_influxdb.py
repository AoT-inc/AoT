from flask_babel import lazy_gettext as lg
from aot.ai.agents.mcp_base import BaseMCP_AI

AI_INFORMATION = {
    "engine_type": "mcp_influxdb",
    "ai_manufacturer": "MCP",
    "ai_name": "InfluxDB Time-Series MCP",
    "ai_name_unique": "mcp_influxdb",
    "description": lg("Analyzes InfluxDB v2 time-series data and performs Flux queries."),
    "is_mcp": True,
    # Using @fastmcp-me/influxdb-mcp-server which is compatible with v2
    "default_command": "npx -y @fastmcp-me/influxdb-mcp-server",
    "auth_methods": ["api_key"],
    "auth_link": "https://docs.influxdata.com/influxdb/v2/admin/tokens/",
    "models": [
        {"label": "Standard Setup", "value": "default"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "influxdb_url", "name": "InfluxDB URL", "type": "text", "default": "http://localhost:8086", "env_var": "INFLUXDB_URL"},
        {"id": "influxdb_token", "name": "InfluxDB Token", "type": "password", "default": "", "env_var": "INFLUXDB_TOKEN"},
        {"id": "influxdb_org", "name": "Organization", "type": "text", "default": "aot", "env_var": "INFLUXDB_ORG"},
        {"id": "influxdb_bucket", "name": "Bucket", "type": "text", "default": "aot", "env_var": "INFLUXDB_BUCKET"}
    ]
}

class InfluxDBMCP_AI(BaseMCP_AI):
    """
    InfluxDB Time-Series MCP agent for Flux query analysis.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "InfluxDB Time-series data analysis and Flux querying"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
        pass
