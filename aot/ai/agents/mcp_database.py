from flask_babel import lazy_gettext as lg

AI_INFORMATION = {
    "engine_type": "mcp_database",
    "ai_manufacturer": "MCP",
    "ai_name": "DB Explorer MCP",
    "ai_name_unique": "mcp_database",
    "description": lg("Analyzes data by querying PostgreSQL/SQLite databases using natural language."),
    "system_prompt": "You are a Database Expert. Your goal is to help users query and analyze stored data. Use the provided database tools to explore tables and execute read-only queries. Always explain your findings clearly.",
    "is_mcp": True,
    "default_command": "npx -y @modelcontextprotocol/server-postgres",
    "auth_methods": ["no_auth"],
    "auth_link": "https://www.postgresql.org/docs/",
    "models": [
        {"label": "PostgreSQL", "value": "postgres"},
        {"label": "SQLite", "value": "sqlite"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "db_url", "name": "Database URL (Connection String)", "type": "text", "default": "postgres://user:pass@localhost:5432/db", "is_cmd_arg": True},
        {"id": "database_type", "name": "DB Type", "type": "select", "options": ["sqlite", "postgres"], "default": "sqlite"}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class DatabaseMCP_AI(BaseMCP_AI):
    """
    Database Expert MCP agent for natural language SQL exploration.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "Natural Language SQL Data exploration (Postgres/SQLite)"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
        pass
