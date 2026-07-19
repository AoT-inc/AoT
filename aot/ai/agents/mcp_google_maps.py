# coding=utf-8

from flask_babel import lazy_gettext as lg

AI_INFORMATION = {
    "engine_type": "mcp_google_maps",
    "ai_manufacturer": "MCP",
    "ai_name": "GIS Expert MCP",
    "ai_name_unique": "mcp_google_maps",
    "description": lg("Provides location-based information and geographical analysis using Google Maps data."),
    "is_mcp": True,
    "default_command": "npx -y @modelcontextprotocol/server-google-maps",
    "auth_methods": ["api_key"],
    "auth_link": "https://console.cloud.google.com/google/maps-apis/credentials",
    "models": [
        {"label": "Places API", "value": "places"},
        {"label": "Search API", "value": "search"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "options": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
        {"id": "google_maps_api_key", "name": "Google Maps API Key", "type": "password", "default": "", "env_var": "GOOGLE_MAPS_API_KEY"},
        {"id": "radius", "name": "Search Radius (m)", "type": "int", "default": 1000},
        {"id": "poi_type", "name": "POI Type", "type": "text", "default": "restaurant"}
    ]
}

from aot.ai.agents.mcp_base import BaseMCP_AI

class GoogleMapsMCP_AI(BaseMCP_AI):
    """
    GIS Expert MCP agent using Google Maps data.

    @phase active
    @stability stable
    @dependency BaseMCP_AI, MCPBridgeService
    """
    MCP_SPECIALTY = "GIS Data Augmentation & Location Intelligence (Google Maps)"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
