from flask_babel import lazy_gettext as lg

AI_INFORMATION = {
    "engine_type": "mcp_excel",
    "ai_manufacturer": "MCP",
    "ai_name": "Excel Genie MCP",
    "ai_name_unique": "mcp_excel",
    "description": lg("Generates professional environmental reports in Excel based on analyzed data."),
    "system_prompt": "You are a Data Reporting Expert. Your mission is to organize environmental analysis results into structured Excel files and professional spreadsheets. Ensure every report is accurate and easy for humans to read.",
    "is_mcp": True,
    "default_command": "npx -y @modelcontextprotocol/server-excel",
    "auth_methods": ["no_auth"],
    "auth_link": "https://www.microsoft.com/en-us/microsoft-365/excel",
    "models": [
        {"label": "Standard", "value": "default"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "file_path", "name": "Excel Path", "type": "text", "default": "/data/report.xlsx"}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class ExcelMCP_AI(BaseMCP_AI):
    """
    Excel Genie MCP agent for environmental data report generation.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "Environmental Data Report Generation & Excel Analysis"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
