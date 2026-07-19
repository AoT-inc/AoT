"""Sync AI agent system prompts with role preset definitions."""
import os
import sys

print("--- SCRIPT RUNNING ---")

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.aot_flask.app import create_app
from aot.databases.models import db, AIAgent
from aot.ai.services.ai_agent_service import AIAgentService

def sync_agent_prompts():
    """Overwrite agent system prompts with latest role preset values.

    Iterates all AIAgent rows and updates system_prompt from
    AIAgentService.get_role_presets() when a mismatch is detected.

    @phase setup
    @stability stable
    @dependency AIAgent, AIAgentService
    """
    print("Initializing Flask App...")
    app = create_app()
    with app.app_context():
        from flask import current_app
        print(f"--- Syncing AI Agent Prompts with Phase 30 Rules ---")
        print(f"Database URI: {current_app.config.get('SQLALCHEMY_DATABASE_URI')}")
        
        presets = AIAgentService.get_role_presets()
        agents = AIAgent.query.all()
        print(f"Found {len(agents)} agents in database.")
        
        updated_count = 0
        for agent in agents:
            role = agent.pipeline_role or agent.role
            print(f"Checking agent '{agent.name}' (Role: {role})...")
            if role in presets:
                preset = presets[role]
                new_prompt = preset.get('system_prompt')
                
                if new_prompt and agent.system_prompt != new_prompt:
                    print(f"Updating prompt for '{agent.name}'...")
                    agent.system_prompt = new_prompt
                    updated_count += 1
                else:
                    print(f"Prompt for '{agent.name}' is already up-to-date.")
            else:
                print(f"No preset found for role '{role}'. Skipping.")
        
        if updated_count > 0:
            db.session.commit()
            print(f"SUCCESS: {updated_count} agents updated.")
        else:
            print("No updates needed. All agents already match presets.")

if __name__ == "__main__":
    sync_agent_prompts()
