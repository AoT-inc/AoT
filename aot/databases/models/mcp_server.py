# coding=utf-8
import json
import logging
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime
from datetime import datetime
from aot.aot_flask.extensions import db

# Base imports for AoT models
def utc_now():
    return datetime.utcnow()

class CRUDMixin(object):
    """Mixin that adds convenience methods for CRUD operations."""
    def save(self, commit=True):
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def delete(self, commit=True):
        db.session.delete(self)
        if commit:
            db.session.commit()
        return True

logger = logging.getLogger(__name__)

class MCPServer(db.Model, CRUDMixin):
    """
    Model for storing External MCP Server configurations.
    Enables AI agents to interact with external tools (Grafana, DBs, etc.) via MCP.
    """
    __tablename__ = 'mcp_servers'

    id = Column(Integer, primary_key=True)
    unique_id = Column(String(50), unique=True, index=True) # UUID or similar
    name = Column(String(100), nullable=False)
    
    # Execution command (e.g., "npx @modelcontextprotocol/server-memory")
    command = Column(String(500), nullable=False)
    
    # Store environmental variables as JSON string
    env_json = Column(Text, default='{}')
    
    # Scope/Purpose: 'general' (alway in manifest) or 'specific' (lazy load)
    scope = Column(String(20), default='general')
    
    # Custom options for UI flexibility (Specific purpose descriptions, etc.)
    custom_options_json = Column(Text, default='{}')

    # GridStack Layout properties
    position_x = Column(Integer, default=0)
    position_y = Column(Integer, default=0)
    width = Column(Integer, default=24)
    height = Column(Integer, default=1)

    is_activated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __init__(self, **kwargs):
        super(MCPServer, self).__init__(**kwargs)
        if not self.unique_id:
            import uuid
            self.unique_id = str(uuid.uuid4())

    def __repr__(self):
        return f"<MCPServer(id={self.id}, name='{self.name}', scope='{self.scope}')>"

    @property
    def env_vars(self):
        try:
            return json.loads(self.env_json) if self.env_json else {}
        except Exception:
            return {}

    @env_vars.setter
    def env_vars(self, value):
        self.env_json = json.dumps(value)

    @property
    def custom_options(self):
        try:
            return json.loads(self.custom_options_json) if self.custom_options_json else {}
        except Exception:
            return {}

    @custom_options.setter
    def custom_options(self, value):
        self.custom_options_json = json.dumps(value)


class AgentMCPAccess(db.Model, CRUDMixin):
    """
    v6: Many-to-Many mapping between AI Agents and MCP Servers.
    Decouples the previous 1:1 binding (Agent.unique_id == MCPServer.unique_id).
    """
    __tablename__ = 'agent_mcp_access'

    id = Column(Integer, primary_key=True)
    agent_unique_id = Column(String(36), nullable=False, index=True)
    mcp_unique_id = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)
    # v23 (MCP_T09): Per-tool whitelisting. JSON array of tool names.
    # None = all tools permitted (backward compatible with existing rows).
    allowed_tools = Column(Text, default=None)

    __table_args__ = (
        db.UniqueConstraint('agent_unique_id', 'mcp_unique_id', name='uq_agent_mcp'),
    )

    @property
    def allowed_tool_list(self):
        """Returns list of allowed tool names, or None if all tools permitted."""
        if self.allowed_tools is None:
            return None
        try:
            return json.loads(self.allowed_tools)
        except (json.JSONDecodeError, TypeError):
            return None

    def __repr__(self):
        return f"<AgentMCPAccess(agent={self.agent_unique_id}, mcp={self.mcp_unique_id})>"
