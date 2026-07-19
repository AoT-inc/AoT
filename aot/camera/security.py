"""
Camera security module: RBAC, audit logging, and credential management.
"""
import logging
import time
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class Permission(Enum):
    """Camera operation permissions."""
    VIEW_STREAM = "view_stream"
    CAPTURE = "capture"
    CONFIGURE = "configure"
    DELETE = "delete"
    PTZ_CONTROL = "ptz_control"
    MANAGE_TIMELAPSE = "manage_timelapse"


class Role(Enum):
    """User roles for camera access."""
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


# Role → Permission mapping
ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
    Role.VIEWER: [Permission.VIEW_STREAM],
    Role.OPERATOR: [
        Permission.VIEW_STREAM,
        Permission.CAPTURE,
        Permission.PTZ_CONTROL,
        Permission.MANAGE_TIMELAPSE,
    ],
    Role.ADMIN: list(Permission),  # All permissions
}


@dataclass
class AuditEntry:
    """A single audit log entry."""
    timestamp: float
    user_id: str
    operation: str
    resource: str
    success: bool
    detail: str = ""


class SecurityManager:
    """Manage role-based access control and audit logging for camera operations.

    @phase active
    @stability stable
    """

    def __init__(self):
        self._audit_log: List[AuditEntry] = []

    def check_permission(self, user_id: str, role: Role, permission: Permission) -> bool:
        """Check if a role has the required permission."""
        allowed = permission in ROLE_PERMISSIONS.get(role, [])
        if not allowed:
            self._log_security_event(user_id, permission.value, "permission_denied")
            logger.warning(f"Permission denied: user={user_id}, role={role.value}, perm={permission.value}")
        return allowed

    def record_audit(self, user_id: str, operation: str, resource: str, success: bool, detail: str = "") -> None:
        """Record an auditable camera operation."""
        entry = AuditEntry(
            timestamp=time.time(),
            user_id=user_id,
            operation=operation,
            resource=resource,
            success=success,
            detail=detail,
        )
        self._audit_log.append(entry)
        logger.info(f"Audit: user={user_id} op={operation} resource={resource} ok={success}")

    def get_audit_log(self, user_id: Optional[str] = None, limit: int = 100) -> List[AuditEntry]:
        """Retrieve audit log entries, optionally filtered by user."""
        entries = self._audit_log
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        return entries[-limit:]

    def _log_security_event(self, user_id: str, operation: str, reason: str) -> None:
        """Record a security event (unauthorized access attempt)."""
        self.record_audit(
            user_id=user_id,
            operation=operation,
            resource="security",
            success=False,
            detail=f"reason={reason}",
        )
