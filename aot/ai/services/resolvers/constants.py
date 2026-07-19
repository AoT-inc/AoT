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
    # Add new physical tools here only — never inline elsewhere
})
