# coding=utf-8
# @ANCHOR: BASE_ACTION_RESOLVER
"""
BaseActionResolver — Abstract base class for all action resolvers.
Ref: SBS-002_V2_STRATEGY (pluggable_resolver.base_class)
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseActionResolver(ABC):
    """
    Abstract base class for all action resolvers.
    Every concrete resolver must implement execute().
    The registry calls execute() after routing the action_type.

    @phase active
    @stability stable
    """

    @abstractmethod
    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the action and return a standard result dict.

        Args:
            action_type: Normalised action type string.
            target_id:   Resolved target unique_id (may be None for some types).
            params:      Action parameters dict.
            context:     Optional ambient context dict from the reasoning engine.
            approved:    True only when the call originates from a human-confirmed
                         or pre-approved scheduler path (Law 3 / PC-089-GATE).

        Returns:
            {'status': 'success'|'error', 'result'|'message': ...}
        """
        ...
