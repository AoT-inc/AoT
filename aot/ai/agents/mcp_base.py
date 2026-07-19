# coding=utf-8
import logging
import json
from aot.ai.agents.base_ai import AbstractAI

logger = logging.getLogger(__name__)

class BaseMCP_AI(AbstractAI):
    """
    Base class for MCP-specialized agents.
    Does NOT inherit from a specific engine (like Gemini).
    Instead, it wraps an internal LLM engine for reasoning,
    while maintaining its specialized MCP identity.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    def __init__(self, agent_config):
        super().__init__(agent_config)
        
        # 1. Determine which LLM brain to use for reasoning
        # v16: reasoning_entry_id allows using an existing AI Service Entry as the brain.
        try:
            options = json.loads(agent_config.custom_options_json) if agent_config.custom_options_json else {}
        except:
            options = {}
            
        self.reasoning_entry_id = options.get('reasoning_entry_id', '')
        self.llm_provider = options.get('llm_provider', 'gemini') # Fallback for old configs
        self.llm_model = options.get('llm_model', '') # Optional override
        
        # 2. Instantiate the internal reasoning engine
        # Pass the original agent_config but we will proxy the entry for the brain
        self._brain = self._init_brain(agent_config)
        
        # 3. Specialized system prompt setup
        specialty = getattr(self, 'MCP_SPECIALTY', 'General Tool Assistance')
        mcp_id = agent_config.unique_id # Linked by sharing the same unique_id
        
        self.mcp_instruction = (
            f"\n\n### [Specialist Context: MCP Server] ###\n"
            f"You are a specialized expert in: {specialty}\n"
            f"You have direct access to a dedicated MCP Server (ID: {mcp_id}).\n"
            f"When the user asks for actions related to your specialty, you MUST prefer using tools "
            f"provided by your MCP server via 'mcp_tool_call' with 'target_id'='{mcp_id}'.\n"
        )
        
        # Inject mcp instruction into the brain's system prompt
        if self._brain:
            orig_system = self._brain.system_prompt or ""
            if self.mcp_instruction not in orig_system:
                self._brain.system_prompt = orig_system + self.mcp_instruction

    def _init_brain(self, agent_config):
        """Helper to get the appropriate engine class based on selected reasoning brain via BrainResolver."""
        from aot.ai.services.brain_resolver import BrainResolver
        brain_ctx = BrainResolver.resolve(
            skeleton_id=agent_config.unique_id,
            preferred_entry_id=self.reasoning_entry_id
        )
        if not brain_ctx:
            return None
            
        engine = brain_ctx.engine_instance
        
        # v12.2: Ensure brain uses a valid LLM model name.
        if not self.llm_model:
            if engine.model_name in ['places', 'default', 'virtual_mcp', 'mcp_influxdb']:
                engine.model_name = brain_ctx.model_name
        else:
            engine.model_name = self.llm_model
            
        return engine

    def run_reasoning(self, context, goal):
        """Delegates reasoning to the internal brain."""
        if not self._brain:
            return {"insight": "Reasoning brain not initialized for MCP agent.", "actions": []}
        
        logger.info(f"[{self.__class__.__name__}] Delegating reasoning to brain...")
        return self._brain.run_reasoning(context, goal)

    def parse_actions(self, raw_response):
        """Delegates action parsing to the internal brain."""
        if not self._brain:
            return []
        return self._brain.parse_actions(raw_response)
