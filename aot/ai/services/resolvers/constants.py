# coding=utf-8
# @ANCHOR: PHYSICAL_TOOLS_REGISTRY
"""
Shared physical tool constants.
Centralised here so PhysicalControlResolver, ActionResolverRegistry, and
SafetyService all reference the same frozenset — prevents drift.

Ref: 008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT (physical_tools_constant.migration)
"""

PHYSICAL_TOOLS: frozenset = frozenset({
    'operate_device',
    'output_on',
    'output_off',
    'set_output',
    'control_output',
    # set_output_state is the MCP-facing native tool; mcp_safety_gate.PHYSICAL_TOOLS
    # already gates it, but this set is what the PC-089 gate in execute_action
    # consults for mcp_tool_call/virtual_tool_call. It was missing here, so the two
    # sets had drifted despite the "prevents drift" note above. Not currently
    # reachable that way (no handler in build_tool_map()), so adding it is a no-op
    # today — and it stays gated the day someone does wire a handler up.
    'set_output_state',
    # Add new physical tools here only — never inline elsewhere
})
