# coding=utf-8
from dataclasses import dataclass
from aot.ai.engine_boot_config import EngineBootConfig
from aot.ai.ai_philosophy_preamble import inject as philosophy_inject
from aot.aot_flask.extensions import db
import logging

logger = logging.getLogger(__name__)

@dataclass
class EngineContext:
    """
    Context container for a resolved AI engine.

    @phase active
    @stability stable
    """
    provider: str
    model_name: str
    engine_instance: object  # AbstractAI instance

class BrainResolver:
    """
    Service to resolve AI engine instances using the Skeleton (Identity) layer.
    Ensures that engine initialization is decoupled from DB sessions to prevent
    identity pollution/shallow-copy bugs.

    @phase active
    @stability stable
    @dependency AIAgentService, AIEntry, AIAgentSkeleton, AIFacilityLearning
    """
    @staticmethod
    def resolve(skeleton_id: str, preferred_entry_id: str = None) -> EngineContext:
        from aot.ai.services.ai_agent_service import ENGINE_REGISTRY
        from aot.databases.models.ai import AIEntry, AIAgent
        from aot.databases.models.ai_skeleton import AIAgentSkeleton

        with db.session.no_autoflush:
            # 1. Resolve target entry (read-only)
            entry = None
            if preferred_entry_id:
                entry = AIEntry.query.filter_by(unique_id=preferred_entry_id).first()
            if not entry:
                entry = BrainResolver._find_best_entry()
            
            if not entry:
                logger.error(f"[BrainResolver] Could not resolve any AIEntry for skeleton {skeleton_id}")
                return None

            # 2. Load skeleton scalars (read-only)
            skeleton = AIAgentSkeleton.query.filter_by(unique_id=skeleton_id).first()
            name = skeleton.display_name if skeleton else 'Unknown Agent'
            
            # Behavior scalars from original agent (if available)
            agent = AIAgent.query.filter_by(unique_id=skeleton_id).first()
            temperature = agent.temperature if agent else 0.7
            max_tokens = agent.max_tokens if agent else 2048
            model_tier = agent.model_tier if agent else 'standard'
            
            system_prompt = skeleton.system_prompt if skeleton else ''
            custom_options = skeleton.custom_options_json if skeleton else '{}'

            # law_8_philosophy_alignment: Inject philosophy preamble for user-facing roles.
            # pipeline_role is read from the agent record; defaults to 'worker' (preamble applies).
            pipeline_role = agent.pipeline_role if agent else 'worker'
            system_prompt = philosophy_inject(system_prompt, role=pipeline_role)

            # v3.1 Phase 3: append active enforcement/learned rule fragments after
            # the constitution (philosophy preamble). Flag-gated inside; no-op for
            # internal roles / flag off / no active rules. Never raises.
            try:
                from aot.ai.services.rule_service import inject_rules
                system_prompt = inject_rules(system_prompt, role=pipeline_role)
            except Exception:
                pass

            # Phase 3: Derive confidence_budget from facility learning state.
            # Injected into engine config so the AI can calibrate its language.
            # Fails gracefully — no exception if AIFacilityLearning record absent.
            confidence_budget = None
            try:
                from aot.databases.models.ai_facility_learning import AIFacilityLearning
                import json as _json_cb
                # Resolve facility_id from the agent's linked facility (if any)
                _facility_id = getattr(agent, 'facility_id', None) if agent else None
                if _facility_id:
                    fl_record = AIFacilityLearning.query.filter_by(
                        facility_id=_facility_id
                    ).first()
                    if fl_record:
                        # Parse confirmations_json for per-domain confidence
                        _confirmations = {}
                        try:
                            _confirmations = _json_cb.loads(
                                fl_record.confirmations_json or '{}'
                            )
                        except (ValueError, TypeError):
                            pass

                        confidence_by_domain = {}
                        for domain, counts in _confirmations.items():
                            if isinstance(counts, dict):
                                confirmed = counts.get('confirmed', 0)
                                total = counts.get('total', 1)
                                ratio = confirmed / max(total, 1)
                                if ratio >= 0.7:
                                    confidence_by_domain[domain] = "HIGH"
                                elif ratio >= 0.3:
                                    confidence_by_domain[domain] = "MEDIUM"
                                else:
                                    confidence_by_domain[domain] = "LOW"

                        # Find lowest-confidence domain for hedge language
                        lowest_domains = [
                            d for d, c in confidence_by_domain.items()
                            if c == "LOW"
                        ]
                        if not lowest_domains:
                            lowest_domains = [
                                d for d, c in confidence_by_domain.items()
                                if c == "MEDIUM"
                            ]
                        suggested_hedge = ""
                        if lowest_domains:
                            suggested_hedge = (
                                f"Note: recommendations for {', '.join(lowest_domains[:2])} "
                                f"are based on limited facility-specific data."
                            )

                        confidence_budget = {
                            "facility_learning_phase_active": bool(
                                fl_record.learning_phase_active
                            ),
                            "total_confirmations": fl_record.feedback_count_total or 0,
                            "confidence_by_domain": confidence_by_domain,
                            "suggested_hedge_language": suggested_hedge,
                        }
            except Exception as _cb_exc:
                logger.debug(
                    "[BrainResolver] confidence_budget derivation skipped: %s",
                    _cb_exc
                )

            # Merge confidence_budget into custom_options for engine access
            if confidence_budget:
                try:
                    import json as _json_merge
                    _opts = _json_merge.loads(custom_options or '{}')
                    _opts['confidence_budget'] = confidence_budget
                    custom_options = _json_merge.dumps(_opts, ensure_ascii=False)
                except Exception:
                    pass  # Preserve original custom_options on merge failure

            # 3. Build detached config — no session reference forwarded
            clean_config = EngineBootConfig(
                unique_id=skeleton_id,
                name=name,
                model_type=entry.model_type,
                api_key=entry.api_key,
                model_name=entry.model_name,
                api_endpoint=entry.api_endpoint,
                auth_type=entry.auth_type,
                auth_id=entry.auth_id,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model_tier=model_tier,
                custom_options_json=custom_options,
            )

        # 4. Instantiate engine outside no_autoflush block
        target_type = entry.model_type
        registry_entry = ENGINE_REGISTRY.get(target_type) or ENGINE_REGISTRY.get('gemini')
        if not registry_entry:
            logger.error(f"[BrainResolver] No engine registered for type: {target_type}")
            return None
            
        engine_class, _ = registry_entry
        try:
            engine = engine_class(clean_config)
            return EngineContext(
                provider=entry.model_type,
                model_name=entry.model_name,
                engine_instance=engine,
            )
        except Exception as e:
            logger.error(f"[BrainResolver] Failed to instantiate engine {target_type}: {e}")
            return None

    @staticmethod
    def _find_best_entry():
        from aot.databases.models.ai import AIEntry
        # v2.4: Skip MCP specialty entries when searching for a 'Reasoning Brain'
        # v2.5: Fallback to any non-mcp entry with an API key if no activated entry found
        entry = AIEntry.query.filter(
            AIEntry.is_activated == True,
            ~AIEntry.model_type.startswith('mcp_')
        ).first()
        if entry:
            return entry
        # Fallback: find any non-mcp entry that has an API key configured
        return AIEntry.query.filter(
            ~AIEntry.model_type.startswith('mcp_'),
            ~AIEntry.model_type.in_(['ai_router']),
            AIEntry.api_key != None,
            AIEntry.api_key != ''
        ).first()
