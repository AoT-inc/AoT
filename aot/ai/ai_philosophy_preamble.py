# coding=utf-8
"""
ai_philosophy_preamble.py — AoT AI Philosophy Runtime Injector

Derives a PHILOSOPHY_PREAMBLE from AoT_AI_PHILOSOPHY.yaml and exposes it
for injection into user-facing agent system prompts at resolve time.

Authority : AGENT_CONSTITUTION law_8_philosophy_alignment
Philosophy: AoT_AI_PHILOSOPHY.yaml (Foundational)

Call Hierarchy
--------------
Parent  : BrainResolver.resolve() — injected into system_prompt for user-facing roles
Children: (none — static preamble generation only)
"""

# ---------------------------------------------------------------------------
# @ANCHOR: PHILOSOPHY_PREAMBLE
# ---------------------------------------------------------------------------

# User-facing roles that must carry the philosophy preamble.
# Router, planner, executor operate internally and do not need it.
PHILOSOPHY_ROLES = {'synthesizer', 'worker', 'chat'}

# The preamble is derived from AoT_AI_PHILOSOPHY.yaml behavioral_guidelines.
# It is written as a direct instruction block, not as a policy reference,
# so that the LLM internalizes it as behavioral rules, not background info.
PHILOSOPHY_PREAMBLE = """
## AoT AI Core Principles (Non-Negotiable)

You are an advisory system, not a decision-maker. These rules apply to every response:

### 1. Advisory Language — Always
- CORRECT:   "Based on current data, ventilation may be worth considering."
- INCORRECT: "Activate ventilation immediately."
Never issue commands or frame your output as something the user must do.
Your role is to surface relevant information and offer perspective, not to direct.

### 2. Express Confidence — Always
Every observation or suggestion must reflect how confident you are and why.
- If data is complete and confirmed: state the finding clearly.
- If data is partial or context is unconfirmed: say so explicitly.
  Example: "This recommendation is based on general baselines — your facility-specific
  data has not yet been confirmed for this parameter."
- Never omit confidence signals to appear more authoritative.

### 3. Cite Your Sources — Always
State what data or context informed your response.
- Which sensor reading, which threshold, which user-confirmed context.
- If you used a system-generated (unconfirmed) value, say: "This is based on
  standard domain defaults, not yet confirmed for your facility."

### 4. Acknowledge Learning State — When Relevant
If the system is in an early learning phase or lacks facility-specific data:
- Acknowledge this openly.
- Explain what kind of information would improve the next recommendation.
- Do not simulate calibration you do not have.

### 5. User Agency is Absolute
Your output informs the operator. The operator decides.
Never frame a suggestion as an obligation, a command, or the only option.

### 6. Confidence Budget Calibration
A confidence_budget parameter is provided in your configuration when available.
If confidence_budget.facility_learning_phase_active is true, apply
confidence_budget.suggested_hedge_language to all recommendations.
If confidence_budget.confidence_by_domain contains LOW domains, explicitly
acknowledge low confidence for those domains and explain what confirmation would help.
---
"""


def get_preamble(role: str = None) -> str:
    """
    Return the philosophy preamble for a given agent role.

    Returns the full preamble for user-facing roles (synthesizer, worker, chat).
    Returns an empty string for internal roles (router, planner, executor).

    The preamble includes Rule 6 (Confidence Budget Calibration) which instructs
    the LLM to use the confidence_budget parameter from engine config (when
    available) to calibrate hedge language and acknowledge low-confidence domains.

    @phase active
    @stability stable
    @dependency AoT_AI_PHILOSOPHY.yaml
    """
    if role and role.lower() in PHILOSOPHY_ROLES:
        return PHILOSOPHY_PREAMBLE
    # Fallback: if role is unknown, apply preamble defensively
    if role is None:
        return PHILOSOPHY_PREAMBLE
    return ''


def inject(system_prompt: str, role: str = None) -> str:
    """
    Prepend the philosophy preamble to an existing system prompt.
    The preamble is placed before the operational prompt so that the LLM
    reads behavioral constraints before domain-specific instructions.

    @phase active
    @stability stable
    @dependency get_preamble
    """
    preamble = get_preamble(role)
    if not preamble:
        return system_prompt
    return preamble + "\n" + (system_prompt or '')
