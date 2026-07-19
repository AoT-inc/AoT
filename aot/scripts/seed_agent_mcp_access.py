"""
TASK_17 CM_3 — Agent MCP Access Seed Script
============================================
Document: 046_TASK_17_CLAUDE_AUDIT_AND_IMPLEMENTATION_PLAN.yaml
Authority: Local_RULES v2.4 / Law 6 (Verifiable Evidence)

PURPOSE:
    Inserts agent_mcp_access rows so all active AI agents can access the
    AoT System Expert Server for device control (operate_device).

ROOT CAUSE DIAGNOSED:
    fast_path in ai_agent_service.py falls back to first active agent
    (Planning Gemini, id=3) when no pipeline_role='worker' agent exists.
    _check_tool_access() denies call because no mapping exists for that agent.

CONSTRAINT:
    No manual DB edits — executed as a Flask-context script per Local_RULES.

USAGE:
    cd <INSTALL_DIRECTORY>
    python3 aot/scripts/seed_agent_mcp_access.py
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.aot_flask.app import create_app
from aot.databases import db
from aot.databases.models.mcp_server import AgentMCPAccess, MCPServer
from aot.databases.models.ai import AIAgent

AOT_EXPERT_SERVER_ID = '67d63a46-21c2-4127-b343-2e43376f49a3'

REQUIRED_MAPPINGS = [
    # (agent_unique_id, agent_name, mcp_unique_id, mcp_name)
    # Agents that must access AoT System Expert Server for operate_device
    ('2e34b06b-35e3-4d10-ad8b-15e0cbb97a8d', 'Planning Gemini',      AOT_EXPERT_SERVER_ID, 'AoT System Expert Server'),
    ('77635528-f5ee-4545-8887-9c421b609926', 'Execution Gemini',     AOT_EXPERT_SERVER_ID, 'AoT System Expert Server'),
    ('ab3fcf3e-cc71-4001-b3d5-22c621bcbf91', 'AoT System Expert',   AOT_EXPERT_SERVER_ID, 'AoT System Expert Server'),
    ('86d07f95-a80e-4c2d-8aa7-bef8d28e34ad', 'Intent Router',        AOT_EXPERT_SERVER_ID, 'AoT System Expert Server'),
    ('5e5fcc75-1ca7-431a-92db-7623bb4fb044',  'Synthesis Gemini',     AOT_EXPERT_SERVER_ID, 'AoT System Expert Server'),
]


def run_seed():
    """Seed agent_mcp_access rows for all active AI agents.

    Grants each configured agent access to the AoT System Expert Server
    so that tool calls like operate_device are authorized.

    @phase setup
    @stability stable
    @dependency AIAgent, AgentMCPAccess, MCPServer
    """
    app = create_app()
    with app.app_context():
        print("[SEED] Verifying AoT System Expert Server exists...")
        server = MCPServer.query.filter_by(unique_id=AOT_EXPERT_SERVER_ID).first()
        if not server:
            print(f"[SEED][ERROR] AoT System Expert Server not found in DB. Aborting.")
            sys.exit(1)
        print(f"[SEED] Found server: '{server.name}' (is_activated={server.is_activated})")

        inserted = 0
        skipped = 0
        for agent_uid, agent_name, mcp_uid, mcp_name in REQUIRED_MAPPINGS:
            agent = AIAgent.query.filter_by(unique_id=agent_uid).first()
            if not agent:
                print(f"[SEED][SKIP] Agent '{agent_name}' ({agent_uid[:8]}) not found in DB.")
                skipped += 1
                continue

            existing = AgentMCPAccess.query.filter_by(
                agent_unique_id=agent_uid,
                mcp_unique_id=mcp_uid
            ).first()

            if existing:
                print(f"[SEED][EXISTS] {agent_name} -> {mcp_name} (already mapped)")
                skipped += 1
            else:
                entry = AgentMCPAccess(
                    agent_unique_id=agent_uid,
                    mcp_unique_id=mcp_uid,
                    allowed_tools=None  # NULL = all tools permitted (backward compat)
                )
                db.session.add(entry)
                print(f"[SEED][INSERT] {agent_name} -> {mcp_name}")
                inserted += 1

        db.session.commit()
        print(f"\n[SEED] Complete. Inserted: {inserted}, Skipped/Existing: {skipped}")

        print("\n[SEED] Current agent_mcp_access mappings for AoT System Expert Server:")
        rows = AgentMCPAccess.query.filter_by(mcp_unique_id=AOT_EXPERT_SERVER_ID).all()
        for row in rows:
            agent = AIAgent.query.filter_by(unique_id=row.agent_unique_id).first()
            name = agent.name if agent else '(not found)'
            print(f"  agent='{name}' ({row.agent_unique_id[:8]}...) allowed_tools={row.allowed_tools}")


if __name__ == '__main__':
    run_seed()
