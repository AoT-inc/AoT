from flask_babel import lazy_gettext as lg

# coding=utf-8

AI_INFORMATION = {
    "engine_type": "mcp_grafana",
    "ai_manufacturer": "MCP",
    "ai_name": "Grafana Analyst MCP",
    "ai_name_unique": "mcp_grafana",
    "description": lg("Provides visual insights by analyzing Grafana dashboards and data, reporting on detected anomalies."),
    "is_mcp": True,
    "default_command": "npx -y @leval/mcp-grafana",
    "auth_methods": ["api_key"],
    "auth_link": "https://grafana.com/docs/grafana/latest/developers/http_api/auth/",
    "models": [
        {"label": "Standard Setup", "value": "default"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "grafana_url", "name": "Grafana URL", "type": "text", "default": "http://localhost:3000", "env_var": "GRAFANA_URL"},
        {"id": "grafana_token", "name": "Service Account Token", "type": "password", "default": "", "env_var": "GRAFANA_SERVICE_ACCOUNT_TOKEN"},
        {"id": "grafana_api_key", "name": "API Key (Legacy)", "type": "password", "default": "", "env_var": "GRAFANA_API_KEY"},
        {"id": "purpose", "name": "Purpose", "type": "text", "default": "Dashboard Data Analysis"}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class GrafanaMCP_AI(BaseMCP_AI):
    """
    Grafana Analyst MCP agent for dashboard data analysis.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "Grafana Dashboard Data Analysis & Anomaly Detection"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
