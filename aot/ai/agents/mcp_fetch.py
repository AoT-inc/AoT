from flask_babel import lazy_gettext as lg

AI_INFORMATION = {
    "engine_type": "mcp_fetch",
    "ai_manufacturer": "MCP",
    "ai_name": "Web Explorer MCP",
    "ai_name_unique": "mcp_fetch",
    "description": lg("Collects real-time information by directly reading or exploring web page content."),
    "system_prompt": "You are a Web Research Expert. Your goal is to fetch web content from provided URLs and distill it into relevant information. Use the fetch tools to gather data and provide accurate summaries based on the raw content.",
    "is_mcp": True,
    "default_command": "npx -y @modelcontextprotocol/server-fetch",
    "auth_methods": ["no_auth"],
    "auth_link": "https://pptr.dev/",
    "models": [
        {"label": "Fetch (Simple)", "value": "fetch"},
        {"label": "Puppeteer (Full)", "value": "puppeteer"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "browser", "name": "Browser", "type": "select", "options": ["puppeteer", "playwright"], "default": "puppeteer"},
        {"id": "headless", "name": "Headless", "type": "boolean", "default": True}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class FetchMCP_AI(BaseMCP_AI):
    """
    Web Explorer MCP agent for content crawling and analysis.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "Web Content Crawling & Analysis (Puppeteer)"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
