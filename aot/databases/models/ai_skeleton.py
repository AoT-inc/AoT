# coding=utf-8
from datetime import datetime
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import validates
from aot.databases import db, set_uuid, CRUDMixin

class ImmutableFieldError(Exception):
    """Raised when an immutable field is modified."""
    pass

class AIAgentSkeleton(CRUDMixin, db.Model):
    """
    Layer 1 (Skeleton) — The immutable identity of an AI Agent.
    Physical Truth: If it's not in the Skeleton, it doesn't exist.
    Ref: SBS-002_V2_STRATEGY (layer_1_skeleton.tables[AIAgentSkeleton])

    @phase active
    @stability stable
    """
    __tablename__ = "ai_agent_skeleton"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    display_name = db.Column(db.String(100), nullable=False)
    
    # Immutable Identity Fields (Guard enforced)
    agent_type = db.Column(db.String(20), nullable=False)   # llm / mcp_virtual / mcp_external / router
    is_mcp = db.Column(db.Boolean, nullable=False, default=False)
    
    # Metadata & Config
    mcp_tool_registry_json = db.Column(db.Text, default='[]')
    authority_level = db.Column(db.Integer, default=1)
    system_prompt = db.Column(db.Text, default='')
    custom_options_json = db.Column(db.Text, default='{}')
    
    is_activated = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @validates('agent_type', 'is_mcp')
    def _guard_immutable(self, key, value):
        """
        089 C-001 Immutability Guard.
        sa_inspect(self).transient is True only before db.session.add().
        This prevents mutation after the record is tied to a database identity.
        """
        if not sa_inspect(self).transient:
            raise ImmutableFieldError(
                f"Field '{key}' is immutable after session registration."
            )
        return value

    def __repr__(self):
        return f"<AIAgentSkeleton(name={self.display_name}, type={self.agent_type})>"
