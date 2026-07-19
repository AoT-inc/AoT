# coding=utf-8
import logging
from dataclasses import dataclass
from typing import Optional

from aot.ai.agents.ai_router import AIRouterAI, AI_INFORMATION as PARENT_INFO
from aot.config.feature_flags import capability_manager

logger = logging.getLogger(__name__)

@dataclass
class IntentVector:
    domain: str
    confidence: float
    requires_approval: bool
    proposed_resolver: str

AI_INFORMATION = PARENT_INFO.copy()
AI_INFORMATION.update({
    "engine_type": "symbolic_intent_router",
    "ai_name": "Symbolic Intent Router",
    "ai_name_unique": "symbolic_intent_router",
})

class SymbolicIntentRouter(AIRouterAI):
    """
    SymbolicIntentRouter: Extended router with domain-based capability gating.
    Classification axes: Execution Domain (DAEMON/LIBRARY) x Confidence.

    @phase active
    @stability experimental
    @dependency AIRouterAI, BrainResolver
    """

    _VALID_DOMAINS = frozenset(['DAEMON', 'LIBRARY'])
    
    _DOMAIN_MAPPING = {
        'CONTROL':         {'domain': 'DAEMON',  'proposed_resolver': 'device_controller',   'requires_approval': True},
        'SCHEDULE':        {'domain': 'DAEMON',  'proposed_resolver': 'schedule_manager',    'requires_approval': True},
        'COMPOSITE':       {'domain': 'DAEMON',  'proposed_resolver': 'orchestrator',        'requires_approval': True},
        'FUNCTION_CREATE': {'domain': 'DAEMON',  'proposed_resolver': 'function_creator',    'requires_approval': True},
        'DATA_QUERY':      {'domain': 'LIBRARY', 'proposed_resolver': 'data_query_handler',  'requires_approval': False},
        'CHAT':            {'domain': 'LIBRARY', 'proposed_resolver': 'chat_handler',        'requires_approval': False},
    }

    def run_reasoning(self, context, goal):
        """
        Overrides run_reasoning to add symbolic intent vector mapping and capability gating.
        """
        # 1. Capability Manager Guard
        if not capability_manager.is_enabled('INTENT_ROUTER'):
            logger.debug("[SymbolicRouter] Intent Router disabled by profile. Falling back to parent.")
            return super().run_reasoning(context, goal)

        # 2. Delegate classification to parent (AIRouterAI uses LLM/Brain)
        raw_result = super().run_reasoning(context, goal)
        
        # 3. Augment with Symbolic Intent Vector
        intent_type = raw_result.get('intent', 'DATA_QUERY').upper()
        vector = self._classify_to_vector(intent_type, raw_result.get('confidence', 0.0))
        
        if vector:
            raw_result['intent_vector'] = {
                'domain': vector.domain,
                'confidence': vector.confidence,
                'requires_approval': vector.requires_approval,
                'proposed_resolver': vector.proposed_resolver
            }
            logger.info(f"[SymbolicRouter] Augmented intent with vector: {vector.domain}")
            
        return raw_result

    def _classify_to_vector(self, intent_type: str, confidence: float) -> Optional[IntentVector]:
        config = self._DOMAIN_MAPPING.get(intent_type)
        if not config:
            # Default fallback for unknown intents
            config = self._DOMAIN_MAPPING['DATA_QUERY']
            
        return IntentVector(
            domain=config['domain'],
            confidence=confidence,
            requires_approval=config['requires_approval'],
            proposed_resolver=config['proposed_resolver']
        )

    def parse_actions(self, raw_response):
        """Pass-through to parent (always empty for router)."""
        return []
