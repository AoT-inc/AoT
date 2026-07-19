# coding=utf-8
import logging
from datetime import datetime
from aot.ai.services.ai_context_service import AIContextService
from aot.ai.services.ai_action_service import AIActionService

logger = logging.getLogger(__name__)

class AIReasoningService:
    """
    Orchestrator for the AI reasoning loop:
    1. Observe (Fetch Context)
    2. Understand (Match with Manifest/Capabilities)
    3. Reason (Synthesize Analysis & Propose Actions)
    4. Act (Execute Actions - optional based on UI)

    @phase active
    @stability unstable
    @dependency AIContextService, AIActionService, AIAgentService
    """

    @staticmethod
    def run_reasoning_cycle(goal="Optimize system for energy efficiency and resource health", agent_id=None):
        """
        Performs a reasoning cycle using the new Agent framework if agent_id is provided,
        otherwise falls back to the default system agent.
        """
        try:
            from aot.ai.services.ai_agent_service import AIAgentService
            from aot.databases.models import AIAgent

            # 1. Resolve Agent
            if not agent_id:
                # Fallback: Use the first active agent as default
                default_agent = AIAgent.query.filter_by(is_activated=True).first()
                if default_agent:
                    agent_id = default_agent.unique_id
            
            # 2. Execute via Agent Framework if available
            if agent_id:
                logger.info(f"Executing reasoning via Agent: {agent_id}")
                return AIAgentService.run_agent_reasoning(agent_id, goal)

            # 3. LEGACY/MOCK FALLBACK (Phase 4 compatibility)
            logger.warning("No AI Agent found. Falling back to legacy mock reasoning.")
            context = AIContextService.get_master_context()
            if "error" in context:
                return {"status": "error", "message": "Failed to fetch system context"}

            manifest = AIActionService.get_action_manifest(agent_unique_id=agent_id)
            proposal = AIReasoningService._generate_mock_proposal(context, goal)

            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "goal": goal,
                "current_state_summary": AIReasoningService._summarize_context(context),
                "reasoning_insight": proposal["insight"],
                "proposed_actions": proposal["actions"],
                "manifest_ref": manifest
            }

        except Exception as e:
            logger.exception("Error in AI reasoning cycle")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _summarize_context(ctx):
        """Creates a human-readable summary of the system state for initial verification."""
        total_energy = sum(e['usage_kwh']['day'] for e in ctx.get('input_energy_summary', []))
        total_water = sum(s['value'] for s in ctx.get('supply_resource_summary', []) if s['type'] == 'moisture')
        
        return {
            "spatial_nodes": len(ctx.get('spatial_hierarchy', [])),
            "active_cameras": len(ctx.get('cameras', [])),
            "total_daily_power_kwh": total_energy,
            "total_water_supply_l": total_water
        }

    @staticmethod
    def _generate_mock_proposal(ctx, goal):
        """
        Generates a mock proposal for Phase 3 verification.
        Reflects how an LLM would interpret the data.
        """
        # Example heuristic-based mock reasoning
        energy_summary = sum(e['usage_kwh']['day'] for e in ctx.get('input_energy_summary', []))
        
        insight = "System state is stable."
        actions = []

        if energy_summary > 100:
             insight = "Daily energy consumption is high. Consider deactivating non-essential HVAC units."
             actions.append({
                 "action_type": "output",
                 "target_id": "hvac_01", # Should match actual IDs in real context
                 "description": "Deactivate secondary HVAC unit to reduce load",
                 "params": {"state": "off"}
             })
        
        water_supply = sum(s['value'] for s in ctx.get('supply_resource_summary', []) if s['type'] == 'moisture')
        if water_supply < 10:
            insight += " Soil moisture levels in Greenhouse A might be low. Suggest irrigation cycle."
            actions.append({
                 "action_type": "function",
                 "target_id": "greenhouse_irrigation_function",
                 "description": "Trigger scheduled irrigation for Greenhouse A",
                 "params": {}
            })

        return {
            "insight": insight,
            "actions": actions
        }
